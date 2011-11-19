"""
Tools for examining HTML resources.
"""

from BeautifulSoup import BeautifulSoup
import re

_ANY_RE = re.compile(r'.*')

def parse_links(html_bytes, declared_encoding=None):
    """
    Parses the specified HTML bytestring, returning a list of Links.
    
    Arguments:
    html_bytes -- HTML bytestring or file object.
    declared_encoding -- the encoding that the HTML document is declared to be in.
    """
    (html, links) = parse_html_and_links(html_bytes, declared_encoding)
    return links

def parse_html_and_links(html_bytes, declared_encoding=None):
    """
    Parses the specified HTML bytestring, returning a 2-tuple containing
    (1) the HTML document and
    (2) a list of Links.
    
    The HTML document can be reoutput by getting its str() representation.
    
    This parse method is useful over parse_links() when the parsed links
    need to be modified and the document reoutput.
    
    Arguments:
    html_bytes -- HTML bytestring or file object.
    declared_encoding -- the encoding that the HTML document is declared to be in.
    """
    try:
        html = BeautifulSoup(html_bytes, fromEncoding=declared_encoding)
    except Exception as e:
        # TODO: Return the underlying exception as a warning
        return (html_bytes, [])
    
    tags_with_src = html.findAll(_ANY_RE, src=_ANY_RE)
    tags_with_href = html.findAll(_ANY_RE, href=_ANY_RE)
    
    links = []
    for tag in tags_with_src:
        relative_url = tag['src']
        embedded = True
        if tag.name == 'img':
            title = _get_image_tag_title(tag)
            type_title = 'Image'
        elif tag.name == 'frame':
            title = tag['name'] if 'name' in tag.attrMap else None
            type_title = 'Frame'
        elif tag.name == 'input' and 'type' in tag.attrMap and tag['type'] == 'image':
            title = _get_image_tag_title(tag)
            type_title = 'Form Image'
        else:
            title = None
            type_title = 'Unknown Embedded (%s)' % tag.name
        links.append(Link.create_from_tag(tag, 'src', type_title, title, embedded))
    
    for tag in tags_with_href:
        relative_url = tag['href']
        embedded = False
        if tag.name == 'a':
            title = tag.string
            type_title = 'Link'
        elif tag.name == 'link' and (
                ('rel' in tag.attrMap and tag['rel'] == 'stylesheet') or (
                 'type' in tag.attrMap and tag['type'] == 'text/css') or (
                 relative_url.endswith('.css'))):
            title = None
            type_title = 'Stylesheet'
            embedded = True
        else:
            title = None
            type_title = 'Unknown (%s)' % tag.name
        links.append(Link.create_from_tag(tag, 'href', type_title, title, embedded))
    
    return (html, links)

def _get_image_tag_title(tag):
    if 'alt' in tag.attrMap:
        return tag['alt']
    elif 'title' in tag.attrMap:
        return tag['title']
    else:
        return None

class Link(object):
    """
    Represents a link in a (usually-HTML) resource.
    """
    @staticmethod
    def create_from_tag(tag, attr_name, type_title, title, embedded):
        """
        Creates a link that is derived from the attribute of an HTML element.
        
        Arguments:
        relative_url - URL or URI referenced by this link, often relative.
        type_title - displayed title for this link's type.
        title - displayed title for this link, or None.
        embedded - whether this link refers to an embedded resource.
        """
        if tag is None or attr_name is None or type_title is None or embedded not in (True, False):
            raise ValueError
        return Link(None, tag, attr_name, type_title, title, embedded)
    
    @staticmethod
    def create_external(relative_url, type_title, title, embedded):
        """
        Creates a external link that is not reflected in the original HTML content.
        
        Arguments:
        relative_url - URL or URI referenced by this link, often relative.
        type_title - displayed title for this link's type.
        title - displayed title for this link, or None.
        embedded - whether this link refers to an embedded resource.
        """
        if relative_url is None or type_title is None or embedded not in (True, False):
            raise ValueError
        return Link(relative_url, None, None, type_title, title, embedded)
    
    def __init__(self, relative_url, tag, attr_name, type_title, title, embedded):
        self._relative_url = relative_url
        self._tag = tag
        self._attr_name = attr_name
        self.title = title
        self.type_title = type_title
        self.embedded = embedded
    
    def _get_relative_url(self):
        if self._relative_url:
            return self._relative_url
        else:
            return self._tag[self._attr_name]
    def _set_relative_url(self, value):
        if self._relative_url:
            self._relative_url = value
        else:
            self._tag[self._attr_name] = value
    relative_url = property(_get_relative_url, _set_relative_url)
    
    @property
    def full_title(self):
        if self.title:
            return '%s: %s' % (self.type_title, self.title)
        else:
            return '%s' % self.type_title
    
    def __repr__(self):
        return 'Link(%s,%s,%s,%s)' % (repr(self.relative_url), repr(self.type_title), repr(self.title), repr(self.embedded))
