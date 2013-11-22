    # -*- coding: utf-8 -*-

__version__ = "0.1.0"
__api__ = "1"
version_info = tuple([int(num) for num in __version__.split('.')])

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
        return self._r('get', self.url + path)

    def start_monitor(self, timeout = None, raise_error = True):
        return self._r('post', self.url)

    def stop_monitor(self, timeout = None, raise_error = True):
        return self._r('delete', self.url)

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
            logging.error("DimonClientPID: Invalid arguments, excepts pid and pid >= 0 .")
        self._update_url()

    def _parse_args(self, **kwargs):
        # TODO: Should we throw another exception?
        self.pid = int(kwargs['pid'])
        if (self.pid <= 0):
            raise KeyError

    def _update_url(self):
        self.url = self.base_url + '/monitor/pid/%s' % self.pid


