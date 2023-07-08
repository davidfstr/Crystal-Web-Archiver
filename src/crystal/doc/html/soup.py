"""
HTML parser implementation that uses BeautifulSoup.
"""

from __future__ import annotations

import bs4
from crystal.metasoup import MetaSoup, parse_html, TagT
from crystal.doc.generic import Document, Link
import json
import re
from typing import Callable, List, Literal, Match, Optional, Tuple, Union
from urllib.parse import urlparse


# HTML parsing library to use. See comparison between options at: 
# https://beautiful-soup-4.readthedocs.io/en/latest/#installing-a-parser
# 
# TODO: Consider migrating to 'lxml' parser for additional speed
_PARSER_LIBRARY = 'html.parser'  # type: Literal['lxml', 'html5lib', 'html.parser']


_ON_CLICK_RE = re.compile(r'''(?i)([a-zA-Z]*\.(?:href|location)) *= *(['"])([^'"]*)['"] *;?$''')
_TEXT_JAVASCRIPT_RE = re.compile(r'(?i)^text/javascript$')
_QUOTED_HTTP_LINK_RE = re.compile(r'''(?i)(?:(")((?:https?:)?\\?/\\?/[^/][^"]+)"|(')((?:https?:)?\\?/\\?/[^/][^']+)')''')
ABSOLUTE_HTTP_LINK_RE = re.compile(r'''(?i)^(https?://.+)$''')

PROBABLE_EMBEDDED_URL_RE = re.compile(r'(?i)\.(gif|jpe?g|png|svg|js|css)$')


def parse_html_and_links(
        html_bytes: bytes, 
        declared_charset: Optional[str]=None
        ) -> 'Optional[Tuple[Document, List[Link]]]':
    try:
        html = parse_html(
            html_bytes,
            from_encoding=declared_charset,
            features=_PARSER_LIBRARY,
        )
    except Exception as e:
        return None
    
    links = []
    
    # <* background=*>
    for tag in html.find_all(background=True):
        embedded = True
        title = None
        type_title = 'Background Image'
        links.append(HtmlLink.create_from_tag(tag, 'background', type_title, title, embedded))
    
    # <* src=*>
    for tag in html.find_all(src=True):
        embedded = True
        if tag.name == 'img':
            title = _get_image_tag_title(tag)
            type_title = 'Image'
        elif tag.name == 'iframe':
            title = _assert_str(tag.attrs['name']) if 'name' in tag.attrs else None
            type_title = 'IFrame'
        elif tag.name == 'frame':
            title = _assert_str(tag.attrs['name']) if 'name' in tag.attrs else None
            type_title = 'Frame'
        elif tag.name == 'input' and 'type' in tag.attrs and tag.attrs['type'] == 'image':
            title = _get_image_tag_title(tag)
            type_title = 'Form Image'
        else:
            title = None
            type_title = 'Unknown Embedded (%s)' % tag.name
        links.append(HtmlLink.create_from_tag(tag, 'src', type_title, title, embedded))
    
    # <img srcset=*>
    for tag in html.find_all('img', srcset=True):
        links.extend(_process_srcset_attr(tag))
    
    # <* href=*>
    for tag in html.find_all(href=True):
        relative_url = _assert_str(tag.attrs['href'])
        relative_url_path = urlparse(relative_url).path
        embedded = False
        if tag.name == 'a':
            title = tag.string
            type_title = 'Link'
        elif tag.name == 'link' and (
                ('rel' in tag.attrs and 'stylesheet' in tag.attrs['rel']) or (
                 'type' in tag.attrs and tag.attrs['type'] == 'text/css') or (
                 relative_url_path.endswith('.css'))):
            title = None
            type_title = 'Stylesheet'
            embedded = True
        elif tag.name == 'link' and (
                    ('rel' in tag.attrs and any([x in tag.attrs['rel'] for x in (
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
    for tag in html.find_all('input', type='button', onclick=_ON_CLICK_RE):
        matcher = _ON_CLICK_RE.search(_assert_str(tag.attrs['onclick']))
        assert matcher is not None
        def process_match(matcher: Match) -> None:
            def replace_url_in_old_attr_value(url: str, old_attr_value: str) -> str:
                q = matcher.group(2)
                return matcher.group(1) + ' = ' + q + url + q
            
            relative_url = matcher.group(3)
            title = _assert_str(tag.attrs['value']) if 'value' in tag.attrs else None
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
    for tag in html.find_all('script', string=_QUOTED_HTTP_LINK_RE):
        if 'type' in tag.attrs:
            if not _TEXT_JAVASCRIPT_RE.fullmatch(_assert_str(tag.attrs['type'])):
                continue
        
        tag_string = tag.string
        if tag_string is None:
            continue
        matches = _QUOTED_HTTP_LINK_RE.findall(tag_string)
        for match in matches:
            def process_str_match(match: str) -> None:
                q = match[0] or match[2]
                old_string_literal = q + (match[1] or match[3]) + q
                
                def replace_url_in_old_attr_value(url: str, old_attr_value: str) -> str:
                    quoted_url = json.dumps(url)  # type: ignore[attr-defined]
                    if q == "'":
                        new_string_literal = q + quoted_url[1:-1].replace(q, '\\' + q) + q
                    else:  # q == '"' or something else
                        new_string_literal = quoted_url
                    
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
    seen_tags_and_attr_names = set([
        (_IdentityKey(link.tag), link.attr_name) for link in links
    ])  # capture
    for tag in html.find_all():
        tag_ident = _IdentityKey(tag)  # cache
        for (attr_name, attr_value) in tag.attrs.items():
            if (tag_ident, attr_name) in seen_tags_and_attr_names:
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
    
    links_ = links  # type: List[Link]  # type: ignore[assignment]  # allow List[HtmlLink] to be converted
    return (HtmlDocument(html), links_)


def _get_image_tag_title(tag: TagT) -> Optional[str]:
    if 'alt' in tag.attrs:
        return _assert_str(tag.attrs['alt'])
    elif 'title' in tag.attrs:
        return _assert_str(tag.attrs['title'])
    else:
        return None


def _process_srcset_attr(img_tag: TagT) -> 'List[HtmlLink]':
    srcset = _parse_srcset_str(_assert_str(img_tag.attrs['srcset']))
    if srcset is None:
        return []
    
    links = []
    
    def process_candidate(parts: List[str]) -> None:
        nonlocal links, srcset
        
        def replace_url_in_old_attr_value(url: str, old_attr_value: str) -> str:
            nonlocal parts, srcset
            parts[0] = url  # reinterpret
            assert srcset is not None  # help mypy
            return _format_srcset_str(srcset)
        
        relative_url = parts[0]
        title = _get_image_tag_title(img_tag)
        type_title = 'Image'
        embedded = True
        links.append(HtmlLink.create_from_complex_tag(
            img_tag, 'srcset', type_title, title, embedded,
            relative_url, replace_url_in_old_attr_value))
    
    candidates = srcset
    for c in candidates:
        parts = c
        process_candidate(parts)
    
    return links


def _parse_srcset_str(srcset_str: str) -> Optional[List[List[str]]]:
    candidates = []
    candidate_strs = [c.strip() for c in srcset_str.split(',')]
    for c_str in candidate_strs:
        parts = [p for p in c_str.split(' ') if len(p) != 0]
        if not (1 <= len(parts) <= 2):
            # Failed to parse srcset
            return None
        candidates.append(parts)
    return candidates


def _format_srcset_str(srcset: List[List[str]]) -> str:
    return ','.join([' '.join(parts) for parts in srcset])


class HtmlDocument(Document):
    def __init__(self, html: MetaSoup) -> None:
        self._html = html
    
    def try_insert_script(self, script_url: str) -> bool:
        first_element = self._html.find(True)
        if first_element is not None:
            script = self._html.new_tag('script')
            script.attrs['src'] = script_url
            
            if isinstance(first_element, bs4.PageElement):
                assert isinstance(script, bs4.Tag)
                first_element.insert_before(script)
            else:
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
    def create_from_tag(
            tag: TagT,
            attr_name: str,
            type_title: str,
            title: Optional[str],
            embedded: bool
            ) -> 'HtmlLink':
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
            raise ValueError()
        return HtmlLink(None, tag, attr_name, type_title, title, embedded)
    
    @staticmethod
    def create_from_complex_tag(
            tag: TagT,
            attr_name: str,
            type_title: str,
            title: Optional[str],
            embedded: bool,
            relative_url: str,
            replace_url_in_old_attr_value: Callable[[str, str], str]
            ) -> 'HtmlLink':
        """
        See HtmlLink.create_from_tag()
        
        Extra Arguments:
        * replace_url_in_old_attr_value --
            function that takes a URL and returns the appropriate
            value for the underlying tag's attribute.
        """
        if (tag is None or attr_name is None or not callable(replace_url_in_old_attr_value) or 
                type_title is None or embedded not in (True, False)):
            raise ValueError()
        return HtmlLink(relative_url, tag, attr_name, type_title, title, embedded, replace_url_in_old_attr_value)
    
    @staticmethod
    def create_external(
            relative_url: str,
            type_title: str,
            title: Optional[str],
            embedded: bool
            ) -> 'HtmlLink':
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
    
    def __init__(self,
            relative_url: Optional[str],
            tag: Optional[TagT],
            attr_name: Optional[str],
            type_title: str,
            title: Optional[str],
            embedded: bool,
            replace_url_in_old_attr_value: Optional[Callable[[str, str], str]]=None
            ) -> None:
        self._relative_url = relative_url
        self._tag = tag
        self._attr_name = attr_name
        self._replace_url_in_old_attr_value = replace_url_in_old_attr_value
        
        self.title = title
        self.type_title = type_title
        self.embedded = embedded
    
    def _get_relative_url(self) -> str:
        if self._relative_url:
            return self._relative_url
        else:
            # NOTE: Immediately strip whitespace from relative URLs inside HTML tags,
            #       before they are resolved against any base URL. Both preceding
            #       and trailing whitespace has been observed in the wild.
            return self._attr_value.strip()
    def _set_relative_url(self, url: str) -> None:
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
    def tag(self) -> Optional[TagT]:
        return self._tag
    
    @property
    def attr_name(self) -> Optional[str]:
        return self._attr_name
    
    def _get_attr_value(self) -> str:
        assert self._tag is not None
        assert self._attr_name is not None
        if self._attr_name == 'string':
            assert self._tag.string is not None
            return self._tag.string
        else:
            return _assert_str(self._tag.attrs[self._attr_name])
    def _set_attr_value(self, attr_value: str) -> None:
        assert self._tag is not None
        assert self._attr_name is not None
        if self._attr_name == 'string':
            self._tag.string = attr_value
        else:
            self._tag.attrs[self._attr_name] = attr_value
    _attr_value = property(_get_attr_value, _set_attr_value)
    
    def __repr__(self) -> str:
        # TODO: Update repr to include new constructor parameters
        return 'HtmlLink(%s,%s,%s,%s)' % (repr(self.relative_url), repr(self.type_title), repr(self.title), repr(self.embedded))


class _IdentityKey:
    """
    Wraps an object, so that equality comparisons and hash operations
    look at the object's identity only.
    """
    # Optimize per-instance memory use, since there may be many _IdentityKey objects
    __slots__ = ('_obj',)
    
    def __init__(self, obj: object) -> None:
        self._obj = obj
    
    def __hash__(self) -> int:
        return id(self._obj)
    
    def __eq__(self, other: object) -> bool:
        return (
            isinstance(other, _IdentityKey) and
            self._obj is other._obj
        )


def _assert_str(value: object) -> str:
    assert isinstance(value, str)
    return value
