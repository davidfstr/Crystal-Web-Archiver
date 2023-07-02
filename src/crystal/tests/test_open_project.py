from crystal import progress
from crystal.progress import CancelOpenProject
from crystal.tests.util.runner import bg_sleep
from crystal.tests.util.server import extracted_project
from crystal.tests.util.subtests import SubtestsContext, awith_subtests
from crystal.tests.util.windows import OpenOrCreateDialog
from unittest.mock import patch


@awith_subtests
async def test_given_project_opening_when_click_cancel_then_returns_to_prompt_dialog(
        subtests: SubtestsContext) -> None:
    with extracted_project('testdata_xkcd.crystalproj.zip') as project_dirpath:
        for method_name in [
                # Case 1: Cancel while creating Project object
                'loading_resource',
                # Case 2: Cancel while creating MainWindow object
                'creating_entity_tree_nodes',
                ]:
            with subtests.test(method_name=method_name):
                ocd = await OpenOrCreateDialog.wait_for()
                
                progress_listener = progress._active_progress_listener
                assert progress_listener is not None
                
                with patch.object(progress_listener, method_name, side_effect=CancelOpenProject):
                    await ocd.start_opening(project_dirpath, next_window_name='cr-open-or-create-project')
                    
                    # HACK: Wait minimum duration to allow open to finish
                    await bg_sleep(0.5)
                    
                    ocd = await OpenOrCreateDialog.wait_for()
