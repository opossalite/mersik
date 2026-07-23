"""Area II -- Column operations (add/duplicate/delete/pin/reorder)."""
from __future__ import annotations

from models import Column


def test_add_column_after_none_first_unpinned(model_with_tracks):
    model = model_with_tracks
    new_col = model.add_column(after=None, key="NEW")
    unpinned = model.zone_columns(pinned=False)
    assert unpinned[0] is new_col


def test_add_column_after_pinned_first_unpinned(model_with_tracks):
    model = model_with_tracks
    pinned_col = model.zone_columns(pinned=True)[0]
    new_col = model.add_column(after=pinned_col, key="NEW")
    unpinned = model.zone_columns(pinned=False)
    assert unpinned[0] is new_col


def test_add_column_after_unpinned_inserted_right(model_with_tracks):
    model = model_with_tracks
    unpinned = model.zone_columns(pinned=False)
    target = unpinned[0]
    new_col = model.add_column(after=target, key="NEW")
    idx_target = model.columns.index(target)
    idx_new = model.columns.index(new_col)
    assert idx_new == idx_target + 1


def test_add_column_tracks_have_slot(model_with_tracks):
    model = model_with_tracks
    new_col = model.add_column(after=None, key="NEW")
    for t in model.tracks:
        assert t.slots[new_col.id] == ""


def test_duplicate_column_same_key_pin(model_with_tracks):
    model = model_with_tracks
    original = model.zone_columns(pinned=False)[0]
    for t in model.tracks:
        t.slots[original.id] = "value"
    dup = model.duplicate_column(original)
    assert dup.key == original.key
    assert dup.pinned == original.pinned
    assert model.columns.index(dup) == model.columns.index(original) + 1
    for t in model.tracks:
        assert t.slots[dup.id] == ""  # empty cells, doesn't copy values


def test_delete_column_removed_from_columns(model_with_tracks):
    model = model_with_tracks
    col = model.columns[0]
    model.delete_column(col)
    assert col not in model.columns


def test_delete_column_removes_slots(model_with_tracks):
    model = model_with_tracks
    col = model.columns[0]
    model.delete_column(col)
    for t in model.tracks:
        assert col.id not in t.slots


def test_toggle_pin_pinned_to_unpinned(model_with_tracks):
    model = model_with_tracks
    pinned_col = model.zone_columns(pinned=True)[0]
    model.toggle_pin(pinned_col)
    assert pinned_col.pinned is False
    unpinned = model.zone_columns(pinned=False)
    assert unpinned[0] is pinned_col  # near edge of unpinned zone


def test_toggle_pin_unpinned_to_pinned(model_with_tracks):
    model = model_with_tracks
    unpinned_col = model.zone_columns(pinned=False)[0]
    model.toggle_pin(unpinned_col)
    assert unpinned_col.pinned is True
    pinned = model.zone_columns(pinned=True)
    assert pinned[-1] is unpinned_col  # far edge of pinned zone, next to divider


def test_reorder_column_pinned_zone(model_with_tracks):
    model = model_with_tracks
    # Give a second pinned column to make reordering observable.
    extra = Column.new("ALBUMARTIST", pinned=True)
    model.columns.insert(0, extra)
    for t in model.tracks:
        t.slots[extra.id] = "x"
    pinned = model.zone_columns(pinned=True)
    first, second = pinned[0], pinned[1]
    model.reorder_column(first, 1)
    new_pinned = model.zone_columns(pinned=True)
    assert new_pinned[0] is second
    assert new_pinned[1] is first


def test_reorder_column_unpinned_zone(model_with_tracks):
    model = model_with_tracks
    unpinned = model.zone_columns(pinned=False)
    first, second = unpinned[0], unpinned[1]
    model.reorder_column(first, 1)
    new_unpinned = model.zone_columns(pinned=False)
    assert new_unpinned[0] is second
    assert new_unpinned[1] is first


def test_reorder_column_blocked_at_edge(model_with_tracks):
    model = model_with_tracks
    unpinned = model.zone_columns(pinned=False)
    first = unpinned[0]
    before = list(model.columns)
    model.reorder_column(first, -1)  # already leftmost in its zone
    assert model.columns == before


def test_set_pinned_value_broadcasts(model_with_tracks):
    model = model_with_tracks
    pinned_col = model.zone_columns(pinned=True)[0]
    model.set_pinned_value(pinned_col, "Broadcast Value")
    for t in model.tracks:
        assert t.slots[pinned_col.id] == "Broadcast Value"
