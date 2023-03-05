from collections import OrderedDict
from crystal.util.cache import cache
from typing import Dict
import wx


@cache
def TREE_NODE_ICONS() -> Dict[str, wx.Bitmap]:
    return OrderedDict([
        (icon_name, _get_tree_node_icon(icon_name))
        for icon_name in [
            # Entity Tree Icons
            'entitytree_cluster_embedded',
            'entitytree_cluster_offsite',
            'entitytree_loading',
            'entitytree_resource',
            'entitytree_root_resource',
            'entitytree_warning',
            
            # Task Tree Icons
            'tasktree_done',
            'tasktree_download_group_members',
            'tasktree_download_group',
            'tasktree_download_resource_body',
            'tasktree_download_resource',
            'tasktree_parse',
            'tasktree_update_group',
        ]
    ])


@cache
def _get_tree_node_icon(icon_name: str) -> wx.Bitmap:
    return _load_png_resource(f'treenodeicon_{icon_name}.png')


def _load_png_resource(resource_name: str) -> wx.Bitmap:
    # TODO: Move general resource management out of crystal.tests package
    from crystal.tests.test_data import open_binary
    
    with open_binary(resource_name) as f:
        bitmap = wx.Bitmap.FromPNGData(f.read())
    if not bitmap.IsOk():
        raise Exception(f'Failed to load image resource {resource_name}')
    return bitmap
