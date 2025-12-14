"""Utilities for detecting and working with AI agents."""

from crystal.util.test_mode import tests_are_running
import os


def ai_agent_detected() -> bool:
    """
    Returns whether it appears that an AI agent is running Crystal.
    
    The precise detection heuristic may change over time. Currently it is:
    - If CRYSTAL_AI_AGENT=True, an agent is assumed to be present.
    - If running in a VS Code terminal (where TERM_PROGRAM=vscode)
      AND tests are not running, an agent is assumed to be present.
    """
    if os.environ.get('CRYSTAL_AI_AGENT', 'False') in ['True', '1']:
        return True
    return (
        os.environ.get('TERM_PROGRAM') == 'vscode' and
        not tests_are_running()
    )
