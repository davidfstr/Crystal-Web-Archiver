"""
Tests the Callout control in callout.py
"""

from unittest import skip


@skip('not yet automated')
def test_callout_contains_message_and_close_button_and_dont_show_again_checkbox() -> None:
    pass


@skip('not yet automated')
def test_callout_appears_above_target_control_and_points_downward_to_center_of_target_control_with_triangle() -> None:
    pass


@skip('not yet automated')
def test_callout_repositions_to_point_to_target_control_when_ancestor_window_changes_size() -> None:
    pass


@skip('not yet automated')
def test_callout_background_and_control_colors_look_good_in_both_light_mode_and_dark_mode() -> None:
    # NOTE: Dark mode currently has the same appearance as light mode,
    #       since the same colors look good for both
    pass


@skip('not yet automated')
def test_callout_appearance_updates_correctly_when_system_appearance_changes_between_light_and_dark_mode() -> None:
    # NOTE: Dark mode currently has the same appearance as light mode,
    #       since the same colors look good for both
    pass


@skip('not yet automated')
def test_close_button_does_display_x_on_macos_and_windows_and_linux() -> None:
    # Linux: A larger close button is needed so that the X actually displays
    # Windows: A non-native GenButton is used for the close button
    pass


@skip('not yet automated')
def test_close_button_focus_state_looks_reasonable() -> None:
    # Windows: A custom focus state is implemented because the default
    #          GenButton focus state has a strange focus color
    pass
