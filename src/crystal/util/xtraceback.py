import io
import os.path
import traceback
from traceback import FrameSummary, StackSummary, TracebackException

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


def format_exception_for_ui_user(exc: BaseException) -> str:
    """
    Formats an exception's traceback nicely for a UI user.
    
    Example output:
        ValueError: Expected a non-negative float but got -1.0
          at <console>:2 in sqrt
          at <console>:1 in <module>
    """
    # Try to extract traceback saved by _extract_bulkhead_traceback()
    full_traceback = getattr(exc, '__full_traceback__', Ellipsis)
    if full_traceback is Ellipsis:
        full_traceback = traceback.extract_tb(exc.__traceback__)
    
    exception_str = io.StringIO()
    print(f'{type(exc).__name__}: {str(exc)}', file=exception_str)
    for fs in reversed(_filter_stack_summary(full_traceback)):
        print(f'  at {fs.filename}:{fs.lineno} in {fs.name}', file=exception_str)
    return exception_str.getvalue()


def format_exception_for_terminal_user(exc: BaseException) -> str:
    """
    Formats an exception's traceback nicely for a terminal user.
    
    Example output:
        Traceback (most recent call last):
          File "<console>", line 1, in <module>
          File "<console>", line 2, in sqrt
        ValueError: Expected a non-negative float but got -1.0
    """
    te = TracebackException(type(exc), exc, exc.__traceback__, compact=True)
    te.stack = _filter_stack_summary(te.stack)
    return ''.join(list(te.format(chain=True)))  # type: ignore[call-arg]


def _filter_stack_summary(ss: StackSummary) -> StackSummary:
    """
    Cleans up the provided StackSummary, returning a new StackSummary.
    
    Currently takes the following actions:
    - Removes frames marked with "# cr-traceback: ignore"
    - Rewrites Python stdlib filepaths to be shorter
    """
    new_frame_summaries = []
    for fs in ss:
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
        # HACK: Modify in place. More reliable than trying to create a modified
        #       FrameSummary object from scratch because FrameSummary has several
        #       important private fields that StackSummary.format_frame_summary()
        #       depends on. These private fields are hard to identify reliably
        #       and copy to a new FrameSummary.
        fs.filename = short_filepath
        new_frame_summaries.append(fs)
    return StackSummary.from_list(new_frame_summaries)
