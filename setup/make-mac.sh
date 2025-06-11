#!/bin/sh

VERSION=`python -c 'import sys; sys.path.append("../src"); import crystal; print(crystal.__version__)'`

rm -rf build dist dist-mac

# Build .app
if [ "$1" != "--app-only" ]; then
    GRAPH_OPT=""
else
    # --graph: Generates a GraphViz .dot file in the build directory that shows
    #          the calculated module dependency graph
    GRAPH_OPT="--graph"
fi
poetry run python setup.py py2app $GRAPH_OPT
if [ $? -ne 0 ]; then
    echo "ERROR: py2app build failed. Aborting."
    exit 1
fi

# Slim .app
zip dist/Crystal\ Web\ Archiver.app/Contents/Resources/lib/python3*.zip \
    -d "wx/locale/*"

# Build .dmg
mkdir dist-mac
if [ "$1" != "--app-only" ]; then
    echo 'Building disk image... (skip with --app-only option)'
    # -format UDBZ: Use bzip2 compression, which produces smaller images
    #               than zlib compression (UDZO), even with zlib-level=9
    hdiutil create -srcfolder dist -volname "Crystal Web Archiver" -format UDBZ dist-mac/crystal-mac-$VERSION.dmg
fi
