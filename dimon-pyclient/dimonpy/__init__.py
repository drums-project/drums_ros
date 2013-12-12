    # -*- coding: utf-8 -*-

__version__ = "0.1.0"
__api__ = "1"
version_info = tuple([int(num) for num in __version__.split('.')])

import re
import logging
import requests
import errno

import zmq
from multiprocessing import Process
from multiprocessing import Queue, Event
from Queue import Empty
from threading import Lock
import time

import msgpack

# Python does not provide a clean way to create signelton objects
# All ASync stuff are part of the module's namespace directly.


__ilock = Lock()

# Set of hosts (endpoints)
__endpoints = set()

# Map from sub_key to callback
# key -> callback
__subs = dict()

# Map from hostnames (endpoints) to sub_keys
__endpoint_keys = dict()

# The single ZMQ_Process instant
zmq_process = None
zmq_cmd_sock = None
ZMQ_CMD_ENDPOINT = "ipc://dimonpyc"

callback_queue = Queue()


def get_callback_queue():
    global callback_queue
    return callback_queue

# This is blocking
def spin(block = True):
    try:
        sub_key, data = callback_queue.get(block = block)
        try:
            with __ilock:
                callback = __subs[sub_key]
            callback(msgpack.loads(data))
        except KeyError:
            logging.error("Subscription key in Queue does not exist! This should never happen.")
    except Empty:
        pass

# Pseudo-thread
class ZMQProcess(Process):
    def __init__(self, cmd_endpoint, result_q):
        Process.__init__(self)
        self.cmd_endpoint = cmd_endpoint
        self.result_q = result_q
        self._terminate_event = Event()
        self.daemon = True

    def __repr__(self):
        name =  self.__class__.__name__
        return '<%s at %#x>' % (name, id(self))

    def set_terminate_event(self):
        self._terminate_event.set()

    def run(self):
        ctx = zmq.Context()
        cmd_sock = ctx.socket(zmq.PULL)
        cmd_sock.connect(self.cmd_endpoint)

        sub_sock = ctx.socket(zmq.SUB)
        poller = zmq.Poller()
        poller.register(cmd_sock, zmq.POLLIN)
        poller.register(sub_sock, zmq.POLLIN)
        #sock.setsockopt(zmq.SUBSCRIBE, self.sub_key)
        #sock.connect(self.endpoint)
        logging.info("Running ZMQProcess.")
        while not self._terminate_event.is_set():
            try:
                socks = dict(poller.poll())

                if cmd_sock in socks and socks[cmd_sock] == zmq.POLLIN:
                    # CMD
                    cmd_string = cmd_sock.recv_string()
                    logging.info("ZMQ heard: %s" % cmd_string)
                    cmd, endpoint, sub_key = cmd_string.split('@')
                    if cmd == 'sub':
                        sub_sock.setsockopt_string(zmq.SUBSCRIBE, sub_key)
                        if len(endpoint) > 0:
                            sub_sock.connect(endpoint)
                    if cmd == 'unsub':
                        sub_sock.setsockopt_string(zmq.UNSUBSCRIBE, sub_key)
                        if len(endpoint) > 0:
                            try:
                                sub_sock.disconnect(endpoint)
                            except AttributeError:
                                logging.warnings("ZMQ does not support disconnect.")
                                pass

                if sub_sock in socks and socks[sub_sock] == zmq.POLLIN:
                    sub_key, payload = sub_sock.recv_multipart()
                    self.result_q.put((sub_key, payload))
            except zmq.ZMQError, e:
                if e.errno == errno.EINTR:
                    continue
                else:
                    raise
            except KeyboardInterrupt:
                pass
        logging.info("ZMQProcess exited cleanly.")
        return True

def subscribe(endpoint, sub_key, callback):
    global zmq_process, zmq_cmd_sock, __ilock
    if not zmq_process:
        logging.info("Creating zmq socket and process for the first time.")
        ctx = zmq.Context()
        zmq_cmd_sock = ctx.socket(zmq.PUSH)
        zmq_cmd_sock.bind(ZMQ_CMD_ENDPOINT)
        time.sleep(0.1)
        zmq_process = ZMQProcess(ZMQ_CMD_ENDPOINT, callback_queue)
        zmq_process.start()

    cmd_str = ""
    with __ilock:
        if not endpoint in __endpoints:
            __endpoints.add(endpoint)
            __endpoint_keys[endpoint] = set()
            e = endpoint
        else:
            e = ''

        if sub_key in __endpoint_keys[endpoint]:
            logging.warnings("This key is already being monitored: %s. Unsubscribe first.", sub_key)
            return False
        else:
            __endpoint_keys[endpoint].add(sub_key)
            __subs[sub_key] = callback
            cmd_str = "sub@%s@%s" % (e, sub_key, )

    if cmd_str:
        zmq_cmd_sock.send_string(cmd_str)
        return True
    else:
        return False

def unsubscribe(endpoint, sub_key):
    global zmq_process, zmq_cmd_sock, __ilock

    with __ilock:
        if not endpoint in __endpoint_keys:
            logging.warnings("Endpoint is not being monitored: %s.", endpoint)
            return False
        if (not sub_key in __endpoint_keys[endpoint]) or (not sub_key in __subs):
            logging.warnings("This key is not being monitored: %s.", sub_key)
            return False

        del __subs[sub_key]
        __endpoint_keys[endpoint].remove(sub_key)
        e = ''
        if not __endpoint_keys[endpoint]:
            __endpoints.remove(endpoint)
            e = endpoint

        kill_zmq = not __endpoints


    cmd_str = "unsub@%s@%s" % (e, sub_key,)
    zmq_cmd_sock.send_string(cmd_str)

    if kill_zmq:
        logging.info("ZMQ Process is not needed any more! Killing it ...")
        zmq_process.set_terminate_event()

    return True

def killall():
    global __ilock
    with __ilock:
        items = __subs.items()[:]

    for sub_key, value in items:
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

        self.async_key = None
        self.zmq_endpoint = None
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
        logging.info("Trying to determine the 0mq publisher endpoint")
        try:
            zmq_endpoint = self.get_info()['zmq_publish']
        except KeyError:
            return False
        except:
            logging.error("Error getting publisher information.")
            return False

        return zmq_endpoint

    def register_callback(self, callback):
        self.zmq_endpoint = self.get_zmq_endpoint()
        if self.zmq_endpoint:
            self.async_key = self.get_subscription_key()
            logging.info("Trying to subscribe to %s with key %s" % (self.zmq_endpoint, self.async_key))
            return subscribe(self.zmq_endpoint, self.async_key, callback)
        else:
            return False

    def unregister_callback(self):
        if self.async_key and self.zmq_endpoint:
            return unsubscribe(self.zmq_endpoint, self.async_key)
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
