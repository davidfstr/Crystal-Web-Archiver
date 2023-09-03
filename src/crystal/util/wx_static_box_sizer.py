from crystal.util.xos import is_linux
import wx


def wrap_static_box_sizer_child(child: wx.Sizer) -> wx.Sizer:
    if is_linux():
        # Add padding around contents of wx.StaticBoxSizer because
        # wxGTK does not do this automatically, unlike macOS and Windows
        container = wx.BoxSizer(wx.VERTICAL)
        container.Add(child, flag=wx.ALL|wx.EXPAND, border=8)
        return container
    else:
        return child