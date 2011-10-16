class EntityTree(object):
    def __init__(self, project, parent_peer):
        self.view = TreeView(parent_peer)
        self.root = RootNode(project, self.view.root)
        
        # TODO: Remove auto-testing code
        self.view.expand(self.root.view.children[0].view)

# ------------------------------------------------------------------------------
# Nodes

from crystal.model import Resource
from crystal.ui import ui_call_later
import threading
import urlparse

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
            
            def download_and_update_children():
                revision = self.download_task()
                self.links = revision.links()
                self._update_children()
            threading.Thread(target=download_and_update_children).start()
    
    def _update_children(self):
        """
        Updates this node's children.
        Should be called whenever project entities change or the underlying resource's links change.
        """
        
        def db_task():
            linked_root_resources = simpleorderedset()
            # TODO: Look for linked resource groups
            #linked_resource_groups = simpleorderedset()
            # TODO: Partition less interesting resources into additional clusters (ex: self-reference, embedded, etc)
            linked_other_resources = defaultordereddict(list)
            
            # Partition links and create resources
            for link in self.links:
                url = urlparse.urljoin(self.resource.url, link.relative_url)
                resource = Resource(self._project, url)
                
                root_resource = self._project.find_root_resource(resource)
                if root_resource is not None:
                    linked_root_resources.add(root_resource)
                else:
                    linked_other_resources[resource].append(link)
            
            def ui_task():
                # Create children and update UI
                children = []
                for rr in linked_root_resources:
                    children.append(RootResourceNode(rr))
                for (r, links_to_r) in linked_other_resources.iteritems():
                    children.append(LinkedResourceNode(r, links_to_r))
                self.view.children = children
            ui_call_later(ui_task)
        self._project.db_call_later(db_task)

class RootResourceNode(_ResourceNode):
    def __init__(self, root_resource):
        project = root_resource.project
        title = '%s - %s' % (project.get_display_url(root_resource.url), root_resource.name)
        super(RootResourceNode, self).__init__(title, root_resource.resource)

class LinkedResourceNode(_ResourceNode):
    def __init__(self, resource, links):
        project = resource.project
        link_titles = ', '.join([link.full_title for link in links])
        title = '%s - %s' % (project.get_display_url(resource.url), link_titles)
        super(LinkedResourceNode, self).__init__(title, resource)

# ------------------------------------------------------------------------------
# wxPython View Facade

import wx

_DEFAULT_TREE_ICON_SIZE = (16,16)

_DEFAULT_FOLDER_ICON_SET_CACHED = None
def _DEFAULT_FOLDER_ICON_SET():
    global _DEFAULT_FOLDER_ICON_SET_CACHED  # necessary to write to a module global
    if not _DEFAULT_FOLDER_ICON_SET_CACHED:
        _DEFAULT_FOLDER_ICON_SET_CACHED = (
            (wx.TreeItemIcon_Normal,   wx.ArtProvider_GetBitmap(wx.ART_FOLDER,      wx.ART_OTHER, _DEFAULT_TREE_ICON_SIZE)),
            (wx.TreeItemIcon_Expanded, wx.ArtProvider_GetBitmap(wx.ART_FILE_OPEN,   wx.ART_OTHER, _DEFAULT_TREE_ICON_SIZE)),
        )
    return _DEFAULT_FOLDER_ICON_SET_CACHED

_DEFAULT_FILE_ICON_SET_CACHED = None
def _DEFAULT_FILE_ICON_SET():
    global _DEFAULT_FILE_ICON_SET_CACHED    # necessary to write to a module global
    if not _DEFAULT_FILE_ICON_SET_CACHED:
        _DEFAULT_FILE_ICON_SET_CACHED = (
            (wx.TreeItemIcon_Normal,   wx.ArtProvider_GetBitmap(wx.ART_NORMAL_FILE, wx.ART_OTHER, _DEFAULT_TREE_ICON_SIZE)),
        )
    return _DEFAULT_FILE_ICON_SET_CACHED

# Maps wx.EVT_TREE_ITEM_* events to names of methods on `NodeView.delegate`
# that will be called (if they exist) upon the reception of such an event.
_EVENT_TYPE_2_DELEGATE_CALLABLE_ATTR = {
    wx.EVT_TREE_ITEM_EXPANDED: 'on_expanded',
    # TODO: Consider adding support for additional wx.EVT_TREE_ITEM_* event types
}
_EVENT_TYPE_ID_2_DELEGATE_CALLABLE_ATTR = dict(zip(
    [et.typeId for et in _EVENT_TYPE_2_DELEGATE_CALLABLE_ATTR],
    _EVENT_TYPE_2_DELEGATE_CALLABLE_ATTR.values()
))

class TreeView(object):
    """
    Displays a tree of nodes.
    
    Acts as a facade for manipulating an underlying wxTreeCtrl.
    For advanced customization, this wxTreeCtrl may be accessed through the `peer` attribute.
    
    Automatically creates a root NodeView (accessible via the `root` attribute),
    which will not be displayed 
    """
    
    def __init__(self, parent_peer):
        self.peer = wx.TreeCtrl(parent_peer, style=wx.TR_DEFAULT_STYLE|wx.TR_HIDE_ROOT)
        
        # Setup node image registration
        self.bitmap_2_image_id = dict()
        tree_icon_size = _DEFAULT_TREE_ICON_SIZE
        self.tree_imagelist = wx.ImageList(tree_icon_size[0], tree_icon_size[1])
        self.peer.AssignImageList(self.tree_imagelist)
        
        # Create root node's view
        self.root = NodeView()
        self.root._attach(NodeViewPeer(self, self.peer.AddRoot('')))
        
        # Listen for events on peer
        for event_type in _EVENT_TYPE_2_DELEGATE_CALLABLE_ATTR:
            self.peer.Bind(event_type, self._dispatch_event, self.peer)
    
    def get_image_id_for_bitmap(self, bitmap):
        """
        Given a wx.Bitmap, returns an image ID suitable to use as an node icon.
        Calling this multiple times with the same wx.Bitmap will return the same image ID.
        """
        if bitmap in self.bitmap_2_image_id:
            image_id = self.bitmap_2_image_id[bitmap]
        else:
            image_id = self.tree_imagelist.Add(bitmap)
            self.bitmap_2_image_id[bitmap] = image_id
        return image_id
    
    def expand(self, node_view):
        self.peer.Expand(node_view.peer.node_id)
    
    # Notified when any interesting event occurs on the peer
    def _dispatch_event(self, event):
        node_id = event.GetItem()
        node_view = self.peer.GetPyData(node_id)
        node_view._dispatch_event(event)

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
    
    def __init__(self):
        self.delegate = None
        self.peer = None
        self._title = ''
        self._expandable = False
        self._icon_set = None
        self._children = []
    
    def gettitle(self):
        return self._title
    def settitle(self, value):
        self._title = value
        if self.peer:
            self.peer.SetItemText(value)
    title = property(gettitle, settitle)
    
    def getexpandable(self):
        return self._expandable
    def setexpandable(self, value):
        self._expandable = value
        if self.peer:
            self.peer.SetItemHasChildren(value)
            # If using default icon set, force it to update since it depends on the expandable state
            if self.icon_set is None:
                self.icon_set = self.icon_set
    expandable = property(getexpandable, setexpandable)
    
    def geticon_set(self):
        """
        A sequence of (wx.TreeItemIcon, wx.Bitmap) tuples, specifying the set of icons applicable
        to this node in various states. If None, then a default icon set is used, depending on
        whether this node is expandable.
        """
        return self._icon_set
    def seticon_set(self, value):
        self._icon_set = value
        if self.peer:
            effective_value = value if value is not None else (
                    _DEFAULT_FOLDER_ICON_SET() if self.expandable else _DEFAULT_FILE_ICON_SET())
            for (which, bitmap) in effective_value:
                self.peer.SetItemImage(self._tree.get_image_id_for_bitmap(bitmap), which)
    icon_set = property(geticon_set, seticon_set)
    
    def getchildren(self):
        return self._children
    def setchildren(self, value):
        self._children = value
        if self.peer:
            if self.peer.GetFirstChild()[0].IsOk():
                # TODO: Implement
                raise NotImplementedError('Children list changed after original initialization.')
            for child in value:
                child.view._attach(NodeViewPeer(self.peer._tree, self.peer.AppendItem('')))
    children = property(getchildren, setchildren)
    
    @property
    def _tree(self):
        if not self.peer:
            raise ValueError('Not attached to a tree.')
        return self.peer._tree
    
    def _attach(self, peer):
        if self.peer:
            raise ValueError('Already attached to a different peer.')
        self.peer = peer
        
        # Enable navigation from peer back to this view
        peer.SetPyData(self)
        
        # Trigger property logic to update peer
        self.title = self.title
        self.expandable = self.expandable
        self.icon_set = self.icon_set
        self.children = self.children
    
    # Called when a wx.EVT_TREE_ITEM_* event occurs on this node
    def _dispatch_event(self, event):
        if not self.delegate:
            return
        event_type_id = event.GetEventType()
        delegate_callable_attr = _EVENT_TYPE_ID_2_DELEGATE_CALLABLE_ATTR.get(event_type_id, None)
        if delegate_callable_attr and hasattr(self.delegate, delegate_callable_attr):
            getattr(self.delegate, delegate_callable_attr)(event)

class NodeViewPeer(tuple):
    def __new__(cls, tree, node_id):
        return tuple.__new__(cls, (tree, node_id))
    
    # TODO: Only the 'tree_peer' should be stored.
    #       Remove use of this property and update constructor.
    @property
    def _tree(self):
        return self[0]
    
    @property
    def tree_peer(self):
        return self._tree.peer
    
    @property
    def node_id(self):
        return self[1]
    
    def SetPyData(self, obj):
        self.tree_peer.SetPyData(self.node_id, obj)
    
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

from collections import OrderedDict

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
    def __init__(self, default_factory=None):
        super(defaultordereddict, self).__init__()
        self.default_factory = default_factory
    
    def __missing__(self, key):
        if self.default_factory is None:
            raise KeyError(key)
        value = self.default_factory()
        self[key] = value
        return value

# ------------------------------------------------------------------------------

# Informal unit test
def _test(project):
    from crystal.ui import APP as app
    frame = wx.Frame(None, title='Frame', size=(500,300))
    et = EntityTree(project, frame)
    frame.Show(True)
    #app.MainLoop()
    return app
