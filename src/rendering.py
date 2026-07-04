"""Helpers that turn model state into Rich renderables for the panels.

Kept separate from the panel widget classes so the "what does this row look
like" logic can be read/tested on its own, independent of Textual.
"""
from __future__ import annotations

from typing import Optional

from rich.text import Text

from models import AudioFile, COVER_ART_KEY, COVER_ART_LABEL


def file_option_text(f: AudioFile) -> Text:
    marker = "\u25cf" if f.selected else "\u25cb"  # ● / ○
    style = f.color if f.selected else f.dim_color
    return Text(f"{marker} #{f.id:>2} {f.filename}", style=style)


def _has_tag(f: AudioFile, tag: str) -> bool:
    if tag == COVER_ART_KEY:
        return f.cover_art is not None
    return tag in f.tags


def tag_option_text(tag: str, selected_files: list[AudioFile]) -> Text:
    label = COVER_ART_LABEL if tag == COVER_ART_KEY else tag
    total = len(selected_files)
    present = sum(1 for f in selected_files if _has_tag(f, tag))
    text = Text(f"{label}  ")
    for f in sorted(selected_files, key=lambda x: x.id):
        if _has_tag(f, tag):
            text.append("\u25cf ", style=f.color)  # ●
        else:
            text.append("\u00b7 ", style=f.dim_color)  # ·
    text.append(f" ({present}/{total})", style="dim")
    return text


def value_lines(tag: str, selected_files: list[AudioFile]) -> list[tuple[Text, str]]:
    """One (Text, option_id) row per line for the text-mode value panel.

    If every selected file shares the same value, a single '*' row is
    shown, with option_id "all" -- editing it bulk-sets every selected
    file. Otherwise one row per file, id/color-matched to the file panel,
    with option_id set to that file's id (as a string) -- editing it only
    touches that one file.
    """
    ordered = sorted(selected_files, key=lambda f: f.id)
    if not ordered:
        return [(Text("(no files selected)", style="dim"), "none")]
    values = {f.id: f.tags.get(tag, "") for f in ordered}
    unique = set(values.values())
    if len(unique) == 1:
        only_value = next(iter(unique))
        text = Text()
        text.append("*  ", style="bold")
        text.append(only_value if only_value else "(empty)")
        return [(text, "all")]
    lines = []
    for f in ordered:
        text = Text()
        text.append(f"#{f.id:<2} ", style=f.color)
        value = values[f.id]
        text.append(value if value else "(empty)")
        lines.append((text, str(f.id)))
    return lines


def image_groups(
    selected_files: list[AudioFile],
) -> list[tuple[Text, Optional[bytes], list[AudioFile]]]:
    """Group selected files by cover art for the image-mode value panel.

    Mirrors value_lines()'s rule exactly: if every selected file has the
    identical image (including "all have none"), a single '*' group is
    returned, in bold with no single file's color (it represents all of
    them). Otherwise, one group per file, labeled and colored to match
    that file's entry in the file panel.
    """
    ordered = sorted(selected_files, key=lambda f: f.id)
    if not ordered:
        return []
    arts = {f.id: f.cover_art for f in ordered}
    unique = set(arts.values())
    if len(unique) == 1:
        label = Text("*", style="bold")
        return [(label, next(iter(unique)), ordered)]
    groups = []
    for f in ordered:
        label = Text(f"#{f.id}", style=f.color)
        groups.append((label, f.cover_art, [f]))
    return groups
