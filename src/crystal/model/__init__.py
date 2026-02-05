"""
Persistent data model.

Unless otherwise specified, all changes to models are auto-saved.

Model objects may only be manipulated on the foreground thread.
Callers that attempt to do otherwise may get thrown `ProgrammingError`s.

History: The crystal.model package was in a single crystal/model.py file for
the first 10 years of its history and you may still see some references
to "model.py" that haven't been updated.
"""

# ------------------------------------------------------------------------------
# Project

from .project import (
    CrossProjectReferenceError,
    EntityTitleFormat,
    Project,
    ProjectClosedError,
    ProjectFormatError,
    ProjectReadOnlyError,
    ProjectTooNewError,
    RevisionBodyMissingError,
)  # reexport

# ------------------------------------------------------------------------------
# Resource

from .resource import (
    Resource,
)  # reexport

# ------------------------------------------------------------------------------
# RootResource

from .root_resource import (
    RootResource,
)  # reexport

# ------------------------------------------------------------------------------
# ResourceRevision

from .resource_revision import (
    DownloadErrorDict,
    NoRevisionBodyError,
    ProjectHasTooManyRevisionsError,
    ResourceRevision,
    ResourceRevisionMetadata,
    RevisionDeletedError,
)  # reexport

# ------------------------------------------------------------------------------
# ResourceGroup

from .resource_group import (
    ResourceGroup,
    ResourceGroupSource,
)  # reexport

# ------------------------------------------------------------------------------
# Alias

from .alias import (
    Alias,
)  # reexport

# ------------------------------------------------------------------------------
