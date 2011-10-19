"""
Contains utility functions for manipulating the UI.
"""

# Initialize wx, if not already done
import wx

# Single global app object
APP = wx.PySimpleApp()

def ui_call_later(callable):
    """
    Calls the argument on the UI thread.
    This should be used for any operation that needs to access UI elements.
    """
    if wx.Thread_IsMain():
        callable()
    else:
        wx.CallAfter(callable)

class _BoxMixin:
    """
    Mixin for wx.Window subclasses that manage an internal wx.BoxSizer.
    """
    def __init__(self, orient):
        """
        Arguments:
        orient -- layout direction. Either wx.HORIZONTAL or wx.VERTICAL.
        """
        self.sizer = wx.BoxSizer(orient)
        self.SetSizer(self.sizer)
    
    def Add(self, child, *args, **kwargs):
        """
        Adds the specified child to this container's sizer.
        """
        if child.GetParent() is not self:
            raise ValueError('Child not initialized with correct parent.')
        self.sizer.Add(child, *args, **kwargs)
    
    def AddSpacer(self, size):
        """
        Adds a fixed-size spacer of the specified size.
        """
        return self.sizer.AddSpacer(size)
    
    def AddStretchSpacer(self, *args, **kwargs):
        """
        Adds a variable-size spacer.
        """
        return self.sizer.AddStretchSpacer(*args, **kwargs)

class BoxPanel(wx.Panel, _BoxMixin):
    """
    Subclass of wx.Panel that has an automatically configured wx.BoxSizer.
    
    Most UIs can be constructed with nested boxes.
    """
    def __init__(self, parent, orient, *args, **kwargs):
        """
        Arguments:
        parent -- parent wx.Window.
        orient -- layout direction. Either wx.HORIZONTAL or wx.VERTICAL.
        """
        wx.Panel.__init__(self, parent, *args, **kwargs)
        _BoxMixin.__init__(self, orient)

class PaddedPanel(object):
    """
    Panel that has a fixed size border around its single child.
    """
    def __new__(cls, parent, padding, create_child):
        """
        Arguments:
        parent -- parent wx.Window.
        padding -- number of padding pixels around all sides of the child.
        create_child -- function(parent : wx.Window) that creates this panel's child.
        """
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
