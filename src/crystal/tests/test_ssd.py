from crystal.model import Project
from crystal.tests.util.server import extracted_project
from crystal.tests.util.skip import skipTest
from crystal.util.ssd import is_ssd
from crystal.util.xos import is_linux, is_mac_os
import os.path
from textwrap import dedent
from unittest import skip
from unittest.mock import patch

# TODO: Implement the following tests, checking the output of 
#       is_ssd() after mocking subprocess input.


def test_given_macos_and_file_on_local_ssd_then_is_detected_as_on_ssd() -> None:
    DISKUTIL_OUTPUT = dedent(('''
        <?xml version="1.0" encoding="UTF-8"?>
        <!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
        <plist version="1.0">
        <dict>
            <key>AESHardware</key>
            <false/>
            <key>APFSContainerFree</key>
            <integer>10416455680</integer>
            <key>APFSContainerReference</key>
            <string>disk1</string>
            <key>APFSContainerSize</key>
            <integer>500068036608</integer>
            <key>APFSPhysicalStores</key>
            <array>
                <dict>
                    <key>APFSPhysicalStore</key>
                    <string>disk0s2</string>
                </dict>
            </array>
            <key>APFSSnapshot</key>
            <true/>
            <key>APFSSnapshotName</key>
            <string>com.apple.os.update-7E723F1B805923559BBF78D4180228116DC67F3DC50096130A5DF71447733E66</string>
            <key>APFSSnapshotUUID</key>
            <string>CA15E030-DBDD-4FF4-847D-50D5EE26B798</string>
            <key>APFSVolumeGroupID</key>
            <string>B41463C7-EA58-399D-A1E0-B032C963DC2E</string>
            <key>Bootable</key>
            <true/>
            <key>BooterDeviceIdentifier</key>
            <string>disk1s2</string>
            <key>BusProtocol</key>
            <string>PCI</string>
            <key>CanBeMadeBootable</key>
            <false/>
            <key>CanBeMadeBootableRequiresDestroy</key>
            <false/>
            <key>Content</key>
            <string>41504653-0000-11AA-AA11-00306543ECAC</string>
            <key>DeviceBlockSize</key>
            <integer>4096</integer>
            <key>DeviceIdentifier</key>
            <string>disk1s5s1</string>
            <key>DeviceNode</key>
            <string>/dev/disk1s5s1</string>
            <key>DeviceTreePath</key>
            <string>IODeviceTree:/PCI0@0/PEG0@1/SSD0@0/PRT0@0/PMP@0</string>
            <key>DiskUUID</key>
            <string>CA15E030-DBDD-4FF4-847D-50D5EE26B798</string>
            <key>Ejectable</key>
            <false/>
            <key>EjectableMediaAutomaticUnderSoftwareControl</key>
            <false/>
            <key>EjectableOnly</key>
            <false/>
            <key>Encryption</key>
            <true/>
            <key>EncryptionThisVolumeProper</key>
            <false/>
            <key>FileVault</key>
            <true/>
            <key>FilesystemName</key>
            <string>APFS</string>
            <key>FilesystemType</key>
            <string>apfs</string>
            <key>FilesystemUserVisibleName</key>
            <string>APFS</string>
            <key>FreeSpace</key>
            <integer>0</integer>
            <key>Fusion</key>
            <false/>
            <key>GlobalPermissionsEnabled</key>
            <true/>
            <key>IOKitSize</key>
            <integer>500068036608</integer>
            <key>IORegistryEntryName</key>
            <string>com.apple.os.update-7E723F1B805923559BBF78D4180228116DC67F3DC50096130A5DF71447733E66</string>
            <key>Internal</key>
            <true/>
            <key>Locked</key>
            <false/>
            <key>MacOSSystemAPFSEFIDriverVersion</key>
            <integer>1934141002700002</integer>
            <key>MediaName</key>
            <string></string>
            <key>MediaType</key>
            <string>Generic</string>
            <key>MountPoint</key>
            <string>/</string>
            <key>OSInternalMedia</key>
            <false/>
            <key>ParentWholeDisk</key>
            <string>disk1</string>
            <key>PartitionMapPartition</key>
            <false/>
            <key>RAIDMaster</key>
            <false/>
            <key>RAIDSlice</key>
            <false/>
            <key>RecoveryDeviceIdentifier</key>
            <string>disk1s3</string>
            <key>Removable</key>
            <false/>
            <key>RemovableMedia</key>
            <false/>
            <key>RemovableMediaOrExternalDevice</key>
            <false/>
            <key>SMARTDeviceSpecificKeysMayVaryNotGuaranteed</key>
            <dict/>
            <key>SMARTStatus</key>
            <string>Verified</string>
            <key>Sealed</key>
            <string>Yes</string>
            <key>Size</key>
            <integer>500068036608</integer>
            <key>SolidState</key>
            <true/>
            <key>SupportsGlobalPermissionsDisable</key>
            <true/>
            <key>SystemImage</key>
            <false/>
            <key>TotalSize</key>
            <integer>500068036608</integer>
            <key>VolumeAllocationBlockSize</key>
            <integer>4096</integer>
            <key>VolumeName</key>
            <string>SSD</string>
            <key>VolumeSize</key>
            <integer>0</integer>
            <key>VolumeUUID</key>
            <string>CA15E030-DBDD-4FF4-847D-50D5EE26B798</string>
            <key>WholeDisk</key>
            <false/>
            <key>Writable</key>
            <false/>
            <key>WritableMedia</key>
            <false/>
            <key>WritableVolume</key>
            <false/>
        </dict>
        </plist>
        '''
    ).lstrip()).encode('utf-8')
    
    _test_given_macos_and_ellipsis(DISKUTIL_OUTPUT, on_ssd=True)


def test_given_macos_and_file_on_local_hdd_then_is_detected_as_not_on_ssd() -> None:
    DISKUTIL_OUTPUT = dedent(('''
        <?xml version="1.0" encoding="UTF-8"?>
        <!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
        <plist version="1.0">
        <dict>
            <key>Bootable</key>
            <true/>
            <key>BusProtocol</key>
            <string>USB</string>
            <key>CanBeMadeBootable</key>
            <false/>
            <key>CanBeMadeBootableRequiresDestroy</key>
            <false/>
            <key>Content</key>
            <string>Apple_HFS</string>
            <key>DeviceBlockSize</key>
            <integer>512</integer>
            <key>DeviceIdentifier</key>
            <string>disk11s2</string>
            <key>DeviceNode</key>
            <string>/dev/disk11s2</string>
            <key>DeviceTreePath</key>
            <string>IODeviceTree:/PCI0@0/XHC1@14</string>
            <key>DiskUUID</key>
            <string>4118AB4C-B7C9-462C-B849-BBAE385E0100</string>
            <key>Ejectable</key>
            <true/>
            <key>EjectableMediaAutomaticUnderSoftwareControl</key>
            <false/>
            <key>EjectableOnly</key>
            <false/>
            <key>FilesystemName</key>
            <string>Journaled HFS+</string>
            <key>FilesystemType</key>
            <string>hfs</string>
            <key>FilesystemUserVisibleName</key>
            <string>Mac OS Extended (Journaled)</string>
            <key>FreeSpace</key>
            <integer>1111923171328</integer>
            <key>GlobalPermissionsEnabled</key>
            <true/>
            <key>IOKitSize</key>
            <integer>5000603328512</integer>
            <key>IORegistryEntryName</key>
            <string>Untitled 2</string>
            <key>Internal</key>
            <false/>
            <key>JournalOffset</key>
            <integer>76324864</integer>
            <key>JournalSize</key>
            <integer>394264576</integer>
            <key>MediaName</key>
            <string></string>
            <key>MediaType</key>
            <string>Generic</string>
            <key>MountPoint</key>
            <string>/Volumes/HDD</string>
            <key>OSInternalMedia</key>
            <false/>
            <key>ParentWholeDisk</key>
            <string>disk11</string>
            <key>PartitionMapPartition</key>
            <true/>
            <key>PartitionMapPartitionOffset</key>
            <integer>209735680</integer>
            <key>RAIDMaster</key>
            <false/>
            <key>RAIDSlice</key>
            <false/>
            <key>Removable</key>
            <false/>
            <key>RemovableMedia</key>
            <false/>
            <key>RemovableMediaOrExternalDevice</key>
            <true/>
            <key>SMARTDeviceSpecificKeysMayVaryNotGuaranteed</key>
            <dict/>
            <key>SMARTStatus</key>
            <string>Not Supported</string>
            <key>Size</key>
            <integer>5000603328512</integer>
            <key>SupportsGlobalPermissionsDisable</key>
            <true/>
            <key>SystemImage</key>
            <false/>
            <key>TotalSize</key>
            <integer>5000603328512</integer>
            <key>VolumeAllocationBlockSize</key>
            <integer>8192</integer>
            <key>VolumeName</key>
            <string>HDD</string>
            <key>VolumeSize</key>
            <integer>5000603328512</integer>
            <key>VolumeUUID</key>
            <string>18A39FDB-D619-3299-8863-9A3A33608A7F</string>
            <key>WholeDisk</key>
            <false/>
            <key>Writable</key>
            <true/>
            <key>WritableMedia</key>
            <true/>
            <key>WritableVolume</key>
            <true/>
        </dict>
        </plist>
        '''
    ).lstrip()).encode('utf-8')
    
    _test_given_macos_and_ellipsis(DISKUTIL_OUTPUT, on_ssd=False)


@skip('not yet automated')
def test_given_macos_and_file_on_local_optical_drive_then_is_detected_as_not_on_ssd() -> None:
    pass


def test_given_macos_and_file_on_network_disk_then_is_detected_as_not_on_ssd() -> None:
    DISKUTIL_OUTPUT = dedent(('''
        <?xml version="1.0" encoding="UTF-8"?>
        <!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
        <plist version="1.0">
        <dict>
            <key>Error</key>
            <true/>
            <key>ErrorMessage</key>
            <string>Could not find disk: /Volumes/SMB</string>
            <key>ExitCode</key>
            <integer>1</integer>
        </dict>
        </plist>
        '''
    ).lstrip()).encode('utf-8')
    
    _test_given_macos_and_ellipsis(DISKUTIL_OUTPUT, on_ssd=False)


def _test_given_macos_and_ellipsis(DISKUTIL_OUTPUT: bytes, on_ssd: bool) -> None:
    if not is_mac_os():
        skipTest('only supported on macOS')
    
    def fake_ismount(itempath: str) -> bool:
        is_root = (itempath == '/')
        return is_root
    def fake_check_output(cmd: list[str]) -> bytes:
        assert 'diskutil' == cmd[0]
        return DISKUTIL_OUTPUT
    with patch('os.path.ismount', fake_ismount), \
            patch('subprocess.check_output', fake_check_output):
        with extracted_project('testdata_xkcd.crystalproj.zip') as project_dirpath:
            db_filepath = os.path.join(project_dirpath, Project._DB_FILENAME)
            assert on_ssd == is_ssd(db_filepath)


@skip('not yet automated')
def test_given_linux_and_file_on_local_ssd_then_is_detected_as_on_ssd() -> None:
    pass


def test_given_linux_and_file_on_local_hdd_then_is_detected_as_not_on_ssd() -> None:
    _test_given_linux_and_ellipsis(rota=True, on_ssd=False)


@skip('not yet automated')
def test_given_linux_and_file_on_local_optical_drive_then_is_detected_as_not_on_ssd() -> None:
    pass


@skip('not yet automated')
def test_given_linux_and_file_on_network_disk_then_is_detected_as_not_on_ssd() -> None:
    pass


def _test_given_linux_and_ellipsis(rota: bool, on_ssd: bool) -> None:
    if not is_linux():
        skipTest('only supported on Linux')
    
    LSBLK_OUTPUT = dedent(('''
        {
           "blockdevices": [
              {
                 "name": "sda",
                 "rota": true,
                 "mountpoints": [
                     null
                 ]
              },{
                 "name": "sda1",
                 "rota": true,
                 "mountpoints": [
                     null
                 ]
              },{
                 "name": "sda2",
                 "rota": true,
                 "mountpoints": [
                     "/boot/efi"
                 ]
              },{
                 "name": "sda3",
                 "rota": true,
                 "mountpoints": [
                     "/var/snap/firefox/common/host-hunspell", "/"
                 ]
              },{
                 "name": "sr0",
                 "rota": %s,
                 "mountpoints": [
                     null
                 ]
              }
           ]
        }
        ''' % ('true' if rota else 'false')
    ).lstrip()).encode('utf-8')
    
    def fake_ismount(itempath: str) -> bool:
        is_root = (itempath == '/')
        return is_root
    def fake_check_output(cmd: list[str]) -> bytes:
        assert 'lsblk' == cmd[0]
        return LSBLK_OUTPUT
    with patch('os.path.ismount', fake_ismount), \
            patch('subprocess.check_output', fake_check_output):
        with extracted_project('testdata_xkcd.crystalproj.zip') as project_dirpath:
            db_filepath = os.path.join(project_dirpath, Project._DB_FILENAME)
            assert on_ssd == is_ssd(db_filepath)


@skip('not yet automated')
def test_given_windows_and_file_on_local_ssd_then_is_detected_as_on_ssd() -> None:
    pass


@skip('not yet automated')
def test_given_windows_and_file_on_local_hdd_then_is_detected_as_not_on_ssd() -> None:
    pass


@skip('not yet automated')
def test_given_windows_and_file_on_local_optical_drive_then_is_detected_as_not_on_ssd() -> None:
    pass


@skip('not yet automated')
def test_given_windows_and_file_on_network_disk_then_is_detected_as_not_on_ssd() -> None:
    pass