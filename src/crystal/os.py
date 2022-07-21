import platform


def project_appears_as_package_file():
    """
    Returns whether *.crystalproj items appear as package files on this platform.
    
    In particular on macOS the CFBundleDocumentTypes property list key defines
    that *.crystalproj items as LSTypeIsPackage=true, which causes all such
    items to appear as package files rather than as directories.
    """
    return is_mac_os()


def is_mac_os() -> bool:
    return (platform.system() == 'Darwin')


def is_windows() -> bool:
    return (platform.system() == 'Windows')
