from crystal.plugins.util.params import try_get_int, try_get_str
import re
import sys
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

_FORUM_PAGE_ITEM_COUNT = 25
_TOPIC_PAGE_ITEM_COUNT = 20

_PHP_URL_WITH_SID = re.compile(r'^(https?://[^/]+/[^/]+\.php(?=\?).*)[?&]sid=[0-9a-f]{32}$')


def normalize_url(old_url: str, **kwargs) -> str:
    url_parts = urlparse(old_url)
    if url_parts.scheme in ('http', 'https'):
        # https?://__DOMAIN__/viewforum.php?f=#&start=#&...
        if url_parts.path == '/viewforum.php':
            params = parse_qs(url_parts.query)
            f = try_get_int(params, 'f')
            start = try_get_int(params, 'start')
            if start is not None and start % _FORUM_PAGE_ITEM_COUNT != 0:
                print('*** Rounding down forum page start for: ' + old_url, file=sys.stderr)
                start -= (start % _FORUM_PAGE_ITEM_COUNT)  # round down
            
            if f is not None:
                new_params = dict(f=f)
                if start is not None and start != 0:
                    new_params['start'] = start
                new_query = urlencode(new_params)
                return urlunparse(url_parts._replace(query=new_query))
        
        # 1. https?://__DOMAIN__/viewforum.php?t=#&start=#&...
        # 2. https?://__DOMAIN__/viewforum.php?p=#&start=#&...
        elif url_parts.path == '/viewtopic.php':
            params = parse_qs(url_parts.query)
            t = try_get_int(params, 't')
            p = try_get_int(params, 'p')
            start = try_get_int(params, 'start')
            if start is not None and start % _TOPIC_PAGE_ITEM_COUNT != 0:
                print('*** Rounding down topic page start for: ' + old_url, file=sys.stderr)
                start -= (start % _TOPIC_PAGE_ITEM_COUNT)  # round down
            
            if t is not None or p is not None:
                new_params = {}
                if t is not None:
                    new_params['t'] = t
                else:
                    assert p is not None
                    new_params['p'] = p
                if start is not None and start != 0:
                    new_params['start'] = start
                new_query = urlencode(new_params)
                return urlunparse(url_parts._replace(query=new_query))
        
        # 1. https?://__DOMAIN__/memberlist.php?mode=viewprofile&u=#&...
        # 2. https?://__DOMAIN__/memberlist.php?mode=group&g=#&...
        elif url_parts.path == '/memberlist.php':
            params = parse_qs(url_parts.query)
            mode = try_get_str(params, 'mode')
            if mode == 'viewprofile':
                u = try_get_int(params, 'u')
                if u is not None:
                    new_query = urlencode(dict(mode=mode, u=u))
                    return urlunparse(url_parts._replace(query=new_query))
            elif mode == 'group':
                g = try_get_int(params, 'g')
                if g is not None:
                    new_query = urlencode(dict(mode=mode, g=g))
                    return urlunparse(url_parts._replace(query=new_query))
        
        # https?://__DOMAIN__/__SCRIPT__.php?**&sid=*
        m = _PHP_URL_WITH_SID.fullmatch(old_url)
        if m is not None:
            # Chop off sid=... part
            return m.group(1)
    
    return old_url
