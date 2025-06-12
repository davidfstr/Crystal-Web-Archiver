from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from crystal.tests.util.runner import pump_wx_events
from crystal.util.wx_treeitem_gettooltip import GetTooltipEvent
from crystal.util.xos import is_windows
from typing import List, Literal, Optional
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
    
    # Toggle value
    checkbox.Value = not checkbox.Value
    
    # Dispatch wx.EVT_CHECKBOX event
    event = wx.PyCommandEvent(wx.EVT_CHECKBOX.typeId, checkbox.GetId())
    event.SetEventObject(checkbox)
    assert event.GetEventObject().GetId() == checkbox.GetId()
    checkbox.ProcessEvent(event)
    
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

def select_menuitem_now(menu: wx.Menu, menuitem_id: int) -> None:
    # Process the related wx.EVT_MENU event immediately,
    # so that the event handler is called before the wx.Menu is disposed
    event = wx.MenuEvent(type=wx.EVT_MENU.typeId, id=menuitem_id, menu=None)
    menu.ProcessEvent(event)


# ------------------------------------------------------------------------------
# Utility: Controls: wx.TreeCtrl

def get_children_of_tree_item(tree: wx.TreeCtrl, tii: wx.TreeItemId) -> list[TreeItem]:
    children = []  # type: List[TreeItem]
    next_child_tii = tree.GetFirstChild(tii)[0]
    while next_child_tii.IsOk():
        children.append(TreeItem(tree, next_child_tii))
        next_child_tii = tree.GetNextSibling(next_child_tii)  # reinterpret
    return children


class TreeItem:
    __slots__ = ['tree', 'id']
    
    _USE_FAST_ID_COMPARISONS = True
    
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
    
    def Tooltip(self, tooltip_type: Literal['icon', 'label', None]=None) -> str | None:
        event = GetTooltipEvent(tree_item_id=self.id, tooltip_cell=[Ellipsis], tooltip_type=tooltip_type)
        self.tree.ProcessEvent(event)  # callee should set: event.tooltip_cell[0]
        assert event.tooltip_cell[0] is not Ellipsis
        return event.tooltip_cell[0]
    
    def SelectItem(self) -> None:
        self.tree.SelectItem(self.id)
    
    def IsSelected(self) -> bool:
        return self.tree.IsSelected(self.id)
    
    @staticmethod
    def GetSelection(tree: wx.TreeCtrl) -> TreeItem | None:
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
    
    def GetFirstChild(self) -> TreeItem | None:
        first_child_tii = self.tree.GetFirstChild(self.id)[0]
        if first_child_tii.IsOk():
            return TreeItem(self.tree, first_child_tii)
        else:
            return None
    
    @property
    def Children(self) -> list[TreeItem]:
        return get_children_of_tree_item(self.tree, self.id)
    
    @property
    def _ItemData(self) -> object:
        return self.tree.GetItemData(self.id)
    
    # === Entity Tree: Find Child ===
    
    def find_child(
            parent_ti: TreeItem,
            url_or_url_pattern: str,
            default_url_prefix: str | None=None
            ) -> TreeItem:
        """
        Returns the first child of the specified parent tree item with the
        specified URL or URL pattern.
        
        Raises TreeItem.ChildNotFound if such a child is not found.
        """
        if default_url_prefix is not None:
            if url_or_url_pattern.startswith(default_url_prefix):
                url_or_url_pattern = url_or_url_pattern[len(default_url_prefix):]  # reinterpret
        try:
            (matching_child_ti,) = (
                child for child in parent_ti.Children
                if child.Text.startswith(f'{url_or_url_pattern} - ')
            )
        except ValueError:
            try:
                (matching_child_ti,) = (
                    child for child in parent_ti.Children
                    if child.Text == url_or_url_pattern
                )
            except ValueError:
                raise TreeItem.ChildNotFound(
                    f'Child {url_or_url_pattern} not found in specified TreeItem'
                ) from None
        return matching_child_ti
    
    def try_find_child(parent_ti: TreeItem, *args, **kwargs) -> TreeItem | None:
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
            (matching_child_ti,) = (
                child for child in parent_ti.Children
                if title_fragment in child.Text
            )
            return matching_child_ti
        except ValueError:
            raise TreeItem.ChildNotFound(
                f'Child with title fragment {title_fragment!r} not found in specified TreeItem'
            ) from None
    
    class ChildNotFound(AssertionError):
        pass
    
    # === Operations ===
    
    async def right_click_showing_popup_menu(self, show_popup_menu: Callable[[wx.Menu], None]) -> None:
        raised_exc = None  # type: Optional[Exception]
        def PopupMenu(menu: wx.Menu, *args, **kwargs) -> bool:
            nonlocal raised_exc
            PopupMenu.called = True  # type: ignore[attr-defined]
            try:
                show_popup_menu(menu)
            except Exception as e:
                raised_exc = e
            return True
        PopupMenu.called = False  # type: ignore[attr-defined]
        with patch.object(self.tree, 'PopupMenu', PopupMenu):
            await self.right_click()
        assert PopupMenu.called  # type: ignore[attr-defined]
        if raised_exc is not None:
            raise raised_exc
    
    async def right_click(self) -> None:
        # TODO: Consider calling ProcessEvent directly rather than relying
        #       on pump_wx_events(), which has been observed to be unreliable
        #       on Windows in the past for posting individual events
        wx.PostEvent(self.tree, wx.TreeEvent(wx.EVT_TREE_ITEM_RIGHT_CLICK.typeId, self.tree, self.id))
        await pump_wx_events()
    
    # === Comparison ===
    
    def __eq__(self, other: object) -> bool:
        if not isinstance(other, TreeItem):
            return False
        if not (self.tree == other.tree):
            return False
        if TreeItem._USE_FAST_ID_COMPARISONS and not is_windows():
            # NOTE: wx.TreeItemId does not support equality comparison on Windows
            return self.id == other.id
        else:
            id_data = self._ItemData
            other_id_data = other._ItemData
            if id_data is None or other_id_data is None:
                raise TreeItemsIncomparableError('Cannot compare TreeItems lacking item data')
            return id_data is other_id_data


class TreeItemsIncomparableError(ValueError):
    pass


# ------------------------------------------------------------------------------
