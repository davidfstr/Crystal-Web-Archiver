"""
Facade for working with wx.TreeCtrl.

This abstraction provides:
* tree nodes that can be manipulated before being added to a tree
* delegate-style event handling on tree nodes
* access to the underlying "peer" objects (i.e. wx.TreeCtrl, tree item index)
"""

from __future__ import annotations

from crystal.progress import OpenProjectProgressListener
from typing import Dict, List, NewType, Optional, Tuple
import wx

IconSet = Tuple[Tuple[wx.TreeItemIcon, wx.Bitmap], ...]
ImageIndex = NewType('ImageIndex', int)

_DEFAULT_TREE_ICON_SIZE = (16,16)

_DEFAULT_FOLDER_ICON_SET_CACHED = None
def _DEFAULT_FOLDER_ICON_SET() -> IconSet:
    global _DEFAULT_FOLDER_ICON_SET_CACHED  # necessary to write to a module global
    if not _DEFAULT_FOLDER_ICON_SET_CACHED:
        _DEFAULT_FOLDER_ICON_SET_CACHED = (
            (wx.TreeItemIcon_Normal,   wx.ArtProvider.GetBitmap(wx.ART_FOLDER,      wx.ART_OTHER, _DEFAULT_TREE_ICON_SIZE)),
            (wx.TreeItemIcon_Expanded, wx.ArtProvider.GetBitmap(wx.ART_FILE_OPEN,   wx.ART_OTHER, _DEFAULT_TREE_ICON_SIZE)),
        )
    return _DEFAULT_FOLDER_ICON_SET_CACHED

_DEFAULT_FILE_ICON_SET_CACHED = None
def _DEFAULT_FILE_ICON_SET() -> IconSet:
    global _DEFAULT_FILE_ICON_SET_CACHED    # necessary to write to a module global
    if not _DEFAULT_FILE_ICON_SET_CACHED:
        _DEFAULT_FILE_ICON_SET_CACHED = (
            (wx.TreeItemIcon_Normal,   wx.ArtProvider.GetBitmap(wx.ART_NORMAL_FILE, wx.ART_OTHER, _DEFAULT_TREE_ICON_SIZE)),
        )
    return _DEFAULT_FILE_ICON_SET_CACHED

# Maps wx.EVT_TREE_ITEM_* events to names of methods on `NodeView.delegate`
# that will be called (if they exist) upon the reception of such an event.
_EVENT_TYPE_2_DELEGATE_CALLABLE_ATTR = {
    wx.EVT_TREE_ITEM_EXPANDED: 'on_expanded',
    wx.EVT_TREE_ITEM_RIGHT_CLICK: 'on_right_click',
    # TODO: Consider adding support for additional wx.EVT_TREE_ITEM_* event types
}
_EVENT_TYPE_ID_2_DELEGATE_CALLABLE_ATTR = dict(zip(
    [et.typeId for et in _EVENT_TYPE_2_DELEGATE_CALLABLE_ATTR],
    _EVENT_TYPE_2_DELEGATE_CALLABLE_ATTR.values()
))

class TreeView(object):
    """
    Displays a tree of nodes.
    
    Acts as a facade for manipulating an underlying wx.TreeCtrl.
    For advanced customization, this wx.TreeCtrl may be accessed through the `peer` attribute.
    
    Automatically creates a root NodeView (accessible via the `root` attribute),
    which will not be displayed 
    """
    
    def __init__(self, parent_peer: wx.Window, *, name: str=None) -> None:
        self.delegate = None  # type: object
        self.peer = _OrderedTreeCtrl(
            parent_peer,
            style=wx.TR_DEFAULT_STYLE|wx.TR_HIDE_ROOT,
            **(
                dict(name=name)
                if name is not None else
                dict()
            ))  # type: wx.TreeCtrl
        
        # Setup node image registration
        self.bitmap_2_image_id = dict()  # type: Dict[wx.Bitmap, ImageIndex]
        tree_icon_size = _DEFAULT_TREE_ICON_SIZE
        self.tree_imagelist = wx.ImageList(tree_icon_size[0], tree_icon_size[1])
        self.peer.AssignImageList(self.tree_imagelist)
        
        # Create root node's view
        self._root_peer = NodeViewPeer(self, self.peer.AddRoot(''))
        self.root = NodeView()
        
        # Listen for events on peer
        for event_type in _EVENT_TYPE_2_DELEGATE_CALLABLE_ATTR:
            self.peer.Bind(event_type, self._dispatch_event, self.peer)
    
    def _get_root(self) -> NodeView:
        return self._root
    def _set_root(self, value: NodeView) -> None:
        self._root = value
        self._root._attach(self._root_peer)
    root = property(_get_root, _set_root)
    
    @property
    def selected_node(self) -> Optional[NodeView]:
        selected_node_id = self.peer.GetSelection()
        return self.peer.GetItemData(selected_node_id) if selected_node_id.IsOk() else None
    
    def get_image_id_for_bitmap(self, bitmap: wx.Bitmap) -> ImageIndex:
        """
        Given a wx.Bitmap, returns an image ID suitable to use as an node icon.
        Calling this multiple times with the same wx.Bitmap will return the same image ID.
        """
        if bitmap in self.bitmap_2_image_id:
            image_id = self.bitmap_2_image_id[bitmap]
        else:
            image_id = self.tree_imagelist.Add(bitmap)
            self.bitmap_2_image_id[bitmap] = ImageIndex(image_id)
        return image_id
    
    def expand(self, node_view):
        self.peer.Expand(node_view.peer.node_id)
    
    # Notified when any interesting event occurs on the peer
    def _dispatch_event(self, event):
        node_id = event.GetItem()
        node_view = self.peer.GetItemData(node_id)  # type: NodeView
        
        # Dispatch event to the node
        node_view._dispatch_event(event)
        
        # Dispatch event to my delegate
        if self.delegate:
            event_type_id = event.GetEventType()
            delegate_callable_attr = _EVENT_TYPE_ID_2_DELEGATE_CALLABLE_ATTR.get(event_type_id, None)
            if delegate_callable_attr and hasattr(self.delegate, delegate_callable_attr):
                getattr(self.delegate, delegate_callable_attr)(event, node_view)

class _OrderedTreeCtrl(wx.TreeCtrl):
    def OnCompareItems(self, item1, item2):
        (item1_view, item2_view) = (self.GetItemData(item1), self.GetItemData(item2))
        assert isinstance(item1_view, NodeView) and isinstance(item2_view, NodeView)
        (order_index_1, order_index_2) = (
            getattr(item1_view, '_order_index', None),
            getattr(item2_view, '_order_index', None)
        )
        if order_index_1 is None and order_index_2 is None:
            return 0
        assert isinstance(order_index_1, int) and isinstance(order_index_2, int)
        return order_index_1 - order_index_2

class NodeView(object):
    """
    Node that is (or will be) in a TreeView.
    
    Acts as a facade for manipulating a wxTreeItemId in a wxTreeCtrl. Allows modifications even
    if the underlying wxTreeItemId doesn't yet exist. For advanced customization, the wxTreeItemId
    and wxTreeCtrl may be accessed through the `peer` attribute (which is a `NodeViewPeer`)).
    
    To receive events that occur on a NodeView, assign an object to the `delegate` attribute.
    * For each event of interest, this object should implement methods of the signature:
          def on_eventname(self, event)
    * The `event` object passed to this method is a wx.Event object that can be inspected for more
      information about the event.
    * The full list of supported event names is given by
      `_EVENT_TYPE_ID_2_DELEGATE_CALLABLE_ATTR.values()`.
    """
    
    def __init__(self) -> None:
        self.delegate = None  # type: object
        self.peer = None  # type: Optional[NodeViewPeer]
        self._title = ''
        self._expandable = False
        self._icon_set = None  # type: Optional[IconSet]
        self._children = []  # type: List[NodeView]
    
    def _get_title(self):
        return self._title
    def _set_title(self, value):
        self._title = value
        if self.peer:
            self.peer.SetItemText(value)
    title = property(_get_title, _set_title)
    
    def _get_expandable(self):
        return self._expandable
    def _set_expandable(self, value):
        self._expandable = value
        if self.peer:
            self.peer.SetItemHasChildren(value)
            # If using default icon set, force it to update since it depends on the expandable state
            if self.icon_set is None:
                self.icon_set = self.icon_set
    expandable = property(_get_expandable, _set_expandable)
    
    def _get_icon_set(self) -> Optional[IconSet]:
        """
        A sequence of (wx.TreeItemIcon, wx.Bitmap) tuples, specifying the set of icons applicable
        to this node in various states. If None, then a default icon set is used, depending on
        whether this node is expandable.
        """
        return self._icon_set
    def _set_icon_set(self, value: Optional[IconSet]) -> None:
        self._icon_set = value
        if self.peer:
            effective_value = (
                value
                if value is not None else (
                    _DEFAULT_FOLDER_ICON_SET()
                    if self.expandable 
                    else _DEFAULT_FILE_ICON_SET()
                )
            )  # type: IconSet
            for (which, bitmap) in effective_value:
                self.peer.SetItemImage(self._tree.get_image_id_for_bitmap(bitmap), which)
    icon_set = property(_get_icon_set, _set_icon_set)
    
    def _get_children(self) -> List[NodeView]:
        return self._children
    def _set_children(self, new_children: List[NodeView]) -> None:
        self.set_children(new_children)
    children = property(_get_children, _set_children)
    
    def set_children(self,
            new_children: List[NodeView],
            progress_listener: Optional[OpenProjectProgressListener]=None) -> None:
        if progress_listener is not None:
            part_count = sum([len(c.children) for c in new_children])
            progress_listener.creating_entity_tree_nodes(part_count)
        
        old_children = self._children
        self._children = new_children
        if self.peer:
            if not self.peer.GetFirstChild()[0].IsOk():
                # Add initial children
                part_index = 0
                for (index, child) in enumerate(new_children):
                    # TODO: Consider storing _order_index in a separate
                    #       child_2_order_index dict rather than annotating
                    #       the child object directly
                    child._order_index = index  # type: ignore[attr-defined]
                    if progress_listener is not None:
                        progress_listener.creating_entity_tree_node(part_index)
                        part_index += len(child.children)
                    child._attach(NodeViewPeer(self.peer._tree, self.peer.AppendItem('')))
            else:
                # Replace existing children, preserving old ones that match new ones
                old_children_set = set(old_children)
                
                children_to_delete = old_children_set - set(new_children)
                for child in children_to_delete:
                    if child.peer is not None:
                        child.peer.Delete()
                
                children_to_add = [new_child for new_child in new_children if new_child not in old_children_set]
                for child in children_to_add:
                    child._attach(NodeViewPeer(self.peer._tree, self.peer.AppendItem('')))
                
                # Reorder children
                for (index, child) in enumerate(new_children):
                    child._order_index = index  # type: ignore[attr-defined]
                self.peer.SortChildren()
    
    def append_child(self, child: NodeView) -> None:
        self.children = self.children + [child]
    
    @property
    def _tree(self) -> TreeView:
        if not self.peer:
            raise ValueError('Not attached to a tree.')
        return self.peer._tree
    
    def _attach(self, peer: NodeViewPeer) -> None:
        if self.peer:
            raise ValueError('Already attached to a different peer.')
        self.peer = peer
        
        # Enable navigation from peer back to this view
        peer.SetItemData(self)
        
        # Trigger property logic to update peer
        self.title = self.title
        self.expandable = self.expandable
        self.icon_set = self.icon_set
        self.children = self.children
    
    # Called when a wx.EVT_TREE_ITEM_* event occurs on this node
    def _dispatch_event(self, event):
        # Dispatch event to my delegate
        if self.delegate:
            event_type_id = event.GetEventType()
            delegate_callable_attr = _EVENT_TYPE_ID_2_DELEGATE_CALLABLE_ATTR.get(event_type_id, None)
            if delegate_callable_attr and hasattr(self.delegate, delegate_callable_attr):
                getattr(self.delegate, delegate_callable_attr)(event)

class NodeViewPeer(tuple):
    def __new__(cls, tree: TreeView, node_id: wx.TreeItemId):
        return tuple.__new__(cls, (tree, node_id))
    
    # TODO: Only the 'tree_peer' should be stored.
    #       Remove use of this property and update constructor.
    @property
    def _tree(self) -> TreeView:
        return self[0]
    
    @property
    def tree_peer(self) -> wx.TreeCtrl:
        return self._tree.peer
    
    @property
    def node_id(self) -> wx.TreeItemId:
        return self[1]
    
    def SetItemData(self, obj: NodeView) -> None:
        node_id = self.node_id  # cache
        if node_id.IsOk():
            self.tree_peer.SetItemData(node_id, obj)
    
    def SetItemText(self, text: str) -> None:
        node_id = self.node_id  # cache
        if node_id.IsOk():
            self.tree_peer.SetItemText(node_id, text)
    
    def SetItemHasChildren(self, has: bool) -> None:
        node_id = self.node_id  # cache
        if node_id.IsOk():
            self.tree_peer.SetItemHasChildren(node_id, has)
    
    def GetFirstChild(self) -> Tuple[wx.TreeItemId, object]:
        node_id = self.node_id  # cache
        if node_id.IsOk():
            return self.tree_peer.GetFirstChild(node_id)
        else:
            raise ValueError('Tree item no longer exists')
    
    def AppendItem(self, text: str, *args) -> wx.TreeItemId:
        node_id = self.node_id  # cache
        if node_id.IsOk():
            return self.tree_peer.AppendItem(node_id, text, *args)
        else:
            raise ValueError('Tree item no longer exists')
    
    def SetItemImage(self, image: ImageIndex, which: wx.TreeItemIcon) -> None:
        node_id = self.node_id  # cache
        if node_id.IsOk():
            self.tree_peer.SetItemImage(node_id, image, which)
    
    def Delete(self) -> None:
        node_id = self.node_id  # cache
        if node_id.IsOk():
            self.tree_peer.Delete(node_id)
    
    def SortChildren(self) -> None:
        node_id = self.node_id  # cache
        if node_id.IsOk():
            self.tree_peer.SortChildren(node_id)
