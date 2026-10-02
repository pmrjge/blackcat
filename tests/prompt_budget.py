#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""Static prompt budget of the stack's agents: what each spawn costs before it does any work.

Usage:
    uv run --script tests/prompt_budget.py [--base REV] [--head REV] [--json] [--check] [--turns [GLOB]]

Per agent: description chars, body chars, maxTurns, whether it has the Agent tool, omitClaudeMd.
Shared: the rules file, the skill listing and the agent listings. The skill listing sums, over the
shipped skills, what lint_agents.skill_listing_entry counts: name + 4 + min(description,
skillListingMaxDescChars) for a listed skill, name + 2 for a skillOverrides "name-only" one, 0 for
"user-invocable-only", "off" or disable-model-invocation. The agent listing a subagent with the Agent
tool sees is the sum of name + description + tools line + 12 over every agent but blackcat; BlackCat's
own listing (blackcat_listing) sums the same over the agents its `Agent(...)` allowlist names. Per
spawn = body + rules (unless omitClaudeMd) + skill listing + agent listing (if the agent has Agent;
blackcat: blackcat_listing). Tokens ~ ceil(chars / 3).

--base REV   compare the working tree (head) with REV (read through `git show`); a table with deltas.
--head REV   measure REV instead of the working tree (the baseline table: --head <base rev>).
--check      exit 1 unless every description <= 200 chars, blackcat body <= 5,200 and, for agents
             absent at base, description <= 160 / body <= 2,400 (with Agent) or <= 120 / <= 1,400
             (leaf); and against the base (--base, default DEFAULT_BASE): bodies of the agents present
             at base <= 0.867 x base, agent listing <= 0.97 x, blackcat listing <= 0.96 x, skill listing
             <= 0.478 x, rules <= 0.95 x, mean per spawn of the base agents (blackcat excluded: it is the
             main thread, never spawned) <= 0.691 x. Ratios are skipped when the base revision is missing.
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
DEFAULT_BASE = "ad22962"   # phase-3 baseline (main after phase 2: 56 agents, 248 skills)
DESC_MAX = 200
BLACKCAT_BODY_MAX = 5200
# agents absent at base: (description cap, body cap) with the Agent tool / as a leaf
NEW_CAPS = {True: (160, 2400), False: (120, 1400)}
# Phase 3 (2026-10-02, base ad22962): agent bodies tightened to role, constraints, routing, output
# contract and one-line skill pointers (procedures moved to skills); the rules file got one canonical
# "Briefs and hand-backs" section; 36 skill modules folded into hub references and every description cut
# to <= 140. Measured against ad22962 (tests/prompt_budget.py --base ad22962, after ff4ed6e + Q4):
#   bodies 93,839 -> 77,964 (0.831 x)        agent_listing 15,330 -> 14,593 (0.952 x)
#   blackcat_listing 14,550 -> 13,828 (0.950 x)   skill_listing 30,782 -> 23,227 (0.755 x)
#   rules 12,198 -> 11,370 (0.932 x)          per_spawn_mean 55,240 -> 46,067 (0.834 x); leaf 43,510 -> 34,932
# Each gate is that ratio x 1.02, rounded down to 0.01 (the phase-2 convention), so the next change has
# ~1-2% headroom and any regrowth fails the check. Every absolute limit went down: against the phase-2
# gates (base 1a38c77) skill_listing 31,235 -> 23,394, agent_listing 15,631 -> 14,870, blackcat_listing
# 14,749 -> 13,968, rules 12,441 -> 11,588, per_spawn_mean 55,587 -> 46,954. bodies now covers all 56
# agents (78,825) where phase 2 gated the 39 base agents at 70,916 plus NEW_CAPS for the 17 newer ones
# (17 x 1,400..2,400 more), so it is lower too. NEW_CAPS stays for agents added after ad22962.
# Phase-2 history of these numbers (base 1a38c77):
# agent_listing and blackcat_listing: design E set 1.20 and 1.25 for 10 new agents. The user then
# asked for one expert per language (+7 agents: rust, haskell, julia, go, python, jvm, node). After
# trimming 27 existing descriptions to <= 150 (19 of them by a further 15-25 chars), the listings
# measured 15,330 (1.314 x base) and 14,550 (1.292 x); each gate is that measurement + 2%, rounded
# down to 0.01. The skill listing (0.63 x) and the mean per spawn (0.90 x) pay for it.
# bodies and rules (design E, rebased from 0abe3eb to 1a38c77): agents present at base may grow
# their bodies by at most 5% in sum (the "## Skills" lines naming the modules, plus the new routing
# targets in May-spawn sentences, and nothing else), and the global rules file, which every agent
# reads on every spawn, by at most 2% (wording fixes only; any new rule must displace an old one).
# New agents are capped one by one through NEW_CAPS instead of a ratio, since they have no base.
# skill_listing and per_spawn_mean (2026-10-02, the user's decision: no "name-only" skills, every
# description explanatory). Design E's 0.65 x and 0.92 x assumed 216 name-only skills (10,693 chars at
# 24beb76). With every description listed (mean ~110 chars, modules <= 140) and 8 skills folded into
# their hubs (248 left), the listing measures 30,782 (1.744 x base 17,647) and the base agents' mean
# per spawn 54,874 (1.402 x 39,146); each gate is that + 2%, rounded down to 0.01. The user's
# principle: loading skills on demand beats large agent prompts, so the listing is where that cost goes.
# Lookup design B1x+C (2026-10-02, .claude-work/agents-p3/lookup/lookup-eval.md): 83 hub modules are
# user-invocable-only (Read by path, marked `name`* in Skills lines and hub tables), and the Skills lines
# gained the cross-domain pointers the evaluation's misses showed. Measured against ad22962:
#   skill_listing 30,782 -> 14,437 (0.469 x)   per_spawn_mean 55,240 -> 37,446 (0.678 x); leaf -> 26,298
#   bodies -> 78,513 (0.837 x)   rules -> 11,534 (0.946 x)   agent and blackcat listings unchanged
# skill_listing and per_spawn_mean go down to ratio x 1.02 rounded down to 0.001 (to 0.01 it would
# leave 0.2% headroom on the listing). rules (x 1.02 = 0.964) would go up, so it keeps 0.95. bodies goes
# UP from 0.84 to 0.85: the verifier restored the one-line evidence gate (VERDICT pass when nothing is
# verifiably wrong; never ask back without evidence) the user asked for in the five reviewer prompts,
# which Q1 had dropped (~790 chars); measured 79,616 (0.848 x), so 0.85 leaves ~150 chars.
# bodies UP from 0.85 to 0.867 (2026-10-02, soft token limits): the verifier gained one line the user
# approved with the maxTurns fix (build work goes to a builder, or dispatches of <= ~90 tool calls;
# +183 chars); measured 79,815 (0.8505 x), x 1.02 rounded down to 0.001.
RATIO = {"bodies": 0.867, "agent_listing": 0.97, "blackcat_listing": 0.96, "skill_listing": 0.478,
         "rules": 0.95, "per_spawn_mean": 0.691}
# SKILL_BUDGET: Claude Code's listing budget is context window x chars/token x
# skillListingBudgetFraction = 1,000,000 x 3 x f for the 5.5 models (Claude Code 2.1.287), shared by the
# stack's skills and every plugin, bundled and claude.ai skill; over it, the least-used skills lose
# their description silently. Measured 2026-10-02 after the 83 hub modules went user-invocable-only
# (design B1x+C, .claude-work/agents-p3/lookup/lookup-eval.md; they are Read by path): stack 14,564
# chars (128 listed skills, with separators; lint counts it); plugins 2,919 (measured: document-skills,
# math-olympiad, skill-creator; LSP plugins list nothing), bundled ~3,950 and claude.ai-synced ~7,300
# (both estimated, lint NON_STACK) = 28,733. The fraction goes back from 0.0156 to 0.012: 36,000
# chars, 7,267 (25%) above that total (the default 0.01 would leave 4.4%). It is a cost-only knob (how
# many descriptions are kept; no permission, hook or sandbox changes).
SKILL_BUDGET = {"fraction": 0.012, "budget": 36_000, "stack": 14_564, "non_stack": 14_169}

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lint_agents import skill_listing_entry, split_top_level, leading_name  # noqa: E402


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


def agent_allowlist(tools):
    """Agent types named in an `Agent(a, b, ...)` tools entry, else None."""
    for t in split_top_level(tools, ","):
        m = re.match(r"^Agent\((.*)\)$", t.strip())
        if m:
            return [leading_name(x) for x in split_top_level(m.group(1), ",") if leading_name(x)]
    return None


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
        "allowlist": agent_allowlist(tools),
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
    overrides = settings.get("skillOverrides") if isinstance(settings.get("skillOverrides"), dict) else {}
    skills = 0
    for rel in tree.list(DOT + "/skills"):
        parts = rel.split("/")
        if len(parts) != 4 or parts[3] != "SKILL.md":
            continue
        text = tree.read(rel) or ""
        head = text.split("---", 2)[1] if text.startswith("---") else ""
        invocable = not re.search(r"(?m)^disable-model-invocation:\s*(true|yes|on|1)\s*$", head)
        d = re.search(r"(?m)^description:\s*(.*)$", head)
        skills += skill_listing_entry(parts[2], len(unquote(d.group(1))) if d else 0,
                                      overrides.get(parts[2], "on"), cap, invocable)
    rules = len(tree.read(RULES) or "")
    listing = sum(a["listing"] for n, a in agents.items() if n != "blackcat")
    bc = agents.get("blackcat")
    allow = set((bc or {}).get("allowlist") or [])
    bc_listing = sum(a["listing"] for n, a in agents.items() if n in allow and n != "blackcat")
    for n, a in agents.items():
        shown = bc_listing if n == "blackcat" else listing
        a["per_spawn"] = (a["body"] + (0 if a["omit_claude_md"] else rules) + skills
                          + (shown if a["has_agent"] else 0))
    spawned = [a for n, a in agents.items() if n != "blackcat"]
    return {"agents": agents, "rules": rules, "skill_listing": skills, "agent_listing": listing,
            "blackcat_listing": bc_listing,
            "bodies": sum(a["body"] for a in agents.values()),
            "descriptions": sum(a["description"] for a in agents.values()),
            "per_spawn": sum(a["per_spawn"] for a in agents.values()),
            "per_spawn_mean": mean(a["per_spawn"] for a in spawned),
            "per_spawn_mean_agent": mean(a["per_spawn"] for a in spawned if a["has_agent"]),
            "per_spawn_mean_leaf": mean(a["per_spawn"] for a in spawned if not a["has_agent"])}


def mean(xs):
    xs = list(xs)
    return round(sum(xs) / len(xs)) if xs else 0


def base_spawn_mean(head, base):
    """Mean per spawn over the agents present at base and head (blackcat excluded): (base, head)."""
    common = [n for n in base["agents"] if n in head["agents"] and n != "blackcat"]
    return (mean(base["agents"][n]["per_spawn"] for n in common),
            mean(head["agents"][n]["per_spawn"] for n in common))


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
    for n, a in sorted(head["agents"].items()):
        if n in base["agents"]:
            continue
        dmax, bmax = NEW_CAPS[bool(a.get("has_agent"))]
        kind = "with Agent" if a.get("has_agent") else "leaf"
        if a["description"] > dmax:
            bad.append("%s.md (new, %s): description %d chars > %d" % (n, kind, a["description"], dmax))
        if a["body"] > bmax:
            bad.append("%s.md (new, %s): body %d chars > %d" % (n, kind, a["body"], bmax))
    common = [n for n in base["agents"] if n in head["agents"]]
    b0 = sum(base["agents"][n]["body"] for n in common)
    b1 = sum(head["agents"][n]["body"] for n in common)
    if b1 > RATIO["bodies"] * b0:
        over = sorted(((head["agents"][n]["body"] - base["agents"][n]["body"], n) for n in common),
                      reverse=True)
        bad.append("bodies of base agents: %d chars > %.2f x %d = %d; grown most: %s"
                   % (b1, RATIO["bodies"], b0, RATIO["bodies"] * b0,
                      ", ".join("%s.md (+%d)" % (n, d) for d, n in over[:8] if d > 0)))
    for key in ("agent_listing", "blackcat_listing", "skill_listing", "rules"):
        if head.get(key, 0) > RATIO[key] * base.get(key, 0):
            bad.append("%s: %d chars > %.2f x %d = %d" % (key, head[key], RATIO[key], base[key],
                                                          RATIO[key] * base[key]))
    m0, m1 = base_spawn_mean(head, base)
    if m1 > RATIO["per_spawn_mean"] * m0:
        bad.append("per_spawn_mean of base agents: %d chars > %.2f x %d = %d"
                   % (m1, RATIO["per_spawn_mean"], m0, RATIO["per_spawn_mean"] * m0))
    return bad


# ---------------------------------------------------------------- report
TOTALS = ("descriptions", "bodies", "rules", "skill_listing", "agent_listing", "blackcat_listing",
          "per_spawn", "per_spawn_mean", "per_spawn_mean_agent", "per_spawn_mean_leaf")


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
        for k in TOTALS:
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
    for k in TOTALS:
        out.append("| %s | %d | %d | %s | %d |" % (k, base[k], head[k], pct(base[k], head[k]), tok(head[k])))
    common = [n for n in base["agents"] if n in head["agents"]]
    b0 = sum(base["agents"][n]["body"] for n in common)
    b1 = sum(head["agents"][n]["body"] for n in common)
    out.append("| bodies (agents at base) | %d | %d | %s | %d |" % (b0, b1, pct(b0, b1), tok(b1)))
    m0, m1 = base_spawn_mean(head, base)
    out.append("| per_spawn_mean (agents at base, no blackcat) | %d | %d | %s | %d |" % (m0, m1, pct(m0, m1), tok(m1)))
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
    if args.check and not args.base:
        args.base = DEFAULT_BASE
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
