"""Read-only comparison of a rendered stage with the live CODEX_HOME, by area (install.sh --diff).

Stdlib only, Python >= 3.11. Loaded and run by path from the private source snapshot.

  codex_diff.py <live codex_home> <stage> [links.json]

Areas, in this order: profiles (codex.config.toml, codex-astra.config.toml), config.toml regions
(--ide-default's two marked regions; the rest of the file is the user's and never compared), rules,
AGENTS.md block, stack/agents (+ agents-astra), stack/skills (+ skill-modules), stack/policy,
stack/hooks (+ bin, mcp, magg), links (links.json against the live manifest's links). Small text
files get a unified diff (capped), role and skill directories a count and the names. Nothing is
written; a symlinked file is reported, never read through. Exit 0 always (a difference is not an
error); 1 on a usage or read problem.

Seeded-bug proofs (tests/mutations/codex_diff.json; each turns tests/test_install_cli.py red): never
report a changed config.toml region; leave the removed live files out of a directory area; read a
live file through a symlink.
"""
from __future__ import annotations

import difflib
import importlib.util
import json
import os
import stat
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
# not the stack's files: install.sh makes them after the apply (the engine's EXCLUDED)
SKIP = ("stack/bin/stack-python",)
MAX_DIFF_LINES = 60
MAX_NAMES = 12


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _read(path):
    """File bytes; None when absent, a link or not a regular file (never read through a link)."""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except OSError:
        return None
    with os.fdopen(fd, "rb") as f:
        if not stat.S_ISREG(os.fstat(f.fileno()).st_mode):
            return None
        return f.read()


def _files(root, sub):
    out = {}
    top = os.path.join(root, sub)
    if os.path.islink(top):
        return out
    for d, dirs, names in os.walk(top):
        dirs[:] = sorted(x for x in dirs if x != "__pycache__")
        for n in sorted(names):
            p = os.path.join(d, n)
            if os.path.relpath(p, root) not in SKIP:
                out[os.path.relpath(p, root)] = p
    return out


def _text_diff(a, b, label, out):
    lines = list(difflib.unified_diff(a.decode("utf-8", "replace").splitlines(), b.decode("utf-8", "replace").splitlines(),
                                      "live/" + label, "new/" + label, lineterm="", n=1))
    for ln in lines[:MAX_DIFF_LINES]:
        out.append("      " + ln)
    if len(lines) > MAX_DIFF_LINES:
        out.append("      ... %d more diff lines" % (len(lines) - MAX_DIFF_LINES))


def _file_pair(live, stage, rel, out):
    """One owned file: added, removed, changed (with a diff) or the same."""
    a, b = _read(os.path.join(live, rel)), _read(os.path.join(stage, rel))
    if os.path.islink(os.path.join(live, rel)):
        out.append("    %s: live file is a symlink (yours): not read" % rel)
    elif a is None and b is None:
        return
    elif a is None:
        out.append("    + %s (new, %d bytes)" % (rel, len(b)))
    elif b is None:
        out.append("    - %s (removed)" % rel)
    elif a != b:
        out.append("    ~ %s" % rel)
        _text_diff(a, b, rel, out)


def _tree(live, stage, subs, out, show_diff):
    """A directory area: names added / removed / changed; diffs only when show_diff."""
    la, sb = {}, {}
    for sub in subs:
        la.update(_files(live, sub))
        sb.update(_files(stage, sub))
    add = sorted(r for r in sb if r not in la)
    rem = sorted(r for r in la if r not in sb)
    chg = sorted(r for r in sb if r in la and _read(la[r]) != _read(sb[r]))
    if not (add or rem or chg):
        return
    out.append("    %d added, %d removed, %d changed" % (len(add), len(rem), len(chg)))
    for sign, names in (("+", add), ("-", rem), ("~", chg)):
        for r in names[:MAX_NAMES]:
            out.append("    %s %s" % (sign, r))
        if len(names) > MAX_NAMES:
            out.append("    %s ... and %d more" % (sign, len(names) - MAX_NAMES))
    if show_diff:
        for r in chg[:MAX_NAMES]:
            a, b = _read(la[r]), _read(sb[r])
            if a is not None and b is not None:
                _text_diff(a, b, r, out)


def _spans(data, find):
    """{"A": bytes|None, ...} bodies of the marked regions (or a one-key {"block": ...})."""
    return {k: (data[v[0]:v[1]] if v else None) for k, v in find(data).items()}


def _regions(live, stage, out):
    reg = _load("codex_diff_region", os.path.join(_HERE, "config_region.py"))
    got = {}
    for tag, root in (("live", live), ("new", stage)):
        data = _read(os.path.join(root, "config.toml"))
        if data is None:
            got[tag] = {"A": None, "B": None}
            continue
        try:
            got[tag] = _spans(data, reg.find)
        except reg.RegionError as exc:
            out.append("    %s config.toml: %s" % (tag, exc))
            return
    for k in ("A", "B"):
        a, b = got["live"][k], got["new"][k]
        if a == b:
            continue
        if a is None:
            out.append("    + region %s (new, %d bytes)" % (k, len(b)))
        elif b is None:
            out.append("    - region %s (removed)" % k)
        else:
            out.append("    ~ region %s" % k)
            _text_diff(a, b, "config.toml region " + k, out)


def _agents_block(live, stage, out):
    cmb = _load("codex_diff_block", os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(_HERE))), "lib",
                                                 "claude_md_block.py"))
    got = {}
    for tag, root in (("live", live), ("new", stage)):
        data = _read(os.path.join(root, "AGENTS.md"))
        if data is None:
            got[tag] = None
            continue
        try:
            span = cmb.find_block(data)
        except cmb.BlockError as exc:
            out.append("    %s AGENTS.md: %s" % (tag, exc))
            return
        got[tag] = data[span[0]:span[1]] if span else None
    a, b = got["live"], got["new"]
    if a == b:
        return
    if a is None:
        out.append("    + stack block (new, %d bytes)" % len(b))
    elif b is None:
        out.append("    - stack block (removed)")
    else:
        out.append("    ~ stack block")
        _text_diff(a, b, "AGENTS.md block", out)


def _links(live, links_json, out):
    new = {}
    if links_json:
        try:
            doc = json.loads((_read(links_json) or b"{}").decode("utf-8"))
            new = doc.get("links") or {}
        except (ValueError, AttributeError):
            out.append("    links.json unreadable")
            return
    old = {}
    try:
        mf = json.loads((_read(os.path.join(live, ".stack-manifest.json")) or b"{}").decode("utf-8"))
        old = (mf.get("links") or {}).get("links", mf.get("links") or {})
    except (ValueError, AttributeError):
        pass
    if not isinstance(old, dict):
        old = {}
    add = sorted(k for k in new if k not in old)
    rem = sorted(k for k in old if k not in new)
    chg = sorted(k for k in new if k in old and new[k] != old[k])
    if add or rem or chg:
        out.append("    %d added, %d removed, %d retargeted (skills root: %s)"
                   % (len(add), len(rem), len(chg), (doc.get("root") if links_json else None)))
        for sign, names in (("+", add), ("-", rem), ("~", chg)):
            out.extend("    %s %s" % (sign, n) for n in names[:MAX_NAMES])
            if len(names) > MAX_NAMES:
                out.append("    %s ... and %d more" % (sign, len(names) - MAX_NAMES))


def report(live, stage, links_json=None):
    """The lines of the comparison, one block per area (an unchanged area says so in one line)."""
    out = []

    def area(name, fn):
        body = []
        fn(body)
        out.append("%s:%s" % (name, "" if body else " no changes"))
        out.extend(body)

    def files(*rels):
        return lambda body: [_file_pair(live, stage, r, body) for r in rels]

    area("profiles", files("codex.config.toml", "codex-astra.config.toml"))
    area("config.toml regions", lambda body: _regions(live, stage, body))
    area("rules", files("rules/claude-agent-stack.rules"))
    area("AGENTS.md block", lambda body: _agents_block(live, stage, body))
    area("stack/agents", lambda body: _tree(live, stage, ("stack/agents", "stack/agents-astra"), body, False))
    area("stack/skills", lambda body: _tree(live, stage, ("stack/skills", "stack/skill-modules"), body, False))
    area("stack/policy", lambda body: _tree(live, stage, ("stack/policy",), body, True))
    area("stack/hooks", lambda body: _tree(live, stage, ("stack/hooks", "stack/bin", "stack/mcp", "stack/magg"),
                                           body, False))
    area("links", lambda body: _links(live, links_json, body))
    return out


def main(argv):
    a = argv[1:]
    if len(a) not in (2, 3):
        sys.stderr.write("usage: codex_diff.py <live codex_home> <stage> [links.json]\n")
        return 1
    for line in report(a[0], a[1], a[2] if len(a) == 3 else None):
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
