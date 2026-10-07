"""Optional hardened tier: build requirements.toml and the managed guard copy (DESIGN.md §4.5, §9 step 6).

OFF BY DEFAULT. MACHINE-WIDE: /etc/codex/requirements.toml changes EVERY Codex session on this
machine (every profile, the CLI, the IDE extension, the desktop app), not just the stack's profile
(F20). This module only writes into --out; installing is the user's step, as root.

Usage (one process; Python >= 3.11, stdlib only):
    requirements.py --codex-home CH --home H --src SRC --out DIR
                    [--etc-dir /etc/codex]
                    [--managed-dir "/Library/Application Support/claude-agent-stack/codex-hooks"]
                    [--state-dir D]

Writes:
- DIR/requirements.toml (toml_emit, loaded by path): `allowed_approval_policies`
  ["on-request","never"]; `allowed_sandbox_modes` ["read-only","workspace-write"];
  `allowed_permission_profiles` {"claude-agent-stack", ":workspace", ":read-only"} (ids missing
  from the map are denied, so `:danger-full-access` is refused); `allowed_web_search_modes`
  ["disabled"]; `allow_managed_hooks_only = false` (the profile's own hooks keep working);
  `[features] hooks = true`; `[permissions.filesystem] deny_read` = the credential set
  (permissions.py) with project-relative patterns anchored at $HOME; `[rules] prefix_rules` = the
  forbidden push and forge rules (convert_rules.py; requirements refuse `allow`); `[hooks]`
  `managed_dir` and one PreToolUse and one PermissionRequest group running
  `/bin/sh '<managed-dir>/codex-hook' <mode> --scope global`.
- DIR/managed-hooks/: a flat copy of SRC/codex_config/hooks/codex-hook, codex_guard.py and every
  file named in SRC/codex_config/hooks/SUPPORT_FILES (a missing file is an error), plus guard.json
  for the global scope (C's templates/guard.base.json + the paths of this machine).

Prints the MACHINE-WIDE warning and the root commands of DESIGN §9 step 6 for the user to run,
including a `/usr/bin/python3 -I` py_compile of the installed managed hooks (the copy ships no
__pycache__). If
<etc-dir>/requirements.toml already exists it is never replaced: a unified diff and the merge
instruction are printed instead of the install command for that file. Never runs sudo, never
writes outside DIR, never writes /etc (an --out inside /etc, the etc dir or the managed dir is
refused). Exit 0 on success, 1 on a build error, 2 on a usage error.

Key spellings verified against openai/codex rust-v0.160.1 (tests/fixtures/rules/README.md):
ConfigRequirementsToml fields, `[rules] prefix_rules` token tables, ManagedHooksRequirementsToml,
built-in profile ids `:workspace`/`:read-only` (protocol/src/models.rs) and `is_permission_allowed`
(missing id = denied). Unverified (probe needs): that managed hooks run from the managed dir with the
command as written; that `deny_read` globs under $HOME behave like the profile's (Linux needs
`glob_scan_max_depth`); `-g wheel` in the printed commands is macOS (Linux: `-g root`).

Seeded-bug proofs (tests/mutations/requirements.json, each turns test_requirements.py red): write
requirements.toml into the etc dir; drop auth.json from deny_read; keep printing the replace
command when /etc already has a file; set allow_managed_hooks_only = true; drop `--scope global`
from the managed hook command; stop refusing an --out inside the etc dir; allow
`:danger-full-access`.
"""
from __future__ import annotations

import argparse
import difflib
import importlib.util
import json
import os
import shlex
import shutil
import stat
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_ETC = "/etc/codex"
DEFAULT_MANAGED = "/Library/Application Support/claude-agent-stack/codex-hooks"
SYSTEM = ("/etc", "/private/etc", "/System", "/usr", "/bin", "/sbin", "/Library", "/dev",
          "/Applications")
_SHELL_BAD = set("'\"`$\\") | {chr(c) for c in range(32)} | {"\x7f"}
WARNING = ("MACHINE-WIDE: requirements.toml applies to EVERY Codex session on this machine (every "
           "profile, the CLI, the IDE extension and the desktop app), not just `codex --profile "
           "codex`. It is optional and off by default; root can always undo it.")


class BuildError(Exception):
    pass


def _load(name):
    spec = importlib.util.spec_from_file_location("codex_config_req_" + name,
                                                  os.path.join(HERE, name + ".py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _under(path, root):
    return path == root or path.startswith(root.rstrip("/") + "/")


def _real(path):
    """realpath of the longest existing ancestor + the rest (the path need not exist)."""
    head, tail = os.path.abspath(path), []
    while not os.path.exists(head) and os.path.dirname(head) != head:
        head, t = os.path.split(head)
        tail.append(t)
    return os.path.join(os.path.realpath(head), *reversed(tail))


def _read_nofollow(path):
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    except OSError as exc:
        raise BuildError("cannot read %s: %s" % (path, exc.strerror or exc)) from exc
    with os.fdopen(fd, "rb") as fh:
        if not stat.S_ISREG(os.fstat(fh.fileno()).st_mode):
            raise BuildError("%s is not a regular file" % path)
        return fh.read()


def _write(path, data, mode):
    tmp = path + ".tmp"
    if os.path.lexists(tmp):
        os.unlink(tmp)
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), mode)
    with os.fdopen(fd, "wb") as fh:
        fh.write(data)
    os.chmod(tmp, mode)
    os.replace(tmp, path)


def hook_command(managed_dir, mode):
    return "/bin/sh '%s' %s --scope global" % (os.path.join(managed_dir, "codex-hook"), mode)


def _rule_toml(rule):
    pattern = []
    for tok in rule["pattern"]:
        pattern.append({"any_of": list(tok)} if isinstance(tok, list) else {"token": tok})
    if rule["decision"] not in ("prompt", "forbidden"):
        raise BuildError("requirements.toml refuses decision %r" % rule["decision"])
    return {"decision": rule["decision"], "justification": rule["justification"],
            "pattern": pattern}


def build_doc(settings, ctx, managed_dir, perms, rules):
    cred = perms.credential_set(settings, ctx)
    deny = []
    for p in cred["paths"] + cred["globs"]:
        p = os.path.join(ctx["home"], p) if not os.path.isabs(p) else p
        if p not in deny:
            deny.append(p)
    forbidden = [_rule_toml(r) for r in rules.forbidden_push_forge(settings, ctx)]
    if not forbidden:
        raise BuildError("no forbidden push/forge rules were derived from settings.json")
    hooks = {"managed_dir": managed_dir}
    for event, mode in (("PreToolUse", "pre_tool_use"), ("PermissionRequest", "permission_request")):
        hooks[event] = [{"matcher": ".*", "hooks": [
            {"type": "command", "command": hook_command(managed_dir, mode), "timeout": 10}]}]
    return {
        "allowed_approval_policies": ["on-request", "never"],
        "allowed_sandbox_modes": ["read-only", "workspace-write"],
        "allowed_web_search_modes": ["disabled"],
        "allow_managed_hooks_only": False,
        "allowed_permission_profiles": {perms.PROFILE_NAME: True, ":workspace": True,
                                        ":read-only": True},
        "features": {"hooks": True},
        "permissions": {"filesystem": {"deny_read": deny}},
        "rules": {"prefix_rules": forbidden},
        "hooks": hooks,
    }


HEADER = """\
# claude-agent-stack: optional hardened tier (codex_config DESIGN.md §4.5). OFF BY DEFAULT.
# MACHINE-WIDE: this file applies to EVERY Codex session on this machine, not just the stack's
# profile. Generated by codex_config/lib/requirements.py; install it as root (see its output).
# allowed_permission_profiles: the built-in ids ":workspace" and ":read-only" are spelled as in
# openai/codex rust-v0.160.1 protocol/src/models.rs; ids missing from the map are denied, so
# ":danger-full-access" is refused (core/src/config/mod.rs is_permission_allowed).
# deny_read: the stack's credential set; project-relative patterns are anchored at $HOME.

"""


def guard_json(template, ctx, cred):
    out = dict(template)
    out.update({
        "schema": 1, "codex_home": ctx["codex_home"], "home": ctx["home"],
        "state_dir": ctx["state_dir"], "stack": ctx["stack"],
        "protected_roots": [ctx["codex_home"], os.path.join(ctx["home"], ".agents"),
                            ctx["state_dir"]],
        "credentials": cred,
        "toolsmith_wrapper": os.path.join(ctx["stack"], "bin", "stack-install"),
    })
    out.setdefault("caps", {})
    out.setdefault("image_max_px", 1920)
    return out


def guard_files(src):
    hooks = os.path.join(src, "codex_config", "hooks")
    files = [os.path.join(hooks, "codex-hook"), os.path.join(hooks, "codex_guard.py")]
    listing = _read_nofollow(os.path.join(hooks, "SUPPORT_FILES")).decode("utf-8")
    for raw in listing.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        rel = line if "/" in line else "dot-claude/hooks/" + line
        parts = rel.split("/")
        if (os.path.isabs(rel) or ".." in parts or len(parts) != 3
                or parts[:2] != ["dot-claude", "hooks"] or not parts[2]):
            raise BuildError("SUPPORT_FILES: %r is not dot-claude/hooks/<name>" % line)
        files.append(os.path.join(src, rel))
    names = [os.path.basename(f) for f in files]
    dup = {n for n in names if names.count(n) > 1 or n == "guard.json"}
    if dup:
        raise BuildError("managed-hooks name clash: %s" % ", ".join(sorted(dup)))
    return files


# the managed-hooks/ copy ships no __pycache__: compiled once as root, for the interpreter the managed
# hooks run on (the stub's /usr/bin/python3), with the command INTERFACES §2 gives for the stack's own
PRECOMPILE = ("import py_compile,sys; [py_compile.compile(f, doraise=True, "
              "invalidation_mode=py_compile.PycInvalidationMode.CHECKED_HASH) for f in sys.argv[1:]]")


def run(argv, out_stream=sys.stdout):
    ap = argparse.ArgumentParser(prog="requirements.py", description=__doc__.split("\n")[0])
    ap.add_argument("--codex-home", required=True)
    ap.add_argument("--home", required=True)
    ap.add_argument("--src", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--etc-dir", default=DEFAULT_ETC)
    ap.add_argument("--managed-dir", default=DEFAULT_MANAGED)
    ap.add_argument("--state-dir")
    a = ap.parse_args(argv)
    for name in ("codex_home", "home", "src", "out", "etc_dir", "managed_dir", "state_dir"):
        v = getattr(a, name)
        if v is not None and (not os.path.isabs(v) or any(c in v for c in "\x00\n\r")):
            ap.error("--%s must be an absolute path" % name.replace("_", "-"))
    if any(c in _SHELL_BAD for c in a.managed_dir):
        ap.error("--managed-dir must not hold quotes, $, backquote, backslash or control characters")
    out = os.path.normpath(a.out)
    real_out = _real(out)
    for root in SYSTEM + (a.etc_dir, a.managed_dir):
        if _under(real_out, _real(root)) or _under(out, os.path.normpath(root)):
            raise BuildError("--out %s is inside %s: this generator never writes there" % (out, root))
    home = os.path.normpath(a.home)
    state = a.state_dir or os.path.join(os.environ.get("XDG_STATE_HOME") or
                                        os.path.join(home, ".local", "state"), "codex-agent-stack")
    ctx = {"codex_home": os.path.normpath(a.codex_home), "home": home,
           "stack": os.path.join(os.path.normpath(a.codex_home), "stack"),
           "state_dir": os.path.normpath(state)}

    toml_emit, perms, rules = _load("toml_emit"), _load("permissions"), _load("convert_rules")
    try:
        settings = json.loads(_read_nofollow(os.path.join(a.src, "dot-claude", "settings.json")))
        doc = build_doc(settings, ctx, a.managed_dir, perms, rules)
        cred = perms.credential_set(settings, ctx)
    except (perms.BuildError, rules.BuildError, ValueError) as exc:
        raise BuildError(str(exc)) from exc
    files = guard_files(a.src)
    template = json.loads(_read_nofollow(os.path.join(a.src, "codex_config", "templates",
                                                      "guard.base.json")))
    if not isinstance(template, dict):
        raise BuildError("templates/guard.base.json must hold a JSON object")
    blobs = [(os.path.basename(f), _read_nofollow(f)) for f in files]
    text = HEADER + toml_emit.dumps(doc)

    os.makedirs(out, mode=0o755, exist_ok=True)
    mh = os.path.join(out, "managed-hooks")
    if os.path.islink(mh) or (os.path.exists(mh) and not os.path.isdir(mh)):
        raise BuildError("%s exists and is not a folder" % mh)
    if os.path.isdir(mh):
        shutil.rmtree(mh)
    os.mkdir(mh, 0o755)
    for name, data in blobs:
        _write(os.path.join(mh, name), data, 0o755 if name == "codex-hook" else 0o644)
    gj = json.dumps(guard_json(template, ctx, cred), indent=2, sort_keys=True) + "\n"
    _write(os.path.join(mh, "guard.json"), gj.encode("utf-8"), 0o644)
    req_path = os.path.join(out, "requirements.toml")
    _write(req_path, text.encode("utf-8"), 0o644)

    etc_file = os.path.join(a.etc_dir, "requirements.toml")
    q = shlex.quote
    p = lambda s: print(s, file=out_stream)  # noqa: E731
    p(WARNING)
    p("Wrote %s and %s/ (%d files)." % (req_path, mh, len(blobs) + 1))
    p("To install, run as root (review the files first):")
    p("  sudo install -d -o root -g wheel -m 0755 %s %s" % (q(a.etc_dir), q(a.managed_dir)))
    p("  sudo install -o root -g wheel -m 0755 %s/* %s" % (q(mh), q(a.managed_dir.rstrip("/") + "/")))
    p("  sudo /usr/bin/python3 -I -c %s %s/*.py" % (q(PRECOMPILE), q(a.managed_dir.rstrip("/"))))
    if os.path.lexists(etc_file):
        try:
            old = _read_nofollow(etc_file).decode("utf-8", "replace")
        except BuildError as exc:
            old = "# (unreadable: %s)\n" % exc
        diff = difflib.unified_diff(old.splitlines(True), text.splitlines(True),
                                    fromfile=etc_file, tofile=req_path)
        p("%s already exists and is NEVER replaced by this tool. Differences:" % etc_file)
        for line in diff:
            out_stream.write(line if line.endswith("\n") else line + "\n")
        p("Merge the keys you want from %s into %s by hand (as root), keeping your own keys." %
          (req_path, etc_file))
    else:
        p("  sudo install -o root -g wheel -m 0644 %s %s" % (q(req_path), q(etc_file)))
    p("Then check /debug-config in `codex --profile codex`. " + WARNING)
    return 0


def main(argv=None):
    try:
        return run(sys.argv[1:] if argv is None else argv)
    except BuildError as exc:
        print("requirements.py: %s" % exc, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
