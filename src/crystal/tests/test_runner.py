"""
Tests for Crystal's test runner functionality.

These tests verify that the test infrastructure itself works correctly,
including error recovery mechanisms, and test utilities.
"""

from contextlib import redirect_stderr
from crystal.browser import MainWindow as RealMainWindow
from crystal.model import Project
from crystal.tests.util.asserts import assertIn
from crystal.tests.util.windows import MainWindow, OpenOrCreateDialog
import io


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
