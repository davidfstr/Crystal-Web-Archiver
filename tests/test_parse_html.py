from crystal.doc.generic import Document, Link
from crystal.doc.html import HTML_PARSER_TYPE_CHOICES, HtmlParserType
from crystal.doc.html import parse_html_and_links as try_parse_html_and_links
from crystal.doc.html.soup import HtmlDocument
from crystal.server import _RequestHandler
from crystal.tests.util.subtests import SubtestsContext, with_subtests
from textwrap import dedent
from typing import List, Tuple

# === Tests: Parse/Format Document ===

def test_can_parse_and_format_basic_html_document() -> None:
    with SubtestsContext('test_can_parse_and_format_basic_html_document').run() as subtests:
        for html_parser_type in HTML_PARSER_TYPE_CHOICES:
            with subtests.test(html_parser_type=html_parser_type):
                EXPECTED_OUTPUT_HTML_STR_CHOICES = [
                    dedent(  # html.parser
                        """
                        <!DOCTYPE html>
                        
                        <html>
                        <head>
                        <meta charset="utf-8"/>
                        <title>Home</title>
                        </head>
                        <body>
                            Hello world!
                        </body>
                        </html>
                        """
                    ).lstrip('\n'),
                    dedent(  # lxml
                        """
                        <html>
                        <head>
                            <meta charset="utf-8">
                            <title>Home</title>
                        </head>
                        <body>
                            Hello world!
                        </body>
                        </html>
                        """
                    ).lstrip('\n').rstrip('\n'),
                ]
                
                doc = _parse_basic_html_document(html_parser_type)
                assert str(doc) in EXPECTED_OUTPUT_HTML_STR_CHOICES


def _parse_basic_html_document(html_parser_type: HtmlParserType) -> HtmlDocument:
    INPUT_HTML_BYTES = dedent(
        """
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8" />
            <title>Home</title>
        </head>
        <body>
            Hello world!
        </body>
        </html>
        """
    ).lstrip('\n').encode('utf-8')
    
    (doc, _) = _parse_html_and_links(INPUT_HTML_BYTES, html_parser_type=html_parser_type)
    
    assert isinstance(doc, HtmlDocument)
    return doc


def test_can_insert_script_reference_in_html_document() -> None:
    with SubtestsContext('test_can_insert_script_reference_in_html_document').run() as subtests:
        for html_parser_type in HTML_PARSER_TYPE_CHOICES:
            with subtests.test(html_parser_type=html_parser_type):
                EXPECTED_OUTPUT_HTML_STR_CHOICES = [
                    dedent(  # html.parser
                        """
                        <!DOCTYPE html>
                        
                        <script src="/script.js"></script><html>
                        <head>
                        <meta charset="utf-8"/>
                        <title>Home</title>
                        </head>
                        <body>
                            Hello world!
                        </body>
                        </html>
                        """
                    ).lstrip('\n'),
                    dedent(  # lxml
                        """
                        <html>
                        <script src="/script.js"></script><head>
                            <meta charset="utf-8">
                            <title>Home</title>
                        </head>
                        <body>
                            Hello world!
                        </body>
                        </html>
                        """
                    ).lstrip('\n').rstrip('\n'),
                ]
                
                doc = _parse_basic_html_document(html_parser_type)
                
                success = doc.try_insert_script('/script.js')
                assert success
                assert str(doc) in EXPECTED_OUTPUT_HTML_STR_CHOICES


# === Tests: Recognize Links ===

# TODO: Extend each "test_recognizes_*" to also test WRITING
#       to the relative_url of the output link to ensure it
#       gets saves in a reasonable way.

def test_recognizes_links_inside_style_tags() -> None:
    with SubtestsContext('test_recognizes_links_inside_style_tags').run() as subtests:
        for html_parser_type in HTML_PARSER_TYPE_CHOICES:
            with subtests.test(html_parser_type=html_parser_type):
                (_, (link,)) = _parse_html_and_links(
                    b"""<style>@import "oo.css";</style>""",
                    html_parser_type=html_parser_type)
                assert 'oo.css' == link.relative_url
                assert 'CSS @import' == link.type_title
                assert True == link.embedded


def test_recognizes_links_inside_style_attributes() -> None:
    with SubtestsContext('test_recognizes_links_inside_style_attributes').run() as subtests:
        for html_parser_type in HTML_PARSER_TYPE_CHOICES:
            with subtests.test(html_parser_type=html_parser_type):
                (_, (link,)) = _parse_html_and_links(
                    b"""<dl style="background-image: url('./Forum_read.png')"></dl>""",
                    html_parser_type=html_parser_type)
                assert './Forum_read.png' == link.relative_url
                assert 'CSS URL Reference' == link.type_title
                assert True == link.embedded


def test_recognizes_body_background_link() -> None:
    with SubtestsContext('test_recognizes_body_background_link').run() as subtests:
        for html_parser_type in HTML_PARSER_TYPE_CHOICES:
            with subtests.test(html_parser_type=html_parser_type):
                (_, (link,)) = _parse_html_and_links(
                    b"""<body background="background.png"></body>""",
                    html_parser_type=html_parser_type)
                assert 'background.png' == link.relative_url
                assert 'Background Image' == link.type_title
                assert True == link.embedded


def test_recognizes_src_attribute() -> None:
    with SubtestsContext('test_recognizes_src_attribute').run() as subtests:
        for html_parser_type in HTML_PARSER_TYPE_CHOICES:
            with subtests.test(html_parser_type=html_parser_type):
                # <img src=*>
                (_, (link,)) = _parse_html_and_links(
                    b"""<img src="background.png" title="Background" />""",
                    html_parser_type=html_parser_type)
                assert 'background.png' == link.relative_url
                assert 'Image' == link.type_title
                assert 'Background' == link.title
                assert True == link.embedded
                
                # <iframe src=*>
                (_, (link,)) = _parse_html_and_links(
                    b"""<iframe src="content.html" name="content"></iframe>""",
                    html_parser_type=html_parser_type)
                assert 'content.html' == link.relative_url
                assert 'IFrame' == link.type_title
                assert 'content' == link.title
                assert True == link.embedded
                
                # <frame src=*>, properly in a <frameset>
                # NOTE: The existence of a <frameset> currently triggers the use of the
                #       "basic" HTML parser rather than the "soup" HTML parser.
                (_, (link,)) = _parse_html_and_links(dedent(
                    """
                    <frameset cols="50%, 50%">
                        <frame src="content.html" name="content"></frame>
                    </frameset>
                    """).lstrip('\n').encode('utf-8'),
                    html_parser_type=html_parser_type)
                assert 'content.html' == link.relative_url
                assert 'Unknown' == link.type_title
                assert None == link.title
                assert False == link.embedded
                
                # <frame src=*>, improperly outside a <frameset>
                (_, (link,)) = _parse_html_and_links(
                    b"""<frame src="content.html" name="content"></frame>""",
                    html_parser_type=html_parser_type)
                assert 'content.html' == link.relative_url
                assert 'Frame' == link.type_title
                assert 'content' == link.title
                assert True == link.embedded
                
                # <input type="image" src=*>
                (_, (link,)) = _parse_html_and_links(
                    b"""<input type="image" src="login-button.png" alt="Login" />""",
                    html_parser_type=html_parser_type)
                assert 'login-button.png' == link.relative_url
                assert 'Form Image' == link.type_title
                assert 'Login' == link.title
                assert True == link.embedded
                
                # <??? src=*>
                (_, (link,)) = _parse_html_and_links(
                    b"""<div src="image.png"></div>""",
                    html_parser_type=html_parser_type)
                assert 'image.png' == link.relative_url
                assert 'Unknown Embedded (div)' == link.type_title
                assert None == link.title
                assert True == link.embedded


def test_recognizes_img_srcset() -> None:
    with SubtestsContext('test_recognizes_img_srcset').run() as subtests:
        for html_parser_type in HTML_PARSER_TYPE_CHOICES:
            with subtests.test(html_parser_type=html_parser_type):
                # Case 1: Normal
                (_, (link1, link2)) = _parse_html_and_links(dedent(
                    """
                    <img
                        src="clock-demo-200px.png"
                        alt="Clock"
                        srcset="clock-demo-400px.png 2x" />
                    """).lstrip('\n').encode('utf-8'),
                    html_parser_type=html_parser_type)
                assert ('clock-demo-200px.png', 'Image', 'Clock', True) == (
                    link1.relative_url, link1.type_title, link1.title, link1.embedded,
                )
                assert ('clock-demo-400px.png', 'Image', 'Clock', True) == (
                    link2.relative_url, link2.type_title, link2.title, link2.embedded,
                )
                
                # Case 2: srcset with missing condition descriptor
                (_, (link1, link2)) = _parse_html_and_links(dedent(
                    """
                    <img
                        srcset="images/team-photo.jpg, images/team-photo-retina.jpg 2x" />
                    """).lstrip('\n').encode('utf-8'),
                    html_parser_type=html_parser_type)
                assert ('images/team-photo.jpg', 'Image', None, True) == (
                    link1.relative_url, link1.type_title, link1.title, link1.embedded,
                )
                assert ('images/team-photo-retina.jpg', 'Image', None, True) == (
                    link2.relative_url, link2.type_title, link2.title, link2.embedded,
                )
                
                # Case 3: srcset with a data: URL containing a comma
                (_, (link1, link2)) = _parse_html_and_links(dedent(
                    """
                    <img
                        src="https://i1.wp.com/shoujo-manga.land/wp-content/uploads/2020/02/small-logo2.png?fit=300%2C60&amp;ssl=1" 
                        srcset="data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7" />
                    """).lstrip('\n').encode('utf-8'),
                    html_parser_type=html_parser_type)
                assert (
                    'https://i1.wp.com/shoujo-manga.land/wp-content/uploads/2020/02/small-logo2.png?fit=300%2C60&ssl=1',
                    'Image', None, True
                ) == (
                    link1.relative_url, link1.type_title, link1.title, link1.embedded,
                )
                assert (
                    'data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7',
                    'Image', None, True
                ) == (
                    link2.relative_url, link2.type_title, link2.title, link2.embedded,
                )


def test_recognizes_source_srcset() -> None:
    with SubtestsContext('test_recognizes_source_srcset').run() as subtests:
        for html_parser_type in HTML_PARSER_TYPE_CHOICES:
            with subtests.test(html_parser_type=html_parser_type):
                (_, (link1, link2, link3)) = _parse_html_and_links(dedent(
                    """
                    <picture>
                        <source srcset="clock-demo-1000px.png 1x" media="(min-width: 1000)" />
                        <source srcset="clock-demo-700px.png 1x" media="(min-width: 700)" />
                        <img src="clock-demo-200px.png" alt="Clock" />
                    </picture>
                    """).lstrip('\n').encode('utf-8'),
                    html_parser_type=html_parser_type)
                
                assert 'clock-demo-1000px.png' == link1.relative_url
                assert 'Image Source' == link1.type_title
                assert None == link1.title
                assert True == link1.embedded
                
                assert 'clock-demo-700px.png' == link2.relative_url
                assert 'Image Source' == link2.type_title
                assert None == link2.title
                assert True == link2.embedded
                
                assert 'clock-demo-200px.png' == link3.relative_url
                assert 'Image' == link3.type_title
                assert 'Clock' == link3.title
                assert True == link3.embedded


def test_recognizes_href_attribute() -> None:
    with SubtestsContext('test_recognizes_href_attribute').run() as subtests:
        for html_parser_type in HTML_PARSER_TYPE_CHOICES:
            with subtests.test(html_parser_type=html_parser_type):
                # <a href=*>
                (_, (link,)) = _parse_html_and_links(
                    b"""<a href="https://example.com">Website</a>""",
                    html_parser_type=html_parser_type)
                assert 'https://example.com' == link.relative_url
                assert 'Link' == link.type_title
                assert 'Website' == link.title
                assert False == link.embedded
                
                # <link rel="stylesheet" href=*>
                (_, (link,)) = _parse_html_and_links(
                    b"""<link rel="stylesheet" href="styles" />""",
                    html_parser_type=html_parser_type)
                assert 'styles' == link.relative_url
                assert 'Stylesheet' == link.type_title
                assert None == link.title
                assert True == link.embedded
                
                # <link type="text/css" href=*>
                (_, (link,)) = _parse_html_and_links(
                    b"""<link type="text/css" href="styles" />""",
                    html_parser_type=html_parser_type)
                assert 'styles' == link.relative_url
                assert 'Stylesheet' == link.type_title
                assert None == link.title
                assert True == link.embedded
                
                # <link href="*.css">
                (_, (link,)) = _parse_html_and_links(
                    b"""<link href="styles.css" />""",
                    html_parser_type=html_parser_type)
                assert 'styles.css' == link.relative_url
                assert 'Stylesheet' == link.type_title
                assert None == link.title
                assert True == link.embedded
                
                # <link rel="shortcut icon" href=*>
                (_, (link,)) = _parse_html_and_links(
                    b"""<link rel="shortcut icon" href="favicon.ico" />""",
                    html_parser_type=html_parser_type)
                assert 'favicon.ico' == link.relative_url
                assert 'Icon' == link.type_title
                assert None == link.title
                assert True == link.embedded
                
                # <link rel="icon" href=*>
                (_, (link,)) = _parse_html_and_links(
                    b"""<link rel="icon" href="favicon.ico" />""",
                    html_parser_type=html_parser_type)
                assert 'favicon.ico' == link.relative_url
                assert 'Icon' == link.type_title
                assert None == link.title
                assert True == link.embedded
                
                # <link rel="apple-touch-icon" href=*>
                (_, (link,)) = _parse_html_and_links(
                    b"""<link rel="apple-touch-icon" href="appicon.png" />""",
                    html_parser_type=html_parser_type)
                assert 'appicon.png' == link.relative_url
                assert 'Icon' == link.type_title
                assert None == link.title
                assert True == link.embedded

                # <??? href=*>
                (_, (link,)) = _parse_html_and_links(
                    b"""<div href="image.png"></div>""",
                    html_parser_type=html_parser_type)
                assert 'image.png' == link.relative_url
                assert 'Unknown Href (div)' == link.type_title
                assert None == link.title
                assert False == link.embedded


def test_recognizes_input_button_onclick() -> None:
    with SubtestsContext('test_recognizes_input_button_onclick').run() as subtests:
        for html_parser_type in HTML_PARSER_TYPE_CHOICES:
            with subtests.test(html_parser_type=html_parser_type):
                # <* onclick='*.location = "*";'>
                (_, (link,)) = _parse_html_and_links(
                    b"""<input type='button' onclick='window.location = "http://example.com/";' value='Example'>""",
                    html_parser_type=html_parser_type)
                assert ('http://example.com/', 'Clickable', 'Example', False) == (
                    link.relative_url, link.type_title, link.title, link.embedded,
                )


def test_recognizes_a_onclick() -> None:
    with SubtestsContext('test_recognizes_a_onclick').run() as subtests:
        for html_parser_type in HTML_PARSER_TYPE_CHOICES:
            with subtests.test(html_parser_type=html_parser_type):
                # <* onclick='*.location = "*";'>
                (_, (link1, link2)) = _parse_html_and_links(
                    b"""<a href="moon-img.html" onclick="window.self.location='moon.html'" target="main">Sailor Moon</a>""",
                    html_parser_type=html_parser_type)
                assert ('moon-img.html', 'Link', 'Sailor Moon', False) == (
                    link1.relative_url, link1.type_title, link1.title, link1.embedded,
                )
                assert ('moon.html', 'Clickable', None, False) == (
                    link2.relative_url, link2.type_title, link2.title, link2.embedded,
                )


def test_recognizes_javascript_with_absolute_or_site_relative_url() -> None:
    with SubtestsContext('test_recognizes_javascript_with_absolute_or_site_relative_url').run() as subtests:
        for html_parser_type in HTML_PARSER_TYPE_CHOICES:
            with subtests.test(html_parser_type=html_parser_type):
                # <script [type="text/javascript"]>..."http(s)://**"...</script>
                if True:
                    (_, (link,)) = _parse_html_and_links(
                        b"""<script>const url = "http://example.com/"; window.location = url;</script>""",
                        html_parser_type=html_parser_type)
                    assert 'http://example.com/' == link.relative_url
                    assert 'Script Reference' == link.type_title
                    assert None == link.title
                    assert False == link.embedded
                    
                    (_, (link,)) = _parse_html_and_links(
                        b"""<script>const url = "http://example.com/poster.png"; window.location = url;</script>""",
                        html_parser_type=html_parser_type)
                    assert 'http://example.com/poster.png' == link.relative_url
                    assert 'Script Reference' == link.type_title
                    assert None == link.title
                    assert True == link.embedded
                    
                    (_, ()) = _parse_html_and_links(
                        b"""<script type="x-json">["http://example.com/"]</script>""",
                        html_parser_type=html_parser_type)
                
                # <script [type="text/javascript"]>..."http(s)://"...</script>
                if True:
                    (_, (link,)) = _parse_html_and_links(
                        b"""<script>const url = 'http://' + disqus_shortname + '.disqus.com/embed.js'; window.location = url;</script>""",
                        html_parser_type=html_parser_type)
                    assert 'http://' == link.relative_url
                    assert 'Script Reference' == link.type_title
                    assert None == link.title
                    assert False == link.embedded
                    
                    # Ensure rewrites link 'http://' properly
                    def get_request_url(absolute_url: str) -> str:
                        if absolute_url == 'http://':
                            return 'http://localhost:2797/_/http/'
                        else:
                            raise NotImplementedError()
                    _RequestHandler._rewrite_links(
                        links=[link],
                        base_url='http://strangecandy.net/',
                        get_request_url=get_request_url)
                    assert 'http://localhost:2797/_/http/' == link.relative_url
                
                # <script [type="text/javascript"]>..."//**"...</script>
                if True:
                    (_, (link,)) = _parse_html_and_links(
                        b"""<script>const url = "//home.html"; window.location = url;</script>""",
                        html_parser_type=html_parser_type)
                    assert '//home.html' == link.relative_url
                    assert 'Script Reference' == link.type_title
                    assert None == link.title
                    assert False == link.embedded
                    
                    (_, (link,)) = _parse_html_and_links(
                        b"""<script>const url = "//poster.png"; window.location = url;</script>""",
                        html_parser_type=html_parser_type)
                    assert '//poster.png' == link.relative_url
                    assert 'Script Reference' == link.type_title
                    assert None == link.title
                    assert True == link.embedded
                    
                    (_, ()) = _parse_html_and_links(
                        b"""<script type="x-json">["//home.html"]</script>""",
                        html_parser_type=html_parser_type)


def test_recognizes_unknown_attribute_with_absolute_url() -> None:
    with SubtestsContext('test_recognizes_unknown_attribute_with_absolute_url').run() as subtests:
        for html_parser_type in HTML_PARSER_TYPE_CHOICES:
            with subtests.test(html_parser_type=html_parser_type):
                # <* *="http(s)://**">
                if True:
                    (_, (link,)) = _parse_html_and_links(
                        b"""<a data-src="https://squarespace.com/">Logo</a>""",
                        html_parser_type=html_parser_type)
                    assert 'https://squarespace.com/' == link.relative_url
                    assert 'Attribute Reference' == link.type_title
                    assert None == link.title
                    assert False == link.embedded
                    
                    (_, (link,)) = _parse_html_and_links(
                        b"""<img data-src="https://images.squarespace-cdn.com/calm+circle+logo.png" />""",
                        html_parser_type=html_parser_type)
                    assert 'https://images.squarespace-cdn.com/calm+circle+logo.png' == link.relative_url
                    assert 'Attribute Reference' == link.type_title
                    assert None == link.title
                    assert True == link.embedded


# === Tests: Rewrite Links ===

# https://developer.mozilla.org/en-US/docs/Web/Security/Subresource_Integrity
def test_when_rewrite_link_using_integrity_then_removes_integrity_attribute() -> None:
    with SubtestsContext('test_recognizes_links_inside_style_tags').run() as subtests:
        for html_parser_type in HTML_PARSER_TYPE_CHOICES:
            with subtests.test(tag='script', html_parser_type=html_parser_type):
                (doc, (link,)) = _parse_html_and_links(
                    b'<script src="https://example.com/script.js" integrity="sha384-v8BU367qNbs/aIZIxuivaU55N5GPF89WBerHoGA4QTcbUjYiLQtKdrfXnqAcXyTv"></script>',
                    html_parser_type=html_parser_type)
                assert (
                    'https://example.com/script.js',
                    'Unknown Embedded (script)', None, True
                ) == (
                    link.relative_url, link.type_title, link.title, link.embedded,
                )
                
                link.relative_url = 'http://localhost:2797/_/https/example.com/script.js'
                
                EXPECTED_OUTPUT_HTML_STR_CHOICES = [
                    # html.parser
                                '''<script src="http://localhost:2797/_/https/example.com/script.js"></script>''',
                    # lxml
                    '''<html><head><script src="http://localhost:2797/_/https/example.com/script.js"></script></head></html>''',
                ]
                assert str(doc) in EXPECTED_OUTPUT_HTML_STR_CHOICES
                assert 'integrity' not in str(doc)
            
            with subtests.test(tag='link', html_parser_type=html_parser_type):
                (doc, (link,)) = _parse_html_and_links(
                    b'<link crossorigin="anonymous" href="https://use.fontawesome.com/releases/v5.12.1/css/all.css" integrity="sha384-v8BU367qNbs/aIZIxuivaU55N5GPF89WBerHoGA4QTcbUjYiLQtKdrfXnqAcXyTv" media="all" rel="stylesheet" type="text/css"/>',
                    html_parser_type=html_parser_type)
                assert (
                    'https://use.fontawesome.com/releases/v5.12.1/css/all.css',
                    'Stylesheet', None, True
                ) == (
                    link.relative_url, link.type_title, link.title, link.embedded,
                )
                
                link.relative_url = 'http://localhost:2797/_/https/use.fontawesome.com/releases/v5.12.1/css/all.css'
                
                EXPECTED_OUTPUT_HTML_STR_CHOICES = [
                    # html.parser
                                '''<link crossorigin="anonymous" href="http://localhost:2797/_/https/use.fontawesome.com/releases/v5.12.1/css/all.css" media="all" rel="stylesheet" type="text/css"/>''',
                    # lxml
                    '''<html><head><link crossorigin="anonymous" href="http://localhost:2797/_/https/use.fontawesome.com/releases/v5.12.1/css/all.css" media="all" rel="stylesheet" type="text/css"></head></html>''',
                ]
                assert str(doc) in EXPECTED_OUTPUT_HTML_STR_CHOICES
                assert 'integrity' not in str(doc)


# === Utility ===

def _parse_html_and_links(
        html_bytes: bytes, 
        *, declared_charset: str | None=None,
        html_parser_type: HtmlParserType,
        ) -> 'Tuple[Document, List[Link]]':
    result = try_parse_html_and_links(html_bytes, declared_charset, html_parser_type)
    assert result is not None
    return result
