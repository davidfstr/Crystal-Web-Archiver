"""
Tools for examining HTML resources.
"""

from BeautifulSoup import BeautifulSoup
import re

_ANY_RE = re.compile(r'.*')

def parse_links(html_bytes):
    """
    Parses and returns a list of `Link`s in the specified HTML bytestring.
    """
    # TODO: Pass in the hinted Content-Encoding HTTP header, if available,
    #       to assist in determining the correct text encoding
    try:
        html = BeautifulSoup(html_bytes)
    except Exception as e:
        # TODO: Return the underlying exception as a warning
        return []
    
    tags_with_src = html.findAll(_ANY_RE, src=_ANY_RE)
    tags_with_href = html.findAll(_ANY_RE, href=_ANY_RE)
    
    links = []
    for tag in tags_with_src:
        relative_url = tag['src']
        if tag.name == 'img':
            title = _get_image_tag_title(tag)
            links.append(Link(relative_url, 'Image', title, True))
        elif tag.name == 'frame':
            title = tag['name'] if 'name' in tag.attrMap else None
            links.append(Link(relative_url, 'Frame', title, True))
        elif tag.name == 'input' and 'type' in tag.attrMap and tag['type'] == 'image':
            title = _get_image_tag_title(tag)
            links.append(Link(relative_url, 'Form Image', title, True))
        else:
            title = None
            links.append(Link(relative_url, 'Unknown Embedded (%s)' % tag.name, title, True))
    for tag in tags_with_href:
        # TODO: Need to resolve URLs to be absolute
        relative_url = tag['href']
        if tag.name == 'a':
            title = tag.string
            links.append(Link(relative_url, 'Link', title, False))
        elif tag.name == 'link' and (
                ('rel' in tag.attrMap and tag['rel'] == 'stylesheet') or (
                 'type' in tag.attrMap and tag['type'] == 'text/css') or (
                 relative_url.endswith('.css'))):
            title = None
            links.append(Link(relative_url, 'Stylesheet', title, True))
        else:
            title = None
            links.append(Link(relative_url, 'Unknown (%s)' % tag.name, title, False))
    
    return links

def _get_image_tag_title(tag):
    if 'alt' in tag.attrMap:
        return tag['alt']
    elif 'title' in tag.attrMap:
        return tag['title']
    else:
        return None

class Link(object):
    def __init__(self, relative_url, type_title, title, embedded):
        """
        Arguments:
        relative_url - URL or URI referenced by this link, often relative.
        type_title - displayed title for this link's type.
        title - displayed title for this link, or None.
        embedded - whether this link refers to an embedded resource.
        """
        if relative_url is None or type_title is None or embedded not in (True, False):
            raise ValueError
        self.relative_url = relative_url
        self.title = title
        self.type_title = type_title
        self.embedded = embedded
    
    @property
    def full_title(self):
        if self.title:
            return '%s: %s' % (self.type_title, self.title)
        else:
            return '%s' % self.type_title
    
    def __repr__(self):
        return 'Link(%s,%s,%s,%s)' % (repr(self.relative_url), repr(self.type_title), repr(self.title), repr(self.embedded))
