"""
HTML parser implementation that uses BeautifulSoup.
"""

from __future__ import annotations

from bs4 import BeautifulSoup
from crystal.doc.generic import Document, Link
import json
import re
from typing import Optional
from urllib.parse import urlparse


_ANY_RE = re.compile(r'.*')

_INPUT_RE = re.compile(r'(?i)input')
_BUTTON_RE = re.compile(r'(?i)button')
# TODO: Make this an r'...' string
_ON_CLICK_RE = re.compile('(?i)([a-zA-Z]*\.(?:href|location)) *= *([\'"])([^\'"]*)[\'"] *;?$')
_BODY_RE = re.compile(r'(?i)body')
_SCRIPT_RE = re.compile(r'(?i)script')
_TEXT_JAVASCRIPT_RE = re.compile(r'(?i)^text/javascript$')
_QUOTED_HTTP_LINK_RE = re.compile(r'''(?i)(?:(")((?:https?:)?\\?/\\?/[^/][^"]+)"|(')((?:https?:)?\\?/\\?/[^/][^']+)')''')
ABSOLUTE_HTTP_LINK_RE = re.compile(r'''(?i)^(https?://.+)$''')

PROBABLE_EMBEDDED_URL_RE = re.compile(r'(?i)\.(gif|jpe?g|svg|js|css)$')


def parse_html_and_links(
        html_bytes: bytes, 
        declared_charset: Optional[str]=None
        ) -> 'Optional[tuple[HtmlDocument, list[HtmlLink]]]':
    try:
        html = BeautifulSoup(
            html_bytes,
            from_encoding=declared_charset,
            # TODO: Consider migrating to 'lxml' parser for additional speed
            features='html.parser',
        )
    except Exception as e:
        return None
    
    links = []
    
    # <* background=*>
    for tag in html.findAll(_ANY_RE, background=_ANY_RE):
        embedded = True
        title = None
        type_title = 'Background Image'
        links.append(HtmlLink.create_from_tag(tag, 'background', type_title, title, embedded))
    
    # <* src=*>
    for tag in html.findAll(_ANY_RE, src=_ANY_RE):
        embedded = True
        if tag.name == 'img':
            title = _get_image_tag_title(tag)
            type_title = 'Image'
        elif tag.name == 'frame':
            title = tag['name'] if 'name' in tag.attrs else None
            type_title = 'Frame'
        elif tag.name == 'input' and 'type' in tag.attrs and tag['type'] == 'image':
            title = _get_image_tag_title(tag)
            type_title = 'Form Image'
        else:
            title = None
            type_title = 'Unknown Embedded (%s)' % tag.name
        links.append(HtmlLink.create_from_tag(tag, 'src', type_title, title, embedded))
    
    # <* href=*>
    for tag in html.findAll(_ANY_RE, href=_ANY_RE):
        relative_url = tag['href']
        relative_url_path = urlparse(relative_url).path
        embedded = False
        if tag.name == 'a':
            title = tag.string
            type_title = 'Link'
        elif tag.name == 'link' and (
                ('rel' in tag.attrs and 'stylesheet' in tag['rel']) or (
                 'type' in tag.attrs and tag['type'] == 'text/css') or (
                 relative_url_path.endswith('.css'))):
            title = None
            type_title = 'Stylesheet'
            embedded = True
        elif tag.name == 'link' and (
                    ('rel' in tag.attrs and any([x in tag['rel'] for x in (
                        'shortcut icon',
                        'icon',
                        'apple-touch-icon')])) or 
                    (relative_url_path.endswith('.ico') or 
                        relative_url_path.endswith('.png'))
                ):
            title = None
            type_title = 'Icon'
            embedded = True
        else:
            title = None
            type_title = 'Unknown (%s)' % tag.name
        links.append(HtmlLink.create_from_tag(tag, 'href', type_title, title, embedded))
    
    # <input type='button' onclick='*.location = "*";'>
    # This type of link is used on: fanfiction.net
    for tag in html.findAll(_INPUT_RE, type=_BUTTON_RE, onclick=_ON_CLICK_RE):
        matcher = _ON_CLICK_RE.search(tag['onclick'])
        def process_match(matcher) -> None:
            def replace_url_in_old_attr_value(url, old_attr_value):
                q = matcher.group(2)
                return matcher.group(1) + ' = ' + q + url + q
            
            relative_url = matcher.group(3)
            title = tag['value'] if 'value' in tag.attrs else None
            type_title = 'Button'
            embedded = False
            links.append(HtmlLink.create_from_complex_tag(
                tag, 'onclick', type_title, title, embedded,
                relative_url, replace_url_in_old_attr_value))
        process_match(matcher)
    
    # 1. <script [type="text/javascript"]>..."http(s)://**"...</script>
    #   - This type of link is used on: http://*.daportfolio.com/
    # 2. <script [type="text/javascript"]>..."//**"...</script>
    #   - This type of link is used on: https://blog.calm.com/take-a-deep-breath
    for tag in html.findAll(_SCRIPT_RE, string=_QUOTED_HTTP_LINK_RE):
        if 'type' in tag.attrs and not _TEXT_JAVASCRIPT_RE.fullmatch(tag.attrs['type']):
            continue
        
        matches = _QUOTED_HTTP_LINK_RE.findall(tag.string)
        for match in matches:
            def process_str_match(match: str) -> None:
                q = match[0] or match[2]
                old_string_literal = q + (match[1] or match[3]) + q
                
                def replace_url_in_old_attr_value(url, old_attr_value):
                    if q == "'":
                        new_string_literal = q + json.dumps(url)[1:-1].replace(q, '\\' + q) + q
                    else:  # q == '"' or something else
                        new_string_literal = json.dumps(url)
                    
                    return old_attr_value.replace(old_string_literal, new_string_literal)
                
                try:
                    relative_url = json.loads('"' + (match[1] or match[3]) + '"')  # type: ignore[attr-defined]
                except ValueError:
                    # Failed to parse JavaScript string literal
                    return
                title = None
                type_title = 'Script Reference'
                embedded = PROBABLE_EMBEDDED_URL_RE.search(relative_url) is not None
                links.append(HtmlLink.create_from_complex_tag(
                    tag, 'string', type_title, title, embedded,
                    relative_url, replace_url_in_old_attr_value))
            process_str_match(match)
    
    # <* *="http(s)://**">
    # This type of link is used on: https://blog.calm.com/take-a-deep-breath
    # where the attribute name is "data-url".
    seen_tags_and_attr_names = set([(link.tag, link.attr_name) for link in links])  # capture
    for tag in html.findAll():
        for (attr_name, attr_value) in tag.attrs.items():
            if (tag, attr_name) in seen_tags_and_attr_names:
                continue
            if not isinstance(attr_value, str):
                # HACK: BeautifulSoup has been observed to provide a 
                #       List[str] value for the "class" attribute...
                continue
            matcher = ABSOLUTE_HTTP_LINK_RE.fullmatch(attr_value)
            if not matcher:
                continue
            
            relative_url = matcher.group(1)
            title = None
            type_title = 'Attribute Reference'
            embedded = PROBABLE_EMBEDDED_URL_RE.search(relative_url) is not None
            links.append(HtmlLink.create_from_tag(
                tag, attr_name, type_title, title, embedded))
    
    return (HtmlDocument(html), links)


def _get_image_tag_title(tag):
    if 'alt' in tag.attrs:
        return tag['alt']
    elif 'title' in tag.attrs:
        return tag['title']
    else:
        return None


class HtmlDocument(Document):
    def __init__(self, html: BeautifulSoup) -> None:
        self._html = html
    
    def try_insert_script(self, script_url: str) -> bool:
        first_element = self._html.find(True)
        if first_element is not None:
            script = self._html.new_tag('script')
            script['src'] = script_url
            
            first_element.insert_before(script)
            return True
        else:
            return False
    
    def __str__(self) -> str:
        return str(self._html)


# TODO: Split this internally into three subclasses
class HtmlLink(Link):
    """
    Represents a link in a (usually-HTML) resource.
    """
    @staticmethod
    def create_from_tag(tag, attr_name, type_title, title, embedded):
        """
        Creates a link that is derived from the attribute of an HTML element.
        
        Arguments:
        * relative_url - URL or URI referenced by this link, often relative.
        * type_title - displayed title for this link's type.
        * title - displayed title for this link, or None.
        * embedded - whether this link refers to an embedded resource.
        """
        if (tag is None or attr_name is None or type_title is None or
                embedded not in (True, False)):
            raise ValueError
        return HtmlLink(None, tag, attr_name, type_title, title, embedded)
    
    @staticmethod
    def create_from_complex_tag(tag, attr_name, type_title, title, embedded,
            relative_url, replace_url_in_old_attr_value):
        """
        See HtmlLink.create_from_tag()
        
        Extra Arguments:
        * replace_url_in_old_attr_value --
            function that takes a URL and returns the appropriate
            value for the underlying tag's attribute.
        """
        if (tag is None or attr_name is None or not callable(replace_url_in_old_attr_value) or 
                type_title is None or embedded not in (True, False)):
            raise ValueError
        return HtmlLink(relative_url, tag, attr_name, type_title, title, embedded, replace_url_in_old_attr_value)
    
    @staticmethod
    def create_external(relative_url, type_title, title, embedded):
        """
        Creates a external link that is not reflected in the original HTML content.
        
        Arguments:
        * relative_url - URL or URI referenced by this link, often relative.
        * type_title - displayed title for this link's type.
        * title - displayed title for this link, or None.
        * embedded - whether this link refers to an embedded resource.
        """
        if relative_url is None or type_title is None or embedded not in (True, False):
            raise ValueError
        return HtmlLink(relative_url, None, None, type_title, title, embedded)
    
    def __init__(self, relative_url, tag, attr_name, type_title, title, embedded,
            replace_url_in_old_attr_value=None):
        self._relative_url = relative_url
        self._tag = tag
        self._attr_name = attr_name
        self._replace_url_in_old_attr_value = replace_url_in_old_attr_value
        
        self.title = title
        self.type_title = type_title
        self.embedded = embedded
    
    def _get_relative_url(self):
        if self._relative_url:
            return self._relative_url
        else:
            # NOTE: Immediately strip whitespace from relative URLs inside HTML tags,
            #       before they are resolved against any base URL. Both preceding
            #       and trailing whitespace has been observed in the wild.
            return self._attr_value.strip()
    def _set_relative_url(self, url):
        if self._relative_url and not self._replace_url_in_old_attr_value:
            self._relative_url = url
        else:
            if self._replace_url_in_old_attr_value:
                attr_value = self._replace_url_in_old_attr_value(url, self._attr_value)
            else:
                attr_value = url
            self._attr_value = attr_value
    relative_url = property(_get_relative_url, _set_relative_url)
    
    @property
    def tag(self):
        return self._tag
    
    @property
    def attr_name(self):
        return self._attr_name
    
    def _get_attr_value(self):
        if self._attr_name == 'string':
            return self._tag.string
        else:
            return self._tag[self._attr_name]
    def _set_attr_value(self, attr_value):
        if self._attr_name == 'string':
            self._tag.string = attr_value
        else:
            self._tag[self._attr_name] = attr_value
    _attr_value = property(_get_attr_value, _set_attr_value)
    
    def __repr__(self):
        # TODO: Update repr to include new constructor parameters
        return 'HtmlLink(%s,%s,%s,%s)' % (repr(self.relative_url), repr(self.type_title), repr(self.title), repr(self.embedded))
