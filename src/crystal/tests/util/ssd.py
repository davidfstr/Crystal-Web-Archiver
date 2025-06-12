from collections.abc import Iterator
from contextlib import contextmanager
from unittest.mock import patch


@contextmanager
def database_on_ssd(is_ssd: bool) -> Iterator[None]:
    def mock_is_ssd(itempath: str) -> bool:
        return is_ssd
    
    with patch('crystal.util.ssd._is_mac_ssd', mock_is_ssd), \
            patch('crystal.util.ssd._is_linux_ssd', mock_is_ssd), \
            patch('crystal.util.ssd._is_windows_ssd', mock_is_ssd):
        yield
