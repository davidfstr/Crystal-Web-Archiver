Crystal Web Archiver
====================

<img src="README/logo.png" title="Crystal Web Archiver icon" align="right" />

Crystal is a program to download websites for long-term archival. It works best
on traditional websites made of distinct pages (rather than infinitely scrolling
feeds of content) which make limited use of JavaScript. This includes most
static websites, blogs, and wikis and excludes most social media sites.

> This project is **beta quality**, and in particular requires additional
> documentation to be realistically usable by most people. If you'd like to
> take the plunge anyway, please see the "Quickstart" section below.


Download ⬇︎
--------

* [macOS 10.14 and later](https://github.com/davidfstr/Crystal-Web-Archiver/releases/download/v1.3.0b/crystal-mac-1.3.0b.dmg)
    * You will need to [right-click or Control-click on the application and select "Open" to open it for the first time](https://github.com/davidfstr/Crystal-Web-Archiver/issues/20).
* [Windows 7, 8, 10](https://github.com/davidfstr/Crystal-Web-Archiver/releases/download/v1.3.0b/crystal-win-1.3.0b.exe)


Quickstart ⭐
----------

To download a simple static website (ex: [xkcd](https://xkcd.com)):

* Download the binary for your operating system. See [above](#download-%EF%B8%8E).
* Open the program and create a new project, call it "xkcd".
* Click the "+ URL" button to add the "https://xkcd.com/1/" URL, named "First Comic".
* Expand the new "First Comic" node to download the page and display its links.
* Click the "+ Group" button to add a new group called "Comics" with the pattern
  "https://xkcd.com/#/". The "#" is a wildcard that matches any number.
  Make sure it also has "First Comic" selected as the Source.
    * If you click the "Preview Members" button in the dialog, you should see a list of
      several URLs, including "https://xkcd.com/1/" and "https://xkcd.com/2/".
* Close the "First Comic" node so that you can see the new "Comics" node at the root level.
* Select the "Comics" node and press the "Download" button.
  This will download all xkcd comics.
* Expand the "Comics" node to see a list of all comic pages.
* Select any comic page you'd like to see and press the "View" button.
  Your default web browser should open and display the downloaded page.
* Congratulations! You've downloaded your first website with Crystal!

To download a website that requires login (ex: [The Pragmatic Engineer](https://newsletter.pragmaticengineer.com/)):

* Using a browser like Chrome, login to the website you want to download.
* Right-click anywhere on the page and choose Inspect to open the Chrome Developer Tools.
* Switch to the Network pane and enable the Doc filter.
* Reload the page by pressing the ⟳ button.
* Select the page's URL in the Network pane.
* Scroll down to see the "Request Headers" section and look for a "cookie" request header.
* Copy the value of the "cookie" request header to a text file for safekeeping.
* Download and launch the [command-line] version of Crystal.
  Passing the saved "cookie" request header value to the `--cookie` command-line option:
    * `poetry run python3 src/main.py --cookie __COOKIE_HEADER_VALUE__`
* Now download pages using Crystal as you would normally. The specified cookie
  header value (which logs you in to the remote server) will be used as you
  download pages.

[command-line]: https://github.com/davidfstr/Crystal-Web-Archiver/wiki/Command-Line-Interface

Known Issues 🐞
------------

* The UI does not allow a group to be changed once it is defined. In particular
  the source of a group cannot be changed in the UI.
    * As a workaround, create a new group with the desired changes and delete the old group.

* robots.txt is not obeyed.
  [(#31)](https://github.com/davidfstr/Crystal-Web-Archiver/issues/31)
    * In practice this isn't a big issue since the user is required to explicitly define
      which pages should be downloaded.
    * Furthermore, there is a hardcoded delay of 1 second between downloads of pages,
      to avoid taxing site infrastructure and to avoid unintentional denial of service
      attacks.

* Large projects (with 10,000+ resources) take a few seconds to open
  because all project resource URLs are loaded into memory immediately.
  [(#30)](https://github.com/davidfstr/Crystal-Web-Archiver/issues/30)


History 📖
-------

I wrote Crystal originally in 2011 because other website downloaders
I tried didn't work well for me and because I wanted to write a large
Python program, as Python was a new language for me at the time.

Every few years I revisit Crystal to add features allowing me to archive 
more sites that I care about, and to bring Crystal up-to-date for the latest
operating systems.


Design 📐
------

A few unique characteristics of Crystal:

* The Crystal project file format (`*.crystalproj`) is suitable for long-term archival:
    * Downloaded pages are stored in their original form as downloaded
      from the web including all HTTP headers.
    * Metadata is stored in a [SQLite database].

* To download pages automatically, the user must define "groups" of pages with similar
  URLs (ex: "Blog Posts", "Archive Pages") and specify rules for finding links to members
  of the group.
    * Once a group has been defined in this way, it is possible for the user to
      instruct Crystal to simply download the group. This involves finding links to all
      members of the group (possibly by downloading other groups) and then downloading
      each member of the group, in parallel.

The design is intended for the future addition of the following features:

* Intelligently updating the pages in websites that have already been downloaded.
    * This would be done by defining rules on groups that specify how often its members
      are updated. For example the set of "Archive Pages" on WordPress blogs is expected
      to change monthly. And the most recently added member of the "Archive Pages" group
      may change daily, whereas the other members are expected to never change.
    * Multiple revisions per downloaded resource are supported to allow multiple
      versions of the same resource to be tracked over time.

[SQLite database]: https://sqlite.org/lts.html


Contributing ⚒
------------

If you'd like to request a feature, report a bug, or ask a question, please create
[a new GitHub Issue](https://github.com/davidfstr/Crystal-Web-Archiver/issues/new),
with either the `type-feature`, `type-bug`, or `type-question` tag.

If you'd like to help work on coding new features, please see
the [code contributor workflow]. If you'd like to help moderate the community
please see the [maintainer workflow].

[code contributor workflow]: https://github.com/davidfstr/Crystal-Web-Archiver/wiki/Contributor-Workflows#code-contributors
[maintainer workflow]: https://github.com/davidfstr/Crystal-Web-Archiver/wiki/Contributor-Workflows#maintainers

### Code Contributors

To **run the code locally**,
run `poetry install` once in Terminal (Mac) or in Command Prompt (Windows), and
`poetry run python src/main.py` thereafter.

To **build new binaries** for Mac or Windows, follow the instructions at [COMPILING.txt].

To **run tests**, run `poetry run pytest` in Terminal (Mac) or in Command Prompt (Windows).

To **typecheck**, run `poetry run mypy` in Terminal (Mac) or in Command Prompt (Windows).

[COMPILING.txt]: COMPILING.txt


Related Projects ⎋
----------------

* [webcrystal]: An alternative website archiving tool that focuses on making it
  easy for automated crawlers (rather than for humans) to download websites.

[webcrystal]: http://dafoster.net/projects/webcrystal/


Release Notes ⋮
-------------

### Future

* See the [Roadmap].
* See open [high-priority issues] and [medium-priority issues].

[Roadmap]: https://github.com/davidfstr/Crystal-Web-Archiver/wiki/Roadmap
[high-priority issues]: https://github.com/davidfstr/Crystal-Web-Archiver/issues?q=is%3Aopen+is%3Aissue+label%3Apriority-high
[medium-priority issues]: https://github.com/davidfstr/Crystal-Web-Archiver/issues?q=is%3Aopen+is%3Aissue+label%3Apriority-medium

### main

* Downloading improvements
    * Can force redownload of older URLs using the `--stale-before` CLI option.

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

### v1.3.0b <small>(July 10, 2022)</small>

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
    * Can now download sites that require cookie-based login
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

### v1.2.0b <small>(April 12, 2021)</small>

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

### v1.1.1b <small>(April 2, 2021)</small>

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

### v1.1.0b <small>(March 22, 2021)</small>

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
        * This can happen if archived JavaScript attempts to force fetching a 
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

### v1.0.0a <small>(January 24, 2012)</small>

* Initial version
