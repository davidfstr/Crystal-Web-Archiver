This code respository contains the source code for the Crystal tool, 
which is used to download and archive websites, 
with a focus on archiving websites that are at risk of becoming no longer available online.

# Crystal Concepts

* Crystal saves a downloaded website in a "project", stored on disk in a .crystalproj directory, which appears as a single file in Finder and Windows Explorer.
* A project contains "resources", each of which corresponds to a URL which can be downloaded.
* A project contains "root resources", each of which corresponds to a well-known URL that is the starting point for downloading a website or part of a website.
* A project contains "resource groups", each of which is a set of resources whose URLs match a well-known pattern.
* A project contains "resource revisions", each of which is a specific version of a resource that has been downloaded.
* A resource is considered "downloaded" when it has at least one resource revision.
* An opened project manages "tasks", each of which corresponds to a running long-lived operation that edits a project, such as downloading root resources or resource groups.

# Development Guidelines

## General

* All new features should be covered by tests. If you add a new feature, please also add a test for it.
* All new features should be documented in the RELEASE_NOTES.md file. If you add a new feature, please also update the "main" branch section of the RELEASE_NOTES.md file to include it.
* A feature is considered complete when:
    * It has been implemented in the codebase.
    * It has been tested either with end-to-end tests or unit tests.
    * It has been documented in the RELEASE_NOTES.md file.
    * It has been reviewed by at least one other developer.

* End-to-end tests should be added to the `./src/crystal/tests` directory. See the `./src/crystal/tests/README.md` file for more information on how to write end-to-end tests.
* Unit tests should be added to the `./tests` directory. Unit tests should cover individual components or functions in isolation.
* Prefer writing end-to-end tests over unit tests, as they provide a more comprehensive coverage of the feature.
* Tests should cover the full functionality of its related feature, including any edge cases.

* Use `crystal --test crystal.tests.test_FOO` to run a specific end-to-end test file like `./src/crystal/tests/test_FOO.py`. The exit code will be 0 only if tests pass.
* Use `crystal --test` to run all end-to-end tests. All end-to-end tests take as long as 4 minutes to run locally, so prefer running individual test files when possible.
* Use `pytest` to run all unit tests. The exit code will be 0 only if tests pass. All unit tests take less than a second to run locally, so you can run them all at once without worrying about performance.

## bash and shell scripts

* Prefer long-form options over short-form options for clarity. When converting a short-form option to a specific long-form option be sure the specific long-form option actually exists.
