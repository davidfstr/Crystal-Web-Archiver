from functools import wraps


def partial2(func, *args, **kwargs):
    """
    Similar to functools.partial, but the wrapped function appears more
    like the original function.
    
    In particular a wrapped @capture_crashes_to_deco function will
    still appear to be a @capture_crashes_to_deco function, rather than
    a functools.partial function.
    """
    @wraps(func)
    def bound_func(*more_args, **more_kwargs):
        return func(*(args + more_args), **(kwargs | more_kwargs))  # cr-traceback: ignore
    return bound_func
