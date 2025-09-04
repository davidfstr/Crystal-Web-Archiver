"""
Utilities for controlling a real web browser during automated tests,
using the Playwright library.
"""

# NOTE: Do NOT import from `playwright` library at top-level because it is
#       not available in all environments. Use local imports of it only.
from collections.abc import Awaitable, Callable
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from functools import wraps
from crystal.tests.util.wait import DEFAULT_WAIT_TIMEOUT, wait_for_future
from crystal.util.xos import is_linux
from crystal.tests.util.skip import skipTest
import sys
from typing import Any, TYPE_CHECKING, Protocol


# Importable types: Page
if TYPE_CHECKING:
    from playwright.sync_api import Page
else:
    try:
        from playwright.sync_api import Page
    except ImportError:
        Page = Any


# ------------------------------------------------------------------------------
# Playwright Interface

def awith_playwright(test_func: 'Callable[[Playwright], Awaitable[None]]') -> Callable[[], Awaitable[None]]:
    """Decorates a test function which uses Playwright."""
    @wraps(test_func)
    async def wrapper() -> None:
        # NOTE: May raise SkipTest if Playwright library not available
        pw = Playwright()
        
        await test_func(pw)
    return wrapper


class BlockUsingPlaywright(Protocol):
    # NOTE: The *args and **kwargs allow the signature to be extended in the future
    def __call__(self, page: Page, *args, **kwargs) -> None:
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
        """
        from playwright.sync_api import sync_playwright
        
        # 1. Run all Playwright operations in a background thread to
        #    avoid locking the foreground thread.
        # 2. Run all Playwright operations on a single consistent thread
        #    to comply with Playwright's threading requirements.
        # 
        # TODO: Recommend sharing a single Playwright,
        #       BrowserContext, and Browser instance between multiple
        #       test functions, to reduce setup/teardown overhead.
        with ThreadPoolExecutor(max_workers=1) as executor:
            def run_block() -> None:
                # TODO: Allow browser's headless mode to be controlled by
                #       an environment variable, like CRYSTAL_HEADLESS_BROWSER=False
                with sync_playwright() as p, \
                        closing(p.chromium.launch(headless=True)) as browser, \
                        closing(browser.new_context()) as context:
                    context.set_default_timeout(int(DEFAULT_WAIT_TIMEOUT * 1000))
                    page = context.new_page()
                    
                    block(page)
            block_future = executor.submit(run_block)
            await wait_for_future(block_future, timeout=sys.maxsize)


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
        expect(self._locator).to_be_enabled(timeout=timeout)
    
    def expect_not(self, timeout: float | None = None) -> None:
        expect(self._locator).not_to_be_enabled(timeout=timeout)
    
    def get(self) -> bool:
        return self._locator.is_enabled()


class CountToBeZeroCondition(Condition):
    def __init__(self, locator: Locator) -> None:
        self._locator = locator
    
    def expect(self, timeout: float | None = None) -> None:
        expect(self._locator).to_have_count(0, timeout=timeout)
    
    def expect_not(self, timeout: float | None = None) -> None:
        expect(self._locator).not_to_have_count(0, timeout=timeout)
    
    def get(self) -> bool:
        return self._locator.count == 0


class HasClassCondition(Condition):
    def __init__(self, locator: Locator, class_name: str) -> None:
        self._locator = locator
        self._class_name = class_name
    
    def expect(self, timeout: float | None = None) -> None:
        expect(self._locator).to_have_class(self._class_name, timeout=timeout)
    
    def expect_not(self, timeout: float | None = None) -> None:
        expect(self._locator).not_to_have_class(self._class_name, timeout=timeout)
    
    def get(self) -> bool:
        return self._class_name in (self._locator.get_attribute('class') or '').split(' ')


# ------------------------------------------------------------------------------
