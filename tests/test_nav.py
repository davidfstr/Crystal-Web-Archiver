"""
Unit tests for crystal.ui.nav module.
"""

from crystal.ui.nav import (
    _DEFAULT_DELETION_STYLE, T, TopWindowNavigatorHasNoWindow, 
    WindowNavigator, inline_diff, Snapshot, SnapshotDiff, NoSuchWindow,
    NotATreeCtrl, TreeItemNavigator,
    MenuBarNavigator, MenuNavigator, MenuItemNavigator,
    NoMenuBar,
)
from crystal.util.xos import is_mac_os, is_windows
from crystal.util.controls import TreeItem
import pytest
import re
from unittest import skip, skipIf, skipUnless
from unittest.mock import Mock, patch
import wx


# === Tests for Navigator ===

class TestNavigator:
    # === Non-Property Tests ===
    
    def test_access_of_children_attribute_provides_helpful_error_message(self) -> None:
        nav = WindowNavigator(path='T[1][2][3]')
        with pytest.raises(AttributeError, match=re.escape(
                "'WindowNavigator' has no attribute 'Children'. "
                "Did you mean T[1][2][3].W.Children?")):
            nav.Children
    
    def test_access_of_parent_attribute_provides_helpful_error_message(self) -> None:
        nav = WindowNavigator(path='T[1][2][3]')
        with pytest.raises(AttributeError, match=re.escape(
                "'WindowNavigator' has no attribute 'Parent'. "
                "Did you mean T[1][2][3].W.Parent?")):
            nav.Parent
    
    def test_children_and_parent_attributes_do_not_appear_in_dir(self) -> None:
        nav = WindowNavigator(path='T[1][2][3]')
        dir_nav = dir(nav)
        assert 'Children' not in dir_nav
        assert 'Parent' not in dir_nav


class TestWindowNavigator:
    # === Formatting Tests: Describe ===
    
    # (TODO: Implement tests)
    
    # === Navigation Tests ===
    
    def test_call_of_unique_named_window_returns_window(self) -> None:
        # Arrange: Create mock windows
        if True:
            parent_window = Mock(spec=wx.Window)
            parent_window.Name = 'parent'
            parent_window.Shown = True
            parent_window.IsTopLevel.return_value = False
            
            target_window = Mock(spec=wx.Window)
            target_window.Name = 'target'
            target_window.Shown = True
            target_window.IsTopLevel.return_value = False
            
            parent_window.Children = [target_window]
            target_window.Children = []
        
        navigator = WindowNavigator(parent_window)
        
        with patch('wx.Window.FindWindowByName') as mock_find:
            mock_find.return_value = target_window
            
            # Act
            result = navigator(Name='target')
        
        # Assert
        assert isinstance(result, WindowNavigator)
        assert result.Window is target_window
        mock_find.assert_called_once_with('target', parent=target_window)
    
    def test_call_of_nonunique_named_window_returns_first_window(self) -> None:
        # Arrange: Create mock windows
        if True:
            parent_window = Mock(spec=wx.Window)
            parent_window.Name = 'parent'
            parent_window.Shown = True
            parent_window.IsTopLevel.return_value = False
            
            first_target = Mock(spec=wx.Window)
            first_target.Name = 'duplicate'
            first_target.Shown = True
            first_target.IsTopLevel.return_value = False
            
            second_target = Mock(spec=wx.Window)
            second_target.Name = 'duplicate'
            second_target.Shown = True
            second_target.IsTopLevel.return_value = False
            
            parent_window.Children = [first_target, second_target]
            first_target.Children = []
            second_target.Children = []
        
        navigator = WindowNavigator(parent_window)
        
        with patch('wx.Window.FindWindowByName') as mock_find:
            mock_find.return_value = first_target
            
            # Act
            result = navigator(Name='duplicate')
        
        # Assert
        assert isinstance(result, WindowNavigator)
        assert result.Window is first_target
        mock_find.assert_called_once_with('duplicate', parent=first_target)
    
    def test_call_of_missing_named_window_raises_no_such_window(self) -> None:
        # Arrange: Create mock windows
        if True:
            parent_window = Mock(spec=wx.Window)
            parent_window.Name = 'parent'
            parent_window.Shown = True
            parent_window.IsTopLevel.return_value = False
            
            child_window = Mock(spec=wx.Window)
            child_window.Name = 'child'
            child_window.Shown = True
            child_window.IsTopLevel.return_value = False
            
            parent_window.Children = [child_window]
            child_window.Children = []
        
        navigator = WindowNavigator(parent_window)
        
        with patch('wx.Window.FindWindowByName') as mock_find:
            mock_find.return_value = None
            
            # Act & Assert
            with pytest.raises(NoSuchWindow, match='does not exist'):
                navigator(Name='nonexistent')
    
    def test_call_of_unique_id_window_returns_window(self) -> None:
        # Arrange: Create mock windows
        if True:
            parent_window = Mock(spec=wx.Window)
            parent_window.Name = 'parent'
            parent_window.Shown = True
            parent_window.IsTopLevel.return_value = False
            
            target_window = Mock(spec=wx.Window)
            target_window.Name = 'target'
            target_window.Id = wx.ID_OK
            target_window.Shown = True
            target_window.IsTopLevel.return_value = False
            
            parent_window.Children = [target_window]
            target_window.Children = []
        
        navigator = WindowNavigator(parent_window)
        
        with patch('wx.Window.FindWindowById') as mock_find:
            mock_find.return_value = target_window
            
            # Act
            result = navigator(Id=wx.ID_OK)
        
        # Assert
        assert isinstance(result, WindowNavigator)
        assert result.Window is target_window
        mock_find.assert_called_once_with(wx.ID_OK, parent=target_window)
    
    def test_call_of_nonunique_id_window_returns_first_window(self) -> None:
        # Arrange: Create mock windows
        if True:
            parent_window = Mock(spec=wx.Window)
            parent_window.Name = 'parent'
            parent_window.Shown = True
            parent_window.IsTopLevel.return_value = False
            
            first_target = Mock(spec=wx.Window)
            first_target.Name = 'first'
            first_target.Id = wx.ID_CANCEL
            first_target.Shown = True
            first_target.IsTopLevel.return_value = False
            
            second_target = Mock(spec=wx.Window)
            second_target.Name = 'second'
            second_target.Id = wx.ID_CANCEL
            second_target.Shown = True
            second_target.IsTopLevel.return_value = False
            
            parent_window.Children = [first_target, second_target]
            first_target.Children = []
            second_target.Children = []
        
        navigator = WindowNavigator(parent_window)
        
        with patch('wx.Window.FindWindowById') as mock_find:
            mock_find.return_value = first_target
            
            # Act
            result = navigator(Id=wx.ID_CANCEL)
        
        # Assert
        assert isinstance(result, WindowNavigator)
        assert result.Window is first_target
        mock_find.assert_called_once_with(wx.ID_CANCEL, parent=first_target)
    
    def test_call_of_missing_id_window_raises_no_such_window(self) -> None:
        # Arrange: Create mock windows
        if True:
            parent_window = Mock(spec=wx.Window)
            parent_window.Name = 'parent'
            parent_window.Shown = True
            parent_window.IsTopLevel.return_value = False
            
            child_window = Mock(spec=wx.Window)
            child_window.Name = 'child'
            child_window.Id = wx.ID_OK
            child_window.Shown = True
            child_window.IsTopLevel.return_value = False
            
            parent_window.Children = [child_window]
            child_window.Children = []
        
        navigator = WindowNavigator(parent_window)
        
        with patch('wx.Window.FindWindowById') as mock_find:
            mock_find.return_value = None
            
            # Act & Assert
            with pytest.raises(NoSuchWindow, match='does not exist'):
                navigator(Id=wx.ID_HELP)
    
    def test_call_of_unique_labeled_window_returns_window(self) -> None:
        # Arrange: Create mock windows
        if True:
            parent_window = Mock(spec=wx.Window)
            parent_window.Name = 'parent'
            parent_window.Label = ''
            parent_window.Shown = True
            parent_window.IsTopLevel.return_value = False
            
            target_window = Mock(spec=wx.Window)
            target_window.Name = 'target'
            target_window.Label = 'Target Button'
            target_window.Shown = True
            target_window.IsTopLevel.return_value = False
            
            parent_window.Children = [target_window]
            target_window.Children = []
        
        navigator = WindowNavigator(parent_window)
        
        with patch('wx.Window.FindWindowByLabel') as mock_find:
            mock_find.return_value = target_window
            
            # Act
            result = navigator(Label='Target Button')
        
        # Assert
        assert isinstance(result, WindowNavigator)
        assert result.Window is target_window
        mock_find.assert_called_once_with('Target Button', parent=target_window)
    
    def test_call_of_nonunique_labeled_window_returns_first_window(self) -> None:
        # Arrange: Create mock windows
        if True:
            parent_window = Mock(spec=wx.Window)
            parent_window.Name = 'parent'
            parent_window.Label = ''
            parent_window.Shown = True
            parent_window.IsTopLevel.return_value = False
            
            first_target = Mock(spec=wx.Window)
            first_target.Name = 'first'
            first_target.Label = 'OK'
            first_target.Shown = True
            first_target.IsTopLevel.return_value = False
            
            second_target = Mock(spec=wx.Window)
            second_target.Name = 'second'
            second_target.Label = 'OK'
            second_target.Shown = True
            second_target.IsTopLevel.return_value = False
            
            parent_window.Children = [first_target, second_target]
            first_target.Children = []
            second_target.Children = []
        
        navigator = WindowNavigator(parent_window)
        
        with patch('wx.Window.FindWindowByLabel') as mock_find:
            mock_find.return_value = first_target
            
            # Act
            result = navigator(Label='OK')
        
        # Assert
        assert isinstance(result, WindowNavigator)
        assert result.Window is first_target
        mock_find.assert_called_once_with('OK', parent=first_target)
    
    def test_call_of_missing_labeled_window_raises_no_such_window(self) -> None:
        # Arrange: Create mock windows
        if True:
            parent_window = Mock(spec=wx.Window)
            parent_window.Name = 'parent'
            parent_window.Label = ''
            parent_window.Shown = True
            parent_window.IsTopLevel.return_value = False
            
            child_window = Mock(spec=wx.Window)
            child_window.Name = 'child'
            child_window.Label = 'Cancel'
            child_window.Shown = True
            child_window.IsTopLevel.return_value = False
            
            parent_window.Children = [child_window]
            child_window.Children = []
        
        navigator = WindowNavigator(parent_window)
        
        with patch('wx.Window.FindWindowByLabel') as mock_find:
            mock_find.return_value = None
            
            # Act & Assert
            with pytest.raises(NoSuchWindow, match='does not exist'):
                navigator(Label='Nonexistent Label')
    
    def test_getitem_of_index_returns_window(self) -> None:
        # Arrange: Create mock windows with parent-child relationship
        if True:
            parent_window = Mock(spec=wx.Window)
            parent_window.Name = 'parent'
            parent_window.Shown = True
            parent_window.IsTopLevel.return_value = False
            
            first_child = Mock(spec=wx.Window)
            first_child.Name = 'first'
            first_child.Shown = True
            first_child.IsTopLevel.return_value = False
            
            second_child = Mock(spec=wx.Window)
            second_child.Name = 'second'
            second_child.Shown = True
            second_child.IsTopLevel.return_value = False
            
            parent_window.Children = [first_child, second_child]
            first_child.Children = []
            second_child.Children = []
        
        navigator = WindowNavigator(parent_window)
        
        # Act
        result0 = navigator[0]
        result1 = navigator[1]
        
        # Assert
        assert isinstance(result0, WindowNavigator)
        assert result0.Window is first_child
        assert isinstance(result1, WindowNavigator)
        assert result1.Window is second_child
    
    def test_getitem_of_unique_named_window_returns_window(self) -> None:
        # Arrange: Create mock windows
        if True:
            parent_window = Mock(spec=wx.Window)
            parent_window.Name = 'parent'
            parent_window.Shown = True
            parent_window.IsTopLevel.return_value = False
            
            target_window = Mock(spec=wx.Window)
            target_window.Name = 'target'
            target_window.Shown = True
            target_window.IsTopLevel.return_value = False
            
            parent_window.Children = [target_window]
            target_window.Children = []
        
        navigator = WindowNavigator(parent_window)
        
        with patch('wx.Window.FindWindowByName') as mock_find:
            mock_find.return_value = target_window
            
            # Act
            result = navigator['target']
        
        # Assert
        assert isinstance(result, WindowNavigator)
        assert result.Window is target_window
        mock_find.assert_called_once_with('target', parent=target_window)
    
    def test_getitem_of_nonunique_named_window_returns_first_window(self) -> None:
        # Arrange: Create mock windows
        if True:
            parent_window = Mock(spec=wx.Window)
            parent_window.Name = 'parent'
            parent_window.Shown = True
            parent_window.IsTopLevel.return_value = False
            
            first_target = Mock(spec=wx.Window)
            first_target.Name = 'duplicate'
            first_target.Shown = True
            first_target.IsTopLevel.return_value = False
            
            second_target = Mock(spec=wx.Window)
            second_target.Name = 'duplicate'
            second_target.Shown = True
            second_target.IsTopLevel.return_value = False
            
            parent_window.Children = [first_target, second_target]
            first_target.Children = []
            second_target.Children = []
        
        navigator = WindowNavigator(parent_window)
        
        with patch('wx.Window.FindWindowByName') as mock_find:
            mock_find.return_value = first_target
            
            # Act
            result = navigator['duplicate']
        
        # Assert
        assert isinstance(result, WindowNavigator)
        assert result.Window is first_target
        mock_find.assert_called_once_with('duplicate', parent=first_target)
    
    def test_getitem_of_missing_named_window_raises_no_such_window(self) -> None:
        # Arrange: Create mock windows
        if True:
            parent_window = Mock(spec=wx.Window)
            parent_window.Name = 'parent'
            parent_window.Shown = True
            parent_window.IsTopLevel.return_value = False
            
            child_window = Mock(spec=wx.Window)
            child_window.Name = 'child'
            child_window.Shown = True
            child_window.IsTopLevel.return_value = False
            
            parent_window.Children = [child_window]
            child_window.Children = []
        
        navigator = WindowNavigator(parent_window)
        
        with patch('wx.Window.FindWindowByName') as mock_find:
            mock_find.return_value = None
            
            # Act & Assert
            with pytest.raises(NoSuchWindow, match='does not exist'):
                navigator['nonexistent']
    
    def test_menubar_of_non_frame_raises_nomenubar(self) -> None:
        # Arrange: Create a non-Frame mock window
        if True:
            window = Mock(spec=wx.Window)
            window.Name = 'window'
            window.Shown = True
            window.IsTopLevel.return_value = False
            
            window.Children = []
        
        navigator = WindowNavigator(window)
        
        # Act & Assert
        with pytest.raises(NoMenuBar):
            navigator.MenuBar
    
    def test_menubar_of_frame_without_menubar_raises_nomenubar(self) -> None:
        # Arrange: Create a Frame mock without a menubar
        if True:
            frame = Mock(spec=wx.Frame)
            frame.Name = 'frame'
            frame.Shown = True
            frame.IsTopLevel.return_value = True
            frame.MenuBar = None
            
            frame.Children = []
        
        navigator = WindowNavigator(frame)
        
        # Act & Assert
        with pytest.raises(NoMenuBar):
            navigator.MenuBar
    
    def test_menubar_of_frame_with_menubar_returns_menubar(self) -> None:
        # Arrange: Create a Frame mock with a menubar
        if True:
            frame = Mock(spec=wx.Frame)
            frame.Name = 'frame'
            frame.Shown = True
            frame.IsTopLevel.return_value = True
            
            menubar = Mock(spec=wx.MenuBar)
            frame.MenuBar = menubar
            
            frame.Children = []
        
        navigator = WindowNavigator(frame)
        
        # Act
        result = navigator.MenuBar
        
        # Assert
        assert isinstance(result, MenuBarNavigator)
        assert result.MenuBar is menubar
    
    def test_tree_of_non_treectrl_raises_notatreectrl(self) -> None:
        # Arrange: Create a non-TreeCtrl mock window
        if True:
            parent_window = Mock(spec=wx.Window)
            parent_window.Name = 'parent'
            parent_window.Shown = True
            parent_window.IsTopLevel.return_value = False
            
            parent_window.Children = []
        
        navigator = WindowNavigator(parent_window)
        
        # Act & Assert
        with pytest.raises(NotATreeCtrl):
            navigator.Tree
    
    def test_tree_of_treectrl_returns_tree_item_navigator(self) -> None:
        # Arrange: Create a TreeCtrl mock window with a root item
        if True:
            tree_window = Mock(spec=wx.TreeCtrl)
            tree_window.Name = 'tree'
            tree_window.Shown = True
            tree_window.IsTopLevel.return_value = False
            
            root_item_id = Mock(spec=wx.TreeItemId)
            root_item_id.IsOk.return_value = True
            tree_window.GetRootItem.return_value = root_item_id
            
            tree_window.Children = []
        
        navigator = WindowNavigator(tree_window)
        
        # Act
        result = navigator.Tree
        
        # Assert
        assert isinstance(result, TreeItemNavigator)
    
    # === Children Tests ===
    
    # (TODO: Add tests for handling of invisible children, top-level children, etc)
    
    # === Children Tests: macOS Common Menubar ===
    
    @skipUnless(is_mac_os(), 'only runs on macOS')
    def test_macos_invisible_frame_with_menubar_shown_when_no_visible_frames(self) -> None:
        # Arrange: Create invisible frame with menubar and a dialog (non-frame)
        if True:
            invisible_frame = Mock(spec=wx.Frame)
            invisible_frame.Name = 'cr-menubar-frame'
            invisible_frame.Shown = False
            invisible_frame.IsTopLevel.return_value = True
            invisible_frame.MenuBar = Mock(spec=wx.MenuBar)
            invisible_frame.Children = []
            
            dialog = Mock(spec=wx.Dialog)
            dialog.Name = 'dialog'
            dialog.Shown = True
            dialog.IsTopLevel.return_value = True
            dialog.IsModal.return_value = False
            dialog.Children = []
        
        navigator = WindowNavigator(None)
        
        with patch('wx.GetTopLevelWindows') as mock_get_tlws:
            mock_get_tlws.return_value = [invisible_frame, dialog]
            
            # Act
            children = navigator._children_of(None)
            
            # Assert: Invisible frame with menubar should be included
            assert invisible_frame in children
            assert dialog in children
            # Invisible frame should come first
            assert children.index(invisible_frame) < children.index(dialog)
    
    @skipUnless(is_mac_os(), 'only runs on macOS')
    def test_macos_invisible_frame_with_menubar_hidden_when_visible_frame_exists(self) -> None:
        # Arrange: Create invisible frame with menubar and visible frame
        if True:
            invisible_frame = Mock(spec=wx.Frame)
            invisible_frame.Name = 'cr-menubar-frame'
            invisible_frame.Shown = False
            invisible_frame.IsTopLevel.return_value = True
            invisible_frame.MenuBar = Mock(spec=wx.MenuBar)
            invisible_frame.Children = []
            
            visible_frame = Mock(spec=wx.Frame)
            visible_frame.Name = 'cr-main-window'
            visible_frame.Shown = True
            visible_frame.IsTopLevel.return_value = True
            visible_frame.MenuBar = Mock(spec=wx.MenuBar)
            visible_frame.Children = []
        
        navigator = WindowNavigator(None)
        
        with patch('wx.GetTopLevelWindows') as mock_get_tlws:
            mock_get_tlws.return_value = [invisible_frame, visible_frame]
            
            # Act
            children = navigator._children_of(None)
            
            # Assert: Invisible frame should NOT be included
            assert invisible_frame not in children
            assert visible_frame in children
    
    @skipUnless(is_mac_os(), 'only runs on macOS')
    def test_macos_invisible_frame_without_menubar_never_shown(self) -> None:
        # Arrange: Create invisible frame WITHOUT menubar
        if True:
            invisible_frame = Mock(spec=wx.Frame)
            invisible_frame.Name = 'invisible-frame'
            invisible_frame.Shown = False
            invisible_frame.IsTopLevel.return_value = True
            invisible_frame.MenuBar = None  # No menubar
            invisible_frame.Children = []
            
            dialog = Mock(spec=wx.Dialog)
            dialog.Name = 'dialog'
            dialog.Shown = True
            dialog.IsTopLevel.return_value = True
            dialog.IsModal.return_value = False
            dialog.Children = []
        
        navigator = WindowNavigator(None)
        
        with patch('wx.GetTopLevelWindows') as mock_get_tlws:
            mock_get_tlws.return_value = [invisible_frame, dialog]
            
            # Act
            children = navigator._children_of(None)
            
            # Assert: Invisible frame without menubar should NOT be included
            assert invisible_frame not in children
            assert dialog in children
    
    @skipIf(is_mac_os(), 'only runs on non-macOS platforms')
    def test_non_macos_invisible_frame_with_menubar_never_shown(self) -> None:
        # Arrange: Create invisible frame with menubar
        if True:
            invisible_frame = Mock(spec=wx.Frame)
            invisible_frame.Name = 'cr-menubar-frame'
            invisible_frame.Shown = False
            invisible_frame.IsTopLevel.return_value = True
            invisible_frame.MenuBar = Mock(spec=wx.MenuBar)
            invisible_frame.Children = []
            
            dialog = Mock(spec=wx.Dialog)
            dialog.Name = 'dialog'
            dialog.Shown = True
            dialog.IsTopLevel.return_value = True
            dialog.IsModal.return_value = False
            dialog.Children = []
        
        navigator = WindowNavigator(None)
        
        with patch('wx.GetTopLevelWindows') as mock_get_tlws:
            mock_get_tlws.return_value = [invisible_frame, dialog]
            
            # Act
            children = navigator._children_of(None)
            
            # Assert: On non-macOS, invisible frame should NOT be included
            assert invisible_frame not in children
            assert dialog in children
    
    # === Properties Tests ===
    
    def test_window_raises_if_navigator_is_top(self) -> None:
        with pytest.raises(TopWindowNavigatorHasNoWindow):
            T.Window
    
    @skip('covered by: test_*_of_*_returns_window')
    def test_window_is_correct_if_navigator_is_not_top(self) -> None:
        pass
    
    def test_query_returns_value_based_on_how_subnavigator_was_found(self) -> None:
        # Arrange: Create mock windows
        if True:
            parent_window = Mock(spec=wx.Window)
            parent_window.Name = 'parent'
            parent_window.Shown = True
            parent_window.IsTopLevel.return_value = True
            
            target_window = Mock(spec=wx.Window)
            target_window.Name = 'target'
            target_window.Id = wx.ID_OK
            target_window.Label = 'Target'
            target_window.Shown = True
            target_window.IsTopLevel.return_value = False
            
            parent_window.Children = [target_window]
            target_window.Children = []
        
        navigator = WindowNavigator(parent_window)
        
        with patch('wx.Window.FindWindowByName') as mock_find1, \
                patch('wx.Window.FindWindowById') as mock_find2, \
                patch('wx.Window.FindWindowByLabel') as mock_find3:
            mock_find1.return_value = target_window
            mock_find2.return_value = target_window
            mock_find3.return_value = target_window
            
            # Act & Assert
            result = navigator(Name='target').Query == "wx.Window.FindWindowByName('target')"
            result = navigator(Id=wx.ID_OK).Query == 'wx.Window.FindWindowById(wx.ID_OK)'
            result = navigator(Label='cr-target').Query == "wx.Window.FindWindowByLabel('cr-target')"
            result = navigator['target'].Query == "wx.Window.FindWindowByName('target')"
            result = navigator[0].Query == 'wx.GetTopLevelWindows()[0]'


class TestMenuBarNavigator:
    # === Formatting Tests: Describe ===
    
    def test_describe_menubar(self) -> None:
        # Arrange
        menubar = Mock(spec=wx.MenuBar)
        
        # Act & Assert
        assert MenuBarNavigator._describe(menubar) == 'wx.MenuBar()'
    
    # === Navigation Tests ===
    
    def test_call_with_title_returns_menu(self) -> None:
        # Arrange: Create mock menubar with menus
        if True:
            menubar = Mock(spec=wx.MenuBar)
            
            file_menu = Mock(spec=wx.Menu)
            file_menu.Title = 'File'
            edit_menu = Mock(spec=wx.Menu)
            edit_menu.Title = 'Edit'
            
            menubar.GetMenuCount.return_value = 2
            menubar.GetMenu.side_effect = lambda i: [file_menu, edit_menu][i]
        
        navigator = MenuBarNavigator(menubar, 'T[0].MenuBar', 'wx.FindWindowByName("cr-main-window").MenuBar')
        
        # Act
        result = navigator(Title='Edit')
        
        # Assert
        assert isinstance(result, MenuNavigator)
        assert result.Menu is edit_menu
    
    def test_getitem_of_index_returns_menu(self) -> None:
        # Arrange: Create mock menubar with menus
        if True:
            menubar = Mock(spec=wx.MenuBar)
            
            file_menu = Mock(spec=wx.Menu)
            file_menu.Title = 'File'
            edit_menu = Mock(spec=wx.Menu)
            edit_menu.Title = 'Edit'
            
            menubar.GetMenuCount.return_value = 2
            menubar.GetMenu.side_effect = lambda i: [file_menu, edit_menu][i]
        
        navigator = MenuBarNavigator(menubar, 'T[0].MenuBar', 'wx.GetTopLevelWindows()[0]')
        
        # Act
        result0 = navigator[0]
        result1 = navigator[1]
        
        # Assert
        assert isinstance(result0, MenuNavigator)
        assert result0.Menu is file_menu
        assert isinstance(result1, MenuNavigator)
        assert result1.Menu is edit_menu
    
    def test_getitem_of_title_returns_first_matching_menu(self) -> None:
        # Arrange: Create mock menubar with duplicate menu titles
        if True:
            menubar = Mock(spec=wx.MenuBar)
            
            file_menu_1 = Mock(spec=wx.Menu)
            file_menu_1.Title = 'File'
            file_menu_2 = Mock(spec=wx.Menu)
            file_menu_2.Title = 'File'
            
            menubar.GetMenuCount.return_value = 2
            menubar.GetMenu.side_effect = lambda i: [file_menu_1, file_menu_2][i]
        
        navigator = MenuBarNavigator(menubar, 'T[0].MenuBar', 'wx.FindWindowByName("cr-main-window").MenuBar')
        
        # Act
        result = navigator['File']
        
        # Assert
        assert isinstance(result, MenuNavigator)
        assert result.Menu is file_menu_1
    
    def test_len_returns_menu_count(self) -> None:
        # Arrange
        menubar = Mock(spec=wx.MenuBar)
        menubar.GetMenuCount.return_value = 3
        
        navigator = MenuBarNavigator(menubar, 'T[0].MenuBar', 'wx.GetTopLevelWindows()[0]')
        
        # Act & Assert
        assert len(navigator) == 3
    
    # === Properties Tests ===
    
    def test_menubar_property_returns_menubar(self) -> None:
        # Arrange
        menubar = Mock(spec=wx.MenuBar)
        navigator = MenuBarNavigator(menubar, 'T[0].MenuBar', 'wx.GetTopLevelWindows()[0]')
        
        # Act & Assert
        assert navigator.MenuBar is menubar
        assert navigator.M is menubar
    
    def test_query_returns_correct_expression(self) -> None:
        # Arrange
        menubar = Mock(spec=wx.MenuBar)
        navigator = MenuBarNavigator(menubar, 'T[0].MenuBar', 'wx.GetTopLevelWindows()[0]')
        
        # Act & Assert
        assert str(navigator.Query) == 'wx.GetTopLevelWindows()[0]'
        assert str(navigator.Q) == 'wx.GetTopLevelWindows()[0]'
    
    

class TestMenuNavigator:
    # === Formatting Tests: Describe ===
    
    def test_describe_menu(self) -> None:
        # Arrange
        menu = Mock(spec=wx.Menu)
        menu.Title = 'File'
        
        # Act & Assert
        assert MenuNavigator._describe(menu) == "wx.Menu(Title='File')"
    
    def test_describe_menu_with_special_title(self) -> None:
        # Arrange
        menu = Mock(spec=wx.Menu)
        menu.Title = 'Help & Support'
        
        # Act & Assert
        assert MenuNavigator._describe(menu) == "wx.Menu(Title='Help & Support')"
    
    # === Navigation Tests ===
    
    def test_call_with_id_returns_menu_item(self) -> None:
        # Arrange: Create mock menu with menu items
        if True:
            menu = Mock(spec=wx.Menu)
            menu.Title = 'File'
            
            new_item = Mock(spec=wx.MenuItem)
            new_item.Kind = wx.ITEM_NORMAL
            new_item.IsEnabled.return_value = True
            new_item.Id = wx.ID_NEW
            new_item.ItemLabelText = 'New Project...'
            new_item.Accel = None
            new_item.IsSubMenu.return_value = False
            new_item.Menu = menu
            new_item.IsChecked.return_value = False
            
            open_item = Mock(spec=wx.MenuItem)
            open_item.Kind = wx.ITEM_NORMAL
            open_item.IsEnabled.return_value = True
            open_item.Id = wx.ID_OPEN
            open_item.ItemLabelText = 'Open Project...'
            open_item.Accel = None
            open_item.IsSubMenu.return_value = False
            open_item.Menu = menu
            open_item.IsChecked.return_value = False
            
            menu.MenuItems = [new_item, open_item]
        
        menubar_query = 'wx.FindWindowByName("cr-main-window").MenuBar'
        navigator = MenuNavigator(menu, 'T[0].MenuBar[0]', menubar_query)
        
        # Act
        result = navigator(Id=wx.ID_OPEN)
        
        # Assert
        assert isinstance(result, MenuItemNavigator)
        assert result.MenuItem is open_item
    
    def test_call_with_item_label_text_returns_menu_item(self) -> None:
        # Arrange: Create mock menu with menu items
        if True:
            menu = Mock(spec=wx.Menu)
            menu.Title = 'File'
            
            new_item = Mock(spec=wx.MenuItem)
            new_item.Kind = wx.ITEM_NORMAL
            new_item.IsEnabled.return_value = True
            new_item.Id = wx.ID_NEW
            new_item.ItemLabelText = 'New Project...'
            new_item.Accel = None
            new_item.IsSubMenu.return_value = False
            new_item.Menu = menu
            new_item.IsChecked.return_value = False
            
            open_item = Mock(spec=wx.MenuItem)
            open_item.Kind = wx.ITEM_NORMAL
            open_item.IsEnabled.return_value = True
            open_item.Id = wx.ID_OPEN
            open_item.ItemLabelText = 'Open Project...'
            open_item.Accel = None
            open_item.IsSubMenu.return_value = False
            open_item.Menu = menu
            open_item.IsChecked.return_value = False
            
            menu.MenuItems = [new_item, open_item]
        
        menubar_query = 'wx.FindWindowByName("cr-main-window").MenuBar'
        navigator = MenuNavigator(menu, 'T[0].MenuBar[0]', menubar_query)
        
        # Act
        result = navigator(ItemLabelText='New Project...')
        
        # Assert
        assert isinstance(result, MenuItemNavigator)
        assert result.MenuItem is new_item
    
    def test_call_with_accel_returns_menu_item(self) -> None:
        # Arrange: Create mock menu with menu items
        if True:
            menu = Mock(spec=wx.Menu)
            menu.Title = 'File'
            
            # Create accelerator for Cmd-N (macOS) / Ctrl-N (others)
            accel_n = Mock(spec=wx.AcceleratorEntry)
            accel_n.Flags = wx.ACCEL_CTRL
            accel_n.KeyCode = ord('N')
            
            # Create accelerator for Cmd-O (macOS) / Ctrl-O (others)
            accel_o = Mock(spec=wx.AcceleratorEntry)
            accel_o.Flags = wx.ACCEL_CTRL
            accel_o.KeyCode = ord('O')
            
            new_item = Mock(spec=wx.MenuItem)
            new_item.Kind = wx.ITEM_NORMAL
            new_item.IsEnabled.return_value = True
            new_item.Id = wx.ID_NEW
            new_item.ItemLabelText = 'New Project...'
            new_item.Accel = accel_n
            new_item.IsSubMenu.return_value = False
            new_item.Menu = menu
            new_item.IsChecked.return_value = False
            
            open_item = Mock(spec=wx.MenuItem)
            open_item.Kind = wx.ITEM_NORMAL
            open_item.IsEnabled.return_value = True
            open_item.Id = wx.ID_OPEN
            open_item.ItemLabelText = 'Open Project...'
            open_item.Accel = accel_o
            open_item.IsSubMenu.return_value = False
            open_item.Menu = menu
            open_item.IsChecked.return_value = False
            
            menu.MenuItems = [new_item, open_item]
        
        menubar_query = 'wx.FindWindowByName("cr-main-window").MenuBar'
        navigator = MenuNavigator(menu, 'T[0].MenuBar[0]', menubar_query)
        
        # Act
        expected_accel = '⌘O' if is_mac_os() else 'Ctrl-O'
        result = navigator(Accel=expected_accel)
        
        # Assert
        assert isinstance(result, MenuItemNavigator)
        assert result.MenuItem is open_item

    def test_getitem_of_index_returns_menu_item(self) -> None:
        # Arrange: Create mock menu with menu items
        if True:
            menu = Mock(spec=wx.Menu)
            menu.Title = 'File'
            
            item1 = Mock(spec=wx.MenuItem)
            item1.Kind = wx.ITEM_NORMAL
            item1.IsEnabled.return_value = True
            item1.Id = wx.ID_NEW
            item1.ItemLabelText = 'New'
            item1.Accel = None
            item1.IsSubMenu.return_value = False
            item1.Menu = menu
            
            item2 = Mock(spec=wx.MenuItem)
            item2.Kind = wx.ITEM_SEPARATOR
            item2.IsSubMenu.return_value = False
            item2.Id = -1  # Auto-assigned ID
            item2.ItemLabelText = ''
            item2.Accel = None
            item2.IsEnabled.return_value = True
            item2.IsChecked.return_value = False
            item2.Menu = menu
            
            menu.MenuItems = [item1, item2]
        
        navigator = MenuNavigator(menu, 'T[0].MenuBar[0]', 'menubar.GetMenu(0)')
        
        # Act
        result0 = navigator[0]
        result1 = navigator[1]
        
        # Assert
        assert isinstance(result0, MenuItemNavigator)
        assert result0.MenuItem is item1
        assert isinstance(result1, MenuItemNavigator)
        assert result1.MenuItem is item2
    
    def test_getitem_of_label_returns_menu_item(self) -> None:
        # Arrange: Create mock menu with menu items
        if True:
            menu = Mock(spec=wx.Menu)
            menu.Title = 'File'
            
            new_item = Mock(spec=wx.MenuItem)
            new_item.Kind = wx.ITEM_NORMAL
            new_item.IsEnabled.return_value = True
            new_item.Id = wx.ID_NEW
            new_item.ItemLabelText = 'New Project...'
            new_item.Accel = None
            new_item.IsSubMenu.return_value = False
            new_item.Menu = menu
            new_item.IsChecked.return_value = False
            
            open_item = Mock(spec=wx.MenuItem)
            open_item.Kind = wx.ITEM_NORMAL
            open_item.IsEnabled.return_value = True
            open_item.Id = wx.ID_OPEN
            open_item.ItemLabelText = 'Open Project...'
            open_item.Accel = None
            open_item.IsSubMenu.return_value = False
            open_item.Menu = menu
            open_item.IsChecked.return_value = False
            
            menu.MenuItems = [new_item, open_item]
        
        menubar_query = 'wx.FindWindowByName("cr-main-window").MenuBar'
        navigator = MenuNavigator(menu, 'T[0].MenuBar[0]', menubar_query)
        
        # Act
        result = navigator['Open Project...']
        
        # Assert
        assert isinstance(result, MenuItemNavigator)
        assert result.MenuItem is open_item
    
    def test_len_returns_menu_item_count(self) -> None:
        # Arrange
        menu = Mock(spec=wx.Menu)
        menu.Title = 'File'
        item1 = Mock(spec=wx.MenuItem)
        item1.Menu = menu
        item2 = Mock(spec=wx.MenuItem)
        item2.Menu = menu
        menu.MenuItems = [item1, item2]
        
        navigator = MenuNavigator(menu, 'T[0].MenuBar[0]', 'menubar.GetMenu(0)')
        
        # Act & Assert
        assert len(navigator) == 2
    
    # === Properties Tests ===
    
    def test_menu_property_returns_menu(self) -> None:
        # Arrange
        menu = Mock(spec=wx.Menu)
        menu.Title = 'File'
        navigator = MenuNavigator(menu, 'T[0].MenuBar[0]', 'wx.FindWindowByName("cr-main-window").MenuBar')
        
        # Act & Assert
        assert navigator.Menu is menu
        assert navigator.M is menu
    
    def test_query_returns_correct_expression(self) -> None:
        # Arrange
        menu = Mock(spec=wx.Menu)
        menu.Title = 'File'
        menubar_query = 'wx.FindWindowByName("cr-main-window").MenuBar'
        navigator = MenuNavigator(menu, 'T[0].MenuBar[0]', menubar_query)
        
        # Act & Assert
        expected_query = f'(mb := {menubar_query}).GetMenu(mb.FindMenu(\'File\'))'
        assert str(navigator.Query) == expected_query
        assert str(navigator.Q) == expected_query


class TestMenuItemNavigator:
    # === Formatting Tests: Describe ===
    
    def test_describe_normal_menu_item(self) -> None:
        # Arrange
        menu = Mock(spec=wx.Menu)
        menu.Title = 'File'
        menu_item = Mock(spec=wx.MenuItem)
        menu_item.Kind = wx.ITEM_NORMAL
        menu_item.IsEnabled.return_value = True
        menu_item.Id = wx.ID_NEW
        menu_item.ItemLabelText = 'New Project...'
        menu_item.Accel = None
        menu_item.IsChecked.return_value = False
        menu_item.IsSubMenu.return_value = False
        menu_item.Menu = menu
        
        # Act
        description = MenuItemNavigator._describe(menu_item)
        
        # Assert
        assert description == "wx.MenuItem(Id=wx.ID_NEW, ItemLabelText='New Project...')"
    
    def test_describe_disabled_menu_item(self) -> None:
        # Arrange
        menu = Mock(spec=wx.Menu)
        menu.Title = 'File'
        menu_item = Mock(spec=wx.MenuItem)
        menu_item.Kind = wx.ITEM_NORMAL
        menu_item.IsEnabled.return_value = False
        menu_item.Id = wx.ID_SAVE
        menu_item.ItemLabelText = 'Save'
        menu_item.Accel = None
        menu_item.IsChecked.return_value = False
        menu_item.IsSubMenu.return_value = False
        menu_item.Menu = menu
        
        # Act
        description = MenuItemNavigator._describe(menu_item)
        
        # Assert
        assert 'Enabled=False' in description
        assert description == "wx.MenuItem(Enabled=False, Id=wx.ID_SAVE, ItemLabelText='Save')"
    
    def test_describe_separator_menu_item(self) -> None:
        # Arrange
        menu = Mock(spec=wx.Menu)
        menu.Title = 'File'
        menu_item = Mock(spec=wx.MenuItem)
        menu_item.Kind = wx.ITEM_SEPARATOR
        menu_item.IsEnabled.return_value = True
        menu_item.Accel = None
        menu_item.IsChecked.return_value = False
        menu_item.IsSubMenu.return_value = False
        menu_item.Menu = menu
        
        # Act
        description = MenuItemNavigator._describe(menu_item)
        
        # Assert
        assert description == 'wx.MenuItem(Kind=wx.ITEM_SEPARATOR)'
    
    def test_describe_check_menu_item_unchecked(self) -> None:
        # Arrange
        menu = Mock(spec=wx.Menu)
        menu.Title = 'View'
        menu_item = Mock(spec=wx.MenuItem)
        menu_item.Kind = wx.ITEM_CHECK
        menu_item.IsEnabled.return_value = True
        menu_item.Id = 100
        menu_item.ItemLabelText = 'Show Toolbar'
        menu_item.Accel = None
        menu_item.IsChecked.return_value = False
        menu_item.IsSubMenu.return_value = False
        menu_item.Menu = menu
        
        # Act
        description = MenuItemNavigator._describe(menu_item)
        
        # Assert
        assert 'Kind=wx.ITEM_CHECK' in description
        assert 'IsChecked' not in description  # Omit when False
        assert description == "wx.MenuItem(Kind=wx.ITEM_CHECK, Id=100, ItemLabelText='Show Toolbar')"
    
    def test_describe_check_menu_item_checked(self) -> None:
        # Arrange
        menu = Mock(spec=wx.Menu)
        menu.Title = 'View'
        menu_item = Mock(spec=wx.MenuItem)
        menu_item.Kind = wx.ITEM_CHECK
        menu_item.IsEnabled.return_value = True
        menu_item.Id = 100
        menu_item.ItemLabelText = 'Show Toolbar'
        menu_item.Accel = None
        menu_item.IsChecked.return_value = True
        menu_item.IsSubMenu.return_value = False
        menu_item.Menu = menu
        
        # Act
        description = MenuItemNavigator._describe(menu_item)
        
        # Assert
        assert 'Kind=wx.ITEM_CHECK' in description
        assert 'IsChecked=True' in description
        assert description == "wx.MenuItem(Kind=wx.ITEM_CHECK, Id=100, ItemLabelText='Show Toolbar', IsChecked=True)"
    
    def test_describe_radio_menu_item_unselected(self) -> None:
        # Arrange
        menu = Mock(spec=wx.Menu)
        menu.Title = 'Format'
        menu_item = Mock(spec=wx.MenuItem)
        menu_item.Kind = wx.ITEM_RADIO
        menu_item.IsEnabled.return_value = True
        menu_item.Id = 201
        menu_item.ItemLabelText = 'as URL - Name'
        menu_item.Accel = None
        menu_item.IsChecked.return_value = False
        menu_item.IsSubMenu.return_value = False
        menu_item.Menu = menu
        
        # Act
        description = MenuItemNavigator._describe(menu_item)
        
        # Assert
        assert 'Kind=wx.ITEM_RADIO' in description
        assert 'IsChecked' not in description  # Omit when False
        assert description == "wx.MenuItem(Kind=wx.ITEM_RADIO, Id=201, ItemLabelText='as URL - Name')"
    
    def test_describe_radio_menu_item_selected(self) -> None:
        # Arrange
        menu = Mock(spec=wx.Menu)
        menu.Title = 'Format'
        menu_item = Mock(spec=wx.MenuItem)
        menu_item.Kind = wx.ITEM_RADIO
        menu_item.IsEnabled.return_value = True
        menu_item.Id = 201
        menu_item.ItemLabelText = 'as URL - Name'
        menu_item.Accel = None
        menu_item.IsChecked.return_value = True
        menu_item.IsSubMenu.return_value = False
        menu_item.Menu = menu
        
        # Act
        description = MenuItemNavigator._describe(menu_item)
        
        # Assert
        assert 'Kind=wx.ITEM_RADIO' in description
        assert 'IsChecked=True' in description
        assert description == "wx.MenuItem(Kind=wx.ITEM_RADIO, Id=201, ItemLabelText='as URL - Name', IsChecked=True)"
    
    def test_describe_menu_item_with_negative_id(self) -> None:
        # Arrange: Auto-assigned IDs are negative and should be omitted
        menu = Mock(spec=wx.Menu)
        menu.Title = 'Entity'
        menu_item = Mock(spec=wx.MenuItem)
        menu_item.Kind = wx.ITEM_NORMAL
        menu_item.IsEnabled.return_value = False
        menu_item.Id = -31953
        menu_item.ItemLabelText = 'View:'
        menu_item.Accel = None
        menu_item.IsChecked.return_value = False
        menu_item.IsSubMenu.return_value = False
        menu_item.Menu = menu
        
        # Act
        description = MenuItemNavigator._describe(menu_item)
        
        # Assert
        assert 'Id=' not in description
        assert 'Enabled=False' in description
        assert "ItemLabelText='View:'" in description
        assert description == "wx.MenuItem(Enabled=False, ItemLabelText='View:')"
    
    def test_describe_menu_item_with_custom_id(self) -> None:
        # Arrange: Custom positive IDs should be shown
        menu = Mock(spec=wx.Menu)
        menu.Title = 'Custom'
        menu_item = Mock(spec=wx.MenuItem)
        menu_item.Kind = wx.ITEM_NORMAL
        menu_item.IsEnabled.return_value = True
        menu_item.Id = 12345
        menu_item.ItemLabelText = 'Custom Action'
        menu_item.Accel = None
        menu_item.IsChecked.return_value = False
        menu_item.IsSubMenu.return_value = False
        menu_item.Menu = menu
        
        # Act
        description = MenuItemNavigator._describe(menu_item)
        
        # Assert
        assert 'Id=12345' in description
        assert description == "wx.MenuItem(Id=12345, ItemLabelText='Custom Action')"
    
    def test_describe_menu_item_with_accelerator(self) -> None:
        # Arrange
        menu = Mock(spec=wx.Menu)
        menu.Title = 'File'
        menu_item = Mock(spec=wx.MenuItem)
        menu_item.Kind = wx.ITEM_NORMAL
        menu_item.IsEnabled.return_value = True
        menu_item.Id = wx.ID_NEW
        menu_item.ItemLabelText = 'New'
        menu_item.IsChecked.return_value = False
        menu_item.IsSubMenu.return_value = False
        menu_item.Menu = menu
        
        accel = Mock(spec=wx.AcceleratorEntry)
        accel.Flags = wx.ACCEL_CTRL
        accel.KeyCode = ord('N')
        menu_item.Accel = accel
        
        # Act
        description = MenuItemNavigator._describe(menu_item)
        
        # Assert
        assert 'Accel=' in description
        if is_mac_os():
            assert description == "wx.MenuItem(Id=wx.ID_NEW, ItemLabelText='New', Accel='⌘N')"
        else:
            assert description == "wx.MenuItem(Id=wx.ID_NEW, ItemLabelText='New', Accel='Ctrl-N')"
    
    # === Formatting Tests: Format Accel ===
    
    def test_format_accel_ctrl_or_command_key(self) -> None:
        # Arrange
        accel = Mock(spec=wx.AcceleratorEntry)
        accel.Flags = wx.ACCEL_CTRL
        accel.KeyCode = ord('S')
        
        # Act & Assert
        if is_mac_os():
            assert MenuItemNavigator._format_accel(accel) == '⌘S'
        else:
            assert MenuItemNavigator._format_accel(accel) == 'Ctrl-S'
    
    def test_format_accel_shift_modifier(self) -> None:
        # Arrange
        accel = Mock(spec=wx.AcceleratorEntry)
        accel.Flags = wx.ACCEL_CTRL | wx.ACCEL_SHIFT
        accel.KeyCode = ord('S')
        
        # Act & Assert
        if is_mac_os():
            assert MenuItemNavigator._format_accel(accel) == '⇧⌘S'
        else:
            assert MenuItemNavigator._format_accel(accel) == 'Ctrl-Shift-S'
    
    def test_format_accel_ctrl_macos(self) -> None:
        # Arrange: RAW_CTRL is the actual Control key on macOS
        accel = Mock(spec=wx.AcceleratorEntry)
        accel.Flags = wx.ACCEL_RAW_CTRL | wx.ACCEL_CTRL
        accel.KeyCode = ord('N')
        
        # Act & Assert
        if is_mac_os():
            assert MenuItemNavigator._format_accel(accel) == '⌃⌘N'
    
    def test_format_accel_alt_modifier(self) -> None:
        # Arrange: ALT is Option on macOS
        accel = Mock(spec=wx.AcceleratorEntry)
        accel.Flags = wx.ACCEL_ALT | wx.ACCEL_CTRL
        accel.KeyCode = ord('A')
        
        # Act & Assert
        if is_mac_os():
            assert MenuItemNavigator._format_accel(accel) == '⌥⌘A'
        else:
            assert MenuItemNavigator._format_accel(accel) == 'Ctrl-Alt-A'
    
    def test_format_accel_all_modifiers(self) -> None:
        # Arrange
        accel_macos = Mock(spec=wx.AcceleratorEntry)
        accel_macos.Flags = wx.ACCEL_RAW_CTRL | wx.ACCEL_ALT | wx.ACCEL_SHIFT | wx.ACCEL_CTRL
        accel_macos.KeyCode = ord('X')
        
        accel_windows = Mock(spec=wx.AcceleratorEntry)
        accel_windows.Flags = wx.ACCEL_CTRL | wx.ACCEL_ALT | wx.ACCEL_SHIFT
        accel_windows.KeyCode = ord('X')
        
        # Act & Assert
        if is_mac_os():
            assert MenuItemNavigator._format_accel(accel_macos) == '⌃⌥⇧⌘X'
        else:
            assert MenuItemNavigator._format_accel(accel_windows) == 'Ctrl-Alt-Shift-X'
    
    def test_format_accel_no_modifiers(self) -> None:
        # Arrange
        accel = Mock(spec=wx.AcceleratorEntry)
        accel.Flags = 0
        accel.KeyCode = wx.WXK_F1
        
        # Act & Assert
        # Result should be the same on both macOS and non-macOS
        assert MenuItemNavigator._format_accel(accel) == f'Key{wx.WXK_F1}'
    
    def test_format_accel_special_key(self) -> None:
        # Arrange: Test a non-printable keycode
        accel = Mock(spec=wx.AcceleratorEntry)
        accel.Flags = wx.ACCEL_CTRL
        accel.KeyCode = wx.WXK_DELETE
        
        # Act & Assert
        if not is_mac_os():
            assert MenuItemNavigator._format_accel(accel) == f'Ctrl-Key{wx.WXK_DELETE}'
    
    # === Navigation Tests ===
    
    def test_getitem_raises_not_implemented_error(self) -> None:
        # Arrange
        menu = Mock(spec=wx.Menu)
        menu.Title = 'File'
        menu_item = Mock(spec=wx.MenuItem)
        menu_item.Id = -1  # separator
        menu_item.Menu = menu
        navigator = MenuItemNavigator(menu_item, 'T[0].MenuBar[0][0]', 'window.MenuBar')
        
        # Act & Assert
        with pytest.raises(NotImplementedError, match='does not yet support navigating to sub-menus'):
            navigator[0]
    
    def test_len_returns_zero(self) -> None:
        # Arrange
        menu = Mock(spec=wx.Menu)
        menu.Title = 'File'
        menu_item = Mock(spec=wx.MenuItem)
        menu_item.Id = -1  # separator
        menu_item.Menu = menu
        navigator = MenuItemNavigator(menu_item, 'T[0].MenuBar[0][0]', 'window.MenuBar')
        
        # Act & Assert
        assert len(navigator) == 0
    
    # === Properties Tests ===
    
    def test_menuitem_property_returns_menuitem(self) -> None:
        # Arrange
        menu = Mock(spec=wx.Menu)
        menu.Title = 'File'
        menu_item = Mock(spec=wx.MenuItem)
        menu_item.Id = -1  # separator
        menu_item.Menu = menu
        navigator = MenuItemNavigator(menu_item, 'T[0].MenuBar[0][0]', 'window.MenuBar')
        
        # Act & Assert
        assert navigator.MenuItem is menu_item
        assert navigator.M is menu_item
    
    @pytest.mark.parametrize('menu_title,item_label,item_id,expected_query_suffix', [
        # Case 1: Menu item without explicit ID (uses FindMenuItem with menu title + label)
        ('Entity', 'View:', -1, "FindMenuItem('Entity', 'View:')"),
        # Case 2: Menu item with explicit positive ID (uses FindItemById)
        ('File', 'New Project...', wx.ID_NEW, f'FindItemById(wx.ID_NEW)'),
    ])
    def test_query_returns_correct_expression(self, menu_title: str, item_label: str, item_id: int, expected_query_suffix: str) -> None:
        # Arrange
        menu = Mock(spec=wx.Menu)
        menu.Title = menu_title
        menu_item = Mock(spec=wx.MenuItem)
        menu_item.Id = item_id
        menu_item.ItemLabelText = item_label
        menu_item.Menu = menu
        navigator = MenuItemNavigator(menu_item, 'T[0].MenuBar[0][0]', 'window.MenuBar')
        
        # Act & Assert
        expected_query = f'window.MenuBar.{expected_query_suffix}'
        assert str(navigator.Query) == expected_query
        assert str(navigator.Q) == expected_query


class TestTreeItemNavigator:
    # === Formatting Tests: Describe ===
    
    # (TODO: Implement tests)
    
    # === Navigation Tests ===
    
    def test_getitem_of_index_returns_tree_item(self) -> None:
        # Arrange: Create mock tree with parent-child relationships
        if True:
            tree_ctrl = Mock(spec=wx.TreeCtrl)
            tree_ctrl.Name = 'tree'
            
            parent_item_id = Mock(spec=wx.TreeItemId)
            parent_item_id.IsOk.return_value = True
            
            first_child_id = Mock(spec=wx.TreeItemId)
            first_child_id.IsOk.return_value = True
            
            second_child_id = Mock(spec=wx.TreeItemId)
            second_child_id.IsOk.return_value = True
            
            # On Windows, TreeItem equality comparison requires _ItemData to be set.
            # Create unique sentinel objects for each item's data.
            if is_windows():
                parent_data = object()
                first_child_data = object()
                second_child_data = object()
                
                def get_item_data(item_id):
                    if item_id is parent_item_id:
                        return parent_data
                    elif item_id is first_child_id:
                        return first_child_data
                    elif item_id is second_child_id:
                        return second_child_data
                    return None
                
                tree_ctrl.GetItemData.side_effect = get_item_data
            
            parent_item = TreeItem(tree_ctrl, parent_item_id)
            first_child = TreeItem(tree_ctrl, first_child_id)
            second_child = TreeItem(tree_ctrl, second_child_id)
            
            # Mock the Children property to return the child items
            with patch.object(TreeItem, 'Children', new_callable=lambda: property(lambda self: [first_child, second_child] if self.id == parent_item_id else [])):
                navigator = TreeItemNavigator(parent_item, path='T.Tree', query='TreeItem.GetRootItem(tree)')
                
                # Act
                result0 = navigator[0]
                result1 = navigator[1]
                
                # Assert
                assert isinstance(result0, TreeItemNavigator)
                assert result0.Item is first_child
                assert str(result0.Query) == 'TreeItem.GetRootItem(tree).Children[0]'
                assert isinstance(result1, TreeItemNavigator)
                assert result1.Item is second_child
                assert str(result1.Query) == 'TreeItem.GetRootItem(tree).Children[1]'
    
    # === Properties Tests ===
    
    @skip('covered by: test_*_of_*_returns_tree_item')
    def test_item_is_correct(self) -> None:
        pass
    
    @skip('covered by: test_*_of_*_returns_tree_item')
    def test_query_returns_value_based_on_how_subnavigator_was_found(self) -> None:
        pass


# === Tests for inline_diff ===

class TestInlineDiff:
    """Tests for the inline_diff() function."""
    
    def test_identical_strings_return_unchanged(self) -> None:
        """Test that identical strings return without any diff markers."""
        result = inline_diff('hello', 'hello')
        assert result == 'hello'
    
    def test_completely_different_strings(self) -> None:
        """Test that completely different strings show as one change."""
        result = inline_diff('abc', 'xyz')
        assert result == '{abc→xyz}'
    
    def test_numeric_change(self) -> None:
        """Test that numeric changes are marked correctly."""
        result = inline_diff('27 of 100', '31 of 100')
        assert result == '{27→31} of 100'
    
    def test_deletion(self) -> None:
        """Test that deletions are marked with empty new value."""
        result = inline_diff('hello world', 'hello')
        assert '{' in result and '→}' in result
    
    def test_insertion(self) -> None:
        """Test that insertions are marked with empty old value."""
        result = inline_diff('hello', 'hello world')
        assert '{→' in result and '}' in result
    
    def test_empty_strings(self) -> None:
        """Test edge case with empty strings."""
        assert inline_diff('', '') == ''
        result_add = inline_diff('', 'text')
        assert '{→text}' == result_add
        result_del = inline_diff('text', '')
        assert '{text→}' == result_del
    
    def test_time_string_change(self) -> None:
        """Test that time strings remain as single tokens."""
        result = inline_diff('2:18:01', '2:19:18')
        assert result == '{2:18:01→2:19:18}'
    
    def test_word_replacement(self) -> None:
        """Test that whole words are replaced without splitting."""
        result = inline_diff('Downloading', 'Complete')
        assert result == '{Downloading→Complete}'
    
    def test_comma_separated_numbers(self) -> None:
        """Test that comma-separated numbers remain as single tokens."""
        result = inline_diff('2,310', '2,307')
        assert result == '{2,310→2,307}'
    
    def test_mixed_time_in_sentence(self) -> None:
        """Test time changes within a larger sentence."""
        result = inline_diff(
            '2:18:01 remaining (3.43s/item)',
            '2:19:18 remaining (3.47s/item)'
        )
        assert result == '{2:18:01→2:19:18} remaining ({3.43→3.47}s/item)'
    
    def test_status_word_change_in_sentence(self) -> None:
        """Test status word changes within a larger sentence."""
        result = inline_diff(
            'Downloading: https://example.com -- Downloading',
            'Downloading: https://example.com -- Complete'
        )
        assert result == 'Downloading: https://example.com -- {Downloading→Complete}'
    
    def test_comma_number_in_context(self) -> None:
        """Test comma-separated numbers in descriptive text."""
        result = inline_diff('— 📄 2,310 more', '— 📄 2,307 more')
        assert result == '— 📄 {2,310→2,307} more'
    
    def test_mixed_digits_letters_and_symbols(self) -> None:
        """Test complex string with mixed token types."""
        result = inline_diff('Item 27 (status: OK)', 'Item 30 (status: DONE)')
        assert result == 'Item {27→30} (status: {OK→DONE})'


# === Tests for Snapshot ===

class TestSnapshot:
    """Tests for the Snapshot class."""
    
    def test_can_create_basic_snapshot(self) -> None:
        """Test that a basic snapshot can be created."""
        snap = _make_snapshot('Test Node')
        assert snap._peer_description == 'Test Node'
        assert snap._children == []
        assert snap._path == 'T'
    
    def test_can_create_snapshot_with_children(self) -> None:
        """Test that a snapshot can have children."""
        parent = _make_snapshot('Parent', children=[
            child1 := _make_snapshot('Child 1', path='T[0]'),
            child2 := _make_snapshot('Child 2', path='T[1]')
        ])
        
        assert len(parent._children) == 2
        assert parent._children[0]._peer_description == 'Child 1'
        assert parent._children[1]._peer_description == 'Child 2'
    
    def test_can_create_snapshot_with_peer_obj(self) -> None:
        """Test that a snapshot can store a peer_obj for identity matching."""
        peer_obj = object()
        snap = _make_snapshot('Node', peer_obj=peer_obj)
        assert snap._peer_obj is peer_obj
    
    def test_repr_shows_description(self) -> None:
        """Test that repr() includes the node description."""
        snap = _make_snapshot('Test Description', path='T', accessor='I')
        result = repr(snap)
        assert 'Test Description' in result


# === Tests for SnapshotDiff ===

class TestSnapshotDiffBasics:
    """Tests for the SnapshotDiff class."""
    
    def test_no_changes_returns_empty_diff(self) -> None:
        """Test that comparing identical snapshots shows no changes."""
        snap = _make_snapshot('Node', peer_obj=object())
        diff = Snapshot.diff(snap, snap)
        
        assert isinstance(diff, SnapshotDiff)
        assert not bool(diff)  # Empty diff is falsy
        assert '(no changes)' in repr(diff)
    
    def test_root_description_change(self) -> None:
        """Test that a change in root description is detected."""
        peer_obj = object()
        old = _make_snapshot('Old Description', peer_obj=peer_obj)
        new = _make_snapshot('New Description', peer_obj=peer_obj)
        
        diff = Snapshot.diff(old, new)
        
        assert bool(diff)  # Has changes
        diff_repr = repr(diff)
        assert 'S ~' in diff_repr
        assert '{Old→New}' in diff_repr
    
    def test_child_added(self) -> None:
        """Test that adding a child is detected."""
        parent_peer = object()
        child_peer = object()
        
        old = _make_snapshot('Parent', children=[
            # (none)
        ], peer_obj=parent_peer)
        new = _make_snapshot('Parent', children=[
            _make_snapshot('New Child', path='T[0]', peer_obj=child_peer)
        ], peer_obj=parent_peer)
        
        diff = Snapshot.diff(old, new)
        
        assert bool(diff)
        diff_repr = repr(diff)
        assert 'S[0] +' in diff_repr
        assert 'New Child' in diff_repr
    
    def test_child_removed(self) -> None:
        """Test that removing a child is detected."""
        parent_peer = object()
        child_peer = object()
        
        old = _make_snapshot('Parent', children=[
            _make_snapshot('Old Child', path='T[0]', peer_obj=child_peer)
        ], peer_obj=parent_peer)
        new = _make_snapshot('Parent', children=[
            # (none)
        ], peer_obj=parent_peer)
        
        diff = Snapshot.diff(old, new)
        
        assert bool(diff)
        diff_repr = repr(diff)
        assert 'S[0] -' in diff_repr
        assert 'Old Child' in diff_repr
    
    def test_child_description_modified(self) -> None:
        """Test that a change in child description is detected."""
        parent_peer = object()
        child_peer = object()
        
        old = _make_snapshot('Parent', children=[
            _make_snapshot('Child v1', path='T[0]', peer_obj=child_peer)
        ], peer_obj=parent_peer)
        new = _make_snapshot('Parent', children=[
            _make_snapshot('Child v2', path='T[0]', peer_obj=child_peer)
        ], peer_obj=parent_peer)
        
        diff = Snapshot.diff(old, new)
        
        assert bool(diff)
        diff_repr = repr(diff)
        assert '# S := T[0]' in diff_repr
        assert 'S ~' in diff_repr
        assert 'Child' in diff_repr
    
    def test_child_moved_without_modification(self) -> None:
        """Test that a child moving positions (but not changing) is detected."""
        parent_peer = object()
        child1_peer = object()
        child2_peer = object()
        
        old = _make_snapshot('Parent', children=[
            _make_snapshot('Other Child', path='T[0]', peer_obj=child2_peer),
            _make_snapshot('Moved Child', path='T[1]', peer_obj=child1_peer),
        ], peer_obj=parent_peer)
        new = _make_snapshot('Parent', children=[
            _make_snapshot('Moved Child', path='T[0]', peer_obj=child1_peer),
            _make_snapshot('Other Child', path='T[1]', peer_obj=child2_peer),
        ], peer_obj=parent_peer)
        
        diff = Snapshot.diff(old, new)
        
        assert bool(diff)
        diff_repr = repr(diff)
        # Should show index change
        assert '0→1' in diff_repr
        assert '1→0' in diff_repr
        assert 'Moved Child' in diff_repr
    
    def test_multiple_children_modified(self) -> None:
        """Test that multiple child modifications are all reported."""
        parent_peer = object()
        child1_peer = object()
        child2_peer = object()
        
        old = _make_snapshot('Parent', children=[
            _make_snapshot('Child 1 v1', path='T[0]', peer_obj=child1_peer),
            _make_snapshot('Child 2 v1', path='T[1]', peer_obj=child2_peer),
        ], peer_obj=parent_peer)
        new = _make_snapshot('Parent', children=[
            _make_snapshot('Child 1 v2', path='T[0]', peer_obj=child1_peer),
            _make_snapshot('Child 2 v2', path='T[1]', peer_obj=child2_peer),
        ], peer_obj=parent_peer)
        
        diff = Snapshot.diff(old, new)
        
        assert bool(diff)
        diff_repr = repr(diff)
        assert 'S[0] ~' in diff_repr
        assert 'S[1] ~' in diff_repr
        assert 'Child 1' in diff_repr
        assert 'Child 2' in diff_repr
    
    def test_nested_changes(self) -> None:
        """Test that changes deep in the tree are detected."""
        root_peer = object()
        parent_peer = object()
        grandchild_peer = object()
        
        old = _make_snapshot('Root', children=[
            _make_snapshot('Parent', children=[
                _make_snapshot('Grandchild v1', path='T[0][0]', peer_obj=grandchild_peer)
            ], path='T[0]', peer_obj=parent_peer)
        ], peer_obj=root_peer)
        new = _make_snapshot('Root', children=[
            _make_snapshot('Parent', children=[
                _make_snapshot('Grandchild v2', path='T[0][0]', peer_obj=grandchild_peer)
            ], path='T[0]', peer_obj=parent_peer)
        ], peer_obj=root_peer)
        
        diff = Snapshot.diff(old, new)
        
        assert bool(diff)
        diff_repr = repr(diff)
        assert '# S := T[0][0]' in diff_repr
        assert 'S ~' in diff_repr
        assert 'Grandchild' in diff_repr
    
    def test_mixed_operations(self) -> None:
        """Test a complex scenario with additions, removals, and modifications."""
        parent_peer = object()
        keep_peer = object()
        remove_peer = object()
        modify_peer = object()
        add_peer = object()
        
        old = _make_snapshot('Parent', children=[
            _make_snapshot('Keep', path='T[0]', peer_obj=keep_peer),
            _make_snapshot('Remove', path='T[1]', peer_obj=remove_peer),
            _make_snapshot('Modify v1', path='T[2]', peer_obj=modify_peer),
        ], peer_obj=parent_peer)
        new = _make_snapshot('Parent', children=[
            _make_snapshot('Keep', path='T[0]', peer_obj=keep_peer),
            _make_snapshot('Modify v2', path='T[1]', peer_obj=modify_peer),
            _make_snapshot('Add', path='T[2]', peer_obj=add_peer),
        ], peer_obj=parent_peer)
        
        diff = Snapshot.diff(old, new)
        
        assert bool(diff)
        diff_repr = repr(diff)
        assert 'Remove' in diff_repr
        assert 'Modify' in diff_repr
        assert 'Add' in diff_repr
        assert '-' in diff_repr  # deletion
        assert '+' in diff_repr  # addition
        assert '~' in diff_repr  # modification
    
    def test_added_node_with_descendents_shows_all_descendents(self) -> None:
        """Test that adding a node with descendents displays all of them."""
        parent_peer = object()
        new_parent_peer = object()
        new_child1_peer = object()
        new_child2_peer = object()
        new_grandchild_peer = object()
        
        old = _make_snapshot('Root', children=[
            # (empty)
        ], peer_obj=parent_peer)
        new = _make_snapshot('Root', children=[
            _make_snapshot('New Parent', children=[
                _make_snapshot('New Child 1', children=[
                    _make_snapshot('New Grandchild', path='T[0][0][0]', peer_obj=new_grandchild_peer)
                ], path='T[0][0]', peer_obj=new_child1_peer),
                _make_snapshot('New Child 2', path='T[0][1]', peer_obj=new_child2_peer),
            ], path='T[0]', peer_obj=new_parent_peer)
        ], peer_obj=parent_peer)
        
        diff = Snapshot.diff(old, new)
        
        assert bool(diff)
        diff_repr = repr(diff)
        # Should show the added parent
        assert 'S[0] + New Parent' in diff_repr
        # Should show all added descendents
        assert 'S[0][0] + New Child 1' in diff_repr
        assert 'S[0][0][0] + New Grandchild' in diff_repr
        assert 'S[0][1] + New Child 2' in diff_repr
    
    def test_removed_node_with_descendents_shows_all_descendents_if_deletion_style_is_full(self) -> None:
        """Test that removing a node with descendents displays all of them."""
        parent_peer = object()
        old_parent_peer = object()
        old_child1_peer = object()
        old_child2_peer = object()
        old_grandchild_peer = object()
        
        old = _make_snapshot('Root', children=[
            _make_snapshot('Old Parent', children=[
                _make_snapshot('Old Child 1', children=[
                    _make_snapshot('Old Grandchild', path='T[0][0][0]', peer_obj=old_grandchild_peer)
                ], path='T[0][0]', peer_obj=old_child1_peer),
                _make_snapshot('Old Child 2', path='T[0][1]', peer_obj=old_child2_peer),
            ], path='T[0]', peer_obj=old_parent_peer)
        ], peer_obj=parent_peer)
        new = _make_snapshot('Root', children=[
            # (empty)
        ], peer_obj=parent_peer)
        
        diff = Snapshot.diff(old, new, deletion_style='full')
        
        assert bool(diff)
        diff_repr = repr(diff)
        # Should show the removed parent
        assert 'S[0] - Old Parent' in diff_repr
        # Should show all removed descendents
        assert 'S[0][0] - Old Child 1' in diff_repr
        assert 'S[0][0][0] - Old Grandchild' in diff_repr
        assert 'S[0][1] - Old Child 2' in diff_repr
    
    def test_removed_node_with_descendents_shows_descendents_placeholder_by_default(self) -> None:
        """Test that removing a node with descendents displays all of them."""
        parent_peer = object()
        old_parent_peer = object()
        old_child1_peer = object()
        old_child2_peer = object()
        old_grandchild_peer = object()
        
        old = _make_snapshot('Root', children=[
            _make_snapshot('Old Parent', children=[
                _make_snapshot('Old Child 1', children=[
                    _make_snapshot('Old Grandchild', path='T[0][0][0]', peer_obj=old_grandchild_peer)
                ], path='T[0][0]', peer_obj=old_child1_peer),
                _make_snapshot('Old Child 2', path='T[0][1]', peer_obj=old_child2_peer),
            ], path='T[0]', peer_obj=old_parent_peer)
        ], peer_obj=parent_peer)
        new = _make_snapshot('Root', children=[
            # (empty)
        ], peer_obj=parent_peer)
        
        assert _DEFAULT_DELETION_STYLE == 'minimal'
        diff = Snapshot.diff(old, new)  # with _DEFAULT_DELETION_STYLE
        
        assert bool(diff)
        diff_repr = repr(diff)
        # Should show the removed parent
        assert 'S[0] - Old Parent' in diff_repr
        # Should show all descendents placeholder only
        assert 'S[0][0..1] - More(Count=2)' in diff_repr
        assert 'S[0][0][0] - Old Grandchild' not in diff_repr
    
    # TODO: Consider eliminating support for diff'ing Snapshots
    #       that lack a peer_obj
    def test_fallback_to_description_matching_when_no_peer_obj(self) -> None:
        """Test that matching falls back to description when peer_obj is None."""
        parent_peer = object()
        
        old = _make_snapshot('Parent', children=[
            _make_snapshot('Child A', path='T[0]', peer_obj=None),
            _make_snapshot('Child B', path='T[1]', peer_obj=None),
        ], peer_obj=parent_peer)
        new = _make_snapshot('Parent', children=[
            _make_snapshot('Child A', path='T[0]', peer_obj=None),
            _make_snapshot('Child B Modified', path='T[1]', peer_obj=None),
        ], peer_obj=parent_peer)
        
        diff = Snapshot.diff(old, new)
        
        assert bool(diff)
        # Child A should match by description, Child B should be seen as removed/added
        diff_repr = repr(diff)
        assert 'Child B' in diff_repr
    
    def test_even_when_children_elided_in_display_then_changes_still_detected_in_diff(self) -> None:
        """Test that snapshots with children_elided=True still report child changes in diffs."""
        parent_peer = object()
        child1_peer = object()
        child2_peer = object()
        
        # Old snapshot has children fully captured
        old = _make_snapshot('Parent', children=[
            _make_snapshot('Child 1', path='T[0]', peer_obj=child1_peer),
            _make_snapshot('Child 2', path='T[1]', peer_obj=child2_peer),
        ], peer_obj=parent_peer)
        
        # New snapshot has children elided (at display time, but still captured internally)
        new = _make_snapshot('Parent', children=[
            # empty
        ], peer_obj=parent_peer, children_elided=True)
        
        diff = Snapshot.diff(old, new)
        
        # Should report children as removed even though new snapshot has elided children
        # because children_elided only affects display, not diff computation
        diff_repr = repr(diff)
        assert 'Child 1' in diff_repr
        assert 'Child 2' in diff_repr
        # Should show deletions
        assert 'S[0] - Child 1' in diff_repr
        assert 'S[1] - Child 2' in diff_repr
    
    def test_even_when_children_elided_in_display_then_changes_still_detected_in_recursive_diff(self) -> None:
        """Test that children_elided on matched child nodes still allows recursive diff."""
        root_peer = object()
        parent_peer = object()
        grandchild_peer = object()
        
        # Old snapshot has full tree
        old = _make_snapshot('Root', children=[
            _make_snapshot('Parent', children=[
                _make_snapshot('Grandchild', path='T[0][0]', peer_obj=grandchild_peer)
            ], path='T[0]', peer_obj=parent_peer)
        ], peer_obj=root_peer)
        
        # New snapshot has Parent with elided children
        new = _make_snapshot('Root', children=[
            _make_snapshot('Parent', children=[
                # empty
            ], path='T[0]', peer_obj=parent_peer, children_elided=True)
        ], peer_obj=root_peer)
        
        diff = Snapshot.diff(old, new)
        
        # Should report Grandchild as removed even though Parent has children_elided=True
        # because children_elided only affects display, not diff computation
        diff_repr = repr(diff)
        assert 'Grandchild' in diff_repr
        assert 'S[0] - Grandchild' in diff_repr


class TestSnapshotDiffDeletionStyle:
    """
    Tests behavior for different values for deletion_style in diff-related APIs.
    
    Most tests focus on deletion_style='minimal' specifically,
    although there is some coverage for deletion_style='full' too.
    """
    
    def test_minimal_deletion_style_collapses_single_child(self) -> None:
        """Test that deletion_style='minimal' collapses a single deleted child."""
        parent_peer = object()
        child_peer = object()
        
        old = _make_snapshot('Parent', children=[
            _make_snapshot('Child', path='T[0]', peer_obj=child_peer)
        ], peer_obj=parent_peer)
        new = _make_snapshot('Parent', children=[
            # (empty)
        ], peer_obj=parent_peer)
        
        diff = Snapshot.diff(old, new, deletion_style='minimal')
        
        assert bool(diff)
        diff_repr = repr(diff)
        # Should show the deleted child but not list it explicitly
        assert 'S[0] - Child' in diff_repr
        # There should be 1 newline: header + 1 deletion entry (no nested children to collapse)
        assert diff_repr.count('\n') == 1  # Header + 1 deletion entry
    
    def test_minimal_deletion_style_collapses_multiple_children(self) -> None:
        """Test that deletion_style='minimal' collapses multiple deleted children into More(Count=N)."""
        parent_peer = object()
        old_parent_peer = object()
        old_child1_peer = object()
        old_child2_peer = object()
        
        old = _make_snapshot('Root', children=[
            _make_snapshot('Old Parent', children=[
                _make_snapshot('Old Child 1', path='T[0][0]', peer_obj=old_child1_peer),
                _make_snapshot('Old Child 2', path='T[0][1]', peer_obj=old_child2_peer),
            ], path='T[0]', peer_obj=old_parent_peer)
        ], peer_obj=parent_peer)
        new = _make_snapshot('Root', children=[
            # (empty)
        ], peer_obj=parent_peer)
        
        diff = Snapshot.diff(old, new, deletion_style='minimal')
        
        assert bool(diff)
        diff_repr = repr(diff)
        # Should show the deleted parent
        assert 'S[0] - Old Parent' in diff_repr
        # Should show collapsed children as More(Count=2)
        assert 'S[0][0..1] - More(Count=2)' in diff_repr
        # Should NOT show individual children
        assert 'Old Child 1' not in diff_repr
        assert 'Old Child 2' not in diff_repr
    
    def test_minimal_deletion_style_with_nested_descendents(self) -> None:
        """Test that deletion_style='minimal' collapses all nested descendents."""
        parent_peer = object()
        old_parent_peer = object()
        old_child1_peer = object()
        old_child2_peer = object()
        old_grandchild_peer = object()
        
        old = _make_snapshot('Root', children=[
            _make_snapshot('Old Parent', children=[
                _make_snapshot('Old Child 1', children=[
                    _make_snapshot('Old Grandchild', path='T[0][0][0]', peer_obj=old_grandchild_peer)
                ], path='T[0][0]', peer_obj=old_child1_peer),
                _make_snapshot('Old Child 2', path='T[0][1]', peer_obj=old_child2_peer),
            ], path='T[0]', peer_obj=old_parent_peer)
        ], peer_obj=parent_peer)
        new = _make_snapshot('Root', children=[
            # (empty)
        ], peer_obj=parent_peer)
        
        diff = Snapshot.diff(old, new, deletion_style='minimal')
        
        assert bool(diff)
        diff_repr = repr(diff)
        # Should show the deleted parent
        assert 'S[0] - Old Parent' in diff_repr
        # Should show collapsed children
        assert 'S[0][0..1] - More(Count=2)' in diff_repr
        # Should NOT show any descendents
        assert 'Old Child 1' not in diff_repr
        assert 'Old Child 2' not in diff_repr
        assert 'Old Grandchild' not in diff_repr
    
    def test_full_deletion_style_shows_all_descendents(self) -> None:
        """Test that deletion_style='full' (default) shows all deleted descendents."""
        parent_peer = object()
        old_parent_peer = object()
        old_child1_peer = object()
        old_child2_peer = object()
        old_grandchild_peer = object()
        
        old = _make_snapshot('Root', children=[
            _make_snapshot('Old Parent', children=[
                _make_snapshot('Old Child 1', children=[
                    _make_snapshot('Old Grandchild', path='T[0][0][0]', peer_obj=old_grandchild_peer)
                ], path='T[0][0]', peer_obj=old_child1_peer),
                _make_snapshot('Old Child 2', path='T[0][1]', peer_obj=old_child2_peer),
            ], path='T[0]', peer_obj=old_parent_peer)
        ], peer_obj=parent_peer)
        new = _make_snapshot('Root', children=[
            # (empty)
        ], peer_obj=parent_peer)
        
        # Use explicit deletion_style='full' to test that it works as before
        diff = Snapshot.diff(old, new, deletion_style='full')
        
        assert bool(diff)
        diff_repr = repr(diff)
        # Should show the removed parent
        assert 'S[0] - Old Parent' in diff_repr
        # Should show all removed descendents
        assert 'S[0][0] - Old Child 1' in diff_repr
        assert 'S[0][0][0] - Old Grandchild' in diff_repr
        assert 'S[0][1] - Old Child 2' in diff_repr
    
    def test_default_deletion_style_is_minimal(self) -> None:
        """Test that the default deletion_style is 'minimal'."""
        assert _DEFAULT_DELETION_STYLE == 'minimal'
    
    def test_minimal_deletion_style_does_not_affect_additions(self) -> None:
        """Test that deletion_style='minimal' does not affect how additions are displayed."""
        parent_peer = object()
        new_parent_peer = object()
        new_child1_peer = object()
        new_child2_peer = object()
        new_grandchild_peer = object()
        
        old = _make_snapshot('Root', children=[
            # (empty)
        ], peer_obj=parent_peer)
        new = _make_snapshot('Root', children=[
            _make_snapshot('New Parent', children=[
                _make_snapshot('New Child 1', children=[
                    _make_snapshot('New Grandchild', path='T[0][0][0]', peer_obj=new_grandchild_peer)
                ], path='T[0][0]', peer_obj=new_child1_peer),
                _make_snapshot('New Child 2', path='T[0][1]', peer_obj=new_child2_peer),
            ], path='T[0]', peer_obj=new_parent_peer)
        ], peer_obj=parent_peer)
        
        diff = Snapshot.diff(old, new, deletion_style='minimal')
        
        assert bool(diff)
        diff_repr = repr(diff)
        # Should show the added parent
        assert 'S[0] + New Parent' in diff_repr
        # Should show all added descendents (minimal only affects deletions)
        assert 'S[0][0] + New Child 1' in diff_repr
        assert 'S[0][0][0] + New Grandchild' in diff_repr
        assert 'S[0][1] + New Child 2' in diff_repr
    
    def test_minimal_deletion_style_with_mixed_changes(self) -> None:
        """Test that deletion_style='minimal' works correctly with mixed additions and deletions."""
        parent_peer = object()
        old_child_peer = object()
        new_child_peer = object()
        old_grandchild1_peer = object()
        old_grandchild2_peer = object()
        
        old = _make_snapshot('Root', children=[
            _make_snapshot('Old Child', children=[
                _make_snapshot('Old Grandchild 1', path='T[0][0]', peer_obj=old_grandchild1_peer),
                _make_snapshot('Old Grandchild 2', path='T[0][1]', peer_obj=old_grandchild2_peer),
            ], path='T[0]', peer_obj=old_child_peer)
        ], peer_obj=parent_peer)
        new = _make_snapshot('Root', children=[
            _make_snapshot('New Child', path='T[0]', peer_obj=new_child_peer)
        ], peer_obj=parent_peer)
        
        diff = Snapshot.diff(old, new, deletion_style='minimal')
        
        assert bool(diff)
        diff_repr = repr(diff)
        # Should show deletion with collapsed children
        assert 'S[0] - Old Child' in diff_repr
        assert 'S[0][0..1] - More(Count=2)' in diff_repr
        # Should show addition (at same index because peers don't match)
        assert 'S[0] + New Child' in diff_repr
        # Should NOT show individual grandchildren
        assert 'Old Grandchild 1' not in diff_repr
        assert 'Old Grandchild 2' not in diff_repr


class TestSnapshotDiffShiftedMoreSyntax:
    """
    Tests that contiguous ranges of moved children (with changed indexes)
    are reported as a single `[A1..B1 → A2..B2] = More(Count=#)` diff entry.
    """

    def test_range_merging_with_additions_interspersed(self) -> None:
        """
        Test that contiguous moved items are merged into a range even when
        additions are interspersed in the sorted output.
        
        Verifies that 2 or more contiguous moves are merged into a range.
        """
        # Create peers for identity matching
        item1 = object()
        item2 = object()
        item3 = object()
        
        old = _make_snapshot(
            'Root',
            [
                _make_snapshot('Item1', path='T[0]', peer_obj=item1),
                _make_snapshot('Item2', path='T[1]', peer_obj=item2),
                _make_snapshot('Item3', path='T[2]', peer_obj=item3),
            ],
        )
        
        new = _make_snapshot(
            'Root',
            [
                _make_snapshot('NewItem1', path='T[0]', peer_obj=object()),
                _make_snapshot('Item1', path='T[1]', peer_obj=item1),
                _make_snapshot('NewItem2', path='T[2]', peer_obj=object()),
                _make_snapshot('Item2', path='T[3]', peer_obj=item2),
                _make_snapshot('Item3', path='T[4]', peer_obj=item3),
            ],
        )
        
        expected_diff_repr_lines = [
            '# S := T',
            'S[0→1] = Item1',
            'S[0] + NewItem1',
            'S[1..2 → 3..4] = More(Count=2)',
            'S[2] + NewItem2',
        ]
        
        diff = Snapshot.diff(old, new)
        diff_repr = repr(diff)
        actual_diff_repr_lines = diff_repr.split('\n')
        assert actual_diff_repr_lines == expected_diff_repr_lines
    
    def test_range_merging_requires_contiguous_new_indices(self) -> None:
        """
        Test that range merging requires BOTH old and new indices to be contiguous.
        
        If items have contiguous old indices but gaps in new indices (due to
        additions), they should not all merge into a single range.
        """
        item1 = object()
        item2 = object()
        item3 = object()
        
        old = _make_snapshot(
            'Root',
            [
                _make_snapshot('Item1', path='T[0]', peer_obj=item1),
                _make_snapshot('Item2', path='T[1]', peer_obj=item2),
                _make_snapshot('Item3', path='T[2]', peer_obj=item3),
            ],
        )
        
        # Items move with a gap in the middle
        new = _make_snapshot(
            'Root',
            [
                _make_snapshot('Item1', path='T[0]', peer_obj=item1),  # Stays at 0
                _make_snapshot('NewItem', path='T[1]', peer_obj=object()),  # New item creates gap
                _make_snapshot('Item2', path='T[2]', peer_obj=item2),  # Moves 1→2
                _make_snapshot('Item3', path='T[3]', peer_obj=item3),  # Moves 2→3
            ],
        )
        
        expected_diff_repr_lines = [
            '# S := T',
            'S[1..2 → 2..3] = More(Count=2)',  # Only Item2 and Item3 merge
            'S[1] + NewItem',
        ]
        
        diff = Snapshot.diff(old, new)
        diff_repr = repr(diff)
        actual_diff_repr_lines = diff_repr.split('\n')
        assert actual_diff_repr_lines == expected_diff_repr_lines
    
    def test_range_merging_single_item_not_merged(self) -> None:
        """
        Test that a single moved item is not turned into a range.
        """
        item1 = object()
        
        old = _make_snapshot(
            'Root',
            [
                _make_snapshot('Item1', path='T[0]', peer_obj=item1),
            ],
        )
        
        new = _make_snapshot(
            'Root',
            [
                _make_snapshot('NewItem', path='T[0]', peer_obj=object()),
                _make_snapshot('Item1', path='T[1]', peer_obj=item1),
            ],
        )
        
        expected_diff_repr_lines = [
            '# S := T',
            'S[0→1] = Item1',  # Single item stays as individual entry
            'S[0] + NewItem',
        ]
        
        diff = Snapshot.diff(old, new)
        diff_repr = repr(diff)
        actual_diff_repr_lines = diff_repr.split('\n')
        assert actual_diff_repr_lines == expected_diff_repr_lines
    
    def test_range_merging_multiple_separate_ranges(self) -> None:
        """
        Test that multiple separate contiguous ranges in the same parent
        are each merged independently.
        """
        item1 = object()
        item2 = object()
        item3 = object()
        item4 = object()
        item5 = object()
        
        old = _make_snapshot(
            'Root',
            [
                _make_snapshot('Item1', path='T[0]', peer_obj=item1),
                _make_snapshot('Item2', path='T[1]', peer_obj=item2),
                _make_snapshot('Item3', path='T[2]', peer_obj=item3),
                _make_snapshot('Item4', path='T[3]', peer_obj=item4),
                _make_snapshot('Item5', path='T[4]', peer_obj=item5),
            ],
        )
        
        # Two separate ranges with a gap: Items 1-2 shift to 2-3, Items 4-5 shift to 6-7
        # Item3 stays at same position creating a break in the sequence
        new = _make_snapshot(
            'Root',
            [
                _make_snapshot('NewItem1', path='T[0]', peer_obj=object()),
                _make_snapshot('NewItem2', path='T[1]', peer_obj=object()),
                _make_snapshot('Item1', path='T[2]', peer_obj=item1),
                _make_snapshot('Item2', path='T[3]', peer_obj=item2),
                _make_snapshot('Item3', path='T[4]', peer_obj=item3),  # Stays at relative position, breaking continuity
                _make_snapshot('NewItem3', path='T[5]', peer_obj=object()),
                _make_snapshot('Item4', path='T[6]', peer_obj=item4),
                _make_snapshot('Item5', path='T[7]', peer_obj=item5),
            ],
        )
        
        expected_diff_repr_lines = [
            '# S := T',
            'S[0..2 → 2..4] = More(Count=3)',  # Items 1-2-3
            'S[0] + NewItem1',
            'S[1] + NewItem2',
            'S[3..4 → 6..7] = More(Count=2)',  # Items 4-5
            'S[5] + NewItem3',
        ]
        
        diff = Snapshot.diff(old, new)
        diff_repr = repr(diff)
        actual_diff_repr_lines = diff_repr.split('\n')
        assert actual_diff_repr_lines == expected_diff_repr_lines
    
    def test_range_merging_only_moves_not_modifications(self) -> None:
        """
        Test that only unchanged moves (=) are merged into ranges,
        not modifications (~).
        """
        item1 = object()
        item2 = object()
        item3 = object()
        item4 = object()
        
        old = _make_snapshot(
            'Root',
            [
                _make_snapshot('Item1', path='T[0]', peer_obj=item1),
                _make_snapshot('Item2-old', path='T[1]', peer_obj=item2),
                _make_snapshot('Item3', path='T[2]', peer_obj=item3),
                _make_snapshot('Item4', path='T[3]', peer_obj=item4),
            ],
        )
        
        new = _make_snapshot(
            'Root',
            [
                _make_snapshot('NewItem', path='T[0]', peer_obj=object()),  # Addition forces items to move
                _make_snapshot('Item1', path='T[1]', peer_obj=item1),
                _make_snapshot('Item2-new', path='T[2]', peer_obj=item2),  # Modified
                _make_snapshot('Item3', path='T[3]', peer_obj=item3),
                _make_snapshot('Item4', path='T[4]', peer_obj=item4),
            ],
        )
        
        expected_diff_repr_lines = [
            '# S := T',
            'S[0→1] = Item1',  # Not merged because Item2 is modified (breaks contiguity)
            'S[0] + NewItem',
            'S[1→2] ~ Item2-{old→new}',  # Modified, not a move
            'S[2..3 → 3..4] = More(Count=2)',  # Item3 and Item4 are merged
        ]
        
        diff = Snapshot.diff(old, new)
        diff_repr = repr(diff)
        actual_diff_repr_lines = diff_repr.split('\n')
        assert actual_diff_repr_lines == expected_diff_repr_lines


class TestSnapshotDiffAddAndDeleteMoreSyntax:
    """
    Test that contiguous ranges of >7 adds or deletes are collapsed such
    that exactly 7 items are displayed with a middle More(Count=#) item.
    """
    
    def test_long_runs_of_additions_are_collapsed(self) -> None:
        """Test that runs of > 7 additions are collapsed with More() entries."""
        parent_peer = object()
        
        # Create a snapshot with many additions (35 new children)
        old = _make_snapshot('Parent', children=[], peer_obj=parent_peer)
        new_children = [
            _make_snapshot(f'Child {i}', path=f'S[{i}]', peer_obj=object())
            for i in range(35)
        ]
        new = _make_snapshot('Parent', children=new_children, peer_obj=parent_peer)
        
        diff = Snapshot.diff(old, new)
        
        assert bool(diff)
        diff_repr = repr(diff)
        
        # Should show first 3 additions
        assert 'S[0] + Child 0' in diff_repr
        assert 'S[1] + Child 1' in diff_repr
        assert 'S[2] + Child 2' in diff_repr
        
        # Should show collapsed middle section
        assert 'S[3..31] + More(Count=29)' in diff_repr
        
        # Should show last 3 additions
        assert 'S[32] + Child 32' in diff_repr
        assert 'S[33] + Child 33' in diff_repr
        assert 'S[34] + Child 34' in diff_repr
        
        # Should NOT show the collapsed entries individually
        assert 'S[15]' not in diff_repr  # middle entry should be collapsed
    
    def test_long_runs_of_deletions_are_collapsed(self) -> None:
        """Test that runs of > 7 deletions are collapsed with More() entries."""
        parent_peer = object()
        
        # Create a snapshot with many deletions (35 removed children)
        old_children = [
            _make_snapshot(f'Child {i}', path=f'S[{i}]', peer_obj=object())
            for i in range(35)
        ]
        old = _make_snapshot('Parent', children=old_children, peer_obj=parent_peer)
        new = _make_snapshot('Parent', children=[], peer_obj=parent_peer)
        
        diff = Snapshot.diff(old, new)
        
        assert bool(diff)
        diff_repr = repr(diff)
        
        # Should show first 3 deletions
        assert 'S[0] - Child 0' in diff_repr
        assert 'S[1] - Child 1' in diff_repr
        assert 'S[2] - Child 2' in diff_repr
        
        # Should show collapsed middle section
        assert 'S[3..31] - More(Count=29)' in diff_repr
        
        # Should show last 3 deletions
        assert 'S[32] - Child 32' in diff_repr
        assert 'S[33] - Child 33' in diff_repr
        assert 'S[34] - Child 34' in diff_repr
        
        # Should NOT show the collapsed entries individually
        assert 'S[15]' not in diff_repr  # middle entry should be collapsed
    
    def test_short_runs_are_not_collapsed(self) -> None:
        """Test that runs of <= 7 additions/deletions are NOT collapsed."""
        parent_peer = object()
        
        # Create a snapshot with exactly 7 additions
        old = _make_snapshot('Parent', children=[], peer_obj=parent_peer)
        new_children = [
            _make_snapshot(f'Child {i}', path=f'S[{i}]', peer_obj=object())
            for i in range(7)
        ]
        new = _make_snapshot('Parent', children=new_children, peer_obj=parent_peer)
        
        diff = Snapshot.diff(old, new)
        
        assert bool(diff)
        diff_repr = repr(diff)
        
        # Should show all 7 additions individually (no More() entry)
        for i in range(7):
            assert f'S[{i}] + Child {i}' in diff_repr
        
        # Should NOT have a More() entry
        assert 'More(Count=' not in diff_repr
    
    def test_non_contiguous_runs_not_collapsed_together(self) -> None:
        """Test that non-contiguous runs of additions are treated separately."""
        parent_peer = object()
        existing_child = object()
        
        # Create old with one child in the middle
        old = _make_snapshot('Parent', children=[
            _make_snapshot('Existing', path='T[5]', peer_obj=existing_child),
        ], peer_obj=parent_peer)
        
        # Create new with additions before and after the existing child
        # Each run has exactly 5 items, so neither should be collapsed (need > 7)
        new_children = []
        for i in range(11):
            if i == 5:
                new_children.append(_make_snapshot('Existing', path=f'S[{i}]', peer_obj=existing_child))
            else:
                new_children.append(_make_snapshot(f'Child {i}', path=f'S[{i}]', peer_obj=object()))
        new = _make_snapshot('Parent', children=new_children, peer_obj=parent_peer)
        
        diff = Snapshot.diff(old, new)
        
        assert bool(diff)
        diff_repr = repr(diff)
        
        # The existing child should not be shown as added or removed
        # (it's matched by peer_obj)
        
        # There should be two separate runs: S[0-4] (5 items) and S[6-10] (5 items)
        # Neither is > 7, so neither should be collapsed
        for i in range(11):
            if i != 5:
                assert f'S[{i}] + Child {i}' in diff_repr
        
        # Should NOT have a More() entry since neither run is > 7
        assert 'More(Count=' not in diff_repr


class TestSnapshotDiffApi:
    """Tests for the SnapshotDiff API."""
    
    def test_old_property_returns_old_snapshot(self) -> None:
        """Test that diff.old returns the old snapshot."""
        old = _make_snapshot('Old', peer_obj=object())
        new = _make_snapshot('New', peer_obj=object())
        
        diff = Snapshot.diff(old, new)
        
        assert diff.old is old
    
    def test_new_property_returns_new_snapshot(self) -> None:
        """Test that diff.new returns the new snapshot."""
        old = _make_snapshot('Old', peer_obj=object())
        new = _make_snapshot('New', peer_obj=object())
        
        diff = Snapshot.diff(old, new)
        
        assert diff.new is new
    
    def test_sub_operator(self) -> None:
        """Test that the __sub__ operator works like Snapshot.diff()."""
        old = _make_snapshot('Old', peer_obj=object())
        new = _make_snapshot('New', peer_obj=object())
        
        diff_method = Snapshot.diff(old, new)
        diff_operator = new - old
        
        assert isinstance(diff_operator, SnapshotDiff)
        assert diff_operator.old is old
        assert diff_operator.new is new
        # Both should produce same repr
        assert repr(diff_method) == repr(diff_operator)
    
    def test_bool_true_when_changes_exist(self) -> None:
        """Test that bool(diff) is True when there are changes."""
        old = _make_snapshot('Old', peer_obj=object())
        new = _make_snapshot('New', peer_obj=object())
        
        diff = Snapshot.diff(old, new)
        
        assert bool(diff) is True
    
    def test_bool_false_when_no_changes(self) -> None:
        """Test that bool(diff) is False when there are no changes."""
        snap = _make_snapshot('Same', peer_obj=object())
        
        diff = Snapshot.diff(snap, snap)
        
        assert bool(diff) is False
    
    def test_custom_name_parameter(self) -> None:
        """Test that the name parameter customizes the root symbol."""
        old = _make_snapshot('Old', peer_obj=object())
        new = _make_snapshot('New', peer_obj=object())
        
        diff = Snapshot.diff(old, new, name='CUSTOM')
        
        diff_repr = repr(diff)
        assert '# CUSTOM :=' in diff_repr
        assert 'CUSTOM ~' in diff_repr
    
    def test_when_try_to_navigate_diff_then_helpful_error_message_raised(self, subtests) -> None:
        root_peer = object()
        
        # Old snapshot: Dialog (minimal)
        old = _make_snapshot(
            '',
            [
                _make_snapshot(
                    "crystal.ui.dialog.BetterMessageDialog(Name='cr-open-or-create-project', Label='Select a Project')",
                    [
                        _make_snapshot(
                            "wx.StaticText(Label='Create a new project or open an existing project?')",
                            path='T[0][0]',
                            peer_obj=object()
                        ),
                    ],
                    path='T[0]',
                    peer_obj=object()
                ),
            ],
            path='T',
            peer_obj=root_peer
        )
        
        # New snapshot: Main window (minimal)
        new = _make_snapshot(
            '',
            [
                _make_snapshot(
                    "wx.Frame(Name='cr-main-window', Label='Untitled Project')",
                    [
                        _make_snapshot(
                            '_',
                            path='T[0][0]',
                            peer_obj=object()
                        ),
                    ],
                    path='T[0]',
                    peer_obj=object()
                ),
            ],
            path='T',
            peer_obj=root_peer
        )
        
        expected_diff_repr_lines = [
            '# S := T',
            "S[0] - crystal.ui.dialog.BetterMessageDialog(Name='cr-open-or-create-project', Label='Select a Project')",
            'S[0][0] - More(Count=1)',
            "S[0] + wx.Frame(Name='cr-main-window', Label='Untitled Project')",
            'S[0][0] + _',
        ]
        
        S = Snapshot.diff(old, new)
        with subtests.test(scenario='print diff'):
            diff_repr = repr(S)
            actual_diff_repr_lines = diff_repr.split('\n')
            assert actual_diff_repr_lines == expected_diff_repr_lines
        
        with subtests.test(scenario='try direct access'):
            with pytest.raises(ValueError, match=re.escape('S[0] is ambiguous. Use S.new[0] or S.old[0] instead')):
                repr(S[0][0])  # type: ignore[index]
        
        with subtests.test(scenario='access new'):
            assert repr(S.new[0][0]) == '# T[0][0].I := _\n{}'
        
        with subtests.test(scenario='access old'):
            assert repr(S.old[0][0]) == "# T[0][0].I := wx.StaticText(Label='Create a new project or open an existing project?')\n{}"


class TestSnapshotDiffSorting:
    """Tests for the ordering of entries in SnapshotDiff output."""
    
    def test_entries_sorted_by_path(self) -> None:
        """Test that diff entries are sorted by path depth-first."""
        root_peer = object()
        child0_peer = object()
        child1_peer = object()
        grandchild_peer = object()
        
        old = _make_snapshot('Root', children=[
            _make_snapshot('Child 0 v1', path='T[0]', peer_obj=child0_peer),
            _make_snapshot('Child 1', children=[
                _make_snapshot('Grandchild v1', path='T[1][0]', peer_obj=grandchild_peer)
            ], path='T[1]', peer_obj=child1_peer),
        ], peer_obj=root_peer)
        new = _make_snapshot('Root', children=[
            _make_snapshot('Child 0 v2', path='T[0]', peer_obj=child0_peer),
            _make_snapshot('Child 1', children=[
                _make_snapshot('Grandchild v2', path='T[1][0]', peer_obj=grandchild_peer)
            ], path='T[1]', peer_obj=child1_peer),
        ], peer_obj=root_peer)
        
        diff = Snapshot.diff(old, new)
        diff_repr = repr(diff)
        
        # S[0] should appear before S[1][0]
        pos_child0 = diff_repr.find('S[0] ~')
        pos_grandchild = diff_repr.find('S[1][0] ~')
        assert pos_child0 < pos_grandchild
    
    def test_additions_come_after_other_operations_at_same_index(self) -> None:
        """Test that additions (+) are sorted after other operations at the same position."""
        parent_peer = object()
        old_child_peer = object()
        new_child_peer = object()
        
        old = _make_snapshot('Parent', children=[
            _make_snapshot('Old Child', path='T[0]', peer_obj=old_child_peer),
        ], peer_obj=parent_peer)
        new = _make_snapshot('Parent', children=[
            _make_snapshot('New Child', path='T[0]', peer_obj=new_child_peer),
        ], peer_obj=parent_peer)
        
        diff = Snapshot.diff(old, new)
        diff_repr = repr(diff)
        assert '# S := T' in diff_repr
        
        # Deletion should come before addition
        lines = diff_repr.split('\n')
        delete_line_idx = next(i for (i, line) in enumerate(lines) if 'S[0] -' in line)
        add_line_idx = next(i for (i, line) in enumerate(lines) if 'S[0] +' in line)
        assert delete_line_idx < add_line_idx


class TestSnapshotDiffGolden:
    """
    Golden tests for SnapshotDiff which verify the exact output format
    for various realistic scenarios.
    """
    
    def test_open_or_create_project_dialog_replaced_with_main_window(self, subtests) -> None:
        """
        Situation:
        - The "Open or Create Project" dialog is replaced with the main window,
          demonstrating that added and removed nodes display all their descendents.
        """
        # Create peer objects for identity matching
        root_peer = object()
        dialog_peer = object()
        dialog_text_peer = object()
        dialog_checkbox_peer = object()
        dialog_open_button_peer = object()
        dialog_new_button_peer = object()
        
        frame_peer = object()
        frame_child_peer = object()
        splitter_peer = object()
        entity_pane_peer = object()
        entity_pane_title_peer = object()
        entity_pane_empty_state_peer = object()
        entity_pane_empty_text_peer = object()
        entity_pane_empty_button_peer = object()
        entity_pane_add_button_peer = object()
        task_pane_peer = object()
        task_pane_title_peer = object()
        
        # Old snapshot: Dialog with children
        old = _make_snapshot(
            '',
            [
                _make_snapshot(
                    "crystal.ui.dialog.BetterMessageDialog(Name='cr-open-or-create-project', Label='Select a Project')",
                    [
                        _make_snapshot(
                            "wx.StaticText(Label='Create a new project or open an existing project?')",
                            path='T[0][0]',
                            peer_obj=dialog_text_peer
                        ),
                        _make_snapshot(
                            "wx.CheckBox(Name='cr-open-or-create-project__checkbox', Label='Open as &read only', Value=False)",
                            path='T[0][1]',
                            peer_obj=dialog_checkbox_peer
                        ),
                        _make_snapshot(
                            "wx.Button(Id=wx.ID_NO, Label='&Open')",
                            path='T[0][2]',
                            peer_obj=dialog_open_button_peer
                        ),
                        _make_snapshot(
                            "wx.Button(Id=wx.ID_YES, Label='&New Project')",
                            path='T[0][3]',
                            peer_obj=dialog_new_button_peer
                        ),
                    ],
                    path='T[0]',
                    peer_obj=dialog_peer
                ),
            ],
            path='T',
            peer_obj=root_peer
        )
        
        # New snapshot: Main window with nested hierarchy
        new = _make_snapshot(
            '',
            [
                _make_snapshot(
                    "wx.Frame(Name='cr-main-window', Label='Untitled Project')",
                    [
                        _make_snapshot(
                            '_',
                            [
                                _make_snapshot(
                                    'wx.SplitterWindow()',
                                    [
                                        _make_snapshot(
                                            "wx.Panel(Name='cr-entity-pane')",
                                            [
                                                _make_snapshot(
                                                    "wx.StaticText(Label='Root URLs and Groups')",
                                                    path='T[0][0][0][0][0]',
                                                    peer_obj=entity_pane_title_peer
                                                ),
                                                _make_snapshot(
                                                    '_',
                                                    [
                                                        _make_snapshot(
                                                            "wx.StaticText(Label='Download your first page by defining a root URL for the page.')",
                                                            path='T[0][0][0][0][1][0]',
                                                            peer_obj=entity_pane_empty_text_peer
                                                        ),
                                                        _make_snapshot(
                                                            "wx.Button(Name='cr-empty-state-new-root-url-button', Label='New Root URL...')",
                                                            path='T[0][0][0][0][1][1]',
                                                            peer_obj=entity_pane_empty_button_peer
                                                        ),
                                                    ],
                                                    path='T[0][0][0][0][1]',
                                                    peer_obj=entity_pane_empty_state_peer
                                                ),
                                                _make_snapshot(
                                                    "wx.Button(Name='cr-add-url-button', Label='New Root URL...')",
                                                    path='T[0][0][0][0][2]',
                                                    peer_obj=entity_pane_add_button_peer
                                                ),
                                            ],
                                            path='T[0][0][0][0]',
                                            peer_obj=entity_pane_peer
                                        ),
                                        _make_snapshot(
                                            "wx.Panel(Name='cr-task-pane')",
                                            [
                                                _make_snapshot(
                                                    "wx.StaticText(Label='Tasks')",
                                                    path='T[0][0][0][1][0]',
                                                    peer_obj=task_pane_title_peer
                                                ),
                                            ],
                                            path='T[0][0][0][1]',
                                            peer_obj=task_pane_peer
                                        ),
                                    ],
                                    path='T[0][0][0]',
                                    peer_obj=splitter_peer
                                ),
                            ],
                            path='T[0][0]',
                            peer_obj=frame_child_peer
                        ),
                    ],
                    path='T[0]',
                    peer_obj=frame_peer
                ),
            ],
            path='T',
            peer_obj=root_peer
        )
        
        expected_diff_repr_lines = [
            '# S := T',
            "S[0] - crystal.ui.dialog.BetterMessageDialog(Name='cr-open-or-create-project', Label='Select a Project')",
            'S[0][0..3] - More(Count=4)',
            "S[0] + wx.Frame(Name='cr-main-window', Label='Untitled Project')",
            'S[0][0] + _',
            'S[0][0][0] + wx.SplitterWindow()',
            "S[0][0][0][0] + wx.Panel(Name='cr-entity-pane')",
            "S[0][0][0][0][0] + wx.StaticText(Label='Root URLs and Groups')",
            'S[0][0][0][0][1] + _',
            "S[0][0][0][0][1][0] + wx.StaticText(Label='Download your first page by defining a root URL for the page.')",
            "S[0][0][0][0][1][1] + wx.Button(Name='cr-empty-state-new-root-url-button', Label='New Root URL...')",
            "S[0][0][0][0][2] + wx.Button(Name='cr-add-url-button', Label='New Root URL...')",
            "S[0][0][0][1] + wx.Panel(Name='cr-task-pane')",
            "S[0][0][0][1][0] + wx.StaticText(Label='Tasks')",
        ]
        
        with subtests.test(direction='forward'):
            diff = Snapshot.diff(old, new)
            diff_repr = repr(diff)
            actual_diff_repr_lines = diff_repr.split('\n')
            assert actual_diff_repr_lines == expected_diff_repr_lines
        
        expected_reverse_diff_repr_lines = [
            '# S := T',
            "S[0] - wx.Frame(Name='cr-main-window', Label='Untitled Project')",
            'S[0][0] - More(Count=1)',
            "S[0] + crystal.ui.dialog.BetterMessageDialog(Name='cr-open-or-create-project', Label='Select a Project')",
            "S[0][0] + wx.StaticText(Label='Create a new project or open an existing project?')",
            "S[0][1] + wx.CheckBox(Name='cr-open-or-create-project__checkbox', Label='Open as &read only', Value=False)",
            "S[0][2] + wx.Button(Id=wx.ID_NO, Label='&Open')",
            "S[0][3] + wx.Button(Id=wx.ID_YES, Label='&New Project')",
        ]
        
        with subtests.test(direction='reverse'):
            diff = Snapshot.diff(new, old)
            diff_repr = repr(diff)
            actual_diff_repr_lines = diff_repr.split('\n')
            assert actual_diff_repr_lines == expected_reverse_diff_repr_lines
    
    def test_new_root_url_dialog_or_other_modal_dialog_appears(self, subtests) -> None:
        """
        Situation:
        - A modal dialog appears over the main window.
        - The main window's children are elided in the new snapshot (at display time).
        - The main window's children are identical in both old and new snapshots.
        - The diff should only show the dialog being added, not the main window's children changing.
        
        This test verifies that children_elided=True only affects display, not data capture.
        Even though children are elided at display time, they're still captured internally.
        When children are identical, no changes are reported (as expected).
        """
        # Create peer objects for identity matching
        root_peer = object()
        main_window_peer = object()
        frame_child_peer = object()
        splitter_peer = object()
        entity_pane_peer = object()
        entity_pane_title_peer = object()
        entity_pane_empty_state_peer = object()
        entity_pane_empty_text_peer = object()
        entity_pane_empty_button_peer = object()
        entity_pane_add_button_peer = object()
        task_pane_peer = object()
        task_pane_title_peer = object()
        
        dialog_peer = object()
        dialog_title_peer = object()
        dialog_url_label_peer = object()
        dialog_url_field_peer = object()
        dialog_cancel_button_peer = object()
        dialog_new_button_peer = object()
        
        # Old snapshot: Just main window with full children
        old = _make_snapshot(
            '',
            [
                _make_snapshot(
                    "wx.Frame(Name='cr-main-window', Label='Untitled Project')",
                    [
                        _make_snapshot(
                            '_',
                            [
                                _make_snapshot(
                                    'wx.SplitterWindow()',
                                    [
                                        _make_snapshot(
                                            "wx.Panel(Name='cr-entity-pane')",
                                            [
                                                _make_snapshot(
                                                    "wx.StaticText(Label='Root URLs and Groups')",
                                                    path='T[0][0][0][0][0]',
                                                    peer_obj=entity_pane_title_peer
                                                ),
                                                _make_snapshot(
                                                    '_',
                                                    [
                                                        _make_snapshot(
                                                            "wx.StaticText(Label='Download your first page by defining a root URL for the page.')",
                                                            path='T[0][0][0][0][1][0]',
                                                            peer_obj=entity_pane_empty_text_peer
                                                        ),
                                                        _make_snapshot(
                                                            "wx.Button(Name='cr-empty-state-new-root-url-button', Label='New Root URL...')",
                                                            path='T[0][0][0][0][1][1]',
                                                            peer_obj=entity_pane_empty_button_peer
                                                        ),
                                                    ],
                                                    path='T[0][0][0][0][1]',
                                                    peer_obj=entity_pane_empty_state_peer
                                                ),
                                                _make_snapshot(
                                                    "wx.Button(Name='cr-add-url-button', Label='New Root URL...')",
                                                    path='T[0][0][0][0][2]',
                                                    peer_obj=entity_pane_add_button_peer
                                                ),
                                            ],
                                            path='T[0][0][0][0]',
                                            peer_obj=entity_pane_peer
                                        ),
                                        _make_snapshot(
                                            "wx.Panel(Name='cr-task-pane')",
                                            [
                                                _make_snapshot(
                                                    "wx.StaticText(Label='Tasks')",
                                                    path='T[0][0][0][1][0]',
                                                    peer_obj=task_pane_title_peer
                                                ),
                                            ],
                                            path='T[0][0][0][1]',
                                            peer_obj=task_pane_peer
                                        ),
                                    ],
                                    path='T[0][0][0]',
                                    peer_obj=splitter_peer
                                ),
                            ],
                            path='T[0][0]',
                            peer_obj=frame_child_peer
                        ),
                    ],
                    path='T[0]',
                    peer_obj=main_window_peer
                ),
            ],
            path='T',
            peer_obj=root_peer
        )
        
        # New snapshot: Main window with children elided + new dialog
        new = _make_snapshot(
            '',
            [
                _make_snapshot(
                    "wx.Frame(Name='cr-main-window', Label='Untitled Project')",
                    [  # Children ARE captured (same as old), just elided at display time
                        _make_snapshot(
                            '_',
                            [
                                _make_snapshot(
                                    'wx.SplitterWindow()',
                                    [
                                        _make_snapshot(
                                            "wx.Panel(Name='cr-entity-pane')",
                                            [
                                                _make_snapshot(
                                                    "wx.StaticText(Label='Root URLs and Groups')",
                                                    path='T[0][0][0][0][0]',
                                                    peer_obj=entity_pane_title_peer
                                                ),
                                                _make_snapshot(
                                                    '_',
                                                    [
                                                        _make_snapshot(
                                                            "wx.StaticText(Label='Download your first page by defining a root URL for the page.')",
                                                            path='T[0][0][0][0][1][0]',
                                                            peer_obj=entity_pane_empty_text_peer
                                                        ),
                                                        _make_snapshot(
                                                            "wx.Button(Name='cr-empty-state-new-root-url-button', Label='New Root URL...')",
                                                            path='T[0][0][0][0][1][1]',
                                                            peer_obj=entity_pane_empty_button_peer
                                                        ),
                                                    ],
                                                    path='T[0][0][0][0][1]',
                                                    peer_obj=entity_pane_empty_state_peer
                                                ),
                                                _make_snapshot(
                                                    "wx.Button(Name='cr-add-url-button', Label='New Root URL...')",
                                                    path='T[0][0][0][0][2]',
                                                    peer_obj=entity_pane_add_button_peer
                                                ),
                                            ],
                                            path='T[0][0][0][0]',
                                            peer_obj=entity_pane_peer
                                        ),
                                        _make_snapshot(
                                            "wx.Panel(Name='cr-task-pane')",
                                            [
                                                _make_snapshot(
                                                    "wx.StaticText(Label='Tasks')",
                                                    path='T[0][0][0][1][0]',
                                                    peer_obj=task_pane_title_peer
                                                ),
                                            ],
                                            path='T[0][0][0][1]',
                                            peer_obj=task_pane_peer
                                        ),
                                    ],
                                    path='T[0][0][0]',
                                    peer_obj=splitter_peer
                                ),
                            ],
                            path='T[0][0]',
                            peer_obj=frame_child_peer
                        ),
                    ],
                    path='T[0]',
                    peer_obj=main_window_peer,
                    children_elided=True
                ),
                _make_snapshot(
                    "wx.Dialog(IsModal=True, Name='cr-new-root-url-dialog', Label='New Root URL')",
                    [
                        _make_snapshot(
                            "wx.StaticText(Label='New Root URL')",
                            path='T[1][0]',
                            peer_obj=dialog_title_peer
                        ),
                        _make_snapshot(
                            "wx.StaticText(Label='URL:')",
                            path='T[1][1]',
                            peer_obj=dialog_url_label_peer
                        ),
                        _make_snapshot(
                            "wx.TextCtrl(Name='cr-new-root-url-dialog__url-field', Value='')",
                            path='T[1][2]',
                            peer_obj=dialog_url_field_peer
                        ),
                        _make_snapshot(
                            "wx.Button(Id=wx.ID_CANCEL, Label='&Cancel')",
                            path='T[1][3]',
                            peer_obj=dialog_cancel_button_peer
                        ),
                        _make_snapshot(
                            "wx.Button(Id=wx.ID_NEW, Label='&New')",
                            path='T[1][4]',
                            peer_obj=dialog_new_button_peer
                        ),
                    ],
                    path='T[1]',
                    peer_obj=dialog_peer
                ),
            ],
            path='T',
            peer_obj=root_peer
        )
        
        # Expected:
        # - Only the dialog should be shown as added
        # - Main window's children should NOT be shown as changed because they're identical
        expected_diff_repr_lines = [
            '# S := T',
            "S[1] + wx.Dialog(IsModal=True, Name='cr-new-root-url-dialog', Label='New Root URL')",
            "S[1][0] + wx.StaticText(Label='New Root URL')",
            "S[1][1] + wx.StaticText(Label='URL:')",
            "S[1][2] + wx.TextCtrl(Name='cr-new-root-url-dialog__url-field', Value='')",
            "S[1][3] + wx.Button(Id=wx.ID_CANCEL, Label='&Cancel')",
            "S[1][4] + wx.Button(Id=wx.ID_NEW, Label='&New')",
        ]
        
        with subtests.test(direction='forward'):
            diff = Snapshot.diff(old, new)
            diff_repr = repr(diff)
            actual_diff_repr_lines = diff_repr.split('\n')
            assert actual_diff_repr_lines == expected_diff_repr_lines
        
        # Expected reverse:
        # - Only the dialog should be shown as removed
        # - Main window children should NOT be shown as changed because they're identical
        expected_reverse_diff_repr_lines = [
            '# S := T',
            "S[1] - wx.Dialog(IsModal=True, Name='cr-new-root-url-dialog', Label='New Root URL')",
            'S[1][0..4] - More(Count=5)',
        ]
        
        with subtests.test(direction='reverse'):
            diff = Snapshot.diff(new, old)
            diff_repr = repr(diff)
            actual_diff_repr_lines = diff_repr.split('\n')
            assert actual_diff_repr_lines == expected_reverse_diff_repr_lines
    
    def test_new_root_url_dialog_disappears_and_creates_entity(self, subtests) -> None:
        """
        Situation:
        - User clicks 'New' button in the 'New Root URL' dialog.
        - The dialog disappears.
        - A new entity appears in the entity tree.
        - The main window's children are elided at display time, but changes within
          those children ARE detected in the diff.
        
        This test verifies that diffs can detect real changes within children_elided=True areas.
        """
        # Create peer objects for identity matching
        root_peer = object()
        main_window_peer = object()
        frame_child_peer = object()
        splitter_peer = object()
        entity_pane_peer = object()
        entity_pane_title_peer = object()
        entity_pane_empty_state_peer = object()
        entity_pane_empty_text_peer = object()
        entity_pane_empty_button_peer = object()
        entity_pane_tree_peer = object()
        entity_pane_tree_root_peer = object()
        entity_pane_tree_item_peer = object()
        entity_pane_add_button_peer = object()
        task_pane_peer = object()
        task_pane_title_peer = object()
        task_pane_tree_peer = object()
        task_pane_tree_root_peer = object()
        task_pane_tree_item_peer = object()
        
        dialog_peer = object()
        dialog_title_peer = object()
        dialog_url_label_peer = object()
        dialog_url_field_peer = object()
        dialog_cancel_button_peer = object()
        dialog_new_button_peer = object()
        
        # Old snapshot: Main window with empty state + dialog
        old = _make_snapshot(
            '',
            [
                _make_snapshot(
                    "wx.Frame(Name='cr-main-window', Label='Untitled Project')",
                    [
                        _make_snapshot(
                            '_',
                            [
                                _make_snapshot(
                                    'wx.SplitterWindow()',
                                    [
                                        _make_snapshot(
                                            "wx.Panel(Name='cr-entity-pane')",
                                            [
                                                _make_snapshot(
                                                    "wx.StaticText(Label='Root URLs and Groups')",
                                                    path='T[0][0][0][0][0]',
                                                    peer_obj=entity_pane_title_peer
                                                ),
                                                _make_snapshot(
                                                    '_',
                                                    [
                                                        _make_snapshot(
                                                            "wx.StaticText(Label='Download your first page by defining a root URL for the page.')",
                                                            path='T[0][0][0][0][1][0]',
                                                            peer_obj=entity_pane_empty_text_peer
                                                        ),
                                                        _make_snapshot(
                                                            "wx.Button(Name='cr-empty-state-new-root-url-button', Label='New Root URL...')",
                                                            path='T[0][0][0][0][1][1]',
                                                            peer_obj=entity_pane_empty_button_peer
                                                        ),
                                                    ],
                                                    path='T[0][0][0][0][1]',
                                                    peer_obj=entity_pane_empty_state_peer
                                                ),
                                                _make_snapshot(
                                                    "wx.Button(Name='cr-add-url-button', Label='New Root URL...')",
                                                    path='T[0][0][0][0][2]',
                                                    peer_obj=entity_pane_add_button_peer
                                                ),
                                            ],
                                            path='T[0][0][0][0]',
                                            peer_obj=entity_pane_peer
                                        ),
                                        _make_snapshot(
                                            "wx.Panel(Name='cr-task-pane')",
                                            [
                                                _make_snapshot(
                                                    "wx.StaticText(Label='Tasks')",
                                                    path='T[0][0][0][1][0]',
                                                    peer_obj=task_pane_title_peer
                                                ),
                                                _make_snapshot(
                                                    "crystal.ui.tree._OrderedTreeCtrl(Name='cr-task-tree')",
                                                    [
                                                        _make_snapshot(
                                                            'TreeItem(IsRoot=True, Visible=False, IsSelected=True)',
                                                            [],  # No children in old snapshot
                                                            path='T[0][0][0][1][1][0]',
                                                            peer_obj=task_pane_tree_root_peer
                                                        ),
                                                    ],
                                                    path='T[0][0][0][1][1]',
                                                    peer_obj=task_pane_tree_peer
                                                ),
                                            ],
                                            path='T[0][0][0][1]',
                                            peer_obj=task_pane_peer
                                        ),
                                    ],
                                    path='T[0][0][0]',
                                    peer_obj=splitter_peer
                                ),
                            ],
                            path='T[0][0]',
                            peer_obj=frame_child_peer
                        ),
                    ],
                    path='T[0]',
                    peer_obj=main_window_peer,
                    children_elided=True
                ),
                _make_snapshot(
                    "wx.Dialog(IsModal=True, Name='cr-new-root-url-dialog', Label='New Root URL')",
                    [
                        _make_snapshot(
                            "wx.StaticText(Label='New Root URL')",
                            path='T[1][0]',
                            peer_obj=dialog_title_peer
                        ),
                        _make_snapshot(
                            "wx.StaticText(Label='URL:')",
                            path='T[1][1]',
                            peer_obj=dialog_url_label_peer
                        ),
                        _make_snapshot(
                            "wx.TextCtrl(Name='cr-new-root-url-dialog__url-field', Value='')",
                            path='T[1][2]',
                            peer_obj=dialog_url_field_peer
                        ),
                        _make_snapshot(
                            "wx.Button(Id=wx.ID_CANCEL, Label='&Cancel')",
                            path='T[1][3]',
                            peer_obj=dialog_cancel_button_peer
                        ),
                        _make_snapshot(
                            "wx.Button(Id=wx.ID_NEW, Label='&New')",
                            path='T[1][4]',
                            peer_obj=dialog_new_button_peer
                        ),
                    ],
                    path='T[1]',
                    peer_obj=dialog_peer
                ),
            ],
            path='T',
            peer_obj=root_peer
        )
        
        # New snapshot: Main window with entity tree (no empty state) + no dialog
        new = _make_snapshot(
            '',
            [
                _make_snapshot(
                    "wx.Frame(Name='cr-main-window', Label='Untitled Project')",
                    [
                        _make_snapshot(
                            '_',
                            [
                                _make_snapshot(
                                    'wx.SplitterWindow()',
                                    [
                                        _make_snapshot(
                                            "wx.Panel(Name='cr-entity-pane')",
                                            [
                                                _make_snapshot(
                                                    "wx.StaticText(Label='Root URLs and Groups')",
                                                    path='T[0][0][0][0][0]',
                                                    peer_obj=entity_pane_title_peer
                                                ),
                                                _make_snapshot(
                                                    "crystal.ui.tree._OrderedTreeCtrl(Name='cr-entity-tree')",
                                                    [
                                                        _make_snapshot(
                                                            'TreeItem(IsRoot=True, Visible=False)',
                                                            [
                                                                _make_snapshot(
                                                                    "TreeItem(👁='▶︎ 📁 /', IsSelected=True, IconTooltip='Fresh root URL')",
                                                                    path='T[0][0][0][0][1][0][0]',
                                                                    peer_obj=entity_pane_tree_item_peer
                                                                ),
                                                            ],
                                                            path='T[0][0][0][0][1][0]',
                                                            peer_obj=entity_pane_tree_root_peer
                                                        ),
                                                    ],
                                                    path='T[0][0][0][0][1]',
                                                    peer_obj=entity_pane_tree_peer
                                                ),
                                                _make_snapshot(
                                                    "wx.Button(Name='cr-add-url-button', Label='New Root URL...')",
                                                    path='T[0][0][0][0][2]',
                                                    peer_obj=entity_pane_add_button_peer
                                                ),
                                            ],
                                            path='T[0][0][0][0]',
                                            peer_obj=entity_pane_peer
                                        ),
                                        _make_snapshot(
                                            "wx.Panel(Name='cr-task-pane')",
                                            [
                                                _make_snapshot(
                                                    "wx.StaticText(Label='Tasks')",
                                                    path='T[0][0][0][1][0]',
                                                    peer_obj=task_pane_title_peer
                                                ),
                                                _make_snapshot(
                                                    "crystal.ui.tree._OrderedTreeCtrl(Name='cr-task-tree')",
                                                    [
                                                        _make_snapshot(
                                                            'TreeItem(IsRoot=True, Visible=False, IsSelected=True)',
                                                            [
                                                                _make_snapshot(
                                                                    "TreeItem(👁='▶︎ 📁 Downloading: https://xkcd.daarchive.net/ -- 2 of 13 item(s) -- ? remaining (?/item)')",
                                                                    path='T[0][0][0][1][1][0][0]',
                                                                    peer_obj=task_pane_tree_item_peer
                                                                ),
                                                            ],
                                                            path='T[0][0][0][1][1][0]',
                                                            peer_obj=task_pane_tree_root_peer
                                                        ),
                                                    ],
                                                    path='T[0][0][0][1][1]',
                                                    peer_obj=task_pane_tree_peer
                                                ),
                                            ],
                                            path='T[0][0][0][1]',
                                            peer_obj=task_pane_peer
                                        ),
                                    ],
                                    path='T[0][0][0]',
                                    peer_obj=splitter_peer
                                ),
                            ],
                            path='T[0][0]',
                            peer_obj=frame_child_peer
                        ),
                    ],
                    path='T[0]',
                    peer_obj=main_window_peer,
                    children_elided=True
                ),
            ],
            path='T',
            peer_obj=root_peer
        )
        
        # Expected:
        # - Dialog is shown as removed
        # - Main window's children ARE shown as changed (even though children_elided=True)
        #   because there are actual differences:
        #   * Empty state replaced with entity tree
        #   * Task tree root gains a new child tree item
        expected_diff_repr_lines = [
            '# S := T',
            'S[0][0][0][0][1] - _',
            'S[0][0][0][0][1][0..1] - More(Count=2)',
            "S[0][0][0][0][1] + crystal.ui.tree._OrderedTreeCtrl(Name='cr-entity-tree')",
            'S[0][0][0][0][1][0] + TreeItem(IsRoot=True, Visible=False)',
            "S[0][0][0][0][1][0][0] + TreeItem(👁='▶︎ 📁 /', IsSelected=True, IconTooltip='Fresh root URL')",
            "S[0][0][0][1][1][0][0] + TreeItem(👁='▶︎ 📁 Downloading: https://xkcd.daarchive.net/ -- 2 of 13 item(s) -- ? remaining (?/item)')",
            "S[1] - wx.Dialog(IsModal=True, Name='cr-new-root-url-dialog', Label='New Root URL')",
            'S[1][0..4] - More(Count=5)',
        ]
        
        with subtests.test(direction='forward'):
            diff = Snapshot.diff(old, new)
            diff_repr = repr(diff)
            actual_diff_repr_lines = diff_repr.split('\n')
            assert actual_diff_repr_lines == expected_diff_repr_lines
        
        # Expected reverse:
        # - Dialog is shown as added
        # - Entity tree replaced with empty state
        # - Task tree item removed from root
        expected_reverse_diff_repr_lines = [
            '# S := T',
            'S[0][0][0][0][1] - crystal.ui.tree._OrderedTreeCtrl(Name=\'cr-entity-tree\')',
            'S[0][0][0][0][1][0] - More(Count=1)',
            'S[0][0][0][0][1] + _',
            "S[0][0][0][0][1][0] + wx.StaticText(Label='Download your first page by defining a root URL for the page.')",
            "S[0][0][0][0][1][1] + wx.Button(Name='cr-empty-state-new-root-url-button', Label='New Root URL...')",
            "S[0][0][0][1][1][0][0] - TreeItem(👁='▶︎ 📁 Downloading: https://xkcd.daarchive.net/ -- 2 of 13 item(s) -- ? remaining (?/item)')",
            "S[1] + wx.Dialog(IsModal=True, Name='cr-new-root-url-dialog', Label='New Root URL')",
            "S[1][0] + wx.StaticText(Label='New Root URL')",
            "S[1][1] + wx.StaticText(Label='URL:')",
            "S[1][2] + wx.TextCtrl(Name='cr-new-root-url-dialog__url-field', Value='')",
            "S[1][3] + wx.Button(Id=wx.ID_CANCEL, Label='&Cancel')",
            "S[1][4] + wx.Button(Id=wx.ID_NEW, Label='&New')",
        ]
        
        with subtests.test(direction='reverse'):
            diff = Snapshot.diff(new, old)
            diff_repr = repr(diff)
            actual_diff_repr_lines = diff_repr.split('\n')
            assert actual_diff_repr_lines == expected_reverse_diff_repr_lines
    
    def test_expand_and_collapse_of_node_in_entity_tree(self, subtests) -> None:
        """
        Situation:
        - A root resource node in the entity tree is expanded,
          revealing its child URLs.
        """
        # Create peer objects for identity-based matching
        root_peer = object()
        root_0_peer = object()
        root_0_0_peer = object()
        root_0_1_peer = object()
        root_0_2_peer = object()
        root_0_3_peer = object()
        root_0_4_peer = object()
        root_0_5_peer = object()
        root_0_6_peer = object()
        root_0_7_peer = object()
        root_1_peer = object()
        root_2_peer = object()
        root_more_peer = object()
        root_5_peer = object()
        root_6_peer = object()
        root_7_peer = object()
        
        # Old snapshot: Root resource collapsed
        old = _make_snapshot(
            'TreeItem(IsRoot=True, Visible=False)',
            [
                _make_snapshot(
                    "TreeItem(👁='▶︎ 📁 /', IsSelected=True, IconTooltip='Fresh root URL')",
                    [],
                    path='T[0][0][0][0][1].Tree[0]',
                    peer_obj=root_0_peer
                ),
                _make_snapshot(
                    "TreeItem(👁='▶︎ 📁 /1/', IconTooltip='Fresh root URL')",
                    [],
                    path='T[0][0][0][0][1].Tree[1]',
                    peer_obj=root_1_peer
                ),
                _make_snapshot(
                    "TreeItem(👁='▶︎ 📁 /2/', IconTooltip='Fresh root URL')",
                    [],
                    path='T[0][0][0][0][1].Tree[2]',
                    peer_obj=root_2_peer
                ),
                _make_snapshot(
                    'More(Count=2)',
                    [],
                    path='T[0][0][0][0][1].Tree[3:5]',
                    peer_obj=root_more_peer
                ),
                _make_snapshot(
                    "TreeItem(👁='▶︎ 📁 /5/', IconTooltip='Fresh root URL')",
                    [],
                    path='T[0][0][0][0][1].Tree[5]',
                    peer_obj=root_5_peer
                ),
                _make_snapshot(
                    "TreeItem(👁='▶︎ 📁 /6/', IconTooltip='Fresh root URL')",
                    [],
                    path='T[0][0][0][0][1].Tree[6]',
                    peer_obj=root_6_peer
                ),
                _make_snapshot(
                    "TreeItem(👁='▶︎ 📁 /#/index.html - Comic', IconTooltip='Group')",
                    [],
                    path='T[0][0][0][0][1].Tree[7]',
                    peer_obj=root_7_peer
                ),
            ],
            path='T[0][0][0][0][1].Tree',
            peer_obj=root_peer
        )
        
        # New snapshot: Root resource expanded
        new = _make_snapshot(
            'TreeItem(IsRoot=True, Visible=False)',
            [
                _make_snapshot(
                    "TreeItem(👁='▼ 📂 /', IsSelected=True, IconTooltip='Fresh root URL')",
                    [
                        _make_snapshot(
                            "TreeItem(👁='▶︎ 📁 /#/index.html - 8 of Comic', IconTooltip='Grouped urls')",
                            [],
                            path='T[0][0][0][0][1].Tree[0][0]',
                            peer_obj=root_0_0_peer
                        ),
                        _make_snapshot(
                            "TreeItem(👁='▶︎ 📁 /atom.xml - Unknown Link (rel=alternate), Link: Feed, Link: Atom Feed', IconTooltip='Undownloaded URL')",
                            [],
                            path='T[0][0][0][0][1].Tree[0][1]',
                            peer_obj=root_0_1_peer
                        ),
                        _make_snapshot(
                            "TreeItem(👁='▶︎ 📁 /rss.xml - Unknown Link (rel=alternate), Link: RSS Feed', IconTooltip='Undownloaded URL')",
                            [],
                            path='T[0][0][0][0][1].Tree[0][2]',
                            peer_obj=root_0_2_peer
                        ),
                        _make_snapshot(
                            "TreeItem(👁='▶︎ 📁 /styles.css - Link: Stylesheet', IconTooltip='Undownloaded URL')",
                            [],
                            path='T[0][0][0][0][1].Tree[0][3]',
                            peer_obj=root_0_3_peer
                        ),
                        _make_snapshot(
                            "TreeItem(👁='▶︎ 📁 /script.js - Link: Script', IconTooltip='Undownloaded URL')",
                            [],
                            path='T[0][0][0][0][1].Tree[0][4]',
                            peer_obj=root_0_4_peer
                        ),
                        _make_snapshot(
                            "TreeItem(👁='▶︎ 📁 /license.html - Link: More details', IconTooltip='Undownloaded URL')",
                            [],
                            path='T[0][0][0][0][1].Tree[0][5]',
                            peer_obj=root_0_5_peer
                        ),
                        _make_snapshot(
                            "TreeItem(👁='▶︎ 📁 (Low-priority: Offsite)', IconTooltip='Offsite URLs')",
                            [],
                            path='T[0][0][0][0][1].Tree[0][6]',
                            peer_obj=root_0_6_peer
                        ),
                        _make_snapshot(
                            "TreeItem(👁='▶︎ 📁 (Hidden: Embedded)', IconTooltip='Embedded URLs')",
                            [],
                            path='T[0][0][0][0][1].Tree[0][7]',
                            peer_obj=root_0_7_peer
                        ),
                    ],
                    path='T[0][0][0][0][1].Tree[0]',
                    peer_obj=root_0_peer
                ),
                _make_snapshot(
                    "TreeItem(👁='▶︎ 📁 /1/', IconTooltip='Fresh root URL')",
                    [],
                    path='T[0][0][0][0][1].Tree[1]',
                    peer_obj=root_1_peer
                ),
                _make_snapshot(
                    "TreeItem(👁='▶︎ 📁 /2/', IconTooltip='Fresh root URL')",
                    [],
                    path='T[0][0][0][0][1].Tree[2]',
                    peer_obj=root_2_peer
                ),
                _make_snapshot(
                    'More(Count=2)',
                    [],
                    path='T[0][0][0][0][1].Tree[3:5]',
                    peer_obj=root_more_peer
                ),
                _make_snapshot(
                    "TreeItem(👁='▶︎ 📁 /5/', IconTooltip='Fresh root URL')",
                    [],
                    path='T[0][0][0][0][1].Tree[5]',
                    peer_obj=root_5_peer
                ),
                _make_snapshot(
                    "TreeItem(👁='▶︎ 📁 /6/', IconTooltip='Fresh root URL')",
                    [],
                    path='T[0][0][0][0][1].Tree[6]',
                    peer_obj=root_6_peer
                ),
                _make_snapshot(
                    "TreeItem(👁='▶︎ 📁 /#/index.html - Comic', IconTooltip='Group')",
                    [],
                    path='T[0][0][0][0][1].Tree[7]',
                    peer_obj=root_7_peer
                ),
            ],
            path='T[0][0][0][0][1].Tree',
            peer_obj=root_peer
        )
        
        expected_diff_repr_lines = [
            '# S := T[0][0][0][0][1].Tree[0]',
            "S ~ TreeItem(👁='{▶︎→▼} {📁→📂} /', IsSelected=True, IconTooltip='Fresh root URL')",
            "S[0] + TreeItem(👁='▶︎ 📁 /#/index.html - 8 of Comic', IconTooltip='Grouped urls')",
            "S[1] + TreeItem(👁='▶︎ 📁 /atom.xml - Unknown Link (rel=alternate), Link: Feed, Link: Atom Feed', IconTooltip='Undownloaded URL')",
            "S[2] + TreeItem(👁='▶︎ 📁 /rss.xml - Unknown Link (rel=alternate), Link: RSS Feed', IconTooltip='Undownloaded URL')",
            'S[3..4] + More(Count=2)',
            "S[5] + TreeItem(👁='▶︎ 📁 /license.html - Link: More details', IconTooltip='Undownloaded URL')",
            "S[6] + TreeItem(👁='▶︎ 📁 (Low-priority: Offsite)', IconTooltip='Offsite URLs')",
            "S[7] + TreeItem(👁='▶︎ 📁 (Hidden: Embedded)', IconTooltip='Embedded URLs')",
        ]
        
        with subtests.test(direction='forward'):
            diff = Snapshot.diff(old, new)
            diff_repr = repr(diff)
            actual_diff_repr_lines = diff_repr.split('\n')
            assert actual_diff_repr_lines == expected_diff_repr_lines
        
        expected_reverse_diff_repr_lines = [
            '# S := T[0][0][0][0][1].Tree[0]',
            "S ~ TreeItem(👁='{▼→▶︎} {📂→📁} /', IsSelected=True, IconTooltip='Fresh root URL')",
            "S[0] - TreeItem(👁='▶︎ 📁 /#/index.html - 8 of Comic', IconTooltip='Grouped urls')",
            "S[1] - TreeItem(👁='▶︎ 📁 /atom.xml - Unknown Link (rel=alternate), Link: Feed, Link: Atom Feed', IconTooltip='Undownloaded URL')",
            "S[2] - TreeItem(👁='▶︎ 📁 /rss.xml - Unknown Link (rel=alternate), Link: RSS Feed', IconTooltip='Undownloaded URL')",
            'S[3..4] - More(Count=2)',
            "S[5] - TreeItem(👁='▶︎ 📁 /license.html - Link: More details', IconTooltip='Undownloaded URL')",
            "S[6] - TreeItem(👁='▶︎ 📁 (Low-priority: Offsite)', IconTooltip='Offsite URLs')",
            "S[7] - TreeItem(👁='▶︎ 📁 (Hidden: Embedded)', IconTooltip='Embedded URLs')",
        ]
        
        with subtests.test(direction='reverse'):
            diff = Snapshot.diff(new, old)
            diff_repr = repr(diff)
            actual_diff_repr_lines = diff_repr.split('\n')
            assert actual_diff_repr_lines == expected_reverse_diff_repr_lines
    
    def test_when_trailing_more_node_in_entity_tree_expanded_then_new_nodes_appended(self, subtests) -> None:
        """
        Situation:
        - A trailing "more" node in the entity tree is expanded,
          revealing additional child URLs.
        """
        # Create peer objects for identity-based matching
        group_peer = object()
        group_0_peer = object()
        group_1_peer = object()
        # Generate peer objects for nodes /1/ through /120/
        child_peers = [object() for i in range(1, 121)]
        group_more_old_peer = object()
        group_more_new_peer = object()
        
        # Old snapshot: Group with nodes /1/ through /100/ visible and a "2,338 more" node
        old = _make_snapshot(
            'TreeItem(IsRoot=True, Visible=False)',
            [
                _make_snapshot(
                    "TreeItem(👁='▶︎ 📁 / - Home', IsSelected=True, IconTooltip='Fresh root URL')",
                    [],
                    path='T[0][0][0][0][1].Tree[0]',
                    peer_obj=group_0_peer
                ),
                _make_snapshot(
                    "TreeItem(👁='▼ 📂 /#/index.html - Comic', IconTooltip='Group')",
                    [
                        _make_snapshot(
                            f"TreeItem(👁='▶︎ 📁 /{i}/index.html', IconTooltip='Undownloaded URL')",
                            [],
                            path=f'T[0][0][0][0][1].Tree[1][{i-1}]',
                            peer_obj=child_peers[i-1]
                        )
                        for i in range(1, 101)
                    ] + [
                        _make_snapshot(
                            "TreeItem(👁='▶︎ 📁 2,338 more')",
                            [],
                            path='T[0][0][0][0][1].Tree[1][100]',
                            peer_obj=group_more_old_peer
                        ),
                    ],
                    path='T[0][0][0][0][1].Tree[1]',
                    peer_obj=group_1_peer
                ),
            ],
            path='T[0][0][0][0][1].Tree',
            peer_obj=group_peer
        )
        
        # New snapshot: Group with nodes /1/ through /120/ visible and a "2,318 more" node
        new = _make_snapshot(
            'TreeItem(IsRoot=True, Visible=False)',
            [
                _make_snapshot(
                    "TreeItem(👁='▶︎ 📁 / - Home', IsSelected=True, IconTooltip='Fresh root URL')",
                    [],
                    path='T[0][0][0][0][1].Tree[0]',
                    peer_obj=group_0_peer
                ),
                _make_snapshot(
                    "TreeItem(👁='▼ 📂 /#/index.html - Comic', IconTooltip='Group')",
                    [
                        _make_snapshot(
                            f"TreeItem(👁='▶︎ 📁 /{i}/index.html', IconTooltip='Undownloaded URL')",
                            [],
                            path=f'T[0][0][0][0][1].Tree[1][{i-1}]',
                            peer_obj=child_peers[i-1]
                        )
                        for i in range(1, 121)
                    ] + [
                        _make_snapshot(
                            "TreeItem(👁='▶︎ 📁 2,318 more')",
                            [],
                            path='T[0][0][0][0][1].Tree[1][120]',
                            peer_obj=group_more_new_peer
                        ),
                    ],
                    path='T[0][0][0][0][1].Tree[1]',
                    peer_obj=group_1_peer
                ),
            ],
            path='T[0][0][0][0][1].Tree',
            peer_obj=group_peer
        )
        
        expected_diff_repr_lines = [
            '# S := T[0][0][0][0][1].Tree[1]',
            "S[100] - TreeItem(👁='▶︎ 📁 2,338 more')",
            "S[100] + TreeItem(👁='▶︎ 📁 /101/index.html', IconTooltip='Undownloaded URL')",
            "S[101] + TreeItem(👁='▶︎ 📁 /102/index.html', IconTooltip='Undownloaded URL')",
            "S[102] + TreeItem(👁='▶︎ 📁 /103/index.html', IconTooltip='Undownloaded URL')",
            'S[103..117] + More(Count=15)',
            "S[118] + TreeItem(👁='▶︎ 📁 /119/index.html', IconTooltip='Undownloaded URL')",
            "S[119] + TreeItem(👁='▶︎ 📁 /120/index.html', IconTooltip='Undownloaded URL')",
            "S[120] + TreeItem(👁='▶︎ 📁 2,318 more')",
        ]
        
        with subtests.test(direction='forward'):
            diff = Snapshot.diff(old, new)
            diff_repr = repr(diff)
            actual_diff_repr_lines = diff_repr.split('\n')
            assert actual_diff_repr_lines == expected_diff_repr_lines
        
        expected_reverse_diff_repr_lines = [
            '# S := T[0][0][0][0][1].Tree[1]',
            "S[100] - TreeItem(👁='▶︎ 📁 /101/index.html', IconTooltip='Undownloaded URL')",
            "S[100] + TreeItem(👁='▶︎ 📁 2,338 more')",
            "S[101] - TreeItem(👁='▶︎ 📁 /102/index.html', IconTooltip='Undownloaded URL')",
            "S[102] - TreeItem(👁='▶︎ 📁 /103/index.html', IconTooltip='Undownloaded URL')",
            'S[103..117] - More(Count=15)',
            "S[118] - TreeItem(👁='▶︎ 📁 /119/index.html', IconTooltip='Undownloaded URL')",
            "S[119] - TreeItem(👁='▶︎ 📁 /120/index.html', IconTooltip='Undownloaded URL')",
            "S[120] - TreeItem(👁='▶︎ 📁 2,318 more')",
        ]
        
        with subtests.test(direction='reverse'):
            diff = Snapshot.diff(new, old)
            diff_repr = repr(diff)
            actual_diff_repr_lines = diff_repr.split('\n')
            assert actual_diff_repr_lines == expected_reverse_diff_repr_lines
    
    def test_when_new_group_defined_then_entity_tree_children_nodes_restructured(self, subtests) -> None:
        """
        Situation:
        - A new group is defined, causing some child URLs of a root resource
          to be reorganized under the group node in the entity tree.
        """
        # Create peer objects for identity-based matching
        root_peer = object()
        root_0_peer = object()
        root_0_0_peer = object()
        root_0_1_peer = object()
        root_0_2_peer = object()
        root_0_39_peer = object()
        root_0_40_peer = object()
        root_0_41_peer = object()
        
        # Peers for URLs that move to the group
        url_1_peer = object()
        url_2438_peer = object()
        url_150_peer = object()
        url_730_peer = object()
        url_162_peer = object()
        url_688_peer = object()
        url_556_peer = object()
        url_1732_peer = object()
        
        # Peers for group nodes
        group_inlined_peer = object()
        group_root_peer = object()
        
        # Old snapshot: Before group is defined
        old = _make_snapshot(
            'TreeItem(IsRoot=True, Visible=False)',
            [
                _make_snapshot(
                    "TreeItem(👁='▼ 📂 / - Home', IconTooltip='Fresh root URL')",
                    [
                        _make_snapshot(
                            "TreeItem(👁='▶︎ 📁 /atom.xml - Unknown Link (rel=alternate), Link: Feed, Link: Atom Feed', IconTooltip='Undownloaded URL')",
                            [],
                            path='T[0][0][0][0][1].Tree[0][0]',
                            peer_obj=root_0_0_peer
                        ),
                        _make_snapshot(
                            "TreeItem(👁='▶︎ 📁 /rss.xml - Unknown Link (rel=alternate), Link: RSS Feed', IconTooltip='Undownloaded URL')",
                            [],
                            path='T[0][0][0][0][1].Tree[0][1]',
                            peer_obj=root_0_1_peer
                        ),
                        _make_snapshot(
                            "TreeItem(👁='▶︎ 📁 /styles.css - Link: Stylesheet', IconTooltip='Undownloaded URL')",
                            [],
                            path='T[0][0][0][0][1].Tree[0][3]',
                            peer_obj=object()
                        ),
                        _make_snapshot(
                            "TreeItem(👁='▶︎ 📁 /script.js - Link: Script', IconTooltip='Undownloaded URL')",
                            [],
                            path='T[0][0][0][0][1].Tree[0][4]',
                            peer_obj=object()
                        ),
                        _make_snapshot(
                            "TreeItem(👁='▶︎ 📁 /1/index.html - Link: |<, Link: |<', IsSelected=True, IconTooltip='Undownloaded URL')",
                            [],
                            path='T[0][0][0][0][1].Tree[0][5]',
                            peer_obj=url_1_peer
                        ),
                        _make_snapshot(
                            "TreeItem(👁='▶︎ 📁 /2438/index.html - Link: < Prev, Link: < Prev', IconTooltip='Undownloaded URL')",
                            [],
                            path='T[0][0][0][0][1].Tree[0][6]',
                            peer_obj=url_2438_peer
                        ),
                        _make_snapshot(
                            "TreeItem(👁='▶︎ 📁 /other1.html - Link', IconTooltip='Undownloaded URL')",
                            [],
                            path='T[0][0][0][0][1].Tree[0][7]',
                            peer_obj=object()
                        ),
                        _make_snapshot(
                            "TreeItem(👁='▶︎ 📁 /other2.html - Link', IconTooltip='Undownloaded URL')",
                            [],
                            path='T[0][0][0][0][1].Tree[0][8]',
                            peer_obj=object()
                        ),
                        _make_snapshot(
                            "TreeItem(👁='▶︎ 📁 /150/index.html - Unknown Href (area)', IconTooltip='Undownloaded URL')",
                            [],
                            path='T[0][0][0][0][1].Tree[0][9]',
                            peer_obj=url_150_peer
                        ),
                        _make_snapshot(
                            "TreeItem(👁='▶︎ 📁 /730/index.html - Unknown Href (area)', IconTooltip='Undownloaded URL')",
                            [],
                            path='T[0][0][0][0][1].Tree[0][10]',
                            peer_obj=url_730_peer
                        ),
                        _make_snapshot(
                            "TreeItem(👁='▶︎ 📁 /162/index.html - Unknown Href (area)', IconTooltip='Undownloaded URL')",
                            [],
                            path='T[0][0][0][0][1].Tree[0][11]',
                            peer_obj=url_162_peer
                        ),
                        _make_snapshot(
                            "TreeItem(👁='▶︎ 📁 /688/index.html - Unknown Href (area)', IconTooltip='Undownloaded URL')",
                            [],
                            path='T[0][0][0][0][1].Tree[0][12]',
                            peer_obj=url_688_peer
                        ),
                        _make_snapshot(
                            "TreeItem(👁='▶︎ 📁 /556/index.html - Unknown Href (area)', IconTooltip='Undownloaded URL')",
                            [],
                            path='T[0][0][0][0][1].Tree[0][13]',
                            peer_obj=url_556_peer
                        ),
                        _make_snapshot(
                            "TreeItem(👁='▶︎ 📁 /1732/index.html - Link', IconTooltip='Undownloaded URL')",
                            [],
                            path='T[0][0][0][0][1].Tree[0][14]',
                            peer_obj=url_1732_peer
                        ),
                        _make_snapshot(
                            "TreeItem(👁='▶︎ 📁 /license.html - Link: More details', IconTooltip='Undownloaded URL')",
                            [],
                            path='T[0][0][0][0][1].Tree[0][15]',
                            peer_obj=root_0_39_peer
                        ),
                        _make_snapshot(
                            "TreeItem(👁='▶︎ 📁 (Low-priority: Offsite)', IconTooltip='Offsite URLs')",
                            [],
                            path='T[0][0][0][0][1].Tree[0][16]',
                            peer_obj=root_0_40_peer
                        ),
                        _make_snapshot(
                            "TreeItem(👁='▶︎ 📁 (Hidden: Embedded)', IconTooltip='Embedded URLs')",
                            [],
                            path='T[0][0][0][0][1].Tree[0][17]',
                            peer_obj=root_0_41_peer
                        ),
                    ],
                    path='T[0][0][0][0][1].Tree[0]',
                    peer_obj=root_0_peer
                ),
            ],
            path='T[0][0][0][0][1].Tree',
            peer_obj=root_peer
        )
        
        # New snapshot: After group is defined
        new = _make_snapshot(
            'TreeItem(IsRoot=True, Visible=False)',
            [
                _make_snapshot(
                    "TreeItem(👁='▼ 📂 / - Home', IconTooltip='Fresh root URL')",
                    [
                        _make_snapshot(
                            "TreeItem(👁='▼ 📂 /#/index.html - 8 of Comic', IconTooltip='Grouped urls')",
                            [
                                _make_snapshot(
                                    "TreeItem(👁='▶︎ 📁 /1/index.html - Link: |<, Link: |<', IsSelected=True, IconTooltip='Undownloaded URL')",
                                    [],
                                    path='T[0][0][0][0][1].Tree[0][0][0]',
                                    peer_obj=url_1_peer
                                ),
                                _make_snapshot(
                                    "TreeItem(👁='▶︎ 📁 /2438/index.html - Link: < Prev, Link: < Prev', IconTooltip='Undownloaded URL')",
                                    [],
                                    path='T[0][0][0][0][1].Tree[0][0][1]',
                                    peer_obj=url_2438_peer
                                ),
                                _make_snapshot(
                                    "TreeItem(👁='▶︎ 📁 /150/index.html - Unknown Href (area)', IconTooltip='Undownloaded URL')",
                                    [],
                                    path='T[0][0][0][0][1].Tree[0][0][2]',
                                    peer_obj=url_150_peer
                                ),
                                _make_snapshot(
                                    "TreeItem(👁='▶︎ 📁 /730/index.html - Unknown Href (area)', IconTooltip='Undownloaded URL')",
                                    [],
                                    path='T[0][0][0][0][1].Tree[0][0][3]',
                                    peer_obj=url_730_peer
                                ),
                                _make_snapshot(
                                    "TreeItem(👁='▶︎ 📁 /162/index.html - Unknown Href (area)', IconTooltip='Undownloaded URL')",
                                    [],
                                    path='T[0][0][0][0][1].Tree[0][0][4]',
                                    peer_obj=url_162_peer
                                ),
                                _make_snapshot(
                                    "TreeItem(👁='▶︎ 📁 /688/index.html - Unknown Href (area)', IconTooltip='Undownloaded URL')",
                                    [],
                                    path='T[0][0][0][0][1].Tree[0][0][5]',
                                    peer_obj=url_688_peer
                                ),
                                _make_snapshot(
                                    "TreeItem(👁='▶︎ 📁 /556/index.html - Unknown Href (area)', IconTooltip='Undownloaded URL')",
                                    [],
                                    path='T[0][0][0][0][1].Tree[0][0][6]',
                                    peer_obj=url_556_peer
                                ),
                                _make_snapshot(
                                    "TreeItem(👁='▶︎ 📁 /1732/index.html - Link', IconTooltip='Undownloaded URL')",
                                    [],
                                    path='T[0][0][0][0][1].Tree[0][0][7]',
                                    peer_obj=url_1732_peer
                                ),
                            ],
                            path='T[0][0][0][0][1].Tree[0][0]',
                            peer_obj=group_inlined_peer
                        ),
                        _make_snapshot(
                            "TreeItem(👁='▶︎ 📁 /atom.xml - Unknown Link (rel=alternate), Link: Feed, Link: Atom Feed', IconTooltip='Undownloaded URL')",
                            [],
                            path='T[0][0][0][0][1].Tree[0][1]',
                            peer_obj=root_0_0_peer
                        ),
                        _make_snapshot(
                            "TreeItem(👁='▶︎ 📁 /rss.xml - Unknown Link (rel=alternate), Link: RSS Feed', IconTooltip='Undownloaded URL')",
                            [],
                            path='T[0][0][0][0][1].Tree[0][2]',
                            peer_obj=root_0_1_peer
                        ),
                        _make_snapshot(
                            "TreeItem(👁='▶︎ 📁 /other1.html - Link', IconTooltip='Undownloaded URL')",
                            [],
                            path='T[0][0][0][0][1].Tree[0][3]',
                            peer_obj=object()
                        ),
                        _make_snapshot(
                            "TreeItem(👁='▶︎ 📁 /other2.html - Link', IconTooltip='Undownloaded URL')",
                            [],
                            path='T[0][0][0][0][1].Tree[0][4]',
                            peer_obj=object()
                        ),
                        _make_snapshot(
                            "TreeItem(👁='▶︎ 📁 /styles.css - Link: Stylesheet', IconTooltip='Undownloaded URL')",
                            [],
                            path='T[0][0][0][0][1].Tree[0][5]',
                            peer_obj=object()
                        ),
                        _make_snapshot(
                            "TreeItem(👁='▶︎ 📁 /script.js - Link: Script', IconTooltip='Undownloaded URL')",
                            [],
                            path='T[0][0][0][0][1].Tree[0][6]',
                            peer_obj=object()
                        ),
                        _make_snapshot(
                            "TreeItem(👁='▶︎ 📁 /license.html - Link: More details', IconTooltip='Undownloaded URL')",
                            [],
                            path='T[0][0][0][0][1].Tree[0][7]',
                            peer_obj=root_0_39_peer
                        ),
                        _make_snapshot(
                            "TreeItem(👁='▶︎ 📁 (Low-priority: Offsite)', IconTooltip='Offsite URLs')",
                            [],
                            path='T[0][0][0][0][1].Tree[0][8]',
                            peer_obj=root_0_40_peer
                        ),
                        _make_snapshot(
                            "TreeItem(👁='▶︎ 📁 (Hidden: Embedded)', IconTooltip='Embedded URLs')",
                            [],
                            path='T[0][0][0][0][1].Tree[0][9]',
                            peer_obj=root_0_41_peer
                        ),
                    ],
                    path='T[0][0][0][0][1].Tree[0]',
                    peer_obj=root_0_peer
                ),
                _make_snapshot(
                    "TreeItem(👁='▶︎ 📁 /#/index.html - Comic', IconTooltip='Group')",
                    [],
                    path='T[0][0][0][0][1].Tree[1]',
                    peer_obj=group_root_peer
                ),
            ],
            path='T[0][0][0][0][1].Tree',
            peer_obj=root_peer
        )
        
        expected_diff_repr_lines = [
            '# S := T[0][0][0][0][1].Tree',
            'S[0][0..1 → 1..2] = More(Count=2)',
            "S[0][0] + TreeItem(👁='▼ 📂 /#/index.html - 8 of Comic', IconTooltip='Grouped urls')",
            "S[0][0][0] + TreeItem(👁='▶︎ 📁 /1/index.html - Link: |<, Link: |<', IsSelected=True, IconTooltip='Undownloaded URL')",
            "S[0][0][1] + TreeItem(👁='▶︎ 📁 /2438/index.html - Link: < Prev, Link: < Prev', IconTooltip='Undownloaded URL')",
            "S[0][0][2] + TreeItem(👁='▶︎ 📁 /150/index.html - Unknown Href (area)', IconTooltip='Undownloaded URL')",
            "S[0][0][3] + TreeItem(👁='▶︎ 📁 /730/index.html - Unknown Href (area)', IconTooltip='Undownloaded URL')",
            "S[0][0][4] + TreeItem(👁='▶︎ 📁 /162/index.html - Unknown Href (area)', IconTooltip='Undownloaded URL')",
            "S[0][0][5] + TreeItem(👁='▶︎ 📁 /688/index.html - Unknown Href (area)', IconTooltip='Undownloaded URL')",
            "S[0][0][6] + TreeItem(👁='▶︎ 📁 /556/index.html - Unknown Href (area)', IconTooltip='Undownloaded URL')",
            "S[0][0][7] + TreeItem(👁='▶︎ 📁 /1732/index.html - Link', IconTooltip='Undownloaded URL')",
            'S[0][2..3 → 5..6] = More(Count=2)',
            "S[0][4] - TreeItem(👁='▶︎ 📁 /1/index.html - Link: |<, Link: |<', IsSelected=True, IconTooltip='Undownloaded URL')",
            "S[0][5] - TreeItem(👁='▶︎ 📁 /2438/index.html - Link: < Prev, Link: < Prev', IconTooltip='Undownloaded URL')",
            'S[0][6..7 → 3..4] = More(Count=2)',
            "S[0][8] - TreeItem(👁='▶︎ 📁 /150/index.html - Unknown Href (area)', IconTooltip='Undownloaded URL')",
            "S[0][9] - TreeItem(👁='▶︎ 📁 /730/index.html - Unknown Href (area)', IconTooltip='Undownloaded URL')",
            "S[0][10] - TreeItem(👁='▶︎ 📁 /162/index.html - Unknown Href (area)', IconTooltip='Undownloaded URL')",
            "S[0][11] - TreeItem(👁='▶︎ 📁 /688/index.html - Unknown Href (area)', IconTooltip='Undownloaded URL')",
            "S[0][12] - TreeItem(👁='▶︎ 📁 /556/index.html - Unknown Href (area)', IconTooltip='Undownloaded URL')",
            "S[0][13] - TreeItem(👁='▶︎ 📁 /1732/index.html - Link', IconTooltip='Undownloaded URL')",
            'S[0][14..16 → 7..9] = More(Count=3)',
            "S[1] + TreeItem(👁='▶︎ 📁 /#/index.html - Comic', IconTooltip='Group')",
        ]
        
        with subtests.test(direction='forward'):
            diff = Snapshot.diff(old, new)
            diff_repr = repr(diff)
            actual_diff_repr_lines = diff_repr.split('\n')
            assert actual_diff_repr_lines == expected_diff_repr_lines
        
        expected_reverse_diff_repr_lines = [
            '# S := T[0][0][0][0][1].Tree',
            "S[0][0] - TreeItem(👁='▼ 📂 /#/index.html - 8 of Comic', IconTooltip='Grouped urls')",
            'S[0][0][0..7] - More(Count=8)',
            'S[0][1..2 → 0..1] = More(Count=2)',
            'S[0][3..4 → 6..7] = More(Count=2)',
            "S[0][4] + TreeItem(👁='▶︎ 📁 /1/index.html - Link: |<, Link: |<', IsSelected=True, IconTooltip='Undownloaded URL')",
            'S[0][5..6 → 2..3] = More(Count=2)',
            "S[0][5] + TreeItem(👁='▶︎ 📁 /2438/index.html - Link: < Prev, Link: < Prev', IconTooltip='Undownloaded URL')",
            'S[0][7..9 → 14..16] = More(Count=3)',
            "S[0][8] + TreeItem(👁='▶︎ 📁 /150/index.html - Unknown Href (area)', IconTooltip='Undownloaded URL')",
            "S[0][9] + TreeItem(👁='▶︎ 📁 /730/index.html - Unknown Href (area)', IconTooltip='Undownloaded URL')",
            "S[0][10] + TreeItem(👁='▶︎ 📁 /162/index.html - Unknown Href (area)', IconTooltip='Undownloaded URL')",
            "S[0][11] + TreeItem(👁='▶︎ 📁 /688/index.html - Unknown Href (area)', IconTooltip='Undownloaded URL')",
            "S[0][12] + TreeItem(👁='▶︎ 📁 /556/index.html - Unknown Href (area)', IconTooltip='Undownloaded URL')",
            "S[0][13] + TreeItem(👁='▶︎ 📁 /1732/index.html - Link', IconTooltip='Undownloaded URL')",
            "S[1] - TreeItem(👁='▶︎ 📁 /#/index.html - Comic', IconTooltip='Group')",
        ]
        
        with subtests.test(direction='reverse'):
            diff = Snapshot.diff(new, old)
            diff_repr = repr(diff)
            actual_diff_repr_lines = diff_repr.split('\n')
            assert actual_diff_repr_lines == expected_reverse_diff_repr_lines
    
    def test_progress_of_download_group_task_in_task_tree(self, subtests) -> None:
        """
        Situation:
        - Multiple child download tasks are progressing, with items being
          completed, moved, and added.
        """
        # Create peer objects for identity-based matching
        root_peer = object()
        task_peer = object()
        subtask_peer = object()
        more_peer = object()
        item_2424_peer = object()
        item_2423_peer = object()
        item_2422_peer = object()
        item_2421_peer = object()
        item_2420_peer = object()
        item_1001_peer = object()
        item_1002_peer = object()
        item_1003_peer = object()
        item_1004_peer = object()
        item_1005_peer = object()
        item_1006_peer = object()
        item_1007_peer = object()
        item_1008_peer = object()
        item_1009_peer = object()
        more_end_peer = object()
        
        # Old snapshot: 27 items completed
        old = _make_snapshot(
            'TreeItem(IsRoot=True, Visible=False, IsSelected=True)',
            [
                _make_snapshot(
                    "TreeItem(👁='▼ 📂 Downloading group: Comic -- 27 of 2,438 item(s) -- 2:18:01 remaining (3.43s/item)')",
                    [  
                        _make_snapshot(
                            "TreeItem(👁='▶︎ 📁 Finding members of group: Comic -- Complete')",
                            path='T[0][0]',
                            peer_obj=subtask_peer
                        ),
                        _make_snapshot(
                            "TreeItem(👁='▼ 📂 Downloading members of group: Comic -- 27 of 2,438 item(s) -- 2:18:01 remaining (3.43s/item)')",
                            [
                                _make_snapshot(
                                    "TreeItem(👁='— 📄 22 more')",
                                    path='T[0][1][0]',
                                    peer_obj=more_peer
                                ),
                                _make_snapshot(
                                    "TreeItem(👁='▶︎ 📁 Downloading: https://xkcd.daarchive.net/2424/index.html -- Complete')",
                                    path='T[0][1][1]',
                                    peer_obj=item_2424_peer
                                ),
                                _make_snapshot(
                                    "TreeItem(👁='▶︎ 📁 Downloading: https://xkcd.daarchive.net/2423/index.html -- Complete')",
                                    path='T[0][1][2]',
                                    peer_obj=item_2423_peer
                                ),
                                _make_snapshot(
                                    "TreeItem(👁='▶︎ 📁 Downloading: https://xkcd.daarchive.net/2422/index.html -- Complete')",
                                    path='T[0][1][3]',
                                    peer_obj=item_2422_peer
                                ),
                                _make_snapshot(
                                    "TreeItem(👁='▶︎ 📁 Downloading: https://xkcd.daarchive.net/2421/index.html -- Complete')",
                                    path='T[0][1][4]',
                                    peer_obj=item_2421_peer
                                ),
                                _make_snapshot(
                                    "TreeItem(👁='▶︎ 📁 Downloading: https://xkcd.daarchive.net/2420/index.html -- Complete')",
                                    path='T[0][1][5]',
                                    peer_obj=item_2420_peer
                                ),
                                _make_snapshot(
                                    "TreeItem(👁='▶︎ 📁 Downloading: https://xkcd.daarchive.net/1001/index.html -- Downloading')",
                                    path='T[0][1][6]',
                                    peer_obj=item_1001_peer
                                ),
                                _make_snapshot(
                                    "TreeItem(👁='▶︎ 📁 Downloading: https://xkcd.daarchive.net/1002/index.html -- Queued')",
                                    path='T[0][1][7]',
                                    peer_obj=item_1002_peer
                                ),
                                _make_snapshot(
                                    "TreeItem(👁='▶︎ 📁 Downloading: https://xkcd.daarchive.net/1003/index.html -- Queued')",
                                    path='T[0][1][8]',
                                    peer_obj=item_1003_peer
                                ),
                                _make_snapshot(
                                    "TreeItem(👁='▶︎ 📁 Downloading: https://xkcd.daarchive.net/1004/index.html -- Queued')",
                                    path='T[0][1][9]',
                                    peer_obj=item_1004_peer
                                ),
                                _make_snapshot(
                                    "TreeItem(👁='▶︎ 📁 Downloading: https://xkcd.daarchive.net/1005/index.html -- Queued')",
                                    path='T[0][1][10]',
                                    peer_obj=item_1005_peer
                                ),
                                _make_snapshot(
                                    "TreeItem(👁='▶︎ 📁 Downloading: https://xkcd.daarchive.net/1006/index.html -- Queued')",
                                    path='T[0][1][11]',
                                    peer_obj=item_1006_peer
                                ),
                                _make_snapshot(
                                    "TreeItem(👁='— 📄 2,310 more')",
                                    path='T[0][1][12]',
                                    peer_obj=more_end_peer
                                ),
                            ],
                            path='T[0][1]',
                            peer_obj=task_peer
                        ),
                    ],
                    path="T['cr-entity-tree'].Tree[0]",
                    peer_obj=task_peer
                ),
            ],
            path="T['cr-entity-tree'].Tree",
            peer_obj=root_peer
        )
        
        # New snapshot: 30 items completed, scrolled up by 3 items
        new = _make_snapshot(
            'TreeItem(IsRoot=True, Visible=False, IsSelected=True)',
            [
                _make_snapshot(
                    "TreeItem(👁='▼ 📂 Downloading group: Comic -- 30 of 2,438 item(s) -- 2:19:18 remaining (3.47s/item)')",
                    [
                        _make_snapshot(
                            "TreeItem(👁='▶︎ 📁 Finding members of group: Comic -- Complete')",
                            path='T[0][0]',
                            peer_obj=subtask_peer
                        ),
                        _make_snapshot(
                            "TreeItem(👁='▼ 📂 Downloading members of group: Comic -- 30 of 2,438 item(s) -- 2:19:18 remaining (3.47s/item)')",
                            [
                                _make_snapshot(
                                    "TreeItem(👁='— 📄 25 more')",
                                    path='T[0][1][0]',
                                    peer_obj=more_peer
                                ),
                                # 2424, 2423, 2422 removed (scrolled off by 3 items)
                                # 2421, 2420 stay visible and complete
                                _make_snapshot(
                                    "TreeItem(👁='▶︎ 📁 Downloading: https://xkcd.daarchive.net/2421/index.html -- Complete')",
                                    path='T[0][1][1]',
                                    peer_obj=item_2421_peer
                                ),
                                _make_snapshot(
                                    "TreeItem(👁='▶︎ 📁 Downloading: https://xkcd.daarchive.net/2420/index.html -- Complete')",
                                    path='T[0][1][2]',
                                    peer_obj=item_2420_peer
                                ),
                                # 1001 moved from index 6 to 3 and completed
                                _make_snapshot(
                                    "TreeItem(👁='▶︎ 📁 Downloading: https://xkcd.daarchive.net/1001/index.html -- Complete')",
                                    path='T[0][1][3]',
                                    peer_obj=item_1001_peer
                                ),
                                # 1002 moved from index 7 to 4 and completed
                                _make_snapshot(
                                    "TreeItem(👁='▶︎ 📁 Downloading: https://xkcd.daarchive.net/1002/index.html -- Complete')",
                                    path='T[0][1][4]',
                                    peer_obj=item_1002_peer
                                ),
                                # 1003 moved from index 8 to 5 and completed
                                _make_snapshot(
                                    "TreeItem(👁='▶︎ 📁 Downloading: https://xkcd.daarchive.net/1003/index.html -- Complete')",
                                    path='T[0][1][5]',
                                    peer_obj=item_1003_peer
                                ),
                                # 1004 moved from index 9 to 6 and now downloading
                                _make_snapshot(
                                    "TreeItem(👁='▶︎ 📁 Downloading: https://xkcd.daarchive.net/1004/index.html -- Downloading')",
                                    path='T[0][1][6]',
                                    peer_obj=item_1004_peer
                                ),
                                # 1005, 1006 stay queued and shifted up
                                _make_snapshot(
                                    "TreeItem(👁='▶︎ 📁 Downloading: https://xkcd.daarchive.net/1005/index.html -- Queued')",
                                    path='T[0][1][7]',
                                    peer_obj=item_1005_peer
                                ),
                                _make_snapshot(
                                    "TreeItem(👁='▶︎ 📁 Downloading: https://xkcd.daarchive.net/1006/index.html -- Queued')",
                                    path='T[0][1][8]',
                                    peer_obj=item_1006_peer
                                ),
                                # 1007, 1008, 1009 newly visible, queued
                                _make_snapshot(
                                    "TreeItem(👁='▶︎ 📁 Downloading: https://xkcd.daarchive.net/1007/index.html -- Queued')",
                                    path='T[0][1][9]',
                                    peer_obj=item_1007_peer
                                ),
                                _make_snapshot(
                                    "TreeItem(👁='▶︎ 📁 Downloading: https://xkcd.daarchive.net/1008/index.html -- Queued')",
                                    path='T[0][1][10]',
                                    peer_obj=item_1008_peer
                                ),
                                _make_snapshot(
                                    "TreeItem(👁='▶︎ 📁 Downloading: https://xkcd.daarchive.net/1009/index.html -- Queued')",
                                    path='T[0][1][11]',
                                    peer_obj=item_1009_peer
                                ),
                                _make_snapshot(
                                    "TreeItem(👁='— 📄 2,307 more')",
                                    path='T[0][1][12]',
                                    peer_obj=more_end_peer
                                ),
                            ],
                            path='T[0][1]',
                            peer_obj=task_peer
                        ),
                    ],
                    path="T['cr-entity-tree'].Tree[0]",
                    peer_obj=task_peer
                ),
            ],
            path="T['cr-entity-tree'].Tree",
            peer_obj=root_peer
        )
        
        expected_diff_repr_lines = [
            "# S := T['cr-entity-tree'].Tree[0]",
            "S ~ TreeItem(👁='▼ 📂 Downloading group: Comic -- {27→30} of 2,438 item(s) -- {2:18:01→2:19:18} remaining ({3.43→3.47}s/item)')",
            "S[1] ~ TreeItem(👁='▼ 📂 Downloading members of group: Comic -- {27→30} of 2,438 item(s) -- {2:18:01→2:19:18} remaining ({3.43→3.47}s/item)')",
            "S[1][0] ~ TreeItem(👁='— 📄 {22→25} more')",
            "S[1][1] - TreeItem(👁='▶︎ 📁 Downloading: https://xkcd.daarchive.net/2424/index.html -- Complete')",
            "S[1][2] - TreeItem(👁='▶︎ 📁 Downloading: https://xkcd.daarchive.net/2423/index.html -- Complete')",
            "S[1][3] - TreeItem(👁='▶︎ 📁 Downloading: https://xkcd.daarchive.net/2422/index.html -- Complete')",
            'S[1][4..5 → 1..2] = More(Count=2)',
            "S[1][6→3] ~ TreeItem(👁='▶︎ 📁 Downloading: https://xkcd.daarchive.net/1001/index.html -- {Downloading→Complete}')",
            "S[1][7→4] ~ TreeItem(👁='▶︎ 📁 Downloading: https://xkcd.daarchive.net/1002/index.html -- {Queued→Complete}')",
            "S[1][8→5] ~ TreeItem(👁='▶︎ 📁 Downloading: https://xkcd.daarchive.net/1003/index.html -- {Queued→Complete}')",
            "S[1][9→6] ~ TreeItem(👁='▶︎ 📁 Downloading: https://xkcd.daarchive.net/1004/index.html -- {Queued→Downloading}')",
            "S[1][9] + TreeItem(👁='▶︎ 📁 Downloading: https://xkcd.daarchive.net/1007/index.html -- Queued')",
            'S[1][10..11 → 7..8] = More(Count=2)',
            "S[1][10] + TreeItem(👁='▶︎ 📁 Downloading: https://xkcd.daarchive.net/1008/index.html -- Queued')",
            "S[1][11] + TreeItem(👁='▶︎ 📁 Downloading: https://xkcd.daarchive.net/1009/index.html -- Queued')",
            "S[1][12] ~ TreeItem(👁='— 📄 {2,310→2,307} more')",
        ]
        
        with subtests.test(direction='forward'):
            diff = Snapshot.diff(old, new)
            diff_repr = repr(diff)
            actual_diff_repr_lines = diff_repr.split('\n')
            assert actual_diff_repr_lines == expected_diff_repr_lines
        
        expected_reverse_diff_repr_lines = [
            "# S := T['cr-entity-tree'].Tree[0]",
            "S ~ TreeItem(👁='▼ 📂 Downloading group: Comic -- {30→27} of 2,438 item(s) -- {2:19:18→2:18:01} remaining ({3.47→3.43}s/item)')",
            "S[1] ~ TreeItem(👁='▼ 📂 Downloading members of group: Comic -- {30→27} of 2,438 item(s) -- {2:19:18→2:18:01} remaining ({3.47→3.43}s/item)')",
            "S[1][0] ~ TreeItem(👁='— 📄 {25→22} more')",
            'S[1][1..2 → 4..5] = More(Count=2)',
            "S[1][1] + TreeItem(👁='▶︎ 📁 Downloading: https://xkcd.daarchive.net/2424/index.html -- Complete')",
            "S[1][2] + TreeItem(👁='▶︎ 📁 Downloading: https://xkcd.daarchive.net/2423/index.html -- Complete')",
            "S[1][3→6] ~ TreeItem(👁='▶︎ 📁 Downloading: https://xkcd.daarchive.net/1001/index.html -- {Complete→Downloading}')",
            "S[1][3] + TreeItem(👁='▶︎ 📁 Downloading: https://xkcd.daarchive.net/2422/index.html -- Complete')",
            "S[1][4→7] ~ TreeItem(👁='▶︎ 📁 Downloading: https://xkcd.daarchive.net/1002/index.html -- {Complete→Queued}')",
            "S[1][5→8] ~ TreeItem(👁='▶︎ 📁 Downloading: https://xkcd.daarchive.net/1003/index.html -- {Complete→Queued}')",
            "S[1][6→9] ~ TreeItem(👁='▶︎ 📁 Downloading: https://xkcd.daarchive.net/1004/index.html -- {Downloading→Queued}')",
            'S[1][7..8 → 10..11] = More(Count=2)',
            "S[1][9] - TreeItem(👁='▶︎ 📁 Downloading: https://xkcd.daarchive.net/1007/index.html -- Queued')",
            "S[1][10] - TreeItem(👁='▶︎ 📁 Downloading: https://xkcd.daarchive.net/1008/index.html -- Queued')",
            "S[1][11] - TreeItem(👁='▶︎ 📁 Downloading: https://xkcd.daarchive.net/1009/index.html -- Queued')",
            "S[1][12] ~ TreeItem(👁='— 📄 {2,307→2,310} more')",
        ]
        
        with subtests.test(direction='reverse'):
            diff = Snapshot.diff(new, old)
            diff_repr = repr(diff)
            actual_diff_repr_lines = diff_repr.split('\n')
            assert actual_diff_repr_lines == expected_reverse_diff_repr_lines


# === Utility ===

def _make_snapshot(
        desc: str,
        children: list[Snapshot] | None = None,
        path: str = 'T',
        query: str = '',
        accessor: str = 'I',
        peer_obj: object | None = None,
        children_elided: bool = False,
        ) -> Snapshot:
    """Helper to create a Snapshot for testing."""
    return Snapshot(
        peer_description=desc,
        children=children or [],
        path=path,
        query=query,
        peer_accessor=accessor,
        peer_obj=peer_obj,
        children_elided=children_elided,
    )
