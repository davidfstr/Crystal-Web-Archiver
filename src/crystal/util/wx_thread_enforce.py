from functools import wraps


# TODO: Use the real @fg_affinity decorator
def fg_affinity2(func, func_name=None):
    @wraps(func)
    def wrapper(*args, **kwargs):
        print(f'FIXME: fg_affinity2: calling {func_name or func.__name__}')
        #if f'{func_name or func.__name__}' == 'wx.core.App.Bind':
        #    print(f'FIXME: {args=}, {kwargs=}')
        return func(*args, **kwargs)  # cr-traceback: ignore
    return wrapper


# Wrap a few items for now, at import time
if True:
    import wx

    ## NOTE: wx.Button.__dict__['__init__'] does not exist, surprisingly
    #wx.Button.__init__ = fg_affinity2(wx.Button.__init__, 'wx.Button.__init__')
    
    def patch_class(cls):
        if cls.__name__ in [
                # Patching wx._core.EvtHandler.ProcessPendingEvents raises a C++ assertion.
                # Skip patching the entire class.
                'EvtHandler',
                # Patching wx._core.Window.??? causes top-level windows to not get set to
                # the correct size. Skip patching the entire class.
                'Window', 'WindowBase',
                # Don't patch common abstract base classes
                'Control', 'Object', 'PyEvent', 'Trackable',
                ]:
            return
        for attr_name in dir(cls):
            if attr_name.startswith('_') and not attr_name.startswith('__'):
                # Don't patch private attributes
                continue
            if attr_name in [
                    '__getattribute__',
                    'IsDisplayAvailable',  # wx.core.App.IsDisplayAvailable
                    
                    # Don't access attributes that print deprecation warnings as a side effect
                    'm_controlDown',  # KeyboardState.m_controlDown
                    'm_shiftDown',  # KeyboardState.m_shiftDown
                    'm_altDown',  # KeyboardState.m_altDown
                    'm_metaDown',  # KeyboardState.m_metaDown
                    ]:
                continue
            try:
                attr_value = getattr(cls, attr_name)
            except AttributeError:  # not found
                continue
            if isinstance(attr_value, type):
                # Don't patch nested types
                pass
            elif callable(attr_value):
                # Patch methods
                print(f'FIXME: patching: {cls.__module__}.{cls.__name__}.{attr_name}')
                try:
                    setattr(cls, attr_name, fg_affinity2(attr_value, f'{cls.__module__}.{cls.__name__}.{attr_name}'))
                except TypeError:  # cannot set 'X' attribute of immutable type 'Y'
                    continue
                
    
    def patch_module(mod):
        for attr_name in dir(mod):
            attr_value = getattr(mod, attr_name)
            if isinstance(attr_value, type):
                # Patch types
                patch_class(attr_value)
            elif callable(attr_value):
                if attr_value.__class__.__name__ == 'PyEventBinder':
                    # Don't patch PyEventBinder instances like wx.EVT_SIZE
                    # because that will cause them to fail isinstance checks
                    continue
                
                # Patch functions
                setattr(mod, attr_name, fg_affinity2(attr_value, f'{mod.__name__}.{attr_name}'))
    
    # Perform patching
    if False:  # works
        patch_class(wx.Button)
    if True:  # works
        for cls in wx.Button.__mro__:
            if not isinstance(cls, type):
                continue
            if cls.__module__ != 'wx' and not cls.__module__.startswith('wx.'):
                continue
            patch_class(cls)
    if False:  # too much; need to filter out more parts of wx
        patch_module(wx)
