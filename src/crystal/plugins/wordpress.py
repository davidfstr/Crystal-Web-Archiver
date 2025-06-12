import re

_URL_WITH_REPLYTOCOM = re.compile(r'^(https?://[^?]+)\?replytocom=[0-9]+/?$')

_URL_WITH_POSTTYPE_SLASH = re.compile(r'^(https?://[^?]+\?post_type=[a-zA-Z_]*)((?:/|%2F)*)$')

def normalize_url(old_url: str, **kwargs) -> str:
    # Normalize "reply to comment" links to strip out parameter,
    # which won't be used anyway if page is loaded with JavaScript
    # 
    # Read more about this parameter at:
    # https://www.namehero.com/blog/filtering-out-replytocom-bots-on-wordpress/
    # 
    # https?://__DOMAIN__/...?replytocom=#
    m = _URL_WITH_REPLYTOCOM.fullmatch(old_url)
    if m is not None:
        # Chop off replytocom=... part
        return m.group(1)
    
    # NextGEN Gallery (nggallery):
    # Prevent percent-encode of slash within ?post_type=... segment
    m = _URL_WITH_POSTTYPE_SLASH.fullmatch(old_url)
    if m is not None:
        return m.group(1) + m.group(2).replace('%2F', '/')
    
    return old_url
