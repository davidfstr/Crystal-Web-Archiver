# --------------------------------------------------------------------------------------------------
# Task

from crystal.model import ResourceRevision
import urllib2

class _ResourceBodyDownloadTask(object): # TODO: extend from Task base class, once it is defined
    def __init__(self, resource):
        self._resource = resource
        
        self.title = 'Downloading: %s' % (resource.url,)
        self.subtitle = 'Queued.'
        self.subtasks = []
    
    def __call__(self):
        """Synchronously runs this task."""
        request = None
        try:
            # TODO: Migrate to httplib instead of urllib2, so that exact request headers can be saved
            #       and redirections can be handled directly. Note that non-HTTP(S) URLs such as FTP
            #       should still be handled. And don't forget to get a nice exception for unsupported
            #       URI schemes (such as mailto).
            self.subtitle = 'Waiting for response...'
            request = urllib2.Request(self._resource.url)
            response_body_stream = urllib2.urlopen(request)
            try:
                # TODO: Provide incremental feedback such as '7 KB of 15 KB'
                self.subtitle = 'Receiving response...'
                response_body = response_body_stream.read() # may raise IOError
            finally:
                response_body_stream.close()
            
            return ResourceRevision(request=request, response_body=response_body)
        except Exception as e:
            return ResourceRevision(download_error=e, request=request)
    
    @property
    def subtitle(self):
        return self._subtitle
    
    @subtitle.setter
    def subtitle(self, value):
        # TODO: Display updates in GUI instead of CLI
        print '-> %s' % (value,)
        self._subtitle = value

# --------------------------------------------------------------------------------------------------
# Other
