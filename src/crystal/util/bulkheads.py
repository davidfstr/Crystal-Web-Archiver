from contextlib import contextmanager
from crystal.util import cli
from functools import wraps
import sys
import traceback
from typing import (
    Callable, Iterator, List, Optional, overload, Protocol, TypeVar, Union
)
from typing_extensions import Concatenate, ParamSpec


_S = TypeVar('_S')
_B = TypeVar('_B', bound='Bulkhead')
_P = ParamSpec('_P')
_R = TypeVar('_R')
_RT = TypeVar('_RT')
_RF = TypeVar('_RF')


# ------------------------------------------------------------------------------
# Bulkheads

CrashReason = BaseException  # with .__traceback__ set to a TracebackType


class Bulkhead(Protocol):  # abstract
    """
    A sink for unhandled exceptions (i.e. crashes).
    """
    crash_reason: Optional[CrashReason]


class BulkheadCell(Bulkhead):
    """
    A concrete Bulkhead which stores any crash that occurs,
    but takes no special action to report such crashes.
    """
    crash_reason: Optional[CrashReason]
    
    def __init__(self, value: Optional[CrashReason]=None) -> None:
        self.crash_reason = value


@overload
def capture_crashes_to_self(
        bulkhead_method: Callable[Concatenate[_B, _P], _RT]
        ) -> Callable[Concatenate[_B, _P], Union[_RT, None]]:
    ...

@overload
def capture_crashes_to_self(
        *, return_if_crashed: _RF
        ) -> Callable[[Callable[Concatenate[_B, _P], _RT]], Callable[Concatenate[_B, _P], Union[_RT, _RF]]]:
    ...

@overload
def capture_crashes_to_self(
        ) -> Callable[[Callable[Concatenate[_B, _P], _RT]], Callable[Concatenate[_B, _P], Union[_RT, None]]]:
    ...

def capture_crashes_to_self(
        bulkhead_method: Optional[Callable[Concatenate[_B, _P], _RT]]=None,
        *, return_if_crashed=None  # _RF
        ):
    """
    A Bulkhead method that captures any raised exceptions to itself,
    as the "crash reason" of the bulkhead.
    
    If the bulkhead was already crashed (with a non-None "crash reason") then
    this method will immediately abort, returning `return_if_crashed`.
    
    Examples:
        class MyBulkhead(Bulkhead):
            @capture_crashes_to_self
            def foo_did_bar(self) -> None:
                ...
            
            @capture_crashes_to_self(return_if_crashed=Ellipsis)
            def calculate_foo(self) -> Result:
                ...
    """
    def decorate(
            bulkhead_method: Callable[Concatenate[_B, _P], _RT]
            ) -> Callable[Concatenate[_B, _P], Union[_RT, _RF]]:
        @wraps(bulkhead_method)
        @_mark_bulkhead_call
        def bulkhead_call(self: _B, *args: _P.args, **kwargs: _P.kwargs) -> Union[_RT, _RF]:
            if self.crash_reason is not None:
                # Bulkhead has already crashed. Abort.
                return return_if_crashed
            try:
                return bulkhead_method(self, *args, **kwargs)  # cr-traceback: ignore
            except BaseException as e:
                # Print traceback to assist in debugging in the terminal,
                # including ancestor callers of bulkhead_call
                _print_bulkhead_exception(e)
                
                # Crash the bulkhead. Abort.
                self.crash_reason = e
                return return_if_crashed
        return bulkhead_call
    if bulkhead_method is None:
        return decorate
    else:
        return decorate(bulkhead_method)


@overload
def capture_crashes_to_bulkhead_arg(
        method: Callable[Concatenate[_S, _B, _P], _RT]
        ) -> Callable[Concatenate[_S, _B, _P], Union[_RT, None]]:
    ...

@overload
def capture_crashes_to_bulkhead_arg(
        *, return_if_crashed: _RF
        ) -> Callable[[Callable[Concatenate[_S, _B, _P], _RT]], Callable[Concatenate[_S, _B, _P], Union[_RT, _RF]]]:
    ...

@overload
def capture_crashes_to_bulkhead_arg(
        ) -> Callable[[Callable[Concatenate[_S, _B, _P], _RT]], Callable[Concatenate[_S, _B, _P], Union[_RT, None]]]:
    ...

def capture_crashes_to_bulkhead_arg(
        method: Optional[Callable[Concatenate[_S, _B, _P], _RT]]=None,
        *, return_if_crashed=None  # _RF
        ):
    """
    A method that captures any raised exceptions to its first Bulkhead argument,
    as the "crash reason" of the bulkhead.
    
    If the bulkhead was already crashed (with a non-None "crash reason") then
    this method will immediately abort, returning `return_if_crashed`.
    
    Examples:
        class MyClass:
            @capture_crashes_to_bulkhead_arg
            def other_foo_did_bar(self, other: Bulkhead) -> None:
                ...
            
            @capture_crashes_to_bulkhead_arg(return_if_crashed=Ellipsis)
            def calculate_baz(self, other: Bulkhead) -> Result:
                ...
    """
    def decorate(
            method: Callable[Concatenate[_S, _B, _P], _RT]
            ) -> Callable[Concatenate[_S, _B, _P], Union[_RT, _RF]]:
        @wraps(method)
        @_mark_bulkhead_call
        def bulkhead_call(self: _S, bulkhead: _B, *args: _P.args, **kwargs: _P.kwargs) -> Union[_RT, _RF]:
            if bulkhead.crash_reason is not None:
                # Bulkhead has already crashed. Abort.
                return return_if_crashed
            try:
                return method(self, bulkhead, *args, **kwargs)  # cr-traceback: ignore
            except BaseException as e:
                # Print traceback to assist in debugging in the terminal,
                # including ancestor callers of bulkhead_call
                _print_bulkhead_exception(e)
                
                # Crash the bulkhead. Abort.
                bulkhead.crash_reason = e
                return return_if_crashed
        return bulkhead_call
    if method is None:
        return decorate
    else:
        return decorate(method)


@overload
def capture_crashes_to(
        bulkhead: Bulkhead
        ) -> Callable[[Callable[_P, _RT]], Callable[_P, Union[_RT, None]]]:
    ...

@overload
def capture_crashes_to(
        bulkhead: Bulkhead,
        return_if_crashed: _RF
        ) -> Callable[[Callable[_P, _RT]], Callable[_P, Union[_RT, _RF]]]:
    ...

def capture_crashes_to(
        bulkhead: Bulkhead,
        return_if_crashed=None  # _RF
        ) -> Callable[[Callable[_P, _RT]], Callable[_P, Union[_RT, _RF]]]:
    """
    A method that captures any raised exceptions to the specified Bulkhead,
    as the "crash reason" of the bulkhead.
    
    If the bulkhead was already crashed (with a non-None "crash reason") then
    this method will immediately abort, returning `return_if_crashed`.
    
    Examples:
        @capture_crashes_to(bulkhead)
        def foo_did_bar() -> None:
            ...
        
        @capture_crashes_to(bulkhead, return_if_crashed=Ellipsis)
        def calculate_foo() -> Result:
            ...
    """
    def decorate(func: Callable[_P, _RT]) -> Callable[_P, Union[_RT, _RF]]:
        @wraps(func)
        @_mark_bulkhead_call
        def bulkhead_call(*args: _P.args, **kwargs: _P.kwargs) -> Union[_RT, _RF]:
            if bulkhead.crash_reason is not None:
                # Bulkhead has already crashed. Abort.
                return return_if_crashed
            try:
                return func(*args, **kwargs)  # cr-traceback: ignore
            except BaseException as e:
                # Print traceback to assist in debugging in the terminal,
                # including ancestor callers of bulkhead_call
                _print_bulkhead_exception(e)
                
                # Crash the bulkhead. Abort.
                bulkhead.crash_reason = e
                return return_if_crashed
        return bulkhead_call
    return decorate


@contextmanager
def crashes_captured_to(bulkhead: Bulkhead, *, enter_if_crashed: bool=False) -> Iterator[None]:
    """
    Context that captures any raised exceptions to the specified Bulkhead,
    as the "crash reason" of the bulkhead.
    
    If the bulkhead was already crashed (with a non-None "crash reason")
    when entering the context, the contents of the context will be skipped,
    unless enter_if_crashed=True.
    
    Example:
        with crashes_captured_to(bulkhead, enter_if_crashed=True):
            ...
    """
    if not enter_if_crashed:
        # NOTE: It's probably not actually possible to implement the
        #       enter_if_crashed=False case because the context manager
        #       protocol provides no reasonable way to skip the interior
        #       context entirely.
        raise NotImplementedError()
    try:
        yield  # cr-traceback: ignore
    except BaseException as e:
        # Print traceback to assist in debugging in the terminal
        _print_bulkhead_exception(e, fix_tb=lambda here_tb, exc_tb: here_tb[:-3] + exc_tb[1:])
        
        # Crash the bulkhead. Abort.
        bulkhead.crash_reason = e
        return


@overload
def capture_crashes_to_stderr(
        func: Callable[_P, _RT]
        ) -> Callable[_P, Union[_RT, None]]:
    ...

@overload
def capture_crashes_to_stderr(
        *, return_if_crashed: _RF
        ) -> Callable[[Callable[_P, _RT]], Callable[_P, Union[_RT, _RF]]]:
    ...

@overload
def capture_crashes_to_stderr(
        ) -> Callable[[Callable[_P, _RT]], Callable[_P, Union[_RT, None]]]:
    ...

def capture_crashes_to_stderr(
        func: Optional[Callable[_P, _RT]]=None,
        *, return_if_crashed=None  # _RF
        ):
    """
    A method that captures any raised exceptions, and prints them to stderr.
    
    Examples:
        @capture_crashes_to_stderr
        def foo(self) -> None:
            ...
        
        @capture_crashes_to_stderr(return_if_crashed=Ellipsis)
        def calculate_foo(self) -> Result:
            ...
    """
    def decorate(func: Callable[_P, _RT]) -> Callable[_P, Union[_RT, _RF]]:
        @wraps(func)
        @_mark_bulkhead_call
        def bulkhead_call(*args: _P.args, **kwargs: _P.kwargs) -> Union[_RT, _RF]:
            try:
                return func(*args, **kwargs)  # cr-traceback: ignore
            except BaseException as e:
                # Print traceback to assist in debugging in the terminal,
                # including ancestor callers of bulkhead_call
                _print_bulkhead_exception(e, is_error=True)
                
                # Abort.
                return return_if_crashed
        return bulkhead_call
    if func is None:
        return decorate
    else:
        return decorate(func)


def does_not_capture_crashes(func: Callable[_P, _R]) -> Callable[_P, _R]:
    """
    Explicitly marks functions that intentionally do not capture crashes,
    allowing them to bubble up to their caller.
    """
    return func


def _mark_bulkhead_call(bulkhead_call: Callable[_P, _R]) -> Callable[_P, _R]:
    bulkhead_call._captures_crashes = True  # type: ignore[attr-defined]
    return bulkhead_call


_ExtractedTraceback = List[traceback.FrameSummary]
_FixTbFunc = Callable[[_ExtractedTraceback, _ExtractedTraceback], _ExtractedTraceback]

def _print_bulkhead_exception(e: BaseException, *, is_error: bool=False, fix_tb: Optional[_FixTbFunc]=None) -> None:
    # Print traceback to assist in debugging in the terminal,
    # including ancestor callers of bulkhead_call
    err_file = sys.stderr
    print(
        cli.TERMINAL_FG_RED if is_error else cli.TERMINAL_FG_YELLOW,
        end='', file=err_file)
    if e.__traceback__ is not None:
        here_tb = traceback.extract_stack(sys._getframe(1))
        exc_tb = traceback.extract_tb(e.__traceback__)
        if fix_tb is None:
            fix_tb = lambda here_tb, exc_tb: here_tb[:-1] + exc_tb
        full_tb_summary = fix_tb(here_tb, exc_tb)  # type: _ExtractedTraceback
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
    Calls a function marked as @capture_crashes_to*,
    which does not reraise exceptions from its interior.
    
    Raises AssertionError if the specified function is not actually
    marked with @capture_crashes_to*.
    """
    ensure_is_bulkhead_call(bulkhead_call)
    return bulkhead_call(*args, **kwargs)  # cr-traceback: ignore


def ensure_is_bulkhead_call(callable: Callable) -> None:
    """
    Raises AssertionError if the specified function is not actually
    marked with @capture_crashes_to*.
    """
    if not is_bulkhead_call(callable):
        raise AssertionError(f'Expected callable {callable!r} to be decorated with @capture_crashes_to*')


def is_bulkhead_call(callable: Callable) -> bool:
    """
    Returns whether the specified function is marked with @capture_crashes_to*.
    """
    return getattr(callable, '_captures_crashes', False) == True


# ------------------------------------------------------------------------------