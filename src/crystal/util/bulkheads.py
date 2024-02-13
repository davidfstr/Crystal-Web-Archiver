from crystal.util import cli
from functools import wraps
import sys
import traceback
from typing import Callable, List, Optional, Protocol, TypeVar
from typing_extensions import Concatenate, ParamSpec


_S = TypeVar('_S')
_TK = TypeVar('_TK', bound='Task')
_P = ParamSpec('_P')
_R = TypeVar('_R')


# ------------------------------------------------------------------------------
# Bulkheads

CrashReason = BaseException  # with .__traceback__ set to a TracebackType


# TODO: Rename concept to Bulkhead
class Task(Protocol):
    crash_reason: CrashReason


def captures_crashes_to_self(
        task_method: 'Callable[Concatenate[_TK, _P], Optional[_R]]'
        ) -> 'Callable[Concatenate[_TK, _P], Optional[_R]]':
    """
    A Task method that captures any raised exceptions to itself,
    as the "crash reason" of the task.
    
    If the task was already crashed (with a non-None "crash reason") then
    this method will immediately abort, returning None.
    """
    @wraps(task_method)
    @_mark_bulkhead
    def bulkhead(self: '_TK', *args: _P.args, **kwargs: _P.kwargs) -> Optional[_R]:
        if self.crash_reason is not None:
            # Task has already crashed. Abort.
            return None
        try:
            return task_method(self, *args, **kwargs)
        except BaseException as e:
            # Print traceback to assist in debugging in the terminal,
            # including ancestor callers of bulkhead
            _print_bulkhead_exception(e)
            
            # Crash the task. Abort.
            self.crash_reason = e
            return None
    return bulkhead


def captures_crashes_to_task_arg(
        method: 'Callable[Concatenate[_S, _TK, _P], Optional[_R]]'
        ) -> 'Callable[Concatenate[_S, _TK, _P], Optional[_R]]':
    """
    A method that captures any raised exceptions to its first Task argument,
    as the "crash reason" of the task.
    
    If the task was already crashed (with a non-None "crash reason") then
    this method will immediately abort, returning None.
    """
    @wraps(method)
    @_mark_bulkhead
    def bulkhead(self: '_S', task: _TK, *args: _P.args, **kwargs: _P.kwargs) -> Optional[_R]:
        if task.crash_reason is not None:
            # Task has already crashed. Abort.
            return None
        try:
            return method(self, task, *args, **kwargs)
        except BaseException as e:
            # Print traceback to assist in debugging in the terminal,
            # including ancestor callers of bulkhead
            _print_bulkhead_exception(e)
            
            # Crash the task. Abort.
            task.crash_reason = e
            return None
    return bulkhead


def captures_crashes_to(task: Task) -> Callable[[Callable[_P, Optional[_R]]], Callable[_P, Optional[_R]]]:
    """
    A method that captures any raised exceptions to the specified Task,
    as the "crash reason" of the task.
    
    If the task was already crashed (with a non-None "crash reason") then
    this method will immediately abort, returning None.
    """
    def decorate(func: Callable[_P, Optional[_R]]) -> Callable[_P, Optional[_R]]:
        @wraps(func)
        @_mark_bulkhead
        def bulkhead(*args: _P.args, **kwargs: _P.kwargs) -> Optional[_R]:
            if task.crash_reason is not None:
                # Task has already crashed. Abort.
                return None
            try:
                return func(*args, **kwargs)
            except BaseException as e:
                # Print traceback to assist in debugging in the terminal,
                # including ancestor callers of bulkhead
                _print_bulkhead_exception(e)
                
                # Crash the task. Abort.
                task.crash_reason = e
                return None
        return bulkhead
    return decorate


def captures_crashes_to_stderr(func: Callable[_P, Optional[_R]]) -> Callable[_P, Optional[_R]]:
    """
    A method that captures any raised exceptions, and prints them to stderr.
    """
    @wraps(func)
    @_mark_bulkhead
    def bulkhead(*args: _P.args, **kwargs: _P.kwargs) -> Optional[_R]:
        try:
            return func(*args, **kwargs)
        except BaseException as e:
            # Print traceback to assist in debugging in the terminal,
            # including ancestor callers of bulkhead
            _print_bulkhead_exception(e, is_error=True)
            
            # Abort.
            return None
    return bulkhead


def does_not_capture_crashes(func: Callable[_P, _R]) -> Callable[_P, _R]:
    """
    Explicitly marks functions that intentionally do not capture crashes,
    allowing them to bubble up to their caller.
    """
    return func


def _mark_bulkhead(bulkhead: Callable[_P, _R]) -> Callable[_P, _R]:
    bulkhead._crashes_captured = True  # type: ignore[attr-defined]
    return bulkhead


def _print_bulkhead_exception(e: BaseException, *, is_error: bool=False) -> None:
    # Print traceback to assist in debugging in the terminal,
    # including ancestor callers of bulkhead
    err_file = sys.stderr
    print(
        cli.TERMINAL_FG_RED if is_error else cli.TERMINAL_FG_YELLOW,
        end='', file=err_file)
    if e.__traceback__ is not None:
        here_tb = traceback.extract_stack(sys._getframe().f_back)
        exc_tb = traceback.extract_tb(e.__traceback__)
        full_tb_summary = here_tb[:-1] + exc_tb  # type: List[traceback.FrameSummary]
        print('Exception in bulkhead:', file=err_file)
        print('Traceback (most recent call last):', file=err_file)
        for x in traceback.format_list(full_tb_summary):
            print(x, end='', file=err_file)
    for x in traceback.format_exception_only(type(e), e):
        print(x, end='', file=err_file)
    print(cli.TERMINAL_RESET, end='', file=err_file)
    err_file.flush()


def call_bulkhead(
        bulkhead: Callable[_P, _R],
        /, *args: _P.args,
        **kwargs: _P.kwargs
        ) -> '_R':
    """
    Calls a method marked as @captures_crashes_to*,
    which does not reraise exceptions from its interior.
    
    Raises AssertionError if the specified method is not actually
    marked with @captures_crashes_to*.
    """
    if getattr(bulkhead, '_crashes_captured', False) != True:
        raise AssertionError(f'Expected callable {bulkhead!r} to be decorated with @captures_crashes_to*')
    return bulkhead(*args, **kwargs)


# ------------------------------------------------------------------------------