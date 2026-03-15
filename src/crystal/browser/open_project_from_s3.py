from crystal.filesystem import S3Filesystem
from crystal.util.test_mode import tests_are_running
from crystal.util.wx_bind import bind
from crystal.util.wx_dialog import (
    CreateButtonSizer, add_title_heading_to_dialog_if_needed,
    position_dialog_initially, ShowModal,
)
from crystal.util.wx_static_box_sizer import wrap_static_box_sizer_child
from crystal.util.xthreading import fg_affinity
from typing import Optional
from typing import override
import wx


_WINDOW_INNER_PADDING = 10
_FORM_LABEL_INPUT_SPACING = 5
_FORM_ROW_SPACING = 10


class OpenProjectFromS3Dialog(wx.Dialog):
    """
    Dialog for opening a Crystal project hosted on AWS S3.

    After ShowModal() returns wx.ID_OK, read:
    * plain_s3_url -- plain s3:// URL (no embedded credentials)
    * credentials -- Credentials, ProfileCredentials, or None
    """

    # NOTE: Only changed when tests are running
    _last_opened: 'Optional[OpenProjectFromS3Dialog]' = None

    plain_s3_url: str
    credentials: 'S3Filesystem.Credentials | S3Filesystem.ProfileCredentials | None'

    _url_field: wx.TextCtrl
    _url_error_label: wx.StaticText
    _use_profile_radio: wx.RadioButton
    _profile_choice: wx.Choice
    _use_manual_radio: wx.RadioButton
    _access_key_id_field: wx.TextCtrl
    _secret_access_key_field: wx.TextCtrl
    _embedded_creds_label: wx.StaticText
    _open_button: wx.Button

    def __init__(self, parent: 'wx.Window | None') -> None:
        super().__init__(
            parent,
            title='Open Project from S3',
            name='cr-open-project-from-s3-dialog',
            style=wx.DEFAULT_DIALOG_STYLE)

        self._embedded_creds_in_url = False

        dialog_sizer = wx.BoxSizer(wx.VERTICAL)
        self.SetSizer(dialog_sizer)

        # URL section
        url_section = self._create_url_section(self)
        dialog_sizer.Add(url_section,
            flag=wx.EXPAND|wx.ALL,
            border=_WINDOW_INNER_PADDING)

        # AWS Credentials section
        cred_section = self._create_credentials_section(self)
        dialog_sizer.Add(cred_section,
            flag=wx.EXPAND|wx.LEFT|wx.RIGHT|wx.BOTTOM,
            border=_WINDOW_INNER_PADDING)

        # Buttons
        if True:
            button_sizer = CreateButtonSizer(self, wx.ID_OK, wx.ID_CANCEL)
            dialog_sizer.Add(button_sizer,
                flag=wx.EXPAND|wx.LEFT|wx.RIGHT|wx.BOTTOM,
                border=_WINDOW_INNER_PADDING)

            self._open_button = self.FindWindow(id=wx.ID_OK)
            self._open_button.Label = '&Open'

            bind(self, wx.EVT_BUTTON, self._on_button)

        self._update_open_enabled()
        self._update_credential_controls()

        position_dialog_initially(self)
        self.Fit()

        if tests_are_running():
            OpenProjectFromS3Dialog._last_opened = self

    def _create_url_section(self, parent: wx.Window) -> wx.Sizer:
        url_sizer = wx.FlexGridSizer(rows=2, cols=2,
            vgap=_FORM_LABEL_INPUT_SPACING, hgap=_FORM_LABEL_INPUT_SPACING)
        url_sizer.AddGrowableCol(1)

        url_label = wx.StaticText(parent, label='S3 URL:', style=wx.ALIGN_RIGHT)
        url_label.Font = url_label.Font.Bold()  # mark as required
        url_sizer.Add(url_label, flag=wx.ALIGN_CENTER_VERTICAL|wx.EXPAND)

        self._url_field = wx.TextCtrl(
            parent, value='',
            size=(400, wx.DefaultCoord),
            name='cr-open-project-from-s3-dialog__url-field')
        self._url_field.Hint = 's3://bucket/path/X.crystalproj/'
        bind(self._url_field, wx.EVT_TEXT, self._on_url_changed)
        bind(self._url_field, wx.EVT_KILL_FOCUS, self._on_url_blur)
        url_sizer.Add(self._url_field, flag=wx.EXPAND)

        url_sizer.AddSpacer(0)  # empty first column for error row

        self._url_error_label = wx.StaticText(
            parent, label='',
            name='cr-open-project-from-s3-dialog__url-error-label')
        self._url_error_label.ForegroundColour = wx.Colour(200, 0, 0)  # red
        self._url_error_label.Hide()
        url_sizer.Add(self._url_error_label, flag=wx.EXPAND)

        return url_sizer

    def _create_credentials_section(self, parent: wx.Window) -> wx.StaticBoxSizer:
        sizer = wx.StaticBoxSizer(wx.VERTICAL, parent, label='AWS Credentials')
        sizer.Add(
            wrap_static_box_sizer_child(
                self._create_credentials_content(sizer.GetStaticBox())),
            flag=wx.EXPAND)
        return sizer

    def _create_credentials_content(self, parent: wx.Window) -> wx.Sizer:
        # Determine available profiles
        try:
            import boto3
            available_profiles = list(boto3.Session().available_profiles)
        except Exception:
            available_profiles = []

        self._available_profiles = available_profiles
        has_profiles = len(available_profiles) > 0
        has_default_profile = 'default' in available_profiles

        content_sizer = wx.BoxSizer(wx.VERTICAL)

        # "Use saved AWS profile" radio
        self._use_profile_radio = wx.RadioButton(
            parent,
            label='Use saved AWS profile',
            style=wx.RB_GROUP,
            name='cr-open-project-from-s3-dialog__use-profile-radio')
        self._use_profile_radio.Enabled = has_profiles
        bind(self._use_profile_radio, wx.EVT_SET_FOCUS, self._on_radio_focused_while_disabled)
        content_sizer.Add(self._use_profile_radio,
            flag=wx.BOTTOM,
            border=_FORM_LABEL_INPUT_SPACING)

        # Profile dropdown row (indented)
        profile_row = wx.BoxSizer(wx.HORIZONTAL)
        profile_label = wx.StaticText(parent, label='Profile:')
        profile_row.Add(profile_label,
            flag=wx.ALIGN_CENTER_VERTICAL|wx.RIGHT,
            border=_FORM_LABEL_INPUT_SPACING)

        choices = available_profiles if has_profiles else ['(no profiles found)']
        self._profile_choice = wx.Choice(
            parent, choices=choices,
            name='cr-open-project-from-s3-dialog__profile-choice')
        if has_default_profile:
            self._profile_choice.SetStringSelection('default')
        elif has_profiles:
            self._profile_choice.SetSelection(0)
        profile_row.Add(self._profile_choice, proportion=1, flag=wx.EXPAND)

        content_sizer.Add(profile_row,
            flag=wx.EXPAND|wx.LEFT|wx.BOTTOM,
            border=20)

        content_sizer.AddSpacer(_FORM_ROW_SPACING)

        # "Enter credentials manually" radio
        self._use_manual_radio = wx.RadioButton(
            parent,
            label='Enter credentials manually',
            name='cr-open-project-from-s3-dialog__use-manual-radio')
        bind(self._use_manual_radio, wx.EVT_SET_FOCUS, self._on_radio_focused_while_disabled)
        content_sizer.Add(self._use_manual_radio,
            flag=wx.BOTTOM,
            border=_FORM_LABEL_INPUT_SPACING)

        # Manual credentials grid (indented)
        manual_sizer = wx.FlexGridSizer(rows=2, cols=2,
            vgap=_FORM_LABEL_INPUT_SPACING, hgap=_FORM_LABEL_INPUT_SPACING)
        manual_sizer.AddGrowableCol(1)

        manual_sizer.Add(wx.StaticText(parent, label='Access Key ID:'),
            flag=wx.ALIGN_CENTER_VERTICAL|wx.EXPAND)
        self._access_key_id_field = wx.TextCtrl(
            parent,
            name='cr-open-project-from-s3-dialog__access-key-id-field')
        manual_sizer.Add(self._access_key_id_field, flag=wx.EXPAND)

        manual_sizer.Add(wx.StaticText(parent, label='Secret Access Key:'),
            flag=wx.ALIGN_CENTER_VERTICAL|wx.EXPAND)
        self._secret_access_key_field = wx.TextCtrl(
            parent,
            style=wx.TE_PASSWORD,
            name='cr-open-project-from-s3-dialog__secret-access-key-field')
        manual_sizer.Add(self._secret_access_key_field, flag=wx.EXPAND)

        content_sizer.Add(manual_sizer,
            flag=wx.EXPAND|wx.LEFT,
            border=20)

        # "Credentials provided in URL" label (shown when URL has embedded creds)
        self._embedded_creds_label = wx.StaticText(
            parent, label='Credentials provided in URL',
            name='cr-open-project-from-s3-dialog__embedded-creds-label')
        self._embedded_creds_label.ForegroundColour = wx.Colour(102, 102, 102)  # gray
        self._embedded_creds_label.Hide()
        content_sizer.Add(self._embedded_creds_label,
            flag=wx.TOP,
            border=_FORM_ROW_SPACING)

        # Set initial radio selection
        if has_profiles:
            self._use_profile_radio.Value = True
        else:
            self._use_manual_radio.Value = True

        # Bind radio events
        bind(parent, wx.EVT_RADIOBUTTON, self._on_credential_source_changed)

        return content_sizer

    # === Events ===

    @fg_affinity
    def _on_url_changed(self, event=None) -> None:
        # Clear any previous URL validation error when user edits the field
        if self._url_error_label.IsShown():
            self._embedded_creds_in_url = False
            self._url_error_label.Label = ''
            self._url_error_label.Hide()
            self._update_credential_controls()
            self.Layout()
        self._update_open_enabled()

    @fg_affinity
    def _on_url_blur(self, event: wx.FocusEvent) -> None:
        self._validate_url_and_update_controls()
        event.Skip()

    @fg_affinity
    def _on_credential_source_changed(self, event: wx.CommandEvent) -> None:
        self._update_credential_controls()

    @fg_affinity
    def _on_radio_focused_while_disabled(self, event: wx.FocusEvent) -> None:
        # On macOS, a focused+disabled radio button traps Tab/Shift-Tab.
        # If this radio received focus while disabled (because embedded
        # credentials are in the URL), navigate forward past it immediately.
        radio = event.GetEventObject()
        if not radio.Enabled:
            for _ in range(10):  # safety limit
                if not radio.Navigate():
                    break
                new_focused = self.FindFocus()
                if new_focused is radio or not isinstance(new_focused, wx.RadioButton):
                    break
                radio = new_focused
        event.Skip()

    @fg_affinity
    def _on_button(self, event: wx.CommandEvent) -> None:
        btn_id = event.GetEventObject().GetId()
        if btn_id == wx.ID_OK:
            self._on_open()
        elif btn_id == wx.ID_CANCEL:
            self.EndModal(wx.ID_CANCEL)
        else:
            event.Skip()

    def _on_open(self) -> None:
        result = self._validate_inputs()
        if result is not None:
            (self.plain_s3_url, self.credentials) = result
            self.EndModal(wx.ID_OK)

    # === Updates ===

    def _validate_url_and_update_controls(self) -> None:
        url = self._url_field.Value.strip()
        if not url:
            self._embedded_creds_in_url = False
            self._url_error_label.Label = ''
            self._url_error_label.Hide()
            self._update_credential_controls()
            self._update_open_enabled()
            self.Layout()
            return

        try:
            (creds, _plain_url) = S3Filesystem.split_credentials_if_present(url)
        except ValueError as e:
            self._embedded_creds_in_url = False
            self._url_error_label.Label = str(e)
            self._url_error_label.Show()
        else:
            self._embedded_creds_in_url = (creds is not None)
            self._url_error_label.Label = ''
            self._url_error_label.Hide()
        self._update_credential_controls()
        self._update_open_enabled()
        self.Layout()

    def _update_open_enabled(self) -> None:
        url_is_valid = (
            bool(self._url_field.Value.strip()) and
            not self._url_error_label.IsShown()
        )
        self._open_button.Enabled = url_is_valid

    def _update_credential_controls(self) -> None:
        has_profiles = len(self._available_profiles) > 0

        if self._embedded_creds_in_url:
            # Disable everything; credentials come from the URL
            self._use_profile_radio.Enabled = False
            self._profile_choice.Enabled = False
            self._use_manual_radio.Enabled = False
            self._access_key_id_field.Enabled = False
            self._secret_access_key_field.Enabled = False
            resize_height = not self._embedded_creds_label.Shown
            self._embedded_creds_label.Show()
        else:
            # Enable controls based on radio selection
            resize_height = self._embedded_creds_label.Shown
            self._embedded_creds_label.Hide()
            self._use_profile_radio.Enabled = has_profiles
            self._use_manual_radio.Enabled = True

            using_profile = self._use_profile_radio.Value and has_profiles
            self._profile_choice.Enabled = using_profile
            self._access_key_id_field.Enabled = not using_profile
            self._secret_access_key_field.Enabled = not using_profile
        
        if resize_height:
            self.Fit()

    def _validate_inputs(self) -> 'tuple[str, S3Filesystem.Credentials | S3Filesystem.ProfileCredentials | None] | None':
        """
        Validates the dialog inputs.

        Returns (plain_url, credentials) on success, or None if validation
        fails (after showing error to user).
        """
        url = self._url_field.Value.strip()
        if not url:
            return None

        try:
            (embedded_creds, plain_url) = S3Filesystem.split_credentials_if_present(url)
        except ValueError as e:
            dialog = wx.MessageDialog(
                self,
                message=str(e),
                caption='Invalid S3 URL',
                style=wx.ICON_ERROR|wx.OK)
            dialog.Name = 'cr-open-project-from-s3-dialog__url-error'
            with dialog:
                position_dialog_initially(dialog)
                ShowModal(dialog)
            return None

        if embedded_creds is not None:
            return (plain_url, embedded_creds)

        if self._use_profile_radio.Value:
            profile_name = self._profile_choice.GetStringSelection()
            return (plain_url, S3Filesystem.ProfileCredentials(profile_name=profile_name))
        else:
            access_key_id = self._access_key_id_field.Value.strip()
            secret_access_key = self._secret_access_key_field.Value.strip()
            if access_key_id and secret_access_key:
                return (plain_url, S3Filesystem.Credentials(
                    access_key_id=access_key_id,
                    secret_access_key=secret_access_key))
            elif not access_key_id and not secret_access_key:
                # No manual credentials entered. Let boto3 use its default chain.
                return (plain_url, None)
            else:
                # Partial credentials. Show error.
                dialog = wx.MessageDialog(
                    self,
                    message=(
                        'Please enter both Access Key ID and Secret Access Key, '
                        'or leave both empty to use default AWS credentials.'
                    ),
                    caption='Incomplete Credentials',
                    style=wx.ICON_ERROR|wx.OK)
                dialog.Name = 'cr-open-project-from-s3-dialog__incomplete-creds-error'
                with dialog:
                    position_dialog_initially(dialog)
                    ShowModal(dialog)
                return None
