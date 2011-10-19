from crystal.browser.entitytree import EntityTree
import wx

_DIALOG_INNER_PADDING = 10

class MainWindow(object):
    def __init__(self, project):
        self.project = project
        
        frame = wx.Frame(None, title='Crystal')
        
        self._create_padded_panel(frame, _DIALOG_INNER_PADDING, self._create_content)
        
        frame.GetChildren()[0].Fit(); frame.Fit()
        frame.Show(True)
    
    # TODO: Make into utility class
    def _create_padded_panel(self, parent, padding, create_child):
        def create_content_inner(parent):
            content_inner = BoxPanel(parent, wx.VERTICAL)
            content_inner.AddSpacer(padding)
            content_inner.Add(create_child(content_inner), proportion=1, flag=wx.EXPAND)
            content_inner.AddSpacer(padding)
            return content_inner
        
        content = BoxPanel(parent, wx.HORIZONTAL)
        content.AddSpacer(padding)
        content.Add(create_content_inner(content), proportion=1, flag=wx.EXPAND)
        content.AddSpacer(padding)
        return content
    
    def _create_content(self, parent):
        def create_entity_tree(parent):
            self.entity_tree = EntityTree(parent, self.project)
            
            return self.entity_tree.peer
        
        def create_button_bar(parent):
            content = BoxPanel(parent, wx.HORIZONTAL)
            content.Add(wx.Button(content, label='+ URL'))
            content.AddSpacer(_DIALOG_INNER_PADDING)
            content.Add(wx.Button(content, label='+ Group'))
            content.AddSpacer(_DIALOG_INNER_PADDING)
            content.Add(wx.Button(content, label='-'))
            content.AddSpacer(_DIALOG_INNER_PADDING * 2)
            content.AddStretchSpacer()
            content.Add(wx.Button(content, label='Update Membership'))
            content.AddSpacer(_DIALOG_INNER_PADDING)
            content.Add(wx.Button(content, label='Download'))
            return content
        
        content = BoxPanel(parent, wx.VERTICAL)
        content.Add(create_entity_tree(content), proportion=1, flag=wx.EXPAND)
        content.AddSpacer(_DIALOG_INNER_PADDING)
        content.Add(create_button_bar(content), flag=wx.EXPAND)
        return content

# ------------------------------------------------------------------------------

class _BoxMixin:
    def __init__(self, orient):
        self.sizer = wx.BoxSizer(orient)
        self.SetSizer(self.sizer)
    
    def Add(self, child, *args, **kwargs):
        if child.GetParent() is not self:
            raise ValueError('Child not initialized with correct parent.')
        self.sizer.Add(child, *args, **kwargs)
    
    def AddSpacer(self, size):
        return self.sizer.AddSpacer(size)
    
    def AddStretchSpacer(self, *args, **kwargs):
        return self.sizer.AddStretchSpacer(*args, **kwargs)

class BoxPanel(wx.Panel, _BoxMixin):
    def __init__(self, parent, orient, *args, **kwargs):
        wx.Panel.__init__(self, parent, *args, **kwargs)
        _BoxMixin.__init__(self, orient)
