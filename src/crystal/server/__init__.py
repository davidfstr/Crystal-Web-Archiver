"""
Implements an HTTP server that serves resource revisions from a Project.
Runs on its own daemon thread.
"""

from __future__ import annotations

from collections.abc import Callable, Generator
from concurrent.futures import Future
import threading
from crystal.doc.generic import Document, Link
from crystal.doc.html.soup import HtmlDocument
from crystal.model import (
    Project, Resource, ResourceGroup, ResourceGroupSource, ResourceRevision,
    RootResource,
)
from crystal import resources
from crystal.predict_group import (
    DetectedRegularGroup, DetectedSequentialGroup, 
    detect_regular_group, detect_sequential_groups,
)
from crystal.server.api import CreateGroupErrorResponse, CreateGroupFormData, CreateGroupRequest, CreateGroupResponse, CreateGroupSuccessResponse, SourceChoice, SourceChoiceValue
from crystal.server.special_pages import fetch_error_html, not_found_page_html, not_in_archive_html, welcome_page_html
from crystal.util.bulkheads import capture_crashes_to_stderr
from crystal.util.cli import (
    TERMINAL_FG_PURPLE, colorize, print_error, print_info, print_success, print_warning,
)
from crystal.util.minify import minify_svg
from crystal.util.ports import is_port_in_use, is_port_in_use_error
from crystal.util.test_mode import tests_are_running
from crystal.util.xthreading import (
    bg_affinity, bg_call_later, fg_affinity, fg_call_and_wait, fg_wait_for,
    is_foreground_thread,
    run_thread_switching_coroutine, SwitchToThread,
)
from crystal.util.xtyping import IntStr, intstr_from
import datetime
from functools import cache
from html import escape as html_escape  # type: ignore[attr-defined]
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, HTTPServer
from io import TextIOBase
import json
import os
import re
import socket
import socketserver
import sys
from textwrap import dedent
import time
import traceback
import trycast
from trycast import checkcast
from typing import (
    Literal, Mapping, Optional, TYPE_CHECKING, TypeAlias, TypedDict,
    assert_never,
)
from typing_extensions import override
from urllib.parse import parse_qs, urljoin, urlparse, urlunparse

if TYPE_CHECKING:
    from crystal.task import Task


# ------------------------------------------------------------------------------
# ProjectServer

_DEFAULT_SERVER_PORT = 2797  # CRYS on telephone keypad
_DEFAULT_SERVER_HOST = '127.0.0.1'


Verbosity = Literal['normal', 'indent']


class ProjectServer:
    """
    Runs the project server on a thread. The server can be accessed via HTTP,
    and allows archived pages in a project to be viewed in a web browser.
    
    The server limits who can connect to it using `--host`. It does not perform
    any additional authentication/authorization to limit access.
    
    Secure-by-default policies:
    - The default host is 127.0.0.1, which only allows connections from the same
      computer the server is running on.
    - When a remote host is specified, projects will be served as read-only
      by default, unless --no-readonly is specified.
    """
    
    # NOTE: Only changed when tests are running
    _last_created: Optional[ProjectServer]=None
    
    def __init__(self,
            project: Project,
            port: int | None=None,
            host: str | None=None,
            *, verbosity: Verbosity='normal',
            stdout: TextIOBase | None=None,
            exit_instruction: str | None=None,
            wait_for_banner: bool=True,
            ) -> None:
        """
        Raises:
        * OSError (errno.EADDRINUSE) -- if the host:port combination is already in use.
        """
        if port is None:
            port = _DEFAULT_SERVER_PORT
            try_other_ports = True
        else:
            try_other_ports = False
        if host is None:
            host = _DEFAULT_SERVER_HOST
        
        self._project = project
        self._host = host
        self._verbosity = verbosity
        self._stdout = stdout
        
        # Start server on port, looking for alternative open port if needed
        while True:
            # NOTE: Must explicitly check whether port in use because Windows
            #       appears not to raise an exception when opening a _HttpServer
            #       on a port that is in use, unlike macOS and Linux
            if try_other_ports and is_port_in_use(port, host):
                pass
            else:
                try:
                    address = (host, port)
                    server = _HttpServer(address, _RequestHandler)
                except Exception as e:
                    if try_other_ports and is_port_in_use_error(e):
                        pass
                    else:
                        raise
                else:
                    break
            
            if port == _DEFAULT_SERVER_PORT and tests_are_running():
                print(
                    '*** Default port for project server is in use. '
                    'Is a real Crystal app running in the background? '
                    'Will continue with a different open port, '
                    'but the current automated test may not expect '
                    'the server to be running on a non-default port.',
                    file=sys.stderr
                )
            
            # Try another port
            port += 1
            continue
        server.project = project
        server.verbosity = verbosity
        server.stdout = stdout
        
        self._server = server
        self._port = port
        
        banner_printed = Future()  # type: Future[Literal[True]]
        
        # NOTE: It's very hard to crash _HttpServer itself such that an
        #       unhandled exception would escape to this level.
        #       Most errors already get routed to _HttpServer.handle_error().
        #       For those errors that somehow manage to escape anyway,
        #       just route them to stderr for now.
        @capture_crashes_to_stderr
        def bg_task() -> None:
            try:
                if verbosity == 'normal':
                    print_success(f'Server started at: http://{host}:{port}', file=self._stdout)
                    
                    # Show readonly mode info if applicable
                    if project.readonly and host != '127.0.0.1':
                        print_info(f'Read-only mode automatically enabled for remote access (--host {host}).', file=self._stdout)
                        print_info('To allow remote modifications, restart with --no-readonly.', file=self._stdout)
                    
                    if exit_instruction:
                        print_info(exit_instruction, file=self._stdout)
                
                # Signal that banner has printed
                banner_printed.set_result(True)
                
                self._server.serve_forever()
            finally:
                self._server.server_close()
        bg_call_later(bg_task, daemon=True)
        
        if wait_for_banner:
            banner_printed._cr_declare_no_deadlocks = True  # type: ignore[attr-defined]
            banner_printed.result()
        
        # Export reference to self, if running tests
        if tests_are_running():
            ProjectServer._last_created = self
    
    def close(self, *, _timeout_if_fg_thread: float|None=None) -> None:
        """
        Raises:
        * TimeoutError
        """
        if is_foreground_thread():
            # Wait for shutdown while still processing wx events
            self._fg_shutdown(self._server, timeout=_timeout_if_fg_thread)
        else:
            self._server.shutdown()
    
    @staticmethod
    def _fg_shutdown(http_server: HTTPServer, *, timeout: float|None) -> None:
        """
        Raises:
        * TimeoutError
        """
        # Request that shutdown happen soon
        assert isinstance(getattr(http_server, '_BaseServer__shutdown_request', None), bool), (
            "BaseServer.__shutdown_request not found or wrong type. "
            "Has BaseServer's internal API changed?"
        )
        http_server._BaseServer__shutdown_request = True  # type: ignore[attr-defined]
        
        # Wait for shutdown to complete,
        # while still processing events in the wx event loop
        is_shut_down = getattr(http_server, '_BaseServer__is_shut_down', None)
        assert isinstance(is_shut_down, threading.Event), (
            "BaseServer.__is_shut_down not found or wrong type. "
            "Has BaseServer's internal API changed?"
        )
        def poll_is_shut_down() -> bool:
            success = is_shut_down.wait(20 / 1000)  # 20 ms
            return success
        fg_wait_for(
            poll_is_shut_down,
            timeout=timeout,
            # No need to sleep additionally between polls because 
            # poll_is_shut_down() sleeps internally
            poll_interval=0)
    
    # === Properties ===
    
    @property
    def project(self) -> Project:
        return self._project
    
    @property
    def port(self) -> int:
        return self._port
    
    @property
    def host(self) -> str:
        return self._host
    
    # === Utility ===
    
    def get_request_url(self, archive_url: str) -> str:
        """
        Given the absolute URL of a resource, returns the URL that should be used to
        request it from the project server.
        """
        return get_request_url(
            archive_url,
            self._port,
            self._host,
            project_default_url_prefix=self._project.default_url_prefix)


def get_request_url(
        archive_url: str,
        port: int | None=None,
        host: str | None=None,
        *, project_default_url_prefix: str | None=None,
        ) -> str:
    """
    Given the absolute URL of a resource, returns the URL that should be used to
    request it from the project server.
    """
    if port is None:
        port = _DEFAULT_SERVER_PORT
    if host is None:
        host = _DEFAULT_SERVER_HOST
    
    request_host = f'{host}:{port}'
    return _RequestHandler.get_request_url_with_host(
        archive_url, request_host, project_default_url_prefix)


# ------------------------------------------------------------------------------
# _HttpServer, _RequestHandler

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

# By default, browsers may not cache root Crystal-served assets
# because it is common for multiple Crystal projects opened near the same
# time to serve different assets at the root
_CACHE_CONTROL_POLICY_AT_ROOT = 'max-age=0, must-revalidate'  # type: Optional[str]
# By default, browsers may cache non-root Crystal-served assets for 1 hour
_CACHE_CONTROL_POLICY_AT_SUBDIRECTORY = 'max-age=3600'  # type: Optional[str]

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
    
    @override
    def server_bind(self):
        """
        Overrides server_bind to assume the server name is "localhost"
        when bound to 127.0.0.1.
        
        The default implementation of HTTPServer.server_bind() uses
        `socket.getfqdn(host)` to determine the server name, which shows an
        unwanted 'Allow "Crystal" to find devices on local networks?'
        security prompt on macOS.
        """
        socketserver.TCPServer.server_bind(self)
        host, port = self.server_address[:2]
        if host == '127.0.0.1':
            # Avoid mDNS lookup on macOS
            self.server_name = 'localhost'
        else:
            self.server_name = socket.getfqdn(host)
        self.server_port = port


class _RequestHandler(BaseHTTPRequestHandler):
    PUBLIC_STATIC_RESOURCE_NAMES = {
        'appicon.png',
        'logotext.png',
        'logotext@2x.png',
        'logotext-dark.png',
        'logotext-dark@2x.png'
    }
    
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
        server = self.server
        assert isinstance(server, _HttpServer)
        (host, port) = server.server_address
        assert isinstance(host, str) and isinstance(port, int)
        return f'{host}:{port}'
    
    # === Request Properties ===
    
    @property
    def request_host(self) -> str:
        return self.headers.get('Host', self._server_host)
    
    @property
    def referer(self) -> str | None:
        return self.headers.get('Referer')
    
    # === Handle ===
    
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
    
    def do_POST(self) -> None:  # override
        try:
            # TODO: No need to use run_thread_switching_coroutine() for such
            #       a simple _do_POST() implementation
            run_thread_switching_coroutine(
                SwitchToThread.BACKGROUND,
                self._do_POST())
        except BrokenPipeError:
            # Browser did drop connection before did finish sending response
            pass
    
    # --- Handle: GET or POST ---
    
    def _do_GET(self) -> Generator[SwitchToThread, None, None]:
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
        
        # Handle: Crystal static resources
        if self.path.startswith('/_/crystal/resources/'):
            yield SwitchToThread.BACKGROUND
            self._handle_static_resource()
            return
        
        # Handle: "Not in Archive" Endpoints
        if self.path.startswith('/_/crystal/download-progress'):
            yield SwitchToThread.BACKGROUND
            self._handle_get_download_progress()
            return
        
        # Reserve 404.html in the root directory for exported projects
        if self.path == '/404.html':
            self.send_not_found_page(vary_referer=True)
            return
        
        # Serve resource revision in archive
        archive_url = self.get_archive_url(self.path)
        if archive_url is not None:
            yield from self._serve_archive_url(archive_url)
            return
        
        # Dynamically rewrite incoming link from archived resource revision
        if self._redirect_to_archive_url_if_referer_is_self():
            return
        
        # Serve Welcome page
        path_parts = urlparse(self.path)
        if path_parts.path == '/':
            self.send_welcome_page(parse_qs(path_parts.query), vary_referer=True)
            return
        
        # Serve Not Found page
        self.send_not_found_page(vary_referer=True)
        return
    
    def _do_POST(self) -> Generator[SwitchToThread, None, None]:
        # Handle: "Not in Archive" Endpoints
        if self.path == '/_/crystal/download-url':
            yield SwitchToThread.BACKGROUND
            self._handle_start_download_url()
            return
        elif self.path == '/_/crystal/create-group':
            yield SwitchToThread.BACKGROUND
            self._handle_create_group()
            return
        elif self.path == '/_/crystal/preview-urls':
            yield SwitchToThread.BACKGROUND
            self._handle_preview_urls()
            return
        
        # For all other POST requests, return 405 Method Not Allowed
        self.send_response(405)
        self.send_header('Allow', 'GET')
        self.end_headers()
        return
    
    # --- Handle: Archive URL ---
    
    def _serve_archive_url(self, archive_url: str) -> Generator[SwitchToThread, None, None]:
        from crystal.task import TaskDisposedException
        
        readonly = self.project.readonly  # cache
        dynamic_ok = self._dynamic_ok()  # cache

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
                def create_resource() -> Resource:
                    assert archive_url is not None
                    return Resource(self.project, archive_url)
                resource = fg_call_and_wait(create_resource)
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
        
        # HACK: Don't wait for subresources to download if there is no real
        #       scheduler thread to run the downloads
        scheduler_running = isinstance(self.project._scheduler_thread, threading.Thread)
        if scheduler_running:
            # 1. Wait for any embedded subresources to finish downloading
            # 2. Escalate any in-progress download of subresources to interactive priority
            download_embedded_future = resource.download(
                wait_for_embedded=True, needs_result=False, interactive=True)
            yield SwitchToThread.BACKGROUND
            try:
                download_embedded_future.result()
            except TaskDisposedException:
                # The download task was concurrently disposed on the scheduler thread.
                # Therefore all subresources must already be downloaded.
                pass
        
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
                # Download at interactive priority
                interactive=True,
            ).result()
        except Exception:
            # Don't care if there was an error downloading
            return None
    
    # --- Handle: Redirect to Archive URL ---
    
    @bg_affinity
    def _redirect_to_archive_url_if_referer_is_self(self) -> bool:
        # Do not redirect Crystal-internal URLs
        if self.path.startswith('/_/'):
            return False
        
        dynamic_ok = self._dynamic_ok()  # cache
        if not dynamic_ok:
            return False
        
        referer_archive_url = self.referer_archive_url
        if referer_archive_url is None:
            return False
        
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
        return True
    
    @property
    def referer_archive_url(self) -> str | None:
        referer = self.referer  # cache
        if referer is not None:
            referer_urlparts = urlparse(referer)
            if ((referer_urlparts.netloc == '' and referer_urlparts.path.startswith('/')) or 
                    referer_urlparts.netloc == self._server_host):
                referer_archive_url = self.get_archive_url(referer_urlparts.path)
                return referer_archive_url
        return None
    
    # --- Handle: "Not in Archive" Endpoints ---
    
    @bg_affinity
    def _handle_start_download_url(self) -> None:
        try:
            # Ensure project is not readonly
            if self.project.readonly:
                self._send_json_response(403, {"error": "Project is read-only"})
                return
            
            # Parse arguments
            content_length = int(self.headers.get('Content-Length', -1))
            if content_length > 0:
                post_data = self.rfile.read(content_length).decode('utf-8')
            else:
                post_data = self.rfile.read().decode('utf-8')
            if not post_data:
                self._send_json_response(400, {"error": "Missing request body"})
                return
            try:
                request_data = json.loads(post_data)
                url = request_data.get('url')
                is_root = request_data.get('is_root')
            except json.JSONDecodeError:
                self._send_json_response(400, {"error": "Invalid JSON"})
                return
            if url is None or is_root is None:
                self._send_json_response(400, {"error": "Missing parameter"})
                return
            if not isinstance(url, str) or not isinstance(is_root, bool):
                self._send_json_response(400, {"error": "Invalid parameter type"})
                return
            
            def create_and_start_download_task() -> str:
                # Get or create a Resource for the URL
                r = Resource(self.project, url)
                
                # Get or create RootResource for the URL, if requested
                if is_root:
                    rr = self.project.get_root_resource(r)
                    if rr is None:
                        rr = RootResource(self.project, '', r)
                
                # Create download task and start downloading
                task = r.download_with_task(interactive=True, needs_result=False)
                
                # Return task ID for progress tracking
                return task.resource.url
            task_id = fg_call_and_wait(create_and_start_download_task)
            
            # Send success response with task ID
            self._send_json_response(200, {
                "status": "success", 
                "message": "Download started",
                "task_id": task_id
            })

        except Exception as e:
            self._print_error(f'Error handling download request: {str(e)}')
            self._send_json_response(500, {
                "error": f"Internal server error: {str(e)}"
            })
    
    @bg_affinity
    def _handle_get_download_progress(self) -> None:
        REPORT_MAX_DURATION = 300  # 5 minutes
        REPORT_PERIOD = 0.5
        
        # Parse arguments
        query_params = parse_qs(urlparse(self.path).query)
        if 'task_id' not in query_params:
            self.send_response(400)
            self.end_headers()
            return
        task_id = query_params['task_id'][0]
        
        self._start_sse_stream()
        
        # Find the task to report on
        def find_task_by_id() -> Task | None:
            resource_url = task_id  # unwrap
            resource = self.project.get_resource(url=resource_url)
            if resource is None:
                return None
            task = resource.get_download_task(needs_result=False)
            if task is None:
                return None
            return task
        task = fg_call_and_wait(find_task_by_id)
        if task is None:
            # Presumably the task completed very quickly,
            # so report as complete immediately
            self._send_sse_data({
                'status': 'complete',
                'progress': 100,
                'message': 'Download completed',
                'completed': 1,
                'total': 1,
            })
            return
        
        # Send periodic progress updates
        start_time = time.monotonic()
        try:
            while (time.monotonic() - start_time) < REPORT_MAX_DURATION:
                def get_task_status() -> dict:
                    completed = task.num_children_complete
                    total = len(task.children_unsynchronized)
                    progress = int((completed / total) * 100) if total > 0 else 0
                    if task.complete:
                        return {
                            'status': 'complete',
                            'progress': 100,
                            'message': 'Download completed',
                            'completed': completed,
                            'total': total,
                        }
                    else:
                        return {
                            'status': 'in_progress',
                            'progress': progress,
                            'message': f'{completed} of {total} items downloaded',
                            'completed': completed,
                            'total': total,
                        }
                status = fg_call_and_wait(get_task_status)
                self._send_sse_data(status)
                
                if status['status'] == 'complete':
                    break
                
                time.sleep(REPORT_PERIOD)
        except BrokenPipeError:
            # Client disconnected
            return
        except Exception as e:
            self._send_sse_data({'error': f'Progress tracking error: {str(e)}'})
            return
    
    @bg_affinity
    def _handle_create_group(self) -> None:
        try:
            # Ensure project is not readonly
            if self.project.readonly:
                self._send_json_response(403, CreateGroupErrorResponse({"error": "Project is read-only"}))
                return
            
            # Parse arguments
            content_length = int(self.headers.get('Content-Length', -1))
            if content_length > 0:
                post_data = self.rfile.read(content_length).decode('utf-8')
            else:
                post_data = self.rfile.read().decode('utf-8')
            if not post_data:
                self._send_json_response(400, CreateGroupErrorResponse({"error": "Missing request body"}))
                return
            try:
                request_data = json.loads(post_data)
                request = checkcast(CreateGroupRequest, request_data)
                url_pattern = request['url_pattern']
                source_data = request['source']
                name = request['name']
                download_immediately = request['download_immediately']
            except json.JSONDecodeError:
                self._send_json_response(400, CreateGroupErrorResponse({"error": "Invalid JSON"}))
                return
            except trycast.ValidationError:
                self._send_json_response(400, CreateGroupErrorResponse({"error": "Invalid request"}))
                return
            
            def parse_source_value(source_value: SourceChoiceValue | None) -> ResourceGroupSource:
                if source_value is None:
                    return None
                elif source_value['type'] == 'root_resource':
                    return self.project.get_root_resource(id=int(source_value['id']))
                elif source_value['type'] == 'resource_group':
                    return self.project.get_resource_group(id=int(source_value['id']))
                else:
                    raise ValueError(f"Invalid source type: {source_value['type']}")
            
            @fg_affinity
            def create_group_and_optionally_start_download() -> CreateGroupResponse:
                source = parse_source_value(source_data)
                
                # Check if group with this pattern already exists
                existing_group = self.project.get_resource_group(url_pattern=url_pattern)
                if existing_group is not None:
                    return CreateGroupErrorResponse({"error": "Group with URL pattern already exists"})
                
                # Create the resource group
                group = ResourceGroup(
                    self.project,
                    name=name,
                    url_pattern=url_pattern,
                    source=source,
                    do_not_download=False
                )
                
                # Start download of the group if requested
                if download_immediately:
                    group.download()
                
                result = CreateGroupSuccessResponse({
                    "status": "success",
                    "message": "Group created successfully",
                    "group_id": intstr_from(group._id),
                })
                return result
            result = fg_call_and_wait(create_group_and_optionally_start_download)
            if 'error' in result:  # CreateGroupErrorResponse
                self._send_json_response(400, result)
            else:  # CreateGroupSuccessResponse
                self._send_json_response(200, result)

        except Exception as e:
            self._print_error(f'Error handling create group request: {str(e)}')
            self._send_json_response(500, CreateGroupErrorResponse({
                "error": f"Internal server error: {str(e)}"
            }))

    @bg_affinity
    def _handle_preview_urls(self) -> None:
        try:
            # Parse arguments
            content_length = int(self.headers.get('Content-Length', -1))
            if content_length > 0:
                post_data = self.rfile.read(content_length).decode('utf-8')
            else:
                post_data = self.rfile.read().decode('utf-8')
            if not post_data:
                self._send_json_response(400, {"error": "Missing request body"})
                return
            try:
                request_data = json.loads(post_data)
                url_pattern = request_data.get('url_pattern')
            except json.JSONDecodeError:
                self._send_json_response(400, {"error": "Invalid JSON"})
                return
            if not url_pattern:
                self._send_json_response(400, {"error": "Missing url_pattern parameter"})
                return
            
            # NOTE: Use same algorithm as the NewGroupDialog to calculate and present URLs
            from crystal.browser.new_group import NewGroupDialog
            matching_urls_and_more_items = fg_call_and_wait(
                lambda: NewGroupDialog._calculate_preview_urls(self.project, url_pattern))
            self._send_json_response(200, {
                "matching_urls": matching_urls_and_more_items,
            })

        except Exception as e:
            self._print_error(f'Error handling preview URLs request: {str(e)}')
            self._send_json_response(500, {
                "error": f"Internal server error: {str(e)}"
            })

    def _start_sse_stream(self) -> None:
        self.send_response(200)
        self.send_header('Content-Type', 'text/event-stream')
        self.send_header('Cache-Control', 'no-cache')
        self.send_header('Connection', 'keep-alive')
        self.end_headers()

    def _send_sse_data(self, data: dict) -> None:
        try:
            sse_data = f"data: {json.dumps(data)}\n\n"
            self.wfile.write(sse_data.encode('utf-8'))
            self.wfile.flush()
        except BrokenPipeError:
            pass
    
    def _send_json_response(self, status_code: int, content: Mapping) -> None:
        self.send_response(status_code)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        self.wfile.write(json.dumps(content).encode('utf-8'))

    # --- Handle: Static Resources ---
    
    @bg_affinity
    def _handle_static_resource(self) -> None:
        """Serve static resources from Crystal's "resources" directory."""
        # Extract resource filename from path: /_/crystal/resources/filename.ext
        if not self.path.startswith('/_/crystal/resources/'):
            self.send_response(404)
            self.end_headers()
            return
        resource_name = self.path.removeprefix('/_/crystal/resources/')
        
        # Security: Only allow specific resource files to prevent directory traversal
        if resource_name not in self.PUBLIC_STATIC_RESOURCE_NAMES:
            self.send_response(404)
            self.end_headers()
            return
        
        try:
            with resources.open_binary(resource_name) as f:
                content = f.read()
            
            # Set appropriate content type.
            # All current public resources are PNG files.
            assert resource_name.endswith('.png')
            content_type = 'image/png'
            
            self.send_response(200)
            self.send_header('Content-Type', content_type)
            self.send_header('Cache-Control', 'max-age=3600')  # cache for 1 hour
            self.end_headers()
            self.wfile.write(content)
        except FileNotFoundError:
            self.send_response(404)
            self.end_headers()
        except Exception as e:
            self._print_error(f'Error serving static resource {resource_name}: {str(e)}')
            self.send_response(500)
            self.end_headers()
    
    # === Send Page ===
    
    @bg_affinity
    def send_welcome_page(self, query_params: dict[str, list[str]], *, vary_referer: bool) -> None:
        if 'url' in query_params:
            archive_url = query_params['url'][0]
            redirect_url = self.get_request_url(archive_url)
            
            self.send_redirect(redirect_url, vary_referer=vary_referer)
            return
        
        self.send_response(200)
        self.send_header('Content-Type', 'text/html')
        if vary_referer:
            self.send_header('Vary', 'Referer')
        # When the default URL prefix for the project is set,
        # this page will be replaced with the default domain's root page,
        # so don't cache the welcome page.
        self.send_header('Cache-Control', 'no-cache')
        self.end_headers()
        
        html_content = welcome_page_html()
        self.wfile.write(html_content.encode('utf-8'))
    
    @bg_affinity
    def send_not_found_page(self, *, vary_referer: bool) -> None:
        self.send_response(404)
        self.send_header('Content-Type', 'text/html')
        if vary_referer:
            self.send_header('Vary', 'Referer')
        self.end_headers()
        
        html_content = not_found_page_html()
        self.wfile.write(html_content.encode('utf-8'))
    
    @bg_affinity
    def send_resource_not_in_archive(self, archive_url: str) -> None:
        self._predict_groups(
            archive_url=archive_url
        )
        
        self.send_response(404)
        self.send_header('Content-Type', 'text/html')
        # If the Download button on the NIA page is pressed,
        # the page will be replaced with the downloaded page,
        # so don't cache the NIA page
        self.send_header('Cache-Control', 'no-cache')
        self.end_headers()
        
        readonly = self.project.readonly  # cache
        
        create_group_form_data = self._calculate_create_group_form_data(
            self.project, archive_url, self.referer_archive_url)
        
        html_content = not_in_archive_html(
            archive_url=archive_url,
            create_group_form_data=create_group_form_data,
            readonly=readonly,
            default_url_prefix=self.project.default_url_prefix,
        )
        self.wfile.write(html_content.encode('utf-8'))
        
        self._print_error('*** Requested resource not in archive: ' + archive_url)
    
    @classmethod
    @bg_affinity
    def _calculate_create_group_form_data(cls,
            project: Project,
            archive_url: str,
            referrer_archive_url: str | None,
            ) -> CreateGroupFormData:
        # Format Source choices,
        # matching the choices computed for NewGroupDialog.source_choice_box
        source_choices = [SourceChoice({
            'display_name': 'none',
            'value': None
        })]
        for rr in project.root_resources:
            display_name = rr.display_name
            source_choices.append(SourceChoice({
                'display_name': display_name,
                'value': SourceChoiceValue(
                    {'type': 'root_resource', 'id': intstr_from(rr._id)})
            }))
        for rg in project.resource_groups:
            display_name = rg.display_name
            source_choices.append(SourceChoice({
                'display_name': display_name,
                'value': SourceChoiceValue(
                    {'type': 'resource_group', 'id': intstr_from(rg._id)})
            }))
        
        # Find the best predicted group
        try:
            # Priority 1: First detected sequential group
            predicted_group = next(detect_sequential_groups(
                project,
                archive_url,
                referrer_archive_url,
                eager_downloads_ok=False,
                detect_last_page_ordinals=False,
            ))  # type: DetectedSequentialGroup | DetectedRegularGroup | None
        except StopIteration:
            # Priority 2: Regular group
            predicted_group = detect_regular_group(project, archive_url, referrer_archive_url)
        
        predicted_url_pattern = predicted_group.url_pattern if predicted_group is not None else None
        predicted_source = predicted_group.source if predicted_group is not None else None
        
        # Determine the selected source value for the dropdown
        if predicted_source is None:
            predicted_source_value = None  # type: SourceChoiceValue | None
        elif isinstance(predicted_source, RootResource):
            predicted_source_value = SourceChoiceValue(
                {'type': 'root_resource', 'id': intstr_from(predicted_source._id)})
        elif isinstance(predicted_source, ResourceGroup):
            predicted_source_value = SourceChoiceValue(
                {'type': 'resource_group', 'id': intstr_from(predicted_source._id)})
        else:
            assert_never(predicted_source)
        
        return CreateGroupFormData({
            'source_choices': source_choices,
            'predicted_url_pattern': predicted_url_pattern or archive_url,
            'predicted_source_value': predicted_source_value,
            'predicted_name': '',
        })
    
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

        # Determine error details
        error_type_html = (
            html_escape(error_dict['type'])
            if error_dict is not None
            else 'unknown'
        )
        error_message_html = (
            html_escape(error_dict['message'])
            if error_dict is not None and error_dict['message'] is not None
            else 'unknown'
        )
        
        html_content = fetch_error_html(
            archive_url=archive_url,
            error_type_html=error_type_html,
            error_message_html=error_message_html
        )
        self.wfile.write(html_content.encode('utf-8'))

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
        
        self._predict_groups(
            archive_url=revision.resource.url,
            archive_url_is_html=revision.is_html
        )
        
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
        if 'date' not in [name.lower() for (name, value) in headers]:
            self.send_header('Date', self.date_time_string())
        self.send_cache_control_header()
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
        self.send_response_without_extra_headers(200)
        
        # Send headers
        if content_type_with_options is not None:
            self.send_header('Content-Type', content_type_with_options)
        self.send_header('Date', self.date_time_string())
        self.send_cache_control_header()
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
                except OSError as e:
                    # macOS: [Errno 57] Socket is not connected
                    if 'Socket is not connected' in str(e):
                        # Browser did disconnect early
                        return
                    raise
        else:
            # Rewrite links in document
            base_url = revision.resource.url
            self._rewrite_links(links, base_url, self.get_request_url)
            
            if (_ENABLE_PIN_DATE_MITIGATION and
                    revision_datetime is not None and
                    isinstance(doc, HtmlDocument)):
                doc.try_insert_script(
                    _PIN_DATE_JS_PATH_PREFIX + 
                    str(int(revision_datetime.timestamp())))
            
            if isinstance(doc, HtmlDocument):
                doc.try_insert_footer_banner(self.get_request_url)
            
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
    
    def send_cache_control_header(self) -> None:
        request_path = self.path
        request_path_at_root = (
            request_path.startswith('/') and 
            request_path.rfind('/') == 0
        )
        
        cache_control_policy = (
            _CACHE_CONTROL_POLICY_AT_ROOT
            if request_path_at_root
            else _CACHE_CONTROL_POLICY_AT_SUBDIRECTORY
        )
        if cache_control_policy is not None:
            self.send_header('Cache-Control', cache_control_policy)
    
    # === URL Transformation ===
    
    def get_archive_url(self, request_path: str) -> str | None:
        return self.get_archive_url_with_dup(
            request_path,
            default_url_prefix=self.project.default_url_prefix
        )
    
    # NOTE: Duplicated in get_archive_url_with_dup() and getArchiveUrlWithDup()
    @staticmethod
    def get_archive_url_with_dup(
            request_path: str,
            default_url_prefix: str | None,
            ) -> str | None:
        match = _REQUEST_PATH_IN_ARCHIVE_RE.match(request_path)
        if match:
            (scheme, rest) = match.groups()
            archive_url = '{}://{}'.format(scheme, rest)
            return archive_url
        elif request_path.startswith('/_/'):
            # Looks similar to _REQUEST_PATH_IN_ARCHIVE_RE but does not match
            return None
        else:
            # If valid default URL prefix is set, use it
            if default_url_prefix is not None and not default_url_prefix.endswith('/'):
                assert request_path.startswith('/')
                return default_url_prefix + request_path
            else:
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
                slash_path = archive_url[len(default_url_prefix):]
                if slash_path.startswith('/_/'):
                    # Don't eliminate the default URL prefix because the
                    # resulting URL looks like a different Crystal-internal URL
                    pass
                elif slash_path == '/404.html':
                    # Don't eliminate the default URL prefix to reserve
                    # 404.html in the root directory for an exported site's
                    # HTTP 404 page
                    pass
                else:
                    # Eliminate the default URL prefix
                    return f'http://{request_host}' + slash_path
        
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
    
    # === Predict Groups ===
    
    def _predict_groups(self, archive_url: str, archive_url_is_html: bool=True) -> None:
        """
        Predicts the properties of the best new resource group containing the
        archive_url, printing the properties to the terminal.
        
        Is only enabled when environment variable CRYSTAL_PREDICT_GROUPS=1.
        """
        if not (os.environ.get('CRYSTAL_PREDICT_GROUPS', '0') == '1' and archive_url_is_html):
            return
        
        try:
            # Inputs
            #archive_url = ... (function parameter)
            referrer_archive_url = self.referer_archive_url
            
            # Outputs
            if True:
                found_group = False
                
                # Look for best matching regular group
                best_group_info = detect_regular_group(
                    self.project, archive_url, referrer_archive_url)
                if best_group_info is not None:
                    found_group = True
                    best_group = (
                        self.project.get_resource_group(url_pattern=best_group_info.url_pattern)
                        if best_group_info.url_pattern is not None
                        else None
                    )
                    prediction_msg = (
                        f"[PREDICT] Regular group:\n"
                        f"    a: {referrer_archive_url!r}\n"
                        f"    b: {archive_url!r}\n"
                        f"    A: {best_group_info.source!r}\n"
                        f"    B: {best_group or best_group_info.url_pattern!r}"
                    )
                    self._print_special(prediction_msg)
                
                # Look for best matching sequential groups
                sequential_group_infos = list(detect_sequential_groups(
                    self.project, archive_url, referrer_archive_url))
                if len(sequential_group_infos) > 0:
                    found_group = True
                    for group_info in sequential_group_infos:
                        best_group = (
                            self.project.get_resource_group(url_pattern=group_info.url_pattern)
                            if group_info.url_pattern is not None
                            else None
                        )
                        prediction_msg = (
                            f"[PREDICT] Sequential group {group_info.first_page_ordinal}..{group_info.last_page_ordinal}:\n"
                            f"    a: {referrer_archive_url!r}\n"
                            f"    b: {archive_url!r}\n"
                            f"    A: {group_info.source!r}\n"
                            f"    B: {best_group or group_info.url_pattern!r}"
                        )
                        self._print_special(prediction_msg)
                
                if not found_group:
                    prediction_msg = (
                        f"[PREDICT] No groups identified:\n"
                        f"    a: {referrer_archive_url!r}\n"
                        f"    b: {archive_url!r}"
                    )
                    self._print_special(prediction_msg)
        except Exception as e:
            self._print_special(f"*** [PREDICT] Error in heuristic:\n{traceback.format_exc()}")
    
    # === Utility: Request Accessors ===
    
    def _dynamic_ok(self) -> bool:
        """
        Returns whether the request is allowed to:
        1. dynamically download resources or
        2. dynamically rewrite links based on referer.
        
        Note that dynamic downloads also require the project to be writable
        (i.e. not readonly).
        """
        return (self.headers.get('X-Crystal-Dynamic', 'True') == 'True')
    
    # === Utility: Logging ===
    
    def log_error(self, format, *args):  # override
        self._print_error(format % args)
    
    def log_message(self, format, *args):  # override
        self._print_info(format % args)
    
    # === Utility: Print ===
    
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
    
    # Useful for debugging
    def _print_special(self, message: str) -> None:
        if self._verbosity == 'indent':
            message = '    ' + message  # reinterpret
        print(colorize(TERMINAL_FG_PURPLE, message), file=self._stdout)
    
    @property
    def _verbosity(self) -> Verbosity:
        return self.server.verbosity
    
    @property
    def _stdout(self) -> TextIOBase | None:
        return self.server.stdout


# ------------------------------------------------------------------------------
# Pin Date JS

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