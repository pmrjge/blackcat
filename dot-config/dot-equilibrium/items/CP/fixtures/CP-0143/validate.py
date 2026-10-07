"""Input validation helpers. Every validator raises ValueError for bad
values and TypeError for values of the wrong type."""


def parse_bool(value):
    """Accept bool, or the strings true/false/yes/no/on/off/1/0 (any case,
    surrounding whitespace ignored). Other strings: ValueError. Other types: TypeError."""
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        raise TypeError("expected bool or str")
    text = value.strip().lower()
    if text in ("true", "yes", "on", "1"):
        return True
    if text in ("false", "no", "off", "0"):
        return False
    raise ValueError("not a boolean: " + value)


def parse_port(value):
    """Integer port 1..65535 from an int or a decimal string."""
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise TypeError("expected int or str")
    try:
        port = int(value)
    except ValueError:
        raise ValueError("not a number: " + value)
    if port < 1 or port > 65535:
        raise ValueError("port out of range")
    return port


def check_username(name):
    """3-16 characters, letters/digits/underscore, must not start with a digit."""
    if not isinstance(name, str):
        raise TypeError("expected str")
    if len(name) < 3 or len(name) > 16:
        raise ValueError("bad length")
    if name[0].isdigit():
        raise ValueError("starts with digit")
    for ch in name:
        if not (ch.isalnum() and ch.isascii()) and ch != "_":
            raise ValueError("bad character")
    return name


def check_email(addr):
    """Very small check: exactly one '@', non-empty local part, domain with a
    dot that is neither first nor last, no spaces."""
    if not isinstance(addr, str):
        raise TypeError("expected str")
    if " " in addr or addr.count("@") != 1:
        raise ValueError("bad address")
    local, domain = addr.split("@")
    if not local or "." not in domain:
        raise ValueError("bad address")
    if domain.startswith(".") or domain.endswith("."):
        raise ValueError("bad domain")
    return addr


def collect_errors(checks, errors=None):
    """Run (callable, argument) pairs; append str(exception) of each
    ValueError to `errors` (a fresh list when None) and return it."""
    if errors is None:
        errors = []
    for fn, arg in checks:
        try:
            fn(arg)
        except ValueError as exc:
            errors.append(str(exc))
    return errors


def clamp(value, lo, hi):
    """Limit value to [lo, hi]; ValueError when lo > hi."""
    if lo > hi:
        raise ValueError("lo > hi")
    if value < lo:
        return lo
    if value > hi:
        return hi
    return value
