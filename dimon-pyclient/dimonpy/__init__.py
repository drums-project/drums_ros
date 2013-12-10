    # -*- coding: utf-8 -*-

__version__ = "0.1.0"
__api__ = "1"
version_info = tuple([int(num) for num in __version__.split('.')])

#__concurrency_impl = 'gevent' # single process, single thread
__concurrency_impl = 'multiprocessing' # multiple processes

import re
import logging
import requests
import errno

if __concurrency_impl == "gevent":
    import zmq.green as zmq
    from gevent import Greenlet as Process
    from gevent.queue import Queue, Empty
    from gevent.event import Event
elif __concurrency_impl == "multiprocessing":
    import zmq
    from multiprocessing import Process
    from multiprocessing import Queue, Event
    from Queue import Empty
else:
    raise NotImplementedError("__concurrency_impl is not defined.")

import msgpack

# Python does not provide a clean way to create signelton objects
# All ASync stuff are part of the module's namespace directly.

__subs = dict()
callback_queue = Queue()


# This is blocking
def spin():
    try:
        sub_key, data = callback_queue.get(block = True)
        try:
            callback, g = __subs[sub_key]
            callback(msgpack.loads(data))
        except KeyError:
            logging.error("Subscription key in Queue does not exist! This should never happen.")
    except Empty:
        pass

# Pseudo-thread

class ZMQProcess(Process):
    def __init__(self, endpoint, sub_key, q, use_sub_key = True):
        Process.__init__(self)
        self.endpoint = endpoint
        if use_sub_key:
            self.sub_key = sub_key
        else:
            self.sub_key = ''
        self.q = q
        self._terminate_event = Event()
        self.daemon = True


    def __repr__(self):
        name =  self.__class__.__name__
        return '<%s at %#x>' % (name, id(self))

    def set_terminate_event(self):
        self._terminate_event.set()

    def run(self):
        #print "Run for %s %s" % (self.endpoint, self.sub_key)
        ctx = zmq.Context()
        sock = ctx.socket(zmq.SUB)
        sock.setsockopt(zmq.SUBSCRIBE, self.sub_key)
        sock.connect(self.endpoint)
        try:
            while not self._terminate_event.is_set():
                #print "Waiting for packet %s %s %s" % (endpoint, sub_key, callback)
                # non-blocking
                try:
                    msgs = sock.recv_multipart()
                except zmq.ZMQError, e:
                    if e.errno == errno.EINTR:
                        continue
                    else:
                        raise
                assert self.sub_key == '' or msgs[0] == self.sub_key
                #print "Calling callback %s %s %s" % (endpoint, sub_key, callback)
                #callback(msgpack.loads(msgs[1]))
                # Putting compressed data on the q
                self.q.put((msgs[0], msgs[1]))
        except KeyboardInterrupt:
            pass

        return True
    #print "Exit  for %s %s %s" % (endpoint, sub_key, callback)


def subscribe(endpoint, sub_key, callback, use_sub_key_zmq=True):
    try:
        current_callback, current_g, count = __subs[sub_key]
        if current_callback == callback:
            __subs[sub_key] = (current_callback, current_g, count + 1)
            return True
        else:
            logging.warning("Only one callback for %s is allowed. Skipping." % sub_key)
            return False
    except KeyError:
        g = ZMQProcess(endpoint, sub_key, callback_queue, use_sub_key_zmq)
        g.start()
        __subs[sub_key] = (callback, g, 1)
        return g


def unsubscribe(sub_key):
    try:
        callback, g, count = __subs[sub_key]
        if count == 1:
            print "Trying to gracefully shutdown %s ..." % g
            try:
                g.kill()
            except AttributeError:
                g.set_terminate_event()
                g.join()
            del __subs[sub_key]
        else:
            __subs[sub_key] = (callback, g , count - 1)
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

        # TODO: Rename this
        self.async_greenlet = None
        self.async_key = None

    # Sends HTTP Requests
    def _r(self, req_type, url, raise_error=True, timeout=None):
        try:
            if req_type == 'get':
                r = requests.get(url, timeout=timeout)
            elif req_type == 'post':
                r = requests.post(url, timeout=timeout)
            elif req_type == 'delete':
                r = requests.delete(url, timeout=timeout)
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
                # Should be alwyas 200
                assert r.status_code == 200
                return r.status_code
        else:
            if r.status_code == 200:
                return r.json()
            else:
                return r.status_code

    def get_info(self, raise_error=True, timeout=None):
        return self._r('get', self.base_url + '/info', raise_error, timeout)

    def get(self, path="", raise_error=True, timeout=None):
        return self._r('get', self.get_url + path, raise_error, timeout)

    def start_monitor(self, raise_error=True, timeout=None,):
        try:
            return self._r('post', self.post_url, raise_error, timeout)
        except requests.exceptions.HTTPError:
            return False

    def stop_monitor(self, raise_error=True, timeout=None):
        if self.async_key:
            self.unregister_callback()
        try:
            return self._r('delete', self.del_url, raise_error, timeout)
        except requests.exceptions.HTTPError:
            return False

    def get_zmq_endpoint(self):
        print "Trying to determine the 0mq publisher endpoint"
        try:
            zmq_endpoint = self.get_info()['zmq_publish']
        except KeyError:
            print "Key error"
            return False
        except:
            logging.error("Error getting publisher information.")
            return False

        return zmq_endpoint

    def register_callback(self, callback, one_process_per_key=True):
        zmq_endpoint = self.get_zmq_endpoint()
        if zmq_endpoint:
            if one_process_per_key:
                self.async_key = self.get_subscription_key()
            else:
                self.async_key = self.host
            if one_process_per_key:
                print "Trying to subscribe to %s with key %s" % (zmq_endpoint, self.async_key)

                self.async_greenlet = subscribe(zmq_endpoint, self.async_key, callback, True)
            else:
                print "Trying to subscribe to all keys from %s" % (zmq_endpoint,)
                self.async_greenlet = subscribe(zmq_endpoint, self.async_key, callback, False)
            return self.async_greenlet != None
        else:
            return False

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

    def get_subscription_key(self):
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

    def get_subscription_key(self):
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

    def get_subscription_key(self):
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

    def get_subscription_key(self):
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

    def get_subscription_key(self):
        return "%s:%s:%s" % (self.host, 'socket', 'socket')
