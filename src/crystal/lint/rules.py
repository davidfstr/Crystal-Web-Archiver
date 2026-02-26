"""
Pylint plugin to ban specific API patterns in Crystal.
"""

from astroid import nodes
import os
from pylint.checkers import BaseChecker
import re
import sys
from typing import List, Tuple, Optional


class CrystalLintRules(BaseChecker):
    """Checker to detect various Crystal-specific banned code patterns."""
    
    name = 'crystal-lint-rules'
    
    # When non-None, tracks fixes for an auto-fixer caller to apply.
    # This list is not used by PyLint itself.
    _fixes: 'Optional[List[StringQuoteFix]]' = None
    
    # Types of messages/diagnostics this plugin can emit. Each message type has:
    # - a short error code (ex: 'C9001')
    # - an error message that is printed when the message diagnostic is emitted
    #   (ex: 'Don't construct threads directly; ...')
    # - a long error code (ex: 'no-direct-thread')
    # - a help string, used in `pylint --list-msgs`
    #   (ex: 'Direct Thread(...) construction is not allowed. ...')
    # 
    # NOTE: Any new C9xxx codes added here should also be added to
    #       "enable" key in .pylintrc.
    msgs = {
        'C9001': (
            "Don't construct threads directly; use bg_call_later() from crystal.util.xthreading instead",
            'no-direct-thread',
            'Direct Thread(...) construction is not allowed. Use bg_call_later() instead.',
        ),
        'C9002': (
            "Don't call wx.Dialog.ShowModal() directly; use ShowModal() from crystal.util.wx_dialog instead",
            'no-direct-showmodal',
            'Direct ShowModal() call on dialog is not allowed. Use ShowModal() from crystal.util.wx_dialog instead.',
        ),
        'C9003': (
            "Don't call wx.Dialog.ShowWindowModal() directly; use ShowWindowModal() from crystal.util.wx_dialog instead",
            'no-direct-showwindowmodal',
            'Direct ShowWindowModal() call on dialog is not allowed. Use ShowWindowModal() from crystal.util.wx_dialog instead.',
        ),
        'C9004': (
            "Don't call wx.SystemSettings.GetAppearance().IsDark() directly; use IsDark() from crystal.util.wx_system_appearance instead",
            'no-direct-isdark',
            'Direct IsDark() call is not allowed. Use IsDark() from crystal.util.wx_system_appearance instead.',
        ),
        'C9005': (
            "Don't call wx.Window.Bind() directly; use bind() from crystal.util.wx_bind instead",
            'no-direct-bind',
            'Direct Bind() call is not allowed. Use bind() from crystal.util.wx_bind instead.',
        ),
        'C9006': (
            "Don't call wx.Window.SetFocus() directly; use SetFocus() from crystal.util.wx_window instead",
            'no-direct-setfocus',
            'Direct SetFocus() call is not allowed. Use SetFocus() from crystal.util.wx_window instead.',
        ),
        'C9007': (
            'Crystal does not use asyncio. Async functions may only be called inside an async end-to-end test function or inside an async callable passed to run_test() in crystal.tests.util.runner.',
            'no-asyncio',
            'Asyncio imports are not allowed. Use async end-to-end tests or async callables with run_test() instead.',
        ),
        'C9008': (
            "Don't call wx.CallAfter() directly; use fg_call_later() from crystal.util.xthreading instead",
            'no-direct-callafter',
            'Direct CallAfter() call is not allowed. Use fg_call_later() from crystal.util.xthreading instead.',
        ),
        'C9009': (
            "Don't call wx.CallLater() directly; use Timer(..., one_shot=True) from crystal.util.wx_timer instead.",
            'no-direct-calllater',
            'Direct CallLater() call is not allowed. Use Timer from crystal.util.wx_timer instead.',
        ),
        'C9010': (
            "Don't use time.time() when measuring durations; use time.monotonic() instead",
            'monotonic-durations',
            'time.time() is not suitable for measuring durations. Use time.monotonic() instead.',
        ),
        'C9011': (
            'Tuple is missing parentheses; use `(k, v)` instead of `k, v`',
            'tuple-missing-parens',
            'Tuples should always be parenthesized. Use `(k, v)` instead of `k, v`.',
        ),
        'C9012': (
            "Don't assume a Crystal subprocess can be started with ['crystal', ...]; use [*get_crystal_command(), ...] instead",
            'no-direct-crystal-subprocess',
            "Direct ['crystal', ...] is not allowed. Use [*get_crystal_command(), ...] from crystal.tests.util.cli instead.",
        ),
        'C9013': (
            'Double-quoted string literal; use single-quoted string literal instead',
            'no-double-quoted-string',
            'String literals should use single quotes rather than double quotes.',
        ),
        'C9014': (
            "Don't call project._db.commit() directly; use `with project._db()` to manage transactions instead",
            'no-direct-database-commit',
            'Direct commit() call on database is not allowed. Use `with project._db()` to manage transactions instead.',
        ),
        'C9015': (
            "Don't call project._db.rollback() directly; use `with project._db()` to manage transactions instead",
            'no-direct-database-rollback',
            'Direct rollback() call on database is not allowed. Use `with project._db()` to manage transactions instead.',
        ),
        'C9016': (
            "Don't use wx.CONSTANT at declaration time (outside function/method bodies)",
            'no-wx-constant-at-declaration-time',
            'wx.UPPER_CASE constants at declaration time are not compatible with --headless mode.',
        ),
    }
    
    # === Visit Call ===
    
    def visit_call(self, node: nodes.Call) -> None:
        """Check for banned API patterns in function calls."""
        
        # Thread(...), threading.Thread(...)
        if self._is_thread_call(node):
            self.add_message('no-direct-thread', node=node)
        
        # dialog.ShowModal(...)
        if self._is_dialog_showmodal_call(node):
            self.add_message('no-direct-showmodal', node=node)
        
        # dialog.ShowWindowModal(...)
        if self._is_dialog_showwindowmodal_call(node):
            self.add_message('no-direct-showwindowmodal', node=node)
        
        # wx.SystemSettings.GetAppearance().IsDark(...)
        if self._is_appearance_isdark_call(node):
            self.add_message('no-direct-isdark', node=node)
        
        # window.Bind(...)
        if self._is_window_bind_call(node):
            self.add_message('no-direct-bind', node=node)
        
        # window.SetFocus(...)
        if self._is_window_setfocus_call(node):
            self.add_message('no-direct-setfocus', node=node)
        
        # wx.CallAfter(...)
        if self._is_callafter_call(node):
            self.add_message('no-direct-callafter', node=node)
        
        # wx.CallLater(...)
        if self._is_calllater_call(node):
            self.add_message('no-direct-calllater', node=node)
        
        # time.time(...)
        if self._is_time_time_call(node):
            self.add_message('monotonic-durations', node=node)
        
        # something.commit(...)
        if self._is_database_commit_call(node):
            self.add_message('no-direct-database-commit', node=node)
        
        # something.rollback(...)
        if self._is_database_rollback_call(node):
            self.add_message('no-direct-database-rollback', node=node)
    
    def _is_thread_call(self, node: nodes.Call) -> bool:
        # Thread(...)
        if isinstance(node.func, nodes.Name) and node.func.name == 'Thread':
            return True
        
        # threading.Thread(...)
        if isinstance(node.func, nodes.Attribute):
            if node.func.attrname == 'Thread':
                if isinstance(node.func.expr, nodes.Name):
                    if node.func.expr.name == 'threading':
                        return True
        
        return False
    
    def _is_dialog_showmodal_call(self, node: nodes.Call) -> bool:
        # dialog.ShowModal(...)
        if isinstance(node.func, nodes.Attribute):
            if node.func.attrname == 'ShowModal':
                # This is a call to ShowModal() method on some object,
                # presumably a wx.Dialog. Ban it.
                return True
        
        return False
    
    def _is_dialog_showwindowmodal_call(self, node: nodes.Call) -> bool:
        # dialog.ShowWindowModal(...)
        if isinstance(node.func, nodes.Attribute):
            if node.func.attrname == 'ShowWindowModal':
                # This is a call to ShowWindowModal() method on some object,
                # presumably a wx.Dialog. Ban it.
                return True
        
        return False
    
    def _is_appearance_isdark_call(self, node: nodes.Call) -> bool:
        # wx.SystemSettings.GetAppearance().IsDark(...)
        if isinstance(node.func, nodes.Attribute):
            if node.func.attrname == 'IsDark':
                # This is a call to IsDark() method on some object,
                # presumably wx.SystemSettings.GetAppearance(). Ban it.
                return True
        
        return False
    
    def _is_window_bind_call(self, node: nodes.Call) -> bool:
        # window.Bind(...)
        if isinstance(node.func, nodes.Attribute):
            if node.func.attrname == 'Bind':
                # This is a call to Bind() method on some object,
                # presumably a wx.Window. Ban it.
                return True
        
        return False
    
    def _is_window_setfocus_call(self, node: nodes.Call) -> bool:
        # window.SetFocus(...)
        if isinstance(node.func, nodes.Attribute):
            if node.func.attrname == 'SetFocus':
                # This is a call to SetFocus() method on some object,
                # presumably a wx.Window. Ban it.
                return True
        
        return False
    
    def _is_callafter_call(self, node: nodes.Call) -> bool:
        # wx.CallAfter(...)
        if isinstance(node.func, nodes.Attribute):
            if node.func.attrname == 'CallAfter':
                if isinstance(node.func.expr, nodes.Name):
                    if node.func.expr.name == 'wx':
                        return True
        
        return False
    
    def _is_calllater_call(self, node: nodes.Call) -> bool:
        # wx.CallLater(...)
        if isinstance(node.func, nodes.Attribute):
            if node.func.attrname == 'CallLater':
                if isinstance(node.func.expr, nodes.Name):
                    if node.func.expr.name == 'wx':
                        return True
        
        return False
    
    def _is_time_time_call(self, node: nodes.Call) -> bool:
        # time.time(...)
        if isinstance(node.func, nodes.Attribute):
            if node.func.attrname == 'time':
                if isinstance(node.func.expr, nodes.Name):
                    if node.func.expr.name == 'time':
                        return True
        
        # time() - assumed to be imported directly from the "time" module
        if isinstance(node.func, nodes.Name) and node.func.name == 'time':
            return True
        
        return False
    
    def _is_database_commit_call(self, node: nodes.Call) -> bool:
        # something.commit(...)
        if isinstance(node.func, nodes.Attribute):
            if node.func.attrname == 'commit':
                return True
        
        return False
    
    def _is_database_rollback_call(self, node: nodes.Call) -> bool:
        # something.rollback(...)
        if isinstance(node.func, nodes.Attribute):
            if node.func.attrname == 'rollback':
                return True
        
        return False
    
    # === Visit Import ===
    
    def visit_import(self, node: nodes.Import) -> None:
        """Check for banned imports."""
        
        # import asyncio
        for (module_name, _) in node.names:
            if module_name == 'asyncio':
                self.add_message('no-asyncio', node=node)
    
    def visit_importfrom(self, node: nodes.ImportFrom) -> None:
        """Check for banned from imports."""
        
        # from asyncio import ...
        if node.modname == 'asyncio':
            self.add_message('no-asyncio', node=node)
    
    # === Visit Attribute (wx constants) ===

    def visit_attribute(self, node: nodes.Attribute) -> None:
        """Check for wx.CONSTANT usage outside function/method bodies."""
        if not self._is_wx_constant_at_declaration_time(node):
            return
        self.add_message('no-wx-constant-at-declaration-time', node=node)

    def _is_wx_constant_at_declaration_time(self, node: nodes.Attribute) -> bool:
        """
        Check if this is a wx.UPPER_CASE attribute access outside a
        function/method body.
        """
        # Must be wx.SOMETHING
        if not isinstance(node.expr, nodes.Name) or node.expr.name != 'wx':
            return False
        # Must be UPPER_CASE
        name = node.attrname
        if not self._is_wx_constant_name(name):
            return False
        # Must be outside a function/method body
        if self._is_inside_function_body(node):
            return False
        return True

    _WX_CONSTANT_RE = re.compile(r'^[A-Z][A-Z0-9_]+$')

    @classmethod
    def _is_wx_constant_name(cls, name: str) -> bool:
        """Check if name matches a wx constant pattern like ID_ANY, EVT_BUTTON, etc."""
        return cls._WX_CONSTANT_RE.fullmatch(name) is not None
    
    def _is_inside_function_body(self, node: nodes.NodeNG) -> bool:
        """Check if the node is inside a FunctionDef or AsyncFunctionDef body."""
        current = node.parent
        while current is not None:
            if isinstance(current, (nodes.FunctionDef, nodes.AsyncFunctionDef)):
                return True
            current = current.parent
        return False

    # === Visit Tuple ===
    
    def visit_tuple(self, node: nodes.Tuple) -> None:
        """Check for tuples without parentheses."""
        # Skip tuples inside type annotations (e.g., tuple[str, str])
        if self._is_in_annotation_context(node):
            return
        if not self._tuple_has_parens(node):
            self.add_message('tuple-missing-parens', node=node)
    
    def _is_in_annotation_context(self, node: nodes.NodeNG) -> bool:
        """Check if the node is inside a type annotation context."""
        current = node
        while current is not None:
            parent = current.parent
            if parent is None:
                break
            
            # Check if we're in an annotated assignment's annotation
            if isinstance(parent, nodes.AnnAssign):
                if current is parent.annotation:
                    return True
                # Check if the annotation is TypeAlias - then the value is also a type
                if current is parent.value and self._is_typealias_annotation(parent):
                    return True
            
            # Check if we're in a function's return annotation
            if isinstance(parent, nodes.FunctionDef):
                if current is parent.returns:
                    return True
            
            # Check if we're in a function argument's annotation
            if isinstance(parent, nodes.Arguments):
                # Check annotations list
                if parent.annotations and current in parent.annotations:
                    return True
                # Check posonlyargs_annotations (positional-only args)
                if hasattr(parent, 'posonlyargs_annotations'):
                    if parent.posonlyargs_annotations and current in parent.posonlyargs_annotations:
                        return True
                # Check kwonlyargs_annotations
                if parent.kwonlyargs_annotations and current in parent.kwonlyargs_annotations:
                    return True
                # Check varargannotation and kwargannotation
                if current is parent.varargannotation or current is parent.kwargannotation:
                    return True
            
            # Check if we're in the first argument of cast()
            if isinstance(parent, nodes.Call):
                if self._is_cast_call(parent) and parent.args and current is parent.args[0]:
                    return True
            
            current = parent
        
        return False
    
    def _is_typealias_annotation(self, node: nodes.AnnAssign) -> bool:
        """Check if the annotation is TypeAlias."""
        ann = node.annotation
        if isinstance(ann, nodes.Name) and ann.name == 'TypeAlias':
            return True
        if isinstance(ann, nodes.Attribute) and ann.attrname == 'TypeAlias':
            return True
        return False
    
    def _is_cast_call(self, node: nodes.Call) -> bool:
        """Check if this is a call to typing.cast()."""
        # cast(...)
        if isinstance(node.func, nodes.Name) and node.func.name == 'cast':
            return True
        # typing.cast(...)
        if isinstance(node.func, nodes.Attribute):
            if node.func.attrname == 'cast':
                if isinstance(node.func.expr, nodes.Name):
                    if node.func.expr.name == 'typing':
                        return True
        return False
    
    def _tuple_has_parens(self, node: nodes.Tuple) -> bool:
        """Check if a tuple has parentheses by examining source code."""
        try:
            lines = _read_source_lines(node)
            
            # Get the line (0-indexed)
            line = lines[node.lineno - 1]
            
            # Check if the character at col_offset is '('
            if node.col_offset < len(line):
                return line[node.col_offset] == '('
        except Exception:
            pass
        return True  # Assume has parens if we can't check (fail safe)
    
    # === Visit List ===
    
    def visit_list(self, node: nodes.List) -> None:
        """Check for banned list patterns."""
        # ['crystal', ...]
        if self._is_crystal_subprocess_list(node):
            self.add_message('no-direct-crystal-subprocess', node=node)
    
    def _is_crystal_subprocess_list(self, node: nodes.List) -> bool:
        """Check if this is a list starting with 'crystal' string literal."""
        if node.elts:  # Check if list has elements
            first_elem = node.elts[0]
            if isinstance(first_elem, nodes.Const):
                if first_elem.value == 'crystal':
                    return True
        return False
    
    # === Visit Const (String Literals) ===
    
    def visit_const(self, node: nodes.Const) -> None:
        """Check for double-quoted string literals."""
        # Only check string constants
        if not isinstance(node.value, str):
            return
        
        # Exception: A string containing a single quote in its value may use double quotes
        if "'" in node.value:
            return
        
        # Exception: A single-quoted f-string may contain a double-quoted string literal
        if self._is_inside_fstring(node):
            return
        
        # Error if this string uses double quotes, by checking the source code
        quote_info = self._get_string_quote_info(node)
        if quote_info is not None:
            (prefix, quote_char, is_triple) = quote_info
            if quote_char == '"' and not is_triple:
                self.add_message('no-double-quoted-string', node=node)
                
                # Track fix info if requested
                if self._fixes is not None:
                    fix = StringQuoteFix(
                        lineno=node.lineno,
                        col_offset=node.col_offset,
                        end_lineno=node.end_lineno or node.lineno,
                        end_col_offset=node.end_col_offset or node.col_offset,
                        prefix=prefix,
                        old_quote='"',
                        new_quote="'",
                        is_fstring=False
                    )
                    self._fixes.append(fix)
    
    def _is_inside_fstring(self, node: nodes.NodeNG) -> bool:
        """Check if the specified node is nested inside an f-string (JoinedStr)."""
        current = node.parent
        while current is not None:
            if isinstance(current, nodes.JoinedStr):
                return True
            current = current.parent
        return False
    
    # === Visit JoinedStr (f-strings) ===
    
    def visit_joinedstr(self, node: nodes.JoinedStr) -> None:
        """Check for double-quoted f-string literals."""
        # Exception: A single-quoted f-string may contain a double-quoted f-string
        if self._is_inside_fstring(node):
            return
        
        # Exception: An f-string containing a single quote in its value may use double quotes
        if self._fstring_contains_single_quote(node):
            return
        
        # Error if this f-string uses double quotes, by checking the source code
        quote_info = self._get_fstring_quote_info(node)
        if quote_info is not None:
            (prefix, quote_char, is_triple) = quote_info
            if quote_char == '"' and not is_triple:
                self.add_message('no-double-quoted-string', node=node)
                
                # Track fix info if requested
                if self._fixes is not None:
                    fix = StringQuoteFix(
                        lineno=node.lineno,
                        col_offset=node.col_offset,
                        end_lineno=node.end_lineno or node.lineno,
                        end_col_offset=node.end_col_offset or node.col_offset,
                        prefix=prefix,
                        old_quote='"',
                        new_quote="'",
                        is_fstring=True
                    )
                    self._fixes.append(fix)
    
    def _fstring_contains_single_quote(self, node: nodes.JoinedStr) -> bool:
        """Check if any string part of the f-string contains a single quote."""
        for value in node.values:
            if isinstance(value, nodes.Const) and isinstance(value.value, str):
                if "'" in value.value:
                    return True
        return False
    
    def _get_fstring_quote_info(self, node: nodes.JoinedStr) -> Optional[Tuple[str, str, bool]]:
        """
        Get quote info for an f-string.
        Returns (prefix, quote_char, is_triple) or None if can't determine.
        """
        try:
            lines = _read_source_lines(node)
            line = lines[node.lineno - 1]
            pos = node.col_offset
            
            if pos >= len(line):
                return None
            
            # f-strings start with 'f' or 'F' prefix
            if (char := line[pos]) not in 'fF':
                return None
            prefix = char
            pos += 1
            
            # Handle rf or fr prefixes
            while pos < len(line) and line[pos] in 'rR':
                prefix += line[pos]
                pos += 1
            if pos >= len(line):
                return None
            
            # Triple-quoted f-string
            remaining = line[pos:]
            if remaining.startswith('"""'):
                return (prefix, '"', True)
            if remaining.startswith("'''"):
                return (prefix, "'", True)
            
            # Regular f-string
            if (char := line[pos]) in ('"', "'"):
                return (prefix, char, False)
            
            return None
        except Exception:
            return None
    
    def _get_string_quote_info(self, node: nodes.Const) -> Optional[Tuple[str, str, bool]]:
        """
        Get quote info for a string constant.
        Returns (prefix, quote_char, is_triple) or None if can't determine.
        """
        try:
            lines = _read_source_lines(node)
            line = lines[node.lineno - 1]
            pos = node.col_offset
            if pos >= len(line):
                return None
            
            # Check for prefixed strings like r", b", etc.
            prefix = ''
            while pos < len(line) and (char := line[pos]) in 'fFrRbBuU':
                prefix += char
                pos += 1
            if pos >= len(line):
                return None
            
            # Triple-quoted string
            remaining = line[pos:]
            if remaining.startswith('"""'):
                return (prefix, '"', True)
            if remaining.startswith("'''"):
                return (prefix, "'", True)
            
            # Regular string
            if (char := line[pos]) in ('"', "'"):
                return (prefix, char, False)
            
            return None
        except Exception:
            return None


def _read_source_lines(node: nodes.NodeNG) -> tuple[str, ...]:
    """
    Read source file and return lines as a tuple.
    
    Uses the authoritative source text from the astroid module, which may be
    from memory (if editing in VS Code) or from disk.
    """
    module = node.root()
    
    # Check for cached lines on the module object
    if hasattr(module, '_crystal_source_lines'):
        return module._crystal_source_lines
    
    # Read from stream
    stream = module.stream()
    if stream is None:
        return ()
    try:
        content_bytes = stream.read()
    finally:
        stream.close()
        
    encoding = module.file_encoding or 'utf-8'
    try:
        content = content_bytes.decode(encoding)
    except LookupError:
        # Fallback if encoding is invalid
        content = content_bytes.decode('utf-8', errors='replace')
        
    lines = tuple(content.splitlines(keepends=True))
    
    # Cache lines on the module object
    module._crystal_source_lines = lines
    return lines


def register(linter):
    """Register the checker with pylint."""
    linter.register_checker(CrystalLintRules(linter))


# === String Quote Fixes ===

class StringQuoteFix:
    """Information needed to fix a double-quoted string."""
    
    def __init__(
        self,
        lineno: int,
        col_offset: int,
        end_lineno: int,
        end_col_offset: int,
        prefix: str,
        old_quote: str,
        new_quote: str,
        is_fstring: bool
    ):
        self.lineno = lineno
        self.col_offset = col_offset
        self.end_lineno = end_lineno
        self.end_col_offset = end_col_offset
        self.prefix = prefix
        self.old_quote = old_quote
        self.new_quote = new_quote
        self.is_fstring = is_fstring


def apply_string_quote_fixes(
    source_lines: List[str],
    fixes: List[StringQuoteFix]
) -> List[str]:
    """
    Apply string quote fixes to source lines.
    
    Arguments:
    * source_lines -- List of source code lines (with line endings)
    * fixes -- List of StringQuoteFix objects to apply
    
    Returns:
    * Modified list of source lines
    """
    # Sort fixes in reverse order to preserve positions
    fixes_sorted = sorted(
        fixes,
        key=lambda f: (f.lineno, f.col_offset),
        reverse=True
    )
    
    lines = source_lines[:]
    for fix in fixes_sorted:
        if fix.lineno == fix.end_lineno:
            # Single line replacement
            line = lines[fix.lineno - 1]
            
            # Extract the original string from source
            original = line[fix.col_offset:fix.end_col_offset]
            
            if fix.is_fstring:
                # For f-strings, replace the quotes
                replacement = _fix_fstring_quotes(original, fix)
            else:
                # For regular strings, replace the quotes
                replacement = _fix_string_quotes(original, fix)
            
            lines[fix.lineno - 1] = (
                line[:fix.col_offset] + replacement + line[fix.end_col_offset:]
            )
        # Multi-line strings are rare and complex, skip them for now
    
    return lines


def _fix_string_quotes(original: str, fix: StringQuoteFix) -> str:
    """
    Fix quotes in a regular string.
    
    Arguments:
    * original -- Original string from source (e.g., 'r\"test\"')
    * fix -- Fix information
    
    Returns:
    * Fixed string (e.g., 'r\\'test\\'')
    """
    # Find the opening quote (after optional prefix)
    pos = 0
    while pos < len(original) and original[pos] in 'fFrRbBuU':
        pos += 1
    if pos >= len(original) or original[pos] != fix.old_quote:
        # Couldn't find opening quote
        return original
    
    # Find the closing quote
    end_pos = len(original) - 1
    while end_pos > pos and original[end_pos] not in ('"', "'"):
        end_pos -= 1
    if end_pos <= pos or original[end_pos] != fix.old_quote:
        # Couldn't find closing quote
        return original
    
    # Replace the quote characters only.
    # The content between quotes stays the same.
    return fix.prefix + fix.new_quote + original[pos + 1:end_pos] + fix.new_quote


def _fix_fstring_quotes(original: str, fix: StringQuoteFix) -> str:
    """
    Fix quotes in an f-string.
    
    Arguments:
    * original -- Original f-string from source (e.g., 'f\"test\"')
    * fix -- Fix information
    
    Returns:
    * Fixed f-string (e.g., 'f\\'test\\'')
    """
    # Find the opening quote (after optional prefix)
    pos = 0
    while pos < len(original) and original[pos] in 'fFrR':
        pos += 1
    if pos >= len(original) or original[pos] != fix.old_quote:
        # Couldn't find opening quote
        return original
    
    # Find the closing quote
    end_pos = len(original) - 1
    while end_pos > pos and original[end_pos] not in ('"', "'"):
        end_pos -= 1
    if end_pos <= pos or original[end_pos] != fix.old_quote:
        # Couldn't find closing quote
        return original
    
    # Replace the quote characters only.
    # The content between quotes stays the same (including nested strings).
    return fix.prefix + fix.new_quote + original[pos + 1:end_pos] + fix.new_quote


def _patch_astroid() -> None:
    """
    Patches astroid 4.0.3 to work with PATH entries that end with os.path.sep.
    
    Backports the fix: https://github.com/pylint-dev/astroid/pull/2928
    """
    if sys.platform != 'win32':
        # Patch only useful on Windows
        return
    try:
        import astroid.modutils
    except ImportError:
        pass
    else:
        path = '\\\\Mac\\Code\\tests\\test_resources.py'
        base = '\\\\mac\\code\\'
        if not astroid.modutils._is_subpath(path, base):
            def _is_subpath2(path: str, base: str) -> bool:
                path = os.path.normcase(os.path.normpath(path))
                base = os.path.normcase(os.path.normpath(base))
                if not path.startswith(base):
                    return False
                return (
                    (len(path) == len(base)) or 
                    (path[len(base)] == os.path.sep) or
                    # Fix
                    (base.endswith(os.path.sep) and path[len(base) - 1] == os.path.sep)
                )
            astroid.modutils._is_subpath = _is_subpath2
        assert astroid.modutils._is_subpath(path, base)


# Patch astroid at import time
_patch_astroid()
