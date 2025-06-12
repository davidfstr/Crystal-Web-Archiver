from collections.abc import Callable, Generator
from crystal.download import HTTP_REQUEST_TIMEOUT
from crystal.util.bulkheads import capture_crashes_to_stderr
from crystal.util.test_mode import tests_are_running
from crystal.util.xthreading import (
    bg_affinity, fg_affinity, start_thread_switching_coroutine, SwitchToThread,
)
import os
from typing import Tuple
from urllib.parse import urlparse, urlunparse
from urllib.request import urlopen


class UrlCleaner:
    """
    Given a potentially messy URL typed manually by the user,
    such as from a browser's URL bar, consider candidate URLs
    that the user might have meant, and resolve a single
    cleaned URL.
    """
    
    @fg_affinity
    def __init__(self,
            url_input: str,
            on_running_changed_func: Callable[[bool], None],
            set_cleaned_url_func: Callable[[str], None],
            ) -> None:
        self.url_input = url_input
        self._on_running_changed_func = on_running_changed_func
        self._set_cleaned_url_func = set_cleaned_url_func
        self._cancelled = False
    
    @fg_affinity
    def start(self) -> None:
        url_candidates = _candidate_urls_from_user_input(self.url_input)
        start_thread_switching_coroutine(
            SwitchToThread.FOREGROUND,
            self._run(url_candidates),
            capture_crashes_to_stderr,
        )
    
    @fg_affinity
    def _run(self, url_candidates: list[str]) -> Generator[SwitchToThread, None, None]:
        assert len(url_candidates) >= 1
        
        self._on_running_changed_func(True)
        if len(url_candidates) == 1:
            cleaned_url = url_candidates[0]
            self._finish(cleaned_url)
            return
        
        try:
            yield SwitchToThread.BACKGROUND
            try:
                cleaned_url = _resolve_url_from_candidates(
                    url_candidates, lambda: self._cancelled)
            except _ResolveCanceled:
                yield SwitchToThread.FOREGROUND
                assert self._cancelled
                return
            except:
                # Fallback to first candidate
                cleaned_url = url_candidates[0]
                raise
        finally:
            yield SwitchToThread.FOREGROUND
            if self._cancelled:
                return
            self._finish(cleaned_url)
    
    @fg_affinity
    def _finish(self, cleaned_url: str | None) -> None:
        if cleaned_url is not None:
            self._set_cleaned_url_func(cleaned_url)
        self._on_running_changed_func(False)
    
    # === Operations ===
    
    @fg_affinity
    def cancel(self) -> None:
        self._cancelled = True
        self._finish(None)


def cleaned_url_is_at_site_root(url_input: str) -> bool:
    candidates = _candidate_urls_from_user_input(url_input)
    assert len(candidates) >= 1
    candidate = candidates[0]
    return urlparse(candidate).path == '/'


def _candidate_urls_from_user_input(url_input: str) -> list[str]:
    """
    Given a potentially messy URL typed manually by the user,
    such as from a browser's URL bar, return candidate URLs
    that the user might have meant.
    
    Always at least one candidate is returned.
    
    In the current implementation:
    * If no https:// or http:// prefix is given,
      try first the former then the latter.
    * If additionally no www. domain prefix is given,
      try first without the prefix then with the prefix.
    """
    url_input = url_input.strip()  # remove leading and trailing whitespace
    
    if url_input == '':
        return [url_input]
    
    url_parts = urlparse(url_input)
    if url_parts.scheme in ('', 'https', 'http'):
        # If missing scheme:
        # 1. try https:// then http://
        # 2. try variations on www
        if url_parts.scheme == '':
            scheme_candidates = ('https', 'http')  # type: Tuple[str, ...]
            
            # Reparse (netloc='', path='DOMAIN/PATH')
            #      to (netloc='DOMAIN', path='PATH')
            if url_parts.netloc == '':
                path_parts = url_parts.path.split('/', 1)
                if len(path_parts) == 2:
                    (new_netloc, new_path) = path_parts
                else:
                    assert len(path_parts) == 1
                    (new_netloc, new_path) = (path_parts[0], '')
                url_parts = url_parts._replace(
                    netloc=new_netloc,
                    path=new_path
                )  # reinterpret
            
            # 1. If has www, then try non-www domain if www domain fails
            # 2. If missing www, then try it if non-www domain fails
            if url_parts.netloc.startswith('www.'):
                netloc_candidates = (url_parts.netloc, url_parts.netloc[len('www.'):])  # type: Tuple[str, ...]
            elif url_parts.netloc != '' and not url_parts.netloc.startswith('www.'):
                netloc_candidates = (url_parts.netloc, 'www.' + url_parts.netloc)
            else:
                netloc_candidates = (url_parts.netloc,)
        else:
            scheme_candidates = (url_parts.scheme,)
            netloc_candidates = (url_parts.netloc,)
        
        # If empty path then normalize to /
        if url_parts.path == '':
            path = '/'
        else:
            path = url_parts.path
        
        # Generate URL candidates
        url_candidates = []
        for scheme in scheme_candidates:
            for netloc in netloc_candidates:
                url_candidates.append(urlunparse(url_parts._replace(
                    scheme=scheme,
                    netloc=netloc,
                    path=path,
                    fragment='',
                )))
        
        return url_candidates
    else:
        # Non-HTTP scheme. Accept URL as-is.
        return [url_input]


@bg_affinity
def _resolve_url_from_candidates(
        url_candidates: list[str],
        did_cancel_func: Callable[[], bool]) -> str:
    """
    Given a list of candidate URLs, return the first URL that can be fetched
    successfully.
    
    Raises:
    * _ResolveCanceled
    """
    if len(url_candidates) == 0:
        raise ValueError()
    
    # If only one candidate, return it immediately
    if len(url_candidates) == 1:
        return url_candidates[0]
    
    # Disallow network requests while running tests,
    # unless CRYSTAL_URLOPEN_MOCKED=True
    if tests_are_running():
        if os.environ.get('CRYSTAL_URLOPEN_MOCKED', 'False') == 'True':
            # OK
            pass
        else:
            raise AssertionError(
                'Attempting to resolve URL candidates with real '
                'network requests while automated tests are running. '
                
                'Please either (1) enter URLs with http:// or https:// '
                'schema that does not need to be resolved, or (2) '
                'mock the urlopen() function with something like '
                '_urlopen_responding_with().'
            )
    
    # Look for URL candidate which can be fetched successfully
    for url_candidate in url_candidates:
        if did_cancel_func():
            raise _ResolveCanceled()
        try:
            print(f'Probing URL: {url_candidate}')
            with urlopen(url_candidate, timeout=HTTP_REQUEST_TIMEOUT) as f:
                if (f.getcode() // 100) != 2:  # not HTTP 2xx Success
                    continue
                
                # If redirected to a different candidate, return that candidate
                redirected_url = f.geturl()
                if redirected_url in url_candidates:
                    return redirected_url
                
                # Return this candidate (which might itself be a redirect)
                return url_candidate
        except Exception:
            # One of:
            # 1. Network down
            # 2. Domain does not exist
            # 3. IP did not respond
            # 4. IP refused connection on port that was tried
            continue
    
    # Fallback to first URL candidate (which wasn't fetched successfully)
    return url_candidates[0]


class _ResolveCanceled(Exception):
    pass
