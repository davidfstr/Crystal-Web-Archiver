from unittest import skip

# === Create ===

@skip('not yet automated')
def test_when_drawer_created_then_displays_inside_parent() -> None:
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


# === Drag or Double-Click Sash ===

@skip('not yet automated')
def test_when_sash_dragged_then_drawer_height_changes() -> None:
    pass


@skip('not yet automated')
def test_given_drawer_open_when_sash_dragged_far_down_then_drawer_closes() -> None:
    pass


@skip('not yet automated')
def test_given_drawer_closed_when_sash_dragged_up_then_drawer_opens_and_drawer_height_changes() -> None:
    pass


@skip('not yet automated')
def test_when_sash_dragged_then_scrolls_drawer_to_bottom_iff_it_was_scrolled_to_bottom_before() -> None:
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
