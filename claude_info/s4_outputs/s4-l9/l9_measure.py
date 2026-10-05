# /// script
# requires-python = ">=3.11"
# ///
"""L9 candidate measurement on the 5 frozen sessions (read-only, aggregates only).

A) plan files written (plan.md / plan.dag.json under .claude-work): count, writers, sizes, heading shapes,
   pairwise shape similarity (Jaccard on normalised H2/H3 headings) and clusters at J >= 0.5.
B) planning spawns (planner, plan-reviewer, orchestrator): runs and list $ (Opus 5.5 prices, MEASURE.md 1.2).
C) Agent briefs written by any thread: share of brief lines that recur (normalised) in >= 5 briefs,
   i.e. the text a brief template would let the writer skip; priced as output at the writer's model.
Usage: uv run --script l9_measure.py [--root PROJECTS] > out.txt
"""
import argparse, glob, json, re, collections, itertools

ROOT = "/Users/pmrj/ZDone/claude-agent-stack/.claude-work/context-diet/data/transcripts/projects"
SESS = ["4e2da3ce", "fae82d02", "e4fe4e24", "a59eca09", "68541e7b"]
TOTAL_USD = 1282.0  # MEASURE.md section 0
P = {"opus": (4, 20, 5, 8, 0.20), "sonnet": (2, 10, 2.5, 4, 0.20)}
PLAN_RE = re.compile(r"(\.claude-work/\S*/plan(\.dag)?\.(md|json)$|/plan\.md$)")
TOK_PER_CHAR = 0.415  # MEASURE.md 1.3
NUM = re.compile(r"[0-9a-f]{7,40}|\d+")


def price(model, u):
    i, o, w5, w1, cr = P["sonnet" if "sonnet" in (model or "") else "opus"]
    w1t = (u.get("cache_creation") or {}).get("ephemeral_1h_input_tokens", 0) or 0
    w5t = (u.get("cache_creation_input_tokens", 0) or 0) - w1t
    return (u.get("input_tokens", 0) * i + u.get("output_tokens", 0) * o + w5t * w5 + w1t * w1
            + u.get("cache_read_input_tokens", 0) * cr) / 1e6


def records(path):
    with open(path, errors="replace") as fh:
        for line in fh:
            try:
                yield json.loads(line)
            except Exception:
                pass


def norm_heading(h):
    h = re.sub(r"[`*_]", "", h.lower())
    h = re.sub(r"^[\w.§()]{0,4}[.)]\s+", "", h)
    h = re.sub(r"\d+", "#", h)
    return re.sub(r"\s+", " ", h).strip(" :—-")


def norm_line(l):
    return re.sub(r"\s+", " ", NUM.sub("#", l.strip().lower()))


def out_usd(chars, model):
    return chars * TOK_PER_CHAR * (10 if "sonnet" in (model or "") else 20) / 1e6


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=ROOT)
    a = ap.parse_args()
    files = []
    for s in SESS:
        files += [(s, "main", f) for f in glob.glob(f"{a.root}/*/{s}*.jsonl")]
        files += [(s, "sub", f) for f in glob.glob(f"{a.root}/*/{s}*/subagents/agent-*.jsonl")]
    plans, spawn_cost, briefs = [], collections.defaultdict(list), []
    for s, scope, f in files:
        atype = "main"
        if scope == "sub":
            try:
                atype = json.load(open(f[:-6] + ".meta.json")).get("agentType", "?")
            except Exception:
                atype = "?"
        usage, model = {}, None
        for r in records(f):
            m = r.get("message") or {}
            if r.get("type") != "assistant" or not isinstance(m, dict):
                continue
            model = m.get("model") or model
            if m.get("id"):
                u = m.get("usage") or {}
                prev = usage.get(m["id"], (None, {}))[1]
                d = {k: max(u.get(k, 0) or 0, prev.get(k, 0) or 0) for k in
                     ("input_tokens", "output_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")}
                d["cache_creation"] = u.get("cache_creation") or prev.get("cache_creation") or {}
                usage[m["id"]] = (m.get("model"), d)
            for c in m.get("content") or []:
                if not isinstance(c, dict) or c.get("type") != "tool_use":
                    continue
                inp = c.get("input") or {}
                if c.get("name") in ("Write", "Edit", "MultiEdit") and PLAN_RE.search(inp.get("file_path", "") or ""):
                    body = inp.get("content") or inp.get("new_string") or ""
                    heads = [norm_heading(h) for h in re.findall(r"^#{2,3}\s+(.+)$", body, re.M)]
                    plans.append(dict(s=s, atype=atype, tool=c["name"], path=inp["file_path"], chars=len(body),
                                      heads=heads, model=model))
                if c.get("name") in ("Agent", "Task"):
                    briefs.append(dict(s=s, atype=atype, model=model, prompt=inp.get("prompt", "") or "",
                                       sub=inp.get("subagent_type", "") or ""))
        if scope == "sub":
            spawn_cost[atype].append((s, sum(price(mo, u) for mo, u in usage.values())))

    print("## A. plan files")
    writes = [p for p in plans if p["tool"] == "Write"]
    print(f"plan tool calls: {len(plans)} (Write {len(writes)}, Edit {len(plans) - len(writes)}); "
          f"sessions {len({p['s'] for p in plans})}; by session {dict(collections.Counter(p['s'] for p in writes))}")
    print("writers (all plan calls):", collections.Counter(p["atype"] for p in plans).most_common())
    print("distinct plan paths written:", len({p['path'] for p in writes}))
    wc = sorted(p["chars"] for p in writes)
    if wc:
        usd = sum(out_usd(p["chars"], p["model"]) for p in writes)
        print(f"Write chars: median={wc[len(wc)//2]} sum={sum(wc)}; output $ of all plan Writes ${usd:.2f} "
              f"= {100*usd/TOTAL_USD:.3f}% of total")
    last = {}
    for p in writes:
        if len(p["heads"]) >= 3:
            last[p["path"]] = p
    ps = list(last.values())
    print(f"distinct plans with >= 3 H2/H3 headings: {len(ps)}")
    hc = collections.Counter(h for p in ps for h in set(p["heads"]))
    print("headings in >= 3 distinct plans:", [(h, n) for h, n in hc.most_common(30) if n >= 3])
    sims = [len(set(x["heads"]) & set(y["heads"])) / len(set(x["heads"]) | set(y["heads"]))
            for x, y in itertools.combinations(ps, 2)]
    if sims:
        sims.sort()
        print(f"pairwise Jaccard: n={len(sims)} median={sims[len(sims)//2]:.2f} p90={sims[int(.9*len(sims))]:.2f} "
              f"share>=0.5={sum(j >= .5 for j in sims)/len(sims):.3f}")
    parent = list(range(len(ps)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i
    for x, y in itertools.combinations(range(len(ps)), 2):
        A, B = set(ps[x]["heads"]), set(ps[y]["heads"])
        if len(A & B) / len(A | B) >= 0.5:
            parent[find(x)] = find(y)
    cl = collections.defaultdict(list)
    for i in range(len(ps)):
        cl[find(i)].append(ps[i])
    big = sorted((v for v in cl.values() if len(v) >= 2), key=len, reverse=True)
    print("clusters (size, sessions, $ of their Writes):",
          [(len(v), len({p['s'] for p in v}), round(sum(out_usd(p['chars'], p['model']) for p in v), 2)) for v in big])
    for v in big[:4]:
        print("  common:", sorted(set.intersection(*(set(p["heads"]) for p in v)))[:10])

    print("\n## B. planning spawns")
    for t in ("planner", "plan-reviewer", "orchestrator"):
        runs = spawn_cost.get(t, [])
        tot = sum(c for _, c in runs)
        bys = collections.defaultdict(float)
        for s, c in runs:
            bys[s] += c
        print(f"{t}: runs={len(runs)} sessions={len(bys)} usd={tot:.2f} ({100*tot/TOTAL_USD:.2f}%) "
              f"by session={ {k: round(v, 2) for k, v in bys.items()} }")
    pb = [b for b in briefs if b["sub"] == "planner"]
    print(f"planner briefs: {len(pb)}; first line shapes:",
          collections.Counter(norm_line(b["prompt"].splitlines()[0] if b["prompt"] else "")[:40] for b in pb).most_common(6))

    print("\n## C. brief boilerplate")
    print(f"briefs: {len(briefs)}; writers: {collections.Counter(b['atype'] for b in briefs).most_common(6)}")
    lc = collections.Counter(l for b in briefs for l in {norm_line(x) for x in b["prompt"].splitlines() if len(x.strip()) >= 20})
    rec = {l for l, n in lc.items() if n >= 5}
    tot_chars = sum(len(b["prompt"]) for b in briefs)
    rep_chars = sum(len(x) for b in briefs for x in b["prompt"].splitlines() if norm_line(x) in rec)
    rep_usd = sum(out_usd(len(x), b["model"]) for b in briefs for x in b["prompt"].splitlines() if norm_line(x) in rec)
    by_w = collections.Counter()
    for b in briefs:
        by_w["main" if b["atype"] == "main" else "sub"] += sum(len(x) for x in b["prompt"].splitlines() if norm_line(x) in rec)
    all_usd = sum(out_usd(len(b["prompt"]), b["model"]) for b in briefs)
    print(f"all brief output $ {all_usd:.2f} ({100*all_usd/TOTAL_USD:.2f}%); brief chars={tot_chars}; "
          f"in lines recurring in >= 5 briefs: {rep_chars} ({100*rep_chars/max(tot_chars, 1):.1f}%), by writer {dict(by_w)}; "
          f"output $ {rep_usd:.2f} = {100*rep_usd/TOTAL_USD:.3f}% of total")
    print("recurring lines: count, first 80 chars")
    for l, n in lc.most_common(10):
        if n >= 5:
            print(f"  {n:3d}  {l[:80]}")


if __name__ == "__main__":
    main()
