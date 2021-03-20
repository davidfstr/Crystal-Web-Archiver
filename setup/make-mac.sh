#!/bin/sh

VERSION=`python -c 'import sys; sys.path.append("../src"); import crystal; print(crystal.__version__)'`

rm -rf build dist dist-mac
poetry run python setup.py py2app
mkdir dist-mac
hdiutil create -srcfolder dist -volname "Crystal Web Archiver" -format UDZO dist-mac/crystal-mac-$VERSION.dmg
