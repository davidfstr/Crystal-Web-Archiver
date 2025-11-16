import functools
import sys
import urllib.parse
from urllib.parse import ParseResult, SplitResult, urlunparse, urlunsplit


def patch_urlparse_to_never_raise_valueerror():
    """
    Patches urllib.parse.urlparse() and also urllib.parse.urlsplit()
    to return a reasonable result in circumstances where the original
    function would raise a ValueError.
    
    Crystal generally assumes that all URLs can be parsed and un-parsed
    without raising. So it's important to avoid raising when parsing a URL.
    
    If urllib.parse.urlparse() returns a result that is not round-tripped
    to the same value after a urllib.parse.urlunparse(), then it will 
    print a warning to stderr.
    """
    if True:
        if sys.version_info >= (3, 14):
            super__urlsplit = urllib.parse._urlsplit  # capture
            
            def _urlsplit(url, scheme=None, allow_fragments=True):
                # NOTE: Crystal uses str URLs only; not bytes URLs.
                if not isinstance(url, str):
                    raise TypeError()
                try:
                    url_parts = super__urlsplit(url, scheme, allow_fragments)
                except ValueError:
                    url_parts = (_scheme := '', _netloc := '', _path := url, _query := '', _fragment := '')
                
                # NOTE: url_parts is what _urlsplit() returns
                (_scheme, _netloc, _path, _query, _fragment) = url_parts
                # NOTE: urlsplit_result is what urlsplit() returns
                urlsplit_result = SplitResult(_scheme or '', _netloc or '', _path, _query, _fragment)
                
                # Check whether SplitResult can be round-tripped back to the original URL
                if scheme is not None:
                    # Can't check round-trip when custom scheme provided
                    pass
                else:
                    url2 = urlunsplit(urlsplit_result)
                    if url2 != url:
                        if url.endswith('#'):
                            # Ignore common case where round-trip doesn't work
                            pass
                        else:
                            print(
                                f'Warning: urlparse/urlsplit returned output that does not '
                                    f'unparse/unsplit to the input: {url!r} -> {url2!r}',
                                file=sys.stderr
                            )
                
                return url_parts
            _urlsplit._super = super__urlsplit
            
            urllib.parse._urlsplit = _urlsplit  # monkeypatch
        else:
            assert sys.version_info >= (3, 11), 'Unsupported version of Python'
            
            super_urlsplit = urllib.parse.urlsplit  # capture
            
            @functools.lru_cache(typed=True)
            def urlsplit(url, scheme='', allow_fragments=True):
                # NOTE: Crystal uses str URLs only; not bytes URLs.
                if not isinstance(url, str):
                    raise TypeError()
                try:
                    url_parts = super_urlsplit(url, scheme, allow_fragments)
                except ValueError:
                    url_parts = SplitResult(scheme='', netloc='', path=url, query='', fragment='')
                
                # Check whether SplitResult can be round-tripped back to the original URL
                if scheme != '':
                    # Can't check round-trip when custom scheme provided
                    pass
                else:
                    url2 = urlunsplit(url_parts)
                    if url2 != url:
                        if url.endswith('#'):
                            # Ignore common case where round-trip doesn't work
                            pass
                        else:
                            print(
                                f'Warning: urlparse/urlsplit returned output that does not '
                                    f'unparse/unsplit to the input: {url!r} -> {url2!r}',
                                file=sys.stderr
                            )
                
                return url_parts
            urlsplit._super = super_urlsplit
            
            urllib.parse.urlsplit = urlsplit  # monkeypatch
    elif False:
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
                # Can't check round-trip when custom scheme provided
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
