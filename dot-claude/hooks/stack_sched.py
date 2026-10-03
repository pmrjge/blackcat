#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""stack_sched.py - scheduler advisor for the claude-agent-stack. A report tool: it plans and
replays, it changes no behaviour and no hook reads it.

A task graph (nodes with an agent type, a size, dependencies, write sets) is turned into waves
(barrier mode: every wave starts when the previous one ended) or per-node starts (release mode),
under the stack's fan-out caps, the write-set conflicts and the gui/accel locks, minimising
J = T_w + lambda * W (T_w weighted tokens, W makespan in seconds) with T_w <= (1 + eps) * T_w(baseline).
Exact search up to 14 nodes, list scheduling above (or when the search budget runs out; a warning
says so).

  uv run --script dot-claude/hooks/stack_sched.py plan graph.json [--mode barrier|release]
                                                   [--speed frugal|balanced|fast] [--json]
  uv run --script dot-claude/hooks/stack_sched.py next graph.json state.json
  uv run --script dot-claude/hooks/stack_sched.py replay --session ID --graph F
                                                   [--segments F --ledger F --prompts F --out F]
  uv run --script dot-claude/hooks/stack_sched.py emit-workflow      (disabled until the probe)

Exit codes: 0 ok, 1 invalid graph, 2 usage error.

Token unit (T_w): input + kappa_w * cache_write + kappa_r * cache_read per API call (output
excluded until its price ratio is read from the pricing page). kappa_w: 1.25 (5 minute cache),
2.0 (1 hour); kappa_r: 0.05 for Opus 5.5, 0.1 for the other models. The per-type numbers come from
the active model (state dir, refreshed by stack_usage.py; see active_model_path) or else
sched_model.json beside this file (schema in the stack's agents-sched plan, section b); without
either the built-in defaults below apply.

Small-n values are used, not just shown. Every type carries a status ("provisional" or "supported") and a
90% band (lo/med/hi for turns, sec_per_call and a multiplicative ctx factor) in sched_model.json. An estimate
has a median and a hi value; the safety factor of a quantity is w = hi/med - 1. The wave plan is built on
med x (1 + w) = hi for provisional types and on med for supported ones, so a provisional value never makes a plan
cheaper than its hi allows (an explicit `n` on a node is taken as given: only sec_per_call and ctx are widened).
Every limit is checked at hi, with a three-way verdict: fits (hi fits), does not fit (even med does not), uncertain
(med fits, hi does not), the types driving the uncertainty named. Checked: the type's maxTurns and soft token
limit (ctx per segment), the per-prompt soft limit (33M ctx; 80M with an orchestrator), the fan-out cap, and an
optional user budget (`plan --budget N`, in the hook's ctx unit). A type without its own band takes its pool's band;
without a pool band it is provisional with w = 1.0, a documented heuristic marked unverified.

Environment: STACK_SCHED_MODEL (model file), STACK_SCHED_LAMBDA (tokens per second; unset =
balanced, T_w(baseline)/W(baseline)), STACK_SCHED_TOKEN_SLACK (eps, default 0).
"""
from __future__ import annotations

import argparse
import bisect
import csv
import dataclasses
import fnmatch
import itertools
import json
import math
import os
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

# ---------------------------------------------------------------- constants (copied, not imported)
# agent_guard.py owns these; the values below are the ones of the commit this file was written
# against (READONLY_TYPES, DEFAULT_FANOUT_BY_TYPE, SOFT_LIMITS). The guard is never imported: it
# is a hook with side effects.
READONLY_TYPES = {"code-reviewer", "security-auditor", "verifier", "plan-reviewer", "claude-code-guide",
                  "proof-checker"}
DEFAULT_CAPS = {"fanout": 3, "fanout_by_type": {"orchestrator": 10, "god-coder": 6, "main-coder": 6,
                                                "ninja-coder": 5, "researcher": 4, "planner": 8,
                                                "plan-reviewer": 8},
                "depth": 3, "blackcat": 8, "workflow": 16}
RISK_TAGS = {"hook", "security", "prod", "gui", "accel"}
EXCLUSIVE_TAGS = ("gui", "accel")          # one agent on the screen; one accelerator job per device
SPEEDS = {"frugal": 0.25, "balanced": 1.0, "fast": 4.0}
BLACKCAT_WINDOW_S = 120.0                  # agent_guard.py BLACKCAT_DISPATCH_WINDOW_S: one prompt's dispatches start within it
SOFT_PROMPT_CTX = 33000000                 # per human prompt (agent_guard.py SOFT_PROMPT_CTX)
SOFT_PROMPT_CTX_BY_TYPE = {"orchestrator": 80000000}   # while one runs (agent_guard.py, same name)
UNVERIFIED_W = 1.0                         # safety factor when neither the type nor its pool has a band
RESUME_WARM_S = 270.0                      # a resume is only warm when the gap is under this
EXACT_MAX_NODES = 14
SEARCH_BUDGET = 1_500_000                  # state expansions before exact search gives up
SHARED_DOCS = ("README.md", "CONFIG.md", "**/FINAL-REPORT.md", "FINAL-REPORT.md", "mcp_servers.md",
               "stack.env.example", "install.sh")
SONNET_TYPES = {"blackcat", "browser-operator", "build-fixer", "claude-code-guide", "coder",
                "data-engineer", "db-engineer", "devops-engineer", "doc-specialist", "explore",
                "localizer", "mcp-broker", "scout", "test-engineer", "verifier"}
ONE_HOUR_TTL = {"orchestrator", "researcher", "main-coder", "ninja-coder", "god-coder", "ml-engineer",
                "dl-engineer", "llm-engineer", "quantum-engineer", "robotics-engineer", "data-scientist"}
SOFT_POOLS = {"builder": 19000000, "analyst": 8700000, "lookup": 450000, "artifact": 3100000}
SOFT_LIMITS = {"claude-code-engineer": 19000000, "scout": 390000, "claude-code-guide": 680000,
               "code-reviewer": 8700000, "verifier": 26000000, "coder": 19000000, "main-coder": 19000000,
               "planner": 8700000, "researcher": 8700000, "explore": 450000, "writer": 3100000,
               "browser-operator": 3100000}
ANALYST_TYPES = {"planner", "plan-reviewer", "researcher", "security-auditor", "proof-checker"}
LOOKUP_TYPES = {"explore", "oracle", "mcp-broker", "scout", "claude-code-guide"}
ARTIFACT_TYPES = {"writer", "browser-operator", "doc-specialist", "designer", "image-director",
                  "localizer", "motion-designer", "cg-artist"}

# (b) provisional defaults: turns M/L, ctx a/b, sec_per_call p50/p90, static_cc. S = M/2 (heuristic
# until the fit supplies p25). Types without a row use their pool's representative.
_TURNS = {"claude-code-engineer": (42, 83), "coder": (18, 107), "verifier": (37, 91),
          "code-reviewer": (41, 60), "planner": (27, 33), "researcher": (32, 48),
          "claude-code-guide": (5, 9), "scout": (5, 7), "explore": (7, 8), "main-coder": (44, 228),
          "writer": (9, 10), "browser-operator": (17, 37), "orchestrator": (2, 4)}
# ctx = a*n + b*n^2 (hook unit). claude-code-engineer from the plan (only Q1 and T6); the others are
# a quick least-squares fit over segments.csv (healthy first segments), provisional until
# sched_model.json exists.
_CTX = {"claude-code-engineer": (95000, 1300), "scout": (12044, 3987), "claude-code-guide": (20824, 2975),
        "code-reviewer": (25284, 1217), "verifier": (24929, 930), "researcher": (82033, 887),
        "coder": (31603, 1297), "browser-operator": (28814, 1047), "planner": (60000, 900),
        "explore": (12044, 3987), "main-coder": (95000, 1300), "writer": (28814, 1047),
        "orchestrator": (100000, 0)}
_SPC = {"claude-code-engineer": (14, 29), "planner": (34, 40), "code-reviewer": (12, 15),
        "verifier": (13, 24), "scout": (8, 9), "claude-code-guide": (8, 9), "explore": (7, 8),
        "researcher": (36, 46), "coder": (7, 22), "main-coder": (9, 13), "browser-operator": (15, 17),
        "writer": (44, 48), "orchestrator": (5, 20)}
_STATIC = {"scout": 28000, "claude-code-guide": 31000, "claude-code-engineer": 57000,
           "code-reviewer": 68000, "verifier": 46000, "coder": 35000, "researcher": 155000,
           "planner": 100000, "explore": 25000, "writer": 40000, "browser-operator": 40000,
           "main-coder": 60000, "orchestrator": 100000}   # upper bounds (smallest first-segment cache write seen)
_POOL_REP = {"builder": "claude-code-engineer", "analyst": "researcher", "lookup": "explore",
             "verifier": "verifier", "artifact": "writer", "reviewer": "code-reviewer"}


def pool_of(t: str) -> str:
    if t in ("verifier",):
        return "verifier"
    if t in ("code-reviewer", "security-auditor"):
        return "reviewer"
    if t in ANALYST_TYPES:
        return "analyst"
    if t in LOOKUP_TYPES:
        return "lookup"
    if t in ARTIFACT_TYPES:
        return "artifact"
    return "builder"


def _builtin_type(t: str) -> Dict[str, Any]:
    rep = t if t in _TURNS else _POOL_REP[pool_of(t)]
    m, l = _TURNS[rep]
    a, b = _CTX.get(rep, _CTX["claude-code-engineer"])
    p50, p90 = _SPC.get(rep, (14, 29))
    pool = pool_of(t)
    return {"model": "sonnet" if t in SONNET_TYPES else "opus",
            "ttl": "1h" if t in ONE_HOUR_TTL else "5m",
            "turns": {"S": max(1, m // 2), "M": m, "L": l}, "ctx": {"a": a, "b": b},
            "static_cc": _STATIC.get(rep, 57000), "sec_per_call": {"p50": p50, "p90": p90},
            "soft_limit": SOFT_LIMITS.get(t, SOFT_POOLS.get(pool)), "maxTurns": None,
            "n_seg": 0, "n_agents": 0, "source": "default" if t in _TURNS else "pool:" + pool}


class GraphError(ValueError):
    """The graph file or dict is not a valid task graph (CLI exit 1)."""


class ModelError(ValueError):
    """The model file exists but cannot be used (CLI exit 2)."""


# ---------------------------------------------------------------- model
def active_model_path() -> Optional[Path]:
    """The model the usage collector refreshes (stack_usage.py, stack_sched_refresh.py),
    ${XDG_STATE_HOME:-~/.local/state}/claude-agent-stack/sched_model.json, when it is a JSON object
    with a non-empty `types`; None otherwise."""
    xdg = os.environ.get("XDG_STATE_HOME") or str(Path.home() / ".local/state")
    p = Path(xdg) / "claude-agent-stack" / "sched_model.json"
    try:
        raw = json.loads(p.read_text())
    except (OSError, ValueError):
        return None
    return p if isinstance(raw, dict) and isinstance(raw.get("types"), dict) and raw["types"] else None


def default_model_path() -> Path:
    """STACK_SCHED_MODEL, else the active (refreshed) model, else the shipped file beside this script."""
    env = os.environ.get("STACK_SCHED_MODEL")
    return Path(env) if env else (active_model_path() or Path(__file__).resolve().with_name("sched_model.json"))


def load_model(path: Any = None) -> Dict[str, Any]:
    """The model: the built-in defaults, overridden per type and per key by `path` (default: the
    file beside this script, or STACK_SCHED_MODEL) when it exists. A missing file is not an error;
    an unreadable or non-object file is (ModelError)."""
    m: Dict[str, Any] = {"version": 0, "generated": None, "stack_hash": None, "sessions": 0,
                         "kappa": {"cache_write_5m": 1.25, "cache_write_1h": 2.0,
                                   "cache_read_opus": 0.05, "cache_read_other": 0.1, "output": None},
                         "types": {}, "pools": {}, "file": None}
    p = Path(path) if path else default_model_path()
    if not p.is_file():
        return m
    try:
        raw = json.loads(p.read_text())
    except (OSError, ValueError) as exc:
        raise ModelError("%s: %s" % (p, exc))
    if not isinstance(raw, dict):
        raise ModelError("%s: not a JSON object" % p)
    m["file"] = str(p)
    for k in ("version", "generated", "stack_hash", "sessions"):
        if k in raw:
            m[k] = raw[k]
    if isinstance(raw.get("kappa"), dict):
        m["kappa"].update(raw["kappa"])
    if isinstance(raw.get("pools"), dict):
        m["pools"] = raw["pools"]
    types = raw.get("types")
    if isinstance(types, dict):
        for t, v in types.items():
            if isinstance(v, dict):
                m["types"][t] = v
    # S1e keys, each kept only when well-formed (else the model behaves as before it had them)
    num = (lambda x: isinstance(x, (int, float)) and not isinstance(x, bool) and x >= 0)
    rc, fx, ri = raw.get("resume_ctx"), raw.get("fixer"), raw.get("run_interval")
    if isinstance(rc, dict) and num(rc.get("alpha")) and num(rc.get("gamma")):
        m["resume_ctx"] = rc
    if isinstance(fx, dict) and num(fx.get("reread")):
        m["fixer"] = fx
    if isinstance(ri, dict) and isinstance(ri.get("groups"), dict):
        m["run_interval"] = ri
    return m


def _merge(base: Dict[str, Any], over: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(base)
    for k, v in over.items():
        if v is None:
            continue
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = dict(out[k], **{kk: vv for kk, vv in v.items() if vv is not None})
        else:
            out[k] = v
    return out


def tinfo(m: Dict[str, Any], t: str) -> Dict[str, Any]:
    """Per-type numbers: built-in default overridden by the model file's row for the type."""
    return _merge(_builtin_type(t), m.get("types", {}).get(t, {}))


_MODEL_RE = re.compile(r"claude-(opus|sonnet|haiku|fable)-(\d+)(?:-(\d{1,2})(?!\d))?")


def _resolved_version(fam: str) -> Optional[str]:
    """major.minor of the model ID that ANTHROPIC_DEFAULT_<FAMILY>_MODEL gives the alias `fam`, else None."""
    mt = _MODEL_RE.search(os.environ.get("ANTHROPIC_DEFAULT_%s_MODEL" % fam.upper(), ""))
    if not mt or mt.group(1) != fam:
        return None
    return mt.group(2) + ("." + mt.group(3) if mt.group(3) else "")


def kappas(m: Dict[str, Any], t: str) -> Tuple[float, float]:
    """(kappa_w, kappa_r) for agent type `t`."""
    info = tinfo(m, t)
    k = m.get("kappa", {})
    kw = k.get("cache_write_1h", 2.0) if info.get("ttl") == "1h" else k.get("cache_write_5m", 1.25)
    cr = k.get("cache_read")
    if isinstance(cr, dict) and isinstance(cr.get("rules"), list):
        # rules: [{"family", "version", "value"}], default otherwise; the version measured per family
        fam = info.get("model") or ""
        ver = _resolved_version(fam) or str((k.get("models_measured") or {}).get(fam, ""))
        kr = cr.get("default", 0.1)
        for rule in cr["rules"]:
            if isinstance(rule, dict) and rule.get("family") == fam and str(rule.get("version")) == ver:
                kr = rule.get("value", kr)
    elif isinstance(cr, dict):
        fam = info.get("model") or ""
        mid = str((k.get("models_measured") or {}).get(fam, fam))
        keys = [x for x in cr if x not in ("default", "other") and x in mid]
        if keys:
            kr = cr[max(keys, key=len)]
        elif fam in cr:
            kr = cr[fam]
        else:
            kr = cr.get("default", cr.get("other", 0.1))
    elif isinstance(cr, (int, float)):
        kr = cr
    else:
        kr = k.get("cache_read_opus", 0.05) if info.get("model") == "opus" else k.get("cache_read_other", 0.1)
    return float(kw or 0), float(kr or 0)


# ---------------------------------------------------------------- graph
@dataclass
class Node:
    id: str
    a: str
    s: Optional[str] = None
    n: Optional[int] = None
    dep: List[str] = field(default_factory=list)
    w: List[str] = field(default_factory=list)
    rd: List[str] = field(default_factory=list)
    r: List[str] = field(default_factory=list)
    alt: Optional[str] = None
    spec: bool = False
    extra: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Graph:
    job: str
    speed: str
    nodes: List[Node]
    meta: Dict[str, Any] = field(default_factory=dict)

    def by_id(self) -> Dict[str, Node]:
        return {n.id: n for n in self.nodes}


@dataclass
class Issue:
    level: str          # "error" | "warn"
    node: Optional[str]
    msg: str


@dataclass
class Est:
    turns: int
    ctx_p50: float
    ctx_p90: float
    t_w: float
    wall_p50: float
    wall_p90: float
    # median and hi (the band's upper bound) of every quantity; *_plan is what the wave plan uses
    turns_hi: float = 0.0
    ctx_hi: float = 0.0
    t_w_hi: float = 0.0
    wall_hi: float = 0.0
    t_w_plan: float = 0.0
    wall_plan: float = 0.0
    # hi of one run (sched_model.json run_interval, S1e): what a per-node cap meets; 0.0 when the model has none
    turns_run_hi: float = 0.0
    ctx_run_hi: float = 0.0
    wall_run_hi: float = 0.0
    resume: bool = False                # planned as a resume of an agent whose prior segment peaked at node "peak"
    status: str = "provisional"
    source: str = "heuristic"          # band source: own | pool | heuristic (unverified)
    w: Dict[str, float] = field(default_factory=dict)      # safety factors hi/med - 1: turns, sec_per_call, ctx
    type: str = ""


@dataclass
class Check:
    name: str
    verdict: str                       # fits | uncertain | does not fit
    med: float
    hi: float
    limit: float
    drivers: List[str] = field(default_factory=list)


@dataclass
class Schedule:
    waves: List[List[str]]
    critical_path: List[str]
    tokens: float
    wall: float
    J: float
    J_baseline: float
    warnings: List[str] = field(default_factory=list)
    mode: str = "barrier"
    times: Dict[str, Tuple[float, float]] = field(default_factory=dict)
    variants: Dict[str, str] = field(default_factory=dict)     # node -> type actually used
    lam: float = 0.0
    caps: Dict[str, Any] = field(default_factory=dict)
    exact: bool = True
    tokens_baseline: float = 0.0
    wall_baseline: float = 0.0
    checks: List[Check] = field(default_factory=list)
    verdict: str = "fits"
    provisional: Dict[str, Dict[str, Any]] = field(default_factory=dict)


_NODE_KEYS = {"id", "a", "s", "n", "dep", "w", "rd", "r", "alt", "spec"}


def load_graph(src: Any) -> Graph:
    """Graph from a path or a dict. Raises GraphError: not an object, no nodes, bad or duplicate
    id, unknown dependency, self-dependency, cycle, bad size, bad speed, unknown risk tag."""
    if isinstance(src, (str, os.PathLike)):
        try:
            data = json.loads(Path(src).read_text())
        except (OSError, ValueError) as exc:
            raise GraphError("%s: %s" % (src, exc))
    else:
        data = src
    if not isinstance(data, dict):
        raise GraphError("graph must be a JSON object")
    raw_nodes = data.get("nodes")
    if not isinstance(raw_nodes, list) or not raw_nodes:
        raise GraphError("graph needs a non-empty 'nodes' list")
    speed = data.get("speed", "balanced")
    if speed not in SPEEDS:
        raise GraphError("speed must be one of %s, got %r" % ("|".join(SPEEDS), speed))
    nodes: List[Node] = []
    seen = set()
    for i, rn in enumerate(raw_nodes):
        if not isinstance(rn, dict):
            raise GraphError("node %d is not an object" % i)
        nid = rn.get("id")
        if not isinstance(nid, str) or not nid:
            raise GraphError("node %d has no string id" % i)
        if nid in seen:
            raise GraphError("duplicate node id %s" % nid)
        seen.add(nid)
        if not isinstance(rn.get("a"), str) or not rn["a"]:
            raise GraphError("node %s has no agent type 'a'" % nid)
        s, n = rn.get("s"), rn.get("n")
        if s is not None and s not in ("S", "M", "L"):
            raise GraphError("node %s: s must be S, M or L" % nid)
        if n is not None and (not isinstance(n, int) or isinstance(n, bool) or n < 1):
            raise GraphError("node %s: n must be a positive integer" % nid)
        for key in ("dep", "w", "rd", "r"):
            v = rn.get(key, [])
            if not isinstance(v, list) or not all(isinstance(x, str) for x in v):
                raise GraphError("node %s: %s must be a list of strings" % (nid, key))
        bad = [t for t in rn.get("r", []) if t not in RISK_TAGS]
        if bad:
            raise GraphError("node %s: unknown risk tag %s (allowed: %s)" % (nid, bad, "|".join(sorted(RISK_TAGS))))
        pk = rn.get("peak")
        if pk is not None and (not isinstance(pk, (int, float)) or isinstance(pk, bool) or pk < 0):
            raise GraphError("node %s: peak must be a non-negative number (the resumed agent's prior peak context)" % nid)
        alt = rn.get("alt")
        if alt is not None and not isinstance(alt, str):
            raise GraphError("node %s: alt must be a string or null" % nid)
        nodes.append(Node(id=nid, a=rn["a"], s=s, n=n, dep=list(rn.get("dep", [])), w=list(rn.get("w", [])),
                          rd=list(rn.get("rd", [])), r=list(rn.get("r", [])), alt=alt,
                          spec=bool(rn.get("spec", False)),
                          extra={k: v for k, v in rn.items() if k not in _NODE_KEYS}))
    ids = {n.id for n in nodes}
    for n in nodes:
        for d in n.dep:
            if d not in ids:
                raise GraphError("node %s depends on unknown node %s" % (n.id, d))
            if d == n.id:
                raise GraphError("node %s depends on itself" % n.id)
    _toposort_or_raise(nodes)
    meta = {k: v for k, v in data.items() if k not in ("job", "speed", "nodes")}
    return Graph(job=str(data.get("job", "job")), speed=speed, nodes=nodes, meta=meta)


def _toposort_or_raise(nodes: Sequence[Node]) -> List[str]:
    indeg = {n.id: len(set(n.dep)) for n in nodes}
    kids: Dict[str, List[str]] = {n.id: [] for n in nodes}
    for n in nodes:
        for d in set(n.dep):
            kids[d].append(n.id)
    ready = [i for i, k in indeg.items() if k == 0]
    out: List[str] = []
    while ready:
        x = ready.pop()
        out.append(x)
        for c in kids[x]:
            indeg[c] -= 1
            if indeg[c] == 0:
                ready.append(c)
    if len(out) != len(nodes):
        cyc = sorted(i for i, k in indeg.items() if k > 0)
        raise GraphError("dependency cycle among %s" % ", ".join(cyc))
    return out


def _glob_overlap(a: str, b: str) -> bool:
    """Conservative: could two write globs name the same file?"""
    sa, sb = a.strip("/").split("/"), b.strip("/").split("/")
    for i in range(max(len(sa), len(sb))):
        if i >= len(sa) or i >= len(sb):
            short, last = (sa, sa[-1]) if len(sa) < len(sb) else (sb, sb[-1])
            return not any(ch in last for ch in "*?[")          # a plain directory covers what is below
        x, y = sa[i], sb[i]
        if x == "**" or y == "**":
            return True
        if x == y or fnmatch.fnmatch(x, y) or fnmatch.fnmatch(y, x):
            continue
        if any(ch in x for ch in "*?[") and any(ch in y for ch in "*?["):
            fx, fy = _first_chars(x), _first_chars(y)
            if fx is not None and fy is not None and not (fx & fy):
                return False                                      # e.g. [a-m]* and [n-z]*
            continue                                              # two patterns: maybe the same name
        return False
    return True


def _first_chars(seg: str) -> Optional[set]:
    """The characters a name matching `seg` can start with, None when any."""
    if not seg or seg[0] in "*?":
        return None
    if seg[0] != "[":
        return {seg[0]}
    end = seg.find("]", 2)
    if end < 0:
        return None
    body, out, i = seg[1:end], set(), 0
    if body[:1] in "!^":
        return None
    while i < len(body):
        if i + 2 < len(body) and body[i + 1] == "-":
            out |= {chr(c) for c in range(ord(body[i]), ord(body[i + 2]) + 1)}
            i += 3
        else:
            out.add(body[i])
            i += 1
    return out


def _sets_overlap(xs: Sequence[str], ys: Sequence[str], ignore: Sequence[str] = ()) -> bool:
    for x in xs:
        if any(fnmatch.fnmatch(x, g) for g in ignore):
            continue
        for y in ys:
            if any(fnmatch.fnmatch(y, g) for g in ignore):
                continue
            if _glob_overlap(x, y):
                return True
    return False


def _closure(nodes: Sequence[Node]) -> Dict[str, set]:
    byid = {n.id: n for n in nodes}
    memo: Dict[str, set] = {}

    def anc(i: str) -> set:
        if i in memo:
            return memo[i]
        s: set = set()
        for d in byid[i].dep:
            s.add(d)
            s |= anc(d)
        memo[i] = s
        return s

    for n in nodes:
        anc(n.id)
    return memo


def validate(g: Graph, m: Dict[str, Any], policy: Optional[Dict[str, Any]] = None) -> List[Issue]:
    """Issues for a graph. Errors: a read-only type with a write set, a risk tag the type cannot
    carry. Warnings: unknown type, unsized node, concurrent write/write or write/read overlap
    (the scheduler serialises these), fan-out above the cap, more nodes than a Workflow takes."""
    pol = policy or {}
    readonly = set(pol.get("readonly", READONLY_TYPES))
    known = pol.get("types")
    caps = dict(DEFAULT_CAPS, **(pol.get("caps") or {}))
    out: List[Issue] = []
    for n in g.nodes:
        for t, what in ((n.a, "type"), (n.alt, "alt type")):
            if t is None:
                continue
            if t in readonly and n.w:
                out.append(Issue("error", n.id, "read-only type %s cannot have a write set (%s)" % (t, ", ".join(n.w[:3]))))
            if known is not None and t not in known:
                out.append(Issue("error", n.id, "%s %s is not in the roster" % (what, t)))
            elif known is None and t not in m.get("types", {}) and t not in _TURNS and t not in SONNET_TYPES \
                    and t not in ONE_HOUR_TTL and t not in ANALYST_TYPES and t not in READONLY_TYPES:
                out.append(Issue("warn", n.id, "%s %s: no model row, pool defaults used" % (what, t)))
        if n.s is None and n.n is None:
            out.append(Issue("warn", n.id, "no size (s or n): M assumed"))
        if "gui" in n.r and n.a in ("coder", "scout", "explore"):
            out.append(Issue("warn", n.id, "gui tag on %s: the screen belongs to computer-use agents" % n.a))
    anc = _closure(g.nodes)
    for x, y in itertools.combinations(g.nodes, 2):
        if x.id in anc[y.id] or y.id in anc[x.id]:
            continue
        if _sets_overlap(x.w, y.w):
            out.append(Issue("warn", x.id, "write set overlaps %s with no dependency between them: they will be serialised" % y.id))
        elif (x.a not in readonly and _sets_overlap(y.w, x.rd)) or (y.a not in readonly and _sets_overlap(x.w, y.rd)):
            out.append(Issue("warn", x.id, "reads what %s writes with no dependency between them: serialised" % y.id))
    cap = effective_cap(g, caps)
    width = _max_width(g)
    if width > cap:
        out.append(Issue("warn", None, "up to %d nodes are ready at once, the fan-out cap is %d: waves will be split" % (width, cap)))
    if g.meta.get("dispatcher") == "blackcat" and len(g.nodes) > caps["blackcat"]:
        out.append(Issue("warn", None, "%d nodes dispatched by BlackCat exceed %d Agent calls per prompt: the guard blocks the rest"
                         % (len(g.nodes), caps["blackcat"])))
    if len(g.nodes) > caps["workflow"]:
        out.append(Issue("warn", None, "%d nodes exceed the Workflow cap of %d" % (len(g.nodes), caps["workflow"])))
    return out


def _max_width(g: Graph) -> int:
    level: Dict[str, int] = {}
    byid = g.by_id()
    for i in _toposort_or_raise(g.nodes):
        level[i] = 1 + max([level[d] for d in byid[i].dep], default=-1)
    counts: Dict[int, int] = {}
    for v in level.values():
        counts[v] = counts.get(v, 0) + 1
    return max(counts.values())


def effective_cap(g: Graph, caps: Optional[Dict[str, Any]]) -> int:
    c = dict(DEFAULT_CAPS, **(caps or {}))
    if isinstance(c.get("fanout"), int) and caps and "fanout" in caps:
        return max(1, int(caps["fanout"]))
    disp = g.meta.get("dispatcher")
    if disp == "blackcat":
        return int(c["blackcat"])
    if disp in c["fanout_by_type"]:
        return int(c["fanout_by_type"][disp])
    return int(c["fanout"])


# ---------------------------------------------------------------- estimate
def _ctx(info: Dict[str, Any], n: float) -> float:
    return info["ctx"]["a"] * n + info["ctx"]["b"] * n * n


def clamp_band(band: Any) -> Optional[Dict[str, Any]]:
    """The band with lo <= med <= hi for turns, sec_per_call and ctx: lo is lowered to med and hi raised to med when
    they sit on the wrong side (so a hi factor below 1 becomes 1). Entries that are not numbers are dropped."""
    if not isinstance(band, dict):
        return None
    out = dict(band)
    for q in ("turns", "sec_per_call", "ctx"):
        d = band.get(q)
        try:
            med = float(d["med"])
            lo, hi = float(d.get("lo", med)), float(d.get("hi", med))
        except (KeyError, TypeError, ValueError, AttributeError):
            out.pop(q, None)
            continue
        out[q] = dict(d, lo=min(lo, med), med=med, hi=max(hi, med))
    return out


def band_of(m: Dict[str, Any], t: str) -> Dict[str, Any]:
    """Status and hi/med factors of type `t`: its own band, else its pool's, else the unverified heuristic
    (provisional, w = UNVERIFIED_W). Factors are never below 1: a band cannot make a plan cheaper."""
    info = tinfo(m, t)
    status, band, src = info.get("status"), clamp_band(info.get("band")), "own"

    def ok(b: Any) -> bool:
        return isinstance(b, dict) and all(isinstance(b.get(k), dict) and b[k].get("med") for k in ("turns", "sec_per_call"))

    pname = info.get("tier") or {"reviewer": "analyst"}.get(pool_of(t), pool_of(t))
    if not ok(band):
        prow = (m.get("pools") or {}).get(pname)
        if isinstance(prow, dict) and ok(clamp_band(prow.get("band"))):
            band, src, status = clamp_band(prow["band"]), "pool", "provisional"
        else:
            band, src, status = None, "heuristic", "provisional"
    if status not in ("provisional", "supported"):
        status = "provisional"

    def f(q: str) -> float:
        d = (band or {}).get(q)
        if not d and src == "own":
            # own band without this quantity (e.g. no usable ctx): the pool's band, else the unverified heuristic
            pb = clamp_band(((m.get("pools") or {}).get(pname) or {}).get("band"))
            d = (pb or {}).get(q)
            if not d:
                return 1.0 + UNVERIFIED_W
        try:
            return max(1.0, float(d["hi"]) / float(d["med"])) if d else 1.0 + UNVERIFIED_W
        except (KeyError, TypeError, ValueError, ZeroDivisionError):
            return 1.0 + UNVERIFIED_W

    return {"status": status, "source": src, "turns": f("turns"), "sec_per_call": f("sec_per_call"),
            "ctx": f("ctx") if (band or {}).get("ctx") or src == "own" or band is None else 1.0}


def _run_factor(m: Dict[str, Any], t: str, resume: bool, q: str) -> float:
    """hi factor of one run (run_interval, S1e step 4) for quantity q, by group <tier>:fresh|resume, else the
    pooled group; 0.0 when the model has no run interval."""
    ri = m.get("run_interval")
    if not isinstance(ri, dict) or not isinstance(ri.get("groups"), dict):
        return 0.0
    tier = tinfo(m, t).get("tier") or {"reviewer": "analyst"}.get(pool_of(t), pool_of(t))
    for grp in ("%s:%s" % (tier, "resume" if resume else "fresh"), "pooled"):
        try:
            return max(1.0, float(ri["groups"][grp][q]["hi"]))
        except (KeyError, TypeError, ValueError):
            continue
    return 0.0


def _est_for(m: Dict[str, Any], t: str, s: Optional[str], n: Optional[int], peak: Optional[float] = None) -> Est:
    info = tinfo(m, t)
    tu = info["turns"]
    n50 = int(n) if n else max(1, int(round(float(tu[s or "M"]))))
    n90 = int(n) if n else max(n50, int(round(float(tu["L"]))))
    kw, kr = kappas(m, t)
    rc = m.get("resume_ctx") if isinstance(m.get("resume_ctx"), dict) else None
    resume = peak is not None and rc is not None

    def cx(k: float) -> float:
        # a resume re-reads its prior context on every call: n * (prior peak + alpha + gamma * n) (S1e step 3)
        if resume:
            return k * (float(peak) + float(rc["alpha"]) + float(rc["gamma"]) * k)
        return _ctx(info, k)

    def tw(k: float) -> float:
        total = cx(k)
        if resume:
            last = float(rc["alpha"]) + 2 * float(rc["gamma"]) * k     # growth written during a warm resume
        else:
            last = info["ctx"]["a"] + 2 * info["ctx"]["b"] * k          # context size at the last call = cache written in total
        last = min(last, total)
        return kw * last + kr * (total - last)

    spc = info["sec_per_call"]
    b = band_of(m, t)
    n_hi = float(n50) if n else n50 * b["turns"]
    wall_med = n50 * float(spc["p50"])
    wall_hi = n_hi * float(spc["p50"]) * b["sec_per_call"]
    tw_med, tw_hi = tw(n50), tw(n_hi) * b["ctx"]
    prov = b["status"] == "provisional"
    rt, rx, rw = (_run_factor(m, t, peak is not None, q) for q in ("turns", "ctx", "wall"))
    return Est(turns=n50, ctx_p50=cx(n50), ctx_p90=cx(n90), t_w=tw_med,
               wall_p50=wall_med, wall_p90=n90 * float(spc["p90"]),
               turns_hi=n_hi, ctx_hi=cx(n_hi) * b["ctx"], t_w_hi=tw_hi, wall_hi=wall_hi,
               t_w_plan=tw_hi if prov else tw_med, wall_plan=wall_hi if prov else wall_med,
               turns_run_hi=(float(n50) if n else n50 * rt) if rt else 0.0, ctx_run_hi=cx(n50) * rx if rx else 0.0,
               wall_run_hi=wall_med * rw if rw else 0.0, resume=resume,
               status=b["status"], source=b["source"],
               w={"turns": b["turns"] - 1.0, "sec_per_call": b["sec_per_call"] - 1.0, "ctx": b["ctx"] - 1.0}, type=t)


def _peak(nd: Node) -> Optional[float]:
    v = nd.extra.get("peak")
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def estimate(g: Graph, m: Dict[str, Any]) -> Dict[str, Est]:
    """{node id: Est} for the primary type: turns (p50), ctx (a*n + b*n^2) at p50 and p90 turns,
    T_w (kappa_w * context written + kappa_r * context re-read) and wall time at p50/p90 (the median fields),
    plus the band's hi values, the safety factors and the values the plan uses (*_plan)."""
    return {n.id: _est_for(m, n.a, n.s, n.n, _peak(n)) for n in g.nodes}


# ---------------------------------------------------------------- scheduling core
def _bottom_levels(dur: Sequence[float], deps: Sequence[Sequence[int]], lat: float) -> List[float]:
    n = len(dur)
    kids: List[List[int]] = [[] for _ in range(n)]
    for i, ds in enumerate(deps):
        for d in ds:
            kids[d].append(i)
    bl = [0.0] * n
    order = _topo_idx(n, deps)
    for i in reversed(order):
        bl[i] = dur[i] + max([bl[c] + lat for c in kids[i]], default=0.0)
    return bl


def _topo_idx(n: int, deps: Sequence[Sequence[int]]) -> List[int]:
    indeg = [len(set(d)) for d in deps]
    kids: List[List[int]] = [[] for _ in range(n)]
    for i, ds in enumerate(deps):
        for d in set(ds):
            kids[d].append(i)
    ready = [i for i in range(n) if indeg[i] == 0]
    out: List[int] = []
    while ready:
        x = ready.pop(0)
        out.append(x)
        for c in kids[x]:
            indeg[c] -= 1
            if indeg[c] == 0:
                ready.append(c)
    return out


class _Budget(Exception):
    pass


def _solve(dur: Sequence[float], deps: Sequence[Sequence[int]], cap: int, mode: str,
           conf: Sequence[Sequence[bool]], rel: Sequence[float], lat: float,
           exact: bool = True) -> Tuple[List[float], List[float], bool]:
    """(starts, ends, was_exact). Times are relative to the window start. barrier: waves; release:
    each node starts when it can."""
    n = len(dur)
    if n == 0:
        return [], [], True
    if exact and n <= EXACT_MAX_NODES:
        try:
            if mode == "barrier":
                return _barrier_exact(dur, deps, cap, conf, rel, lat) + (True,)
            return _release_exact(dur, deps, cap, conf, rel, lat) + (True,)
        except _Budget:
            pass
    if mode == "barrier":
        s, e = _barrier_list(dur, deps, cap, conf, rel, lat)
    else:
        s, e = _release_list(dur, deps, cap, conf, rel, lat)
    return s, e, False


def _wave_start(prev_end: Optional[float], members: Sequence[int], rel: Sequence[float], lat: float) -> float:
    base = 0.0 if prev_end is None else prev_end + lat
    return max([base] + [rel[i] for i in members])


def _barrier_exact(dur, deps, cap, conf, rel, lat):
    n = len(dur)
    full = (1 << n) - 1
    dmask = [sum(1 << d for d in set(ds)) for ds in deps]
    cmask = [sum(1 << j for j in range(n) if conf[i][j]) for i in range(n)]
    all_rel0 = all(r == 0 for r in rel)
    memo: Dict[Tuple[int, float], Tuple[float, Optional[int]]] = {}
    work = [0]

    def best(mask: int, t: Optional[float]) -> Tuple[float, Optional[int]]:
        if mask == full:
            return (t or 0.0), None
        key = (mask, -1.0 if t is None else t)
        if key in memo:
            return memo[key]
        avail = [i for i in range(n) if not (mask >> i) & 1 and (dmask[i] & ~mask) == 0]
        res: Tuple[float, Optional[int]] = (math.inf, None)
        # enumerate conflict-free subsets of avail up to cap, keep the non-dominated ones
        subsets: List[Tuple[int, List[int]]] = []

        def rec(k: int, cur: List[int], cm: int) -> None:
            work[0] += 1
            if work[0] > SEARCH_BUDGET:
                raise _Budget()
            if k == len(avail):
                if cur:
                    subsets.append((sum(1 << x for x in cur), list(cur)))
                return
            x = avail[k]
            if len(cur) < cap and not (cmask[x] & cm):
                cur.append(x)
                rec(k + 1, cur, cm | (1 << x))
                cur.pop()
            rec(k + 1, cur, cm)

        rec(0, [], 0)
        for wm, members in subsets:
            st = _wave_start(t, members, rel, lat)
            en = st + max(dur[i] for i in members)
            if all_rel0 and len(members) < cap:        # dominated: a free rider fits in the wave
                dominated = False
                for x in avail:
                    if not (wm >> x) & 1 and dur[x] <= en - st and not any(conf[x][y] for y in members):
                        dominated = True
                        break
                if dominated:
                    continue
            val, _ = best(mask | wm, en)
            if val < res[0] - 1e-12:
                res = (val, wm)
        memo[key] = res
        return res

    best(0, None)
    starts = [0.0] * n
    ends = [0.0] * n
    mask, t = 0, None
    while mask != full:
        _, wm = memo[(mask, -1.0 if t is None else t)]
        members = [i for i in range(n) if (wm >> i) & 1]
        st = _wave_start(t, members, rel, lat)
        for i in members:
            starts[i], ends[i] = st, st + dur[i]
        t = st + max(dur[i] for i in members)
        mask |= wm
    return starts, ends


def _barrier_list(dur, deps, cap, conf, rel, lat):
    n = len(dur)
    bl = _bottom_levels(dur, deps, lat)
    done: set = set()
    starts = [0.0] * n
    ends = [0.0] * n
    t: Optional[float] = None
    while len(done) < n:
        avail = sorted((i for i in range(n) if i not in done and all(d in done for d in deps[i])),
                       key=lambda i: -bl[i])
        members: List[int] = []
        for i in avail:
            if len(members) < cap and not any(conf[i][j] for j in members):
                members.append(i)
        st = _wave_start(t, members, rel, lat)
        for i in members:
            starts[i], ends[i] = st, st + dur[i]
        t = st + max(dur[i] for i in members)
        done |= set(members)
    return starts, ends


def _feasible_start(i, t0, starts, ends, dur, cap, conf, placed):
    """Earliest t >= t0 with fewer than `cap` placed intervals active at every instant of
    [t, t+dur[i]) and no placed conflicting interval overlapping it."""
    cands = [t0] + sorted(e for j, e in ((j, ends[j]) for j in placed) if e > t0)
    for t in cands:
        e = t + dur[i]
        ok = True
        for j in placed:
            if conf[i][j] and starts[j] < e - 1e-9 and ends[j] > t + 1e-9:
                ok = False
                break
        if not ok:
            continue
        pts = [t] + [starts[j] for j in placed if t < starts[j] < e - 1e-9]
        for p in pts:
            if sum(1 for j in placed if starts[j] <= p + 1e-9 < ends[j]) >= cap:
                ok = False
                break
        if ok:
            return t
    return cands[-1]


def _release_list(dur, deps, cap, conf, rel, lat):
    n = len(dur)
    bl = _bottom_levels(dur, deps, lat)
    order = sorted(_topo_idx(n, deps), key=lambda i: -bl[i])
    starts = [0.0] * n
    ends = [0.0] * n
    placed: List[int] = []
    pending = list(range(n))
    while pending:
        # highest priority node whose predecessors are all placed
        i = next(x for x in order if x in pending and all(d in placed for d in deps[x]))
        t0 = max([rel[i]] + [ends[d] + lat for d in deps[i]])
        t = _feasible_start(i, t0, starts, ends, dur, cap, conf, placed)
        starts[i], ends[i] = t, t + dur[i]
        placed.append(i)
        pending.remove(i)
    return starts, ends


def _release_exact(dur, deps, cap, conf, rel, lat):
    n = len(dur)
    bl = _bottom_levels(dur, deps, lat)
    s0, e0 = _release_list(dur, deps, cap, conf, rel, lat)
    best = [max(e0), s0[:], e0[:]]
    starts = [0.0] * n
    ends = [0.0] * n
    work = [0]
    kids: List[List[int]] = [[] for _ in range(n)]
    for i, ds in enumerate(deps):
        for d in ds:
            kids[d].append(i)

    def rec(placed: List[int], cur_max: float) -> None:
        work[0] += 1
        if work[0] > SEARCH_BUDGET // 20:
            raise _Budget()
        if len(placed) == n:
            if cur_max < best[0] - 1e-9:
                best[0], best[1], best[2] = cur_max, starts[:], ends[:]
            return
        pl = set(placed)
        elig = [i for i in range(n) if i not in pl and all(d in pl for d in deps[i])]
        # bound: every unplaced node needs its own chain after its earliest start
        lb = cur_max
        for i in range(n):
            if i in pl:
                continue
            est = rel[i]
            for d in deps[i]:
                if d in pl:
                    est = max(est, ends[d] + lat)
            lb = max(lb, est + bl[i])
        if lb >= best[0] - 1e-9:
            return
        cands = []
        for i in elig:
            t0 = max([rel[i]] + [ends[d] + lat for d in deps[i]])
            t = _feasible_start(i, t0, starts, ends, dur, cap, conf, placed)
            cands.append((t, -bl[i], i))
        cands.sort()
        for t, _, i in cands:
            starts[i], ends[i] = t, t + dur[i]
            placed.append(i)
            rec(placed, max(cur_max, ends[i]))
            placed.pop()

    rec([], 0.0)
    return best[1], best[2]


# ---------------------------------------------------------------- schedule
def _conflicts(g: Graph, rules: Dict[str, Any]) -> List[List[bool]]:
    nodes = g.nodes
    n = len(nodes)
    anc = _closure(nodes)
    ignore = SHARED_DOCS if rules.get("fragments", True) else ()
    c = [[False] * n for _ in range(n)]
    for i, j in itertools.combinations(range(n), 2):
        x, y = nodes[i], nodes[j]
        if x.id in anc[y.id] or y.id in anc[x.id]:
            continue
        hit = _sets_overlap(x.w, y.w, ignore)
        if not hit and rules.get("rw", True):
            hit = (x.a not in READONLY_TYPES and _sets_overlap(y.w, x.rd, ignore)) or \
                  (y.a not in READONLY_TYPES and _sets_overlap(x.w, y.rd, ignore))
        if not hit:
            hit = any(t in x.r and t in y.r for t in EXCLUSIVE_TAGS)
        c[i][j] = c[j][i] = hit
    return c


def _env_float(name: str) -> Optional[float]:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def schedule(g: Graph, m: Dict[str, Any], mode: str = "barrier", caps: Optional[Dict[str, Any]] = None,
             lam: Optional[float] = None, slack: Optional[float] = 0.0, *,
             durations: Optional[Dict[str, float]] = None, release: Optional[Dict[str, float]] = None,
             lat: float = 0.0, rules: Optional[Dict[str, Any]] = None,
             exact: bool = True, budget: Optional[float] = None) -> Schedule:
    """Schedule the graph. mode "barrier": waves; "release": per-node starts. Minimises
    J = T_w + lam * W over the variant of each node (primary type or its `alt`) and the order,
    subject to T_w <= (1 + eps) * T_w(baseline), the cap, write-set conflicts and gui/accel locks.
    `durations` (node id -> seconds) replaces the model's wall_p50 (alternatives are then ignored),
    `release` is an earliest start per node, `lat` a dispatch latency after each dependency."""
    if mode not in ("barrier", "release"):
        raise ValueError("mode must be barrier or release")
    rules = rules or {}
    nodes = g.nodes
    n = len(nodes)
    idx = {nd.id: i for i, nd in enumerate(nodes)}
    deps = [[idx[d] for d in nd.dep] for nd in nodes]
    cap = effective_cap(g, caps)
    conf = _conflicts(g, rules)
    rel = [float((release or {}).get(nd.id, 0.0)) for nd in nodes]
    prim = [_est_for(m, nd.a, nd.s, nd.n, _peak(nd)) for nd in nodes]
    alt = [(_est_for(m, nd.alt, nd.s, nd.n, _peak(nd)) if nd.alt and not durations else None) for nd in nodes]
    pdur = [float((durations or {}).get(nd.id, prim[i].wall_plan)) for i, nd in enumerate(nodes)]
    ptok = [p.t_w_plan for p in prim]
    warnings: List[str] = []

    # baseline: level barrier list schedule, primary variants
    bs, be, _ = _solve(pdur, deps, cap, "barrier", conf, rel, lat, exact=False)
    w_base = max(be) if be else 0.0
    t_base = sum(ptok)
    speed = SPEEDS[g.speed]
    if lam is not None:
        lam_eff = float(lam)
    else:
        env = _env_float("STACK_SCHED_LAMBDA")
        lam_eff = (env if env is not None else (t_base / w_base if w_base > 0 else 0.0)) * speed
    eps = slack if slack else (_env_float("STACK_SCHED_TOKEN_SLACK") or 0.0)
    j_base = t_base + lam_eff * w_base

    alt_idx = [i for i in range(n) if alt[i] is not None]

    def variant(sel: Sequence[int]) -> Tuple[List[float], float]:
        d = list(pdur)
        tk = list(ptok)
        for i in sel:
            d[i], tk[i] = alt[i].wall_plan, alt[i].t_w_plan
        return d, sum(tk)

    cap_t = (1.0 + eps) * t_base + 1e-9
    solved: Dict[Tuple[int, ...], Tuple[List[float], List[float], bool, float, float]] = {}

    def run(sel: Tuple[int, ...]):
        if sel in solved:
            return solved[sel]
        d, tk = variant(sel)
        s, e, ex = _solve(d, deps, cap, mode, conf, rel, lat, exact=exact)
        w = max(e) if e else 0.0
        solved[sel] = (s, e, ex, tk, w)
        return solved[sel]

    cand_sets: List[Tuple[int, ...]] = [()]
    if alt_idx:
        if len(alt_idx) <= 5:
            cand_sets = [tuple(c) for r in range(len(alt_idx) + 1) for c in itertools.combinations(alt_idx, r)]
        else:
            warnings.append("%d alternatives: greedy choice, not exhaustive" % len(alt_idx))
    best_sel, best_j = (), math.inf
    if len(alt_idx) <= 5:
        for sel in cand_sets:
            s, e, ex, tk, w = run(sel)
            if tk > cap_t:
                continue
            j = tk + lam_eff * w
            if j < best_j - 1e-9:
                best_sel, best_j = sel, j
    else:
        cur: Tuple[int, ...] = ()
        s, e, ex, tk, w = run(cur)
        best_sel, best_j = cur, tk + lam_eff * w
        improved = True
        while improved:
            improved = False
            for i in alt_idx:
                sel = tuple(sorted(set(cur) ^ {i}))
                s, e, ex, tk, w = run(sel)
                if tk <= cap_t and tk + lam_eff * w < best_j - 1e-9:
                    cur, best_sel, best_j, improved = sel, sel, tk + lam_eff * w, True
    s, e, ex, tk, w = run(best_sel)
    d_used, _ = variant(best_sel)
    if not ex and n > EXACT_MAX_NODES:
        warnings.append("%d nodes: list scheduling (exact search stops at %d)" % (n, EXACT_MAX_NODES))
    elif not ex and exact:
        warnings.append("search budget exhausted: list schedule, not proven optimal")
    # waves: nodes grouped by start time
    order = sorted(range(n), key=lambda i: (s[i], e[i], i))
    waves: List[List[str]] = []
    last = None
    for i in order:
        if last is None or abs(s[i] - last) > 1e-9:
            waves.append([])
            last = s[i]
        waves[-1].append(nodes[i].id)
    # critical path on the used durations (longest chain)
    bl = _bottom_levels(d_used, deps, lat)
    cp: List[str] = []
    if n:
        cur_i = max(range(n), key=lambda i: bl[i] if not deps[i] else -1)
        while True:
            cp.append(nodes[cur_i].id)
            kids = [c for c in range(n) if cur_i in deps[c]]
            if not kids:
                break
            cur_i = max(kids, key=lambda c: bl[c])
    # resume gaps
    byid = {nd.id: i for i, nd in enumerate(nodes)}
    for nd in nodes:
        src = nd.extra.get("resume")
        if src in byid:
            gap = s[byid[nd.id]] - e[byid[src]]
            if gap >= RESUME_WARM_S:
                warnings.append("%s resumes %s after %.0f s (>= %d s): cold rewrite or a fresh fixer" % (nd.id, src, gap, RESUME_WARM_S))
    for iss in validate(g, m):
        if iss.level == "error":
            warnings.append("%s: %s" % (iss.node or "graph", iss.msg))
    used = [(nodes[i], _est_for(m, nodes[i].alt if i in best_sel else nodes[i].a, nodes[i].s, nodes[i].n,
                                       _peak(nodes[i])))
            for i in range(n)]
    checks = limit_checks(m, used, max(len(wv) for wv in waves) if waves else 0, cap, budget,
                          dispatcher=g.meta.get("dispatcher"), starts=list(s))
    verdict = _worst([c.verdict for c in checks])
    prov = {}
    for _un, ue in used:
        if ue.status == "provisional":
            prov[ue.type] = {"source": ue.source, "w": ue.w, "unverified": ue.source == "heuristic"}
    return Schedule(waves=waves, critical_path=cp, tokens=tk, wall=w, J=tk + lam_eff * w, J_baseline=j_base,
                    warnings=warnings, mode=mode, times={nodes[i].id: (s[i], e[i]) for i in range(n)},
                    variants={nodes[i].id: (nodes[i].alt if i in best_sel else nodes[i].a) for i in range(n)},
                    lam=lam_eff, caps={"fanout": cap, "depth": DEFAULT_CAPS["depth"],
                                       "blackcat": DEFAULT_CAPS["blackcat"], "workflow": DEFAULT_CAPS["workflow"]},
                    exact=ex, tokens_baseline=t_base, wall_baseline=w_base, checks=checks, verdict=verdict,
                    provisional=prov)


_RANK = {"fits": 0, "uncertain": 1, "does not fit": 2}


def _worst(vs: Sequence[str]) -> str:
    return max(vs, key=lambda v: _RANK[v], default="fits")


def three_way(med: float, hi: float, limit: float) -> str:
    """fits: hi fits; does not fit: med does not fit; uncertain: med fits, hi does not."""
    if hi <= limit:
        return "fits"
    return "does not fit" if med > limit else "uncertain"


def limit_checks(m: Dict[str, Any], used: Sequence[Tuple[Node, Est]], width: int, cap: int,
                 budget: Optional[float] = None, dispatcher: Optional[str] = None,
                 starts: Optional[Sequence[float]] = None) -> List[Check]:
    """Limit checks of a plan at hi: per node maxTurns and soft token limit of its type, the plan's total ctx against
    the per-prompt soft limit and the optional user budget, the fan-out cap. Hard caps and the soft-limit table are
    read, never changed."""
    out: List[Check] = []
    for nd, e in used:
        info = tinfo(m, e.type)
        mt = info.get("maxTurns")
        if mt:
            out.append(Check("maxTurns:%s" % nd.id, three_way(e.turns, e.turns_hi, float(mt)), e.turns, e.turns_hi, float(mt),
                             [e.type] if three_way(e.turns, e.turns_hi, float(mt)) == "uncertain" else []))
        sl = info.get("soft_limit")
        if sl:
            v = three_way(e.ctx_p50, e.ctx_hi, float(sl))
            out.append(Check("soft:%s" % nd.id, v, e.ctx_p50, e.ctx_hi, float(sl), [e.type] if v == "uncertain" else []))
    tot_med = sum(e.ctx_p50 for _, e in used)
    tot_hi = sum(e.ctx_hi for _, e in used)
    contrib: Dict[str, float] = {}
    for _, e in used:
        if e.ctx_hi > e.ctx_p50:
            contrib[e.type] = contrib.get(e.type, 0.0) + e.ctx_hi - e.ctx_p50
    drivers = [t for t, _ in sorted(contrib.items(), key=lambda kv: -kv[1])]
    prompt_lim = max([SOFT_PROMPT_CTX] + [SOFT_PROMPT_CTX_BY_TYPE.get(t or "", 0)
                                          for t in [dispatcher] + [e.type for _, e in used]])
    for name, lim in (("prompt", float(prompt_lim)), ("budget", budget)):
        if lim is None:
            continue
        v = three_way(tot_med, tot_hi, float(lim))
        out.append(Check(name, v, tot_med, tot_hi, float(lim), drivers if v == "uncertain" else []))
    out.append(Check("fanout", three_way(width, width, cap), width, width, cap))
    if dispatcher == "blackcat":
        # the guard counts Agent calls per prompt (not concurrent agents) and closes the burst after the window
        k = float(len(used))
        lim = float(DEFAULT_CAPS["blackcat"])
        out.append(Check("blackcat_dispatches", three_way(k, k, lim), k, k, lim))
        last = float(max(starts)) if starts else 0.0
        out.append(Check("blackcat_window_s", three_way(last, last, BLACKCAT_WINDOW_S), last, last, BLACKCAT_WINDOW_S))
    return out


def next_ready(g: Graph, state: Dict[str, Any], sched: Schedule) -> List[str]:
    """Node ids to dispatch now: pending, every dependency done, no write conflict with a running
    node, and room under the cap. Barrier mode only releases the first wave that still has pending
    nodes and only once nothing from earlier waves is running. Order follows the schedule."""
    st = state.get("nodes", {}) if isinstance(state, dict) else {}

    def status(i: str) -> str:
        return (st.get(i) or {}).get("status", "pending")

    byid = g.by_id()
    conf_ok = _conflicts(g, {})
    idx = {nd.id: i for i, nd in enumerate(g.nodes)}
    running = [i for i in byid if status(i) == "running"]
    cap = int(sched.caps.get("fanout", effective_cap(g, None)))
    room = cap - len(running)
    out: List[str] = []
    if room <= 0:
        return out
    waves = sched.waves
    allowed: Optional[set] = None
    dead_memo: Dict[str, bool] = {}

    def dead(i: str) -> bool:
        # a pending node that can never run: a dependency failed or is blocked, or is itself dead
        if i not in dead_memo:
            dead_memo[i] = any(status(d) in ("failed", "blocked") or (status(d) == "pending" and dead(d))
                               for d in byid[i].dep)
        return dead_memo[i]

    if sched.mode == "barrier":
        for k, w in enumerate(waves):
            if any(status(i) == "running" or (status(i) == "pending" and not dead(i)) for i in w):
                if any(status(i) == "running" for ids in waves[:k] for i in ids):
                    return []
                allowed = set(w)
                break
    order = [i for w in waves for i in w]
    for i in order:
        if status(i) != "pending" or dead(i) or (allowed is not None and i not in allowed):
            continue
        if any(status(d) != "done" for d in byid[i].dep):
            continue
        if any(conf_ok[idx[i]][idx[r]] for r in running + out):
            continue
        if sched.mode == "release" and any(status(x) == "failed" for x in byid[i].dep):
            continue
        out.append(i)
        if len(out) >= room:
            break
    return out


# ---------------------------------------------------------------- replay
FMT_TS = "%Y-%m-%dT%H:%M:%S"


def _ts(s: str) -> float:
    s = s.strip().rstrip("Z")
    main, _, frac = s.partition(".")
    import calendar
    return calendar.timegm(time.strptime(main, FMT_TS)) + (float("0." + frac) if frac else 0.0)


def _read_csv(path: Any) -> List[Dict[str, str]]:
    with open(path, newline="") as fh:
        return list(csv.DictReader(fh))


_LEDGER_RE = re.compile(r'^(\s*)- (\S+?)(?: \(name [^)]*\))? · (?:"(.*)"|\(no description\)|.*?) · (\w+)'
                        r'(?: · (\d\d):(\d\d):(\d\d))?(?: · id (\w+))?\s*$')


def parse_ledger(path: Any) -> List[Dict[str, Any]]:
    """Rows of delegations.md (agent_guard.py ledger_render_text): depth, type, task, state,
    local time of day in seconds, agent id."""
    rows: List[Dict[str, Any]] = []
    if not path or not Path(path).is_file():
        return rows
    for line in Path(path).read_text().splitlines():
        mt = _LEDGER_RE.match(line)
        if not mt:
            continue
        ind, typ, task, state, hh, mm, ss, aid = mt.groups()
        sod = int(hh) * 3600 + int(mm) * 60 + int(ss) if hh else None
        rows.append({"depth": len(ind) // 2, "type": typ, "task": task or "", "state": state, "sod": sod, "id": aid})
    return rows


@dataclass
class Unit:
    key: str
    node: str
    ph: int
    agent: str
    segs: List[int]
    type: str
    start: float
    end: float
    dispatch: float
    deps: List[str]
    w: List[str]
    kind: str
    open: bool
    tokens: float
    seg_rows: List[Dict[str, Any]]
    window: int = 0


@dataclass
class Window:
    i: int
    prompt: str
    t0: float
    t_end: float
    units: List[str]
    aux: List[str]
    makespan: float
    busy: float
    dead: float
    barrier_wait: float
    waves: List[List[str]]
    open: bool
    sim_makespan: float = 0.0
    sim_err: float = 0.0
    rows: Dict[str, Dict[str, float]] = field(default_factory=dict)


@dataclass
class Report:
    session: str
    windows: List[Window]
    units: Dict[str, Unit]
    cold: List[Dict[str, Any]]
    misroutes: List[Dict[str, Any]]
    rows: Dict[str, Dict[str, float]]
    s_wall: Dict[str, float]
    s_tok: Dict[str, float]
    session_tw: float
    cold_excess_tokens: float
    cold_excess_tw: float
    verdict: str
    notes: List[str]
    phase1: Dict[str, Any]
    barrier_rewrites: Dict[str, float]
    tz_offset: float = 0.0


def _unit_tokens(m: Dict[str, Any], t: str, row: Dict[str, str]) -> float:
    kw, kr = kappas(m, t)
    return float(row["input_tokens"]) + kw * float(row["cache_creation_input_tokens"]) + \
        kr * float(row["cache_read_input_tokens"])


def simulate_waves(waves: Sequence[Sequence[Tuple[float, float]]], lat: float = 0.0) -> float:
    """Makespan under barrier semantics from recorded (startup lag, duration) pairs per unit: the first wave is
    dispatched at 0, each next wave `lat` seconds after the previous wave's last unit ends, and a wave ends at
    start + max(lag + duration). Nothing of the recorded start times enters, so comparing the result with the
    recorded makespan is a real test of the barrier model."""
    t = 0.0
    for k, w in enumerate(waves):
        st = 0.0 if k == 0 else t + lat
        t = st + max([lag + d for lag, d in w] or [0.0])
    return t


def cluster_waves(items: Sequence[Tuple[float, str]], gap: float = 120.0) -> List[List[str]]:
    """Group (dispatch time, key) pairs: a new wave starts after a gap above `gap` seconds."""
    out: List[List[str]] = []
    last = None
    for t, k in sorted(items):
        if last is None or t - last > gap:
            out.append([])
        out[-1].append(k)
        last = t
    return out


def _union_len(iv: Sequence[Tuple[float, float]]) -> float:
    tot, cur_s, cur_e = 0.0, None, None
    for s, e in sorted(iv):
        if cur_e is None or s > cur_e:
            if cur_e is not None:
                tot += cur_e - cur_s
            cur_s, cur_e = s, e
        else:
            cur_e = max(cur_e, e)
    if cur_e is not None:
        tot += cur_e - cur_s
    return tot


def replay(ledger: Any, segments: Any, prompts: Any, graph: Any, m: Dict[str, Any], session: Optional[str] = None,
           caps: Optional[Dict[str, Any]] = None) -> Report:
    """Replay a recorded session. `ledger` is a delegations.md path (or None), `segments` and
    `prompts` the agents-usage CSVs (path or list of row dicts), `graph` a graph path/dict/Graph
    whose nodes carry `ph` phases (agent id, segment numbers, dependencies as "node:phase", write
    sets) mapping the recorded segments to the plan. See render_md for the numbers."""
    g = graph if isinstance(graph, Graph) else load_graph(graph)
    seg_rows = segments if isinstance(segments, list) else _read_csv(segments)
    prm_rows = prompts if isinstance(prompts, list) else _read_csv(prompts)
    if session is None:
        session = g.meta.get("session") or (seg_rows[0]["session"] if seg_rows else "")
    seg_rows = [r for r in seg_rows if r["session"].startswith(session)]
    prm_rows = [r for r in prm_rows if r["session"].startswith(session) and r.get("kind") == "human"]
    if not seg_rows:
        raise GraphError("no segments for session %s" % session)
    notes: List[str] = []
    for r in seg_rows:
        r["_t0"], r["_t1"] = _ts(r["first_ts"]), _ts(r["last_ts"])
    by_agent: Dict[str, List[Dict[str, Any]]] = {}
    for r in sorted(seg_rows, key=lambda r: (r["id"], int(r["seg"]))):
        by_agent.setdefault(r["id"], []).append(r)
    seg_of = {(r["id"], int(r["seg"])): r for r in seg_rows}
    # ledger: spawn clock (local time of day) -> UTC offset, spawn dispatch time
    led = parse_ledger(ledger)
    diffs = []
    for row in led:
        r0 = seg_of.get((row["id"], 0)) if row["id"] else None
        if row["sod"] is not None and r0:
            diffs.append((row["sod"] - (r0["_t0"] % 86400) + 43200) % 86400 - 43200)
    tz = 0.0
    if diffs:
        diffs.sort()
        med = diffs[len(diffs) // 2]
        tz = round(med / 900.0) * 900.0
    else:
        notes.append("no ledger rows matched segments: dispatch time = first API call, UTC offset unknown")
    first_t = min(r["_t0"] for r in seg_rows)
    day0 = first_t - (first_t % 86400)
    dispatch0: Dict[str, float] = {}
    ledger_task: Dict[str, Tuple[str, str]] = {}
    for row in led:
        if row["id"] and row["sod"] is not None:
            r0 = seg_of.get((row["id"], 0))
            if r0:
                delta = ((row["sod"] - tz) - (r0["_t0"] % 86400) + 43200) % 86400 - 43200
                dispatch0[row["id"]] = r0["_t0"] + min(0.0, delta) if delta > -600 else r0["_t0"]
                ledger_task[row["id"]] = (row["type"], row["task"])
    # units
    units: Dict[str, Unit] = {}
    aux_units: Dict[str, Unit] = {}
    used = set()
    for nd in g.nodes:
        phs = nd.extra.get("ph") or []
        for k, ph in enumerate(phs):
            segs = ph["segs"] if "segs" in ph else [ph["seg"]]
            rows = [seg_of[(ph["agent"], int(s))] for s in segs if (ph["agent"], int(s)) in seg_of]
            if not rows:
                notes.append("%s phase %d: segments %s of %s not in the data" % (nd.id, k, segs, ph["agent"]))
                continue
            for s in segs:
                used.add((ph["agent"], int(s)))
            st, en = min(r["_t0"] for r in rows), max(r["_t1"] for r in rows)
            disp = dispatch0.get(ph["agent"], st) if int(segs[0]) == 0 else st
            key = "%s#%d" % (nd.id, k)
            units[key] = Unit(key=key, node=nd.id, ph=k, agent=ph["agent"], segs=[int(s) for s in segs], type=nd.a,
                              start=st, end=en, dispatch=min(disp, st), deps=list(ph.get("dep", [])),
                              w=list(ph.get("w", nd.w)), kind=ph.get("kind", ""),
                              open=any(r["open"] == "True" for r in rows),
                              tokens=sum(_unit_tokens(m, nd.a, r) for r in rows), seg_rows=rows)
            if ledger_task.get(ph["agent"]) and int(segs[0]) == 0 and ledger_task[ph["agent"]][0] != nd.a:
                notes.append("%s: ledger says type %s, graph says %s" % (nd.id, ledger_task[ph["agent"]][0], nd.a))
    for ax in g.meta.get("aux", []):
        for s in ax["segs"]:
            r = seg_of.get((ax["agent"], int(s)))
            if r:
                used.add((ax["agent"], int(s)))
                key = "%s#%d" % (ax["id"], s)
                aux_units[key] = Unit(key=key, node=ax["id"], ph=int(s), agent=ax["agent"], segs=[int(s)], type=ax["a"],
                                      start=r["_t0"], end=r["_t1"], dispatch=r["_t0"], deps=[], w=[], kind="aux",
                                      open=r["open"] == "True", tokens=_unit_tokens(m, ax["a"], r), seg_rows=[r])
    # dependency refs "node:phase" -> unit key ("node" alone = the node's last phase)
    def ref(x: str) -> Optional[str]:
        nid, _, ph = x.partition(":")
        if ph:
            return "%s#%d" % (nid, int(ph))
        cand = [u.key for u in units.values() if u.node == nid]
        return max(cand, key=lambda k: units[k].ph) if cand else None

    for u in units.values():
        resolved = [ref(x) for x in u.deps]
        bad = [x for x, r in zip(u.deps, resolved) if r is None or r not in units]
        if bad:
            notes.append("%s: dependency %s not found" % (u.key, bad))
        u.deps = [r for r in resolved if r in units]
        if u.ph > 0:
            prev = "%s#%d" % (u.node, u.ph - 1)
            if prev in units and prev not in u.deps:
                u.deps.append(prev)
    # lat: median reaction time of the orchestrator when it dispatched on a completion (latencies above
    # 60 s are barrier or human waits, not reaction time)
    lats = sorted(u.dispatch - max(units[d].end for d in u.deps) for u in units.values()
                  if u.deps and all(units[d].end <= u.dispatch + 1 for d in u.deps))
    lats = [x for x in lats if 0 <= x <= 60]
    lat = lats[len(lats) // 2] if lats else 0.0
    # windows (human prompts, HH:MM UTC)
    starts_w: List[float] = []
    labels: List[str] = []
    for r in sorted(prm_rows, key=lambda r: int(r.get("i") or 0)):
        hh, mm = r["start"].split(":")
        tw0 = day0 + int(hh) * 3600 + int(mm) * 60
        while starts_w and tw0 < starts_w[-1]:
            tw0 += 86400                      # the session ran past UTC midnight
        starts_w.append(tw0)
        labels.append(r["prompt"][:50])
    allu = list(units.values()) + list(aux_units.values())
    for u in allu:
        u.window = max(0, bisect.bisect_right(starts_w, u.start) - 1) if starts_w else 0
    # actual per-window
    windows: List[Window] = []
    for wi in sorted({u.window for u in allu}):
        wu = [u for u in allu if u.window == wi]
        t0 = min(u.start for u in wu)
        t1 = max(u.end for u in wu)
        busy = _union_len([(u.start, u.end) for u in wu])
        bw = 0.0
        for u in wu:
            if u.kind == "aux":
                continue
            ready = max([units[d].end for d in u.deps] + [t0])
            bw += max(0.0, u.dispatch - ready)
        waves = cluster_waves([(u.dispatch, u.key) for u in wu])
        sim = simulate_waves([[(units_or_aux(units, aux_units, k).start - units_or_aux(units, aux_units, k).dispatch,
                                units_or_aux(units, aux_units, k).end - units_or_aux(units, aux_units, k).start)
                               for k in w] for w in waves], lat)
        mk = t1 - t0
        windows.append(Window(i=wi, prompt=labels[wi] if wi < len(labels) else "", t0=t0, t_end=t1,
                              units=[u.key for u in wu if u.kind != "aux"], aux=[u.key for u in wu if u.kind == "aux"],
                              makespan=mk, busy=busy, dead=mk - busy, barrier_wait=bw, waves=waves,
                              open=any(u.open for u in wu), sim_makespan=sim,
                              sim_err=(sim - mk) / mk if mk else 0.0))
    # cold resumes over every segment of the session
    cold: List[Dict[str, Any]] = []
    unit_of_seg: Dict[Tuple[str, int], Unit] = {}
    for u in allu:
        for s in u.segs:
            unit_of_seg[(u.agent, s)] = u
    for aid, rows in by_agent.items():
        for prev, cur in zip(rows, rows[1:]):
            typ = cur["type"]
            ttl = 3600.0 if tinfo(m, typ)["ttl"] == "1h" else 300.0
            gap = cur["_t0"] - prev["_t1"]
            if gap > ttl:
                exc = min(float(cur["cache_creation_input_tokens"]), float(prev["peak"]))
                kw, _ = kappas(m, typ)
                cold.append({"agent": aid, "type": typ, "desc": cur["desc"], "seg": int(cur["seg"]), "gap": gap, "ttl": ttl,
                             "cc": float(cur["cache_creation_input_tokens"]), "prior_peak": float(prev["peak"]),
                             "excess": exc, "excess_tw": exc * kw,
                             "unit": unit_of_seg.get((aid, int(cur["seg"])))})
    # misroutes: api_calls above 1.5 x the type's p90 turns (a read-only type that wrote files
    # cannot be told from segments.csv: no tool names)
    misroutes: List[Dict[str, Any]] = []
    for r in seg_rows:
        if r["type"] == "orchestrator":
            continue
        p90 = tinfo(m, r["type"])["turns"]["L"]
        if float(r["api_calls"]) > 1.5 * p90:
            misroutes.append({"agent": r["id"], "seg": int(r["seg"]), "type": r["type"], "desc": r["desc"],
                              "calls": int(r["api_calls"]), "limit": 1.5 * p90})
    session_tw = sum(_unit_tokens(m, r["type"], r) for r in seg_rows)
    # advised rows
    for w in windows:
        w.rows["actual/model"] = {"makespan": _actual_model(g, m, w, units, aux_units)}
    rows_out: Dict[str, Dict[str, float]] = {}
    adv_times: Dict[str, Dict[str, Tuple[float, float]]] = {}
    for basis in ("oracle", "model"):
        for mode in ("barrier", "release"):
            for variant_name, rules in (("", {}), ("+caps-only", {"fragments": True, "no_conflicts": True})):
                if variant_name and not (basis == "oracle" and mode == "release"):
                    continue
                name = "%s/%s%s" % (mode, basis, variant_name)
                times_all: Dict[str, Tuple[float, float]] = {}
                for w in windows:
                    mk, times = _advise_window(g, m, w, units, aux_units, mode, basis, lat, caps, rules)
                    w.rows[name] = {"makespan": mk}
                    times_all.update(times)
                adv_times[name] = times_all
                act = (lambda w: w.makespan) if basis == "oracle" else (lambda w: w.rows["actual/model"]["makespan"])
                tot_adv = sum(w.rows[name]["makespan"] for w in windows)
                tot_act = sum(act(w) for w in windows)
                rows_out[name] = {"advised": tot_adv, "actual": tot_act,
                                  "advised_closed": sum(w.rows[name]["makespan"] for w in windows if not w.open),
                                  "actual_closed": sum(act(w) for w in windows if not w.open),
                                  "S_wall": 1 - tot_adv / tot_act if tot_act else 0.0}
    # token rule: a cold resume whose advised gap is under 270 s is warm (its excess is avoided); otherwise a fresh
    # fixer replaces it, costed kappa_w x static_cc plus the fraction f of the prior context it must re-read (f is
    # not measurable from segments.csv: reported at 0, 0.5 and the f where S_tok falls under 3%)
    for name, times in adv_times.items():
        warm = 0.0
        warm_prov = 0.0
        warm_n = 0
        cands: List[Tuple[float, float]] = []
        cand_kw: List[float] = []
        cand_prov: List[bool] = []
        for c in cold:
            u = c["unit"]
            if u is None or u.kind == "aux" or u.key not in times:
                continue
            pu = unit_of_seg.get((c["agent"], c["seg"] - 1))
            if pu is None or pu.key == u.key:
                continue                      # no previous unit, or both segments sit in one multi-segment phase
            prev_end = times[pu.key][1] if pu.key in times else pu.end
            kw, _ = kappas(m, c["type"])
            if times[u.key][0] - prev_end < RESUME_WARM_S:
                warm += c["excess_tw"]
                warm_n += 1
                warm_prov += c["excess_tw"] if band_of(m, c["type"])["status"] == "provisional" else 0.0
            else:
                cands.append((c["excess_tw"], kw * float(tinfo(m, c["type"])["static_cc"])))
                cand_kw.append(kw)
                cand_prov.append(band_of(m, c["type"])["status"] == "provisional")

        def avoid(f: float) -> float:
            return warm + sum(max(0.0, e * (1.0 - f) - st) for e, st in cands)

        den = session_tw or 1.0
        av0 = avoid(0.0)
        prov_av = warm_prov + sum(max(0.0, e - st) for (e, st), pv in zip(cands, cand_prov) if pv)
        wts = [(max(0.0, u.end - times[u.key][1]), band_of(m, u.type)["status"] == "provisional")
               for u in units.values() if u.key in times]
        wtot = sum(x for x, _ in wts)
        rows_out[name]["prov_share_tok"] = prov_av / av0 if av0 > 0 else 0.0
        rows_out[name]["prov_share_wall"] = sum(x for x, pv in wts if pv) / wtot if wtot > 0 else 0.0
        f_star = next((i / 100.0 for i in range(0, 101) if avoid(i / 100.0) / den < 0.03), None)
        # measured fresh-fixer cost (sched_model.json fixer, S1e step 1): kappa_w x (static_cc + reread), reread = the
        # context a fresh builder reads before its first repo write; lo/hi from the interval of its median
        fx = m.get("fixer") if isinstance(m.get("fixer"), dict) else None

        def avoid_r(rr: float) -> float:
            return warm + sum(max(0.0, e - st - kw_c * rr) for (e, st), kw_c in zip(cands, cand_kw))
        if fx and fx.get("reread") is not None:
            rr = float(fx["reread"])
            rows_out[name].update({"S_tok_measured": avoid_r(rr) / den, "fixer_reread": rr,
                                   "S_tok_measured_lo": avoid_r(float(fx.get("hi") or rr)) / den,
                                   "S_tok_measured_hi": avoid_r(float(fx.get("lo") or rr)) / den})
        rows_out[name].update({"warm_tw": warm, "warm": warm_n, "fresh": sum(1 for e, st in cands if e > st),
                               "S_tok_warm": warm / den, "S_tok_upper": avoid(0.0) / den, "S_tok_f50": avoid(0.5) / den,
                               "f_star": f_star if f_star is not None else 1.01, "avoidable_tw": avoid(0.0)})
    s_wall = {k: v["S_wall"] for k, v in rows_out.items()}
    s_tok = {k: v["S_tok_upper"] for k, v in rows_out.items()}
    oracle = [k for k in rows_out if "/oracle" in k and "caps-only" not in k]
    wall_ok = all(s_wall[k] < 0.05 for k in oracle)
    tok_hi = all(rows_out[k]["S_tok_upper"] < 0.03 for k in oracle)
    tok_lo = any(rows_out[k]["S_tok_warm"] >= 0.03 for k in oracle)
    measured = all("S_tok_measured" in rows_out[k] for k in oracle) and bool(oracle)
    if measured:
        m_lo = min(rows_out[k]["S_tok_measured_lo"] for k in oracle)
        m_hi = max(rows_out[k]["S_tok_measured_hi"] for k in oracle)
        m_txt = ", ".join("%s %.2f%% [%.2f-%.2f%%]" % (k, 100 * rows_out[k]["S_tok_measured"], 100 * rows_out[k]["S_tok_measured_lo"],
                                                         100 * rows_out[k]["S_tok_measured_hi"]) for k in oracle)
    if measured and wall_ok and m_hi < 0.03:
        verdict = ("STOP: S_wall < 5%% and the measured S_tok < 3%% on the oracle rows (%s); the scheduler stays a report tool"
                   % m_txt)
    elif measured and wall_ok and all(rows_out[k]["S_tok_measured_lo"] >= 0.03 for k in oracle):
        verdict = ("STOP on wall time (S_wall < 5%% on both oracle rows); token side: the measured S_tok is at or above 3%% (%s, "
                   "fresh fixer re-reading the measured %.0f tokens instead of a cold resume). ASK USER before any behaviour change"
                   % (m_txt, rows_out[oracle[0]]["fixer_reread"]))
    elif measured and wall_ok:
        verdict = ("STOP on wall time (S_wall < 5%% on both oracle rows); token side undecided: the measured S_tok interval straddles "
                   "3%% (%s). ASK USER before any behaviour change" % m_txt)
    elif wall_ok and tok_hi:
        verdict = "STOP: S_wall < 5% and S_tok < 3% on the oracle rows; the scheduler stays a report tool"
    elif wall_ok and not tok_lo:
        verdict = ("STOP on wall time (S_wall < 5%% on both oracle rows); token side undecided by the data: S_tok is %.2f%%-%.2f%% "
                   "(warm resumes only .. fresh fixers with zero re-reads), above 3%% only if a fresh fixer re-reads under %.0f%% "
                   "of the prior context. ASK USER before any behaviour change" % (
                       100 * min(rows_out[k]["S_tok_warm"] for k in oracle), 100 * max(rows_out[k]["S_tok_upper"] for k in oracle),
                       100 * max(rows_out[k]["f_star"] for k in oracle)))
    else:
        verdict = "ASK USER before any behaviour change: an oracle row reaches S_wall >= 5% or the measured S_tok >= 3%"
    # hand estimates
    cold_total = sum(c["excess"] for c in cold)
    cold_tw = sum(c["excess_tw"] for c in cold)
    barrier_rw = {}
    for nid in ("P5", "P7"):
        u = units.get("%s#1" % nid)
        if u:
            barrier_rw[nid] = sum(float(r["cache_creation_input_tokens"]) for r in u.seg_rows)
    phase1 = _phase1(g, units, aux_units, by_agent, seg_rows)
    if any(w.open for w in windows):
        notes.append("window(s) %s contain a segment still open when segments.csv was cut: their makespan is a lower bound"
                     % ", ".join(str(w.i) for w in windows if w.open))
    notes.append("model: %s; model types keyed by today's agent frontmatter (opus/sonnet, TTL), not by the model each agent "
                 "actually ran on during the session" % (m.get("file") or "built-in defaults"))
    notes.append("T_w counts subagent segments only: the main thread's cache mix is not in segments.csv, so S_tok's "
                 "denominator excludes it")
    if isinstance(m.get("fixer"), dict) and m["fixer"].get("reread") is not None:
        notes.append("fresh-fixer cost = kappa_w x (static_cc + fixer.reread): the re-read is measured from the transcripts (the "
                     "context a fresh builder reads before its first repo write, n = %s); the 0%%/50%% columns are kept as the "
                     "bracket it replaces" % m["fixer"].get("n"))
    else:
        notes.append("fresh-fixer cost = kappa_w x static_cc (the model file's p10 first-call cache write) plus the re-read fraction f of "
                     "the prior context; the model has no measured fixer re-read, so S_tok is reported as a bracket")
    notes.append("read-only types that wrote files cannot be detected from segments.csv (no tool names): misroutes use the "
                 "1.5 x p90 turns test only")
    return Report(session=session, windows=windows, units=units, cold=cold, misroutes=misroutes, rows=rows_out,
                  s_wall=s_wall, s_tok=s_tok, session_tw=session_tw, cold_excess_tokens=cold_total,
                  cold_excess_tw=cold_tw, verdict=verdict, notes=notes, phase1=phase1, barrier_rewrites=barrier_rw,
                  tz_offset=tz)


def _actual_model(g: Graph, m: Dict[str, Any], w: Window, units: Dict[str, Unit], aux: Dict[str, Unit]) -> float:
    """Makespan of the window as it was run (dispatch offsets, dependencies) but with the model's durations:
    the baseline of the model rows."""
    end: Dict[str, float] = {}
    for u in sorted((units[k] for k in w.units), key=lambda u: u.start):
        nd = g.by_id()[u.node]
        d = _est_for(m, nd.a, nd.s, nd.n).wall_plan / max(1, len(nd.extra.get("ph") or [1]))
        st = max([u.dispatch - w.t0] + [end[x] for x in u.deps if x in end])
        end[u.key] = st + d
    return max(list(end.values()) + [aux[k].end - w.t0 for k in w.aux] + [0.0])


def units_or_aux(units: Dict[str, Unit], aux: Dict[str, Unit], k: str) -> Unit:
    return units[k] if k in units else aux[k]


def _advise_window(g: Graph, m: Dict[str, Any], w: Window, units: Dict[str, Unit], aux: Dict[str, Unit], mode: str,
                   basis: str, lat: float, caps: Optional[Dict[str, Any]], rules: Dict[str, Any]
                   ) -> Tuple[float, Dict[str, Tuple[float, float]]]:
    """Makespan (seconds from the window's first start) and absolute (start, end) per unit key of
    the window's units rescheduled in `mode`, with actual durations (oracle) or the model's."""
    wu = [units[k] for k in w.units]
    fixed_end = max([aux[k].end for k in w.aux] + [0.0]) - w.t0 if w.aux else 0.0
    if not wu:
        return max(w.makespan if not w.aux else fixed_end, 0.0), {}
    inwin = {u.key for u in wu}
    nodes: List[Node] = []
    dur: Dict[str, float] = {}
    rel: Dict[str, float] = {}
    for u in wu:
        deps = []
        ext = w.t0
        for d in u.deps:
            du = units[d]
            if d in inwin:
                # read-only checks never block builders: drop the edge unless this unit fixes what it reviewed
                if du.type in READONLY_TYPES and u.type not in READONLY_TYPES and u.kind != "fix":
                    continue
                deps.append(d)
            else:
                if du.type in READONLY_TYPES and u.type not in READONLY_TYPES and u.kind != "fix":
                    continue
                ext = max(ext, du.end)
        nd = g.by_id()[u.node]
        nodes.append(Node(id=u.key, a=u.type, s=nd.s, n=nd.n, dep=deps, w=([] if rules.get("no_conflicts") else u.w),
                          rd=[], r=nd.r, extra={}))
        rel[u.key] = max(0.0, ext - w.t0)
        if basis == "oracle":
            dur[u.key] = u.end - u.start
        else:
            nd_est = _est_for(m, nd.a, nd.s, nd.n).wall_plan
            nph = max(1, len(nd.extra.get("ph") or [1]))
            dur[u.key] = nd_est / nph
    sg = Graph(job="window", speed="balanced", nodes=nodes, meta={"dispatcher": "orchestrator"})
    sch = schedule(sg, m, mode=mode, caps=caps or {"fanout": 10}, durations=dur, release=rel, lat=lat, rules=rules)
    mk = max(sch.wall, fixed_end)
    times = {k: (w.t0 + s, w.t0 + e) for k, (s, e) in sch.times.items()}
    return mk, times


def _phase1(g: Graph, units: Dict[str, Unit], aux: Dict[str, Unit], by_agent: Dict[str, List[Dict[str, Any]]],
            seg_rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Critical path of the T-series (actual durations, and with the observed dispatch latencies)
    against the elapsed time from the first orchestrator call to the last T unit."""
    tun = {k: u for k, u in units.items() if u.node.startswith("T")}
    if not tun:
        return {}
    best: Dict[str, Tuple[float, float, List[str]]] = {}

    def cp(k: str) -> Tuple[float, float, List[str]]:
        if k in best:
            return best[k]
        u = tun[k]
        d = u.end - u.start
        pre = [(cp(x), x) for x in u.deps if x in tun]
        if not pre:
            best[k] = (d, d, [k])
            return best[k]
        (pd, pe, pp), px = max(pre, key=lambda t: t[0][0])
        lat = max(0.0, u.start - tun[px].end)
        best[k] = (pd + d, pe + lat + d, pp + [k])
        return best[k]

    ends = {k: cp(k) for k in tun}
    kmax = max(ends, key=lambda k: ends[k][0])
    first = min([u.start for u in tun.values()] + [r["_t0"] for r in seg_rows if r["type"] == "orchestrator" and int(r["seg"]) == 0])
    last = max(u.end for u in tun.values())
    orch_end = max([r["_t1"] for r in seg_rows if r["type"] == "orchestrator" and r["_t1"] <= last + 60 and r["_t0"] >= first - 1] + [last])
    return {"elapsed_min": (orch_end - first) / 60.0, "elapsed_units_min": (last - min(u.start for u in tun.values())) / 60.0,
            "cp_dur_min": ends[kmax][0] / 60.0, "cp_with_latency_min": ends[kmax][1] / 60.0, "path": ends[kmax][2]}


# ---------------------------------------------------------------- rendering
def _fmt_min(s: float) -> str:
    return "%.1f" % (s / 60.0)


def render_md(x: Any, max_chars: Optional[int] = 1500) -> str:
    """Markdown for a Schedule, a Report, an estimate dict or an Issue list; cut at `max_chars`
    (None: no limit)."""
    if isinstance(x, Schedule):
        lines = ["**%s schedule** wall %.0f s, T_w %.0f, J %.0f (baseline %.0f), lambda %.3g, caps fanout %s%s"
                 % (x.mode, x.wall, x.tokens, x.J, x.J_baseline, x.lam, x.caps.get("fanout"),
                    "" if x.exact else ", list schedule")]
        for i, w in enumerate(x.waves, 1):
            lines.append("- %d: %s" % (i, ", ".join("%s@%.0fs" % (n, x.times[n][0]) if x.mode == "release" else n for n in w)))
        lines.append("critical path: " + " > ".join(x.critical_path))
        if x.provisional:
            lines.append("planned at hi (med x (1 + w)) for provisional types: " + ", ".join(
                "%s%s w=%.2f" % (t, " (unverified)" if v["unverified"] else "", max(v["w"].values())) for t, v in sorted(x.provisional.items())))
        lines.append("verdict: **%s**" % x.verdict)
        for c in x.checks:
            if c.verdict != "fits":
                lines.append("- %s %s: med %.0f, hi %.0f, limit %.0f%s" % (c.name, c.verdict, c.med, c.hi, c.limit,
                             " (driven by %s)" % ", ".join(c.drivers) if c.drivers else ""))
        lines += ["warning: " + w for w in x.warnings]
        text = "\n".join(lines)
    elif isinstance(x, Report):
        text = _render_report(x)
    elif isinstance(x, dict):
        text = "\n".join("- %s: %d turns, ctx %.0f (hi %.0f), T_w %.0f (hi %.0f), wall %.0f-%.0f s, %s%s%s" % (
            k, e.turns, e.ctx_p50, e.ctx_hi, e.t_w, e.t_w_hi, e.wall_p50, e.wall_hi, e.status,
            "; one run, 90%% hi: %.0f turns, ctx %.0f, wall %.0f s" % (e.turns_run_hi, e.ctx_run_hi, e.wall_run_hi)
            if e.turns_run_hi else "", "; resume from peak" if e.resume else "")
                         for k, e in x.items())
    elif isinstance(x, list):
        text = "\n".join("- %s %s: %s" % (i.level, i.node or "graph", i.msg) for i in x) or "no issues"
    else:
        text = str(x)
    if max_chars is not None and len(text) > max_chars:
        text = text[:max(0, max_chars - 4)].rstrip() + " ..."
    return text


def _render_report(r: Report) -> str:
    o = []
    o.append("# Scheduler replay, session %s" % r.session)
    o.append("")
    o.append("Generated by stack_sched.py replay. Units are segments of the recorded agents mapped to the graph fixture; windows "
             "are cut at each human prompt (think time excluded: a window runs from its first unit start to its last unit end). "
             "T_w = input + kappa_w x cache writes + kappa_r x cache reads (output excluded, price ratio not read). Local ledger "
             "clock = UTC %+.1f h.\n" % (r.tz_offset / 3600.0))
    o.append("## Verdict\n")
    o.append("**%s**\n" % r.verdict)
    o.append("| row | advised makespan (min) | baseline (min) | S_wall | warm resumes | fresh fixers | S_tok warm only | S_tok fresh, 0% re-read | S_tok fresh, 50% re-read | f where S_tok < 3% |")
    o.append("|---|---|---|---|---|---|---|---|---|---|")
    for k, v in r.rows.items():
        o.append("| %s | %s | %s | %.1f%% | %d | %d | %.2f%% | %.2f%% | %.2f%% | %s |" % (
            k, _fmt_min(v["advised"]), _fmt_min(v["actual"]), 100 * v["S_wall"], v["warm"], v["fresh"], 100 * v["S_tok_warm"],
            100 * v["S_tok_upper"], 100 * v["S_tok_f50"], "n/a" if v["f_star"] > 1 else "%.0f%%" % (100 * v["f_star"])))
    o.append("")
    if any("S_tok_measured" in v for v in r.rows.values()):
        o.append("Measured fresh-fixer cost (model `fixer`): kappa_w x (static_cc + %.0f tokens), the median context a fresh builder "
                 "reads before its first repo write; the interval comes from the 95%% interval of that median.\n"
                 % next(v["fixer_reread"] for v in r.rows.values() if "fixer_reread" in v))
        o.append("| row | S_tok measured | 95% interval |")
        o.append("|---|---|---|")
        for k, v in r.rows.items():
            if "S_tok_measured" in v:
                o.append("| %s | %.2f%% | %.2f%%-%.2f%% |" % (k, 100 * v["S_tok_measured"], 100 * v["S_tok_measured_lo"],
                                                             100 * v["S_tok_measured_hi"]))
        o.append("")
    o.append("Share of the predicted saving that rests on provisional types (small-n bands): wall = share of the per-unit end-time "
             "gains (recorded end - advised end, gains only) of units of provisional type; tokens = share of the avoidable T_w (0% "
             "re-read) from cold resumes of provisional type.\n")
    o.append("| row | wall saving on provisional types | token saving on provisional types |")
    o.append("|---|---|---|")
    for k, v in r.rows.items():
        o.append("| %s | %.0f%% | %.0f%% |" % (k, 100 * v["prov_share_wall"], 100 * v["prov_share_tok"]))
    o.append("")
    o.append("S_wall = 1 - sum(advised makespan) / sum(baseline makespan) over all windows; the baseline of the oracle rows is the recorded "
             "makespan, of the model rows the recorded dispatch pattern run with the model's durations. S_tok = avoidable T_w / session "
             "T_w (%.0f, subagent segments only). A warm resume is one whose advised gap is under 270 s; a cold one that cannot be "
             "made warm is replaced by a fresh fixer costed kappa_w x static_cc plus the re-read fraction of the prior context (not "
             "measured from segments.csv: the bracket columns; the measured row above uses the model's `fixer`). `release/oracle+caps-only` drops the write-set conflict constraints. Only the "
             "oracle rows enter the verdict. Rows excluding windows still open at the data cut (closed windows only):\n" % r.session_tw)
    o.append("| row | S_wall closed windows only |")
    o.append("|---|---|")
    for k, v in r.rows.items():
        o.append("| %s | %.1f%% |" % (k, 100 * (1 - v["advised_closed"] / v["actual_closed"]) if v["actual_closed"] else 0))
    o.append("")
    o.append("## Windows (actual)\n")
    o.append("| # | prompt | units | makespan min | dead min | barrier wait min | waves | sim error | open | %s |" % " | ".join(
        "%s min" % k for k in r.rows))
    o.append("|---|---|---|---|---|---|---|---|---|%s|" % "|".join("---" for _ in r.rows))
    for w in r.windows:
        o.append("| %d | %s | %d+%d | %s | %s | %s | %d | %+.2f%% | %s | %s |" % (
            w.i, w.prompt.replace("|", "/")[:40], len(w.units), len(w.aux), _fmt_min(w.makespan), _fmt_min(w.dead),
            _fmt_min(w.barrier_wait), len(w.waves), 100 * w.sim_err, "yes" if w.open else "",
            " | ".join(_fmt_min(w.rows[k]["makespan"]) for k in r.rows)))
    worst = max((abs(w.sim_err) for w in r.windows), default=0.0)
    o.append("")
    o.append("Barrier simulation from the recorded startup lags and durations (first wave at 0, each next wave one median "
             "dispatch latency after the previous wave's last end; recorded start times are not inputs) differs from the recorded "
             "makespan by at most %.2f%% per window (the done-when asked for 2%%: %s)." % (
                 100 * worst, "met" if worst <= 0.02 else "NOT met, reported as measured"))
    o.append("")
    o.append("## Hand estimates\n")
    cold_noorch = sum(c["excess"] for c in r.cold if c["type"] != "orchestrator")
    o.append("- Cold excess (resume gap above the TTL, min(cache writes, prior peak)): %.0f cache-write tokens over %d resumes, "
             "%.0f without the orchestrator's one (hand estimate 3.02M)." % (r.cold_excess_tokens, len(r.cold), cold_noorch))
    if r.barrier_rewrites:
        o.append("- P5/P7 wave-B resumes (hand estimate 478k + 432k): cache writes of those segments %s; by the min(cache writes, prior "
                 "peak) rule the re-written part is %s." % (
                     " + ".join("%s %.0f" % (k, v) for k, v in sorted(r.barrier_rewrites.items())),
                     " + ".join("%s %.0f" % (c["desc"].split()[0], c["excess"]) for c in r.cold
                                if c["desc"].split()[0] in ("P5", "P7") and c["seg"] == 1)))
    if r.phase1:
        p1 = r.phase1
        o.append("- Phase 1 (T1-T8): elapsed %.1f min from the first orchestrator call to the last T unit (%.1f min from the first T unit); "
                 "longest dependency chain %s = %.1f min of agent time, %.1f min with the dispatch latencies on that chain "
                 "(hand estimate 68 of 73.6 min)." % (p1["elapsed_min"], p1["elapsed_units_min"], " > ".join(p1["path"]),
                                                    p1["cp_dur_min"], p1["cp_with_latency_min"]))
    o.append("")
    o.append("## Cold resumes (gap above the type's cache TTL)\n")
    o.append("excess = min(cache writes of the resumed segment, prior segment peak). Total %.0f cache-write tokens over %d resumes "
             "(%.0f in T_w units, kappa_w weighted).\n" % (r.cold_excess_tokens, len(r.cold), r.cold_excess_tw))
    o.append("| agent | type | task | seg | gap min | TTL min | cache writes | prior peak | excess |")
    o.append("|---|---|---|---|---|---|---|---|---|")
    for c in sorted(r.cold, key=lambda c: -c["excess"]):
        o.append("| %s | %s | %s | %d | %.1f | %.0f | %.0f | %.0f | %.0f |" % (c["agent"][:8], c["type"], c["desc"][:34], c["seg"],
                 c["gap"] / 60, c["ttl"] / 60, c["cc"], c["prior_peak"], c["excess"]))
    o.append("")
    o.append("## Misroutes (api calls above 1.5 x the type's p90 turns)\n")
    for mr in r.misroutes:
        o.append("- %s seg %d %s: %d calls (limit %.0f)" % (mr["type"], mr["seg"], mr["desc"][:40], mr["calls"], mr["limit"]))
    if not r.misroutes:
        o.append("none")
    o.append("")
    o.append("## Notes\n")
    for n in r.notes:
        o.append("- " + n)
    return "\n".join(o) + "\n"


# ---------------------------------------------------------------- CLI
def _plan_cmd(a: argparse.Namespace) -> int:
    try:
        g = load_graph(a.graph)
        if a.speed:
            g.speed = a.speed
        m = load_model(a.model)
        issues = validate(g, m)
        errs = [i for i in issues if i.level == "error"]
        if errs:
            for i in errs:
                print("error: %s: %s" % (i.node or "graph", i.msg), file=sys.stderr)
            return 1
        s = schedule(g, m, mode=a.mode, budget=a.budget)
    except GraphError as exc:
        print("invalid graph: %s" % exc, file=sys.stderr)
        return 1
    except ModelError as exc:
        print("model: %s" % exc, file=sys.stderr)
        return 2
    if a.json:
        print(json.dumps({"mode": s.mode, "waves": s.waves, "critical_path": s.critical_path, "tokens": s.tokens,
                          "wall": s.wall, "J": s.J, "J_baseline": s.J_baseline, "lambda": s.lam, "exact": s.exact,
                          "times": s.times, "variants": s.variants, "verdict": s.verdict, "provisional": s.provisional,
                          "checks": [dataclasses.asdict(c) for c in s.checks], "warnings": s.warnings + [
                              "%s %s: %s" % (i.level, i.node or "graph", i.msg) for i in issues if i.level == "warn"]},
                         indent=2))
    else:
        print(render_md(s, max_chars=None))
        for i in issues:
            if i.level == "warn":
                print("warning: %s: %s" % (i.node or "graph", i.msg))
    return 0


def _next_cmd(a: argparse.Namespace) -> int:
    try:
        g = load_graph(a.graph)
        state = json.loads(Path(a.state).read_text())
        m = load_model(a.model)
    except GraphError as exc:
        print("invalid graph: %s" % exc, file=sys.stderr)
        return 1
    except ModelError as exc:
        print("model: %s" % exc, file=sys.stderr)
        return 2
    except (OSError, ValueError) as exc:
        print("state: %s" % exc, file=sys.stderr)
        return 2
    errs = [i for i in validate(g, m) if i.level == "error"]
    if errs:
        for i in errs:
            print("error: %s: %s" % (i.node or "graph", i.msg), file=sys.stderr)
        return 1
    s = schedule(g, m, mode=a.mode)
    print(json.dumps(next_ready(g, state, s)))
    return 0


def _replay_cmd(a: argparse.Namespace) -> int:
    root = Path.cwd()
    seg = a.segments or str(root / ".claude-work/agents-usage/segments.csv")
    prm = a.prompts or str(root / ".claude-work/agents-usage/prompts.csv")
    xdg = os.environ.get("XDG_STATE_HOME") or str(Path.home() / ".local/state")
    led = a.ledger or str(Path(xdg) / "claude-agent-stack" / a.session / "delegations.md")
    out = a.out or str(root / (".claude-work/agents-sched/replay-%s.md" % a.session[:8]))
    try:
        m = load_model(a.model)
        rep = replay(led, seg, prm, a.graph, m, session=a.session)
    except GraphError as exc:
        print("invalid graph or data: %s" % exc, file=sys.stderr)
        return 1
    except ModelError as exc:
        print("model: %s" % exc, file=sys.stderr)
        return 2
    except (OSError, KeyError, ValueError) as exc:
        print("replay: %s: %s" % (type(exc).__name__, exc), file=sys.stderr)
        return 2
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    Path(out).write_text(render_md(rep, max_chars=None))
    print("wrote %s" % out)
    print("S_wall %s" % ", ".join("%s %.1f%%" % (k, 100 * v) for k, v in rep.s_wall.items()))
    print("S_tok %s" % ", ".join("%s %.2f%%" % (k, 100 * v) for k, v in rep.s_tok.items()))
    print(rep.verdict)
    return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(prog="stack_sched.py", description="Scheduler advisor (report tool).")
    ap.add_argument("--model", default=None, help="sched_model.json (default: STACK_SCHED_MODEL, the active model, the one beside this script)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("plan", help="schedule a graph")
    p.add_argument("graph")
    p.add_argument("--mode", choices=["barrier", "release"], default="barrier")
    p.add_argument("--speed", choices=list(SPEEDS))
    p.add_argument("--budget", type=float, help="user budget in ctx tokens (the hook's unit), checked at hi")
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=_plan_cmd)
    p = sub.add_parser("next", help="node ids to dispatch now")
    p.add_argument("graph")
    p.add_argument("state")
    p.add_argument("--mode", choices=["barrier", "release"], default="barrier")
    p.set_defaults(fn=_next_cmd)
    p = sub.add_parser("replay", help="replay a recorded session")
    p.add_argument("--session", required=True)
    p.add_argument("--graph", required=True)
    p.add_argument("--segments")
    p.add_argument("--ledger")
    p.add_argument("--prompts")
    p.add_argument("--out")
    p.set_defaults(fn=_replay_cmd)
    p = sub.add_parser("emit-workflow", help="disabled until the probe")
    p.set_defaults(fn=lambda a: (print("emit-workflow: disabled until probe", file=sys.stderr), 2)[1])
    a = ap.parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
