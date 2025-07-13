"""
Extensions to the standard library shutil module.
"""

from collections.abc import Iterator
import os
from shutil import (  # type: ignore[attr-defined]  # private API
    _copyfileobj_readinto,
)
from typing import TYPE_CHECKING, Literal


copyfileobj_readinto = _copyfileobj_readinto
copyfileobj_readinto.__doc__ = (
    """
    Copy data from file-like object `fsrc` to file-like object `fdst`.
    
    `fsrc` must support the readinto() method and both files must be
    open in binary mode.
    
    This method is slightly more efficient than shutil.copyfileobj
    (from Python 3.9 - 3.11.4) because it reuses a single internal buffer.
    Details here: https://discuss.python.org/t/making-shutil-copyfileobj-faster/31550/8?u=davidfstr
    """
)


def walkzip(
        src_top_dirpath: str,
        dst_top_dirpath: str,
        *, topdown: Literal[True]=True,
        ) -> Iterator[tuple[str, str, list[str], list[str]]]:
    """
    A generator that yields tuples of (src_dirpath, dst_dirpath, dirnames, filenames)
    similar to os.walk().
    """
    assert topdown == True, 'Only topdown=True is supported'
    
    # Ensure top dirpaths do not end with a separator
    src_top_dirpath = os.path.abspath(src_top_dirpath)
    dst_top_dirpath = os.path.abspath(dst_top_dirpath)
    if src_top_dirpath == os.path.sep or dst_top_dirpath == os.path.sep:
        # NOTE: Supporting walking the root directory would require
        #       more complex relative path handling
        raise NotImplementedError('Cannot walk root directory')
    assert not src_top_dirpath.endswith(os.path.sep)
    assert not dst_top_dirpath.endswith(os.path.sep)
    
    for (src_parent_dirpath, dirnames, filenames) in os.walk(src_top_dirpath, topdown=topdown):
        # NOTE: Equivalent to os.path.relpath(src_dirpath, src_top_dirpath)
        #       but avoids a slower call to os.path.relpath()
        parent_rel_dirpath = src_parent_dirpath[len(src_top_dirpath) + 1:]
        dst_parent_dirpath = os.path.join(dst_top_dirpath, parent_rel_dirpath)
        yield (src_parent_dirpath, dst_parent_dirpath, dirnames, filenames)
