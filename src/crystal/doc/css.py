"""
Parses CSS documents.
"""

from __future__ import annotations

from crystal.doc.generic import Document, Link
import tinycss2
from tinycss2 import ast
from tinycss2.serializer import serialize_string_value, serialize_url


def parse_css_and_links(
        body_bytes: bytes, 
        declared_charset: str=None
        ) -> tuple[CssDocument, list[Link]]:
    (rules, encoding) = tinycss2.parse_stylesheet_bytes(
        body_bytes,
        protocol_encoding=declared_charset)
    
    links = []  # type: list[Link]
    for rule in rules:
        if isinstance(rule, ast.QualifiedRule) or isinstance(rule, ast.AtRule):
            if rule.content is not None:  # has been observed as None in the wild sometimes
                for token in rule.content:
                    # url(**)
                    if isinstance(token, ast.URLToken):
                        links.append(UrlTokenLink(token))
                    
                    # url("**")
                    elif isinstance(token, ast.FunctionBlock):
                        if (token.lower_name == 'url' and 
                                len(token.arguments) == 1 and 
                                isinstance(token.arguments[0], ast.StringToken)):
                            links.append(UrlFunctionLink(token.arguments[0]))
        
        # @import "**";
        if isinstance(rule, ast.AtRule) and rule.at_keyword == 'import':
            for token in rule.prelude:
                if isinstance(token, ast.StringToken):
                    links.append(StringTokenLink(token))
    
    return (CssDocument(rules), links)


class CssDocument(Document):
    def __init__(self, rules) -> None:
        self._rules = rules
    
    def __str__(self) -> str:
        return tinycss2.serialize(self._rules)


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
