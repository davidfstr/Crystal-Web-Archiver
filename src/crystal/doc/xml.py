"""
Parses XML documents.
"""

from bs4 import BeautifulSoup
from crystal.doc.generic import Document, Link
from crystal.doc.html.soup import HtmlDocument, HtmlLink
from crystal.util.fastsoup import BeautifulFastSoup
from typing import BinaryIO, List


def parse_xml_and_links(
        xml_bytes: BinaryIO,
        declared_charset: str | None=None
        ) -> tuple[Document, list[Link]] | None:
    """
    Parses an XML document, returning a FastSoup object that can be
    examined through a BeautifulSoup-compatible API.
    
    Returns None if there was a parsing error.
    """
    try:
        xml = BeautifulFastSoup(BeautifulSoup(
            xml_bytes,
            from_encoding=declared_charset,
            features='xml',
        ))
    except Exception:
        return None
    
    links = []
    
    # <link>*</link> (from RSS feed)
    # <link href=*> (from Atom feed)
    type_title = 'Link'
    title = None
    embedded = False
    for tag in xml.find_all('link'):
        if xml.tag_string(tag) not in [None, '']:
            links.append(HtmlLink.create_from_tag(tag, xml, 'string', type_title, title, embedded))
        if 'href' in  xml.tag_attrs(tag):  # usually also has: rel="alternate"
            links.append(HtmlLink.create_from_tag(tag, xml, 'href', type_title, title, embedded))
    
    links_ = links  # type: List[Link]  # type: ignore[assignment]  # allow List[HtmlLink] to be converted
    return (HtmlDocument(xml, is_html=False), links_)

