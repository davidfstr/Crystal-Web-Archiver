from crystal.util.xos import is_linux
from crystal.util.xthreading import fg_affinity, fg_call_and_wait, is_foreground_thread
import wx


_is_dark = None  # type: bool | None


def IsDark() -> bool:
    """
    Safe replacement for wx.SystemSettings.GetAppearance().IsDark()
    which works on all threads.
    """
    if _is_dark is None:
        def init_is_dark() -> None:
            global _is_dark
            _is_dark = IsDarkNow()
        fg_call_and_wait(init_is_dark)
        assert _is_dark is not None
    return _is_dark


def SetDark(is_dark: bool) -> None:
    """
    Updates cached value of IsDark().
    
    Should be updated by a wx.EVT_SYS_COLOUR_CHANGED event handler
    somewhere in the app whenever IsDarkNow() changes.
    """
    global _is_dark
    _is_dark = is_dark


@fg_affinity
def IsDarkNow() -> bool:
    """
    Safe replacement for wx.SystemSettings.GetAppearance().IsDark(),
    which enforces use on the foreground thread.
    """
    return wx.SystemSettings.GetAppearance().IsDark()
