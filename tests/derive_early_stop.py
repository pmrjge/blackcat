# /// script
# requires-python = ">=3.8"
# dependencies = []
# ///
"""Calibration of the early-stop rule (dot-claude/hooks/stack_progress.py) by replay of frozen transcripts.

Read-only over Claude Code transcripts (--root: <project>/<session>/subagents/agent-*.jsonl and the
.meta.json beside each, for the agent type). Every record goes through stack_progress.feed, the parser the
hook runs, so the replay sees the rounds, budgets and outcomes the live rule would see. Writes only --out
(default .claude-work/s4-l5/calib): grid.csv (one row per rule variant) and calib.md. No transcript text is
written: counts, token sums, list-price dollars and the agent type only.

Run:  uv run --script tests/derive_early_stop.py --root DIR [--sessions ID,ID] [--out DIR]

Definitions
  run        one subagent segment (a spawn, or a message that wakes an agent whose turn had ended), as
             stack_usage.py cuts them; usage = context tokens (input + cache writes + cache reads per API
             call, deduplicated by (message.id, requestId)), the unit of the stack's limits.
  outcome    the run's last STATUS line (its final text, or a SubagentHandback message): success = done, or
             a final text with no STATUS line (a clean finish); otherwise partial, failed, blocked, or none
             (no final text: cut off).
  firing     the first closed round at which the variant's rule holds (evaluated right after the round
             closes, i.e. at the next API call, as the hook does at the next tool call).
  capture    the share of all subagent usage (or list $) spent after the firing in runs that did not end in
             success: the most an immediate stop could have saved. A ceiling: the rule only warns.
  false stop a firing in a run that ended in success AND made write progress after the firing (an edit,
             write, commit or delegation that succeeded): stopping there would have cut useful work.
  benign     a firing in a successful run with no write progress after it (the report was all that was left).
  gate       none: no budget, the failure streak alone; soft: the brief's budget, else the type's soft
             limit (soft.agent.<type> seed, stack_limits_seed.json); soft/2: half of it.
  progress   write: write, delegate or report calls that succeeded; novel: also any successful call not seen
             before in the run (stack_progress.NOVEL_PROGRESS).
List prices ($/MTok, MEASURE.md section 1.2 of the stage-4 measurement, 2026-10-05; prices change, the shares
are what matter): Opus in 4, out 20, 5m write 5, 1h write 8, cache read 0.20; Sonnet 2, 10, 2.5, 4, 0.20.
Output is the per-message maximum of the streamed records (a lower bound where the records hold placeholders).
"""
import argparse
import copy
import csv
import glob
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HOOKS = ROOT / "dot-claude" / "hooks"
sys.path.insert(0, str(HOOKS))
import stack_progress as sp  # noqa: E402

PRICES = {"opus": (4.0, 20.0, 5.0, 8.0, 0.20), "sonnet": (2.0, 10.0, 2.5, 4.0, 0.20)}
GRID_ROUNDS = (4, 6, 8, 10, 12)
GRID_FAILS = (0, 2, 3, 4, 6, 8)
GATES = ("none", "soft", "soft/2")
SUCCESS = ("done", "clean")


def seed_soft():
    seed = json.loads((HOOKS / "stack_limits_seed.json").read_text())
    return {k[len("soft.agent."):]: v.get("seed") for k, v in seed["vars"].items() if k.startswith("soft.agent.")}


def flags(cur):
    """(progress, novel progress, failing, work) of an open round, through stack_progress.close_round;
    work = a successful write or delegation (progress without the report itself)."""
    out = []
    for novel in (False, True):
        sp.NOVEL_PROGRESS = novel
        tmp = {"cur": copy.deepcopy(cur), "win": []}
        sp.close_round(tmp)
        out.append((tmp["win"][-1] if tmp["win"] else [0, 0]) + [int(tmp.get("nwork") or 0)])
    sp.NOVEL_PROGRESS = False
    return out[0][0], out[1][0], out[0][1], out[0][2]


class Seg:
    def __init__(self, atype, brief, soft=None):
        self.st = sp.new_state()
        self.soft = soft
        self.signals = {}       # the shipped rule (stack_progress.evaluate, default knobs): signal -> round
        self.st["brief"] = brief
        self.atype = atype
        self.usd = 0.0
        self.outs = {}
        self.rounds = []        # (write progress, novel progress, failing, calls, ctx, usd) at each close
        self.handback = None

    def price(self, e):
        msg = e.get("message") or {}
        u = msg.get("usage")
        if not isinstance(u, dict):
            return
        key = "%s|%s" % (msg.get("id"), e.get("requestId"))
        p = PRICES["sonnet" if "sonnet" in str(msg.get("model") or "") else "opus"]
        out = int(u.get("output_tokens") or 0)
        if key not in self.outs:
            cc = int(u.get("cache_creation_input_tokens") or 0)
            br = u.get("cache_creation") if isinstance(u.get("cache_creation"), dict) else {}
            w1h = int(br.get("ephemeral_1h_input_tokens") or 0)
            self.usd += (int(u.get("input_tokens") or 0) * p[0] + (cc - w1h) * p[2] + w1h * p[3]
                         + int(u.get("cache_read_input_tokens") or 0) * p[4]) / 1e6
            self.outs[key] = 0
        if out > self.outs[key]:
            self.usd += (out - self.outs[key]) * p[1] / 1e6
            self.outs[key] = out

    def feed(self, e):
        msg = e.get("message") if isinstance(e.get("message"), dict) else {}
        if e.get("type") == "assistant" and isinstance(msg.get("content"), list):
            for b in msg["content"]:
                if isinstance(b, dict) and b.get("type") == "tool_use" and b.get("name") == "SubagentHandback":
                    m = sp.STATUS_RE.search(json.dumps(b.get("input"))[:65536].replace("\\n", "\n"))
                    self.handback = m.group(1).lower() if m else "clean"
        cur = copy.deepcopy(self.st.get("cur"))
        if e.get("type") == "assistant":
            self.price(e)
        if sp.feed(self.st, e) and cur:
            pw, pn, fail, work = flags(cur)
            self.rounds.append((pw, pn, fail, self.st["calls"], self.st["ctx"], self.usd, work))
            for sig, _b, _n in sp.evaluate(self.st, self.st["ctx"], self.st["calls"], self.soft):
                self.signals[sig] = len(self.rounds) - 1

    def outcome(self):
        return self.handback or self.st.get("status") or "none"


def segments(path, atype, soft=None):
    seg, out = None, []
    with open(path, "rb") as f:
        for line in f:
            try:
                e = json.loads(line)
            except (ValueError, RecursionError):
                continue
            if not isinstance(e, dict) or e.get("type") not in ("assistant", "user"):
                continue
            content = (e.get("message") or {}).get("content") if isinstance(e.get("message"), dict) else None
            is_text = e.get("type") == "user" and not (isinstance(content, list) and any(
                isinstance(b, dict) and b.get("type") == "tool_result" for b in content))
            if seg is None or (is_text and seg.st["calls"] and seg.st["ended"]):
                if seg is not None and seg.st["calls"]:
                    out.append(seg)
                seg = Seg(atype, seg.st.get("brief") if seg else None, soft)
            seg.feed(e)
    if seg is not None and seg.st["calls"]:
        out.append(seg)
    return out


def load(root, sessions, soft=None):
    soft = soft or {}
    runs = []
    for path in sorted(glob.glob(os.path.join(root, "*", "*", "subagents", "agent-*.jsonl"))):
        sid = Path(path).parent.parent.name
        if sessions and sid not in sessions:
            continue
        meta = Path(path[:-len(".jsonl")] + ".meta.json")
        try:
            atype = json.loads(meta.read_text()).get("agentType") or "unknown"
        except (OSError, ValueError):
            atype = "unknown"
        for s in segments(path, atype, soft.get(atype)):
            runs.append({"session": sid, "type": atype, "outcome": s.outcome(), "rounds": s.rounds,
                         "calls": s.st["calls"], "ctx": s.st["ctx"], "usd": s.usd,
                         "brief": s.st.get("budget"), "signals": s.signals})
    return runs


def fire_at(run, rounds, fails, gate, novel, soft):
    """Index of the first round where the variant fires, else None."""
    b = run["brief"]
    limit = None
    if gate != "none":
        if b and b.get("tokens"):
            limit = b["tokens"]
        elif soft.get(run["type"]):
            limit = soft[run["type"]] * (0.5 if gate == "soft/2" else 1.0)
        else:
            return None
    rs = run["rounds"]
    for i in range(rounds - 1, len(rs)):
        if limit is not None and rs[i][4] < limit:
            continue
        win = rs[i - rounds + 1:i + 1]
        if any(r[1 if novel else 0] for r in win):
            continue
        if sum(r[2] for r in win) >= fails:
            return i
    return None


def evaluate(runs, rounds, fails, gate, novel, soft):
    tot_ctx = sum(r["ctx"] for r in runs) or 1
    tot_usd = sum(r["usd"] for r in runs) or 1
    row = {"rounds": rounds, "fails": fails, "gate": gate, "progress": "novel" if novel else "write",
           "runs": len(runs), "fired": 0, "fired_success": 0, "false_stop": 0, "benign": 0, "hit": 0,
           "capture_ctx": 0.0, "capture_usd": 0.0, "false_usd": 0.0, "sessions_hit": set()}
    for r in runs:
        i = fire_at(r, rounds, fails, gate, novel, soft)
        if i is None:
            continue
        row["fired"] += 1
        after = r["rounds"][i + 1:]
        if r["outcome"] in SUCCESS:
            row["fired_success"] += 1
            if any(x[6] for x in after):
                row["false_stop"] += 1
                row["false_usd"] += r["usd"] - r["rounds"][i][5]
            else:
                row["benign"] += 1
        else:
            row["hit"] += 1
            row["capture_ctx"] += r["ctx"] - r["rounds"][i][4]
            row["capture_usd"] += r["usd"] - r["rounds"][i][5]
            row["sessions_hit"].add(r["session"])
    row["capture_ctx"] = round(row["capture_ctx"] / tot_ctx, 4)
    row["capture_usd"] = round(row["capture_usd"] / tot_usd, 4)
    row["false_usd"] = round(row["false_usd"] / tot_usd, 4)
    row["sessions_hit"] = len(row["sessions_hit"])
    return row


def proxy(runs):
    """MEASURE.md row 8 rebuilt on these runs: $ after the last write round of non-success runs that wrote."""
    tot = sum(r["usd"] for r in runs) or 1
    s = 0.0
    for r in runs:
        if r["outcome"] in SUCCESS:
            continue
        idx = [i for i, x in enumerate(r["rounds"]) if x[6]]
        if idx:
            s += r["usd"] - r["rounds"][idx[-1]][5]
    return round(s / tot, 4)


def shipped(runs):
    """The shipped rule's own signals (stack_progress.evaluate at the default knobs, the type's soft seed
    as the gate), by outcome: the second route to the grid's (ROUNDS, FAILS, none|soft, write) rows."""
    out = {s: {"fired": 0, "success": 0, "other": 0}
           for s in ("budget", "stall", "stop", "recovered", "first_write")}
    for r in runs:
        for sig in r["signals"]:
            out[sig]["fired"] += 1
            out[sig]["success" if r["outcome"] in SUCCESS else "other"] += 1
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--root", required=True)
    ap.add_argument("--sessions", default="")
    ap.add_argument("--out", default=".claude-work/s4-l5/calib")
    a = ap.parse_args(argv)
    t0 = time.time()
    sessions = {s for s in a.sessions.split(",") if s}
    soft = seed_soft()
    runs = load(a.root, sessions, soft)
    rows = [evaluate(runs, n, f, g, nv, soft)
            for n in GRID_ROUNDS for f in GRID_FAILS if f <= n for g in GATES for nv in (False, True)]
    os.makedirs(a.out, exist_ok=True)
    with open(os.path.join(a.out, "grid.csv"), "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    outc = {}
    for r in runs:
        outc[r["outcome"]] = outc.get(r["outcome"], 0) + 1
    briefs = sum(1 for r in runs if r["brief"])
    summary = {"sessions": len({r["session"] for r in runs}), "runs": len(runs), "outcomes": outc,
               "success": sum(v for k, v in outc.items() if k in SUCCESS), "brief_budgets": briefs,
               "ctx": sum(r["ctx"] for r in runs), "usd": round(sum(r["usd"] for r in runs), 2),
               "proxy_after_last_write": proxy(runs), "shipped": shipped(runs),
               "seconds": round(time.time() - t0, 1)}
    by = {(r["rounds"], r["fails"], r["gate"], r["progress"]): r for r in rows}
    stall, stop = by[(sp.ROUNDS, sp.FAILS, "none", "write")], by[(sp.ROUNDS, sp.FAILS, "soft", "write")]
    summary["routes_agree"] = (stall["fired"] == summary["shipped"]["stall"]["fired"]
                               and stop["fired"] == summary["shipped"].get("stop", {}).get("fired", 0))
    with open(os.path.join(a.out, "summary.json"), "w") as fh:
        json.dump(summary, fh, indent=1, sort_keys=True)
    print(json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
