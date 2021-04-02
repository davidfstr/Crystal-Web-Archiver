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

* [macOS 10.14 and later](https://github.com/davidfstr/Crystal-Web-Archiver/releases/download/v1.1.0b/crystal-mac-1.1.0b.dmg)
* [Windows 7, 8, 10](https://github.com/davidfstr/Crystal-Web-Archiver/releases/download/v1.1.0b/crystal-win-1.1.0b.exe)


Quickstart ⭐
----------

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


Known Issues 🐞
------------

* The UI does not allow a group to be changed once it is defined. In particular
  the source of a group cannot be changed in the UI.
    * As a workaround, create a new group with the desired changes and delete the old group.

* robots.txt is not obeyed.
    * In practice this isn't a big issue since the user is required to explicitly define
      which pages should be downloaded.
    * Furthermore, there is a hardcoded delay of 1 second between downloads of pages,
      to avoid taxing site infrastructure and to avoid unintentional denial of service
      attacks.

* Memory usage when downloading large groups (>2000 members) is very high.
    * There may be wxPython objects that aren't getting deallocated properly.
      In particular I suspect that the "tree refresh" behavior that occurs
      may not be deallocating old tree node references correctly.
    * Or there may be an object reference that isn't getting cleaned up correctly.
    * Informal testing suggests that both problems are probably present.

* Projects (and the underlying databases) are manipulated on the UI thread.
  Occasionally this causes the UI to become unresponsive for a few seconds.

* Large projects (with 10,000+ resources) take a few seconds to open
  because all project resource URLs are loaded into memory immediately.
  Also no feedback is displayed while opening.


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

### v1.1.1b <small>(TBD)</small>

* macOS Fixes
    * Fix argument processing issue that prevented app launch on 
      macOS 10.14 Mojave.

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
