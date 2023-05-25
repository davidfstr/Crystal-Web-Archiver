import bs4
from contextlib import contextmanager
from crystal.browser import MainWindow as RealMainWindow
from crystal.model import Project, Resource, RootResource
from crystal.tests.util.controls import click_button
from crystal.tests.util.runner import bg_sleep
from crystal.tests.util.server import served_project
from crystal.tests.util.wait import DEFAULT_WAIT_PERIOD
from crystal.tests.util.windows import (
    MainWindow, OpenOrCreateDialog, PreferencesDialog,
)
import lxml.html
import tempfile
from typing import Iterator, Tuple
from unittest import skip
from unittest.mock import Mock, patch


async def test_uses_html_parser_specified_in_preferences() -> None:
    with served_project('testdata_xkcd.crystalproj.zip') as sp:
        # Define URLs
        home_url = sp.get_request_url('https://xkcd.com/')
        
        with tempfile.TemporaryDirectory(suffix='.crystalproj') as project_dirpath:
            async with (await OpenOrCreateDialog.wait_for()).create(project_dirpath) as (mw, _):
                project = Project._last_opened_project
                assert project is not None
                
                rr = RootResource(project, 'Home', Resource(project, home_url))
                r = Resource(project, home_url)
                
                # Ensure default HTML parser for new project is lxml
                click_button(mw.preferences_button)
                pd = await PreferencesDialog.wait_for()
                html_parser_title = pd.html_parser_field.Items[pd.html_parser_field.Selection]
                assert 'Fastest - lxml' == html_parser_title
                await pd.ok()
                
                revision_future = r.download(wait_for_embedded=True)
                while not revision_future.done():
                    await bg_sleep(DEFAULT_WAIT_PERIOD)
                revision = revision_future.result()
                
                # Ensure expected HTML parser is used
                with _watch_html_parser_usage() as (lxml_parse_func, bs4_parse_func):
                    (_, _, _) = revision.document_and_links()
                assert (1, 0) == (lxml_parse_func.call_count, bs4_parse_func.call_count)
                
                # Switch HTML parser
                click_button(mw.preferences_button)
                pd = await PreferencesDialog.wait_for()
                pd.html_parser_field.Selection = pd.html_parser_field.Items.index(
                    'Classic - html.parser (bs4)')
                await pd.ok()
                
                # Ensure new HTML parser is used
                with _watch_html_parser_usage() as (lxml_parse_func, bs4_parse_func):
                    (_, _, _) = revision.document_and_links()
                assert (0, 1) == (lxml_parse_func.call_count, bs4_parse_func.call_count)


@skip('covered by: test_uses_html_parser_specified_in_preferences')
async def test_defaults_to_lxml_html_parser_for_new_projects() -> None:
    pass


async def test_uses_html_parser_parser_for_classic_projects() -> None:
    # NOTE: The testdata project is a classic project from Crystal <=1.5.0
    with served_project('testdata_xkcd.crystalproj.zip') as sp:
        with RealMainWindow(sp.project) as rmw:
            mw = await MainWindow.wait_for()
            
            click_button(mw.preferences_button)
            pd = await PreferencesDialog.wait_for()
            try:
                html_parser_title = pd.html_parser_field.Items[pd.html_parser_field.Selection]
                assert 'Classic - html.parser (bs4)' == html_parser_title
            finally:
                await pd.ok()


@contextmanager
def _watch_html_parser_usage() -> Iterator[Tuple[Mock, Mock]]:
    with patch('lxml.html.document_fromstring', wraps=lxml.html.document_fromstring) as lxml_parse_func:
        with patch('crystal.util.fastsoup.BeautifulSoup', wraps=bs4.BeautifulSoup) as bs4_parse_func:
            yield (lxml_parse_func, bs4_parse_func)
