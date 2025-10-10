Release Notes ⋮
-------------

### Future

* See the [Roadmap].
* See open [high-priority issues] and [medium-priority issues].

[Roadmap]: https://github.com/davidfstr/Crystal-Web-Archiver/wiki/Roadmap
[high-priority issues]: https://github.com/davidfstr/Crystal-Web-Archiver/issues?q=is%3Aopen+is%3Aissue+label%3Apriority-high
[medium-priority issues]: https://github.com/davidfstr/Crystal-Web-Archiver/issues?q=is%3Aopen+is%3Aissue+label%3Apriority-medium

### v2.0.0 (September 26, 2025)

Crystal 2.0 is a huge release with many new features and all-new tutorials!
It's now possible to download a website entirely through a web browser, 
by navigating through already-downloaded pages and incrementally adding URLs 
and groups for any links that weren't already downloaded. Inline help messages
guide first-time users through the process of downloading their first website.
Projects are now created as untitled by default, no longer requiring you to 
immediately save & title them upon creation. Many bugs related to browsing 
read-only projects are now fixed. Documentation is great. UI is stable.
New contributors are actively welcome to help enhance Crystal going forward!

* First-time-run experience improvements
    * After creating an empty project a call-to-action appears to create
      the first root URL.
    * After creating the first root URL a call-to-action appears to view
      the downloaded root URL in a web browser.
    * There are new "Root URLs and Groups" and "Tasks" headings in the
      main window to clearly identify what is in each part of the window.
    * The "View" button no longer appears squished on Linux.
    * A project can be opened by double-clicking it in the macOS Finder
      after Crystal is already running.

* Workflow improvements
    * A website can be effectively downloaded entirely by browsing a partially
      downloaded site via a web browser, rather than through Crystal's traditional UI:
        * Missing pages can be immediately downloaded with 1 click when browsing
          a partialy downloaded website.
        * Groups can be immediately added with 2 clicks when browsing
          a partialy downloaded website.
    * Untitled projects are automatically reopened after an unexpected quit.
    * Untitled projects are now saved to a permanent hidden directory instead of
      the system temporary directory, preventing data loss after unexpected
      logout, restart, or shutdown.
    * The Download button is now closer to the View button,
      to make them easier to use together.
    * A copy button is added beside the URL and URL Pattern fields when editing
      root URLs and groups.

* Branding changes
    * Crystal is now known as "Crystal: A Website Archiver" in long form.
    * Crystal's logo and contributor information is now displayed in the
      main window, alongside its version number.
    * Browser error pages are now appropriately styled and include
      Crystal's branding elements.
    * Served pages include a footer banner with Crystal's branding elements.
    * Licensing terms have been added: PolyForm Noncommercial 1.0.0

* Serving improvements
    * When serving from a remote `--host`, projects are opened in `--readonly`
      mode by default so that remote users cannot modify a served project.
      Remote modifications can be explicitly enabled with `--no-readonly`.
    * Caching is disabled for revisions served from the root directory
      to avoid seeing stale HTML pages when browsing multiple Crystal projects
      around the same time.
    * Served revisions always have a Date header, to conform with RFC 7231 §7.1.1.2.
    * **Experimental**: Resource group pattern prediction. When enabled with
      `CRYSTAL_PREDICT_GROUPS=1`, Crystal will analyze the current URL and
      referrer when visiting non-archived pages to predict suitable URL patterns
      and sources for creating resource groups. This is intended to support
      future dynamic browsing features. Predictions are printed to the terminal
      with special `[PREDICT]` formatting.

* Read-only project fixes
    * Fix inability to browse the entity tree of some readonly projects.
      Impact was limited primarily to very old readonly projects.
    * Fix inability to open preferences/settings dialog of readonly projects
      created with Crystal <=1.2.0.
    * Project-specific preferences in a read-only project now appear as disabled.
    * Menuitems related to changing the default URL prefix in a read-only project
      now appear as disabled.

* Parsing improvements
    * Recognizes pages containing `<frameset>` tags more accurately.
      In particular a page using a DOCTYPE DTD that mentions "frameset"
      is no longer assumed to necessarily actually contain a `<frameset>`.

* Downloading improvements
    * While long downloads are running the system will be kept awake
      ("caffeinated") on Linux. macOS and Windows support for caffeination
      already existed.

* Documentation improvements
    * Contributing guidelines added as CONTRIBUTING.md.
    * License FAQ drafted.

* API changes
    * `Project.get_root_resource`, `Project.get_resource_group`, and
      `Project.get_resource` now support kwargs for easily filtering by
      name, URL pattern, and ID.
    * `Resource.bulk_get_or_create` is added as a replacement for
      `Resource.bulk_create`. The former function returns resources that were
      looked up in addition to resources that were created, which is usually the
      behavior that a caller wants. The latter function is deprecated.

* Minor fixes
    * Most dialogs are now shown as window-modal rather than modeless to
      prevent certain types of concurrent edits to a project that Crystal
      isn't designed to handle.
    * Dark mode fixes:
        * Task tree appears with a dark background on macOS when in dark mode
          rather than a pure white background.
        * Pure black icons in the task tree and entity tree appear as off-white
          when in dark mode
    * Adhere to OS-native conventions more closely:
        * Save changes dialog now uses OS-native button labels ("Save" and "Don't Save")
          instead of generic "Yes" and "No" buttons, following platform conventions.
        * The "Preferences..." / "Settings..." button in the main window now uses
          the correct title based on OS conventions. And the dialog which appears
          after pressing the button uses a consistent title.
    * Fixed the "Dismiss" action on a crashed task to not itself crash!
    * Altered the prefilled URL prefix on the server Welcome page to
      be https:// rather than http://, which is more appropriate for most sites.

* Testing improvements
    * If the default server port is in use while tests are running, a warning
      message will be printed suggesting to look for other running copies
      of Crystal.

#### v2.0.1

* Downloading improvements
    * Crawl speed improvements
        * For URLs downloaded interactively - by browsing to an undownloaded URL or
          expanding a entity tree node for an undownloaded URL - download at
          high priority, before other tasks.
        * Adjust default (non-interactive) crawl speed to be friendlier to website hosts.

* Serving improvements
    * Wait for a page to fully download (including embedded resources)
      before serving it.
    * Not in Archive Page fixes:
        * Fix race condition where the Download button might not actually wait
          for URL to download before trying to navigate to it.
        * Fix cache configuration so that refreshing the page will never
          display a stale cached Not in Archive page.

* Documentation improvements
    * Fix anchor formatting in README on PyPI.

* Minor fixes
    * Quit and OS logout improvements
        * When OS logout occurs, Crystal will actually finish quitting normally.
        * When Quit is selected from Crystal's Dock icon on macOS,
          Crystal will actually quit.

### v1.11.0 (August 6, 2025)

This release contains many improvements to the first-run experience:
Projects are opened as untitled rather than immediately asking for a name and
location to save the empty project at; the macOS app no longer requires
installing Rosetta 2 on Intel Macs; and there is no firewall warning dialog
on Windows when viewing a downloaded project.

Additionally Crystal's command-line interface (CLI) supports running
`--headless`, has improved help text, automated test coverage, 
and new `--port`/`--host` options for controlling how projects are served.

* Workflow improvements
    * Crystal now creates new projects as untitled by default instead of immediately
      asking for a name and location to save the empty project at.
    * On Windows selecting any item in the Entity menu immediately after
      creating a new project, such as "New Root URL..." or "New Group..."
      no longer fails.
    * Save As can be used to efficiently save a copy of a project.

* Distribution improvements
    * The macOS app is now a Universal 2 binary, running at full speed on
      both ARM and Intel Macs. There is no longer a need to install Rosetta 2
      to run Crystal on ARM Macs.

* Serving improvements
    * The `--port` and `--host` CLI options can be used to control which port
      and address Crystal serves projects from.
    * No longer is an unnecessary
      'Allow "Crystal" to find devices on local networks?' security prompt 
      shown on macOS when viewing a downloaded page after opening the app.

* Accessibility improvements
    * In the Open/Create Project Dialog you can now press Ctrl/Alt/Cmd+R key to toggle 
      the "Open as read only" checkbox. The R key is underlined in the checkbox 
      label on Windows to indicate this keyboard shortcut.

* CLI improvements
    * Crystal can now be run without a graphical user interface with `--headless`,
      allowing efficient use as a server with `--serve` or as a project-aware
      Python shell with `--shell`.
    * Help text printed by `crystal --help` now more clearly describes the 
      available arguments and options.
    * When Crystal is launched with `--readonly` but no project path,
      the Open/Create Project Dialog now pre-checks the "Open as read only" checkbox
      to reflect the command-line option that was specified.

* Minor fixes
    * Rephrased the placeholder text for Name fields to more-obviously be
      placeholders, especially for environments like Windows where the
      placeholder text color is similar to the regular text color.
    * On filesystems that SQLite cannot write to, such as GVFS/SFTP in Linux,
      projects are opened as readonly.

* Development improvements
    * GitHub Copilot Agent now has a comprehensive set of AI instructions
      to refer to when making autonomous changes to Crystal.
    * Decrease average cost of CI runs by running fewer macOS jobs by default.

* Testing improvements
    * Automated tests will now recover gracefully if a previous failed test
      left a MainWindow open.

### v1.10.0 (June 21, 2025)

This release contains significant usability improvements: Reopening a project
resumes any downloads that were previously running, enabling download of very
large websites across multiple sessions of using Crystal. Additionally the
number of clicks to perform several common actions is reduced.

* Workflow improvements
    * Reopening a project resumes any downloads that were in progress
      when the project was previously closed.
    * New URLs are downloaded immediately by default.
    * Can immediately download the site for a newly created URL
      with 1 extra click.
    * Can immediately download a newly created group with 1 extra click.
    * New URLs and groups in an empty project are selected by default.
    * When opening a project the first URL or group is selected by default.
    * Simpler language is used to explain the symbols used in patterns
      for creating new groups.
    * The "do not download" status of resource groups is saved,
      and is no longer forgotten when a project is closed.

* Distribution improvements
    * The macOS app is codesigned and no longer requires you to bypass
      Gatekeeper security settings to open it for the first time.
    * The Windows installer now offers to create a desktop icon and
      open Crystal after installation.

* Downloading improvements
    * HTTPS certificates are now loaded from the system certificate store
      rather than from certifi's static certificate bundle.
        * On Linux you may need to install the `ca-certificates` package
          manually to setup the system's certificate store.

* Minor fixes
    * Fix closing a project to no longer have a couple of heap-use-after-free
      issues which could corrupt memory, potentially crashing Crystal later.

* Testing improvements
    * Automated tests are now regularly run with Address Sanitizer,
      which helps to identify heap-use-after-free bugs related to
      interacting with wxPython that corrupt memory.

* Support changes **(Breaking Change)**
    * Windows 11+ is now the minimum Windows version.
      Drop support for Windows 7, 8, 8.1, and 10.
    * macOS 13+ is now the minimum macOS version.
      Drop support for macOS 12.
    * Python 3.11+ is now the minimum Python version.
      Drop support for Python 3.8, 3.9, and 3.10.

* Branding changes
    * "Crystal Web Archiver" is now known as "Crystal", in short form,
      or as "Crystal: A Website Downloader" in long form.
        * Application binary name is changed. **(Breaking Change)**
        * Log file location is changed. **(Breaking Change)**
    * Crystal is no longer advertised as "beta" software.
        * It is highly stable, with strong backward-compatibility guarantees.
        * Still, a proper intro video needs to be created to make it easy 
          for new users to see the value of Crystal.

### v1.9.0b (June 22, 2024)

This release contains error-handling improvements and bug fixes
in preparation for Crystal to exit beta status.

* Parsing improvements
    * Can identify `'https://'` inside JavaScript as a URL reference,
      which helps download/serve sites using Disqus.
    * Can identify URL references inside `<style>` elements.
    * Can identify URL references inside `<* style="...">`,
      which helps download/serve sites based on phpBB.
    * Can identify `data:` URL references inside `<* srcset="...">`.
    * Can rewrite URL references that use [Subresource Integrity].

* Error handling improvements
    * Crashes now provide tracebacks with more context,
      back to the start of the thread in which the crash occurred.

* Major fixes
    * Fix crash when dynamically downloading a served URL which is a member of
      a group being actively downloaded.

* Minor fixes
    * Do not show a progress dialog if the related operation completes quickly,
      fixing a flickering effect especially noticeable on Windows.
    * Can now save projects named with url-unsafe characters like `#`.
    * Fix closing a project to no longer have a race condition that
      could cause use-after-free of wxPython objects and corrupt memory,
      potentially crashing Crystal later.

[Subresource Integrity]: https://developer.mozilla.org/en-US/docs/Web/Security/Subresource_Integrity

### v1.8.0b (March 17, 2024)

This release contains many workflow improvements, error-handling improvements,
and bug fixes in preparation for Crystal to exit beta status.

It is faster than ever before to define the structure of a site using the UI,
with support for loose browser-style URL entry, better guesses for names and
sources of entities, and the ability to rename entities after creation.

* First-time-run experience improvements
    * New Root URL Dialog:
        * Accept URLs in loose format, similar to what regular web browsers accept.
        * Better error message when try to create duplicate root URL.
        * Disallow create of empty root URL.
    * New Group Dialog:
        * Improve suggested source when creating a new group.
    * New Root URL and New Group Dialogs:
        * Improve suggested name when creating a new root URL or group.
        * Make it optional to provide a name.
        * Rearrange fields to deemphasize the name field.
        * Update the selected node in the Entity Tree intelligently after
          creating or forgetting a root URL or a group.
        * Allow resizing.
        * Ignore leading and trailing whitespace in URLs and URL patterns.
    * Main Window
        * Prevent resizing the window to be too small.
    * Use ⚓️ and 📁 icons consistently in the UI to refer to 
      Root URLs and Groups respectively.

* Workflow improvements
    * Can now edit the name and source of Root URLs and Groups after creation.
    * Can mark resource group as "do not download" to prevent their members
      from being downloaded when in an embedded context.
    * By default the Default Domain will be set to match the first Root URL
      created, enabling reliable serving of more-modern websites with
      client-side URL routing.

* Improved support for Default URL Prefixes
    * Can now set a Default Domain when serving a downloaded project.
      Previously only a Default Directory could be set.
    * The Default Domain/Directory can be set to match a Root URL that
      is being created or edited.
    * A top-level menuitem can now be used to set the Default Domain/Directory
      to match an existing Root URL. Previously it was necessary to use a
      right-click menuitem instead.
    * Hovering over a URL or Group in the Entity Tree always shows the
      full URL or URL Pattern for the entity, even if a Default Domain
      or Default Directory is set.

* Downloading improvements
    * Remaining time is now reported while downloading groups whose members
      are slow to download, taking >7 seconds each.
    * Don't crash when downloading a group that already contains some member
      URLs that were already downloaded.
        * This crash bug was introduced in v1.7.0b with the new strategy of
          creating member download tasks on demand rather than upfront.
    * Don't crash when try to download a URL that is already downloading.
    * Don't crash when try to download a group that has no member URLs.

* Crawling improvements
    * Download the implicit favicon referenced by the root page of any domain.

* Parsing improvements
    * Can identify URL references to images inside `<source srcset="...">`.
    * Gracefully handle references to invalid URLs like `"//*[@id='"`
      rather than crashing.
    * Parse links from RSS and Atom feeds advertised with a specialized XML MIME type
      like `application/rss+xml` or `application/atom+xml`.

* Serving improvements
    * XML files like Atom feeds and RSS feeds are now served correctly,
      without introducing an invalid `<script>` tag.
    * The log showing HTTP requests made to the served project now always
      displays inside the main window, rather than attempting to appear as an
      attached drawer on macOS and Windows.
        * Drawers are not a concept not natively supported by any OS except
          macOS, and even there they are deprecated.
        * Drawers have never worked properly on Linux, due to Wayland not
          providing APIs to position windows precisely relative to each other.
        * The old drawer mode didn't stay attached to the main window properly
          when using Mission Control on macOS.

* Error handling improvements
    * If a task crashes, show it as crashed in the UI and allow it to be dismissed.
    * If the scheduler thread crashes, show it as crashed in the UI and allow it to be restarted.
    * If an update to the entity tree crashes,
      show the crash in the UI and allow the entity tree to be refreshed.

* Testing improvements
    * Waits now use a soft timeout in addition to a hard timeout,
      which makes it easier to tune/bump timeout durations as needed.
        * Triggering a soft timeout causes a warning to be logged.
    * Warnings logged during a test run are collected and reported
      at the end of the test run.
    * Warnings logged during a test run are reported to GitHub Actions
      as warning annotations.
    * A screenshot is taken automatically whenever a timeout error occurs
      and whenever a rich assertion method (from `asserts.py`) fails.
    * A terminal bell sound is played automatically when tests finish running.
    * When an abort() or SIGABRT occurs while running tests during continuous integration,
      print a stack trace using faulthandler.

* Major fixes
    * Fixed multiple cases where code updating the task tree accessed
      the task hierarchy without synchronizing with the scheduler thread,
      which could cause crashes when downloading groups containing members
      that were already downloaded in the same session.
        * Access to the task hierarchy is now protected with @scheduler_affinity
          and explicit is_synced_with_scheduler_thread() checks.
        * This issue was first introduced in v1.7.0b and is now fixed.
    * For projects on a non-SSD drive, fix issue where newly created groups
      did not find any member URLs that were discovered since the project was opened.
      It was previously necessary to reopen a project to reliably find all
      members of a recently created group.
        * This issue was first introduced in v1.7.0b and is now fixed.

* Minor fixes
    * Prevent system idle sleep while tasks are running,
      in more situations on macOS.
    * Fix disappearance of error nodes when new root URL or group is added.
    * If try to create group with empty URL pattern, show error dialog
      rather than silently failing.

### v1.7.0b (December 18, 2023)

This release features further improvements to downloading large websites
(up to 10 million URLs). Projects open in constant time. Memory usage
while downloading large groups remains constant.

Additionally .crystalproj documents now have an appropriate icon and can be 
easily opened by double-clicking that icon on all supported operating systems.

There has also been a major change to the .crystalproj format: Revisions are
now stored in a hierarchy of directories rather than as a single flat directory.
Crystal continues to be able to read and write projects of all major versions.

* First-time-run experience improvements
    * App name, logo, and icon fixes
        * macOS: Fix application menu title and title of its menuitems
        * Windows: Add app icon and Windows-friendly title to main window
        * Linux: Fix app title and icon in dock to be correct
    * .crystalproj package changes
        * .crystalproj packages now contain a README so that users on computers
          without Crystal are informed about what a .crystalproj package is 
          and how to open it
        * Windows/Linux: .crystalproj packages now have an icon
        * Windows: .crystalproj packages that are double-clicked open in Crystal
        * Windows/Linux: .crystalproj packages now contain a .crystalopen file
          so that it is easy to open a .crystalproj from a file browser
        * macOS: Hide .crystalproj and .crystalopen file extensions

* Large project improvements (with 3,000,000 - 11,000,000 URLs)
    * Large projects now open immediately because URLs and group members
      are now loaded on demand rather than upfront.
    * Large groups now start downloading faster because member
      download tasks are now created on demand rather than upfront.
    * The .crystalproj format has a new major change:
        * .crystalproj format now stores revisions in a hierarchy of nested
          directories rather than all of them inside a single directory,
          to provide faster performance on filesystems which behave poorly
          when a single directory has very many files.
        * .crystalproj format now stores revisions in lexicographic order
          in the filesystem so that when a project is copied to a new location,
          the order of revisions on disk is preserved in the new copy.
        * Projects using this new format have a `major_version` of `2`
          in the `project_property` table.
    * Projects whose database is on a solid state drive (SSD)
      will use less memory because such projects will now prefer to
      load group members via a database query rather than loading
      *all* project URLs into memory.

* Support changes
    * Add Kubuntu as a supported Linux distribution
    * Add KDE as a supported desktop environment, in addition to GNOME
    * Drop support for macOS 10.14. macOS 12+ remains supported.

* Parsing improvements
    * Can identify `<link rel="preload">` references as embedded.
    * Can identify URLs inside `<script>` blocks with a trailing `?...` query.
    * Improved reporting of unknown types of `<link rel="...">`.

* Serving improvements
    * Multiple projects can be open and serving URLs at the same time.

* Error handling improvements
    * When expanding an URL in the Entity Tree that downloaded with an error,
      display an error node appropriately.
    * When expanding an undownloaded URL in the Entity Tree that could not be
      downloaded because the disk is full or the project has too many revisions,
      display an error node appropriately.
    * When expanding an URL in the Entity Tree whose revision body has been
      deleted, try to redownload it automatically.

* Critical fixes
    * Fix continuous integration to regularly run UI tests on macOS once again.
    * Fix continuous integration to reliably fail if UI tests fail.

* Minor fixes
    * Eliminated race condition where scheduler thread could try to read from
      the root task's children list concurrently with a different thread
      adding a new child to it.
    * Hide .crystalproj extension in main window title if extension hidden
      in file browser

* Backward-incompatible API changes
    * `fg_call_later`, `fg_call_and_wait`, `bg_call_later`:
        * Keyword arguments are now required for all optional parameters.
        * Arguments passed in the format `*_call_*(callable, ...)`,
          must now be passed as `*_call_*(callable, args=(...))`.
        * `no_profile=` is replaced with `profile=`.
        * `force=` is renamed to `force_later=`.
    * The `OpenProjectProgressListener` interface has substantially changed
      to reflect the new strategy for opening projects.
        * Additionally, a new `LoadUrlsProgressListener` interface is
          introduced to allow monitoring of when a project decides to
          load its URLs. It can be provided to `Project.__init__`.
    * `Project.title` has been removed.
      Calculate a reasonable title from `Project.path` instead.

### v1.6.0b (September 4, 2023)

This release features significant improvements to downloading large websites
(up to 10 million URLs). Projects open and close faster. The UI is faster.
Downloads are faster. Progress bars are shown for all slow operations.
Estimated time remaining is shown when downloading groups.

* Large project improvements (with 3,000,000 - 11,000,000 URLs)
    * Open projects containing many URLs in about 50% as much time as before:
        * Approximate the URL count when loading a project in O(1) time
          rather than getting an exact URL count in O(r) time,
          where r = the number of URLs in the project
        * Decrease the time to load groups from O(r·g) to about O(r + g·log(r)),
          where r = the number of URLs in the project and
          g = the number of groups in the project
        * Defer creation of Entity Tree nodes corresponding to group members
          until the group is actually expanded
    * Close projects with very many queued tasks (such as download tasks)
      in O(1) time rather than O(t) time, where t = the number of queued tasks
    * Speed up interacting with the Entity Tree and Task Tree when
      there are very many URLs in a project:
        * Entity Tree: Speed up expanding URL nodes when large groups exist,
          now in O(k) time rather than O(r·k) time,
          where k = the number of links originating from the URL node and
          r = the number of URLs in the project.
        * Entity Tree: Load only the first 100 members of each group, on demand
        * Task Tree: Show only up to 100 children when downloading a group
    * Speed up interacting with the Add Group dialog when
      there are very many URLs in a project:
        * When typing each character of a new URL pattern and no wildcard
          has yet been typed, perform an O(1) search for matching URLs
          in the preview pane.
        * When typing each character of a new URL pattern and at least one
          wildcard has been typed, perform an O(log(r)) search for matching URLs
          in the preview pane, where r = the number of URLs in the project.
        * Previously an O(r) search was performed in both of the above cases.
    * Show progress while upgrading project with many URLs
    * Show progress dialog when starting to download a large group
    * Show elapsed time in all progress dialogs
    * Prevent system idle sleep while tasks are running (on macOS and Windows)
    * Print large numbers with comma separators or whatever the appropriate
      separator is for the current locale
    * Minimize memory use when there are very many URLs in a project
      by shrinking in-memory Resource, Task, TaskTreeNode, and NodeView objects
      by defining explicit `__slots__`
    * Minimize memory growth while downloading URLs in a project for
      multiple hours or days
    * If free disk space drops too low then refuse to download further resources
    * Quit immediately even when a project with many resources was open recently
    * Open preferences dialog significantly faster for projects containing many URLs
    * Significantly speedup creation of tasks that have many children,
      such as tasks that download groups with very many members

* First-time-run experience improvements
    * Improve defaults
        * New/Open Project Dialog: Default to creating a new project rather
          than opening an existing one.
        * New Group Dialog: Expand "Preview Members" by default.
    * Polish user interface
        * Use consistent words to refer to common concepts
            * {Create, Add} -> New
            * {URL, Root URL} -> Root URL
        * Add menus
        * macOS: Add proxy icon to the project window, making it easier to navigate
          to the project in the Finder.
        * Add app name to version label in lower-left corner of project window.
    * Add keyboard shortcuts everywhere
    * Groups without a source can now be downloaded, as one would expect.
    * Task Tree: Remove top-level tasks that complete periodically,
      rather than waiting for all of them to complete first

* Critical fixes
    * Linux: Fix dialog that appears on app launch to be sized correctly.
    * Linux: Fix View button to open browser even if Crystal run from read-only volume.
    * Linux: Fix most other dialogs to be sized correctly.
    * macOS: Fix issue where dialogs could appear at unusual locations,
      including offscreen.

* Crawling improvements
    * Don't recurse infinitely if resource identifies alias of itself as an
      embedded resource.

* Downloading improvements
    * Show estimated time remaining and speed when downloading groups and URLs
    * Download faster
        * Reinstate the ASSUME_RESOURCES_DOWNLOADED_IN_SESSION_WILL_ALWAYS_REMAIN_FRESH
          optimization that was disabled in v1.4.0b, which significantly speeds up
          downloading groups of HTML pages that link to similar URLs
        * Support immediate early completion of download tasks for URLs
          that were downloaded in the current session or a recent session
        * Record links while downloading faster by writing all of them to the
          project in bulk rather than one by one
        * Open the project's underlying SQLite database
          in [Write-Ahead Logging (WAL) mode](https://www.sqlite.org/wal.html)
          which is faster than the default mode
        * Change delay between downloads to be inserted after each HTML page downloads
          (with its embedded resources), rather than after each single resource downloads.
          This new behavior simulates user browsing more closely and results in
          much faster downloading of HTML pages with many images
          (or other embedded resources).
        * Parallelize download of URLs from origin server with writes to local
          database where possible.
        * Avoid querying the database for revisions of an URL if it is already
          known that there are no revisions because of other information
          cached in memory
        * Precompile XPath selectors used to parse links from HTML
        * Use an optimized version of [shutil.copyfileobj] that avoids
          repeatedly allocating intermediate buffers
        * Maximum download speed increased from 1 item/sec to 2 items/sec
    * Autopopulate an HTTP Date header when downloading if none provided
      by origin server, as per RFC 7231 §7.1.1.2.
    * Load HTTPS CA certificates from certifi on Windows,
      in addition to from the system CA store.
    * Load HTTPS CA certificates from `$SSL_CERT_FILE` if specified.

* Parsing improvements
    * Links are parsed in about 18% as much time as before.
    * Can identify URL references inside `<img srcset="...">`.
    * Skip parsing links in downloaded files known to be binary files.

* Serving improvements
    * Server logs are now displayed in a UI drawer.
    * Links to anchors on the same page are no longer rewritten,
      for better compatibility with JavaScript libraries that
      treat such links specially.
    * Archived pages are read from disk about 45% faster by avoiding an
      unnecessary `os.stat` call.
    * Archived pages are served faster and more efficiently by using
      the [os.sendfile] primitive when supported by the operating system.
    * Don't warn about unknown X- HTTP headers.

* CLI improvements
    * Profiling warnings:
        * Several foreground tasks are optimized so that they
          no longer print slow foreground task warnings
        * Slow garbage collection operations now print a profiling warning
        * Slow "Recording links" operations now print a profiling warning
    * Include [guppy] module for manual [memory leak profiling].
    * A `$PYTHONSTARTUP` file can be defined that is run automatically
      at the beginning of a shell session.

* Error handling improvements
    * When attempting to download a previously-downloaded revision that is
      missing a body file on disk, delete & redownload the old revision.

* Testing improvements
    * An entire test module can now be run with `--test`, in addition to
      individual test functions.

* Minor fixes
    * Clear completed root tasks in all cases, even in the rare case where
      all tasks except the first one are complete
    * When deleting a ResourceRevision, don't delete revision body if project
      is read-only and also properly mark related Resource as no longer being
      downloaded this session
    * When querying a ResourceRevision's size, don't crash with a traceback
    * When running as a macOS .app, log stdout and stderr to files correctly
      once more

* Backward-incompatible API changes
    * `Resource.revisions()` now returns `Iterable[ResourceRevision]` instead
      of `List[ResourceRevision]` to support streaming results.
        * If the old behavior is desired, wrap calls to `Resource.revisions()`
          inside of a `list(...)` expression.
    * `MainWindow.frame` is no longer public.
    * `ResourceRevision.load()` has been renamed to 
      `ResourceRevision._load_from_data()` and privatized.
        * A replacement `ResourceRevision.load()` method now exists that loads
          an existing revision given an ID.

[guppy]: https://pypi.org/project/guppy3/
[memory leak profiling]: https://github.com/davidfstr/Crystal-Web-Archiver/wiki/Testing-for-Memory-Leaks
[os.sendfile]: https://docs.python.org/3/library/os.html#os.sendfile
[shutil.copyfileobj]: https://docs.python.org/3/library/shutil.html#shutil.copyfileobj

### v1.5.0b (April 2, 2023)

This release focuses on making it easy to install Crystal from PyPI,
adds support for running on Linux from source (but not from a binary),
and fixes many bugs with the built-in CLI shell.

Additionally items in the main window are easier to understand
because icons and tooltips have been added for all tree nodes.

* Distribution improvements
    * Can install Crystal using pipx and pip, from PyPI:
        * `pipx install crystal-web`
        * `crystal`
    * Can run Crystal using `crystal` binary:
        * `poetry run crystal`
    * Can run Crystal using `python -m crystal`:
        * `poetry run python -m crystal`
    * Add support for Linux platform (Ubuntu 22.04, Fedora 37)

* CLI improvements
    * Fixed shell to not hang if exited before UI exited, under certain circumstances.
    * Fixed {help, exit, quit} functions to be available when Crystal runs as an .app or .exe.
    * Altered exiting message while windows open to be more accurate.
    * Pinned the public API of `Project` and `MainWindow`.

* Testing improvements
    * Tests are much faster now that download delays are minimized while running tests.
    * Failure messages are improved whenever a WaitTimedOut.
    * A screenshot is taken whenever a test fails.
    * Several race conditions related to accessing the foreground thread are fixed.

* UI Improvements
    * Icons and tooltips added to all tree nodes in the main window,
      clarifying the different types of entities, links, and tasks that exist.
        * Easy to distinguish between URLs and groups.
        * Easy to see whether a URL was downloaded,
          and whether it was downloaded successfully.
    * URL clusters now show in their title how many members they contain.
    * Fixed "Offsite" cluster nodes to update children appropriately whenever
      the Default URL Prefix is changed.
    * Fixed right-click on non-URL node to no longer print a traceback.
    * Fixed attempt to download a group with no source to no longer print a traceback.

### v1.4.0b (August 22, 2022)

This release adds early support for [incrementally redownloading sites
with new page versions](https://github.com/davidfstr/Crystal-Web-Archiver/issues/80).

It is also now possible to download sites requiring login from the UI
and a tutorial has been added showing how to do that.

There are also many stability improvements, with fewer wxPython-related
Segmentation Faults and dramatically improved automated test coverage.

* Downloading improvements
    * Can redownload newer versions of existing URLs using the UI or `--stale-before` CLI option.
    * Can download sites that require cookie-based login using the UI.
    * Fix to send URL path and query rather than absolute URL in HTTP GET requests,
      improving conformance to RFC 2616 (HTTP/1.1).
        * This helps download WordPress sites successfully.
    * Give up if it takes more than 10 seconds to start downloading an URL.
        * This helps automatically skip extremely slow URLs,
          which tend to be dead links.

* Parsing improvements
    * Can identify rel="stylesheet" references inside CSS that don't end in .css
    * Can identify URL references inside Atom feeds and RSS feeds.

* CLI improvements
    * The [shell] now runs commands on the foreground thread by default,
      making it easy to interact with the `project` and `window` variables.

* Stability improvements
    * Two issues that could cause Crystal to crash with a Segmentation Fault
      were fixed:
        * Updates to tasks now do manipulate the related tree nodes
          on the foreground thread correctly.
        * Crashes that occur in wx.Bind() event handlers no longer
          destabilize the program.
    * Various errors of the form
      `wrapped C/C++ object of type X has been deleted` that could be raised
      while Crystal is closing a project are now handled correctly.
    * Automated UI tests pass consistently:
        * Tests no longer rely on network access or real websites.
        * Did workaround wxDialog.ShowModal() hang on macOS.
        * Did workaround deadlock that can happen when closing a main window
          while there are still lingering tasks running.
        * Did add longer timeouts to accomodate slow test VMs on GitHub Actions.

* Documentation improvements
    * Improved introduction in the README.
    * Added tutorial: To download a dynamic website

### v1.3.0b (July 10, 2022)

This release allows more kinds of advanced sites to be downloaded,
including sites requiring login and sites relying on JSON APIs,
especially those with infinitely scrolling pages.

Projects can now be opened in a [read-only mode] such that
browsing existing downloaded content will never attempt to
dynamically download additional content.

Advanced manipulation of projects can now be done from a
[shell] launched from the command-line interface.

Last but not least, [Substack]-based sites are now recognized specially and can be
downloaded effectively without creating an explosion of URL combinations.

* Regular downloading improvements
    * Can download sites that require cookie-based login
      using the `--cookie` CLI option.

* Dynamic downloading improvements
    * Can identify URL references inside JSON responses.
        * In particular URLs that occur within JSON API endpoint responses
          are recognized correctly, which improves support for dynamically
          downloading infinitely scrolling pages.
    * Browsing to an URL that is a member of an existing resource group
      or matches an existing root URL will download it automatically.
    * Downloads now fail with a timeout error if an origin server fails
      to respond promptly rather than hanging the download operation forever.

* Parsing improvements
    * Whitespace is now stripped from relative URLs obtained from HTML tags,
      which allows the related linked URLs to be discovered correctly.

* Serving improvements
    * Downloaded sites will be served with shortened URLs if a
      Default URL Prefix is defined for a project.
    * Served sites will pin the value of `Date.now()` (and similar date/time
      functions in JavaScript) to always return the same date/time
      from when the page was originally downloaded, which helps ensure
      that any JavaScript on the page behaves in a consistent fashion.
        * In particular if there is JavaScript code that is using the
          current date/time to construct & fetch a URL,
          it will now generate a consistent URL (which can be downloaded
          to the project) rather than an inconsistent URL which cannot
          be cached properly.
    * Files that an origin server provided with a custom
      download filename via the [Content-Disposition] HTTP header
      are now correctly served with that filename.
    * Ignore early disconnection errors when a browser downloads a served URL.

* Archival improvements
    * It is now possible to open a project in [read-only mode],
      and this is done automatically for projects that are marked as
      Locked (on macOS), Read Only (on Windows), or reside on a read-only
      filesystem (such as on a DVD, CD, or optical disc).

* UI improvements
    * Main Window: Alter buttons to use more words and less symbols
    * Main Window: Fix splitter to be visible
    * Task Panel: Use white background on macOS (rather than invisible gray)
    * Main Window: Add version number

* CLI improvements
    * A `--serve` CLI option is added which automatically starts serving
      a project immediately after it is opened.
    * A `--shell` CLI option opens a Python shell that can be used to
      interact with projects in an advanced manner.

* Stability improvements
    * Two issues that could cause Crystal to crash with a Segmentation Fault
      were fixed:
        * [Fixed a crash related to attempting to set the icon of a tree node
          that no longer exists](https://github.com/davidfstr/Crystal-Web-Archiver/issues/52)
        * [Fixed a crash related to sorting of wx.TreeCtrl nodes](https://github.com/davidfstr/Crystal-Web-Archiver/commit/a90ca150b0fe76a9f584290a6a16c43b2ffd480a)
    * Automated UI tests now exist, and are run continuously with GitHub Actions.

[read-only mode]: https://github.com/davidfstr/Crystal-Web-Archiver/wiki/Read-Only-Projects
[shell]: https://github.com/davidfstr/Crystal-Web-Archiver/wiki/Shell
[Substack]: https://substack.com/
[Content-Disposition]: https://developer.mozilla.org/en-US/docs/Web/HTTP/Headers/Content-Disposition

### v1.2.0b (April 12, 2021)

This release primarily features better support for large projects and groups.
Downloads of large groups are dramatically faster and now only require a
constant amount of memory no matter how large the group is. Also a progress bar
is now displayed when opening a large project.

A few more link types in CSS and `<script>` tags are now recognized.

Last but not least, phpBB forums are now recognized specially and can be
downloaded effectively without creating an explosion of URL combinations.
phpBB support is still experimental and likely requires additional tuning.

* Performance & memory usage improvements
    * Don't hold resource revisions of group members in memory while downloading
      other members of the same group.
        * Drastically reduces memory usage while downloading large groups,
          and keeps memory usage mostly constant over time.
    * Don't attempt to reparse and redownload embedded resources for resources
      that were already downloaded in the current session of Crystal.
        * Speeds up downloading large groups where many members embed the
          same expensive subresource (like a soft 404 page).
    * Enumerate resource group members in constant time rather than linear time.
        * Drastically speeds up creating new resources and other operations.

* Parsing improvements
    * Can identify `@import "*";` references inside CSS.
    * Can identify //... references inside `<script>` tags.
    * Fix links that contain spaces and other characters to be percent-encoded.
    * Don't try to rewrite `data:` URLs

* Crawling improvements
    * Don't recurse infinitely if resource identifies ancestor as a
      self-embedded resource.
    * Don't download embedded resources of HTTP 4xx and 5xx error pages.

* Serving improvements
    * When dynamically downloading HTML pages, wait for embedded resources too.
      Avoids rendering such pages with a bunch of missing images.

* Miscellaneous
    * Specially recognize and normalize phpBB URLs.
    * Disallow delete of Resource if it is referenced by a RootResource.

### v1.1.1b (April 2, 2021)

Several first-time-launch issues were fixed. And domains are now recognized
in a case-insensitive fashion, eliminating duplicate URLs within some sites.

* macOS Fixes
    * Fix argument processing issue that prevented app launch on 
      macOS 10.14 Mojave.
    * Bundle HTTPS certificates from the 
      [certifi](https://pypi.org/project/certifi/) project.

* Windows Fixes
    * Embed VCRUNTIME140.dll so that Crystal does install reliably on
      a fresh Windows 7 machine.

* Serving & link-rewriting improvements
    * Treat domain names in a case-insensitive fashion.

* Miscellaneous
    * Can delete entire resources from the Crystal CLI, 
      in addition to resource revisions.

### v1.1.0b (March 22, 2021)

Our first beta release brings support for downloading more complex static sites,
recognizing vastly more link types than ever before. It also supports various 
kinds of *dynamic* link-rewriting (🧠), beyond the usual static link-rewriting.

Additionally the code has been modernized to work properly on the latest
operating systems and use newer versions of the BeautifulSoup parser and
the wxWidgets UI library. Unfortunately this has meant dropping support for
some older macOS versions and Windows XP.

* Parsing improvements
    * Recognize `url(*)` and `url("*")` references inside CSS!
    * Recognize http(s):// references inside `<script>` tags! 🧠
    * Recognize http(s):// references inside custom and unknown attribute types! 🧠
    * Recognize many more link types:
        * Recognize `<* background=*>` links
        * Recognize favicon links
    * Fix scoping issue that made detection of *multiple* links of the format
      `<input type='button' onclick='*.location = "*";'>` unreliable.
    * Fix Content-Type and Location headers to be recognized in case-insensitive fashion,
      fixing redirects and encoding issues on many archived sites.
    * Support rudimentary parsing of pages containing frames (and `<frameset>` tags),
      with a new "basic" parser that can be used instead of the "soup" parser.
    * Fix infinite recursion if a resource identifies itself as a self-embedded resource.

* Downloading improvements
    * Save download errors in archive more reliably

* Serving & link-rewriting improvements
    * Dynamically rewrite incoming links from unparseable site-relative and 
      protocol-relative URLs in archived resource revisions! 🧠
        * Did require altering the request URL format to be more distinct: **(Breaking Change)**
            * Old format: `http://localhost:2797/http/www.example.com/index.html`
            * New format: `http://localhost:2797/_/http/www.example.com/index.html`
    * Dynamically download accessed resources that are a member of an existing
      resource group. 🧠
        * Does allow many unparseable resource-relative URLs in archived
          resources to be recognized and downloaded successfully.
    * Better header processing:
        * Recognize many more headers:
            * Recognize standard headers related to CORS, Timing, Cookies, 
              HTTPS & Certificates, Logging, Referer, Protocol Upgrades,
              and X-RateLimit.
            * Recognize vendor-specific headers from AWS Cloudfront, 
              Cloudflare, Fastly, and Google Cloud.
        * Match headers against the header whitelist and blacklist in case-insensitive fashion,
          allowing more headers to be served correctly and reducing unknown-header warnings.
    * Fix to serve appropriate error page when viewing resource in archive
      that was fetched with an error, rather than crashing.
    * Fix transformed HTML and CSS documents to be reported as charset=utf-8 correctly.
    * Automatically fixup URLs lacking a path to have a / path.
    * Don't attempt to rewrite mailto or javascript URLs.
    * Don't print error if browser drops connection early.
    * Avoid printing binary data to console when handling incoming binary protocol message.
        * This can happen if archived JavaScript attempts to fetch a 
          archived resource over HTTPS from an http:// URL.
    * Colorize logged output by default. 🎨

* Modernize codebase
    * Upgrade Python 2.7 -> 3.8
    * Upgrade wxPython 2.x -> 4
    * Upgrade BeautifulSoup 2.x -> 4
    * Track and pin dependencies with Poetry
    * Change supported operating system versions **(Breaking Change)**
        * Drop support for Windows XP. Only Windows 7, 8, and 10 are now supported.
        * Drop support for Mac OS X 10.7 - 10.13. Only macOS 10.14+ is now supported.

* Miscellaneous
    * User-Agent: Alter to advertise correct version and project URL.
    * Logging changes:
        * Mac: Redirect stdout and stderr to file when running as a binary.
        * Windows: Alter location of stdout and stderr log files to be in %APPDATA%
          rather than beside the .exe, to enable logging even when Crystal is running
          from a locked volume.
    * Other fixes:
        * Mac: Fix wxPython warning around inserting an empty list of items to a list.
        * Fix closing the initial welcome dialog to be correctly interpreted as Quit.
    * Documentation improvements to the README
    * Upgrade development status from Alpha -> Beta 🎉

### v1.0.0a (January 24, 2012)

* Initial version
