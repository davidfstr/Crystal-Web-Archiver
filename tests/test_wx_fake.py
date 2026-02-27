"""
Unit tests for the fake wx module system used in headless mode.
"""

from crystal.util.wx_fake import (
    _FakeWxModule,
    _FakeWxType,
    HeadlessModeError,
    install_fake_wx,
    uninstall_fake_wx,
)
import pytest
import sys


@pytest.fixture(autouse=True)
def _clean_wx_modules():
    """Ensure fake wx is uninstalled after each test."""
    # Save original state of all wx modules
    saved_wx_modules = {
        key: mod for (key, mod) in sys.modules.items()
        if key == 'wx' or key.startswith('wx.')
    }
    
    # Remove real wx so install_fake_wx() can proceed
    for key in list(saved_wx_modules):
        del sys.modules[key]
    yield
    
    # Restore original state
    uninstall_fake_wx()
    for (key, mod) in saved_wx_modules.items():
        sys.modules[key] = mod


class TestInstallFakeWx:
    def test_import_wx_succeeds_after_install(self) -> None:
        install_fake_wx()
        import wx
        assert isinstance(wx, _FakeWxModule)

    def test_import_wx_submodule_succeeds(self) -> None:
        install_fake_wx()
        import wx.adv
        assert isinstance(wx.adv, _FakeWxModule)

    def test_import_wx_richtext_succeeds(self) -> None:
        install_fake_wx()
        import wx.richtext
        assert isinstance(wx.richtext, _FakeWxModule)

    def test_install_raises_if_wx_already_imported(self) -> None:
        sys.modules['wx'] = object()  # type: ignore[assignment]
        with pytest.raises(AssertionError, match='wx was already imported'):
            install_fake_wx()


class TestFakeWxTypes:
    def test_upper_camel_case_returns_fake_type(self) -> None:
        install_fake_wx()
        import wx
        assert isinstance(wx.Window, _FakeWxType)

    def test_fake_type_identity_is_cached(self) -> None:
        install_fake_wx()
        import wx
        assert wx.Window is wx.Window

    def test_fake_type_repr(self) -> None:
        install_fake_wx()
        import wx
        assert repr(wx.Window) == '<FakeWxType: wx.Window>'

    def test_union_with_none_does_not_raise(self) -> None:
        install_fake_wx()
        import wx
        # Should not raise
        result = wx.Window | None
        assert result is wx.Window

    def test_reverse_union_with_none_does_not_raise(self) -> None:
        install_fake_wx()
        import wx
        # Should not raise - tests __ror__
        result = None | wx.Window
        assert result is wx.Window

    def test_instantiation_raises_headless_error(self) -> None:
        install_fake_wx()
        import wx
        with pytest.raises(HeadlessModeError, match='Cannot instantiate/call wx.Window'):
            wx.Window()


class TestFakeWxConstants:
    def test_upper_case_constant_raises_headless_error(self) -> None:
        install_fake_wx()
        import wx
        with pytest.raises(HeadlessModeError, match='Cannot access wx.ID_ANY'):
            wx.ID_ANY

    def test_evt_constant_raises_headless_error(self) -> None:
        install_fake_wx()
        import wx
        with pytest.raises(HeadlessModeError, match='Cannot access wx.EVT_BUTTON'):
            wx.EVT_BUTTON


class TestFakeWxFunctions:
    def test_lower_case_function_raises_headless_error(self) -> None:
        install_fake_wx()
        import wx
        with pytest.raises(HeadlessModeError, match='Cannot access wx.version'):
            wx.version

    def test_private_attr_raises_attribute_error(self) -> None:
        install_fake_wx()
        import wx
        with pytest.raises(AttributeError):
            wx._private


class TestFakeWxTypeChainedAccess:
    def test_chained_upper_camel_case_returns_fake_type(self) -> None:
        install_fake_wx()
        import wx
        result = wx.Window.SubClass
        assert isinstance(result, _FakeWxType)

    def test_chained_constant_raises_headless_error(self) -> None:
        install_fake_wx()
        import wx
        with pytest.raises(HeadlessModeError):
            wx.Window.SOME_CONSTANT
