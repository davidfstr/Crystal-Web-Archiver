"""
Unit tests for crystal.ui.nav module.
"""

from crystal.ui.nav import Snapshot, SnapshotDiff, inline_diff


# === Helper Functions ===

def make_snapshot(
        desc: str,
        children: list[Snapshot] | None = None,
        path: str = 'S',
        query: str = '',
        accessor: str = 'I',
        peer_obj: object | None = None,
        ) -> Snapshot:
    """Helper to create a Snapshot for testing."""
    return Snapshot(
        peer_description=desc,
        children=children or [],
        path=path,
        query=query,
        peer_accessor=accessor,
        peer_obj=peer_obj,
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


# === Tests for Snapshot ===

class TestSnapshot:
    """Tests for the Snapshot class."""
    
    def test_can_create_basic_snapshot(self) -> None:
        """Test that a basic snapshot can be created."""
        snap = make_snapshot('Test Node')
        assert snap._peer_description == 'Test Node'
        assert snap._children == []
        assert snap._path == 'S'
    
    def test_can_create_snapshot_with_children(self) -> None:
        """Test that a snapshot can have children."""
        parent = make_snapshot('Parent', children=[
            child1 := make_snapshot('Child 1', path='S[0]'),
            child2 := make_snapshot('Child 2', path='S[1]')
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
        snap = make_snapshot('Test Description', path='S', accessor='I')
        result = repr(snap)
        assert 'Test Description' in result


# === Tests for SnapshotDiff ===

class TestSnapshotDiff:
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
            make_snapshot('New Child', path='S[0]', peer_obj=child_peer)
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
            make_snapshot('Old Child', path='S[0]', peer_obj=child_peer)
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
            make_snapshot('Child v1', path='S[0]', peer_obj=child_peer)
        ], peer_obj=parent_peer)
        new = make_snapshot('Parent', children=[
            make_snapshot('Child v2', path='S[0]', peer_obj=child_peer)
        ], peer_obj=parent_peer)
        
        diff = Snapshot.diff(old, new)
        
        assert bool(diff)
        diff_repr = repr(diff)
        assert 'S[0] ~' in diff_repr
        assert 'Child' in diff_repr
    
    def test_child_moved_without_modification(self) -> None:
        """Test that a child moving positions (but not changing) is detected."""
        parent_peer = object()
        child1_peer = object()
        child2_peer = object()
        
        old = make_snapshot('Parent', children=[
            make_snapshot('Other Child', path='S[0]', peer_obj=child2_peer),
            make_snapshot('Moved Child', path='S[1]', peer_obj=child1_peer),
        ], peer_obj=parent_peer)
        new = make_snapshot('Parent', children=[
            make_snapshot('Moved Child', path='S[0]', peer_obj=child1_peer),
            make_snapshot('Other Child', path='S[1]', peer_obj=child2_peer),
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
            make_snapshot('Child 1 v1', path='S[0]', peer_obj=child1_peer),
            make_snapshot('Child 2 v1', path='S[1]', peer_obj=child2_peer),
        ], peer_obj=parent_peer)
        new = make_snapshot('Parent', children=[
            make_snapshot('Child 1 v2', path='S[0]', peer_obj=child1_peer),
            make_snapshot('Child 2 v2', path='S[1]', peer_obj=child2_peer),
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
                make_snapshot('Grandchild v1', path='S[0][0]', peer_obj=grandchild_peer)
            ], path='S[0]', peer_obj=parent_peer)
        ], peer_obj=root_peer)
        new = make_snapshot('Root', children=[
            make_snapshot('Parent', children=[
                make_snapshot('Grandchild v2', path='S[0][0]', peer_obj=grandchild_peer)
            ], path='S[0]', peer_obj=parent_peer)
        ], peer_obj=root_peer)
        
        diff = Snapshot.diff(old, new)
        
        assert bool(diff)
        diff_repr = repr(diff)
        # TODO: Fix the following assert to pass,
        #       which ensures that any change always reports its 
        #       (potentially unchanged) ancestors as context
        #assert 'S[0] =' in diff_repr
        assert 'S[0][0] ~' in diff_repr
        assert 'Grandchild' in diff_repr
    
    def test_mixed_operations(self) -> None:
        """Test a complex scenario with additions, removals, and modifications."""
        parent_peer = object()
        keep_peer = object()
        remove_peer = object()
        modify_peer = object()
        add_peer = object()
        
        old = make_snapshot('Parent', children=[
            make_snapshot('Keep', path='S[0]', peer_obj=keep_peer),
            make_snapshot('Remove', path='S[1]', peer_obj=remove_peer),
            make_snapshot('Modify v1', path='S[2]', peer_obj=modify_peer),
        ], peer_obj=parent_peer)
        new = make_snapshot('Parent', children=[
            make_snapshot('Keep', path='S[0]', peer_obj=keep_peer),
            make_snapshot('Modify v2', path='S[1]', peer_obj=modify_peer),
            make_snapshot('Add', path='S[2]', peer_obj=add_peer),
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
    
    # TODO: Consider eliminating support for diff'ing Snapshots
    #       that lack a peer_obj
    def test_fallback_to_description_matching_when_no_peer_obj(self) -> None:
        """Test that matching falls back to description when peer_obj is None."""
        parent_peer = object()
        
        old = make_snapshot('Parent', children=[
            make_snapshot('Child A', path='S[0]', peer_obj=None),
            make_snapshot('Child B', path='S[1]', peer_obj=None),
        ], peer_obj=parent_peer)
        new = make_snapshot('Parent', children=[
            make_snapshot('Child A', path='S[0]', peer_obj=None),
            make_snapshot('Child B Modified', path='S[1]', peer_obj=None),
        ], peer_obj=parent_peer)
        
        diff = Snapshot.diff(old, new)
        
        assert bool(diff)
        # Child A should match by description, Child B should be seen as removed/added
        diff_repr = repr(diff)
        assert 'Child B' in diff_repr


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


class TestSnapshotDiffSorting:
    """Tests for the ordering of entries in SnapshotDiff output."""
    
    def test_entries_sorted_by_path(self) -> None:
        """Test that diff entries are sorted by path depth-first."""
        root_peer = object()
        child0_peer = object()
        child1_peer = object()
        grandchild_peer = object()
        
        old = make_snapshot('Root', children=[
            make_snapshot('Child 0 v1', path='S[0]', peer_obj=child0_peer),
            make_snapshot('Child 1', children=[
                make_snapshot('Grandchild v1', path='S[1][0]', peer_obj=grandchild_peer)
            ], path='S[1]', peer_obj=child1_peer),
        ], peer_obj=root_peer)
        new = make_snapshot('Root', children=[
            make_snapshot('Child 0 v2', path='S[0]', peer_obj=child0_peer),
            make_snapshot('Child 1', children=[
                make_snapshot('Grandchild v2', path='S[1][0]', peer_obj=grandchild_peer)
            ], path='S[1]', peer_obj=child1_peer),
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
            make_snapshot('Old Child', path='S[0]', peer_obj=old_child_peer),
        ], peer_obj=parent_peer)
        new = make_snapshot('Parent', children=[
            make_snapshot('New Child', path='S[0]', peer_obj=new_child_peer),
        ], peer_obj=parent_peer)
        
        diff = Snapshot.diff(old, new)
        diff_repr = repr(diff)
        
        # Deletion should come before addition
        lines = diff_repr.split('\n')
        delete_line_idx = next(i for (i, line) in enumerate(lines) if 'S[0] -' in line)
        add_line_idx = next(i for (i, line) in enumerate(lines) if 'S[0] +' in line)
        assert delete_line_idx < add_line_idx


class TestSnapshotDiffGolden:
    """Golden tests for SnapshotDiff with realistic scenarios."""
    
    def test_realistic_download_progress_scenario(self, subtests) -> None:
        """
        Golden test for a realistic download progress scenario.
        
        This test verifies the exact output format for a complex scenario
        where multiple download tasks are progressing, with items being
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
                            path='S[0][0]',
                            peer_obj=subtask_peer
                        ),
                        make_snapshot(
                            "TreeItem(👁='▼ 📂 Downloading members of group: Comic -- 27 of 2,438 item(s) -- 2:18:01 remaining (3.43s/item)')",
                            [
                                make_snapshot(
                                    "TreeItem(👁='— 📄 22 more')",
                                    path='S[0][1][0]',
                                    peer_obj=more_peer
                                ),
                                make_snapshot(
                                    "TreeItem(👁='▶︎ 📁 Downloading: https://xkcd.daarchive.net/2424/index.html -- Complete')",
                                    path='S[0][1][1]',
                                    peer_obj=item_2424_peer
                                ),
                                make_snapshot(
                                    "TreeItem(👁='▶︎ 📁 Downloading: https://xkcd.daarchive.net/2423/index.html -- Complete')",
                                    path='S[0][1][2]',
                                    peer_obj=item_2423_peer
                                ),
                                make_snapshot(
                                    "TreeItem(👁='▶︎ 📁 Downloading: https://xkcd.daarchive.net/2422/index.html -- Complete')",
                                    path='S[0][1][3]',
                                    peer_obj=item_2422_peer
                                ),
                                make_snapshot(
                                    "TreeItem(👁='▶︎ 📁 Downloading: https://xkcd.daarchive.net/2421/index.html -- Complete')",
                                    path='S[0][1][4]',
                                    peer_obj=item_2421_peer
                                ),
                                make_snapshot(
                                    "TreeItem(👁='▶︎ 📁 Downloading: https://xkcd.daarchive.net/2420/index.html -- Complete')",
                                    path='S[0][1][5]',
                                    peer_obj=item_2420_peer
                                ),
                                make_snapshot(
                                    "TreeItem(👁='▶︎ 📁 Downloading: https://xkcd.daarchive.net/1001/index.html -- Downloading')",
                                    path='S[0][1][6]',
                                    peer_obj=item_1001_peer
                                ),
                                make_snapshot(
                                    "TreeItem(👁='▶︎ 📁 Downloading: https://xkcd.daarchive.net/1002/index.html -- Queued')",
                                    path='S[0][1][7]',
                                    peer_obj=item_1002_peer
                                ),
                                make_snapshot(
                                    "TreeItem(👁='▶︎ 📁 Downloading: https://xkcd.daarchive.net/1003/index.html -- Queued')",
                                    path='S[0][1][8]',
                                    peer_obj=item_1003_peer
                                ),
                                make_snapshot(
                                    "TreeItem(👁='▶︎ 📁 Downloading: https://xkcd.daarchive.net/1004/index.html -- Queued')",
                                    path='S[0][1][9]',
                                    peer_obj=item_1004_peer
                                ),
                                make_snapshot(
                                    "TreeItem(👁='▶︎ 📁 Downloading: https://xkcd.daarchive.net/1005/index.html -- Queued')",
                                    path='S[0][1][10]',
                                    peer_obj=item_1005_peer
                                ),
                                make_snapshot(
                                    "TreeItem(👁='▶︎ 📁 Downloading: https://xkcd.daarchive.net/1006/index.html -- Queued')",
                                    path='S[0][1][11]',
                                    peer_obj=item_1006_peer
                                ),
                                make_snapshot(
                                    "TreeItem(👁='— 📄 2,310 more')",
                                    path='S[0][1][12]',
                                    peer_obj=more_end_peer
                                ),
                            ],
                            path='S[0][1]',
                            peer_obj=task_peer
                        ),
                    ],
                    path='S[0]',
                    peer_obj=task_peer
                ),
            ],
            path='S',
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
                            path='S[0][0]',
                            peer_obj=subtask_peer
                        ),
                        make_snapshot(
                            "TreeItem(👁='▼ 📂 Downloading members of group: Comic -- 30 of 2,438 item(s) -- 2:19:18 remaining (3.47s/item)')",
                            [
                                make_snapshot(
                                    "TreeItem(👁='— 📄 25 more')",
                                    path='S[0][1][0]',
                                    peer_obj=more_peer
                                ),
                                # 2424, 2423, 2422 removed (scrolled off by 3 items)
                                # 2421, 2420 stay visible and complete
                                make_snapshot(
                                    "TreeItem(👁='▶︎ 📁 Downloading: https://xkcd.daarchive.net/2421/index.html -- Complete')",
                                    path='S[0][1][1]',
                                    peer_obj=item_2421_peer
                                ),
                                make_snapshot(
                                    "TreeItem(👁='▶︎ 📁 Downloading: https://xkcd.daarchive.net/2420/index.html -- Complete')",
                                    path='S[0][1][2]',
                                    peer_obj=item_2420_peer
                                ),
                                # 1001 moved from index 6 to 3 and completed
                                make_snapshot(
                                    "TreeItem(👁='▶︎ 📁 Downloading: https://xkcd.daarchive.net/1001/index.html -- Complete')",
                                    path='S[0][1][3]',
                                    peer_obj=item_1001_peer
                                ),
                                # 1002 moved from index 7 to 4 and completed
                                make_snapshot(
                                    "TreeItem(👁='▶︎ 📁 Downloading: https://xkcd.daarchive.net/1002/index.html -- Complete')",
                                    path='S[0][1][4]',
                                    peer_obj=item_1002_peer
                                ),
                                # 1003 moved from index 8 to 5 and completed
                                make_snapshot(
                                    "TreeItem(👁='▶︎ 📁 Downloading: https://xkcd.daarchive.net/1003/index.html -- Complete')",
                                    path='S[0][1][5]',
                                    peer_obj=item_1003_peer
                                ),
                                # 1004 moved from index 9 to 6 and now downloading
                                make_snapshot(
                                    "TreeItem(👁='▶︎ 📁 Downloading: https://xkcd.daarchive.net/1004/index.html -- Downloading')",
                                    path='S[0][1][6]',
                                    peer_obj=item_1004_peer
                                ),
                                # 1005, 1006 stay queued and shifted up
                                make_snapshot(
                                    "TreeItem(👁='▶︎ 📁 Downloading: https://xkcd.daarchive.net/1005/index.html -- Queued')",
                                    path='S[0][1][7]',
                                    peer_obj=item_1005_peer
                                ),
                                make_snapshot(
                                    "TreeItem(👁='▶︎ 📁 Downloading: https://xkcd.daarchive.net/1006/index.html -- Queued')",
                                    path='S[0][1][8]',
                                    peer_obj=item_1006_peer
                                ),
                                # 1007, 1008, 1009 newly visible, queued
                                make_snapshot(
                                    "TreeItem(👁='▶︎ 📁 Downloading: https://xkcd.daarchive.net/1007/index.html -- Queued')",
                                    path='S[0][1][9]',
                                    peer_obj=item_1007_peer
                                ),
                                make_snapshot(
                                    "TreeItem(👁='▶︎ 📁 Downloading: https://xkcd.daarchive.net/1008/index.html -- Queued')",
                                    path='S[0][1][10]',
                                    peer_obj=item_1008_peer
                                ),
                                make_snapshot(
                                    "TreeItem(👁='▶︎ 📁 Downloading: https://xkcd.daarchive.net/1009/index.html -- Queued')",
                                    path='S[0][1][11]',
                                    peer_obj=item_1009_peer
                                ),
                                make_snapshot(
                                    "TreeItem(👁='— 📄 2,307 more')",
                                    path='S[0][1][12]',
                                    peer_obj=more_end_peer
                                ),
                            ],
                            path='S[0][1]',
                            peer_obj=task_peer
                        ),
                    ],
                    path='S[0]',
                    peer_obj=task_peer
                ),
            ],
            path='S',
            peer_obj=root_peer
        )
        
        expected_diff_repr_lines = [
            '# S := S',
            "S[0] ~ TreeItem(👁='▼ 📂 Downloading group: Comic -- {27→30} of 2,438 item(s) -- 2:1{→9:1}8{:01→} remaining (3.4{3→7}s/item)')",
            "S[0][1] ~ TreeItem(👁='▼ 📂 Downloading members of group: Comic -- {27→30} of 2,438 item(s) -- 2:1{→9:1}8{:01→} remaining (3.4{3→7}s/item)')",
            "S[0][1][0] ~ TreeItem(👁='— 📄 2{2→5} more')",
            "S[0][1][1] - TreeItem(👁='▶︎ 📁 Downloading: https://xkcd.daarchive.net/2424/index.html -- Complete')",
            "S[0][1][2] - TreeItem(👁='▶︎ 📁 Downloading: https://xkcd.daarchive.net/2423/index.html -- Complete')",
            "S[0][1][3] - TreeItem(👁='▶︎ 📁 Downloading: https://xkcd.daarchive.net/2422/index.html -- Complete')",
            'S[0][1][4..5 → 1..2] = More(Count=2)',
            "S[0][1][6→3] ~ TreeItem(👁='▶︎ 📁 Downloading: https://xkcd.daarchive.net/1001/index.html -- {D→C}o{wn→mp}l{oading→ete}')",
            "S[0][1][7→4] ~ TreeItem(👁='▶︎ 📁 Downloading: https://xkcd.daarchive.net/1002/index.html -- {Qu→Compl}e{u→t}e{d→}')",
            "S[0][1][8→5] ~ TreeItem(👁='▶︎ 📁 Downloading: https://xkcd.daarchive.net/1003/index.html -- {Qu→Compl}e{u→t}e{d→}')",
            "S[0][1][9→6] ~ TreeItem(👁='▶︎ 📁 Downloading: https://xkcd.daarchive.net/1004/index.html -- {Queue→Downloa}d{→ing}')",
            "S[0][1][9] + TreeItem(👁='▶︎ 📁 Downloading: https://xkcd.daarchive.net/1007/index.html -- Queued')",
            'S[0][1][10..11 → 7..8] = More(Count=2)',
            "S[0][1][10] + TreeItem(👁='▶︎ 📁 Downloading: https://xkcd.daarchive.net/1008/index.html -- Queued')",
            "S[0][1][11] + TreeItem(👁='▶︎ 📁 Downloading: https://xkcd.daarchive.net/1009/index.html -- Queued')",
            "S[0][1][12] ~ TreeItem(👁='— 📄 2,3{1→}0{→7} more')",
        ]
        
        with subtests.test(direction='forward'):
            diff = Snapshot.diff(old, new)
            diff_repr = repr(diff)
            actual_diff_repr_lines = diff_repr.split('\n')
            assert actual_diff_repr_lines == expected_diff_repr_lines
        
        expected_reverse_diff_repr_lines = [
            '# S := S',
            "S[0] ~ TreeItem(👁='▼ 📂 Downloading group: Comic -- {30→27} of 2,438 item(s) -- 2:1{9→8}:{→0}1{8→} remaining (3.4{7→3}s/item)')",
            "S[0][1] ~ TreeItem(👁='▼ 📂 Downloading members of group: Comic -- {30→27} of 2,438 item(s) -- 2:1{9→8}:{→0}1{8→} remaining (3.4{7→3}s/item)')",
            "S[0][1][0] ~ TreeItem(👁='— 📄 2{5→2} more')",
            'S[0][1][1..2 → 4..5] = More(Count=2)',
            "S[0][1][1] + TreeItem(👁='▶︎ 📁 Downloading: https://xkcd.daarchive.net/2424/index.html -- Complete')",
            "S[0][1][2] + TreeItem(👁='▶︎ 📁 Downloading: https://xkcd.daarchive.net/2423/index.html -- Complete')",
            "S[0][1][3→6] ~ TreeItem(👁='▶︎ 📁 Downloading: https://xkcd.daarchive.net/1001/index.html -- {C→D}o{mp→wn}l{ete→oading}')",
            "S[0][1][3] + TreeItem(👁='▶︎ 📁 Downloading: https://xkcd.daarchive.net/2422/index.html -- Complete')",
            "S[0][1][4→7] ~ TreeItem(👁='▶︎ 📁 Downloading: https://xkcd.daarchive.net/1002/index.html -- {Compl→Qu}e{t→u}e{→d}')",
            "S[0][1][5→8] ~ TreeItem(👁='▶︎ 📁 Downloading: https://xkcd.daarchive.net/1003/index.html -- {Compl→Qu}e{t→u}e{→d}')",
            "S[0][1][6→9] ~ TreeItem(👁='▶︎ 📁 Downloading: https://xkcd.daarchive.net/1004/index.html -- {Downloa→Queue}d{ing→}')",
            'S[0][1][7..8 → 10..11] = More(Count=2)',
            "S[0][1][9] - TreeItem(👁='▶︎ 📁 Downloading: https://xkcd.daarchive.net/1007/index.html -- Queued')",
            "S[0][1][10] - TreeItem(👁='▶︎ 📁 Downloading: https://xkcd.daarchive.net/1008/index.html -- Queued')",
            "S[0][1][11] - TreeItem(👁='▶︎ 📁 Downloading: https://xkcd.daarchive.net/1009/index.html -- Queued')",
            "S[0][1][12] ~ TreeItem(👁='— 📄 2,3{→1}0{7→} more')",
        ]
        
        with subtests.test(direction='reverse'):
            diff = Snapshot.diff(new, old)
            diff_repr = repr(diff)
            actual_diff_repr_lines = diff_repr.split('\n')
            assert actual_diff_repr_lines == expected_reverse_diff_repr_lines


class TestSnapshotDiffMoreSyntax:
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
                make_snapshot('Item1', path='S[0]', peer_obj=item1),
                make_snapshot('Item2', path='S[1]', peer_obj=item2),
                make_snapshot('Item3', path='S[2]', peer_obj=item3),
            ],
        )
        
        new = make_snapshot(
            'Root',
            [
                make_snapshot('NewItem1', path='S[0]', peer_obj=object()),
                make_snapshot('Item1', path='S[1]', peer_obj=item1),
                make_snapshot('NewItem2', path='S[2]', peer_obj=object()),
                make_snapshot('Item2', path='S[3]', peer_obj=item2),
                make_snapshot('Item3', path='S[4]', peer_obj=item3),
            ],
        )
        
        expected_diff_repr_lines = [
            '# S := S',
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
                make_snapshot('Item1', path='S[0]', peer_obj=item1),
                make_snapshot('Item2', path='S[1]', peer_obj=item2),
                make_snapshot('Item3', path='S[2]', peer_obj=item3),
            ],
        )
        
        # Items move with a gap in the middle
        new = make_snapshot(
            'Root',
            [
                make_snapshot('Item1', path='S[0]', peer_obj=item1),  # Stays at 0
                make_snapshot('NewItem', path='S[1]', peer_obj=object()),  # New item creates gap
                make_snapshot('Item2', path='S[2]', peer_obj=item2),  # Moves 1→2
                make_snapshot('Item3', path='S[3]', peer_obj=item3),  # Moves 2→3
            ],
        )
        
        expected_diff_repr_lines = [
            '# S := S',
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
                make_snapshot('Item1', path='S[0]', peer_obj=item1),
            ],
        )
        
        new = make_snapshot(
            'Root',
            [
                make_snapshot('NewItem', path='S[0]', peer_obj=object()),
                make_snapshot('Item1', path='S[1]', peer_obj=item1),
            ],
        )
        
        expected_diff_repr_lines = [
            '# S := S',
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
                make_snapshot('Item1', path='S[0]', peer_obj=item1),
                make_snapshot('Item2', path='S[1]', peer_obj=item2),
                make_snapshot('Item3', path='S[2]', peer_obj=item3),
                make_snapshot('Item4', path='S[3]', peer_obj=item4),
                make_snapshot('Item5', path='S[4]', peer_obj=item5),
            ],
        )
        
        # Two separate ranges with a gap: Items 1-2 shift to 2-3, Items 4-5 shift to 6-7
        # Item3 stays at same position creating a break in the sequence
        new = make_snapshot(
            'Root',
            [
                make_snapshot('NewItem1', path='S[0]', peer_obj=object()),
                make_snapshot('NewItem2', path='S[1]', peer_obj=object()),
                make_snapshot('Item1', path='S[2]', peer_obj=item1),
                make_snapshot('Item2', path='S[3]', peer_obj=item2),
                make_snapshot('Item3', path='S[4]', peer_obj=item3),  # Stays at relative position, breaking continuity
                make_snapshot('NewItem3', path='S[5]', peer_obj=object()),
                make_snapshot('Item4', path='S[6]', peer_obj=item4),
                make_snapshot('Item5', path='S[7]', peer_obj=item5),
            ],
        )
        
        expected_diff_repr_lines = [
            '# S := S',
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
                make_snapshot('Item1', path='S[0]', peer_obj=item1),
                make_snapshot('Item2-old', path='S[1]', peer_obj=item2),
                make_snapshot('Item3', path='S[2]', peer_obj=item3),
                make_snapshot('Item4', path='S[3]', peer_obj=item4),
            ],
        )
        
        new = make_snapshot(
            'Root',
            [
                make_snapshot('NewItem', path='S[0]', peer_obj=object()),  # Addition forces items to move
                make_snapshot('Item1', path='S[1]', peer_obj=item1),
                make_snapshot('Item2-new', path='S[2]', peer_obj=item2),  # Modified
                make_snapshot('Item3', path='S[3]', peer_obj=item3),
                make_snapshot('Item4', path='S[4]', peer_obj=item4),
            ],
        )
        
        expected_diff_repr_lines = [
            '# S := S',
            'S[0→1] = Item1',  # Not merged because Item2 is modified (breaks contiguity)
            'S[0] + NewItem',
            'S[1→2] ~ Item2-{old→new}',  # Modified, not a move
            'S[2..3 → 3..4] = More(Count=2)',  # Item3 and Item4 are merged
        ]
        
        diff = Snapshot.diff(old, new)
        diff_repr = repr(diff)
        actual_diff_repr_lines = diff_repr.split('\n')
        assert actual_diff_repr_lines == expected_diff_repr_lines
