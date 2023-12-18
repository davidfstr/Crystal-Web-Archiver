Crystal Web Archiver
====================

<img src="https://github.com/davidfstr/Crystal-Web-Archiver/blob/main/README/logo.png" title="Crystal Web Archiver icon" align="right" />

Crystal is a tool that downloads high fidelity copies of websites for long-term archival.

It works best on traditional websites made of distinct pages which make limited
use of JavaScript (such as blogs, wikis, and other static websites)
although it can also download more dynamic sites which have infinitely 
scrolling feeds of content (such as social media sites).

If you are an early adopter and want to get started creating your first project
with Crystal, please see the Tutorial below.
Additional documentation will be available once Crystal is no longer **in beta**.

Download ⬇︎
--------

* [macOS 12 and later](https://github.com/davidfstr/Crystal-Web-Archiver/releases/download/v1.7.0b/crystal-mac-1.7.0b.dmg)
    * You will need to [right-click or Control-click on the application and select "Open" to open it for the first time](https://github.com/davidfstr/Crystal-Web-Archiver/issues/20).
* [Windows 7 and later](https://github.com/davidfstr/Crystal-Web-Archiver/releases/download/v1.7.0b/crystal-win-1.7.0b.exe)
* Linux
    * Install Python >=3.8,<3.12 and pip from your package manager
        * Ubuntu/Kubuntu 22.04+: `apt-get update; apt-get install -y python3 python3-pip python3-venv`
        * Fedora 37+: `yum update -y; yum install -y python3 python3-pip`
    * Install dependencies of wxPython from your package manager
        * Ubuntu/Kubuntu 22.04+: `apt-get install -y libgtk-3-dev`
        * Fedora 37+: `yum install -y wxGTK-devel gcc gcc-c++ which python3-devel`
    * Install pipx
        * `python3 -m pip install pipx`
    * Install Crystal with pipx
        * NOTE: The following step will take a long time (10+ minutes)
          because wxPython, a dependency of Crystal, will need to be built 
          from source, since it does not offer precompiled wheels for Linux.
        * `pipx install crystal-web`
    * (Optional) Install Crystal icon to GNOME/KDE applications and desktop:
        * `crystal --install-to-desktop`
    * Run Crystal:
        * `crystal`


Tutorial ⭐
--------

### To download a static website (ex: [xkcd]):

* Download Crystal for your operating system. See the Download section above.
* Open Crystal and create a new project, call it "xkcd".
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

### To download a dynamic website (ex: [The Pragmatic Engineer]):

* Open Crystal and create a new project.
* Press the "+ URL" button and add: `https://newsletter.pragmaticengineer.com/` -- Home
* Select the added "Home" and press the "Download" button. Wait for it to finish downloading.
* With "Home" still selected, press the "View" button.
  A web browser should open and display the downloaded home page.
* While browsing a downloaded site from a web browser,
  Crystal's server will log information about requests it
  receives from the web browser. For example:
    * `"GET /_/https/newsletter.pragmaticengineer.com/ HTTP/1.1" 200 -`
        * This line says the web browser did try to fetch the
          <https://newsletter.pragmaticengineer.com/> URL from Crystal.
* Notice in the server log that many red lines did appear saying
  "Requested resource not in archive".
    * Since these were fetched immediately when loading the page,
      they must be a kind of resource that is "embedded" into the page.
      When Crystal downloads a page it also downloads all embedded
      resources it can find statically, but these embedded resources 
      must have been fetched *dynamically* by JavaScript code running on the page.
* We want to eliminate those red lines that appear when viewing the home page.

Eliminate red lines:

* Let's start by eliminating the "Requested resource not in archive" red lines
  related to URLs like `https://bucketeer-*/**.png`
* Press the "+ Group" button and add: `https://bucketeer-*/**.png` -- Bucketeer PNG
* Reload the home page in the web browser.
* Notice in the server log that many green lines did appear saying
  "*** Dynamically downloading existing resource in group 'Bucketeer PNG':"
  and that there are no more red lines related to `https://bucketeer-*/**.png`.

Eliminate more red lines:

* However there are still "Requested resource not in archive" red lines 
  related to URLs like `https://substackcdn.com/**.png`. Let's eliminate them too.
* Press the "+ Group" button and add: `https://substackcdn.com/**.png` -- Substack CDN PNG
* Reload the home page in the web browser.
* Again, all red lines related to `https://substackcdn.com/**.png` should be gone.

Eliminate last two red lines:

* There should be only two red lines left:
    * `*** Requested resource not in archive: https://newsletter.pragmaticengineer.com/api/v1/archive?sort=new&search=&offset=12&limit=12`
    * `*** Requested resource not in archive: https://newsletter.pragmaticengineer.com/api/v1/firehose?`...
* Eliminate the first one by creating a group: `https://newsletter.pragmaticengineer.com/api/v1/archive?**` -- Archive API
* Eliminate the second one by creating a group: `https://newsletter.pragmaticengineer.com/api/v1/firehose?**` -- Firehose API
* Reload the home page in the web browser.
* There should be no red lines left.

Eliminate "Page not found" message:

* However there's a strange "Page not found" message displayed at the top of
  the home page.
    * The Pragmatic Engineer is a [Single Page Application] (SPA), 
      a particularly advanced kind of dynamic website.
    * SPAs can get confused when the URL in the browser has a path component
      that isn't what they expected:
        * When loading the real <https://newsletter.pragmaticengineer.com/>,
          the path component of the URL is: `/`
        * When loading the archived version at <http://localhost:2797/_/https/newsletter.pragmaticengineer.com/>,
          the path component of the URL is: `/_/https/newsletter.pragmaticengineer.com/`
* The "Page not found" message is probably caused by the SPA's routing code
  getting confused by the path component of the archived URL not matching
  the path component of the real URL.
* We can alter the path component of the archived URL to be more realistic
  and match the path component of the real URL by setting the
  Default URL Prefix of the project to `https://newsletter.pragmaticengineer.com`.
* Right-click (or Control-Click) on the "Home" URL and select
  "Set as Default URL Prefix" from the contextual menu.
* With the "Home" URL selected, press the "View" button to open it again in the web browser.
* It should have opened in the web browser at URL <http://localhost:2797/>,
  with a path component of `/` just like the real URL.
* There also should be no further "Page not found" messages.

Final testing:

* If you click the "Let me read it first" link at the bottom of the page,
  a list of article links should appear.
* Congratulations! You've fully downloaded the page! 🎉

### To download a website that requires login (ex: [The Pragmatic Engineer]):

* Using a browser like Chrome, login to the website you want to download.
* Right-click anywhere on the page and choose Inspect to open the Chrome Developer Tools.
* Switch to the Network pane and enable the Doc filter.
* Reload the page by pressing the ⟳ button.
* Select the page's URL in the Network pane.
* Scroll down to see the "Request Headers" section and look for a "cookie" request header.
* Copy the value of the "cookie" request header to a text file for safekeeping.
* Open Crystal, either creating a new project or opening an existing project.
* Click the "Preferences..." button, paste the cookie value in the text box, and click "OK".
    * This cookie value will be remembered only while the project remains open.
      If you reopen Crystal again later you'll need to paste the cookie value in again.
* Now download pages using Crystal as you would normally. The specified cookie
  header value (which logs you in to the remote server) will be used as you
  download pages.

[xkcd]: https://xkcd.com
[The Pragmatic Engineer]: https://newsletter.pragmaticengineer.com/

[command-line]: https://github.com/davidfstr/Crystal-Web-Archiver/wiki/Command-Line-Interface
[access the server log from the regular UI]: https://github.com/davidfstr/Crystal-Web-Archiver/issues/44
[Single Page Application]: https://developer.mozilla.org/en-US/docs/Glossary/SPA


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
`poetry run python -m crystal` thereafter.

To **build new binaries** for Mac or Windows, follow the instructions at [COMPILING.txt].

To **run non-UI tests**, run `poetry run pytest` in Terminal (Mac) or in Command Prompt (Windows).

To **run UI tests**, run `poetry run python -m crystal --test` in Terminal (Mac) or in Command Prompt (Windows).

To **typecheck**, run `poetry run mypy` in Terminal (Mac) or in Command Prompt (Windows).

[COMPILING.txt]: COMPILING.txt


Related Projects ⎋
----------------

* [webcrystal]: An alternative website archiving tool that focuses on making it
  easy for automated crawlers (rather than for humans) to download websites.

[webcrystal]: http://dafoster.net/projects/webcrystal/


Release Notes ⋮
-------------

See [RELEASE_NOTES.md](RELEASE_NOTES.md)
