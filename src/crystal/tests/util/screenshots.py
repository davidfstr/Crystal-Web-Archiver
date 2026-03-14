from collections.abc import Callable, Iterator
from contextlib import contextmanager
import crystal
from crystal.util.xos import is_linux, is_mac_os
from crystal.util.xthreading import fg_call_and_wait
from functools import wraps
import os
import subprocess
import sys
from typing import TypeVar
from typing_extensions import ParamSpec


_P = ParamSpec('_P')
_T = TypeVar('_T')


def take_error_screenshot() -> None:
    """
    Takes a screenshot, just before an exception that will likely fail
    an automated test is about to be thrown.
    """
    # Take screenshot if screenshots directory path defined or guessable
    screenshots_dirpath = os.environ.get('CRYSTAL_SCREENSHOTS_DIRPATH')
    if screenshots_dirpath is None:
        # TODO: Does not correctly detect when running from source on Linux.
        #       Find a way to do that too.
        running_from_source = (
            getattr(sys, 'frozen', None) is None and 
            not is_linux()
        )
        if running_from_source:
            screenshots_dirpath = os.path.join(
                os.path.dirname(crystal.__file__),
                os.path.pardir,
                os.path.pardir,
                '.screenshots')
        else:
            print('*** Cannot take screenshot because CRYSTAL_SCREENSHOTS_DIRPATH not defined', file=sys.stderr)
            return
    
    os.makedirs(screenshots_dirpath, exist_ok=True)
    
    screenshot_id = os.environ.get('CRYSTAL_SCREENSHOT_ID', 'screenshot')
    screenshot_filepath = os.path.abspath(os.path.join(
        screenshots_dirpath, screenshot_filename := f'{screenshot_id}.png'))
    snapshot_filepath = os.path.abspath(os.path.join(
        screenshots_dirpath, snapshot_filename := f'{screenshot_id}.snapshot.txt'))
    
    print_screenshot_messages = os.environ.get('CRYSTAL_NO_SCREENSHOT_MESSAGES', 'False') != 'True'
    if print_screenshot_messages:
        abs_screenshots_dirpath_sep = os.path.abspath(os.path.join(screenshots_dirpath, ''))
        print(
            f'📷 Saving screenshot and snapshot to: {abs_screenshots_dirpath_sep}\n'
            f'    - {screenshot_filename} (best for humans; image)\n'
            f'    - {snapshot_filename} (best for AIs; accessibility tree)',
            file=sys.stderr
        )
    
    # Save screenshot
    try:
        if is_mac_os():
            # Use screencapture directly on macOS
            result = subprocess.call(['screencapture', '-x', screenshot_filepath])
            if result != 0:
                print(f'*** screencapture command failed with exit code: {result}', file=sys.stderr)
        else:
            # Use mss on other platforms
            try:
                import mss
                import mss.tools
            except ImportError:
                print('*** Unable to save screenshot because mss is not available.', file=sys.stderr)
                return
            with mss.mss() as sct:
                sct_img = sct.grab(sct.monitors[1])
                mss.tools.to_png(sct_img.rgb, sct_img.size, output=screenshot_filepath)
    except Exception as e:
        print(f'*** Failed to save screenshot: {e}', file=sys.stderr)
    else:
        if not os.path.exists(screenshot_filepath):
            print('*** Screenshot not saved. Is this macOS and the Screen Recording permission has not been granted?', file=sys.stderr)
    
    # Save snapshot
    with open(snapshot_filepath, 'w', encoding='utf-8') as snapshot_file:
        from crystal.ui.nav import T
        snapshot_file.write('>>> T\n')
        snapshot_file.write(fg_call_and_wait(lambda: repr(T)))


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
