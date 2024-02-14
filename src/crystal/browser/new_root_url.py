from crystal.url_input import UrlCleaner
from crystal.util.bulkheads import captures_crashes_to_stderr
from crystal.util.wx_bind import bind
from crystal.util.wx_dialog import (
    CreateButtonSizer, position_dialog_initially, ShowModal,
)
from crystal.util.xos import is_wx_gtk
from crystal.util.xthreading import fg_affinity, fg_call_later
import os
from typing import Callable, Optional
import wx


_WINDOW_INNER_PADDING = 10
_FORM_LABEL_INPUT_SPACING = 5
_FORM_ROW_SPACING = 10


class NewRootUrlDialog:
    _INITIAL_URL_WIDTH = 400  # in pixels
    _FIELD_TO_SPINNER_MARGIN = 5
    
    # NOTE: Only changed when tests are running
    _last_opened: 'Optional[NewRootUrlDialog]'=None
    
    url_field: wx.TextCtrl
    name_field: wx.TextCtrl
    
    # === Init ===
    
    def __init__(self,
            parent: wx.Window,
            on_finish: Callable[[str, str], None],
            url_exists_func: Callable[[str], bool],
            initial_url: str='',
            initial_name: str='',
            is_edit: bool=False,
            ) -> None:
        """
        Arguments:
        * parent -- parent wx.Window that this dialog is attached to.
        * on_finish -- called when OK pressed on dialog. Is a callable(name, url).
        * initial_url -- overrides the initial URL displayed.
        """
        self._on_finish = on_finish
        self._url_exists_func = url_exists_func
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
        
        ok_button_id = (wx.ID_NEW if not is_edit else wx.ID_SAVE)
        dialog_sizer.Add(self._create_fields(dialog, initial_url, initial_name, is_edit), flag=wx.EXPAND|wx.ALL,
            border=_WINDOW_INNER_PADDING)
        dialog_sizer.Add(CreateButtonSizer(dialog, ok_button_id, wx.ID_CANCEL), flag=wx.EXPAND|wx.BOTTOM,
            border=_WINDOW_INNER_PADDING)
        self.ok_button = dialog.FindWindow(id=ok_button_id)
        self.cancel_button = dialog.FindWindow(id=wx.ID_CANCEL)
        
        self._update_ok_enabled()
        
        if not fields_hide_hint_when_focused():
            # Initialize focus
            if not is_edit:
                self.url_field.SetFocus()
            else:
                self.name_field.SetFocus()
        
        position_dialog_initially(dialog)
        dialog.Show(True)
        dialog.Fit()  # NOTE: Must Fit() after Show() here so that wxGTK actually fits correctly
        
        dialog.MinSize = dialog.Size
        dialog.MaxSize = wx.Size(wx.DefaultCoord, dialog.Size.Height)
        
        # Export reference to self, if running tests
        if os.environ.get('CRYSTAL_RUNNING_TESTS', 'False') == 'True':
            NewRootUrlDialog._last_opened = self
    
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
                self.url_field = wx.TextCtrl(
                    parent, value=initial_url,
                    size=(self._INITIAL_URL_WIDTH, wx.DefaultCoord),
                    name='cr-new-root-url-dialog__url-field')
                self.url_field.Hint = 'https://example.com/'
                self.url_field.SetSelection(-1, -1)  # select all upon focus
                self.url_field.Enabled = not is_edit
                bind(self.url_field, wx.EVT_TEXT, self._update_ok_enabled)
                bind(self.url_field, wx.EVT_SET_FOCUS, self._on_url_field_focus)
                bind(self.url_field, wx.EVT_KILL_FOCUS, self._on_url_field_blur)
                url_field_and_spinner.Add(self.url_field, proportion=1, flag=wx.EXPAND)
                
                spinner_diameter = self.url_field.Size.Height
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
                self.name_field = wx.TextCtrl(
                    parent, value=initial_name,
                    name='cr-new-root-url-dialog__name-field')
                self.name_field.Hint = 'Home'
                self.name_field.SetSelection(-1, -1)  # select all upon focus
                name_field_and_space.Add(self.name_field, proportion=1, flag=wx.EXPAND)
                
                #name_field_and_space.Add(
                #    wx.Size(spinner_diameter, spinner_diameter),
                #    flag=wx.LEFT,
                #    border=self._FIELD_TO_SPINNER_MARGIN)
            fields_sizer.Add(name_field_and_space, flag=wx.EXPAND)
        
        return fields_sizer
    
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
        if self.url_field.Value != cleaned_url:
            self.url_field.Value = cleaned_url
    
    # === Events ===
    
    # NOTE: Focus event can be called multiple times without an intermediate blur event
    @fg_affinity
    def _on_url_field_focus(self, event: wx.FocusEvent) -> None:
        # NOTE: Cannot use url_field.HasFocus() because doesn't work in automated tests
        if self._url_field_focused:
            # Already did focus action
            return
        self._url_field_focused = True
        
        # If field still focused after a tick,
        # stop cleaning any old URL input
        @captures_crashes_to_stderr  # no good location in UI to route crashes too
        def fg_task() -> None:
            # NOTE: Cannot use url_field.HasFocus() because doesn't work in automated tests
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
    def _on_url_field_blur(self, event: Optional[wx.FocusEvent]=None) -> None:
        if not self._url_field_focused:
            # Already did blur action
            return
        self._url_field_focused = False
        
        if self._is_destroying_or_destroyed:
            return
        
        # Start cleaning the new URL input
        url_input = self.url_field.Value
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
    
    def _on_button(self, event: wx.CommandEvent) -> None:
        btn_id = event.GetEventObject().GetId()
        if btn_id in (wx.ID_NEW, wx.ID_SAVE):
            self._on_ok(event)
        elif btn_id == wx.ID_CANCEL:
            self._on_cancel(event)
    
    def _on_close(self, event: wx.CloseEvent) -> None:
        self._on_cancel(event)
    
    @fg_affinity
    def _on_ok(self, event: Optional[wx.CommandEvent]=None) -> None:
        # Blur text fields so that they save their contents
        self._on_url_field_blur()
        
        # If URL input is being cleaned, wait for it to finish before continuing
        if self._url_cleaner is not None:
            self.url_field.Enabled = False
            self.name_field.Enabled = False
            self.ok_button.Enabled = False
            assert self.cancel_button.Enabled == True
            
            self._was_ok_pressed = True
            return
        
        name = self.name_field.Value
        url = self.url_field.Value
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
            
            self.url_field.Enabled = True
            self.name_field.Enabled = True
            self.ok_button.Enabled = True
            assert self.cancel_button.Enabled == True
            return
        self._on_finish(name, url)
        
        self._destroy()
    
    @fg_affinity
    def _on_cancel(self, event: wx.CommandEvent) -> None:
        # Stop cleaning any old URL input
        if self._url_cleaner is not None:
            self._url_cleaner.cancel()
            self._url_cleaner = None
        
        self._destroy()
    
    @fg_affinity
    def _destroy(self) -> None:
        self._is_destroying_or_destroyed = True
        self.dialog.Destroy()
    
    @fg_affinity
    def _on_destroyed(self, event) -> None:
        self._is_destroying_or_destroyed = True
    
    # === Updates ===
    
    def _update_ok_enabled(self, event=None) -> None:
        self.ok_button.Enabled = (self.url_field.Value != '')


def fields_hide_hint_when_focused() -> bool:
    return is_wx_gtk()
