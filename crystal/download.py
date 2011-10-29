from collections import defaultdict
from crystal.model import ResourceRevision
import httplib
import urllib2
from urlparse import urlparse

class Task(object):
    def _get_subtitle(self):
        return self._subtitle
    def _set_subtitle(self, value):
        # TODO: Display updates in GUI instead of CLI
        print '-> %s' % (value,)
        self._subtitle = value
    subtitle = property(_get_subtitle, _set_subtitle)

class ResourceDownloadTask(Task):
    def __init__(self, resource):
        self._resource = resource
        
        self.title = 'Downloading: %s' % (resource.url,)
        self.subtitle = 'Queued.'
        self.subtasks = []
    
    def __call__(self):
        """Synchronously runs this task."""
        try:
            self.subtitle = 'Waiting for response...'
            (metadata, body_stream) = ResourceRequest.create(self._resource.url)()
            
            # TODO: Provide incremental feedback such as '7 KB of 15 KB'
            self.subtitle = 'Receiving response...'
            return ResourceRevision.create_from_response(self._resource, metadata, body_stream)
        except Exception as error:
            return ResourceRevision.create_from_error(self._resource, error)

class ResourceRequest(object):
    """
    Encapsulates a request to fetch a resource.
    """
    
    @staticmethod
    def create(url):
        """
        Raises:
        urllib2.URLError -- if URL scheme not supported.
        """
        url_parts = urlparse(url)
        if url_parts.scheme in ('http', 'https'):
            return HttpResourceRequest(url)
        elif url_parts.scheme == 'ftp':
            return UrlResourceRequest(url)
        else:
            raise URLError('URL scheme "%s" is not supported.' % url_parts.scheme)
    
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
            conn = httplib.HTTPConnection(host_and_port)
        elif scheme == 'https':
            conn = httplib.HTTPSConnection(host_and_port)
        else:
            raise ValueError('Not an HTTP(S) URL.')
        conn.request('GET', self.url) # no special body or headers
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
        request = urllib2.Request(self.url)
        response = urllib2.urlopen(request)
        return (None, response)
    
    def __repr__(self):
        return 'UrlResourceRequest(%s)' % repr(self.url)
