from contextlib import contextmanager
import traceback
from typing import Callable, Iterator, TYPE_CHECKING

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
    window.Bind(event_type, bind_target()(target), *args)


@contextmanager
def bind_target() -> Iterator[None]:
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
    except BaseException as e:
        traceback.print_exc()
