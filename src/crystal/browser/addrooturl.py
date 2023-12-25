from crystal.util.wx_bind import bind
from crystal.util.wx_dialog import position_dialog_initially
from crystal.util.xos import is_wx_gtk
from typing import Callable
import wx


_WINDOW_INNER_PADDING = 10
_FORM_LABEL_INPUT_SPACING = 5
_FORM_ROW_SPACING = 10


class AddRootUrlDialog:
    _INITIAL_URL_WIDTH = 400  # in pixels
    
    # === Init ===
    
    def __init__(self,
            parent: wx.Window,
            on_finish: Callable[[str, str], None],
            initial_url: str='',
            ) -> None:
        """
        Arguments:
        * parent -- parent wx.Window that this dialog is attached to.
        * on_finish -- called when OK pressed on dialog. Is a callable(name, url).
        * initial_url -- overrides the initial URL displayed.
        """
        self._on_finish = on_finish
        
        dialog = self.dialog = wx.Dialog(
            parent, title='New Root URL', name='cr-add-url-dialog',
            style=wx.DEFAULT_DIALOG_STYLE|wx.RESIZE_BORDER)
        dialog_sizer = wx.BoxSizer(wx.VERTICAL)
        dialog.SetSizer(dialog_sizer)
        bind(dialog, wx.EVT_BUTTON, self._on_button)
        bind(dialog, wx.EVT_CLOSE, self._on_close)
        
        dialog_sizer.Add(self._create_fields(dialog, initial_url), flag=wx.EXPAND|wx.ALL,
            border=_WINDOW_INNER_PADDING)
        dialog_sizer.Add(dialog.CreateButtonSizer(wx.OK|wx.CANCEL), flag=wx.EXPAND|wx.BOTTOM,
            border=_WINDOW_INNER_PADDING)
        
        if not fields_hide_hint_when_focused():
            self.url_field.SetFocus()  # initialize focus
        
        position_dialog_initially(dialog)
        dialog.Show(True)
        dialog.Fit()  # NOTE: Must Fit() after Show() here so that wxGTK actually fits correctly
        
        dialog.MinSize = dialog.Size
        dialog.MaxSize = wx.Size(wx.DefaultCoord, dialog.Size.Height)
    
    def _create_fields(self, parent: wx.Window, initial_url: str) -> wx.Sizer:
        fields_sizer = wx.FlexGridSizer(rows=2, cols=2,
            vgap=_FORM_ROW_SPACING, hgap=_FORM_LABEL_INPUT_SPACING)
        fields_sizer.AddGrowableCol(1)
        
        url_label = wx.StaticText(parent, label='URL:', style=wx.ALIGN_RIGHT)
        url_label.Font = url_label.Font.Bold()  # mark as required
        fields_sizer.Add(url_label, flag=wx.EXPAND)
        
        self.url_field = wx.TextCtrl(
            parent, value=initial_url,
            size=(self._INITIAL_URL_WIDTH, wx.DefaultCoord),
            name='cr-add-url-dialog__url-field')
        self.url_field.Hint = 'https://example.com/'
        self.url_field.SetSelection(-1, -1)  # select all upon focus
        fields_sizer.Add(self.url_field, flag=wx.EXPAND)
        
        fields_sizer.Add(wx.StaticText(parent, label='Name:', style=wx.ALIGN_RIGHT), flag=wx.EXPAND)
        
        self.name_field = wx.TextCtrl(
            parent,
            name='cr-add-url-dialog__name-field')
        self.name_field.Hint = 'Home'
        self.name_field.SetSelection(-1, -1)  # select all upon focus
        fields_sizer.Add(self.name_field, flag=wx.EXPAND)
        
        return fields_sizer
    
    # === Events ===
    
    def _on_button(self, event: wx.CommandEvent) -> None:
        btn_id = event.GetEventObject().GetId()
        if btn_id == wx.ID_OK:
            self._on_ok(event)
        elif btn_id == wx.ID_CANCEL:
            self._on_cancel(event)
    
    def _on_close(self, event: wx.CommandEvent) -> None:
        self._on_cancel(event)
    
    def _on_ok(self, event: wx.CommandEvent) -> None:
        name = self.name_field.GetValue()
        url = self.url_field.GetValue()
        self._on_finish(name, url)
        self.dialog.Destroy()
    
    def _on_cancel(self, event: wx.CommandEvent) -> None:
        self.dialog.Destroy()


def fields_hide_hint_when_focused() -> bool:
    return is_wx_gtk()
