from collections.abc import Callable, Iterable
from typing import ParamSpec, TypeVar


_P = ParamSpec('_P')
_R = TypeVar('_R')


class CloakMixin:
    """
    Mixin whose dir() excludes any functions marked with @cloak,
    and any attributes named in __cloak__
    """
    def __dir__(self) -> Iterable[str]:
        extra_cloaked_names = getattr(self, '__cloak__', ())  # type: Iterable[str]
        return [
            n for n in super().__dir__()
            if not (hasattr(getattr(type(self), n, None), '_cloaked') or n in extra_cloaked_names)
        ]


def cloak(func: Callable[_P, _R]) -> Callable[_P, _R]:
    """
    Marks a function to not appear in the dir() of its class.
    
    Useful to keep functions out of a class's public API.
    """
    func._cloaked = True  # type: ignore[attr-defined]
    return func