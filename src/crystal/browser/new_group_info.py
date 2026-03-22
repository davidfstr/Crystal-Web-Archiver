"""
Data and algorithms extracted from the "new_group" module that must be
usable even if wx is not available.
"""

from crystal.model import Project, ResourceGroup


class NewGroupDialogInfo:
    _MAX_VISIBLE_PREVIEW_URLS = 100
    
    # === Operations ===
    
    @classmethod
    def _calculate_preview_urls(cls, project: Project, url_pattern: str) -> list[str]:
        url_pattern_re = ResourceGroup.create_re_for_url_pattern(url_pattern)
        literal_prefix = ResourceGroup.literal_prefix_for_url_pattern(url_pattern)
        
        url_pattern_is_literal = (len(literal_prefix) == len(url_pattern))
        if url_pattern_is_literal:
            member = project.get_resource(literal_prefix)
            if member is None:
                (matching_urls, approx_match_count) = ([], 0)
            else:
                (matching_urls, approx_match_count) = ([member.url], 1)
        else:
            (matching_urls, approx_match_count) = project.urls_matching_pattern(
                url_pattern_re, literal_prefix, limit=cls._MAX_VISIBLE_PREVIEW_URLS)
        
        if len(matching_urls) == 0:
            return []
        else:
            more_count = approx_match_count - len(matching_urls)
            more_items = (
                [f'... about {more_count:n} more']
                if more_count != 0
                else []
            )
            return matching_urls + more_items
