from collections import OrderedDict
from crystal import resources
from functools import cache
import wx

# ------------------------------------------------------------------------------
# Images

@cache
def TREE_NODE_ICONS() -> dict[str, wx.Bitmap]:
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
def ART_PROVIDER_TREE_NODE_ICONS() -> dict[int, wx.Bitmap]:
    # HACK: Uses private API
    from crystal.ui.tree import _DEFAULT_TREE_ICON_SIZE
    
    return OrderedDict([
        (art_id, wx.ArtProvider.GetBitmap(art_id, wx.ART_OTHER, _DEFAULT_TREE_ICON_SIZE))
        for art_id in [
            wx.ART_FOLDER,
            wx.ART_FOLDER_OPEN,
        ]
    ])


@cache
def BADGES() -> dict[str, wx.Bitmap]:
    return OrderedDict([
        (icon_name, _load_png_resource(f'badge_{icon_name}.png'))
        for icon_name in [
            'new',
            'prohibition',
            'stale',
            'warning',
        ]
    ])


def _load_png_resource(resource_name: str) -> wx.Bitmap:
    with resources.open_binary(resource_name) as f:
        bitmap = wx.Bitmap.FromPNGData(f.read())
    if not bitmap.IsOk():
        raise Exception(f'Failed to load image resource {resource_name}')
    return bitmap


# ------------------------------------------------------------------------------
# Derived Images

@cache
def BADGED_TREE_NODE_ICON(tree_node_icon_name: str, badge_name: str | None) -> wx.Bitmap:
    if badge_name is None:
        return TREE_NODE_ICONS()[tree_node_icon_name]
    return _add_badge_to_background(
        background=TREE_NODE_ICONS()[tree_node_icon_name],
        badge=BADGES()[badge_name])


@cache
def BADGED_ART_PROVIDER_TREE_NODE_ICON(art_id: int, badge_name: str | None) -> wx.Bitmap:
    if badge_name is None:
        return ART_PROVIDER_TREE_NODE_ICONS()[art_id]
    return _add_badge_to_background(
        background=ART_PROVIDER_TREE_NODE_ICONS()[art_id],
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


def add_transparent_left_border(original: wx.Bitmap, thickness: int) -> wx.Bitmap:
    if thickness == 0:
        return original
    
    bordered = wx.Bitmap()
    success = bordered.Create(
        original.Width + thickness,
        original.Height,
        original.Depth)
    if not success:
        raise Exception('Failed to create a wx.Bitmap')
    
    dc = wx.MemoryDC(bordered)
    dc.Clear()  # fill bitmap with white
    dc.DrawBitmap(
        original,
        x=thickness,
        y=0,
        useMask=True)
    dc.SelectObject(wx.NullBitmap)  # commit changes to bordered
    bordered.SetMaskColour(wx.Colour(255, 255, 255))  # replace white with transparent
    return bordered


# ------------------------------------------------------------------------------
