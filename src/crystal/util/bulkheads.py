from crystal.util import cli
from functools import wraps
import sys
import traceback
from typing import Callable, List, Optional, Protocol, TypeVar
from typing_extensions import Concatenate, ParamSpec


_S = TypeVar('_S')
_B = TypeVar('_B', bound='Bulkhead')
_P = ParamSpec('_P')
_R = TypeVar('_R')


# ------------------------------------------------------------------------------
# Bulkheads

CrashReason = BaseException  # with .__traceback__ set to a TracebackType


# TODO: Rename concept to Bulkhead
class Bulkhead(Protocol):
    crash_reason: CrashReason


def captures_crashes_to_self(
        bulkhead_method: 'Callable[Concatenate[_B, _P], Optional[_R]]'
        ) -> 'Callable[Concatenate[_B, _P], Optional[_R]]':
    """
    A Bulkhead method that captures any raised exceptions to itself,
    as the "crash reason" of the bulkhead.
    
    If the bulkhead was already crashed (with a non-None "crash reason") then
    this method will immediately abort, returning None.
    """
    @wraps(bulkhead_method)
    @_mark_bulkhead_call
    def bulkhead_call(self: '_B', *args: _P.args, **kwargs: _P.kwargs) -> Optional[_R]:
        if self.crash_reason is not None:
            # Bulkhead has already crashed. Abort.
            return None
        try:
            return bulkhead_method(self, *args, **kwargs)
        except BaseException as e:
            # Print traceback to assist in debugging in the terminal,
            # including ancestor callers of bulkhead_call
            _print_bulkhead_exception(e)
            
            # Crash the bulkhead. Abort.
            self.crash_reason = e
            return None
    return bulkhead_call


def captures_crashes_to_bulkhead_arg(
        method: 'Callable[Concatenate[_S, _B, _P], Optional[_R]]'
        ) -> 'Callable[Concatenate[_S, _B, _P], Optional[_R]]':
    """
    A method that captures any raised exceptions to its first Bulkhead argument,
    as the "crash reason" of the bulkhead.
    
    If the bulkhead was already crashed (with a non-None "crash reason") then
    this method will immediately abort, returning None.
    """
    @wraps(method)
    @_mark_bulkhead_call
    def bulkhead_call(self: '_S', bulkhead: _B, *args: _P.args, **kwargs: _P.kwargs) -> Optional[_R]:
        if bulkhead.crash_reason is not None:
            # Bulkhead has already crashed. Abort.
            return None
        try:
            return method(self, bulkhead, *args, **kwargs)
        except BaseException as e:
            # Print traceback to assist in debugging in the terminal,
            # including ancestor callers of bulkhead_call
            _print_bulkhead_exception(e)
            
            # Crash the bulkhead. Abort.
            bulkhead.crash_reason = e
            return None
    return bulkhead_call


def captures_crashes_to(bulkhead: Bulkhead) -> Callable[[Callable[_P, Optional[_R]]], Callable[_P, Optional[_R]]]:
    """
    A method that captures any raised exceptions to the specified Bulkhead,
    as the "crash reason" of the bulkhead.
    
    If the bulkhead was already crashed (with a non-None "crash reason") then
    this method will immediately abort, returning None.
    """
    def decorate(func: Callable[_P, Optional[_R]]) -> Callable[_P, Optional[_R]]:
        @wraps(func)
        @_mark_bulkhead_call
        def bulkhead_call(*args: _P.args, **kwargs: _P.kwargs) -> Optional[_R]:
            if bulkhead.crash_reason is not None:
                # Bulkhead has already crashed. Abort.
                return None
            try:
                return func(*args, **kwargs)
            except BaseException as e:
                # Print traceback to assist in debugging in the terminal,
                # including ancestor callers of bulkhead_call
                _print_bulkhead_exception(e)
                
                # Crash the bulkhead. Abort.
                bulkhead.crash_reason = e
                return None
        return bulkhead_call
    return decorate


def captures_crashes_to_stderr(func: Callable[_P, Optional[_R]]) -> Callable[_P, Optional[_R]]:
    """
    A method that captures any raised exceptions, and prints them to stderr.
    """
    @wraps(func)
    @_mark_bulkhead_call
    def bulkhead_call(*args: _P.args, **kwargs: _P.kwargs) -> Optional[_R]:
        try:
            return func(*args, **kwargs)
        except BaseException as e:
            # Print traceback to assist in debugging in the terminal,
            # including ancestor callers of bulkhead_call
            _print_bulkhead_exception(e, is_error=True)
            
            # Abort.
            return None
    return bulkhead_call


def does_not_capture_crashes(func: Callable[_P, _R]) -> Callable[_P, _R]:
    """
    Explicitly marks functions that intentionally do not capture crashes,
    allowing them to bubble up to their caller.
    """
    return func


def _mark_bulkhead_call(bulkhead_call: Callable[_P, _R]) -> Callable[_P, _R]:
    bulkhead_call._captures_crashes = True  # type: ignore[attr-defined]
    return bulkhead_call


def _print_bulkhead_exception(e: BaseException, *, is_error: bool=False) -> None:
    # Print traceback to assist in debugging in the terminal,
    # including ancestor callers of bulkhead_call
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


def run_bulkhead_call(
        bulkhead_call: Callable[_P, _R],
        /, *args: _P.args,
        **kwargs: _P.kwargs
        ) -> '_R':
    """
    Calls a method marked as @captures_crashes_to*,
    which does not reraise exceptions from its interior.
    
    Raises AssertionError if the specified method is not actually
    marked with @captures_crashes_to*.
    """
    if getattr(bulkhead_call, '_captures_crashes', False) != True:
        raise AssertionError(f'Expected callable {bulkhead_call!r} to be decorated with @captures_crashes_to*')
    return bulkhead_call(*args, **kwargs)


# ------------------------------------------------------------------------------