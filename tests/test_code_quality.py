import os
from pytest import fail
import subprocess
import sys


def test_type_checker_reports_no_errors() -> None:
    try:
        output_bytes = subprocess.check_output(
            ['mypy'],
            stderr=subprocess.STDOUT
        )
    except subprocess.CalledProcessError as e:
        output_bytes = e.output
        output = output_bytes.decode('utf-8')
        fail('Typechecker failed with output:\n\n%s' % output.rstrip(), pytrace=False)


def test_linter_reports_no_diagnostics() -> None:
    try:
        output_bytes = subprocess.check_output(
            'pylint src tests'.split(' '),
            stderr=subprocess.STDOUT
        )
    except subprocess.CalledProcessError as e:
        output_bytes = e.output
        output = output_bytes.decode('utf-8')
        fail('Linter failed with output:\n\n%s' % output.rstrip(), pytrace=False)


def test_that_zizmor_reports_no_github_action_workflow_vulnerabilities() -> None:
    zizmor = os.path.join(os.path.dirname(sys.executable), 'zizmor')
    try:
        output_bytes = subprocess.check_output(
            [zizmor, '--persona', 'auditor', '.github/workflows/'],
            stderr=subprocess.STDOUT
        )
    except subprocess.CalledProcessError as e:
        output_bytes = e.output
        output = output_bytes.decode('utf-8')
        fail('zizmor found vulnerabilities:\n\n%s' % output.rstrip(), pytrace=False)
