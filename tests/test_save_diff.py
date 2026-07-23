"""Area IV -- Effective tags / diff / save (`models.py`)."""
from __future__ import annotations

import pytest
from mutagen.flac import FLAC

from models import MatrixModel


def test_get_effective_tags_no_changes(model_with_tracks):
    model = model_with_tracks
    track = model.tracks[0]
    tags = model.get_effective_tags(track)
    for k, v in track.original_tags:
        assert (k, v) in tags


def test_get_effective_tags_with_changes(model_with_tracks):
    model = model_with_tracks
    track = model.tracks[0]
    title_col = next(c for c in model.columns if c.key == "TITLE")
    track.slots[title_col.id] = "Changed Title"
    tags = model.get_effective_tags(track)
    assert ("TITLE", "Changed Title") in tags


def test_get_effective_tags_empty_skipped(model_with_tracks):
    model = model_with_tracks
    track = model.tracks[0]
    title_col = next(c for c in model.columns if c.key == "TITLE")
    track.slots[title_col.id] = "   "
    tags = model.get_effective_tags(track)
    assert not any(k == "TITLE" for k, _ in tags)


def test_get_effective_tags_includes_structural(model_with_tracks):
    model = model_with_tracks
    model.auto_number()
    track = model.tracks[0]
    tags = model.get_effective_tags(track)
    keys = {k for k, _ in tags}
    assert "TRACKNUMBER" in keys
    assert "DISCNUMBER" in keys


def test_diff_for_track_no_changes(model_with_tracks):
    model = model_with_tracks
    track = model.tracks[0]
    assert model.diff_for_track(track) == []


def test_diff_for_track_value_changed(model_with_tracks):
    model = model_with_tracks
    track = model.tracks[0]
    artist_col = next(c for c in model.columns if c.key == "ARTIST")
    track.slots[artist_col.id] = "New Artist"
    changes = model.diff_for_track(track)
    assert any("ARTIST" in c and "New Artist" in c for c in changes)


def test_diff_for_track_key_added(model_with_tracks):
    model = model_with_tracks
    track = model.tracks[0]
    new_col = model.add_column(after=None, key="NEWKEY")
    track.slots[new_col.id] = "value"
    changes = model.diff_for_track(track)
    assert any("NEWKEY" in c for c in changes)


def test_diff_for_track_key_removed(model_with_tracks):
    model = model_with_tracks
    track = model.tracks[0]
    title_col = next(c for c in model.columns if c.key == "TITLE")
    track.slots[title_col.id] = ""
    changes = model.diff_for_track(track)
    assert any("TITLE" in c for c in changes)


def test_diff_for_track_cover_changed(model_with_tracks):
    model = model_with_tracks
    track = model.tracks[0]
    track.original_cover = None
    track.cover_art = b"fake-image-bytes"
    changes = model.diff_for_track(track)
    assert "cover art changed" in changes


def test_diff_for_track_multiple_keys(model_with_tracks):
    model = model_with_tracks
    track = model.tracks[0]
    artist_col = next(c for c in model.columns if c.key == "ARTIST")
    title_col = next(c for c in model.columns if c.key == "TITLE")
    track.slots[artist_col.id] = "X"
    track.slots[title_col.id] = "Y"
    changes = model.diff_for_track(track)
    assert len(changes) >= 2


def test_has_unsaved_changes_true(model_with_tracks):
    model = model_with_tracks
    artist_col = next(c for c in model.columns if c.key == "ARTIST")
    model.tracks[0].slots[artist_col.id] = "Changed"
    assert model.has_unsaved_changes() is True


def test_has_unsaved_changes_false(model_with_tracks):
    model = model_with_tracks
    assert model.has_unsaved_changes() is False


def test_save_all_success_updates_original(temp_flac_dir):
    model = MatrixModel()
    model.load_directory(temp_flac_dir)
    track = model.tracks[0]
    artist_col = next(c for c in model.columns if c.key == "ARTIST")
    track.slots[artist_col.id] = "Renamed Artist"
    failures = model.save_all()
    assert failures == []
    assert ("ARTIST", "Renamed Artist") in track.original_tags
    on_disk = FLAC(track.path)
    assert ("ARTIST", "Renamed Artist") in list(on_disk.tags)


def test_save_all_partial_failure(temp_flac_dir):
    model = MatrixModel()
    model.load_directory(temp_flac_dir)
    good_track, bad_track = model.tracks[0], model.tracks[1]
    bad_track.path = bad_track.path.parent / "does_not_exist.flac"
    failures = model.save_all()
    failed_tracks = [t for t, _ in failures]
    assert bad_track in failed_tracks
    assert good_track not in failed_tracks


@pytest.mark.xfail(
    strict=True,
    reason=(
        "Discovered gap: Track.write_to_disk() only writes tag-column "
        "slots and never reads track.computed_tracknumber/tracktotal/"
        "discnumber/disctotal. get_effective_tags() (used for the "
        "save-diff preview) DOES include the computed structural "
        "fields, so the diff screen can show TRACKNUMBER/DISCNUMBER "
        "changes that then silently fail to land on disk after "
        "confirming save. Fix by having write_to_disk consult the "
        "same computed_* attrs (or by having save_all() write them "
        "directly) before un-xfailing this test."
    ),
)
def test_save_writes_structural_tags(temp_flac_dir):
    model = MatrixModel()
    model.load_directory(temp_flac_dir)
    model.auto_number()
    track = model.tracks[0]
    model.save_all()
    on_disk = FLAC(track.path)
    keys = {k for k, _ in on_disk.tags}
    assert "TRACKNUMBER" in keys
    assert "DISCNUMBER" in keys
