"""
Abstractions for interacting with browser pages, panels,
and other high-level UI elements.

Automated tests interacting with the UI should use these abstractions
when possible so that they don't need to know about
- exact CSS selectors and IDs (i.e: "cr-...")
- what condition to wait for after performing an action to verify it finished
all of which are subject to change.

See also:
- crystal/tests/util/windows.py -- For interacting with high-level wxPython UI
"""
# NOTE: If you're planning to add an import from the "playwright" package,
#       add an import from the "xplaywright" package instead, so that it
#       can conditionally import symbols correctly when the underlying
#       "playwright" package is not available.
from collections.abc import Iterator
from contextlib import contextmanager
from crystal.tests.util.xplaywright import Locator, RawPage


# ------------------------------------------------------------------------------
# Page Abstractions

class AbstractPage:
    def __init__(self, raw_page: RawPage) -> None:
        self.raw_page = raw_page


class NotInArchivePage(AbstractPage):
    @classmethod
    def open(cls, raw_page: RawPage, *, url_in_archive: str) -> 'NotInArchivePage':
        raw_page.goto(url_in_archive)
        return NotInArchivePage.connect(raw_page)
    
    @classmethod
    def connect(cls, raw_page: RawPage) -> 'NotInArchivePage':
        assert raw_page.title() == 'Not in Archive | Crystal'
        return NotInArchivePage(raw_page, _ready=True)
    
    def __init__(self, raw_page: RawPage, _ready: bool=False) -> None:
        assert _ready, 'Did you mean to use NotInArchivePage.open() or .connect()?'
        super().__init__(raw_page)
    
    @property
    def download_button(self) -> Locator:
        return self.raw_page.locator('#cr-download-url-button')
    
    @property
    def progress_bar(self) -> Locator:
        return self.raw_page.locator('#cr-download-progress-bar')
    
    @property
    def progress_bar_message(self) -> str:
        progress_bar_message = self.raw_page.locator('#cr-download-progress-bar__message')
        progress_bar_message_str = progress_bar_message.text_content() or ''
        return progress_bar_message_str


# ------------------------------------------------------------------------------
# Utility

@contextmanager
def network_down_after_delay(page: AbstractPage | RawPage) -> Iterator[None]:
    """
    Mock fetch to simulate network failure after delay.
    """
    raw_page = page if isinstance(page, RawPage) else page.raw_page
    
    # Patch window.fetch manually, rather than using the
    # route() API, since we need a delayed response without
    # blocking the thread that calls other UI actions.
    raw_page.evaluate("""
        if (window.crOriginalFetch) {
            throw new Error('Cannot nest network_down_after_delay() contexts');
        }
        window.crOriginalFetch = window.fetch;
        window.fetch = function(url, options) {
            if (url && typeof url === 'string' && url.includes('/_/crystal/download-url')) {
                // Return a promise that rejects after 1 second
                return new Promise((resolve, reject) => {
                    setTimeout(() => {
                        reject(new Error('Network connection failed'));
                    }, 1000);
                });
            }
            // For all other requests, use the original fetch
            return window.crOriginalFetch(url, options);
        };
    """)
    try:
        yield
    finally:
        raw_page.evaluate("""
            window.fetch = window.crOriginalFetch;
            delete window.crOriginalFetch;
        """)


# ------------------------------------------------------------------------------