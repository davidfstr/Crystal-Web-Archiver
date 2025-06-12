"""
Facade for working with wx.TreeCtrl.

This abstraction provides:
* tree nodes that can be manipulated before being added to a tree
* delegate-style event handling on tree nodes
* access to the underlying "peer" objects (i.e. wx.TreeCtrl, tree item index)
"""

from __future__ import annotations

from collections.abc import Callable, Container
from crystal.progress import OpenProjectProgressListener
from crystal.util.bulkheads import run_bulkhead_call
from crystal.util.wx_bind import bind
from crystal.util.wx_error import (
    IGNORE_USE_AFTER_FREE, is_wrapped_object_deleted_error, WindowDeletedError,
    wrapped_object_deleted_error_ignored, wrapped_object_deleted_error_raising,
)
from crystal.util.xthreading import fg_affinity
from typing import cast, Dict, List, NewType, NoReturn, Optional
import wx

IconSet = tuple[tuple[wx.TreeItemIcon, wx.Bitmap], ...]
ImageIndex = NewType('ImageIndex', int)

_DEFAULT_TREE_ICON_SIZE = (16,16)

_DEFAULT_FOLDER_ICON_SET_CACHED = None
def DEFAULT_FOLDER_ICON_SET() -> IconSet:
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
    
    def __init__(self, parent_peer: wx.Window, *, name: str | None=None) -> None:
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
    
    # === Properties ===
    
    def _get_root(self) -> NodeView:
        return self._root
    def _set_root(self, value: NodeView) -> None:
        self._root = value
        self._root._attach(self._root_peer)
    root = property(_get_root, _set_root)
    
    # TODO: Rename: selection
    @property
    def selected_node(self) -> NodeView | None:
        return self.selected_node_in(self.peer)
    
    # TODO: Rename: selection_in
    @staticmethod
    def selected_node_in(tree_peer: wx.TreeCtrl) -> NodeView | None:
        try:
            selected_node_id = tree_peer.GetSelection()
        except Exception as e:
            if is_wrapped_object_deleted_error(e):
                return None
            else:
                raise
        if not selected_node_id.IsOk():
            return None
        return tree_peer.GetItemData(selected_node_id)
    
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
    
    # === Operations ===
    
    def expand(self, node_view):
        self.peer.Expand(node_view.peer.node_id)
    
    # Notified when any interesting event occurs on the peer
    def _dispatch_event(self, event: wx.TreeEvent) -> None:
        node_id = event.GetItem()
        node_view = self.peer.GetItemData(node_id)  # type: NodeView
        
        # Dispatch event to the node
        node_view._dispatch_event(event)
        
        # Dispatch event to my delegate
        if self.delegate:
            event_type_id = event.GetEventType()
            delegate_callable_attr = _EVENT_TYPE_ID_2_DELEGATE_CALLABLE_ATTR.get(event_type_id, None)
            if delegate_callable_attr and hasattr(self.delegate, delegate_callable_attr):
                run_bulkhead_call(
                    getattr(self.delegate, delegate_callable_attr),
                    event,
                    node_view
                )
    
    def dispose(self) -> None:
        self.delegate = None
        self.root.dispose()


class _OrderedTreeCtrl(wx.TreeCtrl):
    def OnCompareItems(self, item1: wx.TreeItemId, item2: wx.TreeItemId) -> int:
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
    DEFAULT_TEXT_COLOR = wx.Colour(0, 0, 0)  # black
    
    # Optimize per-instance memory use, since there may be very many NodeView objects
    __slots__ = (
        'delegate',
        'peer',
        '_title',
        '_text_color',
        '_bold',
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
        self._text_color = None  # type: Optional[wx.Colour]
        self._bold = False
        self._expandable = False
        self._icon_set_func = None  # type: Optional[Callable[[], Optional[IconSet]]]
        self._icon_set = None  # type: Optional[IconSet]
        self._children = []  # type: List[NodeView]
    
    # === Properties ===
    
    def _get_title(self) -> str:
        return self._title
    def _set_title(self, value: str) -> None:
        self._title = value
        if self.peer:
            self.peer.SetItemText(value)
    title = property(_get_title, _set_title)
    
    def _get_text_color(self) -> wx.Colour | None:
        return self._text_color
    def _set_text_color(self, value: wx.Colour | None) -> None:
        self._text_color = value
        if self.peer:
            self.peer.SetItemTextColour(value or self.DEFAULT_TEXT_COLOR)
    text_color = property(_get_text_color, _set_text_color)
    
    def _get_bold(self) -> bool:
        return self._bold
    def _set_bold(self, value: bool) -> None:
        self._bold = value
        if self.peer:
            self.peer.SetItemBold(value)
    bold = property(_get_bold, _set_bold)
    
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
    
    def _get_icon_set(self) -> IconSet | None:
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
            value: (
                IconSet | None |
                Callable[[], IconSet | None]  # deferred value
            )) -> None:
        if callable(value):
            self._icon_set_func = value
            self._icon_set = None
            return
        
        self._icon_set = value
        if self.peer:
            effective_value = (
                value
                if value is not None else (
                    DEFAULT_FOLDER_ICON_SET()
                    if self.expandable 
                    else _DEFAULT_FILE_ICON_SET()
                )
            )  # type: IconSet
            for (which, bitmap) in effective_value:
                self.peer.SetItemImage(self._tree.get_image_id_for_bitmap(bitmap), which)
    icon_set = property(_get_icon_set, _set_icon_set)
    
    def _get_children(self) -> list[NodeView]:
        return self._children
    def _set_children(self, new_children: list[NodeView]) -> None:
        self.set_children(new_children)
    children = cast('List[NodeView]', property(_get_children, _set_children))
    
    def set_children(self,
            new_children: list[NodeView],
            progress_listener: OpenProjectProgressListener | None=None,
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
                    for (index, child) in enumerate(new_children):
                        # TODO: Consider storing _order_index in a separate
                        #       child_2_order_index dict rather than annotating
                        #       the child object directly
                        child._order_index = index  # type: ignore[attr-defined]
                        child._attach(NodeViewPeer(self.peer._tree, self.peer.AppendItem('')))
                else:
                    # Replace existing children, preserving old ones that match new ones
                    
                    old_children_set = set(old_children)
                    
                    # 1. Delete some children
                    # 2. Capture selected node if it is in the deleted region
                    if True:
                        children_to_delete = old_children_set - set(new_children)
                        
                        on_selection_deleted = getattr(
                            self.delegate, 'on_selection_deleted', None
                        )  # type: Optional[Callable[[NodeView], Optional[NodeView]]]
                        old_selection_to_retarget = None  # type: Optional[NodeView]
                        if on_selection_deleted is not None:
                            old_selection = TreeView.selected_node_in(self.peer.tree_peer)
                            if old_selection is not None and old_selection.is_descendent_of_any(children_to_delete):
                                old_selection_to_retarget = old_selection  # capture
                        
                        for child in children_to_delete:
                            child._delete_peer_and_descendants()
                    
                    # Add some children
                    children_to_add = [new_child for new_child in new_children if new_child not in old_children_set]
                    for child in children_to_add:
                        child._attach(NodeViewPeer(self.peer._tree, self.peer.AppendItem('')))
                    
                    # Reorder children
                    for (index, child) in enumerate(new_children):
                        child._order_index = index  # type: ignore[attr-defined]
                    self.peer.SortChildren()
                    
                    # If old selected node was in the deleted region, try to
                    # intelligently retarget the selection to something else
                    if on_selection_deleted is not None and old_selection_to_retarget is not None:
                        new_selection = on_selection_deleted(old_selection_to_retarget)
                        if new_selection is None:
                            self.peer.tree_peer.Unselect()
                        else:
                            assert new_selection.peer is not None
                            new_selection.peer.SelectItem()
                    
            except WindowDeletedError:
                if IGNORE_USE_AFTER_FREE:
                    pass
                else:
                    raise
    
    def append_child(self, child: NodeView) -> None:
        # NOTE: The following is equivalent to:
        #           self.children = self.children + [child]
        self._children.append(child)
        if self.peer:
            try:
                child._attach(NodeViewPeer(self.peer._tree, self.peer.AppendItem('')))
            except WindowDeletedError:
                if IGNORE_USE_AFTER_FREE:
                    pass
                else:
                    raise
    
    @property
    def parent(self) -> NodeView | None:
        if not self.peer:
            raise ValueError('Cannot lookup parent when not attached to a tree.')
        parent_treeitemid = self.peer.GetItemParent()
        if not parent_treeitemid.IsOk():
            return None
        return self.peer.tree_peer.GetItemData(parent_treeitemid)
    
    def is_descendent_of_any(self, ancestor_node_views: Container[NodeView]) -> bool:
        cur_node_view = self  # type: Optional[NodeView]
        while cur_node_view is not None:
            if cur_node_view in ancestor_node_views:
                return True
            cur_node_view = cur_node_view.parent
        return False
    
    @property
    def _tree(self) -> TreeView:
        if not self.peer:
            raise ValueError('Not attached to a tree.')
        return self.peer._tree
    
    # === Operations ===
    
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
        if self._text_color is not None:
            self.text_color = self.text_color
        if self.bold:
            self.bold = self.bold
        self.expandable = self.expandable
        self.icon_set = self.icon_set
        self.set_children(self.children, _initial=True)
    
    def _delete_peer_and_descendants(self) -> None:
        if self.peer is None:
            return
        for child in self._children:
            child._delete_peer_and_descendants()
        self.peer.Delete()
        self.peer = None
    
    # Called when a wx.EVT_TREE_ITEM_* event occurs on this node
    def _dispatch_event(self, event) -> None:
        # Dispatch event to my delegate
        if self.delegate:
            event_type_id = event.GetEventType()
            delegate_callable_attr = _EVENT_TYPE_ID_2_DELEGATE_CALLABLE_ATTR.get(event_type_id, None)
            if delegate_callable_attr and hasattr(self.delegate, delegate_callable_attr):
                run_bulkhead_call(
                    getattr(self.delegate, delegate_callable_attr),
                    event
                )
    
    def dispose(self) -> None:
        self.delegate = None
        self.peer = None
        for c in self._children:
            c.dispose()
        self._children = []
    
    # === Utility ===
    
    def __repr__(self) -> str:
        return f'<NodeView {self.title!r}>'

NULL_NODE_VIEW = NodeView()


class NodeViewPeer(tuple):
    """
    Thin wrapper around a wxPython tree item that makes the underlying API safer to use.
    """
    
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
    
    @fg_affinity
    def SetItemData(self, obj: NodeView) -> None:
        node_id = self.node_id  # cache
        if node_id.IsOk():
            with wrapped_object_deleted_error_ignored():
                self.tree_peer.SetItemData(node_id, obj)
        else:
            self._did_access_not_ok_wx_object()
    
    @fg_affinity
    def SetItemText(self, text: str) -> None:
        node_id = self.node_id  # cache
        if node_id.IsOk():
            with wrapped_object_deleted_error_ignored():
                self.tree_peer.SetItemText(node_id, text)
        else:
            self._did_access_not_ok_wx_object()
    
    @fg_affinity
    def SetItemTextColour(self, colour: wx.Colour) -> None:
        node_id = self.node_id  # cache
        if node_id.IsOk():
            with wrapped_object_deleted_error_ignored():
                self.tree_peer.SetItemTextColour(node_id, colour)
        else:
            self._did_access_not_ok_wx_object()
    
    @fg_affinity
    def SetItemBold(self, bold: bool) -> None:
        node_id = self.node_id  # cache
        if node_id.IsOk():
            with wrapped_object_deleted_error_ignored():
                self.tree_peer.SetItemBold(node_id, bold)
        else:
            self._did_access_not_ok_wx_object()
    
    @fg_affinity
    def SetItemHasChildren(self, has: bool) -> None:
        node_id = self.node_id  # cache
        if node_id.IsOk():
            with wrapped_object_deleted_error_ignored():
                self.tree_peer.SetItemHasChildren(node_id, has)
        else:
            self._did_access_not_ok_wx_object()
    
    # TODO: Delete unused method
    @fg_affinity
    def GetFirstChild(self) -> tuple[wx.TreeItemId, object]:
        node_id = self.node_id  # cache
        if node_id.IsOk():
            with wrapped_object_deleted_error_raising(self._raise_no_longer_exists):
                return self.tree_peer.GetFirstChild(node_id)
        else:
            self._raise_no_longer_exists()
    
    @fg_affinity
    def GetItemParent(self) -> wx.TreeItemId:
        node_id = self.node_id  # cache
        if node_id.IsOk():
            with wrapped_object_deleted_error_raising(self._raise_no_longer_exists):
                return self.tree_peer.GetItemParent(node_id)
        else:
            self._raise_no_longer_exists()
    
    @fg_affinity
    def AppendItem(self, text: str, *args) -> wx.TreeItemId:
        node_id = self.node_id  # cache
        if node_id.IsOk():
            with wrapped_object_deleted_error_raising(self._raise_no_longer_exists):
                return self.tree_peer.AppendItem(node_id, text, *args)
        else:
            self._raise_no_longer_exists()
    
    @fg_affinity
    def SetItemImage(self, image: ImageIndex, which: wx.TreeItemIcon) -> None:
        node_id = self.node_id  # cache
        if node_id.IsOk():
            with wrapped_object_deleted_error_ignored():
                self.tree_peer.SetItemImage(node_id, image, which)
        else:
            self._did_access_not_ok_wx_object()
    
    @fg_affinity
    def Delete(self) -> None:
        node_id = self.node_id  # cache
        if node_id.IsOk():
            with wrapped_object_deleted_error_ignored():
                self.tree_peer.Delete(node_id)
        else:
            self._did_access_not_ok_wx_object()
    
    @fg_affinity
    def SortChildren(self) -> None:
        node_id = self.node_id  # cache
        if node_id.IsOk():
            with wrapped_object_deleted_error_ignored():
                self.tree_peer.SortChildren(node_id)
        else:
            self._did_access_not_ok_wx_object()
    
    @fg_affinity
    def SelectItem(self, select: bool=True) -> None:
        node_id = self.node_id  # cache
        if node_id.IsOk():
            with wrapped_object_deleted_error_ignored():
                self.tree_peer.SelectItem(node_id, select)
        else:
            self._did_access_not_ok_wx_object()
    
    @fg_affinity
    def IsSelected(self) -> bool:
        node_id = self.node_id  # cache
        if node_id.IsOk():
            with wrapped_object_deleted_error_ignored():
                return self.tree_peer.IsSelected(node_id)
            return False
        else:
            self._did_access_not_ok_wx_object()
            return False
    
    @fg_affinity
    def Collapse(self) -> None:
        node_id = self.node_id  # cache
        if node_id.IsOk():
            with wrapped_object_deleted_error_ignored():
                self.tree_peer.Collapse(node_id)
        else:
            self._did_access_not_ok_wx_object()
    
    def _raise_no_longer_exists(self) -> NoReturn:
        raise WindowDeletedError('Tree item no longer exists')
    
    def _did_access_not_ok_wx_object(self) -> None:
        if IGNORE_USE_AFTER_FREE:
            pass
        else:
            self._raise_no_longer_exists()
