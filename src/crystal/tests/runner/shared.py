def normalize_test_names(raw_test_names: list[str]) -> list[str]:
    """
    Normalize test names from various formats into the canonical format.
    
    Handles these input formats:
    - crystal.tests.test_workflows (module)
    - crystal.tests.test_workflows.test_function (function)
    - crystal.tests.test_workflows::test_function (pytest-style function)
    - src/crystal/tests/test_workflows.py (file path)
    - test_workflows (unqualified module)
    - test_function (unqualified function)
    
    Raises:
    * ValueError -- if a test name cannot be resolved to a valid module or function.
    """
    from crystal.tests.index import TEST_FUNCS
    
    if not raw_test_names:
        return []
    
    # Build sets of available modules and functions
    available_modules = set()
    available_functions = set()
    for test_func in TEST_FUNCS:
        module_name = test_func.__module__
        func_name = test_func.__name__
        available_modules.add(module_name)
        available_functions.add(f'{module_name}.{func_name}')
    
    normalized = []
    for raw_name in raw_test_names:
        candidates = []
        
        # Handle pytest-style function notation (::)
        if '::' in raw_name:
            parts = raw_name.split('::', 1)
            if len(parts) == 2:
                (module_part, func_part) = parts
                
                # Convert module part if it's a file path
                if module_part.endswith('.py'):
                    module_part = module_part.replace('/', '.').replace('\\', '.')
                    if module_part.startswith('src.'):
                        module_part = module_part[len('src.'):]
                    if module_part.endswith('.py'):
                        module_part = module_part[:-len('.py')]
                
                candidates.append(f'{module_part}.{func_part}')
        
        # Handle file path notation
        elif raw_name.endswith('.py'):
            file_path = raw_name.replace('/', '.').replace('\\', '.')
            if file_path.startswith('src.'):
                file_path = file_path[len('src.'):]
            if file_path.endswith('.py'):
                file_path = file_path[:-len('.py')]
            candidates.append(file_path)
        
        # Handle unqualified names (try to match against available modules/functions)
        elif '.' not in raw_name:
            # Try to match as unqualified module
            for module in available_modules:
                if module.endswith(f'.{raw_name}'):
                    candidates.append(module)
            
            # Try to match as unqualified function
            for func in available_functions:
                if func.endswith(f'.{raw_name}'):
                    candidates.append(func)
        
        # Handle already qualified names
        else:
            candidates.append(raw_name)
        
        # Gather valid candidates
        valid_candidates = []
        for candidate in candidates:
            if candidate in available_modules or candidate in available_functions:
                valid_candidates.append(candidate)
        
        # Any valid candidate? Use them.
        if valid_candidates:
            normalized.extend(valid_candidates)
            continue
        
        # No valid candidates found
        closest_matches = []
        for candidate in candidates:
            # Find close matches in available modules/functions
            for available in sorted(available_modules | available_functions):
                if candidate.lower() in available.lower() or available.lower() in candidate.lower():
                    closest_matches.append(available)
        
        error_msg = f'Test not found: {raw_name}'
        if closest_matches:
            error_msg += f'\n\nDid you mean one of: {", ".join(sorted(set(closest_matches)))}'
        else:
            error_msg += f'\n\nAvailable test modules: {available_modules_str(available_modules)}'
        raise ValueError(error_msg)
    
    return normalized


def available_modules_str(available_modules: set[str]) -> str:
    return ', '.join(sorted(available_modules)).replace('crystal.tests.', '')
