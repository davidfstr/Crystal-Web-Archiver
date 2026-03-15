import sys
import threading
import traceback
from types import FrameType


def get_thread_stack(thread: threading.Thread) -> str | None:
    """
    Returns a formatted stack trace for the given thread, or None if unavailable.
    """
    # Only works for current process threads
    frames = sys._current_frames()
    ident = thread.ident
    if ident is not None and ident in frames:
        frame: FrameType = frames[ident]
        return ''.join(traceback.format_stack(frame))
    return None
