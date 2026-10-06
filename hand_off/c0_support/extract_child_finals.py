# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Final text of EVERY prompt-tagged agent segment (roots and descendants) for COMPARE_compact M1b/M4.

The frozen collector (stats_before/tools/collect_b0v2.py) writes final_*.txt only for ROOT segments, so the hand-backs of an
orchestrator's children are not extracted. This wrapper adds no parsing of its own for report text: it imports the frozen
collector file unchanged, uses its `stream_agent` and the collector's own final-text rule (collect_b0v2.py main(), the
`final_text` lines), and takes the run tags (prompt id, root, kind) from the collector's runs.csv. The only new code
counts the parent's API calls after each hand-back (M4), with the collector's call key `message.id|requestId`.

  uv run --script extract_child_finals.py --session <SID> --collected <dir with the collector's runs.csv> \\
      --repo <checkout the session ran in> [--projects ~/.claude/projects] [--out <dir>]

Writes <out>/handbacks.csv (no text) and <out>/handbacks/<pid>/final_<agent>_s<seg>.txt. Read-only on transcripts.
"""
import argparse
import csv
import hashlib
import importlib.util
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
COLLECTOR = os.path.normpath(os.path.join(HERE, "..", "..", "stats_before", "tools", "collect_b0v2.py"))
if not os.path.exists(COLLECTOR):
    COLLECTOR = "/Users/pmrj/ZDone/claude-agent-stack/claude_next_steps/work_carried/stats_before/tools/collect_b0v2.py"


def load_collector():
    spec = importlib.util.spec_from_file_location("collect_b0v2_frozen", COLLECTOR)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def call_times(path):
    """{call key: first timestamp} for assistant records with usage (the collector's turn definition)."""
    out = {}
    try:
        fh = open(path, encoding="utf-8", errors="replace")
    except OSError:
        return None
    with fh:
        for line in fh:
            try:
                r = json.loads(line)
            except ValueError:
                continue
            if r.get("type") != "assistant":
                continue
            m = r.get("message") if isinstance(r.get("message"), dict) else {}
            if not isinstance(m.get("usage"), dict) or not r.get("timestamp"):
                continue
            key = f"{m.get('id')}|{r.get('requestId')}"
            if key == "None|None":
                key = "uuid|" + str(r.get("uuid"))
            out.setdefault(key, r["timestamp"])
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--session", required=True)
    ap.add_argument("--collected", required=True, help="the --out dir of collect_b0v2.py for this session (runs.csv)")
    ap.add_argument("--repo", required=True)
    ap.add_argument("--projects", default=os.path.join(os.path.expanduser("~"), ".claude", "projects"))
    ap.add_argument("--project", help="project slug under --projects (default: derived from --repo, as the collector does)")
    ap.add_argument("--out", help="default: --collected")
    a = ap.parse_args()
    col = load_collector()
    out = a.out or a.collected
    slug = a.project or re.sub(r"[^A-Za-z0-9]", "-", a.repo)
    pdir = os.path.join(a.projects, slug)
    sub = os.path.join(pdir, a.session, "subagents")
    rows = [r for r in csv.DictReader(open(os.path.join(a.collected, "runs.csv"), newline="", encoding="utf-8"))
            if r["session"] == a.session and r["kind"] == "prompt"]
    segs_cache, times_cache, recs = {}, {}, []
    for r in sorted(rows, key=lambda x: (x["prompt_id"], x["start"], x["agent_id"], int(x["seg"]))):
        aid, i = r["agent_id"], int(r["seg"])
        if aid not in segs_cache:
            segs_cache[aid] = col.stream_agent(os.path.join(sub, f"agent-{aid}.jsonl"))
        segs = [s for s in segs_cache[aid] if s["start"]]
        if i >= len(segs) or r["open"] == "1":
            continue
        sg = segs[i]
        final_text = ""
        if sg["last_kind"] == "end" and sg["last_key"]:  # identical to collect_b0v2.py main()
            final_text = "\n".join(sg["texts"].get(sg["last_key"], [])).strip()
        if not final_text:
            continue
        sm = col.STATUS_RE.search(final_text)
        par = r["parent_agent_id"] or "main"
        ppath = os.path.join(pdir, f"{a.session}.jsonl") if par == "main" else os.path.join(sub, f"agent-{par}.jsonl")
        if par not in times_cache:
            times_cache[par] = call_times(ppath)
        pt = times_cache[par]
        end = col.parse_ts(sg["end"])
        later = None if pt is None else sum(1 for v in pt.values() if col.parse_ts(v) > end)
        d = os.path.join(out, "handbacks", r["prompt_id"])
        os.makedirs(d, exist_ok=True)
        fn = os.path.join(d, f"final_{aid}_s{i}.txt")
        with open(fn, "w", encoding="utf-8") as fh:
            fh.write(final_text + "\n")
        recs.append(dict(session=a.session, prompt_id=r["prompt_id"], description=r["description"], agent_id=aid, seg=i,
                         agent_type=r["agent_type"], depth=r["depth"], parent=par, is_root=r["is_root"], end=r["end"],
                         report_chars=len(final_text), report_sha8=hashlib.sha256(final_text.encode()).hexdigest()[:8],
                         status_regex=sm.group(1).lower() if sm else "none",
                         later_parent_calls="" if later is None else later,
                         parent_calls_total="" if pt is None else len(pt), file=os.path.relpath(fn, out)))
    with open(os.path.join(out, "handbacks.csv"), "w", newline="", encoding="utf-8") as fh:
        cols = list(recs[0].keys()) if recs else ["session"]
        w = csv.DictWriter(fh, cols, lineterminator="\n")
        w.writeheader()
        w.writerows(recs)
    sha = hashlib.sha256(open(COLLECTOR, "rb").read()).hexdigest()
    print(f"collector {COLLECTOR} sha256 {sha}")
    print(f"hand-backs: {len(recs)} (roots {sum(1 for x in recs if x['is_root'] == '1')}); wrote {os.path.join(out, 'handbacks.csv')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
