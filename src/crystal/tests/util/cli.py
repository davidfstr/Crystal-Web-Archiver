
from collections.abc import Iterator
from contextlib import contextmanager
from crystal.tests.util.asserts import assertEqual
from crystal.tests.util.screenshots import take_error_screenshot
from crystal.tests.util.wait import DEFAULT_WAIT_PERIOD, DEFAULT_WAIT_TIMEOUT, HARD_TIMEOUT_MULTIPLIER, WaitTimedOut
from crystal.tests.util.windows import MainWindow
from crystal.util.xos import is_asan, is_windows
from select import select
import textwrap
import time
from typing import Optional
import warnings
from io import TextIOBase
import os
import subprocess
import sys
from unittest import SkipTest


# ------------------------------------------------------------------------------
# Run CLI

def run_crystal(args: list[str]) -> subprocess.CompletedProcess[str]:
    """
    Run Crystal CLI with the given arguments and return the result.
    
    Raises:
    * SkipTest -- if Crystal CLI cannot be used in the current environment
    """
    with crystal_running(args=args, discrete_stderr=True) as crystal:
        (stdout_data, stderr_data) = crystal.communicate()
        return subprocess.CompletedProcess(
            args=args,
            returncode=crystal.returncode,
            stdout=stdout_data,
            stderr=stderr_data
        )


# ------------------------------------------------------------------------------
# Start CLI

@contextmanager
def crystal_running(*, args=[], env_extra={}, discrete_stderr: bool=False) -> Iterator[subprocess.Popen]:
    """
    Context which starts "crystal" upon enter
    and cleans up the associated process upon exit.
    
    Arguments:
    * discrete_stderr --
        if True, stderr is kept separate from stdout;
        if False, stderr is merged into stdout.
    
    Raises:
    * SkipTest -- if Crystal CLI cannot be used in the current environment
    """
    _ensure_can_use_crystal_cli()
    
    # Determine how to run Crystal on command line
    crystal_command: list[str]
    python = sys.executable
    if getattr(sys, 'frozen', None) == 'macosx_app':
        python_neighbors = os.listdir(os.path.dirname(python))
        (crystal_binary_name,) = (n for n in python_neighbors if 'crystal' in n.lower())
        crystal_binary = os.path.join(os.path.dirname(python), crystal_binary_name)
        crystal_command = [crystal_binary]
    else:
        crystal_command = [python, '-m', 'crystal']
    
    crystal = subprocess.Popen(
        [*crystal_command, *args],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE if discrete_stderr else subprocess.STDOUT,
        encoding='utf-8',
        env={
            **os.environ,
            **{
                'CRYSTAL_FAULTHANDLER': 'True',
                
                # Prevent Python warnings from being mixed into output
                'PYTHONWARNINGS': 'ignore',
                
                # Prevent profiling warnings from being mixed into output
                # TODO: Recommend renaming to avoid (double-)negatives
                'CRYSTAL_NO_PROFILE_FG_TASKS': 'True',
                'CRYSTAL_NO_PROFILE_GC': 'True',
                'CRYSTAL_NO_PROFILE_RECORD_LINKS': 'True',
            },
            **env_extra
        })
    try:
        assert isinstance(crystal.stdout, TextIOBase)
        
        yield crystal
    finally:
        assert crystal.stdin is not None
        crystal.stdin.close()
        assert crystal.stdout is not None
        crystal.stdout.close()
        crystal.kill()
        crystal.wait()


def _ensure_can_use_crystal_cli() -> None:
    """
    Raises:
    * SkipTest -- if Crystal CLI cannot be used in the current environment
    """
    if is_windows():
        # NOTE: Windows doesn't provide stdout for graphical processes,
        #       which is needed by the current implementation.
        #       Workaround is possible with run_exe.py but time-consuming to implement.
        raise SkipTest('not supported on Windows; graphical subprocesses are mute')
    if is_asan():
        # NOTE: ASan slows down many operations, causing shell operations to
        #       spuriously fail timeout checks, even when
        #       CRYSTAL_GLOBAL_TIMEOUT_MULTIPLIER is used
        raise SkipTest('too slow when run with Address Sanitizer')


@contextmanager
def crystal_shell(*, args=[], env_extra={}) -> Iterator[tuple[subprocess.Popen, str]]:
    """
    Context which starts "crystal --shell" upon enter
    and cleans up the associated process upon exit.
    
    Raises:
    * SkipTest -- if Crystal CLI cannot be used in the current environment
    """
    with crystal_running(args=['--shell', *args], env_extra=env_extra) as crystal:
        assert isinstance(crystal.stdout, TextIOBase)
        (banner, _) = read_until(
            crystal.stdout, '\n>>> ',
            timeout=4.0  # 2.0s isn't long enough for macOS test runners on GitHub Actions
        )
        yield (crystal, banner)


# ------------------------------------------------------------------------------
# Interact

def py_eval(
        python: subprocess.Popen,
        py_code: str,
        stop_suffix: str | tuple[str, ...] | None=None,
        *, timeout: float | None=None) -> str:
    if '\n' in py_code and stop_suffix is None:
        raise ValueError(
            'Unsafe to use _py_eval() on multi-line py_code '
            'unless stop_suffix is set carefully')
    if stop_suffix is None:
        stop_suffix = '>>> '
    
    assert isinstance(python.stdin, TextIOBase)
    assert isinstance(python.stdout, TextIOBase)
    python.stdin.write(f'{py_code}\n'); python.stdin.flush()
    (result, found_stop_suffix) = read_until(
        python.stdout, stop_suffix, timeout=timeout, stacklevel_extra=1)
    return result[:-len(found_stop_suffix)]


def read_until(
        stream: TextIOBase,
        stop_suffix: str | tuple[str, ...],
        timeout: float | None=None,
        *, period: float | None=None,
        stacklevel_extra: int=0
        ) -> tuple[str, str]:
    """
    Reads from the specified stream until the provided `stop_suffix`
    is read at the end of the stream or the timeout expires.
    
    Raises:
    * ReadUntilTimedOut -- if the timeout expires before `stop_suffix` is read
    """
    if isinstance(stop_suffix, str):
        stop_suffix = (stop_suffix,)
    if timeout is None:
        timeout = DEFAULT_WAIT_TIMEOUT
    if period is None:
        period = DEFAULT_WAIT_PERIOD
    
    soft_timeout = timeout
    hard_timeout = timeout * HARD_TIMEOUT_MULTIPLIER
    
    stop_suffix_bytes_choices = [s.encode(stream.encoding) for s in stop_suffix]
    
    read_buffer = b''
    found_stop_suffix = None  # type: Optional[str]
    start_time = time.time()
    hard_timeout_exceeded = False
    try:
        delta_time = 0.0
        while True:
            # 1. Wait for stream to be ready to read or hit EOF
            # 2. Read stream (if became ready)
            # 3. Look for an acceptable `stop_suffix` at the end of everything read so far
            remaining_time = hard_timeout - delta_time
            assert remaining_time > 0
            (rlist_ready, _, xlist_ready) = select(
                [stream],
                [],
                [stream],
                remaining_time)
            did_time_out = (len(rlist_ready) + len(xlist_ready) == 0)
            if did_time_out:
                # Look for an acceptable "stop suffix"
                # Special case: '' is always an acceptable `stop_suffix`
                if '' in stop_suffix:
                    found_stop_suffix = ''
            else:
                # Read stream
                # NOTE: Append uses quadratic performance.
                #       Not using for large amounts of text so I don't care.
                read_buffer += stream.buffer.read1(1024)  # type: ignore[attr-defined]  # arbitrary
                
                # Look for an acceptable "stop suffix"
                for (i, s_bytes) in enumerate(stop_suffix_bytes_choices):
                    if read_buffer.endswith(s_bytes):
                        found_stop_suffix = stop_suffix[i]
                        break
            if found_stop_suffix is not None:
                # Done
                break
            
            # If hard timeout exceeded then raise
            delta_time = time.time() - start_time
            if did_time_out or delta_time >= hard_timeout:
                # Screenshot the timeout error
                take_error_screenshot()
                
                hard_timeout_exceeded = True
                read_so_far = read_buffer.decode(stream.encoding)
                raise ReadUntilTimedOut(
                    f'Timed out after {timeout:.1f}s while '
                    f'reading until {stop_suffix!r}. '
                    f'Read so far: {read_so_far!r}',
                    read_so_far)
    finally:
        # If soft timeout exceeded then warn before returning
        if not hard_timeout_exceeded:
            delta_time = time.time() - start_time
            if delta_time > soft_timeout:
                warnings.warn(
                    ('Soft timeout exceeded (%.1fs > %.1fs) while '
                    'reading until %r.') % (
                        delta_time,
                        soft_timeout,
                        stop_suffix
                    ),
                    stacklevel=(2 + stacklevel_extra))
            
    return (read_buffer.decode(stream.encoding), found_stop_suffix)


class ReadUntilTimedOut(WaitTimedOut):
    def __init__(self, message: str, read_so_far: str) -> None:
        super().__init__(message)
        self.read_so_far = read_so_far


_DEFAULT_DRAIN_TTL = min(DEFAULT_WAIT_TIMEOUT, 2.0)

def drain(stream: TextIOBase | subprocess.Popen, ttl: float | None=None) -> str:
    """
    Reads as much as possible from the specified stream for the specified
    TTL duration and returns it.
    
    Often useful for debugging _read_until() failures.
    """
    if ttl is None:
        ttl = _DEFAULT_DRAIN_TTL
    
    if isinstance(stream, subprocess.Popen):
        stream2 = stream.stdout
        assert isinstance(stream2, TextIOBase)
        stream = stream2  # reinterpret
    
    EOT = '\4'  # End of Transmission; an unlikely character to occur in the wild
    try:
        read_until(stream, EOT, ttl)
    except ReadUntilTimedOut as e:
        return e.read_so_far
    else:
        raise ValueError('Actually encountered EOT while reading stream!')


# ------------------------------------------------------------------------------
# Windows

_OK_THREAD_STOP_SUFFIX = (
    # If thread finishes after the "t.start()" fully completes and writes the next '>>> ' prompt
    'OK\n',
    # If thread finishes before the "t.start()" fully completes and writes the next '>>> ' prompt
    'OK\n>>> ',
    # If the next '>>> ' prompt is written in the middle of "OK" + "\n" being printed.
    'OK>>> \n',
    # TODO: Determine how this empiricially observed situation is possible
    'OK\n>>> >>> ',
)

def create_new_empty_project(crystal: subprocess.Popen) -> None:
    # NOTE: Uses private API, including the entire crystal.tests package
    py_eval(crystal, textwrap.dedent('''\
        if True:
            from crystal.tests.util.runner import run_test
            from crystal.tests.util.windows import OpenOrCreateDialog
            import os
            import tempfile
            from threading import Thread
            #
            async def create_new_project():
                ocd = await OpenOrCreateDialog.wait_for()
                mw = await ocd.create_and_leave_open()
                #
                return mw
            #
            result_cell = [Ellipsis]
            def get_result(result_cell):
                result_cell[0] = run_test(lambda: create_new_project())
                print('OK')
            #
            t = Thread(target=lambda: get_result(result_cell))
            t.start()
        '''),
        stop_suffix=_OK_THREAD_STOP_SUFFIX,
        # NOTE: 6.0 was observed to sometimes not be long enough on macOS
        timeout=8.0
    )
    assertEqual(
        "<class 'crystal.tests.util.windows.MainWindow'>\n",
        py_eval(crystal, 'type(result_cell[0])'))


def close_open_or_create_dialog(crystal: subprocess.Popen, *, after_delay: float | None=None) -> None:
    # NOTE: Uses private API, including the entire crystal.tests package
    py_eval(crystal, textwrap.dedent(f'''\
        if True:
            from crystal.tests.util.runner import bg_sleep, run_test
            from crystal.tests.util.windows import OpenOrCreateDialog
            from threading import Thread
            #
            async def close_ocd():
                ocd = await OpenOrCreateDialog.wait_for()
                if {after_delay} != None:
                    await bg_sleep({after_delay})
                ocd.open_or_create_project_dialog.Close()
                #
                print('OK')
            #
            t = Thread(target=lambda: run_test(close_ocd))
            t.start()
        '''), stop_suffix=_OK_THREAD_STOP_SUFFIX if after_delay is None else '')


def close_main_window(crystal: subprocess.Popen, *, after_delay: float | None=None) -> None:
    # NOTE: Uses private API, including the entire crystal.tests package
    py_eval(crystal, textwrap.dedent(f'''\
        if True:
            from crystal.tests.util.runner import bg_sleep, run_test
            from crystal.tests.util.windows import MainWindow
            from threading import Thread
            #
            async def close_main_window():
                mw = await MainWindow.wait_for()
                if {after_delay} != None:
                    await bg_sleep({after_delay})
                await mw.close()
                #
                print('OK')
            #
            t = Thread(target=lambda: run_test(close_main_window))
            t.start()
        '''),
        stop_suffix=_OK_THREAD_STOP_SUFFIX if after_delay is None else '',
        timeout=MainWindow.CLOSE_TIMEOUT,
    )


@contextmanager
def delay_between_downloads_minimized(crystal: subprocess.Popen) -> Iterator[None]:
    # NOTE: Uses private API, including the entire crystal.tests package
    py_eval(crystal, 'from crystal.tests.util.downloads import delay_between_downloads_minimized as D')
    py_eval(crystal, 'download_ctx = D()')
    py_eval(crystal, 'download_ctx.__enter__()')
    try:
        yield
    finally:
        py_eval(crystal, 'download_ctx.__exit__(None, None, None)')


# ------------------------------------------------------------------------------
# Exit

def wait_for_crystal_to_exit(
        crystal: subprocess.Popen,
        *, timeout: float,
        stacklevel_extra: int=0
        ) -> None:
    start_time = time.time()  # capture
    try:
        crystal.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        try:
            crystal.wait(timeout=(timeout * HARD_TIMEOUT_MULTIPLIER) - timeout)
        except subprocess.TimeoutExpired:
            raise WaitTimedOut('Timed out waiting for Crystal to exit') from None
        else:
            delta_time = time.time() - start_time
            warnings.warn(
                ('Soft timeout exceeded (%.1fs > %.1fs) while '
                'waiting for Crystal to exit') % (
                    delta_time,
                    timeout,
                ),
                stacklevel=(2 + stacklevel_extra))


# ------------------------------------------------------------------------------
