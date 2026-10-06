"""CODEX_HOME resolution and the refusal list (DESIGN.md §3, §7.2). Stdlib only, Python >= 3.11.

Precedence: --codex-home PATH > $CODEX_HOME > ~/.codex. resolve() returns {"path", "real", "source"
(flag|env|default), "created" (bool), "warn" [lines]} or raises CodexHomeError, before anything is
created, for:
- a path with BAD_PATH_CHARS (control characters, " ` $ \\) or ' (hook commands quote the stub path
  in single quotes), on the raw value and on the expanded one;
- a symlink before a '..' (the shell and the file system would disagree on the target);
- /, $HOME or a folder containing $HOME; a general-purpose folder (install_state HOME_EQUAL,
  SYSTEM_EQUAL); anything inside credentials or system folders (HOME_INSIDE, SYSTEM_INSIDE);
- anything inside ~/.claude or $CLAUDE_CONFIG_DIR, or containing ~/.claude;
- anything inside one of the given repository checkouts;
- the stacks' state, backup and cache roots under ${XDG_STATE_HOME:-~/.local/state};
- an explicit path (flag or env) that does not exist or is not a directory (Codex's own rule);
- a folder that is not writable by this user.
The default ~/.codex is created with mode 0700 when missing (created=True); an explicit path never is.

install_state.py (the Claude installer's engine) is loaded by file path from ../../lib, relative to
this file, never through sys.path; its HOME_INSIDE, SYSTEM_INSIDE, HOME_EQUAL, SYSTEM_EQUAL,
BAD_PATH_CHARS, expand_path, absolute_path, _inside and _same are reused unchanged. codex_state.py
hands over its own engine instance with use_engine().

Seeded-bug proofs (tests/mutations/codex_home.json; each turns tests/test_codex_home.py red):
drop the ~/.claude refusal; accept a "'" in the path; create an explicit CODEX_HOME that does not
exist; drop the backup-root refusal; create ~/.codex with the umask's mode instead of 0700.
"""
from __future__ import annotations

import importlib.util
import os

ENGINE_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                           "lib", "install_state.py")
STATE_NAMES = ("codex-agent-stack", "codex-agent-stack-backups", "claude-agent-stack",
               "claude-agent-stack-backups", "claude-agent-stack-cache")
_engine = None


class CodexHomeError(Exception):
    """An unsafe or unusable CODEX_HOME; the message says why."""


def load_engine(path=ENGINE_PATH):
    """install_state.py loaded by file path (CWE-427: never via sys.path)."""
    spec = importlib.util.spec_from_file_location("codex_install_state", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def use_engine(mod):
    global _engine
    _engine = mod


def engine():
    if _engine is None:
        use_engine(load_engine())
    return _engine


def state_root(env: dict, home: str) -> str:
    return env.get("XDG_STATE_HOME") or os.path.join(home, ".local", "state")


def default_backup_root(env: dict, home: str) -> str:
    return os.path.join(state_root(env, home), "codex-agent-stack-backups")


def default_state_dir(env: dict, home: str) -> str:
    return os.path.join(state_root(env, home), "codex-agent-stack")


def _bad_chars(p: str) -> bool:
    return "'" in p or bool(engine().BAD_PATH_CHARS.search(p))


def _expand(raw: str, home: str, cwd: str) -> tuple[str, str]:
    ist = engine()
    try:
        return ist.expand_path(raw, home, cwd), ist.absolute_path(raw, home, cwd)
    except ist.ConfigDirError as exc:
        raise CodexHomeError(str(exc).replace("hook commands", "hook commands Codex runs")) from None


def _check(path: str, real: str, home: str, env: dict, cwd: str, repos) -> None:
    ist = engine()
    rhome = ist._real(home)
    if path == "/" or real == "/" or ist._same(real, "/"):
        raise CodexHomeError("refusing / as CODEX_HOME")
    if ist._same(real, rhome) or ist._inside(rhome, real):
        raise CodexHomeError("refusing %s: it is your home folder or contains it" % path)
    for rel in ist.HOME_EQUAL:
        if ist._same(real, ist._real(os.path.join(home, rel))):
            raise CodexHomeError("refusing %s: a general-purpose folder, not a CODEX_HOME" % path)
    for p in ist.SYSTEM_EQUAL:
        if ist._same(real, ist._real(p)):
            raise CodexHomeError("refusing %s: a system folder" % path)
    claude = [os.path.join(home, ".claude")]
    if env.get("CLAUDE_CONFIG_DIR"):
        try:
            claude.append(ist.expand_path(env["CLAUDE_CONFIG_DIR"], home, cwd))
        except ist.ConfigDirError:
            pass
    for c in claude:
        if ist._inside(ist._real(c), real) or ist._inside(os.path.normpath(c), path):
            raise CodexHomeError("refusing %s: it contains the Claude config folder %s" % (path, c))
    inside = ([(os.path.join(home, rel), "credentials") for rel in ist.HOME_INSIDE]
              + [(p, "a system folder") for p in ist.SYSTEM_INSIDE]
              + [(c, "the Claude config folder") for c in claude]
              + [(os.path.join(state_root(env, home), n), "the stack's state or backups") for n in STATE_NAMES]
              + [(r, "a repository checkout (the installer copies from there)") for r in repos if r])
    for p, what in inside:
        if ist._inside(real, ist._real(p)) or ist._inside(path, os.path.normpath(p)):
            raise CodexHomeError("refusing %s: inside %s (%s)" % (path, p, what))


def resolve(flag: str | None, env: dict, home: str, cwd: str, repos: list[str]) -> dict:
    """Resolve and check CODEX_HOME (see the module docstring). flag None: --codex-home not given."""
    if flag is not None:
        if not flag:
            raise CodexHomeError("--codex-home needs a path")
        raw, source = flag, "flag"
    elif env.get("CODEX_HOME"):
        raw, source = env["CODEX_HOME"], "env"
    else:
        raw, source = os.path.join(home, ".codex"), "default"
    if _bad_chars(raw):
        raise CodexHomeError("the path contains a control character or one of ' \" ` $ \\ (they would "
                             "break the hook commands Codex runs): %r" % raw)
    path, raw_abs = _expand(raw, home, cwd)
    ist = engine()
    real = ist._real(path)
    if real != ist._real(raw_abs):
        raise CodexHomeError("%r goes through a symlink before a '..' (the shell would read it as %s, the "
                             "file system as %s): give the resolved path" % (raw, path, ist._real(raw_abs)))
    if _bad_chars(path) or _bad_chars(real):
        raise CodexHomeError("the resolved path %r contains a control character or one of ' \" ` $ \\"
                             % real)
    _check(path, real, home, env, cwd, repos)
    created = False
    if os.path.lexists(path) and not os.path.isdir(path):
        raise CodexHomeError("refusing %s: it exists and is not a directory" % path)
    if not os.path.isdir(path):
        if source != "default":
            raise CodexHomeError("%s does not exist: Codex needs an existing CODEX_HOME (create it first, "
                                 "or leave out %s to use ~/.codex)"
                                 % (path, "--codex-home" if source == "flag" else "CODEX_HOME"))
        try:
            os.mkdir(path, 0o700)
            os.chmod(path, 0o700)
        except OSError as exc:
            raise CodexHomeError("cannot create %s: %s" % (path, exc.strerror)) from None
        created = True
        real = ist._real(path)
    if not os.access(real, os.W_OK | os.X_OK):
        raise CodexHomeError("refusing %s: not writable by you" % path)
    warn = []
    env_home = env.get("CODEX_HOME") or ""
    if source == "flag" and env_home:
        try:
            same = ist._same(ist._real(ist.expand_path(env_home, home, cwd)), real)
        except ist.ConfigDirError:
            same = False
        if not same:
            warn.append("! CODEX_HOME=%s in this shell points elsewhere: a codex started from this shell "
                        "reads that folder, not %s" % (env_home, path))
    if source == "flag" and not ist._same(real, ist._real(os.path.join(home, ".codex"))) and not env_home:
        warn.append("! a non-default CODEX_HOME: Codex reads it only when CODEX_HOME is exported; add  "
                    "export CODEX_HOME='%s'  to your shell's startup file" % path)
    if real != path:
        warn.append("! %s is reached through a symlink (it resolves to %s): see allow_symlinked_codex_home "
                    "(DESIGN.md F18)" % (path, real))
    mode = os.stat(real).st_mode & 0o777
    if mode & 0o077:
        warn.append("! %s has mode %03o: other users can read it (auth.json lives there); chmod 700 is "
                    "recommended" % (path, mode))
    return {"path": path, "real": real, "source": source, "created": created, "warn": warn}
