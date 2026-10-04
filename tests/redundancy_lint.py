#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.9"
# ///
"""Redundancy and dangling-reference lint for dot-claude/ (stdlib only).

Three checks, each against an allowlist (tests/redundancy_allowlist.json) of justified repeats and
known violations; the allowlist's TODO entries are the baseline, so the lint passes today and fails
on new drift:

  repeats  the same long sentence (normalised: markdown marks dropped, lower case, one space; at
           least MIN_CHARS characters) in MIN_FILES or more agent or skill files
  refs     a skill reference that does not resolve: `see `x`` / `load `x``, chained with `, `/`and`/
           `or` (`load `a` and `b``), every backticked name in an agent's `## Skills` paragraph and
           every hub-module mark `x`* must name a shipped skill (or a
           plugin's or Claude Code's own: EXTERNAL_SKILLS, any `plugin:skill`); a section named as
           `see `x` (Heading)`, `` `x` § Heading`` or `` `x` §N`` must be a heading of x's SKILL.md
           or references/*.md (a prefix of the heading text, case-insensitive, "N." numbering ignored)
  hooks    every file in dot-claude/hooks is wired in dot-claude/settings.json (`hooks/<file>` in a
           command) or staged by install.sh (`stage_script ... hooks/<file>` or a `for f in ...` list
           that stages "hooks/$f")

Usage:
  uv run tests/redundancy_lint.py [--root DIR] [--allowlist FILE] [--show-allowed] [--strict]
Exit 0: no finding outside the allowlist; 1: new findings (each printed). --show-allowed also prints
the allowlisted ones; --strict also fails on allowlist entries that no longer match anything (stale).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ALLOWLIST = Path(__file__).resolve().parent / "redundancy_allowlist.json"
MIN_CHARS = 120
MIN_FILES = 3

# Skills that ship outside this repo (Claude Code's bundled ones, Anthropic plugins, the desktop app).
EXTERNAL_SKILLS = {
    "dataviz", "claude-api", "update-config", "workflow-authoring", "loop", "schedule", "run",
    "docx", "xlsx", "pptx", "pdf", "skill-creator", "build-mcp-server", "build-mcp-app",
    "build-mcpb", "math-olympiad", "consolidate-memory", "deep-research", "docs", "explain-usage",
    "google-workspace", "import-memory", "morning", "setup-claude", "chrome-browser",
    "built-in-browser", "computer-use", "artifact-design", "artifact-diagramming",
    "artifact-capabilities", "plugin-authoring",
}
SKILL_NAME = r"[a-z0-9][a-z0-9-]*(?::[a-z0-9][a-z0-9-]*)?"
NAME_TICK = r"`(" + SKILL_NAME + r")`\*?"
# see/load + optional "the" + `name`, then `, `name`` / ` and `name`` / ` or `name`` chained
REF_RE = re.compile(r"(?i)\b(?:see|load)\s+(?:the\s+)?" + NAME_TICK
                    + r"((?:\s*(?:,|\band\b|\bor\b)\s*`" + SKILL_NAME + r"`\*?)*)")
CHAIN_RE = re.compile(r"`(" + SKILL_NAME + r")`")
# a hidden-module mark: `name`* (not part of **bold** or a `*`-suffixed glob)
STAR_RE = re.compile(r"`(" + SKILL_NAME + r")`\*(?![*\w])")
# `name` § Heading / `name` §N (anywhere); `see|load `name` (Heading)` (only after see/load)
SECT_RE = re.compile(r"`(" + SKILL_NAME + r")`\*?\s*§\s*(\d+\b|[^|)\].;,\n`]+)")
# an agent's `## Skills` / `## Skills, if needed` section, up to the next heading or blank line
SKILLS_SECTION_RE = re.compile(r"(?m)^## Skills\b[^\n]*\n((?:[^#\n][^\n]*\n?)+)")
PAREN_RE = re.compile(r"(?i)\b(?:see|load)\s+(?:the\s+)?`(" + SKILL_NAME + r")`\*?\s+\(([^()`:\n]{2,60})\)")


# ---------------------------------------------------------------- files

def scanned_files(root: Path):
    """agent and skill markdown (SKILL.md and references), rules: (relative name, text)."""
    dot = root / "dot-claude"
    paths = sorted((dot / "agents").glob("*.md")) + sorted((dot / "skills").rglob("*.md")) \
        + sorted((dot / "rules").glob("*.md"))
    for p in paths:
        yield p.relative_to(dot).as_posix(), p.read_text(encoding="utf-8", errors="replace")


def skill_names(root: Path):
    return {p.parent.name for p in (root / "dot-claude" / "skills").glob("*/SKILL.md")}


# ---------------------------------------------------------------- (a) repeats

def normalise(s: str) -> str:
    """Code and emphasis marks (` *) dropped, list/quote/table markers stripped, one space, lower case."""
    s = re.sub(r"[`*]", "", s)
    s = re.sub(r"^\s*(?:[-+>|]|\d+[.)])\s+", "", s)
    s = re.sub(r"\s+", " ", s).strip().lower()
    return s.rstrip(" .;:|")


def sentences(text: str):
    """Sentences of a markdown file: line by line (fenced code skipped), each line split after
    . ! ? followed by a space and a capital, backtick or parenthesis; table rows by cell. An agent's
    `tools:` line is skipped: agents of one family share their tool list by design (lint_agents.py
    owns it)."""
    fenced = False
    for line in text.splitlines():
        if line.lstrip().startswith("```"):
            fenced = not fenced
            continue
        if fenced or line.startswith("tools:"):
            continue
        parts = line.split("|") if line.lstrip().startswith("|") else [line]
        for part in parts:
            for s in re.split(r"(?<!\be\.g\.)(?<!\bi\.e\.)(?<=[.!?])\s+(?=[A-Z`(\[])", part):
                yield s


def find_repeats(root: Path):
    """{normalised sentence: sorted files} for every sentence in >= MIN_FILES agent/skill files."""
    where = defaultdict(set)
    for rel, text in scanned_files(root):
        if not rel.startswith(("agents/", "skills/")):
            continue
        for s in sentences(text):
            n = normalise(s)
            if len(n) >= MIN_CHARS:
                where[n].add(rel)
    return {n: sorted(fs) for n, fs in where.items() if len(fs) >= MIN_FILES}


# ---------------------------------------------------------------- (b) refs

def headings(skill_dir: Path):
    out = []
    for p in [skill_dir / "SKILL.md"] + sorted((skill_dir / "references").glob("*.md")):
        if not p.is_file():
            continue
        fenced = False
        for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.lstrip().startswith("```"):
                fenced = not fenced
            elif not fenced and re.match(r"#{1,6}\s", line):
                out.append(line.lstrip("#").strip())
    return out


def section_ok(heads, cited: str) -> bool:
    cited = cited.strip().rstrip(".").strip()
    m = re.fullmatch(r"(\d+)", cited)
    if m:
        return any(re.match(r"%s[.)\s]" % m.group(1), h) for h in heads)
    c = cited.lower()
    for h in heads:
        t = re.sub(r"^\d+[.)]\s*", "", h).lower()
        if t.startswith(c) or c.startswith(t + " ") or c == t:
            return True
    return False


def find_bad_refs(root: Path):
    """[(file, ref, why)] for references that don't resolve. ref: 'name' or 'name § Section'."""
    have = skill_names(root)
    skills_dir = root / "dot-claude" / "skills"
    heads_cache = {}

    def known(name):
        return name in have or name in EXTERNAL_SKILLS or ":" in name

    bad = set()
    for rel, text in scanned_files(root):
        names = set()
        for m in REF_RE.finditer(text):
            names.add(m.group(1))
            names.update(CHAIN_RE.findall(m.group(2) or ""))
        names.update(STAR_RE.findall(text))
        if rel.startswith("agents/"):           # an agent's `## Skills` paragraph: every `name` is a skill
            for m in SKILLS_SECTION_RE.finditer(text):
                names.update(CHAIN_RE.findall(m.group(1)))
        for n in names:
            if not known(n):
                bad.add((rel, n, "no such skill"))
        for m in list(SECT_RE.finditer(text)) + list(PAREN_RE.finditer(text)):
            n, sect = m.group(1), m.group(2).strip()
            if n not in have:
                if m.re is PAREN_RE and not known(n):
                    bad.add((rel, n, "no such skill"))
                continue        # § after a non-skill backtick (a tool, a file): not a skill ref
            if n not in heads_cache:
                heads_cache[n] = headings(skills_dir / n)
            if not section_ok(heads_cache[n], sect):
                bad.add((rel, "%s § %s" % (n, sect), "no such heading in skills/%s" % n))
    return sorted(bad)


# ---------------------------------------------------------------- (c) hooks

def installer_staged_hooks(install_text: str):
    staged = set(re.findall(r"stage_script\s+\d+\s+\"?hooks/([A-Za-z0-9_.-]+)", install_text))
    for m in re.finditer(r"(?m)^\s*for f in ([^;\n]+); do[^\n]*\"(?:\$S/)?hooks/\$f\"", install_text):
        staged.update(m.group(1).split())
    return staged


def find_dead_hooks(root: Path):
    """[(file, why)] for dot-claude/hooks files neither wired in settings.json nor staged."""
    dot = root / "dot-claude"
    settings = (dot / "settings.json").read_text(encoding="utf-8")
    wired = set(re.findall(r"hooks/([A-Za-z0-9_.-]+)", settings))
    install = root / "install.sh"
    staged = installer_staged_hooks(install.read_text(encoding="utf-8")) if install.is_file() else set()
    out = []
    for p in sorted((dot / "hooks").iterdir()):
        if p.name == "__pycache__" or p.name.startswith(".") or not p.is_file():
            continue
        if p.name not in wired and p.name not in staged:
            out.append((p.name, "not wired in settings.json and not staged by install.sh"))
    return out


# ---------------------------------------------------------------- allowlist and report

def load_allowlist(path: Path):
    data = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    for k in ("repeats", "refs", "hooks"):
        data.setdefault(k, [])
    return data


def repeat_allowed(sentence, allow):
    return next((i for i, e in enumerate(allow["repeats"]) if e["contains"].lower() in sentence), None)


def ref_allowed(rel, ref, allow):
    return next((i for i, e in enumerate(allow["refs"])
                 if e["ref"] == ref and e.get("file") in (None, rel)), None)


def hook_allowed(name, allow):
    return next((i for i, e in enumerate(allow["hooks"]) if e["file"] == name), None)


def run(root: Path, allowlist: Path):
    """(new findings, allowed findings, stale allowlist entries): lists of printable lines."""
    allow = load_allowlist(allowlist)
    used = {k: set() for k in ("repeats", "refs", "hooks")}
    new, allowed = [], []
    for sent, files in sorted(find_repeats(root).items()):
        i = repeat_allowed(sent, allow)
        line = "repeat in %d files (%s): %s" % (len(files), ", ".join(files), sent)
        (allowed if i is not None else new).append(line)
        if i is not None:
            used["repeats"].add(i)
    for rel, ref, why in find_bad_refs(root):
        i = ref_allowed(rel, ref, allow)
        line = "ref %s: `%s` (%s)" % (rel, ref, why)
        (allowed if i is not None else new).append(line)
        if i is not None:
            used["refs"].add(i)
    for name, why in find_dead_hooks(root):
        i = hook_allowed(name, allow)
        line = "hook hooks/%s: %s" % (name, why)
        (allowed if i is not None else new).append(line)
        if i is not None:
            used["hooks"].add(i)
    stale = ["stale allowlist %s entry: %s" % (k, json.dumps(e, ensure_ascii=False))
             for k in used for i, e in enumerate(allow[k]) if i not in used[k]]
    return new, allowed, stale


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--root", type=Path, default=ROOT)
    ap.add_argument("--allowlist", type=Path, default=ALLOWLIST)
    ap.add_argument("--show-allowed", action="store_true")
    ap.add_argument("--strict", action="store_true")
    a = ap.parse_args(argv)
    new, allowed, stale = run(a.root, a.allowlist)
    for line in new:
        print("NEW  " + line)
    if a.show_allowed:
        for line in allowed:
            print("OK   " + line)
    for line in stale:
        print("STALE " + line)
    print("redundancy_lint: %d new, %d allowlisted, %d stale allowlist entr%s"
          % (len(new), len(allowed), len(stale), "y" if len(stale) == 1 else "ies"))
    return 1 if new or (a.strict and stale) else 0


if __name__ == "__main__":
    sys.exit(main())
