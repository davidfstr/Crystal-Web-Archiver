from base64 import urlsafe_b64decode, urlsafe_b64encode
from crystal.plugins.util.params import try_get_int, try_get_str
import json
import sys
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse


def normalize_url(old_url: str, **kwargs) -> str:
    old_url_parts = urlparse(old_url)
    if old_url_parts.scheme in ('http', 'https'):
        # https?://__DOMAIN__/api/v1/firehose?_=...&d=...
        if old_url_parts.path == '/api/v1/firehose':
            params = parse_qs(old_url_parts.query)
            t = try_get_int(params, '_')
            d = try_get_str(params, 'd')
            if t is not None and d is not None:
                try:
                    d_obj = json.loads(urlsafe_b64decode(d))  # type: ignore[attr-defined]
                except ValueError:
                    print('*** Substack: Unable to decode "d" argument: ' + d, file=sys.stderr)
                else:
                    if isinstance(d_obj, dict):
                        # Pin $.properties.browserSessionId to fixed arbitrary valid value
                        properties = d_obj.get('properties', {})
                        browserSessionId = properties.get('browserSessionId', None)
                        if isinstance(browserSessionId, str):
                            browserSessionId = '1xh68gok0s4'  # reinterpret
                            properties['browserSessionId'] = browserSessionId  # reinterpret
                        
                        # Pin $.context.page.referrer to '' (which usually is already the case)
                        context = d_obj.get('context', {})
                        page = context.get('page', {})
                        referrer = page.get('referrer', None)
                        if isinstance(referrer, str):
                            referrer = ''  # reinterpret
                            page['referrer'] = referrer  # reinterpret
                        
                        # Alter $.context.page.url so that its domain matches that of old_url
                        url = page.get('url', None)
                        if isinstance(url, str):
                            url_parts = urlparse(url)
                            url = urlunparse(url_parts._replace(
                                scheme=old_url_parts.scheme,
                                netloc=old_url_parts.netloc,
                            ))  # reinterpret
                            page['url'] = url  # reinterpret
                        
                        new_d = urlsafe_b64encode(
                            json.dumps(d_obj).encode('utf-8')  # type: ignore[attr-defined]
                        ).decode('utf-8')
                        
                        new_params = dict(_=t, d=new_d)
                        new_query = urlencode(new_params)
                        return urlunparse(old_url_parts._replace(query=new_query))
    
    return old_url
