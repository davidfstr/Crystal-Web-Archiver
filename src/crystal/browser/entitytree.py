from __future__ import annotations

from crystal.browser.icons import BADGED_TREE_NODE_ICON, TREE_NODE_ICONS
from crystal.model import Project, Resource, ResourceGroup, ResourceRevision, RootResource
from crystal.progress import (
    DummyOpenProjectProgressListener,
    OpenProjectProgressListener,
)
from crystal.task import CannotDownloadWhenProjectReadOnlyError
# TODO: Expand this star import
from crystal.ui.tree import *
from crystal.util.wx_bind import bind
from crystal.util.xcollections import defaultordereddict
from crystal.util.xthreading import bg_call_later, fg_call_later
import os
import threading
from typing import cast, List, Optional, Union
from urllib.parse import urljoin, urlparse, urlunparse
import wx
import wx.lib.newevent


_ID_SET_PREFIX = 101
_ID_CLEAR_PREFIX = 102


# Similar to wx's EVT_TREE_ITEM_GETTOOLTIP event,
# but cross-platform and focused on the icon specifically
GetTooltipEvent, EVT_TREE_ITEM_ICON_GETTOOLTIP = wx.lib.newevent.NewEvent()


class EntityTree:
    """
    Displays a tree of top-level project entities.
    """
    def __init__(self,
            parent_peer: wx.Window,
            project: Project,
            progress_listener: OpenProjectProgressListener) -> None:
        """
        Raises:
        * CancelOpenProject
        """
        self.view = TreeView(parent_peer, name='cr-entity-tree')
        self.view.delegate = self
        self.root = RootNode(project, self.view.root, progress_listener)
        self._project = project
        self._group_nodes_need_updating = False
        self._right_clicked_node = None
        
        project.listeners.append(self)
        
        self.peer.SetInitialSize((550, 300))
        
        bind(self.peer, wx.EVT_MOTION, self._on_mouse_motion)
        # For tests only
        bind(self.peer, EVT_TREE_ITEM_ICON_GETTOOLTIP, self._on_get_tooltip_event)
        # For tests only
        bind(self.peer, wx.EVT_MENU, self._on_popup_menuitem_selected)
    
    # === Properties ===
    
    @property
    def peer(self) -> wx.TreeCtrl:
        """The wx.TreeCtrl controlled by this class."""
        return self.view.peer
    
    @property
    def selected_entity(self) -> Optional[NodeEntity]:
        selected_node_view = self.view.selected_node
        if selected_node_view is None:
            return None
        selected_node = selected_node_view.delegate
        assert isinstance(selected_node, Node)
        
        return selected_node.entity
    
    # HACK: Violates the Law of Demeter rather substantially.
    @property
    def parent_of_selected_entity(self):
        selected_wxtreeitemid = self.view.peer.GetSelection()
        if not selected_wxtreeitemid.IsOk():
            return None
        
        parent_wxtreeitemid = self.view.peer.GetItemParent(selected_wxtreeitemid)
        if not parent_wxtreeitemid.IsOk():
            return None
        
        parent_node_view = self.view.peer.GetItemData(parent_wxtreeitemid)
        parent_node = parent_node_view.delegate
        
        return parent_node.entity
    
    # === Updates ===
    
    def update(self):
        """
        Updates the nodes in this tree, usually due to a project change.
        """
        self.root.update_descendants()
    
    # === Event: Resource Did Instantiate ===
    
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
            fg_call_later(self._refresh_group_nodes_now, force=True)
    
    def _refresh_group_nodes_now(self) -> None:
        try:
            for rgn in self.root.children:
                if type(rgn) is ResourceGroupNode:
                    rgn.update_children()
        finally:
            self._group_nodes_need_updating = False
    
    # === Event: Resource Revision Did Instantiate ===
    
    def resource_revision_did_instantiate(self, revision: ResourceRevision) -> None:
        fg_call_later(lambda:
            self.root.update_icon_set_of_descendants_with_resource(revision.resource))
    
    # === Event: Root Resource Did Instantiate ===
    
    def root_resource_did_instantiate(self, root_resource: RootResource) -> None:
        self.update()
    
    # === Event: Resource Group Did Instantiate ===
    
    def resource_group_did_instantiate(self, group: ResourceGroup) -> None:
        self.update()
    
    # === Event: Min Fetch Date Did Change ===
    
    def min_fetch_date_did_change(self) -> None:
        fg_call_later(lambda:
            self.root.update_icon_set_of_descendants_with_resource(None))
    
    # === Event: Right Click ===
    
    def on_right_click(self, event, node_view):
        node = node_view.delegate
        self._right_clicked_node = node
        
        # Create popup menu
        menu = wx.Menu()
        bind(menu, wx.EVT_MENU, self._on_popup_menuitem_selected)
        if isinstance(node, _ResourceNode):
            if self._project.default_url_prefix == (
                    EntityTree._get_url_prefix_for_resource(node.resource)):
                menu.Append(_ID_CLEAR_PREFIX, 'Clear Default URL Prefix')
            else:
                menu.Append(_ID_SET_PREFIX, 'Set As Default URL Prefix')
        
        # Show popup menu
        if menu.GetMenuItemCount() > 0:
            if os.environ.get('CRYSTAL_RUNNING_TESTS', 'False') == 'False':
                self.peer.PopupMenu(menu, event.GetPoint())
            else:
                print('(Suppressing popup menu while CRYSTAL_RUNNING_TESTS=True)')
        menu.Destroy()
    
    def _on_popup_menuitem_selected(self, event):
        node = self._right_clicked_node
        
        item_id = event.GetId()
        if item_id == _ID_SET_PREFIX:
            self._project.default_url_prefix = (
                EntityTree._get_url_prefix_for_resource(node.resource))
            self._did_change_default_url_prefix()
        elif item_id == _ID_CLEAR_PREFIX:
            self._project.default_url_prefix = None
            self._did_change_default_url_prefix()
    
    def _did_change_default_url_prefix(self) -> None:
        self.root.update_descendants()  # update "Offsite" ClusterNodes
        self.root.update_title_of_descendants()  # update URLs in titles
    
    @staticmethod
    def _get_url_prefix_for_resource(resource):
        """
        Given a resource, returns the URL prefix that will chop off everything
        before the resource's enclosing directory.
        """
        url = resource.url
        url_components = urlparse(url)
        
        # If URL path contains slash, chop last slash and everything following it
        path = url_components.path
        if '/' in path:
            new_path = path[:path.rindex('/')]
        else:
            new_path = path
        
        new_url_components = list(url_components)
        new_url_components[2] = new_path
        return urlunparse(new_url_components)
    
    # === Event: Mouse Motion, Get Tooltip ===
    
    # Update the tooltip whenever hovering the mouse over a tree node icon
    def _on_mouse_motion(self, event: wx.MouseEvent) -> None:
        (tree_item_id, hit_flags) = self.peer.HitTest(event.Position)
        if (hit_flags & wx.TREE_HITTEST_ONITEMICON) != 0:
            new_tooltip = self._icon_tooltip_for_tree_item_id(tree_item_id)
        else:
            new_tooltip = None
        
        self.peer.SetToolTip(new_tooltip)
    
    def _on_get_tooltip_event(self, event: wx.Event) -> None:
        event.tooltip_cell[0] = self._icon_tooltip_for_tree_item_id(event.tree_item_id)
    
    def _icon_tooltip_for_tree_item_id(self, tree_item_id) -> Optional[str]:
        node_view = self.peer.GetItemData(tree_item_id)  # type: NodeView
        node = cast(Node, node_view.delegate)
        return node.icon_tooltip
    
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
    old_seq_selfdict = dict([(x, x) for x in old_seq])
    return [old_seq_selfdict.get(x, x) for x in new_seq]


NodeEntity = Union['RootResource', 'Resource', 'ResourceGroup']


class Node:
    def __init__(self):
        self._children = []  # type: List[Node]
    
    # === Properties ===
    
    def _get_view(self) -> NodeView:
        return self._view
    def _set_view(self, value: NodeView) -> None:
        self._view = value
        self._view.delegate = self
    view = property(_get_view, _set_view)
    
    def _get_children(self) -> List[Node]:
        return self._children
    def _set_children(self, value: List[Node]) -> None:
        self.set_children(value)
    children = property(_get_children, _set_children)
    
    def set_children(self,
            value: List[Node],
            progress_listener: Optional[OpenProjectProgressListener]=None) -> None:
        """
        Raises:
        * CancelOpenProject
        """
        value = _sequence_with_matching_elements_replaced(value, self._children)
        self._children = value
        self.view.set_children([child.view for child in value], progress_listener)
    
    @property
    def icon_tooltip(self) -> Optional[str]:
        """
        The tooltip to display when the mouse hovers over this node's icon.
        """
        return None
    
    @property
    def entity(self) -> Optional[NodeEntity]:
        """
        The entity represented by this node, or None if not applicable.
        """
        return None
    
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
    
    def update_icon_set_of_descendants_with_resource(self, resource: Optional[Resource]) -> None:
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
        pass
    
    def update_title(self) -> None:
        """
        Updates this node's title. Usually due to a project change.
        """
        if hasattr(self, 'calculate_title'):
            self.view.title = self.calculate_title()  # type: ignore[attr-defined]
    
    def update_icon_set(self) -> None:
        """
        Updates this node's icon set. Usually due to a project change.
        """
        if hasattr(self, 'calculate_icon_set'):
            self.view.icon_set = self.calculate_icon_set()  # type: ignore[attr-defined]
    
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
        return '<%s titled %s at %s>' % (type(self).__name__, repr(self.view.title), hex(id(self)))


class RootNode(Node):
    def __init__(self, project: Project, view: NodeView, progress_listener: OpenProjectProgressListener) -> None:
        """
        Raises:
        * CancelOpenProject
        """
        super().__init__()
        
        self.view = view
        self.view.title = 'ROOT'
        self.view.expandable = True
        
        self._project = project
        
        self.update_children(progress_listener)
    
    # === Updates ===
    
    def update_children(self, 
            progress_listener: Optional[OpenProjectProgressListener]=None) -> None:
        """
        Raises:
        * CancelOpenProject
        """
        if progress_listener is None:
            progress_listener = DummyOpenProjectProgressListener()
        
        children = []  # type: List[Node]
        
        progress_listener.loading_root_resource_views()
        for (index, rr) in enumerate(self._project.root_resources):
            progress_listener.loading_root_resource_view(index)
            children.append(RootResourceNode(rr))
        
        progress_listener.loading_resource_group_views()
        for (index, rg) in enumerate(self._project.resource_groups):
            progress_listener.loading_resource_group_view(index)
            children.append(ResourceGroupNode(rg))
        
        self.set_children(children, progress_listener)


class _LoadingNode(Node):
    def __init__(self):
        super().__init__()
        
        self.view = NodeView()
        self.view.icon_set = (
            (wx.TreeItemIcon_Normal, TREE_NODE_ICONS()['entitytree_loading']),
        )
        self.view.title = 'Loading...'
    
    # === Updates ===
    
    def update_children(self):
        pass


class _ChildrenUnavailableBecauseReadOnlyNode(Node):
    def __init__(self):
        super().__init__()
        
        self.view = NodeView()
        self.view.icon_set = (
            (wx.TreeItemIcon_Normal, TREE_NODE_ICONS()['entitytree_warning']),
        )
        self.view.title = 'Cannot download children: Project is read only'
    
    # === Updates ===
    
    def update_children(self):
        pass


class _ResourceNode(Node):
    """Base class for `Node`s whose children is derived from the links in a `Resource`."""
    
    def __init__(self,
            title: str,
            resource: Resource,
            tree_node_icon_name: str='entitytree_resource') -> None:
        super().__init__()
        
        self._tree_node_icon_name = tree_node_icon_name
        
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
        self.download_future = None
        self.resource_links = None
    
    # === Properties ===
    
    def calculate_icon_set(self) -> Optional[IconSet]:
        return (
            (wx.TreeItemIcon_Normal, BADGED_TREE_NODE_ICON(
                self._tree_node_icon_name,
                # NOTE: Expensive to calculate _status_badge_name
                self._status_badge_name(force_recalculate=True))),
        )
    
    def _status_badge_name(self, *, force_recalculate: bool=False) -> Optional[str]:
        if not self._status_badge_name_calculated or force_recalculate:
            self._status_badge_name_value = self._calculate_status_badge_name()
            self._status_badge_name_calculated = True
        return self._status_badge_name_value
    
    def _calculate_status_badge_name(self) -> Optional[str]:
        resource = self.resource  # cache
        
        # NOTE: Inefficient. Performs 2 database queries (via 2 calls to
        #       default_revision) when only 1 could be used
        any_rr = resource.default_revision(stale_ok=True)
        if any_rr is None:
            # Not downloaded
            return 'new'
        else:
            non_stale_rr = resource.default_revision(stale_ok=False)
            if non_stale_rr is None:
                # Stale
                return 'stale'
            else:
                # Fresh
                if non_stale_rr.error is None:
                    # OK
                    return None
                else:
                    # Error
                    return 'warning'
    
    @property
    def icon_tooltip(self) -> Optional[str]:
        return '%s %s' % (self._status_badge_tooltip, self._entity_tooltip)
    
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
            return 'Error'
        else:
            raise AssertionError('Unknown resource status badge: ' + status_badge_name)
    
    @property
    def _entity_tooltip(self) -> str:  # abstract
        raise NotImplementedError()
    
    @property
    def entity(self):
        return self.resource
    
    @property
    def _project(self):
        return self.resource.project
    
    # === Comparison ===
    
    def __eq__(self, other):
        return isinstance(other, _ResourceNode) and (
            self.view.title == other.view.title and self.resource == other.resource)
    def __hash__(self):
        return hash(self.view.title) ^ hash(self.resource)
    
    # === Events ===
    
    def on_expanded(self, event):
        # If this is the first expansion attempt, start an asynchronous task to fetch
        # the resource and subsequently update the children
        if self.download_future is None:
            self.download_future = self.resource.download()
            
            def download_done(future):
                # TODO: Gracefully handle ProjectFreeSpaceTooLowError here
                try:
                    revision = future.result()
                except CannotDownloadWhenProjectReadOnlyError:
                    def fg_task():
                        self.children = [_ChildrenUnavailableBecauseReadOnlyNode()]
                    fg_call_later(fg_task)
                else:
                    revision = revision.resolve_http_304()  # reinterpret
                    
                    def bg_task():
                        # Link parsing is I/O intensive, so do it on a background thread
                        self.resource_links = revision.links()
                        fg_call_later(self.update_children)
                    bg_call_later(bg_task)
            self.download_future.add_done_callback(download_done)
    
    # === Updates ===
    
    def update_children(self):
        """
        Updates this node's children.
        Should be called whenever project entities change or the underlying resource's links change.
        """
        if self.download_future is None:
            # We were never expanded, so no need to recalculate anything.
            return
        
        # Partition links and create resources
        resources_2_links = defaultordereddict(list)
        if self.resource_links:
            for link in self.resource_links:
                url = urljoin(self.resource.url, link.relative_url)
                resource = Resource(self._project, url)
                resources_2_links[resource].append(link)
        
        linked_root_resources = []
        group_2_root_and_normal_resources = defaultordereddict(lambda: (list(), list()))
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
        children = []
        
        for (rr, links_to_r) in linked_root_resources:
            children.append(RootResourceNode(rr))
        
        for (group, (rr_2_links, r_2_links)) in group_2_root_and_normal_resources.items():
            root_rsrc_nodes = []
            for (rr, links_to_r) in rr_2_links:
                root_rsrc_nodes.append(RootResourceNode(rr))
            linked_rsrc_nodes = []
            for (r, links_to_r) in r_2_links:
                linked_rsrc_nodes.append(LinkedResourceNode(r, links_to_r))
            children.append(GroupedLinkedResourcesNode(group, root_rsrc_nodes, linked_rsrc_nodes))
        
        for (r, links_to_r) in linked_other_resources:
            children.append(LinkedResourceNode(r, links_to_r))
        
        if lowpri_offsite_resources:
            subchildren = []
            for (r, links_to_r) in lowpri_offsite_resources:
                subchildren.append(LinkedResourceNode(r, links_to_r))
            children.append(ClusterNode('(Low-priority: Offsite)', subchildren, (
                (wx.TreeItemIcon_Normal, TREE_NODE_ICONS()['entitytree_cluster_offsite']),
            ), 'Offsite URLs'))
        
        if hidden_embedded_resources:
            subchildren = []
            for (r, links_to_r) in hidden_embedded_resources:
                subchildren.append(LinkedResourceNode(r, links_to_r))
            children.append(ClusterNode('(Hidden: Embedded)', subchildren, (
                (wx.TreeItemIcon_Normal, TREE_NODE_ICONS()['entitytree_cluster_embedded']),
            ), 'Embedded URLs'))
        
        self.children = children


class RootResourceNode(_ResourceNode):
    def __init__(self, root_resource: RootResource) -> None:
        self.root_resource = root_resource
        super().__init__(
            self.calculate_title(),
            root_resource.resource,
            'entitytree_root_resource')
    
    # === Properties ===
    
    @property
    def _entity_tooltip(self) -> str:
        return 'root URL'
    
    def calculate_title(self):
        project = self.root_resource.project
        return '%s - %s' % (
            project.get_display_url(self.root_resource.url),
            self.root_resource.name)
    
    @property
    def entity(self):
        return self.root_resource
    
    # === Comparison ===
    
    def __eq__(self, other):
        return isinstance(other, RootResourceNode) and (
            self.root_resource == other.root_resource)
    def __hash__(self):
        return hash(self.root_resource)


class NormalResourceNode(_ResourceNode):
    def __init__(self, resource):
        self.resource = resource
        super().__init__(self.calculate_title(), resource)
    
    # === Properties ===
    
    @property
    def _entity_tooltip(self) -> str:
        return 'URL'
    
    def calculate_title(self):
        project = self.resource.project
        return '%s' % project.get_display_url(self.resource.url)
    
    @property
    def entity(self):
        return self.resource
    
    # === Comparison ===
    
    def __eq__(self, other):
        return isinstance(other, NormalResourceNode) and (
            self.resource == other.resource)
    def __hash__(self):
        return hash(self.resource)


class LinkedResourceNode(_ResourceNode):
    def __init__(self, resource, links):
        self.resource = resource
        self.links = tuple(links)
        super().__init__(self.calculate_title(), resource)
    
    # === Properties ===
    
    @property
    def _entity_tooltip(self) -> str:
        return 'URL'
    
    def calculate_title(self):
        project = self.resource.project
        link_titles = ', '.join([self._full_title_of_link(link) for link in self.links])
        return '%s - %s' % (
            project.get_display_url(self.resource.url),
            link_titles)
    
    def _full_title_of_link(self, link):
        if link.title:
            return '%s: %s' % (link.type_title, link.title)
        else:
            return '%s' % link.type_title
    
    @property
    def entity(self):
        return self.resource
    
    # === Comparison ===
    
    def __eq__(self, other):
        return isinstance(other, LinkedResourceNode) and (
            self.resource == other.resource and self.links == other.links)
    def __hash__(self):
        return hash(self.resource) ^ hash(self.links)


class ClusterNode(Node):
    def __init__(self, title: str, children, icon_set: IconSet, icon_tooltip: str) -> None:
        super().__init__()
        
        self._icon_tooltip = icon_tooltip
        
        self.view = NodeView()
        self.view.icon_set = icon_set
        self.view.title = title
        self.view.expandable = True
        
        self.children = children
        self._children_tuple = tuple(self.children)
    
    # === Properties ===
    
    @property
    def icon_tooltip(self) -> Optional[str]:
        return self._icon_tooltip
    
    # === Comparison ===
    
    def __eq__(self, other):
        return isinstance(other, ClusterNode) and (
            self.children == other.children)
    def __hash__(self):
        return hash(self._children_tuple)


class ResourceGroupNode(Node):
    _MAX_VISIBLE_CHILDREN = 100
    _MORE_CHILDREN_TO_SHOW = 20
    
    def __init__(self, resource_group: ResourceGroup) -> None:
        self.resource_group = resource_group
        super().__init__()
        self._max_visible_children = self._MAX_VISIBLE_CHILDREN
        
        self.view = NodeView()
        self.view.title = self.calculate_title()
        self.view.expandable = True
        
        # Workaround for: https://github.com/wxWidgets/wxWidgets/issues/13886
        self.children = [_LoadingNode()]
        assert not self._children_loaded
    
    # === Properties ===
    
    @property
    def icon_tooltip(self) -> Optional[str]:
        return 'Group'
    
    def calculate_title(self):
        project = self.resource_group.project
        return '%s - %s' % (
            project.get_display_url(self.resource_group.url_pattern),
            self.resource_group.name)
    
    @property
    def entity(self):
        return self.resource_group
    
    # === Update ===
    
    @property
    def _children_loaded(self) -> bool:
        if len(self.children) >= 1 and isinstance(self.children[0], _LoadingNode):
            return False
        else:
            return True
    
    def update_children(self, force_populate: bool=False) -> None:
        if not force_populate:
            if not self._children_loaded:
                return
        
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
        for r in members[:self._max_visible_children]:
            rr = project.get_root_resource(r)
            if rr is None:
                children_rs.append(NormalResourceNode(r))
            else:
                children_rrs.append(RootResourceNode(rr))
        if len(members) > self._max_visible_children:
            children_extra = [
                MorePlaceholderNode(len(members) - self._max_visible_children, self),
            ]  # type: List[Node]
        else:
            children_extra = []
        self.children = children_rrs + children_rs + children_extra
    
    # === Events ===
    
    def on_expanded(self, event) -> None:
        # If this is the first expansion attempt, populate the children
        if not self._children_loaded:
            self.update_children(force_populate=True)
    
    def on_more_expanded(self, more_node: MorePlaceholderNode) -> None:
        # Save selected node
        old_children_len = len(self.children)  # capture
        more_node_was_selected = more_node.view.peer.IsSelected()  # capture
        if more_node_was_selected:
            more_node.view.peer.SelectItem(False)
        
        self._max_visible_children += self._MORE_CHILDREN_TO_SHOW
        self.update_children()
        
        # Restore selected node
        if more_node_was_selected:
            node_in_position_of_old_more_node = self.children[old_children_len - 1]
            node_in_position_of_old_more_node.view.peer.SelectItem()
    
    # === Comparison ===
    
    def __eq__(self, other) -> bool:
        return isinstance(other, ResourceGroupNode) and (
            self.resource_group == other.resource_group)
    def __hash__(self) -> int:
        return hash(self.resource_group)


class GroupedLinkedResourcesNode(Node):
    def __init__(self, resource_group, root_rsrc_nodes, linked_rsrc_nodes):
        self.resource_group = resource_group
        super().__init__()
        
        self.view = NodeView()
        #self.view.title = ... (set below)
        self.view.expandable = True
        
        self.children = root_rsrc_nodes + linked_rsrc_nodes
        self._children_tuple = tuple(self.children)
        
        self.view.title = self.calculate_title()  # after self.children is initialized
    
    # === Properties ===
    
    @property
    def icon_tooltip(self) -> Optional[str]:
        return 'Grouped URLs'
    
    def calculate_title(self):
        project = self.resource_group.project
        return '%s - %d of %s' % (
            project.get_display_url(self.resource_group.url_pattern),
            len(self.children),
            self.resource_group.name)
    
    @property
    def entity(self):
        return self.resource_group
    
    # === Comparison ===
    
    def __eq__(self, other):
        return isinstance(other, GroupedLinkedResourcesNode) and (
            self.children == other.children)
    def __hash__(self):
        return hash(self._children_tuple)


class MorePlaceholderNode(Node):
    def __init__(self, more_count: int, delegate: Optional[object]=None) -> None:
        super().__init__()
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
    
    def on_expanded(self, event):
        if hasattr(self._delegate, 'on_more_expanded'):
            self._delegate.on_more_expanded(self)  # type: ignore[attr-defined]
    
    # === Comparison ===
    
    def __eq__(self, other) -> bool:
        return (
            isinstance(other, MorePlaceholderNode) and 
            self._more_count == other._more_count
        )
    def __hash__(self) -> int:
        return self._more_count
