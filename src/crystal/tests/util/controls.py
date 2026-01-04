from __future__ import annotations

from collections.abc import Callable, Container, Iterator
from contextlib import contextmanager
import crystal
from crystal.tests.util.runner import bg_sleep
from crystal.util.bulkheads import capture_crashes_to_stderr
from crystal.util.wx_treeitem_gettooltip import GetTooltipEvent
from crystal.util.xos import is_mac_os, is_windows
from crystal.util.xthreading import fg_call_later
import datetime
from functools import cache
import os
import re
import subprocess
import sys
import tempfile
from typing import TYPE_CHECKING, List, Literal, Optional, TypeAlias, assert_never
from unittest.mock import patch
import wx

if TYPE_CHECKING:
    from crystal.ui.nav import Navigator, Snapshot


# ------------------------------------------------------------------------------
# General: Click

_ClickablePeer: TypeAlias = 'wx.Button | wx.CheckBox | wx.RadioButton | TreeItem'
Clickable: TypeAlias = '_ClickablePeer | Navigator | Snapshot'

# NOTE: This function is exposed to AI agents in the shell
def click(window: Clickable, *, sync: bool = True) -> None:
    """
    Clicks a wx.Window control.
    
    Waits for the click handler to return unless sync=False.
    Async clicks can be useful if the click handler takes a blocking action
    such as running a modal dialog.
    
    Examples:
    - click(T(Id=wx.ID_YES).W)
    - click(T['cr-open-or-create-project__checkbox'].W)
    - click(T[0][0][0][0][2].W)
    
    Raises:
    * ElementNotInteractableException -- if window is disabled
    """
    if isinstance(window, wx.Window) and not window.Enabled:
        raise ElementNotInteractableException(window)
    
    # Allow clicking common objects that point to a unique wx.Window
    from crystal.ui.nav import Navigator, Snapshot
    if isinstance(window, (Navigator, Snapshot)):
        return click(window.Peer)
    
    if sync:
        _click_now(window)
    else:
        fg_call_later(
            capture_crashes_to_stderr(lambda: _click_now(window)),
            force_later=True,
        )


def _click_now(window: _ClickablePeer) -> None:
    if isinstance(window, wx.Button):
        click_button(window)
    elif isinstance(window, wx.CheckBox):
        click_checkbox(window)
    elif isinstance(window, wx.RadioButton):
        click_radio_button(window)
    elif isinstance(window, TreeItem):
        window.SelectItem()
    else:
        if TYPE_CHECKING:
            assert_never(window)
        else:
            raise NotImplementedError(
                f'Do not know how to click a {type(window).__name__}.'
            )


class ElementNotInteractableException(Exception):
    def __init__(self, window: wx.Window) -> None:
        super().__init__(f'Window is disabled, so click has no effect: {window}')


# ------------------------------------------------------------------------------
# General: Screenshot

# NOTE: This function is exposed to AI agents in the shell
async def screenshot(window: wx.Window | 'Navigator' | 'Snapshot' | None = None) -> 'ScreenshotResult':
    """
    Takes a screenshot of the specified wx.Window,
    or of all top-level windows if no window is provided.
    
    Examples:
    - await screenshot()  # capture all top-level windows
    - await screenshot(T['cr-entity-pane'].W)  # capture a specific window
    - await screenshot(T['cr-entity-pane'])  # same as above (Navigator/Snapshot)
    
    Returns:
    * ScreenshotResult -- contains the filepath where the screenshot was saved
    """
    # Resolve Navigator or Snapshot to wx.Window
    if window is not None:
        from crystal.ui.nav import Navigator, Snapshot
        if isinstance(window, (Navigator, Snapshot)):
            window = window.Peer
        
        if not isinstance(window, wx.Window):
            raise NotImplementedError(
                f'Do not know how to screenshot a {type(window).__name__}.'
            )
    
    # Determine screenshots directory
    base_dirpath = os.getcwd()  # default
    if getattr(sys, 'frozen', None) is None:
        src_dirpath = os.path.dirname(os.path.dirname(os.path.abspath(crystal.__file__)))
        if os.path.basename(src_dirpath) == 'src':
            # Running from source code
            base_dirpath = os.path.dirname(src_dirpath)  # reinterpret
    screenshots_dirpath = os.path.join(base_dirpath, '.screenshots')
    os.makedirs(screenshots_dirpath, exist_ok=True)
    
    # Generate filename with timestamp and window name
    if True:
        timestamp = datetime.datetime.now().strftime('%Y-%m-%d-%H%M')
        
        # Add window identifier if specific window provided
        window_name_safe = _sanitize_for_filename(_get_window_identifier(window))
        screenshot_filename = f'{timestamp}__{window_name_safe}.png'
        
        # Generate unique filepath if file already exists
        base_filepath = os.path.join(screenshots_dirpath, screenshot_filename)
        screenshot_filepath = base_filepath
        counter = 2
        while os.path.exists(screenshot_filepath):
            name_without_ext = os.path.splitext(screenshot_filename)[0]
            screenshot_filepath = os.path.join(screenshots_dirpath, f'{name_without_ext}-{counter}.png')
            counter += 1
    
    screenshot_filepath = os.path.abspath(screenshot_filepath)
    
    # Take screenshot
    await _capture_screenshot_to_file(screenshot_filepath, window)
    
    return ScreenshotResult(screenshot_filepath)


def _get_window_identifier(window: wx.Window | None) -> str:
    """
    Returns a string identifier for a window suitable for use in a filename.
    """
    if window is None:
        return 'all-windows'
    
    if window.Name and window.Name not in DEFAULT_WINDOW_NAMES():
        return window.Name
    else:
        return type(window).__name__


@cache
def DEFAULT_WINDOW_NAMES() -> Container[str]:
    from crystal.ui.nav import WindowNavigator
    return set(WindowNavigator._DEFAULT_NAME_FOR_WINDOW_TYPE_STR.values())


def _sanitize_for_filename(name: str) -> str:
    """
    Sanitizes a string to be safe for use in a filename.
    """
    # Keep only safe characters: letters, digits, hyphens, underscores
    safe_name = re.sub(r'[^a-zA-Z0-9_-]', '-', name)
    return safe_name


async def _capture_screenshot_to_file(filepath: str, window: wx.Window | None) -> None:
    """
    Captures a screenshot and saves it to the specified filepath.
    
    Brings Crystal to the foreground before capturing to ensure the app
    content is visible (not obscured by other applications).
    
    Arguments:
    * filepath -- absolute path where screenshot should be saved
    * window -- wx.Window to capture, or None to capture all top-level windows
    """
    # Bring Crystal to front so the screenshot captures Crystal's windows
    # rather than whatever is behind them
    if is_mac_os():
        from crystal.util.macos_app import bring_app_to_front
        bring_app_to_front()
    else:
        # On other platforms, raise the window to front
        top_level_window = _get_top_level_window_containing(window)
        if top_level_window is not None:
            top_level_window.Raise()
    # Give the window manager a moment to actually bring windows to front.
    # NOTE: Use bg_sleep to yield control to the foreground thread so 
    #       window raise events can be processed.
    await bg_sleep(0.1)
    
    # If target is all top-level windows and there is exactly 1 top-level window,
    # then retarget to capture exactly that top-level window
    if window is None:
        parentless_tlws = [w for w in wx.GetTopLevelWindows() if w.Parent is None]
        if len(parentless_tlws) == 1:
            (window,) = parentless_tlws
    
    try:
        if window is not None:
            _capture_window_screenshot_to_file(filepath, window)
        else:
            # TODO: Capture ONLY the top-level windows,
            #       showing a transparent/white background whereever there
            #       is not a top-level window.
            _capture_fullscreen_screenshot_to_file(filepath)
    except Exception as e:
        print(f'*** Failed to save screenshot: {e}', file=sys.stderr)
        raise


def _capture_window_screenshot_to_file(filepath: str, window: wx.Window) -> None:
    """
    Captures a screenshot of a specific window and saves it to a file.
    
    Arguments:
    * filepath -- absolute path where screenshot should be saved
    * window -- wx.Window to capture
    """
    rect = window.GetScreenRect()
    if is_mac_os():
        # On macOS, use screencapture with region bounds
        # Format: screencapture -R x,y,w,h file.png
        result = subprocess.call([
            'screencapture',
            '-x',  # don't play camera sound
            '-R', f'{rect.x},{rect.y},{rect.width},{rect.height}',
            filepath
        ])
        if result != 0:
            raise RuntimeError(f'screencapture command failed with exit code: {result}')
    else:
        # On other platforms, use PIL ImageGrab
        try:
            from PIL import ImageGrab
        except ImportError:
            raise ImportError(
                'Unable to save screenshot because PIL/Pillow is not available.'
            )
        
        # Capture the screen region
        bbox = (rect.x, rect.y, rect.x + rect.width, rect.y + rect.height)
        image = ImageGrab.grab(bbox=bbox)
        
        # Save the image
        image.save(filepath, 'PNG')


def _capture_fullscreen_screenshot_to_file(filepath: str) -> None:
    """
    Captures a screenshot showing all top-level windows, on a transparent background.
    
    Arguments:
    * filepath -- absolute path where screenshot should be saved
    """
    # Get rectangles for all top-level windows
    window_rects = []
    for window in wx.GetTopLevelWindows():
        if window.Shown:  # Only include visible windows
            window_rects.append(window.GetScreenRect())
    
    if not window_rects:
        # No visible windows to capture
        _create_empty_transparent_image(filepath)
        return
    
    # Find the union rectangle that contains all windows
    min_x = min(rect.x for rect in window_rects)
    min_y = min(rect.y for rect in window_rects)
    max_x = max(rect.x + rect.width for rect in window_rects)
    max_y = max(rect.y + rect.height for rect in window_rects)
    union_width = max_x - min_x
    union_height = max_y - min_y
    
    # Create a temporary file for the initial screenshot
    with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as temp_file:
        temp_filepath = temp_file.name
    
    # TODO: Restructure so that tempfile context cleans up its own file
    try:
        # Screenshot the union region
        if is_mac_os():
            result = subprocess.call([
                'screencapture',
                '-x',  # don't play camera sound
                '-R', f'{min_x},{min_y},{union_width},{union_height}',
                temp_filepath
            ])
            if result != 0:
                raise RuntimeError(f'screencapture command failed with exit code: {result}')
        else:
            try:
                from PIL import ImageGrab
            except ImportError:
                raise ImportError(
                    'Unable to save screenshot because PIL/Pillow is not available.'
                )
            bbox = (min_x, min_y, max_x, max_y)
            image = ImageGrab.grab(bbox=bbox)
            image.save(temp_filepath, 'PNG')
        
        # Load the screenshot and create transparent image with only Crystal windows
        _create_transparent_windowed_screenshot(
            temp_filepath, filepath, window_rects, min_x, min_y
        )
    finally:
        # Clean up temporary file
        if os.path.exists(temp_filepath):
            os.remove(temp_filepath)


def _create_empty_transparent_image(filepath: str) -> None:
    """
    Creates a 1x1 transparent PNG image using wxPython.
    
    Arguments:
    * filepath -- absolute path where image should be saved
    """
    # Create a 1x1 transparent image
    image = wx.Image(1, 1)
    image.InitAlpha()
    image.SetAlpha(0, 0, 0)
    
    # Save as PNG
    image.SaveFile(filepath, wx.BITMAP_TYPE_PNG)


def _create_transparent_windowed_screenshot(
        source_filepath: str,
        dest_filepath: str,
        window_rects: List[wx.Rect],
        offset_x: int,
        offset_y: int
        ) -> None:
    """
    Creates a screenshot with transparent background showing only window regions.
    
    Uses wxPython for all image manipulation to avoid external dependencies.
    
    Arguments:
    * source_filepath -- path to source screenshot image
    * dest_filepath -- path where final image should be saved
    * window_rects -- list of window rectangles in screen coordinates
    * offset_x -- X offset of the source image relative to screen coordinates
    * offset_y -- Y offset of the source image relative to screen coordinates
    """
    # Load the source screenshot as a wx.Image
    source_image = wx.Image(source_filepath)
    if not source_image.IsOk():
        raise RuntimeError(f'Failed to load screenshot from {source_filepath}')
    
    # Create a transparent image of the same size
    width = source_image.GetWidth()
    height = source_image.GetHeight()
    transparent_image = wx.Image(width, height)
    transparent_image.InitAlpha()
    
    # Initialize all pixels as transparent (alpha = 0)
    # TODO: Is there a more efficient way to bulk-set this pixel data
    for y in range(height):
        for x in range(width):
            transparent_image.SetAlpha(x, y, 0)
    
    # Copy each window region from source to transparent image
    for rect in window_rects:
        # Convert screen coordinates to image coordinates
        img_x = rect.x - offset_x
        img_y = rect.y - offset_y
        
        # Ensure the rectangle is within the source image bounds
        in_bounds = (
            img_x >= 0 and img_y >= 0 and
            img_x + rect.width <= width and
            img_y + rect.height <= height
        )
        if not in_bounds:
            continue
            
        # Copy pixels from source to transparent image for this window region
        # TODO: Is there a more efficient way to bulk-copy this pixel data
        for dy in range(rect.height):
            for dx in range(rect.width):
                src_x = img_x + dx
                src_y = img_y + dy
                
                # Copy RGB values
                r = source_image.GetRed(src_x, src_y)
                g = source_image.GetGreen(src_x, src_y)
                b = source_image.GetBlue(src_x, src_y)
                transparent_image.SetRGB(src_x, src_y, r, g, b)
                
                # Set alpha to fully opaque for window pixels
                transparent_image.SetAlpha(src_x, src_y, 255)
    
    # Save the final image
    if not transparent_image.SaveFile(dest_filepath, wx.BITMAP_TYPE_PNG):
        raise RuntimeError(f'Failed to save transparent screenshot to {dest_filepath}')


def _get_top_level_window_containing(window: wx.Window) -> wx.Window | None:
    """
    Returns the top-level window (Frame or Dialog) containing the given window.
    """
    current = window
    while current is not None:
        parent = current.GetParent()
        if parent is None:
            # Found the top-level window
            return current
        current = parent
    return None


class ScreenshotResult:
    def __init__(self, filepath: str) -> None:
        self._filepath = filepath
    
    @property
    def filepath(self) -> str:
        return self._filepath
    
    def __repr__(self) -> str:
        return f'🤖 Screenshot saved to: {self._filepath}'


# ------------------------------------------------------------------------------
# wx.Button

def click_button(button: wx.Button) -> None:
    # Dispatch wx.EVT_BUTTON event
    event = wx.PyCommandEvent(wx.EVT_BUTTON.typeId, button.GetId())
    event.SetEventObject(button)
    assert event.GetEventObject().GetId() == button.GetId()
    button.Command(event)


# ------------------------------------------------------------------------------
# wx.CheckBox

def set_checkbox_value(checkbox: wx.CheckBox, value: bool) -> None:
    """
    Changes the value of a checkbox in a way that fires a realistic
    wx.EVT_CHECKBOX event if appropriate.
    """
    if checkbox.Value != value:
        click_checkbox(checkbox)
        assert checkbox.Value == value


def click_checkbox(checkbox: wx.CheckBox) -> None:
    old_value = checkbox.Value  # capture
    
    # Toggle value
    checkbox.Value = not checkbox.Value
    
    # Dispatch wx.EVT_CHECKBOX event
    event = wx.PyCommandEvent(wx.EVT_CHECKBOX.typeId, checkbox.GetId())
    event.SetEventObject(checkbox)
    assert event.GetEventObject().GetId() == checkbox.GetId()
    checkbox.ProcessEvent(event)
    
    new_value = checkbox.Value  # capture
    assert new_value != old_value, 'Expected checkbox to toggle value'


# ------------------------------------------------------------------------------
# wx.RadioButton

def click_radio_button(radio: wx.RadioButton) -> None:
    radio.Value = True
    radio.ProcessEvent(wx.CommandEvent(wx.wxEVT_RADIOBUTTON, radio.Id))


# ------------------------------------------------------------------------------
# wx.FileDialog

@contextmanager
def file_dialog_returning(filepath: str | list[str]) -> Iterator[None]:
    filepaths = filepath if isinstance(filepath, list) else [filepath]
    
    with patch('wx.FileDialog', spec=True) as MockFileDialog:
        instance = MockFileDialog.return_value
        instance.ShowModal.return_value = wx.ID_OK
        instance.GetPath.side_effect = filepaths
        
        yield
        
        if instance.ShowModal.call_count != len(filepaths):
            raise AssertionError(
                f'Expected wx.FileDialog.ShowModal to be called exactly {len(filepaths)} time(s), '
                f'but it was called {instance.ShowModal.call_count} time(s)')


# ------------------------------------------------------------------------------
# wx.Menu

# TODO: Alter callers that use the {menu, menuitem_id} signature to use {menuitem} instead
#       when possible because it requires less bookkeeping in the caller.
def select_menuitem_now(
        menu: wx.Menu | None = None,
        menuitem_id: int | None = None,
        *, menuitem: wx.MenuItem | None = None
        ) -> None:
    """
    Selects a menu item immediately.
    
    Either both `menu` and `menuitem_id` must be specified, or `menuitem` must be.
    """
    if menuitem is None:
        if menu is None or menuitem_id is None:
            raise ValueError('Either both `menu` and `menuitem_id` must be specified, or `menuitem` must be specified')
    else:
        menu = menuitem.GetMenu()
        menuitem_id = menuitem.GetId()
        
        assert menuitem.IsEnabled(), \
            f'Menu item {menuitem.GetItemLabelText()!r} is not enabled'
    
    # Process the related wx.EVT_MENU event immediately,
    # so that the event handler is called before the wx.Menu is disposed
    event = wx.MenuEvent(type=wx.EVT_MENU.typeId, id=menuitem_id, menu=None)
    menu.ProcessEvent(event)


# ------------------------------------------------------------------------------
# wx.TreeCtrl

def get_children_of_tree_item(tree: wx.TreeCtrl, tii: wx.TreeItemId) -> list[TreeItem]:
    children = []  # type: List[TreeItem]
    next_child_tii = tree.GetFirstChild(tii)[0]
    while next_child_tii.IsOk():
        children.append(TreeItem(tree, next_child_tii))
        next_child_tii = tree.GetNextSibling(next_child_tii)  # reinterpret
    return children


class TreeItem:
    __slots__ = ['tree', 'id']
    
    _USE_FAST_ID_COMPARISONS = True
    
    # === Init ===
    
    def __init__(self, tree: wx.TreeCtrl, id: wx.TreeItemId) -> None:
        if not id.IsOk():
            raise ValueError('TreeItemId is invalid')
        
        self.tree = tree
        self.id = id
    
    # === Root ===
    
    # TODO: Consider rename to RootOf, which reads more naturally IMHO
    @staticmethod
    def GetRootItem(tree: wx.TreeCtrl) -> TreeItem:
        root_tii = tree.GetRootItem()
        assert root_tii.IsOk()
        return TreeItem(tree, root_tii)
    
    def IsRoot(self) -> bool:
        return self.id == self.tree.GetRootItem()
    
    # === Peer Queries and Actions ===
    
    @property
    def Text(self) -> str:
        return self.tree.GetItemText(self.id)
    
    @property
    def TextColour(self) -> wx.Colour:
        return self.tree.GetItemTextColour(self.id)
    
    @property
    def Bold(self) -> bool:
        return self.tree.IsBold(self.id)
    
    def Tooltip(self, tooltip_type: Literal['icon', 'label', None]=None) -> str | None:
        event = GetTooltipEvent(tree_item_id=self.id, tooltip_cell=[Ellipsis], tooltip_type=tooltip_type)
        self.tree.ProcessEvent(event)  # callee should set: event.tooltip_cell[0]
        assert event.tooltip_cell[0] is not Ellipsis
        if isinstance(event.tooltip_cell[0], Exception):
            raise event.tooltip_cell[0]
        return event.tooltip_cell[0]
    
    def SelectItem(self) -> None:
        self.tree.SelectItem(self.id)
    
    def IsSelected(self) -> bool:
        return self.tree.IsSelected(self.id)
    
    @staticmethod
    def GetSelection(tree: wx.TreeCtrl) -> TreeItem | None:
        selected_tii = tree.GetSelection()
        if selected_tii.IsOk():
            return TreeItem(tree, selected_tii)
        else:
            return None
    
    def ItemHasChildren(self) -> bool:
        return self.tree.ItemHasChildren(self.id)
    
    def Expand(self) -> None:
        self.tree.Expand(self.id)
    
    def Collapse(self) -> None:
        self.tree.Collapse(self.id)
    
    def IsExpanded(self) -> bool:
        return self.tree.IsExpanded(self.id)
    
    def ScrollTo(self) -> None:
        self.tree.ScrollTo(self.id)
    
    def GetFirstChild(self) -> TreeItem | None:
        first_child_tii = self.tree.GetFirstChild(self.id)[0]
        if first_child_tii.IsOk():
            return TreeItem(self.tree, first_child_tii)
        else:
            return None
    
    @property
    def Children(self) -> list[TreeItem]:
        return get_children_of_tree_item(self.tree, self.id)
    
    @property
    def _ItemData(self) -> object:
        return self.tree.GetItemData(self.id)
    
    # === Entity Tree: Find Child ===
    
    def find_child(
            parent_ti: TreeItem,
            url_or_url_pattern: str,
            default_url_prefix: str | None=None
            ) -> TreeItem:
        """
        Returns the first child of the specified parent tree item with the
        specified URL or URL pattern.
        
        Raises TreeItem.ChildNotFound if such a child is not found.
        """
        if default_url_prefix is not None:
            if url_or_url_pattern.startswith(default_url_prefix):
                url_or_url_pattern = url_or_url_pattern[len(default_url_prefix):]  # reinterpret
        try:
            (matching_child_ti,) = (
                child for child in parent_ti.Children
                if child.Text.startswith(f'{url_or_url_pattern} - ')
            )
        except ValueError:
            try:
                (matching_child_ti,) = (
                    child for child in parent_ti.Children
                    if child.Text == url_or_url_pattern
                )
            except ValueError:
                child_texts = [child.Text for child in parent_ti.Children]
                raise TreeItem.ChildNotFound(
                    f'Child {url_or_url_pattern} not found in specified TreeItem. '
                    f'Instead found {child_texts}.'
                ) from None
        return matching_child_ti
    
    def try_find_child(parent_ti: TreeItem, *args, **kwargs) -> TreeItem | None:
        try:
            return parent_ti.find_child(*args, **kwargs)
        except TreeItem.ChildNotFound:
            return None

    def find_child_by_title(parent_ti: TreeItem, title_fragment: str) -> TreeItem:
        """
        Returns the first child of the specified parent tree item whose
        title contains the specified fragment.
        
        Raises TreeItem.ChildNotFound if such a child is not found.
        """
        try:
            (matching_child_ti,) = (
                child for child in parent_ti.Children
                if title_fragment in child.Text
            )
            return matching_child_ti
        except ValueError:
            raise TreeItem.ChildNotFound(
                f'Child with title fragment {title_fragment!r} not found in specified TreeItem'
            ) from None
    
    class ChildNotFound(AssertionError):
        pass
    
    # === Operations ===
    
    async def right_click_showing_popup_menu(self, show_popup_menu: Callable[[wx.Menu], None]) -> None:
        raised_exc = None  # type: Optional[Exception]
        def PopupMenu(menu: wx.Menu, *args, **kwargs) -> bool:
            nonlocal raised_exc
            PopupMenu.called = True  # type: ignore[attr-defined]
            try:
                show_popup_menu(menu)
            except Exception as e:
                raised_exc = e
            return True
        PopupMenu.called = False  # type: ignore[attr-defined]
        with patch.object(self.tree, 'PopupMenu', PopupMenu):
            await self.right_click()
            assert PopupMenu.called  # type: ignore[attr-defined]
        if raised_exc is not None:
            raise raised_exc
    
    async def right_click(self) -> None:
        self.tree.ProcessEvent(wx.TreeEvent(wx.EVT_TREE_ITEM_RIGHT_CLICK.typeId, self.tree, self.id))
    
    # === Comparison ===
    
    def __eq__(self, other: object) -> bool:
        if not isinstance(other, TreeItem):
            return False
        if not (self.tree == other.tree):
            return False
        if TreeItem._USE_FAST_ID_COMPARISONS and not is_windows():
            # NOTE: wx.TreeItemId does not support equality comparison on Windows
            return self.id == other.id
        else:
            id_data = self._ItemData
            other_id_data = other._ItemData
            if id_data is None or other_id_data is None:
                raise TreeItemsIncomparableError('Cannot compare TreeItems lacking item data')
            return id_data is other_id_data
    
    def __hash__(self) -> int:
        if TreeItem._USE_FAST_ID_COMPARISONS and not is_windows():
            return hash(self.tree) ^ hash(self.id)
        else:
            id_data = self._ItemData
            if id_data is None:
                raise TreeItemsIncomparableError('Cannot hash TreeItem lacking item data')
            return hash(self.tree) ^ hash(id_data)


class TreeItemsIncomparableError(ValueError):
    pass


# ------------------------------------------------------------------------------
