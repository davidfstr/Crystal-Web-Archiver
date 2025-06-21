# Automated Tests for Crystal

Most tests are end-to-end UI tests, which open up a real Crystal project,
interact with UI controls to perform actions, and verify that the output
UI or project state is as expected.

## Define a test module

If you are not adding tests to an existing module like `test_workflows.py`,
then you will need to create a new test module.

All test modules live inside `./src/crystal/tests/` and are named with a
`test_` prefix.

For the new test module to be detected, you must manually add it to
`./src/crystal/tests/index.py` inside the `_TEST_FUNCS` list.

> TODO: Find a way to auto-detect and import test modules in the future,
> in a way that doesn't break when Crystal is packaged with py2app or py2exe.

To run all tests inside a module, like `crystal.tests.test_foo`:

```
$ crystal --test crystal.tests.test_foo
```

## Define a test function

All test functions live at the top-level of a test module and are named with a
`test_` prefix.

### Async tests

Most test functions are declared as `async`.

Test functions declared as `async` run on the foreground UI thread.
They can therefore safely manipulate the UI (i.e. any `wx.Window`),
access any `Project` (which may involve accessing the underlying
SQLite database), and generally call any `@fg_affinity` function.

```
async def test_func_with_ui() -> None:
    ...
```

If you want to use subtests, use the `@awith_subtests` decorator:

```
@awith_subtests
async def test_with_some_subtests(subtests: SubtestsContext) -> None:
    with subtests.test(kwarg1='DownloadResourceTask'):
        ...
    
    with subtests.test(kwarg1='UpdateResourceGroupMembersTask'):
        ...
    
    with subtests.test(kwarg1='DownloadResourceGroupMembersTask'):
        ...
```

To understand how the async test runner works at a low level,
see the [Appendix: How the async test runner works] section.

[Appendix: How the async test runner works]: #how_the_async_test_runner_works

### Sync tests

Test functions NOT declared as `async` run on a background thread:

```
def test_func_without_ui() -> None:
    ...
```

If you want to use subtests, use the `with_subtests` decorator:

```
@with_subtests
def test_with_some_subtests(subtests: SubtestsContext) -> None:
    with subtests.test(kwarg1='DownloadResourceTask'):
        ...
    
    with subtests.test(kwarg1='UpdateResourceGroupMembersTask'):
        ...
    
    with subtests.test(kwarg1='DownloadResourceGroupMembersTask'):
        ...
```

## Run a test function or module

To run an individual test function, like `crystal.tests.test_module.test_func`:

```
$ crystal --test crystal.tests.test_module.test_func
```

To run all test functions in a module, like `crystal.tests.test_module`:

```
$ crystal --test crystal.tests.test_module
```

## Download from a served project fixture

Many tests want to download something to a new project. To avoid accessing a 
real network and avoid making requests to a real website, such tests typically
serve an example website from a project fixture:

```
    # Start serving a website that can be downloaded, from a project fixture
    with served_project('testdata_xkcd.crystalproj.zip') as sp:
        
        # Define URLs
        home_url = sp.get_request_url('https://xkcd.com/')
        comic1_url = sp.get_request_url('https://xkcd.com/1/')
        comic2_url = sp.get_request_url('https://xkcd.com/2/')
        comic_pattern = sp.get_request_url('https://xkcd.com/#/')
        
        ...
```

<a name="project_fixtures" />

Currently defined project fixtures include:
- testdata_xkcd.crystalproj.zip
    - Most commonly used fixture.
    - A mostly static site.
    - Includes a few comic and feed resources.
    - For a full list of URLs available, see the URLs defined in
      `test_can_download_and_serve_a_static_site`
      in `test_workflows.py`.
- testdata_xkcd-v2.crystalproj.zip
    - Similar to the "testdata_xkcd.crystalproj.zip" fixture,
      with a similar set of resources, but crawled on a later date
      and with different content.
    - Currently only used by
      `test_can_update_downloaded_site_with_newer_page_revisions`
      in `test_workflows.py`.
- testdata_bongo.cat.crystalproj.zip
    - A slightly dynamic site, with some links constructed by JavaScript
      that cannot be detected by Crystal with static analysis only.
    - Includes a home page and some sound resources.
    - For a full list of URLs available, see the URLs defined in
      `test_can_download_and_serve_a_site_requiring_dynamic_link_rewriting`
      in `test_workflows.py`.

## Create a new project

Most tests want to populate a project from scratch. To create a new project:

```
        # Create a new project using the UI,
        # returning a MainWindow (`mw`) that can be used to control the UI, and
        # returning a `project` that can be used to manipulate the project directly
        async with (await OpenOrCreateDialog.wait_for()).create() as (mw, project):
            ...
```

Tests may want to create a project and reopen it several times:

```
        # Create project
        async with (await OpenOrCreateDialog.wait_for()).create(delete=False) as (mw, project):
            project_dirpath = project.path
            
            ...
        
        # Reopen project
        async with (await OpenOrCreateDialog.wait_for()).open(project_dirpath) as (mw, project):
            ...
        
        # Reopen project without UI
        with Project(project_dirpath) as project:
            ...
```

Old tests sometimes explicitly create an empty directory for a project
before creating and reopening it, but this verbose pattern is discouraged for
new tests:

```
    # Create empty project directory
    with tempfile.TemporaryDirectory(suffix='.crystalproj') as project_dirpath:
        
        # Create project
        async with (await OpenOrCreateDialog.wait_for()).create(project_dirpath) as (mw, project):
            ...
        
        # Reopen project
        async with (await OpenOrCreateDialog.wait_for()).open(project_dirpath) as (mw, project):
            ...
        
        # Reopen project without UI
        with Project(project_dirpath) as project:
            ...
```

> TODO: Rewrite occurrences of the above verbose `TemporaryDirectory` pattern
> to use the new recommended pattern instead.

## Edit a copy of a project fixture

Some tests want to edit a project with realistic content prepopulated.
To create a copy of a [project fixture](#project_fixtures):

```
    # Create a copy of a project fixture
    with extracted_project('testdata_xkcd.crystalproj.zip') as project_dirpath:
        
        # Open the project fixture copy
        async with (await OpenOrCreateDialog.wait_for()).open(project_dirpath) as (mw, project):
            ...
```

## Create project entities directly

After creating or opening a project, it is common to create new project entities
such as `Resource`s, `RootResource`s, or `ResourceGroup`s directly: 

```
            home_r = Resource(project, home_url)
            home_rr = RootResource(project, 'Home', home_r)
            comic_g = ResourceGroup(project, '', comic_pattern, source=home_rr)
```

## Create project entities with the UI

It is also possible to create project entities using the UI.
Using the UI tends to require more verbose code and can be brittle against
UI changes. Therefore using the UI to create project entities is not
recommended unless you are writing tests intended to directly test the UI.

```
            root_ti = TreeItem.GetRootItem(mw.entity_tree.window)
            
            # Create root resource
            assert mw.new_root_url_button.Enabled
            click_button(mw.new_root_url_button)
            nud = await NewRootUrlDialog.wait_for()
            nud.name_field.Value = 'Home'
            nud.url_field.Value = home_url
            nud.do_not_download_immediately()
            nud.do_not_set_default_url_prefix()
            await nud.ok()
            home_ti = root_ti.find_child(home_url, project.default_url_prefix)
            
            # Create resource group
            assert mw.new_group_button.Enabled
            click_button(mw.new_group_button)
            ngd = await NewGroupDialog.wait_for()
            ngd.pattern_field.Value = comic_pattern
            ngd.source = 'Home'
            ngd.name_field.Value = 'Comic'
            await ngd.ok()
            comic_ti = root_ti.find_child(comic_pattern, project.default_url_prefix)
```

> TODO: Alter `click_button` to internally assert that the button it is about
> to click is enabled, so that individual tests don't need to do that assert.

## Inspect and manipulate the UI

After creating or opening a project, you'll get an `mw`
(`crystal.tests.util.windows.MainWindow`) object which can be interacted with
to manipulate the UI in the main window. (This is not the same as the
`crystal.browser.MainWindow` object that is available on the Crystal CLI.)

Read the source of `MainWindow` or look at how other tests interact with it
to determine what actions are possible.

Clicking certain buttons in the main window will show new dialogs,
which can be interacted with using other classes in the
`crystal.tests.util.windows` package such as `NewRootUrlDialog`,
`NewGroupDialog`, and `PreferencesDialog`:

```
            assert mw.new_root_url_button.Enabled
            click_button(mw.new_root_url_button)
            nud = await NewRootUrlDialog.wait_for()
```

```
            assert mw.new_group_button.Enabled
            click_button(mw.new_group_button)
            ngd = await NewGroupDialog.wait_for()
```

```
            assert mw.preferences_button.Enabled
            click_button(mw.preferences_button)
            pd = await PreferencesDialog.wait_for()
```

It is common to interact with the entity tree inside the main window.
Many tests immediately locate the root tree item in the entity tree:

```
            root_ti = TreeItem.GetRootItem(mw.entity_tree.window)
```

A `crystal.tests.util.TreeItem` contains many methods for inspection and
manipulation. It is common to `Expand` or `Collapse` a tree item,
inspect its `Children`, locate a specific child using `find_child`, or
select it with `SelectItem`:

```
            (home_ti,) = root_ti.Children
            
            home_ti.Expand()
            await wait_for(first_child_of_tree_item_is_not_loading_condition(home_ti))
            comic1_ti = home_ti.find_child(comic1_url, project.default_url_prefix)
```

## Waiting for downloads to complete

There are several actions that can cause Crystal to start downloading a resource
or resource group using a download task. For example expanding a node in the 
entity tree or selecting a node and pressing the download button will start a
download.

It's not recommended to manually wait for a download to complete using a 
fixed timeout because they can take a highly variable amount of time to complete,
depending on how many embedded subresources there are, among other factors.
Instead use the `wait_for_download_to_start_and_finish` utility method,
which looks for continued *progress* in a download, regardless of how long the
total download task takes to finish:

```
            home_ti.Expand()
            await wait_for_download_to_start_and_finish(mw.task_tree)
```

## Waiting for other things to happen

The `wait_for` function in `crystal.tests.util.wait` can be used to wait for
arbitrary conditions to become true. For example it's common to expand an
entity tree node and wait for its children to no longer display a loading state:

```
            comic_group_ti.Expand()
            await wait_for(first_child_of_tree_item_is_not_loading_condition(comic_group_ti))
```

It's also common to wait for a named window to become visible:

```
            await wait_for(window_condition('cr-new-root-url-dialog'))
```

There are many other kinds of conditions that can be waited for,
defined as functions in the `crystal.tests.util.wait` package that
end with `_condition`. In particular:

- window_condition
    - Whether the named window exists and is visible.
- first_child_of_tree_item_is_not_loading_condition
- tree_has_children_condition
- tree_has_no_children_condition
- tree_item_has_no_children_condition
- is_enabled_condition
    - Whether the specified window is enabled.
- not_condition
    - Whether the specified condition is falsy.
- or_condition
    - Whether any of the specified conditions are true.

The foreground UI thread is released while waiting for a condition,
allowing actions that must be done on the UI thread to make progress.

## Deterministic control of tasks and the task scheduler

Some tests want to have very precise control over the task scheduler,
stepping the scheduler forward manually rather than letting it run
freely. This is common for tests that want to precisely inspect the
state of the task tree in the main window while running tasks.

Such tests can disable the scheduler thread when opening or creating
projects, using the `@scheduler_disabled` context manager:

```
    # Disable the scheduler for any created or opened projects
    with scheduler_disabled():
        
        # Create a project, with the scheduler disabled
        async with (await OpenOrCreateDialog.wait_for()).create() as (mw, project):
            project_dirpath = project.path
            
            ...
        
        # Open a project, with the scheduler disabled
        async with (await OpenOrCreateDialog.wait_for()).open(project_dirpath) as (mw, project):
            ...
```

When the scheduler is disabled, it's recommended to explicitly clean up any 
tasks that aren't complete before closing a project, especially if an assertion
failure during a test causes it to exit early.
The `clear_top_level_tasks_on_exit` context manager makes this cleanup easy:

```
    with scheduler_disabled():
        
        async with (await OpenOrCreateDialog.wait_for()).create() as (mw, project):
            
            # Cleanup any tasks still running before closing the project,
            # even if an exception was raised
            with clear_top_level_tasks_on_exit(project):
                ...
```

When the scheduler is disabled, adding a task to the project (either directly
or indirectly) will NOT add it to the task tree immediately automatically.
The `append_deferred_top_level_tasks` function (in `crystal.tests.util.tasks`)
must be called explicitly:

```
                # Directly add a download task to the project,
                # and finish making it observable in the task tree
                drg_task = comic_g.create_download_task()
                project.add_task(drg_task); append_deferred_top_level_tasks(project)
```

```
                # Indirectly add a download task to the project,
                # and finish making it observable in the task tree
                home_r = Resource(project, home_url)
                home_r.download(); append_deferred_top_level_tasks(project)
```

When the scheduler is disabled, tasks will not run automatically. (Duh.)
The scheduler must be stepped manually:

```
                await step_scheduler(project)  # default: expect_done=False
```

```
                await step_scheduler(project, expect_done=True)
```

```
                step_scheduler_now(project, expect_done=True)
```

It is sometimes useful to run the scheduler until no more tasks are left:

```
                await step_scheduler_until_done(project)
```

## Mocking modal dialogs

Code that calls `ShowModal` on any dialog should use the version of `ShowModal`
imported from `crystal.util.wx_dialog` rather than the method on `wx.Dialog`.

Tests that interact with code that might call `ShowModal` on a
`wx.MessageDialog` *must* mock `ShowModal` to return the button id that the
test wants to click on rather than attempting to directly click the button
in the real dialog.

For example, the version of `ShowModal` imported into the
`crystal.browser.new_group` module can be mocked with:

```
            ngd = await NewGroupDialog.wait_for()
            with patch(
                    'crystal.browser.new_group.ShowModal',
                    mocked_show_modal('cr-empty-url-pattern', wx.ID_OK)
                    ) as show_modal_method:
                click_button(ngd.ok_button)
                assert 1 == show_modal_method.call_count
```

If `ShowModal` isn't mocked correctly then an exception like the following
will be raised when the test runs:

> AssertionError: Attempted to call ShowModal on wx.MessageDialog
> 'cr-empty-url-pattern' while running an automated test, which would hang the
> test. Please patch ShowModal to return an appropriate result.

## Appendix: Notable test suites

The `test_workflows` suite is the oldest suite and performs nearly all actions
directly through the UI, eschewing direct manipulation of the `Project` object.
It tests high-level workflows that a user might want to perform. For example:

- test_can_download_and_serve_a_static_site
- test_can_download_and_serve_a_site_requiring_dynamic_link_rewriting
- test_can_download_and_serve_a_site_requiring_dynamic_url_discovery
- test_can_download_and_serve_a_site_requiring_cookie_authentication

<a name="how_the_async_test_runner_works" />

## Appendix: How the async test runner works

At a low-level, async test functions communicate with the test runner
`run_test` in `crystal.tests.util.runner` by yielding `runner.Command`
instances, using the following functions:

- bg_sleep (SleepCommand)
- bg_fetch_url (FetchUrlCommand)
- pump_wx_events (PumpWxEventsCommand)
- bg_breakpoint (BreakpointCommand)

When a `runner.Command` is yielded, the test runner suspends the test function,
switches from the foreground thread to a background thread, runs the command,
switches back to the foreground thread, and resumes the test function.

### bg_sleep

The `bg_sleep` function is frequently used to wait for an operation on a
`Project` to complete:

```
            # default: wait_for_embedded=False, needs_result=True
            revision_future = comic_r.download()
            while not revision_future.done():
                await bg_sleep(DEFAULT_WAIT_PERIOD)
```

```
            revision_future = comic_r.download_body()
            while not revision_future.done():
                await bg_sleep(DEFAULT_WAIT_PERIOD)
```

> TODO: Extract the preceding common pattern to a reusable function.

> TODO: Mention the preceding wait strategy in the
> "Waiting for downloads to complete" and the 
> "Waiting for other things to happen" sections.

### bg_fetch_url

The `bg_fetch_url` is not typically used directly. Instead the
higher-level `fetch_archive_url` function is more commonly-used by tests
to simulate a web browser fetching a resource revision from a project.

> TODO: Move the preceding paragraph to a new section about strategies
> for simulating using a web browser to fetch a resource revision from a
> project. That can be complicated when multiple projects are being served
> at the same time because then the `_DEFAULT_SERVER_PORT` (2797) may not
> be the correct port to fetch the revision from.

### pump_wx_events

The `pump_wx_events` function is sometimes used when stepping the scheduler
thread manually to run any deferred actions on the foreground thread that
were enqueued by a `fg_call_later` call inside Crystal product code.

> TODO: Move the preceding paragraph to the "Deterministic control of tasks
> and the task scheduler" section.

### bg_breakpoint

The `bg_breakpoint` function is useful to temporarily insert in an
async test function to allow the UI to be inspected & manipulated
when the program reaches the breakpoint location.

> TODO: Move the preceding paragraph to a new "Debugging" section in this README.
