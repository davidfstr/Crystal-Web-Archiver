"""Unit tests for module util/macos_app.py"""

from crystal.util import macos_app
from crystal.tests.util.wait import wait_for_sync
import pytest
import sys
from unittest.mock import patch


# Skip all tests in this module on non-macOS platforms
pytestmark = pytest.mark.skipif(
    sys.platform != 'darwin',
    reason='Tests only run on macOS'
)


# === Test: Application Menu Name ===

def test_set_and_get_application_menu_name() -> None:
    """Test setting and getting the application menu name."""
    # Store the original name to restore it later
    original_name = macos_app.get_application_menu_name()
    assert isinstance(original_name, str)
    assert len(original_name) > 0
    
    try:
        # Set a test name
        test_name = 'TestApp'
        macos_app.set_application_menu_name(test_name)
        
        # Get and verify the name was set
        retrieved_name = macos_app.get_application_menu_name()
        assert retrieved_name == test_name
    finally:
        # Restore the original name
        macos_app.set_application_menu_name(original_name)


def test_get_application_menu_name_not_supported_on_non_darwin() -> None:
    """Test that get_application_menu_name raises error on non-macOS."""
    with patch('sys.platform', 'linux'):
        with pytest.raises(ValueError, match='Not supported on this OS'):
            macos_app.get_application_menu_name()


def test_set_application_menu_name_not_supported_on_non_darwin() -> None:
    """Test that set_application_menu_name raises error on non-macOS."""
    with patch('sys.platform', 'linux'):
        with pytest.raises(ValueError, match='Not supported on this OS'):
            macos_app.set_application_menu_name('TestName')


def test_warn_if_application_menu_name_changes_from_detects_name_change() -> None:
    """Test that warn_if_application_menu_name_changes_from detects app name changes."""
    original_name = macos_app.get_application_menu_name()
    try:
        with patch('crystal.util.macos_app.print_special') as mock_print_special:
            macos_app.set_application_menu_name('AppName1')
            # NOTE: Use a short period so that this test executes fast on average
            macos_app.warn_if_application_menu_name_changes_from('AppName1', period=0.1)
            macos_app.set_application_menu_name('AppName2')
            
            # Wait for print_special() to be called by the monitoring thread of
            # warn_if_application_menu_name_changes_from()
            wait_for_sync(
                lambda: mock_print_special.called,
                timeout=0.5
            )
            
            # Assert that print_special() was called with "App menu name changed from"
            call_args = mock_print_special.call_args[0][0]
            assert 'App menu name changed from' in call_args
            assert 'AppName1' in call_args
            assert 'AppName2' in call_args
    finally:
        macos_app.set_application_menu_name(original_name)


# === Test: Bring to Front ===

def test_bring_app_to_front_not_supported_on_non_darwin() -> None:
    """Test that bring_app_to_front raises error on non-macOS."""
    with patch('sys.platform', 'linux'):
        with pytest.raises(ValueError, match='Not supported on this OS'):
            macos_app.bring_app_to_front()
