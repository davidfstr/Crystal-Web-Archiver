# ------------------------------------------------------------------------------
# Terminal Colors

_USE_COLORS = True

# ANSI color codes
# Obtained from: http://www.bri1.com/files/06-2008/pretty.py
_TERM_FG_BLUE =          '\033[0;34m'
_TERM_FG_BOLD_BLUE =     '\033[1;34m'
_TERM_FG_RED =           '\033[0;31m'
_TERM_FG_BOLD_RED =      '\033[1;31m'
_TERM_FG_GREEN =         '\033[0;32m'
_TERM_FG_BOLD_GREEN =    '\033[1;32m'
_TERM_FG_CYAN =          '\033[0;36m'
_TERM_FG_BOLD_CYAN =     '\033[1;36m'
_TERM_FG_YELLOW =        '\033[0;33m'
_TERM_FG_BOLD_YELLOW =   '\033[1;33m'
_TERM_RESET =            '\033[0m'


def print_success(message: str) -> None:
    print(_colorize(_TERM_FG_GREEN, message))


def print_error(message: str) -> None:
    print(_colorize(_TERM_FG_RED, message))


def print_warning(message: str) -> None:
    print(_colorize(_TERM_FG_YELLOW, message))


def print_info(message: str) -> None:
    print(_colorize(_TERM_FG_CYAN, message))


def _colorize(color_code, str_value):
    return (color_code + str_value + _TERM_RESET) if _USE_COLORS else str_value


# ------------------------------------------------------------------------------
