"""
Unit tests for the custom pylint rules defined in crystal_banned_api.py.
"""

import subprocess
import tempfile
import os
from textwrap import dedent


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


def _assert_message_emitted(code: str, message_id: str) -> None:
    """Assert that pylint emits the given message for the code."""
    (exit_code, output) = _run_pylint_on_code(code)
    assert message_id in output, (
        f'Expected message {message_id} not found in output:\n{output}'
    )


def _assert_no_message_emitted(code: str, message_id: str) -> None:
    """Assert that pylint does not emit the given message for the code."""
    (exit_code, output) = _run_pylint_on_code(code)
    assert message_id not in output, (
        f'Unexpected message {message_id} found in output:\n{output}'
    )


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
        _assert_no_message_emitted(code, 'C9011')
    
    def test_for_loop_without_parens_is_flagged(self) -> None:
        code = dedent(
            '''\
            d = {}
            for key, value in d.items():
                pass
            '''
        )
        _assert_message_emitted(code, 'C9011')
    
    # --- Assignment unpacking ---
    
    def test_assignment_unpacking_with_parens_is_allowed(self) -> None:
        code = dedent(
            '''\
            tup = (1, 2)
            (t0, t1) = tup
            '''
        )
        _assert_no_message_emitted(code, 'C9011')
    
    def test_assignment_unpacking_without_parens_is_flagged(self) -> None:
        code = dedent(
            '''\
            tup = (1, 2)
            t0, t1 = tup
            '''
        )
        _assert_message_emitted(code, 'C9011')
    
    # --- Single-element tuple unpacking ---
    
    def test_single_element_unpacking_with_parens_is_allowed(self) -> None:
        code = dedent(
            '''\
            cell = (1,)
            (t0,) = cell
            '''
        )
        _assert_no_message_emitted(code, 'C9011')
    
    def test_single_element_unpacking_without_parens_is_flagged(self) -> None:
        code = dedent(
            '''\
            cell = (1,)
            t0, = cell
            '''
        )
        _assert_message_emitted(code, 'C9011')
    
    # --- Tuple literals on right side of assignment ---
    
    def test_tuple_literal_with_parens_is_allowed(self) -> None:
        code = dedent(
            '''\
            tup = (1, 2)
            '''
        )
        _assert_no_message_emitted(code, 'C9011')
    
    def test_tuple_literal_without_parens_is_flagged(self) -> None:
        code = dedent(
            '''\
            tup = 1, 2
            '''
        )
        _assert_message_emitted(code, 'C9011')
    
    # --- Subscript with tuple key ---
    
    def test_subscript_tuple_key_with_parens_is_allowed(self) -> None:
        code = dedent(
            '''\
            lookup = {}
            lookup[(1, 2)] = True
            '''
        )
        _assert_no_message_emitted(code, 'C9011')
    
    def test_subscript_tuple_key_without_parens_is_flagged(self) -> None:
        code = dedent(
            '''\
            lookup = {}
            lookup[1, 2] = True
            '''
        )
        _assert_message_emitted(code, 'C9011')
    
    # --- Type annotations should NOT be flagged ---
    
    def test_tuple_type_annotation_is_allowed(self) -> None:
        code = dedent(
            '''\
            tup: tuple[str, str]
            '''
        )
        _assert_no_message_emitted(code, 'C9011')
    
    def test_dict_type_annotation_is_allowed(self) -> None:
        code = dedent(
            '''\
            d: dict[str, int]
            '''
        )
        _assert_no_message_emitted(code, 'C9011')
    
    def test_function_return_type_annotation_is_allowed(self) -> None:
        code = dedent(
            '''\
            def foo() -> tuple[str, int]:
                return ('a', 1)
            '''
        )
        _assert_no_message_emitted(code, 'C9011')
    
    def test_function_param_type_annotation_is_allowed(self) -> None:
        code = dedent(
            '''\
            def foo(x: tuple[str, int]) -> None:
                pass
            '''
        )
        _assert_no_message_emitted(code, 'C9011')
    
    def test_typealias_with_literal_is_allowed(self) -> None:
        code = dedent(
            '''\
            from typing import Literal, TypeAlias
            EntityTitleFormat: TypeAlias = Literal['url_name', 'name_url']
            '''
        )
        _assert_no_message_emitted(code, 'C9011')
    
    def test_cast_first_argument_is_allowed(self) -> None:
        code = dedent(
            '''\
            from typing import Literal, cast
            proxy_type = cast(Literal['none', 'socks5'], 'none')
            '''
        )
        _assert_no_message_emitted(code, 'C9011')


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
        _assert_message_emitted(code, 'C9012')
    
    def test_list_variable_with_crystal_literal_first_is_flagged(self) -> None:
        code = dedent(
            '''\
            args = []
            cmd = ['crystal', *args]
            '''
        )
        _assert_message_emitted(code, 'C9012')
    
    def test_list_with_get_crystal_command_is_allowed(self) -> None:
        code = dedent(
            '''\
            import subprocess
            from crystal.tests.util.cli import get_crystal_command
            args = []
            crystal = subprocess.Popen([*get_crystal_command(), *args])
            '''
        )
        _assert_no_message_emitted(code, 'C9012')
    
    def test_list_variable_with_get_crystal_command_is_allowed(self) -> None:
        code = dedent(
            '''\
            from crystal.tests.util.cli import get_crystal_command
            args = []
            cmd = [*get_crystal_command(), *args]
            '''
        )
        _assert_no_message_emitted(code, 'C9012')
    
    def test_list_with_other_string_first_is_allowed(self) -> None:
        code = dedent(
            '''\
            import subprocess
            args = []
            proc = subprocess.Popen(['python', *args])
            '''
        )
        _assert_no_message_emitted(code, 'C9012')
    
    def test_empty_list_is_allowed(self) -> None:
        code = dedent(
            '''\
            empty = []
            '''
        )
        _assert_no_message_emitted(code, 'C9012')


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
        _assert_no_message_emitted(code, 'C9013')
    
    def test_double_quoted_string_is_flagged(self) -> None:
        code = dedent(
            """\
            name = "crystal-banned-api"
            """
        )
        _assert_message_emitted(code, 'C9013')
    
    # --- Strings containing single quotes ---
    
    def test_double_quoted_string_with_single_quote_in_value_is_allowed(self) -> None:
        code = dedent(
            """\
            explanation = "Don't construct threads directly"
            """
        )
        _assert_no_message_emitted(code, 'C9013')
    
    # --- f-strings ---
    
    def test_single_quoted_fstring_is_allowed(self) -> None:
        code = dedent(
            """\
            print(f'AppPreferences: Property changed')
            """
        )
        _assert_no_message_emitted(code, 'C9013')
    
    def test_double_quoted_fstring_is_flagged(self) -> None:
        code = dedent(
            """\
            print(f"AppPreferences: Property changed")
            """
        )
        _assert_message_emitted(code, 'C9013')
    
    # --- r-strings (raw strings) ---
    
    def test_single_quoted_rstring_is_allowed(self) -> None:
        code = dedent(
            """\
            import re
            if re.fullmatch(r'[0-9]+', 'foo'): ...
            """
        )
        _assert_no_message_emitted(code, 'C9013')
    
    def test_double_quoted_rstring_is_flagged(self) -> None:
        code = dedent(
            """\
            import re
            if re.fullmatch(r"[0-9]+", "foo"): ...
            """
        )
        _assert_message_emitted(code, 'C9013')
    
    # --- Triple-quoted strings (docstrings, multiline) ---
    
    def test_triple_double_quoted_string_is_allowed(self) -> None:
        code = dedent(
            '''\
            def register(linter):
                """Register the checker with pylint."""
                ...
            '''
        )
        _assert_no_message_emitted(code, 'C9013')
    
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
        _assert_no_message_emitted(code, 'C9013')
    
    # --- Nested strings inside f-strings ---
    
    def test_double_quoted_string_nested_in_fstring_is_allowed(self) -> None:
        code = dedent(
            """\
            condition = True
            value = f'{"set" if condition else "unset"}'
            """
        )
        _assert_no_message_emitted(code, 'C9013')
    
    def test_double_quoted_rstring_nested_in_fstring_is_allowed(self) -> None:
        code = dedent(
            """\
            condition = True
            value = f'{r"set" if condition else r"unset"}'
            """
        )
        _assert_no_message_emitted(code, 'C9013')
    
    def test_double_quoted_fstring_nested_in_fstring_is_allowed(self) -> None:
        code = dedent(
            """\
            condition = True
            value = f'{f"set" if condition else f"unset"}'
            """
        )
        _assert_no_message_emitted(code, 'C9013')
