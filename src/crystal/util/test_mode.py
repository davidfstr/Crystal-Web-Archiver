import os


def tests_are_running() -> bool:
    return os.environ.get('CRYSTAL_RUNNING_TESTS', 'False') == 'True'


def set_tests_are_running() -> None:
    os.environ['CRYSTAL_RUNNING_TESTS'] = 'True'
