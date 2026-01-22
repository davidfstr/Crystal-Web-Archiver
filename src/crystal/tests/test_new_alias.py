from crystal.model import Alias, Resource, RootResource
from crystal.tests.util.asserts import assertIn, assertEqual
from crystal.tests.util.server import MockHttpServer
from crystal.tests.util.subtests import awith_subtests, SubtestsContext
from crystal.tests.util.tasks import wait_for_download_task_to_start_and_finish
from crystal.tests.util.wait import first_child_of_tree_item_is_not_loading_condition, wait_for
from crystal.tests.util.windows import OpenOrCreateDialog
from crystal.util.controls import TreeItem
from textwrap import dedent


# ------------------------------------------------------------------------------
# Test: Create & Delete

@awith_subtests
async def test_can_create_alias(subtests: SubtestsContext) -> None:
    """Test that aliases can be created and appear in the entity tree."""
    async with (await OpenOrCreateDialog.wait_for()).create() as (mw, project):
        # Initially empty entity tree
        assert mw.entity_tree.is_empty_state_visible(), \
            'Should start in empty state'
        
        with subtests.test(target_is_external=False):
            # Create an alias with internal target
            alias = Alias(
                project,
                'https://www.example.com/',
                'https://example.com/',
                target_is_external=False
            )
            
            # Entity tree should now be visible (not empty)
            assert not mw.entity_tree.is_empty_state_visible(), \
                'Should enter non-empty state after adding alias'
            
            # Verify alias appears in entity tree
            root_ti = TreeItem.GetRootItem(mw.entity_tree.window)
            (alias_ti,) = root_ti.Children
            
            # Verify label format
            assertEqual(
                'https://www.example.com/** → https://example.com/**',
                alias_ti.Text)
            
            # Clean up for next subtest
            alias.delete()
        
        with subtests.test(target_is_external=True):
            # Create an alias with external target
            alias = Alias(
                project,
                'https://archive.example.com/',
                'https://live.example.com/',
                target_is_external=True
            )
            
            # Verify alias appears in entity tree with globe icon
            root_ti = TreeItem.GetRootItem(mw.entity_tree.window)
            (alias_ti,) = root_ti.Children
            
            # Verify label format includes globe icon
            assertEqual(
                'https://archive.example.com/** → 🌐 https://live.example.com/**',
                alias_ti.Text)


async def test_can_forget_alias() -> None:
    """Test that aliases can be deleted and entity tree is updated."""
    async with (await OpenOrCreateDialog.wait_for()).create() as (mw, project):
        # Create an alias
        alias = Alias(
            project,
            'https://temp.example.com/',
            'https://example.com/',
        )
        
        # Verify alias is in tree
        root_ti = TreeItem.GetRootItem(mw.entity_tree.window)
        assertEqual(1, len(root_ti.Children))
        
        # Delete the alias
        alias.delete()
        
        # Verify alias is removed from tree
        root_ti = TreeItem.GetRootItem(mw.entity_tree.window)
        assertEqual(0, len(root_ti.Children))
        
        # Entity tree should return to empty state
        assert mw.entity_tree.is_empty_state_visible(), \
            'Should return to empty state after deleting only entity'


async def test_resource_nodes_corresponding_to_external_urls_are_formatted_correctly() -> None:
    """
    Test that when a resource is aliased to an external URL,
    it displays with the globe icon (🌐) in the entity tree.
    """
    # Set up a mock server with HTML that links to a URL that will be aliased
    # to an external URL
    server = MockHttpServer({
        '/page.html': dict(
            status_code=200,
            headers=[('Content-Type', 'text/html')],
            content=dedent(
                """
                <!DOCTYPE html>
                <html>
                <head>
                    <link rel="stylesheet" href="/external/style.css">
                </head>
                <body>
                    <h1>Test Page</h1>
                </body>
                </html>
                """
            ).strip().encode('utf-8')
        ),
    })
    with server:
        async with (await OpenOrCreateDialog.wait_for()).create() as (mw, project):
            # Get URLs from server
            page_url = server.get_url('/page.html')
            external_css_url = server.get_url('/external/style.css')
            
            # Create an alias that rewrites /external/* to an external URL
            alias = Alias(
                project,
                server.get_url('/external/'),
                'https://cdn.example.com/',
                target_is_external=True
            )
            
            # Create and download a root resource that links to the external URL
            home_r = Resource(project, page_url)
            home_rr = RootResource(project, 'Home', home_r)
            
            async with wait_for_download_task_to_start_and_finish(project):
                home_r.download()
            
            root_ti = TreeItem.GetRootItem(mw.entity_tree.window)
            home_ti = root_ti.find_child(page_url, project.default_url_prefix)
            home_ti.Expand()
            await wait_for(first_child_of_tree_item_is_not_loading_condition(home_ti))
            
            (hidden_embedded_ti,) = home_ti.Children
            assertEqual('(Hidden: Embedded)', hidden_embedded_ti.Text)
            hidden_embedded_ti.Expand()
            await wait_for(first_child_of_tree_item_is_not_loading_condition(hidden_embedded_ti))
            
            (external_css_ti,) = hidden_embedded_ti.Children
            assertIn('🌐 https://cdn.example.com/style.css', external_css_ti.Text)
