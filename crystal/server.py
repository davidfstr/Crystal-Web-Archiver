from BaseHTTPServer import BaseHTTPRequestHandler, HTTPServer
from datetime import datetime
import os
import re
import urlparse
import shutil

def run(project):
    port = 2797
    address = ('', port)
    server = HTTPServer(address, _RequestHandler)
    server.project = project
    try:
        print 'Server started on port %s.' % port
        server.serve_forever()
    finally:
        server.server_close()

_SCHEME_REST_RE = re.compile(r'^/([^/]+)/(.+)$')

# Set of archived headers that may be played back as-is
_HEADER_WHITELIST = set([
    'date',
    'vary',
    'content-type',
    'server'
])
# Set of archived headers known to cause problems if blindly played back
_HEADER_BLACKLIST = set([
    'transfer-encoding',
])

class _RequestHandler(BaseHTTPRequestHandler):
    @property
    def project(self):
        return self.server.project
    
    @property
    def request_host(self):
        return self.headers.get('Host', 'localhost:%s' % self.server.server_port)
    
    def do_GET(self):
        request_host = self.request_host
        request_url = 'http://%s%s' % (request_host, self.path)
        
        scheme_rest_match = _SCHEME_REST_RE.match(self.path)
        if not scheme_rest_match:
            path_parts = urlparse.urlparse(self.path)
            if path_parts.path == '/':
                query_params = urlparse.parse_qs(path_parts.query)
            else:
                query_params = {}
            
            self.send_welcome_page(query_params)
            return
        (scheme, rest) = scheme_rest_match.groups()
        archive_url = '%s://%s' % (scheme, rest)
        
        # TODO: Normalize archive url by stripping fragment (and maybe also {params, query}).
        #       This should probably be implemented in a static method on Resource,
        #       as this functionality should also be used by the Resource constructor.
        resource = self.project.get_resource(archive_url)
        if not resource:
            self.send_resource_not_in_archive(archive_url)
            return
        
        revision = resource.default_revision()
        if not revision:
            self.send_resource_not_in_archive(archive_url)
            return
        
        if revision.is_http:
            self.send_http_revision(revision)
            return
        else:
            self.send_generic_revision(revision)
            return
    
    def send_welcome_page(self, query_params):
        if 'url' in query_params:
            archive_url = query_params['url'][0]
            archive_url_parts = urlparse.urlparse(archive_url)
            
            # TODO: Avoid stripping {params, query, fragment}, if present
            redirect_url = 'http://%s/%s/%s%s' % (
                self.request_host,
                archive_url_parts.scheme,
                archive_url_parts.netloc, archive_url_parts.path)
            
            self.send_response(302)
            self.send_header('Location', redirect_url)
            self.end_headers()
            return
        
        self.send_response(200)
        self.send_header('Content-Type', 'text/html')
        self.end_headers()
        
        self.wfile.write("""
<!DOCTYPE html>
<html>
<head><title>Welcome | Crystal Web Archiver</title></head>
<body>
    <p>Enter the URL of a page to load from the archive:</p>
    <form action="/">
        URL: <input type="text" name="url" value="http://" /><input type="submit" value="Go" />
    </form>
</body>
</html>
""".strip())
    
    def send_resource_not_in_archive(self, archive_url):
        self.send_response(404)
        self.send_header('Content-Type', 'text/html')
        self.end_headers()
        
        self.wfile.write("""
<!DOCTYPE html>
<html>
<head><title>Not in Archive | Crystal Web Archiver</title></head>
<body>
    <p>The requested resource was not found in the archive.</p>
    <p>The original resource is located here: <a href="%(archive_url)s">%(archive_url)s</a></p>
</body>
</html>
""".strip() % {'archive_url': archive_url})
    
    def send_http_revision(self, revision):
        metadata = revision.metadata
        
        self.send_response(metadata['status_code'], metadata['reason_phrase'])
        
        # TODO: Rewrite links in headers (such as the Location header)
        for (name, value) in metadata['headers']:
            if name not in _HEADER_WHITELIST:
                if name not in _HEADER_BLACKLIST:
                    print '*** Ignoring unknown header in archive: %s: %s' % (name, value)
                continue
            self.send_header(name, value)
        self.end_headers()
        
        self.send_revision_body(revision)
    
    # TODO: Test
    def send_generic_revision(self, revision):
        self.send_response(200)
        
        self.send_header('Content-Type', revision.content_type)
        self.send_header('Content-Length', revision.size())
        self.end_headers()
        
        self.send_revision_body(revision)
    
    def send_revision_body(self, revision):
        # TODO: Rewrite links in HTML.
        #       Note that this will change the content length.
        with revision.open() as body:
            shutil.copyfileobj(body, self.wfile)
