"""Shared fixtures for the mersik test suite.

Adds ../src to sys.path (app.py/models.py use plain top-level imports,
not a package), and provides helpers for building synthetic FLAC files
and in-memory model state without touching disk.
"""
from __future__ import annotations

import io
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from PIL import Image as PILImage

SRC_DIR = Path(__file__).resolve().parent.parent / "src"
sys.path.insert(0, str(SRC_DIR))

from models import Column, MatrixModel, Track  # noqa: E402

FFMPEG_AVAILABLE = shutil.which("ffmpeg") is not None


def _encode_silent_flac(path: Path, duration: float = 0.1) -> None:
    """Encode a tiny silent FLAC file at `path` using ffmpeg."""
    subprocess.run(
        [
            "ffmpeg",
            "-f", "lavfi",
            "-i", f"anullsrc=r=44100:cl=mono",
            "-t", str(duration),
            "-y",
            str(path),
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def make_flac(
    path: Path,
    tags: list[tuple[str, str]] | None = None,
    picture: bytes | None = None,
) -> Path:
    """Create a real, valid FLAC file at `path` with exactly the given
    (key, value) tag pairs (duplicates allowed) and optional embedded
    cover art. Requires ffmpeg to synthesize the audio stream."""
    from mutagen.flac import FLAC, Picture

    path.parent.mkdir(parents=True, exist_ok=True)
    _encode_silent_flac(path)
    audio = FLAC(path)
    if audio.tags is None:
        audio.add_tags()
    audio.tags.clear()
    for key, value in tags or []:
        audio.tags.append((key, value))
    audio.clear_pictures()
    if picture is not None:
        pic = Picture()
        pic.data = picture
        pic.type = 3
        pic.mime = "image/png"
        audio.add_picture(pic)
    audio.save()
    return path


def make_png_bytes(size: tuple[int, int] = (4, 4), color=(255, 0, 0)) -> bytes:
    img = PILImage.new("RGB", size, color)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


@pytest.fixture(scope="session", autouse=True)
def _require_ffmpeg():
    if not FFMPEG_AVAILABLE:
        pytest.skip("ffmpeg not available; cannot synthesize FLAC fixtures", allow_module_level=True)


@pytest.fixture
def png_bytes() -> bytes:
    return make_png_bytes()


@pytest.fixture
def temp_empty_dir(tmp_path: Path) -> Path:
    d = tmp_path / "empty_album"
    d.mkdir()
    return d


@pytest.fixture
def temp_flac_dir(tmp_path: Path, png_bytes: bytes) -> Path:
    """A small two-track, single-disc album: same ALBUM/ALBUMARTIST,
    different ARTIST/TITLE, one duplicate-key case, one embedded cover."""
    root = tmp_path / "album"
    make_flac(
        root / "01.flac",
        tags=[
            ("ALBUMARTIST", "Various"),
            ("ALBUM", "Comp"),
            ("ARTIST", "Alice"),
            ("TITLE", "Song One"),
            ("DATE", "2020"),
            ("REPLAYGAIN_TRACK_GAIN", "-3.0 dB"),
            ("REPLAYGAIN_TRACK_GAIN", "-4.0 dB"),
        ],
        picture=png_bytes,
    )
    make_flac(
        root / "02.flac",
        tags=[
            ("ALBUMARTIST", "Various"),
            ("ALBUM", "Comp"),
            ("ARTIST", "Bob"),
            ("TITLE", "Song Two"),
            ("DATE", "2020"),
        ],
    )
    return root


@pytest.fixture
def temp_multidisc_dir(tmp_path: Path) -> Path:
    """Two discs, two tracks each, DISCNUMBER tags present."""
    root = tmp_path / "multidisc"
    make_flac(root / "d1t1.flac", tags=[("DISCNUMBER", "1"), ("TITLE", "A1")])
    make_flac(root / "d1t2.flac", tags=[("DISCNUMBER", "1"), ("TITLE", "A2")])
    make_flac(root / "d2t1.flac", tags=[("DISCNUMBER", "2"), ("TITLE", "B1")])
    make_flac(root / "d2t2.flac", tags=[("DISCNUMBER", "2"), ("TITLE", "B2")])
    return root


@pytest.fixture
def model_with_tracks() -> MatrixModel:
    """Pre-populated MatrixModel built entirely in-memory (no disk I/O),
    with 3 tracks across 2 discs and a mix of pinned/unpinned columns.
    Fast + deterministic for column/undo/disc-ordering tests."""
    model = MatrixModel()

    col_album = Column.new("ALBUM", pinned=True)
    col_artist = Column.new("ARTIST", pinned=False)
    col_title = Column.new("TITLE", pinned=False)
    model.columns = [col_album, col_artist, col_title]

    t1 = Track(path=Path("/fake/t1.flac"), disc=1, position=0)
    t2 = Track(path=Path("/fake/t2.flac"), disc=1, position=1)
    t3 = Track(path=Path("/fake/t3.flac"), disc=2, position=0)
    for t, artist, title in ((t1, "Alice", "One"), (t2, "Alice", "Two"), (t3, "Bob", "Three")):
        t.slots[col_album.id] = "Comp"
        t.slots[col_artist.id] = artist
        t.slots[col_title.id] = title
        t.original_tags = [
            ("ALBUM", "Comp"),
            ("ARTIST", artist),
            ("TITLE", title),
        ]
    model.tracks = [t1, t2, t3]
    return model
