from crystal import __version__
import os
import pytest
import re


def test_version_is_expected_value() -> None:
    assert __version__ == '1.5.0b', \
        'Version in crystal/__init__.py is not the expected value'


def test_version_in_pyproject_toml_is_consistent_with_package_version() -> None:
    pyproject_toml_filepath = os.path.join(
        os.path.dirname(__file__), '..', 'pyproject.toml')
    with open(pyproject_toml_filepath, 'r', encoding='utf-8') as f:
        pyproject_toml = f.read()
    
    m = re.search(r'\nversion *= *"([^"]+?)(\.post\d+)?\"\n', pyproject_toml)
    assert m is not None, 'Unable to find version in pyproject.toml'
    pyproject_toml_version = m.group(1)
    assert __version__ == pyproject_toml_version, \
        'Version in pyproject.toml and crystal/__init__.py are not the same'


@pytest.mark.skip('not yet automated')
def test_version_and_copyright_in_mac_binary_is_correct() -> None:
    pass


def test_version_and_copyright_in_windows_binary_is_correct() -> None:
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
    assert __version__ == app_version, \
        'Version in win-installer.iss does not match expected string from crystal/__init__.py'
    
    m = re.search(r'\nAppCopyright=(.*)\n', iss)
    assert m is not None
    app_copyright = m.group(1)
    assert COPYRIGHT_STRING_.replace('©', '(C)') == app_copyright, \
        'Copyright string in win-installer.iss does not match expected string from setup_settings.py'
    
    m = re.search(r'\nOutputBaseFilename=(.*)\n', iss)
    assert m is not None
    output_base_filename = m.group(1)
    assert f'crystal-win-{__version__}' == output_base_filename, \
        'Version in output filename in win-installer.iss does not match expected string from crystal/__init__.py'
