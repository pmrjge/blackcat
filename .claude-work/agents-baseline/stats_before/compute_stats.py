# /// script
# requires-python = ">=3.12"
# dependencies = ["numpy==2.3.3"]
# [tool.uv]
# exclude-newer = "2026-10-01T00:00:00Z"
# ///
"""BEFORE statistics of the agent-stack baseline (pre-Bayesian), from the frozen inputs only.

  uv run --script compute_stats.py            # writes stats_before.json, stats_before.md, runs_before.csv next to this file
  uv run --script compute_stats.py --check    # also verifies inputs/MANIFEST.sha256 first (exit 1 on mismatch)

Deterministic: no wall-clock values in the outputs; every bootstrap draws from
numpy.random.default_rng(SEED ^ sha256(group key | metric)[:8]), so adding a group never changes another.
Reads ONLY ./inputs/ (frozen copies; see inputs/FROZEN_AT.txt and inputs/MANIFEST.sha256).
"""
import csv
import hashlib
import json
import math
import os
import re
import sys
from collections import Counter, defaultdict

import numpy as np

SCHEMA_VERSION = "1.0.0"
SEED = 20261003
B = 10000
MIN_N_CI = 5            # bootstrap CIs only for n >= 5; below that the CI is null (reason recorded)
Z = 1.959963984540054   # two-sided 95 % normal quantile for Wilson intervals

HERE = os.path.dirname(os.path.abspath(__file__))
INP = os.path.join(HERE, "inputs")
SESSIONS = {
    "4e2da3ce-e2f4-4971-aac5-a67f2dcf252e": ("old_install", os.path.join(INP, "baseline")),
    "fae82d02-7bf7-4439-9024-17b07cace5cc": ("new_install", os.path.join(INP, "collected_fae82d02")),
}
# campaign window for T-overhead in the new session (collector's own 'overhead' kind needs \bT\d+\b, which misses 'T8b');
# the old session uses the collector's kind == 'overhead' (window = first 'baseline campaign' dispatch).
CAMPAIGN_SINCE = {"fae82d02-7bf7-4439-9024-17b07cace5cc": "2026-10-03T11:05:00Z"}
GRADE_FILES = [os.path.join(INP, "baseline", "grades.csv"), os.path.join(INP, "baseline", "grades_T8b.csv")]
PROMPTS = os.path.join(INP, "baseline", "prompts.csv")
USAGE = {"4e2da3ce-e2f4-4971-aac5-a67f2dcf252e": os.path.join(INP, "usage_live", "runs_schema1.csv"),
         "fae82d02-7bf7-4439-9024-17b07cace5cc": os.path.join(INP, "usage_live", "runs3.csv")}
GRADES = ("pass", "partial", "fail", "tool-absent")
STATUSES = ("done", "partial", "blocked", "none")
METRICS = ("tokens_total", "tokens_fresh", "tokens_input", "tokens_output", "tokens_cache_creation",
           "tokens_cache_read", "tool_calls", "turns", "duration_s", "agent_wall_s", "spawn_count")
HEADLINE_METRICS = ("tokens_total", "tokens_fresh", "tool_calls", "turns", "duration_s")
NEVER_RUN_HELD = {"P01": "blackcat target; needs a fresh main session", "P02": "blackcat target; needs a fresh main session",
                  "P22": "needs user consent (third-party MCP)", "P87": "needs user consent (paid image-studio)",
                  "P89": "MLX benchmark, must run alone; not dispatched before STOP",
                  "P97": "git init blocked under .claude-work (user decision)"}

DEFINITIONS = {
    "run": "One prompt execution = (session, prompt_id, variant). All collector segments whose prompt_id tag matches "
           "(root dispatch, its resumes and every descendant agent) belong to the run.",
    "variant": "Parsed from the root dispatch description '<PID> <variant> run ...': v2 = re-run on the NEW install's "
               "dedicated agent; r2 = replicate (batch X, never dispatched); no token = v1.",
    "install": "old_install = session 4e2da3ce (installed ~/.claude lacking 19 corpus agents; fallbacks used); "
               "new_install = session fae82d02 (new install, dedicated agents present).",
    "agent_type": "Root agent type of the run; 'orchestrated' when the run has more than one distinct root agent type (P90).",
    "fallback": "1 when the root agent_type is not among the prompt's target_agent alternatives ('X or Y', 'X (or Y)').",
    "tokens_total": "Sum over the run's segments of input + output + cache_creation + cache_read tokens (collector).",
    "tokens_fresh": "tokens_total - tokens_cache_read (input + output + cache_creation).",
    "tool_calls": "Sum of tool_use blocks over the run's segments (collector 'tool_calls').",
    "turns": "Sum of distinct API calls over the run's segments (collector 'turns').",
    "duration_s": "Elapsed wall clock of the run: max(segment end) - min(segment start), seconds (includes waits between "
                  "resumes and children).",
    "agent_wall_s": "Sum of the segments' wall_s (agent-seconds, double-counts parallel children).",
    "spawn_count": "Sum of Agent tool calls made inside the run.",
    "cost_usd": "NOT RECORDED in any input (no price or cost column). Reported as missing; tokens are the only cost proxy. "
                "No price table is applied here because prices are external and unverified in this job.",
    "grade": "Grader verdict from grades.csv (T8a, 22 ids) + grades_T8b.csv (T8b, 18 ids): pass | partial | fail | "
             "tool-absent. Grades exist ONLY for old_install v1 runs. Any other run is 'ungraded'.",
    "grade_rates": "k/n with n = graded runs in the group (tool-absent INCLUDED in n); Wilson score 95 % interval. "
                   "pass_rate_excl_tool_absent uses n = graded runs minus tool-absent.",
    "quality_score": "pass = 1, partial = 0.5, fail = 0, tool-absent = 0 (secondary; used only for descriptive Pareto points).",
    "grader_reexecuted": "1 when the grade note says the grader re-ran or recomputed something (regex re-?ran|recomputed|"
                         "reproduced|matches grader); grader_blocked = 1 when it says the re-run was blocked or not done.",
    "final_status": "STATUS value of the run's final report (last-ending root segment), collector regex "
                    "'^\\W*STATUS:\\s*(done|partial|blocked)' case-insensitive; 'none' = no STATUS line.",
    "status_line_strict": "Final report has a line starting (after non-word chars such as ``` or **) with upper-case 'STATUS:' "
                          "followed by done|partial|blocked.",
    "status_block_complete": "status_line_strict AND lines starting with upper-case RESULT, EVIDENCE and FILES (NEXT optional).",
    "clean_header": "First non-empty line matches '<input> · <YYYY-MM-DD[ HH:MM]> · <agent type>' (U+00B7 separators), "
                    "the clean-finish header of the current rules (dot-claude/rules/claude-agent-stack.md, added in commit "
                    "18b8da1 on 2026-10-02 14:22 +0100; whether the OLD install carried it is unverified).",
    "format_class": "status_block (strict STATUS line, no header) | clean_header (header, no STATUS line) | both | neither | "
                    "missing (no final report file).",
    "compliant_current_rule": "format_class == clean_header, or format_class == status_block with status_block_complete.",
    "compliant_legacy": "status_line_strict present (the STATUS-only convention).",
    "deviations": "Per-run list: neither_format, both_formats, status_block_incomplete(missing fields), header_agent_mismatch, "
                  "header_template_literal ('<input:' copied), header_input_over_10_words, fallback_agent.",
    "overclaim": "Graded run whose final_status is done (or clean_header) but grade is partial|fail|tool-absent.",
    "underclaim": "Graded run whose final_status is partial|blocked but grade is pass.",
    "quantiles": "numpy.percentile method 'linear' (Hyndman-Fan type 7). IQR = q75 - q25; p90 = 90th percentile.",
    "bootstrap": f"Percentile bootstrap, B = {B}, resampling runs with replacement within the group; CI for mean and median; "
                 f"only when n >= {MIN_N_CI}.",
    "pareto": "Descriptive only. A point is non-dominated if no other point is at least as good on every objective and "
              "strictly better on one. Objectives: minimise median tokens_total, maximise pass rate (2-D); plus minimise "
              "median duration_s (3-D). Agent-type points are confounded by task mix; no design recommendation is made.",
    "overhead": "Root dispatches whose description starts with T<digits>[letter] (grading, collection) inside the campaign "
                "window; excluded from every run statistic.",
}


def sha256_file(p):
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        for b in iter(lambda: fh.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def load_csv(p):
    with open(p, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def num(x):
    if x is None or x == "":
        return None
    try:
        v = float(x)
    except ValueError:
        return None
    return v


def ts(x):
    import datetime as dt
    return dt.datetime.fromisoformat(x.replace("Z", "+00:00")).timestamp()


def wilson(k, n):
    if n == 0:
        return {"k": k, "n": 0, "p": None, "lo": None, "hi": None}
    p = k / n
    den = 1 + Z * Z / n
    c = (p + Z * Z / (2 * n)) / den
    h = Z * math.sqrt(p * (1 - p) / n + Z * Z / (4 * n * n)) / den
    return {"k": k, "n": n, "p": round(p, 4), "lo": round(max(0.0, c - h), 4), "hi": round(min(1.0, c + h), 4)}


def rng_for(*key):
    d = hashlib.sha256("|".join(map(str, key)).encode()).digest()
    return np.random.default_rng(SEED ^ int.from_bytes(d[:8], "big"))


def rnd(x, k=4):
    return None if x is None else (round(float(x), k) if isinstance(x, (float, np.floating)) else x)


def summarize(vals, key):
    v = np.array([x for x in vals if x is not None], dtype=float)
    out = {"n": int(v.size), "n_missing": int(sum(1 for x in vals if x is None))}
    if v.size == 0:
        out.update(dict.fromkeys(("mean", "median", "q25", "q75", "iqr", "p90", "min", "max", "sd",
                                  "mean_ci95", "median_ci95"), None))
        return out
    q25, q50, q75, q90 = np.percentile(v, [25, 50, 75, 90], method="linear")
    out.update(mean=rnd(v.mean(), 2), median=rnd(q50, 2), q25=rnd(q25, 2), q75=rnd(q75, 2), iqr=rnd(q75 - q25, 2),
               p90=rnd(q90, 2), min=rnd(v.min(), 2), max=rnd(v.max(), 2),
               sd=rnd(v.std(ddof=1), 2) if v.size > 1 else None)
    if v.size >= MIN_N_CI:
        idx = rng_for(*key).integers(0, v.size, size=(B, v.size))
        bs = v[idx]
        means, meds = bs.mean(axis=1), np.median(bs, axis=1)
        out["mean_ci95"] = [rnd(np.percentile(means, 2.5), 2), rnd(np.percentile(means, 97.5), 2)]
        out["median_ci95"] = [rnd(np.percentile(meds, 2.5), 2), rnd(np.percentile(meds, 97.5), 2)]
    else:
        out["mean_ci95"] = out["median_ci95"] = None
        out["ci_note"] = f"n < {MIN_N_CI}: no bootstrap CI"
    return out


# ---------------------------------------------------------------- final-report format parsing
STATUS_LOOSE = re.compile(r"^\W*STATUS:\s*(done|partial|blocked)\b", re.IGNORECASE | re.MULTILINE)
STATUS_STRICT = re.compile(r"^\W*STATUS:\s*(done|partial|blocked)\b", re.MULTILINE)
FIELD = {f: re.compile(rf"^\W*{f}\b", re.MULTILINE) for f in ("RESULT", "EVIDENCE", "FILES")}
HEADER = re.compile(r"^(?P<inp>.+?) · (?P<date>\d{4}-\d{2}-\d{2})(?: (?P<time>\d{2}:\d{2}))? · (?P<agent>[A-Za-z0-9_-]+)\s*$")


def parse_report(text, agent_type):
    if text is None:
        return {"format_class": "missing", "status_line_strict": None, "status_block_complete": None,
                "clean_header": None, "compliant_current_rule": None, "compliant_legacy": None, "fmt_deviations": []}
    lines = [ln for ln in text.splitlines() if ln.strip()]
    first = lines[0].strip().strip("`*").strip() if lines else ""
    hm = HEADER.match(first)
    strict = STATUS_STRICT.search(text)
    missing = [f for f, rx in FIELD.items() if not rx.search(text)]
    complete = bool(strict) and not missing
    dev = []
    if hm and strict:
        cls = "both"
        dev.append("both_formats")
    elif hm:
        cls = "clean_header"
    elif strict:
        cls = "status_block"
        if missing:
            dev.append("status_block_incomplete(" + ",".join(missing) + ")")
    else:
        cls = "neither"
        dev.append("neither_format")
    if hm:
        if hm.group("agent") != agent_type:
            dev.append("header_agent_mismatch")
        if hm.group("inp").lstrip().startswith("<input"):
            dev.append("header_template_literal")
        words = re.sub(r"^<input:\s*|>$", "", hm.group("inp").strip()).split()
        if len(words) > 10:
            dev.append("header_input_over_10_words")
    return {"format_class": cls, "status_line_strict": int(bool(strict)), "status_block_complete": int(complete),
            "clean_header": int(bool(hm)), "header_agent": hm.group("agent") if hm else None,
            "compliant_current_rule": int(cls == "clean_header" or (cls == "status_block" and complete)),
            "compliant_legacy": int(bool(strict)), "fmt_deviations": dev}


def target_alternatives(t):
    t = re.sub(r"\(.*?\)", lambda m: " or " + m.group(0)[1:-1].replace("or ", ""), t or "")
    return {a.strip() for a in re.split(r"\bor\b|,|/", t) if a.strip()}


# ---------------------------------------------------------------- build runs
def build_runs(prompts, grades):
    runs, overhead, segrows = {}, defaultdict(lambda: {"segments": 0, "tokens_total": 0, "roots": []}), {}
    for sid, (inst, d) in SESSIONS.items():
        rows = load_csv(os.path.join(d, "runs.csv"))
        segrows[sid] = rows
        byroot = defaultdict(list)
        for r in rows:
            if r["kind"] == "prompt":
                byroot[r["prompt_id"]].append(r)
        # overhead: T-dispatches (desc T<n>[a-z]) at depth of the campaign's dispatcher; by root description
        since = CAMPAIGN_SINCE.get(sid)
        for r in rows:
            if r["kind"] == "overhead" or (since and r["kind"] == "other" and r["is_root"] != "1"
                                           and re.match(r"^\s*T\d+[a-z]?\b", r["description"] or "")
                                           and ts(r["start"]) >= ts(since)):
                o = overhead[inst]
                o["segments"] += 1
                o["tokens_total"] += int(r["tokens_total"] or 0)
                o["roots"].append(r["description"])
        for pid, segs in byroot.items():
            roots = [s for s in segs if s["is_root"] == "1"]
            vm = None
            for s in roots:
                m = re.match(r"^\s*P\d{2,3}\s+([vr]\d+)\b", s["description"] or "")
                if m:
                    vm = m.group(1)
            variant = vm or "v1"
            rtypes = sorted({s["agent_type"] for s in roots})
            atype = rtypes[0] if len(rtypes) == 1 else "orchestrated"
            last_root = max(roots, key=lambda s: (ts(s["end"]), int(s["seg"])))
            fn = os.path.join(d, "run", pid, f"final_{last_root['agent_id']}.txt")
            text = open(fn, encoding="utf-8").read() if os.path.exists(fn) else None
            pm = prompts.get(pid, {})
            alts = target_alternatives(pm.get("target_agent", ""))
            fallback = int(atype != "orchestrated" and atype not in alts)
            g = grades.get(pid) if (inst == "old_install" and variant == "v1") else None
            tok = {k: sum(int(s[k] or 0) for s in segs) for k in
                   ("tokens_input", "tokens_output", "tokens_cache_creation", "tokens_cache_read", "tokens_total")}
            rep = parse_report(text, atype if atype != "orchestrated" else last_root["agent_type"])
            dev = list(rep.pop("fmt_deviations"))
            if fallback:
                dev.append("fallback_agent")
            why = (g or {}).get("why", "")
            run = dict(
                run_id=f"{inst}:{pid}:{variant}", session=sid, install=inst, prompt_id=pid, variant=variant,
                family=pm.get("family"), cost_class=pm.get("cost_class"), target_agent=pm.get("target_agent"),
                needs_network=pm.get("needs_network"), agent_type=atype, root_agent_types=rtypes,
                root_models=sorted({m for s in roots for m in (s["model"] or "").split(";") if m}),
                fallback=fallback, n_segments=len(segs), n_agents=len({s["agent_id"] for s in segs}),
                open_segments=sum(int(s["open"] or 0) for s in segs),
                **tok, tokens_fresh=tok["tokens_total"] - tok["tokens_cache_read"],
                turns=sum(int(s["turns"] or 0) for s in segs), tool_calls=sum(int(s["tool_calls"] or 0) for s in segs),
                duration_s=round(max(ts(s["end"]) for s in segs) - min(ts(s["start"]) for s in segs), 1),
                agent_wall_s=round(sum(float(s["wall_s"] or 0) for s in segs), 1),
                spawn_count=sum(int(s["spawn_count"] or 0) for s in segs),
                max_depth=max(int(s["depth"] or 0) for s in segs),
                tool_errors=sum(int(s["tool_errors"] or 0) for s in segs),
                tool_denied=sum(int(s["tool_denied"] or 0) for s in segs),
                sandbox_blocks=sum(int(s["sandbox_blocks"] or 0) for s in segs),
                hit_max_turns=int(any(s["hit_max_turns"] == "1" for s in segs)),
                soft_limit_hits=sum(int(s["soft_limit_hits"] or 0) for s in segs),
                compactions=sum(int(s["compactions"] or 0) for s in segs),
                skill_calls=sum(len([x for x in (s["skill_calls"] or "").split(";") if x]) for s in segs),
                expected_skills_used=sorted({x for s in roots for x in (s["expected_skills_used"] or "").split(";") if x}),
                expected_skills_missed=sorted({x for s in roots for x in (s["expected_skills_missed"] or "").split(";") if x}),
                final_status=last_root["final_status"] or "none", final_report_file=os.path.relpath(fn, HERE) if text is not None else None,
                **rep, deviations=dev,
                grade=(g or {}).get("check_result") or "ungraded",
                grader_reexecuted=int(bool(re.search(r"re-?ran|recomputed|reproduced|matches grader", why, re.IGNORECASE))) if g else None,
                grader_blocked=int(bool(re.search(r"not re-?run|not re-executed|re-?run blocked|blocked for grader|"
                                                  r"recompile blocked|grader run blocked|evidence only", why, re.IGNORECASE))) if g else None,
                cost_usd=None,
            )
            run["quality_score"] = {"pass": 1.0, "partial": 0.5, "fail": 0.0, "tool-absent": 0.0}.get(run["grade"])
            runs[run["run_id"]] = run
    return [runs[k] for k in sorted(runs)], dict(overhead), segrows


def group_summary(rs, key):
    graded = [r for r in rs if r["grade"] in GRADES]
    gc = Counter(r["grade"] for r in graded)
    ng = len(graded)
    nta = gc["tool-absent"]
    sc = Counter(r["final_status"] for r in rs)
    fc = Counter(r["format_class"] for r in rs)
    with_rep = [r for r in rs if r["format_class"] != "missing"]
    out = {
        "n_runs": len(rs),
        "run_ids": [r["run_id"] for r in rs],
        "grades": {
            "n_graded": ng, "n_ungraded": len(rs) - ng, "counts": {g: gc[g] for g in GRADES},
            "rates": {g: wilson(gc[g], ng) for g in GRADES},
            "pass_rate_excl_tool_absent": wilson(gc["pass"], ng - nta),
            "quality_score": summarize([r["quality_score"] for r in graded], key + ("quality",)),
            "grader_reexecuted": wilson(sum(r["grader_reexecuted"] for r in graded), ng),
            "grader_blocked": wilson(sum(r["grader_blocked"] for r in graded), ng),
        },
        "self_report": {"counts": {s: sc[s] for s in STATUSES}, "rates": {s: wilson(sc[s], len(rs)) for s in STATUSES}},
        "format": {
            "n_with_report": len(with_rep),
            "classes": {c: fc[c] for c in ("status_block", "clean_header", "both", "neither", "missing")},
            "status_line_strict": wilson(sum(r["status_line_strict"] for r in with_rep), len(with_rep)),
            "status_block_complete": wilson(sum(r["status_block_complete"] for r in with_rep), len(with_rep)),
            "clean_finish_rate": wilson(sum(r["clean_header"] for r in with_rep), len(with_rep)),
            "compliant_current_rule": wilson(sum(r["compliant_current_rule"] for r in with_rep), len(with_rep)),
            "compliant_legacy": wilson(sum(r["compliant_legacy"] for r in with_rep), len(with_rep)),
            "runs_with_any_deviation": wilson(sum(1 for r in rs if r["deviations"]), len(rs)),
            "deviation_counts": dict(sorted(Counter(re.sub(r"\(.*", "", d) for r in rs for d in r["deviations"]).items())),
        },
        "environment": {
            "fallback": wilson(sum(r["fallback"] for r in rs), len(rs)),
            "runs_with_sandbox_block": wilson(sum(1 for r in rs if r["sandbox_blocks"] > 0), len(rs)),
            "runs_with_tool_denied": wilson(sum(1 for r in rs if r["tool_denied"] > 0), len(rs)),
            "runs_hit_max_turns": wilson(sum(r["hit_max_turns"] for r in rs), len(rs)),
            "runs_with_soft_limit_hit": wilson(sum(1 for r in rs if r["soft_limit_hits"] > 0), len(rs)),
        },
        "metrics": {m: summarize([r[m] for r in rs], key + (m,)) for m in METRICS},
        "cost_usd": {"status": "missing", "n": 0, "reason": "no cost/price field in any input"},
    }
    return out


GROUPINGS = [("install",), ("install", "variant"), ("install", "agent_type"), ("install", "family"),
             ("install", "cost_class"), ("install", "family", "cost_class"), ("prompt_id",),
             ("install", "variant", "graded")]


def all_groups(runs):
    res = {"overall": group_summary(runs, ("overall",))}
    for gk in GROUPINGS:
        name = "by_" + "_".join(gk)
        buckets = defaultdict(list)
        for r in runs:
            rr = dict(r, graded="graded" if r["grade"] in GRADES else "ungraded")
            buckets[tuple(rr[k] for k in gk)].append(r)
        res[name] = {"|".join(map(str, k)): dict(keys=dict(zip(gk, k)), **group_summary(v, (name,) + k))
                     for k, v in sorted(buckets.items(), key=lambda kv: tuple(map(str, kv[0])))}
    return res


def pareto_front(points, objs):
    """objs: list of (field, 'min'|'max'). Returns ids of non-dominated points."""
    def better_eq(a, b):
        return all((a[f] <= b[f]) if s == "min" else (a[f] >= b[f]) for f, s in objs)

    def strictly(a, b):
        return any((a[f] < b[f]) if s == "min" else (a[f] > b[f]) for f, s in objs)
    nd = []
    for p in points:
        if not any(better_eq(q, p) and strictly(q, p) for q in points if q is not p):
            nd.append(p["id"])
    return nd


def pareto(runs, groups):
    gr = [r for r in runs if r["grade"] in GRADES]
    out = {"population": "old_install v1 graded runs (the only graded population)", "n_runs": len(gr)}
    pts = []
    for g in groups["by_install_agent_type"].values():
        if g["grades"]["n_graded"] == 0:
            continue
        gg = [r for r in gr if r["run_id"] in g["run_ids"]]
        pts.append({"id": g["keys"]["agent_type"], "n_graded": len(gg),
                    "median_tokens_total": float(np.median([r["tokens_total"] for r in gg])),
                    "median_duration_s": float(np.median([r["duration_s"] for r in gg])),
                    "pass_rate": g["grades"]["rates"]["pass"]["p"],
                    "pass_rate_ci95": [g["grades"]["rates"]["pass"]["lo"], g["grades"]["rates"]["pass"]["hi"]],
                    "mean_quality_score": g["grades"]["quality_score"]["mean"]})
    pts.sort(key=lambda p: p["id"])
    out["agent_type_points"] = pts
    out["agent_type_front_tokens_vs_pass"] = pareto_front(pts, [("median_tokens_total", "min"), ("pass_rate", "max")])
    out["agent_type_front_tokens_duration_vs_pass"] = pareto_front(
        pts, [("median_tokens_total", "min"), ("median_duration_s", "min"), ("pass_rate", "max")])
    rp = [{"id": r["run_id"], "agent_type": r["agent_type"], "tokens_total": r["tokens_total"],
           "tokens_fresh": r["tokens_fresh"], "duration_s": r["duration_s"], "quality_score": r["quality_score"],
           "grade": r["grade"]} for r in gr]
    out["run_points"] = rp
    out["run_front_tokens_vs_quality"] = pareto_front(rp, [("tokens_total", "min"), ("quality_score", "max")])
    out["run_front_fresh_tokens_vs_quality"] = pareto_front(rp, [("tokens_fresh", "min"), ("quality_score", "max")])
    ns = [q["n_graded"] for q in pts]
    out["caveat"] = ("Points mix different prompts and task classes; agent types were assigned by prompt, not randomised; "
                     f"n per agent type is {min(ns)}-{max(ns)}. Descriptive only.")
    return out


def paired(runs):
    by = defaultdict(dict)
    for r in runs:
        by[r["prompt_id"]][(r["install"], r["variant"])] = r
    pairs = [(p, d[("old_install", "v1")], d[("new_install", "v2")]) for p, d in sorted(by.items())
             if ("old_install", "v1") in d and ("new_install", "v2") in d]
    out = {"definition": "Prompts run as old_install v1 AND new_install v2. Differences confound agent type (fallback -> "
                         "dedicated), install/config, model and time; NOT replicates.",
           "n_pairs": len(pairs), "pairs": [], "metrics": {}}
    for p, a, b in pairs:
        out["pairs"].append({"prompt_id": p, "v1_agent": a["agent_type"], "v2_agent": b["agent_type"],
                             "v1_grade": a["grade"], "v2_grade": b["grade"],
                             "v1_status": a["final_status"], "v2_status": b["final_status"],
                             **{f"{m}_v1": a[m] for m in HEADLINE_METRICS}, **{f"{m}_v2": b[m] for m in HEADLINE_METRICS}})
    for m in HEADLINE_METRICS:
        lr = [math.log2(b[m] / a[m]) for _, a, b in pairs if a[m] and b[m]]
        s = summarize(lr, ("paired", m))
        s["v2_lower_count"] = sum(1 for x in lr if x < 0)
        s["note"] = "log2(v2/v1); median 1.0 = v2 used twice as much"
        out["metrics"][m] = s
    return out


def replicates(runs):
    c = Counter((r["prompt_id"], r["install"], r["variant"]) for r in runs)
    multi = {"|".join(k): n for k, n in c.items() if n > 1}
    r2 = [r["run_id"] for r in runs if r["variant"].startswith("r")]
    return {"definition": "Within-prompt variance needs >= 2 runs of the same prompt on the same install and variant "
                          "(r2 replicates).",
            "replicated_cells": multi, "r2_runs": r2, "n_replicated_cells": len(multi),
            "within_prompt_variance": None if not multi else "see replicated_cells",
            "status": "missing: batch X (r2 replicates) was never dispatched" if not r2 else "present"}


def status_vs_grade(runs):
    gr = [r for r in runs if r["grade"] in GRADES]
    tab = defaultdict(Counter)
    for r in gr:
        tab[r["final_status"]][r["grade"]] += 1
    over = [r["run_id"] for r in gr if (r["final_status"] == "done" or r["clean_header"] == 1) and r["grade"] != "pass"]
    under = [r["run_id"] for r in gr if r["final_status"] in ("partial", "blocked") and r["grade"] == "pass"]
    return {"n_graded": len(gr), "crosstab": {s: {g: tab[s][g] for g in GRADES} for s in STATUSES},
            "overclaim": wilson(len(over), len(gr)), "overclaim_runs": over,
            "underclaim": wilson(len(under), len(gr)), "underclaim_runs": under}


def cross_check(segrows):
    """Second route: token totals per agent from the live usage tables (independent writer: the stack's usage hook)."""
    res = {}
    for sid, rows in segrows.items():
        u = load_csv(USAGE[sid])
        last = {}
        for r in u:
            if r["session"] != sid:
                continue
            k = (r["id"], r["seg"])
            key = (int(r["api_calls"] or 0), float(r["last_ts"] or 0), int(r["output"] or 0))
            if k not in last or key >= last[k][0]:
                last[k] = (key, r)
        utot = defaultdict(int)
        for (aid, _), (_, r) in last.items():
            utot[aid] += sum(int(r[f] or 0) for f in ("input", "output", "cache_creation", "cache_read"))
        ctot = defaultdict(int)
        for r in rows:
            if r["kind"] == "prompt":
                ctot[r["agent_id"]] += int(r["tokens_total"] or 0)
        both = sorted(set(ctot) & set(utot))
        rel = {a: (utot[a] - ctot[a]) / ctot[a] if ctot[a] else None for a in both}
        exact = sum(1 for a in both if utot[a] == ctot[a])
        within1 = sum(1 for a in both if rel[a] is not None and abs(rel[a]) <= 0.01)
        res[sid] = {"usage_file": os.path.relpath(USAGE[sid], HERE), "prompt_agents_collector": len(ctot),
                    "prompt_agents_in_usage": len(both), "missing_in_usage": sorted(set(ctot) - set(utot)),
                    "exact_match": exact, "within_1pct": within1,
                    "max_abs_rel_diff": rnd(max((abs(x) for x in rel.values() if x is not None), default=None), 6),
                    "mismatches": {a: {"collector": ctot[a], "usage": utot[a]} for a in both if utot[a] != ctot[a]}}
    return res


def provenance(runs):
    out = {}
    for sid, (inst, _) in SESSIONS.items():
        commits, snaps = Counter(), Counter()
        u = load_csv(USAGE[sid])
        for r in u:
            if r["session"] == sid:
                if r.get("stack_commit"):
                    commits[r["stack_commit"]] += 1
                if r.get("snap"):
                    snaps[r["snap"]] += 1
        out[inst] = {"session": sid,
                     "stack_commit": sorted(commits) or "missing (usage schema 1 has no stack_commit column)",
                     "limits_snapshot_id": sorted(snaps) or "missing (usage schema 1 has no snap column)",
                     "runs_by_root_model": dict(sorted(Counter(";".join(r["root_models"]) for r in runs
                                                               if r["install"] == inst).items()))}
    return out


def main():
    if "--check" in sys.argv:
        bad = []
        for line in open(os.path.join(INP, "MANIFEST.sha256"), encoding="utf-8"):
            h, rel = line.rstrip("\n").split("  ", 1)
            if sha256_file(os.path.join(INP, rel)) != h:
                bad.append(rel)
        if bad:
            print("MANIFEST MISMATCH:", bad)
            sys.exit(1)
        print("manifest ok")
    prompts = {r["id"]: r for r in load_csv(PROMPTS)}
    grades = {}
    for f in GRADE_FILES:
        for r in load_csv(f):
            if r["id"] in grades:
                raise SystemExit(f"duplicate grade for {r['id']} in {f}")
            grades[r["id"]] = r
    runs, overhead, segrows = build_runs(prompts, grades)
    groups = all_groups(runs)
    ran = {r["prompt_id"] for r in runs}
    graded_ids = {r["prompt_id"] for r in runs if r["grade"] in GRADES}
    gaps = {
        "never_run_prompts": sorted(set(prompts) - ran),
        "never_run_held": {k: v for k, v in NEVER_RUN_HELD.items() if k not in ran},
        "ungraded_runs": [r["run_id"] for r in runs if r["grade"] == "ungraded"],
        "grades_without_run": sorted(set(grades) - graded_ids),
        "runs_without_final_report": [r["run_id"] for r in runs if r["format_class"] == "missing"],
        "open_segments_in_runs": [r["run_id"] for r in runs if r["open_segments"]],
        "cost_usd": "not recorded anywhere (all runs)",
        "replicates_r2": "batch X never dispatched: no within-prompt replicate exists",
        "grades_new_install": "T8c/T8x never dispatched: no new_install run is graded",
        "b0b3_stop_list_not_started": "per inputs/b0b3_plan.md STOP: P47 P50 P52 P53 P69 P72-P86, wave L (P88 P89 P91-P96 P98 P99 P100)",
    }
    inputs = {}
    for line in open(os.path.join(INP, "MANIFEST.sha256"), encoding="utf-8"):
        h, rel = line.rstrip("\n").split("  ", 1)
        inputs[rel] = h
    manifest_sha = sha256_file(os.path.join(INP, "MANIFEST.sha256"))
    frozen = dict(ln.split(": ", 1) for ln in open(os.path.join(INP, "FROZEN_AT.txt"), encoding="utf-8").read().splitlines()[:3]
                  if ": " in ln)
    confounds = [
        {"id": "install_and_agent_change", "text": "old_install runs used fallback agents for 19 missing types; new_install runs "
         "used dedicated agents, a newer stack and possibly other models. v1-vs-v2 differences mix all of these."},
        {"id": "tool_absent_sandbox", "text": "Graders marked 'tool-absent' when the sandbox or machine lacked a toolchain "
         "(Miri, Gradle/kotlinc, Hackage, Julia registry). These are environment failures, kept in the grade denominator; "
         "pass_rate_excl_tool_absent is reported alongside."},
        {"id": "grader_blocked", "text": "The read-only guard often blocked the grader from re-running tests; many grades rest on "
         "the agent's own evidence (see grades.grader_blocked / grader_reexecuted)."},
        {"id": "rubric_ambiguity", "text": "Verified example: P18 graded pass because 'exit 2 and permissionDecision deny both "
         "correct per hooks doc', while P23 graded partial because the hook used 'deny JSON with exit 0, not exit 2 as rubric "
         "says' (grades.csv vs grades_T8b.csv). P11 partial hinges on rubric intent ('return str(x+1)'). One grader per batch, "
         "no inter-rater check."},
        {"id": "small_n", "text": "Most agent types have 1-3 runs; one run per prompt; no replicates. Wilson intervals are wide "
         "and bootstrap CIs are omitted below n=5."},
        {"id": "format_rule_version", "text": "The clean-finish header rule entered the repo at 18b8da1 (2026-10-02 14:22 +0100); "
         "whether the old install carried it is unverified, so old_install format compliance is also given under the legacy "
         "STATUS-only convention."},
        {"id": "selection", "text": "Prompt order, batching and concurrency were not randomised; S/M/L classes were run in waves; "
         "the graded population is old_install v1 only (40 runs)."},
        {"id": "model_mix", "text": "Root models differ between installs (see provenance.*.runs_by_root_model): the agent "
         "definitions pin models per agent type, so install, agent type and model change together."},
        {"id": "binary_quality_front", "text": "With pass/partial/fail grades the run-level cost-quality front collapses to the "
         "cheapest passing run (and any cheaper non-passing run); it says nothing about which design is better."},
        {"id": "tokens_include_cache", "text": "tokens_total counts cache reads at full weight; tokens_fresh excludes them. "
         "Neither is a cost; cost is missing."},
    ]
    out = {
        "schema_version": SCHEMA_VERSION,
        "title": "agent-stack baseline BEFORE statistics (pre-Bayesian)",
        "frozen_at": frozen,
        "inputs_manifest_sha256": manifest_sha,
        "inputs": inputs,
        "seed": SEED, "bootstrap_B": B, "min_n_bootstrap": MIN_N_CI, "wilson_z": Z,
        "definitions": DEFINITIONS,
        "exclusions": {"overhead_dispatches": overhead,
                       "non_campaign_agents": "collector kind 'other' rows (other jobs in the same sessions) are excluded",
                       "open_segments": "runs with open segments would be flagged; none at freeze time" if not gaps["open_segments_in_runs"] else gaps["open_segments_in_runs"]},
        "data_gaps": gaps,
        "confounds": confounds,
        "n": {"runs": len(runs), "graded_runs": len(graded_ids), "prompts_in_corpus": len(prompts),
              "prompts_run": len(ran), "by_install_variant": dict(Counter(f"{r['install']}|{r['variant']}" for r in runs))},
        "runs": runs,
        "groups": groups,
        "status_vs_grade": status_vs_grade(runs),
        "pareto_points": pareto(runs, groups),
        "paired_v1_v2": paired(runs),
        "replicates": replicates(runs),
        "cross_checks": {"tokens_second_route": cross_check(segrows)},
        "provenance": provenance(runs),
        "environment": {"python": sys.version.split()[0], "numpy": np.__version__},
    }
    flat_cols = ["run_id", "install", "prompt_id", "variant", "family", "cost_class", "target_agent", "agent_type",
                 "fallback", "root_models", "grade", "quality_score", "final_status", "format_class",
                 "compliant_current_rule", "compliant_legacy", "clean_header", "status_block_complete", "deviations",
                 *METRICS, "max_depth", "tool_errors", "tool_denied", "sandbox_blocks", "hit_max_turns",
                 "soft_limit_hits", "compactions", "skill_calls", "n_segments", "n_agents", "cost_usd"]
    with open(os.path.join(HERE, "runs_before.csv"), "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh, lineterminator="\n")
        w.writerow(flat_cols)
        for r in runs:
            w.writerow([";".join(r[c]) if isinstance(r[c], list) else ("" if r[c] is None else r[c]) for c in flat_cols])
    with open(os.path.join(HERE, "stats_before.json"), "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=1, ensure_ascii=False, sort_keys=False)
        fh.write("\n")
    with open(os.path.join(HERE, "stats_before.md"), "w", encoding="utf-8") as fh:
        fh.write(render_md(out))
    print(f"runs {len(runs)}; graded {len(graded_ids)}; wrote stats_before.json, stats_before.md, runs_before.csv")


# ---------------------------------------------------------------- markdown
def fr(w):
    return "missing (n=0)" if not w or w["n"] == 0 else f"{w['k']}/{w['n']} = {w['p']:.2f} [{w['lo']:.2f}, {w['hi']:.2f}]"


def fk(x):
    return "-" if x is None else (f"{x / 1e6:.2f}M" if x >= 1e5 else f"{x / 1e3:.0f}k" if x >= 1e3 else f"{x:g}")


def fm(s, f=fk):
    if not s or s["n"] == 0:
        return "missing"
    ci = s.get("median_ci95")
    return f"{f(s['median'])}" + (f" [{f(ci[0])}, {f(ci[1])}]" if ci else "")


def fs(x):
    return "-" if x is None else f"{x:.0f}"


def render_md(o):
    L = []
    a = L.append
    g = o["groups"]
    a("# Agent-stack baseline: BEFORE statistics (pre-Bayesian)\n")
    a(f"Schema {o['schema_version']} · frozen {o['frozen_at'].get('frozen_at_local', '?')} · inputs manifest sha256 "
      f"`{o['inputs_manifest_sha256'][:16]}…` · seed {o['seed']} · bootstrap B={o['bootstrap_B']} (CIs only for n≥{o['min_n_bootstrap']}).")
    a("Generated by `uv run --script compute_stats.py` from `inputs/` only. Machine-readable twin: `stats_before.json`; "
      "definitions there (`definitions`). Like-for-like procedure: `COMPARE.md`.\n")
    n = o["n"]
    a(f"**Population.** {n['runs']} runs of {n['prompts_run']}/{n['prompts_in_corpus']} corpus prompts: "
      + ", ".join(f"{k} n={v}" for k, v in sorted(n["by_install_variant"].items()))
      + f". Graded: {n['graded_runs']} runs, all old_install v1. Cost (USD) is not recorded anywhere: missing for all runs.\n")
    a("Rates are k/n = p [Wilson 95 %]. Numbers are medians [bootstrap 95 % CI of the median]. n is per cell.\n")
    for inst, pv in o["provenance"].items():
        a(f"- {inst}: session {pv['session'][:8]}, stack commit {pv['stack_commit']}, limits snapshot "
          f"{pv['limits_snapshot_id']}, runs by root model {pv['runs_by_root_model']}.")
    a("")
    a("## 1. Headline by install × variant\n")
    a("| cell | n runs | n graded | pass / partial / fail / tool-absent | pass rate | tokens_total | tokens_fresh | tool calls | duration s | STATUS line | clean header | compliant (current rule) |")
    a("|---|---|---|---|---|---|---|---|---|---|---|---|")
    for k, s in g["by_install_variant"].items():
        c = s["grades"]["counts"]
        a(f"| {k} | {s['n_runs']} | {s['grades']['n_graded']} | "
          + (f"{c['pass']} / {c['partial']} / {c['fail']} / {c['tool-absent']}" if s["grades"]["n_graded"] else "missing")
          + f" | {fr(s['grades']['rates']['pass'])} | {fm(s['metrics']['tokens_total'])} | {fm(s['metrics']['tokens_fresh'])} | "
          f"{fm(s['metrics']['tool_calls'], fs)} | {fm(s['metrics']['duration_s'], fs)} | {fr(s['format']['status_line_strict'])} | "
          f"{fr(s['format']['clean_finish_rate'])} | {fr(s['format']['compliant_current_rule'])} |")
    s = g["by_install_variant"].get("old_install|v1")
    if s:
        a(f"\nold_install v1: pass rate excluding tool-absent {fr(s['grades']['pass_rate_excl_tool_absent'])}; "
          f"grader re-executed something in {fr(s['grades']['grader_reexecuted'])}; grader re-run blocked/not done in "
          f"{fr(s['grades']['grader_blocked'])}; legacy STATUS-only compliance {fr(s['format']['compliant_legacy'])}.")
    a("\nOther metrics per cell (mean, IQR, p90, mean CI) are in `stats_before.json` → `groups.by_install_variant.*.metrics`.\n")
    a("## 2. By agent type\n")
    a("| install | agent type | n | n graded | pass rate | tokens_total | duration s | tool calls | self-report done/partial/blocked/none | fallback |")
    a("|---|---|---|---|---|---|---|---|---|---|")
    for k, s in g["by_install_agent_type"].items():
        sc = s["self_report"]["counts"]
        a(f"| {s['keys']['install']} | {s['keys']['agent_type']} | {s['n_runs']} | {s['grades']['n_graded']} | "
          f"{fr(s['grades']['rates']['pass'])} | {fm(s['metrics']['tokens_total'])} | {fm(s['metrics']['duration_s'], fs)} | "
          f"{fm(s['metrics']['tool_calls'], fs)} | {sc['done']}/{sc['partial']}/{sc['blocked']}/{sc['none']} | "
          f"{s['environment']['fallback']['k']}/{s['n_runs']} |")
    a("\n## 3. By task class (family × install)\n")
    a("| install | family | n | n graded | pass rate | tokens_total | duration s |")
    a("|---|---|---|---|---|---|---|")
    for k, s in g["by_install_family"].items():
        a(f"| {s['keys']['install']} | {s['keys']['family']} | {s['n_runs']} | {s['grades']['n_graded']} | "
          f"{fr(s['grades']['rates']['pass'])} | {fm(s['metrics']['tokens_total'])} | {fm(s['metrics']['duration_s'], fs)} |")
    a("\n| install | cost class | n | n graded | pass rate | tokens_total | duration s |")
    a("|---|---|---|---|---|---|---|")
    for k, s in g["by_install_cost_class"].items():
        a(f"| {s['keys']['install']} | {s['keys']['cost_class']} | {s['n_runs']} | {s['grades']['n_graded']} | "
          f"{fr(s['grades']['rates']['pass'])} | {fm(s['metrics']['tokens_total'])} | {fm(s['metrics']['duration_s'], fs)} |")
    a("\nPer prompt id (n = 1 or 2): `groups.by_prompt_id`; per run: `runs[]` and the flat `runs_before.csv`.\n")
    sv = o["status_vs_grade"]
    a(f"## 4. Self-reported STATUS vs grade (graded runs, n={sv['n_graded']})\n")
    a("| final_status | pass | partial | fail | tool-absent |")
    a("|---|---|---|---|---|")
    for st, row in sv["crosstab"].items():
        a(f"| {st} | " + " | ".join(str(row[x]) for x in GRADES) + " |")
    a(f"\nOverclaim (done/clean header but not pass): {fr(sv['overclaim'])} {sv['overclaim_runs']}. "
      f"Underclaim (partial/blocked but pass): {fr(sv['underclaim'])} {sv['underclaim_runs']}.\n")
    a("Format deviations per cell:\n")
    for k, s in g["by_install_variant"].items():
        a(f"- {k} (n={s['n_runs']}): classes {s['format']['classes']}; deviation counts {s['format']['deviation_counts']}")
    p = o["pareto_points"]
    a(f"\n## 5. Cost-vs-quality points (descriptive; {p['population']}, n={p['n_runs']})\n")
    a("| agent type | n graded | median tokens_total | median duration s | pass rate [Wilson] | non-dominated (tokens, pass) | (tokens, duration, pass) |")
    a("|---|---|---|---|---|---|---|")
    for q in p["agent_type_points"]:
        a(f"| {q['id']} | {q['n_graded']} | {fk(q['median_tokens_total'])} | {q['median_duration_s']:.0f} | "
          f"{q['pass_rate']:.2f} [{q['pass_rate_ci95'][0]:.2f}, {q['pass_rate_ci95'][1]:.2f}] | "
          f"{'yes' if q['id'] in p['agent_type_front_tokens_vs_pass'] else ''} | "
          f"{'yes' if q['id'] in p['agent_type_front_tokens_duration_vs_pass'] else ''} |")
    a(f"\nRun-level non-dominated (tokens_total ↓, quality_score ↑): {', '.join(p['run_front_tokens_vs_quality'])}. "
      f"With tokens_fresh: {', '.join(p['run_front_fresh_tokens_vs_quality'])}.")
    a(f"\n{p['caveat']} No design recommendation is drawn here.\n")
    pv = o["paired_v1_v2"]
    a(f"## 6. Paired old v1 vs new v2 (n={pv['n_pairs']} prompts; not replicates)\n")
    a("| metric | n | median log2(v2/v1) [CI] | mean [CI] | v2 lower |")
    a("|---|---|---|---|---|")
    for m, s in pv["metrics"].items():
        ci = s.get("median_ci95")
        mci = s.get("mean_ci95")
        a(f"| {m} | {s['n']} | {s['median']:+.2f}" + (f" [{ci[0]:+.2f}, {ci[1]:+.2f}]" if ci else "") + f" | {s['mean']:+.2f}"
          + (f" [{mci[0]:+.2f}, {mci[1]:+.2f}]" if mci else "") + f" | {s['v2_lower_count']}/{s['n']} |")
    a(f"\n{pv['definition']} v2 grades: missing (never graded).\n")
    rp = o["replicates"]
    a(f"## 7. Within-prompt variance\n\n{rp['status']}. Replicated cells: {rp['n_replicated_cells']}. "
      "Within-prompt variance cannot be estimated from these inputs.\n")
    a("## 8. Overhead (excluded from run statistics)\n")
    for k, v in o["exclusions"]["overhead_dispatches"].items():
        a(f"- {k}: {v['segments']} segments, tokens_total {fk(v['tokens_total'])} ({'; '.join(sorted(set(v['roots'])))})")
    a("\n## 9. Cross-checks (second route)\n")
    for sid, c in o["cross_checks"]["tokens_second_route"].items():
        a(f"- session {sid[:8]}: per-agent token totals, collector vs `{c['usage_file']}` (usage hook, independent writer): "
          f"{c['exact_match']}/{c['prompt_agents_in_usage']} exact, max |rel diff| {c['max_abs_rel_diff']}; "
          f"missing in usage {len(c['missing_in_usage'])}.")
    dg = o["data_gaps"]
    a("\n## 10. Data gaps\n")
    a(f"- Never run: {len(dg['never_run_prompts'])} prompts ({', '.join(dg['never_run_prompts'])}).")
    a(f"- Held for the user: {', '.join(f'{k} ({v})' for k, v in dg['never_run_held'].items())}.")
    a(f"- Ungraded runs: {len(dg['ungraded_runs'])} (every new_install run). {dg['grades_new_install']}.")
    a(f"- {dg['replicates_r2']}.")
    a(f"- Cost: {dg['cost_usd']}.")
    a(f"- {dg['b0b3_stop_list_not_started']}.")
    a(f"- Runs without a final report: {dg['runs_without_final_report'] or 'none'}; open segments: {dg['open_segments_in_runs'] or 'none'}.")
    a("\n## 11. Confounds and caveats\n")
    for c in o["confounds"]:
        a(f"- **{c['id']}**: {c['text']}")
    return "\n".join(L) + "\n"


if __name__ == "__main__":
    main()
