#!/usr/bin/env python3
"""stack_fanout.py - the dynamic fan-out cap's decision core (stdlib only, Python 3.8+, no side effects).

Pure functions the guard (agent_guard.py) calls to size an orchestrator's limit on running children
per job (dynamic fan-out plan, D1-D3). Nothing here reads the environment or a file on its own: the
caller passes the knobs (parse_knobs(os.environ)), the time, the live lease ids, the live child ids,
the budget numbers and the parsed sched model. The one clock read is the glob-overlap deadline (an
injectable `clock`, time.monotonic by default). The only I/O helpers are load_model (a read-only
cached reader of a sched model file) and the CLI.

Rules this module holds to:
  R1  the dynamic cap never exceeds the static cap (C_ceil = fanout_limit), and in `off` or `shadow`
      mode every decision allows (the guard's static decision stands unchanged);
  R2  the plan, budget and AIMD terms apply only to spawning types in STACK_FANOUT_DYN_TYPES
      (default orchestrator), never to the main thread or BlackCat;
  R3  any failure (a bad plan, bad input, an exception) is the static decision, never a refusal;
  R4  with 0 running children the AIMD window is ignored: a ready planned node always gets one spawn
      while K_B >= 1;
  R5  at most one live run per plan node, at most NODE_RUNS runs per node (aborted runs excluded),
      no node before its dependencies have ended;
  R9  every knob is an env-only fixed guard, never learned (KNOBS lists them for FIXED_LIMIT_KNOBS).
K_sess (the session slot guard) lives in agent_guard.py under its own switch; here it is only one
more term of the reported cap.

Node runs (D1). A run is {tid, child_id, type, t_spawn, t_end, outcome, iso}: tid is the spawn
lease's tool_use_id. A run is live while its lease exists (tid in the live lease ids) or its child is
registered and not stopped (child_id in the live child ids). A run whose lease is gone and whose
child_id is still null never started (a later gate denied it, or the Agent call failed): it is
aborted, neither live nor counted toward NODE_RUNS. Any other run has ended.

Formula (D2), o = the spawning agent, s = the requested spawn:
  B_rem  = min(hard.prompt - used_p, hard.session - total)            (caps <= 0 are off)
  Commit = sum over live children j of o: max(0, c_med(t_j) - seg_j)
  K_B    = max k: sum_{i<=k} c_med(t_i) <= B_rem - Commit - RESERVE_TOK  (i = s, then R_elig in plan
           order, then further spawns like s); unknown budget or model: K_B = infinity (None)
  C_dyn  = min(C_ceil, n + |R_elig| + max(0, slack - U), W, n + K_B, n + K_sess)

CLI:
  python3 stack_fanout.py check PLAN.json [--types a,b,...] [--cap N]
  python3 stack_fanout.py report --session SID [--json]
Exit codes: 0 ok (plan accepted), 1 plan rejected or nothing to report, 2 usage error.
"""
import copy
import fnmatch
import json
import math
import os
import re
import sys
import time

# ---------------------------------------------------------------- constants
MODES = ("off", "shadow", "enforce")
ENFORCE_TERMS = ("node", "deps", "conflict", "budget", "aimd")
# deny code -> the enforce term that owns it ("ceil" is the static cap and always applies)
CODE_TERM = {"running": "node", "runs_used": "node", "deps": "deps", "exclusive": "conflict",
             "conflict": "conflict", "window": "aimd", "budget": "budget", "ceil": "static"}
CHAIN = ("coder", "main-coder", "ninja-coder", "supreme-coder")
# first run + 1 retry (orchestrator.md:39), 2x main-coder and 2x ninja-coder (each "failed twice"
# before escalating, :33), 1x supreme-coder (once per session, :34)
_NODE_RUNS = 7
RESERVE_TOK = 8000000          # absolute tokens held back from B_rem: integration plus a verifier
HEALTHY_FRAC = 0.25            # a finish is healthy only while B_rem >= HEALTHY_FRAC * hard.prompt
UNDERSTATED_MAX = 3            # unplanned spawns past the slack before the plan terms switch off
CONFLICT_BUDGET_S = 0.2        # glob-overlap work per decision; past it the conflict term is skipped
# the docs' wording for Claude Code's spawn refusal (sub-agents.md#concurrent-subagent-limit); the
# hook-visible PostToolUseFailure text is unverified (open question 0(e))
CONCURRENCY_REFUSAL_HINT = "Concurrent subagent limit reached"

# copied from stack_sched.py (RISK_TAGS, EXCLUSIVE_TAGS); never imported: the guard imports this file
RISK_TAGS = frozenset(("hook", "security", "prod", "gui", "accel"))
EXCLUSIVE_TAGS = ("gui", "accel")

PLAN_MAX_BYTES = 64 * 1024
PLAN_MAX_DEPTH = 6
PLAN_MAX_NODES = 32
PLAN_MAX_GLOBS = 16
PLAN_MAX_GLOB_CHARS = 256
PLAN_MAX_SLACK = 4
NODE_ID_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_.-]{0,15}\Z")
TYPE_RE = re.compile(r"^[a-z][a-z0-9-]{0,47}\Z")
JOB_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}\Z")
OUTCOME_RE = re.compile(r"^[a-z_]{1,32}\Z")
SID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}\Z")
STOP_ERRORS_RL = ("rate_limit", "overloaded")      # StopFailure error -> beta_rl cut
STOP_ERRORS_FAIL = ("server_error", "unknown")     # StopFailure error -> beta_fail cut
RUNS_KEPT = 64                 # runs kept per node (aborted ones dropped first)
UNPLANNED_KEPT = 128
DENIALS_KEPT = 64

# state layout under <session state dir> (the guard writes, the report reads)
STATE_SUBDIR = "fanout-dyn"
LOG_NAME = "fanout-dyn.jsonl"

# ---------------------------------------------------------------- knobs (env-only fixed guards)
KNOB_DEFAULTS = {
    "STACK_FANOUT_DYN": "shadow",
    "STACK_FANOUT_DYN_ENFORCE": "node,deps",
    "STACK_FANOUT_DYN_TYPES": "orchestrator",
    "STACK_FANOUT_DYN_W0": "8",
    "STACK_FANOUT_DYN_WMIN": "1",
    "STACK_FANOUT_DYN_ALPHA": "1",
    "STACK_FANOUT_DYN_BETA_RL": "0.5",
    "STACK_FANOUT_DYN_BETA_FAIL": "0.75",
    "STACK_FANOUT_DYN_HOLD_S": "60",
    "STACK_FANOUT_DYN_RESERVE_TOK": str(RESERVE_TOK),
    "STACK_FANOUT_DYN_SLACK": "2",
    "STACK_FANOUT_DYN_NODE_RUNS": str(_NODE_RUNS),
    "STACK_FANOUT_DYN_DELAY_RATIO": "1.5",
    "STACK_FANOUT_DYN_BREAKER": "5/600",
}
KNOBS = tuple(sorted(KNOB_DEFAULTS))
# never in scope, whatever STACK_FANOUT_DYN_TYPES says (R2)
NEVER_SCOPED = frozenset(("blackcat", "main", ""))


def _int_in(raw, lo, hi):
    v = int(str(raw).strip())
    if v < lo or v > hi:
        raise ValueError(raw)
    return v


def _float_in(raw, lo, hi, lo_open=False):
    v = float(str(raw).strip())
    if not math.isfinite(v) or v > hi or v < lo or (lo_open and v == lo):
        raise ValueError(raw)
    return v


def _names(raw, allowed=None):
    out = []
    for item in re.split(r"[,;\s]+", str(raw).strip().strip("'\"").lower()):
        if not item:
            continue
        if allowed is not None and item not in allowed:
            raise ValueError(item)
        if allowed is None and not TYPE_RE.match(item):
            raise ValueError(item)
        if item not in out:
            out.append(item)
    return tuple(out)


def _mode(raw):
    names = _names(raw, MODES)
    if len(names) != 1:
        raise ValueError(raw)
    return names[0]


def _breaker(raw):
    m = re.match(r"^\s*(\d{1,4})\s*/\s*(\d{1,6})\s*s?\s*$", str(raw))
    if not m:
        raise ValueError(raw)
    return int(m.group(1)), int(m.group(2))


_KNOB_PARSE = {
    "STACK_FANOUT_DYN": _mode,
    "STACK_FANOUT_DYN_ENFORCE": lambda r: _names(r, ENFORCE_TERMS),
    "STACK_FANOUT_DYN_TYPES": lambda r: _names(r),
    "STACK_FANOUT_DYN_W0": lambda r: _int_in(r, 1, 1024),
    "STACK_FANOUT_DYN_WMIN": lambda r: _int_in(r, 1, 1024),
    "STACK_FANOUT_DYN_ALPHA": lambda r: _int_in(r, 0, 64),
    "STACK_FANOUT_DYN_BETA_RL": lambda r: _float_in(r, 0.0, 1.0, lo_open=True),
    "STACK_FANOUT_DYN_BETA_FAIL": lambda r: _float_in(r, 0.0, 1.0, lo_open=True),
    "STACK_FANOUT_DYN_HOLD_S": lambda r: _float_in(r, 0.0, 86400.0),
    "STACK_FANOUT_DYN_RESERVE_TOK": lambda r: _int_in(r, 0, 10 ** 12),
    "STACK_FANOUT_DYN_SLACK": lambda r: _int_in(r, 0, 32),
    "STACK_FANOUT_DYN_NODE_RUNS": lambda r: _int_in(r, 1, 32),
    "STACK_FANOUT_DYN_DELAY_RATIO": lambda r: _float_in(r, 1.0, 1000.0, lo_open=True),
    "STACK_FANOUT_DYN_BREAKER": _breaker,
}
_KNOB_KEY = {
    "STACK_FANOUT_DYN": "mode", "STACK_FANOUT_DYN_ENFORCE": "enforce",
    "STACK_FANOUT_DYN_TYPES": "types", "STACK_FANOUT_DYN_W0": "w0", "STACK_FANOUT_DYN_WMIN": "wmin",
    "STACK_FANOUT_DYN_ALPHA": "alpha", "STACK_FANOUT_DYN_BETA_RL": "beta_rl",
    "STACK_FANOUT_DYN_BETA_FAIL": "beta_fail", "STACK_FANOUT_DYN_HOLD_S": "hold_s",
    "STACK_FANOUT_DYN_RESERVE_TOK": "reserve_tok", "STACK_FANOUT_DYN_SLACK": "slack",
    "STACK_FANOUT_DYN_NODE_RUNS": "node_runs", "STACK_FANOUT_DYN_DELAY_RATIO": "delay_ratio",
    "STACK_FANOUT_DYN_BREAKER": "breaker",
}


def parse_knobs(env):
    """(knobs, warnings) from a mapping such as os.environ. An unset, empty or invalid value takes its
    default (each invalid one adds a warning naming the knob, never its value); STACK_POLICY=off
    turns the mode off. Never raises."""
    env = env if hasattr(env, "get") else {}
    out, warnings = {}, []
    for name in KNOBS:
        raw = env.get(name)
        parse = _KNOB_PARSE[name]
        val = None
        if raw is not None and str(raw).strip():
            try:
                val = parse(raw)
            except (ValueError, TypeError, IndexError):
                warnings.append("%s: invalid value ignored; default %s applies"
                                % (name, KNOB_DEFAULTS[name]))
        if val is None:
            val = parse(KNOB_DEFAULTS[name])
        out[_KNOB_KEY[name]] = val
    if str(env.get("STACK_POLICY", "on")).strip().lower() == "off":
        out["mode"] = "off"
    return out, warnings


DEFAULT_KNOBS = parse_knobs({})[0]


def in_scope(caller, caller_type, c_ceil, knobs):
    """True when the dynamic terms apply to this caller: mode not off, a static cap > 0, a subagent
    (never the main thread or BlackCat) whose type is listed in STACK_FANOUT_DYN_TYPES."""
    try:
        if knobs.get("mode", "off") == "off" or not isinstance(c_ceil, int) or c_ceil <= 0:
            return False
        if not caller or caller == "main" or (caller_type or "") in NEVER_SCOPED:
            return False
        return caller_type in knobs.get("types", ())
    except (AttributeError, TypeError):
        return False


# ---------------------------------------------------------------- plan (D1)
class PlanError(ValueError):
    """A rejected plan; the message holds only validated ids, integers and fixed text."""


def _sid(x):
    """x when it is a valid node id (safe to echo), else None."""
    return x if isinstance(x, str) and NODE_ID_RE.match(x) else None


def _depth(obj, limit):
    """True when obj nests at most `limit` containers deep (iterative)."""
    stack = [(obj, 1)]
    while stack:
        cur, d = stack.pop()
        if isinstance(cur, (dict, list)):
            if d > limit:
                return False
            items = cur.values() if isinstance(cur, dict) else cur
            stack.extend((x, d + 1) for x in items if isinstance(x, (dict, list)))
    return True


def _globs(nid, key, v):
    if v is None:
        return []
    if not isinstance(v, list) or len(v) > PLAN_MAX_GLOBS:
        raise PlanError("node %s: %s must be a list of at most %d globs" % (nid, key, PLAN_MAX_GLOBS))
    for g in v:
        if not isinstance(g, str) or not g or len(g) > PLAN_MAX_GLOB_CHARS or "\x00" in g:
            raise PlanError("node %s: each %s glob must be a non-empty string of at most %d characters"
                            % (nid, key, PLAN_MAX_GLOB_CHARS))
    return list(v)


def _find_cycle(nodes, left):
    """One dependency cycle among the node ids in `left`, as a list of ids ending where it began."""
    deps = {n["id"]: [d for d in n["dep"] if d in left] for n in nodes if n["id"] in left}
    start = sorted(left)[0]
    path, pos, cur = [], {}, start
    while cur not in pos:
        pos[cur] = len(path)
        path.append(cur)
        cur = deps[cur][0]
    return path[pos[cur]:] + [cur]


def _toposort(nodes):
    indeg = {n["id"]: len(set(n["dep"])) for n in nodes}
    kids = {n["id"]: [] for n in nodes}
    for n in nodes:
        for d in set(n["dep"]):
            kids[d].append(n["id"])
    ready = [n["id"] for n in nodes if indeg[n["id"]] == 0]
    out = []
    while ready:
        x = ready.pop(0)
        out.append(x)
        for c in kids[x]:
            indeg[c] -= 1
            if indeg[c] == 0:
                ready.append(c)
    if len(out) != len(nodes):
        cyc = _find_cycle(nodes, {i for i, k in indeg.items() if k > 0})
        raise PlanError("cycle %s" % "→".join(cyc))
    return out


def _max_width(nodes, order):
    byid = {n["id"]: n for n in nodes}
    level, counts = {}, {}
    for i in order:
        level[i] = 1 + max([level[d] for d in byid[i]["dep"]], default=-1)
        counts[level[i]] = counts.get(level[i], 0) + 1
    return max(counts.values()) if counts else 0


def parse_plan(content, allowed_types=None):
    """Validate an orchestrator's plan.dag.json content (a str or bytes from tool_input.content, or
    an already decoded dict) and return its normalized copy:
      {"v": 1, "job", "slack" (int or None), "width", "nodes": [{"id", "a", "alt", "dep", "w", "rd",
       "r"}]}  (nodes in the file's order).
    allowed_types: the caller's POLICY row (every `a` and `alt` must be in it); None skips that check.
    Raises PlanError with a message safe to show (validated ids, integers, fixed text)."""
    if isinstance(content, (bytes, bytearray)):
        if len(content) > PLAN_MAX_BYTES:
            raise PlanError("plan larger than %d bytes" % PLAN_MAX_BYTES)
        try:
            content = bytes(content).decode("utf-8")
        except UnicodeDecodeError:
            raise PlanError("plan is not UTF-8") from None
    if isinstance(content, str):
        if len(content.encode("utf-8", "replace")) > PLAN_MAX_BYTES:
            raise PlanError("plan larger than %d bytes" % PLAN_MAX_BYTES)
        try:
            data = json.loads(content)
        except RecursionError:
            raise PlanError("plan nests deeper than %d levels" % PLAN_MAX_DEPTH) from None
        except ValueError:
            raise PlanError("plan is not valid JSON") from None
    else:
        data = content
    if not isinstance(data, dict):
        raise PlanError("plan must be a JSON object")
    if not _depth(data, PLAN_MAX_DEPTH):
        raise PlanError("plan nests deeper than %d levels" % PLAN_MAX_DEPTH)
    job = data.get("job")
    if not isinstance(job, str) or not JOB_RE.match(job):
        raise PlanError("job must be a name of letters, digits, '_', '.', '-' (at most 64)")
    slack = data.get("slack")
    if slack is not None and (not isinstance(slack, int) or isinstance(slack, bool)
                              or not 0 <= slack <= PLAN_MAX_SLACK):
        raise PlanError("slack must be an integer from 0 to %d" % PLAN_MAX_SLACK)
    raw = data.get("nodes")
    if not isinstance(raw, list) or not raw:
        raise PlanError("plan needs a non-empty nodes list")
    if len(raw) > PLAN_MAX_NODES:
        raise PlanError("plan has more than %d nodes" % PLAN_MAX_NODES)
    row = None if allowed_types is None else frozenset(allowed_types)
    nodes, seen = [], set()
    for i, rn in enumerate(raw):
        if not isinstance(rn, dict):
            raise PlanError("node %d is not an object" % i)
        nid = rn.get("id")
        if not _sid(nid):
            raise PlanError("node %d: id must match %s" % (i, NODE_ID_RE.pattern))
        if nid in seen:
            raise PlanError("duplicate node id %s" % nid)
        seen.add(nid)
        types = []
        for key in ("a", "alt"):
            t = rn.get(key)
            if t is None and key == "alt":
                types.append(None)
                continue
            if not isinstance(t, str) or not TYPE_RE.match(t):
                raise PlanError("node %s: %s must be an agent type" % (nid, key))
            if row is not None and t not in row:
                raise PlanError("node %s: %s is not an agent type this caller may spawn" % (nid, key))
            types.append(t)
        dep = rn.get("dep", [])
        if not isinstance(dep, list) or len(dep) > PLAN_MAX_NODES or \
                not all(isinstance(d, str) for d in dep):
            raise PlanError("node %s: dep must be a list of node ids" % nid)
        r = rn.get("r", [])
        if not isinstance(r, list) or not all(isinstance(t, str) and t in RISK_TAGS for t in r):
            raise PlanError("node %s: r must be a subset of %s" % (nid, "|".join(sorted(RISK_TAGS))))
        s, n = rn.get("s"), rn.get("n")
        if s is not None and s not in ("S", "M", "L"):
            raise PlanError("node %s: s must be S, M or L" % nid)
        if n is not None and (not isinstance(n, int) or isinstance(n, bool) or n < 1):
            raise PlanError("node %s: n must be a positive integer" % nid)
        nodes.append({"id": nid, "a": types[0], "alt": types[1], "dep": list(dict.fromkeys(dep)),
                      "w": _globs(nid, "w", rn.get("w")), "rd": _globs(nid, "rd", rn.get("rd")),
                      "r": sorted(set(r))})
    for nd in nodes:
        for d in nd["dep"]:
            if d == nd["id"]:
                raise PlanError("node %s depends on itself" % nd["id"])
            if d not in seen:
                shown = _sid(d)
                raise PlanError("node %s depends on an unknown node%s"
                                % (nd["id"], " " + shown if shown else ""))
    order = _toposort(nodes)
    return {"v": 1, "job": job, "slack": slack, "width": _max_width(nodes, order), "nodes": nodes}


def plan_accept_text(plan):
    return "plan accepted: %d nodes, max width %d" % (len(plan["nodes"]), int(plan["width"]))


def plan_reject_text(err, c_ceil):
    return "plan rejected: %s; static cap %d applies" % (err, int(c_ceil))


def chain_types(node):
    """Agent types a spawn for `node` may have: its a, its alt, and every escalation-chain step after
    the earliest of them on coder -> main-coder -> ninja-coder -> supreme-coder."""
    own = [t for t in (node.get("a"), node.get("alt")) if t]
    on = [CHAIN.index(t) for t in own if t in CHAIN]
    later = list(CHAIN[min(on) + 1:]) if on else []
    return tuple(dict.fromkeys(own + later))


def node_of(plan, description, child_type):
    """(node id or None, why) for a spawn: the first word of the raw Agent description names the node
    and child_type must be in chain_types(node). why: planned | no_plan | no_label | unknown_node |
    type_mismatch. Anything but planned is an unplanned spawn."""
    if not plan:
        return None, "no_plan"
    words = str(description or "").split()
    if not words:
        return None, "no_label"
    word = words[0].rstrip(":,;")
    for nd in plan.get("nodes", ()):
        if nd["id"] == word:
            return (nd["id"], "planned") if child_type in chain_types(nd) else (None, "type_mismatch")
    return None, "unknown_node"


# ---------------------------------------------------------------- glob overlap (copied)
def glob_overlap(a, b):
    """Conservative: could two write globs name the same file? (stack_sched._glob_overlap, copied.)"""
    sa, sb = a.strip("/").split("/"), b.strip("/").split("/")
    for i in range(max(len(sa), len(sb))):
        if i >= len(sa) or i >= len(sb):
            last = sa[-1] if len(sa) < len(sb) else sb[-1]
            return not any(ch in last for ch in "*?[")          # a plain directory covers what is below
        x, y = sa[i], sb[i]
        if x == "**" or y == "**":
            return True
        if x == y or fnmatch.fnmatch(x, y) or fnmatch.fnmatch(y, x):
            continue
        if any(ch in x for ch in "*?[") and any(ch in y for ch in "*?["):
            fx, fy = _first_chars(x), _first_chars(y)
            if fx is not None and fy is not None and not _ranges_meet(fx, fy):
                return False                                      # e.g. [a-m]* and [n-z]*
            continue                                              # two patterns: maybe the same name
        return False
    return True


def _first_chars(seg):
    """The code-point ranges [(lo, hi)] a name matching `seg` can start with, None when any
    (copied). Ranges stay intervals, never expanded: a class over all of Unicode costs the same as
    [a-m]."""
    if not seg or seg[0] in "*?":
        return None
    if seg[0] != "[":
        return [(ord(seg[0]), ord(seg[0]))]
    end = seg.find("]", 2)
    if end < 0:
        return None
    body, out, i = seg[1:end], [], 0
    if body[:1] in "!^":
        return None
    while i < len(body):
        if i + 2 < len(body) and body[i + 1] == "-":
            out.append((ord(body[i]), ord(body[i + 2])))
            i += 3
        else:
            out.append((ord(body[i]), ord(body[i])))
            i += 1
    return out


def _ranges_meet(xs, ys):
    """True when two lists of (lo, hi) code-point ranges share a character (an empty range, lo >
    hi, holds none)."""
    return any(a <= d and c <= b for a, b in xs if a <= b for c, d in ys if c <= d)


class _Deadline(Exception):
    pass


def _sets_overlap(xs, ys, deadline, clock):
    for x in xs:
        for y in ys:
            if clock() > deadline:
                raise _Deadline()
            if glob_overlap(x, y):
                return True
    return False


# ---------------------------------------------------------------- node state (D1)
def nodes_new(job=None):
    """An empty node state for one orchestrator (JSON-serializable)."""
    return {"v": 1, "job": job, "runs": {}, "unplanned": [], "ready_ts": {}, "understated": 0,
            "plan_off": False, "breaker": {"denials": [], "tripped": False}}


def _norm_nodes(nodes):
    base = nodes_new()
    if isinstance(nodes, dict):
        for k in base:
            if k in nodes and isinstance(nodes[k], type(base[k])):
                base[k] = nodes[k]
        if isinstance(nodes.get("job"), str):
            base["job"] = nodes["job"]
    return base


def nodes_for_plan(nodes, plan):
    """The node state to use with `plan`: a new job (a Write to another job path) starts fresh node
    runs; the breaker carries over (it belongs to the orchestrator, not the plan)."""
    st = _norm_nodes(copy.deepcopy(nodes))
    if plan is None or st.get("job") == plan.get("job"):
        return st
    fresh = nodes_new(plan.get("job"))
    fresh["breaker"] = st["breaker"]
    return fresh


def run_status(run, live_tids, live_children):
    """live | aborted | ended (D1)."""
    if run.get("tid") is not None and run.get("tid") in live_tids:
        return "live"
    cid = run.get("child_id")
    if cid is None:
        return "aborted"
    return "live" if cid in live_children else "ended"


def _all_runs(st):
    for nid, runs in st["runs"].items():
        for r in runs:
            yield nid, r
    for r in st["unplanned"]:
        yield None, r


def record_spawn(nodes, node_id, tid, child_type, now, iso=False):
    """A new state with a run for an allowed spawn (node_id None: an unplanned one). Called inside
    the guard's fanout_acquire, under the 'fanout' mutex."""
    st = _norm_nodes(copy.deepcopy(nodes))
    run = {"tid": str(tid) if tid is not None else None, "child_id": None, "type": str(child_type),
           "t_spawn": float(now), "t_end": None, "outcome": None, "iso": bool(iso)}
    lst = st["unplanned"] if node_id is None else st["runs"].setdefault(str(node_id), [])
    lst.append(run)
    keep = UNPLANNED_KEPT if node_id is None else RUNS_KEPT
    while len(lst) > keep:
        idx = next((i for i, r in enumerate(lst) if r.get("child_id") is None and r is not run), 0)
        lst.pop(idx)
    return st


def bind_child(nodes, tid, child_id):
    """(new state, found): bind the child's agent id to the run of spawn lease `tid` (on_agent_done,
    from the event's tool_use_id)."""
    st = _norm_nodes(copy.deepcopy(nodes))
    for _, r in _all_runs(st):
        if tid is not None and r.get("tid") == tid:
            r["child_id"] = str(child_id) if child_id is not None else None
            return st, True
    return st, False


def end_run(nodes, child_id, now, outcome="ok"):
    """(new state, found): record the end of the run of `child_id` (mark_stopped, on_stop_failure);
    a run already ended keeps its first end."""
    st = _norm_nodes(copy.deepcopy(nodes))
    oc = outcome if isinstance(outcome, str) and OUTCOME_RE.match(outcome) else "other"
    for _, r in _all_runs(st):
        if child_id is not None and r.get("child_id") == child_id:
            if r.get("t_end") is None:
                r["t_end"], r["outcome"] = float(now), oc
            return st, True
    return st, False


def remove_run(nodes, tid):
    """(new state, found): drop the run of spawn lease `tid` (on_agent_failed, and the rollback() of
    a spawn a later on_agent gate denied), so the node is free again."""
    st = _norm_nodes(copy.deepcopy(nodes))
    for key, lst in list(st["runs"].items()) + [(None, st["unplanned"])]:
        for i, r in enumerate(lst):
            if tid is not None and r.get("tid") == tid:
                lst.pop(i)
                if key is not None and not lst:
                    del st["runs"][key]
                return st, True
    return st, False


def compact(nodes, live_tids, live_children):
    """A new state without aborted runs and without ended unplanned runs (bounded state)."""
    st = _norm_nodes(copy.deepcopy(nodes))
    lt, lc = frozenset(live_tids), frozenset(live_children)
    for nid in list(st["runs"]):
        st["runs"][nid] = [r for r in st["runs"][nid] if run_status(r, lt, lc) != "aborted"]
        if not st["runs"][nid]:
            del st["runs"][nid]
    st["unplanned"] = [r for r in st["unplanned"] if run_status(r, lt, lc) == "live"]
    return st


def mark_ready(nodes, eligible, now):
    """A new state where each node in `eligible` without a ready_ts gets `now` (queue-time metric)."""
    st = _norm_nodes(copy.deepcopy(nodes))
    for nid in eligible:
        st["ready_ts"].setdefault(nid, float(now))
    return st


def note_understated(nodes):
    """A new state after an unplanned spawn past the slack: after UNDERSTATED_MAX of them the plan
    terms switch off for this orchestrator."""
    st = _norm_nodes(copy.deepcopy(nodes))
    st["understated"] = int(st["understated"]) + 1
    if st["understated"] >= UNDERSTATED_MAX:
        st["plan_off"] = True
    return st


def breaker_note_denial(nodes, now, knobs=None):
    """A new state after a dynamic denial (each one the static cap would have allowed): BREAKER
    count denials within its window with no new child trip the breaker for good (this orchestrator
    goes back to static until the session restarts). A count of 0 disables the breaker."""
    k = knobs or DEFAULT_KNOBS
    count, window = k["breaker"]
    st = _norm_nodes(copy.deepcopy(nodes))
    br = st["breaker"]
    dn = [float(t) for t in br.get("denials", []) if now - float(t) <= window] + [float(now)]
    br["denials"] = dn[-DENIALS_KEPT:]
    if count > 0 and len(dn) >= count:
        br["tripped"] = True
    return st


def breaker_note_child(nodes):
    """A new state after a new child of this orchestrator started: the denial count restarts."""
    st = _norm_nodes(copy.deepcopy(nodes))
    st["breaker"]["denials"] = []
    return st


def _live_nodes(plan, st, lt, lc):
    live = {}
    for nd in plan["nodes"]:
        runs = [r for r in st["runs"].get(nd["id"], []) if run_status(r, lt, lc) == "live"]
        if runs:
            live[nd["id"]] = any(r.get("iso") for r in runs)
    return live


def node_block(plan, node_id, nodes, live_tids, live_children, knobs=None, isolation=None,
               clock=time.monotonic, budget_s=CONFLICT_BUDGET_S, _live=None):
    """Why `node_id` is not ready, as (code, detail), or None when it is:
      ("running", None)            it has a live run
      ("runs_used", NODE_RUNS)     its non-aborted runs reached NODE_RUNS
      ("deps", [dep ids])          some dependency has no ended run
      ("exclusive", (node, tag))   a live node shares the gui or accel tag
      ("conflict", node)           its w overlaps a live node's w or rd, or its rd a live node's w,
                                   and neither runs with isolation "worktree"
    Glob overlap past budget_s seconds is skipped (that term falls back to static)."""
    k = knobs or DEFAULT_KNOBS
    st = _norm_nodes(nodes)
    lt, lc = frozenset(live_tids), frozenset(live_children)
    byid = {nd["id"]: nd for nd in plan["nodes"]}
    nd = byid[node_id]
    stats = [run_status(r, lt, lc) for r in st["runs"].get(node_id, [])]
    if "live" in stats:
        return ("running", None)
    if sum(1 for s in stats if s != "aborted") >= k["node_runs"]:
        return ("runs_used", k["node_runs"])
    waiting = [d for d in nd["dep"]
               if "ended" not in [run_status(r, lt, lc) for r in st["runs"].get(d, [])]]
    if waiting:
        return ("deps", waiting)
    live = _live_nodes(plan, st, lt, lc) if _live is None else _live
    for u in byid:
        if u not in live or u == node_id:
            continue
        shared = [t for t in EXCLUSIVE_TAGS if t in nd["r"] and t in byid[u]["r"]]
        if shared:
            return ("exclusive", (u, shared[0]))
    if isolation == "worktree" or not (nd["w"] or nd["rd"]):
        return None
    deadline = clock() + budget_s
    try:
        for u in byid:
            if u not in live or u == node_id or live[u]:
                continue
            other = byid[u]
            if _sets_overlap(nd["w"], other["w"] + other["rd"], deadline, clock) or \
                    _sets_overlap(nd["rd"], other["w"], deadline, clock):
                return ("conflict", u)
    except _Deadline:
        return None
    return None


def ready_eligible(plan, nodes, live_tids, live_children, knobs=None, clock=time.monotonic,
                   budget_s=CONFLICT_BUDGET_S):
    """(R_elig: ready node ids in plan order, {blocked node id: (code, detail)}), with no isolation
    assumed for the candidates (D2). A dependency counts once it has an ended run, whatever the
    outcome."""
    st = _norm_nodes(nodes)
    lt, lc = frozenset(live_tids), frozenset(live_children)
    live = _live_nodes(plan, st, lt, lc)
    deadline_total = clock() + budget_s
    elig, blocked = [], {}
    for nd in plan["nodes"]:
        left = max(0.0, deadline_total - clock())
        why = node_block(plan, nd["id"], st, lt, lc, knobs, None, clock, left, _live=live)
        if why is None:
            elig.append(nd["id"])
        else:
            blocked[nd["id"]] = why
    return elig, blocked


def unplanned_live(nodes, live_tids, live_children):
    """U: the orchestrator's live unplanned children."""
    st = _norm_nodes(nodes)
    lt, lc = frozenset(live_tids), frozenset(live_children)
    return sum(1 for r in st["unplanned"] if run_status(r, lt, lc) == "live")


# ---------------------------------------------------------------- cost model (copied built-ins)
# stack_sched.py's provisional defaults (_TURNS, _CTX, _SPC, _POOL_REP, the pool sets, UNVERIFIED_W),
# copied: the guard never imports stack_sched. Parity: c_med(t) == stack_sched._est_for(m, t, None,
# None).ctx_p50 and wall_hi(t) == ...wall_hi for the same model.
_TURNS = {"claude-code-engineer": (42, 83), "coder": (18, 107), "verifier": (37, 91),
          "code-reviewer": (41, 60), "planner": (27, 33), "researcher": (32, 48),
          "claude-code-guide": (5, 9), "scout": (5, 7), "explore": (7, 8), "main-coder": (44, 228),
          "writer": (9, 10), "browser-operator": (17, 37), "orchestrator": (2, 4)}
_CTX = {"claude-code-engineer": (95000, 1300), "scout": (12044, 3987), "claude-code-guide": (20824, 2975),
        "code-reviewer": (25284, 1217), "verifier": (24929, 930), "researcher": (82033, 887),
        "coder": (31603, 1297), "browser-operator": (28814, 1047), "planner": (60000, 900),
        "explore": (12044, 3987), "main-coder": (95000, 1300), "writer": (28814, 1047),
        "orchestrator": (100000, 0)}
_SPC = {"claude-code-engineer": (14, 29), "planner": (34, 40), "code-reviewer": (12, 15),
        "verifier": (13, 24), "scout": (8, 9), "claude-code-guide": (8, 9), "explore": (7, 8),
        "researcher": (36, 46), "coder": (7, 22), "main-coder": (9, 13), "browser-operator": (15, 17),
        "writer": (44, 48), "orchestrator": (5, 20)}
_POOL_REP = {"builder": "claude-code-engineer", "analyst": "researcher", "lookup": "explore",
             "verifier": "verifier", "artifact": "writer", "reviewer": "code-reviewer"}
_ANALYST = frozenset(("planner", "plan-reviewer", "researcher", "security-auditor", "proof-checker"))
_LOOKUP = frozenset(("explore", "oracle", "mcp-broker", "scout", "claude-code-guide"))
_ARTIFACT = frozenset(("writer", "browser-operator", "doc-specialist", "designer", "image-director",
                       "motion-designer", "cg-artist"))
UNVERIFIED_W = 1.0
MODEL_MAX_BYTES = 4 << 20


def pool_of(t):
    if t == "verifier":
        return "verifier"
    if t in ("code-reviewer", "security-auditor"):
        return "reviewer"
    if t in _ANALYST:
        return "analyst"
    if t in _LOOKUP:
        return "lookup"
    if t in _ARTIFACT:
        return "artifact"
    return "builder"


def _builtin(t):
    rep = t if t in _TURNS else _POOL_REP[pool_of(t)]
    t_med, t_long = _TURNS[rep]
    a, b = _CTX.get(rep, _CTX["claude-code-engineer"])
    p50, p90 = _SPC.get(rep, (14, 29))
    return {"turns": {"S": max(1, t_med // 2), "M": t_med, "L": t_long}, "ctx": {"a": a, "b": b},
            "sec_per_call": {"p50": p50, "p90": p90}}


def _merge(base, over):
    out = dict(base)
    for k, v in over.items():
        if v is None:
            continue
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = dict(out[k], **{kk: vv for kk, vv in v.items() if vv is not None})
        else:
            out[k] = v
    return out


def _clamp_band(band):
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


def _band_factors(model, info, t):
    """(turns, sec_per_call) hi/med factors: the type's band, else its pool's, else 1 + UNVERIFIED_W
    (stack_sched.band_of)."""
    band, src = _clamp_band(info.get("band")), "own"
    pools = model.get("pools") if isinstance(model.get("pools"), dict) else {}

    def ok(b):
        return isinstance(b, dict) and all(isinstance(b.get(k), dict) and b[k].get("med")
                                           for k in ("turns", "sec_per_call"))

    pname = info.get("tier") or {"reviewer": "analyst"}.get(pool_of(t), pool_of(t))
    if not ok(band):
        prow = pools.get(pname)
        if isinstance(prow, dict) and ok(_clamp_band(prow.get("band"))):
            band, src = _clamp_band(prow["band"]), "pool"
        else:
            band, src = None, "heuristic"

    def f(q):
        d = (band or {}).get(q)
        if not d and src == "own":
            pb = _clamp_band((pools.get(pname) or {}).get("band"))
            d = (pb or {}).get(q)
            if not d:
                return 1.0 + UNVERIFIED_W
        try:
            return max(1.0, float(d["hi"]) / float(d["med"])) if d else 1.0 + UNVERIFIED_W
        except (KeyError, TypeError, ValueError, ZeroDivisionError):
            return 1.0 + UNVERIFIED_W

    return f("turns"), f("sec_per_call")


def _num(x, what):
    v = float(x)
    if not math.isfinite(v) or v < 0:
        raise ValueError(what)
    return v


def cost_model(model, t):
    """{"c_med", "wall_hi", "spc_p90"} of agent type `t`: c_med = a*M + b*M^2 context tokens (M the
    type's median turns), wall_hi from the band, spc_p90 the p90 seconds per call. model: the parsed
    sched model (the session's copy) or None for the built-ins. Raises ValueError on a malformed model
    row (the caller treats the budget as unknown: K_B = infinity)."""
    model = model if isinstance(model, dict) else {}
    types = model.get("types") if isinstance(model.get("types"), dict) else {}
    row = types.get(t)
    info = _merge(_builtin(t), row if isinstance(row, dict) else {})
    tu, ctx, spc = info["turns"], info["ctx"], info["sec_per_call"]
    n50 = max(1, int(round(_num(tu["M"], "turns"))))
    a, b = _num(ctx["a"], "ctx.a"), _num(ctx["b"], "ctx.b")
    bt, bs = _band_factors(model, info, t)
    return {"c_med": a * n50 + b * n50 * n50,
            "wall_hi": n50 * bt * _num(spc["p50"], "spc") * bs,
            "spc_p90": _num(spc["p90"], "spc")}


def c_med(model, t):
    return cost_model(model, t)["c_med"]


_MODEL_CACHE = {}


def load_model(path):
    """The parsed sched model at `path`, cached per (path, mtime, size); None when missing, larger
    than MODEL_MAX_BYTES, unreadable or not an object. Read-only."""
    try:
        stt = os.stat(path)
        key = (str(path), stt.st_mtime_ns, stt.st_size)
        if key in _MODEL_CACHE:
            return _MODEL_CACHE[key]
        if stt.st_size > MODEL_MAX_BYTES:
            return None
        with open(path, "rb") as f:
            data = json.loads(f.read().decode("utf-8"))
    except (OSError, ValueError, RecursionError, TypeError):
        return None
    data = data if isinstance(data, dict) else None
    _MODEL_CACHE.clear()
    _MODEL_CACHE[key] = data
    return data


# ---------------------------------------------------------------- budget (D2)
def budget_remaining(hard_prompt, hard_session, total, used_p):
    """B_rem = min(hard.prompt - used_p, hard.session - total) over the caps that are on (> 0);
    None when neither is on or an input is not a number (unknown budget)."""
    try:
        parts = []
        if hard_prompt and float(hard_prompt) > 0:
            parts.append(float(hard_prompt) - float(used_p or 0))
        if hard_session and float(hard_session) > 0:
            parts.append(float(hard_session) - float(total or 0))
    except (TypeError, ValueError):
        return None
    vals = [p for p in parts if math.isfinite(p)]
    return min(vals) if vals and len(vals) == len(parts) else None


def commit_tokens(children, model):
    """Commit = sum over live children (type, seg) of max(0, c_med(type) - seg): what they are
    still expected to use. seg: the child's context tokens so far (budget.json files[].seg)."""
    total = 0.0
    for t, seg in children:
        total += max(0.0, c_med(model, t) - float(seg or 0))
    return total


def k_budget(b_rem, commit, reserve, costs):
    """K_B = max k with costs[0] + ... + costs[k-1] <= b_rem - commit - reserve; past the listed
    costs further spawns cost like costs[0]. None (infinity) when b_rem is None, costs is empty or a
    further spawn costs nothing. Never negative."""
    if b_rem is None or not costs:
        return None
    room = float(b_rem) - float(commit or 0) - float(reserve or 0)
    k = 0
    for c in costs:
        c = max(0.0, float(c))
        if c > room:
            return k
        room -= c
        k += 1
    first = max(0.0, float(costs[0]))
    if first <= 0:
        return None
    return k + int(room // first)


def healthy_budget(b_rem, hard_prompt):
    """The budget part of a healthy finish: B_rem >= HEALTHY_FRAC * hard.prompt (True when unknown)."""
    try:
        if b_rem is None or not hard_prompt or float(hard_prompt) <= 0:
            return True
        return float(b_rem) >= HEALTHY_FRAC * float(hard_prompt)
    except (TypeError, ValueError):
        return True


def finish_healthy(stopped_normally, duration_s, wall_hi, soft_hit, b_rem, hard_prompt):
    """A child's finish counts as healthy (D3) when it stopped normally, took at most wall_hi(t)
    seconds, had no soft_agent hit for that run, and B_rem >= 0.25 x hard.prompt."""
    try:
        within = duration_s is not None and wall_hi is not None and float(duration_s) <= float(wall_hi)
    except (TypeError, ValueError):
        within = False
    return bool(stopped_normally) and within and not soft_hit and healthy_budget(b_rem, hard_prompt)


def delay_ratio(children, now, model):
    """r = median over live children (type, started, seg_calls) with at least 3 calls of
    ((now - started) / seg_calls) / spc_p90(type); None when no child qualifies (shadow-only)."""
    rs = []
    for t, started, calls in children:
        try:
            calls, started = int(calls), float(started)
            if calls < 3:
                continue
            p90 = cost_model(model, t)["spc_p90"]
            if p90 > 0:
                rs.append(((float(now) - started) / calls) / p90)
        except (TypeError, ValueError, KeyError):
            continue
    if not rs:
        return None
    rs.sort()
    mid = len(rs) // 2
    return rs[mid] if len(rs) % 2 else (rs[mid - 1] + rs[mid]) / 2.0


# ---------------------------------------------------------------- AIMD window (D3)
def aimd_new(c_ceil, knobs=None):
    k = knobs or DEFAULT_KNOBS
    return {"v": 1, "w": max(1, min(int(c_ceil), k["w0"])), "last_dec": None}


def aimd_window(aimd, c_ceil, knobs=None):
    """W clamped to [min(W_min, C_ceil), C_ceil]; a missing or bad state starts at min(C_ceil, W0)."""
    k = knobs or DEFAULT_KNOBS
    c = int(c_ceil)
    try:
        w = int(aimd["w"])
    except (TypeError, KeyError, ValueError):
        w = min(c, k["w0"])
    return max(min(k["wmin"], c), min(c, w))


def aimd_update(aimd, event, now, c_ceil, knobs=None, healthy=False, error=None):
    """(new AIMD state, action) for one lifecycle event of a child of the orchestrator:
      "finish"        healthy -> W + alpha (capped at C_ceil); otherwise no change
      "stop_failure"  error rate_limit|overloaded -> W = max(W_min, floor(beta_rl W));
                      server_error|unknown -> beta_fail; any other error: no change
      "refusal"       Claude Code's concurrency refusal (PostToolUseFailure) -> beta_rl
      "delay"         the delay signal: shadow only, W unchanged, action "shadow_cut"
      anything else   no change
    A cut happens only when the last one is at least HOLD_S old (one per wave). action: increase |
    cut | hold | shadow_cut | none."""
    k = knobs or DEFAULT_KNOBS
    st = dict(aimd) if isinstance(aimd, dict) else aimd_new(c_ceil, k)
    w = aimd_window(st, c_ceil, k)
    st["w"] = w
    beta = None
    if event == "finish":
        if healthy and k["alpha"] > 0 and w < int(c_ceil):
            st["w"] = min(int(c_ceil), w + k["alpha"])
            return st, "increase"
        return st, "none"
    if event == "stop_failure":
        beta = k["beta_rl"] if error in STOP_ERRORS_RL else \
            k["beta_fail"] if error in STOP_ERRORS_FAIL else None
    elif event == "refusal":
        beta = k["beta_rl"]
    elif event == "delay":
        return st, "shadow_cut"
    if beta is None:
        return st, "none"
    last = st.get("last_dec")
    if isinstance(last, (int, float)) and now - float(last) < k["hold_s"]:
        return st, "hold"
    st["w"] = max(min(k["wmin"], int(c_ceil)), int(math.floor(beta * w)))
    st["last_dec"] = float(now)
    return st, "cut"


# ---------------------------------------------------------------- decision (D2)
def _static(c_ceil, binding, mode, kind, **extra):
    cap = c_ceil if isinstance(c_ceil, int) and not isinstance(c_ceil, bool) else 0
    out = {"allow": True, "would_allow": True, "cap": cap, "binding": binding, "terms": {"ceil": cap},
           "reason": None, "code": None, "mode": mode, "kind": kind, "planned": False, "node": None,
           "understated": False, "eligible": [], "free": None, "fallback": True, "fails": []}
    out.update(extra)
    return out


def dyn_decision(knobs, kind, caller, caller_type, c_ceil, n, child_type, plan=None, nodes=None,
                 node_id=None, isolation=None, live_tids=(), live_children=(), b_rem=None, commit=0.0,
                 model=None, aimd=None, k_sess=None, clock=time.monotonic):
    """The dynamic fan-out decision for one Agent spawn (kind "spawn") or resume (kind "resume") of
    `caller`, called by the guard after its static checks passed, under the 'fanout' mutex.

    Inputs: knobs (parse_knobs), c_ceil = fanout_limit(caller), n = running_children (idle filter
    on), child_type the requested subagent_type, plan (parse_plan, or None), nodes (node state),
    node_id (node_of; None = unplanned), isolation (tool_input.isolation), live_tids (the caller's
    live lease ids), live_children (the ids of registered children not stopped), b_rem
    (budget_remaining; None = unknown), commit (commit_tokens), model (sched model or None), aimd
    (AIMD state), k_sess (MAXC - n_sess, or None).

    Returns {allow, would_allow, cap, binding, terms, reason, code, mode, kind, planned, node,
    understated, eligible, free, fallback}: allow is what the guard does (always True in off and
    shadow mode); would_allow is the decision with every term enforced (the shadow log); cap = C_dyn
    <= c_ceil; code the first failing term's deny code (running, runs_used, deps, exclusive,
    conflict, ceil, window, budget) and reason its deny text. Any exception is the static decision
    (allow True, fallback True, binding "error")."""
    mode = "off"
    try:
        knobs = DEFAULT_KNOBS if knobs is None else knobs
        mode = knobs.get("mode", "off")
        if mode == "off":
            return _static(c_ceil, "off", mode, kind)
        if not in_scope(caller, caller_type, c_ceil, knobs):
            return _static(c_ceil, "scope", mode, kind)
        return _decide(knobs, mode, kind, c_ceil, n, child_type, plan, nodes, node_id, isolation,
                       live_tids, live_children, b_rem, commit, model, aimd, k_sess, clock)
    except Exception as exc:  # noqa: BLE001 - R3: any failure is the static decision
        return _static(c_ceil, "error", mode, kind, error=type(exc).__name__)


def _decide(k, mode, kind, c_ceil, n, child_type, plan, nodes, node_id, isolation, live_tids,
            live_children, b_rem, commit, model, aimd, k_sess, clock):
    if kind not in ("spawn", "resume"):
        raise ValueError("kind")
    if not isinstance(n, int) or isinstance(n, bool) or n < 0:
        raise ValueError("n")
    st = _norm_nodes(nodes)
    if st["breaker"].get("tripped"):
        return _static(c_ceil, "breaker", mode, kind)
    lt, lc = frozenset(live_tids), frozenset(live_children)
    plan_on = plan is not None and kind == "spawn" and not st.get("plan_off")
    planned = bool(plan_on and node_id is not None
                   and any(nd["id"] == node_id for nd in plan["nodes"]))
    w = aimd_window(aimd, c_ceil, k)
    terms = {"ceil": c_ceil, "w": w}
    fails, elig, understated = [], [], False

    if plan_on:
        elig, _blocked = ready_eligible(plan, st, lt, lc, k, clock)
        u = unplanned_live(st, lt, lc)
        slack = plan["slack"] if plan.get("slack") is not None else k["slack"]
        if planned:
            why = node_block(plan, node_id, st, lt, lc, k, isolation, clock)
            if why is not None:
                fails.append(why)
            elif node_id not in elig:
                elig = [nd["id"] for nd in plan["nodes"] if nd["id"] in elig or nd["id"] == node_id]
        else:
            understated = u >= slack
        terms["elig"] = n + len(elig) + max(0, slack - u)
        terms["u"], terms["slack"] = u, slack

    kb = None
    try:
        others = []
        if plan_on:
            byid = {nd["id"]: nd for nd in plan["nodes"]}
            others = [c_med(model, byid[v]["a"]) for v in elig if v != node_id]
        kb = k_budget(b_rem, commit, k["reserve_tok"], [c_med(model, child_type)] + others)
    except (ValueError, TypeError, KeyError):
        kb = None                                     # unknown model: K_B = infinity (fail open)
    if kb is not None:
        terms["kb"] = n + kb
    if k_sess is not None:
        terms["sess"] = n + int(k_sess)

    if n >= c_ceil:
        fails.append(("ceil", c_ceil))
    if n > 0 and n >= w:                              # R4: with no child running W is ignored
        fails.append(("window", w))
    if kb is not None and kb < 1:
        fails.append(("budget", int(max(0.0, (b_rem or 0) - (commit or 0)))))

    cap_terms = {key: v for key, v in terms.items() if key in ("ceil", "elig", "w", "kb", "sess")}
    cap = max(0, min(min(cap_terms.values()), c_ceil))
    binding = min(cap_terms, key=lambda key: (cap_terms[key], list(cap_terms).index(key)))
    enforced = [f for f in fails
                if CODE_TERM[f[0]] == "static" or CODE_TERM[f[0]] in k["enforce"]]
    allow = mode != "enforce" or not enforced
    shown = enforced[0] if (mode == "enforce" and enforced) else (fails[0] if fails else None)
    out = {"allow": allow, "would_allow": not fails, "cap": cap,
           "binding": shown[0] if shown else binding, "terms": terms, "code": None,
           "reason": None, "mode": mode, "kind": kind, "planned": planned,
           "node": node_id if planned else None, "understated": understated,
           "eligible": list(elig), "free": max(0, cap - n), "fallback": False,
           "fails": [f[0] for f in fails]}
    if shown:
        out["code"] = shown[0]
        out["reason"] = deny_text(shown, out, k, child_type)
    return out


def deny_text(fail, result, knobs=None, child_type=None):
    """The deny text of a failing term: fixed text, integers and validated ids only (D6)."""
    k = knobs or DEFAULT_KNOBS
    code, detail = fail
    node = _sid(result.get("node")) or "?"
    if code == "running":
        msg = ("node %s already has a live run. Wait for its task notification, or TaskStop it if "
               "it is stuck." % node)
    elif code == "runs_used":
        msg = ("node %s has used its %d runs (STACK_FANOUT_DYN_NODE_RUNS). Do this part yourself or "
               "revise plan.dag.json." % (node, int(detail)))
    elif code == "deps":
        deps = [d for d in (_sid(x) for x in detail) if d][:4]
        msg = "node %s waits on %s, not ended yet." % (node, ", ".join(deps) or "its dependencies")
    elif code == "exclusive":
        other, tag = detail
        msg = ("node %s and live node %s share the %s lock. Wait for its task notification."
               % (node, _sid(other) or "?", tag if tag in EXCLUSIVE_TAGS else "exclusive"))
    elif code == "conflict":
        msg = ("node %s writes where live node %s works (plan.dag.json w/rd). Wait for its task "
               "notification, or spawn it with isolation \"worktree\"." % (node, _sid(detail) or "?"))
    elif code == "window":
        msg = ("window %d reached after rate limits or failures (AIMD). Wait for a task notification "
               "before spawning more." % int(detail))
    elif code == "budget":
        t = child_type if isinstance(child_type, str) and TYPE_RE.match(child_type) else "agent"
        msg = ("the token budget left after running children's expected use and the %d reserve does "
               "not cover another %s. Wait for children to finish, or do this part yourself."
               % (int(k["reserve_tok"]), t))
    else:
        msg = "static cap %d reached. Wait for a task notification." % int(detail)
    ready = [x for x in (_sid(v) for v in result.get("eligible", ())) if x][:8]
    return "Dynamic fan-out (%s): %s Free slots: %d; ready nodes: %s." % (
        code, msg, int(result.get("free") or 0), ", ".join(ready) or "none")


def log_fields(result):
    """The shadow-log record of a decision: numbers, fixed codes and validated ids only."""
    terms = {key: int(v) for key, v in (result.get("terms") or {}).items()
             if isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)}
    return {"mode": result.get("mode") if result.get("mode") in MODES else "other",
            "kind": result.get("kind") if result.get("kind") in ("spawn", "resume") else "other",
            "allow": bool(result.get("allow")), "would_allow": bool(result.get("would_allow")),
            "cap": int(result.get("cap") or 0), "binding": str(result.get("binding"))[:16],
            "code": result.get("code") if result.get("code") in CODE_TERM else None,
            "planned": bool(result.get("planned")), "node": _sid(result.get("node")),
            "understated": bool(result.get("understated")), "fallback": bool(result.get("fallback")),
            "terms": terms, "n_elig": len(result.get("eligible") or ())}


# ---------------------------------------------------------------- state paths (for the guard)
def _safe(value, default="none"):
    """agent_guard.safe(), copied: a filesystem-safe token."""
    s = re.sub(r"[^A-Za-z0-9_-]", "_", str(value or ""))[:128]
    return s or default


def state_paths(session_dir, caller):
    """{"plan", "nodes", "aimd"} file paths of one orchestrator under <session>/fanout-dyn/."""
    base = os.path.join(session_dir, STATE_SUBDIR, _safe(caller))
    return {"plan": base + ".plan.json", "nodes": base + ".nodes.json", "aimd": base + ".aimd.json"}


# ---------------------------------------------------------------- CLI
def _read_json(path, limit=MODEL_MAX_BYTES):
    try:
        if os.path.getsize(path) > limit:
            return None
        with open(path, "rb") as f:
            return json.loads(f.read().decode("utf-8"))
    except (OSError, ValueError, RecursionError):
        return None


def _check_cmd(args):
    path, types, cap = None, None, 32
    it = iter(args)
    for a in it:
        if a == "--types":
            types = [t for t in re.split(r"[,\s]+", next(it, "")) if t]
        elif a == "--cap":
            cap = int(next(it, "32"))
        elif path is None and not a.startswith("--"):
            path = a
        else:
            return 2
    if path is None:
        return 2
    try:
        with open(path, "rb") as f:
            content = f.read(PLAN_MAX_BYTES + 1)
    except OSError as exc:
        print("cannot read %s (%s)" % (path, type(exc).__name__), file=sys.stderr)
        return 2
    try:
        plan = parse_plan(content, types)
    except PlanError as exc:
        print(plan_reject_text(exc, cap))
        return 1
    print(plan_accept_text(plan))
    return 0


def _report(session_dir):
    folder = os.path.join(session_dir, STATE_SUBDIR)
    out = {"orchestrators": {}, "log": {}}
    try:
        names = sorted(os.listdir(folder))
    except OSError:
        names = []
    for f in names:
        m = re.match(r"^([A-Za-z0-9_-]{1,128})\.(plan|nodes|aimd)\.json\Z", f)
        if not m:
            continue
        o = out["orchestrators"].setdefault(m.group(1), {})
        data = _read_json(os.path.join(folder, f))
        if m.group(2) == "plan" and isinstance(data, dict) and isinstance(data.get("nodes"), list):
            o["plan"] = {"nodes": len(data["nodes"]), "width": data.get("width")}
        elif m.group(2) == "nodes" and isinstance(data, dict):
            st = _norm_nodes(data)
            runs = [r for _, r in _all_runs(st)]
            o["nodes"] = {"runs": len(runs),
                          "ended": sum(1 for r in runs if r.get("t_end") is not None),
                          "unbound": sum(1 for r in runs if r.get("child_id") is None),
                          "understated": st["understated"], "plan_off": st["plan_off"],
                          "breaker": bool(st["breaker"].get("tripped"))}
        elif m.group(2) == "aimd" and isinstance(data, dict):
            o["aimd"] = {"w": data.get("w") if isinstance(data.get("w"), int) else None}
    try:
        with open(os.path.join(session_dir, LOG_NAME), "rb") as f:
            for line in f.read(8 << 20).splitlines():
                try:
                    rec = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(rec, dict):
                    continue
                key = "%s:%s" % ("allow" if rec.get("would_allow") else "would_deny",
                                 str(rec.get("code") or rec.get("binding"))[:16])
                out["log"][key] = out["log"].get(key, 0) + 1
    except OSError:
        pass
    return out


def _report_cmd(args):
    sid, as_json = None, False
    it = iter(args)
    for a in it:
        if a == "--session":
            sid = next(it, None)
        elif a == "--json":
            as_json = True
        else:
            return 2
    if not sid or not SID_RE.match(sid) or ".." in sid:
        return 2
    base = os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state")
    rep = _report(os.path.join(base, "claude-agent-stack", sid))
    if as_json:
        print(json.dumps(rep, indent=1, sort_keys=True))
    else:
        for o, v in sorted(rep["orchestrators"].items()):
            print("%s  plan=%s nodes=%s aimd=%s" % (o, v.get("plan"), v.get("nodes"), v.get("aimd")))
        for key, cnt in sorted(rep["log"].items()):
            print("%-32s %d" % (key, cnt))
    return 0 if (rep["orchestrators"] or rep["log"]) else 1


USAGE = ("usage: stack_fanout.py check PLAN.json [--types a,b,...] [--cap N]\n"
         "       stack_fanout.py report --session SID [--json]")


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    cmd = argv[0] if argv else None
    try:
        rc = _check_cmd(argv[1:]) if cmd == "check" else \
            _report_cmd(argv[1:]) if cmd == "report" else 2
    except ValueError:
        rc = 2
    if rc == 2:
        print(USAGE, file=sys.stderr)
    return rc


if __name__ == "__main__":
    sys.exit(main())
