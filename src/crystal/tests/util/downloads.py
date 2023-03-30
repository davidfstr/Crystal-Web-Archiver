from contextlib import contextmanager
import crystal.task
from typing import Iterator


@contextmanager
def delay_between_downloads_minimized() -> Iterator[None]:
    old_value = crystal.task.DELAY_BETWEEN_DOWNLOADS
    # NOTE: Must be long enough so that download tasks stay around long enough
    #       to be observed, but short enough to provide a speed boost
    crystal.task.DELAY_BETWEEN_DOWNLOADS = 0.2
    try:
        yield
    finally:
        crystal.task.DELAY_BETWEEN_DOWNLOADS = old_value
