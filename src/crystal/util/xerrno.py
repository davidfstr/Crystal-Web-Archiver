import errno


def is_path_too_long_error(exc: BaseException) -> bool:
    """
    Return whether the given exception looks like a 'path too long' error
    on the current platform.
    """
    return (
        isinstance(exc, OSError) and
        (
            # POSIX case
            exc.errno == errno.ENAMETOOLONG or
            # Windows case: ERROR_FILENAME_EXCED_RANGE
            getattr(exc, "winerror", None) == 206
        )
    )
