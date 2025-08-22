"""
Persists preferences related to Crystal itself, 
independent of any particular Project, or session where a project is opened.
"""

from collections.abc import Callable
from crystal.util.xappdirs import user_state_dir
import json
import os
import os.path
from typing import Any, Dict, Optional, cast


# NOTE: Use the `app_prefs` singleton instance rather than attempting
#       to instantiate this class directly.
class AppPreferences:
    def __init__(self, _ready: bool = False) -> None:
        if not _ready:
            raise ValueError(
                'Use the app_prefs singleton instance '
                'instead of creating a new AppPreferences() object')

    # === State Management ===
    
    def _get_state_filepath(self) -> str:
        # During tests, optionally disable persistence to avoid interfering with real app preferences
        if os.environ.get('CRYSTAL_NO_PERSIST_APP_PREFS', 'False') == 'True':
            # Return a temporary file path that won't affect real preferences
            import tempfile
            return os.path.join(tempfile.gettempdir(), 'crystal_test_app_preferences.json')
        return os.path.join(user_state_dir(), 'app_preferences.json')
    
    def _load_state(self) -> dict[str, Any]:
        state_filepath = self._get_state_filepath()
        if not os.path.exists(state_filepath):
            return {}
        
        try:
            with open(state_filepath, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            # If state file is corrupted or unreadable, start fresh
            return {}
    
    def _save_state(self, state: dict[str, Any]) -> None:
        state_filepath = self._get_state_filepath()
        try:
            with open(state_filepath, 'w', encoding='utf-8') as f:
                json.dump(state, f, indent=2)
        except OSError:
            # If we can't save state, continue silently.
            # The worst case is we lose some preferences.
            pass
    
    # === Properties ===
    
    @staticmethod
    def _define_property(
            prop_name: str,
            *, doc: str,
            validator: Callable[[Any], bool] | None = None,
            ) -> property:
        '''
        Defines a persistent app preferences property.
        
        Example:
            my_prop = cast(MyPropType, _define_property(
                'my_prop',
                doc=(
                    """
                    Documentation for my_prop.
                    """
                )
            ))
        '''
        def _get_property_value(self) -> Any:
            state = self._load_state()
            prop_value = state.get(prop_name)
            if prop_value is None:
                return None
            if validator is None:
                return prop_value
            return prop_value if validator(prop_value) else None
        def _set_property_value(self, prop_value: Any) -> None:
            state = self._load_state()
            state[prop_name] = prop_value
            self._save_state(state)
        def _clear_property_value(self) -> None:
            state = self._load_state()
            state.pop(prop_name, None)
            self._save_state(state)
        prop = property(
            fget=_get_property_value,
            fset=_set_property_value,
            fdel=_clear_property_value,
            doc=doc
        )
        return prop
    
    unsaved_untitled_project_path = cast(Optional[str], _define_property(
        'unsaved_untitled_project_path',
        validator=lambda project_path: (
            project_path is not None and 
            os.path.exists(project_path)
        ),
        doc=(
            """
            The path to the last untitled project that was opened
            which wasn't explicitly saved or closed without saving.
            Will be reopened automatically if Crystall unexpectedly quits.
            
            Returns None if Crystal was cleanly shut down.
            """
        )
    ))
    
    view_button_callout_dismissed = cast(bool, _define_property(
        'view_button_callout_dismissed',
        doc=(
            """
            Whether the View button callout has been permanently dismissed.
            
            The callout appears when there is exactly one root resource in a project
            to help users discover the View button functionality.
            """
        )
    ))


app_prefs = AppPreferences(_ready=True)  # singleton
