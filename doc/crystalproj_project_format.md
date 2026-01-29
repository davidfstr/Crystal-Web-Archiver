# Crystal project format (.crystalproj)

A Crystal project is stored on disk in a specially-structured directory that
ends in the `.crystalproj` extension. It may also temporarily have the
`.crystalproj-partial` extension while it is being created by Crystal's "Save As" operation.

A project partially-copied by Crystal's "Save As" operation will temporarily
have a `.crystalproj-partial` extension.

A typical .crystalproj in the most-recent major version (`2`)
has the following **directory structure**:

```
xkcd.crystalproj
├── database.sqlite     -- ⭐ SQLite database that tracks project entities and metadata
├── database.sqlite-shm -- Transient; Exists only while project is opened in Crystal
├── database.sqlite-wal -- Transient; Exists only while project is opened in Crystal
├── revisions           -- ⭐ Contains the body of each ResourceRevision
│   └── 000
│       └── 000
│           └── 000
│               └── 000
│                   ├── 001
│                   ├── 002
│                   ├── 003
│                   ├── 004
│                   ├── 005
│                   ├── 006
│                   ├── 007
│                   ├── 008
│                   ├── 009
│                   ├── 00a
│                   ├── 00b
│                   ├── 00c
│                   ├── 00d
│                   ├── 00e
│                   ├── 00f
│                   ├── 010
|                   └── ...
├── revisions.inprogress -- Transient; Exists only while migrating from major version 1 to 2
|   └── ...
|   
|   [ADDITIONAL FILES]
├── .directory
├── desktop.ini
├── icons
│   └── docicon.ico
├── OPEN ME.crystalopen
├── README.txt
└── tmp
```

The `.crystalproj` directory will be marked as being **file-like** on operating 
systems that support it, such that double-clicking a `.crystalproj` will open
the Crystal app automatically rather than displaying the contents of the directory:
- On macOS the `.crystalproj` file extension is marked as LSTypeIsPackage = true.
    - See related code in: `setup/setup.py`
- On Windows the `.crystalproj` file extension is marked as a Directory Class
  and configured to open in the Crystal app. Note that open/save dialogs will
  still browse inside `.crystalproj` directories despite it being marked as
  a Directory Class.
    - See related code in: `setup/win-installer.iss`
- On Linux the `.crystalproj` file extension is given a custom icon but is
  not marked as file-like, due to lack of desktop environment support for that behavior.
    - See related code in: `install_to_linux_desktop_environment` at `src/crystal/install.py`
- For more information about the file-like behavior of Crystal projects,
  see the test names in:
    - `src/crystal/tests/test_icons.py`
    - `src/crystal/tests/test_install_to_desktop.py`
    - `src/crystal/tests/test_file_extension_visibility.py`

The database (`database.sqlite`) is locked by the Crystal process while the
project is open (via standard SQLite locking), preventing concurrent writes
from other processes.

The authoritative reference in code for how projects are structured/read/written
is `src/crystal/model.py`.


## Core Concepts

- **Resource**
    - A downloadable URL.
- **Root Resource**
    - A user-specified starting point for downloading (appears in the Entity Tree UI).
- **Resource Group**
    - Automatically groups resources matching a URL pattern.
    - Often linked to from a particular Root Resource or members of another Group,
      which may be recorded as the group's Source.
        - Groups with a Source defined support the Update Members and Download operations.
- **Resource Revision**
    - A specific downloaded version of a resource.
    - Resources can have multiple revisions over time.
    - Each resource with at least one revision designates one of those revisions
      as its Default Revision, which is the revision that will be displayed when
      the resource is served or exported.
- **Alias**
    - URL rewriting rules for treating different URLs as equivalent.

All of the above items are considered to be the **Entities** of a Project
and most are displayed in the Entity Tree UI.


## Major Version

Each Crystal project has a major version, stored as the `major_version` property
in the `project_property` table of the project's database (`database.sqlite`).

From the docstring of `Project.major_version`:

> Crystal will refuse to open a project with a later major version than
> it knows how to read, with a ProjectTooNewError.
> 
> Crystal will permit opening projects with a major version that is
> older than the latest supported major version, even without upgrading
> the project's version, because the project may be stored on a read-only
> volume such as a DVD, CD, or BluRay disc.

So far, different major versions differ only in how revision bodies
are stored in the project. See §"Revisions Format" for details.

Before v1.7.0b, projects had no explicit `major_version` defined -
effectively having `major_version == 1` - and did not enforce the prohibition
on opening projects with unrecognized (high) major versions.

### Migrations

Crystal will prompt the user whether to automatically migrate a project
to the most recent major version when opening it as writable. The user may
decline to upgrade and can still use any features that don't depend on the
later major version, including writing to the project.

If a migration is interrupted - by the user explicitly cancelling the project open,
I/O error, disk disconnection, or sudden process termination - it will be
resumed automatically when Crystal next attempts to open the project.

Once a migration to a later major version starts it can be temporarily but
not permanently cancelled. Crystal does not support downgrading a project
to an earlier major version.


## Database Schema

Every Crystal project contains a SQLite database (`database.sqlite`) which
describes all entities in the project. It currently has the following format:

```sql
-- Tables
CREATE TABLE project_property (  -- since v1.0.0a
    name text unique not null,   -- since v1.0.0a
    value text                   -- since v1.0.0a
);
CREATE TABLE resource (          -- since v1.0.0a
    id integer primary key,      -- since v1.0.0a
    url text unique not null     -- since v1.0.0a
);
CREATE TABLE root_resource (     -- since v1.0.0a
    id integer primary key,      -- since v1.0.0a
    name text not null,          -- since v1.0.0a
    resource_id integer unique not null,               -- since v1.0.0a
    foreign key (resource_id) references resource(id)  -- since v1.0.0a
);
CREATE TABLE resource_group (  -- since v1.0.0a
    id integer primary key,    -- since v1.0.0a
    name text not null,        -- since v1.0.0a
    url_pattern text not null, -- since v1.0.0a
    source_type text,          -- since v1.0.0a
    source_id integer,         -- since v1.0.0a
    do_not_download integer not null default 0  -- since v1.8.0b
);
CREATE TABLE resource_revision (   -- since v1.0.0a
    id integer primary key,        -- since v1.0.0a
    resource_id integer not null,  -- since v1.0.0a
    request_cookie text,           -- since v1.3.0b
    error text not null,           -- since v1.0.0a
    metadata text not null         -- since v1.0.0a
);
CREATE TABLE alias (                               -- since v2.2.0
    id integer primary key,                        -- since v2.2.0
    source_url_prefix text unique not null,        -- since v2.2.0
    target_url_prefix text not null,               -- since v2.2.0
    target_is_external integer not null default 0  -- since v2.2.0
);

-- Indexes
-- since v1.0.0a
CREATE INDEX resource_revision__resource_id on resource_revision (resource_id);
-- since v1.6.0b
CREATE INDEX resource_revision__error_not_null on resource_revision (
    id,
    resource_id
) where error != "null";
-- since v1.6.0b
CREATE INDEX resource_revision__request_cookie_not_null on resource_revision (
    id,
    request_cookie
) where request_cookie is not null;
-- since v1.6.0b
CREATE INDEX resource_revision__status_code on resource_revision (
    json_extract(metadata, "$.status_code"),
    resource_id
) where json_extract(metadata, "$.status_code") != 200;
```

### Complex Fields

- `resource_revision.request_cookie`
    - The `Cookie` HTTP header value used when fetching the revision.
- `resource_revision.error`
    - Represents a Python exception raised while fetching the revision.
    - Is either the string `"null"` or a stringifed JSON value that looks like:
      `{"type": "gaierror", "message": "Name or service not known"}`,
      as defined by the `DownloadErrorDict` data type.
- `resource_revision.metadata`
    - Is either the string `"null"` or a stringified JSON value with the
      following format:
      
      ```python
      class ResourceRevisionMetadata(TypedDict):
          http_version: int  # 10 for HTTP/1.0, 11 for HTTP/1.1
          status_code: int
          reason_phrase: str
          # NOTE: Each element of headers is a 2-item (key, value) list
          headers: list[list[str]]  # email.message.EmailMessage
      ```

### Index Purposes

- The `resource_revision__resource_id` index makes it fast to lookup revisions
  related to a resource.

- The `resource_revision__error_not_null` and `resource_revision__status_code`
  indexes make it fast to search for revisions with errors.

- The `resource_revision__request_cookie_not_null` index makes it fast to search
  for resources that were NOT fetched with a `request_cookie`, which is suspicious
  in a project were almost all revisions *were* fetched with one.

- There is no `root_resource__resource_id` index because the number of RootResources
  is typically small (less than 100), such that all RootResources are loaded into memory.


## Project Properties

There are a number of properties in the `project_property` table that affect
the project's behavior:

* `major_version`: IntStr = '1'
    - The major version of the project.
    - See §"Major Version" for more information.
    - Since v1.7.0b.
* `default_url_prefix`: NotRequired[str]
    - The root URL prefix to strip/shorten in the UI.
    - Since v1.0.0a.
* `html_parser_type`: Literal['html_parser', 'lxml'] = 'html_parser'
    - The parser used for HTML content.
    - Since v1.6.0b.
* `entity_title_format`: Literal['url_name', 'name_url'] = 'url_name'
    - Determines how entities are labeled in the Entity Tree UI.
    - Since v2.1.0.


## Revisions Format

Each ResourceRevision in a Project has:
- an integer `id`,
- metadata stored as a row in the `resource_revision`, and
- a body stored within the `revisions` directory of the `.crystalproj`.

The structure of the `revisions` directory depends on the `major_version` of
the project.

### major_version == 1 (or undefined), since v1.0.0a

The `revisions` directory has this format:

```
xkcd.crystalproj
├── ...
├── revisions
|   ├── 1
|   ├── 2
|   ├── 3
|   ├── 4
|   ├── 5
|   ├── 6
|   ├── 7
|   ├── 8
|   ├── 9
|   ├── 10
|   ├── 11
|   ├── 12
│   └── ... (up to the maximum revision ID)
└── ...
```

Note: Revision IDs are allocated using SQLite auto-increment IDs which start
at 1 rather than 0.

There is no limit on the number of revisions.

### major_version == 2, since v1.7.0b

The `revisions` directory has this format:

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

Note: Revision IDs are allocated using SQLite auto-increment IDs which start
at 1 rather than 0.

The maximum number of revisions is 16^15 == 2^60 == 1,152,921,504,606,846,976.
It is unlikely that anyone will ever want to exceed this limit.

The maximum number of files/directories per directory is 16^3 == 2^12 == 4,096.

It is the per-directory limit on contained files/directories which makes
`major_version == 2` projects more efficent to access on most filesystems
for projects containing very many revisions (i.e. millions+).

While a project is being upgraded from major version 1 to 2, a transient
`revisions.inprogress` directory is created to hold the revisions in the
new format. When the upgrade finishes that directly will be renamed to
be the new `revisions` directory.

History: `major_version == 2` projects were introduced as part of downloading a
website containing about 5.5 million revisions and 2.6 TB of data,
the largest project ever downloaded by Crystal's author at the time.


## Additional Files

Projects contain a number of additional files which aren't related to the core
content of the project:

```
xkcd.crystalproj
├── ...
|   
|   [ADDITIONAL FILES]
├── .directory          -- Linux: Defines custom icon for .crystalproj directory. Since v1.7.0b.
├── desktop.ini         -- Windows: Defines custom icon for .crystalproj directory. Since v1.7.0b.
├── icons               -- Windows: Defines custom icon for .crystalproj directory. Since v1.7.0b.
│   └── docicon.ico     -- Windows: Defines custom icon for .crystalproj directory. Since v1.7.0b.
├── OPEN ME.crystalopen -- Launches the Crystal app when opened. Since v1.7.0b.
├── README.txt          -- Explains where to download the Crystal app. Since v1.7.0b.
└── tmp                 -- Temporary directory for Crystal's internal use. Since v1.6.0b.
```

Whenever Crystal opens a project as writable and observes that an additional
file it expects is missing, it will create the missing additional file with
its default content.

The opener (`OPEN ME.crystalopen`) exists to make it easy for users to open the
project with the Crystal app on operating systems where `.crystalproj` directories
cannot be marked as file-like or when the file-like behavior fails to work.
It always has the FourCC file content b'CrOp' ("Crystal Opener")
to make it easy to identify for signature-based detection algorithms.

The temporary directory (`tmp`) is currently used to hold partially downloaded
files during download operations. It is cleared whenever a project is opened as writable.
Therefore it is not safe to persist any data in this directory across opens of the project.
