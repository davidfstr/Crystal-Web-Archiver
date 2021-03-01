"""
HTML parser implementation that uses BeautifulSoup.
"""

from bs4 import BeautifulSoup
import re

_ANY_RE = re.compile(r'.*')

_INPUT_RE = re.compile('(?i)input')
_BUTTON_RE = re.compile('(?i)button')
_ON_CLICK_RE = re.compile('(?i)([a-zA-Z]*\.(?:href|location)) *= *([\'"])([^\'"]*)[\'"] *;?$')
_BODY_RE = re.compile('(?i)body')

def parse_html_and_links(html_bytes, declared_encoding=None):
    try:
        html = BeautifulSoup(html_bytes, fromEncoding=declared_encoding)
    except Exception as e:
        # TODO: Return the underlying exception as a warning by some mechanism
        
        # If input is file object, read it directly into memory so that
        # str() can be called on it properly.
        if hasattr(html_bytes, 'read'):
            html_bytes.seek(0)
            html_bytes = html_bytes.read()
        
        return (html_bytes, [])
    
    links = []
    
    # <body background=*>
    for tag in html.findAll(_BODY_RE, background=_ANY_RE):
        relative_url = tag['background']
        embedded = True
        title = None
        type_title = 'Background Image'
        links.append(Link.create_from_tag(tag, 'background', type_title, title, embedded))
    
    # <* src=*>
    for tag in html.findAll(_ANY_RE, src=_ANY_RE):
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
    
    # <* href=*>
    for tag in html.findAll(_ANY_RE, href=_ANY_RE):
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
        elif tag.name == 'link' and (
                ('rel' in tag.attrMap and tag['rel'] in (
                    'shortcut icon',
                    'icon',
                    'apple-touch-icon')) or (
                 relative_url.endswith('.ico'))):
            title = None
            type_title = 'Icon'
            embedded = True
        else:
            title = None
            type_title = 'Unknown (%s)' % tag.name
        links.append(Link.create_from_tag(tag, 'href', type_title, title, embedded))
    
    # <input type='button' onclick='*.location = "*";'>
    # This type of link is heavily used on fanfiction.net
    for tag in html.findAll(_INPUT_RE, type=_BUTTON_RE, onclick=_ON_CLICK_RE):
        matcher = _ON_CLICK_RE.match(tag['onclick'])
        def get_attr_value(url):
            q = matcher.group(2)
            return matcher.group(1) + ' = ' + q + url + q
        
        relative_url = matcher.group(3)
        title = tag['value'] if 'value' in tag.attrMap else None
        type_title = 'Button'
        embedded = False
        links.append(Link.create_from_complex_tag(
            tag, 'onclick', type_title, title, embedded,
            relative_url, get_attr_value))
    
    return (html, links)

def _get_image_tag_title(tag):
    if 'alt' in tag.attrMap:
        return tag['alt']
    elif 'title' in tag.attrMap:
        return tag['title']
    else:
        return None

# TODO: Split this internally into three subclasses
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
        if (tag is None or attr_name is None or type_title is None or
                embedded not in (True, False)):
            raise ValueError
        return Link(None, tag, attr_name, type_title, title, embedded)
    
    @staticmethod
    def create_from_complex_tag(tag, attr_name, type_title, title, embedded,
            relative_url, get_attr_value_for_url):
        """
        See Link.create_from_tag()
        
        Extra Arguments:
        get_attr_value_for_url -- function that takes a URL and returns the appropriate
                                  value for the underlying tag's attribute.
        """
        if (tag is None or attr_name is None or not callable(get_attr_value_for_url) or 
                type_title is None or embedded not in (True, False)):
            raise ValueError
        return Link(relative_url, tag, attr_name, type_title, title, embedded, get_attr_value_for_url)
    
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
    
    def __init__(self, relative_url, tag, attr_name, type_title, title, embedded,
            get_attr_value_for_url=None):
        self._relative_url = relative_url
        self._tag = tag
        self._attr_name = attr_name
        self._get_attr_value_for_url = get_attr_value_for_url
        self.title = title
        self.type_title = type_title
        self.embedded = embedded
    
    def _get_relative_url(self):
        if self._relative_url:
            return self._relative_url
        else:
            return self._tag[self._attr_name]
    def _set_relative_url(self, value):
        if self._relative_url and not self._get_attr_value_for_url:
            self._relative_url = value
        else:
            if self._get_attr_value_for_url:
                attr_value = self._get_attr_value_for_url(value)
            else:
                attr_value = value
            self._tag[self._attr_name] = attr_value
    relative_url = property(_get_relative_url, _set_relative_url)
    
    def __repr__(self):
        return 'Link(%s,%s,%s,%s)' % (repr(self.relative_url), repr(self.type_title), repr(self.title), repr(self.embedded))
