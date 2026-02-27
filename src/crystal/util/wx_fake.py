"""
Fake wx module system for headless mode.

When Crystal runs in --headless mode, wxPython may not be installed.
This module installs a fake `wx` module into sys.modules so that 
`import wx` succeeds and type annotations like `wx.Window | None` evaluate cleanly,
while preventing actual wx usage at runtime.
"""

from importlib.abc import Loader, MetaPathFinder
from importlib.machinery import ModuleSpec
import re
import sys
from types import ModuleType


# === Installation ===

def install_fake_wx() -> None:
    """
    Install the fake wx module finder into sys.meta_path.

    Must be called before any `import wx` statement.
    """
    # Install _FakeWxFinder
    if 'wx' in sys.modules:
        raise AssertionError('wx was already imported before install_fake_wx()')
    sys.meta_path.insert(0, _FakeWxFinder())


def uninstall_fake_wx() -> None:
    """
    Remove the fake wx module finder from sys.meta_path and
    clean up any fake wx modules from sys.modules.

    Primarily useful for testing.
    """
    # Uninstall _FakeWxFinder
    sys.meta_path[:] = [
        f for f in sys.meta_path
        if not isinstance(f, _FakeWxFinder)
    ]
    
    # Remove all fake wx modules from sys.modules
    to_remove = [
        key for (key, mod) in sys.modules.items()
        if isinstance(mod, _FakeWxModule)
    ]
    for key in to_remove:
        del sys.modules[key]


# === Import Machinery ===

class _FakeWxLoader(Loader):
    """Creates FakeWxModule instances for wx and wx.* imports."""

    def create_module(self, spec: ModuleSpec) -> '_FakeWxModule':
        return _FakeWxModule(spec.name)

    def exec_module(self, module: ModuleType) -> None:
        # Nothing to execute: The module is ready
        pass


class _FakeWxFinder(MetaPathFinder):
    """Intercepts `import wx` and `import wx.*` to return fake modules."""

    _loader = _FakeWxLoader()

    def find_spec(self, fullname, path, target=None):
        if fullname == 'wx' or fullname.startswith('wx.'):
            return ModuleSpec(fullname, self._loader)
        return None


# === Fake Module ===

class _FakeWxModule(ModuleType):
    """
    A fake wx module that returns FakeWxType for UpperCamelCase names
    (types and functions) and raises HeadlessModeError for constants.
    """

    def __init__(self, name: str) -> None:
        super().__init__(name)
        self.__path__: list[str] = []  # required for submodule imports
        self._fake_types: dict[str, _FakeWxType] = {}

    def __getattr__(self, name: str) -> object:
        if name.startswith('_'):
            raise AttributeError(name)
        
        # UpperCamelCase: class/type or function -> return FakeWxType
        if _is_upper_camel_case(name):
            return self._get_or_create_fake_type(name)
        
        # 1. UPPER_CASE (constant) -> raise immediately
        # 2. lower_case or other (unknown) -> raise immediately
        raise HeadlessModeError(f'Cannot access {self.__name__}.{name} in headless mode')

    def _get_or_create_fake_type(self, name: str) -> '_FakeWxType':
        if name not in self._fake_types:
            self._fake_types[name] = _FakeWxType(name)
        return self._fake_types[name]


# === Fake Types ===

class _FakeWxType:
    """
    A sentinel type returned for wx.UpperCamelCase names such as classes
    (like wx.Window) or top-level function (like wx.GetApp).

    As a class, supports use in type annotations (e.g., `wx.Window | None`)
    but raises HeadlessModeError if instantiated.
    
    As a top-level function, raises HeadlessModeError if called.
    """

    def __init__(self, name: str) -> None:
        self._name = name

    def __repr__(self) -> str:
        return f'<FakeWxType: wx.{self._name}>'

    def __call__(self, *args, **kwargs):
        raise HeadlessModeError(
            f'Cannot instantiate/call wx.{self._name} in headless mode'
        )

    def __or__(self, other):
        # Support `wx.Window | None` style annotations
        return self

    def __ror__(self, other):
        # Support `None | wx.Window` style annotations
        return self

    def __getitem__(self, item):
        # Support `wx.Window[...]` style subscripts if any exist
        return self

    def __getattr__(self, name: str):
        if name.startswith('_'):
            raise AttributeError(name)
        
        # Support chained attribute access like wx.Window.SubClass
        if _is_upper_camel_case(name):
            return _FakeWxType(f'{self._name}.{name}')
        
        raise HeadlessModeError(
            f'Cannot access wx.{self._name}.{name} in headless mode'
        )


# === Errors ===

class HeadlessModeError(Exception):
    """Raised when wx functionality is used in headless mode."""
    pass


# === Utility ===

_ALL_UPPER_RE = re.compile(r'^[A-Z][A-Z0-9_]*$')

def _is_all_upper_or_underscore(name: str) -> bool:
    """Check if name matches [A-Z][A-Z0-9_]* (i.e., a constant like ID_ANY)."""
    return _ALL_UPPER_RE.match(name) is not None


def _is_upper_camel_case(name: str) -> bool:
    """Check if name starts with uppercase but is not all-uppercase (i.e., a class name)."""
    return name[0].isupper() and not _is_all_upper_or_underscore(name)
