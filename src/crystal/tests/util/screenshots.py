from contextlib import contextmanager
import os
import pyscreeze
from typing import Iterator


@contextmanager
def screenshot_if_raises() -> Iterator[None]:
    try:
        yield
    except:
        # Take screenshot if screenshots directory path defined
        screenshots_dirpath = os.environ.get('CRYSTAL_SCREENSHOTS_DIRPATH')
        if screenshots_dirpath is not None:
            os.makedirs(screenshots_dirpath, exist_ok=True)
            
            screenshot_filename = os.environ.get('CRYSTAL_SCREENSHOT_ID', 'screenshot') + '.png'
            screenshot_filepath = os.path.join(screenshots_dirpath, screenshot_filename)
            print('*** Saving screenshot to: ' + os.path.abspath(screenshot_filepath))
            pyscreeze.screenshot(screenshot_filepath)
        
        raise