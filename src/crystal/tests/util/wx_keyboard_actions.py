"""
Utilities for simulating pressing keys in a wx.Window in a highly-accurate fashion.

At the time of writing, the heaviest user of these utilities is:
    - test_can_download_and_serve_a_static_site_using_using_keyboard
Read that test to see examples of using these methods in context
of performing real actions in a workflow.
"""

from crystal.util.xos import is_linux, is_mac_os, is_windows, is_wx_gtk
import wx


# ------------------------------------------------------------------------------
# Press <Key> in <Window>

def press_return_in_window_triggering_default_button(tlw: wx.TopLevelWindow) -> None:
    """
    Simulates a Return key press on the specified window that triggers
    the default button.
    """
    # If there is a default button, Return will trigger it
    if is_mac_os() or is_windows() or is_wx_gtk():
        # NOTE: On macOS, wxPython handles Return key for default buttons natively
        #       through Cocoa, not through wx events. We need to find the default
        #       button and trigger it directly using Command(), which is what
        #       wxWidgets does internally when Return is pressed in text controls.
        #       Evidence: https://github.com/wxWidgets/wxWidgets/blob/08b10e373e8de34ec3f7439615e16a2288df0b35/src/osx/cocoa/button.mm#L284-L296
        # 
        # NOTE: On Windows, wxPython handles Return key for default buttons through
        #       MSWProcessMessage(), which intercepts WM_KEYDOWN messages with VK_RETURN,
        #       finds the default button, and triggers it by calling MSWCommand(BN_CLICKED, 0).
        #       Since we can't easily create the MSG structure from Python, we'll use the
        #       same approach as macOS: find the default button and trigger it directly.
        #       Evidence: https://github.com/wxWidgets/wxWidgets/blob/08b10e373e8de34ec3f7439615e16a2288df0b35/src/msw/window.cpp#L2541-L2741
        # 
        # NOTE: On Linux/GTK, wxPython handles Return key for default buttons through
        #       GTK's native window management in the top-level window key handler.
        #       The key press goes to gtk_window_activate_key() which, according to GTK
        #       documentation, checks if the key press should activate the default widget.
        #       wxWidgets uses GTK's default activation mechanism elsewhere (e.g. calling
        #       gtk_window_activate_default() in listbox.cpp:157), confirming this approach.
        #       Since we can't directly call GTK functions from Python, we'll use the
        #       same approach as other platforms: find the default button and trigger it directly.
        #       Evidence: https://github.com/wxWidgets/wxWidgets/blob/08b10e373e8de34ec3f7439615e16a2288df0b35/src/gtk/toplevel.cpp#L216-L234
        default_item = tlw.GetDefaultItem()
        if default_item is not None and default_item.Enabled:
            evt = wx.CommandEvent(wx.wxEVT_BUTTON, default_item.GetId())
            evt.SetEventObject(default_item)
            default_item.Command(evt)
    else:
        raise NotImplementedError(
            'Triggering the effect of Return key '
            'not yet implemented for this OS'
        )


def press_tab_in_window_to_navigate_focus(window: wx.Window) -> None:
    """
    Simulates a Tab key press on the specified window that
    navigates focus forward.
    """
    window.NavigateIn(wx.NavigationKeyEvent.IsForward)


def press_shift_tab_in_window_to_navigate_focus(window: wx.Window) -> None:
    """
    Simulates a Shift+Tab key press on the specified window that
    navigates focus backward.
    """
    window.NavigateIn(wx.NavigationKeyEvent.IsBackward)


def press_key_in_window_triggering_menu_item(
        window: wx.Window,
        key_code: int,
        *, ctrl: bool=False, shift: bool=False, alt: bool=False
        ) -> None:
    """
    Simulates a key press on the specified window that triggers a menu item.
    
    This directly mimics the accelerator-checking logic in
    wxWindowMac::OSXHandleKeyEvent from src/osx/window_osx.cpp:
    1. Walk up the window hierarchy looking for an accelerator table
    2. Check if the key event matches any accelerator
    3. If found, fire a wxEVT_MENU event with the command ID
    """
    # Create a CHAR_HOOK event to match against accelerator tables
    key_event = wx.KeyEvent(wx.wxEVT_CHAR_HOOK)
    key_event.SetKeyCode(key_code)
    if ctrl:
        key_event.SetControlDown(True)
    if shift:
        key_event.SetShiftDown(True)
    if alt:
        key_event.SetAltDown(True)
    key_event.SetId(window.GetId())
    key_event.SetEventObject(window)
    
    # If the window (or an ancestor) is a Frame, check its MenuBar for matching accelerators
    ancestor = window
    while ancestor is not None:
        if isinstance(ancestor, wx.Frame):
            menu_bar = ancestor.GetMenuBar()
            if menu_bar is not None:
                for (menu, _) in menu_bar.Menus:
                    menu_item = _find_menu_item_with_matching_accelerator(menu, key_event)
                    if menu_item is None:
                        continue
                    if not menu_item.Enabled:
                        continue
                    # Found a matching menu item. Fire wxEVT_MENU event.
                    menu_item.Menu.ProcessEvent(
                        wx.CommandEvent(wx.wxEVT_MENU, menu_item.Id))
                    return
        
        # Check parent window
        ancestor = ancestor.GetParent()
    
    # (No accelerator found. Do nothing.)
    pass


def _find_menu_item_with_matching_accelerator(
        menu: wx.Menu,
        key_event: wx.KeyEvent
        ) -> wx.MenuItem | None:
    """
    Recursively searches a menu and its submenus for a menu item
    with an accelerator matching the given key event.
    """
    for item in menu.MenuItems:
        if item.IsSeparator():
            continue
        
        # Check if this item has a submenu
        if item.IsSubMenu():
            submenu = item.GetSubMenu()
            if submenu is not None:
                result = _find_menu_item_with_matching_accelerator(submenu, key_event)
                if result is not None:
                    return result
        
        # Check if this item's accelerator matches the key event
        accel = item.GetAccel()
        if accel is not None:
            # Match key code
            if accel.GetKeyCode() != key_event.GetKeyCode():
                continue
            
            # Match modifiers
            flags = accel.GetFlags()
            if ((flags & wx.ACCEL_CTRL) != 0) != key_event.ControlDown():
                continue
            if ((flags & wx.ACCEL_SHIFT) != 0) != key_event.ShiftDown():
                continue
            if ((flags & wx.ACCEL_ALT) != 0) != key_event.AltDown():
                continue
            
            # All parts match!
            return item
    
    return None


def press_arrow_key_in_treectrl(
        window: wx.TreeCtrl,
        key_code: int,
        ) -> None:
    """
    Simulates an arrow key press on the specified wx.TreeCtrl.
    
    On macOS/Linux: Uses wxEVT_CHAR because that's what wxGenericTreeCtrl
    listens to for handling arrow key navigation. See:
    - wxGenericTreeCtrl::OnChar in wxWidgets/src/generic/treectlg.cpp
    - EVT_CHAR binding in the event table around line 946
    
    On Windows: Simulates the effects of arrow keys directly, mirroring the
    behavior of wxTreeCtrl::MSWHandleSelectionKey in 
    wxWidgets/src/msw/treectrl.cpp, because Windows TreeCtrl processes 
    arrow keys via WM_KEYDOWN messages before wxEVT_CHAR events are generated.
    """
    if not window.Enabled:
        return
    
    if is_mac_os() or is_linux():
        key_event = wx.KeyEvent(wx.wxEVT_CHAR)
        key_event.SetKeyCode(key_code)
        key_event.SetId(window.GetId())
        key_event.SetEventObject(window)
        window.ProcessEvent(key_event)
    elif is_windows():
        _press_arrow_key_in_treectrl_on_windows(window, key_code)
    else:
        raise NotImplementedError('Unrecognized OS')


def _press_arrow_key_in_treectrl_on_windows(
        tree: wx.TreeCtrl,
        key_code: int,
        ) -> None:
    """
    Simulates the effects of arrow keys on a wx.TreeCtrl on Windows,
    paralleling the behavior of wxTreeCtrl::MSWHandleSelectionKey().
    
    See: https://github.com/wxWidgets/wxWidgets/blob/08b10e373e8de34ec3f7439615e16a2288df0b35/src/msw/treectrl.cpp#L2368-L2563
    """
    htSel = tree.GetSelection()
    
    if key_code == wx.WXK_UP:
        # VK_UP case (simplified: no Ctrl/Shift handling)
        if htSel.IsOk():
            next_item = tree.GetPrevVisible(htSel)
            if next_item.IsOk():
                _select_tree_item_firing_events(tree, htSel, next_item)
    
    elif key_code == wx.WXK_DOWN:
        # VK_DOWN case (simplified: no Ctrl/Shift handling)
        if htSel.IsOk():
            next_item = tree.GetNextVisible(htSel)
            if next_item.IsOk():
                _select_tree_item_firing_events(tree, htSel, next_item)
        else:
            # No selection: select root item
            root_item = tree.GetRootItem()
            if root_item.IsOk():
                # Check if root is hidden
                if tree.HasFlag(wx.TR_HIDE_ROOT):
                    # Get first child of root
                    first_child, _ = tree.GetFirstChild(root_item)
                    if first_child.IsOk():
                        _select_tree_item_firing_events(tree, wx.TreeItemId(), first_child)
                else:
                    _select_tree_item_firing_events(tree, wx.TreeItemId(), root_item)
    
    elif key_code == wx.WXK_LEFT:
        # VK_LEFT case
        if htSel.IsOk():
            if tree.ItemHasChildren(htSel) and tree.IsExpanded(htSel):
                # Collapse if expanded and has children
                tree.Collapse(htSel)
            else:
                # Navigate to parent
                parent_item = tree.GetItemParent(htSel)
                if parent_item.IsOk():
                    # Check if parent is hidden root
                    root_item = tree.GetRootItem()
                    if not (tree.HasFlag(wx.TR_HIDE_ROOT) and parent_item == root_item):
                        _select_tree_item_firing_events(tree, htSel, parent_item)
    
    elif key_code == wx.WXK_RIGHT:
        # VK_RIGHT case
        if htSel.IsOk():
            # Ensure visible
            tree.EnsureVisible(htSel)
            
            if tree.ItemHasChildren(htSel):
                if not tree.IsExpanded(htSel):
                    # Expand if collapsed
                    tree.Expand(htSel)
                else:
                    # Navigate to first child if already expanded
                    first_child, _ = tree.GetFirstChild(htSel)
                    if first_child.IsOk():
                        _select_tree_item_firing_events(tree, htSel, first_child)


def _select_tree_item_firing_events(
        tree: wx.TreeCtrl,
        old_item: wx.TreeItemId,
        new_item: wx.TreeItemId
        ) -> None:
    """
    Selects a tree item and fires the appropriate selection change events,
    mirroring the behavior in wxTreeCtrl::MSWHandleSelectionKey().
    """
    # Fire SEL_CHANGING event
    changing_event = wx.TreeEvent(wx.wxEVT_TREE_SEL_CHANGING, tree, new_item)
    if old_item.IsOk():
        # NOTE: wxPython doesn't expose SetOldItem(), so we set m_itemOld directly
        changing_event.m_itemOld = old_item
    
    # Allow handlers to veto the selection
    if not tree.ProcessEvent(changing_event) or changing_event.IsAllowed():
        # Perform the selection
        tree.UnselectAll()
        tree.SelectItem(new_item)
        
        # Fire SEL_CHANGED event
        changed_event = wx.TreeEvent(wx.wxEVT_TREE_SEL_CHANGED, tree, new_item)
        if old_item.IsOk():
            # NOTE: wxPython doesn't expose SetOldItem(), so we set m_itemOld directly
            changed_event.m_itemOld = old_item
        tree.ProcessEvent(changed_event)


# ------------------------------------------------------------------------------