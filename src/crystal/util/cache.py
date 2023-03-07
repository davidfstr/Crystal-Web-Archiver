try:
    # Python 3.9+
    from functools import cache  # type: ignore[attr-defined]
except ImportError:
    # Python 3.8
    from functools import lru_cache
    cache = lambda func: lru_cache(maxsize=None)(func)
