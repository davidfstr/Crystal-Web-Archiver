import codecs
import crystal.tests.test_data as test_data
from crystal.util.xos import is_windows
import importlib.resources
import os
import sys
from typing import BinaryIO, TextIO


def open_binary(filename: str) -> BinaryIO:
    """
    Opens a binary data file from this directory.
    
    On Windows, the data file must be explicitly listed in setup.py
    in the data_files section to be accessible by this function.
    """
    if is_windows():
        if getattr(sys, 'frozen', None) == 'windows_exe':
            filepath_components = (
                [os.path.dirname(sys.executable)] +
                ['lib'] + 
                test_data.__name__.split('.') + 
                [filename]
            )
        else:
            filepath_components = (
                [os.path.dirname(test_data.__file__)] +
                [filename]
            )
        return open(os.path.join(*filepath_components), 'rb')
    else:
        return importlib.resources.open_binary(test_data, filename)


def open_text(filename: str, *, encoding: str='utf-8', errors='strict') -> TextIO:
    """
    Opens a text data file from this directory.
    
    On Windows, the data file must be explicitly listed in setup.py
    in the data_files section to be accessible by this function.
    """
    # NOTE: The following implementation is based on codecs.open()
    file = open_binary(filename)
    try:
        info = codecs.lookup(encoding)
        srw = codecs.StreamReaderWriter(file, info.streamreader, info.streamwriter, errors)
        srw.encoding = encoding  # type: ignore[misc]
        return srw
    except:
        file.close()
        raise
