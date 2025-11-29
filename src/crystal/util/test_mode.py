import inspect
import os


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


def is_called_from_a_test() -> bool:
    """
    Returns whether the caller of this function was called directly from 
    a test function.
    """
    # NOTE:
    # - stack()[0] is the current frame (this function)
    # - stack()[1] is the direct caller
    # - stack()[2] is the direct caller's caller; maybe a test
    return inspect.stack()[2].function.startswith("test_")
