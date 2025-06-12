from __future__ import annotations

from concurrent.futures import Future
from crystal.browser.icons import (
    BADGED_ART_PROVIDER_TREE_NODE_ICON, BADGED_TREE_NODE_ICON, TREE_NODE_ICONS,
)
from crystal.doc.generic import Link
from crystal.doc.html.soup import TEXT_LINK_TYPE_TITLE
from crystal.model import (
    Project, ProjectHasTooManyRevisionsError, Resource, ResourceGroup,
    ResourceGroupSource, ResourceRevision, RevisionBodyMissingError,
    RevisionDeletedError, RootResource,
)
from crystal.progress import (
    CancelLoadUrls, DummyOpenProjectProgressListener,
    OpenProjectProgressListener,
)
from crystal.task import (
    CannotDownloadWhenProjectReadOnlyError, ProjectFreeSpaceTooLowError,
)
# TODO: Expand this star import
from crystal.ui.tree import *
from crystal.util.bulkheads import (
    Bulkhead, capture_crashes_to, capture_crashes_to_self,
    capture_crashes_to_stderr, CrashReason, run_bulkhead_call,
)
from crystal.util.notimplemented import NotImplemented, NotImplementedType
from crystal.util.url_prefix import (
    get_url_directory_prefix_for, get_url_domain_prefix_for,
)
from crystal.util.wx_bind import bind
from crystal.util.wx_treeitem_gettooltip import (
    EVT_TREE_ITEM_GETTOOLTIP, GetTooltipEvent,
)
from crystal.util.xcollections.ordereddict import defaultordereddict
from crystal.util.xthreading import bg_call_later, fg_call_later
import time
from typing import cast, Dict, final, Literal, Optional, Tuple, Union
from typing_extensions import override
from urllib.parse import urljoin
import wx

DeferrableResourceGroupSource = Union[
    ResourceGroupSource,
    Callable[[], ResourceGroupSource]
]


class EntityTree(Bulkhead):
    """
    Displays a tree of top-level project entities.
    """
    _ID_SET_DOMAIN_PREFIX = 101
    _ID_SET_DIRECTORY_PREFIX = 102
    _ID_CLEAR_PREFIX = 103
    
    def __init__(self,
            parent_peer: wx.Window,
            project: Project,
            progress_listener: OpenProjectProgressListener) -> None:
        """
        Raises:
        * CancelOpenProject
        """
        self._crash_reason = None  # type: Optional[CrashReason]
        
        self.view = TreeView(parent_peer, name='cr-entity-tree')
        self.view.delegate = self
        self.root = RootNode(project, self.view.root, progress_listener)
        self._project = project
        self._group_nodes_need_updating = False
        self._right_clicked_node = None  # type: Optional[Node]
        
        project.listeners.append(self)
        
        self.peer.SetInitialSize((550, 300))
        
        bind(self.peer, wx.EVT_MOTION, self._on_mouse_motion)
        # For tests only
        bind(self.peer, EVT_TREE_ITEM_GETTOOLTIP, self._on_get_tooltip_event)
        
        # Select first top-level entity initially, if available
        root_children = self.root.children
        if len(root_children) >= 1:
            root_children[0].view.peer.SelectItem()
    
    # === Bulkhead ===
    
    def _get_crash_reason(self) -> CrashReason | None:
        return self._crash_reason
    def _set_crash_reason(self, reason: CrashReason | None) -> None:
        from crystal.task import CrashedTask
        
        if reason is None:
            self._crash_reason = None
        else:
            if self._crash_reason is not None:
                # Ignore subsequent crashes until the first one is dismissed
                return
            self._crash_reason = reason
            
            # Report crash to Task Tree
            def dismiss_crash_reason() -> None:
                assert not crash_reason_view.complete
                
                # Recreate entity tree children
                self.root.set_children([])
                self.root.update_children()
                
                # Remove the CrashedTask soon
                crash_reason_view.finish()
                
                # Clear the crash reason
                self.crash_reason = None
            crash_reason_view = CrashedTask(
                'Updating entity tree',
                reason,
                dismiss_crash_reason,
                dismiss_action_title='Refresh')
            self._project.add_task(crash_reason_view)
    crash_reason = cast(Optional[CrashReason], property(_get_crash_reason, _set_crash_reason))
    
    # === Properties ===
    
    @property
    def peer(self) -> wx.TreeCtrl:
        """The wx.TreeCtrl controlled by this class."""
        return self.view.peer
    
    @property
    def selected_entity(self) -> NodeEntity | None:
        selected_node = self.selected_node
        if selected_node is None:
            return None
        return selected_node.entity
    
    @property
    def selected_node(self) -> Node | None:
        selected_node_view = self.view.selected_node
        if selected_node_view is None:
            return None
        selected_node = Node.for_node_view(selected_node_view)
        return selected_node
    
    @property
    def source_of_selection(self) -> ResourceGroupSource:
        selected_node_view = self.view.selected_node
        if selected_node_view is None:
            return None
        return Node.for_node_view(selected_node_view).source
    
    @property
    def name_of_selection(self) -> str | None:
        entity = self.selected_entity
        if isinstance(entity, (RootResource, ResourceGroup)):
            return entity.name
        elif isinstance(entity, Resource):
            selected_node_view = self.view.selected_node
            if selected_node_view is None:
                return None
            selected_node = Node.for_node_view(selected_node_view)
            if isinstance(selected_node, LinkedResourceNode):
                for link in selected_node.links:
                    if (link.type_title == TEXT_LINK_TYPE_TITLE and 
                            link.title is not None and
                            link.title != ''):
                        return link.title
                return None
            else:
                return None
        else:
            return None
    
    # === Updates ===
    
    # TODO: Should this be marked with: @capture_crashes_to_self
    def update(self):
        """
        Updates the nodes in this tree, usually due to a project change.
        """
        self.root.update_descendants()
    
    # === Events: Resource Lifecycle ===
    
    @capture_crashes_to_self
    def resource_did_instantiate(self, resource: Resource) -> None:
        # TODO: Optimize to only refresh those groups that could potentially
        #       be affected by this particular resource being instantiated
        self._refresh_group_nodes()
    
    def _refresh_group_nodes(self) -> None:
        # Coalesce multiple refreshes that happen in succession
        if self._group_nodes_need_updating:
            return
        else:
            self._group_nodes_need_updating = True
            @capture_crashes_to_stderr
            def fg_task_later() -> None:
                try:
                    try:
                        root_children = self.root.children
                    except BaseException as e:
                        self.root.crash_reason = e
                        return
                    for rgn in root_children:
                        if isinstance(rgn, ResourceGroupNode):
                            run_bulkhead_call(rgn.update_children)
                finally:
                    self._group_nodes_need_updating = False
            fg_call_later(fg_task_later, force_later=True)
    
    # === Events: Resource Revision Lifecycle ===
    
    @capture_crashes_to_self
    def resource_revision_did_instantiate(self, revision: ResourceRevision) -> None:
        @capture_crashes_to(self)
        def fg_task() -> None:
            self.root.update_icon_set_of_descendants_with_resource(revision.resource)
        fg_call_later(fg_task)
    
    # === Events: Root Resource Lifecycle ===
    
    @capture_crashes_to_self
    def root_resource_did_instantiate(self, root_resource: RootResource) -> None:
        selection_was_empty = self.view.selected_node in [None, self.view.root]  # capture
        
        self.update()
        
        if selection_was_empty:
            # Select the newly-created entity
            for child in self.root.children:
                if child.entity == root_resource:
                    child.view.peer.SelectItem()
                    break
    
    @capture_crashes_to_self
    # TODO: Do not recommend asserting that a listener method will be called
    #       from any particular thread
    @fg_affinity
    def root_resource_did_forget(self, root_resource: RootResource) -> None:
        self.update()
    
    # === Events: Resource Group Lifecycle ===
    
    @capture_crashes_to_self
    def resource_group_did_instantiate(self, group: ResourceGroup) -> None:
        selection_was_empty = self.view.selected_node in [None, self.view.root]  # capture
        
        self.update()
        
        if selection_was_empty:
            # Select the newly-created entity
            for child in self.root.children:
                if child.entity == group:
                    child.view.peer.SelectItem()
                    break
        
        # Some badges related to the ResourceGroup.do_not_download status
        # may need to be updated
        @capture_crashes_to(self)
        def fg_task() -> None:
            self.root.update_icon_set_of_descendants_in_group(group)
        fg_call_later(fg_task)
    
    @capture_crashes_to_self
    # TODO: Do not recommend asserting that a listener method will be called
    #       from any particular thread
    @fg_affinity
    def resource_group_did_change_do_not_download(self, group: ResourceGroup) -> None:
        self.root.update_icon_set_of_descendants_in_group(group)
    
    @capture_crashes_to_self
    # TODO: Do not recommend asserting that a listener method will be called
    #       from any particular thread
    @fg_affinity
    def resource_group_did_forget(self, group: ResourceGroup) -> None:
        self.update()
        
        # Some badges related to the ResourceGroup.do_not_download status
        # may need to be updated
        self.root.update_icon_set_of_descendants_in_group(group)
    
    # === Event: Min Fetch Date Did Change ===
    
    @capture_crashes_to_self
    def min_fetch_date_did_change(self) -> None:
        @capture_crashes_to(self)
        def fg_task() -> None:
            self.root.update_icon_set_of_descendants()
        fg_call_later(fg_task)
    
    # === Event: Right Click ===
    
    @capture_crashes_to_self
    def on_right_click(self, event: wx.MouseEvent, node_view: NodeView) -> None:
        node = Node.for_node_view(node_view)
        self._right_clicked_node = node
        
        # Create popup menu
        menu = wx.Menu()
        (cup_mis, on_attach_menuitems) = \
            self.create_change_url_prefix_menuitems_for(node, menu_type='popup')
        for mi in cup_mis:
            menu.Append(mi)
        on_attach_menuitems()
        bind(menu, wx.EVT_MENU, self._on_popup_menuitem_selected)
        
        # Show popup menu
        self.peer.PopupMenu(menu)
        menu.Destroy()
    
    def create_change_url_prefix_menuitems_for(self,
            node: Node | None,
            *, menu_type: Literal['popup', 'top_level']
            ) -> Tuple[list[wx.MenuItem], Callable[[], None]]:
        menuitems = []  # type: List[wx.MenuItem]
        on_attach_menuitems = lambda: None
        def append_disabled_menuitem() -> None:
            nonlocal on_attach_menuitems
            mi = wx.MenuItem(None, self._ID_SET_DOMAIN_PREFIX, 'Set As Default Domain')
            # NOTE: wxGTK does not allow altering a wx.MenuItem's Enabled
            #       state until it is attached to a wx.Menu
            on_attach_menuitems = lambda: mi.Enable(False)
            menuitems.append(mi)
        if isinstance(node, (_ResourceNode, ResourceGroupNode)):
            selection_urllike = self._url_or_url_prefix_for(node)
            selection_domain_prefix = get_url_domain_prefix_for(selection_urllike)
            selection_dir_prefix = get_url_directory_prefix_for(selection_urllike)
            if selection_domain_prefix is None:
                append_disabled_menuitem()
            else:
                if self._project.default_url_prefix == selection_domain_prefix:
                    menuitems.append(wx.MenuItem(
                        None, self._ID_CLEAR_PREFIX, 'Clear Default Domain'))
                else:
                    prefix_descriptor = self._try_remove_http_scheme(selection_domain_prefix)
                    menuitems.append(wx.MenuItem(
                        None,
                        self._ID_SET_DOMAIN_PREFIX,
                        f'Set As Default Domain: {prefix_descriptor}'
                            if menu_type == 'popup'
                            else 'Set As Default Domain'))
                assert selection_dir_prefix is not None
                if selection_dir_prefix != selection_domain_prefix:
                    if self._project.default_url_prefix == selection_dir_prefix:
                        menuitems.append(wx.MenuItem(
                            None, self._ID_CLEAR_PREFIX, 'Clear Default Directory'))
                    else:
                        prefix_descriptor = self._try_remove_http_scheme(selection_dir_prefix)
                        menuitems.append(wx.MenuItem(
                            None,
                            self._ID_SET_DIRECTORY_PREFIX,
                            f'Set As Default Directory: {prefix_descriptor}'
                                if menu_type == 'popup'
                                else 'Set As Default Directory'))
        else:
            append_disabled_menuitem()
        assert len(menuitems) > 0
        return (menuitems, on_attach_menuitems)
    
    @capture_crashes_to_self
    def _on_popup_menuitem_selected(self, event: wx.MenuEvent) -> None:
        self.on_change_url_prefix_menuitem_selected(event, self._right_clicked_node)
    
    @capture_crashes_to_self
    def on_change_url_prefix_menuitem_selected(self, event: wx.MenuEvent, node: Node | None) -> None:
        assert node is not None
        
        item_id = event.Id
        if item_id == self._ID_SET_DOMAIN_PREFIX:
            assert isinstance(node, (_ResourceNode, ResourceGroupNode))
            self.set_default_url_prefix('domain', self._url_or_url_prefix_for(node))
        elif item_id == self._ID_SET_DIRECTORY_PREFIX:
            assert isinstance(node, (_ResourceNode, ResourceGroupNode))
            self.set_default_url_prefix('directory', self._url_or_url_prefix_for(node))
        elif item_id == self._ID_CLEAR_PREFIX:
            self.clear_default_url_prefix()
        else:
            # Some other menuitem
            event.Skip()
    
    def set_default_url_prefix(self,
            prefix_type: Literal['domain', 'directory'],
            url_or_url_prefix: str
            ) -> None:
        if prefix_type == 'domain':
            new_default_url_prefix = (
                get_url_domain_prefix_for(url_or_url_prefix))
        elif prefix_type == 'directory':
            new_default_url_prefix = (
                get_url_directory_prefix_for(url_or_url_prefix))
        else:
            raise ValueError()
        if new_default_url_prefix is not None:
            self._project.default_url_prefix = new_default_url_prefix
            self._did_change_default_url_prefix()
    
    def clear_default_url_prefix(self) -> None:
        self._project.default_url_prefix = None
        self._did_change_default_url_prefix()
    
    def _did_change_default_url_prefix(self) -> None:
        self.root.update_descendants()  # update "Offsite" ClusterNodes
        self.root.update_title_of_descendants()  # update URLs in titles
    
    @staticmethod
    def _url_or_url_prefix_for(node: _ResourceNode | ResourceGroupNode) -> str:
        if isinstance(node, _ResourceNode):
            return node.resource.url
        elif isinstance(node, ResourceGroupNode):
            return ResourceGroup.literal_prefix_for_url_pattern(
                node.resource_group.url_pattern)
        else:
            raise ValueError()
    
    @staticmethod
    def _try_remove_http_scheme(url_or_url_prefix: str) -> str:
        if url_or_url_prefix.lower().startswith('https://'):
            return url_or_url_prefix[len('https://'):]
        if url_or_url_prefix.lower().startswith('http://'):
            return url_or_url_prefix[len('http://'):]
        return url_or_url_prefix
    
    # === Event: Mouse Motion, Get Tooltip ===
    
    # Update the tooltip whenever hovering the mouse over a tree node icon
    @capture_crashes_to_self
    def _on_mouse_motion(self, event: wx.MouseEvent) -> None:
        (tree_item_id, hit_flags) = self.peer.HitTest(event.Position)
        if (hit_flags & wx.TREE_HITTEST_ONITEMICON) != 0:
            new_tooltip = self._tooltip_for_tree_item_id(tree_item_id, 'icon')
        elif (hit_flags & wx.TREE_HITTEST_ONITEMLABEL) != 0:
            new_tooltip = self._tooltip_for_tree_item_id(tree_item_id, 'label')
        else:
            new_tooltip = None
        
        if new_tooltip is None:
            self.peer.UnsetToolTip()
        else:
            self.peer.SetToolTip(new_tooltip)
    
    @capture_crashes_to_self
    def _on_get_tooltip_event(self, event: GetTooltipEvent) -> None:  # type: ignore[reportInvalidTypeForm]
        event.tooltip_cell[0] = self._tooltip_for_tree_item_id(event.tree_item_id, event.tooltip_type)
    
    def _tooltip_for_tree_item_id(self, tree_item_id: wx.TreeItemId, tooltip_type: Literal['icon', 'label']) -> str | None:
        node_view = self.peer.GetItemData(tree_item_id)  # type: NodeView
        node = Node.for_node_view(node_view)
        if tooltip_type == 'icon':
            return node.icon_tooltip
        elif tooltip_type == 'label':
            return node.label_tooltip
        else:
            raise ValueError()
    
    # === Dispose ===
    
    def dispose(self) -> None:
        self._project.listeners.remove(self)
        self.root.dispose()
        self.view.dispose()


def _sequence_with_matching_elements_replaced(new_seq, old_seq):
    """
    Returns copy of `new_seq`, replacing each element with an equivalent member of
    `old_seq` whenever possible.
    
    Behavior is undefined if `new_seq` or `old_seq` contains duplicate elements.
    """
    old_seq_selfdict = {x: x for x in old_seq}
    return [old_seq_selfdict.get(x, x) for x in new_seq]


NodeEntity = Union['RootResource', 'Resource', 'ResourceGroup']


class Node(Bulkhead):
    def __init__(self, *, source: DeferrableResourceGroupSource) -> None:
        self._source = source
        self._children = []  # type: List[Node]
        self._crash_reason = None  # type: Optional[CrashReason]
    
    @staticmethod
    def for_node_view(node_view: NodeView) -> Node:
        node = node_view.delegate
        assert isinstance(node, Node)
        return node
    
    # === Properties ===
    
    def _get_view(self) -> NodeView:
        return self._view
    def _set_view(self, value: NodeView) -> None:
        self._view = value
        self._view.delegate = self
    view = property(_get_view, _set_view)
    
    def _get_children(self) -> list[Node]:
        return self._children
    def _set_children(self, value: list[Node]) -> None:
        self.set_children(value)
    children = property(_get_children, _set_children)
    
    def set_children(self,
            value: list[Node],
            progress_listener: OpenProjectProgressListener | None=None) -> None:
        """
        Raises:
        * CancelOpenProject
        """
        # NOTE: Very important. Needed to reuse most nodes when changing
        #       children list to a similar children list.
        value = _sequence_with_matching_elements_replaced(value, self._children)
        self._children = value
        self.view.set_children([child.view for child in value], progress_listener)
    
    @property
    def icon_tooltip(self) -> str | None:
        """
        The tooltip to display when the mouse hovers over this node's icon.
        """
        return None
    
    @property
    def label_tooltip(self) -> str | None:
        """
        The tooltip to display when the mouse hovers over this node's label.
        """
        return None
    
    @property
    def entity(self) -> NodeEntity | None:
        """
        The entity represented by this node, or None if not applicable.
        """
        return None
    
    @property
    def source(self) -> ResourceGroupSource:
        if callable(self._source):
            return self._source()
        else:
            return self._source
    
    # === Bulkhead ===
    
    def _get_crash_reason(self) -> CrashReason | None:
        return self._crash_reason
    def _set_crash_reason(self, reason: CrashReason | None) -> None:
        """
        Called when a crash occurs while expanding this node,
        to display the crash information in the UI as a single child error node.
        """
        assert reason is not None, 'Clearing the crash reason is not supported'
        self._crash_reason = reason
        # TODO: Actually expose the reason itself in a tooltip
        # TODO: Consider allowing the crash to be dismissed, similar to how CrashedTask does
        self._set_error_child(_ErrorNode.CRASH_TITLE, is_crash=True)
    crash_reason = cast(CrashReason, property(_get_crash_reason, _set_crash_reason))
    
    # protected
    def _set_error_child(self, message: str, *, is_crash: bool=False) -> None:
        """
        Sets the children of this node to a single error node.
        
        Can be called from any thread.
        """
        @capture_crashes_to_stderr
        def fg_task() -> None:
            self.children = [_ErrorNode(message, is_crash=is_crash)]
        fg_call_later(fg_task)
    
    # === Updates ===
    
    def update_descendants(self) -> None:
        """
        Updates this node's descendants, usually due to a project change.
        """
        self._call_on_descendants('update_children')
    
    def update_title_of_descendants(self) -> None:
        """
        Updates the title of this node's descendants, usually due to a project change.
        """
        self._call_on_descendants('update_title')
    
    def update_icon_set_of_descendants(self) -> None:
        """
        Updates the icon set of this node's descendants, usually due to a project change.
        """
        self.update_icon_set_of_descendants_with_resource(None)
    
    def update_icon_set_of_descendants_with_resource(self, resource: Resource | None) -> None:
        """
        Updates the icon set of this node's descendants, usually due to a project change.
        
        Only update if the entity's resource matches the specified resource
        or update all resources if `resource` is None.
        """
        if isinstance(self.entity, (RootResource, Resource)):
            if resource is None or self.entity.resource == resource:
                self.update_icon_set()
        for child in self.children:
            child.update_icon_set_of_descendants_with_resource(resource)
    
    def update_icon_set_of_descendants_in_group(self, group: ResourceGroup) -> None:
        """
        Updates the icon set of this node's descendants, usually due to a project change.
        
        Only update if the entity's resource is in the specified group.
        """
        if isinstance(self.entity, (RootResource, Resource)):
            if self.entity.resource in group:
                self.update_icon_set()
        elif isinstance(self.entity, ResourceGroup):
            if self.entity == group:
                self.update_icon_set()
        for child in self.children:
            child.update_icon_set_of_descendants_in_group(group)
    
    def _call_on_descendants(self, method_name) -> None:
        getattr(self, method_name)()
        for child in self.children:
            child._call_on_descendants(method_name)
    
    def update_children(self) -> None:
        """
        Updates this node's immediate children, usually due to a project change.
        
        Subclasses may override this method to recompute their children nodes.
        The default implementation takes no action.
        """
    
    @final
    def update_title(self) -> None:
        """
        Updates this node's title. Usually due to a project change.
        """
        maybe_title = self.calculate_title()
        if not isinstance(maybe_title, NotImplementedType):
            self.view.title = maybe_title
    
    def calculate_title(self) -> str | NotImplementedType:
        return NotImplemented
    
    @final
    def update_icon_set(self) -> None:
        """
        Updates this node's icon set. Usually due to a project change.
        """
        maybe_icon_set = self.calculate_icon_set()
        if not isinstance(maybe_icon_set, NotImplementedType):
            self.view.icon_set = maybe_icon_set
    
    def calculate_icon_set(self) -> IconSet | None | NotImplementedType:
        return NotImplemented
    
    # === Dispose ===
    
    def dispose(self) -> None:
        if hasattr(self, '_view'):
            self._view.dispose()
            self._view = NULL_NODE_VIEW
        for c in self._children:
            c.dispose()
        self._children = []
    
    # === Utility ===
    
    def __repr__(self):
        return '<{} titled {} at {}>'.format(type(self).__name__, repr(self.view.title), hex(id(self)))


class RootNode(Node):
    def __init__(self, project: Project, view: NodeView, progress_listener: OpenProjectProgressListener) -> None:
        """
        Raises:
        * CancelOpenProject
        """
        super().__init__(source=None)
        
        self.view = view
        self.view.title = 'ROOT'
        self.view.expandable = True
        
        self._project = project
        
        self.update_children(progress_listener)
    
    # === Updates ===
    
    @override
    def update_children(self, 
            progress_listener: OpenProjectProgressListener | None=None) -> None:
        """
        Raises:
        * CancelOpenProject
        """
        if progress_listener is None:
            progress_listener = DummyOpenProjectProgressListener()
        
        children = []  # type: List[Node]
        
        progress_listener.loading_root_resource_views()
        for (index, rr) in enumerate(self._project.root_resources):
            children.append(RootResourceNode(rr, source=None))
        
        progress_listener.loading_resource_group_views()
        for (index, rg) in enumerate(self._project.resource_groups):
            children.append(ResourceGroupNode(rg))
        
        self.set_children(children, progress_listener)


class _LoadingNode(Node):
    def __init__(self) -> None:
        super().__init__(source=None)
        
        self.view = NodeView()
        self.view.icon_set = (
            (wx.TreeItemIcon_Normal, TREE_NODE_ICONS()['entitytree_loading']),
        )
        self.view.title = 'Loading...'
    
    # === Updates ===
    
    @override
    def update_children(self):
        pass


class _ErrorNode(Node):
    CRASH_TEXT_COLOR = wx.Colour(255, 0, 0)  # red
    CRASH_TITLE = 'Something went wrong'
    
    def __init__(self, title: str, *, is_crash: bool=False) -> None:
        super().__init__(source=None)
        
        self.view = NodeView()
        self.view.icon_set = (
            (wx.TreeItemIcon_Normal, TREE_NODE_ICONS()['entitytree_warning']),
        )
        self.view.title = title
        if is_crash:
            self.view.text_color = _ErrorNode.CRASH_TEXT_COLOR
            self.view.bold = True
    
    # === Updates ===
    
    @override
    def update_children(self):
        pass


class _ResourceNode(Node):
    """Base class for `Node`s whose children is derived from the links in a `Resource`."""
    
    def __init__(self,
            title: str,
            resource: Resource,
            tree_node_icon_name: str='entitytree_resource',
            *, source: DeferrableResourceGroupSource,
            source_of_links: ResourceGroupSource,
            ) -> None:
        super().__init__(source=source)
        
        self._tree_node_icon_name = tree_node_icon_name
        self._source_of_links = source_of_links
        
        self._status_badge_name_calculated = False
        self._status_badge_name_value = None  # type: Optional[str]
        
        self.view = NodeView()
        # NOTE: Defer expensive calculation until if/when the icon_set is used
        self.view.icon_set = self.calculate_icon_set
        self.view.title = title
        self.view.expandable = True
        # Workaround for: https://github.com/wxWidgets/wxWidgets/issues/13886
        self.children = [_LoadingNode()]
        
        self.resource = resource
        self.download_future = None  # type: Optional[Future[ResourceRevision]]
        self.resource_links = None  # type: Optional[List[Link]]
    
    # === Properties ===
    
    @override
    def calculate_icon_set(self) -> IconSet | None:
        return (
            (wx.TreeItemIcon_Normal, BADGED_TREE_NODE_ICON(
                self._tree_node_icon_name,
                # NOTE: Expensive to calculate _status_badge_name
                self._status_badge_name(force_recalculate=True))),
        )
    
    def _status_badge_name(self, *, force_recalculate: bool=False) -> str | None:
        if not self._status_badge_name_calculated or force_recalculate:
            self._status_badge_name_value = self._calculate_status_badge_name()
            self._status_badge_name_calculated = True
        return self._status_badge_name_value
    
    def _calculate_status_badge_name(self) -> str | None:
        is_dnd_url = False
        url = self.resource.url  # cache
        for rg in self.resource.project.resource_groups:
            if rg.contains_url(url):
                if rg.do_not_download:
                    is_dnd_url = True
                else:
                    is_dnd_url = False
                    break
        
        if is_dnd_url:
            return 'prohibition'
        
        freshest_rr = self.resource.default_revision(stale_ok=True)
        if freshest_rr is None:
            # Not downloaded
            return 'new'
        else:
            if freshest_rr.is_stale:
                # Stale
                return 'stale'
            else:
                # Fresh
                if freshest_rr.error is None:
                    # OK
                    return None
                else:
                    # Error
                    return 'warning'
    
    @override
    @property
    def icon_tooltip(self) -> str | None:
        return '{} {}'.format(self._status_badge_tooltip, self._entity_tooltip)
    
    @property
    def _status_badge_tooltip(self) -> str:
        status_badge_name = self._status_badge_name()  # cache
        if status_badge_name is None:
            return 'Fresh'
        elif status_badge_name == 'new':
            return 'Undownloaded'
        elif status_badge_name == 'stale':
            return 'Stale'
        elif status_badge_name == 'warning':
            return 'Error downloading'
        elif status_badge_name == 'prohibition':
            return 'Ignored'
        else:
            raise AssertionError('Unknown resource status badge: ' + status_badge_name)
    
    @property
    def _entity_tooltip(self) -> str:  # abstract
        raise NotImplementedError()
    
    @override
    @property
    def label_tooltip(self) -> str:
        return f'URL: {self.resource.url}'
    
    @override
    @property
    def entity(self) -> NodeEntity:
        return self.resource
    
    @property
    def _project(self) -> Project:
        return self.resource.project
    
    # === Comparison ===
    
    def __eq__(self, other):
        return isinstance(other, _ResourceNode) and (
            self.view.title == other.view.title and self.resource == other.resource)
    def __hash__(self):
        return hash(self.view.title) ^ hash(self.resource)
    
    # === Events ===
    
    @capture_crashes_to_self
    def on_expanded(self, event: wx.TreeEvent) -> None:
        # If this is the first expansion attempt, start an asynchronous task to fetch
        # the resource and subsequently update the children
        if self.download_future is None:
            self.download_future = self.resource.download()
            
            def download_done(future: Future[ResourceRevision]) -> None:
                try:
                    revision = future.result()
                except CannotDownloadWhenProjectReadOnlyError:
                    self._set_error_child('Cannot download: Project is read only')
                except ProjectFreeSpaceTooLowError:
                    self._set_error_child('Cannot download: Disk is full')
                except ProjectHasTooManyRevisionsError:
                    self._set_error_child('Cannot download: Project has too many revisions')
                except Exception:
                    self._set_error_child('Cannot download: Unexpected error')
                else:
                    revision = revision.resolve_http_304()  # reinterpret
                    
                    error_dict = revision.error_dict
                    if error_dict is not None:
                        self._set_error_child(
                            f'Error downloading URL: {error_dict["type"]}: {error_dict["message"]}')
                        return
                    
                    @capture_crashes_to(self)
                    def bg_task() -> None:
                        # Link parsing is I/O intensive, so do it on a background thread
                        try:
                            self.resource_links = revision.links()
                        # TODO: Instead of catching RevisionDeletedError,
                        #       fix Resource.download() and DownloadResourceTask.future
                        #       to never return a ResourceRevision that has been deleted,
                        #       even when it internally deletes and redownloads a revision
                        #       whose body is missing
                        except (RevisionBodyMissingError, RevisionDeletedError):
                            self._set_error_child(
                                'Cannot list links: URL revision body is missing. Recommend delete and redownload.')
                        except Exception:
                            self._set_error_child(
                                'Cannot list links: Unexpected error')
                        else:
                            fg_call_later(self.update_children)
                    bg_call_later(bg_task)
            self.download_future.add_done_callback(download_done)
    
    # === Updates ===
    
    @capture_crashes_to_self
    @override
    def update_children(self) -> None:
        """
        Updates this node's children.
        Should be called whenever project entities change or the underlying resource's links change.
        """
        if self.download_future is None:
            # We were never expanded, so no need to recalculate anything.
            return
        
        if len(self.children) >= 1 and isinstance(self.children[0], _ErrorNode):
            # Leave error state unchanged
            return
        
        # Partition links and create resources
        resources_2_links = defaultordereddict(list)  # type: Dict[Resource, List[Link]]
        if self.resource_links:
            for link in self.resource_links:
                url = urljoin(self.resource.url, link.relative_url)
                resource = Resource(self._project, url)
                resources_2_links[resource].append(link)
        
        linked_root_resources = []
        group_2_root_and_normal_resources = defaultordereddict(
            lambda: (list(), list())
        )  # type: Dict[ResourceGroup, Tuple[List[Tuple[RootResource, List[Link]]], List[Tuple[Resource, List[Link]]]]]
        linked_other_resources = []
        lowpri_offsite_resources = []
        # TODO: Recognize cluster: (Hidden: Banned by robots.txt)
        # TODO: Recognize cluster: (Hidden: Self reference)
        hidden_embedded_resources = []
        # TODO: Recognize cluster: (Hidden: Ignored Protocols: *)
        
        default_url_prefix = self._project.default_url_prefix
        for (r, links_to_r) in resources_2_links.items():
            rr = self._project.get_root_resource(r)
            
            if rr is not None:
                linked_root_resources.append((rr, links_to_r))
                for rg in self._project.resource_groups:
                    if r in rg:
                        group_2_root_and_normal_resources[rg][0].append((rr, links_to_r))
            else:
                in_any_group = False
                for rg in self._project.resource_groups:
                    if r in rg:
                        in_any_group = True
                        group_2_root_and_normal_resources[rg][1].append((r, links_to_r))
                
                if not in_any_group:
                    is_embedded = False
                    for link in links_to_r:
                        if link.embedded:
                            is_embedded = True
                            break
                    
                    if is_embedded:
                        hidden_embedded_resources.append((r, links_to_r))
                    elif default_url_prefix and not r.url.startswith(default_url_prefix):
                        lowpri_offsite_resources.append((r, links_to_r))
                    else:
                        linked_other_resources.append((r, links_to_r))
        
        # Create children and update UI
        children = []  # type: List[Node]
        
        for (rr, links_to_r) in linked_root_resources:
            children.append(RootResourceNode(rr,
                source=self._source_of_links))
        
        for (group, (rr_2_links, r_2_links)) in group_2_root_and_normal_resources.items():
            root_rsrc_nodes = []
            for (rr, links_to_r) in rr_2_links:
                root_rsrc_nodes.append(RootResourceNode(rr,
                    source=self._source_of_links))
            linked_rsrc_nodes = []
            for (r, links_to_r) in r_2_links:
                linked_rsrc_nodes.append(LinkedResourceNode(r, links_to_r,
                    source=self._source_of_links))
            children.append(GroupedLinkedResourcesNode(
                group, root_rsrc_nodes, linked_rsrc_nodes,
                source=self._source_of_links))
        
        for (r, links_to_r) in linked_other_resources:
            children.append(LinkedResourceNode(r, links_to_r,
                source=self._source_of_links))
        
        if lowpri_offsite_resources:
            subchildren = []
            for (r, links_to_r) in lowpri_offsite_resources:
                subchildren.append(LinkedResourceNode(r, links_to_r,
                    source=self._source_of_links))
            children.append(ClusterNode('(Low-priority: Offsite)', subchildren, (
                (wx.TreeItemIcon_Normal, TREE_NODE_ICONS()['entitytree_cluster_offsite']),
            ), 'Offsite URLs', source=self._source_of_links))
        
        if hidden_embedded_resources:
            subchildren = []
            for (r, links_to_r) in hidden_embedded_resources:
                subchildren.append(LinkedResourceNode(r, links_to_r,
                    source=self._source_of_links))
            children.append(ClusterNode('(Hidden: Embedded)', subchildren, (
                (wx.TreeItemIcon_Normal, TREE_NODE_ICONS()['entitytree_cluster_embedded']),
            ), 'Embedded URLs', source=self._source_of_links))
        
        self.children = children
    
    # NOTE: If crash while trying to determine which new node to select,
    #       fallback to just clearing the selection
    @capture_crashes_to_stderr
    def on_selection_deleted(self,
            old_selected_node_view: NodeView,
            ) -> NodeView | None:
        old_selected_node = Node.for_node_view(old_selected_node_view)
        if isinstance(old_selected_node, _ResourceNode):
            # Probably this node still exists but in a different location.
            # Try to find that location.
            for child in self.children:
                if old_selected_node == child:
                    return child.view
                for grandchild in child.children:
                    if old_selected_node == grandchild:
                        return grandchild.view
            
            # Maybe this node changed type, either:
            #     1. {LinkedResourceNode, NormalResourceNode} -> RootResourceNode
            #     2. RootResourceNode -> {LinkedResourceNode, NormalResourceNode}
            # Try to find a node with the same URL even if different type.
            for child in self.children:
                if isinstance(child, _ResourceNode):
                    if old_selected_node.resource == child.resource:
                        return child.view
                for grandchild in child.children:
                    if isinstance(grandchild, _ResourceNode):
                        if old_selected_node.resource == grandchild.resource:
                            return grandchild.view
            
            return None
        elif isinstance(old_selected_node, GroupedLinkedResourcesNode):
            # Probably the first child still exists but in a different location.
            # Try to find that location.
            children = old_selected_node.children
            if len(children) == 0:
                return None
            return self.on_selection_deleted(children[0].view)
        else:
            return None


class RootResourceNode(_ResourceNode):
    ICON = '⚓️'
    ICON_TRUNCATION_FIX = ''
    
    def __init__(self,
            root_resource: RootResource,
            *, source: DeferrableResourceGroupSource,
            ) -> None:
        self.root_resource = root_resource
        super().__init__(
            self.calculate_title(),
            root_resource.resource,
            'entitytree_root_resource',
            source=source,
            source_of_links=root_resource)
    
    # === Properties ===
    
    @property
    def _entity_tooltip(self) -> str:
        return 'root URL'
    
    @override
    def calculate_title(self) -> str:
        return self.calculate_title_of(self.root_resource)
    
    @staticmethod
    def calculate_title_of(root_resource: RootResource) -> str:
        project = root_resource.project
        display_url = project.get_display_url(root_resource.url)
        if root_resource.name != '':
            return '{} - {}'.format(display_url, root_resource.name)
        else:
            return '{}'.format(display_url)
    
    @override
    @property
    def label_tooltip(self) -> str:
        if self.root_resource.name != '':
            return (
                f'URL: {self.resource.url}\n'
                f'Name: {self.root_resource.name}'
            )
        else:
            return (
                f'URL: {self.resource.url}'
            )
    
    @override
    @property
    def entity(self) -> RootResource:
        return self.root_resource
    
    # === Comparison ===
    
    def __eq__(self, other):
        return (
            isinstance(other, RootResourceNode) and
            self.root_resource == other.root_resource
        )
    def __hash__(self):
        return hash(self.root_resource)


class NormalResourceNode(_ResourceNode):
    def __init__(self,
            resource: Resource,
            *, source: DeferrableResourceGroupSource,
            source_of_links: ResourceGroupSource,
            ) -> None:
        self.resource = resource
        super().__init__(
            self.calculate_title(),
            resource,
            source=source,
            source_of_links=source_of_links)
    
    # === Properties ===
    
    @property
    def _entity_tooltip(self) -> str:
        return 'URL'
    
    @override
    def calculate_title(self) -> str:
        project = self.resource.project
        return '%s' % project.get_display_url(self.resource.url)
    
    @override
    @property
    def entity(self) -> Resource:
        return self.resource
    
    # === Comparison ===
    
    def __eq__(self, other):
        return isinstance(other, NormalResourceNode) and (
            self.resource == other.resource)
    def __hash__(self):
        return hash(self.resource)


class LinkedResourceNode(_ResourceNode):
    def __init__(self,
            resource: Resource,
            links: list[Link],
            *, source: ResourceGroupSource,
            ) -> None:
        self.resource = resource
        self.links = tuple(links)
        super().__init__(
            self.calculate_title(),
            resource,
            source=source,
            source_of_links=None)
    
    # === Properties ===
    
    @property
    def _entity_tooltip(self) -> str:
        return 'URL'
    
    @override
    def calculate_title(self) -> str:
        project = self.resource.project
        link_titles = ', '.join([self._full_title_of_link(link) for link in self.links])
        return '{} - {}'.format(
            project.get_display_url(self.resource.url),
            link_titles)
    
    @staticmethod
    def _full_title_of_link(link: Link) -> str:
        if link.title:
            return '{}: {}'.format(link.type_title, link.title)
        else:
            return '%s' % link.type_title
    
    @override
    @property
    def entity(self) -> Resource:
        return self.resource
    
    # === Comparison ===
    
    def __eq__(self, other):
        return isinstance(other, LinkedResourceNode) and (
            self.resource == other.resource and self.links == other.links)
    def __hash__(self):
        return hash(self.resource) ^ hash(self.links)


class ClusterNode(Node):
    def __init__(self,
            title: str,
            children,
            icon_set: IconSet,
            tooltip: str,
            *, source: ResourceGroupSource,
            ) -> None:
        super().__init__(source=source)
        
        self._tooltip = tooltip
        
        self.view = NodeView()
        self.view.icon_set = icon_set
        self.view.title = title
        self.view.expandable = True
        
        self.children = children
        self._children_tuple = tuple(self.children)
    
    # === Properties ===
    
    @override
    @property
    def icon_tooltip(self) -> str:
        return self._tooltip
    
    @override
    @property
    def label_tooltip(self) -> str:
        return self._tooltip
    
    # === Comparison ===
    
    def __eq__(self, other):
        return isinstance(other, ClusterNode) and (
            self.children == other.children)
    def __hash__(self):
        return hash(self._children_tuple)


class _GroupedNode(Node):  # abstract
    entity_tooltip: str  # abstract
    
    ICON = '📁'
    ICON_TRUNCATION_FIX = ' '
    
    def __init__(self,
            resource_group: ResourceGroup,
            *, source: DeferrableResourceGroupSource,
            ) -> None:
        self.resource_group = resource_group
        super().__init__(source=source)
    
    # === Properties ===
    
    @override
    def calculate_icon_set(self) -> IconSet | None:
        return (
            (wx.TreeItemIcon_Normal, BADGED_ART_PROVIDER_TREE_NODE_ICON(
                wx.ART_FOLDER,
                self._status_badge_name()
            )),
            (wx.TreeItemIcon_Expanded, BADGED_ART_PROVIDER_TREE_NODE_ICON(
                wx.ART_FOLDER_OPEN,
                self._status_badge_name()
            )),
        )
    
    def _status_badge_name(self) -> str | None:
        if self.resource_group.do_not_download:
            return 'prohibition'
        else:
            return None
    
    @override
    @property
    def icon_tooltip(self) -> str | None:
        status_badge_name = self._status_badge_name()
        if status_badge_name is None:
            return f'{self.entity_tooltip.capitalize()}'
        elif status_badge_name == 'prohibition':
            return f'Ignored {self.entity_tooltip}'
        else:
            raise AssertionError()
        
    @override
    @property
    def label_tooltip(self) -> str:
        if self.resource_group.name != '':
            return (
                f'URL Pattern: {self.resource_group.url_pattern}\n'
                f'Name: {self.resource_group.name}'
            )
        else:
            return (
                f'URL Pattern: {self.resource_group.url_pattern}'
            )


class ResourceGroupNode(_GroupedNode):
    entity_tooltip = 'group'
    
    _MAX_VISIBLE_CHILDREN = 100
    _MORE_CHILDREN_TO_SHOW = 20
    
    def __init__(self, resource_group: ResourceGroup) -> None:
        super().__init__(resource_group, source=lambda: resource_group.source)
        self._max_visible_children = self._MAX_VISIBLE_CHILDREN
        
        self.view = NodeView()
        # NOTE: Defer expensive calculation until if/when the icon_set is used
        self.view.icon_set = self.calculate_icon_set
        self.view.title = self.calculate_title()
        self.view.expandable = True
        
        # Workaround for: https://github.com/wxWidgets/wxWidgets/issues/13886
        self.children = [_LoadingNode()]
        assert not self._children_loaded
    
    # === Properties ===
    
    @override
    def calculate_title(self) -> str:
        return self.calculate_title_of(self.resource_group)
    
    @staticmethod
    def calculate_title_of(resource_group: ResourceGroup) -> str:
        project = resource_group.project
        display_url = project.get_display_url(resource_group.url_pattern)
        if resource_group.name != '':
            return '{} - {}'.format(display_url, resource_group.name)
        else:
            return '{}'.format(display_url)
    
    @override
    @property
    def entity(self) -> ResourceGroup:
        return self.resource_group
    
    # === Update ===
    
    @property
    def _children_loaded(self) -> bool:
        if len(self.children) >= 1 and isinstance(self.children[0], _LoadingNode):
            return False
        else:
            return True
    
    @capture_crashes_to_self
    @override
    def update_children(self, force_populate: bool=False) -> None:
        if not force_populate:
            if not self._children_loaded:
                return
        
        # NOTE: May trigger a load of the members, which could be slow
        members = self.resource_group.members  # cache
        
        children = self.children  # cache
        if len(children) > self._max_visible_children:
            more_placeholder_node = children[-1]
            assert isinstance(more_placeholder_node, MorePlaceholderNode)
            more_placeholder_node.more_count = len(members) - self._max_visible_children
            return
        
        children_rrs = []  # type: List[Node]
        children_rs = []  # type: List[Node]
        project = self.resource_group.project  # cache
        for r in members[:min(self._max_visible_children, len(members))]:
            rr = project.get_root_resource(r)
            if rr is None:
                children_rs.append(NormalResourceNode(r,
                    source=lambda: self.resource_group.source,
                    source_of_links=self.resource_group))
            else:
                children_rrs.append(RootResourceNode(rr,
                    source=lambda: self.resource_group.source))
        if len(members) > self._max_visible_children:
            children_extra = [
                MorePlaceholderNode(len(members) - self._max_visible_children, self,
                    source=lambda: self.resource_group.source),
            ]  # type: List[Node]
        else:
            children_extra = []
        self.children = children_rrs + children_rs + children_extra
    
    # === Events ===
    
    @capture_crashes_to_self
    def on_expanded(self, event: wx.TreeEvent) -> None:
        # If this is the first expansion attempt, populate the children
        if not self._children_loaded:
            @capture_crashes_to(self)
            def fg_task_later() -> None:
                # Show progress dialog in advance if will need to load all project URLs
                try:
                    self.resource_group.project.load_urls()
                except CancelLoadUrls:
                    # Collapse the tree item that was just expanded
                    self.view.peer.Collapse()
                    
                    # Cancel update children
                    return
                
                self.update_children(force_populate=True)
            @capture_crashes_to(self)
            def bg_task():
                # Give time for the loading node to display
                time.sleep(.1)
                
                # NOTE: Use profile=False because it is known that the database
                #       query for loading group members is known to be slow.
                #       
                #       In the future it would be ideal to move database operations
                #       off of the foreground thread.
                fg_call_later(fg_task_later, profile=False)
            bg_call_later(bg_task)
    
    # NOTE: If the more-node crashes while expanding, replace the entire list
    #       of sibling children with a single error node. A bit of an extreme
    #       response, but is probably the safest thing to do.
    @capture_crashes_to_self
    def on_more_expanded(self, more_node: MorePlaceholderNode) -> None:
        # Save selected node
        old_children_len = len(self.children)  # capture
        more_node_was_selected = more_node.view.peer.IsSelected()  # capture
        if more_node_was_selected:
            more_node.view.peer.SelectItem(False)
        
        self._max_visible_children += self._MORE_CHILDREN_TO_SHOW
        # NOTE: Does NOT raise here if update_children() crashes internally
        self.update_children()
        
        # Restore selected node
        if more_node_was_selected and len(self.children) >= 1:
            node_in_position_of_old_more_node = self.children[old_children_len - 1]
            node_in_position_of_old_more_node.view.peer.SelectItem()
    
    # === Comparison ===
    
    def __eq__(self, other) -> bool:
        return (
            isinstance(other, ResourceGroupNode) and
            self.resource_group == other.resource_group
        )
    def __hash__(self) -> int:
        return hash(self.resource_group)


class GroupedLinkedResourcesNode(_GroupedNode):
    entity_tooltip = 'grouped URLs'
    
    def __init__(self,
            resource_group: ResourceGroup,
            root_rsrc_nodes: list[RootResourceNode],
            linked_rsrc_nodes: list[LinkedResourceNode],
            source: ResourceGroupSource,
            ) -> None:
        super().__init__(resource_group, source=source)
        
        self.view = NodeView()
        # NOTE: Defer expensive calculation until if/when the icon_set is used
        self.view.icon_set = self.calculate_icon_set
        #self.view.title = ... (set below)
        self.view.expandable = True
        
        self.children = root_rsrc_nodes + linked_rsrc_nodes
        self._children_tuple = tuple(self.children)
        
        self.view.title = self.calculate_title()  # after self.children is initialized
    
    # === Properties ===
    
    @override
    def calculate_title(self) -> str:
        project = self.resource_group.project
        display_url_pattern = project.get_display_url(self.resource_group.url_pattern)
        if self.resource_group.name != '':
            return '%s - %d of %s' % (
                display_url_pattern,
                len(self.children),
                self.resource_group.name)
        else:
            return '%s - %d link%s' % (
                display_url_pattern,
                len(self.children),
                '' if len(self.children) == 1 else 's')
    
    @override
    @property
    def entity(self) -> NodeEntity | None:
        # This node groups together various _ResourceNode entities that
        # are in the same ResourceGroup
        return self.resource_group
    
    # === Comparison ===
    
    def __eq__(self, other):
        return isinstance(other, GroupedLinkedResourcesNode) and (
            self.children == other.children)
    def __hash__(self):
        return hash(self._children_tuple)


class MorePlaceholderNode(Node):
    def __init__(self,
            more_count: int,
            delegate: object | None=None,
            *, source: DeferrableResourceGroupSource
            ) -> None:
        super().__init__(source=source)
        self._more_count = -1
        self._delegate = delegate
        
        self.view = NodeView()
        #self.view.title = ... (set below)
        self.view.icon_set = (
            (wx.TreeItemIcon_Normal, TREE_NODE_ICONS()['entitytree_more']),
        )
        self.view.expandable = True
        
        self.more_count = more_count  # sets self.view.title too
        
        # Workaround for: https://github.com/wxWidgets/wxWidgets/issues/13886
        self.children = [_LoadingNode()]
    
    def _get_more_count(self) -> int:
        return self._more_count
    def _set_more_count(self, more_count: int) -> None:
        if more_count == self._more_count:
            return
        self._more_count = more_count
        self.view.title = f'{more_count:n} more'
    more_count = property(_get_more_count, _set_more_count)
    
    # === Events ===
    
    @capture_crashes_to_self
    def on_expanded(self, event: wx.TreeEvent) -> None:
        if hasattr(self._delegate, 'on_more_expanded'):
            run_bulkhead_call(self._delegate.on_more_expanded, self)  # type: ignore[attr-defined]
    
    # === Comparison ===
    
    def __eq__(self, other) -> bool:
        return (
            isinstance(other, MorePlaceholderNode) and 
            self._more_count == other._more_count
        )
    def __hash__(self) -> int:
        return self._more_count
