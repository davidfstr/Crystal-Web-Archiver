"""
Tests the About Box displayed by AboutDialog.
"""

from crystal.browser import MainWindow as RealMainWindow
from crystal.model import Resource, RootResource
from crystal.util.controls import TreeItem
from crystal.tests.util.windows import OpenOrCreateDialog
from unittest import skip
import wx


@skip('covered by: test_can_open_about_with_menuitem')
async def test_can_open_about_box_from_application_menu_or_help_menu() -> None:
    pass


# macOS, Windows: Passes because dialog opened as window-modal
# Linux: Passes because dialog opened as app-modal
@skip('not yet automated')
async def test_cannot_open_multiple_about_boxes() -> None:
    pass


async def test_can_close_about_box_by_pressing_enter() -> None:
    async with (await OpenOrCreateDialog.wait_for()).create() as (mw, _):
        about_dialog = await mw.open_about_with_menuitem()
        await about_dialog.press_enter()


async def test_can_close_about_box_by_pressing_enter_given_entity_selected() -> None:
    async with (await OpenOrCreateDialog.wait_for()).create() as (mw, project):
        rmw = RealMainWindow._last_created
        assert rmw is not None
        
        # Create and select a RootResource in the Entity Tree
        home_rr = RootResource(project, 'Home', Resource(project, 'https://example.com/'))
        root_ti = TreeItem.GetRootItem(mw.entity_tree.window)
        (home_ti,) = root_ti.Children
        home_ti.SelectItem()
        
        # Locate the "Edit..." menuitem
        # (which can be activated by pressing Return)
        (edit_entity_mi,) = rmw._edit_action._menuitems
        assert edit_entity_mi.Accel.KeyCode == wx.WXK_RETURN
        
        assert edit_entity_mi.Enabled == True
        about_dialog = await mw.open_about_with_menuitem()
        assert edit_entity_mi.Enabled == False
        
        await about_dialog.press_enter()


@skip('not yet automated')
async def test_can_close_about_box_by_pressing_escape() -> None:
    pass


@skip('not yet automated')
async def test_about_box_looks_good_in_light_mode_and_dark_mode() -> None:
    pass


@skip('not yet automated')
async def test_about_box_updates_correctly_when_system_appearance_changes_between_light_and_dark_mode() -> None:
    pass
