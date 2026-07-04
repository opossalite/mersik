# FLAC Tag Editor (TUI)

Miller-columns style TUI for batch-editing FLAC metadata: files on the left,
tags in the middle, values (or cover art) on the right.

## Setup

```
pip install -r requirements.txt
python app.py [directory]      # defaults to the current directory
```

Requires a `.flac` directory (non-recursive scan). Cover art rendering uses
`textual-image`, which auto-detects Kitty's graphics protocol / Sixel /
half-block fallback depending on your terminal.

## Keybinds

**Global:** `q` quit (confirms if unsaved) · `s` save (shows a collapsed diff
first) · `u` undo · `y` redo

**File panel (left):** `j/k` `↑/↓` navigate · `space` toggle selected ·
`l/→` focus tags

**Tag panel (middle):** `j/k` `↑/↓` navigate · `h/←` focus files ·
`l/→` focus values · `a` add tag · `r/e` rename tag · `d` delete tag

**Value panel (right):** `j/k` `↑/↓` scroll · `h/←` focus tags ·
`r/e` set value for all selected files (or replace cover art, in image mode) ·
`c` auto-count (zero-padded sequence in filename order; not available for
cover art)

The bottom bar always shows the keybinds for whichever panel has focus.

## A few implementation notes worth knowing about

- **Case-sensitive tags**: mutagen's `FLAC.tags` object has a dict-like
  interface (`.keys()`, `[key]`) that silently lowercases everything, since
  Vorbis comments are conventionally case-insensitive. That directly
  conflicts with the "same tag, different case = different tag" requirement,
  so `models.py` bypasses that interface and reads/writes the underlying
  `list` of `(key, value)` tuples directly (`.append()`, iteration), which
  preserves case exactly as found on disk. If you ever see tag case
  behaving unexpectedly, this is the first place to look.
- **Cover art** is treated as a pseudo-tag (`COVER_ART_KEY` in
  `models.py`) so it can share the same middle-panel row/selection logic
  as real tags, with the right panel switching to image rendering
  automatically when it's highlighted.
- **Multi-value Vorbis fields**: if a file has multiple values under the
  same exact key (legal in the Vorbis comment spec, e.g. multiple `ARTIST`
  entries), they're joined with `"; "` on load. Round-tripping that back
  out as a single joined string on save is a simplification — if you rely
  on true multi-valued fields, that's a spot to extend.
- **Selection state is not undoable.** Toggling which files are "in scope"
  with `space` is treated as workspace navigation, not a data edit, so it
  doesn't go on the undo stack. Only actual tag/value/image mutations do.
- **History is per-session.** Undo/redo works across saves within one run,
  but doesn't persist once you quit.
- **Image replacement** is a plain path prompt for now (`r/e` in image
  mode) rather than a file-picker widget — kept simple deliberately, per
  your call; a modal file browser would be a natural follow-up.

## Structure

- `models.py` — `AudioFile`, directory scanning, mutagen read/write
- `history.py` — `HistoryFrame`, undo/redo stack, save-diff collapsing
- `mutations.py` — the actual tag operations (add/rename/delete/set/auto-count/replace-image), each building a history frame
- `rendering.py` — model state → Rich `Text` for the panels (colors, presence dots, uniform-vs-per-file value display)
- `modals.py` — text input prompt and yes/no confirmation dialogs
- `panels.py` — the four panel widgets and their keybinds
- `app.py` — layout, focus routing, and wiring keybinds to mutations
