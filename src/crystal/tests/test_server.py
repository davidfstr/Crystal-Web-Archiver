from contextlib import asynccontextmanager, redirect_stdout
from copy import deepcopy
from crystal.model import Project, Resource, ResourceRevision, RootResource
from crystal import server
from crystal.server import get_request_url
from crystal.tests.util.controls import click_button, TreeItem
from crystal.tests.util.runner import bg_sleep
from crystal.tests.util.server import (
    assert_does_open_webbrowser_to, extracted_project, fetch_archive_url, WebPage,
)
from crystal.tests.util.wait import DEFAULT_WAIT_PERIOD
from crystal.tests.util.windows import OpenOrCreateDialog
from io import StringIO
import tempfile
from typing import AsyncIterator, Callable, Optional, Tuple
from unittest import skip


# TODO: Many serving behaviors are tested indirectly by larger tests
#       in test_workflows.py. Write stubs for all such behaviors
#       and link them to the covering test.

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
    UNSAFE_HEADER_NAME = 'Cache-Control'
    assert UNSAFE_HEADER_NAME.lower() in server._HEADER_DENYLIST
    
    async with _xkcd_home_page_served() as (revision, server_page, _):
        # Ensure test data has header
        saved_header_value = revision._get_first_value_of_http_header(UNSAFE_HEADER_NAME)
        assert saved_header_value is not None
        
        # Ensure header has expected value in served page
        served_header_value = server_page.headers[UNSAFE_HEADER_NAME]
        assert served_header_value is None


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


@asynccontextmanager
async def _xkcd_home_page_served(
        alter_revision_func: Optional[Callable[[ResourceRevision], None]]=None,
        ) -> AsyncIterator[Tuple[ResourceRevision, WebPage, str]]:
    with extracted_project('testdata_xkcd.crystalproj.zip') as project_dirpath:
        # Define URLs
        home_url = 'https://xkcd.com/'
        
        async with (await OpenOrCreateDialog.wait_for()).open(project_dirpath) as mw:
            project = Project._last_opened_project
            assert project is not None
            
            r = Resource(project, home_url)
            
            revision = r.default_revision()
            assert revision is not None
            
            # Start server
            root_ti = TreeItem.GetRootItem(mw.entity_tree.window)
            assert root_ti is not None
            home_ti = root_ti.GetFirstChild()
            assert home_ti is not None
            assert f'{home_url} - Home' == home_ti.Text
            home_ti.SelectItem()
            with assert_does_open_webbrowser_to(get_request_url(home_url)):
                click_button(mw.view_button)
            
            # Alter revision before fetching it through the server, if applicable
            if alter_revision_func is not None:
                alter_revision_func(revision)
            
            # Fetch the revision through the server
            with redirect_stdout(StringIO()) as captured_stdout:
                server_page = await fetch_archive_url(home_url)
            # HACK: Ensure following "OK" print happens at start of line
            print()
            
            yield (revision, server_page, captured_stdout.getvalue())


# ------------------------------------------------------------------------------
