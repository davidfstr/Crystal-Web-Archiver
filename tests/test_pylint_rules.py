"""
Unit tests for the custom pylint rules defined in crystal_banned_api.py.
"""

import astroid
from crystal_banned_api import CrystalBannedApiChecker
import os
import pylint.testutils
from pylint.checkers import BaseChecker
import subprocess
import tempfile
from textwrap import dedent
from typing import Type


# === C9001: no-direct-thread ===

class TestNoDirectThreadInMemory:
    """In-memory tests for the no-direct-thread rule (C9001)."""
    
    def test_thread_constructor_is_flagged(self) -> None:
        code = dedent(
            '''\
            from threading import Thread
            t = Thread(target=lambda: None)
            '''
        )
        _assert_message_emitted_inmem(code, 'no-direct-thread')
    
    def test_threading_thread_constructor_is_flagged(self) -> None:
        code = dedent(
            '''\
            import threading
            t = threading.Thread(target=lambda: None)
            '''
        )
        _assert_message_emitted_inmem(code, 'no-direct-thread')
    
    def test_bg_call_later_is_allowed(self) -> None:
        code = dedent(
            '''\
            from crystal.util.xthreading import bg_call_later
            bg_call_later(lambda: None)
            '''
        )
        _assert_no_message_emitted_inmem(code, 'no-direct-thread')


# === C9002: no-direct-showmodal ===

class TestNoDirectShowModalInMemory:
    """In-memory tests for the no-direct-showmodal rule (C9002)."""
    
    def test_showmodal_call_is_flagged(self) -> None:
        code = dedent(
            '''\
            dialog = None  # Assume wx.Dialog instance
            result = dialog.ShowModal()
            '''
        )
        _assert_message_emitted_inmem(code, 'no-direct-showmodal')
    
    def test_other_method_is_allowed(self) -> None:
        code = dedent(
            '''\
            obj = None
            result = obj.Show()
            '''
        )
        _assert_no_message_emitted_inmem(code, 'no-direct-showmodal')


# === C9003: no-direct-showwindowmodal ===

class TestNoDirectShowWindowModalInMemory:
    """In-memory tests for the no-direct-showwindowmodal rule (C9003)."""
    
    def test_showwindowmodal_call_is_flagged(self) -> None:
        code = dedent(
            '''\
            dialog = None  # Assume wx.Dialog instance
            dialog.ShowWindowModal()
            '''
        )
        _assert_message_emitted_inmem(code, 'no-direct-showwindowmodal')


# === C9004: no-direct-isdark ===

class TestNoDirectIsDarkInMemory:
    """In-memory tests for the no-direct-isdark rule (C9004)."""
    
    def test_isdark_call_is_flagged(self) -> None:
        code = dedent(
            '''\
            appearance = None  # Assume wx.SystemAppearance instance
            is_dark = appearance.IsDark()
            '''
        )
        _assert_message_emitted_inmem(code, 'no-direct-isdark')


# === C9005: no-direct-bind ===

class TestNoDirectBindInMemory:
    """In-memory tests for the no-direct-bind rule (C9005)."""
    
    def test_bind_call_is_flagged(self) -> None:
        code = dedent(
            '''\
            import wx
            window = None  # Assume wx.Window instance
            window.Bind(wx.EVT_CLOSE, lambda e: None)
            '''
        )
        _assert_message_emitted_inmem(code, 'no-direct-bind')
    
    def test_bind_function_is_allowed(self) -> None:
        code = dedent(
            '''\
            from crystal.util.wx_bind import bind
            import wx
            window = None
            bind(window, wx.EVT_CLOSE, lambda e: None)
            '''
        )
        _assert_no_message_emitted_inmem(code, 'no-direct-bind')


# === C9006: no-direct-setfocus ===

class TestNoDirectSetFocusInMemory:
    """In-memory tests for the no-direct-setfocus rule (C9006)."""
    
    def test_setfocus_call_is_flagged(self) -> None:
        code = dedent(
            '''\
            window = None  # Assume wx.Window instance
            window.SetFocus()
            '''
        )
        _assert_message_emitted_inmem(code, 'no-direct-setfocus')


# === C9007: no-asyncio ===

class TestNoAsyncioInMemory:
    """In-memory tests for the no-asyncio rule (C9007)."""
    
    def test_import_asyncio_is_flagged(self) -> None:
        code = dedent(
            '''\
            import asyncio
            '''
        )
        _assert_message_emitted_inmem(code, 'no-asyncio')
    
    def test_from_asyncio_import_is_flagged(self) -> None:
        code = dedent(
            '''\
            from asyncio import run
            '''
        )
        _assert_message_emitted_inmem(code, 'no-asyncio')
    
    def test_other_import_is_allowed(self) -> None:
        code = dedent(
            '''\
            import sys
            '''
        )
        _assert_no_message_emitted_inmem(code, 'no-asyncio')


# === C9008: no-direct-callafter ===

class TestNoDirectCallAfterInMemory:
    """In-memory tests for the no-direct-callafter rule (C9008)."""
    
    def test_wx_callafter_is_flagged(self) -> None:
        code = dedent(
            '''\
            import wx
            wx.CallAfter(lambda: None)
            '''
        )
        _assert_message_emitted_inmem(code, 'no-direct-callafter')
    
    def test_fg_call_later_is_allowed(self) -> None:
        code = dedent(
            '''\
            from crystal.util.xthreading import fg_call_later
            fg_call_later(lambda: None)
            '''
        )
        _assert_no_message_emitted_inmem(code, 'no-direct-callafter')


# === C9009: no-direct-calllater ===

class TestNoDirectCallLaterInMemory:
    """In-memory tests for the no-direct-calllater rule (C9009)."""
    
    def test_wx_calllater_is_flagged(self) -> None:
        code = dedent(
            '''\
            import wx
            wx.CallLater(100, lambda: None)
            '''
        )
        _assert_message_emitted_inmem(code, 'no-direct-calllater')
    
    def test_timer_is_allowed(self) -> None:
        code = dedent(
            '''\
            from crystal.util.wx_timer import Timer
            Timer(None, 100, lambda: None, one_shot=True)
            '''
        )
        _assert_no_message_emitted_inmem(code, 'no-direct-calllater')


# === C9010: monotonic-durations ===

class TestMonotonicDurationsInMemory:
    """In-memory tests for the monotonic-durations rule (C9010)."""
    
    def test_time_time_call_is_flagged(self) -> None:
        code = dedent(
            '''\
            import time
            start = time.time()
            '''
        )
        _assert_message_emitted_inmem(code, 'monotonic-durations')
    
    def test_time_call_direct_import_is_flagged(self) -> None:
        code = dedent(
            '''\
            from time import time
            start = time()
            '''
        )
        _assert_message_emitted_inmem(code, 'monotonic-durations')
    
    def test_time_monotonic_is_allowed(self) -> None:
        code = dedent(
            '''\
            import time
            start = time.monotonic()
            '''
        )
        _assert_no_message_emitted_inmem(code, 'monotonic-durations')


# === C9011: tuple-missing-parens ===

class TestTupleMissingParens:
    """Tests for the tuple-missing-parens rule (C9011)."""
    
    # --- For loops ---
    
    def test_for_loop_with_parens_is_allowed(self) -> None:
        code = dedent(
            '''\
            d = {}
            for (key, value) in d.items():
                pass
            '''
        )
        _assert_no_message_emitted(code, 'tuple-missing-parens')
    
    def test_for_loop_without_parens_is_flagged(self) -> None:
        code = dedent(
            '''\
            d = {}
            for key, value in d.items():
                pass
            '''
        )
        _assert_message_emitted(code, 'tuple-missing-parens')
    
    # --- Assignment unpacking ---
    
    def test_assignment_unpacking_with_parens_is_allowed(self) -> None:
        code = dedent(
            '''\
            tup = (1, 2)
            (t0, t1) = tup
            '''
        )
        _assert_no_message_emitted(code, 'tuple-missing-parens')
    
    def test_assignment_unpacking_without_parens_is_flagged(self) -> None:
        code = dedent(
            '''\
            tup = (1, 2)
            t0, t1 = tup
            '''
        )
        _assert_message_emitted(code, 'tuple-missing-parens')
    
    # --- Single-element tuple unpacking ---
    
    def test_single_element_unpacking_with_parens_is_allowed(self) -> None:
        code = dedent(
            '''\
            cell = (1,)
            (t0,) = cell
            '''
        )
        _assert_no_message_emitted(code, 'tuple-missing-parens')
    
    def test_single_element_unpacking_without_parens_is_flagged(self) -> None:
        code = dedent(
            '''\
            cell = (1,)
            t0, = cell
            '''
        )
        _assert_message_emitted(code, 'tuple-missing-parens')
    
    # --- Tuple literals on right side of assignment ---
    
    def test_tuple_literal_with_parens_is_allowed(self) -> None:
        code = dedent(
            '''\
            tup = (1, 2)
            '''
        )
        _assert_no_message_emitted(code, 'tuple-missing-parens')
    
    def test_tuple_literal_without_parens_is_flagged(self) -> None:
        code = dedent(
            '''\
            tup = 1, 2
            '''
        )
        _assert_message_emitted(code, 'tuple-missing-parens')
    
    # --- Subscript with tuple key ---
    
    def test_subscript_tuple_key_with_parens_is_allowed(self) -> None:
        code = dedent(
            '''\
            lookup = {}
            lookup[(1, 2)] = True
            '''
        )
        _assert_no_message_emitted(code, 'tuple-missing-parens')
    
    def test_subscript_tuple_key_without_parens_is_flagged(self) -> None:
        code = dedent(
            '''\
            lookup = {}
            lookup[1, 2] = True
            '''
        )
        _assert_message_emitted(code, 'tuple-missing-parens')
    
    # --- Type annotations should NOT be flagged ---
    
    def test_tuple_type_annotation_is_allowed(self) -> None:
        code = dedent(
            '''\
            tup: tuple[str, str]
            '''
        )
        _assert_no_message_emitted(code, 'tuple-missing-parens')
    
    def test_dict_type_annotation_is_allowed(self) -> None:
        code = dedent(
            '''\
            d: dict[str, int]
            '''
        )
        _assert_no_message_emitted(code, 'tuple-missing-parens')
    
    def test_function_return_type_annotation_is_allowed(self) -> None:
        code = dedent(
            '''\
            def foo() -> tuple[str, int]:
                return ('a', 1)
            '''
        )
        _assert_no_message_emitted(code, 'tuple-missing-parens')
    
    def test_function_param_type_annotation_is_allowed(self) -> None:
        code = dedent(
            '''\
            def foo(x: tuple[str, int]) -> None:
                pass
            '''
        )
        _assert_no_message_emitted(code, 'tuple-missing-parens')
    
    def test_typealias_with_literal_is_allowed(self) -> None:
        code = dedent(
            '''\
            from typing import Literal, TypeAlias
            EntityTitleFormat: TypeAlias = Literal['url_name', 'name_url']
            '''
        )
        _assert_no_message_emitted(code, 'tuple-missing-parens')
    
    def test_cast_first_argument_is_allowed(self) -> None:
        code = dedent(
            '''\
            from typing import Literal, cast
            proxy_type = cast(Literal['none', 'socks5'], 'none')
            '''
        )
        _assert_no_message_emitted(code, 'tuple-missing-parens')


# === C9012: no-direct-crystal-subprocess ===

class TestNoDirectCrystalSubprocess:
    """Tests for the no-direct-crystal-subprocess rule (C9012)."""
    
    def test_list_with_crystal_literal_first_is_flagged(self) -> None:
        code = dedent(
            '''\
            import subprocess
            args = []
            crystal = subprocess.Popen(['crystal', *args])
            '''
        )
        _assert_message_emitted(code, 'no-direct-crystal-subprocess')
    
    def test_list_variable_with_crystal_literal_first_is_flagged(self) -> None:
        code = dedent(
            '''\
            args = []
            cmd = ['crystal', *args]
            '''
        )
        _assert_message_emitted(code, 'no-direct-crystal-subprocess')
    
    def test_list_with_get_crystal_command_is_allowed(self) -> None:
        code = dedent(
            '''\
            import subprocess
            from crystal.tests.util.cli import get_crystal_command
            args = []
            crystal = subprocess.Popen([*get_crystal_command(), *args])
            '''
        )
        _assert_no_message_emitted(code, 'no-direct-crystal-subprocess')
    
    def test_list_variable_with_get_crystal_command_is_allowed(self) -> None:
        code = dedent(
            '''\
            from crystal.tests.util.cli import get_crystal_command
            args = []
            cmd = [*get_crystal_command(), *args]
            '''
        )
        _assert_no_message_emitted(code, 'no-direct-crystal-subprocess')
    
    def test_list_with_other_string_first_is_allowed(self) -> None:
        code = dedent(
            '''\
            import subprocess
            args = []
            proc = subprocess.Popen(['python', *args])
            '''
        )
        _assert_no_message_emitted(code, 'no-direct-crystal-subprocess')
    
    def test_empty_list_is_allowed(self) -> None:
        code = dedent(
            '''\
            empty = []
            '''
        )
        _assert_no_message_emitted(code, 'no-direct-crystal-subprocess')


# === C9013: no-double-quoted-string ===

class TestNoDoubleQuotedString:
    """Tests for the no-double-quoted-string rule (C9013)."""
    
    # --- Regular strings ---
    
    def test_single_quoted_string_is_allowed(self) -> None:
        code = dedent(
            """\
            name = 'crystal-banned-api'
            """
        )
        _assert_no_message_emitted(code, 'no-double-quoted-string')
    
    def test_double_quoted_string_is_flagged(self) -> None:
        code = dedent(
            """\
            name = "crystal-banned-api"
            """
        )
        _assert_message_emitted(code, 'no-double-quoted-string')
    
    # --- Strings containing single quotes ---
    
    def test_double_quoted_string_with_single_quote_in_value_is_allowed(self) -> None:
        code = dedent(
            """\
            explanation = "Don't construct threads directly"
            """
        )
        _assert_no_message_emitted(code, 'no-double-quoted-string')
    
    # --- f-strings ---
    
    def test_single_quoted_fstring_is_allowed(self) -> None:
        code = dedent(
            """\
            print(f'AppPreferences: Property changed')
            """
        )
        _assert_no_message_emitted(code, 'no-double-quoted-string')
    
    def test_double_quoted_fstring_is_flagged(self) -> None:
        code = dedent(
            """\
            print(f"AppPreferences: Property changed")
            """
        )
        _assert_message_emitted(code, 'no-double-quoted-string')
    
    # --- r-strings (raw strings) ---
    
    def test_single_quoted_rstring_is_allowed(self) -> None:
        code = dedent(
            """\
            import re
            if re.fullmatch(r'[0-9]+', 'foo'): ...
            """
        )
        _assert_no_message_emitted(code, 'no-double-quoted-string')
    
    def test_double_quoted_rstring_is_flagged(self) -> None:
        code = dedent(
            """\
            import re
            if re.fullmatch(r"[0-9]+", "foo"): ...
            """
        )
        _assert_message_emitted(code, 'no-double-quoted-string')
    
    # --- Triple-quoted strings (docstrings, multiline) ---
    
    def test_triple_double_quoted_string_is_allowed(self) -> None:
        code = dedent(
            '''\
            def register(linter):
                """Register the checker with pylint."""
                ...
            '''
        )
        _assert_no_message_emitted(code, 'no-double-quoted-string')
    
    def test_triple_single_quoted_string_is_allowed(self) -> None:
        code = dedent(
            """\
            import textwrap
            code = textwrap.dedent(
                '''\\
                import wx
                
                return wx.GetApp()
                '''
            )
            """
        )
        _assert_no_message_emitted(code, 'no-double-quoted-string')
    
    # --- Nested strings inside f-strings ---
    
    def test_double_quoted_string_nested_in_fstring_is_allowed(self) -> None:
        code = dedent(
            """\
            condition = True
            value = f'{"set" if condition else "unset"}'
            """
        )
        _assert_no_message_emitted(code, 'no-double-quoted-string')
    
    def test_double_quoted_rstring_nested_in_fstring_is_allowed(self) -> None:
        code = dedent(
            """\
            condition = True
            value = f'{r"set" if condition else r"unset"}'
            """
        )
        _assert_no_message_emitted(code, 'no-double-quoted-string')
    
    def test_double_quoted_fstring_nested_in_fstring_is_allowed(self) -> None:
        code = dedent(
            """\
            condition = True
            value = f'{f"set" if condition else f"unset"}'
            """
        )
        _assert_no_message_emitted(code, 'no-double-quoted-string')


# === Utilities ===

# --- Utilities: In-Memory Testing Helpers ---

def _assert_message_emitted_inmem(code: str, message_id: str) -> None:
    """
    Assert that checker emits the given message for the code (in-memory).
    
    message_id should be the symbolic name (e.g. 'no-direct-thread').
    """
    messages = _run_checker_on_code(code)
    message_ids = [msg.msg_id for msg in messages]
    assert message_id in message_ids, (
        f'Expected message {message_id} not found. Got: {message_ids}'
    )


def _assert_no_message_emitted_inmem(code: str, message_id: str) -> None:
    """
    Assert that checker does not emit the given message (in-memory).
    
    message_id should be the symbolic name (e.g. 'no-direct-thread').
    """
    messages = _run_checker_on_code(code)
    message_ids = [msg.msg_id for msg in messages]
    assert message_id not in message_ids, (
        f'Unexpected message {message_id} found. Got: {message_ids}'
    )


def _run_checker_on_code(code: str, checker_class: Type[BaseChecker] = CrystalBannedApiChecker) -> list[pylint.testutils.MessageTest]:
    """
    Run a pylint checker on code in-memory and return messages.
    
    This is much faster than _run_pylint_on_code() since it:
    - Doesn't spawn a subprocess
    - Doesn't write to filesystem
    - Directly invokes the checker
    """
    # Create a test case instance
    test_case = _InMemoryCheckerTestCase()
    test_case.CHECKER_CLASS = checker_class
    test_case.setup_method()
    
    # Parse the code into an AST
    module = astroid.parse(code)
    
    # Walk the AST with the checker to trigger visit_* methods
    test_case.walk(module)
    
    # Return collected messages
    return test_case.linter.release_messages()


class _InMemoryCheckerTestCase(pylint.testutils.CheckerTestCase):
    """
    Base class for in-memory pylint checker tests.
    
    Uses pylint's in-memory API to avoid subprocess and filesystem overhead.
    Much faster than _run_pylint_on_code().
    """
    CHECKER_CLASS: Type[BaseChecker] = CrystalBannedApiChecker


# --- Utilities: In-Filesystem Testing Helpers ---

def _assert_message_emitted(code: str, message_id: str) -> None:
    """
    Assert that pylint emits the given message for the code.
    
    message_id should be the symbolic name (e.g. 'tuple-missing-parens').
    """
    (exit_code, output) = _run_pylint_on_code(code)
    # Pylint output format: "C9011: ... (tuple-missing-parens)"
    # Check for symbolic name in parentheses
    assert f'({message_id})' in output, (
        f'Expected message {message_id} not found in output:\n{output}'
    )


def _assert_no_message_emitted(code: str, message_id: str) -> None:
    """
    Assert that pylint does not emit the given message for the code.
    
    message_id should be the symbolic name (e.g. 'tuple-missing-parens').
    """
    (exit_code, output) = _run_pylint_on_code(code)
    # Pylint output format: "C9011: ... (tuple-missing-parens)"
    # Check for symbolic name in parentheses
    assert f'({message_id})' not in output, (
        f'Unexpected message {message_id} found in output:\n{output}'
    )


def _run_pylint_on_code(code: str) -> tuple[int, str]:
    """
    Run pylint with crystal_banned_api rules on the given code.
    
    Returns a tuple of (exit_code, output).
    """
    with tempfile.NamedTemporaryFile(
        mode='w', suffix='.py', delete=False
    ) as f:
        f.write(code)
        temp_path = f.name
    
    try:
        result = subprocess.run(
            [
                'pylint',
                '--rcfile=.pylintrc',
                temp_path,
            ],
            capture_output=True,
            text=True,
            env={**os.environ, 'PYTHONPATH': 'src'},
        )
        return (result.returncode, result.stdout + result.stderr)
    finally:
        os.unlink(temp_path)

