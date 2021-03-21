import wx

_WINDOW_INNER_PADDING = 10

class BetterMessageDialog(wx.Dialog):
    """
    Implements a version of wx.MessageDialog that allows the button names to be customized.
    """
    def __init__(self, parent, message, title, style, yes_label=None, no_label=None, escape_is_cancel=False):
        """
        Arguments:
        parent -- parent window.
        message -- the message displayed in the dialog.
        title -- the title displayed in the dialog's titlebar.
        style -- the set of buttons to display.
                 See wx.Dialog.CreateButtonSizer() for all options.
        yes_label -- label for the wx.YES button.
        no_label -- label for the wx.NO button.
        """
        wx.Dialog.__init__(self, parent, title=title)
        self_sizer = wx.BoxSizer(wx.VERTICAL); self.SetSizer(self_sizer)
        self.Bind(wx.EVT_BUTTON, self._on_button)
        
        message_label = wx.StaticText(self, label=message)
        message_label.Wrap(400)
        self_sizer.Add(
            message_label,
            flag=wx.ALL,
            border=_WINDOW_INNER_PADDING)
        self_sizer.Add(
            self.CreateButtonSizer(style),
            flag=wx.BOTTOM | wx.ALIGN_RIGHT,
            border=_WINDOW_INNER_PADDING)
        
        # Customize button titles
        if yes_label is not None:
            self.FindWindowById(wx.ID_YES).SetLabel(yes_label)
        if no_label is not None:
            self.FindWindowById(wx.ID_NO).SetLabel(no_label)
        
        if escape_is_cancel:
            self.SetEscapeId(wx.ID_CANCEL)
        
        self.Fit()
    
    def _on_button(self, event):
        self.EndModal(event.GetEventObject().GetId())
        self.Hide()
