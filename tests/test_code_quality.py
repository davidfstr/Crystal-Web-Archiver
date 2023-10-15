from pytest import fail
import subprocess


def test_type_checker_reports_no_errors() -> None:
    try:
        output_bytes = subprocess.check_output(
            ['mypy'],
            stderr=subprocess.STDOUT
        )
        had_error = False
    except subprocess.CalledProcessError as e:
        output_bytes = e.output
        had_error = True
    output = output_bytes.decode('utf-8')
    
    if had_error:
        fail('Typechecker failed with output:\n\n%s' % output.rstrip())
