from __future__ import annotations

from contextlib import asynccontextmanager

from crystal.tests.util.controls import (
    click_button, file_dialog_returning, package_dialog_returning,
    TreeItem
)
from crystal.tests.util.runner import bg_sleep, pump_wx_events
from crystal.tests.util.screenshots import screenshot_if_raises
from crystal.tests.util.tasks import first_task_title_progression
from crystal.tests.util.wait import (
    tree_has_no_children_condition,
    wait_for, WaitTimedOut, window_condition, not_condition
)
from crystal.util.xos import is_mac_os
import sys
import tempfile
import traceback
from typing import AsyncIterator, Optional, Tuple, TYPE_CHECKING
import wx

if TYPE_CHECKING:
    import wx.adv


# ------------------------------------------------------------------------------
# Window & Dialog Abstractions

class OpenOrCreateDialog:
    # NOTE: 8.0 isn't long enough for Windows test runners on GitHub Actions
    _TIMEOUT_FOR_OPEN_MAIN_WINDOW = 10.0
    
    open_or_create_project_dialog: wx.Dialog
    open_as_readonly: wx.CheckBox
    open_button: wx.Button
    create_button: wx.Button
    
    @staticmethod
    async def wait_for() -> OpenOrCreateDialog:
        self = OpenOrCreateDialog(ready=True)
        open_or_create_project_dialog = await wait_for(window_condition(
            'cr-open-or-create-project'))  # type: wx.Window
        assert isinstance(open_or_create_project_dialog, wx.Dialog)
        self.open_or_create_project_dialog = open_or_create_project_dialog
        self.open_as_readonly = self.open_or_create_project_dialog.FindWindowByName(
            'cr-open-or-create-project__checkbox')
        assert isinstance(self.open_as_readonly, wx.CheckBox)
        self.open_button = self.open_or_create_project_dialog.FindWindowById(wx.ID_YES)
        assert isinstance(self.open_button, wx.Button)
        self.create_button = self.open_or_create_project_dialog.FindWindowById(wx.ID_NO)
        assert isinstance(self.create_button, wx.Button)
        return self
    
    def __init__(self, *, ready: bool=False) -> None:
        assert ready, 'Did you mean to use OpenOrCreateDialog.wait_for()?'
    
    @asynccontextmanager
    async def create(self, 
            project_dirpath: Optional[str]=None
            ) -> AsyncIterator[Tuple[MainWindow, str]]:
        if project_dirpath is None:
            with tempfile.TemporaryDirectory(suffix='.crystalproj') as project_dirpath:
                assert project_dirpath is not None
                async with self.create(project_dirpath) as (mw, project_dirpath):
                    yield (mw, project_dirpath)
            return
        
        mw = await self.create_and_leave_open(project_dirpath)
        
        exc_info_while_close = None
        try:
            yield (mw, project_dirpath)
        except:
            exc_info_while_close = sys.exc_info()
            raise
        finally:
            await mw.close(exc_info_while_close)
    
    async def create_and_leave_open(self, project_dirpath: str) -> MainWindow:
        with file_dialog_returning(project_dirpath):
            click_button(self.create_button)
            
            with screenshot_if_raises():
                mw = await MainWindow.wait_for(timeout=self._TIMEOUT_FOR_OPEN_MAIN_WINDOW)
        return mw
    
    @asynccontextmanager
    async def open(self, 
            project_dirpath: str, 
            *, readonly: Optional[bool]=None,
            autoclose: bool=True,
            ) -> AsyncIterator[MainWindow]:
        if readonly is not None:
            self.open_as_readonly.Value = readonly
        
        with package_dialog_returning(project_dirpath):
            click_button(self.open_button)
            
            with screenshot_if_raises():
                mw = await MainWindow.wait_for(timeout=self._TIMEOUT_FOR_OPEN_MAIN_WINDOW)
        
        exc_info_while_close = None
        try:
            yield mw
        except:
            exc_info_while_close = sys.exc_info()
            raise
        finally:
            if autoclose:
                await mw.close(exc_info_while_close)


class MainWindow:
    _connect_timeout: Optional[float]
    
    main_window: wx.Frame
    entity_tree: 'EntityTree'
    add_url_button: wx.Button
    add_group_button: wx.Button
    forget_button: wx.Button
    download_button: wx.Button
    update_membership_button: wx.Button
    view_button: wx.Button
    task_tree: wx.TreeCtrl
    preferences_button: wx.Button
    read_write_icon: wx.StaticText
    
    @staticmethod
    async def wait_for(*, timeout: Optional[float]=None) -> MainWindow:
        self = MainWindow(ready=True)
        self._connect_timeout = timeout
        await self._connect()
        return self
    
    async def _connect(self) -> None:
        self.main_window = await wait_for(
            window_condition('cr-main-window'),
            timeout=self._connect_timeout)
        assert isinstance(self.main_window, wx.Frame)
        entity_tree_window = self.main_window.FindWindowByName('cr-entity-tree')
        assert isinstance(entity_tree_window, wx.TreeCtrl)
        self.entity_tree = EntityTree(entity_tree_window)
        self.add_url_button = self.main_window.FindWindowByName('cr-add-url-button')
        assert isinstance(self.add_url_button, wx.Button)
        self.add_group_button = self.main_window.FindWindowByName('cr-add-group-button')
        assert isinstance(self.add_group_button, wx.Button)
        self.forget_button = self.main_window.FindWindowByName('cr-forget-button')
        assert isinstance(self.forget_button, wx.Button)
        self.download_button = self.main_window.FindWindowByName('cr-download-button')
        assert isinstance(self.download_button, wx.Button)
        self.update_membership_button = self.main_window.FindWindowByName('cr-update-membership-button')
        assert isinstance(self.update_membership_button, wx.Button)
        self.view_button = self.main_window.FindWindowByName('cr-view-button')
        assert isinstance(self.view_button, wx.Button)
        self.task_tree = self.main_window.FindWindowByName('cr-task-tree')
        assert isinstance(self.task_tree, wx.TreeCtrl)
        self.preferences_button = self.main_window.FindWindowByName('cr-preferences-button')
        assert isinstance(self.preferences_button, wx.Button)
        self.read_write_icon = self.main_window.FindWindowByName('cr-read-write-icon')
        assert isinstance(self.read_write_icon, wx.StaticText)
    
    def __init__(self, *, ready: bool=False) -> None:
        assert ready, 'Did you mean to use MainWindow.wait_for()?'
    
    @property
    def readonly(self) -> bool:
        label = self.read_write_icon.Label  # cache
        if label in ['🔒', 'Read only']:
            return True
        elif label in ['✏️', 'Writable']:
            return False
        else:
            raise AssertionError()
    
    async def close(self, exc_info=None) -> None:
        # Try wait for any lingering tasks to complete.
        # 
        # Does workaround: https://github.com/davidfstr/Crystal-Web-Archiver/issues/74
        try:
            await wait_for(
                tree_has_no_children_condition(self.task_tree),
                timeout=4.0)  # wait only briefly
        except WaitTimedOut:
            first_task_title = first_task_title_progression(self.task_tree)()
            print(f'*** MainWindow: Closing while tasks are still running. May deadlock! Current task: {first_task_title}')
            
            # Print traceback or current exception that is being handled immediately
            # because impending deadlock may prevent traceback from being printed
            # in the usual manner
            if exc_info is None:
                traceback.print_stack()
            else:
                traceback.print_exception(*exc_info)
            
            # (continue)
        
        self.main_window.Close()
        await wait_for(lambda: self.main_window.IsBeingDeleted)
        await wait_for(lambda: not self.main_window.IsShown)
        await wait_for(not_condition(window_condition('cr-main-window')))
        await OpenOrCreateDialog.wait_for()
    
    @asynccontextmanager
    async def temporarily_closed(self, project_dirpath: str) -> AsyncIterator[None]:
        await self.close()
        try:
            yield
        finally:
            async with (await OpenOrCreateDialog.wait_for()).open(project_dirpath, autoclose=False):
                pass
            await self._connect()  # reconnect self


class AddUrlDialog:
    name_field: wx.TextCtrl
    url_field: wx.TextCtrl
    ok_button: wx.Button
    
    @staticmethod
    async def wait_for() -> AddUrlDialog:
        self = AddUrlDialog(ready=True)
        add_url_dialog = await wait_for(window_condition('cr-add-url-dialog'))  # type: wx.Window
        self.name_field = add_url_dialog.FindWindowByName('cr-add-url-dialog__name-field')
        assert isinstance(self.name_field, wx.TextCtrl)
        self.url_field = add_url_dialog.FindWindowByName('cr-add-url-dialog__url-field')
        assert isinstance(self.url_field, wx.TextCtrl)
        self.ok_button = add_url_dialog.FindWindowById(wx.ID_OK)
        assert isinstance(self.ok_button, wx.Button)
        return self
    
    def __init__(self, *, ready: bool=False) -> None:
        assert ready, 'Did you mean to use AddUrlDialog.wait_for()?'
    
    async def ok(self) -> None:
        click_button(self.ok_button)
        await wait_for(not_condition(window_condition('cr-add-url-dialog')))


class AddGroupDialog:
    name_field: wx.TextCtrl
    pattern_field: wx.TextCtrl
    source_field: wx.Choice
    preview_members_pane: wx.CollapsiblePane
    preview_members_list: wx.ListBox
    ok_button: wx.Button
    
    @staticmethod
    async def wait_for() -> AddGroupDialog:
        self = AddGroupDialog(ready=True)
        add_group_dialog = await wait_for(window_condition('cr-add-group-dialog'))  # type: wx.Window
        self.name_field = add_group_dialog.FindWindowByName('cr-add-group-dialog__name-field')
        assert isinstance(self.name_field, wx.TextCtrl)
        self.pattern_field = add_group_dialog.FindWindowByName('cr-add-group-dialog__pattern-field')
        assert isinstance(self.pattern_field, wx.TextCtrl)
        self.source_field = add_group_dialog.FindWindowByName('cr-add-group-dialog__source-field')
        assert isinstance(self.source_field, wx.Choice)
        self.preview_members_pane = add_group_dialog.FindWindowByName('cr-add-group-dialog__preview-members')
        assert isinstance(self.preview_members_pane, wx.CollapsiblePane)
        self.preview_members_list = add_group_dialog.FindWindowByName('cr-add-group-dialog__preview-members__list')
        assert isinstance(self.preview_members_list, wx.ListBox)
        self.ok_button = add_group_dialog.FindWindowById(wx.ID_OK)
        assert isinstance(self.ok_button, wx.Button)
        return self
    
    def __init__(self, *, ready: bool=False) -> None:
        assert ready, 'Did you mean to use AddGroupDialog.wait_for()?'
    
    def _get_source(self) -> Optional[str]:
        selection_ci = self.source_field.GetSelection()
        if selection_ci == wx.NOT_FOUND:
            return None
        return self.source_field.GetString(selection_ci)
    def _set_source(self, source_title: str) -> None:
        selection_ci = self.source_field.GetStrings().index(source_title)
        self.source_field.SetSelection(selection_ci)
    source = property(_get_source, _set_source)
    
    async def ok(self) -> None:
        click_button(self.ok_button)
        await wait_for(not_condition(window_condition('cr-add-group-dialog')))


class PreferencesDialog:
    stale_before_checkbox: wx.CheckBox
    stale_before_date_picker: 'wx.adv.DatePickerCtrl'
    cookie_field: wx.ComboBox
    ok_button: wx.Button
    
    @staticmethod
    async def wait_for() -> PreferencesDialog:
        import wx.adv
        
        self = PreferencesDialog(ready=True)
        preferences_dialog = await wait_for(window_condition('cr-preferences-dialog'))  # type: wx.Window
        self.stale_before_checkbox = preferences_dialog.FindWindowByName('cr-preferences-dialog__stale-before-checkbox')
        assert isinstance(self.stale_before_checkbox, wx.CheckBox)
        self.stale_before_date_picker = preferences_dialog.FindWindowByName('cr-preferences-dialog__stale-before-date-picker')
        assert isinstance(self.stale_before_date_picker, wx.adv.DatePickerCtrl)
        self.cookie_field = preferences_dialog.FindWindowByName('cr-preferences-dialog__cookie-field')
        assert isinstance(self.cookie_field, wx.ComboBox)
        self.ok_button = preferences_dialog.FindWindowById(wx.ID_OK)
        assert isinstance(self.ok_button, wx.Button)
        return self
    
    def __init__(self, *, ready: bool=False) -> None:
        assert ready, 'Did you mean to use PreferencesDialog.wait_for()?'
    
    async def ok(self) -> None:
        click_button(self.ok_button)
        await wait_for(not_condition(window_condition('cr-preferences-dialog')))


# ------------------------------------------------------------------------------
# Panel Abstractions

class EntityTree:
    def __init__(self, window: wx.TreeCtrl) -> None:
        self.window = window
    
    async def get_tree_item_icon_tooltip(self, tree_item: TreeItem) -> Optional[str]:
        from crystal.browser.entitytree import GetTooltipEvent
        
        if tree_item.tree != self.window:
            raise ValueError()
        
        event = GetTooltipEvent(tree_item_id=tree_item.id, tooltip_cell=[Ellipsis])
        wx.PostEvent(self.window, event)  # callee should set: event.tooltip_cell[0]
        # Try multiple times, since Windows sometimes doesn't seem to pump
        # all events immediately
        for _ in range(3):
            await pump_wx_events()
            if event.tooltip_cell[0] is not Ellipsis:
                break
            await bg_sleep(50/1000)
        else:
            raise AssertionError('GetTooltipEvent did not return tooltip')
        return event.tooltip_cell[0]
    
    async def set_default_url_prefix_to_resource_at_tree_item(self, tree_item: TreeItem) -> None:
        # TODO: Publicize constant
        from crystal.browser.entitytree import _ID_SET_PREFIX
        
        if tree_item.tree != self.window:
            raise ValueError()
        
        # Simulate right-click on tree node, opening (and closing) a menu
        wx.PostEvent(self.window, wx.TreeEvent(wx.EVT_TREE_ITEM_RIGHT_CLICK.typeId, self.window, tree_item.id))
        await pump_wx_events()
        
        # Simulate click on menuitem "Set As Default URL Prefix"
        wx.PostEvent(self.window, wx.MenuEvent(type=wx.EVT_MENU.typeId, id=_ID_SET_PREFIX, menu=None))
        await pump_wx_events()


# ------------------------------------------------------------------------------
