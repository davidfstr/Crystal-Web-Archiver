"""
Code coverage gathering utilities.

Top-level code in this module is marked with "# pragma: no cover" because it 
must be loaded before coverage instrumentation is started, 
so will never be observed as covered.
"""

from collections.abc import Iterator  # pragma: no cover
from contextlib import contextmanager  # pragma: no cover
import os  # pragma: no cover


cov = None  # pragma: no cover


@contextmanager  # pragma: no cover
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


def switch_context(test_name: str = '') -> None:  # pragma: no cover
    """
    Changes the test name that subsequent executed lines will be attributed to.
    
    Omit the test name to attribute lines to the test runner itself.
    """
    if cov is None:
        return
    cov.switch_context(test_name)
