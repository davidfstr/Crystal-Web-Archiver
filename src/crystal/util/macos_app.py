import sys


def set_application_menu_name(app_name: str) -> None:
    """Changes the title of the application menu on macOS."""
    if sys.platform != 'darwin':
        raise ValueError('Not supported on this OS')
    
    try:
        import ctypes
        import ctypes.util
        
        # Load the Foundation framework
        foundation_path = ctypes.util.find_library('Foundation')
        if foundation_path is None:
            print('Warning: Could not find Foundation framework', file=sys.stderr)
            return
        foundation = ctypes.cdll.LoadLibrary(foundation_path)
        
        # Load the objc library
        objc_path = ctypes.util.find_library('objc')
        if objc_path is None:
            print('Warning: Could not find objc library', file=sys.stderr)
            return
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
        
        # Get main bundle
        NSBundle = objc.objc_getClass(b'NSBundle')
        mainBundle_sel = objc.sel_registerName(b'mainBundle')
        mainBundle = objc_msgSend(NSBundle, mainBundle_sel)
        
        # Get the info dictionary
        infoDictionary_sel = objc.sel_registerName(b'infoDictionary')
        infoDict = objc_msgSend(mainBundle, infoDictionary_sel)
        
        # Create NSString for the key and value
        NSString = objc.objc_getClass(b'NSString')
        stringWithUTF8String_sel = objc.sel_registerName(b'stringWithUTF8String:')
        objc_msgSend_str = objc.objc_msgSend
        objc_msgSend_str.restype = ctypes.c_void_p
        objc_msgSend_str.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_char_p]
        cfBundleNameKey = objc_msgSend_str(NSString, stringWithUTF8String_sel, b'CFBundleName')
        appNameNSString = objc_msgSend_str(NSString, stringWithUTF8String_sel, app_name.encode('utf-8'))
        
        # Set CFBundleName in the info dictionary
        setObject_forKey_sel = objc.sel_registerName(b'setObject:forKey:')
        objc_msgSend_set = objc.objc_msgSend
        objc_msgSend_set.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]
        objc_msgSend_set(infoDict, setObject_forKey_sel, appNameNSString, cfBundleNameKey)
    
    except Exception as e:
        print(f'Warning: Failed to set application name: {e}', file=sys.stderr)


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
        appkit = ctypes.cdll.LoadLibrary(appkit_path)
        
        # Load the objc library
        objc_path = ctypes.util.find_library('objc')
        if objc_path is None:
            print('Warning: Could not find objc library', file=sys.stderr)
            return
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
