"""Area III -- Disc / ordering / auto-number."""
from __future__ import annotations

from pathlib import Path

from models import Track


def test_discs_sorted_unique(model_with_tracks):
    model = model_with_tracks
    assert model.discs() == [1, 2]


def test_tracks_in_disc_sorted_by_position(model_with_tracks):
    model = model_with_tracks
    group = model.tracks_in_disc(1)
    positions = [t.position for t in group]
    assert positions == sorted(positions)


def test_ordered_tracks_interleaves_discs(model_with_tracks):
    model = model_with_tracks
    ordered = model.ordered_tracks()
    discs = [t.disc for t in ordered]
    assert discs == sorted(discs)
    assert len(ordered) == 3


def test_move_track_within_disc(model_with_tracks):
    model = model_with_tracks
    group = model.tracks_in_disc(1)
    t0, t1 = group[0], group[1]
    model.move_track(t0, 1)
    new_group = model.tracks_in_disc(1)
    assert new_group[0] is t1
    assert new_group[1] is t0


def test_move_track_boundary_blocked(model_with_tracks):
    model = model_with_tracks
    group = model.tracks_in_disc(1)
    first = group[0]
    model.move_track(first, -1)  # already at top
    assert model.tracks_in_disc(1)[0] is first


def test_set_disc_lower(model_with_tracks):
    model = model_with_tracks
    track_on_disc2 = model.tracks_in_disc(2)[0]
    model.set_disc(track_on_disc2, 1)
    assert track_on_disc2.disc == 1
    assert track_on_disc2 in model.tracks_in_disc(1)


def test_set_disc_higher_creates_new(model_with_tracks):
    model = model_with_tracks
    track = model.tracks_in_disc(1)[0]
    model.set_disc(track, 3)
    assert track.disc == 3
    assert 3 in model.discs()


def test_set_disc_below_one_blocked(model_with_tracks):
    model = model_with_tracks
    track = model.tracks_in_disc(1)[0]
    original_disc = track.disc
    model.set_disc(track, 0)
    assert track.disc == original_disc


def test_auto_number_single_disc():
    from models import MatrixModel

    model = MatrixModel()
    model.tracks = [
        Track(path=Path(f"/t{i}.flac"), disc=1, position=i) for i in range(3)
    ]
    model.auto_number()
    numbers = sorted(t.computed_tracknumber for t in model.tracks)
    assert numbers == [1, 2, 3]


def test_auto_number_multi_disc(model_with_tracks):
    model = model_with_tracks
    model.auto_number()
    for disc in model.discs():
        group = model.tracks_in_disc(disc)
        numbers = [t.computed_tracknumber for t in group]
        assert numbers == list(range(1, len(group) + 1))


def test_auto_number_writes_computed_attrs(model_with_tracks):
    model = model_with_tracks
    model.auto_number()
    for t in model.tracks:
        assert t.computed_tracknumber is not None
        assert t.computed_tracktotal is not None
        assert t.computed_discnumber is not None
        assert t.computed_disctotal is not None


def test_auto_number_resets_old(model_with_tracks):
    model = model_with_tracks
    model.auto_number()
    track = model.tracks[0]
    track.computed_tracknumber = 999
    model.auto_number()
    assert track.computed_tracknumber != 999


def test_auto_number_disc_total_correct(model_with_tracks):
    model = model_with_tracks
    model.auto_number()
    for t in model.tracks:
        assert t.computed_disctotal == len(model.discs())
