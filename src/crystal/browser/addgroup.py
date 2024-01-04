# TODO: Consider extracting functions shared between dialogs to own module
from crystal.browser.addrooturl import AddRootUrlDialog, fields_hide_hint_when_focused
from crystal.model import Project, ResourceGroup, ResourceGroupSource
from crystal.progress import CancelLoadUrls
from crystal.util.wx_bind import bind
from crystal.util.wx_dialog import position_dialog_initially
from crystal.util.wx_static_box_sizer import wrap_static_box_sizer_child
from crystal.util.xos import is_linux
import sys
from typing import Callable, Optional, Union
import wx


_WINDOW_INNER_PADDING = 10
_FORM_LABEL_INPUT_SPACING = 5
_FORM_ROW_SPACING = 10


class AddGroupDialog:
    _INITIAL_URL_PATTERN_WIDTH = AddRootUrlDialog._INITIAL_URL_WIDTH
    _MAX_VISIBLE_PREVIEW_URLS = 100
    
    # === Init ===
    
    def __init__(self,
            parent: wx.Window,
            on_finish: Callable[[str, str, ResourceGroupSource], None],
            project: Project,
            initial_url_pattern: str='',
            initial_source: Optional[ResourceGroupSource]=None,
            ) -> None:
        """
        Arguments:
        * parent -- parent wx.Window that this dialog is attached to.
        * on_finish -- called when OK pressed on dialog. Is a callable(name, url_pattern, source).
        * project -- the project.
        * initial_url_pattern -- overrides the initial URL pattern displayed.
        * initial_source -- overrides the initial source displayed.
        
        Raises:
        * CancelLoadUrls
        """
        self._project = project
        self._on_finish = on_finish
        
        # Show progress dialog in advance if will need to load all project URLs
        try:
            project.load_urls()
        except CancelLoadUrls:
            raise
        
        dialog = self.dialog = wx.Dialog(
            parent, title='New Group',
            name='cr-add-group-dialog',
            style=wx.DEFAULT_DIALOG_STYLE|wx.RESIZE_BORDER)
        dialog_sizer = wx.BoxSizer(wx.VERTICAL)
        dialog.SetSizer(dialog_sizer)
        bind(dialog, wx.EVT_BUTTON, self._on_button)
        bind(dialog, wx.EVT_CLOSE, self._on_close)
        
        # NOTE: Don't use wx.CollapsiblePane on wxGTK/Linux because
        #       it doesn't resize its parent window properly on
        #       expand and unexpand events
        preview_box_collapsible = not is_linux()
        preview_box: Union[wx.Window, wx.Sizer]
        preview_box_root: wx.Window
        preview_box_root_sizer: wx.BoxSizer
        preview_box_flags: int
        preview_box_border: int
        if preview_box_collapsible:
            preview_box = wx.CollapsiblePane(
                dialog, label='Preview Members',
                name='cr-add-group-dialog__preview-members')
            preview_box.Expand()
            preview_box_root = preview_box.GetPane()
            preview_box_root_sizer = wx.BoxSizer(wx.VERTICAL)
            preview_box_root.SetSizer(preview_box_root_sizer)
            preview_box_flags = 0
            preview_box_border = 0
        else:
            preview_box_root_sizer = wx.StaticBoxSizer(
                wx.VERTICAL, dialog, label='Preview Members')
            preview_box = preview_box_root_sizer
            preview_box_root = preview_box_root_sizer.GetStaticBox()
            preview_box_flags = wx.TOP
            preview_box_border = 10
        
        preview_box_root_sizer.Add(
            wrap_static_box_sizer_child(self._create_preview_box_content(preview_box_root)),
            proportion=1,
            flag=wx.EXPAND)
        
        content_sizer = wx.BoxSizer(wx.VERTICAL)
        content_sizer.Add(
            self._create_fields(dialog, initial_url_pattern, initial_source),
            flag=wx.EXPAND)
        content_sizer.Add(preview_box, proportion=1, flag=wx.EXPAND|preview_box_flags, border=preview_box_border)
        
        dialog_sizer.Add(content_sizer, proportion=1, flag=wx.EXPAND|wx.ALL,
            border=_WINDOW_INNER_PADDING)
        dialog_sizer.Add(dialog.CreateButtonSizer(wx.OK|wx.CANCEL), flag=wx.EXPAND|wx.BOTTOM,
            border=_WINDOW_INNER_PADDING)
        
        if not fields_hide_hint_when_focused():
            self.pattern_field.SetFocus()  # initialize focus
        self._update_preview_urls()
        
        position_dialog_initially(dialog)
        dialog.Show(True)
        dialog.Fit()
        
        dialog.MinSize = dialog.Size
        dialog.MaxSize = wx.Size(wx.DefaultCoord, wx.DefaultCoord)
    
    def _create_fields(self,
            parent: wx.Window,
            initial_url_pattern: str,
            initial_source: Optional[ResourceGroupSource]
            ) -> wx.Sizer:
        fields_sizer = wx.FlexGridSizer(cols=2,
            vgap=_FORM_ROW_SPACING, hgap=_FORM_LABEL_INPUT_SPACING)
        fields_sizer.AddGrowableCol(1)
        
        pattern_field_sizer = wx.BoxSizer(wx.VERTICAL)
        self.pattern_field = wx.TextCtrl(
            parent, value=initial_url_pattern,
            size=(self._INITIAL_URL_PATTERN_WIDTH, wx.DefaultCoord),
            name='cr-add-group-dialog__pattern-field')
        bind(self.pattern_field, wx.EVT_TEXT, self._on_pattern_field_changed)
        self.pattern_field.Hint = 'https://example.com/post/*'
        self.pattern_field.SetSelection(-1, -1)  # select all upon focus
        pattern_field_sizer.Add(self.pattern_field, flag=wx.EXPAND)
        pattern_field_sizer.Add(wx.StaticText(parent, label='# = digit, @ = alpha, * = any nonslash, ** = any'), flag=wx.EXPAND)
        
        pattern_label = wx.StaticText(parent, label='URL Pattern:', style=wx.ALIGN_RIGHT|wx.ALIGN_TOP)
        pattern_label.Font = pattern_label.Font.Bold()  # mark as required
        fields_sizer.Add(pattern_label, flag=wx.EXPAND)
        fields_sizer.Add(pattern_field_sizer, flag=wx.EXPAND)
        
        fields_sizer.Add(wx.StaticText(parent, label='Source:', style=wx.ALIGN_RIGHT), flag=wx.EXPAND)
        self.source_choice_box = wx.Choice(
            parent,
            name='cr-add-group-dialog__source-field')
        self.source_choice_box.Append('none', None)
        for rr in self._project.root_resources:
            self.source_choice_box.Append(rr.display_name, rr)
        for rg in self._project.resource_groups:
            self.source_choice_box.Append(rg.display_name, rg)
        self.source_choice_box.SetSelection(0)
        if initial_source is not None:
            for i in range(self.source_choice_box.GetCount()):
                cur_source = self.source_choice_box.GetClientData(i)
                if cur_source == initial_source:
                    self.source_choice_box.SetSelection(i)
                    break
        fields_sizer.Add(self.source_choice_box, flag=wx.EXPAND)
        
        fields_sizer.Add(wx.StaticText(parent, label='Name:', style=wx.ALIGN_RIGHT), flag=wx.EXPAND)
        self.name_field = wx.TextCtrl(
            parent,
            name='cr-add-group-dialog__name-field')
        self.name_field.Hint = 'Post'
        self.name_field.SetSelection(-1, -1)  # select all upon focus
        fields_sizer.Add(self.name_field, flag=wx.EXPAND)
        
        return fields_sizer
    
    def _create_preview_box_content(self, parent: wx.Window) -> wx.Sizer:
        content_sizer = wx.BoxSizer(wx.VERTICAL)
        
        self.url_list = wx.ListBox(
            parent, style=wx.LB_ALWAYS_SB, size=(-1,150),
            name='cr-add-group-dialog__preview-members__list')
        
        content_sizer.Add(wx.StaticText(parent, label='Known matching URLs:'), flag=wx.EXPAND)
        content_sizer.Add(self.url_list, proportion=1, flag=wx.EXPAND)
        
        return content_sizer
    
    # === Operations ===
    
    def _update_preview_urls(self) -> None:
        url_pattern = self.pattern_field.GetValue()
        url_pattern_re = ResourceGroup.create_re_for_url_pattern(url_pattern)
        literal_prefix = ResourceGroup.literal_prefix_for_url_pattern(url_pattern)
        
        url_pattern_is_literal = (len(literal_prefix) == len(url_pattern))
        if url_pattern_is_literal:
            member = self._project.get_resource(literal_prefix)
            if member is None:
                (matching_urls, approx_match_count) = ([], 0)
            else:
                (matching_urls, approx_match_count) = ([member.url], 1)
        else:
            (matching_urls, approx_match_count) = self._project.urls_matching_pattern(
                url_pattern_re, literal_prefix, limit=self._MAX_VISIBLE_PREVIEW_URLS)
        
        self.url_list.Clear()
        if len(matching_urls) > 0:  # avoid warning on Mac
            more_count = approx_match_count - len(matching_urls)
            more_items = (
                [f'... about {more_count:n} more']
                if more_count != 0
                else []
            )
            self.url_list.InsertItems(matching_urls + more_items, 0)
    
    # === Events ===
    
    def _on_pattern_field_changed(self, event) -> None:
        self._update_preview_urls()
    
    def _on_button(self, event: wx.CommandEvent) -> None:
        btn_id = event.GetEventObject().GetId()
        if btn_id == wx.ID_OK:
            self._on_ok(event)
        elif btn_id == wx.ID_CANCEL:
            self._on_cancel(event)
    
    def _on_close(self, event: wx.CloseEvent) -> None:
        self._on_cancel(event)
    
    def _on_ok(self, event: wx.CommandEvent) -> None:
        name = self.name_field.GetValue()
        url_pattern = self.pattern_field.GetValue()
        source = self.source_choice_box.GetClientData(
            self.source_choice_box.GetSelection())
        self._on_finish(name, url_pattern, source)
        self.dialog.Destroy()
    
    def _on_cancel(self, event: wx.CommandEvent) -> None:
        self.dialog.Destroy()
