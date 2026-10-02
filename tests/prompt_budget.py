#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""Static prompt budget of the stack's agents: what each spawn costs before it does any work.

Usage:
    uv run --script tests/prompt_budget.py [--base REV] [--head REV] [--json] [--check] [--turns [GLOB]]

Per agent: description chars, body chars, maxTurns, whether it has the Agent tool, omitClaudeMd.
Shared: the rules file, the skill listing (sum of name + 4 + min(description, skillListingMaxDescChars)
over model-invocable skills) and the agent listing an agent with the Agent tool sees (sum of name +
description + tools line + 12 over every agent but blackcat). Per spawn = body + rules (unless
omitClaudeMd) + skill listing + agent listing (if the agent has Agent). Tokens ~ ceil(chars / 3).

--base REV   compare the working tree (head) with REV (read through `git show`); a table with deltas.
--head REV   measure REV instead of the working tree (the baseline table: --head <base rev>).
--check      exit 1 unless every description <= 200 chars, blackcat body <= 5,200, and against
             --base: sum of bodies of agents present at base <= 0.75 x base, agent listing <= 0.70 x
             base, rules <= 1.05 x base (ratios skipped when the base revision is missing).
--turns      read Claude Code subagent transcripts (read-only; default
             ~/.claude/projects/**/subagents/agent-*.meta.json) and print p50/p90/max turns per agent
             type (one turn = one assistant message id).
"""
import argparse
import glob
import json
import math
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOT = "dot-claude"
RULES = DOT + "/rules/claude-agent-stack.md"
DESC_MAX = 200
BLACKCAT_BODY_MAX = 5200
RATIO = {"bodies": 0.75, "agent_listing": 0.70, "rules": 1.05}


# ---------------------------------------------------------------- sources
class Tree:
    """Files of the working tree (rev None) or of a git revision."""

    def __init__(self, rev=None):
        self.rev = rev

    def read(self, rel):
        if self.rev is None:
            p = ROOT / rel
            return p.read_text() if p.is_file() else None
        r = subprocess.run(["git", "-C", str(ROOT), "show", "%s:%s" % (self.rev, rel)],
                           capture_output=True, text=True)
        return r.stdout if r.returncode == 0 else None

    def list(self, rel_dir):
        """Paths (relative to ROOT) of the files under rel_dir, recursively."""
        if self.rev is None:
            base = ROOT / rel_dir
            return sorted(p.relative_to(ROOT).as_posix() for p in base.rglob("*") if p.is_file())
        r = subprocess.run(["git", "-C", str(ROOT), "ls-tree", "-r", "--name-only", self.rev, rel_dir],
                           capture_output=True, text=True)
        return sorted(r.stdout.split()) if r.returncode == 0 else []


def rev_exists(rev):
    return subprocess.run(["git", "-C", str(ROOT), "rev-parse", "--verify", "--quiet", rev + "^{commit}"],
                          capture_output=True).returncode == 0


# ---------------------------------------------------------------- parsing
def split_frontmatter(text):
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, text
    try:
        end = lines[1:].index("---") + 1
    except ValueError:
        return {}, text
    fm = {}
    for line in lines[1:end]:
        m = re.match(r"^([A-Za-z_]+):\s*(.*)$", line)
        if m:
            fm[m.group(1)] = m.group(2).strip()
    return fm, "\n".join(lines[end + 1:]).strip()


def unquote(v):
    v = (v or "").strip()
    if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
        inner = v[1:-1]
        return inner.replace('\\"', '"') if v[0] == '"' else inner.replace("''", "'")
    return v


def agent_record(name, text):
    fm, body = split_frontmatter(text)
    tools = fm.get("tools", "")
    turns = fm.get("maxTurns", "")
    return {
        "name": name,
        "description": len(unquote(fm.get("description"))),
        "body": len(body),
        "maxTurns": int(turns) if turns.isdigit() else None,
        "has_agent": bool(re.search(r"(^|,)\s*Agent\b", tools)),
        "omit_claude_md": fm.get("omitClaudeMd", "").lower() == "true",
        "tools": tools,
        "listing": len(name) + len(unquote(fm.get("description"))) + len(tools) + 12,
    }


def measure(tree):
    agents = {}
    for rel in tree.list(DOT + "/agents"):
        if rel.endswith(".md") and rel.count("/") == 2:
            text = tree.read(rel)
            if text is not None:
                name = rel.rsplit("/", 1)[1][:-3]
                agents[name] = agent_record(name, text)
    try:
        settings = json.loads(tree.read(DOT + "/settings.json") or "{}")
    except ValueError:
        settings = {}
    cap = int(settings.get("skillListingMaxDescChars", 1536))
    skills = 0
    for rel in tree.list(DOT + "/skills"):
        parts = rel.split("/")
        if len(parts) != 4 or parts[3] != "SKILL.md":
            continue
        text = tree.read(rel) or ""
        head = text.split("---", 2)[1] if text.startswith("---") else ""
        if re.search(r"(?m)^disable-model-invocation:\s*(true|yes|on|1)\s*$", head):
            continue
        d = re.search(r"(?m)^description:\s*(.*)$", head)
        skills += len(parts[2]) + 4 + min(len(unquote(d.group(1))) if d else 0, cap)
    rules = len(tree.read(RULES) or "")
    listing = sum(a["listing"] for n, a in agents.items() if n != "blackcat")
    for a in agents.values():
        a["per_spawn"] = (a["body"] + (0 if a["omit_claude_md"] else rules) + skills
                          + (listing if a["has_agent"] else 0))
    return {"agents": agents, "rules": rules, "skill_listing": skills, "agent_listing": listing,
            "bodies": sum(a["body"] for a in agents.values()),
            "descriptions": sum(a["description"] for a in agents.values()),
            "per_spawn": sum(a["per_spawn"] for a in agents.values())}


# ---------------------------------------------------------------- checks
def check(head, base):
    bad = []
    for n, a in sorted(head["agents"].items()):
        if a["description"] > DESC_MAX:
            bad.append("%s.md: description %d chars > %d" % (n, a["description"], DESC_MAX))
    bc = head["agents"].get("blackcat")
    if bc and bc["body"] > BLACKCAT_BODY_MAX:
        bad.append("blackcat.md: body %d chars > %d" % (bc["body"], BLACKCAT_BODY_MAX))
    if base is None:
        return bad
    common = [n for n in base["agents"] if n in head["agents"]]
    b0 = sum(base["agents"][n]["body"] for n in common)
    b1 = sum(head["agents"][n]["body"] for n in common)
    if b1 > RATIO["bodies"] * b0:
        over = sorted(((head["agents"][n]["body"] - RATIO["bodies"] * base["agents"][n]["body"], n)
                       for n in common), reverse=True)
        bad.append("bodies of base agents: %d chars > %.2f x %d = %d; most over 0.75 x base: %s"
                   % (b1, RATIO["bodies"], b0, RATIO["bodies"] * b0,
                      ", ".join("%s.md (+%d)" % (n, d) for d, n in over[:8] if d > 0)))
    for key in ("agent_listing", "rules"):
        if head[key] > RATIO[key] * base[key]:
            bad.append("%s: %d chars > %.2f x %d = %d" % (key, head[key], RATIO[key], base[key],
                                                          RATIO[key] * base[key]))
    return bad


# ---------------------------------------------------------------- report
def tok(chars):
    return math.ceil(chars / 3)


def pct(a, b):
    return "—" if not a else "%+.1f%%" % (100.0 * (b - a) / a)


def table(head, base, rev):
    out = []
    if base is None:
        out.append("| agent | desc | body | maxTurns | Agent | per spawn (chars) | ≈ tokens |")
        out.append("|---|---:|---:|---:|:-:|---:|---:|")
        for n, a in sorted(head["agents"].items()):
            out.append("| %s | %d | %d | %s | %s | %d | %d |" % (
                n, a["description"], a["body"], a["maxTurns"] or "—", "y" if a["has_agent"] else "",
                a["per_spawn"], tok(a["per_spawn"])))
        out.append("")
        for k in ("descriptions", "bodies", "rules", "skill_listing", "agent_listing", "per_spawn"):
            out.append("- %s: %d chars (≈ %d tokens)" % (k, head[k], tok(head[k])))
        return "\n".join(out)
    out.append("Base `%s` → head (working tree). Chars; tokens ≈ chars / 3." % rev)
    out.append("")
    out.append("| agent | desc | body | Δ body | maxTurns | per spawn | Δ per spawn |")
    out.append("|---|---:|---:|---:|---:|---:|---:|")
    names = sorted(set(head["agents"]) | set(base["agents"]))
    for n in names:
        a0, a1 = base["agents"].get(n), head["agents"].get(n)
        if a1 is None:
            out.append("| %s | removed | | | | | |" % n)
            continue
        if a0 is None:
            out.append("| %s (new) | %d | %d | | %s | %d | |" % (
                n, a1["description"], a1["body"], a1["maxTurns"] or "—", a1["per_spawn"]))
            continue
        out.append("| %s | %d→%d | %d→%d | %s | %s→%s | %d→%d | %s |" % (
            n, a0["description"], a1["description"], a0["body"], a1["body"], pct(a0["body"], a1["body"]),
            a0["maxTurns"] or "—", a1["maxTurns"] or "—", a0["per_spawn"], a1["per_spawn"],
            pct(a0["per_spawn"], a1["per_spawn"])))
    out.append("")
    out.append("| total | base chars | head chars | Δ | head ≈ tokens |")
    out.append("|---|---:|---:|---:|---:|")
    for k in ("descriptions", "bodies", "rules", "skill_listing", "agent_listing", "per_spawn"):
        out.append("| %s | %d | %d | %s | %d |" % (k, base[k], head[k], pct(base[k], head[k]), tok(head[k])))
    common = [n for n in base["agents"] if n in head["agents"]]
    b0 = sum(base["agents"][n]["body"] for n in common)
    b1 = sum(head["agents"][n]["body"] for n in common)
    out.append("| bodies (agents at base) | %d | %d | %s | %d |" % (b0, b1, pct(b0, b1), tok(b1)))
    return "\n".join(out)


# ---------------------------------------------------------------- turns
def quantile(xs, q):
    xs = sorted(xs)
    if not xs:
        return 0
    k = (len(xs) - 1) * q
    lo, hi = math.floor(k), math.ceil(k)
    return xs[lo] + (xs[hi] - xs[lo]) * (k - lo)


def is_prompt(content):
    """A user message that is a new prompt (text), not only tool results."""
    if isinstance(content, str):
        return bool(content.strip())
    if isinstance(content, list):
        kinds = {c.get("type") for c in content if isinstance(c, dict)}
        return "text" in kinds and "tool_result" not in kinds
    return False


def turns(pattern):
    by_type = {}
    for meta in glob.glob(os.path.expanduser(pattern), recursive=True):
        try:
            atype = json.load(open(meta)).get("agentType") or "?"
        except (OSError, ValueError):
            continue
        # maxTurns binds each segment: a SendMessage resume (a user message with text, not a tool
        # result) starts a fresh budget, so a run counts as its longest segment.
        segs = [set()]
        try:
            with open(meta[:-len(".meta.json")] + ".jsonl") as fh:
                for line in fh:
                    try:
                        ev = json.loads(line)
                    except ValueError:
                        continue
                    msg = ev.get("message") or {}
                    if ev.get("type") == "assistant" and msg.get("id"):
                        segs[-1].add(msg["id"])
                    elif ev.get("type") == "user" and segs[-1] and is_prompt(msg.get("content")):
                        segs.append(set())
        except OSError:
            continue
        by_type.setdefault(atype, []).append(max(len(s) for s in segs))
    out = ["Turns per subagent run (one turn = one assistant message id; a run = its longest segment "
           "between SendMessage resumes), from `%s`." % pattern, "",
           "| agent type | runs | p50 | p90 | max |", "|---|---:|---:|---:|---:|"]
    for t, xs in sorted(by_type.items()):
        out.append("| %s | %d | %.0f | %.0f | %d |" % (t, len(xs), quantile(xs, .5), quantile(xs, .9), max(xs)))
    return "\n".join(out), by_type


# ---------------------------------------------------------------- main
def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--base", default=None)
    ap.add_argument("--head", default=None, help="measure this revision instead of the working tree")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--turns", nargs="?", const="~/.claude/projects/**/subagents/agent-*.meta.json")
    args = ap.parse_args(argv)

    if args.turns:
        text, data = turns(args.turns)
        print(json.dumps(data, indent=1, sort_keys=True) if args.json else text)
        return 0

    if args.head and not rev_exists(args.head):
        print("prompt_budget: head revision %r not found" % args.head, file=sys.stderr)
        return 2
    head = measure(Tree(args.head))
    base = None
    if args.base:
        if rev_exists(args.base):
            base = measure(Tree(args.base))
        else:
            print("prompt_budget: base revision %r not found; ratio checks skipped" % args.base,
                  file=sys.stderr)
    if args.json:
        print(json.dumps({"head": head, "base": base}, indent=1, sort_keys=True))
    else:
        print(table(head, base, args.base))
    if args.check:
        bad = check(head, base)
        for b in bad:
            print("prompt_budget: FAIL %s" % b, file=sys.stderr)
        if bad:
            return 1
        print("prompt_budget: check ok", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
