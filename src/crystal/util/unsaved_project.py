"""
Tracks the last untitled project opened which wasn't explicitly saved or
closed without saving. This is used for determining whether Crystal quit
unexpectedly and where to find the project to reopen automatically when
Crystal launches again.
"""

from crystal.util.xappdirs import user_state_dir
import json
import os
import os.path
from typing import Dict, Optional


_STATE_FILENAME = 'unsaved_project.json'


def _get_state_filepath() -> str:
    """Get the path to the state file that tracks untitled project information."""
    return os.path.join(user_state_dir(), _STATE_FILENAME)


def _load_state() -> Dict:
    """Load the untitled project state from disk, returning empty dict if not found."""
    state_filepath = _get_state_filepath()
    if not os.path.exists(state_filepath):
        return {}
    
    try:
        with open(state_filepath, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        # If state file is corrupted or unreadable, start fresh
        return {}


def _save_state(state: Dict) -> None:
    """Save the untitled project state to disk."""
    state_filepath = _get_state_filepath()
    try:
        with open(state_filepath, 'w', encoding='utf-8') as f:
            json.dump(state, f, indent=2)
    except OSError:
        # If we can't save state, continue silently
        # The worst case is we don't auto-reopen next time
        pass


def get_unsaved_untitled_project_path() -> Optional[str]:
    """
    Gets the path to the last untitled project that was opened
    which wasn't explicitly saved or closed without saving.

    Returns None if Crystal was cleanly shut down.
    """
    state = _load_state()
    last_project_path = state.get('unsaved_untitled_project_path')
    if last_project_path is not None and os.path.exists(last_project_path):
        return last_project_path
    else:
        return None


def set_unsaved_untitled_project_path(project_path: str) -> None:
    """
    Records the path to the currently active untitled project,
    which hasn't been saved or closed yet.
    
    Also marks Crystal as not having quit cleanly yet.
    """
    state = _load_state()
    state['unsaved_untitled_project_path'] = project_path
    _save_state(state)


def clear_unsaved_untitled_project_path() -> None:
    """
    Clear the recorded untitled project path.
    
    This should be called when an untitled project is saved (becomes titled)
    or when an untitled project is explicitly closed without saving.
    """
    state = _load_state()
    state.pop('unsaved_untitled_project_path', None)
    _save_state(state)
