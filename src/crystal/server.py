"""
Implements an HTTP server that serves resource revisions from a Project.
Runs on its own daemon thread.
"""

from BaseHTTPServer import BaseHTTPRequestHandler, HTTPServer
from datetime import datetime
import os
import re
import urlparse
import shutil
from StringIO import StringIO
from xthreading import bg_call_later, fg_call_and_wait

_SERVER_PORT = 2797

def start(project):
    """
    Starts the archive server on a daemon thread.
    """
    port = _SERVER_PORT
    address = ('', port)
    server = HTTPServer(address, _RequestHandler)
    server.project = project
    def bg_task():
        try:
            print colorize(_TERM_FG_GREEN, 'Server started on port %s.' % port)
            server.serve_forever()
        finally:
            server.server_close()
    bg_call_later(bg_task, daemon=True)

def get_request_url(archive_url):
    """
    Given the absolute URL of a resource, returns the URL that should be used to
    request it from the archive server.
    """
    request_host = 'localhost:%s' % _SERVER_PORT
    return _RequestHandler.get_request_url_with_host(archive_url, request_host)

# ----------------------------------------------------------------------------------------

_SCHEME_REST_RE = re.compile(r'^/([^/]+)/(.+)$')

# Set of archived headers that may be played back as-is
_HEADER_WHITELIST = set([
    'date',
    'vary',
    'content-type',
    'server',
    'last-modified',
    'etag',
])
# Set of archived headers known to cause problems if blindly played back
_HEADER_BLACKLIST = set([
    'transfer-encoding',
    'content-length',
    'accept-ranges',
    'cache-control',
    'connection',
    'age',
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
        
        revision = fg_call_and_wait(resource.default_revision)
        if not revision:
            self.send_resource_not_in_archive(archive_url)
            return
        
        self.send_revision(revision)
    
    def send_welcome_page(self, query_params):
        if 'url' in query_params:
            archive_url = query_params['url'][0]
            redirect_url = self.get_request_url(archive_url)
            
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
        
        print colorize(_TERM_FG_RED, '*** Requested resource not in archive: ' + archive_url)
    
    def send_revision(self, revision):
        if revision.is_http:
            self.send_http_revision(revision)
        else:
            self.send_generic_revision(revision)
    
    def send_http_revision(self, revision):
        metadata = revision.metadata
        
        self.send_response(metadata['status_code'], metadata['reason_phrase'])
        
        for (name, value) in metadata['headers']:
            if name == 'location':
                self.send_header(name, self.get_request_url(value))
                continue
                
            if name in _HEADER_WHITELIST:
                self.send_header(name, value)
            else:
                if name not in _HEADER_BLACKLIST:
                    print colorize(_TERM_FG_YELLOW, 
                        '*** Ignoring unknown header in archive: %s: %s' % (name, value))
                continue
        self.end_headers()
        
        self.send_revision_body(revision)
    
    def send_generic_revision(self, revision):
        self.send_response(200)
        
        self.send_header('Content-Type', revision.content_type)
        self.end_headers()
        
        self.send_revision_body(revision)
    
    def send_revision_body(self, revision):
        (html, links) = revision.html_and_links()
        if html is None:
            # Not HTML. Cannot rewrite content.
            with revision.open() as body:
                shutil.copyfileobj(body, self.wfile)
        else:
            # Rewrite links in HTML
            base_url = revision.resource.url
            for link in links:
                relative_url = link.relative_url
                absolute_url = urlparse.urljoin(base_url, relative_url)
                request_url = self.get_request_url(absolute_url)
                link.relative_url = request_url
            
            # Output altered HTML
            shutil.copyfileobj(StringIO(str(html)), self.wfile)
    
    def get_request_url(self, archive_url):
        return _RequestHandler.get_request_url_with_host(archive_url, self.request_host)
    
    @staticmethod
    def get_request_url_with_host(archive_url, request_host):
        """
        Given the absolute URL of a resource, returns the URL that should be used to
        request it from the archive server.
        """
        archive_url_parts = urlparse.urlparse(archive_url)
        
        request_scheme = 'http'
        request_netloc = request_host
        request_path = '%s/%s%s' % (
            archive_url_parts.scheme,
            archive_url_parts.netloc, archive_url_parts.path)
        request_params = archive_url_parts.params
        request_query = archive_url_parts.query
        request_fragment = archive_url_parts.fragment
        
        request_url_parts = (
            request_scheme, request_netloc, request_path,
            request_params, request_query, request_fragment
        )
        request_url = urlparse.urlunparse(request_url_parts)
        return request_url
    
    def log_error(self, format, *args):
        print colorize(_TERM_FG_RED, format % args)
    
    def log_message(self, format, *args):
        print colorize(_TERM_FG_CYAN, format % args)
        
# ----------------------------------------------------------------------------------------
# Terminal Colors

_USE_COLORS = True

# ANSI color codes
# Obtained from: http://www.bri1.com/files/06-2008/pretty.py
_TERM_FG_BLUE =          '\033[0;34m'
_TERM_FG_BOLD_BLUE =     '\033[1;34m'
_TERM_FG_RED =           '\033[0;31m'
_TERM_FG_BOLD_RED =      '\033[1;31m'
_TERM_FG_GREEN =         '\033[0;32m'
_TERM_FG_BOLD_GREEN =    '\033[1;32m'
_TERM_FG_CYAN =          '\033[0;36m'
_TERM_FG_BOLD_CYAN =     '\033[1;36m'
_TERM_FG_YELLOW =        '\033[0;33m'
_TERM_FG_BOLD_YELLOW =   '\033[1;33m'
_TERM_RESET =            '\033[0m'

def colorize(color_code, str_value):
    return (color_code + str_value + _TERM_RESET) if _USE_COLORS else str_value

# ------------------------------------------------------------------------------