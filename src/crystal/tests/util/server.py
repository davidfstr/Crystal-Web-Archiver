from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
from crystal.model import Project
from crystal import resources
from crystal.server import get_request_url, ProjectServer
from crystal.tests.util.runner import bg_fetch_url
from crystal.tests.util.wait import DEFAULT_WAIT_TIMEOUT
from crystal.util import http_date
from crystal.util.xdatetime import datetime_is_aware
from crystal.util.xthreading import fg_call_and_wait
import datetime
from email.message import EmailMessage
import json
import os
import re
import tempfile
from typing import Dict, Iterator, Optional
import unittest.mock
from zipfile import ZipFile


# ------------------------------------------------------------------------------
# Utility: Server

@contextmanager
def served_project(
        zipped_project_filename: str,
        *, fetch_date_of_resources_set_to: Optional[datetime.datetime]=None,
        port: Optional[int]=None,
        ) -> Iterator[ProjectServer]:
    if fetch_date_of_resources_set_to is not None:
        if not datetime_is_aware(fetch_date_of_resources_set_to):
            raise ValueError('Expected fetch_date_of_resources_set_to to be an aware datetime')
    
    with extracted_project(zipped_project_filename) as project_filepath:
        must_alter_fetch_date = (fetch_date_of_resources_set_to is not None)
        project_server = None  # type: Optional[ProjectServer]
        project = fg_call_and_wait(lambda: Project(project_filepath, readonly=True if not must_alter_fetch_date else False))
        try:
            # Alter the fetch date of every ResourceRevision in the project
            # to match "fetch_date_of_resources_set_to", if provided
            if must_alter_fetch_date:
                def fg_task() -> None:
                    for r in project.resources:
                        for rr in list(r.revisions()):
                            if rr.metadata is None:
                                print(
                                    f'Warning: Unable to alter fetch date of '
                                    f'resource revision lacking HTTP headers: {rr}')
                                continue
                            
                            assert fetch_date_of_resources_set_to is not None
                            rr_new_date = http_date.format(fetch_date_of_resources_set_to)
                            
                            # New Metadata = Old Metadata with Date and Age headers replaced
                            rr_new_metadata = deepcopy(rr.metadata)
                            rr_new_metadata['headers'] = [
                                [cur_name, cur_value]
                                for (cur_name, cur_value) in
                                rr_new_metadata['headers']
                                if cur_name.lower() not in ['date', 'age']
                            ] + [['Date', rr_new_date]]
                            
                            rr._alter_metadata(rr_new_metadata, ignore_readonly=True)
                fg_call_and_wait(fg_task)
            
            # Start server
            project_server = ProjectServer(project,
                port=(port or 2798),  # CRYT on telephone keypad
                verbosity='indent',
            )
            yield project_server
        finally:
            def close_project() -> None:
                if project_server is not None:
                    project_server.close()
                project.close()
            fg_call_and_wait(close_project)


@contextmanager
def extracted_project(
        zipped_project_filename: str
        ) -> Iterator[str]:
    with tempfile.TemporaryDirectory() as project_parent_dirpath:
        # Extract project
        with resources.open_binary(zipped_project_filename) as zipped_project_file:
            with ZipFile(zipped_project_file, 'r') as project_zipfile:
                project_zipfile.extractall(project_parent_dirpath)
        
        # Open project
        (project_filename,) = [
            fn for fn in os.listdir(project_parent_dirpath)
            if fn.endswith('.crystalproj')
        ]
        project_filepath = os.path.join(project_parent_dirpath, project_filename)
        yield project_filepath


@contextmanager
def assert_does_open_webbrowser_to(request_url: str) -> Iterator[None]:
    with unittest.mock.patch('webbrowser.open', spec=True) as mock_open:
        yield
        mock_open.assert_called_with(request_url)


async def is_url_not_in_archive(archive_url: str) -> bool:
    server_page = await fetch_archive_url(
        archive_url, 
        headers={'X-Crystal-Dynamic': 'False'})
    return server_page.is_not_in_archive


async def fetch_archive_url(
        archive_url: str,
        port: Optional[int]=None,
        *, headers: Optional[Dict[str, str]]=None,
        timeout: Optional[float]=None,
        ) -> WebPage:
    if timeout is None:
        timeout = DEFAULT_WAIT_TIMEOUT
    return await bg_fetch_url(get_request_url(archive_url, port), headers=headers, timeout=timeout)


class WebPage:
    def __init__(self, status: int, headers: EmailMessage, content_bytes: bytes) -> None:
        self._status = status
        self._headers = headers
        self._content_bytes = content_bytes
        self._content = None  # type: Optional[str]
    
    # === High-Level Attributes ===
    
    @property
    def is_not_in_archive(self) -> bool:
        return (
            self._status == 404 and
            self.title == 'Not in Archive | Crystal Web Archiver'
        )
    
    @property
    def etag(self) -> Optional[str]:
        return self._headers.get('ETag')
    
    @property
    def title(self) -> Optional[str]:
        # TODO: Use an HTML parser to improve robustness
        m = re.search(r'<title>([^<]*)</title>', self.content)
        if m is None:
            return None
        else:
            return m.group(1).strip()
    
    # === Low-Level Attributes ===
    
    @property
    def status(self) -> int:
        return self._status
    
    @property
    def headers(self) -> EmailMessage:
        return self._headers
    
    @property
    def content(self) -> str:  # lazy
        if self._content is None:
            self._content = self._content_bytes.decode('utf-8')
        return self._content
    
    @property
    def content_bytes(self) -> bytes:
        return self._content_bytes


# ------------------------------------------------------------------------------
