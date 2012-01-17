dist-mac:
	rm -rf build dist
	python setup.py py2app
	hdiutil create -srcfolder dist -volname "Crystal Web Archiver" -format UDZO dist/crystal-1.0.dmg
