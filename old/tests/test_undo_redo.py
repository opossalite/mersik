"""Area V -- Undo / redo history."""
from __future__ import annotations


def test_undo_no_stack(model_with_tracks):
    model = model_with_tracks
    assert model.undo() is False


def test_undo_one_step(model_with_tracks):
    model = model_with_tracks
    artist_col = next(c for c in model.columns if c.key == "ARTIST")
    original_value = model.tracks[0].slots[artist_col.id]
    model.push_history()
    model.tracks[0].slots[artist_col.id] = "Changed"
    assert model.undo() is True
    # after undo, the *object* was replaced by the snapshot's deep copy
    restored_track = next(t for t in model.tracks if t.path == model.tracks[0].path)
    restored_col = next(c for c in model.columns if c.key == "ARTIST")
    assert restored_track.slots[restored_col.id] == original_value


def test_undo_multiple_steps(model_with_tracks):
    model = model_with_tracks
    artist_col = next(c for c in model.columns if c.key == "ARTIST")

    model.push_history()
    model.tracks[0].slots[artist_col.id] = "First"

    model.push_history()
    model.tracks[0].slots[artist_col.id] = "Second"

    model.undo()
    col = next(c for c in model.columns if c.key == "ARTIST")
    assert model.tracks[0].slots[col.id] == "First"

    model.undo()
    col = next(c for c in model.columns if c.key == "ARTIST")
    assert model.tracks[0].slots[col.id] != "First"


def test_redo_no_stack(model_with_tracks):
    model = model_with_tracks
    assert model.redo() is False


def test_redo_after_undo(model_with_tracks):
    model = model_with_tracks
    artist_col = next(c for c in model.columns if c.key == "ARTIST")
    model.push_history()
    model.tracks[0].slots[artist_col.id] = "Changed"
    model.undo()
    assert model.redo() is True
    col = next(c for c in model.columns if c.key == "ARTIST")
    assert model.tracks[0].slots[col.id] == "Changed"


def test_new_action_clears_redo(model_with_tracks):
    model = model_with_tracks
    artist_col = next(c for c in model.columns if c.key == "ARTIST")
    model.push_history()
    model.tracks[0].slots[artist_col.id] = "Changed"
    model.undo()
    assert model._redo_stack  # something to redo

    model.push_history()  # a fresh mutating action
    model.tracks[0].slots[next(c for c in model.columns if c.key == "ARTIST").id] = "Another"
    assert model._redo_stack == []


def test_history_limit_cap(model_with_tracks):
    model = model_with_tracks
    for _ in range(101):
        model.push_history()
    assert len(model._undo_stack) == 100


def test_cover_art_sharing_across_snapshots(model_with_tracks):
    model = model_with_tracks
    shared = b"shared-cover-bytes"
    model.tracks[0].cover_art = shared
    model.push_history()
    snapshot_tracks = model._undo_stack[-1][1]
    snapshot_track = next(t for t in snapshot_tracks if t.path == model.tracks[0].path)
    assert snapshot_track.cover_art is shared  # bytes treated as atomic by deepcopy


def test_undo_deep_copy_independent(model_with_tracks):
    model = model_with_tracks
    artist_col = next(c for c in model.columns if c.key == "ARTIST")
    model.push_history()
    snapshot_track = model._undo_stack[-1][1][0]
    model.tracks[0].slots[artist_col.id] = "Mutated After Snapshot"
    # the snapshot must not have changed alongside the live object
    snapshot_col = model._undo_stack[-1][0][0]
    assert snapshot_track.slots is not model.tracks[0].slots
