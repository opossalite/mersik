#!/usr/bin/env python3


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



def main():
    print("Hello from mersik!")
    df = read_flac_tags("./")
    print(df)


if __name__ == "__main__":
    main()
