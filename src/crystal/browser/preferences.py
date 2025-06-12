from crystal.util.wx_bind import bind
from crystal.util.wx_date_picker import fix_date_picker_size
from crystal.util.wx_dialog import position_dialog_initially
from crystal.util.wx_static_box_sizer import wrap_static_box_sizer_child
from crystal.util.xos import is_linux, is_mac_os, is_windows
import datetime
from typing import Dict, TYPE_CHECKING
from tzlocal import get_localzone
import wx

if TYPE_CHECKING:
    from crystal.doc.html import HtmlParserType
    from crystal.model import Project


_WINDOW_INNER_PADDING = 10
_FORM_LABEL_INPUT_SPACING = 5
_FORM_ROW_SPACING = 10


class PreferencesDialog:
    _LXML_ITEM = \
        'Fastest - lxml'
    _HTML_PARSER_BS4_ITEM = \
        'Classic - html.parser (bs4)'
    
    _HTML_PARSER_TYPE_FOR_ITEM = {
        _LXML_ITEM: 'lxml',
        _HTML_PARSER_BS4_ITEM: 'html_parser',
    }  # type: Dict[str, HtmlParserType]
    _ITEM_FOR_HTML_PARSER_TYPE = {
        v: k for (k, v) in _HTML_PARSER_TYPE_FOR_ITEM.items()
    }
    
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
        
        project_box_sizer = wx.StaticBoxSizer(wx.VERTICAL, dialog, label='Project')
        project_box_sizer.Add(wrap_static_box_sizer_child(
            self._create_project_fields(project_box_sizer.GetStaticBox())))
        dialog_sizer.Add(project_box_sizer, flag=wx.EXPAND|wx.ALL,
            border=_WINDOW_INNER_PADDING)
        
        session_box_sizer = wx.StaticBoxSizer(wx.VERTICAL, dialog, label='Session')
        session_box_sizer.Add(wrap_static_box_sizer_child(
            self._create_session_fields(session_box_sizer.GetStaticBox())))
        dialog_sizer.Add(session_box_sizer, flag=wx.EXPAND|(wx.ALL & ~wx.TOP),
            border=_WINDOW_INNER_PADDING)
        
        dialog_sizer.Add(dialog.CreateButtonSizer(wx.OK|wx.CANCEL), flag=wx.EXPAND|wx.BOTTOM,
            border=_WINDOW_INNER_PADDING)
        
        position_dialog_initially(dialog)
        dialog.Show(True)
        dialog.Fit()  # NOTE: Must Fit() after Show() here so that wxGTK actually fits correctly
    
    def _create_project_fields(self, parent: wx.Window) -> wx.Sizer:
        fields_sizer = wx.GridBagSizer(
            vgap=_FORM_ROW_SPACING, hgap=_FORM_LABEL_INPUT_SPACING)
        
        fields_sizer.Add(
            wx.StaticText(parent, label='These preferences are saved with the project.'),
            flag=wx.EXPAND|wx.TOP, pos=wx.GBPosition(0, 0), span=wx.GBSpan(1, 2),
            border=5 if is_windows() else 0)
        
        fields_sizer.Add(
            wx.StaticText(parent, label='HTML Parser:'),
            flag=wx.EXPAND, pos=wx.GBPosition(1, 0))
        self.html_parser_field = wx.Choice(
            parent,
            name='cr-preferences-dialog__html-parser-field')
        self.html_parser_field.SetItems([
            self._LXML_ITEM,
            self._HTML_PARSER_BS4_ITEM,
        ])
        self._old_html_parser_type = self._project.html_parser_type
        self.html_parser_field.Selection = self.html_parser_field.Items.index(
            self._ITEM_FOR_HTML_PARSER_TYPE[self._old_html_parser_type])
        fields_sizer.Add(
            self.html_parser_field,
            flag=wx.EXPAND, pos=wx.GBPosition(1, 1))
        
        return fields_sizer
    
    def _create_session_fields(self, parent: wx.Window) -> wx.Sizer:
        fields_sizer = wx.GridBagSizer(
            vgap=_FORM_ROW_SPACING, hgap=_FORM_LABEL_INPUT_SPACING)
        
        fields_sizer.Add(
            wx.StaticText(parent, label='These preferences reset when Crystal quits.'),
            flag=wx.EXPAND|wx.TOP, pos=wx.GBPosition(0, 0), span=wx.GBSpan(1, 2),
            border=5 if is_windows() else 0)
        
        fields_sizer.Add(
            wx.StaticText(parent, label='To redownload URLs, provide:'),
            flag=wx.EXPAND|wx.TOP, pos=wx.GBPosition(1, 0), span=wx.GBSpan(1, 2),
            border=8)
        fields_sizer.Add(
            self._create_stale_before_field(parent),
            flag=wx.EXPAND, pos=wx.GBPosition(2, 0), span=wx.GBSpan(1, 2))
        
        fields_sizer.Add(
            wx.StaticText(parent, label='To download a site requiring login, provide:'),
            flag=wx.EXPAND, pos=wx.GBPosition(3, 0), span=wx.GBSpan(1, 2))
        fields_sizer.Add(
            wx.StaticText(parent, label='Cookie:'),
            flag=wx.EXPAND, pos=wx.GBPosition(4, 0))
        self.cookie_field = wx.ComboBox(
            parent,
            name='cr-preferences-dialog__cookie-field')
        self.cookie_field.SetItems(
            self._project.request_cookies_in_use(most_recent_first=True))
        self.cookie_field.Value = self._project.request_cookie or ''
        fields_sizer.Add(
            self.cookie_field,
            flag=wx.EXPAND, pos=wx.GBPosition(4, 1))
        
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
    
    def _update_stale_before_date_picker_enabled(self, event: wx.CommandEvent | None=None) -> None:
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
        # Save project fields
        new_html_parser_type = \
            self._HTML_PARSER_TYPE_FOR_ITEM[
                self.html_parser_field.Items[self.html_parser_field.Selection]]
        if new_html_parser_type != self._old_html_parser_type:
            self._project.html_parser_type = new_html_parser_type
        
        # Save session fields
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
