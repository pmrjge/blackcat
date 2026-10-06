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

A recorded file edited after A5 by a dated amendment of COMPARE_eq.md section 12 (A6, ...) is listed under the record's
"later" key: {rel: {"amendments": [...], "a5_blob": <git blob id of its A5 bytes>, "sha256": <its tracked digest>}}.
For such a file `check` requires the tracked bytes to hash to "sha256", every amendment id to be named in section 12,
and runs the three A5 checks above on the A5 bytes read from git (`git cat-file blob a5_blob`), which must hash to the
recorded new digest. Blob ids are content addresses: a rebase or merge never changes them.

Usage: python3 tests/equilibrium_paths.py check [--root DIR]      exit 0 ok, 1 findings (each printed)
       python3 tests/equilibrium_paths.py amend --amendment A6 [--a5-rev REV] FILE...
                                                                  re-pin FILEs edited by that amendment
       python3 tests/equilibrium_paths.py apply --root DIR        the one-time forward pass (rewrites files)
Stdlib only (git for amended files).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
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
A5_REV = "d28d9ee"  # the last A5 commit on main: every recorded file there holds its A5 bytes
COMPARE = f"{EQ}/COMPARE_eq.md"

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


def _git_blob(root: Path, blob: str) -> bytes | None:
    r = subprocess.run(["git", "-C", str(root), "cat-file", "blob", blob], capture_output=True)
    return r.stdout if r.returncode == 0 else None


def _section12(root: Path) -> str:
    text = (root / COMPARE).read_text(encoding="utf-8") if (root / COMPARE).is_file() else ""
    i = text.find("## 12. Amendments")
    return text[i:] if i >= 0 else ""


def check(root: Path = ROOT) -> list[str]:
    bad = []
    rec = json.loads((root / RECORD).read_text(encoding="utf-8"))
    later = rec.get("later", {})
    for rel in sorted(set(later) - set(rec["files"])):
        bad.append(f"{rel}: listed as amended but not in the A5 record")
    sec12 = _section12(root) if later else ""
    for rel, r in sorted(rec["files"].items()):
        p = root / rel
        if not p.is_file():
            bad.append(f"{rel}: recorded but missing")
            continue
        cur = p.read_bytes()
        if rel in later:
            la = later[rel]
            if sha(cur) != la.get("sha256"):
                bad.append(f"{rel}: tracked bytes differ from the recorded amended digest")
                continue
            names = la.get("amendments") or []
            missing = [a for a in names if not re.search(rf"\*\*{re.escape(a)}\b", sec12)]
            if not names or missing:
                bad.append(f"{rel}: amendment {missing or names} not named in {COMPARE} section 12")
                continue
            cur = _git_blob(root, str(la.get("a5_blob", "")))
            if cur is None:
                bad.append(f"{rel}: the A5 bytes (blob {la.get('a5_blob')}) cannot be read from git")
                continue
        if sha(cur) != r["new_sha256"]:
            bad.append(f"{rel}: tracked bytes differ from the recorded new digest"
                       if rel not in later else f"{rel}: the A5 blob does not hash to the recorded new digest")
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


def amend(root: Path, amendment: str, rels: list[str], a5_rev: str = A5_REV) -> int:
    """Re-pin files a dated amendment edited after A5: record their A5 blob (from a5_rev, verified against the A5
    record) and their tracked digest. The A5 record itself ("files") is never rewritten."""
    path = root / RECORD
    rec = json.loads(path.read_text(encoding="utf-8"))
    later = rec.setdefault("later", {})
    for rel in rels:
        rel = str(Path(rel).as_posix())
        if rel not in rec["files"]:
            print(f"amend: {rel} is not in the A5 record (an unrecorded file needs no re-pin)")
            return 1
        prev = later.get(rel, {})
        blob = prev.get("a5_blob")
        if not blob:
            r = subprocess.run(["git", "-C", str(root), "rev-parse", f"{a5_rev}:{rel}"], capture_output=True, text=True)
            if r.returncode:
                print(f"amend: {a5_rev}:{rel} not found: {r.stderr.strip()}")
                return 1
            blob = r.stdout.strip()
        data = _git_blob(root, blob)
        if data is None or sha(data) != rec["files"][rel]["new_sha256"]:
            print(f"amend: blob {blob} of {rel} is not its A5 bytes")
            return 1
        later[rel] = {"amendments": sorted(set(prev.get("amendments", [])) | {amendment}), "a5_blob": blob,
                      "sha256": sha((root / rel).read_bytes())}
    path.write_text(json.dumps(rec, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print(f"amend: {len(rels)} file(s) re-pinned under {amendment}")
    return 0


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
    ap.add_argument("mode", choices=["check", "apply", "amend"])
    ap.add_argument("--root", type=Path, default=ROOT)
    ap.add_argument("--amendment", default="")
    ap.add_argument("--a5-rev", default=A5_REV)
    ap.add_argument("files", nargs="*")
    a = ap.parse_args(argv)
    if a.mode == "amend":
        if not re.fullmatch(r"A[0-9]+", a.amendment) or not a.files:
            ap.error("amend needs --amendment A<n> and at least one file")
        return amend(a.root, a.amendment, a.files, a.a5_rev)
    if a.mode == "apply":
        return apply(a.root)
    bad = check(a.root)
    for b in bad:
        print(b)
    print(f"equilibrium_paths: {'ok' if not bad else f'{len(bad)} finding(s)'}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
