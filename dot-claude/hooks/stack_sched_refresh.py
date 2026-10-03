# /// script
# requires-python = ">=3.9"
# dependencies = ["pandas>=2.2", "numpy>=1.26"]
# ///
"""stack_sched_refresh.py - refits the scheduler's cost model from the usage collector's rows.

Run by stack_usage.py at a safe boundary only (the session's collector exiting: SessionEnd, the
Claude Code process gone, or idle), through `uv run --offline --script` (skipped when uv or a warm
cache is missing), or by hand: `stack_usage.py refresh [--online] [--force]`.

  uv run --script stack_sched_refresh.py [--usage DIR] [--out FILE] [--shipped FILE] [--agents DIR]
                                         [--guard FILE] [--step 1.5] [--B 2000] [--dry-run]

Model: target = the shipped model (sched_model.json beside this file, fitted on the stack's own
transcripts) combined with fit() (tests/derive_sched_model.py, installed beside this file) on every
complete segment row in usage/runs*.csv and runs2*.csv (v2 wins per key; empty cells are skipped, never
imputed; src and stack_commit travel with each row) whose session the shipped model did not already use:
  values    n-weighted mean per type and pool: turns and sec_per_call by healthy segments (n_seg),
            ctx a, b and static_cc by healthy first segments (n_first). New rows count only once
            fit() gives the type a value (its own data or its pool's are gated: >= 5 healthy
            segments from >= 3 agents); until then the shipped values and counts stand
            (evidence.n_seg_seen shows what is waiting)
  counts    n_seg, n_agents, n_first summed; status "supported" iff n_seg >= 5 and n_agents >= 3
            (derive_sched_model.MIN_SEG / MIN_AGENTS), else "provisional"
  bands     per quantity, the log half-widths of both bands combined as for a weighted mean,
            h = sqrt((w h_ship)^2 + ((1 - w) h_new)^2), w = n_ship / (n_ship + n_new), around the
            combined med (without a new band, h_new = h_ship sqrt(n_ship / n_new), the same spread):
            a band narrows as n grows; method "combined"
Bounded step: every value (turns S/M/L, ctx a/b, static_cc, sec_per_call, band lo/hi) moves at most
x STEP (default 1.5, STACK_SCHED_REFRESH_STEP) per refresh from the model in force (the active file
when it was refreshed from the same shipped model, else the shipped one); repeated refreshes
converge on the target. The output keeps the evidence per type (`evidence`) and a `refresh` record.
Soft limits come from the session's limits snapshot, else the seed (stack_limits_seed.json), else
agent_guard.py. It reads no live.json and writes only the candidate model, the next session's input
(the scheduler reads the copy its own session's snapshot made at SessionStart, U4).
It never writes limits, thresholds, maxTurns, prompts or agent files: only --out, atomically.
"""
import argparse
import copy
import datetime as dt
import json
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
# installed: derive_sched_model.py and derive_thresholds.py beside this file; in the repo: tests/
sys.path[:0] = [HERE, os.path.join(os.path.dirname(os.path.dirname(HERE)), "tests")]

import pandas as pd  # noqa: E402

import derive_sched_model as D  # noqa: E402
import stack_limits as L  # noqa: E402
import stack_usage as U  # noqa: E402

STEP_DEFAULT = 1.5
TURN_VALUES = (("turns", "S"), ("turns", "M"), ("turns", "L"), ("sec_per_call", "p50"), ("sec_per_call", "p90"))
FIRST_VALUES = (("ctx", "a"), ("ctx", "b"), ("static_cc", None))
BAND_QTY = (("turns", "n_seg"), ("sec_per_call", "n_seg"), ("ctx", "n_first"))


def now_iso():
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _get(d, k, sub):
    v = d.get(k)
    if sub is not None:
        v = v.get(sub) if isinstance(v, dict) else None
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) else None


def _set(d, k, sub, v):
    if sub is None:
        d[k] = v
    else:
        d.setdefault(k, {})[sub] = v


def frame(rows, skip_sessions=()):
    """runs.csv rows (complete, with API calls, sessions not in skip_sessions) as fit()'s segment table."""
    recs = []
    for (s, aid, seg), r in rows.items():
        if s in skip_sessions or r.get("status") != "complete" or r.get("is_main") == "1":
            continue                                  # main-thread and session rows are no agent segments
        try:
            n = int(r["api_calls"])
            f0, f1 = float(r["first_ts"]), float(r["last_ts"])
        except (KeyError, TypeError, ValueError):
            continue
        if n <= 0:
            continue
        num = lambda k: float(r[k]) if r.get(k) not in (None, "") else float("nan")
        recs.append(dict(session=s, id=aid, type=r["type"], seg=int(seg), api_calls=n, ctx=num("ctx"),
                         first_cc=num("first_cc"), first_cr=num("first_cr"), prev_peak=num("prev_peak"),
                         gap_s=num("gap_s"), cache_creation_input_tokens=num("cache_creation"),
                         first_ts=U.iso(f0), last_ts=U.iso(f1), wall_s=max(0.0, f1 - f0),
                         compactions=int(float(r.get("compacted") or 0)),
                         turn_limit=bool(int(float(r.get("turn_limited") or 0))),
                         after_limit=bool(int(float(r.get("after_limit") or 0))), open=False,
                         src=r.get("src") or "", stack_commit=r.get("stack_commit") or ""))
    return pd.DataFrame(recs)


def soft_limits(guard, sid=None):
    """{type: soft limit or None}: the session snapshot's soft.agent.* values (a session's limits are
    fixed at its start, U4), else the seed, else the AST read of agent_guard.py (D.soft_limits_auto)."""
    sid = sid or snapshot_sid()
    if sid:
        try:
            doc, state = L.read_snapshot(sid)
            if state == "ok":
                pre = "soft.agent."
                vals = {v[len(pre):]: x for v, x in doc["values"].items() if v.startswith(pre)}
                if vals:
                    return vals
        except (ValueError, OSError):
            pass
    try:
        return D.soft_limits_auto(guard, L.SEED_PATH if os.path.exists(L.SEED_PATH) else None)
    except (OSError, SyntaxError, SystemExit):         # no seed and no guard: types without a soft limit
        return {}


def snapshot_sid():
    """The session whose snapshot applies: STACK_LIMITS_SNAPSHOT (a path), else CLAUDE_SESSION_ID."""
    snap = os.environ.get("STACK_LIMITS_SNAPSHOT")
    if snap:
        b = os.path.basename(snap)
        return b[:-len(".json")] if b.endswith(".json") else b
    return os.environ.get("CLAUDE_SESSION_ID") or None


def usable(n):
    """(n_seg, n_first) of a new-fit entry that its values can stand for: 0 where the fit gave no
    value (neither the type nor its pool had enough new data), so such rows are not counted yet."""
    if not n:
        return 0, 0
    return ((n.get("n_seg") or 0) if _get(n, "turns", "M") is not None else 0,
            (n.get("n_first") or 0) if _get(n, "ctx", "a") is not None else 0)


def combine_entry(s, n):
    """One type or pool: shipped entry s, new-fit entry n (None = no new data)."""
    out = copy.deepcopy(s)
    nn, fn = usable(n)
    if not nn and not fn:
        return out
    ns, fs = s.get("n_seg") or 0, s.get("n_first") or 0
    for keys, ws, wn in ((TURN_VALUES, ns, nn), (FIRST_VALUES, fs, fn)):
        for k, sub in keys:
            a, b = _get(s, k, sub), _get(n, k, sub)
            if b is None or wn == 0:
                continue
            v = b if a is None or ws == 0 else (ws * a + wn * b) / (ws + wn)
            _set(out, k, sub, v)
    out["n_seg"], out["n_first"] = ns + nn, fs + fn
    if nn:
        out["n_agents"] = (s.get("n_agents") or 0) + (n.get("n_agents") or 0)
    bs = s.get("band") if isinstance(s.get("band"), dict) else None
    bn = n.get("band") if isinstance(n.get("band"), dict) else None
    if bs is None and bn is None:
        return out
    band = copy.deepcopy(bs or bn)
    for q, w_s, w_n in (("turns", ns, nn), ("sec_per_call", ns, nn), ("ctx", fs, fn)):
        qs, qn = (bs or {}).get(q), (bn or {}).get(q)
        if w_n == 0:
            continue
        med = 1.0 if q == "ctx" else (_get(out, "turns", "M") if q == "turns" else _get(out, "sec_per_call", "p50"))
        if med is None:
            continue
        res = {"med": med}
        for side in ("lo", "hi"):
            hs = _halfwidth(qs, side) if isinstance(qs, dict) and w_s else None
            hn = _halfwidth(qn, side) if isinstance(qn, dict) else None
            if hn is None and hs is not None:
                hn = hs * math.sqrt(w_s / w_n)          # no new band: the shipped spread, n_new values
            if hn is None and hs is None:
                continue
            if hs is None:
                h = hn
            else:
                w = w_s / (w_s + w_n)
                h = math.hypot(w * hs, (1 - w) * hn)
            res[side] = med * math.exp(-h if side == "lo" else h)
        band[q] = res
    band["method"] = "combined"
    band["n_ref"] = _get(out, "turns", "M") or band.get("n_ref")
    out["band"] = band
    return out


def _halfwidth(q, side):
    """log(hi/med) or log(med/lo) of a band quantity; None when not computable."""
    try:
        med, x = float(q["med"]), float(q[side])
    except (KeyError, TypeError, ValueError):
        return None
    if med <= 0 or x <= 0:
        return None
    return abs(math.log(x / med))


def combine(shipped, new, collected_sessions, n_rows):
    """The target model (see the module docstring)."""
    J = copy.deepcopy(shipped)
    for group in ("types", "pools"):
        src, add = shipped.get(group) or {}, (new or {}).get(group) or {}
        J[group] = {}
        for t in sorted(set(src) | set(add)):
            if t in src:
                J[group][t] = combine_entry(src[t], add.get(t))
            else:
                J[group][t] = copy.deepcopy(add[t])
    for t, v in J["types"].items():
        v["status"] = "supported" if (v.get("n_seg") or 0) >= D.MIN_SEG and (v.get("n_agents") or 0) >= D.MIN_AGENTS \
            else "provisional"
        if v["status"] == "supported" and str(v.get("source") or "").startswith("pool:"):
            v["source"] = "own"
        nt = ((new or {}).get("types") or {}).get(t) or {}
        st = (shipped.get("types") or {}).get(t) or {}
        for k in ("maxTurns", "soft_limit"):          # current frontmatter / SOFT_LIMITS, read by fit()
            if k in nt:
                v[k] = nt[k]
        nn, fn = usable(nt)
        v["evidence"] = {"n_seg_shipped": st.get("n_seg") or 0, "n_seg_collected": nn,
                         "n_agents_collected": (nt.get("n_agents") or 0) if nn else 0, "n_first_collected": fn,
                         "n_seg_seen": nt.get("n_seg") or 0}
    if new:
        J["stack_hash"] = new.get("stack_hash") or J.get("stack_hash")
        J["data_until"] = max(filter(None, [shipped.get("data_until"), new.get("data_until")]), default=None)
    J["sessions"] = sorted(set(shipped.get("sessions") or []) | set(collected_sessions))
    J["refresh"] = {"base_generated": shipped.get("generated"), "rows": n_rows,
                    "sessions_collected": len(collected_sessions)}
    return J


def bounded(prev, target, step):
    """target with every value moved at most x step from prev (same type/pool in prev)."""
    out = copy.deepcopy(target)
    lim = lambda p, x: x if p is None or p <= 0 or x is None else min(max(x, p / step), p * step)
    for group in ("types", "pools"):
        for t, v in (out.get(group) or {}).items():
            p = ((prev.get(group) or {}).get(t)) or {}
            for k, sub in TURN_VALUES + FIRST_VALUES:
                x = _get(v, k, sub)
                if x is not None:
                    _set(v, k, sub, lim(_get(p, k, sub), x))
            b, pb = v.get("band"), p.get("band") if isinstance(p.get("band"), dict) else {}
            if isinstance(b, dict):
                for q, _cnt in BAND_QTY:
                    if not isinstance(b.get(q), dict):
                        continue
                    for side in ("lo", "hi"):
                        x = _get(b[q], side, None) if side in b[q] else None
                        if x is not None:
                            b[q][side] = lim(_get(pb.get(q) or {}, side, None), x)
                    # med follows the stepped point value; lo <= med <= hi
                    med = 1.0 if q == "ctx" else (_get(v, "turns", "M") if q == "turns"
                                                  else _get(v, "sec_per_call", "p50"))
                    if med is not None:
                        b[q]["med"] = med
                        b[q]["lo"] = min(b[q].get("lo", med), med)
                        b[q]["hi"] = max(b[q].get("hi", med), med)
                if _get(v, "turns", "M") is not None:
                    b["n_ref"] = _get(v, "turns", "M")
    return out


def rounded(J):
    r1 = lambda x: None if x is None else round(float(x), 1)
    for group in ("types", "pools"):
        for v in (J.get(group) or {}).values():
            for k, sub in TURN_VALUES + (("ctx", "b"),):
                if _get(v, k, sub) is not None:
                    _set(v, k, sub, r1(_get(v, k, sub)))
            for k, sub in (("ctx", "a"), ("static_cc", None)):
                if _get(v, k, sub) is not None:
                    _set(v, k, sub, int(round(_get(v, k, sub))))
            b = v.get("band")
            if isinstance(b, dict):
                for q, _ in BAND_QTY:
                    if isinstance(b.get(q), dict):
                        f = (lambda x: round(float(x), 3)) if q == "ctx" else r1
                        b[q] = {s: f(b[q][s]) for s in ("lo", "med", "hi") if isinstance(b[q].get(s), (int, float))}
                if b.get("n_ref") is not None:
                    b["n_ref"] = r1(b["n_ref"])
    return J


def valid_model(J):
    return isinstance(J, dict) and isinstance(J.get("types"), dict) and bool(J["types"])


def refresh(usage, out, shipped_path, agents_dir, guard, step=STEP_DEFAULT, B=D.B_DEFAULT, dry_run=False, sid=None):
    shipped = json.load(open(shipped_path, encoding="utf-8"))
    if not valid_model(shipped):
        raise SystemExit("refresh: %s is not a model" % shipped_path)
    active = U.read_json(out)
    base = active if valid_model(active) and (active.get("refresh") or {}).get("base_generated") == \
        shipped.get("generated") else shipped
    rows = U.read_rows([os.path.join(usage, n) for n in ("runs.1.csv", "runs.csv", "runs2.1.csv", "runs2.csv")])
    seg = frame(rows, set(shipped.get("sessions") or []))
    fm_all = D.frontmatter(agents_dir)
    fm = {t: v for t, v in fm_all.items() if t in D.DT.TIER_OF}
    soft = soft_limits(guard, sid)
    new = None
    if len(seg):
        new = D.fit(seg, fm, soft, seed=0, B=B)
    sessions = sorted(seg.session.unique()) if len(seg) else []
    target = combine(shipped, new, sessions, len(seg))
    J = rounded(bounded(base, target, step))
    J["generated"] = now_iso()
    J["refresh"].update(refreshed=J["generated"], step=step, base=("active" if base is active else "shipped"),
                        method="n-weighted combination of the shipped model and fit() on runs.csv; bands combined "
                               "on the log scale; each value moves at most x step per refresh")
    if not dry_run:
        tmp = "%s.%d.tmp" % (out, os.getpid())
        os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(J, fh, indent=1)
            fh.write("\n")
        os.replace(tmp, out)
    sup = sum(1 for v in J["types"].values() if v.get("status") == "supported")
    flips = sorted(t for t, v in J["types"].items()
                   if v.get("status") == "supported" and (base["types"].get(t) or {}).get("status") != "supported")
    print("refresh: %d rows from %d sessions; %d/%d types supported; newly supported: %d" % (
        len(seg), len(sessions), sup, len(J["types"]), len(flips)))
    return J


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--usage", default=U.usage_dir())
    ap.add_argument("--out", default=U.active_model_path())
    ap.add_argument("--shipped", default=os.path.join(HERE, "sched_model.json"))
    ap.add_argument("--agents", default=os.path.join(os.path.dirname(HERE), "agents"))
    ap.add_argument("--guard", default=os.path.join(HERE, "agent_guard.py"))
    ap.add_argument("--step", type=float, default=float(os.environ.get("STACK_SCHED_REFRESH_STEP") or STEP_DEFAULT))
    ap.add_argument("--B", type=int, default=int(os.environ.get("STACK_SCHED_REFRESH_B") or D.B_DEFAULT))
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--session", default=None, help="session whose limits snapshot gives the soft limits "
                    "(default: STACK_LIMITS_SNAPSHOT, CLAUDE_SESSION_ID; else the seed)")
    a = ap.parse_args(argv)
    if not 1 < a.step < float("inf"):           # NaN fails too
        ap.error("--step must be a finite number > 1")
    refresh(a.usage, a.out, a.shipped, a.agents, a.guard, a.step, a.B, a.dry_run, a.session)
    return 0


if __name__ == "__main__":
    sys.exit(main())
