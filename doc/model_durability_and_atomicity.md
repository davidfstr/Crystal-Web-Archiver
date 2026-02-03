This file documents an audit of the model.py subsystem as of 2026-02-01.

## References

Key implementation classes/files:
- doc/crystalproj_project_format.md
    - Documents project format
- src/crystal/model.py
    - Implements all entities


## Durability and Atomicity

All model operations are expected to be durable and atomic,
unless otherwise documented.

Symbol key:
- ✅ = Safe
- 👌 = Acceptable
- ⚠️ = Problem

Model operations:

- Resource I/O:
    - Resource.__new__(), Resource._finish_init(), Resource._finish_save()
        - Write Resource to database row.
        - ✅ SAFE: Single transaction (INSERT + COMMIT) for writable projects.
        - ✅ DEFERRED SAVE: For readonly projects, resources are marked _UNSAVED_ID
          and saved later when project becomes writable (in Project._save_as_coro).
    - Resource.delete()
        - Deletes a Resource synchronously.
        - First deletes all ResourceRevision children (see ResourceRevision.delete()).
        - Then deletes Resource from database (DELETE + COMMIT).
        - ✅ SAFE: Each ResourceRevision deletion is atomic. Final Resource deletion is atomic.
        - 👌 ACCEPTABLE: If crash during multi-revision deletion, some revisions may be 
          deleted while others remain, leaving Resource in partial state.
          However the remaining revisions will be the most recent (and thus most
          important revisions). Additionally Resource.delete() can be safely retried 
          and may fully succeed after a retry.
            - It would be possible to make the entire ResourceRevision+Resource
              deletion operation atomic if it was revised to:
                1. delete the ResourceRevision+Resource rows in the database with a single transaction, then
                2. delete the corresponding ResourceRevision body files
              however the current implementation is simpler and considered
              good enough for now.
    - Resource.bulk_get_or_create(), Resource._bulk_create_resource_ids_for_urls()
        - Bulk creates Resources in database using executemany + single COMMIT.
        - ✅ SAFE: Single transaction for all resources.
        - ✅ EFFICIENT: Bulk insert is much faster than individual inserts.

- RootResource I/O:
    - RootResource.__new__()
        - Writes RootResource to database row atomically (INSERT + COMMIT).
        - ✅ SAFE: Single transaction. Readonly check before write.
    - RootResource.delete()
        - Deletes RootResource synchronously (DELETE + COMMIT).
        - Clears references from ResourceGroups that point to it.
        - ✅ SAFE: Single transaction with readonly check.
    - RootResource.name setter
        - Updates name (UPDATE + COMMIT).
        - ✅ SAFE: Single transaction with readonly check.

- ResourceRevision I/O:
    - DownloadResourceBodyTask,
      download_resource_revision,
      ResourceRevision.create_from_response,
      ResourceRevision._create_from_stream(⭐ bottleneck)
        - Writes ResourceRevisions (database row + revision body file) to disk.
        - 👌 **CONCURRENT WRITE PATTERN** in _create_from_stream():
            1. fg_call_later() schedules INSERT on foreground thread (async)
            2. Background thread downloads body to NamedTemporaryFile + fsync
            3. Waits for database INSERT to complete (properly synchronized)
            4. If both succeed: os.rename(temp_file, final_location) + fsync parent dir
            5. If body download fails but INSERT succeeded: Rollback with DELETE + COMMIT
        - 👌 **WINDOW OF INCONSISTENCY**:
            - Between database COMMIT and file rename completion, database row exists but file doesn't
            - Another thread trying to read would get RevisionBodyMissingError (triggers redownload)
            - This is acceptable: single-threaded download scheduler makes this unlikely
        - 👌 **ROLLBACK FAILURE RISK**:
            - If body write/rename fails, rollback DELETE is attempted
            - Rollback can fail in certain scenarios:
                - **Disk disconnect**: If disk disconnects during write, rollback DELETE immediately fails
                  (disk is no longer accessible)
                - **Disk full**: If disk fills during body write, rollback DELETE will also fail
                  (all subsequent I/O operations fail when disk is full)
            - If rollback fails: database row exists pointing to missing/incomplete body file
            - However this is **rare** because:
                - Disk disconnect is uncommon during normal operation
                - DownloadResourceBodyTask checks for ample free space before download
                  (min 5% of disk or 4 GiB, whichever is less)
            - Additionally, common types of rollback failures are **proactively repaired** when the project is reopened
        - ✅ **ERROR RECOVERY**:
            - **Proactive repair on project open** (_repair_incomplete_rollback_of_resource_revision_create):
                - Checks if last revision has missing body file
                - Verifies filesystem is accessible by testing 3 earlier revisions
                - If all 3 earlier revisions are readable, deletes the orphaned last revision
                - Handles edge cases: temporarily-unmounted filesystem, intermittent availability,
                  insufficient test revisions available
                - This proactively cleans up rollback failures before user encounters them
            - **Passive recovery on access**:
                - RevisionBodyMissingError triggers re-download when revision is accessed
                - test_disk_io_errors.py verifies this recovery path works
                - Missing body files are handled gracefully throughout codebase
    - ResourceRevision.delete()
        - Deletes a ResourceRevision synchronously.
        - First deletes database row (DELETE + COMMIT).
        - Then tries to delete body file (os.remove), ignores FileNotFoundError.
        - ✅ SAFE: Database row is deleted first, so revision is correctly gone from system's perspective.
        - ✅ SAFE: Tolerant of missing body file. Single transaction for database.
        - 👌 ACCEPTABLE: If crash after database DELETE but before body file deleted,
          an orphaned body file remains on disk. This wastes some space but doesn't
          affect project correctness.
    - ResourceRevision.open()
        - Opens a ResourceRevision's body for reading.
        - ✅ SAFE: Read-only operation. Raises RevisionBodyMissingError if missing.
    - ResourceRevision._alter_metadata()
        - Alters the metadata (but not body) of an existing ResourceRevision.
        - Used only in automated tests; not product code.
        - ✅ SAFE: Single transaction (UPDATE + COMMIT).

- ResourceGroup I/O:
    - ResourceGroup.__init__()
        - Writes ResourceGroup to database row (INSERT),
          updates source (UPDATE), then COMMITs change. 1 combined transaction.
        - ✅ SAFE: Single transaction with readonly check.
    - ResourceGroup.delete()
        - Deletes ResourceGroup synchronously (DELETE + COMMIT).
        - Clears references from other ResourceGroups that point to it,
          within the same single transaction.
        - ✅ SAFE: Single transaction with readonly check.
    - ResourceGroup.source setter, do_not_download setter, name setter
        - Updates properties (UPDATE + COMMIT).
        - ✅ SAFE: Single transaction with readonly check.

- Alias I/O:
    - Alias.__init__()
        - Writes Alias to database row (INSERT + COMMIT).
        - ✅ SAFE: Single transaction with readonly check.
        - Validates that source_url_prefix and target_url_prefix end in '/'.
    - Alias.delete()
        - Deletes Alias synchronously (DELETE + COMMIT).
        - ✅ SAFE: Single transaction with readonly check.
    - Alias.target_url_prefix setter, target_is_external setter
        - Updates properties (UPDATE + COMMIT).
        - ✅ SAFE: Single transaction with readonly check.
        - NOTE: source_url_prefix is read-only after creation.


## Migration I/O Analysis

Migrating a project from `major_version == 1` to `major_version == 2` should
be atomic, durable, and not "get stuck", since the Crystal UI currently does 
not allow opening a project that is in the middle of such a migration.

- Project._apply_migrations() - Major Version 1 → 2 Migration
    - Purpose: Migrate revisions from flat structure (revisions/1, revisions/2, ...)
      to hierarchical structure (revisions/000/000/000/000/001, ...).
    - ✅ **MIGRATION INTERRUPTION SAFETY**:
        - Creates revisions.inprogress directory before starting migration
        - Migrates revisions one-by-one using os.rename()
        - If cancelled/crashed: revisions.inprogress exists, migration resumes on next open
        - ✅ SAFE: Migration is resumable
    - ✅ **MIGRATION ATOMICITY & DURABILITY**:
        - Each revision file is moved with os.rename() (atomic on same filesystem)
        - On macOS/Linux:
            - Periodic fsyncs ensure directory updates are durable:
                - After each revision whose ID ends in 'fff' (every 4,096 revisions)
                - After the final revision
            - fsync() used on parent directory
            - ✅ SAFE: Periodic fsyncs provide good durability guarantees on most filesystems
            - ✅ SAFE: Up to ~4,096 revisions may be in intermediate state between fsyncs
            (still in old location or already in new location), but migration resumes
            correctly from either state - no files are lost
        - On Windows:
            - os.rename() is implemented by CPython via a call to MoveFileExW with flags 0.
                - In particular it does NOT use the MOVEFILE_WRITE_THROUGH (0x8) flag which
                  guarantees the function "does not return until the file is actually moved
                  on the disk."
            - The official documentation for MoveFileExW at
              https://learn.microsoft.com/en-us/windows/win32/api/winbase/nf-winbase-movefileexw
              does not document any mechanism to flush *multiple* rename operations
              to disk at the same time; it only provides a mechanism to flush
              *individual* rename operations.
            - ⚠️ RENAMES UNFLUSHED: Neither the MOVEFILE_WRITE_THROUGH flag nor any other mechanism
              is used by the migration process to ensure that renames are flushed to disk,
              since there appears to be no documented way to *efficiently* flush *multiple*
              renames to disk at once.
    - ✅ **MIGRATION COMMIT**:
        - After ALL revisions migrated:
            1. UPDATE major_version=2 + COMMIT in database
            2. os.rename(revisions, tmp/revisions) - atomic
            3. os.rename(revisions.inprogress, revisions) - atomic
            4. fsync parent of revisions, to persist the rename
        - ✅ SAFE: Database commit happens FIRST, making major_version the source of truth
        - ✅ RECOVERY: On open, if (major_version == 2 AND revisions.inprogress exists):
            - Migration commit was interrupted after database commit but before filesystem cleanup
            - Automatically resume steps 2-4 to complete filesystem operations
        - ✅ SAFE: Cannot get stuck in re-migration loop because once major_version=2,
          the v1→v2 migration is never attempted again
    - ✅ MAX_REVISION_ID CHECK:
        - Migration checks if max revision ID > Project._MAX_REVISION_ID before starting
        - Auto-vetoes migration if too many revisions (would fail with ProjectHasTooManyRevisionsError)
        - This prevents "getting stuck" in a bad migration state


## General I/O Observations

### Database Durability
- ✅ SQLite WAL Mode: Enabled for all writable projects (since v1.6.0b).
    - WAL provides better concurrency and crash recovery than default journal mode.
    - On clean close: WAL is checkpointed and journal_mode changed back to DELETE
      (for compatibility with read-only media).
- ✅ Crystal relies on SQLite's automatic durability guarantees.
    - SQLite in WAL mode only syncs WAL on commit (not main database file).
    - Under disk full, SQLite should handle gracefully (transaction will fail).
    - Under sudden termination, WAL should be replayed on next open (standard SQLite recovery).
    - Under disk I/O error (bad block), SQLite may return SQLITE_IOERR, which Crystal
      does not handle specially (will propagate as exception).
    - Under disk disconnect, SQLite may return SQLITE_IOERR or SQLITE_CANTOPEN.
      Crystal does not handle these specially.

### Error Recovery
- ✅ Resource.delete() is resilient to partial deletion state (uses list snapshot)
- ✅ ResourceRevision.delete() tolerates missing body files
- ✅ ResourceRevision.open() detects missing body files and can trigger re-download
- ✅ Migration can be cancelled and resumed
- ✅ Migration commit atomicity is ensured by committing database first, then filesystem
