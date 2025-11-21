"""
Unit tests for the Crystal test runner functionality in:
- crystal.tests.runner
- crystal.tests.util.runner
"""

from crystal.tests.runner.shared import normalize_test_names
import pytest


class TestNormalizeTestNames:
    """Test the _normalize_test_names function with various input formats."""
    
    def test_qualified_module_name(self):
        """Test that qualified module names work correctly."""
        result = normalize_test_names(['crystal.tests.test_workflows'])
        assert result == ['crystal.tests.test_workflows']
    
    def test_qualified_function_name(self):
        """Test that qualified function names work correctly."""
        result = normalize_test_names(['crystal.tests.test_workflows.test_can_download_and_serve_a_static_site_using_main_window_ui'])
        assert result == ['crystal.tests.test_workflows.test_can_download_and_serve_a_static_site_using_main_window_ui']
    
    def test_unqualified_module_name(self):
        """Test that unqualified module names are resolved correctly."""
        result = normalize_test_names(['test_workflows'])
        assert result == ['crystal.tests.test_workflows']
    
    def test_file_path_notation(self):
        """Test that file path notation is converted correctly."""
        result = normalize_test_names(['src/crystal/tests/test_workflows.py'])
        assert result == ['crystal.tests.test_workflows']
    
    def test_pytest_style_function_notation(self):
        """Test that pytest-style function notation (::) is converted correctly."""
        result = normalize_test_names(['crystal.tests.test_workflows::test_can_download_and_serve_a_static_site_using_main_window_ui'])
        assert result == ['crystal.tests.test_workflows.test_can_download_and_serve_a_static_site_using_main_window_ui']
    
    def test_unqualified_function_name(self):
        """Test that unqualified function names are resolved correctly."""
        result = normalize_test_names(['test_can_download_and_serve_a_static_site_using_main_window_ui'])
        assert result == ['crystal.tests.test_workflows.test_can_download_and_serve_a_static_site_using_main_window_ui']
    
    def test_multiple_test_names(self):
        """Test that multiple test names are all normalized correctly."""
        result = normalize_test_names([
            'test_workflows',
            'crystal.tests.test_bulkheads::test_capture_crashes_to_self_decorator_works',
            'src/crystal/tests/test_xthreading.py'
        ])
        expected = [
            'crystal.tests.test_workflows',
            'crystal.tests.test_bulkheads.test_capture_crashes_to_self_decorator_works',
            'crystal.tests.test_xthreading'
        ]
        assert result == expected
    
    def test_empty_list(self):
        """Test that an empty list returns an empty list."""
        result = normalize_test_names([])
        assert result == []
    
    def test_nonexistent_module_raises_error(self):
        """Test that non-existent modules raise a descriptive error."""
        with pytest.raises(ValueError) as exc_info:
            normalize_test_names(['crystal.tests.test_no_such_suite'])
        
        error_msg = str(exc_info.value)
        assert 'Test not found: crystal.tests.test_no_such_suite' in error_msg
        assert 'Available test modules:' in error_msg
    
    def test_nonexistent_unqualified_function_raises_error(self):
        """Test that non-existent unqualified functions raise a descriptive error."""
        with pytest.raises(ValueError) as exc_info:
            normalize_test_names(['test_no_such_function'])
        
        error_msg = str(exc_info.value)
        assert 'Test not found: test_no_such_function' in error_msg
    
    def test_invalid_pytest_style_format(self):
        """Test that invalid pytest-style formats raise errors."""
        with pytest.raises(ValueError) as exc_info:
            normalize_test_names(['invalid::format::too::many::colons'])
        
        error_msg = str(exc_info.value)
        assert 'Test not found: invalid::format::too::many::colons' in error_msg
    
    def test_file_path_without_src_prefix(self):
        """Test that file paths without 'src/' prefix work correctly."""
        result = normalize_test_names(['crystal/tests/test_workflows.py'])
        assert result == ['crystal.tests.test_workflows']
    
    def test_windows_style_file_path(self):
        """Test that Windows-style file paths work correctly."""
        result = normalize_test_names(['src\\crystal\\tests\\test_workflows.py'])
        assert result == ['crystal.tests.test_workflows']
    
    def test_partial_module_match(self):
        """Test that partial module names are resolved correctly."""
        # This should match any module ending with test_workflows
        result = normalize_test_names(['test_workflows'])
        assert 'crystal.tests.test_workflows' in result
    
    def test_case_sensitivity(self):
        """Test that function names are case-sensitive."""
        with pytest.raises(ValueError):
            normalize_test_names(['test_CAN_DOWNLOAD_AND_SERVE_A_STATIC_SITE'])  # Wrong case
    
    def test_function_in_nonexistent_module(self):
        """Test that functions in non-existent modules raise errors."""
        with pytest.raises(ValueError) as exc_info:
            normalize_test_names(['crystal.tests.test_nonexistent::test_some_function'])
        
        error_msg = str(exc_info.value)
        assert 'Test not found' in error_msg
