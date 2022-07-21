"""
Provides a tree UI with an API similar to the 'tree' module, but with one difference:
* subtitles are supported (in addition to the regular title)
"""

from crystal.ui.tree import NodeView as NodeView1

# Clients should be able to import TreeView from this package
from crystal.ui.tree import TreeView


class NodeView(NodeView1):
    def __init__(self):
        super().__init__()
        self.__title = ''
        self.__subtitle = ''
    
    def _get_title(self):
        return self.__title
    def _set_title(self, value):
        self.__title = value
        self._update_base_title()
    title = property(_get_title, _set_title)
    
    def _get_subtitle(self):
        return self.__subtitle
    def _set_subtitle(self, value):
        self.__subtitle = value
        self._update_base_title()
    subtitle = property(_get_subtitle, _set_subtitle)
    
    def _update_base_title(self):
        # HACK: Call property implementation directly, since calling properties
        #       on the super() object doesn't seem to work.
        super()._set_title('%s -- %s' % (self.__title, self.__subtitle))
