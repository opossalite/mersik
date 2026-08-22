#!/usr/bin/env python3


import argparse
from pathlib import Path
import pandas as pd
from mutagen.flac import FLAC


def read_flac_tags(folder: str | Path) -> pd.DataFrame:
    """
    Scan a folder (non-recursive) for FLAC files and return a DataFrame
    of their tags.

    Each row = one file. Columns = tag keys found across all files, plus
    'filename'. Repeated tag values (e.g. multiple ARTIST entries) produce
    repeated columns with the SAME name (e.g. two 'artist' columns) rather
    than synthetic suffixes — this keeps it unambiguous that they're
    multiple values of the same tag, not a differently-named tag.
    Missing values for a given file show up as NaN.
    """
    folder = Path(folder)
    flac_paths = sorted(folder.glob("*.flac"))

    # First pass: figure out the max number of values seen per key,
    # so we know how many 'artist' columns (etc.) to create.
    max_counts: dict[str, int] = {}
    file_tags: list[tuple[str, dict[str, list[str]]]] = []
    for path in flac_paths:
        audio = FLAC(path)
        tags: dict[str, list[str]] = dict(audio.tags) if audio.tags else {}
        file_tags.append((path.name, tags))
        for key, values in tags.items():
            max_counts[key] = max(max_counts.get(key, 0), len(values))

    # Build ordered column list: filename first, then tag keys alphabetized,
    # each repeated according to its max count.
    ordered_keys = sorted(max_counts.keys())
    columns = ["filename"]
    for key in ordered_keys:
        columns.extend([key] * max_counts[key])

    rows = []
    for filename, tags in file_tags:
        row: list[str | None] = [filename]
        for key in ordered_keys:
            values = tags.get(key, [])
            padded = values + [None] * (max_counts[key] - len(values))
            row.extend(padded)
        rows.append(row)

    return pd.DataFrame(rows, columns=columns)



def extract_covers(folder: str | Path) -> dict[str, bytes]:
    """
    Extract all embedded cover art from each FLAC file in `folder`.

    Returns a dict mapping generated cover filename -> image bytes.
    Filenames are derived from the source FLAC's filename (stem + an
    extension based on the picture's MIME type), e.g. "01 - Track.jpg"
    for a single picture embedded in "01 - Track.flac". Basing the name
    on the source file (rather than something generic like "front.jpg")
    means files naturally avoid colliding with each other even before
    any covers/ directory exists.

    If a single FLAC file has multiple embedded pictures, each one gets
    a distinct filename by appending an index before the extension:
    "01 - Track.jpg", "01 - Track_2.jpg", "01 - Track_3.jpg", etc. This
    keeps them from overwriting one another within the same run.

    Files with no embedded pictures, or pictures with a MIME type we
    don't recognize, are skipped (a skipped picture doesn't consume an
    index slot for the ones that follow it).
    """
    folder = Path(folder)
    flac_paths = sorted(folder.glob("*.flac"))

    mime_to_ext = {
        "image/jpeg": ".jpg",
        "image/jpg": ".jpg",
        "image/png": ".png",
    }

    covers: dict[str, bytes] = {}
    for path in flac_paths:
        audio = FLAC(path)
        if not audio.pictures:
            continue

        exported = 0
        for picture in audio.pictures:
            ext = mime_to_ext.get(picture.mime)
            if ext is None:
                print(f"Skipping a cover for {path.name}: unrecognized MIME type {picture.mime!r}")
                continue

            exported += 1
            suffix = "" if exported == 1 else f"_{exported}"
            cover_filename = f"{path.stem}{suffix}{ext}"
            covers[cover_filename] = picture.data

    return covers


def confirm(prompt: str) -> bool:
    """
    Ask the user a yes/no question, defaulting to No if they just hit enter.
    """
    answer = input(f"{prompt} [y/N] ").strip().lower()
    return answer in ("y", "yes")


def cmd_generate(path: str | Path) -> None:
    """
    'mersik generate [path]': scan the FLAC files in `path` and write
    their tags out to tags.csv, and their embedded cover art out to a
    covers/ directory, inside that same directory.

    If tags.csv already exists, ask for confirmation before overwriting
    it (default: do nothing).

    Cover filenames are derived from each source FLAC's filename (with
    an index suffix if a single file has multiple embedded pictures),
    so they don't collide with each other by default. If covers/
    already exists and any newly-generated cover filename matches a
    file already there, ask for confirmation before writing anything
    (default: make no changes at all). On confirmation, all covers are
    written, including overwriting the conflicting ones; on decline,
    the filesystem is left exactly as it was — nothing is written, not
    even non-conflicting covers.
    """
    folder = Path(path)

    csv_path = folder / "tags.csv"
    if csv_path.exists():
        if not confirm(f"{csv_path} already exists. Overwrite?"):
            print("Skipped tags.csv generation.")
            return

    df = read_flac_tags(folder)
    df.to_csv(csv_path, index=False)
    print(f"Wrote {len(df)} row(s) to {csv_path}")

    covers = extract_covers(folder)
    if not covers:
        print("No embedded cover art found.")
        return

    covers_dir = folder / "covers"
    existing_files = set()
    if covers_dir.exists():
        existing_files = {p.name for p in covers_dir.iterdir() if p.is_file()}

    conflicts = sorted(name for name in covers if name in existing_files)
    if conflicts:
        conflict_list = ", ".join(conflicts)
        if not confirm(f"{len(conflicts)} cover(s) already exist in {covers_dir} ({conflict_list}). Overwrite?"):
            print("Skipped covers generation; no files were changed.")
            return

    covers_dir.mkdir(exist_ok=True)
    for filename, data in covers.items():
        (covers_dir / filename).write_bytes(data)

    print(f"Wrote {len(covers)} cover(s) to {covers_dir}")


def cmd_save(path: str | Path) -> None:
    """
    'mersik save [path]': read tags.csv from `path` and write those
    values back into the corresponding FLAC files.

    Not implemented yet — this is a placeholder so the CLI shape exists
    ahead of the real write-back logic.
    """
    folder = Path(path)
    csv_path = folder / "tags.csv"
    print(f"[save] not implemented yet — would apply {csv_path} to files in {folder}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="mersik")
    subparsers = parser.add_subparsers(dest="command", required=True)

    generate_parser = subparsers.add_parser(
        "generate", help="generate tags.csv from FLAC files in a directory"
    )
    generate_parser.add_argument("path", nargs="?", default=".", help="directory to scan")

    save_parser = subparsers.add_parser(
        "save", help="save tags.csv values back into FLAC files (not yet implemented)"
    )
    save_parser.add_argument("path", nargs="?", default=".", help="directory containing tags.csv")

    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()

    if args.command == "generate":
        cmd_generate(args.path)
    elif args.command == "save":
        cmd_save(args.path)


if __name__ == "__main__":
    main()
