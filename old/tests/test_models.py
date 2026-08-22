"""Area I -- Data model & loader (`models.py`)."""
from __future__ import annotations

from pathlib import Path

import pytest
from conftest import make_flac

from models import (
    STANDARD_KEYS,
    STRUCTURAL_KEYS,
    Column,
    MatrixModel,
    Track,
    ThumbnailCache,
    sniff_mime,
)

# ---- sniff_mime -----------------------------------------------------


def test_sniff_mime_jpeg():
    assert sniff_mime(b"\xff\xd8\xff\x00rest") == "image/jpeg"


def test_sniff_mime_png():
    assert sniff_mime(b"\x89PNG\r\n\x1a\nrest") == "image/png"


def test_sniff_mime_gif87():
    assert sniff_mime(b"GIF87arest") == "image/gif"


def test_sniff_mime_gif89():
    assert sniff_mime(b"GIF89arest") == "image/gif"


def test_sniff_mime_fallback():
    assert sniff_mime(b"not an image") == "image/jpeg"


# ---- Column -----------------------------------------------------------


def test_column_new_id_increments():
    a = Column.new("A", pinned=False)
    b = Column.new("B", pinned=False)
    assert b.id > a.id


def test_column_new_pinned_state():
    c = Column.new("ALBUM", pinned=True)
    assert c.key == "ALBUM"
    assert c.pinned is True


# ---- Track defaults -----------------------------------------------------


def test_track_filename():
    t = Track(path=Path("/x/y/song.flac"))
    assert t.filename == "song.flac"


def test_track_slots_default_empty():
    t = Track(path=Path("/x.flac"))
    assert t.slots == {}


def test_track_disc_default_one():
    t = Track(path=Path("/x.flac"))
    assert t.disc == 1


def test_track_position_default_zero():
    t = Track(path=Path("/x.flac"))
    assert t.position == 0


def test_track_cover_art_default_none():
    t = Track(path=Path("/x.flac"))
    assert t.cover_art is None


# ---- ThumbnailCache -----------------------------------------------------


def test_thumbnail_cache_get_none_returns_none():
    cache = ThumbnailCache()
    assert cache.get(None) is None


def test_thumbnail_cache_put_and_get(png_bytes):
    cache = ThumbnailCache()
    img1 = cache.get(png_bytes)
    img2 = cache.get(png_bytes)
    assert img1 is not None
    assert img1 is img2  # same bytes -> same cached object, no re-decode


def test_thumbnail_cache_lru_eviction():
    cache = ThumbnailCache(max_entries=2)
    from conftest import make_png_bytes

    b1, b2, b3 = make_png_bytes(color=(1, 0, 0)), make_png_bytes(color=(0, 1, 0)), make_png_bytes(color=(0, 0, 1))
    cache.get(b1)
    cache.get(b2)
    cache.get(b3)  # should evict b1
    assert b1 not in cache._cache
    assert b2 in cache._cache
    assert b3 in cache._cache


def test_thumbnail_cache_same_bytes_same_object(png_bytes):
    cache = ThumbnailCache()
    img1 = cache.get(png_bytes)
    img2 = cache.get(bytes(png_bytes))  # equal but distinct bytes object
    assert img1 is img2


# ---- MatrixModel.load_directory -----------------------------------------


def test_matrix_model_empty_after_no_flac(temp_empty_dir):
    model = MatrixModel()
    failures = model.load_directory(temp_empty_dir)
    assert failures == []
    assert model.tracks == []
    assert model.columns == []


def test_load_single_flac_populates_tracks(tmp_path):
    make_flac(tmp_path / "one.flac", tags=[("ARTIST", "A")])
    model = MatrixModel()
    model.load_directory(tmp_path)
    assert len(model.tracks) == 1
    assert model.tracks[0].filename == "one.flac"


def test_load_recursive_finds_subdirs(tmp_path):
    make_flac(tmp_path / "disc1" / "a.flac", tags=[("ARTIST", "A")])
    make_flac(tmp_path / "disc2" / "b.flac", tags=[("ARTIST", "B")])
    model = MatrixModel()
    model.load_directory(tmp_path)
    assert len(model.tracks) == 2


def test_load_skips_corrupt_file(tmp_path):
    good = tmp_path / "good.flac"
    make_flac(good, tags=[("ARTIST", "A")])
    bad = tmp_path / "bad.flac"
    bad.write_bytes(b"not a real flac file")
    model = MatrixModel()
    failures = model.load_directory(tmp_path)
    assert len(model.tracks) == 1
    assert len(failures) == 1
    assert failures[0][0] == bad


def test_load_auto_pin_standard_same_value(temp_flac_dir):
    model = MatrixModel()
    model.load_directory(temp_flac_dir)
    album_cols = [c for c in model.columns if c.key == "ALBUM"]
    assert len(album_cols) == 1
    assert album_cols[0].pinned is True


def test_load_standard_key_pinned_even_if_values_differ(temp_flac_dir):
    """`pinned = is_standard OR (all_same and i==0)` -- being in
    STANDARD_KEYS pins a column unconditionally, regardless of whether
    every track agrees on the value. (src/README.md's "won't pin if
    all values are not identical" line describes an AND relationship
    the current implementation doesn't actually have -- see
    "Additional features to implement" item 6 in src/README.md, which
    already flags this as intended *future* behavior, not a bug.)"""
    model = MatrixModel()
    model.load_directory(temp_flac_dir)
    artist_cols = [c for c in model.columns if c.key == "ARTIST"]
    assert len(artist_cols) == 1
    assert artist_cols[0].pinned is True


def test_load_non_standard_same_value_also_pinned(tmp_path):
    """Because the pinning condition is an OR, a non-standard key with
    an identical value across every track is *also* auto-pinned, not
    just STANDARD_KEYS members. This is the behavior src/README.md
    flags with "the name of which should probably be changed
    internally"."""
    make_flac(tmp_path / "a.flac", tags=[("CUSTOM", "same")])
    make_flac(tmp_path / "b.flac", tags=[("CUSTOM", "same")])
    model = MatrixModel()
    model.load_directory(tmp_path)
    custom_cols = [c for c in model.columns if c.key == "CUSTOM"]
    assert len(custom_cols) == 1
    assert custom_cols[0].pinned is True


def test_load_non_standard_different_value_unpinned(tmp_path):
    make_flac(tmp_path / "a.flac", tags=[("CUSTOM", "one")])
    make_flac(tmp_path / "b.flac", tags=[("CUSTOM", "two")])
    model = MatrixModel()
    model.load_directory(tmp_path)
    custom_cols = [c for c in model.columns if c.key == "CUSTOM"]
    assert len(custom_cols) == 1
    assert custom_cols[0].pinned is False


def test_load_duplicate_keys_separate_columns(temp_flac_dir):
    model = MatrixModel()
    model.load_directory(temp_flac_dir)
    rg_cols = [c for c in model.columns if c.key == "REPLAYGAIN_TRACK_GAIN"]
    assert len(rg_cols) == 2
    assert rg_cols[0].id != rg_cols[1].id


def test_load_structural_keys_not_columns(temp_multidisc_dir):
    model = MatrixModel()
    model.load_directory(temp_multidisc_dir)
    keys = {c.key for c in model.columns}
    assert keys.isdisjoint(STRUCTURAL_KEYS)


def test_load_disc_from_tag(temp_multidisc_dir):
    model = MatrixModel()
    model.load_directory(temp_multidisc_dir)
    discs = {t.filename: t.disc for t in model.tracks}
    assert discs["d1t1.flac"] == 1
    assert discs["d2t1.flac"] == 2


def test_load_default_disc_one(tmp_path):
    make_flac(tmp_path / "a.flac", tags=[("ARTIST", "A")])
    model = MatrixModel()
    model.load_directory(tmp_path)
    assert model.tracks[0].disc == 1


def test_load_cover_art_stored(temp_flac_dir):
    model = MatrixModel()
    model.load_directory(temp_flac_dir)
    track = next(t for t in model.tracks if t.filename == "01.flac")
    assert track.cover_art is not None


def test_load_no_cover_art_none(temp_flac_dir):
    model = MatrixModel()
    model.load_directory(temp_flac_dir)
    track = next(t for t in model.tracks if t.filename == "02.flac")
    assert track.cover_art is None


def test_load_original_tags_copied(tmp_path):
    make_flac(tmp_path / "a.flac", tags=[("ARTIST", "A"), ("TITLE", "T")])
    model = MatrixModel()
    model.load_directory(tmp_path)
    assert ("ARTIST", "A") in model.tracks[0].original_tags
    assert ("TITLE", "T") in model.tracks[0].original_tags


def test_load_original_cover_copied(temp_flac_dir):
    model = MatrixModel()
    model.load_directory(temp_flac_dir)
    track = next(t for t in model.tracks if t.filename == "01.flac")
    assert track.original_cover == track.cover_art


def test_columns_sorted_pinned_first(temp_flac_dir):
    model = MatrixModel()
    model.load_directory(temp_flac_dir)
    pinned_flags = [c.pinned for c in model.columns]
    # once it becomes False it should never go back to True
    assert pinned_flags == sorted(pinned_flags, reverse=True)


def test_columns_preserve_first_seen_order(tmp_path):
    # Differing values per track so neither key gets auto-pinned,
    # keeping both in the unpinned, first-seen-order zone.
    make_flac(tmp_path / "a.flac", tags=[("ZKEY", "1"), ("AKEY", "2")])
    make_flac(tmp_path / "b.flac", tags=[("ZKEY", "9"), ("AKEY", "8")])
    model = MatrixModel()
    model.load_directory(tmp_path)
    unpinned_keys = [c.key for c in model.columns if not c.pinned]
    assert unpinned_keys.index("ZKEY") < unpinned_keys.index("AKEY")


def test_load_fresh_album_defaults(tmp_path):
    make_flac(tmp_path / "a.flac", tags=[])
    model = MatrixModel()
    model.load_directory(tmp_path)
    keys = {c.key for c in model.columns}
    assert keys == set(STANDARD_KEYS) - STRUCTURAL_KEYS


def test_load_all_tags_identical_standard_pinned(tmp_path):
    make_flac(tmp_path / "a.flac", tags=[("DATE", "2020")])
    make_flac(tmp_path / "b.flac", tags=[("DATE", "2020")])
    model = MatrixModel()
    model.load_directory(tmp_path)
    date_col = next(c for c in model.columns if c.key == "DATE")
    assert date_col.pinned is True
