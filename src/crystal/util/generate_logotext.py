#!/usr/bin/env python3
"""
Generate logotext bitmaps for Crystal.

This utility renders "Crystal" text using Futura Medium font
and saves it as PNG images at multiple resolutions for 
consistent cross-platform display.

Usage:
$ python3 -m crystal.util.generate_logotext
"""

from pathlib import Path
import sys
import wx


# Text to render
_TEXT = "Crystal"
# Base font size for 1x rendering
# NOTE: Duplicated by _BASE_FONT_SIZE and .cr-brand-header__logotext--text font-size */
_BASE_FONT_SIZE = 23
# NOTE: Duplicated by _LIGHT_TEXT_COLOR and .cr-brand-header__logotext--text color
_LIGHT_TEXT_COLOR = (0, 0, 0)
# NOTE: Duplicated by _DARK_TEXT_COLOR and @media .cr-brand-header__logotext--text color
_DARK_TEXT_COLOR = (216, 216, 216)  # AKA #d8d8d8


def generate_logotext_bitmaps(output_dir: str | None = None):
    """
    Generate logotext bitmaps at 1x and 2x resolutions for both light and dark modes.
    
    Arguments:
    * output_dir -- Directory to save the bitmaps. Defaults to src/crystal/resources/
    """
    if output_dir is None:
        # Default to resources directory
        script_dir = Path(__file__).parent
        output_dir_path = script_dir.parent / "resources"
    else:
        output_dir_path = Path(output_dir)
    
    output_dir_path.mkdir(exist_ok=True)
    
    app = wx.App(False)  # Create wx app for font rendering
    try:
        # Try to use Futura Medium, fall back to system font
        font_1x = wx.Font(_BASE_FONT_SIZE, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_MEDIUM, faceName='Futura')
        if not font_1x.IsOk() or font_1x.GetFaceName() != 'Futura' or font_1x.GetWeight() != wx.FONTWEIGHT_MEDIUM:
            # Try without "Medium"
            font_1x = wx.Font(_BASE_FONT_SIZE, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL, faceName='Futura')
            if not font_1x.IsOk() or font_1x.GetFaceName() != 'Futura':
                # Fallback to system font with bold weight
                font_1x = wx.Font(_BASE_FONT_SIZE, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD)
                print(f"Warning: Futura font not found, using fallback: {font_1x.GetFaceName()}")
            else:
                print(f"Using Futura font: {font_1x.GetFaceName()}")
        else:
            print(f"Using Futura Medium font: {font_1x.GetFaceName()}")
        
        # Create 2x font
        font_2x = wx.Font(_BASE_FONT_SIZE * 2, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, font_1x.GetWeight(), faceName=font_1x.GetFaceName())
        
        # Generate light mode variants (black text)
        # Generate 1x bitmap
        bitmap_1x_light = _render_text_to_bitmap(_TEXT, font_1x, text_color=_LIGHT_TEXT_COLOR)
        bitmap_1x_path = output_dir_path / "logotext.png"
        bitmap_1x_light.SaveFile(str(bitmap_1x_path), wx.BITMAP_TYPE_PNG)
        print(f"Generated 1x logotext (light): {bitmap_1x_path}")
        print(f"  Size: {bitmap_1x_light.GetWidth()}x{bitmap_1x_light.GetHeight()}")
        
        # Generate 2x bitmap  
        bitmap_2x_light = _render_text_to_bitmap(_TEXT, font_2x, text_color=_LIGHT_TEXT_COLOR)
        bitmap_2x_path = output_dir_path / "logotext@2x.png"
        bitmap_2x_light.SaveFile(str(bitmap_2x_path), wx.BITMAP_TYPE_PNG)
        print(f"Generated 2x logotext (light): {bitmap_2x_path}")
        print(f"  Size: {bitmap_2x_light.GetWidth()}x{bitmap_2x_light.GetHeight()}")
        
        # Generate dark mode variants (white text on black background)
        # Generate 1x bitmap
        bitmap_1x_dark = _render_text_to_bitmap(_TEXT, font_1x, text_color=_DARK_TEXT_COLOR, background_color=(0, 0, 0))
        bitmap_1x_dark_path = output_dir_path / "logotext-dark.png"
        bitmap_1x_dark.SaveFile(str(bitmap_1x_dark_path), wx.BITMAP_TYPE_PNG)
        print(f"Generated 1x logotext (dark): {bitmap_1x_dark_path}")
        print(f"  Size: {bitmap_1x_dark.GetWidth()}x{bitmap_1x_dark.GetHeight()}")
        
        # Generate 2x bitmap  
        bitmap_2x_dark = _render_text_to_bitmap(_TEXT, font_2x, text_color=_DARK_TEXT_COLOR, background_color=(0, 0, 0))
        bitmap_2x_dark_path = output_dir_path / "logotext-dark@2x.png"
        bitmap_2x_dark.SaveFile(str(bitmap_2x_dark_path), wx.BITMAP_TYPE_PNG)
        print(f"Generated 2x logotext (dark): {bitmap_2x_dark_path}")
        print(f"  Size: {bitmap_2x_dark.GetWidth()}x{bitmap_2x_dark.GetHeight()}")
        
        print("\nLogotype bitmaps generated successfully!")
        print("These can now be used with wx.BitmapBundle for consistent cross-platform rendering.")
        print("Light mode variants: logotext.png, logotext@2x.png")
        print("Dark mode variants: logotext-dark.png, logotext-dark@2x.png")
    finally:
        app.Destroy()


def _render_text_to_bitmap(
        text: str,
        font: wx.Font,
        text_color: tuple[int, int, int] = (0, 0, 0),
        background_color: tuple[int, int, int] = (255, 255, 255)
        ) -> wx.Bitmap:
    """
    Render text to a bitmap with transparent background.
    
    Arguments:
    * text -- The text to render
    * font -- The font to use for rendering
    * text_color -- RGB tuple for text color (default: black)
    * background_color -- RGB tuple for background color (default: white). This color will be made transparent.
    """
    # Create a temporary DC to measure text
    temp_dc = wx.MemoryDC()
    temp_dc.SetFont(font)
    text_width, text_height = temp_dc.GetTextExtent(text)
    
    # Add some padding
    padding = 0
    bitmap_width = text_width + (padding * 2)
    bitmap_height = text_height + (padding * 2)
    
    # Create bitmap (use default depth, not 32-bit)
    bitmap = wx.Bitmap(bitmap_width, bitmap_height)
    
    # Create DC for rendering
    dc = wx.MemoryDC(bitmap)
    
    # Clear with specified background color (will be made transparent later)
    dc.SetBackground(wx.Brush(wx.Colour(*background_color)))
    dc.Clear()
    
    # Set font and text color
    dc.SetFont(font)
    dc.SetTextForeground(wx.Colour(*text_color))
    
    # Draw text
    dc.DrawText(text, padding, padding)
    
    # Clean up DC
    dc.SelectObject(wx.NullBitmap)
    
    # Convert to image to set transparency
    image = bitmap.ConvertToImage()
    
    # Set background pixels to transparent
    image.SetMask(True)
    image.SetMaskColour(*background_color)
    
    # Convert back to bitmap
    result_bitmap = wx.Bitmap(image)
    
    return result_bitmap


if __name__ == "__main__":
    output_dir_arg: str | None
    if len(sys.argv) > 1:
        output_dir_arg = sys.argv[1]
    else:
        output_dir_arg = None
    
    generate_logotext_bitmaps(output_dir_arg)
