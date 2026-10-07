#!/usr/bin/env python3
"""stack_progress.py - per-run brief budgets and the early-stop rule (stdlib only, Python 3.8+, POSIX).

Stage 4 lever L5. agent_guard.py's `budget` PreToolUse gate calls check() for a subagent's tool call once
the hard budgets allowed it, passing the run's usage it already counted (context tokens = input +
cache_creation + cache_read per API call, and API calls, since the registry `started` stamp: the segment
of turns.<type> and soft/hard.agent.<type>). Signals, each at most once per run (evaluate()):

  budget     the run reached its brief's own `budget:` line (prompt-and-brief-design references/
             delegation.md, section 3: `budget: ~N K tokens, <= k children`; `N calls` too). Tokens are
             context tokens, the unit `stack-budget` shows. A note in warn mode.
  stall      the last ROUNDS closed tool rounds made no progress and at least FAILS of them failed (RULE),
             at any usage. Logged only: the evidence for the gate below.
  stop       a stall while the run is past its budget: the brief's, else the type's soft limit
             (soft.agent.<type> of the session snapshot, passed by the caller; a type with none, the
             orchestrator, is never past it). The early-stop note in warn mode.
  recovered  a successful write or delegation after the stall: logged only, the false-stop evidence.
  first_write  S4 L7 B3, logged only: the run's first call of a write or delegate tool by name
             (FIRST_WRITE_TOOLS; attempted, failed or not; shell commands do not count), with `at_call`,
             the 1-based index of the API call that made it (calls before it = at_call - 1): how long a
             run explores before it acts, measured as the Stage-4 ttp.py baseline measured it.

No limit is duplicated: the turn gate, soft/hard.agent, the prompt and session budgets and the MCP cap
stay in agent_guard.py and stack_limits.py, and the usage is the budget gate's. New here: the brief's
budget and the shape of the run (progress, failures, repeats), which no other gate reads.

RULE (replayed on the frozen sessions by tests/derive_early_stop.py, which reports the trade-off):
  a tool round is the tool calls of one API call (one message.id), closed when the next API call starts;
  progress: a successful call of class write (Edit, Write, NotebookEdit; a shell command that commits,
            merges, moves, copies, creates or redirects into a file), delegate (Agent, SendMessage) or
            report (SubagentHandback, TaskStop, AskUserQuestion);
  failing:  a round with an error result (is_error: a hook refusal, a non-zero exit, a tool error), or
            whose every call repeats an earlier call of the run (same tool and input).

Modes, STACK_EARLY_STOP: `observe` (the default; unset or unknown) logs each firing to
<session>/early-stop.jsonl (numbers and ids only) and returns nothing; `warn` also returns one note per
run for the budget and stop signals, which agent_guard adds to the call (additionalContext); `off` reads
nothing. STACK_POLICY=off is off. No refusal mode: enforcement waits for the observe data (`report`).
Fixed knobs, env only: STACK_EARLY_STOP_ROUNDS (3-64, default ROUNDS), STACK_EARLY_STOP_FAILS (0-ROUNDS).

State: <session>/progress/<agent_id>.json (offset, run stamp, the round window, recent call signatures),
replaced atomically under <agent_id>.lock (flock, non-blocking: a parallel call of the same agent skips,
the next one catches up). Fails open: agent_guard wraps check(); an error only skips the signal.

CLI: stack_progress.py report [--session SID] [--json]   early-stop.jsonl joined to usage/reports.jsonl
                                                         (the run's hand-back status), for the campaign
     stack_progress.py --self-test
"""
import errno
import fcntl
import json
import os
import re
import sys
import time
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:      # stack_io.py beside this file, also when loaded by path
    sys.path.insert(0, HERE)
from stack_io import read_json, write_json_atomic  # noqa: E402

MODES = ("off", "observe", "warn")
ROUNDS = 8                  # closed tool rounds in the window
FAILS = 4                   # failing rounds needed in it
ROUNDS_RANGE = (3, 64)
NOVEL_PROGRESS = False      # True: any successful call new to the run counts as progress (calibration)
STATE_DIR = "progress"
LOG = "early-stop.jsonl"
LOG_MAX = 4 << 20           # bytes; past it nothing more is logged
STATE_MAX = 1 << 20
SCAN_BYTES = 8 << 20        # most bytes read per call; the rest waits for the next call
SCAN_S = 0.5
KEYS_KEPT = 8
SEEN_KEPT = 256             # call signatures remembered per run (repeat detection)
WINDOW_KEPT = 64
BRIEF_SCAN = 64 << 10       # chars of a user message searched for a budget line
TOKENS_RANGE = (1000, 10 ** 10)
CALLS_RANGE = (1, 10000)
ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}\Z")
USAGE_KEYS = ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")

WRITE_TOOLS = ("Edit", "Write", "NotebookEdit", "MultiEdit")
DELEGATE_TOOLS = ("Agent", "Task", "SendMessage")
REPORT_TOOLS = ("SubagentHandback", "TaskStop", "AskUserQuestion")
SHELL_TOOLS = ("Bash", "PowerShell")
PROGRESS = ("write", "delegate", "report")
WORK = ("write", "delegate")    # progress that is more than the report: "recovered" counts these
FIRST_WRITE_TOOLS = WRITE_TOOLS + DELEGATE_TOOLS    # B3: by tool name only
# a shell command that changes files or history; a false match only counts as progress (fewer firings)
_SEP = r"(?:^|[\s;&|(`]|\$\()"
WRITE_CMD_RE = re.compile(
    _SEP + r"git(?:\s+-C\s+\S+)?\s+(?:commit|merge|rebase|cherry-pick|am|apply|revert|mv|rm|add|tag|"
           r"restore|switch|checkout|worktree\s+add|stash\s+(?:push|pop|apply))\b"
    r"|" + _SEP + r"(?:mv|cp|mkdir|touch|tee|patch|ln|rm|rsync|install|truncate|unzip)\s"
    r"|\bsed\s+(?:-[A-Za-z]*i|--in-place)|\bperl\s+-[A-Za-z]*i"
    r"|(?<![0-9&>])>>?\s*(?!/dev/null|&)[^\s|;&>]"
    r"|\b(?:uv|pip|npm|pnpm|yarn|cargo|go)\s+(?:add|install|remove|get)\b")

BUDGET_LINE_RE = re.compile(r"(?im)^[ \t>*_`-]*budget[*_`]*[ \t]*:[ \t]*(.+)$")
# Linear on any text (briefs and the run's own text are model-written; a parse past the hook timeout lets the
# call through unchecked): no two adjacent quantifiers over the same characters, and a number starts only
# where no digit (or separator) precedes it, so a run of digits is tried once. Bounded digit runs: a longer
# number is no budget (past the ranges below) and never reaches int()/float() (the 4300-digit limit, inf).
_NUM = r"(?<![\d.,])(\d{1,3}(?:,\d{3}){1,4}|\d{1,15}(?:\.\d{1,9})?)"
TOKENS_RE = re.compile(_NUM + r"\s*(?:([kmb])\s*)?(?:context\s+|ctx\s+)?(?:tokens?|tok)\b", re.I)
CALLS_RE = re.compile(r"(?<!\d)(\d{1,9})\s*(?:tool\s+|api\s+)?(?:calls?|turns?|rounds?)\b", re.I)
STATUS_RE = re.compile(r"(?m)^[ \t>*_`]*STATUS[*_`]*[ \t]*:[ \t]*(?:[*_`]+[ \t]*)?"
                       r"(done|partial|failed|blocked)\b", re.I)

NOTE_BUDGET = ("Brief budget reached: this run has used {used} since you were started or resumed; your "
               "brief set {budget}. Finish the current step and return STATUS: partial with what is done "
               "and what is left, unless only the report remains. This note blocks no tool.")
NOTE_STOP = ("Early-stop check: this run is past its budget ({budget}) and its last {rounds} tool rounds "
             "made no progress (no successful edit, write, commit or delegation); {fails} of them failed "
             "or only repeated earlier calls. Stop retrying: return STATUS: partial with the failing "
             "command, its error and what is left, or NEXT naming who can unblock it. This note blocks "
             "no tool.")


# ---------------------------------------------------------------- knobs
def mode():
    if os.environ.get("STACK_POLICY", "on").strip().lower() == "off":
        return "off"
    m = os.environ.get("STACK_EARLY_STOP", "").strip().lower()
    return m if m in MODES else "observe"


def _knob(name, default, lo, hi):
    try:
        v = int(os.environ.get(name, "").strip())
    except ValueError:
        return default
    return v if lo <= v <= hi else default


def params():
    """(rounds, fails) from the env knobs; an invalid or out-of-range value takes its default."""
    rounds = _knob("STACK_EARLY_STOP_ROUNDS", ROUNDS, *ROUNDS_RANGE)
    return rounds, _knob("STACK_EARLY_STOP_FAILS", min(FAILS, rounds), 0, rounds)


# ---------------------------------------------------------------- brief budget
def _number(digits, suffix):
    v = float(digits.replace(",", ""))
    return int(v * {"k": 1e3, "m": 1e6, "b": 1e9}.get((suffix or "").lower(), 1))


def parse_budget(text):
    """{"tokens": int|None, "calls": int|None} from the first `budget:` line of a message that names
    tokens or calls (in its first BRIEF_SCAN chars), else None. Other items on the line (children,
    searches) are no budget of this run; values outside the sane ranges are dropped."""
    if not isinstance(text, str):
        return None
    for m in BUDGET_LINE_RE.finditer(text[:BRIEF_SCAN]):
        tokens = calls = None
        for part in re.split(r"[;·|]|,(?!\d{3}\b)|\band\b", m.group(1)):   # not 1,500,000
            t = TOKENS_RE.search(part)
            if t:
                v = _number(t.group(1), t.group(2))
                if tokens is None and TOKENS_RANGE[0] <= v <= TOKENS_RANGE[1]:
                    tokens = v
                continue
            c = CALLS_RE.search(part)
            if c and calls is None and CALLS_RANGE[0] <= int(c.group(1)) <= CALLS_RANGE[1]:
                calls = int(c.group(1))
        if tokens or calls:
            return {"tokens": tokens, "calls": calls}
    return None


def budget_text(budget):
    parts = []
    if budget.get("tokens"):
        parts.append("{:,} context tokens".format(budget["tokens"]))
    if budget.get("calls"):
        parts.append("%d API calls" % budget["calls"])
    return " or ".join(parts) or "none"


# ---------------------------------------------------------------- the run's shape
def classify(name, tool_input):
    """write | delegate | report | read."""
    if name in WRITE_TOOLS:
        return "write"
    if name in DELEGATE_TOOLS:
        return "delegate"
    if name in REPORT_TOOLS:
        return "report"
    if name in SHELL_TOOLS and isinstance(tool_input, dict):
        cmd = tool_input.get("command")
        if isinstance(cmd, str) and WRITE_CMD_RE.search(cmd[:8192]):
            return "write"
    return "read"


def signature(name, tool_input):
    """A call's identity for repeat detection: crc32 and adler32 of tool and canonical input (64 bits;
    zlib, not hashlib, keeps the hook's start-up short; a collision only marks one round failing)."""
    try:
        raw = json.dumps(tool_input, sort_keys=True, separators=(",", ":"), default=str)
    except (TypeError, ValueError, RecursionError):
        raw = repr(tool_input)
    data = ("%s\0%s" % (name, raw)).encode("utf-8", "replace")
    return "%08x%08x" % (zlib.crc32(data), zlib.adler32(data))


def new_state(run=None):
    """A run's state (JSON). off/ino/keys/brief carry over to the next run; the rest is the run's."""
    return {"v": 1, "run": run, "off": 0, "ino": None, "keys": [],
            "calls": 0, "ctx": 0, "brief": None, "budget": None,
            "cur": None,        # the open round {"id": message id, "uses": {tool_use_id: [class, repeat, ok]}}
            "seen": [], "win": [],          # closed rounds, oldest first: [progress 0/1, failing 0/1]
            "nround": 0, "nwork": 0,        # closed rounds, and those with a successful write/delegate
            "first_write": None,            # B3: the API call (1-based) of the first write/delegate call
            "status": None, "ended": False, "fired": {}}


def close_round(st):
    """Close the open round into the window; True when it held a tool call."""
    cur = st.get("cur")
    st["cur"] = None
    if not cur or not cur.get("uses"):
        return False
    uses = list(cur["uses"].values())
    prog = any(ok == 1 and (cls in PROGRESS or (NOVEL_PROGRESS and not rep)) for cls, rep, ok in uses)
    fail = any(ok == 0 for _c, _r, ok in uses) or all(rep for _c, rep, _o in uses)
    st["win"] = (st["win"] + [[int(prog), int(fail)]])[-WINDOW_KEPT:]
    st["nround"] = int(st.get("nround") or 0) + 1
    if any(ok == 1 and cls in WORK for cls, _r, ok in uses):
        st["nwork"] = int(st.get("nwork") or 0) + 1
    return True


def _text_of(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(b["text"] for b in content if isinstance(b, dict) and b.get("type") == "text"
                         and isinstance(b.get("text"), str))
    return ""


def feed(st, e, since=None):
    """Update the run state `st` with one transcript record `e`. An assistant record timestamped before
    `since` (the run stamp, as the transcripts write it) belongs to an earlier run: only its dedupe key
    is kept. A user message's `budget:` line is read whatever its time (the opening message of a resume
    can carry a stamp just before the run's); the run's first API call fixes the budget in force.
    Returns True when the record closed a tool round."""
    if not isinstance(e, dict):
        return False
    ts = e.get("timestamp")
    early = since is not None and isinstance(ts, str) and len(ts) == len(since) and ts < since
    msg = e.get("message") if isinstance(e.get("message"), dict) else {}
    content = msg.get("content")
    closed = False
    if e.get("type") == "assistant":
        mid = msg.get("id") or e.get("uuid")
        if st["cur"] is not None and st["cur"].get("id") != mid:
            closed = close_round(st)
        usage = msg.get("usage")
        key = "%s|%s" % (msg.get("id"), e.get("requestId"))
        if isinstance(usage, dict) and key not in st["keys"]:
            st["keys"] = (st["keys"] + [key])[-KEYS_KEPT:]
            if not early:
                try:
                    tokens = sum(int(usage.get(k) or 0) for k in USAGE_KEYS)
                except (TypeError, ValueError):
                    tokens = 0
                st["calls"] += 1
                st["ctx"] += max(tokens, 0)
                if st["calls"] == 1:
                    st["budget"] = st.get("brief")
        if early or not isinstance(content, list):
            return closed
        for b in content:
            if not isinstance(b, dict):
                continue
            if b.get("type") == "tool_use" and isinstance(b.get("id"), str):
                name = str(b.get("name") or "")
                sig = signature(name, b.get("input"))
                if st["cur"] is None:
                    st["cur"] = {"id": mid, "uses": {}}
                st["cur"]["uses"][b["id"]] = [classify(name, b.get("input")), int(sig in st["seen"]), None]
                if name in FIRST_WRITE_TOOLS and st.get("first_write") is None:
                    st["first_write"] = st["calls"]
                if sig not in st["seen"]:
                    st["seen"] = (st["seen"] + [sig])[-SEEN_KEPT:]
            elif b.get("type") == "text" and isinstance(b.get("text"), str) and b["text"].strip():
                m = STATUS_RE.search(b["text"])
                st["status"] = m.group(1).lower() if m else "clean"
        st["ended"] = st["cur"] is None     # an API call with no tool call so far: the turn ended
        return closed
    if e.get("type") != "user":
        return False
    if isinstance(content, list) and any(isinstance(b, dict) and b.get("type") == "tool_result"
                                         for b in content):
        uses = (st.get("cur") or {}).get("uses") or {}
        for b in content:
            if isinstance(b, dict) and b.get("type") == "tool_result" and b.get("tool_use_id") in uses:
                uses[b["tool_use_id"]][2] = 0 if b.get("is_error") is True else 1
        return False
    budget = parse_budget(_text_of(content))
    if budget:
        st["brief"] = budget
    return False


def gate(st, used_tokens, used_calls, default_tokens):
    """(the budget in force {"tokens", "calls", "src"} or None, whether the usage reached it)."""
    b = st.get("budget")
    if b and (b.get("tokens") or b.get("calls")):
        budget = dict(b, src="brief")
    elif default_tokens:
        budget = {"tokens": int(default_tokens), "calls": None, "src": "soft"}
    else:
        return None, False
    over = bool((budget.get("tokens") and used_tokens >= budget["tokens"])
                or (budget.get("calls") and used_calls >= budget["calls"]))
    return budget, over


def stalled(st, rounds, fails):
    """(fires, failing rounds in the window): the last `rounds` closed rounds hold no progress and at
    least `fails` failing rounds."""
    win = st["win"][-rounds:]
    n = sum(f for _p, f in win)
    if len(win) < rounds or any(p for p, _f in win):
        return False, n
    return n >= fails, n


def evaluate(st, used_tokens, used_calls, default_tokens, rounds=ROUNDS, fails=FAILS):
    """The signals that fire now, each at most once per run: [(signal, budget or None, failing rounds)].
      budget     the usage reached the brief's own budget (a note in warn mode)
      stall      the last `rounds` closed rounds hold no progress and >= `fails` failing ones, at any
                 usage (logged only: the evidence for the gate)
      stop       stall while the usage is past the budget in force, the brief's or else the type's soft
                 limit (the early-stop note in warn mode)
      recovered  a round with a successful write or delegation closed after the stall fired (logged
                 only: the false-stop evidence)
      first_write  the run called a write or delegate tool (logged only; B3, st["first_write"])
    st["fired"][signal] = [closed rounds, work rounds, API calls] when it fired."""
    out, fired = [], st["fired"]
    mark = [int(st.get("nround") or 0), int(st.get("nwork") or 0), int(used_calls)]
    budget, over = gate(st, used_tokens, used_calls, default_tokens)
    if over and budget["src"] == "brief" and "budget" not in fired:
        fired["budget"] = mark
        out.append(("budget", budget, 0))
    stall, n = stalled(st, rounds, fails)
    if stall and "stall" not in fired:
        fired["stall"] = mark
        out.append(("stall", budget, n))
    if stall and over and "stop" not in fired:
        fired["stop"] = mark
        out.append(("stop", budget, n))
    if "stall" in fired and "recovered" not in fired and mark[1] > fired["stall"][1]:
        fired["recovered"] = mark
        out.append(("recovered", budget, 0))
    if st.get("first_write") is not None and "first_write" not in fired:
        fired["first_write"] = mark
        out.append(("first_write", budget, 0))
    return out


# ---------------------------------------------------------------- the hook side
def iso_stamp(t):
    """A time.time() stamp as the transcripts write timestamps (UTC, milliseconds, 'Z')."""
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(t)) + ".%03dZ" % int((t % 1) * 1000)


def scan(st, path, since, deadline):
    """Feed the complete lines appended to `path` since st["off"] (at most SCAN_BYTES, until
    `deadline`, time.monotonic). A replaced or truncated file restarts at its end."""
    try:
        info = os.stat(path)
    except OSError:
        return
    off = int(st.get("off") or 0)
    if st.get("ino") not in (None, info.st_ino) or info.st_size < off:
        st.update(off=info.st_size, ino=info.st_ino, keys=[])
        return
    st["ino"] = info.st_ino
    if info.st_size == off:
        return
    with open(path, "rb") as f:
        f.seek(off)
        start = off
        for line in f:
            if not line.endswith(b"\n") or off - start > SCAN_BYTES or time.monotonic() > deadline:
                break
            off += len(line)
            if b'"assistant"' not in line and b'"user"' not in line:
                continue
            try:
                e = json.loads(line)
            except (ValueError, RecursionError):
                continue
            feed(st, e, since)
    st["off"] = off


def log_row(d, row):
    path = os.path.join(d, LOG)
    try:
        if os.path.getsize(path) > LOG_MAX:
            return
    except OSError:
        pass
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND | getattr(os, "O_NOFOLLOW", 0), 0o600)
    try:
        os.write(fd, (json.dumps(row, separators=(",", ":")) + "\n").encode("utf-8"))
    finally:
        os.close(fd)


def _num(v):
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def check(d, aid, atype, path, run, used_tokens=None, used_calls=None, default_tokens=None, how=None):
    """PreToolUse of a subagent: bring the run's state up to date with its own transcript `path`,
    evaluate, log each firing; the note for this call (mode warn) or None.
    used_tokens/used_calls: the run's usage as the budget gate counted it (None: this module's count).
    default_tokens: the type's soft limit, the gate of a run whose brief names no budget."""
    how = how or mode()
    if how == "off" or not isinstance(aid, str) or not ID_RE.match(aid) or not path:
        return None
    folder = os.path.join(d, STATE_DIR)
    os.makedirs(folder, mode=0o700, exist_ok=True)
    lock = os.open(os.path.join(folder, aid + ".lock"), os.O_RDWR | os.O_CREAT, 0o600)
    try:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            if exc.errno in (errno.EAGAIN, errno.EACCES, errno.EWOULDBLOCK):
                return None
            raise
        spath = os.path.join(folder, aid + ".json")
        st = read_json(spath, limit=STATE_MAX)
        run = _num(run)
        fresh = not isinstance(st, dict) or st.get("v") != 1 or st.get("run") != run
        if not isinstance(st, dict) or st.get("v") != 1:
            st = new_state(run)
        elif st.get("run") != run:          # a new run (spawn or resume): keep the file position
            st = dict(new_state(run), off=st.get("off", 0), ino=st.get("ino"), keys=st.get("keys") or [],
                      brief=st.get("brief"))
        pos = (st.get("off"), st.get("ino"))
        scan(st, path, iso_stamp(run) if run is not None else None, time.monotonic() + SCAN_S)
        tokens = st["ctx"] if used_tokens is None else int(used_tokens)
        calls = st["calls"] if used_calls is None else int(used_calls)
        rounds, fails = params()
        fired = evaluate(st, tokens, calls, _num(default_tokens), rounds, fails)
        if fresh or fired or (st.get("off"), st.get("ino")) != pos:     # else nothing changed
            write_json_atomic(spath, st)
    finally:
        os.close(lock)
    notes = []
    for sig, budget, n in fired:
        b = budget or {}
        row = {"v": 1, "ts": round(time.time(), 3), "agent_id": aid, "type": str(atype)[:80],
               "run": run, "signal": sig, "mode": how, "calls": calls, "ctx": tokens,
               "budget_tokens": b.get("tokens"), "budget_calls": b.get("calls"), "src": b.get("src"),
               "rounds": rounds, "fails": n}
        if sig == "first_write":
            row["at_call"] = st.get("first_write")
        log_row(d, row)
        if sig == "budget":
            used = "{:,} context tokens in {} API calls".format(tokens, calls)
            notes.append(NOTE_BUDGET.format(used=used, budget=budget_text(b)))
        elif sig == "stop":
            notes.append(NOTE_STOP.format(budget=budget_text(b), rounds=rounds, fails=n))
    return "\n\n".join(notes) if notes and how == "warn" else None


# ---------------------------------------------------------------- report (the observe campaign)
def state_root():
    base = os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state")
    return os.path.join(base, "claude-agent-stack")


def _jsonl(path, limit=64 << 20):
    rows = []
    try:
        with open(path, "rb") as f:
            data = f.read(limit)
    except OSError:
        return rows
    for line in data.splitlines():
        try:
            r = json.loads(line)
        except (ValueError, RecursionError):
            continue
        if isinstance(r, dict):
            rows.append(r)
    return rows


def report(session=None):
    """early-stop.jsonl of every session (or one) joined to usage/reports.jsonl by (session, agent id,
    run stamp): {"sessions", "signals": {signal: {outcome: n}}, "types": {type: {signal: n}}}. The
    outcome is the hand-back's STATUS (done, partial, failed, blocked), `handback` for a SubagentHandback
    whose message could not be read, `no-report` when none was logged. "first_write": per outcome, n,
    median and p90 of the first_write rows' at_call (B3)."""
    root = state_root()
    outcome = {}
    for r in _jsonl(os.path.join(root, "usage", "reports.jsonl")):
        outcome[(r.get("session"), r.get("agent_id"), str(r.get("run")))] = str(
            r.get("status") or r.get("format") or "none")
    if session:
        sessions = [session]
    else:
        try:
            sessions = sorted(s for s in os.listdir(root) if os.path.isfile(os.path.join(root, s, LOG)))
        except OSError:
            sessions = []
    out = {"sessions": 0, "signals": {}, "types": {}, "first_write": {}}
    at = {}
    for s in sessions:
        if not isinstance(s, str) or not ID_RE.match(s):
            continue
        rows = _jsonl(os.path.join(root, s, LOG))
        out["sessions"] += bool(rows)
        for r in rows:
            sig = str(r.get("signal"))
            got = outcome.get((s, r.get("agent_id"), str(r.get("run"))), "no-report")
            by = out["signals"].setdefault(sig, {})
            by[got] = by.get(got, 0) + 1
            t = out["types"].setdefault(str(r.get("type")), {})
            t[sig] = t.get(sig, 0) + 1
            if sig == "first_write" and _num(r.get("at_call")) is not None:
                at.setdefault(got, []).append(r["at_call"])
    for got, xs in at.items():
        xs.sort()
        n = len(xs)
        out["first_write"][got] = {"n": n, "median": xs[n // 2] if n % 2 else (xs[n // 2 - 1] + xs[n // 2]) / 2,
                                   "p90": xs[min(n - 1, int(0.9 * n))]}
    return out


# ---------------------------------------------------------------- self-test
def _call(st, k, name="Bash", tool_input=None, error=True):
    feed(st, {"type": "assistant", "requestId": "r%d" % k, "message": {
        "id": "m%d" % k, "usage": {"input_tokens": 10},
        "content": [{"type": "tool_use", "id": "t%d" % k, "name": name,
                     "input": tool_input if tool_input is not None else {"command": "make"}}]}})
    feed(st, {"type": "user", "message": {"content": [
        {"type": "tool_result", "tool_use_id": "t%d" % k, "is_error": error}]}})


def self_test():
    problems = []
    if parse_budget("Goal: x\nbudget: ~300 K tokens, ≤ 3 children\n") != {"tokens": 300000, "calls": None}:
        problems.append("the delegation.md budget form is not parsed")
    if parse_budget("- **Budget**: 2.5M tokens; 40 calls") != {"tokens": 2500000, "calls": 40}:
        problems.append("tokens and calls are not both parsed")
    if parse_budget("budget: at most 6 searches/fetches") is not None \
            or parse_budget("stay within the token budget: be brief") is not None:
        problems.append("a search budget or prose read as a run budget")
    if classify("Bash", {"command": "git -C /r commit -m x"}) != "write" \
            or classify("Bash", {"command": "pytest -q 2>&1 | tail -5"}) != "read" \
            or classify("Bash", {"command": "ls > /dev/null"}) != "read":
        problems.append("shell write classes are wrong")
    st = new_state()
    for k in range(10):
        _call(st, k)
    if len(st["win"]) != 9 or not stalled(st, 8, 4)[0]:
        problems.append("a failing loop does not stall")
    if [s for s, _b, _n in evaluate(st, 10 ** 9, 10, 1000)] != ["stall", "stop"] \
            or evaluate(st, 10 ** 9, 11, 1000):
        problems.append("stall and stop do not fire exactly once")
    _call(st, 10, "Edit", {"file_path": "x"}, error=False)
    _call(st, 11)
    if stalled(st, 8, 4)[0] or [s for s, _b, _n in evaluate(st, 10 ** 9, 12, 1000)] != ["recovered",
                                                                                         "first_write"]:
        problems.append("a successful edit is not progress, or no recovery or first write is logged")
    if st["first_write"] != 11 or new_state()["first_write"] is not None:
        problems.append("the first write is not the 11th API call (B3)")
    for p in problems:
        sys.stderr.write("stack_progress self-test: %s\n" % p)
    print("stack_progress self-test: %s" % ("FAIL" if problems else "ok"))
    return 1 if problems else 0


def main(argv):
    if argv[1:2] == ["--self-test"]:
        return self_test()
    if argv[1:2] == ["report"]:
        import argparse
        ap = argparse.ArgumentParser(prog="stack_progress.py report")
        ap.add_argument("--session")
        ap.add_argument("--json", action="store_true")
        a = ap.parse_args(argv[2:])
        r = report(a.session)
        if a.json:
            print(json.dumps(r, indent=1, sort_keys=True))
            return 0
        print("early stop (STACK_EARLY_STOP=%s): %d session(s) with firings" % (mode(), r["sessions"]))
        for sig, by in sorted(r["signals"].items()):
            print("  %-8s %s" % (sig, ", ".join("%s %d" % kv for kv in sorted(by.items()))))
        for t, by in sorted(r["types"].items()):
            print("  %-22s %s" % (t, ", ".join("%s %d" % kv for kv in sorted(by.items()))))
        for got, s in sorted(r["first_write"].items()):
            print("  first write at API call, %s: n %d, median %s, p90 %s" % (got, s["n"], s["median"], s["p90"]))
        return 0
    sys.stderr.write("usage: stack_progress.py report [--session SID] [--json] | --self-test\n")
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
