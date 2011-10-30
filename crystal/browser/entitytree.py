from crystal.model import Resource
from crystal.ui.tree import *
from crystal.xcollections import defaultordereddict
from crystal.xthreading import bg_call_later, fg_call_later
import threading
import urlparse

class EntityTree(object):
    """
    Displays a tree of top-level project entities.
    """
    def __init__(self, parent_peer, project):
        self.view = TreeView(parent_peer)
        self.root = RootNode(project, self.view.root)
        
        self.peer.SetInitialSize((550, 300))
        
        # TODO: Remove auto-testing code
        #self.view.expand(self.root.view.children[0].view)
    
    @property
    def peer(self):
        return self.view.peer
    
    def update(self):
        """
        Updates the nodes in this tree, usually due to a project change.
        """
        self.root.update_descendants()

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
    
    def _get_children(self):
        return self._children
    def _set_children(self, value):
        value = _sequence_with_matching_elements_replaced(value, self._children)
        self._children = value
        self.view.children = [child.view for child in value]
    children = property(_get_children, _set_children)
    
    def update_descendants(self):
        """
        Updates this node's descendants, usually due to a project change.
        """
        self.update_children()
        for child in self.children:
            child.update_descendants()
    
    def update_children(self):
        """
        Updates this node's immediate children, usually due to a project change.
        
        Subclasses may override this method to recompute their children nodes.
        The default implementation takes no action.
        """
        pass
    
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

class _ResourceNode(Node):
    """Base class for `Node`s whose children is derived from the `Link`s in a `Resource`."""
    
    def __init__(self, title, resource):
        super(_ResourceNode, self).__init__()
        self.view = NodeView()
        self.view.title = title
        self.view.expandable = True
        self.view.delegate = self
        
        self.resource = resource
        self.download_task = None
        self.resource_links = None
    
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
        if self.download_task is None:
            self.download_task = self.resource.download_self()
            
            def bg_task():
                revision = self.download_task()
                self.resource_links = revision.links()
                fg_call_later(self.update_children)
            bg_call_later(bg_task)
    
    def update_children(self):
        """
        Updates this node's children.
        Should be called whenever project entities change or the underlying resource's links change.
        """
        # Partition links and create resources
        resources_2_links = defaultordereddict(list)
        if self.resource_links:
            for link in self.resource_links:
                url = urlparse.urljoin(self.resource.url, link.relative_url)
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
        for (r, links_to_r) in resources_2_links.iteritems():
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
        
        for (group, (rr_2_links, r_2_links)) in group_2_root_and_normal_resources.iteritems():
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
        project = root_resource.project
        title = '%s - %s' % (project.get_display_url(root_resource.url), root_resource.name)
        super(RootResourceNode, self).__init__(title, root_resource.resource)
        
        self.root_resource = root_resource
    
    def __eq__(self, other):
        return isinstance(other, RootResourceNode) and (
            self.root_resource == other.root_resource)
    def __hash__(self):
        return hash(self.root_resource)

class NormalResourceNode(_ResourceNode):
    def __init__(self, resource):
        project = resource.project
        title = '%s' % project.get_display_url(resource.url)
        super(NormalResourceNode, self).__init__(title, resource)
        
        self.resource = resource
    
    def __eq__(self, other):
        return isinstance(other, NormalResourceNode) and (
            self.resource == other.resource)
    def __hash__(self):
        return hash(self.resource)

class LinkedResourceNode(_ResourceNode):
    def __init__(self, resource, links):
        project = resource.project
        link_titles = ', '.join([link.full_title for link in links])
        title = '%s - %s' % (project.get_display_url(resource.url), link_titles)
        super(LinkedResourceNode, self).__init__(title, resource)
        
        self.resource = resource
        self.links = tuple(links)
    
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
        self.view.delegate = self
        
        self.children = children
        self._children_tuple = tuple(self.children)
    
    def __eq__(self, other):
        return isinstance(other, ClusterNode) and (
            self.children == other.children)
    def __hash__(self):
        return hash(self._children_tuple)

class ResourceGroupNode(Node):
    def __init__(self, resource_group):
        super(ResourceGroupNode, self).__init__()
        project = resource_group.project
        self.view = NodeView()
        self.view.title = '%s - %s' % (project.get_display_url(resource_group.url_pattern), resource_group.name)
        self.view.expandable = True
        self.view.delegate = self
        
        children_rrs = []
        children_rs = []
        project = resource_group.project
        for r in project.resources:
            if r in resource_group:
                rr = project.get_root_resource(r)
                if rr is None:
                    children_rs.append(NormalResourceNode(r))
                else:
                    children_rrs.append(RootResourceNode(rr))
        children = children_rrs + children_rs
        self.children = children
        
        self.resource_group = resource_group
    
    def __eq__(self, other):
        return isinstance(other, ResourceGroupNode) and (
            self.resource_group == other.resource_group)
    def __hash__(self):
        return hash(self.resource_group)

class GroupedLinkedResourcesNode(Node):
    def __init__(self, resource_group, root_rsrc_nodes, linked_rsrc_nodes):
        super(GroupedLinkedResourcesNode, self).__init__()
        project = resource_group.project
        self.view = NodeView()
        self.view.title = '%s - %s' % (project.get_display_url(resource_group.url_pattern), resource_group.name)
        self.view.expandable = True
        self.view.delegate = self
        
        self.children = root_rsrc_nodes + linked_rsrc_nodes
        self._children_tuple = tuple(self.children)
    
    def __eq__(self, other):
        return isinstance(other, GroupedLinkedResourcesNode) and (
            self.children == other.children)
    def __hash__(self):
        return hash(self._children_tuple)

# ------------------------------------------------------------------------------

# Informal unit test
def _test(project):
    app = wx.PySimpleApp()
    frame = wx.Frame(None, title='Frame', size=(500,300))
    et = EntityTree(frame, project)
    frame.Show(True)
    #app.MainLoop()
    return app
