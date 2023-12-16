"""
Additional collections on top of the built-in Python collections and the
extended collections in the standard `collections` module.
"""

from collections import OrderedDict
import sys
from typing import cast, Dict, TypeVar


class simpleorderedset:
    """Ordered set that supports a limited set of operations."""
    
    def __init__(self):
        self.set = set()
        self.items = []
        
    def add(self, value):
        old_size = len(self.set)
        self.set.append(value)
        new_size = len(self.set)
        if new_size > old_size:
            self.items.append(value)
    
    def __contains__(self, value):
        return value in self.set
    
    def __len__(self):
        return len(self.items)
    
    def __iter__(self):
        return self.items.__iter__()


class defaultordereddict(OrderedDict):
    def __init__(self, default_factory=None):
        super().__init__()
        self.default_factory = default_factory
    
    def __missing__(self, key):
        if self.default_factory is None:
            raise KeyError(key)
        value = self.default_factory()
        self[key] = value
        return value


_K = TypeVar('_K')
_V = TypeVar('_V')

def as_ordereddict(d: Dict[_K, _V]) -> 'OrderedDict[_K, _V]':
    assert sys.version_info >= (3, 8)
    return cast('OrderedDict[_K, _V]', d)
