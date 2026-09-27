"""Run agent_guard.main() with selected functions wrapped in a sleep, to widen race windows.

usage: guard_race_main.py <path/to/agent_guard.py> '<json patch>' [hook args...]
patch: {"<function name>": {"before": seconds, "after": seconds}, ...}
The hook file itself is not modified; the module is imported and its globals are rebound.
"""
import importlib.util
import json
import sys
import time

path, spec = sys.argv[1], json.loads(sys.argv[2])
mod_spec = importlib.util.spec_from_file_location("agent_guard", path)
g = importlib.util.module_from_spec(mod_spec)
mod_spec.loader.exec_module(g)


def wrap(fn, before=0.0, after=0.0):
    def inner(*a, **k):
        if before:
            time.sleep(before)
        r = fn(*a, **k)
        if after:
            time.sleep(after)
        return r
    return inner


for name, cfg in spec.items():
    setattr(g, name, wrap(getattr(g, name), cfg.get("before", 0), cfg.get("after", 0)))

sys.exit(g.main([path] + sys.argv[3:]))
