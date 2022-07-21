"""
Additional collections on top of the built-in Python collections and the
extended collections in the standard `collections` module.
"""

from collections import OrderedDict


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
