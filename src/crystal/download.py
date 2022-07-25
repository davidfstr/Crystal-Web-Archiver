"""
Provides services for downloading a ResourceRevision.
"""

from collections import defaultdict
from crystal import __version__
from crystal.model import Resource, ResourceRevision, ResourceRevisionMetadata
from crystal.util.xos import is_windows
from http.client import HTTPConnection, HTTPSConnection
import io
import platform
import ssl
from typing import Dict, Optional, Tuple
import urllib.error
import urllib.request
from urllib.parse import urlparse


_HTTP_REQUEST_TIMEOUT = 10  # seconds

# The User-Agent string to use for downloads, or None to omit.
_USER_AGENT_STRING = 'Crystal/%s (https://dafoster.net/projects/crystal-web-archiver/)' % __version__

# Whether to log verbose output related to HTTP requests and responses.
# Can be used to inspect the exact request & response lines and headers exchanged.
# 
# For temporary experimentation in the shell.
# 
# TODO: Alter the format of the verbose output to be as easy to read as
#       curl's similar -v option.
_VERBOSE_HTTP_REQUESTS_AND_RESPONSES = False

# Extra HTTP headers to add to every request, overriding any standard headers.
# 
# For temporary experimentation in the shell.
# 
# WARNING: These headers will NOT be persisted in the downloaded ResourceRevision
#          and therefore it will not be possible to repeat a similar request in
#          the future to get a more up-to-date version of a prior revision.
_EXTRA_HEADERS = dict()  # type: Dict[str, str]


def download_resource_revision(resource: Resource, progress_listener) -> ResourceRevision:
    """
    Synchronously downloads a revision of the specified resource.
    For internal use by DownloadResourceBodyTask.
    
    Arguments:
    * resource -- the resource to download.
    * progress_listener -- the DownloadResourceBodyTask that progress updates will be sent to.
    """
    
    if resource.project.request_cookie_applies_to(resource.url):
        request_cookie = resource.project.request_cookie
    else:
        request_cookie = None
    
    try:
        progress_listener.subtitle = 'Waiting for response...'
        (metadata, body_stream) = ResourceRequest.create(
            resource.url, 
            request_cookie
        )()
        try:
            # TODO: Provide incremental feedback such as '7 KB of 15 KB'
            progress_listener.subtitle = 'Receiving response...'
            return ResourceRevision.create_from_response(
                resource,
                metadata,
                body_stream,
                request_cookie
            )
        finally:
            body_stream.close()
    except Exception as error:
        return ResourceRevision.create_from_error(
            resource,
            error,
            request_cookie
        )


class ResourceRequest:
    """
    Encapsulates a request to fetch a resource.
    """
    
    @staticmethod
    def create(url: str, request_cookie: Optional[str]=None) -> 'ResourceRequest':
        """
        Raises:
        * urllib.error.URLError -- if URL scheme not supported.
        """
        url_parts = urlparse(url)
        if url_parts.scheme in ('http', 'https'):
            return HttpResourceRequest(url, request_cookie)
        elif url_parts.scheme == 'ftp':
            return UrlResourceRequest(url)
        else:
            raise urllib.error.URLError('URL scheme "%s" is not supported.' % url_parts.scheme)
    
    def __call__(self) -> Tuple[Optional[ResourceRevisionMetadata], io.BytesIO]:
        """
        Returns a (metadata, body_stream) tuple, where
            `metadata` is a JSON-serializable dictionary or None and
            `body_stream` is a file-like object (which supports `read` and `close`).
        
        Raises any Exception.
        """
        raise NotImplementedError


class HttpResourceRequest(ResourceRequest):
    def __init__(self, url: str, request_cookie: Optional[str]=None) -> None:
        if urlparse(url).scheme not in ('http', 'https'):
            raise ValueError
        self.url = url
        self._request_cookie = request_cookie
    
    def __call__(self):
        url_parts = urlparse(self.url)
        scheme = url_parts.scheme
        host_and_port = url_parts.netloc
        path = url_parts.path or '/'
        
        if scheme == 'http':
            conn = HTTPConnection(
                host_and_port,
                timeout=_HTTP_REQUEST_TIMEOUT,
            )
        elif scheme == 'https':
            conn = HTTPSConnection(
                host_and_port,
                timeout=_HTTP_REQUEST_TIMEOUT,
                context=get_ssl_context(),
            )
        else:
            raise ValueError('Not an HTTP(S) URL.')
        
        if _VERBOSE_HTTP_REQUESTS_AND_RESPONSES:
            conn.set_debuglevel(1)
        
        headers = {}
        if _USER_AGENT_STRING is not None:
            headers['User-Agent'] = _USER_AGENT_STRING
        if self._request_cookie is not None:
            headers['Cookie'] = self._request_cookie
        for (k, v) in _EXTRA_HEADERS.items():
            headers[k] = v
        
        conn.request('GET', path, headers=headers)
        response = conn.getresponse()
        
        metadata = ResourceRevisionMetadata({
            'http_version': response.version,
            'status_code': response.status,
            'reason_phrase': response.reason,
            'headers': response.getheaders()
        })
        # TODO: Defining a class inline like this is probably expensive,
        #       especially in memory usage. Please define class externally
        #       and just instantiate here.
        class HttpResourceBodyStream:
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
        response = urllib.request.urlopen(request, context=get_ssl_context())
        return (None, response)
    
    def __repr__(self):
        return 'UrlResourceRequest(%s)' % repr(self.url)


_SSL_CONTEXT = None

def get_ssl_context():
    global _SSL_CONTEXT
    if _SSL_CONTEXT is None:
        if is_windows():
            # Use Windows default CA certificates
            cafile = None
        else:
            # Use bundled certifi CA certificates
            import certifi
            cafile = certifi.where()
        _SSL_CONTEXT = ssl.create_default_context(cafile=cafile)
    return _SSL_CONTEXT
