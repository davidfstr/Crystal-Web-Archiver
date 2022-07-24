from __future__ import annotations

from contextlib import contextmanager
from crystal.util.xos import project_appears_as_package_file
from typing import Iterator, List, Optional
import unittest.mock
import wx


# ------------------------------------------------------------------------------
# Utility: Controls: wx.Button

def click_button(button: wx.Button) -> None:
    event = wx.PyCommandEvent(wx.EVT_BUTTON.typeId, button.GetId())
    event.SetEventObject(button)
    assert event.GetEventObject().GetId() == button.GetId()
    
    button.Command(event)


# ------------------------------------------------------------------------------
# Utility: Controls: wx.FileDialog, wx.DirDialog

@contextmanager
def package_dialog_returning(filepath: str) -> Iterator[None]:
    if project_appears_as_package_file():
        with file_dialog_returning(filepath):
            yield
    else:
        with dir_dialog_returning(filepath):
            yield


@contextmanager
def file_dialog_returning(filepath: str) -> Iterator[None]:
    with unittest.mock.patch('wx.FileDialog', spec=True) as MockFileDialog:
        instance = MockFileDialog.return_value
        instance.ShowModal.return_value = wx.ID_OK
        instance.GetPath.return_value = filepath
        
        yield


@contextmanager
def dir_dialog_returning(filepath: str) -> Iterator[None]:
    with unittest.mock.patch('wx.DirDialog', spec=True) as MockDirDialog:
        instance = MockDirDialog.return_value
        instance.ShowModal.return_value = wx.ID_OK
        instance.GetPath.return_value = filepath
        
        yield


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
        self.tree = tree
        self.id = id
    
    @property
    def Text(self) -> str:
        return self.tree.GetItemText(self.id)
    
    def SelectItem(self) -> None:
        self.tree.SelectItem(self.id)
    
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
    
    @staticmethod
    def GetRootItem(tree: wx.TreeCtrl) -> Optional[TreeItem]:
        root_tii = tree.GetRootItem()
        if root_tii.IsOk():
            return TreeItem(tree, root_tii)
        else:
            return None
    
    def GetFirstChild(self) -> Optional[TreeItem]:
        first_child_tii = self.tree.GetFirstChild(self.id)[0]
        if first_child_tii.IsOk():
            return TreeItem(self.tree, first_child_tii)
        else:
            return None
    
    @property
    def Children(self) -> List[TreeItem]:
        return get_children_of_tree_item(self.tree, self.id)
    
    def __eq__(self, other: object) -> bool:
        # wx.TreeItemId does not support equality comparison on Windows
        return NotImplemented


# ------------------------------------------------------------------------------
