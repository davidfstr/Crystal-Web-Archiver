"""
Locates user-specific Crystal state directories,
building on the `appdirs` library.
"""

import appdirs
from crystal import APP_AUTHOR, APP_NAME
import os


def user_log_dir() -> str:
    """
    Get the directory where application logs should be stored.
    """
    log_dir = appdirs.user_log_dir(APP_NAME, APP_AUTHOR)
    os.makedirs(log_dir, exist_ok=True)
    return log_dir


def user_data_dir() -> str:
    """
    Get the directory where application data should be stored.
    """
    data_dir = appdirs.user_data_dir(APP_NAME, APP_AUTHOR)
    os.makedirs(data_dir, exist_ok=True)
    return data_dir


def user_untitled_projects_dir() -> str:
    """
    Get the directory where untitled projects should be stored.
    
    This directory is permanent (not in a temporary location) but hidden
    from normal user browsing.
    
    Returns the absolute path to the directory, creating it if necessary.
    """
    untitled_projects_dir = os.path.join(user_data_dir(), 'UntitledProjects')
    os.makedirs(untitled_projects_dir, exist_ok=True)
    return untitled_projects_dir


def user_state_dir() -> str:
    """
    Get the directory where application state should be stored.
    
    This includes things like the last untitled project path and other
    application-level state that should persist across app restarts.
    
    Returns the absolute path to the directory, creating it if necessary.
    """
    state_dir = appdirs.user_state_dir(APP_NAME, APP_AUTHOR)
    os.makedirs(state_dir, exist_ok=True)
    return state_dir
