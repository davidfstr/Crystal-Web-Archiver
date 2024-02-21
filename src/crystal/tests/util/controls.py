from __future__ import annotations

from contextlib import asynccontextmanager, contextmanager
from crystal.tests.util.runner import pump_wx_events
from crystal.util.xos import is_windows
from typing import AsyncIterator, Callable, Iterator, List, Optional
from unittest.mock import patch
import wx


# ------------------------------------------------------------------------------
# Utility: Controls: wx.Button

def click_button(button: wx.Button) -> None:
    # Dispatch wx.EVT_BUTTON event
    event = wx.PyCommandEvent(wx.EVT_BUTTON.typeId, button.GetId())
    event.SetEventObject(button)
    assert event.GetEventObject().GetId() == button.GetId()
    button.Command(event)


# ------------------------------------------------------------------------------
# Utility: Controls: wx.CheckBox

def set_checkbox_value(checkbox: wx.CheckBox, value: bool) -> None:
    """
    Changes the value of a checkbox in a way that fires a realistic
    wx.EVT_CHECKBOX event if appropriate.
    """
    if checkbox.Value != value:
        click_checkbox(checkbox)
        assert checkbox.Value == value


def click_checkbox(checkbox: wx.CheckBox) -> None:
    old_value = checkbox.Value  # capture
    
    # Dispatch wx.EVT_CHECKBOX event
    event = wx.PyCommandEvent(wx.EVT_CHECKBOX.typeId, checkbox.GetId())
    event.SetEventObject(checkbox)
    assert event.GetEventObject().GetId() == checkbox.GetId()
    checkbox.Command(event)
    
    new_value = checkbox.Value  # capture
    assert new_value != old_value, 'Expected checkbox to toggle value'


# ------------------------------------------------------------------------------
# Utility: Controls: wx.FileDialog

@contextmanager
def file_dialog_returning(filepath: str) -> Iterator[None]:
    with patch('wx.FileDialog', spec=True) as MockFileDialog:
        instance = MockFileDialog.return_value
        instance.ShowModal.return_value = wx.ID_OK
        instance.GetPath.return_value = filepath
        
        yield


# ------------------------------------------------------------------------------
# Utility: Controls: wx.Menu

async def select_menuitem(menu: wx.Menu, menuitem_id: int) -> None:
    wx.PostEvent(menu, wx.MenuEvent(type=wx.EVT_MENU.typeId, id=menuitem_id, menu=None))
    await pump_wx_events()


# ------------------------------------------------------------------------------
# Utility: Controls: wx.TreeCtrl

def get_children_of_tree_item(tree: wx.TreeCtrl, tii: wx.TreeItemId) -> List[TreeItem]:
    children = []  # type: List[TreeItem]
    next_child_tii = tree.GetFirstChild(tii)[0]
    while next_child_tii.IsOk():
        children.append(TreeItem(tree, next_child_tii))
        next_child_tii = tree.GetNextSibling(next_child_tii)  # reinterpret
    return children


class TreeItem:
    __slots__ = ['tree', 'id']
    
    def __init__(self, tree: wx.TreeCtrl, id: wx.TreeItemId) -> None:
        if not id.IsOk():
            raise ValueError('TreeItemId is invalid')
        
        self.tree = tree
        self.id = id
    
    # === Peer Queries and Actions ===
    
    @property
    def Text(self) -> str:
        return self.tree.GetItemText(self.id)
    
    @property
    def TextColour(self) -> wx.Colour:
        return self.tree.GetItemTextColour(self.id)
    
    @property
    def Bold(self) -> bool:
        return self.tree.IsBold(self.id)
    
    def SelectItem(self) -> None:
        self.tree.SelectItem(self.id)
    
    def IsSelected(self) -> bool:
        return self.tree.IsSelected(self.id)
    
    @staticmethod
    def GetSelection(tree: wx.TreeCtrl) -> Optional[TreeItem]:
        selected_tii = tree.GetSelection()
        if selected_tii.IsOk():
            return TreeItem(tree, selected_tii)
        else:
            return None
    
    def Expand(self) -> None:
        self.tree.Expand(self.id)
    
    def Collapse(self) -> None:
        self.tree.Collapse(self.id)
    
    def IsExpanded(self) -> bool:
        return self.tree.IsExpanded(self.id)
    
    def ScrollTo(self) -> None:
        self.tree.ScrollTo(self.id)
    
    @staticmethod
    def GetRootItem(tree: wx.TreeCtrl) -> TreeItem:
        root_tii = tree.GetRootItem()
        assert root_tii.IsOk()
        return TreeItem(tree, root_tii)
    
    def GetFirstChild(self) -> Optional[TreeItem]:
        first_child_tii = self.tree.GetFirstChild(self.id)[0]
        if first_child_tii.IsOk():
            return TreeItem(self.tree, first_child_tii)
        else:
            return None
    
    @property
    def Children(self) -> List[TreeItem]:
        return get_children_of_tree_item(self.tree, self.id)
    
    # === Entity Tree: Find Child ===
    
    def find_child(parent_ti: TreeItem, url_or_url_pattern: str, url_prefix: Optional[str]=None) -> TreeItem:
        """
        Returns the first child of the specified parent tree item with the
        specified URL or URL pattern.
        
        Raises TreeItem.ChildNotFound if such a child is not found.
        """
        if url_prefix is not None:
            assert url_prefix.endswith('/')
            if url_or_url_pattern.startswith(url_prefix):
                url_or_url_pattern = '/' + url_or_url_pattern[len(url_prefix):]  # reinterpret
        try:
            (matching_child_ti,) = [
                child for child in parent_ti.Children
                if child.Text.startswith(f'{url_or_url_pattern} - ')
            ]
        except ValueError:
            try:
                (matching_child_ti,) = [
                    child for child in parent_ti.Children
                    if child.Text == url_or_url_pattern
                ]
            except ValueError:
                raise TreeItem.ChildNotFound(
                    f'Child {url_or_url_pattern} not found in specified TreeItem'
                ) from None
        return matching_child_ti
    
    def try_find_child(parent_ti: TreeItem, *args, **kwargs) -> Optional[TreeItem]:
        try:
            return parent_ti.find_child(*args, **kwargs)
        except TreeItem.ChildNotFound:
            return None

    def find_child_by_title(parent_ti: TreeItem, title_fragment: str) -> TreeItem:
        """
        Returns the first child of the specified parent tree item whose
        title contains the specified fragment.
        
        Raises TreeItem.ChildNotFound if such a child is not found.
        """
        try:
            (matching_child_ti,) = [
                child for child in parent_ti.Children
                if title_fragment in child.Text
            ]
            return matching_child_ti
        except ValueError:
            raise TreeItem.ChildNotFound(
                f'Child with title fragment {title_fragment!r} not found in specified TreeItem'
            ) from None
    
    class ChildNotFound(AssertionError):
        pass
    
    # === Operations ===
    
    @asynccontextmanager
    async def right_click_returning_popup_menu(self) -> AsyncIterator[wx.Menu]:
        captured_menu = None  # type: Optional[wx.Menu]
        destroy_captured_menu = None  # type: Optional[Callable[[], None]]
        def PopupMenu(menu: wx.Menu, *args, **kwargs) -> bool:
            nonlocal captured_menu, destroy_captured_menu
            captured_menu = menu
            destroy_captured_menu = captured_menu.Destroy
            # Prevent caller from immediately destroying the menu we're about to return
            def do_nothing(*args, **kwargs) -> None:
                pass
            captured_menu.Destroy = do_nothing
            return True
        with patch.object(self.tree, 'PopupMenu', PopupMenu):
            await self.right_click()
            assert captured_menu is not None
            assert destroy_captured_menu is not None
            try:
                yield captured_menu
            finally:
                destroy_captured_menu()
    
    async def right_click(self) -> None:
        wx.PostEvent(self.tree, wx.TreeEvent(wx.EVT_TREE_ITEM_RIGHT_CLICK.typeId, self.tree, self.id))
        await pump_wx_events()
    
    # === Comparison ===
    
    def __eq__(self, other: object) -> bool:
        if is_windows():
            # wx.TreeItemId does not support equality comparison on Windows
            raise ValueError('Cannot compare TreeItems on Windows')
        else:
            return (
                isinstance(other, TreeItem) and
                self.tree == other.tree and
                self.id == other.id
            )


# ------------------------------------------------------------------------------
