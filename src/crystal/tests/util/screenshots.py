from contextlib import contextmanager
from crystal.util.xos import is_mac_os
import os
import sys
from typing import Iterator


@contextmanager
def screenshot_if_raises() -> Iterator[None]:
    try:
        yield
    except:
        # Take screenshot if screenshots directory path defined
        screenshots_dirpath = os.environ.get('CRYSTAL_SCREENSHOTS_DIRPATH')
        if screenshots_dirpath is not None:
            try:
                import PIL
            except ImportError:
                print('*** Unable to save screenshot because PIL is not available, which pyscreeze depends on.', file=sys.stderr)
            else:
                try:
                    import pyscreeze
                except ImportError:
                    print('*** Unable to save screenshot because pyscreeze is not available.', file=sys.stderr)
                else:
                    # HACK: Force pyscreeze to use 'screencapture' tool on macOS
                    # in _screenshot_osx() rather than ImageGrab.grab(),
                    # which doesn't seem to work on macOS 12+
                    if is_mac_os():
                        pyscreeze.PIL__version__ = [1, 0, 0]  # pretend PIL is old version
                    
                    os.makedirs(screenshots_dirpath, exist_ok=True)
                    
                    screenshot_filename = os.environ.get('CRYSTAL_SCREENSHOT_ID', 'screenshot') + '.png'
                    screenshot_filepath = os.path.abspath(os.path.join(screenshots_dirpath, screenshot_filename))
                    print('*** Saving screenshot to: ' + screenshot_filepath, file=sys.stderr)
                    pyscreeze.screenshot(screenshot_filepath)
                    if not os.path.exists(screenshot_filepath):
                        print('*** Screenshot not saved. Is this macOS and the Screen Recording permission has not been granted?', file=sys.stderr)
        
        # Continue raising
        raise
