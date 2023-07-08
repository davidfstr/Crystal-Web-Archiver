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
    
    links_ = links  # type: List[Link]  # type: ignore[assignment]  # allow List[HtmlLink] to be converted
    return (HtmlDocument(BeautifulSoupFacade(xml)), links_)

