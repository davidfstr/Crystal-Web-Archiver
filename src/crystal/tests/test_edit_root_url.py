from crystal.model import Project, ResourceGroup
from crystal.tests.util.controls import click_button, TreeItem
from crystal.tests.util.server import extracted_project
from crystal.tests.util.wait import (
    first_child_of_tree_item_is_not_loading_condition, wait_for,
)
from crystal.tests.util.windows import NewRootUrlDialog, OpenOrCreateDialog
from unittest import skip


async def test_can_edit_name_of_root_url() -> None:
    with extracted_project('testdata_xkcd.crystalproj.zip') as project_dirpath:
        home_url = 'https://xkcd.com/'
        home_g_pattern = 'https://xkcd.*/'
        assert home_g_pattern != home_url
        
        async with (await OpenOrCreateDialog.wait_for()).open(project_dirpath) as (mw, project):
            ResourceGroup(project, 'Home Group', home_g_pattern)
            
            root_ti = TreeItem.GetRootItem(mw.entity_tree.window)
            home_ti = root_ti.GetFirstChild()
            assert home_ti is not None
            assert home_ti.Text.endswith('Home')
            
            home_ti.Expand()
            await wait_for(first_child_of_tree_item_is_not_loading_condition(home_ti))
            home_ti__home_ti = home_ti.find_child(home_url)
            assert home_ti__home_ti.Text.endswith('Home')
            
            home_g_ti = root_ti.find_child(home_g_pattern)
            assert home_g_ti.Text.endswith('Home Group')
            
            home_g_ti.Expand()
            await wait_for(first_child_of_tree_item_is_not_loading_condition(home_g_ti))
            home_g_ti__home_ti = home_g_ti.find_child(home_url)
            assert home_g_ti__home_ti.Text.endswith('Home')
            
            # Ensure can rename top-level RootResourceNode
            if True:
                home_ti.SelectItem()
                
                assert mw.edit_button.Enabled
                click_button(mw.edit_button)
                nud = await NewRootUrlDialog.wait_for()
                
                # 1. Ensure prepopulates correct information
                # 2. Test: Cannot edit URL
                assert home_url == nud.url_field.Value
                assert 'Home' == nud.name_field.Value
                #assert None == ngd.source
                assert not nud.url_field.Enabled
                assert nud.name_field.HasFocus  # default focused field
                
                nud.name_field.Value = 'Home2'
                await nud.ok()
                home_ti = root_ti.GetFirstChild()
                assert home_ti is not None
                
                # Ensure selection did not change
                assert home_ti.IsSelected()
                assert home_ti.IsExpanded()
                
                # Ensure all copies of home node have updated name
                assert home_ti.Text.endswith('Home2')
                assert home_ti__home_ti.Text.endswith('Home2')
                assert home_g_ti__home_ti.Text.endswith('Home2')
            
            # Ensure can rename nested RootResourceNode
            if True:
                home_ti__home_ti.SelectItem()
                
                assert mw.edit_button.Enabled
                click_button(mw.edit_button)
                nud = await NewRootUrlDialog.wait_for()
                
                # Ensure prepopulates correct information
                assert home_url == nud.url_field.Value
                assert 'Home2' == nud.name_field.Value
                
                nud.name_field.Value = 'Home'
                await nud.ok()
                home_ti = root_ti.GetFirstChild()
                assert home_ti is not None
                
                # Ensure selection did not change
                assert home_ti.IsExpanded()
                assert home_ti__home_ti.IsSelected()
                
                # Ensure all copies of home node have updated name
                assert home_ti.Text.endswith('Home')
                assert home_ti__home_ti.Text.endswith('Home')
                assert home_g_ti__home_ti.Text.endswith('Home')


@skip('covered by: test_can_edit_name_of_root_url')
async def test_cannot_edit_url_of_root_url() -> None:
    pass
