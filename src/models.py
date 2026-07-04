"""Data models for the FLAC tag editor."""
from __future__ import annotations

import io
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from mutagen.flac import FLAC, Picture
from PIL import Image as PILImage

# Reserved tag key used internally to represent the embedded cover art as
# if it were just another tag in the middle panel. Vorbis comment field
# names are plain ASCII words, so this NUL-wrapped string can never collide
# with a real tag written by any tagger.
COVER_ART_KEY = "\x00COVER_ART\x00"
COVER_ART_LABEL = "[Cover Art]"

# Six fixed hex colors (Catppuccin Mocha's accent palette), one per file,
# repeating for files beyond the 6th. These are explicit truecolor values
# rather than named ANSI colors like "red"/"blue" on purpose: named ANSI
# colors are resolved through whatever 16-color palette the *terminal*
# defines, and Textual's own ANSI-to-truecolor translation layer doesn't
# necessarily resolve a bare color name to the same RGB in every render
# context (e.g. inside an OptionList row vs. a plain Static). Using fixed
# hex means the same file's color is genuinely the same value everywhere
# (file panel, tag presence dots, value rows, image labels), not just the
# same name.
PALETTE = ["#f38ba8", "#a6e3a1", "#f9e2af", "#89b4fa", "#cba6f7", "#94e2d5"]


def dim_hex(hex_color: str, factor: float = 0.45) -> str:
    """Darken a hex color toward black by `factor`, as a fixed computed
    value. Used instead of Rich's "dim" style attribute, which renders as
    a faint/alpha effect whose appearance can vary by terminal and by the
    widget's background -- a fixed darker hex looks the same everywhere.
    """
    hex_color = hex_color.lstrip("#")
    r, g, b = (int(hex_color[i : i + 2], 16) for i in (0, 2, 4))
    r, g, b = (round(c * factor) for c in (r, g, b))
    return f"#{r:02x}{g:02x}{b:02x}"

# Max pixel dimensions for the *display* thumbnail (see get_cover_thumbnail).
THUMBNAIL_MAX_SIZE = (240, 240)


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
    # (source_bytes, PIL.Image) -- populated lazily by get_cover_thumbnail().
    # Excluded from repr/eq so this dataclass stays readable/comparable.
    _thumbnail_cache: Optional[tuple] = field(default=None, repr=False, compare=False)

    @property
    def filename(self) -> str:
        return self.path.name

    @property
    def color(self) -> str:
        return PALETTE[(self.id - 1) % len(PALETTE)]

    @property
    def dim_color(self) -> str:
        """Darkened version of .color, for files not in scope (e.g.
        unselected in the file panel, or missing a given tag)."""
        return dim_hex(self.color)

    def get_cover_thumbnail(self) -> Optional[PILImage.Image]:
        """Return a small, display-ready PIL image for the current cover
        art, computing it only once per distinct image.

        Decoding + resizing full-resolution embedded art is the expensive
        part of showing the cover-art panel, so the result is cached and
        keyed on the actual bytes -- if cover_art hasn't changed (the
        common case, since it only changes via an explicit replace),
        repeat visits to the panel are free. The cache is invalidated
        automatically whenever cover_art is reassigned to different bytes
        (including by undo/redo, which restores a prior bytes object).
        """
        if self.cover_art is None:
            return None
        cached = self._thumbnail_cache
        if cached is not None and cached[0] == self.cover_art:
            return cached[1]
        thumbnail = PILImage.open(io.BytesIO(self.cover_art)).convert("RGB")
        thumbnail.thumbnail(THUMBNAIL_MAX_SIZE)
        self._thumbnail_cache = (self.cover_art, thumbnail)
        return thumbnail

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
