import sys


def bring_app_to_front() -> None:
    """Brings the current application to the front on macOS."""
    if sys.platform != 'darwin':
        raise ValueError('Not supported on this OS')
    
    try:
        import ctypes
        import ctypes.util
        
        # Load the AppKit framework
        appkit_path = ctypes.util.find_library('AppKit')
        if appkit_path is None:
            print('Warning: Could not find AppKit framework', file=sys.stderr)
            return
        objc_path = ctypes.util.find_library('objc')
        if objc_path is None:
            print('Warning: Could not find objc library', file=sys.stderr)
            return
        
        appkit = ctypes.cdll.LoadLibrary(appkit_path)
        objc = ctypes.cdll.LoadLibrary(objc_path)
        
        # Define objc_getClass to lookup Objective-C classes
        objc.objc_getClass.restype = ctypes.c_void_p
        objc.objc_getClass.argtypes = [ctypes.c_char_p]
        
        # Define sel_registerName to lookup Objective-C selectors
        objc.sel_registerName.restype = ctypes.c_void_p
        objc.sel_registerName.argtypes = [ctypes.c_char_p]
            
        # Define objc_msgSend for calling Objective-C methods
        objc_msgSend = objc.objc_msgSend
        objc_msgSend.restype = ctypes.c_void_p
        objc_msgSend.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        
        # Get the shared application instance
        NSApplication = objc.objc_getClass(b'NSApplication')
        sharedApplication = objc.sel_registerName(b'sharedApplication')
        app = objc_msgSend(NSApplication, sharedApplication)
        
        # Activate the application, ignoring other apps
        activateIgnoringOtherApps = objc.sel_registerName(b'activateIgnoringOtherApps:')
        objc_msgSend_bool = objc.objc_msgSend
        objc_msgSend_bool.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_bool]
        objc_msgSend_bool(app, activateIgnoringOtherApps, True)
        
    except Exception as e:
        print(f'Warning: Failed to bring application to front: {e}', file=sys.stderr)
