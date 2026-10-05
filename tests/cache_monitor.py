#!/usr/bin/env python3
"""cache_monitor.py - prompt-cache misses in Claude Code transcripts, each with a labelled cause.

Reads the session transcripts (`<root>/<project>/<session>.jsonl` and
`<root>/<project>/<session>/subagents/agent-*.jsonl`, with `agent-*.meta.json` for the type) and
prints aggregates only: no prompt, tool or message text leaves this process.

Method (the Stage 4 h4 scripts, stage4-measure/h4_extract.py and the L1 audit's l1_misses.py):
  request   one per unique message.id in a thread (synthetic messages skipped); usage = the max over
            its streamed records; ctx = input + cache_creation + cache_read
  idle      seconds from the previous request's first record to the last user record before this
            one (else from the previous request's last record to this one's first)
  ttl       3600 s when the thread has written 1-hour cache, else 300 s
  miss      max(0, min(prev ctx, ctx) - cache_read): prefix tokens that were cached and are written
            again (a re-write); counted when > --min-miss tokens
  cause     compaction      a compact_boundary since the previous request (a new context)
            ttl-expiry      idle > ttl (an expected miss; the others are no-gap misses)
            model-change    another model than the previous request, or one request after such a
                            switch (or thinking_drop modelChanged)
            system-prompt   thinking_drop with systemPromptChanged or a disk baseline (process
                            restart, --resume)
            history-rewrite thinking_drop with messagesHistoryChanged (e.g. after a compaction)
            resume-thinking-drop  a subagent resume (SubagentStart again) where Claude Code dropped
                            the earlier thinking blocks: the L1 audit's main no-gap cause
            thinking-drop   the same drop without a resume
            resume          a resume that missed without a drop
            unexplained     none of the above (look here first: stack text changing mid-thread?)
  usd       list-price estimate (h4_common.PRICES_LIST: stage4-research platform.md, 2026-10-05; not
            a bill): miss tokens x (write price - read price); total = every request's cost

Usage: python3 tests/cache_monitor.py [--root DIR] [--session SID ...] [--days N] [--min-miss TOK]
                                       [--list] [--json] [--fail-over PCT]
--root defaults to ${CLAUDE_CONFIG_DIR:-~/.claude}/projects; --days 7 (by the newest file of a
session; 0 = all). --fail-over PCT exits 1 when the no-gap miss cost exceeds PCT % of the total
(a monitor alarm). Exit 2 when no transcript matched. Stdlib only.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

PRICES = {   # $/MTok, list prices (see the module docstring); w1h = 1-hour cache write
    "opus": {"inp": 4.0, "out": 20.0, "w5": 5.0, "w1h": 8.0, "rd": 0.20},
    "sonnet": {"inp": 2.0, "out": 10.0, "w5": 2.5, "w1h": 4.0, "rd": 0.20},
}
GAP_CAUSES = frozenset({"ttl-expiry", "compaction"})     # not counted as no-gap misses
CAUSES = ("compaction", "ttl-expiry", "model-change", "system-prompt", "history-rewrite",
          "resume-thinking-drop", "thinking-drop", "resume", "unexplained")


def tier(model: str | None) -> str:
    return "sonnet" if model and "sonnet" in model else "opus"


def ts(s: object) -> float | None:
    if not isinstance(s, str) or not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


@dataclass
class Req:
    k: int
    model: str | None
    ts_first: float | None
    ts_send: float | None
    marks: dict[str, object]
    ts_last: float | None = None
    inp: int = 0
    cc: int = 0
    cc1h: int = 0
    cr: int = 0
    out: int = 0

    @property
    def ctx(self) -> int:
        return self.inp + self.cc + self.cr

    def usd(self) -> float:
        p = PRICES[tier(self.model)]
        w5 = max(self.cc - self.cc1h, 0)
        return (self.inp * p["inp"] + w5 * p["w5"] + self.cc1h * p["w1h"] + self.cr * p["rd"]
                + self.out * p["out"]) / 1e6


@dataclass
class Thread:
    session: str
    thread: str          # "main" or the agent id
    agent_type: str
    reqs: list[Req] = field(default_factory=list)


def parse_thread(path: Path, session: str, thread: str, agent_type: str) -> Thread:
    """One transcript file -> its API requests, each with the markers seen since the previous one."""
    th = Thread(session, thread, agent_type)
    by_id: dict[str, Req] = {}
    marks: dict[str, object] = {}
    last_user: float | None = None
    with path.open(encoding="utf-8", errors="replace") as fh:
        for line in fh:
            try:
                r = json.loads(line)
            except ValueError:
                continue
            if not isinstance(r, dict):
                continue
            t = r.get("type")
            if t == "assistant":
                m = r.get("message") or {}
                if m.get("model") == "<synthetic>":
                    continue
                mid = m.get("id") or r.get("requestId") or r.get("uuid")
                u = m.get("usage") or {}
                q = by_id.get(mid)
                if q is None:
                    q = Req(len(th.reqs), m.get("model"), ts(r.get("timestamp")), last_user, marks)
                    marks = {}
                    by_id[mid] = q
                    th.reqs.append(q)
                q.ts_last = ts(r.get("timestamp")) or q.ts_last
                q.inp = max(q.inp, u.get("input_tokens") or 0)
                q.cc = max(q.cc, u.get("cache_creation_input_tokens") or 0)
                q.cc1h = max(q.cc1h, (u.get("cache_creation") or {}).get("ephemeral_1h_input_tokens") or 0)
                q.cr = max(q.cr, u.get("cache_read_input_tokens") or 0)
                q.out = max(q.out, u.get("output_tokens") or 0)
            elif t == "user":
                last_user = ts(r.get("timestamp")) or last_user
            elif t == "system" and r.get("subtype") == "compact_boundary":
                marks["compact"] = True
            elif t == "attachment":
                a = r.get("attachment") or {}
                if a.get("type") == "thinking_drop":
                    cc = a.get("clientChange") or {}
                    kinds = cc.get("kinds")
                    kinds = kinds.split(",") if isinstance(kinds, str) else list(kinds or [])
                    marks["drop"] = {"kinds": {x.strip() for x in kinds if x and x.strip() != "none"},
                                     "baseline": cc.get("baseline")}
                elif a.get("type") == "hook_success" and a.get("hookEvent") == "SubagentStart" and th.reqs:
                    marks["resume"] = True
    return th


def cause(prev: Req, q: Req, idle: float | None, ttl: int, prev_model: str | None = None) -> str:
    """The label of a miss at `q`; prev_model is the model of the request before `prev` (a switch
    there leaves the new model's cache unwritten, so the request after it misses too)."""
    if q.marks.get("compact"):
        return "compaction"
    if idle is not None and idle > ttl:
        return "ttl-expiry"
    drop = q.marks.get("drop")
    kinds = drop["kinds"] if isinstance(drop, dict) else set()
    if q.model != prev.model or "modelChanged" in kinds or (prev_model is not None and prev_model != prev.model):
        return "model-change"
    if isinstance(drop, dict):
        if "systemPromptChanged" in kinds or drop.get("baseline") == "disk":
            return "system-prompt"
        if "messagesHistoryChanged" in kinds:
            return "history-rewrite"
        return "resume-thinking-drop" if q.marks.get("resume") else "thinking-drop"
    return "resume" if q.marks.get("resume") else "unexplained"


def analyse(threads: list[Thread], min_miss: int = 1000) -> dict[str, object]:
    """Aggregates plus one row per miss (labels and numbers only)."""
    tot: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    by_type: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    by_cause: dict[str, dict[str, float]] = {c: defaultdict(float) for c in CAUSES}
    misses: list[dict[str, object]] = []
    for th in threads:
        scope = "main" if th.thread == "main" else "sub"
        wrote_1h = False
        for i, q in enumerate(th.reqs):
            for key in (scope, "all"):
                s = tot[key]
                s["requests"] += 1
                s["ctx"] += q.ctx
                s["cache_read"] += q.cr
                s["cache_write"] += q.cc
                s["usd"] += q.usd()
            by_type[th.agent_type]["usd"] += q.usd()
            by_type[th.agent_type]["requests"] += 1
            prev = th.reqs[i - 1] if i else None
            wrote_1h = wrote_1h or bool(prev and prev.cc1h)
            if prev is None:
                continue
            miss = max(0, min(prev.ctx, q.ctx) - q.cr)
            if miss <= min_miss:
                continue
            ttl = 3600 if wrote_1h else 300
            if q.ts_send is not None and prev.ts_first is not None and q.ts_send >= prev.ts_first:
                idle = q.ts_send - prev.ts_first
            elif q.ts_first is not None and prev.ts_last is not None:
                idle = q.ts_first - prev.ts_last
            else:
                idle = None
            c = cause(prev, q, idle, ttl, th.reqs[i - 2].model if i >= 2 else None)
            p = PRICES[tier(q.model)]
            w = p["w1h"] if q.cc1h else p["w5"]
            usd = miss * (w - p["rd"]) / 1e6
            nogap = c not in GAP_CAUSES
            for key in (scope, "all"):
                s = tot[key]
                s["miss_n"] += 1
                s["miss_tok"] += miss
                s["miss_usd"] += usd
                if nogap:
                    s["nogap_n"] += 1
                    s["nogap_tok"] += miss
                    s["nogap_usd"] += usd
            by_cause[c]["n"] += 1
            by_cause[c]["tok"] += miss
            by_cause[c]["usd"] += usd
            if nogap:
                by_type[th.agent_type]["nogap_n"] += 1
                by_type[th.agent_type]["nogap_usd"] += usd
            misses.append({"session": th.session[:8], "thread": th.thread[:18], "type": th.agent_type,
                           "k": q.k, "idle_s": None if idle is None else round(idle),
                           "ttl": ttl, "prev_ctx": prev.ctx, "cache_read": q.cr, "miss": miss,
                           "usd": round(usd, 4), "cause": c})
    for s in tot.values():
        s["read_share"] = s["cache_read"] / s["ctx"] if s["ctx"] else 0.0
        s["nogap_usd_share"] = s["nogap_usd"] / s["usd"] if s["usd"] else 0.0
    return {"totals": {k: dict(v) for k, v in tot.items()},
            "by_cause": {k: dict(v) for k, v in by_cause.items() if v},
            "by_type": {k: dict(v) for k, v in by_type.items()},
            "misses": misses, "min_miss": min_miss}


def discover(root: Path, sessions: list[str] | None, days: float) -> list[tuple[Path, str, str, str]]:
    """[(file, session, thread, agent type)] under root."""
    found: dict[str, list[Path]] = defaultdict(list)
    for proj in sorted(p for p in root.glob("*") if p.is_dir()):
        for f in proj.glob("*.jsonl"):
            found[f.stem].append(f)
        for f in proj.glob("*/subagents/agent-*.jsonl"):
            found[f.parent.parent.name].append(f)
    cutoff = time.time() - days * 86400 if days > 0 else None
    out: list[tuple[Path, str, str, str]] = []
    for sid, files in sorted(found.items()):
        if sessions and not any(sid.startswith(s) for s in sessions):
            continue
        if cutoff is not None and max(f.stat().st_mtime for f in files) < cutoff:
            continue
        for f in sorted(files):
            if f.parent.name == "subagents":
                aid = f.stem[len("agent-"):]
                atype = "?"
                meta = f.with_name(f.stem + ".meta.json")
                try:
                    atype = str(json.loads(meta.read_text(encoding="utf-8")).get("agentType") or "?")
                except (OSError, ValueError, AttributeError):
                    pass
                out.append((f, sid, aid, atype))
            else:
                out.append((f, sid, "main", "main"))
    return out


def fmt_report(res: dict[str, object], list_misses: bool, top: int = 12) -> str:
    tot = res["totals"]
    lines = ["scope  requests  read_share  misses(tok)            no-gap misses(tok)      no-gap $ / total $"]
    for key in ("main", "sub", "all"):
        s = tot.get(key)
        if not s:
            continue
        lines.append(
            f"{key:<5} {s['requests']:9.0f}  {100 * s['read_share']:9.1f}%  "
            f"{s.get('miss_n', 0):6.0f} ({s.get('miss_tok', 0):10.0f})    "
            f"{s.get('nogap_n', 0):6.0f} ({s.get('nogap_tok', 0):10.0f})    "
            f"{s.get('nogap_usd', 0):8.2f} / {s['usd']:.2f} = {100 * s['nogap_usd_share']:.2f}%")
    lines.append("")
    lines.append("cause                     n        tokens        usd")
    for c in CAUSES:
        v = res["by_cause"].get(c)
        if v:
            gap = "  (gap)" if c in GAP_CAUSES else ""
            lines.append(f"{c:<22} {v['n']:4.0f}  {v['tok']:12.0f}  {v['usd']:9.2f}{gap}")
    bt = sorted(((k, v) for k, v in res["by_type"].items() if v.get("nogap_n")),
                key=lambda kv: -kv[1]["nogap_usd"])[:top]
    if bt:
        lines.append("")
        lines.append("agent type (no-gap misses)        n       usd   of the type's $")
        for k, v in bt:
            pct = 100 * v["nogap_usd"] / v["usd"] if v["usd"] else 0.0
            lines.append(f"{k:<30} {v['nogap_n']:5.0f}  {v['nogap_usd']:8.2f}   {pct:5.1f}%")
    if list_misses:
        lines.append("")
        lines.append("session  thread             type                   k   idle_s  prev_ctx  read   miss"
                     "     usd  cause")
        for m in res["misses"]:
            idle = "-" if m["idle_s"] is None else str(m["idle_s"])
            lines.append(f"{m['session']:<8} {m['thread']:<18} {m['type'][:20]:<20} {m['k']:4d} {idle:>8} "
                         f"{m['prev_ctx']:9d} {m['cache_read']:6d} {m['miss']:6d} {m['usd']:7.3f}  {m['cause']}")
    lines.append("")
    lines.append(f"misses: cached prefix tokens written again (> {res['min_miss']} tok); "
                 "$ = list-price estimate, not a bill")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n", 1)[0])
    base = Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude")
    ap.add_argument("--root", type=Path, default=base / "projects", help="transcripts root (projects dir)")
    ap.add_argument("--session", action="append", help="session id or prefix (repeatable)")
    ap.add_argument("--days", type=float, default=7.0, help="sessions active in the last N days (0 = all)")
    ap.add_argument("--min-miss", type=int, default=1000, help="tokens a re-write must exceed to count")
    ap.add_argument("--list", action="store_true", help="one line per miss (labels and numbers only)")
    ap.add_argument("--json", action="store_true", help="the aggregates and misses as JSON")
    ap.add_argument("--fail-over", type=float, metavar="PCT",
                    help="exit 1 when no-gap miss $ exceed PCT %% of the total")
    a = ap.parse_args(argv)
    files = discover(a.root.expanduser(), a.session, a.days)
    if not files:
        print(f"cache_monitor: no transcripts under {a.root}", file=sys.stderr)
        return 2
    res = analyse([parse_thread(*f) for f in files], a.min_miss)
    if not a.list:
        res_out = dict(res, misses=[]) if a.json else res
    else:
        res_out = res
    print(json.dumps(res_out, indent=1, sort_keys=True) if a.json else fmt_report(res, a.list))
    share = res["totals"]["all"]["nogap_usd_share"] if "all" in res["totals"] else 0.0
    return 1 if a.fail_over is not None and 100 * share > a.fail_over else 0


if __name__ == "__main__":
    sys.exit(main())
