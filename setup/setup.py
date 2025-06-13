r"""
py2app/py2exe build script for Crystal Web Archiver.

Usage (All Platforms):
    python setup.py

Usage (Mac OS X):
    python setup.py py2app
Usage (Windows):
    python setup.py py2exe

Windows users may need to copy 'MSVCP90.dll' to C:\WINDOWS\system32 if the
following error is encountered:
    error: MSVCP90.dll: No such file or directory
See the tutorial for py2exe for more information about this DLL.
"""

import os
from setuptools import setup
import sys

# Import variables from setup_settings.py
env = {}  # type: dict[str, str]
with open('./setup_settings.py', encoding='utf-8') as f:
    exec(f.read(), env)

if sys.platform == 'darwin':
    # If run without args, build application
    if len(sys.argv) == 1:
        sys.argv.append("py2app")
        
    # Ensure 'py2app' package installed
    try:
        import py2app
    except ImportError:
        exit(
            'This script requires py2app to be installed. ' + 
            'Download it from http://undefined.org/python/py2app.html')
    
    PLIST = {
        # 1. Define app name used by the application menu
        # 2. Define file name of the created .app
        'CFBundleName': env['APP_NAME'],
        'CFBundleDocumentTypes': [
            # Associate application with .crystalproj files
            {
                'CFBundleTypeExtensions': ['crystalproj'],
                'CFBundleTypeMIMETypes': ['application/vnd.crystal.project'],
                'CFBundleTypeIconFile': 'DocIconMac.icns',
                'CFBundleTypeName': 'Crystal Project',
                'CFBundleTypeRole': 'Editor',
                'LSTypeIsPackage': True,
            },
            # Associate application with .crystalopen files
            {
                'CFBundleTypeExtensions': ['crystalopen'],
                'CFBundleTypeMIMETypes': ['application/vnd.crystal.opener'],
                'CFBundleTypeIconFile': 'OpenerIcon.icns',
                'CFBundleTypeName': 'Crystal Opener',
                'CFBundleTypeRole': 'Editor',
            },
        ],
        'CFBundleIdentifier': 'net.dafoster.crystal',
        'CFBundleShortVersionString': env['VERSION_STRING'],
        'CFBundleSignature': 'CrWA',  # Crystal Web Archiver
        'CFBundleVersion': env['VERSION_STRING'],
        'NSHumanReadableCopyright': env['COPYRIGHT_STRING'],
    }
    
    # Exclude PIL unless $CRYSTAL_SUPPORT_SCREENSHOTS is True
    extra_excludes = (
        [] if os.environ.get('CRYSTAL_SUPPORT_SCREENSHOTS', 'False') == 'True'
        else ['PIL']
    )

    extra_setup_options = dict(
        setup_requires=['py2app'],
        app=['../src/crystal/__main__.py'],
        data_files=[
            'media/DocIconMac.icns',
            'media/OpenerIcon.icns',
        ],
        options={'py2app': {
            # Cannot use argv_emulation=True in latest version of py2app
            # because of: https://github.com/ronaldoussoren/py2app/issues/340
            'argv_emulation': False,
            'iconfile': 'media/AppIconMac.icns',
            'plist': PLIST,
            'includes': [
                # xattr depends on cffi but py2app doesn't detect that automatically
                '_cffi_backend', 'cffi',
            ],
            'excludes': [
                'numpy',
                'test',  # CPython test data
            ] + extra_excludes
        }},
    )
elif sys.platform == 'win32':
    # If run without args, build executables in quiet mode
    if len(sys.argv) == 1:
        sys.argv.append("py2app")
        sys.argv.append("-q")
    
    # Ensure 'py2exe' package installed
    try:
        import py2exe
    except ImportError:
        exit(
            'This script requires py2exe to be installed. ' + 
            'Download it from http://www.py2exe.org/')
    
    # py2exe doesn't look for modules in the directory of the main
    # source file by default, so we must add it to the system path explicitly.
    sys.path.append(r'..\src')
    
    extra_setup_options = dict(
        setup_requires=['py2exe'],
        windows=[{
            'script': r'..\src\crystal\__main__.py',
            'icon_resources': [
                (0, r'media\AppIconWin.ico'),
                (1, r'media\OpenerIcon.ico'),
            ],
            # Executable name
            'dest_base': env['APP_NAME'],
        }],
        data_files=[
            # crystal.resources
            (r'lib\crystal\resources', [
                r'..\src\crystal\resources' + '\\' + filename
                for filename in os.listdir(r'..\src\crystal\resources')
                if filename not in ['__pycache__'] and not filename.startswith('.')
            ]),
        ],
        # Combine 'library.zip' into the generated exe
        zipfile=None,
        options={'py2exe': {
            'includes': [
                # lxml
                # https://stackoverflow.com/questions/5308760/py2exe-lxml-woes#5309733
                'lxml.etree', 'lxml._elementpath', 'gzip',
            ],
            'ignores': [
                # Mac junk
                'Carbon', 'Carbon.Files',
                # Windows junk
                'win32api', 'win32con', 'win32pipe',
                # Other junk
                '_scproxy', 'chardet', 'cjkcodecs.aliases', 'iconv_codec',
            ],
            # Would love to use mode '1' to put everything into a single exe,
            # but it breaks wxPython's default tree node icons. Don't know why.
            'bundle_files': 3,
            # Enable compression.
            # Most effective when all files bundled in a single exe (18 MB -> 8 MB).
            'compressed': True,
        }},
    )
else:
    exit('This build script can only run on Mac OS X and Windows.')

setup(
    name=env['APP_NAME'],
    **extra_setup_options
)
