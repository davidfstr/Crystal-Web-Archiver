"""
Unit tests for Pack16 path computation functions.
"""

from crystal.model.resource_revision import ResourceRevision as RR
from crystal.tests.util import xtempfile
import os


def test_entry_name_for_revision_id_computes_correct_values() -> None:
    """Test computing entry names within pack files."""
    # First revision (ID 1)
    assert RR._entry_name_for_revision_id(0x001) == '001'

    # Last revision in first pack (ID 15 = 0x00f)
    assert RR._entry_name_for_revision_id(0x00f) == '00f'

    # First revision in second pack (ID 16 = 0x010)
    assert RR._entry_name_for_revision_id(0x010) == '010'

    # Revision in second pack (ID 26 = 0x01a)
    assert RR._entry_name_for_revision_id(0x01a) == '01a'

    # Last revision in second pack (ID 31 = 0x01f)
    assert RR._entry_name_for_revision_id(0x01f) == '01f'

    # High revision ID
    assert RR._entry_name_for_revision_id(0x123456789ab) == '9ab'


def test_pack_filepath_for_revision_id_computes_correct_values() -> None:
    """Test computing pack file paths for revision IDs."""
    with xtempfile.TemporaryDirectory() as project_path:
        # First pack (revisions 0x000-0x00f)
        # Pack base ID is 0x000, so hex is '000000000000000'
        # Pack file is 00_.zip in directory 000/000/000/000/
        expected = os.path.join(
            project_path, 'revisions', '000', '000', '000', '000', '00_.zip')
        assert RR._body_pack_filepath_with(project_path, 0x001) == expected
        assert RR._body_pack_filepath_with(project_path, 0x00f) == expected

        # Second pack (revisions 0x010-0x01f)
        # Pack base ID is 0x010, so hex is '000000000000010'
        # Pack file is 01_.zip in directory 000/000/000/000/ (same as first pack)
        expected = os.path.join(
            project_path, 'revisions', '000', '000', '000', '000', '01_.zip')
        assert RR._body_pack_filepath_with(project_path, 0x010) == expected
        assert RR._body_pack_filepath_with(project_path, 0x01a) == expected
        assert RR._body_pack_filepath_with(project_path, 0x01f) == expected

        # 256th pack (revisions 0xff0-0xfff)
        # Pack base ID is 0xff0, so hex is '000000000000ff0'
        # Pack file is ff_.zip in directory 000/000/000/000/ (same directory level)
        expected = os.path.join(
            project_path, 'revisions', '000', '000', '000', '000', 'ff_.zip')
        assert RR._body_pack_filepath_with(project_path, 0xff0) == expected
        assert RR._body_pack_filepath_with(project_path, 0xfff) == expected

        # High revision ID pack
        # Revision 0x123456789ab as 15-char hex is '0000123456789ab'
        # Pack base ID for revision 0x123456789ab is 0x123456789a0
        # Pack file is 9a_.zip in directory 000/012/345/678/
        expected = os.path.join(
            project_path, 'revisions', '000', '012', '345', '678', '9a_.zip')
        assert RR._body_pack_filepath_with(project_path, 0x123456789ab) == expected
