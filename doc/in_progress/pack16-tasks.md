# Pack16 Implementation Breakdown

Reference: `doc/tech_designs/pack16.md`

---

## Increment 1: Pack16 path computation and zip utilities

**Goal:** Build the low-level foundation that all other increments depend on.

**Work:**
- Add a `_body_pack_filepath_with()` static method to `ResourceRevision` that computes
  the pack zip file path for a given revision ID (e.g., revision `0x01a` → `000/000/000/001/01_.zip`).
- Add a helper that computes the entry name within a pack zip for a given revision ID
  (e.g., revision `0x01a` → `'01a'`).
- Add utility functions (likely in a new module like `crystal/model/pack16.py`):
  - `create_pack_file(revision_files: dict[str, str], dest_path: str, tmp_dir: str)`:
    Create an uncompressed ZIP64 file from a mapping of `{entry_name: source_filepath}`.
    Write to `tmp_dir` first, then `rename_and_flush` to `dest_path`. fsync the temp file
    before moving.
  - `read_pack_entry(pack_path: str, entry_name: str) -> BinaryIO`:
    Open a specific entry from a pack zip, returning a file-like object via
    `zipfile.ZipFile.open()`.
  - `rewrite_pack_without_entry(pack_path: str, entry_name: str, tmp_dir: str)`:
    Rewrite a pack zip file with one entry removed. Write to tmp, then move into place.
- Update `_LATEST_SUPPORTED_MAJOR_VERSION` to `3` and make `_body_filepath_with()` work
  for `major_version == 3` (same hierarchical paths as version 2).

**Tests:**
- Unit tests (`tests/`) for path computation: various revision IDs → expected pack paths
  and entry names.
    💬 Agreed: Valuable to unit test.
- Unit tests for `create_pack_file`, `read_pack_entry`, `rewrite_pack_without_entry` using
  temp directories and synthetic files.
    ✖️ Insufficiently distinct from corresponding E2E tests. Suggest omit.

**Key files:**
- `src/crystal/model/resource_revision.py` (modify `_body_filepath_with`)
- New: `src/crystal/model/pack16.py` (or similar)
- `src/crystal/model/project.py` (update `_LATEST_SUPPORTED_MAJOR_VERSION`)
- New: `tests/model/test_pack16.py`

**Estimated time:** ~2 hours

---

## Increment 2: Read revisions from pack files

**Goal:** `ResourceRevision.open()` and `body_size` can read from pack zip files.

**Work:**
- Modify `ResourceRevision.open()`: for `major_version >= 3`, try the pack file first
  (via `read_pack_entry`). If the pack file doesn't exist or the entry isn't in it,
  fall back to the hierarchical file. If neither exists, raise `RevisionBodyMissingError`.
- Similarly modify `ResourceRevision.body_size` to support reading size from pack entries.
- The returned file-like object from `zipfile.ZipFile.open()` needs care: the `ZipFile`
  must stay open while the entry stream is being read. Consider wrapping it so that
  closing the entry stream also closes the `ZipFile`.

**Tests:**
- Unit tests: manually create a pack zip in a temp project directory, then verify
  `open()` reads the correct content.
    = test_given_resource_revision_in_pack_file_then_open_reads_correct_revision_content
- Unit tests: verify fallback to hierarchical file when pack doesn't exist.
    = test_given_resource_revision_in_individual_file_then_open_reads_correct_revision_content
- Unit tests: verify `RevisionBodyMissingError` when neither pack nor hierarchical exists.
    = test_given_resource_revision_body_expected_but_no_file_exists_then_open_raises_revision_body_missing

**Key files:**
- `src/crystal/model/resource_revision.py` (modify `open`, `body_size`)
- `tests/model/test_pack16.py`

**Estimated time:** ~2 hours

---

## Increment 3: Write revisions with packing

**Goal:** During download, after every 16th revision, pack the group into a zip.

**Work:**
- After a revision is successfully written in `_create_from_stream()`, check whether
  this revision completes a group of 16 (i.e., `revision_id % 16 == 15`
  or, for the first group, `revision_id % 16 == 15` accounting for ID 0 being unused).
  More precisely: pack when `revision_id` is of the form `16*k - 1` for some k, which
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
- End-to-end test: create a v3 project, download >16 resources, verify pack files
  are created and individual files are removed.
    = test_given_project_in_pack16_format_when_create_multiple_of_16_resource_revision_then_creates_pack_file_if_at_least_one_revision_body_exists
        # Case 1 (subtest): 16th + 32nd revision has a body; 2 packs
        # Case 2 (subtest): 16th + 32nd revision has no body, rest have bodies; 2 packs
        # Case 3 (subtest): first 16 revisions have no body, next 16 revisions have body; 1 pack
        # Case 4 (subtest): first 16 revisions have body, next 16 revisions have no body; 1 pack
- End-to-end test: verify that revisions that don't complete a pack remain as
  individual files.
    = test_given_project_in_pack16_format_when_create_non_multiple_of_16_resource_revision_then_creates_individual_file
    
- Unit test: verify that a group with all error-only revisions produces no pack file.
    = ✖️ Replaced by case 3 & 4 above

**Key files:**
- `src/crystal/model/resource_revision.py` (modify `_create_from_stream`)
- `src/crystal/tests/model/test_pack16.py` (new e2e test file)

**Estimated time:** ~3 hours

---

## Increment 4: Recovery — complete incomplete packs on project open

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

**Tests:**
- End-to-end test: create a v3 project with 20 revisions, manually delete the
  last pack file and scatter the individual files back, reopen, verify pack is recreated.
    - test_given_individual_files_exist_for_last_missing_complete_pack_file_when_project_opened_then_pack_file_created_and_individual_files_deleted
- Edge case: highest revision doesn't complete a full pack of 16 — no recovery needed.
    - test_given_individual_files_exist_for_last_missing_incomplete_pack_file_when_project_opened_then_pack_file_not_created_and_individual_files_retained

**Key files:**
- `src/crystal/model/project.py` (modify `_load` or related)
- `src/crystal/model/resource_revision.py` or `src/crystal/model/pack16.py`
- `src/crystal/tests/model/test_pack16.py`

**Estimated time:** ~2 hours

---

## Increment 5: Delete revisions from pack files

**Goal:** `ResourceRevision.delete()` works correctly when the revision is inside a pack.

**Work:**
- Modify `delete()`: for `major_version >= 3`, check if the revision is in a pack file.
  If so, rewrite the pack without that entry (via `rewrite_pack_without_entry`).
  If not, fall back to deleting the hierarchical file.
- Create `DeleteResourceRevisionTask` — a new leaf Task type that performs the deletion
  on the scheduler thread, to avoid concurrent access to pack files during writes.
- Change the public `delete()` API to return a `Future` so callers can await completion.
  Update all existing callers of `delete()` to handle the new async API.

**Tests:**
- Unit test: delete a revision from a pack, verify the pack is rewritten without it.
    💬 E2E test: test_given_nonlast_resource_revision_in_pack_file_when_deleted_then_pack_file_rewritten_without_it
        # ...and other revision in pack file is still readable
- Unit test: delete the last revision from a pack, verify the pack file is removed entirely.
    💬 E2E test: test_given_last_resource_revision_in_pack_file_when_deleted_then_pack_file_deleted
- End-to-end test: delete a revision from a v3 project, verify it's gone and other
  revisions in the same pack are still accessible.
    💬 Moved to above test as an extension: `# ...and other revision in pack file is still readable`
- Test that existing delete behavior (non-pack) still works.
    ✖️ Out of scope. Don't rewrite tests covering Hierarichal scenarios. Hopefully those tests already exist.

**Key files:**
- `src/crystal/model/resource_revision.py` (modify `delete`)
- `src/crystal/task.py` (new `DeleteResourceRevisionTask`)
- Callers of `delete()` — search for usages
- `src/crystal/tests/model/test_pack16.py`

**Estimated time:** ~3 hours

---

## Increment 6: Preferences UI — Revision Storage Format dropdown

**Goal:** User can see and change the project's revision storage format in Preferences.

**Work:**
- Add a "Revision Storage Format" dropdown to the Project section of PreferencesDialog
  with options: "Flat", "Hierarchical", "Pack16".
- Display the current format based on `project.major_version` (1=Flat, 2=Hierarchical,
  3=Pack16).
- Validate transitions on OK:
  - Flat → Hierarchical: trigger existing migration flow.
  - Hierarchical → Pack16: allowed (will trigger migration in a later increment).
  - All other transitions: show error dialog with appropriate message per tech design.
- Disable the field when `project.readonly`.
- For now, the Hierarchical → Pack16 transition just stores the intent; the actual
  migration task is wired up in Increment 7.

**Tests:**
- End-to-end test: open preferences, verify dropdown shows correct current format.
- End-to-end test: attempt invalid transitions (Hierarchical → Flat, Flat → Pack16,
  Pack16 → anything), verify error dialogs appear.
- End-to-end test: verify dropdown is disabled for readonly projects.

**Key files:**
- `src/crystal/browser/preferences.py`
- `src/crystal/tests/test_preferences.py` (or new test file)

**Estimated time:** ~2-3 hours

---

## Increment 7: Migration task — core logic

**Goal:** `MigrateRevisionsToPack16FormatTask` packs all existing hierarchical revisions.

**Work:**
- Create `MigrateRevisionsToPack16FormatTask` (leaf task) in `task.py` or a new module.
- The task:
  1. Waits until it is the only top-level task (sits idle during initial timeslices).
  2. Puts the project into readonly mode (with `_cr_readonly_ok` bypass for itself).
  3. Sets `major_version = 3` if not already.
  4. Scans revision IDs in increments of 16, writing packs for each group.
  5. Skips revisions that have been deleted or lack bodies.
  6. Reports progress: "Migrating revision storage format — X of N packs — HH:MM:SS remaining".
  7. On completion, restores writable mode.
- Wire up the confirmation dialog flow from Preferences (Increment 6): when user selects
  Hierarchical → Pack16 and presses OK, show warning dialog, then create and schedule
  the migration task.
- Trigger `hibernate_tasks` before and after migration per tech design.

**Tests:**
- End-to-end test: create a v2 project with ~50 revisions, trigger migration via
  preferences, verify all packs are created and project is v3.
- End-to-end test: verify project is readonly during migration (can't download).
- End-to-end test: verify migration progress updates appear in task tree.

**Key files:**
- New: `src/crystal/model/migrate_to_pack16.py` (or add to existing migration code)
- `src/crystal/task.py` (new task class)
- `src/crystal/browser/preferences.py` (wire up confirmation + task creation)
- `src/crystal/model/project.py` (readonly mode support for migration)
- `src/crystal/tests/model/test_pack16.py`

**Estimated time:** ~3 hours

---

## Increment 8: Migration robustness — hibernate, resume, error handling

**Goal:** Migration survives crashes, project close/reopen, and I/O errors gracefully.

**Work:**
- Add `MigrateRevisionsToPack16FormatTask` to `hibernate_tasks` / `unhibernate_tasks`
  so that closing the project during migration persists the task's existence and
  reopening the project restores it.
- On reopen of a v3 project that still has unmigrated revisions (detected by checking
  for missing pack files), automatically schedule a new migration task.
- Handle I/O errors during migration: if a hierarchical file can't be read after
  opening, skip it from the pack, leave the original file in place, warn to stderr.
- Ensure temp pack files in `tmp/` are cleaned up on project open (existing tmp
  cleanup logic may already handle this).

**Tests:**
- End-to-end test: start migration, close project mid-migration, reopen, verify
  migration resumes and completes.
- End-to-end test: simulate a corrupt revision file during migration, verify it's
  skipped and warning is emitted.
- End-to-end test: verify temp files are cleaned up after interrupted migration.

**Key files:**
- `src/crystal/model/project.py` (hibernate/unhibernate, project open logic)
- `src/crystal/model/migrate_to_pack16.py`
- `src/crystal/tests/model/test_pack16.py`

**Estimated time:** ~3 hours

---

## Increment 9: Polish, edge cases, and release notes

**Goal:** Ensure all edge cases are covered, comprehensive test coverage, and documentation.

**Work:**
- Handle edge case: project with revision ID 0 (shouldn't exist, but be defensive).
- Handle edge case: v3 project opened by older Crystal version → verify
  `ProjectTooNewError` is raised with a clear message.
- Handle edge case: empty project (no revisions) — migration is a no-op.
- Handle edge case: project where all revisions are error-only (no bodies) — migration
  produces no pack files.
- Review all `body_filepath` usages across the codebase and verify they work for v3.
  (Search for `_body_filepath`, `_body_filepath_with`, `_REVISIONS_DIRNAME` usage.)
- Add release notes entry to `RELEASE_NOTES.md`.
- Final pass through all tests; add any missing coverage.

**Tests:**
- Additional edge-case tests as described above.
- Run full test suite to verify no regressions.

**Key files:**
- Various (audit pass)
- `RELEASE_NOTES.md`
- `src/crystal/tests/model/test_pack16.py`

**Estimated time:** ~2 hours

---

## Summary

| # | Increment | Est. | Depends on |
|---|-----------|------|------------|
| 1 | Pack16 path computation and zip utilities | 2h | — |
| 2 | Read revisions from pack files | 2h | 1 |
| 3 | Write revisions with packing | 3h | 1, 2 |
| 4 | Recovery — complete incomplete packs on open | 2h | 1, 3 |
| 5 | Delete revisions from pack files | 3h | 1, 2 |
| 6 | Preferences UI — format dropdown | 2-3h | — |
| 7 | Migration task — core logic | 3h | 1, 2, 3, 6 |
| 8 | Migration robustness — hibernate, resume, errors | 3h | 7 |
| 9 | Polish, edge cases, and release notes | 2h | all |
| | **Total** | **~22-23h** | |

**Recommended order:** 1 → 2 → 3 → 4 → 5 → 6 → 7 → 8 → 9

Increments 5 and 6 have no dependency on each other and could be done in either order,
but doing 5 before 6 keeps the model-layer work grouped together before moving to UI.
