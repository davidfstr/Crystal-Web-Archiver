# Aliases

I want to add support for a new kind of entity in Crystal projects: Aliases

An Alias says that all URLs with a particular Source URL Prefix should be
treated as be equivalent to the same URL with the source prefix replaced
with a Target URL Prefix.

Both source and target prefixes must end in a slash (/).
- The model layer raises if this constraint is not met.
    - See `Alias.__init__` docstring below.
- The UI layer will add a trailing slash if none is provided explicitly.
    - See `# === Test: Rewrite URLs to End in Slash ===` in UI tests below

Additionally an Alias may be configured so that the Target URLs resulting from 
URL rewriting may be treated as External to the project, targeting a live resource
on the internet rather than a different URL within the project.

## Database Schema

Structurally, an Alias will be stored in a new table within a project's SQLite
database, with the following structure:

- "alias" (new table)
    - id: int (primary, autoincrement)
    - source_url_prefix: str (unique)
        - ex 1: `https://www.folklore.org/`
        - ex 2: `ftp://mirror:mirror@ftp.macintosh.garden/`
    - target_url_prefix: str
        - ex 1: `https://folklore.org/`
        - ex 2: `https://files.dafoster.net/ftp.macintosh.garden/`
    - target_is_external: bool = False
        - ex 1: `False` (target exists within project)
        - ex 2: `True` (target exists outside project, as a live resource on the internet)

## Operations

Similar to other Entities in a Project - such as Root URLs (`RootResource`) and
Groups (`ResourceGroup`) - Aliases support:

* List (aka: read)
* New (aka: create)
* Edit (aka: update)
* Forget (aka: delete)

List (in UI):
- Aliases will appear alongside other entities in the Entity Tree within the Main Window.
- They will appear after {Root Resources, Resource Groups}.
- Aliases will appear in order - relative to each other - in the order they were
  created (i.e. SORT BY id ASC).
- The node in the entity tree:
    - Will have an icon matching the Unicode ⎋ icon
    - Will have the icon tooltip "Alias"
    - Will have text/label in the format:
        - `{source_url_prefix}/** → {target_url_prefix}/**`
          (if target_is_external = False)
            - "→" is a Unicode right arrow
        - `{source_url_prefix}/** → 🌐 {target_url_prefix}/**`
          (if target_is_external = True)
            - "🌐" is the Unicode globe icon
    - Will never have children nodes

New (in UI):
- Most entities support triggering the New action through 2 mechanisms:
    1. A "New" button in the Entity Pane below the Entity Tree
    2. A "New" menuitem in the "Entity" menu
  However:
    - Aliases are expected to be a somewhat advanced type of entity,
      not commonly used.
    - There isn't horizontal space available to introduce another "New"
      button in the Entity Pane without reworking the UI layout.
  Therefore:
    - Aliases will only support triggering the New action through the
      second mechanism (which is less visible to end users than the first one):
        2. A "New" menuitem in the "Entity" menu
- The "New" menuitem will be titled "New Alias...",
  appear directly after the existing {"New Root URL..." and "New Group..."} menuitems, 
  and have the keyboard accelerator Cmd-Shift-A (or Ctrl-Shift-A on non-macOS)
- The New action will show a `NewAliasDialog`, similar in structure to the dialogs
  for other entities (`NewRootUrlDialog` and `NewGroupDialog`), with the following
  appearance:

    # New Alias
    Source URL Prefix: ________________________________________ [📋]
    Target URL Prefix: ________________________________________ [📋]
                       [ ] 🌐 External: On internet, outside project
    
                                                      [Cancel] [New]
    
  Notes:
    - "🌐" is the Unicode globe icon, used consistently in the UI
      to signify an External URL residing outside the project as
      a live internet resource
    - "[📋]" is a copy button, similar to the one used in the
      NewRootUrlDialog
- Edge cases:
    - source_url_prefix or target_url_prefix is not a valid URL,
      including common cases like omitting the https:// or http:// prefix
        - Defer validation of this case to the v2 implementation.
        - For v1, continue to passthru the invalid URL to the Alias
          (and Resource constructors).
    - (source_url_prefix == target_url_prefix) and (target_is_external == False)
        - This is a strange normalization rule that will have no effect.
        - Allow it without comment.
    - (source_url_prefix == target_url_prefix) and (target_is_external == True)
        - This is actually an interesting special case:
          It causes URLs with a particular prefix to be omitted from the
          project and referencing links to be rewritten to point at the
          live site (assuming it is still online).
        - Allow it without comment.
    - Neither source_url_prefix nor target_url_prefix match any discovered
      URLs (Resources) in the project
        - Doesn't matter. This is expected to be a common case.
    - If multiple aliases could apply to the same URL,
      the first matching alias (ORDER BY id ASC) wins.
          

Edit (in UI):
- The existing "Edit" button and menuitem will trigger the Edit action on
  an Alias if the Alias is selected in the Entity Tree when the "Edit"
  button/menuitem is triggered.
- Similar to other entity types, the Edit action will show a modified version
  of the New dialog, with the following changes:
    - Title/heading is changed from "# New Alias" to "# Edit Alias".
    - The "Source URL Prefix" field is disabled, although its copy button still works.
        - Disallowing change of the Source URL Prefix after construction
          is expected to simplify the initial implementation of Aliases.
    - All other fields remain enabled.
    - OK button is changed from "New" to "Save"

Forget (in UI):
- The existing "Forget" button and menuitem will trigger the Forget action on
  an Alias if the Alias is selected in the Entity Tree when the "Forget"
  button/menuitem is triggered.

The above alias operations can also be performed in the CLI/Shell,
in addition to the (G)UI, through methods on a new `Alias` class and 
new methods on the existing `Project` class:

```python
class Project:
    # Positioned after Project._revision_count, before "# === Tasks ==="
    @property
    def aliases(self) -> Iterable[Alias]: ...

# NOTE: Similar interface/implementation as RootResource
class Alias:
    # === Init ===
    
    @fg_affinity
    def __init__(self,
        project: Project,
        source_url_prefix: str,
        target_url_prefix: str,
        *, target_is_external: bool = False
        ) -> None: ...
        """
        Raises:
        * ProjectReadOnlyError
        * Alias.AlreadyExists --
            if there is already an `Alias` with specified `source_url_prefix`.
        * ValueError --
            if `source_url_prefix` or `target_url_prefix` do not end in slash (/).
        """
    
    # === Delete ===
    
    @fg_affinity
    def delete(self) -> None: ...
    
    # === Properties ===
    
    @property  # read-only
    def source_url_prefix(self) -> str: ...
    
    @property  # read/write
    def target_url_prefix(self) -> str: ...
    
    @property  # read/write
    def target_is_external(self) -> bool: ...
    
    # === Utility ===
    
    def __repr__(self):
        if self.target_is_external:
            return f'Alias({self.source_url_prefix!r}, {self.target_url_prefix!r}, target_is_external={True!r})'
        else:
            return f'Alias({self.source_url_prefix!r}, {self.target_url_prefix!r})'
    
    class AlreadyExists(Exception): ...
```

## Interactions

### URL Normalization

Aliases will be implemented using the existing **URL normalization** system
that already exists in Crystal, which is battle-tested and well-covered by tests.

Formally, a source URL that is mapped to a target URL by an Alias
says that the source URL *normalizes* to the target URL in the existing
normalization system implemented in Resource.resource_url_alternatives().
- Affected implementation: Resource.resource_url_alternatives
- Covering tests: src/crystal/tests/test_url_normalization.py

Alias-based normalization happens after all other types of normalization.
In particular alias-based normalization happens after plugin-based normalization.

Notable effects of using the existing URL normalization system:
- Download tasks will resolve links to normalized URLs,
    UNLESS a Resource for the original URL was already created
    (regardless of whether the Resource at the original URL has any downloaded ResourceRevisions)
- The Entity Tree will resolve links to normalized URLs,
    UNLESS a Resource for the original URL was already created
    (regardless of whether the Resource at the original URL has any downloaded ResourceRevisions)
- The Project Server when requested an original URL will serve a redirect to its normalized URL,
    UNLESS a Resource for the original URL was already created
    (regardless of whether the Resource at the original URL has any downloaded ResourceRevisions)

The "UNLESS" clauses in the above impacts are frequently not desirable,
because they allow duplicate resources/revisions to stick around in a
project even after an alias is defined.

In a v2 implementation of Aliases, whenever an Alias is created,
the user will be prompted whether or not to delete any preexisting Resources
(and ResourceRevisions) that use Source URLs. The v1 implementation will always
retain any Source URLs that were previously downloaded, for simplicity.

### Handling: Target is External

When normalizing URLs based on an Alias, and the Alias is marked as
target_is_external=True, the Target URL (normally implicitly WITHIN the project)
will take the special form `crystal://external/https://domain/path` in the results
returned by `Resource.resource_url_alternatives`.

That special form will be formatted/parsed centrally by new utility methods:
- def format_external_url(external_url: str) -> str: ...  # returns archive_url
- def parse_external_url(archive_url: str) -> str | None: ...  # returns external_url, or None if not an external URL

The following methods related to converting an Archive URL
(usually WITHIN the project) to a Request URL will be updated to translate
URLs in the form `crystal://external/X` to be just `X`:
- _RequestHandler.get_request_url_with_host() in src/crystal/server/__init__.py
  ⭐(chokepoint)
    - _RequestHandler.get_request_url()
    - get_request_url() at the top-level of src/crystal/server/__init__.py

Resource.__new__ (and its Resource.bulk_get_or_create sibling)
will be modified to recognize attempts to create `crystal://external/X` URLs
and create them in-memory only, not saving them to the database.
    - Pro: Allows code that relies on URL normalization happening inside
      the Resource constructor to continue working without modification.
        - Example: ParseResourceRevisionLinks normalizes links and
          bulk-creates related Resources using Resource.bulk_get_or_create.
    - Con: Extra complexity to introduce a special type of Resource
      that isn't actually in the database. Some operations (like downloading)
      will not work.
        - Resource already has a conceptually similar _UNSAVED_ID mechanism to 
          represent Resources that aren't saved to the database.
          HOWEVER that mechanism is designed for resources that CAN (and SHOULD)
          be saved if a project transitions from read-only to writable.
          Notably, Project._save_as_coro iterates over tracked 
          Project._unsaved_resources and populates their IDs.
            - [ ] Consider renaming Project._unsaved_resources -> 
              _resources_pending_save, to be more clear that the collection
              no longer holds ALL kinds of unsaved resources
        - Instead, introduce a new type of special ID (<0): _EXTERNAL_ID:
            - Use the next available value `_EXTERNAL_ID = -4  # type: Literal[-4]`
            - `id=_EXTERNAL_ID` is valid for `Resource.__new__`
              and `Resource._finish_init`, in its private API
            - `id=_EXTERNAL_ID` is valid for `Resource._id`,
              and will be set that way if passed to `Resource._finish_init`
            - An `id=_EXTERNAL_ID` Resource is NOT recorded in
              its associated project (by `Resource._finish_init`).
              Thus for the 2 copies of `# Record self in Project`,
              rewrite as:
              
                if id == Resource._EXTERNAL_ID:
                    # No need to deduplicate copies of this kind of resource
                    pass
                else:
                    # Record self in Project
                    ... (11 lines)
            
            - Anything in `# === Operations: Download ===` is not valid when
              id is any kind of special id (`id is None or id < 0`).
                - Add an `_ensure_id_is_regular_id` utility method that
                  raises ValueError if any kind of special ID is detected.
                - Call that method from all `# === Operations: Download ===` methods.
            - `id=_EXTERNAL_ID` sets `Resource._definitely_has_no_revisions = True`
              and therefore short-circuits all `# === Revisions ===` queries.
            - Passing a url to Resource.__new__ that parse_external_url thinks
              is an external URL at the same time as passing id != _EXTERNAL_ID
              is an error. Raise ValueError in this situation.

DownloadResourceTask, when looking for embedded resources to download automatically,
will ignore external `crystal://external/X` URLs. That is, it will treat them
as if they were all in a special Do Not Download group.
Affects this code:

    # Normalize the URL and look it up in the project
    # 
    # NOTE: Normally this should not perform any database
    #       queries, unless one of the related Resources
    #       was deleted sometime between being created
    #       by ParseResourceRevisionLinks and being
    #       accessed here.
    link_resource = Resource(project, link_url)
    if not any([g.contains_url(link_resource.url) for g in dnd_groups]):
        embedded_resources.append(link_resource)

Places in the UI where URLs are displayed - notably in the Entity Tree,
when looking at links - will be updated to recognize `crystal://external/X` URLs
and display them as "🌐 X" (where 🌐 is the Unicode globe icon). Suggest
centralizing the formatting logic in a utility method:

    def format_display_url_for_archive_url(archive_url: str) -> str:
        if (external_url := parse_external_url(archive_url)) is not None:
            return f'🌐 {external_url}'
        else:
            return archive_url

## Automated Tests

The above functionality I recommend covering with (at least) the following automated
(mostly acceptance, mostly end-to-end) tests:

Starting from the UI layer:

- test_new_alias.py (in src/crystal/tests/),
  with similar structure as: test_new_root_url.py
    - # === Test: Create & Delete ===
    √√ test_can_create_alias
        √ Include: test when new alias then entity tree is updated
        √ Include: test resource nodes in entity tree corresponding to external urls are formatted correctly
            - # ...as "🌐 {url}"
    √√ test_can_forget_alias
        √ Include: test when forget alias then entity tree is updated
    - # === Test: Rewrite URLs to End in Slash ===
    √ test_given_url_input_is_nonempty_when_blur_url_input_then_appends_slash_if_input_did_not_end_in_slash
    - # === Test: Disallow Create Empty Alias ===
    √ test_given_any_url_input_is_empty_then_ok_button_is_disabled
    √ test_given_any_url_input_is_empty_when_all_url_inputs_becomes_nonempty_then_ok_button_is_enabled
    √ test_given_all_url_inputs_are_nonempty_when_any_url_input_becomes_empty_then_ok_button_is_disabled
    - # === Test: Disallow Create Duplicate Alias ===
    √ test_given_source_url_input_matches_existing_alias_when_press_ok_then_displays_error_dialog
    - # === Test: Copy ===
    √ test_when_press_copy_button_beside_url_input_then_copies_url

- test_edit_alias.py (in src/crystal/tests/),
  with similar structure as: test_edit_root_url.py
    √√ test_can_edit_target_url_and_is_external_of_alias
        √ Include: test when edit alias then entity tree is updated
    √√ test_cannot_edit_source_url_of_alias
    ok test_can_copy_source_or_target_urls

## Implementation Phasing - v1 (Proposed)

- 1. Model Layer: Implement the database schema and operations on aliases in the CLI
    - [x] 1.1: Add `alias` table schema and database migration
        - Since migrations are run on all projects (including new ones),
          recommend implementing table creation *only* as a migration.
    - [x] 1.2: Implement `Alias` class with basic CRUD (no UI, no normalization integration)
    - [x] 1.3: Add `Project.aliases` property
    - [x] 1.4: Manual CLI verification,
          (using the `terminal_operate` tool, running `crystal --shell`)
        - test can create, list, update, delete `Alias` instances
    - [x] 1.5: Write tests for `Alias` CRUD operations
        - Consider extending: test_can_read_project_with_shell, test_can_write_project_with_shell

- 2. URL Normalization Integration & Interactions:
      Implement interactions of aliases with other parts of the system,
      to verify early that the proposed strategy of plugging in to the existing
      URL normalization system will actually work
    - [x] 2.1: Implement `format_external_url()` and `parse_external_url()` utilities
    - [x] 2.2: Modify `Resource.resource_url_alternatives()` to use aliases
    - [x] 2.3: Implement `_EXTERNAL_ID` mechanism in `Resource.__new__`
    - [x] 2.4: Update `_RequestHandler.get_request_url_with_host()` for external URLs
    - [x] 2.5: Update `DownloadResourceTask` to skip external resources
    - [x] 2.6: Write automated tests for URL normalization with aliases
        - Suggest extend the existing test_url_normalization.py module
    - [x] 2.7: Write automated tests for external URL handling
        (ok) 2.7.1. test cannot accidentally create a resource with a url formatted as an external url
            - # ...because ValueError will be raised
        (x) 2.7.2. test downloading a resource ignores any embedded urls that are external
        (x) 2.7.3.
            ✖️ test when serving an html resource containing links to external urls that the external urls are formatted correctly in html
            ✅ test_given_an_html_resource_containing_link_to_an_external_url_is_served_when_link_is_followed_then_redirects_to_external_url
    - [x] 2.8: Manually test whether an Alias works in the Macintosh Garden project to implement a real redirect to an external URL

- 3: UI: Entity Tree Integration
    - [x] 3.1: Display aliases in Entity Tree & make selectable (list operation)
    - [#] 3.2: Implement `format_display_url_for_archive_url()` utility
    - [x] 3.3: Update Entity Tree to show external URLs as "🌐 URL"
    - [x] 3.4: Write automated tests for Entity Tree display

- 4: UI: Create Operation, with UI Dialog
    - [x] 4.1: Create `NewAliasDialog` (basic structure).
               Wire up "New Alias..." menu item (Cmd-Shift-A).
               Can save an alias in the UI.
    - [x] 4.2: Add auto-slash-appending
    - [x] 4.3: Add copy buttons to URL fields
    - [x] 4.4: Implement duplicate alias detection
    - [x] 4.5: Write automated tests for `NewAliasDialog`
        - test_new_alias.py (See §"Acceptance Tests" above.)

- 5: UI: Edit & Delete Operations
    - [x] 5.1: Extend `NewAliasDialog` to support an editing mode.
               Wire up Edit button/menuitem to work with aliases.
               Ensure Entity Tree updates when aliases change.
               Can edit an alias in the UI.
    - [x] 5.2: Wire up Forget button/menuitem to work with aliases.
               Ensure Entity Tree updates when aliases change.
               Can delete an alias in the UI.
    - [x] 5.3: Write automated tests for edit/delete operations
        √ test_edit_alias.py (See §"Acceptance Tests" above.)
        √ test_can_forget_alias (See §"Acceptance Tests" above.)

- 6: Final (Human) QA & Polish
    - [x] 6.1: Review all TODOs and edge cases
    - [x] 6.2: Update RELEASE_NOTES.md
    - [x] 6.3: Final manual integration testing

This breakdown is intended to:
- Separates risky normalization work into its own phase (validate early!)
- Makes each phase completable in 1-3 hours
- Provides clear testing checkpoints
- Avoids coupling UI work with core logic

## Implementation Phasing - v2 (Proposed)

TBD
