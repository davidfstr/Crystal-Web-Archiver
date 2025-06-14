from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from copy import deepcopy
from crystal import resources
from crystal.model import Project
from crystal.server import get_request_url, ProjectServer
from crystal.tests.util.runner import bg_fetch_url
from crystal.tests.util.wait import DEFAULT_WAIT_TIMEOUT
from crystal.util import http_date
from crystal.util.bulkheads import capture_crashes_to_stderr
from crystal.util.xdatetime import datetime_is_aware
from crystal.util.xthreading import bg_call_later, fg_call_and_wait
import datetime
from email.message import EmailMessage
from http.server import BaseHTTPRequestHandler, HTTPServer
import os
import re
import tempfile
from typing import List, Optional
import unittest.mock
from zipfile import ZipFile

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
                                f'resource revision lacking HTTP headers: {rr}')
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
        project_server = ProjectServer(project,
            port=(port or 2798),  # CRYT on telephone keypad
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
        
        self._port = 2798  # CRYT on telephone keypad
        address = ('', self._port)
        self._server = HTTPServer(address, RequestHandler)
        
        @capture_crashes_to_stderr
        def bg_task() -> None:
            try:
                self._server.serve_forever()
            finally:
                self._server.server_close()
        bg_call_later(bg_task, daemon=True)
    
    def get_url(self, path: str) -> str:
        return f'http://localhost:{self._port}' + path
    
    def close(self) -> None:
        self._server.shutdown()
    
    def __enter__(self) -> MockHttpServer:
        return self
    
    def __exit__(self, exc_type, exc_value, exc_traceback) -> None:
        self.close()


# ------------------------------------------------------------------------------
# Utility: Extracted Project

@contextmanager
def extracted_project(
        zipped_project_filename: str
        ) -> Iterator[str]:
    # NOTE: If a file inside the temporary directory is still open,
    #       ignore_cleanup_errors=True will prevent Windows from raising,
    #       at the cost of leaving the temporary directory around
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as project_parent_dirpath:
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
def assert_does_open_webbrowser_to(request_url: str) -> Iterator[None]:
    with unittest.mock.patch('webbrowser.open', spec=True) as mock_open:
        yield
        mock_open.assert_called_with(request_url)


async def is_url_not_in_archive(archive_url: str) -> bool:
    server_page = await fetch_archive_url(
        archive_url, 
        headers={'X-Crystal-Dynamic': 'False'})
    return server_page.is_not_in_archive


async def fetch_archive_url(
        archive_url: str,
        port: int | None=None,
        *, headers: dict[str, str] | None=None,
        timeout: float | None=None,
        ) -> WebPage:
    if timeout is None:
        timeout = DEFAULT_WAIT_TIMEOUT
    return await bg_fetch_url(get_request_url(archive_url, port), headers=headers, timeout=timeout)


# TODO: Rename as HttpResponse or ProjectServerResponse
class WebPage:
    def __init__(self, status: int, headers: EmailMessage, content_bytes: bytes) -> None:
        self._status = status
        self._headers = headers
        self._content_bytes = content_bytes
        self._content = None  # type: Optional[str]
    
    # === High-Level Attributes ===
    
    @property
    def is_not_in_archive(self) -> bool:
        return (
            self._status == 404 and
            self.title == 'Not in Archive | Crystal'
        )
    
    @property
    def etag(self) -> str | None:
        return self._headers.get('ETag')
    
    @property
    def title(self) -> str | None:
        # TODO: Use an HTML parser to improve robustness
        m = re.search(r'<title>([^<]*)</title>', self.content)
        if m is None:
            return None
        else:
            return m.group(1).strip()
    
    # === Low-Level Attributes ===
    
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
