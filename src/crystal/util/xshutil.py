from shutil import (  # type: ignore[attr-defined]  # private API
    _copyfileobj_readinto,
)

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
