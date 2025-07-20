from collections.abc import Callable
from contextlib import contextmanager
from crystal.tests.util import xtempfile
from crystal.util.xos import is_mac_os
import os
import subprocess
import sys
import time
from typing import Iterator, Type, TypeVar
from unittest import SkipTest
import uuid


@contextmanager
def hdiutil_disk_image_mounted(srcfolder: str | None = None, readonly: bool = False) -> Iterator[str]:
    """
    Creates and mounts a temporary HFS+ disk image on macOS, yielding the mount point.
    Cleanly detaches the image on exit.
    
    If srcfolder is provided, the disk image is populated from that folder.
    If readonly is True, attaches the image read-only.
    
    Raises:
    * SkipTest -- if not supported on this platform
    """
    if not is_mac_os():
        raise SkipTest('hdiutil_disk_image_mounted only supported on macOS')

    with xtempfile.TemporaryDirectory(prefix='tmpfs_') as tmp_root:
        mount_point = os.path.join(tmp_root, 'mnt')
        os.makedirs(mount_point, exist_ok=True)

        # Create the sparse image
        image_path = os.path.join(tmp_root, 'volume.dmg' if srcfolder else 'volume.sparseimage')
        if srcfolder:
            create_cmd = [
                'hdiutil', 'create',
                '-srcfolder', srcfolder,
                image_path
            ]
        else:
            create_cmd = [
                'hdiutil', 'create',
                '-size', '16m',
                '-fs', 'HFS+',
                '-type', 'SPARSE',
                # Randomize volume name to avoid collisions with existing mounts
                '-volname', f'TemporaryFS-{uuid.uuid4().hex}',
                image_path
            ]
        try:
            def create_image() -> None:
                subprocess.run(create_cmd, check=True, capture_output=True)
            _run_with_retries(
                create_image,
                exc_type=subprocess.CalledProcessError,
                exc_matcher=lambda e: b'Resource busy' in e.stderr,
            )
        except subprocess.CalledProcessError as e:
            print(
                f"*** hdiutil create failed (cmd={e.cmd}, returncode={e.returncode})\n"
                f"stdout:\n{e.stdout.decode(errors='replace')}\n"
                f"stderr:\n{e.stderr.decode(errors='replace')}",
                file=sys.stderr
            )
            raise

        # Mount the image
        if readonly:
            attach_cmd = [
                'hdiutil', 'attach',
                image_path,
                '-readonly',
                '-mountpoint', mount_point
            ]
        else:
            attach_cmd = [
                'hdiutil', 'attach',
                image_path,
                '-mountpoint', mount_point,
                '-nobrowse'
            ]
        try:
            def attach_image() -> None:
                subprocess.run(attach_cmd, check=True, capture_output=True)
            _run_with_retries(
                attach_image,
                exc_type=subprocess.CalledProcessError,
                exc_matcher=lambda e: b'Resource busy' in e.stderr,
            )
        except subprocess.CalledProcessError as e:
            print(
                f"*** hdiutil attach failed (cmd={e.cmd}, returncode={e.returncode})\n"
                f"stdout:\n{e.stdout.decode(errors='replace')}\n"
                f"stderr:\n{e.stderr.decode(errors='replace')}",
                file=sys.stderr
            )
            raise

        try:
            yield mount_point
        finally:
            # Unmount the image
            try:
                def detach_image() -> None:
                    subprocess.run([
                        'hdiutil', 'detach',
                        mount_point,
                        '-force'
                    ], check=True, capture_output=True)
                _run_with_retries(
                    detach_image,
                    exc_type=subprocess.CalledProcessError,
                    exc_matcher=lambda e: b'Resource busy' in e.stderr,
                )
            except subprocess.CalledProcessError:
                pass


_E = TypeVar('_E', bound=BaseException)

def _run_with_retries(
        callable: Callable[[], None],
        exc_type: Type[_E]=BaseException,  # type: ignore[assignment]
        exc_matcher: Callable[[_E], bool]=lambda e: True,
        max_retry_count: int = 3,
        delay: float = 1.0) -> None:
    """
    Runs a callable with retries on failure.
    
    Uses a constant delay between retries. (Does NOT use exponential backoff.)
    
    Arguments:
    * callable -- Callable to run
    * max_retry_count -- Maximum number of retries before declaring failure
    * delay -- Delay between retries in seconds
    """
    for attempt_index in range(max_retry_count + 1):
        try:
            if attempt_index > 0:
                time.sleep(delay)
            callable()
            return  # success
        except exc_type as e:
            if exc_matcher(e) and attempt_index < max_retry_count:
                continue
            else:
                raise