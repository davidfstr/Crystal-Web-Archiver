import io
import os.path
import traceback

_CRYSTAL_PACKAGE_PARENT_DIRPATH = os.path.abspath(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

# TODO: Locate the stdlib with a more-reliable method,
#       such as `sysconfig.get_paths().get('stdlib')`.
#       
#       The `os.__file__` method below does not work when Python is running
#       inside a frozen Windows .exe file.
_PYTHON_STDLIB_PARENT_DIRPATH = (
    os.path.abspath(os.path.dirname(os.__file__))
    if hasattr(os, '__file__')
    else None
)


def format_exception_for_user(exc: BaseException) -> str:
    # Try to extract traceback saved by _extract_bulkhead_traceback()
    full_traceback = getattr(exc, '__full_traceback__', Ellipsis)
    if full_traceback is Ellipsis:
        full_traceback = traceback.extract_tb(exc.__traceback__)
    
    exception_str = io.StringIO()
    print(f'{type(exc).__name__}: {str(exc)}', file=exception_str)
    for fs in reversed(full_traceback):
        if '# cr-traceback: ignore' in (fs.line or ''):
            # Don't print frames marked as uninteresting
            continue
        if fs.filename.startswith(_CRYSTAL_PACKAGE_PARENT_DIRPATH):
            short_filepath = os.path.relpath(fs.filename, start=_CRYSTAL_PACKAGE_PARENT_DIRPATH)
        elif (_PYTHON_STDLIB_PARENT_DIRPATH is not None and 
                fs.filename.startswith(_PYTHON_STDLIB_PARENT_DIRPATH)):
            short_filepath = os.path.relpath(fs.filename, start=_PYTHON_STDLIB_PARENT_DIRPATH)
        else:
            short_filepath = fs.filename
        print(f'  at {short_filepath}:{fs.lineno} in {fs.name}', file=exception_str)
    
    return exception_str.getvalue()
