from collections import OrderedDict
from crystal.util.bulkheads import capture_crashes_to_stderr
from crystal.util import cli
from crystal.util.wx_bind import bind
from crystal.util.xos import (
    is_linux, is_mac_os, is_windows, windows_major_version,
)
from crystal.util.xthreading import fg_call_later
from enum import Enum
from functools import cached_property
from io import StringIO, TextIOBase
from threading import Lock
from typing import Dict, List, Optional, Tuple, Union
import wx
from wx.richtext import RichTextCtrl


def _hexcolor_to_color(hexcolor: str) -> wx.Colour:
    assert hexcolor.startswith('#')
    return wx.Colour(
        int(hexcolor[1:3], 16),
        int(hexcolor[3:5], 16),
        int(hexcolor[5:7], 16)
    )

_CODE_PREFIX = '\033'
_COLOR_CODES = OrderedDict([
    # NOTE: Color hex values determined by matching what
    #       the Terminal app on macOS uses for these color codes
    (cli.TERMINAL_FG_GREEN,  _hexcolor_to_color('#33BD26')),
    (cli.TERMINAL_FG_RED,    _hexcolor_to_color('#C33820')),
    (cli.TERMINAL_FG_YELLOW, _hexcolor_to_color('#AEAD24')),
    (cli.TERMINAL_FG_CYAN,   _hexcolor_to_color('#33BBC7')),
])  # type: Dict[str, wx.Colour]
_RESET_CODE = cli.TERMINAL_RESET


# TODO: Avoid inheriting directly from wx.Frame because doing so
#       implicitly exports a bunch of API from wx.Frame as public
#       that is difficult to support.
class LogDrawer(wx.Frame):
    """
    A drawer that stays attached to the bottom of its parent window,
    even as the parent is repositioned or the parent/drawer is resized.
    
    This drawer contains a textual log that can be written to through the
    file-like object returned by `writer`. The writer understands
    ANSI escape codes generated by the crystal.util.cli package for
    colorizing text.
    
    See also:
    * Positioning and Sizing a Drawer
      https://developer.apple.com/library/archive/documentation/Cocoa/Conceptual/Drawers/Concepts/DrawerSizing.html
    * NSDrawer
      https://developer.apple.com/documentation/appkit/nsdrawer
    """
    
    _INITIAL_LEADING_PLUS_TRAILING_OFFSET = 100  # pixels
    
    # === Init ===
    
    def __init__(self, parent: wx.TopLevelWindow) -> None:
        content_children = self._content_children_of(parent)
        if len(content_children) != 1:
            raise ValueError(
                'LogDrawer can only be attached to a parent with exactly one child. '
                'Suggest moving existing children inside a single wx.Panel container. '
                f'Children: {content_children}')
        
        drawer_style = wx.CLIP_CHILDREN|wx.FRAME_NO_TASKBAR
        if _WindowPairingStrategy.get() == _WindowPairingStrategy.FLOAT_ON_PARENT:
            drawer_style |= wx.FRAME_FLOAT_ON_PARENT
        if wx_resize_border_is_invisible():
            drawer_style |= wx.RESIZE_BORDER
        super().__init__(parent=parent, style=drawer_style)
        
        self._ignore_next_activate = False
        self._leading_plus_trailing_offset = self._INITIAL_LEADING_PLUS_TRAILING_OFFSET
        self._last_height = None  # type: Optional[int]
        self._height_before_closed = None  # type: Optional[int]
        self._parent_will_be_maximized_after_next_resize = False
        self._parent_maximized_size = None
        self._parent_content_container = None  # non-None iff self maximized
        self._was_scrolled_to_bottom = True
        self._is_unmaximizing = False
        
        # Create splitter container that will show a visible sash at the bottom
        # of the drawer, to hint to the user that the drawer is designed
        # to be resized from the bottom edge
        self._splitter = wx.SplitterWindow(
            self,
            style=wx.SP_3D|wx.SP_NO_XP_THEME|wx.SP_LIVE_UPDATE)
        
        # Create upper textarea
        self._textarea = RichTextCtrl(
            self._splitter,
            style=wx.VSCROLL|wx.HSCROLL|wx.NO_BORDER|wx.richtext.RE_READONLY)
        self._textarea.AlwaysShowScrollbars(hflag=False, vflag=True)
        self._textarea.BackgroundColour = wx.Colour(0, 0, 0)  # black
        
        # Create empty bottom
        bottom_pane = wx.Window(self._splitter, style=wx.BORDER_NONE)
        
        # Finish creating splitter container
        self._splitter.SplitHorizontally(
            self._textarea,
            bottom_pane,
            sashPosition=-1  # bottom pane 1 pixel high (the minimum)
        )
        self._splitter.SashGravity = 1.0  # top window grows on resize
        self._splitter.MinimumPaneSize = 1  # prevent unsplit when sash is double-clicked
        
        # Use sizer to delete 1 pixel height used by bottom pane,
        # plus some extra to make the sash look good
        clip_amount = 1  # default
        if is_windows():  # Windows 7, Windows 8, Windows 10
            clip_amount = 4
        elif is_mac_os():  # macOS 10.14
            clip_amount = 3
        self_sizer = wx.BoxSizer(wx.VERTICAL)
        self_sizer.Add(self._splitter, proportion=1, flag=wx.EXPAND|wx.BOTTOM, border=-clip_amount)
        self.SetSizer(self_sizer)
        
        # Reshape self to initial size and position
        desired_width = self.Parent.Size.Width - self._leading_plus_trailing_offset
        self.SetSize(
            x=self._desired_x(desired_width),
            y=self._desired_y,
            width=desired_width,
            height=self._preferred_height,
            sizeFlags=wx.SIZE_USE_EXISTING)
        
        # Set minimum height (when drawer is closed)
        self.SetSizeHints(
            minW=-1,
            maxW=-1,
            minH=self._minimum_height,
            maxH=-1)
        
        # Bind event handlers
        bind(self.Parent, wx.EVT_MOVE, self._on_parent_reshaped)
        bind(self.Parent, wx.EVT_SIZE, self._on_parent_reshaped)
        bind(self._splitter, wx.EVT_LEFT_DOWN, self._on_splitter_mouse_down)
        bind(self._splitter, wx.EVT_MOTION, self._on_splitter_mouse_motion)
        bind(self._splitter, wx.EVT_LEFT_UP, self._on_splitter_mouse_up)
        bind(self._splitter, wx.EVT_SPLITTER_SASH_POS_CHANGING, self._on_splitter_sash_position_changing)
        bind(self._splitter, wx.EVT_SPLITTER_DCLICK, self._on_splitter_double_click)
        bind(self.Parent, wx.EVT_MAXIMIZE, self._on_parent_will_maximize)
        if hasattr(wx, 'EVT_FULLSCREEN'):  # wxPython >=4.2.1
            bind(self.Parent, wx.EVT_FULLSCREEN, self._on_parent_will_fullscreen_or_unfullscreen)
        bind(self._textarea, wx.EVT_SCROLLWIN, self._on_scroll)
        
        # Initialize event state
        self._on_splitter_mouse_up()
        
        # Initialize "resized recently" timer
        self._resized_recently_timer = wx.Timer(self)
        bind(self, wx.EVT_TIMER, self._on_resized_recently)
        self._resized_recently_timer.Start(100)  # ms
        
        # Setup drawer's initial maximized state
        if True:
            parent_already_maximized = self.Parent.IsMaximized() or (
                hasattr(self.Parent, 'IsFullScreen') and self.Parent.IsFullScreen())
            
            # Grow parent height to encompass drawer's initial height
            if not parent_already_maximized:
                self.Parent.SetSize(
                    x=wx.DefaultCoord,
                    y=wx.DefaultCoord,
                    width=wx.DefaultCoord,
                    height=self.Parent.Size.Height + self.Size.Height,
                    sizeFlags=wx.SIZE_USE_EXISTING)
            
            # Maximize self initially
            self._on_parent_did_maximize(force_maximize_self=True)
            self.Parent.SendSizeEvent()
    
    def close(self) -> None:
        self._resized_recently_timer.Stop()
        self.Close()
    
    # === Properties ===
    
    @cached_property
    def writer(self) -> TextIOBase:
        """
        Returns a file-like object representing this drawer's content that can be written to.
        
        Writing to the file will write to this drawer's content and will also
        write to sys.stdout.
        """
        return _LogDrawerWriter(self)
    
    # === Shape ===
    
    @property
    def is_open(self) -> bool:
        if self._parent_content_container is None:  # self unmaximized
            return self.Size.Height > self._minimum_height
        else:  # self maximized
            return self._parent_content_container.Window2.Size.Height > self._minimum_content_height
    
    def _desired_x(self, desired_width: int) -> int:
        return int(self.Parent.Position.x + (self.Parent.Size.Width - desired_width)/2)
    
    @property
    def _desired_y(self) -> int:
        return self.Parent.Position.y + self.Parent.Size.Height + self._desired_y_adjustment
    
    @cached_property
    def _desired_y_adjustment(self) -> int:
        if is_windows():
            major_version = windows_major_version()
            if major_version is None:  # unknown Windows
                pass
            elif major_version in [7, 8]:  # Windows 7, Windows 8
                return 0
            elif major_version >= 10:  # Windows 10+
                return -7
        # Default
        return 0
    
    @property
    def _preferred_height(self) -> int:
        PREFERRED_ROW_COUNT = 15
        return self._line_height * PREFERRED_ROW_COUNT
    
    @cached_property
    def _line_height(self) -> int:
        dc = wx.MemoryDC()
        dc.SetFont(self._textarea.Font)
        (_, h) = dc.GetTextExtent('m')
        return h
    
    @cached_property
    def _minimum_height(self) -> int:
        extra_height = 3  # default
        if is_windows():  # Windows *
            extra_height = 3  # Windows 7, Windows 8, Windows 10
        elif is_mac_os():  # macOS 10.14
            extra_height = 2
        result = self._splitter.SashSize + extra_height
        return result
    
    @property
    def _minimum_content_height(self) -> int:
        # NOTE: Must be >= 1 to prevent unsplit
        return 1
    
    # === Actions ===
    
    def _toggle_open(self) -> None:
        """Toggles whether this drawer is open or closed."""
        if self.is_open:
            # Close the drawer
            if self._parent_content_container is None:  # self unmaximized
                self._height_before_closed = self.Size.Height  # capture
                self.SetSize(
                    x=wx.DefaultCoord,
                    y=wx.DefaultCoord,
                    width=wx.DefaultCoord,
                    height=self._minimum_height,
                    sizeFlags=wx.SIZE_USE_EXISTING)
            else:  # self maximized
                self._height_before_closed = self._parent_content_container.Window2.Size.Height
                height_after_closed = self._minimum_content_height
                self._parent_content_container.SashPosition += \
                    self._height_before_closed - height_after_closed
        else:
            # Open the drawer
            if self._parent_content_container is None:  # self unmaximized
                height_before_closed = self._height_before_closed or self._preferred_height
                self.SetSize(
                    x=wx.DefaultCoord,
                    y=wx.DefaultCoord,
                    width=wx.DefaultCoord,
                    height=height_before_closed,
                    sizeFlags=wx.SIZE_USE_EXISTING)
                self._height_before_closed = None
            else:  # self maximized
                height_after_closed = self._minimum_content_height
                self._parent_content_container.SashPosition -= \
                    self._height_before_closed - height_after_closed
                self._height_before_closed = None
    
    def _maximize(self) -> None:
        assert self._parent_content_container is None  # self unmaximized
        
        (parent_content,) = self._content_children_of(self.Parent)
        
        was_closed = not self.is_open  # capture
        
        # Install wx.SplitterWindow in parent
        if True:
            self._parent_content_container = wx.SplitterWindow(self.Parent, style=wx.SP_3D|wx.SP_NO_XP_THEME|wx.SP_LIVE_UPDATE)
            assert self._parent_content_container is not None
            # Prevent unsplit if sash dragged all the way to top or bottom
            self._parent_content_container.MinimumPaneSize = self._minimum_content_height
            self._parent_content_container.SashGravity = 1.0
            parent_content.Reparent(self._parent_content_container)
            self._parent_content_container.Initialize(parent_content)
            self._parent_content_container.Fit()
            
            bind(self._parent_content_container, wx.EVT_SPLITTER_DCLICK, self._on_splitter_double_click)
            bind(self._parent_content_container, wx.EVT_SPLITTER_SASH_POS_CHANGING, self._on_resize_when_maximized)
        
        # Move log from drawer to parent
        if True:
            log_drawer_content = self._splitter.Window1
            log_drawer_content_height = log_drawer_content.Size.Height  # capture
            log_drawer_content.Reparent(self._parent_content_container)
            
            self._parent_content_container.SplitHorizontally(
                self._parent_content_container.Window1,
                log_drawer_content,
                # Target height
                -log_drawer_content_height)
            
            # Adjust drawer content height to match exact target height
            target_height = log_drawer_content_height
            actual_height = log_drawer_content.Size.Height
            self._parent_content_container.SashPosition -= target_height - actual_height
            
            self.Hide()
        
        if was_closed and self.is_open:
            old_height_before_closed = self._height_before_closed  # save
            self._toggle_open()
            assert not self.is_open
            self._height_before_closed = old_height_before_closed  # restore
    
    @property
    def _is_maximized(self) -> bool:
        return self._parent_content_container is not None
    
    @staticmethod
    def _content_children_of(parent: wx.Window) -> List[wx.Window]:
        return [c for c in parent.Children if not isinstance(c, wx.TopLevelWindow)]
    
    # === Events ===
    
    def _on_resize_when_maximized(self, event: wx.SplitterEvent) -> None:
        # Maintain scroll to bottom if applicable
        if self._was_scrolled_to_bottom:
            self._scroll_to_bottom()
        
        # Continue processing event in the normal fashion
        event.Skip()
    
    def _on_resized_recently(self, event: wx.TimerEvent) -> None:
        mouse_state = wx.GetMouseState()
        if not mouse_state.LeftIsDown():
            if self.is_open:
                self._height_before_closed = None
            
            # Stop waiting for mouse up
            self._resized_recently_timer.Stop()
    
    def _on_parent_reshaped(self, event: Union[wx.MoveEvent, wx.SizeEvent]) -> None:
        if isinstance(event, wx.SizeEvent):
            if self._parent_will_be_maximized_after_next_resize:
                self._parent_will_be_maximized_after_next_resize = False
                if self._parent_maximized_size is None:
                    self._on_parent_did_maximize()
                else:
                    self._parent_maximized_size = self.Parent.Size
            elif self._parent_maximized_size is not None and self._parent_maximized_size != event.Size:
                self._on_parent_unmaximized()
        
        # Continue processing event in the normal fashion
        event.Skip()
    
    def _on_splitter_mouse_down(self, event: wx.MouseEvent) -> None:
        self._mouse_down_y = event.Y  # capture
        self._mouse_down_height = self.Size.Height  # capture
        
        # Continue processing event in the normal fashion
        event.Skip()
    
    def _on_splitter_mouse_motion(self, event: wx.MouseEvent) -> None:
        if self._mouse_down_y is not None:
            new_height = max(
                self._mouse_down_height + (event.Y - self._mouse_down_y),
                self._minimum_height)
            
            # Alter the drawer height
            self.SetSize(
                x=wx.DefaultCoord,
                y=wx.DefaultCoord,
                width=wx.DefaultCoord,
                height=new_height,
                sizeFlags=wx.SIZE_USE_EXISTING)
        
        # Continue processing event in the normal fashion
        event.Skip()
    
    def _on_splitter_mouse_up(self, event: Optional[wx.MouseEvent]=None) -> None:
        self._mouse_down_y = None
        self._mouse_down_height = None
        
        if event is not None:
            # Continue processing event in the normal fashion
            event.Skip()
    
    def _on_splitter_sash_position_changing(self, event: wx.SplitterEvent) -> None:
        # Veto sash position change
        event.SetSashPosition(-1)
    
    def _on_splitter_double_click(self, event: wx.SplitterEvent) -> None:
        self._toggle_open()
    
    def _on_parent_will_maximize(self, event: Optional[wx.MaximizeEvent]=None) -> None:
        self._parent_will_be_maximized_after_next_resize = True
        
        if event is not None:
            # Continue processing event in the normal fashion
            event.Skip()
    
    def _on_parent_did_maximize(self, *, force_maximize_self: bool=False) -> None:
        self._parent_maximized_size = self.Parent.Size
        if force_maximize_self:
            self._maximize()
    
    def _on_parent_unmaximized(self) -> None:
        self._parent_maximized_size = None
    
    def _on_parent_will_fullscreen_or_unfullscreen(self, event) -> None:
        if event.IsFullScreen():  # fullscreen
            self._parent_will_be_maximized_after_next_resize = True
            self._on_parent_did_maximize()
        else:  # un-fullscreen
            self._on_parent_unmaximized()
        
        # Continue processing event in the normal fashion
        event.Skip()
    
    def _on_scroll(self, event: wx.ScrollEvent) -> None:
        if event.Orientation == wx.VERTICAL:
            self._was_scrolled_to_bottom = self._scrolled_to_bottom
        
        # Continue processing event in the normal fashion
        event.Skip()
    
    @property
    def _scrolled_to_bottom(self) -> bool:
        textarea = self._textarea  # cache
        textarea_was_scrolled_to_bottom = (
            textarea.GetScrollPos(wx.VERTICAL) +
            textarea.GetScrollThumb(wx.VERTICAL) +
            self._line_height
        ) >= textarea.GetScrollRange(wx.VERTICAL)  # capture
        return textarea_was_scrolled_to_bottom
    
    def _scroll_to_bottom(self) -> None:
        textarea = self._textarea  # cache
        textarea.ShowPosition(textarea.LastPosition)


class _LogDrawerWriter(TextIOBase):
    def __init__(self, drawer: LogDrawer) -> None:
        self._drawer = drawer
        self._print_buffer_lock = Lock()
        self._print_buffer = []  # type: List[str]
    
    def write(self, text: str) -> int:
        # Send text to sys.stdout
        print(text, end='')
        
        # Queue text to be printed to drawer
        with self._print_buffer_lock:
            self._print_buffer.append(text)
        
        # Start printing queued texts to drawer, but don't wait until finished
        # 
        # NOTE: Normally would print crashes to LogDrawer, but this IS the
        #       print function for LogDrawer, so fallback to stderr instead.
        @capture_crashes_to_stderr
        def fg_task() -> None:
            with self._print_buffer_lock:
                last_print_buffer = self._print_buffer
                if len(last_print_buffer) == 0:
                    return
                self._print_buffer = []
            
            textarea = self._drawer._textarea  # cache
            textarea_was_scrolled_to_bottom = (
                self._drawer._was_scrolled_to_bottom
            )  # capture
            
            for text in last_print_buffer:
                # Append text to text area
                if True:
                    # Try parse coloring codes around text
                    color: Optional[wx.Colour] = None  # default
                    plain_text: str = text  # default
                    if _CODE_PREFIX in text:
                        if text.endswith(_RESET_CODE):
                            for (code, color) in _COLOR_CODES.items():
                                if text.startswith(code):
                                    break
                            else:
                                # Failed to parse codes
                                color = None
                            if color is not None:
                                plain_text = text[len(code):-len(_RESET_CODE)]
                            else:
                                # Failed to parse codes
                                pass
                        else:
                            # Failed to parse codes
                            pass
                    else:
                        # Text contains no codes
                        pass
                    
                    # Append colored text
                    textarea.SetInsertionPointEnd()
                    if color is not None:
                        textarea.BeginTextColour(color)
                    textarea.WriteText(plain_text)
                    if color is not None:
                        textarea.EndTextColour()
                        # HACK: EndTextColour doesn't seem to actually work
                        #       unless I immediately write some text afterward.
                        # TODO: Eliminate these inserted '\u200b' values
                        #       from any text copied (or cut) from the text area.
                        textarea.WriteText('\u200b')  # zero-width space
            
            if textarea_was_scrolled_to_bottom:
                self._drawer._scroll_to_bottom()
        fg_call_later(fg_task)
        
        # Report successful print
        return len(text)


class _WindowPairingStrategy(Enum):
    """
    Strategy used to keep a drawer window floating directly above 
    (or directly below) its parent window at all times.
    """
    
    # Keep the drawer floating directly above its parent window at all times,
    # using the wx.FRAME_FLOAT_ON_PARENT style bit on the drawer.
    # 
    # Doesn't work properly on macOS: When activating a window
    # from a different app, that window appears below the drawer,
    # rather than that window appearing above both the drawer and
    # the drawer's parent window.
    FLOAT_ON_PARENT = 1
    
    # Keep the drawer floating either directly above or below its parent window at all times,
    # via creative use of the wx.STAY_ON_TOP style bit and wx.Window.Raise().
    FLOAT_AND_RAISE_ON_ACTIVATE = 2
    
    @staticmethod
    def get() -> '_WindowPairingStrategy':
        if is_mac_os():  # macOS 10.14
            return _WindowPairingStrategy.FLOAT_AND_RAISE_ON_ACTIVATE
        elif is_windows():  # Windows 7
            return _WindowPairingStrategy.FLOAT_ON_PARENT
        else:
            return _WindowPairingStrategy.FLOAT_ON_PARENT


def wx_resize_border_is_invisible() -> bool:
    """
    Returns whether the wx.RESIZE_BORDER style applied to a wx.Frame causes
    a resizable border to appear that is visible, as opposed to one that is invisible.
    """
    if is_mac_os():  # macOS 10.14+
        return True
    elif is_windows():  # Windows *
        major_version = windows_major_version()
        if major_version is None:  # unknown Windows
            pass
        elif major_version in [7, 8]:  # Windows 7, Windows 8
            # Windows 7 and 8 add a visible border on all edges
            return False
        elif major_version >= 10:  # Windows 10+
            # Windows 10 adds a visible border on the top edge only
            return False
        else:  # unknown Windows
            pass
        # Unknown Windows
        return False
    elif is_linux():  # Ubuntu 22.04+
        return True
    
    # Default, assuming a newer OS
    return True
