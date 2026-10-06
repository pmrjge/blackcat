"""Shared helpers for the rules, permissions, requirements and execpolicy-mirror tests (part F).

Nothing here touches the real ~/.codex, ~/.agents, ~/.claude or /etc: contexts point at scratch
paths, and the only repository file read is dot-claude/settings.json (read-only input).
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

from conftest import FAKE_CODEX_DIR, REPO, VENDOR

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "rules"
FAKE_CODEX = FAKE_CODEX_DIR / "codex"
SETTINGS = REPO / "dot-claude" / "settings.json"
SCHEMA = json.loads((VENDOR / "config.schema.json").read_text())


def settings() -> dict:
    return json.loads(SETTINGS.read_text())


def ctx_for(home: Path, codex_home: Path | None = None) -> dict:
    home = Path(home)
    ch = Path(codex_home) if codex_home else home / ".codex"
    return {"codex_home": str(ch), "home": str(home), "stack": str(ch / "stack"),
            "state_dir": str(home / ".local" / "state" / "codex-agent-stack"),
            "profile_name": "codex", "uv": "uv", "skills_root": str(home / ".agents" / "skills")}


def codex_env(extra: dict | None = None) -> dict:
    """Environment for running the fake codex: the mirror runs under this interpreter."""
    env = dict(os.environ)
    env["FAKE_CODEX_PYTHON"] = sys.executable
    env.update(extra or {})
    return env


def execpolicy(rules, *cmd, flags=(), env=None):
    """Run `codex execpolicy check` through the fake CLI; returns (exit code, stdout, stderr)."""
    argv = [str(FAKE_CODEX), "execpolicy", "check"]
    for r in ([rules] if isinstance(rules, (str, Path)) else rules):
        argv += ["--rules", str(r)]
    argv += list(flags) + list(cmd)
    p = subprocess.run(argv, capture_output=True, text=True, env=env or codex_env(), timeout=60)
    return p.returncode, p.stdout, p.stderr


def decision(rules, *cmd, flags=("--resolve-host-executables", "--")):
    rc, out, err = execpolicy(rules, *cmd, flags=flags)
    assert rc == 0, err
    return json.loads(out).get("decision")


# ------------------------------------------------------------------ a small JSON-schema checker


def _resolve(node):
    while "$ref" in node:
        node = SCHEMA["definitions"][node["$ref"].rsplit("/", 1)[1]]
    return node


def schema_errors(value, node, path="$"):
    """Errors of `value` against a schema node of the vendored config.schema.json (the subset of
    JSON Schema it uses: $ref, type, enum, oneOf/anyOf/allOf, properties, additionalProperties,
    items, required)."""
    node = _resolve(node)
    errs = []
    if "allOf" in node:
        for sub in node["allOf"]:
            errs += schema_errors(value, sub, path)
    for key in ("oneOf", "anyOf"):
        if key in node:
            ok = [sub for sub in node[key] if not schema_errors(value, sub, path)]
            if not ok or (key == "oneOf" and len(ok) > 1):
                errs.append("%s: %r fails %s" % (path, value, key))
    if "enum" in node and value not in node["enum"]:
        errs.append("%s: %r not in %s" % (path, value, node["enum"]))
    t = node.get("type")
    types = {"object": dict, "string": str, "array": list, "boolean": bool, "integer": int}
    if isinstance(t, str) and t in types:
        if not isinstance(value, types[t]) or (t == "integer" and isinstance(value, bool)):
            return errs + ["%s: %r is not %s" % (path, value, t)]
    if isinstance(value, dict):
        props = node.get("properties", {})
        for k in node.get("required", []):
            if k not in value:
                errs.append("%s: missing %s" % (path, k))
        for k, v in value.items():
            if k in props:
                errs += schema_errors(v, props[k], "%s.%s" % (path, k))
            elif node.get("additionalProperties") is False:
                errs.append("%s: unknown key %s" % (path, k))
            elif isinstance(node.get("additionalProperties"), dict):
                errs += schema_errors(v, node["additionalProperties"], "%s.%s" % (path, k))
    if isinstance(value, list) and "items" in node:
        for i, v in enumerate(value):
            errs += schema_errors(v, node["items"], "%s[%d]" % (path, i))
    return errs


def definition(name):
    return SCHEMA["definitions"][name]


# --------------------------------------------------------------- vendored Rust struct key lists


def rust_fields(text: str, struct: str) -> set:
    """TOML key names of a Rust struct in a vendored source (serde `rename` honoured)."""
    m = re.search(r"pub struct %s \{(.*?)\n\}" % re.escape(struct), text, re.S)
    assert m, struct
    names, rename = set(), None
    for line in m.group(1).splitlines():
        r = re.search(r'#\[serde\([^)]*rename = "([^"]+)"', line)
        if r:
            rename = r.group(1)
            continue
        f = re.match(r"\s*pub (?:r#)?(\w+):", line)
        if f:
            names.add(rename or f.group(1))
            rename = None
    return names


def vendored(name: str) -> str:
    return (FIXTURES / name).read_text()


# ------------------------------------------------------------------ requirements source fixture


def make_src(root: Path, support=("stack_io.py", "dot-claude/hooks/toolsmith_policy.py"),
             template=None) -> Path:
    """A minimal snapshot tree for requirements.py: settings.json (the repository's), the guard
    files (fixture bytes) and C's guard template."""
    src = Path(root)
    (src / "dot-claude" / "hooks").mkdir(parents=True)
    (src / "codex_config" / "hooks").mkdir(parents=True)
    (src / "codex_config" / "templates").mkdir(parents=True)
    (src / "dot-claude" / "settings.json").write_text(SETTINGS.read_text())
    (src / "codex_config" / "hooks" / "codex-hook").write_text("#!/bin/sh\n# fixture stub\nexit 0\n")
    (src / "codex_config" / "hooks" / "codex_guard.py").write_text("# fixture guard\n")
    (src / "codex_config" / "hooks" / "SUPPORT_FILES").write_text(
        "# support files\n" + "".join(s + "\n" for s in support))
    for s in support:
        name = s.rsplit("/", 1)[-1]
        (src / "dot-claude" / "hooks" / name).write_text("# fixture %s\n" % name)
    (src / "codex_config" / "templates" / "guard.base.json").write_text(
        json.dumps(template if template is not None else {"caps": {"max_spawns": 8}}))
    return src


def tree_state(root: Path, skip: Path | None = None) -> dict:
    """{relative path: (type, size, mtime_ns, mode, link target)} for everything under root."""
    out = {}
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        if skip is not None and Path(dirpath) == skip:
            dirnames[:] = []
            continue
        for n in dirnames + filenames:
            p = Path(dirpath) / n
            if skip is not None and p == skip:
                continue
            st = p.lstat()
            out[str(p.relative_to(root))] = (st.st_mode, st.st_size, st.st_mtime_ns,
                                             os.readlink(p) if p.is_symlink() else None)
    return out
