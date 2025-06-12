from io import TextIOBase

# ------------------------------------------------------------------------------
# Terminal Colors

_USE_COLORS = True

# ANSI color codes
# Obtained from: http://www.bri1.com/files/06-2008/pretty.py
TERMINAL_FG_BLUE =          '\033[0;34m'
TERMINAL_FG_BOLD_BLUE =     '\033[1;34m'
TERMINAL_FG_RED =           '\033[0;31m'
TERMINAL_FG_BOLD_RED =      '\033[1;31m'
TERMINAL_FG_GREEN =         '\033[0;32m'
TERMINAL_FG_BOLD_GREEN =    '\033[1;32m'
TERMINAL_FG_CYAN =          '\033[0;36m'
TERMINAL_FG_BOLD_CYAN =     '\033[1;36m'
TERMINAL_FG_YELLOW =        '\033[0;33m'
TERMINAL_FG_BOLD_YELLOW =   '\033[1;33m'
TERMINAL_RESET =            '\033[0m'


def print_success(message: str, file: TextIOBase | None=None) -> None:
    print(_colorize(TERMINAL_FG_GREEN, message), file=file)


def print_error(message: str, file: TextIOBase | None=None) -> None:
    print(_colorize(TERMINAL_FG_RED, message), file=file)


def print_warning(message: str, file: TextIOBase | None=None) -> None:
    print(_colorize(TERMINAL_FG_YELLOW, message), file=file)


def print_info(message: str, file: TextIOBase | None=None) -> None:
    print(_colorize(TERMINAL_FG_CYAN, message), file=file)


def _colorize(color_code: str, str_value: str) -> str:
    return (color_code + str_value + TERMINAL_RESET) if _USE_COLORS else str_value


# ------------------------------------------------------------------------------
