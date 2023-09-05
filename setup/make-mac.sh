#!/bin/sh

VERSION=`python -c 'import sys; sys.path.append("../src"); import crystal; print(crystal.__version__)'`

rm -rf build dist dist-mac
# --graph: Generates a GraphViz .dot file in the build directory that shows
#          the calculated module dependency graph
poetry run python setup.py py2app --graph
mkdir dist-mac
if [ "$1" != "--app-only" ]; then
    echo 'Building disk image... (skip with --app-only option)'
    # -format UDBZ: Use bzip2 compression, which produces smaller images
    #               than zlib compression (UDZO), even with zlib-level=9
    hdiutil create -srcfolder dist -volname "Crystal Web Archiver" -format UDBZ dist-mac/crystal-mac-$VERSION.dmg
fi
