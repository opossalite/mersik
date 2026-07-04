"""Data models for the FLAC tag editor."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from mutagen.flac import FLAC, Picture

# Reserved tag key used internally to represent the embedded cover art as
# if it were just another tag in the middle panel. Vorbis comment field
# names are plain ASCII words, so this NUL-wrapped string can never collide
# with a real tag written by any tagger.
COVER_ART_KEY = "\x00COVER_ART\x00"
COVER_ART_LABEL = "[Cover Art]"

# The six "classic" terminal colors. Files beyond the 6th repeat the cycle.
PALETTE = ["red", "green", "yellow", "blue", "magenta", "cyan"]


def sniff_mime(data: bytes) -> str:
    """Best-effort image mime-type sniff from magic bytes."""
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"GIF87a") or data.startswith(b"GIF89a"):
        return "image/gif"
    if len(data) >= 12 and data[4:12] == b"ftypavif":
        return "image/avif"
    return "image/jpeg"  # reasonable fallback


@dataclass
class AudioFile:
    """One FLAC file being edited, and its current in-memory tag state.

    `tags` and `cover_art` reflect the *working* state, which may differ
    from what's on disk until write_to_disk() is called. All edits during
    a session happen here; nothing touches the filesystem until save.
    """

    path: Path
    id: int
    selected: bool = True
    tags: dict[str, str] = field(default_factory=dict)
    cover_art: Optional[bytes] = None

    @property
    def filename(self) -> str:
        return self.path.name

    @property
    def color(self) -> str:
        return PALETTE[(self.id - 1) % len(PALETTE)]

    def load_from_disk(self) -> None:
        """(Re)populate .tags and .cover_art by reading the file on disk.

        NOTE: mutagen's FLAC .tags object (VCFLACDict) is dict-*like*, but
        its .keys()/[key] interface silently lowercases every key, since
        Vorbis comments are conventionally treated as case-insensitive.
        Underneath, though, it's actually a plain `list` of (key, value)
        tuples that preserves whatever case was on disk. We iterate that
        list directly instead of using the dict interface, so that e.g.
        "Genre" and "genre" are read as two distinct tags rather than
        being silently folded into one.
        """
        audio = FLAC(self.path)
        self.tags = {}
        if audio.tags is not None:
            for key, value in audio.tags:  # raw (key, value) tuples, case intact
                if key in self.tags:
                    self.tags[key] = f"{self.tags[key]}; {value}"
                else:
                    self.tags[key] = value
        pictures = audio.pictures
        self.cover_art = pictures[0].data if pictures else None

    def write_to_disk(self) -> None:
        """Persist the current in-memory .tags / .cover_art to the file.

        Same reasoning as load_from_disk: we use .append() (a plain list
        method, not overridden by the dict wrapper) rather than
        `audio.tags[key] = value`, because that dict-style assignment
        first deletes *all* case-insensitive matches of the key before
        adding the new one -- which would silently destroy a same-named,
        different-case tag we're deliberately keeping distinct.
        """
        audio = FLAC(self.path)
        if audio.tags is None:
            audio.add_tags()
        audio.tags.clear()
        for key, value in self.tags.items():
            audio.tags.append((key, value))
        audio.clear_pictures()
        if self.cover_art is not None:
            picture = Picture()
            picture.data = self.cover_art
            picture.type = 3  # "Cover (front)"
            picture.mime = sniff_mime(self.cover_art)
            audio.add_picture(picture)
        audio.save()


def scan_directory(directory: Path) -> list[AudioFile]:
    """Scan a directory (non-recursive) for .flac files, alphanumeric order.

    IDs are assigned 1..N in that same order and are stable for the life
    of the session (used for color-matching and undo/redo bookkeeping).
    """
    paths = sorted(directory.glob("*.flac"), key=lambda p: p.name.lower())
    files: list[AudioFile] = []
    for index, path in enumerate(paths, start=1):
        audio_file = AudioFile(path=path, id=index)
        audio_file.load_from_disk()
        files.append(audio_file)
    return files
