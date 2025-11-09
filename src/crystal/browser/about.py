from crystal import APP_COPYRIGHT_STRING, __version__ as CRYSTAL_VERSION, APP_NAME
from crystal.ui.branding import (
    AUTHORS_1_TEXT, AUTHORS_2_TEXT, AUTHORS_2_URL, 
    create_program_name_control, get_font_size_scale, load_app_icon,
)
from crystal.ui.clickable_text import ClickableText
from crystal.util.wx_bind import bind
from crystal.util.wx_dialog import (
    ShowModal, ShowWindowModal, position_dialog_initially, 
    set_dialog_or_frame_icon_if_appropriate,
)
from crystal.util.wx_system_appearance import IsDarkNow, SetDark
from typing import Callable
import wx


_WINDOW_INNER_PADDING = 20


class AboutDialog:
    """
    An About dialog that displays information about Crystal,
    including the program icon, name, version, and authors.
    """
    
    def __init__(self, parent: wx.Window | None, on_close: Callable[[], None] | None=None) -> None:
        self._on_close_callback = on_close or (lambda: None)
        
        dialog = self.dialog = wx.Dialog(
            parent,
            title=f'About {APP_NAME}',
            name='cr-about-dialog',
            style=wx.DEFAULT_DIALOG_STYLE
        )
        set_dialog_or_frame_icon_if_appropriate(dialog)
        
        dialog_sizer = wx.BoxSizer(wx.VERTICAL)
        dialog.SetSizer(dialog_sizer)
        
        # Content area
        self._program_name_sizer = content_sizer = wx.BoxSizer(wx.VERTICAL)
        dialog_sizer.Add(
            content_sizer,
            flag=wx.ALL,
            border=_WINDOW_INNER_PADDING
        )
        
        # Program icon
        try:
            app_icon = load_app_icon(wx.Size(64, 64))
            
            icon_ctrl = wx.StaticBitmap(dialog, bitmap=app_icon)
            content_sizer.Add(
                icon_ctrl,
                flag=wx.ALIGN_CENTER|wx.BOTTOM,
                border=12)
        except Exception:
            # If icon loading fails, continue without icon
            pass
        
        font_size_scale = get_font_size_scale()  # cache
        
        more_prominent_font = wx.Font(
            int(14 * font_size_scale),
            wx.FONTFAMILY_DEFAULT,
            wx.FONTSTYLE_NORMAL,
            wx.FONTWEIGHT_NORMAL
        )
        
        less_prominent_font = wx.Font(
            int(12 * font_size_scale),
            wx.FONTFAMILY_DEFAULT,
            wx.FONTSTYLE_NORMAL,
            wx.FONTWEIGHT_NORMAL
        )
        less_prominent_color = wx.Colour(128, 128, 128)  # gray
        
        # Program name
        self._program_name = program_name = create_program_name_control(dialog)
        self._program_name_sizer_index = len(content_sizer.GetChildren())
        content_sizer.Add(
            program_name,
            flag=wx.ALIGN_CENTER|wx.BOTTOM,
            border=4
        )
        
        # Version
        version_label = wx.StaticText(dialog, label=f'Version {CRYSTAL_VERSION}')
        version_label.SetFont(more_prominent_font)
        content_sizer.Add(
            version_label,
            flag=wx.ALIGN_CENTER|wx.BOTTOM,
            border=24
        )
        
        # Description
        description_label = wx.StaticText(dialog, label='Archiving websites since 2011!')
        description_label.SetFont(more_prominent_font)
        content_sizer.Add(
            description_label,
            flag=wx.ALIGN_CENTER|wx.BOTTOM,
            border=24
        )
        
        # NOTE: Removing this line for now because it creates one too many
        #       rows for the user to pay attention to.
        if False:
            # Authors line with clickable "contributors" link
            authors_area = wx.Panel(dialog)
            if True:
                authors_sizer = wx.BoxSizer(wx.HORIZONTAL)
                authors_area.SetSizer(authors_sizer)
                
                # "By David Foster and " part
                by_text = wx.StaticText(authors_area, label=AUTHORS_1_TEXT)
                by_text.SetFont(less_prominent_font)
                by_text.SetForegroundColour(less_prominent_color)
                authors_sizer.Add(by_text)
                
                # "contributors" clickable link
                contributors_link = ClickableText(
                    authors_area,
                    label=AUTHORS_2_TEXT,
                    url=AUTHORS_2_URL
                )
                contributors_link.SetFont(less_prominent_font)
                authors_sizer.Add(contributors_link)
            content_sizer.Add(
                authors_area,
                flag=wx.ALIGN_CENTER|wx.BOTTOM,
                border=12
            )
        
        # Copyright (multi-line)
        copyright_label = wx.StaticText(dialog, label=self._copyright_text())
        copyright_label.SetFont(less_prominent_font)
        copyright_label.SetForegroundColour(less_prominent_color)
        content_sizer.Add(
            copyright_label,
            flag=wx.ALIGN_CENTER|wx.BOTTOM,
            border=20
        )
        
        # OK button
        ok_button = wx.Button(dialog, wx.ID_OK, label='OK')
        content_sizer.Add(
            ok_button,
            flag=wx.ALIGN_CENTER
        )
        
        bind(dialog, wx.EVT_BUTTON, self._on_button)
        bind(dialog, wx.EVT_CLOSE, self._on_close)
        bind(dialog, wx.EVT_CHAR_HOOK, self._on_char_hook)
        bind(dialog, wx.EVT_SYS_COLOUR_CHANGED, self._on_system_appearance_changed)
        
        position_dialog_initially(dialog)
        dialog.Fit()
        if parent is not None:
            ShowWindowModal(dialog, modal_fallback=True)
        else:
            with dialog:
                ShowModal(dialog)
    
    @staticmethod
    def _copyright_text() -> str:
        # Format copyright as multi-line string
        copyright_text = APP_COPYRIGHT_STRING.replace('. ', '.\n')
        if '.' in copyright_text and not copyright_text.endswith('.'):
            copyright_text += '.'
        return copyright_text
    
    def _refresh_program_name(self) -> None:
        """Refresh the program name to reflect the new light/dark mode."""
        # Find the program name in the content sizer and store its flags
        sizer_index = self._program_name_sizer_index
        old_item = self._program_name_sizer.GetItem(sizer_index)
        assert old_item is not None
        flag = old_item.GetFlag()
        border = old_item.GetBorder()
        
        # Remove the old program name
        self._program_name_sizer.Remove(sizer_index)
        self._program_name.Destroy()
        
        # Create/insert new program name with updated appearance
        self._program_name = create_program_name_control(self.dialog)
        self._program_name_sizer.Insert(sizer_index, self._program_name, flag=flag, border=border)
        self.dialog.Layout()
    
    # === Events ===
    
    def _on_button(self, event: wx.CommandEvent) -> None:
        btn_id = event.GetEventObject().GetId()
        if btn_id == wx.ID_OK:
            self.dialog.Close()
    
    def _on_close(self, event: wx.CloseEvent) -> None:
        self._on_close_callback()
        
        # Return wx.OK to caller of ShowModal or ShowWindowModal
        suppress_destroy = False
        if self.dialog.Parent is None:
            self.dialog.EndModal(wx.OK)
            if getattr(self.dialog, 'cr_simulated_modal', False):
                # ShowModal in wx_dialog.py still needs to interact with the dialog object
                suppress_destroy = True
        
        # Dispose dialog, unless suppressed
        if not suppress_destroy:
            self.dialog.Destroy()
    
    def _on_char_hook(self, event: wx.KeyEvent) -> None:
        """Handle keyboard shortcuts, especially Return key for OK button."""
        if event.KeyCode == wx.WXK_RETURN or event.KeyCode == wx.WXK_NUMPAD_ENTER:
            # Activate the OK button when Return/Enter is pressed
            ok_button = self.dialog.FindWindowById(wx.ID_OK)
            assert ok_button is not None
            click_event = wx.CommandEvent(wx.wxEVT_COMMAND_BUTTON_CLICKED)
            click_event.EventObject = ok_button
            ok_button.Command(click_event)
            return  # don't propagate
        
        # Keep processing the event
        event.Skip()
    
    def _on_system_appearance_changed(self, event: wx.SysColourChangedEvent) -> None:
        """Update UI when system transitions to/from dark mode."""
        # NOTE: Duplicated in every handler for wx.SysColourChangedEvent
        SetDark(IsDarkNow())
        
        self._refresh_program_name()
        
        # Keep processing the event
        event.Skip()
    