This code respository contains the source code for the Crystal tool, 
which is used to download and archive websites, 
with a focus on archiving websites that are at risk of becoming no longer available online.

# Crystal Concepts

Projects:

* Crystal saves a downloaded website in a "project", stored on disk in a .crystalproj directory, which appears as a single file in Finder and Windows Explorer.
* A project contains "resources", each of which corresponds to a URL which can be downloaded.
* A project contains "root resources", each of which corresponds to a well-known URL that is the starting point for downloading a website or part of a website.
* A project contains "resource groups", each of which is a set of resources whose URLs match a well-known pattern.
* A project contains "resource revisions", each of which is a specific version of a resource that has been downloaded.
* A resource is considered "downloaded" when it has at least one resource revision.
* An opened project manages "tasks", each of which corresponds to a running long-lived operation that edits a project, such as downloading root resources or resource groups.

UI:

* The user interface for Crystal is built with wxPython.
* Projects have at most one "main window" which (1) displays the project's root resources and resource groups in an "entity tree" and (2) displays the project's tasks in a "task tree".
* A project may also be created directly - in Crystal's embedded Python shell or in automated tests - without a main window.

Threads:

* The wxPython user interface must both only be accessed from the foreground thread, which is the main thread of the application.
* Projects must also only be accessed from the foreground thread, because its SQLite database enforces a single-threaded access policy.
* Many functions are marked with the `@fg_affinity` decorator, which enforces that they are only called from the foreground thread.
* A callable can be scheduled to run on the foreground thread using `crystal.util.xthreading.fg_call_later()`, which is a wrapper around `wx.CallAfter()`.
* A callable can be run synchronously on the foreground thread using `crystal.util.xthreading.fg_call_and_wait()`, although care should be taken to avoid deadlocks.
* Any thread that is not the foreground thread is considered a "background thread".
* Some functions are marked with the `@bg_affinity` decorator to enforce they are only called from a background thread.
* Each project has a "scheduler thread" that runs tasks in the background, such as downloading resources. A scheduler thread is also a kind of background thread.
* Some functions are marked with the `@scheduler_affinity` decorator to enforce they are only called from the scheduler thread.

Error Handling:

* Crystal uses a "bulkhead" pattern to ensure that (1) the blast radius of an unhandled exception is confined to its containing "bulkhead", and (2) all unhandled exceptions are reported to the user in the UI when possible, or to stderr otherwise:
    * Functions can be marked with one of the `@capture_crashes_to*` decorators to declare how unhandled exceptions should be handled.
    * Many `@capture_crashes_to*` decorators capture exceptions to a `Bulkhead`, which reports them to the user in the UI.
    * Unhandled exceptions which occur while running a task are captured to the task's `Bulkhead`, which reports them to the UI through the task's node in the task tree.
    * Unhandled exceptions which occur in contexts where they cannot be reasonably reported to the UI are captured to stderr using the `@capture_crashes_to_stderr` decorator.
* The traceback of an unhandled exception is always printed to stderr, regardless of how it is captured, so that it is visible to developers:
    * An unhandled exception which is reported in the UI is also printed as a yellow warning to stderr.
    * An unhandled exception which is not reported in the UI is printed as a red error to stderr.

# Development Guidelines

## Features

* All new features should be covered by tests. If you add a new feature, please also add a test for it.
* All new features should be documented in the RELEASE_NOTES.md file. If you add a new feature, please also update the "main" branch section of the RELEASE_NOTES.md file to include it.
* A feature is considered complete when:
    * It has been implemented in the codebase.
    * It has been tested either with end-to-end tests or unit tests.
    * It has been documented in the RELEASE_NOTES.md file.
    * It has been reviewed by at least one other developer.

## Testing

* Read `./src/crystal/tests/README.md` before writing any end-to-end tests.
* End-to-end tests should be added to the `./src/crystal/tests` directory. See the `./src/crystal/tests/README.md` file for more information on how to write end-to-end tests.
* Unit tests should be added to the `./tests` directory. Unit tests should cover individual components or functions in isolation.
* Prefer writing end-to-end tests over unit tests, as they provide a more comprehensive coverage of the feature.
* Tests should cover the full functionality of its related feature, including any edge cases.

* Use `crystal --test crystal.tests.test_FOO` to run a specific end-to-end test file like `./src/crystal/tests/test_FOO.py`. The exit code will be 0 only if tests pass.
* Use `crystal --test` to run all end-to-end tests. All end-to-end tests take as long as 4 minutes to run locally, so prefer running individual test files when possible.
* Use `pytest` to run all unit tests. The exit code will be 0 only if tests pass. All unit tests take less than a second to run locally, so you can run them all at once without worrying about performance.

* End-to-end tests should be named with full sentences, describing the behavior being tested. For example `test_given_entity_tree_in_empty_state_when_create_root_resource_then_entity_tree_enters_non_empty_state`.
* End-to-end tests generally do not require a docstring, as the test name should be descriptive enough.
* End-to-end tests should avoid accessing windows by name directly, e.g. `mw.main_window.FindWindow(name='cr-view-button-callout')`. Instead create/use functions on page object classes in `./src/crystal/tests/util/windows.py` which encapsulate how to locate and manipulate windows.

* Standalone test scripts that use async testing utilities like `OpenOrCreateDialog.wait_for` will not work because they depend on the custom event loop used by `crystal --test` and a running foreground thread. In particular async testing utilities are not compatible with `asyncio.run()`. Instead write temporary scripts as an end-to-end test.

## Conventions

* Use single quotes for strings, e.g. `my_string = 'hello'`.
* Use double quotes for docstrings, e.g. `"""This is a docstring."""`

## Getting Started

* Run `crystal --version` and ensure you see a result like `Crystal 2.0.2`.
    * If you see `crystal: command not found` then you probably need to activate a Python virtual environment first or use Poetry to run commands. Try `source venv3.12/bin/activate && crystal --version` first. If there is no `venv3.12` directory then try `poetry run crystal --version`.
* Ensure you can run a unit test. Try `pytest tests/test_version.py` or `poetry run pytest ...`.
* Ensure you can run an end-to-end test. Try `xvfb-run crystal --test crystal.tests.test_main_window.test_branding_area_shows_crystal_logo_and_program_name_and_version_number_and_authors` or `poetry run xvfb-run crystal --test ...`.
    * If you see `xvfb-run: command not found` then remove `xvfb-run` from the command and try again.
