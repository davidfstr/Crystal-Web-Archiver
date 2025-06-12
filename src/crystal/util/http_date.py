from crystal.util.xdatetime import datetime_is_aware, datetime_is_in_utc
import datetime

# https://developer.mozilla.org/en-US/docs/Web/HTTP/Headers/Date#syntax
# https://developer.mozilla.org/en-US/docs/Web/HTTP/Headers/If-Modified-Since#syntax
# 
# TODO: Rewrite related code to not assume an en-US locale.
_DATE_HEADER_FORMAT = '%a, %d %b %Y %H:%M:%S GMT'


def parse(date_str: str) -> datetime.datetime:
    """
    Raises:
    * ValueError
    """
    return datetime.datetime.strptime(date_str, _DATE_HEADER_FORMAT)


def format(date: datetime.datetime) -> str:
    assert datetime_is_aware(date)
    assert datetime_is_in_utc(date)
    return date.strftime(_DATE_HEADER_FORMAT)
