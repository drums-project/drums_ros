    # -*- coding: utf-8 -*-

__version__ = "0.1.0"
__api__ = "1"
version_info = tuple([int(num) for num in __version__.split('.')])

import sys
import re
import logging
import requests
import zmq
import msgpack

from multiprocessing import Process
from multiprocessing import Queue, Event
from Queue import Empty, Full



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

        self.async_running = False
        self.async_process = None
        self.data_queue = Queue()

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
        print("Status: %s" % r.status_code)
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
        return self._r('delete', self.del_url)

    def register_callback(self, callback):
        if not self.async_running:
            self._async_init()
        pass
        #msg = ('eva', 8002, self.callback_queue, callback, )
        #self.push_socket.send('eva', 8002, msg)

    def _parse_args(self, **kwargs):
        raise NotImplementedError

    def _get_partial_url(self):
        raise NotImplementedError

    def _get_subscription_key(self):
        raise NotImplementedError

    def _async_init(self):
        print "Trying to determine the 0mq publisher endpoint"
        try:
            zmq_endpoint = self.get_info()['zmq_publish']
        except KeyError:
            print "Key error"
            return False
        except:
            logging.error("Error getting publisher information.")
            return False

        sub_key = self._get_subscription_key()
        print "Trying to connect to subscribe to %s with key %s" % (zmq_endpoint, sub_key)

        self.async_process = Process(target = self._async_loop, args = (zmq_endpoint, sub_key, self.data_queue,))
        self.async_process.start()
        return True


    # This runs in a seperate context
    def _async_loop(self, endpoint, sub_key, q):
        try:
            ctx = zmq.Context()
            sock = ctx.socket(zmq.SUB)
            sock.setsockopt('SUBSCRIBE', sub_key)
            sock.connect(endpoint)
        except:
            logging.error("0mq err")

        while True:
            msgs = sock.recv_multipart()
            # Still compressed
            assert msgs[0] == sub_key
            q.put(msgs[1])


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
