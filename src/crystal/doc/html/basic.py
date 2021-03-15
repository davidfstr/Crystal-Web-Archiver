"""
HTML parser implementation that uses regular expressions.
"""

from crystal.doc.generic import Document, Link
import re

def parse_html_and_links(html_bytes, declared_charset=None):
    if not isinstance(html_bytes, str):
        raise ValueError('This parser implementation only accepts bytestrings.')
    
    dividers_and_urls = re.split(r'(?i)([\'"][^\'"]+\.s?html?[\'"])', html_bytes)
    
    dividers_and_links = []
    links = []
    for i, old_item in enumerate(dividers_and_urls):
        if i & 1 == 0:
            new_item = old_item
        else:
            new_item = BasicLink(old_item)
            links.append(new_item)
        
        dividers_and_links.append(new_item)
    
    return (BasicHtmlDocument(dividers_and_links), links)

class BasicHtmlDocument(Document):
    def __init__(self, dividers_and_links):
        self._dividers_and_links = dividers_and_links
    
    def __str__(self):
        return ''.join([str(item) for item in self._dividers_and_links])

class BasicLink(Link):
    def __init__(self, quoted_href):
        self._quoted_href = quoted_href
        
        self.title = None
        self.type_title = 'Unknown'
        self.embedded = False
    
    def _get_relative_url(self):
        return self._quoted_href[1:-1]
    def _set_relative_url(self, value):
        self._quoted_href = '"%s"' % value
    relative_url = property(_get_relative_url, _set_relative_url)
    
    # Simplifies BasicHtmlDocument's __str__ method implementation
    def __str__(self):
        return self._quoted_href
