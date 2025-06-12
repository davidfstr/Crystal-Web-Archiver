import bs4
from bs4 import BeautifulSoup
from collections.abc import Callable, Iterable, MutableMapping
import lxml.html
from re import Pattern
from typing import Literal, Optional, TYPE_CHECKING, Union

if TYPE_CHECKING:
    from crystal.doc.html import HtmlParserType


def parse_html(
        html_bytes: bytes,
        from_encoding: str | None,
        parser_type: 'HtmlParserType',
        ) -> 'FastSoup':
    """
    Parses an HTML document, returning a FastSoup object that can be
    examined through a BeautifulSoup-compatible API.
    """
    if parser_type == 'lxml':
        parser = lxml.html.HTMLParser(encoding=from_encoding)
        root = lxml.html.document_fromstring(html_bytes, parser=parser)
        return LxmlFastSoup(root)
    elif parser_type == 'html_parser':
        # TODO: Consider supporting 'html.parser' without using the
        #       real BeautifulSoup API to wrap it, which would probably
        #       be faster to parse.
        # NOTE: Although the native BeautifulSoup API also supports the
        #       'html5lib' parser, no version of Crystal has used it so far.
        return BeautifulFastSoup(BeautifulSoup(
            html_bytes, from_encoding=from_encoding, features='html.parser'))
    else:
        raise ValueError(f'Unrecognized value for parser_type: {parser_type}')


Tag = Union[lxml.html.HtmlElement, bs4.Tag]

FindFunc = Callable[['FastSoup'], Iterable[Tag]]


class FastSoup:  # abstract
    """A parsed HTML or XML document, navigable with a BeautifulSoup-compatible API."""
    
    # === Document ===
    
    def find_all(self, 
            tag_name: str | None=None, 
            **attrs: str | Pattern | Literal[True]
            ) -> Iterable[Tag]:
        raise NotImplementedError()
    
    @classmethod
    def find_all_compile(cls, 
            tag_name: str | None=None, 
            **attrs: str | Pattern | Literal[True]
            ) -> FindFunc:
        raise NotImplementedError()
    
    def find(self, pattern: Literal[True]) -> 'Optional[Tag]':
        raise NotImplementedError()
    
    def new_tag(self, tag_name: str) -> 'Tag':
        raise NotImplementedError()
    
    def __str__(self) -> str:
        raise NotImplementedError()
    
    # === Tags ===
    
    def tag_name(self, tag: Tag) -> str:
        raise NotImplementedError()
    
    def tag_attrs(self, tag: Tag) -> MutableMapping[str, str | list[str]]:
        raise NotImplementedError()
    
    def tag_string(self, tag: Tag) -> str | None:
        raise NotImplementedError()
    
    def set_tag_string(self, tag: Tag, string: str | None) -> None:
        raise NotImplementedError()
    
    def tag_insert_before(self, tag: Tag, tag2: Tag) -> None:
        raise NotImplementedError()


class BeautifulFastSoup(FastSoup):
    def __init__(self, base: BeautifulSoup) -> None:
        self._base = base
    
    # === Document ===
    
    def find_all(self, 
            tag_name: str | None=None, 
            **attrs: str | Pattern | Literal[True]
            ) -> Iterable[Tag]:
        return self._base.find_all(tag_name, **attrs)  # type: ignore[arg-type]
    
    # NOTE: BeautifulFastSoup doesn't actually support precompiling find_all() queries
    @classmethod
    def find_all_compile(cls, 
            tag_name: str | None=None, 
            **attrs: str | Pattern | Literal[True]
            ) -> FindFunc:
        def find_func(soup: FastSoup) -> Iterable[Tag]:
            if not isinstance(soup, BeautifulFastSoup):
                raise TypeError()
            return soup.find_all(tag_name, **attrs)
        return find_func
    
    def find(self, pattern: Literal[True]) -> 'Optional[Tag]':
        result = self._base.find(pattern)  # type: ignore[arg-type]
        assert not isinstance(result, bs4.NavigableString)
        return result
    
    def new_tag(self, tag_name: str) -> 'Tag':
        return self._base.new_tag(tag_name)
    
    def __str__(self) -> str:
        return str(self._base)
    
    # === Tags ===
    
    def tag_name(self, tag: Tag) -> str:
        assert isinstance(tag, bs4.Tag)
        return tag.name
    
    def tag_attrs(self, tag: Tag) -> MutableMapping[str, str | list[str]]:
        assert isinstance(tag, bs4.Tag)
        return tag.attrs  # type: ignore[return-value]
    
    def tag_string(self, tag: Tag) -> str | None:
        assert isinstance(tag, bs4.Tag)
        return tag.string
    
    def set_tag_string(self, tag: Tag, string: str | None) -> None:
        assert isinstance(tag, bs4.Tag)
        tag.string = string;
    
    def tag_insert_before(self, tag: Tag, tag2: Tag) -> None:
        assert isinstance(tag, bs4.Tag)
        assert isinstance(tag2, bs4.Tag)
        tag.insert_before(tag2)


class LxmlFastSoup(FastSoup):
    def __init__(self, root: lxml.html.HtmlElement) -> None:
        self._root = root
    
    # === Document ===
    
    def find_all(self, 
            tag_name: str | None=None, 
            **attrs: str | Pattern | Literal[True]
            ) -> Iterable[Tag]:
        return self.find_all_compile(tag_name, **attrs)(self)
    
    @classmethod
    def find_all_compile(cls, 
            tag_name: str | None=None, 
            **attrs: str | Pattern | Literal[True]
            ) -> FindFunc:
        tag_pattern = tag_name if tag_name is not None else '*'
        attr_pattern = ''.join([
            f'[{cls._make_attr_pattern_part(k, v_pat)}]'
            for (k, v_pat) in attrs.items()
            if k != 'string'
        ])
        total_pattern = f'.//{tag_pattern}{attr_pattern}'
        
        re_attrs = [
            (k, v_pat)
            for (k, v_pat) in attrs.items()
            if isinstance(v_pat, Pattern)
        ]
        
        # Filter by tag name, attribute existence, and exact attribute values
        find_func = cls._find_tags_matching_xpath(lxml.etree.XPath(total_pattern))
        # Filter by attribute values matching regular expression patterns
        # NOTE: XPath DOES support regular expressions natively, but I couldn't
        #       get it to accept a pattern that matched both single quotes and
        #       double quotes in the same pattern, even with various kinds of escaping.
        #       Therefore I filter by regular expressions manually.
        for (k, v_pat) in re_attrs:
            if k == 'string':
                find_func = cls._filter_tags_whose_text_matches_pattern(
                    find_func, v_pat)
            else:
                find_func = cls._filter_tags_whose_attrib_matches_pattern(
                    find_func, k, v_pat)
        return find_func
    
    @staticmethod
    def _make_attr_pattern_part(name: str, value_pat: str | Pattern | Literal[True]) -> str:
        if value_pat == True or isinstance(value_pat, Pattern):
            return f'@{name}'
        elif isinstance(value_pat, str):
            return f'@{name}="{value_pat}"'
        else:
            raise ValueError()
    
    @staticmethod
    def _find_tags_matching_xpath(xpath: lxml.etree.XPath) -> FindFunc:
        def find_func(soup: FastSoup) -> Iterable[Tag]:
            if not isinstance(soup, LxmlFastSoup):
                raise TypeError()
            return xpath(soup._root)
        return find_func
    
    @staticmethod
    def _filter_tags_whose_text_matches_pattern(
            find_func: FindFunc,
            v_pat: Pattern
            ) -> FindFunc:
        def new_find_func(soup: FastSoup) -> Iterable[Tag]:
            for tag in find_func(soup):  # type: lxml.html.HtmlElement
                v = tag.text
                if isinstance(v, str) and v_pat.search(v) is not None:
                    yield tag
        return new_find_func
    
    @staticmethod
    def _filter_tags_whose_attrib_matches_pattern(
            find_func: FindFunc,
            k: str,
            v_pat: Pattern
            ) -> FindFunc:
        def new_find_func(soup: FastSoup) -> Iterable[Tag]:
            for tag in find_func(soup):  # type: lxml.html.HtmlElement
                v = tag.attrib[k]
                if isinstance(v, str) and v_pat.search(v) is not None:
                    yield tag
        return new_find_func
    
    def find(self, pattern: Literal[True]) -> 'Optional[Tag]':
        return self._root.find('*')
    
    def new_tag(self, tag_name: str) -> 'Tag':
        return self._root.makeelement(tag_name)
    
    def __str__(self) -> str:
        return lxml.html.tostring(self._root, encoding='unicode')
    
    # === Tags ===
    
    def tag_name(self, tag: Tag) -> str:
        assert isinstance(tag, lxml.html.HtmlElement)
        return tag.tag
    
    def tag_attrs(self, tag: Tag) -> MutableMapping[str, str | list[str]]:
        assert isinstance(tag, lxml.html.HtmlElement)
        return tag.attrib
    
    def tag_string(self, tag: Tag) -> str | None:
        assert isinstance(tag, lxml.html.HtmlElement)
        return tag.text
    
    def set_tag_string(self, tag: Tag, string: str | None) -> None:
        assert isinstance(tag, lxml.html.HtmlElement)
        tag.text = string
    
    def tag_insert_before(self, tag: Tag, tag2: Tag) -> None:
        assert isinstance(tag, lxml.html.HtmlElement)
        assert isinstance(tag2, lxml.html.HtmlElement)
        tag.addprevious(tag2)


def name_of_tag(tag: Tag) -> str:
    if isinstance(tag, lxml.html.HtmlElement):
        return tag.tag
    elif isinstance(tag, bs4.Tag):
        return tag.name
    else:
        raise ValueError()
