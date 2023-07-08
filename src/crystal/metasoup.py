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
    
    # (TODO: ...)


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
    
    # (TODO: ...)


class LxmlSoup(MetaSoup):
    def __init__(self, html_bytes: bytes, from_encoding: Optional[str]) -> None:
        raise NotImplementedError()


class LxmlTag:
    def __init__(self) -> None:
        self._attrs = {}  # type: Dict[str, Union[str, List[str]]]
    
    @property
    def name(self) -> str:
        raise NotImplementedError()
    
    @property
    def attrs(self) -> MutableMapping[str, Union[str, List[str]]]:
        return self._attrs
    
    def _get_string(self) -> Optional[str]:
        raise NotImplementedError()
    def _set_string(self, string: Optional[str]) -> None:
        raise NotImplementedError()
    string = cast(str, property(_get_string, _set_string))
    
    def insert_before(self, tag: TagT) -> None:
        assert isinstance(tag, LxmlTag)
        raise NotImplementedError()
