"""Mersik2 - matrix-based FLAC tag editor."""
from __future__ import annotations

import sys
from pathlib import Path

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical, VerticalScroll
from textual.coordinate import Coordinate
from textual.screen import ModalScreen, Screen
from textual.widgets import DataTable, Footer, Header, Input, Label, Static
from textual_image.widget import Image as TermImage

from models import MatrixModel, Column, Track, sniff_mime

PALETTE = ["#f38ba8", "#a6e3a1", "#f9e2af", "#89b4fa", "#cba6f7", "#94e2d5"]


def disc_color(disc: int) -> str:
    return PALETTE[(disc - 1) % len(PALETTE)]


class PromptScreen(ModalScreen[str]):
    """Simple text-input modal, used for new column names."""

    DEFAULT_CSS = """
    PromptScreen {
        align: center middle;
    }
    #dialog {
        width: 50;
        height: auto;
        border: thick $accent;
        background: $panel;
        padding: 1 2;
    }
    """

    def __init__(self, prompt: str, initial: str = "") -> None:
        super().__init__()
        self.prompt = prompt
        self.initial = initial

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Label(self.prompt)
            yield Input(value=self.initial, id="prompt_input")

    def on_mount(self) -> None:
        self.query_one("#prompt_input", Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self.dismiss(event.value)

    def key_escape(self) -> None:
        self.dismiss(None)


class EditCellScreen(ModalScreen[str]):
    """Edit-mode input for a single cell, prefilled with current value."""

    DEFAULT_CSS = """
    EditCellScreen {
        align: center middle;
    }
    #dialog {
        width: 60;
        height: auto;
        border: thick $accent;
        background: $panel;
        padding: 1 2;
    }
    """

    def __init__(self, key_label: str, value: str) -> None:
        super().__init__()
        self.key_label = key_label
        self.value = value

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Label(f"Editing {self.key_label}")
            yield Input(value=self.value, id="edit_input")

    def on_mount(self) -> None:
        inp = self.query_one("#edit_input", Input)
        inp.focus()
        inp.cursor_position = len(inp.value)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self.dismiss(event.value)

    def key_escape(self) -> None:
        self.dismiss(None)


class SaveDiffScreen(ModalScreen[bool]):
    """Summary of pending changes before writing to disk."""

    DEFAULT_CSS = """
    SaveDiffScreen {
        align: center middle;
    }
    #dialog {
        width: 90%;
        height: 80%;
        border: thick $accent;
        background: $panel;
        padding: 1 2;
    }
    #body {
        height: 1fr;
    }
    #actions {
        height: auto;
        padding-top: 1;
    }
    """

    BINDINGS = [
        Binding("y", "confirm", "Confirm save"),
        Binding("n", "cancel", "Cancel"),
        Binding("escape", "cancel", "Cancel"),
    ]

    def __init__(self, model: MatrixModel) -> None:
        super().__init__()
        self.model = model

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Label("Save changes? (y = confirm, n/esc = cancel)")
            with VerticalScroll(id="body"):
                any_changes = False
                for track in self.model.ordered_tracks():
                    changes = self.model.diff_for_track(track)
                    if changes:
                        any_changes = True
                        yield Label(f"[b]{track.filename}[/b]")
                        for c in changes:
                            yield Label(f"  {c}")
                if not any_changes:
                    yield Label("No changes staged.")
            yield Label("", id="actions")

    def action_confirm(self) -> None:
        self.dismiss(True)

    def action_cancel(self) -> None:
        self.dismiss(False)


class ConfirmQuitScreen(ModalScreen[bool]):
    DEFAULT_CSS = """
    ConfirmQuitScreen {
        align: center middle;
    }
    #dialog {
        width: 60;
        height: auto;
        border: thick $error;
        background: $panel;
        padding: 1 2;
    }
    """

    BINDINGS = [
        Binding("y", "confirm", "Quit without saving"),
        Binding("n,escape", "cancel", "Cancel"),
    ]

    def __init__(self, message: str) -> None:
        super().__init__()
        self.message = message

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Label(self.message)
            yield Label("[y] quit without saving   [n/esc] cancel")

    def action_confirm(self) -> None:
        self.dismiss(True)

    def action_cancel(self) -> None:
        self.dismiss(False)


class MatrixScreen(Screen):
    BINDINGS = [
        Binding("i", "edit_cell", "Edit"),
        Binding("a", "add_column", "Add column"),
        Binding("d", "duplicate_column", "Duplicate column"),
        Binding("x", "delete_column", "Delete column"),
        Binding("n", "auto_number", "Auto-number"),
        Binding("shift+j,shift+down", "move_row(1)", "Move row down"),
        Binding("shift+k,shift+up", "move_row(-1)", "Move row up"),
        Binding("plus,equals_sign", "change_disc(1)", "Disc +"),
        Binding("minus", "change_disc(-1)", "Disc -"),
        Binding("shift+h,shift+left", "reorder_column(-1)", "Move column left"),
        Binding("shift+l,shift+right", "reorder_column(1)", "Move column right"),
        Binding("p", "toggle_pin", "Toggle pin"),
        Binding("z", "undo", "Undo"),
        Binding("y", "redo", "Redo"),
        Binding("w", "save", "Save"),
        Binding("s", "save", "Save"),
        Binding("c", "cover_art", "Cover art page"),
        Binding("q", "request_quit", "Quit"),
        Binding("slash", "search", "Search"),
        Binding("right_bracket", "search_next(1)", "Next match"),
        Binding("left_bracket", "search_next(-1)", "Previous match"),
    ]

    MAX_CELL_WIDTH = 40

    ROW_KEY_PREFIX = "row-"

    def __init__(self, model: MatrixModel) -> None:
        super().__init__()
        self.model = model
        self.last_search: str | None = None

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static("", id="empty_state")
        yield DataTable(id="matrix", cursor_type="cell", zebra_stripes=False)
        yield Footer()

    def on_mount(self) -> None:
        if not self.model.tracks:
            self.query_one("#matrix", DataTable).display = False
            self.query_one("#empty_state", Static).update(
                "No .flac files found in this folder (checked recursively). "
                "Nothing to edit here -- point mersik at a folder containing "
                "FLAC files and restart."
            )
            return
        self.query_one("#empty_state", Static).display = False
        self.rebuild_table()

    # -- table construction -------------------------------------------

    def rebuild_table(self, keep_cursor: tuple[int, int] | None = None) -> None:
        table = self.query_one("#matrix", DataTable)
        cursor = keep_cursor or (
            (table.cursor_row, table.cursor_column) if table.columns else (0, 0)
        )
        table.clear(columns=True)

        table.add_column("Disc", key="__disc__", width=6)
        for col in self.model.columns:
            label = col.key + (" [dim](pinned)[/dim]" if col.pinned else "")
            table.add_column(label, key=str(col.id), width=self.MAX_CELL_WIDTH + 2)

        for track in self.model.ordered_tracks():
            color = disc_color(track.disc)
            row: list[str] = [f"[{color}]D{track.disc}[/{color}]"]
            for col in self.model.columns:
                value = track.slots.get(col.id, "")
                row.append(self._truncate(value))
            table.add_row(*row, key=str(id(track)))

        self._track_by_rowkey = {str(id(t)): t for t in self.model.ordered_tracks()}
        self._col_by_id = {c.id: c for c in self.model.columns}

        if table.row_count:
            r = min(cursor[0], table.row_count - 1)
            c = min(cursor[1], len(table.columns) - 1)
            table.cursor_coordinate = Coordinate(r, c)

    def current_track(self) -> Track | None:
        table = self.query_one("#matrix", DataTable)
        if not table.row_count:
            return None
        row_key = table.coordinate_to_cell_key(table.cursor_coordinate).row_key.value
        return self._track_by_rowkey.get(row_key)

    def current_column(self) -> Column | None:
        table = self.query_one("#matrix", DataTable)
        if not table.columns:
            return None
        col_key = table.coordinate_to_cell_key(table.cursor_coordinate).column_key.value
        if col_key == "__disc__":
            return None
        return self._col_by_id.get(int(col_key))

    @classmethod
    def _truncate(cls, value: str) -> str:
        """Display-only truncation -- the underlying stored value in
        track.slots is never touched, so editing a cell always shows
        the full text regardless of how it's rendered here."""
        if len(value) <= cls.MAX_CELL_WIDTH:
            return value
        return value[: cls.MAX_CELL_WIDTH - 1] + "…"

    # -- search -----------------------------------------------------

    def _row_matches(self, track: Track, query: str) -> bool:
        query = query.lower()
        if query in track.filename.lower():
            return True
        for col in self.model.columns:
            if query in track.slots.get(col.id, "").lower():
                return True
        return False

    def _jump_to_row(self, row_index: int) -> None:
        table = self.query_one("#matrix", DataTable)
        table.cursor_coordinate = Coordinate(row_index, table.cursor_column)

    def action_search(self) -> None:
        if not self.model.tracks:
            return

        def handle(query: str | None) -> None:
            if not query:
                return
            self.last_search = query
            self._do_search(direction=1, include_current=True)

        self.app.push_screen(
            PromptScreen("Search (filename or any tag value):", initial=self.last_search or ""),
            handle,
        )

    def action_search_next(self, direction: int) -> None:
        if not self.last_search:
            self.action_search()
            return
        self._do_search(direction=direction, include_current=False)

    def _do_search(self, direction: int, include_current: bool) -> None:
        table = self.query_one("#matrix", DataTable)
        if not table.row_count or not self.last_search:
            return
        ordered = self.model.ordered_tracks()
        n = len(ordered)
        start = table.cursor_row if include_current else table.cursor_row + direction
        for step in range(n + 1):
            idx = (start + step * direction) % n
            if ordered[idx] is not None and self._row_matches(ordered[idx], self.last_search):
                self._jump_to_row(idx)
                return
        self.notify(f"No match for '{self.last_search}'.", severity="warning")

    # -- actions --------------------------------------------------------

    def action_edit_cell(self) -> None:
        track = self.current_track()
        col = self.current_column()
        if track is None:
            return
        if col is None:
            return  # disc column: edited via +/- instead
        current = track.slots.get(col.id, "")

        def handle(result: str | None) -> None:
            if result is None:
                return
            self.model.push_history()
            if col.pinned:
                self.model.set_pinned_value(col, result)
            else:
                track.slots[col.id] = result
            table = self.query_one("#matrix", DataTable)
            self.rebuild_table(keep_cursor=(table.cursor_row, table.cursor_column))

        self.app.push_screen(EditCellScreen(col.key, current), handle)

    def action_add_column(self) -> None:
        col = self.current_column()

        def handle(name: str | None) -> None:
            if not name:
                return
            self.model.push_history()
            new_col = self.model.add_column(after=col, key=name.strip())
            table = self.query_one("#matrix", DataTable)
            self.rebuild_table(keep_cursor=(table.cursor_row, table.cursor_column))

        self.app.push_screen(PromptScreen("New column name:"), handle)

    def action_duplicate_column(self) -> None:
        col = self.current_column()
        if col is None:
            return
        self.model.push_history()
        self.model.duplicate_column(col)
        table = self.query_one("#matrix", DataTable)
        self.rebuild_table(keep_cursor=(table.cursor_row, table.cursor_column))

    def action_delete_column(self) -> None:
        col = self.current_column()
        if col is None:
            return
        self.model.push_history()
        self.model.delete_column(col)
        table = self.query_one("#matrix", DataTable)
        self.rebuild_table(keep_cursor=(table.cursor_row, max(0, table.cursor_column - 1)))

    def action_auto_number(self) -> None:
        self.model.push_history()
        self.model.auto_number()
        self.notify("Track/disc numbers recomputed.")

    def action_move_row(self, delta: int) -> None:
        track = self.current_track()
        if track is None:
            return
        self.model.push_history()
        self.model.move_track(track, delta)
        table = self.query_one("#matrix", DataTable)
        new_row = max(0, min(table.row_count - 1, table.cursor_row + delta))
        self.rebuild_table(keep_cursor=(new_row, table.cursor_column))

    def action_change_disc(self, delta: int) -> None:
        track = self.current_track()
        if track is None:
            return
        new_disc = track.disc + delta
        if new_disc < 1:
            return
        self.model.push_history()
        self.model.set_disc(track, new_disc)
        table = self.query_one("#matrix", DataTable)
        self.rebuild_table(keep_cursor=(table.cursor_row, table.cursor_column))

    def action_reorder_column(self, delta: int) -> None:
        col = self.current_column()
        if col is None:
            return  # disc gutter isn't a reorderable column
        self.model.push_history()
        self.model.reorder_column(col, delta)
        table = self.query_one("#matrix", DataTable)
        new_col_idx = 1 + self.model.columns.index(col)  # +1 for disc gutter col
        self.rebuild_table(keep_cursor=(table.cursor_row, new_col_idx))

    def action_toggle_pin(self) -> None:
        col = self.current_column()
        if col is None:
            return
        self.model.push_history()
        self.model.toggle_pin(col)
        table = self.query_one("#matrix", DataTable)
        new_col_idx = 1 + self.model.columns.index(col)
        self.rebuild_table(keep_cursor=(table.cursor_row, new_col_idx))

    def action_undo(self) -> None:
        table = self.query_one("#matrix", DataTable)
        if self.model.undo():
            self.rebuild_table(keep_cursor=(table.cursor_row, table.cursor_column))
            self.notify("Undo.")
        else:
            self.notify("Nothing to undo.", severity="warning")

    def action_redo(self) -> None:
        table = self.query_one("#matrix", DataTable)
        if self.model.redo():
            self.rebuild_table(keep_cursor=(table.cursor_row, table.cursor_column))
            self.notify("Redo.")
        else:
            self.notify("Nothing to redo.", severity="warning")

    def action_save(self) -> None:
        def handle(confirmed: bool | None) -> None:
            if confirmed:
                failures = self.model.save_all()
                if failures:
                    detail = "; ".join(f"{t.filename}: {err}" for t, err in failures[:3])
                    more = f" (+{len(failures) - 3} more)" if len(failures) > 3 else ""
                    self.notify(
                        f"{len(failures)} file(s) failed to save: {detail}{more}",
                        severity="error",
                        timeout=10,
                    )
                else:
                    self.notify("Saved.")

        self.app.push_screen(SaveDiffScreen(self.model), handle)

    def action_request_quit(self) -> None:
        if not self.model.has_unsaved_changes():
            self.app.exit()
            return

        def handle(confirmed: bool | None) -> None:
            if confirmed:
                self.app.exit()

        self.app.push_screen(
            ConfirmQuitScreen("You have unsaved changes. Quit without saving?"),
            handle,
        )

    def action_cover_art(self) -> None:
        self.app.push_screen(CoverArtScreen(self.model))


class CoverArtScreen(Screen):
    """Grid/filmstrip-style single-track view over the cover art page.
    Thumbnails are decoded+resized once via the model's shared
    ThumbnailCache (keyed on the image bytes themselves), so navigating
    between tracks or reopening this page never re-decodes an image
    that's already been seen -- that repeated full-res decode/resize on
    every visit was the freeze in the old app.
    """

    DEFAULT_CSS = """
    CoverArtScreen #art_preview_box {
        height: 24;
        align: center middle;
        border: round $accent;
    }
    """

    BINDINGS = [
        Binding("escape,q", "back", "Back to matrix"),
        Binding("r", "replace", "Replace cover"),
        Binding("shift+a", "apply_all", "Apply to all"),
        Binding("e", "export", "Export cover art"),
    ]

    def __init__(self, model: MatrixModel) -> None:
        super().__init__()
        self.model = model
        self.index = 0

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical():
            yield Static("", id="art_info")
            with Container(id="art_preview_box"):
                yield TermImage(id="art_preview")
        yield Footer()

    def on_mount(self) -> None:
        self.refresh_info()

    def refresh_info(self) -> None:
        tracks = self.model.ordered_tracks()
        if not tracks:
            return
        track = tracks[self.index % len(tracks)]
        has_art = "yes" if track.cover_art else "no"
        info = self.query_one("#art_info", Static)
        info.update(
            f"Track {self.index + 1}/{len(tracks)}: {track.filename}\n"
            f"Has cover art: {has_art}\n"
            f"[r] replace this track's cover  [shift+A] apply this image to ALL tracks  "
            f"[e] export full-size cover  [left/right] switch track  [esc] back"
        )
        preview = self.query_one("#art_preview", TermImage)
        if track.cover_art:
            # Cache lookup only -- decode/resize happens at most once per
            # distinct image, not on every navigation.
            thumb = self.model.thumbnail_cache.get(track.cover_art)
            preview.image = thumb
            preview.styles.display = "block"
        else:
            preview.image = None
            preview.styles.display = "none"

    def action_back(self) -> None:
        self.app.pop_screen()

    def action_replace(self) -> None:
        def handle(path_str: str | None) -> None:
            if not path_str:
                return
            p = Path(path_str.strip())
            if not p.exists():
                self.notify(f"File not found: {p}", severity="error")
                return
            tracks = self.model.ordered_tracks()
            track = tracks[self.index % len(tracks)]
            try:
                data = p.read_bytes()
            except OSError as exc:
                self.notify(f"Couldn't read image: {exc}", severity="error")
                return
            self.model.push_history()
            track.cover_art = data
            self.refresh_info()

        self.app.push_screen(PromptScreen("Path to image file:"), handle)

    def action_apply_all(self) -> None:
        tracks = self.model.ordered_tracks()
        if not tracks:
            return
        track = tracks[self.index % len(tracks)]
        if track.cover_art is None:
            self.notify("Current track has no cover art to broadcast.", severity="warning")
            return
        self.model.push_history()
        # Every track gets the same bytes object, so the thumbnail cache
        # sees one cache key across all of them -- broadcasting to N
        # tracks never triggers N decodes.
        shared_bytes = track.cover_art
        for t in tracks:
            t.cover_art = shared_bytes
        self.notify(f"Applied this cover to all {len(tracks)} tracks (staged, not yet saved).")
        self.refresh_info()

    def action_export(self) -> None:
        tracks = self.model.ordered_tracks()
        if not tracks:
            return
        track = tracks[self.index % len(tracks)]
        if track.cover_art is None:
            self.notify("This track has no cover art to export.", severity="warning")
            return

        def handle(path_str: str | None) -> None:
            if not path_str:
                return
            dest = Path(path_str.strip()).expanduser()
            if dest.is_dir():
                mime = sniff_mime(track.cover_art)
                ext = ".png" if mime == "image/png" else ".gif" if mime == "image/gif" else ".jpg"
                dest = dest / f"{track.path.stem}_cover{ext}"
            try:
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(track.cover_art)
            except OSError as exc:
                self.notify(f"Export failed: {exc}", severity="error")
                return
            self.notify(f"Exported full-size cover to {dest}")

        self.app.push_screen(
            PromptScreen("Export path (file or folder):", initial=str(Path.cwd())),
            handle,
        )

    def key_left(self) -> None:
        self.index -= 1
        self.refresh_info()

    def key_right(self) -> None:
        self.index += 1
        self.refresh_info()


class MersikApp(App):
    CSS = """
    Screen {
        background: $surface;
    }
    """

    def __init__(self, root: Path) -> None:
        super().__init__()
        self.root = root
        self.model = MatrixModel()

    def on_mount(self) -> None:
        failures = self.model.load_directory(self.root)
        self.push_screen(MatrixScreen(self.model))
        if failures:
            detail = "; ".join(f"{p.name}: {err}" for p, err in failures[:3])
            more = f" (+{len(failures) - 3} more)" if len(failures) > 3 else ""
            self.notify(
                f"{len(failures)} file(s) skipped (failed to load): {detail}{more}",
                severity="error",
                timeout=10,
            )


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python app.py <folder>")
        sys.exit(1)
    root = Path(sys.argv[1]).expanduser().resolve()
    if not root.is_dir():
        print(f"Not a directory: {root}")
        sys.exit(1)
    MersikApp(root).run()


if __name__ == "__main__":
    main()
