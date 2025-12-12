"""
Pylint plugin to ban specific API patterns in Crystal.
"""

import astroid
from astroid import nodes
from functools import lru_cache
from pylint.checkers import BaseChecker


class CrystalBannedApiChecker(BaseChecker):
    """Checker to detect usage of banned API patterns."""
    
    name = 'crystal-banned-api'
    
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
            # Get the source file
            module = node.root()
            lines = _read_source_lines(module.file)
            
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
        if self._is_double_quoted_string(node):
            self.add_message('no-double-quoted-string', node=node)
    
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
        if self._is_double_quoted_fstring(node):
            self.add_message('no-double-quoted-string', node=node)
    
    def _fstring_contains_single_quote(self, node: nodes.JoinedStr) -> bool:
        """Check if any string part of the f-string contains a single quote."""
        for value in node.values:
            if isinstance(value, nodes.Const) and isinstance(value.value, str):
                if "'" in value.value:
                    return True
        return False
    
    def _is_double_quoted_fstring(self, node: nodes.JoinedStr) -> bool:
        """Check if an f-string uses double quotes by examining source code."""
        try:
            module = node.root()
            lines = _read_source_lines(module.file)
            
            line = lines[node.lineno - 1]
            
            if node.col_offset < len(line):
                char = line[node.col_offset]
                
                # f-strings start with 'f' or 'F' prefix
                if char in 'fF':
                    next_pos = node.col_offset + 1
                    # Handle rf or fr prefixes
                    if next_pos < len(line) and line[next_pos] in 'rR':
                        next_pos += 1
                    if next_pos < len(line):
                        # Skip triple-quoted f-strings
                        if line[next_pos:].startswith('"""') or line[next_pos:].startswith("'''"):
                            return False
                        return line[next_pos] == '"'
        except Exception:
            pass
        return False
    
    def _is_double_quoted_string(self, node: nodes.Const) -> bool:
        """Check if a string constant uses double quotes by examining source code."""
        try:
            # Get the source file
            module = node.root()
            lines = _read_source_lines(module.file)
            
            # Get the line (0-indexed)
            line = lines[node.lineno - 1]
            
            # Get the character at col_offset
            if node.col_offset < len(line):
                char = line[node.col_offset]
                
                # Skip triple-quoted strings
                remaining = line[node.col_offset:]
                if remaining.startswith('"""') or remaining.startswith("'''"):
                    return False
                
                # Check for prefixed strings like f", r", b", etc.
                # The prefix comes before the quote character
                if char in 'fFrRbBuU':
                    # Could be a prefix; check the next character(s)
                    next_pos = node.col_offset + 1
                    # Handle multi-character prefixes like fr, rf, br, rb
                    if next_pos < len(line) and line[next_pos] in 'fFrRbBuU':
                        next_pos += 1
                    if next_pos < len(line):
                        # Skip triple-quoted strings
                        if line[next_pos:].startswith('"""') or line[next_pos:].startswith("'''"):
                            return False
                        return line[next_pos] == '"'
                
                # Regular string. Check if it starts with double quote.
                return char == '"'
        except Exception:
            pass
        return False  # Assume single-quoted if we can't check (fail safe)


@lru_cache(maxsize=128)
def _read_source_lines(filepath: str) -> tuple[str, ...]:
    """
    Read source file and return lines as a tuple.
    
    Cached to avoid re-reading the same file multiple times during analysis.
    Returns tuple instead of list so result is hashable for caching.
    """
    with open(filepath, 'r') as f:
        return tuple(f.readlines())


def register(linter):
    """Register the checker with pylint."""
    linter.register_checker(CrystalBannedApiChecker(linter))
