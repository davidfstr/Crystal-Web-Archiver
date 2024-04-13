import re


_URL_WITH_REPLYTOCOM = re.compile(r'^(https?://[^?]+)\?replytocom=[0-9]+/?$')

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
    
    return old_url
