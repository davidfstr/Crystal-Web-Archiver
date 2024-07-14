from crystal.util.xthreading import fg_affinity
import os
import subprocess
import sys
from typing import Union
from typing_extensions import Literal


@fg_affinity
def run_tests_in_parallel(job_count: Union[int, Literal[0]]) -> None:
    if job_count == 0:
        maybe_job_count = os.cpu_count()
        assert maybe_job_count is not None
        job_count = maybe_job_count
    if not (job_count >= 1):
        raise ValueError('Expected job_count >= 1')
    
    # TODO: Run # of jobs requested, rather than just one
    # TODO: Run all tests, rather than just one
    # TODO: Determine appropriate {python, crystal_command} using
    #       similar/same logic as test_shell.py
    python = sys.executable
    crystal_command = [python, '-m', 'crystal']
    crystal = subprocess.Popen(
        [*crystal_command, '--test', 'crystal.tests.test_download_body.test_download_does_save_resource_metadata_and_content_accurately'],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        encoding='utf-8',
        env={
            **os.environ,
            **{
                'CRYSTAL_FAULTHANDLER': 'True',
            },
        })
    crystal_stdout = crystal.stdout  # cache
    assert crystal_stdout is not None
    for line in crystal_stdout:
        print(f'out> {line}', end='')
