from crystal.util.xos import (
    is_linux, is_mac_os, is_windows, windows_major_version,
)
import json
import os
import os.path
import subprocess


# NOTE: Neither the "ssd" nor "ssd_checker" projects on PyPI,
#       which are supposed to implement this function,
#       actually work on macOS, as of 2023-12-08.
def is_ssd(itempath: str) -> bool:
    """
    Returns whether the specified file is definitely on a local solid state disk.
    
    Such a disk is assumed to support O(1) random reads and have a high
    maximum IOPS.
    """
    if is_mac_os():
        return _is_mac_ssd(itempath)
    elif is_linux():
        return _is_linux_ssd(itempath)
    elif is_windows():
        return _is_windows_ssd(itempath)
    else:  # unknown OS
        return False


def _mountpoint(abs_itempath: str) -> str:
    assert abs_itempath.startswith('/')
    mountpoint_dirpath = abs_itempath
    while not os.path.ismount(mountpoint_dirpath):
        new_mountpoint_dirpath = os.path.dirname(mountpoint_dirpath)
        if mountpoint_dirpath == new_mountpoint_dirpath:
            raise AssertionError('Root directory is not considered a mount point: ' + mountpoint_dirpath)
        mountpoint_dirpath = new_mountpoint_dirpath  # reinterpret
    return mountpoint_dirpath


def _is_mac_ssd(itempath: str) -> bool:
    import plistlib
    
    mountpoint_dirpath = _mountpoint(os.path.realpath(itempath))
    mountpoint_info = plistlib.loads(subprocess.check_output(
        ['diskutil', 'info', '-plist', mountpoint_dirpath],
    ))
    return mountpoint_info.get('SolidState', False)


def _is_linux_ssd(itempath: str) -> bool:
    mountpoint_dirpath = _mountpoint(os.path.realpath(itempath))
    lsblk_info = json.loads(subprocess.check_output(
        ['lsblk', '-o', 'name,rota,mountpoints', '--list', '--json'],
    ).decode('utf-8'))
    for device in lsblk_info['blockdevices']:
        for device_mount in device['mountpoints']:
            if device_mount == mountpoint_dirpath:
                rota = device['rota']
                assert isinstance(rota, bool)
                return not rota
    return False  # mountpoint not found


def _is_windows_ssd(itempath: str) -> bool:
    import win32file

    itempath = os.path.realpath(itempath)
    # TODO: Does this handle UNC paths correctly?
    drive = os.path.splitdrive(itempath)[0].upper()
    drivetype = win32file.GetDriveType(drive)
    if drivetype == win32file.DRIVE_RAMDISK:
        return True
    elif drivetype in (win32file.DRIVE_FIXED, win32file.DRIVE_REMOVABLE):
        winver = windows_major_version()
        if winver is not None and winver < 8:
            # Need Windows 8+ to access MSFT_PhysicalDisk in WMI, according to:
            # https://learn.microsoft.com/en-us/windows-hardware/drivers/storage/msft-physicaldisk
            return False
        
        import wmi

        c = wmi.WMI()
        phy_to_part = 'Win32_DiskDriveToDiskPartition'
        log_to_part = 'Win32_LogicalDiskToPartition'
        index = {
            log_disk.Caption: phy_disk.Index
            for phy_disk in c.Win32_DiskDrive()
            for partition in phy_disk.associators(phy_to_part)
            for log_disk in partition.associators(log_to_part)
        }
        
        if drive in index:
            c = wmi.WMI(moniker='//./ROOT/Microsoft/Windows/Storage')
            return bool(c.MSFT_PhysicalDisk(DeviceId=str(index[drive]), MediaType=4))
        else:
            return False
    else:
        return False
