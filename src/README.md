# mersik — matrix FLAC tag editor

## What this is

A Textual TUI for editing FLAC (Vorbis comment) tags across a whole
album at once. Core design goals:

- **Forgiving with arbitrary tags.** FLAC/Vorbis comments allow any key
  and multiple values per key. The app treats duplicate keys (e.g. two
  `ARTIST` tags) as independent columns, and freeform tag names are a
  first-class citizen, not an afterthought.
- **Opinionated about standard practice.** Album-spanning fields
  (ALBUMARTIST, ALBUM, DISCTOTAL, etc.) get pinned and edited once for the
  whole album. Track/disc numbering is derived automatically from row
  order + disc grouping rather than typed by hand.
- **Nothing touches disk until you explicitly save**, and save always
  shows a diff first.

## Stack

Python, Textual (TUI framework), mutagen (FLAC/Vorbis comment I/O),
Pillow (image decode/resize), textual-image (kitty graphics protocol
rendering).

## Run

```
pip install textual mutagen textual-image pillow rich
python src/app.py /path/to/album/root
```

Loads all `.flac` files recursively under the given folder (so
`disc1/`, `disc2/` subfolders are fine).

## Core data model (`src/models.py`)

- `Column`: one matrix column. Has a `key` (tag name) and `pinned`
  bool. Duplicate columns for the same key are separate `Column`
  objects — each independently editable, no cross-effect.
- `Track`: one FLAC file's in-memory state — `slots: dict[column_id,
  value]`, `disc`/`position` (drives TRACKNUMBER/DISCNUMBER, not stored
  as ordinary tag columns), `cover_art` bytes, plus `original_tags` /
  `original_cover` captured at load time for diffing.
- `MatrixModel`: owns the full track + column list. Key methods:
  `load_directory`, `save_all`, `add_column`/`duplicate_column`/
  `delete_column`/`reorder_column`/`toggle_pin`, `move_track`,
  `set_disc`, `auto_number`, `get_effective_tags`/`diff_for_track`,
  `has_unsaved_changes`, `push_history`/`undo`/`redo`.
- `ThumbnailCache`: decodes+resizes cover art once per distinct image
  (keyed on raw bytes, not object identity), capped at 200 entries
  (LRU eviction). Lives on the model so it survives navigating away
  from and back to the cover-art screen.
- `STANDARD_KEYS`: ALBUMARTIST, ALBUM, ARTIST, TITLE, DATE,
  TRACKNUMBER, TRACKTOTAL, DISCNUMBER, DISCTOTAL — always pinned at
  load, exact casing. TRACKNUMBER/TRACKTOTAL/DISCNUMBER/DISCTOTAL are
  "structural" — not directly-editable columns, only ever written via
  `auto_number()`, computed from disc groups + row order.

Loading auto-pins any tag whose value is both identical across every track
and included in the always-pinned standard set (won't pin if all values
are not identical), the name of which should probably be changed
internally.

## UI (`src/app.py`)

`MersikApp` → pushes `MatrixScreen` (primary view) → can push
`CoverArtScreen` (secondary page), plus modal screens: `PromptScreen`
(generic text input), `EditCellScreen`, `SaveDiffScreen`,
`ConfirmQuitScreen`.

### Matrix view keybinds
- arrows / hjkl: move cursor (vim-modal: navigate without editing)
- `i`: edit focused cell (editing a pinned column broadcasts to all
  tracks; unpinned edits only that one cell)
- `shift+j/k` or `shift+down/up`: reorder the focused row within its
  disc group (visual only — no file changes until save, and no
  separate "renumber" happens automatically)
- `+`/`-`: move focused track to next/previous disc (creates a new
  disc group implicitly if it doesn't exist yet)
- `n`: auto-number — recompute TRACKNUMBER/TRACKTOTAL/DISCNUMBER/
  DISCTOTAL from current disc groups + row order (the only thing that
  writes those structural fields)
- `a`: add new empty unpinned column (prompts for key name), placed
  right of the focused column (or as the first unpinned column if the
  focused column was pinned)
- `d`: duplicate focused column (same key, same pinned state, empty
  cells), placed directly to its right
- `x`: delete focused column (removes that tag from every file on
  save, unless a duplicate column for the same key still holds values)
- `p`: toggle focused column's pinned state, moved to the near edge of
  its new zone (next to the pin/unpin divider)
- `shift+h/l` or `shift+left/right`: reorder the focused column within
  its own zone (pinned columns can't cross into unpinned or vice versa
  this way — only `p` changes zone membership)
- `z` / `y`: undo / redo (full-state snapshot history, capped at 100
  steps — see "Undo/redo" below)
- `/`: search — jump to the first row (from current position forward,
  wrapping) whose filename or *any* tag value contains the query,
  case-insensitive; `]`/`[` repeat the last search forward/backward
- `w` or `s`: save — shows a diff summary first (`y` confirm, `n`/esc
  cancel); per-file failures are reported without rolling back
  successful writes
- `c`: open the cover-art page
- `q`: quit — warns first if there are unsaved changes

Cells longer than ~42 chars are truncated with an ellipsis for
*display only*; the full value is always what's edited and saved.
Loading a folder with no `.flac` files (recursively) shows a message
instead of a blank/broken table, and no keybind crashes on the empty
state.

### Cover art page keybinds
- left/right: switch track
- `r`: replace this track's cover art from a file path
- `shift+A`: broadcast this track's current cover art to every track
  (staged in memory only, until save; shares one bytes object so this
  is still a single decode across all tracks, not N)
- `e`: export the current track's full-resolution embedded art (not
  the cached thumbnail) to a path you provide — auto-names the file if
  given a folder, using the detected image extension

Real kitty-protocol thumbnails render via `textual-image`'s `Image`
widget. Caching (see `ThumbnailCache` above) is what prevents the
freeze the user hit in the previous project, where every visit to the
image page re-decoded full-resolution art from scratch.

### Undo/redo
Every mutating action pushes a full deep-copy snapshot of
columns+tracks onto an undo stack *before* it runs (`push_history()`).
Chosen over diff-based undo because it's trivially correct even for
compound actions like `auto_number()` touching every track at once,
and album-sized sessions make the memory cost negligible.
`copy.deepcopy` treats `bytes` as atomic, so cover art is never
actually duplicated per snapshot — only the small tag/structure data
is genuinely copied each time. New actions after an undo clear the
redo stack. Capped at 100 entries.

### Safety
- Quit confirms if `model.has_unsaved_changes()` is true.
- Files that fail to load (corrupt, permissions, etc.) are skipped
  with a notification listing which ones and why; the rest of the
  album still loads.
- Save failures are per-file — a write error partway through a batch
  doesn't roll back files that already saved, and the user is told
  exactly which files failed and why.

## Testing approach so far

No formal test suite file exists yet — validation has been done ad hoc
via a scratch script pattern: generate silent FLAC files with ffmpeg,
tag them with mutagen (including a deliberate duplicate-key case),
then either (a) exercise `MatrixModel` methods directly and assert on
the results, or (b) drive `MersikApp` headlessly via Textual's
`app.run_test()` / `Pilot` (`await pilot.press(...)`, inspect
`app.screen_stack`, `DataTable` state, etc.). Every feature described
above has been exercised this way at least once. If picking this back
up, it's worth turning this into an actual `tests/` directory with
pytest rather than re-deriving the scratch scripts each session.

## What's left to implement

Roughly in suggested priority order:

1. **Status bar.** Persistent line showing track count, disc count,
   current position, and an unsaved-changes indicator (the underlying
   `has_unsaved_changes()` check already exists — just needs surfacing
   in the UI, most naturally updated at the end of `rebuild_table()`).

2. **Config file.** Externalize currently-hardcoded values: the
   `STANDARD_KEYS` pin list (`models.py`), the disc color `PALETTE`
   (`app.py`), and `ThumbnailCache`'s max size / entry cap
   (`models.py`). Likely `~/.config/mersik/config.toml` with built-in
   defaults if absent. Open question: read once at startup only
   (simpler), or support a reload keybind.

3. **Cover art page small gaps.**
   - No keybind to *remove* a track's cover art entirely (only
     replace / apply-to-all / export exist).
   - No confirmation before `shift+A` overwrites existing per-track art
     on other tracks — currently silent/irreversible except via undo.

4. **Load-time robustness beyond individual file failures.**
   Symlink loops or permission-denied *directories* during the
   recursive walk aren't caught (only per-file read errors are).

5. **Scale/concurrency, unverified.**
   - Large libraries (hundreds of tracks) — no virtualization tested;
     Textual's `DataTable` should handle it but hasn't been checked at
     that scale.
   - No staleness detection if the FLAC files are modified externally
     while a session has them open — a save would silently clobber
     external changes.

6. **Formal test suite.** Convert the ad hoc scratch-script validation
   pattern described above into an actual `tests/` directory.

Nothing above blocks normal use of the app — it's fully functional as
described in the keybind sections. These are the known gaps as of the
last working session.

## Additional features to implement, on request by user

In no particular order:

1. Shorten the length of cells (too long horizontally)

2. Vim keys for navigation don't work, only arrow keys right now
    are working

3. Move keybinds into a popup window that makes it easy to read,
    rather than the status bar

4. Make the cover arts into their own tab rather than a toggle pop-up

5. Enforce the existence of a select few tags (NUMBER and TOTAL tags
    should not have more than one copy):
    - ALBUMARTIST
    - ALBUM
    - ARTIST
    - TITLE
    - DATE
    - TRACKNUMBER
    - TRACKTOTAL
    - DISCNUMBER
    - DISCTOTAL

6. The "always-pinned" set should be renamed to reflect a change in
    intention. They should not always be pinned no matter what,
    instead they should be pinned IF all files have the same value
    for that column. If there are different values, it should not
    get pinned, but rather should show up at the start of the
    unpinned section.

