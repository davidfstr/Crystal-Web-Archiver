#!/bin/sh

VERSION=`python3 -c 'import crystal; print(crystal.__version__)'`

rm -rf build dist dist-mac
python setup.py py2app
mkdir dist-mac
hdiutil create -srcfolder dist -volname "Crystal Web Archiver" -format UDZO dist-mac/crystal-mac-$VERSION.dmg
