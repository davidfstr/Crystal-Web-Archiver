"""
Parses CSS documents.
"""

from collections.abc import Iterable
from crystal.doc.generic import Document, Link
import tinycss2
from tinycss2 import ast
from tinycss2.serializer import serialize_string_value, serialize_url
from typing import List, Tuple


def parse_css_and_links(
        body_bytes: bytes, 
        declared_charset: str | None=None
        ) -> 'Tuple[CssDocument, List[Link]]':
    (rules, _) = tinycss2.parse_stylesheet_bytes(
        body_bytes,
        protocol_encoding=declared_charset)
    return _parse_css_and_links(rules)


def parse_css_and_links_from_style_tag(
        tag_str: str
        ) -> 'Tuple[CssDocument, List[Link]]':
    rules = tinycss2.parse_stylesheet(tag_str)
    return _parse_css_and_links(rules)


def parse_css_and_links_from_style_attribute(
        attr_value: str
        ) -> 'Tuple[CssDocument, List[Link]]':
    decls = tinycss2.parse_declaration_list(attr_value)
    
    links = []  # type: List[Link]
    for decl in decls:
        if not isinstance(decl, ast.Declaration):
            continue
        _parse_links_from_component_values(decl.value, links)
    
    return (CssDocument(decls), links)


def _parse_css_and_links(rules) -> 'Tuple[CssDocument, List[Link]]':
    links = []  # type: List[Link]
    for rule in rules:
        if isinstance(rule, ast.QualifiedRule) or isinstance(rule, ast.AtRule):
            if rule.content is not None:  # has been observed as None in the wild sometimes
                _parse_links_from_component_values(rule.content, links)
        
        # @import "**";
        if isinstance(rule, ast.AtRule) and rule.at_keyword == 'import':
            for token in rule.prelude:
                if isinstance(token, ast.StringToken):
                    links.append(StringTokenLink(token))
    
    return (CssDocument(rules), links)


# https://doc.courtbouillon.org/tinycss2/stable/api_reference.html#term-component-values
def _parse_links_from_component_values(tokens, links: list[Link]) -> None:
    for token in tokens:
        # url(**)
        if isinstance(token, ast.URLToken):
            links.append(UrlTokenLink(token))
        
        # url("**")
        elif isinstance(token, ast.FunctionBlock):
            if (token.lower_name == 'url' and 
                    len(token.arguments) == 1 and 
                    isinstance(token.arguments[0], ast.StringToken)):
                links.append(UrlFunctionLink(token.arguments[0]))


class CssDocument(Document):
    def __init__(self, nodes: Iterable[ast.Node]) -> None:
        self._nodes = nodes
    
    def __str__(self) -> str:
        return tinycss2.serialize([
            n for n in self._nodes
            if not isinstance(n, ast.ParseError)
        ])


class UrlTokenLink(Link):
    def __init__(self, token: ast.URLToken) -> None:
        self._token = token
        
        self.title = None
        self.type_title = 'CSS URL Reference'
        self.embedded = True
    
    def _get_relative_url(self) -> str:
        return self._token.value
    def _set_relative_url(self, url: str) -> None:
        self._token.value = url
        self._token.representation = 'url(%s)' % serialize_url(url)
    relative_url = property(_get_relative_url, _set_relative_url)


class UrlFunctionLink(Link):
    def __init__(self, token: ast.StringToken) -> None:
        self._token = token
        
        self.title = None
        self.type_title = 'CSS URL Reference'
        self.embedded = True
    
    def _get_relative_url(self) -> str:
        return self._token.value
    def _set_relative_url(self, url: str) -> None:
        self._token.value = url
        self._token.representation = serialize_string_value(url)
    relative_url = property(_get_relative_url, _set_relative_url)


class StringTokenLink(Link):
    def __init__(self, token: ast.StringToken) -> None:
        self._token = token
        
        self.title = None
        self.type_title = 'CSS @import'
        self.embedded = True
    
    def _get_relative_url(self) -> str:
        return self._token.value
    def _set_relative_url(self, url: str) -> None:
        self._token.value = url
        self._token.representation = '"%s"' % serialize_string_value(url)
    relative_url = property(_get_relative_url, _set_relative_url)
