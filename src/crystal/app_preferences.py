"""
Persists preferences related to Crystal itself, 
independent of any particular Project, or session where a project is opened.
"""

from crystal.util.xappdirs import user_state_dir
import json
import os
import os.path
from typing import Dict, Optional, cast


# NOTE: Use the `app_prefs` singleton instance rather than attempting
#       to instantiate this class directly.
class AppPreferences:
    _STATE_FILENAME = 'unsaved_project.json'
    
    def __init__(self, _ready: bool = False) -> None:
        if not _ready:
            raise ValueError(
                'Use the app_prefs singleton instance '
                'instead of creating a new AppPreferences() object')

    # === State Management ===
    
    def _get_state_filepath(self) -> str:
        return os.path.join(user_state_dir(), self._STATE_FILENAME)
    
    def _load_state(self) -> Dict:
        state_filepath = self._get_state_filepath()
        if not os.path.exists(state_filepath):
            return {}
        
        try:
            with open(state_filepath, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            # If state file is corrupted or unreadable, start fresh
            return {}
    
    def _save_state(self, state: Dict) -> None:
        state_filepath = self._get_state_filepath()
        try:
            with open(state_filepath, 'w', encoding='utf-8') as f:
                json.dump(state, f, indent=2)
        except OSError:
            # If we can't save state, continue silently.
            # The worst case is we lose some preferences.
            pass
    
    # === Properties ===
    
    def _get_unsaved_untitled_project_path(self) -> Optional[str]:
        state = self._load_state()
        last_project_path = state.get('unsaved_untitled_project_path')
        if last_project_path is not None and os.path.exists(last_project_path):
            return last_project_path
        else:
            return None
    def _set_unsaved_untitled_project_path(self, project_path: str) -> None:
        state = self._load_state()
        state['unsaved_untitled_project_path'] = project_path
        self._save_state(state)
    def _clear_unsaved_untitled_project_path(self) -> None:
        state = self._load_state()
        state.pop('unsaved_untitled_project_path', None)
        self._save_state(state)
    unsaved_untitled_project_path = cast(Optional[str], property(
        fget=_get_unsaved_untitled_project_path,
        fset=_set_unsaved_untitled_project_path,
        fdel=_clear_unsaved_untitled_project_path,
        doc=(
            """
            The path to the last untitled project that was opened
            which wasn't explicitly saved or closed without saving.
            Will be reopened automatically if Crystall unexpectedly quits.
            
            Returns None if Crystal was cleanly shut down.
            """
        )
    ))


app_prefs = AppPreferences(_ready=True)  # singleton
