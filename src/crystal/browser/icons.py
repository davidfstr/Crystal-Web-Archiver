from collections import OrderedDict
from crystal.util.cache import cache
from typing import Dict, Optional
import wx


# ------------------------------------------------------------------------------
# Images

@cache
def TREE_NODE_ICONS() -> Dict[str, wx.Bitmap]:
    return OrderedDict([
        (icon_name, _load_png_resource(f'treenodeicon_{icon_name}.png'))
        for icon_name in [
            # Entity Tree Icons
            'entitytree_cluster_embedded',
            'entitytree_cluster_offsite',
            'entitytree_loading',
            'entitytree_more',
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
def BADGES() -> Dict[str, wx.Bitmap]:
    return OrderedDict([
        (icon_name, _load_png_resource(f'badge_{icon_name}.png'))
        for icon_name in [
            'new',
            'stale',
            'warning',
        ]
    ])


def _load_png_resource(resource_name: str) -> wx.Bitmap:
    # TODO: Move general resource management out of crystal.tests package
    from crystal.tests.test_data import open_binary
    
    with open_binary(resource_name) as f:
        bitmap = wx.Bitmap.FromPNGData(f.read())
    if not bitmap.IsOk():
        raise Exception(f'Failed to load image resource {resource_name}')
    return bitmap


# ------------------------------------------------------------------------------
# Derived Images

@cache
def BADGED_TREE_NODE_ICON(tree_node_icon_name: str, badge_name: Optional[str]) -> wx.Bitmap:
    if badge_name is None:
        return TREE_NODE_ICONS()[tree_node_icon_name]
    return _add_badge_to_background(
        background=TREE_NODE_ICONS()[tree_node_icon_name],
        badge=BADGES()[badge_name])


def _add_badge_to_background(background: wx.Bitmap, badge: wx.Bitmap) -> wx.Bitmap:
    background_plus_badge = background.GetSubBitmap(
        wx.Rect(0, 0, background.Width, background.Height))  # copy
    dc = wx.MemoryDC(background_plus_badge)
    # Draw badge in lower-right corner
    dc.DrawBitmap(
        badge,
        x=background.Width - badge.Width,
        y=background.Height - badge.Height,
        useMask=True)
    dc.SelectObject(wx.NullBitmap)  # commit changes to background_plus_badge
    return background_plus_badge


# ------------------------------------------------------------------------------
