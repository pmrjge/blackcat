"""Configuration dict helpers."""


def deep_merge(base, override):
    """Return a new dict: keys of `override` win; nested dicts are merged
    recursively; neither argument is modified."""
    out = {}
    for key, value in base.items():
        out[key] = deep_merge(value, {}) if isinstance(value, dict) else value
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = deep_merge(out[key], value)
        elif isinstance(value, dict):
            out[key] = deep_merge({}, value)
        else:
            out[key] = value
    return out


def get_path(cfg, path, default=None):
    """Look up 'a.b.c' in nested dicts; `default` when any step is missing."""
    node = cfg
    for part in path.split("."):
        if not isinstance(node, dict) or part not in node:
            return default
        node = node[part]
    return node


def set_path(cfg, path, value):
    """Set 'a.b.c' creating intermediate dicts; returns cfg. A non-dict in
    the way raises ValueError."""
    parts = path.split(".")
    node = cfg
    for part in parts[:-2]:
        child = node.setdefault(part, {})
        if not isinstance(child, dict):
            raise ValueError("not a mapping: " + part)
        node = child
    node[parts[-1]] = value
    return cfg


def flatten(cfg, prefix="", out=None):
    """{'a': {'b': 1}} -> {'a.b': 1}; empty nested dicts are dropped."""
    if out is None:
        out = {}
    for key, value in cfg.items():
        name = prefix + key
        if isinstance(value, dict):
            flatten(value, name + ".", out)
        else:
            out[name] = value
    return out


def diff_keys(a, b):
    """Sorted flattened keys whose value differs between a and b (including
    keys present in only one of them)."""
    fa, fb = flatten(a), flatten(b)
    keys = set(fa) | set(fb)
    return sorted(k for k in keys if fa.get(k, object()) != fb.get(k, object()))


def with_defaults(cfg, defaults=None):
    """cfg merged over defaults (deep); `defaults` of None means empty."""
    if defaults is None:
        defaults = {}
    return deep_merge(defaults, cfg)
