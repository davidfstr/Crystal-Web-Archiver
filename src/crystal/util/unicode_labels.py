from crystal.util.xos import is_windows, windows_major_version


def decorate_label(icon: str, message: str, truncation_fix: str) -> str:
    if truncation_fix not in ('', ' ', '  '):
        raise ValueError()
    if is_windows():
        if windows_major_version() == 7:
            # Windows 7: Cannot display Unicode icon at all
            return f'{message}'
        else:  # windows_major_version() >= 8
            # Windows 8, 10: Can display some Unicode icons.
            # Some icons require trailing spaces to avoid truncating the message
            return f'{icon} {message}{truncation_fix}'
    return f'{icon} {message}'
