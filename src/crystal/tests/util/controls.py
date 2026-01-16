from collections.abc import Iterator
from contextlib import contextmanager
from unittest.mock import patch
import wx


# ------------------------------------------------------------------------------
# wx.FileDialog

@contextmanager
def file_dialog_returning(filepath: str | list[str]) -> Iterator[None]:
    filepaths = filepath if isinstance(filepath, list) else [filepath]
    
    with patch('wx.FileDialog', spec=True) as MockFileDialog:
        instance = MockFileDialog.return_value
        instance.ShowModal.return_value = wx.ID_OK
        instance.GetPath.side_effect = filepaths
        
        yield
        
        if instance.ShowModal.call_count != len(filepaths):
            raise AssertionError(
                f'Expected wx.FileDialog.ShowModal to be called exactly {len(filepaths)} time(s), '
                f'but it was called {instance.ShowModal.call_count} time(s)')


# ------------------------------------------------------------------------------
# wx.Menu

# TODO: Alter callers that use the {menu, menuitem_id} signature to use {menuitem} instead
#       when possible because it requires less bookkeeping in the caller.
def select_menuitem_now(
        menu: wx.Menu | None = None,
        menuitem_id: int | None = None,
        *, menuitem: wx.MenuItem | None = None
        ) -> None:
    """
    Selects a menu item immediately.
    
    Either both `menu` and `menuitem_id` must be specified, or `menuitem` must be.
    """
    if menuitem is None:
        if menu is None or menuitem_id is None:
            raise ValueError('Either both `menu` and `menuitem_id` must be specified, or `menuitem` must be specified')
    else:
        menu = menuitem.GetMenu()
        menuitem_id = menuitem.GetId()
        
        assert menuitem.IsEnabled(), \
            f'Menu item {menuitem.GetItemLabelText()!r} is not enabled'
    
    # Process the related wx.EVT_MENU event immediately,
    # so that the event handler is called before the wx.Menu is disposed
    event = wx.MenuEvent(type=wx.EVT_MENU.typeId, id=menuitem_id, menu=None)
    menu.ProcessEvent(event)


# ------------------------------------------------------------------------------
