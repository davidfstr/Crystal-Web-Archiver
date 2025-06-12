

def try_get_int(params: dict[str, list[str]], key: str) -> int | None:
    str_value = try_get_str(params, key)
    if str_value is None:
        return None
    try:
        return int(str_value)
    except ValueError:
        return None


def try_get_str(params: dict[str, list[str]], key: str) -> str | None:
    values = params.get(key)
    if values is None:
        return None
    if len(values) != 1:
        return None
    return values[0]
