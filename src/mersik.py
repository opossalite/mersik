#!/usr/bin/env python3
"""
mersik - edit FLAC and WavPack tags and cover art outside the files, then write them back.

    mersik init [path]   export tags to tags.csv and cover art to covers/
    mersik save [path]   write tags.csv and covers/ back into the music files
    mersik diff [path]   show how tags.csv and covers/ differ from the music files
                         (read-only; exit status 1 if there are differences)

Supported formats: .flac (Vorbis comments) and .wv (WavPack, APEv2 tags).

init and save are exact inverses: running `init` and then `save` (or `diff`)
without editing anything changes and reports nothing.

Images are never re-encoded or resized: the exact bytes embedded in a file
are what get written to covers/, and the exact bytes in covers/ are what get
embedded on save. Pillow is only used to read image dimensions.
"""

import argparse
import csv
import io
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from mutagen.apev2 import BINARY, TEXT, APEValue
from mutagen.flac import FLAC, Picture
from mutagen.wavpack import WavPack
from PIL import Image

RESERVED_KEY = "filename"
CSV_NAME = "tags.csv"
COVERS_DIR_NAME = "covers"

# A FLAC metadata block stores its length in 24 bits.
MAX_PICTURE_BYTES = 0xFFFFFF - 4096


class MersikError(Exception):
    """A problem worth stopping for; printed without a traceback."""


class SkipFile(Exception):
    """Something about one file means it can't be handled; it's skipped with a warning."""


# --------------------------------------------------------------------------
# Small helpers
# --------------------------------------------------------------------------

def confirm(prompt: str) -> bool:
    """Ask a yes/no question, defaulting to No."""
    try:
        answer = input(f"{prompt} [y/N] ").strip().lower()
    except EOFError:
        return False
    return answer in ("y", "yes")


def warn(message: str) -> None:
    print(f"warning: {message}", file=sys.stderr)


def format_size(num_bytes: int) -> str:
    if num_bytes < 1024:
        return f"{num_bytes} B"
    if num_bytes < 1024 * 1024:
        return f"{num_bytes / 1024:.0f} KiB"
    return f"{num_bytes / (1024 * 1024):.1f} MiB"


def list_music(folder: Path) -> list[Path]:
    """The music files mersik handles, by exact extension (.flac, .wv)."""
    return sorted(p for p in folder.iterdir() if p.is_file() and p.suffix in _FORMATS)


def shared_stems(files: list[Path]) -> set[str]:
    """Stems used by more than one file (e.g. Track.flac + Track.wv)."""
    counts = Counter(p.stem for p in files)
    return {stem for stem, n in counts.items() if n > 1}


def warn_shared_stems(files: list[Path]) -> set[str]:
    shared = shared_stems(files)
    for stem in sorted(shared):
        names = ", ".join(p.name for p in files if p.stem == stem)
        warn(f"{names} share a name, so their cover art can't be told apart; "
             f"covers are skipped for them (tags still work)")
    return shared


# --------------------------------------------------------------------------
# Image helpers
# --------------------------------------------------------------------------

_MIME_TO_EXT = {
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/png": ".png",
    "image/gif": ".gif",
    "image/bmp": ".bmp",
    "image/webp": ".webp",
}
_EXT_TO_MIME = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".gif": "image/gif",
    ".bmp": "image/bmp",
    ".webp": "image/webp",
}


def sniff_image(data: bytes, declared_mime: str | None = None) -> tuple[str, str] | None:
    """
    Work out (mime, extension) for image bytes. The actual bytes win over
    the declared MIME type, which is only a fallback. Returns None for
    anything we don't recognize (e.g. FLAC's "-->" URL pictures).
    """
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg", ".jpg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png", ".png"
    if data.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif", ".gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp", ".webp"
    ext = _MIME_TO_EXT.get((declared_mime or "").lower())
    if ext:
        return _EXT_TO_MIME[ext], ext
    return None


def describe_image(data: bytes) -> str:
    size = format_size(len(data))
    try:
        with Image.open(io.BytesIO(data)) as img:
            return f"{(img.format or 'image').lower()} {img.width}x{img.height}, {size}"
    except Exception:
        return f"unreadable image, {size}"


@dataclass
class Pic:
    """One embedded picture, format-neutrally. `meta` is the backend's own detail."""
    data: bytes
    mime: str
    ext: str
    meta: object = None


class MusicFile:
    """
    A format-neutral view of one tagged music file. Tag names are handled
    lowercase and case-insensitively; values are lists of strings.
    """
    label = "music"
    max_picture_bytes: int | None = None

    def __init__(self, path: Path):
        self.path = path

    @staticmethod
    def valid_key(key: str) -> bool:
        raise NotImplementedError

    def key_problem(self, key: str) -> str | None:
        """Why `key` can't be written to this file (None if it can)."""
        return None if self.valid_key(key) else f"is not a valid {self.label} tag name"

    def tag_items(self) -> dict[str, list[str]]:
        """Every text tag as {lowercase key: values}, empty values included."""
        raise NotImplementedError

    def get(self, key: str) -> list[str]:
        raise NotImplementedError

    def set(self, key: str, values: list[str]) -> None:
        raise NotImplementedError

    def remove(self, key: str) -> None:
        raise NotImplementedError

    def pictures(self) -> list[Pic]:
        """The pictures `init` exports, in a stable order."""
        raise NotImplementedError

    def unexportable_count(self) -> int:
        """Pictures present that `init` can't export (and `save` keeps)."""
        raise NotImplementedError

    def make_pic(self, data: bytes, mime: str, ext: str, source_name: str,
                 template: Pic | None, index: int) -> Pic:
        raise NotImplementedError

    def finalize_pictures(self, pics: list[Pic]) -> None:
        """Last checks/assignments before `replace_pictures`; may raise SkipFile."""

    def replace_pictures(self, pics: list[Pic]) -> None:
        """Replace the exportable pictures with `pics`, keeping the others."""
        raise NotImplementedError

    def save(self) -> None:
        raise NotImplementedError


# ---- FLAC ----------------------------------------------------------------

_VORBIS_KEY = re.compile(r"[\x20-\x3c\x3e-\x7d]+")  # Vorbis comment field names
_MODE_DEPTH = {"1": 1, "L": 8, "P": 8, "LA": 16, "I;16": 16,
               "RGB": 24, "RGBA": 32, "CMYK": 32}


def make_flac_picture(data: bytes, mime: str, template: Picture | None, index: int) -> Picture:
    """
    Build a FLAC picture block around the untouched image bytes. Type and
    description are inherited from `template` (the picture previously at
    this position) when there is one.
    """
    pic = Picture()
    pic.data = data
    pic.mime = mime
    pic.type = template.type if template else (3 if index == 1 else 0)
    pic.desc = template.desc if template else ""
    pic.colors = 0
    with Image.open(io.BytesIO(data)) as img:
        pic.width, pic.height = img.size
        pic.depth = _MODE_DEPTH.get(img.mode, 24)
    return pic


class FlacFile(MusicFile):
    label = "FLAC"
    max_picture_bytes = MAX_PICTURE_BYTES

    def __init__(self, path: Path):
        super().__init__(path)
        self.audio = FLAC(path)

    @staticmethod
    def valid_key(key: str) -> bool:
        return bool(_VORBIS_KEY.fullmatch(key))

    def tag_items(self) -> dict[str, list[str]]:
        tags = self.audio.tags
        return {k.lower(): list(v) for k, v in tags.items()} if tags else {}

    def get(self, key: str) -> list[str]:
        tags = self.audio.tags
        return list(tags.get(key, [])) if tags else []

    def set(self, key: str, values: list[str]) -> None:
        if self.audio.tags is None:
            self.audio.add_tags()
        self.audio[key] = values

    def remove(self, key: str) -> None:
        if key in self.audio:
            del self.audio[key]

    def pictures(self) -> list[Pic]:
        out = []
        for pic in self.audio.pictures:
            kind = sniff_image(pic.data, pic.mime)
            if kind is not None:
                out.append(Pic(pic.data, kind[0], kind[1], pic))
        return out

    def unexportable_count(self) -> int:
        return len(self.audio.pictures) - len(self.pictures())

    def make_pic(self, data, mime, ext, source_name, template, index) -> Pic:
        picture = make_flac_picture(data, mime, template.meta if template else None, index)
        return Pic(data, mime, ext, picture)

    def replace_pictures(self, pics: list[Pic]) -> None:
        unmanaged = [p for p in self.audio.pictures if sniff_image(p.data, p.mime) is None]
        self.audio.clear_pictures()
        for pic in pics:
            self.audio.add_picture(Picture(pic.meta.write()))  # copy, keeps all metadata
        for pic in unmanaged:
            self.audio.add_picture(pic)

    def save(self) -> None:
        self.audio.save()


# ---- WavPack (APEv2 tags) -------------------------------------------------
#
# APEv2 stores art as binary items named "Cover Art (<kind>)" whose value is
# "<filename>\0<image bytes>". Item names are unique, so each picture needs its
# own kind, and mutagen reorders items when saving, so pictures are put in a
# fixed order (by kind) wherever position matters.

_APE_PICTURE_LABELS = [
    "Cover Art (Front)", "Cover Art (Back)", "Cover Art (Other)", "Cover Art (Leaflet)",
    "Cover Art (Media)", "Cover Art (Artist)", "Cover Art (Illustration)",
    "Cover Art (Band logo)", "Cover Art (Publisher logo)", "Cover Art (Icon)",
    "Cover Art (Conductor)", "Cover Art (Composer)",
]
_APE_LABEL_ORDER = {label.lower(): i for i, label in enumerate(_APE_PICTURE_LABELS)}
_APE_INVALID_KEYS = {"oggs", "tag", "id3", "mp+"}


def _ape_order(label: str) -> tuple[int, str]:
    low = label.lower()
    return (_APE_LABEL_ORDER.get(low, len(_APE_LABEL_ORDER)), low)


class WavPackFile(MusicFile):
    label = "WavPack"

    def __init__(self, path: Path):
        super().__init__(path)
        self.audio = WavPack(path)

    @staticmethod
    def valid_key(key: str) -> bool:
        return (2 <= len(key) <= 255
                and all(0x20 <= ord(c) <= 0x7E for c in key)
                and key.lower() not in _APE_INVALID_KEYS)

    def _existing_key(self, key: str) -> str | None:
        """The key as stored in the file (its own capitalization), if present."""
        tags = self.audio.tags
        if tags is None:
            return None
        low = key.lower()
        return next((k for k in tags.keys() if k.lower() == low), None)

    def key_problem(self, key: str) -> str | None:
        problem = super().key_problem(key)
        if problem:
            return problem
        existing = self._existing_key(key)
        if existing is not None and self.audio.tags[existing].kind != TEXT:
            return "is a binary item in this file, not a text tag"
        return None

    def tag_items(self) -> dict[str, list[str]]:
        tags = self.audio.tags
        if not tags:
            return {}
        return {k.lower(): list(v) for k, v in tags.items() if v.kind == TEXT}

    def get(self, key: str) -> list[str]:
        existing = self._existing_key(key)
        if existing is None or self.audio.tags[existing].kind != TEXT:
            return []
        return list(self.audio.tags[existing])

    def set(self, key: str, values: list[str]) -> None:
        if self.audio.tags is None:
            self.audio.add_tags()
        # keep the capitalization the file already uses for this tag
        self.audio.tags[self._existing_key(key) or key] = list(values)

    def remove(self, key: str) -> None:
        existing = self._existing_key(key)
        if existing is not None and self.audio.tags[existing].kind == TEXT:
            del self.audio.tags[existing]

    def _picture_items(self) -> list[Pic]:
        out = []
        for key, value in (self.audio.tags.items() if self.audio.tags else []):
            if value.kind != BINARY or not key.lower().startswith("cover art"):
                continue
            name, sep, data = bytes(value).partition(b"\0")
            if not sep:
                continue
            declared = _EXT_TO_MIME.get(Path(name.decode("utf-8", "replace")).suffix.lower())
            kind = sniff_image(data, declared)
            if kind is not None:
                out.append(Pic(data, kind[0], kind[1], {"label": key, "filename": name}))
        out.sort(key=lambda p: _ape_order(p.meta["label"]))
        return out

    def pictures(self) -> list[Pic]:
        return self._picture_items()

    def unexportable_count(self) -> int:
        tags = self.audio.tags
        if not tags:
            return 0
        n = sum(1 for k, v in tags.items()
                if v.kind == BINARY and k.lower().startswith("cover art"))
        return n - len(self._picture_items())

    def make_pic(self, data, mime, ext, source_name, template, index) -> Pic:
        meta = {"label": template.meta["label"] if template else None,
                "filename": source_name.encode("utf-8", "surrogateescape")}
        return Pic(data, mime, ext, meta)

    def finalize_pictures(self, pics: list[Pic]) -> None:
        """Give every new picture a free 'Cover Art (...)' name."""
        managed = {p.meta["label"].lower() for p in self._picture_items()}
        existing = {k.lower() for k in (self.audio.tags.keys() if self.audio.tags else [])}
        used = (existing - managed) | {p.meta["label"].lower() for p in pics if p.meta["label"]}
        for pic in pics:
            if pic.meta["label"]:
                continue
            for label in _APE_PICTURE_LABELS:
                if label.lower() not in used:
                    pic.meta["label"] = label
                    used.add(label.lower())
                    break
            else:
                raise SkipFile("too many pictures for a WavPack file")

    def replace_pictures(self, pics: list[Pic]) -> None:
        if self.audio.tags is None:
            self.audio.add_tags()
        tags = self.audio.tags
        for current in self._picture_items():
            del tags[current.meta["label"]]
        for pic in pics:
            raw = pic.meta["filename"] + b"\0" + pic.data
            tags[pic.meta["label"]] = APEValue(raw, BINARY)

    def save(self) -> None:
        self.audio.save()


_FORMATS: dict[str, type[MusicFile]] = {".flac": FlacFile, ".wv": WavPackFile}


def open_music(path: Path) -> MusicFile:
    return _FORMATS[path.suffix](path)


# --------------------------------------------------------------------------
# init: music files -> tags.csv + covers/
# --------------------------------------------------------------------------

def read_music_tags(folder: Path) -> tuple[list[str], list[list[str]]]:
    """
    Read every music file's tags. Returns (columns, rows). The first column
    is 'filename'; then each tag key (alphabetical) repeated as many times as
    the most values any file has for it, so multiple values of one tag are
    several columns with the same name. Empty tag values are dropped (a tag
    with no non-empty value gets no column); missing values are empty cells.
    """
    file_tags: list[tuple[str, dict[str, list[str]]]] = []
    max_counts: dict[str, int] = {}
    for path in list_music(folder):
        tags: dict[str, list[str]] = {}
        for key, values in open_music(path).tag_items().items():
            kept = [v for v in values if v != ""]  # empty values/tags aren't exported
            if kept:
                tags[key] = kept
        if RESERVED_KEY in tags:
            warn(f"{path.name}: its '{RESERVED_KEY}' tag can't be exported (clashes with the "
                 f"filename column) and will be left untouched by save")
            del tags[RESERVED_KEY]
        file_tags.append((path.name, tags))
        for key, values in tags.items():
            max_counts[key] = max(max_counts.get(key, 0), len(values))

    keys = sorted(max_counts)
    columns = ["filename"]
    for key in keys:
        columns.extend([key] * max_counts[key])

    rows = []
    for filename, tags in file_tags:
        row = [filename]
        for key in keys:
            values = tags.get(key, [])
            row.extend(values + [""] * (max_counts[key] - len(values)))
        rows.append(row)
    return columns, rows


def extract_covers(folder: Path) -> dict[str, bytes]:
    """
    Map cover filename -> the exact embedded image bytes. Names are the
    music file's name with the image's extension: '01 - Track.flac' (or
    '.wv') gives '01 - Track.jpg'. A file with several pictures gets
    '01 - Track_2.png', '01 - Track_3.jpg', ... for the extras so they can
    coexist. An extra's index is bumped past any name that another music
    file owns (e.g. when 'A_2.flac' exists, the second picture of 'A.flac'
    becomes 'A_3'), so `save` always maps every image back to the right file
    and slot. Files that share a name across formats are skipped.
    """
    files = list_music(folder)
    shared = warn_shared_stems(files)
    used_stems = {p.stem for p in files}  # each file owns its own stem
    covers: dict[str, bytes] = {}

    for path in files:
        if path.stem in shared:
            continue
        mf = open_music(path)
        pictures = mf.pictures()
        skipped = mf.unexportable_count()
        if skipped:
            warn(f"{path.name}: skipped {skipped} picture(s) with an unrecognized image type")
        index = 1
        for n, pic in enumerate(pictures):
            if n == 0:
                stem = path.stem
            else:
                index += 1
                while f"{path.stem}_{index}" in used_stems:
                    index += 1
                stem = f"{path.stem}_{index}"
                used_stems.add(stem)
            covers[f"{stem}{pic.ext}"] = pic.data
    return covers


def cmd_init(path: str | Path) -> None:
    """
    'mersik init [path]': export tags to tags.csv and embedded art to covers/.

    - Existing tags.csv: ask before overwriting; declining skips only the csv.
    - Existing covers/: files whose names don't clash are left alone. If any
      new cover has the same name as an existing, different file, ask once
      before writing anything; declining writes no covers at all.
    """
    folder = Path(path)
    if not folder.is_dir():
        raise MersikError(f"{folder} is not a directory")
    if not list_music(folder):
        raise MersikError(f"no music files (.flac, .wv) found in {folder}")

    csv_path = folder / CSV_NAME
    covers_dir = folder / COVERS_DIR_NAME
    covers = extract_covers(folder)

    # Decide everything first, then write, so no prompt follows a write.
    write_csv = True
    if csv_path.exists() and not confirm(f"{csv_path} already exists. Overwrite?"):
        print(f"Skipped {CSV_NAME}.")
        write_csv = False

    write_covers = bool(covers)
    unchanged: set[str] = set()
    if covers and covers_dir.exists():
        if not covers_dir.is_dir():
            raise MersikError(f"{covers_dir} exists and is not a directory")
        conflicts = []
        for name, data in covers.items():
            existing = covers_dir / name
            if existing.exists():
                if existing.is_file() and existing.read_bytes() == data:
                    unchanged.add(name)  # identical already; nothing to overwrite
                else:
                    conflicts.append(name)
        if conflicts:
            listing = "\n".join(f"  {n}" for n in conflicts)
            print(f"{len(conflicts)} cover(s) in {covers_dir} would be overwritten:\n{listing}")
            if not confirm("Overwrite them?"):
                print("Skipped covers; no cover files were changed.")
                write_covers = False

    if write_csv:
        columns, rows = read_music_tags(folder)
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(columns)
            writer.writerows(rows)
        print(f"Wrote {len(rows)} row(s) to {csv_path}")

    if not covers:
        print("No embedded cover art found.")
    elif write_covers:
        covers_dir.mkdir(exist_ok=True)
        written = 0
        for name, data in covers.items():
            if name in unchanged:
                continue
            (covers_dir / name).write_bytes(data)
            written += 1
        note = f" ({len(unchanged)} already up to date)" if unchanged else ""
        print(f"Wrote {written} cover(s) to {covers_dir}{note}")


# --------------------------------------------------------------------------
# save: tags.csv + covers/ -> music files
# --------------------------------------------------------------------------

_CSV_KEY = re.compile(r"[\x20-\x7e]+")  # printable ASCII; each format checks its own rules


def read_tags_csv(csv_path: Path) -> tuple[dict[str, dict[str, list[str]]], list[str]]:
    """
    Parse tags.csv. Returns ({filename: {key: [values]}}, [managed keys]).
    Repeated column names are repeated values, in column order; empty cells
    are ignored. Read with the csv module rather than pandas, which would
    rename duplicate columns.
    """
    with open(csv_path, newline="", encoding="utf-8-sig") as f:
        reader = csv.reader(f)
        header = next(reader, None)
        if header is None:
            raise MersikError(f"{csv_path} is empty")
        header = [h.strip().lower() for h in header]
        if "filename" not in header:
            raise MersikError(f"{csv_path} has no 'filename' column")
        fn_col = header.index("filename")

        key_cols: dict[str, list[int]] = {}
        for i, name in enumerate(header):
            if i == fn_col or not name or name == "filename":
                continue
            if not _CSV_KEY.fullmatch(name):
                raise MersikError(f"{csv_path}: {name!r} is not a valid tag name")
            key_cols.setdefault(name, []).append(i)

        rows: dict[str, dict[str, list[str]]] = {}
        for line_no, row in enumerate(reader, start=2):
            if not any(cell.strip() for cell in row):
                continue
            row = row + [""] * (len(header) - len(row))
            filename = row[fn_col]
            if not filename.strip():
                warn(f"{csv_path} line {line_no}: no filename; skipping")
                continue
            if Path(filename).name != filename:
                warn(f"{csv_path} line {line_no}: {filename!r} is not a plain filename; skipping")
                continue
            if filename in rows:
                raise MersikError(f"{csv_path} line {line_no}: {filename!r} appears more than once")
            rows[filename] = {
                key: [row[i] for i in cols if row[i] != ""]
                for key, cols in key_cols.items()
            }
    return rows, list(key_cols)


def find_cover_files(folder: Path, stems: set[str]) -> dict[str, dict[int, list[Path]]]:
    """
    Match images in covers/ to music files: {stem: {index: [paths]}}.
    'Track.ext' is index 1 of 'Track.flac'; 'Track_N.ext' (N >= 2) is index N.
    An exact stem match wins over the '_N' reading, so 'A_2.flac' and the
    second picture of 'A.flac' don't get confused.
    """
    covers_dir = folder / COVERS_DIR_NAME
    found: dict[str, dict[int, list[Path]]] = defaultdict(lambda: defaultdict(list))
    if not covers_dir.is_dir():
        return found
    for p in sorted(covers_dir.iterdir()):
        if not p.is_file() or p.suffix.lower() not in _EXT_TO_MIME:
            continue
        if p.stem in stems:
            found[p.stem][1].append(p)
            continue
        m = re.fullmatch(r"(.+)_(\d+)", p.stem)
        if m and m.group(1) in stems and int(m.group(2)) >= 2:
            found[m.group(1)][int(m.group(2))].append(p)
    return found


@dataclass
class CoverChange:
    pictures: list[Pic]
    old_desc: list[str]
    new_desc: list[str]


@dataclass
class FilePlan:
    path: Path
    tag_changes: list[tuple[str, list[str], list[str]]] = field(default_factory=list)
    cover: CoverChange | None = None
    # Informational only; never something `save` acts on.
    untracked_tags: list[str] = field(default_factory=list)
    art_without_cover_file: bool = False

    @property
    def has_changes(self) -> bool:
        return bool(self.tag_changes) or self.cover is not None


@dataclass
class Comparison:
    plans: list[FilePlan]          # one per readable music file
    csv_only: list[str]            # rows in tags.csv with no music file
    no_row: list[str]              # music files with no row in tags.csv

    @property
    def changed(self) -> list[FilePlan]:
        return [p for p in self.plans if p.has_changes]


def plan_covers(mf: MusicFile, files: dict[int, list[Path]]) -> CoverChange | None:
    """
    What `save` would do to this file's pictures (None = nothing). If
    anything about the images is unusable the whole file's pictures are left
    alone, so a bad image can never cause other pictures to be dropped.
    """
    if not files:
        return None
    name = mf.path.name
    clashes = [i for i, paths in files.items() if len(paths) > 1]
    if clashes:
        names = ", ".join(p.name for i in clashes for p in files[i])
        warn(f"{name}: several images claim the same slot ({names}); covers left unchanged")
        return None

    current = mf.pictures()
    new: list[tuple[Path, bytes, str, str]] = []
    for pos, index in enumerate(sorted(files)):
        p = files[index][0]
        data = p.read_bytes()
        same_as_embedded = pos < len(current) and current[pos].data == data
        if not same_as_embedded:
            problem = None
            if mf.max_picture_bytes is not None and len(data) > mf.max_picture_bytes:
                problem = f"is too large for a {mf.label} picture"
            else:
                try:
                    with Image.open(io.BytesIO(data)):
                        pass
                except Exception:
                    problem = "is not a readable image"
            if problem:
                warn(f"{name}: {p.name} {problem}; covers left unchanged")
                return None
        mime, ext = sniff_image(data, _EXT_TO_MIME[p.suffix.lower()])
        new.append((p, data, mime, ext))

    if [d for _, d, _, _ in new] == [pic.data for pic in current]:
        return None  # byte-identical to what's embedded

    pictures = []
    for pos, (p, data, mime, ext) in enumerate(new):
        template = current[pos] if pos < len(current) else None
        if template is not None and template.data == data:
            pictures.append(template)  # untouched, keeps all metadata
        else:
            pictures.append(mf.make_pic(data, mime, ext, p.name, template, pos + 1))
    try:
        mf.finalize_pictures(pictures)
    except SkipFile as exc:
        warn(f"{name}: {exc}; covers left unchanged")
        return None
    return CoverChange(
        pictures=pictures,
        old_desc=[describe_image(pic.data) for pic in current],
        new_desc=[f"{p.name}: {describe_image(d)}" for p, d, _, _ in new],
    )


def plan_file(path: Path, tag_row: dict[str, list[str]] | None,
              cover_files: dict[int, list[Path]]) -> FilePlan:
    mf = open_music(path)
    plan = FilePlan(path)
    if tag_row is not None:
        for key, new in tag_row.items():
            # Empty-string values in a file are indistinguishable from empty
            # csv cells, so they count as "no value" on both sides.
            old = [v for v in mf.get(key) if v != ""]
            if old != new:
                if new:
                    problem = mf.key_problem(key)
                    if problem:
                        raise SkipFile(f"tag {key!r} {problem}")
                plan.tag_changes.append((key, old, new))
        have = {k for k, v in mf.tag_items().items() if any(x != "" for x in v)}
        plan.untracked_tags = sorted(have - set(tag_row) - {RESERVED_KEY})
    plan.cover = plan_covers(mf, cover_files)
    plan.art_without_cover_file = bool(mf.pictures()) and not cover_files
    return plan


def compare_folder(folder: Path) -> Comparison:
    """Compare tags.csv and covers/ against the music files. Writes nothing."""
    csv_path = folder / CSV_NAME
    if not csv_path.is_file():
        raise MersikError(f"{csv_path} not found; run 'mersik init' first")
    files = list_music(folder)
    rows, keys = read_tags_csv(csv_path)
    for fmt in sorted({_FORMATS[p.suffix] for p in files}, key=lambda c: c.label):
        for key in keys:
            if not fmt.valid_key(key):
                raise MersikError(f"{csv_path}: {key!r} is not a valid {fmt.label} tag name")
    names = {p.name for p in files}
    shared = warn_shared_stems(files)
    cover_files = find_cover_files(folder, {p.stem for p in files} - shared)

    plans = []
    for path in files:
        try:
            plans.append(plan_file(path, rows.get(path.name), cover_files.get(path.stem, {})))
        except SkipFile as exc:
            warn(f"{path.name}: {exc}; skipping")
        except Exception as exc:
            warn(f"{path.name}: could not be read ({exc}); skipping")
    return Comparison(
        plans=plans,
        csv_only=sorted(set(rows) - names),
        no_row=sorted(p.name for p in files if p.name not in rows),
    )


def fmt_values(values: list[str]) -> str:
    return "(none)" if not values else "; ".join(f'"{v}"' for v in values)


def print_plans(plans: list[FilePlan]) -> None:
    for plan in plans:
        print(plan.path.name)
        for key, old, new in plan.tag_changes:
            print(f"  {key}: {fmt_values(old)}  ->  {fmt_values(new)}")
        if plan.cover:
            print(f"  cover: {'; '.join(plan.cover.old_desc) or '(none)'}")
            print(f"      -> {'; '.join(plan.cover.new_desc)}")
        print()


def apply_plan(plan: FilePlan) -> None:
    mf = open_music(plan.path)
    for key, _old, new in plan.tag_changes:
        if new:
            mf.set(key, new)
        else:
            mf.remove(key)
    if plan.cover is not None:
        mf.replace_pictures(plan.cover.pictures)
    mf.save()


def cmd_save(path: str | Path) -> None:
    """
    'mersik save [path]': write tags.csv and covers/ back into the music files.

    Tags: for every tag that has a column in tags.csv, the file's values are
    replaced by that row's non-empty cells (so clearing the cells removes the
    tag). Tags with no column, and files with no row, are left alone.

    Covers: a file's pictures are replaced by the images in covers/ named
    after it ('Track.jpg', 'Track_2.png', ...). Files with no matching image
    keep their pictures. Images are embedded byte-for-byte.

    Every pending change is listed per file, then one confirmation is
    requested (default: no) before anything is written.
    """
    folder = Path(path)
    comparison = compare_folder(folder)
    for missing in comparison.csv_only:
        warn(f"{missing} is in {CSV_NAME} but not in {folder}; skipping")

    plans = comparison.changed
    unchanged = len(comparison.plans) - len(plans)
    if not plans:
        print(f"Nothing to save; {unchanged} file(s) already match.")
        return

    print_plans(plans)
    if unchanged:
        print(f"{unchanged} other file(s) already match and won't be touched.\n")
    if not confirm(f"Apply these changes to {len(plans)} file(s)? This overwrites them in place."):
        print("Cancelled; no files were changed.")
        return

    failed = 0
    for plan in plans:
        try:
            apply_plan(plan)
        except Exception as exc:
            failed += 1
            warn(f"{plan.path.name}: save failed ({exc})")
    print(f"Saved {len(plans) - failed} file(s)." + (f" {failed} failed." if failed else ""))
    if failed:
        sys.exit(1)


def cmd_diff(path: str | Path) -> int:
    """
    'mersik diff [path]': report how tags.csv and covers/ differ from the
    music files, without modifying anything. It lists exactly what `save`
    would change (file value vs csv value), plus notes about things `save`
    would ignore. Returns 1 if there are differences, else 0 (like diff(1)).
    """
    folder = Path(path)
    comparison = compare_folder(folder)
    changed = comparison.changed

    for plan in changed:
        print(plan.path.name)
        for key, file_vals, csv_vals in plan.tag_changes:
            print(f"  {key}:")
            print(f"    file: {fmt_values(file_vals)}")
            print(f"    csv:  {fmt_values(csv_vals)}")
        if plan.cover:
            print("  cover:")
            print(f"    file:   {'; '.join(plan.cover.old_desc) or '(none)'}")
            print(f"    covers: {'; '.join(plan.cover.new_desc)}")
        print()

    notes = []
    for name in comparison.csv_only:
        notes.append(f"in {CSV_NAME} but no such file: {name}")
    for name in comparison.no_row:
        notes.append(f"no row in {CSV_NAME} (tags not compared): {name}")
    for plan in comparison.plans:
        if plan.untracked_tags:
            notes.append(f"{plan.path.name}: tags with no column in {CSV_NAME}: "
                         + ", ".join(plan.untracked_tags))
        if plan.art_without_cover_file:
            notes.append(f"{plan.path.name}: has embedded art but no matching image in "
                         f"{COVERS_DIR_NAME}/ (not compared)")
    if notes:
        print("Not compared / ignored by save:")
        for note in notes:
            print(f"  {note}")
        print()

    matching = len(comparison.plans) - len(changed)
    if changed:
        print(f"{len(changed)} file(s) differ, {matching} match.")
        return 1
    print(f"No differences; {matching} file(s) match.")
    return 0


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="mersik", description="FLAC/WavPack tag and cover art editor")
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser(
        "init", help="export tags to tags.csv and cover art to covers/"
    )
    init_parser.add_argument("path", nargs="?", default=".", help="directory with music files")

    save_parser = subparsers.add_parser(
        "save", help="write tags.csv and covers/ back into the music files"
    )
    save_parser.add_argument("path", nargs="?", default=".", help="directory with music files and tags.csv")

    diff_parser = subparsers.add_parser(
        "diff", help="show how tags.csv and covers/ differ from the music files (changes nothing)"
    )
    diff_parser.add_argument("path", nargs="?", default=".", help="directory with music files and tags.csv")
    return parser


def main():
    args = build_parser().parse_args()
    try:
        if args.command == "init":
            cmd_init(args.path)
        elif args.command == "save":
            cmd_save(args.path)
        elif args.command == "diff":
            sys.exit(cmd_diff(args.path))
    except MersikError as exc:
        print(f"error: {exc}", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
