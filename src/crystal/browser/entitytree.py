from crystal.model import Resource
from crystal.ui.tree import *
from crystal.xcollections import defaultordereddict
from crystal.xthreading import bg_call_later, fg_call_later
import threading
from urllib.parse import urljoin, urlparse, urlunparse

_ID_SET_PREFIX = 101
_ID_CLEAR_PREFIX = 102

class EntityTree(object):
    """
    Displays a tree of top-level project entities.
    """
    def __init__(self, parent_peer, project):
        self.view = TreeView(parent_peer)
        self.view.delegate = self
        self.root = RootNode(project, self.view.root)
        self._project = project
        self._group_nodes_need_updating = False
        self._right_clicked_node = None
        
        project.listeners.append(self)
        
        self.peer.SetInitialSize((550, 300))
    
    @property
    def peer(self):
        """The wx.TreeCtrl controlled by this class."""
        return self.view.peer
    
    @property
    def selected_entity(self):
        selected_node_view = self.view.selected_node
        if selected_node_view is None:
            return None
        selected_node = selected_node_view.delegate
        
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
    
    def update(self):
        """
        Updates the nodes in this tree, usually due to a project change.
        """
        self.root.update_descendants()
    
    def _refresh_group_nodes(self):
        # Coalesce multiple refreshes that happen in succession
        if self._group_nodes_need_updating:
            return
        else:
            self._group_nodes_need_updating = True
            fg_call_later(self._refresh_group_nodes_now, force=True)
    
    def _refresh_group_nodes_now(self):
        try:
            for rgn in self.root.children:
                if type(rgn) is not ResourceGroupNode:
                    continue
                rgn.update_children()
        finally:
            self._group_nodes_need_updating = False
    
    def resource_did_instantiate(self, resource):
        self._refresh_group_nodes()
    
    def on_right_click(self, event, node_view):
        node = node_view.delegate
        self._right_clicked_node = node
        
        # Create popup menu
        menu = wx.Menu()
        menu.Bind(wx.EVT_MENU, self._on_popup_menuitem_selected)
        if self._project.default_url_prefix == (
                EntityTree._get_url_prefix_for_resource(node.resource)):
            menu.Append(_ID_CLEAR_PREFIX, 'Clear Default URL Prefix')
        else:
            menu.Append(_ID_SET_PREFIX, 'Set As Default URL Prefix')
        
        # Show popup menu
        if menu.GetMenuItemCount() > 0:
            self.peer.PopupMenu(menu, event.GetPoint())
        menu.Destroy()
    
    def _on_popup_menuitem_selected(self, event):
        node = self._right_clicked_node
        
        item_id = event.GetId()
        if item_id == _ID_SET_PREFIX:
            self._project.default_url_prefix = (
                EntityTree._get_url_prefix_for_resource(node.resource))
            self._update_titles_of_descendants()
        elif item_id == _ID_CLEAR_PREFIX:
            self._project.default_url_prefix = None
            self._update_titles_of_descendants()
    
    def _update_titles_of_descendants(self):
        self.root.update_title_of_descendants()
    
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

def _sequence_with_matching_elements_replaced(new_seq, old_seq):
    """
    Returns copy of `new_seq`, replacing each element with an equivalent member of
    `old_seq` whenever possible.
    
    Behavior is undefined if `new_seq` or `old_seq` contains duplicate elements.
    """
    old_seq_selfdict = dict([(x, x) for x in old_seq])
    return [old_seq_selfdict.get(x, x) for x in new_seq]

class Node(object):
    def __init__(self):
        self._children = []
    
    def _get_view(self):
        return self._view
    def _set_view(self, value):
        self._view = value
        self._view.delegate = self
    view = property(_get_view, _set_view)
    
    def _get_children(self):
        return self._children
    def _set_children(self, value):
        value = _sequence_with_matching_elements_replaced(value, self._children)
        self._children = value
        self.view.children = [child.view for child in value]
    children = property(_get_children, _set_children)
    
    @property
    def entity(self):
        """
        The entity (ex: RootResource, Resource, ResourceGroup)
        represented by this node, or None if not applicable.
        """
        return None
    
    def update_descendants(self):
        """
        Updates this node's descendants, usually due to a project change.
        """
        self._call_on_descendants('update_children')
    
    def update_title_of_descendants(self):
        """
        Updates the title of this node's descendants, usually due to a project change.
        """
        self._call_on_descendants('update_title')
    
    def _call_on_descendants(self, method_name):
        getattr(self, method_name)()
        for child in self.children:
            child._call_on_descendants(method_name)
    
    def update_children(self):
        """
        Updates this node's immediate children, usually due to a project change.
        
        Subclasses may override this method to recompute their children nodes.
        The default implementation takes no action.
        """
        pass
    
    def update_title(self):
        """
        Updates this node's title. Usually due to a project change.
        """
        if hasattr(self, 'calculate_title'):
            self.view.title = self.calculate_title()
    
    def __repr__(self):
        return '<%s titled %s at %s>' % (type(self).__name__, repr(self.view.title), hex(id(self)))

class RootNode(Node):
    def __init__(self, project, view):
        super(RootNode, self).__init__()
        
        self.view = view
        self.view.title = 'ROOT'
        self.view.expandable = True
        
        self._project = project
        
        self.update_children()
    
    def update_children(self):
        children = []
        for rr in self._project.root_resources:
            children.append(RootResourceNode(rr))
        for rg in self._project.resource_groups:
            children.append(ResourceGroupNode(rg))
        self.children = children

class _LoadingNode(Node):
    def __init__(self):
        super(_LoadingNode, self).__init__()
        
        self.view = NodeView()
        self.view.title = 'Loading...'
    
    def update_children(self):
        pass

class _ResourceNode(Node):
    """Base class for `Node`s whose children is derived from the links in a `Resource`."""
    
    def __init__(self, title, resource):
        super(_ResourceNode, self).__init__()
        
        self.view = NodeView()
        self.view.title = title
        self.view.expandable = True
        # Workaround for: http://trac.wxwidgets.org/ticket/13886
        self.children = [_LoadingNode()]
        
        self.resource = resource
        self.download_future = None
        self.resource_links = None
    
    @property
    def entity(self):
        return self.resource
    
    def __eq__(self, other):
        return isinstance(other, _ResourceNode) and (
            self.view.title == other.view.title and self.resource == other.resource)
    def __hash__(self):
        return hash(self.view.title) ^ hash(self.resource)
    
    @property
    def _project(self):
        return self.resource.project
    
    def on_expanded(self, event):
        # If this is the first expansion attempt, start an asynchronous task to fetch
        # the resource and subsequently update the children
        if self.download_future is None:
            self.download_future = self.resource.download()
            
            def download_done(future):
                revision = future.result()
                def bg_task():
                    # Link parsing is I/O intensive, so do it on a background thread
                    self.resource_links = revision.links()
                    fg_call_later(self.update_children)
                bg_call_later(bg_task)
            self.download_future.add_done_callback(download_done)
    
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
            children.append(ClusterNode('(Low-priority: Offsite)', subchildren))
        
        if hidden_embedded_resources:
            subchildren = []
            for (r, links_to_r) in hidden_embedded_resources:
                subchildren.append(LinkedResourceNode(r, links_to_r))
            children.append(ClusterNode('(Hidden: Embedded)', subchildren))
        
        self.children = children

class RootResourceNode(_ResourceNode):
    def __init__(self, root_resource):
        self.root_resource = root_resource
        super(RootResourceNode, self).__init__(self.calculate_title(), root_resource.resource)
    
    def calculate_title(self):
        project = self.root_resource.project
        return '%s - %s' % (
            project.get_display_url(self.root_resource.url),
            self.root_resource.name)
    
    @property
    def entity(self):
        return self.root_resource
    
    def __eq__(self, other):
        return isinstance(other, RootResourceNode) and (
            self.root_resource == other.root_resource)
    def __hash__(self):
        return hash(self.root_resource)

class NormalResourceNode(_ResourceNode):
    def __init__(self, resource):
        self.resource = resource
        super(NormalResourceNode, self).__init__(self.calculate_title(), resource)
    
    def calculate_title(self):
        project = self.resource.project
        return '%s' % project.get_display_url(self.resource.url)
    
    @property
    def entity(self):
        return self.resource
    
    def __eq__(self, other):
        return isinstance(other, NormalResourceNode) and (
            self.resource == other.resource)
    def __hash__(self):
        return hash(self.resource)

class LinkedResourceNode(_ResourceNode):
    def __init__(self, resource, links):
        self.resource = resource
        self.links = tuple(links)
        super(LinkedResourceNode, self).__init__(self.calculate_title(), resource)
    
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
    
    def __eq__(self, other):
        return isinstance(other, LinkedResourceNode) and (
            self.resource == other.resource and self.links == other.links)
    def __hash__(self):
        return hash(self.resource) ^ hash(self.links)

class ClusterNode(Node):
    def __init__(self, title, children, icon_set=None):
        super(ClusterNode, self).__init__()
        
        self.view = NodeView()
        self.view.icon_set = icon_set
        self.view.title = title
        self.view.expandable = True
        
        self.children = children
        self._children_tuple = tuple(self.children)
    
    def __eq__(self, other):
        return isinstance(other, ClusterNode) and (
            self.children == other.children)
    def __hash__(self):
        return hash(self._children_tuple)

class ResourceGroupNode(Node):
    def __init__(self, resource_group):
        self.resource_group = resource_group
        super(ResourceGroupNode, self).__init__()
        
        self.view = NodeView()
        self.view.title = self.calculate_title()
        self.view.expandable = True
        
        self.update_children()
    
    def calculate_title(self):
        project = self.resource_group.project
        return '%s - %s' % (
            project.get_display_url(self.resource_group.url_pattern),
            self.resource_group.name)
    
    @property
    def entity(self):
        return self.resource_group
    
    def update_children(self):
        children_rrs = []
        children_rs = []
        project = self.resource_group.project
        for r in project.resources:
            if r in self.resource_group:
                rr = project.get_root_resource(r)
                if rr is None:
                    children_rs.append(NormalResourceNode(r))
                else:
                    children_rrs.append(RootResourceNode(rr))
        self.children = children_rrs + children_rs
    
    def __eq__(self, other):
        return isinstance(other, ResourceGroupNode) and (
            self.resource_group == other.resource_group)
    def __hash__(self):
        return hash(self.resource_group)

class GroupedLinkedResourcesNode(Node):
    def __init__(self, resource_group, root_rsrc_nodes, linked_rsrc_nodes):
        self.resource_group = resource_group
        super(GroupedLinkedResourcesNode, self).__init__()
        
        self.view = NodeView()
        self.view.title = self.calculate_title()
        self.view.expandable = True
        
        self.children = root_rsrc_nodes + linked_rsrc_nodes
        self._children_tuple = tuple(self.children)
    
    def calculate_title(self):
        project = self.resource_group.project
        return '%s - %s' % (
            project.get_display_url(self.resource_group.url_pattern),
            self.resource_group.name)
    
    @property
    def entity(self):
        return self.resource_group
    
    def __eq__(self, other):
        return isinstance(other, GroupedLinkedResourcesNode) and (
            self.children == other.children)
    def __hash__(self):
        return hash(self._children_tuple)

# ------------------------------------------------------------------------------

# Informal unit test
def _test(project):
    app = wx.App()
    frame = wx.Frame(None, title='Frame', size=(500,300))
    et = EntityTree(frame, project)
    frame.Show(True)
    #app.MainLoop()
    return app
