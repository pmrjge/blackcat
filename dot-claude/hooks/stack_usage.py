#!/usr/bin/env python3
"""stack_usage.py - per-session usage collector of the claude-agent-stack (stdlib only, Python 3.9+).

A background job per Claude Code session reads the session's subagent transcripts incrementally and
appends one row per agent segment (a spawn or a resume), one row per human-prompt window of the main
thread and one session row to a CSV that the scheduler's cost model and the learned limits are
refitted from (stack_sched_refresh.py, stack_limits.py). Numbers and ids only (plus `task`, the plain
words of the Agent description: a word with a digit, '/', ':', '.' or '_' is dropped, and `model`, the
model id the API reported for the segment's calls): no prompt,
transcript text, tool input, path, command, URL or secret is ever written. Every field is measured
(transcripts, agent meta files, the guard's JSONL files); a field that cannot be measured is left
empty, never estimated or defaulted.

Hook entry points (settings.json; both read the hook's JSON on stdin and exit 0 at once):
  stack_usage.py start      SessionStart and SubagentStart: start the session's collector, detached
                            (new session, stdio on /dev/null), unless one runs already
  stack_usage.py end        SessionEnd: write the session's end marker; the collector sees it, scans
                            one last time, writes the limit proposals (stack_limits.propose, when
                            importable) and refreshes the candidate model, then exits. Nothing there
                            changes any limit (S6 U4)
CLI:
  stack_usage.py runs [--session ID] [--json]   agent-run view (segments aggregated per agent)
  stack_usage.py status                         one line (doctor.sh)
  stack_usage.py refresh [--online] [--force]   refit the active model now (stack_sched_refresh.py)
  stack_usage.py propose [--model F]            soft-limit / maxTurns drift; prints only
  stack_usage.py scan --session ID --subagents DIR [--final]   one scan, no daemon (tests, catch-up)
  stack_usage.py run --session ID --subagents DIR [--owner-pid N]   the collector itself

Lifecycle: one collector per session, guaranteed by an flock on sessions/<id>/collector.lock held
for the collector's life (a second `start` sees the lock and does nothing; two racing starts spawn
two processes and the loser exits at once). It exits on the end marker, when the Claude Code
process that ran the hook is gone (owner pid; its start time guards against pid reuse), after
STACK_USAGE_IDLE_S without transcript growth, or never starts with STACK_USAGE_COLLECT=0. The next
SessionStart or SubagentStart of the session starts it again; offsets are persisted, so nothing is
read twice and nothing is lost. Every exit path fails silently: a hook never fails because of it.

Files under ${XDG_STATE_HOME:-~/.local/state}/claude-agent-stack/:
  usage/runs3.csv             segment rows (COLUMNS_V3, schema 3), append-only under usage/runs3.lock
                              (fcntl), header line, last row per (session, id, seg) wins
  usage/runs3.1.csv           the archive: rows rotated out of runs3.csv (STACK_USAGE_MAX_BYTES); a
                              runs3.csv of another header is set aside as runs3.old-schema-<epoch>.csv,
                              one rotation cannot read (a line the csv module refuses, a NUL, bad UTF-8)
                              as runs3[.1].unreadable-<epoch>.csv, byte for byte
  usage/runs2.csv, runs2.1.csv  the v2 history (COLUMNS_V2, no `model`: read as unknown), and
  usage/runs.csv, runs.1.csv  the v1 history (COLUMNS_V1): read as src=seed_v1; both NEVER written,
                              renamed or rotated here (an older install's collector, still running
                              after an upgrade, keeps appending to its own file; a new header in the
                              same file would have each version set the other's file aside)
  usage/sessions/<id>/        collector.lock, collector.json (pid, owner, heartbeat, exit reason),
                              state.json (byte offsets and parser state per transcript), end (marker)
  usage/refresh.json          the last refresh: time, trigger, result
  sched_model.json            the ACTIVE scheduler model (written by stack_sched_refresh.py)

Segments are cut exactly as tests/derive_thresholds.py does (read_records + segments_of): an API
call is one assistant message deduplicated by (message.id, requestId) with the per-field max; a
segment starts at the first prompt or at a resume message after the agent ended its turn; a
compaction stays inside the segment. Status: `partial` while the segment's last event is a tool
call or tool result and the transcript changed within LIVE_S (600 s), else `complete`. A later row
for the same key replaces an earlier one (a complete segment can grow again when a background
child's notification wakes the agent).

`model` (schema 3): the `message.model` of the segment's API calls, one id when they all agree,
`mixed` when they do not, empty when none was reported (a `<synthetic>` line is no model). The
readers that learn from the rows (stack_limits.read_rows, stack_sched_refresh, stack-budget) skip an
agent row whose model is set and is not its type's frontmatter model (stack_limits.model_mismatch: a
/override-agent run is that session's only); rows are never rewritten, the filter is at read time.
"""
import csv
import errno
import fcntl
import glob
import hashlib
import io
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import time
from bisect import bisect_left, bisect_right
from datetime import datetime, timezone

SCHEMA_VERSION = 3
V1_SCHEMA = 1
COLUMNS_V1 = ["schema_version", "session", "id", "type", "seg", "status", "api_calls", "ctx", "input", "output",
              "cache_creation", "cache_read", "first_cc", "first_cr", "peak", "prev_peak", "gap_s", "first_ts",
              "last_ts", "wall_s", "compacted", "turn_limited", "after_limit"]
TOOL_COLS = ["n_read", "n_write", "n_edit", "n_notebook", "n_bash", "n_grep", "n_glob", "n_agent", "n_send",
             "n_skill", "n_toolsearch", "n_webfetch", "n_websearch", "n_lsp", "n_mcp", "n_other"]
HIT_COLS = ["hit_soft", "hit_turn", "hit_hard_agent", "hit_hard_prompt", "hit_hard_session", "hit_mcp"]
COLUMNS_V2 = (COLUMNS_V1
              + TOOL_COLS + ["tool_calls"]                                                       # A
              + ["files_written", "files_written_repo", "git_commits", "ro_write", "first_ctx",
                 "first_write_call", "ctx_at_first_write"]                                       # B
              + ["resume", "cold", "parent", "depth", "node", "window"]                          # C
              + ["status_code"] + HIT_COLS + ["sess_src", "snap", "regime", "is_main", "window_ctx"]   # S6
              + ["task", "stack_commit", "src"])                                                 # U
COLUMNS_V3 = COLUMNS_V2 + ["model"]
COLUMNS = COLUMNS_V3
EMPTY_ROW = {c: "" for c in COLUMNS}         # an unmeasured field is an empty cell, never 0
STRING_COLUMNS = ("session", "id", "type", "status", "parent", "node", "sess_src", "snap", "regime", "task",
                  "stack_commit", "src", "model")      # every other column is a number (or empty)
REQUIRED_STRINGS = STRING_COLUMNS[:4]         # a row with an invalid one is neither written nor read
OPTIONAL_STRINGS = STRING_COLUMNS[4:]         # validated; an invalid or unmeasurable value is an empty cell
KEY = ("session", "id", "seg")
TOOL_MAP = {"Read": "n_read", "Write": "n_write", "Edit": "n_edit", "MultiEdit": "n_edit",
            "NotebookEdit": "n_notebook", "Bash": "n_bash", "Grep": "n_grep", "Glob": "n_glob", "Agent": "n_agent",
            "Task": "n_agent", "SendMessage": "n_send", "Skill": "n_skill", "ToolSearch": "n_toolsearch",
            "WebFetch": "n_webfetch", "WebSearch": "n_websearch", "LSP": "n_lsp"}
WRITE_TOOLS = ("Write", "Edit", "MultiEdit", "NotebookEdit")
READONLY_TYPES = {"code-reviewer", "security-auditor", "verifier", "plan-reviewer", "claude-code-guide",
                  "proof-checker"}            # agent_guard.py's read-only set
HIT_KIND = {"soft_agent": "hit_soft", "soft_prompt": "hit_soft", "soft_session": "hit_soft", "turn": "hit_turn",
            "hard_agent": "hit_hard_agent", "hard_prompt": "hit_hard_prompt", "hard_session": "hit_hard_session",
            "mcp": "hit_mcp"}
# the prompt and session limits: a firing is the main window's (and the session's) whoever's call tripped it
SCOPE_KINDS = ("soft_prompt", "hard_prompt", "soft_session", "hard_session")
SESSION_KINDS = ("soft_session", "hard_session")
HIT_SLACK_S = 5.0         # the guard's PreToolUse fires just after the transcript line of the call it refuses
GUARD_FILE_MAX = 8 << 20  # limit-hits.jsonl / prompt-windows.jsonl: the last bytes read per scan

# transcript parsing: the same constants as tests/derive_thresholds.py
F = ("input_tokens", "output_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")
RESUME_RE = re.compile(r"^(Another Claude session|The coordinator) sent a message while you were working")
COMPACT_RE = re.compile(r"^This session is being continued from a previous conversation")
TURN_LIMIT_RE = re.compile(r"turn limit", re.I)
TEXT_HEAD = 300           # derive_thresholds matches only the first 300 characters of a user message
LIVE_S = 600

# validation patterns end in \Z, not $ ($ also matches before a trailing newline): no cell the writer
# lets through needs csv quoting, which _csv_rows' line-at-a-time parsing relies on
ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}\Z")
TYPE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,79}\Z")
UNKNOWN_TYPE = "(unknown)"
NODE_RE = re.compile(r"^[A-Z]{1,3}[0-9]{1,3}[a-z]?\Z")
HEX16_RE = re.compile(r"^[0-9a-f]{16}\Z")
COMMIT_HEX_RE = re.compile(r"^[0-9a-f]{7,40}\Z")
TASK_RE = re.compile(r"^[A-Za-z][A-Za-z -]{0,59}\Z")
TASK_WORD_RE = re.compile(r"[A-Za-z][A-Za-z-]{0,23}\Z")
# a model id as the API reports it (claude-opus-5-5, us.anthropic.claude-...-v1:0, ...@date, ...[1m]);
# `<synthetic>` (Claude Code's own error lines) fails it and is no model
MODEL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:@/\[\]-]{0,127}\Z")
MODEL_MIXED = "mixed"     # a segment whose calls reported two different models
SESS_SRC = ("startup", "resume", "clear", "compact", "fork")
SRC_VALUES = ("measured", "seed_v1")
STATUS_VALUES = ("partial", "complete")
COMMIT_RE = re.compile(r"(?:^|[;&|(]\s*|\n\s*)git(?:\s+-C\s+\S+)?\s+commit\b")   # a commit command, not a mention
STATUS_RE = re.compile(r"^STATUS:\s*(done|partial|blocked)", re.M)
STATUS_CODE = {"done": 0, "partial": 1, "blocked": 2}
HUMAN_SKIP = ("<task-notification>", "Base directory for this skill")
NOTE_PATHS = ("/.claude-work/", "/tmp/", "/private/tmp/", "/private/var/", "/var/folders/")
SHELLS = {"sh", "bash", "zsh", "dash", "ksh", "fish", "env"}
WINDOW = 16               # recent API-call keys kept to merge a message's streamed lines
READ_CHUNK = 8 << 20      # bytes read per transcript per scan (a large backlog takes a few scans)
HERE = os.path.dirname(os.path.abspath(__file__))


def knob(name, default):
    try:
        return float(os.environ.get(name, "").strip())
    except ValueError:
        return default


def enabled():
    return os.environ.get("STACK_USAGE_COLLECT", "1").strip() != "0"


def state_root():
    base = os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state")
    return os.path.join(base, "claude-agent-stack")


def usage_dir():
    return os.path.join(state_root(), "usage")


def active_model_path():
    return os.path.join(state_root(), "sched_model.json")


def session_dir(sid, create=True):
    d = os.path.join(usage_dir(), "sessions", sid)
    if create:
        os.makedirs(d, mode=0o700, exist_ok=True)
    return d


def write_json_atomic(path, obj):
    tmp = "%s.%d.tmp" % (path, os.getpid())
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, separators=(",", ":"))
    os.replace(tmp, path)


def read_json(path):
    try:
        with open(path, encoding="utf-8") as fh:
            v = json.load(fh)
        return v if isinstance(v, dict) else None
    except (OSError, ValueError):
        return None


def epoch(ts):
    """Seconds since the epoch of an ISO timestamp; None when unparseable."""
    if not isinstance(ts, str) or not ts:
        return None
    s = ts.strip().replace("Z", "+00:00")
    m = re.match(r"^(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d)(\.\d+)?([+-]\d\d:\d\d)?$", s)
    if not m:
        return None
    try:
        base = datetime.fromisoformat(m.group(1) + (m.group(3) or "+00:00"))
    except ValueError:
        return None
    frac = float(m.group(2)) if m.group(2) else 0.0
    return base.timestamp() + frac


def iso(t):
    return datetime.fromtimestamp(float(t), timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def subagents_dir(ev):
    """The session's subagents folder from a hook event (transcript_path is the main session's
    transcript; a subagent's own path is mapped back, as agent_guard.transcript_files does)."""
    tp = ev.get("transcript_path")
    if not isinstance(tp, str) or not tp.strip():
        return None
    tp = os.path.expanduser(tp.strip())
    folder = os.path.dirname(tp)
    if os.path.basename(folder) == "subagents":
        return folder
    stem = os.path.basename(tp)
    stem = stem[:-len(".jsonl")] if stem.endswith(".jsonl") else str(ev.get("session_id") or stem)
    return os.path.join(folder, stem, "subagents")


# ---------------------------------------------------------------- incremental transcript parser
def text_of(c):
    if isinstance(c, str):
        return c
    if isinstance(c, list):
        return " ".join(b.get("text", "") for b in c if isinstance(b, dict) and b.get("type") == "text"
                        and isinstance(b.get("text", ""), str))
    return ""


def is_tool_result(c):
    return isinstance(c, list) and any(isinstance(b, dict) and b.get("type") == "tool_result" for b in c)


def new_agent(main=False):
    """Parser state of one transcript. main=True: the main thread, whose 'segments' are the human-prompt
    windows (seg = window index) and which keeps the human prompts' times (and promptIds) in `humans`."""
    return {"off": 0, "ino": None, "type": None, "nseg": 0, "cur": None, "last_kind": None, "last_evt": None,
            "win": {}, "prev": None, "prev_tl": False, "emitted": {}, "meta": None, "main": bool(main),
            "humans": []}


def _new_seg(a, idx=None):
    a["cur"] = {"idx": a["nseg"] if idx is None else idx, "n": 0, "in": 0, "out": 0, "cc": 0, "cr": 0, "peak": 0,
                "fts": None, "lts": None, "fcc": 0, "fcr": 0, "fkey": None, "lkey": None, "comp": 0, "tl": False,
                "after": bool(a["prev_tl"]), "gap": None, "prev_peak": None,
                # tool counts, the segment's written files (sha256 prefixes, dropped with the segment), commits
                "tc": {}, "fw": {}, "gc": 0, "fctx": 0, "fwc": None, "cfw": None, "lsc": None, "ltxt": False,
                # the distinct model ids its calls reported (two are enough to say `mixed`)
                "models": []}
    a["nseg"] += 1
    if a["prev"]:
        a["cur"]["prev_peak"] = a["prev"]["peak"]


def _finish_seg(a, out):
    """The current segment ends because a new one starts: its final row (complete)."""
    cur = a["cur"]
    if cur is None:
        return
    if cur["n"]:
        out.append(seg_row_values(cur, "complete", bool(cur["tl"]), a["last_kind"], a["main"]))
        if not a["main"]:
            a["prev"] = {"peak": cur["peak"], "lts": cur["lts"]}
    a["prev_tl"] = bool(cur["tl"])


def repo_path(p):
    """A written path that is work, not notes: none of the scratch/notes locations (and not $TMPDIR)."""
    tmp = os.environ.get("TMPDIR", "").rstrip("/")
    return not (any(n in p for n in NOTE_PATHS) or (len(tmp) > 1 and p.startswith(tmp + "/")))


def _on_blocks(cur, w, content):
    """Tool-use blocks (each once per call, by block id) and the call's STATUS line, into the segment's
    counts. Paths and commands are matched and dropped; only hashes of written paths stay in memory."""
    for i, b in enumerate(content):
        if not isinstance(b, dict):
            continue
        if b.get("type") == "text":
            txt = b.get("text")
            if isinstance(txt, str) and txt.strip():
                w["txt"] = True
                mt = STATUS_RE.search(txt)
                if mt:
                    w["sc"] = STATUS_CODE[mt.group(1)]
            continue
        if b.get("type") != "tool_use":
            continue
        bid = b.get("id") if isinstance(b.get("id"), str) and b.get("id") else "@%d" % i
        if bid in w["tu"]:
            continue
        w["tu"].append(bid)
        name = str(b.get("name"))
        col = TOOL_MAP.get(name) or ("n_mcp" if name.startswith("mcp__") else "n_other")
        cur["tc"][col] = cur["tc"].get(col, 0) + 1
        inp = b.get("input") if isinstance(b.get("input"), dict) else {}
        if name in WRITE_TOOLS:
            p = inp.get("file_path") if isinstance(inp.get("file_path"), str) and inp.get("file_path") \
                else inp.get("notebook_path")
            if isinstance(p, str) and p:
                hsh = hashlib.sha256(p.encode("utf-8", "replace")).hexdigest()[:16]
                repo = int(repo_path(p))
                cur["fw"][hsh] = max(cur["fw"].get(hsh, 0), repo)
                if repo:
                    w["wr"] = True
                    if cur["fwc"] is None:
                        cur["fwc"] = w["i"]
        elif name == "Bash" and COMMIT_RE.search(str(inp.get("command", ""))):
            cur["gc"] += 1


def _on_call_line(a, r, m, u, out):
    key = "%s|%s" % (m.get("id"), r.get("requestId"))
    if key == "None|None":
        key = "uuid|" + str(r.get("uuid"))
    vals = []
    for f in F:
        try:
            vals.append(max(0, int(u.get(f) or 0)))
        except (TypeError, ValueError):
            vals.append(0)
    tools = any(isinstance(b, dict) and b.get("type") == "tool_use" for b in (m.get("content") or [])
                if isinstance(m.get("content"), list))
    ts = r.get("timestamp")
    w = a["win"].get(key)
    if w is None:
        # a new API call: one event, appended to the current segment
        if a["main"]:
            # the main thread: the segment is the human-prompt window of the call's time
            t = epoch(ts)
            i = None if t is None else bisect_right(a["humans"], [t, "￿"]) - 1
            if i is None or i < 0:                  # before the first prompt: no window, later lines ignored
                a["win"][key] = {"v": [0, 0, 0, 0], "tools": False, "seg": -1, "tu": [], "sc": None, "txt": False,
                                 "wr": False, "i": 0}
                while len(a["win"]) > WINDOW:
                    a["win"].pop(next(iter(a["win"])))
                return
            if a["cur"] is not None:
                i = max(i, a["cur"]["idx"])
            if a["cur"] is None or a["cur"]["idx"] != i:
                _finish_seg(a, out)
                _new_seg(a, i)
        elif a["cur"] is None:
            _new_seg(a)
        cur = a["cur"]
        w = {"v": [0, 0, 0, 0], "tools": False, "seg": cur["idx"], "tu": [], "sc": None, "txt": False, "wr": False,
             "i": cur["n"] + 1}
        a["win"][key] = w
        while len(a["win"]) > WINDOW:
            a["win"].pop(next(iter(a["win"])))
        cur["n"] += 1
        if cur["fkey"] is None:
            cur["fkey"] = key
            cur["fts"] = epoch(ts)
        cur["lkey"] = key
        cur["lts"] = epoch(ts)
        new_call = True
    else:
        new_call = False
    cur = a["cur"]
    if cur is None or w["seg"] != cur["idx"]:
        return                       # a late line of a call in a finished segment: ignored
    md = m.get("model")
    if isinstance(md, str) and MODEL_RE.match(md):
        ms = cur.setdefault("models", [])
        if md not in ms and len(ms) < 2:
            ms.append(md)
    old = w["v"]
    nv = [max(o, v) for o, v in zip(old, vals)]
    for i, k in enumerate(("in", "out", "cc", "cr")):
        cur[k] += nv[i] - old[i]
    w["v"] = nv
    w["tools"] = w["tools"] or tools
    if isinstance(m.get("content"), list):
        _on_blocks(cur, w, m["content"])
    ctx = nv[0] + nv[2] + nv[3]
    cur["peak"] = max(cur["peak"], ctx)
    if cur["fkey"] == key:
        cur["fcc"], cur["fcr"], cur["fctx"] = nv[2], nv[3], ctx
    if cur["fwc"] == w["i"] and w["wr"]:
        cur["cfw"] = ctx                    # the first repo-writing call's context
    if cur["lkey"] == key:
        cur["lsc"], cur["ltxt"] = w["sc"], w["txt"]
        t = epoch(ts)
        if t is not None:
            cur["lts"] = t
    if new_call or a["last_evt"] == key:
        # derive_thresholds sets last_kind from the call's final tool set when it reaches the event
        a["last_kind"] = "tool" if w["tools"] else "end"
        a["last_evt"] = key


def feed_line(a, line, out):
    """One transcript line into the agent's parser state; finished segments' rows go to `out`."""
    try:
        r = json.loads(line)
    except ValueError:
        return
    if not isinstance(r, dict):
        return
    t = r.get("type")
    if t == "assistant":
        m = r.get("message") or {}
        if not isinstance(m, dict):
            return
        u = m.get("usage")
        if not isinstance(u, dict):
            return
        _on_call_line(a, r, m, u, out)
    elif t == "user":
        m = r.get("message") or {}
        c = m.get("content") if isinstance(m, dict) else None
        if not is_tool_result(c):
            txt = text_of(c)[:TEXT_HEAD]
            if a["cur"] is None or (RESUME_RE.match(txt) and a["last_kind"] in ("end", "tr")):
                if a["cur"] is not None and a["last_kind"] == "tr" and TURN_LIMIT_RE.search(txt):
                    a["cur"]["tl"] = True
                _finish_seg(a, out)
                _new_seg(a)
            elif COMPACT_RE.match(txt):
                a["cur"]["comp"] += 1
            a["last_evt"] = None
            return
        if a["cur"] is None:
            _new_seg(a)
        a["last_kind"] = "tr"
        a["last_evt"] = None


def feed_main_line(a, line, out):
    """One line of the main thread's transcript: calls go to their human-prompt window, human prompts
    (not tool results, not isMeta, not a task notification or skill preamble) open the next window."""
    try:
        r = json.loads(line)
    except ValueError:
        return
    if not isinstance(r, dict):
        return
    t = r.get("type")
    if t == "assistant":
        feed_line(a, line, out)
    elif t == "user":
        m = r.get("message") or {}
        c = m.get("content") if isinstance(m, dict) else None
        if is_tool_result(c) or r.get("isMeta"):
            return
        if text_of(c)[:TEXT_HEAD].startswith(HUMAN_SKIP):
            return
        tm = epoch(r.get("timestamp"))
        if tm is None:
            return
        pid = r.get("promptId")
        ent = [tm, pid if isinstance(pid, str) and ID_RE.match(pid) else ""]
        k = bisect_left(a["humans"], ent)
        if k < len(a["humans"]) and a["humans"][k] == ent:
            return                      # the same prompt record written twice (a resumed transcript replays it)
        a["humans"].insert(k, ent)


def _status_code(cur, status, tl, end):
    """0 done, 1 partial, 2 blocked; empty while the segment is open or when it ended on a tool call.
    The STATUS line of the segment's last call wins; a text-only last call without one is a clean finish
    (0); a segment cut by the turn limit is at least partial."""
    if status == "partial":
        return ""
    code = None
    if end == "end" and cur["ltxt"]:
        code = cur["lsc"] if cur["lsc"] is not None else 0
    if tl and code != 2:
        code = 1
    return "" if code is None else code


def seg_row_values(cur, status, tl, end=None, main=False):
    """The measured part of a segment row (session, id, type and the metadata columns are added by
    the caller). `end` is the kind of the segment's last event (end | tool | tr)."""
    def num(x):
        return "" if x is None else (round(x, 3) if isinstance(x, float) else x)
    d = {"seg": cur["idx"], "status": status, "api_calls": cur["n"],
         "ctx": cur["in"] + cur["cc"] + cur["cr"], "input": cur["in"], "output": cur["out"],
         "cache_creation": cur["cc"], "cache_read": cur["cr"], "first_cc": cur["fcc"], "first_cr": cur["fcr"],
         "peak": cur["peak"], "prev_peak": num(cur["prev_peak"]),
         "gap_s": num(cur["gap"]),
         "first_ts": num(cur["fts"]), "last_ts": num(cur["lts"]),
         "wall_s": num(cur["lts"] - cur["fts"]) if cur["lts"] is not None and cur["fts"] is not None else "",
         "compacted": cur["comp"], "turn_limited": int(bool(tl)), "after_limit": int(bool(cur["after"]))}
    if main:                      # a prompt window has no compaction/turn-limit/resume notion of its own
        d.update(compacted="", turn_limited="", after_limit="")
    for c in TOOL_COLS:
        d[c] = cur["tc"].get(c, 0)
    d["tool_calls"] = sum(d[c] for c in TOOL_COLS)
    d.update(files_written=len(cur["fw"]), files_written_repo=sum(cur["fw"].values()), git_commits=cur["gc"],
             first_ctx=cur["fctx"], first_write_call=num(cur["fwc"]), ctx_at_first_write=num(cur["cfw"]))
    ms = cur.get("models") or []
    d["model"] = ms[0] if len(ms) == 1 else (MODEL_MIXED if ms else "")
    if main:
        d.update(resume=0, cold="", status_code="", window=cur["idx"], is_main=1, depth=0)
    else:
        d["resume"] = int(cur["idx"] != 0)
        d["cold"] = int(cur["fcr"] < 0.5 * cur["prev_peak"]) if cur["idx"] and cur["prev_peak"] is not None else ""
        d["status_code"] = _status_code(cur, status, tl, end)
        d["is_main"] = 0
    return d


def _set_gap(a):
    cur = a["cur"]
    if cur and a["prev"] and cur["gap"] is None and cur["fts"] is not None and a["prev"].get("lts") is not None:
        cur["gap"] = round(cur["fts"] - a["prev"]["lts"], 3)


def current_row(a, live):
    """The row of the agent's last segment as it stands (None without API calls)."""
    cur = a["cur"]
    if cur is None or not cur["n"]:
        return None
    end = a["last_kind"]
    if a["main"]:                 # the last window is open while the transcript is growing
        return seg_row_values(cur, "partial" if live else "complete", False, end, True)
    status = "partial" if (end in ("tool", "tr") and live) else "complete"
    tl = cur["tl"] or (end == "tr" and not live)
    return seg_row_values(cur, status, tl, end)


# ---------------------------------------------------------------- scanning a session
def agent_meta(folder, aid):
    """The measured, validated fields of agent-<id>.meta.json (None when the file is unreadable):
    type, parent ("main" when the meta names none), depth, node, task. Only these survive; the
    description is reduced to a plan-node id and its plain words."""
    meta = read_json(os.path.join(folder, "agent-%s.meta.json" % aid))
    if meta is None:
        return None
    t = meta.get("agentType")
    par = meta.get("parentAgentId")
    dep = meta.get("spawnDepth")
    desc = meta.get("description")
    node = task = ""
    if isinstance(desc, str):
        words = desc.split(None, 1)
        if words and NODE_RE.match(words[0]):
            node = words[0]
        # plain words only: a token with a digit, '/', ':', '.', '_' or over 24 letters (paths, URLs,
        # flags, keys, hashes) is dropped; the plan node id lives in `node`
        task = " ".join(w for w in (x.strip(".,;:!?()") for x in desc.split())
                        if TASK_WORD_RE.match(w))[:60].strip()
    return {"type": t if isinstance(t, str) and TYPE_RE.match(t) else None,
            "parent": "main" if par is None else (par if isinstance(par, str) and ID_RE.match(par) else ""),
            "depth": dep if isinstance(dep, int) and not isinstance(dep, bool) and 0 <= dep <= 99 else "",
            "node": node, "task": task}


def agent_type(folder, aid):
    return (agent_meta(folder, aid) or {}).get("type")


def read_stack_commit():
    """The commit of the installed stack (~/.claude/.stack-manifest.json); empty when the manifest is
    absent, unparseable or holds no hex commit. Read-only."""
    d = read_json(os.path.join(os.path.expanduser("~"), ".claude", ".stack-manifest.json"))
    c = d.get("commit") if d else None
    return c if isinstance(c, str) and COMMIT_HEX_RE.match(c) else ""


def _num(x):
    """A finite number >= 0 (bool excluded) or None."""
    if isinstance(x, bool) or not isinstance(x, (int, float)) or x != x or x in (float("inf"), float("-inf")) or x < 0:
        return None
    return x


def _jsonl_tail(path):
    """Lines of a guard JSONL file (the last GUARD_FILE_MAX bytes), None when the file is absent."""
    try:
        with open(path, "rb") as fh:
            size = os.fstat(fh.fileno()).st_size
            fh.seek(max(0, size - GUARD_FILE_MAX))
            data = fh.read(GUARD_FILE_MAX)
    except OSError:
        return None
    lines = data.splitlines()
    if size > GUARD_FILE_MAX and lines:
        lines = lines[1:]                       # the first line is cut
    return lines


def load_hits(gdir):
    """[(column, agent_id | None, ts, kind)] of <gdir>/limit-hits.jsonl; None when the file does not
    exist (the hit_* cells are then unmeasurable: empty). Lines that fail the schema are skipped. The
    guard records the agent whose call tripped a limit, for prompt and session limits too."""
    lines = _jsonl_tail(os.path.join(gdir, "limit-hits.jsonl"))
    if lines is None:
        return None
    out = []
    for ln in lines:
        try:
            r = json.loads(ln)
        except ValueError:
            continue
        if not isinstance(r, dict) or r.get("v") != 1 or r.get("kind") not in HIT_KIND:
            continue
        t, aid = _num(r.get("ts")), r.get("agent_id")
        if t is None or not (aid is None or (isinstance(aid, str) and ID_RE.match(aid))):
            continue
        out.append((HIT_KIND[r["kind"]], aid, float(t), r["kind"]))
    return out


def load_windows(gdir):
    """[{ts, prompt_id, base}] of <gdir>/prompt-windows.jsonl in file order; None when absent."""
    lines = _jsonl_tail(os.path.join(gdir, "prompt-windows.jsonl"))
    if lines is None:
        return None
    out = []
    for ln in lines:
        try:
            r = json.loads(ln)
        except ValueError:
            continue
        if not isinstance(r, dict) or r.get("v") != 1:
            continue
        t, base, pid = _num(r.get("ts")), _num(r.get("base")), r.get("prompt_id")
        if t is None or base is None or isinstance(base, float) or not (
                pid is None or (isinstance(pid, str) and ID_RE.match(pid))):
            continue
        out.append({"ts": float(t), "prompt_id": pid or "", "base": int(base)})
    return out


def hit_cells(hits, aid, lo, hi):
    """The six hit_* cells of an agent segment: a 1 when a firing of the kind by this agent falls in
    [lo, hi + slack]. hit_soft is the agent's own soft limit only (soft_agent): a soft prompt or session
    firing during its call is the main window's and the session's hit. Empty cells when there is no
    limit-hits.jsonl (nothing measured) or no time span."""
    if hits is None or lo == "" or hi == "":
        return {c: "" for c in HIT_COLS}
    got = {c: 0 for c in HIT_COLS}
    for col, who, t, kind in hits:
        if who == aid and lo <= t <= hi + HIT_SLACK_S and (col != "hit_soft" or kind == "soft_agent"):
            got[col] = 1
    return got


def session_hit_cells(hits):
    """The session row's hit_* cells: hit_soft from soft_session, hit_hard_session from hard_session
    (limit-hits.jsonl is the session's own file), 0 otherwise; empty when the file does not exist."""
    if hits is None:
        return {c: "" for c in HIT_COLS}
    got = {c: 0 for c in HIT_COLS}
    for col, _who, _t, kind in hits:
        if kind in SESSION_KINDS:
            got[col] = 1
    return got


def window_ctx(i, humans, pw, total):
    """The whole-tree context of main window i: base(k+1) - base(k) of the guard's prompt-windows.jsonl,
    the open window's budget total - base(k). Window i is matched to a guard line by promptId, else
    by the nearest time (10 s). Empty when it cannot be matched or measured."""
    if not pw or i >= len(humans):
        return ""
    tm, pid = humans[i]
    k = next((j for j, w in enumerate(pw) if pid and w["prompt_id"] == pid), None)
    if k is None:
        j = min(range(len(pw)), key=lambda x: abs(pw[x]["ts"] - tm))
        k = j if abs(pw[j]["ts"] - tm) <= 10 else None
    if k is None:
        return ""
    if k + 1 < len(pw):
        v = pw[k + 1]["base"] - pw[k]["base"]
    elif total is not None:
        v = total - pw[k]["base"]
    else:
        return ""
    return int(v) if v >= 0 else ""


def snapshot_cells(sid):
    """sess_src, snap, regime from the session's limits snapshot (written by the guard at SessionStart);
    empty cells while no snapshot exists or a field is not valid."""
    d = read_json(os.path.join(state_root(), "limits", "snapshots", sid + ".json")) or {}
    h = d.get("hash")
    h = h[len("sha256:"):][:16] if isinstance(h, str) and h.startswith("sha256:") else ""
    src, reg = d.get("source_event"), d.get("regime")
    return {"sess_src": src if src in SESS_SRC else "", "snap": h if HEX16_RE.match(h) else "",
            "regime": reg if isinstance(reg, str) and HEX16_RE.match(reg) else ""}


def _feed_file(a, path, stt, feed, out):
    """New complete lines of one transcript into the parser. Returns (grew, pending)."""
    grew, data = False, b""
    if stt.st_size > a["off"]:
        try:
            with open(path, "rb") as fh:
                fh.seek(a["off"])
                data = fh.read(min(READ_CHUNK, stt.st_size - a["off"]))
        except OSError:
            data = b""
        start = 0
        if a.get("skip"):
            # the rest of a line longer than READ_CHUNK (no API usage lives in such a line)
            nl = data.find(b"\n")
            start = len(data) if nl < 0 else nl + 1
            a["skip"] = nl < 0
        cut = data.rfind(b"\n")
        if cut >= start:
            grew = True
            for line in data[start:cut + 1].splitlines():
                if line.strip():
                    feed(a, line.decode("utf-8", "replace"), out)
                    if not a["main"]:
                        _set_gap(a)
            a["off"] += cut + 1
        elif len(data) == READ_CHUNK:
            a["off"] += len(data)
            a["skip"] = True
        else:
            a["off"] += start
    return grew, len(data) == READ_CHUNK


def _fresh(a, stt, main):
    if a is None or a.get("ino") != stt.st_ino or stt.st_size < a.get("off", 0):
        emitted = a["emitted"] if a else {}
        a = new_agent(main)
        a["ino"] = stt.st_ino
        a["emitted"] = emitted
    return a


def scan(st, sid, folder, final=False, now=None, commit=None):
    """Read what the session's main and subagent transcripts gained since the last scan. Returns the
    rows to append (only rows that differ from the last one written for their key) and whether any
    transcript grew. `commit` is the installed stack's commit (read now when None)."""
    now = time.time() if now is None else now
    commit = read_stack_commit() if commit is None else commit
    agents = st.setdefault("agents", {})
    rows, grew = [], False
    st["more"] = False
    gdir = os.path.join(state_root(), sid)               # the guard's session state folder (read only)
    hits, pw = load_hits(gdir), load_windows(gdir)
    base = dict(schema_version=SCHEMA_VERSION, session=sid, src="measured", stack_commit=commit,
                **snapshot_cells(sid))
    budget = _num((read_json(os.path.join(gdir, "budget.json")) or {}).get("total"))

    def emit(a, aid, atype, vals, extra):
        row = dict(EMPTY_ROW, **base, id=aid, type=atype, **vals, **extra)
        sig = json.dumps([row[c] for c in COLUMNS])
        k = str(vals["seg"])
        if a["emitted"].get(k) != sig:
            a["emitted"][k] = sig
            rows.append(row)

    def span(vals):
        f, t = vals["first_ts"], vals["last_ts"]
        if f != "":
            st["tmin"] = f if st.get("tmin") is None else min(st["tmin"], f)
        if t != "":
            st["tmax"] = t if st.get("tmax") is None else max(st["tmax"], t)

    def settle(a, path, stt, feed, out):
        """Feed the file; returns (grew, live). Live: a backlog remains or the file changed lately."""
        g, pending = _feed_file(a, path, stt, feed, out)
        if pending:
            st["more"] = True            # a backlog: read on (the segment is not finished yet)
        return g, pending or (not final and (now - stt.st_mtime) < LIVE_S)

    def trim(a):
        # emitted signatures are kept for the last two segments only (older ones never change)
        if a["cur"] is not None:
            for k in [k for k in a["emitted"] if int(k) < a["cur"]["idx"] - 1]:
                a["emitted"].pop(k, None)

    # ---- the main thread: one row per human-prompt window (scanned first: the subagents' `window` needs it)
    mpath = os.path.join(os.path.dirname(os.path.dirname(folder)), sid + ".jsonl")
    ma = st.get("main")
    try:
        stt = os.stat(mpath)
    except OSError:
        stt = None
    if stt is not None:
        ma = st["main"] = _fresh(ma, stt, True)
        out = []
        g, live = settle(ma, mpath, stt, feed_main_line, out)
        grew = grew or g
        cr = current_row(ma, live)
        if cr is not None:
            out.append(cr)
        humans = ma["humans"]
        hs = [h[0] for h in humans]
        for vals in out:
            i = vals["seg"]
            cells = {c: "" for c in HIT_COLS}
            if hits is not None and i < len(hs):
                lo, hi = hs[i], (hs[i + 1] if i + 1 < len(hs) else float("inf"))
                cells = {c: 0 for c in HIT_COLS}
                for col, who, t, kind in hits:
                    # the main thread's own firings and every prompt/session firing (whoever's call
                    # tripped it); soft_session is the session row's: it shares hit_soft with
                    # soft_prompt, and soft.prompt reads a window's hit_soft
                    if (who is None or kind in SCOPE_KINDS) and kind != "soft_session" and lo <= t < hi:
                        cells[col] = 1
            span(vals)
            emit(ma, "main", "blackcat", vals,
                 dict(cells, ro_write=0, window_ctx=window_ctx(i, humans, pw, budget)))
        trim(ma)
    humans = ma["humans"] if ma else []

    # ---- the subagents: one row per segment
    for path in sorted(glob.glob(os.path.join(folder, "agent-*.jsonl"))):
        aid = os.path.basename(path)[len("agent-"):-len(".jsonl")]
        if not ID_RE.match(aid):
            continue
        try:
            stt = os.stat(path)
        except OSError:
            continue
        a = agents[aid] = _fresh(agents.get(aid), stt, False)
        if a["type"] is None or a["meta"] is None:
            a["meta"] = agent_meta(folder, aid)
            a["type"] = (a["meta"] or {}).get("type")
        out = []
        g, live = settle(a, path, stt, feed_line, out)
        grew = grew or g
        cr = current_row(a, live)
        if cr is not None:
            out.append(cr)
        atype = a["type"] or UNKNOWN_TYPE
        mt = a["meta"] or {}
        for vals in out:
            fts, lts = vals["first_ts"], vals["last_ts"]
            span(vals)
            ro = "" if atype == UNKNOWN_TYPE else int(
                (atype[:-5] if atype.endswith("-copy") else atype) in READONLY_TYPES
                and vals["files_written_repo"] + vals["git_commits"] > 0)
            win = max(0, bisect_right(humans, [fts, "￿"]) - 1) if humans and fts != "" else ""
            extra = dict(hit_cells(hits, aid, fts, lts), ro_write=ro, parent=mt.get("parent", ""),
                         depth=mt.get("depth", ""), node=mt.get("node", ""), task=mt.get("task", ""), window=win)
            emit(a, aid, atype, vals, extra)
        trim(a)

    # ---- the session row, at the final scan: the budget's whole-session context
    if final and budget is not None and st.get("tmin") is not None:
        vals = {"seg": 0, "status": "complete", "ctx": int(budget), "first_ts": st["tmin"], "last_ts": st["tmax"],
                "wall_s": round(st["tmax"] - st["tmin"], 3), "is_main": 1, "depth": 0}
        vals.update(session_hit_cells(hits))
        row = dict(EMPTY_ROW, **base, id="session", type="blackcat", **vals)
        sig = json.dumps([row[c] for c in COLUMNS])
        if st.get("emitted_session") != sig:
            st["emitted_session"] = sig
            rows.append(row)
    return rows, grew


# ---------------------------------------------------------------- runs.csv
class Locked:
    """flock on a lock file (blocking unless nb=True; `ok` says whether it was taken). wait=S: non-blocking
    tries for up to S seconds (a flock anyone holds, even from a read-only fd, cannot stall the caller)."""

    def __init__(self, path, nb=False, wait=None):
        self.path, self.nb, self.wait, self.fh, self.ok = path, nb, wait, None, False

    def __enter__(self):
        os.makedirs(os.path.dirname(self.path), mode=0o700, exist_ok=True)
        self.fh = open(self.path, "a")
        end = None if self.wait is None else time.monotonic() + self.wait
        while True:
            try:
                fcntl.flock(self.fh, fcntl.LOCK_EX | (fcntl.LOCK_NB if self.nb or end is not None else 0))
                self.ok = True
            except OSError as exc:
                if exc.errno not in (errno.EAGAIN, errno.EACCES, errno.EWOULDBLOCK):
                    raise
                if end is not None and time.monotonic() < end:
                    time.sleep(0.05)
                    continue
            return self

    def __exit__(self, *exc):
        if self.fh:
            self.fh.close()


def v1_paths():
    u = usage_dir()
    return os.path.join(u, "runs.1.csv"), os.path.join(u, "runs.csv")


def v2_paths():
    u = usage_dir()
    return os.path.join(u, "runs2.1.csv"), os.path.join(u, "runs2.csv")


def v3_paths():
    u = usage_dir()
    return os.path.join(u, "runs3.1.csv"), os.path.join(u, "runs3.csv")


def csv_paths():
    """Every row file a reader merges, oldest first: the v1 and v2 histories (never written here), then
    v3 (the rows this collector writes)."""
    return v1_paths() + v2_paths() + v3_paths()


def file_schemas(path):
    """The schema versions a row file holds, by its name: runs3*.csv 3, runs2*.csv 2, any other 1."""
    b = os.path.basename(path)
    return ("3",) if b.startswith("runs3") else ("2",) if b.startswith("runs2") else ("1",)


def _header_ok(path):
    """Whether the file's first line is COLUMNS' header (bytes: a bad byte further down is no error)."""
    try:
        with open(path, "rb") as fh:
            return fh.readline(1 << 16).rstrip(b"\r\n") == ",".join(COLUMNS).encode("ascii")
    except OSError:
        return False


ARCHIVE_FACTOR = 4        # runs3.1.csv keeps at most this many times STACK_USAGE_MAX_BYTES
APPEND_LOCK_WAIT_S = 5.0  # append_rows: runs3.lock busy this long -> TimeoutError, retried next tick
APPEND_LOCK = "runs3.lock"


def _set_aside(path, tag="old-schema"):
    """runs3.csv of another header becomes runs3.old-schema-<epoch>.csv, a file rotation cannot read
    runs3[.1].unreadable-<epoch>.csv: renamed, byte for byte, never over an earlier one."""
    base = "%s.%s-%d" % (os.path.splitext(path)[0], tag, int(time.time()))
    dest, n = base + ".csv", 0
    while os.path.exists(dest):
        n += 1
        dest = "%s-%d.csv" % (base, n)
    os.replace(path, dest)


def _read_strict(path):
    """read_rows of one file for rotation; None (the file set aside, see _rotate_if_needed) when the
    strict reader refuses it."""
    try:
        return read_rows([path], schemas=(str(SCHEMA_VERSION),), strict=True)
    except Unreadable:
        _set_aside(path, "unreadable")
        return None


def _rotate_if_needed(cur, old):
    """Rotation: once runs3.csv passes STACK_USAGE_MAX_BYTES (default 8 MB) it is merged into
    runs3.1.csv (the last row per key, newest sessions first, at most ARCHIVE_FACTOR x the cap: the
    oldest sessions beyond that are dropped; the newest one always stays) and starts again empty. A file
    of another header is set aside (_set_aside). Rotation reads strictly (U1, append-only): a file with a
    line the csv module refuses, a NUL or bad UTF-8 (or, for the archive, another header or no read
    access) is set aside intact as runs3[.1].unreadable-<epoch>.csv, never rewritten from the rows
    ahead of that line; an unreadable runs3.csv then starts again empty, an unreadable archive is
    rebuilt from runs3.csv alone. Only runs3*.csv is ever touched. Called under runs3.lock."""
    cap = knob("STACK_USAGE_MAX_BYTES", 8e6)
    try:
        size = os.path.getsize(cur)
    except OSError:
        return
    if size and not _header_ok(cur):
        _set_aside(cur)
        return
    if cap <= 0 or size <= cap:
        return
    if os.path.lexists(old) and not _header_ok(old):
        _set_aside(old, "unreadable")    # its rows would read as none: never replace it by runs3.csv's
    rows = _read_strict(old) or {}
    new = _read_strict(cur)
    if new is None:
        return
    rows.update(new)                       # the last row of a key wins, as read_rows([old, cur])
    by_session = {}
    for k, r in rows.items():
        by_session.setdefault(k[0], []).append(r)

    def newest(sess):
        best = 0.0
        for r in by_session[sess]:
            try:
                best = max(best, float(r.get("last_ts") or 0))
            except ValueError:
                pass
        return best
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=COLUMNS, extrasaction="ignore", lineterminator="\n")
    w.writeheader()
    first = buf.tell()
    for sess in sorted(by_session, key=newest, reverse=True):
        mark = buf.tell()
        for r in by_session[sess]:
            w.writerow(r)
        if buf.tell() > cap * ARCHIVE_FACTOR and mark > first:     # the newest session always stays
            buf.seek(mark)
            buf.truncate()
            break
    tmp = old + ".%d.tmp" % os.getpid()
    with open(tmp, "w", encoding="utf-8", newline="") as fh:
        fh.write(buf.getvalue())
    os.chmod(tmp, 0o600)
    os.replace(tmp, old)
    os.unlink(cur)


def valid_cell(col, v):
    """Whether a string column's value is acceptable (the hostile-CSV filter of the readers and writer)."""
    if col == "session" or col == "id" or col == "parent":
        return bool(ID_RE.match(v))
    if col == "type":
        return bool(TYPE_RE.match(v)) or v == UNKNOWN_TYPE
    if col == "status":
        return v in STATUS_VALUES
    if col == "node":
        return bool(NODE_RE.match(v))
    if col == "sess_src":
        return v in SESS_SRC
    if col in ("snap", "regime"):
        return bool(HEX16_RE.match(v))
    if col == "stack_commit":
        return bool(COMMIT_HEX_RE.match(v))
    if col == "src":
        return v in SRC_VALUES
    if col == "task":
        return bool(TASK_RE.match(v))
    if col == "model":
        return bool(MODEL_RE.match(v))
    return True


def append_rows(rows):
    """Append rows to runs3.csv (rotating to runs3.1.csv), each as a schema 3 row (COLUMNS; a column the
    row lacks is an empty cell). The v1 and v2 files (runs[2].csv, runs[2].1.csv, their set-aside copies)
    are never written, renamed or rotated. A row with an invalid session, id, type or status is not
    written (every reader drops it); an optional string cell that is not valid is written empty. So no
    written cell needs csv quoting (_csv_rows)."""
    if not rows:
        return
    old, cur = v3_paths()
    with Locked(os.path.join(usage_dir(), APPEND_LOCK), wait=APPEND_LOCK_WAIT_S) as lk:
        if not lk.ok:            # scan_once reloads its state: the rows are derived again next tick
            raise TimeoutError(APPEND_LOCK + " busy")
        _rotate_if_needed(cur, old)
        new = not os.path.exists(cur) or os.path.getsize(cur) == 0
        buf = io.StringIO()
        w = csv.DictWriter(buf, fieldnames=COLUMNS, extrasaction="ignore", lineterminator="\n")
        if new:
            w.writeheader()
        for r in rows:
            if not all(isinstance(r.get(c), str) and valid_cell(c, r[c]) for c in REQUIRED_STRINGS):
                continue                 # a row every reader drops (bad session, id, type or status)
            r = dict(r, schema_version=SCHEMA_VERSION)
            for c in OPTIONAL_STRINGS:
                v = r.get(c)
                if v not in (None, "") and not (isinstance(v, str) and valid_cell(c, v)):
                    r[c] = ""
            w.writerow(r)
        fd = os.open(cur, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
        try:
            os.write(fd, buf.getvalue().encode("utf-8"))
        finally:
            os.close(fd)


class Unreadable(Exception):
    """A row file the strict reader refuses (read_rows(strict=True), rotation)."""


def _csv_rows(fh, strict=False):
    """The rows of a CSV file as csv.DictReader gives them (a short row's missing cells None, extra
    cells under the key None), each physical line parsed on its own: no valid cell holds a quote, comma
    or newline, so a line the csv module refuses or a NUL (csv on Python < 3.11 refuses it) costs that
    line only, never the rest of the file, and an unbalanced quote cannot swallow the lines after it.
    strict (rotation): such a line raises csv.Error instead."""
    header = None
    for ln in fh:
        if "\x00" in ln:
            if strict:
                raise csv.Error("line contains NUL")
            ln = ln.replace("\x00", "")
        try:
            cells = next(csv.reader((ln,), strict=strict), None)
        except csv.Error:
            if strict:
                raise
            continue
        if not cells:
            continue                    # a blank line, as DictReader
        if header is None:
            header = cells
            continue
        row = dict(zip(header, cells))
        for k in header[len(cells):]:
            row[k] = None
        if len(cells) > len(header):
            row[None] = cells[len(header):]
        yield row


def read_rows(paths=None, schemas=None, strict=False):
    """{(session, id, seg): row}, the last row of a key winning, over the given files (default: runs.1.csv,
    runs.csv, runs2.1.csv, runs2.csv, runs3.1.csv, runs3.csv in that order: the v1 and v2 histories,
    then v3). Every row has all COLUMNS keys: a v1 or v2 row has the columns its schema lacks empty
    (`model` among them: unknown, never guessed) and a v1 row src = seed_v1. Rows of another schema
    version, with a bad session/id/type/status or a non-numeric seg are skipped; an invalid optional
    string cell (parent, node, task, model, ...) is read as empty. A malformed line (csv, NUL, bad UTF-8)
    is skipped alone; strict=True raises Unreadable on it instead (rotation). `schemas` limits the
    accepted schema versions; by default a file holds the schema of its name (file_schemas). Nothing is
    filtered by model here (rotation keeps every row): the learners do that (stack_limits.model_mismatch)."""
    out = {}
    for p in paths or csv_paths():
        accept = schemas or file_schemas(p)
        try:
            fh = open(p, encoding="utf-8", errors="strict" if strict else "replace", newline="")
        except FileNotFoundError:
            continue
        except OSError as exc:
            if strict:
                raise Unreadable(p) from exc
            continue
        with fh:
            try:
                for r in _csv_rows(fh, strict):
                    ver = r.get("schema_version")
                    if ver not in accept:
                        continue
                    if not (ID_RE.match(r.get("session") or "") and ID_RE.match(r.get("id") or "")):
                        continue
                    try:
                        k = (r["session"], r["id"], int(r["seg"]))
                    except (KeyError, TypeError, ValueError):
                        continue
                    if ver != "1" and not (valid_cell("type", r.get("type") or "") and
                                           valid_cell("status", r.get("status") or "")):
                        continue
                    r = {c: (r.get(c) if isinstance(r.get(c), str) else "") for c in COLUMNS}
                    if ver == "1":
                        r["src"] = "seed_v1"
                    for c in OPTIONAL_STRINGS:
                        if r[c] != "" and not valid_cell(c, r[c]):
                            r[c] = ""
                    out[k] = r
            except (csv.Error, UnicodeDecodeError) as exc:     # strict only: _csv_rows skips the line
                if strict:
                    raise Unreadable(p) from exc
    return out


read_rows_v2 = read_rows


def runs_view(rows, session=None):
    """Agent runs: the segment rows of each (session, id) aggregated."""
    agg = {}
    for (s, aid, seg), r in sorted(rows.items()):
        if (session and s != session) or r.get("is_main") == "1":     # main-thread and session rows are no agents
            continue
        a = agg.setdefault((s, aid), {"session": s, "id": aid, "type": r["type"], "segments": 0, "api_calls": 0,
                                      "ctx": 0, "output": 0, "first_ts": None, "last_ts": None, "compacted": 0,
                                      "turn_limited": 0, "status": "complete"})
        a["type"] = r["type"]
        a["segments"] += 1
        for k in ("api_calls", "ctx", "output", "compacted"):
            try:
                a[k] += int(float(r[k] or 0))
            except ValueError:
                pass
        a["turn_limited"] = max(a["turn_limited"], int(r["turn_limited"] or 0))
        for k, f in (("first_ts", min), ("last_ts", max)):
            try:
                v = float(r[k])
            except (TypeError, ValueError):
                continue
            a[k] = v if a[k] is None else f(a[k], v)
        if r["status"] == "partial":
            a["status"] = "partial"
    for a in agg.values():
        a["wall_s"] = round(a["last_ts"] - a["first_ts"], 3) if a["first_ts"] and a["last_ts"] else None
    return list(agg.values())


# ---------------------------------------------------------------- the collector
UV_PATHS = ("~/.local/bin/uv", "/opt/homebrew/bin/uv", "/usr/local/bin/uv", "~/.cargo/bin/uv")
PS_PATHS = ("/bin/ps", "/usr/bin/ps")
_EXE = {}                 # name -> absolute path or None, resolved once per process


def _exe(name, candidates):
    """The first executable regular file among fixed absolute candidates (install.sh puts uv in
    Homebrew's bin or ~/.local/bin), resolved once; None when there is none. Never a PATH lookup: an
    agent-writable directory on PATH (an activated project .venv/bin) cannot substitute uv or ps."""
    if name not in _EXE:
        found = None
        for c in candidates:
            c = os.path.expanduser(c)
            if os.path.isabs(c) and os.path.isfile(c) and os.access(c, os.X_OK):
                found = c
                break
        _EXE[name] = found
    return _EXE[name]


def find_ps():
    return _exe("ps", PS_PATHS)


def proc_info(pid):
    """(ppid, comm, lstart) of a process; None when it is gone (or no ps at its fixed paths)."""
    ps = find_ps()
    if ps is None:
        return None
    try:
        p = subprocess.run([ps, "-o", "ppid=", "-o", "lstart=", "-o", "comm=", "-p", str(int(pid))],
                           stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=3)
    except (OSError, subprocess.SubprocessError, ValueError):
        return None
    line = p.stdout.strip()
    m = re.match(r"^(\d+)\s+(\w{3}\s+\w{3}\s+\d+\s+[\d:]+\s+\d{4})\s+(.*)$", line)
    if not m:
        return None
    return int(m.group(1)), os.path.basename(m.group(3).strip()).lstrip("-"), m.group(2)


def find_owner():
    """The Claude Code process that ran this hook: the first ancestor that is not a shell."""
    pid = os.getppid()
    for _ in range(6):
        if pid <= 1:
            return None
        info = proc_info(pid)
        if info is None:
            return None
        if info[1] not in SHELLS:
            return pid
        pid = info[0]
    return None


def alive(pid, lstart=None):
    """Whether the owner process still runs; with lstart, also that its pid was not reused."""
    if not pid:
        return True
    try:
        os.kill(int(pid), 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        pass
    except (OSError, ValueError):
        return False
    if lstart:
        info = proc_info(pid)
        if info is not None and info[2] != lstart:
            return False
    return True


def load_state(sd):
    st = read_json(os.path.join(sd, "state.json")) or {}
    if st.get("v") != SCHEMA_VERSION:
        # another schema's state (an older collector): the transcripts are read again from the start, so
        # every row of the session is written anew in this schema (the last row per key wins)
        st = {"v": SCHEMA_VERSION, "agents": {}}
    return st


def save_state(sd, st):
    write_json_atomic(os.path.join(sd, "state.json"), st)


def scan_once(sid, folder, final=False, st=None, sd=None, commit=None):
    """Scan until no transcript has a backlog; rows appended, state saved. On an error the state
    is reloaded from disk (nothing counted twice, nothing skipped) and the error raised."""
    sd = sd or session_dir(sid)
    st = load_state(sd) if st is None else st
    commit = read_stack_commit() if commit is None else commit
    total, grew_any = [], False
    try:
        for _ in range(1000):
            rows, grew = scan(st, sid, folder, final=final, commit=commit)
            append_rows(rows)
            save_state(sd, st)
            total += rows
            grew_any = grew_any or grew
            if not st.get("more"):
                break
    except Exception:
        st.clear()
        st.update(load_state(sd))
        raise
    return total, grew_any


def prune_sessions(keep):
    """Collector folders of sessions idle for 14 days (no collector holding their lock)."""
    base = os.path.join(usage_dir(), "sessions")
    now = time.time()
    try:
        names = os.listdir(base)
    except OSError:
        return
    for s in names:
        p = os.path.join(base, s)
        if s == keep or not os.path.isdir(p):
            continue
        try:
            last = max([os.path.getmtime(p)] + [os.path.getmtime(os.path.join(p, f)) for f in os.listdir(p)])
        except OSError:
            continue
        if now - last < 14 * 86400:
            continue
        with Locked(os.path.join(p, "collector.lock"), nb=True) as lk:
            if lk.ok:
                shutil.rmtree(p, ignore_errors=True)


def propose_limits():
    """The proposer of the learned limits (stack_limits.propose, a stdlib writer of proposals.json: inputs
    to the NEXT SessionStart). Skipped silently when stack_limits is not importable or fails; it never
    changes a live limit or a snapshot (S6 U4)."""
    if HERE not in sys.path:
        sys.path.insert(0, HERE)
    try:
        import stack_limits
        fn = getattr(stack_limits, "propose", None)
        return fn() if callable(fn) else None
    except Exception:  # noqa: BLE001 - absent, unfinished (NotImplementedError) or failing: not our failure
        return None


def run(sid, folder, owner=None, poll=None, idle=None):
    """The collector loop. Returns the exit reason. Exit order: final scan (rows appended), propose
    (proposals.json), the uv refresh (the candidate scheduler model)."""
    if not enabled():
        return "disabled"
    sd = session_dir(sid)
    poll = knob("STACK_USAGE_POLL_S", 5.0) if poll is None else poll
    idle = knob("STACK_USAGE_IDLE_S", 7200.0) if idle is None else idle
    with Locked(os.path.join(sd, "collector.lock"), nb=True) as lk:
        if not lk.ok:
            return "already running"
        lstart = None
        if owner:
            info = proc_info(owner)
            lstart = info[2] if info else None
        started = time.time()
        meta = {"pid": os.getpid(), "owner": owner, "started": round(started, 3), "heartbeat": round(started, 3),
                "rows": 0, "exited": None, "reason": None}
        write_json_atomic(os.path.join(sd, "collector.json"), meta)
        try:
            prune_sessions(sid)
        except Exception:  # noqa: BLE001 - housekeeping only
            pass
        st = load_state(sd)
        commit = read_stack_commit()                      # the installed stack, as of the collector's start
        last_growth, last_beat, last_pid_check, reason = time.time(), 0.0, time.time(), None
        stop = {"sig": False}
        signal.signal(signal.SIGTERM, lambda *_: stop.update(sig=True))
        while True:
            now = time.time()
            ended = os.path.exists(os.path.join(sd, "end"))
            check_reuse = now - last_pid_check >= 60          # a ps call once a minute, kill(0) every tick
            gone = not alive(owner, lstart if check_reuse else None)
            if check_reuse:
                last_pid_check = now
            final = ended or gone or stop["sig"]
            try:
                rows, grew = scan_once(sid, folder, final=final, st=st, sd=sd, commit=commit)
                meta["rows"] += len(rows)
            except Exception:  # noqa: BLE001 - never die on a bad line or a full disk; retry next tick
                grew = False
            now = time.time()
            if grew:
                last_growth = now
            if final:
                reason = "session end" if ended else ("owner gone" if gone else "signal")
                break
            if now - last_growth > idle:
                reason = "idle"
                break
            if now - last_beat >= 30:
                meta["heartbeat"] = round(now, 3)
                write_json_atomic(os.path.join(sd, "collector.json"), meta)
                last_beat = now
            time.sleep(poll)
        meta.update(heartbeat=round(time.time(), 3), exited=round(time.time(), 3), reason=reason)
        write_json_atomic(os.path.join(sd, "collector.json"), meta)
    if reason in ("session end", "owner gone", "idle"):
        propose_limits()
        refresh(trigger=reason, session=sid)      # the refit takes this session's snapshot soft limits
    return reason


def spawn_collector(sid, folder, owner):
    cmd = [sys.executable, os.path.abspath(__file__), "run", "--session", sid, "--subagents", folder]
    if owner:
        cmd += ["--owner-pid", str(owner)]
    subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     close_fds=True, start_new_session=True, cwd="/")


def hook_start(ev, owner=None):
    if not enabled():
        return "disabled"
    sid = ev.get("session_id")
    if not isinstance(sid, str) or not ID_RE.match(sid):
        return "no session"
    folder = subagents_dir(ev)
    if not folder:
        return "no transcript"
    sd = session_dir(sid)
    try:
        os.unlink(os.path.join(sd, "end"))   # the session runs (again): a stale marker would stop it
    except OSError:
        pass
    with Locked(os.path.join(sd, "collector.lock"), nb=True) as lk:
        if not lk.ok:
            return "running"
    spawn_collector(sid, folder, owner if owner is not None else find_owner())
    return "started"


def hook_end(ev):
    sid = ev.get("session_id")
    if not isinstance(sid, str) or not ID_RE.match(sid):
        return "no session"
    d = session_dir(sid, create=False)
    if not os.path.isdir(d):
        return "no collector"
    with open(os.path.join(d, "end"), "w") as fh:
        fh.write("%.3f\n" % time.time())
    return "marked"


# ---------------------------------------------------------------- refresh (stack_sched_refresh.py)
def find_uv():
    """uv at a fixed install path (UV_PATHS), never from PATH; None: the refresh is skipped."""
    return _exe("uv", UV_PATHS)


# what steers uv's interpreter choice for `uv run --script` (an active venv or conda env, a parent uv,
# a pinned Python, a config file) or what Python imports: the refit runs unsandboxed at the collector's
# exit, so none of it comes from the session's environment (install.sh warms the cache the same way)
REFRESH_ENV_DROP = ("VIRTUAL_ENV", "CONDA_PREFIX", "CONDA_DEFAULT_ENV", "UV_INTERNAL__PARENT_INTERPRETER",
                    "UV_PYTHON", "UV_CONFIG_FILE", "PYTHONPATH", "PYTHONHOME")
REFRESH_PATH = "/usr/bin:/bin:/usr/sbin:/sbin"


def refresh_env():
    """The environment of the refit's uv: os.environ without REFRESH_ENV_DROP, PATH = REFRESH_PATH (no
    project .venv/bin), no __pycache__ in the hooks folder. It runs with --no-config and cwd "/"."""
    env = {k: v for k, v in os.environ.items() if k not in REFRESH_ENV_DROP}
    env.update(PATH=REFRESH_PATH, PYTHONDONTWRITEBYTECODE="1")
    return env


def _fingerprint():
    fp = []
    for p in csv_paths() + (os.path.join(HERE, "sched_model.json"),):
        try:
            s = os.stat(p)
            fp.append([os.path.basename(p), s.st_size, int(s.st_mtime)])
        except OSError:
            fp.append([os.path.basename(p), 0, 0])
    return fp


def refresh(trigger="manual", online=False, force=False, session=None):
    """Run stack_sched_refresh.py through uv (pandas/numpy). Offline by default: without uv or a
    warm uv cache it is skipped and refresh.json says so. session: the collector's session id, passed
    as --session (its limits snapshot gives the soft limits; a bad id is dropped). Returns the
    recorded result."""
    rec_path = os.path.join(usage_dir(), "refresh.json")
    prev = read_json(rec_path) or {}
    res = {"ts": round(time.time(), 3), "trigger": trigger, "status": None, "rc": None, "summary": None}
    if trigger != "manual" and os.environ.get("STACK_USAGE_REFRESH", "1").strip() == "0":
        return {"status": "off (STACK_USAGE_REFRESH=0)"}
    os.makedirs(usage_dir(), mode=0o700, exist_ok=True)
    with Locked(os.path.join(usage_dir(), "refresh.lock"), nb=True) as lk:
        if not lk.ok:
            return {"status": "skipped: another refresh runs"}
        fp = _fingerprint()
        if not force and prev.get("status") == "ok" and prev.get("fingerprint") == fp \
                and os.path.exists(active_model_path()):
            return {"status": "skipped: no new rows"}
        script = os.path.join(HERE, "stack_sched_refresh.py")
        uv = find_uv()
        if uv is None or not os.path.exists(script):
            res["status"] = "skipped: uv not found" if uv is None else "skipped: stack_sched_refresh.py missing"
        else:
            cmd = [uv, "run", "--quiet", "--no-config"] + ([] if online else ["--offline"]) + [
                "--script", script, "--usage", usage_dir(), "--out", active_model_path()]
            if isinstance(session, str) and ID_RE.match(session):
                cmd += ["--session", session]
            env = refresh_env()
            if not online:
                env["UV_OFFLINE"] = "1"
            # the cache install.sh warms (sandboxed commands cannot write there), when it exists
            cache = os.path.join(state_root() + "-cache", "uv")
            if os.path.isdir(cache) and "UV_CACHE_DIR" not in os.environ:
                env["UV_CACHE_DIR"] = cache
            try:
                p = subprocess.run(cmd, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=1800,
                                   env=env, cwd="/")
                res["rc"] = p.returncode
                last = (p.stdout.strip().splitlines() or [""])[-1]
                # only the script's own one-line numeric summary is kept, never uv's or Python's text
                res["summary"] = last[:240] if last.startswith("refresh:") else None
                res["status"] = "ok" if p.returncode == 0 else (
                    "skipped: uv cache lacks pandas/numpy (run `stack_usage.py refresh --online` once)"
                    if not online else "failed (exit %d)" % p.returncode)
            except subprocess.TimeoutExpired:
                res["status"] = "failed: timeout"
            except OSError as exc:
                res["status"] = "skipped: %s" % type(exc).__name__
        res["fingerprint"] = fp
        write_json_atomic(rec_path, res)
    return res


# ---------------------------------------------------------------- status and proposals
def collectors():
    """[(session, running, heartbeat)] of every collector folder."""
    base = os.path.join(usage_dir(), "sessions")
    out = []
    try:
        names = sorted(os.listdir(base))
    except OSError:
        return out
    for s in names:
        d = os.path.join(base, s)
        meta = read_json(os.path.join(d, "collector.json")) or {}
        with Locked(os.path.join(d, "collector.lock"), nb=True) as lk:
            running = not lk.ok
        out.append((s, running, meta.get("heartbeat")))
    return out


def status_line():
    if not enabled():
        return "usage collector off (STACK_USAGE_COLLECT=0)"
    if os.path.isdir(usage_dir()) and not os.access(usage_dir(), os.R_OK | os.X_OK):
        return "usage collector: %s not readable from here (a sandboxed shell?)" % usage_dir()
    rows = read_rows()
    sessions = {k[0] for k in rows}
    running = [c for c in collectors() if c[1]]
    act = read_json(active_model_path())
    if act and isinstance(act.get("types"), dict):
        sup = sum(1 for v in act["types"].values() if isinstance(v, dict) and v.get("status") == "supported")
        model = "active model %s (%d/%d types supported)" % ((act.get("refresh") or {}).get("refreshed") or
                                                              act.get("generated"), sup, len(act["types"]))
    else:
        model = "no active model yet (the shipped sched_model.json is used)"
    ref = read_json(os.path.join(usage_dir(), "refresh.json")) or {}
    last = "last refresh: %s" % (ref.get("status") or "never")
    return "usage collector: %d running, %d segment rows from %d sessions; %s; %s" % (
        len(running), len(rows), len(sessions), model, last)


def frontmatter(agents_dir):
    out = {}
    for f in sorted(glob.glob(os.path.join(agents_dir, "*.md"))):
        try:
            txt = open(f, encoding="utf-8").read()
        except OSError:
            continue
        m = re.match(r"---\n(.*?)\n---", txt, re.S)
        fm = m.group(1) if m else ""
        name = re.search(r"^name:\s*(\S+)", fm, re.M)
        mt = re.search(r"^maxTurns:\s*(\d+)", fm, re.M)
        out[name.group(1) if name else os.path.basename(f)[:-3]] = int(mt.group(1)) if mt else None
    return out


def propose(model_path=None, agents_dir=None):
    """Lines comparing the model's turns and context with each type's maxTurns and soft limit.
    Prints only; nothing is written. Heuristic: maxTurns below 1.2 x turns L (p90), or more than
    3 x L; soft limit below ctx at L, or more than 4 x ctx at L. Supported types only."""
    path = model_path or (active_model_path() if os.path.exists(active_model_path())
                          else os.path.join(HERE, "sched_model.json"))
    J = read_json(path)
    if not J or not isinstance(J.get("types"), dict):
        return ["no model at %s" % path]
    fm = frontmatter(agents_dir or os.path.join(os.path.dirname(HERE), "agents"))
    lines = ["# proposals from %s (prints only; edit SOFT_LIMITS / frontmatter by hand)" % path]
    for t, v in sorted(J["types"].items()):
        if not isinstance(v, dict) or v.get("status") != "supported":
            continue
        L = (v.get("turns") or {}).get("L")
        a, b = (v.get("ctx") or {}).get("a"), (v.get("ctx") or {}).get("b")
        mt = fm.get(t, v.get("maxTurns"))
        if L and mt:
            if mt < 1.2 * L:
                lines.append("%s: maxTurns %d < 1.2 x turns L %.0f: consider ~%d" % (t, mt, L, int(1.5 * L)))
            elif mt > 3 * L:
                lines.append("%s: maxTurns %d > 3 x turns L %.0f: could be ~%d" % (t, mt, L, int(1.5 * L)))
        soft = v.get("soft_limit")
        if L and a is not None and b is not None and soft:
            c = a * L + b * L * L
            if soft < c:
                lines.append("%s: soft limit %.3gM < ctx at L %.3gM: consider ~%.3gM" % (t, soft / 1e6, c / 1e6,
                                                                                          1.3 * c / 1e6))
            elif soft > 4 * c:
                lines.append("%s: soft limit %.3gM > 4 x ctx at L %.3gM" % (t, soft / 1e6, c / 1e6))
    if len(lines) == 1:
        lines.append("no drift beyond the thresholds")
    return lines


# ---------------------------------------------------------------- CLI
def _arg(argv, name, default=None):
    if name in argv:
        i = argv.index(name)
        if i + 1 < len(argv):
            return argv[i + 1]
    return default


def _hook_event():
    try:
        ev = json.loads(sys.stdin.read() or "{}")
        return ev if isinstance(ev, dict) else {}
    except (ValueError, RecursionError):
        return {}


def main(argv):
    cmd = argv[1] if len(argv) > 1 else ""
    if cmd in ("start", "end"):
        # hooks: never fail, never print
        try:
            ev = _hook_event()
            (hook_start if cmd == "start" else hook_end)(ev)
        except Exception:  # noqa: BLE001
            pass
        return 0
    if cmd == "run":
        sid, folder = _arg(argv, "--session"), _arg(argv, "--subagents")
        if not (sid and ID_RE.match(sid) and folder):
            return 2
        owner = _arg(argv, "--owner-pid")
        try:
            run(sid, folder, int(owner) if owner else None)
        except Exception:  # noqa: BLE001 - a detached job: nothing to report to
            pass
        return 0
    if cmd == "scan":
        sid, folder = _arg(argv, "--session"), _arg(argv, "--subagents")
        if not (sid and ID_RE.match(sid) and folder):
            sys.stderr.write("usage: stack_usage.py scan --session ID --subagents DIR [--final]\n")
            return 2
        rows, _ = scan_once(sid, folder, final="--final" in argv)
        print("%d rows" % len(rows))
        return 0
    if cmd == "runs":
        view = runs_view(read_rows(), _arg(argv, "--session"))
        if "--json" in argv:
            print(json.dumps(view, indent=1))
        else:
            cols = ["session", "id", "type", "segments", "api_calls", "ctx", "wall_s", "compacted", "turn_limited",
                    "status"]
            print("\t".join(cols))
            for r in view:
                print("\t".join(str(r[c])[:12] if c == "session" else str(r[c]) for c in cols))
        return 0
    if cmd == "status":
        print(status_line())
        return 0
    if cmd == "refresh":
        print(json.dumps(refresh("manual", online="--online" in argv, force="--force" in argv)))
        return 0
    if cmd == "propose":
        print("\n".join(propose(_arg(argv, "--model"), _arg(argv, "--agents"))))
        return 0
    sys.stderr.write("usage: stack_usage.py start|end (hooks) | runs [--session ID] [--json] | status | "
                     "refresh [--online] [--force] | propose [--model F] [--agents DIR] | "
                     "scan --session ID --subagents DIR [--final] | run --session ID --subagents DIR\n")
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
