from contextlib import contextmanager
from crystal.browser.tasktree import TaskTreeNode
import crystal.task
from crystal.tests.util.controls import click_button, TreeItem
from crystal.tests.util.data import MAX_TIME_TO_DOWNLOAD_404_URL
from crystal.tests.util.server import served_project
from crystal.tests.util.wait import tree_has_no_children_condition, wait_for, wait_while
from crystal.tests.util.windows import OpenOrCreateDialog
from crystal.model import Project, Resource, ResourceGroup, RootResource
import math
import tempfile
from typing import Iterator, List, Optional
from unittest import skip


async def test_while_downloading_large_group_then_show_no_more_than_100_download_task_children_at_once() -> None:
    # NOTE: NOT using the xkcd test data, because I want all xkcd URLs to give HTTP 404
    with served_project('testdata_bongo.cat.crystalproj.zip') as sp:
        # Define URLs
        if True:
            home_url = sp.get_request_url('https://xkcd.com/')
            
            comic_pattern = sp.get_request_url('https://xkcd.com/#/')
        
        with tempfile.TemporaryDirectory(suffix='.crystalproj') as project_dirpath:
            async with (await OpenOrCreateDialog.wait_for()).create(project_dirpath) as (mw, _):
                project = Project._last_opened_project
                assert project is not None
                
                assert 100 == TaskTreeNode._MAX_VISIBLE_CHILDREN
                assert 5 == TaskTreeNode._MAX_VISIBLE_COMPLETED_CHILDREN
                
                # Use smaller values for children counts so that the test runs faster
                SMALL_MAX_VISIBLE_CHILDREN = 3
                SMALL_MAX_VISIBLE_COMPLETED_CHILDREN = 2
                with _attr_replaced_with(TaskTreeNode, '_MAX_VISIBLE_CHILDREN', SMALL_MAX_VISIBLE_CHILDREN), \
                        _attr_replaced_with(TaskTreeNode, '_MAX_VISIBLE_COMPLETED_CHILDREN', SMALL_MAX_VISIBLE_COMPLETED_CHILDREN):
                    N = TaskTreeNode._MAX_VISIBLE_CHILDREN
                    M = TaskTreeNode._MAX_VISIBLE_COMPLETED_CHILDREN
                    
                    # Create future group members
                    for i in range(1, N + M + 1):
                        Resource(project, comic_pattern.replace('#', str(i)))
                    
                    # Create group source
                    rr = RootResource(project, 'Home', Resource(project, home_url))
                    
                    # Create group
                    g = ResourceGroup(project, 'Comic', comic_pattern)
                    g.source = rr
                    
                    root_ti = TreeItem.GetRootItem(mw.entity_tree.window)
                    assert root_ti is not None
                    
                    (_, comic_group_ti) = root_ti.Children
                    assert f'{comic_pattern} - Comic' == comic_group_ti.Text
                    
                    task_root_ti = TreeItem.GetRootItem(mw.task_tree)
                    assert task_root_ti is not None
                    
                    # Start downloading group
                    assert 0 == len(task_root_ti.Children)
                    comic_group_ti.SelectItem()
                    await mw.click_download_button()
                    
                    (download_rg_task_ti,) = task_root_ti.Children
                    assert download_rg_task_ti.Text.startswith(
                        'Downloading group: ')
                    
                    (update_rg_members_task_ti, download_rg_members_task_ti) = \
                        download_rg_task_ti.Children
                    assert update_rg_members_task_ti.Text.startswith(
                        'Finding members of group: ')
                    assert download_rg_members_task_ti.Text.startswith(
                        'Downloading members of group: ')
                    
                    # Ensure only first 100 member download tasks are visible,
                    # with a "# more" placeholder at the end
                    children = download_rg_members_task_ti.Children
                    assert len(children) == N + 1
                    assert children[0].Text.startswith(
                        f'Downloading: {comic_pattern.replace("#", "1")} --')
                    assert all([c.Text.startswith('Downloading: ') for c in children[:N]])
                    assert f'{M} more' == children[-1].Text
                    
                    # Ensure leading "# more" placeholder inserted after first task completes
                    def leading_download_statuses() -> Optional[List[bool]]:
                        leading_children = download_rg_members_task_ti.Children[:M]
                        if len(leading_children) >= 1 and leading_children[0].Text.endswith(' more'):
                            return None
                        assert all([c.Text.startswith('Downloading: ') for c in leading_children])
                        statuses = [c.Text.endswith('-- Complete') for c in leading_children]
                        return statuses
                    await wait_while(
                        leading_download_statuses,
                        total_timeout=math.inf,  # progress timeout is sufficient
                        progress_timeout=crystal.task.DELAY_BETWEEN_DOWNLOADS + MAX_TIME_TO_DOWNLOAD_404_URL)
                    children = download_rg_members_task_ti.Children
                    assert len(children) == N + 2
                    assert f'{1} more' == children[0].Text
                    assert children[1].Text.startswith(
                        f'Downloading: {comic_pattern.replace("#", "2")} --')
                    assert all([c.Text.startswith('Downloading: ') for c in children[1:(N + 1)]])
                    assert M-1 >= 1
                    assert f'{M-1} more' == children[-1].Text
                    
                    # Ensure leading "# more" placeholder increments as each task completes,
                    # until group finishes downloading
                    def loading_more_text() -> Optional[str]:
                        assert task_root_ti is not None
                        if len(task_root_ti.Children) == 0:
                            # download_rg_members_task_ti was deleted
                            return None
                        
                        first_child = download_rg_members_task_ti.GetFirstChild()
                        if first_child is None or not first_child.Text.endswith(' more'):
                            return None
                        else:
                            return first_child.Text
                    await wait_while(
                        loading_more_text,
                        total_timeout=math.inf,  # progress timeout is sufficient
                        progress_timeout=crystal.task.DELAY_BETWEEN_DOWNLOADS + MAX_TIME_TO_DOWNLOAD_404_URL)
                    assert (
                        len(task_root_ti.Children) == 0 or
                        download_rg_members_task_ti.Text.endswith('-- Complete')
                    )
                    assert (
                        len(task_root_ti.Children) == 0 or
                        download_rg_task_ti.Text.endswith('-- Complete')
                    )
                    await wait_for(tree_has_no_children_condition(mw.task_tree))


@skip('not yet automated')
async def test_when_top_level_task_finishes_then_is_removed_from_ui_soon(self) -> None:
    pass

@contextmanager
def _attr_replaced_with(obj: object, attr_name: str, value: object) -> Iterator[None]:
    old_value = getattr(obj, attr_name)
    setattr(obj, attr_name, value)
    try:
        yield
    finally:
        setattr(obj, attr_name, old_value)
