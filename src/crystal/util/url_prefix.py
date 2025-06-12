from urllib.parse import urlparse, urlunparse


def get_url_domain_prefix_for(url_or_url_prefix: str) -> str | None:
    """
    Given a URL or URL prefix, returns the URL for its enclosing domain,
    with no trailing slash.
    """
    url_components = urlparse(url_or_url_prefix)
    if url_components.scheme not in ('http', 'https'):
        return None
    
    return urlunparse(url_components._replace(
        path='',
        params='',
        query='',
        fragment='',
    ))

def get_url_directory_prefix_for(url_or_url_prefix: str) -> str | None:
    """
    Given a URL or URL prefix, returns the URL for its enclosing directory,
    with no trailing slash.
    """
    url_components = urlparse(url_or_url_prefix)
    if url_components.scheme not in ('http', 'https'):
        return None
    
    # If URL path contains slash, chop last slash and everything following it
    path = url_components.path
    if '/' in path:
        new_path = path[:path.rindex('/')]
    else:
        new_path = path
    
    return urlunparse(url_components._replace(path=new_path))
