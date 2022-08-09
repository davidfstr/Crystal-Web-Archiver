from typing import TYPE_CHECKING
import wx

if TYPE_CHECKING:
    import wx.adv


def fix_date_picker_size(dp: 'wx.adv.DatePickerCtrl') -> 'wx.adv.DatePickerCtrl':
    dp_best_size = dp.GetBestSize()
    dp.SetMinSize(wx.Size(
        # HACK: macOS, Windows: Add space to read last digit of year
        dp_best_size.width + 5,
        # HACK: macOS: Remove extra padding at top (which messes up centering)
        dp_best_size.height - 4))
    return dp
