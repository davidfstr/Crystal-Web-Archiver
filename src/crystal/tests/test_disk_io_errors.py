# Tests for the following kinds of scenarios:
# 
# - Read/write of project data that has "bad blocks" or other corruption
#   detected by the underlying device driver or filesystem.
# 
# - Read of project data where the project is slightly malformed
#   in a way that is repairable. For example a ResourceRevision
#   whose body file is missing from the revisions directory.

from contextlib import redirect_stderr
from crystal.model import Project, Resource
from crystal.tests.util.runner import bg_sleep
from crystal.tests.util.server import served_project
from crystal.tests.util.wait import DEFAULT_WAIT_PERIOD
from crystal.tests.util.windows import OpenOrCreateDialog
import io
import os
from unittest import skip

# ------------------------------------------------------------------------------
# Test: RevisionBodyMissingError

async def test_given_default_revision_with_missing_body_when_download_related_resource_then_deletes_and_redownloads_revision() -> None:
    # Read Case: Error when reading the revision body from disk when parsing links from HTML
    with served_project('testdata_xkcd.crystalproj.zip') as sp:
        home_url = sp.get_request_url('https://xkcd.com/')
        
        async with (await OpenOrCreateDialog.wait_for()).create() as (mw, project):
            # Download revision
            r = Resource(project, home_url)
            revision_future = r.download_body()
            while not revision_future.done():
                await bg_sleep(DEFAULT_WAIT_PERIOD)
            
            # Simulate loss of revision body file
            revision = revision_future.result()
            os.remove(revision._body_filepath)
            
            # Download related resource
            with redirect_stderr(io.StringIO()) as captured_stderr:
                revision_future = r.download(wait_for_embedded=True, needs_result=True)
                while not revision_future.done():
                    await bg_sleep(DEFAULT_WAIT_PERIOD)
            assert 'is missing its body on disk. Redownloading it.' in captured_stderr.getvalue()
            revision = revision_future.result()
            assert revision.has_body
            with revision.open():  # ensure no error
                pass


@skip('fails: not implemented')
async def test_given_default_revision_with_missing_body_when_related_resource_served_then_serves_404_error_page_saying_revision_is_corrupt_and_requires_redownload() -> None:
    # Read Case 1: Error when reading the revision body from disk when parsing links from HTML
    # Read Case 2: Error when reading the revision body from disk when serving non-HTML revision
    pass


# ------------------------------------------------------------------------------
# Test: RevisionBodyIOError

@skip('fails: not implemented')
async def test_given_default_revision_with_body_containing_bad_blocks_when_download_related_resource_then_deletes_and_redownloads_revision() -> None:
    # Write Case: Error when downloading the revision body to disk initially
    # Read Case: Error when reading the revision body from disk when parsing links from HTML
    pass


@skip('fails: not implemented')
async def test_given_default_revision_with_body_containing_bad_blocks_when_related_html_resource_served_then_serves_404_error_page_saying_revision_is_corrupt_and_requires_redownload() -> None:
    # Read Case: Error when reading the revision body from disk when parsing links from HTML
    pass


@skip('fails: not implemented')
async def test_given_default_revision_with_body_containing_bad_blocks_when_related_non_html_resource_served_then_resets_connection_abruptly() -> None:
    # Read Case: Error when reading the revision body from disk when serving non-HTML revision
    """
    # Set SO_LINGER to 1,0 which, by convention, causes a
    # connection reset to be sent (RST) when close is called,
    # instead of the standard FIN shutdown sequence.
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack(
        'hh' if is_windows() else 'ii', 1, 0))
    sock.close()
    """


# ------------------------------------------------------------------------------