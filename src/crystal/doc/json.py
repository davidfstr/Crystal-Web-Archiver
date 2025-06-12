"""
Parses JSON documents.
"""

from __future__ import annotations

from crystal.doc.generic import Document, Link
from crystal.doc.html.soup import (
    ABSOLUTE_HTTP_LINK_RE, PROBABLE_EMBEDDED_URL_RE,
)
import json
from typing import BinaryIO


def parse_json_and_links(
        body_bytes: BinaryIO,
        declared_charset: str | None=None
        ) -> tuple[Document, list[Link]] | None:
    try:
        json_obj = json.load(body_bytes)  # type: ignore[attr-defined]
    except Exception:
        return None
    links = []  # type: list[Link]
    # TODO: If JSON document is just a str which is a link, recognize that link
    _find_links(json_obj, links)
    return (_JsonDocument(json_obj), links)


def _find_links(json_obj: object, links: list[Link]) -> None:
    if isinstance(json_obj, dict):
        # dict
        for (k, v) in json_obj.items():
            # Add links
            if isinstance(k, str) and ABSOLUTE_HTTP_LINK_RE.fullmatch(k) is not None:
                key_link = _DictKeyLink(json_obj, k)
                links.append(key_link)
            else:
                key_link = None
            if isinstance(v, str) and ABSOLUTE_HTTP_LINK_RE.fullmatch(v) is not None:
                value_link = _DictValueLink(json_obj, key_link or k)
                links.append(value_link)
            
            # Recurse
            _find_links(k, links)
            _find_links(v, links)
    
    elif isinstance(json_obj, list):
        # list
        for (i, item) in enumerate(json_obj):
            # Add links
            if isinstance(item, str) and ABSOLUTE_HTTP_LINK_RE.fullmatch(item) is not None:
                links.append(_ListItemLink(json_obj, i))
            
            # Recurse
            _find_links(item, links)
    
    else:
        # scalar
        pass


class _JsonDocument(Document):
    def __init__(self, json_obj) -> None:
        self._json_obj = json_obj
    
    def __str__(self) -> str:
        return json.dumps(self._json_obj)  # type: ignore[attr-defined]


class _JsonLink(Link):  # abstract
    def __init__(self, type_title: str) -> None:
        self.title = None
        self.type_title = type_title
        self.embedded = PROBABLE_EMBEDDED_URL_RE.search(self.relative_url) is not None


class _DictKeyLink(_JsonLink):
    def __init__(self, json_obj: dict, key: str) -> None:
        self._json_obj = json_obj
        self.key = key
        super().__init__('Dict Key Reference')
    
    def _get_relative_url(self) -> str:
        return self.key
    def _set_relative_url(self, url: str) -> None:
        old_key = self.key
        new_key = url
        value = self._json_obj[old_key]
        
        del self._json_obj[old_key]
        self._json_obj[new_key] = value
        
        self.key = new_key
    relative_url = property(_get_relative_url, _set_relative_url)


class _DictValueLink(_JsonLink):
    def __init__(self, json_obj: dict, key_ref: _DictKeyLink | str) -> None:
        self._json_obj = json_obj
        self._key_ref = key_ref
        super().__init__('Dict Value Reference')
    
    @property
    def _key(self) -> str:
        return (
            self._key_ref.key 
            if isinstance(self._key_ref, _DictKeyLink) 
            else self._key_ref
        )
    
    def _get_relative_url(self) -> str:
        return self._json_obj[self._key]
    def _set_relative_url(self, url: str) -> None:
        self._json_obj[self._key] = url
    relative_url = property(_get_relative_url, _set_relative_url)


class _ListItemLink(_JsonLink):
    def __init__(self, json_obj: list, index: int) -> None:
        self._json_obj = json_obj
        self._index = index
        super().__init__('List Item Reference')
    
    def _get_relative_url(self) -> str:
        return self._json_obj[self._index]
    def _set_relative_url(self, url: str) -> None:
        self._json_obj[self._index] = url
    relative_url = property(_get_relative_url, _set_relative_url)
