from contextlib import contextmanager, nullcontext
from crystal import __version__ as crystal_version
from crystal.browser.addgroup import AddGroupDialog
from crystal.browser.addrooturl import AddRootUrlDialog
from crystal.browser.entitytree import EntityTree
from crystal.browser.preferences import PreferencesDialog
from crystal.browser.tasktree import TaskTree
from crystal.model import Project, Resource, ResourceGroup, RootResource
from crystal.progress import (
    DummyOpenProjectProgressListener, OpenProjectProgressListener,
)
from crystal.server import ProjectServer
from crystal.task import RootTask
from crystal.ui.actions import Action
from crystal.ui.BetterMessageDialog import BetterMessageDialog
from crystal.ui.log_drawer import LogDrawer
from crystal.util.wx_bind import bind
from crystal.util.xos import is_linux, is_mac_os, is_windows
from crystal.util.xthreading import (
    bg_call_later, fg_call_later, fg_call_and_wait, set_is_quitting
)
import os
import time
from typing import ContextManager, Iterator, Optional
import webbrowser
import wx

_WINDOW_INNER_PADDING = 10


class MainWindow:
    project: Project
    frame: wx.Frame
    entity_tree: EntityTree
    task_tree: TaskTree
    
    def __init__(self,
            project: Project,
            progress_listener: Optional[OpenProjectProgressListener]=None,
            ) -> None:
        """
        Raises:
        * CancelOpenProject
        """
        if progress_listener is None:
            progress_listener = DummyOpenProjectProgressListener()
        
        self.project = project
        self._log_drawer = None  # type: Optional[LogDrawer]
        self._project_server = None  # type: Optional[ProjectServer]
        
        self._create_actions()
        
        # TODO: Rename: raw_frame -> frame,
        #               frame -> frame_content
        raw_frame = wx.Frame(None, title=project.title, name='cr-main-window')
        try:
            raw_frame.SetRepresentedFilename(project.path)
            
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
            
            self._frame = raw_frame
        except:
            raw_frame.Destroy()
            raise
    
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
            action_func=self._on_close_project,
            enabled=True)
        self._save_project_action = Action(
            wx.ID_SAVE,
            '',
            wx.AcceleratorEntry(wx.ACCEL_CTRL, ord('S')),
            # TODO: Support untitled projects (that require an initial save)
            action_func=None,
            enabled=False)
        self._quit_action = Action(
            wx.ID_EXIT,
            '',
            wx.AcceleratorEntry(wx.ACCEL_CTRL, ord('Q')),
            # NOTE: Action is bound to self._on_quit later manually
            action_func=None,
            enabled=True)
        
        # Edit
        self._preferences_action = Action(
            wx.ID_PREFERENCES,
            '',
            wx.AcceleratorEntry(wx.ACCEL_CTRL, ord(',')),
            # NOTE: Action is bound to self._on_preferences later manually
            action_func=None,
            enabled=True,
            button_label='&Preferences...')
        
        # Entity
        self._new_root_url_action = Action(wx.ID_ANY,
            'New &Root URL...',
            wx.AcceleratorEntry(wx.ACCEL_CTRL, ord('R')),
            self._on_add_url,
            enabled=(not self._readonly))
        self._new_group_action = Action(wx.ID_ANY,
            'New &Group...',
            wx.AcceleratorEntry(wx.ACCEL_CTRL, ord('G')),
            self._on_add_group,
            enabled=(not self._readonly))
        self._forget_action = Action(wx.ID_ANY,
            '&Forget',
            wx.AcceleratorEntry(wx.ACCEL_CTRL, wx.WXK_BACK),
            self._on_remove_entity,
            enabled=False)
        self._download_action = Action(wx.ID_ANY,
            '&Download',
            wx.AcceleratorEntry(wx.ACCEL_CTRL, wx.WXK_RETURN),
            self._on_download_entity,
            enabled=False)
        self._update_membership_action = Action(wx.ID_ANY,
            'Update &Membership',
            accel=None,
            action_func=self._on_update_group_membership,
            enabled=False)
        self._view_action = Action(wx.ID_ANY,
            '&View',
            wx.AcceleratorEntry(wx.ACCEL_CTRL|wx.ACCEL_SHIFT, ord('O')),
            self._on_view_entity,
            enabled=False)
        
        # HACK: Gather all actions indirectly by inspecting fields
        self._actions = [a for a in self.__dict__.values() if isinstance(a, Action)]
    
    # === Menubar ===
    
    def _create_menu_bar(self, raw_frame: wx.Frame) -> wx.MenuBar:
        file_menu = wx.Menu()
        self._new_project_action.append_menuitem_to(file_menu)
        self._open_project_action.append_menuitem_to(file_menu)
        file_menu.AppendSeparator()
        self._close_project_action.append_menuitem_to(file_menu)
        self._save_project_action.append_menuitem_to(file_menu)
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
        
        entity_menu = wx.Menu()
        self._new_root_url_action.append_menuitem_to(entity_menu)
        self._new_group_action.append_menuitem_to(entity_menu)
        self._forget_action.append_menuitem_to(entity_menu)
        entity_menu.AppendSeparator()
        self._download_action.append_menuitem_to(entity_menu)
        self._update_membership_action.append_menuitem_to(entity_menu)
        self._view_action.append_menuitem_to(entity_menu)
        
        menubar = wx.MenuBar()
        menubar.Append(file_menu, 'File')
        menubar.Append(edit_menu, 'Edit')
        menubar.Append(entity_menu, 'Entity')
        return menubar
    
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
        
        return self.entity_tree.peer
    
    def _create_button_bar(self, parent: wx.Window):
        readonly = self._readonly  # cache
        
        add_url_button = self._new_root_url_action.create_button(parent, name='cr-add-url-button')
        
        add_group_button = self._new_group_action.create_button(parent, name='cr-add-group-button')
        
        remove_entity_button = self._forget_action.create_button(parent, name='cr-forget-button')
        
        download_button = self._download_action.create_button(parent, name='cr-download-button')
        
        update_membership_button = self._update_membership_action.create_button(
            parent, name='cr-update-membership-button')
        
        view_button = self._view_action.create_button(parent, name='cr-view-button')
        
        content_sizer = wx.BoxSizer(wx.HORIZONTAL)
        content_sizer.Add(add_url_button)
        content_sizer.AddSpacer(_WINDOW_INNER_PADDING)
        content_sizer.Add(add_group_button)
        content_sizer.AddSpacer(_WINDOW_INNER_PADDING)
        content_sizer.Add(remove_entity_button)
        content_sizer.AddSpacer(_WINDOW_INNER_PADDING * 2)
        content_sizer.AddStretchSpacer()
        content_sizer.Add(download_button)
        content_sizer.AddSpacer(_WINDOW_INNER_PADDING)
        content_sizer.Add(update_membership_button)
        content_sizer.AddSpacer(_WINDOW_INNER_PADDING)
        content_sizer.Add(view_button)
        return content_sizer
    
    # === Entity Pane: Properties ===
    
    @property
    def _selection_initial_url(self):
        selected_entity = self.entity_tree.selected_entity
        if type(selected_entity) in (Resource, RootResource):
            return selected_entity.resource.url
        elif type(selected_entity) is ResourceGroup:
            return selected_entity.url_pattern
        else:
            return self.project.default_url_prefix
    
    @property
    def _selection_initial_source(self):
        selected_entity = self.entity_tree.selected_entity
        if type(selected_entity) in (Resource, RootResource):
            parent_of_selected_entity = self.entity_tree.parent_of_selected_entity
            if type(parent_of_selected_entity) in (ResourceGroup, RootResource):
                return parent_of_selected_entity
            else:
                return None
        elif type(selected_entity) is ResourceGroup:
            return selected_entity.source
        else:
            return None
    
    # === Operations ===
    
    def close(self) -> None:
        """
        Closes this window.
        
        The caller is still responsible for closing the underlying Project.
        """
        dummy_event = wx.CommandEvent()
        self._on_close_project(dummy_event)
    
    def __enter__(self) -> 'MainWindow':
        return self
    
    def __exit__(self, exc_type, exc_value, exc_traceback) -> None:
        self.close()
    
    # === File Menu: Events ===
    
    def _on_close_project(self, event: wx.CommandEvent) -> None:
        self.entity_tree.dispose()
        self.task_tree.dispose()
        self._frame.Close()
    
    def _on_quit(self, event: wx.CommandEvent) -> None:
        if event.Id == wx.ID_EXIT:
            set_is_quitting()
            self._frame.Close()
        else:
            event.Skip()
    
    def _on_close_frame(self, event: wx.CloseEvent) -> None:
        # Dispose actions early so that they don't try to interact with
        # wx.Objects in the frame while the frame is being deleted
        for a in self._actions:
            a.dispose()
        
        if self._log_drawer is not None:
            self._log_drawer.close()
        if self._project_server is not None:
            self._project_server.close()
        
        event.Skip()  # continue dispose of frame
    
    # === Entity Pane: Events ===
    
    def _on_add_url(self, event: wx.CommandEvent) -> None:
        AddRootUrlDialog(
            self._frame, self._on_add_url_dialog_ok,
            initial_url=self._selection_initial_url)
    
    def _on_add_url_dialog_ok(self, name, url):
        # TODO: Validate user input:
        #       * Is name or url empty?
        #       * Is name or url already taken?
        RootResource(self.project, name, Resource(self.project, url))
    
    def _on_add_group(self, event):
        AddGroupDialog(
            self._frame, self._on_add_group_dialog_ok,
            self.project,
            initial_url=self._selection_initial_url,
            initial_source=self._selection_initial_source)
    
    def _on_add_group_dialog_ok(self, name: str, url_pattern: str, source):
        # TODO: Validate user input:
        #       * Is name or url_pattern empty?
        #       * Is name or url_pattern already taken?
        rg = ResourceGroup(self.project, name, url_pattern)
        rg.source = source
    
    def _on_remove_entity(self, event):
        self.entity_tree.selected_entity.delete()
        # TODO: This update() should happen in response to a delete
        #       event fired by the entity itself.
        self.entity_tree.update()
    
    def _on_download_entity(self, event) -> None:
        selected_entity = self.entity_tree.selected_entity
        assert selected_entity is not None
        
        # Show progress dialog if it will likely take a long time to start the download
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
        
        def bg_task() -> None:
            assert selected_entity is not None
            
            # Start download
            selected_entity.download(needs_result=False)
            
            # Close progress dialog, if applicable
            if progress_dialog is not None:
                def fg_task() -> None:
                    nonlocal progress_dialog
                    progress_dialog.Destroy()
                    progress_dialog = None  # unexport
                fg_call_and_wait(fg_task)
        bg_call_later(bg_task)
    
    def _on_update_group_membership(self, event):
        selected_entity = self.entity_tree.selected_entity
        selected_entity.update_membership()
    
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
                open_browser_context = self._cwd_set_to_writable_dir()  # type: ContextManager
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
    
    def start_server(self) -> 'ProjectServer':
        """
        Starts an HTTP server that serves pages from this project.
        
        If an HTTP server is already running, does nothing.
        """
        if self._project_server is None:
            self._log_drawer = LogDrawer(parent=self._frame)
            
            # TODO: If the server couldn't be started (ex: due to the default port being in
            #       use), report an appropriate error.
            self._project_server = ProjectServer(self.project, stdout=self._log_drawer.writer)
        
        return self._project_server
    
    def _on_selected_entity_changed(self, event):
        selected_entity = self.entity_tree.selected_entity  # cache
        readonly = self._readonly  # cache
        self._forget_action.enabled = (
            (not readonly) and
            type(selected_entity) in (ResourceGroup, RootResource))
        self._download_action.enabled = (
            (not readonly) and
            selected_entity is not None)
        self._update_membership_action.enabled = (
            (not readonly) and
            type(selected_entity) is ResourceGroup)
        self._view_action.enabled = (
            type(selected_entity) in (Resource, RootResource))
    
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
    
    # === Status Bar: Init ===
    
    def _create_status_bar(self, parent: wx.Window) -> wx.Sizer:
        readonly = self._readonly  # cache
        
        pane = parent
        pane_sizer = wx.BoxSizer(wx.HORIZONTAL)
        
        version_label = wx.StaticText(pane, label=f'Crystal v{crystal_version}')
        
        preferences_button = self._preferences_action.create_button(pane, name='cr-preferences-button')
        bind(preferences_button, wx.EVT_BUTTON, self._on_preferences)
        
        if readonly:
            rwi_label = '🔒' if not is_windows() else 'Read only'
            rwi_tooltip = 'Read only project'
        else:
            rwi_label = '✏️' if not is_windows() else 'Writable'
            rwi_tooltip = 'Writable project'
        read_write_icon = wx.StaticText(pane, label=rwi_label, name='cr-read-write-icon')
        read_write_icon.SetToolTip(rwi_tooltip)
        
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
        
        return pane_sizer
    
    # === Status Bar: Events ===
    
    def _on_preferences(self, event: wx.CommandEvent) -> None:
        if event.Id == wx.ID_PREFERENCES or isinstance(event.EventObject, wx.Button):
            PreferencesDialog(self._frame, self.project)
        else:
            event.Skip()
