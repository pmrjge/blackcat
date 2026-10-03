"""stack_fanout_wire.py - the guard side of the dynamic fan-out cap (stdlib only, Python 3.8+).

agent_guard.py imports this file only while STACK_FANOUT_DYN is shadow (the default) or enforce and
a cheap pre-gate passes, so `off` and every call of a non-in-scope caller cost the hook no import. Every function takes `g`, a
live view of agent_guard's globals (its helpers, locks and constants), and never raises: any failure
is the static decision (R3). The decision core is stack_fanout.py (pure: no env, no file on its own).

Dynamic fan-out plan D1-D6, as wired here:
  scope     stack_fanout.in_scope: a subagent whose type is in STACK_FANOUT_DYN_TYPES (default
            orchestrator) with a static cap > 0; never the main thread or BlackCat (R2).
  decision  dyn_spawn / dyn_resume run inside the guard's 'fanout' mutex after its session (K_sess),
            fan-out and copy checks allowed the call, so they only refuse what static allows (R1).
            shadow: computed and logged, never refused; enforce: the terms in
            STACK_FANOUT_DYN_ENFORCE refuse with stack_fanout.deny_text. K_sess stays the guard's
            (STACK_FANOUT_SESSION); here it is only a reported cap term.
  plan      dyn_capture: the in-scope agent's own Write of ./.claude-work/<job>/plan.dag.json, seen by
            the `budget` PreToolUse hook; tool_input.content is validated (stack_fanout.parse_plan
            against the caller's POLICY row; the file on disk is never read) and kept normalized in
            <session>/fanout-dyn/<agent>.plan.json. The Write gets "plan accepted ..." or "plan
            rejected ...; static cap N applies" as additionalContext; an Edit keeps the old copy.
  runs      <agent>.nodes.json, written under 'fanout': recorded when a spawn is allowed (tid = the
            lease name), child bound at PostToolUse(Agent) (dyn_bind_child, inside the guard's own
            mutex block), ended at SubagentStop / TaskStop / StopFailure or a done foreground call
            (dyn_child_end), removed by on_agent's rollback() and on PostToolUseFailure /
            PermissionDenied (dyn_remove_run). A run whose lease is gone and whose child is unbound
            is aborted anyway (D1), so a removal lost to a lock timeout frees its node all the same.
  AIMD      <agent>.aimd.json: + alpha on a healthy finish; beta cuts on StopFailure rate_limit,
            overloaded, server_error, unknown and on a PostToolUseFailure carrying Claude Code's
            concurrency refusal (text unverified, open question 0(e)); one line per change in
            <session>/fanout-dyn-events.jsonl.
  logs      fanout-dyn.jsonl (decisions) and fanout-dyn-events.jsonl: numbers, fixed codes and
            validated ids only, 0600, no more lines past LOG_MAX_BYTES.
  budget    glob-overlap work is capped at CONFLICT_S per pass (the module's 0.2 s deadline, scaled
            through its injectable clock); past it the conflict term is skipped.
"""
import json
import os
import re
import time

LOG_MAX_BYTES = 4 << 20
EVENTS_LOG = "fanout-dyn-events.jsonl"
PLAN_FILE = "plan.dag.json"
CONFLICT_S = 0.02
ERROR_RE = re.compile(r"^[a-z_]{1,32}\Z")
ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}\Z")      # LIMITS_ID_RE, anchored with \Z
EXC_RE = re.compile(r"^[A-Za-z]{1,40}\Z")
WHY_CODES = ("planned", "no_plan", "no_label", "unknown_node", "type_mismatch")


def knobs(g):
    """(stack_fanout module, knobs) while STACK_FANOUT_DYN is shadow or enforce, else None."""
    if not g.policy_on():
        return None
    mod = g.fanout_dyn_module()
    if mod is None:
        return None
    k, warnings = mod.parse_knobs(os.environ)
    for w in warnings:
        g.warn_once("fanout-dyn: " + w)
    return None if k.get("mode") == "off" else (mod, k)


def clock(mod):
    """The module's deadline clock, scaled so its CONFLICT_BUDGET_S means CONFLICT_S here."""
    scale = max(1.0, float(mod.CONFLICT_BUDGET_S) / CONFLICT_S)
    return lambda: time.monotonic() * scale


def num(x):
    """x rounded to 3 places when it is a finite float, else None (log fields)."""
    return round(x, 3) if isinstance(x, float) and x == x and abs(x) != float("inf") else None


def valid_id(g, aid):
    return aid if isinstance(aid, str) and ID_RE.match(aid) else "invalid"


def valid_type(g, t):
    t = g.norm(t)
    return t if t in g.AGENTS or t in g.COPY_BASE else ("other" if t else None)


def append(g, d, name, rec):
    """One log line (the guard's append_jsonl: 0600), none past LOG_MAX_BYTES. Never raises."""
    try:
        path = os.path.join(d, name)
        try:
            if os.path.getsize(path) >= LOG_MAX_BYTES:
                return
        except FileNotFoundError:
            pass
        g.append_jsonl(path, rec)
    except (OSError, TypeError, ValueError) as exc:
        g.warn_once("%s not written (%s)" % (name, type(exc).__name__))


def log_decision(g, d, mod, result, who, who_type, child, **extra):
    """fanout-dyn.jsonl: one decision (stack_fanout.log_fields) plus caller-validated numbers and
    fixed codes."""
    rec = {"v": 1, "ts": round(time.time(), 3), "agent_id": valid_id(g, who),
           "agent_type": valid_type(g, who_type), "child": valid_type(g, child)}
    rec.update(mod.log_fields(result))
    err = result.get("error")
    if isinstance(err, str) and EXC_RE.match(err):
        rec["error"] = err
    rec.update(extra)
    append(g, d, mod.LOG_NAME, rec)


def stored_plan(g, mod, paths, caller_type):
    """The stored plan, validated again (cheap), or None."""
    raw = g.read_json(paths["plan"])
    if raw is None:
        return None
    try:
        return mod.parse_plan(raw, g.spawn_row(caller_type, False))
    except mod.PlanError:
        return None


def runs_of(st):
    """Every run dict of a node state (tolerant of a malformed file)."""
    out = []
    runs = st.get("runs") if isinstance(st, dict) else None
    for lst in (runs.values() if isinstance(runs, dict) else ()):
        out += [r for r in (lst if isinstance(lst, list) else ()) if isinstance(r, dict)]
    unpl = st.get("unplanned") if isinstance(st, dict) else None
    out += [r for r in (unpl if isinstance(unpl, list) else ()) if isinstance(r, dict)]
    return out


def children(reg, caller):
    """{agent id: record} of the caller's live background children (bg, not stopped, idle ones
    included). A foreground child is live through its lease; its registry parent is written only
    when it is done."""
    return {aid: rec for aid, rec in reg.items()
            if isinstance(rec, dict) and rec.get("parent") == caller and rec.get("bg")
            and not rec.get("stopped")}


def model_of(g, mod, ev):
    """The session's copy of the sched model (snapshots/<sid>.sched_model.json), or None (the
    module's built-ins)."""
    sid = ev.get("session_id")
    if not isinstance(sid, str) or not ID_RE.match(sid):
        return None
    return mod.load_model(os.path.join(g.state_root(), "limits", "snapshots",
                                       sid + ".sched_model.json"))


def budget(g, d, ev, mod):
    """(B_rem or None when unknown, hard.prompt, budget.json state or {}): this session's limits and
    the last saved token counts (read without the budget lock: an estimate)."""
    hp, hs = g.budget_caps(g.session_limits(ev, d))
    st = g.read_json(os.path.join(d, g.BUDGET_STATE)) or {}
    if not st:
        return None, hp, {}
    total = int(st.get("total") or 0)
    used = total - int(st.get("prompt_base") or 0)
    return mod.budget_remaining(hp, hs, total, used), hp, st


def inputs(g, d, ev, mod, kids, leases, model):
    """(B_rem, Commit, delay ratio) for the caller's live children: registered ones with their
    current run's seg from budget.json, lease-only ones (foreground, starting, resume reservations)
    at seg 0 (expected to use their whole c_med)."""
    b_rem, _hp, st = budget(g, d, ev, mod)
    files = g.transcript_files(ev)
    fst_all = st.get("files") if isinstance(st.get("files"), dict) else {}
    commit_kids, delay_kids = [], []
    for aid, rec in kids.items():
        seg, calls = 0, 0
        if files:
            fst = fst_all.get(g.subagent_file(files, aid)) or {}
            if isinstance(fst, dict) and fst.get("seg_run") == rec.get("started"):
                seg, calls = int(fst.get("seg") or 0), int(fst.get("seg_calls") or 0)
        t = g.norm(rec.get("type"))
        commit_kids.append((t, seg))
        started = rec.get("started") or rec.get("spawned")
        if isinstance(started, (int, float)) and not isinstance(started, bool):
            delay_kids.append((t, started, calls))
    commit_kids += [(g.norm(rec.get("type")), 0) for _, _, rec in leases]
    try:
        commit = mod.commit_tokens(commit_kids, model)
    except (ValueError, TypeError, KeyError):
        commit, b_rem = 0.0, None                   # unknown model row: budget unknown (K_B = inf)
    return b_rem, commit, mod.delay_ratio(delay_kids, time.time(), model)


def dyn_spawn(g, d, ev, caller, caller_type, child, limit, n, now, reg, tid, sess):
    """Inside the 'fanout' mutex, after the static checks allowed this spawn: the dynamic decision.
    Its deny reason in enforce mode, else None; records the run of an allowed spawn. Any failure:
    None (the static decision)."""
    dk = knobs(g)
    if dk is None:
        return None
    mod, k = dk
    try:
        if n is None or not mod.in_scope(caller, caller_type, limit, k):
            return None
        return _spawn(g, d, ev, mod, k, caller, caller_type, child, limit, n, now, reg, tid, sess)
    except Exception as exc:  # noqa: BLE001 - R3: the static decision
        g.warn_once("fanout-dyn: spawn decision failed (%s); static decision" % type(exc).__name__)
        return None


def _spawn(g, d, ev, mod, k, caller, caller_type, child, limit, n, now, reg, tid, sess):
    ti = g.tool_input(ev)
    paths = mod.state_paths(d, caller)
    plan = stored_plan(g, mod, paths, caller_type)
    leases = g.live_leases(d, now, caller)
    live_tids = {lid for _, lid, _ in leases}
    kids = children(reg, caller)
    nodes = mod.compact(mod.nodes_for_plan(g.read_json(paths["nodes"]), plan), live_tids, kids)
    node_id, why_node = mod.node_of(plan, ti.get("description"), child)
    model = model_of(g, mod, ev)
    b_rem, commit, delay = inputs(g, d, ev, mod, kids, leases, model)
    k_sess = sess["maxc"] - sess["n"] if sess.get("maxc") is not None else None
    iso = str(ti.get("isolation") or "").strip().lower() or None
    res = mod.dyn_decision(k, "spawn", caller, caller_type, limit, n, child, plan=plan,
                           nodes=nodes, node_id=node_id, isolation=iso, live_tids=live_tids,
                           live_children=set(kids), b_rem=b_rem, commit=commit, model=model,
                           aimd=g.read_json(paths["aimd"]), k_sess=k_sess, clock=clock(mod))
    if res["allow"]:
        nodes = mod.record_spawn(nodes, node_id if res.get("planned") else None,
                                 g.safe(tid) if tid else None, child, now, iso=iso == "worktree")
        nodes = mod.breaker_note_child(nodes)
        if res.get("understated"):
            nodes = mod.note_understated(nodes)
        nodes = mod.mark_ready(nodes, res.get("eligible") or (), now)
    else:
        nodes = mod.breaker_note_denial(nodes, now, k)
    g.write_json_atomic(paths["nodes"], nodes)
    log_decision(g, d, mod, res, caller, caller_type, child, n=int(n),
                 why=why_node if why_node in WHY_CODES else "other", delay=num(delay))
    return None if res["allow"] else res["reason"]


def dyn_resume(g, d, ev, owner, owner_type, ttype, limit, n, now, reg, sess):
    """Inside the 'fanout' mutex, after the static checks allowed this resume: the dynamic decision
    without plan terms. Deny reason in enforce mode, else None."""
    dk = knobs(g)
    if dk is None:
        return None
    mod, k = dk
    try:
        if n is None or not mod.in_scope(owner, owner_type, limit, k):
            return None
        paths = mod.state_paths(d, owner)
        nodes = g.read_json(paths["nodes"])
        leases = g.live_leases(d, now, owner)
        kids = children(reg, owner)
        model = model_of(g, mod, ev)
        b_rem, commit, delay = inputs(g, d, ev, mod, kids, leases, model)
        k_sess = sess["maxc"] - sess["n"] if sess.get("maxc") is not None else None
        res = mod.dyn_decision(k, "resume", owner, owner_type, limit, n, ttype, nodes=nodes,
                               live_tids={lid for _, lid, _ in leases}, live_children=set(kids),
                               b_rem=b_rem, commit=commit, model=model,
                               aimd=g.read_json(paths["aimd"]), k_sess=k_sess, clock=clock(mod))
        if not res["allow"]:
            g.write_json_atomic(paths["nodes"], mod.breaker_note_denial(nodes, now, k))
        log_decision(g, d, mod, res, owner, owner_type, ttype, n=int(n), why="resume",
                     delay=num(delay))
        return None if res["allow"] else res["reason"]
    except Exception as exc:  # noqa: BLE001 - R3: the static decision
        g.warn_once("fanout-dyn: resume decision failed (%s); static decision" % type(exc).__name__)
        return None


def dyn_remove_run(g, d, caller, tid):
    """Drop the node run of spawn lease `tid`: its node is free again. True when one was removed.
    A lock timeout leaves an aborted run, which frees the node all the same (D1)."""
    try:
        dk = knobs(g)
        if dk is None or not tid:
            return False
        mod = dk[0]
        path = mod.state_paths(d, caller)["nodes"]
        if not os.path.exists(path):
            return False
        with g.mutex(d, "fanout"):
            st, found = mod.remove_run(g.read_json(path), g.safe(tid))
            if found:
                g.write_json_atomic(path, st)
        return found
    except Exception as exc:  # noqa: BLE001 - bookkeeping only
        g.warn_once("fanout-dyn: run not removed (%s)" % type(exc).__name__)
        return False


def dyn_bind_child(g, d, caller, tid, child_id):
    """PostToolUse(Agent), while on_agent_done holds 'fanout': bind the child to its run before the
    lease goes, so no count sees the run neither live nor bound."""
    try:
        dk = knobs(g)
        if dk is None or not tid:
            return
        mod = dk[0]
        path = mod.state_paths(d, caller)["nodes"]
        if not os.path.exists(path):
            return
        st, found = mod.bind_child(g.read_json(path), g.safe(tid), child_id)
        if found:
            g.write_json_atomic(path, st)
    except Exception as exc:  # noqa: BLE001 - bookkeeping only
        g.warn_once("fanout-dyn: child not bound (%s)" % type(exc).__name__)


def soft_hit(g, d, aid, run):
    """True when limit-hits.jsonl records a soft_agent hit for this run of `aid` (last 256 KiB)."""
    try:
        with open(os.path.join(d, g.LIMIT_HITS), "rb") as f:
            f.seek(0, os.SEEK_END)
            f.seek(max(0, f.tell() - (256 << 10)))
            data = f.read()
    except OSError:
        return False
    for line in data.splitlines():
        if b'"soft_agent"' not in line:
            continue
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        if isinstance(rec, dict) and rec.get("kind") == "soft_agent" and rec.get("agent_id") == aid \
                and (run is None or rec.get("run") == run):
            return True
    return False


def dyn_child_end(g, d, ev, child_id, kind=None):
    """A child of an in-scope agent ended: record the end of its run, once, and update the parent's
    AIMD window. kind: finish (SubagentStop, a completed foreground call: + alpha when healthy) |
    stop_failure (the error's cut) | task_stop | other (no change); None = from the event."""
    try:
        dk = knobs(g)
        if dk is None or not child_id:
            return
        mod, k = dk
        ev = ev or {}
        rec = g.reg_get(d, child_id) or {}
        parent, ptype = rec.get("parent"), g.norm(rec.get("parent_type"))
        limit = g.fanout_limit(parent, ptype)[0] if parent else 0
        if not parent or not mod.in_scope(parent, ptype, limit, k):
            return
        paths = mod.state_paths(d, parent)
        if not os.path.exists(paths["nodes"]):
            return
        event = ev.get("hook_event_name")
        error = ev.get("error") if event == "StopFailure" else None
        error = error if isinstance(error, str) and ERROR_RE.match(error) else (
            "other" if error is not None else None)
        if kind is None:
            kind = "finish" if event == "SubagentStop" else \
                "stop_failure" if event == "StopFailure" else "task_stop"
        healthy = False
        if kind == "finish":
            model = model_of(g, mod, ev)
            started = rec.get("started") or rec.get("spawned")
            dur = time.time() - started if isinstance(started, (int, float)) else None
            try:
                wall_hi = mod.cost_model(model, g.norm(rec.get("type")))["wall_hi"]
            except (ValueError, TypeError, KeyError):
                wall_hi = None
            b_rem, hp, _ = budget(g, d, ev, mod)
            healthy = mod.finish_healthy(True, dur, wall_hi,
                                         soft_hit(g, d, child_id, rec.get("started")), b_rem, hp)
        now = time.time()
        with g.mutex(d, "fanout"):
            st = g.read_json(paths["nodes"])
            run_key = "%s@%s" % (child_id, rec.get("started"))   # a resumed child is a new run
            mine = [r for r in runs_of(st) if r.get("child_id") == child_id]
            if not mine:
                return                                  # not a run of this agent
            if any(r.get("t_end") is None for r in mine):
                st, _ = mod.end_run(st, child_id, now,
                                    kind if kind != "stop_failure" else "sf_" + (error or "other"))
                g.write_json_atomic(paths["nodes"], st)
            if kind not in ("finish", "stop_failure"):
                return
            cur = g.read_json(paths["aimd"])
            seen = [x for x in ((cur or {}).get("seen") or []) if isinstance(x, str)]
            if run_key in seen:
                return                                  # this run already counted
            aimd, action = mod.aimd_update(cur, kind, now, limit, k, healthy=healthy, error=error)
            aimd["seen"] = (seen + [run_key])[-64:]
            g.write_json_atomic(paths["aimd"], aimd)
        append(g, d, EVENTS_LOG, {
            "v": 1, "ts": round(now, 3), "event": kind, "agent_id": valid_id(g, parent),
            "child": valid_type(g, rec.get("type")), "error": error, "healthy": bool(healthy),
            "action": action, "w": int(aimd.get("w") or 0)})
    except Exception as exc:  # noqa: BLE001 - bookkeeping only
        g.warn_once("fanout-dyn: child end not recorded (%s)" % type(exc).__name__)


def dyn_spawn_failed(g, d, ev, caller, tid):
    """PostToolUseFailure / PermissionDenied of an Agent call: remove its run; a failure carrying
    Claude Code's concurrency refusal also cuts the caller's AIMD window."""
    dyn_remove_run(g, d, caller, tid)
    try:
        dk = knobs(g)
        if dk is None or ev.get("hook_event_name") != "PostToolUseFailure":
            return
        mod, k = dk
        if mod.CONCURRENCY_REFUSAL_HINT.lower() not in str(ev.get("error") or "")[:4096].lower():
            return
        ctype = g.norm(ev.get("agent_type"))
        limit = g.fanout_limit(caller, ctype)[0]
        if not mod.in_scope(caller, ctype, limit, k):
            return
        path = mod.state_paths(d, caller)["aimd"]
        now = time.time()
        with g.mutex(d, "fanout"):
            aimd, action = mod.aimd_update(g.read_json(path), "refusal", now, limit, k)
            if action == "cut":
                g.write_json_atomic(path, aimd)
        append(g, d, EVENTS_LOG, {"v": 1, "ts": round(now, 3), "event": "refusal",
                                  "agent_id": valid_id(g, caller), "action": action,
                                  "w": int(aimd.get("w") or 0)})
    except Exception as exc:  # noqa: BLE001 - bookkeeping only
        g.warn_once("fanout-dyn: refusal not recorded (%s)" % type(exc).__name__)


def dyn_capture(g, ev, d):
    """`budget` PreToolUse: an in-scope agent's Write of .claude-work/<job>/plan.dag.json. Returns
    the additionalContext ("plan accepted ..." / "plan rejected ...; static cap N applies" / the
    Edit note) or None. The plan comes from tool_input.content only."""
    tool = g.canonical_tool(ev.get("tool_name"))
    if tool not in ("Write", "Edit", "MultiEdit"):
        return None
    ti = ev.get("tool_input") if isinstance(ev.get("tool_input"), dict) else {}
    fp = ti.get("file_path")
    if not isinstance(fp, str) or not fp.endswith(PLAN_FILE):
        return None
    import posixpath
    p = posixpath.normpath(fp.replace("\\", "/"))
    if posixpath.basename(p) != PLAN_FILE or \
            posixpath.basename(posixpath.dirname(posixpath.dirname(p))) != ".claude-work":
        return None
    aid = ev.get("agent_id")
    dk = knobs(g)
    if dk is None or not aid:
        return None
    mod, k = dk
    atype = g.norm(ev.get("agent_type")) or g.norm((g.reg_get(d, aid) or {}).get("type"))
    limit = g.fanout_limit(aid, atype)[0]
    if not mod.in_scope(aid, atype, limit, k):
        return None
    if tool != "Write":
        return ("plan.dag.json not captured: an Edit keeps the previous plan; rewrite "
                "plan.dag.json with Write.")
    try:
        plan = mod.parse_plan(ti.get("content") if isinstance(ti.get("content"), str) else None,
                              g.spawn_row(atype, False))
    except mod.PlanError as exc:
        return mod.plan_reject_text(exc, limit)
    g.write_json_atomic(mod.state_paths(d, aid)["plan"], plan)
    return mod.plan_accept_text(plan)
