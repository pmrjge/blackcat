#!/usr/bin/env python3
"""Prompt-cache stability lint: the static prompt text the stack ships stays byte-stable.

Claude Code caches the request prefix (tools, system prompt, then the first user message). Text the
stack ships into that prefix must not carry anything that changes between runs or between edits for
no reason: dates, clock times, epoch timestamps, UUIDs/session ids, agent/tool/message ids, commit
hashes, x.y.z versions, model IDs, `!`cmd`` shell injection or ${CLAUDE_SESSION_ID}. A volatile
value there is re-written each time it changes, and every spawn after the change starts cold.

Scope (decided by the Stage 4 L1 audit: rules and agents carry no dates or ids; skills carry dated
as-of facts in their bodies, which load on invocation, at the tail of the context):
  dot-claude/agents/*.md        frontmatter `description` (the agent listing) and the body (the
                                subagent's system prompt); the other frontmatter keys are config
                                (mcpServers args pin versions on purpose), not prompt text
  dot-claude/rules/*.md         the whole file (loaded into every thread)
  dot-claude/CLAUDE*.md         the whole file (CLAUDE.md templates, when the repo ships one)
  dot-claude/skills/*/SKILL.md  frontmatter `name`, `description`, `when_to_use` (the skill listing
                                in every thread); not the body
Hook text injected early (SessionStart, SubagentStart) is checked by running the hooks:
tests/test_cache_stability.py.

Usage: python3 tests/cache_stability_lint.py [--root DIR] [--json]
Exits 0 and prints "cache_stability_lint: ok (N files)" when clean; else prints one
`path:line: kind: match` per finding and exits 1. Stdlib only.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

_MONTHS = (r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|June?|July?|Aug(?:ust)?|"
           r"Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)")
_HEX_MIX = r"(?=[0-9a-f]*[a-f])(?=[0-9a-f]*\d)"    # at least one digit and one letter
# (kind, pattern). Ordered: the first kind that claims a span wins (a UUID is not also a date).
PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("uuid", re.compile(r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b")),
    ("iso-datetime", re.compile(r"\b(?:19|20)\d\d-[01]\d-[0-3]\d[T ][0-2]\d:[0-5]\d(?::[0-5]\d)?")),
    ("date", re.compile(r"\b(?:19|20)\d\d-(?:0[1-9]|1[0-2])-(?:0[1-9]|[12]\d|3[01])\b"
                        r"|\b(?:19|20)\d\d/(?:0[1-9]|1[0-2])/(?:0[1-9]|[12]\d|3[01])\b"
                        rf"|\b{_MONTHS}\.? [0-3]?\d(?:st|nd|rd|th)?,? (?:19|20)\d\d\b"
                        rf"|\b[0-3]?\d {_MONTHS} (?:19|20)\d\d\b")),
    ("clock-time", re.compile(r"(?<![\d:.])(?:[01]\d|2[0-3]):[0-5]\d:[0-5]\d(?![\d:])")),
    ("epoch", re.compile(r"(?<![\w.])1[5-9]\d{8}(?:\d{3})?(?![\w.])")),
    ("agent-id", re.compile(r"\bagent-a[0-9a-f]{15,17}\b")),
    ("api-id", re.compile(r"\b(?:toolu|srvtoolu|msg|req|msgbatch|file)_[0-9A-Za-z]{16,}\b")),
    ("commit", re.compile(rf"(?<![0-9A-Za-z]){_HEX_MIX}[0-9a-f]{{40}}(?![0-9A-Za-z])"
                          rf"|\b(?:commit|sha|SHA|rev|HEAD)\s*[:=]?\s*`?{_HEX_MIX}[0-9a-f]{{7,39}}\b")),
    ("model-id", re.compile(r"\bclaude-(?:opus|sonnet|haiku)-\d+(?:[-.]\d+)*\b"
                            r"|\bclaude-\d(?:[-.]\d+)*-(?:opus|sonnet|haiku)\b")),
    ("version", re.compile(r"(?<![\w.\-/])v?\d+\.\d+\.\d+(?:-[0-9A-Za-z.]+)?(?![\w/]|\.\d)")),
    ("shell-injection", re.compile(r"(?:^|(?<=\s))!`[^`\n]+`")),
    ("session-var", re.compile(r"\$\{?CLAUDE_SESSION_ID\b\}?")),
]

# Findings accepted on purpose: (repo-relative path, kind, matched text) -> reason. Only for a value
# that never changes while the stack is installed.
ALLOW: dict[tuple[str, str, str], str] = {}

PROMPT_KEYS_AGENT = frozenset({"description"})
PROMPT_KEYS_SKILL = frozenset({"name", "description", "when_to_use"})


def frontmatter_spans(lines: list[str]) -> tuple[int, dict[str, list[int]]]:
    """(index of the closing `---` line, {key: [line indexes holding its value]}) for a file that
    opens with `---`; (-1, {}) otherwise. A key owns its line and the indented or blank lines after
    it."""
    if not lines or lines[0].rstrip("\r\n") != "---":
        return -1, {}
    keys: dict[str, list[int]] = {}
    cur: str | None = None
    for i in range(1, len(lines)):
        s = lines[i].rstrip("\r\n")
        if s == "---":
            return i, keys
        m = re.match(r"^([A-Za-z_][\w-]*)\s*:", s)
        if m:
            cur = m.group(1)
            keys.setdefault(cur, []).append(i)
        elif cur is not None and (s.startswith((" ", "\t")) or not s.strip()):
            keys[cur].append(i)
        else:
            cur = None
    return -1, {}


def scoped_lines(path: Path, kind: str) -> list[tuple[int, str]]:
    """[(1-based line number, text)] of the prompt text of `path`; kind: agent, skill or whole."""
    lines = path.read_text(encoding="utf-8").splitlines()
    if kind == "whole":
        return list(enumerate(lines, 1))
    end, keys = frontmatter_spans(lines)
    want = PROMPT_KEYS_AGENT if kind == "agent" else PROMPT_KEYS_SKILL
    idx = sorted(i for k, v in keys.items() if k in want for i in v)
    if kind == "agent":
        idx += range(end + 1 if end >= 0 else 0, len(lines))
    return [(i + 1, lines[i]) for i in idx]


def targets(root: Path) -> list[tuple[Path, str]]:
    d = root / "dot-claude"
    out = [(p, "agent") for p in sorted((d / "agents").glob("*.md"))]
    out += [(p, "whole") for p in sorted((d / "rules").glob("*.md"))]
    out += [(p, "whole") for p in sorted(d.glob("CLAUDE*.md"))]
    out += [(p, "skill") for p in sorted((d / "skills").glob("*/SKILL.md"))]
    return out


def scan_line(text: str) -> list[tuple[str, str]]:
    """[(kind, match)] in one line, in order; a span an earlier kind claimed is not reported again."""
    taken: list[tuple[int, int]] = []
    hits: list[tuple[int, str, str]] = []
    for kind, rx in PATTERNS:
        for m in rx.finditer(text):
            a, b = m.span()
            if any(a < y and x < b for x, y in taken):
                continue
            taken.append((a, b))
            hits.append((a, kind, m.group(0).strip()))
    return [(k, s) for _, k, s in sorted(hits)]


def lint(root: Path = REPO_ROOT) -> tuple[list[dict[str, object]], int]:
    """(findings, number of files scanned)."""
    found: list[dict[str, object]] = []
    files = targets(root)
    for path, kind in files:
        rel = path.relative_to(root).as_posix()
        for n, text in scoped_lines(path, kind):
            for k, s in scan_line(text):
                if (rel, k, s) not in ALLOW:
                    found.append({"path": rel, "line": n, "kind": k, "match": s})
    return found, len(files)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n", 1)[0])
    ap.add_argument("--root", type=Path, default=REPO_ROOT, help="repository root (default: this repo)")
    ap.add_argument("--json", action="store_true", help="print the findings as JSON")
    a = ap.parse_args(argv)
    found, n = lint(a.root.resolve())
    if a.json:
        print(json.dumps({"files": n, "findings": found}, indent=1))
    elif found:
        for f in found:
            print(f"{f['path']}:{f['line']}: {f['kind']}: {f['match']}")
        print(f"cache_stability_lint: {len(found)} finding(s) in {n} files", file=sys.stderr)
    else:
        print(f"cache_stability_lint: ok ({n} files)")
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())
