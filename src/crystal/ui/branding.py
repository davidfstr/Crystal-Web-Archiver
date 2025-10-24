"""
Utilities for displaying the Crystal program name with consistent branding.
"""

from crystal import APP_NAME, resources
from crystal.util.wx_system_appearance import IsDark
from crystal.util.xos import is_linux, is_mac_os, is_windows
import sys
import wx


# === App Icon ===

def load_app_icon(size: wx.Size) -> wx.Bitmap:
    """Load the Crystal application icon from resources."""
    with resources.open_binary('appicon.png') as f:
        bitmap = wx.Bitmap.FromPNGData(f.read())
    if not bitmap.IsOk():
        raise Exception('Failed to load app icon')
    
    # Scale if needed
    if bitmap.Size != size:
        image = bitmap.ConvertToImage()
        image = image.Scale(size.Width, size.Height, wx.IMAGE_QUALITY_HIGH)
        bitmap = wx.Bitmap(image)  # reinterpret
    
    return bitmap


# === Program Name / Logotext ===

def create_program_name_control(parent: wx.Window) -> wx.StaticBitmap | wx.StaticText:
    """Creates a control displaying the Crystal program name using a logotext bitmap."""
    PROGRAM_NAME = APP_NAME
    PROGRAM_NAME_USES_BITMAP = True
    
    font_size_scale = get_font_size_scale()  # cache
    is_dark_mode = IsDark()  # cache
    
    # Try to load bitmap logotext for consistent cross-platform rendering
    try:
        if not PROGRAM_NAME_USES_BITMAP:
            # TODO: Avoid using exceptions purely for control flow
            raise Exception('Forcing text fallback for logotext bitmap')
        logotext_bundle = load_logotext_bitmap(is_dark_mode)
        if logotext_bundle:
            program_name = wx.StaticBitmap(parent, bitmap=logotext_bundle)
        else:
            raise RuntimeError("Failed to create logotext bundle")
    except Exception as e:
        # Fallback to text if bitmap loading fails
        print(
            f"Warning: Failed to load logotext bitmap, using text fallback: {e}",
            file=sys.stderr)
        program_name = wx.StaticText(parent, label=PROGRAM_NAME)
        program_name_font = load_app_name_font(int(23 * font_size_scale))
        program_name.SetFont(program_name_font)
    
    return program_name


def load_logotext_bitmap(is_dark_mode: bool = False) -> wx.BitmapBundle:
    """Load the Crystal logotext bitmap bundle with 1x and 2x versions."""
    bitmaps = []
    
    # Choose filenames based on mode
    if is_dark_mode:
        filename_1x = 'logotext-dark.png'
        filename_2x = 'logotext-dark@2x.png'
    else:
        filename_1x = 'logotext.png'
        filename_2x = 'logotext@2x.png'
    
    # Load 1x version
    try:
        with resources.open_binary(filename_1x) as f:
            bitmap_1x = wx.Bitmap.FromPNGData(f.read())
        if bitmap_1x.IsOk():
            bitmaps.append(bitmap_1x)
    except Exception:
        pass
    
    # Load 2x version
    try:
        with resources.open_binary(filename_2x) as f:
            bitmap_2x = wx.Bitmap.FromPNGData(f.read())
        if bitmap_2x.IsOk():
            bitmaps.append(bitmap_2x)
    except Exception:
        pass
    
    if not bitmaps:
        raise Exception('Failed to load logotext bitmaps')
    
    # Create bitmap bundle from available bitmaps
    return wx.BitmapBundle.FromBitmaps(bitmaps)


def load_app_name_font(base_size: int) -> wx.Font:
    """Create a Futura Medium font with fallback to system fonts."""
    # Try Futura Medium first
    font = wx.Font(base_size, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_MEDIUM, faceName='Futura')
    if font.IsOk() and font.GetFaceName() == 'Futura' and font.GetWeight() == wx.FONTWEIGHT_MEDIUM:
        return font
    
    # Try Futura Normal
    font = wx.Font(base_size, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL, faceName='Futura')
    if font.IsOk() and font.GetFaceName() == 'Futura':
        return font
     
    # Fallback to System Bold
    font = wx.Font(base_size, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD)
    assert font.IsOk(), 'Failed to create fallback font'
    return font


# === Authors ===

AUTHORS_1_TEXT = 'By David Foster and '
AUTHORS_2_TEXT = 'contributors'
AUTHORS_2_URL = 'https://github.com/davidfstr/Crystal-Web-Archiver/graphs/contributors'


# === Utility: Fonts ===

def get_font_size_scale() -> float:
    """
    Determines the font size scale based on OS.
    
    Most font sizes should be multiplied by this scaling factor to give a
    consistent vertical height across operating systems.
    """
    if is_mac_os():
        font_size_scale = 1.0
    elif is_windows() or is_linux():
        font_size_scale = 72 / 96
    else:
        raise AssertionError('Unknown operating system')
    return font_size_scale
