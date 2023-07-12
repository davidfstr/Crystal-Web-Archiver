"""Tests for DownloadResourceTask"""

from crystal.model import Project, Resource
import crystal.task
from crystal.tests.util.runner import bg_sleep
from crystal.tests.util.wait import DEFAULT_WAIT_PERIOD
from crystal.tests.util.windows import OpenOrCreateDialog
from crystal.util.xthreading import bg_call_later
from http.server import BaseHTTPRequestHandler, HTTPServer
import tempfile
from textwrap import dedent
from typing import List
from unittest import skip


# ------------------------------------------------------------------------------
# Tests

async def test_downloads_embedded_resources() -> None:
    server = MockHttpServer({
        '/': dict(
            status_code=200,
            headers=[('Content-Type', 'text/html')],
            content=dedent(
                """
                <!DOCTYPE html>
                <html>
                <body>
                    <img src="/assets/image.png" />
                </body>
                </html>
                """
            ).lstrip('\n').encode('utf-8')
        )
    })
    with server:
        with tempfile.TemporaryDirectory(suffix='.crystalproj') as project_dirpath:
            async with (await OpenOrCreateDialog.wait_for()).create(project_dirpath) as (mw, _):
                project = Project._last_opened_project
                assert project is not None
                
                r = Resource(project, server.get_url('/'))
                revision_future = r.download(wait_for_embedded=True)
                while not revision_future.done():
                    await bg_sleep(DEFAULT_WAIT_PERIOD)
                
                assert ['/', '/assets/image.png'] == server.requested_paths


async def test_does_not_download_embedded_resources_of_http_4xx_and_5xx_pages() -> None:
    server = MockHttpServer({
        '/': dict(
            status_code=404,
            headers=[('Content-Type', 'text/html')],
            content=dedent(
                """
                <!DOCTYPE html>
                <html>
                <body>
                    <img src="/assets/image.png" />
                </body>
                </html>
                """
            ).lstrip('\n').encode('utf-8')
        ),
        '/assets/image.png': dict(
            status_code=404,
            headers=[('Content-Type', 'text/html')],
            content=dedent(
                """
                <!DOCTYPE html>
                <html>
                <body>
                    <img src="/assets/image.png" />
                </body>
                </html>
                """
            ).lstrip('\n').encode('utf-8')
        )
    })
    with server:
        with tempfile.TemporaryDirectory(suffix='.crystalproj') as project_dirpath:
            async with (await OpenOrCreateDialog.wait_for()).create(project_dirpath) as (mw, _):
                project = Project._last_opened_project
                assert project is not None
                
                r = Resource(project, server.get_url('/'))
                revision_future = r.download(wait_for_embedded=True)
                while not revision_future.done():
                    await bg_sleep(DEFAULT_WAIT_PERIOD)
                
                assert ['/'] == server.requested_paths


async def test_does_not_download_forever_when_embedded_resources_form_a_cycle() -> None:
    server = MockHttpServer({
        '/': dict(
            status_code=200,
            headers=[('Content-Type', 'text/html')],
            content=dedent(
                """
                <!DOCTYPE html>
                <html>
                <body>
                    <img src="/assets/image.png" />
                </body>
                </html>
                """
            ).lstrip('\n').encode('utf-8')
        ),
        '/assets/image.png': dict(
            status_code=200,
            headers=[('Content-Type', 'text/html')],
            content=dedent(
                """
                <!DOCTYPE html>
                <html>
                <body>
                    <img src="/assets/image.png" />
                </body>
                </html>
                """
            ).lstrip('\n').encode('utf-8')
        )
    })
    with server:
        with tempfile.TemporaryDirectory(suffix='.crystalproj') as project_dirpath:
            async with (await OpenOrCreateDialog.wait_for()).create(project_dirpath) as (mw, _):
                project = Project._last_opened_project
                assert project is not None
                
                r = Resource(project, server.get_url('/'))
                revision_future = r.download(wait_for_embedded=True)
                while not revision_future.done():
                    await bg_sleep(DEFAULT_WAIT_PERIOD)
                
                assert ['/', '/assets/image.png'] == server.requested_paths


async def test_does_not_download_forever_when_embedded_resources_nest_infinitely() -> None:
    server = MockHttpServer({
        '/': dict(
            status_code=200,
            headers=[('Content-Type', 'text/html')],
            content=dedent(
                """
                <!DOCTYPE html>
                <html>
                <body>
                    <img src="/assets/image.png" />
                </body>
                </html>
                """
            ).lstrip('\n').encode('utf-8')
        ),
        (lambda path: path.startswith('/assets/')): dict(
            status_code=200,
            headers=[('Content-Type', 'text/html')],
            content=(lambda path: dedent(
                f"""
                <!DOCTYPE html>
                <html>
                <body>
                    <img src="/assets{path}" />
                </body>
                </html>
                """
            ).lstrip('\n').encode('utf-8'))
        )
    })
    with server:
        with tempfile.TemporaryDirectory(suffix='.crystalproj') as project_dirpath:
            async with (await OpenOrCreateDialog.wait_for()).create(project_dirpath) as (mw, _):
                project = Project._last_opened_project
                assert project is not None
                
                r = Resource(project, server.get_url('/'))
                revision_future = r.download(wait_for_embedded=True)
                while not revision_future.done():
                    await bg_sleep(DEFAULT_WAIT_PERIOD)
                
                assert 3 == crystal.task._MAX_EMBEDDED_RESOURCE_RECURSION_DEPTH
                assert [
                    '/',
                    '/assets/image.png',  # 1
                    '/assets/assets/image.png',  # 2
                    '/assets/assets/assets/image.png'  # 3
                ] == server.requested_paths


# ------------------------------------------------------------------------------
# Utility

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
    
    def __enter__(self) -> 'MockHttpServer':
        return self
    
    def __exit__(self, exc_type, exc_value, exc_traceback) -> None:
        self.close()


# ------------------------------------------------------------------------------
