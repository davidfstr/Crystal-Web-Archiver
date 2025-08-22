from collections.abc import Iterable


def is_iterable_empty(i: Iterable) -> bool:
    try:
        next(iter(i))
    except StopIteration:
        return True
    else:
        return False


def is_iterable_len_1(i: Iterable) -> bool:
    j = iter(i)
    try:
        next(j)
    except StopIteration:
        return False
    else:
        try:
            next(j)
        except StopIteration:
            return True
        else:
            return False
