from crystal.model import Alias
from crystal.tests.util.asserts import assertEqual
from crystal.tests.util.subtests import SubtestsContext, awith_subtests
from crystal.tests.util.windows import MainWindow, NewAliasDialog, OpenOrCreateDialog
from crystal.util.controls import TreeItem, click_button
from unittest import skip


# ------------------------------------------------------------------------------
# Test: Edit

@awith_subtests
async def test_can_edit_target_url_and_is_external_of_alias(subtests: SubtestsContext) -> None:
    """Test that alias target_url_prefix and target_is_external can be modified and entity tree is updated."""
    with subtests.test(layer='model'):
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
            assertEqual('https://target2.example.com/', alias.target_url_prefix)

            # Verify entity tree is updated
            root_ti = TreeItem.GetRootItem(mw.entity_tree.window)
            (alias_ti,) = root_ti.Children
            assertEqual(
                'https://source.example.com/** → https://target2.example.com/**',
                alias_ti.Text)

            # Modify target_is_external
            alias.target_is_external = True
            assertEqual(True, alias.target_is_external)

            # Verify entity tree is updated with globe icon
            root_ti = TreeItem.GetRootItem(mw.entity_tree.window)
            (alias_ti,) = root_ti.Children
            assertEqual(
                'https://source.example.com/** → 🌐 https://target2.example.com/**',
                alias_ti.Text)

    with subtests.test(layer='ui'):
        async with (await OpenOrCreateDialog.wait_for()).create() as (mw, project):
            # Create an alias
            alias = Alias(
                project,
                'https://source.example.com/',
                'https://target1.example.com/',
                target_is_external=False
            )

            # Verify initial state in entity tree
            root_ti = TreeItem.GetRootItem(mw.entity_tree.window)
            (alias_ti,) = root_ti.Children
            assertEqual(
                'https://source.example.com/** → https://target1.example.com/**',
                alias_ti.Text)

            # Select and edit the alias
            alias_ti.SelectItem()
            assert mw.edit_button.Enabled
            click_button(mw.edit_button)
            nad = await NewAliasDialog.wait_for()

            # Verify the dialog is prepopulated correctly
            assertEqual('https://source.example.com/', nad.source_url_prefix_field.Value)
            assertEqual('https://target1.example.com/', nad.target_url_prefix_field.Value)
            assertEqual(False, nad.target_is_external_checkbox.Value)

            # Modify target_url_prefix
            nad.target_url_prefix_field.Value = 'https://target2.example.com/'
            await nad.ok()

            # Verify the model was updated
            assertEqual('https://target2.example.com/', alias.target_url_prefix)
            assertEqual(False, alias.target_is_external)

            # Verify entity tree is updated
            root_ti = TreeItem.GetRootItem(mw.entity_tree.window)
            (alias_ti,) = root_ti.Children
            assertEqual(
                'https://source.example.com/** → https://target2.example.com/**',
                alias_ti.Text)

            # Edit again to change target_is_external
            alias_ti.SelectItem()
            click_button(mw.edit_button)
            nad = await NewAliasDialog.wait_for()
            nad.target_is_external_checkbox.Value = True
            await nad.ok()

            # Verify the model was updated
            assertEqual(True, alias.target_is_external)

            # Verify entity tree is updated with globe icon
            root_ti = TreeItem.GetRootItem(mw.entity_tree.window)
            (alias_ti,) = root_ti.Children
            assertEqual(
                'https://source.example.com/** → 🌐 https://target2.example.com/**',
                alias_ti.Text)


@awith_subtests
async def test_cannot_edit_source_url_of_alias(subtests: SubtestsContext) -> None:
    """Test that source_url_prefix is read-only."""
    with subtests.test(layer='model'):
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
                raise AssertionError('Setting source_url_prefix should raise AttributeError')

    with subtests.test(layer='ui'):
        async with (await OpenOrCreateDialog.wait_for()).create() as (mw, project):
            # Create an alias
            alias = Alias(
                project,
                'https://source.example.com/',
                'https://target.example.com/',
            )

            # Select and edit the alias
            root_ti = TreeItem.GetRootItem(mw.entity_tree.window)
            (alias_ti,) = root_ti.Children
            alias_ti.SelectItem()

            assert mw.edit_button.Enabled
            click_button(mw.edit_button)
            nad = await NewAliasDialog.wait_for()

            # Verify source URL prefix field is disabled
            assertEqual('https://source.example.com/', nad.source_url_prefix_field.Value)
            assertEqual(False, nad.source_url_prefix_field.Enabled)

            # Verify target URL prefix field is enabled
            assertEqual('https://target.example.com/', nad.target_url_prefix_field.Value)
            assertEqual(True, nad.target_url_prefix_field.Enabled)

            await nad.cancel()


@skip('covered by: test_new_alias.test_when_press_copy_button_beside_url_input_then_copies_url')
async def test_can_copy_source_or_target_urls() -> None:
    pass
