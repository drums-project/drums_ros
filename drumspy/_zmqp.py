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

import zmq
import multiprocessing
import logging
import errno


class ZMQProcess(multiprocessing.Process):
    def __init__(self, cmd_endpoint, result_q):
        multiprocessing.Process.__init__(self)
        self.cmd_endpoint = cmd_endpoint
        self.result_q = result_q
        self._terminate_event = multiprocessing.Event()
        self.logger = logging.getLogger(type(self).__name__)
        self.daemon = True

    def __repr__(self):
        name = self.__class__.__name__
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
                                self.logger.warnings(
                                    "ZMQ does not support disconnect.")
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
