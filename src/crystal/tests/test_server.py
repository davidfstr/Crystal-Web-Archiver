from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager, closing, redirect_stdout
from copy import deepcopy
from crystal import server
from crystal.doc.html.soup import HtmlDocument
from crystal.model import Project, Resource, ResourceRevision, RootResource
from crystal.server import _DEFAULT_SERVER_PORT, ProjectServer, get_request_url
from crystal.server.footer_banner import _FOOTER_BANNER_MESSAGE
from crystal.server.special_pages import generic_404_page_html
from crystal.tests.util.asserts import assertEqual, assertIn, assertNotIn
from crystal.tests.util.controls import click_button, click_checkbox, TreeItem
from crystal.tests.util.data import LOREM_IPSUM_LONG, LOREM_IPSUM_SHORT
from crystal.tests.util.downloads import network_down
from crystal.tests.util.pages import (
    NotInArchivePage, network_down_after_delay, reloads_paused
)
from crystal.tests.util.runner import bg_fetch_url
from crystal.tests.util.server import (
    assert_does_open_webbrowser_to, extracted_project, fetch_archive_url,
    MockHttpServer, served_project, WebPage,
)
from crystal.tests.util.skip import skipTest
from crystal.tests.util.subtests import SubtestsContext, awith_subtests
from crystal.tests.util.tasks import wait_for_download_to_start_and_finish
from crystal.tests.util.wait import DEFAULT_WAIT_TIMEOUT, DEFAULT_WAIT_PERIOD, wait_for_future
from crystal.tests.util.windows import (
    MainWindow, NewRootUrlDialog, OpenOrCreateDialog,
)
from crystal.tests.util.xplaywright import (
    Playwright, RawPage, awith_playwright, expect,
)
from crystal.util.cli import TERMINAL_FG_PURPLE, colorize
from crystal.util.ports import is_port_in_use
from io import StringIO
import json
from textwrap import dedent
from unittest import skip
from unittest.mock import ANY, patch


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
            # 
            # TODO: Suppress warning: '*** Default port for project server is in use. Is a real Crystal app running in the background?'
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
#     - send_http_revision -- partially covered below
#     - send_generic_revision


@skip('not yet automated')
def test_when_url_requested_corresponds_to_partially_downloaded_resource_then_wait_for_embedded_subresources_before_serving_resource() -> None:
    pass


@skip('covered by: test_can_download_and_serve_a_site_requiring_dynamic_url_discovery')
def test_when_url_requested_corresponds_to_undownloaded_resource_matching_a_defined_root_resource_then_dynamically_downloads_the_url() -> None:
    # In particular, covers when the following warning is
    # printed to the server console:
    # - '*** Dynamically downloading root resource ...'
    pass


@skip('covered by: test_can_download_and_serve_a_site_requiring_dynamic_url_discovery')
def test_when_url_requested_corresponds_to_undownloaded_resource_matching_a_defined_resource_group_then_dynamically_downloads_the_url() -> None:
    # In particular, covers two cases where one of the following warnings is
    # printed to the server console:
    # - '*** Dynamically downloading new resource in group ...'
    # - '*** Dynamically downloading existing resource in group ...'
    pass


@skip('covered by: test_can_download_and_serve_a_site_requiring_dynamic_link_rewriting')
def test_when_url_requested_appears_to_be_a_site_relative_url_constructed_by_javascript_then_redirects_to_corresponding_archive_url() -> None:
    # In particular, covers when the following warning is
    # printed to the server console:
    # - '*** Dynamically rewriting link from ...'
    pass


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
# Test: Special Pages

@awith_playwright
async def test_when_serve_special_page_and_branding_logo_cannot_load_then_replaces_logo_with_simplified_svg_fallback(pw: Playwright) -> None:
    # Use the "Not in Archive" special page, 
    # with the logo image prevented from loading successfully
    original_public_filenames = server._RequestHandler.PUBLIC_STATIC_RESOURCE_NAMES
    with patch.object(
            server._RequestHandler,
            'PUBLIC_STATIC_RESOURCE_NAMES',
            original_public_filenames - {'appicon.png'}):
        async with _not_in_archive_page_visible() as server_page:
            # Verify the NIA page contains branding header
            assert server_page.is_not_in_archive
            assert server_page.status == 404
            assert 'cr-brand-header' in server_page.content
            
            # Use Playwright to verify the fallback logo is displayed
            def pw_task(raw_page: RawPage, *args, **kwargs) -> None:
                # Navigate to the NIA page 
                raw_page.goto(f'http://127.0.0.1:{_DEFAULT_SERVER_PORT}/https://xkcd.com/missing-page/')
                
                # Ensure the brand header exists
                brand_header = raw_page.locator('.cr-brand-header')
                expect(brand_header).to_be_visible()
                
                # Ensure the main logo image is hidden due to error
                main_logo = brand_header.locator('.cr-brand-header__logo--image')
                expect(main_logo).to_have_count(1)
                expect(main_logo).to_have_css('display', 'none')
                
                # Ensure the fallback logo image is visible
                fallback_logo = brand_header.locator('.cr-brand-header__logo--image_fallback')
                expect(fallback_logo).to_have_count(1)
                expect(fallback_logo).to_have_css('display', 'inline')
                expect(fallback_logo).to_be_visible()
                
                # Verify the fallback logo src is a data URL (inlined SVG),
                # which should always be available and render correctly
                fallback_src = fallback_logo.get_attribute('src')
                assert fallback_src is not None
                assert fallback_src.startswith('data:image/svg+xml;base64,')
            await pw.run(pw_task)


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


async def test_when_invalid_internal_crystal_url_is_requested_then_always_serves_not_found_page() -> None:
    with Project() as project:
        with closing(ProjectServer(project, _DEFAULT_SERVER_PORT)) as sp:
            invalid_page = await bg_fetch_url('http://127.0.0.1:2797/_/')
            assertEqual('Not Found | Crystal', invalid_page.title)  # not_found_page_html
            
            invalid_page = await bg_fetch_url('http://127.0.0.1:2797/_/https/')
            assertEqual('Not Found | Crystal', invalid_page.title)  # not_found_page_html
            
            missing_page = await bg_fetch_url('http://127.0.0.1:2797/_/https/xkcd.com/')
            assertEqual('Not in Archive | Crystal', missing_page.title)  # not_in_archive_html


async def test_when_404_html_at_site_root_is_requested_then_always_serves_not_found_page() -> None:
    # ...and NOT a "Not in Archive" page or a "Generic 404" page
    
    # Case 1: A more-direct test
    with Project() as project:
        with closing(ProjectServer(project, _DEFAULT_SERVER_PORT)) as sp:
            reserved_404_page = await bg_fetch_url('http://127.0.0.1:2797/404.html')
            assertEqual('Not Found | Crystal', reserved_404_page.title)  # not_found_page_html
    
    # Case 2: A more-realistic test
    if True:
        COMIC_PAGE = dict(
            status_code=200,
            headers=[('Content-Type', 'text/html')],
            content='Comic!'.encode('utf-8')
        )
        
        _404_PAGE = dict(
            status_code=404,
            headers=[('Content-Type', 'text/html')],
            content='404!'.encode('utf-8')
        )
        
        server = MockHttpServer({
            '/': COMIC_PAGE,
            # NOTE: An exported site will have a 404 HTML page in this location.
            #       ProjectServer will never serve an archive URL here.
            '/404.html': _404_PAGE,
        })
        with server:
            home_url = server.get_url('/')
            _404_url = server.get_url('/404.html')
            
            with Project() as project:
                project.default_url_prefix = home_url.removesuffix('/')
                home_rr = RootResource(project, '', Resource(project, home_url))
                _404_rr = RootResource(project, '', Resource(project, _404_url))
                
                await wait_for_future(home_rr.download())
                await wait_for_future(_404_rr.download())
                
                with closing(ProjectServer(project, _DEFAULT_SERVER_PORT)) as sp:
                    home_url_in_archive = sp.get_request_url(home_url)
                    _404_url_in_archive = sp.get_request_url(_404_url)
                    
                    assertEqual(
                        'http://127.0.0.1:2797/',
                        home_url_in_archive)
                    assertEqual(
                        # NOT: 'http://127.0.0.1:2797/404.html'
                        #      even though it is in the default URL prefix "http://127.0.0.1:2798/"
                        'http://127.0.0.1:2797/_/http/127.0.0.1:2798/404.html',
                        _404_url_in_archive)
                    reserved_404_html_url_in_archive = \
                        'http://127.0.0.1:2797/404.html'
                    
                    home_page = await bg_fetch_url(home_url_in_archive)
                    assertIn('Comic!', home_page.content)
                    
                    _404_page = await bg_fetch_url(_404_url_in_archive)
                    assertIn('404!', _404_page.content)
                    
                    reserved_404_page = await bg_fetch_url(reserved_404_html_url_in_archive)
                    assertEqual('Not Found | Crystal', reserved_404_page.title)  # not_found_page_html


# ------------------------------------------------------------------------------
# Test: "Generic 404" Page (generic_404_page_html)

async def test_given_404_page_visible_then_no_crystal_branding_is_visible() -> None:
    # ...because the 404 page is intended to blend into its parent site
    
    async with _generic_404_page_visible() as server_page:
        content = server_page.content
        assertNotIn('<div class="cr-brand-header">', content)
        assertNotIn('Crystal', server_page.title)


@awith_playwright
async def test_given_404_page_visible_and_served_from_root_directory_of_domain_then_url_box_links_to_correct_original_url(pw: Playwright) -> None:
    _404_PAGE = dict(
        status_code=404,
        headers=[('Content-Type', 'text/html')],
        content=generic_404_page_html(
            default_url_prefix='https://xkcd.com',
        ).encode('utf-8')
    )
    
    # Case 1: Request URL is within the domain of the default URL prefix
    # - Default URL prefix is 'https://xkcd.com'
    # - Serve root is: 'http://xkcd.daarchive.net/'
    # - Request URL is: 'http://xkcd.daarchive.net/222/'
    # - Then archive URL should be: 'https://xkcd.com/222/'
    server = MockHttpServer({
        '/404.html': _404_PAGE,
        '/222/': _404_PAGE,
    })
    with server:
        missing_comic_url = server.get_url('/222/')
        
        def pw_task(raw_page: RawPage, *args, **kwargs) -> None:
            raw_page.goto(missing_comic_url)
            url_box_link = raw_page.locator('.cr-url-box__link')
            expect(url_box_link).to_have_text('https://xkcd.com/222/')
        await pw.run(pw_task)
    
    # Case 2: Request URL is outside the domain of the default URL prefix
    # - Default URL prefix is 'https://xkcd.com'
    # - Serve root is: 'http://xkcd.daarchive.net/'
    # - Request URL is: 'http://xkcd.daarchive.net/_/https/c.xkcd.com/random/comic/'
    # - Then archive URL should be: 'https://c.xkcd.com/random/comic/'
    server = MockHttpServer({
        '/404.html': _404_PAGE,
        '/_/https/c.xkcd.com/random/comic/': _404_PAGE,
    })
    with server:
        missing_comic_url = server.get_url('/_/https/c.xkcd.com/random/comic/')
        
        def pw_task(raw_page: RawPage, *args, **kwargs) -> None:
            raw_page.goto(missing_comic_url)
            url_box_link = raw_page.locator('.cr-url-box__link')
            expect(url_box_link).to_have_text('https://c.xkcd.com/random/comic/')
        await pw.run(pw_task)


@awith_playwright
async def test_given_404_page_visible_and_served_from_subdirectory_of_domain_then_url_box_links_to_correct_original_url(pw: Playwright) -> None:
    _404_PAGE = dict(
        status_code=404,
        headers=[('Content-Type', 'text/html')],
        content=generic_404_page_html(
            default_url_prefix='https://xkcd.com',
        ).encode('utf-8')
    )
    
    OTHER_CRYSTAL_404_PAGE = dict(
        status_code=404,
        headers=[('Content-Type', 'text/html')],
        content=generic_404_page_html(
            default_url_prefix='https://blag.xkcd.com',
        ).encode('utf-8')
    )
    
    # Case 1: Request URL is within the domain of the default URL prefix
    # - Default URL prefix is 'https://xkcd.com'
    # - Serve root is: 'http://dafoster.net/xkcd.daarchive.net/'
    # - Request URL is: 'http://dafoster.net/xkcd.daarchive.net/222/'
    # - Then archive URL should be: 'https://xkcd.com/222/'
    if True:
        # Case 1.1: Has no 404.html in any parent directories
        server = MockHttpServer({
            '/xkcd.daarchive.net/404.html': _404_PAGE,
            '/xkcd.daarchive.net/222/': _404_PAGE,
        })
        with server:
            missing_comic_url = server.get_url('/xkcd.daarchive.net/222/')
            
            def pw_task(raw_page: RawPage, *args, **kwargs) -> None:
                raw_page.goto(missing_comic_url)
                url_box_link = raw_page.locator('.cr-url-box__link')
                expect(url_box_link).to_have_text('https://xkcd.com/222/')
            await pw.run(pw_task)
        
        # Case 1.2: Has OTHER_CRYSTAL_404_PAGE in a parent directory
        server = MockHttpServer({
            '/404.html': OTHER_CRYSTAL_404_PAGE,
            '/xkcd.daarchive.net/404.html': _404_PAGE,
            '/xkcd.daarchive.net/222/': _404_PAGE,
        })
        with server:
            missing_comic_url = server.get_url('/xkcd.daarchive.net/222/')
            
            def pw_task(raw_page: RawPage, *args, **kwargs) -> None:
                raw_page.goto(missing_comic_url)
                url_box_link = raw_page.locator('.cr-url-box__link')
                expect(url_box_link).to_have_text('https://xkcd.com/222/')
            await pw.run(pw_task)

    # Case 2: Request URL is outside the domain of the default URL prefix
    # - Default URL prefix is 'https://xkcd.com'
    # - Serve root is: 'http://dafoster.net/xkcd.daarchive.net/'
    # - Request URL is: 'http://dafoster.net/xkcd.daarchive.net/_/https/c.xkcd.com/random/comic/'
    # - Then archive URL should be: 'https://c.xkcd.com/random/comic/'
    if True:
        # Case 2.1: Has no 404.html in any parent directories
        server = MockHttpServer({
            '/xkcd.daarchive.net/404.html': _404_PAGE,
            '/xkcd.daarchive.net/_/https/c.xkcd.com/random/comic/': _404_PAGE,
        })
        with server:
            missing_comic_url = server.get_url('/xkcd.daarchive.net/_/https/c.xkcd.com/random/comic/')
            
            def pw_task(raw_page: RawPage, *args, **kwargs) -> None:
                raw_page.goto(missing_comic_url)
                url_box_link = raw_page.locator('.cr-url-box__link')
                expect(url_box_link).to_have_text('https://c.xkcd.com/random/comic/')
            await pw.run(pw_task)
        
        # Case 2.2: Has OTHER_CRYSTAL_404_PAGE in a parent directory
        server = MockHttpServer({
            '/404.html': OTHER_CRYSTAL_404_PAGE,
            '/xkcd.daarchive.net/404.html': _404_PAGE,
            '/xkcd.daarchive.net/_/https/c.xkcd.com/random/comic/': _404_PAGE,
        })
        with server:
            missing_comic_url = server.get_url('/xkcd.daarchive.net/_/https/c.xkcd.com/random/comic/')
            
            def pw_task(raw_page: RawPage, *args, **kwargs) -> None:
                raw_page.goto(missing_comic_url)
                url_box_link = raw_page.locator('.cr-url-box__link')
                expect(url_box_link).to_have_text('https://c.xkcd.com/random/comic/')
            await pw.run(pw_task)


@awith_playwright
async def test_given_404_page_viewed_directly_then_does_not_link_to_any_original_url(pw: Playwright) -> None:
    _404_PAGE = dict(
        status_code=404,
        headers=[('Content-Type', 'text/html')],
        content=generic_404_page_html(
            default_url_prefix='https://xkcd.com',
        ).encode('utf-8')
    )
    
    server = MockHttpServer({
        '/404.html': _404_PAGE,
    })
    with server:
        missing_comic_url = server.get_url('/404.html')
        
        def pw_task(raw_page: RawPage, *args, **kwargs) -> None:
            raw_page.goto(missing_comic_url)
            url_box_link = raw_page.locator('.cr-url-box__link')
            expect(url_box_link).to_have_text("See browser's URL")
        await pw.run(pw_task)


@awith_playwright
async def test_when_404_page_downloaded_and_served_by_crystal_then_url_box_links_to_correct_original_url(pw: Playwright) -> None:
    original_404_url = 'https://xkcd.com/missing-page/'
    async with _generic_404_page_visible(request_path='/missing-page/', headless=True) as server_page:
        served_404_url = server_page.request_url
        
        async with (await OpenOrCreateDialog.wait_for()).create() as (mw, project):
            # Create RootResource with dialog, which should also set the default URL prefix
            click_button(mw.new_root_url_button)
            nrud = await NewRootUrlDialog.wait_for()
            nrud.url_field.Value = served_404_url
            nrud.do_not_download_immediately()  # easier to test
            await nrud.ok()
            
            # Start server
            root_ti = TreeItem.GetRootItem(mw.entity_tree.window)
            (home_ti,) = root_ti.Children
            home_ti.SelectItem()
            served_404_url_in_archive = get_request_url(
                served_404_url,
                project_default_url_prefix=project.default_url_prefix)
            with assert_does_open_webbrowser_to(served_404_url_in_archive):
                click_button(mw.view_button)
            
            def pw_task(raw_page: RawPage, *args, **kwargs) -> None:
                raw_page.goto(served_404_url_in_archive)
                url_box_link = raw_page.locator('.cr-url-box__link')
                expect(url_box_link).to_have_text(original_404_url)
            await pw.run(pw_task)


@awith_playwright
async def test_when_404_page_exported_by_crystal_is_downloaded_and_served_by_crystal_then_url_box_links_to_correct_original_url(pw: Playwright) -> None:
    COMIC_PAGE = dict(
        status_code=200,
        headers=[('Content-Type', 'text/html')],
        content='Comic!'.encode('utf-8')
    )
    
    _404_PAGE = dict(
        status_code=404,
        headers=[('Content-Type', 'text/html')],
        content=generic_404_page_html(
            default_url_prefix='https://xkcd.com',
        ).encode('utf-8')
    )
    
    server = MockHttpServer({
        '/': COMIC_PAGE,
        '/99999/index.html': _404_PAGE,
        '/_/https/c.xkcd.com/random/comic/index.html': _404_PAGE,
        
        # NOTE: An exported site will have a 404 HTML page in this location.
        #       However a ProjectServer will always serve a "Not Found" page
        #       at this special location.
        '/404.html': _404_PAGE,
    })
    with server:
        home_url = server.get_url('/')
        _404_url_samedomain = server.get_url('/99999/index.html')
        _404_url_otherdomain = server.get_url('/_/https/c.xkcd.com/random/comic/index.html')
        
        async with (await OpenOrCreateDialog.wait_for()).create() as (mw, project):
            # Create RootResource with dialog, which should also set the default URL prefix
            click_button(mw.new_root_url_button)
            nrud = await NewRootUrlDialog.wait_for()
            nrud.url_field.Value = home_url
            nrud.do_not_download_immediately()  # easier to test
            click_checkbox(nrud.create_group_checkbox)
            assert nrud.create_group_checkbox.Value  # download URLs in domain upon request
            await nrud.ok()
            
            # Start server
            root_ti = TreeItem.GetRootItem(mw.entity_tree.window)
            (home_ti, *_) = root_ti.Children
            home_ti.SelectItem()
            with assert_does_open_webbrowser_to(ANY):
                click_button(mw.view_button)
            
            _404_url_samedomain_in_archive = get_request_url(
                _404_url_samedomain,
                project_default_url_prefix=project.default_url_prefix)
            _404_url_otherdomain_in_archive = get_request_url(
                _404_url_otherdomain,
                project_default_url_prefix=project.default_url_prefix)
            
            def pw_task(raw_page: RawPage, *args, **kwargs) -> None:
                raw_page.goto(_404_url_samedomain_in_archive)
                url_box_link = raw_page.locator('.cr-url-box__link')
                expect(url_box_link).to_have_text('https://xkcd.com/99999/index.html')
                
                raw_page.goto(_404_url_otherdomain_in_archive)
                url_box_link = raw_page.locator('.cr-url-box__link')
                expect(url_box_link).to_have_text('https://c.xkcd.com/random/comic/index.html')
            await pw.run(pw_task)


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
        assert '<div class="cr-readonly-warning">' in content, \
            "Readonly warning should be visible when project is readonly"
        
        # Download button should be present but disabled
        assert '<button id="cr-download-url-button" ' in content, \
            "Download button should be present in readonly mode"
        assert '<button id="cr-download-url-button" disabled ' in content, \
            "Download button should be disabled in readonly mode"


async def test_given_nia_page_visible_and_project_is_writable_then_download_button_is_enabled_and_readonly_warning_is_not_visible() -> None:
    async with _not_in_archive_page_visible(readonly=False) as server_page:
        content = server_page.content
        
        # Should NOT show readonly warning
        assert '<div class="cr-readonly-warning">' not in content, \
            "Readonly warning should NOT be visible when project is writable"
        
        # Download button should be present and enabled
        assert '<button id="cr-download-url-button" ' in content, \
            "Download button should be present when project is writable"
        assert '<button id="cr-download-url-button" disabled ' not in content, \
            "Download button should NOT be disabled when project is writable"


async def test_given_nia_page_visible_when_download_button_pressed_then_download_starts_and_runs_with_progress_bar() -> None:
    with served_project('testdata_xkcd.crystalproj.zip') as sp:
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
            
            home_url_in_archive = get_request_url(
                home_url,
                project_default_url_prefix=project.default_url_prefix)
            
            # Start the project server by clicking View button
            home_ti.SelectItem()
            with assert_does_open_webbrowser_to(home_url_in_archive):
                click_button(mw.view_button)
            
            # Verify that the home page is NOT a "Not in Archive" page
            home_page = await fetch_archive_url(home_url)
            assert not home_page.is_not_in_archive
            assert home_page.status == 200
            
            # Verify the home page contains a "|<" button (first comic link)
            home_content = home_page.content
            assert '|&lt;</a>' in home_content, \
                "Home page should contain the '|<' (first comic) link"
            
            # Simulate press of that button by fetching the first comic page
            first_comic_page = await fetch_archive_url(comic1_url)
            
            # Ensure that page IS a "Not in Archive" page
            assert first_comic_page.is_not_in_archive
            
            # Simulate press of the "Download" button on the "Not in Archive" page
            # by directly querying the related endpoint
            server_port = _DEFAULT_SERVER_PORT
            download_response = await bg_fetch_url(
                f'http://127.0.0.1:{server_port}/_/crystal/download-url',
                method='POST',
                data=json.dumps({
                    'url': comic1_url,
                    'is_root': True,
                }).encode('utf-8'),
                headers={'Content-Type': 'application/json'}
            )
            
            # Ensure the download started successfully
            assert download_response.status == 200
            download_result = json.loads(download_response.content)
            assert download_result['status'] == 'success'
            assert 'task_id' in download_result
            task_id = download_result['task_id']
            
            # Wait for the download task to complete
            await wait_for_download_to_start_and_finish(mw.task_tree, immediate_finish_ok=True)
            
            # Simulate the page reload after download completion
            # by re-fetching the first comic page
            reloaded_comic_page = await fetch_archive_url(comic1_url)
            
            # Ensure that the fetched page is now no longer a "Not In Archive" page
            assert reloaded_comic_page.status == 200
            assert not reloaded_comic_page.is_not_in_archive


# TODO: Implement discrete test that actually checks that the progress bar updates
@skip('covered by: test_given_nia_page_visible_when_download_button_pressed_then_download_starts_and_runs_with_progress_bar')
async def test_when_download_complete_and_successful_download_with_content_then_page_reloads_to_reveal_downloaded_page() -> None:
    pass


async def test_when_download_complete_and_successful_download_with_fetch_error_then_page_reloads_to_reveal_error_page() -> None:
    with served_project('testdata_xkcd.crystalproj.zip') as sp:
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
            
            home_url_in_archive = get_request_url(
                home_url,
                project_default_url_prefix=project.default_url_prefix)
            
            # Start the project server by clicking View button
            home_ti.SelectItem()
            with assert_does_open_webbrowser_to(home_url_in_archive):
                click_button(mw.view_button)
            
            # Verify that the home page is NOT a "Not in Archive" page
            home_page = await fetch_archive_url(home_url)
            assert not home_page.is_not_in_archive
            assert home_page.status == 200
            
            # Verify the home page contains a "|<" button (first comic link)
            home_content = home_page.content
            assert '|&lt;</a>' in home_content, \
                "Home page should contain the '|<' (first comic) link"
            
            # Simulate press of that button by fetching the first comic page
            first_comic_page = await fetch_archive_url(comic1_url)
            
            # Ensure that page IS a "Not in Archive" page
            assert first_comic_page.is_not_in_archive
            
            # Simulate press of the "Download" button with network down
            # by directly querying the related endpoint
            with network_down():  # for backend
                server_port = _DEFAULT_SERVER_PORT
                download_response = await bg_fetch_url(
                    f'http://127.0.0.1:{server_port}/_/crystal/download-url',
                    method='POST',
                    data=json.dumps({
                        'url': comic1_url,
                        'is_root': True,
                    }).encode('utf-8'),
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
            reloaded_comic_page = await fetch_archive_url(comic1_url)
            
            # Ensure that the fetched page shows a fetch error page (not "Not In Archive")
            try:
                assert reloaded_comic_page.is_fetch_error
            except AssertionError as e:
                raise AssertionError(
                    f'{e} '
                    f'Page content starts with: {reloaded_comic_page.content[:500]!r}'
                ) from None


@awith_playwright
async def test_when_download_fails_then_download_button_enables_and_page_does_not_reload(pw: Playwright) -> None:
    async with _not_in_archive_page_visible_temporarily() as (comic1_url_in_archive, *_):
        def pw_task(raw_page: RawPage, *args, **kwargs) -> None:
            page = NotInArchivePage.open(raw_page, url_in_archive=comic1_url_in_archive)
            
            with network_down_after_delay(page):  # for frontend
                # Ensure download button is initially enabled
                expect(page.download_url_button).to_be_enabled()
                expect(page.download_url_button).to_contain_text('⬇ Download')
                
                # Ensure progress bar is initially hidden
                expect(page.progress_bar).not_to_be_visible()
                
                # Start download
                page.download_url_button.click()
                # TODO: Pause something to prevent download from immediately completing
                expect(page.download_url_button).to_be_disabled()
                expect(page.download_url_button).to_contain_text('⬇ Downloading...')
                page.progress_bar.wait_for(state='visible')
                
                # Wait for download failure. Then:
                # 1. Ensure the page did NOT reload
                # 2. Wait for the download button to be re-enabled
                expect(page.download_url_button).to_be_enabled()
                expect(page.download_url_button).to_contain_text('⬇ Download')
                
                # Ensure error message is displayed
                progress_bar_message = page.progress_bar_message
                assertIn('Download failed:', progress_bar_message)
                assertIn('Network connection failed', progress_bar_message)
        await pw.run(pw_task)


async def test_given_readonly_project_then_create_group_checkbox_is_disabled() -> None:
    async with _not_in_archive_page_visible(readonly=True) as server_page:
        content = server_page.content
        
        # Create group checkbox should be present but disabled
        assert '<input type="checkbox" id="cr-create-group-checkbox"' in content, \
            "Create group checkbox should be present even in readonly mode"
        assert '<input type="checkbox" id="cr-create-group-checkbox" disabled ' in content, \
            "Create group checkbox should be disabled in readonly mode"


@skip('covered by: test_given_create_group_form_visible_when_download_group_checkbox_unticked_then_download_button_is_replaced_with_create_button')
async def test_given_writable_project_when_create_group_checkbox_ticked_then_shows_create_group_form() -> None:
    # ...and URL Pattern is populated with a suggestion
    # ...and Source is populated with a suggestion
    # ...and Preview Members are populated
    # ...and Download Immediately checkbox is ticked
    # ...and has Cancel and Download buttons
    pass


@awith_playwright
async def test_given_create_group_form_visible_when_download_group_checkbox_unticked_then_download_button_is_replaced_with_create_button(pw: Playwright) -> None:
    async with _not_in_archive_page_visible_temporarily() as (comic1_url_in_archive, home_url_in_archive, *_):
        def pw_task(raw_page: RawPage, *args, **kwargs) -> None:
            page = _navigate_from_home_to_comic_1_nia_page(
                raw_page, home_url_in_archive, comic1_url_in_archive)

            # Ensure create group checkbox exists and is unchecked initially
            expect(page.create_group_checkbox).to_be_visible()
            expect(page.create_group_checkbox).not_to_be_checked()
            
            # Ensure form is initially hidden
            expect(page.create_group_form).not_to_be_visible()
            
            # Click the create group checkbox to show the form
            page.create_group_checkbox.click()
            expect(page.create_group_checkbox).to_be_checked()
            expect(page.create_group_form).to_be_visible()
            
            # Verify that URL Pattern is populated with a suggestion
            expect(page.url_pattern_field).to_be_visible()
            expect(page.url_pattern_field).not_to_have_value('')
            assert 'xkcd.com' in page.url_pattern_field.input_value()
            
            # Verify that Source dropdown is populated with suggestions
            expect(page.source_dropdown).to_be_visible()
            source_options = page.source_dropdown.locator('option')
            source_option_count = source_options.count()
            assert source_option_count >= 2, \
                "Source dropdown should have at least 'none' plus one root resource option"
            
            # Verify that Preview Members are populated (asynchronously)
            page.wait_for_initial_preview_urls()
            expect(page.preview_urls_container).to_contain_text('xkcd.com')
            
            # Verify that the download immediately checkbox is checked by default
            expect(page.download_immediately_checkbox).to_be_checked()
            
            # Verify that the group action button shows "Download" initially
            expect(page.download_or_create_group_button).to_be_visible()
            expect(page.download_or_create_group_button).to_contain_text('⬇ Download')
            
            # Uncheck the download immediately checkbox
            page.download_immediately_checkbox.click()
            expect(page.download_immediately_checkbox).not_to_be_checked()
            
            # Verify that the group action button now shows "Create"
            expect(page.download_or_create_group_button).to_contain_text('✚ Create')
            
            # Check the download immediately checkbox again
            page.download_immediately_checkbox.click()
            expect(page.download_immediately_checkbox).to_be_checked()
            
            # Verify that the group action button shows "Download" again
            expect(page.download_or_create_group_button).to_contain_text('⬇ Download')
        await pw.run(pw_task)


@awith_playwright
async def test_given_create_group_form_visible_when_reload_page_then_is_still_on_a_nia_page(pw: Playwright) -> None:
    """
    This test verifies that the act of showing the create group form does not
    automatically download the current URL. Older group prediction algorithms
    could sometimes do that. Then reloading the page would show the downloaded
    page rather than an NIA page, a confusing experience for a user.
    """
    async with _not_in_archive_page_visible_temporarily() as (comic1_url_in_archive, *_):
        def pw_task(raw_page: RawPage, *args, **kwargs) -> None:
            # Navigate to comic #1, which should be a "Not in Archive" page
            page = NotInArchivePage.open(raw_page, url_in_archive=comic1_url_in_archive)
            
            # Show the create group form
            page.create_group_checkbox.click()
            expect(page.create_group_checkbox).to_be_checked()
            expect(page.create_group_form).to_be_visible()
            
            # Reload the page
            raw_page.reload()
            
            # Verify we're still on a "Not in Archive" page
            page_after_reload = NotInArchivePage.wait_for(raw_page)
            
            # The form should be hidden again after reload (checkbox unchecked)
            expect(page_after_reload.create_group_checkbox).not_to_be_checked()
            expect(page_after_reload.create_group_form).not_to_be_visible()
            
            # The original download button should still be present
            expect(page_after_reload.download_url_button).to_be_visible()
            expect(page_after_reload.download_url_button).to_contain_text('⬇ Download')
        await pw.run(pw_task)


@awith_playwright
async def test_given_create_group_form_visible_when_cancel_button_pressed_then_hides_create_group_form(pw: Playwright) -> None:
    async with _not_in_archive_page_visible_temporarily() as (comic1_url_in_archive, *_):
        def pw_task(raw_page: RawPage, *args, **kwargs) -> None:
            # Navigate to comic #1, which should be a "Not in Archive" page
            page = NotInArchivePage.open(raw_page, url_in_archive=comic1_url_in_archive)
            
            # Show the create group form
            page.create_group_checkbox.click()
            expect(page.create_group_checkbox).to_be_checked()
            expect(page.create_group_form).to_be_visible()
            expect(page.cancel_group_button).to_be_visible()
            
            # Click the cancel button
            page.cancel_group_button.click()
            
            # Verify the checkbox is unchecked and form is hidden
            expect(page.create_group_checkbox).not_to_be_checked()
            expect(page.create_group_form).not_to_be_visible()
            
            # Verify the original download button is still present and functional
            expect(page.download_url_button).to_be_visible()
            expect(page.download_url_button).to_contain_text('⬇ Download')
        await pw.run(pw_task)


@awith_playwright
async def test_given_create_group_form_visible_when_any_download_button_clicked_then_disables_form_and_creates_group_and_starts_downloading_group_and_displays_success_message_and_downloads_url_and_reloads_page(pw: Playwright) -> None:
    # Test Case 1: Download button above the create group form is clicked
    async with _not_in_archive_page_visible_temporarily() as (comic1_url_in_archive, home_url_in_archive, sp, project, *_):
        def pw_task(raw_page: RawPage, *args, **kwargs) -> None:
            page = _navigate_from_home_to_comic_1_nia_page(
                raw_page, home_url_in_archive, comic1_url_in_archive)
            
            # Show the create group form
            page.create_group_checkbox.click()
            expect(page.create_group_checkbox).to_be_checked()
            expect(page.create_group_form).to_be_visible()
            
            # Keep the download immediately checkbox checked (default state)
            expect(page.download_immediately_checkbox).to_be_checked()
            expect(page.download_or_create_group_button).to_contain_text('⬇ Download')
            
            # Verify form is initially enabled
            page.create_group_form_enabled.expect()
            page.create_group_form_collapsed.expect_not()
            
            # Ensure progress bar is initially hidden
            expect(page.progress_bar).not_to_be_visible()
            
            # Click the download URL button (above the form)
            expect(page.download_url_button).to_be_enabled()
            expect(page.download_url_button).to_contain_text('⬇ Download')
            with reloads_paused(raw_page):
                page.download_url_button.click()
                
                # Verify download button gets disabled and progress bar appears
                expect(page.download_url_button).to_be_disabled()
                expect(page.download_url_button).to_contain_text('⬇ Downloading...')
                page.progress_bar.wait_for(state='visible')
            
            # Wait for the page to reload after download completes.
            # The group should be created automatically and the page should reload to the comic.
            expect(raw_page).to_have_title('xkcd: Barrel - Part 1')
        await pw.run(pw_task)
        
        # Ensure expected entities created
        if True:
            home_url = sp.get_request_url('https://xkcd.com/')
            comic1_url = sp.get_request_url('https://xkcd.com/1/')
            comic_url_pattern = sp.get_request_url('https://xkcd.com/#/')
            
            assert project.get_root_resource(url=home_url) is not None
            assert project.get_root_resource(url=comic1_url) is None, (
                'Should not have created RootResource for comic 1 '
                'because created ResourceGroup covers it'
            )
            assert project.get_resource_group(url_pattern=comic_url_pattern) is not None

    # Test Case 2: Download button at the bottom of the create group form
    async with _not_in_archive_page_visible_temporarily() as (comic1_url_in_archive, home_url_in_archive, sp, project, *_):
        def pw_task(raw_page: RawPage, *args, **kwargs) -> None:
            page = _navigate_from_home_to_comic_1_nia_page(
                raw_page, home_url_in_archive, comic1_url_in_archive)
            
            # Show the create group form again
            page.create_group_checkbox.click()
            expect(page.create_group_checkbox).to_be_checked()
            expect(page.create_group_form).to_be_visible()
            
            # Keep the download immediately checkbox checked (default state)
            expect(page.download_immediately_checkbox).to_be_checked()
            expect(page.download_or_create_group_button).to_contain_text('⬇ Download')
            
            # Verify form is initially enabled
            page.create_group_form_enabled.expect()
            page.create_group_form_collapsed.expect_not()
            
            # Ensure progress bar is initially hidden
            expect(page.progress_bar).not_to_be_visible()
            
            # Click the download button at the bottom of the create group form
            with reloads_paused(raw_page):
                page.download_or_create_group_button.click()
                
                # Verify form gets disabled immediately and progress bar appears
                expect(page.download_or_create_group_button).to_be_disabled()
                page.progress_bar.wait_for(state='visible')
            
            # Wait for the page to reload after download completes.
            # The group should be created automatically and the page should reload to the comic.
            expect(raw_page).to_have_title('xkcd: Barrel - Part 1')
        await pw.run(pw_task)
        
        # Ensure expected entities created
        if True:
            home_url = sp.get_request_url('https://xkcd.com/')
            comic1_url = sp.get_request_url('https://xkcd.com/1/')
            comic_url_pattern = sp.get_request_url('https://xkcd.com/#/')
            
            assert project.get_root_resource(url=home_url) is not None
            assert project.get_root_resource(url=comic1_url) is None, (
                'Should not have created RootResource for comic 1 '
                'because created ResourceGroup covers it'
            )
            assert project.get_resource_group(url_pattern=comic_url_pattern) is not None


@skip('covered by: test_given_create_group_form_visible_and_group_previously_created_when_download_button_clicked_then_downloads_url_and_reloads_page')
async def test_given_create_group_form_visible_when_create_button_clicked_then_disables_form_and_creates_group_and_displays_success_message_and_collapses_form_with_animation(pw: Playwright) -> None:
    pass


@awith_playwright
async def test_given_create_group_form_visible_and_group_previously_created_when_download_button_clicked_then_downloads_url_and_reloads_page(pw: Playwright) -> None:
    async with _not_in_archive_page_visible_temporarily() as (comic1_url_in_archive, home_url_in_archive, sp, project, *_):
        def pw_task(raw_page: RawPage, *args, **kwargs) -> None:
            page = _navigate_from_home_to_comic_1_nia_page(
                raw_page, home_url_in_archive, comic1_url_in_archive)
            
            # Show the create group form
            page.create_group_checkbox.click()
            expect(page.create_group_checkbox).to_be_checked()
            expect(page.create_group_form).to_be_visible()
            
            # Uncheck the download immediately checkbox to get "Create" button
            page.download_immediately_checkbox.click()
            expect(page.download_immediately_checkbox).not_to_be_checked()
            expect(page.download_or_create_group_button).to_contain_text('✚ Create')
            
            # Verify form is initially enabled
            page.create_group_form_enabled.expect()
            page.create_group_form_collapsed.expect_not()
            
            # Click the create button
            page.download_or_create_group_button.click()
            
            # Verify form gets disabled immediately
            expect(page.download_or_create_group_button).to_be_disabled()
            
            # Wait for the creation to complete and success message to appear
            expect(page.action_message).to_be_visible()
            expect(page.action_message).to_contain_text('Group created successfully')
            expect(page.action_message).to_contain_class('success')
            
            # Verify form becomes collapsed with animation
            page.create_group_form_collapsed.expect()
            
            # Verify form remains disabled after creation
            page.create_group_form_enabled.expect_not()
            
            # Ensure progress bar is initially hidden
            expect(page.progress_bar).not_to_be_visible()
            
            # Click the download URL button
            expect(page.download_url_button).to_be_enabled()
            expect(page.download_url_button).to_contain_text('⬇ Download')
            with reloads_paused(raw_page):
                page.download_url_button.click()
                
                # Verify download button gets disabled and progress bar appears
                expect(page.download_url_button).to_be_disabled()
                expect(page.download_url_button).to_contain_text('⬇ Downloading...')
                page.progress_bar.wait_for(state='visible')
            
            # Wait for the page to reload after download completes.
            # Ensure refreshed page is the actual comic page.
            expect(raw_page).to_have_title('xkcd: Barrel - Part 1')
        await pw.run(pw_task)
        
        # Ensure expected entities created
        if True:
            home_url = sp.get_request_url('https://xkcd.com/')
            comic1_url = sp.get_request_url('https://xkcd.com/1/')
            comic_url_pattern = sp.get_request_url('https://xkcd.com/#/')
            
            assert project.get_root_resource(url=home_url) is not None
            assert project.get_root_resource(url=comic1_url) is None, (
                'Should not have created RootResource for comic 1 '
                'because created ResourceGroup covers it'
            )
            assert project.get_resource_group(url_pattern=comic_url_pattern) is not None


@awith_playwright
async def test_given_create_group_form_visible_when_download_or_create_button_clicked_and_create_group_fails_then_displays_failure_message_and_enables_form(pw: Playwright) -> None:
    async with _not_in_archive_page_visible_temporarily() as (comic1_url_in_archive, home_url_in_archive, *_):
        def pw_task(raw_page: RawPage, *args, **kwargs) -> None:
            page = _navigate_from_home_to_comic_1_nia_page(
                raw_page, home_url_in_archive, comic1_url_in_archive)
            
            with network_down_after_delay(page):
                # Show the create group form
                page.create_group_checkbox.click()
                expect(page.create_group_checkbox).to_be_checked()
                expect(page.create_group_form).to_be_visible()
                
                # Uncheck the download immediately checkbox to get "Create" button
                page.download_immediately_checkbox.click()
                expect(page.download_immediately_checkbox).not_to_be_checked()
                expect(page.download_or_create_group_button).to_contain_text('✚ Create')
                
                # Verify form is initially enabled
                page.create_group_form_enabled.expect()
                page.create_group_form_collapsed.expect_not()
                
                # Click the create button (this will fail due to network being down)
                page.download_or_create_group_button.click()
                
                # Verify form gets disabled immediately
                expect(page.download_or_create_group_button).to_be_disabled()
                expect(page.download_or_create_group_button).to_contain_text('Creating...')
                
                # Wait for the creation to fail and error message to appear
                expect(page.action_message).to_be_visible()
                expect(page.action_message).to_contain_text('Failed to create group')
                expect(page.action_message).to_contain_class('error')
                
                # Verify form becomes re-enabled after failure
                expect(page.download_or_create_group_button).to_be_enabled()
                expect(page.download_or_create_group_button).to_contain_text('✚ Create')
                page.create_group_form_enabled.expect()
                
                # Verify form is not collapsed after failure
                page.create_group_form_collapsed.expect_not()
        await pw.run(pw_task)


@awith_playwright
async def test_given_create_group_form_visible_when_type_in_url_pattern_field_then_preview_members_update_live(pw: Playwright) -> None:
    async with _not_in_archive_page_visible_temporarily() as (comic1_url_in_archive, home_url_in_archive, sp, *_):
        # Extract values before defining the closure
        # to avoid capturing the unserializable ProjectServer object
        url_pattern_1 = sp.get_request_url('https://xkcd.com/#/')
        url_pattern_2 = sp.get_request_url('https://xkcd.com/1*/')
        
        def pw_task(raw_page: RawPage, *args, **kwargs) -> None:
            page = _navigate_from_home_to_comic_1_nia_page(
                raw_page, home_url_in_archive, comic1_url_in_archive)
            
            # Show the create group form
            page.create_group_checkbox.click()
            expect(page.create_group_checkbox).to_be_checked()
            expect(page.create_group_form).to_be_visible()
            
            # Wait for initial preview to load
            page.wait_for_initial_preview_urls()
            expect(page.preview_urls_container).to_contain_text('xkcd.com')
            
            # Enter a URL pattern
            page.url_pattern_field.clear()
            page.url_pattern_field.type(url_pattern_1)
            page.wait_for_preview_urls_after_url_pattern_changed()
            expect(page.preview_urls_container).to_contain_text('xkcd.com')
            old_preview_urls = page.preview_urls_container.text_content() or ''  # capture
            
            # Enter a more-specific URL pattern
            page.url_pattern_field.clear()
            page.url_pattern_field.type(url_pattern_2)
            expect(page.preview_urls_container).not_to_contain_text(old_preview_urls)
            expect(page.preview_urls_container).to_contain_text('xkcd.com')
        await pw.run(pw_task)


@awith_playwright
async def test_given_create_group_form_visible_when_type_in_url_pattern_field_and_network_down_then_preview_members_show_error_message(pw: Playwright) -> None:
    async with _not_in_archive_page_visible_temporarily() as (comic1_url_in_archive, home_url_in_archive, sp, *_):
        # Extract values before defining the closure
        # to avoid capturing the unserializable ProjectServer object
        url_pattern = sp.get_request_url('https://xkcd.com/1*/')
        
        def pw_task(raw_page: RawPage, *args, **kwargs) -> None:
            page = _navigate_from_home_to_comic_1_nia_page(
                raw_page, home_url_in_archive, comic1_url_in_archive)
            
            # Show the create group form
            page.create_group_checkbox.click()
            expect(page.create_group_checkbox).to_be_checked()
            expect(page.create_group_form).to_be_visible()
            
            # Wait for initial preview to load
            page.wait_for_initial_preview_urls()
            expect(page.preview_urls_container).to_contain_text('xkcd.com')
            
            # Now simulate network going down and try to update URL pattern
            with network_down_after_delay(page):
                page.url_pattern_field.clear()
                page.url_pattern_field.type(url_pattern)
                
                # Wait a moment for the network request to fail.
                # The preview should show an error message.
                expect(page.preview_urls_container).to_contain_text('Error')
        await pw.run(pw_task)


@awith_playwright
async def test_given_create_group_form_visible_and_text_field_focused_when_press_enter_then_presses_primary_button(pw: Playwright) -> None:
    # Case 1: URL Pattern text field
    # Case 2: Name text field
    for field_func in [lambda page: page.url_pattern_field, lambda page: page.name_field]:
        async with _not_in_archive_page_visible_temporarily() as (comic1_url_in_archive, home_url_in_archive, sp, *_):
            def pw_task(raw_page: RawPage, *args, **kwargs) -> None:
                page = _navigate_from_home_to_comic_1_nia_page(
                    raw_page, home_url_in_archive, comic1_url_in_archive)
                
                # Show the create group form
                page.create_group_checkbox.click()
                expect(page.create_group_checkbox).to_be_checked()
                expect(page.create_group_form).to_be_visible()
                
                # Wait for initial preview to load
                page.wait_for_initial_preview_urls()
                
                # Focus the URL pattern field and press Enter
                text_field = field_func(page)  # cache
                text_field.click()  # Focus the field
                expect(text_field).to_be_focused()
                
                # Verify the primary button is initially "Download" (download immediately is checked by default)
                expect(page.download_or_create_group_button).to_contain_text('⬇ Download')
                expect(page.download_or_create_group_button).to_be_enabled()
                
                # Press Enter and verify it activates the primary button (Download)
                with reloads_paused(raw_page):
                    text_field.press('Enter')
                    
                    # The button should get disabled as download starts
                    expect(page.download_or_create_group_button).to_be_disabled()
                
                # Wait for the page to reload (indicating successful download)
                expect(raw_page).to_have_title('xkcd: Barrel - Part 1')
            await pw.run(pw_task)


@awith_playwright
async def test_given_create_group_form_visible_and_text_field_focused_when_press_escape_then_presses_cancel_button(pw: Playwright) -> None:
    # Case 1: URL Pattern text field
    # Case 2: Name text field
    for field_func in [lambda page: page.url_pattern_field, lambda page: page.name_field]:
        async with _not_in_archive_page_visible_temporarily() as (comic1_url_in_archive, home_url_in_archive, sp, *_):
            def pw_task(raw_page: RawPage, *args, **kwargs) -> None:
                page = _navigate_from_home_to_comic_1_nia_page(
                    raw_page, home_url_in_archive, comic1_url_in_archive)
                
                # Show the create group form
                page.create_group_checkbox.click()
                expect(page.create_group_checkbox).to_be_checked()
                expect(page.create_group_form).to_be_visible()
                
                # Wait for initial preview to load
                page.wait_for_initial_preview_urls()
                
                # Focus the URL pattern field and press Escape
                text_field = field_func(page)  # cache
                text_field.click()  # Focus the field
                expect(text_field).to_be_focused()
                
                # Verify the form is initially visible
                expect(page.create_group_form).to_be_visible()
                expect(page.create_group_checkbox).to_be_checked()
                
                # Press Escape and verify it activates the cancel button
                text_field.press('Escape')
                
                # Verify the checkbox is unchecked and form is hidden (same effect as clicking cancel)
                expect(page.create_group_checkbox).not_to_be_checked()
                expect(page.create_group_form).not_to_be_visible()
                
                # Verify the original download button is still present and functional
                expect(page.download_url_button).to_be_visible()
                expect(page.download_url_button).to_contain_text('⬇ Download')
            await pw.run(pw_task)


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
# Test: Send HTTP Revision: Header Inclusion & Exclusion (_HEADER_ALLOWLIST, _HEADER_DENYLIST)

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
# Test: Send HTTP Revision: Footer Banner

# Currently pages containing <frameset> are parsed as a BasicDocument
# which is too dumb to know which BasicLinks it contains are embedded.
# 
# TODO: Treat <frame> links (inside a <frameset>) as embedded
_MUST_DOWNLOAD_FRAMES_IN_FRAMESET_EXPLICITLY = True

# Maximum overhead that the footer banner is allowed to add to regular pages
# before triggering a test failure.
# 
# As of 2025-09-09:
# - Overhead is 2,576 bytes, before variable name substitution
# - Overhead is 2,126 bytes, after variable name substitution
_MAX_BANNER_OVERHEAD_BYTES = 3_000  # 3KB

# Whether to print the footer banner overhead in bytes, when running the test:
# $ crystal --test test_footer_banner_does_not_add_more_than_X_bytes_of_overhead_to_page
_PRINT_BANNER_OVERHEAD = True


@awith_playwright
async def test_when_serve_regular_page_with_long_content_then_footer_banner_appears_at_bottom_of_page_content(pw: Playwright) -> None:
    # Serve a long page
    server = MockHttpServer({
        '/long-page': dict(
            status_code=200,
            headers=[('Content-Type', 'text/html')],
            content=dedent(
                f"""
                <!DOCTYPE html>
                <html>
                <head>
                    <title>Long Lorem Ipsum Page</title>
                </head>
                <body>
                    <h1>Very Long Page for Footer Banner Testing</h1>
                    <div>
                        {LOREM_IPSUM_LONG * 15}
                    </div>
                </body>
                </html>
                """
            ).strip().encode('utf-8')
        )
    })
    with server:
        long_page_url = server.get_url('/long-page')
        
        async with (await OpenOrCreateDialog.wait_for()).create() as (mw, project):
            # Download the page
            r = Resource(project, long_page_url)
            revision_future = r.download(wait_for_embedded=True)
            await wait_for_future(revision_future)
            
            # Serve the page
            with closing(ProjectServer(project)) as project_server:
                long_page_url_in_archive = project_server.get_request_url(long_page_url)
                
                # Verify banner is present in the served HTML
                served_page = await fetch_archive_url(long_page_url)
                assert served_page.status == 200
                assert 'id="cr-footer-banner"' in served_page.content
                assert _FOOTER_BANNER_MESSAGE in served_page.content
                
                # Verify banner is visible only after scrolling to bottom of page
                def pw_task(raw_page: RawPage, *args, **kwargs) -> None:
                    raw_page.goto(long_page_url_in_archive)
                    
                    # Ensure the banner exists
                    footer_banner = raw_page.locator('#cr-footer-banner')
                    expect(footer_banner).to_be_visible()
                    expect(footer_banner).to_contain_text(
                        _FOOTER_BANNER_MESSAGE)
                    
                    # Ensure the banner is not initially visible,
                    # before scrolling the page content
                    initial_banner_box = footer_banner.bounding_box()
                    viewport_size = raw_page.viewport_size
                    assert initial_banner_box is not None
                    assert viewport_size is not None
                    assert initial_banner_box['y'] > viewport_size['height']
                    
                    # Scroll to the bottom of the page
                    raw_page.evaluate('window.scrollTo(0, document.body.scrollHeight)')
                    
                    # Ensure the banner is visible,
                    # after scrolling the page content
                    final_banner_box = footer_banner.bounding_box()
                    assert final_banner_box is not None
                    assert final_banner_box['y'] < viewport_size['height']
                await pw.run(pw_task)


@awith_playwright
async def test_when_serve_regular_page_with_short_content_then_footer_banner_appears_pinned_to_bottom_of_browser_viewport(pw: Playwright) -> None:
    # Serve a short page that will have a banner
    mock_server = MockHttpServer({
        '/short-page': dict(
            status_code=200,
            headers=[('Content-Type', 'text/html')],
            content=dedent(
                f"""
                <!DOCTYPE html>
                <html>
                <head>
                    <title>Short Page</title>
                </head>
                <body>
                    <h1>Short Page Content</h1>
                    <div>
                        {LOREM_IPSUM_SHORT}
                    </div>
                </body>
                </html>
                """
            ).strip().encode('utf-8')
        )
    })
    with mock_server:
        short_page_url = mock_server.get_url('/short-page')
        
        async with (await OpenOrCreateDialog.wait_for()).create() as (mw, project):
            # Download the page
            r = Resource(project, short_page_url)
            revision_future = r.download(wait_for_embedded=True)
            await wait_for_future(revision_future)
            
            # Serve the page
            with closing(ProjectServer(project)) as project_server:
                short_page_url_in_archive = project_server.get_request_url(short_page_url)
                
                # Verify banner is present in the served HTML
                served_page = await fetch_archive_url(short_page_url)
                assert served_page.status == 200
                assert 'id="cr-footer-banner"' in served_page.content
                assert _FOOTER_BANNER_MESSAGE in served_page.content
                
                # Verify banner appears pinned to bottom of viewport and stacked on top
                def pw_task(raw_page: RawPage, *args, **kwargs) -> None:
                    raw_page.goto(short_page_url_in_archive)
                    
                    # Ensure the banner exists and is visible
                    footer_banner = raw_page.locator('#cr-footer-banner')
                    expect(footer_banner).to_be_visible()
                    expect(footer_banner).to_contain_text(_FOOTER_BANNER_MESSAGE)
                    
                    # Verify banner has non-zero dimensions
                    banner_box = footer_banner.bounding_box()
                    assert banner_box is not None
                    assert banner_box['width'] > 0, \
                        f"Banner width should be > 0, got {banner_box['width']}"
                    assert banner_box['height'] > 0, \
                        f"Banner height should be > 0, got {banner_box['height']}"
                    
                    # Verify banner Y coordinate is > 0 (visible in viewport)
                    assert banner_box['y'] > 0, \
                        f"Banner Y coordinate should be > 0, got {banner_box['y']}"
                    
                    # Verify banner is positioned at or very close to the bottom of the viewport
                    viewport_size = raw_page.viewport_size
                    assert viewport_size is not None
                    viewport_bottom = viewport_size['height']
                    banner_bottom = banner_box['y'] + banner_box['height']
                    assert abs(banner_bottom - viewport_bottom) <= 10, \
                        f"Banner should be at bottom of viewport. ' \
                        f'Banner bottom: {banner_bottom}, Viewport bottom: {viewport_bottom}"
                    
                    # Verify banner is positioned fixed or absolute to stay at bottom
                    banner_styles = footer_banner.evaluate('el => window.getComputedStyle(el)')
                    position = banner_styles['position']
                    assert position in ['fixed', 'absolute'], \
                        f"Banner should be positioned fixed or absolute, got {position}"
                    
                    # Verify banner is stacked on top (has high z-index)
                    z_index = banner_styles.get('zIndex', 'auto')
                    assert z_index.isdigit() and int(z_index) >= 1000, \
                        f"Banner should have high z-index for stacking, got {z_index}"
                await pw.run(pw_task)


@awith_playwright
async def test_when_serve_iframe_then_footer_banner_does_not_appear_at_bottom_of_iframe(pw: Playwright) -> None:
    # Serve a page with an iframe structure
    server = MockHttpServer({
        '/main-page': dict(
            status_code=200,
            headers=[('Content-Type', 'text/html')],
            content=dedent(
                f"""
                <!DOCTYPE html>
                <html>
                <head>
                    <title>Main Page with Iframe</title>
                </head>
                <body>
                    <h1>Main Page Content</h1>
                    <p>
                        {LOREM_IPSUM_SHORT}
                    </p]>
                    
                    <iframe id="test-iframe" src="/iframe-content" width="800" height="400" style="border: 2px solid red;"></iframe>
                    
                    <p>
                        {LOREM_IPSUM_SHORT}
                    </p>
                </body>
                </html>
                """
            ).strip().encode('utf-8')
        ),
        '/iframe-content': dict(
            status_code=200,
            headers=[('Content-Type', 'text/html')],
            content=dedent(
                f"""
                <!DOCTYPE html>
                <html>
                <head>
                    <title>Iframe Content</title>
                </head>
                <body style="background-color: lightblue; margin: 10px;">
                    <h2>Content Inside Iframe</h2>
                    <p>
                        {LOREM_IPSUM_SHORT}
                    </p>
                </body>
                </html>
                """
            ).strip().encode('utf-8')
        )
    })
    with server:
        main_page_url = server.get_url('/main-page')
        
        async with (await OpenOrCreateDialog.wait_for()).create() as (mw, project):
            # Download both the main page and iframe content
            main_resource = Resource(project, main_page_url)
            main_revision_future = main_resource.download(wait_for_embedded=True)
            await wait_for_future(main_revision_future)
            
            # Serve the pages
            with closing(ProjectServer(project)) as project_server:
                main_page_url_in_archive = project_server.get_request_url(main_page_url)
                
                def pw_task(raw_page: RawPage, *args, **kwargs) -> None:
                    raw_page.goto(main_page_url_in_archive)
                    
                    # Ensure banner exists at bottom of main page
                    main_banner = raw_page.locator('#cr-footer-banner')
                    expect(main_banner).to_be_visible()
                    expect(main_banner).to_contain_text(_FOOTER_BANNER_MESSAGE)
                    
                    # Wait for iframe to load
                    iframe = raw_page.locator('#test-iframe')
                    expect(iframe).to_be_visible()
                    
                    # Ensure no banner exists at bottom of iframe
                    iframe_content = iframe.content_frame
                    iframe_banner = iframe_content.locator('#cr-footer-banner')
                    expect(iframe_banner).not_to_be_visible()
                await pw.run(pw_task)


@awith_subtests
@awith_playwright
async def test_when_serve_frameset_page_then_footer_banner_appears_at_bottom_of_largest_frame_at_bottom_of_browser_viewport(
        pw: Playwright,
        subtests: SubtestsContext
        ) -> None:
    # Case 1:
    # - Single frame on bottom row
    #     - FRAMESET with ROWS="120,*" where the bottom frame gets the banner
    # - Based on: http://www.rakhal.com/FFIndex/lstmain.html
    with subtests.test(case=1):
        server = MockHttpServer({
            '/lstmain.html': dict(
                status_code=200,
                headers=[('Content-Type', 'text/html')],
                content=dedent(
                    """
                    <HTML>
                    <HEAD><TITLE>The Penultimate Ranma Fanfic Index</TITLE></HEAD>
                    <FRAMESET ROWS="120,*" FRAMEBORDER="1" FRAMESPACING="0" BORDER="0"> 
                        <FRAMESET COLS="75%,*" FRAMEBORDER="1" FRAMESPACING="0" BORDER="0">
                            <FRAME NAME="lefttop" SRC="/rindex.htm"> 
                            <FRAME NAME="righttop" SRC="/rankey.html">
                        </FRAMESET>
                        <FRAME NAME="body" SRC="/ranlgnd.shtml"> 
                    </FRAMESET> 
                    </HTML>
                    """
                ).strip().encode('utf-8')
            ),
            '/rindex.htm': dict(
                status_code=200,
                headers=[('Content-Type', 'text/html')],
                content=dedent(
                    """
                    <!DOCTYPE html>
                    <html>
                    <head>
                        <title>Left Top Frame</title>
                    </head>
                    <body style="background-color: lightgreen; margin: 10px;">
                        <h3>Left Top Frame</h3>
                    </body>
                    </html>
                    """
                ).strip().encode('utf-8')
            ),
            '/rankey.html': dict(
                status_code=200,
                headers=[('Content-Type', 'text/html')],
                content=dedent(
                    """
                    <!DOCTYPE html>
                    <html>
                    <head>
                        <title>Right Top Frame</title>
                    </head>
                    <body style="background-color: lightcoral; margin: 10px;">
                        <h3>Right Top Frame</h3>
                    </body>
                    </html>
                    """
                ).strip().encode('utf-8')
            ),
            '/ranlgnd.shtml': dict(
                status_code=200,
                headers=[('Content-Type', 'text/html')],
                content=dedent(
                    f"""
                    <!DOCTYPE html>
                    <html>
                    <head>
                        <title>Main Body Frame</title>
                    </head>
                    <body style="background-color: white; margin: 10px;">
                        <h2>Main Content Frame</h2>
                        <div>
                            {LOREM_IPSUM_SHORT}
                        </div>
                    </body>
                    </html>
                    """
                ).strip().encode('utf-8')
            )
        })
        with server:
            frameset_page_url = server.get_url('/lstmain.html')
            frame1_url = server.get_url('/rindex.htm')
            frame2_url = server.get_url('/rankey.html')
            frame3_url = server.get_url('/ranlgnd.shtml')
            
            async with (await OpenOrCreateDialog.wait_for()).create() as (mw, project):
                # Download the frameset page and all frame content
                await wait_for_future(
                    Resource(project, frameset_page_url).download(wait_for_embedded=True)
                )
                if _MUST_DOWNLOAD_FRAMES_IN_FRAMESET_EXPLICITLY:
                    for frame_url in [frame1_url, frame2_url, frame3_url]:
                        await wait_for_future(
                            Resource(project, frame_url).download(wait_for_embedded=True)
                        )
                
                # Serve the pages
                with closing(ProjectServer(project)) as project_server:
                    frameset_page_url_in_archive = project_server.get_request_url(frameset_page_url)
                    
                    # Verify frameset page HTML has no footer banner
                    served_frameset_page = await fetch_archive_url(frameset_page_url)
                    assert served_frameset_page.status == 200
                    assert 'id="cr-footer-banner"' not in served_frameset_page.content
                    
                    # Verify footer banner appears only in appropriate frames
                    def pw_task(raw_page: RawPage, *args, **kwargs) -> None:
                        raw_page.goto(frameset_page_url_in_archive)
                        
                        # Wait for frames to load
                        raw_page.wait_for_load_state('networkidle')
                        
                        # Left top frame should NOT have footer banner
                        lefttop_frame = raw_page.frame('lefttop')
                        assert lefttop_frame is not None
                        lefttop_banner = lefttop_frame.locator('#cr-footer-banner')
                        expect(lefttop_banner).not_to_be_visible()
                        
                        # Right top frame should NOT have footer banner
                        righttop_frame = raw_page.frame('righttop')
                        assert righttop_frame is not None
                        righttop_banner = righttop_frame.locator('#cr-footer-banner')
                        expect(righttop_banner).not_to_be_visible()
                        
                        # Body frame (at bottom) SHOULD have footer banner
                        body_frame = raw_page.frame('body')
                        assert body_frame is not None
                        body_banner = body_frame.locator('#cr-footer-banner')
                        expect(body_banner).to_be_visible()
                        expect(body_banner).to_contain_text(_FOOTER_BANNER_MESSAGE)
                    await pw.run(pw_task)
    
    # Case 2:
    # - Multiple frames on bottom row. Top-level column split.
    #     - FRAMESET with COLS="19%,81%" where the wider right column gets the banner
    # - Based on: http://www.tmffa.com/old/frame.html
    with subtests.test(case=2):
        server = MockHttpServer({
            '/frame.html': dict(
                status_code=200,
                headers=[('Content-Type', 'text/html')],
                content=dedent(
                    """
                    <HTML>
                    <HEAD><TITLE>The Tenchi Muyo Fan Fiction Archive</TITLE></HEAD>
                    <FRAMESET COLS="19%,81%">
                        <FRAMESET ROWS="19%,81%">
                            <FRAME SRC="/midi.html" NAME="midi">
                            <FRAME SRC="/menu.html" NAME="menu">
                        </FRAMESET>
                        <FRAME SRC="/fanfic.html" NAME="Screen">
                    </FRAMESET>
                    </HTML>
                    """
                ).strip().encode('utf-8')
            ),
            '/midi.html': dict(
                status_code=200,
                headers=[('Content-Type', 'text/html')],
                content=dedent(
                    """
                    <!DOCTYPE html>
                    <html>
                    <head>
                        <title>Midi Frame</title>
                    </head>
                    <body style="background-color: lightgray; margin: 10px;">
                        <h4>Midi Frame</h4>
                    </body>
                    </html>
                    """
                ).strip().encode('utf-8')
            ),
            '/menu.html': dict(
                status_code=200,
                headers=[('Content-Type', 'text/html')],
                content=dedent(
                    """
                    <!DOCTYPE html>
                    <html>
                    <head>
                        <title>Menu Frame</title>
                    </head>
                    <body style="background-color: lightblue; margin: 10px;">
                        <h4>Menu Frame</h4>
                    </body>
                    </html>
                    """
                ).strip().encode('utf-8')
            ),
            '/fanfic.html': dict(
                status_code=200,
                headers=[('Content-Type', 'text/html')],
                content=dedent(
                    f"""
                    <!DOCTYPE html>
                    <html>
                    <head>
                        <title>Screen Frame</title>
                    </head>
                    <body style="background-color: white; margin: 10px;">
                        <h2>Screen Frame Content</h2>
                        <div>
                            {LOREM_IPSUM_SHORT}
                        </div>
                    </body>
                    </html>
                    """
                ).strip().encode('utf-8')
            )
        })
        with server:
            frameset_page_url = server.get_url('/frame.html')
            midi_url = server.get_url('/midi.html')
            menu_url = server.get_url('/menu.html')
            fanfic_url = server.get_url('/fanfic.html')
            
            async with (await OpenOrCreateDialog.wait_for()).create() as (mw, project):
                # Download the frameset page and all frame content
                await wait_for_future(
                    Resource(project, frameset_page_url).download(wait_for_embedded=True)
                )
                if _MUST_DOWNLOAD_FRAMES_IN_FRAMESET_EXPLICITLY:
                    for frame_url in [midi_url, menu_url, fanfic_url]:
                        await wait_for_future(
                            Resource(project, frame_url).download(wait_for_embedded=True)
                        )
                
                # Serve the pages
                with closing(ProjectServer(project)) as project_server:
                    frameset_page_url_in_archive = project_server.get_request_url(frameset_page_url)
                    
                    # Verify frameset page HTML has no footer banner
                    served_frameset_page = await fetch_archive_url(frameset_page_url)
                    assert served_frameset_page.status == 200
                    assert 'id="cr-footer-banner"' not in served_frameset_page.content
                    
                    # Verify footer banner appears only in appropriate frames
                    def pw_task(raw_page: RawPage, *args, **kwargs) -> None:
                        raw_page.goto(frameset_page_url_in_archive)
                        
                        # Wait for frames to load
                        raw_page.wait_for_load_state('networkidle')
                        
                        # Midi frame should NOT have footer banner
                        midi_frame = raw_page.frame('midi')
                        assert midi_frame is not None
                        midi_banner = midi_frame.locator('#cr-footer-banner')
                        expect(midi_banner).not_to_be_visible()
                        
                        # Menu frame should NOT have footer banner
                        menu_frame = raw_page.frame('menu')
                        assert menu_frame is not None
                        menu_banner = menu_frame.locator('#cr-footer-banner')
                        expect(menu_banner).not_to_be_visible()
                        
                        # Screen frame (largest at bottom) SHOULD have footer banner
                        screen_frame = raw_page.frame('Screen')
                        assert screen_frame is not None
                        screen_banner = screen_frame.locator('#cr-footer-banner')
                        expect(screen_banner).to_be_visible()
                        expect(screen_banner).to_contain_text(_FOOTER_BANNER_MESSAGE)
                    await pw.run(pw_task)
    
    # Case 3:
    # - Very short single frame on bottom.
    #     - FRAMESET with ROWS="*,20" where the bottom row gets the banner
    #         - However the bottom row is so short that the banner will be hidden
    # - Based on: https://otakuworld.com/index.html?/0home.html
    with subtests.test(case=3):
        server = MockHttpServer({
            '/index.html': dict(
                status_code=200,
                headers=[('Content-Type', 'text/html')],
                content=dedent(
                    """
                    <!DOCTYPE html PUBLIC "-//W3C//DTD HTML 4.01 Frameset//EN" "http://www.w3.org/TR/html4/frameset.dtd">
                    <html>
                    <head><title>Otaku World! Anime and Manga</title></head>
                    <frameset rows="*,20" border="0">
                        <frame src="/0home.html" frameborder="0" marginheight="2" marginwidth="0" name="main" scrolling="Auto">
                        <frame src="/map2.htm" frameborder="0" marginheight="0" marginwidth="0" name="map" scrolling="no" noresize>
                    </frameset>
                    </html>
                    """
                ).strip().encode('utf-8')
            ),
            '/0home.html': dict(
                status_code=200,
                headers=[('Content-Type', 'text/html')],
                content=dedent(
                    f"""
                    <!DOCTYPE html>
                    <html>
                    <head>
                        <title>Main Content</title>
                    </head>
                    <body style="background-color: white; margin: 10px;">
                        <h1>Otaku World Main Content</h1>
                        <div>
                            {LOREM_IPSUM_SHORT}
                        </div>
                    </body>
                    </html>
                    """
                ).strip().encode('utf-8')
            ),
            '/map2.htm': dict(
                status_code=200,
                headers=[('Content-Type', 'text/html')],
                content=dedent(
                    """
                    <!DOCTYPE html>
                    <html>
                    <head>
                        <title>Map Frame</title>
                    </head>
                    <body style="background-color: lightgray; margin: 0; padding: 0;">
                        <small>Navigation Map</small>
                    </body>
                    </html>
                    """
                ).strip().encode('utf-8')
            )
        })
        with server:
            frameset_page_url = server.get_url('/index.html')
            main_url = server.get_url('/0home.html')
            map_url = server.get_url('/map2.htm')
            
            async with (await OpenOrCreateDialog.wait_for()).create() as (mw, project):
                # Download the frameset page and all frame content
                await wait_for_future(
                    Resource(project, frameset_page_url).download(wait_for_embedded=True)
                )
                if _MUST_DOWNLOAD_FRAMES_IN_FRAMESET_EXPLICITLY:
                    for frame_url in [main_url, map_url]:
                        await wait_for_future(
                            Resource(project, frame_url).download(wait_for_embedded=True)
                        )
                
                # Serve the pages
                with closing(ProjectServer(project)) as project_server:
                    frameset_page_url_in_archive = project_server.get_request_url(frameset_page_url)
                    
                    # Verify frameset page HTML has no footer banner
                    served_frameset_page = await fetch_archive_url(frameset_page_url)
                    assert served_frameset_page.status == 200
                    assert 'id="cr-footer-banner"' not in served_frameset_page.content
                    
                    # Verify footer banner appears only in appropriate frames
                    def pw_task(raw_page: RawPage, *args, **kwargs) -> None:
                        raw_page.goto(frameset_page_url_in_archive)
                        
                        # Wait for frames to load
                        raw_page.wait_for_load_state('networkidle')
                        
                        # Main frame should NOT have footer banner
                        main_frame = raw_page.frame('main')
                        assert main_frame is not None
                        main_banner = main_frame.locator('#cr-footer-banner')
                        expect(main_banner).not_to_be_visible()
                        
                        # Map frame (at bottom but very short) gets the banner but it's hidden due to height
                        map_frame = raw_page.frame('map')
                        assert map_frame is not None
                        map_banner = map_frame.locator('#cr-footer-banner')
                        expect(map_banner).not_to_be_visible()
                    await pw.run(pw_task)
    
    # Case 4:
    # - Frameset nested inside frame
    #     - FRAMESET with ROWS="*,20" where the bottom row gets the banner
    #         - However the bottom row is so short that the banner will be hidden
    #     - Additionally, the top row is itself a FRAMESET with COLS="300,*",
    #       where the wider right column gets the banner
    #         - Strictly-speaking this nested right column is NOT at the
    #           bottom of the browser window's viewport, so arguably no
    #           banner should be shown in this case. However the current
    #           behavior actually looks good for the example site,
    #           so I am keeping the behavior for now.
    #           It may change in the future.
    # - Based on: https://otakuworld.com/index.html?/kiss/dolls/
    with subtests.test(case=4):
        server = MockHttpServer({
            '/index.html': dict(
                status_code=200,
                headers=[('Content-Type', 'text/html')],
                content=dedent(
                    """
                    <!DOCTYPE html PUBLIC "-//W3C//DTD HTML 4.01 Frameset//EN" "http://www.w3.org/TR/html4/frameset.dtd">
                    <html>
                    <head><title>Otaku World! Anime and Manga</title></head>
                    <frameset rows="*,20" border="0">
                        <frame src="/kiss/dolls/" frameborder="0" marginheight="2" marginwidth="0" name="main" scrolling="Auto">
                        <frame src="/map2.htm" frameborder="0" marginheight="0" marginwidth="0" name="map" scrolling="no" noresize>
                    </frameset>
                    </html>
                    """
                ).strip().encode('utf-8')
            ),
            '/kiss/dolls/': dict(
                status_code=200,
                headers=[('Content-Type', 'text/html')],
                content=dedent(
                    """
                    <html>
                    <head><title>The Big KiSS Page - The Dolls</title></head>
                    <frameset cols="300,*" border="0" framespacing="0" frameborder="NO">
                        <frame src="/kiss/dolls/newest.htm" marginheight="1" marginwidth="4" noresize name="lists">
                        <frame src="/kiss/dolls/intro.htm" marginheight="3" marginwidth="3" noresize name="pictures">
                    </frameset>
                    </html>
                    """
                ).strip().encode('utf-8')
            ),
            '/kiss/dolls/newest.htm': dict(
                status_code=200,
                headers=[('Content-Type', 'text/html')],
                content=dedent(
                    """
                    <!DOCTYPE html>
                    <html>
                    <head>
                        <title>Lists Frame</title>
                    </head>
                    <body style="background-color: lightgray; margin: 4px;">
                        <h4>Lists Content</h4>
                        <p>Navigation and lists content</p>
                    </body>
                    </html>
                    """
                ).strip().encode('utf-8')
            ),
            '/kiss/dolls/intro.htm': dict(
                status_code=200,
                headers=[('Content-Type', 'text/html')],
                content=dedent(
                    f"""
                    <!DOCTYPE html>
                    <html>
                    <head>
                        <title>Pictures Frame</title>
                    </head>
                    <body style="background-color: white; margin: 3px;">
                        <h2>Pictures Content</h2>
                        <div>
                            {LOREM_IPSUM_SHORT}
                        </div>
                    </body>
                    </html>
                    """
                ).strip().encode('utf-8')
            ),
            '/map2.htm': dict(
                status_code=200,
                headers=[('Content-Type', 'text/html')],
                content=dedent(
                    """
                    <!DOCTYPE html>
                    <html>
                    <head>
                        <title>Map Frame</title>
                    </head>
                    <body style="background-color: lightgray; margin: 0; padding: 0;">
                        <small>Navigation Map</small>
                    </body>
                    </html>
                    """
                ).strip().encode('utf-8')
            )
        })
        with server:
            frameset_page_url = server.get_url('/index.html')
            nested_frameset_url = server.get_url('/kiss/dolls/')
            lists_url = server.get_url('/kiss/dolls/newest.htm')
            pictures_url = server.get_url('/kiss/dolls/intro.htm')
            map_url = server.get_url('/map2.htm')
            
            async with (await OpenOrCreateDialog.wait_for()).create() as (mw, project):
                # Download the frameset page and all frame content
                await wait_for_future(
                    Resource(project, frameset_page_url).download(wait_for_embedded=True)
                )
                if _MUST_DOWNLOAD_FRAMES_IN_FRAMESET_EXPLICITLY:
                    for frame_url in [nested_frameset_url, lists_url, pictures_url, map_url]:
                        await wait_for_future(
                            Resource(project, frame_url).download(wait_for_embedded=True)
                        )
                
                # Serve the pages
                with closing(ProjectServer(project)) as project_server:
                    frameset_page_url_in_archive = project_server.get_request_url(frameset_page_url)
                    
                    # Verify frameset page HTML has no footer banner
                    served_frameset_page = await fetch_archive_url(frameset_page_url)
                    assert served_frameset_page.status == 200
                    assert 'id="cr-footer-banner"' not in served_frameset_page.content
                    
                    # Verify nested frameset page HTML has no footer banner
                    served_nested_frameset_page = await fetch_archive_url(nested_frameset_url)
                    assert served_nested_frameset_page.status == 200
                    assert 'id="cr-footer-banner"' not in served_nested_frameset_page.content
                    
                    # Verify footer banner appears only in appropriate frames
                    def pw_task(raw_page: RawPage, *args, **kwargs) -> None:
                        raw_page.goto(frameset_page_url_in_archive)
                        
                        # Wait for frames to load
                        raw_page.wait_for_load_state('networkidle')
                        
                        # Top-level map frame (at bottom but very short) gets banner but it's hidden
                        map_frame = raw_page.frame('map')
                        assert map_frame is not None
                        map_banner = map_frame.locator('#cr-footer-banner')
                        expect(map_banner).not_to_be_visible()
                        
                        # Main frame contains nested frameset
                        main_frame = raw_page.frame('main')
                        assert main_frame is not None
                        
                        # Lists frame (left column in nested frameset) should NOT have banner
                        lists_frame = main_frame.frame_locator('frame[name="lists"]').first
                        lists_banner = lists_frame.locator('#cr-footer-banner')
                        expect(lists_banner).not_to_be_visible()
                        
                        # Pictures frame (right column in nested frameset) SHOULD have banner
                        # (even though it's not at the bottom of the browser viewport, 
                        #  the current behavior shows the banner here and it looks good)
                        pictures_frame = main_frame.frame_locator('frame[name="pictures"]').first
                        pictures_banner = pictures_frame.locator('#cr-footer-banner')
                        expect(pictures_banner).to_be_visible()
                        expect(pictures_banner).to_contain_text(_FOOTER_BANNER_MESSAGE)
                    await pw.run(pw_task)


@awith_playwright
async def test_when_serve_page_with_all_floated_content_then_footer_banner_appears_at_bottom_of_page_content(pw: Playwright) -> None:
    # Serve a page with all floated content
    server = MockHttpServer({
        '/floated-page': dict(
            status_code=200,
            headers=[('Content-Type', 'text/html')],
            content=dedent(
                f"""
                <!DOCTYPE html>
                <html lang="en-US">
                <head><title>All About Me! - Project Lafiel</title></head>
                <body>
                    <div id="page-title-wide" style="float: left; width: 100%;">
                        <h1>All About Me!</h1>
                    </div>
                    <div class="clearfix" style="clear: both;"></div>
                    <div id="main-section" style="float: left; width: 100%; clear: both;">
                        <p>{LOREM_IPSUM_SHORT}</p>
                    </div>
                    <div class="clearfix" style="clear: both;"></div>
                    <footer id="canuck-footer" style="float: left; width: 100%;">
                        Seikai no Dansho, Seikai no Monsho, Seikai no Senki. Copyright 1996-2020 Hiroyuki Morioka
                    </footer>
                </body>
                </html>
                """
            ).strip().encode('utf-8')
        )
    })
    with server:
        floated_page_url = server.get_url('/floated-page')
        
        async with (await OpenOrCreateDialog.wait_for()).create() as (mw, project):
            # Download the page
            r = Resource(project, floated_page_url)
            revision_future = r.download(wait_for_embedded=True)
            await wait_for_future(revision_future)
            
            # Serve the page
            with closing(ProjectServer(project)) as project_server:
                floated_page_url_in_archive = project_server.get_request_url(floated_page_url)
                
                # Verify banner is present in the served HTML
                served_page = await fetch_archive_url(floated_page_url)
                assert served_page.status == 200
                assert 'id="cr-footer-banner"' in served_page.content
                assert _FOOTER_BANNER_MESSAGE in served_page.content
                
                # Verify banner appears correctly at bottom of page with floated content
                def pw_task(raw_page: RawPage, *args, **kwargs) -> None:
                    raw_page.goto(floated_page_url_in_archive)
                    
                    # Ensure the banner exists and is visible
                    footer_banner = raw_page.locator('#cr-footer-banner')
                    expect(footer_banner).to_be_visible()
                    expect(footer_banner).to_contain_text(_FOOTER_BANNER_MESSAGE)
                    
                    # Verify banner has non-zero dimensions
                    banner_box = footer_banner.bounding_box()
                    assert banner_box is not None
                    assert banner_box['width'] > 0, f"Banner width should be > 0, got {banner_box['width']}"
                    assert banner_box['height'] > 0, f"Banner height should be > 0, got {banner_box['height']}"
                    
                    # Verify banner has the clear: both style to properly position after floated content
                    banner_styles = footer_banner.evaluate('el => window.getComputedStyle(el)')
                    assert banner_styles['clear'] == 'both', \
                        f"Banner should have clear: both style, got {banner_styles['clear']}"
                    
                    # Verify banner is positioned after all the floated content
                    main_section = raw_page.locator('#main-section')
                    main_box = main_section.bounding_box()
                    assert main_box is not None
                    main_bottom = main_box['y'] + main_box['height']
                    assert banner_box['y'] >= main_bottom, (
                        f"Banner should be below main content. "
                        f"Banner Y: {banner_box['y']}, Main bottom: {main_bottom}"
                    )
                await pw.run(pw_task)


@awith_playwright
async def test_when_serve_page_with_all_absolute_positioned_content_then_footer_banner_appears_pinned_to_bottom_of_browser_viewport_and_stacked_on_top(pw: Playwright) -> None:
    # Serve a page with all absolute positioned content
    server = MockHttpServer({
        '/absolute-page': dict(
            status_code=200,
            headers=[('Content-Type', 'text/html')],
            content=dedent(
                """
                <html>
                <head>
                    <meta charset="utf-8" />
                    <title>Bongo Cat</title>
                </head>
                <body>
                    <header style="position: absolute; width: calc(100% - 20px); padding: 10px; font-size: 32px; text-align: center;">
                        Controls
                    </header>
                    <div id="container" style="position: absolute; top: 50%; left: 50%; transform: translate(-50%,-50%); width: 400px; height: 400px; font-size: 200px; text-align: center; line-height: 400px;">
                        😺
                    </div>
                    <footer style="position: absolute; width: calc(100% - 20px); padding: 10px; bottom: 0; z-index: 500;">
                        Meme by X. Website by Y.
                    </footer>
                </body>
                </html>
                """
            ).strip().encode('utf-8')
        )
    })
    with server:
        absolute_page_url = server.get_url('/absolute-page')
        
        async with (await OpenOrCreateDialog.wait_for()).create() as (mw, project):
            # Download the page
            r = Resource(project, absolute_page_url)
            revision_future = r.download(wait_for_embedded=True)
            await wait_for_future(revision_future)
            
            # Serve the page
            with closing(ProjectServer(project)) as project_server:
                absolute_page_url_in_archive = project_server.get_request_url(absolute_page_url)
                
                # Verify banner is present in the served HTML
                served_page = await fetch_archive_url(absolute_page_url)
                assert served_page.status == 200
                assert 'id="cr-footer-banner"' in served_page.content
                assert _FOOTER_BANNER_MESSAGE in served_page.content
                
                # Verify banner appears pinned to bottom of viewport and stacked on top
                def pw_task(raw_page: RawPage, *args, **kwargs) -> None:
                    raw_page.goto(absolute_page_url_in_archive)
                    
                    # Ensure the banner exists and is visible
                    footer_banner = raw_page.locator('#cr-footer-banner')
                    expect(footer_banner).to_be_visible()
                    expect(footer_banner).to_contain_text(_FOOTER_BANNER_MESSAGE)
                    
                    # Verify banner has non-zero dimensions
                    banner_box = footer_banner.bounding_box()
                    assert banner_box is not None
                    assert banner_box['width'] > 0, \
                        f"Banner width should be > 0, got {banner_box['width']}"
                    assert banner_box['height'] > 0, \
                        f"Banner height should be > 0, got {banner_box['height']}"
                    
                    # Verify banner Y coordinate is > 0 (visible in viewport)
                    assert banner_box['y'] > 0, \
                        f"Banner Y coordinate should be > 0, got {banner_box['y']}"
                    
                    # Verify banner is positioned at or very close to the bottom of the viewport
                    viewport_size = raw_page.viewport_size
                    assert viewport_size is not None
                    viewport_bottom = viewport_size['height']
                    banner_bottom = banner_box['y'] + banner_box['height']
                    assert abs(banner_bottom - viewport_bottom) <= 10, \
                        f"Banner should be at bottom of viewport. ' \
                        f'Banner bottom: {banner_bottom}, Viewport bottom: {viewport_bottom}"
                    
                    # Verify banner is positioned fixed or absolute to stay at bottom
                    banner_styles = footer_banner.evaluate('el => window.getComputedStyle(el)')
                    position = banner_styles['position']
                    assert position in ['fixed', 'absolute'], \
                        f"Banner should be positioned fixed or absolute, got {position}"
                    
                    # Verify banner is stacked on top (has high z-index)
                    z_index = banner_styles.get('zIndex', 'auto')
                    assert z_index.isdigit() and int(z_index) >= 1000, \
                        f"Banner should have high z-index for stacking, got {z_index}"
                await pw.run(pw_task)


@awith_playwright
async def test_when_serve_regular_page_and_branding_logo_cannot_load_then_hides_logo(pw: Playwright) -> None:
    """
    NOTE: The fallback behavior of hiding the broken logo image is different 
          than the fallback behavior for the logo in the branding area on
          served special pages (like the Not in Archive page). On the latter
          pages the logo is replaced with a simplified SVG image which is
          inlined to the page itself. However that inlined SVG adds additional
          size to the page which I don't want to add to every footer banner
          displayed on every served page.
    """
    
    # Serve a simple page that will have a banner
    mock_server = MockHttpServer({
        '/simple-page': dict(
            status_code=200,
            headers=[('Content-Type', 'text/html')],
            content=dedent(
                f"""
                <!DOCTYPE html>
                <html>
                <head>
                    <title>Simple Page</title>
                </head>
                <body>
                    <h1>Simple Page Content</h1>
                    <div>
                        {LOREM_IPSUM_SHORT}
                    </div>
                </body>
                </html>
                """
            ).strip().encode('utf-8')
        )
    })
    with mock_server:
        simple_page_url = mock_server.get_url('/simple-page')
        
        async with (await OpenOrCreateDialog.wait_for()).create() as (mw, project):
            # Download the page
            r = Resource(project, simple_page_url)
            revision_future = r.download(wait_for_embedded=True)
            await wait_for_future(revision_future)
            
            # Serve the page, with the logo image prevented from loading successfully
            original_public_filenames = server._RequestHandler.PUBLIC_STATIC_RESOURCE_NAMES
            with patch.object(
                    server._RequestHandler,
                    'PUBLIC_STATIC_RESOURCE_NAMES',
                    original_public_filenames - {'appicon.png'}):
                with closing(ProjectServer(project)) as project_server:
                    simple_page_url_in_archive = project_server.get_request_url(simple_page_url)
                    
                    # Verify banner is present in the served HTML
                    served_page = await fetch_archive_url(simple_page_url)
                    assert served_page.status == 200
                    assert 'id="cr-footer-banner"' in served_page.content
                    assert _FOOTER_BANNER_MESSAGE in served_page.content
                    
                    # Verify logo is hidden in browser due to onerror handler
                    def pw_task(raw_page: RawPage, *args, **kwargs) -> None:
                        raw_page.goto(simple_page_url_in_archive)
                        
                        # Ensure the banner exists
                        footer_banner = raw_page.locator('#cr-footer-banner')
                        expect(footer_banner).to_be_visible()
                        expect(footer_banner).to_contain_text(
                            _FOOTER_BANNER_MESSAGE)
                        
                        # Ensure the logo img element exists but is hidden due to onerror
                        logo_img = footer_banner.locator('img')
                        expect(logo_img).to_have_count(1)
                        expect(logo_img).to_have_css('display', 'none')
                    
                    await pw.run(pw_task)


async def test_footer_banner_does_not_add_more_than_X_bytes_of_overhead_to_page() -> None:
    """
    The footer banner is currently the heaviest (in page size) element that the
    ProjectServer adds to regular pages. This test verifies that the weight of
    the footer banner does not increase unexpectedly.
    """
    # Serve a simple page that will have a banner
    mock_server = MockHttpServer({
        '/simple-page': dict(
            status_code=200,
            headers=[('Content-Type', 'text/html')],
            content=dedent(
                f"""
                <!DOCTYPE html>
                <html>
                <head>
                    <title>Simple Page</title>
                </head>
                <body>
                    <h1>Simple Page Content</h1>
                    <div>
                        {LOREM_IPSUM_SHORT}
                    </div>
                </body>
                </html>
                """
            ).strip().encode('utf-8')
        )
    })
    with mock_server:
        simple_page_url = mock_server.get_url('/simple-page')
        
        async with (await OpenOrCreateDialog.wait_for()).create() as (mw, project):
            # Download the page
            r = Resource(project, simple_page_url)
            revision_future = r.download(wait_for_embedded=True)
            await wait_for_future(revision_future)
            
            # Serve the page and measure size with banner
            with closing(ProjectServer(project)) as project_server:
                served_page_with_banner = await fetch_archive_url(simple_page_url)
                assert served_page_with_banner.status == 200
                assert 'id="cr-footer-banner"' in served_page_with_banner.content
                assert _FOOTER_BANNER_MESSAGE in served_page_with_banner.content
                page_size_with_banner = len(served_page_with_banner.content_bytes)
            
            # Serve the page and measure size without banner
            with patch.object(HtmlDocument, 'try_insert_footer_banner', return_value=False):
                with closing(ProjectServer(project)) as project_server:
                    served_page_without_banner = await fetch_archive_url(simple_page_url)
                    assert served_page_without_banner.status == 200
                    assert 'id="cr-footer-banner"' not in served_page_without_banner.content
                    assert _FOOTER_BANNER_MESSAGE not in served_page_without_banner.content
                    page_size_without_banner = len(served_page_without_banner.content_bytes)
            
            # Calculate overhead
            banner_overhead = page_size_with_banner - page_size_without_banner
            if _PRINT_BANNER_OVERHEAD:
                print(colorize(
                    TERMINAL_FG_PURPLE,
                    f'Footer banner overhead: {banner_overhead} bytes'
                ))
            
            # Verify banner overhead does not increase greatly unexpectedly
            assert banner_overhead > 0, \
                f'Banner should add some overhead, but got {banner_overhead} bytes'
            assert banner_overhead <= _MAX_BANNER_OVERHEAD_BYTES, (
                f'Banner overhead is {banner_overhead} bytes, which exceeds the '
                f'maximum allowed {_MAX_BANNER_OVERHEAD_BYTES} bytes. '
                f'This indicates the banner content grew unexpectedly.'
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
async def _generic_404_page_visible(
        *, request_path: str='/missing-page/',
        headless: bool=False,
        ) -> AsyncIterator[WebPage]:
    """
    Context manager that opens a test project, starts a server, and returns a WebPage
    for a "Generic 404" page by requesting a URL that doesn't exist in the archive.
    """
    with extracted_project('testdata_xkcd.crystalproj.zip') as project_dirpath, \
            patch('crystal.server.special_pages.SHOW_GENERIC_404_PAGE_INSTEAD_OF_NOT_IN_ARCHIVE_PAGE', True):
        with Project(project_dirpath) as project:
            project.default_url_prefix = 'https://xkcd.com'
        
        if headless:
            with Project(project_dirpath, readonly=True) as project:
                with closing(ProjectServer(project, _DEFAULT_SERVER_PORT+1)) as sp:
                    request_url = sp.get_request_url(f'https://xkcd.com{request_path}')
                    g404_page = await bg_fetch_url(request_url)
                    assert g404_page.title == 'Not in Archive'
                    assert g404_page.status == 404
                    
                    yield g404_page
        else:
            async with (await OpenOrCreateDialog.wait_for()).open(project_dirpath, readonly=True) as (mw, project):
                # Start server
                root_ti = TreeItem.GetRootItem(mw.entity_tree.window)
                home_ti = root_ti.GetFirstChild()
                assert home_ti is not None
                home_ti.SelectItem()
                home_request_url = get_request_url(
                    'https://xkcd.com/',
                    project_default_url_prefix=project.default_url_prefix)
                with assert_does_open_webbrowser_to(home_request_url):
                    click_button(mw.view_button)
                
                # Verify that "Not in Archive" page reached
                request_url = get_request_url(
                    f'https://xkcd.com{request_path}',
                    project_default_url_prefix=project.default_url_prefix)
                g404_page = await bg_fetch_url(request_url)
                assert g404_page.title == 'Not in Archive'
                assert g404_page.status == 404
                
                yield g404_page


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
async def _not_in_archive_page_visible_temporarily() -> AsyncIterator[tuple[str, str, ProjectServer, Project]]:
    """
    Context manager that opens a test project, starts a server, and
    shows a "Not in Archive" page by requesting a URL that doesn't exist in the archive.
    
    The caller may actually download the missing page,
    unlike the _not_in_archive_page_visible() context manager
    where no downloads are allowed.
    """
    with served_project('testdata_xkcd.crystalproj.zip') as sp:
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
            
            home_url_in_archive = get_request_url(
                home_url,
                project_default_url_prefix=project.default_url_prefix)
            comic1_url_in_archive = get_request_url(
                comic1_url,
                project_default_url_prefix=project.default_url_prefix)
            
            # Start the project server by clicking View button
            home_ti.SelectItem()
            with assert_does_open_webbrowser_to(home_url_in_archive):
                click_button(mw.view_button)
            
            yield (comic1_url_in_archive, home_url_in_archive, sp, project)


@asynccontextmanager
async def _fetch_error_page_visible() -> AsyncIterator[tuple[WebPage, str]]:
    """
    Context manager that opens a test project, starts a server, and returns a WebPage
    for a "Fetch Error" page by requesting a URL that exists while the network is down.
    """
    with served_project('testdata_xkcd.crystalproj.zip') as sp:
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
                    await mw.click_download_button(
                        immediate_finish_ok=True)
                    await wait_for_download_to_start_and_finish(
                        mw.task_tree,
                        immediate_finish_ok=True)
            
            home_url_in_archive = get_request_url(
                home_url,
                project_default_url_prefix=project.default_url_prefix)
            
            # Start the project server by clicking View button
            home_ti.SelectItem()
            with assert_does_open_webbrowser_to(home_url_in_archive):
                click_button(mw.view_button)
            
            # Verify that "Fetch Error" page reached
            fetch_error_page = await fetch_archive_url(home_url)
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


def _navigate_from_home_to_comic_1_nia_page(
        raw_page: RawPage,
        home_url_in_archive: str,
        comic1_url_in_archive: str,
        *, already_at_home: bool=False) -> NotInArchivePage:
    """
    Navigates from home page to comic #1, so that referrer is set correctly,
    and the predicted group attributes are realistic.
    """
    if not already_at_home:
        raw_page.goto(home_url_in_archive)
    first_comic_link = raw_page.locator('a', has_text='|<').first
    expect(first_comic_link).to_be_visible()
    first_comic_link.click()
    expect(raw_page).to_have_url(comic1_url_in_archive)
    page = NotInArchivePage.wait_for(raw_page)
    return page


# ------------------------------------------------------------------------------
