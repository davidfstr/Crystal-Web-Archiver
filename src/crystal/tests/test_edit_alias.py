from crystal.model import Alias
from crystal.tests.util.asserts import assertEqual
from crystal.tests.util.windows import OpenOrCreateDialog
from crystal.util.controls import TreeItem


# ------------------------------------------------------------------------------
# Test: Edit

async def test_can_edit_target_url_and_is_external_of_alias() -> None:
    """Test that alias target_url_prefix and target_is_external can be modified and entity tree is updated."""
    async with (await OpenOrCreateDialog.wait_for()).create() as (mw, project):
        # Create an alias
        alias = Alias(
            project,
            'https://source.example.com/',
            'https://target1.example.com/',
            target_is_external=False
        )
        
        # Verify initial state
        assertEqual('https://target1.example.com/', alias.target_url_prefix)
        assertEqual(False, alias.target_is_external)
        
        # Modify target_url_prefix
        alias.target_url_prefix = 'https://target2.example.com/'
        
        # Verify change persisted
        assertEqual('https://target2.example.com/', alias.target_url_prefix)
        
        # Verify entity tree is updated
        root_ti = TreeItem.GetRootItem(mw.entity_tree.window)
        (alias_ti,) = root_ti.Children
        assertEqual(
            'https://source.example.com/** → https://target2.example.com/**',
            alias_ti.Text)
        
        # Modify target_is_external
        alias.target_is_external = True
        
        # Verify change persisted
        assertEqual(True, alias.target_is_external)
        
        # Verify entity tree is updated with globe icon
        root_ti = TreeItem.GetRootItem(mw.entity_tree.window)
        (alias_ti,) = root_ti.Children
        
        assertEqual(
            'https://source.example.com/** → 🌐 https://target2.example.com/**',
            alias_ti.Text)


async def test_cannot_edit_source_url_of_alias() -> None:
    """Test that source_url_prefix is read-only."""
    async with (await OpenOrCreateDialog.wait_for()).create() as (mw, project):
        # Create an alias
        alias = Alias(
            project,
            'https://source.example.com/',
            'https://target.example.com/',
        )
        
        # Verify source_url_prefix exists and can be read
        assertEqual('https://source.example.com/', alias.source_url_prefix)
        
        # Verify source_url_prefix cannot be modified
        try:
            alias.source_url_prefix = 'https://new-source.example.com/'  # type: ignore[misc]
        except AttributeError:
            pass  # expected
        else:
            assert False, 'Setting source_url_prefix should raise AttributeError'
