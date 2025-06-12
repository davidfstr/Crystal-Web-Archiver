from collections.abc import Callable
from crystal.browser.icons import add_transparent_left_border
from crystal.util.wx_bind import bind
from crystal.util.xos import is_mac_os, is_windows
from typing import List
import wx


class Action:
    """
    Represents a command that can be accessed by multiple controls.
    
    When a property of an Action (ex: whether it is enabled) is changed,
    all associated controls will be updated automatically.
    """
    
    def __init__(self,
            menuitem_id: int=wx.ID_ANY,
            # You can prefix a letter in the label with & to underline it
            # and make it triggerable with Alt-<Letter> on Windows.
            # Linux and macOS will ignore & prefixes.
            label: str='',
            accel: wx.AcceleratorEntry | None=None,
            action_func: Callable[[wx.CommandEvent], None] | None=None,
            enabled: bool=True,
            button_bitmap: wx.Bitmap | None=None,
            button_label: str=''):
        self._menuitem_id = menuitem_id
        self._label = label
        self._accel = accel
        self._action_func = action_func
        self._enabled = enabled
        self._button_bitmap = button_bitmap
        self._button_label = button_label
        
        self._menuitems = []  # type: List[wx.MenuItem]
        self._buttons = []  # type: List[wx.Button]
    
    # === Properties ===
    
    def _get_enabled(self) -> bool:
        return self._enabled
    def _set_enabled(self, enabled: bool) -> None:
        self._enabled = enabled
        for mi in self._menuitems:
            mi.Enabled = enabled
        for b in self._buttons:
            b.Enabled = enabled
        
    enabled = property(_get_enabled, _set_enabled)
    
    # === Operations ===
    
    def append_menuitem_to(self, menu: wx.Menu) -> wx.MenuItem:
        """
        Creates a new wx.MenuItem associated with this action
        at the end of the specified menu.
        """
        menuitem = menu.Append(self._menuitem_id, self._label)
        if self._accel is not None:
            menuitem.Accel = self._accel
        if self._action_func is not None:
            bind(menu, wx.EVT_MENU, self._on_menuitem_command)
        menuitem.Enabled = self._enabled
        
        self._menuitems.append(menuitem)  # save reference
        return menuitem
    
    def create_button(self, *args, **kwargs) -> wx.Button:
        """
        Creates a new wx.Button associated with this action.
        """
        button_label = self._button_label or self._label
        if is_mac_os():
            # Don't use &<Letter> on macOS because it:
            # (1) creates an automatic ⌘<Letter> accelerator that, 
            #     when triggered, leaves the associated button stuck in a
            #     weird "pressed" state, and because it
            # (2) doesn't underline the letter or give any visual indication
            #     that the shortcut exists.
            # On macOS rely on menuitem accelerators instead.
            button_label = wx.Control.RemoveMnemonics(button_label)  # reinterpret
        
        button = wx.Button(*args, label=button_label, **kwargs)
        if self._button_bitmap is not None:
            button.SetBitmap(add_transparent_left_border(
                self._button_bitmap,
                # Alter left margin for bitmap to be reasonable on Windows.
                # Initially it is 0.
                8+6 if is_windows() else 0
            ))
            if is_windows():
                # Decrease bitmap-to-text spacing on Windows to be reasonable
                button.SetBitmapMargins((-6, 0))
        # (NOTE: Do NOT set accelerator for the button because it does not
        #        work consistently on macOS. Any action added as a button
        #        should also be added as a menuitem too, and we CAN set an
        #        accelerator reliably there.)
        if self._action_func is not None:
            bind(button, wx.EVT_BUTTON, self._action_func)
        button.Enabled = self._enabled
        
        self._buttons.append(button)  # save reference
        return button
    
    def dispose(self) -> None:
        # Avoid interacting with any further wx.Objects when this Action
        # is being deleted, because some of them are likely to have been 
        # deleted already, and such interactions could cause a crash
        self._menuitems.clear()
        self._buttons.clear()
    
    # === Events ===
    
    def _on_menuitem_command(self, event: wx.CommandEvent) -> None:
        if self._action_func is not None and event.Id in [m.Id for m in self._menuitems]:
            # NOTE: It is the responsiblity of the action function to call
            #       event.Skip() if appropriate.
            self._action_func(event)
        else:
            event.Skip()
