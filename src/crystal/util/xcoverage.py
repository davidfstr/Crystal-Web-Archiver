from collections.abc import Iterator
from contextlib import contextmanager
import os


cov = None


@contextmanager
def collect_and_save() -> Iterator[None]:
    """
    Runs a context under code coverage, if the COVERAGE_RUN env var is set to a value.
    """
    global cov
    
    if os.environ.get('COVERAGE_RUN', None) is None:
        yield
        return
    
    import coverage
    cov = coverage.Coverage()  # export
    with cov.collect():
        yield
    cov.save()
    cov = None  # export


def switch_context(test_name: str = '') -> None:
    if cov is None:
        return
    cov.switch_context(test_name)
