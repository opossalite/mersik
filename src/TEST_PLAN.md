# Mersik — Formal Test Plan

**12 areas, ~95 tests.** Each test is designed to be runnable by both
developers (`pytest tests/`) and by AI during implementation sessions.

> **Status: implemented.** `tests/` at the repo root now contains a
> pytest suite following this plan (139 passing, 1 environment-dependent
> skip, 2 intentional `xfail(strict=True)` documenting real bugs the
> suite found — see "Known issues found by the test suite" in
> `src/README.md`). Test names below match the actual test functions
> where the plan and implementation agree; a handful of Area I tests
> were renamed/adjusted from what's listed here once writing them
> against the real code revealed the pinning logic is `OR`, not `AND` --
> see `src/README.md` for details. Run `pytest tests/ -v` from the repo
> root to execute the suite.

---

## I. Data Model — `models.py` (29 tests)

| # | Name | What it covers |
|---|------|----------------|
| 1.1 | `test_sniff_mime_jpeg` | `sniff_mime()` with `\xff\xd8\xff` prefix |
| 1.2 | `test_sniff_mime_png` | `sniff_mime()` with `\x89PNG\r\n\x1a\n` prefix |
| 1.3 | `test_sniff_mime_gif87` | `sniff_mime()` with `GIF87a` prefix |
| 1.4 | `test_sniff_mime_gif89` | `sniff_mime()` with `GIF89a` prefix |
| 1.5 | `test_sniff_mime_fallback` | Unknown bytes → `image/jpeg` |
| 1.6 | `test_column_new_id_increments` | `Column.new()` auto-increments ID |
| 1.7 | `test_column_new_pinned_state` | `Column.new(key, pinned=True)` |
| 1.8 | `test_track_filename` | `Track.filename` returns `Path.name` |
| 1.9 | `test_track_slots_default_empty` | New Track has empty slots |
| 1.10 | `test_track_disc_default_one` | New Track has `disc=1` |
| 1.11 | `test_track_position_default_zero` | New Track has `position=0` |
| 1.12 | `test_track_cover_art_default_none` | New Track has `cover_art=None` |
| 1.13 | `test_thumbnail_cache_get_none_returns_none` | `get(None)` → `None` |
| 1.14 | `test_thumbnail_cache_put_and_get` | Store then retrieve image |
| 1.15 | `test_thumbnail_cache_lru_eviction` | After `max_entries`, oldest evicted |
| 1.16 | `test_thumbnail_cache_same_bytes_same_object` | Same bytes → same cached image object |
| 1.17 | `test_matrix_model_empty_after_no_flac` | Non-FLAC folder → `tracks=[]`, `columns=[]` |
| 1.18 | `test_load_single_flac_populates_tracks` | One `.flac` → 1 track loaded |
| 1.19 | `test_load_recursive_finds_subdirs` | `.flac` in subdirectories loaded |
| 1.20 | `test_load_skips_corrupt_file` | Corrupt file → failure in list, no crash |
| 1.21 | `test_load_auto_pin_standard_same_value` | `ALBUM` same across tracks → pinned |
| 1.22 | `test_load_no_pin_standard_different_value` | `ARTIST` differs across tracks → unpinned |
| 1.23 | `test_load_no_pin_non_standard` | `CUSTOM` key → never auto-pinned |
| 1.24 | `test_load_duplicate_keys_separate_columns` | Two `REPLAYGAIN` → two `Column` objects |
| 1.25 | `test_load_structural_keys_not_columns` | `TRACKNUMBER`/`DISCNUMBER` never in columns |
| 1.26 | `test_load_disc_from_tag` | `DISCNUMBER: 2/3` → `track.disc=2` |
| 1.27 | `test_load_default_disc_one` | Missing DISCNUMBER → `track.disc=1` |
| 1.28 | `test_load_cover_art_stored` | Embedded picture → `cover_art` populated |
| 1.29 | `test_load_no_cover_art_none` | No picture → `cover_art=None` |
| 1.30 | `test_load_original_tags_copied` | `original_tags` matches raw tags |
| 1.31 | `test_load_original_cover_copied` | `original_cover` matches embedded image |
| 1.32 | `test_columns_sorted_pinned_first` | Pinned columns precede unpinned |
| 1.33 | `test_columns_preserve_first_seen_order` | Order = first-seen key order |
| 1.34 | `test_load_fresh_album_defaults` | Empty album gets STANDARD_KEYS columns |
| 1.35 | `test_load_all_tags_identical_standard_pinned` | All tags identical + standard → pinned |

---

## II. Column Operations (13 tests)

| # | Name | What it covers |
|---|------|----------------|
| 2.1 | `test_add_column_after_none_first_unpinned` | `add_column(None, "K")` → first unpinned |
| 2.2 | `test_add_column_after_pinned_first_unpinned` | `add_column(pinned, "K")` → first unpinned |
| 2.3 | `test_add_column_after_unpinned_inserted_right` | `add_column(unpinned, "K")` → after it |
| 2.4 | `test_add_column_tracks_have_slot` | New column adds empty slot to all tracks |
| 2.5 | `test_duplicate_column_same_key_pin` | Duplicate → same key/pin, empty cells, right |
| 2.6 | `test_delete_column_removed_from_columns` | `delete_column` removes from list |
| 2.7 | `test_delete_column_removes_slots` | Slot removed from all tracks |
| 2.8 | `test_toggle_pin_pinned_to_unpinned` | → near edge of unpinned zone |
| 2.9 | `test_toggle_pin_unpinned_to_pinned` | → far edge of pinned zone |
| 2.10 | `test_reorder_column_pinned_zone` | Swap within pinned zone |
| 2.11 | `test_reorder_column_unpinned_zone` | Swap within unpinned zone |
| 2.12 | `test_reorder_column_blocked_at_edge` | Boundary → no change |
| 2.13 | `test_set_pinned_value_broadcasts` | `set_pinned_value` → all tracks |

---

## III. Disc / Ordering / Auto-number (13 tests)

| # | Name | What it covers |
|---|------|----------------|
| 3.1 | `test_discs_sorted_unique` | `discs()` → sorted unique disc numbers |
| 3.2 | `test_tracks_in_disc_sorted_by_position` | `tracks_in_disc(d)` → ordered by position |
| 3.3 | `test_ordered_tracks_interleaves_discs` | `ordered_tracks()` interleaves discs |
| 3.4 | `test_move_track_within_disc` | `move_track(t, 1)` swaps positions |
| 3.5 | `test_move_track_boundary_blocked` | At boundary → no change |
| 3.6 | `test_set_disc_lower` | `set_disc(t, 1)` → moves to disc 1 |
| 3.7 | `test_set_disc_higher_creates_new` | `set_disc(t, 3)` → new disc created |
| 3.8 | `test_set_disc_below_one_blocked` | `set_disc(t, 0)` → no change |
| 3.9 | `test_auto_number_single_disc` | One disc → TRACKNUMBER 1..N |
| 3.10 | `test_auto_number_multi_disc` | Multiple discs → per-disc numbering |
| 3.11 | `test_auto_number_writes_computed_attrs` | `computed_tracknumber` etc. set |
| 3.12 | `test_auto_number_resets_old` | Re-running overwrites previous values |
| 3.13 | `test_auto_number_disc_total_correct` | DISCTOTAL = number of discs |

---

## IV. Effective Tags / Diff / Save (15 tests)

| # | Name | What it covers |
|---|------|----------------|
| 4.1 | `test_get_effective_tags_no_changes` | Returns original + structural |
| 4.2 | `test_get_effective_tags_with_changes` | Modified slots reflected |
| 4.3 | `test_get_effective_tags_empty_skipped` | Blank values not included |
| 4.4 | `test_get_effective_tags_includes_structural` | `computed_tracknumber` as pair |
| 4.5 | `test_diff_for_track_no_changes` | Empty list when nothing changed |
| 4.6 | `test_diff_for_track_value_changed` | `KEY: old -> new` format |
| 4.7 | `test_diff_for_track_key_added` | `KEY: [] -> [new_val]` |
| 4.8 | `test_diff_for_track_key_removed` | `KEY: [old_val] -> []` |
| 4.9 | `test_diff_for_track_cover_changed` | `"cover art changed"` |
| 4.10 | `test_diff_for_track_multiple_keys` | Multiple changed keys listed |
| 4.11 | `test_has_unsaved_changes_true` | Any diff → `True` |
| 4.12 | `test_has_unsaved_changes_false` | No diffs → `False` |
| 4.13 | `test_save_all_success_updates_original` | `original_tags`/`original_cover` updated |
| 4.14 | `test_save_all_partial_failure` | Some fail → others saved, failures returned |
| 4.15 | `test_save_writes_structural_tags` | `TRACKNUMBER`/`DISCNUMBER` written |

---

## V. Undo / Redo (9 tests)

| # | Name | What it covers |
|---|------|----------------|
| 5.1 | `test_undo_no_stack` | `undo()` → `False` |
| 5.2 | `test_undo_one_step` | Restore previous columns+tracks |
| 5.3 | `test_undo_multiple_steps` | LIFO restoration |
| 5.4 | `test_redo_no_stack` | `redo()` → `False` |
| 5.5 | `test_redo_after_undo` | Restore undone state |
| 5.6 | `test_new_action_clears_redo` | Mutation after undo clears redo stack |
| 5.7 | `test_history_limit_cap` | 101 pushes → oldest evicted |
| 5.8 | `test_cover_art_sharing_across_snapshots` | `cover_art` bytes not duplicated |
| 5.9 | `test_undo_deep_copy_independent` | Current object independent of undo copy |

---

## VI. CLI / App Initialization (7 tests)

| # | Name | What it covers |
|---|------|----------------|
| 6.1 | `test_main_no_args_exits_1` | `sys.exit(1)` |
| 6.2 | `test_main_non_directory_exits_1` | `sys.exit(1)` |
| 6.3 | `test_main_creates_app_with_model` | `MersikApp(root)` created |
| 6.4 | `test_app_loads_directory_on_mount` | `load_directory` called |
| 6.5 | `test_app_pushes_matrix_screen` | `MatrixScreen` pushed |
| 6.6 | `test_app_notifies_load_failures` | Failure notification shown |
| 6.7 | `test_app_no_notification_on_success` | No failure notification |

---

## VII. UI / Textual Headless Tests (36 tests)

| # | Name | What it covers |
|---|------|----------------|
| 7.1 | `test_empty_state_shown` | No tracks → empty message, DataTable hidden |
| 7.2 | `test_table_rebuilt_with_columns` | DataTable populated with columns/rows |
| 7.3 | `test_disc_column_rendered_with_color` | `D{disc}` with `PALETTE` color |
| 7.4 | `test_pinned_column_has_label` | `[dim](pinned)[/dim]` in header |
| 7.5 | `test_truncate_long_values` | >40 chars → `…` |
| 7.6 | `test_current_track_returns_track` | `current_track()` returns correct track |
| 7.7 | `test_current_column_returns_column` | `current_column()` returns correct column |
| 7.8 | `test_edit_cell_pinned_broadcasts` | Pinned edit → all tracks |
| 7.9 | `test_edit_cell_unpinned_single` | Unpinned → one cell only |
| 7.10 | `test_add_column_prompts` | `a` → `PromptScreen` |
| 7.11 | `test_duplicate_column_works` | `d` → duplicate created |
| 7.12 | `test_delete_column_works` | `x` → column removed |
| 7.13 | `test_toggle_pin_works` | `p` → pinned toggled, position changed |
| 7.14 | `test_move_row_works` | `shift+j/k` → row order changed |
| 7.15 | `test_change_disc_works` | `+/−` → disc changed |
| 7.16 | `test_auto_number_works` | `n` → numbers recomputed |
| 7.17 | `test_search_prompts` | `/` → `PromptScreen` |
| 7.18 | `test_search_jumps_to_match` | Cursor jumps to matching row |
| 7.19 | `test_search_wrap` | Search wraps around |
| 7.20 | `test_save_prompts` | `w/s` → `SaveDiffScreen` |
| 7.21 | `test_save_confirm` | `y` → `save_all()` called |
| 7.22 | `test_save_cancel` | `n/esc` → no save |
| 7.23 | `test_quit_no_changes_exits` | `q` → exit immediately |
| 7.24 | `test_quit_with_changes_prompts` | `q` → `ConfirmQuitScreen` |
| 7.25 | `test_quit_confirmed` | `y` → exits |
| 7.26 | `test_quit_cancelled` | `n/esc` → stays |
| 7.27 | `test_cover_art_info_shown` | Track name, cover status shown |
| 7.28 | `test_cover_art_no_art_hidden` | No cover → preview hidden |
| 7.29 | `test_cover_art_with_art` | Cover → preview shown |
| 7.30 | `test_cover_art_left_right` | Arrows → index changes, info refreshes |
| 7.31 | `test_cover_art_apply_all` | `shift+A` → all tracks get cover |
| 7.32 | `test_cover_art_apply_all_no_cover` | No cover → warning notification |
| 7.33 | `test_cover_art_back` | `esc` → back to matrix |
| 7.34 | `test_prompt_dismiss_value` | Submit → `dismiss(value)` |
| 7.35 | `test_prompt_dismiss_none` | Escape → `dismiss(None)` |
| 7.36 | `test_edit_cell_screen_dismiss_value` | Submit → `dismiss(value)` |
| 7.37 | `test_edit_cell_screen_dismiss_none` | Escape → `dismiss(None)` |
| 7.38 | `test_save_diff_shows_changes` | Diff lists all changed tracks/tags |
| 7.39 | `test_save_diff_no_changes` | Shows "No changes staged." |
| 7.40 | `test_confirm_quit_dismiss` | `y/n/esc` → correct dismiss value |

---

## VIII. Edge Cases / Robustness (10 tests)

| # | Name | What it covers |
|---|------|----------------|
| 8.1 | `test_no_tracks_no_crash_any_method` | Zero tracks → no errors |
| 8.2 | `test_move_track_no_tracks` | `move_track` → no error |
| 8.3 | `test_set_disc_no_tracks` | `set_disc` → no error |
| 8.4 | `test_auto_number_no_tracks` | `auto_number` → no error |
| 8.5 | `test_discs_empty` | Zero tracks → empty list |
| 8.6 | `test_ordered_tracks_empty` | Zero tracks → empty list |
| 8.7 | `test_cover_art_apply_all_no_tracks` | Zero tracks → no crash |
| 8.8 | `test_load_directory_with_symlink_loop` | Symlink loop handled gracefully |
| 8.9 | `test_load_directory_permission_denied_dir` | Permission error on dir → graceful |
| 8.10 | `test_load_with_mixed_flac_and_other_files` | Only `.flac` files loaded |

---

## Test Run Commands

Run these from the **repo root** (`tests/` is a sibling of `src/`, not
nested inside it):

```bash
# Run all tests
pytest tests/ -v

# Run a specific area
pytest tests/test_models.py -v         # Data model (I)
pytest tests/test_column_ops.py -v     # Column operations (II)
pytest tests/test_disc_numbering.py -v # Disc/numbering (III)
pytest tests/test_save_diff.py -v      # Effective tags/diff/save (IV)
pytest tests/test_undo_redo.py -v      # Undo/redo (V)
pytest tests/test_cli_app.py -v        # CLI/App (VI)
pytest tests/test_ui.py -v             # UI headless (VII)
pytest tests/test_edge_cases.py -v     # Edge cases (VIII)

# Run with coverage
pytest tests/ --cov=src --cov-report=term-missing -v
```

## File Structure

```
mersik/                     # repo root
  src/
    app.py
    models.py
    README.md
    TEST_PLAN.md            # this file
  tests/
    conftest.py             # fixtures: temp FLAC files, in-memory model, PNG bytes
    test_models.py          # Area I
    test_column_ops.py      # Area II
    test_disc_numbering.py  # Area III
    test_save_diff.py       # Area IV
    test_undo_redo.py       # Area V
    test_cli_app.py         # Area VI
    test_ui.py              # Area VII
    test_edge_cases.py      # Area VIII
  pytest.ini                # asyncio_mode = auto, testpaths = tests
```

Note: `app.py`/`models.py` use plain top-level imports (`from models
import ...`), not a package-relative import, so `tests/conftest.py`
inserts `src/` onto `sys.path` at collection time. This is why tests
import with `from models import ...` / `import app as app_module`
rather than `from src.models import ...`.

## Fixture Strategy

- `make_flac(path, tags, picture=None)` (in `conftest.py`, not a
  fixture itself but used by several fixtures/tests directly): creates
  a real, valid FLAC file via `ffmpeg` (silent audio stream) +
  `mutagen` (exact Vorbis comments, optional embedded cover), clearing
  ffmpeg's own `encoder` tag first so fixture data is exactly what the
  test specifies.
- `temp_flac_dir`: two-track single-disc album with matching
  ALBUM/ALBUMARTIST, differing ARTIST/TITLE, a duplicate-key
  (`REPLAYGAIN_TRACK_GAIN` x2) case, and one embedded cover.
- `temp_multidisc_dir`: two discs, two tracks each, real `DISCNUMBER`
  tags on disk.
- `temp_empty_dir`: empty directory for "no FLAC files" edge cases.
- `png_bytes` / `make_png_bytes(...)`: small real PNG bytes for cover
  art tests, via Pillow.
- `model_with_tracks`: a `MatrixModel` built **entirely in memory** (no
  disk I/O, no ffmpeg dependency) with 3 tracks across 2 discs and a
  mix of pinned/unpinned columns — used for the column-ops,
  disc-ordering, and undo/redo suites, which don't need real files and
  run faster without them.
- A session-scoped `autouse` fixture skips the whole run if `ffmpeg` is
  not on `PATH`, since every disk-based fixture depends on it.
