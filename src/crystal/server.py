"""
Implements an HTTP server that serves resource revisions from a Project.
Runs on its own daemon thread.
"""

from datetime import datetime
from html import escape as html_escape
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, HTTPServer
from io import StringIO
import os
import re
import shutil
from textwrap import dedent
from typing import Optional
from urllib.parse import parse_qs, ParseResult, urljoin, urlparse, urlunparse
from .xthreading import bg_call_later, fg_call_and_wait

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
            print_success('Server started on port %s.' % port)
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

_REQUEST_PATH_IN_ARCHIVE_RE = re.compile(r'^/_/([^/]+)/(.+)$')

# Set of archived headers that may be played back as-is
_HEADER_WHITELIST = set([
    'date',
    'vary',
    'content-language',
    'content-type',
    'server',
    'last-modified',
    'etag',
    'content-encoding',
    'x-xss-protection',
    'x-content-type-options',
    'x-frame-options',
    
    # CORS
    'access-control-allow-origin',
    'access-control-allow-methods',
    'access-control-expose-headers',
    
    # Timing
    'timing-allow-origin',  # enable cross-origin access to timing API
    'server-timing',
    
    # Vendor-specific: AWS Cloudfront
    'x-amz-cf-id',
    'x-amz-cf-pop',
    'x-amz-storage-class',
    
    # Vendor-specific: Cloudflare
    'cf-cache-status',
    'cf-ray',
    'cf-request-id',
    
    # Vendor-specific: Google Cloud
    'x-goog-generation',
    'x-goog-hash',
    'x-goog-metageneration',
    'x-goog-storage-class',
    'x-goog-stored-content-encoding',
    'x-goog-stored-content-length',
    'x-guploader-uploadid',
    
    # Vendor-specific: Fastly
    'detected-user-agent',
    'normalized-user-agent',
    'request_came_from_shield',
])
# Set of archived headers known to cause problems if blindly played back
_HEADER_BLACKLIST = set([
    # Connection
    'transfer-encoding',# overridden by this web server
    'content-length',   # overridden by this web server
    'accept-ranges',    # partial content ranges not supported by this server
    'connection',       # usually: keep-alive
    'via',              # this web server is not a proxy
    
    # Cache
    'cache-control',
    'age',
    'expires',
    
    # Cookie
    'set-cookie',       # don't allow cookies to be set by archived site
    'p3p',              # never allow third party cookies
    
    # HTTPS & Certificates
    'expect-ct',        # don't require Certificate Transparency
    'strict-transport-security',  # don't require HTTPS
    
    # Logging
    'nel',              # don't enable network request logging
    'report-to',        # don't enable Content Security Policy logging
    
    # Referer
    'referrer-policy',  # don't omit referer because used to dynamically rewrite links
    
    # Protocol Upgrades
    'alt-svc',          # we don't support HTTP/2, QUIC, or any alternate protocol advertised by this
    
    # X-RateLimit
    'x-ratelimit-limit',
    'x-ratelimit-remaining',
    'x-ratelimit-count',
    'x-ratelimit-reset',
    
    # Ignored non-problematic headers
    # TODO: Consider moving these headers to the _HEADER_WHITELIST
    'x-powered-by',
    'x-monk',
    'x-cache',
    'x-ecn-p',
    'vtag',
])

class _RequestHandler(BaseHTTPRequestHandler):
    @property
    def project(self):
        return self.server.project
    
    @property
    def _server_host(self) -> str:
        return 'localhost:%s' % self.server.server_port
    
    # === Request Properties ===
    
    @property
    def request_host(self) -> str:
        return self.headers.get('Host', self._server_host)
    
    @property
    def referer(self) -> Optional[str]:
        return self.headers.get('Referer')
    
    # === Handle Incoming Request ===
    
    def parse_request(self):  # override
        # If we receive a request line with clearly binary data,
        # such as from an incoming HTTPS connection,
        # reject it immediately, before BaseHTTPRequestHandler
        # tries to print a ton of binary data to the console
        # as an error.
        if b'\x00' in self.raw_requestline:
            # Populate globals that send_error() requires
            self.command = None
            self.request_version = self.default_request_version
            self.close_connection = True
            self.requestline = '<binary data>'
            
            self.send_error(
                HTTPStatus.BAD_REQUEST,
                "Bad request version")
            return False
        
        return super().parse_request()
    
    def do_GET(self):  # override
        request_host = self.request_host
        request_url = 'http://%s%s' % (request_host, self.path)
        
        # Serve resource revision in archive
        archive_url = self.get_archive_url(self.path)
        if archive_url is not None:
            # Fill in missing '/' path if needed
            archive_urlparts = urlparse(archive_url)
            if archive_urlparts.path == '':
                archive_url_with_path = urlunparse(ParseResult(
                    scheme=archive_urlparts.scheme,
                    netloc=archive_urlparts.netloc,
                    path='/',
                    params=archive_urlparts.params,
                    query=archive_urlparts.query,
                    fragment=archive_urlparts.fragment,
                ))
                redirect_url = self.get_request_url(archive_url_with_path)
                
                self.send_redirect(redirect_url)
                return
            
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
            
            self.send_revision(revision, archive_url)
            return
        
        # Dynamically rewrite incoming link from archived resource revision
        referer = self.referer  # cache
        if referer is not None:
            referer_urlparts = urlparse(referer)
            if ((referer_urlparts.netloc == '' and referer_urlparts.path.startswith('/')) or 
                    referer_urlparts.netloc == self._server_host):
                referer_archive_url = self.get_archive_url(referer_urlparts.path)
                referer_archive_urlparts = urlparse(referer_archive_url)
                requested_archive_url = '%s://%s%s' % (
                    referer_archive_urlparts.scheme,
                    referer_archive_urlparts.netloc,
                    self.path,
                )
                redirect_url = self.get_request_url(requested_archive_url)
                
                print_warning('*** Dynamically rewriting link from %s: %s' % (
                    referer_archive_url,
                    requested_archive_url,
                ))
                
                self.send_redirect(redirect_url, vary_referer=True)
                return
        
        # Serve Welcome page
        path_parts = urlparse(self.path)
        if path_parts.path == '/':
            self.send_welcome_page(parse_qs(path_parts.query), vary_referer=True)
            return
        
        # Serve Not Found page
        self.send_not_found_page(vary_referer=True)
        return
    
    # === Send Page ===
    
    def send_welcome_page(self, query_params: dict[str, str], *, vary_referer: bool) -> None:
        # TODO: Is this /?url=** path used anywhere anymore?
        if 'url' in query_params:
            archive_url = query_params['url'][0]
            redirect_url = self.get_request_url(archive_url)
            
            self.send_redirect(redirect_url, vary_referer=vary_referer)
            return
        
        self.send_response(200)
        self.send_header('Content-Type', 'text/html')
        if vary_referer:
            self.send_header('Vary', 'Referer')
        self.end_headers()
        
        self.wfile.write(dedent(
            """
            <!DOCTYPE html>
            <html>
            <head>
                <meta charset="utf-8" />
                <title>Welcome | Crystal Web Archiver</title>
            </head>
            <body>
                <p>Enter the URL of a page to load from the archive:</p>
                <form action="/">
                    URL: <input type="text" name="url" value="http://" /><input type="submit" value="Go" />
                </form>
            </body>
            </html>
            """
        ).lstrip('\n').encode('utf-8'))
    
    def send_not_found_page(self, *, vary_referer: bool) -> None:
        self.send_response(404)
        self.send_header('Content-Type', 'text/html')
        if vary_referer:
            self.send_header('Vary', 'Referer')
        self.end_headers()
        
        self.wfile.write(dedent(
            """
            <!DOCTYPE html>
            <html>
            <head>
                <meta charset="utf-8" />
                <title>Not Found | Crystal Web Archiver</title>
            </head>
            <body>
                <p>There is no page here.</>
                <p>Return to <a href="/">home page</a>?</p>
            </body>
            </html>
            """
        ).lstrip('\n').encode('utf-8'))
    
    def send_resource_not_in_archive(self, archive_url: str) -> None:
        self.send_response(404)
        self.send_header('Content-Type', 'text/html')
        self.end_headers()
        
        self.wfile.write((dedent(
            """
            <!DOCTYPE html>
            <html>
            <head>
                <meta charset="utf-8" />
                <title>Not in Archive | Crystal Web Archiver</title>
            </head>
            <body>
                <p>The requested resource was not found in the archive.</p>
                <p>The original resource is located here: <a href="%(archive_url)s">%(archive_url)s</a></p>
            </body>
            </html>
            """
        ).lstrip('\n') % {
            # TODO: Shouldn't this be HTML-escaped?
            'archive_url': archive_url
        }).encode('utf-8'))
        
        print_error('*** Requested resource not in archive: ' + archive_url)
    
    def send_redirect(self, redirect_url: str, *, vary_referer: bool=False) -> None:
        self.send_response(307)
        self.send_header('Location', redirect_url)
        if vary_referer:
            self.send_header('Vary', 'Referer')
        self.end_headers()
    
    # === Send Revision ===
    
    def send_revision(self, revision, archive_url) -> None:
        if revision.error is not None:
            self.send_resource_error(revision.error_dict, archive_url)
            return
        assert revision.has_body
        
        if revision.is_http:
            self.send_http_revision(revision)
        else:
            self.send_generic_revision(revision)
    
    def send_resource_error(self, error_dict, archive_url) -> None:
        self.send_response(400)
        self.send_header('Content-Type', 'text/html')
        self.end_headers()
        
        self.wfile.write((dedent(
            """
            <!DOCTYPE html>
            <html>
            <head>
                <meta charset="utf-8" />
                <title>Fetch Error | Crystal Web Archiver</title>
            </head>
            <body>
                <p>
                    A <tt>%(error_type)s</tt> error with message <tt>%(error_message)s</tt>
                    was encountered when fetching this resource.
                </p>
                <p>The original resource is located here: <a href="%(archive_url)s">%(archive_url)s</a></p>
            </body>
            </html>
            """
        ).lstrip('\n') % {
            'error_type': (
                html_escape(error_dict['type'])
                if error_dict is not None
                else 'unknown'
            ),
            'error_message': (
                html_escape(error_dict['message'])
                if error_dict is not None and error_dict['message'] is not None
                else 'unknown'
            ),
            # TODO: Shouldn't this be HTML-escaped?
            'archive_url': archive_url
        }).encode('utf-8'))
        
        print_error('*** Requested resource was fetched with error: ' + archive_url)
    
    def send_http_revision(self, revision) -> None:
        metadata = revision.metadata
        
        # Determine Content-Type to send
        sender = self.send_revision_body(revision)
        content_type_with_options = (
            next(sender) or 
            revision.declared_content_type_with_options
        )
        
        # Determine headers to send
        headers = [[k, v] for (k, v) in metadata['headers']]  # clone, make mutable
        if content_type_with_options is not None:
            # Replace first preexisting 'Content-Type' header with new value,
            # or append new 'Content-Type' header to end of headers
            for kv in headers:
                (k, v) = kv
                if k.lower() == 'content-type':
                    kv[1] = content_type_with_options
                    break
            else:
                headers.append(['content-type', content_type_with_options])
        
        # Send status line
        self.send_response(metadata['status_code'], metadata['reason_phrase'])
        
        # Send headers
        for (name, value) in headers:
            if name.lower() == 'location':
                self.send_header(name, self.get_request_url(value))
                continue
                
            if name.lower() in _HEADER_WHITELIST:
                self.send_header(name, value)
            else:
                if name.lower() not in _HEADER_BLACKLIST:
                    print_warning(
                        '*** Ignoring unknown header in archive: %s: %s' % (name, value))
                continue
        self.end_headers()
        
        # Send body
        try:
            next(sender)
        except StopIteration:
            pass
        else:
            raise AssertionError()
    
    def send_generic_revision(self, revision) -> None:
        # Determine what Content-Type to send
        sender = self.send_revision_body(revision)
        content_type_with_options = (
            next(sender) or 
            revision.declared_content_type_with_options
        )
        
        # Send status line
        self.send_response(200)
        
        # Send headers
        if content_type_with_options is not None:
            self.send_header('Content-Type', content_type_with_options)
        self.end_headers()
        
        # Send body
        try:
            next(sender)
        except StopIteration:
            pass
        else:
            raise AssertionError()
    
    def send_revision_body(self, revision) -> None:
        assert revision.has_body
        
        (doc, links, content_type_with_options) = revision.document_and_links()
        
        # Send headers with content type
        yield content_type_with_options
        
        # Send body
        if doc is None:
            # Not a document. Cannot rewrite content.
            with revision.open() as body:
                try:
                    shutil.copyfileobj(body, self.wfile)
                except BrokenPipeError:
                    # Browser did disconnect early
                    return
        else:
            # Rewrite links in document
            base_url = revision.resource.url
            for link in links:
                relative_url = link.relative_url
                absolute_url = urljoin(base_url, relative_url)
                request_url = self.get_request_url(absolute_url)
                link.relative_url = request_url
            
            # Output altered document
            try:
                self.wfile.write(str(doc).encode('utf-8'))
            except BrokenPipeError:
                # Browser did disconnect early
                return
    
    # === URL Transformation ===
    
    @staticmethod
    def get_archive_url(request_path: str) -> Optional[str]:
        match = _REQUEST_PATH_IN_ARCHIVE_RE.match(request_path)
        if match:
            (scheme, rest) = match.groups()
            archive_url = '%s://%s' % (scheme, rest)
            return archive_url
        else:
            return None
    
    def get_request_url(self, archive_url: str) -> str:
        return _RequestHandler.get_request_url_with_host(archive_url, self.request_host)
    
    @staticmethod
    def get_request_url_with_host(archive_url: str, request_host: str) -> str:
        """
        Given the absolute URL of a resource, returns the URL that should be used to
        request it from the archive server.
        """
        archive_url_parts = urlparse(archive_url)
        
        request_scheme = 'http'
        request_netloc = request_host
        request_path = '_/%s/%s%s' % (
            archive_url_parts.scheme,
            archive_url_parts.netloc, archive_url_parts.path)
        request_params = archive_url_parts.params
        request_query = archive_url_parts.query
        request_fragment = archive_url_parts.fragment
        
        request_url_parts = (
            request_scheme, request_netloc, request_path,
            request_params, request_query, request_fragment
        )
        request_url = urlunparse(request_url_parts)
        return request_url
    
    # === Logging ===
    
    def log_error(self, format, *args):  # override
        print_error(format % args)
    
    def log_message(self, format, *args):  # override
        print_info(format % args)
        
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

def print_success(message: str) -> None:
    print(colorize(_TERM_FG_GREEN, message))

def print_error(message: str) -> None:
    print(colorize(_TERM_FG_RED, message))

def print_warning(message: str) -> None:
    print(colorize(_TERM_FG_YELLOW, message))

def print_info(message: str) -> None:
    print(colorize(_TERM_FG_CYAN, message))

# ------------------------------------------------------------------------------