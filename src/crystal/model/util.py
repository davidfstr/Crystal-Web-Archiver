# ------------------------------------------------------------------------------
# Utility

def _resolve_proxy(maybe_proxy: object) -> object:
    from crystal.shell import _Proxy
    if isinstance(maybe_proxy, _Proxy):
        return maybe_proxy._value
    else:
        return maybe_proxy


# ------------------------------------------------------------------------------
