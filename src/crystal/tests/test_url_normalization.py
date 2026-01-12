"""
Crystal treats certain URLs as being exactly equivalent to other URLs,
assuming that a fetch for the latter URL will give exactly the same response
as the former URL.

Example:
- https://xkcd.com#hello -> (remove fragment)
  https://xkcd.com -> (add missing root path)
  https://xkcd.com/

Concepts related to normalized URLs:
- Original URL -- 
    A URL that hasn't been normalized at all
- Alternative URL (for an Original URL) -- 
    An original URL or a more-normalized version of the original URL
- Normalized URL (for an Original URL) --
    The maximally-normalized alternative URL of the original URL

An Original URL may have 1 or more partially-normalized Alternative URLs
(that match neither the Original URL or its Normalized URL) for backward
compatibility with older saved projects that used less sophisticated
normalization rules.

For more information, see the doccomment on:
- Resource.resource_url_alternatives
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, closing
from crystal.model import Project, Resource, RootResource
from crystal.server import ProjectServer
from crystal.tests.util.asserts import assertEqual, assertIn, assertNotEqual, assertNotIn
from crystal.tests.util.controls import TreeItem
from crystal.tests.util.runner import bg_fetch_url
from crystal.tests.util.server import MockHttpServer
from crystal.tests.util.wait import first_child_of_tree_item_is_not_loading_condition, wait_for, wait_for_future
from crystal.tests.util.windows import MainWindow, OpenOrCreateDialog
from crystal.tests.util import xtempfile
import os
from textwrap import dedent
from unittest import skip
from unittest.mock import ANY, patch


_DUMMY_PROJECT: Project = ANY


# === Test: Normalization Rules ===

def test_alternatives_of_fully_normalized_url_is_only_the_original_url() -> None:
    assertEqual(
        ['https://xkcd.com/'],
        Resource.resource_url_alternatives(_DUMMY_PROJECT, 'https://xkcd.com/'))


# NOTE: Does not cover the "always" part of the invariant described
def test_alternatives_of_non_normalized_url_always_has_the_original_url_as_the_first_alternative() -> None:
    assertEqual(
        'https://xkcd.com#hello',
        Resource.resource_url_alternatives(_DUMMY_PROJECT, 'https://xkcd.com#hello')[0])


# NOTE: Does not cover the "always" part of the invariant described
def test_alternatives_of_non_normalized_url_always_has_the_most_normalized_version_of_the_url_as_the_last_alternative() -> None:
    assertEqual(
        'https://xkcd.com/',
        Resource.resource_url_alternatives(_DUMMY_PROJECT, 'https://xkcd.com#hello')[-1])


def test_alternatives_of_non_normalized_url_may_have_multiple_more_normalized_versions_of_the_url() -> None:
    assertEqual([
        'https://xkcd.com#hello',
        'https://xkcd.com',
        'https://xkcd.com/',
    ], Resource.resource_url_alternatives(_DUMMY_PROJECT, 'https://xkcd.com#hello'))


def test_normalized_url_does_not_have_fragment_component() -> None:
    assertEqual(
        'https://xkcd.com/1/',
        Resource.resource_url_alternatives(_DUMMY_PROJECT, 'https://xkcd.com/1/#footer')[-1])


def test_normalized_url_has_lowercased_domain_name() -> None:
    assertEqual(
        'https://xkcd.com/1/',
        Resource.resource_url_alternatives(_DUMMY_PROJECT, 'https://XKCD.com/1/')[-1])


def test_normalized_url_pointing_at_root_of_domain_always_ends_in_slash() -> None:
    assertEqual(
        'https://xkcd.com/',
        Resource.resource_url_alternatives(_DUMMY_PROJECT, 'https://xkcd.com')[-1])


def test_normalized_url_is_percent_encoded() -> None:
    assertEqual(
        'https://xkcd.com/old%20archive/',
        Resource.resource_url_alternatives(_DUMMY_PROJECT, 'https://xkcd.com/old archive/')[-1])


@skip('not yet automated')
def test_plugins_can_normalize_urls() -> None:
    pass


# === Test: Normalization Effects ===

async def test_given_project_database_contains_resource_or_root_resource_with_non_normalized_url_then_loaded_resources_retain_original_non_normalized_url() -> None:
    """
    Projects that already have an original URL defined as a Resource will retain
    the Resource with the original URL, upon opening the project
    (in Resource.__new__, when id is not None).
    """
    NON_NORMALIZED_URL = 'https://xkcd.com'
    
    with xtempfile.TemporaryDirectory(suffix='.crystalproj') as project_dirpath:
        os.rmdir(project_dirpath)
        
        # Disable URL normalization
        def do_not_normalize(project: Project, url: str) -> list[str]:
            return [url]
        with patch.object(Resource, 'resource_url_alternatives', do_not_normalize):
            
            # Create Project containing Resource with non-normalized URL
            with Project(project_dirpath) as p:
                r = Resource(p, url=NON_NORMALIZED_URL)
                assertEqual(NON_NORMALIZED_URL, r.url)
                
                rr = RootResource(p, '', r)
                assertEqual(NON_NORMALIZED_URL, rr.url)
        
        # Ensure when Project reopened with URL normalization enabled,
        # Resource with non-normalized URL still retains that URL
        with Project(project_dirpath) as p:
            r2 = p.get_resource(url=NON_NORMALIZED_URL)
            assert r2 is not None
            assertEqual(NON_NORMALIZED_URL, r2.url)
            
            rr2 = p.get_root_resource(url=NON_NORMALIZED_URL)
            assert rr2 is not None
            assertEqual(NON_NORMALIZED_URL, rr2.url)


async def test_given_html_resource_with_link_to_embedded_non_normalized_url_when_download_html_resource_then_also_downloads_normalized_version_of_embedded_url() -> None:
    """
    Download tasks (DownloadResourceTask.child_task_did_complete)
    will resolve links within an HTML document 
    that point to an original URL to point at its normalized URL, 
    downloading embedded resources directly from the normalized URL and saving them 
    to the project with the normalized URL.
    """
    async with _html_page_pointing_to_other_domain_with_non_canonical_url(embedded=True) as (HTML_URL, NON_NORMALIZED_URL, NORMALIZED_URL, mw, project):
        assertNotEqual(None, project.get_resource(url=HTML_URL))
        assertEqual(None, project.get_resource(url=NON_NORMALIZED_URL))
        assertNotEqual(None, project.get_resource(url=NORMALIZED_URL))


async def test_given_html_resource_with_link_to_non_normalized_url_when_its_resource_node_is_expanded_in_the_entity_tree_then_displayed_links_use_normalized_version_of_url() -> None:
    """
    The Entity Tree (_ResourceNode.update_children) will resolve links within an HTML document
    that point to an original URL to point at its normalized URL,
    showing only the normalized URL in the Entity Tree,
    in the common case where the original URL is not found in the project.
    """
    async with _html_page_pointing_to_other_domain_with_non_canonical_url(embedded=False) as (HTML_URL, NON_NORMALIZED_URL, NORMALIZED_URL, mw, project):
        root_ti = TreeItem.GetRootItem(mw.entity_tree.window)
        (html_ti,) = root_ti.Children
        html_ti.Expand()
        await wait_for(first_child_of_tree_item_is_not_loading_condition(html_ti))
        # Should not raise TreeItem.ChildNotFound
        html_ti.find_child(NORMALIZED_URL, project.default_url_prefix)


async def test_given_html_resource_with_link_to_non_normalized_url_when_served_by_project_server_then_links_retain_original_non_normalized_url() -> None:
    """
    When ProjectServer serves a rewritten HTML page,
    links involving an original URL are NOT directly rewritten to point at its normalized URL.
    The links are served with the original URL. However, see the next test below...
    """
    async with _html_page_pointing_to_other_domain_with_non_canonical_url(embedded=False) as (HTML_URL, NON_NORMALIZED_URL, NORMALIZED_URL, mw, project):
        with closing(ProjectServer(project, port=Ellipsis)) as server:
            served_html = (await bg_fetch_url(server.get_request_url(HTML_URL))).content

            assertNotIn(
                f'<a href="{server.get_request_url(NORMALIZED_URL)}">',
                served_html)
            assertIn(
                f'<a href="{server.get_request_url(NON_NORMALIZED_URL)}">',
                served_html)


async def test_when_non_normalized_url_requested_from_project_server_then_responds_with_redirect_to_normalized_version_of_url() -> None:
    """
    When ProjectServer serves a request for an original URL,
    it will respond with a redirect to its normalized URL (within the project),
    in the common case where the original URL is not found in the project.
    """
    async with _html_page_pointing_to_other_domain_with_non_canonical_url(embedded=False) as (HTML_URL, NON_NORMALIZED_URL, NORMALIZED_URL, mw, project):
        with closing(ProjectServer(project, port=Ellipsis)) as server:
            response = await bg_fetch_url(
                server.get_request_url(NON_NORMALIZED_URL),
                follow_redirects=False)
            assertEqual(
                server.get_request_url(NORMALIZED_URL),
                response.redirect_target_href,
                'Response was not a redirect or did not redirect to the expected location')


@asynccontextmanager
async def _html_page_pointing_to_other_domain_with_non_canonical_url(
        embedded: bool = False,
        ) -> AsyncIterator[tuple[str, str, str, MainWindow, Project]]:
    with MockHttpServer() as server2:
        NON_NORMALIZED_URL = server2.get_url('')
        NORMALIZED_URL = server2.get_url('/')
        
        link_html = (
            f'<img src="{NON_NORMALIZED_URL}" />'
            if embedded
            else f'<a href="{NON_NORMALIZED_URL}">Other Domain</a>'
        )
        
        server1 = MockHttpServer({
            '/': dict(
                status_code=200,
                headers=[('Content-Type', 'text/html')],
                content=dedent(
                    f"""
                    <!DOCTYPE html>
                    <html>
                    <body>
                        {link_html}
                    </body>
                    </html>
                    """
                ).lstrip('\n').encode('utf-8')
            )
        })
        with server1:
            HTML_URL = server1.get_url('/')
            
            async with (await OpenOrCreateDialog.wait_for()).create() as (mw, project):
                html_r = Resource(project, HTML_URL)
                html_rr = RootResource(project, '', html_r)
                revision_future = html_r.download(wait_for_embedded=True)
                await wait_for_future(revision_future)
                
                yield (HTML_URL, NON_NORMALIZED_URL, NORMALIZED_URL, mw, project)
