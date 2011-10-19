from crystal.ui import BoxPanel, PaddedPanel
import wx

_WINDOW_INNER_PADDING = 10
_FORM_LABEL_INPUT_SPACING = 5
_FORM_ROW_SPACING = 10

class AddRootUrlDialog(object):
    def __init__(self, parent):
        frame = wx.Dialog(parent, title='Add Root URL')
        
        PaddedPanel(frame, _WINDOW_INNER_PADDING, self._create_content)
        
        # TODO: Listen for EVT_CLOSE events on self
        
        frame.GetChildren()[0].Fit(); frame.Fit()
        frame.Show(True)
    
    def _create_content(self, parent):
        content = BoxPanel(parent, wx.VERTICAL)
        content.Add(self._create_fields(content), proportion=1, flag=wx.EXPAND)
        content.AddSpacer(_WINDOW_INNER_PADDING)
        content.Add(self._create_button_bar(content), flag=wx.EXPAND)
        return content
    
    def _create_fields(self, parent):
        content = wx.Panel(parent)
        content_sizer = wx.FlexGridSizer(rows=2, cols=2,
            vgap=_FORM_ROW_SPACING, hgap=_FORM_LABEL_INPUT_SPACING)
        content_sizer.AddGrowableCol(1)
        content.SetSizer(content_sizer)
        
        content_sizer.Add(wx.StaticText(content, label='Name:', style=wx.ALIGN_RIGHT), flag=wx.EXPAND)
        self.name_field = wx.TextCtrl(content)
        content_sizer.Add(self.name_field, flag=wx.EXPAND)
        
        content_sizer.Add(wx.StaticText(content, label='URL:', style=wx.ALIGN_RIGHT), flag=wx.EXPAND)
        self.url_field = wx.TextCtrl(content, value='http://', size=(300,-1)) # width hint
        content_sizer.Add(self.url_field, flag=wx.EXPAND)
        
        return content
    
    # TODO: Use wx.Dialog.CreateButtonSizer to position and order buttons appropriately
    def _create_button_bar(self, parent):
        content = BoxPanel(parent, wx.HORIZONTAL)
        content.AddStretchSpacer()
        content.Add(wx.Button(content, id=wx.ID_CANCEL, label='Cancel'))
        content.AddSpacer(_WINDOW_INNER_PADDING)
        content.Add(wx.Button(content, id=wx.ID_OK, label='OK'))
        return content
