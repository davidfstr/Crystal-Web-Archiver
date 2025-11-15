from collections.abc import AsyncIterator
from contextlib import asynccontextmanager


# ------------------------------------------------------------------------------
# Specific Features

def proxy_enabled() -> bool:
    return _is_feature_enabled('Proxy')


# ------------------------------------------------------------------------------
# General Features

_enabled_features = set()  # type: set[str]


def set_enabled_features(value: set[str]) -> None:
    global _enabled_features
    if _enabled_features != set():
        raise ValueError('Features already initialized')
    _enabled_features = value


def _is_feature_enabled(feature_name: str) -> bool:
    return feature_name in _enabled_features


@asynccontextmanager
async def feature_enabled(feature_name: str) -> AsyncIterator[None]:
    """
    Context in which the specified feature is temporarily enabled.
    
    Useful while running automated tests.
    
    Example:
        @feature_enabled('Proxy')
        async def test_foo() -> None:
            ...
    """
    was_enabled = feature_name in _enabled_features
    _enabled_features.add(feature_name)
    try:
        yield
    finally:
        if not was_enabled:
            _enabled_features.remove(feature_name)


# ------------------------------------------------------------------------------
