from crystal import resources
import os.path


def test_appicon_copies_remain_in_sync() -> None:
    with open(os.path.join('setup', 'media', 'AppIconWin.ico'), 'rb') as file1:
        data1 = file1.read()
    with resources.open_binary('appicon.ico') as file2:
        data2 = file2.read()
    assert data1 == data2


def test_docicon_copies_remain_in_sync() -> None:
    with open(os.path.join('setup', 'media', 'DocIconWin.ico'), 'rb') as file1:
        data1 = file1.read()
    with resources.open_binary('docicon.ico') as file2:
        data2 = file2.read()
    assert data1 == data2
