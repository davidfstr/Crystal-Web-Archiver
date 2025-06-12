from collections.abc import Iterator
from contextlib import contextmanager, redirect_stderr
from crystal.tests.util.subtests import SubtestsContext, with_subtests
from crystal.util.profile import (
    ignore_runtime_from_enclosing_warn_if_slow, warn_if_slow,
)
import gc
import io
from unittest.mock import patch


@with_subtests
def test_warn_if_slow_context_does_warn_appropriately(subtests: SubtestsContext) -> None:
    with _gc_disabled():
        with subtests.test(context_execution_time='fast'):
            with patch('time.time', side_effect=[0.0, 0.1]):
                with redirect_stderr(io.StringIO()) as captured_stderr:
                    with warn_if_slow(
                            'Inserting links',
                            max_duration=1.0,
                            message='1 link from https://xkcd.com/',
                            enabled=True):
                        pass
            assert '' == captured_stderr.getvalue(), \
                'Expected no warning to be printed for a fast-executing context'
        
        with subtests.test(context_execution_time='slow'):
            with patch('time.time', side_effect=[0.0, 1.1]):
                with redirect_stderr(io.StringIO()) as captured_stderr:
                    with warn_if_slow(
                            'Inserting links',
                            max_duration=1.0,
                            message='1 link from https://xkcd.com/',
                            enabled=True):
                        pass
            assert (
                '*** Inserting links took 1.10s to execute: 1 link from https://xkcd.com/\n' == 
                captured_stderr.getvalue()
            ), 'Expected a warning to be printed for a slow-executing context'


@with_subtests
def test_warn_if_slow_context_does_exclude_inner_context_runtime(subtests: SubtestsContext) -> None:
    with _gc_disabled():
        with subtests.test(nesting_level=1):
            with subtests.test(
                    inner_context_type='warn_if_slow'):
                with patch('time.time', side_effect=[0.0, 0.1, 1.2, 1.3]):
                    with redirect_stderr(io.StringIO()) as captured_stderr:
                        with warn_if_slow('Outer context', max_duration=1.0, message='Outer'):
                            with warn_if_slow('Inner context', max_duration=1.0, message='Inner'):
                                pass
                assert (
                    '*** Inner context took 1.10s to execute: Inner\n' == 
                    captured_stderr.getvalue()
                ), 'Expected a warning to be printed by inner context but not the outer context'
            
            with subtests.test(
                    inner_context_type='ignore_runtime_from_enclosing_warn_if_slow'):
                with patch('time.time', side_effect=[0.0, 0.1, 1.2, 1.3]):
                    with redirect_stderr(io.StringIO()) as captured_stderr:
                        with warn_if_slow('Outer context', max_duration=1.0, message='Outer'):
                            with ignore_runtime_from_enclosing_warn_if_slow():
                                pass
                assert (
                    '' == 
                    captured_stderr.getvalue()
                ), 'Expected no warning to be printed by outer context'
        
        with subtests.test(nesting_level=2):
            with subtests.test(
                    inner_context_type='warn_if_slow',
                    inner_inner_context_type='warn_if_slow'):
                with patch('time.time', side_effect=[0.0, 0.1, 0.2, 1.3, 1.4, 1.5]):
                    with redirect_stderr(io.StringIO()) as captured_stderr:
                        with warn_if_slow('Outer context', max_duration=1.0, message='Outer'):
                            with warn_if_slow('Inner context', max_duration=1.0, message='Inner'):
                                with warn_if_slow('Inner inner context', max_duration=1.0, message='Inner inner'):
                                    pass
                assert (
                    '*** Inner inner context took 1.10s to execute: Inner inner\n' == 
                    captured_stderr.getvalue()
                ), 'Expected a warning to be printed by inner inner context but not by any other context'
            
            with subtests.test(
                    inner_context_type='warn_if_slow',
                    inner_inner_context_type='ignore_runtime_from_enclosing_warn_if_slow'):
                with patch('time.time', side_effect=[0.0, 0.1, 0.2, 1.3, 1.4, 1.5]):
                    with redirect_stderr(io.StringIO()) as captured_stderr:
                        with warn_if_slow('Outer context', max_duration=1.0, message='Outer'):
                            with warn_if_slow('Inner context', max_duration=1.0, message='Inner'):
                                with ignore_runtime_from_enclosing_warn_if_slow():
                                    pass
                assert (
                    '' == 
                    captured_stderr.getvalue()
                ), 'Expected no warning to be printed by any context'


@contextmanager
def _gc_disabled() -> Iterator[None]:
    # Disable garbage collection because it uses time.time(),
    # and callers are mocking the use of time.time()
    gc.disable()
    try:
        yield
    finally:
        gc.enable()
