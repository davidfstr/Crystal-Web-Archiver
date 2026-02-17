from crystal.app_preferences import app_prefs
from crystal.util import features
from crystal.util.wx_bind import bind
from crystal.util.wx_date_picker import fix_date_picker_size
from crystal.util.wx_dialog import (
    add_title_heading_to_dialog_if_needed, position_dialog_initially,
    ShowModal, ShowWindowModal,
)
from crystal.util.wx_static_box_sizer import wrap_static_box_sizer_child
from crystal.util.xos import is_windows, preferences_are_called_settings_in_this_os
import datetime
from typing import Callable, Dict, TYPE_CHECKING, assert_never
from tzlocal import get_localzone
import wx

if TYPE_CHECKING:
    from crystal.doc.html import HtmlParserType
    from crystal.model.project import MigrationType, Project


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
    
    _FORMAT_NAME_FOR_MAJOR_VERSION = {
        1: 'Flat',
        2: 'Hierarchical',
        3: 'Pack16',
    }
    
    # === Init ===

    def __init__(self,
            parent: wx.Window,
            project: 'Project',
            on_close: 'Callable[[MigrationType | None], None] | None' = None,
            ) -> None:
        """
        Arguments:
        * parent -- parent wx.Window that this dialog is attached to.
        * project -- the project whose preferences are being edited.
        * on_close -- optional callback called when dialog is closed.
                      Receives the user's requested migration, if any.
        """
        self._project = project
        self._on_close_callback = on_close or (lambda migration_type: None)
        self._migration_type: 'MigrationType | None' = None
        
        dialog = self.dialog = wx.Dialog(
            parent,
            title=(
                'Settings'
                if preferences_are_called_settings_in_this_os()
                else 'Preferences'
            ),
            name='cr-preferences-dialog',
        )
        dialog_sizer = wx.BoxSizer(wx.VERTICAL)
        dialog.SetSizer(dialog_sizer)
        bind(dialog, wx.EVT_BUTTON, self._on_button)
        bind(dialog, wx.EVT_CLOSE, self._on_close)
        
        add_title_heading_to_dialog_if_needed(
            dialog,
            dialog_sizer,
            border=_WINDOW_INNER_PADDING
        )

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
        
        app_box_sizer = wx.StaticBoxSizer(wx.VERTICAL, dialog, label='Application')
        app_box_sizer.Add(wrap_static_box_sizer_child(
            self._create_app_fields(app_box_sizer.GetStaticBox())))
        dialog_sizer.Add(app_box_sizer, flag=wx.EXPAND|(wx.ALL & ~wx.TOP),
            border=_WINDOW_INNER_PADDING)
        
        dialog_sizer.Add(dialog.CreateButtonSizer(wx.OK|wx.CANCEL), flag=wx.EXPAND|wx.BOTTOM,
            border=_WINDOW_INNER_PADDING)
        
        position_dialog_initially(dialog)
        # NOTE: Must call Fit before ShowWindowModal on macOS to avoid
        #       awkward window resize animation after show
        dialog.Fit()
        ShowWindowModal(dialog)
    
    def _create_project_fields(self, parent: wx.Window) -> wx.Sizer:
        fields_sizer = wx.GridBagSizer(
            vgap=_FORM_ROW_SPACING, hgap=_FORM_LABEL_INPUT_SPACING)
        
        fields_sizer.Add(
            wx.StaticText(parent, label='These preferences are saved with the project.'),
            flag=wx.EXPAND|wx.TOP, pos=wx.GBPosition(0, 0), span=wx.GBSpan(1, 2),
            border=5 if is_windows() else 0)
        
        # HTML Parser
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
        if self._project.readonly:
            self.html_parser_field.Enabled = False
        fields_sizer.Add(
            self.html_parser_field,
            flag=wx.EXPAND, pos=wx.GBPosition(1, 1))

        # Revision Storage Format
        fields_sizer.Add(
            wx.StaticText(parent, label='Revision Storage Format:'),
            flag=wx.EXPAND, pos=wx.GBPosition(2, 0))
        format_sizer = wx.BoxSizer(wx.HORIZONTAL)
        if True:
            major_version = self._project.major_version
            
            if major_version not in self._FORMAT_NAME_FOR_MAJOR_VERSION:
                raise ValueError(f'Unknown {major_version=}')
            format_sizer.Add(
                wx.StaticText(
                    parent,
                    label=self._FORMAT_NAME_FOR_MAJOR_VERSION[major_version],
                    name='cr-preferences-dialog__revision-format-label'),
                flag=wx.CENTER
            )

            if major_version == 1:
                self._migrate_checkbox = wx.CheckBox(
                    parent, label='Migrate to Hierarchical',
                    name='cr-preferences-dialog__migrate-checkbox')
            elif major_version == 2:
                self._migrate_checkbox = wx.CheckBox(
                    parent, label='Migrate to Pack16',
                    name='cr-preferences-dialog__migrate-checkbox')
            elif major_version == 3:
                self._migrate_checkbox = None
            else:
                raise ValueError(f'Unknown {major_version=}')
            if self._migrate_checkbox is not None:
                format_sizer.AddSpacer(_FORM_LABEL_INPUT_SPACING * 2)
                format_sizer.Add(self._migrate_checkbox, flag=wx.CENTER)
                self._migrate_checkbox.Enabled = not self._project.readonly
        fields_sizer.Add(
            format_sizer,
            flag=wx.EXPAND, pos=wx.GBPosition(2, 1))

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
    
    def _create_app_fields(self, parent: wx.Window) -> wx.Sizer:
        fields_sizer = wx.GridBagSizer(
            vgap=_FORM_ROW_SPACING, hgap=_FORM_LABEL_INPUT_SPACING)
        
        fields_sizer.Add(
            wx.StaticText(parent, label='These preferences apply to all projects.'),
            flag=wx.EXPAND|wx.TOP, pos=wx.GBPosition(0, 0), span=wx.GBSpan(1, 2),
            border=5 if is_windows() else 0)
        
        # Proxy configuration
        if features.proxy_enabled():
            next_row = self._create_proxy_fieldset(parent, fields_sizer, start_row=1)
        else:
            next_row = 1
        
        # Reset dismissed callouts button
        self.reset_callouts_button = wx.Button(
            parent, 
            label='Reset Dismissed Help Messages',
            name='cr-preferences-dialog__reset-callouts-button')
        bind(self.reset_callouts_button, wx.EVT_BUTTON, self._on_reset_callouts)
        fields_sizer.Add(
            self.reset_callouts_button,
            flag=(wx.TOP if features.proxy_enabled() else 0),
            pos=wx.GBPosition(next_row, 0), span=wx.GBSpan(1, 2),
            border=8)
        
        return fields_sizer
    
    def _create_proxy_fieldset(
            self, 
            parent: wx.Window, 
            fields_sizer: wx.GridBagSizer, 
            start_row: int,
            ) -> int:
        """
        Create proxy configuration fields in the given sizer.
        
        Returns the row index after the created fields.
        
        Arguments:
        * parent -- parent wx.Window that will contain the proxy fields.
        * fields_sizer -- the GridBagSizer to add the proxy fields to.
        * start_row -- the row number where the proxy fields should start.
        """
        # Proxy configuration heading
        fields_sizer.Add(
            wx.StaticText(parent, label='Proxy:'),
            flag=wx.EXPAND|wx.TOP, pos=wx.GBPosition(start_row, 0), span=wx.GBSpan(1, 2),
            border=8)
        
        # No proxy radio button
        self.no_proxy_radio = wx.RadioButton(
            parent,
            label='No proxy',
            name='cr-preferences-dialog__no-proxy-radio',
            style=wx.RB_GROUP)
        bind(self.no_proxy_radio, wx.EVT_RADIOBUTTON, self._on_proxy_type_changed)
        fields_sizer.Add(
            self.no_proxy_radio,
            flag=wx.EXPAND, pos=wx.GBPosition(start_row + 1, 0), span=wx.GBSpan(1, 2))
        
        # HTTP/HTTPS proxy radio button (disabled, not yet supported)
        self.http_proxy_radio = wx.RadioButton(
            parent,
            label='HTTP/HTTPS proxy (not yet supported)',
            name='cr-preferences-dialog__http-proxy-radio')
        self.http_proxy_radio.Enabled = False
        fields_sizer.Add(
            self.http_proxy_radio,
            flag=wx.EXPAND, pos=wx.GBPosition(start_row + 2, 0), span=wx.GBSpan(1, 2))
        
        # SOCKS proxy radio button
        self.socks5_proxy_radio = wx.RadioButton(
            parent,
            label='SOCKS v5 proxy',
            name='cr-preferences-dialog__socks5-proxy-radio')
        bind(self.socks5_proxy_radio, wx.EVT_RADIOBUTTON, self._on_proxy_type_changed)
        fields_sizer.Add(
            self.socks5_proxy_radio,
            flag=wx.EXPAND, pos=wx.GBPosition(start_row + 3, 0), span=wx.GBSpan(1, 2))
        
        # SOCKS proxy host and port fields (indented)
        socks5_fields_sizer = wx.BoxSizer(wx.HORIZONTAL)
        if True:
            socks5_fields_sizer.Add(
                wx.StaticText(parent, label='Host:'),
                flag=wx.CENTER|wx.LEFT, border=20)
            socks5_fields_sizer.AddSpacer(_FORM_LABEL_INPUT_SPACING)
            
            self.socks5_host_field = wx.TextCtrl(
                parent,
                name='cr-preferences-dialog__socks5-host-field',
                size=(200, -1))
            self.socks5_host_field.Hint = 'localhost'
            socks5_fields_sizer.Add(self.socks5_host_field, flag=wx.CENTER)
            
            socks5_fields_sizer.AddSpacer(10)
            socks5_fields_sizer.Add(
                wx.StaticText(parent, label='Port:'),
                flag=wx.CENTER)
            socks5_fields_sizer.AddSpacer(_FORM_LABEL_INPUT_SPACING)
            
            self.socks5_port_field = wx.TextCtrl(
                parent,
                name='cr-preferences-dialog__socks5-port-field',
                size=(60, -1))
            self.socks5_port_field.Hint = '1080'
            socks5_fields_sizer.Add(self.socks5_port_field, flag=wx.CENTER)
        fields_sizer.Add(
            socks5_fields_sizer,
            flag=wx.EXPAND, pos=wx.GBPosition(start_row + 4, 0), span=wx.GBSpan(1, 2))
        
        # Load proxy preferences
        proxy_type = app_prefs.proxy_type
        if proxy_type == 'none':
            self.no_proxy_radio.Value = True
        elif proxy_type == 'socks5':
            self.socks5_proxy_radio.Value = True
        else:
            assert_never(proxy_type)
        self.socks5_host_field.Value = (
            app_prefs.socks5_proxy_host
            if app_prefs.socks5_proxy_host_is_set else ''
        )
        self.socks5_port_field.Value = (
            str(app_prefs.socks5_proxy_port)
            if app_prefs.socks5_proxy_port_is_set else ''
        )   
        
        self._update_proxy_fields_enabled()
        
        return start_row + 5
    
    # === Events ===
    
    def _update_stale_before_date_picker_enabled(self, event: wx.CommandEvent | None=None) -> None:
        self.stale_before_date_picker.Enabled = self.stale_before_checkbox.Value
    
    def _update_proxy_fields_enabled(self) -> None:
        """Enable/disable SOCKS v5 host and port fields based on selected proxy type."""
        is_socks5_selected = self.socks5_proxy_radio.Value
        self.socks5_host_field.Enabled = is_socks5_selected
        self.socks5_port_field.Enabled = is_socks5_selected
    
    def _on_proxy_type_changed(self, event: wx.CommandEvent) -> None:
        """Handle proxy type radio button selection changes."""
        self._update_proxy_fields_enabled()
    
    def _on_reset_callouts(self, event: wx.CommandEvent) -> None:
        # Reset all dismissed help callouts so they will appear again
        del app_prefs.view_button_callout_dismissed
        
        # Signal action performed by disabling the button
        self.reset_callouts_button.Enabled = False
    
    def _on_button(self, event: wx.CommandEvent) -> None:
        btn_id = event.GetEventObject().GetId()
        if btn_id == wx.ID_OK:
            self._on_ok(event)
        elif btn_id == wx.ID_CANCEL:
            self._on_cancel(event)
    
    def _on_close(self, event: wx.CloseEvent) -> None:
        self._on_close_callback(self._migration_type)

        self.dialog.Destroy()
    
    def _on_ok(self, event: wx.CommandEvent) -> None:
        # Save project fields
        if not self._project.readonly:
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
            # TODO: Gracefully handle situation where get_localzone() fails with an error like:
            #       tzlocal.utils.ZoneInfoNotFoundError: 'Multiple conflicting time zone configurations found:\n/etc/timezone: Etc/UTC\n/etc/localtime is a symlink to: America/New_York\nFix the configuration, or set the time zone in a TZ environment variable.\n'
            #       This has been observed to happen on Ubuntu 22 when run in Parallels Desktop 20.
            #       Fix with: $ readlink -f /etc/localtime | sed 's|.*/zoneinfo/||' | sudo tee /etc/timezone
            stale_before_dt_local = stale_before_dt.replace(tzinfo=get_localzone())
            self._project.min_fetch_date = stale_before_dt_local
        else:
            self._project.min_fetch_date = None

        # Save app fields
        if features.proxy_enabled():
            if self.no_proxy_radio.Value:
                app_prefs.proxy_type = 'none'
            elif self.socks5_proxy_radio.Value:
                app_prefs.proxy_type = 'socks5'
            else:
                raise AssertionError()

            try:
                app_prefs.socks5_proxy_host = self.socks5_host_field.Value.strip()
            except ValueError:  # invalid format
                del app_prefs.socks5_proxy_host

            port_str = self.socks5_port_field.Value.strip()
            try:
                port = int(port_str)
                app_prefs.socks5_proxy_port = port
            except ValueError:  # invalid format
                del app_prefs.socks5_proxy_port

        # Check for migration request
        if self._migrate_checkbox is not None and self._migrate_checkbox.Value:
            from crystal.model.project import MigrationType
            
            major_version = self._project.major_version
            if major_version == 1:
                self._migration_type = MigrationType.FLAT_TO_HIERARCHICAL
            elif major_version == 2:
                # Show warning dialog for Pack16 migration
                warning_dialog = wx.MessageDialog(
                    self.dialog,
                    'Migration may take several hours to complete. '
                    'The project will not be usable while migration is in progress.',
                    'Migrate to Pack16',
                    wx.OK | wx.CANCEL | wx.ICON_WARNING)
                warning_dialog.Name = 'cr-migrate-to-pack16-warning'
                warning_dialog.SetOKCancelLabels('Migrate', 'Cancel')
                with warning_dialog:
                    result = ShowModal(warning_dialog)
                if result != wx.ID_OK:
                    return  # user cancelled; leave Preferences open
                self._migration_type = MigrationType.HIERARCHICAL_TO_PACK16
            else:
                raise AssertionError()

        self.dialog.Close()  # will call _on_close()
    
    def _on_cancel(self, event: wx.Event) -> None:
        self.dialog.Close()  # will call _on_close()
