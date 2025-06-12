from collections.abc import Callable, Iterator
from contextlib import contextmanager
from crystal.util import cli
import sys
import traceback
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import wx


def bind(
        window: 'wx.Window', 
        event_type, 
        target: 'Callable[[wx.Event], None]',
        *args
        ) -> None:
    """
    Equivalent to wx.Window.Bind(), but safer.
    """
    window.Bind(event_type, _bind_target()(target), *args)


@contextmanager
def _bind_target() -> Iterator[None]:
    """
    Decorates any function that is a target of wx.Window.Bind().
    
    Will handle any uncaught exceptions by printing their traceback
    and swallowing them to prevent them from bubbling up to wx.
    
    It has been observed at least on macOS that uncaught exceptions
    that make it to wx can put it into an invalid state that will
    cause a segmentation fault later (especially when Python exits).
    """
    try:
        yield
    except BaseException:
        err_file = sys.stderr
        print(cli.TERMINAL_FG_RED, end='', file=err_file)
        print('Exception in wxPython listener:', file=err_file)
        traceback.print_exc(file=err_file)
        print(cli.TERMINAL_RESET, end='', file=err_file)
        err_file.flush()

