#!/bin/sh

rm -rf build dist dist-mac
python setup.py py2app
mkdir dist-mac
hdiutil create -srcfolder dist -volname "Crystal Web Archiver" -format UDZO dist-mac/crystal-mac-1.0.dmg
