from crystal.util.xos import is_linux, is_windows
import wx


def wrap_static_box_sizer_child(child: wx.Sizer) -> wx.Sizer:
    if is_linux():
        # Add padding around contents of wx.StaticBoxSizer because
        # wxGTK does not do this automatically, unlike macOS and Windows
        container = wx.BoxSizer(wx.VERTICAL)
        container.Add(child, proportion=1, flag=wx.ALL|wx.EXPAND, border=8)
        return container
    elif is_windows():
        # Default padding in Windows is cramped. So add some more.
        container = wx.BoxSizer(wx.VERTICAL)
        container.Add(child, proportion=1, flag=wx.ALL|wx.EXPAND, border=4)
        return container
    else:
        return child