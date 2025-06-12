"""
HTML parser implementation that uses regular expressions.
"""

from __future__ import annotations

from crystal.doc.generic import Document, Link
import re


def parse_html_and_links(
        html_bytes: bytes, 
        declared_charset: str | None=None
        ) -> tuple[Document, list[Link]]:
    if not isinstance(html_bytes, bytes):
        raise ValueError('This parser implementation only accepts bytestrings.')
    # TODO: Attempt to honor the declared_charset rather than always assuming UTF-8.
    #       Recommend using the webencodings package (already a dependency) to map
    #       internet charset names to Python encoding names.
    html = html_bytes.decode('utf-8', errors='replace')
    
    dividers_and_urls = re.split(r'(?i)([\'"][^\'"]+\.s?html?[\'"])', html)
    
    dividers_and_links = []
    links = []  # type: list[Link]
    for (i, old_item) in enumerate(dividers_and_urls):
        if i & 1 == 0:
            new_item = old_item
        else:
            new_item = BasicLink(old_item)
            links.append(new_item)
        
        dividers_and_links.append(new_item)
    
    return (BasicDocument(dividers_and_links), links)


class BasicDocument(Document):
    def __init__(self, dividers_and_links: list[str | BasicLink]) -> None:
        self._dividers_and_links = dividers_and_links
    
    def __str__(self) -> str:
        return ''.join([str(item) for item in self._dividers_and_links])


class BasicLink(Link):
    def __init__(self, quoted_href: str) -> None:
        if not (len(quoted_href) >= 2 and 
                quoted_href[0] in ('\'', '\"') and 
                quoted_href[-1] == quoted_href[0]):
            raise ValueError()
        self._quoted_href = quoted_href
        
        self.title = None
        self.type_title = 'Unknown'
        self.embedded = False
    
    def _get_relative_url(self) -> str:
        return self._quoted_href[1:-1]
    def _set_relative_url(self, value: str) -> None:
        self._quoted_href = '"%s"' % value
    relative_url = property(_get_relative_url, _set_relative_url)
    
    # Simplifies BasicDocument's __str__ method implementation
    def __str__(self) -> str:
        return self._quoted_href
