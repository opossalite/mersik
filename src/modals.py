"""Modal dialogs used for prompts and confirmations.

TextInputModal is used for: add tag, rename tag, set value for all
selected, and the "path to new cover image" prompt.
ConfirmModal is used for: save confirmation (with the collapsed diff) and
the quit-with-unsaved-changes warning.
"""
from __future__ import annotations

from typing import Optional

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Input, Static


class TextInputModal(ModalScreen[Optional[str]]):
    """Prompts for a single line of text. Enter submits, Escape cancels."""

    DEFAULT_CSS = """
    TextInputModal {
        align: center middle;
    }
    TextInputModal > Vertical {
        width: 64;
        height: auto;
        border: thick $accent;
        background: $surface;
        padding: 1 2;
    }
    TextInputModal .title {
        margin-bottom: 1;
        text-style: bold;
    }
    TextInputModal .hint {
        margin-top: 1;
        color: $text-muted;
    }
    """

    BINDINGS = [Binding("escape", "cancel", "cancel")]

    def __init__(self, title: str, initial: str = "") -> None:
        super().__init__()
        self._title = title
        self._initial = initial

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static(self._title, classes="title")
            yield Input(value=self._initial, id="modal-input")
            yield Static("enter confirm    esc cancel", classes="hint")

    def on_mount(self) -> None:
        input_widget = self.query_one(Input)
        input_widget.focus()
        input_widget.action_end()  # place cursor after any prefilled text

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self.dismiss(event.value)

    def action_cancel(self) -> None:
        self.dismiss(None)


class ConfirmModal(ModalScreen[bool]):
    """Shows a title and a list of body lines. y/enter confirms, n/escape cancels."""

    DEFAULT_CSS = """
    ConfirmModal {
        align: center middle;
    }
    ConfirmModal > Vertical {
        width: 76;
        height: auto;
        max-height: 80%;
        border: thick $warning;
        background: $surface;
        padding: 1 2;
    }
    ConfirmModal .title {
        margin-bottom: 1;
        text-style: bold;
    }
    ConfirmModal .body {
        margin-bottom: 1;
        height: auto;
        max-height: 20;
        overflow-y: auto;
    }
    ConfirmModal .hint {
        color: $text-muted;
    }
    """

    BINDINGS = [
        Binding("y,enter", "confirm", "confirm"),
        Binding("n,escape", "cancel", "cancel"),
    ]

    def __init__(self, title: str, lines: list[str]) -> None:
        super().__init__()
        self._title = title
        self._lines = lines

    def compose(self) -> ComposeResult:
        body = "\n".join(f"- {line}" for line in self._lines) if self._lines else "(no pending changes)"
        with Vertical():
            yield Static(self._title, classes="title")
            yield Static(body, classes="body")
            yield Static("[y] confirm    [n] cancel", classes="hint")

    def action_confirm(self) -> None:
        self.dismiss(True)

    def action_cancel(self) -> None:
        self.dismiss(False)
