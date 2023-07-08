import bs4
from bs4 import BeautifulSoup
from typing import Dict, Iterable, List, Literal, MutableMapping, Optional, Pattern, Union


# TODO: Either:
#           1. Convert MetaSoup to be a Protocol, which BeautifulSoup
#              and LxmlSoup happen to conform to, or
#           2. Implement proper wrapper around BeautifulSoup object
#              (which extends MetaSoup)
#       so that callers just need to work with MetaSoup objects
#       (and not MetaSoupT objects).
MetaSoupT = Union['LxmlSoup', BeautifulSoup]

TagT = Union['LxmlTag', bs4.Tag]


def MetaSoup(
        html_bytes: bytes,
        from_encoding: Optional[str],
        features: Literal['lxml', 'html5lib', 'html.parser'],
        ) -> MetaSoupT:
    if features == 'lxml':
        return LxmlSoup(html_bytes, from_encoding)
    elif features in ['html5lib', 'html.parser']:
        return BeautifulSoup(html_bytes, from_encoding=from_encoding, features=features)
    else:
        raise ValueError(f'Unrecognized value for features: {features}')


class LxmlSoup:
    def __init__(self, html_bytes: bytes, from_encoding: Optional[str]) -> None:
        raise NotImplementedError()
    
    def find_all(self, tag_name: Optional[str]=None, **attrs: Union[str, Pattern, Literal[True]]) -> 'Iterable[LxmlTag]':
        raise NotImplementedError()
    
    def find(self, pattern: Literal[True]) -> 'Optional[LxmlTag]':
        raise NotImplementedError()
    
    def new_tag(self, tag_name: str) -> 'LxmlTag':
        raise NotImplementedError()
    
    def __str__(self) -> str:
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
    
    def _get_string(self) -> str:
        raise NotImplementedError()
    def _set_string(self, string: str) -> None:
        raise NotImplementedError()
    string = property(_get_string, _set_string)
    
    def insert_before(self, tag: TagT) -> None:
        assert isinstance(tag, LxmlTag)
        raise NotImplementedError()
