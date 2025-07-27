from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager, nullcontext
import sys
from crystal import __version__ as crystal_version
from crystal import APP_NAME
from crystal.browser.entitytree import (
    EntityTree, ResourceGroupNode, RootResourceNode,
)
from crystal.browser.icons import TREE_NODE_ICONS
from crystal.browser.new_group import NewGroupDialog
from crystal.browser.new_root_url import ChangePrefixCommand, NewRootUrlDialog
from crystal.browser.preferences import PreferencesDialog
from crystal.browser.tasktree import TaskTree
from crystal.model import (
    Project, ProjectReadOnlyError, Resource, ResourceGroup, ResourceGroupSource, RootResource,
)
from crystal.progress import (
    CancelLoadUrls, CancelSaveAs, DummyOpenProjectProgressListener,
    OpenProjectProgressListener, SaveAsProgressDialog,
)
from crystal.server import ProjectServer
from crystal.task import DownloadResourceGroupMembersTask, RootTask
from crystal.ui.actions import Action
from crystal.ui.BetterMessageDialog import BetterMessageDialog
from crystal.ui.log_drawer import LogDrawer
from crystal.ui.tree import DEFAULT_FOLDER_ICON_SET
from crystal.util.bulkheads import (
    capture_crashes_to, capture_crashes_to_stderr,
)
from crystal.util.ellipsis import EllipsisType
from crystal.util.finderinfo import get_hide_file_extension
from crystal.util.test_mode import tests_are_running
from crystal.util.unicode_labels import decorate_label
from crystal.util.url_prefix import (
    get_url_directory_prefix_for, get_url_domain_prefix_for,
)
from crystal.util.quitting import set_is_quitting
from crystal.util.wx_bind import bind
from crystal.util.wx_dialog import (
    position_dialog_initially, set_dialog_or_frame_icon_if_appropriate,
    ShowModal,
)
from crystal.util.wx_timer import Timer, TimerError
from crystal.util.xos import (
    is_kde_or_non_gnome, is_linux, is_mac_os, is_windows, mac_version,
)
from crystal.util.xsqlite3 import (
    is_database_closed_error, is_database_gone_error,
)
from crystal.util.xthreading import (
    bg_call_later, fg_affinity, fg_call_and_wait, fg_call_later, fg_trampoline, fg_wait_for,
)
from functools import partial
import os
import sqlite3
import time
import traceback
from typing import Optional
import webbrowser
import wx

_WINDOW_INNER_PADDING = 10


class MainWindow:
    _AUTOHIBERNATE_PERIOD = 1000 * 60 * 5  # 5 min, in milliseconds
    
    project: Project
    _frame: wx.Frame
    entity_tree: EntityTree
    task_tree: TaskTree
    
    # NOTE: Only changed when tests are running
    _last_created: 'Optional[MainWindow]'=None
    
    @fg_affinity
    def __init__(self,
            project: Project,
            progress_listener: OpenProjectProgressListener | None=None,
            ) -> None:
        """
        Creates a MainWindow that displays, listens to, and takes ownership of the given Project.
        
        When the MainWindow is closed, the Project will be closed automatically.
        
        If this constructor raises an exception the Project will still be closed, immediately.
        
        Raises:
        * CancelOpenProject
        """
        if progress_listener is None:
            progress_listener = DummyOpenProjectProgressListener()
        
        self._closed = False
        self.project = project
        self._log_drawer = None  # type: Optional[LogDrawer]
        self._project_server = None  # type: Optional[ProjectServer]
        
        try:
            self._create_actions()
            
            frame_title = self._calculate_frame_title(project)
            
            # TODO: Rename: raw_frame -> frame,
            #               frame -> frame_content
            raw_frame = wx.Frame(None, title=frame_title, name='cr-main-window')
            try:
                # macOS: Define proxy icon beside the filename in the titlebar
                raw_frame.SetRepresentedFilename(project.path)
                # Define frame icon, if appropriate
                set_dialog_or_frame_icon_if_appropriate(raw_frame)
                
                # 1. Define *single* child with full content of the wx.Frame,
                #    so that LogDrawer can be created for this window later
                # 2. Add all controls to a root wx.Panel rather than to the
                #    raw wx.Frame directly so that tab traversal between child
                #    components works correctly.
                frame = wx.Panel(raw_frame)
                
                frame_sizer = wx.BoxSizer(wx.VERTICAL)
                frame.SetSizer(frame_sizer)
                
                splitter = wx.SplitterWindow(frame, style=wx.SP_3D|wx.SP_NO_XP_THEME|wx.SP_LIVE_UPDATE, name='cr-main-window-splitter')
                splitter.SetSashGravity(1.0)
                splitter.SetMinimumPaneSize(20)
                
                entity_pane = self._create_entity_pane(splitter, progress_listener)
                task_pane = self._create_task_pane(splitter)
                splitter.SplitHorizontally(entity_pane, task_pane, -task_pane.GetBestSize().height)
                
                frame_sizer.Add(splitter, proportion=1, flag=wx.EXPAND)
                
                frame_sizer.Add(
                    self._create_status_bar(frame),
                    proportion=0,
                    flag=wx.EXPAND)
                
                raw_frame.MenuBar = self._create_menu_bar(raw_frame)
                
                bind(raw_frame, wx.EVT_CLOSE, self._on_close_frame)
                
                frame.Fit()
                raw_frame.Fit()  # NOTE: Must Fit() before Show() here so that wxGTK actually fits correctly
                raw_frame.Show(True)
                
                # Define minimum size for main window
                min_width = entity_pane.GetBestSize().Width
                min_height = task_pane.GetBestSize().Height * 2
                raw_frame.MinSize = wx.Size(min_width, min_height)
                
                self._frame = raw_frame
            except:
                raw_frame.Destroy()
                raise
            
            # Start listening to project events
            project.listeners.append(self)
            
            self._unhibernate()
            
            # Auto-hibernate every few minutes, in case Crystal crashes
            self._autohibernate_timer = None
            try:
                self._autohibernate_timer = Timer(self._hibernate, self._AUTOHIBERNATE_PERIOD)
            except TimerError:
                pass
            
            # Export reference to self, if running tests
            if tests_are_running():
                MainWindow._last_created = self
        except:
            project.close()
            raise
    
    @staticmethod
    def _calculate_frame_title(project) -> str:
        frame_title: str
        filename_with_ext = os.path.basename(project.path)
        (filename_without_ext, filename_ext) = os.path.splitext(filename_with_ext)
        if project.is_untitled:
            filename_without_ext = 'Untitled Project'  # reinterpret
        if is_windows() or is_kde_or_non_gnome():
            frame_title = f'{filename_without_ext} - {APP_NAME}'
        else:  # is_mac_os(); other
            if project.is_untitled:
                # Never show extension for untitled projects
                extension_visible = False
            elif not os.path.exists(project.path):
                print(f'*** Tried to calculate frame title for project not on disk: {project.path}', file=sys.stderr)
                extension_visible = False
            else:
                extension_visible = (
                    not get_hide_file_extension(project.path) if is_mac_os()
                    else True
                )
            if extension_visible:
                frame_title = filename_with_ext
            else:
                frame_title = filename_without_ext
        return frame_title
    
    @property
    def _readonly(self) -> bool:
        return self.project.readonly
    
    # === Actions ===
    
    def _create_actions(self) -> None:
        # File
        self._new_project_action = Action(
            wx.ID_NEW,
            '&New Project...',
            wx.AcceleratorEntry(wx.ACCEL_CTRL, ord('N')),
            # TODO: Support multiple open projects
            action_func=None,
            enabled=False)
        self._open_project_action = Action(
            wx.ID_OPEN,
            '&Open Project...',
            wx.AcceleratorEntry(wx.ACCEL_CTRL, ord('O')),
            # TODO: Support multiple open projects
            action_func=None,
            enabled=False)
        self._close_project_action = Action(
            wx.ID_CLOSE,
            '',
            wx.AcceleratorEntry(wx.ACCEL_CTRL, ord('W')),
            action_func=self._on_close_window,
            enabled=True)
        (s_label, s_enabled) = self._calculate_save_action_properties()
        self._save_project_action = Action(
            wx.ID_SAVE,
            s_label,
            wx.AcceleratorEntry(wx.ACCEL_CTRL, ord('S')),
            action_func=self._on_save_as_project,
            enabled=s_enabled)
        self._save_as_project_action = Action(
            wx.ID_SAVEAS,
            '',
            wx.AcceleratorEntry(wx.ACCEL_CTRL|wx.ACCEL_SHIFT, ord('S')),
            action_func=self._on_save_as_project,
            enabled=True)
        self._quit_action = Action(
            wx.ID_EXIT,
            '',
            wx.AcceleratorEntry(wx.ACCEL_CTRL, ord('Q')),
            # NOTE: Action is bound to self._on_quit later manually
            action_func=None,
            enabled=True)
        
        # Edit
        if is_mac_os():
            mv = mac_version()
            if mv is not None and mv >= [13]:
                preferences_label = 'Settings...'
            else:
                preferences_label = 'Preferences...'
        else:
            preferences_label = ''  # OS default
        self._preferences_action = Action(
            wx.ID_PREFERENCES,
            preferences_label,
            wx.AcceleratorEntry(wx.ACCEL_CTRL, ord(',')),
            # NOTE: Action is bound to self._on_preferences later manually
            action_func=None,
            enabled=True,
            button_label=decorate_label('⚙️', '&Preferences...', ''))
        
        # Entity
        self._new_root_url_action = Action(wx.ID_ANY,
            'New &Root URL...',
            wx.AcceleratorEntry(wx.ACCEL_CTRL, ord('R')),
            self._on_new_root_url,
            enabled=(not self._readonly),
            button_bitmap=TREE_NODE_ICONS()['entitytree_root_resource'],
            button_label='New &Root URL...')
        self._new_group_action = Action(wx.ID_ANY,
            'New &Group...',
            wx.AcceleratorEntry(wx.ACCEL_CTRL, ord('G')),
            self._on_new_group,
            enabled=(not self._readonly),
            button_bitmap=dict(DEFAULT_FOLDER_ICON_SET())[wx.TreeItemIcon_Normal],
            button_label='New &Group...')
        self._edit_action = Action(wx.ID_ANY,
            '&Edit...',
            accel=wx.AcceleratorEntry(wx.ACCEL_NORMAL, wx.WXK_RETURN),
            action_func=self._on_edit_entity,
            enabled=False,
            button_label=decorate_label('✏️', '&Edit...', ''))
        self._forget_action = Action(wx.ID_ANY,
            '&Forget',
            wx.AcceleratorEntry(wx.ACCEL_CTRL, wx.WXK_BACK),
            self._on_forget_entity,
            enabled=False,
            button_label=decorate_label('✖️', '&Forget', ''))
        self._download_action = Action(wx.ID_ANY,
            '&Download',
            wx.AcceleratorEntry(wx.ACCEL_CTRL, wx.WXK_RETURN),
            self._on_download_entity,
            enabled=False,
            button_label=decorate_label('⬇', '&Download', ''))
        self._update_members_action = Action(wx.ID_ANY,
            'Update &Members',
            accel=None,
            action_func=self._on_update_group_members,
            enabled=False,
            button_label=decorate_label('🔎', 'Update &Members', ' '))
        self._view_action = Action(wx.ID_ANY,
            '&View',
            # TODO: Consider adding Space as a alternate accelerator
            #wx.AcceleratorEntry(wx.ACCEL_NORMAL, wx.WXK_SPACE),
            wx.AcceleratorEntry(wx.ACCEL_CTRL|wx.ACCEL_SHIFT, ord('O')),
            self._on_view_entity,
            enabled=False,
            button_label=decorate_label('👀', '&View', ' '))
        
        # HACK: Gather all actions indirectly by inspecting fields
        self._actions = [a for a in self.__dict__.values() if isinstance(a, Action)]
    
    def _calculate_save_action_properties(self) -> tuple[str, bool]:
        label = '&Save...' if self.project.is_untitled else ''
        enabled = self.project.is_untitled
        return (label, enabled)
    
    # === Menubar ===
    
    def _create_menu_bar(self, raw_frame: wx.Frame) -> wx.MenuBar:
        file_menu = wx.Menu()
        self._new_project_action.append_menuitem_to(file_menu)
        self._open_project_action.append_menuitem_to(file_menu)
        file_menu.AppendSeparator()
        self._close_project_action.append_menuitem_to(file_menu)
        self._save_project_action.append_menuitem_to(file_menu)
        self._save_as_project_action.append_menuitem_to(file_menu)
        # Append Quit menuitem
        if True:
            self._quit_action.append_menuitem_to(file_menu)
            # NOTE: Can only intercept wx.EVT_MENU for wx.ID_EXIT on an wx.Frame
            #       on macOS. In particular cannot intercept on the File wx.Menu.
            bind(raw_frame, wx.EVT_MENU, self._on_quit)
        
        edit_menu = wx.Menu()
        edit_menu.Append(wx.ID_UNDO, '').Enabled = False
        edit_menu.Append(wx.ID_REDO, '').Enabled = False
        edit_menu.AppendSeparator()
        edit_menu.Append(wx.ID_CUT, '').Enabled = False
        edit_menu.Append(wx.ID_COPY, '').Enabled = False
        edit_menu.Append(wx.ID_PASTE, '').Enabled = False
        # Append Preferences menuitem
        if True:
            if not is_mac_os():
                edit_menu.AppendSeparator()
            # NOTE: On macOS the Preferences menuitem will actually be positioned
            #       in the [Application Name] menu rather than the Edit menu.
            self._preferences_action.append_menuitem_to(edit_menu)
            # NOTE: Can only intercept wx.EVT_MENU for wx.ID_PREFERENCES on an wx.Frame
            #       on macOS. In particular cannot intercept on the Edit wx.Menu.
            bind(raw_frame, wx.EVT_MENU, self._on_preferences)
        
        self._entity_menu = entity_menu = wx.Menu()
        self._new_root_url_action.append_menuitem_to(entity_menu)
        self._new_group_action.append_menuitem_to(entity_menu)
        self._edit_action.append_menuitem_to(entity_menu)
        self._forget_action.append_menuitem_to(entity_menu)
        entity_menu.AppendSeparator()
        self._download_action.append_menuitem_to(entity_menu)
        self._update_members_action.append_menuitem_to(entity_menu)
        self._view_action.append_menuitem_to(entity_menu)
        entity_menu.AppendSeparator()
        if True:
            (cup_mis, on_attach_menuitems) = \
                self.entity_tree.create_change_url_prefix_menuitems_for(
                    node=None, menu_type='top_level')
            for mi in cup_mis:
                entity_menu.Append(mi)
            on_attach_menuitems()
            self._change_url_prefix_menuitems = cup_mis
            
            bind(entity_menu, wx.EVT_MENU_OPEN, self._on_entity_menu_open)
            bind(entity_menu, wx.EVT_MENU, self._on_change_url_prefix_menuitem_selected)
        
        menubar = wx.MenuBar()
        menubar.Append(file_menu, 'File')
        menubar.Append(edit_menu, 'Edit')
        menubar.Append(entity_menu, 'Entity')
        return menubar
    
    def _on_entity_menu_open(self, event: wx.MenuEvent) -> None:
        menu = self._entity_menu  # cache
        
        # Locate old _change_url_prefix_menuitems
        assert len(self._change_url_prefix_menuitems) >= 1
        first_old_mi = self._change_url_prefix_menuitems[0]
        (first_old_mi2, first_old_mi_offset) = \
            menu.FindChildItem(first_old_mi.Id)
        assert first_old_mi2 == first_old_mi
        
        # Remove/dispose old _change_url_prefix_menuitems
        for mi in reversed(self._change_url_prefix_menuitems):
            menu.Remove(mi.Id)
        self._change_url_prefix_menuitems.clear()
        
        # Create new _change_url_prefix_menuitems
        (cup_mis, on_attach_menuitems) = \
            self.entity_tree.create_change_url_prefix_menuitems_for(
                node=self.entity_tree.selected_node,
                menu_type='top_level')
        for (mi_offset, mi) in enumerate(cup_mis, start=first_old_mi_offset):
            menu.Insert(mi_offset, mi)
        on_attach_menuitems()
        self._change_url_prefix_menuitems = cup_mis
    
    def _on_change_url_prefix_menuitem_selected(self, event: wx.MenuEvent) -> None:
        self.entity_tree.on_change_url_prefix_menuitem_selected(
            event, self.entity_tree.selected_node)
    
    # === Entity Pane: Init ===
    
    def _create_entity_pane(self, parent, progress_listener: OpenProjectProgressListener):
        """
        Raises:
        * CancelOpenProject
        """
        pane = wx.Panel(parent)
        pane_sizer = wx.BoxSizer(wx.VERTICAL)
        pane.SetSizer(pane_sizer)
        
        pane_sizer.Add(
            self._create_entity_pane_content(pane, progress_listener),
            proportion=1,
            flag=wx.EXPAND|wx.ALL,
            border=_WINDOW_INNER_PADDING)
        
        return pane
    
    def _create_entity_pane_content(self, parent: wx.Window, progress_listener: OpenProjectProgressListener):
        """
        Raises:
        * CancelOpenProject
        """
        content_sizer = wx.BoxSizer(wx.VERTICAL)
        content_sizer.Add(
            self._create_entity_tree(parent, progress_listener),
            proportion=1,
            flag=wx.EXPAND)
        content_sizer.AddSpacer(_WINDOW_INNER_PADDING)
        content_sizer.Add(self._create_button_bar(parent), flag=wx.EXPAND)
        return content_sizer
    
    def _create_entity_tree(self, parent: wx.Window, progress_listener: OpenProjectProgressListener):
        """
        Raises:
        * CancelOpenProject
        """
        self.entity_tree = EntityTree(parent, self.project, progress_listener)
        bind(self.entity_tree.peer, wx.EVT_TREE_SEL_CHANGED, self._on_selected_entity_changed)
        self._on_selected_entity_changed()
        
        return self.entity_tree.peer
    
    def _create_button_bar(self, parent: wx.Window):
        new_root_url_button = self._new_root_url_action.create_button(parent, name='cr-add-url-button')
        new_group_button = self._new_group_action.create_button(parent, name='cr-add-group-button')
        edit_entity_button = self._edit_action.create_button(parent, name='cr-edit-button')
        forget_entity_button = self._forget_action.create_button(parent, name='cr-forget-button')
        download_button = self._download_action.create_button(parent, name='cr-download-button')
        update_members_button = self._update_members_action.create_button(
            parent, name='cr-update-members-button')
        
        view_button = self._view_action.create_button(parent, name='cr-view-button')
        
        content_sizer = wx.BoxSizer(wx.HORIZONTAL)
        content_sizer.Add(new_root_url_button)
        content_sizer.AddSpacer(_WINDOW_INNER_PADDING)
        content_sizer.Add(new_group_button)
        content_sizer.AddSpacer(_WINDOW_INNER_PADDING)
        content_sizer.Add(edit_entity_button)
        content_sizer.AddSpacer(_WINDOW_INNER_PADDING)
        content_sizer.Add(forget_entity_button)
        content_sizer.AddSpacer(_WINDOW_INNER_PADDING * 2)
        content_sizer.AddStretchSpacer()
        content_sizer.Add(download_button)
        content_sizer.AddSpacer(_WINDOW_INNER_PADDING)
        content_sizer.Add(update_members_button)
        content_sizer.AddSpacer(_WINDOW_INNER_PADDING)
        content_sizer.Add(view_button)
        return content_sizer
    
    # === Entity Pane: Properties ===
    
    @property
    def _suggested_url_or_url_pattern_for_selection(self) -> str | None:
        selected_entity = self.entity_tree.selected_entity
        
        if isinstance(selected_entity, (Resource, RootResource)):
            return selected_entity.resource.url
        elif isinstance(selected_entity, ResourceGroup):
            return selected_entity.url_pattern
        else:
            return self.project.default_url_prefix
    
    @property
    def _suggested_source_for_selection(self) -> ResourceGroupSource:
        return self.entity_tree.source_of_selection
    
    @property
    def _suggested_name_for_selection(self) -> str | None:
        return self.entity_tree.name_of_selection
    
    # === Operations ===
    
    @fg_affinity
    def close(self, *, prompt_to_save_untitled: bool = False) -> None:
        """
        Closes this window, disposing any related resources.
        
        Does NOT prompt to save the project if it is untitled, by default,
        to ensure the close operation is not cancelled.
        
        See also: MainWindow.try_close()
        """
        self._on_close_frame(prompt_to_save_untitled=prompt_to_save_untitled)
    
    def __enter__(self) -> 'MainWindow':
        return self
    
    def __exit__(self, exc_type, exc_value, exc_traceback) -> None:
        self.close()
    
    # === Project: Events ===
    
    # TODO: Use @fg_trampoline here to simplify the implementation
    @capture_crashes_to_stderr
    def project_is_dirty_did_change(self) -> None:
        if is_mac_os():
            @capture_crashes_to_stderr
            @fg_affinity
            def fg_task() -> None:
                self._frame.OSXSetModified(self.project.is_dirty)
            fg_call_later(fg_task)
    
    @fg_trampoline
    @capture_crashes_to_stderr
    def project_readonly_did_change(self) -> None:
        # Update actions
        self._new_root_url_action.enabled = not self._readonly
        self._new_group_action.enabled = not self._readonly
        self._on_selected_entity_changed()
        
        # Update status bar
        self._update_read_write_icon_for_readonly_status()
    
    @fg_trampoline
    @capture_crashes_to_stderr
    def project_root_task_did_change(self, old_root_task: 'RootTask', new_root_task: 'RootTask') -> None:
        """
        Called when the project gets a new RootTask (e.g., during Save As reopen).
        Updates the TaskTree to connect to the new RootTask.
        """
        self.task_tree.change_root_task(new_root_task)
    
    # === File Menu: Events ===
    
    def _on_save_as_project(self, event: wx.MenuEvent) -> None:
        """
        1. Handle Save menu item for untitled projects.
        2. Handle Save As menu item for all projects.
        """
        # Prompt for a save location
        dialog = wx.FileDialog(self._frame,
            message='',
            wildcard='*' + Project.FILE_EXTENSION,
            style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT)
        with dialog:
            if dialog.ShowModal() != wx.ID_OK:
                return
            
            new_project_path = dialog.GetPath()  # capture
            if not new_project_path.endswith(self.project.FILE_EXTENSION):
                new_project_path += self.project.FILE_EXTENSION
        
        # Save the project
        progress_dialog = SaveAsProgressDialog(self._frame)
        future = self.project.save_as(new_project_path, progress_dialog)
        
        # Update the window title and proxy icon
        @capture_crashes_to_stderr
        @fg_affinity
        def on_save_complete() -> None:
            # Check whether save succeeded
            try:
                future.result(timeout=0)
            except FileExistsError:
                raise AssertionError()
            except CancelSaveAs:
                return
            # TODO: Handle ProjectReadOnlyError more gracefully,
            #       by providing a more-targeted error message
            except (ProjectReadOnlyError, Exception) as e:
                self._show_save_error_dialog(e)
                # TODO: Introduce public read-only `project.is_closed` property
                if self.project._closed:
                    self.close()
                return
            finally:
                progress_dialog.reset()
            
            # Update window title
            self._frame.SetTitle(self._calculate_frame_title(self.project))
            
            # Update proxy icon
            self._frame.SetRepresentedFilename(new_project_path)
            
            # Update Save menu item
            (s_label, s_enabled) = self._calculate_save_action_properties()
            self._save_project_action.label = s_label
            self._save_project_action.enabled = s_enabled
        future.add_done_callback(lambda _: fg_call_later(on_save_complete))
    
    def _on_close_window(self, event: wx.CommandEvent) -> None:
        self._frame.Close()  # will trigger call to _on_close_frame()
    
    def _on_quit(self, event: wx.CommandEvent) -> None:
        if event.Id == wx.ID_EXIT:
            set_is_quitting()
            self._frame.Close()  # will trigger call to _on_close_frame()
        else:
            event.Skip()
    
    # TODO: Move this method adjacent to close()
    @fg_affinity
    def _on_close_frame(self,
            event: wx.CloseEvent | None = None,
            *, prompt_to_save_untitled: bool = True,
            ) -> None:
        """
        Tries to close this window, disposing any related resources.
        
        If the project is untitled and dirty, prompts to save it unless prompt_to_save_untitled=False.
        If the user cancels the prompt the close event is vetoed.
        """
        did_not_cancel = self.try_close(prompt_to_save_untitled=prompt_to_save_untitled)
        if not did_not_cancel and event is not None:
            # Cancel the close
            event.Veto()
    
    # TODO: Move this method adjacent to close()
    @fg_affinity
    def try_close(self,
            *, prompt_to_save_untitled: bool = True,
            will_prompt_to_save: Callable[[], None] | None = None,
            ) -> bool:
        """
        Tries to close this window, disposing any related resources.
        
        If the project is untitled and dirty, prompts to save it unless prompt_to_save_untitled=False.
        If the user cancels the prompt, the window is not closed, and returns False.
        
        In all other situations, the project is closed and returns True.
        
        It is safe to call this method multiple times, even after the project has closed.
        
        See also: MainWindow.close()
        """
        if self._closed:
            # Already closed
            return True
        try:
            did_not_cancel = self._do_try_close(
                prompt_to_save_untitled=prompt_to_save_untitled,
                will_prompt_to_save=will_prompt_to_save)
            return did_not_cancel
        except:
            did_not_cancel = True
            raise
        finally:
            if did_not_cancel:
                self._closed = True
    
    def _do_try_close(self,
            *, prompt_to_save_untitled: bool = True,
            will_prompt_to_save: Callable[[], None] | None = None,
            ) -> bool:
        # If the project is untitled and dirty, prompt to save it
        if self.project.is_untitled and self.project.is_dirty and prompt_to_save_untitled:
            if will_prompt_to_save is not None:
                will_prompt_to_save()
            
            dialog = wx.MessageDialog(
                self._frame,
                message='Do you want to save the changes you made to this project?',
                caption='Save Changes',
                style=wx.YES_NO | wx.CANCEL | wx.ICON_QUESTION
            )
            dialog.Name = 'cr-save-changes-dialog'
            with dialog:
                result = ShowModal(dialog)
            if result == wx.ID_CANCEL:
                return False
            elif result == wx.ID_YES:
                # Prompt for a save location
                file_dialog = wx.FileDialog(self._frame,
                    message='',
                    wildcard='*' + Project.FILE_EXTENSION,
                    style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT)
                with file_dialog:
                    if file_dialog.ShowModal() != wx.ID_OK:
                        return False
                    
                    new_project_path = file_dialog.GetPath()
                    if not new_project_path.endswith(self.project.FILE_EXTENSION):
                        new_project_path += self.project.FILE_EXTENSION
                    
                    # Save the project
                    progress_dialog = SaveAsProgressDialog(self._frame)
                    future = self.project.save_as(new_project_path, progress_dialog)
                    
                    # Wait for save to complete
                    try:
                        fg_wait_for(lambda: future.done(), timeout=None, poll_interval=0.1)
                        future.result()
                    except CancelSaveAs:
                        return False
                    # TODO: Handle ProjectReadOnlyError more gracefully,
                    #       by providing a more-targeted error message
                    except (ProjectReadOnlyError, Exception) as e:
                        self._show_save_error_dialog(e)
                        return False
                    finally:
                        progress_dialog.reset()
            elif result == wx.ID_NO:
                # Do not save, just close
                pass
            else:
                raise AssertionError(f'Unexpected dialog result: {result}')
        
        if self._autohibernate_timer is not None:
            self._autohibernate_timer.stop()
        
        self._hibernate()
        
        # Dispose resources created in MainWindow.start_server(), in reverse order
        if self._project_server is not None:
            self._project_server.close()
        if self._log_drawer is not None:
            self._log_drawer.close()
        
        # Dispose resources created in MainWindow.__init__(), in reverse order
        if True:
            self.task_tree.dispose()
            self.entity_tree.dispose()
            
            # Dispose actions so that they don't try to interact with
            # wx.Objects in the frame while the frame is being deleted
            for a in self._actions:
                a.dispose()
            
            self.project.listeners.remove(self)
            self.project.close()
        
        # Destroy self, since we did not Veto() the close event
        self._frame.Destroy()
        
        # Clear reference to self if we're the last created MainWindow
        if MainWindow._last_created is self:
            MainWindow._last_created = None
        
        return True

    @fg_affinity
    def _show_save_error_dialog(self, e: Exception) -> None:
        # Show error information on stderr
        # HACK: Suppress while tests are running to keep the output clean
        if not tests_are_running():
            traceback.print_exception(e, file=sys.stderr)
        
        error_dialog = wx.MessageDialog(
            self._frame,
            message=f'Error saving project: {str(e) or type(e).__name__}',
            caption='Save Error',
            style=wx.ICON_ERROR|wx.OK
        )
        error_dialog.Name = 'cr-save-error-dialog'
        with error_dialog:
            ShowModal(error_dialog)
    
    # === Entity Pane: New/Edit Root Url ===
    
    def _on_new_root_url(self, event: wx.CommandEvent) -> None:
        NewRootUrlDialog(
            self._frame,
            self._on_new_root_url_dialog_ok,
            url_exists_func=self._root_url_exists,
            initial_url=self._suggested_url_or_url_pattern_for_selection or '',
            initial_name=self._suggested_name_for_selection or '',
            initial_set_as_default_domain=(self.project.default_url_prefix is None),
            initial_set_as_default_directory=False,
        )
    
    def _root_url_exists(self, url: str) -> bool:
        r = self.project.get_resource(url)
        if r is None:
            return False
        rr = self.project.get_root_resource(r)
        return rr is not None
    
    @fg_affinity
    def _on_new_root_url_dialog_ok(self,
            name: str,
            url: str,
            change_prefix_command: ChangePrefixCommand,
            download_immediately: bool,
            create_group: bool,
            ) -> None:
        if url == '':
            raise ValueError('Invalid blank URL')
        
        try:
            rr = RootResource(self.project, name, Resource(self.project, url))
        except RootResource.AlreadyExists:
            raise ValueError('Invalid duplicate URL')
        
        if isinstance(change_prefix_command, EllipsisType):
            pass
        elif change_prefix_command is None:
            self.entity_tree.clear_default_url_prefix()
        else:
            self.entity_tree.set_default_url_prefix(*change_prefix_command)
        
        if create_group:
            assert url.endswith('/')
            rg = ResourceGroup(self.project, '', url + '**', source=rr)
            
            if download_immediately:
                rg.download(needs_result=False)
        else:
            if download_immediately:
                rr.download(needs_result=False)
    
    @fg_affinity
    def _on_edit_root_url_dialog_ok(self,
            rr: RootResource,
            name: str,
            url: str,
            change_prefix_command: ChangePrefixCommand,
            download_immediately: bool,
            create_group: bool,
            ) -> None:
        if url != rr.url:
            raise ValueError()
        
        if name != rr.name:
            rr.name = name
            
            # TODO: This update should happen in response to an event
            #       fired by the entity itself.
            self.entity_tree.root.update_title_of_descendants()  # update names in titles
        
        if isinstance(change_prefix_command, EllipsisType):
            pass
        elif change_prefix_command is None:
            self.entity_tree.clear_default_url_prefix()
        else:
            self.entity_tree.set_default_url_prefix(*change_prefix_command)
        
        assert download_immediately == False
        assert create_group == False
    
    # === Entity Pane: New/Edit Group ===
    
    def _on_new_group(self, event: wx.CommandEvent) -> None:
        try:
            NewGroupDialog(
                self._frame,
                self._on_new_group_dialog_ok,
                self.project,
                saving_source_would_create_cycle_func=lambda source: False,
                initial_url_pattern=self._suggested_url_or_url_pattern_for_selection or '',
                initial_source=self._suggested_source_for_selection,
                initial_name=self._suggested_name_for_selection or '')
        except CancelLoadUrls:
            pass
    
    @fg_affinity
    def _on_new_group_dialog_ok(self,
            name: str,
            url_pattern: str,
            source: ResourceGroupSource,
            do_not_download: bool,
            download_immediately: bool,
            ) -> None:
        # TODO: Validate user input:
        #       * Is url_pattern empty?
        #       * Is url_pattern already taken?
        rg = ResourceGroup(
            self.project, name, url_pattern, source,
            do_not_download=do_not_download)
        
        if download_immediately:
            rg.download(needs_result=False)
    
    @fg_affinity
    def _on_edit_group_dialog_ok(self,
            rg: ResourceGroup,
            name: str,
            url_pattern: str,
            source: ResourceGroupSource,
            do_not_download: bool,
            download_immediately: bool,
            ) -> None:
        if url_pattern != rg.url_pattern:
            raise ValueError()
        (rg.name, rg.source, rg.do_not_download) = (name, source, do_not_download)
        
        # TODO: This update should happen in response to an event
        #       fired by the entity itself.
        self.entity_tree.root.update_title_of_descendants()  # update names in titles
        
        assert download_immediately == False
    
    def _saving_source_would_create_cycle(self, rg: ResourceGroup, source: ResourceGroupSource) -> bool:
        ancestor_source = source  # type: ResourceGroupSource
        while ancestor_source is not None:
            if ancestor_source == rg:
                return True
            if isinstance(ancestor_source, ResourceGroup):
                ancestor_source = ancestor_source.source  # reinterpret
            else:
                ancestor_source = None
        return False
    
    # === Entity Pane: Other Commands ===
    
    def _on_edit_entity(self, event) -> None:
        selected_entity = self.entity_tree.selected_entity
        assert selected_entity is not None
        
        if isinstance(selected_entity, RootResource):
            rr = selected_entity
            selection_urllike = rr.resource.url
            selection_domain_prefix = get_url_domain_prefix_for(selection_urllike)
            selection_dir_prefix = get_url_directory_prefix_for(selection_urllike)
            NewRootUrlDialog(
                self._frame,
                partial(self._on_edit_root_url_dialog_ok, rr),
                url_exists_func=self._root_url_exists,
                initial_url=rr.url,
                initial_name=rr.name,
                initial_set_as_default_domain=(
                    selection_domain_prefix is not None and
                    self.project.default_url_prefix == selection_domain_prefix
                ),
                initial_set_as_default_directory=(
                    selection_dir_prefix is not None and
                    selection_dir_prefix != selection_domain_prefix and
                    self.project.default_url_prefix == selection_dir_prefix
                ),
                allow_set_as_default_domain_or_directory=(
                    selection_domain_prefix is not None or
                    selection_dir_prefix is not None
                ),
                is_edit=True,
            )
        elif isinstance(selected_entity, ResourceGroup):
            rg = selected_entity
            try:
                NewGroupDialog(
                    self._frame,
                    partial(self._on_edit_group_dialog_ok, rg),
                    self.project,
                    saving_source_would_create_cycle_func=
                        partial(self._saving_source_would_create_cycle, rg),
                    initial_url_pattern=rg.url_pattern,
                    initial_source=rg.source,
                    initial_name=rg.name,
                    initial_do_not_download=rg.do_not_download,
                    is_edit=True)
            except CancelLoadUrls:
                pass
        else:
            raise AssertionError()
    
    def _on_forget_entity(self, event) -> None:
        selected_entity = self.entity_tree.selected_entity
        assert selected_entity is not None
        
        selected_entity.delete()
    
    def _on_download_entity(self, event) -> None:
        selected_entity = self.entity_tree.selected_entity
        assert selected_entity is not None
        
        # Show progress dialog in advance if will need to load all project URLs
        if isinstance(selected_entity, ResourceGroup):
            try:
                selected_entity.project.load_urls()
            except CancelLoadUrls:
                return
        
        # Show progress dialog if it will likely take a long time to start the download
        if DownloadResourceGroupMembersTask._LAZY_LOAD_CHILDREN:
            progress_dialog = None  # type: Optional[wx.ProgressDialog]
        else:
            if (isinstance(selected_entity, ResourceGroup) and
                    len(selected_entity.members) >= 2000):  # TODO: Tune threshold
                progress_dialog = wx.ProgressDialog(
                    title='Starting download',
                    message=f'Starting download of {len(selected_entity.members):n} members...',
                    parent=self._frame,
                    style=wx.PD_ELAPSED_TIME)
                progress_dialog.Name = 'cr-starting-download'
                progress_dialog.Pulse(progress_dialog.Message)  # make progress bar indeterminate
                progress_dialog.Show()
                
                # Update the elapsed time every 1 second
                # 
                # NOTE: It would be simpler to implement this logic with wx.Timer
                #       but wx.Timer seems to not work well if very many lambdas
                #       are scheduled with fg_call_later at the same time.
                @capture_crashes_to_stderr
                def elapsed_time_updater() -> None:
                    while True:
                        time.sleep(1.0)
                        def fg_task() -> bool:
                            if progress_dialog is not None:
                                progress_dialog.Pulse(progress_dialog.Message)
                                return True
                            else:
                                return False
                        still_ticking = fg_call_and_wait(fg_task)
                        if not still_ticking:
                            break
                bg_call_later(elapsed_time_updater)
            else:
                progress_dialog = None
        
        # Run download() on a background thread because it can take a long time
        # to instantiate the tree of related download tasks (when _LAZY_LOAD_CHILDREN == False)
        # 
        # NOTE: Loudly crashes the entire scheduler thread upon failure.
        #       If this failure mode ends up happening commonly,
        #       suggest implementing a less drastic failure mode.
        @capture_crashes_to(self.project.root_task)
        def bg_task() -> None:
            assert selected_entity is not None
            
            # Start download
            selected_entity.download(needs_result=False)
            
            # Close progress dialog, if applicable
            if progress_dialog is not None:
                def fg_task() -> None:
                    nonlocal progress_dialog
                    assert progress_dialog is not None
                    progress_dialog.Destroy()
                    progress_dialog = None  # unexport
                fg_call_and_wait(fg_task)
        bg_call_later(bg_task)
    
    def _on_update_group_members(self, event):
        selected_entity = self.entity_tree.selected_entity
        selected_entity.update_members()
    
    def _on_view_entity(self, event) -> None:
        # TODO: If the server couldn't be started (ex: due to the default port being in
        #       use), report an appropriate error.
        project_server = self.start_server()
        
        selected_entity = self.entity_tree.selected_entity
        assert isinstance(selected_entity, (Resource, RootResource))
        archive_url = selected_entity.resource.url
        request_url = project_server.get_request_url(archive_url)
        
        def open_browser_to_url() -> None:
            if is_linux():
                # HACK: Firefox on Linux starts with an error if
                #       the current working directory is not writable,
                #       so make sure the current working directory is
                #       writable before potentially starting Firefox
                open_browser_context = self._cwd_set_to_writable_dir()  # type: AbstractContextManager
            else:
                open_browser_context = nullcontext()
            with open_browser_context:
                # NOTE: Can block for as long as 3 seconds on Linux
                webbrowser.open(request_url)
        
        # HACK: If LogDrawer is using _WindowPairingStrategy.FLOAT_AND_RAISE_ON_ACTIVATE,
        #       make sure the log drawer is done bringing itself and MainWindow to front
        #       before bringing a browser to the front on top of them
        if os.environ.get('CRYSTAL_RUNNING_TESTS', 'False') == 'False':
            wx.CallLater(10, open_browser_to_url)
        else:
            # NOTE: During tests it's easier to spy on this call if it's NOT
            #       deferred inside wx.CallLater
            open_browser_to_url()
    
    @contextmanager
    def _cwd_set_to_writable_dir(self) -> Iterator[None]:
        assert is_linux(), 'This function only supports Linux'
        new_cwd = os.environ.get('HOME', '/')
        old_cwd = os.getcwd()  # capture
        os.chdir(new_cwd)
        try:
            yield
        finally:
            os.chdir(old_cwd)
    
    def start_server(self, port: int | None=None, host: str | None=None) -> 'ProjectServer':
        """
        Starts an HTTP server that serves pages from this project.
        
        If an HTTP server is already running, does nothing.
        
        Raises:
        * OSError (errno.EADDRINUSE) -- if the host:port combination is already in use.
        """
        if self._project_server is None:
            self._log_drawer = LogDrawer(parent=self._frame)
            self._project_server = ProjectServer(self.project, port=port, host=host, stdout=self._log_drawer.writer)
        
        return self._project_server
    
    # === Entity Pane: Events ===
    
    def _on_selected_entity_changed(self, event: wx.TreeEvent | None=None) -> None:
        selected_entity = self.entity_tree.selected_entity  # cache
        
        readonly = self._readonly  # cache
        self._edit_action.enabled = (
            (not readonly) and
            isinstance(selected_entity, (ResourceGroup, RootResource)))
        self._forget_action.enabled = (
            (not readonly) and
            isinstance(selected_entity, (ResourceGroup, RootResource)))
        self._download_action.enabled = (
            (not readonly) and
            selected_entity is not None)
        self._update_members_action.enabled = (
            (not readonly) and
            isinstance(selected_entity, ResourceGroup))
        self._view_action.enabled = (
            isinstance(selected_entity, (Resource, RootResource)))
    
    # === Task Pane: Init ===
    
    def _create_task_pane(self, parent: wx.Window) -> wx.Window:
        pane = wx.Panel(parent)
        pane_sizer = wx.BoxSizer(wx.VERTICAL)
        pane.SetSizer(pane_sizer)
        
        pane_sizer.Add(
            self._create_task_pane_content(pane), 
            proportion=1, 
            flag=wx.EXPAND|wx.ALL, 
            border=_WINDOW_INNER_PADDING)
        
        return pane
    
    def _create_task_pane_content(self, parent: wx.Window) -> wx.Window:
        content_sizer = wx.BoxSizer(wx.VERTICAL)
        content_sizer.Add(self._create_task_tree(parent), proportion=1, flag=wx.EXPAND)
        return content_sizer
    
    def _create_task_tree(self, parent: wx.Window) -> wx.Window:
        self.task_tree = TaskTree(parent, self.project.root_task)
        if is_mac_os():
            self.task_tree.peer.SetBackgroundColour(
                wx.Colour(254, 254, 254))  # pure white
        
        return self.task_tree.peer
    
    # === Task Pane: Other Commands ===
    
    @capture_crashes_to_stderr
    def _hibernate(self) -> None:
        if self.project.readonly:
            return
        
        try:
            self.project.hibernate_tasks()
        except (sqlite3.DatabaseError, sqlite3.ProgrammingError) as e:
            # Ignore certain types of I/O errors while closing
            io_error = (
                # Disk containing the database may have unmounted expectedly
                is_database_gone_error(e) or
                # Automated tests are simulating unmount of the disk
                # containing the database, using _close_project_abruptly()
                (tests_are_running() and is_database_closed_error(e))
            )
            if not io_error:
                raise
    
    @capture_crashes_to_stderr
    def _unhibernate(self) -> None:
        if self.project.readonly:
            return
        
        def confirm_unhibernate_tasks() -> bool:
            dialog = wx.MessageDialog(
                self._frame,
                message=(
                    'Downloads were running when this project was last closed. '
                    'Resume them?'
                ),
                caption='Resume Downloads?',
                style=wx.OK|wx.CANCEL,
            )
            dialog.Name = 'cr-resume-downloads'
            with dialog:
                dialog.SetOKCancelLabels('Resume', wx.ID_CANCEL)
                dialog.SetEscapeId(wx.ID_CANCEL)
                position_dialog_initially(dialog)
                choice = ShowModal(dialog)
            should_resume = (choice == wx.ID_OK)
            return should_resume
        self.project.unhibernate_tasks(confirm_unhibernate_tasks)
    
    # === Status Bar: Init ===
    
    def _create_status_bar(self, parent: wx.Window) -> wx.Window:
        pane = wx.Panel(parent)
        pane_sizer = wx.BoxSizer(wx.HORIZONTAL)
        pane.SetSizer(pane_sizer)
        
        version_label = wx.StaticText(pane, label=f'Crystal v{crystal_version}')
        
        preferences_button = self._preferences_action.create_button(pane, name='cr-preferences-button')
        bind(preferences_button, wx.EVT_BUTTON, self._on_preferences)
        
        self._read_write_icon = read_write_icon = wx.StaticText(pane, name='cr-read-write-icon')
        self._update_read_write_icon_for_readonly_status()
        
        pane_sizer.Add(
            version_label,
            proportion=1,
            flag=wx.CENTER|wx.EXPAND|wx.ALL,
            border=_WINDOW_INNER_PADDING)
        pane_sizer.Add(
            preferences_button,
            flag=wx.CENTER|wx.ALL &~ wx.RIGHT,
            border=_WINDOW_INNER_PADDING)
        pane_sizer.Add(
            read_write_icon,
            flag=wx.CENTER|wx.ALL,
            border=_WINDOW_INNER_PADDING)
        
        return pane
    
    def _update_read_write_icon_for_readonly_status(self) -> None:
        readonly = self._readonly  # cache
        
        if readonly:
            rwi_label = '🔒' if not is_windows() else 'Read only'
            rwi_tooltip = 'Read only project'  # type: str
        else:
            rwi_label = '✏️' if not is_windows() else 'Writable'
            rwi_tooltip = 'Writable project'
        self._read_write_icon.SetLabel(rwi_label)
        self._read_write_icon.SetToolTip(rwi_tooltip)
    
    # === Status Bar: Events ===
    
    def _on_preferences(self, event: wx.MenuEvent | wx.CommandEvent) -> None:
        if event.Id == wx.ID_PREFERENCES or isinstance(event.EventObject, wx.Button):
            PreferencesDialog(self._frame, self.project)
        else:
            event.Skip()
