"""Panel widgets: file list, tag list, and the two value-panel variants.

Navigation (hjkl / arrows) and per-panel keybinds live here as BINDINGS.
The actual mutation logic lives in mutations.py; these widgets just call
back into the App (self.app.on_xxx()), which owns the AudioFile list, the
HistoryManager, and orchestrates refreshing all three panels after any
change. That keeps "what can trigger a change" (here) separate from "how a
change is applied and displayed" (app.py).
"""
from __future__ import annotations

from textual.binding import Binding
from textual.containers import Container
from textual.widgets import OptionList, Static


class FilePanel(OptionList):
    """Left panel: every FLAC file in the working directory."""

    KEYBIND_HELP = "j/k \u2191/\u2193 navigate    space toggle selected    l/\u2192 focus tags"

    BINDINGS = [
        Binding("j", "cursor_down", "down", show=False),
        Binding("k", "cursor_up", "up", show=False),
        Binding("l,right", "move_right", "focus tags"),
        Binding("space", "toggle_select", "toggle selected"),
    ]

    def action_move_right(self) -> None:
        self.app.focus_tag_panel()  # type: ignore[attr-defined]

    def action_toggle_select(self) -> None:
        if self.highlighted is not None:
            self.app.on_file_toggle_select(self.highlighted)  # type: ignore[attr-defined]


class TagPanel(OptionList):
    """Middle panel: tags present across the currently selected files."""

    KEYBIND_HELP = (
        "j/k \u2191/\u2193 navigate    h/\u2190 focus files    l/\u2192 focus values    "
        "a add    r/e rename    d delete"
    )

    BINDINGS = [
        Binding("j", "cursor_down", "down", show=False),
        Binding("k", "cursor_up", "up", show=False),
        Binding("h,left", "move_left", "focus files"),
        Binding("l,right", "move_right", "focus values"),
        Binding("r,e", "rename_tag", "rename tag"),
        Binding("d", "delete_tag", "delete tag"),
        Binding("a", "add_tag", "add tag"),
    ]

    def action_move_left(self) -> None:
        self.app.focus_file_panel()  # type: ignore[attr-defined]

    def action_move_right(self) -> None:
        self.app.focus_value_panel()  # type: ignore[attr-defined]

    def action_rename_tag(self) -> None:
        self.app.on_tag_rename()  # type: ignore[attr-defined]

    def action_delete_tag(self) -> None:
        self.app.on_tag_delete()  # type: ignore[attr-defined]

    def action_add_tag(self) -> None:
        self.app.on_tag_add()  # type: ignore[attr-defined]

    def on_option_list_option_highlighted(self, event: OptionList.OptionHighlighted) -> None:
        option = event.option
        self.app.on_tag_highlighted(option.id if option is not None else None)  # type: ignore[attr-defined]


class ValueTextPanel(OptionList):
    """Right panel, text mode: values for the currently highlighted tag."""

    KEYBIND_HELP = "j/k \u2191/\u2193 scroll    h/\u2190 focus tags    r/e set value for all selected    c auto-count"

    BINDINGS = [
        Binding("j", "cursor_down", "down", show=False),
        Binding("k", "cursor_up", "up", show=False),
        Binding("h,left", "move_left", "focus tags"),
        Binding("r,e", "rename_value", "set value"),
        Binding("c", "auto_count", "auto-count"),
    ]

    def action_move_left(self) -> None:
        self.app.focus_tag_panel()  # type: ignore[attr-defined]

    def action_rename_value(self) -> None:
        self.app.on_value_rename()  # type: ignore[attr-defined]

    def action_auto_count(self) -> None:
        self.app.on_auto_count()  # type: ignore[attr-defined]


class ValueImagePanel(Container, can_focus=True):
    """Right panel, image mode: cover art for the currently selected files."""

    KEYBIND_HELP = "\u2191/\u2193 scroll    h/\u2190 focus tags    r/e replace cover art for all selected"

    BINDINGS = [
        Binding("h,left", "move_left", "focus tags"),
        Binding("r,e", "replace_image", "replace image"),
    ]

    def action_move_left(self) -> None:
        self.app.focus_tag_panel()  # type: ignore[attr-defined]

    def action_replace_image(self) -> None:
        self.app.on_image_replace()  # type: ignore[attr-defined]


class KeybindFooter(Static):
    """Bottom bar: keybinds available in whichever panel currently has focus."""

    def show_for(self, panel: object) -> None:
        panel_help = getattr(panel, "KEYBIND_HELP", "")
        global_help = "q quit    s save    u undo    y redo"
        self.update(f"{panel_help}    |    {global_help}")
