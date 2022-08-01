import os
from typing import Tuple

# Read current win-installer.iss
with open('win-installer.iss', 'r', newline='\r\n') as f:
    old_lines = list(f)
for line in old_lines:
    if not line.endswith('\r\n'):
        raise AssertionError(f'win-installer.iss: Expected line to end with CRLF: {line!r}')

# Locate existing [Files] stanza
source_line_range: Tuple[int, int]
for (i, line) in enumerate(old_lines):
    if line.strip() == '[Files]':
        for (j, line) in enumerate(old_lines[i+1:], i+1):
            if not line.startswith('Source:'):
                break
        else:
            j = len(old_lines)
        source_line_range = (i+1, j)
        break
else:
    raise ValueError('win-installer.iss: [Files] stanza not found')

# Generate new [Files] stanza content
if True:
    new_source_lines = []
    
    INCLUDE_EXTENSIONS = ['.pyd', '.dll', '.exe', '.pem']
    for filename in sorted(os.listdir('dist')):
        if any([filename.endswith(ext) for ext in INCLUDE_EXTENSIONS]):
            new_source_lines.append(f'Source: "dist\\{filename}"; DestDir: "{{app}}"\r\n')
    
    for (parent_dirpath, dirnames, filenames) in os.walk(os.path.join('dist', 'lib', 'crystal')):
        for filename in sorted(filenames):  # traverse in sorted order
            source_filepath = os.path.relpath(os.path.join(parent_dirpath, filename), start='.')
            source_filepath_nt = source_filepath.replace(os.sep, '\\')
            dest_dirpath = os.path.dirname(source_filepath)
            dest_dirpath_nt = dest_dirpath.replace(os.sep, '\\')
            dest_app_dirpath_nt = '{app}' + dest_dirpath_nt[len('dist'):]
            new_source_lines.append(f'Source: "{source_filepath_nt}"; DestDir: "{dest_app_dirpath_nt}"\r\n')
        dirnames[:] = sorted(dirnames)  # traverse in sorted order
    
    if len(new_source_lines) == 0:
        raise ValueError('No valid source files found')

# Generate new win-installer.iss content
new_lines = list(old_lines)  # shallow copy
new_lines[source_line_range[0]:source_line_range[1]] = new_source_lines

# Write new win-installer.iss
with open('win-installer.iss', 'w', newline='') as f:
    for line in new_lines:
        assert line.endswith('\r\n')
        f.write(line)
