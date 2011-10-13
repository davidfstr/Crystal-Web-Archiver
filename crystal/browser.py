# FIXME: Consider renaming this module to 'entitytree'

from collections import OrderedDict
import threading
import wx

class EntityTree(object):
    def __init__(self, project, parent_peer):
        self.view = TreeView(parent_peer)
        self.root = RootNode(project, self.view.root)

# ------------------------------------------------------------------------------
# Nodes

class Node(object):
    pass

class RootNode(Node):
    def __init__(self, project, view):
        self.view = view
        
        children = []
        for rr in project.root_resources:
            children.append(RootResourceNode(rr))
        # TODO: Append children for resource groups
        
        self.view.title = 'ROOT'
        self.view.expandable = True
        self.view.children = children

class _ResourceNode(Node):
    """Base class for `Node`s whose children is derived from the `Link`s in a `Resource`."""
    
    def __init__(self, title, resource):
        self.view = NodeView()
        self.view.title = title
        self.view.expandable = True
        
        self.resource = resource
        self.download_task = None
        self.links = None
    
    @property
    def _project(self):
        return self.resource.project
    
    # FIXME: Get view to call this appropriately
    def node_did_expand(self):
        # If this is the first expansion attempt, start an asynchronous task to fetch
        # the resource and subsequently update the children
        if self.download_task is None:
            self.download_task = self.resource.download_self()
            
            def download_and_update_children():
                revision = self.download_task()
                self.links = revision.links()
                self._update_children()
            threading.Thread(download_and_update_children).start()
    
    def _update_children(self):
        """
        Updates this node's children.
        Should be called whenever project entities change or the underlying resource's links change.
        """
        linked_root_resources = simpleorderedset()
        # TODO: Look for linked resource groups
        #linked_resource_groups = simpleorderedset()
        # TODO: Partition less interesting resources into additional clusters (ex: self-reference, embedded, etc)
        linked_other_resources = defaultordereddict(list)
        
        # Partition links
        for link in self.links:
            resource = Resource(self._project, link.url)
            root_resource = self._project.find_root_resource(resource)
            if root_resource is not None:
                linked_root_resources.add(root_resource)
            else:
                linked_other_resources[resource].append(link)
        
        # Create children
        children = []
        for rr in linked_root_resources:
            children.append(RootResourceNode(rr))
        for (r, links_to_r) in linked_other_resources:
            children.append(LinkedResourceNode(r, links_to_r))
        self.view.children = children

class RootResourceNode(_ResourceNode):
    def __init__(self, root_resource):
        title = '%s - %s' % (root_resource.url, root_resource.name)
        super(RootResourceNode, self).__init__(title, root_resource.resource)

class LinkedResourceNode(_ResourceNode):
    def __init__(self, resource, links):
        title = [link.title for link in links].join(', ')
        super(LinkedResourceNode, self).__init__(title, root_resource.resource)

# ------------------------------------------------------------------------------
# wxPython View Facade

import wx

class TreeView(object):
    def __init__(self, parent_peer):
        self._peer = wx.TreeCtrl(parent_peer, style=wx.TR_DEFAULT_STYLE|wx.TR_HIDE_ROOT)
        
        tree_icon_size = (16,16)
        tree_icon_list = wx.ImageList(tree_icon_size[0], tree_icon_size[1])
        self.folder_closed_icon  = tree_icon_list.Add(wx.ArtProvider_GetBitmap(wx.ART_FOLDER,        wx.ART_OTHER, tree_icon_size))
        self.folder_open_icon    = tree_icon_list.Add(wx.ArtProvider_GetBitmap(wx.ART_FILE_OPEN,     wx.ART_OTHER, tree_icon_size))
        self.file_icon           = tree_icon_list.Add(wx.ArtProvider_GetBitmap(wx.ART_NORMAL_FILE,   wx.ART_OTHER, tree_icon_size))
        self._peer.AssignImageList(tree_icon_list)
        
        self.root = NodeView()
        self.root._attach(_NodeViewPeer(self, self._peer.AddRoot('')))
    
    def _configure_node_icon(self, node_peer):
        node_peer.SetItemImage(self.folder_closed_icon, wx.TreeItemIcon_Normal)
        node_peer.SetItemImage(self.folder_open_icon, wx.TreeItemIcon_Expanded)

class NodeView(object):
    def __init__(self):
        self._peer = None
        self._title = ''
        self._expandable = False
        self._children = []
    
    def gettitle(self):
        return self._title
    def settitle(self, value):
        self._title = value
        if self._peer:
            self._peer.SetItemText(value)
    title = property(gettitle, settitle)
    
    def getexpandable(self):
        return self._expandable
    def setexpandable(self, value):
        self._expandable = value
        if self._peer:
            self._peer.SetItemHasChildren(value)
    expandable = property(getexpandable, setexpandable)
    
    def getchildren(self):
        return self._children
    def setchildren(self, value):
        self._children = value
        if self._peer:
            if self._peer.GetFirstChild()[0].IsOk():
                # TODO: Implement
                raise NotImplementedError('Children list changed after original initialization.')
            for child in value:
                child.view._attach(_NodeViewPeer(self._peer.tree, self._peer.AppendItem('')))
    children = property(getchildren, setchildren)
    
    def _attach(self, peer):
        if self._peer:
            raise ValueError('Already attached to a different peer.')
        self._peer = peer
        
        # Trigger property logic to update peer
        self.title = self.title
        self.expandable = self.expandable
        self.children = self.children
        # TODO: NodeView should be handling its own icon configuration
        self._peer.tree._configure_node_icon(self._peer)

class _NodeViewPeer(tuple):
    def __new__(cls, tree, node_id):
        return tuple.__new__(cls, (tree, node_id))
    
    # TODO: Only the 'tree_peer' should be stored.
    #       Remove use of this property and update constructor.
    @property
    def tree(self):
        return self[0]
    
    @property
    def tree_peer(self):
        return self.tree._peer
    
    @property
    def node_id(self):
        return self[1]
    
    def SetItemText(self, text):
        self.tree_peer.SetItemText(self.node_id, text)
    
    def SetItemHasChildren(self, has):
        self.tree_peer.SetItemHasChildren(self.node_id, has)
    
    def GetFirstChild(self):
        return self.tree_peer.GetFirstChild(self.node_id)
    
    def AppendItem(self, text, *args):
        return self.tree_peer.AppendItem(self.node_id, text, *args)
    
    def SetItemImage(self, image, which):
        self.tree_peer.SetItemImage(self.node_id, image, which)

# ------------------------------------------------------------------------------
# Collection Utilities
# TODO: Extract to own module

class simpleorderedset(object):
    """Ordered set that supports a limited set of operations."""
    
    def __init__(self):
        self.set = set()
        self.items = []
        
    def add(self, value):
        old_size = len(self.set)
        self.set.append(value)
        new_size = len(self.set)
        if new_size > old_size:
            self.items.append(value)
    
    def __contains__(self, value):
        return value in self.set
    
    def __len__(self):
        return len(self.items)
    
    def __iter__(self):
        return self.items.__iter__()

class defaultordereddict(OrderedDict):
    def __init__(default_factory=None):
        self.default_factory = default_factory
    
    def __missing__(self, key):
        if self.default_factory is None:
            raise KeyError(key)
        return self.default_factory()

# ------------------------------------------------------------------------------

# Informal unit test
def _test(project):
    app = wx.App(False)
    frame = wx.Frame(None, title='Frame', size=(500,300))
    et = EntityTree(project, frame)
    frame.Show(True)
    #app.MainLoop()
    return app
