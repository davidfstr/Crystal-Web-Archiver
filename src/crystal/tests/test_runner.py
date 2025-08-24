"""
Tests for Crystal's test runner functionality.

These tests verify that the test infrastructure itself works correctly,
including error recovery mechanisms, and test utilities.
"""

from contextlib import redirect_stderr
from crystal.browser import MainWindow as RealMainWindow
from crystal.model import Project
from crystal.server import _DEFAULT_SERVER_PORT
from crystal.tests.util.asserts import assertIn
from crystal.tests.util.controls import click_button, TreeItem
from crystal.tests.util.server import assert_does_open_webbrowser_to, extracted_project
from crystal.tests.util.windows import MainWindow, OpenOrCreateDialog
from crystal.util.ports import port_in_use
import io
from unittest.mock import ANY


# === OpenOrCreateDialog Tests ===

async def test_when_main_window_left_open_then_ocd_wait_for_does_recover_gracefully() -> None:
    # Intentionally leave a MainWindow open, simulating a test failure
    ocd1 = await OpenOrCreateDialog.wait_for()
    main_window = await ocd1.create_and_leave_open()
    
    # Wait for an OpenOrCreateDialog to appear, simulating a newly started test.
    # But it won't appear because the MainWindow is still open.
    # OpenOrCreateDialog should detect this and attempt to recover automatically.
    # 
    # The recovery mechanism should:
    # 1. Detect that a MainWindow is open
    # 2. Print a warning message
    # 3. Close the MainWindow (handling any "Do you want to save?" dialog)
    # 4. Wait for the OpenOrCreateDialog to appear
    with redirect_stderr(io.StringIO()) as captured_stderr:
        ocd2 = await OpenOrCreateDialog.wait_for(timeout=1.0)
    assertIn(
        'WARNING: OpenOrCreateDialog.wait_for() noticed that a MainWindow was left open',
        captured_stderr.getvalue()
    )


# === MainWindow Tests ===

async def test_when_main_window_left_open_then_mw_connect_does_recover_gracefully() -> None:
    # Intentionally leave a MainWindow open, simulating a test failure
    ocd = await OpenOrCreateDialog.wait_for()
    main_window = await ocd.create_and_leave_open()
    try:
        # Wait for an OpenOrCreateDialog to appear, simulating a newly started test.
        # But it won't appear because the MainWindow is still open.
        # OpenOrCreateDialog should detect this and attempt to recover automatically.
        # 
        # The recovery mechanism should:
        # 1. Detect that a MainWindow is open
        # 2. Print a warning message
        with redirect_stderr(io.StringIO()) as captured_stderr:
            with Project() as project, \
                    RealMainWindow(project) as rmw:
                # NOTE: Calls MainWindow._connect() internally
                mw = await MainWindow.wait_for(timeout=1)
                
                ...  # remainder of simulated test
        assertIn(
                'WARNING: MainWindow._connect() noticed that a MainWindow was left open',
                captured_stderr.getvalue()
            )
    finally:
        await main_window.close()


# === ProjectServer Tests ===

async def test_given_default_project_server_port_in_use_when_press_view_button_then_warns_default_port_in_use() -> None:
    with port_in_use(_DEFAULT_SERVER_PORT, '127.0.0.1'):    
        # Open a project 
        with extracted_project('testdata_xkcd.crystalproj.zip') as project_dirpath:
            async with (await OpenOrCreateDialog.wait_for()).open(project_dirpath) as \
                    (mw, project):
                # Select the home URL
                root_ti = TreeItem.GetRootItem(mw.entity_tree.window)
                home_ti = root_ti.GetFirstChild()
                assert home_ti is not None
                home_ti.SelectItem()
                
                # Press the "View" button to start a ProjectServer
                with redirect_stderr(io.StringIO()) as captured_stderr:
                    with assert_does_open_webbrowser_to(ANY):
                        click_button(mw.view_button)
                
                # Ensure that a warning was printed
                assertIn(
                    '*** Default port for project server is in use.',
                    captured_stderr.getvalue()
                )
