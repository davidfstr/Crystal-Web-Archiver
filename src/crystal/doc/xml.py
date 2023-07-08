"""
Parses XML documents.
"""

from __future__ import annotations

from bs4 import BeautifulSoup
from crystal.doc.generic import Document, Link
from crystal.doc.html.soup import HtmlDocument, HtmlLink
from crystal.metasoup import BeautifulSoupFacade
from io import BytesIO
import re
from typing import List, Optional


def parse_xml_and_links(
        xml_bytes: BytesIO, 
        declared_charset: str=None
        ) -> Optional[tuple[Document, list[Link]]]:
    try:
        xml = BeautifulSoupFacade(BeautifulSoup(
            xml_bytes,
            from_encoding=declared_charset,
            features='xml',
        ))
    except Exception as e:
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
    return (HtmlDocument(xml), links_)

