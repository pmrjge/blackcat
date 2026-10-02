#!/usr/bin/env python3
"""stack_usage.py - per-session usage collector of the claude-agent-stack (stdlib only, Python 3.9+).

A background job per Claude Code session reads the session's subagent transcripts incrementally and
appends one row per agent segment (a spawn or a resume) to a CSV that the scheduler's cost model is
refitted from (stack_sched_refresh.py). Numbers and ids only: no prompt, transcript text, tool
input or secret is ever written.

Hook entry points (settings.json; both read the hook's JSON on stdin and exit 0 at once):
  stack_usage.py start      SessionStart and SubagentStart: start the session's collector, detached
                            (new session, stdio on /dev/null), unless one runs already
  stack_usage.py end        SessionEnd: write the session's end marker; the collector sees it, scans
                            one last time, refreshes the active model and exits
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
  usage/runs.csv              segment rows (COLUMNS), append-only under usage/runs.lock (fcntl),
                              header line, last row per (session, id, seg) wins
  usage/runs.1.csv            the archive: rows rotated out of runs.csv (STACK_USAGE_MAX_BYTES)
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
"""
import csv
import errno
import fcntl
import glob
import io
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone

SCHEMA_VERSION = 1
COLUMNS = ["schema_version", "session", "id", "type", "seg", "status", "api_calls", "ctx", "input", "output",
           "cache_creation", "cache_read", "first_cc", "first_cr", "peak", "prev_peak", "gap_s", "first_ts",
           "last_ts", "wall_s", "compacted", "turn_limited", "after_limit"]
STRING_COLUMNS = ("session", "id", "type", "status")      # every other column is a number (or empty)
KEY = ("session", "id", "seg")

# transcript parsing: the same constants as tests/derive_thresholds.py
F = ("input_tokens", "output_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")
RESUME_RE = re.compile(r"^(Another Claude session|The coordinator) sent a message while you were working")
COMPACT_RE = re.compile(r"^This session is being continued from a previous conversation")
TURN_LIMIT_RE = re.compile(r"turn limit", re.I)
TEXT_HEAD = 300           # derive_thresholds matches only the first 300 characters of a user message
LIVE_S = 600

ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
TYPE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,79}$")
UNKNOWN_TYPE = "(unknown)"
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


def new_agent():
    return {"off": 0, "ino": None, "type": None, "nseg": 0, "cur": None, "last_kind": None, "last_evt": None,
            "win": {}, "prev": None, "prev_tl": False, "emitted": {}}


def _new_seg(a):
    a["cur"] = {"idx": a["nseg"], "n": 0, "in": 0, "out": 0, "cc": 0, "cr": 0, "peak": 0, "fts": None, "lts": None,
                "fcc": 0, "fcr": 0, "fkey": None, "lkey": None, "comp": 0, "tl": False,
                "after": bool(a["prev_tl"]), "gap": None, "prev_peak": None}
    a["nseg"] += 1
    if a["prev"]:
        a["cur"]["prev_peak"] = a["prev"]["peak"]


def _finish_seg(a, out):
    """The current segment ends because a new one starts: its final row (complete)."""
    cur = a["cur"]
    if cur is None:
        return
    if cur["n"]:
        out.append(seg_row_values(cur, "complete", bool(cur["tl"])))
        a["prev"] = {"peak": cur["peak"], "lts": cur["lts"]}
    a["prev_tl"] = bool(cur["tl"])


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
        if a["cur"] is None:
            _new_seg(a)
        cur = a["cur"]
        w = {"v": [0, 0, 0, 0], "tools": False, "seg": cur["idx"]}
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
    old = w["v"]
    nv = [max(o, v) for o, v in zip(old, vals)]
    for i, k in enumerate(("in", "out", "cc", "cr")):
        cur[k] += nv[i] - old[i]
    w["v"] = nv
    w["tools"] = w["tools"] or tools
    ctx = nv[0] + nv[2] + nv[3]
    cur["peak"] = max(cur["peak"], ctx)
    if cur["fkey"] == key:
        cur["fcc"], cur["fcr"] = nv[2], nv[3]
    if cur["lkey"] == key:
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


def seg_row_values(cur, status, tl):
    """The numeric part of a segment row (session, id and type are added by the caller)."""
    def num(x):
        return "" if x is None else (round(x, 3) if isinstance(x, float) else x)
    return {"seg": cur["idx"], "status": status, "api_calls": cur["n"],
            "ctx": cur["in"] + cur["cc"] + cur["cr"], "input": cur["in"], "output": cur["out"],
            "cache_creation": cur["cc"], "cache_read": cur["cr"], "first_cc": cur["fcc"], "first_cr": cur["fcr"],
            "peak": cur["peak"], "prev_peak": num(cur["prev_peak"]),
            "gap_s": num(cur["gap"]),
            "first_ts": num(cur["fts"]), "last_ts": num(cur["lts"]),
            "wall_s": num(cur["lts"] - cur["fts"]) if cur["lts"] is not None and cur["fts"] is not None else "",
            "compacted": cur["comp"], "turn_limited": int(bool(tl)), "after_limit": int(bool(cur["after"]))}


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
    status = "partial" if (end in ("tool", "tr") and live) else "complete"
    tl = cur["tl"] or (end == "tr" and not live)
    return seg_row_values(cur, status, tl)


# ---------------------------------------------------------------- scanning a session
def agent_type(folder, aid):
    meta = read_json(os.path.join(folder, "agent-%s.meta.json" % aid)) or {}
    t = meta.get("agentType")
    return t if isinstance(t, str) and TYPE_RE.match(t) else None


def scan(st, sid, folder, final=False, now=None):
    """Read what the session's subagent transcripts gained since the last scan. Returns the rows
    to append (only rows that differ from the last one written for their key) and whether any
    transcript grew."""
    now = time.time() if now is None else now
    agents = st.setdefault("agents", {})
    rows, grew = [], False
    st["more"] = False
    for path in sorted(glob.glob(os.path.join(folder, "agent-*.jsonl"))):
        aid = os.path.basename(path)[len("agent-"):-len(".jsonl")]
        if not ID_RE.match(aid):
            continue
        try:
            stt = os.stat(path)
        except OSError:
            continue
        a = agents.get(aid)
        if a is None or a.get("ino") != stt.st_ino or stt.st_size < a.get("off", 0):
            emitted = a["emitted"] if a else {}
            a = agents[aid] = new_agent()
            a["ino"] = stt.st_ino
            a["emitted"] = emitted
        if a["type"] is None:
            a["type"] = agent_type(folder, aid)
        out, data = [], b""
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
                        feed_line(a, line.decode("utf-8", "replace"), out)
                        _set_gap(a)
                a["off"] += cut + 1
            elif len(data) == READ_CHUNK:
                a["off"] += len(data)
                a["skip"] = True
            else:
                a["off"] += start
        pending = len(data) == READ_CHUNK
        if pending:
            st["more"] = True            # a backlog: read on (the segment is not finished yet)
        live = pending or (not final and (now - stt.st_mtime) < LIVE_S)
        cr = current_row(a, live)
        if cr is not None:
            out.append(cr)
        atype = a["type"] or UNKNOWN_TYPE
        for vals in out:
            row = dict(schema_version=SCHEMA_VERSION, session=sid, id=aid, type=atype, **vals)
            sig = json.dumps([row[c] for c in COLUMNS])
            k = str(vals["seg"])
            if a["emitted"].get(k) != sig:
                a["emitted"][k] = sig
                rows.append(row)
        # emitted signatures are kept for the last two segments only (older ones never change)
        if a["cur"] is not None:
            for k in [k for k in a["emitted"] if int(k) < a["cur"]["idx"] - 1]:
                a["emitted"].pop(k, None)
    return rows, grew


# ---------------------------------------------------------------- runs.csv
class Locked:
    """flock on a lock file (blocking unless nb=True; `ok` says whether it was taken)."""

    def __init__(self, path, nb=False):
        self.path, self.nb, self.fh, self.ok = path, nb, None, False

    def __enter__(self):
        os.makedirs(os.path.dirname(self.path), mode=0o700, exist_ok=True)
        self.fh = open(self.path, "a")
        try:
            fcntl.flock(self.fh, fcntl.LOCK_EX | (fcntl.LOCK_NB if self.nb else 0))
            self.ok = True
        except OSError as exc:
            if exc.errno not in (errno.EAGAIN, errno.EACCES, errno.EWOULDBLOCK):
                raise
        return self

    def __exit__(self, *exc):
        if self.fh:
            self.fh.close()


def csv_paths():
    u = usage_dir()
    return os.path.join(u, "runs.1.csv"), os.path.join(u, "runs.csv")


def _header_ok(path):
    try:
        with open(path, encoding="utf-8", newline="") as fh:
            return fh.readline().rstrip("\r\n") == ",".join(COLUMNS)
    except OSError:
        return False


ARCHIVE_FACTOR = 4        # runs.1.csv keeps at most this many times STACK_USAGE_MAX_BYTES


def _rotate_if_needed(cur, old):
    """Rotation: once runs.csv passes STACK_USAGE_MAX_BYTES (default 8 MB) it is merged into
    runs.1.csv (the last row per key, newest sessions first, at most ARCHIVE_FACTOR x the cap: the
    oldest sessions beyond that are dropped; the newest one always stays) and starts again empty. A file of another schema is
    set aside as runs.old-schema.csv. Called under runs.lock."""
    cap = knob("STACK_USAGE_MAX_BYTES", 8e6)
    try:
        size = os.path.getsize(cur)
    except OSError:
        return
    if size and not _header_ok(cur):
        os.replace(cur, os.path.join(os.path.dirname(cur), "runs.old-schema.csv"))
        return
    if cap <= 0 or size <= cap:
        return
    by_session = {}
    for k, r in read_rows([old, cur]).items():
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


def append_rows(rows):
    if not rows:
        return
    old, cur = csv_paths()
    with Locked(os.path.join(usage_dir(), "runs.lock")):
        _rotate_if_needed(cur, old)
        new = not os.path.exists(cur) or os.path.getsize(cur) == 0
        buf = io.StringIO()
        w = csv.DictWriter(buf, fieldnames=COLUMNS, extrasaction="ignore", lineterminator="\n")
        if new:
            w.writeheader()
        for r in rows:
            w.writerow(r)
        fd = os.open(cur, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
        try:
            os.write(fd, buf.getvalue().encode("utf-8"))
        finally:
            os.close(fd)


def read_rows(paths=None):
    """{(session, id, seg): row} over the given files (default: runs.1.csv then runs.csv), the last
    row of a key winning. Rows of another schema version or with malformed ids are skipped."""
    out = {}
    for p in paths or csv_paths():
        try:
            fh = open(p, encoding="utf-8", newline="")
        except OSError:
            continue
        with fh:
            for r in csv.DictReader(fh):
                if r.get("schema_version") != str(SCHEMA_VERSION):
                    continue
                if not (ID_RE.match(r.get("session") or "") and ID_RE.match(r.get("id") or "")):
                    continue
                try:
                    k = (r["session"], r["id"], int(r["seg"]))
                except (KeyError, TypeError, ValueError):
                    continue
                out[k] = r
    return out


def runs_view(rows, session=None):
    """Agent runs: the segment rows of each (session, id) aggregated."""
    agg = {}
    for (s, aid, seg), r in sorted(rows.items()):
        if session and s != session:
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
def proc_info(pid):
    """(ppid, comm, lstart) of a process; None when it is gone."""
    try:
        p = subprocess.run(["ps", "-o", "ppid=", "-o", "lstart=", "-o", "comm=", "-p", str(int(pid))],
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
        st = {"v": SCHEMA_VERSION, "agents": {}}
    return st


def save_state(sd, st):
    write_json_atomic(os.path.join(sd, "state.json"), st)


def scan_once(sid, folder, final=False, st=None, sd=None):
    """Scan until no transcript has a backlog; rows appended, state saved. On an error the state
    is reloaded from disk (nothing counted twice, nothing skipped) and the error raised."""
    sd = sd or session_dir(sid)
    st = load_state(sd) if st is None else st
    total, grew_any = [], False
    try:
        for _ in range(1000):
            rows, grew = scan(st, sid, folder, final=final)
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


def run(sid, folder, owner=None, poll=None, idle=None):
    """The collector loop. Returns the exit reason."""
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
                rows, grew = scan_once(sid, folder, final=final, st=st, sd=sd)
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
        refresh(trigger=reason)
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
    for c in (shutil.which("uv"), os.path.expanduser("~/.local/bin/uv"), "/opt/homebrew/bin/uv",
              "/usr/local/bin/uv", os.path.expanduser("~/.cargo/bin/uv")):
        if c and os.access(c, os.X_OK):
            return c
    return None


def _fingerprint():
    fp = []
    for p in csv_paths() + (os.path.join(HERE, "sched_model.json"),):
        try:
            s = os.stat(p)
            fp.append([os.path.basename(p), s.st_size, int(s.st_mtime)])
        except OSError:
            fp.append([os.path.basename(p), 0, 0])
    return fp


def refresh(trigger="manual", online=False, force=False):
    """Run stack_sched_refresh.py through uv (pandas/numpy). Offline by default: without uv or a
    warm uv cache it is skipped and refresh.json says so. Returns the recorded result."""
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
            cmd = [uv, "run", "--quiet"] + ([] if online else ["--offline"]) + ["--script", script,
                                                                                "--usage", usage_dir(),
                                                                                "--out", active_model_path()]
            env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")     # no __pycache__ in the hooks folder
            if not online:
                env["UV_OFFLINE"] = "1"
            # the cache install.sh warms (sandboxed commands cannot write there), when it exists
            cache = os.path.join(state_root() + "-cache", "uv")
            if os.path.isdir(cache) and "UV_CACHE_DIR" not in os.environ:
                env["UV_CACHE_DIR"] = cache
            try:
                p = subprocess.run(cmd, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=1800,
                                   env=env)
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
