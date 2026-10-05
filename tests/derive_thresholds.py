# /// script
# requires-python = ">=3.11"
# dependencies = ["pandas>=2.2", "numpy>=1.26"]
# ///
"""Data-derived soft token limits and maxTurns for the claude-agent-stack agents.

The derivation behind agent_guard.py's SOFT_LIMITS / SOFT_PROMPT_CTX and the maxTurns values of
2026-10-02 (CONFIG.md, "Soft token limits"). The repo copy of the analysis script first run as
.claude-work/agents-usage/thresholds.py; it changes no configuration: compare its thresholds.md
with the values in agent_guard.py and the agents' frontmatter, and change those by hand.

Read-only over Claude Code transcripts (~/.claude/projects/*/<session>.jsonl and
<session>/subagents/agent-*.jsonl + .meta.json). Writes only into --out (default
<repo>/.claude-work/agents-usage/, which git ignores locally):
  segments.csv   one row per subagent run segment (a spawn or a resume = one hook "run")
  runs.csv       one row per subagent (all its segments)
  prompts.csv    one row per human-prompt window and per hook-effective window
  sessions.csv   one row per session
  thresholds.md  the derived table and notes (regenerated in full)

Run:  uv run --script tests/derive_thresholds.py
      uv run --script tests/derive_thresholds.py --root DIR --agents DIR --out DIR --session ID

Definitions
  api call   one assistant message, deduplicated by (message.id, requestId), per field the max
             (a streamed message is written as several lines). maxTurns counts these (verified:
             the harness verifier stopped at exactly 150 = its installed maxTurns).
  ctx        input + cache_creation + cache_read: the hook's unit (agent_guard.py USAGE_KEYS)
  fresh      input + output + cache_creation (new tokens processed)
  cum        fresh + cache_read
  peak       largest single-call context (input + cache_creation + cache_read)
  rereads    cache_read / peak: how many times a context the size of the peak was re-read
  segment    a subagent's run from its first prompt, or from a resume ("... sent a message while
             you were working" arriving after the agent ended its turn), to the next resume.
             Compaction stays inside the segment. This matches the hook's MCP-call cap, which
             restarts its count on every spawn or resume.
  problem    a segment that compacted (its context ran out) or stopped at its turn limit;
             after_limit = the continuation segment of a turn-limited run.
  healthy    finished, not problem, not after_limit.
"""
import argparse, glob, json, os, re, datetime as dt
import sys
import numpy as np, pandas as pd

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HERE = os.path.join(REPO, ".claude-work", "agents-usage")   # output folder (--out)
# q, ceil2 and derive are the stack's shared statistics (dot-claude/hooks/stack_limits.py; installed
# beside this file or in the repo's hooks folder)
sys.path[:0] = [os.path.dirname(os.path.abspath(__file__)), os.path.join(REPO, "dot-claude", "hooks")]
from stack_limits import q, ceil2, derive as _derive  # noqa: E402,F401
F = ("input_tokens", "output_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")
RESUME_RE = re.compile(r"^(Another Claude session|The coordinator) sent a message while you were working")
COMPACT_RE = re.compile(r"^This session is being continued from a previous conversation")
TURN_LIMIT_RE = re.compile(r"turn limit", re.I)
LIVE_S = 600
SEED = 20261002
M_GRID = (1.25, 1.3, 1.35, 1.4, 1.45, 1.5)
FT_OK, FT_REJECT = 0.05, 0.10
UNIT = "ctx"
THIS_SESSION = "4e2da3ce-e2f4-4971-aac5-a67f2dcf252e"   # --session: the session reported on
BENCH_EST = 51_124_527   # agents-bench/dry-run-output.txt, both arms, 102 `claude -p` sessions

# comparable-type pools for types with too few runs (judgement: same role, tools and maxTurns band)
TIER = {
    "lookup": "scout oracle claude-code-guide explore mcp-broker",
    "analyst": "planner plan-reviewer code-reviewer security-auditor researcher proof-checker",
    "verifier": "verifier",
    "coordinator": "orchestrator",
    "artifact": ("writer browser-operator doc-specialist designer image-director motion-designer cg-artist "
                 "rigger-animator sculptor-painter"),
    "builder": ("claude-code-engineer coder main-coder ninja-coder build-fixer test-engineer "
                "data-scientist data-engineer devops-engineer frontend-engineer python-engineer "
                "rust-engineer go-engineer node-engineer jvm-engineer julia-engineer haskell-engineer "
                "mobile-engineer game-engineer embedded-engineer hpc-engineer cuda-engineer mlx-engineer "
                "dl-engineer ml-engineer llm-engineer robotics-engineer quantum-engineer biochem-engineer "
                "security-engineer vfx-td mathematician procedural-3d-ui"),
}
TIER_OF = {t: k for k, v in TIER.items() for t in v.split()}


# ------------------------------------------------------------------------------------- extraction
def ts(x):
    return dt.datetime.fromisoformat(x.replace("Z", "+00:00"))


def text_of(c):
    if isinstance(c, str):
        return c
    if isinstance(c, list):
        return " ".join(b.get("text", "") for b in c if isinstance(b, dict) and b.get("type") == "text")
    return ""


def is_tool_result(c):
    return isinstance(c, list) and any(isinstance(b, dict) and b.get("type") == "tool_result" for b in c)


# API calls per model over every transcript read (the models the thresholds are measured on)
MODELS = {}
# doctor.sh's record of those models: /stack-doctor warns when an alias resolves elsewhere
DOCTOR = os.path.join(REPO, "dot-claude", "bin", "doctor.sh")


def read_records(path):
    calls, ev = {}, []
    for line in open(path, encoding="utf-8", errors="replace"):
        try:
            r = json.loads(line)
        except ValueError:
            continue
        t = r.get("type")
        if t == "assistant":
            m = r.get("message") or {}
            u = m.get("usage")
            if not isinstance(u, dict):
                continue
            key = f"{m.get('id')}|{r.get('requestId')}"
            if key == "None|None":
                key = "uuid|" + str(r.get("uuid"))
            c = calls.get(key)
            if c is None:
                c = calls[key] = {f: 0 for f in F}
                c.update(ts=r.get("timestamp"), model=m.get("model"), tools=set())
                MODELS[m.get("model")] = MODELS.get(m.get("model"), 0) + 1
                ev.append(("call", c))
            for f in F:
                c[f] = max(c[f], int(u.get(f) or 0))
            for b in m.get("content") or []:
                if isinstance(b, dict) and b.get("type") == "tool_use":
                    c["tools"].add(b.get("id"))
            c["last_ts"] = r.get("timestamp")
        elif t == "user":
            m = r.get("message") or {}
            c = m.get("content")
            ev.append(("user", dict(ts=r.get("timestamp"), tr=is_tool_result(c), text=text_of(c)[:300],
                                    meta=bool(r.get("isMeta")), prompt=r.get("promptId"))))
    return ev


def segments_of(ev):
    segs, cur, last_kind = [], None, None
    for kind, e in ev:
        if kind == "user" and not e["tr"]:
            t = e["text"]
            if cur is None or (RESUME_RE.match(t) and last_kind in ("end", "tr")):
                if cur is not None and last_kind == "tr" and TURN_LIMIT_RE.search(t):
                    cur["turn_limit"] = True
                cur = dict(calls=[], compactions=0, turn_limit=False)
                segs.append(cur)
            elif COMPACT_RE.match(t):
                cur["compactions"] += 1
            continue
        if cur is None:
            cur = dict(calls=[], compactions=0, turn_limit=False)
            segs.append(cur)
        if kind == "user":
            last_kind = "tr"
        else:
            cur["calls"].append(e)
            last_kind = "tool" if e["tools"] else "end"
    if segs:
        segs[-1]["end"] = last_kind
    return segs


def summarize(calls):
    s = {f: sum(c[f] for c in calls) for f in F}
    s["api_calls"] = len(calls)
    s["tool_calls"] = sum(len(c["tools"]) for c in calls)
    s["fresh"] = s["input_tokens"] + s["output_tokens"] + s["cache_creation_input_tokens"]
    s["ctx"] = s["input_tokens"] + s["cache_creation_input_tokens"] + s["cache_read_input_tokens"]
    s["cum"] = s["fresh"] + s["cache_read_input_tokens"]
    pk = [c["input_tokens"] + c["cache_creation_input_tokens"] + c["cache_read_input_tokens"] for c in calls]
    s["peak"] = max(pk, default=0)
    s["rereads"] = round(s["cache_read_input_tokens"] / s["peak"], 1) if s["peak"] else 0.0
    s["first_ts"] = calls[0]["ts"] if calls else None
    s["last_ts"] = (calls[-1].get("last_ts") or calls[-1]["ts"]) if calls else None
    return s


def load(root):
    now = dt.datetime.now(dt.timezone.utc)
    seg_rows, run_rows, sess, mains = [], [], [], {}
    for main in sorted(glob.glob(os.path.join(root, "*", "*.jsonl"))):
        sid = os.path.basename(main)[:-6]
        proj = os.path.basename(os.path.dirname(main))
        sub = os.path.join(os.path.dirname(main), sid, "subagents")
        mev = read_records(main)
        files = sorted(glob.glob(os.path.join(sub, "agent-*.jsonl")))
        allcalls = [e for k, e in mev if k == "call"]
        typed = 0
        for f in files:
            aid = os.path.basename(f)[6:-6]
            try:
                meta = json.load(open(f[:-6] + ".meta.json"))
            except (OSError, ValueError):
                meta = {}
            atype = meta.get("agentType") or "(unknown)"
            typed += atype in TIER_OF
            ev = read_records(f)
            allcalls += [e for k, e in ev if k == "call"]
            segs = segments_of(ev)
            live = (now - dt.datetime.fromtimestamp(os.path.getmtime(f), dt.timezone.utc)).total_seconds() < LIVE_S
            prev_tl = False
            first = len(seg_rows)
            for i, sg in enumerate(segs):
                last = i == len(segs) - 1
                open_ = last and sg.get("end") in ("tool", "tr") and live
                tl = sg["turn_limit"] or (last and sg.get("end") == "tr" and not live)
                seg_rows.append(dict(session=sid, id=aid, type=atype, desc=meta.get("description", ""),
                                     depth=meta.get("spawnDepth"), seg=i, nsegs=len(segs),
                                     compactions=sg["compactions"], turn_limit=bool(tl), after_limit=prev_tl,
                                     open=bool(open_), **summarize(sg["calls"])))
                prev_tl = bool(tl)
            mine = seg_rows[first:]
            run_rows.append(dict(session=sid, id=aid, type=atype, desc=meta.get("description", ""), nsegs=len(segs),
                                 compactions=sum(x["compactions"] for x in mine),
                                 turn_limit=any(x["turn_limit"] for x in mine), open=any(x["open"] for x in mine),
                                 **summarize([c for sg in segs for c in sg["calls"]])))
        tot = summarize(sorted(allcalls, key=lambda c: c["ts"]))
        sess.append(dict(session=sid, project=proj, subagents=len(files), stack_typed=typed,
                         live=(now - dt.datetime.fromtimestamp(os.path.getmtime(main), dt.timezone.utc)).total_seconds() < LIVE_S,
                         **{k: tot[k] for k in ("fresh", "ctx", "cum", "cache_read_input_tokens", "api_calls", "first_ts")}))
        mains[sid] = dict(ev=mev, calls=sorted(allcalls, key=lambda c: c["ts"]))
    return pd.DataFrame(seg_rows), pd.DataFrame(run_rows), pd.DataFrame(sess), mains


def prompt_windows(mains):
    """human: windows between human prompts (UserPromptSubmit). hook: the hook also restarts the
    prompt budget when a main-thread tool call carries a prompt_id it has not seen
    (budget_note_prompt); task notifications get their own promptId, so a notification the main
    thread acts on with a tool call starts a new hook window."""
    rows = []
    for sid, m in mains.items():
        human, eff, pend, seen = [], [], None, set()
        for k, e in m["ev"]:
            if k == "user" and not e["tr"] and not e["meta"]:
                t = e["text"]
                if t.startswith("<task-notification>"):
                    if e["prompt"] and e["prompt"] not in seen:
                        pend = (e["ts"], e["prompt"])
                    continue
                if t.startswith("Base directory for this skill"):
                    continue
                human.append((e["ts"], t[:70].replace("\n", " ").replace("|", "/")))
                eff.append(e["ts"]); seen.add(e["prompt"]); pend = None
            elif k == "call" and e["tools"] and pend:
                eff.append(e["ts"]); seen.add(pend[1]); pend = None
        calls = m["calls"]
        cts = np.array([ts(c["ts"]).timestamp() for c in calls])
        for kind, bounds in (("human", [h[0] for h in human]), ("hook", sorted(set(eff)))):
            b = [ts(x).timestamp() for x in bounds] + [np.inf]
            for i in range(len(b) - 1):
                idx = np.nonzero((cts >= b[i]) & (cts < b[i + 1]))[0]
                sel = [calls[j] for j in idx]
                s = summarize(sel)
                cs = np.cumsum([c["input_tokens"] + c["cache_creation_input_tokens"] + c["cache_read_input_tokens"] for c in sel])
                rows.append(dict(session=sid, kind=kind, i=i,
                                 start=dt.datetime.fromtimestamp(b[i], dt.timezone.utc).strftime("%H:%M"),
                                 prompt=human[i][1] if kind == "human" else "",
                                 fresh=s["fresh"], ctx=s["ctx"], cum=s["cum"], api_calls=s["api_calls"],
                                 cumctx=cs, callts=[c["ts"] for c in sel]))
    return pd.DataFrame(rows)


# ------------------------------------------------------------------------------------- statistics
def auc(pos, neg):
    pos, neg = np.asarray(pos, float), np.asarray(neg, float)
    if not len(pos) or not len(neg):
        return np.nan
    return float((pos[:, None] > neg[None, :]).mean() + (pos[:, None] == neg[None, :]).mean() / 2)


def derive(x, names, hard=False):
    """stack_limits.derive (the shared core), with a NaN pair for the CI of fewer than 3 values (this
    report formats it)."""
    d = _derive(x, names, hard=hard)
    if d["ci"][0] is None:
        d["ci"] = (np.nan, np.nan)
    return d


def M(v):
    if v is None or (isinstance(v, float) and not np.isfinite(v)):
        return "-"
    return f"{v/1e6:.1f}M" if v >= 1e6 else f"{v/1e3:.0f}k"


def table(rows, hdr):
    o = ["| " + " | ".join(hdr) + " |", "|" + "|".join("---" for _ in hdr) + "|"]
    o += ["| " + " | ".join(str(c) for c in r) + " |" for r in rows]
    return "\n".join(o)


# ------------------------------------------------------------------------------------- report
def main():
    global HERE, THIS_SESSION
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=os.path.expanduser("~/.claude/projects"))
    ap.add_argument("--agents", default=os.path.join(REPO, "dot-claude", "agents"))
    ap.add_argument("--out", default=HERE)
    ap.add_argument("--session", default=THIS_SESSION)
    a = ap.parse_args()
    HERE, THIS_SESSION = a.out, a.session
    os.makedirs(HERE, exist_ok=True)
    seg, run, sess, mains = load(a.root)
    pw = prompt_windows(mains)
    seg.to_csv(os.path.join(HERE, "segments.csv"), index=False)
    run.to_csv(os.path.join(HERE, "runs.csv"), index=False)
    pw.drop(columns=["cumctx", "callts"]).to_csv(os.path.join(HERE, "prompts.csv"), index=False)
    sess.to_csv(os.path.join(HERE, "sessions.csv"), index=False)
    mt = {}
    for f in glob.glob(os.path.join(a.agents, "*.md")):
        mm = re.search(r"^maxTurns:\s*(\d+)\s*$", open(f).read(4096), re.M)
        if mm:
            mt[os.path.basename(f)[:-3]] = int(mm.group(1))
    out = report(seg, run, sess, pw, mt)
    open(os.path.join(HERE, "thresholds.md"), "w").write(out)
    print(out)


def report(seg, run, sess, pw, mt):
    o = []
    P = o.append
    sh = lambda s: s[:8]
    seg = seg.copy()
    seg["name"] = seg.id.str[:7] + "/" + seg.seg.astype(str) + " " + seg.desc.str[:34] + " [" + seg.session.map(sh) + "]"
    seg["problem"] = seg.turn_limit | (seg.compactions > 0)
    seg["tier"] = seg.type.map(TIER_OF).fillna("other")
    fin = seg[~seg.open]
    H = fin[~fin.problem & ~fin.after_limit]
    now = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    P(f"# Soft token limits and maxTurns, derived from transcripts\n\nGenerated {now} by `tests/derive_thresholds.py` "
      f"(recompute: `uv run --script tests/derive_thresholds.py`). Raw tables: `segments.csv`, "
      f"`runs.csv`, `prompts.csv`, `sessions.csv`. Read-only over transcripts; no prompt text beyond the "
      f"first 70 characters of each human prompt.\n")

    # ---- data
    P("## Data\n")
    rows = []
    for r in sess.itertuples():
        rows.append([sh(r.session), re.sub(r"^-Users-[^-]+-", "", r.project)[:40], r.subagents, r.stack_typed,
                     M(r.ctx), M(r.fresh), f"{100*r.cache_read_input_tokens/max(r.cum,1):.1f}%", r.api_calls,
                     "live (partial)" if r.live else "ended"])
    P(table(rows, ["session", "project", "subagents", "of a stack type", "ctx (hook unit)", "fresh",
                   "cache-read share", "API calls", "state"]))
    P(f"\nIncluded: every session transcript under `~/.claude/projects/` ({len(sess)}). Both ran this stack's "
      "agents (every subagent's `.meta.json` `agentType` is a stack type; the stack's state folder "
      "`~/.local/state/claude-agent-stack/<session>/` exists with `budget.json` and `delegations.md` for both). "
      "The stack repo's own folder under `~/.claude/projects/` holds only `memory/` (no transcript). Two "
      "more stack state folders (17b4b227, 67b92311) hold only lock files and no transcript exists: not usable.\n")
    P(f"Segments: {len(seg)} ({len(fin)} finished, {int(seg.open.sum())} still running and excluded), from "
      f"{len(run)} subagents. Problem segments (compacted or turn-limited): {int(fin.problem.sum())}; "
      f"continuations after a turn limit: {int(fin.after_limit.sum())}. Healthy: {len(H)}.\n")

    # ---- current hook
    P("## Current hook budgets (agent_guard.py, settings.json)\n")
    P("- Unit: context tokens = `input + cache_creation + cache_read` of every API call (output excluded), "
      "counted cumulatively over the whole session tree (main transcript + every `subagents/agent-*.jsonl`), "
      "incrementally via `budget.json` offsets; calls deduplicated by `(message.id, requestId)`.\n"
      "- `STACK_PROMPT_CTX_BUDGET=100000000` (100M): tokens since the last prompt boundary. The boundary is "
      "set at UserPromptSubmit and also whenever a main-thread tool call carries a `prompt_id` not seen "
      "before (`budget_note_prompt`); task notifications carry their own promptId in the transcript, so the "
      "effective window can restart on a notification turn (inferred from code + transcripts; unverified "
      "against a live hook log).\n"
      "- `STACK_SESSION_CTX_BUDGET=666000000` (666M): whole session.\n"
      "- Both are HARD: once spent, every tool call of every agent is denied except reporting/stopping tools "
      "(SubagentHandback, TaskStop, AskUserQuestion) and Write/Edit under `.claude-work/` or the scratchpad. "
      "They fail open (unreadable transcript = allowed). `0` disables. Both are OWNED_ENV in install.sh: a "
      "value raised in `~/.claude/settings.json` holds until the next install.\n"
      "- No per-agent token budget exists. Per agent there is only `STACK_MAX_MCP_CALLS=64` MCP calls per "
      "spawn/resume (min with the type's maxTurns), hard, and Claude Code's own `maxTurns` (frontmatter, hard: "
      "the run stops).\n")

    # ---- unit choice
    P("## Which unit separates healthy from runaway\n")
    rows = []
    for u in ("ctx", "fresh", "api_calls", "tool_calls", "peak", "rereads"):
        r = fin[u] / fin.groupby("type")[u].transform(lambda s: s[~fin.loc[s.index, "problem"]].median() or 1)
        rr = run[~run.open]
        rr = rr.assign(problem=rr.turn_limit | (rr.compactions > 0))
        rn = rr[u] / rr.groupby("type")[u].transform(lambda s: s[~rr.loc[s.index, "problem"]].median() or 1)
        rows.append([u, f"{auc(fin[u][fin.problem], fin[u][~fin.problem]):.3f}",
                     f"{auc(r[fin.problem], r[~fin.problem]):.3f}",
                     f"{auc(rn[rr.problem], rn[~rr.problem]):.3f}"])
    P(table(rows, ["unit", "AUC per segment, raw", "AUC per segment, / type median", "AUC per run (all segments), / type median"]))
    P(f"\nAUC = P(a problem segment's value > a healthy one's); problem = compacted or turn-limited "
      f"({int(fin.problem.sum())} segments), markers that do not depend on the token units. Within a type "
      "(the `/ type median` column, which removes the scale difference between a scout and a builder), "
      "cumulative context (`ctx`) and API calls separate best; fresh tokens and peak context separate worse "
      "because cache creation saturates (a long run re-reads a context of ~200-400k, it does not create much "
      "more). Per segment beats per run: the orchestrator and resumed builders accumulate many healthy "
      "segments, and a per-run count would trip them for being long-lived, not for running away. Chosen unit: "
      "**`ctx` per segment** (spawn or resume), which is also the hook's existing unit and the reset rule of "
      "the MCP cap, so the builder needs per-file counters only.\n")
    rr = H.groupby("type").rereads.median()
    P("Re-reads (cache_read / peak context): healthy medians per type " +
      ", ".join(f"{t} {v:.0f}x" for t, v in rr.sort_values(ascending=False).items()) +
      "; problem segments " + ", ".join(f"{r.name.split(' [')[0][:20]} {r.rereads:.0f}x" for r in fin[fin.problem].itertuples()) +
      ". A runaway is a long context re-read 90-160 times; cache reads are cheap per token but are 96-97% of "
      "all tokens here, so they are what a cumulative limit actually limits.\n")

    # ---- per-agent soft limits
    P("## Per-agent soft limit (ctx per segment)\n")
    P("Rule: soft = p90(healthy) x m, m the smallest of 1.25..1.5 (step 0.05) with false trips <= 5% (else the "
      "lowest), floor 2 x median, rounded up to 2 significant figures. A type is derived from its own runs when it "
      "has >= 5 healthy segments from >= 3 distinct agents; otherwise from its comparable-type pool (TIER in the "
      "script). `catch`: soft / healthy median; <= 3 means every segment above 3x the median trips. "
      "Problem segments caught = problem segments of that type above the soft limit. p90 CI = bootstrap 90% "
      "(4,000 resamples).\n")
    rows, derived, uncapped = [], {}, []
    types = sorted(set(fin.type) | set(mt))
    def own_ok(t):
        h = H[H.type == t]
        return len(h) >= 5 and h.id.nunique() >= 3
    pools = {}
    for tier, members in TIER.items():
        mem = members.split()
        h = H[H.type.isin(mem)]
        if len(h) >= 5 and h.id.nunique() >= 3:
            pools[tier] = derive(h[UNIT].values, h.name.tolist())
            pools[tier]["src"] = h
    for t in sorted(set(fin.type)):
        h = H[H.type == t]
        tier = TIER_OF.get(t, "other")
        pb = fin[(fin.type == t) & (fin.problem | fin.after_limit)]
        own = derive(h[UNIT].values, h.name.tolist()) if own_ok(t) else None
        if own is not None and own["ft"] <= FT_REJECT:
            d = own; src = "own"
            sup = "well" if len(h) >= 10 and h.id.nunique() >= 5 else "provisional"
        elif tier in pools:
            d = dict(pools[tier])
            src = (f"pool:{tier} (own {M(own['soft'])} rejected: {100*own['ft']:.0f}% false trips)"
                   if own is not None else f"pool:{tier}")
            sup = "provisional (pooled)"
            # false trips of this type's own healthy runs against the pooled limit
            d["ft"] = float((h[UNIT] > d["soft"]).mean()) if len(h) else np.nan
            d["tripped"] = h[h[UNIT] > d["soft"]].name.tolist()
            d["ci"] = (np.nan, np.nan)
        else:
            uncapped.append([t, f"{len(h)} / {h.id.nunique()}", M(h[UNIT].median()), M(h[UNIT].quantile(.9)),
                             M(h[UNIT].max())])
            continue
        derived[t] = d
        caught = f"{int((pb[UNIT] > d['soft']).sum())}/{len(pb)}" if len(pb) else "-"
        tr = "; ".join(x.split(" [")[0] for x in d["tripped"]) or "none"
        mx_all = fin[fin.type == t][UNIT].max()
        rows.append([t, src, f"{len(h)} / {h.id.nunique()}", M(h[UNIT].median()), M(h[UNIT].quantile(.9)),
                     f"{M(d['ci'][0])}-{M(d['ci'][1])}" if src == "own" else "(see pool row)",
                     f"**{M(d['soft'])}**", f"{d['m']:.2f}" + (" floor" if d["floor"] else ""),
                     f"{100*d['ft']:.0f}%" if np.isfinite(d["ft"]) else "-", tr,
                     f"{mx_all/d['soft']:.2f}x ({M(mx_all)})", f"{d['soft']/max(h[UNIT].median(),1):.1f}x", caught, sup])
    for tier, d in pools.items():
        h = d["src"]
        rows.append([f"*{tier} pool* (unobserved types)", "pool", f"{len(h)} / {h.id.nunique()}", M(d["median"]), M(d["p90"]),
                     f"{M(d['ci'][0])}-{M(d['ci'][1])}", f"**{M(d['soft'])}**", f"{d['m']:.2f}",
                     f"{100*d['ft']:.0f}%", "; ".join(x.split(" [")[0] for x in d["tripped"]) or "none",
                     f"{h[UNIT].max()/d['soft']:.2f}x", f"{d['soft']/d['median']:.1f}x", "-", "provisional"])
    P(table(rows, ["type", "derived from", "n healthy seg / agents", "median", "p90", "p90 CI", "soft",
                   "m", "false trips", "tripped (healthy)", "max / soft", "catch (soft/median)",
                   "problem segs caught", "support"]))
    P("\n`max / soft` > 1 means the observed maximum of that type (problem segments included) is above the "
      "limit, i.e. the limit would have fired on it; the headroom of healthy runs is `1 / (max healthy / soft)`. "
      "Unobserved types inherit their pool (TIER): " + "; ".join(
          f"{k}: {', '.join(t for t in v.split() if t not in derived)}" for k, v in TIER.items()
          if k in pools and any(t not in derived for t in v.split())) +
      ". Types with no usable data (fewer than 5 healthy segments from 3 agents, and no pool) stay uncapped: " +
      (", ".join(sorted(t for t in mt if t not in derived and TIER_OF.get(t) not in pools and t != "blackcat")) or "none") +
      " (blackcat is the main thread, covered by the per-prompt limit).\n")
    if uncapped:
        P("Uncapped (observed, but too few distinct agents and no comparable pool):\n")
        P(table(uncapped, ["type", "n healthy seg / agents", "median", "p90", "max"]))
        P("\nThe orchestrator's segments are short relays (1-14 API calls); its cost is in its children, which "
          "their own limits cover. Its two runs differ by ~2x (leave-one-session-out below), so a limit from them "
          "would be a guess.\n")
    for t, d in derived.items():
        h = H[H.type == t]
        if d["ft"] > FT_REJECT and len(h):
            P(f"Note on {t}: {100*d['ft']:.0f}% false trips = {len(d['tripped'])} of {len(h)} healthy segments; with "
              f"n = {len(h)} one trip is already {100/len(h):.0f}%, and any limit below the type's maximum "
              f"({M(h[UNIT].max())}) trips it. The tripped segment ({'; '.join(d['tripped'])}) also exceeds the "
              f"worktree maxTurns ({mt.get(t)}) in API calls, so the hard cap would stop it anyway; the pooled value "
              "is kept rather than a limit at the maximum that would catch nothing.\n")

    # descriptive per type
    P("Per type, all finished segments (problem ones included): n, then median / p90 / max:\n")
    rows = []
    for t, g in fin.groupby("type"):
        f3 = lambda c, k=M: " / ".join(k(v) for v in (g[c].median(), g[c].quantile(.9), g[c].max()))
        n3 = lambda c: " / ".join(f"{v:.0f}" for v in (g[c].median(), g[c].quantile(.9), g[c].max()))
        rows.append([t, len(g), g.id.nunique(), f3("fresh"), f3("ctx"), n3("api_calls"), n3("tool_calls"),
                     f"{g.rereads.median():.0f} / {g.rereads.max():.0f}"])
    P(table(rows, ["type", "segments", "agents", "fresh", "ctx (cumulative)", "API calls (turns)", "tool calls",
                   "rereads median / max"]))
    P("")

    # problem segment detail
    pr = fin[fin.problem | fin.after_limit].sort_values(UNIT, ascending=False)
    P("Problem and after-limit segments vs their limit:\n")
    P(table([[r.name, r.type, r.api_calls, M(getattr(r, UNIT)), r.compactions, "yes" if r.turn_limit else "",
              f"{getattr(r, UNIT)/derived[r.type]['soft']:.1f}x" if r.type in derived else "-",
              f"{getattr(r, UNIT)/H[H.type == r.type][UNIT].median():.1f}x" if (H.type == r.type).any() else "-"]
             for r in pr.itertuples()],
            ["segment", "type", "API calls", "ctx", "compactions", "turn limit", "ctx / soft", "ctx / healthy median"]))

    # ---- robustness: leave one session out
    P("\n### Robustness: leave one session out\n")
    rows = []
    sids = list(sess.session)
    for t in sorted(set(H.type)):
        for s_tr in sids:
            tr_ = H[(H.type == t) & (H.session == s_tr)]
            te_ = H[(H.type == t) & (H.session != s_tr)]
            if len(tr_) >= 3 and len(te_) >= 1:
                d = derive(tr_[UNIT].values, tr_.name.tolist())
                rows.append([t, sh(s_tr), len(tr_), M(d["soft"]), M(derived[t]["soft"]) if t in derived else "-",
                             len(te_), f"{100*(te_[UNIT] > d['soft']).mean():.0f}%"])
    P(table(rows, ["type", "derived on session", "n", "soft (that session)", "soft (pooled, table)", "n other session", "false trips in other session"]))
    P("\nWhere the two sessions disagree the pooled table value is the better estimate; the spread is the honest "
      "uncertainty of the per-type limits.\n")

    # ---- prompt and session
    P("## Whole-prompt and session soft limits (ctx, whole session tree)\n")
    hp = pw[pw.kind == "human"].copy(); hk = pw[pw.kind == "hook"]
    names = (hp.session.map(sh) + " #" + hp.i.astype(str) + " " + hp.start + " " + hp.prompt.str[:40]).tolist()
    dp = derive(hp[UNIT].values, names)
    dk = derive(hk[UNIT].values, [""] * len(hk))
    sv = sess[UNIT].values
    ds = dict(n=len(sv), median=q(sv, .5), p90=q(sv, .9), max=float(sv.max()))
    ds["soft"] = ceil2(ds["p90"] * 1.25)
    P(table([
        ["per human prompt (UserPromptSubmit to next)", f"{dp['n']} prompts / {len(sess)} sessions", M(dp["median"]), M(dp["p90"]),
         f"{M(dp['ci'][0])}-{M(dp['ci'][1])}", f"**{M(dp['soft'])}**", f"{dp['m']:.2f}", f"{100*dp['ft']:.1f}%",
         f"{dp['max']/dp['soft']:.2f}x ({M(dp['max'])})", "provisional (2 sessions)"],
        ["per hook window (as the hook counts today)", f"{dk['n']}", M(dk["median"]), M(dk["p90"]),
         f"{M(dk['ci'][0])}-{M(dk['ci'][1])}", M(dk["soft"]), f"{dk['m']:.2f}", f"{100*dk['ft']:.1f}%",
         f"{dk['max']/dk['soft']:.2f}x", "reference only"],
        ["per session", f"{ds['n']} (one live)", M(ds["median"]), M(ds["p90"]), "n too small", f"**{M(ds['soft'])}** (provisional)",
         "1.25", "0%", f"{ds['max']/ds['soft']:.2f}x ({M(ds['max'])})", "insufficient (n=2)"],
    ], ["scope", "n", "median", "p90", "p90 CI", "soft", "m", "false trips", "max / soft", "support"]))
    P("\nPrompts above the per-prompt soft limit (all are legitimate multi-agent jobs, so every one is a false "
      "trip by construction; the soft limit's job there is to ask before continuing), with the moment it would "
      "have fired:\n")
    rows = []
    for r in hp[hp[UNIT] > dp["soft"]].sort_values(UNIT, ascending=False).itertuples():
        k = int(np.searchsorted(r.cumctx, dp["soft"], side="right"))
        when = r.callts[k][11:16] if k < len(r.callts) else "-"
        rows.append([sh(r.session), r.i, r.start, r.prompt[:48], M(r.ctx), M(r.fresh), when + " UTC",
                     f"{100*dp['soft']/r.ctx:.0f}%"])
    P(table(rows, ["session", "#", "start UTC", "prompt", "ctx", "fresh", "would warn at", "share done at warning"]))
    P(f"\nThe prompt distribution is a mixture: short questions (median {M(dp['median'])}) and dispatched jobs. "
      f"`3 x median` ({M(3*dp['median'])}) is therefore not a runaway marker for prompts; the soft limit sits at "
      f"{dp['soft']/dp['median']:.0f}x the median and fires only on the multi-phase jobs above. The session row "
      f"has n = {ds['n']} (one session still running): p90 x 1.25 of two values is not a distribution estimate. "
      "Keep the hard 666M as is and treat the session soft value as provisional until >= 5 sessions exist; the "
      "per-prompt and per-segment limits do the real work.\n")

    # this session
    P("### What this session would have tripped\n")
    me = fin[(fin.session == THIS_SESSION) & fin.type.isin(derived)]
    trip = me[me.apply(lambda r: r[UNIT] > derived[r.type]["soft"], axis=1)]
    P(table([[r.name.split(" [")[0], r.type, M(getattr(r, UNIT)), M(derived[r.type]["soft"]),
              "problem" if r.problem or r.after_limit else "healthy"] for r in trip.sort_values(UNIT, ascending=False).itertuples()],
            ["segment", "type", "ctx", "soft", "class"]))
    tot = float(sess[sess.session == THIS_SESSION][UNIT].iloc[0]) if (sess.session == THIS_SESSION).any() else np.nan
    P(f"\nPrompts: see the table above (session {sh(THIS_SESSION)} rows). Session total so far {M(tot)} vs the "
      f"provisional session soft {M(ds['soft'])} and hard 666M. Phase totals from `report.md` (subagents by "
      "label, cumulative incl. output): Phase 1 61.9M, Phase 2 159.5M, Phase 3 108.6M; each phase spans several "
      "prompts, so the per-prompt limit fires on the prompt that dispatched the phase (#1 Phase 1, #3 Phase 2), "
      "while Phase 3 was spread over many smaller prompts and the per-segment limits are what flag it.\n")

    # ---- benchmark
    P("## Benchmark runs\n")
    P(f"The planned full run is ~{M(BENCH_EST)} tokens (estimate in `agents-bench/dry-run-output.txt`, range "
      "x0.5-x2), spread over 102 separate `claude -p` sessions (17 tasks x 3 reps x 2 arms), each with its own "
      "`CLAUDE_CONFIG_DIR` and `XDG_STATE_HOME` (`run_bench.py`). Per session that is ~0.5M (<= 1M at x2), far "
      "below every prompt or session limit, so the aggregate cannot trip them. What can interfere is the "
      "per-segment soft limit inside a run: a non-interactive `claude -p` cannot answer the ask, so a soft trip "
      "becomes a STATUS: partial and a quality loss in one arm only (the old arm, 75dfdfc, has no soft limits). "
      "Scope it per run: `run_bench.py` builds each run's env (lines 142-143); add the soft-limit switch there "
      "(e.g. `STACK_SOFT_LIMIT_SCALE=0` to turn soft limits off, or a factor such as 2) so both arms run under "
      "the same rules, and record it in the result JSON. Hard caps stay on in both arms. Whether a process env "
      "var overrides the installed `settings.json` env block is unverified: the builder should test it with "
      "one `claude -p` run, or the harness can write the value into each arm's `config/settings.json` env "
      "after install.\n")

    # ---- verifier maxTurns
    P("## Verifier maxTurns\n")
    v = fin[fin.type == "verifier"].copy()
    v["job"] = np.where(v.desc.str.contains("harness|benchmark", case=False), "build", "verify")
    vv = v[(v.job == "verify") & ~v.after_limit & ~v.turn_limit]
    dv = derive(vv.api_calls.values, vv.name.tolist(), hard=True)
    b = v[v.job == "build"]
    P(table([[r.name.split(" [")[0], sh(r.session), r.job, r.api_calls, r.tool_calls, M(r.ctx),
              "yes" if r.turn_limit else ""] for r in v.sort_values("api_calls").itertuples()],
            ["segment", "session", "job", "API calls", "tool calls", "ctx", "turn limit"]))
    bt = int(b.api_calls.sum())
    P("\n" + table([["verifier (verification jobs)", "API calls per segment", dv["n"], f"{dv['median']:.0f}",
                     f"{dv['p90']:.1f}", f"{dv['ci'][0]:.0f}-{dv['ci'][1]:.0f}", f"{int(dv['soft'])}", "1.50 (hard cap: top of band)",
                     f"{100*dv['ft']:.0f}%", f"{dv['soft']/dv['max']:.2f}x over max {dv['max']:.0f}",
                     f"build job {bt} = {bt/dv['median']:.1f}x median", "provisional (n=6)"]],
                   ["type", "unit", "n", "median", "p90", "p90 CI", "maxTurns from data", "m", "false trips",
                    "headroom", "runaway", "support"]))
    P(f"\nThe maxTurns count is exact: the harness segment stopped at {int(b.api_calls.max())} API calls = the "
      f"installed maxTurns 150, then needed {bt - int(b.api_calls.max())} more after a resume. Verification jobs "
      f"run {int(vv.api_calls.min())}-{int(vv.api_calls.max())} calls (median {dv['median']:.0f}); the harness build "
      f"({bt} calls) is {bt/dv['median']:.1f}x that median and {bt/dv['max']:.2f}x the longest verification, a "
      f"different job. Data-derived cap: p90 {dv['p90']:.1f} x 1.5 = {int(dv['soft'])}. The current worktree value "
      f"{mt.get('verifier')} is {mt.get('verifier', 0)/dv['p90']:.2f}x p90, within {abs(mt.get('verifier', 0)-dv['soft'])/dv['soft']*100:.0f}% "
      "of the derived value, which is below the resolution of n = 6 (p90 CI above): **keep 140**; do not raise it "
      "for the build job. Prompt note for the verifier (and for dispatchers): *a verifier verifies; building a "
      "harness, fixture or tool is a builder's job (coder / claude-code-engineer), or split it into separate "
      "dispatches (set up, dry run, verify) of <= ~90 calls each.*\n")
    rows = []
    for t in sorted(set(fin.type)):
        x = fin[fin.type == t].api_calls
        if t in mt:
            over = fin[(fin.type == t) & (fin.api_calls > mt[t])]
            rows.append([t, mt[t], int(x.max()), f"{x.quantile(.9):.0f}", len(over),
                         "; ".join(over.name.str.split(" \\[").str[0]) or "-"])
    P("maxTurns vs observed API calls per segment (worktree frontmatter; data were produced under the installed, "
      "partly higher values):\n")
    P(table(rows, ["type", "maxTurns (worktree)", "max observed", "p90 observed", "segments above", "which"]))

    # ---- soft semantics
    P("\n## Soft semantics for the builder\n")
    P("- At the threshold: inject a warning (PreToolUse `additionalContext` or a deny of the next non-reporting "
      "call with a reason) telling the agent to wrap up: finish the current step, return `STATUS: partial` with "
      "what is done and what remains, and ASK its caller (subagent) or the user (main thread) before continuing. "
      "Fire once per segment (per prompt for the prompt limit); a resume or an explicit go-ahead starts a new "
      "allowance.\n"
      "- Counters: per-agent = `ctx` of that agent's transcript since its current run's `started` stamp (same "
      "reset rule as `mcp-calls/<agent_id>.json`); per-prompt = since UserPromptSubmit only (human prompts), not "
      "on task-notification prompt_ids.\n"
      "- One documented env var raises them all: `STACK_SOFT_LIMIT_SCALE` (float, default 1; 2 = double every "
      "soft limit; 0 = soft limits off). Optional per-type override in the style of STACK_MAX_FANOUT_BY_TYPE.\n"
      "- Hard caps are unchanged and never weakened: STACK_PROMPT_CTX_BUDGET 100M, STACK_SESSION_CTX_BUDGET 666M, "
      "STACK_MAX_MCP_CALLS 64, maxTurns. Every soft value in this file is below its hard counterpart.\n"
      "- Fail open like the existing budgets.\n")

    # ---- models
    P("## Models measured\n")
    seen = sorted(((n, str(k)) for k, n in MODELS.items() if k and not str(k).startswith("<")), reverse=True)
    P("API calls per model: " + (", ".join(f"{k} {n}" for n, k in seen) or "none") + ".\n")
    rec = re.search(r'(?m)^MEASURED_MODELS="([^"]*)"', open(DOCTOR, encoding="utf-8").read())
    rec = dict(x.split("=", 1) for x in (rec.group(1).split() if rec else []) if "=" in x)
    top = {fam: next((k for _, k in seen if f"-{fam}-" in k), None) for fam in ("opus", "sonnet")}
    stale = {fam: (rec.get(fam), top[fam]) for fam in top if top[fam] and rec.get(fam) != top[fam]}
    P("`MEASURED_MODELS` in `dot-claude/bin/doctor.sh`: " + (" ".join(f"{k}={v}" for k, v in rec.items()) or "missing")
      + (". Matches the most-used model of each family.\n" if not stale else
         ". Update it with the values you adopt from this run: " + ", ".join(
             f"{fam} recorded {a}, most used here {b}" for fam, (a, b) in stale.items()) + ".\n"))

    # ---- refresh
    P("## Refresh and revisit\n")
    P("`uv run --script tests/derive_thresholds.py` (in the stack repo) "
      "regenerates every number here. Re-derive when the healthy segment count of a type, or the number of "
      "sessions, doubles, and after any major stack change (agent prompts, skills loading, models, maxTurns). "
      "Today's counts: " + ", ".join(f"{t} {n}" for t, n in H.type.value_counts().items()) + f"; sessions {len(sess)}.\n")
    P("## Limitations\n")
    P("- Two sessions, one day, one user: per-type values are provisional except where marked well; the session "
      "limit is not estimable.\n- `healthy` = not compacted and not turn-limited; a long but legitimate segment "
      "without compaction counts as healthy, so false-trip rates are upper bounds on harm.\n- Live session: the "
      "running agents (including this analysis) are excluded; totals of the live session grow.\n- Thresholds are "
      "in-sample; the leave-one-session-out table is the only out-of-sample check.\n")
    return "\n".join(o) + "\n"


if __name__ == "__main__":
    main()
