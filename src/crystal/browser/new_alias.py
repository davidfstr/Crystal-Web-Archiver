from collections.abc import Callable
from crystal.util.test_mode import tests_are_running
from crystal.util.wx_bind import bind
from crystal.util.wx_clipboard import create_copy_button
from crystal.util.wx_dialog import (
    CreateButtonSizer, ShowModal, add_title_heading_to_dialog_if_needed, 
    position_dialog_initially, ShowWindowModal,
)
from crystal.util.wx_window import SetFocus
from crystal.util.xthreading import fg_affinity
from typing import Optional
import wx


_WINDOW_INNER_PADDING = 10
_FORM_LABEL_INPUT_SPACING = 5
_FORM_ROW_SPACING = 10

_INITIAL_URL_WIDTH = 400  # in pixels
_FIELD_TO_COPY_BUTTON_MARGIN = 5


class NewAliasDialog:
    _ID_TARGET_IS_EXTERNAL = 101
    
    # NOTE: Only changed when tests are running
    _last_opened: 'Optional[NewAliasDialog]'=None
    
    _source_url_prefix_field: wx.TextCtrl
    _target_url_prefix_field: wx.TextCtrl
    _target_is_external_checkbox: wx.CheckBox
    _ok_button: wx.Button
    _cancel_button: wx.Button
    
    # === Init ===
    
    def __init__(self,
            parent: wx.Window,
            on_finish: Callable[[str, str, bool], None],
            alias_exists_func: Callable[[str], bool],
            initial_source_url_prefix: str='',
            initial_target_url_prefix: str='',
            initial_target_is_external: bool=False,
            is_edit: bool=False,
            readonly: bool=False,
            on_close: Callable[[], None] | None = None,
            ) -> None:
        """
        Arguments:
        * parent -- parent wx.Window that this dialog is attached to.
        * on_finish -- called when OK pressed on dialog.
        * alias_exists_func -- function to check if an alias with given source_url_prefix already exists.
        * initial_source_url_prefix -- overrides the initial source URL prefix displayed.
        * initial_target_url_prefix -- overrides the initial target URL prefix displayed.
        * initial_target_is_external -- overrides the initial target_is_external value.
        * is_edit -- whether this is an edit dialog (source URL prefix cannot be changed).
        * readonly -- whether dialog is readonly (no edits allowed).
        * on_close -- optional callback called when dialog is closed.
        """
        self._on_finish = on_finish
        self._alias_exists_func = alias_exists_func
        self._is_edit = is_edit
        self._readonly = readonly
        self._on_close_callback = on_close or (lambda: None)
        
        self._source_url_prefix_field_focused = False
        self._target_url_prefix_field_focused = False
        self._is_destroying_or_destroyed = False

        dialog = self.dialog = wx.Dialog(
            parent,
            title=(
                'New Alias' if not is_edit else (
                    'Edit Alias' if not readonly else 
                    'Alias'
                )
            ),
            name='cr-new-alias-dialog',
            style=wx.DEFAULT_DIALOG_STYLE|wx.RESIZE_BORDER)
        dialog_sizer = wx.BoxSizer(wx.VERTICAL)
        dialog.SetSizer(dialog_sizer)
        bind(dialog, wx.EVT_BUTTON, self._on_button)
        bind(dialog, wx.EVT_CLOSE, self._on_close)
        bind(dialog, wx.EVT_WINDOW_DESTROY, self._on_destroyed)
        
        add_title_heading_to_dialog_if_needed(
            dialog,
            dialog_sizer,
            border=_WINDOW_INNER_PADDING)
        
        dialog_sizer.Add(
            self._create_fields(
                dialog, 
                initial_source_url_prefix, 
                initial_target_url_prefix,
                initial_target_is_external,
                is_edit),
            flag=wx.EXPAND|wx.ALL,
            border=_WINDOW_INNER_PADDING)
    
        dialog_sizer.Add(
            self._create_buttons(dialog, is_edit),
            flag=wx.EXPAND|wx.BOTTOM,
            border=_WINDOW_INNER_PADDING)
        
        self._update_ok_enabled()
        
        # Initialize focus
        if not is_edit:
            SetFocus(self._source_url_prefix_field)
        else:
            SetFocus(self._target_url_prefix_field)
        
        position_dialog_initially(dialog)
        dialog.Fit()
        ShowWindowModal(dialog)
        
        dialog.MinSize = dialog.Size
        dialog.MaxSize = wx.Size(wx.DefaultCoord, wx.DefaultCoord)
        
        # Export reference to self, if running tests
        if tests_are_running():
            NewAliasDialog._last_opened = self
    
    def _create_fields(self, 
            parent: wx.Window, 
            initial_source_url_prefix: str,
            initial_target_url_prefix: str,
            initial_target_is_external: bool,
            is_edit: bool) -> wx.Sizer:
        fields_sizer = wx.FlexGridSizer(rows=3, cols=2,
            vgap=_FORM_ROW_SPACING, hgap=_FORM_LABEL_INPUT_SPACING)
        fields_sizer.AddGrowableCol(1)
        
        # Source URL Prefix
        if True:
            source_label = wx.StaticText(parent, label='Source URL Prefix:', style=wx.ALIGN_RIGHT)
            source_label.Font = source_label.Font.Bold()  # mark as required
            fields_sizer.Add(source_label, flag=wx.EXPAND)
            
            source_field_and_copy = wx.BoxSizer(wx.HORIZONTAL)
            if True:
                self._source_url_prefix_field = wx.TextCtrl(
                    parent, value=initial_source_url_prefix,
                    size=(_INITIAL_URL_WIDTH, wx.DefaultCoord),
                    name='cr-new-alias-dialog__source-url-prefix-field')
                self._source_url_prefix_field.Hint = 'https://example.com/old/'
                self._source_url_prefix_field.SetSelection(-1, -1)  # select all upon focus
                self._source_url_prefix_field.Enabled = not is_edit and not self._readonly
                bind(self._source_url_prefix_field, wx.EVT_TEXT, self._on_source_url_prefix_field_changed)
                bind(self._source_url_prefix_field, wx.EVT_SET_FOCUS, self._on_source_url_prefix_field_focus)
                bind(self._source_url_prefix_field, wx.EVT_KILL_FOCUS, self._on_source_url_prefix_field_blur)
                source_field_and_copy.Add(self._source_url_prefix_field, proportion=1, flag=wx.EXPAND)
                
                copy_button = create_copy_button(
                    parent,
                    name='cr-new-alias-dialog__source-url-prefix-copy-button',
                    text_to_copy=lambda: self._source_url_prefix_field.Value,
                    parent_is_disposed=lambda: self._is_destroying_or_destroyed,
                    previously_focused_func=lambda: (
                        self._source_url_prefix_field if self._source_url_prefix_field_focused
                        else None
                    ))
                source_field_and_copy.Add(copy_button, flag=wx.LEFT|wx.CENTER, border=_FIELD_TO_COPY_BUTTON_MARGIN)
            fields_sizer.Add(source_field_and_copy, flag=wx.EXPAND)
        
        # Target URL Prefix
        if True:
            target_label = wx.StaticText(parent, label='Target URL Prefix:', style=wx.ALIGN_RIGHT)
            target_label.Font = target_label.Font.Bold()  # mark as required
            fields_sizer.Add(target_label, flag=wx.EXPAND)
            
            target_field_and_copy = wx.BoxSizer(wx.HORIZONTAL)
            if True:
                self._target_url_prefix_field = wx.TextCtrl(
                    parent, value=initial_target_url_prefix,
                    size=(_INITIAL_URL_WIDTH, wx.DefaultCoord),
                    name='cr-new-alias-dialog__target-url-prefix-field')
                self._target_url_prefix_field.Hint = 'https://example.com/new/'
                self._target_url_prefix_field.SetSelection(-1, -1)  # select all upon focus
                self._target_url_prefix_field.Enabled = not self._readonly
                bind(self._target_url_prefix_field, wx.EVT_TEXT, self._on_target_url_prefix_field_changed)
                bind(self._target_url_prefix_field, wx.EVT_SET_FOCUS, self._on_target_url_prefix_field_focus)
                bind(self._target_url_prefix_field, wx.EVT_KILL_FOCUS, self._on_target_url_prefix_field_blur)
                target_field_and_copy.Add(self._target_url_prefix_field, proportion=1, flag=wx.EXPAND)
                
                copy_button = create_copy_button(
                    parent,
                    name='cr-new-alias-dialog__target-url-prefix-copy-button',
                    text_to_copy=lambda: self._target_url_prefix_field.Value,
                    parent_is_disposed=lambda: self._is_destroying_or_destroyed,
                    previously_focused_func=lambda: (
                        self._target_url_prefix_field if self._target_url_prefix_field_focused
                        else None
                    ))
                target_field_and_copy.Add(copy_button, flag=wx.LEFT|wx.CENTER, border=_FIELD_TO_COPY_BUTTON_MARGIN)
            fields_sizer.Add(target_field_and_copy, flag=wx.EXPAND)
        
        # Target is External checkbox
        if True:
            # Empty cell in left column
            fields_sizer.Add(wx.Size(0, 0))
            
            self._target_is_external_checkbox = wx.CheckBox(parent,
                id=self._ID_TARGET_IS_EXTERNAL,
                label='🌐 External: On internet, outside project',
                name='cr-new-alias-dialog__target-is-external-checkbox')
            self._target_is_external_checkbox.Value = initial_target_is_external
            self._target_is_external_checkbox.Enabled = not self._readonly
            fields_sizer.Add(self._target_is_external_checkbox, flag=wx.EXPAND)
        
        return fields_sizer
    
    def _create_buttons(self, parent: wx.Window, is_edit: bool) -> wx.Sizer:
        ok_button_id = (wx.ID_NEW if not is_edit else wx.ID_SAVE)
        
        button_sizer = wx.BoxSizer(wx.HORIZONTAL)
        button_sizer.AddStretchSpacer()
        if self._readonly:
            button_sizer.Add(CreateButtonSizer(parent, cancel_id=wx.ID_CANCEL), flag=wx.CENTER)
        else:
            button_sizer.Add(CreateButtonSizer(parent, ok_button_id, wx.ID_CANCEL), flag=wx.CENTER)
        
        self._ok_button = parent.FindWindow(id=ok_button_id)  # possibly None
        self._cancel_button = parent.FindWindow(id=wx.ID_CANCEL)
        
        return button_sizer
    
    # === Events ===
    
    @fg_affinity
    def _on_source_url_prefix_field_changed(self, event=None) -> None:
        self._update_ok_enabled()
    
    @fg_affinity
    def _on_target_url_prefix_field_changed(self, event=None) -> None:
        self._update_ok_enabled()
    
    @fg_affinity
    def _on_source_url_prefix_field_focus(self, event: wx.FocusEvent) -> None:
        self._source_url_prefix_field_focused = True
        
        # Continue processing event in the normal fashion
        event.Skip()
    
    @fg_affinity
    def _on_source_url_prefix_field_blur(self, event: wx.FocusEvent) -> None:
        self._source_url_prefix_field_focused = False
        
        # Auto-append slash if field is nonempty and doesn't end with slash
        if (value := self._source_url_prefix_field.Value) and not value.endswith('/'):
            self._source_url_prefix_field.Value += '/'
        
        # Continue processing event in the normal fashion
        event.Skip()
    
    @fg_affinity
    def _on_target_url_prefix_field_focus(self, event: wx.FocusEvent) -> None:
        self._target_url_prefix_field_focused = True
        
        # Continue processing event in the normal fashion
        event.Skip()
    
    @fg_affinity
    def _on_target_url_prefix_field_blur(self, event: wx.FocusEvent) -> None:
        self._target_url_prefix_field_focused = False
        
        # Auto-append slash if field is nonempty and doesn't end with slash
        if (value := self._target_url_prefix_field.Value) and not value.endswith('/'):
            self._target_url_prefix_field.Value += '/'
        
        # Continue processing event in the normal fashion
        event.Skip()
    
    @fg_affinity
    def _on_button(self, event: wx.CommandEvent) -> None:
        btn_id = event.GetEventObject().GetId()
        if btn_id in (wx.ID_NEW, wx.ID_SAVE):
            self._on_ok(event)
        elif btn_id == wx.ID_CANCEL:
            self._on_cancel(event)
    
    @fg_affinity
    def _on_close(self, event: wx.CloseEvent) -> None:
        self._on_close_callback()
        
        self._is_destroying_or_destroyed = True
        self.dialog.Destroy()
    
    @fg_affinity
    def _on_destroyed(self, event) -> None:
        self._is_destroying_or_destroyed = True
    
    @fg_affinity
    def _on_ok(self, event: wx.CommandEvent | None=None) -> None:
        source_url_prefix = self._source_url_prefix_field.Value
        target_url_prefix = self._target_url_prefix_field.Value
        target_is_external = self._target_is_external_checkbox.Value
        
        # Check for duplicate alias (only when creating new)
        if not self._is_edit:
            if self._alias_exists_func(source_url_prefix):
                dialog = wx.MessageDialog(
                    self.dialog,
                    'An alias with this source URL prefix already exists.',
                    'Duplicate Alias',
                    wx.OK | wx.ICON_ERROR)
                dialog.Name = 'cr-alias-exists-dialog'
                position_dialog_initially(dialog)
                ShowModal(dialog)
                dialog.Destroy()
                return
        
        self._on_finish(source_url_prefix, target_url_prefix, target_is_external)
        self.dialog.Close()  # will call _on_close()
    
    @fg_affinity
    def _on_cancel(self, event: wx.CommandEvent) -> None:
        self.dialog.Close()  # will call _on_close()
    
    # === Updates ===
    
    def _update_ok_enabled(self) -> None:
        if self._ok_button is not None:
            self._ok_button.Enabled = (
                self._source_url_prefix_field.Value != '' and
                self._target_url_prefix_field.Value != ''
            )
