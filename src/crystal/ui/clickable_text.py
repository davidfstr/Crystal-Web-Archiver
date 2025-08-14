
import webbrowser
import wx


class ClickableText(wx.StaticText):
    """A StaticText control that acts like a hyperlink."""
    
    def __init__(self, parent: wx.Window, label: str, url: str) -> None:
        super().__init__(parent, label=label)
        self._url = url
        self.SetForegroundColour(wx.SystemSettings.GetColour(wx.SYS_COLOUR_HOTLIGHT))
        self.SetCursor(wx.Cursor(wx.CURSOR_HAND))
        self.Bind(wx.EVT_LEFT_UP, self._on_click)
        self.Bind(wx.EVT_ENTER_WINDOW, self._on_enter)
        self.Bind(wx.EVT_LEAVE_WINDOW, self._on_leave)
    
    def _on_click(self, event: wx.MouseEvent) -> None:
        webbrowser.open(self._url)
    
    def _on_enter(self, event: wx.MouseEvent) -> None:
        # Add underline on hover
        font = self.GetFont()
        font.SetUnderlined(True)
        self.SetFont(font)
    
    def _on_leave(self, event: wx.MouseEvent) -> None:
        # Remove underline when not hovering
        font = self.GetFont()
        font.SetUnderlined(False)
        self.SetFont(font)
