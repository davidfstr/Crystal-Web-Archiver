from crystal.doc.generic import Document, Link
from crystal.doc.html.soup import HtmlDocument, HtmlLink
import json
import re
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

_URL_WITH_TP_IMAGE_ID = re.compile(r'^(https?://[^?]+)\?tp_image_id=[0-9]+$')
_URL_WITH_OM_HIDE = re.compile(r'^(https?://[^?]+)\?omhide=[a-z]+$')

def normalize_url(old_url: str, **kwargs) -> str:
    if not old_url.startswith('https://minimalistbaker.com/'):
        return old_url
    
    # https://minimalistbaker.com/...?tp_image_id=#
    m = _URL_WITH_TP_IMAGE_ID.fullmatch(old_url)
    if m is not None:
        # Chop off tp_image_id=... part
        return m.group(1)
    
    # https://minimalistbaker.com/...?omhide=...
    m = _URL_WITH_OM_HIDE.fullmatch(old_url)
    if m is not None:
        # Chop off omhide=... part
        return m.group(1)
    
    return old_url
    


_FWP_JSON_RE = re.compile(r'''window\.FWP_JSON = ([^\n]+);''')
_FACETWP_PAGE_RE = re.compile(r'''(<a class="[^"]+" data-page="([^"]+)")(>[^<]+</a>)''')

def postprocess_document_and_links(
        url: str,
        doc: Document | None,
        links: list[Link],
        **kwargs,
        ) -> tuple[Document | None, list[Link]]:
    if not url.startswith('https://minimalistbaker.com/'):
        return (doc, links)
    if not isinstance(doc, HtmlDocument):
        return (doc, links)
    # HACK: Uses private API. Recommend making this API public.
    html = doc._html
    
    url_parts = urlparse(url)  # cache
    
    # <script>...window.FWP_JSON = X;...</script>
    for tag in html.find_all('script'):
        tag_string = html.tag_string(tag)
        if tag_string is None:
            continue
        for json_str in _FWP_JSON_RE.findall(tag_string):
            def process_json_match(json_str: str) -> None:
                try:
                    json_obj = json.loads(json_str)
                except ValueError:
                    return
                
                # Normalize the JSON string so that substrings of it can be
                # replaced reliably later
                normalized_json_str = json.dumps(json_obj)
                new_tag_string = tag_string.replace(json_str, normalized_json_str)
                html.set_tag_string(tag, new_tag_string)
                
                old_pager = json_obj.get('preload_data', {}).get('pager')
                if old_pager is None:
                    return
                
                # ex: <a class="facetwp-page active" data-page="2">2</a>
                # ex: <a class="facetwp-page"        data-page="3">3</a>
                for (prefix, ordinal, suffix) in _FACETWP_PAGE_RE.findall(old_pager):
                    def process_page_match(prefix: str, ordinal: str, suffix: str) -> None:
                        old_string_literal = f'{prefix}{suffix}'
                        
                        def replace_url_in_old_attr_value(url: str, old_attr_value: str) -> str:
                            nonlocal old_string_literal
                            new_string_literal = f'{prefix} href={json.dumps(url)}{suffix}'
                            new_attr_value = old_attr_value.replace(
                                _json_escape_str(old_string_literal),
                                _json_escape_str(new_string_literal)
                            )  # capture
                            if new_string_literal != old_string_literal:
                                assert new_attr_value != old_attr_value, (
                                    f'Could not find '
                                    f'{_json_escape_str(old_string_literal)=} '
                                    f'in {old_attr_value=}'
                                )
                            old_string_literal = new_string_literal  # reinterpret
                            return new_attr_value
                        
                        # Create link
                        relative_url = '#'
                        title = ordinal
                        type_title = 'Paginator Reference'
                        embedded = False
                        link = HtmlLink.create_from_complex_tag(
                            tag, html, 'string', type_title, title, embedded,
                            relative_url, replace_url_in_old_attr_value)
                        
                        # Initialize initial link href
                        new_query_parts = dict(parse_qsl(url_parts.query))
                        if ordinal == '1':
                            if 'fwp_paged' in new_query_parts:
                                del new_query_parts['fwp_paged']
                        else:
                            new_query_parts['fwp_paged'] = ordinal
                        new_url_parts = url_parts._replace(
                            scheme='',
                            netloc='',
                            query=urlencode(new_query_parts)
                        )
                        link.relative_url = urlunparse(new_url_parts)
                        
                        links.append(link)  # reinterpret
                    process_page_match(prefix, ordinal, suffix)
            process_json_match(json_str)
    
    # NOTE: `links` was changed in-place by the preceding loop
    return (doc, links)


def _json_escape_str(s: str) -> str:
    return json.dumps(s)[1:-1]
