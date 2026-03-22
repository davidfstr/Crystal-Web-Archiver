"""
Data and algorithms extracted from the "entitytree" module that must be
usable even if wx is not available.
"""

from typing import assert_never, TYPE_CHECKING

if TYPE_CHECKING:
    from crystal.model.resource_group import ResourceGroup, RootResource


class RootResourceNodeInfo:
    ICON = '⚓️'
    ICON_TRUNCATION_FIX = ''
    
    # === Properties ===
    
    @staticmethod
    def calculate_title_of(root_resource: 'RootResource') -> str:
        project = root_resource.project
        display_url = project.get_display_url(root_resource.url)
        if root_resource.name != '':
            entity_title_format = project.entity_title_format  # cache
            if entity_title_format == 'name_url':
                return f'{root_resource.name} - {display_url}'
            elif entity_title_format == 'url_name':
                return f'{display_url} - {root_resource.name}'
            else:
                assert_never(entity_title_format)
        else:
            return f'{display_url}'


class _GroupedNodeInfo:
    ICON = '📁'
    ICON_TRUNCATION_FIX = ' '


class ResourceGroupNodeInfo(_GroupedNodeInfo):
    # === Properties ===
    
    @staticmethod
    def calculate_title_of(resource_group: 'ResourceGroup') -> str:
        project = resource_group.project
        display_url = project.get_display_url(resource_group.url_pattern)
        if resource_group.name != '':
            entity_title_format = project.entity_title_format  # cache
            if entity_title_format == 'name_url':
                return f'{resource_group.name} - {display_url}'
            elif entity_title_format == 'url_name':
                return f'{display_url} - {resource_group.name}'
            else:
                assert_never(entity_title_format)
        else:
            return f'{display_url}'
