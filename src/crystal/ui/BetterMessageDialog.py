from collections.abc import Callable
from crystal.util.wx_bind import bind
from crystal.util.wx_dialog import (
    position_dialog_initially, set_dialog_or_frame_icon_if_appropriate,
)
from crystal.util.xos import is_wx_gtk
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
            *, checkbox_label: str | None=None,
            on_checkbox_clicked: Callable[[wx.CommandEvent], None] | None=None,
            yes_label: str | None=None, 
            no_label: str | None=None, 
            escape_is_cancel: bool=False,
            name: str | None=None,
            ) -> None:
        """
        Arguments:
        * parent -- parent window.
        * message -- the message displayed in the dialog.
        * title -- the title displayed in the dialog's titlebar.
        * style -- the set of buttons to display. See wx.Dialog.CreateButtonSizer() for all options.
        * yes_label -- label for the wx.YES button.
        * no_label -- label for the wx.NO button.
        """
        if name is None:
            super().__init__(parent, title=title)
        else:
            super().__init__(parent, title=title, name=name)
        set_dialog_or_frame_icon_if_appropriate(self)
        
        self_sizer = wx.BoxSizer(wx.VERTICAL); self.SetSizer(self_sizer)
        
        bind(self, wx.EVT_BUTTON, self._on_button)
        
        message_label = wx.StaticText(self, label=message)
        message_label.Wrap(400)
        self_sizer.Add(
            message_label,
            flag=wx.ALL,
            border=_WINDOW_INNER_PADDING)
        if checkbox_label is None:
            self._checkbox = None
        else:
            self._checkbox = wx.CheckBox(
                self, label=checkbox_label,
                **(dict(name=f'{name}__checkbox') if name else dict()))
            if on_checkbox_clicked is not None:
                bind(self._checkbox, wx.EVT_CHECKBOX, on_checkbox_clicked)
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
            self.FindWindow(id=wx.ID_YES).SetLabel(yes_label)
        if no_label is not None:
            self.FindWindow(id=wx.ID_NO).SetLabel(no_label)
        
        if escape_is_cancel:
            self.SetEscapeId(wx.ID_CANCEL)
        
        position_dialog_initially(self)
        
        # HACK: wxGTK won't compute size of first dialog shown correctly
        #       unless it is explicitly shown during a Fit()
        if is_wx_gtk():
            self.Show()
        self.Fit()
        if is_wx_gtk():
            self.Hide()
    
    def IsCheckBoxChecked(self) -> bool:
        if self._checkbox is None:
            raise ValueError()
        return self._checkbox.Value
    
    def _on_button(self, event: wx.CommandEvent) -> None:
        self.EndModal(event.GetId())
        self.Hide()
