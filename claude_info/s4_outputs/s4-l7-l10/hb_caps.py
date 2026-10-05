# /// script
# requires-python = ">=3.10"
# ///
"""Offline: apply stack_report.parse/check (main 7d12c58) to the final hand-back of every subagent run in the
frozen transcripts; aggregates by role class. Read-only on the data."""
import glob, json, os, statistics as st, sys
sys.path.insert(0, "/Users/pmrj/ZDone/claude-agent-stack/dot-claude/hooks")
import stack_report as sr  # noqa: E402

P = "/Users/pmrj/ZDone/claude-agent-stack/.claude-work/context-diet/data/transcripts/projects"
rows = []
for f in glob.glob(P + "/**/subagents/agent-*.jsonl", recursive=True):
    meta = f[:-6] + ".meta.json"
    try:
        md = json.load(open(meta)); atype = md.get("agentType"); depth = md.get("spawnDepth")
    except Exception:
        atype = None; depth = None
    seg = {"text": None, "hb": None, "ctx": 0}
    segs = []
    for line in open(f, encoding="utf-8", errors="replace"):
        try:
            r = json.loads(line)
        except Exception:
            continue
        m = r.get("message") or {}
        c = m.get("content")
        if r.get("type") == "user":
            txt = c if isinstance(c, str) else "".join(b.get("text", "") for b in c or [] if isinstance(b, dict) and b.get("type") == "text")
            if txt and not txt.lstrip().startswith(("<system-reminder>", "<task-notification>")):
                if seg["text"] or seg["hb"]:
                    segs.append(seg)
                seg = {"text": None, "hb": None, "ctx": 0}
        elif r.get("type") == "assistant" and isinstance(c, list):
            u = m.get("usage") or {}
            seg["ctx"] = (u.get("input_tokens") or 0) + (u.get("cache_creation_input_tokens") or 0) + (u.get("cache_read_input_tokens") or 0) or seg["ctx"]
            t = "".join(b.get("text", "") for b in c if b.get("type") == "text")
            if t.strip():
                seg["text"] = t
            for b in c:
                if b.get("type") == "tool_use" and b.get("name") == "SubagentHandback":
                    seg["hb"] = (b.get("input") or {}).get("message")
    if seg["text"] or seg["hb"]:
        segs.append(seg)
    for s in segs:
        text = s["hb"] if isinstance(s["hb"], str) and s["hb"].strip() else s["text"]
        p = sr.parse(text)
        chk = sr.check(p, atype, text)
        rows.append(dict(type=atype, cls=chk["class"], status=p["status"], fmt=p["format"], via="handback" if s["hb"] else "text", depth=depth, ctx=s["ctx"],
                         chars=len(text), counted=chk["counted"], cap=chk["cap"], hard=chk["hard"], soft=chk["soft"]))

def q(xs, p):
    xs = sorted(xs); return xs[min(len(xs) - 1, int(p * len(xs)))] if xs else None

print("runs", len(rows), "via handback", sum(r["via"] == "handback" for r in rows))
print("class n med p90 over1.0x over1.5x excess_chars_over_cap(sum) no_status")
for cls in ["lookup", "builder", "coord", "review", "plan", "ALL"]:
    g = [r for r in rows if cls == "ALL" or r["cls"] == cls]
    if not g: continue
    c = [r["counted"] for r in g]
    o1 = sum(r["counted"] > r["cap"] for r in g); o15 = sum(r["counted"] > 1.5 * r["cap"] for r in g)
    ex = sum(max(0, r["counted"] - r["cap"]) for r in g)
    ns = sum("no_status" in r["hard"] for r in g)
    print(cls, len(g), int(st.median(c)), q(c, .9), f"{o1} ({o1/len(g):.0%})", f"{o15} ({o15/len(g):.0%})", ex, ns)
print("builder by status:")
for stt in ["done", "partial", "blocked", None]:
    g = [r for r in rows if r["cls"] == "builder" and r["status"] == stt]
    if g:
        c = [r["counted"] for r in g]
        print(" ", stt, len(g), int(st.median(c)), q(c, .9), sum(r["counted"] > r["cap"] for r in g))
print("clean-finish (header) builder done: n", sum(1 for r in rows if r["cls"] == "builder" and r["fmt"] == "clean"))
print("by via: ", {v: (len(g := [r for r in rows if r["via"] == v]), int(st.median([r["counted"] for r in g])), sum(r["counted"] > r["cap"] for r in g)) for v in ("handback", "text")})
json.dump(rows, open(os.path.join(os.path.dirname(__file__), "hb_caps_rows.json"), "w"))
# break-even of a one-shot restate (child rewrites once) vs carrying the excess in the parent.
# token-equivalents in input-price units: cache read 0.1, cache write 1.25, output 5 (Opus list ratios).
OUT_REWRITE = 1.0   # rewritten report ~ cap-sized output, in tokens = cap/3
for name, reads in (("to_main", 130), ("to_sub", 18.5)):
    g = [r for r in rows if (r["depth"] == 1) == (name == "to_main") and r["counted"] > r["cap"]]
    win = 0; net = 0.0
    for r in g:
        ex = (r["counted"] - r["cap"]) / 3
        save = ex * (1.25 + reads * 0.1)
        cost = r["ctx"] * 0.1 + (r["cap"] / 3) * 5 + 200 * 5   # re-read context, rewrite, hook reason+thinking
        win += save > cost; net += save - cost
    print(name, "over-cap", len(g), "restate pays off", win, "net token-eq", int(net), "median ctx", int(st.median([r["ctx"] for r in g])) if g else None)
