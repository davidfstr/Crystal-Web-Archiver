from crystal.util.caffeination import Caffeination
import unittest
from unittest.mock import patch, MagicMock


class TestCaffeination(unittest.TestCase):
    def setUp(self) -> None:
        self._reset_caffeination()
    
    def tearDown(self) -> None:
        self._reset_caffeination()
    
    @staticmethod
    def _reset_caffeination() -> None:
        Caffeination._caffeine_count = 0
        Caffeination._caffeinated = False
        Caffeination._caffeination_unavailable = False
        if Caffeination._wakepy_keeper:
            try:
                Caffeination._wakepy_keeper.__exit__(None, None, None)
            except:
                pass
        Caffeination._wakepy_keeper = None
    
    @patch('crystal.util.caffeination.wakepy')
    def test_add_caffeine(self, mock_wakepy) -> None:
        """Test adding caffeine using wakepy."""
        mock_keeper = MagicMock()
        mock_wakepy.keep.running.return_value = mock_keeper
        
        # Initial state
        self.assertEqual(Caffeination._caffeine_count, 0)
        self.assertFalse(Caffeination._caffeinated)
        
        # Add first caffeine
        Caffeination.add_caffeine()
        
        self.assertEqual(Caffeination._caffeine_count, 1)
        self.assertTrue(Caffeination._caffeinated)
        mock_wakepy.keep.running.assert_called_once()
        mock_keeper.__enter__.assert_called_once()
        
        # Add second caffeine (should not create new keeper)
        mock_wakepy.reset_mock()
        mock_keeper.reset_mock()
        Caffeination.add_caffeine()
        
        self.assertEqual(Caffeination._caffeine_count, 2)
        self.assertTrue(Caffeination._caffeinated)
        mock_wakepy.keep.running.assert_not_called()
        mock_keeper.__enter__.assert_not_called()
    
    @patch('crystal.util.caffeination.wakepy')
    def test_remove_caffeine(self, mock_wakepy) -> None:
        """Test removing caffeine using wakepy."""
        mock_keeper = MagicMock()
        mock_wakepy.keep.running.return_value = mock_keeper
        
        # Add two caffeines
        Caffeination.add_caffeine()
        Caffeination.add_caffeine()
        
        # Remove first caffeine (should still be caffeinated)
        Caffeination.remove_caffeine()
        
        self.assertEqual(Caffeination._caffeine_count, 1)
        self.assertTrue(Caffeination._caffeinated)
        mock_keeper.__exit__.assert_not_called()
        
        # Remove second caffeine (should stop caffeination)
        Caffeination.remove_caffeine()
        
        self.assertEqual(Caffeination._caffeine_count, 0)
        self.assertFalse(Caffeination._caffeinated)
        mock_keeper.__exit__.assert_called_once_with(None, None, None)
    
    @patch('crystal.util.caffeination.wakepy')
    def test_multiple_add_remove_cycles(self, mock_wakepy) -> None:
        """Test multiple cycles of adding and removing caffeine."""
        mock_keeper = MagicMock()
        mock_wakepy.keep.running.return_value = mock_keeper
        
        # First cycle
        Caffeination.add_caffeine()
        self.assertTrue(Caffeination._caffeinated)
        mock_wakepy.keep.running.assert_called_once()
        mock_keeper.__enter__.assert_called_once()
        
        Caffeination.remove_caffeine()
        self.assertFalse(Caffeination._caffeinated)
        mock_keeper.__exit__.assert_called_once_with(None, None, None)
        
        # Reset mocks for second cycle
        mock_wakepy.reset_mock()
        mock_keeper.reset_mock()
        
        # Second cycle
        Caffeination.add_caffeine()
        self.assertTrue(Caffeination._caffeinated)
        mock_wakepy.keep.running.assert_called_once()
        mock_keeper.__enter__.assert_called_once()
        
        Caffeination.remove_caffeine()
        self.assertFalse(Caffeination._caffeinated)
        mock_keeper.__exit__.assert_called_once_with(None, None, None)
    
    @patch('crystal.util.caffeination.wakepy')
    def test_no_operation_when_already_in_desired_state(self, mock_wakepy) -> None:
        """Test that no wakepy operations occur when already in desired state."""
        mock_keeper = MagicMock()
        mock_wakepy.keep.running.return_value = mock_keeper
        
        # Initial state should not trigger any operations
        Caffeination._set_caffeinated(False)
        mock_wakepy.keep.running.assert_not_called()
        
        # Add caffeine to make it caffeinated
        Caffeination.add_caffeine()
        mock_wakepy.keep.running.assert_called_once()
        mock_keeper.__enter__.assert_called_once()
        
        # Reset mocks
        mock_wakepy.reset_mock()
        mock_keeper.reset_mock()
        
        # Setting to caffeinated when already caffeinated should do nothing
        Caffeination._set_caffeinated(True)
        mock_wakepy.keep.running.assert_not_called()
        mock_keeper.__enter__.assert_not_called()
        mock_keeper.__exit__.assert_not_called()
    
    @patch('crystal.util.caffeination.wakepy')
    @patch('crystal.util.caffeination.warnings')
    def test_wakepy_activation_error_handling(self, mock_warnings, mock_wakepy) -> None:
        """Test that wakepy activation errors are handled gracefully."""
        # Create a mock ActivationError similar to what happens on Linux
        class MockActivationError(Exception):
            def __init__(self, message):
                super().__init__(message)
        
        # Create mock keeper that fails on __enter__
        mock_keeper = MagicMock()
        mock_keeper.__enter__.side_effect = MockActivationError(
            'Could not activate Mode "keep.running"!\n\n'
            'Method usage results, in order (highest priority first):\n'
            '[(FAIL @ACTIVATION, org.freedesktop.PowerManagement, '
            '"DBusNotFoundError(The environment variable DBUS_SESSION_BUS_ADDRESS is not set!)")]'
        )
        mock_wakepy.keep.running.return_value = mock_keeper
        
        # Initial state
        self.assertEqual(Caffeination._caffeine_count, 0)
        self.assertFalse(Caffeination._caffeinated)
        self.assertFalse(Caffeination._caffeination_unavailable)
        
        # Add caffeine - should trigger the error but handle it gracefully
        with patch('crystal.util.caffeination.contextlib.nullcontext') as mock_nullcontext:
            mock_null_keeper = MagicMock()
            mock_nullcontext.return_value = mock_null_keeper
            
            Caffeination.add_caffeine()
            
            # Should have incremented caffeine count and set caffeinated to True
            self.assertEqual(Caffeination._caffeine_count, 1)
            self.assertTrue(Caffeination._caffeinated)
            
            # Should have marked caffeination as unavailable
            self.assertTrue(Caffeination._caffeination_unavailable)
            
            # Should have warned about the failure
            mock_warnings.warn.assert_called_once()
            warning_message = mock_warnings.warn.call_args[0][0]
            self.assertIn('Unable to caffeinate:', warning_message)
            self.assertIn('Will no longer try to caffeinate until quit', warning_message)
            
            # Should have fallen back to nullcontext
            mock_nullcontext.assert_called_once()
            mock_null_keeper.__enter__.assert_called_once()
        
        # Add second caffeine - should use nullcontext immediately
        mock_warnings.reset_mock()
        mock_wakepy.reset_mock()
        
        with patch('crystal.util.caffeination.contextlib.nullcontext') as mock_nullcontext2:
            mock_null_keeper2 = MagicMock()
            mock_nullcontext2.return_value = mock_null_keeper2
            
            Caffeination.add_caffeine()
            
            # Should have incremented count but not tried wakepy again
            self.assertEqual(Caffeination._caffeine_count, 2)
            self.assertTrue(Caffeination._caffeinated)
            mock_wakepy.keep.running.assert_not_called()
            mock_warnings.warn.assert_not_called()
            
            # Should have used nullcontext directly since caffeination is marked unavailable
            mock_nullcontext2.assert_not_called()  # Not called because _wakepy_keeper is already set
        
        # Remove caffeine down to zero - should work normally
        Caffeination.remove_caffeine()
        self.assertEqual(Caffeination._caffeine_count, 1)
        self.assertTrue(Caffeination._caffeinated)
        
        Caffeination.remove_caffeine()
        self.assertEqual(Caffeination._caffeine_count, 0)
        self.assertFalse(Caffeination._caffeinated)
        self.assertIsNone(Caffeination._wakepy_keeper)


if __name__ == '__main__':
    unittest.main()
