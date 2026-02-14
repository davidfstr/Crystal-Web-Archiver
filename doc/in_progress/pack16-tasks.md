# Pack16 Implementation Breakdown

Reference: `doc/tech_designs/pack16.md`

---

## Increment 1: Write revisions with packing

**Goal:** During download, after every 16th revision, pack the group into a zip.

**Work:**
- Add `_body_pack_filepath_with()` static method to `ResourceRevision` that computes
  the pack zip file path for a given revision ID (e.g., revision `0x01a` → `000/000/000/001/01_.zip`).
- Add helper that computes the entry name within a pack zip for a given revision ID
  (e.g., revision `0x01a` → `'01a'`).
- Add utility function (likely in new module `crystal/model/pack16.py`):
  - `create_pack_file(revision_files: dict[str, str], dest_path: str, tmp_dir: str)`:
    Create an uncompressed ZIP64 file from a mapping of `{entry_name: source_filepath}`.
    Write to `tmp_dir` first, fsync, then `rename_and_flush` to `dest_path`.
- Update `_LATEST_SUPPORTED_MAJOR_VERSION` to `3` in Project class.
- Make `_body_filepath_with()` work for `major_version == 3` (same hierarchical paths as version 2).
- After a revision is successfully written in `_create_from_stream()`, check whether
  this revision completes a group of 16 (i.e., `revision_id % 16 == 15`).
  More precisely: pack when `revision_id` is of the form `16*k - 1` for some k≥1, which
  means hex digit pattern `XX...Xf`.
- When packing is triggered:
  1. Identify revision IDs `16*k - 16` through `16*k - 1` (the 16 in the group).
  2. Collect those that have body files on disk.
  3. Call `create_pack_file()` to write the zip.
  4. Delete the individual files.
- Handle edge case: error-only revisions (no body file) — trigger packing after the
  DB row is written, even though no file was written. The pack may contain fewer than
  16 entries (or even zero, in which case skip writing the pack).
- This logic only activates for `major_version >= 3`.

**Tests:**
- Unit test for path computation: various revision IDs → expected pack paths and entry names.
- E2E: `test_given_project_in_pack16_format_when_create_multiple_of_16_resource_revisions_then_creates_pack_file_if_at_least_one_revision_body_exists`
  - Set `project._set_major_version(3, project._db)` directly on empty project
  - Case 1 (subtest): 16th + 32nd revision has a body; verify 2 packs created
  - Case 2 (subtest): 16th + 32nd revision has no body, rest have bodies; verify 2 packs
  - Case 3 (subtest): first 16 revisions have no body, next 16 have body; verify 1 pack (second group)
  - Case 4 (subtest): first 16 revisions have body, next 16 have no body; verify 1 pack (first group)
- E2E: `test_given_project_in_pack16_format_when_create_non_multiple_of_16_resource_revisions_then_creates_individual_files`
  - Download 18 resources
  - Verify pack 00_ exists
  - Verify files 010-011 remain as individual files

**Key files:**
- `src/crystal/model/resource_revision.py` (modify `_create_from_stream`, add `_body_pack_filepath_with`)
- `src/crystal/model/project.py` (update `_LATEST_SUPPORTED_MAJOR_VERSION`)
- New: `src/crystal/model/pack16.py`
- New: `tests/test_pack16.py` (unit test for path computation)
- New: `src/crystal/tests/model/test_pack16.py` (E2E tests)

**Estimated time:** ~3 hours

---

## Increment 2: Read revisions from pack files

**Goal:** `ResourceRevision.open()` and `body_size` can read from pack zip files.

**Work:**
- Add utility function to `pack16.py`:
  - `read_pack_entry(pack_path: str, entry_name: str) -> BinaryIO`:
    Open a specific entry from a pack zip, returning a file-like object via
    `zipfile.ZipFile.open()`. The returned file-like object must keep the `ZipFile`
    open until the stream is closed (wrap if needed).
- Modify `ResourceRevision.open()`: for `major_version >= 3`, try the pack file first
  (via `read_pack_entry`). If the pack file doesn't exist or the entry isn't in it,
  fall back to the hierarchical file. If neither exists, raise `RevisionBodyMissingError`.
- Similarly modify `ResourceRevision.body_size` to support reading size from pack entries.

**Tests:**
- E2E: Extend Increment 1 tests to verify revisions can be read back via
  `revision.open()` after being packed. Preserve the low-level filesystem checks too.
- E2E: `test_given_project_with_major_version_3_when_pack_file_missing_then_falls_back_to_hierarchical_file`
  - Create v3 project with 16 revisions (creates pack 00_)
  - Manually delete pack file, restore individual files
  - Verify `open()` still works by reading hierarchical files
- E2E: `test_given_project_with_major_version_3_when_both_pack_and_hierarchical_missing_then_raises_revision_body_missing_error`
  - Create revision with body
  - Manually delete both pack and hierarchical file
  - Verify `open()` raises `RevisionBodyMissingError`

**Key files:**
- `src/crystal/model/resource_revision.py` (modify `open`, `body_size`)
- `src/crystal/model/pack16.py` (add `read_pack_entry`)
- `src/crystal/tests/model/test_pack16.py`

**Estimated time:** ~2 hours

---

## Increment 3: Recovery — complete incomplete packs on project open

**Goal:** When opening a v3 project, detect and complete any pack that should have been
written but wasn't (e.g., due to disk-full during a previous session).

**Work:**
- On project open (in `_load()` or `_apply_migrations()` for `major_version == 3`):
  1. Query the highest revision ID from the database.
  2. Compute which pack should contain it.
  3. Check if that pack file exists on disk.
  4. If not, and there are loose revision files that should be in it, run the packing
     operation.
- This only applies to the *highest-numbered* pack, per the tech design.
- Extract packing logic from `_create_from_stream()` to a reusable function in `pack16.py`.

**Tests:**
- E2E: `test_given_individual_files_exist_for_last_missing_complete_pack_file_when_project_opened_then_pack_file_created_and_individual_files_deleted`
  - Create v3 project with 20 revisions (should create packs 00_ and 01_)
  - Close project
  - Manually delete pack 01_.zip and restore individual files 010-013
  - Reopen project
  - Verify pack 01_.zip is recreated
  - Verify individual files are deleted
- E2E: `test_given_individual_files_exist_for_last_missing_incomplete_pack_file_when_project_opened_then_pack_file_not_created_and_individual_files_retained`
  - Create v3 project with 18 revisions (pack 00_, then files 010-011)
  - Close and reopen
  - Verify files 010-011 remain as individual files (no pack created)

**Key files:**
- `src/crystal/model/project.py` (modify `_load` or related)
- `src/crystal/model/pack16.py` (extract reusable packing function)
- `src/crystal/tests/model/test_pack16.py`

**Estimated time:** ~2 hours

---

## Increment 4: Delete revisions from pack files

**Goal:** `ResourceRevision.delete()` works correctly when the revision is inside a pack.

**Prerequisite Work:**
- Create `DeleteResourceRevisionTask` — a new leaf Task type that performs `ResourceRevision` deletion
  on the scheduler thread, to avoid concurrent access to pack files during writes.
- Change the public `delete()` API to return a `Future` so callers can await completion.
  Update all existing callers of `delete()` to handle the new async API.

**Work:**
- Add utility function to `pack16.py`:
  - `rewrite_pack_without_entry(pack_path: str, entry_name: str, tmp_dir: str)`:
    Rewrite a pack zip file with one entry removed. Write to tmp, fsync, then move into place.
    If the pack becomes empty after removal, delete the pack file entirely.
- Modify `delete()`: for `major_version >= 3`, check if the revision is in a pack file.
  If so, rewrite the pack without that entry (via `rewrite_pack_without_entry`).
  If not, fall back to deleting the hierarchical file.

**Tests:**
- E2E: `test_given_nonlast_resource_revision_in_pack_file_when_deleted_then_pack_file_rewritten_without_it`
  - Create v3 project with 16 revisions (creates pack 00_)
  - Delete one revision from the pack (not the last one)
  - Verify pack is rewritten without that entry
  - Verify other revisions in same pack are still readable via `open()`
- E2E: `test_given_last_resource_revision_in_pack_file_when_deleted_then_pack_file_deleted`
  - Create v3 project with 16 revisions
  - Delete all but one revision from the pack
  - Delete the last revision
  - Verify pack file is removed entirely

**Key files:**
- `src/crystal/model/resource_revision.py` (modify `delete`)
- `src/crystal/model/pack16.py` (add `rewrite_pack_without_entry`)
- `src/crystal/task.py` (new `DeleteResourceRevisionTask`)
- Callers of `delete()` — search for usages and update
- `src/crystal/tests/model/test_pack16.py`

**Estimated time:** ~3 hours

---

## Increment 5: Migration — core logic

**Goal:** Packing all existing hierarchical revisions into Pack16 format during a
modal progress dialog at project open, following the same pattern as the
existing Flat → Hierarchical migration.

**Work:**
- Add migration logic to `_apply_migrations()` in `project.py` (or a new
  `_migrate_v2_to_v3` function following the pattern of `_migrate_v1_to_v2`):
  1. Detect migration-in-progress marker: `major_version == 3` and
     `major_version_old == 2`.
  2. Scan revision IDs starting at `1`, progressing in increments of 16.
     For each group, check if the corresponding .zip file exists. If not,
     and the range contains at least one revision expecting a body, pack it.
  3. Skip revisions that have been deleted or lack bodies. Incomplete packs
     (fewer than 16 revisions in the final group) remain as individual files.
  4. On completion, remove the `major_version_old` marker.
- Report progress in terms of revisions processed, reusing the existing
  `{will_upgrade_revisions, upgrading_revision, did_upgrade_revisions}`
  callbacks in `OpenProjectProgressListener`. The lower-level code processes
  in units of packs but advances the progress count by 16 per pack (or by the
  actual revision count in the final incomplete group).
- The migration is triggered in tests by simulating what the Preferences UI
  will do later (Increment 7):
  1. Hibernate any running tasks (`hibernate_tasks`) and stop the scheduler
     (`_stop_scheduler`).
  2. Set `major_version_old` to `2`.
  3. Set `major_version` to `3`.
  4. Close the project. Reopen the project.
  Migration starts/resumes automatically on reopen via `_apply_migrations()`.

**Tests:**
- E2E: `test_given_project_with_major_version_2_when_migrate_to_pack16_then_creates_all_packs_and_upgrades_to_major_version_3`
  - Create v2 project with ~50 revisions
  - Trigger migration programmatically (set markers, close, reopen)
  - Verify all expected packs are created on disk
  - Verify `major_version == 3` and `major_version_old` is removed
  - Verify all revisions still readable via `open()`
- E2E: `test_given_empty_project_when_migrate_to_pack16_then_migration_completes_immediately`
  - Create v2 project with no revisions
  - Trigger migration programmatically
  - Verify project opens as v3 with no pack files
- E2E: `test_given_project_with_only_error_revisions_when_migrate_to_pack16_then_creates_no_pack_files`
  - Create v2 project where all revisions are error-only (no bodies)
  - Trigger migration programmatically
  - Verify no pack files created, project is v3

**Key files:**
- `src/crystal/model/project.py` (add `_migrate_v2_to_v3` in `_apply_migrations`)
- `src/crystal/model/pack16.py` (reuse packing functions from Increment 1)
- `src/crystal/tests/model/test_pack16.py`

**Estimated time:** ~3 hours

---

## Increment 6: Migration robustness — resume, cancel, error handling

**Goal:** Migration survives cancellation, crashes, and I/O errors gracefully.

**Work:**
- Ensure the `major_version_old` marker persists across close/reopen so that
  an interrupted migration resumes automatically on next project open.
  (This should work naturally from the Increment 5 design — the marker is only
  removed on successful completion.)
- Support cancellation: the modal progress dialog is cancelable. On cancel,
  close the project. The migration-in-progress marker remains, so the next
  open will resume from where it left off (scanning for the first unmigrated pack).
- Handle I/O errors during migration: if a hierarchical file can't be read after
  opening, skip it from the pack, leave the original file in place, warn to stderr.
    - The current implementation in `create_pack_file` uses `ZipFile.write` which I suspect
      doesn't provide enough control to:
      (1) detect whether an I/O error occurred during a read of the old revision 
          vs. an I/O error during a write to the pack file or
      (2) recover from a failed write to the pack file - it's not clear from
          the ZipFile documentation whether a failed `write` leaves the zip file
          in a good state or not, with the partial entry removed. Look at CPython
          source code (available in this workspace, or at `/Users/davidf/Projects/cpython`)
          to see what kind of error recovery is builtin, if any.
          - If no builtin error recovery, it MAY be sufficient to save the zip file's prior
            location (via `tell`) immediately before attempting to write a zip entry,
            and if an error is raised, rewind the zip file to the old location (via `seek`)
            and truncate the file size to end at the old location. Testing required
            to determine whether that procedure actually works.
- Ensure temp pack files in `tmp/` are cleaned up on project open (existing tmp
  cleanup logic already handles this).

**Tests:**
- E2E: `test_given_migration_in_progress_when_cancel_and_reopen_project_then_migration_resumes_and_completes`
  - Create v2 project with 50+ revisions
  - Trigger migration programmatically
  - Cancel the progress dialog mid-migration
  - Verify project is closed and some packs exist (partial migration)
  - Reopen project
  - Verify migration resumes and completes
  - Verify all revisions readable
- E2E: `test_given_corrupt_revision_file_when_migrate_to_pack16_then_skips_file_and_warns`
  - Create v2 project with revisions
  - Corrupt one revision file
    - Simulate I/O error when reading a particular revision ID but not other IDs
  - Trigger migration programmatically
  - Verify migration completes
  - Verify corrupt file is skipped from pack and left in place
  - Verify warning is emitted to stderr
- E2E: `test_given_interrupted_migration_when_reopen_then_cleans_up_temp_pack_files`
  - Mark as `@skip('covered by: X')`, where X is the E2E test name verifying that
    a project's "tmp" directory is cleaned upon open

**Key files:**
- `src/crystal/model/project.py` (migration resume logic, tmp cleanup)
- `src/crystal/model/pack16.py`
- `src/crystal/tests/model/test_pack16.py`

**Estimated time:** ~3 hours

---

## Increment 7a: Preferences UI — Revision Storage Format

**Goal:** User can see the project's current revision storage format in Preferences
and initiate a Hierarchical → Pack16 (or Flat → Hierarchical) migration via a checkbox.

**Work:**
- Add a "Revision Storage Format" section to Preferences showing:
  - A read-only label displaying the current format name
    (1=Flat, 2=Hierarchical, 3=Pack16).
  - A "Migrate to ..." checkbox, shown only when a valid migration is available:
    - Flat project: `[ ] Migrate to Hierarchical`
    - Hierarchical project: `[ ] Migrate to Pack16`
    - Pack16 project: no checkbox shown.
- When "Migrate to Hierarchical" is checked and OK is pressed: signal migration
  by creating the `revisions.inprogress` directory (existing behavior), then
  close and reopen the project.
- When "Migrate to Pack16" is checked and OK is pressed:
  1. Show warning dialog ("may take several hours", "Cancel" / "Migrate" buttons).
  2. On confirm: set `major_version_old = 2`, set `major_version = 3`,
     close and reopen the project. Migration starts automatically on reopen
     (Increment 5).
- Disable the checkbox when `project.readonly`.

**Tests:**
- E2E: `test_preferences_dialog_shows_current_revision_storage_format`
  - Open preferences for v1, v2, v3 projects
  - Verify label shows "Flat", "Hierarchical", "Pack16" respectively
  - Verify checkbox text and visibility is correct for each format
- E2E: `test_given_hierarchical_project_when_migrate_to_pack16_via_preferences_and_user_confirms_then_migration_completes`
  - Create v2 project with revisions
  - Open Preferences, check "Migrate to Pack16", press OK, confirm warning
  - Characterize current behavior where second dialog appears after project reopens,
    that must be explicitly confirmed.
  - Verify migration runs (progress dialog appears and completes)
  - Verify project is now v3 with packs created
- E2E: `test_given_hierarchical_project_when_migrate_to_pack16_via_preferences_and_cancel_warning_then_no_migration`
  - Create v2 project
  - Open Preferences, check "Migrate to Pack16", press OK, cancel warning
  - Verify project remains v2
- E2E: `test_given_flat_project_when_migrate_to_hierarchical_via_preferences_then_migration_and_completes`
  - Create v1 project with revisions
  - Open/reopen project. Dismiss dialog prompting migrate v1 -> v2.
    Project finishes opening as v1.
  - Open Preferences, check "Migrate to Hierarchical", press OK.
  - Characterize current behavior where un-vetoable dialog appears after project reopens,
    that must be explicitly confirmed.
  - Verify migration runs (progress dialog appears and completes)
  - Verify project is now v2

**Key files:**
- `src/crystal/browser/preferences.py`
- `src/crystal/tests/test_preferences.py` (or new test file)

**Estimated time:** ~2-3 hours

---

## Increment 7b: Migration UI Robustness

- When open project, if a migration is already in progress
  then don't prompt the user whether to continue it or or cancel opening the project.
  Instead, just continue immediately. The user can cancel opening the project
  during the migration process itself if desired.
  - [ ] Alter behavior, to remove unhelpful prompt
  - [ ] E2E test change: `test_given_hierarchical_project_when_migrate_to_pack16_via_preferences_and_user_confirms_then_migration_completes`
    - No second dialog appears after project reopens
  - [ ] E2E test change: `test_given_flat_project_when_migrate_to_hierarchical_via_preferences_then_migration_and_completes`
    - No confirmation dialog appears at all to start the migration. Hmm.
    - Add above test function def: `# TODO: Add 1 confirmation dialog before starting migration`

Error handling during v2 -> v3 migration, in UI layer:
- If I/O error while reading an individual revision file being packed, it is left outside the pack, a warning is printed to stderr (not to the UI), and the migration continues.
  - [ ] E2E test extend: `test_given_corrupt_revision_file_when_migrate_to_pack16_then_skips_file_and_warns`
    - Extend to actually check that a warning is printed to stderr
- If I/O error while writing a pack file...
  - Currently, `create_pack_file` raises OSError when fail to write pack file.
    Then `_pack_revisions_for_id` prints warning to stderr and otherwise fails silently.
    Then `_migrate_v2_to_v3` continues on to further pack files. This is OK actually.
  - [ ] E2E test add: `test_given_cannot_write_pack_file_when_migrate_to_pack16_then_skips_file_and_warns`,
    after existing test: `test_given_corrupt_revision_file_when_migrate_to_pack16_then_skips_file_and_warns`
  - [ ] Update docstring of `_pack_revisions_for_id` to explain that fails with
        a warning to stderr if cannot write pack file but does NOT raise an
        error to its caller
- If disk disconnect while running migration...
  - See §"Crystal: Migrate: Disk disconnect scenario" below.

### Crystal: Migrate: Disk disconnect scenario

Crystal‘s current migration strategy of skipping individual divisions or pack files with IO errors works well when there are individual I owe issues. (such as bad blocks). However, this strategy of skipping individual files does not work well when a widespread error takes an entire project directory off-line, such as disk disconnection. Currently, a disk disconnection will cause very many IO errors to be printed to the console, but the migration will continue until the very last step when it tries to commit the migration to the database. At that point it will fail, but it will in the meantime have spent a lot of wasted time trying to migrate individual revisions and pack files that cannot be accessed at all.

A better behavior would be to periodically do a lightweight check of overall disk health during a migration. If the disk health check fails, then the entire migration should be aborted early rather than continuing all the way to the end. 

Proposal:
- Every ~256 revisions (revision_id % 256 == 0) the directory containing the current/next revision should be listed to see whether the directory list operation has a IO error in particular if it has a file not found error. If any of these errors are detected on the directory list operation than the entire migration should be aborted and the UI should report that the disk containing the project appears to no longer be available and to try the migration again later.
- A similar check is performed directly after processing the last revision being migrated.

Tasks:
- Implement the above change in behavior, such that the UI will report when a migration fails early because of disk disconnection.
- Add test: test given disk disconnects before migration reaches intermediate checkpoint then when checkpoint hit then aborts migration early and displays error dialog and closes project
- Add test: test given disk disconnects before migration reaches final checkpoint then when checkpoint hit then aborts migration early and displays error dialog and closes project

---

## Increment 8: Polish, edge cases, and release notes

**Goal:** Ensure all edge cases are covered, comprehensive test coverage, and documentation.

**Work:**
- Handle edge case: project with revision ID 0 (shouldn't exist by SQLite auto-increment,
  but be defensive in pack boundary calculations).
- Handle edge case: v3 project opened by older Crystal version → verify
  `ProjectTooNewError` is raised with a clear message. (Should already work, but test it.)
- Review all `body_filepath` usages across the codebase and verify they work for v3.
  (Search for `_body_filepath`, `_body_filepath_with`, `_REVISIONS_DIRNAME` usage.)
- Add release notes entry to `RELEASE_NOTES.md` in the "main" branch section.
- Final pass through all tests; add any missing coverage.

**Tests:**
- E2E: `test_given_project_with_major_version_3_when_opened_by_older_crystal_then_raises_project_too_new_error`
  - `# NOTE: See also: test_refuses_to_open_project_with_unknown_high_major_version`
  - Create v3 project
  - Temporarily set `Project._LATEST_SUPPORTED_MAJOR_VERSION = 2`
  - Attempt to open project
  - Verify `ProjectTooNewError` is raised
- Run full test suite (`crystal test` and `pytest`) to verify no regressions

**Key files:**
- Various (audit pass)
- `RELEASE_NOTES.md`
- `src/crystal/tests/model/test_pack16.py`

**Estimated time:** ~2 hours

---

## Increment 9: Pre/post-branch fixes

[ ] Fix broken "from crystal.model import *" in shell. The "project" subpackage
    overrides the "project" builtin provided by the shell. Probably need to
    define __all__ for crystal.model.

---

## Summary

| # | Increment | Est. | Depends on |
|---|-----------|------|------------|
| 1 | Write revisions with packing | 3h | — |
| 2 | Read revisions from pack files | 2h | 1 |
| 3 | Recovery — complete incomplete packs on open | 2h | 1, 2 |
| 4 | Delete revisions from pack files | 3h | 1, 2 |
| 5 | Migration — core logic | 3h | 1, 2, 3 |
| 6 | Migration robustness — resume, cancel, errors | 3h | 5 |
| 7 | Preferences UI — revision storage format | 2-3h | 5, 6 |
| 8 | Polish, edge cases, and release notes | 2h | all |
| | **Total** | **~20-21h** | |

**Recommended order:** 1 → 2 → 3 → 4 → 5 → 6 → 7 → 8

Each increment builds working, testable functionality using E2E tests.
Early increments (1-4) can use `project._set_major_version(3, project._db)` directly in tests before the UI is ready.
Migration increments (5-6) trigger migration programmatically (set markers, close, reopen) without needing the Preferences UI.
The Preferences UI (7) is implemented last, after the model-layer migration is solid.
