"""WavPack (.wv) support, plus folders mixing .flac and .wv."""
import csv
import subprocess
import sys
from pathlib import Path

import pytest
from mutagen.apev2 import BINARY, TEXT, APEValue
from mutagen.flac import FLAC
from mutagen.wavpack import WavPack

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import mersik  # noqa: E402
from test_mersik import answers, make_flac, make_image, snapshot  # noqa: E402,F401


def make_wv(path: Path, **tags) -> Path:
    subprocess.run(
        ["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "sine=d=0.2",
         "-c:a", "wavpack", str(path)],
        check=True,
    )
    audio = WavPack(path)
    if audio.tags is None:
        audio.add_tags()
    for k, v in tags.items():
        audio.tags[k] = v
    audio.save()
    return path


def embed_ape(path: Path, data: bytes, label="Cover Art (Front)", filename="cover.jpg"):
    audio = WavPack(path)
    if audio.tags is None:
        audio.add_tags()
    audio.tags[label] = APEValue(filename.encode() + b"\0" + data, BINARY)
    audio.save()


def ape_pictures(path: Path):
    """[(label, filename, data)] sorted by label, straight from the file."""
    out = []
    for k, v in WavPack(path).tags.items():
        if v.kind == BINARY and k.lower().startswith("cover art"):
            name, _, data = bytes(v).partition(b"\0")
            out.append((k, name.decode(), data))
    return sorted(out)


def text_tags(path: Path) -> dict:
    return {k: list(v) for k, v in WavPack(path).tags.items() if v.kind == TEXT}


@pytest.fixture
def wvdir(tmp_path, answers):
    make_wv(tmp_path / "01 - One.wv", Title="One", artist=["A", "B"])
    make_wv(tmp_path / "02 - Two.wv", title="Two")
    return tmp_path


def noop_roundtrip(folder, answers):
    before = {p.name: p.read_bytes() for p in folder.iterdir() if p.is_file() and p.suffix in (".wv", ".flac")}
    answers.extend(["y", "y"])
    mersik.cmd_init(folder)
    assert mersik.cmd_diff(folder) == 0
    mersik.cmd_save(folder)  # would prompt (and 'n') if it found anything
    after = {p.name: p.read_bytes() for p in folder.iterdir() if p.is_file() and p.suffix in (".wv", ".flac")}
    assert after == before


def test_init_exports_wavpack_tags_and_full_res_covers(wvdir, answers):
    jpg, png = make_image("JPEG"), make_image("PNG")
    embed_ape(wvdir / "01 - One.wv", jpg, "Cover Art (Front)", "front.jpg")
    embed_ape(wvdir / "02 - Two.wv", png, "Cover Art (Front)", "x.png")
    mersik.cmd_init(wvdir)
    assert (wvdir / "covers" / "01 - One.jpg").read_bytes() == jpg
    assert (wvdir / "covers" / "02 - Two.png").read_bytes() == png
    with open(wvdir / "tags.csv", newline="") as f:
        rows = list(csv.reader(f))
    header = rows[0]
    assert header[0] == "filename" and header.count("artist") == 2
    assert not any(h.startswith("cover art") for h in header)  # binary items aren't columns
    row = dict(zip(header, rows[1]))
    assert row["title"] == "One" and row["filename"] == "01 - One.wv"


def test_roundtrip_plain(wvdir, answers):
    embed_ape(wvdir / "01 - One.wv", make_image("JPEG"))
    noop_roundtrip(wvdir, answers)


def test_roundtrip_empty_values_and_odd_text(wvdir, answers):
    audio = WavPack(wvdir / "01 - One.wv")
    audio.tags["comment"] = ["", "second", ""]
    audio.tags["onlyempty"] = [""]
    audio.tags["lyrics"] = ["line1\nline2\r\nline3", '  spaced "quoted", comma  ', "ünïcödé ✓"]
    audio.save()
    noop_roundtrip(wvdir, answers)
    with open(wvdir / "tags.csv", newline="") as f:
        rows = list(csv.reader(f))
    assert "onlyempty" not in rows[0] and rows[0].count("comment") == 1


def test_roundtrip_multiple_pictures_survive_mutagen_reordering(wvdir, answers):
    # mutagen sorts APE items by size on every save, so order must come from the label.
    front, back, other = make_image("JPEG", (900, 900)), make_image("PNG", (300, 300)), make_image("JPEG", (500, 500))
    path = wvdir / "01 - One.wv"
    embed_ape(path, front, "Cover Art (Front)", "f.jpg")
    embed_ape(path, back, "Cover Art (Back)", "b.png")
    embed_ape(path, other, "Cover Art (Other)", "o.jpg")
    mersik.cmd_init(wvdir)
    covers = wvdir / "covers"
    assert (covers / "01 - One.jpg").read_bytes() == front
    assert (covers / "01 - One_2.png").read_bytes() == back
    assert (covers / "01 - One_3.jpg").read_bytes() == other
    assert mersik.cmd_diff(wvdir) == 0
    before = (path).read_bytes()
    mersik.cmd_save(wvdir)
    assert path.read_bytes() == before


def test_roundtrip_unknown_binary_and_unreadable_picture_kept(wvdir, answers):
    path = wvdir / "01 - One.wv"
    embed_ape(path, make_image("JPEG"), "Cover Art (Front)", "f.jpg")
    embed_ape(path, b"\xff\xd8\xffnot really a jpeg", "Cover Art (Back)", "b.jpg")  # exported, unreadable
    audio = WavPack(path)
    audio.tags["Cover Art (Other)"] = APEValue(b"nodelimiterhere", BINARY)         # not exportable
    audio.tags["Some Blob"] = APEValue(b"x\0yz", BINARY)                             # not a picture
    audio.save()
    noop_roundtrip(wvdir, answers)
    keys = {k for k in WavPack(path).tags.keys()}
    assert {"Cover Art (Other)", "Some Blob"} <= keys


def test_save_edits_tags_and_keeps_existing_key_capitalization(wvdir, answers):
    mersik.cmd_init(wvdir)
    with open(wvdir / "tags.csv", newline="") as f:
        rows = list(csv.reader(f))
    h = rows[0]
    rows[1][h.index("title")] = "Uno"
    rows[1][h.index("encoder")] = ""      # blank -> removed
    rows[2][h.index("artist")] = "Solo"   # new tag on a file that had none
    with open(wvdir / "tags.csv", "w", newline="") as f:
        csv.writer(f).writerows(rows)
    assert mersik.cmd_diff(wvdir) == 1
    answers.append("n")
    mersik.cmd_save(wvdir)
    assert text_tags(wvdir / "01 - One.wv")["Title"] == ["One"]  # declined
    answers.append("y")
    mersik.cmd_save(wvdir)
    t1, t2 = text_tags(wvdir / "01 - One.wv"), text_tags(wvdir / "02 - Two.wv")
    assert t1["Title"] == ["Uno"]              # 'Title' keeps its own capitalization
    assert "encoder" not in {k.lower() for k in t1}
    assert t1["artist"] == ["A", "B"]
    assert t2["artist"] == ["Solo"]
    assert mersik.cmd_diff(wvdir) == 0


def test_save_embeds_exact_bytes_and_new_labels(wvdir, answers):
    mersik.cmd_init(wvdir)
    covers = wvdir / "covers"
    covers.mkdir(exist_ok=True)
    a, b = make_image("JPEG", (2400, 2400)), make_image("PNG", (1000, 1000))
    (covers / "01 - One.jpg").write_bytes(a)
    (covers / "01 - One_2.png").write_bytes(b)
    answers.append("y")
    mersik.cmd_save(wvdir)
    pics = ape_pictures(wvdir / "01 - One.wv")
    assert [(l, d) for l, _, d in pics] == [("Cover Art (Back)", b), ("Cover Art (Front)", a)]
    assert {n for _, n, _ in pics} == {"01 - One.jpg", "01 - One_2.png"}
    assert mersik.cmd_diff(wvdir) == 0
    # and back out, byte-identical
    for f in covers.iterdir():
        f.unlink()
    mersik.cmd_init(wvdir)
    assert (covers / "01 - One.jpg").read_bytes() == a
    assert (covers / "01 - One_2.png").read_bytes() == b


def test_save_replacing_a_picture_keeps_its_label_and_unmanaged_items(wvdir, answers):
    path = wvdir / "01 - One.wv"
    embed_ape(path, make_image("JPEG"), "Cover Art (Back)", "b.jpg")
    audio = WavPack(path)
    audio.tags["Some Blob"] = APEValue(b"x\0yz", BINARY)
    audio.save()
    mersik.cmd_init(wvdir)
    new = make_image("PNG", (700, 700))
    (wvdir / "covers" / "01 - One.jpg").unlink()
    (wvdir / "covers" / "01 - One.png").write_bytes(new)
    answers.append("y")
    mersik.cmd_save(wvdir)
    pics = ape_pictures(path)
    assert [(l, d) for l, _, d in pics] == [("Cover Art (Back)", new)]
    assert "Some Blob" in WavPack(path).tags


def test_save_too_many_pictures_leaves_covers_alone(wvdir, answers, capsys):
    mersik.cmd_init(wvdir)
    covers = wvdir / "covers"
    covers.mkdir(exist_ok=True)
    (covers / "01 - One.jpg").write_bytes(make_image("JPEG", (50, 50)))
    for i in range(2, 2 + len(mersik._APE_PICTURE_LABELS) + 1):
        (covers / f"01 - One_{i}.jpg").write_bytes(make_image("JPEG", (50 + i, 50)))
    assert mersik.cmd_diff(wvdir) == 0
    assert "too many pictures" in capsys.readouterr().err
    assert ape_pictures(wvdir / "01 - One.wv") == []


def test_wavpack_rejects_keys_it_cannot_store(wvdir):
    (wvdir / "tags.csv").write_text("filename,x\n01 - One.wv,1\n")  # 1-char key: invalid in APEv2
    with pytest.raises(mersik.MersikError, match="WavPack"):
        mersik.cmd_diff(wvdir)


def test_save_will_not_overwrite_a_binary_item_with_text(wvdir, answers, capsys):
    embed_ape(wvdir / "01 - One.wv", make_image("JPEG"))
    (wvdir / "tags.csv").write_text("filename,cover art (front)\n01 - One.wv,oops\n")
    assert mersik.cmd_diff(wvdir) == 0   # file skipped with a warning, nothing to apply
    assert "binary item" in capsys.readouterr().err
    assert len(ape_pictures(wvdir / "01 - One.wv")) == 1


def test_diff_is_read_only_for_wavpack(wvdir, answers, capsys):
    embed_ape(wvdir / "01 - One.wv", make_image("JPEG"))
    mersik.cmd_init(wvdir)
    with open(wvdir / "tags.csv", newline="") as f:
        rows = list(csv.reader(f))
    rows[1][rows[0].index("title")] = "Uno"
    with open(wvdir / "tags.csv", "w", newline="") as f:
        csv.writer(f).writerows(rows)
    (wvdir / "covers" / "01 - One.jpg").write_bytes(make_image("PNG"))
    capsys.readouterr()
    before = snapshot(wvdir)
    mtimes = {p: p.stat().st_mtime_ns for p in wvdir.rglob("*") if p.is_file()}
    assert mersik.cmd_diff(wvdir) == 1
    assert snapshot(wvdir) == before
    assert {p: p.stat().st_mtime_ns for p in wvdir.rglob("*") if p.is_file()} == mtimes
    out = capsys.readouterr().out
    assert '"One"' in out and '"Uno"' in out and "cover:" in out


# ------------------------------------------------------------ mixed folders

@pytest.fixture
def mixed(tmp_path, answers):
    make_flac(tmp_path / "01 - One.flac", title="One", artist=["A", "B"])
    make_wv(tmp_path / "02 - Two.wv", Title="Two", artist=["C"])
    return tmp_path


def test_mixed_folder_roundtrip_and_edit(mixed, answers):
    from test_mersik import embed
    embed(mixed / "01 - One.flac", make_image("JPEG"), "image/jpeg")
    embed_ape(mixed / "02 - Two.wv", make_image("PNG"))
    noop_roundtrip(mixed, answers)
    with open(mixed / "tags.csv", newline="") as f:
        rows = list(csv.reader(f))
    assert [r[0] for r in rows[1:]] == ["01 - One.flac", "02 - Two.wv"]
    t = rows[0].index("title")
    rows[1][t], rows[2][t] = "Uno", "Dos"
    with open(mixed / "tags.csv", "w", newline="") as f:
        csv.writer(f).writerows(rows)
    answers.append("y")
    mersik.cmd_save(mixed)
    assert FLAC(mixed / "01 - One.flac")["title"] == ["Uno"]
    assert text_tags(mixed / "02 - Two.wv")["Title"] == ["Dos"]
    assert mersik.cmd_diff(mixed) == 0


def test_same_name_in_two_formats_skips_covers_but_not_tags(tmp_path, answers, capsys):
    from test_mersik import embed
    make_flac(tmp_path / "Track.flac", title="F")
    make_wv(tmp_path / "Track.wv", title="W")
    embed(tmp_path / "Track.flac", make_image("JPEG"), "image/jpeg")
    mersik.cmd_init(tmp_path)
    assert "share a name" in capsys.readouterr().err
    assert not (tmp_path / "covers").exists()
    with open(tmp_path / "tags.csv", newline="") as f:
        rows = list(csv.reader(f))
    assert sorted(r[0] for r in rows[1:]) == ["Track.flac", "Track.wv"]
    t = rows[0].index("title")
    for r in rows[1:]:
        r[t] = r[t] + "2"
    with open(tmp_path / "tags.csv", "w", newline="") as f:
        csv.writer(f).writerows(rows)
    answers.append("y")
    mersik.cmd_save(tmp_path)
    assert FLAC(tmp_path / "Track.flac")["title"] == ["F2"]
    assert text_tags(tmp_path / "Track.wv")["title"] == ["W2"]


def test_cli_works_on_wavpack(wvdir):
    def run(*args, inp="y\ny\n"):
        return subprocess.run([sys.executable, str(Path(mersik.__file__)), *args],
                              input=inp, capture_output=True, text=True)
    assert run("init", str(wvdir)).returncode == 0
    assert run("diff", str(wvdir)).returncode == 0
    (wvdir / "tags.csv").write_text("filename,title\n01 - One.wv,Other\n")
    r = run("diff", str(wvdir))
    assert r.returncode == 1 and "Other" in r.stdout
