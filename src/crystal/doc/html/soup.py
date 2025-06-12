"""
HTML parser implementation that uses BeautifulSoup.
"""

from collections.abc import Callable
from crystal.doc.css import (
    CssDocument, parse_css_and_links_from_style_attribute,
    parse_css_and_links_from_style_tag,
)
from crystal.doc.generic import Document, Link
from crystal.doc.html import HtmlParserType
from crystal.util.fastsoup import (
    BeautifulFastSoup, FastSoup, FindFunc, LxmlFastSoup, name_of_tag,
    parse_html, Tag,
)
from dataclasses import dataclass
import json
import re
from re import Match
from typing import List, Optional, Tuple, Type
from urllib.parse import urlparse

_PARSER_LIBRARY_T_CHOICES = (
    LxmlFastSoup,
    BeautifulFastSoup,
)  # type: Tuple[Type[FastSoup], ...]


_ON_CLICK_RE = re.compile(r'''(?i)([a-zA-Z.]*\.(?:href|location)) *= *(['"])([^'"]*)['"] *;?$''')
_TEXT_JAVASCRIPT_RE = re.compile(r'(?i)^text/javascript$')
_QUOTED_HTTP_LINK_RE = re.compile(
    r'(?i)(?:'
        r'(")((?:'                          # "..."
                   r'\\?/\\?/[^/"][^"]*|'       # //...
            r'https?:\\?/\\?/(?:[^/"][^"]*)?'   # https://...
        r'))"|'
        r"(')("                             # '...'
                   r"\\?/\\?/[^/'][^']*|"       # //...
            r"https?:\\?/\\?/(?:[^/'][^']*)?"   # https://...
        r")'"
    r')'
)
ABSOLUTE_HTTP_LINK_RE = re.compile(r'''(?i)^(https?://.+)$''')

PROBABLE_EMBEDDED_URL_RE = re.compile(r'(?i)\.(gif|jpe?g|png|svg|js|css)(?:\?[^/?]*)?$')


@dataclass
class _XPaths:
    STYLE_XP: FindFunc
    STYLE_EQ_STAR_XP: FindFunc
    BACKGROUND_EQ_STAR_XP: FindFunc
    SRC_EQ_STAR_XP: FindFunc
    IMG_SRCSET_EQ_STAR_XP: FindFunc
    SOURCE_SRCSET_EQ_STAR_XP: FindFunc
    HREF_EQ_STAR_XP: FindFunc
    ONCLICK_EQ_ELLIPSIS_XP: FindFunc
    SCRIPT_STRING_EQ_QUOTED_HTTP_LINK_XP: FindFunc
    STAR_XP: FindFunc

_XPS_FOR_PARSER_LIBRARY_T = {T: _XPaths(
    STYLE_XP = T.find_all_compile(
        'style'),
    STYLE_EQ_STAR_XP = T.find_all_compile(
        style=True),
    BACKGROUND_EQ_STAR_XP = T.find_all_compile(
        background=True),
    SRC_EQ_STAR_XP = T.find_all_compile(
        src=True),
    IMG_SRCSET_EQ_STAR_XP = T.find_all_compile(
        'img', srcset=True),
    SOURCE_SRCSET_EQ_STAR_XP = T.find_all_compile(
        'source', srcset=True),
    HREF_EQ_STAR_XP = T.find_all_compile(
        href=True),
    ONCLICK_EQ_ELLIPSIS_XP = T.find_all_compile(
        onclick=_ON_CLICK_RE),
    SCRIPT_STRING_EQ_QUOTED_HTTP_LINK_XP = T.find_all_compile(
        'script', string=_QUOTED_HTTP_LINK_RE),
    STAR_XP = T.find_all_compile(),
) for T in _PARSER_LIBRARY_T_CHOICES}


TEXT_LINK_TYPE_TITLE = 'Link'
FAVICON_TYPE_TITLE = 'Icon'


def parse_html_and_links(
        html_bytes: bytes, 
        declared_charset: str | None,
        parser_type: HtmlParserType,
        ) -> 'Optional[Tuple[Document, List[Link]]]':
    try:
        html = parse_html(
            html_bytes,
            from_encoding=declared_charset,
            parser_type=parser_type,
        )
    except Exception as e:
        return None
    
    XPS = _XPS_FOR_PARSER_LIBRARY_T[type(html)]
    
    links = []  # type: List[Link]
    pre_stringify_actions = []  # type: List[Callable[[], None]]
    
    # <style>...</style>
    for tag in XPS.STYLE_XP(html):
        style_body = html.tag_string(tag)
        if style_body is None:
            continue
        (css_doc, css_links) = parse_css_and_links_from_style_tag(style_body)
        links.extend(css_links)
        pre_stringify_actions.append(_update_style_tag_string_func(html, tag, css_doc))
    
    # <* style=*>
    for tag in XPS.STYLE_EQ_STAR_XP(html):
        style_value = html.tag_attrs(tag)['style']
        if not isinstance(style_value, str):
            continue
        (css_doc, css_links) = parse_css_and_links_from_style_attribute(style_value)
        links.extend(css_links)
        pre_stringify_actions.append(_update_style_attr_value_func(html, tag, css_doc))
    
    # <* background=*>
    for tag in XPS.BACKGROUND_EQ_STAR_XP(html):
        embedded = True
        title = None
        type_title = 'Background Image'
        links.append(HtmlLink.create_from_tag(tag, html, 'background', type_title, title, embedded))
    
    # <source srcset=*>, before <img src=*>
    for tag in XPS.SOURCE_SRCSET_EQ_STAR_XP(html):
        links.extend(_process_srcset_attr(html, tag))
    
    # <* src=*>
    for tag in XPS.SRC_EQ_STAR_XP(html):
        tag_name = html.tag_name(tag)  # cache
        tag_attrs = html.tag_attrs(tag)  # cache
        
        embedded = True
        if tag_name == 'img':
            title = _get_image_tag_title(html, tag)
            type_title = 'Image'
        elif tag_name == 'iframe':
            title = _assert_str(tag_attrs['name']) if 'name' in tag_attrs else None
            type_title = 'IFrame'
        elif tag_name == 'frame':
            title = _assert_str(tag_attrs['name']) if 'name' in tag_attrs else None
            type_title = 'Frame'
        elif tag_name == 'input' and 'type' in tag_attrs and tag_attrs['type'] == 'image':
            title = _get_image_tag_title(html, tag)
            type_title = 'Form Image'
        else:
            title = None
            type_title = 'Unknown Embedded (%s)' % tag_name
        if tag_name == 'script' and 'integrity' in tag_attrs:
            rewrite_side_effect = _remove_integrity_attr_func(html, tag)
        else:
            rewrite_side_effect = None
        links.append(HtmlLink.create_from_tag(
            tag, html, 'src', type_title, title, embedded,
            rewrite_side_effect=rewrite_side_effect))
    
    # <img srcset=*>
    for tag in XPS.IMG_SRCSET_EQ_STAR_XP(html):
        links.extend(_process_srcset_attr(html, tag))
    
    # <* href=*>
    for tag in XPS.HREF_EQ_STAR_XP(html):
        tag_name = html.tag_name(tag)  # cache
        tag_attrs = html.tag_attrs(tag)  # cache
        
        relative_url = _assert_str(tag_attrs['href'])
        relative_url_path = urlparse(relative_url).path
        embedded = False
        if tag_name == 'a':
            title = html.tag_string(tag)
            type_title = TEXT_LINK_TYPE_TITLE  # 'Link'
        elif tag_name == 'link' and (
                ('rel' in tag_attrs and 'stylesheet' in tag_attrs['rel']) or (
                 'type' in tag_attrs and tag_attrs['type'] == 'text/css') or (
                 relative_url_path.endswith('.css'))):
            title = None
            type_title = 'Stylesheet'
            embedded = True
        elif tag_name == 'link' and (
                    ('rel' in tag_attrs and any([x in tag_attrs['rel'] for x in (
                        'shortcut icon',
                        'icon',
                        'apple-touch-icon')])) or 
                    (relative_url_path.endswith('.ico') or 
                        relative_url_path.endswith('.png'))
                ):
            title = None
            type_title = FAVICON_TYPE_TITLE
            embedded = True
        elif tag_name == 'link' and (
                'rel' in tag_attrs and 'preload' in tag_attrs['rel']):
            title = None
            type_title = 'Preload'
            embedded = True
        elif tag_name == 'link' and 'rel' in tag_attrs:
            def format_rel(rel: str | list[str]) -> str:
                if isinstance(rel, str):
                    return rel
                elif isinstance(rel, list):
                    return ','.join(rel)
                else:
                    raise ValueError()
            
            title = None
            type_title = 'Unknown Link (rel=%s)' % format_rel(tag_attrs['rel'])
        else:
            title = None
            type_title = 'Unknown Href (%s)' % tag_name
        if tag_name == 'link' and 'integrity' in tag_attrs:
            rewrite_side_effect = _remove_integrity_attr_func(html, tag)
        else:
            rewrite_side_effect = None
        links.append(HtmlLink.create_from_tag(
            tag, html, 'href', type_title, title, embedded,
            rewrite_side_effect=rewrite_side_effect))
    
    # <* onclick='*.location = "*";'>
    # This type of link is used on:
    # - fanfiction.net
    # - http://niko-niko.net/mg/shows.html
    for tag in XPS.ONCLICK_EQ_ELLIPSIS_XP(html):
        tag_attrs = html.tag_attrs(tag)  # cache
        
        matcher = _ON_CLICK_RE.search(_assert_str(tag_attrs['onclick']))
        assert matcher is not None
        def process_match(matcher: Match) -> None:
            def replace_url_in_old_attr_value(url: str, old_attr_value: str) -> str:
                q = matcher.group(2)
                return matcher.group(1) + ' = ' + q + url + q
            
            relative_url = matcher.group(3)
            title = _assert_str(tag_attrs['value']) if 'value' in tag_attrs else None
            type_title = 'Clickable'
            embedded = False
            links.append(HtmlLink.create_from_complex_tag(
                tag, html, 'onclick', type_title, title, embedded,
                relative_url, replace_url_in_old_attr_value))
        process_match(matcher)
    
    # 1. <script [type="text/javascript"]>..."http(s)://**"...</script>
    #   - This type of link is used on: http://*.daportfolio.com/
    # 2. <script [type="text/javascript"]>..."//**"...</script>
    #   - This type of link is used on: https://blog.calm.com/take-a-deep-breath
    for tag in XPS.SCRIPT_STRING_EQ_QUOTED_HTTP_LINK_XP(html):
        tag_attrs = html.tag_attrs(tag)  # cache
        
        if 'type' in tag_attrs:
            if not _TEXT_JAVASCRIPT_RE.fullmatch(_assert_str(tag_attrs['type'])):
                continue
        
        tag_string = html.tag_string(tag)
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
                    tag, html, 'string', type_title, title, embedded,
                    relative_url, replace_url_in_old_attr_value))
            process_str_match(match)
    
    # <* *="http(s)://**">
    # This type of link is used on: https://blog.calm.com/take-a-deep-breath
    # where the attribute name is "data-url".
    seen_tags_and_attr_names = {
        (_IdentityKey(link.tag), link.attr_name) for link in links
        if isinstance(link, HtmlLink)
    }  # capture
    for tag in XPS.STAR_XP(html):
        tag_ident = _IdentityKey(tag)  # cache
        for (attr_name, attr_value) in html.tag_attrs(tag).items():
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
                tag, html, attr_name, type_title, title, embedded))
    
    doc = HtmlDocument(html, pre_stringify_actions=pre_stringify_actions)
    return (doc, links)


def _update_style_tag_string_func(html: FastSoup, tag: Tag, css_doc: CssDocument) -> Callable[[], None]:
    return lambda: html.set_tag_string(tag, str(css_doc))


def _update_style_attr_value_func(html: FastSoup, tag: Tag, css_doc: CssDocument) -> Callable[[], None]:
    def update_style_attr_value() -> None:
        html.tag_attrs(tag)['style'] = str(css_doc)
    return update_style_attr_value


def _remove_integrity_attr_func(html: FastSoup, tag: Tag) -> Callable[[], None]:
    def remove_integrity_attr() -> None:
        del html.tag_attrs(tag)['integrity']
    return remove_integrity_attr


def _get_image_tag_title(html: FastSoup, tag: Tag) -> str | None:
    tag_attrs = html.tag_attrs(tag)  # cache
    
    if 'alt' in tag_attrs:
        return _assert_str(tag_attrs['alt'])
    elif 'title' in tag_attrs:
        return _assert_str(tag_attrs['title'])
    else:
        return None


def _process_srcset_attr(html: FastSoup, img_or_source_tag: Tag) -> 'List[HtmlLink]':
    srcset = _parse_srcset_str(_assert_str(html.tag_attrs(img_or_source_tag)['srcset']))
    if srcset is None:
        return []
    
    links = []
    
    def process_candidate(parts: list[str]) -> None:
        nonlocal links, srcset
        
        def replace_url_in_old_attr_value(url: str, old_attr_value: str) -> str:
            nonlocal parts, srcset
            parts[0] = url  # reinterpret
            assert srcset is not None  # help mypy
            return _format_srcset_str(srcset)
        
        relative_url = parts[0]
        tag_name = name_of_tag(img_or_source_tag)  # cache
        if tag_name == 'img':
            title = _get_image_tag_title(html, img_or_source_tag)
            type_title = 'Image'
        elif tag_name == 'source':
            title = None
            type_title = 'Image Source'
        else:
            raise ValueError()
        embedded = True
        links.append(HtmlLink.create_from_complex_tag(
            img_or_source_tag, html, 'srcset', type_title, title, embedded,
            relative_url, replace_url_in_old_attr_value))
    
    candidates = srcset
    for c in candidates:
        parts = c
        process_candidate(parts)
    
    return links


# NOTE: Each URL in a srcset may itself contain a comma
#       (due to data: URLs) so cannot just split on comma
_SRCSET_PART_RE = re.compile(r' *(data:[^ ]+|[^ ,]+)(?: +([^ ,]+))? *,')

def _parse_srcset_str(srcset_str: str) -> list[list[str]] | None:
    candidates = []
    for parts in _SRCSET_PART_RE.findall(srcset_str + ','):
        if parts[1] == '':
            candidates.append([parts[0]])
        else:
            candidates.append([parts[0], parts[1]])
    return candidates


def _format_srcset_str(srcset: list[list[str]]) -> str:
    return ','.join([' '.join(parts) for parts in srcset])


class HtmlDocument(Document):
    def __init__(self,
            html: FastSoup,
            *, is_html: bool=True,
            pre_stringify_actions: list[Callable[[], None]] | None=None,
            ) -> None:
        self._html = html
        self._is_html = is_html
        self._pre_stringify_actions = pre_stringify_actions or []
    
    def try_insert_script(self, script_url: str) -> bool:
        def create_script(html: FastSoup) -> Tag:
            script = html.new_tag('script')
            html.tag_attrs(script)['src'] = script_url
            return script
        return self._try_insert_html_element(create_script) is not None
    
    def try_insert_favicon_link(self, favicon_url: str) -> Link | None:
        def create_link(html: FastSoup) -> Tag:
            link = self._html.new_tag('link')
            self._html.tag_attrs(link)['rel'] = 'icon'
            self._html.tag_attrs(link)['href'] = favicon_url
            return link
        link_tag = self._try_insert_html_element(create_link)
        if link_tag is None:
            return None
        link = HtmlLink.create_from_tag(
            link_tag, self._html, 'href', FAVICON_TYPE_TITLE, None, True)
        return link
    
    def _try_insert_html_element(self, create_element_func: Callable[[FastSoup], Tag]) -> Tag | None:
        if not self._is_html:
            # Don't try to insert an HTML link into a non-HTML document,
            # such as an XML document
            return False
        
        first_element = self._html.find(True)
        if first_element is not None:
            new_element = create_element_func(self._html)
            self._html.tag_insert_before(first_element, new_element)
            return new_element
        else:
            return None
    
    def __str__(self) -> str:
        for action in self._pre_stringify_actions:
            action()
        return str(self._html)


# TODO: Split this internally into three subclasses
class HtmlLink(Link):
    """
    Represents a link in a (usually-HTML) resource.
    """
    @staticmethod
    def create_from_tag(
            tag: Tag,
            tag_doc: FastSoup,
            attr_name: str,
            type_title: str,
            title: str | None,
            embedded: bool,
            *, rewrite_side_effect: Callable[[], None] | None=None,
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
        return HtmlLink(
            None, tag, tag_doc, attr_name, type_title, title, embedded,
            rewrite_side_effect=rewrite_side_effect)
    
    @staticmethod
    def create_from_complex_tag(
            tag: Tag,
            tag_doc: FastSoup,
            attr_name: str,
            type_title: str,
            title: str | None,
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
        return HtmlLink(
            relative_url, tag, tag_doc, attr_name, type_title, title, embedded,
            replace_url_in_old_attr_value=replace_url_in_old_attr_value)
    
    @staticmethod
    def create_external(
            relative_url: str,
            type_title: str,
            title: str | None,
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
        return HtmlLink(relative_url, None, None, None, type_title, title, embedded)
    
    def __init__(self,
            relative_url: str | None,
            tag: Tag | None,
            tag_doc: FastSoup | None,
            attr_name: str | None,
            type_title: str,
            title: str | None,
            embedded: bool,
            *, replace_url_in_old_attr_value: Callable[[str, str], str] | None=None,
            rewrite_side_effect: Callable[[], None] | None=None,
            ) -> None:
        self._relative_url = relative_url
        self._tag = tag
        self._tag_doc = tag_doc
        self._attr_name = attr_name
        self._replace_url_in_old_attr_value = replace_url_in_old_attr_value
        self._rewrite_side_effect = rewrite_side_effect
        
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
            self._relative_url = url
        if self._rewrite_side_effect is not None:
            self._rewrite_side_effect()
    relative_url = property(_get_relative_url, _set_relative_url)
    
    @property
    def tag(self) -> Tag | None:
        return self._tag
    
    @property
    def attr_name(self) -> str | None:
        return self._attr_name
    
    def _get_attr_value(self) -> str:
        assert self._tag is not None
        assert self._tag_doc is not None
        assert self._attr_name is not None
        if self._attr_name == 'string':
            tag_string = self._tag_doc.tag_string(self._tag)
            assert tag_string is not None
            return tag_string
        else:
            tag_attrs = self._tag_doc.tag_attrs(self._tag)
            return _assert_str(tag_attrs[self._attr_name])
    def _set_attr_value(self, attr_value: str) -> None:
        assert self._tag is not None
        assert self._tag_doc is not None
        assert self._attr_name is not None
        if self._attr_name == 'string':
            self._tag_doc.set_tag_string(self._tag, attr_value)
        else:
            tag_attrs = self._tag_doc.tag_attrs(self._tag)
            tag_attrs[self._attr_name] = attr_value
    _attr_value = property(_get_attr_value, _set_attr_value)
    
    def __repr__(self) -> str:
        # TODO: Update repr to include new constructor parameters
        return 'HtmlLink({},{},{},{})'.format(repr(self.relative_url), repr(self.type_title), repr(self.title), repr(self.embedded))


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
