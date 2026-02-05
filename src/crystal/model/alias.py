from __future__ import annotations

from contextlib import closing
from crystal.model.util import resolve_proxy
from crystal.util.xthreading import (
    fg_affinity,
)
from typing import (
    cast, TYPE_CHECKING,
)

if TYPE_CHECKING:
    from crystal.model.project import Project


# ------------------------------------------------------------------------------
# Alias

class Alias:
    """
    An Alias causes URLs with a particular Source URL Prefix to be considered
    equivalent to the URL with the prefix replaced with a Target URL Prefix.
    
    In particular any links to URLs matching the Source URL Prefix of an Alias
    will be rewritten to point to the equivalent URL with the Target URL Prefix.
    
    An alias's target can be marked as External, meaning that it points to a
    live URL on the internet rather than to a downloaded URL in the project.
    
    Persisted and auto-saved.
    """
    project: Project
    _source_url_prefix: str
    _target_url_prefix: str
    _target_is_external: bool
    _id: int | None  # or None if deleted
    
    # === Init ===
    
    @fg_affinity
    def __init__(self,
            project: Project,
            source_url_prefix: str,
            target_url_prefix: str,
            *, target_is_external: bool = False,
            _id: int | None = None) -> None:
        """
        Creates a new alias.
        
        Arguments:
        * project -- associated `Project`.
        * source_url_prefix -- source URL prefix. Must end in '/'.
        * target_url_prefix -- target URL prefix. Must end in '/'.
        * target_is_external -- whether target is external to the project.
        
        Raises:
        * ProjectReadOnlyError
        * Alias.AlreadyExists --
            if there is already an `Alias` with specified `source_url_prefix`.
        * ValueError --
            if `source_url_prefix` or `target_url_prefix` do not end in slash (/).
        * sqlite3.DatabaseError --
            if a database error occurred, preventing the creation of the new Alias.
        """
        from crystal.model.project import Project, ProjectReadOnlyError
        
        project = resolve_proxy(project)  # type: ignore[assignment]
        if not isinstance(project, Project):
            raise TypeError()
        if not isinstance(source_url_prefix, str):
            raise TypeError()
        if not isinstance(target_url_prefix, str):
            raise TypeError()
        if not isinstance(target_is_external, bool):
            raise TypeError()
        
        # Validate that URL prefixes end in slash
        if not source_url_prefix.endswith('/'):
            raise ValueError('source_url_prefix must end in slash (/)')
        if not target_url_prefix.endswith('/'):
            raise ValueError('target_url_prefix must end in slash (/)')
        
        # Check for duplicate source_url_prefix
        if not project._loading:
            if project.get_alias(source_url_prefix) is not None:
                raise Alias.AlreadyExists(
                    f'Alias with source_url_prefix {source_url_prefix!r} already exists')        
        
        self.project = project
        self._source_url_prefix = source_url_prefix
        self._target_url_prefix = target_url_prefix
        self._target_is_external = target_is_external
        
        if project._loading:
            assert _id is not None
            self._id = _id
        else:
            if project.readonly:
                raise ProjectReadOnlyError()
            with project._db, closing(project._db.cursor()) as c:
                c.execute(
                    'insert into alias (source_url_prefix, target_url_prefix, target_is_external) values (?, ?, ?)',
                    (source_url_prefix, target_url_prefix, int(target_is_external)))
                self._id = c.lastrowid
        project._aliases.append(self)
        
        # Notify listeners if not loading
        if not project._loading:
            project._alias_did_instantiate(self)
    
    # === Delete ===
    
    @fg_affinity
    def delete(self) -> None:
        """
        Deletes this alias.
        
        Raises:
        * ProjectReadOnlyError
        * sqlite3.DatabaseError --
            if the delete fully failed due to a database error
        """
        from crystal.model.project import ProjectReadOnlyError
        
        if self.project.readonly:
            raise ProjectReadOnlyError()
        with self.project._db, closing(self.project._db.cursor()) as c:
            c.execute('delete from alias where id=?', (self._id,))
        self._id = None
        
        self.project._aliases.remove(self)
        
        self.project._alias_did_forget(self)
    
    # === Properties ===
    
    @property
    def source_url_prefix(self) -> str:
        """Source URL prefix. Always ends in '/'."""
        return self._source_url_prefix
    
    def _get_target_url_prefix(self) -> str:
        """
        Target URL prefix. Always ends in '/'.
        
        Setter Raises:
        * sqlite3.DatabaseError
        """
        return self._target_url_prefix
    @fg_affinity
    def _set_target_url_prefix(self, target_url_prefix: str) -> None:
        from crystal.model.project import ProjectReadOnlyError
        
        if not target_url_prefix.endswith('/'):
            raise ValueError('target_url_prefix must end in slash (/)')
        if self._target_url_prefix == target_url_prefix:
            return
        
        if self.project.readonly:
            raise ProjectReadOnlyError()
        with self.project._db, closing(self.project._db.cursor()) as c:
            c.execute('update alias set target_url_prefix=? where id=?', (
                target_url_prefix,
                self._id,))
        
        self._target_url_prefix = target_url_prefix
        
        self.project._alias_did_change(self)
    target_url_prefix = cast(str, property(_get_target_url_prefix, _set_target_url_prefix))
    
    def _get_target_is_external(self) -> bool:
        """Whether target is external to the project."""
        return self._target_is_external
    @fg_affinity
    def _set_target_is_external(self, target_is_external: bool) -> None:
        from crystal.model.project import ProjectReadOnlyError
        
        if not isinstance(target_is_external, bool):
            raise TypeError()
        if self._target_is_external == target_is_external:
            return
        
        if self.project.readonly:
            raise ProjectReadOnlyError()
        with self.project._db, closing(self.project._db.cursor()) as c:
            c.execute('update alias set target_is_external=? where id=?', (
                int(target_is_external),
                self._id,))
        
        self._target_is_external = target_is_external
        
        self.project._alias_did_change(self)
    target_is_external = cast(bool, property(_get_target_is_external, _set_target_is_external))
    
    # === External URLs ===
    
    @staticmethod
    def format_external_url(external_url: str) -> str:
        """
        Given an external URL (pointing to a live resource on the internet),
        returns the corresponding archive URL that should be used internally
        within the project to represent this external resource.
        
        Example:
        >>> Alias.format_external_url('https://example.com/page')
        'crystal://external/https://example.com/page'
        """
        return f'crystal://external/{external_url}'
    
    @staticmethod
    def parse_external_url(archive_url: str) -> str | None:
        """
        Given an archive URL, returns the corresponding external URL if the
        archive URL represents an external resource, or None otherwise.
        
        Example:
        >>> Alias.parse_external_url('crystal://external/https://example.com/page')
        'https://example.com/page'
        >>> Alias.parse_external_url('https://example.com/page')
        None
        """
        prefix = 'crystal://external/'
        if archive_url.startswith(prefix):
            return archive_url[len(prefix):]
        else:
            return None
    
    @staticmethod
    def format_external_url_for_display(external_url: str) -> str:
        return f'🌐 {external_url}'
    
    # === Utility ===
    
    def __repr__(self):
        if self.target_is_external:
            return f'Alias({self.source_url_prefix!r}, {self.target_url_prefix!r}, target_is_external={True!r})'
        else:
            return f'Alias({self.source_url_prefix!r}, {self.target_url_prefix!r})'
    
    class AlreadyExists(Exception):
        """
        Raised when an attempt is made to create a new `Alias` with a
        `source_url_prefix` that is already used by an existing `Alias`.
        """


# ------------------------------------------------------------------------------
