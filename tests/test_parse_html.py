from crystal.doc.generic import Document, Link
from crystal.doc.html import HtmlParserType, HTML_PARSER_TYPE_CHOICES
from crystal.doc.html import parse_html_and_links as try_parse_html_and_links
from crystal.doc.html.soup import HtmlDocument
from crystal.tests.util.subtests import SubtestsContext, with_subtests
from textwrap import dedent
from typing import List, Optional, Tuple

# === Tests ===

# TODO: Extend each "test_recognizes_*" to also test WRITING
#       to the relative_url of the output link to ensure it
#       gets saves in a reasonable way.

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


def test_recognizes_body_background_link() -> None:
    with SubtestsContext('test_recognizes_body_background_link').run() as subtests:
        for html_parser_type in HTML_PARSER_TYPE_CHOICES:
            with subtests.test(html_parser_type=html_parser_type):
                (_, (link,)) = _parse_html_and_links(
                    """<body background="background.png"></body>""".encode('utf-8'),
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
                    """<img src="background.png" title="Background" />""".encode('utf-8'),
                    html_parser_type=html_parser_type)
                assert 'background.png' == link.relative_url
                assert 'Image' == link.type_title
                assert 'Background' == link.title
                assert True == link.embedded
                
                # <iframe src=*>
                (_, (link,)) = _parse_html_and_links(
                    """<iframe src="content.html" name="content"></iframe>""".encode('utf-8'),
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
                    """<frame src="content.html" name="content"></frame>""".encode('utf-8'),
                    html_parser_type=html_parser_type)
                assert 'content.html' == link.relative_url
                assert 'Frame' == link.type_title
                assert 'content' == link.title
                assert True == link.embedded
                
                # <input type="image" src=*>
                (_, (link,)) = _parse_html_and_links(
                    """<input type="image" src="login-button.png" alt="Login" />""".encode('utf-8'),
                    html_parser_type=html_parser_type)
                assert 'login-button.png' == link.relative_url
                assert 'Form Image' == link.type_title
                assert 'Login' == link.title
                assert True == link.embedded
                
                # <??? src=*>
                (_, (link,)) = _parse_html_and_links(
                    """<div src="image.png"></div>""".encode('utf-8'),
                    html_parser_type=html_parser_type)
                assert 'image.png' == link.relative_url
                assert 'Unknown Embedded (div)' == link.type_title
                assert None == link.title
                assert True == link.embedded


def test_recognizes_img_srcset() -> None:
    with SubtestsContext('test_recognizes_img_srcset').run() as subtests:
        for html_parser_type in HTML_PARSER_TYPE_CHOICES:
            with subtests.test(html_parser_type=html_parser_type):
                (_, (link1, link2)) = _parse_html_and_links(dedent(
                    """
                    <img
                        src="clock-demo-200px.png"
                        alt="Clock"
                        srcset="clock-demo-400px.png 2x" />
                    """).lstrip('\n').encode('utf-8'),
                    html_parser_type=html_parser_type)
                
                assert 'clock-demo-200px.png' == link1.relative_url
                assert 'Image' == link1.type_title
                assert 'Clock' == link1.title
                assert True == link1.embedded
                
                assert 'clock-demo-400px.png' == link2.relative_url
                assert 'Image' == link2.type_title
                assert 'Clock' == link2.title
                assert True == link2.embedded


def test_recognizes_href_attribute() -> None:
    with SubtestsContext('test_recognizes_href_attribute').run() as subtests:
        for html_parser_type in HTML_PARSER_TYPE_CHOICES:
            with subtests.test(html_parser_type=html_parser_type):
                # <a href=*>
                (_, (link,)) = _parse_html_and_links(
                    """<a href="https://example.com">Website</a>""".encode('utf-8'),
                    html_parser_type=html_parser_type)
                assert 'https://example.com' == link.relative_url
                assert 'Link' == link.type_title
                assert 'Website' == link.title
                assert False == link.embedded
                
                # <link rel="stylesheet" href=*>
                (_, (link,)) = _parse_html_and_links(
                    """<link rel="stylesheet" href="styles" />""".encode('utf-8'),
                    html_parser_type=html_parser_type)
                assert 'styles' == link.relative_url
                assert 'Stylesheet' == link.type_title
                assert None == link.title
                assert True == link.embedded
                
                # <link type="text/css" href=*>
                (_, (link,)) = _parse_html_and_links(
                    """<link type="text/css" href="styles" />""".encode('utf-8'),
                    html_parser_type=html_parser_type)
                assert 'styles' == link.relative_url
                assert 'Stylesheet' == link.type_title
                assert None == link.title
                assert True == link.embedded
                
                # <link href="*.css">
                (_, (link,)) = _parse_html_and_links(
                    """<link href="styles.css" />""".encode('utf-8'),
                    html_parser_type=html_parser_type)
                assert 'styles.css' == link.relative_url
                assert 'Stylesheet' == link.type_title
                assert None == link.title
                assert True == link.embedded
                
                # <link rel="shortcut icon" href=*>
                (_, (link,)) = _parse_html_and_links(
                    """<link rel="shortcut icon" href="favicon.ico" />""".encode('utf-8'),
                    html_parser_type=html_parser_type)
                assert 'favicon.ico' == link.relative_url
                assert 'Icon' == link.type_title
                assert None == link.title
                assert True == link.embedded
                
                # <link rel="icon" href=*>
                (_, (link,)) = _parse_html_and_links(
                    """<link rel="icon" href="favicon.ico" />""".encode('utf-8'),
                    html_parser_type=html_parser_type)
                assert 'favicon.ico' == link.relative_url
                assert 'Icon' == link.type_title
                assert None == link.title
                assert True == link.embedded
                
                # <link rel="apple-touch-icon" href=*>
                (_, (link,)) = _parse_html_and_links(
                    """<link rel="apple-touch-icon" href="appicon.png" />""".encode('utf-8'),
                    html_parser_type=html_parser_type)
                assert 'appicon.png' == link.relative_url
                assert 'Icon' == link.type_title
                assert None == link.title
                assert True == link.embedded

                # <??? href=*>
                (_, (link,)) = _parse_html_and_links(
                    """<div href="image.png"></div>""".encode('utf-8'),
                    html_parser_type=html_parser_type)
                assert 'image.png' == link.relative_url
                assert 'Unknown Href (div)' == link.type_title
                assert None == link.title
                assert False == link.embedded


def test_recognizes_input_button_onclick() -> None:
    with SubtestsContext('test_recognizes_input_button_onclick').run() as subtests:
        for html_parser_type in HTML_PARSER_TYPE_CHOICES:
            with subtests.test(html_parser_type=html_parser_type):
                # <input type='button' onclick='*.location = "*";'>
                (_, (link,)) = _parse_html_and_links(
                    """<input type='button' onclick='window.location = "http://example.com/";' value='Example'>""".encode('utf-8'),
                    html_parser_type=html_parser_type)
                assert 'http://example.com/' == link.relative_url
                assert 'Button' == link.type_title
                assert 'Example' == link.title
                assert False == link.embedded


def test_recognizes_javascript_with_absolute_or_site_relative_url() -> None:
    with SubtestsContext('test_recognizes_javascript_with_absolute_or_site_relative_url').run() as subtests:
        for html_parser_type in HTML_PARSER_TYPE_CHOICES:
            with subtests.test(html_parser_type=html_parser_type):
                # <script [type="text/javascript"]>..."http(s)://**"...</script>
                if True:
                    (_, (link,)) = _parse_html_and_links(
                        """<script>const url = "http://example.com/"; window.location = url;</script>""".encode('utf-8'),
                        html_parser_type=html_parser_type)
                    assert 'http://example.com/' == link.relative_url
                    assert 'Script Reference' == link.type_title
                    assert None == link.title
                    assert False == link.embedded
                    
                    (_, (link,)) = _parse_html_and_links(
                        """<script>const url = "http://example.com/poster.png"; window.location = url;</script>""".encode('utf-8'),
                        html_parser_type=html_parser_type)
                    assert 'http://example.com/poster.png' == link.relative_url
                    assert 'Script Reference' == link.type_title
                    assert None == link.title
                    assert True == link.embedded
                    
                    (_, ()) = _parse_html_and_links(
                        """<script type="x-json">["http://example.com/"]</script>""".encode('utf-8'),
                        html_parser_type=html_parser_type)
                
                # <script [type="text/javascript"]>..."//**"...</script>
                if True:
                    (_, (link,)) = _parse_html_and_links(
                        """<script>const url = "//home.html"; window.location = url;</script>""".encode('utf-8'),
                        html_parser_type=html_parser_type)
                    assert '//home.html' == link.relative_url
                    assert 'Script Reference' == link.type_title
                    assert None == link.title
                    assert False == link.embedded
                    
                    (_, (link,)) = _parse_html_and_links(
                        """<script>const url = "//poster.png"; window.location = url;</script>""".encode('utf-8'),
                        html_parser_type=html_parser_type)
                    assert '//poster.png' == link.relative_url
                    assert 'Script Reference' == link.type_title
                    assert None == link.title
                    assert True == link.embedded
                    
                    (_, ()) = _parse_html_and_links(
                        """<script type="x-json">["//home.html"]</script>""".encode('utf-8'),
                        html_parser_type=html_parser_type)


def test_recognizes_unknown_attribute_with_absolute_url() -> None:
    with SubtestsContext('test_recognizes_unknown_attribute_with_absolute_url').run() as subtests:
        for html_parser_type in HTML_PARSER_TYPE_CHOICES:
            with subtests.test(html_parser_type=html_parser_type):
                # <* *="http(s)://**">
                if True:
                    (_, (link,)) = _parse_html_and_links(
                        """<a data-src="https://squarespace.com/">Logo</a>""".encode('utf-8'),
                        html_parser_type=html_parser_type)
                    assert 'https://squarespace.com/' == link.relative_url
                    assert 'Attribute Reference' == link.type_title
                    assert None == link.title
                    assert False == link.embedded
                    
                    (_, (link,)) = _parse_html_and_links(
                        """<img data-src="https://images.squarespace-cdn.com/calm+circle+logo.png" />""".encode('utf-8'),
                        html_parser_type=html_parser_type)
                    assert 'https://images.squarespace-cdn.com/calm+circle+logo.png' == link.relative_url
                    assert 'Attribute Reference' == link.type_title
                    assert None == link.title
                    assert True == link.embedded


# === Utility ===

def _parse_html_and_links(
        html_bytes: bytes, 
        *, declared_charset: Optional[str]=None,
        html_parser_type: HtmlParserType,
        ) -> 'Tuple[Document, List[Link]]':
    result = try_parse_html_and_links(html_bytes, declared_charset, html_parser_type)
    assert result is not None
    return result
