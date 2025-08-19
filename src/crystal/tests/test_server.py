from collections.abc import AsyncIterator, Callable
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager, closing, redirect_stdout
from copy import deepcopy
from crystal import server
from crystal.model import Resource, ResourceRevision
from crystal.server import _DEFAULT_SERVER_PORT, get_request_url
from crystal.tests.util.asserts import assertEqual, assertIn
from crystal.tests.util.controls import click_button, TreeItem
from crystal.tests.util.downloads import network_down
from crystal.tests.util.runner import bg_fetch_url
from crystal.tests.util.server import (
    assert_does_open_webbrowser_to, extracted_project, fetch_archive_url,
    served_project, WebPage,
)
from crystal.tests.util.skip import skipTest
from crystal.tests.util.tasks import wait_for_download_to_start_and_finish
from crystal.tests.util.wait import DEFAULT_WAIT_TIMEOUT, wait_for_future
from crystal.tests.util.windows import (
    MainWindow, NewRootUrlDialog, OpenOrCreateDialog,
)
from crystal.util.ports import is_port_in_use
from crystal.util.xos import is_linux
from io import StringIO
import json
import sys
from unittest import skip

# TODO: Many serving behaviors are tested indirectly by larger tests
#       in test_workflows.py. Link stubs for such behaviors
#       to any preexisting covering test.

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
# Test: Serve Archive URL (_serve_archive_url)

# (TODO: Add tests, for at least the following cases)
# - Decide between response outcomes:
#   - send_redirect
#   - send_resource_not_in_archive -- covered below
#   - send_revision -- NOT covered elsewhere yet
#     - send_http_revision
#     - send_generic_revision
# - Dynamically modify project:
#   - '*** Dynamically downloading new resource in group ...'
#   - '*** Dynamically downloading root resource ...'
#   - '*** Dynamically downloading existing resource in group ...'
# - Dynamically take action:
#   - '*** Dynamically rewriting link from ...'


# ------------------------------------------------------------------------------
# Test: Redirect to Archive URL (_redirect_to_archive_url_if_referer_is_self)

# (TODO: Add test stubs)


# ------------------------------------------------------------------------------
# Test: "Welcome" Page (send_welcome_page)

async def test_given_welcome_page_visible_then_crystal_branding_and_url_input_is_visible() -> None:
    async with _welcome_page_visible() as server_page:
        # Verify Crystal branding is visible
        content = server_page.content
        assert 'Crystal' in content, \
            "Crystal branding should be visible in page content"
        
        # Verify URL input is visible
        assert 'Enter the URL of a page' in content, \
            "URL input should be visible on the welcome page"
        
        # Verify form elements are present
        assert '<form action="/">' in content, \
            "Form should be present on welcome page"
        assert 'name="url"' in content, \
            "URL input field should be present"
        assert 'type="submit"' in content, \
            "Submit button should be present"


async def test_given_welcome_page_visible_when_enter_url_then_navigates_to_url_in_archive() -> None:
    with extracted_project('testdata_xkcd.crystalproj.zip') as project_dirpath:
        async with (await OpenOrCreateDialog.wait_for()).open(project_dirpath) as (mw, project):
            # Start server
            root_ti = TreeItem.GetRootItem(mw.entity_tree.window)
            home_ti = root_ti.GetFirstChild()
            assert home_ti is not None
            home_ti.SelectItem()
            with assert_does_open_webbrowser_to(get_request_url('https://xkcd.com/')):
                click_button(mw.view_button)
            
            target_url = 'https://xkcd.com/'
            target_url_in_archive = get_request_url(
                target_url,
                _DEFAULT_SERVER_PORT,
                project_default_url_prefix=project.default_url_prefix)
            
            # Simulate form submit of target_url. Expect redirect.
            redirect_response = await bg_fetch_url(
                f'http://127.0.0.1:{_DEFAULT_SERVER_PORT}/?url={target_url}',
                follow_redirects=False
            )
            assertEqual(307, redirect_response.status)
            location_header = redirect_response.headers.get('Location')
            assertEqual(target_url_in_archive, location_header)
            
            # Follow the redirect. Expect archived page.
            final_response = await bg_fetch_url(target_url_in_archive)
            assertEqual(200, final_response.status)
            assertIn('<title>xkcd:', final_response.content, \
                "Response should contain the archived xkcd title")


# ------------------------------------------------------------------------------
# Test: "Not Found" Page (send_not_found_page)

async def test_given_not_found_page_visible_then_crystal_branding_and_exit_button_is_visible() -> None:
    async with _not_found_page_visible() as server_page:
        # Verify Crystal branding is visible
        content = server_page.content
        assert 'Crystal' in content, \
            "Crystal branding should be visible in page content"
        
        # Verify error message is present
        assert 'Page Not Found' in content, \
            "Error message should indicate the page was not found"
        
        # Verify go back button is visible 
        assert '← Go Back' in content and 'onclick="history.back()"' in content, \
            "Go Back button should be visible on the not found page"

        # Verify return home button is visible
        assert 'Return to Home' in content, \
            "Return to Home button should be visible on the not found page"


# ------------------------------------------------------------------------------
# Test: "Not in Archive" Page (send_resource_not_in_archive)

async def test_given_nia_page_visible_then_crystal_branding_and_error_message_and_url_is_visible() -> None:
    async with _not_in_archive_page_visible() as server_page:
        # Verify Crystal branding is visible
        content = server_page.content
        assert 'Crystal' in content, \
            "Crystal branding should be visible in page content"
        
        # Verify the missing URL is displayed in the error message
        missing_url = 'https://xkcd.com/missing-page/'
        assert missing_url in content, \
            f"Missing URL {missing_url} should be visible in the error message"
        
        # Verify basic error message content
        assert '<strong>Page Not in Archive</strong>' in content, \
            "Error message should indicate the page is not in archive"


async def test_given_nia_page_visible_when_press_go_back_button_then_navigates_to_previous_page() -> None:
    async with _not_in_archive_page_visible() as server_page:
        # Verify a go back button is present in the content
        content = server_page.content
        assert '← Go Back' in content and 'onclick="history.back()"' in content, \
            "Go back button should be present on NIA page"


async def test_given_nia_page_visible_and_project_is_readonly_then_download_button_is_disabled_and_readonly_warning_visible() -> None:
    async with _not_in_archive_page_visible(readonly=True) as server_page:
        content = server_page.content
        
        # Should show readonly warning
        assert '<div class="readonly-notice">' in content, \
            "Readonly warning should be visible when project is readonly"
        
        # Download button should be present but disabled
        assert '<button id="download-button" ' in content, \
            "Download button should be present in readonly mode"
        assert '<button id="download-button" disabled ' in content, \
            "Download button should be disabled in readonly mode"


async def test_given_nia_page_visible_and_project_is_writable_then_download_button_is_enabled_and_readonly_warning_is_not_visible() -> None:
    async with _not_in_archive_page_visible(readonly=False) as server_page:
        content = server_page.content
        
        # Should NOT show readonly warning
        assert '<div class="readonly-notice">' not in content, \
            "Readonly warning should NOT be visible when project is writable"
        
        # Download button should be present and enabled
        assert '<button id="download-button" ' in content, \
            "Download button should be present when project is writable"
        assert '<button id="download-button" disabled ' not in content, \
            "Download button should NOT be disabled when project is writable"


async def test_given_nia_page_visible_when_download_button_pressed_then_download_starts_and_runs_with_progress_bar() -> None:
    with served_project('testdata_xkcd.crystalproj.zip', port=_DEFAULT_SERVER_PORT) as sp:
        # Define URLs
        home_url = sp.get_request_url('https://xkcd.com/')
        comic1_url = sp.get_request_url('https://xkcd.com/1/')
        
        # Create a new project in the UI
        async with (await OpenOrCreateDialog.wait_for()).create() as (mw, project):
            # Download the home page
            if True:
                root_ti = TreeItem.GetRootItem(mw.entity_tree.window)
                assert root_ti.GetFirstChild() is None  # no entities
                
                # Add home URL as root resource
                click_button(mw.new_root_url_button)
                if True:
                    nud = await NewRootUrlDialog.wait_for()
                    
                    nud.name_field.Value = 'Home'
                    nud.url_field.Value = home_url
                    nud.do_not_download_immediately()
                    await nud.ok()
                (home_ti,) = root_ti.Children
                
                # Download the home page
                home_ti.SelectItem()
                await mw.click_download_button()
                await wait_for_download_to_start_and_finish(mw.task_tree)
            
            server_port = _DEFAULT_SERVER_PORT + 1
            home_url_in_archive = get_request_url(
                home_url,
                server_port,
                project_default_url_prefix=project.default_url_prefix)
            
            # Start the project server by clicking View button
            home_ti.SelectItem()
            with assert_does_open_webbrowser_to(home_url_in_archive):
                click_button(mw.view_button)
            
            # Verify that the home page is NOT a "Not in Archive" page
            home_page = await fetch_archive_url(home_url, server_port)
            assert not home_page.is_not_in_archive
            assert home_page.status == 200
            
            # Verify the home page contains a "|<" button (first comic link)
            home_content = home_page.content
            assert '|&lt;</a>' in home_content, \
                "Home page should contain the '|<' (first comic) link"
            
            # Simulate press of that button by fetching the first comic page
            first_comic_page = await fetch_archive_url(comic1_url, server_port)
            
            # Ensure that page IS a "Not in Archive" page
            assert first_comic_page.is_not_in_archive
            
            # Simulate press of the "Download" button on the "Not in Archive" page
            # by directly querying the related endpoint
            download_response = await bg_fetch_url(
                f'http://127.0.0.1:{server_port}/_/crystal/download-url',
                method='POST',
                data=json.dumps({'url': comic1_url}).encode('utf-8'),
                headers={'Content-Type': 'application/json'}
            )
            
            # Ensure the download started successfully
            assert download_response.status == 200
            download_result = json.loads(download_response.content)
            assert download_result['status'] == 'success'
            assert 'task_id' in download_result
            task_id = download_result['task_id']
            
            # Wait for the download task to complete
            await wait_for_download_to_start_and_finish(mw.task_tree)
            
            # Simulate the page reload after download completion
            # by re-fetching the first comic page
            reloaded_comic_page = await fetch_archive_url(comic1_url, server_port)
            
            # Ensure that the fetched page is now no longer a "Not In Archive" page
            assert reloaded_comic_page.status == 200
            assert not reloaded_comic_page.is_not_in_archive


@skip('covered by: test_given_nia_page_visible_when_download_button_pressed_then_download_starts_and_runs_with_progress_bar')
async def test_when_download_complete_and_successful_download_with_content_then_page_reloads_to_reveal_downloaded_page() -> None:
    pass


async def test_when_download_complete_and_successful_download_with_fetch_error_then_page_reloads_to_reveal_error_page() -> None:
    with served_project('testdata_xkcd.crystalproj.zip', port=_DEFAULT_SERVER_PORT) as sp:
        # Define URLs
        home_url = sp.get_request_url('https://xkcd.com/')
        comic1_url = sp.get_request_url('https://xkcd.com/1/')
        
        async with (await OpenOrCreateDialog.wait_for()).create() as (mw, project):
            # Download the home page
            if True:
                root_ti = TreeItem.GetRootItem(mw.entity_tree.window)
                assert root_ti.GetFirstChild() is None  # no entities
                
                # Add home URL as root resource
                click_button(mw.new_root_url_button)
                if True:
                    nud = await NewRootUrlDialog.wait_for()
                    
                    nud.name_field.Value = 'Home'
                    nud.url_field.Value = home_url
                    nud.do_not_download_immediately()
                    await nud.ok()
                (home_ti,) = root_ti.Children
                
                # Download the home page
                home_ti.SelectItem()
                await mw.click_download_button()
                await wait_for_download_to_start_and_finish(mw.task_tree)
            
            server_port = _DEFAULT_SERVER_PORT + 1
            home_url_in_archive = get_request_url(
                home_url,
                server_port,
                project_default_url_prefix=project.default_url_prefix)
            
            # Start the project server by clicking View button
            home_ti.SelectItem()
            with assert_does_open_webbrowser_to(home_url_in_archive):
                click_button(mw.view_button)
            
            # Verify that the home page is NOT a "Not in Archive" page
            home_page = await fetch_archive_url(home_url, server_port)
            assert not home_page.is_not_in_archive
            assert home_page.status == 200
            
            # Verify the home page contains a "|<" button (first comic link)
            home_content = home_page.content
            assert '|&lt;</a>' in home_content, \
                "Home page should contain the '|<' (first comic) link"
            
            # Simulate press of that button by fetching the first comic page
            first_comic_page = await fetch_archive_url(comic1_url, server_port)
            
            # Ensure that page IS a "Not in Archive" page
            assert first_comic_page.is_not_in_archive
            
            # Simulate press of the "Download" button with network down
            # by directly querying the related endpoint
            with network_down():  # for Crystal backend
                download_response = await bg_fetch_url(
                    f'http://127.0.0.1:{server_port}/_/crystal/download-url',
                    method='POST',
                    data=json.dumps({'url': comic1_url}).encode('utf-8'),
                    headers={'Content-Type': 'application/json'}
                )
                
                # Ensure the download started successfully
                assert download_response.status == 200
                download_result = json.loads(download_response.content)
                assert download_result['status'] == 'success'
                assert 'task_id' in download_result
                task_id = download_result['task_id']
                
                # Wait for the download task to complete (will fail due to network being down)
                await wait_for_download_to_start_and_finish(
                    mw.task_tree, immediate_finish_ok=True)
            
            # Simulate the page reload after download completion
            # by re-fetching the first comic page
            reloaded_comic_page = await fetch_archive_url(comic1_url, server_port)
            
            # Ensure that the fetched page shows a fetch error page (not "Not In Archive")
            try:
                assert reloaded_comic_page.is_fetch_error
            except AssertionError as e:
                raise AssertionError(
                    f'{e} '
                    f'Page content starts with: {reloaded_comic_page.content[:500]!r}'
                ) from None


async def test_when_download_fails_then_download_button_enables_and_page_does_not_reload() -> None:
    # 1. Skip Playwright test when Crystal is bundled
    # 2. Ensure Crystal is NOT bundled on at least one platform (Linux),
    #    so that Playwright tests will run on at least 1 CI job
    if is_linux():
        assert not hasattr(sys, 'frozen')
    if hasattr(sys, 'frozen'):
        skipTest('Playwright not available in bundled app')
    from playwright.sync_api import sync_playwright
    
    with served_project('testdata_xkcd.crystalproj.zip', port=_DEFAULT_SERVER_PORT) as sp:
        # Define URLs
        home_url = sp.get_request_url('https://xkcd.com/')
        comic1_url = sp.get_request_url('https://xkcd.com/1/')
        
        async with (await OpenOrCreateDialog.wait_for()).create() as (mw, project):
            # Download the home page
            if True:
                root_ti = TreeItem.GetRootItem(mw.entity_tree.window)
                assert root_ti.GetFirstChild() is None  # no entities
                
                # Add home URL as root resource
                click_button(mw.new_root_url_button)
                if True:
                    nud = await NewRootUrlDialog.wait_for()
                    
                    nud.name_field.Value = 'Home'
                    nud.url_field.Value = home_url
                    nud.do_not_download_immediately()
                    await nud.ok()
                (home_ti,) = root_ti.Children
                
                # Download the home page
                home_ti.SelectItem()
                await mw.click_download_button()
                await wait_for_download_to_start_and_finish(mw.task_tree)
            
            server_port = _DEFAULT_SERVER_PORT + 1
            home_url_in_archive = get_request_url(
                home_url,
                server_port,
                project_default_url_prefix=project.default_url_prefix)
            comic1_url_in_archive = get_request_url(
                comic1_url,
                server_port,
                project_default_url_prefix=project.default_url_prefix)
            
            # Start the project server by clicking View button
            home_ti.SelectItem()
            with assert_does_open_webbrowser_to(home_url_in_archive):
                click_button(mw.view_button)

            # Test the download button behavior in a real browser
            # 
            # 1. Run all Playwright operations in a background thread to
            #    avoid locking the foreground thread.
            # 2. Run all Playwright operations on a single consistent thread
            #    to comply with Playwright's threading requirements.
            # 
            # NOTE: This is the only automated test that uses Playwright,
            #       at the time of writing. When there are multiple tests
            #       that use Playwright, recommend enhancing testing
            #       infrastructure to support sharing a single Playwright,
            #       BrowserContext, and Browser instance between multiple
            #       test functions, to reduce setup/teardown overhead.
            with ThreadPoolExecutor(max_workers=1) as executor:
                def run_playwright_test():
                    # TODO: Allow browser's headless mode to be controlled by
                    #       an environment variable, like CRYSTAL_HEADLESS_BROWSER=False
                    with sync_playwright() as p, \
                            closing(p.chromium.launch(headless=True)) as browser, \
                            closing(browser.new_context()) as context:
                        context.set_default_timeout(int(DEFAULT_WAIT_TIMEOUT * 1000))
                        page = context.new_page()
                        
                        # Navigate to comic #1, which should be a "Not in Archive" page
                        page.goto(comic1_url_in_archive)
                        assert page.title() == 'Not in Archive | Crystal'
                        
                        # Mock fetch to simulate network failure after delay
                        # 
                        # Patch window.fetch manually, rather than using the
                        # route() API, since we need a delayed response without
                        # blocking the thread that calls download_button.click()
                        page.evaluate("""
                            window.originalFetch = window.fetch;
                            window.fetch = function(url, options) {
                                if (url && typeof url === 'string' && url.includes('/_/crystal/download-url')) {
                                    // Return a promise that rejects after 1 second
                                    return new Promise((resolve, reject) => {
                                        setTimeout(() => {
                                            reject(new Error('Network connection failed'));
                                        }, 1000);
                                    });
                                }
                                // For all other requests, use the original fetch
                                return window.originalFetch(url, options);
                            };
                        """)
                        
                        # Ensure download button is initially enabled
                        download_button = page.locator('#download-button')
                        assert download_button.is_enabled()
                        assert download_button.text_content() == '⬇ Download'
                        
                        # Ensure progress div is initially hidden
                        progress_div = page.locator('#download-progress')
                        assert not progress_div.is_visible()
                        
                        # Start download
                        download_button.click()
                        page.wait_for_function('document.getElementById("download-button").disabled')
                        assert download_button.text_content() == '⬇ Downloading...'
                        page.wait_for_selector('#download-progress', state='visible')
                        
                        # Wait for download failure. Then:
                        # 1. Ensure the page did NOT reload
                        # 2. Wait for the download button to be re-enabled
                        page.wait_for_function('!document.getElementById("download-button").disabled')
                        assert download_button.is_enabled()
                        assert download_button.text_content() == '⬇ Download'
                        
                        # Ensure error message is displayed
                        progress_text = page.locator('#progress-text')
                        progress_text_content = progress_text.text_content()
                        assertIn('Download failed:', progress_text_content)
                        assertIn('Network connection failed', progress_text_content)
                playwright_future = executor.submit(run_playwright_test)
                await wait_for_future(playwright_future, timeout=sys.maxsize)


# ------------------------------------------------------------------------------
# Test: "Fetch Error" Page (send_resource_error)

async def test_given_fetch_error_page_visible_then_crystal_branding_and_error_message_and_url_is_visible() -> None:
    async with _fetch_error_page_visible() as (server_page, failing_url):
        # Verify Crystal branding is visible
        content = server_page.content
        assert 'Crystal' in content, \
            "Crystal branding should be visible in page content"
        
        # Verify the failing URL is displayed in the error message
        assert failing_url in content, \
            f"Failing URL {failing_url} should be visible in the error message"
        
        # Verify basic error message content
        assert '<strong>Fetch Error</strong>' in content, \
            "Error message should indicate there was a fetch error"


async def test_given_fetch_error_page_visible_when_press_go_back_button_then_navigates_to_previous_page() -> None:
    async with _fetch_error_page_visible() as (server_page, failing_url):
        # Verify a go back button is present in the content
        content = server_page.content
        assert '← Go Back' in content and 'onclick="history.back()"' in content, \
            "Go back button should be present on fetch error page"


# ------------------------------------------------------------------------------
# Test: Header Inclusion & Exclusion (_HEADER_ALLOWLIST, _HEADER_DENYLIST)

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
# Test: Misc Functionality (in _do_GET and _do_POST)

@skip('not yet automated')
async def test_js_date_always_returns_datetime_that_resource_was_downloaded() -> None:
    # Case 1: new Date()
    # Case 2: Date()
    # Case 3: Date.now()
    pass


# ------------------------------------------------------------------------------
# Utility

@asynccontextmanager
async def _welcome_page_visible(*, readonly: bool=False) -> AsyncIterator[WebPage]:
    """
    Context manager that opens a test project, starts a server, and returns a WebPage
    for the welcome page by requesting the root path "/".
    
    Arguments:
    * readonly -- Whether to open the project in readonly mode
    """
    with extracted_project('testdata_xkcd.crystalproj.zip') as project_dirpath:
        async with (await OpenOrCreateDialog.wait_for()).open(project_dirpath, readonly=readonly) as (mw, project):
            # Start server
            root_ti = TreeItem.GetRootItem(mw.entity_tree.window)
            home_ti = root_ti.GetFirstChild()
            assert home_ti is not None
            home_ti.SelectItem()
            with assert_does_open_webbrowser_to(get_request_url('https://xkcd.com/')):
                click_button(mw.view_button)
            
            # Fetch the welcome page by requesting the root path directly
            welcome_page = await bg_fetch_url(f'http://127.0.0.1:{_DEFAULT_SERVER_PORT}/')
            assert welcome_page.title == 'Welcome | Crystal'
            assert welcome_page.status == 200
            
            yield welcome_page


@asynccontextmanager
async def _not_found_page_visible(*, readonly: bool=False) -> AsyncIterator[WebPage]:
    """
    Context manager that opens a test project, starts a server, and returns a WebPage
    for a "Not Found" page by requesting a non-existent path that isn't a URL.
    
    Arguments:
    * readonly -- Whether to open the project in readonly mode (not used for this page type)
    """
    with extracted_project('testdata_xkcd.crystalproj.zip') as project_dirpath:
        async with (await OpenOrCreateDialog.wait_for()).open(project_dirpath, readonly=readonly) as (mw, project):
            # Start server
            root_ti = TreeItem.GetRootItem(mw.entity_tree.window)
            home_ti = root_ti.GetFirstChild()
            assert home_ti is not None
            home_ti.SelectItem()
            with assert_does_open_webbrowser_to(get_request_url('https://xkcd.com/')):
                click_button(mw.view_button)
            
            # Fetch a not found page by requesting a non-existent path directly
            not_found_page = await bg_fetch_url(f'http://127.0.0.1:{_DEFAULT_SERVER_PORT}/non-existent-path')
            assert not_found_page.title == 'Not Found | Crystal'
            assert not_found_page.status == 404
            
            yield not_found_page


@asynccontextmanager
async def _not_in_archive_page_visible(*, readonly: bool=False) -> AsyncIterator[WebPage]:
    """
    Context manager that opens a test project, starts a server, and returns a WebPage
    for a "Not in Archive" page by requesting a URL that doesn't exist in the archive.
    
    Arguments:
    * readonly -- Whether to open the project in readonly mode
    """
    with extracted_project('testdata_xkcd.crystalproj.zip') as project_dirpath:
        # Define URLs - use a URL that is NOT in the archive to trigger NIA page
        missing_url = 'https://xkcd.com/missing-page/'
        
        async with (await OpenOrCreateDialog.wait_for()).open(project_dirpath, readonly=readonly) as (mw, project):
            # Start server
            root_ti = TreeItem.GetRootItem(mw.entity_tree.window)
            home_ti = root_ti.GetFirstChild()
            assert home_ti is not None
            home_ti.SelectItem()
            with assert_does_open_webbrowser_to(get_request_url('https://xkcd.com/')):
                click_button(mw.view_button)
            
            # Verify that "Not in Archive" page reached
            nia_page = await fetch_archive_url(missing_url)
            assert nia_page.is_not_in_archive
            assert nia_page.title == 'Not in Archive | Crystal'
            assert nia_page.status == 404
            
            yield nia_page


@asynccontextmanager
async def _fetch_error_page_visible() -> AsyncIterator[tuple[WebPage, str]]:
    """
    Context manager that opens a test project, starts a server, and returns a WebPage
    for a "Fetch Error" page by requesting a URL that exists while the network is down.
    """
    with served_project('testdata_xkcd.crystalproj.zip', port=_DEFAULT_SERVER_PORT) as sp:
        # Define URLs
        home_url = sp.get_request_url('https://xkcd.com/')
        
        async with (await OpenOrCreateDialog.wait_for()).create() as (mw, project):
            # Download the home page when network is down to cause fetch error
            if True:
                root_ti = TreeItem.GetRootItem(mw.entity_tree.window)
                assert root_ti.GetFirstChild() is None  # no entities
                
                # Add home URL as root resource
                click_button(mw.new_root_url_button)
                if True:
                    nud = await NewRootUrlDialog.wait_for()
                    
                    nud.name_field.Value = 'Home'
                    nud.url_field.Value = home_url
                    nud.do_not_download_immediately()
                    await nud.ok()
                (home_ti,) = root_ti.Children
                
                # Download the home page, when network is down
                with network_down():
                    home_ti.SelectItem()
                    await mw.click_download_button()
                    await wait_for_download_to_start_and_finish(mw.task_tree)
            
            server_port = _DEFAULT_SERVER_PORT + 1
            home_url_in_archive = get_request_url(
                home_url,
                server_port,
                project_default_url_prefix=project.default_url_prefix)
            
            # Start the project server by clicking View button
            home_ti.SelectItem()
            with assert_does_open_webbrowser_to(home_url_in_archive):
                click_button(mw.view_button)
            
            # Verify that "Fetch Error" page reached
            fetch_error_page = await fetch_archive_url(home_url, server_port)
            assert fetch_error_page.is_fetch_error
            assert fetch_error_page.title == 'Fetch Error | Crystal'
            assert fetch_error_page.status == 400
            
            yield (fetch_error_page, home_url)


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
