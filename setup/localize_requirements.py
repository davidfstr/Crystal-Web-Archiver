"""
Filters requirements.txt input based on environment markers,
outputting only requirements that match the current build environment.
"""

from packaging.markers import Marker
import sys

for line in sys.stdin:
    line = line.strip()
    if ';' in line:
        (req, marker) = line.split(';', 1)
        if Marker(marker.strip()).evaluate():
            print(req.strip())
    elif line and not line.startswith('#'):
        print(line)
