"""
Lightweight minification algorithms for content on HTML pages.
"""

import re


# NOTE: Only tested with input: _FOOTER_BANNER_UNMINIFIED_JS
def minify_js(js_code: str) -> str:
    # Remove // comments
    # NOTE: Assumes that "//" does not appear inside string literals
    js_code = re.sub(r'//.*', '', js_code)
    
    # Collapse all runs of 2+ whitespace (including newlines) into a single space
    # NOTE: Assumes that runs of 2+ whitespace does not appear inside string literals
    js_code = re.sub(r'\s{2,}', ' ', js_code)
    
    # Strip leading/trailing space overall
    js_code = js_code.strip()
    
    # Identify variable names and replace with short names
    # NOTE: Assumes that variable names do not appear as words inside string literals
    if True:
        # Find variable declarations: const, let, var
        # Pattern matches: const name = ...; or const name;
        short_name_for_long_name = {}
        variable_counter = 1
        VAR_PATTERN = r'\b(?:const|let|var)\s+([a-zA-Z_$][a-zA-Z0-9_$]*)\s*(?:[=;])'
        for long_name in re.findall(VAR_PATTERN, js_code):
            if long_name in short_name_for_long_name:
                continue
            short_name_for_long_name[long_name] = f'${variable_counter}'  # ex: '$1'
            variable_counter += 1
        
        # Replace each variable name with: $1, $2, $3, ...
        for (long_name, short_name) in short_name_for_long_name.items():
            js_code = re.sub(r'\b' + re.escape(long_name) + r'\b', short_name, js_code)
        
        # Look for string literals that may have gotten variable-substituted improperly
        for literal in re.findall(r'"([^"]*)"', js_code) + re.findall(r"'([^']*)'", js_code):
            if '$' in literal:
                # Try to unminify the literal
                unmin_literal = literal
                for (long_name, short_name) in short_name_for_long_name.items():
                    unmin_literal = unmin_literal.replace(short_name, long_name)
                
                raise ValueError(
                    f'It looks like this string literal may contain a '
                    f'variable name that was substituted: {unmin_literal!r} -> {literal!r}')
    
    return js_code


# NOTE: Only tested with input: appicon--fallback.svg
def minify_svg(svg_bytes: bytes) -> bytes:
    # Delete comments
    svg_bytes = re.sub(rb'<!--.*?-->', b'', svg_bytes)
    
    # Delete whitespace between tags
    svg_bytes = re.sub(rb'>\s+<', b'><', svg_bytes)
    
    return svg_bytes
