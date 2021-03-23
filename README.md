Crystal Web Archiver
====================

<img src="README/logo.png" title="Crystal Web Archiver icon" align="right" />

Crystal is a program to download websites for long-term archival. It works best
on traditional websites made of distinct pages (rather than infinitely scrolling
feeds of content) which make limited use of JavaScript. This includes most
static websites, blogs, and wikis and excludes most social media sites.

> This project is **alpha quality**, and in particular requires additional
> documentation to be realistically usable by most people. If you'd like to
> take the plunge anyway, please see the "Quickstart" section below.


Download ⬇︎
--------
* [Mac OS X 10.7 (Lion)](https://github.com/downloads/davidfstr/Crystal-Web-Archiver/crystal-mac-1.0.dmg)
* [Windows XP and later](https://github.com/downloads/davidfstr/Crystal-Web-Archiver/crystal-win-1.0.exe)


Quickstart ⭐
----------

* Download the binary for your operating system. See [above](#download).
* Open the program and create a new project, call it "xkcd".
* Click the "+ URL" button to add the "http://xkcd.com/1/" URL, named "First Comic".
* Expand the new "First Comic" node to download the page and display its links.
* Click the "+ Group" button to add a new group called "Comics" with the pattern
  "http://xkcd.com/#/". The "#" is a wildcard that matches any number.
    * If you click the "Preview Members" button in the dialog, you should see a list of
      several URLs, including "http://xkcd.com/1/" and "http://xkcd.com/2/".
* Close the "First Comic" node so that you can see the new "Comics" node at the root level.
* Select the "Comics" node and press the "Download" button.
  This will download all xkcd comics.
* Expand the "Comics" node to see a list of all comic pages.
* Select any comic page you'd like to see and press the "View" button.
  Your default web browser should open and display the downloaded page.


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

Every few years I revisit Crystal to add features allowing me to more sites
that I care about, and to bring Crystal up-to-date for the latest
operating systems.


Design 📐
------

A few unique characteristics of Crystal:

* Downloaded pages are stored on disk in their original form as downloaded from the web,
  including all HTTP headers. This makes the downloaded file format suitable for archival.

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


Contributing ⚒
------------

If you'd like to request a feature or report a bug, please create
[a new GitHub Issue](https://github.com/davidfstr/Crystal-Web-Archiver/issues/new).

To build new binaries for Mac or Windows, follow the instructions at <COMPILING.txt>.

To run tests, run `poetry run pytest` in Terminal (Mac) or Command Prompt (Windows).


Related Projects ⎋
----------------

* [webcrystal]: An alternative website archiving tool that focuses on making it
  easy for automated crawlers (rather than for humans) to download websites.

[webcrystal]: http://dafoster.net/projects/webcrystal/
