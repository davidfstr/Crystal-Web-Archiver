from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager, redirect_stdout
from copy import deepcopy
from crystal import server
from crystal.model import Project, Resource, ResourceRevision, RootResource
from crystal.server import _DEFAULT_SERVER_PORT, get_request_url
from crystal.tests.util.controls import click_button, TreeItem
from crystal.tests.util.runner import bg_sleep
from crystal.tests.util.server import (
    assert_does_open_webbrowser_to, extracted_project, fetch_archive_url,
    served_project, WebPage,
)
from crystal.tests.util.skip import skipTest
from crystal.tests.util.tasks import wait_for_download_to_start_and_finish
from crystal.tests.util.wait import DEFAULT_WAIT_PERIOD
from crystal.tests.util.windows import (
    MainWindow, NewRootUrlDialog, OpenOrCreateDialog,
)
from crystal.util.ports import is_port_in_use
from io import StringIO

# TODO: Many serving behaviors are tested indirectly by larger tests
#       in test_workflows.py. Write stubs for all such behaviors
#       and link them to the covering test.

# ------------------------------------------------------------------------------
# Test: Start Server

async def test_given_default_serving_port_in_use_when_start_serving_project_then_finds_alternate_port() -> None:
    if is_port_in_use(_DEFAULT_SERVER_PORT):
        skipTest('_DEFAULT_SERVER_PORT is already in use outside of tests')
    if is_port_in_use(_DEFAULT_SERVER_PORT + 1):
        skipTest('_DEFAULT_SERVER_PORT + 1 is already in use outside of tests')
    
    assert not is_port_in_use(_DEFAULT_SERVER_PORT)
    with served_project('testdata_xkcd.crystalproj.zip', port=_DEFAULT_SERVER_PORT) as sp:
        assert is_port_in_use(_DEFAULT_SERVER_PORT)
        
        # Define URLs
        home_url = sp.get_request_url('https://xkcd.com/')
        
        async with (await OpenOrCreateDialog.wait_for()).create() as (mw, project):
            # Create a URL
            if True:
                root_ti = TreeItem.GetRootItem(mw.entity_tree.window)
                assert root_ti.GetFirstChild() is None  # no entities
                
                click_button(mw.new_root_url_button)
                nud = await NewRootUrlDialog.wait_for()
                
                nud.name_field.Value = 'Home'
                nud.url_field.Value = home_url
                nud.do_not_download_immediately()
                await nud.ok()
                (home_ti,) = root_ti.Children
            
            # Download the URL
            home_ti.SelectItem()
            await mw.click_download_button()
            await wait_for_download_to_start_and_finish(mw.task_tree)
            
            # Try to start second server, also on _DEFAULT_SERVER_PORT.
            # Expect it to actually start on (_DEFAULT_SERVER_PORT + 1).
            expected_port = _DEFAULT_SERVER_PORT + 1
            home_ti.SelectItem()
            try:
                with assert_does_open_webbrowser_to(get_request_url(home_url, expected_port, project_default_url_prefix=project.default_url_prefix)):
                    click_button(mw.view_button)
            finally:
                assert is_port_in_use(expected_port)
            
            # Ensure can fetch the revision through the server
            server_page = await fetch_archive_url(home_url, expected_port)
            assert 200 == server_page.status


# ------------------------------------------------------------------------------
# Test: Header Inclusion & Exclusion

async def test_when_serve_page_then_safe_headers_included() -> None:
    SAFE_HEADER_NAME = 'Date'
    assert SAFE_HEADER_NAME.lower() in server._HEADER_ALLOWLIST
    
    async with _xkcd_home_page_served() as (revision, server_page, _):
        # Ensure test data has header
        saved_header_value = revision._get_first_value_of_http_header(SAFE_HEADER_NAME)
        assert saved_header_value is not None
        
        # Ensure header has expected value in served page
        served_header_value = server_page.headers[SAFE_HEADER_NAME]
        assert served_header_value is not None
        assert saved_header_value == served_header_value


async def test_when_serve_page_then_unsafe_headers_excluded() -> None:
    UNSAFE_HEADER_NAME = 'Connection'
    assert UNSAFE_HEADER_NAME.lower() in server._HEADER_DENYLIST
    
    async with _xkcd_home_page_served() as (revision, server_page, _):
        # Ensure test data has header
        saved_header_value = revision._get_first_value_of_http_header(UNSAFE_HEADER_NAME)
        assert saved_header_value is not None
        
        # Ensure header has expected value in served page
        served_header_value = server_page.headers[UNSAFE_HEADER_NAME]
        assert served_header_value is None, (
            f'Header {UNSAFE_HEADER_NAME!r} has '
            f'unexpected value {served_header_value!r}'
        )


async def test_when_serve_page_with_unknown_non_x_header_then_excludes_header_and_prints_warning() -> None:
    UNKNOWN_NON_X_HEADER_NAME = 'Crystal-Test-Header'
    UNKNOWN_NON_X_HEADER_VALUE = 'some_value'
    assert (
        UNKNOWN_NON_X_HEADER_NAME.lower() not in server._HEADER_ALLOWLIST and
        UNKNOWN_NON_X_HEADER_NAME.lower() not in server._HEADER_DENYLIST
    )
    
    # Insert header into test data
    def alter_revision(revision: ResourceRevision) -> None:
        saved_header_value = revision._get_first_value_of_http_header(UNKNOWN_NON_X_HEADER_NAME)
        assert saved_header_value is None
        
        new_metadata = deepcopy(revision.metadata)
        assert new_metadata is not None
        new_metadata['headers'].append(
            [UNKNOWN_NON_X_HEADER_NAME, UNKNOWN_NON_X_HEADER_VALUE])
        revision._alter_metadata(new_metadata)
    
    async with _xkcd_home_page_served(alter_revision) as (revision, server_page, captured_stdout):
        # Ensure header has expected value in served page
        served_header_value = server_page.headers[UNKNOWN_NON_X_HEADER_NAME]
        assert served_header_value is None
        
        # Ensure warning printed
        assert (
            f'*** Ignoring unknown header in archive: {UNKNOWN_NON_X_HEADER_NAME}: {UNKNOWN_NON_X_HEADER_VALUE}'
            in captured_stdout
        )


async def test_when_serve_page_with_unknown_x_header_then_excludes_header_silently() -> None:
    UNKNOWN_X_HEADER_NAME = 'X-Timer'
    assert (
        UNKNOWN_X_HEADER_NAME.lower() not in server._HEADER_ALLOWLIST and
        UNKNOWN_X_HEADER_NAME.lower() not in server._HEADER_DENYLIST
    )
    assert True == server._IGNORE_UNKNOWN_X_HEADERS
    
    async with _xkcd_home_page_served() as (revision, server_page, captured_stdout):
        # Ensure test data has header
        saved_header_value = revision._get_first_value_of_http_header(UNKNOWN_X_HEADER_NAME)
        assert saved_header_value is not None
        
        # Ensure header has expected value in served page
        served_header_value = server_page.headers[UNKNOWN_X_HEADER_NAME]
        assert served_header_value is None
        
        # Ensure warning NOT printed
        assert (
            f'*** Ignoring unknown header in archive: {UNKNOWN_X_HEADER_NAME}: '
            not in captured_stdout
        )


# ------------------------------------------------------------------------------
# Utility

@asynccontextmanager
async def _xkcd_home_page_served(
        alter_revision_func: Callable[[ResourceRevision], None] | None=None,
        ) -> AsyncIterator[tuple[ResourceRevision, WebPage, str]]:
    with extracted_project('testdata_xkcd.crystalproj.zip') as project_dirpath:
        # Define URLs
        home_url = 'https://xkcd.com/'
        
        async with (await OpenOrCreateDialog.wait_for()).open(project_dirpath) as (mw, project):
            r = Resource(project, home_url)
            
            revision = r.default_revision()
            assert revision is not None
            
            # Alter revision before fetching it through the server, if applicable
            if alter_revision_func is not None:
                alter_revision_func(revision)
            
            (server_page, captured_stdout_str) = await serve_and_fetch_xkcd_home_page(mw)
            
            yield (revision, server_page, captured_stdout_str)


async def serve_and_fetch_xkcd_home_page(mw: MainWindow) -> tuple[WebPage, str]:
    home_url = 'https://xkcd.com/'
    
    with redirect_stdout(StringIO()) as captured_stdout:
        # Start server
        root_ti = TreeItem.GetRootItem(mw.entity_tree.window)
        home_ti = root_ti.GetFirstChild()
        assert home_ti is not None
        assert f'{home_url} - Home' == home_ti.Text
        home_ti.SelectItem()
        with assert_does_open_webbrowser_to(get_request_url(home_url)):
            click_button(mw.view_button)
        
        # Fetch the revision through the server
        server_page = await fetch_archive_url(home_url)
    
    return (server_page, captured_stdout.getvalue())


# ------------------------------------------------------------------------------
