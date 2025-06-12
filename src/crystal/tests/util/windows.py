from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import AbstractContextManager, asynccontextmanager, nullcontext
from crystal.browser.new_root_url import (
    NewRootUrlDialog as RealNewRootUrlDialog,
)
from crystal.model import Project
from crystal.task import is_synced_with_scheduler_thread
from crystal.tests.util.controls import (
    click_button, file_dialog_returning, select_menuitem_now, TreeItem,
)
from crystal.tests.util.runner import bg_sleep, pump_wx_events
from crystal.tests.util.tasks import first_task_title_progression
from crystal.tests.util.wait import (
    not_condition, or_condition, tree_has_no_children_condition, wait_for,
    WaitTimedOut, window_condition,
)
from crystal.util.xos import is_mac_os
import os.path
import re
import sys
import tempfile
import traceback
from typing import TYPE_CHECKING
import wx

if TYPE_CHECKING:
    import wx.adv


# ------------------------------------------------------------------------------
# Window & Dialog Abstractions

class OpenOrCreateDialog:
    # NOTE: 10.0 isn't long enough for Windows test runners on GitHub Actions
    _TIMEOUT_FOR_OPEN_MAIN_WINDOW = 12.0
    
    open_or_create_project_dialog: wx.Dialog
    open_as_readonly: wx.CheckBox
    open_button: wx.Button
    create_button: wx.Button
    
    @staticmethod
    async def wait_for(timeout: float | None=None) -> OpenOrCreateDialog:
        self = OpenOrCreateDialog(ready=True)
        open_or_create_project_dialog = await wait_for(
            window_condition('cr-open-or-create-project'),
            timeout=timeout,
            stacklevel_extra=1,
        )  # type: wx.Window
        assert isinstance(open_or_create_project_dialog, wx.Dialog)
        self.open_or_create_project_dialog = open_or_create_project_dialog
        self.open_as_readonly = self.open_or_create_project_dialog.FindWindow(name=
            'cr-open-or-create-project__checkbox')
        assert isinstance(self.open_as_readonly, wx.CheckBox)
        self.open_button = self.open_or_create_project_dialog.FindWindow(id=wx.ID_NO)
        assert isinstance(self.open_button, wx.Button)
        self.create_button = self.open_or_create_project_dialog.FindWindow(id=wx.ID_YES)
        assert isinstance(self.create_button, wx.Button)
        return self
    
    def __init__(self, *, ready: bool=False) -> None:
        assert ready, 'Did you mean to use OpenOrCreateDialog.wait_for()?'
    
    @asynccontextmanager
    async def create(self, 
            project_dirpath: str | None=None,
            *, autoclose: bool=True,
            delete: bool | None=None,
            ) -> AsyncIterator[tuple[MainWindow, Project]]:
        """
        Creates a new project.
        
        If no project_dirpath is provided (i.e. the default) then a project
        will be created in a new temporary directory. That temporary directory
        will be deleted when the project is closed unless delete=False.
        
        If a project_dirpath is provided to an existing empty directory,
        a project will be created in that directory. That directory will
        not be deleted when the project is closed.
        
        The project will be automatically closed when exiting the
        returned context, unless autoclose=False, which leaves the
        MainWindow open.
        """
        if project_dirpath is None:
            if delete is None:
                delete = True
            
            # TODO: After upgrading to Python 3.12+, just use the
            #       "delete" parameter of TemporaryDirectory
            tmpdir_context = (
                tempfile.TemporaryDirectory(  # type: ignore[assignment]
                    suffix='.crystalproj',
                    # NOTE: If a file inside the temporary directory is still open,
                    #       ignore_cleanup_errors=True will prevent Windows from raising,
                    #       at the cost of leaving the temporary directory around
                    ignore_cleanup_errors=True
                ) if delete
                else nullcontext(tempfile.mkdtemp(suffix='.crystalproj'))
            )  # type: AbstractContextManager[str]
            
            with tmpdir_context as project_dirpath:
                assert project_dirpath is not None
                async with self.create(project_dirpath, autoclose=autoclose) as (mw, project2):
                    yield (mw, project2)
            return
        else:
            if delete is not None:
                raise ValueError(
                    'When creating a project in an existing directory, '
                    'the "delete" option should not be used.')
        
        mw = await self.create_and_leave_open(project_dirpath)
        
        project = Project._last_opened_project
        assert project is not None
        
        exc_info_while_close = None
        try:
            yield (mw, project)
        except:
            exc_info_while_close = sys.exc_info()
            raise
        finally:
            if autoclose:
                await mw.close(exc_info_while_close)
    
    async def create_and_leave_open(self, project_dirpath: str) -> MainWindow:
        old_opened_project = Project._last_opened_project  # capture
        try:
            with file_dialog_returning(project_dirpath):
                click_button(self.create_button)
                
                mw = await MainWindow.wait_for(timeout=self._TIMEOUT_FOR_OPEN_MAIN_WINDOW)
                return mw
        except:
            # Close any project that was opened
            new_opened_project = Project._last_opened_project  # capture
            if new_opened_project != old_opened_project:
                if new_opened_project is not None:
                    new_opened_project.close()
            
            raise
    
    @asynccontextmanager
    async def open(self, 
            project_dirpath: str, 
            *, readonly: bool | None=None,
            autoclose: bool=True,
            using_crystalopen: bool=False,
            wait_func: Callable[[], Awaitable[None]] | None=None,
            ) -> AsyncIterator[tuple[MainWindow, Project]]:
        """
        Opens an existing project.
        
        The project will be automatically closed when exiting the
        returned context, unless autoclose=False, which leaves the
        MainWindow open.
        """
        if not os.path.exists(project_dirpath):
            raise ValueError('Project does not exist: ' + project_dirpath)
        
        if readonly is not None:
            self.open_as_readonly.Value = readonly
        
        if using_crystalopen:
            itempath_to_open = os.path.join(project_dirpath, Project._OPENER_DEFAULT_FILENAME)
        else:
            itempath_to_open = project_dirpath
        
        with file_dialog_returning(itempath_to_open):
            click_button(self.open_button)
            
            if wait_func is not None:
                await wait_func()
            mw = await MainWindow.wait_for(timeout=self._TIMEOUT_FOR_OPEN_MAIN_WINDOW)
        
        project = Project._last_opened_project
        assert project is not None
        
        exc_info_while_close = None
        try:
            yield (mw, project)
        except:
            exc_info_while_close = sys.exc_info()
            raise
        finally:
            if autoclose:
                await mw.close(exc_info_while_close)
    
    async def start_opening(self, project_dirpath: str, *, next_window_name: str) -> None:
        with file_dialog_returning(project_dirpath):
            click_button(self.open_button)
            
            await wait_for(
                or_condition(
                    window_condition('cr-opening-project'),
                    window_condition('cr-main-window'),
                    window_condition(next_window_name)),
                stacklevel_extra=1)


class MainWindow:
    _connect_timeout: float | None
    
    main_window: wx.Frame
    entity_tree: EntityTree
    new_root_url_button: wx.Button
    new_group_button: wx.Button
    edit_button: wx.Button
    forget_button: wx.Button
    download_button: wx.Button
    update_members_button: wx.Button
    view_button: wx.Button
    task_tree: wx.TreeCtrl
    preferences_button: wx.Button
    read_write_icon: wx.StaticText
    
    @staticmethod
    async def wait_for(*, timeout: float | None=None) -> MainWindow:
        self = MainWindow(ready=True)
        self._connect_timeout = timeout
        await self._connect()
        return self
    
    async def _connect(self) -> None:
        self.main_window = await wait_for(
            window_condition('cr-main-window'),
            timeout=self._connect_timeout,
            stacklevel_extra=1)
        assert isinstance(self.main_window, wx.Frame)
        entity_tree_window = self.main_window.FindWindow(name='cr-entity-tree')
        assert isinstance(entity_tree_window, wx.TreeCtrl)
        self.entity_tree = EntityTree(entity_tree_window)
        self.new_root_url_button = self.main_window.FindWindow(name='cr-add-url-button')
        assert isinstance(self.new_root_url_button, wx.Button)
        self.new_group_button = self.main_window.FindWindow(name='cr-add-group-button')
        assert isinstance(self.new_group_button, wx.Button)
        self.edit_button = self.main_window.FindWindow(name='cr-edit-button')
        assert isinstance(self.edit_button, wx.Button)
        self.forget_button = self.main_window.FindWindow(name='cr-forget-button')
        assert isinstance(self.forget_button, wx.Button)
        self.download_button = self.main_window.FindWindow(name='cr-download-button')
        assert isinstance(self.download_button, wx.Button)
        self.update_members_button = self.main_window.FindWindow(name='cr-update-members-button')
        assert isinstance(self.update_members_button, wx.Button)
        self.view_button = self.main_window.FindWindow(name='cr-view-button')
        assert isinstance(self.view_button, wx.Button)
        self.task_tree = self.main_window.FindWindow(name='cr-task-tree')
        assert isinstance(self.task_tree, wx.TreeCtrl)
        self.preferences_button = self.main_window.FindWindow(name='cr-preferences-button')
        assert isinstance(self.preferences_button, wx.Button)
        self.read_write_icon = self.main_window.FindWindow(name='cr-read-write-icon')
        assert isinstance(self.read_write_icon, wx.StaticText)
    
    def __init__(self, *, ready: bool=False) -> None:
        assert ready, 'Did you mean to use MainWindow.wait_for()?'
    
    # === Menubar ===
    
    @property
    def entity_menu(self) -> wx.Menu:
        mb = self.main_window.MenuBar
        entity_menu_index = mb.FindMenu('Entity')
        assert entity_menu_index != wx.NOT_FOUND
        entity_menu = mb.GetMenu(entity_menu_index)
        return entity_menu
    
    # === Properties ===
    
    @property
    def readonly(self) -> bool:
        label = self.read_write_icon.Label  # cache
        if label in ['🔒', 'Read only']:
            return True
        elif label in ['✏️', 'Writable']:
            return False
        else:
            raise AssertionError()
    
    # === Operations ===
    
    async def click_download_button(self, *, immediate_finish_ok: bool=False) -> None:
        """
        Clicks the "Download" button and waits for it to finish starting
        a download task.
        """
        task_root_ti = TreeItem.GetRootItem(self.task_tree)
        assert task_root_ti is not None
        
        old_task_count = len(task_root_ti.Children)
        
        click_button(self.download_button)
        def task_count_changed_condition() -> int | None:
            assert task_root_ti is not None
            new_task_count = len(task_root_ti.Children)
            if new_task_count != old_task_count:
                return new_task_count
            else:
                return None
        try:
            await wait_for(task_count_changed_condition, stacklevel_extra=1)
        except WaitTimedOut:
            if immediate_finish_ok:
                # TOOD: We ended up waiting until the entire timeout expired.
                #       Find a more efficient way to detect that the download
                #       started and immediately finished.
                return
            else:
                raise
    
    # === Close ===
    
    CLOSE_TIMEOUT = 4.0
    
    async def close(self, exc_info=None) -> None:
        if is_synced_with_scheduler_thread():
            # Immediately close project
            pass
        else:
            # Try wait for any lingering tasks to complete.
            # 
            # Does workaround: https://github.com/davidfstr/Crystal-Web-Archiver/issues/74
            try:
                await wait_for(
                    tree_has_no_children_condition(self.task_tree),
                    timeout=self.CLOSE_TIMEOUT,  # wait only briefly
                    stacklevel_extra=1)
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
        await self.wait_for_close()
    
    async def close_with_menuitem(self) -> None:
        close_menuitem = self.main_window.MenuBar.FindItemById(wx.ID_CLOSE)
        wx.PostEvent(close_menuitem.Menu, wx.CommandEvent(wx.EVT_MENU.typeId, close_menuitem.Id))
        await self.wait_for_close()
    
    async def wait_for_close(self) -> None:
        await wait_for(lambda: self.main_window.IsBeingDeleted)
        await wait_for(lambda: not self.main_window.IsShown)
        await wait_for(
            not_condition(window_condition('cr-main-window')),
            timeout=4.0,  # 2.0s isn't long enough for macOS test runners on GitHub Actions
            stacklevel_extra=1,
        )
        await OpenOrCreateDialog.wait_for(
            timeout=4.0  # 2.0s isn't long enough for macOS test runners on GitHub Actions
        )
    
    @asynccontextmanager
    async def temporarily_closed(self, project_dirpath: str) -> AsyncIterator[None]:
        await self.close()
        try:
            yield
        finally:
            async with (await OpenOrCreateDialog.wait_for()).open(project_dirpath, autoclose=False):
                pass
            await self._connect()  # reconnect self
    
    async def open_preferences_with_menuitem(self) -> PreferencesDialog:
        prefs_menuitem = self.main_window.MenuBar.FindItemById(wx.ID_PREFERENCES)
        wx.PostEvent(self.main_window, wx.CommandEvent(wx.EVT_MENU.typeId, prefs_menuitem.Id))
        return await PreferencesDialog.wait_for()
    
    async def quit_with_menuitem(self) -> None:
        quit_menuitem = self.main_window.MenuBar.FindItemById(wx.ID_EXIT)
        wx.PostEvent(self.main_window, wx.CommandEvent(wx.EVT_MENU.typeId, quit_menuitem.Id))
        
        await self.wait_for_close()


class NewRootUrlDialog:
    _dialog: wx.Dialog
    _controller: RealNewRootUrlDialog
    url_field: wx.TextCtrl
    url_cleaner_spinner: wx.ActivityIndicator
    name_field: wx.TextCtrl
    ok_button: wx.Button
    cancel_button: wx.Button
    
    download_immediately_checkbox: wx.CheckBox  # or None
    create_group_checkbox: wx.CheckBox  # or None
    
    options_button: wx.Button
    set_as_default_domain_checkbox: wx.CheckBox
    set_as_default_directory_checkbox: wx.CheckBox
    
    @staticmethod
    async def wait_for() -> NewRootUrlDialog:
        self = NewRootUrlDialog(ready=True)
        self._dialog = await wait_for(window_condition('cr-new-root-url-dialog'), stacklevel_extra=1)
        assert isinstance(self._dialog, wx.Dialog)
        assert RealNewRootUrlDialog._last_opened is not None
        self._controller = RealNewRootUrlDialog._last_opened
        self.url_field = self._dialog.FindWindow(name='cr-new-root-url-dialog__url-field')
        assert isinstance(self.url_field, wx.TextCtrl)
        self.url_cleaner_spinner = self._dialog.FindWindow(name='cr-new-root-url-dialog__url-cleaner-spinner')
        assert isinstance(self.url_cleaner_spinner, wx.ActivityIndicator)
        self.name_field = self._dialog.FindWindow(name='cr-new-root-url-dialog__name-field')
        assert isinstance(self.name_field, wx.TextCtrl)
        self.ok_button = self._dialog.FindWindow(id=wx.ID_NEW)
        if self.ok_button is None:
            self.ok_button = self._dialog.FindWindow(id=wx.ID_SAVE)
        assert isinstance(self.ok_button, wx.Button)
        self.cancel_button = self._dialog.FindWindow(id=wx.ID_CANCEL)
        assert isinstance(self.cancel_button, wx.Button)
        
        self.download_immediately_checkbox = self._dialog.FindWindow(name='cr-new-root-url-dialog__download-immediately-checkbox')
        assert (
            self.download_immediately_checkbox is None or
            isinstance(self.download_immediately_checkbox, wx.CheckBox)
        )
        self.create_group_checkbox = self._dialog.FindWindow(name='cr-new-root-url-dialog__create-group-checkbox')
        assert (
            self.create_group_checkbox is None or
            isinstance(self.create_group_checkbox, wx.CheckBox)
        )
        
        self.options_button = self._dialog.FindWindow(id=wx.ID_MORE)
        assert isinstance(self.options_button, wx.Button)
        self.set_as_default_domain_checkbox = self._dialog.FindWindow(name='cr-new-root-url-dialog__set-as-default-domain-checkbox')
        assert isinstance(self.set_as_default_domain_checkbox, wx.CheckBox)
        self.set_as_default_directory_checkbox = self._dialog.FindWindow(name='cr-new-root-url-dialog__set-as-default-directory-checkbox')
        assert isinstance(self.set_as_default_directory_checkbox, wx.CheckBox)
        
        return self
    
    def __init__(self, *, ready: bool=False) -> None:
        assert ready, 'Did you mean to use NewRootUrlDialog.wait_for()?'
    
    @property
    def shown(self) -> bool:
        if self._controller._is_destroying_or_destroyed:
            return False
        return self._dialog.IsShown()
    
    @property
    def url_field_focused(self) -> bool:
        return self._controller._url_field_focused
    
    @property
    def new_options_shown(self) -> bool:
        return (
            self.download_immediately_checkbox is not None and
            self.create_group_checkbox is not None
        )
    
    async def ok(self) -> None:
        click_button(self.ok_button)
        await wait_for(not_condition(window_condition('cr-new-root-url-dialog')), stacklevel_extra=1)
    
    async def cancel(self) -> None:
        click_button(self.cancel_button)
        await wait_for(not_condition(window_condition('cr-new-root-url-dialog')), stacklevel_extra=1)
    
    # === Utility ===
    
    def do_not_download_immediately(self) -> None:
        """
        Configures the URL being created so that it is NOT immediately downloaded
        after creation.
        
        Several tests that create a URL are not interested in the default
        "download immediately" behavior and are simpler to write when there
        is no need to worry about or clean up after a URL is downloaded as
        a side effect of creating it.
        """
        if self.download_immediately_checkbox is None:
            return
        if self.download_immediately_checkbox.Value:
            self.download_immediately_checkbox.Value = False
    
    def do_not_set_default_url_prefix(self) -> None:
        """
        Configures the URL being created to NOT also set it as the default domain.
        
        Several test infrastructure methods (like TreeItem.find_child) are easier
        to use when there is no Default URL Prefix set, so some tests intentionally
        avoid setting a Default URL Prefix.
        """
        click_button(self.options_button)
        if self.set_as_default_domain_checkbox.Value:
            self.set_as_default_domain_checkbox.Value = False
        
        assert False == self.set_as_default_domain_checkbox.Value
        assert False == self.set_as_default_directory_checkbox.Value


class NewGroupDialog:
    _NONE_SOURCE_TITLE = 'none'
    _SOURCE_TITLE_RE = re.compile(r'^(?:[^a-zA-Z0-9]+ )?(.*?)(?: - (.*?))? *$')
    
    name_field: wx.TextCtrl
    pattern_field: wx.TextCtrl
    source_field: wx.Choice
    preview_members_pane: wx.CollapsiblePane | None
    preview_members_list: wx.ListBox
    cancel_button: wx.Button
    ok_button: wx.Button
    
    download_immediately_checkbox: wx.CheckBox  # or None
    
    @staticmethod
    async def wait_for() -> NewGroupDialog:
        self = NewGroupDialog(ready=True)
        add_group_dialog = await wait_for(
            NewGroupDialog.window_condition(),
            timeout=5.0,  # 4.2s observed for macOS test runners on GitHub Actions
            stacklevel_extra=1,
        )  # type: wx.Window
        self.name_field = add_group_dialog.FindWindow(name='cr-new-group-dialog__name-field')
        assert isinstance(self.name_field, wx.TextCtrl)
        self.pattern_field = add_group_dialog.FindWindow(name='cr-new-group-dialog__pattern-field')
        assert isinstance(self.pattern_field, wx.TextCtrl)
        self.source_field = add_group_dialog.FindWindow(name='cr-new-group-dialog__source-field')
        assert isinstance(self.source_field, wx.Choice)
        self.preview_members_pane = add_group_dialog.FindWindow(name='cr-new-group-dialog__preview-members')
        assert (
            self.preview_members_pane is None or
            isinstance(self.preview_members_pane, wx.CollapsiblePane)
        )
        self.preview_members_list = add_group_dialog.FindWindow(name='cr-new-group-dialog__preview-members__list')
        assert isinstance(self.preview_members_list, wx.ListBox)
        self.cancel_button = add_group_dialog.FindWindow(id=wx.ID_CANCEL)
        assert isinstance(self.cancel_button, wx.Button)
        self.ok_button = add_group_dialog.FindWindow(id=wx.ID_NEW)
        if self.ok_button is None:
            self.ok_button = add_group_dialog.FindWindow(id=wx.ID_SAVE)
        assert isinstance(self.ok_button, wx.Button)
        
        self.download_immediately_checkbox = add_group_dialog.FindWindow(name='cr-new-group-dialog__download-immediately-checkbox')
        assert (
            self.download_immediately_checkbox is None or
            isinstance(self.download_immediately_checkbox, wx.CheckBox)
        )
        
        return self
    
    @staticmethod
    def window_condition() -> Callable[[], wx.Window | None]:
        return window_condition('cr-new-group-dialog')
    
    def __init__(self, *, ready: bool=False) -> None:
        assert ready, 'Did you mean to use NewGroupDialog.wait_for()?'
    
    # TODO: Rename -> source_name
    def _get_source(self) -> str | None:
        selection_ci = self.source_field.GetSelection()
        if selection_ci == wx.NOT_FOUND:
            return None
        source_title = self.source_field.GetString(selection_ci)
        if source_title == self._NONE_SOURCE_TITLE:
            return None
        m = self._SOURCE_TITLE_RE.fullmatch(source_title)
        assert m is not None
        source_name = m.group(2)
        if source_name is not None:
            return source_name
        else:
            # If the referenced source has no name, allow referring to it by its display URL
            cur_source_display_url = m.group(1)
            assert cur_source_display_url is not None
            return cur_source_display_url
            
    def _set_source(self, source_name: str | None) -> None:
        if source_name is None:
            selection_ci = 0
        else:
            for (selection_ci, source_title) in enumerate(self.source_field.GetStrings()):
                if selection_ci == 0:
                    continue
                m = self._SOURCE_TITLE_RE.fullmatch(source_title)
                assert m is not None
                cur_source_name = m.group(2)
                if cur_source_name is not None:
                    if cur_source_name == source_name:
                        break
                else:
                    # If the referenced source has no name, allow referring to it by its display URL
                    cur_source_display_url = m.group(1)
                    assert cur_source_display_url is not None
                    if cur_source_display_url == source_name:
                        break
            else:
                raise ValueError(f'Source not found: {source_name}')
        self.source_field.SetSelection(selection_ci)
    source = property(_get_source, _set_source)
    
    @property
    def new_options_shown(self) -> bool:
        return (
            self.download_immediately_checkbox is not None
        )
    
    async def ok(self) -> None:
        click_button(self.ok_button)
        await wait_for(not_condition(window_condition('cr-new-group-dialog')), stacklevel_extra=1)
    
    async def cancel(self) -> None:
        click_button(self.cancel_button)
        await wait_for(not_condition(window_condition('cr-new-group-dialog')), stacklevel_extra=1)


class PreferencesDialog:
    html_parser_field: wx.Choice
    stale_before_checkbox: wx.CheckBox
    stale_before_date_picker: wx.adv.DatePickerCtrl
    cookie_field: wx.ComboBox
    ok_button: wx.Button
    
    @staticmethod
    async def wait_for() -> PreferencesDialog:
        import wx.adv
        
        self = PreferencesDialog(ready=True)
        preferences_dialog = await wait_for(
            window_condition('cr-preferences-dialog'),
            timeout=4.0,  # 2.0s isn't long enough for macOS test runners on GitHub Actions
            stacklevel_extra=1,
        )  # type: wx.Window
        self.html_parser_field = preferences_dialog.FindWindow(name=
            'cr-preferences-dialog__html-parser-field')
        assert isinstance(self.html_parser_field, wx.Choice)
        self.stale_before_checkbox = preferences_dialog.FindWindow(name=
            'cr-preferences-dialog__stale-before-checkbox')
        assert isinstance(self.stale_before_checkbox, wx.CheckBox)
        self.stale_before_date_picker = preferences_dialog.FindWindow(name=
            'cr-preferences-dialog__stale-before-date-picker')
        assert isinstance(self.stale_before_date_picker, wx.adv.DatePickerCtrl)
        self.cookie_field = preferences_dialog.FindWindow(name=
            'cr-preferences-dialog__cookie-field')
        assert isinstance(self.cookie_field, wx.ComboBox)
        self.ok_button = preferences_dialog.FindWindow(id=wx.ID_OK)
        assert isinstance(self.ok_button, wx.Button)
        return self
    
    def __init__(self, *, ready: bool=False) -> None:
        assert ready, 'Did you mean to use PreferencesDialog.wait_for()?'
    
    async def ok(self) -> None:
        click_button(self.ok_button)
        await wait_for(not_condition(window_condition('cr-preferences-dialog')), stacklevel_extra=1)


# ------------------------------------------------------------------------------
# Panel Abstractions

class EntityTree:
    def __init__(self, window: wx.TreeCtrl) -> None:
        self.window = window
    
    async def get_tree_item_icon_tooltip(self, tree_item: TreeItem) -> str | None:
        if tree_item.tree != self.window:
            raise ValueError()
        return tree_item.Tooltip('icon')
    
    @staticmethod
    async def assert_tree_item_icon_tooltip_contains(ti: TreeItem, value: str) -> None:
        tooltip = await (EntityTree(ti.tree).get_tree_item_icon_tooltip(ti))
        assert tooltip is not None and value in tooltip, \
            f'Expected tooltip to contain {value!r}, but it was: {tooltip!r}'
    
    async def set_default_domain_to_entity_at_tree_item(self, tree_item: TreeItem) -> None:
        """
        Raises:
        * MenuitemMissingError
        * MenuitemDisabledError
        """
        await self._choose_action_for_entity_at_tree_item(tree_item, 'Set As Default Domain')
    
    async def set_default_directory_to_entity_at_tree_item(self, tree_item: TreeItem) -> None:
        """
        Raises:
        * MenuitemMissingError
        * MenuitemDisabledError
        """
        await self._choose_action_for_entity_at_tree_item(tree_item, 'Set As Default Directory')
    
    async def clear_default_domain_from_entity_at_tree_item(self, tree_item: TreeItem) -> None:
        """
        Raises:
        * MenuitemMissingError
        * MenuitemDisabledError
        """
        await self._choose_action_for_entity_at_tree_item(tree_item, 'Clear Default Domain')
    
    async def clear_default_directory_from_entity_at_tree_item(self, tree_item: TreeItem) -> None:
        """
        Raises:
        * MenuitemMissingError
        * MenuitemDisabledError
        """
        await self._choose_action_for_entity_at_tree_item(tree_item, 'Clear Default Directory')
    
    async def _choose_action_for_entity_at_tree_item(self,
            tree_item: TreeItem,
            action_prefix: str) -> None:
        """
        Raises:
        * MenuitemMissingError
        * MenuitemDisabledError
        """
        def show_popup(menu: wx.Menu) -> None:
            try:
                (set_prefix_menuitem,) = (
                    mi for mi in menu.MenuItems
                    if mi.ItemLabelText.startswith(action_prefix)
                )
            except ValueError:  # not enough values to unpack
                raise MenuitemMissingError()
            if not set_prefix_menuitem.Enabled:
                raise MenuitemDisabledError()
            select_menuitem_now(menu, set_prefix_menuitem.Id)
        await tree_item.right_click_showing_popup_menu(show_popup)


class MenuitemMissingError(ValueError):
    pass


class MenuitemDisabledError(ValueError):
    pass


# ------------------------------------------------------------------------------
