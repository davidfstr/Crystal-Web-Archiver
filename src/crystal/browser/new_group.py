# TODO: Consider extracting functions shared between dialogs to own module
from collections.abc import Callable
from crystal.browser.entitytree import ResourceGroupNode, RootResourceNode
from crystal.browser.new_root_url import (
    fields_hide_hint_when_focused, NewRootUrlDialog,
)
from crystal.model import Project, ResourceGroup, ResourceGroupSource
from crystal.progress import CancelLoadUrls
from crystal.util.unicode_labels import decorate_label
from crystal.util.wx_bind import bind
from crystal.util.wx_dialog import (
    CreateButtonSizer, position_dialog_initially, ShowModal,
)
from crystal.util.wx_static_box_sizer import wrap_static_box_sizer_child
from crystal.util.xos import is_linux, is_mac_os, is_windows
from crystal.util.xthreading import fg_affinity
import wx

_WINDOW_INNER_PADDING = 10
_FORM_LABEL_INPUT_SPACING = 5
_FORM_ROW_SPACING = 10
_SCROLL_RATE = 20
_ABOVE_OPTIONS_PADDING = 10

_OPTIONS_SHOWN_LABEL = 'Basic Options'
_OPTIONS_NOT_SHOWN_LABEL = 'Advanced Options'


class NewGroupDialog:
    _INITIAL_URL_PATTERN_WIDTH = NewRootUrlDialog._INITIAL_URL_WIDTH
    _MAX_VISIBLE_PREVIEW_URLS = 100
    _SHOW_SEQUENTIAL_OPTION = False  # hide feature until it is finished
    
    # === Init ===
    
    def __init__(self,
            parent: wx.Window,
            on_finish: Callable[[str, str, ResourceGroupSource, bool, bool], None],
            project: Project,
            saving_source_would_create_cycle_func: Callable[[ResourceGroupSource], bool],
            initial_url_pattern: str='',
            initial_source: ResourceGroupSource=None,
            initial_name: str='',
            initial_do_not_download: bool=False,
            is_edit: bool=False,
            ) -> None:
        """
        Arguments:
        * parent -- parent wx.Window that this dialog is attached to.
        * on_finish -- called when OK pressed on dialog. Is a callable(name, url_pattern, source).
        * project -- the project.
        * initial_url_pattern -- overrides the initial URL pattern displayed.
        * initial_source -- overrides the initial source displayed.
        * initial_name -- overrides the initial name displayed.
        
        Raises:
        * CancelLoadUrls
        """
        self._project = project
        self._on_finish = on_finish
        self._saving_source_would_create_cycle_func = saving_source_would_create_cycle_func
        self._is_edit = is_edit
        
        # Show progress dialog in advance if will need to load all project URLs
        try:
            project.load_urls()
        except CancelLoadUrls:
            raise
        
        dialog = self.dialog = wx.Dialog(
            parent,
            title=('New Group' if not is_edit else 'Edit Group'),
            name='cr-new-group-dialog',
            style=wx.DEFAULT_DIALOG_STYLE|wx.RESIZE_BORDER)
        dialog_sizer = wx.BoxSizer(wx.VERTICAL)
        dialog.SetSizer(dialog_sizer)
        bind(dialog, wx.EVT_BUTTON, self._on_button)
        bind(dialog, wx.EVT_CLOSE, self._on_close)
        
        content_sizer = wx.BoxSizer(wx.VERTICAL)
        content_sizer.Add(
            self._create_fields(dialog, initial_url_pattern, initial_source, initial_name, is_edit),
            flag=wx.EXPAND)
        (
            preview_box,
            preview_box_flags,
            preview_box_border,
        ) = self._create_preview_box(dialog)
        content_sizer.Add(
            preview_box,
            proportion=1,
            flag=wx.EXPAND|preview_box_flags,
            border=preview_box_border)
        
        if not is_edit:
            new_options_sizer = self._create_new_options(dialog)
            content_sizer.Add(
                new_options_sizer,
                flag=wx.EXPAND|wx.TOP,
                border=_ABOVE_OPTIONS_PADDING)
        
        self._advanced_options_sizer = self._create_advanced_options(dialog, initial_do_not_download)
        content_sizer.Add(
            self._advanced_options_sizer,
            flag=wx.EXPAND|wx.TOP,
            border=_ABOVE_OPTIONS_PADDING)
        
        dialog_sizer.Add(content_sizer, proportion=1, flag=wx.EXPAND|wx.ALL,
            border=_WINDOW_INNER_PADDING)
        dialog_sizer.Add(self._create_buttons(dialog, is_edit), flag=wx.EXPAND|wx.BOTTOM,
            border=_WINDOW_INNER_PADDING)
        
        if not fields_hide_hint_when_focused():
            # Initialize focus
            if not is_edit:
                self.pattern_field.SetFocus()
            else:
                self.name_field.SetFocus()
        self._update_preview_urls()
        
        position_dialog_initially(dialog)
        dialog.Fit()
        self._on_options_toggle()  # collapse options initially
        dialog.Show(True)
        
        dialog.MinSize = dialog.Size
        # TODO: Clamp height to fixed value, but still allow
        #       dialog to change height when options shown/hidden
        dialog.MaxSize = wx.Size(wx.DefaultCoord, wx.DefaultCoord)
    
    def _create_fields(self,
            parent: wx.Window,
            initial_url_pattern: str,
            initial_source: ResourceGroupSource,
            initial_name: str,
            is_edit: bool,
            ) -> wx.Sizer:
        fields_sizer = wx.FlexGridSizer(cols=2,
            vgap=_FORM_ROW_SPACING, hgap=_FORM_LABEL_INPUT_SPACING)
        fields_sizer.AddGrowableCol(1)
        
        pattern_field_sizer = wx.BoxSizer(wx.VERTICAL)
        self.pattern_field = wx.TextCtrl(
            parent, value=initial_url_pattern,
            size=(self._INITIAL_URL_PATTERN_WIDTH, wx.DefaultCoord),
            name='cr-new-group-dialog__pattern-field')
        bind(self.pattern_field, wx.EVT_TEXT, self._on_pattern_field_changed)
        self.pattern_field.Hint = 'https://example.com/post/*'
        self.pattern_field.SetSelection(-1, -1)  # select all upon focus
        self.pattern_field.Enabled = not is_edit
        pattern_field_sizer.Add(self.pattern_field, flag=wx.EXPAND)
        pattern_field_sizer.Add(wx.StaticText(parent, label='# = numbers, @ = letters, * = anything but /, ** = anything'), flag=wx.EXPAND)
        
        pattern_label = wx.StaticText(parent, label='URL Pattern:', style=wx.ALIGN_RIGHT|wx.ALIGN_TOP)
        pattern_label.Font = pattern_label.Font.Bold()  # mark as required
        fields_sizer.Add(pattern_label, flag=wx.EXPAND)
        fields_sizer.Add(pattern_field_sizer, flag=wx.EXPAND)
        
        fields_sizer.Add(wx.StaticText(parent, label='Source:', style=wx.ALIGN_RIGHT), flag=wx.EXPAND)
        self.source_choice_box = wx.Choice(
            parent,
            name='cr-new-group-dialog__source-field')
        self.source_choice_box.Append('none', None)
        for rr in self._project.root_resources:
            self.source_choice_box.Append(
                decorate_label(
                    RootResourceNode.ICON,
                    RootResourceNode.calculate_title_of(rr),
                    RootResourceNode.ICON_TRUNCATION_FIX),
                rr)
        for rg in self._project.resource_groups:
            self.source_choice_box.Append(
                decorate_label(
                    ResourceGroupNode.ICON,
                    ResourceGroupNode.calculate_title_of(rg),
                    ResourceGroupNode.ICON_TRUNCATION_FIX),
                rg)
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
            parent, value=initial_name,
            name='cr-new-group-dialog__name-field')
        self.name_field.Hint = 'Post'
        self.name_field.SetSelection(-1, -1)  # select all upon focus
        fields_sizer.Add(self.name_field, flag=wx.EXPAND)
        
        return fields_sizer
    
    def _create_preview_box(self, parent: wx.Window) -> tuple[wx.Window | wx.Sizer, int, int]:
        # NOTE: Don't use wx.CollapsiblePane on wxGTK/Linux because
        #       it doesn't resize its parent window properly on
        #       expand and unexpand events
        preview_box_collapsible = not is_linux()
        preview_box: wx.Window | wx.Sizer
        preview_box_root: wx.Window
        preview_box_root_sizer: wx.BoxSizer
        preview_box_flags: int
        preview_box_border: int
        if preview_box_collapsible:
            preview_box = wx.CollapsiblePane(
                parent, label='Preview Members',
                name='cr-new-group-dialog__preview-members')
            preview_box.Expand()
            preview_box_root = preview_box.GetPane()
            preview_box_root_sizer = wx.BoxSizer(wx.VERTICAL)
            preview_box_root.SetSizer(preview_box_root_sizer)
            preview_box_flags = 0
            preview_box_border = 0
        else:
            preview_box_root_sizer = wx.StaticBoxSizer(
                wx.VERTICAL, parent, label='Preview Members')
            preview_box = preview_box_root_sizer
            preview_box_root = preview_box_root_sizer.GetStaticBox()
            preview_box_flags = wx.TOP
            preview_box_border = 10
        
        preview_box_root_sizer.Add(
            wrap_static_box_sizer_child(
                self._create_preview_box_content(preview_box_root)),
            proportion=1,
            flag=wx.EXPAND)
        
        return (
            preview_box,
            preview_box_flags,
            preview_box_border,
        )
    
    def _create_preview_box_content(self, parent: wx.Window) -> wx.Sizer:
        content_sizer = wx.BoxSizer(wx.VERTICAL)
        
        self.url_list = wx.ListBox(
            parent, style=wx.LB_ALWAYS_SB, size=(-1,150),
            name='cr-new-group-dialog__preview-members__list')
        
        content_sizer.Add(wx.StaticText(parent, label='Known matching URLs:'), flag=wx.EXPAND)
        content_sizer.Add(self.url_list, proportion=1, flag=wx.EXPAND)
        
        return content_sizer
    
    def _create_new_options(self, parent: wx.Window) -> wx.StaticBoxSizer:
        options_sizer = wx.StaticBoxSizer(wx.VERTICAL, parent, label='New Group Options')
        options_sizer.Add(
            wrap_static_box_sizer_child(
                self._create_new_options_content(
                    options_sizer.GetStaticBox())),
            flag=wx.EXPAND)
        return options_sizer
    
    def _create_new_options_content(self, parent: wx.Window) -> wx.Sizer:
        options_sizer = wx.BoxSizer(wx.VERTICAL)
        
        self._download_immediately_checkbox = wx.CheckBox(parent,
            label='Download Group Immediately',
            name='cr-new-group-dialog__download-immediately-checkbox')
        self._download_immediately_checkbox.Value = False
        options_sizer.Add(self._download_immediately_checkbox,
            flag=wx.BOTTOM,
            border=_FORM_LABEL_INPUT_SPACING)
        
        return options_sizer
    
    def _create_advanced_options(self, parent: wx.Window, *args, **kwargs) -> wx.StaticBoxSizer:
        options_sizer = wx.StaticBoxSizer(wx.VERTICAL, parent, label='Advanced Options')
        options_sizer.Add(
            wrap_static_box_sizer_child(
                self._create_advanced_options_content(
                    options_sizer.GetStaticBox(),
                    *args, **kwargs)),
            flag=wx.EXPAND)
        return options_sizer
    
    def _create_advanced_options_content(self,
            parent: wx.Window,
            initial_do_not_download: bool,
            ) -> wx.Sizer:
        options_sizer = wx.BoxSizer(wx.VERTICAL)
        
        self.do_not_download_checkbox = wx.CheckBox(
            parent, label='Do not download members when embedded',
            name='cr-new-group-dialog__do-not-download-checkbox')
        self.do_not_download_checkbox.Value = initial_do_not_download
        options_sizer.Add(self.do_not_download_checkbox,
            flag=wx.BOTTOM,
            border=_FORM_LABEL_INPUT_SPACING)
        
        if self._SHOW_SEQUENTIAL_OPTION:
            options_sizer.AddSpacer(_FORM_ROW_SPACING)
            
            sequential_row = wx.BoxSizer(wx.HORIZONTAL)
            if True:
                self.sequential_checkbox = wx.CheckBox(
                    parent, label='Sequential members',
                    name='cr-new-group-dialog__sequential-checkbox')
                minimum_choice_values = ['0', '1', '2']
                # TODO: Allow the user to specify any integer value, via a wx.ComboBox
                self.minimum_choice_box = wx.Choice(
                    parent,
                    choices=minimum_choice_values)
                self.minimum_choice_box.Selection = minimum_choice_values.index('2')
                
                sequential_row.Add(self.sequential_checkbox, flag=wx.CENTER)
                sequential_row.Add(wx.StaticText(parent, label='–'), flag=wx.CENTER)
                sequential_row.AddSpacer(_FORM_LABEL_INPUT_SPACING)
                sequential_row.Add(wx.StaticText(parent, label='Minimum:'), flag=wx.CENTER)
                sequential_row.AddSpacer(_FORM_LABEL_INPUT_SPACING)
                sequential_row.Add(self.minimum_choice_box, flag=wx.CENTER)
                
            options_sizer.Add(sequential_row)
            
            wildcard_row_scroller = wx.ScrolledWindow(parent, style=wx.HSCROLL|wx.ALWAYS_SHOW_SB)
            if True:
                wildcard_row = wx.BoxSizer(wx.HORIZONTAL)
                if True:
                    url_pattern_fragments = [
                        'https://xkcd.com/',
                        '/',
                        #'/longlonglonglonglonglonglonglonglonglonglonglonglonglonglonglonglonglongmoremoremore',
                    ]
                    url_pattern_wildcards = ['#']
                    assert len(url_pattern_fragments) == len(url_pattern_wildcards) + 1
                    
                    wildcard_labels = [
                        wx.StaticText(wildcard_row_scroller, label=upf)
                        for upf in url_pattern_fragments
                    ]
                    for wl in wildcard_labels:
                        wl.SetForegroundColour(
                            wx.Colour(
                                255 * 5//8,
                                255 * 5//8,
                                255 * 5//8,
                            )  # light gray
                        )
                    
                    wildcard_buttons = [
                        wx.RadioButton(
                            wildcard_row_scroller,
                            label=upw,
                            style=(wx.RB_GROUP if i == 0 else 0))
                        for (i, upw) in enumerate(url_pattern_wildcards)
                    ]
                    wildcard_buttons[0].Value = True  # select first wildcard by default
                    
                    for (wl, wb) in zip(wildcard_labels, wildcard_buttons):
                        wildcard_row.Add(wl, flag=wx.CENTER)
                        wildcard_row.AddSpacer(_FORM_LABEL_INPUT_SPACING)
                        wildcard_row.Add(wb, flag=wx.CENTER)
                        wildcard_row.AddSpacer(_FORM_LABEL_INPUT_SPACING)
                    wildcard_row.Add(wildcard_labels[-1], flag=wx.CENTER)
                
                # NOTE: MUST SetScrollRate to something for scrollbars to work 
                wildcard_row_scroller.SetScrollRate(_SCROLL_RATE, 0)
                
                wildcard_row_scroller.SetSizer(wildcard_row)
                virtual_size = wildcard_row.ComputeFittingWindowSize(wildcard_row_scroller)
                wildcard_row_scroller.SetMinSize(wx.Size(
                    # Prevent scroller's min width from inheriting its virtual min width,
                    # so that the parent can define the width of the scroller
                    0,
                    # Force scroller's min height to match its virtual min height
                    virtual_size.Height
                ))
            
            if is_mac_os():
                checkbox_text_x = 20
            elif is_windows():
                checkbox_text_x = 16
            elif is_linux():
                checkbox_text_x = 24
            else:
                raise AssertionError()
            options_sizer.Add(
                wildcard_row_scroller,
                flag=wx.LEFT|wx.EXPAND,
                # Indent the wildcard row such that its left edge aligns with
                # the "Sequential members" checkbox label
                border=checkbox_text_x)
        
        return options_sizer
    
    def _create_buttons(self, parent: wx.Window, is_edit: bool) -> wx.Sizer:
        ok_button_id = (wx.ID_NEW if not is_edit else wx.ID_SAVE)
        
        button_sizer = wx.BoxSizer(wx.HORIZONTAL)
        
        self._options_button = wx.Button(parent, wx.ID_MORE, _OPTIONS_SHOWN_LABEL)
        button_sizer.Add(
            self._options_button,
            flag=wx.CENTER|wx.LEFT,
            border=_WINDOW_INNER_PADDING)
        
        button_sizer.AddStretchSpacer()
        button_sizer.Add(CreateButtonSizer(parent, ok_button_id, wx.ID_CANCEL), flag=wx.CENTER)
        return button_sizer
    
    # === Operations ===
    
    def _update_preview_urls(self) -> None:
        url_pattern = self.pattern_field.GetValue().strip()
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
    
    @fg_affinity
    def _on_button(self, event: wx.CommandEvent) -> None:
        btn_id = event.GetEventObject().GetId()
        if btn_id in (wx.ID_NEW, wx.ID_SAVE):
            self._on_ok()
        elif btn_id == wx.ID_CANCEL:
            self._on_cancel()
        elif btn_id == wx.ID_MORE:
            self._on_options_toggle()
    
    @fg_affinity
    def _on_close(self, event: wx.CloseEvent) -> None:
        self._on_cancel()
    
    @fg_affinity
    def _on_ok(self) -> None:
        name = self.name_field.Value
        url_pattern = self.pattern_field.Value.strip()
        if len(url_pattern) == 0:
            dialog = wx.MessageDialog(
                self.dialog,
                message='Please enter a URL pattern.',
                caption='Empty URL Pattern',
                style=wx.OK,
            )
            dialog.Name = 'cr-empty-url-pattern'
            position_dialog_initially(dialog)
            choice = ShowModal(dialog)
            assert wx.ID_OK == choice
            return
        source = self.source_choice_box.GetClientData(
            self.source_choice_box.GetSelection())
        if self._saving_source_would_create_cycle_func(source):
            dialog = wx.MessageDialog(
                self.dialog,
                message='Cannot use that Source because it has this group as a Source.',
                caption='Source Cycle Created',
                style=wx.OK,
            )
            dialog.Name = 'cr-source-cycle-created'
            position_dialog_initially(dialog)
            choice = ShowModal(dialog)
            assert wx.ID_OK == choice
            return
        do_not_download = self.do_not_download_checkbox.Value
        if self._is_edit:
            download_immediately = False
        else:
            download_immediately = self._download_immediately_checkbox.Value
        self._on_finish(
            name, url_pattern, source, do_not_download,
            download_immediately)
        
        self.dialog.Destroy()
    
    @fg_affinity
    def _on_cancel(self) -> None:
        self.dialog.Destroy()
    
    @fg_affinity
    def _on_options_toggle(self) -> None:
        options = self._advanced_options_sizer.GetStaticBox()
        if options.Shown:
            # Hide
            self._options_button.Label = _OPTIONS_NOT_SHOWN_LABEL
            
            options_height = options.Size.Height + _ABOVE_OPTIONS_PADDING
            options.Shown = False
            self.dialog.SetSize(
                x=wx.DefaultCoord,
                y=wx.DefaultCoord,
                width=wx.DefaultCoord,
                height=self.dialog.Size.Height - options_height,
                sizeFlags=wx.SIZE_USE_EXISTING)
        else:
            # Show
            self._options_button.Label = _OPTIONS_SHOWN_LABEL
            
            options.Shown = True
            options_height = options.Size.Height + _ABOVE_OPTIONS_PADDING
            self.dialog.SetSize(
                x=wx.DefaultCoord,
                y=wx.DefaultCoord,
                width=wx.DefaultCoord,
                height=self.dialog.Size.Height + options_height,
                sizeFlags=wx.SIZE_USE_EXISTING)
