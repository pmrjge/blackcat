"""Shared file helpers of the stack's hooks and installer (stdlib only, Python 3.8+, POSIX).

Imported by agent_guard.py, stack_usage.py, stack_limits.py, stack_fanout.py, stack_sched_refresh.py
(beside them in hooks/) and lib/install_state.py (from the repo). One copy of: reading a JSON object
that may be missing or damaged, replacing a file atomically, and the UTC second-precision timestamp.
"""
import json
import os
import time


def read_json(path, default=None, limit=None):
    """The JSON object (a dict) in `path`; `default` when the file is missing or unreadable, is not
    UTF-8 JSON, holds another type, nests too deeply, or has more than `limit` bytes."""
    try:
        with open(path, "rb") as f:
            raw = f.read() if limit is None else f.read(limit + 1)
        if limit is not None and len(raw) > limit:
            return default
        obj = json.loads(raw.decode("utf-8"))
    except (OSError, ValueError, RecursionError):   # ValueError covers UnicodeDecodeError
        return default
    return obj if isinstance(obj, dict) else default


def write_atomic(path, data, mode=0o600, fsync=False):
    """Replace `path` with the bytes `data`: a fresh temporary file beside it (O_EXCL, so never a
    symlink's target), then rename. Creates the parent directory; a symlink at `path` is replaced,
    not written through. On any failure the temporary file goes and `path` is unchanged."""
    folder = os.path.dirname(path)
    if folder:
        os.makedirs(folder, exist_ok=True)
    tmp = os.path.join(folder, ".tmp-%d-%s" % (os.getpid(), os.urandom(6).hex()))
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            if fsync:
                f.flush()
                os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def write_json_atomic(path, obj, mode=0o600, indent=None, sort_keys=False):
    """write_atomic of `obj` as JSON: compact by default; with `indent`, pretty with a final newline."""
    if indent is None:
        text = json.dumps(obj, sort_keys=sort_keys, separators=(",", ":"))
    else:
        text = json.dumps(obj, sort_keys=sort_keys, indent=indent) + "\n"
    write_atomic(path, text.encode("utf-8"), mode)


def now_iso(t=None):
    """UTC time `t` (default: now) as YYYY-MM-DDTHH:MM:SSZ."""
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() if t is None else t))
