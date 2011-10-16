"""
Tools for examining HTML resources.
"""

from BeautifulSoup import BeautifulSoup
import re

class LinkParser(object):
    _any_re = re.compile(r'.*')
    
    # TODO: Promote to top-level function, since this class isn't carrying its weight
    @staticmethod
    def parse(html_bytes):
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
        
        tags_with_src = html.findAll(LinkParser._any_re, src=LinkParser._any_re)
        tags_with_href = html.findAll(LinkParser._any_re, href=LinkParser._any_re)
        
        links = []
        for tag in tags_with_src:
            # TODO: Need to resolve URLs to be absolute
            url = tag['src']
            if tag.name == 'img':
                title = LinkParser._get_image_tag_title(tag)
                links.append(Link(url, title, 'Image', True))
            elif tag.name == 'frame':
                title = tag['name'] if 'name' in tag.attrMap else None
                links.append(Link(url, title, 'Frame', True))
            elif tag.name == 'input' and 'type' in tag.attrMap and tag['type'] == 'image':
                title = LinkParser._get_image_tag_title(tag)
                links.append(Link(url, title, 'Form Image', True))
            else:
                title = None
                links.append(Link(url, title, 'Unknown Embedded (%s)' % (tag.name,), True))
        for tag in tags_with_href:
            # TODO: Need to resolve URLs to be absolute
            url = tag['href']
            if tag.name == 'a':
                title = tag.string
                links.append(Link(url, title, 'Link', False))
            elif tag.name == 'link' and (
                    ('rel' in tag.attrMap and tag['rel'] == 'stylesheet') or (
                     'type' in tag.attrMap and tag['type'] == 'text/css') or (
                     url.endswith('.css'))):
                title = None
                links.append(Link(url, title, 'Stylesheet', True))
            else:
                title = None
                links.append(Link(url, title, 'Unknown (%s)' % (tag.name,), False))
        
        return links
    
    @staticmethod
    def _get_image_tag_title(tag):
        if 'alt' in tag.attrMap:
            return tag['alt']
        elif 'title' in tag.attrMap:
            return tag['title']
        else:
            return None

class Link(object):
    def __init__(self, url, title, type_title, embedded):
        """
        Arguments:
        url - URL or URI referenced by this link.
        title - displayed title for this link, or None.
        type_title - displayed title for this link's type.
        embedded - whether this link refers to an embedded resource.
        """
        if url is None or type_title is None or embedded not in (True, False):
            raise ValueError
        self.url = url
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
        return 'Link(%s,%s,%s,%s)' % (repr(self.url), repr(self.title), repr(self.type_title), repr(self.embedded))
