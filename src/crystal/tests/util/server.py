from __future__ import annotations

from contextlib import contextmanager
from crystal.server import get_request_url
from crystal.tests.util.runner import bg_fetch_url
from crystal.tests.util.wait import DEFAULT_WAIT_TIMEOUT
from email.message import EmailMessage
import re
from typing import Dict, Iterator, Optional
import unittest.mock


# ------------------------------------------------------------------------------
# Utility: Server

@contextmanager
def assert_does_open_webbrowser_to(request_url: str) -> Iterator[None]:
    with unittest.mock.patch('webbrowser.open', spec=True) as mock_open:
        yield
        mock_open.assert_called_with(request_url)


async def is_url_not_in_archive(archive_url: str) -> bool:
    server_page = await fetch_archive_url(
        archive_url, 
        headers={'X-Crystal-Dynamic': 'False'})
    return server_page.is_not_in_archive


async def fetch_archive_url(
        archive_url: str,
        *, headers: Optional[Dict[str, str]]=None,
        timeout: Optional[float]=None,
        ) -> WebPage:
    if timeout is None:
        timeout = DEFAULT_WAIT_TIMEOUT
    return await bg_fetch_url(get_request_url(archive_url), headers=headers, timeout=timeout)


class WebPage:
    def __init__(self, status: int, headers: EmailMessage, content_bytes: bytes) -> None:
        self._status = status
        self._headers = headers
        self._content_bytes = content_bytes
        self._content = None  # type: Optional[str]
    
    @property
    def is_not_in_archive(self) -> bool:
        return (
            self._status == 404 and
            self.title == 'Not in Archive | Crystal Web Archiver'
        )
    
    @property
    def etag(self) -> Optional[str]:
        return self._headers.get('ETag')
    
    @property
    def title(self) -> Optional[str]:
        # TODO: Use an HTML parser to improve robustness
        m = re.search(r'<title>([^<]*)</title>', self.content)
        if m is None:
            return None
        else:
            return m.group(1).strip()
    
    @property
    def content(self) -> str:  # lazy
        if self._content is None:
            self._content = self._content_bytes.decode('utf-8')
        return self._content
    
    @property
    def content_bytes(self) -> bytes:
        return self._content_bytes


# ------------------------------------------------------------------------------
