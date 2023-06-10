from crystal.tests.util.controls import TreeItem
from crystal.tests.util.server import served_project
from crystal.tests.util.wait import (
    first_child_of_tree_item_is_not_loading_condition,
    wait_for,
)
from crystal.tests.util.windows import OpenOrCreateDialog
from crystal.model import Project, Resource, ResourceGroup
import locale
import os
import tempfile
from unittest import skip



# ------------------------------------------------------------------------------
# Test: RootNode

# (TODO: Add basic tests)


# ------------------------------------------------------------------------------
# Test: RootResourceNode

# (TODO: Add basic tests)


# ------------------------------------------------------------------------------
# Test: NormalResourceNode

# (TODO: Add basic tests)


# ------------------------------------------------------------------------------
# Test: LinkedResourceNode

# (TODO: Add basic tests)


# ------------------------------------------------------------------------------
# Test: ClusterNode

# (TODO: Add basic tests)


# ------------------------------------------------------------------------------
# Test: ResourceGroupNode

@skip('not yet automated')
async def test_rgn_icon_looks_like_folder_and_has_correct_tooltip() -> None:
    pass


@skip('not yet automated')
async def test_rgn_title_shows_group_name_and_url() -> None:
    pass


@skip('covered by: test_given_more_node_selected_when_expand_more_node_then_first_newly_visible_child_is_selected')
async def test_rgn_does_not_load_children_until_initially_expanded() -> None:
    pass


@skip('covered by: test_given_more_node_selected_when_expand_more_node_then_first_newly_visible_child_is_selected')
async def test_rgn_only_shows_first_100_children_initially_and_has_a_more_node_showing_how_many_remain() -> None:
    pass


@skip('covered by: test_given_more_node_selected_when_expand_more_node_then_first_newly_visible_child_is_selected')
async def test_when_expand_more_node_in_rgn_then_shows_20_more_children_and_a_new_more_node() -> None:
    pass


async def test_given_more_node_selected_when_expand_more_node_then_first_newly_visible_child_is_selected() -> None:
    with served_project('testdata_xkcd.crystalproj.zip') as sp:
        # Define URLs
        if True:
            comic_pattern = sp.get_request_url('https://xkcd.com/#/')
        
        with tempfile.TemporaryDirectory(suffix='.crystalproj') as project_dirpath:
            async with (await OpenOrCreateDialog.wait_for()).create(project_dirpath) as (mw, _):
                project = Project._last_opened_project
                assert project is not None
                
                # Create future group members
                for i in range(1, 1000+1):
                    Resource(project, comic_pattern.replace('#', str(i)))
                
                # Create group
                ResourceGroup(project, 'Comic', comic_pattern)
                
                root_ti = TreeItem.GetRootItem(mw.entity_tree.window)
                assert root_ti is not None
                
                comic_group_ti = root_ti.GetFirstChild()
                assert comic_group_ti is not None
                assert f'{comic_pattern} - Comic' == comic_group_ti.Text
                
                # Ensure first child of group (not displayed) is "Loading..."
                cg_child_ti = comic_group_ti.GetFirstChild()
                assert cg_child_ti is not None
                assert 'Loading...' == cg_child_ti.Text
                
                comic_group_ti.Expand()
                await wait_for(first_child_of_tree_item_is_not_loading_condition(comic_group_ti))
                
                # Ensure after expanding that first 100 children are shown initially,
                # followed by a "# more" node
                cg_children_tis = comic_group_ti.Children
                assert len(cg_children_tis) == 100 + 1
                for i in range(0, 100):
                    expected_comic_url = comic_pattern.replace('#', str(i + 1))
                    assert expected_comic_url == cg_children_tis[i].Text
                more_ti = cg_children_tis[-1]
                more_ti.ScrollTo()
                assert '900 more' == more_ti.Text
                
                more_ti.Expand()
                def more_children_visible() -> bool:
                    assert comic_group_ti is not None
                    return len(comic_group_ti.Children) > (100 + 1)
                await wait_for(more_children_visible)
                
                # Ensure after expanding "# more" node that another 20 children are shown
                cg_children_tis = comic_group_ti.Children
                assert len(cg_children_tis) == 100 + 20 + 1
                for i in range(0, 100 + 20):
                    expected_comic_url = comic_pattern.replace('#', str(i + 1))
                    assert expected_comic_url == cg_children_tis[i].Text
                more_ti = cg_children_tis[-1]
                more_ti.ScrollTo()
                assert '880 more' == more_ti.Text
                assert False == more_ti.IsExpanded()
                
                more_ti.SelectItem()
                
                more_ti.Expand()
                def more_children_visible() -> bool:
                    assert comic_group_ti is not None
                    return len(comic_group_ti.Children) > (100 + 20 + 1)
                await wait_for(more_children_visible)
                
                # Ensure after expanding a selected "# more" node that the
                # first newly visible child inherits the selection
                cg_children_tis = comic_group_ti.Children
                assert len(cg_children_tis) == 100 + 20 + 20 + 1
                node_in_position_of_old_more_node = cg_children_tis[100 + 20]
                assert True == node_in_position_of_old_more_node.IsSelected()


async def test_given_more_node_with_large_item_count_then_displays_count_with_commas() -> None:
    # Initialize locale based on LANG='en_US.UTF-8'
    old_lang = os.environ.get('LANG')
    os.environ['LANG'] = 'en_US.UTF-8'
    old_locale = locale.setlocale(locale.LC_ALL)
    locale.setlocale(locale.LC_ALL, '')
    try:
        with served_project('testdata_xkcd.crystalproj.zip') as sp:
            # Define URLs
            if True:
                comic_pattern = sp.get_request_url('https://xkcd.com/#/')
            
            with tempfile.TemporaryDirectory(suffix='.crystalproj') as project_dirpath:
                async with (await OpenOrCreateDialog.wait_for()).create(project_dirpath) as (mw, _):
                    project = Project._last_opened_project
                    assert project is not None
                    
                    # Create future group members
                    for i in range(1, 1200+1):
                        Resource(project, comic_pattern.replace('#', str(i)))
                    
                    # Create group
                    ResourceGroup(project, 'Comic', comic_pattern)
                    
                    root_ti = TreeItem.GetRootItem(mw.entity_tree.window)
                    assert root_ti is not None
                    
                    comic_group_ti = root_ti.GetFirstChild()
                    assert comic_group_ti is not None
                    assert f'{comic_pattern} - Comic' == comic_group_ti.Text
                    
                    comic_group_ti.Expand()
                    await wait_for(first_child_of_tree_item_is_not_loading_condition(comic_group_ti))
                    
                    cg_children_tis = comic_group_ti.Children
                    more_ti = cg_children_tis[-1]
                    more_ti.ScrollTo()
                    assert '1,100 more' == more_ti.Text
    finally:
        if old_lang is None:
            del os.environ['LANG']
        else:
            os.environ['LANG'] = old_lang
        locale.setlocale(locale.LC_ALL, old_locale)


# ------------------------------------------------------------------------------
# Test: GroupedLinkedResourcesNode

# (TODO: Add basic tests)


# ------------------------------------------------------------------------------
# Test: MorePlaceholderNode

# (TODO: Add basic tests)


# ------------------------------------------------------------------------------
