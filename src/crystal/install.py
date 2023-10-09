from contextlib import contextmanager
import os
import shutil
import subprocess
import sys
from typing import Iterator, List


def install_to_linux_desktop_environment() -> None:
    """Install the Crystal application to the desktop. (Linux only)"""
    from crystal import resources
    from crystal.util import gio
    from crystal.util.xos import is_linux
    import glob
    
    if not is_linux():
        raise ValueError()
    
    # Ensure not running as root (unless is actually the root user)
    running_as_root_user = (os.geteuid() == 0)
    is_root_user = (os.getuid() == 0)
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
    with open(f'{mime_dirpath}/packages/application-vnd.crystal-opener.xml', 'w') as dst_file:
        with resources.open_text('application-vnd.crystal-opener.xml', encoding='utf-8') as src_file:
            shutil.copyfileobj(src_file, dst_file)
    subprocess.run(['update-mime-database', mime_dirpath], check=True)
    
    # Install .crystalopen file icon
    if True:
        # Locate places where MIME icons are installed, in global theme directories
        mime_icon_dirpaths = []
        with _cwd_set_to('/usr/share/icons'):
            for mime_icon_filepath in glob.iglob('**/text-plain.*', recursive=True):
                mime_icon_dirpath = os.path.dirname(mime_icon_filepath)
                if mime_icon_dirpath not in mime_icon_dirpaths:
                    mime_icon_dirpaths.append(mime_icon_dirpath)
        
        # Install new MIME icons, in local theme directories
        if len(mime_icon_dirpaths) == 0:
            print('*** Unable to locate places to install MIME icons')
        else:
            local_icons_dirpath = os.path.expanduser('~/.local/share/icons')
            for mime_icon_dirpath in mime_icon_dirpaths:
                mime_icon_abs_dirpath = os.path.join(local_icons_dirpath, mime_icon_dirpath)
                os.makedirs(mime_icon_abs_dirpath, exist_ok=True)
                
                # Install PNG icon for MIME type
                with open(f'{mime_icon_abs_dirpath}/application-vnd.crystal-opener.png', 'wb') as dst_file:
                    # TODO: Read/cache source icon once, so that don't need to many times...
                    with resources.open_binary('application-vnd.crystal-opener.png') as src_file:
                        shutil.copyfileobj(src_file, dst_file)
                
                # Install SVG icon for MIME type,
                # because at least KDE on Kubuntu 22 seems to ignore PNG icons
                with open(f'{mime_icon_abs_dirpath}/application-vnd.crystal-opener.svg', 'wb') as dst_file:
                    # TODO: Read/cache source icon once, so that don't need to many times...
                    with resources.open_binary('application-vnd.crystal-opener.svg') as src_file:
                        shutil.copyfileobj(src_file, dst_file)
            
            # NOTE: At least on Ubuntu 22 it seems the icon caches don't need
            #       to be explicitly updated to pick up the new icon type
            #       immediately, which is good because it may not be possible
            #       to sudo.
            #subprocess.run(['sudo', 'update-icon-caches', *glob.glob('/usr/share/icons/*')], check=True)
    
    # Install .crystalproj folder icon
    if True:
        # Determine icon names for regular folder, which actually resolve to an icon
        try:
            regular_folder_dirpath = os.path.dirname(__file__)
            p = subprocess.run(
                ['gio', 'info', '--attributes', 'standard::icon', regular_folder_dirpath],
                check=True,
                capture_output=True,
            )
        except FileNotFoundError:
            # GIO not available
            pass
        else:
            icon_names: List[str]
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
            folder_icon_dirpaths = []
            if len(icon_names) != 0:
                with _cwd_set_to('/usr/share/icons'):
                    for (root_dirpath, dirnames, filenames) in os.walk('.'):
                        for filename in filenames:
                            (filename_without_ext, _) = os.path.splitext(filename)
                            if filename_without_ext in icon_names:
                                if root_dirpath not in folder_icon_dirpaths:
                                    folder_icon_dirpaths.append(root_dirpath)
            
            # Install new folder icons, in local theme directories
            if len(folder_icon_dirpaths) == 0:
                print('*** Unable to locate places to install folder icons')
            else:
                local_icons_dirpath = os.path.expanduser('~/.local/share/icons')
                for folder_icon_dirpath in folder_icon_dirpaths:
                    folder_icon_abs_dirpath = os.path.join(local_icons_dirpath, folder_icon_dirpath)
                    os.makedirs(folder_icon_abs_dirpath, exist_ok=True)
                    
                    # Install PNG icon for folder type
                    with open(f'{folder_icon_abs_dirpath}/crystalproj.png', 'wb') as dst_file:
                        # TODO: Read/cache source icon once, so that don't need to 123 times...
                        with resources.open_binary('docicon.png') as src_file:
                            shutil.copyfileobj(src_file, dst_file)
                    
                    # Install SVG icon for folder type,
                    # because at least KDE on Kubuntu 22 seems to ignore PNG icons
                    with open(f'{folder_icon_abs_dirpath}/crystalproj.svg', 'wb') as dst_file:
                        # TODO: Read/cache source icon once, so that don't need to 123 times...
                        with resources.open_binary('docicon.svg') as src_file:
                            shutil.copyfileobj(src_file, dst_file)


@contextmanager
def _cwd_set_to(dirpath: str) -> 'Iterator[None]':
    old_cwd = os.getcwd()
    os.chdir(dirpath)
    try:
        yield
    finally:
        os.chdir(old_cwd)
