"""
Unit tests for crystal.ui.nav module.
"""

from crystal.ui.nav import _DEFAULT_DELETION_STYLE, inline_diff, Snapshot, SnapshotDiff 
import pytest
import re


# === Helper Functions ===

def make_snapshot(
        desc: str,
        children: list[Snapshot] | None = None,
        path: str = 'T',
        query: str = '',
        accessor: str = 'I',
        peer_obj: object | None = None,
        children_elided: bool = False,
        ) -> Snapshot:
    """Helper to create a Snapshot for testing."""
    return Snapshot(
        peer_description=desc,
        children=children or [],
        path=path,
        query=query,
        peer_accessor=accessor,
        peer_obj=peer_obj,
        children_elided=children_elided,
    )


# === Tests for inline_diff ===

class TestInlineDiff:
    """Tests for the inline_diff() function."""
    
    def test_identical_strings_return_unchanged(self) -> None:
        """Test that identical strings return without any diff markers."""
        result = inline_diff('hello', 'hello')
        assert result == 'hello'
    
    def test_completely_different_strings(self) -> None:
        """Test that completely different strings show as one change."""
        result = inline_diff('abc', 'xyz')
        assert result == '{abc→xyz}'
    
    def test_numeric_change(self) -> None:
        """Test that numeric changes are marked correctly."""
        result = inline_diff('27 of 100', '31 of 100')
        assert result == '{27→31} of 100'
    
    def test_deletion(self) -> None:
        """Test that deletions are marked with empty new value."""
        result = inline_diff('hello world', 'hello')
        assert '{' in result and '→}' in result
    
    def test_insertion(self) -> None:
        """Test that insertions are marked with empty old value."""
        result = inline_diff('hello', 'hello world')
        assert '{→' in result and '}' in result
    
    def test_empty_strings(self) -> None:
        """Test edge case with empty strings."""
        assert inline_diff('', '') == ''
        result_add = inline_diff('', 'text')
        assert '{→text}' == result_add
        result_del = inline_diff('text', '')
        assert '{text→}' == result_del
    
    def test_time_string_change(self) -> None:
        """Test that time strings remain as single tokens."""
        result = inline_diff('2:18:01', '2:19:18')
        assert result == '{2:18:01→2:19:18}'
    
    def test_word_replacement(self) -> None:
        """Test that whole words are replaced without splitting."""
        result = inline_diff('Downloading', 'Complete')
        assert result == '{Downloading→Complete}'
    
    def test_comma_separated_numbers(self) -> None:
        """Test that comma-separated numbers remain as single tokens."""
        result = inline_diff('2,310', '2,307')
        assert result == '{2,310→2,307}'
    
    def test_mixed_time_in_sentence(self) -> None:
        """Test time changes within a larger sentence."""
        result = inline_diff(
            '2:18:01 remaining (3.43s/item)',
            '2:19:18 remaining (3.47s/item)'
        )
        assert result == '{2:18:01→2:19:18} remaining ({3.43→3.47}s/item)'
    
    def test_status_word_change_in_sentence(self) -> None:
        """Test status word changes within a larger sentence."""
        result = inline_diff(
            'Downloading: https://example.com -- Downloading',
            'Downloading: https://example.com -- Complete'
        )
        assert result == 'Downloading: https://example.com -- {Downloading→Complete}'
    
    def test_comma_number_in_context(self) -> None:
        """Test comma-separated numbers in descriptive text."""
        result = inline_diff('— 📄 2,310 more', '— 📄 2,307 more')
        assert result == '— 📄 {2,310→2,307} more'
    
    def test_mixed_digits_letters_and_symbols(self) -> None:
        """Test complex string with mixed token types."""
        result = inline_diff('Item 27 (status: OK)', 'Item 30 (status: DONE)')
        assert result == 'Item {27→30} (status: {OK→DONE})'


# === Tests for Snapshot ===

class TestSnapshot:
    """Tests for the Snapshot class."""
    
    def test_can_create_basic_snapshot(self) -> None:
        """Test that a basic snapshot can be created."""
        snap = make_snapshot('Test Node')
        assert snap._peer_description == 'Test Node'
        assert snap._children == []
        assert snap._path == 'T'
    
    def test_can_create_snapshot_with_children(self) -> None:
        """Test that a snapshot can have children."""
        parent = make_snapshot('Parent', children=[
            child1 := make_snapshot('Child 1', path='T[0]'),
            child2 := make_snapshot('Child 2', path='T[1]')
        ])
        
        assert len(parent._children) == 2
        assert parent._children[0]._peer_description == 'Child 1'
        assert parent._children[1]._peer_description == 'Child 2'
    
    def test_can_create_snapshot_with_peer_obj(self) -> None:
        """Test that a snapshot can store a peer_obj for identity matching."""
        peer_obj = object()
        snap = make_snapshot('Node', peer_obj=peer_obj)
        assert snap._peer_obj is peer_obj
    
    def test_repr_shows_description(self) -> None:
        """Test that repr() includes the node description."""
        snap = make_snapshot('Test Description', path='T', accessor='I')
        result = repr(snap)
        assert 'Test Description' in result


# === Tests for SnapshotDiff ===

class TestSnapshotDiffBasics:
    """Tests for the SnapshotDiff class."""
    
    def test_no_changes_returns_empty_diff(self) -> None:
        """Test that comparing identical snapshots shows no changes."""
        snap = make_snapshot('Node', peer_obj=object())
        diff = Snapshot.diff(snap, snap)
        
        assert isinstance(diff, SnapshotDiff)
        assert not bool(diff)  # Empty diff is falsy
        assert '(no changes)' in repr(diff)
    
    def test_root_description_change(self) -> None:
        """Test that a change in root description is detected."""
        peer_obj = object()
        old = make_snapshot('Old Description', peer_obj=peer_obj)
        new = make_snapshot('New Description', peer_obj=peer_obj)
        
        diff = Snapshot.diff(old, new)
        
        assert bool(diff)  # Has changes
        diff_repr = repr(diff)
        assert 'S ~' in diff_repr
        assert '{Old→New}' in diff_repr
    
    def test_child_added(self) -> None:
        """Test that adding a child is detected."""
        parent_peer = object()
        child_peer = object()
        
        old = make_snapshot('Parent', children=[
            # (none)
        ], peer_obj=parent_peer)
        new = make_snapshot('Parent', children=[
            make_snapshot('New Child', path='T[0]', peer_obj=child_peer)
        ], peer_obj=parent_peer)
        
        diff = Snapshot.diff(old, new)
        
        assert bool(diff)
        diff_repr = repr(diff)
        assert 'S[0] +' in diff_repr
        assert 'New Child' in diff_repr
    
    def test_child_removed(self) -> None:
        """Test that removing a child is detected."""
        parent_peer = object()
        child_peer = object()
        
        old = make_snapshot('Parent', children=[
            make_snapshot('Old Child', path='T[0]', peer_obj=child_peer)
        ], peer_obj=parent_peer)
        new = make_snapshot('Parent', children=[
            # (none)
        ], peer_obj=parent_peer)
        
        diff = Snapshot.diff(old, new)
        
        assert bool(diff)
        diff_repr = repr(diff)
        assert 'S[0] -' in diff_repr
        assert 'Old Child' in diff_repr
    
    def test_child_description_modified(self) -> None:
        """Test that a change in child description is detected."""
        parent_peer = object()
        child_peer = object()
        
        old = make_snapshot('Parent', children=[
            make_snapshot('Child v1', path='T[0]', peer_obj=child_peer)
        ], peer_obj=parent_peer)
        new = make_snapshot('Parent', children=[
            make_snapshot('Child v2', path='T[0]', peer_obj=child_peer)
        ], peer_obj=parent_peer)
        
        diff = Snapshot.diff(old, new)
        
        assert bool(diff)
        diff_repr = repr(diff)
        assert '# S := T[0]' in diff_repr
        assert 'S ~' in diff_repr
        assert 'Child' in diff_repr
    
    def test_child_moved_without_modification(self) -> None:
        """Test that a child moving positions (but not changing) is detected."""
        parent_peer = object()
        child1_peer = object()
        child2_peer = object()
        
        old = make_snapshot('Parent', children=[
            make_snapshot('Other Child', path='T[0]', peer_obj=child2_peer),
            make_snapshot('Moved Child', path='T[1]', peer_obj=child1_peer),
        ], peer_obj=parent_peer)
        new = make_snapshot('Parent', children=[
            make_snapshot('Moved Child', path='T[0]', peer_obj=child1_peer),
            make_snapshot('Other Child', path='T[1]', peer_obj=child2_peer),
        ], peer_obj=parent_peer)
        
        diff = Snapshot.diff(old, new)
        
        assert bool(diff)
        diff_repr = repr(diff)
        # Should show index change
        assert '0→1' in diff_repr
        assert '1→0' in diff_repr
        assert 'Moved Child' in diff_repr
    
    def test_multiple_children_modified(self) -> None:
        """Test that multiple child modifications are all reported."""
        parent_peer = object()
        child1_peer = object()
        child2_peer = object()
        
        old = make_snapshot('Parent', children=[
            make_snapshot('Child 1 v1', path='T[0]', peer_obj=child1_peer),
            make_snapshot('Child 2 v1', path='T[1]', peer_obj=child2_peer),
        ], peer_obj=parent_peer)
        new = make_snapshot('Parent', children=[
            make_snapshot('Child 1 v2', path='T[0]', peer_obj=child1_peer),
            make_snapshot('Child 2 v2', path='T[1]', peer_obj=child2_peer),
        ], peer_obj=parent_peer)
        
        diff = Snapshot.diff(old, new)
        
        assert bool(diff)
        diff_repr = repr(diff)
        assert 'S[0] ~' in diff_repr
        assert 'S[1] ~' in diff_repr
        assert 'Child 1' in diff_repr
        assert 'Child 2' in diff_repr
    
    def test_nested_changes(self) -> None:
        """Test that changes deep in the tree are detected."""
        root_peer = object()
        parent_peer = object()
        grandchild_peer = object()
        
        old = make_snapshot('Root', children=[
            make_snapshot('Parent', children=[
                make_snapshot('Grandchild v1', path='T[0][0]', peer_obj=grandchild_peer)
            ], path='T[0]', peer_obj=parent_peer)
        ], peer_obj=root_peer)
        new = make_snapshot('Root', children=[
            make_snapshot('Parent', children=[
                make_snapshot('Grandchild v2', path='T[0][0]', peer_obj=grandchild_peer)
            ], path='T[0]', peer_obj=parent_peer)
        ], peer_obj=root_peer)
        
        diff = Snapshot.diff(old, new)
        
        assert bool(diff)
        diff_repr = repr(diff)
        assert '# S := T[0][0]' in diff_repr
        assert 'S ~' in diff_repr
        assert 'Grandchild' in diff_repr
    
    def test_mixed_operations(self) -> None:
        """Test a complex scenario with additions, removals, and modifications."""
        parent_peer = object()
        keep_peer = object()
        remove_peer = object()
        modify_peer = object()
        add_peer = object()
        
        old = make_snapshot('Parent', children=[
            make_snapshot('Keep', path='T[0]', peer_obj=keep_peer),
            make_snapshot('Remove', path='T[1]', peer_obj=remove_peer),
            make_snapshot('Modify v1', path='T[2]', peer_obj=modify_peer),
        ], peer_obj=parent_peer)
        new = make_snapshot('Parent', children=[
            make_snapshot('Keep', path='T[0]', peer_obj=keep_peer),
            make_snapshot('Modify v2', path='T[1]', peer_obj=modify_peer),
            make_snapshot('Add', path='T[2]', peer_obj=add_peer),
        ], peer_obj=parent_peer)
        
        diff = Snapshot.diff(old, new)
        
        assert bool(diff)
        diff_repr = repr(diff)
        assert 'Remove' in diff_repr
        assert 'Modify' in diff_repr
        assert 'Add' in diff_repr
        assert '-' in diff_repr  # deletion
        assert '+' in diff_repr  # addition
        assert '~' in diff_repr  # modification
    
    def test_added_node_with_descendents_shows_all_descendents(self) -> None:
        """Test that adding a node with descendents displays all of them."""
        parent_peer = object()
        new_parent_peer = object()
        new_child1_peer = object()
        new_child2_peer = object()
        new_grandchild_peer = object()
        
        old = make_snapshot('Root', children=[
            # (empty)
        ], peer_obj=parent_peer)
        new = make_snapshot('Root', children=[
            make_snapshot('New Parent', children=[
                make_snapshot('New Child 1', children=[
                    make_snapshot('New Grandchild', path='T[0][0][0]', peer_obj=new_grandchild_peer)
                ], path='T[0][0]', peer_obj=new_child1_peer),
                make_snapshot('New Child 2', path='T[0][1]', peer_obj=new_child2_peer),
            ], path='T[0]', peer_obj=new_parent_peer)
        ], peer_obj=parent_peer)
        
        diff = Snapshot.diff(old, new)
        
        assert bool(diff)
        diff_repr = repr(diff)
        # Should show the added parent
        assert 'S[0] + New Parent' in diff_repr
        # Should show all added descendents
        assert 'S[0][0] + New Child 1' in diff_repr
        assert 'S[0][0][0] + New Grandchild' in diff_repr
        assert 'S[0][1] + New Child 2' in diff_repr
    
    def test_removed_node_with_descendents_shows_all_descendents_if_deletion_style_is_full(self) -> None:
        """Test that removing a node with descendents displays all of them."""
        parent_peer = object()
        old_parent_peer = object()
        old_child1_peer = object()
        old_child2_peer = object()
        old_grandchild_peer = object()
        
        old = make_snapshot('Root', children=[
            make_snapshot('Old Parent', children=[
                make_snapshot('Old Child 1', children=[
                    make_snapshot('Old Grandchild', path='T[0][0][0]', peer_obj=old_grandchild_peer)
                ], path='T[0][0]', peer_obj=old_child1_peer),
                make_snapshot('Old Child 2', path='T[0][1]', peer_obj=old_child2_peer),
            ], path='T[0]', peer_obj=old_parent_peer)
        ], peer_obj=parent_peer)
        new = make_snapshot('Root', children=[
            # (empty)
        ], peer_obj=parent_peer)
        
        diff = Snapshot.diff(old, new, deletion_style='full')
        
        assert bool(diff)
        diff_repr = repr(diff)
        # Should show the removed parent
        assert 'S[0] - Old Parent' in diff_repr
        # Should show all removed descendents
        assert 'S[0][0] - Old Child 1' in diff_repr
        assert 'S[0][0][0] - Old Grandchild' in diff_repr
        assert 'S[0][1] - Old Child 2' in diff_repr
    
    def test_removed_node_with_descendents_shows_descendents_placeholder_by_default(self) -> None:
        """Test that removing a node with descendents displays all of them."""
        parent_peer = object()
        old_parent_peer = object()
        old_child1_peer = object()
        old_child2_peer = object()
        old_grandchild_peer = object()
        
        old = make_snapshot('Root', children=[
            make_snapshot('Old Parent', children=[
                make_snapshot('Old Child 1', children=[
                    make_snapshot('Old Grandchild', path='T[0][0][0]', peer_obj=old_grandchild_peer)
                ], path='T[0][0]', peer_obj=old_child1_peer),
                make_snapshot('Old Child 2', path='T[0][1]', peer_obj=old_child2_peer),
            ], path='T[0]', peer_obj=old_parent_peer)
        ], peer_obj=parent_peer)
        new = make_snapshot('Root', children=[
            # (empty)
        ], peer_obj=parent_peer)
        
        assert _DEFAULT_DELETION_STYLE == 'minimal'
        diff = Snapshot.diff(old, new)  # with _DEFAULT_DELETION_STYLE
        
        assert bool(diff)
        diff_repr = repr(diff)
        # Should show the removed parent
        assert 'S[0] - Old Parent' in diff_repr
        # Should show all descendents placeholder only
        assert 'S[0][0..1] - More(Count=2)' in diff_repr
        assert 'S[0][0][0] - Old Grandchild' not in diff_repr
    
    # TODO: Consider eliminating support for diff'ing Snapshots
    #       that lack a peer_obj
    def test_fallback_to_description_matching_when_no_peer_obj(self) -> None:
        """Test that matching falls back to description when peer_obj is None."""
        parent_peer = object()
        
        old = make_snapshot('Parent', children=[
            make_snapshot('Child A', path='T[0]', peer_obj=None),
            make_snapshot('Child B', path='T[1]', peer_obj=None),
        ], peer_obj=parent_peer)
        new = make_snapshot('Parent', children=[
            make_snapshot('Child A', path='T[0]', peer_obj=None),
            make_snapshot('Child B Modified', path='T[1]', peer_obj=None),
        ], peer_obj=parent_peer)
        
        diff = Snapshot.diff(old, new)
        
        assert bool(diff)
        # Child A should match by description, Child B should be seen as removed/added
        diff_repr = repr(diff)
        assert 'Child B' in diff_repr
    
    def test_when_children_elided_then_assumes_no_changes_in_diff(self) -> None:
        """Test that snapshots with children_elided=True don't report child changes."""
        parent_peer = object()
        child1_peer = object()
        child2_peer = object()
        
        # Old snapshot has children fully captured
        old = make_snapshot('Parent', children=[
            make_snapshot('Child 1', path='T[0]', peer_obj=child1_peer),
            make_snapshot('Child 2', path='T[1]', peer_obj=child2_peer),
        ], peer_obj=parent_peer)
        
        # New snapshot has children elided (not fully captured)
        new = make_snapshot('Parent', children=[
            # empty
        ], peer_obj=parent_peer, children_elided=True)
        
        diff = Snapshot.diff(old, new)
        
        # Should not report children as removed since new snapshot has elided children
        diff_repr = repr(diff)
        assert 'Child 1' not in diff_repr
        assert 'Child 2' not in diff_repr
        # Should show no changes
        assert '-' not in diff_repr
    
    def test_when_children_elided_then_assumes_no_changes_in_recursive_diff(self) -> None:
        """Test that children_elided on matched child nodes prevents recursive diff."""
        root_peer = object()
        parent_peer = object()
        grandchild_peer = object()
        
        # Old snapshot has full tree
        old = make_snapshot('Root', children=[
            make_snapshot('Parent', children=[
                make_snapshot('Grandchild', path='T[0][0]', peer_obj=grandchild_peer)
            ], path='T[0]', peer_obj=parent_peer)
        ], peer_obj=root_peer)
        
        # New snapshot has Parent with elided children
        new = make_snapshot('Root', children=[
            make_snapshot('Parent', children=[
                # empty
            ], path='T[0]', peer_obj=parent_peer, children_elided=True)
        ], peer_obj=root_peer)
        
        diff = Snapshot.diff(old, new)
        
        # Should not report Grandchild as removed
        diff_repr = repr(diff)
        assert 'Grandchild' not in diff_repr



class TestSnapshotDiffDeletionStyle:
    """
    Tests behavior for different values for deletion_style in diff-related APIs.
    
    Most tests focus on deletion_style='minimal' specifically,
    although there is some coverage for deletion_style='full' too.
    """
    
    def test_minimal_deletion_style_collapses_single_child(self) -> None:
        """Test that deletion_style='minimal' collapses a single deleted child."""
        parent_peer = object()
        child_peer = object()
        
        old = make_snapshot('Parent', children=[
            make_snapshot('Child', path='T[0]', peer_obj=child_peer)
        ], peer_obj=parent_peer)
        new = make_snapshot('Parent', children=[
            # (empty)
        ], peer_obj=parent_peer)
        
        diff = Snapshot.diff(old, new, deletion_style='minimal')
        
        assert bool(diff)
        diff_repr = repr(diff)
        # Should show the deleted child but not list it explicitly
        assert 'S[0] - Child' in diff_repr
        # There should be 1 newline: header + 1 deletion entry (no nested children to collapse)
        assert diff_repr.count('\n') == 1  # Header + 1 deletion entry
    
    def test_minimal_deletion_style_collapses_multiple_children(self) -> None:
        """Test that deletion_style='minimal' collapses multiple deleted children into More(Count=N)."""
        parent_peer = object()
        old_parent_peer = object()
        old_child1_peer = object()
        old_child2_peer = object()
        
        old = make_snapshot('Root', children=[
            make_snapshot('Old Parent', children=[
                make_snapshot('Old Child 1', path='T[0][0]', peer_obj=old_child1_peer),
                make_snapshot('Old Child 2', path='T[0][1]', peer_obj=old_child2_peer),
            ], path='T[0]', peer_obj=old_parent_peer)
        ], peer_obj=parent_peer)
        new = make_snapshot('Root', children=[
            # (empty)
        ], peer_obj=parent_peer)
        
        diff = Snapshot.diff(old, new, deletion_style='minimal')
        
        assert bool(diff)
        diff_repr = repr(diff)
        # Should show the deleted parent
        assert 'S[0] - Old Parent' in diff_repr
        # Should show collapsed children as More(Count=2)
        assert 'S[0][0..1] - More(Count=2)' in diff_repr
        # Should NOT show individual children
        assert 'Old Child 1' not in diff_repr
        assert 'Old Child 2' not in diff_repr
    
    def test_minimal_deletion_style_with_nested_descendents(self) -> None:
        """Test that deletion_style='minimal' collapses all nested descendents."""
        parent_peer = object()
        old_parent_peer = object()
        old_child1_peer = object()
        old_child2_peer = object()
        old_grandchild_peer = object()
        
        old = make_snapshot('Root', children=[
            make_snapshot('Old Parent', children=[
                make_snapshot('Old Child 1', children=[
                    make_snapshot('Old Grandchild', path='T[0][0][0]', peer_obj=old_grandchild_peer)
                ], path='T[0][0]', peer_obj=old_child1_peer),
                make_snapshot('Old Child 2', path='T[0][1]', peer_obj=old_child2_peer),
            ], path='T[0]', peer_obj=old_parent_peer)
        ], peer_obj=parent_peer)
        new = make_snapshot('Root', children=[
            # (empty)
        ], peer_obj=parent_peer)
        
        diff = Snapshot.diff(old, new, deletion_style='minimal')
        
        assert bool(diff)
        diff_repr = repr(diff)
        # Should show the deleted parent
        assert 'S[0] - Old Parent' in diff_repr
        # Should show collapsed children
        assert 'S[0][0..1] - More(Count=2)' in diff_repr
        # Should NOT show any descendents
        assert 'Old Child 1' not in diff_repr
        assert 'Old Child 2' not in diff_repr
        assert 'Old Grandchild' not in diff_repr
    
    def test_full_deletion_style_shows_all_descendents(self) -> None:
        """Test that deletion_style='full' (default) shows all deleted descendents."""
        parent_peer = object()
        old_parent_peer = object()
        old_child1_peer = object()
        old_child2_peer = object()
        old_grandchild_peer = object()
        
        old = make_snapshot('Root', children=[
            make_snapshot('Old Parent', children=[
                make_snapshot('Old Child 1', children=[
                    make_snapshot('Old Grandchild', path='T[0][0][0]', peer_obj=old_grandchild_peer)
                ], path='T[0][0]', peer_obj=old_child1_peer),
                make_snapshot('Old Child 2', path='T[0][1]', peer_obj=old_child2_peer),
            ], path='T[0]', peer_obj=old_parent_peer)
        ], peer_obj=parent_peer)
        new = make_snapshot('Root', children=[
            # (empty)
        ], peer_obj=parent_peer)
        
        # Use explicit deletion_style='full' to test that it works as before
        diff = Snapshot.diff(old, new, deletion_style='full')
        
        assert bool(diff)
        diff_repr = repr(diff)
        # Should show the removed parent
        assert 'S[0] - Old Parent' in diff_repr
        # Should show all removed descendents
        assert 'S[0][0] - Old Child 1' in diff_repr
        assert 'S[0][0][0] - Old Grandchild' in diff_repr
        assert 'S[0][1] - Old Child 2' in diff_repr
    
    def test_default_deletion_style_is_minimal(self) -> None:
        """Test that the default deletion_style is 'minimal'."""
        assert _DEFAULT_DELETION_STYLE == 'minimal'
    
    def test_minimal_deletion_style_does_not_affect_additions(self) -> None:
        """Test that deletion_style='minimal' does not affect how additions are displayed."""
        parent_peer = object()
        new_parent_peer = object()
        new_child1_peer = object()
        new_child2_peer = object()
        new_grandchild_peer = object()
        
        old = make_snapshot('Root', children=[
            # (empty)
        ], peer_obj=parent_peer)
        new = make_snapshot('Root', children=[
            make_snapshot('New Parent', children=[
                make_snapshot('New Child 1', children=[
                    make_snapshot('New Grandchild', path='T[0][0][0]', peer_obj=new_grandchild_peer)
                ], path='T[0][0]', peer_obj=new_child1_peer),
                make_snapshot('New Child 2', path='T[0][1]', peer_obj=new_child2_peer),
            ], path='T[0]', peer_obj=new_parent_peer)
        ], peer_obj=parent_peer)
        
        diff = Snapshot.diff(old, new, deletion_style='minimal')
        
        assert bool(diff)
        diff_repr = repr(diff)
        # Should show the added parent
        assert 'S[0] + New Parent' in diff_repr
        # Should show all added descendents (minimal only affects deletions)
        assert 'S[0][0] + New Child 1' in diff_repr
        assert 'S[0][0][0] + New Grandchild' in diff_repr
        assert 'S[0][1] + New Child 2' in diff_repr
    
    def test_minimal_deletion_style_with_mixed_changes(self) -> None:
        """Test that deletion_style='minimal' works correctly with mixed additions and deletions."""
        parent_peer = object()
        old_child_peer = object()
        new_child_peer = object()
        old_grandchild1_peer = object()
        old_grandchild2_peer = object()
        
        old = make_snapshot('Root', children=[
            make_snapshot('Old Child', children=[
                make_snapshot('Old Grandchild 1', path='T[0][0]', peer_obj=old_grandchild1_peer),
                make_snapshot('Old Grandchild 2', path='T[0][1]', peer_obj=old_grandchild2_peer),
            ], path='T[0]', peer_obj=old_child_peer)
        ], peer_obj=parent_peer)
        new = make_snapshot('Root', children=[
            make_snapshot('New Child', path='T[0]', peer_obj=new_child_peer)
        ], peer_obj=parent_peer)
        
        diff = Snapshot.diff(old, new, deletion_style='minimal')
        
        assert bool(diff)
        diff_repr = repr(diff)
        # Should show deletion with collapsed children
        assert 'S[0] - Old Child' in diff_repr
        assert 'S[0][0..1] - More(Count=2)' in diff_repr
        # Should show addition (at same index because peers don't match)
        assert 'S[0] + New Child' in diff_repr
        # Should NOT show individual grandchildren
        assert 'Old Grandchild 1' not in diff_repr
        assert 'Old Grandchild 2' not in diff_repr


class TestSnapshotDiffShiftedMoreSyntax:
    """
    Tests that contiguous ranges of moved children (with changed indexes)
    are reported as a single `[A1..B1 → A2..B2] = More(Count=#)` diff entry.
    """

    def test_range_merging_with_additions_interspersed(self) -> None:
        """
        Test that contiguous moved items are merged into a range even when
        additions are interspersed in the sorted output.
        
        Verifies that 2 or more contiguous moves are merged into a range.
        """
        # Create peers for identity matching
        item1 = object()
        item2 = object()
        item3 = object()
        
        old = make_snapshot(
            'Root',
            [
                make_snapshot('Item1', path='T[0]', peer_obj=item1),
                make_snapshot('Item2', path='T[1]', peer_obj=item2),
                make_snapshot('Item3', path='T[2]', peer_obj=item3),
            ],
        )
        
        new = make_snapshot(
            'Root',
            [
                make_snapshot('NewItem1', path='T[0]', peer_obj=object()),
                make_snapshot('Item1', path='T[1]', peer_obj=item1),
                make_snapshot('NewItem2', path='T[2]', peer_obj=object()),
                make_snapshot('Item2', path='T[3]', peer_obj=item2),
                make_snapshot('Item3', path='T[4]', peer_obj=item3),
            ],
        )
        
        expected_diff_repr_lines = [
            '# S := T',
            'S[0→1] = Item1',
            'S[0] + NewItem1',
            'S[1..2 → 3..4] = More(Count=2)',
            'S[2] + NewItem2',
        ]
        
        diff = Snapshot.diff(old, new)
        diff_repr = repr(diff)
        actual_diff_repr_lines = diff_repr.split('\n')
        assert actual_diff_repr_lines == expected_diff_repr_lines
    
    def test_range_merging_requires_contiguous_new_indices(self) -> None:
        """
        Test that range merging requires BOTH old and new indices to be contiguous.
        
        If items have contiguous old indices but gaps in new indices (due to
        additions), they should not all merge into a single range.
        """
        item1 = object()
        item2 = object()
        item3 = object()
        
        old = make_snapshot(
            'Root',
            [
                make_snapshot('Item1', path='T[0]', peer_obj=item1),
                make_snapshot('Item2', path='T[1]', peer_obj=item2),
                make_snapshot('Item3', path='T[2]', peer_obj=item3),
            ],
        )
        
        # Items move with a gap in the middle
        new = make_snapshot(
            'Root',
            [
                make_snapshot('Item1', path='T[0]', peer_obj=item1),  # Stays at 0
                make_snapshot('NewItem', path='T[1]', peer_obj=object()),  # New item creates gap
                make_snapshot('Item2', path='T[2]', peer_obj=item2),  # Moves 1→2
                make_snapshot('Item3', path='T[3]', peer_obj=item3),  # Moves 2→3
            ],
        )
        
        expected_diff_repr_lines = [
            '# S := T',
            'S[1..2 → 2..3] = More(Count=2)',  # Only Item2 and Item3 merge
            'S[1] + NewItem',
        ]
        
        diff = Snapshot.diff(old, new)
        diff_repr = repr(diff)
        actual_diff_repr_lines = diff_repr.split('\n')
        assert actual_diff_repr_lines == expected_diff_repr_lines
    
    def test_range_merging_single_item_not_merged(self) -> None:
        """
        Test that a single moved item is not turned into a range.
        """
        item1 = object()
        
        old = make_snapshot(
            'Root',
            [
                make_snapshot('Item1', path='T[0]', peer_obj=item1),
            ],
        )
        
        new = make_snapshot(
            'Root',
            [
                make_snapshot('NewItem', path='T[0]', peer_obj=object()),
                make_snapshot('Item1', path='T[1]', peer_obj=item1),
            ],
        )
        
        expected_diff_repr_lines = [
            '# S := T',
            'S[0→1] = Item1',  # Single item stays as individual entry
            'S[0] + NewItem',
        ]
        
        diff = Snapshot.diff(old, new)
        diff_repr = repr(diff)
        actual_diff_repr_lines = diff_repr.split('\n')
        assert actual_diff_repr_lines == expected_diff_repr_lines
    
    def test_range_merging_multiple_separate_ranges(self) -> None:
        """
        Test that multiple separate contiguous ranges in the same parent
        are each merged independently.
        """
        item1 = object()
        item2 = object()
        item3 = object()
        item4 = object()
        item5 = object()
        
        old = make_snapshot(
            'Root',
            [
                make_snapshot('Item1', path='T[0]', peer_obj=item1),
                make_snapshot('Item2', path='T[1]', peer_obj=item2),
                make_snapshot('Item3', path='T[2]', peer_obj=item3),
                make_snapshot('Item4', path='T[3]', peer_obj=item4),
                make_snapshot('Item5', path='T[4]', peer_obj=item5),
            ],
        )
        
        # Two separate ranges with a gap: Items 1-2 shift to 2-3, Items 4-5 shift to 6-7
        # Item3 stays at same position creating a break in the sequence
        new = make_snapshot(
            'Root',
            [
                make_snapshot('NewItem1', path='T[0]', peer_obj=object()),
                make_snapshot('NewItem2', path='T[1]', peer_obj=object()),
                make_snapshot('Item1', path='T[2]', peer_obj=item1),
                make_snapshot('Item2', path='T[3]', peer_obj=item2),
                make_snapshot('Item3', path='T[4]', peer_obj=item3),  # Stays at relative position, breaking continuity
                make_snapshot('NewItem3', path='T[5]', peer_obj=object()),
                make_snapshot('Item4', path='T[6]', peer_obj=item4),
                make_snapshot('Item5', path='T[7]', peer_obj=item5),
            ],
        )
        
        expected_diff_repr_lines = [
            '# S := T',
            'S[0..2 → 2..4] = More(Count=3)',  # Items 1-2-3
            'S[0] + NewItem1',
            'S[1] + NewItem2',
            'S[3..4 → 6..7] = More(Count=2)',  # Items 4-5
            'S[5] + NewItem3',
        ]
        
        diff = Snapshot.diff(old, new)
        diff_repr = repr(diff)
        actual_diff_repr_lines = diff_repr.split('\n')
        assert actual_diff_repr_lines == expected_diff_repr_lines
    
    def test_range_merging_only_moves_not_modifications(self) -> None:
        """
        Test that only unchanged moves (=) are merged into ranges,
        not modifications (~).
        """
        item1 = object()
        item2 = object()
        item3 = object()
        item4 = object()
        
        old = make_snapshot(
            'Root',
            [
                make_snapshot('Item1', path='T[0]', peer_obj=item1),
                make_snapshot('Item2-old', path='T[1]', peer_obj=item2),
                make_snapshot('Item3', path='T[2]', peer_obj=item3),
                make_snapshot('Item4', path='T[3]', peer_obj=item4),
            ],
        )
        
        new = make_snapshot(
            'Root',
            [
                make_snapshot('NewItem', path='T[0]', peer_obj=object()),  # Addition forces items to move
                make_snapshot('Item1', path='T[1]', peer_obj=item1),
                make_snapshot('Item2-new', path='T[2]', peer_obj=item2),  # Modified
                make_snapshot('Item3', path='T[3]', peer_obj=item3),
                make_snapshot('Item4', path='T[4]', peer_obj=item4),
            ],
        )
        
        expected_diff_repr_lines = [
            '# S := T',
            'S[0→1] = Item1',  # Not merged because Item2 is modified (breaks contiguity)
            'S[0] + NewItem',
            'S[1→2] ~ Item2-{old→new}',  # Modified, not a move
            'S[2..3 → 3..4] = More(Count=2)',  # Item3 and Item4 are merged
        ]
        
        diff = Snapshot.diff(old, new)
        diff_repr = repr(diff)
        actual_diff_repr_lines = diff_repr.split('\n')
        assert actual_diff_repr_lines == expected_diff_repr_lines


class TestSnapshotDiffAddAndDeleteMoreSyntax:
    """
    Test that contiguous ranges of >7 adds or deletes are collapsed such
    that exactly 7 items are displayed with a middle More(Count=#) item.
    """
    
    def test_long_runs_of_additions_are_collapsed(self) -> None:
        """Test that runs of > 7 additions are collapsed with More() entries."""
        parent_peer = object()
        
        # Create a snapshot with many additions (35 new children)
        old = make_snapshot('Parent', children=[], peer_obj=parent_peer)
        new_children = [
            make_snapshot(f'Child {i}', path=f'S[{i}]', peer_obj=object())
            for i in range(35)
        ]
        new = make_snapshot('Parent', children=new_children, peer_obj=parent_peer)
        
        diff = Snapshot.diff(old, new)
        
        assert bool(diff)
        diff_repr = repr(diff)
        
        # Should show first 3 additions
        assert 'S[0] + Child 0' in diff_repr
        assert 'S[1] + Child 1' in diff_repr
        assert 'S[2] + Child 2' in diff_repr
        
        # Should show collapsed middle section
        assert 'S[3..31] + More(Count=29)' in diff_repr
        
        # Should show last 3 additions
        assert 'S[32] + Child 32' in diff_repr
        assert 'S[33] + Child 33' in diff_repr
        assert 'S[34] + Child 34' in diff_repr
        
        # Should NOT show the collapsed entries individually
        assert 'S[15]' not in diff_repr  # middle entry should be collapsed
    
    def test_long_runs_of_deletions_are_collapsed(self) -> None:
        """Test that runs of > 7 deletions are collapsed with More() entries."""
        parent_peer = object()
        
        # Create a snapshot with many deletions (35 removed children)
        old_children = [
            make_snapshot(f'Child {i}', path=f'S[{i}]', peer_obj=object())
            for i in range(35)
        ]
        old = make_snapshot('Parent', children=old_children, peer_obj=parent_peer)
        new = make_snapshot('Parent', children=[], peer_obj=parent_peer)
        
        diff = Snapshot.diff(old, new)
        
        assert bool(diff)
        diff_repr = repr(diff)
        
        # Should show first 3 deletions
        assert 'S[0] - Child 0' in diff_repr
        assert 'S[1] - Child 1' in diff_repr
        assert 'S[2] - Child 2' in diff_repr
        
        # Should show collapsed middle section
        assert 'S[3..31] - More(Count=29)' in diff_repr
        
        # Should show last 3 deletions
        assert 'S[32] - Child 32' in diff_repr
        assert 'S[33] - Child 33' in diff_repr
        assert 'S[34] - Child 34' in diff_repr
        
        # Should NOT show the collapsed entries individually
        assert 'S[15]' not in diff_repr  # middle entry should be collapsed
    
    def test_short_runs_are_not_collapsed(self) -> None:
        """Test that runs of <= 7 additions/deletions are NOT collapsed."""
        parent_peer = object()
        
        # Create a snapshot with exactly 7 additions
        old = make_snapshot('Parent', children=[], peer_obj=parent_peer)
        new_children = [
            make_snapshot(f'Child {i}', path=f'S[{i}]', peer_obj=object())
            for i in range(7)
        ]
        new = make_snapshot('Parent', children=new_children, peer_obj=parent_peer)
        
        diff = Snapshot.diff(old, new)
        
        assert bool(diff)
        diff_repr = repr(diff)
        
        # Should show all 7 additions individually (no More() entry)
        for i in range(7):
            assert f'S[{i}] + Child {i}' in diff_repr
        
        # Should NOT have a More() entry
        assert 'More(Count=' not in diff_repr
    
    def test_non_contiguous_runs_not_collapsed_together(self) -> None:
        """Test that non-contiguous runs of additions are treated separately."""
        parent_peer = object()
        existing_child = object()
        
        # Create old with one child in the middle
        old = make_snapshot('Parent', children=[
            make_snapshot('Existing', path='T[5]', peer_obj=existing_child),
        ], peer_obj=parent_peer)
        
        # Create new with additions before and after the existing child
        # Each run has exactly 5 items, so neither should be collapsed (need > 7)
        new_children = []
        for i in range(11):
            if i == 5:
                new_children.append(make_snapshot('Existing', path=f'S[{i}]', peer_obj=existing_child))
            else:
                new_children.append(make_snapshot(f'Child {i}', path=f'S[{i}]', peer_obj=object()))
        new = make_snapshot('Parent', children=new_children, peer_obj=parent_peer)
        
        diff = Snapshot.diff(old, new)
        
        assert bool(diff)
        diff_repr = repr(diff)
        
        # The existing child should not be shown as added or removed
        # (it's matched by peer_obj)
        
        # There should be two separate runs: S[0-4] (5 items) and S[6-10] (5 items)
        # Neither is > 7, so neither should be collapsed
        for i in range(11):
            if i != 5:
                assert f'S[{i}] + Child {i}' in diff_repr
        
        # Should NOT have a More() entry since neither run is > 7
        assert 'More(Count=' not in diff_repr


class TestSnapshotDiffApi:
    """Tests for the SnapshotDiff API."""
    
    def test_old_property_returns_old_snapshot(self) -> None:
        """Test that diff.old returns the old snapshot."""
        old = make_snapshot('Old', peer_obj=object())
        new = make_snapshot('New', peer_obj=object())
        
        diff = Snapshot.diff(old, new)
        
        assert diff.old is old
    
    def test_new_property_returns_new_snapshot(self) -> None:
        """Test that diff.new returns the new snapshot."""
        old = make_snapshot('Old', peer_obj=object())
        new = make_snapshot('New', peer_obj=object())
        
        diff = Snapshot.diff(old, new)
        
        assert diff.new is new
    
    def test_sub_operator(self) -> None:
        """Test that the __sub__ operator works like Snapshot.diff()."""
        old = make_snapshot('Old', peer_obj=object())
        new = make_snapshot('New', peer_obj=object())
        
        diff_method = Snapshot.diff(old, new)
        diff_operator = new - old
        
        assert isinstance(diff_operator, SnapshotDiff)
        assert diff_operator.old is old
        assert diff_operator.new is new
        # Both should produce same repr
        assert repr(diff_method) == repr(diff_operator)
    
    def test_bool_true_when_changes_exist(self) -> None:
        """Test that bool(diff) is True when there are changes."""
        old = make_snapshot('Old', peer_obj=object())
        new = make_snapshot('New', peer_obj=object())
        
        diff = Snapshot.diff(old, new)
        
        assert bool(diff) is True
    
    def test_bool_false_when_no_changes(self) -> None:
        """Test that bool(diff) is False when there are no changes."""
        snap = make_snapshot('Same', peer_obj=object())
        
        diff = Snapshot.diff(snap, snap)
        
        assert bool(diff) is False
    
    def test_custom_name_parameter(self) -> None:
        """Test that the name parameter customizes the root symbol."""
        old = make_snapshot('Old', peer_obj=object())
        new = make_snapshot('New', peer_obj=object())
        
        diff = Snapshot.diff(old, new, name='CUSTOM')
        
        diff_repr = repr(diff)
        assert '# CUSTOM :=' in diff_repr
        assert 'CUSTOM ~' in diff_repr
    
    def test_when_try_to_navigate_diff_then_helpful_error_message_raised(self, subtests) -> None:
        root_peer = object()
        
        # Old snapshot: Dialog (minimal)
        old = make_snapshot(
            '',
            [
                make_snapshot(
                    "crystal.ui.dialog.BetterMessageDialog(Name='cr-open-or-create-project', Label='Select a Project')",
                    [
                        make_snapshot(
                            "wx.StaticText(Label='Create a new project or open an existing project?')",
                            path='T[0][0]',
                            peer_obj=object()
                        ),
                    ],
                    path='T[0]',
                    peer_obj=object()
                ),
            ],
            path='T',
            peer_obj=root_peer
        )
        
        # New snapshot: Main window (minimal)
        new = make_snapshot(
            '',
            [
                make_snapshot(
                    "wx.Frame(Name='cr-main-window', Label='Untitled Project')",
                    [
                        make_snapshot(
                            '_',
                            path='T[0][0]',
                            peer_obj=object()
                        ),
                    ],
                    path='T[0]',
                    peer_obj=object()
                ),
            ],
            path='T',
            peer_obj=root_peer
        )
        
        expected_diff_repr_lines = [
            '# S := T',
            "S[0] - crystal.ui.dialog.BetterMessageDialog(Name='cr-open-or-create-project', Label='Select a Project')",
            'S[0][0] - More(Count=1)',
            "S[0] + wx.Frame(Name='cr-main-window', Label='Untitled Project')",
            'S[0][0] + _',
        ]
        
        S = Snapshot.diff(old, new)
        with subtests.test(scenario='print diff'):
            diff_repr = repr(S)
            actual_diff_repr_lines = diff_repr.split('\n')
            assert actual_diff_repr_lines == expected_diff_repr_lines
        
        with subtests.test(scenario='try direct access'):
            with pytest.raises(ValueError, match=re.escape('S[0]... is ambiguous. Use S.new[0]... or S.old[0]... instead')):
                repr(S[0][0])  # type: ignore[index]
        
        with subtests.test(scenario='access new'):
            assert repr(S.new[0][0]) == '# T[0][0].I := _\n{}'
        
        with subtests.test(scenario='access old'):
            assert repr(S.old[0][0]) == "# T[0][0].I := wx.StaticText(Label='Create a new project or open an existing project?')\n{}"


class TestSnapshotDiffSorting:
    """Tests for the ordering of entries in SnapshotDiff output."""
    
    def test_entries_sorted_by_path(self) -> None:
        """Test that diff entries are sorted by path depth-first."""
        root_peer = object()
        child0_peer = object()
        child1_peer = object()
        grandchild_peer = object()
        
        old = make_snapshot('Root', children=[
            make_snapshot('Child 0 v1', path='T[0]', peer_obj=child0_peer),
            make_snapshot('Child 1', children=[
                make_snapshot('Grandchild v1', path='T[1][0]', peer_obj=grandchild_peer)
            ], path='T[1]', peer_obj=child1_peer),
        ], peer_obj=root_peer)
        new = make_snapshot('Root', children=[
            make_snapshot('Child 0 v2', path='T[0]', peer_obj=child0_peer),
            make_snapshot('Child 1', children=[
                make_snapshot('Grandchild v2', path='T[1][0]', peer_obj=grandchild_peer)
            ], path='T[1]', peer_obj=child1_peer),
        ], peer_obj=root_peer)
        
        diff = Snapshot.diff(old, new)
        diff_repr = repr(diff)
        
        # S[0] should appear before S[1][0]
        pos_child0 = diff_repr.find('S[0] ~')
        pos_grandchild = diff_repr.find('S[1][0] ~')
        assert pos_child0 < pos_grandchild
    
    def test_additions_come_after_other_operations_at_same_index(self) -> None:
        """Test that additions (+) are sorted after other operations at the same position."""
        parent_peer = object()
        old_child_peer = object()
        new_child_peer = object()
        
        old = make_snapshot('Parent', children=[
            make_snapshot('Old Child', path='T[0]', peer_obj=old_child_peer),
        ], peer_obj=parent_peer)
        new = make_snapshot('Parent', children=[
            make_snapshot('New Child', path='T[0]', peer_obj=new_child_peer),
        ], peer_obj=parent_peer)
        
        diff = Snapshot.diff(old, new)
        diff_repr = repr(diff)
        assert '# S := T' in diff_repr
        
        # Deletion should come before addition
        lines = diff_repr.split('\n')
        delete_line_idx = next(i for (i, line) in enumerate(lines) if 'S[0] -' in line)
        add_line_idx = next(i for (i, line) in enumerate(lines) if 'S[0] +' in line)
        assert delete_line_idx < add_line_idx


class TestSnapshotDiffGolden:
    """
    Golden tests for SnapshotDiff which verify the exact output format
    for various realistic scenarios.
    """
    
    def test_open_or_create_project_dialog_replaced_with_main_window(self, subtests) -> None:
        """
        Situation:
        - The "Open or Create Project" dialog is replaced with the main window,
          demonstrating that added and removed nodes display all their descendents.
        """
        # Create peer objects for identity matching
        root_peer = object()
        dialog_peer = object()
        dialog_text_peer = object()
        dialog_checkbox_peer = object()
        dialog_open_button_peer = object()
        dialog_new_button_peer = object()
        
        frame_peer = object()
        frame_child_peer = object()
        splitter_peer = object()
        entity_pane_peer = object()
        entity_pane_title_peer = object()
        entity_pane_empty_state_peer = object()
        entity_pane_empty_text_peer = object()
        entity_pane_empty_button_peer = object()
        entity_pane_add_button_peer = object()
        task_pane_peer = object()
        task_pane_title_peer = object()
        
        # Old snapshot: Dialog with children
        old = make_snapshot(
            '',
            [
                make_snapshot(
                    "crystal.ui.dialog.BetterMessageDialog(Name='cr-open-or-create-project', Label='Select a Project')",
                    [
                        make_snapshot(
                            "wx.StaticText(Label='Create a new project or open an existing project?')",
                            path='T[0][0]',
                            peer_obj=dialog_text_peer
                        ),
                        make_snapshot(
                            "wx.CheckBox(Name='cr-open-or-create-project__checkbox', Label='Open as &read only', Value=False)",
                            path='T[0][1]',
                            peer_obj=dialog_checkbox_peer
                        ),
                        make_snapshot(
                            "wx.Button(Id=wx.ID_NO, Label='&Open')",
                            path='T[0][2]',
                            peer_obj=dialog_open_button_peer
                        ),
                        make_snapshot(
                            "wx.Button(Id=wx.ID_YES, Label='&New Project')",
                            path='T[0][3]',
                            peer_obj=dialog_new_button_peer
                        ),
                    ],
                    path='T[0]',
                    peer_obj=dialog_peer
                ),
            ],
            path='T',
            peer_obj=root_peer
        )
        
        # New snapshot: Main window with nested hierarchy
        new = make_snapshot(
            '',
            [
                make_snapshot(
                    "wx.Frame(Name='cr-main-window', Label='Untitled Project')",
                    [
                        make_snapshot(
                            '_',
                            [
                                make_snapshot(
                                    'wx.SplitterWindow()',
                                    [
                                        make_snapshot(
                                            "wx.Panel(Name='cr-entity-pane')",
                                            [
                                                make_snapshot(
                                                    "wx.StaticText(Label='Root URLs and Groups')",
                                                    path='T[0][0][0][0][0]',
                                                    peer_obj=entity_pane_title_peer
                                                ),
                                                make_snapshot(
                                                    '_',
                                                    [
                                                        make_snapshot(
                                                            "wx.StaticText(Label='Download your first page by defining a root URL for the page.')",
                                                            path='T[0][0][0][0][1][0]',
                                                            peer_obj=entity_pane_empty_text_peer
                                                        ),
                                                        make_snapshot(
                                                            "wx.Button(Name='cr-empty-state-new-root-url-button', Label='New Root URL...')",
                                                            path='T[0][0][0][0][1][1]',
                                                            peer_obj=entity_pane_empty_button_peer
                                                        ),
                                                    ],
                                                    path='T[0][0][0][0][1]',
                                                    peer_obj=entity_pane_empty_state_peer
                                                ),
                                                make_snapshot(
                                                    "wx.Button(Name='cr-add-url-button', Label='New Root URL...')",
                                                    path='T[0][0][0][0][2]',
                                                    peer_obj=entity_pane_add_button_peer
                                                ),
                                            ],
                                            path='T[0][0][0][0]',
                                            peer_obj=entity_pane_peer
                                        ),
                                        make_snapshot(
                                            "wx.Panel(Name='cr-task-pane')",
                                            [
                                                make_snapshot(
                                                    "wx.StaticText(Label='Tasks')",
                                                    path='T[0][0][0][1][0]',
                                                    peer_obj=task_pane_title_peer
                                                ),
                                            ],
                                            path='T[0][0][0][1]',
                                            peer_obj=task_pane_peer
                                        ),
                                    ],
                                    path='T[0][0][0]',
                                    peer_obj=splitter_peer
                                ),
                            ],
                            path='T[0][0]',
                            peer_obj=frame_child_peer
                        ),
                    ],
                    path='T[0]',
                    peer_obj=frame_peer
                ),
            ],
            path='T',
            peer_obj=root_peer
        )
        
        expected_diff_repr_lines = [
            '# S := T',
            "S[0] - crystal.ui.dialog.BetterMessageDialog(Name='cr-open-or-create-project', Label='Select a Project')",
            'S[0][0..3] - More(Count=4)',
            "S[0] + wx.Frame(Name='cr-main-window', Label='Untitled Project')",
            'S[0][0] + _',
            'S[0][0][0] + wx.SplitterWindow()',
            "S[0][0][0][0] + wx.Panel(Name='cr-entity-pane')",
            "S[0][0][0][0][0] + wx.StaticText(Label='Root URLs and Groups')",
            'S[0][0][0][0][1] + _',
            "S[0][0][0][0][1][0] + wx.StaticText(Label='Download your first page by defining a root URL for the page.')",
            "S[0][0][0][0][1][1] + wx.Button(Name='cr-empty-state-new-root-url-button', Label='New Root URL...')",
            "S[0][0][0][0][2] + wx.Button(Name='cr-add-url-button', Label='New Root URL...')",
            "S[0][0][0][1] + wx.Panel(Name='cr-task-pane')",
            "S[0][0][0][1][0] + wx.StaticText(Label='Tasks')",
        ]
        
        with subtests.test(direction='forward'):
            diff = Snapshot.diff(old, new)
            diff_repr = repr(diff)
            actual_diff_repr_lines = diff_repr.split('\n')
            assert actual_diff_repr_lines == expected_diff_repr_lines
        
        expected_reverse_diff_repr_lines = [
            '# S := T',
            "S[0] - wx.Frame(Name='cr-main-window', Label='Untitled Project')",
            'S[0][0] - More(Count=1)',
            "S[0] + crystal.ui.dialog.BetterMessageDialog(Name='cr-open-or-create-project', Label='Select a Project')",
            "S[0][0] + wx.StaticText(Label='Create a new project or open an existing project?')",
            "S[0][1] + wx.CheckBox(Name='cr-open-or-create-project__checkbox', Label='Open as &read only', Value=False)",
            "S[0][2] + wx.Button(Id=wx.ID_NO, Label='&Open')",
            "S[0][3] + wx.Button(Id=wx.ID_YES, Label='&New Project')",
        ]
        
        with subtests.test(direction='reverse'):
            diff = Snapshot.diff(new, old)
            diff_repr = repr(diff)
            actual_diff_repr_lines = diff_repr.split('\n')
            assert actual_diff_repr_lines == expected_reverse_diff_repr_lines
    
    def test_new_root_url_dialog_or_other_modal_dialog_appears(self, subtests) -> None:
        """
        Situation:
        - A modal dialog appears over the main window.
        - The main window's children are elided in the new snapshot (not fully captured).
        - The diff should only show the dialog being added, not the main window's children being removed.
        
        This test verifies the fix for the issue where children_elided=True was treated
        as having zero children, causing spurious deletion entries in the diff.
        """
        # Create peer objects for identity matching
        root_peer = object()
        main_window_peer = object()
        frame_child_peer = object()
        splitter_peer = object()
        entity_pane_peer = object()
        entity_pane_title_peer = object()
        entity_pane_empty_state_peer = object()
        entity_pane_empty_text_peer = object()
        entity_pane_empty_button_peer = object()
        entity_pane_add_button_peer = object()
        task_pane_peer = object()
        task_pane_title_peer = object()
        
        dialog_peer = object()
        dialog_title_peer = object()
        dialog_url_label_peer = object()
        dialog_url_field_peer = object()
        dialog_cancel_button_peer = object()
        dialog_new_button_peer = object()
        
        # Old snapshot: Just main window with full children
        old = make_snapshot(
            '',
            [
                make_snapshot(
                    "wx.Frame(Name='cr-main-window', Label='Untitled Project')",
                    [
                        make_snapshot(
                            '_',
                            [
                                make_snapshot(
                                    'wx.SplitterWindow()',
                                    [
                                        make_snapshot(
                                            "wx.Panel(Name='cr-entity-pane')",
                                            [
                                                make_snapshot(
                                                    "wx.StaticText(Label='Root URLs and Groups')",
                                                    path='T[0][0][0][0][0]',
                                                    peer_obj=entity_pane_title_peer
                                                ),
                                                make_snapshot(
                                                    '_',
                                                    [
                                                        make_snapshot(
                                                            "wx.StaticText(Label='Download your first page by defining a root URL for the page.')",
                                                            path='T[0][0][0][0][1][0]',
                                                            peer_obj=entity_pane_empty_text_peer
                                                        ),
                                                        make_snapshot(
                                                            "wx.Button(Name='cr-empty-state-new-root-url-button', Label='New Root URL...')",
                                                            path='T[0][0][0][0][1][1]',
                                                            peer_obj=entity_pane_empty_button_peer
                                                        ),
                                                    ],
                                                    path='T[0][0][0][0][1]',
                                                    peer_obj=entity_pane_empty_state_peer
                                                ),
                                                make_snapshot(
                                                    "wx.Button(Name='cr-add-url-button', Label='New Root URL...')",
                                                    path='T[0][0][0][0][2]',
                                                    peer_obj=entity_pane_add_button_peer
                                                ),
                                            ],
                                            path='T[0][0][0][0]',
                                            peer_obj=entity_pane_peer
                                        ),
                                        make_snapshot(
                                            "wx.Panel(Name='cr-task-pane')",
                                            [
                                                make_snapshot(
                                                    "wx.StaticText(Label='Tasks')",
                                                    path='T[0][0][0][1][0]',
                                                    peer_obj=task_pane_title_peer
                                                ),
                                            ],
                                            path='T[0][0][0][1]',
                                            peer_obj=task_pane_peer
                                        ),
                                    ],
                                    path='T[0][0][0]',
                                    peer_obj=splitter_peer
                                ),
                            ],
                            path='T[0][0]',
                            peer_obj=frame_child_peer
                        ),
                    ],
                    path='T[0]',
                    peer_obj=main_window_peer
                ),
            ],
            path='T',
            peer_obj=root_peer
        )
        
        # New snapshot: Main window with children elided + new dialog
        new = make_snapshot(
            '',
            [
                make_snapshot(
                    "wx.Frame(Name='cr-main-window', Label='Untitled Project')",
                    [],  # Children elided - not fully captured
                    path='T[0]',
                    peer_obj=main_window_peer,
                    children_elided=True
                ),
                make_snapshot(
                    "wx.Dialog(IsModal=True, Name='cr-new-root-url-dialog', Label='New Root URL')",
                    [
                        make_snapshot(
                            "wx.StaticText(Label='New Root URL')",
                            path='T[1][0]',
                            peer_obj=dialog_title_peer
                        ),
                        make_snapshot(
                            "wx.StaticText(Label='URL:')",
                            path='T[1][1]',
                            peer_obj=dialog_url_label_peer
                        ),
                        make_snapshot(
                            "wx.TextCtrl(Name='cr-new-root-url-dialog__url-field', Value='')",
                            path='T[1][2]',
                            peer_obj=dialog_url_field_peer
                        ),
                        make_snapshot(
                            "wx.Button(Id=wx.ID_CANCEL, Label='&Cancel')",
                            path='T[1][3]',
                            peer_obj=dialog_cancel_button_peer
                        ),
                        make_snapshot(
                            "wx.Button(Id=wx.ID_NEW, Label='&New')",
                            path='T[1][4]',
                            peer_obj=dialog_new_button_peer
                        ),
                    ],
                    path='T[1]',
                    peer_obj=dialog_peer
                ),
            ],
            path='T',
            peer_obj=root_peer
        )
        
        # Expected:
        # - Only the dialog should be shown as added
        # - The main window's children should NOT be shown as removed
        #   because the new snapshot has children_elided=True
        expected_diff_repr_lines = [
            '# S := T',
            "S[1] + wx.Dialog(IsModal=True, Name='cr-new-root-url-dialog', Label='New Root URL')",
            "S[1][0] + wx.StaticText(Label='New Root URL')",
            "S[1][1] + wx.StaticText(Label='URL:')",
            "S[1][2] + wx.TextCtrl(Name='cr-new-root-url-dialog__url-field', Value='')",
            "S[1][3] + wx.Button(Id=wx.ID_CANCEL, Label='&Cancel')",
            "S[1][4] + wx.Button(Id=wx.ID_NEW, Label='&New')",
        ]
        
        with subtests.test(direction='forward'):
            diff = Snapshot.diff(old, new)
            diff_repr = repr(diff)
            actual_diff_repr_lines = diff_repr.split('\n')
            assert actual_diff_repr_lines == expected_diff_repr_lines
        
        # Expected reverse:
        # - Dialog removed, main window children NOT shown as added
        #   because the old snapshot still has children_elided=False on the new snapshot
        #   (but the new snapshot in the reverse diff has children_elided=True from old)
        expected_reverse_diff_repr_lines = [
            '# S := T',
            "S[1] - wx.Dialog(IsModal=True, Name='cr-new-root-url-dialog', Label='New Root URL')",
            'S[1][0..4] - More(Count=5)',
        ]
        
        with subtests.test(direction='reverse'):
            diff = Snapshot.diff(new, old)
            diff_repr = repr(diff)
            actual_diff_repr_lines = diff_repr.split('\n')
            assert actual_diff_repr_lines == expected_reverse_diff_repr_lines
    
    def test_expand_and_collapse_of_node_in_entity_tree(self, subtests) -> None:
        """
        Situation:
        - A root resource node in the entity tree is expanded,
          revealing its child URLs.
        """
        # Create peer objects for identity-based matching
        root_peer = object()
        root_0_peer = object()
        root_0_0_peer = object()
        root_0_1_peer = object()
        root_0_2_peer = object()
        root_0_3_peer = object()
        root_0_4_peer = object()
        root_0_5_peer = object()
        root_0_6_peer = object()
        root_0_7_peer = object()
        root_1_peer = object()
        root_2_peer = object()
        root_more_peer = object()
        root_5_peer = object()
        root_6_peer = object()
        root_7_peer = object()
        
        # Old snapshot: Root resource collapsed
        old = make_snapshot(
            'TreeItem(IsRoot=True, Visible=False)',
            [
                make_snapshot(
                    "TreeItem(👁='▶︎ 📁 /', IsSelected=True, IconTooltip='Fresh root URL')",
                    [],
                    path='T[0][0][0][0][1].Tree[0]',
                    peer_obj=root_0_peer
                ),
                make_snapshot(
                    "TreeItem(👁='▶︎ 📁 /1/', IconTooltip='Fresh root URL')",
                    [],
                    path='T[0][0][0][0][1].Tree[1]',
                    peer_obj=root_1_peer
                ),
                make_snapshot(
                    "TreeItem(👁='▶︎ 📁 /2/', IconTooltip='Fresh root URL')",
                    [],
                    path='T[0][0][0][0][1].Tree[2]',
                    peer_obj=root_2_peer
                ),
                make_snapshot(
                    'More(Count=2)',
                    [],
                    path='T[0][0][0][0][1].Tree[3:5]',
                    peer_obj=root_more_peer
                ),
                make_snapshot(
                    "TreeItem(👁='▶︎ 📁 /5/', IconTooltip='Fresh root URL')",
                    [],
                    path='T[0][0][0][0][1].Tree[5]',
                    peer_obj=root_5_peer
                ),
                make_snapshot(
                    "TreeItem(👁='▶︎ 📁 /6/', IconTooltip='Fresh root URL')",
                    [],
                    path='T[0][0][0][0][1].Tree[6]',
                    peer_obj=root_6_peer
                ),
                make_snapshot(
                    "TreeItem(👁='▶︎ 📁 /#/index.html - Comic', IconTooltip='Group')",
                    [],
                    path='T[0][0][0][0][1].Tree[7]',
                    peer_obj=root_7_peer
                ),
            ],
            path='T[0][0][0][0][1].Tree',
            peer_obj=root_peer
        )
        
        # New snapshot: Root resource expanded
        new = make_snapshot(
            'TreeItem(IsRoot=True, Visible=False)',
            [
                make_snapshot(
                    "TreeItem(👁='▼ 📂 /', IsSelected=True, IconTooltip='Fresh root URL')",
                    [
                        make_snapshot(
                            "TreeItem(👁='▶︎ 📁 /#/index.html - 8 of Comic', IconTooltip='Grouped urls')",
                            [],
                            path='T[0][0][0][0][1].Tree[0][0]',
                            peer_obj=root_0_0_peer
                        ),
                        make_snapshot(
                            "TreeItem(👁='▶︎ 📁 /atom.xml - Unknown Link (rel=alternate), Link: Feed, Link: Atom Feed', IconTooltip='Undownloaded URL')",
                            [],
                            path='T[0][0][0][0][1].Tree[0][1]',
                            peer_obj=root_0_1_peer
                        ),
                        make_snapshot(
                            "TreeItem(👁='▶︎ 📁 /rss.xml - Unknown Link (rel=alternate), Link: RSS Feed', IconTooltip='Undownloaded URL')",
                            [],
                            path='T[0][0][0][0][1].Tree[0][2]',
                            peer_obj=root_0_2_peer
                        ),
                        make_snapshot(
                            "TreeItem(👁='▶︎ 📁 /styles.css - Link: Stylesheet', IconTooltip='Undownloaded URL')",
                            [],
                            path='T[0][0][0][0][1].Tree[0][3]',
                            peer_obj=root_0_3_peer
                        ),
                        make_snapshot(
                            "TreeItem(👁='▶︎ 📁 /script.js - Link: Script', IconTooltip='Undownloaded URL')",
                            [],
                            path='T[0][0][0][0][1].Tree[0][4]',
                            peer_obj=root_0_4_peer
                        ),
                        make_snapshot(
                            "TreeItem(👁='▶︎ 📁 /license.html - Link: More details', IconTooltip='Undownloaded URL')",
                            [],
                            path='T[0][0][0][0][1].Tree[0][5]',
                            peer_obj=root_0_5_peer
                        ),
                        make_snapshot(
                            "TreeItem(👁='▶︎ 📁 (Low-priority: Offsite)', IconTooltip='Offsite URLs')",
                            [],
                            path='T[0][0][0][0][1].Tree[0][6]',
                            peer_obj=root_0_6_peer
                        ),
                        make_snapshot(
                            "TreeItem(👁='▶︎ 📁 (Hidden: Embedded)', IconTooltip='Embedded URLs')",
                            [],
                            path='T[0][0][0][0][1].Tree[0][7]',
                            peer_obj=root_0_7_peer
                        ),
                    ],
                    path='T[0][0][0][0][1].Tree[0]',
                    peer_obj=root_0_peer
                ),
                make_snapshot(
                    "TreeItem(👁='▶︎ 📁 /1/', IconTooltip='Fresh root URL')",
                    [],
                    path='T[0][0][0][0][1].Tree[1]',
                    peer_obj=root_1_peer
                ),
                make_snapshot(
                    "TreeItem(👁='▶︎ 📁 /2/', IconTooltip='Fresh root URL')",
                    [],
                    path='T[0][0][0][0][1].Tree[2]',
                    peer_obj=root_2_peer
                ),
                make_snapshot(
                    'More(Count=2)',
                    [],
                    path='T[0][0][0][0][1].Tree[3:5]',
                    peer_obj=root_more_peer
                ),
                make_snapshot(
                    "TreeItem(👁='▶︎ 📁 /5/', IconTooltip='Fresh root URL')",
                    [],
                    path='T[0][0][0][0][1].Tree[5]',
                    peer_obj=root_5_peer
                ),
                make_snapshot(
                    "TreeItem(👁='▶︎ 📁 /6/', IconTooltip='Fresh root URL')",
                    [],
                    path='T[0][0][0][0][1].Tree[6]',
                    peer_obj=root_6_peer
                ),
                make_snapshot(
                    "TreeItem(👁='▶︎ 📁 /#/index.html - Comic', IconTooltip='Group')",
                    [],
                    path='T[0][0][0][0][1].Tree[7]',
                    peer_obj=root_7_peer
                ),
            ],
            path='T[0][0][0][0][1].Tree',
            peer_obj=root_peer
        )
        
        expected_diff_repr_lines = [
            '# S := T[0][0][0][0][1].Tree[0]',
            "S ~ TreeItem(👁='{▶︎→▼} {📁→📂} /', IsSelected=True, IconTooltip='Fresh root URL')",
            "S[0] + TreeItem(👁='▶︎ 📁 /#/index.html - 8 of Comic', IconTooltip='Grouped urls')",
            "S[1] + TreeItem(👁='▶︎ 📁 /atom.xml - Unknown Link (rel=alternate), Link: Feed, Link: Atom Feed', IconTooltip='Undownloaded URL')",
            "S[2] + TreeItem(👁='▶︎ 📁 /rss.xml - Unknown Link (rel=alternate), Link: RSS Feed', IconTooltip='Undownloaded URL')",
            'S[3..4] + More(Count=2)',
            "S[5] + TreeItem(👁='▶︎ 📁 /license.html - Link: More details', IconTooltip='Undownloaded URL')",
            "S[6] + TreeItem(👁='▶︎ 📁 (Low-priority: Offsite)', IconTooltip='Offsite URLs')",
            "S[7] + TreeItem(👁='▶︎ 📁 (Hidden: Embedded)', IconTooltip='Embedded URLs')",
        ]
        
        with subtests.test(direction='forward'):
            diff = Snapshot.diff(old, new)
            diff_repr = repr(diff)
            actual_diff_repr_lines = diff_repr.split('\n')
            assert actual_diff_repr_lines == expected_diff_repr_lines
        
        expected_reverse_diff_repr_lines = [
            '# S := T[0][0][0][0][1].Tree[0]',
            "S ~ TreeItem(👁='{▼→▶︎} {📂→📁} /', IsSelected=True, IconTooltip='Fresh root URL')",
            "S[0] - TreeItem(👁='▶︎ 📁 /#/index.html - 8 of Comic', IconTooltip='Grouped urls')",
            "S[1] - TreeItem(👁='▶︎ 📁 /atom.xml - Unknown Link (rel=alternate), Link: Feed, Link: Atom Feed', IconTooltip='Undownloaded URL')",
            "S[2] - TreeItem(👁='▶︎ 📁 /rss.xml - Unknown Link (rel=alternate), Link: RSS Feed', IconTooltip='Undownloaded URL')",
            'S[3..4] - More(Count=2)',
            "S[5] - TreeItem(👁='▶︎ 📁 /license.html - Link: More details', IconTooltip='Undownloaded URL')",
            "S[6] - TreeItem(👁='▶︎ 📁 (Low-priority: Offsite)', IconTooltip='Offsite URLs')",
            "S[7] - TreeItem(👁='▶︎ 📁 (Hidden: Embedded)', IconTooltip='Embedded URLs')",
        ]
        
        with subtests.test(direction='reverse'):
            diff = Snapshot.diff(new, old)
            diff_repr = repr(diff)
            actual_diff_repr_lines = diff_repr.split('\n')
            assert actual_diff_repr_lines == expected_reverse_diff_repr_lines
    
    def test_when_trailing_more_node_in_entity_tree_expanded_then_new_nodes_appended(self, subtests) -> None:
        """
        Situation:
        - A trailing "more" node in the entity tree is expanded,
          revealing additional child URLs.
        """
        # Create peer objects for identity-based matching
        group_peer = object()
        group_0_peer = object()
        group_1_peer = object()
        # Generate peer objects for nodes /1/ through /120/
        child_peers = [object() for i in range(1, 121)]
        group_more_old_peer = object()
        group_more_new_peer = object()
        
        # Old snapshot: Group with nodes /1/ through /100/ visible and a "2,338 more" node
        old = make_snapshot(
            'TreeItem(IsRoot=True, Visible=False)',
            [
                make_snapshot(
                    "TreeItem(👁='▶︎ 📁 / - Home', IsSelected=True, IconTooltip='Fresh root URL')",
                    [],
                    path='T[0][0][0][0][1].Tree[0]',
                    peer_obj=group_0_peer
                ),
                make_snapshot(
                    "TreeItem(👁='▼ 📂 /#/index.html - Comic', IconTooltip='Group')",
                    [
                        make_snapshot(
                            f"TreeItem(👁='▶︎ 📁 /{i}/index.html', IconTooltip='Undownloaded URL')",
                            [],
                            path=f'T[0][0][0][0][1].Tree[1][{i-1}]',
                            peer_obj=child_peers[i-1]
                        )
                        for i in range(1, 101)
                    ] + [
                        make_snapshot(
                            "TreeItem(👁='▶︎ 📁 2,338 more')",
                            [],
                            path='T[0][0][0][0][1].Tree[1][100]',
                            peer_obj=group_more_old_peer
                        ),
                    ],
                    path='T[0][0][0][0][1].Tree[1]',
                    peer_obj=group_1_peer
                ),
            ],
            path='T[0][0][0][0][1].Tree',
            peer_obj=group_peer
        )
        
        # New snapshot: Group with nodes /1/ through /120/ visible and a "2,318 more" node
        new = make_snapshot(
            'TreeItem(IsRoot=True, Visible=False)',
            [
                make_snapshot(
                    "TreeItem(👁='▶︎ 📁 / - Home', IsSelected=True, IconTooltip='Fresh root URL')",
                    [],
                    path='T[0][0][0][0][1].Tree[0]',
                    peer_obj=group_0_peer
                ),
                make_snapshot(
                    "TreeItem(👁='▼ 📂 /#/index.html - Comic', IconTooltip='Group')",
                    [
                        make_snapshot(
                            f"TreeItem(👁='▶︎ 📁 /{i}/index.html', IconTooltip='Undownloaded URL')",
                            [],
                            path=f'T[0][0][0][0][1].Tree[1][{i-1}]',
                            peer_obj=child_peers[i-1]
                        )
                        for i in range(1, 121)
                    ] + [
                        make_snapshot(
                            "TreeItem(👁='▶︎ 📁 2,318 more')",
                            [],
                            path='T[0][0][0][0][1].Tree[1][120]',
                            peer_obj=group_more_new_peer
                        ),
                    ],
                    path='T[0][0][0][0][1].Tree[1]',
                    peer_obj=group_1_peer
                ),
            ],
            path='T[0][0][0][0][1].Tree',
            peer_obj=group_peer
        )
        
        expected_diff_repr_lines = [
            '# S := T[0][0][0][0][1].Tree[1]',
            "S[100] - TreeItem(👁='▶︎ 📁 2,338 more')",
            "S[100] + TreeItem(👁='▶︎ 📁 /101/index.html', IconTooltip='Undownloaded URL')",
            "S[101] + TreeItem(👁='▶︎ 📁 /102/index.html', IconTooltip='Undownloaded URL')",
            "S[102] + TreeItem(👁='▶︎ 📁 /103/index.html', IconTooltip='Undownloaded URL')",
            'S[103..117] + More(Count=15)',
            "S[118] + TreeItem(👁='▶︎ 📁 /119/index.html', IconTooltip='Undownloaded URL')",
            "S[119] + TreeItem(👁='▶︎ 📁 /120/index.html', IconTooltip='Undownloaded URL')",
            "S[120] + TreeItem(👁='▶︎ 📁 2,318 more')",
        ]
        
        with subtests.test(direction='forward'):
            diff = Snapshot.diff(old, new)
            diff_repr = repr(diff)
            actual_diff_repr_lines = diff_repr.split('\n')
            assert actual_diff_repr_lines == expected_diff_repr_lines
        
        expected_reverse_diff_repr_lines = [
            '# S := T[0][0][0][0][1].Tree[1]',
            "S[100] - TreeItem(👁='▶︎ 📁 /101/index.html', IconTooltip='Undownloaded URL')",
            "S[100] + TreeItem(👁='▶︎ 📁 2,338 more')",
            "S[101] - TreeItem(👁='▶︎ 📁 /102/index.html', IconTooltip='Undownloaded URL')",
            "S[102] - TreeItem(👁='▶︎ 📁 /103/index.html', IconTooltip='Undownloaded URL')",
            'S[103..117] - More(Count=15)',
            "S[118] - TreeItem(👁='▶︎ 📁 /119/index.html', IconTooltip='Undownloaded URL')",
            "S[119] - TreeItem(👁='▶︎ 📁 /120/index.html', IconTooltip='Undownloaded URL')",
            "S[120] - TreeItem(👁='▶︎ 📁 2,318 more')",
        ]
        
        with subtests.test(direction='reverse'):
            diff = Snapshot.diff(new, old)
            diff_repr = repr(diff)
            actual_diff_repr_lines = diff_repr.split('\n')
            assert actual_diff_repr_lines == expected_reverse_diff_repr_lines
    
    def test_when_new_group_defined_then_entity_tree_children_nodes_restructured(self, subtests) -> None:
        """
        Situation:
        - A new group is defined, causing some child URLs of a root resource
          to be reorganized under the group node in the entity tree.
        """
        # Create peer objects for identity-based matching
        root_peer = object()
        root_0_peer = object()
        root_0_0_peer = object()
        root_0_1_peer = object()
        root_0_2_peer = object()
        root_0_39_peer = object()
        root_0_40_peer = object()
        root_0_41_peer = object()
        
        # Peers for URLs that move to the group
        url_1_peer = object()
        url_2438_peer = object()
        url_150_peer = object()
        url_730_peer = object()
        url_162_peer = object()
        url_688_peer = object()
        url_556_peer = object()
        url_1732_peer = object()
        
        # Peers for group nodes
        group_inlined_peer = object()
        group_root_peer = object()
        
        # Old snapshot: Before group is defined
        old = make_snapshot(
            'TreeItem(IsRoot=True, Visible=False)',
            [
                make_snapshot(
                    "TreeItem(👁='▼ 📂 / - Home', IconTooltip='Fresh root URL')",
                    [
                        make_snapshot(
                            "TreeItem(👁='▶︎ 📁 /atom.xml - Unknown Link (rel=alternate), Link: Feed, Link: Atom Feed', IconTooltip='Undownloaded URL')",
                            [],
                            path='T[0][0][0][0][1].Tree[0][0]',
                            peer_obj=root_0_0_peer
                        ),
                        make_snapshot(
                            "TreeItem(👁='▶︎ 📁 /rss.xml - Unknown Link (rel=alternate), Link: RSS Feed', IconTooltip='Undownloaded URL')",
                            [],
                            path='T[0][0][0][0][1].Tree[0][1]',
                            peer_obj=root_0_1_peer
                        ),
                        make_snapshot(
                            "TreeItem(👁='▶︎ 📁 /styles.css - Link: Stylesheet', IconTooltip='Undownloaded URL')",
                            [],
                            path='T[0][0][0][0][1].Tree[0][3]',
                            peer_obj=object()
                        ),
                        make_snapshot(
                            "TreeItem(👁='▶︎ 📁 /script.js - Link: Script', IconTooltip='Undownloaded URL')",
                            [],
                            path='T[0][0][0][0][1].Tree[0][4]',
                            peer_obj=object()
                        ),
                        make_snapshot(
                            "TreeItem(👁='▶︎ 📁 /1/index.html - Link: |<, Link: |<', IsSelected=True, IconTooltip='Undownloaded URL')",
                            [],
                            path='T[0][0][0][0][1].Tree[0][5]',
                            peer_obj=url_1_peer
                        ),
                        make_snapshot(
                            "TreeItem(👁='▶︎ 📁 /2438/index.html - Link: < Prev, Link: < Prev', IconTooltip='Undownloaded URL')",
                            [],
                            path='T[0][0][0][0][1].Tree[0][6]',
                            peer_obj=url_2438_peer
                        ),
                        make_snapshot(
                            "TreeItem(👁='▶︎ 📁 /other1.html - Link', IconTooltip='Undownloaded URL')",
                            [],
                            path='T[0][0][0][0][1].Tree[0][7]',
                            peer_obj=object()
                        ),
                        make_snapshot(
                            "TreeItem(👁='▶︎ 📁 /other2.html - Link', IconTooltip='Undownloaded URL')",
                            [],
                            path='T[0][0][0][0][1].Tree[0][8]',
                            peer_obj=object()
                        ),
                        make_snapshot(
                            "TreeItem(👁='▶︎ 📁 /150/index.html - Unknown Href (area)', IconTooltip='Undownloaded URL')",
                            [],
                            path='T[0][0][0][0][1].Tree[0][9]',
                            peer_obj=url_150_peer
                        ),
                        make_snapshot(
                            "TreeItem(👁='▶︎ 📁 /730/index.html - Unknown Href (area)', IconTooltip='Undownloaded URL')",
                            [],
                            path='T[0][0][0][0][1].Tree[0][10]',
                            peer_obj=url_730_peer
                        ),
                        make_snapshot(
                            "TreeItem(👁='▶︎ 📁 /162/index.html - Unknown Href (area)', IconTooltip='Undownloaded URL')",
                            [],
                            path='T[0][0][0][0][1].Tree[0][11]',
                            peer_obj=url_162_peer
                        ),
                        make_snapshot(
                            "TreeItem(👁='▶︎ 📁 /688/index.html - Unknown Href (area)', IconTooltip='Undownloaded URL')",
                            [],
                            path='T[0][0][0][0][1].Tree[0][12]',
                            peer_obj=url_688_peer
                        ),
                        make_snapshot(
                            "TreeItem(👁='▶︎ 📁 /556/index.html - Unknown Href (area)', IconTooltip='Undownloaded URL')",
                            [],
                            path='T[0][0][0][0][1].Tree[0][13]',
                            peer_obj=url_556_peer
                        ),
                        make_snapshot(
                            "TreeItem(👁='▶︎ 📁 /1732/index.html - Link', IconTooltip='Undownloaded URL')",
                            [],
                            path='T[0][0][0][0][1].Tree[0][14]',
                            peer_obj=url_1732_peer
                        ),
                        make_snapshot(
                            "TreeItem(👁='▶︎ 📁 /license.html - Link: More details', IconTooltip='Undownloaded URL')",
                            [],
                            path='T[0][0][0][0][1].Tree[0][15]',
                            peer_obj=root_0_39_peer
                        ),
                        make_snapshot(
                            "TreeItem(👁='▶︎ 📁 (Low-priority: Offsite)', IconTooltip='Offsite URLs')",
                            [],
                            path='T[0][0][0][0][1].Tree[0][16]',
                            peer_obj=root_0_40_peer
                        ),
                        make_snapshot(
                            "TreeItem(👁='▶︎ 📁 (Hidden: Embedded)', IconTooltip='Embedded URLs')",
                            [],
                            path='T[0][0][0][0][1].Tree[0][17]',
                            peer_obj=root_0_41_peer
                        ),
                    ],
                    path='T[0][0][0][0][1].Tree[0]',
                    peer_obj=root_0_peer
                ),
            ],
            path='T[0][0][0][0][1].Tree',
            peer_obj=root_peer
        )
        
        # New snapshot: After group is defined
        new = make_snapshot(
            'TreeItem(IsRoot=True, Visible=False)',
            [
                make_snapshot(
                    "TreeItem(👁='▼ 📂 / - Home', IconTooltip='Fresh root URL')",
                    [
                        make_snapshot(
                            "TreeItem(👁='▼ 📂 /#/index.html - 8 of Comic', IconTooltip='Grouped urls')",
                            [
                                make_snapshot(
                                    "TreeItem(👁='▶︎ 📁 /1/index.html - Link: |<, Link: |<', IsSelected=True, IconTooltip='Undownloaded URL')",
                                    [],
                                    path='T[0][0][0][0][1].Tree[0][0][0]',
                                    peer_obj=url_1_peer
                                ),
                                make_snapshot(
                                    "TreeItem(👁='▶︎ 📁 /2438/index.html - Link: < Prev, Link: < Prev', IconTooltip='Undownloaded URL')",
                                    [],
                                    path='T[0][0][0][0][1].Tree[0][0][1]',
                                    peer_obj=url_2438_peer
                                ),
                                make_snapshot(
                                    "TreeItem(👁='▶︎ 📁 /150/index.html - Unknown Href (area)', IconTooltip='Undownloaded URL')",
                                    [],
                                    path='T[0][0][0][0][1].Tree[0][0][2]',
                                    peer_obj=url_150_peer
                                ),
                                make_snapshot(
                                    "TreeItem(👁='▶︎ 📁 /730/index.html - Unknown Href (area)', IconTooltip='Undownloaded URL')",
                                    [],
                                    path='T[0][0][0][0][1].Tree[0][0][3]',
                                    peer_obj=url_730_peer
                                ),
                                make_snapshot(
                                    "TreeItem(👁='▶︎ 📁 /162/index.html - Unknown Href (area)', IconTooltip='Undownloaded URL')",
                                    [],
                                    path='T[0][0][0][0][1].Tree[0][0][4]',
                                    peer_obj=url_162_peer
                                ),
                                make_snapshot(
                                    "TreeItem(👁='▶︎ 📁 /688/index.html - Unknown Href (area)', IconTooltip='Undownloaded URL')",
                                    [],
                                    path='T[0][0][0][0][1].Tree[0][0][5]',
                                    peer_obj=url_688_peer
                                ),
                                make_snapshot(
                                    "TreeItem(👁='▶︎ 📁 /556/index.html - Unknown Href (area)', IconTooltip='Undownloaded URL')",
                                    [],
                                    path='T[0][0][0][0][1].Tree[0][0][6]',
                                    peer_obj=url_556_peer
                                ),
                                make_snapshot(
                                    "TreeItem(👁='▶︎ 📁 /1732/index.html - Link', IconTooltip='Undownloaded URL')",
                                    [],
                                    path='T[0][0][0][0][1].Tree[0][0][7]',
                                    peer_obj=url_1732_peer
                                ),
                            ],
                            path='T[0][0][0][0][1].Tree[0][0]',
                            peer_obj=group_inlined_peer
                        ),
                        make_snapshot(
                            "TreeItem(👁='▶︎ 📁 /atom.xml - Unknown Link (rel=alternate), Link: Feed, Link: Atom Feed', IconTooltip='Undownloaded URL')",
                            [],
                            path='T[0][0][0][0][1].Tree[0][1]',
                            peer_obj=root_0_0_peer
                        ),
                        make_snapshot(
                            "TreeItem(👁='▶︎ 📁 /rss.xml - Unknown Link (rel=alternate), Link: RSS Feed', IconTooltip='Undownloaded URL')",
                            [],
                            path='T[0][0][0][0][1].Tree[0][2]',
                            peer_obj=root_0_1_peer
                        ),
                        make_snapshot(
                            "TreeItem(👁='▶︎ 📁 /other1.html - Link', IconTooltip='Undownloaded URL')",
                            [],
                            path='T[0][0][0][0][1].Tree[0][3]',
                            peer_obj=object()
                        ),
                        make_snapshot(
                            "TreeItem(👁='▶︎ 📁 /other2.html - Link', IconTooltip='Undownloaded URL')",
                            [],
                            path='T[0][0][0][0][1].Tree[0][4]',
                            peer_obj=object()
                        ),
                        make_snapshot(
                            "TreeItem(👁='▶︎ 📁 /styles.css - Link: Stylesheet', IconTooltip='Undownloaded URL')",
                            [],
                            path='T[0][0][0][0][1].Tree[0][5]',
                            peer_obj=object()
                        ),
                        make_snapshot(
                            "TreeItem(👁='▶︎ 📁 /script.js - Link: Script', IconTooltip='Undownloaded URL')",
                            [],
                            path='T[0][0][0][0][1].Tree[0][6]',
                            peer_obj=object()
                        ),
                        make_snapshot(
                            "TreeItem(👁='▶︎ 📁 /license.html - Link: More details', IconTooltip='Undownloaded URL')",
                            [],
                            path='T[0][0][0][0][1].Tree[0][7]',
                            peer_obj=root_0_39_peer
                        ),
                        make_snapshot(
                            "TreeItem(👁='▶︎ 📁 (Low-priority: Offsite)', IconTooltip='Offsite URLs')",
                            [],
                            path='T[0][0][0][0][1].Tree[0][8]',
                            peer_obj=root_0_40_peer
                        ),
                        make_snapshot(
                            "TreeItem(👁='▶︎ 📁 (Hidden: Embedded)', IconTooltip='Embedded URLs')",
                            [],
                            path='T[0][0][0][0][1].Tree[0][9]',
                            peer_obj=root_0_41_peer
                        ),
                    ],
                    path='T[0][0][0][0][1].Tree[0]',
                    peer_obj=root_0_peer
                ),
                make_snapshot(
                    "TreeItem(👁='▶︎ 📁 /#/index.html - Comic', IconTooltip='Group')",
                    [],
                    path='T[0][0][0][0][1].Tree[1]',
                    peer_obj=group_root_peer
                ),
            ],
            path='T[0][0][0][0][1].Tree',
            peer_obj=root_peer
        )
        
        expected_diff_repr_lines = [
            '# S := T[0][0][0][0][1].Tree',
            'S[0][0..1 → 1..2] = More(Count=2)',
            "S[0][0] + TreeItem(👁='▼ 📂 /#/index.html - 8 of Comic', IconTooltip='Grouped urls')",
            "S[0][0][0] + TreeItem(👁='▶︎ 📁 /1/index.html - Link: |<, Link: |<', IsSelected=True, IconTooltip='Undownloaded URL')",
            "S[0][0][1] + TreeItem(👁='▶︎ 📁 /2438/index.html - Link: < Prev, Link: < Prev', IconTooltip='Undownloaded URL')",
            "S[0][0][2] + TreeItem(👁='▶︎ 📁 /150/index.html - Unknown Href (area)', IconTooltip='Undownloaded URL')",
            "S[0][0][3] + TreeItem(👁='▶︎ 📁 /730/index.html - Unknown Href (area)', IconTooltip='Undownloaded URL')",
            "S[0][0][4] + TreeItem(👁='▶︎ 📁 /162/index.html - Unknown Href (area)', IconTooltip='Undownloaded URL')",
            "S[0][0][5] + TreeItem(👁='▶︎ 📁 /688/index.html - Unknown Href (area)', IconTooltip='Undownloaded URL')",
            "S[0][0][6] + TreeItem(👁='▶︎ 📁 /556/index.html - Unknown Href (area)', IconTooltip='Undownloaded URL')",
            "S[0][0][7] + TreeItem(👁='▶︎ 📁 /1732/index.html - Link', IconTooltip='Undownloaded URL')",
            'S[0][2..3 → 5..6] = More(Count=2)',
            "S[0][4] - TreeItem(👁='▶︎ 📁 /1/index.html - Link: |<, Link: |<', IsSelected=True, IconTooltip='Undownloaded URL')",
            "S[0][5] - TreeItem(👁='▶︎ 📁 /2438/index.html - Link: < Prev, Link: < Prev', IconTooltip='Undownloaded URL')",
            'S[0][6..7 → 3..4] = More(Count=2)',
            "S[0][8] - TreeItem(👁='▶︎ 📁 /150/index.html - Unknown Href (area)', IconTooltip='Undownloaded URL')",
            "S[0][9] - TreeItem(👁='▶︎ 📁 /730/index.html - Unknown Href (area)', IconTooltip='Undownloaded URL')",
            "S[0][10] - TreeItem(👁='▶︎ 📁 /162/index.html - Unknown Href (area)', IconTooltip='Undownloaded URL')",
            "S[0][11] - TreeItem(👁='▶︎ 📁 /688/index.html - Unknown Href (area)', IconTooltip='Undownloaded URL')",
            "S[0][12] - TreeItem(👁='▶︎ 📁 /556/index.html - Unknown Href (area)', IconTooltip='Undownloaded URL')",
            "S[0][13] - TreeItem(👁='▶︎ 📁 /1732/index.html - Link', IconTooltip='Undownloaded URL')",
            'S[0][14..16 → 7..9] = More(Count=3)',
            "S[1] + TreeItem(👁='▶︎ 📁 /#/index.html - Comic', IconTooltip='Group')",
        ]
        
        with subtests.test(direction='forward'):
            diff = Snapshot.diff(old, new)
            diff_repr = repr(diff)
            actual_diff_repr_lines = diff_repr.split('\n')
            assert actual_diff_repr_lines == expected_diff_repr_lines
        
        expected_reverse_diff_repr_lines = [
            '# S := T[0][0][0][0][1].Tree',
            "S[0][0] - TreeItem(👁='▼ 📂 /#/index.html - 8 of Comic', IconTooltip='Grouped urls')",
            'S[0][0][0..7] - More(Count=8)',
            'S[0][1..2 → 0..1] = More(Count=2)',
            'S[0][3..4 → 6..7] = More(Count=2)',
            "S[0][4] + TreeItem(👁='▶︎ 📁 /1/index.html - Link: |<, Link: |<', IsSelected=True, IconTooltip='Undownloaded URL')",
            'S[0][5..6 → 2..3] = More(Count=2)',
            "S[0][5] + TreeItem(👁='▶︎ 📁 /2438/index.html - Link: < Prev, Link: < Prev', IconTooltip='Undownloaded URL')",
            'S[0][7..9 → 14..16] = More(Count=3)',
            "S[0][8] + TreeItem(👁='▶︎ 📁 /150/index.html - Unknown Href (area)', IconTooltip='Undownloaded URL')",
            "S[0][9] + TreeItem(👁='▶︎ 📁 /730/index.html - Unknown Href (area)', IconTooltip='Undownloaded URL')",
            "S[0][10] + TreeItem(👁='▶︎ 📁 /162/index.html - Unknown Href (area)', IconTooltip='Undownloaded URL')",
            "S[0][11] + TreeItem(👁='▶︎ 📁 /688/index.html - Unknown Href (area)', IconTooltip='Undownloaded URL')",
            "S[0][12] + TreeItem(👁='▶︎ 📁 /556/index.html - Unknown Href (area)', IconTooltip='Undownloaded URL')",
            "S[0][13] + TreeItem(👁='▶︎ 📁 /1732/index.html - Link', IconTooltip='Undownloaded URL')",
            "S[1] - TreeItem(👁='▶︎ 📁 /#/index.html - Comic', IconTooltip='Group')",
        ]
        
        with subtests.test(direction='reverse'):
            diff = Snapshot.diff(new, old)
            diff_repr = repr(diff)
            actual_diff_repr_lines = diff_repr.split('\n')
            assert actual_diff_repr_lines == expected_reverse_diff_repr_lines
    
    def test_progress_of_download_group_task_in_task_tree(self, subtests) -> None:
        """
        Situation:
        - Multiple child download tasks are progressing, with items being
          completed, moved, and added.
        """
        # Create peer objects for identity-based matching
        root_peer = object()
        task_peer = object()
        subtask_peer = object()
        more_peer = object()
        item_2424_peer = object()
        item_2423_peer = object()
        item_2422_peer = object()
        item_2421_peer = object()
        item_2420_peer = object()
        item_1001_peer = object()
        item_1002_peer = object()
        item_1003_peer = object()
        item_1004_peer = object()
        item_1005_peer = object()
        item_1006_peer = object()
        item_1007_peer = object()
        item_1008_peer = object()
        item_1009_peer = object()
        more_end_peer = object()
        
        # Old snapshot: 27 items completed
        old = make_snapshot(
            'TreeItem(IsRoot=True, Visible=False, IsSelected=True)',
            [
                make_snapshot(
                    "TreeItem(👁='▼ 📂 Downloading group: Comic -- 27 of 2,438 item(s) -- 2:18:01 remaining (3.43s/item)')",
                    [  
                        make_snapshot(
                            "TreeItem(👁='▶︎ 📁 Finding members of group: Comic -- Complete')",
                            path='T[0][0]',
                            peer_obj=subtask_peer
                        ),
                        make_snapshot(
                            "TreeItem(👁='▼ 📂 Downloading members of group: Comic -- 27 of 2,438 item(s) -- 2:18:01 remaining (3.43s/item)')",
                            [
                                make_snapshot(
                                    "TreeItem(👁='— 📄 22 more')",
                                    path='T[0][1][0]',
                                    peer_obj=more_peer
                                ),
                                make_snapshot(
                                    "TreeItem(👁='▶︎ 📁 Downloading: https://xkcd.daarchive.net/2424/index.html -- Complete')",
                                    path='T[0][1][1]',
                                    peer_obj=item_2424_peer
                                ),
                                make_snapshot(
                                    "TreeItem(👁='▶︎ 📁 Downloading: https://xkcd.daarchive.net/2423/index.html -- Complete')",
                                    path='T[0][1][2]',
                                    peer_obj=item_2423_peer
                                ),
                                make_snapshot(
                                    "TreeItem(👁='▶︎ 📁 Downloading: https://xkcd.daarchive.net/2422/index.html -- Complete')",
                                    path='T[0][1][3]',
                                    peer_obj=item_2422_peer
                                ),
                                make_snapshot(
                                    "TreeItem(👁='▶︎ 📁 Downloading: https://xkcd.daarchive.net/2421/index.html -- Complete')",
                                    path='T[0][1][4]',
                                    peer_obj=item_2421_peer
                                ),
                                make_snapshot(
                                    "TreeItem(👁='▶︎ 📁 Downloading: https://xkcd.daarchive.net/2420/index.html -- Complete')",
                                    path='T[0][1][5]',
                                    peer_obj=item_2420_peer
                                ),
                                make_snapshot(
                                    "TreeItem(👁='▶︎ 📁 Downloading: https://xkcd.daarchive.net/1001/index.html -- Downloading')",
                                    path='T[0][1][6]',
                                    peer_obj=item_1001_peer
                                ),
                                make_snapshot(
                                    "TreeItem(👁='▶︎ 📁 Downloading: https://xkcd.daarchive.net/1002/index.html -- Queued')",
                                    path='T[0][1][7]',
                                    peer_obj=item_1002_peer
                                ),
                                make_snapshot(
                                    "TreeItem(👁='▶︎ 📁 Downloading: https://xkcd.daarchive.net/1003/index.html -- Queued')",
                                    path='T[0][1][8]',
                                    peer_obj=item_1003_peer
                                ),
                                make_snapshot(
                                    "TreeItem(👁='▶︎ 📁 Downloading: https://xkcd.daarchive.net/1004/index.html -- Queued')",
                                    path='T[0][1][9]',
                                    peer_obj=item_1004_peer
                                ),
                                make_snapshot(
                                    "TreeItem(👁='▶︎ 📁 Downloading: https://xkcd.daarchive.net/1005/index.html -- Queued')",
                                    path='T[0][1][10]',
                                    peer_obj=item_1005_peer
                                ),
                                make_snapshot(
                                    "TreeItem(👁='▶︎ 📁 Downloading: https://xkcd.daarchive.net/1006/index.html -- Queued')",
                                    path='T[0][1][11]',
                                    peer_obj=item_1006_peer
                                ),
                                make_snapshot(
                                    "TreeItem(👁='— 📄 2,310 more')",
                                    path='T[0][1][12]',
                                    peer_obj=more_end_peer
                                ),
                            ],
                            path='T[0][1]',
                            peer_obj=task_peer
                        ),
                    ],
                    path="T['cr-entity-tree'].Tree[0]",
                    peer_obj=task_peer
                ),
            ],
            path="T['cr-entity-tree'].Tree",
            peer_obj=root_peer
        )
        
        # New snapshot: 30 items completed, scrolled up by 3 items
        new = make_snapshot(
            'TreeItem(IsRoot=True, Visible=False, IsSelected=True)',
            [
                make_snapshot(
                    "TreeItem(👁='▼ 📂 Downloading group: Comic -- 30 of 2,438 item(s) -- 2:19:18 remaining (3.47s/item)')",
                    [
                        make_snapshot(
                            "TreeItem(👁='▶︎ 📁 Finding members of group: Comic -- Complete')",
                            path='T[0][0]',
                            peer_obj=subtask_peer
                        ),
                        make_snapshot(
                            "TreeItem(👁='▼ 📂 Downloading members of group: Comic -- 30 of 2,438 item(s) -- 2:19:18 remaining (3.47s/item)')",
                            [
                                make_snapshot(
                                    "TreeItem(👁='— 📄 25 more')",
                                    path='T[0][1][0]',
                                    peer_obj=more_peer
                                ),
                                # 2424, 2423, 2422 removed (scrolled off by 3 items)
                                # 2421, 2420 stay visible and complete
                                make_snapshot(
                                    "TreeItem(👁='▶︎ 📁 Downloading: https://xkcd.daarchive.net/2421/index.html -- Complete')",
                                    path='T[0][1][1]',
                                    peer_obj=item_2421_peer
                                ),
                                make_snapshot(
                                    "TreeItem(👁='▶︎ 📁 Downloading: https://xkcd.daarchive.net/2420/index.html -- Complete')",
                                    path='T[0][1][2]',
                                    peer_obj=item_2420_peer
                                ),
                                # 1001 moved from index 6 to 3 and completed
                                make_snapshot(
                                    "TreeItem(👁='▶︎ 📁 Downloading: https://xkcd.daarchive.net/1001/index.html -- Complete')",
                                    path='T[0][1][3]',
                                    peer_obj=item_1001_peer
                                ),
                                # 1002 moved from index 7 to 4 and completed
                                make_snapshot(
                                    "TreeItem(👁='▶︎ 📁 Downloading: https://xkcd.daarchive.net/1002/index.html -- Complete')",
                                    path='T[0][1][4]',
                                    peer_obj=item_1002_peer
                                ),
                                # 1003 moved from index 8 to 5 and completed
                                make_snapshot(
                                    "TreeItem(👁='▶︎ 📁 Downloading: https://xkcd.daarchive.net/1003/index.html -- Complete')",
                                    path='T[0][1][5]',
                                    peer_obj=item_1003_peer
                                ),
                                # 1004 moved from index 9 to 6 and now downloading
                                make_snapshot(
                                    "TreeItem(👁='▶︎ 📁 Downloading: https://xkcd.daarchive.net/1004/index.html -- Downloading')",
                                    path='T[0][1][6]',
                                    peer_obj=item_1004_peer
                                ),
                                # 1005, 1006 stay queued and shifted up
                                make_snapshot(
                                    "TreeItem(👁='▶︎ 📁 Downloading: https://xkcd.daarchive.net/1005/index.html -- Queued')",
                                    path='T[0][1][7]',
                                    peer_obj=item_1005_peer
                                ),
                                make_snapshot(
                                    "TreeItem(👁='▶︎ 📁 Downloading: https://xkcd.daarchive.net/1006/index.html -- Queued')",
                                    path='T[0][1][8]',
                                    peer_obj=item_1006_peer
                                ),
                                # 1007, 1008, 1009 newly visible, queued
                                make_snapshot(
                                    "TreeItem(👁='▶︎ 📁 Downloading: https://xkcd.daarchive.net/1007/index.html -- Queued')",
                                    path='T[0][1][9]',
                                    peer_obj=item_1007_peer
                                ),
                                make_snapshot(
                                    "TreeItem(👁='▶︎ 📁 Downloading: https://xkcd.daarchive.net/1008/index.html -- Queued')",
                                    path='T[0][1][10]',
                                    peer_obj=item_1008_peer
                                ),
                                make_snapshot(
                                    "TreeItem(👁='▶︎ 📁 Downloading: https://xkcd.daarchive.net/1009/index.html -- Queued')",
                                    path='T[0][1][11]',
                                    peer_obj=item_1009_peer
                                ),
                                make_snapshot(
                                    "TreeItem(👁='— 📄 2,307 more')",
                                    path='T[0][1][12]',
                                    peer_obj=more_end_peer
                                ),
                            ],
                            path='T[0][1]',
                            peer_obj=task_peer
                        ),
                    ],
                    path="T['cr-entity-tree'].Tree[0]",
                    peer_obj=task_peer
                ),
            ],
            path="T['cr-entity-tree'].Tree",
            peer_obj=root_peer
        )
        
        expected_diff_repr_lines = [
            "# S := T['cr-entity-tree'].Tree[0]",
            "S ~ TreeItem(👁='▼ 📂 Downloading group: Comic -- {27→30} of 2,438 item(s) -- {2:18:01→2:19:18} remaining ({3.43→3.47}s/item)')",
            "S[1] ~ TreeItem(👁='▼ 📂 Downloading members of group: Comic -- {27→30} of 2,438 item(s) -- {2:18:01→2:19:18} remaining ({3.43→3.47}s/item)')",
            "S[1][0] ~ TreeItem(👁='— 📄 {22→25} more')",
            "S[1][1] - TreeItem(👁='▶︎ 📁 Downloading: https://xkcd.daarchive.net/2424/index.html -- Complete')",
            "S[1][2] - TreeItem(👁='▶︎ 📁 Downloading: https://xkcd.daarchive.net/2423/index.html -- Complete')",
            "S[1][3] - TreeItem(👁='▶︎ 📁 Downloading: https://xkcd.daarchive.net/2422/index.html -- Complete')",
            'S[1][4..5 → 1..2] = More(Count=2)',
            "S[1][6→3] ~ TreeItem(👁='▶︎ 📁 Downloading: https://xkcd.daarchive.net/1001/index.html -- {Downloading→Complete}')",
            "S[1][7→4] ~ TreeItem(👁='▶︎ 📁 Downloading: https://xkcd.daarchive.net/1002/index.html -- {Queued→Complete}')",
            "S[1][8→5] ~ TreeItem(👁='▶︎ 📁 Downloading: https://xkcd.daarchive.net/1003/index.html -- {Queued→Complete}')",
            "S[1][9→6] ~ TreeItem(👁='▶︎ 📁 Downloading: https://xkcd.daarchive.net/1004/index.html -- {Queued→Downloading}')",
            "S[1][9] + TreeItem(👁='▶︎ 📁 Downloading: https://xkcd.daarchive.net/1007/index.html -- Queued')",
            'S[1][10..11 → 7..8] = More(Count=2)',
            "S[1][10] + TreeItem(👁='▶︎ 📁 Downloading: https://xkcd.daarchive.net/1008/index.html -- Queued')",
            "S[1][11] + TreeItem(👁='▶︎ 📁 Downloading: https://xkcd.daarchive.net/1009/index.html -- Queued')",
            "S[1][12] ~ TreeItem(👁='— 📄 {2,310→2,307} more')",
        ]
        
        with subtests.test(direction='forward'):
            diff = Snapshot.diff(old, new)
            diff_repr = repr(diff)
            actual_diff_repr_lines = diff_repr.split('\n')
            assert actual_diff_repr_lines == expected_diff_repr_lines
        
        expected_reverse_diff_repr_lines = [
            "# S := T['cr-entity-tree'].Tree[0]",
            "S ~ TreeItem(👁='▼ 📂 Downloading group: Comic -- {30→27} of 2,438 item(s) -- {2:19:18→2:18:01} remaining ({3.47→3.43}s/item)')",
            "S[1] ~ TreeItem(👁='▼ 📂 Downloading members of group: Comic -- {30→27} of 2,438 item(s) -- {2:19:18→2:18:01} remaining ({3.47→3.43}s/item)')",
            "S[1][0] ~ TreeItem(👁='— 📄 {25→22} more')",
            'S[1][1..2 → 4..5] = More(Count=2)',
            "S[1][1] + TreeItem(👁='▶︎ 📁 Downloading: https://xkcd.daarchive.net/2424/index.html -- Complete')",
            "S[1][2] + TreeItem(👁='▶︎ 📁 Downloading: https://xkcd.daarchive.net/2423/index.html -- Complete')",
            "S[1][3→6] ~ TreeItem(👁='▶︎ 📁 Downloading: https://xkcd.daarchive.net/1001/index.html -- {Complete→Downloading}')",
            "S[1][3] + TreeItem(👁='▶︎ 📁 Downloading: https://xkcd.daarchive.net/2422/index.html -- Complete')",
            "S[1][4→7] ~ TreeItem(👁='▶︎ 📁 Downloading: https://xkcd.daarchive.net/1002/index.html -- {Complete→Queued}')",
            "S[1][5→8] ~ TreeItem(👁='▶︎ 📁 Downloading: https://xkcd.daarchive.net/1003/index.html -- {Complete→Queued}')",
            "S[1][6→9] ~ TreeItem(👁='▶︎ 📁 Downloading: https://xkcd.daarchive.net/1004/index.html -- {Downloading→Queued}')",
            'S[1][7..8 → 10..11] = More(Count=2)',
            "S[1][9] - TreeItem(👁='▶︎ 📁 Downloading: https://xkcd.daarchive.net/1007/index.html -- Queued')",
            "S[1][10] - TreeItem(👁='▶︎ 📁 Downloading: https://xkcd.daarchive.net/1008/index.html -- Queued')",
            "S[1][11] - TreeItem(👁='▶︎ 📁 Downloading: https://xkcd.daarchive.net/1009/index.html -- Queued')",
            "S[1][12] ~ TreeItem(👁='— 📄 {2,307→2,310} more')",
        ]
        
        with subtests.test(direction='reverse'):
            diff = Snapshot.diff(new, old)
            diff_repr = repr(diff)
            actual_diff_repr_lines = diff_repr.split('\n')
            assert actual_diff_repr_lines == expected_reverse_diff_repr_lines
