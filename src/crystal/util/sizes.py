from crystal.util.xos import is_mac_os


def format_byte_size(byte_count: int) -> str:
    """Format a size in bytes as a human-readable string."""
    if is_mac_os():
        if byte_count < 1000:
            return f'{byte_count} B'
        elif byte_count < 1000 * 1000:
            return f'{byte_count / 1000:.1f} KB'
        elif byte_count < 1000 * 1000 * 1000:
            return f'{byte_count / (1000 * 1000):.1f} MB'
        elif byte_count < 1000 * 1000 * 1000 * 1000:
            return f'{byte_count / (1000 * 1000 * 1000):.1f} GB'
        else:
            return f'{byte_count / (1000 * 1000 * 1000 * 1000):.2f} TB'
    else:  # Windows or Linux
        if byte_count < 1024:
            return f'{byte_count} B'
        elif byte_count < 1024 * 1024:
            return f'{byte_count / 1024:.1f} KiB'
        elif byte_count < 1024 * 1024 * 1024:
            return f'{byte_count / (1024 * 1024):.1f} MiB'
        elif byte_count < 1024 * 1024 * 1024 * 1024:
            return f'{byte_count / (1024 * 1024 * 1024):.1f} GiB'
        else:
            return f'{byte_count / (1024 * 1024 * 1024 * 1024):.2f} TiB'
