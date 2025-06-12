import bs4
from collections.abc import Iterator
from contextlib import contextmanager
from crystal.browser import MainWindow as RealMainWindow
from crystal.doc.generic import Document, Link
from crystal.doc.html import parse_html_and_links
from crystal.doc.html.basic import BasicDocument
from crystal.doc.html.soup import FAVICON_TYPE_TITLE, HtmlDocument
from crystal.model import (
    Project, Resource, ResourceRevision, ResourceRevisionMetadata,
    RootResource,
)
from crystal.tests.util.asserts import assertEqual, assertRaises
from crystal.tests.util.controls import click_button
from crystal.tests.util.runner import bg_sleep
from crystal.tests.util.server import served_project
from crystal.tests.util.subtests import awith_subtests, SubtestsContext
from crystal.tests.util.wait import DEFAULT_WAIT_PERIOD
from crystal.tests.util.windows import (
    MainWindow, OpenOrCreateDialog, PreferencesDialog,
)
from io import BytesIO
import lxml.html
import os
import tempfile
from textwrap import dedent
from unittest import skip
from unittest.mock import Mock, patch
from urllib.parse import ParseResult, urljoin, urlparse

# ------------------------------------------------------------------------------
# Tests: HTML Parser Option

async def test_uses_html_parser_specified_in_preferences() -> None:
    with served_project('testdata_xkcd.crystalproj.zip') as sp:
        # Define URLs
        home_url = sp.get_request_url('https://xkcd.com/')
        
        async with (await OpenOrCreateDialog.wait_for()).create() as (mw, project):
            RootResource(project, 'Home', Resource(project, home_url))
            r = Resource(project, home_url)
            
            # Ensure default HTML parser for new project is lxml
            click_button(mw.preferences_button)
            pd = await PreferencesDialog.wait_for()
            html_parser_title = pd.html_parser_field.Items[pd.html_parser_field.Selection]
            assert 'Fastest - lxml' == html_parser_title
            await pd.ok()
            
            revision_future = r.download(wait_for_embedded=True)
            while not revision_future.done():
                await bg_sleep(DEFAULT_WAIT_PERIOD)
            revision = revision_future.result()
            
            # Ensure expected HTML parser is used
            with _watch_html_parser_usage() as (lxml_parse_func, bs4_parse_func):
                (_, _, _) = revision.document_and_links()
            assert (1, 0) == (lxml_parse_func.call_count, bs4_parse_func.call_count)
            
            # Switch HTML parser
            click_button(mw.preferences_button)
            pd = await PreferencesDialog.wait_for()
            pd.html_parser_field.Selection = pd.html_parser_field.Items.index(
                'Classic - html.parser (bs4)')
            await pd.ok()
            
            # Ensure new HTML parser is used
            with _watch_html_parser_usage() as (lxml_parse_func, bs4_parse_func):
                (_, _, _) = revision.document_and_links()
            assert (0, 1) == (lxml_parse_func.call_count, bs4_parse_func.call_count)


@skip('covered by: test_uses_html_parser_specified_in_preferences')
async def test_defaults_to_lxml_html_parser_for_new_projects() -> None:
    pass


async def test_uses_html_parser_parser_for_classic_projects() -> None:
    # NOTE: The testdata project is a classic project from Crystal <=1.5.0
    with served_project('testdata_xkcd.crystalproj.zip') as sp:
        with RealMainWindow(sp.project) as rmw:
            mw = await MainWindow.wait_for()
            
            click_button(mw.preferences_button)
            pd = await PreferencesDialog.wait_for()
            try:
                html_parser_title = pd.html_parser_field.Items[pd.html_parser_field.Selection]
                assert 'Classic - html.parser (bs4)' == html_parser_title
            finally:
                await pd.ok()


@contextmanager
def _watch_html_parser_usage() -> Iterator[tuple[Mock, Mock]]:
    with patch('lxml.html.document_fromstring', wraps=lxml.html.document_fromstring) as lxml_parse_func:
        with patch('crystal.util.fastsoup.BeautifulSoup', wraps=bs4.BeautifulSoup) as bs4_parse_func:
            yield (lxml_parse_func, bs4_parse_func)


# ------------------------------------------------------------------------------
# Tests: parse_html_and_links

@skip('not yet automated')
def test_recognizes_link_to_background_image() -> None:
    pass  # type_title = 'Background Image'


@skip('not yet automated')
def test_recognizes_link_to_image_using_src() -> None:
    pass  # type_title = 'Image'


@skip('not yet automated')
def test_recognizes_link_to_iframe() -> None:
    pass  # type_title = 'IFrame'


@skip('not yet automated')
def test_recognizes_link_to_frame_when_no_frameset_present() -> None:
    pass  # type_title = 'Frame'


@skip('not yet automated')
def test_recognizes_link_to_frame_when_frameset_present() -> None:
    pass  # type_title = 'Unknown' (in doc/html/basic.py)


@skip('not yet automated')
def test_recognizes_link_to_form_image() -> None:
    pass  # type_title = 'Form Image'


@skip('not yet automated')
def test_recognizes_unknown_link_type_using_src_attribute() -> None:
    # type_title = 'Unknown Embedded (%s)' % tag_name
    # 
    # ex: <audio>, <embed>, <source>, <track>, <video>
    # via: https://www.w3schools.com/tags/att_src.asp
    pass


@skip('not yet automated')
def test_recognizes_link_to_image_using_srcset() -> None:
    pass  # type_title = 'Image'


@skip('not yet automated')
def test_recognizes_text_link() -> None:
    pass  # type_title = 'Link'


@skip('not yet automated')
def test_recognizes_link_to_stylesheet() -> None:
    # ...using rel stylesheet
    # ...using type css
    # ...using css file extension
    pass  # type_title = 'Stylesheet'


@awith_subtests
async def test_recognizes_explicit_link_to_favicon(subtests: SubtestsContext) -> None:
    with subtests.test('in general'):
        HTML_TEXT = dedent(
            '''
            <!DOCTYPE html>
            <html>
                <head>
                    <title>xkcd: Fast Radio Bursts</title>
                    <link rel="icon" href="/s/919f27.ico" type="image/x-icon"/>
                    <link rel="alternate" type="application/atom+xml" title="Atom 1.0" href="/atom.xml"/>
                    <link rel="alternate" type="application/rss+xml" title="RSS 2.0" href="/rss.xml"/>
                </head>
                <body>
                    ...
                </body>
            </html>
            '''
        ).lstrip('\n')
        assert '919f27.ico' in HTML_TEXT  # ensure has explicit favicon link
        
        with tempfile.TemporaryDirectory(suffix='.crystalproj') as project_dirpath:
            os.rmdir(project_dirpath)
            with Project(project_dirpath) as project:
                rr = ResourceRevision.create_from_response(
                    Resource(project, 'https://www.apple.com/'),
                    metadata=ResourceRevisionMetadata(
                        http_version=10,
                        status_code=200,
                        reason_phrase='OK',
                        headers=[
                            ['Content-Type', 'text/html'],
                        ],
                    ),
                    body_stream=BytesIO(HTML_TEXT.encode('utf-8')))
                (doc, links, _) = rr.document_and_links()
                assert isinstance(doc, HtmlDocument)  # ensure using soup parser
                
                # 1. Ensure detects explicit favicon link
                # 2. Ensure does not insert implicit favicon link
                (favicon_link,) = (
                    link for link in links if
                    link.type_title == FAVICON_TYPE_TITLE and
                    link.relative_url == '/s/919f27.ico'
                )
                
                # Ensure can rewrite explicit favicon link
                favicon_link.relative_url = '/favicon2.ico'
                assert 'favicon2.ico' in str(doc)
    
    with subtests.test(using='rel shortcut icon'):  # for old IE
        HTML_TEXT = '''<link rel="shortcut icon" href="/s/919f27.ico" type="image/x-icon"/>'''
        (_, links) = _parse_html_and_links(HTML_TEXT)
        (favicon_link,) = (
            link for link in links if
            link.type_title == FAVICON_TYPE_TITLE and
            link.relative_url == '/s/919f27.ico'
        )
    
    with subtests.test(using='rel icon'):
        HTML_TEXT = '''<link rel="icon" href="/s/919f27.ico" type="image/x-icon"/>'''
        (_, links) = _parse_html_and_links(HTML_TEXT)
        (favicon_link,) = (
            link for link in links if
            link.type_title == FAVICON_TYPE_TITLE and
            link.relative_url == '/s/919f27.ico'
        )
    
    with subtests.test(using='rel apple-touch-icon'):
        HTML_TEXT = '''<link rel="apple-touch-icon" href="/custom_icon.png">'''
        (_, links) = _parse_html_and_links(HTML_TEXT)
        (favicon_link,) = (
            link for link in links if
            link.type_title == FAVICON_TYPE_TITLE and
            link.relative_url == '/custom_icon.png'
        )
    
    with subtests.test(using='ico file extension'):
        HTML_TEXT = '''<link href="/myicon.ico" />'''
        (_, links) = _parse_html_and_links(HTML_TEXT)
        (favicon_link,) = (
            link for link in links if
            link.type_title == FAVICON_TYPE_TITLE and
            link.relative_url == '/myicon.ico'
        )
    
    with subtests.test(using='png file extension'):
        HTML_TEXT = '''<link href="/myicon.png" />'''
        (_, links) = _parse_html_and_links(HTML_TEXT)
        (favicon_link,) = (
            link for link in links if
            link.type_title == FAVICON_TYPE_TITLE and
            link.relative_url == '/myicon.png'
        )


# NOTE: Logic for recognizing this kind of link currently lives in
#       ResourceRevision.document_and_links() rather than inside
#       any parse_html_and_links() function.
@awith_subtests
async def test_recognizes_implicit_link_to_favicon_from_site_root(subtests: SubtestsContext) -> None:
    HTML_TEXT = dedent(
        '''
        <!DOCTYPE html>
        <html xmlns="http://www.w3.org/1999/xhtml" xml:lang="en-US" lang="en-US" prefix="og: http://ogp.me/ns#" class="no-js" data-layout-name="privacy-day">
            <head>
                <meta charset="utf-8"/>
                <link rel="canonical" href="https://www.apple.com/"/>
                <link rel="alternate" href="https://www.apple.com/" hreflang="en-US"/>
                <title>Apple</title>
            </head>
            <body class="page-home ac-nav-overlap globalnav-scrim globalheader-dark nav-dark">
                ...
            </body>
        </html>
        '''
    ).lstrip('\n')
    assert 'favicon.ico' not in HTML_TEXT  # ensure no explicit favicon link
    
    FORCE_BASIC_PARSER_TEXT = '<!-- <frameset></frameset> -->'
    
    with subtests.test(parser='soup'):
        with tempfile.TemporaryDirectory(suffix='.crystalproj') as project_dirpath:
            os.rmdir(project_dirpath)
            with Project(project_dirpath) as project:
                rr = ResourceRevision.create_from_response(
                    Resource(project, 'https://www.apple.com/'),
                    metadata=ResourceRevisionMetadata(
                        http_version=10,
                        status_code=200,
                        reason_phrase='OK',
                        headers=[
                            ['Content-Type', 'text/html'],
                        ],
                    ),
                    body_stream=BytesIO(HTML_TEXT.encode('utf-8')))
                (doc, links, _) = rr.document_and_links()
                assert isinstance(doc, HtmlDocument)  # ensure using soup parser
                
                # Ensure inserts implicit favicon link
                (favicon_link,) = (
                    link for link in links if
                    link.type_title == FAVICON_TYPE_TITLE and
                    link.relative_url == '/favicon.ico'
                )
                
                # Ensure can rewrite implicit favicon link
                # (in document from soup parser)
                favicon_link.relative_url = '/favicon2.ico'
                assert 'favicon2.ico' in str(doc)
    
    with subtests.test(parser='basic'):
        with tempfile.TemporaryDirectory(suffix='.crystalproj') as project_dirpath:
            os.rmdir(project_dirpath)
            with Project(project_dirpath) as project:
                rr = ResourceRevision.create_from_response(
                    Resource(project, 'https://www.apple.com/'),
                    metadata=ResourceRevisionMetadata(
                        http_version=10,
                        status_code=200,
                        reason_phrase='OK',
                        headers=[
                            ['Content-Type', 'text/html'],
                        ],
                    ),
                    body_stream=BytesIO((HTML_TEXT + FORCE_BASIC_PARSER_TEXT).encode('utf-8')))
                (doc, links, _) = rr.document_and_links()
                assert isinstance(doc, BasicDocument)  # ensure using basic parser
                
                # Ensure inserts implicit favicon link
                (favicon_link,) = (
                    link for link in links if
                    link.type_title == FAVICON_TYPE_TITLE and
                    link.relative_url == '/favicon.ico'
                )
                
                # Characterize known limitation:
                # Ensure CANNOT rewrite implicit favicon link
                # (in document from basic parser)
                favicon_link.relative_url = '/favicon2.ico'
                assert 'favicon2.ico' not in str(doc)


# TODO: Consider recognizing implicit favicon regardless of whether
#       at site root or not
async def test_does_not_recognize_implicit_link_to_favicon_from_outside_site_root() -> None:
    HTML_TEXT = dedent(
        '''
        <!DOCTYPE html>
        <html class="en-us amr nojs en seg-consumer us" lang="en-US">
            <head>
                <title>Apple Store Online - Apple</title>
                <meta charset="utf-8" />
                <link rel="canonical" href="https://www.apple.com/store" />
                <link rel="alternate" hreflang="en-us" href="https://www.apple.com/store" />
            </head>
            <body class="">
                ...
            </body>
        </html>
        '''
    ).lstrip('\n')
    assert 'favicon.ico' not in HTML_TEXT  # ensure no explicit favicon link
    
    with tempfile.TemporaryDirectory(suffix='.crystalproj') as project_dirpath:
        os.rmdir(project_dirpath)
        with Project(project_dirpath) as project:
            rr = ResourceRevision.create_from_response(
                Resource(project, 'https://www.apple.com/store'),
                metadata=ResourceRevisionMetadata(
                    http_version=10,
                    status_code=200,
                    reason_phrase='OK',
                    headers=[
                        ['Content-Type', 'text/html'],
                    ],
                ),
                body_stream=BytesIO(HTML_TEXT.encode('utf-8')))
            (doc, links, _) = rr.document_and_links()
            
            # Ensure does NOT insert implicit favicon link
            () = (
                link for link in links if
                link.type_title == FAVICON_TYPE_TITLE and
                link.relative_url == '/favicon.ico'
            )


@skip('not yet automated')
def test_recognizes_link_to_preloaded_resource() -> None:
    pass  # type_title = 'Preload'


@skip('not yet automated')
def test_recognizes_unknown_link_type_using_rel_attribute() -> None:
    # type_title = 'Unknown Link (rel=%s)' % ...
    # 
    # ex: alternate, author, canonical, dns-prefetch, license,
    #     manifest, me, modulepreload, next, pingback, preconnect,
    #     prefetch, prerender, prev, privacy-policy, search,
    #     terms-of-service
    # via: https://developer.mozilla.org/en-US/docs/Web/HTML/Attributes/rel
    pass


@skip('not yet automated')
def test_recognizes_unknown_link_type_using_href_attribute() -> None:
    # type_title = 'Unknown Href (%s)' % tag_name
    # 
    # ex: <none known>
    pass


@skip('not yet automated')
def test_recognizes_onclick_eq_location_eq_ellipsis_link() -> None:
    pass  # type_title = 'Button'


@skip('not yet automated')
def test_recognizes_reference_to_absolute_url_inside_inline_script() -> None:
    pass  # type_title = 'Script Reference'


@skip('not yet automated')
def test_recognizes_reference_to_site_relative_url_inside_inline_script() -> None:
    pass  # type_title = 'Script Reference'


@skip('not yet automated')
def test_recognizes_unknown_attribute_reference_to_absolute_url() -> None:
    pass  # type_title = 'Attribute Reference'


@skip('not yet automated')
def test_does_not_recognize_mailto_or_data_or_javascript_urls_as_links() -> None:
    pass  # see: is_unrewritable_url()


async def test_does_recognize_invalid_relative_urls_as_links() -> None:
    # Ensure test data is detected as an invalid relative URL
    # using native urllib functions
    assert hasattr(urlparse, '_super'), \
        'Expected urlparse() to be patched by patch_urlparse_to_never_raise_exception()'
    assertRaises(
        ValueError,
        lambda: urlparse._super("//*[@id='"))  # type: ignore[attr-defined]
    
    # Ensure test data is detected as an valid relative URL
    # using patched urllib functions
    assertEqual(
        ParseResult(scheme='', netloc='', path="//*[@id='", params='', query='', fragment=''),
        urlparse("//*[@id='"))
    assertEqual(
        "//*[@id='",
        urljoin('https://example.com/', "//*[@id='"))
    
    # Ensure does recognize invalid relative URL as a link in general
    HTML_TEXT = '''<a href="//*[@id='"><a href="#">'''
    (_, links) = _parse_html_and_links(HTML_TEXT)
    (bad_link, good_link) = links
    assert "//*[@id='" == bad_link.relative_url
    assert '#' == good_link.relative_url
    
    with tempfile.TemporaryDirectory(suffix='.crystalproj') as project_dirpath:
        os.rmdir(project_dirpath)
        with Project(project_dirpath) as project:
            rr = ResourceRevision.create_from_response(
                Resource(project, 'https://example.com/'),
                metadata=ResourceRevisionMetadata(
                    http_version=10,
                    status_code=200,
                    reason_phrase='OK',
                    headers=[
                        ['Content-Type', 'text/html'],
                    ],
                ),
                body_stream=BytesIO(HTML_TEXT.encode('utf-8')))
            (doc, links, _) = rr.document_and_links()
            
            # Ensure does recognize invalid relative URL as a document link
            (bad_link, good_link, favicon_link) = links
            assert "//*[@id='" == bad_link.relative_url
            assert '#' == good_link.relative_url
            assert '/favicon.ico' == favicon_link.relative_url


async def test_recognizes_http_redirect_as_a_link() -> None:
    with tempfile.TemporaryDirectory(suffix='.crystalproj') as project_dirpath:
        os.rmdir(project_dirpath)
        with Project(project_dirpath) as project:
            rr = ResourceRevision.create_from_response(
                Resource(project, 'https://www.xkcd.com/'),
                metadata=ResourceRevisionMetadata(
                    http_version=10,
                    status_code=301,
                    reason_phrase='Moved Permanently',
                    headers=[
                        ['Location', 'https://xkcd.com/'],
                    ],
                ),
                body_stream=BytesIO(b''))
            (doc, links, _) = rr.document_and_links()
            
            # Ensure inserts redirect link
            (redirect_link,) = (
                link for link in links if
                link.type_title == 'Redirect' and
                link.relative_url == 'https://xkcd.com/' and
                link.embedded
            )


@skip('fails: not yet implemented')
def test_recognizes_meta_http_equiv_refresh_as_a_link() -> None:
    # see: https://developer.mozilla.org/en-US/docs/Web/HTML/Element/meta#examples
    pass  # type_title = 'Redirect' (proposed)


@skip('not yet automated')
def test_recognizes_links_defined_by_plugins() -> None:
    # ex: plugins_minbaker.postprocess_document_and_links()
    pass


def _parse_html_and_links(html: str) -> tuple[Document, list[Link]]:
    doc_and_links = parse_html_and_links(html.encode('utf-8'), 'utf-8', 'lxml')
    assert doc_and_links is not None
    return doc_and_links


# ------------------------------------------------------------------------------
