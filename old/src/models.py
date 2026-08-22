"""Data model for the matrix-based FLAC tag editor."""
from __future__ import annotations

import copy
import io
import itertools
from collections import OrderedDict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from mutagen.flac import FLAC, Picture
from PIL import Image as PILImage

STANDARD_KEYS = [
    "ALBUMARTIST",
    "ALBUM",
    "ARTIST",
    "TITLE",
    "DATE",
    "TRACKNUMBER",
    "TRACKTOTAL",
    "DISCNUMBER",
    "DISCTOTAL",
]

# Keys that are structurally managed (disc grouping / auto-number) rather
# than freely edited like a normal pinned/unpinned tag column. They still
# round-trip as ordinary Vorbis comments on save.
STRUCTURAL_KEYS = {"TRACKNUMBER", "TRACKTOTAL", "DISCNUMBER", "DISCTOTAL"}

_column_id_counter = itertools.count(1)


def sniff_mime(data: bytes) -> str:
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"GIF87a") or data.startswith(b"GIF89a"):
        return "image/gif"
    return "image/jpeg"


@dataclass
class Column:
    """One column in the matrix. Duplicate keys are separate Column
    instances, each independently editable."""

    id: int
    key: str
    pinned: bool

    @classmethod
    def new(cls, key: str, pinned: bool) -> "Column":
        return cls(id=next(_column_id_counter), key=key, pinned=pinned)


@dataclass
class Track:
    """One FLAC file and its in-memory (possibly unsaved) tag state."""

    path: Path
    disc: int = 1
    position: int = 0  # order within its disc group, 0-indexed
    slots: dict[int, str] = field(default_factory=dict)  # column.id -> value
    cover_art: Optional[bytes] = None
    original_tags: list[tuple[str, str]] = field(default_factory=list)
    original_cover: Optional[bytes] = None

    @property
    def filename(self) -> str:
        return self.path.name

    def load_from_disk(self) -> list[tuple[str, str]]:
        """Return the raw (key, value) tuples as stored on disk, case
        intact, duplicates preserved as separate tuples."""
        audio = FLAC(self.path)
        raw: list[tuple[str, str]] = []
        if audio.tags is not None:
            for key, value in audio.tags:
                raw.append((key, value))
        pictures = audio.pictures
        self.cover_art = pictures[0].data if pictures else None
        self.original_cover = self.cover_art
        self.original_tags = list(raw)
        return raw

    def write_to_disk(self, columns: list[Column]) -> None:
        audio = FLAC(self.path)
        if audio.tags is None:
            audio.add_tags()
        audio.tags.clear()
        for col in columns:
            value = self.slots.get(col.id, "")
            if value.strip() == "":
                continue
            audio.tags.append((col.key, value))
        audio.clear_pictures()
        if self.cover_art is not None:
            picture = Picture()
            picture.data = self.cover_art
            picture.type = 3
            picture.mime = sniff_mime(self.cover_art)
            audio.add_picture(picture)
        audio.save()


class ThumbnailCache:
    """Decodes + resizes embedded cover art once per distinct image and
    reuses the result, keyed on the raw bytes (not object identity) so
    tracks sharing the same art -- e.g. after an "apply to all" -- never
    trigger a second decode. This is what actually prevents the freeze
    when reopening the cover-art page: without it, every visit/every
    left-right press would re-decode full-resolution embedded art.

    Capped at `max_entries`, evicting the least-recently-used image, so
    a long session with many different cover swaps doesn't grow
    unbounded.
    """

    def __init__(self, max_size: tuple[int, int] = (320, 320), max_entries: int = 200) -> None:
        self.max_size = max_size
        self.max_entries = max_entries
        self._cache: "OrderedDict[bytes, PILImage.Image]" = OrderedDict()

    def get(self, data: Optional[bytes]) -> Optional[PILImage.Image]:
        if not data:
            return None
        cached = self._cache.get(data)
        if cached is not None:
            self._cache.move_to_end(data)
            return cached
        img = PILImage.open(io.BytesIO(data))
        img = img.convert("RGB")
        img.thumbnail(self.max_size)
        self._cache[data] = img
        if len(self._cache) > self.max_entries:
            self._cache.popitem(last=False)
        return img


class MatrixModel:
    """Holds the full set of tracks + columns for the current session."""

    def __init__(self) -> None:
        self.tracks: list[Track] = []
        self.columns: list[Column] = []  # pinned columns first, then unpinned
        self._undo_stack: list[tuple[list[Column], list[Track]]] = []
        self._redo_stack: list[tuple[list[Column], list[Track]]] = []
        self._history_limit = 100
        self.thumbnail_cache = ThumbnailCache()

    # ---- loading -----------------------------------------------------

    def load_directory(self, root: Path) -> list[tuple[Path, str]]:
        """Returns a list of (path, error) for any file that couldn't be
        read -- those files are simply excluded from the session rather
        than aborting the whole load."""
        paths = sorted(root.rglob("*.flac"), key=lambda p: str(p).lower())
        self.tracks = []
        per_track_raw: list[list[tuple[str, str]]] = []
        failures: list[tuple[Path, str]] = []
        for p in paths:
            track = Track(path=p)
            try:
                raw = track.load_from_disk()
            except Exception as exc:  # noqa: BLE001 - corrupt file, perms, etc.
                failures.append((p, str(exc)))
                continue
            self.tracks.append(track)
            per_track_raw.append(raw)

        if not self.tracks:
            self.columns = []
            return failures

        # Collect all distinct keys across all tracks, first-seen order,
        # case preserved as first encountered.
        seen_keys: list[str] = []
        for raw in per_track_raw:
            for key, _ in raw:
                if key not in seen_keys:
                    seen_keys.append(key)
        # Make sure standard keys are considered even if absent everywhere,
        # so a fresh/empty album still gets the default pinned skeleton.
        for key in STANDARD_KEYS:
            if key not in seen_keys:
                seen_keys.append(key)

        self.columns = []
        for key in seen_keys:
            if key in STRUCTURAL_KEYS:
                continue  # handled via track.disc/position, not a column
            values_per_track = [self._values_for_key(raw, key) for raw in per_track_raw]
            max_count = max((len(v) for v in values_per_track), default=1)
            max_count = max(max_count, 1)
            all_same = self._all_same_single_value(values_per_track)
            is_standard = key in STANDARD_KEYS
            for i in range(max_count):
                pinned = is_standard or (all_same and i == 0)
                col = Column.new(key, pinned=pinned)
                self.columns.append(col)
                for track, values in zip(self.tracks, values_per_track):
                    if i < len(values):
                        track.slots[col.id] = values[i]
                    else:
                        track.slots[col.id] = ""

        # sort: pinned first, then unpinned, preserving relative order
        pinned = [c for c in self.columns if c.pinned]
        unpinned = [c for c in self.columns if not c.pinned]
        self.columns = pinned + unpinned

        # disc/position from DISCNUMBER / TRACKNUMBER tags if present
        for track, raw in zip(self.tracks, per_track_raw):
            disc_val = self._first_value(raw, "DISCNUMBER")
            try:
                track.disc = int(disc_val.split("/")[0]) if disc_val else 1
            except ValueError:
                track.disc = 1

        self._resort_positions_from_current_order()
        return failures

    @staticmethod
    def _values_for_key(raw: list[tuple[str, str]], key: str) -> list[str]:
        return [v for k, v in raw if k == key]

    @staticmethod
    def _first_value(raw: list[tuple[str, str]], key: str) -> str:
        for k, v in raw:
            if k == key:
                return v
        return ""

    @staticmethod
    def _all_same_single_value(values_per_track: list[list[str]]) -> bool:
        if not values_per_track:
            return True
        firsts = []
        for v in values_per_track:
            if len(v) > 1:
                return False
            firsts.append(v[0] if v else "")
        return len(set(firsts)) <= 1

    # ---- disc / ordering ----------------------------------------------

    def discs(self) -> list[int]:
        return sorted(set(t.disc for t in self.tracks))

    def tracks_in_disc(self, disc: int) -> list[Track]:
        return sorted(
            (t for t in self.tracks if t.disc == disc), key=lambda t: t.position
        )

    def ordered_tracks(self) -> list[Track]:
        result: list[Track] = []
        for disc in self.discs():
            result.extend(self.tracks_in_disc(disc))
        return result

    def _resort_positions_from_current_order(self) -> None:
        by_disc: dict[int, list[Track]] = {}
        for t in self.tracks:
            by_disc.setdefault(t.disc, []).append(t)
        for disc, tlist in by_disc.items():
            for i, t in enumerate(tlist):
                t.position = i

    def move_track(self, track: Track, delta: int) -> None:
        """Move a track up/down (delta=-1/+1) within its disc group."""
        group = self.tracks_in_disc(track.disc)
        idx = group.index(track)
        new_idx = idx + delta
        if new_idx < 0 or new_idx >= len(group):
            return
        group[idx], group[new_idx] = group[new_idx], group[idx]
        for i, t in enumerate(group):
            t.position = i

    def set_disc(self, track: Track, new_disc: int) -> None:
        """Reassign a track to a (possibly new) disc, appended at the end
        of that disc's group. new_disc >= 1; if it's higher than any
        existing disc, the group is created implicitly."""
        if new_disc < 1:
            return
        old_disc = track.disc
        old_group = [t for t in self.tracks_in_disc(old_disc) if t is not track]
        for i, t in enumerate(old_group):
            t.position = i
        new_group = self.tracks_in_disc(new_disc)
        track.disc = new_disc
        track.position = len(new_group)

    def auto_number(self) -> None:
        """Recompute TRACKNUMBER/TRACKTOTAL/DISCNUMBER/DISCTOTAL for every
        track from current disc + position, writing into the appropriate
        slots (creating the columns if they don't already exist as
        structural fields -- these are tracked on the Track object
        itself and only materialized into slots at write time via
        get_effective_tags)."""
        discs = self.discs()
        disc_total = len(discs)
        for disc in discs:
            group = self.tracks_in_disc(disc)
            track_total = len(group)
            for i, t in enumerate(group):
                t.disc = disc
                t.position = i
                t.computed_tracknumber = i + 1
                t.computed_tracktotal = track_total
                t.computed_discnumber = disc
                t.computed_disctotal = disc_total

    # ---- history (undo/redo) ---------------------------------------

    def _snapshot(self) -> tuple[list[Column], list[Track]]:
        """Deep-copy columns + tracks for the undo/redo stack.

        This is a full-state snapshot rather than a diff, which is
        simpler and safer for compound actions (e.g. auto_number()
        touching every track at once) at the cost of some memory -- but
        for album-sized sessions (dozens of tracks/columns) that cost is
        negligible. copy.deepcopy treats bytes as atomic, so cover_art
        is never actually duplicated across snapshots, only referenced;
        only the small tag/structure data is genuinely copied each time.
        """
        return (copy.deepcopy(self.columns), copy.deepcopy(self.tracks))

    def push_history(self) -> None:
        """Call before any mutating action to record an undo point."""
        self._undo_stack.append(self._snapshot())
        if len(self._undo_stack) > self._history_limit:
            self._undo_stack.pop(0)
        self._redo_stack.clear()

    def undo(self) -> bool:
        if not self._undo_stack:
            return False
        self._redo_stack.append(self._snapshot())
        self.columns, self.tracks = self._undo_stack.pop()
        return True

    def redo(self) -> bool:
        if not self._redo_stack:
            return False
        self._undo_stack.append(self._snapshot())
        self.columns, self.tracks = self._redo_stack.pop()
        return True

    # ---- columns --------------------------------------------------

    def zone_columns(self, pinned: bool) -> list[Column]:
        return [c for c in self.columns if c.pinned == pinned]

    def toggle_pin(self, col: Column) -> None:
        """Flip a column's pinned state, moving it to the near edge of
        its new zone (right next to the pin/unpin divider)."""
        col.pinned = not col.pinned
        others = [c for c in self.columns if c is not col]
        pinned = [c for c in others if c.pinned]
        unpinned = [c for c in others if not c.pinned]
        if col.pinned:
            pinned.append(col)  # far edge of pinned zone == next to divider
        else:
            unpinned.insert(0, col)  # near edge of unpinned zone == next to divider
        self.columns = pinned + unpinned

    def reorder_column(self, col: Column, delta: int) -> None:
        """Move a column left/right (delta=-1/+1) within its own
        pinned/unpinned zone only -- it can never cross zones this way."""
        zone = self.zone_columns(col.pinned)
        idx = zone.index(col)
        new_idx = idx + delta
        if new_idx < 0 or new_idx >= len(zone):
            return
        zone[idx], zone[new_idx] = zone[new_idx], zone[idx]
        if col.pinned:
            self.columns = zone + self.zone_columns(False)
        else:
            self.columns = self.zone_columns(True) + zone

    def add_column(self, after: Optional[Column], key: str) -> Column:
        """New empty unpinned column, placed right after `after` (or as
        the first unpinned column if `after` is pinned or None)."""
        col = Column.new(key, pinned=False)
        for t in self.tracks:
            t.slots[col.id] = ""
        if after is None or after.pinned:
            insert_at = min(
                (i for i, c in enumerate(self.columns) if not c.pinned),
                default=len(self.columns),
            )
        else:
            insert_at = self.columns.index(after) + 1
        self.columns.insert(insert_at, col)
        return col

    def duplicate_column(self, col: Column) -> Column:
        """New column of same key/pin-state, empty cells, placed
        directly to the right."""
        new_col = Column.new(col.key, pinned=col.pinned)
        for t in self.tracks:
            t.slots[new_col.id] = ""
        insert_at = self.columns.index(col) + 1
        self.columns.insert(insert_at, new_col)
        return new_col

    def delete_column(self, col: Column) -> None:
        self.columns.remove(col)
        for t in self.tracks:
            t.slots.pop(col.id, None)

    def set_pinned_value(self, col: Column, value: str) -> None:
        assert col.pinned
        for t in self.tracks:
            t.slots[col.id] = value

    # ---- effective tags / save -------------------------------------

    def get_effective_tags(self, track: Track) -> list[tuple[str, str]]:
        """All (key, value) pairs this track will be saved with: normal
        column slots plus the structural disc/track fields computed from
        auto_number() (or left absent if auto_number was never run and
        no such tag existed on disk)."""
        pairs: list[tuple[str, str]] = []
        for col in self.columns:
            value = track.slots.get(col.id, "")
            if value.strip() != "":
                pairs.append((col.key, value))
        for key, attr, total_attr in (
            ("TRACKNUMBER", "computed_tracknumber", None),
            ("TRACKTOTAL", "computed_tracktotal", None),
            ("DISCNUMBER", "computed_discnumber", None),
            ("DISCTOTAL", "computed_disctotal", None),
        ):
            val = getattr(track, attr, None)
            if val is not None:
                pairs.append((key, str(val)))
        return pairs

    def diff_for_track(self, track: Track) -> list[str]:
        """Human-readable list of changes for one track vs. what's on
        disk right now."""
        old = list(track.original_tags)
        new = self.get_effective_tags(track)
        changes: list[str] = []
        if old != new:
            old_map: dict[str, list[str]] = {}
            for k, v in old:
                old_map.setdefault(k, []).append(v)
            new_map: dict[str, list[str]] = {}
            for k, v in new:
                new_map.setdefault(k, []).append(v)
            keys = sorted(set(old_map) | set(new_map))
            for k in keys:
                ov, nv = old_map.get(k, []), new_map.get(k, [])
                if ov != nv:
                    changes.append(f"{k}: {ov} -> {nv}")
        if track.cover_art != track.original_cover:
            changes.append("cover art changed")
        return changes

    def has_unsaved_changes(self) -> bool:
        return any(self.diff_for_track(t) for t in self.tracks)

    def save_all(self) -> list[tuple[Track, str]]:
        """Write every track to disk. Returns a list of (track, error)
        for any file that failed -- successfully written files are kept,
        so a failure partway through doesn't roll back what already
        succeeded, but the caller can report exactly what didn't land."""
        failures: list[tuple[Track, str]] = []
        for track in self.tracks:
            try:
                track.write_to_disk(self.columns)
            except Exception as exc:  # noqa: BLE001 - surface any failure
                failures.append((track, str(exc)))
                continue
            track.original_tags = self.get_effective_tags(track)
            track.original_cover = track.cover_art
        return failures


# Track needs these computed attrs default to None; attach dynamically
# rather than cluttering the dataclass signature for something optional.
Track.computed_tracknumber = None
Track.computed_tracktotal = None
Track.computed_discnumber = None
Track.computed_disctotal = None
