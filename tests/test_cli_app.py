"""Area VI -- CLI / App initialization (`app.py`)."""
from __future__ import annotations

import sys

import pytest

import app as app_module
from app import MatrixScreen, MersikApp


def test_main_no_args_exits_1(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["app.py"])
    with pytest.raises(SystemExit) as exc:
        app_module.main()
    assert exc.value.code == 1


def test_main_non_directory_exits_1(monkeypatch, tmp_path):
    not_a_dir = tmp_path / "nope.txt"
    not_a_dir.write_text("x")
    monkeypatch.setattr(sys, "argv", ["app.py", str(not_a_dir)])
    with pytest.raises(SystemExit) as exc:
        app_module.main()
    assert exc.value.code == 1


def test_main_creates_app_with_model(monkeypatch, tmp_path, temp_flac_dir):
    created = {}
    monkeypatch.setattr(sys, "argv", ["app.py", str(temp_flac_dir)])

    class FakeApp(MersikApp):
        def run(self):  # avoid actually launching the TUI
            created["instance"] = self

    monkeypatch.setattr(app_module, "MersikApp", FakeApp)
    app_module.main()
    assert isinstance(created["instance"].model, app_module.MatrixModel)


@pytest.mark.asyncio
async def test_app_loads_directory_on_mount(temp_flac_dir):
    app = MersikApp(temp_flac_dir)
    async with app.run_test():
        assert len(app.model.tracks) == 2


@pytest.mark.asyncio
async def test_app_pushes_matrix_screen(temp_flac_dir):
    app = MersikApp(temp_flac_dir)
    async with app.run_test():
        assert isinstance(app.screen, MatrixScreen)


@pytest.mark.asyncio
async def test_app_notifies_load_failures(temp_flac_dir):
    (temp_flac_dir / "corrupt.flac").write_bytes(b"not a flac")
    app = MersikApp(temp_flac_dir)
    async with app.run_test() as pilot:
        await pilot.pause()
        # A failure notification should have been raised.
        assert any("skipped" in n.message for n in app._notifications)


@pytest.mark.asyncio
async def test_app_no_notification_on_success(temp_flac_dir):
    app = MersikApp(temp_flac_dir)
    async with app.run_test() as pilot:
        await pilot.pause()
        assert not any("skipped" in n.message for n in app._notifications)
