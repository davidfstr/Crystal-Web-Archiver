from crystal.ui import BoxPanel, PaddedPanel
import wx

_DIALOG_INNER_PADDING = 10

class AddRootUrlDialog(object):
    def __init__(self, parent):
        # TODO: Remove explicit size once Fit is being used
        frame = wx.Frame(parent, title='Add Root URL', size=(500,300))
        
        PaddedPanel(frame, _DIALOG_INNER_PADDING, self._create_content)
        
        frame.SetDefaultItem(self.ok_button)
        # TODO: Use fit once all sizers are working
        #frame.GetChildren()[0].Fit(); frame.Fit()
        frame.Show(True)
    
    def _create_content(self, parent):
        content = BoxPanel(parent, wx.VERTICAL)
        content.Add(self._create_fields(content), proportion=1, flag=wx.EXPAND)
        content.AddSpacer(_DIALOG_INNER_PADDING)
        content.Add(self._create_button_bar(content), flag=wx.EXPAND)
        return content
    
    def _create_fields(self, parent):
        return wx.Button(parent, label='-----------------Fields-----------------')
    
    def _create_button_bar(self, parent):
        content = BoxPanel(parent, wx.HORIZONTAL)
        content.AddStretchSpacer()
        content.Add(wx.Button(content, label='Cancel'))
        content.AddSpacer(_DIALOG_INNER_PADDING)
        self.ok_button = wx.Button(content, label='OK')
        content.Add(self.ok_button)
        return content
