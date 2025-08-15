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
_BASE_FONT_SIZE = 23


def generate_logotext_bitmaps(output_dir: str | None = None):
    """
    Generate logotext bitmaps at 1x and 2x resolutions.
    
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
        
        # Generate 1x bitmap
        bitmap_1x = _render_text_to_bitmap(_TEXT, font_1x)
        bitmap_1x_path = output_dir_path / "logotext.png"
        bitmap_1x.SaveFile(str(bitmap_1x_path), wx.BITMAP_TYPE_PNG)
        print(f"Generated 1x logotext: {bitmap_1x_path}")
        print(f"  Size: {bitmap_1x.GetWidth()}x{bitmap_1x.GetHeight()}")
        
        # Generate 2x bitmap  
        bitmap_2x = _render_text_to_bitmap(_TEXT, font_2x)
        bitmap_2x_path = output_dir_path / "logotext@2x.png"
        bitmap_2x.SaveFile(str(bitmap_2x_path), wx.BITMAP_TYPE_PNG)
        print(f"Generated 2x logotext: {bitmap_2x_path}")
        print(f"  Size: {bitmap_2x.GetWidth()}x{bitmap_2x.GetHeight()}")
        
        print("\nLogotype bitmaps generated successfully!")
        print("These can now be used with wx.BitmapBundle for consistent cross-platform rendering.")
    finally:
        app.Destroy()


def _render_text_to_bitmap(text: str, font: wx.Font) -> wx.Bitmap:
    """
    Render text to a bitmap with transparent background.
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
    
    # Clear with white background first (we'll make it transparent later)
    dc.SetBackground(wx.Brush(wx.Colour(255, 255, 255)))
    dc.Clear()
    
    # Set font and text color
    dc.SetFont(font)
    dc.SetTextForeground(wx.Colour(0, 0, 0))  # Black text
    
    # Draw text
    dc.DrawText(text, padding, padding)
    
    # Clean up DC
    dc.SelectObject(wx.NullBitmap)
    
    # Convert to image to set transparency
    image = bitmap.ConvertToImage()
    
    # Set white pixels to transparent
    image.SetMask(True)
    image.SetMaskColour(255, 255, 255)
    
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
