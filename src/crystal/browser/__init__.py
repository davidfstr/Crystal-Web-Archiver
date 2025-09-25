from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager, nullcontext
import sys
from crystal import __version__ as CRYSTAL_VERSION
from crystal import APP_NAME, resources
from crystal.app_preferences import app_prefs
from crystal.browser.entitytree import (
    EntityTree, ResourceGroupNode, RootResourceNode,
)
from crystal.browser.icons import TREE_NODE_ICONS
from crystal.browser.new_group import NewGroupDialog
from crystal.browser.new_root_url import ChangePrefixCommand, NewRootUrlDialog
from crystal.browser.preferences import PreferencesDialog
from crystal.browser.tasktree import TaskTree, TaskTreeNode
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
from crystal.ui.callout import Callout
from crystal.ui.clickable_text import ClickableText
from crystal.ui.log_drawer import LogDrawer
from crystal.ui.tree import DEFAULT_FOLDER_ICON_SET
from crystal.ui.tree2 import NodeView
from crystal.util.bulkheads import (
    capture_crashes_to, capture_crashes_to_stderr,
)
from crystal.util.cloak import CloakMixin, cloak
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
from crystal.util.wx_system_appearance import IsDark, IsDarkNow, SetDark
from crystal.util.wx_timer import Timer, TimerError
from crystal.util.xcollections.iterables import is_iterable_empty, is_iterable_len_1
from crystal.util.xos import (
    is_kde_or_non_gnome, is_linux, is_mac_os, is_windows,
    preferences_are_called_settings_in_this_os,
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


class MainWindow(CloakMixin):
    _AUTOHIBERNATE_PERIOD = 1000 * 60 * 5  # 5 min, in milliseconds
    _PROJECT_SERVER_SHUTDOWN_TIMEOUT = 2.0  # seconds; short
    
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
                # macOS: Show initial dirty state
                raw_frame.OSXSetModified(project.is_dirty)
                
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
                
                bind(raw_frame, wx.EVT_SYS_COLOUR_CHANGED, self._on_system_appearance_changed)
                bind(raw_frame, wx.EVT_CLOSE, self._on_close_frame)
                
                frame.Fit()
                raw_frame.Fit()  # NOTE: Must Fit() before Show() here so that wxGTK actually fits correctly
                raw_frame.Show(True)
                
                # Define minimum size for main window
                min_width = entity_pane.GetBestSize().Width
                min_height = task_pane.GetBestSize().Height * 2
                # HACK: On Linux/wxGTK, there's a systematic ~52px discrepancy between
                # reported widget sizes and actual visual sizes. Compensate by adding
                # extra width on Linux to ensure buttons render at their intended size.
                if is_linux():
                    width_discrepancy = raw_frame.GetSize().Width - entity_pane.GetSize().Width
                    if width_discrepancy == 0:
                        if tests_are_running():
                            print('*** MainWindow width hack for Linux may no longer be needed', file=sys.stderr)
                    elif width_discrepancy > 0:
                        min_width += width_discrepancy
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
    
    _EDIT_ACTION_LABEL = '&Edit...'
    _GET_INFO_ACTION_LABEL = 'G&et Info...'
    
    _EDIT_ACTION_BUTTON_LABEL = decorate_label('✏️', '&Edit...', '')
    _GET_INFO_ACTION_BUTTON_LABEL = decorate_label('🔍', 'G&et Info...', '')
    
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
        if preferences_are_called_settings_in_this_os():
            preferences_label = 'Settings...'
        else:
            preferences_label = ''  # 'Preferences...' (or OS default)
        self._preferences_action = Action(
            wx.ID_PREFERENCES,
            preferences_label,
            wx.AcceleratorEntry(wx.ACCEL_CTRL, ord(',')),
            # NOTE: Action is bound to self._on_preferences later manually
            action_func=None,
            enabled=True,
            button_label=decorate_label('⚙️', (
                '&Preferences...'
                if preferences_label == ''
                else preferences_label  # no mnemonic
            ), truncation_fix='')
        )
        
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
            self._EDIT_ACTION_LABEL if not self._readonly else self._GET_INFO_ACTION_LABEL,
            accel=wx.AcceleratorEntry(wx.ACCEL_NORMAL, wx.WXK_RETURN),
            action_func=self._on_edit_entity,
            enabled=False,
            button_label=(
                self._EDIT_ACTION_BUTTON_LABEL
                if not self._readonly else
                self._GET_INFO_ACTION_BUTTON_LABEL
            ))
        self._forget_action = Action(wx.ID_ANY,
            '&Forget',
            wx.AcceleratorEntry(wx.ACCEL_CTRL, wx.WXK_BACK),
            self._on_forget_entity,
            enabled=False,
            button_label=decorate_label('✖️', '&Forget', ''))
        self._update_members_action = Action(wx.ID_ANY,
            'Update &Members',
            accel=None,
            action_func=self._on_update_group_members,
            enabled=False,
            button_label=decorate_label('🔎', 'Update &Members', ' '))
        self._download_action = Action(wx.ID_ANY,
            '&Download',
            wx.AcceleratorEntry(wx.ACCEL_CTRL, wx.WXK_RETURN),
            self._on_download_entity,
            enabled=False,
            button_label=decorate_label('⬇', '&Download', ''))
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
        self._update_members_action.append_menuitem_to(entity_menu)
        self._download_action.append_menuitem_to(entity_menu)
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
        self._entity_pane_content_sizer = wx.BoxSizer(wx.VERTICAL)
        # NOTE: Minimum vertical size chosen so that empty state is about the
        #       same height as the non-empty state
        self._entity_pane_content_sizer.SetMinSize(0, 300)
        
        # Add title heading for the entity tree
        entity_title_text = wx.StaticText(parent, label='Root URLs and Groups')
        entity_title_text.Font = entity_title_text.Font.MakeBold().MakeLarger()
        self._entity_pane_content_sizer.Add(
            entity_title_text,
            flag=wx.EXPAND|wx.LEFT|wx.RIGHT|wx.BOTTOM,
            border=_WINDOW_INNER_PADDING // 2)
        
        self._entity_tree_sizer_index = 1
        self._entity_tree_empty_state = self._create_empty_state_panel(parent)
        self._entity_tree_nonempty_state = self._create_entity_tree(parent, progress_listener)
        self._entity_pane_content_sizer.Add(self._entity_tree_empty_state, proportion=1, flag=wx.EXPAND)
        
        self._entity_pane_content_sizer.AddSpacer(_WINDOW_INNER_PADDING)
        self._entity_pane_content_sizer.Add(self._create_button_bar(parent), flag=wx.EXPAND)
        
        # Update visibility based on whether project initially empty or not
        is_empty_state_visible_initially = self._update_entity_pane_empty_state_visibility()
        if is_empty_state_visible_initially and is_mac_os():
            # Focus CTA button, since macOS does not do so automatically
            cta_button = parent.FindWindowByName('cr-empty-state-new-root-url-button')
            cta_button.SetFocus()
        
        # Defer callout visibility update until after layout is complete
        fg_call_later(self._update_view_button_callout_visibility, force_later=True)
        
        return self._entity_pane_content_sizer
    
    def _create_empty_state_panel(self, parent: wx.Window) -> wx.Panel:
        """Create the empty state panel with message and call-to-action button."""
        
        panel = wx.Panel(parent)
        panel_sizer = wx.BoxSizer(wx.VERTICAL)

        # Center vertically
        panel_sizer.AddStretchSpacer()
        
        # Create message text, large and centered
        message = wx.StaticText(panel, 
            label="Download your first page by defining a root URL for the page.",
            style=wx.ALIGN_CENTER)
        if True:
            message.Wrap(400)  # wrap text at 400px
            
            # Make message text larger
            font = message.GetFont()
            font.SetPointSize(font.GetPointSize() + 2)
            message.SetFont(font)
        panel_sizer.Add(message, flag=wx.ALIGN_CENTER)
        
        # Add spacing between message and button
        panel_sizer.AddSpacer(20)
        
        # Create primary call-to-action button
        cta_button = self._new_root_url_action.create_button(
            panel,
            name='cr-empty-state-new-root-url-button'
        )
        if True:
            # Use primary button styling
            cta_button.SetDefault()
            
            # Make title text larger and bold
            button_font = cta_button.GetFont()
            button_font.SetPointSize(button_font.GetPointSize() + 1)
            button_font.SetWeight(wx.FONTWEIGHT_BOLD)
            cta_button.SetFont(button_font)
            
            # Set a larger minimum height for the button
            # NOTE: cta_button.MinWidth does not return a sensible value
            #       on at least macOS
            cta_button.SetMinSize((cta_button.MinWidth, 40))
        panel_sizer.Add(cta_button, flag=wx.ALIGN_CENTER)
        
        # Center vertically
        panel_sizer.AddStretchSpacer()
        
        panel.SetSizer(panel_sizer)
        return panel
    
    def _create_entity_tree(self, parent: wx.Window, progress_listener: OpenProjectProgressListener):
        """
        Raises:
        * CancelOpenProject
        """
        self.entity_tree = EntityTree(parent, self.project, progress_listener)
        self.entity_tree.peer.Hide()
        bind(self.entity_tree.peer, wx.EVT_TREE_SEL_CHANGED, self._on_selected_entity_changed)
        if is_windows():
            # On Windows, repaint callout when tree is scrolled or repainted,
            # because tree draws over callout despite its z-order position
            bind(self.entity_tree.peer, wx.EVT_PAINT, self._on_tree_paint)
            bind(self.entity_tree.peer, wx.EVT_SCROLLWIN, self._on_tree_scroll)
        self._on_selected_entity_changed()
        
        return self.entity_tree.peer
    
    def _update_entity_pane_empty_state_visibility(self) -> bool:
        """
        Show entity tree or its empty state based on project content.
        
        Returns whether project is detected as empty.
        """
        is_project_empty = (
            is_iterable_empty(self.project.root_resources) and
            is_iterable_empty(self.project.resource_groups)
        )
        
        sizer_index = self._entity_tree_sizer_index  # cache
        
        current_window = self._entity_pane_content_sizer.GetItem(sizer_index).GetWindow()
        desired_window = (
            self._entity_tree_empty_state
            if is_project_empty
            else self._entity_tree_nonempty_state
        )
        if current_window != desired_window:
            current_window.Hide()
            desired_window.Show()
            
            self._entity_pane_content_sizer.Detach(sizer_index)
            self._entity_pane_content_sizer.Insert(sizer_index, desired_window, proportion=1, flag=wx.EXPAND)
            self._entity_pane_content_sizer.Layout()
        
        return is_project_empty
    
    def _create_button_bar(self, parent: wx.Window):
        new_root_url_button = self._new_root_url_action.create_button(parent, name='cr-add-url-button')
        new_group_button = self._new_group_action.create_button(parent, name='cr-add-group-button')
        edit_entity_button = self._edit_action.create_button(parent, name='cr-edit-button')
        forget_entity_button = self._forget_action.create_button(parent, name='cr-forget-button')
        update_members_button = self._update_members_action.create_button(
            parent, name='cr-update-members-button')
        download_button = self._download_action.create_button(parent, name='cr-download-button')
        
        view_button = self._view_action.create_button(parent, name='cr-view-button')
        self._view_button_callout_dismissed_temporarily = False
        self._view_button_callout = Callout(  # initially hidden
            parent=parent,
            target_control=view_button,
            message='View your first downloaded page in a browser by pressing "View"',
            on_temporary_dismiss=self._on_view_callout_temporary_dismiss,
            on_permanent_dismiss=self._on_view_callout_permanent_dismiss,
            name='cr-view-button-callout'
        )
        
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
        content_sizer.Add(update_members_button)
        content_sizer.AddSpacer(_WINDOW_INNER_PADDING)
        content_sizer.Add(download_button)
        content_sizer.AddSpacer(_WINDOW_INNER_PADDING)
        content_sizer.Add(view_button)
        return content_sizer
    
    # === Entity Pane: View Button Callout ===
    
    @capture_crashes_to_stderr
    def _update_view_button_callout_visibility(self) -> None:
        should_show_callout = (
            self.project._created_this_session and
            not self._view_button_callout_dismissed_temporarily and
            not (app_prefs.view_button_callout_dismissed or False) and
            (has_exactly_one_root_resource := is_iterable_len_1(self.project.root_resources))
        )
        if should_show_callout:
            self._view_button_callout.show_callout()
        else:
            self._view_button_callout.hide_callout()
    
    def _on_view_callout_temporary_dismiss(self) -> None:
        self._view_button_callout_dismissed_temporarily = True
        self._view_button_callout.hide_callout()
    
    def _on_view_callout_permanent_dismiss(self) -> None:
        app_prefs.view_button_callout_dismissed = True
        self._view_button_callout.hide_callout()
    
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
    
    def __exit__(self, *args) -> None:
        self.close()
    
    # === Project: Events ===
    
    # TODO: Use @fg_trampoline here to simplify the implementation
    @capture_crashes_to_stderr
    @cloak
    def project_is_dirty_did_change(self) -> None:
        if is_mac_os():
            @capture_crashes_to_stderr
            @fg_affinity
            def fg_task() -> None:
                self._frame.OSXSetModified(self.project.is_dirty)
            fg_call_later(fg_task)
    
    @fg_trampoline
    @capture_crashes_to_stderr
    @cloak
    def project_readonly_did_change(self) -> None:
        # Update actions
        self._new_root_url_action.enabled = not self._readonly
        self._new_group_action.enabled = not self._readonly
        if self._readonly:
            self._edit_action.label = self._GET_INFO_ACTION_LABEL
            self._edit_action.button_label = self._GET_INFO_ACTION_BUTTON_LABEL
        else:
            self._edit_action.label = self._EDIT_ACTION_LABEL
            self._edit_action.button_label = self._EDIT_ACTION_BUTTON_LABEL
        
        self._on_selected_entity_changed()
        
        # Update status bar
        self._update_read_write_icon_for_readonly_status()
    
    @fg_trampoline
    @capture_crashes_to_stderr
    @cloak
    def project_root_task_did_change(self, old_root_task: 'RootTask', new_root_task: 'RootTask') -> None:
        """
        Called when the project gets a new RootTask (e.g., during Save As reopen).
        Updates the TaskTree to connect to the new RootTask.
        """
        self.task_tree.change_root_task(new_root_task)
    
    # === File Menu: Events ===
    
    @fg_affinity
    def _on_system_appearance_changed(self, event: wx.SysColourChangedEvent) -> None:
        """Update UI when system transitions to/from dark mode."""
        SetDark(IsDarkNow())
        
        self.entity_tree.root.update_icon_set_of_descendants_supporting_dark_mode()
        self._refresh_task_tree_appearance()
        self._refresh_branding_area()
        
        # Keep processing the event
        event.Skip()
    
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
                dialog.SetYesNoLabels(wx.ID_SAVE, "&Don't Save")
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
            try:
                self._project_server.close(
                    _timeout_if_fg_thread=self._PROJECT_SERVER_SHUTDOWN_TIMEOUT)
            except TimeoutError:
                # Ignore timeout. Let the server continue shutting down in the
                # background. ProjectServer runs a daemon thread, so the Crystal
                # process won't be kept alive even if ProjectServer blocks forever.
                pass
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
                readonly=self._readonly,
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
                    is_edit=True,
                    readonly=self._readonly
                )
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
    
    # NOTE: Can't capture to the Entity Tree itself reliably since may not be visible
    @capture_crashes_to_stderr
    @cloak
    def root_resource_did_instantiate(self, root_resource: RootResource) -> None:
        self._update_entity_pane_empty_state_visibility()
        self._update_view_button_callout_visibility()
    
    # NOTE: Can't capture to the Entity Tree itself reliably since may not be visible
    @capture_crashes_to_stderr
    @cloak
    def root_resource_did_forget(self, root_resource: RootResource) -> None:
        self._update_entity_pane_empty_state_visibility()
        self._update_view_button_callout_visibility()
    
    # NOTE: Can't capture to the Entity Tree itself reliably since may not be visible
    @capture_crashes_to_stderr
    @cloak
    def resource_group_did_instantiate(self, group: ResourceGroup) -> None:
        self._update_entity_pane_empty_state_visibility()
    
    # NOTE: Can't capture to the Entity Tree itself reliably since may not be visible
    @capture_crashes_to_stderr
    @cloak
    def resource_group_did_forget(self, group: ResourceGroup) -> None:
        self._update_entity_pane_empty_state_visibility()
    
    def _on_selected_entity_changed(self, event: wx.TreeEvent | None=None) -> None:
        selected_entity = self.entity_tree.selected_entity  # cache
        
        readonly = self._readonly  # cache
        self._edit_action.enabled = (
            isinstance(selected_entity, (ResourceGroup, RootResource)))
        self._forget_action.enabled = (
            (not readonly) and
            isinstance(selected_entity, (ResourceGroup, RootResource)))
        self._update_members_action.enabled = (
            (not readonly) and
            isinstance(selected_entity, ResourceGroup))
        self._download_action.enabled = (
            (not readonly) and
            selected_entity is not None)
        self._view_action.enabled = (
            isinstance(selected_entity, (Resource, RootResource)))
    
    @capture_crashes_to_stderr
    def _on_tree_paint(self, event: wx.PaintEvent) -> None:
        if is_windows():
            # Repaint callout after the tree finishes repainting
            if hasattr(self, '_view_button_callout') and self._view_button_callout.IsShown():
                @capture_crashes_to_stderr
                def repaint_callout() -> None:
                    self._view_button_callout.Refresh()
                fg_call_later(repaint_callout, force_later=True)
        
        # Keep processing the event normally
        event.Skip()
    
    @capture_crashes_to_stderr
    def _on_tree_scroll(self, event: wx.ScrollWinEvent) -> None:
        """Handle tree scroll events to fix Windows callout artifacts during scrolling."""
        if is_windows():
            # Repaint callout after tree scrolling to fix visual artifacts
            if hasattr(self, '_view_button_callout') and self._view_button_callout.IsShown():
                @capture_crashes_to_stderr
                def repaint_tree_and_callout() -> None:
                    self.entity_tree.peer.Refresh()
                    self._view_button_callout.Refresh()
                fg_call_later(repaint_tree_and_callout, force_later=True)
        
        # Keep processing the event normally
        event.Skip()
    
    # === Task Pane: Init/Refresh ===
    
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
        
        # Add title heading for the task tree
        task_title_text = wx.StaticText(parent, label='Tasks')
        task_title_text.Font = task_title_text.Font.MakeBold().MakeLarger()
        content_sizer.Add(
            task_title_text,
            flag=wx.EXPAND|wx.LEFT|wx.RIGHT|wx.BOTTOM,
            border=_WINDOW_INNER_PADDING // 2)
        
        content_sizer.Add(self._create_task_tree(parent), proportion=1, flag=wx.EXPAND)
        return content_sizer
    
    def _create_task_tree(self, parent: wx.Window) -> wx.Window:
        self.task_tree = TaskTree(parent, self.project.root_task)
        self._set_task_tree_background_color()
        
        return self.task_tree.peer
    
    def _set_task_tree_background_color(self) -> None:
        """Sets the task tree background color based on the current light/dark mode."""
        if not is_mac_os():
            # Use OS default appearance
            return
        
        is_dark_mode = IsDark()
        if is_dark_mode:
            # Use a slightly lighter dark color to ensure text is readable
            self.task_tree.peer.SetBackgroundColour(wx.Colour(0x30, 0x30, 0x30))  # dark gray
        else:
            self.task_tree.peer.SetBackgroundColour(wx.Colour(254, 254, 254))  # pure white
    
    @fg_affinity
    def _refresh_task_tree_appearance(self) -> None:
        """Refresh the task tree appearance to reflect the new light/dark mode."""
        assert hasattr(self, 'task_tree')
        self._set_task_tree_background_color()
        def update_icon_set_of_descendents(tn: NodeView) -> None:
            for child in tn.children:
                assert isinstance(child, NodeView)
                update_icon_set_of_descendents(child)
            
            if hasattr(tn, 'update_icon_set'):
                tn.update_icon_set()
            else:
                ttn = tn.delegate
                if ttn is not None:
                    assert isinstance(ttn, TaskTreeNode)
                    ttn.update_icon_set()
        update_icon_set_of_descendents(self.task_tree.root.tree_node)
        self.task_tree.peer.Refresh()
    
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
    
    # === Status Bar: Init/Refresh ===
    
    def _create_status_bar(self, parent: wx.Window) -> wx.Window:
        pane = wx.Panel(parent)
        pane_sizer = wx.BoxSizer(wx.HORIZONTAL)
        pane.SetSizer(pane_sizer)
        
        self._branding_area = self._create_branding_area(pane)
        
        preferences_button = self._preferences_action.create_button(pane, name='cr-preferences-button')
        bind(preferences_button, wx.EVT_BUTTON, self._on_preferences)
        
        self._read_write_icon = read_write_icon = wx.StaticText(pane, name='cr-read-write-icon')
        self._update_read_write_icon_for_readonly_status()
        
        pane_sizer.Add(
            self._branding_area,
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
    
    def _create_branding_area(self, parent: wx.Window) -> wx.Window:
        """Create the branding area with Crystal icon, program name, version, and authors."""
        PROGRAM_NAME = 'Crystal'
        PROGRAM_NAME_USES_BITMAP = True
        PROGRAM_VERSION = f'v{CRYSTAL_VERSION}'
        AUTHORS_1_TEXT = 'By David Foster and '
        AUTHORS_2_TEXT = 'contributors'
        AUTHORS_2_URL = 'https://github.com/davidfstr/Crystal-Web-Archiver/graphs/contributors'
        
        if is_mac_os():
            font_size_scale = 1.0
        elif is_windows() or is_linux():
            font_size_scale = 72 / 96
        else:
            raise AssertionError('Unknown operating system')
        
        is_dark_mode = IsDark()
        
        # Create branding area with icon and text
        branding_area = wx.Panel(parent)
        branding_sizer = wx.BoxSizer(wx.HORIZONTAL)
        branding_area.SetSizer(branding_sizer)
        
        # Program icon (42x42)
        try:
            app_icon = self._load_app_icon()
            # Scale to 42x42 if needed
            if app_icon.GetSize() != (42, 42):
                image = app_icon.ConvertToImage()
                image = image.Scale(42, 42, wx.IMAGE_QUALITY_HIGH)
                app_icon = wx.Bitmap(image)
            
            icon_ctrl = wx.StaticBitmap(branding_area, bitmap=app_icon)
            branding_sizer.Add(
                icon_ctrl,
                flag=wx.CENTER|wx.RIGHT,
                border=8)
        except Exception:
            # If icon loading fails, continue without icon
            pass
        
        # Text area for program name, version, and authors
        text_area = wx.Panel(branding_area)
        if True:
            text_sizer = wx.BoxSizer(wx.VERTICAL)
            text_area.SetSizer(text_sizer)
            
            # Program name and version on same line
            program_line = wx.Panel(text_area)
            if True:
                program_line_sizer = wx.BoxSizer(wx.HORIZONTAL)
                program_line.SetSizer(program_line_sizer)
                
                # Program name (bitmap logotext for consistent cross-platform rendering)
                try:
                    if not PROGRAM_NAME_USES_BITMAP:
                        # TODO: Avoid using exceptions purely for control flow
                        raise Exception('Forcing text fallback for logotext bitmap')
                    logotext_bundle = self._load_logotext_bitmap(is_dark_mode)
                    if logotext_bundle:
                        program_name = wx.StaticBitmap(program_line, bitmap=logotext_bundle)
                        logotext_height = program_name.Size.Height
                    else:
                        raise RuntimeError("Failed to create logotext bundle")
                except Exception as e:
                    # Fallback to text if bitmap loading fails
                    print(f"Warning: Failed to load logotext bitmap, using text fallback: {e}")
                    program_name = wx.StaticText(program_line, label=PROGRAM_NAME)
                    program_name_font = self._load_app_name_font(int(23 * font_size_scale))
                    program_name.SetFont(program_name_font)
                    logotext_height = program_name.GetTextExtent(PROGRAM_NAME)[1]
                
                # Add program name to sizer
                program_line_sizer.Add(program_name, flag=wx.ALIGN_BOTTOM)
                
                # Space between name and version
                program_line_sizer.AddSpacer(8)
                
                # Version, with precise baseline alignment
                version_label = wx.StaticText(program_line, label=PROGRAM_VERSION)
                if True:
                    version_font = wx.Font(int(14 * font_size_scale), wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL)
                    version_label.SetFont(version_font)
                    version_label.SetForegroundColour(wx.Colour(128, 128, 128))  # gray
                    
                    # Calculate baseline offset for version text alignment
                    dc = wx.ClientDC(program_line)
                    dc.SetFont(version_font)
                    (_, _, version_descent, _) = dc.GetFullTextExtent(PROGRAM_VERSION)
                    
                    # For bitmap logotext, approximate baseline as 80% of height (typical for text)
                    # For text logotext, use actual measured descent
                    if isinstance(program_name, wx.StaticBitmap):
                        if is_mac_os():
                            fudge_offset = +2
                        elif is_windows():
                            fudge_offset = +0
                        elif is_linux():
                            fudge_offset = +1
                        else:
                            raise AssertionError('Unknown operating system')
                        logotext_baseline_from_bottom = int(logotext_height * 0.2) + fudge_offset
                    else:
                        dc.SetFont(program_name_font)
                        _, _, program_descent, _ = dc.GetFullTextExtent(PROGRAM_NAME)
                        logotext_baseline_from_bottom = program_descent
                    
                    # Calculate offset to align version baseline with logotext baseline
                    baseline_offset = max(0, logotext_baseline_from_bottom - version_descent)
                program_line_sizer.Add(
                    version_label,
                    # Use bottom border for baseline alignment
                    flag=wx.ALIGN_BOTTOM|wx.BOTTOM,
                    border=max(0, baseline_offset)
                )
            text_sizer.Add(program_line, flag=wx.BOTTOM, border=2)
            
            # Authors line with clickable "contributors" link
            authors_area = wx.Panel(text_area)
            if True:
                authors_sizer = wx.BoxSizer(wx.HORIZONTAL)
                authors_area.SetSizer(authors_sizer)
                authors_font = wx.Font(int(14 * font_size_scale), wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL)
                
                # "By David Foster and " part
                by_text = wx.StaticText(authors_area, label=AUTHORS_1_TEXT)
                by_text.SetFont(authors_font)
                if is_dark_mode:
                    by_text.SetForegroundColour(wx.Colour(0xD8, 0xD8, 0xD8))
                else:
                    by_text.SetForegroundColour(wx.Colour(0x1D, 0x1D, 0x1D))
                authors_sizer.Add(by_text)
                
                # "contributors" clickable link
                contributors_link = ClickableText(
                    authors_area, 
                    label=AUTHORS_2_TEXT, 
                    url=AUTHORS_2_URL
                )
                contributors_link.SetFont(authors_font)
                authors_sizer.Add(contributors_link)
            text_sizer.Add(
                authors_area,
                flag=wx.TOP|wx.BOTTOM,
                border=2,
            )
        branding_sizer.Add(text_area, flag=wx.CENTER)
        
        return branding_area
    
    @fg_affinity
    def _refresh_branding_area(self) -> None:
        """Refresh the branding area to reflect the new light/dark mode."""
        assert hasattr(self, '_branding_area')
        parent = self._branding_area.GetParent()
        sizer = parent.GetSizer()
        
        # Find the branding area in its parent's sizer. Store its position and flags.
        old_item = None
        sizer_position = -1
        for i in range(sizer.GetItemCount()):
            item = sizer.GetItem(i)
            if item.GetWindow() == self._branding_area:
                old_item = item
                sizer_position = i
                break
        assert old_item is not None
        proportion = old_item.GetProportion()
        flag = old_item.GetFlag()
        border = old_item.GetBorder()
        
        # Remove the old branding area
        sizer.Remove(sizer_position)
        self._branding_area.Destroy()
        
        # Create/insert new branding area with updated appearance
        self._branding_area = self._create_branding_area(parent)
        sizer.Insert(sizer_position, self._branding_area, proportion, flag, border)
        parent.Layout()
    
    @staticmethod
    def _load_app_icon() -> wx.Bitmap:
        """Load the Crystal application icon from resources."""
        with resources.open_binary('appicon.png') as f:
            bitmap = wx.Bitmap.FromPNGData(f.read())
        if not bitmap.IsOk():
            raise Exception('Failed to load app icon')
        return bitmap
    
    @staticmethod
    def _load_logotext_bitmap(is_dark_mode: bool = False) -> wx.BitmapBundle:
        """Load the Crystal logotext bitmap bundle with 1x and 2x versions."""
        bitmaps = []
        
        # Choose filenames based on mode
        if is_dark_mode:
            filename_1x = 'logotext-dark.png'
            filename_2x = 'logotext-dark@2x.png'
        else:
            filename_1x = 'logotext.png'
            filename_2x = 'logotext@2x.png'
        
        # Load 1x version
        try:
            with resources.open_binary(filename_1x) as f:
                bitmap_1x = wx.Bitmap.FromPNGData(f.read())
            if bitmap_1x.IsOk():
                bitmaps.append(bitmap_1x)
        except Exception:
            pass
        
        # Load 2x version
        try:
            with resources.open_binary(filename_2x) as f:
                bitmap_2x = wx.Bitmap.FromPNGData(f.read())
            if bitmap_2x.IsOk():
                bitmaps.append(bitmap_2x)
        except Exception:
            pass
        
        if not bitmaps:
            raise Exception('Failed to load logotext bitmaps')
        
        # Create bitmap bundle from available bitmaps
        return wx.BitmapBundle.FromBitmaps(bitmaps)
    
    @staticmethod
    def _load_app_name_font(base_size: int) -> wx.Font:
        """Create a Futura Medium font with fallback to system fonts."""
        # Try Futura Medium first
        font = wx.Font(base_size, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_MEDIUM, faceName='Futura')
        if font.IsOk() and font.GetFaceName() == 'Futura' and font.GetWeight() == wx.FONTWEIGHT_MEDIUM:
            return font
        
        # Try Futura Normal
        font = wx.Font(base_size, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL, faceName='Futura')
        if font.IsOk() and font.GetFaceName() == 'Futura':
            return font
         
        # Fallback to System Bold
        font = wx.Font(base_size, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD)
        assert font.IsOk(), 'Failed to create fallback font'
        return font
    
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
            PreferencesDialog(self._frame, self.project, self._on_preferences_dialog_close)
        else:
            event.Skip()
    
    @fg_affinity
    def _on_preferences_dialog_close(self) -> None:
        # Update callout visibility in callout were reset in app preferences
        self._update_view_button_callout_visibility()
