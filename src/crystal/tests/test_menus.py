from crystal.tests.test_shell import (
    # TODO: Extract methods to shared module rather than importing private functions
    _create_new_empty_project,
    _OK_THREAD_STOP_SUFFIX,
    _py_eval,
    crystal_shell,
)
from crystal.tests.util.windows import OpenOrCreateDialog
from crystal.tests.util.xos import skip_on_windows
import tempfile
import textwrap


async def test_can_close_project_with_menuitem() -> None:
    with tempfile.TemporaryDirectory(suffix='.crystalproj') as project_dirpath:
        async with (await OpenOrCreateDialog.wait_for()).create(project_dirpath, autoclose=False) as (mw, _):
            await mw.close_with_menuitem()


async def test_can_quit_with_menuitem() -> None:
    skip_on_windows()()  # crystal_shell doesn't support Windows
    
    with crystal_shell() as (crystal, _):
        _create_new_empty_project(crystal)
        
        _py_eval(crystal, textwrap.dedent(f'''\
            from crystal.tests.util.runner import run_test
            from crystal.tests.util.windows import MainWindow
            from threading import Thread
            import wx

            async def quit_with_menuitem():
                mw = await MainWindow.wait_for()
                #
                await mw.quit_with_menuitem()
                #
                print('OK')

            t = Thread(target=lambda: run_test(quit_with_menuitem))
            t.start()
            '''), stop_suffix=('crystal.util.xthreading.NoForegroundThreadError\n',))


async def test_can_open_preferences_with_menuitem() -> None:
    with tempfile.TemporaryDirectory(suffix='.crystalproj') as project_dirpath:
        async with (await OpenOrCreateDialog.wait_for()).create(project_dirpath) as (mw, _):
            prefs_dialog = await mw.open_preferences_with_menuitem()
            await prefs_dialog.ok()
