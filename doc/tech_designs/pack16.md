# Pack16

Currently the "revisions" directory of a latest-version (`major_version == 2`)
Crystal project looks like:

```
xkcd.crystalproj
├── ...
├── revisions
│   ├── 000
│   |   ├── 000
│   |   |   ├── 000
│   |   |   |   ├── 000
│   |   |   |   |   ├── 001
│   |   |   |   |   ├── 002
│   |   |   |   |   ├── 003
│   |   |   |   |   ├── 004
│   |   |   |   |   ├── 005
│   |   |   |   |   ├── 006
│   |   |   |   |   ├── 007
│   |   |   |   |   ├── 008
│   |   |   |   |   ├── 009
│   |   |   |   |   ├── 00a
│   |   |   |   |   ├── 00b
│   |   |   |   |   ├── 00c
│   |   |   |   |   ├── 00d
│   |   |   |   |   ├── 00e
│   |   |   |   |   ├── 00f
│   |   |   |   |   ├── 010
|   |   |   |   |   ├── ...
|   |   |   |   |   └── fff
|   |   |   |   ├── 001
│   |   |   |   |   ├── 000
│   |   |   |   |   ├── 001
|   |   |   |   |   ├── ...
|   |   |   |   |   └── fff
|   |   |   |   ├── 002
|   |   |   |   |   └── ...
|   |   |   |   ├── ...
|   |   |   |   |   └── ...
|   |   |   |   └── fff
|   |   |   |       └── ...
|   |   |   └── ...
|   |   └── ...
|   └── ...
├── revisions.inprogress -- Transient; Exists only while migrating from major version 1 to 2
|   └── ...
└── ...
```

In this document:
- I will call the `major_version == 2` format "Hierarchical".
- I will call the `major_version == 1` format "Flat".

I want to give the user the option to choose an alternate revision storage format, "Pack16".

The Pack16 format bundles groups of 16 revisions together into a (uncompressed) .zip file.
It is helpful for increasing the average file size in the revisions directory from 
about 100 KB to about 1.5 MB, which is significantly more efficient to store in
storage systems that have a large minimum object size. In particular AWS S3 Glacier
has a minimum billable object size of 128 KB.

Pack16 looks like:

```
xkcd.crystalproj
├── ...
├── revisions
│   ├── 000
│   |   ├── 000
│   |   |   ├── 000
│   |   |   |   ├── 000
│   |   |   |   |   ├── 00_.zip
│   |   |   |   |   |   ├── 001
│   |   |   |   |   |   ├── 002
│   |   |   |   |   |   ├── ...
│   |   |   |   |   |   └── 00f
│   |   |   |   |   ├── 01_.zip
│   |   |   |   |   |   └── ...
|   |   |   |   |   ├── ...
│   |   |   |   |   |   └── ...
|   |   |   |   |   └── ff_.zip
│   |   |   |   |       └── ...
|   |   |   |   ├── 001
|   |   |   |   |   └── ...
|   |   |   |   ├── 002
|   |   |   |   |   └── ...
|   |   |   |   ├── ...
|   |   |   |   |   └── ...
|   |   |   |   └── fff
|   |   |   |       └── ...
|   |   |   └── ...
|   |   └── ...
|   └── ...
└── ...
```

The maximum number of files per leaf directory is 16^2 == 2^8 == 256.

The maximum number of subdirectories per non-leaf directory is still 16^3 == 2^12 == 4,096.

Detail:
- During delete operations on a Pack16 project, when a revision is removed from
  a pack file that is currently open for reading, Crystal uses a rename-aside
  strategy to safely replace the pack file. The pack file (e.g., `01_.zip`) is
  temporarily moved to `01_.zip.replacing` while the new pack file is written
  into place. It is possible that Crystal may crash such that `01_.zip.replacing`
  is left on disk but the new `01_.zip` may or may not have been moved into place.
    - If `01_.zip.replacing` exists but `01_.zip` does not exist,
      Crystal will repair the pack file - by moving `.replacing` back to the
      original filename - the next time a revision in that pack is read.
    - If both `01_.zip` and `01_.zip.replacing` exist (cleanup after successful
      replacement didn't complete), Crystal will delete the orphaned
      `01_.zip.replacing` the next time it performs a delete operation on
      that same pack file.
    - Orphaned `.replacing` files are harmless (they contain old data that is
      superseded by the current pack file) but do waste disk space until cleaned up.

## Major Version

A project using the Pack16 revision format won't be readable by older versions
of Crystal that read up to `major_version == 2`. Therefore use of Pack16 implies
using a higher major version number (i.e. `3`). Conversely, the `major_version == 3`
format can be referred to in shorthand as "Pack16".

Older versions of Crystal will refuse to open a `major_version == 3` project.

## Operation: Write

Consider the simple situation where an empty project - containing no revisions - 
has revisions written to it, in Pack16 format.

Revisions are always downloaded in increasing order: 1, 2, 3, etc because they 
are numbered using an auto-increment database ID.
(SQLite starts auto-increment IDs at 1, not 0.)

The first revisions - excluding the missing revision 0 - are written to files
001, ..., 00e in the same way that Hierarchical does.

The next revision (with `id == 16*1 - 1`) is also written to file (`00f`)
but is followed by a packing operation: Revision files 000...00f
(with ids `16*0` to `16*1 - 1`) are written to a `00_.zip` file in the project's
"tmp" directory and then moved into place in the project's "revisions" directory.
The original individual revision files 000...00f are then deleted.

Details: The packing operation performs these steps atomically:
- Write the pack file to "tmp" directory
- fsync the pack file to flush its contents to disk
- Move/flush the pack file to "revisions" directory, using `rename_and_flush`,
  which uses either fsync or MOVEFILE_WRITE_THROUGH depending on OS
- Delete the original individual Hierarchical files
- No fsync follows the deletions (losing those deletes is acceptable)

The next revision (`id == 16*1`) is again downloaded as a single file (`010`),
same as the next several files. Then after revision `id == 16*2 - 1` is written,
another .zip file (`01_.zip`) is packed and the individual revision files discarded.
The pattern repeats.

Note: Pack files are placed in the innermost leaf directory of the Hierarchical
structure. For example, revisions at paths 000/000/001/000 through 000/000/001/00f
are combined into a pack file at 000/000/001/00_.zip.

Revisions that don't complete a pack of 16 remain as individual files.
For example, if a project has 243 revisions (IDs 1-243), packs 00_.zip through
0e_.zip would exist (covering IDs 0x001-0x0ef, 1-239), while revisions 240-243 would remain
as individual files 0f0, 0f1, 0f2, 0f3.

Detail: Some revisions do not have a revision body that is stored to a file,
such as error-only revisions. In that situation, the packing operation happens 
after the revision file would otherwise have been written, 
after the corresponding revision database row is written.

Detail: Sometimes during a packing operation there may be zero revision files 
to pack, because none of the revisions in range had revision file bodies.
In this situation no zip file is written at all.

Detail: Pack files contain entries with 3-digit hex names matching the Hierarchical
format (e.g., "001", "002", etc.). If a pack file is extracted in place, it should
put the extracted files exactly where they were in the Hierarchical format.

Detail: When opening a Pack16 project, check if the highest-numbered pack is incomplete.
If so, initiate a packing operation for those revisions. This handles recovery from
disk-full errors that may have prevented packing during the original write.
(Determine this by looking at the highest revision ID in the database and checking
if a corresponding pack file exists.)

Detail:
- .zip files are always written with ZIP64 extensions enabled. 
- Each zip entry is written with no compression to increase data recoverability 
  if a bad block appears in the middle of the zip file.

## Operation: Read

Given a revision id R, identify the path where its corresponding pack .zip file 
should be. Try to open the pack file. If pack file does not exist, check if a
`.replacing` file exists (indicating a crash during delete). If found, repair by
moving it back to the original pack filename, then retry the open. If pack file
(after repair attempt) does not exist or the revision is not found in it, then
try to open the revision's Hierarchical file instead. If that also fails then
report that the revision's body file is missing.

Detail: ResourceRevision.open() uses zipfile.ZipFile.open() to return a read-only
file-like object directly from the zip file, without extracting to a temporary location.

Detail: Each read operation opens and closes the zip file independently.
No caching of zip file handles is performed in the initial implementation.

Detail: Reading from pack files requires additional disk seeks to read the zip's
central directory and position to the file data. File data itself is stored
uncompressed, so data reads perform the same as Hierarchical format. The additional
seeks have negligible impact on SSDs but may increase time-to-first-byte on HDDs.

## Operation: Migrate (from Hierarchical)

Migration to Pack16 format is only allowed directly from Hierarchical format.
If the user desires to migrate from Flat format to Pack16, they must migrate
to Hierarchical first.

Unlike the Flat → Hierarchical migration, which Crystal actively recommends
when opening a v1 project, the Hierarchical → Pack16 migration is entirely
voluntary. Crystal will happily open a v2 project without prompting the user
to upgrade.

### Preferences UI

The Preferences dialog displays the project's current revision storage format
as a read-only label, with a checkbox to initiate migration when applicable:

- **Flat project (`major_version == 1`):**
  `Revision Storage Format:  Flat     [ ] Migrate to Hierarchical`
    - Effect: Signal that a major_version 1 -> 2 migration is "in-progress"
      by creating an empty "revisions.inprogress" directory inside the
      project directory. (This is how this migration type has always
      been signaled in the past.)
    - Project is closed and reopened.
      Migration 1 -> 2 starts/resumes automatically.

- **Hierarchical project (`major_version == 2`):**
  `Revision Storage Format:  Hierarchical   [ ] Migrate to Pack16`

- **Pack16 project (`major_version == 3`):**
  `Revision Storage Format:  Pack16`
  No migration checkbox is shown (no further migrations are available).

The checkbox is unchecked by default. Checking it and pressing "OK" to save
triggers the migration flow described below. The checkbox acts as a deferred
action, consistent with the Preferences dialog's save-on-OK pattern.

### Migration flow

Migration is initiated explicitly by the user, in the following sequence:

- User checks "Migrate to Pack16" in Preferences and presses "OK".
- A warning dialog appears: migration "may take several hours to complete"
  and the project will not be usable while the migration is in progress.
    - User confirms with "Migrate" button. Or cancels with "Cancel" button,
      which leaves the Preferences dialog open.
- On confirmation:
    1. Save a migration-in-progress marker to the project. Specifically,
       store the old major version in a `major_version_old` property and
       set `major_version` to `3`.
        - Setting the higher major version in the 2 -> 3 sequence in
          the `major_version` property (rather than in some other property
          like `major_version_new`) will prevent older versions of
          Crystal that do not understand `major_version >= 3` from
          opening the project while it is being migrated.
    2. Close the project fully using the usual procedure, including
       hibernating any in-progress tasks.
    3. Reopen the project. On open, the project detects the
       migration-in-progress marker (`major_version_old` is present) and
       shows a cancelable modal progress dialog to perform the migration.
    4. If the user cancels the progress dialog, the project is closed.
       The migration-in-progress marker remains, so the next open will
       resume the migration.
    5. After the progress dialog completes, remove the `major_version_old`
       marker. The project opens normally as writable at `major_version == 3`.

This flow is intentionally similar to the existing Flat → Hierarchical
migration, which also closes the project and performs migration during
a modal progress dialog at reopen time.

Detail: On step 3, when the project reopens and detects the migration-in-progress
marker, it will show a confirmation prompt before starting the migration
(reusing the existing `will_upgrade_revisions` callback in
`OpenProjectProgressListener`). This means the user sees two prompts on
initial migration: one in Preferences to confirm intent, and one on reopen
to continue. This is a known awkwardness accepted in the initial implementation
to minimize code changes to the existing v1→v2 migration path. A future
improvement could skip the reopen prompt when migration has not yet done
any work.

### Migration steps (performed inside the progress dialog)

- Assert that `major_version == 3` and `major_version_old == 2`.
- Identify the first unmigrated pack. Linear scan through revision IDs
  starting at `1`, progressing through `16*1`, `16*2`, etc. Look for a
  missing .zip file in the "revisions" directory, where the associated
  range of revision IDs in the project database has at least one revision
  expecting a body.
- Starting from the first unmigrated pack, write packs of revisions to .zip
  files using the same logic as "Operation: Write", processing all packs until
  the full range of revision IDs have been scanned. Revisions that have been
  deleted or lack bodies are skipped. Incomplete packs (those with fewer than 16
  revisions) remain as individual files.
- Report progress in terms of revisions processed (not packs), reusing the
  existing `{will_upgrade_revisions, upgrading_revision, did_upgrade_revisions}`
  callbacks in `OpenProjectProgressListener`. This avoids changing the model→UI
  interface. The lower-level code processes in units of packs, but the progress
  callbacks are invoked per-revision (or per-pack, advancing the count by 16).
- On completion, remove the `major_version_old` marker.

### Migration details

Detail: During migration, only enough additional disk space is needed to write the
largest individual pack file (typically a few MB). Individual Hierarchical files
are deleted only after their pack file is fsync'ed to disk.

Detail: If the migration process crashes after creating a pack file in "tmp" but
before moving it to "revisions", the temporary pack file will be cleaned up when
the project is reopened.

Detail: If an I/O error occurs while reading a Hierarchical file during migration
(after successfully opening it), that file will be skipped from the pack file.
The presumed-corrupted Hierarchical file will NOT be deleted after writing the
pack file. A warning will be printed to stderr (visible to shell & developer
users but not UI users).

Detail: During migration, the project is fully closed — no reads or writes are
possible. This is a simpler model than allowing reads during migration, at the
cost of blocking project use until migration completes. For large projects
(1–5 TB), migration may take many hours. The cancelable progress dialog allows
the user to stop and resume later; the read path (Operation: Read) handles the
mixed pack+loose state correctly, so a partially-migrated project that is
force-opened would still be readable.

## Operation: Delete

ResourceRevision exposes a delete() operation. It is rarely used, so its 
implementation doesn't need to be especially efficient.

Look for a corresponding Pack16 zip file. If found then rewrite the zip file 
with the revision removed in the project's "tmp" directory. Then move the new 
zip file into place, in the "revisions" directory, replacing the old zip file.
If the old zip file is currently open for reading (on Windows), a rename-aside
strategy is used: the old file is renamed to `.replacing` suffix, the new file
is moved into place, then the `.replacing` file is deleted. This ensures no data
loss if the process crashes mid-operation.

If no Pack16 zip file is found, look for a Hierarchical file instead.

If no Hierarchical file found, report revision body as missing.

Detail: To avoid problems with concurrent deletes and pack operations done by writes, 
the delete operation should be done inside a (new kind of) Task
(DeleteResourceRevisionTask), so that writes done by other Tasks can't happen 
at the same time. (Only one task may write to the project's revision bodies during
a timeslice of the scheduler thread.) Performing a delete inside of a Task will
require changing the current ResourceRevision.delete() API to return a Future 
rather than performing the delete synchronously.

## Operation: Alter Metadata

Revision metadata (stored in the database) can be altered via 
ResourceRevision._alter_metadata, but this does not require modifying the 
pack file since it does not affect the revision body.

## Summary

**Core Design:**
- Packs contain 16 consecutive revision IDs based on hex boundaries (XX0-XXf)
- Packs are created incrementally during writes, not retroactively
- Mixed format (pack + loose files) is a valid state during migration and after incomplete packs

**Robustness:**
- fsync operations ensure durability before deleting source files
- Project is fully closed during migration (no concurrent access)
- Corrupt file handling during migration is graceful (skip and warn)
- Crash recovery cleans up temp files on project reopen
- Incomplete packs at project open trigger automatic packing

**Performance Trade-offs:**
- No zip handle caching (simplicity over performance)
- Additional seeks when reading from packs (acceptable on SSDs)
- Minimal extra disk space during migration (one pack at a time)

**Migration Safety:**
- Can only migrate from Hierarchical → Pack16
- Cannot rollback after migration starts
- Progress tracking based on pack count
- Cancelable modal dialog; migration resumes on next project open if interrupted
- Migration state persisted via `major_version_old` marker
