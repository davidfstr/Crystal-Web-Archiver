from crystal import __version__
import os
import pytest
import re


def test_version_is_expected_value():
    assert __version__ == '1.4.0b'


def test_version_in_pyproject_toml_is_consistent_with_package_version():
    pyproject_toml_filepath = os.path.join(
        os.path.dirname(__file__), '..', 'pyproject.toml')
    with open(pyproject_toml_filepath, 'r', encoding='utf-8') as f:
        pyproject_toml = f.read()
    
    m = re.search(r'\nversion *= *"([^"]+)"\n', pyproject_toml)
    assert m is not None, 'Unable to find version in pyproject.toml'
    pyproject_toml_version = m.group(1)
    assert __version__ == pyproject_toml_version


@pytest.mark.skip('not yet automated')
def test_version_and_copyright_in_mac_binary_is_correct():
    pass


def test_version_and_copyright_in_windows_binary_is_correct():
    iss_filepath = os.path.join(
        os.path.dirname(__file__), '..', 'setup', 'win-installer.iss')
    with open(iss_filepath, 'r', encoding='utf-8') as f:
        iss = f.read()
    
    setup_settings_filepath = os.path.join(
        os.path.dirname(__file__), '..', 'setup', 'setup_settings.py')
    with open(setup_settings_filepath, 'r', encoding='utf-8') as f:
        exec(f.read())
    COPYRIGHT_STRING_ = locals()['COPYRIGHT_STRING']  # HACK
    
    m = re.search(r'\nAppVersion=(.*)\n', iss)
    assert m is not None
    app_version = m.group(1)
    assert __version__ == app_version
    
    m = re.search(r'\nAppCopyright=(.*)\n', iss)
    assert m is not None
    app_copyright = m.group(1)
    assert COPYRIGHT_STRING_.replace('©', '(C)') == app_copyright
    
    m = re.search(r'\nOutputBaseFilename=(.*)\n', iss)
    assert m is not None
    output_base_filename = m.group(1)
    assert f'crystal-win-{__version__}' == output_base_filename
