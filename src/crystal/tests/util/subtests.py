from collections.abc import Awaitable, Callable, Iterator
from contextlib import contextmanager
from functools import wraps
from io import StringIO
import traceback
from unittest import SkipTest

# ------------------------------------------------------------------------------
# Utility: Subtests

class SubtestsContext:
    def __init__(self, test_name: str) -> None:
        self._test_name = test_name
        self._report = StringIO()
    
    # TODO: Allow with-statement to be used on SubtestsContext directly,
    #       eliminating the need to call run() in the API.
    @contextmanager
    def run(self) -> 'Iterator[SubtestsContext]':
        raised_exc = True
        try:
            yield self
            raised_exc = False
        except _SubtestReturn:
            raised_exc = False
        finally:
            subtest_report = self._report.getvalue()
            self._report.close()
            if len(subtest_report) != 0:
                print(subtest_report, end='')
                print('-' * 70)
                if not raised_exc:
                    raise SubtestFailed()
    
    @contextmanager
    def test(self, msg: str | None=None, **kwargs: object) -> Iterator[None]:
        """
        Context in which a subtest runs.
        
        The subtest is in failure output by its `msg`, `kwargs`, or both.
        
        If an exception is raised within a subtest context,
        by default the context is exited but the parent test continues
        executing after the context. If you want the parent test to
        exit instead, pass return_if_failure=True.
        
        Arguments:
        * msg --
            (Optional) Identifies this subtest in output.
        * return_if_failure --
            (Optional) Whether to return if an exception is raised in this context.
            Defaults to False.
        * kwargs --
            (Optional) Identifies this subtest in output.
        """
        if msg is None and len(kwargs) == 0:
            raise ValueError()
        return_if_failure = bool(kwargs.pop('return_if_failure', False))
        
        try:
            yield
        except Exception as e:
            if isinstance(e, AssertionError):
                exc_category = 'FAILURE'
                exc_traceback_useful = True
            elif isinstance(e, SkipTest):
                exc_category = 'SKIP'
                exc_traceback_useful = False
            else:
                exc_category = 'ERROR'
                exc_traceback_useful = True
            
            subtest_name_parts = [f'[{msg}] '] if msg is not None else []
            for (k, v) in kwargs.items():
                subtest_name_parts.append(f'({k}={v!r}) ')
            subtest_name = ''.join(subtest_name_parts).rstrip()
            
            print('- ' * (70 // 2), file=self._report)
            print(f'SUBTEST: {self._test_name} {subtest_name}', file=self._report)
            print('. ' * (70 // 2), file=self._report)
            if exc_traceback_useful:
                traceback.print_exc(file=self._report)
            print(exc_category, file=self._report)
            
            if return_if_failure:
                raise _SubtestReturn()
        else:
            # Passed. No output.
            pass


class _SubtestReturn(BaseException):
    pass


class SubtestFailed(Exception):
    def __init__(self) -> None:
        super().__init__('Subtest failed')


def with_subtests(test_func: Callable[[SubtestsContext], None]) -> Callable[[], None]:
    """Decorates a test function which can use subtests."""
    test_func_id = (test_func.__module__, test_func.__name__)
    test_name = f'{test_func_id[0]}.{test_func_id[1]}'
    
    subtests = SubtestsContext(test_name)
    
    @wraps(test_func)
    def wrapper():
        with subtests.run():
            test_func(subtests)
    return wrapper


def awith_subtests(test_func: Callable[[SubtestsContext], Awaitable[None]]) -> Callable[[], Awaitable[None]]:
    """Decorates a test function which can use subtests."""
    test_func_id = (test_func.__module__, test_func.__name__)
    test_name = f'{test_func_id[0]}.{test_func_id[1]}'
    
    subtests = SubtestsContext(test_name)
    
    @wraps(test_func)
    async def wrapper():
        raised_exc = True
        try:
            await test_func(subtests)
            raised_exc = False
        except _SubtestReturn:
            raised_exc = False
        finally:
            subtest_report = subtests._report.getvalue()
            if len(subtest_report) != 0:
                print(subtest_report, end='')
                print('-' * 70)
                if not raised_exc:
                    raise Exception('Subtests did fail')
    return wrapper


# ------------------------------------------------------------------------------