import importlib.util
import inspect
import os
import sys
from typing import Callable


def tests_are_running() -> bool:
    return os.environ.get('CRYSTAL_RUNNING_TESTS', 'False') == 'True'


def set_tests_are_running() -> None:
    os.environ['CRYSTAL_RUNNING_TESTS'] = 'True'


def is_parallel() -> bool:
    """
    Returns whether tests are currently being run in parallel.
    """
    return (
        tests_are_running() and
        os.environ.get('CRYSTAL_IS_PARALLEL', 'False') == 'True'
    )


def test_function_caller() -> str | None:
    """
    Returns the name of the test function that directly called the caller of this function,
    or None if the caller of this function was not directly called by a test function.
    """
    # NOTE:
    # - stack()[0] is the current frame (this function)
    # - stack()[1] is the direct caller
    # - stack()[2] is the direct caller's caller; maybe a test
    frame_info = inspect.stack()[2]
    if frame_info.function.startswith("test_"):
        return frame_info.function
    else:
        return None
