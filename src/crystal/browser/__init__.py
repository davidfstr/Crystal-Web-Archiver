from crystal import __version__ as crystal_version
from crystal.browser.addgroup import AddGroupDialog
from crystal.browser.addrooturl import AddRootUrlDialog
from crystal.browser.entitytree import EntityTree
from crystal.browser.preferences import PreferencesDialog
from crystal.browser.tasktree import TaskTree
from crystal.model import Project, Resource, ResourceGroup, RootResource
from crystal.progress import OpenProjectProgressListener
from crystal.task import RootTask
from crystal.ui.BetterMessageDialog import BetterMessageDialog
from crystal.util.wx_bind import bind
from crystal.util.xos import is_mac_os, is_windows
import wx

_WINDOW_INNER_PADDING = 10


class MainWindow:
    entity_tree: EntityTree
    
    def __init__(self, project: Project, progress_listener: OpenProjectProgressListener) -> None:
        self.project = project
        
        frame = wx.Frame(None, title=project.title, name='cr-main-window')
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
        
        frame.Fit()
        frame.Show(True)
        
        self.frame = frame
    
    @property
    def _readonly(self) -> bool:
        return self.project.readonly
    
    # === Entity Pane: Init ===
    
    def _create_entity_pane(self, parent, progress_listener: OpenProjectProgressListener):
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
        content_sizer = wx.BoxSizer(wx.VERTICAL)
        content_sizer.Add(
            self._create_entity_tree(parent, progress_listener),
            proportion=1,
            flag=wx.EXPAND)
        content_sizer.AddSpacer(_WINDOW_INNER_PADDING)
        content_sizer.Add(self._create_button_bar(parent), flag=wx.EXPAND)
        return content_sizer
    
    def _create_entity_tree(self, parent: wx.Window, progress_listener: OpenProjectProgressListener):
        self.entity_tree = EntityTree(parent, self.project, progress_listener)
        bind(self.entity_tree.peer, wx.EVT_TREE_SEL_CHANGED, self._on_selected_entity_changed)
        
        return self.entity_tree.peer
    
    def _create_button_bar(self, parent: wx.Window):
        readonly = self._readonly  # cache
        
        add_url_button = wx.Button(parent, label='Add URL', name='cr-add-url-button')
        bind(add_url_button, wx.EVT_BUTTON, self._on_add_url)
        if readonly:
            add_url_button.Disable()
        
        add_group_button = wx.Button(parent, label='Add Group', name='cr-add-group-button')
        bind(add_group_button, wx.EVT_BUTTON, self._on_add_group)
        if readonly:
            add_group_button.Disable()
        
        self._remove_entity_button = wx.Button(parent, label='Forget', name='cr-forget-button')
        bind(self._remove_entity_button, wx.EVT_BUTTON, self._on_remove_entity)
        self._remove_entity_button.Disable()
        
        self._download_button = wx.Button(parent, label='Download', name='cr-download-button')
        bind(self._download_button, wx.EVT_BUTTON, self._on_download_entity)
        self._download_button.Disable()
        
        self._update_membership_button = wx.Button(parent, label='Update Membership', name='cr-update-membership-button')
        bind(self._update_membership_button, wx.EVT_BUTTON, self._on_update_group_membership)
        self._update_membership_button.Disable()
        
        self._view_button = wx.Button(parent, label='View', name='cr-view-button')
        bind(self._view_button, wx.EVT_BUTTON, self._on_view_entity)
        self._view_button.Disable()
        
        content_sizer = wx.BoxSizer(wx.HORIZONTAL)
        content_sizer.Add(add_url_button)
        content_sizer.AddSpacer(_WINDOW_INNER_PADDING)
        content_sizer.Add(add_group_button)
        content_sizer.AddSpacer(_WINDOW_INNER_PADDING)
        content_sizer.Add(self._remove_entity_button)
        content_sizer.AddSpacer(_WINDOW_INNER_PADDING * 2)
        content_sizer.AddStretchSpacer()
        content_sizer.Add(self._download_button)
        content_sizer.AddSpacer(_WINDOW_INNER_PADDING)
        content_sizer.Add(self._update_membership_button)
        content_sizer.AddSpacer(_WINDOW_INNER_PADDING)
        content_sizer.Add(self._view_button)
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
    
    # === Entity Pane: Events ===
    
    def _on_add_url(self, event):
        AddRootUrlDialog(
            self.frame, self._on_add_url_dialog_ok,
            initial_url=self._selection_initial_url)
    
    def _on_add_url_dialog_ok(self, name, url):
        # TODO: Validate user input:
        #       * Is name or url empty?
        #       * Is name or url already taken?
        RootResource(self.project, name, Resource(self.project, url))
        self.entity_tree.update()
    
    def _on_add_group(self, event):
        AddGroupDialog(
            self.frame, self._on_add_group_dialog_ok,
            self.project,
            initial_url=self._selection_initial_url,
            initial_source=self._selection_initial_source)
    
    def _on_add_group_dialog_ok(self, name, url_pattern, source):
        # TODO: Validate user input:
        #       * Is name or url_pattern empty?
        #       * Is name or url_pattern already taken?
        rg = ResourceGroup(self.project, name, url_pattern)
        rg.source = source
        self.entity_tree.update()
    
    def _on_remove_entity(self, event):
        self.entity_tree.selected_entity.delete()
        self.entity_tree.update()
    
    def _on_download_entity(self, event) -> None:
        selected_entity = self.entity_tree.selected_entity
        assert selected_entity is not None
        if self._alert_if_not_downloadable(selected_entity):
            return
        selected_entity.download(needs_result=False)
    
    def _on_update_group_membership(self, event):
        selected_entity = self.entity_tree.selected_entity
        if self._alert_if_not_downloadable(selected_entity):
            return
        selected_entity.update_membership()
    
    def _alert_if_not_downloadable(self, entity):
        """
        Displays an alert if the entity is a group without a source,
        which cannot be downloaded. Returns True if an alert was displayed.
        """
        if type(entity) is ResourceGroup and entity.source is None:
            # TODO: Would be great if we automatically gave the user the option
            #       to select a source for the group. Perhaps by automatically
            #       forwarding the user to the edit dialog for the group.
            dialog = BetterMessageDialog(self.frame,
                message=('The group "%s" does not have a source defined, which ' +
                    'prevents it from being downloaded.') % entity.name,
                title='No Source Defined',
                style=wx.OK)
            dialog.ShowModal()
            dialog.Destroy()
            return True
        else:
            return False
    
    def _on_view_entity(self, event) -> None:
        import crystal.server
        import webbrowser
        
        # TODO: If the server couldn't be started (ex: due to the default port being in
        #       use), report an appropriate error.
        project_server = self.project.start_server()
        
        selected_entity = self.entity_tree.selected_entity
        assert isinstance(selected_entity, (Resource, RootResource))
        archive_url = selected_entity.resource.url
        request_url = project_server.get_request_url(archive_url)
        webbrowser.open(request_url)
    
    def _on_selected_entity_changed(self, event):
        selected_entity = self.entity_tree.selected_entity  # cache
        readonly = self._readonly  # cache
        self._remove_entity_button.Enable(
            (not readonly) and
            type(selected_entity) in (ResourceGroup, RootResource))
        self._download_button.Enable(
            (not readonly) and
            selected_entity is not None)
        self._update_membership_button.Enable(
            (not readonly) and
            type(selected_entity) is ResourceGroup)
        self._view_button.Enable(
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
    
    def _create_status_bar(self, parent: wx.Window) -> wx.Window:
        readonly = self._readonly  # cache
        
        pane = wx.Panel(parent)
        pane_sizer = wx.BoxSizer(wx.HORIZONTAL)
        pane.SetSizer(pane_sizer)
        
        version_label = wx.StaticText(pane, label=f'v{crystal_version}')
        
        preferences_button = wx.Button(pane, label='Preferences...', name='cr-preferences-button')
        bind(preferences_button, wx.EVT_BUTTON, lambda event: PreferencesDialog(self.frame, self.project))
        
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
        
        return pane
