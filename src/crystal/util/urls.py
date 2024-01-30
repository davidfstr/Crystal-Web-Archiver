from urllib.parse import quote


# Adapted from requote_uri() @ requests/utils.py
def requote_uri(uri):
    # type: (str) -> str
    """
    Re-quote the given URI.

    This function passes the given URI through an unquote/quote cycle to
    ensure that it is fully and consistently quoted.
    """
    safe_with_percent = "!#$%&'()*+,/:;=?@[]~"
    safe_without_percent = "!#$&'()*+,/:;=?@[]~"
    try:
        # Unquote only the unreserved characters
        # Then quote only illegal characters (do not quote reserved,
        # unreserved, or '%')
        return quote(_unquote_unreserved(uri), safe=safe_with_percent)
    except _InvalidURL:
        # We couldn't unquote the given URI, so let's try quoting it, but
        # there may be unquoted '%'s in the URI. We need to make sure they're
        # properly quoted so they do not cause issues elsewhere.
        return quote(uri, safe=safe_without_percent)


# The unreserved URI characters (RFC 3986)
_UNRESERVED_SET = frozenset(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz" + "0123456789-._~")

# Adapted from unquote_unreserved() @ requests/utils.py
def _unquote_unreserved(uri):
    # type: (str) -> str
    """
    Un-escape any percent-escape sequences in a URI that are unreserved
    characters. This leaves all reserved, illegal and non-ASCII bytes encoded.
    """
    parts = uri.split('%')
    for i in range(1, len(parts)):
        h = parts[i][0:2]
        if len(h) == 2 and h.isalnum():
            try:
                c = chr(int(h, 16))
            except ValueError:
                raise _InvalidURL("Invalid percent-escape sequence: '%s'" % h)

            if c in _UNRESERVED_SET:
                parts[i] = c + parts[i][2:]
            else:
                parts[i] = '%' + parts[i]
        else:
            parts[i] = '%' + parts[i]
    return ''.join(parts)


class _InvalidURL(ValueError):
    """The URL provided was somehow invalid."""


def is_unrewritable_url(relative_url: str) -> bool:
    # Don't rewrite certain schemes
    for prefix in ('mailto:', 'javascript:', 'data:'):
        if relative_url.startswith(prefix):
            return True
    
    # Otherwise OK to rewrite
    return False
