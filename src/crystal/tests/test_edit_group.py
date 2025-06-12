from crystal.model import Project, ResourceGroup
from crystal.tests.util.controls import click_button, TreeItem
from crystal.tests.util.server import extracted_project
from crystal.tests.util.wait import (
    first_child_of_tree_item_is_not_loading_condition, is_enabled_condition,
    wait_for,
)
from crystal.tests.util.windows import NewGroupDialog, OpenOrCreateDialog
from crystal.util.wx_dialog import mocked_show_modal
from crystal.util.xos import is_windows
from unittest import skip
from unittest.mock import patch
import wx


async def test_can_edit_name_of_group() -> None:
    with extracted_project('testdata_xkcd.crystalproj.zip') as project_dirpath:
        comic_pattern = 'https://xkcd.com/#/'
        
        async with (await OpenOrCreateDialog.wait_for()).open(project_dirpath) as (mw, project):
            root_ti = TreeItem.GetRootItem(mw.entity_tree.window)
            
            home_ti = root_ti.GetFirstChild()
            assert home_ti is not None
            assert home_ti.Text.endswith('Home')
            
            home_ti.Expand()
            await wait_for(first_child_of_tree_item_is_not_loading_condition(home_ti))
            home_ti__comic_ti = home_ti.find_child(comic_pattern)
            assert home_ti__comic_ti.Text.endswith('Comics')
            
            comic_ti = root_ti.find_child(comic_pattern)
            assert comic_ti.Text.endswith('Comics')
            
            # Ensure can rename top-level ResourceGroupNode
            if True:
                comic_ti.SelectItem()
                
                assert mw.edit_button.Enabled
                click_button(mw.edit_button)
                ngd = await NewGroupDialog.wait_for()
                
                # 1. Ensure prepopulates correct information
                # 2. Test: Cannot edit URL pattern
                assert comic_pattern == ngd.pattern_field.Value
                assert 'Comics' == ngd.name_field.Value
                assert 'Home' == ngd.source
                assert not ngd.pattern_field.Enabled
                assert ngd.name_field.HasFocus  # default focused field
                
                ngd.name_field.Value = 'Comics2'
                await ngd.ok()
                comic_ti = root_ti.find_child(comic_pattern)
                assert comic_ti.Text.endswith('Comics2')
                
                # Ensure selection did not change
                assert comic_ti.IsSelected()
                
                # Ensure all copies of comic node have updated name
                assert home_ti.IsExpanded()
                home_ti__comic_ti = home_ti.find_child(comic_pattern)
                assert home_ti__comic_ti.Text.endswith('Comics2')
            
            # Ensure can rename nested GroupedLinkedResourcesNode
            if True:
                home_ti__comic_ti.SelectItem()
                
                if is_windows():
                    await wait_for(is_enabled_condition(mw.edit_button), timeout=.5)
                assert mw.edit_button.Enabled
                click_button(mw.edit_button)
                ngd = await NewGroupDialog.wait_for()
                
                # Ensure prepopulates correct information
                assert comic_pattern == ngd.pattern_field.Value
                assert 'Comics2' == ngd.name_field.Value
                
                ngd.name_field.Value = 'Comics'
                await ngd.ok()
                home_ti = root_ti.GetFirstChild()
                assert home_ti is not None
                
                # Ensure selection did not change
                assert home_ti.IsExpanded()
                home_ti__comic_ti = home_ti.find_child(comic_pattern)
                assert home_ti__comic_ti.IsSelected()
                
                # Ensure all copies of home node have updated name
                comic_ti = root_ti.find_child(comic_pattern)
                assert comic_ti.Text.endswith('Comics')
                assert home_ti__comic_ti.Text.endswith('Comics')


async def test_can_edit_source_of_group() -> None:
    with extracted_project('testdata_xkcd.crystalproj.zip') as project_dirpath:
        comic_pattern = 'https://xkcd.com/#/'
        first_comic_pattern = 'https://xkcd.com/1/'
        
        async with (await OpenOrCreateDialog.wait_for()).open(project_dirpath) as (mw, project):
            root_ti = TreeItem.GetRootItem(mw.entity_tree.window)
            comic_ti = root_ti.find_child(comic_pattern)
            comic_ti.SelectItem()
            
            # Ensure can edit source to be root resource
            if True:
                assert comic_ti.IsSelected()
                
                assert mw.edit_button.Enabled
                click_button(mw.edit_button)
                ngd = await NewGroupDialog.wait_for()
                assert 'Home' == ngd.source
                
                ngd.source = 'Atom Feed'
                await ngd.ok()
                
                click_button(mw.edit_button)
                ngd = await NewGroupDialog.wait_for()
                assert 'Atom Feed' == ngd.source
                await ngd.ok()
            
            # Ensure can edit source to be group
            if True:
                ResourceGroup(project, 'First Comic', first_comic_pattern)
                first_comic_ti = root_ti.find_child(first_comic_pattern)
                
                assert comic_ti.IsSelected()
                
                assert mw.edit_button.Enabled
                click_button(mw.edit_button)
                ngd = await NewGroupDialog.wait_for()
                assert 'Atom Feed' == ngd.source
                
                ngd.source = 'First Comic'
                await ngd.ok()
                
                click_button(mw.edit_button)
                ngd = await NewGroupDialog.wait_for()
                assert 'First Comic' == ngd.source
                await ngd.ok()
            
            # Ensure cannot edit source to be self
            if True:
                assert comic_ti.IsSelected()
                
                assert mw.edit_button.Enabled
                click_button(mw.edit_button)
                ngd = await NewGroupDialog.wait_for()
                assert 'First Comic' == ngd.source
                
                ngd.source = 'Comics'
                
                with patch(
                        'crystal.browser.new_group.ShowModal',
                        mocked_show_modal('cr-source-cycle-created', wx.ID_OK)
                        ) as show_modal_method:
                    click_button(ngd.ok_button)
                    assert 1 == show_modal_method.call_count
                
                await ngd.cancel()
            
            # Ensure cannot edit source to be group that would create cycle
            if True:
                first_comic_ti.SelectItem()
                
                assert mw.edit_button.Enabled
                click_button(mw.edit_button)
                ngd = await NewGroupDialog.wait_for()
                assert None == ngd.source
                
                ngd.source = 'Comics'
                
                with patch(
                        'crystal.browser.new_group.ShowModal',
                        mocked_show_modal('cr-source-cycle-created', wx.ID_OK)
                        ) as show_modal_method:
                    click_button(ngd.ok_button)
                    assert 1 == show_modal_method.call_count
                
                await ngd.cancel()


@skip('covered by: test_can_edit_name_of_group')
async def test_cannot_edit_url_pattern_of_group() -> None:
    pass


@skip('covered by: test_can_edit_source_of_group')
async def test_given_editing_group_when_select_self_as_source_and_press_save_then_shows_error_dialog() -> None:
    pass


@skip('covered by: test_can_edit_source_of_group')
async def test_given_editing_group_when_select_source_that_would_create_cycle_and_press_save_then_shows_error_dialog() -> None:
    pass
