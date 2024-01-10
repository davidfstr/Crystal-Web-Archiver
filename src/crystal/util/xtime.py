from contextlib import contextmanager
import sys
import time
from typing import Iterator


_MAX_SLEEP_IMPRECISION_MULTIPLIER = 15


@contextmanager
def sleep_profiled() -> Iterator[None]:
    super_sleep = time.sleep
    
    def sleep(secs: float) -> None:
        start_time = time.time()  # capture
        try:
            super_sleep(secs)
        finally:
            if secs > 0:
                delta_time = time.time() - start_time
                if delta_time > secs * _MAX_SLEEP_IMPRECISION_MULTIPLIER:
                    print('*** %s took %.02fs to execute' % (
                        f'sleep({secs})',
                        delta_time,
                    ), file=sys.stderr)
    
    time.sleep = sleep
    try:
        yield
    finally:
        time.sleep = super_sleep
