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
import json

# Singleton
from _drumspy import DrumsPy

def init():
    dp = DrumsPy()
    return True

def add_exporter(e):
    dp = DrumsPy()
    dp.add_exporter(e)
    
def is_shutdown():
    dp = DrumsPy()
    return dp.is_shutdown()

def shutdown():
    dp = DrumsPy()
    dp.shutdown()


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





# Exceptions: http://www.python-requests.org/en/latest/api/#requests.exceptions.HTTPError
class DrumsRESTBase(object):
    def __init__(self, host, http_port, **kwargs):
        # TODO: Sanintize
        self.host = host
        self.http_port = http_port
        self.base_url = "http://%s:%s/drums/v%s" % (host, http_port, __api__)
        self.logger = logging.getLogger("%s.DrumsREST" % __name__)
        self.dp = DrumsPy()
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
            return self.dp.subscribe(self.zmq_endpoint, self.async_key, callback)
        else:
            return False

    def unregister_callback(self):
        if self.async_key and self.zmq_endpoint:
            return self.dp.unsubscribe(self.zmq_endpoint, self.async_key)
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
