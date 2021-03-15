"""
Parses HTML documents.
"""

def parse_links(html_bytes, declared_charset=None):
    """
    Parses the specified HTML bytestring, returning a list of links.
    
    Arguments:
    html_bytes -- HTML bytestring or file object.
    declared_charset -- the encoding that the HTML document is declared to be in.
    """
    (html, links) = parse_html_and_links(html_bytes, declared_charset)
    return links


def parse_html_and_links(html_bytes, declared_charset=None):
    """
    Parses the specified HTML bytestring, returning a 2-tuple containing
    (1) the HTML document and
    (2) a list of mutable links.
    
    The HTML document can be reoutput by getting its str() representation.
    
    Each link has the following mutable properties:
    * relative_url : str -- URL or URI referenced by this link, often relative.
    * type_title : str -- displayed title for this link's type.
    * title : str -- displayed title for this link, or None.
    * embedded : bool -- whether this link refers to an embedded resource.
    
    This parse method should be used instead of parse_links() when the parsed
    links need to be modified and the document reoutput.
    
    Arguments:
    html_bytes -- HTML bytestring or file object.
    declared_charset -- the encoding that the HTML document is declared to be in.
    """    
    import crystal.html.basic as basic
    import crystal.html.soup as soup
    
    # Convert html_bytes to string
    if hasattr(html_bytes, 'read'):
        html_bytes = html_bytes.read()
    
    # HACK: The BeautifulSoup parser doesn't currently handle <frameset>
    #       tags correctly. So workaround with a basic parser.
    if (b'frameset' in html_bytes) or (b'FRAMESET' in html_bytes):
        return basic.parse_html_and_links(html_bytes, declared_charset)
    else:
        return soup.parse_html_and_links(html_bytes, declared_charset)


def create_external_link(relative_url, type_title, title, embedded):
    import crystal.html.soup as soup
    
    return soup.Link.create_external(relative_url, type_title, title, embedded)