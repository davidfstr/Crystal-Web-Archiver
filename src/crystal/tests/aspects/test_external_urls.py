from contextlib import closing
from crystal.model import Project, Resource, Alias
from crystal.server import ProjectServer
from crystal.task import DownloadResourceTask
from crystal.tests.util.asserts import assertEqual, assertIn, assertNotIn, assertRaises
from crystal.tests.util.runner import bg_fetch_url
from crystal.tests.util.server import MockHttpServer
from crystal.tests.util.subtests import SubtestsContext, awith_subtests
from crystal.tests.util.tasks import (
    append_deferred_top_level_tasks,
    scheduler_disabled,
    step_scheduler,
)
from crystal.tests.util.wait import wait_for_future
from crystal.tests.util.windows import OpenOrCreateDialog
from crystal.util.ellipsis import Ellipsis
from textwrap import dedent
from unittest import skip


# === Test: Format & Parse ===

def test_format_external_url_creates_external_urls() -> None:
    assertEqual(
        'crystal://external/https://example.com/page',
        Alias.format_external_url('https://example.com/page'))


def test_parse_external_url_recognizes_external_urls() -> None:
    # External URL format
    assertEqual(
        'https://example.com/page',
        Alias.parse_external_url('crystal://external/https://example.com/page'))
    
    # Normal URL format
    assertEqual(
        None,
        Alias.parse_external_url('https://example.com/page'))


# === Test: Resource API ===

async def test_can_only_create_resource_with_external_url_using_external_ok_equals_true() -> None:
    with Project() as project:
        external_url = 'https://example.com/page'
        formatted_external_url = Alias.format_external_url(external_url)
        
        # Attempting to create without specifying _external_ok=True should raise
        with assertRaises(ValueError) as exc_context:
            Resource(project, formatted_external_url)
        assertIn('_external_ok=True', str(exc_context.exception))
        
        # Should succeed with _external_ok=True
        resource = Resource(project, formatted_external_url, _external_ok=True)
        assertEqual(formatted_external_url, resource.url)
        assertEqual(external_url, resource.external_url)
        assertEqual(True, resource.definitely_has_no_revisions)
        
        # Also, verify that resources with an external URL are not saved to
        # the database or to project tracking
        assertEqual(None, project.get_resource(id=Resource._EXTERNAL_ID))
        assertEqual(None, project.get_resource(url=resource.url))


@skip('covered by: test_can_only_create_resource_with_external_url_using_external_ok_equals_true')
def test_cannot_accidentally_create_a_resource_with_a_url_formatted_as_an_external_url() -> None:
    # ...because ValueError will be raised
    pass


# === Test: Rewrite/Redirect Workflows ===

# TODO: Implement this behavior in NewRootUrlDialog. Test it too.
#       Tracked by: https://github.com/davidfstr/Crystal-Web-Archiver/issues/287
@skip('fails: not yet implemented')
async def test_when_try_to_save_new_root_url_that_looks_like_formatted_external_url_or_uses_crystal_scheme_then_shows_error_dialog() -> None:
    pass


async def test_downloading_a_resource_ignores_any_embedded_urls_that_are_external() -> None:
    """
    Test that when downloading an HTML resource containing embedded links,
    any links that get rewritten by aliases to external URLs are NOT
    scheduled for download.
    """
    with scheduler_disabled():
        # Set up a mock server with three resources:
        # - /page.html (main HTML page with embedded links)
        # - /internal.css (internal resource that WILL be downloaded)
        # - /external/style.css (external resource that will NOT be downloaded)
        server = MockHttpServer({
            '/page.html': dict(
                status_code=200,
                headers=[('Content-Type', 'text/html')],
                content=dedent(
                    """
                    <!DOCTYPE html>
                    <html>
                    <head>
                        <link rel="stylesheet" href="/internal.css">
                        <link rel="stylesheet" href="/external/style.css">
                    </head>
                    <body>
                        <p>Test page</p>
                    </body>
                    </html>
                    """
                ).lstrip('\n').encode('utf-8')
            ),
            '/internal.css': dict(
                status_code=200,
                headers=[('Content-Type', 'text/css')],
                content=b'body { color: blue; }'
            ),
            '/external/style.css': dict(
                status_code=200,
                headers=[('Content-Type', 'text/css')],
                content=b'body { color: red; }'
            ),
        })
        with server:
            page_url = server.get_url('/page.html')
            internal_css_url = server.get_url('/internal.css')
            external_css_in_project_url = server.get_url('/external/style.css')
            external_css_url = 'https://example.com/external/style.css'  # after rewrite by alias
            
            alias_source_prefix = server.get_url('/external/')
            alias_target_prefix = 'https://example.com/external/'
            
            with Project() as project:
                # Create an alias that rewrites /external/ to an external URL
                Alias(
                    project,
                    source_url_prefix=alias_source_prefix,
                    target_url_prefix=alias_target_prefix,
                    target_is_external=True
                )
                
                # Start downloading the main page
                page_r = Resource(project, page_url)
                page_r.download(); append_deferred_top_level_tasks(project)
                
                # Find the DownloadResourceTask
                (download_task,) = project.root_task.children
                assert isinstance(download_task, DownloadResourceTask)
                assertEqual(page_r, download_task.resource)
                
                # Step through: download body
                await step_scheduler(project)
                
                # Step through: parse links
                await step_scheduler(project)
                
                # Step through: process embedded links and create child tasks
                await step_scheduler(project)
                
                # Verify that only the internal CSS was scheduled for download,
                # not the external CSS
                if True:
                    child_download_tasks = [
                        c for c in download_task.children 
                        if isinstance(c, DownloadResourceTask)
                    ]
                    child_urls = [t.resource.url for t in child_download_tasks]
                    
                    # Should download internal.css
                    assertIn(internal_css_url, child_urls)
                    
                    # Should NOT download external/style.css (which was rewritten to an external URL)
                    assertNotIn(external_css_in_project_url, child_urls)
                    assertNotIn(external_css_url, child_urls)


@awith_subtests
async def test_when_undownloaded_source_url_is_requested_from_project_server_that_links_to_external_target_url_then_redirects_to_external_target_url(subtests: SubtestsContext) -> None:
    """
    Test that when a Source URL is requested from ProjectServer,
    and an alias maps it to an external Target URL,
    then ProjectServer responds with a redirect to the external Target URL.
    """
    for resource_exists in [False, True]:
        with subtests.test(resource_exists=resource_exists):
            with Project() as project:
                # Define URLs
                source_url = 'http://example.com/internal/page.html'
                target_url = 'https://external.com/page.html'
                
                if resource_exists:
                    Resource(project, source_url)
                
                # Create an alias that maps source to external target
                Alias(
                    project,
                    source_url_prefix='http://example.com/internal/',
                    target_url_prefix='https://external.com/',
                    target_is_external=True
                )
                
                # Start a ProjectServer
                with closing(ProjectServer(project, port=Ellipsis)) as project_server:
                    # Request the Source URL
                    response = await bg_fetch_url(
                        project_server.get_request_url(source_url),
                        follow_redirects=False)
                    
                    # Verify it redirects to the external Target URL
                    assertEqual(
                        target_url,
                        response.redirect_target_href,
                        'Source URL did not redirect to external Target URL')


async def test_when_downloaded_source_url_is_requested_from_project_server_that_links_to_external_target_url_then_returns_downloaded_revision() -> None:
    """
    Test that when a Source URL that has been downloaded is requested from ProjectServer,
    even though an alias maps it to an external Target URL,
    ProjectServer serves the downloaded revision (not a redirect).
    
    This allows users to view downloaded content that they've archived,
    even if they've configured an alias to redirect to an external site.
    """
    # Set up a mock server with a downloadable resource
    server = MockHttpServer({
        '/internal/page.html': dict(
            status_code=200,
            headers=[('Content-Type', 'text/html')],
            content=b'<html><body>Downloaded content from source URL</body></html>'
        ),
    })
    with server:
        source_url = server.get_url('/internal/page.html')
        target_url = 'https://external.com/page.html'
        
        with Project() as project:
            # Download the source URL BEFORE creating the alias
            # (otherwise Resource constructor will detect it normalizes to an external URL)
            source_r = Resource(project, source_url)
            await wait_for_future(source_r.download())
            
            # Create an alias that maps source to external target
            Alias(
                project,
                source_url_prefix=server.get_url('/internal/'),
                target_url_prefix='https://external.com/',
                target_is_external=True
            )
            
            # Start a ProjectServer
            with closing(ProjectServer(project, port=Ellipsis)) as project_server:
                # Request the Source URL
                response = await bg_fetch_url(
                    project_server.get_request_url(source_url),
                    follow_redirects=False)
                
                # Verify it serves the downloaded revision (not a redirect)
                assertEqual(
                    None,
                    response.redirect_target_href,
                    'Downloaded Source URL should not redirect; should serve the downloaded revision')
                assertEqual(200, response.status)
                assertIn(
                    b'Downloaded content from source URL',
                    response.content_bytes,
                    'Should serve the downloaded content')


async def test_given_an_html_resource_containing_link_to_an_external_url_is_served_when_link_is_followed_then_redirects_to_external_url() -> None:
    """
    Test that when serving an HTML resource containing links,
    any links that are rewritten by aliases to external URLs:
    1. Are served pointing to the Source URL within the project (not direct external URLs)
    2. When the Source URL is requested, ProjectServer redirects to the external Target URL
    """
    # Set up a mock server with an HTML page containing internal and external links
    server = MockHttpServer({
        '/page.html': dict(
            status_code=200,
            headers=[('Content-Type', 'text/html')],
            content=dedent(
                """
                <!DOCTYPE html>
                <html>
                <head>
                    <link rel="stylesheet" href="/internal.css">
                    <link rel="stylesheet" href="/external/style.css">
                </head>
                <body>
                    <p>Links:</p>
                    <a href="/internal-page.html">Internal Page</a>
                    <a href="/external/page.html">External Page</a>
                </body>
                </html>
                """
            ).lstrip('\n').encode('utf-8')
        ),
        '/internal.css': dict(
            status_code=200,
            headers=[('Content-Type', 'text/css')],
            content=b'body { color: blue; }'
        ),
    })
    with server:
        page_url = server.get_url('/page.html')
        internal_css_url = server.get_url('/internal.css')
        external_css_in_project_url = server.get_url('/external/style.css')
        external_css_url = 'https://example.com/external/style.css'  # after rewrite by alias
        external_page_in_project_url = server.get_url('/external/page.html')
        external_page_url = 'https://example.com/external/page.html'  # after rewrite by alias
        
        alias_source_prefix = server.get_url('/external/')
        alias_target_prefix = 'https://example.com/external/'
        
        with Project() as project:
            # Create an alias that rewrites /external/ to an external URL
            Alias(
                project,
                source_url_prefix=alias_source_prefix,
                target_url_prefix=alias_target_prefix,
                target_is_external=True
            )
            
            # Download the main page (with embedded resources)
            page_r = Resource(project, page_url)
            await wait_for_future(page_r.download(wait_for_embedded=True))
            
            # Start a ProjectServer and fetch the served HTML
            with closing(ProjectServer(project, port=Ellipsis)) as project_server:
                # Verify links in served HTML
                served_page = await bg_fetch_url(project_server.get_request_url(page_url))
                served_html = served_page.content
                assertIn(
                    f'href="{project_server.get_request_url(internal_css_url)}"',
                    served_html,
                    'Expected internal CSS link to be rewritten to project-internal URL')
                assertIn(
                    f'href="{project_server.get_request_url(external_css_in_project_url)}"',
                    served_html,
                    'Expected external CSS link to point to Source URL within the project')
                assertIn(
                    f'href="{project_server.get_request_url(external_page_in_project_url)}"',
                    served_html,
                    'Expected external page link to point to Source URL within the project')
                
                # Verify requesting a Source URL redirects to the external Target URL
                if True:
                    internal_css_response = await bg_fetch_url(
                        project_server.get_request_url(internal_css_url),
                        follow_redirects=False)
                    assertEqual(
                        None,
                        internal_css_response.redirect_target_href,
                        'Internal CSS URL unexpectedly redirected somewhere else')
                    assertEqual(200, internal_css_response.status)
                    
                    external_css_response = await bg_fetch_url(
                        project_server.get_request_url(external_css_in_project_url),
                        follow_redirects=False)
                    assertEqual(
                        external_css_url,
                        external_css_response.redirect_target_href,
                        'External CSS Source URL did not redirect to external Target URL')
                    
                    external_page_response = await bg_fetch_url(
                        project_server.get_request_url(external_page_in_project_url),
                        follow_redirects=False)
                    assertEqual(
                        external_page_url,
                        external_page_response.redirect_target_href,
                        'External page Source URL did not redirect to external Target URL')
