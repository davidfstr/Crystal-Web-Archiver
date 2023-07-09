import bs4
from bs4 import BeautifulSoup
import lxml.html
from typing import (
    cast, Dict, Iterable, List, Literal, MutableMapping, Optional, Pattern, Union
)


def parse_html(
        html_bytes: bytes,
        from_encoding: Optional[str],
        features: Literal['lxml', 'html5lib', 'html.parser'],
        ) -> 'FastSoup':
    if features == 'lxml':
        parser = lxml.html.HTMLParser(encoding=from_encoding)
        root = lxml.html.document_fromstring(html_bytes, parser=parser)
        return LxmlSoup(root)
    elif features in ['html5lib', 'html.parser']:
        return BeautifulSoupFacade(
            BeautifulSoup(html_bytes, from_encoding=from_encoding, features=features))
    else:
        raise ValueError(f'Unrecognized value for features: {features}')


Tag = Union[lxml.html.HtmlElement, bs4.Tag]


class FastSoup:  # abstract
    # === Document ===
    
    def find_all(self, tag_name: Optional[str]=None, **attrs: Union[str, Pattern, Literal[True]]) -> 'Iterable[Tag]':
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
    
    def tag_attrs(self, tag: Tag) -> MutableMapping[str, Union[str, List[str]]]:
        raise NotImplementedError()
    
    def tag_string(self, tag: Tag) -> Optional[str]:
        raise NotImplementedError()
    
    def set_tag_string(self, tag: Tag, string: Optional[str]) -> None:
        raise NotImplementedError()
    
    def tag_insert_before(self, tag: Tag, tag2: Tag) -> None:
        raise NotImplementedError()


class BeautifulSoupFacade(FastSoup):
    def __init__(self, base: BeautifulSoup) -> None:
        self._base = base
    
    # === Document ===
    
    def find_all(self, tag_name: Optional[str]=None, **attrs: Union[str, Pattern, Literal[True]]) -> 'Iterable[Tag]':
        return self._base.find_all(tag_name, **attrs)  # type: ignore[arg-type]
    
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
    
    def tag_attrs(self, tag: Tag) -> MutableMapping[str, Union[str, List[str]]]:
        assert isinstance(tag, bs4.Tag)
        return tag.attrs  # type: ignore[return-value]
    
    def tag_string(self, tag: Tag) -> Optional[str]:
        assert isinstance(tag, bs4.Tag)
        return tag.string
    
    def set_tag_string(self, tag: Tag, string: Optional[str]) -> None:
        assert isinstance(tag, bs4.Tag)
        tag.string = string;
    
    def tag_insert_before(self, tag: Tag, tag2: Tag) -> None:
        assert isinstance(tag, bs4.Tag)
        assert isinstance(tag2, bs4.Tag)
        tag.insert_before(tag2)


class LxmlSoup(FastSoup):
    def __init__(self, root: lxml.html.HtmlElement) -> None:
        self._root = root
    
    # === Document ===
    
    def find_all(self, tag_name: Optional[str]=None, **attrs: Union[str, Pattern, Literal[True]]) -> 'Iterable[Tag]':
        def make_attr_pattern_part(name: str, value_pat: Union[str, Pattern, Literal[True]]) -> str:
            if value_pat == True or isinstance(value_pat, Pattern):
                return f'@{name}'
            elif isinstance(value_pat, str):
                return f'@{name}="{value_pat}"'
            else:
                raise ValueError()
        
        tag_pattern = tag_name if tag_name is not None else '*'
        attr_pattern = ''.join([
            f'[{make_attr_pattern_part(k, v_pat)}]'
            for (k, v_pat) in attrs.items()
            if k != 'string'
        ])
        total_pattern = f'.//{tag_pattern}{attr_pattern}'
        
        re_attrs = [
            (k, v_pat)
            for (k, v_pat) in attrs.items()
            if isinstance(v_pat, Pattern)
        ]
        def matches_re_attrs(tag) -> bool:
            for (k, v_pat) in re_attrs:
                v = tag.text if k == 'string' else tag.attrib[k]
                if not isinstance(v, str) or v_pat.search(v) is None:
                    return False
            return True
        
        results = self._root.findall(total_pattern)
        if len(re_attrs) == 0:
            return results
        else:
            return [r for r in results if matches_re_attrs(r)]
    
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
    
    def tag_attrs(self, tag: Tag) -> MutableMapping[str, Union[str, List[str]]]:
        assert isinstance(tag, lxml.html.HtmlElement)
        return tag.attrib
    
    def tag_string(self, tag: Tag) -> Optional[str]:
        assert isinstance(tag, lxml.html.HtmlElement)
        return tag.text
    
    def set_tag_string(self, tag: Tag, string: Optional[str]) -> None:
        assert isinstance(tag, lxml.html.HtmlElement)
        tag.text = string
    
    def tag_insert_before(self, tag: Tag, tag2: Tag) -> None:
        assert isinstance(tag, lxml.html.HtmlElement)
        assert isinstance(tag2, lxml.html.HtmlElement)
        tag.addprevious(tag2)
