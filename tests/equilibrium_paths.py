#!/usr/bin/env python3
"""Path relativisation of equilibrium/ (COMPARE_eq.md amendment A5, 2026-10-06): the rules, the forward pass, the check.

RULES lists (id, old bytes, new bytes) in priority order. The forward pass (`apply`, run once on 2026-10-06 over the
pre-relativisation tree) replaces, left to right, every occurrence of an old string by its new one (at each position
the first rule in RULES that matches wins) and records per changed file its old and new sha256 and every substitution
as (offset in the new file, rule id) in equilibrium/PATH_RELATIVISATION.json. The old strings live only here: no file
under equilibrium/ names the old home directory.

`check` proves that only path text changed. For every recorded file it requires:
- the tracked bytes hash to the recorded new digest;
- reversing the recorded substitutions gives bytes that hash to the recorded old digest (the pre-relativisation file);
- the forward pass over those old bytes gives the tracked bytes again (no occurrence was missed or added);
and that no file under equilibrium/ contains the old home prefix.

Usage: python3 tests/equilibrium_paths.py check [--root DIR]      exit 0 ok, 1 findings (each printed)
       python3 tests/equilibrium_paths.py apply --root DIR        the one-time forward pass (rewrites files)
Stdlib only.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EQ = "equilibrium"
RECORD = f"{EQ}/PATH_RELATIVISATION.json"
SKIP = {f"{EQ}/README.md", RECORD, f"{EQ}/PATH_RELATIVISATION.md"}
OLD_HOME = b"/Users/pmrj"
OLD_M = OLD_HOME + b"/ZDone/claude-agent-stack"
OLD_STAGE = OLD_HOME + b"/ZDone/Worktree_for_Claude/claude-agent-stack/next-steps-7c1c7f/.claude-work/equilibrium"
OLD_LEAN = OLD_HOME + b"/lean/stack_mathlib"

RULES: list[tuple[str, bytes, bytes]] = [
    # the host Lean project lies outside the repository: $HOME-relative (${HOME:-} under `set -u`)
    ("lean-sh-default", b"${EQ_LEAN_PROJECT:-" + OLD_LEAN + b"}", b"${EQ_LEAN_PROJECT:-${HOME:-}/lean/stack_mathlib}"),
    ("lean-py-default", b'os.environ.get("EQ_LEAN_PROJECT", "' + OLD_LEAN + b'")',
     b'os.environ.get("EQ_LEAN_PROJECT", os.path.expanduser("~/lean/stack_mathlib"))'),
    ("lean-text", OLD_LEAN, b"$HOME/lean/stack_mathlib"),
    # scripts derive M (the checkout) and the staged package from their own location at run time
    ("m-sh-default", b"M=${EQ_M:-" + OLD_M + b"}",
     b'M=${EQ_M:-$(git -C "$(dirname "$0")" rev-parse --show-toplevel 2>/dev/null'
     b' || (cd "$(dirname "$0")/../.." && pwd))}'),  # a subshell: a brace group's `}` would end the ${...}
    ("stage-sh-default", b"STAGE=${EQ_STAGE_DIR:-" + OLD_STAGE + b"}",
     b'STAGE=${EQ_STAGE_DIR:-$(cd "$(dirname "$0")/.." && pwd)}'),
    ("m-py-default", b'DEFAULT_M = Path("' + OLD_M + b'")',
     b'DEFAULT_M = next((p for p in Path(__file__).resolve().parents if (p / ".git").exists()),\n'
     b"                 Path(__file__).resolve().parents[2])  # the checkout holding this script: the repository root"),
    ("campaign-py", b'CAMPAIGN = Path("' + OLD_M + b'/claude-local-work/campaign/agents-baseline")',
     b'CAMPAIGN_REL = Path("claude-local-work/campaign/agents-baseline")  # relative to the repository root\n'
     b"CAMPAIGN = Path(__file__).resolve().parents[4] / CAMPAIGN_REL"),
    # extract_src.py writes gen/src/SOURCES.sha256: the paths it writes become relative too
    ("campaign-py-writer", b"  {CAMPAIGN / n}\"", b"  {CAMPAIGN_REL / n}\""),
    # documents: relative to the repository root (the former STAGE is equilibrium/, the former M is .)
    ("stage-text", OLD_STAGE, b"equilibrium"),
    ("m-prefix-text", OLD_M + b"/", b""),
    ("m-text", OLD_M, b"."),
    # the repository's name (USER, 2026-10-06)
    ("vcs-source", b"git@github.com:pmrjge/blackcat_v1.git", b"git@github.com:pmrjge/blackcat.git"),
]
BY_ID = {i: (old, new) for i, old, new in RULES}
PATTERN = re.compile(b"|".join(re.escape(old) for _, old, _ in RULES))
ORDER = [i for i, _, _ in RULES]


def sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def forward(data: bytes) -> tuple[bytes, list[list]]:
    """The forward pass: (new bytes, [[offset in new, rule id], ...])."""
    out, subs, pos = bytearray(), [], 0
    for m in PATTERN.finditer(data):
        rid = next(i for i in ORDER if data.startswith(BY_ID[i][0], m.start()))
        if len(BY_ID[rid][0]) != m.end() - m.start():  # the alternation picked an earlier, shorter rule: impossible
            raise AssertionError(f"rule order: {rid} at {m.start()}")
        out += data[pos:m.start()]
        subs.append([len(out), rid])
        out += BY_ID[rid][1]
        pos = m.end()
    out += data[pos:]
    return bytes(out), subs


def reverse(data: bytes, subs: list[list]) -> bytes:
    """The recorded substitutions undone, last first; raises ValueError where the tracked bytes disagree."""
    buf = bytearray(data)
    for off, rid in sorted(subs, key=lambda s: s[0], reverse=True):
        old, new = BY_ID[rid]
        if bytes(buf[off:off + len(new)]) != new:
            raise ValueError(f"offset {off}: not the {rid} text")
        buf[off:off + len(new)] = old
    return bytes(buf)


def eq_files(root: Path) -> list[Path]:
    return sorted(p for p in (root / EQ).rglob("*") if p.is_file() and "__pycache__" not in p.parts
                  and ".ruff_cache" not in p.parts and ".pytest_cache" not in p.parts)


def check(root: Path = ROOT) -> list[str]:
    bad = []
    rec = json.loads((root / RECORD).read_text(encoding="utf-8"))
    for rel, r in sorted(rec["files"].items()):
        p = root / rel
        if not p.is_file():
            bad.append(f"{rel}: recorded but missing")
            continue
        cur = p.read_bytes()
        if sha(cur) != r["new_sha256"]:
            bad.append(f"{rel}: tracked bytes differ from the recorded new digest")
            continue
        if any(s[1] not in BY_ID for s in r["subs"]) or not r["subs"]:
            bad.append(f"{rel}: unknown rule id or no substitution")
            continue
        try:
            old = reverse(cur, r["subs"])
        except ValueError as e:
            bad.append(f"{rel}: {e}")
            continue
        if sha(old) != r["old_sha256"]:
            bad.append(f"{rel}: reversed bytes differ from the recorded old digest")
        elif forward(old) != (cur, r["subs"]):
            bad.append(f"{rel}: the forward pass over the old bytes does not give the tracked bytes")
    for p in eq_files(root):
        if OLD_HOME in p.read_bytes():
            bad.append(f"{p.relative_to(root)}: names the old home directory")
    return bad


def apply(root: Path) -> int:
    files = {}
    for p in eq_files(root):
        rel = str(p.relative_to(root))
        if rel in SKIP:
            continue
        data = p.read_bytes()
        new, subs = forward(data)
        if subs:
            p.write_bytes(new)
            files[rel] = {"old_sha256": sha(data), "new_sha256": sha(new), "subs": subs}
    rec = {"amendment": "COMPARE_eq.md A5", "date": "2026-10-06", "rules": ORDER, "files": files}
    (root / RECORD).write_text(json.dumps(rec, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print(f"apply: {len(files)} files, {sum(len(f['subs']) for f in files.values())} substitutions")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("mode", choices=["check", "apply"])
    ap.add_argument("--root", type=Path, default=ROOT)
    a = ap.parse_args(argv)
    if a.mode == "apply":
        return apply(a.root)
    bad = check(a.root)
    for b in bad:
        print(b)
    print(f"equilibrium_paths: {'ok' if not bad else f'{len(bad)} finding(s)'}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
