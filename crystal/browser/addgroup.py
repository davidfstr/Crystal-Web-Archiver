# -*- coding: utf-8 -*-

import sys
import wx

_WINDOW_INNER_PADDING = 10
_FORM_LABEL_INPUT_SPACING = 5
_FORM_ROW_SPACING = 10

class AddGroupDialog(object):
    def __init__(self, parent, on_finish, initial_url=None):
        """
        Arguments:
        parent -- parent wx.Window that this dialog is attached to.
        on_finish -- called when OK pressed on dialog. Is a callable(name, url_pattern).
        initial_url -- overrides the initial URL displayed.
        """
        self.on_finish = on_finish
        if initial_url is None:
            initial_url = 'http://'
        
        dialog = self.dialog = wx.Dialog(parent, title='Add Group')
        dialog_sizer = wx.BoxSizer(wx.VERTICAL)
        dialog.SetSizer(dialog_sizer)
        dialog.Bind(wx.EVT_BUTTON, self._on_button)
        dialog.Bind(wx.EVT_CLOSE, self._on_close)
        
        # Mac: Requires wx 2.9 to appear in native look & feel
        preview_box = wx.CollapsiblePane(dialog, label='Preview')
        preview_box_root = preview_box.GetPane()
        preview_box_root_sizer = wx.BoxSizer(wx.VERTICAL)
        preview_box_root.SetSizer(preview_box_root_sizer)
        preview_box_root_sizer.SetSizeHints(preview_box_root)
        
        url_list = wx.ListBox(preview_box_root, style=wx.LB_ALWAYS_SB, size=(-1,150))
        url_list.InsertItems(['<url 1>', '<url 2>'], 0)
        
        preview_box_root_sizer.Add(wx.StaticText(preview_box_root, label='Known matching URLs:'), flag=wx.EXPAND)
        preview_box_root_sizer.Add(url_list, flag=wx.EXPAND)
        
        content_sizer = wx.BoxSizer(wx.VERTICAL)
        content_sizer.Add(self._create_fields(dialog, initial_url), flag=wx.EXPAND)
        content_sizer.Add(preview_box, flag=wx.EXPAND)
        
        dialog_sizer.Add(content_sizer, flag=wx.EXPAND|wx.ALL,
            border=_WINDOW_INNER_PADDING)
        dialog_sizer.Add(dialog.CreateButtonSizer(wx.OK|wx.CANCEL), flag=wx.EXPAND|wx.BOTTOM,
            border=_WINDOW_INNER_PADDING)
        
        self.name_field.SetFocus()
        
        dialog.Fit()
        dialog.Show(True)
    
    def _create_fields(self, parent, initial_url):
        fields_sizer = wx.FlexGridSizer(rows=2, cols=2,
            vgap=_FORM_ROW_SPACING, hgap=_FORM_LABEL_INPUT_SPACING)
        fields_sizer.AddGrowableCol(1)
        
        fields_sizer.Add(wx.StaticText(parent, label='Name:', style=wx.ALIGN_RIGHT), flag=wx.EXPAND)
        self.name_field = wx.TextCtrl(parent)
        self.name_field.SetSelection(-1, -1)
        fields_sizer.Add(self.name_field, flag=wx.EXPAND)
        
        pattern_field_sizer = wx.BoxSizer(wx.VERTICAL)
        self.pattern_field = wx.TextCtrl(parent, value=initial_url, size=(300,-1)) # width hint
        self.pattern_field.SetSelection(-1, -1)
        pattern_field_sizer.Add(self.pattern_field, flag=wx.EXPAND)
        pattern_field_sizer.Add(wx.StaticText(parent, label='# = digit, @ = alpha, * = any nonslash, ** = any'), flag=wx.EXPAND)
        
        fields_sizer.Add(wx.StaticText(parent, label='URL Pattern:', style=wx.ALIGN_RIGHT|wx.ALIGN_TOP), flag=wx.EXPAND)
        fields_sizer.Add(pattern_field_sizer, flag=wx.EXPAND)
        
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
        url_pattern = self.pattern_field.GetValue()
        self.on_finish(name, url_pattern)
        self.dialog.Destroy()
    
    def _on_cancel(self, event):
        self.dialog.Destroy()
