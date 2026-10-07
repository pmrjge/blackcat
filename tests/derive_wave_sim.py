# /// script
# requires-python = ">=3.11"
# dependencies = ["pandas>=2.2", "numpy>=1.26"]
# ///
"""Held-out check of the replay's barrier simulation (dot-config/dot-claude/hooks/stack_sched.py: cluster_waves,
simulate_window, WAVE_GAP_S): do recorded waves, startup lags and durations reproduce each window's makespan
on sessions the parameters were not fitted on?

Read-only over Claude Code transcripts (--root: <project>/<session>.jsonl and <session>/subagents/agent-*.jsonl,
parsed by tests/derive_thresholds.py) and the stack's delegation ledgers (--state: <session>/delegations.md).
Writes only --out (default .claude-work/agents-sched/wave-sim.md). Point --root and --state at copies, and list only
closed sessions in --sessions: a session still being written changes between runs.

Run:  uv run --script tests/derive_wave_sim.py --root DIR --state DIR [--sessions ID,ID]
          [--replay-usage DIR] [--replay-ledger FILE] [--before OLD_stack_sched.py] [--out FILE]

Definitions
  unit          one subagent segment (a spawn or a resume); dispatch = the ledger's spawn time for a spawn,
                the first API call for a resume; a resume depends on the agent's previous segment.
  group         the units one dispatcher (the ledger parent: an agent id, or "main") started inside one
                human-prompt window (exact prompt timestamps). makespan = first unit start to last unit end.
  message waves the dispatcher's own assistant messages: the Agent/SendMessage calls of one message form one
                wave (tool_use -> "agentId: ..." in its tool_result; SendMessage -> the target's next segment).
                The clustering rule is scored against them (pairwise F1), the simulation is run on both. They are
                not barrier waves: a later message can dispatch before an earlier message's units end (negative
                gaps between message waves), so they are no upper bound on what a rule can reach.
  fit           on the training sessions' multi-unit groups of subagent dispatchers: gap = the GRID value
                with the best pairwise F1 against the message waves (ties: the larger gap); lat = median gap
                between a rule wave's last end and the next wave's first dispatch, kept in [0, 60] s (as the
                replay's own latency estimate); stagger = median gap between consecutive dispatches in a rule wave.
  held-out      leave one session out: each session's groups are simulated with the parameters fitted on
                the others. The main thread is reported apart: BlackCat's children run in the background, so
                its groups are not barrier waves and the barrier model is not expected to hold there.
                Headline: the groups with more than one message wave; a single-wave group only replaces its
                dispatch offsets with j x stagger and never exercises the barrier.
  CI            groups of one (session, dispatcher) share a dispatcher and a fitted parameter set: the share
                within 2% and the median |error| are bootstrapped over those clusters (few clusters: crude).
  minimax       the smallest worst-case |error| over a (lat, stagger) grid for a fixed partition; it bounds
                nothing about other partitions. For the replay windows: the smallest stagger at which some lat
                puts every window within 2%, against the per-session median in-wave gaps.
"""
import argparse, glob, importlib.util, json, math, os, random, re, statistics as st, sys

TESTS = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(TESTS)
sys.path.insert(0, TESTS)
import derive_thresholds as DT  # noqa: E402  (same transcript parser; puts dot-config/dot-claude/hooks on sys.path)
import stack_sched as SS  # noqa: E402

GRID = (5, 10, 15, 20, 30, 45, 60, 90, 120, 180, 300)
LAT_GRID = [float(x) for x in range(0, 121)]
STAGGER_GRID = [x / 2.0 for x in range(0, 41)]
AID_RE = re.compile(r"agentId: ([0-9a-f]{17})")
SEED = 20261003
FIXTURE = os.path.join(TESTS, "fixtures", "sched", "graph-4e2da3ce.json")


# ------------------------------------------------------------------------------------- inputs
def human_prompts(ev):
    """Exact timestamps of the human prompts (derive_thresholds.prompt_windows' filter)."""
    out = []
    for k, e in ev:
        if k == "user" and not e["tr"] and not e["meta"]:
            t = e["text"]
            if t.startswith("<task-notification>") or t.startswith("Base directory for this skill"):
                continue
            out.append(SS._ts(e["ts"]))
    return sorted(out)


def dispatch_calls(path):
    """[(message id, tool, target agent id)] of a transcript's Agent/Task/SendMessage calls, in order."""
    calls, res = [], {}
    for line in open(path, encoding="utf-8", errors="replace"):
        try:
            r = json.loads(line)
        except ValueError:
            continue
        if r.get("type") == "assistant":
            m = r.get("message") or {}
            for b in m.get("content") or []:
                if isinstance(b, dict) and b.get("type") == "tool_use" and b.get("name") in ("Agent", "Task", "SendMessage"):
                    inp = b.get("input") or {}
                    calls.append([m.get("id"), b["name"], inp.get("to") if b["name"] == "SendMessage" else None, b.get("id"),
                                  SS._ts(r["timestamp"])])
        elif r.get("type") == "user":
            c = (r.get("message") or {}).get("content")
            for b in c if isinstance(c, list) else []:
                if isinstance(b, dict) and b.get("type") == "tool_result":
                    mt = AID_RE.search(json.dumps(b.get("content")))
                    if mt:
                        res[b.get("tool_use_id")] = mt.group(1)
    for c in calls:
        if c[1] != "SendMessage":
            c[2] = res.get(c[3])
    return calls


def ledger_parents(path):
    """agent id -> (parent id or "main", local time of day of the spawn)"""
    out, stack = {}, []
    for r in SS.parse_ledger(path):
        stack = stack[:r["depth"]]
        if r["id"]:
            out[r["id"]] = (stack[-1] if stack else "main", r["sod"])
        stack.append(r["id"] or "?")
    return out


def session_groups(sid, seg, ev, files, ledger):
    """Groups of one session (see Definitions), with their message waves."""
    rows = seg[seg.session == sid].to_dict("records")
    led = ledger_parents(ledger)
    t0of = {(r["id"], int(r["seg"])): SS._ts(r["first_ts"]) for r in rows}
    diffs = sorted(((sod - (t0of[(i, 0)] % 86400) + 43200) % 86400 - 43200)
                   for i, (_, sod) in led.items() if sod is not None and (i, 0) in t0of)
    tz = round(diffs[len(diffs) // 2] / 900.0) * 900.0 if diffs else 0.0
    units = {}
    for r in rows:
        aid, k = r["id"], int(r["seg"])
        st0, en = SS._ts(r["first_ts"]), SS._ts(r["last_ts"])
        parent, sod = led.get(aid, ("?", None))
        disp = st0
        if k == 0 and sod is not None:
            delta = ((sod - tz) - (st0 % 86400) + 43200) % 86400 - 43200
            disp = st0 + min(0.0, delta) if delta > -600 else st0
        units["%s#%d" % (aid, k)] = dict(key="%s#%d" % (aid, k), agent=aid, seg=k, dispatch=disp, start=st0, end=en,
                                         parent=parent, deps=["%s#%d" % (aid, k - 1)] if k else [])
    # message waves: the dispatching message of each unit
    segs_of = {}
    for u in units.values():
        segs_of.setdefault(u["agent"], []).append(u)
    for v in segs_of.values():
        v.sort(key=lambda u: u["seg"])
    msg = {}
    for f in files:
        for mid, tool, tgt, _, ts in dispatch_calls(f):
            if not tgt or tgt not in segs_of:
                continue
            if tool == "SendMessage":
                cand = [u for u in segs_of[tgt] if u["seg"] > 0 and u["start"] >= ts - 2 and u["key"] not in msg]
                if cand and cand[0]["start"] - ts <= 120:
                    msg[cand[0]["key"]] = mid
            else:
                msg[segs_of[tgt][0]["key"]] = mid
    hp = human_prompts(ev)
    import bisect
    groups = {}
    for u in units.values():
        wi = max(0, bisect.bisect_right(hp, u["start"]) - 1)
        groups.setdefault((wi, u["parent"]), []).append(u)
    out = []
    for (wi, disp), us in sorted(groups.items()):
        t0 = min(u["start"] for u in us)
        t_org = min(u["dispatch"] for u in us)          # the simulated timeline's 0: the group's first dispatch
        keys = {u["key"] for u in us}
        for u in us:
            u["rel"] = max([0.0] + [units[d]["end"] - t_org for d in u["deps"] if d not in keys and d in units])
        tw = {}
        for u in sorted(us, key=lambda u: u["dispatch"]):
            tw.setdefault(msg.get(u["key"], u["key"]), []).append(u["key"])
        out.append(dict(sid=sid, wi=wi, disp=disp, units={u["key"]: u for u in us}, t0=t0,
                        mk=max(u["end"] for u in us) - t0, truth=sorted(tw.values(), key=lambda w: units[w[0]]["dispatch"])))
    return out


def load(root, state, sessions):
    seg, _, _, mains = DT.load(root)
    sids = sessions or sorted(s for s in mains if os.path.isfile(os.path.join(state, s, "delegations.md")))
    rows = []
    for sid in sids:
        main = glob.glob(os.path.join(root, "*", sid + ".jsonl"))
        files = main + glob.glob(os.path.join(root, "*", sid, "subagents", "agent-*.jsonl"))
        rows += session_groups(sid, seg, mains[sid]["ev"], files, os.path.join(state, sid, "delegations.md"))
    return sids, rows


# ------------------------------------------------------------------------------------- model
def rule_waves(r, gap, deps=True):
    us = r["units"]
    return SS.cluster_waves([(u["dispatch"], k) for k, u in us.items()], gap,
                            deps={k: u["deps"] for k, u in us.items()} if deps else None)


def timeline(r, waves):
    us = r["units"]
    return [[(us[k]["start"] - us[k]["dispatch"], us[k]["end"] - us[k]["start"], us[k]["rel"]) for k in w] for w in waves]


def err_new(r, p, waves=None):
    w = rule_waves(r, p["gap"]) if waves is None else waves
    return (SS.simulate_window([timeline(r, w)], p["lat"], p["stagger"]) - r["mk"]) / r["mk"]


def err_old(r, lat):
    """the replay before this check: 120 s gap clusters, no stagger, no release, measured from the first dispatch"""
    us = r["units"]
    w = SS.cluster_waves([(u["dispatch"], k) for k, u in us.items()], 120.0)
    return (SS.simulate_waves([[(us[k]["start"] - us[k]["dispatch"], us[k]["end"] - us[k]["start"]) for k in x] for x in w], lat)
            - r["mk"]) / r["mk"]


def pairs(waves):
    return {(a, b) for w in waves for i, a in enumerate(sorted(w)) for b in sorted(w)[i + 1:]}


def f1(rows, gap):
    tp = fp = fn = 0
    for r in rows:
        a, b = pairs(rule_waves(r, gap)), pairs(r["truth"])
        tp, fp, fn = tp + len(a & b), fp + len(a - b), fn + len(b - a)
    return 2 * tp / (2 * tp + fp + fn) if tp + fp + fn else 1.0


def barrier(rows):
    return [r for r in rows if r["disp"] != "main" and len(r["units"]) > 1 and r["mk"] > 0]


def fit(rows):
    sub = barrier(rows)
    gap = max(GRID, key=lambda g: (round(f1(sub, g), 3), g))
    lats, stg = [], []
    for r in sub:
        w = rule_waves(r, gap)
        us = r["units"]
        stg += [us[b]["dispatch"] - us[a]["dispatch"] for x in w for a, b in zip(x, x[1:])]
        lats += [x for x in (us[b[0]]["dispatch"] - max(us[k]["end"] for k in a) for a, b in zip(w, w[1:])) if 0 <= x <= 60]
    return dict(gap=float(gap), lat=st.median(lats) if lats else 0.0, stagger=st.median(stg) if stg else 0.0,
                f1=f1(sub, gap), n_lat=len(lats), n_stagger=len(stg))


# ------------------------------------------------------------------------------------- statistics
def wilson(k, n, z=1.96):
    if not n:
        return (float("nan"), float("nan"))
    p = k / n
    c = (p + z * z / (2 * n)) / (1 + z * z / n)
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return (c - h, c + h)


def boot_median(x, B=2000, seed=SEED):
    if not x:
        return (float("nan"), float("nan"))
    rng = random.Random(seed)
    m = sorted(st.median(rng.choices(x, k=len(x))) for _ in range(B))
    return (m[int(0.025 * B)], m[int(0.975 * B) - 1])


def _cluster_resamples(errs, clusters, B, seed):
    by = {}
    for e, c in zip(errs, clusters):
        by.setdefault(c, []).append(abs(e))
    keys, rng = sorted(by), random.Random(seed)
    return [[x for k in rng.choices(keys, k=len(keys)) for x in by[k]] for _ in range(B)]


def cluster_share_ci(errs, clusters, B=2000, seed=SEED):
    """95% bootstrap CI of the share within 2%, resampling whole clusters (crude with few clusters)"""
    s = sorted(sum(x <= 0.02 for x in pick) / len(pick) for pick in _cluster_resamples(errs, clusters, B, seed))
    return s[int(0.025 * B)], s[int(0.975 * B) - 1]


def cluster_median_ci(errs, clusters, B=2000, seed=SEED):
    """95% bootstrap CI of the median |error|, resampling whole clusters (crude with few clusters)"""
    m = sorted(st.median(pick) for pick in _cluster_resamples(errs, clusters, B, seed))
    return m[int(0.025 * B)], m[int(0.975 * B) - 1]


def summary(errs, clusters=None):
    a = [abs(e) for e in errs]
    if not a:
        return "n=0"
    k = sum(x <= 0.02 for x in a)
    if clusters is None:
        (lo, hi), (mlo, mhi), ci, n = wilson(k, len(a)), boot_median(a), "95% CI", "n=%d" % len(a)
    else:
        lo, hi = cluster_share_ci(errs, clusters)
        mlo, mhi = cluster_median_ci(errs, clusters)
        ci, n = "crude 95% CI", "n=%d in %d clusters" % (len(a), len(set(clusters)))
    return "%s; within 2%%: %d (%.0f%%, %s %.0f-%.0f%%); median |error| %.2f%% (%s %.2f-%.2f%%); max %.1f%%" % (
        n, k, 100 * k / len(a), ci, 100 * lo, 100 * hi, 100 * st.median(a), ci, 100 * mlo, 100 * mhi, 100 * max(a))


def minimax(timelines_mk, stagger_max=None):
    """min over (lat, stagger <= stagger_max) of the worst |error|, and the best share within 2%, over [(timelines, makespan)]"""
    best, best_share = (float("inf"), None, None), (-1, None, None)
    for lat in LAT_GRID:
        for sg in (x for x in STAGGER_GRID if stagger_max is None or x <= stagger_max):
            e = [abs(SS.simulate_window(tl, lat, sg) - mk) / mk for tl, mk in timelines_mk]
            if max(e) < best[0]:
                best = (max(e), lat, sg)
            k = sum(x <= 0.02 for x in e)
            if k > best_share[0]:
                best_share = (k, lat, sg)
    return best, best_share


def min_stagger(timelines_mk, tol=0.02):
    """(smallest stagger on the grid at which some lat puts every item within tol, that lat), or None"""
    for sg in STAGGER_GRID:
        for lat in LAT_GRID:
            if all(abs(SS.simulate_window(tl, lat, sg) - mk) / mk <= tol for tl, mk in timelines_mk):
                return sg, lat
    return None


def fmt(e):
    return "%+.2f%%" % (100 * e)


# ------------------------------------------------------------------------------------- report
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=os.path.expanduser("~/.claude/projects"))
    ap.add_argument("--state", default=os.path.expanduser("~/.local/state/claude-agent-stack"))
    ap.add_argument("--sessions", default="", help="comma-separated session ids (default: every one with a ledger)")
    ap.add_argument("--replay-usage", default="", help="folder with the replay's segments.csv and prompts.csv")
    ap.add_argument("--replay-ledger", default="", help="the replay session's delegations.md")
    ap.add_argument("--before", default="", help="a stack_sched.py from before this check, for the before column")
    ap.add_argument("--out", default=os.path.join(REPO, ".claude-work", "agents-sched", "wave-sim.md"))
    a = ap.parse_args()
    sids, rows = load(a.root, a.state, [s for s in a.sessions.split(",") if s])
    o = ["# Barrier simulation, held-out check", "",
         "Generated by tests/derive_wave_sim.py (definitions in its docstring). Sessions: %s." % ", ".join(s[:8] for s in sids), ""]
    full = fit(rows)
    o.append("Fitted on all sessions: gap %.0f s (pairwise F1 against the message waves %.3f), lat %.1f s (n=%d), stagger %.1f s (n=%d)."
             % (full["gap"], full["f1"], full["lat"], full["n_lat"], full["stagger"], full["n_stagger"]))
    o.append("")
    o.append("Pairwise F1 of the rule against the message waves, subagent dispatchers, all sessions: " + ", ".join(
        "%d s %.3f" % (g, f1(barrier(rows), g)) for g in GRID) + ".")
    o.append("")
    o += ["## Leave one session out", "",
          "| held-out session | fitted gap s | lat s | stagger s | F1 held-out | groups | before (120 s, old sim) | after (rule) | after (message waves) |",
          "|---|---|---|---|---|---|---|---|---|"]
    ho_new, ho_old, ho_truth, ho_main, detail, ho_rows, main_cl = [], [], [], [], [], [], []
    for s in sids:
        p = fit([r for r in rows if r["sid"] != s])
        test = barrier([r for r in rows if r["sid"] == s])
        en = [err_new(r, p) for r in test]
        eo = [err_old(r, p["lat"]) for r in test]
        et = [err_new(r, p, r["truth"]) for r in test]
        ho_new += en; ho_old += eo; ho_truth += et; ho_rows += test
        mrows = [r for r in rows if r["sid"] == s and r["disp"] == "main" and len(r["units"]) > 1 and r["mk"] > 0]
        ho_main += [err_new(r, p) for r in mrows]
        main_cl += [(r["sid"], r["disp"]) for r in mrows]
        within = lambda e: "%d/%d within 2%%" % (sum(abs(x) <= 0.02 for x in e), len(e))
        o.append("| %s | %.0f | %.1f | %.1f | %.3f | %d | %s | %s | %s |" % (
            s[:8], p["gap"], p["lat"], p["stagger"], f1(test, p["gap"]), len(test), within(eo), within(en), within(et)))
        for r, x, y, z in zip(test, eo, en, et):
            us = r["units"]
            gaps = [us[b[0]]["dispatch"] - max(us[k]["end"] for k in w) for w, b in zip(r["truth"], r["truth"][1:])]
            detail.append("| %s | %d | %s | %d | %d | %.1f | %s | %s | %s | %s |" % (
                s[:8], r["wi"], r["disp"][:8], len(us), len(r["truth"]), r["mk"] / 60, fmt(x), fmt(y), fmt(z),
                " ".join("%.0f" % g for g in gaps) or "-"))
    cl = [(r["sid"], r["disp"]) for r in ho_rows]
    mw = [i for i, r in enumerate(ho_rows) if len(r["truth"]) > 1]
    pick = lambda e, ix: [e[i] for i in ix]
    o += ["", "Held-out, subagent dispatchers (multi-unit groups). CIs resample (session, dispatcher) clusters.", "",
          "Headline, groups with more than one message wave (the only ones that exercise the barrier):", "",
          "- before: " + summary(pick(ho_old, mw), pick(cl, mw)), "- after, rule waves: " + summary(pick(ho_new, mw), pick(cl, mw)),
          "", "All groups (%d of %d have one message wave: the simulation only replaces their dispatch offsets with j x stagger):"
          % (len(ho_rows) - len(mw), len(ho_rows)), "",
          "- before: " + summary(ho_old, cl), "- after, rule waves: " + summary(ho_new, cl),
          "- after, message waves: " + summary(ho_truth, cl),
          "- main thread (not barrier; reported apart): " + summary(ho_main, main_cl), "",
          "| session | window | dispatcher | units | message waves | makespan min | before | after | after, message waves | gaps between message waves s |",
          "|---|---|---|---|---|---|---|---|---|---|"] + detail
    (mm, lat_mm, sg_mm), (share, lat_sh, sg_sh) = minimax([([timeline(r, r["truth"])], r["mk"]) for r in barrier(rows)])
    o += ["", "Minimax over lat 0-120 s and stagger 0-20 s with the message waves (not barrier waves), all subagent-dispatcher "
          "groups: worst |error| at best %.1f%% (lat %.0f s, stagger %.1f s); at most %d of %d groups within 2%% (lat %.0f s, "
          "stagger %.1f s)." % (100 * mm, lat_mm, sg_mm, share, len(barrier(rows)), lat_sh, sg_sh), ""]
    if a.replay_usage:
        m = SS.load_model("/nonexistent/sched_model.json")
        seg_f, prm_f = os.path.join(a.replay_usage, "segments.csv"), os.path.join(a.replay_usage, "prompts.csv")
        sess = json.load(open(FIXTURE))["session"]
        led = a.replay_ledger or None
        rep = SS.replay(led, seg_f, prm_f, FIXTURE, m, session=sess)
        p = fit([r for r in rows if r["sid"] != sess])
        rho = SS.replay(led, seg_f, prm_f, FIXTURE, m, session=sess, sim=p)
        old = None
        if a.before:
            spec = importlib.util.spec_from_file_location("stack_sched_before", a.before)
            OLD = importlib.util.module_from_spec(spec)
            sys.modules["stack_sched_before"] = OLD
            spec.loader.exec_module(OLD)
            old = {w.i: w for w in OLD.replay(led, seg_f, prm_f, FIXTURE, m, session=sess).windows}
        ho = {w.i: w for w in rho.windows}
        o += ["## Replay windows, session %s (graph fixture)" % sess[:8], "",
              "In-session parameters: lat %.1f s, stagger %.1f s, gap %.0f s. Held-out parameters (fitted on the other sessions): "
              "lat %.1f s, stagger %.1f s, gap %.0f s." % (rep.sim_params["lat"], rep.sim_params["stagger"], rep.sim_params["gap"],
                                                         p["lat"], p["stagger"], p["gap"]), "",
              "| window | units | makespan min | waves before | waves after | before | after, in-session | after, held-out |",
              "|---|---|---|---|---|---|---|---|"]
        for w in rep.windows:
            b = old.get(w.i) if old else None
            o.append("| %d | %d+%d | %.1f | %s | %d | %s | %s | %s |" % (
                w.i, len(w.units), len(w.aux), w.makespan / 60, len(b.waves) if b else "-", len(w.waves),
                fmt(b.sim_err) if b else "-", fmt(w.sim_err), fmt(ho[w.i].sim_err)))
        for name, R in (("before", list(old.values()) if old else []), ("after, in-session", rep.windows),
                        ("after, held-out", rho.windows)):
            if R:
                o.append("")
                o.append("- %s: %s" % (name, summary([w.sim_err for w in R])))
        bw = [w.i for w in rep.windows if any(len(g) > 1 for g in w.sim_in)]
        cnt = lambda R: "%d/%d" % (sum(abs(w.sim_err) <= 0.02 for w in R if w.i in bw), len(bw))
        parts = (["before " + cnt(old.values())] if old else []) + ["in-session " + cnt(rep.windows),
                                                                     "held-out " + cnt(rho.windows)]
        o += ["", "Windows with more than one wave in a timeline (the only ones that exercise the barrier): %s; within 2%%: %s."
              % (", ".join(map(str, bw)) or "none", ", ".join(parts))]
        tm = [(w.sim_in, w.makespan) for w in rep.windows]
        (mm, lat_mm, sg_mm), (share, lat_sh, sg_sh) = minimax(tm)
        cap = max([rep.sim_params["stagger"]] + [fit([r for r in rows if r["sid"] == s])["stagger"] for s in sids])
        need = min_stagger(tm)
        o += ["", "Minimax over lat 0-120 s and stagger 0-20 s on these windows' rule waves: worst |error| at best %.2f%% "
              "(lat %.0f s, stagger %.1f s); at most %d of %d windows within 2%% (lat %.0f s, stagger %.1f s). A pair that "
              "only these windows select is fitted on the windows it is judged on." % (
                  100 * mm, lat_mm, sg_mm, share, len(rep.windows), lat_sh, sg_sh)]
        if need is None:
            o[-1] += " No (lat, stagger) on the grid puts every window within 2%."
        else:
            o[-1] += (" 2%% in every window needs a stagger of at least %.1f s (with lat %.0f s), %s every median in-wave "
                      "gap measured (per session and in this replay: at most %.1f s)." % (
                          need[0], need[1], "above" if need[0] > cap else "within", cap))
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    open(a.out, "w").write("\n".join(o) + "\n")
    print("\n".join(o))


if __name__ == "__main__":
    main()
