"""Undo/redo history for tag edits.

Every mutation (see mutations.py) is recorded as a HistoryFrame describing
exactly what changed, per affected file, in both directions. Undo/redo just
replays the `before`/`after` state back onto the live AudioFile objects --
there's no separate "re-run the action" logic, which keeps undo trivially
correct even for actions like auto-count that assign different values to
different files.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from models import AudioFile, COVER_ART_KEY, COVER_ART_LABEL

# Sentinel meaning "this tag (or cover art) did not exist in this state".
# Using a sentinel object (rather than e.g. None) lets a tag's value
# legitimately be an empty string without being confused for "absent".
MISSING = object()


@dataclass
class HistoryFrame:
    """One undoable action.

    before/after map file_id -> {tag_key: value_or_MISSING}. tag_key is
    either a real vorbis comment field name, or COVER_ART_KEY for cover art.
    `meta` carries display info (e.g. which tag, old/new name) that isn't
    reconstructable from before/after alone.
    """

    action: str
    file_ids: list[int]
    before: dict[int, dict[str, Any]]
    after: dict[int, dict[str, Any]]
    meta: dict[str, Any] = field(default_factory=dict)


class HistoryManager:
    def __init__(self) -> None:
        self.undo_stack: list[HistoryFrame] = []
        self.redo_stack: list[HistoryFrame] = []
        self._saved_index = 0

    @property
    def dirty(self) -> bool:
        return len(self.undo_stack) != self._saved_index

    def mark_saved(self) -> None:
        self._saved_index = len(self.undo_stack)

    def push(self, frame: HistoryFrame) -> None:
        self.undo_stack.append(frame)
        self.redo_stack.clear()

    def undo(self, files_by_id: dict[int, AudioFile]) -> Optional[HistoryFrame]:
        if not self.undo_stack:
            return None
        frame = self.undo_stack.pop()
        self._apply(frame.before, files_by_id)
        self.redo_stack.append(frame)
        return frame

    def redo(self, files_by_id: dict[int, AudioFile]) -> Optional[HistoryFrame]:
        if not self.redo_stack:
            return None
        frame = self.redo_stack.pop()
        self._apply(frame.after, files_by_id)
        self.undo_stack.append(frame)
        return frame

    @staticmethod
    def _apply(state: dict[int, dict[str, Any]], files_by_id: dict[int, AudioFile]) -> None:
        for file_id, tag_state in state.items():
            audio_file = files_by_id.get(file_id)
            if audio_file is None:
                continue
            for tag, value in tag_state.items():
                if tag == COVER_ART_KEY:
                    audio_file.cover_art = None if value is MISSING else value
                elif value is MISSING:
                    audio_file.tags.pop(tag, None)
                else:
                    audio_file.tags[tag] = value

    def pending_since_save(self) -> list[HistoryFrame]:
        return self.undo_stack[self._saved_index :]


def collapse_pending(frames: list[HistoryFrame]) -> list[str]:
    """Collapse a list of history frames into a condensed, human-readable
    summary for the save-confirmation dialog.

    The undo/redo stack itself always stays granular (one frame per action,
    so undo/redo still steps one action at a time) -- this function only
    affects what's *displayed*, grouping repeated edits to the same tag
    into a single line using the union of affected files and the final
    value/name (last-write-wins).
    """
    groups: dict[tuple, dict[str, Any]] = {}
    # Tracks which group a renamed tag currently belongs to, so a chain of
    # renames (artsit -> artist -> Artist) collapses into one line showing
    # the very first name and the very last name.
    rename_chain: dict[str, tuple] = {}

    for frame in frames:
        action = frame.action
        if action == "rename_tag":
            old_name = frame.meta["old_name"]
            new_name = frame.meta["new_name"]
            key = rename_chain.pop(old_name, None) or ("rename_tag", old_name, id(frame))
            rename_chain[new_name] = key
        elif action in ("add_tag", "delete_tag", "rename_value", "auto_count"):
            key = (action, frame.meta.get("tag"))
        elif action == "replace_image":
            key = ("replace_image",)
        else:
            key = (action, id(frame))

        group = groups.setdefault(
            key, {"action": action, "file_ids": set(), "meta": dict(frame.meta)}
        )
        group["file_ids"] |= set(frame.file_ids)
        if action == "rename_tag":
            group["meta"].setdefault("old_name", frame.meta["old_name"])
            group["meta"]["new_name"] = frame.meta["new_name"]
        else:
            group["meta"].update(frame.meta)

    lines: list[str] = []
    for group in groups.values():
        n = len(group["file_ids"])
        meta = group["meta"]
        action = group["action"]
        if action == "rename_tag":
            lines.append(f"renamed tag '{meta['old_name']}' -> '{meta['new_name']}' on {n} file(s)")
        elif action == "delete_tag":
            tag_label = meta.get("tag", "?")
            label = COVER_ART_LABEL if tag_label == COVER_ART_KEY else tag_label
            lines.append(f"deleted tag '{label}' from {n} file(s)")
        elif action == "add_tag":
            lines.append(f"added tag '{meta.get('tag', '?')}' to {n} file(s)")
        elif action == "rename_value":
            lines.append(f"changed '{meta.get('tag', '?')}' value on {n} file(s)")
        elif action == "auto_count":
            lines.append(f"auto-numbered '{meta.get('tag', '?')}' across {n} file(s)")
        elif action == "replace_image":
            lines.append(f"replaced cover art on {n} file(s)")
    return lines
