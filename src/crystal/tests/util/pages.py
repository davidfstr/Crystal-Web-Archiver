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
from crystal.tests.util.asserts import assertEqual
from crystal.tests.util.xplaywright import Condition, CountToBeZeroCondition, HasClassCondition, expect, Locator, RawPage


# ------------------------------------------------------------------------------
# Page Abstractions

class AbstractPage:
    def __init__(self, raw_page: RawPage) -> None:
        self.raw_page = raw_page


class NotInArchivePage(AbstractPage):
    @classmethod
    def open(cls, raw_page: RawPage, *, url_in_archive: str) -> 'NotInArchivePage':
        raw_page.goto(url_in_archive)
        return NotInArchivePage.wait_for(raw_page)
    
    @classmethod
    def wait_for(cls, raw_page: RawPage) -> 'NotInArchivePage':
        expect(raw_page).to_have_title('Not in Archive | Crystal')
        return NotInArchivePage(raw_page, _ready=True)
    
    def __init__(self, raw_page: RawPage, _ready: bool=False) -> None:
        assert _ready, 'Did you mean to use NotInArchivePage.open() or .wait_for()?'
        super().__init__(raw_page)
    
    # === URL Information ===
    
    @property
    def download_url_button(self) -> Locator:
        return self.raw_page.locator('#cr-download-url-button')
    
    # === Progress Bar ===
    
    @property
    def progress_bar(self) -> Locator:
        return self.raw_page.locator('#cr-download-progress-bar')
    
    @property
    def progress_bar_message(self) -> str:
        progress_bar_message = self.raw_page.locator('#cr-download-progress-bar__message')
        progress_bar_message_str = progress_bar_message.text_content() or ''
        return progress_bar_message_str
    
    # === Create Group Form ===
    
    @property
    def create_group_checkbox(self) -> Locator:
        return self.raw_page.locator('#cr-create-group-checkbox')
    
    @property
    def create_group_form(self) -> Locator:
        return self.raw_page.locator('#cr-create-group-form')
    
    @property
    def create_group_form_enabled(self) -> Condition:
        disabled_inputs = self.raw_page.locator('#cr-create-group-form input:disabled, #cr-create-group-form select:disabled, #cr-create-group-form button:disabled')
        return CountToBeZeroCondition(disabled_inputs)
    
    @property
    def create_group_form_collapsed(self) -> Condition:
        collapsible_content = self.raw_page.locator('#cr-create-group-form__collapsible-content')
        return HasClassCondition(collapsible_content, 'slide-up')
    
    @property
    def url_pattern_field(self) -> Locator:
        return self.raw_page.locator('#cr-group-url-pattern')
    
    @property
    def source_dropdown(self) -> Locator:
        return self.raw_page.locator('#cr-group-source')
    
    @property
    def name_field(self) -> Locator:
        return self.raw_page.locator('#cr-group-name')
    
    @property
    def preview_urls_container(self) -> Locator:
        return self.raw_page.locator('#cr-preview-urls')
    
    def wait_for_initial_preview_urls(self) -> None:
        first_preview_url = self.preview_urls_container.locator('.cr-list-ctrl-item').first
        first_preview_url.wait_for()
        expect(first_preview_url).not_to_contain_text('Enter a URL pattern to see matching URLs')
        expect(first_preview_url).not_to_contain_text('Loading preview...')
    
    def wait_for_preview_urls_after_url_pattern_changed(self) -> None:
        # NOTE: Currently the same waiting logic will work, but I suspect
        #       different logic may be needed in the future
        self.wait_for_initial_preview_urls()
    
    @property
    def download_immediately_checkbox(self) -> Locator:
        return self.raw_page.locator('#cr-download-immediately-checkbox')
    
    @property
    def cancel_group_button(self) -> Locator:
        return self.raw_page.locator('#cr-cancel-group-button')
    
    @property
    def download_or_create_group_button(self) -> Locator:
        return self.raw_page.locator('#cr-group-action-button')
    
    @property
    def action_message(self) -> Locator:
        """The success/error message displayed in the form actions area."""
        return self.raw_page.locator('.cr-action-message')


# ------------------------------------------------------------------------------
# Utility: Reload

@contextmanager
def reloads_paused(page: RawPage, *, expect_reload: bool=True) -> Iterator[None]:
    """
    Context manager that pauses `window.crReload()` calls during execution,
    then performs the reload after exiting if one was attempted.
    
    It would be ideal to patch `window.location.reload`, but it appears to be
    a read-only property which ignores assignments.
    
    Usage:
        with reloads_paused(page):
            page.some_button.click()  # This might call window.crReload()
            expect(page.some_element).to_be_visible()
        # (If window.crReload() was called above, it happens here)
    """
    page.evaluate('''() => {
        window.crOriginalReload = window.crReload;
        window.crReloadCalled = false;
        window.crReload = function() {
            window.crReloadCalled = true;
        };
    }''')
    try:
        yield
        
        if expect_reload:
            from playwright._impl._errors import TimeoutError as PlaywrightTimeoutError
            try:
                page.wait_for_function('() => window.crReloadCalled')
            except PlaywrightTimeoutError:
                raise AssertionError(
                    'Expected window.crReload() to be called'
                ) from None
    finally:
        reload_was_called = page.evaluate('() => window.crReloadCalled')  # capture
        page.evaluate('''() => {
            if (window.crOriginalReload) {
                window.crReload = window.crOriginalReload;
                delete window.crOriginalReload;
                delete window.crReloadCalled;
            }
        }''')
        
        if reload_was_called:
            page.evaluate('() => window.crReload();')


# ------------------------------------------------------------------------------
# Utility: Network Down

@contextmanager
def network_down_after_delay(page: AbstractPage | RawPage) -> Iterator[None]:
    """
    Mock fetch and EventSource to simulate network failure after delay.
    """
    raw_page = page if isinstance(page, RawPage) else page.raw_page
    
    # Patch window.fetch and EventSource manually, rather than using the
    # route() API, since we need a delayed response without
    # blocking the thread that calls other UI actions.
    raw_page.evaluate("""
        if (window.crOriginalFetch || window.crOriginalEventSource) {
            throw new Error('Cannot nest network_down_after_delay() contexts');
        }
        
        // Patch window.fetch
        window.crOriginalFetch = window.fetch;
        window.fetch = function(url, options) {
            if (url && typeof url === 'string' && (
                url.includes('/_/crystal/download-url') ||
                url.includes('/_/crystal/create-group') ||
                url.includes('/_/crystal/preview-urls')
            )) {
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
        
        // Patch EventSource for the download endpoint
        window.crOriginalEventSource = window.EventSource;
        window.EventSource = function(url, config) {
            // If this is a download URL, throw an error immediately to simulate network failure
            if (url && typeof url === 'string' && url.includes('/_/crystal/download-url')) {
                const fakeEventSource = {
                    onmessage: null,
                    onerror: null,
                    close: function() {},
                };
                
                // Fire an error after 1 second
                setTimeout(() => {
                    if (fakeEventSource.onerror) {
                        const errorEvent = {};
                        fakeEventSource.onerror(errorEvent);
                    }
                }, 1000);
                
                return fakeEventSource;
            }
            // For other URLs, use the original EventSource
            return new window.crOriginalEventSource(url, config);
        };
    """)
    try:
        yield
    finally:
        raw_page.evaluate("""
            window.fetch = window.crOriginalFetch;
            delete window.crOriginalFetch;
            
            window.EventSource = window.crOriginalEventSource;
            delete window.crOriginalEventSource;
        """)


# ------------------------------------------------------------------------------