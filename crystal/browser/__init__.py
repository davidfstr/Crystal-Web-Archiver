from crystal.browser.entitytree import EntityTree
from crystal.ui import BoxPanel, PaddedPanel
import wx

_WINDOW_INNER_PADDING = 10

class MainWindow(object):
    def __init__(self, project):
        self.project = project
        
        frame = wx.Frame(None, title='Crystal')
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
        content_sizer = wx.BoxSizer(wx.HORIZONTAL)
        content_sizer.Add(wx.Button(parent, label='+ URL'))
        content_sizer.AddSpacer(_WINDOW_INNER_PADDING)
        content_sizer.Add(wx.Button(parent, label='+ Group'))
        content_sizer.AddSpacer(_WINDOW_INNER_PADDING)
        content_sizer.Add(wx.Button(parent, label='-'))
        content_sizer.AddSpacer(_WINDOW_INNER_PADDING * 2)
        content_sizer.AddStretchSpacer()
        content_sizer.Add(wx.Button(parent, label='Update Membership'))
        content_sizer.AddSpacer(_WINDOW_INNER_PADDING)
        content_sizer.Add(wx.Button(parent, label='Download'))
        return content_sizer
