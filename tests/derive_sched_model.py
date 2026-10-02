# /// script
# requires-python = ">=3.11"
# dependencies = ["pandas>=2.2", "numpy>=1.26"]
# ///
"""Scheduler cost model (dot-claude/hooks/sched_model.json) derived from Claude Code transcripts.

Step 1b of .claude-work/agents-sched/plan.md, section (b). Read-only over the transcripts
(~/.claude/projects/*/<session>.jsonl and <session>/subagents/agent-*.jsonl + .meta.json), parsed
with tests/derive_thresholds.py's own functions (read_records, segments_of, summarize, TIER), so a
segment, an API call and `ctx` mean exactly what they mean there and in agent_guard.py.

Run:  uv run --script tests/derive_sched_model.py
      uv run --script tests/derive_sched_model.py --until now      # every transcript to date
      uv run --script tests/derive_sched_model.py --root DIR --agents DIR --guard FILE \
            --out FILE --report FILE --until ISO

Writes --out (default dot-claude/hooks/sched_model.json) and --report (default
.claude-work/agents-sched/model-fit.md). Deterministic for a fixed --until and fixed inputs: two
runs differ only in `generated`. The default --until pins the snapshot behind
.claude-work/agents-usage/segments.csv and the SOFT_LIMITS values (2026-10-02 20:28 UTC); a
segment counts only if its last API call is at or before --until.

Per type (healthy = finished, not compacted, not turn-limited, not the continuation of a
turn-limited segment):
  turns {S,M,L}     p25/p50/p90 of healthy segments' API calls (maxTurns counts these)
  ctx {a,b}         ctx(n) = a*n + b*n^2 for a segment of n API calls; ctx = input +
                    cache_creation + cache_read summed over the calls (the hook's unit). Fitted
                    on healthy first segments as ctx/n = a + b*n (Huber IRLS, scale = MAD; a no-
                    intercept fit in ctx), clipped to a, b >= 0.
  static_cc         p10 of the first call's cache_creation in healthy first segments
  sec_per_call      p50/p90 of (last_ts - first_ts) / api_calls over healthy segments
  cold              a resume whose gap exceeds the type's cache TTL re-writes about
                    min(cache_creation of the resumed segment, prior segment peak); `frac` is the
                    measured median of first-call cache_creation / that bound on cold resumes
  ttl, model, maxTurns from the agent's frontmatter; soft_limit from agent_guard.py SOFT_LIMITS
Pooling: theta = (n*theta_own + 5*theta_pool)/(n + 5) when the type has >= 5 healthy segments from
>= 3 agents (for ctx and static_cc: >= 5 healthy first segments), else theta = theta_pool and
source = "pool:<tier>". Tiers are derive_thresholds.TIER; the coordinator pool (orchestrator only)
is kept although it has 2 agents, because no other tier resembles a relay.

stack_hash = sha256 over the canonical JSON {agent: {model, maxTurns, cacheTtl}} of every
dot-claude/agents/*.md frontmatter (the fields this model reads; install-time placeholder
substitution elsewhere in the frontmatter does not change it). A consumer recomputes it from the
installed agents and treats a mismatch as a stale model.
"""
import argparse, ast, datetime as dt, glob, hashlib, json, math, os, re, sys

import numpy as np
import pandas as pd

TESTS = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(TESTS)
sys.path.insert(0, TESTS)
import derive_thresholds as DT  # noqa: E402  (same transcript parser as the soft limits)

UNTIL_DEFAULT = "2026-10-02T20:28:00Z"
K = 5                      # pooling prior weight (plan (b))
MIN_SEG, MIN_AGENTS = 5, 3
TTL_S = {"5m": 300, "1h": 3600}
POOLS = ("lookup", "analyst", "verifier", "artifact", "builder", "coordinator")
DOCS = "https://platform.claude.com/docs/en/build-with-claude/prompt-caching"
# plan (b) provisional defaults, used only to report disagreements (never written to the model)
DEFAULTS = {
    "turns_ML": {"claude-code-engineer": (42, 83), "coder": (18, 107), "verifier": (37, 91),
                 "code-reviewer": (41, 60), "planner": (27, 33), "researcher": (32, 48),
                 "claude-code-guide": (5, 9), "scout": (5, 7), "explore": (7, 8),
                 "main-coder": (44, 228), "writer": (9, 10), "browser-operator": (17, 37),
                 "orchestrator": (2, 4)},
    "ctx_a": {"claude-code-engineer": (95e3, 95e3)},
    "ctx_b": {"claude-code-engineer": (1.1e3, 1.45e3)},
    "sec_p50": {"claude-code-engineer": (9, 19), "planner": (28, 41), "code-reviewer": (9, 15),
                "verifier": (11, 16), "scout": (7, 9), "claude-code-guide": (7, 9)},
    "static_cc_max": {"scout": 28e3, "claude-code-guide": 35e3},
    "soft": {"claude-code-engineer": 19e6, "coder": 19e6, "main-coder": 19e6, "verifier": 26e6,
             "code-reviewer": 8.7e6, "planner": 8.7e6, "researcher": 8.7e6,
             "claude-code-guide": 680e3, "explore": 450e3, "scout": 390e3, "writer": 3.1e6,
             "browser-operator": 3.1e6},
}


def iso(x):
    return dt.datetime.fromisoformat(x.replace("Z", "+00:00"))


# ------------------------------------------------------------------------------------- inputs
def frontmatter(agents_dir):
    out = {}
    for f in sorted(glob.glob(os.path.join(agents_dir, "*.md"))):
        txt = open(f, encoding="utf-8").read()
        m = re.match(r"---\n(.*?)\n---", txt, re.S)
        fm = m.group(1) if m else ""
        g = lambda rx: (re.search(rx, fm, re.M) or [None, None])[1]
        name = g(r"^name:\s*(\S+)") or os.path.basename(f)[:-3]
        mt = g(r"^maxTurns:\s*(\d+)")
        out[name] = dict(model=g(r"^model:\s*(\S+)"), maxTurns=int(mt) if mt else None,
                         cacheTtl=g(r"^experimental:\s*\n(?:[ \t]+.*\n)*?[ \t]+cacheTtl:\s*(\S+)") or "5m")
    return out


def stack_hash(fm):
    canon = json.dumps({k: fm[k] for k in sorted(fm)}, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(canon.encode()).hexdigest()


def soft_limits(guard):
    """SOFT_LIMITS from agent_guard.py by AST (read-only; nothing is executed)."""
    tree = ast.parse(open(guard, encoding="utf-8").read())
    consts, soft = {}, None
    val = lambda n: consts[n.id] if isinstance(n, ast.Name) else ast.literal_eval(n)
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            name = node.targets[0].id
            if name.startswith("_SOFT_") and isinstance(node.value, ast.Constant):
                consts[name] = node.value.value
            elif name == "SOFT_LIMITS":
                soft = {ast.literal_eval(k): val(v) for k, v in zip(node.value.keys, node.value.values)}
    if soft is None:
        raise SystemExit(f"SOFT_LIMITS not found in {guard}")
    return soft


def load(root, until):
    """One row per subagent segment, as derive_thresholds.load, plus first-call fields, the gap to
    the previous segment and its peak. Segments whose last call is after `until` are dropped."""
    now = dt.datetime.now(dt.timezone.utc)
    lim = iso(until)
    rows, models = [], {}
    for main in sorted(glob.glob(os.path.join(root, "*", "*.jsonl"))):
        sid = os.path.basename(main)[:-6]
        sub = os.path.join(os.path.dirname(main), sid, "subagents")
        for f in sorted(glob.glob(os.path.join(sub, "agent-*.jsonl"))):
            aid = os.path.basename(f)[6:-6]
            try:
                meta = json.load(open(f[:-6] + ".meta.json"))
            except (OSError, ValueError):
                meta = {}
            atype = meta.get("agentType") or "(unknown)"
            atype = atype[:-5] if atype.endswith("-copy") else atype
            segs = DT.segments_of(DT.read_records(f))
            live = (now - dt.datetime.fromtimestamp(os.path.getmtime(f), dt.timezone.utc)).total_seconds() < DT.LIVE_S
            prev, prev_tl = None, False
            for i, sg in enumerate(segs):
                last = i == len(segs) - 1
                tl = sg["turn_limit"] or (last and sg.get("end") == "tr" and not live)
                s = DT.summarize(sg["calls"])
                row = dict(session=sid, id=aid, type=atype, seg=i, compactions=sg["compactions"],
                           turn_limit=bool(tl), after_limit=prev_tl,
                           open=bool(last and sg.get("end") in ("tool", "tr") and live), **s)
                prev_tl = bool(tl)
                if sg["calls"]:
                    c0 = sg["calls"][0]
                    row.update(first_cc=c0["cache_creation_input_tokens"], first_cr=c0["cache_read_input_tokens"],
                               gap_s=(iso(s["first_ts"]) - iso(prev["last_ts"])).total_seconds() if prev else np.nan,
                               prev_peak=prev["peak"] if prev else np.nan)
                    if iso(s["last_ts"]) <= lim:
                        rows.append(row)
                        for c in sg["calls"]:
                            models[c["model"]] = models.get(c["model"], 0) + 1
                    prev = s
    df = pd.DataFrame(rows)
    df["problem"] = df.turn_limit | (df.compactions > 0)
    df["healthy"] = ~df.open & ~df.problem & ~df.after_limit & (df.api_calls > 0)
    df["wall_s"] = [(iso(b) - iso(a)).total_seconds() for a, b in zip(df.first_ts, df.last_ts)]
    df["spc"] = df.wall_s / df.api_calls
    return df, models


# ------------------------------------------------------------------------------------- fits
def huber_line(x, y, c=1.345, iters=100):
    """Huber M-estimate of y = a + b*x by IRLS, scale = MAD of the residuals."""
    X = np.column_stack([np.ones_like(x), x])
    beta = np.linalg.lstsq(X, y, rcond=None)[0]
    for _ in range(iters):
        r = y - X @ beta
        s = np.median(np.abs(r - np.median(r))) / 0.6745
        if not s > 0:
            break
        w = np.minimum(1.0, c * s / np.maximum(np.abs(r), 1e-12))
        sw = np.sqrt(w)
        nb = np.linalg.lstsq(X * sw[:, None], y * sw, rcond=None)[0]
        if np.allclose(nb, beta, rtol=1e-10, atol=1e-9):
            beta = nb
            break
        beta = nb
    return float(beta[0]), float(beta[1])


def fit_ctx(n, ctx):
    n, ctx = np.asarray(n, float), np.asarray(ctx, float)
    y = ctx / n
    if len(n) == 1 or np.ptp(n) == 0:
        return float(np.median(y)), 0.0
    a, b = huber_line(n, y)
    if b < 0:
        a, b = float(np.median(y)), 0.0
    if a < 0:
        a, b = 0.0, float(np.median(y / n))
    return a, b


def raw_params(h, f):
    """Own (unpooled) parameters of a set of healthy segments h and healthy first segments f."""
    p = {}
    if len(h):
        x = h.api_calls.values
        p.update(S=np.quantile(x, .25), M=np.quantile(x, .5), L=np.quantile(x, .9),
                 spc50=np.quantile(h.spc.values, .5), spc90=np.quantile(h.spc.values, .9))
    if len(f):
        p["a"], p["b"] = fit_ctx(f.api_calls.values, f.ctx.values)
        p["static_cc"] = np.quantile(f.first_cc.values, .1)
    return p


TURN_KEYS, FIRST_KEYS = ("S", "M", "L", "spc50", "spc90"), ("a", "b", "static_cc")


def gate(d):
    return len(d) >= MIN_SEG and d.id.nunique() >= MIN_AGENTS


def fit(seg, types):
    """The model (pools + per type) from a segment table."""
    H = seg[seg.healthy]
    Fs = H[H.seg == 0]
    pools = {}
    for tier in POOLS:
        mem = DT.TIER[tier].split()
        h, f = H[H.type.isin(mem)], Fs[Fs.type.isin(mem)]
        if len(h) and len(f) and (gate(h) or tier == "coordinator"):
            pools[tier] = dict(p=raw_params(h, f), n_seg=len(h), n_agents=int(h.id.nunique()), n_first=len(f))
    out = {}
    for t in types:
        tier = DT.TIER_OF.get(t)
        h, f = H[H.type == t], Fs[Fs.type == t]
        own = raw_params(h, f)
        pool = pools.get(tier)
        p, src = {}, {}
        for keys, d, nm in ((TURN_KEYS, h, "turns"), (FIRST_KEYS, f, "ctx")):
            if pool and gate(d):
                n = len(d)
                for k in keys:
                    p[k] = (n * own[k] + K * pool["p"][k]) / (n + K)
                src[nm] = "own"
            elif pool:
                for k in keys:
                    p[k] = pool["p"][k]
                src[nm] = f"pool:{tier}"
            elif gate(d):
                for k in keys:
                    p[k] = own[k]
                src[nm] = "own"
            else:
                src[nm] = None
        out[t] = dict(p=p, tier=tier, n_seg=len(h), n_agents=int(h.id.nunique()), n_first=len(f),
                      source=src["turns"], source_ctx=src["ctx"])
    return out, pools


def cold_resumes(seg, fm):
    r = seg[(seg.seg > 0) & seg.gap_s.notna() & (seg.api_calls > 0)].copy()
    r["ttl_s"] = r.type.map(lambda t: TTL_S.get(fm.get(t, {}).get("cacheTtl", "5m"), 300))
    r["bound"] = np.minimum(r.cache_creation_input_tokens, r.prev_peak)
    # warm: the first call re-reads the prior context from cache; cold: it reads at most the shared
    # system prefix and writes the context again
    r["cold"] = r.first_cr < 0.5 * r.prev_peak
    r["over_ttl"] = r.gap_s > r.ttl_s
    r["frac"] = r.first_cc / r.bound.where(r.bound > 0)
    return r


# ------------------------------------------------------------------------------------- output
def r1(x):
    return None if x is None or not np.isfinite(x) else round(float(x), 1)


def ri(x):
    return None if x is None or not np.isfinite(x) else int(round(float(x)))


def params_json(p):
    return dict(turns=dict(S=r1(p.get("S")), M=r1(p.get("M")), L=r1(p.get("L"))),
                ctx=dict(a=ri(p.get("a")), b=r1(p.get("b"))),
                static_cc=ri(p.get("static_cc")),
                sec_per_call=dict(p50=r1(p.get("spc50")), p90=r1(p.get("spc90"))))


def build(seg, models, fm, soft, until):
    types = sorted(t for t in fm if t in DT.TIER_OF)
    missing = sorted(t for t in fm if t not in DT.TIER_OF and t != "blackcat")
    if missing:
        raise SystemExit(f"agents without a tier in derive_thresholds.TIER: {missing}")
    model, pools = fit(seg, types)
    cr = cold_resumes(seg, fm)
    cold_obs = cr[cr.cold & cr.over_ttl & cr.frac.notna()]
    frac = float(np.median(cold_obs.frac)) if len(cold_obs) >= MIN_SEG else None
    fam = {}
    for k, n in sorted(models.items(), key=lambda kv: (-kv[1], str(kv[0]))):
        for f in ("opus", "sonnet", "haiku"):
            if k and f"-{f}-" in str(k) and f not in fam:
                fam[f] = k
    J = dict(version=1, generated=dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
             stack_hash=stack_hash(fm), sessions=sorted(seg.session.unique().tolist()), data_until=until,
             kappa=dict(cache_write_5m=1.25, cache_write_1h=2.0,
                        cache_read={"default": 0.1, "opus-5-5": 0.05},
                        cache_read_match="the longest key that is a substring of the model ID, else default",
                        output=None, prices=None, models_measured=fam, source=DOCS),
             types={}, pools={})
    for t in types:
        m, f = model[t], fm[t]
        ttl = f["cacheTtl"]
        J["types"][t] = dict(model=f["model"], ttl=ttl, tier=m["tier"], **params_json(m["p"]),
                             cold=dict(after_s=TTL_S.get(ttl, 300), rewrite="min(cache_creation, prior_peak)",
                                       frac=round(frac, 3) if frac is not None else None),
                             soft_limit=soft.get(t), maxTurns=f["maxTurns"], n_seg=m["n_seg"],
                             n_agents=m["n_agents"], n_first=m["n_first"], source=m["source"],
                             source_ctx=m["source_ctx"])
    for tier in POOLS:
        if tier in pools:
            pl = pools[tier]
            J["pools"][tier] = dict(**params_json(pl["p"]), n_seg=pl["n_seg"], n_agents=pl["n_agents"],
                                    n_first=pl["n_first"])
    return J, model, pools, cr


# ------------------------------------------------------------------------------------- validation
def ctx_pred(p, n):
    return p["a"] * n + p["b"] * n * n


def loso(seg, types, by="session"):
    """Leave one group out (by session, or by agent id): refit everything (pools, gates,
    shrinkage) without the group, predict its healthy segments. One row per held-out segment."""
    rows = []
    for s in sorted(seg[by].unique()):
        tr, te = seg[seg[by] != s], seg[(seg[by] == s) & seg.healthy]
        if tr.empty or te.empty:
            continue
        m, pools = fit(tr, types)
        for r in te.itertuples():
            if r.type not in m:
                continue
            p = m[r.type]["p"]
            pl = pools.get(m[r.type]["tier"], {}).get("p", {})
            row = dict(session=s, type=r.type, seg=r.seg, n=r.api_calls, src=m[r.type]["source"])
            if "M" in p:
                row["e_turns"] = abs(math.log(p["M"] / r.api_calls))
                if r.wall_s > 0:
                    row["e_wall_n"] = abs(math.log(p["spc50"] * r.api_calls / r.wall_s))
                    row["e_wall_M"] = abs(math.log(p["spc50"] * p["M"] / r.wall_s))
            if "M" in pl:
                row["e_turns_pool"] = abs(math.log(pl["M"] / r.api_calls))
            if r.seg == 0 and "a" in p and ctx_pred(p, r.api_calls) > 0:
                row["e_ctx_n"] = abs(math.log(ctx_pred(p, r.api_calls) / r.ctx))
                row["e_ctx_M"] = abs(math.log(ctx_pred(p, p["M"]) / r.ctx))
            rows.append(row)
    return pd.DataFrame(rows)


def check_segments_csv(seg, path):
    if not os.path.exists(path):
        return "segments.csv not found: no cross-check."
    ref = pd.read_csv(path)
    ref = ref[~ref.open & (ref.api_calls > 0)]
    j = ref.merge(seg, on=["id", "seg"], suffixes=("_ref", ""), how="left", indicator=True)
    both = j[j._merge == "both"]
    same = int(((both.api_calls_ref == both.api_calls) & (both.ctx_ref == both.ctx)).sum())
    return (f"{same} of {len(ref)} finished segments in segments.csv have identical api_calls and ctx here; "
            f"{int((j._merge == 'left_only').sum())} missing here; {len(seg) - len(both)} here not in segments.csv.")


def fmt(v, unit=""):
    if v is None or (isinstance(v, float) and not np.isfinite(v)):
        return "-"
    if unit == "tok":
        return f"{v/1e6:.2f}M" if v >= 1e6 else f"{v/1e3:.1f}k"
    return f"{v:.1f}" if isinstance(v, float) else str(v)


def table(rows, hdr):
    o = ["| " + " | ".join(hdr) + " |", "|" + "|".join("---" for _ in hdr) + "|"]
    return "\n".join(o + ["| " + " | ".join(str(c) for c in r) + " |" for r in rows])


def disagreements(J):
    out = []

    def cmp(t, what, fit_v, lo, hi):
        if fit_v is None or t not in J["types"]:
            return
        if fit_v < lo * 0.7 or fit_v > hi * 1.3:
            ref = lo if fit_v < lo else hi
            out.append([t, what, f"{lo:g}" if lo == hi else f"{lo:g}-{hi:g}", f"{fit_v:g}",
                        f"{100*(fit_v-ref)/ref:+.0f}%", J["types"][t]["source"]])
    for t, (m, l) in DEFAULTS["turns_ML"].items():
        cmp(t, "turns M", J["types"][t]["turns"]["M"], m, m)
        cmp(t, "turns L", J["types"][t]["turns"]["L"], l, l)
    for t, (lo, hi) in DEFAULTS["ctx_a"].items():
        cmp(t, "ctx a", J["types"][t]["ctx"]["a"], lo, hi)
    for t, (lo, hi) in DEFAULTS["ctx_b"].items():
        cmp(t, "ctx b", J["types"][t]["ctx"]["b"], lo, hi)
    for t, (lo, hi) in DEFAULTS["sec_p50"].items():
        cmp(t, "sec_per_call p50", J["types"][t]["sec_per_call"]["p50"], lo, hi)
    for t, hi in DEFAULTS["static_cc_max"].items():
        v = J["types"][t]["static_cc"]
        if v is not None and v > hi * 1.3:
            out.append([t, "static_cc (upper bound)", f"<= {hi:g}", f"{v:g}", f"{100*(v-hi)/hi:+.0f}%",
                        J["types"][t]["source_ctx"]])
    for t, v in DEFAULTS["soft"].items():
        s = J["types"][t]["soft_limit"]
        if s is None or abs(s - v) / v > 0.3:
            out.append([t, "soft_limit", f"{v:g}", f"{s}", "-" if s is None else f"{100*(s-v)/v:+.0f}%", "agent_guard.py"])
    return out


def report(J, model, pools, cr, ev, ev_agent, seg, check):
    o = []
    P = o.append
    H = seg[seg.healthy]
    P("# sched_model.json: fit report\n")
    P(f"Generated {J['generated']} by `uv run --script tests/derive_sched_model.py` (data until "
      f"{J['data_until']}; sessions {', '.join(s[:8] for s in J['sessions'])}; stack_hash "
      f"`{J['stack_hash'][:19]}…`). Healthy segments: {len(H)} of {len(seg)} ({int(seg.open.sum())} open, "
      f"{int(seg.problem.sum())} compacted or turn-limited, {int(seg.after_limit.sum())} after a turn limit). "
      f"Cross-check against `.claude-work/agents-usage/segments.csv`: {check}\n")
    P("## Per type\n")
    P("`n_seg / n_agents` = healthy segments / distinct agents (turns, sec_per_call); `n_first` = healthy first "
      "segments (ctx, static_cc). Source: `own` = shrunk own fit, (n*own + 5*pool)/(n + 5); `pool:<tier>` = the "
      "tier's pooled fit. Types with no data and no own fit carry their pool's values.\n")
    rows = []
    for t, d in J["types"].items():
        if d["n_seg"] == 0 and d["n_first"] == 0:
            continue
        rows.append([t, d["tier"], f"{d['n_seg']} / {d['n_agents']}", d["n_first"], d["source"], d["source_ctx"],
                     "/".join(fmt(d["turns"][k]) for k in "SML"), fmt(d["ctx"]["a"], "tok"), fmt(d["ctx"]["b"]),
                     fmt(d["static_cc"], "tok"), f"{fmt(d['sec_per_call']['p50'])} / {fmt(d['sec_per_call']['p90'])}",
                     d["ttl"], d["maxTurns"], fmt(d["soft_limit"], "tok") if d["soft_limit"] else "none"])
    P(table(rows, ["type", "tier", "n_seg / n_agents", "n_first", "source", "source ctx", "turns S/M/L",
                   "ctx a", "ctx b", "static_cc", "s/call p50 / p90", "ttl", "maxTurns", "soft"]))
    unobs = [t for t, d in J["types"].items() if d["n_seg"] == 0 and d["n_first"] == 0]
    P(f"\nUnobserved types ({len(unobs)}) use their pool: " +
      "; ".join(f"{tier}: {', '.join(t for t in unobs if J['types'][t]['tier'] == tier)}"
                for tier in POOLS if any(J['types'][t]['tier'] == tier for t in unobs)) + ".\n")
    P(table([[k, f"{v['n_seg']} / {v['n_agents']}", v["n_first"], "/".join(fmt(v["turns"][x]) for x in "SML"),
              fmt(v["ctx"]["a"], "tok"), fmt(v["ctx"]["b"]), fmt(v["static_cc"], "tok"),
              f"{fmt(v['sec_per_call']['p50'])} / {fmt(v['sec_per_call']['p90'])}"] for k, v in J["pools"].items()],
            ["pool", "n_seg / n_agents", "n_first", "turns S/M/L", "ctx a", "ctx b", "static_cc", "s/call p50 / p90"]))

    cols = ["e_turns", "e_turns_pool", "e_ctx_n", "e_ctx_M", "e_wall_n", "e_wall_M"]
    med = lambda s: f"{s.median():.2f} ({s.notna().sum()})" if s.notna().any() else "-"
    hdr = ["type", "turns", "turns, pool only", "ctx \\| n", "ctx \\| M", "wall \\| n", "wall \\| M"]

    def errtable(e):
        e = e.copy()
        for c in cols:
            if c not in e:
                e[c] = np.nan
        rows = [[t] + [med(g[c]) for c in cols] for t, g in e.groupby("type")]
        missing = sorted(set(H.type) - set(e.dropna(subset=["e_turns"]).type))
        return table(rows + [["**all**"] + [med(e[c]) for c in cols]], hdr), missing, e

    P("\n## Leave one session out\n")
    P("Each session held out in turn: pools, gates and shrinkage refitted on the other session(s), errors on the "
      "held-out session's healthy segments. Cells: median |log(pred/actual)| (0.69 = a factor of 2) and n. "
      "`turns` predicts M; `ctx | n` = ctx(a, b) at the actual API calls (healthy first segments); `ctx | M` = "
      "ctx at the predicted M (what the planner sees); `wall | n` = sec_per_call p50 x actual calls; `wall | M` = "
      "p50 x M; `turns, pool only` = the tier pool's M, the baseline the per-type fit must beat.\n")
    tb, missing, ev = errtable(ev)
    P(tb)
    one = sorted(t for t, g in H.groupby("type") if g.session.nunique() == 1)
    P(f"\nWith {seg.session.nunique()} sessions most types occur in one session only ({', '.join(one)}): held out, "
      "they are predicted from their pool fitted on the other session, so the `turns` and `pool only` columns "
      "coincide and this table measures transfer to a session where the type was never seen. No prediction at "
      "all (neither the type nor its pool in the other session): " + (", ".join(missing) or "none") + ".\n")
    P("## Leave one agent out\n")
    P("The case the planner meets: a new agent of a type seen before. Each agent's segments held out in turn, "
      "everything refitted on the rest; same columns.\n")
    tb2, missing2, ev2 = errtable(ev_agent)
    P(tb2)
    weak = [t for t, g in ev2.groupby("type") if g.e_turns.median() > math.log(2) or
            (g.e_ctx_n.notna().any() and g.e_ctx_n.median() > math.log(1.5)) or
            (g.e_wall_n.notna().any() and g.e_wall_n.median() > math.log(2))]
    P("\nFlagged (leave one agent out: turns or wall | n off by more than 2x, or ctx | n by more than 1.5x, at the "
      "median): " + (", ".join(weak) or "none") + ".\n")

    P("## Cold resumes\n")
    P("A resume is cold when its first call reads less than half the prior segment's peak from cache (it then "
      "re-writes the context). Rule tested: cold if and only if the gap exceeds the type's ttl (worktree "
      "frontmatter `experimental.cacheTtl`, default 5m).\n")
    rows = []
    for lab, g in (("gap <= ttl", cr[~cr.over_ttl]), ("gap > ttl", cr[cr.over_ttl])):
        for ttl in sorted(g.ttl_s.unique()):
            x = g[g.ttl_s == ttl]
            rows.append([lab, f"{ttl} s", len(x), int(x.cold.sum()),
                         f"{x[x.cold].frac.median():.2f}" if x.cold.any() and x[x.cold].frac.notna().any() else "-"])
    P(table(rows, ["gap vs ttl", "ttl", "resumes", "cold", "median first-call write / min(segment cache_creation, "
                   "prior peak), cold ones"]))
    odd = cr[cr.cold != cr.over_ttl]
    P(f"\nRule misses: {len(odd)} of {len(cr)} resumes" + (": " + "; ".join(
        f"{r.type} {r.id[:7]}/{r.seg} gap {r.gap_s:.0f} s, ttl {r.ttl_s} s, {'cold' if r.cold else 'warm'}"
        for r in odd.itertuples()) if len(odd) else "") + f". `cold.frac` in the model = "
      f"{J['types'][next(iter(J['types']))]['cold']['frac']} (median over cold resumes with gap > ttl; null below "
      "5 observations); below 1 where a compaction shrank the context below the prior peak.\n")

    P("## Where the fit disagrees with the plan (b) provisional defaults by more than 30%\n")
    dis = disagreements(J)
    P(table(dis, ["type", "quantity", "default", "fit", "vs nearest default", "source"]) if dis else "None.")
    P("")
    return "\n".join(o) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=os.path.expanduser("~/.claude/projects"))
    ap.add_argument("--agents", default=os.path.join(REPO, "dot-claude", "agents"))
    ap.add_argument("--guard", default=os.path.join(REPO, "dot-claude", "hooks", "agent_guard.py"))
    ap.add_argument("--out", default=os.path.join(REPO, "dot-claude", "hooks", "sched_model.json"))
    ap.add_argument("--report", default=os.path.join(REPO, ".claude-work", "agents-sched", "model-fit.md"))
    ap.add_argument("--segments-csv", default=os.path.join(REPO, ".claude-work", "agents-usage", "segments.csv"))
    ap.add_argument("--until", default=UNTIL_DEFAULT, help="ISO timestamp or 'now'")
    a = ap.parse_args()
    until = (dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ") if a.until == "now" else a.until)
    fm = frontmatter(a.agents)
    soft = soft_limits(a.guard)
    seg, models = load(a.root, until)
    J, model, pools, cr = build(seg, models, fm, soft, until)
    ev = loso(seg, list(J["types"]))
    ev_agent = loso(seg, list(J["types"]), by="id")
    with open(a.out, "w", encoding="utf-8") as fh:
        json.dump(J, fh, indent=1)
        fh.write("\n")
    if a.report:
        os.makedirs(os.path.dirname(a.report), exist_ok=True)
        txt = report(J, model, pools, cr, ev, ev_agent, seg, check_segments_csv(seg, a.segments_csv))
        with open(a.report, "w", encoding="utf-8") as fh:
            fh.write(txt)
    print(f"wrote {a.out}" + (f" and {a.report}" if a.report else ""))


if __name__ == "__main__":
    main()
