import atexit
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager, nullcontext
import cProfile
from functools import wraps
import inspect
import sys
import threading
import time
from typing import Optional

_excluded_delta_time_stack = threading.local()

@contextmanager
def warn_if_slow(
        title: str,
        max_duration: float,
        message: Callable[[], str] | str,
        *, enabled: bool=True
        ) -> Iterator[None]:
    """
    Context that profiles the runtime of its enclosed code and
    upon exit prints a warning if the runtime exceeds the specified `max_duration`.
    
    If a warn_if_slow() context is nested within another warn_if_slow() context,
    the runtime of the inner context will be excluded from the runtime of the
    outer context.
    
    If a ignore_runtime_from_enclosing_warn_if_slow() context is nested within
    a warn_if_slow() context, the runtime of the inner context will be excluded
    from the runtime of the outer context.
    """
    if not enabled:
        yield
        return
    if not (max_duration > 0):
        raise ValueError()
    
    if not hasattr(_excluded_delta_time_stack, 'value'):
        _excluded_delta_time_stack.value = []
    _excluded_delta_time_stack.value.append(0)
    
    start_time = time.time()  # capture
    try:
        yield
    finally:
        end_time = time.time()  # capture
        
        excluded_delta_time = _excluded_delta_time_stack.value.pop()
        
        delta_time = end_time - start_time  # cache
        if (delta_time - excluded_delta_time) > max_duration:
            message_str = message() if callable(message) else message
            assert isinstance(message_str, str)
            excluded_part = (
                ' ({:.02f}s excluded)'.format(excluded_delta_time)
                if excluded_delta_time > 0
                else ''
            )
            print("*** {} took {:.02f}s{} to execute: {}".format(
                title,
                delta_time,
                excluded_part,
                message_str,
            ), file=sys.stderr)
            
            # Exclude delta_time from any enclosing calls of warn_if_slow()
            for (i, _) in enumerate(_excluded_delta_time_stack.value):
                _excluded_delta_time_stack.value[i] += delta_time


@contextmanager
def ignore_runtime_from_enclosing_warn_if_slow() -> Iterator[None]:
    """
    Context that excluded its runtime from that of any enclosing
    warn_if_slow() context.
    """
    if not hasattr(_excluded_delta_time_stack, 'value'):
        _excluded_delta_time_stack.value = []
    
    start_time = time.time()  # capture
    try:
        yield
    finally:
        end_time = time.time()  # capture
        delta_time = end_time - start_time  # cache
        
        # Exclude delta_time from any enclosing calls of warn_if_slow()
        for (i, _) in enumerate(_excluded_delta_time_stack.value):
            _excluded_delta_time_stack.value[i] += delta_time


def create_profiled_callable(title: str, max_duration: float, callable: Callable, *args) -> Callable:
    """
    Decorates the specified callable such that it prints
    a warning to the console if its runtime is long.
    """
    @wraps(callable)
    def profiled_callable() -> None:
        def message_func() -> str:
            # TODO: Remove support for nested callable objects that are
            #       tracked using a "callable" attribute. I believe this
            #       is dead code.
            root_callable = callable
            while hasattr(root_callable, 'callable'):
                root_callable = root_callable.callable  # type: ignore[attr-defined]
            
            try:
                file = inspect.getsourcefile(root_callable)
            except Exception:
                file = '?'
            try:
                start_line_number = str(inspect.getsourcelines(root_callable)[-1])
            except Exception:
                start_line_number = '?'
            return '{} @ [{}:{}]'.format(
                root_callable,
                file,
                start_line_number
            )
            
        with warn_if_slow(title, max_duration, message_func):
            return callable(*args)  # cr-traceback: ignore
    return profiled_callable


def create_profiling_context(
        stats_filepath: str,
        *, enabled: bool=True,
        ) -> 'AbstractContextManager[Optional[cProfile.Profile]]':
    """
    Creates a cProfile profiling context.
    Within the context all function calls are timed.
    The content can be entered and exited mutliple times.
    
    Just before the program exits, a .stats file is written to the specified
    filepath. This file can be analyzed/visualized with the PyPI "flameprof"
    module and the standard library "pstats" module.
    """
    if enabled:
        profiling_context = cProfile.Profile()  # type: AbstractContextManager[Optional[cProfile.Profile]]
        @atexit.register
        def dump_stats() -> None:  # type: ignore[misc]
            profiler = profiling_context
            assert isinstance(profiler, cProfile.Profile)
            profiler.dump_stats(stats_filepath)
    else:
        profiling_context = nullcontext(enter_result=None)
    return profiling_context
