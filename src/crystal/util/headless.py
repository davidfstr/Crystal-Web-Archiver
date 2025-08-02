# Whether we're running in headless mode (no wx main loop)
_headless_mode = False


def set_headless_mode(headless: bool) -> None:
    global _headless_mode
    _headless_mode = headless


def is_headless_mode() -> bool:
    return _headless_mode
