"""Area VII -- UI / Textual headless tests, driven via `Pilot`."""
from __future__ import annotations

import pytest
from textual.widgets import DataTable, Input

from app import (
    ConfirmQuitScreen,
    CoverArtScreen,
    EditCellScreen,
    MatrixScreen,
    MersikApp,
    PromptScreen,
    SaveDiffScreen,
    disc_color,
    PALETTE,
)

pytestmark = pytest.mark.asyncio


# ---- empty state / table construction ------------------------------------


async def test_empty_state_shown(temp_empty_dir):
    app = MersikApp(temp_empty_dir)
    async with app.run_test():
        table = app.screen.query_one("#matrix", DataTable)
        empty = app.screen.query_one("#empty_state")
        assert table.display is False
        assert empty.display is not False
        assert "No .flac files" in str(empty.render())


async def test_table_rebuilt_with_columns(temp_flac_dir):
    app = MersikApp(temp_flac_dir)
    async with app.run_test():
        table = app.screen.query_one("#matrix", DataTable)
        assert table.row_count == 2
        assert len(table.columns) > 1  # disc gutter + tag columns


async def test_disc_column_rendered_with_color():
    assert disc_color(1) == PALETTE[0]
    assert disc_color(len(PALETTE) + 1) == PALETTE[0]  # wraps


async def test_pinned_column_has_label(temp_flac_dir):
    app = MersikApp(temp_flac_dir)
    async with app.run_test():
        screen = app.screen
        labels = [str(col.label) for col in screen.query_one("#matrix", DataTable).columns.values()]
        assert any("pinned" in label for label in labels)


async def test_truncate_long_values():
    long_value = "x" * 60
    truncated = MatrixScreen._truncate(long_value)
    assert len(truncated) == MatrixScreen.MAX_CELL_WIDTH
    assert truncated.endswith("…")


async def test_current_track_returns_track(temp_flac_dir):
    app = MersikApp(temp_flac_dir)
    async with app.run_test():
        screen = app.screen
        track = screen.current_track()
        assert track is not None
        assert track in app.model.tracks


async def test_current_column_returns_column(temp_flac_dir):
    app = MersikApp(temp_flac_dir)
    async with app.run_test() as pilot:
        screen = app.screen
        table = screen.query_one("#matrix", DataTable)
        table.cursor_coordinate = (0, 1)  # first real column, past disc gutter
        await pilot.pause()
        col = screen.current_column()
        assert col is not None
        assert col in app.model.columns


# ---- editing cells --------------------------------------------------------


async def test_edit_cell_pinned_broadcasts(temp_flac_dir):
    app = MersikApp(temp_flac_dir)
    async with app.run_test() as pilot:
        screen = app.screen
        pinned_col = next(c for c in app.model.columns if c.pinned)
        col_index = 1 + app.model.columns.index(pinned_col)
        table = screen.query_one("#matrix", DataTable)
        table.cursor_coordinate = (0, col_index)
        await pilot.pause()
        await pilot.press("i")
        await pilot.pause()
        inp = app.screen.query_one("#edit_input", Input)
        inp.value = "Broadcast Value"
        await pilot.press("enter")
        await pilot.pause()
        for t in app.model.tracks:
            assert t.slots[pinned_col.id] == "Broadcast Value"


async def test_edit_cell_unpinned_single(temp_flac_dir):
    app = MersikApp(temp_flac_dir)
    async with app.run_test() as pilot:
        screen = app.screen
        unpinned_col = next(c for c in app.model.columns if not c.pinned)
        col_index = 1 + app.model.columns.index(unpinned_col)
        table = screen.query_one("#matrix", DataTable)
        table.cursor_coordinate = (0, col_index)
        await pilot.pause()
        target_track = screen.current_track()
        await pilot.press("i")
        await pilot.pause()
        inp = app.screen.query_one("#edit_input", Input)
        inp.value = "Only Me"
        await pilot.press("enter")
        await pilot.pause()
        assert target_track.slots[unpinned_col.id] == "Only Me"
        others = [t for t in app.model.tracks if t is not target_track]
        assert all(t.slots.get(unpinned_col.id) != "Only Me" for t in others)


# ---- column mutation keybinds ---------------------------------------------


async def test_add_column_prompts(temp_flac_dir):
    app = MersikApp(temp_flac_dir)
    async with app.run_test() as pilot:
        await pilot.press("a")
        await pilot.pause()
        assert isinstance(app.screen, PromptScreen)


async def test_duplicate_column_works(temp_flac_dir):
    app = MersikApp(temp_flac_dir)
    async with app.run_test() as pilot:
        table = app.screen.query_one("#matrix", DataTable)
        table.cursor_coordinate = (0, 1)  # cursor starts on the disc gutter
        await pilot.pause()               # (col 0), which has no Column
        before = len(app.model.columns)
        await pilot.press("d")
        await pilot.pause()
        assert len(app.model.columns) == before + 1


async def test_delete_column_works(temp_flac_dir):
    app = MersikApp(temp_flac_dir)
    async with app.run_test() as pilot:
        table = app.screen.query_one("#matrix", DataTable)
        table.cursor_coordinate = (0, 1)
        await pilot.pause()
        before = len(app.model.columns)
        await pilot.press("x")
        await pilot.pause()
        assert len(app.model.columns) == before - 1


async def test_toggle_pin_works(temp_flac_dir):
    app = MersikApp(temp_flac_dir)
    async with app.run_test() as pilot:
        table = app.screen.query_one("#matrix", DataTable)
        unpinned_col = next(c for c in app.model.columns if not c.pinned)
        col_index = 1 + app.model.columns.index(unpinned_col)
        table.cursor_coordinate = (0, col_index)
        await pilot.pause()
        await pilot.press("p")
        await pilot.pause()
        assert unpinned_col.pinned is True


# ---- row / disc keybinds --------------------------------------------------


async def test_move_row_works(temp_multidisc_dir):
    app = MersikApp(temp_multidisc_dir)
    async with app.run_test() as pilot:
        first_in_disc1 = app.model.tracks_in_disc(1)[0]
        table = app.screen.query_one("#matrix", DataTable)
        table.cursor_coordinate = (0, 0)
        await pilot.pause()
        await pilot.press("shift+j")
        await pilot.pause()
        assert app.model.tracks_in_disc(1)[1] is first_in_disc1


async def test_change_disc_works(temp_flac_dir):
    app = MersikApp(temp_flac_dir)
    async with app.run_test() as pilot:
        table = app.screen.query_one("#matrix", DataTable)
        table.cursor_coordinate = (0, 0)
        await pilot.pause()
        track = app.screen.current_track()
        original_disc = track.disc
        await pilot.press("plus")
        await pilot.pause()
        assert track.disc == original_disc + 1


async def test_auto_number_works(temp_multidisc_dir):
    app = MersikApp(temp_multidisc_dir)
    async with app.run_test() as pilot:
        await pilot.press("n")
        await pilot.pause()
        assert all(t.computed_tracknumber is not None for t in app.model.tracks)


# ---- search ----------------------------------------------------------------


async def test_search_prompts(temp_flac_dir):
    app = MersikApp(temp_flac_dir)
    async with app.run_test() as pilot:
        await pilot.press("slash")
        await pilot.pause()
        assert isinstance(app.screen, PromptScreen)


async def test_search_jumps_to_match(temp_flac_dir):
    app = MersikApp(temp_flac_dir)
    async with app.run_test() as pilot:
        table = app.screen.query_one("#matrix", DataTable)
        table.cursor_coordinate = (0, 0)
        await pilot.pause()
        await pilot.press("slash")
        await pilot.pause()
        inp = app.screen.query_one("#prompt_input", Input)
        # NOTE: both tracks share DATE "2020", which itself contains "02"
        # as a substring -- querying "02" would match track 01 immediately
        # via include_current=True. "song two" is specific to track 02.
        inp.value = "song two"
        await pilot.press("enter")
        await pilot.pause()
        row_key = table.coordinate_to_cell_key(table.cursor_coordinate).row_key.value
        track = app.screen._track_by_rowkey[row_key]
        assert track.filename == "02.flac"


async def test_search_wrap(temp_flac_dir):
    app = MersikApp(temp_flac_dir)
    async with app.run_test() as pilot:
        table = app.screen.query_one("#matrix", DataTable)
        # Start on the last row and search for something on the first.
        table.cursor_coordinate = (table.row_count - 1, 0)
        await pilot.pause()
        await pilot.press("slash")
        await pilot.pause()
        inp = app.screen.query_one("#prompt_input", Input)
        inp.value = "01"
        await pilot.press("enter")
        await pilot.pause()
        row_key = table.coordinate_to_cell_key(table.cursor_coordinate).row_key.value
        track = app.screen._track_by_rowkey[row_key]
        assert "01" in track.filename


# ---- save flow --------------------------------------------------------------


async def test_save_prompts(temp_flac_dir):
    app = MersikApp(temp_flac_dir)
    async with app.run_test() as pilot:
        await pilot.press("w")
        await pilot.pause()
        assert isinstance(app.screen, SaveDiffScreen)


async def test_save_confirm(temp_flac_dir):
    app = MersikApp(temp_flac_dir)
    async with app.run_test() as pilot:
        table = app.screen.query_one("#matrix", DataTable)
        unpinned_col = next(c for c in app.model.columns if not c.pinned)
        col_index = 1 + app.model.columns.index(unpinned_col)
        table.cursor_coordinate = (0, col_index)
        await pilot.pause()
        await pilot.press("i")
        await pilot.pause()
        inp = app.screen.query_one("#edit_input", Input)
        inp.value = "Saved Value"
        await pilot.press("enter")
        await pilot.pause()

        matrix_screen = app.screen
        await pilot.press("w")
        await pilot.pause()
        assert isinstance(app.screen, SaveDiffScreen)
        await pilot.press("y")
        await pilot.pause()
        assert app.screen is matrix_screen
        assert not app.model.has_unsaved_changes()


async def test_save_cancel(temp_flac_dir):
    app = MersikApp(temp_flac_dir)
    async with app.run_test() as pilot:
        table = app.screen.query_one("#matrix", DataTable)
        unpinned_col = next(c for c in app.model.columns if not c.pinned)
        col_index = 1 + app.model.columns.index(unpinned_col)
        table.cursor_coordinate = (0, col_index)
        await pilot.pause()
        await pilot.press("i")
        await pilot.pause()
        inp = app.screen.query_one("#edit_input", Input)
        inp.value = "Unsaved Value"
        await pilot.press("enter")
        await pilot.pause()

        await pilot.press("w")
        await pilot.pause()
        await pilot.press("n")
        await pilot.pause()
        assert app.model.has_unsaved_changes()


# ---- quit flow ---------------------------------------------------------------


async def test_quit_no_changes_exits(temp_flac_dir):
    app = MersikApp(temp_flac_dir)
    async with app.run_test() as pilot:
        await pilot.press("q")
        await pilot.pause()
        assert not app.is_running or app._exit


async def test_quit_with_changes_prompts(temp_flac_dir):
    app = MersikApp(temp_flac_dir)
    async with app.run_test() as pilot:
        table = app.screen.query_one("#matrix", DataTable)
        unpinned_col = next(c for c in app.model.columns if not c.pinned)
        col_index = 1 + app.model.columns.index(unpinned_col)
        table.cursor_coordinate = (0, col_index)
        await pilot.pause()
        await pilot.press("i")
        await pilot.pause()
        inp = app.screen.query_one("#edit_input", Input)
        inp.value = "Dirty"
        await pilot.press("enter")
        await pilot.pause()

        await pilot.press("q")
        await pilot.pause()
        assert isinstance(app.screen, ConfirmQuitScreen)


async def test_quit_cancelled(temp_flac_dir):
    app = MersikApp(temp_flac_dir)
    async with app.run_test() as pilot:
        table = app.screen.query_one("#matrix", DataTable)
        unpinned_col = next(c for c in app.model.columns if not c.pinned)
        col_index = 1 + app.model.columns.index(unpinned_col)
        table.cursor_coordinate = (0, col_index)
        await pilot.pause()
        await pilot.press("i")
        await pilot.pause()
        inp = app.screen.query_one("#edit_input", Input)
        inp.value = "Dirty"
        await pilot.press("enter")
        await pilot.pause()

        matrix_screen = app.screen
        await pilot.press("q")
        await pilot.pause()
        await pilot.press("n")
        await pilot.pause()
        assert app.screen is matrix_screen
        assert app.is_running


# ---- cover art page -----------------------------------------------------------


async def test_cover_art_info_shown(temp_flac_dir):
    app = MersikApp(temp_flac_dir)
    async with app.run_test() as pilot:
        await pilot.press("c")
        await pilot.pause()
        info = app.screen.query_one("#art_info")
        assert "Track 1" in str(info.render())


async def test_cover_art_no_art_hidden(temp_flac_dir):
    app = MersikApp(temp_flac_dir)
    async with app.run_test() as pilot:
        await pilot.press("c")
        await pilot.pause()
        screen: CoverArtScreen = app.screen
        # ordered_tracks()[0] is "01.flac", which has cover art in the
        # fixture -- move to "02.flac" (index 1), which has none.
        screen.index = 1
        screen.refresh_info()
        preview = screen.query_one("#art_preview")
        assert preview.styles.display == "none"


async def test_cover_art_with_art(temp_flac_dir):
    app = MersikApp(temp_flac_dir)
    async with app.run_test() as pilot:
        await pilot.press("c")
        await pilot.pause()
        preview = app.screen.query_one("#art_preview")
        assert preview.styles.display == "block"


async def test_cover_art_left_right(temp_flac_dir):
    app = MersikApp(temp_flac_dir)
    async with app.run_test() as pilot:
        await pilot.press("c")
        await pilot.pause()
        screen: CoverArtScreen = app.screen
        start_index = screen.index
        await pilot.press("right")
        await pilot.pause()
        assert screen.index == start_index + 1


async def test_cover_art_apply_all(temp_flac_dir):
    app = MersikApp(temp_flac_dir)
    async with app.run_test() as pilot:
        await pilot.press("c")
        await pilot.pause()
        screen: CoverArtScreen = app.screen
        screen.index = 0  # "01.flac" has embedded art in the fixture
        screen.refresh_info()
        await pilot.press("shift+a")
        await pilot.pause()
        assert all(t.cover_art is not None for t in app.model.tracks)


async def test_cover_art_apply_all_no_cover(temp_flac_dir):
    app = MersikApp(temp_flac_dir)
    async with app.run_test() as pilot:
        await pilot.press("c")
        await pilot.pause()
        screen: CoverArtScreen = app.screen
        screen.index = 1  # "02.flac" has no embedded art
        screen.refresh_info()
        before = [t.cover_art for t in app.model.tracks]
        await pilot.press("shift+a")
        await pilot.pause()
        after = [t.cover_art for t in app.model.tracks]
        assert before == after


async def test_cover_art_back(temp_flac_dir):
    app = MersikApp(temp_flac_dir)
    async with app.run_test() as pilot:
        matrix_screen = app.screen
        await pilot.press("c")
        await pilot.pause()
        assert isinstance(app.screen, CoverArtScreen)
        await pilot.press("escape")
        await pilot.pause()
        assert app.screen is matrix_screen


# ---- modal dismiss semantics ----------------------------------------------


async def test_prompt_dismiss_value(temp_flac_dir):
    app = MersikApp(temp_flac_dir)
    async with app.run_test() as pilot:
        result = {}

        def handle(value):
            result["value"] = value

        app.push_screen(PromptScreen("test:"), handle)
        await pilot.pause()
        inp = app.screen.query_one("#prompt_input", Input)
        inp.value = "hello"
        await pilot.press("enter")
        await pilot.pause()
        assert result["value"] == "hello"


async def test_prompt_dismiss_none(temp_flac_dir):
    app = MersikApp(temp_flac_dir)
    async with app.run_test() as pilot:
        result = {"called": False, "value": "sentinel"}

        def handle(value):
            result["called"] = True
            result["value"] = value

        app.push_screen(PromptScreen("test:"), handle)
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()
        assert result["called"] is True
        assert result["value"] is None


async def test_edit_cell_screen_dismiss_value(temp_flac_dir):
    app = MersikApp(temp_flac_dir)
    async with app.run_test() as pilot:
        result = {}
        app.push_screen(EditCellScreen("KEY", "old"), lambda v: result.update(value=v))
        await pilot.pause()
        inp = app.screen.query_one("#edit_input", Input)
        inp.value = "new"
        await pilot.press("enter")
        await pilot.pause()
        assert result["value"] == "new"


async def test_edit_cell_screen_dismiss_none(temp_flac_dir):
    app = MersikApp(temp_flac_dir)
    async with app.run_test() as pilot:
        result = {"value": "sentinel"}
        app.push_screen(EditCellScreen("KEY", "old"), lambda v: result.update(value=v))
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()
        assert result["value"] is None


async def test_save_diff_shows_changes(temp_flac_dir):
    app = MersikApp(temp_flac_dir)
    async with app.run_test() as pilot:
        unpinned_col = next(c for c in app.model.columns if not c.pinned)
        app.model.tracks[0].slots[unpinned_col.id] = "Changed"
        await pilot.press("w")
        await pilot.pause()
        body_text = " ".join(str(lbl.render()) for lbl in app.screen.query("#body Label"))
        assert "Changed" in body_text


async def test_save_diff_no_changes(temp_flac_dir):
    app = MersikApp(temp_flac_dir)
    async with app.run_test() as pilot:
        await pilot.press("w")
        await pilot.pause()
        body_text = " ".join(str(lbl.render()) for lbl in app.screen.query("#body Label"))
        assert "No changes staged." in body_text


async def test_confirm_quit_dismiss(temp_flac_dir):
    app = MersikApp(temp_flac_dir)
    async with app.run_test() as pilot:
        result = {}
        app.push_screen(ConfirmQuitScreen("msg"), lambda v: result.update(value=v))
        await pilot.pause()
        await pilot.press("y")
        await pilot.pause()
        assert result["value"] is True
