import threading
from tqdm.std import TqdmDefaultWriteLock  # type: ignore[attr-defined]
import traceback
from typing import assert_never, Literal


def patch_tqdm_to_debug_deadlocks(on_deadlock: Literal['raise', 'keep_trying']='raise') -> None:
    """
    Patch tqdm to detect potential deadlocks when accessing its internal tqdm._lock.
    
    When a deadlock is detected a warning is printed and one of the following
    actions is taken, depending on the value of `on_deadlock`:
    * 'raise' - Raise an exception
    * 'keep_trying' - Keep trying to acquire the lock anyway.
    """
    TqdmDefaultWriteLock.th_lock_holders = []  # List[Tuple[threading.Thread, traceback.StackSummary]]
    
    def acquire(self, *a, **k):
        k_no_timeout = dict(k)
        if 'timeout' not in k:
            k['timeout'] = 5.0
        for lock in self.locks:
            ok = lock.acquire(*a, **k)
            if not ok:
                try:
                    lock_holder = TqdmDefaultWriteLock.th_lock_holders[-1]
                except IndexError:
                    lock_holder = ('<none>', ['<none>'])
                
                print(
                    f'*** TqdmDefaultWriteLock: Failed to acquire lock in '
                    f'{k["timeout"]} seconds. '
                    f'Lock holder is {lock_holder[0]} at:\n'
                    f'{"".join(lock_holder[1])}')
                print(f'*** New acquirer is:\n{"".join(traceback.format_stack())}')
                if on_deadlock == 'raise':
                    raise AssertionError('Failed to acquire TqdmDefaultWriteLock')
                elif on_deadlock == 'keep_trying':
                    print('*** Continuing to try acquiring lock anyway:')
                    lock.acquire(*a, **k_no_timeout)
                else:
                    assert_never(on_deadlock)
        
        TqdmDefaultWriteLock.th_lock_holders.append((
            threading.current_thread(),
            traceback.format_stack()
        ))
    TqdmDefaultWriteLock.acquire = acquire
    
    super_release = TqdmDefaultWriteLock.release
    def release(self, *args, **kwargs):
        TqdmDefaultWriteLock.th_lock_holders.pop()
        return super_release(self, *args, **kwargs)
    TqdmDefaultWriteLock.release = release
