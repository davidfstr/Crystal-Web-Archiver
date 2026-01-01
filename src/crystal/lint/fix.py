#!/usr/bin/env python3
"""
Auto-fixer for the [no-double-quoted-string] (C9013) PyLint rule,
and potentially other rules in the future.

Usage:
    python -m crystal.lint.fix <file_path>
    python -m crystal.lint.fix --check <file_path>  # Check only, no fixes
"""

import argparse
import astroid
from astroid import nodes
from crystal.lint.rules import (
    CrystalLintRules,
    apply_string_quote_fixes
)
import sys
from pathlib import Path
from typing import Tuple


def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description='Fix double-quoted string literals to use single quotes'
    )
    parser.add_argument('file', type=Path, help='File to fix')
    parser.add_argument(
        '--check',
        action='store_true',
        help='Check only, do not modify files'
    )
    
    args = parser.parse_args()
    
    if not args.file.exists():
        print(f'Error: File not found: {args.file}', file=sys.stderr)
        return 1
    
    (has_issues, num_fixes) = fix_file(args.file, check_only=args.check)
    
    if args.check:
        return 1 if has_issues else 0
    else:
        return 0


def fix_file(file_path: Path, check_only: bool = False) -> Tuple[bool, int]:
    """
    Fix double-quoted strings in a file.
    
    Arguments:
    * file_path -- Path to the file to fix
    * check_only -- If True, only check for issues without fixing
    
    Returns:
    * (has_issues, num_fixes): Whether the file has issues and number of fixes made
    """
    # Read source
    with open(file_path, 'r', encoding='utf-8') as f:
        source = f.read()
    
    # Parse AST
    try:
        tree = astroid.parse(source, module_name=str(file_path))
    except SyntaxError as e:
        print(f'Syntax error in {file_path}: {e}', file=sys.stderr)
        return (False, 0)
    
    # Create a minimal mock linter for the checker
    class MockLinter:
        def add_message(self, *args, **kwargs):
            pass  # Ignore message emissions
        
        def _register_options_provider(self, provider):
            pass  # Ignore option registration
    
    # Create a checker with fix tracking enabled
    checker = CrystalLintRules(linter=MockLinter())  # type: ignore[arg-type]
    checker._fixes = []
    
    # Set up source lines on the module for the checker to access
    source_lines = source.splitlines(keepends=True)
    tree._crystal_source_lines = tuple(source_lines)
    
    # Walk the AST with the checker
    for node in tree.nodes_of_class((nodes.Const, nodes.JoinedStr)):
        if isinstance(node, nodes.Const):
            checker.visit_const(node)
        elif isinstance(node, nodes.JoinedStr):
            checker.visit_joinedstr(node)
    fixes = checker._fixes
    if not fixes:
        return (False, 0)
    
    if check_only:
        # Print fixes
        print(f'{file_path}: {len(fixes)} issue(s) found')
        for fix in fixes:
            print(f'  Line {fix.lineno}, Col {fix.col_offset}: Double-quoted string should use single quotes')
        return (True, len(fixes))
    else:
        # Apply fixes
        fixed_lines = apply_string_quote_fixes(source_lines, fixes)
        with open(file_path, 'w', encoding='utf-8') as f:
            f.writelines(fixed_lines)
        
        print(f'{file_path}: Fixed {len(fixes)} issue(s)')
        return (True, len(fixes))


if __name__ == '__main__':
    sys.exit(main())
