from __future__ import annotations

from collections.abc import Callable, Iterator
from concurrent.futures import Future
from contextlib import contextmanager
from copy import deepcopy
from crystal import resources
from crystal.model import Project
from crystal.server import _DEFAULT_SERVER_PORT, get_request_url, ProjectServer
from crystal.tests.util.runner import bg_fetch_url
from crystal.tests.util.wait import DEFAULT_WAIT_TIMEOUT
import crystal.tests.util.xtempfile as xtempfile
from crystal.util import http_date
from crystal.util.bulkheads import capture_crashes_to_stderr
from crystal.util.xdatetime import datetime_is_aware
from crystal.util.xfunctools import partial2
from crystal.util.xthreading import bg_call_later, fg_call_and_wait
import datetime
from email.message import EmailMessage
from http.server import BaseHTTPRequestHandler, HTTPServer
import os
import re
import socket
import sys
import threading
from typing import List, Optional
import unittest.mock
from zipfile import ZipFile

# ------------------------------------------------------------------------------
# Utility: Port Detection

def get_most_recently_started_server_port() -> int:
    """
    Returns the port of the most recently started ProjectServer during tests.
    Falls back to _DEFAULT_SERVER_PORT if no server has been started yet.
    
    This function enables test utilities to auto-detect which port a ProjectServer
    is running on, eliminating the need for tests to hardcode the port.
    
    Only works when tests are running.
    """
    if ProjectServer._last_created is not None:
        return ProjectServer._last_created.port
    return _DEFAULT_SERVER_PORT


# ------------------------------------------------------------------------------
# Utility: Server

@contextmanager
def served_project(
        zipped_project_filename: str,
        **kwargs,
        ) -> Iterator[ProjectServer]:
    with extracted_project(zipped_project_filename) as project_dirpath:
        with served_project_from_filepath(project_dirpath, **kwargs) as sp:
            yield sp


@contextmanager
def served_project_from_filepath(
        project_dirpath: str,
        *, fetch_date_of_resources_set_to: datetime.datetime | None=None,
        port: int | None=None,
        ) -> Iterator[ProjectServer]:
    if fetch_date_of_resources_set_to is not None:
        if not datetime_is_aware(fetch_date_of_resources_set_to):
            raise ValueError('Expected fetch_date_of_resources_set_to to be an aware datetime')
    
    must_alter_fetch_date = (fetch_date_of_resources_set_to is not None)
    project_server = None  # type: Optional[ProjectServer]
    project = fg_call_and_wait(lambda: Project(project_dirpath, readonly=True if not must_alter_fetch_date else False))
    try:
        # Alter the fetch date of every ResourceRevision in the project
        # to match "fetch_date_of_resources_set_to", if provided
        if must_alter_fetch_date:
            def fg_task() -> None:
                for r in project.resources:
                    for rr in list(r.revisions()):
                        if rr.metadata is None:
                            print(
                                f'Warning: Unable to alter fetch date of '
                                f'resource revision lacking HTTP headers: {rr}',
                                file=sys.stderr)
                            continue
                        
                        assert fetch_date_of_resources_set_to is not None
                        rr_new_date = http_date.format(fetch_date_of_resources_set_to)
                        
                        # New Metadata = Old Metadata with Date and Age headers replaced
                        rr_new_metadata = deepcopy(rr.metadata)
                        rr_new_metadata['headers'] = [
                            [cur_name, cur_value]
                            for (cur_name, cur_value) in
                            rr_new_metadata['headers']
                            if cur_name.lower() not in ['date', 'age']
                        ] + [['Date', rr_new_date]]
                        
                        rr._alter_metadata(rr_new_metadata, ignore_readonly=True)
            fg_call_and_wait(fg_task)
        
        # Start server
        # Use port 0 by default to let OS assign an available port,
        # avoiding conflicts when tests run in parallel
        project_server = ProjectServer(project,
            port=(port if port is not None else 0),
            host='127.0.0.1',
            verbosity='indent',
        )
        yield project_server
    finally:
        def close_project() -> None:
            if project_server is not None:
                project_server.close()
            project.close()
        fg_call_and_wait(close_project)


class MockHttpServer:
    def __init__(self, routes) -> None:
        self.requested_paths = []  # type: List[str]
        
        mock_server = self  # capture
        class RequestHandler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # override
                mock_server.requested_paths.append(self.path)
                
                # Look for static route
                route = routes.get(self.path)
                if route is not None:
                    self._send_route_response(route)
                    return
                
                # Look for dynamic route
                for (path_pattern, route) in routes.items():
                    if not callable(path_pattern):
                        continue
                    if not path_pattern(self.path):
                        continue
                    self._send_route_response(route)
                    return
                
                self.send_response(404)
                self.end_headers()
                return
            
            def _send_route_response(self, route) -> None:
                self.send_response(route['status_code'])
                for (k, v) in route['headers']:
                    self.send_header(k, v)
                self.end_headers()
                
                content = route['content']
                if callable(content):
                    content = content(self.path)
                assert isinstance(content, bytes)
                self.wfile.write(content)
        
        # Bind to port 0 to get an OS-assigned available port
        address = ('127.0.0.1', 0)
        self._server = HTTPServer(address, RequestHandler)
        self._port = self._server.server_port
        
        @capture_crashes_to_stderr
        def bg_task() -> None:
            try:
                self._server.serve_forever()
            finally:
                self._server.server_close()
        bg_call_later(bg_task, name='MockHttpServer.serve', daemon=True)
    
    def get_url(self, path: str) -> str:
        return f'http://127.0.0.1:{self._port}' + path
    
    def close(self) -> None:
        self._server.shutdown()
    
    def __enter__(self) -> MockHttpServer:
        return self
    
    def __exit__(self, *args) -> None:
        self.close()


class MockFtpServer:
    """
    A minimal FTP server for testing purposes.
    
    Supports basic FTP commands needed by urllib to download a file.
    
    Logs all commands received when _VERBOSE=True to help debug which
    FTP commands are actually used by the caller.
    """
    
    # Enable verbose logging of FTP commands for debugging
    _VERBOSE = False
    
    def __init__(self, files: dict[str, bytes]) -> None:
        """
        Arguments:
        * files -- Dictionary mapping file paths to their content bytes.
                   Example: {'/test.txt': b'Hello World'}
        """
        self.files = files
        self.requested_paths = []  # type: List[str]
        
        # Bind to port 0 to get an OS-assigned available port
        self._server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._server_socket.bind(('127.0.0.1', 0))
        self._port = self._server_socket.getsockname()[1]
        self._server_socket.listen(5)
        
        self._running = True
        self._server_thread = bg_call_later(
            self._serve,
            name='MockFtpServer.serve',
            daemon=True,
        )
    
    @capture_crashes_to_stderr
    def _serve(self) -> None:
        """Main server loop that accepts connections."""
        while self._running:
            try:
                self._server_socket.settimeout(0.5)
                try:
                    client_socket, address = self._server_socket.accept()
                except socket.timeout:
                    continue
                
                # Handle client in a separate thread
                bg_call_later(
                    partial2(self._handle_client, client_socket),
                    name='MockFtpServer.handle_client',
                    daemon=True,
                )
            except Exception as e:
                if self._running:
                    print(f'MockFtpServer error: {e}', file=sys.stderr)
                break
    
    @capture_crashes_to_stderr
    def _handle_client(self, client_socket: socket.socket) -> None:
        """Handle a single FTP client connection."""
        try:
            # Send welcome message
            self._send_response(client_socket, '220 MockFTP Server Ready\r\n')
            
            # Track state
            data_socket = None
            
            while True:
                # Receive command
                data = client_socket.recv(1024)
                if not data:
                    break
                
                command_line = data.decode('ascii').strip()
                if self._VERBOSE:
                    print(f'[MockFtpServer] Received: {command_line}', file=sys.stderr)
                
                parts = command_line.split(None, 1)
                if not parts:
                    continue
                
                command = parts[0].upper()
                argument = parts[1] if len(parts) > 1 else ''
                
                # Handle commands
                if command == 'USER':
                    self._send_response(client_socket, '331 User name okay, need password\r\n')
                
                elif command == 'PASS':
                    self._send_response(client_socket, '230 User logged in\r\n')
                
                elif command == 'CWD':
                    # Change working directory
                    # (NOTE: Requested dirpath ignored. Assumed to be "/" or ".")
                    self._send_response(client_socket, '250 Directory changed\r\n')
                
                elif command == 'TYPE':
                    # TYPE I = binary mode, TYPE A = ASCII mode
                    self._send_response(client_socket, '200 Type set\r\n')
                
                elif command == 'PASV':
                    # Enter passive mode - create data socket
                    data_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    data_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                    data_socket.bind(('127.0.0.1', 0))  # Let OS assign port
                    data_socket.listen(1)
                    
                    data_port = data_socket.getsockname()[1]
                    # Format: 227 Entering Passive Mode (h1,h2,h3,h4,p1,p2)
                    # where port = p1*256 + p2
                    p1 = data_port // 256
                    p2 = data_port % 256
                    self._send_response(
                        client_socket,
                        f'227 Entering Passive Mode (127,0,0,1,{p1},{p2})\r\n'
                    )
                
                elif command == 'RETR':
                    # Retrieve (download) a file
                    file_path = argument
                    # Normalize path: ensure it starts with /
                    # NOTE: Assumes current directory is "/"
                    if not file_path.startswith('/'):
                        file_path = '/' + file_path
                    self.requested_paths.append(file_path)
                    
                    if file_path not in self.files:
                        self._send_response(client_socket, '550 File not found\r\n')
                        continue
                    
                    if data_socket is None:
                        self._send_response(client_socket, '425 Use PASV first\r\n')
                        continue
                    
                    # Accept data connection
                    self._send_response(client_socket, '150 Opening data connection\r\n')
                    data_conn, _ = data_socket.accept()
                    
                    # Send file content
                    data_conn.sendall(self.files[file_path])
                    data_conn.close()
                    data_socket.close()
                    data_socket = None
                    
                    self._send_response(client_socket, '226 Transfer complete\r\n')
                
                elif command == 'QUIT':
                    self._send_response(client_socket, '221 Goodbye\r\n')
                    break
                
                else:
                    if self._VERBOSE:
                        print(f'[MockFtpServer] Unknown command: {command}', file=sys.stderr)
                    self._send_response(client_socket, f'502 Command not implemented: {command}\r\n')
            
        except Exception as e:
            if self._VERBOSE:
                print(f'[MockFtpServer] Client handler error: {e}', file=sys.stderr)
        finally:
            client_socket.close()
    
    def _send_response(self, sock: socket.socket, message: str) -> None:
        """Send a response message to the client."""
        if self._VERBOSE:
            print(f'[MockFtpServer] Sending: {message.strip()}', file=sys.stderr)
        sock.sendall(message.encode('ascii'))
    
    def get_url(self, path: str) -> str:
        """Get the FTP URL for a given path."""
        return f'ftp://127.0.0.1:{self._port}{path}'
    
    def close(self) -> None:
        """Shut down the server."""
        self._running = False
        self._server_socket.close()
        self._server_thread.join(timeout=2.0)
    
    def __enter__(self) -> 'MockFtpServer':
        return self
    
    def __exit__(self, *args) -> None:
        self.close()


# ------------------------------------------------------------------------------
# Utility: Extracted Project

@contextmanager
def extracted_project(
        zipped_project_filename: str
        ) -> Iterator[str]:
    with xtempfile.TemporaryDirectory() as project_parent_dirpath:
        # Extract project
        with resources.open_binary(zipped_project_filename) as zipped_project_file:
            with ZipFile(zipped_project_file, 'r') as project_zipfile:
                project_zipfile.extractall(project_parent_dirpath)
        
        # Open project
        (project_filename,) = (
            fn for fn in os.listdir(project_parent_dirpath)
            if fn.endswith('.crystalproj')
        )
        project_dirpath = os.path.join(project_parent_dirpath, project_filename)
        yield project_dirpath


# ------------------------------------------------------------------------------
# Utility: Server Requests

@contextmanager
def assert_does_open_webbrowser_to(request_url: str | Callable[[], str]) -> Iterator[Future[str]]:
    """
    Asserts that webbrowser.open() is called with the specified URL.
    
    Yields a Future that will contain the URL that webbrowser.open() was called with.
    This allows the URL to be computed after the context block executes (e.g., after
    a server starts), and then retrieved afterward:
        
        with assert_does_open_webbrowser_to(lambda: ...) as url_future:
            click_button(mw.view_button)
        actual_url = url_future.result()
    """
    url_future: Future[str] = Future()
    
    with unittest.mock.patch('webbrowser.open', spec=True) as mock_open:
        # NOTE: Likely starts a ProjectServer, which is likely to affect the
        #       calculated request_url if it is a callable
        yield url_future
        if callable(request_url):
            request_url = request_url()
        mock_open.assert_called_with(request_url)
        url_future.set_result(request_url)


async def is_url_not_in_archive(archive_url: str, port: int | None=None) -> bool:
    """
    Checks whether the specified Resource URL is in a Project that is open
    by checking whether its running ProjectServer is serving a
    Not in Archive Page for the URL.
    
    If no port is specified then the port of the most recently started ProjectServer
    will be used. Therefore note that calls to this function without a port
    cannot be safely reordered relative to the start of context managers like 
    `with served_project(...):` and `with ProjectServer(...):`.
    """
    server_page = await fetch_archive_url(
        archive_url, port,
        headers={'X-Crystal-Dynamic': 'False'},
        timeout=4.0,  # 8.0s in ASAN; >4.0s observed in Linux ASAN
    )
    return server_page.is_not_in_archive


async def fetch_archive_url(
        archive_url: str,
        port: int | None=None,
        *, headers: dict[str, str] | None=None,
        timeout: float | None=None,
        ) -> WebPage:
    """
    Fetches the served version of the latest revision of the specified Resource URL
    from a Project that is open and whose ProjectServer is running.
    
    If no port is specified then the port of the most recently started ProjectServer
    will be used. Therefore note that calls to this function without a port
    cannot be safely reordered relative to the start of context managers like 
    `with served_project(...):` and `with ProjectServer(...):`.
    """
    if timeout is None:
        timeout = DEFAULT_WAIT_TIMEOUT
    return await bg_fetch_url(get_request_url(archive_url, port), headers=headers, timeout=timeout)


# TODO: Rename as HttpResponse or ProjectServerResponse
class WebPage:
    def __init__(self, request_url: str, status: int, headers: EmailMessage, content_bytes: bytes) -> None:
        self._request_url = request_url
        self._status = status
        self._headers = headers
        self._content_bytes = content_bytes
        self._content = None  # type: Optional[str]
    
    # === High-Level Attributes ===
    
    @property
    def is_not_in_archive(self) -> bool:
        return (
            self.title == 'Not in Archive | Crystal' and
            self._status == 404
        )
    
    @property
    def is_fetch_error(self) -> bool:
        return (
            self.title == 'Fetch Error | Crystal' and
            self._status == 400
        )
    
    @property
    def etag(self) -> str | None:
        return self._headers.get('ETag')
    
    @property
    def title(self) -> str:
        # TODO: Use an HTML parser to improve robustness
        m = re.search(r'<title>([^<]*)</title>', self.content)
        if m is None:
            return ''
        else:
            return m.group(1).strip()
    
    # === Low-Level Attributes ===
    
    @property
    def request_url(self) -> str:
        return self._request_url
    
    @property
    def status(self) -> int:
        return self._status
    
    @property
    def headers(self) -> EmailMessage:
        return self._headers
    
    @property
    def content(self) -> str:  # lazy
        if self._content is None:
            self._content = self._content_bytes.decode('utf-8')
        return self._content
    
    @property
    def content_bytes(self) -> bytes:
        return self._content_bytes


# ------------------------------------------------------------------------------
