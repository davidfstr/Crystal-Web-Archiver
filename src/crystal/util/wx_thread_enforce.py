from functools import wraps


# === Wrap ===

def wrap(obj):
    if isinstance(obj, type):
        if getattr(obj, '__module__', '').startswith('wx.'):
            # Wrap wx class
            return wrap_class(obj)
        else:
            # Passthru non-wx class
            return obj
    
    if callable(obj):
        if getattr(obj, '__module__', '').startswith('wx.'):
            # Wrap wx function
            return wrap_function(obj)
        else:
            # Passthru non-wx function
            return obj
    
    # Passthru unknown type of object
    return obj


def wrap_class(cls):
    class GuardMeta(type):
        def __instancecheck__(self, instance):
            return (
                isinstance(instance, cls) or 
                super().__instancecheck__(instance)
            )
    
    # TODO: See whether wraps() actually works here
    #@wraps(cls)
    class ClassGuard(metaclass=GuardMeta):
        def __init__(self, *args, **kwargs) -> None:
            print(f'ClassGuard: creating a {cls.__name__}')
            self._cr_guarded = cls(*unwrap_tuple(args), **unwrap_dict_values(kwargs))
        
        def __getattr__(self, name):
            print(f'FIXME: ClassGuard: {cls.__name__}: get {name}')
            # TODO: Wrap any returned bound methods -- FIXME
            return wrap(getattr(self._cr_guarded, name))
    
    return ClassGuard


def wrap_function(func):
    # TODO: Actually use @wraps later. Useful for debugging to not use initially.
    #@wraps(func)
    def func_guard(*args, **kwargs):
        print(f'func_guard: calling {func.__name__}')
        # TODO: Wrap return value
        return func(*unwrap_tuple(args), **unwrap_dict_values(kwargs))
    return func_guard


# === Unwrap ===

def unwrap(obj):
    # Unwrap ClassGuard instance
    return getattr(obj, '_cr_guarded', obj)


def unwrap_tuple(t):
    return tuple([unwrap(item) for item in t])


def unwrap_dict_values(d):
    return {
        key: unwrap(value)
        for (key, value) in
        d.items()
    }
