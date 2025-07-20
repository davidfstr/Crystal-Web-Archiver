from collections.abc import Iterator
from contextlib import contextmanager
from crystal.util.xos import is_linux
import os
import tzlocal
from unittest.mock import patch
from zoneinfo import ZoneInfo


@contextmanager
def localtime_fallback_for_get_localzone(get_localzone_location: str) -> Iterator[None]:
    """
    Context manager that provides a fallback for tzlocal.get_localzone() to use
    _get_zoneinfo_from_localtime() if get_localzone fails.
    
    Arguments:
    * get_localzone_location -- the import path for get_localzone, e.g. 'tzlocal.get_localzone'
    """
    if not is_linux():
        yield
        return

    real_get_localzone = tzlocal.get_localzone
    def wrapped_get_localzone(*args, **kwargs):
        try:
            return real_get_localzone(*args, **kwargs)
        except tzlocal.utils.ZoneInfoNotFoundError as e:
            msg = str(e)
            if 'Multiple conflicting time zone configurations found' in msg:
                # Fallback to /etc/localtime
                return _get_zoneinfo_from_localtime()
            raise
    with patch(get_localzone_location, wrapped_get_localzone):
        yield


def _get_zoneinfo_from_localtime():
    tz_path = os.path.realpath('/etc/localtime')
    if '/zoneinfo/' not in tz_path:
        raise RuntimeError(f"/etc/localtime does not point to a zoneinfo file: {tz_path}")
    zone_name = tz_path.split('/zoneinfo/', 1)[-1]
    return ZoneInfo(zone_name)
