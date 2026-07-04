"""Tag mutation operations.

Each function here takes an explicit list of *target* AudioFile objects --
the caller is responsible for pre-filtering to the currently selected set --
so it is structurally impossible for one of these functions to accidentally
touch a file that isn't part of the active selection. Each function computes
a HistoryFrame, applies the change in-memory immediately, and pushes the
frame onto the history stack. Nothing here touches the filesystem; that
only happens in AudioFile.write_to_disk(), called on save.
"""
from __future__ import annotations

import io
from pathlib import Path

from PIL import Image as PILImage

from history import HistoryFrame, HistoryManager, MISSING
from models import AudioFile, COVER_ART_KEY


def add_tag(files: list[AudioFile], history: HistoryManager, tag_name: str, default_value: str = "") -> None:
    targets = [f for f in files if tag_name not in f.tags]
    if not targets:
        return
    before = {f.id: {tag_name: MISSING} for f in targets}
    after = {f.id: {tag_name: default_value} for f in targets}
    for f in targets:
        f.tags[tag_name] = default_value
    history.push(HistoryFrame("add_tag", [f.id for f in targets], before, after, meta={"tag": tag_name}))


def delete_tag(files: list[AudioFile], history: HistoryManager, tag_name: str) -> None:
    targets = [f for f in files if tag_name in f.tags]
    if not targets:
        return
    before = {f.id: {tag_name: f.tags[tag_name]} for f in targets}
    after = {f.id: {tag_name: MISSING} for f in targets}
    for f in targets:
        del f.tags[tag_name]
    history.push(HistoryFrame("delete_tag", [f.id for f in targets], before, after, meta={"tag": tag_name}))


def delete_cover_art(files: list[AudioFile], history: HistoryManager) -> None:
    targets = [f for f in files if f.cover_art is not None]
    if not targets:
        return
    before = {f.id: {COVER_ART_KEY: f.cover_art} for f in targets}
    after = {f.id: {COVER_ART_KEY: MISSING} for f in targets}
    for f in targets:
        f.cover_art = None
    history.push(
        HistoryFrame("delete_tag", [f.id for f in targets], before, after, meta={"tag": COVER_ART_KEY})
    )


def rename_tag(files: list[AudioFile], history: HistoryManager, old_name: str, new_name: str) -> None:
    if old_name == new_name or not new_name:
        return
    targets = [f for f in files if old_name in f.tags]
    if not targets:
        return
    before: dict[int, dict] = {}
    after: dict[int, dict] = {}
    for f in targets:
        value = f.tags[old_name]
        entry_before = {old_name: value}
        entry_after: dict = {old_name: MISSING, new_name: value}
        if new_name in f.tags and new_name != old_name:
            entry_before[new_name] = f.tags[new_name]  # will be overwritten; remember it
        before[f.id] = entry_before
        after[f.id] = entry_after
        del f.tags[old_name]
        f.tags[new_name] = value
    history.push(
        HistoryFrame(
            "rename_tag",
            [f.id for f in targets],
            before,
            after,
            meta={"old_name": old_name, "new_name": new_name},
        )
    )


def set_value_all(files: list[AudioFile], history: HistoryManager, tag_name: str, new_value: str) -> None:
    """Bulk-set a tag's value to the same string across all given files."""
    targets = [f for f in files if f.tags.get(tag_name) != new_value]
    if not targets:
        return
    before = {f.id: {tag_name: f.tags.get(tag_name, MISSING)} for f in targets}
    after = {f.id: {tag_name: new_value} for f in targets}
    for f in targets:
        f.tags[tag_name] = new_value
    history.push(
        HistoryFrame("rename_value", [f.id for f in targets], before, after, meta={"tag": tag_name})
    )


def auto_count(files: list[AudioFile], history: HistoryManager, tag_name: str) -> None:
    """Assign each file a distinct sequential number, in filename order,
    zero-padded to at least 2 digits (3+ if there are 100+ files)."""
    ordered = sorted(files, key=lambda f: f.filename.lower())
    if not ordered:
        return
    width = max(2, len(str(len(ordered))))
    before = {f.id: {tag_name: f.tags.get(tag_name, MISSING)} for f in ordered}
    after: dict[int, dict] = {}
    for index, f in enumerate(ordered, start=1):
        value = str(index).zfill(width)
        after[f.id] = {tag_name: value}
        f.tags[tag_name] = value
    history.push(
        HistoryFrame("auto_count", [f.id for f in ordered], before, after, meta={"tag": tag_name})
    )


def replace_image(files: list[AudioFile], history: HistoryManager, image_path: Path) -> bytes:
    """Bulk-replace cover art across all given files with the image at
    image_path. Raises FileNotFoundError / PIL exceptions on bad input --
    the caller is expected to surface those to the user.
    Returns the raw bytes that were embedded.
    """
    path = Path(image_path).expanduser()
    if not path.is_file():
        raise FileNotFoundError(f"No such file: {path}")
    data = path.read_bytes()
    with PILImage.open(io.BytesIO(data)) as img:
        img.verify()  # raises if the file isn't a valid, readable image

    targets = [f for f in files if f.cover_art != data]
    if not targets:
        return data
    before = {
        f.id: {COVER_ART_KEY: f.cover_art if f.cover_art is not None else MISSING} for f in targets
    }
    after = {f.id: {COVER_ART_KEY: data} for f in targets}
    for f in targets:
        f.cover_art = data
    history.push(HistoryFrame("replace_image", [f.id for f in targets], before, after, meta={}))
    return data
