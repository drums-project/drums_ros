    # -*- coding: utf-8 -*-

__version__ = "0.1.0"
__api__ = "1"
version_info = tuple([int(num) for num in __version__.split('.')])

import re
import logging
import requests

# Exceptions: http://www.python-requests.org/en/latest/api/#requests.exceptions.HTTPError
class DimonRESTBase(object):
    def __init__(self, host, port):
        # TODO: Sanintize
        self.host = host
        self.port = port
        self.base_url = "http://%s:%s/dimon/v%s" % (host, port, __api__)

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

    def _parse_args(self, **kwargs):
        raise NotImplementedError

    def _get_partial_url(self):
        raise NotImplementedError


class DimonPID(DimonRESTBase):
    def __init__(self, host, port, **kwargs):
        DimonRESTBase.__init__(self, host, port)
        try:
            self._parse_args(**kwargs)
        except KeyError:
            logging.error("DimonPID: Invalid arguments, excepts pid and pid >= 0 .")
            raise RuntimeError
        self._update_url()

    def _parse_args(self, **kwargs):
        # TODO: Should we throw another exception?
        self.pid = int(kwargs['pid'])
        if (self.pid <= 0):
            raise KeyError

    def _update_url(self):
        self.get_url = self.base_url + '/monitor/pid/%s' % self.pid
        self.del_url = self.get_url
        self.post_url = self.get_url

class DimonHost(DimonRESTBase):
    def __init__(self, host, port, **kwargs):
        DimonRESTBase.__init__(self, host, port)
        try:
            self._parse_args(**kwargs)
        except KeyError:
            logging.error("DimonHost: Invalid arguments")
            return False
        self._update_url()
        return True

    def _parse_args(self, **kwargs):
        pass

    def _update_url(self):
        self.get_url = self.base_url + '/monitor/host'
        self.del_url = self.get_url
        self.post_url = self.get_url


class DimonLatency(DimonRESTBase):
    def __init__(self, host, port, **kwargs):
        DimonRESTBase.__init__(self, host, port)
        self.__host_regex = re.compile("(?=^.{1,254}$)(^(?:(?!\d|-)[a-zA-Z0-9\-]{1,63}(?<!-)\.?)+(?:[a-zA-Z]{2,})$)")
        self.__ip_regex = re.compile("^(?:[0-9]{1,3}\.){3}[0-9]{1,3}$")
        try:
            self._parse_args(**kwargs)
        except KeyError:
            logging.error("DimonLatency: Invalid arguments, excepts valid `target` hostname or address")
            return False
        self._update_url()
        return True

    def _parse_args(self, **kwargs):
        # TODO: Should we throw another exception?
        self.target = kwargs['target']
        if not (self.__host_regex.match(self.target) or self.__ip_regex.match(self.target)):
            raise KeyError

    def _update_url(self):
        self.get_url = self.base_url + '/monitor/latency/%s' % self.target
        self.del_url = self.get_url
        self.post_url = self.get_url


class DimonSocket(DimonRESTBase):
    def __init__(self, host, port, **kwargs):
        DimonRESTBase.__init__(self, host, port)
        try:
            self._parse_args(**kwargs)
        except KeyError:
            logging.error("DimonSocket: Invalid arguments, excepts proto (tcp|udp), direction(bi|src|dst) and valid sport ")
            raise RuntimeError
        self._update_url()

    def _parse_args(self, **kwargs):
        # TODO: Should we throw another exception?
        self.proto = kwargs['proto']
        self.direction = kwargs['direction']
        self.port = int(kwargs['sport'])
        if (self.port <= 0) or (not self.proto in ['tcp', 'udp']) or (not self.direction in ['bi', 'src', 'dst']):
            raise KeyError

    def _update_url(self):
        self.get_url = self.base_url + '/monitor/socket'
        self.post_url = self.get_url + '/%s/%s/%s' % (self.proto, self.direction, self.port)
        self.del_url = self.post_url
