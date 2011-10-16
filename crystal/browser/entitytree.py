from crystal.model import Resource
from crystal.ui import ui_call_later
from crystal.ui.tree import *
from crystal.xcollections import defaultordereddict
import threading
import urlparse

class EntityTree(object):
    """
    Displays a tree of top-level project entities.
    """
    def __init__(self, project, parent_peer):
        self.view = TreeView(parent_peer)
        self.root = RootNode(project, self.view.root)
        
        # TODO: Remove auto-testing code
        self.view.expand(self.root.view.children[0].view)

class Node(object):
    pass

class RootNode(Node):
    def __init__(self, project, view):
        self.view = view
        
        children = []
        for rr in project.root_resources:
            children.append(RootResourceNode(rr))
        for rg in project.resource_groups:
            children.append(ResourceGroupNode(rg))
        
        self.view.title = 'ROOT'
        self.view.expandable = True
        self.view.children = children

class _ResourceNode(Node):
    """Base class for `Node`s whose children is derived from the `Link`s in a `Resource`."""
    
    def __init__(self, title, resource):
        self.view = NodeView()
        self.view.title = title
        self.view.expandable = True
        self.view.delegate = self
        
        self.resource = resource
        self.download_task = None
        self.links = None
    
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
                self.links = revision.links()
                self._update_children()
            threading.Thread(target=bg_task).start()
    
    def _update_children(self):
        """
        Updates this node's children.
        Should be called whenever project entities change or the underlying resource's links change.
        
        May be called from any thread.
        """
        
        def db_task():
            # Partition links and create resources
            resources_2_links = defaultordereddict(list)
            for link in self.links:
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
                rr = self._project.find_root_resource(r)
                
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
            
            def ui_task():
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
                
                self.view.children = children
            ui_call_later(ui_task)
        self._project.db_call_later(db_task)

class RootResourceNode(_ResourceNode):
    def __init__(self, root_resource):
        project = root_resource.project
        title = '%s - %s' % (project.get_display_url(root_resource.url), root_resource.name)
        super(RootResourceNode, self).__init__(title, root_resource.resource)

class NormalResourceNode(_ResourceNode):
    def __init__(self, resource):
        project = resource.project
        title = '%s' % project.get_display_url(resource.url)
        super(NormalResourceNode, self).__init__(title, resource)

class LinkedResourceNode(_ResourceNode):
    def __init__(self, resource, links):
        project = resource.project
        link_titles = ', '.join([link.full_title for link in links])
        title = '%s - %s' % (project.get_display_url(resource.url), link_titles)
        super(LinkedResourceNode, self).__init__(title, resource)

class ClusterNode(Node):
    def __init__(self, title, children, icon_set=None):
        self.view = NodeView()
        self.view.icon_set = icon_set
        self.view.title = title
        self.view.expandable = True
        self.view.children = children
        self.view.delegate = self

class ResourceGroupNode(Node):
    def __init__(self, resource_group):
        project = resource_group.project
        
        children_rrs = []
        children_rs = []
        for r in project.resources:
            if r in resource_group:
                rr = project.find_root_resource(r)
                if rr is None:
                    children_rs.append(NormalResourceNode(r))
                else:
                    children_rrs.append(RootResourceNode(rr))
        children = children_rrs + children_rs
        
        self.view = NodeView()
        self.view.title = '%s - %s' % (resource_group.url_pattern, resource_group.name)
        self.view.expandable = True
        self.view.children = children
        self.view.delegate = self

class GroupedLinkedResourcesNode(Node):
    def __init__(self, resource_group, root_rsrc_nodes, linked_rsrc_nodes):
        self.view = NodeView()
        self.view.title = '%s - %s' % (resource_group.url_pattern, resource_group.name)
        self.view.expandable = True
        self.view.children = root_rsrc_nodes + linked_rsrc_nodes
        self.view.delegate = self

# ------------------------------------------------------------------------------

# Informal unit test
def _test(project):
    from crystal.ui import APP as app
    frame = wx.Frame(None, title='Frame', size=(500,300))
    et = EntityTree(project, frame)
    frame.Show(True)
    #app.MainLoop()
    return app
