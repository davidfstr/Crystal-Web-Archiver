from collections.abc import Iterator
from contextlib import contextmanager
import sys
import time
import traceback


_MAX_SLEEP_IMPRECISION_MULTIPLIER = 15


_avoid_calling_time_monotonic = False


@contextmanager
def time_monotonic_calls_avoided() -> Iterator[None]:
    """
    Context in which optional calls to time.monotonic() are avoided.
    
    Useful when time.monotonic() is being mocked.
    """
    global _avoid_calling_time_monotonic
    assert _avoid_calling_time_monotonic == False
    _avoid_calling_time_monotonic = True
    try:
        yield
    finally:
        _avoid_calling_time_monotonic = False


def avoid_calling_time_monotonic() -> bool:
    """Whether calls to time.monotonic() should be avoided."""
    return _avoid_calling_time_monotonic


@contextmanager
def sleep_profiled() -> Iterator[None]:
    """
    Context in which warnings are printed if time.sleep() sleeps for vastly
    longer than the duration that it was requested to sleep.
    """
    super_sleep = time.sleep
    
    def sleep(secs: float) -> None:
        if _avoid_calling_time_monotonic:
            start_time = -1.0
        else:
            start_time = time.monotonic()  # capture
            _warn_if_monotonic_time_value_suspicious(start_time)
        try:
            super_sleep(secs)
        finally:
            if secs > 0:
                if _avoid_calling_time_monotonic or start_time == -1.0:
                    pass
                else:
                    end_time = time.monotonic()
                    _warn_if_monotonic_time_value_suspicious(end_time)
                    delta_time = end_time - start_time
                    if delta_time > secs * _MAX_SLEEP_IMPRECISION_MULTIPLIER:
                        print('*** {} took {:.02f}s to execute: {}'.format(
                            f'sleep({secs})',
                            delta_time,
                            'Stack:',
                        ), file=sys.stderr)
                        traceback.print_stack(file=sys.stderr)
    
    time.sleep = sleep
    try:
        yield
    finally:
        time.sleep = super_sleep


def _warn_if_monotonic_time_value_suspicious(time_value: float) -> None:
    if time_value < 10.0:
        print(
            f'*** time.monotonic() is reporting an unusually low time '
            f'of {time_value:.02f}. Is it being mocked?'
        )