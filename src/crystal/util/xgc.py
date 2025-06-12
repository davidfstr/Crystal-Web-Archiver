from collections.abc import Iterator
from contextlib import contextmanager
import gc
import os
import sys
import time

# If True, then the runtime of foreground tasks is tracked to ensure
# they are short. This is necessary to keep the UI responsive.
PROFILE_GC = os.environ.get('CRYSTAL_NO_PROFILE_GC', 'False') != 'True'

# Maximum reasonable time that foreground tasks should take to complete.
# If profiling is enabled, warnings will be printed for tasks whose runtime
# exceeds this threshold.
_GC_RUNTIME_THRESHOLD = 1.0 # sec


def start_profiling_gc() -> None:
    last_gc_start = None
    def on_gc(phase: str, info: dict) -> None:
        nonlocal last_gc_start
        now = time.time()  # capture
        if phase == 'start':
            last_gc_start = now
        elif phase == 'stop':
            if last_gc_start is not None:
                duration = now - last_gc_start
                if duration > _GC_RUNTIME_THRESHOLD:
                    print('*** {} took {:.02f}s to execute: {!r}'.format(
                        'Garbage collection',
                        duration,
                        info,
                    ), file=sys.stderr)
                
                last_gc_start = None
    gc.callbacks.append(on_gc)


@contextmanager
def gc_disabled() -> Iterator[None]:
    """
    Context in which garbage collection is disabled.
    
    Useful when allocating a very large number of long-lived objects,
    to avoid many useless runs of the garbage collector.
    """
    was_enabled = gc.isenabled()
    if was_enabled:
        gc.disable()
    try:
        yield
    finally:
        assert not gc.isenabled()
        if was_enabled:
            gc.enable()
