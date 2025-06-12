"""Tests for DownloadResourceTask and DownloadResourceGroupTask"""

from contextlib import redirect_stderr
from crystal.model import Project, Resource
import crystal.task
from crystal.tests.util.asserts import assertEqual
from crystal.tests.util.controls import click_button, TreeItem
from crystal.tests.util.runner import bg_sleep
from crystal.tests.util.server import MockHttpServer, served_project
from crystal.tests.util.tasks import wait_for_download_to_start_and_finish
from crystal.tests.util.wait import DEFAULT_WAIT_PERIOD, wait_for
from crystal.tests.util.windows import NewGroupDialog, OpenOrCreateDialog
import io
import os
import tempfile
from textwrap import dedent
from unittest import skip
from unittest.mock import patch

_FAVICON_PATH = '/favicon.ico'


# ------------------------------------------------------------------------------
# Resource.download() Tests

@skip('covered by: test_given_downloading_resource_when_start_download_resource_then_existing_download_task_returned')
async def test_given_not_downloading_resource_when_start_download_resource_then_download_task_created_and_returned() -> None:
    pass


async def test_given_downloading_resource_when_start_download_resource_then_existing_download_task_returned() -> None:
    with served_project('testdata_xkcd.crystalproj.zip') as sp:
        # Define URLs
        home_url = sp.get_request_url('https://xkcd.com/')
        
        async with (await OpenOrCreateDialog.wait_for()).create() as (mw, project):
            r = Resource(project, home_url)
            
            rr_future = r.download()
            
            rr_future2 = r.download()
            assert rr_future2 is rr_future
            
            await wait_for_download_to_start_and_finish(mw.task_tree)


# ------------------------------------------------------------------------------
# DownloadResourceTask Tests

async def test_downloads_embedded_resources() -> None:
    server = MockHttpServer({
        '/': dict(
            status_code=200,
            headers=[('Content-Type', 'text/html')],
            content=dedent(
                """
                <!DOCTYPE html>
                <html>
                <body>
                    <img src="/assets/image.png" />
                </body>
                </html>
                """
            ).lstrip('\n').encode('utf-8')
        )
    })
    with server:
        async with (await OpenOrCreateDialog.wait_for()).create() as (mw, project):
            r = Resource(project, server.get_url('/'))
            revision_future = r.download(wait_for_embedded=True)
            while not revision_future.done():
                await bg_sleep(DEFAULT_WAIT_PERIOD)
            
            assertEqual(['/', '/assets/image.png', _FAVICON_PATH], server.requested_paths)


async def test_does_not_download_embedded_resources_of_http_4xx_and_5xx_pages() -> None:
    server = MockHttpServer({
        '/': dict(
            status_code=404,
            headers=[('Content-Type', 'text/html')],
            content=dedent(
                """
                <!DOCTYPE html>
                <html>
                <body>
                    <img src="/assets/image.png" />
                </body>
                </html>
                """
            ).lstrip('\n').encode('utf-8')
        ),
        '/assets/image.png': dict(
            status_code=404,
            headers=[('Content-Type', 'text/html')],
            content=dedent(
                """
                <!DOCTYPE html>
                <html>
                <body>
                    <img src="/assets/image.png" />
                </body>
                </html>
                """
            ).lstrip('\n').encode('utf-8')
        )
    })
    with server:
        async with (await OpenOrCreateDialog.wait_for()).create() as (mw, project):
            r = Resource(project, server.get_url('/'))
            revision_future = r.download(wait_for_embedded=True)
            while not revision_future.done():
                await bg_sleep(DEFAULT_WAIT_PERIOD)
            
            assertEqual(['/'], server.requested_paths)


async def test_does_not_download_embedded_resources_of_recognized_binary_resource() -> None:
    server = MockHttpServer({
        '/': dict(
            status_code=200,
            headers=[('Content-Type', 'image/png')],
            content=dedent(
                """
                PNG <img src="/assets/image.png" />
                """
            ).lstrip('\n').encode('utf-8')
        )
    })
    with server:
        async with (await OpenOrCreateDialog.wait_for()).create() as (mw, project):
            r = Resource(project, server.get_url('/'))
            revision_future = r.download(wait_for_embedded=True)
            while not revision_future.done():
                await bg_sleep(DEFAULT_WAIT_PERIOD)
            
            assertEqual(['/'], server.requested_paths)


async def test_does_not_download_forever_given_embedded_resources_form_a_cycle() -> None:
    server = MockHttpServer({
        '/': dict(
            status_code=200,
            headers=[('Content-Type', 'text/html')],
            content=dedent(
                """
                <!DOCTYPE html>
                <html>
                <body>
                    <img src="/assets/image.png" />
                </body>
                </html>
                """
            ).lstrip('\n').encode('utf-8')
        ),
        '/assets/image.png': dict(
            status_code=200,
            headers=[('Content-Type', 'text/html')],
            content=dedent(
                """
                <!DOCTYPE html>
                <html>
                <body>
                    <img src="/assets/image.png" />
                </body>
                </html>
                """
            ).lstrip('\n').encode('utf-8')
        )
    })
    with server:
        async with (await OpenOrCreateDialog.wait_for()).create() as (mw, project):
            r = Resource(project, server.get_url('/'))
            revision_future = r.download(wait_for_embedded=True)
            while not revision_future.done():
                await bg_sleep(DEFAULT_WAIT_PERIOD)
            
            assertEqual(['/', '/assets/image.png', _FAVICON_PATH], server.requested_paths)


async def test_does_not_download_forever_given_embedded_resources_nest_infinitely() -> None:
    server = MockHttpServer({
        '/': dict(
            status_code=200,
            headers=[('Content-Type', 'text/html')],
            content=dedent(
                """
                <!DOCTYPE html>
                <html>
                <body>
                    <img src="/assets/image.png" />
                </body>
                </html>
                """
            ).lstrip('\n').encode('utf-8')
        ),
        (lambda path: path.startswith('/assets/')): dict(
            status_code=200,
            headers=[('Content-Type', 'text/html')],
            content=(lambda path: dedent(
                f"""
                <!DOCTYPE html>
                <html>
                <body>
                    <img src="/assets{path}" />
                </body>
                </html>
                """
            ).lstrip('\n').encode('utf-8'))
        )
    })
    with server:
        async with (await OpenOrCreateDialog.wait_for()).create() as (mw, project):
            r = Resource(project, server.get_url('/'))
            revision_future = r.download(wait_for_embedded=True)
            while not revision_future.done():
                await bg_sleep(DEFAULT_WAIT_PERIOD)
            
            assert 3 == crystal.task._MAX_EMBEDDED_RESOURCE_RECURSION_DEPTH
            assertEqual([
                '/',
                '/assets/image.png',  # 1
                '/assets/assets/image.png',  # 2
                '/assets/assets/assets/image.png',  # 3
                _FAVICON_PATH,
            ], server.requested_paths)


async def test_when_download_resource_given_revision_body_missing_then_redownloads_revision_body() -> None:
    server = MockHttpServer({
        '/': dict(
            status_code=200,
            headers=[('Content-Type', 'text/html')],
            content=dedent(
                """
                <!DOCTYPE html>
                <html>
                <body>
                    <img src="/assets/image.png" />
                </body>
                </html>
                """
            ).lstrip('\n').encode('utf-8')
        ),
    })
    with server:
        with tempfile.TemporaryDirectory(suffix='.crystalproj') as project_dirpath:
            async with (await OpenOrCreateDialog.wait_for()).create(project_dirpath) as (mw, project):
                r = Resource(project, server.get_url('/'))
                revision_future = r.download(wait_for_embedded=True)
                while not revision_future.done():
                    await bg_sleep(DEFAULT_WAIT_PERIOD)
                
                assertEqual(['/', '/assets/image.png', _FAVICON_PATH], server.requested_paths)
                server.requested_paths.clear()
                
                rr = revision_future.result()
                rr_body_filepath = rr._body_filepath  # capture
            
            # Simulate loss of revision body file, perhaps due to an
            # incomplete copy of a .crystalproj from one disk to another
            # (perhaps because of bad blocks in the revision body file)
            os.remove(rr_body_filepath)
            
            async with (await OpenOrCreateDialog.wait_for()).open(project_dirpath) as (mw, project):
                with redirect_stderr(io.StringIO()) as captured_stderr:
                    r = Resource(project, server.get_url('/'))
                    revision_future = r.download(wait_for_embedded=True)
                    while not revision_future.done():
                        await bg_sleep(DEFAULT_WAIT_PERIOD)
                
                assert (
                    ' is missing its body on disk. Redownloading it.'
                    in captured_stderr.getvalue()
                )
                assertEqual(['/'], server.requested_paths)


async def test_when_download_resource_given_all_embedded_resources_already_downloaded_then_completes_early() -> None:
    server = MockHttpServer({
        '/': dict(
            status_code=200,
            headers=[('Content-Type', 'text/html')],
            content=dedent(
                """
                <!DOCTYPE html>
                <html>
                <body>
                    <img src="/assets/image.png" />
                </body>
                </html>
                """
            ).lstrip('\n').encode('utf-8')
        ),
        '/index.php': dict(
            status_code=200,
            headers=[('Content-Type', 'text/html')],
            content=dedent(
                """
                <!DOCTYPE html>
                <html>
                <body>
                    <img src="/assets/image.png" />
                </body>
                </html>
                """
            ).lstrip('\n').encode('utf-8')
        )
    })
    with server:
        async with (await OpenOrCreateDialog.wait_for()).create() as (mw, project):
            r = Resource(project, server.get_url('/'))
            revision_future = r.download(wait_for_embedded=True)
            while not revision_future.done():
                await bg_sleep(DEFAULT_WAIT_PERIOD)
            
            assertEqual(['/', '/assets/image.png', _FAVICON_PATH], server.requested_paths)
            server.requested_paths.clear()
            
            r = Resource(project, server.get_url('/index.php'))
            revision_future = r.download(wait_for_embedded=True)
            while not revision_future.done():
                await bg_sleep(DEFAULT_WAIT_PERIOD)
            
            assertEqual(['/index.php'], server.requested_paths)


async def test_given_same_resource_embedded_multiple_times_then_downloads_it_only_once() -> None:
    server = MockHttpServer({
        '/': dict(
            status_code=200,
            headers=[('Content-Type', 'text/html')],
            content=dedent(
                """
                <!DOCTYPE html>
                <html>
                <body>
                    <img src="/assets/image.png" />
                    <img src="/assets/image.png" />
                    <img src="/assets/image.png#fragment-should-be-ignored" />
                </body>
                </html>
                """
            ).lstrip('\n').encode('utf-8')
        )
    })
    with server:
        async with (await OpenOrCreateDialog.wait_for()).create() as (mw, project):
            r = Resource(project, server.get_url('/'))
            revision_future = r.download(wait_for_embedded=True)
            while not revision_future.done():
                await bg_sleep(DEFAULT_WAIT_PERIOD)
            
            assertEqual(['/', '/assets/image.png', _FAVICON_PATH], server.requested_paths)


# ------------------------------------------------------------------------------
# DownloadResourceGroupTask Tests

@skip('covered by: test_some_tasks_may_complete_immediately')
async def test_can_download_group_with_nothing_as_source() -> None:
    # See subtest: task_type='DownloadResourceGroupTask'
    pass


@skip('covered by: test_can_download_and_serve_a_static_site')
async def test_can_download_group_with_root_resource_as_source() -> None:
    # See section: "Test can download resource group, when root resource is source"
    pass


@skip('covered by: test_can_download_and_serve_a_static_site')
async def test_can_download_group_with_group_as_source() -> None:
    # See section: "Test can update membership of resource group, when other resource group is source"
    pass


async def test_can_download_empty_group() -> None:
    with served_project('testdata_xkcd.crystalproj.zip') as sp:
        # Define URLs
        comic_pattern = sp.get_request_url('https://xkcd.com/#/')
        
        async with (await OpenOrCreateDialog.wait_for()).create() as (mw, _):
            assert mw.new_group_button.Enabled
            click_button(mw.new_group_button)
            ngd = await NewGroupDialog.wait_for()
            
            ngd.pattern_field.Value = comic_pattern
            ngd.name_field.Value = 'Comic'
            await ngd.ok()
            
            root_ti = TreeItem.GetRootItem(mw.entity_tree.window)
            comic_ti = root_ti.find_child(comic_pattern)
            comic_ti.SelectItem()
            
            class DownloadResourceGroupTaskSpy(crystal.task.DownloadResourceGroupTask):
                finish_call_count = 0
                
                def finish(self, *args, **kwargs):
                    DownloadResourceGroupTaskSpy.finish_call_count += 1
                    return super().finish(*args, **kwargs)
            
            with patch('crystal.task.DownloadResourceGroupTask', DownloadResourceGroupTaskSpy):
                click_button(mw.download_button)
                await wait_for(lambda: DownloadResourceGroupTaskSpy.finish_call_count >= 1 or None)
                assert 1 == DownloadResourceGroupTaskSpy.finish_call_count


# ------------------------------------------------------------------------------
