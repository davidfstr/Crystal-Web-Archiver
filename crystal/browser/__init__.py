from crystal.browser.addgroup import AddGroupDialog
from crystal.browser.addrooturl import AddRootUrlDialog
from crystal.browser.entitytree import EntityTree
from crystal.model import Resource, RootResource
import wx

_WINDOW_INNER_PADDING = 10

class MainWindow(object):
    def __init__(self, project):
        self.project = project
        
        self.frame = wx.Frame(None, title='Crystal')
        frame = self.frame
        frame_sizer = wx.BoxSizer(wx.VERTICAL)
        frame.SetSizer(frame_sizer)
        
        frame_sizer.Add(self._create_content(frame), flag=wx.EXPAND|wx.ALL, border=_WINDOW_INNER_PADDING)
        
        frame.Fit()
        frame.Show(True)
    
    def _create_content(self, parent):
        content_sizer = wx.BoxSizer(wx.VERTICAL)
        content_sizer.Add(self._create_entity_tree(parent), proportion=1, flag=wx.EXPAND)
        content_sizer.AddSpacer(_WINDOW_INNER_PADDING)
        content_sizer.Add(self._create_button_bar(parent), flag=wx.EXPAND)
        return content_sizer
    
    def _create_entity_tree(self, parent):
        self.entity_tree = EntityTree(parent, self.project)
        
        return self.entity_tree.peer
    
    def _create_button_bar(self, parent):
        add_url_button = wx.Button(parent, label='+ URL')
        add_url_button.Bind(wx.EVT_BUTTON, self._on_add_url)
        
        add_group_button = wx.Button(parent, label='+ Group')
        add_group_button.Bind(wx.EVT_BUTTON, self._on_add_group)
        
        remove_entity_button = wx.Button(parent, label='-')
        remove_entity_button.Bind(wx.EVT_BUTTON, self._on_remove_entity)
        # TODO: Enable depending on what item in the tree is selected
        remove_entity_button.Disable()
        
        update_membership_button = wx.Button(parent, label='Update Membership')
        update_membership_button.Disable()
        
        download_button = wx.Button(parent, label='Download')
        download_button.Disable()
        
        content_sizer = wx.BoxSizer(wx.HORIZONTAL)
        content_sizer.Add(add_url_button)
        content_sizer.AddSpacer(_WINDOW_INNER_PADDING)
        content_sizer.Add(add_group_button)
        content_sizer.AddSpacer(_WINDOW_INNER_PADDING)
        content_sizer.Add(remove_entity_button)
        content_sizer.AddSpacer(_WINDOW_INNER_PADDING * 2)
        content_sizer.AddStretchSpacer()
        content_sizer.Add(update_membership_button)
        content_sizer.AddSpacer(_WINDOW_INNER_PADDING)
        content_sizer.Add(download_button)
        return content_sizer
    
    def _on_add_url(self, event):
        # TODO: Prepopulate URL field with that of the selected resource (if applicable).
        #       Otherwise prepopulate it with the project's default URL prefix (if applicable).
        #       Otherwise prepopulate it with "http://"
        AddRootUrlDialog(self.frame, self._on_add_url_dialog_ok)
    
    def _on_add_url_dialog_ok(self, name, url):
        # Create the root resource
        # TODO: Handle error where a root resource with the specified name or url already exists
        RootResource(self.project, name, Resource(self.project, url))
    
    def _on_add_group(self, event):
        AddGroupDialog(self.frame)
    
    def _on_remove_entity(self, event):
        pass
