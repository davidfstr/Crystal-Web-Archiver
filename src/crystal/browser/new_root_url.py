from collections.abc import Callable
from crystal.url_input import cleaned_url_is_at_site_root, UrlCleaner
from crystal.util.bulkheads import capture_crashes_to_stderr
from crystal.util.ellipsis import Ellipsis, EllipsisType
from crystal.util.test_mode import tests_are_running
from crystal.util.wx_bind import bind
from crystal.util.wx_dialog import (
    CreateButtonSizer, position_dialog_initially, ShowModal,
)
from crystal.util.wx_static_box_sizer import wrap_static_box_sizer_child
from crystal.util.xos import is_linux, is_windows, is_wx_gtk
from crystal.util.xthreading import fg_affinity, fg_call_later
from typing import Literal, Optional, Union
import wx

ChangePrefixCommand = Union[
    # Set prefix
    tuple[Literal['domain', 'directory'], str],
    # Clear prefix
    None,
    # Leave prefix unchanged
    EllipsisType,
]


_WINDOW_INNER_PADDING = 10
_FORM_LABEL_INPUT_SPACING = 5
_FORM_ROW_SPACING = 10
_BESIDE_OPTIONS_PADDING = 10

_OPTIONS_SHOWN_LABEL = 'Basic Options'
_OPTIONS_NOT_SHOWN_LABEL = 'Advanced Options'


class NewRootUrlDialog:
    _ID_SET_DOMAIN_PREFIX = 101
    _ID_SET_DIRECTORY_PREFIX = 102
    
    _ID_DOWNLOAD_IMMEDIATELY = 111
    _ID_CREATE_GROUP = 112
    
    _INITIAL_URL_WIDTH = 400  # in pixels
    _FIELD_TO_SPINNER_MARGIN = 5
    
    # NOTE: Only changed when tests are running
    _last_opened: 'Optional[NewRootUrlDialog]'=None
    
    _url_field: wx.TextCtrl
    _name_field: wx.TextCtrl
    _ok_button: wx.Button
    _cancel_button: wx.Button
    _options_button: wx.Button
    
    _download_immediately_checkbox: wx.CheckBox
    _create_group_checkbox: wx.CheckBox
    
    _set_as_default_domain_checkbox: wx.CheckBox
    _set_as_default_directory_checkbox: wx.CheckBox
    
    # === Init ===
    
    def __init__(self,
            parent: wx.Window,
            on_finish: Callable[[str, str, ChangePrefixCommand, bool, bool], None],
            url_exists_func: Callable[[str], bool],
            initial_url: str='',
            initial_name: str='',
            initial_set_as_default_domain: bool=False,
            initial_set_as_default_directory: bool=False,
            allow_set_as_default_domain_or_directory: bool=True,
            is_edit: bool=False,
            ) -> None:
        """
        Arguments:
        * parent -- parent wx.Window that this dialog is attached to.
        * on_finish -- called when OK pressed on dialog.
        * initial_url -- overrides the initial URL displayed.
        """
        self._on_finish = on_finish
        self._url_exists_func = url_exists_func
        self._did_own_prefix = (
            is_edit and
            (initial_set_as_default_domain or initial_set_as_default_directory)
        )
        self._is_edit = is_edit
        
        self._url_field_focused = False
        self._last_cleaned_url = None  # type: Optional[str]
        self._url_cleaner = None  # type: Optional[UrlCleaner]
        self._was_ok_pressed = False
        self._is_destroying_or_destroyed = False
        
        dialog = self.dialog = wx.Dialog(
            parent,
            title=('New Root URL' if not is_edit else 'Edit Root URL'),
            name='cr-new-root-url-dialog',
            style=wx.DEFAULT_DIALOG_STYLE|wx.RESIZE_BORDER)
        dialog_sizer = wx.BoxSizer(wx.VERTICAL)
        dialog.SetSizer(dialog_sizer)
        bind(dialog, wx.EVT_BUTTON, self._on_button)
        bind(dialog, wx.EVT_CLOSE, self._on_close)
        bind(dialog, wx.EVT_WINDOW_DESTROY, self._on_destroyed)
        
        dialog_sizer.Add(
            self._create_fields(dialog, initial_url, initial_name, is_edit),
            flag=wx.EXPAND|wx.ALL,
            border=_WINDOW_INNER_PADDING)
        
        if not is_edit:
            new_options_sizer = self._create_new_options(dialog)
            dialog_sizer.Add(
                new_options_sizer,
                flag=wx.EXPAND|wx.LEFT|wx.RIGHT|wx.BOTTOM,
                border=self._assert_same(
                    _WINDOW_INNER_PADDING,  # wx.LEFT|wx.RIGHT
                    _BESIDE_OPTIONS_PADDING,  # wx.BOTTOM
                ))
        
        self._advanced_options_sizer = self._create_advanced_options(
            dialog,
            initial_set_as_default_domain, initial_set_as_default_directory,
            allow_set_as_default_domain_or_directory)
        dialog_sizer.Add(
            self._advanced_options_sizer,
            flag=wx.EXPAND|wx.LEFT|wx.RIGHT|wx.BOTTOM,
            border=self._assert_same(
                _WINDOW_INNER_PADDING,  # wx.LEFT|wx.RIGHT
                _BESIDE_OPTIONS_PADDING,  # wx.BOTTOM
            ))
    
        dialog_sizer.Add(
            self._create_buttons(dialog, is_edit),
            flag=wx.EXPAND|wx.BOTTOM,
            border=_WINDOW_INNER_PADDING)
        
        self._update_ok_enabled()
        
        if not fields_hide_hint_when_focused():
            # Initialize focus
            if not is_edit:
                self._url_field.SetFocus()
            else:
                self._name_field.SetFocus()
        
        position_dialog_initially(dialog)
        # TODO: Verify that the wxGTK-specific logic here is actually necessary
        if not is_wx_gtk():
            dialog.Fit()
            self._on_advanced_options_toggle()  # collapse options initially
            dialog.Show(True)
        else:
            dialog.Show(True)
            dialog.Fit()  # NOTE: Must Fit() after Show() here so that wxGTK actually fits correctly
            self._on_advanced_options_toggle()  # collapse options initially
        
        dialog.MinSize = dialog.Size
        # TODO: Clamp height to fixed value, but still allow
        #       dialog to change height when options shown/hidden
        dialog.MaxSize = wx.Size(wx.DefaultCoord, wx.DefaultCoord)
        
        # Export reference to self, if running tests
        if tests_are_running():
            NewRootUrlDialog._last_opened = self
    
    @staticmethod
    def _assert_same(v1: int, v2: int) -> int:
        assert v1 == v2
        return v1
    
    def _create_fields(self, parent: wx.Window, initial_url: str, initial_name: str, is_edit: bool) -> wx.Sizer:
        fields_sizer = wx.FlexGridSizer(rows=2, cols=2,
            vgap=_FORM_ROW_SPACING, hgap=_FORM_LABEL_INPUT_SPACING)
        fields_sizer.AddGrowableCol(1)
        if True:
            url_label = wx.StaticText(parent, label='URL:', style=wx.ALIGN_RIGHT)
            url_label.Font = url_label.Font.Bold()  # mark as required
            fields_sizer.Add(url_label, flag=wx.EXPAND)
            
            url_field_and_spinner = wx.BoxSizer(wx.HORIZONTAL)
            spinner_diameter: int
            if True:
                self._url_field = wx.TextCtrl(
                    parent, value=initial_url,
                    size=(self._INITIAL_URL_WIDTH, wx.DefaultCoord),
                    name='cr-new-root-url-dialog__url-field')
                self._url_field.Hint = 'https://example.com/'
                self._url_field.SetSelection(-1, -1)  # select all upon focus
                self._url_field.Enabled = not is_edit
                bind(self._url_field, wx.EVT_TEXT, self._on_url_field_changed)
                bind(self._url_field, wx.EVT_SET_FOCUS, self._on_url_field_focus)
                bind(self._url_field, wx.EVT_KILL_FOCUS, self._on_url_field_blur)
                url_field_and_spinner.Add(self._url_field, proportion=1, flag=wx.EXPAND)
                
                spinner_diameter = self._url_field.Size.Height
                self.url_cleaner_spinner = wx.ActivityIndicator(
                    parent,
                    size=wx.Size(spinner_diameter, spinner_diameter),
                    name='cr-new-root-url-dialog__url-cleaner-spinner')
                self.url_cleaner_spinner.Hide()
                url_field_and_spinner.Add(
                    self.url_cleaner_spinner,
                    flag=wx.LEFT|wx.RESERVE_SPACE_EVEN_IF_HIDDEN,
                    border=self._FIELD_TO_SPINNER_MARGIN)
            fields_sizer.Add(url_field_and_spinner, flag=wx.EXPAND)
            
            fields_sizer.Add(wx.StaticText(parent, label='Name:', style=wx.ALIGN_RIGHT), flag=wx.EXPAND)
            
            name_field_and_space = wx.BoxSizer(wx.HORIZONTAL)
            if True:
                self._name_field = wx.TextCtrl(
                    parent, value=initial_name,
                    name='cr-new-root-url-dialog__name-field')
                self._name_field.Hint = 'Home'
                self._name_field.SetSelection(-1, -1)  # select all upon focus
                name_field_and_space.Add(self._name_field, proportion=1, flag=wx.EXPAND)
                
                #name_field_and_space.Add(
                #    wx.Size(spinner_diameter, spinner_diameter),
                #    flag=wx.LEFT,
                #    border=self._FIELD_TO_SPINNER_MARGIN)
            fields_sizer.Add(name_field_and_space, flag=wx.EXPAND)
        
        return fields_sizer
    
    def _create_new_options(self, parent: wx.Window) -> wx.StaticBoxSizer:
        options_sizer = wx.StaticBoxSizer(wx.VERTICAL, parent, label='New URL Options')
        options_sizer.Add(
            wrap_static_box_sizer_child(
                self._create_new_options_content(
                    options_sizer.GetStaticBox())),
            flag=wx.EXPAND)
        return options_sizer
    
    def _create_new_options_content(self, parent: wx.Window) -> wx.Sizer:
        options_sizer = wx.BoxSizer(wx.VERTICAL)
        
        self._download_immediately_checkbox = wx.CheckBox(parent,
            id=self._ID_DOWNLOAD_IMMEDIATELY,
            label='Download Immediately',
            name='cr-new-root-url-dialog__download-immediately-checkbox')
        self._download_immediately_checkbox.Value = True
        options_sizer.Add(self._download_immediately_checkbox,
            flag=wx.BOTTOM,
            border=_FORM_LABEL_INPUT_SPACING)
        
        self._create_group_checkbox = wx.CheckBox(parent,
            id=self._ID_CREATE_GROUP,
            label='Create Group to Download Entire Site',
            name='cr-new-root-url-dialog__create-group-checkbox')
        self._create_group_checkbox.Value = False
        options_sizer.Add(self._create_group_checkbox,
            flag=wx.BOTTOM,
            border=5)
        
        only_simple_sites_label = wx.StaticText(parent, label='')
        only_simple_sites_label.ForegroundColour = \
            wx.Colour(102, 102, 102)  # gray
        only_simple_sites_label.Font = only_simple_sites_label.Font.MakeSmaller()
        # NOTE: Underline formatting is not supported on Windows,
        #       even when using GenStaticText as an alternative to wx.StaticText
        only_simple_sites_label.SetLabelMarkup(
            'Only recommended for downloading <u>simple sites</u>')
        # NOTE: Altering the label's cursor on wxGTK also seems to set
        #       the cursor of its enclosing Sizer as a side effect,
        #       which is confusing. So don't set any cursor on wxGTK.
        if not is_wx_gtk():
            only_simple_sites_label.Cursor = wx.Cursor(wx.CURSOR_QUESTION_ARROW)
        only_simple_sites_label.ToolTip = (
            'A simple website is created by a single person only, '
            'may contain text and images but not video, '
            'and does not requiring logging in to view its content.'
        )
        options_sizer.Add(only_simple_sites_label,
            flag=wx.LEFT,
            border=(
                17 if is_windows() else
                24 if is_linux() else
                20  # macOS
            ))
        
        bind(parent, wx.EVT_CHECKBOX, self._on_checkbox)
        
        self._update_create_group_enabled()
        self._update_download_immediately_label()
        
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
            initial_set_as_default_domain: bool,
            initial_set_as_default_directory: bool,
            allow_set_as_default_domain_or_directory: bool,
            ) -> wx.Sizer:
        options_sizer = wx.BoxSizer(wx.VERTICAL)
        
        self._set_as_default_domain_checkbox = wx.CheckBox(parent,
            id=self._ID_SET_DOMAIN_PREFIX,
            label='Set As Default Domain',
            name='cr-new-root-url-dialog__set-as-default-domain-checkbox')
        self._set_as_default_domain_checkbox.Value = initial_set_as_default_domain
        self._set_as_default_domain_checkbox.Enabled = allow_set_as_default_domain_or_directory
        options_sizer.Add(self._set_as_default_domain_checkbox,
            flag=wx.BOTTOM,
            border=_FORM_LABEL_INPUT_SPACING)
        
        self._set_as_default_directory_checkbox = wx.CheckBox(parent,
            id=self._ID_SET_DIRECTORY_PREFIX,
            label='Set As Default Directory',
            name='cr-new-root-url-dialog__set-as-default-directory-checkbox')
        self._set_as_default_directory_checkbox.Value = initial_set_as_default_directory
        self._set_as_default_directory_checkbox.Enabled = allow_set_as_default_domain_or_directory
        options_sizer.Add(self._set_as_default_directory_checkbox)
        
        bind(parent, wx.EVT_CHECKBOX, self._on_checkbox)
        
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
        
        self._ok_button = parent.FindWindow(id=ok_button_id)
        self._cancel_button = parent.FindWindow(id=wx.ID_CANCEL)
        
        return button_sizer
    
    # === URL Cleaning ===
    
    @fg_affinity
    def _on_url_cleaner_running_changed(self, running: bool) -> None:
        if self._is_destroying_or_destroyed:
            return
        
        if running:
            self.url_cleaner_spinner.Show()
            self.url_cleaner_spinner.Start()
        else:
            self.url_cleaner_spinner.Hide()
            self.url_cleaner_spinner.Stop()
            
            self._url_cleaner = None
            
            if self._was_ok_pressed:
                # Continue executing the OK action
                self._on_ok()

    @fg_affinity
    def _set_cleaned_url(self, cleaned_url: str) -> None:
        if self._is_destroying_or_destroyed:
            return
        
        self._last_cleaned_url = cleaned_url
        if self._url_field.Value != cleaned_url:
            self._url_field.Value = cleaned_url
    
    # === Events ===
    
    @fg_affinity
    def _on_url_field_changed(self, event=None) -> None:
        self._update_create_group_enabled()
        self._update_ok_enabled()
    
    # NOTE: Focus event can be called multiple times without an intermediate blur event
    @fg_affinity
    def _on_url_field_focus(self, event: wx.FocusEvent) -> None:
        # NOTE: Cannot use _url_field.HasFocus() because doesn't work in automated tests
        if self._url_field_focused:
            # Already did focus action
            return
        self._url_field_focused = True
        
        # If field still focused after a tick,
        # stop cleaning any old URL input
        @capture_crashes_to_stderr  # no good location in UI to route crashes too
        def fg_task() -> None:
            # NOTE: Cannot use _url_field.HasFocus() because doesn't work in automated tests
            if not self._url_field_focused:
                return
            
            # Stop cleaning any old URL input
            if self._url_cleaner is not None:
                self._url_cleaner.cancel()
                self._url_cleaner = None
        fg_call_later(fg_task, force_later=True)
        
        # Continue processing event in the normal fashion
        event.Skip()
    
    # NOTE: Blur event can be called multiple times without an intermediate focus event
    # NOTE: Blur event can be called while dialog is being destroyed
    @fg_affinity
    def _on_url_field_blur(self, event: wx.FocusEvent | None=None) -> None:
        if not self._url_field_focused:
            # Already did blur action
            return
        self._url_field_focused = False
        
        if self._is_destroying_or_destroyed:
            return
        
        # Start cleaning the new URL input
        url_input = self._url_field.Value
        if url_input == self._last_cleaned_url:
            # URL is already clean
            pass
        else:
            if self._url_cleaner is None or self._url_cleaner.url_input != url_input:
                if self._url_cleaner is not None:
                    self._url_cleaner.cancel()
                    self._url_cleaner = None
                
                self._url_cleaner = UrlCleaner(
                    url_input,
                    self._on_url_cleaner_running_changed,
                    self._set_cleaned_url)
                self._url_cleaner.start()
                # (NOTE: self._url_cleaner may be None now)
        
        # Continue processing event in the normal fashion
        if event is not None:
            event.Skip()
    
    @fg_affinity
    def _on_button(self, event: wx.CommandEvent) -> None:
        btn_id = event.GetEventObject().GetId()
        if btn_id in (wx.ID_NEW, wx.ID_SAVE):
            self._on_ok(event)
        elif btn_id == wx.ID_CANCEL:
            self._on_cancel(event)
        elif btn_id == wx.ID_MORE:
            self._on_advanced_options_toggle()
    
    @fg_affinity
    def _on_checkbox(self, event: wx.CommandEvent) -> None:
        checkbox_id = event.GetEventObject().GetId()
        if checkbox_id == self._ID_CREATE_GROUP:
            self._update_download_immediately_label()
        elif checkbox_id == self._ID_SET_DOMAIN_PREFIX:
            if self._set_as_default_domain_checkbox.Value:
                self._set_as_default_directory_checkbox.Value = False
        elif checkbox_id == self._ID_SET_DIRECTORY_PREFIX:
            if self._set_as_default_directory_checkbox.Value:
                self._set_as_default_domain_checkbox.Value = False
    
    @fg_affinity
    def _on_close(self, event: wx.CloseEvent) -> None:
        self._on_cancel(event)
    
    @fg_affinity
    def _on_ok(self, event: wx.CommandEvent | None=None) -> None:
        # Blur text fields so that they save their contents
        self._on_url_field_blur()
        
        # If URL input is being cleaned, wait for it to finish before continuing
        if self._url_cleaner is not None:
            self._url_field.Enabled = False
            self._name_field.Enabled = False
            self._ok_button.Enabled = False
            assert self._cancel_button.Enabled == True
            
            self._was_ok_pressed = True
            return
        
        name = self._name_field.Value
        url = self._url_field.Value
        if not self._is_edit and self._url_exists_func(url):
            dialog = wx.MessageDialog(
                self.dialog,
                message='That root URL already exists in the project.',
                caption='Root URL Exists',
                style=wx.OK,
            )
            dialog.Name = 'cr-root-url-exists'
            position_dialog_initially(dialog)
            choice = ShowModal(dialog)
            assert wx.ID_OK == choice
            
            self._url_field.Enabled = True
            self._name_field.Enabled = True
            self._ok_button.Enabled = True
            assert self._cancel_button.Enabled == True
            return
        if self._set_as_default_domain_checkbox.Value:
            change_prefix_command = ('domain', url)  # type: ChangePrefixCommand
        elif self._set_as_default_directory_checkbox.Value:
            change_prefix_command = ('directory', url)
        else:
            change_prefix_command = None if self._did_own_prefix else Ellipsis
        if self._is_edit:
            download_immediately = False
            create_group = False
        else:
            download_immediately = self._download_immediately_checkbox.Value
            create_group = self._create_group_checkbox.Value
        self._on_finish(
            name, url, change_prefix_command,
            download_immediately, create_group)
        
        self._destroy()
    
    @fg_affinity
    def _on_cancel(self, event: wx.CommandEvent) -> None:
        # Stop cleaning any old URL input
        if self._url_cleaner is not None:
            self._url_cleaner.cancel()
            self._url_cleaner = None
        
        self._destroy()
    
    @fg_affinity
    def _on_advanced_options_toggle(self) -> None:
        options = self._advanced_options_sizer.GetStaticBox()
        if options.Shown:
            # Hide
            self._options_button.Label = _OPTIONS_NOT_SHOWN_LABEL
            
            options_height = options.Size.Height + _BESIDE_OPTIONS_PADDING
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
            options_height = options.Size.Height + _BESIDE_OPTIONS_PADDING
            self.dialog.SetSize(
                x=wx.DefaultCoord,
                y=wx.DefaultCoord,
                width=wx.DefaultCoord,
                height=self.dialog.Size.Height + options_height,
                sizeFlags=wx.SIZE_USE_EXISTING)
    
    @fg_affinity
    def _destroy(self) -> None:
        self._is_destroying_or_destroyed = True
        self.dialog.Destroy()
    
    @fg_affinity
    def _on_destroyed(self, event) -> None:
        self._is_destroying_or_destroyed = True
    
    # === Updates ===
    
    def _update_create_group_enabled(self) -> None:
        url = self._url_field.Value
        self._create_group_checkbox.Enabled = (
            url == '' or cleaned_url_is_at_site_root(url)
        )
        
        self._update_download_immediately_label()
    
    def _update_download_immediately_label(self) -> None:
        self._download_immediately_checkbox.Label = (
            'Download Site Immediately' if (
                self._create_group_checkbox.Enabled and
                self._create_group_checkbox.Value
            ) else 'Download URL Immediately'
        )
    
    def _update_ok_enabled(self) -> None:
        self._ok_button.Enabled = (self._url_field.Value != '')


def fields_hide_hint_when_focused() -> bool:
    return is_wx_gtk()
