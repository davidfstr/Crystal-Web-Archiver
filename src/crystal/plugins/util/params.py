from typing import Dict, List, Optional


def try_get_int(params: Dict[str, List[str]], key: str) -> Optional[int]:
    str_value = try_get_str(params, key)
    if str_value is None:
        return None
    try:
        return int(str_value)
    except ValueError:
        return None


def try_get_str(params: Dict[str, List[str]], key: str) -> Optional[str]:
    values = params.get(key)
    if values is None:
        return None
    if len(values) != 1:
        return None
    return values[0]
