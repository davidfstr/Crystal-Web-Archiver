# -*- coding: utf-8 -*-

import sys
import wx

_WINDOW_INNER_PADDING = 10
_FORM_LABEL_INPUT_SPACING = 5
_FORM_ROW_SPACING = 10

class AddGroupDialog(object):
    def __init__(self, parent):
        frame = wx.Dialog(parent, title='Add Group')
        frame_sizer = wx.BoxSizer(wx.VERTICAL)
        frame.SetSizer(frame_sizer)
        
        # Mac: Requires wx 2.9 to appear in native look & feel
        preview_box = wx.CollapsiblePane(frame, label='Preview')
        preview_box_root = preview_box.GetPane()
        preview_box_root_sizer = wx.BoxSizer(wx.VERTICAL)
        preview_box_root.SetSizer(preview_box_root_sizer)
        preview_box_root_sizer.SetSizeHints(preview_box_root)
        
        url_list = wx.ListBox(preview_box_root, style=wx.LB_ALWAYS_SB, size=(-1,150))
        url_list.InsertItems(['<url 1>', '<url 2>'], 0)
        
        preview_box_root_sizer.Add(wx.StaticText(preview_box_root, label='Known matching URLs:'), flag=wx.EXPAND)
        preview_box_root_sizer.Add(url_list, flag=wx.EXPAND)
        
        content_sizer = wx.BoxSizer(wx.VERTICAL)
        content_sizer.Add(self._create_fields(frame), flag=wx.EXPAND)
        content_sizer.Add(preview_box, flag=wx.EXPAND)
        
        frame_sizer.Add(content_sizer, flag=wx.EXPAND|wx.ALL,
            border=_WINDOW_INNER_PADDING)
        frame_sizer.Add(frame.CreateButtonSizer(wx.OK|wx.CANCEL), flag=wx.EXPAND|wx.BOTTOM,
            border=_WINDOW_INNER_PADDING)
        
        frame.Fit()
        frame.Show(True)
    
    def _create_fields(self, parent):
        fields_sizer = wx.FlexGridSizer(rows=2, cols=2,
            vgap=_FORM_ROW_SPACING, hgap=_FORM_LABEL_INPUT_SPACING)
        fields_sizer.AddGrowableCol(1)
        
        fields_sizer.Add(wx.StaticText(parent, label='Name:', style=wx.ALIGN_RIGHT), flag=wx.EXPAND)
        self.name_field = wx.TextCtrl(parent)
        fields_sizer.Add(self.name_field, flag=wx.EXPAND)
        
        pattern_field_sizer = wx.BoxSizer(wx.VERTICAL)
        self.pattern_field = wx.TextCtrl(parent, value='http://', size=(300,-1)) # width hint
        pattern_field_sizer.Add(self.pattern_field, flag=wx.EXPAND)
        pattern_field_sizer.Add(wx.StaticText(parent, label='# = digit, @ = alpha, * = any nonslash, ** = any'), flag=wx.EXPAND)
        
        fields_sizer.Add(wx.StaticText(parent, label='Pattern:', style=wx.ALIGN_RIGHT|wx.ALIGN_TOP), flag=wx.EXPAND)
        fields_sizer.Add(pattern_field_sizer, flag=wx.EXPAND)
        
        return fields_sizer
