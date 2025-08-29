from collections.abc import Callable, Generator
from crystal import resources
from crystal.util.test_mode import tests_are_running
from crystal.util.wx_bind import bind
from crystal.util.xos import is_kde_or_non_gnome, is_mac_os, is_windows, is_wx_gtk
from crystal.util.xthreading import ContinueSoonFunc, FgCommand, fg_affinity
from types import coroutine
from typing import Protocol
import warnings
import wx
from wx import FileDialog as UnpatchedFileDialog


# ------------------------------------------------------------------------------
# wx.Dialog.ShowModal

def ShowModal(dialog: wx.Dialog) -> int:
    """
    Replacement for wx.Dialog.ShowModal() that works properly even when
    running automated tests.
    
    Automated tests should patch this function to replace it with a
    `mocked_show_modal()` function rather than setting a return value directly.
    """
    is_running_tests = tests_are_running()  # cache
    
    if not isinstance(dialog, wx.MessageDialog):
        warnings.warn(
            'ShowModalAsync should be preferred for showing modal dialogs '
            'other than wx.MessageDialog because it is less prone to deadlocks.',
            category=DeprecationWarning,
            stacklevel=2
        )
    
    if is_running_tests and isinstance(dialog, UnpatchedFileDialog):
        raise AssertionError(
            f'Attempted to call ShowModal utility on wx.FileDialog {dialog.Name!r} '
            f'but the real wx.FileDialog.ShowModal() should be used instead '
            f'because file_dialog_returning() patches the real ShowModal().')
    
    if is_running_tests and isinstance(dialog, wx.MessageDialog):
        # A wx.MessageDialog opened with ShowModal cannot be interacted
        # with via wx.FindWindowByName() and similar functions on macOS.
        # So don't allow such a dialog to be shown while tests are running.
        raise AssertionError(
            f'Attempted to call ShowModal utility on wx.MessageDialog {dialog.Name!r} '
            f'while running an automated test, which would hang the test. '
            f'Please patch ShowModal to return an appropriate result. '
            f'Caption={dialog.Caption!r}, Message={dialog.Message!r}')
    
    # HACK: ShowModal sometimes hangs on macOS while running automated tests,
    #       as admitted by the wxPython test suite in test_dialog.py.
    #       So simulate its effect in a way that does NOT hang while running tests.
    if is_running_tests and is_mac_os():
        dialog.SetReturnCode(0)
        dialog.Show()
        
        loop = wx.GetApp().GetTraits().CreateEventLoop()
        with wx.EventLoopActivator(loop):
            while dialog.GetReturnCode() == 0:
                loop.Dispatch()
                if not dialog.IsShown() and dialog.GetReturnCode() == 0:
                    dialog.SetReturnCode(wx.ID_CANCEL)
        
        return dialog.GetReturnCode()
    else:
        return dialog.ShowModal()


class ShowModalFunc(Protocol):
    call_count: int
    def __call__(self, dialog: wx.Dialog) -> int: ...


def mocked_show_modal(
        dialog_name: str,
        return_code: int | Callable[[wx.Dialog], int],
        ) -> ShowModalFunc:
    """
    Creates a mocked version of ShowModal which verifies that the expected
    dialog was opened and returns the provided return code.
    """
    ShowModal: ShowModalFunc
    def ShowModal(dialog: wx.Dialog) -> int:  # type: ignore[no-redef]
        assert dialog_name == dialog.Name, (
            f'Expected dialog with name {dialog_name!r}, got {dialog.Name!r}. '
            f'Caption={dialog.Caption!r}, Message={dialog.Message!r}')
        ShowModal.call_count += 1
        if callable(return_code):
            return return_code(dialog)
        else:
            return return_code
    ShowModal.call_count = 0
    return ShowModal

# ------------------------------------------------------------------------------
# ShowModalAsync

@coroutine
@fg_affinity
def ShowModalAsync(dialog: wx.Dialog) -> Generator[FgCommand, ContinueSoonFunc | int, int]:
    """
    Shows the specified dialog and suspends until the dialog is closed,
    usually by the user clicking a button.
    
    Must be called from within a coroutine run by start_fg_coroutine().
    
    Example:
        async def my_fg_coroutine() -> None:
            dialog = ...
            return_code = await ShowModalAsync(dialog)
            ...  # do something with the return code
        
        start_fg_coroutine(my_fg_coroutine)
    """
    continue_soon_func = yield FgCommand.GET_CONTINUE_SOON_FUNC
    assert callable(continue_soon_func)  # is a ContinueSoonFunc
    
    def on_button(event: wx.CommandEvent) -> None:
        dialog.SetReturnCode(event.GetId())
        on_close()

    def on_char_hook(event: wx.KeyEvent) -> None:
        # TODO: Support Command-Period on macOS. Unfortunately the following
        #       never returns true: `keycode == ord('.') and event.CmdDown()`
        is_cancel_gesture = (
            # Esc key
            event.KeyCode == wx.WXK_ESCAPE
        )
        
        if is_cancel_gesture:
            # Try to find a cancel button
            cancel_btn = dialog.FindWindowById(wx.ID_CANCEL)
            if cancel_btn and cancel_btn.IsEnabled():
                cancel_btn.Command(wx.EVT_BUTTON.typeId)
            else:
                dialog.SetReturnCode(dialog.GetEscapeId())
                on_close()
            return  # don't propagate
        
        event.Skip()
    
    def on_close(event: wx.CloseEvent | None = None):
        if event is not None:
            dialog.SetReturnCode(dialog.GetEscapeId())
        
        return_code = dialog.GetReturnCode()  # capture
        # NOTE: The caller is responsible for destroying the dialog
        dialog.Hide()
        continue_soon_func(return_code)

    bind(dialog, wx.EVT_BUTTON, on_button)
    bind(dialog, wx.EVT_CHAR_HOOK, on_char_hook)
    bind(dialog, wx.EVT_CLOSE, on_close)
    dialog.Show()
    
    return_code = yield FgCommand.SUSPEND_UNTIL_CONTINUE
    assert isinstance(return_code, int)
    return return_code


# ------------------------------------------------------------------------------
# ShowWindowModal

def ShowWindowModal(dialog: wx.Dialog) -> None:
    """
    Shows a dialog as window-modal, preventing interaction with the parent window
    but allowing interaction with other application windows.
    
    This is a cross-platform wrapper that:
    - Uses ShowWindowModal() on macOS and Windows
    - Falls back to Show() on Linux (due to platform limitations)
    
    Window-modal dialogs prevent the user from interacting with the parent
    window until the dialog is closed, but still allow interaction with other
    application windows and the system.
    """
    if is_wx_gtk() or (is_windows() and tests_are_running()):
        # 1. GTK sometimes segfaults when closing a dialog displayed as window-modal.
        #    So don't use ShowWindowModal() on GTK.
        # 2. Windows won't process wx events properly when a window-modal
        #    dialog is open, which blocks automated tests from executing.
        #    So don't use ShowWindowModal() on Windows during tests.
        dialog.Show()
    else:
        # 1. macOS fully supports window-modal dialogs
        # 2. Windows partially supports window-modal dialogs,
        #    disabling interactions on the parent window,
        #    but NOT visually disabling any controls.
        dialog.ShowWindowModal()


# ------------------------------------------------------------------------------
# Misc Utilities

def add_title_heading_to_dialog_if_needed(
        dialog: wx.Dialog,
        dialog_sizer: wx.Sizer,
        border: int,
        ) -> None:
    """
    Adds a title heading to a window-modal dialog on macOS where window-modal dialogs
    don't show title bars. On other platforms, this is a no-op.
    
    Arguments:
    * dialog -- the dialog to add the title heading to
    * dialog_sizer -- the main vertical sizer for the dialog content
    * border -- the border/padding to use around the title heading
    """
    if not is_mac_os():
        return
    
    title_text = wx.StaticText(dialog, label=dialog.Title)
    title_text.Font = title_text.Font.MakeBold().MakeLarger()
    dialog_sizer.Add(
        title_text,
        flag=wx.EXPAND|wx.LEFT|wx.RIGHT|wx.TOP,
        border=border)


def position_dialog_initially(dialog: wx.Dialog) -> None:
    """
    Reposition the specified dialog by a default offset relative to
    its parent window.
    
    Different operating systems open dialogs at various positions
    relative to their parent window. This function standardizes
    the behavior across different operating systems. Native behavior:
    - macOS 10.14: (0, 0) offset
    - Windows 7: (200, 200) offset
    - Windows 10: (150, 200) offset
    - Ubuntu 22: (100, 100) offset
    """
    if dialog.Parent is None:
        return
    new_position = dialog.Parent.Position
    new_position.x += (150 // 2)
    new_position.y += (200 // 2)
    # NOTE: Linux sometimes ignores repositioning requests,
    #       especially if Wayland is being used rather than X11
    dialog.Position = new_position


def set_dialog_or_frame_icon_if_appropriate(tlw: wx.TopLevelWindow) -> None:
    # 1. Windows: Define app icon in the top-left corner
    # 2. KDE: Define app icon in the top-left corner and in the dock
    if is_windows() or is_kde_or_non_gnome():
        tlw.SetIcons(wx.IconBundle(resources.open_binary('appicon.ico')))


def CreateButtonSizer(
        parent: wx.Dialog,
        affirmative_id: int | None=None,
        cancel_id=wx.ID_CANCEL,
        ) -> wx.Sizer:
    """
    Has a similar effect as wx.Dialog.CreateButtonSizer() but supports any
    value for the `affirmative_id`.
    """
    sizer = wx.StdDialogButtonSizer()
    
    if affirmative_id is not None:
        affirmative_button = wx.Button(parent, affirmative_id)
        affirmative_button.SetDefault()
        sizer.SetAffirmativeButton(affirmative_button)
    
    sizer.SetCancelButton(wx.Button(parent, cancel_id))
    
    sizer.Realize()
    return sizer


# ------------------------------------------------------------------------------