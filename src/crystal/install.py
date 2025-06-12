# This module provides routines for installing the Crystal application
# into the Linux desktop environment (e.g., creating .desktop files,
# MIME types, and icons). This module is invoked when the
# --install-to-desktop command-line argument is provided to Crystal.
# 
# This module is only intended to be used on Linux systems and should not be
# imported or executed on non-Linux platforms.

from collections.abc import Iterator
from contextlib import contextmanager
from crystal.util.ellipsis import Ellipsis, EllipsisType
from functools import cache
import os
import os.path
import shutil
import subprocess
import sys
from typing import BinaryIO, Dict, Literal, Optional, Tuple, Union
import xml.etree.ElementTree as ET


def install_to_linux_desktop_environment() -> None:
    """
    Install the Crystal application to the desktop environment, in Linux.
    """
    from crystal import resources
    from crystal.util import gio
    from crystal.util.xos import is_linux
    import glob
    
    if not is_linux():
        raise ValueError()
    
    # Ensure not running as root (unless is actually the root user)
    running_as_root_user = (os.geteuid() == 0)  # type: ignore[attr-defined]  # available in Linux
    is_root_user = (os.getuid() == 0)  # type: ignore[attr-defined]  # available in Linux
    if running_as_root_user and not is_root_user:
        print('*** --install-to-desktop should not be run as root or with sudo')
        sys.exit(1)
    
    # Install .desktop file to ~/.local/share/applications
    # 
    # NOTE: Only .desktop files opened from this directory will show their
    #       icon in the dock correctly.
    if True:
        # Format .desktop file in memory
        with resources.open_text('crystal.desktop', encoding='utf-8') as f:
            desktop_file_content = f.read()
        if os.path.basename(sys.executable) in ['python', 'python3']:
            crystal_executable = f'{sys.executable} -m crystal'
        else:
            crystal_executable = sys.executable
        desktop_file_content = desktop_file_content.replace(
            '__CRYSTAL_PATH__', crystal_executable)
        desktop_file_content = desktop_file_content.replace(
            '__APPICON_PATH__', resources.get_filepath('appicon.png'))
        
        apps_dirpath = os.path.expanduser('~/.local/share/applications')
        os.makedirs(apps_dirpath, exist_ok=True)
        with open(f'{apps_dirpath}/crystal.desktop', 'w') as f:
            f.write(desktop_file_content)
        
        subprocess.run([
            'update-desktop-database',
            os.path.expanduser('~/.local/share/applications')
        ], check=True)
    
    # Install symlink to .desktop file on ~/Desktop, if possible
    desktop_dirpath = os.path.expanduser('~/Desktop')
    if os.path.isdir(desktop_dirpath) and not os.path.exists(f'{desktop_dirpath}/crystal.desktop'):
        subprocess.run([
            'ln', '-s',
            f'{apps_dirpath}/crystal.desktop',
            f'{desktop_dirpath}/crystal.desktop',
        ], check=True)
        
        # Mark .desktop symlink on desktop as "Allow Launching" on Ubuntu 22+
        # https://askubuntu.com/questions/1218954/desktop-files-allow-launching-set-this-via-cli
        try:
            gio.set(f'{desktop_dirpath}/crystal.desktop', 'metadata::trusted', 'true')
        except gio.GioNotAvailable:
            pass
        except gio.UnrecognizedGioAttributeError:
            # For example Kubuntu 22 does not recognize this attribute
            pass
        else:
            subprocess.run([
                'chmod', 'a+x',
                f'{desktop_dirpath}/crystal.desktop',
            ], check=True)
    
    # Install .crystalopen MIME type definition
    mime_dirpath = os.path.expanduser('~/.local/share/mime')
    os.makedirs(f'{mime_dirpath}/packages', exist_ok=True)
    with open(f'{mime_dirpath}/packages/application-vnd.crystal.opener.xml', 'w') as dst_file:
        with resources.open_text('application-vnd.crystal.opener.xml', encoding='utf-8') as src_file:
            shutil.copyfileobj(src_file, dst_file)
    subprocess.run(['update-mime-database', mime_dirpath], check=True)
    
    # Install .crystalopen file icon
    # 
    # NOTE: It is necessary to install both PNG and SVG versions,
    #       because some desktop environments (like KDE) only recognize one type.
    # NOTE: It is necessary to install prescaled icon versions,
    #       because some apps (like GNOME/KDE's Open Dialog) cannot scale icons themselves.
    if True:
        # Locate places where MIME icons are installed, in global theme directories
        dimension_for_mime_icon_dirpath = {}  # type: Dict[str, Union[Tuple[int, int], EllipsisType]]
        with _cwd_set_to('/usr/share/icons'):
            for mime_icon_filepath in glob.iglob('**/text-plain.*', recursive=True):
                mime_icon_dirpath = os.path.dirname(mime_icon_filepath)
                
                old_dimension = dimension_for_mime_icon_dirpath.get(mime_icon_dirpath)
                if old_dimension is not Ellipsis:
                    with open(mime_icon_filepath, 'rb') as f:
                        if mime_icon_filepath.endswith('.png'):
                            new_dimension = get_png_dimensions(f) or Ellipsis
                        elif mime_icon_filepath.endswith('.svg'):
                            new_dimension = get_svg_dimensions(f) or Ellipsis
                        else:
                            # Ignore futuristic image types
                            continue
                    if old_dimension is not None and new_dimension != old_dimension:
                        new_dimension = Ellipsis  # ambiguous
                    if new_dimension != old_dimension:
                        dimension_for_mime_icon_dirpath[mime_icon_dirpath] = new_dimension
        
        # Install new MIME icons, in local theme directories
        if len(dimension_for_mime_icon_dirpath) == 0:
            print('WARNING: Unable to locate places to install MIME icons')
        else:
            local_icons_dirpath = os.path.expanduser('~/.local/share/icons')
            for (mime_icon_dirpath, dimension) in dimension_for_mime_icon_dirpath.items():
                mime_icon_abs_dirpath = os.path.join(local_icons_dirpath, mime_icon_dirpath)
                os.makedirs(mime_icon_abs_dirpath, exist_ok=True)
                
                # Install PNG icon for MIME type
                with open(f'{mime_icon_abs_dirpath}/application-vnd.crystal.opener.png', 'wb') as dst_file:
                    dst_file.write(_get_or_load_best_icon('application-vnd.crystal.opener', 'png', dimension))
                
                # Install SVG icon for MIME type,
                # because at least KDE on Kubuntu 22 seems to ignore PNG icons
                with open(f'{mime_icon_abs_dirpath}/application-vnd.crystal.opener.svg', 'wb') as dst_file:
                    dst_file.write(_get_or_load_best_icon('application-vnd.crystal.opener', 'svg', dimension))
            
            # NOTE: At least on Ubuntu 22 it seems the icon caches don't need
            #       to be explicitly updated to pick up the new icon type
            #       immediately, which is good because it may not be possible
            #       to sudo.
            #subprocess.run(['sudo', 'update-icon-caches', *glob.glob('/usr/share/icons/*')], check=True)
    
    # Install .crystalproj folder icon
    # 
    # NOTE: It is necessary to install both PNG and SVG versions,
    #       because some desktop environments (like KDE) only recognize one type.
    # NOTE: It is necessary to install prescaled icon versions,
    #       because some apps (like GNOME/KDE's Open Dialog) cannot scale icons themselves.
    if True:
        # Determine icon names for regular folder, which actually resolve to an icon
        icon_names: list[str]
        try:
            regular_folder_dirpath = os.path.dirname(__file__)
            p = subprocess.run(
                ['gio', 'info', '--attributes', 'standard::icon', regular_folder_dirpath],
                check=True,
                capture_output=True,
            )
        except FileNotFoundError:
            # GIO not available
            icon_names = []
        else:
            gio_lines = p.stdout.decode('utf-8').split('\n')
            for line in gio_lines:
                line = line.strip()  # reinterpret
                if line.startswith('standard::icon:'):
                    line = line[len('standard::icon:'):]  # reinterpret
                    icon_names = [x.strip() for x in line.strip().split(',')]
                    break
            else:
                icon_names = []
            
        # Locate places where folder icons are installed, in global theme directories
        dimension_for_folder_icon_dirpath = {}  # type: Dict[str, Union[Tuple[int, int], EllipsisType]]
        if len(icon_names) != 0:
            with _cwd_set_to('/usr/share/icons'):
                for (folder_icon_dirpath, dirnames, filenames) in os.walk('.'):
                    for filename in filenames:
                        (filename_without_ext, _) = os.path.splitext(filename)
                        if filename_without_ext not in icon_names:
                            continue
                        
                        old_dimension = dimension_for_folder_icon_dirpath.get(folder_icon_dirpath)
                        if old_dimension is not Ellipsis:
                            with open(os.path.join(folder_icon_dirpath, filename), 'rb') as f:
                                if filename.endswith('.png'):
                                    new_dimension = get_png_dimensions(f) or Ellipsis
                                elif filename.endswith('.svg'):
                                    new_dimension = get_svg_dimensions(f) or Ellipsis
                                else:
                                    # Ignore futuristic image types
                                    continue
                            if old_dimension is not None and new_dimension != old_dimension:
                                new_dimension = Ellipsis  # ambiguous
                            if new_dimension != old_dimension:
                                dimension_for_folder_icon_dirpath[folder_icon_dirpath] = new_dimension
        
        # Install new folder icons, in local theme directories
        if len(dimension_for_folder_icon_dirpath) == 0:
            print('WARNING: Unable to locate places to install folder icons')
        else:
            local_icons_dirpath = os.path.expanduser('~/.local/share/icons')
            for (folder_icon_dirpath, dimension) in dimension_for_folder_icon_dirpath.items():
                folder_icon_abs_dirpath = os.path.join(local_icons_dirpath, folder_icon_dirpath)
                os.makedirs(folder_icon_abs_dirpath, exist_ok=True)
                
                # Install PNG icon for folder type
                with open(f'{folder_icon_abs_dirpath}/crystalproj.png', 'wb') as dst_file:
                    dst_file.write(_get_or_load_best_icon('docicon', 'png', dimension))
                
                # Install SVG icon for folder type,
                # because at least KDE on Kubuntu 22 seems to ignore PNG icons
                with open(f'{folder_icon_abs_dirpath}/crystalproj.svg', 'wb') as dst_file:
                    dst_file.write(_get_or_load_best_icon('docicon', 'svg', dimension))
    
    # If KDE, restart plasmasession so that desktop detects new icons immediately
    import psutil  # type: ignore[reportMissingModuleSource]  # Linux-only dependency
    for process in psutil.process_iter(attrs=['cmdline', 'pid', 'cwd', 'environ']):
        process_cmdline = process.cmdline()
        if (len(process_cmdline) >= 1 and
                os.path.basename(process_cmdline[0]) == 'plasmashell'):
            plasmashell = process  # type: Optional[psutil.Process]
            break
    else:
        plasmashell = None
    if plasmashell is not None:
        plasmashell_info = dict(
            cmdline=plasmashell.cmdline(),
            cwd=plasmashell.cwd(),
            environ=plasmashell.environ(),
        )  # capture
        subprocess.run(
            ['kill', str(plasmashell.pid)],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        subprocess.Popen(
            plasmashell_info['cmdline'],
            cwd=plasmashell_info['cwd'],
            env=plasmashell_info['environ'],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        # (Leave new plasmashell process running)


@cache  # ...in memory
def _get_or_load_best_icon(
        name: str,
        type: Literal['png', 'svg'],
        dimension: tuple[int, int] | EllipsisType,
        ) -> bytes:
    """
    Returns the bytes for the icon with the specified name and type
    which either has dimensions matching the specified dimensions or
    is the fallback version of the icon.
    """
    from crystal import resources
    
    if dimension == Ellipsis:
        icon_filename = f'{name}.{type}'
    else:
        assert not isinstance(dimension, EllipsisType)  # help mypy
        icon_filename = f'{name}_{dimension[0]}x{dimension[1]}.{type}'
    try:
        with resources.open_binary(icon_filename) as src_file:
            return src_file.read()
    except FileNotFoundError:
        if dimension == Ellipsis:
            raise ValueError(f'Fallback icon {icon_filename!r} not found')
        return _get_or_load_best_icon(name, type, Ellipsis)


# ------------------------------------------------------------------------------
# Utility: Read Image Dimensions

_PNG_SIGNATURE = bytes([137, 80, 78, 71, 13, 10, 26, 10])  # b'\x89PNG\r\n\x1a\n'


def get_png_dimensions(f: BinaryIO) -> tuple[int, int] | None:
    """
    Reads the specified PNG file object to determine its (width, height) dimensions.
    Returns None if the file is not a valid PNG file.
    """
    # PNG specification 1.2:
    # http://libpng.org/pub/png/spec/1.2/PNG-Contents.html
    
    # Read/validate PNG file signature
    f.seek(0)
    signature = f.read(len(_PNG_SIGNATURE))
    if signature != _PNG_SIGNATURE:
        # Not a PNG file
        return None
    
    # Read IHDR chunk, containing width and height dimensions
    # 
    # NOTE: The CRC of the IHDR chunk is NOT validated for simplicity of implementation
    f.seek(12)
    chunk_type = f.read(4)
    if chunk_type != b'IHDR':
        # PNG file missing required first 'IHDR' chunk
        return None
    width = _decode_uint(f.read(4))
    height = _decode_uint(f.read(4))
    if width == 0 or height == 0:
        # Invalid width or height
        return None
    return (width, height)


def get_svg_dimensions(f: BinaryIO) -> tuple[int, int] | None:
    """
    Reads the specified SVG file object to determine its (width, height) dimensions.
    Returns None if the file is not a valid SVG file or no dimensions are defined.
    """
    try:
        for (event, el) in ET.iterparse(f, events=('start',)):
            assert event == 'start'
            first_el = el
            
            # Ensure initial tag is <svg>
            if first_el.tag != '{http://www.w3.org/2000/svg}svg':
                # Not an SVG file
                return None
            
            # Parse "viewBox" from <svg> element
            view_box_str = first_el.attrib.get('viewBox')
            if view_box_str is None:
                # No view box defined. No dimensions available.
                return None
            try:
                view_box_int_parts = [int(str_part) for str_part in view_box_str.split(' ')]
            except ValueError:
                # Malformed "viewBox" attribute
                return None
            if len(view_box_int_parts) != 4:
                # Malformed "viewBox" attribute
                return None
            (_, _, width, height) = view_box_int_parts
            if width > 0 and height > 0:
                return (width, height)
            else:
                # SVG rendering is disabled
                return None
        
        # Not an XML file (or an SVG file)
        return None
    except ET.ParseError:
        # Not an XML file (or an SVG file)
        return None


def _decode_uint(uint_bytes: bytes) -> int:
    value = 0
    for b in uint_bytes:
        value = (value << 8) + b
    return value


# ------------------------------------------------------------------------------
# Utility: Change Working Directory

@contextmanager
def _cwd_set_to(dirpath: str) -> 'Iterator[None]':
    old_cwd = os.getcwd()
    os.chdir(dirpath)
    try:
        yield
    finally:
        os.chdir(old_cwd)


# ------------------------------------------------------------------------------
