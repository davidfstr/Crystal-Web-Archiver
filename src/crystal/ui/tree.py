"""
Facade for working with wx.TreeCtrl.

This abstraction provides:
* tree nodes that can be manipulated before being added to a tree
* delegate-style event handling on tree nodes
* access to the underlying "peer" objects (i.e. wx.TreeCtrl, tree item index)
"""

from __future__ import annotations

from crystal.progress import OpenProjectProgressListener
from crystal.util.wx_bind import bind
from crystal.util.wx_error import (
    is_wrapped_object_deleted_error,
    WindowDeletedError,
    wrapped_object_deleted_error_ignored,
    wrapped_object_deleted_error_raising
)
from crystal.util.xthreading import is_foreground_thread
from typing import Callable, Dict, List, NewType, NoReturn, Optional, Tuple, Union
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


class TreeView:
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
        # NOTE: In wxPython 4.2.0, wx.Bitmap icons will be superceded by wx.BitmapBundle,
        #       and wx.ImageList will be superceded by a plain list of wx.BitmapBundles.
        self._bitmap_2_image_id = dict()  # type: Dict[wx.Bitmap, ImageIndex]
        self._tree_imagelist = wx.ImageList(*_DEFAULT_TREE_ICON_SIZE)
        self.peer.AssignImageList(self._tree_imagelist)
        
        # Create root node's view
        self._root_peer = NodeViewPeer(self, self.peer.AddRoot(''))
        self.root = NodeView()
        
        # Listen for events on peer
        for event_type in _EVENT_TYPE_2_DELEGATE_CALLABLE_ATTR:
            bind(self.peer, event_type, self._dispatch_event, self.peer)
    
    def _get_root(self) -> NodeView:
        return self._root
    def _set_root(self, value: NodeView) -> None:
        self._root = value
        self._root._attach(self._root_peer)
    root = property(_get_root, _set_root)
    
    @property
    def selected_node(self) -> Optional[NodeView]:
        try:
            selected_node_id = self.peer.GetSelection()
        except Exception as e:
            if is_wrapped_object_deleted_error(e):
                return None
            else:
                raise
        return self.peer.GetItemData(selected_node_id) if selected_node_id.IsOk() else None
    
    def get_image_id_for_bitmap(self, bitmap: wx.Bitmap) -> ImageIndex:
        """
        Given a wx.Bitmap, returns an image ID suitable to use as an node icon.
        Calling this multiple times with the same wx.Bitmap will return the same image ID.
        """
        if bitmap in self._bitmap_2_image_id:
            image_id = self._bitmap_2_image_id[bitmap]
        else:
            image_id = self._tree_imagelist.Add(bitmap)
            self._bitmap_2_image_id[bitmap] = ImageIndex(image_id)
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
    
    def dispose(self) -> None:
        self.delegate = None
        self.root.dispose()


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


class NodeView:
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
    # Optimize per-instance memory use, since there may be very many NodeView objects
    __slots__ = (
        'delegate',
        'peer',
        '_title',
        '_expandable',
        '_icon_set_func',
        '_icon_set',
        '_children',
        '_order_index',
    )
    
    def __init__(self) -> None:
        self.delegate = None  # type: object
        self.peer = None  # type: Optional[NodeViewPeer]
        self._title = ''
        self._expandable = False
        self._icon_set_func = None  # type: Optional[Callable[[], Optional[IconSet]]]
        self._icon_set = None  # type: Optional[IconSet]
        self._children = []  # type: List[NodeView]
    
    def _get_title(self) -> str:
        return self._title
    def _set_title(self, value: str) -> None:
        self._title = value
        if self.peer:
            self.peer.SetItemText(value)
    title = property(_get_title, _set_title)
    
    def _get_expandable(self) -> bool:
        return self._expandable
    def _set_expandable(self, value: bool) -> None:
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
        if self._icon_set_func is not None:
            self._icon_set = self._icon_set_func()
            self._icon_set_func = None
        return self._icon_set
    def _set_icon_set(self,
            value: Union[
                Optional[IconSet],
                Callable[[], Optional[IconSet]]  # deferred value
            ]) -> None:
        if callable(value):
            self._icon_set_func = value
            self._icon_set = None
            return
        
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
            progress_listener: Optional[OpenProjectProgressListener]=None,
            *, _initial: bool=False
            ) -> None:
        """
        Raises:
        * CancelOpenProject
        """
        if progress_listener is not None:
            part_count = sum([len(c.children) for c in new_children])
            progress_listener.creating_entity_tree_nodes(part_count)
        
        old_children = self._children
        self._children = new_children
        if self.peer:
            try:
                if _initial or len(old_children) == 0:
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
                    
                    # Calculate whether needs_reorder
                    last_order_index = -1
                    for child in new_children:
                        cur_order_index = getattr(child, '_order_index', None)
                        if cur_order_index is None:
                            if last_order_index != -1:
                                # New child without order-index mixed with
                                # old children with order-index
                                needs_reorder = True
                                break
                            else:
                                # New child without order-index mixed with
                                # only other new children without order-index
                                continue
                        if cur_order_index < last_order_index:
                            needs_reorder = True
                            break
                        last_order_index = cur_order_index
                    else:
                        needs_reorder = False
                    
                    if needs_reorder:
                        # Reorder children
                        for (index, child) in enumerate(new_children):
                            child._order_index = index  # type: ignore[attr-defined]
                        self.peer.SortChildren()
            except WindowDeletedError:
                pass
    
    def append_child(self, child: NodeView) -> None:
        # NOTE: The following is equivalent to:
        #           self.children = self.children + [child]
        self._children.append(child)
        if self.peer:
            try:
                child._attach(NodeViewPeer(self.peer._tree, self.peer.AppendItem('')))
            except WindowDeletedError:
                pass
    
    @property
    def _tree(self) -> TreeView:
        if not self.peer:
            raise ValueError('Not attached to a tree.')
        return self.peer._tree
    
    def _attach(self, peer: NodeViewPeer) -> None:
        old_peer = self.peer  # capture
        if old_peer:
            raise ValueError(
                f'Already attached to a different peer: '
                f'old_peer={old_peer!r}, new_peer={peer!r}')
        self.peer = peer
        
        # Enable navigation from peer back to this view
        peer.SetItemData(self)
        
        # Trigger property logic to update peer
        self.title = self.title
        self.expandable = self.expandable
        self.icon_set = self.icon_set
        self.set_children(self.children, _initial=True)
    
    # Called when a wx.EVT_TREE_ITEM_* event occurs on this node
    def _dispatch_event(self, event):
        # Dispatch event to my delegate
        if self.delegate:
            event_type_id = event.GetEventType()
            delegate_callable_attr = _EVENT_TYPE_ID_2_DELEGATE_CALLABLE_ATTR.get(event_type_id, None)
            if delegate_callable_attr and hasattr(self.delegate, delegate_callable_attr):
                getattr(self.delegate, delegate_callable_attr)(event)
    
    def dispose(self) -> None:
        self.delegate = None
        self.peer = None
        for c in self._children:
            c.dispose()
        self._children = []

NULL_NODE_VIEW = NodeView()


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
        assert is_foreground_thread()
        node_id = self.node_id  # cache
        if node_id.IsOk():
            with wrapped_object_deleted_error_ignored():
                self.tree_peer.SetItemData(node_id, obj)
    
    def SetItemText(self, text: str) -> None:
        assert is_foreground_thread()
        node_id = self.node_id  # cache
        if node_id.IsOk():
            with wrapped_object_deleted_error_ignored():
                self.tree_peer.SetItemText(node_id, text)
    
    def SetItemHasChildren(self, has: bool) -> None:
        assert is_foreground_thread()
        node_id = self.node_id  # cache
        if node_id.IsOk():
            with wrapped_object_deleted_error_ignored():
                self.tree_peer.SetItemHasChildren(node_id, has)
    
    def GetFirstChild(self) -> Tuple[wx.TreeItemId, object]:
        assert is_foreground_thread()
        node_id = self.node_id  # cache
        if node_id.IsOk():
            with wrapped_object_deleted_error_raising(self._raise_no_longer_exists):
                return self.tree_peer.GetFirstChild(node_id)
        else:
            self._raise_no_longer_exists()
    
    def AppendItem(self, text: str, *args) -> wx.TreeItemId:
        assert is_foreground_thread()
        node_id = self.node_id  # cache
        if node_id.IsOk():
            with wrapped_object_deleted_error_raising(self._raise_no_longer_exists):
                return self.tree_peer.AppendItem(node_id, text, *args)
        else:
            self._raise_no_longer_exists()
    
    def SetItemImage(self, image: ImageIndex, which: wx.TreeItemIcon) -> None:
        assert is_foreground_thread()
        node_id = self.node_id  # cache
        if node_id.IsOk():
            with wrapped_object_deleted_error_ignored():
                self.tree_peer.SetItemImage(node_id, image, which)
    
    def Delete(self) -> None:
        assert is_foreground_thread()
        node_id = self.node_id  # cache
        if node_id.IsOk():
            with wrapped_object_deleted_error_ignored():
                self.tree_peer.Delete(node_id)
    
    def SortChildren(self) -> None:
        assert is_foreground_thread()
        node_id = self.node_id  # cache
        if node_id.IsOk():
            with wrapped_object_deleted_error_ignored():
                self.tree_peer.SortChildren(node_id)
    
    def SelectItem(self, select: bool=True) -> None:
        assert is_foreground_thread()
        node_id = self.node_id  # cache
        if node_id.IsOk():
            with wrapped_object_deleted_error_ignored():
                self.tree_peer.SelectItem(node_id, select)
    
    def IsSelected(self) -> bool:
        assert is_foreground_thread()
        node_id = self.node_id  # cache
        if node_id.IsOk():
            with wrapped_object_deleted_error_ignored():
                return self.tree_peer.IsSelected(node_id)
            return False
        else:
            return False
    
    def _raise_no_longer_exists(self) -> NoReturn:
        raise WindowDeletedError('Tree item no longer exists')
