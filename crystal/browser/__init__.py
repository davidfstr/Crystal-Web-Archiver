from crystal.browser.entitytree import EntityTree
from crystal.ui import BoxPanel, PaddedPanel
import wx

_DIALOG_INNER_PADDING = 10

class MainWindow(object):
    def __init__(self, project):
        self.project = project
        
        frame = wx.Frame(None, title='Crystal')
        
        PaddedPanel(frame, _DIALOG_INNER_PADDING, self._create_content)
        
        frame.GetChildren()[0].Fit(); frame.Fit()
        frame.Show(True)
    
    def _create_content(self, parent):
        content = BoxPanel(parent, wx.VERTICAL)
        content.Add(self._create_entity_tree(content), proportion=1, flag=wx.EXPAND)
        content.AddSpacer(_DIALOG_INNER_PADDING)
        content.Add(self._create_button_bar(content), flag=wx.EXPAND)
        return content
    
    def _create_entity_tree(self, parent):
        self.entity_tree = EntityTree(parent, self.project)
        
        return self.entity_tree.peer
    
    def _create_button_bar(self, parent):
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
