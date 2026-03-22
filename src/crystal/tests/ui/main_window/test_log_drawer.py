from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, redirect_stdout
from crystal.server import get_request_url
from crystal.tests.util.asserts import assertEqual
from crystal.tests.util.server import assert_does_open_webbrowser_to, extracted_project
from crystal.tests.util.windows import MainWindow, OpenOrCreateDialog
from crystal.ui.log_drawer import LogDrawer
from crystal.util.controls import click_button, TreeItem
from io import StringIO
from unittest import skip
from unittest.mock import patch
import wx
from wx.richtext import RichTextCtrl


# === Test: Create ===

async def test_when_drawer_created_then_displays_inside_parent() -> None:
    async with _log_drawer_visible() as (mw, log_drawer):
        # Verify the LogDrawer is maximized into the parent
        assert log_drawer._is_maximized, \
            'LogDrawer should be maximized into parent'

        # Verify the LogDrawer's content (a RichTextCtrl) is inside the main window
        pcc = log_drawer._parent_content_container
        assert pcc is not None
        assert isinstance(pcc, wx.SplitterWindow)
        assert pcc.Parent == mw.main_window, \
            'LogDrawer content container should be a child of the main window'

        # Verify the splitter has two windows: the original content and the log textarea
        assert pcc.Window1 is not None, \
            'Splitter should have the original content as Window1'
        assert pcc.Window2 is not None, \
            'Splitter should have the log textarea as Window2'
        assert isinstance(pcc.Window2, RichTextCtrl), \
            'Window2 of the splitter should be the log textarea (RichTextCtrl)'

        # Verify the drawer is open and visible
        assert log_drawer.is_open, \
            'LogDrawer should be open after creation'


# === Test: Drawer Text ===

@skip('not yet automated')
def test_when_write_colorized_text_to_writer_then_displays_colorized_text_in_drawer_and_in_stdout() -> None:
    pass


@skip('not yet automated')
def test_when_write_text_to_writer_then_scrolls_drawer_to_bottom_iff_it_was_scrolled_to_bottom_before() -> None:
    pass


@skip('not yet automated')
def test_can_select_and_copy_text_in_drawer() -> None:
    pass


@skip('not yet automated')
def test_cannot_edit_text_in_drawer() -> None:
    pass


@skip('not yet automated')
def test_always_displays_vertical_scrollbar_and_never_displays_horizontal_scrollbar() -> None:
    pass


async def test_when_write_many_lines_to_writer_beyond_max_then_leading_lines_trimmed() -> None:
    MAX_LINE_COUNT = 50
    with patch('crystal.ui.log_drawer._MAX_LINE_COUNT', MAX_LINE_COUNT):
        async with _log_drawer_visible() as (mw, log_drawer):
            textarea = log_drawer._textarea
            writer = log_drawer.writer

            # Count lines already present (from server startup banner)
            initial_line_count = textarea.GetNumberOfLines()

            # Write lines until we reach exactly MAX_LINE_COUNT
            lines_to_add = MAX_LINE_COUNT - initial_line_count
            with redirect_stdout(StringIO()):
                for i in range(lines_to_add):
                    writer.write(f'line {i}\n')
            assertEqual(MAX_LINE_COUNT, textarea.GetNumberOfLines())

            # Write one more line, which should cause the leading line to be trimmed
            final_line_text = 'this is the final line'
            with redirect_stdout(StringIO()):
                writer.write(f'{final_line_text}\n')
            assertEqual(MAX_LINE_COUNT, textarea.GetNumberOfLines(),
                'Line count should still be MAX_LINE_COUNT after trimming')

            # Verify the last line of content is the one we just wrote
            last_content_line = textarea.GetLineText(MAX_LINE_COUNT - 2)
            assertEqual(final_line_text, last_content_line,
                'Last content line should be the final line we wrote')


# === Test: Drag or Double-Click Sash ===

@skip('not yet automated')
def test_when_sash_dragged_then_drawer_height_changes() -> None:
    pass


@skip('not yet automated')
def test_given_drawer_open_when_sash_dragged_far_down_then_drawer_closes() -> None:
    pass


@skip('not yet automated')
def test_given_drawer_closed_when_sash_dragged_up_then_drawer_opens_and_drawer_height_changes() -> None:
    pass


@skip('not yet automated')
def test_when_sash_dragged_then_scrolls_drawer_to_bottom_iff_it_was_scrolled_to_bottom_before() -> None:
    pass


@skip('not yet automated')
def test_given_drawer_open_when_double_click_sash_then_drawer_closes() -> None:
    # Case A: Drawer is out of parent (unmaximized)
    # Case B: Drawer is in parent (maximized)
    pass


@skip('not yet automated')
def test_given_drawer_closed_when_double_click_sash_then_drawer_opens_to_last_used_height() -> None:
    # Case A: Drawer is out of parent (unmaximized)
    # Case B: Drawer is in parent (maximized)
    # Case 1: Drawer was closed by double-clicking the sash
    # Case 2: Drawer was closed by dragging the sash far up
    # Case 3: Drawer was closed by dragging the drawer's south edge/corner far up
    pass


# === Utility ===

@asynccontextmanager
async def _log_drawer_visible() -> AsyncIterator[tuple[MainWindow, LogDrawer]]:
    """
    Context manager that opens a test project, starts a server (which creates
    and displays the LogDrawer), and yields the MainWindow and LogDrawer.
    """
    with extracted_project('testdata_xkcd.crystalproj.zip') as project_dirpath:
        async with (await OpenOrCreateDialog.wait_for()).open(project_dirpath) as (mw, _project):
            # Start server by selecting a resource and clicking View
            root_ti = TreeItem.GetRootItem(mw.entity_tree.window)
            home_ti = root_ti.GetFirstChild()
            assert home_ti is not None
            home_ti.SelectItem()
            with assert_does_open_webbrowser_to(lambda: get_request_url('https://xkcd.com/')):
                click_button(mw.view_button)

            # Find the LogDrawer among the top-level windows
            log_drawers = [
                w for w in wx.GetTopLevelWindows()
                if isinstance(w, LogDrawer)
            ]
            assert len(log_drawers) == 1, \
                f'Expected exactly 1 LogDrawer, found {len(log_drawers)}'
            log_drawer = log_drawers[0]

            yield (mw, log_drawer)
