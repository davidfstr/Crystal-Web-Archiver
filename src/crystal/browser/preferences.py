from crystal.util.wx_bind import bind
from crystal.util.wx_date_picker import fix_date_picker_size
from crystal.util.xos import is_mac_os
import datetime
import wx
from typing import Optional, TYPE_CHECKING
from tzlocal import get_localzone

if TYPE_CHECKING:
    from crystal.model import Project


_WINDOW_INNER_PADDING = 10
_FORM_LABEL_INPUT_SPACING = 5
_FORM_ROW_SPACING = 10


class PreferencesDialog:
    # === Init ===
    
    def __init__(self, parent: wx.Window, project: 'Project') -> None:
        """
        Arguments:
        * parent -- parent wx.Window that this dialog is attached to.
        """
        self._project = project
        
        dialog = self.dialog = wx.Dialog(parent, title='Preferences', name='cr-preferences-dialog')
        dialog_sizer = wx.BoxSizer(wx.VERTICAL)
        dialog.SetSizer(dialog_sizer)
        bind(dialog, wx.EVT_BUTTON, self._on_button)
        bind(dialog, wx.EVT_CLOSE, self._on_close)
        
        session_box_sizer = wx.StaticBoxSizer(wx.VERTICAL, dialog, label='Session')
        session_box_sizer.Add(self._create_session_fields(session_box_sizer.GetStaticBox()))
        dialog_sizer.Add(session_box_sizer, flag=wx.EXPAND|wx.ALL,
            border=_WINDOW_INNER_PADDING)
        
        dialog_sizer.Add(dialog.CreateButtonSizer(wx.OK|wx.CANCEL), flag=wx.EXPAND|wx.BOTTOM,
            border=_WINDOW_INNER_PADDING)
        
        dialog.Fit()
        dialog.Show(True)
    
    def _create_session_fields(self, parent: wx.Window) -> wx.Sizer:
        fields_sizer = wx.GridBagSizer(
            vgap=_FORM_ROW_SPACING, hgap=_FORM_LABEL_INPUT_SPACING)
        
        fields_sizer.Add(
            self._smaller_text(wx.StaticText(parent, label='For redownloading URLs:')),
            flag=wx.EXPAND, pos=wx.GBPosition(0, 0), span=wx.GBSpan(1, 2))
        fields_sizer.Add(
            self._create_stale_before_field(parent),
            flag=wx.EXPAND, pos=wx.GBPosition(1, 0), span=wx.GBSpan(1, 2))
        
        fields_sizer.Add(
            self._smaller_text(wx.StaticText(parent, label='For sites requiring login:')),
            flag=wx.EXPAND, pos=wx.GBPosition(2, 0), span=wx.GBSpan(1, 2))
        fields_sizer.Add(
            wx.StaticText(parent, label='Cookie:'),
            flag=wx.EXPAND, pos=wx.GBPosition(3, 0))
        self.cookie_field = wx.ComboBox(
            parent,
            name='cr-preferences-dialog__cookie-field')
        self.cookie_field.SetItems(
            self._project.request_cookies_in_use(most_recent_first=True))
        self.cookie_field.Value = self._project.request_cookie or ''
        fields_sizer.Add(
            self.cookie_field,
            flag=wx.EXPAND, pos=wx.GBPosition(3, 1))
        
        return fields_sizer
    
    def _create_stale_before_field(self, parent: wx.Window) -> wx.Sizer:
        import wx.adv  # import late because does print spurious messages on macOS
        
        sizer = wx.BoxSizer(wx.HORIZONTAL)
        
        self.stale_before_checkbox = wx.CheckBox(
            parent, label='Treat URLs as stale older than:',
            name='cr-preferences-dialog__stale-before-checkbox')
        bind(self.stale_before_checkbox, wx.EVT_CHECKBOX, self._update_stale_before_date_picker_enabled)
        sizer.Add(self.stale_before_checkbox, flag=wx.CENTER)
        
        self.stale_before_date_picker = wx.adv.DatePickerCtrl(
            parent, dt=wx.DefaultDateTime,  # default to today
            name='cr-preferences-dialog__stale-before-date-picker')
        sizer.Add(self.stale_before_date_picker, flag=wx.CENTER)
        fix_date_picker_size(self.stale_before_date_picker)
        
        stale_before_dt = self._project.min_fetch_date
        if stale_before_dt is not None:
            stale_before_dt_local = stale_before_dt.astimezone(tz=None)  # local timezone
            self.stale_before_checkbox.Value = True
            self.stale_before_date_picker.Value = wx.DateTime(
                year=stale_before_dt_local.year,
                month=stale_before_dt_local.month - 1,
                day=stale_before_dt_local.day)
        
        self._update_stale_before_date_picker_enabled()
        
        return sizer
    
    # === Events ===
    
    def _update_stale_before_date_picker_enabled(self, event: Optional[wx.CommandEvent]=None) -> None:
        self.stale_before_date_picker.Enabled = self.stale_before_checkbox.Value
    
    def _on_button(self, event: wx.CommandEvent) -> None:
        btn_id = event.GetEventObject().GetId()
        if btn_id == wx.ID_OK:
            self._on_ok(event)
        elif btn_id == wx.ID_CANCEL:
            self._on_cancel(event)
    
    def _on_close(self, event: wx.CloseEvent) -> None:
        self._on_cancel(event)
    
    def _on_ok(self, event: wx.CommandEvent) -> None:
        self._project.request_cookie = self.cookie_field.Value or None
        if self.stale_before_checkbox.Value:
            stale_before_wdt = self.stale_before_date_picker.Value
            stale_before_dt = datetime.datetime(
                year=stale_before_wdt.year,
                month=stale_before_wdt.month + 1,
                day=stale_before_wdt.day)
            stale_before_dt_local = stale_before_dt.replace(tzinfo=get_localzone())
            self._project.min_fetch_date = stale_before_dt_local
        else:
            self._project.min_fetch_date = None
        
        self.dialog.Destroy()
    
    def _on_cancel(self, event: wx.Event) -> None:
        self.dialog.Destroy()
    
    # === Utility ===
    
    @staticmethod
    def _smaller_text(label: wx.StaticText) -> wx.StaticText:
        new_font = wx.Font(label.Font)
        new_font.SetPointSize(12)
        label.Font = new_font
        return label
