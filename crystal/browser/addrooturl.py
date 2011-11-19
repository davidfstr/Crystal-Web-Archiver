import wx

_WINDOW_INNER_PADDING = 10
_FORM_LABEL_INPUT_SPACING = 5
_FORM_ROW_SPACING = 10

class AddRootUrlDialog(object):
    def __init__(self, parent, on_finish):
        """
        Arguments:
        parent -- parent wx.Window that this dialog is attached to.
        on_finish -- called when OK pressed on dialog. Is a callable(name, url).
        """
        self.on_finish = on_finish
        
        dialog = self.dialog = wx.Dialog(parent, title='Add Root URL')
        dialog_sizer = wx.BoxSizer(wx.VERTICAL)
        dialog.SetSizer(dialog_sizer)
        dialog.Bind(wx.EVT_BUTTON, self._on_button)
        dialog.Bind(wx.EVT_CLOSE, self._on_close)
        
        dialog_sizer.Add(self._create_fields(dialog), flag=wx.EXPAND|wx.ALL,
            border=_WINDOW_INNER_PADDING)
        dialog_sizer.Add(dialog.CreateButtonSizer(wx.OK|wx.CANCEL), flag=wx.EXPAND|wx.BOTTOM,
            border=_WINDOW_INNER_PADDING)
        
        self.name_field.SetFocus()
        
        dialog.Fit()
        dialog.Show(True)
    
    def _create_fields(self, parent):
        fields_sizer = wx.FlexGridSizer(rows=2, cols=2,
            vgap=_FORM_ROW_SPACING, hgap=_FORM_LABEL_INPUT_SPACING)
        fields_sizer.AddGrowableCol(1)
        
        fields_sizer.Add(wx.StaticText(parent, label='Name:', style=wx.ALIGN_RIGHT), flag=wx.EXPAND)
        self.name_field = wx.TextCtrl(parent)
        self.name_field.SetSelection(-1, -1)
        fields_sizer.Add(self.name_field, flag=wx.EXPAND)
        
        fields_sizer.Add(wx.StaticText(parent, label='URL:', style=wx.ALIGN_RIGHT), flag=wx.EXPAND)
        self.url_field = wx.TextCtrl(parent, value='http://', size=(300,-1)) # width hint
        self.url_field.SetSelection(-1, -1)
        fields_sizer.Add(self.url_field, flag=wx.EXPAND)
        
        return fields_sizer
    
    def _on_button(self, event):
        btn_id = event.GetEventObject().GetId()
        if btn_id == wx.ID_OK:
            self._on_ok(event)
        elif btn_id == wx.ID_CANCEL:
            self._on_cancel(event)
    
    def _on_close(self, event):
        self._on_cancel(event)
    
    def _on_ok(self, event):
        name = self.name_field.GetValue()
        url = self.url_field.GetValue()
        self.on_finish(name, url)
        self.dialog.Destroy()
    
    def _on_cancel(self, event):
        self.dialog.Destroy()
    
    