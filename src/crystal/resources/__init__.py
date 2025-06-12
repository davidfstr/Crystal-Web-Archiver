import codecs
import crystal.resources as resources
from crystal.util.xos import is_windows
import importlib.resources
import os
import sys
from typing import BinaryIO, TextIO


def open_binary(filename: str) -> BinaryIO:
    """
    Opens a binary data file from this directory for reading.
    
    On Windows, the data file must be explicitly listed in setup.py
    in the data_files section to be accessible by this function.
    
    Raises:
    * FileNotFoundException
    """
    if is_windows():
        return open(get_filepath(filename), 'rb')
    else:
        return importlib.resources.files(resources).joinpath(filename).open('rb')


def open_text(filename: str, *, encoding: str='utf-8', errors='strict') -> TextIO:
    """
    Opens a text data file from this directory for reading.
    
    On Windows, the data file must be explicitly listed in setup.py
    in the data_files section to be accessible by this function.
    
    Raises:
    * FileNotFoundException
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


def get_filepath(filename: str) -> str:
    """Returns the path to a data file from this directory."""
    if getattr(sys, 'frozen', None) == 'windows_exe':
        filepath_components = (
            [os.path.dirname(sys.executable)] +
            ['lib'] +
            resources.__name__.split('.') +
            [filename]
        )
    else:
        filepath_components = (
            [os.path.dirname(resources.__file__)] +
            [filename]
        )
    return os.path.join(*filepath_components)
