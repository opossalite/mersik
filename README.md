# mersik
CLI tag editor for FLAC and WavPack files: export tags and cover art, edit them with whatever tools you like, write them back.

    pip install ./src
    mersik init [path]    # FLAC files -> tags.csv + covers/
    mersik save [path]    # tags.csv + covers/ -> FLAC files
    mersik diff [path]    # show how tags.csv + covers/ differ from the FLAC files (changes nothing)

`path` defaults to the current directory (non-recursive). Handles `.flac` and `.wv` files, alone or mixed.

## Formats
| | FLAC | WavPack |
|---|---|---|
| Tags | Vorbis comments | APEv2 items |
| Embedded art | picture blocks | `Cover Art (...)` binary items |
| Multiple pictures | any number | one per kind (Front, Back, Other, ...), up to 12 |

Everything below works the same for both. Notes specific to WavPack:
- Pictures are ordered by kind (Front first), because APEv2 files don't keep item order. `Track.jpg` is the
  Front cover, `Track_2.png` the next kind, and so on; a replaced picture keeps its kind.
- A tag that already exists keeps the capitalization it has in the file.
- APEv2 names must be 2-255 printable ASCII characters; a csv column that WavPack (or FLAC) can't store is
  an error when that format is in the folder, and a column that names a binary item is skipped for that file.
- If `Track.flac` and `Track.wv` both exist, their cover art can't be told apart by name, so covers are
  skipped for those two (with a warning); their tags still work.

## init
- Writes `tags.csv`: one row per file, a `filename` column, then one column per tag.
  Multi-valued tags (e.g. two artists) are repeated columns with the same name.
- Writes embedded art to `covers/`, named after the music file: `01 - Track.flac` -> `01 - Track.jpg`.
  Extra pictures in one file become `01 - Track_2.png`, `01 - Track_3.jpg`, ...
- Images are written byte-for-byte (no resizing or re-encoding).
- Asks before overwriting `tags.csv`. Existing files in `covers/` are kept; if a new cover has the same
  name as a different existing file, it lists them and asks before writing any covers.

## save
- For each tag that has a column in `tags.csv`, the file's values become that row's non-empty cells
  (blank the cells to remove the tag). Tags without a column, and files without a row, are untouched.
- Files with a matching image in `covers/` get their pictures replaced by it, byte-for-byte; picture type
  and description are kept for the slot being replaced. Files without a matching image keep their pictures.
- Lists every pending change per file, then asks once for confirmation before writing anything.
  Files that already match are not rewritten.

## diff
- Read-only: never writes to the FLAC files, `tags.csv` or `covers/`.
- Reports exactly what `save` would change, as file value vs csv value per tag and file cover vs `covers/`
  image per file. It uses the same comparison code as `save`, so the two can't disagree.
- Also lists things `save` ignores: csv rows with no file, files with no row, tags with no csv column, and
  embedded art with no matching image in `covers/`.
- Exit status: 0 no differences, 1 differences, 2 error (like `diff(1)`).

## init and save are inverses
Running `init` and then `save` or `diff` without editing anything finds nothing to do, and no FLAC is
rewritten. Details that make that hold:
- Tag names are case-insensitive and exported lowercase; multi-line, quoted, comma and Unicode values survive.
- Empty tags are dropped on both ends: `init` doesn't export empty values (a tag with only empty values gets
  no column), and `save` never writes them. Empty cells just mean "no value".
- A tag literally named `filename` can't be a column; it's reported by `init` and never touched by `save`.
- Extra pictures are numbered past any name another track owns (`A_2.flac` pushes `A.flac`'s second
  picture to `A_3`), so every image maps back to the right file and slot.
- Pictures `init` can't export (non-image types, other binary items) are kept by `save`; if any image in `covers/` is
  unreadable, that file's pictures are left alone rather than partly replaced.

## Tests
    cd src && pip install pytest && pytest   # needs ffmpeg on PATH to build test FLACs
