"""
Parses HTML documents.
"""

from __future__ import annotations

from crystal.doc.generic import Document, Link
from typing import BinaryIO, Literal, Tuple

# HTML parsing library to use. See comparison between options at: 
# https://beautiful-soup-4.readthedocs.io/en/latest/#installing-a-parser
HtmlParserType = Literal['lxml', 'html_parser']

HTML_PARSER_TYPE_CHOICES = (
    HtmlParserType.__args__  # type: ignore[attr-defined]
)  # type: Tuple[HtmlParserType, ...]


def parse_html_and_links(
        html_bytes: bytes | BinaryIO,
        declared_charset: str | None,
        parser_type: HtmlParserType,
        ) -> tuple[Document, list[Link]] | None:
    """
    Parses the specified HTML bytestring, returning a 2-tuple containing
    (1) the HTML document and
    (2) a list of mutable links.
    
    The HTML document can be reoutput by getting its str() representation.
    
    Each link has the following mutable properties:
    * relative_url : str -- URL or URI referenced by this link, often relative.
    * type_title : str -- displayed title for this link's type.
    * title : str -- displayed title for this link, or None.
    * embedded : bool -- whether this link refers to an embedded resource.
    
    Arguments:
    * html_bytes -- HTML bytestring or file object.
    * declared_charset -- the encoding that the HTML document is declared to be in.
    """    
    import crystal.doc.html.basic as basic
    import crystal.doc.html.soup as soup

    # Convert html_bytes to string
    if hasattr(html_bytes, 'read'):
        html_bytes = html_bytes.read()  # type: ignore[union-attr]
    assert isinstance(html_bytes, bytes)
    
    # HACK: The BeautifulSoup parser doesn't currently handle <frameset>
    #       tags correctly. So workaround with a basic parser.
    if (b'frameset' in html_bytes) or (b'FRAMESET' in html_bytes):
        return basic.parse_html_and_links(html_bytes, declared_charset)
    else:
        return soup.parse_html_and_links(
            html_bytes, declared_charset, parser_type)
