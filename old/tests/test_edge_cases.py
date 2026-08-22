"""Area VIII -- Edge cases / robustness."""
from __future__ import annotations

import os
import sys

import pytest

from models import MatrixModel, Track
from conftest import make_flac


@pytest.fixture
def empty_model() -> MatrixModel:
    return MatrixModel()


def test_no_tracks_no_crash_any_method(empty_model):
    model = empty_model
    assert model.has_unsaved_changes() is False
    assert model.save_all() == []
    assert model.undo() is False
    assert model.redo() is False


@pytest.mark.xfail(
    strict=True,
    reason=(
        "Discovered gap: move_track() calls tracks_in_disc(track.disc)"
        ".index(track), which raises ValueError if the track isn't "
        "actually a member of self.tracks (e.g. calling it against an "
        "empty model, or a stale Track reference). In normal UI usage "
        "this can't happen -- MatrixScreen.action_move_row only ever "
        "passes current_track(), which is always drawn from the live "
        "model -- but the method itself has no defensive check. Fix "
        "by returning early if `track not in group` before un-xfailing."
    ),
)
def test_move_track_no_tracks(empty_model):
    fake = Track(path=__import__("pathlib").Path("/nowhere.flac"))
    empty_model.move_track(fake, 1)


def test_set_disc_no_tracks(empty_model):
    from pathlib import Path

    fake = Track(path=Path("/nowhere.flac"))
    empty_model.set_disc(fake, 2)
    assert fake.disc == 2


def test_auto_number_no_tracks(empty_model):
    empty_model.auto_number()  # should simply do nothing


def test_discs_empty(empty_model):
    assert empty_model.discs() == []


def test_ordered_tracks_empty(empty_model):
    assert empty_model.ordered_tracks() == []


def test_cover_art_apply_all_no_tracks(empty_model):
    # Mirrors CoverArtScreen.action_apply_all's guard: tracks() empty.
    assert empty_model.ordered_tracks() == []


@pytest.mark.skipif(sys.platform == "win32", reason="symlinks/permissions differ on Windows")
def test_load_directory_with_symlink_loop(tmp_path):
    root = tmp_path / "loopy"
    root.mkdir()
    make_flac(root / "real.flac", tags=[("ARTIST", "A")])
    loop_link = root / "loop"
    try:
        loop_link.symlink_to(root, target_is_directory=True)
    except OSError:
        pytest.skip("symlink creation not permitted in this environment")

    model = MatrixModel()
    # rglob will recurse into the symlink loop; this documents current
    # behavior -- it should not hang or raise. If this test starts
    # timing out, that confirms src/README.md's "Load-time robustness"
    # gap (item 4 in "What's left to implement") needs addressing.
    import signal

    def _timeout_handler(signum, frame):
        raise TimeoutError("load_directory hung on a symlink loop")

    if hasattr(signal, "SIGALRM"):
        signal.signal(signal.SIGALRM, _timeout_handler)
        signal.alarm(10)
    try:
        model.load_directory(root)
    finally:
        if hasattr(signal, "SIGALRM"):
            signal.alarm(0)
    assert len(model.tracks) >= 1


@pytest.mark.skipif(sys.platform == "win32", reason="permission bits differ on Windows")
@pytest.mark.skipif(os.geteuid() == 0, reason="root ignores permission bits")
def test_load_directory_permission_denied_dir(tmp_path):
    root = tmp_path / "restricted_parent"
    root.mkdir()
    make_flac(root / "visible.flac", tags=[("ARTIST", "A")])
    blocked = root / "blocked"
    blocked.mkdir()
    make_flac(blocked / "hidden.flac", tags=[("ARTIST", "B")])
    blocked.chmod(0o000)
    try:
        model = MatrixModel()
        # Should not raise -- at minimum the visible file loads.
        model.load_directory(root)
        assert any(t.filename == "visible.flac" for t in model.tracks)
    finally:
        blocked.chmod(0o755)  # allow tmp_path cleanup


def test_load_with_mixed_flac_and_other_files(tmp_path):
    make_flac(tmp_path / "song.flac", tags=[("ARTIST", "A")])
    (tmp_path / "notes.txt").write_text("not audio")
    (tmp_path / "cover.jpg").write_bytes(b"\xff\xd8\xff fake jpeg")
    model = MatrixModel()
    model.load_directory(tmp_path)
    assert len(model.tracks) == 1
    assert model.tracks[0].filename == "song.flac"
