import bs4
from bs4 import BeautifulSoup
from typing import cast, Dict, Iterable, List, Literal, MutableMapping, Optional, Pattern, Union


TagT = Union['LxmlTag', bs4.Tag]


def parse_html(
        html_bytes: bytes,
        from_encoding: Optional[str],
        features: Literal['lxml', 'html5lib', 'html.parser'],
        ) -> 'MetaSoup':
    if features == 'lxml':
        return LxmlSoup(html_bytes, from_encoding)
    elif features in ['html5lib', 'html.parser']:
        return BeautifulSoupFacade(
            BeautifulSoup(html_bytes, from_encoding=from_encoding, features=features))
    else:
        raise ValueError(f'Unrecognized value for features: {features}')


class MetaSoup:  # abstract
    # === Document ===
    
    def find_all(self, tag_name: Optional[str]=None, **attrs: Union[str, Pattern, Literal[True]]) -> 'Iterable[TagT]':
        raise NotImplementedError()
    
    def find(self, pattern: Literal[True]) -> 'Optional[TagT]':
        raise NotImplementedError()
    
    def new_tag(self, tag_name: str) -> 'TagT':
        raise NotImplementedError()
    
    def __str__(self) -> str:
        raise NotImplementedError()
    
    # === Tags ===
    
    def tag_name(self, tag: TagT) -> str:
        raise NotImplementedError()
    
    def tag_attrs(self, tag: TagT) -> MutableMapping[str, Union[str, List[str]]]:
        raise NotImplementedError()
    
    def tag_string(self, tag: TagT) -> Optional[str]:
        raise NotImplementedError()
    
    def set_tag_string(self, tag: TagT, string: Optional[str]) -> None:
        raise NotImplementedError()
    
    def tag_insert_before(self, tag: TagT, tag2: TagT) -> None:
        raise NotImplementedError()


class BeautifulSoupFacade(MetaSoup):
    def __init__(self, base: BeautifulSoup) -> None:
        self._base = base
    
    # === Document ===
    
    def find_all(self, tag_name: Optional[str]=None, **attrs: Union[str, Pattern, Literal[True]]) -> 'Iterable[TagT]':
        return self._base.find_all(tag_name, **attrs)  # type: ignore[arg-type]
    
    def find(self, pattern: Literal[True]) -> 'Optional[TagT]':
        result = self._base.find(pattern)  # type: ignore[arg-type]
        assert not isinstance(result, bs4.NavigableString)
        return result
    
    def new_tag(self, tag_name: str) -> 'TagT':
        return self._base.new_tag(tag_name)
    
    def __str__(self) -> str:
        return str(self._base)
    
    # === Tags ===
    
    def tag_name(self, tag: TagT) -> str:
        assert isinstance(tag, bs4.Tag)
        return tag.name
    
    def tag_attrs(self, tag: TagT) -> MutableMapping[str, Union[str, List[str]]]:
        assert isinstance(tag, bs4.Tag)
        return tag.attrs  # type: ignore[return-value]
    
    def tag_string(self, tag: TagT) -> Optional[str]:
        assert isinstance(tag, bs4.Tag)
        return tag.string
    
    def set_tag_string(self, tag: TagT, string: Optional[str]) -> None:
        assert isinstance(tag, bs4.Tag)
        tag.string = string;
    
    def tag_insert_before(self, tag: TagT, tag2: TagT) -> None:
        assert isinstance(tag, bs4.Tag)
        assert isinstance(tag2, bs4.Tag)
        tag.insert_before(tag2)


class LxmlSoup(MetaSoup):
    def __init__(self, html_bytes: bytes, from_encoding: Optional[str]) -> None:
        raise NotImplementedError()


LxmlTag = object
