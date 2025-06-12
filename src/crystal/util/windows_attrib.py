from crystal.util.xos import is_windows
import subprocess
from typing import Literal


def set_windows_file_attrib(itempath: str, attribs: list[Literal['+h', '+s']]) -> None:
    assert is_windows()
    subprocess.check_call(
        ['attrib', *attribs, itempath],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=subprocess.CREATE_NO_WINDOW)  # type: ignore[attr-defined]
