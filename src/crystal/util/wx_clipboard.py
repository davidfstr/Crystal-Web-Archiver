"""Utilities for working with the system clipboard in wxPython."""

from collections.abc import Callable
from crystal.util.wx_bind import bind
from crystal.util.xos import is_linux
import wx


def create_copy_button(
        parent: wx.Window,
        *, name: str,
        text_to_copy: Callable[[], str | None],
        parent_is_disposed: Callable[[], bool],
        ) -> wx.Button:
    if is_linux():
        # Button needs to be at least this large for icon to display at all
        size = (36, 36)
    else:
        size = (24, 24)
    
    copy_button = wx.Button(parent, label='📋', size=size, name=name)
    copy_button.SetToolTip(f'Copy to clipboard')
    
    def on_copy_click(event: wx.CommandEvent | None = None) -> None:
        if parent_is_disposed():
            return
        
        text = text_to_copy()
        if text is None:
            # Not ready to copy yet
            copy_button.SetLabel('⏳')
            copy_button.SetFocus()  # blur the field being copied
            wx.CallLater(200, on_copy_click)  # try again
            return
        
        copy_text_to_clipboard(text)
        
        # 1. Show brief feedback
        # 2. Reset label after delay
        copy_button.SetLabel('✓')
        def reset_label() -> None:
            if parent_is_disposed():
                return
            copy_button.SetLabel('📋')
        wx.CallLater(500, reset_label)
    bind(copy_button, wx.EVT_BUTTON, on_copy_click)
    
    return copy_button


def copy_text_to_clipboard(text: str) -> None:
    if wx.TheClipboard.Open():
        try:
            data = wx.TextDataObject(text)
            wx.TheClipboard.SetData(data)
        finally:
            wx.TheClipboard.Close()
