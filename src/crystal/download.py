"""
Provides services for downloading a ResourceRevision.
"""

from collections import defaultdict
from crystal.model import ResourceRevision
from http.client import HTTPConnection, HTTPSConnection
import urllib.error
import urllib.request
from urllib.parse import urlparse

# The User-Agent string to use for downloads, or None to omit.
_USER_AGENT_STRING = 'Crystal/0.1 (crystalbot@dafoster.net)'

def download_resource_revision(resource, progress_listener):
    """
    Synchronously downloads a revision of the specified resource.
    For internal use by DownloadResourceBodyTask.
    
    Arguments:
    resource -- the resource to download.
    progress_listener -- the DownloadResourceBodyTask that progress updates will be sent to.
    """
    try:
        progress_listener.subtitle = 'Waiting for response...'
        (metadata, body_stream) = ResourceRequest.create(resource.url)()
        
        # TODO: Provide incremental feedback such as '7 KB of 15 KB'
        progress_listener.subtitle = 'Receiving response...'
        return ResourceRevision.create_from_response(resource, metadata, body_stream)
    except Exception as error:
        return ResourceRevision.create_from_error(resource, error)

class ResourceRequest(object):
    """
    Encapsulates a request to fetch a resource.
    """
    
    @staticmethod
    def create(url):
        """
        Raises:
        urllib.error.URLError -- if URL scheme not supported.
        """
        url_parts = urlparse(url)
        if url_parts.scheme in ('http', 'https'):
            return HttpResourceRequest(url)
        elif url_parts.scheme == 'ftp':
            return UrlResourceRequest(url)
        else:
            raise urllib.error.URLError('URL scheme "%s" is not supported.' % url_parts.scheme)
    
    def __call__(self):
        """
        Returns a (metadata, body_stream) tuple, where
            `metadata` is a JSON-serializable dictionary or None and
            `body_stream` is a file-like object (which supports `read` and `close`).
        
        Raises any Exception.
        """
        raise NotImplementedError

class HttpResourceRequest(ResourceRequest):
    def __init__(self, url):
        if urlparse(url).scheme not in ('http', 'https'):
            raise ValueError
        self.url = url
    
    def __call__(self):
        url_parts = urlparse(self.url)
        scheme = url_parts.scheme
        host_and_port = url_parts.netloc
        
        if scheme == 'http':
            conn = HTTPConnection(host_and_port)
        elif scheme == 'https':
            conn = HTTPSConnection(host_and_port)
        else:
            raise ValueError('Not an HTTP(S) URL.')
        headers = {
            'User-Agent': _USER_AGENT_STRING,
        }
        conn.request('GET', self.url, headers=headers)
        response = conn.getresponse()
        
        metadata = {
            'http_version': response.version,
            'status_code': response.status,
            'reason_phrase': response.reason,
            'headers': response.getheaders()
        }
        class HttpResourceBodyStream(object):
            close = conn.close
            read = response.read
            fileno = response.fileno
            mode = 'rb'
        return (metadata, HttpResourceBodyStream())
    
    def __repr__(self):
        return 'HttpResourceRequest(%s)' % repr(self.url)

class UrlResourceRequest(ResourceRequest):
    def __init__(self, url):
        self.url = url
    
    def __call__(self):
        request = urllib.request.Request(self.url)
        response = urllib.request.urlopen(request)
        return (None, response)
    
    def __repr__(self):
        return 'UrlResourceRequest(%s)' % repr(self.url)
