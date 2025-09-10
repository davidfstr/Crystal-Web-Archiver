from typing import Self
from unittest.mock import patch


class FakeClipboard:
    """
    A fake clipboard that captures text without affecting the real system clipboard.
    
    Usage as a context manager:
        with FakeClipboard() as clipboard:
            ...
            assertEqual(clean_url, clipboard.text)
    """
    
    def __init__(self) -> None:
        self._text = ''  # type: str
    
    # === Properties ===
    
    def _set_text(self, text: str) -> None:
        self._text = text
    def _get_text(self) -> str:
        return self._text
    text = property(_get_text, _set_text)
    
    # === Context ===
    
    def __enter__(self) -> Self:
        self._patcher = patch('crystal.util.wx_clipboard.copy_text_to_clipboard', self._set_text)
        self._patcher.start()
        
        return self
    
    def __exit__(self, *args) -> None:
        self._patcher.stop()

