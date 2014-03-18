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

from _zmqp import ZMQProcess
from Queue import Empty, Full
import zmq
import threading
import multiprocessing
import logging
import time
import msgpack

class Singleton(type):
    """
    A singleton metaclass.
    From: http://c2.com/cgi/wiki?PythonSingleton
    """
    def __init__(cls, name, bases, dictionary):
        super(Singleton, cls).__init__(name, bases, dictionary)
        cls._instance = None
        cls._lock = threading.Lock()

    def __call__(cls, *args, **kws):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super(Singleton, cls).__call__(*args, **kws)
        return cls._instance


class DrumsPy(threading.Thread):
    __metaclass__ = Singleton
    def __init__(self):
        threading.Thread.__init__(self)
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

        self.terminate_event = threading.Event()
        self.is_running = threading.Event()
        self.daemon = True

        self.logger = logging.getLogger(type(self).__name__)

        self.logger.info("Creating zmq socket and process for the first time.")
        ctx = zmq.Context()
        self.zmq_cmd_sock = ctx.socket(zmq.PUSH)
        self.zmq_cmd_sock.bind(self.ZMQ_CMD_ENDPOINT)
        time.sleep(0.1)
        self.zmq_process = ZMQProcess(self.ZMQ_CMD_ENDPOINT, self.callback_queue)
        self.zmq_process.start()
    
        self.logger.info("Creating WebScoket thread for the first time.")
        self.ws_thread = GraphitePublisher(2003)

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

    def __kill_spinner_thread(self):
        while self.is_alive():
            self.logger.info("Spinner thread is still alive. Killing it.")
            self.callback_queue.put(('__term__', '__term__'))
            time.sleep(0.1)

    def __kill_ws_thread(self):
        return
        while self.ws_thread.is_alive():
            self.logger.info("WebSocket Thread thread is still alive. Killing it.")
            self.ws_thread.request_shutdown()
            time.sleep(0.1)

    def shutdown(self):
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
            except Empty:
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

            kill_zmq = not self.__endpoints

        cmd_str = "unsub@%s@%s" % (e, sub_key,)


        # TODO: Fix this
        #if kill_zmq:
        #    __logger.info("ZMQ Process is not needed any more! Killing it ...")
        #    zmq_process.set_terminate_event()
        #    time.sleep(0.1)

        self.zmq_cmd_sock.send_string(cmd_str)

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
