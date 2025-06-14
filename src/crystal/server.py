"""
Implements an HTTP server that serves resource revisions from a Project.
Runs on its own daemon thread.
"""

from __future__ import annotations

from collections.abc import Callable, Generator
from crystal.doc.generic import Document, Link
from crystal.doc.html.soup import HtmlDocument
from crystal.model import (
    Project, Resource, ResourceGroup, ResourceRevision, RootResource,
)
from crystal.util.bulkheads import capture_crashes_to_stderr
from crystal.util.cli import (
    print_error, print_info, print_success, print_warning,
)
from crystal.util.ports import is_port_in_use, is_port_in_use_error
from crystal.util.test_mode import tests_are_running
from crystal.util.xthreading import (
    bg_affinity, bg_call_later, fg_call_and_wait,
    run_thread_switching_coroutine, SwitchToThread,
)
import datetime
from html import escape as html_escape  # type: ignore[attr-defined]
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, HTTPServer
from io import TextIOBase
import re
from textwrap import dedent
from typing import Literal, Optional
from typing_extensions import override
from urllib.parse import parse_qs, urljoin, urlparse, urlunparse

_DEFAULT_SERVER_PORT = 2797  # CRYS on telephone keypad


Verbosity = Literal['normal', 'indent']


class ProjectServer:
    """Runs the archive server on a thread."""
    
    # NOTE: Only changed when tests are running
    _last_created: Optional[ProjectServer]=None
    
    def __init__(self,
            project: Project,
            port: int | None=None,
            *, verbosity: Verbosity='normal',
            stdout: TextIOBase | None=None,
            ) -> None:
        if port is None:
            port = _DEFAULT_SERVER_PORT
            try_other_ports = True
        else:
            try_other_ports = False
        
        self._project = project
        self._verbosity = verbosity
        self._stdout = stdout
        
        # Start server on port, looking for alternative open port if needed
        while True:
            # NOTE: Must explicitly check whether port in use because Windows
            #       appears not to raise an exception when opening a _HttpServer
            #       on a port that is in use, unlike macOS and Linux
            if try_other_ports and is_port_in_use(port):
                pass
            else:
                try:
                    address = ('', port)
                    server = _HttpServer(address, _RequestHandler)
                except Exception as e:
                    if try_other_ports and is_port_in_use_error(e):
                        pass
                    else:
                        raise
                else:
                    break
            
            # Try another port
            port += 1
            continue
        server.project = project
        server.verbosity = verbosity
        server.stdout = stdout
        
        self._server = server
        self._port = port
        
        # NOTE: It's very hard to crash _HttpServer itself such that an
        #       unhandled exception would escape to this level.
        #       Most errors already get routed to _HttpServer.handle_error().
        #       For those errors that somehow manage to escape anyway,
        #       just route them to stderr for now.
        @capture_crashes_to_stderr
        def bg_task() -> None:
            try:
                if verbosity == 'normal':
                    print_success('Server started on port %s.' % port, file=self._stdout)
                self._server.serve_forever()
            finally:
                self._server.server_close()
        bg_call_later(bg_task, daemon=True)
        
        # Export reference to self, if running tests
        if tests_are_running():
            ProjectServer._last_created = self
    
    def close(self) -> None:
        self._server.shutdown()
    
    # === Properties ===
    
    @property
    def project(self) -> Project:
        return self._project
    
    @property
    def port(self) -> int:
        return self._port
    
    # === Utility ===
    
    def get_request_url(self, archive_url: str) -> str:
        """
        Given the absolute URL of a resource, returns the URL that should be used to
        request it from the project server.
        """
        return get_request_url(archive_url, self._port, self._project.default_url_prefix)


def get_request_url(
        archive_url: str,
        port: int | None=None,
        project_default_url_prefix: str | None=None,
        ) -> str:
    """
    Given the absolute URL of a resource, returns the URL that should be used to
    request it from the project server.
    """
    if port is None:
        port = _DEFAULT_SERVER_PORT
    
    request_host = 'localhost:%s' % port
    return _RequestHandler.get_request_url_with_host(
        archive_url, request_host, project_default_url_prefix)


# ------------------------------------------------------------------------------

_REQUEST_PATH_IN_ARCHIVE_RE = re.compile(r'^/_/([^/]+)/(.+)$')

_PIN_DATE_JS_PATH_RE = re.compile(r'^/_/crystal/pin_date\.js\?t=([0-9]+)$')
_PIN_DATE_JS_PATH_PREFIX = '/_/crystal/pin_date.js?t='

# Set of archived headers that may be played back as-is
_HEADER_ALLOWLIST = {
    'date',
    'vary',
    'content-disposition',
    'content-language',
    'content-type',
    'server',
    'last-modified',
    'etag',
    'content-encoding',
    'x-xss-protection',
    'x-content-type-options',
    'x-frame-options',
    'x-download-options',
    'x-permitted-cross-domain-policies',
    
    # CORS
    'access-control-allow-origin',
    'access-control-allow-methods',
    'access-control-expose-headers',
    
    # CORP
    'cross-origin-resource-policy',
    
    # COOP
    'cross-origin-opener-policy',
    
    # Timing
    'timing-allow-origin',  # enable cross-origin access to timing API
    'server-timing',
    
    # Infrastructure-specific: AWS Cloudfront
    'x-amz-cf-id',
    'x-amz-cf-pop',
    'x-amz-storage-class',
    
    # Infrastructure-specific: AWS S3
    'x-amz-id-2',
    'x-amz-request-id',
    'x-amz-version-id',
    
    # Infrastructure-specific: Cloudflare
    'cf-cache-status',
    'cf-ray',
    'cf-request-id',
    'cf-bgj',
    'cf-polished',
    
    # Infrastructure-specific: Google Cloud
    'x-goog-generation',
    'x-goog-hash',
    'x-goog-metageneration',
    'x-goog-storage-class',
    'x-goog-stored-content-encoding',
    'x-goog-stored-content-length',
    'x-guploader-uploadid',
    
    # Infrastructure-specific: Fastly
    'detected-user-agent',
    'fastly-restarts',
    'normalized-user-agent',
    'request_came_from_shield',
    'surrogate-control',
    'x-served-by',
    
    # Infrastructure-specific: Envoy
    'x-envoy-attempt-count',
    'x-envoy-upstream-service-time',
    
    # Service-specific: imgix
    'x-imgix-id',
    
    # Site-specific: Substack
    'x-cluster',
}
# Set of archived headers known to cause problems if blindly played back
_HEADER_DENYLIST = {
    # Connection
    'transfer-encoding',# overridden by this web server
    'content-length',   # overridden by this web server
    'accept-ranges',    # partial content ranges not supported by this server
    'connection',       # usually: keep-alive
    'keep-alive',
    'via',              # this web server is not a proxy
    
    # Cache
    'cache-control',
    'age',
    'expires',
    'pragma',           # usually: no-cache
    
    # Cookie
    'set-cookie',       # don't allow cookies to be set by archived site
    'p3p',              # never allow third party cookies
    
    # HTTPS & Certificates
    'expect-ct',        # don't require Certificate Transparency
    'strict-transport-security',  # don't require HTTPS
    
    # Links (uninteresting)
    # NOTE: Details at: https://github.com/davidfstr/Crystal-Web-Archiver/issues/75
    'link',
    
    # Logging
    'content-security-policy-report-only',
                        # don't enable CSP logging
    'cross-origin-embedder-policy-report-only',
                        # don't enable COEP logging
    'cross-origin-opener-policy-report-only',
                        # don't enable COOP logging
    'nel',              # don't enable network request logging
    'report-to',        # don't enable Content Security Policy logging
    
    # Referer
    'referrer-policy',  # don't omit referer because used to dynamically rewrite links
    
    # Protocol Upgrades
    'upgrade',          # we don't support HTTP/2, QUIC, or any alternate protocol advertised by this
    'alt-svc',          # we don't support HTTP/2, QUIC, or any alternate protocol advertised by this
    
    # X-RateLimit
    'x-ratelimit-limit',
    'x-ratelimit-remaining',
    'x-ratelimit-count',
    'x-ratelimit-reset',
    
    # Ignored non-problematic headers
    # TODO: Consider moving these headers to the _HEADER_ALLOWLIST
    'x-powered-by',
    'x-monk',
    'x-cache',
    'x-ecn-p',
    'vtag',
}
# Whether to suppress warnings related to unknown X- HTTP headers
_IGNORE_UNKNOWN_X_HEADERS = True

# When True, attempt to override JavaScript's Date class in HTML documents to
# return a consistent datetime for "now" matching the Date header that the
# page was served with.
# 
# Some pages like <https://newsletter.pragmaticengineer.com/archive> format
# URLs in JavaScript based on the current datetime. By pinning the current
# datetime to a consistent value, the generated URLs will also have a
# consistent value, allowing those generated URLs to be cached effectively.
_ENABLE_PIN_DATE_MITIGATION = True

# By default, browsers may cache Crystal-served assets for 1 hour
_CACHE_CONTROL_POLICY = 'max-age=3600'  # type: Optional[str]

_HTTP_COLON_SLASH_SLASH_RE = re.compile(r'(?i)https?://')


class _HttpServer(HTTPServer):
    project: Project
    verbosity: Verbosity
    stdout: TextIOBase | None
    
    @override
    def handle_error(self, request, client_address):
        # Print to stderr a message starting with
        # 'Exception occurred during processing of request from'
        return super().handle_error(request, client_address)


class _RequestHandler(BaseHTTPRequestHandler):
    # Prevent slow/broken request from blocking all other requests
    timeout = 1  # second
    
    server: _HttpServer
    
    @property
    def project(self) -> Project:
        server = self.server
        assert isinstance(server, _HttpServer)
        return server.project
    
    @property
    def _server_host(self) -> str:
        return 'localhost:%s' % self.server.server_port  # type: ignore[attr-defined]
    
    # === Request Properties ===
    
    @property
    def request_host(self) -> str:
        return self.headers.get('Host', self._server_host)
    
    @property
    def referer(self) -> str | None:
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
    
    def do_GET(self) -> None:  # override
        try:
            run_thread_switching_coroutine(
                SwitchToThread.BACKGROUND,
                self._do_GET())
        except BrokenPipeError:
            # Browser did drop connection before did finish sending response
            pass
    
    def _do_GET(self) -> Generator[SwitchToThread, None, None]:
        readonly = self.project.readonly  # cache
        dynamic_ok = (self.headers.get('X-Crystal-Dynamic', 'True') == 'True')
        
        # Parse self.path using RFC 2616 rules,
        # which in particular allows it to be an absolute URI!
        if self.path == '*':
            self.send_response(400)
            self.end_headers()
            return
        elif self.path.startswith('/'):
            host = self.headers.get('Host')
            if host is None:
                self.send_response(400)
                self.end_headers()
                return
        else:  # self.path must be an absolute URI
            pathurl_parts = urlparse(self.path)
            if pathurl_parts.scheme not in ('http', 'https') or pathurl_parts.netloc == '':
                self.send_response(400)
                self.end_headers()
                return
            
            # Rewrite self.path to be a URL path and the Host header to be a domain
            self.path = urlunparse(pathurl_parts._replace(scheme='', netloc=''))
            self.headers['Host'] = pathurl_parts.netloc  # replace any that existed before
        
        # Serve pin_date.js if requested
        m = _PIN_DATE_JS_PATH_RE.fullmatch(self.path)
        if m is not None:
            timestamp = int(m.group(1))
            
            self.send_response(200)
            self.send_header('Content-Type', 'application/javascript')
            self.end_headers()
            self.wfile.write(_pin_date_js(timestamp).encode('utf-8'))
            return
        
        # Serve resource revision in archive
        archive_url = self.get_archive_url(self.path)
        if archive_url is not None:
            yield SwitchToThread.FOREGROUND
            
            # If URL not in archive in its original form,
            # see whether it exists in the archive in a different form,
            # or whether it should be created in a different form
            resource = self.project.get_resource(archive_url)
            if resource is None:
                archive_url_alternatives = Resource.resource_url_alternatives(
                    self.project, archive_url)
                if len(archive_url_alternatives) >= 2:
                    assert archive_url_alternatives[0] == archive_url
                    # TODO: Optimize to use a bulk version of Project.get_resource()
                    #       rather than making several individual queries
                    for urla in archive_url_alternatives[1:]:
                        if self.project.get_resource(urla) is not None:
                            # Redirect to existing URL in archive
                            yield SwitchToThread.BACKGROUND
                            self.send_redirect(self.get_request_url(urla))
                            return
                    
                    # Redirect to canonical form of URL in archive
                    yield SwitchToThread.BACKGROUND
                    self.send_redirect(self.get_request_url(archive_url_alternatives[-1]))
                    return
            # (Either resource exists at archive_url, or archive_url is in canonical form)
            
            if resource is None:
                # If the previously undiscovered resource is a member of an
                # existing resource group, presume that the user is interested 
                # in downloading it immediately upon access
                matching_rg = self._find_group_matching_archive_url(archive_url)
                if matching_rg is not None and not readonly and dynamic_ok:
                    self._print_warning('*** Dynamically downloading new resource in group {!r}: {}'.format(
                        matching_rg.display_name,
                        archive_url,
                    ))
                    
                    # Try download resource immediately
                    def download_resource() -> Resource:
                        assert archive_url is not None
                        return Resource(self.project, archive_url)
                    resource = fg_call_and_wait(download_resource)
                    yield SwitchToThread.BACKGROUND
                    self._try_download_revision_dynamically(resource, needs_result=False)
                    # (continue to serve downloaded resource revision)
                else:
                    yield SwitchToThread.BACKGROUND
                    self.send_resource_not_in_archive(archive_url)
                    return
            
            if resource.definitely_has_no_revisions:
                revision = None  # type: Optional[ResourceRevision]
            else:
                def get_default_revision() -> ResourceRevision | None:
                    assert resource is not None
                    return resource.default_revision(
                        stale_ok=True if self.project.readonly else False
                    )
                revision = fg_call_and_wait(get_default_revision)
            
            yield SwitchToThread.BACKGROUND
            
            if revision is None:
                if not readonly and dynamic_ok:
                    # If the existing resource is also a root resource,
                    # presume that the user is interested 
                    # in downloading it immediately upon access
                    matching_rr = self._find_root_resource_matching_archive_url(archive_url)
                    if matching_rr is not None:
                        self._print_warning('*** Dynamically downloading root resource {!r}: {}'.format(
                            matching_rr.display_name,
                            archive_url,
                        ))
                    
                    # If the existing resource is a member of an
                    # existing resource group, presume that the user is interested 
                    # in downloading it immediately upon access
                    matching_rg = self._find_group_matching_archive_url(archive_url)
                    if matching_rg is not None:
                        self._print_warning('*** Dynamically downloading existing resource in group {!r}: {}'.format(
                            matching_rg.display_name,
                            archive_url,
                        ))
                    
                    if matching_rr is not None or matching_rg is not None:
                        # Try download resource immediately
                        revision = self._try_download_revision_dynamically(resource, needs_result=True)
                        # (continue to serve downloaded resource revision)
                
                if revision is None:
                    self.send_resource_not_in_archive(archive_url)
                    return
            
            # If client did make a conditional request which did match the revision,
            # send a short HTTP 304 response rather than the whole revision
            if_none_match = self.headers['If-None-Match']
            if if_none_match is not None:
                etag = revision.etag
                # NOTE: Only an If-None-Match containing a single ETag is supported for now
                if etag is not None and etag == if_none_match:
                    self.send_response(304)
                    self.end_headers()
                    return
            
            self.send_revision(revision, archive_url)
            return
        
        # Dynamically rewrite incoming link from archived resource revision
        referer = self.referer  # cache
        if referer is not None and dynamic_ok:
            referer_urlparts = urlparse(referer)
            if ((referer_urlparts.netloc == '' and referer_urlparts.path.startswith('/')) or 
                    referer_urlparts.netloc == self._server_host):
                referer_archive_url = self.get_archive_url(referer_urlparts.path)
                if referer_archive_url is not None:
                    referer_archive_urlparts = urlparse(referer_archive_url)
                    assert isinstance(referer_archive_urlparts.scheme, str)
                    assert isinstance(referer_archive_urlparts.netloc, str)
                    requested_archive_url = '{}://{}{}'.format(
                        referer_archive_urlparts.scheme,
                        referer_archive_urlparts.netloc,
                        self.path,
                    )
                    redirect_url = self.get_request_url(requested_archive_url)
                    
                    self._print_warning('*** Dynamically rewriting link from {}: {}'.format(
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
    
    def _find_root_resource_matching_archive_url(self, archive_url: str) -> RootResource | None:
        for rr in self.project.root_resources:
            if rr.resource.url == archive_url:
                return rr
        return None
    
    def _find_group_matching_archive_url(self, archive_url: str) -> ResourceGroup | None:
        # ...excluding "do not download" groups
        for rg in self.project.resource_groups:
            if rg.contains_url(archive_url) and not rg.do_not_download:
                return rg
        return None
    
    @staticmethod
    @bg_affinity
    def _try_download_revision_dynamically(resource: Resource, *, needs_result: bool) -> ResourceRevision | None:
        try:
            return resource.download(
                # NOTE: Need to wait for embedded resources as well.
                #       If we were to serve a downloaded HTML page with
                #       embedded links that were not yet downloaded,
                #       they would be served as HTTP 404 until they
                #       finished downloading. To avoid serving a broken
                #       page we must wait longer for the embedded resources
                #       to finish downloading.
                wait_for_embedded=True,
                needs_result=needs_result,
                # Assume optimistically that resource is embedded so that
                # it downloads at "interactive priority", without inserting
                # any artificial delays
                is_embedded=True,
            ).result()
        except Exception:
            # Don't care if there was an error downloading
            return None
    
    # === Send Page ===
    
    @bg_affinity
    def send_welcome_page(self, query_params: dict[str, list[str]], *, vary_referer: bool) -> None:
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
                <title>Welcome | Crystal</title>
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
    
    @bg_affinity
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
                <title>Not Found | Crystal</title>
            </head>
            <body>
                <p>There is no page here.</>
                <p>Return to <a href="/">home page</a>?</p>
            </body>
            </html>
            """
        ).lstrip('\n').encode('utf-8'))
    
    @bg_affinity
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
                <title>Not in Archive | Crystal</title>
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
        
        self._print_error('*** Requested resource not in archive: ' + archive_url)
    
    @bg_affinity
    def send_redirect(self, redirect_url: str, *, vary_referer: bool=False) -> None:
        self.send_response(307)
        self.send_header('Location', redirect_url)
        if vary_referer:
            self.send_header('Vary', 'Referer')
        self.end_headers()
    
    # === Send Revision ===
    
    @bg_affinity
    def send_revision(self, revision: ResourceRevision, archive_url: str) -> None:
        if revision.error is not None:
            self.send_resource_error(revision.error_dict, archive_url)
            return
        assert revision.has_body
        
        if revision.is_http:
            self.send_http_revision(revision)
        else:
            self.send_generic_revision(revision)
    
    @bg_affinity
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
                <title>Fetch Error | Crystal</title>
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
        
        self._print_error('*** Requested resource was fetched with error: ' + archive_url)
    
    @bg_affinity
    def send_http_revision(self, revision: ResourceRevision) -> None:
        if revision.is_http_304:
            def do_resolve_http_304():
                nonlocal revision
                revision = revision.resolve_http_304()  # reinterpret
            fg_call_and_wait(do_resolve_http_304)
        
        metadata = revision.metadata
        assert metadata is not None
        
        # Determine Content-Type to send
        assert revision.has_body
        (doc, links, content_type_with_options) = revision.document_and_links()
        if not content_type_with_options:
            content_type_with_options = revision.declared_content_type_with_options
        
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
        
        # Try extract revision datetime from Date header
        revision_datetime = revision.date
        
        # Send status line
        self.send_response_without_extra_headers(
            metadata['status_code'],
            metadata['reason_phrase'])
        
        # Send headers
        for (name, value) in headers:
            name_lower = name.lower()  # cache
            
            if name_lower == 'location':
                self.send_header(name, self.get_request_url(value))
                continue
                
            if name_lower in _HEADER_ALLOWLIST:
                self.send_header(name, value)
            else:
                if name_lower not in _HEADER_DENYLIST:
                    if not (_IGNORE_UNKNOWN_X_HEADERS and name_lower.startswith('x-')):
                        self._print_warning(
                            '*** Ignoring unknown header in archive: {}: {}'.format(name, value))
                continue
        if _CACHE_CONTROL_POLICY is not None:
            self.send_header('Cache-Control', _CACHE_CONTROL_POLICY)
        self.end_headers()
        
        # Send body
        self.send_revision_body(revision, doc, links, revision_datetime)
    
    @bg_affinity
    def send_generic_revision(self, revision: ResourceRevision) -> None:
        # Determine what Content-Type to send
        assert revision.has_body
        (doc, links, content_type_with_options) = revision.document_and_links()
        if not content_type_with_options:
            content_type_with_options = revision.declared_content_type_with_options
        
        # Send status line
        self.send_response(200)
        
        # Send headers
        if content_type_with_options is not None:
            self.send_header('Content-Type', content_type_with_options)
        self.end_headers()
        
        # Send body
        self.send_revision_body(revision, doc, links, revision_datetime=None)
    
    @bg_affinity
    def send_revision_body(self, 
            revision: ResourceRevision, 
            doc: Document | None, 
            links: list[Link], 
            revision_datetime: datetime.datetime | None
            ) -> None:
        # Send body
        if doc is None:
            # Not a document. Cannot rewrite content.
            with revision.open() as body:
                sock = self.connection
                try:
                    # NOTE: It would be more straightforward to use
                    #           shutil.copyfileobj(body, self.wfile)
                    #       but copyfileobj() does not use os.sendfile()
                    #       internally (which is the fastest file copy primitive):
                    #           https://github.com/python/cpython/issues/69249
                    sock.sendfile(body)
                except BrokenPipeError:
                    # Browser did disconnect early
                    return
        else:
            # Rewrite links in document
            base_url = revision.resource.url
            self._rewrite_links(links, base_url, self.get_request_url)
            
            if _ENABLE_PIN_DATE_MITIGATION:
                # TODO: Add try_insert_script() to Document interface
                if isinstance(doc, HtmlDocument) and revision_datetime is not None:
                    doc.try_insert_script(
                        _PIN_DATE_JS_PATH_PREFIX + 
                        str(int(revision_datetime.timestamp())))
            
            # Output altered document
            try:
                self.wfile.write(str(doc).encode('utf-8'))
            except BrokenPipeError:
                # Browser did disconnect early
                return
    
    @staticmethod
    def _rewrite_links(
            links: list[Link],
            base_url: str,
            get_request_url: Callable[[str], str]
            ) -> None:
        for link in links:
            relative_url = link.relative_url
            if relative_url.startswith('#'):
                # Don't rewrite links to anchors on the same page,
                # because some pages use JavaScript libraries
                # that treat such "local anchor links" specially
                pass
            else:
                if _HTTP_COLON_SLASH_SLASH_RE.fullmatch(relative_url):
                    absolute_url = relative_url
                else:
                    absolute_url = urljoin(base_url, relative_url)
                request_url = get_request_url(absolute_url)
                link.relative_url = request_url
    
    # === Send Response ===
    
    def send_response_without_extra_headers(self, code, message=None) -> None:
        """
        Similar to BaseHTTPRequestHandler.send_response(),
        but does not send its own {Server, Date} headers.
        
        The caller should still attempt to send its own Date header
        to conform with RFC 7231 §7.1.1.2, which requires that origin servers
        with a reliable clock to generate a Date header.
        """
        self.log_request(code)
        self.send_response_only(code, message)
    
    # === URL Transformation ===
    
    def get_archive_url(self, request_path: str) -> str | None:
        match = _REQUEST_PATH_IN_ARCHIVE_RE.match(request_path)
        if match:
            (scheme, rest) = match.groups()
            archive_url = '{}://{}'.format(scheme, rest)
            return archive_url
        else:
            # If valid default URL prefix is set, use it
            default_url_prefix = self.project.default_url_prefix  # cache
            if default_url_prefix is not None and not default_url_prefix.endswith('/'):
                assert request_path.startswith('/')
                return default_url_prefix + request_path
            
            return None
    
    def get_request_url(self, archive_url: str) -> str:
        return self.get_request_url_with_host(
            archive_url, self.request_host, self.project.default_url_prefix)
    
    @staticmethod
    def get_request_url_with_host(
            archive_url: str,
            request_host: str,
            default_url_prefix: str | None,
            ) -> str:
        """
        Given the absolute URL of a resource, returns the URL that should be used to
        request it from the archive server.
        """
        # If valid default URL prefix is set, use it
        if default_url_prefix is not None and not default_url_prefix.endswith('/'):
            if archive_url.startswith(default_url_prefix + '/'):
                return f'http://{request_host}' + archive_url[len(default_url_prefix):]
        
        archive_url_parts = urlparse(archive_url)
        
        request_scheme = 'http'
        request_netloc = request_host
        request_path = '_/{}/{}{}'.format(
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
        self._print_error(format % args)
    
    def log_message(self, format, *args):  # override
        self._print_info(format % args)
    
    # === Print ===
    
    def _print_info(self, message: str) -> None:
        if self._verbosity == 'indent':
            message = '    ' + message  # reinterpret
        print_info(message, file=self._stdout)
    
    def _print_warning(self, message: str) -> None:
        if self._verbosity == 'indent':
            message = '    ' + message  # reinterpret
        print_warning(message, file=self._stdout)
    
    def _print_error(self, message: str) -> None:
        if self._verbosity == 'indent':
            message = '    ' + message  # reinterpret
        print_error(message, file=self._stdout)
    
    @property
    def _verbosity(self) -> Verbosity:
        return self.server.verbosity
    
    @property
    def _stdout(self) -> TextIOBase | None:
        return self.server.stdout


_PIN_DATE_JS_TEMPLATE = dedent(
    """
    window.Date = (function() {
        const RealDate = window.Date;  // capture
        
        function PageLoadDate() {
            if (this === window) {
                // Date() -> str
                return (new PageLoadDate()).toString();
            } else {
                // new Date() -> Date
                return new RealDate(%d);
            }
        }
        PageLoadDate.now = function() {
            return (new PageLoadDate()).getTime();
        }
        PageLoadDate.UTC = RealDate.UTC
        
        return PageLoadDate;
    })();
    """
).lstrip()  # type: str

def _pin_date_js(timestamp: int) -> str:
    return _PIN_DATE_JS_TEMPLATE % timestamp


# ------------------------------------------------------------------------------