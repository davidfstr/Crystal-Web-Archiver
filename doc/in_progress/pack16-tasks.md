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

## Increment 4.5: Additional concurrency testing

[ ] Heavily test concurrent scenarios for Create + {Read, Delete},
    because Create does not sync with scheduler thread (and therefore
    cannot assume it has exclusive access). See code marked as below.
    - Also: Windows probably needs special happening RE Reads colliding with
      other operations, since file Reads on Windows prevent Delete

```python
# NOTE: NOT @scheduler_affinity despite doing revision body I/O,
#       because it uses lock-less mechanisms to accomodate concurrent operations
```

---

## Increment 5: Preferences UI — Revision Storage Format dropdown

**Goal:** User can see and change the project's revision storage format in Preferences.

**Work:**
- Add a "Revision Storage Format" dropdown to the Project section of PreferencesDialog
  with options: "Flat", "Hierarchical", "Pack16".
- Display the current format based on `project.major_version` (1=Flat, 2=Hierarchical,
  3=Pack16).
- Validate transitions on OK:
  - Flat → Hierarchical: trigger existing migration flow.
  - Hierarchical → Pack16: allowed (will trigger migration in Increment 6).
  - All other transitions: show error dialog with appropriate message per tech design:
    - Hierarchical → Flat: 'Migrating from "Hierarchical" to "Flat" format is not supported.'
    - Flat → Pack16: 'Migrating from "Flat" to "Pack16" directly is not supported. Migrate to "Hierarchical" first.'
    - Pack16 → Hierarchical: 'Migrating from "Pack16" to any other format is not supported.'
    - Pack16 → Flat: 'Migrating from "Pack16" to any other format is not supported.'
- Disable the field when `project.readonly`.
- For now, the Hierarchical → Pack16 transition just stores the intent; the actual
  migration task is wired up in Increment 6.

**Tests:**
- E2E: `test_preferences_dialog_shows_current_revision_storage_format`
  - Open preferences for v1, v2, v3 projects
  - Verify dropdown shows "Flat", "Hierarchical", "Pack16" respectively
- E2E: `test_preferences_dialog_prevents_unsupported_format_transitions`
  - Attempt each invalid transition
  - Verify appropriate error dialog appears with correct message
- E2E: `test_preferences_dialog_disables_format_dropdown_for_readonly_project`
  - Open readonly project
  - Verify dropdown is disabled

**Key files:**
- `src/crystal/browser/preferences.py`
- `src/crystal/tests/test_preferences.py` (or new test file)

**Estimated time:** ~2-3 hours

---

## Increment 6: Migration task — core logic

**Goal:** `MigrateRevisionsToPack16FormatTask` packs all existing hierarchical revisions.

**Work:**
- Create `MigrateRevisionsToPack16FormatTask` (leaf task) in `task.py` or a new module.
- The task:
  1. Waits until it is the only top-level task (sits idle during initial timeslices).
  2. Puts the project into readonly mode (with `_cr_readonly_ok` bypass for itself).
  3. Triggers immediate `Project.hibernate_tasks` to persist that migration has started.
  4. Sets `major_version = 3` if not already.
  5. Scans revision IDs in increments of 16, writing packs for each group.
  6. Skips revisions that have been deleted or lack bodies.
  7. Reports progress: "Migrating revision storage format — X of N packs — HH:MM:SS remaining".
  8. On completion, restores writable mode.
  9. Triggers immediate `Project.hibernate_tasks` (pretending task is complete) to persist completion.
- N (total pack count) calculated as `floor(highest_revision_id / 16) + 1`.
- Wire up the confirmation dialog flow from Preferences (Increment 5): when user selects
  Hierarchical → Pack16 and presses OK, show warning dialog ("may take several hours"),
  then create and schedule the migration task.

**Tests:**
- E2E: `test_given_project_with_major_version_2_when_migrate_to_pack16_then_creates_all_packs_and_upgrades_to_major_version_3`
  - Create v2 project with ~50 revisions
  - Trigger migration via preferences
  - Verify all packs are created
  - Verify project is v3
  - Verify all revisions still readable via `open()`
- E2E: `test_when_migration_in_progress_then_project_is_readonly`
  - Create v2 project with revisions
  - Start migration
  - Verify attempts to download fail with `ProjectReadOnlyError`
  - Wait for migration to complete
  - Verify downloads work again
- E2E: `test_when_migrate_to_pack16_then_task_tree_shows_progress`
  - Start migration
  - Verify task appears in task tree with progress updates

**Key files:**
- New: `src/crystal/model/migrate_to_pack16.py` (or add to existing migration code)
- `src/crystal/task.py` (new task class, or import from new module)
- `src/crystal/browser/preferences.py` (wire up confirmation + task creation)
- `src/crystal/model/project.py` (readonly mode support for migration)
- `src/crystal/tests/model/test_pack16.py`

**Estimated time:** ~3 hours

---

## Increment 7: Migration robustness — hibernate, resume, error handling

**Goal:** Migration survives crashes, project close/reopen, and I/O errors gracefully.

**Work:**
- Add `MigrateRevisionsToPack16FormatTask` to `hibernate_tasks` / `unhibernate_tasks`
  so that closing the project during migration persists the task's existence and
  reopening the project restores it.
- On reopen of a v3 project that still has unmigrated revisions (detected by checking
  for missing pack files during the scan in `_load`), automatically schedule a new
  migration task.
- Handle I/O errors during migration: if a hierarchical file can't be read after
  opening, skip it from the pack, leave the original file in place, warn to stderr.
- Ensure temp pack files in `tmp/` are cleaned up on project open (existing tmp
  cleanup logic may already handle this; verify).

**Tests:**
- E2E: `test_given_migration_in_progress_when_close_and_reopen_project_then_migration_resumes_and_completes`
  - Create v2 project with 50+ revisions
  - Start migration
  - Close project mid-migration (may need to pause or use test hook)
  - Reopen project
  - Verify migration task is restored and completes
- E2E: `test_given_corrupt_revision_file_when_migrate_to_pack16_then_skips_file_and_warns`
  - Create v2 project with revisions
  - Corrupt one revision file (truncate or write garbage)
  - Start migration
  - Verify migration completes
  - Verify corrupt file is skipped from pack and left in place
  - Verify warning is emitted to stderr (may need to capture stderr in test)
- E2E: `test_given_interrupted_migration_when_reopen_then_cleans_up_temp_pack_files`
  - Simulate crash during migration (manually create temp pack file in tmp/)
  - Reopen project
  - Verify temp files are removed

**Key files:**
- `src/crystal/model/project.py` (hibernate/unhibernate, project open logic, tmp cleanup)
- `src/crystal/model/migrate_to_pack16.py`
- `src/crystal/tests/model/test_pack16.py`

**Estimated time:** ~3 hours

---

## Increment 8: Polish, edge cases, and release notes

**Goal:** Ensure all edge cases are covered, comprehensive test coverage, and documentation.

**Work:**
- Handle edge case: project with revision ID 0 (shouldn't exist by SQLite auto-increment,
  but be defensive in pack boundary calculations).
- Handle edge case: v3 project opened by older Crystal version → verify
  `ProjectTooNewError` is raised with a clear message. (Should already work, but test it.)
- Handle edge case: empty project (no revisions) — migration is a no-op.
- Handle edge case: project where all revisions are error-only (no bodies) — migration
  produces no pack files.
- Review all `body_filepath` usages across the codebase and verify they work for v3.
  (Search for `_body_filepath`, `_body_filepath_with`, `_REVISIONS_DIRNAME` usage.)
- Add release notes entry to `RELEASE_NOTES.md` in the "main" branch section.
- Final pass through all tests; add any missing coverage.

**Tests:**
- E2E: `test_given_project_with_major_version_3_when_opened_by_older_crystal_then_raises_project_too_new_error`
  - Create v3 project
  - Temporarily set `Project._LATEST_SUPPORTED_MAJOR_VERSION = 2`
  - Attempt to open project
  - Verify `ProjectTooNewError` is raised
- E2E: `test_given_empty_project_when_migrate_to_pack16_then_migration_completes_immediately`
- E2E: `test_given_project_with_only_error_revisions_when_migrate_to_pack16_then_creates_no_pack_files`
- Run full test suite (`crystal test` and `pytest`) to verify no regressions

**Key files:**
- Various (audit pass)
- `RELEASE_NOTES.md`
- `src/crystal/tests/model/test_pack16.py`

**Estimated time:** ~2 hours

---

## Increment 9: Post-branch fixes

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
| 5 | Preferences UI — format dropdown | 2-3h | — |
| 6 | Migration task — core logic | 3h | 1, 2, 3, 5 |
| 7 | Migration robustness — hibernate, resume, errors | 3h | 6 |
| 8 | Polish, edge cases, and release notes | 2h | all |
| | **Total** | **~20-21h** | |

**Recommended order:** 1 → 2 → 3 → 4 → 5 → 6 → 7 → 8

Each increment builds working, testable functionality using E2E tests.
Early increments (1-4) can use `project._set_major_version(3, project._db)` directly in tests before the UI is ready.
