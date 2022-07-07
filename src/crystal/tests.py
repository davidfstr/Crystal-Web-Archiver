from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager, contextmanager
from crystal.os import project_appears_as_package_file
from crystal.xthreading import fg_call_and_wait
import re
import tempfile
import time
from typing import (
    AsyncIterator, Awaitable, Callable, Dict, Generator, Generic, Iterator,
    List, Optional, Tuple, TypeVar, Union,
)
from unittest import skip
import unittest.mock
import urllib.request
import urllib.error
import wx

_T = TypeVar('_T')

# === Test Runner ===

def run_test(async_test_func: Callable[[], Awaitable[None]]) -> None:
    if wx.IsMainThread():
        raise ValueError(
            'run_test() does not support being called on the wx main thread')
    
    test_co = async_test_func()  # should be a Generator[Command, None, None]
    last_command_result = None  # type: Union[object, Exception]
    while True:
        try:
            command = fg_call_and_wait(
                lambda: test_co.send(last_command_result)  # type: ignore[attr-defined]
            )
        except StopIteration:
            break
        if not isinstance(command, Command):
            raise ValueError(
                'Async test function did yield something that was '
                f'not a Command: {command!r}')
        try:
            last_command_result = command.run()
        except Exception as e:
            last_command_result = e

@asyncio.coroutine
def bg_sleep(  # type: ignore[misc]  # ignore non-Generator return type here
        duration: float
        ) -> Awaitable[None]:  # or Generator[Command, object, None]
    """
    Switch to a background thread, sleep for the specified duration, and
    then resume this foreground thread.
    """
    assert wx.IsMainThread()
    
    none_or_error = yield SleepCommand(duration)
    if none_or_error is None:
        return
    elif isinstance(none_or_error, Exception):
        raise none_or_error
    else:
        raise AssertionError()

@asyncio.coroutine
def bg_fetch_url(  # type: ignore[misc]  # ignore non-Generator return type here
    url: str,
    *, headers: Optional[Dict[str, str]]=None,
    timeout: float,
    ) -> Awaitable[WebPage]:  # or Generator[Command, object, WebPage]
    """
    Switch to a background thread, fetch the specified URL, and
    then resume this foreground thread.
    """
    assert wx.IsMainThread()
    
    page_or_error = yield FetchUrlCommand(url, headers, timeout)
    if isinstance(page_or_error, WebPage):
        return page_or_error
    elif isinstance(page_or_error, Exception):
        raise page_or_error
    else:
        raise AssertionError()

class Command(Generic[_T]):  # abstract
    def run(self) -> _T:
        raise NotImplementedError()

class SleepCommand(Command[None]):
    def __init__(self, delay: float) -> None:
        self._delay = delay
    
    def run(self) -> None:
        assert not wx.IsMainThread()
        
        time.sleep(self._delay)

class FetchUrlCommand(Command['WebPage']):
    def __init__(self, url: str, headers: Optional[Dict[str, str]], timeout: float) -> None:
        self._url = url
        self._headers = headers
        self._timeout = timeout
    
    def run(self) -> WebPage:
        assert not wx.IsMainThread()
        
        try:
            response_stream = urllib.request.urlopen(
                urllib.request.Request(
                    self._url,
                    headers=(self._headers or {})
                ),
                timeout=self._timeout)
        except urllib.error.HTTPError as e:
            response_stream = e
        with response_stream as response:
            response_text = response.read().decode('utf-8')
        return WebPage(response_stream.status, response_text)

# === Tests ===

async def test_can_download_and_serve_a_static_site() -> None:
    """
    Test that can successfully download and serve a mostly-static site.
    
    Example site: https://xkcd.com/
    """
    assert wx.IsMainThread()
    
    # TODO: Use a pre-downloaded version of xkcd rather than the real xkcd
    if True:
        home_url = 'https://xkcd.com/'
        
        comic1_url = 'https://xkcd.com/1/'
        comic2_url = 'https://xkcd.com/2/'
        comic_pattern = 'https://xkcd.com/#/'
        
        atom_feed_url = 'https://xkcd.com/atom.xml'
        rss_feed_url = 'https://xkcd.com/rss.xml'
        feed_pattern = 'https://xkcd.com/*.xml'
    
    with tempfile.TemporaryDirectory(suffix='.crystalproj') as project_dirpath:
        # 1. Test can create project
        # 2. Test can quit
        async with (await OpenOrCreateDialog.wait_for()).create(project_dirpath) as (mw, _):
            assert False == mw.readonly
            
            # Test can create root resource
            if True:
                root_ti = TreeItem.GetRootItem(mw.entity_tree)
                assert root_ti is not None
                assert root_ti.GetFirstChild() is None  # no entities
                
                click_button(mw.add_url_button)
                add_url_dialog = await wait_for(window_condition('cr-add-url-dialog'))  # type: wx.Window
                name_field = add_url_dialog.FindWindowByName('cr-add-url-dialog__name-field')
                assert isinstance(name_field, wx.TextCtrl)
                url_field = add_url_dialog.FindWindowByName('cr-add-url-dialog__url-field')
                assert isinstance(url_field, wx.TextCtrl)
                ok_button = add_url_dialog.FindWindowById(wx.ID_OK)
                assert isinstance(ok_button, wx.Button)
                
                name_field.Value = 'Home'
                url_field.Value = home_url
                click_button(ok_button)
                home_ti = root_ti.GetFirstChild()
                assert home_ti is not None  # entity was created
                assert f'{home_url} - Home' == home_ti.Text
            
            # Test can view resource (that has zero downloaded revisions)
            home_ti.SelectItem()
            home_request_url = get_request_url(home_url)
            assert 'http://localhost:2797/_/https/xkcd.com/' == home_request_url
            with assert_does_open_webbrowser_to(home_request_url):
                click_button(mw.view_button)
            assert True == (await is_url_not_in_archive(home_url))
            
            # Test can download root resource (using download button)
            assert home_ti.id == mw.entity_tree.GetSelection()
            click_button(mw.download_button)
            await wait_for_download_to_start_and_finish(mw.task_tree)
            
            # Test can view resource (that has a downloaded revision)
            assert False == (await is_url_not_in_archive(home_url))
            
            # Test can re-download resource (by expanding tree node)
            home_ti.Expand()
            await wait_for(first_child_of_tree_item_is_not_loading_condition(home_ti))
            await wait_for(tree_has_no_children_condition(mw.task_tree))
            (comic1_ti,) = [
                child for child in home_ti.Children
                if child.Text.startswith(f'{comic1_url} - ')
            ]  # ensure did find sub-resource for Comic #1
            assert f'{comic1_url} - Link: |<, Link: |<' == comic1_ti.Text  # title format of sub-resource
            
            # Test can download resource (by expanding tree node)
            if True:
                comic1_ti.Expand()
                await wait_for_download_to_start_and_finish(mw.task_tree)
                assert first_child_of_tree_item_is_not_loading_condition(comic1_ti)()
                
                (comic2_ti,) = [
                    child for child in comic1_ti.Children
                    if child.Text.startswith(f'{comic2_url} - ')
                ]  # ensure did find sub-resource for Comic #2
                assert f'{comic2_url} - Link: Next >, Link: Next >' == comic2_ti.Text  # title format of sub-resource
                
                comic1_ti.Collapse()
            
            # Test can create resource group (using selected resource as template)
            if True:
                comic1_ti.SelectItem()
                
                click_button(mw.add_group_button)
                agd = await AddGroupDialog.wait_for()
                
                assert '' == agd.name_field.Value  # default name = (nothing)
                assert comic1_url == agd.pattern_field.Value  # default pattern = (from resource)
                selection_ci = agd.source_field.GetSelection()
                assert selection_ci != wx.NOT_FOUND
                assert 'Home' == agd.source_field.GetString(selection_ci)  # default source = (from resource parent)
                assert agd.name_field.HasFocus  # default focused field
                
                agd.name_field.Value = 'Comic'
                
                assert not agd.preview_members_pane.IsExpanded()  # collapsed by default
                agd.preview_members_pane.Expand()
                member_urls = [
                    agd.preview_members_list.GetString(i)
                    for i in range(agd.preview_members_list.GetCount())
                ]
                assert [comic1_url] == member_urls  # contains exact match of pattern
                
                agd.pattern_field.Value = comic_pattern
                
                member_urls = [
                    agd.preview_members_list.GetString(i)
                    for i in range(agd.preview_members_list.GetCount())
                ]
                assert comic1_url in member_urls  # contains first comic
                assert len(member_urls) >= 2  # contains last comic too
                
                await agd.ok()
                
                # Ensure the new resource group does now group sub-resources
                if True:
                    (grouped_subresources_ti,) = [
                        child for child in home_ti.Children
                        if child.Text.startswith(f'{comic_pattern} - ')
                    ]  # ensure did find grouped sub-resources
                    assert f'{comic_pattern} - Comic' == grouped_subresources_ti.Text  # title format of grouped sub-resources
                    
                    grouped_subresources_ti.Expand()
                    await wait_for(first_child_of_tree_item_is_not_loading_condition(grouped_subresources_ti))
                    
                    (comic1_ti,) = [
                        child for child in grouped_subresources_ti.Children
                        if child.Text.startswith(f'{comic1_url} - ')
                    ]  # contains first comic
                    assert len(grouped_subresources_ti.Children) >= 2  # contains last comic too
                    
                    grouped_subresources_ti.Collapse()
                
                home_ti.Collapse()
                
                # Ensure the new resource group appears at the root of the entity tree
                (comic_group_ti,) = [
                    child for child in root_ti.Children
                    if child.Text.startswith(f'{comic_pattern} - ')
                ]  # ensure did find resource group at root of entity tree
                assert f'{comic_pattern} - Comic' == comic_group_ti.Text  # title format of resource group
                
                comic_group_ti.Expand()
                await wait_for(first_child_of_tree_item_is_not_loading_condition(comic_group_ti))
                
                # Ensure the new resource group does contain the expected members
                (comic1_ti,) = [
                    child for child in comic_group_ti.Children
                    if child.Text == f'{comic1_url}'
                ]  # contains first comic
                assert len(comic_group_ti.Children) >= 2  # contains last comic too
                
                comic_group_ti.Collapse()
            
            # Test can download resource group
            if True:
                # Create small resource group (with only 2 members)
                if True:
                    home_ti.Expand()
                    await wait_for(first_child_of_tree_item_is_not_loading_condition(home_ti))
                    
                    (atom_feed_ti,) = [
                        child for child in home_ti.Children
                        if child.Text.startswith(f'{atom_feed_url} - ')
                    ]  # contains atom feed
                    (rss_feed_ti,) = [
                        child for child in home_ti.Children
                        if child.Text.startswith(f'{rss_feed_url} - ')
                    ]  # contains rss feed
                    
                    atom_feed_ti.SelectItem()
                    
                    click_button(mw.add_group_button)
                    agd = await AddGroupDialog.wait_for()
                    
                    agd.name_field.Value = 'Feed'
                    agd.pattern_field.Value = feed_pattern
                    await agd.ok()
                    
                    home_ti.Collapse()
                    
                    (feed_group_ti,) = [
                        child for child in root_ti.Children
                        if child.Text.startswith(f'{feed_pattern} - ')
                    ]
                    
                    feed_group_ti.Expand()
                    await wait_for(first_child_of_tree_item_is_not_loading_condition(feed_group_ti))
                    (atom_feed_ti,) = [
                        child for child in feed_group_ti.Children
                        if child.Text == f'{atom_feed_url}'
                    ]
                    (rss_feed_ti,) = [
                        child for child in feed_group_ti.Children
                        if child.Text == f'{rss_feed_url}'
                    ]
                    assert 2 == len(feed_group_ti.Children)  # == [atom feed, rss feed]
                    
                    feed_group_ti.Collapse()
                
                assert True == (await is_url_not_in_archive(atom_feed_url))
                assert True == (await is_url_not_in_archive(rss_feed_url))
                
                feed_group_ti.SelectItem()
                click_button(mw.download_button)
                await wait_for_download_to_start_and_finish(mw.task_tree)
                
                assert False == (await is_url_not_in_archive(atom_feed_url))
                assert False == (await is_url_not_in_archive(rss_feed_url))
        
        # Test can open project (as writable)
        async with (await OpenOrCreateDialog.wait_for()).open(project_dirpath) as mw:
            assert False == mw.readonly
            
            root_ti = TreeItem.GetRootItem(mw.entity_tree)
            assert root_ti is not None
            
            # Start server
            (home_ti,) = [
                child for child in root_ti.Children
                if child.Text.startswith(f'{home_url} - ')
            ]
            home_ti.SelectItem()
            with assert_does_open_webbrowser_to(get_request_url(home_url)):
                click_button(mw.view_button)
            
            # Test can still view resource (that has a downloaded revision)
            assert False == (await is_url_not_in_archive(home_url))
            
            # Test can still re-download resource (by expanding tree node)
            home_ti.Expand()
            await wait_for(first_child_of_tree_item_is_not_loading_condition(home_ti))
            await wait_for(tree_has_no_children_condition(mw.task_tree))
            (grouped_subresources_ti,) = [
                child for child in home_ti.Children
                if child.Text.startswith(f'{comic_pattern} - ')
            ]
            
            # Test can forget resource group
            if True:
                grouped_subresources_ti.SelectItem()
                click_button(mw.forget_button)
                
                # Ensure the forgotten resource group no longer groups sub-resources
                () = [
                    child for child in home_ti.Children
                    if child.Text.startswith(f'{comic_pattern} - ')
                ]  # ensure did not find grouped sub-resources
                (comic1_ti,) = [
                    child for child in home_ti.Children
                    if child.Text.startswith(f'{comic1_url} - ')
                ]  # ensure did find sub-resource for Comic #1
                
                # Ensure the forgotten resource group no longer appears at the root of the entity tree
                home_ti.Collapse()
                () = [
                    child for child in root_ti.Children
                    if child.Text.startswith(f'{comic_pattern} - ')
                ]  # ensure did not find resource group at root of entity tree
            
            # Test can forget root resource
            if True:
                home_ti.SelectItem()
                click_button(mw.forget_button)
                
                # Ensure the forgotten root resource no longer appears at the root of the entity tree
                () = [
                    child for child in root_ti.Children
                    if child.Text.startswith(f'{home_url} - ')
                ]  # ensure did not find resource
                
                # Ensure that the resource for the forgotten root resource is NOT deleted
                assert False == (await is_url_not_in_archive(home_url))
        
        # Test can open project (as read only)
        async with (await OpenOrCreateDialog.wait_for()).open(project_dirpath, readonly=True) as mw:
            assert True == mw.readonly
            
            root_ti = TreeItem.GetRootItem(mw.entity_tree)
            assert root_ti is not None
            
            # 1. Test cannot add new root resource in read-only project
            # 2. Test cannot add new resource group in read-only project
            selected_ti = TreeItem.GetSelection(mw.entity_tree)
            # NOTE: Cannot test the selection on Windows
            #assert (selected_ti is None) or (selected_ti == root_ti)
            assert False == mw.add_url_button.IsEnabled()
            assert False == mw.add_group_button.IsEnabled()
            
            # Test cannot download/forget existing resource in read-only project
            if True:
                (feed_group_ti,) = [
                    child for child in root_ti.Children
                    if child.Text.startswith(f'{feed_pattern} - ')
                ]
                
                feed_group_ti.Expand()
                await wait_for(first_child_of_tree_item_is_not_loading_condition(feed_group_ti))
                
                (atom_feed_ti,) = [
                    child for child in feed_group_ti.Children
                    if child.Text == f'{atom_feed_url}'
                ]
                
                atom_feed_ti.SelectItem()
                assert False == mw.download_button.IsEnabled()
                assert False == mw.forget_button.IsEnabled()
            
            # Test cannot download/update/forget existing resource group in read-only project
            feed_group_ti.SelectItem()
            assert False == mw.download_button.IsEnabled()
            assert False == mw.update_membership_button.IsEnabled()
            assert False == mw.forget_button.IsEnabled()
            
            # Start server
            atom_feed_ti.SelectItem()
            with assert_does_open_webbrowser_to(get_request_url(atom_feed_url)):
                click_button(mw.view_button)
            
            # Test can still view resource (that has a downloaded revision)
            assert False == (await is_url_not_in_archive(atom_feed_url))

@skip('not yet automated')
def test_can_download_and_serve_a_site_requiring_dynamic_url_discovery() -> None:
    """
    Tests that can successfully download and serve a site containing
    JavaScript which dynamically fetches URLs that cannot be discovered
    statically by Crystal.
    
    Example site: https://bongo.cat/
    """
    pass

# === Utility: Window Abstractions ===

class OpenOrCreateDialog(object):
    open_or_create_project_dialog: wx.Dialog
    open_as_readonly: wx.CheckBox
    open_button: wx.Button
    create_button: wx.Button
    
    @staticmethod
    async def wait_for() -> OpenOrCreateDialog:
        self = OpenOrCreateDialog(ready=True)
        open_or_create_project_dialog = await wait_for(window_condition(
            'cr-open-or-create-project'))  # type: wx.Window
        assert isinstance(open_or_create_project_dialog, wx.Dialog)
        self.open_as_readonly = open_or_create_project_dialog.FindWindowByName(
            'cr-open-or-create-project__checkbox')
        assert isinstance(self.open_as_readonly, wx.CheckBox)
        self.open_button = open_or_create_project_dialog.FindWindowById(wx.ID_YES)
        assert isinstance(self.open_button, wx.Button)
        self.create_button = open_or_create_project_dialog.FindWindowById(wx.ID_NO)
        assert isinstance(self.create_button, wx.Button)
        return self
    
    def __init__(self, *, ready: bool=False) -> None:
        assert ready, 'Did you mean to use OpenOrCreateDialog.wait_for()?'
    
    @asynccontextmanager
    async def create(self, 
            project_dirpath: Optional[str]=None
            ) -> AsyncIterator[Tuple[MainWindow, str]]:
        if project_dirpath is None:
            with tempfile.TemporaryDirectory(suffix='.crystalproj') as project_dirpath:
                assert project_dirpath is not None
                async with self.create(project_dirpath) as (mw, project_dirpath):
                    yield (mw, project_dirpath)
            return
        
        with file_dialog_returning(project_dirpath):
            click_button(self.create_button)
            
            mw = await MainWindow.wait_for()
        
        yield (mw, project_dirpath)
        
        await mw.close()
    
    @asynccontextmanager
    async def open(self, 
            project_dirpath: str, 
            *, readonly: Optional[bool]=None
            ) -> AsyncIterator[MainWindow]:
        if readonly is not None:
            self.open_as_readonly.Value = readonly
        
        with package_dialog_returning(project_dirpath):
            click_button(self.open_button)
            
            mw = await MainWindow.wait_for()
        
        yield mw
        
        await mw.close()

class MainWindow(object):
    main_window: wx.Frame
    entity_tree: wx.TreeCtrl
    add_url_button: wx.Button
    add_group_button: wx.Button
    forget_button: wx.Button
    download_button: wx.Button
    update_membership_button: wx.Button
    view_button: wx.Button
    task_tree: wx.TreeCtrl
    read_write_icon: wx.StaticText
    
    @staticmethod
    async def wait_for() -> MainWindow:
        self = MainWindow(ready=True)
        self.main_window = await wait_for(window_condition('cr-main-window'))
        assert isinstance(self.main_window, wx.Frame)
        self.entity_tree = self.main_window.FindWindowByName('cr-entity-tree')
        assert isinstance(self.entity_tree, wx.TreeCtrl)
        self.add_url_button = self.main_window.FindWindowByName('cr-add-url-button')
        assert isinstance(self.add_url_button, wx.Button)
        self.add_group_button = self.main_window.FindWindowByName('cr-add-group-button')
        assert isinstance(self.add_group_button, wx.Button)
        self.forget_button = self.main_window.FindWindowByName('cr-forget-button')
        assert isinstance(self.forget_button, wx.Button)
        self.download_button = self.main_window.FindWindowByName('cr-download-button')
        assert isinstance(self.download_button, wx.Button)
        self.update_membership_button = self.main_window.FindWindowByName('cr-update-membership-button')
        assert isinstance(self.update_membership_button, wx.Button)
        self.view_button = self.main_window.FindWindowByName('cr-view-button')
        assert isinstance(self.view_button, wx.Button)
        self.task_tree = self.main_window.FindWindowByName('cr-task-tree')
        assert isinstance(self.task_tree, wx.TreeCtrl)
        self.read_write_icon = self.main_window.FindWindowByName('cr-read-write-icon')
        assert isinstance(self.read_write_icon, wx.StaticText)
        return self
    
    def __init__(self, *, ready: bool=False) -> None:
        assert ready, 'Did you mean to use MainWindow.wait_for()?'
    
    @property
    def readonly(self) -> bool:
        label = self.read_write_icon.Label  # cache
        if label in ['🔒', 'Read only']:
            return True
        elif label in ['✏️', 'Writable']:
            return False
        else:
            raise AssertionError()
    
    async def close(self) -> None:
        self.main_window.Close()
        await wait_for(lambda: self.main_window.IsBeingDeleted)
        await wait_for(lambda: not self.main_window.IsShown)
        await wait_for(not_condition(window_condition('cr-main-window')))

class AddGroupDialog(object):
    name_field: wx.TextCtrl
    pattern_field: wx.TextCtrl
    source_field: wx.Choice
    preview_members_pane: wx.CollapsiblePane
    preview_members_list: wx.ListBox
    ok_button: wx.Button
    
    @staticmethod
    async def wait_for() -> AddGroupDialog:
        self = AddGroupDialog(ready=True)
        add_group_dialog = await wait_for(window_condition('cr-add-group-dialog'))  # type: wx.Window
        self.name_field = add_group_dialog.FindWindowByName('cr-add-group-dialog__name-field')
        assert isinstance(self.name_field, wx.TextCtrl)
        self.pattern_field = add_group_dialog.FindWindowByName('cr-add-group-dialog__pattern-field')
        assert isinstance(self.pattern_field, wx.TextCtrl)
        self.source_field = add_group_dialog.FindWindowByName('cr-add-group-dialog__source-field')
        assert isinstance(self.source_field, wx.Choice)
        self.preview_members_pane = add_group_dialog.FindWindowByName('cr-add-group-dialog__preview-members')
        assert isinstance(self.preview_members_pane, wx.CollapsiblePane)
        self.preview_members_list = add_group_dialog.FindWindowByName('cr-add-group-dialog__preview-members__list')
        assert isinstance(self.preview_members_list, wx.ListBox)
        self.ok_button = add_group_dialog.FindWindowById(wx.ID_OK)
        assert isinstance(self.ok_button, wx.Button)
        return self
    
    def __init__(self, *, ready: bool=False) -> None:
        assert ready, 'Did you mean to use AddGroupDialog.wait_for()?'
    
    async def ok(self) -> None:
        click_button(self.ok_button)
        await wait_for(not_condition(window_condition('cr-add-group-dialog')))

# === Utility: Wait for Download ===

async def wait_for_download_to_start_and_finish(
        task_tree: wx.TreeCtrl,
        total_timeout: Optional[float]=None,
        ) -> None:
    from crystal.task import DELAY_BETWEEN_DOWNLOADS
    
    max_download_duration_per_standard_item = (
        0.5 +  # fetch + parse time
        DELAY_BETWEEN_DOWNLOADS
    ) * 2
    max_download_duration_per_large_item = (
        max_download_duration_per_standard_item * 4  # TODO: allow caller to tune
    )
    max_large_item_count = 1  # TODO: allow caller to tune
    period = _DEFAULT_WAIT_PERIOD
    
    # Wait for start of download
    await wait_for(tree_has_children_condition(task_tree))
    
    # Determine how many items are being downloaded
    item_count: int
    first_task_title_func = first_task_title_progression(task_tree)
    observed_titles = []  # type: List[str]
    while True:
        download_task_title = first_task_title_func()
        if download_task_title is None:
            raise AssertionError(
                'Download finished early without finding sub-resources. '
                'Did the download fail? '
                f'Task titles observed were: {observed_titles}')
        if download_task_title not in observed_titles:
            observed_titles.append(download_task_title)
        
        m = re.fullmatch(
            r'^Downloading(?: group)?: (.*?) -- (?:(\d+) of (\d+) item\(s\)|(.*))$',
            download_task_title)
        if m is None:
            raise AssertionError(
                f'Expected first task to be a download task but found task with title: '
                f'{download_task_title}')
        if m.group(4) is not None:
            pass  # keep waiting
        else:
            item_count = int(m.group(3))
            break
        
        await bg_sleep(period)
        continue
    
    large_item_count = min(max_large_item_count, item_count)
    standard_item_count = item_count - large_item_count
    
    # Wait while downloading
    await wait_while(
        first_task_title_func,
        total_timeout=(
            (max_download_duration_per_standard_item * standard_item_count) +
            (max_download_duration_per_large_item * large_item_count)
        ),
        total_timeout_message=lambda: (
            f'Resource download timed out: '
            f'Gave up at status: {first_task_title_func()!r}'
        ),
        progress_timeout=max(
            max_download_duration_per_standard_item,
            max_download_duration_per_large_item,
        ),
        progress_timeout_message=lambda: (
            f'Subresource download timed out: '
            f'Stuck at status: {first_task_title_func()!r}'
        ),
        period=period,
    )
    
    # Ensure did finish downloading
    assert tree_has_no_children_condition(task_tree)()

# === Utility: Wait While ===

async def wait_while(
        progression_func: Callable[[], Optional[_T]],
        total_timeout: Optional[float]=None,
        *, total_timeout_message: Optional[Callable[[], str]]=None,
        progress_timeout: Optional[float]=None,
        progress_timeout_message: Optional[Callable[[], str]]=None,
        period: Optional[float]=None,
        ) -> None:
    """
    Waits while the specified progression returns different non-None values
    at least every `progress_timeout` seconds, checking every `period` seconds,
    until a None value is returned, or the `total_timeout` expires.
    
    Raises:
    * WaitTimedOut -- 
        if either:
            1. the `progress_timeout` expires while waiting for
               a differing value from the specified progression
            2. the `total_timeout` expires while waiting for
               the progression to complete.
    """
    if total_timeout is None:
        total_timeout = _DEFAULT_WAIT_TIMEOUT
    
    last_status = progression_func()
    if last_status is None:
        return  # done
    
    def do_check_status() -> Optional[bool]:
        nonlocal last_status
        
        current_status = progression_func()
        if current_status is None:
            return True  # done
        
        changed_status = (current_status != last_status)  # capture
        last_status = current_status  # reinterpret
        
        if changed_status:
            return False  # progress
        else:
            return None  # no progress
    
    start_time = time.time()  # capture
    while True:
        is_done = (await wait_for(
            do_check_status,
            timeout=progress_timeout,
            period=period,
            message=progress_timeout_message,
        ))  # type: bool
        if is_done:
            return
        
        delta_time = time.time() - start_time
        if delta_time > total_timeout:
            raise (
                WaitTimedOut(total_timeout_message())
                if total_timeout_message is not None
                else WaitTimedOut()
            )

def first_task_title_progression(task_tree: wx.TreeCtrl) -> Callable[[], Optional[str]]:
    def first_task_title():
        root_ti = TreeItem.GetRootItem(task_tree)
        assert root_ti is not None
        first_task_ti = root_ti.GetFirstChild()
        if first_task_ti is None:
            return None  # done
        return first_task_ti.Text
    return first_task_title

# === Utility: Wait For ===

_DEFAULT_WAIT_TIMEOUT = 2.0  # arbitrary
_DEFAULT_WAIT_PERIOD = 0.1  # arbitrary

async def wait_for(
        condition: Callable[[], Optional[_T]],
        timeout: Optional[float]=None,
        *, period: Optional[float]=None,
        message: Optional[Callable[[], str]]=None,
        ) -> _T:
    """
    Waits up to `timeout` seconds for the specified condition to become non-None,
    returning the result of the condition, checking every `period` seconds.
    
    Raises:
    * WaitTimedOut -- if the timeout expires before the condition becomes non-None
    """
    if timeout is None:
        timeout = _DEFAULT_WAIT_TIMEOUT
    if period is None:
        period = _DEFAULT_WAIT_PERIOD
    
    start_time = time.time()  # capture
    while True:
        condition_result = condition()
        if condition_result is not None:
            return condition_result
        
        delta_time = time.time() - start_time
        if delta_time > timeout:
            raise (
                WaitTimedOut(message())
                if message is not None
                else WaitTimedOut()
            )
        
        await bg_sleep(period)

class WaitTimedOut(Exception):
    pass

def window_condition(name: str, *, hidden_ok: bool=False) -> Callable[[], Optional[wx.Window]]:
    def window() -> Optional[wx.Window]:
        window = wx.FindWindowByName(name)  # type: Optional[wx.Window]
        if window is None:
            return None
        if not hidden_ok and not window.IsShown():
            return None
        return window
    return window

def first_child_of_tree_item_is_not_loading_condition(
        ti: TreeItem
        ) -> Callable[[], Optional[wx.TreeItemId]]:
    def first_child_of_tree_item_is_not_loading() -> Optional[TreeItem]:
        first_child_ti = ti.GetFirstChild()
        if first_child_ti is None:
            return None
        if first_child_ti.Text == 'Loading...':
            return None
        return first_child_ti
    return first_child_of_tree_item_is_not_loading

def tree_has_children_condition(
        tree: wx.TreeCtrl, 
        ) -> Callable[[], Optional[bool]]:
    return not_condition(tree_has_no_children_condition(tree))

def tree_has_no_children_condition(
        tree: wx.TreeCtrl, 
        ) -> Callable[[], Optional[bool]]:
    return tree_item_has_no_children_condition(tree, tree.GetRootItem())

def tree_item_has_no_children_condition(
        # TODO: Use TreeItem rather than (wx.TreeCtrl, wx.TreeItemId) pair
        tree: wx.TreeCtrl, 
        tii: wx.TreeItemId
        ) -> Callable[[], Optional[bool]]:
    def tree_item_has_no_children() -> Optional[bool]:
        first_child_tii = tree.GetFirstChild(tii)[0]
        if not first_child_tii.IsOk():
            return True
        else:
            return None
    return tree_item_has_no_children

def not_condition(condition: Callable[[], Optional[_T]]) -> Callable[[], Optional[bool]]:
    def not_() -> Optional[bool]:
        if condition():
            return None
        else:
            return True
    return not_

# === Utility: Controls: wx.Button ===

def click_button(button: wx.Button) -> None:
    event = wx.PyCommandEvent(wx.EVT_BUTTON.typeId, button.GetId())
    event.SetEventObject(button)
    assert event.GetEventObject().GetId() == button.GetId()
    
    button.Command(event)

# === Utility: Controls: wx.FileDialog, wx.DirDialog ===

@contextmanager
def package_dialog_returning(filepath: str) -> Iterator[None]:
    if project_appears_as_package_file():
        with file_dialog_returning(filepath):
            yield
    else:
        with dir_dialog_returning(filepath):
            yield

@contextmanager
def file_dialog_returning(filepath: str) -> Iterator[None]:
    with unittest.mock.patch('wx.FileDialog', spec=True) as MockFileDialog:
        instance = MockFileDialog.return_value
        instance.ShowModal.return_value = wx.ID_OK
        instance.GetPath.return_value = filepath
        
        yield

@contextmanager
def dir_dialog_returning(filepath: str) -> Iterator[None]:
    with unittest.mock.patch('wx.DirDialog', spec=True) as MockDirDialog:
        instance = MockDirDialog.return_value
        instance.ShowModal.return_value = wx.ID_OK
        instance.GetPath.return_value = filepath
        
        yield

# === Utility: Controls: wx.TreeCtrl ===

def get_children_of_tree_item(tree: wx.TreeCtrl, tii: wx.TreeItemId) -> List[TreeItem]:
    children = []  # type: List[TreeItem]
    next_child_tii = tree.GetFirstChild(tii)[0]
    while next_child_tii.IsOk():
        children.append(TreeItem(tree, next_child_tii))
        next_child_tii = tree.GetNextSibling(next_child_tii)  # reinterpret
    return children

class TreeItem(object):
    __slots__ = ['tree', 'id']
    
    def __init__(self, tree: wx.TreeCtrl, id: wx.TreeItemId) -> None:
        self.tree = tree
        self.id = id
    
    @property
    def Text(self) -> str:
        return self.tree.GetItemText(self.id)
    
    def SelectItem(self) -> None:
        self.tree.SelectItem(self.id)
    
    @staticmethod
    def GetSelection(tree: wx.TreeCtrl) -> Optional[TreeItem]:
        selected_tii = tree.GetSelection()
        if selected_tii.IsOk():
            return TreeItem(tree, selected_tii)
        else:
            return None
    
    def Expand(self) -> None:
        self.tree.Expand(self.id)
    
    def Collapse(self) -> None:
        self.tree.Collapse(self.id)
    
    @staticmethod
    def GetRootItem(tree: wx.TreeCtrl) -> Optional[TreeItem]:
        root_tii = tree.GetRootItem()
        if root_tii.IsOk():
            return TreeItem(tree, root_tii)
        else:
            return None
    
    def GetFirstChild(self) -> Optional[TreeItem]:
        first_child_tii = self.tree.GetFirstChild(self.id)[0]
        if first_child_tii.IsOk():
            return TreeItem(self.tree, first_child_tii)
        else:
            return None
    
    @property
    def Children(self) -> List[TreeItem]:
        return get_children_of_tree_item(self.tree, self.id)
    
    def __eq__(self, other: object) -> bool:
        # wx.TreeItemId does not support equality comparison on Windows
        return NotImplemented

# === Utility: Server ===

@contextmanager
def assert_does_open_webbrowser_to(request_url: str) -> Iterator[None]:
    with unittest.mock.patch('webbrowser.open', spec=True) as mock_open:
        yield
        mock_open.assert_called_with(request_url)

def get_request_url(archive_url: str) -> str:
    from crystal.model import Project
    import crystal.server
    
    # TODO: Alter API crystal.server.get_request_url() to accept
    #       default_url_prefix as parameter rather than a whole Project,
    #       so that we don't have to mock a whole Project here.
    project = unittest.mock.MagicMock(spec=Project)
    project.default_url_prefix = None
    
    request_url = crystal.server.get_request_url(archive_url, project)
    return request_url

async def is_url_not_in_archive(archive_url: str) -> bool:
    server_page = await fetch_archive_url(
        archive_url, 
        headers={'X-Crystal-Dynamic': 'False'})
    return server_page.is_not_in_archive

async def fetch_archive_url(
        archive_url: str,
        *, headers: Optional[Dict[str, str]]=None,
        timeout: Optional[float]=None,
        ) -> WebPage:
    if timeout is None:
        timeout = _DEFAULT_WAIT_TIMEOUT
    return await bg_fetch_url(get_request_url(archive_url), headers=headers, timeout=timeout)

class WebPage(object):
    def __init__(self, status: int, content: str) -> None:
        self._status = status
        self._content = content
    
    @property
    def is_not_in_archive(self) -> bool:
        return (
            self._status == 404 and
            self.title == 'Not in Archive | Crystal Web Archiver'
        )
    
    @property
    def title(self) -> Optional[str]:
        # TODO: Use an HTML parser to improve robustness
        m = re.search(r'<title>([^<]*)</title>', self._content)
        if m is None:
            return None
        else:
            return m.group(1).strip()
