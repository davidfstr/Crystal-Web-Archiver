from crystal.resources import open_binary
import os.path


def test_appicon_copies_remain_in_sync() -> None:
    with open(os.path.join('setup', 'media', 'AppIconWin.ico'), 'rb') as file1:
        data1 = file1.read()
    with open_binary('appicon.ico') as file2:
        data2 = file2.read()
    assert data1 == data2
