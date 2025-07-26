"""
Keeps track of whether the application is quitting.
"""

# Whether the user has requested that the application quit.
_is_quitting = False

# The exit code that the main thread is trying to quit with, if any.
_exit_code = None  # type: int | None


def is_quitting() -> bool:
    return _is_quitting


def set_is_quitting() -> None:
    global _is_quitting
    _is_quitting = True


def set_exit_code(exit_code: int) -> None:
    global _exit_code
    _exit_code = exit_code


def get_exit_code() -> int | None:
    return _exit_code
