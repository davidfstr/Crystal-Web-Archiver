from crystal.util.test_mode import is_parallel, test_function_caller, tests_are_running
from crystal.util.xos import is_wx_gtk
import sys
from types import EllipsisType
from typing import Literal
from unittest import SkipTest
import wx


# TODO: Is it necessary to pass an explicit `previously_focused` value
#       if that information can already be determined automatically?
def SetFocus(
        window: wx.Window,
        previously_focused: wx.Window | None | EllipsisType = Ellipsis,
        *, simulate_events: bool | None=None) -> wx.Window:
    """
    Replacement for wx.Window.SetFocus() that works properly even on Linux.
    
    On Linux - or if simulate_events=True - focus and blur events will
    be manually simulated on the old and new components exchanging focus.
    
    Returns the window that was focused.
    """
    if tests_are_running() and is_parallel() and ((caller_test_name := test_function_caller()) is not None):
        from crystal.tests.util.mark import serial_only
        if caller_test_name not in serial_only.test_names:  # type: ignore[attr-defined]
            raise AssertionError(f'focus-sensitive test {caller_test_name} must be marked with @serial_only')
        raise SkipTest('focus-sensitive test must be run in serial, not in parallel')
    
    if previously_focused is Ellipsis:
        previously_focused = wx.Window.FindFocus()
    assert not isinstance(previously_focused, EllipsisType)  # help mypy
    
    if simulate_events is None:  # auto
        simulate_events = (
            # wxGTK's SetFocus() doesn't appear to have any effect
            is_wx_gtk()
        )
    
    if simulate_events:
        # Simulate focus and blur events
        
        # Keep focus state in UI up-to-date so that UI doesn't issue
        # its own focus/blur events unexpectedly later
        window.SetFocus()  # pylint: disable=no-direct-setfocus
        
        # Simulate blur event
        if previously_focused is not None:
            event = wx.FocusEvent(wx.EVT_KILL_FOCUS.typeId, previously_focused.GetId())
            event.SetEventObject(previously_focused)
            assert event.GetEventObject().GetId() == previously_focused.GetId()
            event.SetWindow(window)  # yes, the next window
            previously_focused.HandleWindowEvent(event)
        
        # Simulate focus event
        event = wx.FocusEvent(wx.EVT_SET_FOCUS.typeId, window.GetId())
        event.SetEventObject(window)
        assert event.GetEventObject().GetId() == window.GetId()
        event.SetWindow(previously_focused)  # yes, the previous window
        window.HandleWindowEvent(event)
    else:
        actual_previously_focused = wx.Window.FindFocus()
        if previously_focused != actual_previously_focused:
            print(
                f'*** SetFocus: Expected previously focused window to be '
                f'{previously_focused} but was instead '
                f'{actual_previously_focused}',
                file=sys.stderr)
        
        window.SetFocus()  # pylint: disable=no-direct-setfocus
    
    return window
