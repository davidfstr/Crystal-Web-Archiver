from collections.abc import Callable
from crystal.util.bulkheads import capture_crashes_to_stderr
from crystal.util.wx_bind import bind
from crystal.util.xos import is_linux, is_windows
from crystal.util.xthreading import fg_call_later
import wx
import wx.lib.buttons


class Callout(wx.Panel):
    """
    A callout that displays a message pointing to a target control.
    
    Features:
    - Displays a message with a triangle pointing to a target control
    - Can temporarily dismiss by pressing an X button
    - Can permanently dismiss by ticking a checkbox
    """
    _CORNER_RADIUS = 6  # px
    _PADDING = 8  # px
    _COLOR = wx.Colour(10, 130, 255)  # primary blue
    
    _MESSAGE_MAX_WIDTH = 250  # px
    
    # Triangle pointer properties
    _TRIANGLE_HEIGHT = 8  # px
    _TRIANGLE_WIDTH = 16  # px
    
    _CALLOUT_TO_CONTROL_GAP = 0  # px
    
    # === Init ===
    
    def __init__(self,
            parent: wx.Window,
            target_control: wx.Control,
            message: str,
            *, on_temporary_dismiss: Callable[[], None] | None = None,
            on_permanent_dismiss: Callable[[], None] | None = None,
            name: str,
            ) -> None:
        """
        Creates a callout pointing to a target control.
        
        The callout should be added to the same parent control as its target control.
        
        The callout will be initially hidden and must be shown using
        show_callout() after its target control is finished being positioned.
        
        The callout has a transparent background which can cause rendering
        artifacts on Windows because Windows has trouble with components that
        stack on top of each other. See MainWindow.{_on_tree_paint, _on_tree_scroll}
        for an example of workarounds for forcefully repainting a callout if
        the control underneath the callout is repainted.
        
        Arguments:
        * parent -- Parent window
        * target_control -- Control to point the callout towards
        * message -- Help message to display
        * on_temporary_dismiss -- Callback when temporarily dismissed (X button)
        * on_permanent_dismiss -- Callback when permanently dismissed (checkbox)
        * name -- Control name for testing
        """
        super().__init__(
            parent,
            style=wx.BORDER_NONE,
            name=name,
        )
        
        self._target_control = target_control
        self._on_temporary_dismiss = on_temporary_dismiss or (lambda: None)
        self._on_permanent_dismiss = on_permanent_dismiss or (lambda: None)
        
        self.SetBackgroundStyle(wx.BG_STYLE_CUSTOM)  # Enable custom background painting
        self.SetForegroundColour(wx.Colour(255, 255, 255))  # White text
        
        self._create_child_windows(message)
        self.hide_callout()  # start hidden
        
        # Configure to draw custom background:
        # rounded rectangle + triangle
        bind(self, wx.EVT_PAINT, self._on_paint)
        
        self._listen_for_need_to_reposition_callout()
    
    def _create_child_windows(self, message: str) -> None:
        sizer = wx.BoxSizer(wx.VERTICAL)
        self.SetSizer(sizer)
        
        # Top bar with close button
        top_bar = wx.BoxSizer(wx.HORIZONTAL)
        
        # Message text
        message_text = wx.StaticText(self, label=message)
        message_text.SetForegroundColour(self.GetForegroundColour())
        if is_windows():
            # On Windows, child controls need explicit background color to match parent
            message_text.SetBackgroundColour(self._COLOR)
        message_text.Wrap(self._MESSAGE_MAX_WIDTH)
        
        # Close button (X)
        if is_linux():
            close_button_size = (36, 34)
        else:  # is_mac_os() or is_windows()
            close_button_size = (20, 20)
        if is_windows():
            # On Windows, use GenButton because the native button doesn't allow
            # customizing the background color to blend in to the parent's background
            close_button = wx.lib.buttons.GenButton(self, label="✕", size=close_button_size)
            close_button.SetBackgroundColour(self._COLOR)
            
            # Override DrawFocusIndicator to fix replace default strange
            # orange focus color with something more sensible
            def custom_draw_focus_indicator(dc: wx.DC, w: int, h: int) -> None:
                focus_color = wx.Colour(135, 206, 255)  # light sky blue
                focus_pen = wx.Pen(focus_color, 1, wx.PENSTYLE_USER_DASH)  # dashed line
                focus_pen.SetDashes([1, 1])
                focus_pen.SetCap(wx.CAP_BUTT)
                
                # Draw focus rectangle inside the bezel area of the button's border
                dc.SetPen(focus_pen)
                margin = close_button.bezelWidth + 1  # Stay inside the beveled edge
                dc.DrawLine(margin, margin, w - margin, margin)  # top
                dc.DrawLine(margin, h - margin - 1, w - margin, h - margin - 1)  # bottom
                dc.DrawLine(margin, margin, margin, h - margin - 1)  # left
                dc.DrawLine(w - margin - 1, margin, w - margin - 1, h - margin - 1)  # right
            close_button.DrawFocusIndicator = custom_draw_focus_indicator
        else:
            # On macOS/Linux, regular button works fine
            close_button = wx.Button(self, label="✕", size=close_button_size)
        close_button.SetName(self.Name + '__close-button')
        bind(close_button, wx.EVT_BUTTON, self._on_close_button)
        close_button.SetToolTip("Dismiss this help message")
        
        top_bar.Add(
            message_text,
            proportion=1,
            flag=wx.ALIGN_TOP | wx.ALL,
            border=self._PADDING,
        )
        top_bar.Add(
            close_button,
            flag=wx.ALIGN_TOP | wx.TOP | wx.BOTTOM | wx.RIGHT,
            border=self._PADDING,
        )
        
        sizer.Add(top_bar, flag=wx.EXPAND)
        
        # Checkbox for permanent dismissal
        self._dismiss_checkbox = wx.CheckBox(
            self,
            label="Don't show this message again",
            name=self.Name + '__dismiss-checkbox')
        self._dismiss_checkbox.SetForegroundColour(self.GetForegroundColour())
        if is_windows():
            # On Windows, explicitly set background color to match parent
            self._dismiss_checkbox.SetBackgroundColour(self._COLOR)
        sizer.Add(
            self._dismiss_checkbox,
            flag=wx.ALL,
            border=self._PADDING,
        )
        
        # Add space for the triangle pointer at the bottom
        sizer.AddSpacer(self._TRIANGLE_HEIGHT)
        
        self.Fit()
    
    @capture_crashes_to_stderr
    def _position_callout(self) -> None:
        """Position the callout relative to the target control."""
        callout_size = self.GetSize()  # cache
        
        # Get target control position and size, in parent-relative coordinates
        target_x: int
        target_y: int
        target_width: int
        if True:
            target_rect = self._target_control.GetScreenRect()
            parent_rect = self.GetParent().GetScreenRect()
            
            # Convert to parent-relative coordinates
            target_x = target_rect.x - parent_rect.x
            target_y = target_rect.y - parent_rect.y
            target_width = target_rect.width
        
        # Position callout above the target control, centered horizontally
        callout_x = target_x + (target_width - callout_size.width) // 2
        callout_y = target_y - callout_size.height - self._CALLOUT_TO_CONTROL_GAP

        # Reposition callout to fit within parent bounds
        parent_size = self.GetParent().GetSize()
        callout_x = max(10, min(callout_x, parent_size.width - callout_size.width - 10))
        callout_y = max(10, min(callout_y, parent_size.height - callout_size.height - 10))
        
        # Commit position change
        self.SetPosition((callout_x, callout_y))
        
        # Update the drawn triangle's position
        self.Refresh()
    
    def _listen_for_need_to_reposition_callout(self) -> None:
        # Listen for size changes on ancestor windows
        parent = self.GetParent()
        while parent is not None:
            bind(parent, wx.EVT_SIZE, self._on_layout_change)
            parent = parent.GetParent()
        
        # Listen for splitter sash position changes on ancestor windows
        parent = self.GetParent()
        while parent is not None:
            if isinstance(parent, wx.SplitterWindow):
                bind(parent, wx.EVT_SPLITTER_SASH_POS_CHANGED, self._on_layout_change)
                bind(parent, wx.EVT_SPLITTER_SASH_POS_CHANGING, self._on_layout_change)
            parent = parent.GetParent()
    
    def _on_layout_change(self, event: wx.Event) -> None:
        # Reposition the callout if it's currently visible
        if self.IsShown():
            # NOTE: Ensure the layout has been updated before repositioning
            fg_call_later(self._position_callout, force_later=True)
        
        # Allow default processing to continue
        event.Skip()
    
    # === Events ===
    
    def _on_paint(self, event: wx.PaintEvent) -> None:
        """Draws the callout background."""
        dc = wx.PaintDC(self)
        # Use GraphicsContext instead of wx.DC for proper transparency support
        gc = wx.GraphicsContext.Create(dc)
            
        size = self.GetSize()  # cache
        
        # Clear the entire background to transparent
        gc.SetBrush(wx.Brush(wx.Colour(0, 0, 0, 0)))  # Fully transparent
        gc.DrawRectangle(0, 0, size.width, size.height)
        
        # Calculate triangle position
        if True:
            # Get target control position relative to this callout
            target_rect = self._target_control.GetScreenRect()
            callout_rect = self.GetScreenRect()
            
            # Calculate where the triangle should point (center of target control)
            target_center_x = target_rect.x + target_rect.width // 2
            callout_left_x = callout_rect.x
            
            # Triangle tip x-position relative to callout panel
            triangle_tip_x = target_center_x - callout_left_x
            
            # Constrain triangle tip to be within the callout bounds
            triangle_tip_x = max(
                self._TRIANGLE_WIDTH // 2, 
                min(
                    triangle_tip_x,
                    size.width - self._TRIANGLE_WIDTH // 2
                )
            )
        
        # Create a path that combines the rounded rectangle and triangle
        path = gc.CreatePath()
        if True:
            # Main callout rectangle dimensions
            callout_height = size.height - self._TRIANGLE_HEIGHT
            
            # Draw rounded rectangle path
            path.AddRoundedRectangle(0, 0, size.width, callout_height, self._CORNER_RADIUS)
            
            # Add triangle to the path
            triangle_y = callout_height
            path.MoveToPoint(triangle_tip_x - self._TRIANGLE_WIDTH // 2, triangle_y)
            path.AddLineToPoint(triangle_tip_x + self._TRIANGLE_WIDTH // 2, triangle_y)
            path.AddLineToPoint(triangle_tip_x, size.height)
            path.CloseSubpath()
        
        # Fill the path
        gc.SetBrush(gc.CreateBrush(wx.Brush(self._COLOR)))
        gc.FillPath(path)
    
    def _on_close_button(self, event: wx.CommandEvent) -> None:
        if self._dismiss_checkbox.GetValue():
            self._on_permanent_dismiss()
        else:
            self._on_temporary_dismiss()
        
        self.Hide()
    
    # === Operations ===
    
    def show_callout(self) -> None:
        """Show the callout and bring it to front."""
        self._position_callout()
        self.Show()
        self.Raise()  # Bring to front
        self.Refresh()  # Ensure triangle is drawn correctly
        
    def hide_callout(self) -> None:
        self.Hide()
