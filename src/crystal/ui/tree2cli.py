"""
Provides a tree UI with an API similar to the 'tree' module, but with two differences:
* subtitles are supported (in addition to the regular title)
* the UI is a CLI instead of a GUI.
"""

class TreeView:
    def __init__(self):
        self.root = NodeView()
    
    def _get_root(self):
        return self._root
    def _set_root(self, value):
        self._root = value
        self._root._attach(self)
    root = property(_get_root, _set_root)
    
    def _refresh(self):
        def _print_node(parent, level):
            print('%s* %s' % ('  '*level, parent.title or '-'))
            print('%s  %s' % ('  '*level, parent.subtitle or '-'))
            for child in parent.children:
                _print_node(child, level+1)
        
        _print_node(self.root, 0)
        print()


class NodeView:
    def __init__(self):
        self._tree = None
        self._title = ''
        self._subtitle = ''
        self._children = []
    
    def _get_title(self):
        return self._title
    def _set_title(self, value):
        self._title = value
        if self._tree:
            self._tree._refresh()
    title = property(_get_title, _set_title)
    
    def _get_subtitle(self):
        return self._subtitle
    def _set_subtitle(self, value):
        self._subtitle = value
        if self._tree:
            self._tree._refresh()
    subtitle = property(_get_subtitle, _set_subtitle)
    
    def _get_children(self):
        return self._children
    def _set_children(self, value):
        self._children = value
        if self._tree:
            self._attach_children()
            self._tree._refresh()
    children = property(_get_children, _set_children)
    
    def append_child(self, child):
        self.children = self.children + [child]
    
    def _attach(self, tree):
        self._tree = tree
        self._attach_children()
    
    def _attach_children(self):
        for child in self._children:
            child._attach(self._tree)
