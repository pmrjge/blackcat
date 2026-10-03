# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Per-run metrics of a baseline campaign from Claude Code subagent transcripts.

Read-only on transcripts, the delegation ledger and ~/.claude. Streams each transcript line by line.
Writes (idempotent, overwritten on every run):
  <out>/runs.csv                          one row per agent SEGMENT (a spawn, or a resume of a finished agent)
  <out>/run/<prompt_id>/final_<agent>.txt  final assistant message of each root segment of a prompt run
                                          (for graders); a multi-segment root also gets final_<agent>_s<k>.txt
runs.csv holds ids and numbers only: no prompt text, no file contents (the description is the dispatch label).

  uv run --script collect.py [--session SID ...|all] [--since ISO] [--campaign-since ISO]

Definitions
  segment      same as .claude-work/agents-usage/thresholds.py: an agent's run from its first record, or from
               a resume message ("... sent a message while you were working" after it ended its turn), to
               the next resume. Compaction stays inside the segment.
  turn         one distinct API call (message.id|requestId); a streamed message is several records, the
               maximum of each usage field is kept.
  tool_denied  guard/permission denials (is_error, hook error/Blocked/Refused/...); sandbox_blocks: tool results
               with "Operation not permitted" or a sandbox denial (not counted in tool_denied).
  tokens_*     sums over the segment's turns; tokens_total = input + output + cache_creation + cache_read.
  prompt_id    PNN/PNNN at the start of the Agent description of the root dispatch; children inherit it.
               Only dispatches that start at or after the campaign start count (default: the first agent
               whose description contains "baseline campaign"), because earlier phase-2 work used labels
               like "P10 ..." too; an id must also exist in prompts.csv when that file is present.
  kind         prompt | overhead (root dispatch "T<n> ..." inside the campaign) | other.
  root         the topmost tagged ancestor-or-self; is_root=1 on its segments.
"""
import argparse
import csv
import datetime as dt
import glob
import json
import os
import re
import sys
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
DEFAULT_SESSION = "4e2da3ce-e2f4-4971-aac5-a67f2dcf252e"
HOME = os.path.expanduser("~")
FIELDS = ("input_tokens", "output_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")
RESUME_RE = re.compile(r"^(Another Claude session|The coordinator) sent a message while you were working")
COMPACT_RE = re.compile(r"^This session is being continued from a previous conversation")
TURN_LIMIT_RE = re.compile(r"turn limit", re.I)
PID_RE = re.compile(r"^\s*(P\d{2,3})\b")
OVERHEAD_RE = re.compile(r"^\s*T\d+\b")
STATUS_RE = re.compile(r"^\W*STATUS:\s*(done|partial|blocked)\b", re.I | re.M)
SKILL_PATH_RE = re.compile(r"/skills/([A-Za-z0-9._-]+)/SKILL\.md")
SOFT_RE = re.compile(r"^(?:[^\n]*hook[^\n]*\n)?\s*Soft token limit reached for (this run|this prompt)\b")
DENIED_RE = re.compile(r"hook error|Blocked|Refused|denied|not allowed|cannot widen|No such tool available|"
                       r"doesn't want|permission|isolated git worktree|should return findings", re.I)
SANDBOX_RE = re.compile(r"Operation not permitted|<sandbox_violations>|sandbox (?:restriction|deny|denied|blocked)|denied by (?:the )?sandbox", re.I)
REVIEWERS = {"code-reviewer", "plan-reviewer", "security-auditor", "verifier"}
LIVE_S = 600


def parse_ts(x):
    return dt.datetime.fromisoformat(x.replace("Z", "+00:00"))


def text_of(c):
    if isinstance(c, str):
        return c
    if isinstance(c, list):
        return " ".join(b.get("text", "") for b in c if isinstance(b, dict) and b.get("type") == "text")
    return ""


def blocks_text(c):
    """Texts a hook-context check may see: string content, text blocks, tool_result texts."""
    if isinstance(c, str):
        yield c
    elif isinstance(c, list):
        for b in c:
            if not isinstance(b, dict):
                continue
            if b.get("type") == "text":
                yield b.get("text", "")
            elif b.get("type") == "tool_result":
                yield from blocks_text(b.get("content"))


def strip_reminder(t):
    t = t.lstrip()
    if t.startswith("<system-reminder>"):
        t = t[len("<system-reminder>"):].lstrip()
    return t


# ------------------------------------------------------------------------------ transcript streaming
def new_seg(ts):
    return dict(start=ts, end=ts, calls={}, order=[], tool_names={}, tools=Counter(), skill_calls=[], reads=[],
                agent_calls=[], errors=0, denied=0, sandbox=0, compact_summary=0, compact_boundary=0, soft=0,
                turn_limit=False, last_kind=None, last_key=None, texts={})


def stream_agent(path):
    segs, cur = [], None
    for line in open(path, encoding="utf-8", errors="replace"):
        try:
            r = json.loads(line)
        except ValueError:
            continue
        ts = r.get("timestamp")
        t = r.get("type")
        m = r.get("message") if isinstance(r.get("message"), dict) else {}
        c = m.get("content")
        is_tr = isinstance(c, list) and any(isinstance(b, dict) and b.get("type") == "tool_result" for b in c)
        if t == "user" and not is_tr:
            txt = text_of(c)
            if cur is None or (RESUME_RE.match(txt) and cur["last_kind"] in ("end", "tr")):
                tl = cur is not None and cur["last_kind"] == "tr" and bool(TURN_LIMIT_RE.search(txt[:300]))
                if tl:
                    cur["turn_limit"] = True
                cur = new_seg(ts)
                segs.append(cur)
            elif COMPACT_RE.match(txt):
                cur["compact_summary"] += 1
        if cur is None:
            cur = new_seg(ts)
            segs.append(cur)
        if ts:
            if cur["start"] is None:
                cur["start"] = ts
            cur["end"] = ts
        if t == "system" and r.get("subtype") == "compact_boundary":
            cur["compact_boundary"] += 1
        elif t == "attachment":
            a = r.get("attachment") if isinstance(r.get("attachment"), dict) else {}
            if a.get("type") == "hook_additional_context":
                ctx = a.get("content")
                items = [x for x in ctx if isinstance(x, str)] if isinstance(ctx, list) else list(blocks_text(ctx))
                cur["soft"] += sum(1 for s_ in items if SOFT_RE.match(strip_reminder(s_)))
        elif t == "user":
            if is_tr:
                cur["last_kind"] = "tr"
                for b in c:
                    if not isinstance(b, dict) or b.get("type") != "tool_result":
                        continue
                    body = b.get("content")
                    body = body if isinstance(body, str) else text_of(body)
                    sb = bool(SANDBOX_RE.search(body[:4000]))
                    cur["sandbox"] += sb
                    if b.get("is_error"):
                        cur["errors"] += 1
                        if not sb and DENIED_RE.search(body[:400]):
                            cur["denied"] += 1
                cur["soft"] += sum(1 for x in blocks_text(c) if SOFT_RE.match(strip_reminder(x)))
            else:
                if any(SOFT_RE.match(strip_reminder(x)) for x in blocks_text(c)):
                    cur["soft"] += 1
        elif t == "assistant":
            u = m.get("usage")
            if not isinstance(u, dict):
                continue
            key = f"{m.get('id')}|{r.get('requestId')}"
            if key == "None|None":
                key = "uuid|" + str(r.get("uuid"))
            call = cur["calls"].get(key)
            if call is None:
                call = cur["calls"][key] = {f: 0 for f in FIELDS}
                call["model"] = m.get("model")
                call["has_tool"] = False
                cur["order"].append(key)
            for f in FIELDS:
                call[f] = max(call[f], int(u.get(f) or 0))
            for b in c if isinstance(c, list) else []:
                if not isinstance(b, dict):
                    continue
                if b.get("type") == "tool_use":
                    call["has_tool"] = True
                    tid, name, inp = b.get("id"), b.get("name"), b.get("input") or {}
                    if tid in cur["tool_names"]:
                        continue
                    cur["tool_names"][tid] = name
                    cur["tools"][name] += 1
                    if name == "Skill":
                        cur["skill_calls"].append(str(inp.get("skill") or inp.get("name") or ""))
                    elif name == "Read":
                        mm = SKILL_PATH_RE.search(str(inp.get("file_path") or ""))
                        if mm:
                            cur["reads"].append(mm.group(1))
                    elif name == "Bash":
                        cmd = str(inp.get("command") or "")
                        if re.search(r"\b(cat|head|tail|sed|bat|less|rg|grep|awk)\b", cmd):
                            for mm in SKILL_PATH_RE.finditer(cmd):
                                cur["reads"].append(mm.group(1))
                    elif name in ("Agent", "Task"):
                        cur["agent_calls"].append((tid, str(inp.get("subagent_type") or "")))
                elif b.get("type") == "text" and b.get("text"):
                    lst = cur["texts"].setdefault(key, [])
                    if b["text"] not in lst:
                        lst.append(b["text"])
            cur["last_kind"] = "tool" if call["has_tool"] else "end"
            cur["last_key"] = key
    return segs


# ------------------------------------------------------------------------------ lookups
def read_json(path):
    try:
        with open(path) as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def frontmatter_max_turns(claude_dir):
    out = {}
    for f in glob.glob(os.path.join(claude_dir, "agents", "*.md")):
        try:
            head = open(f, encoding="utf-8").read(8192)
        except OSError:
            continue
        if not head.startswith("---"):
            continue
        fm = head.split("\n---", 1)[0]
        mm = re.search(r"^maxTurns:\s*(\d+)\s*$", fm, re.M)
        out[os.path.basename(f)[:-3]] = int(mm.group(1)) if mm else None
    return out


def hidden_skills(repo, claude_dir):
    """Skills under <repo>/dot-claude/skills that are not installed in ~/.claude/skills, or marked
    hidden (user-invocable-only / off) in a settings.json skillOverrides."""
    def names(d):
        return {os.path.basename(os.path.dirname(p)) for p in glob.glob(os.path.join(d, "*", "SKILL.md"))}
    repo_s, inst_s = names(os.path.join(repo, "dot-claude", "skills")), names(os.path.join(claude_dir, "skills"))
    over = set()
    for sj in (os.path.join(repo, "dot-claude", "settings.json"), os.path.join(claude_dir, "settings.json")):
        so = (read_json(sj) or {}).get("skillOverrides") or {}
        over |= {k for k, v in so.items() if v in ("user-invocable-only", "off")}
    return (repo_s - inst_s) | over, repo_s, inst_s, over


def load_csv(path):
    try:
        with open(path, newline="", encoding="utf-8") as fh:
            return list(csv.DictReader(fh))
    except OSError:
        return []


def load_ledger(state, sid):
    d = os.path.join(state, sid)
    spawns = {}
    for f in glob.glob(os.path.join(d, "spawns", "*.json")):
        j = read_json(f)
        if j and j.get("tid"):
            spawns[j["tid"]] = j
    registry = {os.path.basename(f)[:-5]: read_json(f) or {} for f in glob.glob(os.path.join(d, "agents", "*.json"))}
    soft = (read_json(os.path.join(d, "budget.json")) or {}).get("soft_agents") or {}
    return spawns, registry, soft


def iso(ts):
    return ts.replace("+00:00", "Z") if ts else ""


# ------------------------------------------------------------------------------ main
def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--session", action="append", help="session id (repeatable) or 'all'; default the baseline session")
    ap.add_argument("--since", help="only segments starting at or after this ISO timestamp (UTC if no zone)")
    ap.add_argument("--campaign-since", help="ISO timestamp: prompt ids and T-overhead count only for dispatches from "
                    "here on (default: first agent described 'baseline campaign'; 'none' = no window)")
    ap.add_argument("--projects", default=os.path.join(HOME, ".claude", "projects"))
    ap.add_argument("--claude-dir", default=os.path.join(HOME, ".claude"))
    ap.add_argument("--state-dir", default=os.path.join(HOME, ".local", "state", "claude-agent-stack"))
    ap.add_argument("--repo", default=REPO)
    ap.add_argument("--out", default=HERE)
    ap.add_argument("--project", help="project slug dir under --projects (default: derived from --repo)")
    a = ap.parse_args()

    slug = a.project or re.sub(r"[^A-Za-z0-9]", "-", a.repo)
    pdir = os.path.join(a.projects, slug)
    sessions = a.session or [DEFAULT_SESSION]
    if sessions == ["all"]:
        sessions = sorted(os.path.basename(p)[:-6] for p in glob.glob(os.path.join(pdir, "*.jsonl")))
    since = parse_ts(a.since if re.search(r"(Z|[+-]\d\d:?\d\d)$", a.since) else a.since + "+00:00") if a.since else None

    max_turns = frontmatter_max_turns(a.claude_dir)
    hidden, repo_skills, inst_skills, overridden = hidden_skills(a.repo, a.claude_dir)
    prompts = {r["id"]: r for r in load_csv(os.path.join(a.out, "prompts.csv"))}
    grades = {r["id"]: r for r in load_csv(os.path.join(a.out, "grades.csv"))}

    rows, finals = [], []
    for sid in sessions:
        sub = os.path.join(pdir, sid, "subagents")
        spawns, registry, soft_snap = load_ledger(a.state_dir, sid)
        agents = {}
        for f in sorted(glob.glob(os.path.join(sub, "agent-*.jsonl"))):
            aid = os.path.basename(f)[6:-6]
            meta = read_json(f[:-6] + ".meta.json") or {}
            reg = registry.get(aid) or {}
            segs = stream_agent(f)
            agents[aid] = dict(
                path=f, segs=segs, type=meta.get("agentType") or reg.get("type") or "",
                # stats_before patch: newer Claude Code stores "<agentType>: <description>" in meta.json
                desc=re.sub(r"^" + re.escape((meta.get("agentType") or reg.get("type") or "") + ": "), "",
                            meta.get("description") or "") if (meta.get("agentType") or reg.get("type")) else (meta.get("description") or ""),
                parent=meta.get("parentAgentId") or reg.get("parent") or "",
                depth=meta.get("spawnDepth") if meta.get("spawnDepth") is not None else reg.get("depth"),
                mtime=os.path.getmtime(f), start=(segs[0]["start"] if segs else None))

        # campaign window
        if a.campaign_since and a.campaign_since.lower() == "none":
            camp = None
        elif a.campaign_since:
            camp = parse_ts(a.campaign_since if re.search(r"(Z|[+-]\d\d:?\d\d)$", a.campaign_since)
                            else a.campaign_since + "+00:00")
        else:
            st = [parse_ts(v["start"]) for v in agents.values()
                  if v["start"] and re.search(r"baseline campaign", v["desc"], re.I)]
            camp = min(st) if st else None

        def tag(aid):
            v = agents[aid]
            if camp is not None and (not v["start"] or parse_ts(v["start"]) < camp):
                return None
            mm = PID_RE.match(v["desc"])
            if mm and (not prompts or mm.group(1) in prompts):
                return ("prompt", mm.group(1))
            if camp is not None and OVERHEAD_RE.match(v["desc"]):
                return ("overhead", "")
            return None

        def root_of(aid):
            found, seen = None, set()
            cur = aid
            while cur in agents and cur not in seen:
                seen.add(cur)
                tg = tag(cur)
                if tg:
                    found = (cur, tg)
                cur = agents[cur]["parent"]
            return found

        for aid, v in agents.items():
            rt = root_of(aid)
            v["root"], v["kind"], v["pid"] = (rt[0], rt[1][0], rt[1][1]) if rt else ("", "other", "")

        for aid, v in agents.items():
            live_file = (dt.datetime.now(dt.timezone.utc).timestamp() - v["mtime"]) < LIVE_S
            mt = max_turns.get(v["type"])
            segs = v["segs"]
            prev_limit = False
            for i, sg in enumerate(segs):
                if not sg["start"]:
                    continue
                if since and parse_ts(sg["start"]) < since:
                    continue
                calls = [sg["calls"][k] for k in sg["order"]]
                tot = {f: sum(c[f] for c in calls) for f in FIELDS}
                total = sum(tot.values())
                turns = len(calls)
                models = []
                for c in calls:
                    mdl = c.get("model")
                    if mdl and mdl != "<synthetic>" and mdl not in models:
                        models.append(mdl)
                last = i == len(segs) - 1
                open_ = last and live_file and sg["last_kind"] in ("tool", "tr")
                final_text = ""
                if sg["last_kind"] == "end" and sg["last_key"]:
                    final_text = "\n".join(sg["texts"].get(sg["last_key"], [])).strip()
                sm = STATUS_RE.search(final_text)
                status = sm.group(1).lower() if sm else "none"
                tool_n = sum(sg["tools"].values())
                tools_s = ";".join(f"{k}:{n}" for k, n in sorted(sg["tools"].items(), key=lambda kv: (-kv[1], kv[0])))
                # spawns: ledger record by tool_use id (= tid), fallback to the call's subagent_type
                child_types, ledger_hits = [], 0
                for tid, stype in sg["agent_calls"]:
                    rec = spawns.get(tid)
                    ledger_hits += rec is not None
                    child_types.append((rec or {}).get("type") or stype or "?")
                reads = list(dict.fromkeys(sg["reads"]))
                skills = [s for s in sg["skill_calls"] if s]
                used_names = set(skills) | {s.split(":")[-1] for s in skills} | set(reads)
                exp_raw = (prompts.get(v["pid"]) or {}).get("expected_skills", "") if v["pid"] else ""
                exp = [e.strip().rstrip("*").strip() for e in exp_raw.split(";") if e.strip()]
                used = [e for e in exp if e in used_names]
                missed = [e for e in exp if e not in used_names]
                soft_hits = sg["soft"]
                snap = soft_snap.get(aid)
                if isinstance(snap, (int, float)) and soft_hits == 0:
                    nxt = parse_ts(segs[i + 1]["start"]).timestamp() if i + 1 < len(segs) and segs[i + 1]["start"] else None
                    s0 = parse_ts(sg["start"]).timestamp()
                    if s0 - 5 <= snap and (nxt is None or snap < nxt - 5):
                        soft_hits = 1
                hit_turn = bool(mt and turns >= mt) or sg["turn_limit"]
                comp = max(sg["compact_summary"], sg["compact_boundary"])
                wall = round((parse_ts(sg["end"]) - parse_ts(sg["start"])).total_seconds(), 1)
                pm = prompts.get(v["pid"]) or {}
                is_root = int(bool(v["root"]) and v["root"] == aid)
                row = dict(
                    session=sid, prompt_id=v["pid"], kind=v["kind"], root_agent_id=v["root"], is_root=is_root,
                    agent_id=aid, seg=i, nsegs=len(segs), parent_agent_id=v["parent"], depth=v["depth"] if v["depth"] is not None else "",
                    agent_type=v["type"], model=";".join(models), description=v["desc"],
                    start=iso(sg["start"]), end=iso(sg["end"]), wall_s=wall, open=int(open_),
                    turns=turns, tool_calls=tool_n, tools=tools_s,
                    tokens_input=tot["input_tokens"], tokens_output=tot["output_tokens"],
                    tokens_cache_creation=tot["cache_creation_input_tokens"],
                    tokens_cache_read=tot["cache_read_input_tokens"], tokens_total=total,
                    max_turns=mt if mt is not None else "", hit_max_turns=int(hit_turn), compactions=comp,
                    tool_errors=sg["errors"], tool_denied=sg["denied"], sandbox_blocks=sg["sandbox"],
                    skill_calls=";".join(skills), skill_md_reads=";".join(reads),
                    skill_md_reads_hidden=";".join(r_ for r_ in reads if r_ in hidden),
                    expected_skills_used=";".join(used), expected_skills_missed=";".join(missed),
                    spawn_count=len(sg["agent_calls"]), child_types=";".join(child_types),
                    reviewer_children=sum(1 for c_ in child_types if c_ in REVIEWERS), ledger_matched=ledger_hits,
                    final_status=status, soft_limit_hits=soft_hits,
                    family=pm.get("family", ""), target_agent=pm.get("target_agent", ""), cost_class=pm.get("cost_class", ""),
                    check_result=(grades.get(v["pid"]) or {}).get("check_result", "") if v["pid"] else "")
                rows.append(row)
                if is_root and v["kind"] == "prompt" and final_text and not open_:
                    finals.append((v["pid"], aid, i, len(segs), final_text))

    rows.sort(key=lambda r: (r["start"], r["agent_id"], r["seg"]))
    os.makedirs(a.out, exist_ok=True)
    cols = list(rows[0].keys()) if rows else []
    tmp = os.path.join(a.out, "runs.csv.tmp")
    with open(tmp, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, cols, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
    os.replace(tmp, os.path.join(a.out, "runs.csv"))
    for pid, aid, i, n, text in finals:
        d = os.path.join(a.out, "run", pid)
        os.makedirs(d, exist_ok=True)
        names = [f"final_{aid}_s{i}.txt"] + ([f"final_{aid}.txt"] if i == n - 1 else [])
        if n == 1:
            names = [f"final_{aid}.txt"]
        for nm in names:
            with open(os.path.join(d, nm), "w", encoding="utf-8") as fh:
                fh.write(text + "\n")

    kinds = Counter(r["kind"] for r in rows)
    print(f"sessions: {', '.join(sessions)}")
    print(f"rows: {len(rows)}  (kinds: {dict(kinds)}; prompt ids: {len({r['prompt_id'] for r in rows if r['prompt_id']})}; "
          f"open segments: {sum(r['open'] for r in rows)}; final files: {len(finals)})")
    print(f"campaign window start: {iso(camp.isoformat()) if camp else 'none'}; hidden skills: {len(hidden)} "
          f"(repo {len(repo_skills)}, installed {len(inst_skills)}, overridden {len(overridden)})")
    print("columns (%d): %s" % (len(cols), ", ".join(cols)))
    print("wrote", os.path.join(a.out, "runs.csv"))


if __name__ == "__main__":
    sys.exit(main())
