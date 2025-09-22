"""
Utilities for controlling a real web browser during automated tests,
using the Playwright library.
"""

# NOTE: Do NOT import from `playwright` library at top-level because it is
#       not available in all environments. Use local imports of it only.
from collections.abc import Awaitable, Callable
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from contextlib import closing
from functools import wraps
from subprocess import SubprocessError
from textwrap import dedent
from crystal.tests.util.wait import DEFAULT_WAIT_TIMEOUT, GLOBAL_TIMEOUT_MULTIPLIER, wait_for_future
from crystal.util.xos import is_asan, is_linux
from crystal.tests.util.skip import skipTest
import os
import site
import subprocess
import sys
from typing import Any, TYPE_CHECKING, Concatenate, ParamSpec, Protocol


# Importable Playright types
# 
# These types are designed to be imported by tests without those tests
# worrying about whether the underlying "playwright" package is available or not.
if TYPE_CHECKING:
    from playwright.sync_api import Locator, Page as RawPage, expect
else:
    try:
        from playwright.sync_api import Locator, Page as RawPage, expect
    except ImportError:
        Locator = Any
        RawPage = Any
        expect = lambda *args, **kwargs: None


# ------------------------------------------------------------------------------
# Playwright Interface

_P = ParamSpec('_P')

def awith_playwright(
        test_func: 'Callable[Concatenate[Playwright, _P], Awaitable[None]]'
        ) -> Callable[_P, Awaitable[None]]:
    """Decorates a test function which uses Playwright."""
    @wraps(test_func)
    async def wrapper(*args: _P.args, **kwargs: _P.kwargs) -> None:
        # NOTE: May raise SkipTest if Playwright library not available
        pw = Playwright()
        
        await test_func(pw, *args, **kwargs)
    return wrapper


class BlockUsingPlaywright(Protocol):
    # NOTE: The *args and **kwargs allow the signature to be extended in the future
    def __call__(self, raw_page: RawPage, *args, **kwargs) -> None:
        ...


class Playwright:
    def __init__(self) -> None:
        """
        Raises:
        * SkipTest -- If Playwright is not available in this environment.
        """
        # 1. Skip Playwright test when Crystal is bundled
        # 2. Ensure Crystal is NOT bundled on at least one platform (Linux),
        #    so that Playwright tests will run on at least 1 CI job
        if is_linux():
            assert not hasattr(sys, 'frozen')
        else:
            if hasattr(sys, 'frozen'):
                skipTest('Playwright not available in bundled app')
    
    async def run(self, block: BlockUsingPlaywright) -> None:
        """
        Runs the specified block of code in a context where a web browser
        can be controlled with the Playwright library.
        
        The block must be serializable using the "dill" library.
        
        This runs Playwright + greenlet in a separate process because they
        can trigger segfaults when combined with wxPython's event loop.
        
        Set environment variable CRYSTAL_HEADLESS_BROWSER=False if you
        want to see what the browser is doing.
        """
        import dill
        
        # Serialize the block function using dill,
        # so that a local function closure can be provided
        try:
            serialized_block = dill.dumps(block)
        except (TypeError, AttributeError) as e:
            # If serialization fails, provide a helpful error message
            if 'KeyedRef' in str(e) or 'cannot pickle' in str(e):
                raise RuntimeError(
                    f'Cannot serialize Playwright block function due to unpicklable objects '
                    f'(likely ProjectServer, Project, or wxPython objects) in the closure. '
                    f'To fix this, extract any data you need from unpicklable objects '
                    f'before defining the Playwright block function. '
                    f'Original error: {e}'
                ) from e
            else:
                raise
        
        # 1. Run Playwright in a separate process using ProcessPoolExecutor (or equivalent)
        # 2. Use wait_for_future to avoid blocking the foreground thread,
        #    so that it can still run operations like serving HTTP requests
        if is_asan():
            # Playwright's sync API uses greenlet, and greenlet is incompatible with ASAN
            # (see: https://github.com/python-greenlet/greenlet/issues/367), so
            # run Playwright + greenlet using a non-ASAN Python
            await _run_block_with_playwright_using_custom_python(
                serialized_block,
                os.environ['CRYSTAL_NONASAN_PYTHON_PATH'],  # required for ASAN builds
            )
        else:
            await _run_block_with_playwright_using_this_python(
                serialized_block
            )


async def _run_block_with_playwright_using_this_python(serialized_block: bytes) -> None:
    with ProcessPoolExecutor(max_workers=1) as executor:
        future = executor.submit(_run_block_with_playwright, serialized_block)
        await wait_for_future(future, timeout=sys.maxsize)


async def _run_block_with_playwright_using_custom_python(
        serialized_block: bytes,
        python_executable: str,
        ) -> None:
    """
    Runs Playwright in a subprocess using a custom Python executable.
    """
    # Compute new PYTHONPATH
    (site_packages_dirpath, *_) = site.getsitepackages()
    crystal_dirpath = os.path.abspath(os.path.join(
        os.path.dirname(__file__), '..', '..', '..'))
    assert os.path.exists(os.path.join(crystal_dirpath, 'crystal'))
    new_pythonpath = os.pathsep.join(
        [
            # Include current Python's site-packages
            site_packages_dirpath,
            # Include Crystal's source directory (for the "crystal" module)
            crystal_dirpath
        ] + 
        # Include old PYTHONPATH
        os.environ.get('PYTHONPATH', '').split(os.pathsep)
    )
    
    # Start Playwright in subprocess
    process = subprocess.Popen(
        [python_executable, '-c', dedent(
            '''
            from crystal.tests.util.xplaywright import _run_block_with_playwright
            import sys

            serialized_block = sys.stdin.buffer.read()
            _run_block_with_playwright(serialized_block)
            '''
        )],
        stdin=subprocess.PIPE,
        stdout=None,  # passthru
        stderr=None,  # passthru
        env={
            **os.environ,
            **{
                'PYTHONPATH': new_pythonpath,
            }
        }
    )
    
    # Run subprocess in background thread to avoid blocking the foreground thread
    with ThreadPoolExecutor(max_workers=1) as executor:
        def run_and_wait() -> None:
            process.communicate(input=serialized_block)
            if process.returncode != 0:
                raise SubprocessError(
                    f'Playwright subprocess failed with code {process.returncode}'
                )
        future = executor.submit(run_and_wait)
        await wait_for_future(future, timeout=sys.maxsize)


def _run_block_with_playwright(serialized_block: bytes) -> None:
    """
    Runs a (serialized) block with Playwright.
    
    This function is designed to be called in a subprocess.
    """
    import dill
    from playwright.sync_api import sync_playwright
    
    # Deserialize the block function
    block = dill.loads(serialized_block)
    
    # TODO: Recommend sharing a single Playwright,
    #       BrowserContext, and Browser instance between multiple
    #       test functions, to reduce setup/teardown overhead.
    headless = os.environ.get('CRYSTAL_HEADLESS_BROWSER', 'True') == 'True'
    with sync_playwright() as p, \
            closing(p.chromium.launch(headless=headless)) as browser, \
            closing(browser.new_context()) as context:
        context.set_default_timeout(int(DEFAULT_WAIT_TIMEOUT * 1000) * GLOBAL_TIMEOUT_MULTIPLIER)
        page = context.new_page()
        page.on('pageerror', lambda e: print(f'*** Uncaught JavaScript exception: {e}', file=sys.stderr))
        
        block(page)


# ------------------------------------------------------------------------------
# Condition

class Condition:  # abstract
    def expect(self, timeout: float | None = None) -> None:  # abstract
        raise NotImplementedError()
    
    def expect_not(self, timeout: float | None = None) -> None:  # abstract
        raise NotImplementedError()
    
    def get(self) -> bool:  # abstract
        raise NotImplementedError()


class EnabledCondition(Condition):
    def __init__(self, locator: Locator) -> None:
        self._locator = locator
    
    def expect(self, timeout: float | None = None) -> None:
        expect(self._locator).to_be_enabled(timeout=scale_timeout(timeout))
    
    def expect_not(self, timeout: float | None = None) -> None:
        expect(self._locator).not_to_be_enabled(timeout=scale_timeout(timeout))
    
    def get(self) -> bool:
        return self._locator.is_enabled()


class CountToBeZeroCondition(Condition):
    def __init__(self, locator: Locator) -> None:
        self._locator = locator
    
    def expect(self, timeout: float | None = None) -> None:
        expect(self._locator).to_have_count(0, timeout=scale_timeout(timeout))
    
    def expect_not(self, timeout: float | None = None) -> None:
        expect(self._locator).not_to_have_count(0, timeout=scale_timeout(timeout))
    
    def get(self) -> bool:
        return self._locator.count == 0


class HasClassCondition(Condition):
    def __init__(self, locator: Locator, class_name: str) -> None:
        self._locator = locator
        self._class_name = class_name
    
    def expect(self, timeout: float | None = None) -> None:
        expect(self._locator).to_have_class(self._class_name, timeout=scale_timeout(timeout))
    
    def expect_not(self, timeout: float | None = None) -> None:
        expect(self._locator).not_to_have_class(self._class_name, timeout=scale_timeout(timeout))
    
    def get(self) -> bool:
        return self._class_name in (self._locator.get_attribute('class') or '').split(' ')


# ------------------------------------------------------------------------------
# Utility

def scale_timeout(timeout: float | None) -> float | None:
    if timeout is None:
        return timeout
    else:
        return timeout * GLOBAL_TIMEOUT_MULTIPLIER


# ------------------------------------------------------------------------------
