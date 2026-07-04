"""Main application: layout, focus routing, and wiring panel keybinds to
the mutation functions in mutations.py.

Overall flow for any edit:
  1. A panel's keybind calls an app.on_xxx() method (usually via a modal
     prompt for input first).
  2. on_xxx() calls the matching function in mutations.py, passing
     self.selected_files -- so it is impossible for an edit to reach an
     unselected file.
  3. on_xxx() calls the relevant refresh_*() method(s) to re-render.

Nothing writes to disk except do_save(), triggered by 's' + confirmation.
"""
from __future__ import annotations

import io
import sys
from pathlib import Path
from typing import Optional

from PIL import Image as PILImage
from textual.app import App, ComposeResult
from textual.containers import Horizontal
from textual.widgets import ContentSwitcher, Static
from textual.widgets.option_list import Option
from textual_image.widget import Image

import mutations
from history import HistoryManager, collapse_pending
from models import AudioFile, COVER_ART_KEY, scan_directory
from modals import ConfirmModal, TextInputModal
from panels import FilePanel, KeybindFooter, TagPanel, ValueImagePanel, ValueTextPanel
from rendering import file_option_text, image_groups, tag_option_text, value_lines


class TagEditorApp(App):
    CSS = """
    Screen {
        background: transparent;
    }

    #body {
        height: 1fr;
    }

    .panel {
        width: 1fr;
        height: 1fr;
        border: round $surface-lighten-2;
        background: transparent;
    }

    .panel:focus-within {
        border: round $accent;
    }

    ValueImagePanel {
        overflow-y: auto;
        padding: 1;
    }

    ValueImagePanel .group-label {
        margin-top: 1;
        text-style: bold;
    }

    #footer {
        dock: bottom;
        height: 1;
        background: $surface;
        color: $text-muted;
        padding: 0 1;
    }
    """

    BINDINGS = [
        ("q", "quit_confirm", "quit"),
        ("s", "save_confirm", "save"),
        ("u", "undo", "undo"),
        ("y", "redo", "redo"),
    ]

    def __init__(self, directory: Path) -> None:
        super().__init__()
        self.directory = directory
        self.files: list[AudioFile] = []
        self.files_by_id: dict[int, AudioFile] = {}
        self.history = HistoryManager()
        self.current_tag: Optional[str] = None

    # -- layout ------------------------------------------------------

    def compose(self) -> ComposeResult:
        with Horizontal(id="body"):
            yield FilePanel(id="file-panel", classes="panel")
            yield TagPanel(id="tag-panel", classes="panel")
            with ContentSwitcher(initial="value-text", id="value-switcher", classes="panel"):
                yield ValueTextPanel(id="value-text")
                yield ValueImagePanel(id="value-image")
        yield KeybindFooter(id="footer")

    def on_mount(self) -> None:
        self.files = scan_directory(self.directory)
        self.files_by_id = {f.id: f for f in self.files}
        if not self.files:
            self.notify(f"No .flac files found in {self.directory}", severity="warning", timeout=6)
        self.refresh_files()
        self.refresh_tags()
        file_panel = self.query_one(FilePanel)
        file_panel.focus()
        self.query_one(KeybindFooter).show_for(file_panel)

    # -- focus tracking / footer --------------------------------------

    def on_descendant_focus(self, event) -> None:  # noqa: ANN001
        self.query_one(KeybindFooter).show_for(event.widget)

    def focus_file_panel(self) -> None:
        self.query_one(FilePanel).focus()

    def focus_tag_panel(self) -> None:
        self.query_one(TagPanel).focus()

    def focus_value_panel(self) -> None:
        switcher = self.query_one(ContentSwitcher)
        if switcher.current == "value-image":
            self.query_one(ValueImagePanel).focus()
        else:
            self.query_one(ValueTextPanel).focus()

    # -- derived state --------------------------------------------------

    @property
    def selected_files(self) -> list[AudioFile]:
        return [f for f in self.files if f.selected]

    # -- refresh helpers --------------------------------------------------

    def refresh_files(self) -> None:
        panel = self.query_one(FilePanel)
        highlighted = panel.highlighted
        panel.clear_options()
        for f in self.files:
            panel.add_option(Option(file_option_text(f), id=str(f.id)))
        if not self.files:
            return
        # OptionList doesn't auto-highlight an option just because it has
        # focus, so without this, "space" would silently do nothing the
        # moment the panel is first focused. Default to the first file,
        # or preserve position across refreshes.
        if highlighted is not None and highlighted < len(self.files):
            panel.highlighted = highlighted
        else:
            panel.highlighted = 0

    def refresh_tags(self, preserve_tag: Optional[str] = None) -> None:
        panel = self.query_one(TagPanel)
        selected = self.selected_files
        tag_names = sorted({t for f in selected for t in f.tags.keys()})
        has_cover = any(f.cover_art is not None for f in selected)
        tags = ([COVER_ART_KEY] if has_cover else []) + tag_names

        current = preserve_tag
        if current is None:
            current = self.current_tag
        if current is None and panel.highlighted is not None:
            existing = panel.get_option_at_index(panel.highlighted)
            current = existing.id if existing is not None else None

        panel.clear_options()
        for tag in tags:
            panel.add_option(Option(tag_option_text(tag, selected), id=tag))

        if tags:
            new_index = tags.index(current) if current in tags else 0
            panel.highlighted = new_index
            self.on_tag_highlighted(tags[new_index])
        else:
            self.on_tag_highlighted(None)

    def refresh_values(self) -> None:
        selected = self.selected_files
        tag = self.current_tag
        switcher = self.query_one(ContentSwitcher)

        if tag == COVER_ART_KEY:
            switcher.current = "value-image"
            self._populate_image_panel(selected)
            return

        switcher.current = "value-text"
        panel = self.query_one(ValueTextPanel)
        panel.clear_options()
        if tag is None:
            return
        for index, line in enumerate(value_lines(tag, selected)):
            panel.add_option(Option(line, id=str(index)))

    def _populate_image_panel(self, selected: list[AudioFile]) -> None:
        panel = self.query_one(ValueImagePanel)
        panel.remove_children()
        groups = image_groups(selected)
        if not groups:
            panel.mount(Static("No files selected.", classes="group-label"))
            return
        widgets = []
        for label, art, group_files in groups:
            widgets.append(Static(f"{label}", classes="group-label"))
            if art is None:
                widgets.append(Static("(no cover art)"))
                continue
            try:
                # textual-image's terminal-graphics renderer (Kitty's
                # Unicode-placeholder method) can only address a limited
                # number of terminal cells. Embedded cover art is often
                # full-resolution (e.g. 3000x3000+), which blows past that
                # limit and crashes the render. We only ever need a
                # thumbnail on screen, so shrink a *copy* for display --
                # the original bytes in AudioFile.cover_art are untouched
                # and are what actually gets written back to disk.
                thumb = PILImage.open(io.BytesIO(art))
                thumb = thumb.convert("RGB")
                thumb.thumbnail((320, 320))
                image_widget = Image()
                image_widget.image = thumb
                widgets.append(image_widget)
            except Exception as exc:
                widgets.append(Static(f"(couldn't render image: {exc})"))
        panel.mount_all(widgets)

    # -- panel callbacks --------------------------------------------------

    def on_file_toggle_select(self, highlighted_index: int) -> None:
        panel = self.query_one(FilePanel)
        option = panel.get_option_at_index(highlighted_index)
        if option is None or option.id is None:
            return
        audio_file = self.files_by_id[int(option.id)]
        audio_file.selected = not audio_file.selected
        self.refresh_files()
        self.refresh_tags()

    def on_tag_highlighted(self, tag_id: Optional[str]) -> None:
        self.current_tag = tag_id
        self.refresh_values()

    def on_tag_add(self) -> None:
        def handle(name: Optional[str]) -> None:
            name = (name or "").strip()
            if name:
                mutations.add_tag(self.selected_files, self.history, name)
                self.refresh_tags(preserve_tag=name)

        self.push_screen(TextInputModal("New tag name (applies to all selected files):"), handle)

    def on_tag_rename(self) -> None:
        tag = self.current_tag
        if tag is None or tag == COVER_ART_KEY:
            return

        def handle(new_name: Optional[str]) -> None:
            new_name = (new_name or "").strip()
            if new_name and new_name != tag:
                mutations.rename_tag(self.selected_files, self.history, tag, new_name)
                self.refresh_tags(preserve_tag=new_name)

        self.push_screen(TextInputModal(f"Rename tag '{tag}' to:", initial=tag), handle)

    def on_tag_delete(self) -> None:
        tag = self.current_tag
        if tag is None:
            return
        if tag == COVER_ART_KEY:
            mutations.delete_cover_art(self.selected_files, self.history)
        else:
            mutations.delete_tag(self.selected_files, self.history, tag)
        self.refresh_tags()

    def on_value_rename(self) -> None:
        tag = self.current_tag
        if tag is None or tag == COVER_ART_KEY:
            return

        def handle(new_value: Optional[str]) -> None:
            if new_value is not None:
                mutations.set_value_all(self.selected_files, self.history, tag, new_value)
                self.refresh_tags(preserve_tag=tag)

        self.push_screen(TextInputModal(f"Set '{tag}' for all selected files to:"), handle)

    def on_auto_count(self) -> None:
        tag = self.current_tag
        if tag is None or tag == COVER_ART_KEY:
            return
        mutations.auto_count(self.selected_files, self.history, tag)
        self.refresh_tags(preserve_tag=tag)

    def on_image_replace(self) -> None:
        def handle(path_str: Optional[str]) -> None:
            if not path_str:
                return
            try:
                mutations.replace_image(self.selected_files, self.history, Path(path_str.strip()))
            except Exception as exc:  # bad path / unreadable image
                self.notify(f"Couldn't load image: {exc}", severity="error", timeout=6)
            self.refresh_tags(preserve_tag=COVER_ART_KEY)

        self.push_screen(TextInputModal("Path to new cover image:"), handle)

    # -- global actions --------------------------------------------------

    def action_undo(self) -> None:
        frame = self.history.undo(self.files_by_id)
        if frame is not None:
            self.refresh_files()
            self.refresh_tags(preserve_tag=self.current_tag)
            self.notify(f"Undid: {frame.action}", timeout=3)

    def action_redo(self) -> None:
        frame = self.history.redo(self.files_by_id)
        if frame is not None:
            self.refresh_files()
            self.refresh_tags(preserve_tag=self.current_tag)
            self.notify(f"Redid: {frame.action}", timeout=3)

    def action_save_confirm(self) -> None:
        lines = collapse_pending(self.history.pending_since_save())

        def handle(confirmed: Optional[bool]) -> None:
            if confirmed:
                self.do_save()

        self.push_screen(ConfirmModal("Save these changes to disk?", lines), handle)

    def do_save(self) -> None:
        for f in self.files:
            f.write_to_disk()
        self.history.mark_saved()
        self.notify("Saved.", timeout=3)

    def action_quit_confirm(self) -> None:
        if not self.history.dirty:
            self.exit()
            return

        def handle(confirmed: Optional[bool]) -> None:
            if confirmed:
                self.exit()

        self.push_screen(ConfirmModal("Unsaved changes", ["Quit without saving?"]), handle)


def main() -> None:
    directory = Path(sys.argv[1]).expanduser() if len(sys.argv) > 1 else Path.cwd()
    if not directory.is_dir():
        print(f"Not a directory: {directory}", file=sys.stderr)
        sys.exit(1)
    TagEditorApp(directory).run()


if __name__ == "__main__":
    main()
