# -*- coding: utf-8 -*-
"""
Copyright 2013 Mani Monajjemi (AutonomyLab, Simon Fraser University)

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
"""

__version__ = "0.9.0"
__api__ = "1"
version_info = tuple([int(num) for num in __version__.split('.')])


# TODO: CHECK IF zmq_cmd_sock and zmq_process are thread-safe

import re
import logging
import requests
import errno

import zmq
import multiprocessing
import threading
import Queue
import time
import msgpack
import json
#import pickle
#import struct

from wsgiref.simple_server import make_server
from ws4py.websocket import EchoWebSocket
from ws4py.server.wsgirefserver import WSGIServer, WebSocketWSGIRequestHandler
from ws4py.server.wsgiutils import WebSocketWSGIApplication

class Singleton(type):
    """
    A singleton metaclass.
    From: http://c2.com/cgi/wiki?PythonSingleton
    """
    def __init__(cls, name, bases, dictionary):
        super(Singleton, cls).__init__(name, bases, dictionary)
        cls._instance = None
        cls._lock = Lock()

    def __call__(cls, *args, **kws):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super(Singleton, cls).__call__(*args, **kws)
        return cls._instance


class DrumsPy(Thread):
    __metaclass__ = Singleton
    def __init__(self):
        Thread.__init__(self)
        self.__ilock = threading.Lock()
        # Set of hosts (endpoints)
        self.__endpoints = set()
        # Map from sub_key to callback
        # key -> callback
        self.__subs = dict()
        # Map from hostnames (endpoints) to sub_keys
        self.__endpoint_keys = dict()
        # The single ZMQ_Process instant
        self.zmq_process = None
        self.zmq_cmd_sock = None
        # TODO: Config
        self.ZMQ_CMD_ENDPOINT = "ipc://drumspyc"
        self.callback_queue = multiprocessing.Queue()
        # WebSocket Broadcaster
        self.ws_thread = None

        self.terminate_event = Event()
        self.is_running = Event()
        self.daemon = True

        self.logger = logging.getLogger(type(self).__name__)
    
    def init(self):
        if not self.zmq_process:
            self.logger.info("Creating zmq socket and process for the first time.")
            ctx = zmq.Context()
            self.zmq_cmd_sock = ctx.socket(zmq.PUSH)
            self.zmq_cmd_sock.bind(ZMQ_CMD_ENDPOINT)
            self.time.sleep(0.1)
            self.zmq_process = ZMQProcess(self.ZMQ_CMD_ENDPOINT, self.callback_queue)
            self.zmq_process.start()

        if not self.ws_thread:
            self.logger.info("Creating WebScoket thread for the first time.")
            self.ws_thread = GraphitePublisher(2003)

        
        if not self.is_running.is_set():
            self.logger.info("Starting drums client's thread ...")
            self.start()

    def is_shutdown(self):
        return self.terminate_event.is_set()

    def __kill_zmq_prcoess(self):
        while self.zmq_process.is_alive():
            self.logger.info("ZMQ Process is still alive. Killing it.")
            self.zmq_process.set_terminate_event()
            self.zmq_cmd_sock.send_string('@@')
            time.sleep(0.1)
       self.logger.info("ZMQ Process is not alive any more.")

    def __kill_spinner_thread():
        while self.is_alive():
            self.logger.info("Spinner thread is still alive. Killing it.")
            self.callback_queue.put(('__term__', '__term__'))
            time.sleep(0.1)

    def __kill_ws_thread(self):
        while self.ws_thread.is_alive():
            self.logger.info("WebSocket Thread thread is still alive. Killing it.")
            self.ws_thread.request_shutdown()
            time.sleep(0.1)

    def shutdown():
        self.logger.info("Shutting down spinner thread ...")
        self.__kill_spinner_thread()
        self.logger.info("Shutting down WebSocketThread ...")
        self.__kill_ws_thread()
        self.logger.info("Shutting down ZMQProcess ...")
        self.__kill_zmq_prcoess()
        return True

# This is blocking
    def run(self):
        while not self.terminate_event.is_set():
            try:
                sub_key, data = self.callback_queue.get()
                if sub_key == '__term__':
                    # ZMQ will automatically shutdown after all subscription
                    # and endpoints are removed
                    # ACK back to main thread to shutdown
                    self.terminate_event.set()
                    self.logger.info("I've been told to terminate. Setting TerminateEvent.")
                    continue
                try:
                    with self.__ilock:
                        callback = self.__subs[sub_key]
                    msg = msgpack.loads(data)
                    callback(msg)
                    # TODO: Plugins
                    self.ws_thread.broadcast(msg, False)
                except KeyError:
                    self.logger.error("Subscription key `%s` in Queue does not exist! It might have been unsubscribed." % (sub_key, ))
            except Queue.Empty:
                pass
        self.logger.info("drumspy spinner thread exited cleanly.")
        return True
   
    def subscribe(self,endpoint, sub_key, callback):
        cmd_str = ""
        with self.__ilock:
            if not endpoint in self.__endpoints:
                self.__endpoints.add(endpoint)
                self.__endpoint_keys[endpoint] = set()
                e = endpoint
            else:
                e = ''

            if sub_key in self.__endpoint_keys[endpoint]:
                self.logger.warning("This key is already being monitored: %s. Unsubscribe first.", sub_key)
                # TODO: fix this
                return True
            else:
                self.__endpoint_keys[endpoint].add(sub_key)
                self.__subs[sub_key] = callback
                cmd_str = "sub@%s@%s" % (e, sub_key, )

        if cmd_str:
            self.zmq_cmd_sock.send_string(cmd_str)
            return True
        else:
            return False

    def unsubscribe(self, endpoint, sub_key):
        with self.__ilock:
            if not endpoint in self.__endpoint_keys:
                self.logger.warning("Endpoint is not being monitored: %s.", endpoint)
                return False
            if (not sub_key in self.__endpoint_keys[endpoint]) or (not sub_key in self.__subs):
                self.logger.warning("This key is not being monitored: %s.", sub_key)
                return False

            del self.__subs[sub_key]
            self.__endpoint_keys[endpoint].remove(sub_key)
            e = ''
            if not self.__endpoint_keys[endpoint]:
                self.__endpoints.remove(endpoint)
                e = endpoint

            kill_zmq = not __endpoints

        cmd_str = "unsub@%s@%s" % (e, sub_key,)


        # TODO: Fix this
        #if kill_zmq:
        #    __logger.info("ZMQ Process is not needed any more! Killing it ...")
        #    zmq_process.set_terminate_event()
        #    time.sleep(0.1)

        zmq_cmd_sock.send_string(cmd_str)

        return True

    def killall(self):
        with self.__ilock:
            items = __subs.items()[:]

        for sub_key, value in items:
            self.unsubscribe(sub_key)


class GraphitePublisher():
    def __init__(self, port):
        self.ctx = zmq.Context()
        self.sock = self.ctx.socket(zmq.STREAM)
        self.port = port
        self.logger = logging.getLogger("%s.graphite" % __name__)
        self.timestamp = 0
        try:
            self.sock.connect('tcp://localhost:%s' % self.port)
            self.id = self.sock.getsockopt(zmq.IDENTITY)
            self.logger.info("Connected.")
        except zmq.ZMQError, e:
            self.logger.error('ZMQ Error %s', e)

    def _send(self, d, path):
        #self.logger.info("In send: %s" % (path,))
        if isinstance(d, dict):
            for key, val in d.items():
                self._send(val, path + "." + key)
        elif isinstance(d, list):
            for index, val in enumerate(d):
                self._send(val, path + "." + str(index))

        elif isinstance(d, (int, long, float, complex)):
            #self.logger.info("Sending %s : %s" % (path, d,))
            self.sock.send(self.id, zmq.SNDMORE)
            self.sock.send_string("%s %s %s\n" % (path, d, self.timestamp), zmq.SNDMORE)

    def _send_optimized(self, d, path):
        stack = list()
        stack.append((path, d["data"]))
        buf = list()
        while stack:
            p, ref = stack.pop()
            if isinstance(ref, dict):
                it = ref.iteritems()
            elif isinstance(ref, list):
                it = enumerate(ref)
            else:
                continue
            for key, val in it:
                np = p + "." + str(key)
                if isinstance(val, (int, long, float)):
                    #print np, val
                    #self.sock.send_string("")
                    buf.append("%s %s %s\n" % (np, val, self.timestamp))
                    #plain text seems smaller in our case
                    #buf.append((np, (self.timestamp, val,),))
                else:
                    stack.append((np, val))


        #payload = pickle.dumps(buf)
        #header = struct.pack("!L", len(payload))

        self.sock.send(self.id, zmq.SNDMORE)
        self.sock.send_string("\n".join(buf))
        del stack
        del buf

    def broadcast(self, message, binary=False):
        try:
            k = message['data'].get('meta', '')
            if not k:
                k = message['key']

            if isinstance(k, list):
                assert len(k) > 0
                if len(k) == 1:
                    k = k[0]
                else:
                    # TODO
                    pub_meta = k[0].split(",")
                    k = "%s,topic,__mux__,%s,__mux__" % (pub_meta[0], pub_meta[3],)

            k = str(k).replace(",", ".")
            root_key = "drums.%s.%s.%s" % (message['src'], message['type'], k)
            root_key = root_key.replace('/', ':')
            #data = message['data']
            self.timestamp = message['data']['timestamp']
            #self._send(data, root_key)
            self._send_optimized(message, root_key)

        except KeyError, e:
            self.logger.info("Key `%s` not found in %s." % (e, message))

    def is_alive(self):
        return False

    def request_shutdown(self):
        self.sock.close()

# class WebSocketThread(threading.Thread):
#     def __init__(self, port):
#         threading.Thread.__init__(self)
#         self.port = port
#         self.server = make_server('', self.port,
#             server_class=WSGIServer,
#             handler_class=WebSocketWSGIRequestHandler,
#             app=WebSocketWSGIApplication(handler_cls=EchoWebSocket))
#         self.server.initialize_websockets_manager()
#         self.logger = logging.getLogger("%s.WebSocketThread" % __name__)

#     def run(self):
#         self.logger.info("Starting WebSocket handler on port %s" % self.port)
#         # This is blocking until shutdown() request
#         self.server.serve_forever()
#         # After shutdown
#         self.server.server_close()
#         self.logger.info("Websocket Handler exited cleanly.")
#         return True

#     def request_shutdown(self):
#         self.server.shutdown()

#     # TODO: Check Safety Here
#     # TODO: Send compressed data here (transfer overhead to browser)
#     def broadcast(self, msg, binary):
#         self.server.manager.broadcast(json.dumps(msg), binary)

class ZMQProcess(multiprocessing.Process):
    def __init__(self, cmd_endpoint, result_q):
        multiprocessing.Process.__init__(self)
        self.cmd_endpoint = cmd_endpoint
        self.result_q = result_q
        self._terminate_event = multiprocessing.Event()
        self.logger = logging.getLogger(type(self).__name__)
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
        self.logger.info("Running ZMQProcess.")
        while not self._terminate_event.is_set():
            try:
                socks = dict(poller.poll())

                if cmd_sock in socks and socks[cmd_sock] == zmq.POLLIN:
                    # CMD
                    cmd_string = cmd_sock.recv_string()
                    self.logger.info("ZMQ heard: %s" % cmd_string)
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
                                self.logger.warnings("ZMQ does not support disconnect.")
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
                # Let's inform the spinner thread to terminate
                # TODO: FIND A BETTER WAY
                #print "CTRL+C HEARD"
                self.logger.info("ZMQProcess CTRL+C Detected.")
                self.result_q.put(('__term__', '__term__'))
                pass
        self.logger.info("ZMQProcess exited cleanly.")
        return True



# Exceptions: http://www.python-requests.org/en/latest/api/#requests.exceptions.HTTPError
class DrumsRESTBase(object):
    def __init__(self, host, http_port, **kwargs):
        # TODO: Sanintize
        self.host = host
        self.http_port = http_port
        self.base_url = "http://%s:%s/drums/v%s" % (host, http_port, __api__)
        self.logger = logging.getLogger("%s.DrumsREST" % __name__)
        try:
            # everyone can have a meta attached
            self.meta = kwargs.get('meta', '')
            if self.meta and not isinstance(self.meta, basestring):
                self.meta = ''
                self.logger.warning("Meta should be pure string. Ignorting it.")
            # parse the rest
            self._parse_args(**kwargs)
        except KeyError:
            self.logger.error(self.parse_err)
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
                r = requests.post(url,
                    timeout=timeout,
                    headers={'Content-type': 'application/json'},
                    data=json.dumps({'meta': self.meta}))
            elif req_type == 'delete':
                #r = requests.delete(url, timeout=timeout)
                r = requests.delete(url,
                    timeout=timeout,
                    headers={'Content-type': 'application/json'},
                    data=json.dumps({'meta': self.meta}))
        except requests.ConnectionError as e:
            self.logger.error("DrumseRESTBase: Connection Error: %s" % e)
            return False
        except requests.exceptions.Timeout as e:
            self.logger.error("DrumseRESTBase: Timeout error: %s" % e)
            return False
        self.logger.debug("HTTP Status: %s" % r.status_code)
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

    def start_monitor(self, raise_error=True, timeout=None):
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
        self.logger.info("Trying to determine the 0mq publisher endpoint")
        try:
            zmq_endpoint = self.get_info()['zmq_publish']
            #zmq_advertised_host =
        except KeyError:
            return False
        except:
            self.logger.error("Error getting publisher information.")
            return False

        return zmq_endpoint

    def register_callback(self, callback):
        # TODO: Invalidate cache
        if not self.zmq_endpoint:
            self.zmq_endpoint = self.get_zmq_endpoint()
        if self.zmq_endpoint:
            self.async_key = self.get_subscription_key()
            self.logger.info("Trying to subscribe to %s with key %s" % (self.zmq_endpoint, self.async_key))
            return subscribe(self.zmq_endpoint, self.async_key, callback)
        else:
            return False

    def unregister_callback(self):
        if self.async_key and self.zmq_endpoint:
            return unsubscribe(self.zmq_endpoint, self.async_key)
        else:
            self.logger.error("Something is wrong in async module of %s" % self)
            return False

    def _parse_args(self, **kwargs):
        raise NotImplementedError

    def _get_partial_url(self):
        raise NotImplementedError

    def get_subscription_key(self):
        raise NotImplementedError

class DrumsPID(DrumsRESTBase):
    def __init__(self, host, http_port, **kwargs):
        DrumsRESTBase.__init__(self, host, http_port, **kwargs)

    def _parse_args(self, **kwargs):
        # TODO: Should we throw another exception?
        self.pid = int(kwargs['pid'])
        if (self.pid <= 0):
            self.parse_err = "DrumsPID: Invalid arguments, excepts pid and pid >= 0 ."
            raise KeyError

    def _update_url(self):
        self.get_url = self.base_url + '/monitor/pid/%s' % self.pid
        self.del_url = self.get_url
        self.post_url = self.get_url

    def get_subscription_key(self):
        return "%s:%s:%s" % (self.host, 'pid', self.pid)

class DrumsHost(DrumsRESTBase):
    def __init__(self, host, http_port, **kwargs):
        DrumsRESTBase.__init__(self, host, http_port, **kwargs)

    def _parse_args(self, **kwargs):
        self.parse_err = ""
        pass

    def _update_url(self):
        self.get_url = self.base_url + '/monitor/host'
        self.del_url = self.get_url
        self.post_url = self.get_url

    def get_subscription_key(self):
        return "%s:%s:%s" % (self.host, 'host', 'host')


class DrumsLatency(DrumsRESTBase):
    def __init__(self, host, http_port, **kwargs):
        DrumsRESTBase.__init__(self, host, http_port, **kwargs)

    def _parse_args(self, **kwargs):
        #__host_regex = re.compile("(?=^.{1,254}$)(^(?:(?!\d|-)[a-zA-Z0-9\-]{1,63}(?<!-)\.?)+(?:[a-zA-Z]{2,})$)")
        __host_regex = re.compile('^(?![0-9]+$)(?!-)[a-zA-Z0-9-]{,63}(?<!-)$')
        __ip_regex = re.compile("^(?:[0-9]{1,3}\.){3}[0-9]{1,3}$")
        self.target = kwargs['target']
        if not (__host_regex.match(self.target) or __ip_regex.match(self.target)):
            self.parse_err = "DrumsLatency: Invalid arguments, excepts valid `target` hostname or address. Input is %s" % (self.target,)
            raise KeyError

    def _update_url(self):
        self.get_url = self.base_url + '/monitor/latency/%s' % self.target
        self.del_url = self.get_url
        self.post_url = self.get_url

    def get_subscription_key(self):
        return "%s:%s:%s" % (self.host, 'latency', self.target)

class DrumsSocket(DrumsRESTBase):
    def __init__(self, host, http_port, **kwargs):
        DrumsRESTBase.__init__(self, host, http_port, **kwargs)

    def _parse_args(self, **kwargs):
        # TODO: Should we throw another exception?
        self.proto = kwargs['proto']
        self.direction = kwargs['direction']
        self.port = int(kwargs['port'])
        if (self.port <= 0) or (not self.proto in ['tcp', 'udp']) or (not self.direction in ['bi', 'src', 'dst']):
            self.parse_err = "DrumsSocket: Invalid arguments, excepts proto (tcp|udp), direction(bi|src|dst) and valid port "
            raise KeyError

    def _update_url(self):
        self.get_url = self.base_url + '/monitor/socket'
        self.post_url = self.get_url + '/%s/%s/%s' % (self.proto, self.direction, self.port)
        self.del_url = self.post_url

    def get_subscription_key(self):
        return "%s:%s:%s" % (self.host, 'socket', '%s:%s' % (self.proto, self.port))
