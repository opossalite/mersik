import csv
import io
import subprocess
import sys
from pathlib import Path

import pytest
from mutagen.flac import FLAC, Picture
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import mersik  # noqa: E402


def make_image(fmt: str, size=(1800, 1200), color=(200, 30, 60)) -> bytes:
    buf = io.BytesIO()
    Image.effect_noise(size, 40).convert("RGB").save(buf, fmt)  # noisy => big, incompressible
    return buf.getvalue()


def make_flac(path: Path, **tags) -> Path:
    subprocess.run(
        ["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "sine=d=0.2", str(path)],
        check=True,
    )
    audio = FLAC(path)
    for k, v in tags.items():
        audio[k] = v
    audio.save()
    return path


def embed(path: Path, data: bytes, mime: str, ptype=3):
    audio = FLAC(path)
    pic = Picture()
    pic.data, pic.mime, pic.type = data, mime, ptype
    pic.width, pic.height, pic.depth = 1, 1, 24
    audio.add_picture(pic)
    audio.save()


@pytest.fixture
def answers(monkeypatch):
    """Queue of replies to confirmation prompts; an empty queue answers 'n'."""
    queue = []
    monkeypatch.setattr("builtins.input", lambda *_: queue.pop(0) if queue else "n")
    return queue


@pytest.fixture
def album(tmp_path, answers):
    make_flac(tmp_path / "01 - One.flac", title="One", artist=["A", "B"])
    make_flac(tmp_path / "02 - Two.flac", title="Two")
    return tmp_path


def test_only_two_commands():
    parser = mersik.build_parser()
    choices = parser._subparsers._group_actions[0].choices
    assert set(choices) == {"init", "save", "diff"}


def test_init_exports_full_res_and_same_name(album):
    jpg = make_image("JPEG")
    png = make_image("PNG")
    embed(album / "01 - One.flac", jpg, "image/jpeg")
    embed(album / "02 - Two.flac", png, "image/png")
    mersik.cmd_init(album)
    assert (album / "covers" / "01 - One.jpg").read_bytes() == jpg
    assert (album / "covers" / "02 - Two.png").read_bytes() == png
    assert Image.open(album / "covers" / "01 - One.jpg").size == (1800, 1200)
    header = (album / "tags.csv").read_text().splitlines()[0]
    assert header.startswith("filename,artist,artist,")


def test_init_multiple_pictures_get_index(album):
    a, b = make_image("JPEG"), make_image("PNG")
    embed(album / "01 - One.flac", a, "image/jpeg")
    embed(album / "01 - One.flac", b, "image/png", ptype=4)
    mersik.cmd_init(album)
    assert (album / "covers" / "01 - One.jpg").read_bytes() == a
    assert (album / "covers" / "01 - One_2.png").read_bytes() == b


def test_init_csv_decline_keeps_csv_but_still_writes_covers(album, answers):
    (album / "tags.csv").write_text("keep me")
    embed(album / "01 - One.flac", make_image("JPEG"), "image/jpeg")
    answers.append("n")
    mersik.cmd_init(album)
    assert (album / "tags.csv").read_text() == "keep me"
    assert (album / "covers" / "01 - One.jpg").exists()


def test_init_keeps_nonconflicting_and_asks_on_conflict(album, answers):
    data = make_image("JPEG")
    embed(album / "01 - One.flac", data, "image/jpeg")
    covers = album / "covers"
    covers.mkdir()
    (covers / "unrelated.jpg").write_bytes(b"mine")
    (covers / "01 - One.jpg").write_bytes(b"different")

    answers.append("n")  # no csv yet -> only prompt is the cover overwrite
    mersik.cmd_init(album)
    assert (covers / "01 - One.jpg").read_bytes() == b"different"
    assert not (album / "covers" / "02 - Two.jpg").exists()

    answers.extend(["y", "y"])  # csv exists now: overwrite csv, overwrite cover
    mersik.cmd_init(album)
    assert (covers / "01 - One.jpg").read_bytes() == data
    assert (covers / "unrelated.jpg").read_bytes() == b"mine"  # never touched


def test_save_roundtrip_tags_and_decline(album, answers):
    mersik.cmd_init(album)
    with open(album / "tags.csv", newline="") as f:
        rows = list(csv.reader(f))
    col = rows[0].index("title")
    rows[1][col] = "Uno"
    with open(album / "tags.csv", "w", newline="") as f:
        csv.writer(f).writerows(rows)
    answers.append("n")
    mersik.cmd_save(album)
    assert FLAC(album / "01 - One.flac")["title"] == ["One"]  # declined
    answers.append("y")
    mersik.cmd_save(album)
    assert FLAC(album / "01 - One.flac")["title"] == ["Uno"]
    assert FLAC(album / "01 - One.flac")["artist"] == ["A", "B"]
    assert FLAC(album / "02 - Two.flac")["title"] == ["Two"]


def test_save_blank_cell_removes_tag_and_missing_column_is_untouched(album, answers):
    mersik.cmd_init(album)
    (album / "tags.csv").write_text("filename,title\n01 - One.flac,\n")
    answers.append("y")
    mersik.cmd_save(album)
    f = FLAC(album / "01 - One.flac")
    assert "title" not in f
    assert f["artist"] == ["A", "B"]  # no artist column -> untouched
    assert FLAC(album / "02 - Two.flac")["title"] == ["Two"]  # no row -> untouched


def test_save_embeds_full_res_bytes_exactly(album, answers):
    mersik.cmd_init(album)
    jpg = make_image("JPEG", size=(2400, 2400))
    covers = album / "covers"
    covers.mkdir()
    (covers / "01 - One.jpg").write_bytes(jpg)
    answers.append("y")
    mersik.cmd_save(album)
    pics = FLAC(album / "01 - One.flac").pictures
    assert len(pics) == 1
    assert pics[0].data == jpg
    assert (pics[0].width, pics[0].height, pics[0].mime, pics[0].type) == (2400, 2400, "image/jpeg", 3)
    # round trip back out is identical
    (covers / "01 - One.jpg").unlink()
    mersik.cmd_init(album)
    assert (covers / "01 - One.jpg").read_bytes() == jpg


def test_save_unchanged_covers_do_not_touch_file(album):
    embed(album / "01 - One.flac", make_image("JPEG"), "image/jpeg", ptype=4)
    mersik.cmd_init(album)
    before = (album / "01 - One.flac").read_bytes()
    mersik.cmd_save(album)  # nothing to do, no prompt
    assert (album / "01 - One.flac").read_bytes() == before


def test_save_keeps_picture_type_when_replacing(album, answers):
    embed(album / "01 - One.flac", make_image("JPEG"), "image/jpeg", ptype=4)
    mersik.cmd_init(album)
    new = make_image("PNG")
    (album / "covers" / "01 - One.jpg").unlink()
    (album / "covers" / "01 - One.png").write_bytes(new)
    answers.append("y")
    mersik.cmd_save(album)
    pics = FLAC(album / "01 - One.flac").pictures
    assert [p.data for p in pics] == [new]
    assert pics[0].type == 4 and pics[0].mime == "image/png"


def test_save_without_csv_errors(album):
    with pytest.raises(mersik.MersikError):
        mersik.cmd_save(album)


# ---------------------------------------------------------------- round trip

def snapshot(folder: Path) -> dict[str, bytes]:
    return {str(p.relative_to(folder)): p.read_bytes() for p in sorted(folder.rglob("*")) if p.is_file()}


def assert_roundtrip_is_noop(album, answers):
    """init, then diff and save must both find nothing to do and change no FLAC."""
    flacs_before = {p.name: p.read_bytes() for p in album.glob("*.flac")}
    answers.extend(["y", "y"])
    mersik.cmd_init(album)
    assert mersik.cmd_diff(album) == 0
    mersik.cmd_save(album)  # would prompt if it found anything; an empty queue answers 'n'
    assert {p.name: p.read_bytes() for p in album.glob("*.flac")} == flacs_before


def test_roundtrip_plain(album, answers):
    embed(album / "01 - One.flac", make_image("JPEG"), "image/jpeg", ptype=4)
    assert_roundtrip_is_noop(album, answers)


def test_roundtrip_empty_values_and_odd_text(album, answers):
    f = FLAC(album / "01 - One.flac")
    f["comment"] = ["", "second", ""]
    f["onlyempty"] = [""]
    f["lyrics"] = ["line1\nline2\r\nline3", '  spaced "quoted", comma  ', "ünïcödé ✓"]
    f.save()
    assert_roundtrip_is_noop(album, answers)
    with open(album / "tags.csv", newline="") as fh:
        rows = list(csv.reader(fh))
    assert "onlyempty" not in rows[0]          # all-empty tag: no column
    assert rows[0].count("comment") == 1       # empty values compacted away
    assert rows[1][rows[0].index("comment")] == "second"


def test_save_never_writes_empty_values(album, answers):
    mersik.cmd_init(album)
    with open(album / "tags.csv", "w", newline="") as fh:
        csv.writer(fh).writerows([["filename", "mood", "mood"], ["01 - One.flac", "", ""]])
    mersik.cmd_save(album)  # nothing to write: no prompt, nothing changes
    assert "mood" not in FLAC(album / "01 - One.flac")


def test_roundtrip_uppercase_and_duplicate_case_keys(album, answers):
    f = FLAC(album / "01 - One.flac")
    f.tags.append(("ARTIST", "C"))  # same key, different case
    f.tags.append(("GENRE", "Rock"))
    f.save()
    assert_roundtrip_is_noop(album, answers)


def test_roundtrip_filename_tag_is_left_alone(album, answers, capsys):
    f = FLAC(album / "01 - One.flac")
    f["filename"] = "weird"
    f.save()
    assert_roundtrip_is_noop(album, answers)
    assert FLAC(album / "01 - One.flac")["filename"] == ["weird"]
    assert "filename" in capsys.readouterr().err


def test_roundtrip_unreadable_and_unknown_pictures(album, answers):
    good = make_image("JPEG")
    path = album / "01 - One.flac"
    embed(path, good, "image/jpeg")
    embed(path, b"\xff\xd8\xffthis is not really a jpeg", "image/jpeg")  # exported, unreadable
    embed(path, b"data", "-->")                                          # not exportable, kept
    assert_roundtrip_is_noop(album, answers)
    assert len(FLAC(path).pictures) == 3


def test_roundtrip_many_pictures_and_name_collisions(tmp_path, answers):
    # 'A_2.flac' owns the name 'A_2', so A's second/third pictures must not use it.
    for name in ("A", "A_2", "A_3"):
        make_flac(tmp_path / f"{name}.flac", title=name)
    imgs = [make_image("JPEG", (400, 400)), make_image("PNG", (400, 400)), make_image("JPEG", (500, 500))]
    for img, mime in zip(imgs, ["image/jpeg", "image/png", "image/jpeg"]):
        embed(tmp_path / "A.flac", img, mime)
    own = make_image("JPEG", (300, 300))
    embed(tmp_path / "A_2.flac", own, "image/jpeg")
    answers.extend(["y", "y"])
    mersik.cmd_init(tmp_path)
    covers = tmp_path / "covers"
    assert (covers / "A.jpg").read_bytes() == imgs[0]
    assert (covers / "A_2.jpg").read_bytes() == own
    assert not (covers / "A_3.jpg").exists() or (covers / "A_3.jpg").read_bytes() != own
    assert mersik.cmd_diff(tmp_path) == 0
    assert [p.data for p in FLAC(tmp_path / "A.flac").pictures] == imgs
    assert [p.data for p in FLAC(tmp_path / "A_2.flac").pictures] == [own]
    assert FLAC(tmp_path / "A_3.flac").pictures == []


def test_exported_then_edited_then_saved_matches_exactly(album, answers):
    """Edit a tag and swap a cover in the exported files; the FLACs end up matching them."""
    embed(album / "01 - One.flac", make_image("JPEG"), "image/jpeg")
    answers.extend(["y", "y"])
    mersik.cmd_init(album)
    with open(album / "tags.csv", newline="") as f:
        rows = list(csv.reader(f))
    rows[1][rows[0].index("title")] = "Changed"
    with open(album / "tags.csv", "w", newline="") as f:
        csv.writer(f).writerows(rows)
    new = make_image("PNG", (2000, 2000))
    (album / "covers" / "01 - One.jpg").unlink()
    (album / "covers" / "01 - One.png").write_bytes(new)
    assert mersik.cmd_diff(album) == 1
    answers.append("y")
    mersik.cmd_save(album)
    assert mersik.cmd_diff(album) == 0
    f = FLAC(album / "01 - One.flac")
    assert f["title"] == ["Changed"] and [p.data for p in f.pictures] == [new]


# ---------------------------------------------------------------------- diff

def test_diff_reports_differences_and_modifies_nothing(album, answers, capsys):
    embed(album / "01 - One.flac", make_image("JPEG"), "image/jpeg")
    answers.extend(["y", "y"])
    mersik.cmd_init(album)
    with open(album / "tags.csv", newline="") as f:
        rows = list(csv.reader(f))
    col = rows[0].index("title")
    rows[1][col] = "Uno"
    rows.append(["ghost.flac"] + [""] * (len(rows[0]) - 1))
    with open(album / "tags.csv", "w", newline="") as f:
        csv.writer(f).writerows(rows)
    new = make_image("PNG")
    (album / "covers" / "01 - One.jpg").unlink()
    (album / "covers" / "01 - One.png").write_bytes(new)
    FLAC(album / "02 - Two.flac")  # untouched file with no differences
    capsys.readouterr()

    answers[:] = ["y"]  # a prompt during diff would consume this
    before = snapshot(album)
    mtimes = {p: p.stat().st_mtime_ns for p in album.rglob("*") if p.is_file()}
    assert mersik.cmd_diff(album) == 1
    assert snapshot(album) == before
    assert {p: p.stat().st_mtime_ns for p in album.rglob("*") if p.is_file()} == mtimes
    assert answers == ["y"]

    out = capsys.readouterr().out
    assert "01 - One.flac" in out and '"One"' in out and '"Uno"' in out
    assert "cover:" in out and "01 - One.png" in out
    assert "ghost.flac" in out
    assert "02 - Two.flac\n  title" not in out
    assert "1 file(s) differ, 1 match." in out


def test_diff_notes_for_untracked_tags_and_uncovered_art(album, answers, capsys):
    embed(album / "01 - One.flac", make_image("JPEG"), "image/jpeg")
    answers.extend(["y", "y"])
    mersik.cmd_init(album)
    (album / "tags.csv").write_text("filename,title\n01 - One.flac,One\n")
    (album / "covers" / "01 - One.jpg").unlink()
    capsys.readouterr()
    assert mersik.cmd_diff(album) == 0  # notes aren't differences
    out = capsys.readouterr().out
    assert "artist" in out and "no column" in out
    assert "02 - Two.flac" in out and "no row" in out
    assert "embedded art" in out


def test_diff_without_csv_errors(album):
    with pytest.raises(mersik.MersikError):
        mersik.cmd_diff(album)


def test_cli_exit_codes(album, answers):
    def run(*args):
        return subprocess.run([sys.executable, str(Path(mersik.__file__)), *args],
                              input="y\ny\n", capture_output=True, text=True)
    assert run("diff", str(album)).returncode == 2        # no tags.csv yet
    assert run("init", str(album)).returncode == 0
    assert run("diff", str(album)).returncode == 0
    (album / "tags.csv").write_text("filename,title\n01 - One.flac,Other\n")
    r = run("diff", str(album))
    assert r.returncode == 1 and "Other" in r.stdout
