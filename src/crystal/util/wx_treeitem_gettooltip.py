import wx.lib.newevent

# Similar to wx's EVT_TREE_ITEM_GETTOOLTIP event, but cross-platform
(GetTooltipEvent, EVT_TREE_ITEM_GETTOOLTIP) = wx.lib.newevent.NewEvent()
