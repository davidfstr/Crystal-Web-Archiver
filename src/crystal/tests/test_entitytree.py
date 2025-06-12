from crystal.model import (
    DownloadErrorDict, Project, Resource, ResourceGroup, RootResource,
)
from crystal.tests.util.asserts import assertEqual, assertIn
from crystal.tests.util.controls import TreeItem
from crystal.tests.util.downloads import network_down
from crystal.tests.util.runner import bg_sleep
from crystal.tests.util.server import served_project
from crystal.tests.util.tasks import wait_for_download_to_start_and_finish
from crystal.tests.util.wait import (
    DEFAULT_WAIT_PERIOD, first_child_of_tree_item_is_not_loading_condition,
    wait_for,
)
from crystal.tests.util.windows import (
    MainWindow, MenuitemMissingError, OpenOrCreateDialog,
)
import locale
import os
import tempfile
from unittest import skip
import wx

# ------------------------------------------------------------------------------
# Test: EntityTree: Default Domain/Directory

async def test_given_resource_node_whose_path_is_slash_when_set_default_url_domain_to_it_then_node_displays_only_path() -> None:
    async with (await OpenOrCreateDialog.wait_for()).create() as (mw, project):
        rr = RootResource(project, '', Resource(project, 'https://neocities.org/'))
        
        root_ti = TreeItem.GetRootItem(mw.entity_tree.window)
        rrn = root_ti.find_child(rr.resource.url, project.default_url_prefix)
        
        assert rrn.Text != '/'
        await mw.entity_tree.set_default_domain_to_entity_at_tree_item(rrn)
        assert rrn.Text == '/'
        
        # test_given_resource_node_whose_path_is_slash_and_default_url_domain_matches_it_when_clear_default_url_domain_then_node_displays_full_url
        await mw.entity_tree.clear_default_domain_from_entity_at_tree_item(rrn)
        assert rrn.Text.startswith('https://neocities.org/')
        
        # test_given_resource_node_whose_path_is_slash_then_cannot_set_default_url_prefix_to_it
        try:
            await mw.entity_tree.set_default_directory_to_entity_at_tree_item(rrn)
        except MenuitemMissingError:
            pass
        else:
            raise AssertionError('Did not expect resource to offer option to: set_default_url_prefix')


@skip('covered by: test_given_resource_node_whose_path_is_slash_when_set_default_url_domain_to_it_then_node_displays_only_path')
async def test_given_resource_node_whose_path_is_slash_then_cannot_set_default_url_prefix_to_it() -> None:
    pass


@skip('covered by: test_given_resource_node_whose_path_is_slash_when_set_default_url_domain_to_it_then_node_displays_only_path')
async def test_given_resource_node_whose_path_is_slash_and_default_url_domain_matches_it_when_clear_default_url_domain_then_node_displays_full_url() -> None:
    pass


async def test_given_resource_node_whose_path_is_more_than_slash_when_set_default_url_domain_to_it_then_node_displays_only_path() -> None:
    async with (await OpenOrCreateDialog.wait_for()).create() as (mw, project):
        rr = RootResource(project, '', Resource(project, 'https://neocities.org/~distantskies/'))
        
        root_ti = TreeItem.GetRootItem(mw.entity_tree.window)
        rrn = root_ti.find_child(rr.resource.url, project.default_url_prefix)
        
        assert rrn.Text != '/~distantskies/'
        await mw.entity_tree.set_default_domain_to_entity_at_tree_item(rrn)
        assert rrn.Text == '/~distantskies/'
        
        # test_given_resource_node_whose_path_is_more_than_slash_and_default_url_domain_matches_it_when_clear_default_url_domain_then_node_displays_full_url
        await mw.entity_tree.clear_default_domain_from_entity_at_tree_item(rrn)
        assert rrn.Text.startswith('https://neocities.org/~distantskies/')
        
        # test_given_resource_node_whose_path_is_more_than_slash_when_set_default_url_prefix_to_it_then_node_displays_only_slash
        await mw.entity_tree.set_default_directory_to_entity_at_tree_item(rrn)
        assert rrn.Text == '/'
        
        # test_given_resource_node_whose_path_is_more_than_slash_and_default_url_prefix_matches_it_when_clear_default_url_prefix_then_node_displays_full_url
        await mw.entity_tree.clear_default_directory_from_entity_at_tree_item(rrn)
        assert rrn.Text.startswith('https://neocities.org/~distantskies/')


@skip('covered by: test_given_resource_node_whose_path_is_more_than_slash_when_set_default_url_domain_to_it_then_node_displays_only_path')
async def test_given_resource_node_whose_path_is_more_than_slash_when_set_default_url_prefix_to_it_then_node_displays_only_slash() -> None:
    pass


@skip('covered by: test_given_resource_node_whose_path_is_more_than_slash_when_set_default_url_domain_to_it_then_node_displays_only_path')
async def test_given_resource_node_whose_path_is_more_than_slash_and_default_url_domain_matches_it_when_clear_default_url_domain_then_node_displays_full_url() -> None:
    pass


@skip('covered by: test_given_resource_node_whose_path_is_more_than_slash_when_set_default_url_domain_to_it_then_node_displays_only_path')
async def test_given_resource_node_whose_path_is_more_than_slash_and_default_url_prefix_matches_it_when_clear_default_url_prefix_then_node_displays_full_url() -> None:
    pass


@skip('not yet automated')
async def test_given_resource_group_node_whose_path_is_slash_wildcard_when_set_default_url_domain_to_it_then_node_displays_only_path_pattern() -> None:
    pass


@skip('not yet automated')
async def test_given_resource_group_node_whose_path_is_slash_wildcard_then_cannot_set_default_url_prefix_to_it() -> None:
    pass


@skip('not yet automated')
async def test_given_resource_group_node_whose_path_is_slash_wildcard_and_default_url_domain_matches_it_when_clear_default_url_domain_then_node_displays_full_url_pattern() -> None:
    pass


@skip('not yet automated')
async def test_given_resource_group_node_whose_path_is_more_than_slash_literal_when_set_default_url_domain_to_it_then_node_displays_only_path_pattern() -> None:
    pass


@skip('not yet automated')
async def test_given_resource_group_node_whose_path_is_more_than_slash_literal_when_set_default_url_prefix_to_it_then_node_displays_only_slash() -> None:
    pass


@skip('not yet automated')
async def test_given_resource_group_node_whose_path_is_more_than_slash_literal_and_default_url_domain_matches_it_when_clear_default_url_domain_then_node_displays_full_url_pattern() -> None:
    pass


@skip('not yet automated')
async def test_given_resource_group_node_whose_path_is_more_than_slash_literal_and_default_url_prefix_matches_it_when_clear_default_url_prefix_then_node_displays_full_url_pattern() -> None:
    pass


async def test_when_selected_entity_changes_and_top_level_entity_menu_opened_then_appropriate_change_url_prefix_actions_shown() -> None:
    async with (await OpenOrCreateDialog.wait_for()).create() as (mw, project):
        root_ti = TreeItem.GetRootItem(mw.entity_tree.window)
        
        # Case: No entities selected
        selected_ti = TreeItem.GetSelection(mw.entity_tree.window)
        assert (selected_ti is None) or (selected_ti == root_ti)
        cup_actions = _change_url_prefix_actions_in_top_level_menu(mw)
        assertEqual(
            [
                ('Set As Default Domain', False),
            ],
            [
                (mi.ItemLabelText, mi.Enabled) for mi in 
                cup_actions
            ]
        )
        
        rr = RootResource(project, '', Resource(project, 'https://neocities.org/'))
        rr2 = RootResource(project, '', Resource(project, 'https://neocities.org/~distantskies/'))
        
        rrn = root_ti.find_child(rr.resource.url, project.default_url_prefix)
        rrn2 = root_ti.find_child(rr2.resource.url, project.default_url_prefix)
        
        # Case: URL with path / selected
        rrn.SelectItem()
        cup_actions = _change_url_prefix_actions_in_top_level_menu(mw)
        assertEqual(
            [
                ('Set As Default Domain', True),
            ],
            [
                (mi.ItemLabelText, mi.Enabled) for mi in 
                cup_actions
            ]
        )
        
        # Case: URL with path / selected; matches domain
        _select_change_url_prefix_action(mw, cup_actions[0])
        cup_actions = _change_url_prefix_actions_in_top_level_menu(mw)
        assertEqual(
            [
                ('Clear Default Domain', True),
            ],
            [
                (mi.ItemLabelText, mi.Enabled) for mi in 
                cup_actions
            ]
        )
        
        # Clear Default URL Domain/Prefix
        _select_change_url_prefix_action(mw, cup_actions[0])
        cup_actions = _change_url_prefix_actions_in_top_level_menu(mw)
        assertEqual(
            [
                ('Set As Default Domain', True),
            ],
            [
                (mi.ItemLabelText, mi.Enabled) for mi in 
                cup_actions
            ]
        )
        
        # Case: URL with path more than / selected
        rrn2.SelectItem()
        cup_actions = _change_url_prefix_actions_in_top_level_menu(mw)
        assertEqual(
            [
                ('Set As Default Domain', True),
                ('Set As Default Directory', True),
            ],
            [
                (mi.ItemLabelText, mi.Enabled) for mi in 
                cup_actions
            ]
        )
        
        # Case: URL with path more than / selected; matches domain
        _select_change_url_prefix_action(mw, cup_actions[0])
        cup_actions = _change_url_prefix_actions_in_top_level_menu(mw)
        assertEqual(
            [
                ('Clear Default Domain', True),
                ('Set As Default Directory', True),
            ],
            [
                (mi.ItemLabelText, mi.Enabled) for mi in 
                cup_actions
            ]
        )
        
        # Case: URL with path more than / selected; matches prefix
        _select_change_url_prefix_action(mw, cup_actions[1])
        cup_actions = _change_url_prefix_actions_in_top_level_menu(mw)
        assertEqual(
            [
                ('Set As Default Domain', True),
                ('Clear Default Directory', True),
            ],
            [
                (mi.ItemLabelText, mi.Enabled) for mi in 
                cup_actions
            ]
        )


def _change_url_prefix_actions_in_top_level_menu(mw: MainWindow) -> list[wx.MenuItem]:
    entity_menu = mw.entity_menu  # cache
    entity_menu.ProcessEvent(wx.MenuEvent(type=wx.EVT_MENU_OPEN.typeId))
    entity_menu.ProcessEvent(wx.MenuEvent(type=wx.EVT_MENU_CLOSE.typeId))
    cup_actions = [
        mi for mi in entity_menu.MenuItems
        if mi.ItemLabelText in [
            'Set As Default Domain',
            'Set As Default Directory',
            'Clear Default Domain',
            'Clear Default Directory',
        ]
    ]
    return cup_actions


def _select_change_url_prefix_action(mw: MainWindow, mi: wx.MenuItem) -> None:
    entity_menu = mw.entity_menu  # cache
    entity_menu.ProcessEvent(wx.MenuEvent(type=wx.EVT_MENU.typeId, id=mi.Id, menu=None))


# ------------------------------------------------------------------------------
# Test: EntityTree: Label Tooltips

async def test_when_hover_over_resource_node_label_then_tooltip_always_contains_full_url() -> None:
    # ...even if Default URL Prefix is set
    async with (await OpenOrCreateDialog.wait_for()).create() as (mw, project):
        rr = RootResource(project, '', Resource(project, 'https://neocities.org/'))
        
        root_ti = TreeItem.GetRootItem(mw.entity_tree.window)
        rrn = root_ti.find_child(rr.resource.url, project.default_url_prefix)
        
        assertIn('URL: https://neocities.org/', rrn.Tooltip('label') or '')
        await mw.entity_tree.set_default_domain_to_entity_at_tree_item(rrn)
        assertIn('URL: https://neocities.org/', rrn.Tooltip('label') or '')


async def test_when_hover_over_resource_group_node_label_then_tooltip_always_contains_full_url_pattern() -> None:
    # ...even if Default URL Prefix is set
    async with (await OpenOrCreateDialog.wait_for()).create() as (mw, project):
        Resource(project, 'https://xkcd.com/atom.xml')
        Resource(project, 'https://xkcd.com/rss.xml')
        rg = ResourceGroup(project, 'Feed', 'https://xkcd.com/*.xml')
        
        root_ti = TreeItem.GetRootItem(mw.entity_tree.window)
        rgn = root_ti.find_child(rg.url_pattern, project.default_url_prefix)
        
        assertIn('URL Pattern: https://xkcd.com/*.xml', rgn.Tooltip('label') or '')
        await mw.entity_tree.set_default_domain_to_entity_at_tree_item(rgn)
        assertIn('URL Pattern: https://xkcd.com/*.xml', rgn.Tooltip('label') or '')


# ------------------------------------------------------------------------------
# Test: RootNode

# (TODO: Add basic tests)


# ------------------------------------------------------------------------------
# Test: _ResourceNode

# (TODO: Add basic tests)


async def test_rn_with_error_child_retains_child_when_new_entity_added() -> None:
    with network_down():
        async with (await OpenOrCreateDialog.wait_for()).create() as (mw, project):
            root_ti = TreeItem.GetRootItem(mw.entity_tree.window)
            
            RootResource(project, 'Domain 1', Resource(project, 'https://nosuchdomain1.com/'))
            (rrn1_ti,) = root_ti.Children
            
            rrn1_ti.Expand()
            await wait_for(first_child_of_tree_item_is_not_loading_condition(rrn1_ti))
            assert rrn1_ti.GetFirstChild() is not None
            
            RootResource(project, 'Domain 2', Resource(project, 'https://nosuchdomain2.com/'))
            (rrn1_ti, rrn2_ti) = root_ti.Children
            assert rrn1_ti.GetFirstChild() is not None  # has failed in the past
            
            rrn2_ti.Expand()
            await wait_for(first_child_of_tree_item_is_not_loading_condition(rrn2_ti))
            assert rrn1_ti.GetFirstChild() is not None
            assert rrn2_ti.GetFirstChild() is not None


# ------------------------------------------------------------------------------
# Test: RootResourceNode

@skip('not yet automated')
async def test_rrn_icon_looks_like_anchor_and_has_correct_tooltip() -> None:
    pass


@skip('not yet automated')
async def test_rrn_title_shows_rr_name_and_url() -> None:
    pass


@skip('not yet automated')
async def test_rrn_does_not_load_children_until_initially_expanded() -> None:
    pass


@skip('not yet automated')
async def test_undownloaded_rrn_has_undownloaded_badge() -> None:
    pass


@skip('not yet automated')
async def test_downloaded_fresh_rrn_has_fresh_badge() -> None:
    pass


@skip('not yet automated')
async def test_downloaded_stale_rrn_has_stale_badge() -> None:
    pass


@skip('not yet automated')
async def test_downloaded_error_rrn_has_error_badge() -> None:
    pass


async def test_given_rr_is_not_downloaded_and_project_is_read_only_when_expand_rrn_then_shows_error_node() -> None:
    with served_project('testdata_xkcd.crystalproj.zip') as sp:
        home_url = sp.get_request_url('https://xkcd.com/')
        
        with tempfile.TemporaryDirectory(suffix='.crystalproj') as project_dirpath:
            # Create project
            async with (await OpenOrCreateDialog.wait_for()).create(project_dirpath) as (mw, project):
                # Create RootResource but don't download it
                r = Resource(project, home_url)
                RootResource(project, 'Home', r)
            
            # Reopen project as read-only
            async with (await OpenOrCreateDialog.wait_for()).open(project_dirpath, readonly=True) as (mw, project):
                root_ti = TreeItem.GetRootItem(mw.entity_tree.window)
                (home_ti,) = root_ti.Children
                
                # Expand RootResourceNode and ensure it has an _ErrorNode child
                home_ti.Expand()
                await wait_for(first_child_of_tree_item_is_not_loading_condition(home_ti))
                (error_ti,) = home_ti.Children
                assert (
                    'Cannot download: Project is read only' ==
                    error_ti.Text
                )


@skip('not yet automated')
async def test_given_rr_is_not_downloaded_and_disk_is_full_when_expand_rrn_then_shows_error_node() -> None:
    pass


@skip('not yet automated')
async def test_given_rr_is_not_downloaded_and_project_has_maximum_revisions_when_expand_rrn_then_shows_error_node() -> None:
    pass


async def test_given_rr_is_downloaded_and_is_error_when_expand_rrn_then_shows_error_node() -> None:
    with served_project('testdata_xkcd.crystalproj.zip') as sp:
        home_url = sp.get_request_url('https://xkcd.com/')
        
        async with (await OpenOrCreateDialog.wait_for()).create() as (mw, project):
            # Download revision
            with network_down():
                r = Resource(project, home_url)
                home_rr = RootResource(project, 'Home', r)
                revision_future = home_rr.download()
                while not revision_future.done():
                    await bg_sleep(DEFAULT_WAIT_PERIOD)
                # Wait for download to complete, including the trailing wait
                await wait_for_download_to_start_and_finish(mw.task_tree, immediate_finish_ok=True)
                
                rr = revision_future.result()
                assert DownloadErrorDict(
                    type='gaierror',
                    message='[Errno 8] nodename nor servname provided, or not known',
                ) == rr.error_dict
            
            root_ti = TreeItem.GetRootItem(mw.entity_tree.window)
            (home_ti,) = root_ti.Children
            
            # Expand RootResourceNode and ensure it has an _ErrorNode child
            home_ti.Expand()
            await wait_for(first_child_of_tree_item_is_not_loading_condition(home_ti))
            (error_ti,) = home_ti.Children
            assert (
                'Error downloading URL: gaierror: [Errno 8] nodename nor servname provided, or not known' ==
                error_ti.Text
            )


async def test_given_rr_is_downloaded_but_revision_body_missing_when_expand_rrn_then_shows_error_node_and_redownloads_rr() -> None:
    with served_project('testdata_xkcd.crystalproj.zip') as sp:
        home_url = sp.get_request_url('https://xkcd.com/')
        
        with tempfile.TemporaryDirectory(suffix='.crystalproj') as project_dirpath:
            # Download revision
            async with (await OpenOrCreateDialog.wait_for()).create(project_dirpath) as (mw, project):
                r = Resource(project, home_url)
                home_rr = RootResource(project, 'Home', r)
                revision_future = home_rr.download()
                while not revision_future.done():
                    await bg_sleep(DEFAULT_WAIT_PERIOD)
                
                rr = revision_future.result()
                rr_body_filepath = rr._body_filepath  # capture
            
            # Simulate loss of revision body file, perhaps due to an
            # incomplete copy of a .crystalproj from one disk to another
            # (perhaps because of bad blocks in the revision body file)
            os.remove(rr_body_filepath)
            
            async with (await OpenOrCreateDialog.wait_for()).open(project_dirpath) as (mw, project):
                root_ti = TreeItem.GetRootItem(mw.entity_tree.window)
                (home_ti,) = root_ti.Children
                
                # Expand RootResourceNode and ensure it has an _ErrorNode child
                # 
                # TODO: In the future, block on the redownload finishing
                #       and list the links in the redownloaded revision,
                #       WITHOUT needing to reopen the project later
                home_ti.Expand()
                await wait_for(first_child_of_tree_item_is_not_loading_condition(home_ti))
                (error_ti,) = home_ti.Children
                assert (
                    'Cannot list links: URL revision body is missing. Recommend delete and redownload.' ==
                    error_ti.Text
                )
                
                # Wait for redownload to complete
                await wait_for_download_to_start_and_finish(mw.task_tree, immediate_finish_ok=True)
                
                # Reexpand RootResourceNode and ensure the children are the same
                home_ti.Collapse()
                home_ti.Expand()
                await wait_for(first_child_of_tree_item_is_not_loading_condition(home_ti))
                (error_ti,) = home_ti.Children
                assert (
                    'Cannot list links: URL revision body is missing. Recommend delete and redownload.' ==
                    error_ti.Text
                )
            
            # Reopen same project
            async with (await OpenOrCreateDialog.wait_for()).open(project_dirpath) as (mw, project):
                root_ti = TreeItem.GetRootItem(mw.entity_tree.window)
                (home_ti,) = root_ti.Children
                
                # Expand RootResourceNode and ensure it now lists the links in
                # the redownloaded revision
                home_ti.Expand()
                await wait_for(
                    first_child_of_tree_item_is_not_loading_condition(home_ti),
                    timeout=3.0  # took 2.2s on Linux CI
                )
                children = home_ti.Children
                assert not (
                    len(children) >= 1 and 
                    'Cannot list links:' in children[0].Text
                )


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
        
        async with (await OpenOrCreateDialog.wait_for()).create() as (mw, project):
            # Create future group members
            for i in range(1, 1000+1):
                Resource(project, comic_pattern.replace('#', str(i)))
            
            # Create group
            ResourceGroup(project, 'Comic', comic_pattern)
            
            root_ti = TreeItem.GetRootItem(mw.entity_tree.window)
            
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
            def more_children_visible() -> bool | None:
                assert comic_group_ti is not None
                return (len(comic_group_ti.Children) > (100 + 1)) or None
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
            def more_children_visible() -> bool | None:
                assert comic_group_ti is not None
                return (len(comic_group_ti.Children) > (100 + 20 + 1)) or None
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
            
            async with (await OpenOrCreateDialog.wait_for()).create() as (mw, project):
                # Create future group members
                for i in range(1, 1200+1):
                    Resource(project, comic_pattern.replace('#', str(i)))
                
                # Create group
                ResourceGroup(project, 'Comic', comic_pattern)
                
                root_ti = TreeItem.GetRootItem(mw.entity_tree.window)
                
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
