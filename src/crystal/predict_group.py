from collections.abc import Iterator
from dataclasses import dataclass
from crystal.model import Project, Resource, ResourceGroup, ResourceGroupSource, RootResource
from crystal.util.xthreading import bg_affinity, fg_call_and_wait
import re
from urllib.parse import urljoin
from typing import assert_never


# Detects groups that have at minimum this many members.
# 
# Tuning guide:
# - Must be >=2 to avoid strange algorithm behavior.
# - Lower values may cause detected groups to have overly narrow URL patterns.
# - Higher values may cause group prediction to take longer because
#   additional resources may need to be downloaded to ensure a proposed
#   group has this minimum number of members.
# 
# TODO: Tune this value. >=8, <16 is probably also safe.
_MIN_GROUP_SIZE = 3


# ------------------------------------------------------------------------------
# Detect Regular Group

@dataclass(frozen=True)
class DetectedRegularGroup:
    source: ResourceGroupSource
    url_pattern: str


def detect_regular_group(
        project: Project,
        current_url: str,
        referrer_url: str | None
        ) -> DetectedRegularGroup | None:
    """
    Guesses the best URL pattern and source for a new resource group
    that would include the current URL being visited.
    """
    best_source = _detect_narrowest_existing_group_given_member_url(
        project, referrer_url)
    if best_source is None:
        return None
    best_url_pattern = _detect_new_group_given_member_url_and_source(
        current_url,
        best_source,
    )
    if best_url_pattern is None:
        return None
    return DetectedRegularGroup(best_source, best_url_pattern)


@bg_affinity
def _detect_narrowest_existing_group_given_member_url(
        project: Project,
        referrer_url: str | None,
        ) -> ResourceGroupSource:
    """
    Identifies the narrowest preexisting RootResource or ResourceGroup matching
    the specified referrer.
    """
    if referrer_url is None:
        return None
    
    # Check whether a RootResource matches the referrer URL
    referrer_url_not_none = referrer_url  # capture
    referrer_resource = fg_call_and_wait(lambda: project.get_resource(referrer_url_not_none))
    if referrer_resource is not None:
        rr = project.get_root_resource(referrer_resource)
        if rr is not None:
            return rr
    
    # Check whether any ResourceGroups match the referrer URL
    matching_groups = [
        rg for rg in project.resource_groups
        if rg.contains_url(referrer_url)
    ]
    if len(matching_groups) > 0:
        # Pick the group with the most-specific pattern, matching the fewest URLs
        def genericity_for_url_pattern(url_pattern: str) -> tuple[object, ...]:
            (url_pattern, star_star_count) = re.subn(r'\*\*', '', url_pattern)
            (url_pattern, star_count) = re.subn(r'\*', '', url_pattern)
            (url_pattern, digits_or_alphas_count) = re.subn(r'[#@]', '', url_pattern)
            non_wildcard_count = len(url_pattern)
            return (
                star_star_count,  # higher is more generic
                star_count,  # higher is more generic
                digits_or_alphas_count,  # higher is more generic
                -non_wildcard_count,  # higher is LESS generic
                url_pattern,  # tie-breaker, for determinism
            )
        group_with_most_specific_pattern = min(
            matching_groups,
            key=lambda rg: genericity_for_url_pattern(rg.url_pattern)
        )
        return group_with_most_specific_pattern
    
    # Otherwise return no source
    return None


@bg_affinity
def _detect_new_group_given_member_url_and_source(
        current_url: str,
        best_source: RootResource | ResourceGroup,
        ) -> str | None:
    """
    Guesses the URL pattern of a new group matching the current URL,
    given the current URL and its guessed source.
    
    If the guessed source is in fact the source of the current URL
    (as opposed to being a non-source that happens to link to the current URL)
    then this method will identify the narrowest URL pattern which matches the
    current URL and results in a group with >= _MIN_GROUP_SIZE members.
    
    If no such URL pattern can be found then None will be returned.
    In that case it is unlikely that the guessed source is a true source
    for the current URL, or the source is linking to group members using
    dynamic links rather than static links.
    """
    # HACK: Import locally so that Task._USE_EXTRA_LISTENER_ASSERTIONS_ALWAYS
    #       doesn't capture the wrong value
    from crystal.task import CannotDownloadWhenProjectReadOnlyError, TaskDisposedException
    
    if isinstance(best_source, RootResource):
        source_rs = [best_source.resource]
    elif isinstance(best_source, ResourceGroup):
        best_source_g = best_source  # capture
        source_rs = fg_call_and_wait(lambda: 
            list(best_source_g.members[:_MIN_GROUP_SIZE]))
    else:
        assert_never(best_source)
    
    # Collect outgoing links from >= _MIN_GROUP_SIZE members of the source
    # 
    # Assuming each source member links to >=1 member of the current URL's group
    # then we should collect >= _MIN_GROUP_SIZE links to the current URL's group.
    # 
    # As a special case: A single (unique) source member may link to ALL
    # members of the current URL's group.
    linked_urls = []  # type: list[str]
    for source_r in source_rs:
        # Read/download the latest revision of the source resource
        # TODO: Start all Futures concurrently
        # TODO: Timeout?
        # TODO: Error handling?
        revision_future = source_r.download_body(interactive=True)
        try:
            revision = revision_future.result()
        except CannotDownloadWhenProjectReadOnlyError:
            # TODO: Implement better error handling.
            #       If must skip a resource from a group then an extra member
            #       from the group should be consulted.
            continue
        # HACK: Situation can happen if running within a Playwright.run() block,
        #       probably because its subprocess isn't receiving the full state
        #       from its parent process.
        except TaskDisposedException:
            # HACK: Clear any cached DownloadResourceBodyTask
            source_r._download_body_task_ref = None
            
            # Try again
            revision_future = source_r.download_body(interactive=True)
            revision = revision_future.result()
        
        # Parse links from source resource's latest revision
        source_r_url = source_r.url  # cache
        linked_urls.extend([
            urljoin(source_r_url, link.relative_url)
            for link in revision.links()
        ])
    # 1. If the particular member linking to the current_url wasn't consulted,
    #    record the current_url as a known link originating from the source anyway
    # 2. If current_url wasn't detected as a static link, add it as a dynamic link
    if current_url not in linked_urls:
        linked_urls.append(current_url)
    # 1. Deduplicate the linked URLs for accurate URL counting
    # 2. Sort the linked URLs for easier debugging
    linked_urls = sorted(set(linked_urls))
    
    # Split current URL into dimensions
    # ex: [
    #     ('https://', 'www.artima.com'), ('/', 'weblogs'),
    #     ('/', 'index.jsp'),
    #     ('?blogger=', 'guido'), ('&start=', '0'), ('&thRange=', '15')
    # ]
    current_url_dims = _split_url_by_dimension(current_url)  # cache
    
    # Retain only those linked URLs which:
    # - have the same number and type of dimensions as the current URL
    # - have the same domain (i.e. the first dimension)
    # - both look like files or both look like directories
    linked_urls_as_dims = [_split_url_by_dimension(url) for url in linked_urls]
    linked_urls_as_dims = [
        url_dims
        for url_dims in linked_urls_as_dims
        if (
            _dims_match(url_dims, current_url_dims) and
            url_dims[0] == current_url_dims[0] and
            (url_dims[-1].value == '') == (current_url_dims[-1].value == '')
        )
    ]
    
    # No URL pattern exists that will match a large enough group
    # of the source's linked URLs
    if len(linked_urls_as_dims) < _MIN_GROUP_SIZE:
        return None
    
    url_pattern_dims = list(current_url_dims)  # clone
    for (i, pattern_dim) in enumerate(url_pattern_dims):
        # Try to use an exact match on the current dimension
        filtered_urls_as_dims = [
            url_dims
            for url_dims in linked_urls_as_dims
            if url_dims[i].value == pattern_dim.value
        ]
        if len(filtered_urls_as_dims) >= _MIN_GROUP_SIZE:
            # Success
            url_pattern_dims[i] = _replace_dim_value(
                url_pattern_dims[i], pattern_dim.value)
            linked_urls_as_dims = filtered_urls_as_dims  # reinterpret
            continue
        
        # Try to use a # wildcard on the current dimension
        if re.fullmatch(r'[0-9]+', pattern_dim.value):
            filtered_urls_as_dims = [
                url_dims
                for url_dims in linked_urls_as_dims
                if re.fullmatch(r'[0-9]+', url_dims[i].value)
            ]
            if len(filtered_urls_as_dims) >= _MIN_GROUP_SIZE:
                # Success
                url_pattern_dims[i] = _replace_dim_value(
                    url_pattern_dims[i], '#')
                linked_urls_as_dims = filtered_urls_as_dims  # reinterpret
                continue
        
        # (Do NOT try to use a @ wildcard on the current dimension,
        #  since any case where a @ would match is more likely to actually
        #  want the broader * wildcard.)
        
        # Fallback to a * wildcard on the current dimension
        url_pattern_dims[i] = _replace_dim_value(
            url_pattern_dims[i], '*')
        continue
    
    return _join_url_by_dimension(url_pattern_dims)


# ------------------------------------------------------------------------------
# Detect Sequential Group

@dataclass(frozen=True)
class DetectedSequentialGroup:
    source: ResourceGroupSource
    url_pattern: str
    
    page_ordinal_dimension_index: int
    first_page_ordinal: int  # usually 1 or 2; always 1 for now
    last_page_ordinal: int | None  # None if unknown


@dataclass(frozen=True)
class PageUrlPattern:
    """A URL pattern containing a # wildcard."""
    url_pattern_dims: 'list[UrlDimension]'
    page_ordinal_dim_index: int
    
    def construct_page_url(self, page_ordinal: int) -> 'PageUrl':
        new_dims = list(self.url_pattern_dims)
        new_dims[self.page_ordinal_dim_index] = _replace_dim_value(
            new_dims[self.page_ordinal_dim_index], str(page_ordinal)
        )
        url = _join_url_by_dimension(new_dims)
        return PageUrl(
            url,
            page_ordinal=page_ordinal,
            page_url_pattern=self,
        )
    
    def to_str(self) -> str:
        url_pattern_dims = list(self.url_pattern_dims)
        url_pattern_dims[self.page_ordinal_dim_index] = _replace_dim_value(
            url_pattern_dims[self.page_ordinal_dim_index], '#'
        )
        url_pattern_str = _join_url_by_dimension(url_pattern_dims)
        return url_pattern_str


@dataclass(frozen=True)
class PageUrl:
    """A URL to a page matching a particular PageUrlPattern."""
    url: str
    page_ordinal: int
    page_url_pattern: PageUrlPattern


@dataclass(frozen=True)
class Page:
    """A downloaded page."""
    url: PageUrl
    linked_page_urls: list[PageUrl]
    exists: bool
    
    @property
    def linked_page_ordinals(self) -> list[int]:
        return [
            linked_page_url.page_ordinal
            for linked_page_url in self.linked_page_urls
        ]


def detect_sequential_groups(
        project: Project,
        current_url: str,
        referrer_url: str | None,
        eager_downloads_ok=True,
        detect_last_page_ordinals: bool=True,
        ) -> Iterator[DetectedSequentialGroup]:
    """
    Detects sequential groups based on the current URL and referrer.
    
    A sequential group has members that take on consecutive integer values
    for at least one # wildcard position.
    
    Returns a iterator of detected sequential groups, each with their properties.
    
    To understand how the {eager_downloads_ok, detect_last_page_ordinals}
    parameters affect the performance and behavior of the calculations,
    see the docstring for _detect_sequential_group_at_dimension().
    """
    current_url_dims = _split_url_by_dimension(current_url)
    
    # Consider each dimension that could be matched by a # wildcard
    for (dim_index, dim) in enumerate(current_url_dims):
        if not re.fullmatch(r'[0-9]+', dim.value):
            continue
        page_ordinal = int(dim.value)
        
        page_url_pattern = PageUrlPattern(
            url_pattern_dims=current_url_dims,
            page_ordinal_dim_index=dim_index,
        )
        current_page_url = PageUrl(
            current_url,
            page_ordinal,
            page_url_pattern,
        )
        
        # Try to detect a sequential group at this dimension
        detected_group = _detect_sequential_group_at_dimension(
            project,
            current_page_url,
            referrer_url,
            eager_downloads_ok,
            detect_last_page_ordinals,
        )
        if detected_group is not None:
            yield detected_group


@bg_affinity
def _detect_sequential_group_at_dimension(
        project: Project,
        current_page_url: PageUrl,
        referrer_url: str | None,
        eager_downloads_ok: bool,
        detect_last_page_ordinal: bool,
        ) -> 'DetectedSequentialGroup | None':
    """
    Try to detect a sequential group at a specific URL dimension index.
    
    If eager_downloads_ok == False, then none of the DOWNLOAD operations
    mentioned in the below paragraphs will be performed.
    
    If detect_last_page_ordinal == True,
    a successfully detected sequential group will require 1-2 download operations:
    - If the current_page_url is the first/intermediate page,
      2 DOWNLOAD operations will be needed:
        - 1 download of any page (i.e. the first/intermediate page),
          to look for a link to the last page
        - 1 download of the last page, to confirm that it is
          actually the last page (and doesn't link to any page following it)
    - If the current_page_url is the last page,
      1 DOWNLOAD operation will be needed:
        - 1 download of any page (i.e. the current/last page),
          to look for a link to the last page
        - 0 additional downloads to get the last page, to confirm that it is
          actually the last page (and doesn't link to any page following it)
    
    If detect_last_page_ordinal == False,
    a successfully detected sequential group will require 0-1 download operations:
    - If the current_page_url is the first or last page,
      1 DOWNLOAD operation will be needed:
        - 1 download of any page (i.e. the current/first/last page),
          to look for a link to an adjacent page
    - If the referrer_url is a page and the current_page_url is an adjacent page:
      0 DOWNLOAD operations will be needed
        - 0 additional downloads of any page,
          to look for a link to an adjacent page
    
    TODO: Consider changing "detect_last_page_ordinal" to instead allow specifying:
    - DO_NOT_CALCULATE =
        Current behavior of detect_last_page_ordinal=False.
        <= 1 downloads.
    - CALCULATE_FAST =
        Current behavior of detect_last_page_ordinal=True.
        <= 2 downloads.
    - CALCULATE_ACCURATE =
        Accelerate/decelerate algorithm to find last page.
        <= log2(N) downloads, where N is the size of the sequential group.
    """
    # NOTE: Internal steps below related to downloading - which are expensive -
    #       write the word DOWNLOADING in all caps for increased visibility
    
    current_page_ordinal = current_page_url.page_ordinal
    
    source = _detect_narrowest_existing_group_given_member_url(project, referrer_url)
    if source is None:
        return None
    
    adjacent_page_ordinals = [
        current_page_url.page_ordinal + 1,
        current_page_url.page_ordinal - 1,
    ]
    
    # Ensure a sequential link from page K to (K+1) or (K-1) exists,
    # which is the key signature identifying a sequential group
    # 
    # 1. Check whether referrer_url -> current_page_url is
    #    a sequential link from page K to page (K+1) or (K-1)
    referrer_page_url = (
        _parse_url_for_page_matching_pattern(
            referrer_url, current_page_url.page_url_pattern)
        if referrer_url is not None
        else None
    )
    did_navigate_through_sequential_link = (
        referrer_page_url is not None and
        referrer_page_url.page_ordinal in adjacent_page_ordinals
    )
    if not did_navigate_through_sequential_link:
        if eager_downloads_ok:
            # 2. Check whether the current page, after DOWNLOADING, contains
            #    a sequential link from page K to page (K+1) or (K-1)
            current_page = _download_and_parse_page(project, current_page_url)
            current_page_contains_sequential_link = any(
                (x in current_page.linked_page_ordinals) for x in adjacent_page_ordinals
            )
            if not current_page_contains_sequential_link:
                return None
        else:
            # Can't prove that current page contains a sequential link
            return None
    else:
        current_page = None
    
    # Ensure first page is referenced
    seen_page_ordinals = [current_page_url.page_ordinal]
    if referrer_page_url is not None:
        seen_page_ordinals.append(referrer_page_url.page_ordinal)
    if current_page is not None:
        seen_page_ordinals.extend(current_page.linked_page_ordinals)
    if 1 in seen_page_ordinals:
        # Can skip calculations that depend on expensive DOWNLOADING
        page_1 = None
    else:
        if eager_downloads_ok:
            # Construct URL where page 1 should be. Try to DOWNLOAD it.
            page_url_1 = current_page_url.page_url_pattern.construct_page_url(1)
            page_1 = _download_and_parse_page(project, page_url_1)
            if not page_1.exists:
                return None
        else:
            # Can't prove the page 1 exists
            return None
    
    # TODO: Extract this section to its own function, so that complex conditional
    #       logic (especially related to detect_last_page_ordinal == False and
    #       eager_downloads_ok == False) can be simplified by early return statements
    if detect_last_page_ordinal:
        # Try to locate last page
        
        any_page = None
        seen_page_ordinals = [current_page_url.page_ordinal]
        if referrer_page_url is not None:
            seen_page_ordinals.append(referrer_page_url.page_ordinal)
        if current_page is not None:
            any_page = current_page
            seen_page_ordinals.extend(current_page.linked_page_ordinals)
        if page_1 is not None:
            any_page = page_1
            seen_page_ordinals.extend(page_1.linked_page_ordinals)
        if any_page is None:
            if eager_downloads_ok:
                # DOWNLOAD any page to look for link to last page
                current_page = _download_and_parse_page(project, current_page_url)
                any_page = current_page
                seen_page_ordinals.extend(current_page.linked_page_ordinals)
            else:
                any_page = None  # can't download one
        
        if any_page is None:
            # Unable to locate last page with the already-downloaded information
            assert eager_downloads_ok == False, \
                "Earlier code should have tried to download any_page"
            last_page_ordinal = None
        else:
            probable_last_page_ordinal = max(seen_page_ordinals)
            if probable_last_page_ordinal == current_page_ordinal and current_page is not None:
                probable_last_page = current_page
            else:
                if eager_downloads_ok:
                    # DOWNLOAD the probable last page, since we haven't done so already
                    probable_last_page_url = current_page_url.page_url_pattern.construct_page_url(
                        probable_last_page_ordinal)
                    probable_last_page = _download_and_parse_page(project, probable_last_page_url)
                else:
                    probable_last_page = None  # can't download one
            
            if probable_last_page is None:
                # Unable to verify last page with the already-downloaded information
                last_page_ordinal = None
            else:
                probable_last_page_ordinal2 = max(
                    probable_last_page.linked_page_ordinals,
                    default=probable_last_page_ordinal
                )
                if probable_last_page_ordinal2 > probable_last_page_ordinal:
                    # The probable last page links to a page following it,
                    # so we didn't actually find the last page.
                    # 
                    # Don't try any harder to find the last page for now.
                    # The caller can use more sophisticated techniques to locate
                    # the last page if it really wants to find it.
                    # 
                    # TODO: Add support for a CALCULATE_ACCURATE algorithm here.
                    #       See this function's docstring for more details.
                    last_page_ordinal = None
                else:
                    last_page_ordinal = probable_last_page_ordinal
    else:
        last_page_ordinal = None
    
    return DetectedSequentialGroup(
        source=source,
        url_pattern=current_page_url.page_url_pattern.to_str(),
        page_ordinal_dimension_index=current_page_url.page_url_pattern.page_ordinal_dim_index,
        first_page_ordinal=1,
        last_page_ordinal=last_page_ordinal,
    )


def _parse_url_for_page_matching_pattern(
        url: str,
        page_url_pattern: PageUrlPattern
        ) -> PageUrl | None:
    url_dims = _split_url_by_dimension(url)
    url_pattern_dims = page_url_pattern.url_pattern_dims  # cache
    page_ordinal_dim_index = page_url_pattern.page_ordinal_dim_index  # cache
    
    # Ensure URL has the same structure as the URL pattern
    if not _dims_match(url_dims, url_pattern_dims):
        return None
    
    # Ensure the non-page dimensions are identical
    for (i, (url_dim, url_pattern_dim)) in enumerate(zip(url_dims, url_pattern_dims)):
        if i == page_ordinal_dim_index:
            continue
        if url_dim.value != url_pattern_dim.value:
            return None
    
    # Ensure the target page ordinal has an integer value
    url_page_ordinal_dim = url_dims[page_ordinal_dim_index]
    if not re.fullmatch(r'[0-9]+', url_page_ordinal_dim.value):
        return None
    url_page_ordinal = int(url_page_ordinal_dim.value)
    
    return PageUrl(
        url=url,
        page_ordinal=url_page_ordinal,
        page_url_pattern=page_url_pattern
    )


@bg_affinity
def _download_and_parse_page(project: Project, page_url: PageUrl) -> Page:
    page_url_url = page_url.url  # cache
    page_url_pattern = page_url.page_url_pattern  # cache
    
    # Read/download the current page's latest revision
    try:
        page_r = fg_call_and_wait(lambda: Resource(project, page_url_url))
        # TODO: Timeout?
        # TODO: Better error handling?
        page_rev_future = page_r.download_body(interactive=True)
        page_rev = page_rev_future.result()
    except Exception:
        # If we can't download, assume page does not exist
        page_exists = False
    else:
        page_exists = (
            page_rev.status_code is not None and
            (page_rev.status_code // 100) == 2
        )
    if not page_exists:
        return Page(
            url=page_url,
            linked_page_urls=[],
            exists=False,
        )
    
    # Parse links from the revision
    linked_urls = [
        urljoin(page_url_url, link.relative_url)
        for link in page_rev.links()
    ]
    linked_page_urls = [
        linked_page_url
        for linked_url in linked_urls
        if (linked_page_url := _parse_url_for_page_matching_pattern(
            linked_url,
            page_url_pattern,
        )) is not None
    ]
    return Page(
        url=page_url,
        linked_page_urls=linked_page_urls,
        exists=True,
    )


# ------------------------------------------------------------------------------
# URL Dimensions

@dataclass(frozen=True)
class UrlDimension:
    type: str
    value: str


def _split_url_by_dimension(url: str) -> list[UrlDimension]:
    """
    Splits a URL into a list of UrlDimension values.
    
    The resulting UrlDimensions, when reading the contained string fragments
    from left-to-right, will always form the original URL.
    """
    m = re.fullmatch(r'(?i)^(?P<scheme>(?:http|https|ftp):)(?P<scheme_relative_url>//.*)$', url)
    if m is None:
        # Not a recognized hierarchical URL scheme
        return [UrlDimension(type=url, value='')]
    (scheme, scheme_relative_url) = m.groups()
    
    # If URL looks like it is from an exported Crystal site,
    # restore the original query in the URL so that predictions are better
    url_has_crystal_style_query = (
        '$/' in scheme_relative_url and 
        '?' not in scheme_relative_url
    )
    if url_has_crystal_style_query:
        scheme_relative_url = scheme_relative_url.replace('$/', '?')
    
    # ex: [('//', 'xkcd.com'), ('/', '1'), ('/', '')]
    # ex: [('//', 'www.artima.com'), ('/', 'weblogs'), ('/', 'index.jsp?blogger=guido&start=0&thRange=15')]
    level_dimensions = re.findall(r'(/+)([^/]*)', scheme_relative_url)  # type: list[tuple[str, str]]
    if len(level_dimensions) > 0:
        filename_and_query = level_dimensions[-1][1].split('?', maxsplit=1)
        if len(filename_and_query) == 2:  # has query
            # ex: ('index.jsp', 'blogger=guido&start=0&thRange=15')
            (filename, query) = filename_and_query
            # ex: [('blogger', 'guido'), ('start', '0'), ('thRange', '15')]
            query_kvs = [
                unsplit_kv.split('=', maxsplit=1)
                for unsplit_kv in query.split('&')
            ]
            
            query_dimensions = []
            for (i, kv) in enumerate(query_kvs):
                sep = '?' if i == 0 else '&'
                if len(kv) == 2:
                    (k, v) = kv
                    k += '='
                else:
                    k = ''
                    (v,) = kv
                query_dimensions.append((sep + k, v))
            
            old_last_level_dimension = level_dimensions[-1]
            new_last_level_dimension = (
                old_last_level_dimension[0],  # usually '/'
                filename
            )
            
            # ex: [
            #     ('//', 'www.artima.com'), ('/', 'weblogs'),
            #     ('/', 'index.jsp'),
            #     ('?blogger=', 'guido'), ('&start=', '0'), ('&thRange=', '15')
            # ]
            dimensions = _dims_from_tuples(
                level_dimensions[:-1] + 
                [new_last_level_dimension] +
                query_dimensions
            )
        else:  # has no query
            dimensions = _dims_from_tuples(level_dimensions)
    else:
        dimensions = _dims_from_tuples(level_dimensions)
    
    # Undo rewrite of the URL's query, if it was rewritten
    if url_has_crystal_style_query:
        for (i, dim) in enumerate(dimensions):
            if dim.type.startswith('?'):
                new_dim = _replace_dim_type(dim, '$/' + dim.type.removeprefix('?'))
                dimensions[i] = new_dim
    
    # Prepend scheme to first dimension
    if len(dimensions) > 0:
        dimensions[0] = _replace_dim_type(
            dimensions[0],
            scheme + dimensions[0].type)
    else:
        dimensions = [UrlDimension(scheme, '')]
    return dimensions


def _join_url_by_dimension(url_dims: list[UrlDimension]) -> str:
    parts = []
    for dim in url_dims:
        parts.append(dim.type)
        parts.append(dim.value)
    return ''.join(parts)


def _dims_match(dims1: list[UrlDimension], dims2: list[UrlDimension]) -> bool:
    if len(dims1) != len(dims2):
        return False
    for (dim1, dim2) in zip(dims1, dims2):
        if dim1.type != dim2.type:
            return False
    return True


def _dims_from_tuples(tuples: list[tuple[str, str]]) -> list[UrlDimension]:
    return [UrlDimension(type, value) for (type, value) in tuples]


def _replace_dim_type(dim: UrlDimension, new_type: str) -> UrlDimension:
    return UrlDimension(type=new_type, value=dim.value)


def _replace_dim_value(dim: UrlDimension, new_value: str) -> UrlDimension:
    return UrlDimension(type=dim.type, value=new_value)


# ------------------------------------------------------------------------------
