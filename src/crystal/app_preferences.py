"""
Persists preferences related to Crystal itself, 
independent of any particular Project, or session where a project is opened.
"""

from collections.abc import Callable
from crystal.util.test_mode import tests_are_running
from crystal.util.xappdirs import user_state_dir
from functools import cache
import json
import os
import os.path
from tempfile import mkstemp
from typing import Any, Literal, Optional, cast


# NOTE: Use the `app_prefs` singleton instance rather than attempting
#       to instantiate this class directly.
class AppPreferences:
    """
    A persistent key-value store that contains app preferences.
    
    Every individual app preference value can be read/written using a property
    defined on this class.
    
    By default any change to app preferences is immediately written to disk.
    It is possible to opt-in to lower durability (for increased performance)
    by setting autoflush=False explicitly. Then callers must remember to
    eventually call flush() so that preferences are eventually written to disk.
    
    All properties of this class (including autoflush) do NOT report I/O
    errors to the caller by default, to make them easy to use in code that
    has no reasonable way of handling such errors.
    
    Methods that explicitly write preferences (notably flush) DO report I/O
    errors to the caller by default, since those callers are likely to want
    to know if writes fail.
    
    Methods that explicitly read preferences (notably sync) do NOT report I/O
    errors to the caller since there is no reasonable way for callers to
    recover. Instead, a fresh set of preferences will be loaded silently.
    """
    
    # Whether to log all side effects that occur during API calls
    _VERBOSE_EFFECTS = False
    
    def __init__(self, _ready: bool = False) -> None:
        if not _ready:
            raise ValueError(
                'Use the app_prefs singleton instance '
                'instead of creating a new AppPreferences() object')
        self._in_memory_state: dict[str, Any] | None = None
        self._is_dirty = False
        self._autoflush = True

    # === State Management ===
    
    # NOTE: The correctness of internal usage of mkstemp() relies on this caching 
    #       so that a consistent/non-changing filepath is reported to callers.
    @cache
    def _get_state_filepath(self) -> str:
        # Allow overriding the preferences file. Useful during automated tests.
        maybe_filepath = os.environ.get('CRYSTAL_PREFS_FILEPATH')
        if maybe_filepath is not None:
            return maybe_filepath
        
        # During tests, use isolated preferences to avoid interfering with real app preferences
        if tests_are_running():
            (_, filepath) = mkstemp(prefix=f'crystal_{os.getpid()}_prefs', suffix='.json')
            return filepath
        
        # Otherwise use the usual location
        return os.path.join(user_state_dir(), 'app_preferences.json')
    
    def _load_state(self) -> dict[str, Any]:
        """
        Loads on-disk preferences to in-memory, if not already done.
        
        If an I/O error occurs a fresh set of preferences will be loaded
        and the I/O error will not be reported to the caller.
        """
        # If we have an in-memory cache, use it
        if self._in_memory_state is not None:
            return self._in_memory_state
        
        # Otherwise load from disk
        if self._VERBOSE_EFFECTS:
            print('AppPreferences: I/O: Load from disk')
        state_filepath = self._get_state_filepath()
        if not os.path.exists(state_filepath):
            state = {}
        else:
            try:
                with open(state_filepath, 'r', encoding='utf-8') as f:
                    state = json.load(f)
            except (json.JSONDecodeError, OSError):
                # If state file is corrupted or unreadable, start fresh
                state = {}
        
        # Cache in memory
        self._in_memory_state = state
        self._is_dirty = False
        return state
    
    def _save_state(self, state: dict[str, Any], *, raise_on_error: bool=True) -> None:
        """
        Saves in-memory preferences to on-disk.
        
        By default if an I/O error occurs then that error will be raised to the caller.
        
        If the save is successful, the preferences will be marked non-dirty.
        """
        if self._VERBOSE_EFFECTS:
            print('AppPreferences: I/O: Save to disk')
        state_filepath = self._get_state_filepath()
        try:
            with open(state_filepath, 'w', encoding='utf-8') as f:
                json.dump(state, f, indent=2)
        except:
            if raise_on_error:
                raise
            else:
                pass
            pass
        else:
            # Clear dirty flag after successful save
            self._is_dirty = False
    
    def _mark_dirty_and_maybe_flush(self, *, flush: bool | None = None, raise_on_error: bool) -> None:
        """
        Marks the preferences as dirty (modified in memory but not yet saved to disk).
        `
        May immediately flush the preferences to disk, depending on the `flush`
        argument and `autoflush` configuration, which then reverts the preferences
        back to non-dirty before returning to the caller. 
        
        Arguments:
        * flush -- 
            If True, immediately flush to disk.
            If False, do not flush to disk.
            If None (default), use automatic behavior (flush if autoflush is True).
        """
        self._is_dirty = True
        
        # Decide whether to flush
        if flush is None:
            # Automatic behavior: flush if autoflush is enabled
            should_flush = self._autoflush
        else:
            # Explicit flush parameter
            should_flush = flush
        
        if should_flush:
            self.flush(raise_on_error=raise_on_error)
    
    def flush(self, *, raise_on_error: bool=True) -> None:
        """
        Flush any in-memory changes to disk if the preferences are dirty.
        
        By default raises if an I/O error occurs.
        
        Upon a successful flush the preferences will be marked as non-dirty.
        If the flush fails due to an I/O error, the preferences will be left marked dirty.
        
        Raises:
        * OSError -- if an I/O error occurs and raise_on_error=True
        """
        if self._is_dirty and self._in_memory_state is not None:
            self._save_state(self._in_memory_state, raise_on_error=raise_on_error)
    
    def sync(self, *, immediately: bool=True) -> None:
        """
        Read preferences from disk into memory. Immediately by default.
        
        This is useful when a different process may have modified the preferences
        and the current process needs to observe those changes.
        
        If an I/O error occurs a fresh set of preferences will be loaded
        and the I/O error will not be reported to the caller.
        
        Raises:
        * ValueError -- if the in-memory preferences are dirty before attempting to sync
        """
        if self._is_dirty:
            raise ValueError(
                'Cannot sync preferences from disk when in-memory preferences are dirty. '
                'Call flush() first to save changes, or reset() to discard them.'
            )
        
        # Clear in-memory cache to force reload from disk
        self._in_memory_state = None
        if immediately:
            # Force immediate load from disk
            # NOTE: Does not raise even on I/O errors. Loads fresh preferences in that case.
            self._load_state()
    
    def _get_autoflush(self) -> bool:
        return self._autoflush
    # NOTE: If we can't save state, continue silently by default.
    #       The worst case is we lose some preferences.
    def _set_autoflush(self, value: bool, *, raise_on_error: bool=False) -> None:
        self._autoflush = value
        if value and self._is_dirty:
            self.flush(raise_on_error=raise_on_error)
    autoflush = cast(bool, property(
        _get_autoflush,
        _set_autoflush,
        doc=(
            """
            Whether to automatically flush preferences to disk after each write operation.
            
            When True (default), preferences are immediately written to disk.
            When False, preferences are kept in memory and must be manually flushed.
            
            When True then is_dirty should never be observable as True by callers
            unless an I/O error prevents flushing to disk.
            
            If autoflush is set to True and the preferences are dirty
            then they will be immediately flushed to disk. If the flush fails
            then autoflush will remain set to True. If the flush fails
            and raise_on_error is explicitly set to True then an I/O error will
            be raised to the caller.
            
            Raises:
            * OSError -- if an I/O error occurs and raise_on_error=True
            """
        )
    ))
    
    def reset(self, *, flush: bool | None = None) -> None:
        """
        Resets preferences to their default state. Useful during automated tests.
        
        Arguments:
        * flush -- 
            If True, immediately flush to disk.
            If False, do not flush to disk.
            If None (default), use automatic behavior.
        """
        self._in_memory_state = {}
        # NOTE: If we can't save state, continue silently.
        #       The worst case is we lose some preferences.
        self._mark_dirty_and_maybe_flush(flush=flush, raise_on_error=False)
    
    # === Property Definitions ===
    
    @staticmethod
    def _define_property(
            prop_name: str,
            *, default: Any=None,
            doc: str,
            validator: Callable[[Any], bool] | None = None,
            ) -> property:
        '''
        Defines a persistent app preferences property.
        
        Example:
            my_prop = cast(MyPropType, _define_property(
                'my_prop',
                default=...,
                validator=lambda value: ...,
                doc=(
                    """
                    Documentation for my_prop.
                    """
                )
            ))
        '''
        def _get_property_value(self: 'AppPreferences') -> Any:
            state = self._load_state()
            if prop_name not in state:
                return default
            prop_value = state[prop_name]
            return (
                prop_value
                if validator is None or validator(prop_value)
                else default
            )
        def _set_property_value(self: 'AppPreferences', prop_value: Any, *, flush: bool | None = None) -> None:
            """
            Raises:
            * ValueError -- if the value is not valid for the property
            """
            state = self._load_state()
            if prop_name not in state or state[prop_name] != prop_value:
                prop_value_is_valid = validator is None or validator(prop_value)
                if not prop_value_is_valid:
                    raise ValueError(
                        f'Value {prop_value!r} for property {prop_name!r} '
                        f'is not valid')
                if self._VERBOSE_EFFECTS:
                    print(
                        f'AppPreferences: Property change: '
                        f'{prop_name}: '
                        f'{repr(state[prop_name]) if prop_name in state else "unset"} -> '
                        f'{repr(prop_value)}')
                state[prop_name] = prop_value
                # NOTE: If we can't save state, continue silently.
                #       The worst case is we lose some preferences.
                self._mark_dirty_and_maybe_flush(flush=flush, raise_on_error=False)
        def _clear_property_value(self: 'AppPreferences', *, flush: bool | None = None) -> None:
            state = self._load_state()
            if prop_name in state:
                if self._VERBOSE_EFFECTS:
                    print(f'AppPreferences: Property change: {prop_name}: {state.get(prop_name)!r} -> unset')
                state.pop(prop_name, None)
                # NOTE: If we can't save state, continue silently.
                #       The worst case is we lose some preferences.
                self._mark_dirty_and_maybe_flush(flush=flush, raise_on_error=False)
        prop = property(
            fget=_get_property_value,
            fset=_set_property_value,
            fdel=_clear_property_value,
            doc=doc
        )
        return prop
    
    def is_set(self, prop_name: str) -> bool:
        """Returns whether the specified property has been set to a value."""
        state = self._load_state()
        return prop_name in state
    
    # === Properties ===
    
    unsaved_untitled_project_path = cast(Optional[str], _define_property(
        'unsaved_untitled_project_path',
        default=None,
        validator=lambda project_path: (
            project_path is not None and 
            isinstance(project_path, str) and
            os.path.exists(project_path)
        ),
        doc=(
            """
            The path to the last untitled project that was opened
            which wasn't explicitly saved or closed without saving.
            Will be reopened automatically if Crystal unexpectedly quits.
            
            Returns None if Crystal was cleanly shut down.
            """
        )
    ))
    
    view_button_callout_dismissed = cast(bool, _define_property(
        'view_button_callout_dismissed',
        default=False,
        validator=lambda value: isinstance(value, bool),
        doc=(
            """
            Whether the View button callout has been permanently dismissed.
            
            The callout appears when there is exactly one root resource in a project
            to help users discover the View button functionality.
            """
        )
    ))
    
    proxy_type = cast(Literal['none', 'socks5'], _define_property(
        'proxy_type',
        default='none',
        validator=lambda pt: pt in ['none', 'socks5'],
        doc=(
            """
            The type of proxy to use for network connections.
            
            Valid values:
            - 'none': No proxy
            - 'socks5': SOCKS5 proxy
            
            Returns 'none' if not set or invalid.
            """
        )
    ))
    
    socks5_proxy_host = cast(str, _define_property(
        'socks5_proxy_host',
        default='localhost',
        validator=lambda host: isinstance(host, str) and host.strip() != '',
        doc=(
            """
            The hostname or IP address of the SOCKS5 proxy server.
            
            Only used when proxy_type is 'socks5'.
            """
        )
    ))
    socks5_proxy_host_is_set = property(lambda self: self.is_set('socks5_proxy_host'))
    
    socks5_proxy_port = cast(int, _define_property(
        'socks5_proxy_port',
        default=1080,
        validator=lambda port: isinstance(port, int) and 1 <= port <= 65535,
        doc=(
            """
            The port number of the SOCKS5 proxy server.
            
            Only used when proxy_type is 'socks5'.
            Must be between 1 and 65535.
            """
        )
    ))
    socks5_proxy_port_is_set = property(lambda self: self.is_set('socks5_proxy_port'))


app_prefs = AppPreferences(_ready=True)  # singleton
