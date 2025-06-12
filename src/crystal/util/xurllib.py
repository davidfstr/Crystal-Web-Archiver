import sys
import urllib.parse
from urllib.parse import ParseResult, urlunparse


def patch_urlparse_to_never_raise_valueerror():
    super_urlparse = urllib.parse.urlparse  # capture

    def urlparse(url: str, scheme: str='', allow_fragments: bool=True) -> ParseResult:
        """
        Parses a URL in the same way that urllib.parse.urlparse() does,
        but always returns a ParseResult for a str input, never raising an exception.
        
        For more information about why this function exists, see discussion at:
        * https://discuss.python.org/t/urlparse-can-sometimes-raise-an-exception-should-it/44465/3
        """
        if not isinstance(url, str):
            raise TypeError()
        try:
            url_parts = super_urlparse(url, scheme, allow_fragments)
        except ValueError:
            url_parts = ParseResult(scheme='', netloc='', path=url, params='', query='', fragment='')
        
        # Check whether ParseResult can be round-tripped back to the original URL
        if scheme != '':
            # Can't check round-trip when default scheme provided
            pass
        else:
            url2 = urlunparse(url_parts)
            if url2 != url:
                if url.endswith('#'):
                    # Ignore common case where round-trip doesn't work
                    pass
                else:
                    print(
                        f'Warning: urlparse returned output that does not '
                            f'unparse to the input: {url!r} -> {url2!r}',
                        file=sys.stderr
                    )
        
        return url_parts
    urlparse._super = super_urlparse
    
    urllib.parse.urlparse = urlparse  # monkeypatch
