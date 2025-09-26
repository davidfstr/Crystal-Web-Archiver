from collections.abc import Callable, Iterator
from contextlib import contextmanager
from crystal.util.xos import is_mac_os
from functools import wraps
import os
import subprocess
import sys
import tempfile
from typing import TypeVar
from typing_extensions import ParamSpec

_P = ParamSpec('_P')
_T = TypeVar('_T')


def take_error_screenshot() -> None:
    """
    Takes a screenshot, just before an exception that will likely fail
    an automated test is about to be thrown.
    """
    # Take screenshot if screenshots directory path defined
    screenshots_dirpath = os.environ.get('CRYSTAL_SCREENSHOTS_DIRPATH')
    if screenshots_dirpath is None:
        return
    
    os.makedirs(screenshots_dirpath, exist_ok=True)
    
    screenshot_filename = os.environ.get('CRYSTAL_SCREENSHOT_ID', 'screenshot') + '.png'
    screenshot_filepath = os.path.abspath(os.path.join(screenshots_dirpath, screenshot_filename))
    print_screenshot_messages = os.environ.get('CRYSTAL_NO_SCREENSHOT_MESSAGES', 'False') != 'True'
    if print_screenshot_messages:
        print('*** Saving screenshot to: ' + screenshot_filepath, file=sys.stderr)
    
    try:
        if is_mac_os():
            # Use screencapture directly on macOS
            result = subprocess.call(['screencapture', '-x', screenshot_filepath])
            if result != 0:
                print(f'*** screencapture command failed with exit code: {result}', file=sys.stderr)
        else:
            # Use PIL/pyscreeze on other platforms
            try:
                import PIL
            except ImportError:
                print('*** Unable to save screenshot because PIL is not available, which pyscreeze depends on.', file=sys.stderr)
                return
            try:
                import pyscreeze
            except ImportError:
                print('*** Unable to save screenshot because pyscreeze is not available.', file=sys.stderr)
                return
            
            pyscreeze.screenshot(screenshot_filepath)
    except Exception as e:
        print(f'*** Failed to save screenshot: {e}', file=sys.stderr)
    else:
        if not os.path.exists(screenshot_filepath):
            print('*** Screenshot not saved. Is this macOS and the Screen Recording permission has not been granted?', file=sys.stderr)


@contextmanager
def screenshot_if_raises() -> Iterator[None]:
    """
    Context that will take a screenshot if an exception is raised within it.
    """
    try:
        yield
    except:
        take_error_screenshot()
        raise


def screenshot_if_raises_deco(callable: Callable[_P, _T]) -> Callable[_P, _T]:
    """
    Decorates a function to make it take a screenshot whenever it raises an exception.
    """
    @wraps(callable)
    def wrapped(*args: _P.args, **kwargs: _P.kwargs) -> _T:
        with screenshot_if_raises():
            return callable(*args, **kwargs)
    return wrapped
