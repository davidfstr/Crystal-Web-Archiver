"""Tests for DownloadResourceTask and DownloadResourceGroupTask"""

from contextlib import redirect_stderr
from crystal.app_preferences import app_prefs
from crystal.model import Resource, RootResource
import crystal.task
from crystal.tests.util.asserts import assertEqual, assertIn
from crystal.tests.util.controls import click_button, TreeItem
from crystal.tests.util.runner import bg_sleep
from crystal.tests.util.server import MockHttpServer, MockFtpServer, served_project
from crystal.tests.util.tasks import wait_for_download_task_to_start_and_finish
from crystal.tests.util.wait import (
    DEFAULT_WAIT_PERIOD, first_child_of_tree_item_is_not_loading_condition,
    wait_for, wait_for_future,
)
from crystal.tests.util.windows import NewGroupDialog, OpenOrCreateDialog
import crystal.tests.util.xtempfile as xtempfile
import io
import os
import socks
import sockshandler
import socket
import ssl
from textwrap import dedent
from unittest import skip
from unittest.mock import MagicMock, patch
import urllib.request

from crystal.util.xos import is_windows


_FAVICON_PATH = '/favicon.ico'


# ------------------------------------------------------------------------------
# Resource.download() Tests

@skip('covered by: test_given_downloading_resource_when_start_download_resource_then_existing_download_task_returned')
async def test_given_not_downloading_resource_when_start_download_resource_then_download_task_created_and_returned() -> None:
    pass


async def test_given_downloading_resource_when_start_download_resource_then_existing_download_task_returned() -> None:
    with served_project('testdata_xkcd.crystalproj.zip') as sp:
        # Define URLs
        home_url = sp.get_request_url('https://xkcd.com/')
        
        async with (await OpenOrCreateDialog.wait_for()).create() as (mw, project):
            r = Resource(project, home_url)
            
            async with wait_for_download_task_to_start_and_finish(project):
                rr_future = r.download()
                
                rr_future2 = r.download()
                assert rr_future2 is rr_future


# ------------------------------------------------------------------------------
# DownloadResourceTask Tests

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
        async with (await OpenOrCreateDialog.wait_for()).create() as (mw, project):
            r = Resource(project, server.get_url('/'))
            revision_future = r.download(wait_for_embedded=True)
            while not revision_future.done():
                await bg_sleep(DEFAULT_WAIT_PERIOD)
            
            assertEqual(['/', '/assets/image.png', _FAVICON_PATH], server.requested_paths)


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
        async with (await OpenOrCreateDialog.wait_for()).create() as (mw, project):
            r = Resource(project, server.get_url('/'))
            revision_future = r.download(wait_for_embedded=True)
            while not revision_future.done():
                await bg_sleep(DEFAULT_WAIT_PERIOD)
            
            assertEqual(['/'], server.requested_paths)


async def test_does_not_download_embedded_resources_of_recognized_binary_resource() -> None:
    server = MockHttpServer({
        '/': dict(
            status_code=200,
            headers=[('Content-Type', 'image/png')],
            content=dedent(
                """
                PNG <img src="/assets/image.png" />
                """
            ).lstrip('\n').encode('utf-8')
        )
    })
    with server:
        async with (await OpenOrCreateDialog.wait_for()).create() as (mw, project):
            r = Resource(project, server.get_url('/'))
            revision_future = r.download(wait_for_embedded=True)
            while not revision_future.done():
                await bg_sleep(DEFAULT_WAIT_PERIOD)
            
            assertEqual(['/'], server.requested_paths)


async def test_does_not_download_forever_given_embedded_resources_form_a_cycle() -> None:
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
        async with (await OpenOrCreateDialog.wait_for()).create() as (mw, project):
            r = Resource(project, server.get_url('/'))
            revision_future = r.download(wait_for_embedded=True)
            while not revision_future.done():
                await bg_sleep(DEFAULT_WAIT_PERIOD)
            
            assertEqual(['/', '/assets/image.png', _FAVICON_PATH], server.requested_paths)


async def test_does_not_download_forever_given_embedded_resources_nest_infinitely() -> None:
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
        async with (await OpenOrCreateDialog.wait_for()).create() as (mw, project):
            r = Resource(project, server.get_url('/'))
            revision_future = r.download(wait_for_embedded=True)
            while not revision_future.done():
                await bg_sleep(DEFAULT_WAIT_PERIOD)
            
            assert 3 == crystal.task._MAX_EMBEDDED_RESOURCE_RECURSION_DEPTH
            assertEqual([
                '/',
                '/assets/image.png',  # 1
                '/assets/assets/image.png',  # 2
                '/assets/assets/assets/image.png',  # 3
                _FAVICON_PATH,
            ], server.requested_paths)


async def test_when_download_resource_given_revision_body_missing_then_redownloads_revision_body() -> None:
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
    })
    with server:
        with xtempfile.TemporaryDirectory(suffix='.crystalproj') as project_dirpath:
            async with (await OpenOrCreateDialog.wait_for()).create(project_dirpath) as (mw, project):
                r = Resource(project, server.get_url('/'))
                revision_future = r.download(wait_for_embedded=True)
                while not revision_future.done():
                    await bg_sleep(DEFAULT_WAIT_PERIOD)
                
                assertEqual(['/', '/assets/image.png', _FAVICON_PATH], server.requested_paths)
                server.requested_paths.clear()
                
                rr = revision_future.result()
                rr_body_filepath = rr._body_filepath  # capture
            
            # Simulate loss of revision body file, perhaps due to an
            # incomplete copy of a .crystalproj from one disk to another
            # (perhaps because of bad blocks in the revision body file)
            os.remove(rr_body_filepath)
            
            async with (await OpenOrCreateDialog.wait_for()).open(project_dirpath) as (mw, project):
                with redirect_stderr(io.StringIO()) as captured_stderr:
                    r = Resource(project, server.get_url('/'))
                    revision_future = r.download(wait_for_embedded=True)
                    while not revision_future.done():
                        await bg_sleep(DEFAULT_WAIT_PERIOD)
                
                assert (
                    ' is missing its body on disk. Redownloading it.'
                    in captured_stderr.getvalue()
                )
                assertEqual(['/'], server.requested_paths)


async def test_when_download_resource_given_all_embedded_resources_already_downloaded_then_completes_early() -> None:
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
        '/index.php': dict(
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
        async with (await OpenOrCreateDialog.wait_for()).create() as (mw, project):
            r = Resource(project, server.get_url('/'))
            revision_future = r.download(wait_for_embedded=True)
            while not revision_future.done():
                await bg_sleep(DEFAULT_WAIT_PERIOD)
            
            assertEqual(['/', '/assets/image.png', _FAVICON_PATH], server.requested_paths)
            server.requested_paths.clear()
            
            r = Resource(project, server.get_url('/index.php'))
            revision_future = r.download(wait_for_embedded=True)
            while not revision_future.done():
                await bg_sleep(DEFAULT_WAIT_PERIOD)
            
            assertEqual(['/index.php'], server.requested_paths)


async def test_given_same_resource_embedded_multiple_times_then_downloads_it_only_once() -> None:
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
                    <img src="/assets/image.png" />
                    <img src="/assets/image.png#fragment-should-be-ignored" />
                </body>
                </html>
                """
            ).lstrip('\n').encode('utf-8')
        )
    })
    with server:
        async with (await OpenOrCreateDialog.wait_for()).create() as (mw, project):
            r = Resource(project, server.get_url('/'))
            revision_future = r.download(wait_for_embedded=True)
            while not revision_future.done():
                await bg_sleep(DEFAULT_WAIT_PERIOD)
            
            assertEqual(['/', '/assets/image.png', _FAVICON_PATH], server.requested_paths)


# ------------------------------------------------------------------------------
# DownloadResourceGroupTask Tests

@skip('covered by: test_some_tasks_may_complete_immediately')
async def test_can_download_group_with_nothing_as_source() -> None:
    # See subtest: task_type='DownloadResourceGroupTask'
    pass


@skip('covered by: test_can_download_and_serve_a_static_site_using_main_window_ui')
async def test_can_download_group_with_root_resource_as_source() -> None:
    # See section: "Test can download resource group, when root resource is source"
    pass


@skip('covered by: test_can_download_and_serve_a_static_site_using_main_window_ui')
async def test_can_download_group_with_group_as_source() -> None:
    # See section: "Test can update membership of resource group, when other resource group is source"
    pass


async def test_can_download_empty_group() -> None:
    with served_project('testdata_xkcd.crystalproj.zip') as sp:
        # Define URLs
        comic_pattern = sp.get_request_url('https://xkcd.com/#/')
        
        async with (await OpenOrCreateDialog.wait_for()).create() as (mw, _):
            assert mw.new_group_button.Enabled
            click_button(mw.new_group_button)
            ngd = await NewGroupDialog.wait_for()
            
            ngd.pattern_field.Value = comic_pattern
            ngd.name_field.Value = 'Comic'
            await ngd.ok()
            
            root_ti = TreeItem.GetRootItem(mw.entity_tree.window)
            comic_ti = root_ti.find_child(comic_pattern)
            comic_ti.SelectItem()
            
            with patch.object(
                    crystal.task.DownloadResourceGroupTask, 'finish', autospec=True,
                    side_effect=crystal.task.DownloadResourceGroupTask.finish) as spy_finish:
                click_button(mw.download_button)
                await wait_for(lambda: spy_finish.call_count >= 1 or None)
                assert 1 == spy_finish.call_count


# ------------------------------------------------------------------------------
# Proxy Tests

@skip('covered by nearly all automated tests implicitly')
async def test_can_download_resource_with_no_proxy() -> None:
    pass


async def test_can_download_http_resource_with_socks_proxy() -> None:
    server = MockHttpServer({
        '/': dict(
            status_code=200,
            headers=[('Content-Type', 'text/html')],
            content=b'<!DOCTYPE html><html><body>Hello World</body></html>'
        )
    })
    with server:
        # Create a mock socksocket that delegates all I/O to a real socket
        # which connects directly to the test server,
        # bypassing the real SOCKS protocol
        mock_socksocket = MagicMock(spec=socket.socket)
        if True:
            mock_socksocket.set_proxy = MagicMock()  # method that socks.socksocket has
            
            real_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            mock_socksocket.connect = real_socket.connect
            mock_socksocket.send = real_socket.send
            mock_socksocket.sendall = real_socket.sendall
            mock_socksocket.recv = real_socket.recv
            mock_socksocket.settimeout = real_socket.settimeout
            mock_socksocket.close = real_socket.close
            mock_socksocket.makefile = real_socket.makefile
        
        with patch('socks.socksocket', return_value=mock_socksocket):
            # Configure app preferences to use SOCKS v5 proxy
            app_prefs.proxy_type = 'socks5'
            app_prefs.socks5_proxy_host = 'test-proxy-host'
            app_prefs.socks5_proxy_port = 9999
            
            async with (await OpenOrCreateDialog.wait_for()).create() as (mw, project):
                r = Resource(project, server.get_url('/'))
                revision_future = r.download()
                await wait_for_future(revision_future)
                
                # Verify SOCKS proxy was configured correctly.
                # (It may be called multiple times due to fetch of favicon
                #  and other embedded resources.)
                assert mock_socksocket.set_proxy.call_count >= 1
                mock_socksocket.set_proxy.assert_any_call(
                    socks.SOCKS5, 'test-proxy-host', 9999, rdns=True
                )
                
                # Verify the server received the request
                assert '/' in server.requested_paths
                
                # Verify the download succeeded
                rr = revision_future.result()
                assert rr is not None
                assert rr.metadata is not None
                assertEqual(200, rr.metadata['status_code'])


async def test_can_download_https_resource_with_socks_proxy() -> None:
    server = MockHttpServer({
        '/': dict(
            status_code=200,
            headers=[('Content-Type', 'text/html')],
            content=b'<!DOCTYPE html><html><body>Hello Secure World</body></html>'
        )
    })
    with server:
        # Create a mock socksocket that delegates all I/O to a real socket
        # which connects directly to the test server,
        # bypassing the real SOCKS protocol
        mock_socksocket = MagicMock(spec=socket.socket)
        if True:
            mock_socksocket.set_proxy = MagicMock()  # method that socks.socksocket has
            
            real_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            mock_socksocket.connect = real_socket.connect
            mock_socksocket.send = real_socket.send
            mock_socksocket.sendall = real_socket.sendall
            mock_socksocket.recv = real_socket.recv
            mock_socksocket.settimeout = real_socket.settimeout
            mock_socksocket.close = real_socket.close
            mock_socksocket.makefile = real_socket.makefile
        
        # Create a mock SSL context that bypasses SSL wrapping
        mock_ssl_context = MagicMock(spec=ssl.SSLContext)
        mock_ssl_context.wrap_socket = MagicMock(side_effect=lambda sock, **kwargs: sock)
        
        with patch('socks.socksocket', return_value=mock_socksocket), \
                patch('crystal.download.get_ssl_context', return_value=mock_ssl_context):
            # Configure app preferences to use SOCKS v5 proxy
            app_prefs.proxy_type = 'socks5'
            app_prefs.socks5_proxy_host = 'test-proxy-host'
            app_prefs.socks5_proxy_port = 9999
            
            async with (await OpenOrCreateDialog.wait_for()).create() as (mw, project):
                # Use an HTTPS URL (which will be handled by _SocksHTTPSConnection)
                # but connect to the HTTP test server
                r = Resource(project, server.get_url('/').replace('http://', 'https://'))
                revision_future = r.download()
                await wait_for_future(revision_future)
                
                # Verify SOCKS proxy was configured correctly.
                # (It may be called multiple times due to fetch of favicon
                #  and other embedded resources.)
                assert mock_socksocket.set_proxy.call_count >= 1
                mock_socksocket.set_proxy.assert_any_call(
                    socks.SOCKS5, 'test-proxy-host', 9999, rdns=True
                )
                
                # Verify SSL context's wrap_socket was called (but it just returned the socket as-is)
                assert mock_ssl_context.wrap_socket.call_count >= 1
                
                # Verify the server received the request
                assert '/' in server.requested_paths
                
                # Verify the download succeeded
                rr = revision_future.result()
                assert rr is not None
                assert rr.metadata is not None
                assertEqual(200, rr.metadata['status_code'])


async def test_can_download_ftp_resource_with_socks_proxy() -> None:
    server = MockFtpServer({
        '/test.txt': b'Hello FTP World'
    })
    with server:
        socks_handler_init_calls = []
        def mock_init(self, *args, **kwargs):
            socks_handler_init_calls.append((args, kwargs))
            # Don't actually use SOCKS. Just create a normal handler
            # that will connect directly to our test FTP server.
            urllib.request.HTTPHandler.__init__(self)
        
        with patch.object(sockshandler.SocksiPyHandler, '__init__', mock_init):
            # Configure app preferences to use SOCKS v5 proxy
            app_prefs.proxy_type = 'socks5'
            app_prefs.socks5_proxy_host = 'test-proxy-host'
            app_prefs.socks5_proxy_port = 9999
            
            async with (await OpenOrCreateDialog.wait_for()).create() as (mw, project):
                r = Resource(project, server.get_url('/test.txt'))
                revision_future = r.download()
                await wait_for_future(revision_future)
                
                # Verify SOCKS proxy handler was created with correct settings
                assert len(socks_handler_init_calls) >= 1
                (args, kwargs) = socks_handler_init_calls[0]
                assert len(args) >= 3
                assert args[0] == socks.SOCKS5
                assert args[1] == 'test-proxy-host'
                assert args[2] == 9999
                
                # Verify the server received the request
                assert '/test.txt' in server.requested_paths
                
                # Verify the download succeeded
                rr = revision_future.result()
                assert rr is not None
                with rr.open() as body:
                    assert body.read() == b'Hello FTP World'


async def test_cannot_download_resource_with_socks_proxy_if_connect_to_socks_proxy_fails() -> None:
    server = MockHttpServer({
        '/': dict(
            status_code=200,
            headers=[('Content-Type', 'text/html')],
            content=b'<!DOCTYPE html><html><body>Hello World</body></html>'
        )
    })
    with server:
        # Reserve a random port by opening and closing a server socket
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(('127.0.0.1', 0))  # bind to any free port
            reserved_port = s.getsockname()[1]
            # (Socket closes when exiting 'with' block,
            #  but port will be unavailable for a few seconds afterward)
        
        # Configure app preferences to use SOCKS v5 proxy pointing to the reserved port
        # (which has nothing listening on it)
        app_prefs.proxy_type = 'socks5'
        app_prefs.socks5_proxy_host = '127.0.0.1'
        app_prefs.socks5_proxy_port = reserved_port
        
        async with (await OpenOrCreateDialog.wait_for()).create() as (mw, project):
            # Create a RootResource pointing at the simple resource
            r = Resource(project, server.get_url('/'))
            home_rr = RootResource(project, 'Home', r)
            
            root_ti = TreeItem.GetRootItem(mw.entity_tree.window)
            (home_ti,) = root_ti.Children
            
            # Try to download it by expanding its node in the Entity Tree
            home_ti.Expand()
            await wait_for(first_child_of_tree_item_is_not_loading_condition(home_ti))
            
            # Ensure that, after the loading child goes away, there is a unique
            # error node child that mentions a proxy-related error.
            (error_ti,) = home_ti.Children
            assertIn('Error downloading URL:', error_ti.Text)
            assertIn('ProxyConnectionError:', error_ti.Text)
            assertIn('Error connecting to SOCKS5 proxy', error_ti.Text)
            if is_windows():
                assertIn(
                    'No connection could be made because the target machine actively refused it',
                    error_ti.Text)
            else:
                assertIn(
                    'Connection refused',
                    error_ti.Text)


# ------------------------------------------------------------------------------
