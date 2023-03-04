from collections import OrderedDict
from crystal.util.cache import cache
from typing import Dict
import wx


@cache
def TREE_NODE_ICONS() -> Dict[str, wx.Bitmap]:
    return OrderedDict([
        (icon_name, _get_tree_node_icon(icon_name))
        for icon_name in [
            'entitytree_cluster_embedded',
            'entitytree_cluster_offsite',
            'entitytree_loading',
            'entitytree_resource',
            'entitytree_root_resource',
            'entitytree_warning',
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
