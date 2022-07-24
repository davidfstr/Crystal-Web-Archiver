"""
Parses XML documents.
"""

from __future__ import annotations

from bs4 import BeautifulSoup
from crystal.doc.generic import Document, Link
from crystal.doc.html.soup import HtmlDocument, HtmlLink
from io import BytesIO
import re
from typing import Optional


_LINK_RE = re.compile(r'(?i)link')


def parse_xml_and_links(
        xml_bytes: BytesIO, 
        declared_charset: str=None
        ) -> Optional[tuple[Document, list[Link]]]:
    try:
        xml = BeautifulSoup(
            xml_bytes,
            from_encoding=declared_charset,
            features='xml',
        )
    except Exception as e:
        return None
    
    links = []
    
    # <link>*</link> (from RSS feed)
    # <link href=*> (from Atom feed)
    type_title = 'Link'
    title = None
    embedded = False
    for tag in xml.findAll(_LINK_RE):
        if tag.string not in [None, '']:
            links.append(HtmlLink.create_from_tag(tag, 'string', type_title, title, embedded))
        if 'href' in tag.attrs:  # usually also has: rel="alternate"
            links.append(HtmlLink.create_from_tag(tag, 'href', type_title, title, embedded))
    
    return (HtmlDocument(xml), links)

