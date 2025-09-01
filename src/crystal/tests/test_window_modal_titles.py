"""
Tests for window-modal dialog titles that are visible on macOS but not on other platforms.

On macOS, window-modal dialogs appear as sheets without title bars, so we add a 
heading at the top of the dialog content to show the title. On other platforms,
the title appears in the window title bar and no additional heading is needed.
"""

from crystal.model import Resource, RootResource
from crystal.tests.util.controls import click_button
from crystal.tests.util.wait import wait_for, window_condition
from crystal.tests.util.windows import (
    NewGroupDialog, NewRootUrlDialog, OpenOrCreateDialog, PreferencesDialog, TreeItem,
)
from crystal.util.xos import is_mac_os
import wx


async def test_new_root_url_dialog_has_title_heading_on_macos_only() -> None:
    async with (await OpenOrCreateDialog.wait_for()).create() as (mw, project):
        # Open New Root URL dialog
        click_button(mw.new_root_url_button)
        nud = await NewRootUrlDialog.wait_for()
        try:
            title_heading = _find_static_text_with_label(nud._dialog, "New Root URL")
            if is_mac_os():
                assert title_heading is not None, "Title heading should be present on macOS"
            else:
                assert title_heading is None, "Title heading should not be present on non-macOS"
        finally:
            await nud.cancel()


async def test_edit_root_url_dialog_has_title_heading_on_macos_only() -> None:
    async with (await OpenOrCreateDialog.wait_for()).create() as (mw, project):
        # First create a root URL to edit
        RootResource(project, 'Test', Resource(project, 'https://example.com/'))
        
        # Wait for the root URL to appear in the tree
        root_ti = TreeItem.GetRootItem(mw.entity_tree.window)
        await wait_for(lambda: len(root_ti.Children) >= 1)
        
        # Select and edit the root URL
        test_ti = root_ti.Children[0]
        test_ti.SelectItem()
        click_button(mw.edit_button)
        
        nud = await NewRootUrlDialog.wait_for()
        try:
            title_heading = _find_static_text_with_label(nud._dialog, "Edit Root URL")
            if is_mac_os():
                assert title_heading is not None, "Title heading should be present on macOS"
            else:
                assert title_heading is None, "Title heading should not be present on non-macOS"
        finally:
            await nud.cancel()


async def test_new_group_dialog_has_title_heading_on_macos_only() -> None:
    async with (await OpenOrCreateDialog.wait_for()).create() as (mw, project):
        # Open New Group dialog
        click_button(mw.new_group_button)
        
        ngd = await NewGroupDialog.wait_for()
        try:
            title_heading = _find_static_text_with_label(ngd._dialog, "New Group")
            if is_mac_os():
                assert title_heading is not None, "Title heading should be present on macOS"
            else:
                assert title_heading is None, "Title heading should not be present on non-macOS"
        finally:
            await ngd.cancel()


async def test_preferences_dialog_has_title_heading_on_macos_only() -> None:
    async with (await OpenOrCreateDialog.wait_for()).create() as (mw, project):
        # Open Preferences dialog
        click_button(mw.preferences_button)

        pref = await PreferencesDialog.wait_for()
        try:
            title_heading = (
                _find_static_text_with_label(pref._dialog, "Preferences") or
                _find_static_text_with_label(pref._dialog, "Settings")
            )
            if is_mac_os():
                assert title_heading is not None, "Title heading should be present on macOS"
            else:
                assert title_heading is None, "Title heading should not be present on non-macOS"
        finally:
            await pref.cancel()


# === Utility ===

def _find_static_text_with_label(parent: wx.Window, label: str) -> wx.StaticText | None:
    """Find a wx.StaticText control within parent that has the specified label."""
    for child in parent.GetChildren():
        if isinstance(child, wx.StaticText) and child.GetLabel() == label:
            return child
        # Recursively search in child windows
        found = _find_static_text_with_label(child, label)
        if found:
            return found
    return None
