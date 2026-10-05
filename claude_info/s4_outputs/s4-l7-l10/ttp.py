# /// script
# requires-python = ">=3.10"
# ///
"""Builders only: API calls before the first write/delegate (exploration length) and total calls, by outcome."""
import glob, json, sys, statistics as st
sys.path.insert(0, "/Users/pmrj/ZDone/claude-agent-stack/dot-claude/hooks")
import stack_report as sr
P = "/Users/pmrj/ZDone/claude-agent-stack/.claude-work/context-diet/data/transcripts/projects"
PROG = {"Edit", "Write", "NotebookEdit", "Agent", "Task", "SendMessage"}
out = []
for f in glob.glob(P + "/**/subagents/agent-*.jsonl", recursive=True):
    try: atype = json.load(open(f[:-6] + ".meta.json")).get("agentType")
    except Exception: continue
    if sr.role_class(atype) != "builder": continue
    segs, cur = [], None
    def new(): return {"ids": [], "first": None, "text": None, "hb": None}
    cur = new()
    for line in open(f, errors="replace"):
        try: r = json.loads(line)
        except Exception: continue
        m = r.get("message") or {}; c = m.get("content")
        if r.get("type") == "user":
            t = c if isinstance(c, str) else "".join(b.get("text", "") for b in c or [] if isinstance(b, dict) and b.get("type") == "text")
            if t and not t.lstrip().startswith(("<system-reminder>", "<task-notification>")):
                if cur["ids"]: segs.append(cur)
                cur = new()
        elif r.get("type") == "assistant" and isinstance(c, list):
            mid = m.get("id")
            if mid and (not cur["ids"] or cur["ids"][-1] != mid): cur["ids"].append(mid)
            for b in c:
                if b.get("type") == "tool_use":
                    if b.get("name") in PROG and cur["first"] is None: cur["first"] = len(cur["ids"])
                    if b.get("name") == "SubagentHandback": cur["hb"] = (b.get("input") or {}).get("message")
                elif b.get("type") == "text" and b.get("text", "").strip(): cur["text"] = b["text"]
    if cur["ids"]: segs.append(cur)
    for s in segs:
        txt = s["hb"] or s["text"] or ""
        status = sr.parse(txt)["status"] if txt else None
        ok = status == "done" or (status is None and sr.parse(txt)["format"] == "clean")
        out.append((atype, ok, s["first"], len(s["ids"])))
def q(x, p): x = sorted(x); return x[min(len(x)-1, int(p*len(x)))]
for ok in (True, False):
    g = [o for o in out if o[1] == ok]; w = [o[2] for o in g if o[2] is not None]
    print("success" if ok else "other", "n", len(g), "never-wrote", sum(o[2] is None for o in g),
          "calls-to-first-write med/p90", st.median(w), q(w, .9), "share of calls before first write", round(sum(w)/sum(o[3] for o in g if o[2] is not None), 2))
