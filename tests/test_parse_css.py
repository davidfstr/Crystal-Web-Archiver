from crystal.doc.css import CssDocument
from crystal.doc.css import parse_css_and_links as try_parse_css_and_links
from crystal.doc.generic import Document, Link
from textwrap import dedent
from typing import List, Optional, Tuple
from unittest import skip

# === Tests ===

# TODO: Extend each "test_recognizes_*" to also test WRITING
#       to the relative_url of the output link to ensure it
#       gets saves in a reasonable way.

def test_can_parse_and_format_basic_css_document() -> None:
    INPUT_CSS_BYTES = dedent(
        """
        html {
            background-color: cyan;
        }
        """
    ).lstrip('\n').encode('utf-8')
    EXPECTED_OUTPUT_CSS_STR = dedent(
        """
        html {
            background-color: cyan;
        }
        """
    ).lstrip('\n')
    
    (doc, _) = _parse_css_and_links(INPUT_CSS_BYTES)
    
    assert isinstance(doc, CssDocument)
    assert EXPECTED_OUTPUT_CSS_STR == str(doc)


def test_recognizes_url_token_link() -> None:
    (_, (link,)) = _parse_css_and_links(
        """body { background: url(background.png) }""".encode('utf-8'))
    assert 'background.png' == link.relative_url
    assert 'CSS URL Reference' == link.type_title
    assert True == link.embedded


def test_recognizes_url_function_link() -> None:
    (_, (link,)) = _parse_css_and_links(
        """body { background: url("background.png") }""".encode('utf-8'))
    assert 'background.png' == link.relative_url
    assert 'CSS URL Reference' == link.type_title
    assert True == link.embedded


def test_recognizes_import_string_link() -> None:
    (_, (link,)) = _parse_css_and_links(
        """@import "page.js" """.encode('utf-8'))
    assert 'page.js' == link.relative_url
    assert 'CSS @import' == link.type_title
    assert True == link.embedded


# === Utility ===

def _parse_css_and_links(
        css_bytes: bytes, 
        *, declared_charset: Optional[str]=None,
        ) -> 'Tuple[Document, List[Link]]':
    result = try_parse_css_and_links(css_bytes, declared_charset)
    assert result is not None
    return result
