"""
Provides a tree UI with an API similar to the 'tree' module, but with one difference:
* subtitles are supported (in addition to the regular title)
"""

# Clients should be able to import TreeView from this package
from crystal.ui.tree import NodeView as NodeView1
from crystal.ui.tree import TreeView


class NodeView(NodeView1):
    # Optimize per-instance memory use, since there may be very many NodeView objects
    __slots__ = (
        '__title',
        '__subtitle',
    )
    
    def __init__(self) -> None:
        super().__init__()
        self.__title = ''
        self.__subtitle = ''
    
    def _get_title(self) -> str:
        return self.__title
    def _set_title(self, value: str) -> None:
        self.__title = value
        self._update_base_title()
    title = property(_get_title, _set_title)
    
    def _get_subtitle(self) -> str:
        return self.__subtitle
    def _set_subtitle(self, value: str) -> None:
        self.__subtitle = value
        self._update_base_title()
    subtitle = property(_get_subtitle, _set_subtitle)
    
    def _update_base_title(self) -> None:
        subtitle = self.__subtitle  # cache
        combined_title = (
            '{} -- {}'.format(self.__title, subtitle)
            if len(subtitle) != 0
            else self.__title
        )
        # HACK: Call property implementation directly, since calling properties
        #       on the super() object doesn't seem to work.
        super()._set_title(combined_title)

NULL_NODE_VIEW = NodeView()
