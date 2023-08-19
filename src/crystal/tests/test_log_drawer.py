from unittest import skip


# === Create ===

@skip('not yet automated')
def test_when_drawer_created_given_not_on_linux_and_parent_window_not_maximized_then_displays_below_parent() -> None:
    pass


@skip('not yet automated')
def test_when_drawer_created_given_not_on_linux_and_parent_window_maximized_then_displays_inside_parent() -> None:
    # Case 1: Given Windows OS
    # Case 2: Given macOS
    pass


@skip('not yet automated')
def test_when_drawer_created_given_on_linux_then_displays_inside_parent() -> None:
    pass


# === Drawer Text ===

@skip('not yet automated')
def test_when_write_colorized_text_to_writer_then_displays_colorized_text_in_drawer_and_in_stdout() -> None:
    pass


@skip('not yet automated')
def test_when_write_text_to_writer_then_scrolls_drawer_to_bottom_iff_it_was_scrolled_to_bottom_before() -> None:
    pass


@skip('not yet automated')
def test_can_select_and_copy_text_in_drawer() -> None:
    pass


@skip('not yet automated')
def test_cannot_edit_text_in_drawer() -> None:
    pass


@skip('not yet automated')
def test_always_displays_vertical_scrollbar_and_never_displays_horizontal_scrollbar() -> None:
    pass


# === Activate Self or Parent ===

@skip('not yet automated')
def test_given_drawer_out_of_parent_when_activate_drawer_then_both_drawer_and_parent_raise_above_all_other_windows() -> None:
    # Case 1: _WindowPairingStrategy.FLOAT_ON_PARENT is being used
    # Case 2: _WindowPairingStrategy.FLOAT_AND_RAISE_ON_ACTIVATE is being used
    pass


@skip('not yet automated')
def test_given_drawer_out_of_parent_when_activate_parent_of_drawer_then_both_parent_and_drawer_raise_above_all_other_windows() -> None:
    # Case 1: _WindowPairingStrategy.FLOAT_ON_PARENT is being used
    # Case 2: _WindowPairingStrategy.FLOAT_AND_RAISE_ON_ACTIVATE is being used
    pass


@skip('not yet automated')
def test_given_drawer_out_of_parent_when_activate_window_from_other_app_then_window_raises_above_both_drawer_and_parent() -> None:
    # Case A1: Drawer was directly below parent (in Z-order)
    # Case A2: Drawer was directly above parent (in Z-order)
    # 
    # Case B1: _WindowPairingStrategy.FLOAT_ON_PARENT is being used
    # Case B2: _WindowPairingStrategy.FLOAT_AND_RAISE_ON_ACTIVATE is being used
    pass

# === Reshape Parent ===

@skip('not yet automated')
def test_given_drawer_out_of_parent_when_parent_repositioned_then_drawer_is_repositioned_to_stay_attached_to_parent() -> None:
    pass


@skip('not yet automated')
def test_given_drawer_out_of_parent_when_parent_resized_then_drawer_is_repositioned_to_stay_attached_to_parent_and_resized_to_maintain_leading_and_trailing_offsets() -> None:
    pass


# === Drag Border or Edge ===

@skip('not yet automated')
def test_given_drawer_out_of_parent_when_drawer_north_edge_or_corner_dragged_then_only_width_changes_and_stays_centered_below_parent() -> None:
    pass


@skip('not yet automated')
def test_given_drawer_out_of_parent_when_drawer_south_edge_or_corner_dragged_then_size_changes_and_stays_centered_below_parent() -> None:
    pass


@skip('not yet automated')
def test_given_drawer_out_of_parent_when_drawer_south_edge_or_corner_dragged_far_up_then_drawer_closes() -> None:
    pass


@skip('not yet automated')
def test_given_drawer_out_of_parent_when_drawer_edge_or_corner_dragged_then_keeps_drawer_width_no_greater_than_parent_width() -> None:
    pass


@skip('not yet automated')
def test_given_drawer_out_of_parent_when_drawer_edge_or_corner_dragged_then_scrolls_drawer_to_bottom_iff_it_was_scrolled_to_bottom_before() -> None:
    pass


# === Drag or Double-Click Sash ===

@skip('not yet automated')
def test_when_sash_dragged_then_drawer_height_changes() -> None:
    pass


@skip('not yet automated')
def test_given_drawer_out_of_parent_and_drawer_open_when_sash_dragged_far_up_then_drawer_closes() -> None:
    pass


@skip('not yet automated')
def test_given_drawer_out_of_parent_and_drawer_closed_when_sash_dragged_down_then_drawer_opens_and_drawer_height_changes() -> None:
    pass


@skip('not yet automated')
def test_given_drawer_out_of_parent_when_sash_dragged_then_scrolls_drawer_to_bottom_iff_it_was_scrolled_to_bottom_before() -> None:
    pass


@skip('not yet automated')
def test_given_drawer_in_parent_and_drawer_open_when_sash_dragged_far_down_then_drawer_closes() -> None:
    pass


@skip('not yet automated')
def test_given_drawer_in_parent_and_drawer_closed_when_sash_dragged_up_then_drawer_opens_and_drawer_height_changes() -> None:
    pass


@skip('not yet automated')
def test_given_drawer_in_parent_when_sash_dragged_then_scrolls_drawer_to_bottom_iff_it_was_scrolled_to_bottom_before() -> None:
    pass


@skip('not yet automated')
def test_given_drawer_open_when_double_click_sash_then_drawer_closes() -> None:
    # Case A: Drawer is out of parent (unmaximized)
    # Case B: Drawer is in parent (maximized)
    pass


@skip('not yet automated')
def test_given_drawer_closed_when_double_click_sash_then_drawer_opens_to_last_used_height() -> None:
    # Case A: Drawer is out of parent (unmaximized)
    # Case B: Drawer is in parent (maximized)
    # Case 1: Drawer was closed by double-clicking the sash
    # Case 2: Drawer was closed by dragging the sash far up
    # Case 3: Drawer was closed by dragging the drawer's south edge/corner far up
    pass


# === Minimize or Unminimize Parent ===

@skip('not yet automated')
def test_given_drawer_out_of_parent_when_parent_of_drawer_minimized_then_drawer_hides() -> None:
    # Case 1: Given macOS
    # Case 2: Given Windows OS
    pass


@skip('not yet automated')
def test_given_drawer_out_of_parent_when_parent_of_drawer_unminimized_then_drawer_shows() -> None:
    # Case 1: Given macOS
    # Case 2: Given Windows OS
    pass


# === Maximize or Unmaximize Parent ===

@skip('not yet automated')
def test_given_not_linux_when_parent_of_drawer_maximized_then_drawer_moves_into_parent_and_closed_state_stays_same() -> None:
    # Case 1: Given Windows OS
    # Case 2: Given macOS
    pass


@skip('not yet automated')
def test_given_not_linux_when_parent_of_drawer_unmaximized_then_drawer_moves_out_of_parent_and_closed_state_stays_same() -> None:
    # Case 1: Given Windows OS
    # Case 2: Given macOS
    pass
