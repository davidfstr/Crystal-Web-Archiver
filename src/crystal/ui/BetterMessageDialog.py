from typing import Callable, Optional
import wx

_WINDOW_INNER_PADDING = 10

class BetterMessageDialog(wx.Dialog):
    """
    Implements a version of wx.MessageDialog that allows the button names
    to be customized. It also allows an optional checkbox.
    """
    def __init__(self, 
            parent: wx.Window, 
            message: str, 
            title: str, 
            style,
            *, checkbox_label: Optional[str]=None,
            on_checkbox_clicked: Optional[Callable[[wx.CommandEvent], None]]=None,
            yes_label: Optional[str]=None, 
            no_label: Optional[str]=None, 
            escape_is_cancel: bool=False,
            ) -> None:
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
        if checkbox_label is None:
            self._checkbox = None
        else:
            self._checkbox = wx.CheckBox(self, label=checkbox_label)
            if on_checkbox_clicked is not None:
                self._checkbox.Bind(wx.EVT_CHECKBOX, on_checkbox_clicked)
        self_sizer.Add(
            self._checkbox,
            flag=wx.LEFT | wx.BOTTOM | wx.ALIGN_LEFT,
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
    
    def IsCheckBoxChecked(self) -> bool:
        if self._checkbox is None:
            raise ValueError()
        return self._checkbox.Value
    
    def _on_button(self, event):
        self.EndModal(event.GetEventObject().GetId())
        self.Hide()
