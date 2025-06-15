"""
Provides services for downloading a ResourceRevision.
"""

from collections.abc import Iterable
from crystal import __version__
from crystal.model import (
    ProjectHasTooManyRevisionsError, Resource, ResourceRevision,
    ResourceRevisionMetadata,
)
from crystal.util.xos import is_mac_os, is_windows
from crystal.util.xthreading import fg_call_and_wait
from http.client import HTTPConnection, HTTPSConnection
import ssl
import truststore
from typing import BinaryIO, cast, Collection, Dict, TYPE_CHECKING
import urllib.error
from urllib.parse import urlparse
import urllib.request

if TYPE_CHECKING:
    from crystal.task import DownloadResourceBodyTask


HTTP_REQUEST_TIMEOUT = 10  # seconds

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


def download_resource_revision(
        resource: Resource,
        progress_listener: 'DownloadResourceBodyTask',
        ) -> ResourceRevision:
    """
    Synchronously downloads a revision of the specified resource.
    For internal use by DownloadResourceBodyTask.
    
    Arguments:
    * resource -- the resource to download.
    * progress_listener -- the DownloadResourceBodyTask that progress updates will be sent to.
    
    Raises:
    * ProjectHasTooManyRevisionsError
    """
    
    if resource.project.request_cookie_applies_to(resource.url):
        request_cookie = resource.project.request_cookie
    else:
        request_cookie = None
    
    if resource.definitely_has_no_revisions:
        known_etags = ()  # type: Collection[str]
    else:
        known_etags = fg_call_and_wait(lambda: resource.revision_for_etag().keys())
    
    try:
        progress_listener.subtitle = 'Waiting for response...'
        (metadata, body_stream) = ResourceRequest.create(
            resource.url, 
            request_cookie,
            known_etags,
        )()
        try:
            # If an HTTP 304 response was received without an ETag,
            # try to populate the ETag value so that future calls to
            # ResourceRevision.resolve_http_304() will actually be
            # able to find the original revision
            if metadata is not None and metadata['status_code'] == 304:
                response_etags = [
                    cur_value
                    for (cur_name, cur_value) in metadata['headers']
                    if cur_name.lower() == 'etag'
                ]
                response_etag = response_etags[0] if len(response_etags) > 0 else None
                if response_etag is None and len(known_etags) == 1:
                    (known_etag,) = known_etags
                    metadata['headers'].append(['ETag', known_etag])
            
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
    except ProjectHasTooManyRevisionsError:
        raise
    except Exception as error:
        # TODO: Handle rare case where this raises an IO error when writing
        #       revision to the database, perhaps by creating/returning
        #       an *unsaved* ResourceRevision in memory.
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
    def create(
            url: str,
            request_cookie: str | None=None,
            known_etags: Iterable[str]=()
            ) -> 'ResourceRequest':
        """
        Raises:
        * urllib.error.URLError -- if URL scheme not supported.
        """
        url_parts = urlparse(url)
        if url_parts.scheme in ('http', 'https'):
            return HttpResourceRequest(url, request_cookie, known_etags)
        elif url_parts.scheme == 'ftp':
            return UrlResourceRequest(url)
        else:
            raise urllib.error.URLError('URL scheme "%s" is not supported.' % url_parts.scheme)
    
    def __call__(self) -> tuple[ResourceRevisionMetadata | None, BinaryIO]:
        """
        Returns a (metadata, body_stream) tuple, where
            `metadata` is a JSON-serializable dictionary or None and
            `body_stream` is a file-like object (which supports `read` and `close`).
        
        Raises any Exception.
        """
        raise NotImplementedError


class HttpResourceRequest(ResourceRequest):
    def __init__(self, 
            url: str,
            request_cookie: str | None=None,
            known_etags: Iterable[str]=()
            ) -> None:
        if urlparse(url).scheme not in ('http', 'https'):
            raise ValueError('Expected URL with http or https scheme')
        self.url = url
        self._request_cookie = request_cookie
        self._known_etags = known_etags
    
    def __call__(self) -> tuple[ResourceRevisionMetadata, BinaryIO]:
        url_parts = urlparse(self.url)
        scheme = url_parts.scheme
        host_and_port = url_parts.netloc
        path_and_query = (
            (url_parts.path or '/') + 
            ('' if url_parts.query == '' else f'?{url_parts.query}')
        )
        
        if scheme == 'http':
            conn = HTTPConnection(
                host_and_port,
                timeout=HTTP_REQUEST_TIMEOUT,
            )
        elif scheme == 'https':
            conn = HTTPSConnection(
                host_and_port,
                timeout=HTTP_REQUEST_TIMEOUT,
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
        if_none_match_value = ', '.join(self._known_etags)
        if if_none_match_value != '':
            headers['If-None-Match'] = if_none_match_value
        for (k, v) in _EXTRA_HEADERS.items():
            headers[k] = v
        
        conn.request('GET', path_and_query, headers=headers)
        response = conn.getresponse()
        
        metadata = ResourceRevisionMetadata({
            'http_version': response.version,
            'status_code': response.status,
            'reason_phrase': response.reason,
            'headers': [[k, v] for (k, v) in response.getheaders()]
        })
        body_stream = _HttpResourceBodyStream(
            close=conn.close,
            read=response.read,
            readinto=response.readinto,
            fileno=response.fileno,
            mode='rb')
        return (metadata, cast(BinaryIO, body_stream))
    
    def __repr__(self):
        return 'HttpResourceRequest(%s)' % repr(self.url)


class _HttpResourceBodyStream:
    """
    File-like object for reading from an HTTP resource.
    """
    def __init__(self, close, read, readinto, fileno, mode) -> None:
        self.close = close
        self.read = read
        self.readinto = readinto
        self.fileno = fileno
        self.mode = mode


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

def get_ssl_context() -> ssl.SSLContext:
    """
    Creates the SSLContext used to make HTTPS connections.
    
    In particular, loads any CA certificates needed to authenticate those connections.
    """
    global _SSL_CONTEXT
    if _SSL_CONTEXT is None:
        # Load certifications from OS certificate store.
        # 
        # Optimize options to connect from client to server
        # (rather than optimizing for a server receiving a client connection),
        # emulating the behavior of ssl.create_default_context(purpose=ssl.Purpose.SERVER_AUTH).
        # 
        # On Linux:
        # - OpenSSL's $SSL_CERT_FILE and $SSL_CERT_DIR environment variables
        #   can be used to override the default CA certificates.
        # - Certificate locations for major distros are supported,
        #   with the authoritative list in truststore/_openssl.py:
        #   https://github.com/sethmlarson/truststore/blob/8725ad5ea26966eeb2960be24b85ca6c9371f11f/src/truststore/_openssl.py#L8-L17
        ctx = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ctx.verify_mode = ssl.CERT_REQUIRED
        ctx.check_hostname = True
        
        _SSL_CONTEXT = ctx  # export
    return _SSL_CONTEXT
