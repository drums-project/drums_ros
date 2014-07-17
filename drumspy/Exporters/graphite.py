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

from . import ExporterBase
import zmq

class GraphiteExporter(ExporterBase):
    def __init__(self, port):
        ExporterBase.__init__(self)
        self.ctx = zmq.Context()
        self.sock = self.ctx.socket(zmq.STREAM)
        self.port = port
        self.timestamp = 0
        try:
            self.sock.connect('tcp://localhost:%s' % self.port)
            self.id = self.sock.getsockopt(zmq.IDENTITY)
            self.logger.info("Connected.")
        except zmq.ZMQError, e:
            self.logger.error('ZMQ Error %s', e)

    # def _send(self, d, path):
    #     #self.logger.info("In send: %s" % (path,))
    #     if isinstance(d, dict):
    #         for key, val in d.items():
    #             self._send(val, path + "." + key)
    #     elif isinstance(d, list):
    #         for index, val in enumerate(d):
    #             self._send(val, path + "." + str(index))

    #     elif isinstance(d, (int, long, float, complex)):
    #         #self.logger.info("Sending %s : %s" % (path, d,))
    #         self.sock.send(self.id, zmq.SNDMORE)
    #         self.sock.send_string("%s %s %s\n" % (path, d, self.timestamp), zmq.SNDMORE)

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

    def cleanup(self):
        self.sock.close()
