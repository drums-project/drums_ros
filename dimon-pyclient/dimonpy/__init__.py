    # -*- coding: utf-8 -*-

__version__ = "0.1.0"
__api__ = "1"
version_info = tuple([int(num) for num in __version__.split('.')])

__concurrency_impl = 'gevent' # single process, single thread
#__concurrency_impl = 'multiprocessing' # multiple processes

import re
import logging
import requests
if __concurrency_impl == "gevent":
    import zmq.green as zmq
    from gevent import Greenlet as Process
    from gevent.queue import Queue
    from gevent.event import Event
elif __concurrency_impl == "multiprocessing":
    import zmq
    from multiprocessing import Process
    from multiprocessing import Queue, Event
else:
    raise NotImplementedError("__concurrency_impl is not defined.")

import msgpack

# Python does not provide a clean way to create signelton objects
# All ASync stuff are part of the module's namespace directly.

__subs = dict()
callback_queue = Queue()

def spin_once():
    sub_key, data = callback_queue.get()
    try:
        callback, g = __subs[sub_key]
        callback(msgpack.loads(data))
    except KeyError:
        logging.error("Subscription key in Queue does not exist! This should never happen.")

def spin():
    while True:
        spin_once()

# Pseudo-thread

class ZMQProcess(Process):
    def __init__(self, endpoint, sub_key, q):
        Process.__init__(self)
        self.endpoint = endpoint
        self.sub_key = sub_key
        self.q = q
        self._terminate_event = Event()
        self.daemon = True

    def __repr__(self):
        name =  self.__class__.__name__
        return '<%s at %#x>' % (name, id(self))
    
    def set_terminate_event(self):
        self._terminate_event.set()

    def run(self):
        #print "Init for %s %s %s" % (endpoint, sub_key, callback)
        ctx = zmq.Context()
        sock = ctx.socket(zmq.SUB)
        sock.setsockopt(zmq.SUBSCRIBE, self.sub_key)
        sock.connect(self.endpoint)
        try:
            while not self._terminate_event.is_set():
                #print "Waiting for packet %s %s %s" % (endpoint, sub_key, callback)
                # non-blocking
                msgs = sock.recv_multipart()
                assert msgs[0] == self.sub_key
                #print "Calling callback %s %s %s" % (endpoint, sub_key, callback)
                #callback(msgpack.loads(msgs[1]))
                # Putting compressed data on the q
                self.q.put((msgs[0], msgs[1]))
        except KeyboardInterrupt:
            pass

        return True
    #print "Exit  for %s %s %s" % (endpoint, sub_key, callback)

def subscribe(endpoint, sub_key, callback):
    if sub_key in __subs:
        logging.error("Only one callback for %s is allowed. Skipping." % sub_key)
        return None
    else:
        g = ZMQProcess(endpoint, sub_key, callback_queue)
        g.start()
        __subs[sub_key] = (callback, g)
        return g

def unsubscribe(sub_key):
    try:
        callback, g = __subs[sub_key]
        print "Trying to gracefully shutdown %s ..." % g
        try:
            g.kill()
        except AttributeError:
            g.set_terminate_event()
            g.join()
        del __subs[sub_key]
        return True
    except KeyError:
        logging.error("Subscribtion Key %s not found." % sub_key)
        return False

def killall():
    for sub_key, value in __subs.items():
        unsubscribe(sub_key)

# Exceptions: http://www.python-requests.org/en/latest/api/#requests.exceptions.HTTPError
class DimonRESTBase(object):
    def __init__(self, host, http_port, **kwargs):
        # TODO: Sanintize
        self.host = host
        self.http_port = http_port
        self.base_url = "http://%s:%s/dimon/v%s" % (host, http_port, __api__)
        try:
            self._parse_args(**kwargs)
        except KeyError:
            logging.error(self.parse_err)
            raise RuntimeError
        self._update_url()

        self.async_greenlet = None
        self.async_key = None

    def _r(self, req_type, url, timeout = None, raise_error = True):
        try:
            if req_type == 'get':
                r = requests.get(url, timeout = timeout)
            elif req_type == 'post':
                r = requests.post(url, timeout = timeout)
            elif req_type == 'delete':
                r = requests.delete(url, timeout = timeout)
        except requests.ConnectionError as e:
            logging.error("DimoneRESTBase: Connection Error: %s" % e)
            return False
        except requests.exceptions.Timeout as e:
            logging.error("DimoneRESTBase: Timeout error: %s" % e)
            return False
        logging.debug("HTTP Status: %s" % r.status_code)
        if raise_error:
            r.raise_for_status()
            if req_type == 'get':
                return r.json()
            else:
                # TODO: Remove This
                assert r.status_code == 200
                return r.status_code # Should be alwyas 200
        else:
            if r.status_code == 200:
                return r.json()
            else:
                return r.status_code

    def get_info(self, timeout = None, raise_error = True):
        return self._r('get', self.base_url + '/info')

    def get(self, path = "", timeout = None, raise_error = True):
        return self._r('get', self.get_url + path)

    def start_monitor(self, timeout = None, raise_error = True):
        return self._r('post', self.post_url)

    def stop_monitor(self, timeout = None, raise_error = True):
        if self.async_key:
            self.unregister_callback()
        return self._r('delete', self.del_url)

    def register_callback(self, callback):
        print "Trying to determine the 0mq publisher endpoint"
        try:
            zmq_endpoint = self.get_info()['zmq_publish']
        except KeyError:
            print "Key error"
            return False
        except:
            logging.error("Error getting publisher information.")
            return False

        self.async_key = self._get_subscription_key()
        print "Trying to subscribe to %s with key %s" % (zmq_endpoint, self.async_key)

        self.async_greenlet = subscribe(zmq_endpoint, self.async_key, callback)
        return self.async_greenlet != None

    def unregister_callback(self):
        if not self.async_greenlet:
            logging.error("No async subscriber is running for %s" % self)
            return False
        if self.async_key:
            return unsubscribe(self.async_key)
        else:
            logging.error("Something is wrong in async module of %s" % self)
            return False

    def _parse_args(self, **kwargs):
        raise NotImplementedError

    def _get_partial_url(self):
        raise NotImplementedError

    def _get_subscription_key(self):
        raise NotImplementedError

class DimonPID(DimonRESTBase):
    def __init__(self, host, http_port, **kwargs):
        DimonRESTBase.__init__(self, host, http_port, **kwargs)

    def _parse_args(self, **kwargs):
        # TODO: Should we throw another exception?
        self.pid = int(kwargs['pid'])
        if (self.pid <= 0):
            self.parse_err = "DimonPID: Invalid arguments, excepts pid and pid >= 0 ."
            raise KeyError

    def _update_url(self):
        self.get_url = self.base_url + '/monitor/pid/%s' % self.pid
        self.del_url = self.get_url
        self.post_url = self.get_url

    def _get_subscription_key(self):
        return "%s:%s:%s" % (self.host, 'pid', self.pid)

class DimonHost(DimonRESTBase):
    def __init__(self, host, http_port, **kwargs):
        DimonRESTBase.__init__(self, host, http_port, **kwargs)

    def _parse_args(self, **kwargs):
        self.parse_err = ""
        pass

    def _update_url(self):
        self.get_url = self.base_url + '/monitor/host'
        self.del_url = self.get_url
        self.post_url = self.get_url

    def _get_subscription_key(self):
        return "%s:%s:%s" % (self.host, 'host', 'host')


class DimonLatency(DimonRESTBase):
    def __init__(self, host, http_port, **kwargs):
        DimonRESTBase.__init__(self, host, http_port, **kwargs)

    def _parse_args(self, **kwargs):
        __host_regex = re.compile("(?=^.{1,254}$)(^(?:(?!\d|-)[a-zA-Z0-9\-]{1,63}(?<!-)\.?)+(?:[a-zA-Z]{2,})$)")
        __ip_regex = re.compile("^(?:[0-9]{1,3}\.){3}[0-9]{1,3}$")
        self.target = kwargs['target']
        if not (__host_regex.match(self.target) or __ip_regex.match(self.target)):
            self.parse_err = "DimonLatency: Invalid arguments, excepts valid `target` hostname or address"
            raise KeyError

    def _update_url(self):
        self.get_url = self.base_url + '/monitor/latency/%s' % self.target
        self.del_url = self.get_url
        self.post_url = self.get_url

    def _get_subscription_key(self):
        return "%s:%s:%s" % (self.host, 'latency', self.target)

class DimonSocket(DimonRESTBase):
    def __init__(self, host, http_port, **kwargs):
        DimonRESTBase.__init__(self, host, http_port, **kwargs)

    def _parse_args(self, **kwargs):
        # TODO: Should we throw another exception?
        self.proto = kwargs['proto']
        self.direction = kwargs['direction']
        self.port = int(kwargs['port'])
        if (self.port <= 0) or (not self.proto in ['tcp', 'udp']) or (not self.direction in ['bi', 'src', 'dst']):
            self.parse_err = "DimonSocket: Invalid arguments, excepts proto (tcp|udp), direction(bi|src|dst) and valid port "
            raise KeyError

    def _update_url(self):
        self.get_url = self.base_url + '/monitor/socket'
        self.post_url = self.get_url + '/%s/%s/%s' % (self.proto, self.direction, self.port)
        self.del_url = self.post_url

    def _get_subscription_key(self):
        return "%s:%s:%s" % (self.host, 'socket', 'socket')
