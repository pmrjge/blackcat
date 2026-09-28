#!/usr/bin/env python3
"""Behavior enforcement for the Claude Code multi-agent stack (stdlib only, Python 3.8+, POSIX).

Wired in settings.json (every event below) and, in `blackcat-guard` mode, in agents/blackcat.md. The
installer renders every hook command with an absolute interpreter path (never a pyenv/asdf shim):
a hook that cannot start is a non-blocking error in Claude Code, i.e. every gate silently open.
Reads the hook JSON on stdin.

  PreToolUse  Agent                 spawn policy, depth limit, self-copy rule, fan-out caps,
                                    blackcat dispatch window (atomic markers), god-coder singleton
                                    (pending lease), strip `model`
  PreToolUse  SendMessage           resuming a finished agent follows the spawn policy (the caller's
                                    row, or its own child/parent) and its parent's fan-out caps;
                                    resuming a finished god-coder takes the god-coder lock
  PreToolUse  mcp__computer-use__*  one agent on the screen at a time
  PreToolUse  Bash|Monitor|PowerShell  `no-push` mode: agents never push and never write to a
                                    forge (gh/tea/fj), in any form, also inside bash -c, eval, $(...)
                                    (absolute; not switched off by STACK_POLICY=off)
  PreToolUse  local-file MCP tools  context-mode ctx_index, markitdown, docling, playwright: a path
                                    or file: URI argument is held to the Read deny rules (Claude Code
                                    cannot see inside MCP arguments)
  PostToolUse Agent                 record child id/type/depth/parent; confirm or release the
                                    god-coder lock; turn the fan-out lease into a registry entry
  SubagentStart / SubagentStop      registry bookkeeping; confirm / release locks
  PostToolUse TaskStop, StopFailure mark the agent stopped and release its locks (a stopped or
                                    failed subagent is not promised a SubagentStop)
  PostToolUseFailure / PermissionDenied (Agent)   roll back god-coder lease, blackcat marker and
                                    fan-out lease
  UserPromptSubmit                  prune blackcat markers of earlier prompts
  SessionStart (startup|resume)     clear locks and blackcat markers, prune old session dirs

Concurrency model (the user's spec): depth 4 below the main thread (blackcat -> L1 -> L2 -> L3 ->
L4; settings.json sets CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH=4, and the fallback here stays at
Claude Code's own default of 3); any agent whose row allows
it may launch several children in ONE message (they run concurrently in the background); agents
in SELF_SPAWN may launch copies of themselves (one generation: a copy cannot copy itself again);
at most STACK_MAX_FANOUT running children per parent, STACK_MAX_SELF_FANOUT of them copies.

State: ${XDG_STATE_HOME:-~/.local/state}/claude-agent-stack/<session_id>/
  agents/<agent_id>.json  registry {type, depth, parent, parent_type, name, spawned, started,
                          stopped, transcript}
  names/<name>.json       {type, id} for agents spawned with a `name`
  fanout/<caller>/<tool_use_id>.json   pending spawn leases (until PostToolUse)
  blackcat/dispatch.<prompt>.<k>, blackcat/step.<prompt>.<k>   O_EXCL markers
  god-coder.lock, screen.lock  JSON, replaced atomically; transitions under flock(*.mutex)

Failure policy: an exception in a PreToolUse handler (or in blackcat-guard mode) denies the call
(fail closed); lifecycle events log to stderr and exit 0. The escape hatch (STACK_POLICY=off) is
shown to the user in `systemMessage`, never to the model in the deny reason.

Liveness: an agent counts as gone on SubagentStop, PostToolUse(TaskStop) or StopFailure; while it
waits for background children its own transcript is quiet, so idle rules look at the whole live
subtree (the agent's transcript and every live descendant's).

CLI: `agent_guard.py --print-policy` (JSON consumed by doctor.sh and tests/lint_agents.py),
`--self-test`, `blackcat-guard` (PreToolUse hook of the blackcat main thread), `image-limit`
(PreToolUse/PostToolUse hook that keeps images under STACK_IMAGE_MAX_PX), `no-push` (PreToolUse
Bash/Monitor/PowerShell hook that denies any git push or forge write), no argument = event.

Knobs (env):
  STACK_POLICY=off        disable every deny and lock (bookkeeping and model strip continue)
  BLACKCAT_MAX_DISPATCH=3   blackcat Agent calls per user prompt (parallel fan-out of independent asks)
  BLACKCAT_DISPATCH_WINDOW_S=30  all blackcat dispatches for one prompt must start within this many
                          seconds of the first one (one parallel burst, not ad-hoc orchestration)
  BLACKCAT_MAX_STEPS=8      blackcat non-Agent tool calls per user prompt (blackcat-guard mode)
  STACK_MAX_FANOUT=8      running + pending children per parent agent (0 = no cap)
  STACK_MAX_SELF_FANOUT=4 of those, copies of the parent's own type (0 = no cap)
  STACK_FANOUT_IDLE_S=1800  a child whose live subtree shows no activity for this long no longer
                          counts as running (settings.json ships 600)
  STACK_FANOUT_PENDING_TTL_S=120  a spawn lease never confirmed by PostToolUse expires
  GOD_PENDING_TTL_S=120   an unconfirmed god-coder lease (spawn or resume) is reclaimable after this
  GOD_IDLE_S=900          a holder whose live subtree is idle this long is presumed gone
                          (settings.json ships 1800)
  GOD_LOCK_TTL_S=21600    hard ceiling on any god-coder lock
  SCREEN_LOCK_TTL_S=900   screen lock expiry
  STRIP_AGENT_MODEL=1     remove per-call `model` from Agent input
  STACK_MAX_DEPTH         deny Agent from callers at this depth (default
                          CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH, else 3)
  STACK_GUARD_LOG=0       1 = append every raw event to <session>/guard.log
  STACK_IMAGE_MAX_PX=1919 image-limit mode: longest side of any image an agent sees or uploads
                          (0 = off)
  STACK_IMAGE_UPLOAD_TOOLS  image-limit mode: regex of more MCP tool names whose image-file
                          arguments get downscaled copies (the built-in list: UPLOAD_TOOLS)
  STACK_IMAGE_MAX_B64=4500000  image-limit mode: most base64 characters of one image sent to the
                          model (the API refuses more than 5 MB)
"""
import base64
import contextlib
import errno
import fcntl
import json
import os
import re
import shlex
import shutil
import stat
import struct
import subprocess
import sys
import tempfile
import time
from urllib.parse import quote, unquote, urlparse

# ---------------------------------------------------------------- policy (single source of truth)
AGENTS = [
    "blackcat", "orchestrator", "planner", "plan-reviewer", "oracle", "scout", "researcher",
    "mathematician", "image-director", "designer", "motion-designer", "writer",
    "doc-specialist", "coder", "main-coder", "ninja-coder", "god-coder", "mlx-engineer",
    "cuda-engineer",
    "devops-engineer", "data-engineer", "frontend-engineer", "code-reviewer", "verifier",
    "security-auditor", "mcp-broker", "claude-code-guide",
    "ml-engineer", "dl-engineer", "llm-engineer", "data-scientist", "browser-operator",
    "claude-code-engineer", "quantum-engineer", "robotics-engineer", "cg-artist",
]
BUILTINS = ["explore"]
LEAVES = ["oracle", "scout", "code-reviewer", "verifier", "security-auditor", "mcp-broker",
          "claude-code-guide", "browser-operator"]

_BLACKCAT_ROW = [a for a in AGENTS if a != "blackcat"]
_ACCEL_ROW = ["coder", "explore", "scout", "verifier", "code-reviewer", "mathematician",
              "mcp-broker", "ninja-coder", "god-coder"]

# parent agent_type -> child agent types it may spawn. Parents not listed are unrestricted.
# A row that contains the parent itself allows copies of that agent (see SELF_SPAWN).
POLICY = {
    "blackcat": list(_BLACKCAT_ROW),
    "orchestrator": [a for a in _BLACKCAT_ROW if a != "orchestrator"] + ["explore"],
    "planner": ["scout", "explore", "claude-code-guide"],
    "plan-reviewer": ["scout", "explore", "claude-code-guide"],
    "researcher": ["researcher", "scout", "doc-specialist", "mathematician", "data-engineer",
                   "data-scientist", "browser-operator", "mcp-broker"],
    "writer": ["writer", "scout", "researcher", "mathematician"],
    "mathematician": ["mathematician", "scout", "mcp-broker", "quantum-engineer"],
    "image-director": ["scout"],
    "doc-specialist": ["doc-specialist", "scout", "mcp-broker"],
    "designer": ["image-director", "scout", "mcp-broker", "cg-artist"],
    "motion-designer": ["image-director", "designer", "scout", "mcp-broker", "cg-artist"],
    "coder": ["coder", "explore", "scout"],
    "main-coder": ["main-coder", "coder", "explore", "scout", "verifier", "code-reviewer",
                   "security-auditor", "plan-reviewer", "mlx-engineer", "cuda-engineer",
                   "ml-engineer", "dl-engineer", "llm-engineer", "mcp-broker", "claude-code-guide",
                   "ninja-coder", "god-coder"],
    "ninja-coder": ["ninja-coder", "main-coder", "coder", "mathematician", "explore", "scout",
                    "verifier", "code-reviewer", "security-auditor", "researcher", "mlx-engineer",
                    "cuda-engineer", "ml-engineer", "dl-engineer", "llm-engineer", "mcp-broker",
                    "god-coder", "quantum-engineer"],
    "god-coder": ["coder", "main-coder", "ninja-coder", "mlx-engineer", "cuda-engineer",
                  "ml-engineer", "dl-engineer", "llm-engineer", "explore", "scout", "verifier",
                  "code-reviewer", "security-auditor", "mathematician", "researcher"],
    "mlx-engineer": list(_ACCEL_ROW),
    "cuda-engineer": list(_ACCEL_ROW),
    "devops-engineer": ["coder", "explore", "scout", "verifier", "security-auditor", "mcp-broker"],
    "data-engineer": ["data-engineer", "coder", "explore", "scout", "verifier", "mathematician",
                      "data-scientist", "doc-specialist", "mcp-broker"],
    "frontend-engineer": ["coder", "explore", "scout", "verifier", "code-reviewer", "designer",
                          "image-director", "mcp-broker"],
    "ml-engineer": ["ml-engineer", "data-scientist", "data-engineer", "coder", "explore", "scout",
                    "verifier", "code-reviewer", "mathematician", "mcp-broker"],
    "dl-engineer": ["dl-engineer", "mlx-engineer", "cuda-engineer", "data-engineer", "coder",
                    "explore", "scout", "researcher", "verifier", "code-reviewer",
                    "mathematician", "mcp-broker", "ninja-coder", "god-coder"],
    "llm-engineer": ["llm-engineer", "mlx-engineer", "cuda-engineer", "dl-engineer",
                     "data-scientist", "coder", "explore", "scout", "researcher", "verifier",
                     "code-reviewer", "mathematician", "mcp-broker", "claude-code-guide",
                     "ninja-coder", "god-coder"],
    "data-scientist": ["data-scientist", "data-engineer", "ml-engineer", "mathematician", "coder",
                       "explore", "scout", "verifier", "doc-specialist", "writer", "mcp-broker"],
    "claude-code-engineer": ["claude-code-guide", "scout", "explore", "verifier", "code-reviewer",
                             "mcp-broker"],
    # quantum computing and quantum-physics numerics; derivations stay with mathematician
    "quantum-engineer": ["quantum-engineer", "mathematician", "coder", "explore", "scout",
                         "researcher", "verifier", "code-reviewer", "cuda-engineer", "mlx-engineer",
                         "mcp-broker", "ninja-coder"],
    "robotics-engineer": ["robotics-engineer", "coder", "explore", "scout", "researcher",
                          "verifier", "code-reviewer", "mathematician", "dl-engineer",
                          "cuda-engineer", "mlx-engineer", "cg-artist", "mcp-broker",
                          "ninja-coder"],
    # a GUI agent (ZBrush, Substance, Houdini through computer use): no copies, one screen
    "cg-artist": ["image-director", "coder", "scout", "verifier", "mcp-broker"],
    "oracle": [], "scout": [], "code-reviewer": [], "verifier": [], "security-auditor": [],
    "mcp-broker": [], "claude-code-guide": [], "browser-operator": [],
}
# Agents allowed to spawn copies of themselves (derived: the row lists the parent itself).
SELF_SPAWN = sorted(p for p, row in POLICY.items() if p in row)

# Main-thread blackcat: delegation tools plus the main-thread-only features subagents never get
# (dynamic workflows, scheduled tasks, routines, push notifications, file hand-off, skills).
# ExitPlanMode: the main thread leaves plan mode with it (Desktop/Conductor/CLI plan mode).
# mcp__conductor__AskUserQuestion: Conductor disables AskUserQuestion and serves its own.
BLACKCAT_TOOLS = {"Agent", "SendMessage", "AskUserQuestion", "mcp__conductor__AskUserQuestion",
                "ExitPlanMode", "TaskStop", "ListAgents", "ToolSearch", "Skill", "Workflow",
                "CronCreate", "CronDelete", "CronList", "ScheduleWakeup", "RemoteTrigger",
                "PushNotification", "SendUserFile"}
GOD = "god-coder"
GOD_LOCK = "god-coder.lock"
SCREEN_LOCK = "screen.lock"
TERMINAL_STATUSES = {"completed", "failed", "error", "cancelled", "canceled", "killed"}
# Shown to the USER (systemMessage) when the guard itself fails; the model only sees a neutral
# reason, so it is never nudged towards switching the policy off.
BYPASS_HINT = ("claude-agent-stack guard error (see above). If it persists: python3 "
               "~/.claude/hooks/agent_guard.py --self-test, or set \"STACK_POLICY\": \"off\" in the "
               "env block of ~/.claude/settings.json to bypass the stack policy.")


# ---------------------------------------------------------------- small helpers
class MutexTimeout(Exception):
    pass


_KNOWN_TYPES = None


def norm(name):
    """Canonical agent type/name. Claude Code resolves subagent_type case- and separator-
    insensitively ('Code Reviewer', 'CodeReviewer' -> code-reviewer), so map every spelling of a
    known type onto its canonical name; anything else keeps the old normalization."""
    global _KNOWN_TYPES
    if _KNOWN_TYPES is None:
        _KNOWN_TYPES = {re.sub(r"[^a-z0-9]", "", a): a
                        for a in AGENTS + BUILTINS + ["general-purpose", "fork", "plan", "claude",
                                                      "statusline-setup"]}
    s = str(name or "").strip().lower()
    return _KNOWN_TYPES.get(re.sub(r"[^a-z0-9]", "", s)) or re.sub(r"[\s_]+", "-", s)


def ident(value):
    """Agent id as used for registry keys and lock holders. The docs show both 'agent-abc123'
    (SubagentStart example) and bare ids (tool_response.agentId, SubagentStop 'def456' with
    transcript agent-def456.jsonl); strip the prefix everywhere so the joins cannot diverge."""
    s = str(value or "")
    return s[len("agent-"):] if s.startswith("agent-") else s


def safe(value, default="none"):
    """Filesystem-safe token (no dots, so marker names split cleanly)."""
    s = re.sub(r"[^A-Za-z0-9_-]", "_", str(value or ""))[:128]
    return s or default


def knob_int(name, default):
    try:
        return int(os.environ.get(name, "").strip())
    except ValueError:
        return default


def policy_on():
    return os.environ.get("STACK_POLICY", "on").strip().lower() != "off"


def max_depth():
    fallback = knob_int("CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH", 3)
    return knob_int("STACK_MAX_DEPTH", fallback)


def state_root():
    base = os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state")
    return os.path.join(base, "claude-agent-stack")


def sdir(session_id):
    d = os.path.join(state_root(), safe(session_id, "nosession"))
    os.makedirs(d, exist_ok=True)
    return d


def warn(msg):
    sys.stderr.write("agent_guard: %s\n" % msg)


def emit(obj):
    sys.stdout.write(json.dumps(obj))
    sys.stdout.flush()
    sys.exit(0)


def deny(reason, user_message=None):
    out = {"hookSpecificOutput": {"hookEventName": "PreToolUse",
                                  "permissionDecision": "deny",
                                  "permissionDecisionReason": reason}}
    if user_message:
        out["systemMessage"] = user_message
    emit(out)


def guard_error(what):
    """Fail closed on an internal error: neutral reason for the model, escape hatch for the user."""
    deny("stack guard error: %s. Report STATUS: blocked with this message; do not retry." % what,
         "%s (%s)" % (BYPASS_HINT, what))


@contextlib.contextmanager
def mutex(d, name, timeout=5.0):
    """Exclusive flock on <d>/<name>.mutex, polled non-blocking up to `timeout` seconds."""
    fd = os.open(os.path.join(d, name + ".mutex"), os.O_RDWR | os.O_CREAT, 0o600)
    try:
        deadline = time.monotonic() + timeout
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError as exc:
                if exc.errno not in (errno.EAGAIN, errno.EACCES, errno.EWOULDBLOCK):
                    raise
                if time.monotonic() >= deadline:
                    raise MutexTimeout("timed out waiting for %s.mutex" % name)
                time.sleep(0.005)
        try:
            yield
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)


def create_excl(path):
    """Atomically create `path`; False if it already exists."""
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        return False
    os.write(fd, str(time.time()).encode())
    os.close(fd)
    return True


def write_json_atomic(path, obj):
    folder = os.path.dirname(path)
    os.makedirs(folder, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".tmp-", dir=folder)
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(obj, f)
        os.replace(tmp, path)
    except BaseException:
        unlink(tmp)
        raise


def read_json(path):
    try:
        with open(path) as f:
            obj = json.load(f)
    except (OSError, ValueError):
        return None
    return obj if isinstance(obj, dict) else None


def unlink(path):
    try:
        os.unlink(path)
    except FileNotFoundError:
        pass


def log(d, ev):
    if os.environ.get("STACK_GUARD_LOG", "0") == "1":
        with open(os.path.join(d, "guard.log"), "a") as f:
            f.write(json.dumps(ev) + "\n")


def tool_input(ev):
    ti = ev.get("tool_input")
    if ti is None:
        return {}
    if not isinstance(ti, dict):
        raise ValueError("tool_input is not a JSON object")
    return ti


def prompt_key(ev):
    return safe(ev.get("prompt_id"), "noprompt")


# ---------------------------------------------------------------- registry
def reg_path(d, aid):
    return os.path.join(d, "agents", safe(aid) + ".json")


def reg_get(d, aid):
    return read_json(reg_path(d, aid)) if aid else None


def reg_put(d, aid, fields, clear=()):
    """Drop `clear` keys, then merge `fields`; None values only fill absent keys."""
    with mutex(d, "registry"):
        cur = reg_get(d, aid) or {}
        for k in clear:
            cur.pop(k, None)
        for k, v in fields.items():
            if v is not None or k not in cur:
                cur[k] = v
        write_json_atomic(reg_path(d, aid), cur)


def names_path(d, name):
    return os.path.join(d, "names", safe(norm(name)) + ".json")


def caller_depth(d, ev):
    aid = ev.get("agent_id")
    if not aid:
        return 0  # main thread
    dep = (reg_get(d, aid) or {}).get("depth")
    return dep if isinstance(dep, int) and not isinstance(dep, bool) else None


def resolve_target(d, to):
    """SendMessage/TaskStop target -> (agent_id or None, type, name) via registry, then names/."""
    rec = reg_get(d, ident(to))
    if rec:
        return ident(to), norm(rec.get("type")), norm(rec.get("name")) or None
    nrec = read_json(names_path(d, to))
    if nrec:
        return (ident(nrec["id"]) if nrec.get("id") else None), norm(nrec.get("type")), norm(to)
    return None, None, None


# ---------------------------------------------------------------- blackcat markers
def marker(d, kind, pid, k):
    return os.path.join(d, "blackcat", "%s.%s.%d" % (kind, pid, k))


def markers_full(d, kind, pid, limit):
    return all(os.path.exists(marker(d, kind, pid, k)) for k in range(limit))


def claim_marker(d, kind, pid, limit):
    os.makedirs(os.path.join(d, "blackcat"), exist_ok=True)
    for k in range(limit):
        path = marker(d, kind, pid, k)
        if create_excl(path):
            return path
    return None


def drop_highest_marker(d, kind, pid, limit):
    for k in reversed(range(limit)):
        path = marker(d, kind, pid, k)
        if os.path.exists(path):
            unlink(path)
            return


def first_marker_ts(d, kind, pid, limit, now):
    """Creation time of the oldest marker of this prompt (None if there is none). A marker that
    was just created and not yet written counts as created now."""
    found = []
    for k in range(limit):
        try:
            with open(marker(d, kind, pid, k)) as f:
                raw = f.read().strip()
        except OSError:
            continue
        try:
            found.append(float(raw) if raw else now)
        except ValueError:
            found.append(now)
    return min(found) if found else None


def dispatch_window_closed(d, pid, limit, now):
    """True once blackcat's first dispatch for this prompt is older than the window: every
    dispatch for one prompt must go out as one parallel burst."""
    window = knob_int("BLACKCAT_DISPATCH_WINDOW_S", 30)
    first = first_marker_ts(d, "dispatch", pid, limit, now)
    return window > 0 and first is not None and now - first > window


# ---------------------------------------------------------------- fan-out caps and copies
def fanout_dir(d, caller):
    return os.path.join(d, "fanout", safe(caller))


def load_registry(d):
    """{agent_id: record} for every registry entry (one directory scan)."""
    folder = os.path.join(d, "agents")
    out = {}
    try:
        entries = os.listdir(folder)
    except FileNotFoundError:
        return out
    for f in entries:
        if f.endswith(".json"):
            rec = read_json(os.path.join(folder, f))
            if rec is not None:
                out[rec.get("id") or f[:-5]] = rec
    return out


def own_activity(d, aid, rec, ev):
    """(latest activity timestamp, whether a transcript file backed it)."""
    last = 0.0
    for key in ("spawned", "started"):
        try:
            last = max(last, float(rec.get(key) or 0))
        except (TypeError, ValueError):
            pass
    tr = transcript_of(d, aid, ev)
    if tr:
        try:
            return max(last, os.path.getmtime(tr)), True
        except OSError:
            pass
    return last, False


def subtree_activity(d, root, ev, reg=None, root_times=True):
    """(latest activity of `root` and its live (not stopped) descendants, any transcript seen).
    A parent that waits for background children writes nothing to its own transcript, so its own
    mtime alone is not a liveness signal. root_times=False ignores the root's registry timestamps
    (god_stale already folds in the lock's own ts)."""
    reg = load_registry(d) if reg is None else reg
    kids = {}
    for aid, rec in reg.items():
        if not rec.get("stopped"):
            kids.setdefault(rec.get("parent"), []).append(aid)
    root_rec = reg.get(root) or {}
    if not root_times:
        root_rec = {k: v for k, v in root_rec.items() if k not in ("spawned", "started")}
    best, seen_tr = own_activity(d, root, root_rec, ev)
    seen, frontier = {root}, [root]
    while frontier:
        nxt = []
        for node in frontier:
            for aid in kids.get(node, []):
                if aid not in seen:
                    seen.add(aid)
                    t, has_tr = own_activity(d, aid, reg[aid], ev)
                    best, seen_tr = max(best, t), seen_tr or has_tr
                    nxt.append(aid)
        frontier = nxt
    return best, seen_tr


def children_running(d, caller, now, ev):
    """{type: count} of registry children of `caller` that have not stopped and whose subtree
    still shows activity within STACK_FANOUT_IDLE_S."""
    idle = knob_int("STACK_FANOUT_IDLE_S", 1800)
    reg = load_registry(d)
    out = {}
    for aid, rec in reg.items():
        if rec.get("parent") != caller or rec.get("stopped"):
            continue
        last, _ = subtree_activity(d, aid, ev, reg)
        if idle > 0 and last and now - last > idle:
            continue
        t = norm(rec.get("type")) or "?"
        out[t] = out.get(t, 0) + 1
    return out


def fanout_pending(d, caller, now):
    """{type: count} of unexpired spawn leases of `caller`; expired ones are removed."""
    ttl = knob_int("STACK_FANOUT_PENDING_TTL_S", 120)
    folder = fanout_dir(d, caller)
    out = {}
    try:
        entries = os.listdir(folder)
    except FileNotFoundError:
        return out
    for f in entries:
        path = os.path.join(folder, f)
        if f.startswith("."):
            continue
        rec = read_json(path)
        try:
            ts = float((rec or {}).get("ts") or 0)
        except (TypeError, ValueError):
            ts = 0.0
        if not rec or now - ts > ttl:
            unlink(path)
            continue
        t = norm(rec.get("type")) or "?"
        out[t] = out.get(t, 0) + 1
    return out


def fanout_acquire(d, ev, caller, parent_type, child):
    """Check the fan-out caps and, if they allow it, take a lease for this spawn, atomically.
    Returns a denial reason, or None when the spawn may proceed."""
    max_all = knob_int("STACK_MAX_FANOUT", 8)
    max_self = knob_int("STACK_MAX_SELF_FANOUT", 4)
    tid = ev.get("tool_use_id")
    with mutex(d, "fanout"):
        now = time.time()
        live = children_running(d, caller, now, ev)
        pend = fanout_pending(d, caller, now)
        total = sum(live.values()) + sum(pend.values())
        copies = live.get(child, 0) + pend.get(child, 0)
        who = parent_type or caller
        if max_all > 0 and total >= max_all:
            return ("Fan-out limit: '%s' already has %d children running or starting "
                    "(STACK_MAX_FANOUT=%d). Wait for a task notification before spawning more, "
                    "or do this part yourself." % (who, total, max_all))
        if parent_type and child == parent_type and max_self > 0 and copies >= max_self:
            return ("Copy limit: '%s' already has %d copies of itself running or starting "
                    "(STACK_MAX_SELF_FANOUT=%d). Wait for one to finish, or do this part "
                    "yourself." % (who, copies, max_self))
        if tid:
            write_json_atomic(os.path.join(fanout_dir(d, caller), safe(tid) + ".json"),
                              {"type": child, "ts": now})
    return None


def fanout_release(d, caller, tool_use_id):
    if tool_use_id:
        unlink(os.path.join(fanout_dir(d, caller), safe(tool_use_id) + ".json"))


def copy_rule_violation(d, ev, parent_type, child):
    """One generation of copies: a copy (an agent spawned by its own type) cannot copy itself."""
    aid = ev.get("agent_id")
    if not aid or not parent_type or child != parent_type:
        return None
    rec = reg_get(d, aid) or {}
    if norm(rec.get("parent_type")) == parent_type:
        return ("Self-copy rule: this '%s' is already a copy spawned by another '%s', and copies "
                "cannot spawn further copies. Split the work across other agent types, do it "
                "yourself, or return STATUS: partial." % (parent_type, parent_type))
    return None


# ---------------------------------------------------------------- god-coder lock
def god_path(d):
    return os.path.join(d, GOD_LOCK)


def transcript_of(d, holder, ev):
    rec = reg_get(d, holder) or {}
    if rec.get("transcript"):
        return os.path.expanduser(rec["transcript"])
    tp, sid = ev.get("transcript_path"), ev.get("session_id")
    if not tp:
        return None
    # Derived locations are unverified; used only when they exist.
    base = os.path.dirname(os.path.expanduser(tp))
    names = ["agent-%s.jsonl" % holder, "agent-agent-%s.jsonl" % holder]  # ident() stripped it?
    cands = [os.path.join(base, n) for n in names]
    if sid:
        cands[:0] = [os.path.join(base, str(sid), "subagents", n) for n in names]
    for c in cands:
        if os.path.isfile(c):
            return c
    return None


def god_stale(d, lock, ev, now):
    """Reason string if the lock may be reclaimed, else None. Caller holds god.mutex."""
    ts = float(lock.get("ts") or 0)
    if now - ts > knob_int("GOD_LOCK_TTL_S", 21600):
        return "lock older than GOD_LOCK_TTL_S"
    state, holder = lock.get("state"), lock.get("holder")
    # 'pending' (Agent call) and 'resumed' (SendMessage) are unconfirmed until SubagentStart turns
    # them into 'running'; a resume that is refused or never starts must not hold the lock.
    if state in ("pending", "resumed") and now - ts > knob_int("GOD_PENDING_TTL_S", 120):
        return "unconfirmed %s lease expired" % state
    if holder and not str(holder).startswith("name:"):
        stopped = (reg_get(d, holder) or {}).get("stopped")
        if isinstance(stopped, (int, float)) and stopped >= ts:
            return "holder stopped"
        # Liveness = the holder's transcript OR any live descendant's: a god-coder waiting for the
        # coders/reviewers it delegated to writes nothing to its own transcript.
        # Without any transcript to look at, liveness is unknown: keep the lock (TTL still applies).
        last, seen_tr = subtree_activity(d, holder, ev, root_times=False)
        if seen_tr and now - max(last, ts) > knob_int("GOD_IDLE_S", 900):
            return "holder idle"
    return None


def holder_matches(d, lock_holder, agent_id, name=None):
    if not lock_holder:
        return False
    if agent_id and lock_holder == agent_id:
        return True
    if not name and agent_id:
        name = norm((reg_get(d, agent_id) or {}).get("name")) or None
    return bool(name) and lock_holder == "name:" + name


def god_acquire(d, ev, state, holder, by):
    """Take the lock if free or stale. Returns None on success, else the blocking lock."""
    with mutex(d, "god"):
        now = time.time()
        lock = read_json(god_path(d))
        if lock:
            reason = god_stale(d, lock, ev, now)
            if not reason:
                return lock
            warn("reclaiming god-coder lock held by %s (%s)" % (lock.get("holder"), reason))
        write_json_atomic(god_path(d), {"state": state, "holder": holder, "by": by, "ts": now,
                                        "tool_use_id": ev.get("tool_use_id")})
        return None


def god_release_pending(d, by, tool_use_id):
    with mutex(d, "god"):
        lock = read_json(god_path(d))
        if not lock or lock.get("state") != "pending" or lock.get("by") != by:
            return
        if tool_use_id and lock.get("tool_use_id") and lock["tool_use_id"] != tool_use_id:
            return
        unlink(god_path(d))


def god_confirm(d, ev, agent_id):
    """pending -> running with holder=agent_id (best effort if the lock is missing)."""
    with mutex(d, "god"):
        now = time.time()
        # Re-check under the god mutex: SubagentStop writes `stopped` before it takes this mutex
        # to release, so a stop that raced the caller's check is always seen here.
        if (reg_get(d, agent_id) or {}).get("stopped"):
            return
        lock = read_json(god_path(d))
        if lock is None:
            warn("god-coder %s started without a lock; recording it as running" % agent_id)
            by = "?"
        elif holder_matches(d, lock.get("holder"), agent_id):
            by = lock.get("by")
        elif not lock.get("holder") and lock.get("state") == "pending":
            by = lock.get("by")
        elif god_stale(d, lock, ev, now):
            by = "?"
        else:
            warn("two live god-coder holders: %s and %s" % (lock.get("holder"), agent_id))
            return
        write_json_atomic(god_path(d), {"state": "running", "holder": agent_id, "by": by,
                                        "ts": now})


def god_release_holder(d, agent_id, agent_type, by=None):
    """Release if agent_id holds the lock, or if an unconfirmed pending lease was taken by `by`
    (PostToolUse 'completed' from the caller that spawned it). A SubagentStop (by=None) never
    releases someone else's unconfirmed lease: it cannot tell whose spawn that lease is for."""
    with mutex(d, "god"):
        lock = read_json(god_path(d))
        if not lock:
            return
        unconfirmed = not lock.get("holder") and lock.get("state") == "pending"
        if holder_matches(d, lock.get("holder"), agent_id) or (
                unconfirmed and norm(agent_type) == GOD and by is not None
                and lock.get("by") == by):
            unlink(god_path(d))


def god_busy_reason(lock):
    return ("A god-coder is already %s in this session (holder: %s). Only one at a time per "
            "session, and resuming a finished god-coder counts. SendMessage the holder, or wait "
            "for it to finish." % (lock.get("state") or "active", lock.get("holder") or "starting"))


# ---------------------------------------------------------------- PreToolUse: Agent
def on_agent(ev, d):
    ti = tool_input(ev)
    child = norm(ti.get("subagent_type") or "general-purpose")
    aid = ev.get("agent_id")
    caller = aid or "main"
    parent = norm(ev.get("agent_type"))
    if not parent and aid:
        parent = norm((reg_get(d, aid) or {}).get("type"))
    pid = prompt_key(ev)
    tid = ev.get("tool_use_id")
    max_dispatch = knob_int("BLACKCAT_MAX_DISPATCH", 3)

    if policy_on():
        is_blackcat = not aid and parent == "blackcat"
        # 1. pure checks
        if str(ti.get("isolation") or "").strip().lower() == "remote":
            deny("Remote isolation runs the agent in a cloud session that does not load this "
                 "stack's hooks (no spawn policy, depth, fan-out, god-coder or screen locks). Omit "
                 "isolation or use isolation: \"worktree\".")
        if parent in POLICY and child not in POLICY[parent]:
            deny("Spawn policy: '%s' may not spawn '%s'. Allowed: %s. Return STATUS: partial "
                 "with NEXT naming the agent you need."
                 % (parent, child, ", ".join(POLICY[parent]) or "none"))
        depth, limit = caller_depth(d, ev), max_depth()
        if depth is not None and depth >= limit:
            deny("Depth limit: '%s' runs at depth %d and agents at depth >= %d cannot spawn. "
                 "Do the work yourself or return STATUS: partial with NEXT naming the agent."
                 % (parent or caller, depth, limit))
        why = copy_rule_violation(d, ev, parent, child)
        if why:
            deny(why)
        if is_blackcat:
            if markers_full(d, "dispatch", pid, max_dispatch):
                deny("BlackCat dispatch limit (%d per prompt) reached. Use SendMessage to resume an "
                     "agent, or tell the user what is missing; work that needs coordination goes "
                     "to ONE orchestrator call." % max_dispatch)
            if dispatch_window_closed(d, pid, max_dispatch, time.time()):
                deny("BlackCat already dispatched for this prompt: parallel dispatches must go out "
                     "together in one message. Relay the results as they arrive; follow-ups go "
                     "through SendMessage, and multi-step work goes to the orchestrator.")
        # 2. side effects, each rolled back if a later step denies or fails
        leased, took_god, claimed = False, False, None

        def rollback():
            if claimed:
                unlink(claimed)
            if took_god:
                god_release_pending(d, caller, tid)
            if leased:
                fanout_release(d, caller, tid)

        try:
            why = fanout_acquire(d, ev, caller, parent, child)
            if why:
                deny(why)
            leased = True
            if child == GOD:
                blocking = god_acquire(d, ev, "pending", None, caller)
                if blocking:
                    rollback()
                    deny(god_busy_reason(blocking))
                took_god = True
            if is_blackcat:
                claimed = claim_marker(d, "dispatch", pid, max_dispatch)
                if not claimed:
                    rollback()
                    deny("BlackCat dispatch limit (%d per prompt) reached. Use SendMessage to "
                         "resume that agent." % max_dispatch)
            record_name(d, ti, child, caller)
        except SystemExit:
            raise
        except Exception:
            rollback()
            raise
    else:
        record_name(d, ti, child, caller)

    # 3. models are fixed by agent definitions
    if os.environ.get("STRIP_AGENT_MODEL", "1") == "1" and "model" in ti:
        new_input = {k: v for k, v in ti.items() if k != "model"}
        emit({"hookSpecificOutput": {"hookEventName": "PreToolUse",
                                     "permissionDecision": "allow",
                                     "permissionDecisionReason":
                                         "model override removed; agent definition decides",
                                     "updatedInput": new_input}})


def record_name(d, ti, child, caller):
    name = ti.get("name")
    if isinstance(name, str) and name.strip():
        write_json_atomic(names_path(d, name),
                          {"type": child, "id": None, "by": caller, "ts": time.time()})


# ---------------------------------------------------------------- PreToolUse: SendMessage
def send_policy_violation(d, ev, target_id, ttype):
    """Resuming a FINISHED agent starts new work in it, like a spawn: allowed when the caller's
    POLICY row lists the target's type, or the target is the caller's own child (follow-ups) or
    its own parent. A message to a running agent is coordination, not a spawn, and passes; so do
    the main thread (blackcat's row lists every agent) and targets the registry doesn't know."""
    aid = ev.get("agent_id")
    if not aid or not target_id or not ttype:
        return None
    caller_type = norm(ev.get("agent_type")) or norm((reg_get(d, aid) or {}).get("type"))
    row = POLICY.get(caller_type)
    if row is None or ttype in row:
        return None
    rec = reg_get(d, target_id) or {}
    if not rec.get("stopped") or rec.get("parent") == aid \
            or (reg_get(d, aid) or {}).get("parent") == target_id:
        return None
    return ("SendMessage policy: '%s' may not resume '%s', a finished %s (it may resume or spawn: "
            "%s). Return STATUS: partial with NEXT naming that agent, so your parent can resume it."
            % (caller_type, target_id, ttype, ", ".join(row) or "none"))


def resume_cap_violation(d, ev, target_id, ttype):
    """A resumed agent runs again under its registry parent, so it counts against that parent's
    fan-out caps like a new spawn. (No lease: the resume's SubagentStart makes it count as
    running.)"""
    rec = reg_get(d, target_id) if target_id else None
    if not rec or not rec.get("stopped"):
        return None
    owner = rec.get("parent") or ev.get("agent_id") or "main"
    owner_type = norm(rec.get("parent_type")) or None
    max_all = knob_int("STACK_MAX_FANOUT", 8)
    max_self = knob_int("STACK_MAX_SELF_FANOUT", 4)
    with mutex(d, "fanout"):
        now = time.time()
        live = children_running(d, owner, now, ev)
        pend = fanout_pending(d, owner, now)
    who = owner_type or owner
    if max_all > 0 and sum(live.values()) + sum(pend.values()) >= max_all:
        return ("Fan-out limit: resuming '%s' would give '%s' more than %d running children "
                "(STACK_MAX_FANOUT). Wait for a task notification, then resume it."
                % (target_id, who, max_all))
    if owner_type and ttype == owner_type and max_self > 0 \
            and live.get(ttype, 0) + pend.get(ttype, 0) >= max_self:
        return ("Copy limit: resuming '%s' would give '%s' more than %d running copies of itself "
                "(STACK_MAX_SELF_FANOUT). Wait for one to finish." % (target_id, who, max_self))
    return None


def on_send(ev, d):
    if not policy_on():
        return
    ti = tool_input(ev)
    to = None
    for key in ("to", "recipient", "agentId", "agent_id", "name"):
        if isinstance(ti.get(key), str) and ti[key].strip():
            to = ti[key].strip()
            break
    if not to:
        return
    target_id, ttype, tname = resolve_target(d, to)
    why = (send_policy_violation(d, ev, target_id, ttype)
           or resume_cap_violation(d, ev, target_id, ttype))
    if why:
        deny(why)
    if ttype != GOD:
        return
    holder = target_id or "name:" + norm(to)
    caller = ev.get("agent_id") or "main"
    with mutex(d, "god"):
        now = time.time()
        lock = read_json(god_path(d))
        if lock and (lock.get("holder") == holder
                     or holder_matches(d, lock.get("holder"), target_id, tname)):
            return  # talking to the current holder
        if lock and not god_stale(d, lock, ev, now):
            blocking = lock
        else:
            blocking = None
            write_json_atomic(god_path(d), {"state": "resumed", "holder": holder, "by": caller,
                                            "ts": now})
    if blocking:
        deny(god_busy_reason(blocking))


# ---------------------------------------------------------------- PreToolUse: computer use
def on_screen(ev, d):
    if not policy_on():
        return
    holder = ev.get("agent_id") or "main"
    who = ev.get("agent_type") or holder
    path = os.path.join(d, SCREEN_LOCK)
    with mutex(d, "screen"):
        now = time.time()
        cur = read_json(path)
        busy = (cur and cur.get("holder") != holder
                and now - float(cur.get("ts") or 0) < knob_int("SCREEN_LOCK_TTL_S", 900))
        if not busy:
            write_json_atomic(path, {"holder": holder, "who": who, "ts": now})
    if busy:
        deny("Screen busy: '%s' is using computer use. Return STATUS: blocked, NEXT: retry "
             "after %s finishes." % (cur.get("who"), cur.get("who")))


# ---------------------------------------------------------------- local-file MCP tools
# MCP tools that read local files by path or file: URI. Claude Code applies its Read deny rules to
# its own tools, not to MCP arguments, and context-mode's own check misreads `//abs` and `~/` rules
# — so stack.env, ~/.ssh and ~/.aws would be one pre-approved call away.
# (tool-name regex, arguments the tool reads as a local path, prefixes it treats as a URL instead).
# A file: URI counts in any argument; markitdown takes only URIs (file:, data:, http(s):).
LOCAL_READ_TOOLS = [
    (re.compile(r"mcp__context-mode__ctx_index\Z"), ("path",), ()),
    (re.compile(r"mcp__markitdown__"), (), ()),
    (re.compile(r"mcp__magg__docling_"), ("source", "sources", "path", "file_path"), ("http://", "https://")),
    (re.compile(r"mcp__(?:playwright__|magg__pw_)"), ("paths",), ()),   # browser_file_upload
    # chrome-devtools-mcp mounted by mcp-broker: upload_file, traces, heap snapshots, screenshots
    (re.compile(r"mcp__magg__cdt_"), ("filePaths", "filePath", "baseFilePath", "currentFilePath",
                                     "requestFilePath", "responseFilePath"), ()),
]
DIRS_REFUSED = re.compile(r"mcp__context-mode__ctx_index\Z")   # walks a directory it is given
# Bounds that keep the check well inside the hook's 15 s timeout (a timed-out hook doesn't block):
# more than this is refused, not matched. No real path is longer than 4096 bytes.
MAX_PATH_ARG, MAX_PATH_ARGS, MAX_PATH_TOTAL = 4096, 64, 16384


def local_read_keys(tool):
    """(path argument names, URL prefixes) for a local-file tool, else None."""
    for rx, keys, urls in LOCAL_READ_TOOLS:
        if rx.match(tool):
            return keys, urls
    return None


def path_bases(ev):
    """Directories a relative path may be resolved against: the tool resolves against its own
    start directory (the project), the session may have moved since (ev.cwd)."""
    out = []
    for b in (os.environ.get("CLAUDE_PROJECT_DIR"), ev.get("cwd"), os.getcwd()):
        if b and os.path.isabs(b) and b not in out:
            out.append(b)
    return out


def read_deny_specs(bases):
    """(spec, anchors for `/x`) for every Read(...) deny rule: the user settings next to this hook
    (`/x` = <config dir>/x) and each project's .claude/settings{,.local}.json (`/x` = <project>/x;
    <project>/.claude/x too, to be safe)."""
    conf = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    files = [(os.path.join(conf, "settings.json"), (conf,))]
    for b in bases:
        for name in ("settings.json", "settings.local.json"):
            files.append((os.path.join(b, ".claude", name), (b, os.path.join(b, ".claude"))))
    specs, seen = [], set()
    for path, anchors in files:
        if path in seen:
            continue
        seen.add(path)
        rules = ((read_json(path) or {}).get("permissions") or {}).get("deny")
        for rule in rules if isinstance(rules, list) else []:
            if not isinstance(rule, str):
                continue
            if rule.strip() == "Read":                       # Read denied outright: every path
                specs.append(("//**", anchors))
                continue
            m = re.match(r"\s*Read\((.+)\)\s*\Z", rule)
            if m and not m.group(1).strip().startswith("!"):   # carve-outs only narrow a deny: ignored
                specs.append((m.group(1).strip(), anchors))
    return specs


def glob_regex(pat):
    """gitignore glob -> regex: `**/` any directories, `*` `?` within one segment, `[...]` classes."""
    out, i, n = "", 0, len(pat)
    while i < n:
        c = pat[i]
        if pat.startswith("**/", i):
            out, i = out + "(?:.*/)?", i + 3
        elif pat.startswith("**", i):
            out, i = out + ".*", i + 2
        elif c == "*":
            out, i = out + "[^/]*", i + 1
        elif c == "?":
            out, i = out + "[^/]", i + 1
        elif c == "[":
            j = i + 1 + (pat[i + 1:i + 2] in ("!", "^"))
            j += pat[j:j + 1] == "]"                 # a "]" right after the opening is literal
            j = pat.find("]", j)
            if j < 0:                                # no closing bracket: a literal "["
                out, i = out + re.escape(c), i + 1
                continue
            body = pat[i + 1:j]
            neg = body[:1] in ("!", "^")
            body = body[1:] if neg else body
            body = body.replace("\\", "\\\\").replace("[", "\\[")
            out, i = out + ("[^/%s]" % body if neg else "[%s]" % body), j + 1
        else:
            out, i = out + re.escape(c), i + 1
    return out


def deny_patterns(spec, anchors):
    """Claude Code's rule paths: //x absolute, ~/x under home, /x at the settings source's anchor;
    anything else relative to the working directory, matched here at any depth (stricter).
    Yields (regex that also matches everything below the path, literal prefix or None)."""
    if spec.startswith("//"):
        pats = [spec[1:]]
    elif spec.startswith("~/"):
        pats = [os.path.expanduser("~") + spec[1:]]
    elif spec.startswith("/"):
        pats = [a.rstrip("/") + spec for a in anchors]
    else:
        pats = ["**/" + (spec[2:] if spec.startswith("./") else spec)]
    # a symlinked anchor (~/.claude or ~/.ssh kept in a dotfiles or vault folder) also guards its target
    for pat in list(pats):
        head = re.split(r"[*?\[]", pat, maxsplit=1)[0]
        head = head[:head.rfind("/") + 1] if pat.startswith("/") else ""
        real = os.path.realpath(head) if len(head) > 1 else head
        if real and real.rstrip("/") != head.rstrip("/"):
            pats.append(real.rstrip("/") + "/" + pat[len(head):])
        if pat.startswith("/") and not re.search(r"[*?\[]", pat) and os.path.realpath(pat) != pat:
            pats.append(os.path.realpath(pat))                  # a symlinked file: its target too
    flags = re.IGNORECASE if sys.platform == "darwin" else 0   # APFS is case-insensitive
    for pat in pats:
        pat = re.sub(r"/{2,}", "/", pat).rstrip("/") or "/"     # `dir/` and `a//b` mean the plain path
        literal = re.split(r"[*?\[]", pat, maxsplit=1)[0] if pat.startswith("/") else None
        yield re.compile(glob_regex(pat) + r"(?:/.*)?\Z", flags), literal


def local_paths(ev, keys, urls=()):
    """Every absolute path an argument could name, read every way the tool might read it: as a
    file: URI, and (under a path argument) as a literal path — `x:/../..`, `file:/../..` and
    `http://../..` are relative paths to a tool that doesn't parse URIs — with `~` expanded or not,
    percent-decoded or not, trimmed or not, against each base directory; lexical and
    symlink-resolved. Returns (paths, problem)."""
    raw, found = [], []

    def visit(key, v, depth):
        if depth > 4:
            return
        if isinstance(v, dict):
            for k, x in v.items():
                visit(str(k), x, depth + 1)
        elif isinstance(v, list):
            for x in v:
                visit(key, x, depth + 1)
        elif isinstance(v, str) and (key in keys or v.strip()[:5].lower() == "file:"):
            raw.append((key, v))

    visit("", tool_input(ev), 0)
    if len(raw) > MAX_PATH_ARGS:
        return [], "%d path arguments (the guard checks at most %d)" % (len(raw), MAX_PATH_ARGS)
    if max([len(v) for _, v in raw] + [0]) > MAX_PATH_ARG or sum(len(v) for _, v in raw) > MAX_PATH_TOTAL:
        return [], "path arguments longer than the guard checks (%d characters each, %d in all)" % (
            MAX_PATH_ARG, MAX_PATH_TOTAL)
    bases = path_bases(ev) or [os.getcwd()]
    for key, v in raw:
        forms = set()
        for s in {v, v.strip()}:
            if s[:5].lower() == "file:":
                forms.add(unquote(urlparse(s).path) or "/")
            if key in keys and s and not s.startswith(urls or ("\0",)):
                forms.update({s, unquote(s)})
        for f in list(forms):
            if f.startswith("~"):
                forms.add(os.path.expanduser(f))
        for f in forms:
            for b in ([None] if os.path.isabs(f) else bases):
                p = f if b is None else os.path.join(b, f)
                found.extend({os.path.normpath(p), os.path.realpath(p)})
    return list(dict.fromkeys(found)), None


def on_local_read(ev, d):
    if not policy_on():
        return
    tool = ev.get("tool_name") or ""
    keys, urls = local_read_keys(tool) or ((), ())
    paths, problem = local_paths(ev, keys, urls)
    if problem:
        deny("Refused: %s. Pass the real path of one file." % problem)
    if DIRS_REFUSED.match(tool):
        for p in paths:
            if os.path.isdir(p):
                deny("%s is a directory. Index files one at a time: a directory can hold files the "
                     "Read deny rules protect, which this tool would index without asking." % p)
    fold = (lambda x: x.lower()) if sys.platform == "darwin" else (lambda x: x)
    rules = [(spec, rx, fold(literal) if literal is not None else None)
             for spec, anchors in read_deny_specs(path_bases(ev))
             for rx, literal in deny_patterns(spec, anchors)]
    for p in paths:
        under = fold(p).rstrip("/") + "/" if os.path.isdir(p) else None
        for spec, rx, literal in rules:
            inside = under is not None and literal is not None and literal.startswith(under)
            if inside or rx.match(p):
                deny("%s is off limits: %s the Read deny rule Read(%s). Secrets never enter an "
                     "agent's context; use another source or ask the user."
                     % (p, "it holds files protected by" if inside else "it matches", spec))


# ---------------------------------------------------------------- lifecycle
def agent_response(ev):
    tr = ev.get("tool_response")
    if isinstance(tr, str):
        try:
            tr = json.loads(tr)
        except ValueError:
            m = re.search(r"agent_?[iI]d[\"']?\s*[:=]\s*[\"']?([A-Za-z0-9_-]+)", tr)
            return (m.group(1) if m else None), None
    if isinstance(tr, list):
        tr = next((x for x in tr if isinstance(x, dict) and
                   (x.get("agentId") or x.get("agent_id"))), {})
    if not isinstance(tr, dict):
        return None, None
    return tr.get("agentId") or tr.get("agent_id"), tr.get("status")


def on_agent_done(ev, d):
    ti = ev.get("tool_input") if isinstance(ev.get("tool_input"), dict) else {}
    caller = ev.get("agent_id") or "main"
    child_id, status = agent_response(ev)
    if not child_id:
        fanout_release(d, caller, ev.get("tool_use_id"))
        return
    child_id = ident(child_id)
    child = norm(ti.get("subagent_type") or "general-purpose")
    pdepth = caller_depth(d, ev)
    name = ti.get("name") if isinstance(ti.get("name"), str) and ti["name"].strip() else None
    # Unknown caller depth -> child depth null (clear any stale value first). Registry write and
    # lease drop happen under the 'fanout' mutex, so fanout_acquire() never sees the child twice
    # (lock order fanout -> registry; nothing takes them in the other order).
    with mutex(d, "fanout"):
        reg_put(d, child_id, {"id": child_id, "type": child,
                              "depth": None if pdepth is None else pdepth + 1,
                              "parent": caller, "parent_type": norm(ev.get("agent_type")) or None,
                              "spawned": time.time(), "name": norm(name) if name else None},
                clear=("depth",))
        fanout_release(d, caller, ev.get("tool_use_id"))
    if name:
        write_json_atomic(names_path(d, name), {"type": child, "id": child_id,
                                                "by": ev.get("agent_id") or "main",
                                                "ts": time.time()})
    if child != GOD:
        return
    if str(status or "").lower() in TERMINAL_STATUSES:
        god_release_holder(d, child_id, GOD, by=ev.get("agent_id") or "main")
    elif policy_on() and not (reg_get(d, child_id) or {}).get("stopped"):
        god_confirm(d, ev, child_id)


def on_subagent_start(ev, d):
    aid = ev.get("agent_id")
    if not aid:
        return
    atype = norm(ev.get("agent_type"))
    reg_put(d, aid, {"type": atype or None, "started": time.time()}, clear=("stopped",))
    if atype == GOD and policy_on():
        god_confirm(d, ev, aid)


def mark_stopped(d, aid, atype, transcript=None):
    """Record that `aid` is no longer running and drop the locks it holds. Agents the registry has
    never seen (Claude Code's internal agents: prompt suggestions, /btw) get no new entry."""
    if reg_get(d, aid):
        reg_put(d, aid, {"type": atype or None, "stopped": time.time(),
                         "transcript": transcript or None})
    path = os.path.join(d, SCREEN_LOCK)
    with mutex(d, "screen"):
        cur = read_json(path)
        if cur and cur.get("holder") == aid:
            unlink(path)
    god_release_holder(d, aid, atype)


def on_subagent_stop(ev, d):
    aid = ev.get("agent_id")
    if not aid:
        return
    mark_stopped(d, aid, norm(ev.get("agent_type")), ev.get("agent_transcript_path"))


def on_task_stop(ev, d):
    """PostToolUse TaskStop: a subagent stopped by TaskStop is not guaranteed a SubagentStop."""
    ti = ev.get("tool_input") if isinstance(ev.get("tool_input"), dict) else {}
    tr = ev.get("tool_response") if isinstance(ev.get("tool_response"), dict) else {}
    target = ti.get("task_id") or ti.get("shell_id") or tr.get("task_id")
    if not target:
        return
    aid, atype, _ = resolve_target(d, str(target))
    if aid:
        mark_stopped(d, aid, atype)


def on_stop_failure(ev, d):
    """StopFailure replaces Stop when a turn ends on an API error; inside a subagent it is the
    only end-of-run signal there may be."""
    aid = ev.get("agent_id")
    if aid:
        mark_stopped(d, aid, norm(ev.get("agent_type")))


def on_agent_failed(ev, d):
    ti = ev.get("tool_input") if isinstance(ev.get("tool_input"), dict) else {}
    aid = ev.get("agent_id")
    fanout_release(d, aid or "main", ev.get("tool_use_id"))
    if norm(ti.get("subagent_type")) == GOD:
        god_release_pending(d, aid or "main", ev.get("tool_use_id"))
    if not aid and norm(ev.get("agent_type")) == "blackcat":
        drop_highest_marker(d, "dispatch", prompt_key(ev), knob_int("BLACKCAT_MAX_DISPATCH", 3))


def on_prompt(ev, d):
    folder = os.path.join(d, "blackcat")
    pid = safe(ev.get("prompt_id"), "") or None
    try:
        entries = os.listdir(folder)
    except FileNotFoundError:
        return
    for f in entries:
        parts = f.split(".")
        if pid is None or len(parts) != 3 or parts[1] != pid:
            unlink(os.path.join(folder, f))


def last_activity(path):
    t = os.path.getmtime(path)
    try:
        for f in os.listdir(path):
            t = max(t, os.path.getmtime(os.path.join(path, f)))
    except OSError:
        pass
    return t


def on_session_start(ev, d):
    if ev.get("source") not in ("startup", "resume"):
        return
    with mutex(d, "god"):
        unlink(god_path(d))
    with mutex(d, "screen"):
        unlink(os.path.join(d, SCREEN_LOCK))
    shutil.rmtree(os.path.join(d, "blackcat"), ignore_errors=True)
    shutil.rmtree(os.path.join(d, "fanout"), ignore_errors=True)
    # Subagents never outlive the process that ran them: after a restart or --resume nothing from
    # the registry is running any more (a SendMessage resume fires SubagentStart, which clears
    # this again). Without this, dead children would count against STACK_MAX_FANOUT.
    now = time.time()
    folder = os.path.join(d, "agents")
    try:
        entries = [f for f in os.listdir(folder) if f.endswith(".json")]
    except FileNotFoundError:
        entries = []
    with mutex(d, "registry"):
        for f in entries:
            path = os.path.join(folder, f)
            rec = read_json(path)
            if rec is not None and not rec.get("stopped"):
                rec["stopped"] = now
                write_json_atomic(path, rec)
    root = state_root()
    for s in os.listdir(root):
        p = os.path.join(root, s)
        try:
            if os.path.isdir(p) and p != d and now - last_activity(p) > 3 * 86400:
                shutil.rmtree(p, ignore_errors=True)
        except OSError as exc:
            warn("prune %s: %s" % (p, exc))


# ---------------------------------------------------------------- image-limit mode
# Every image an agent sees, or uploads with a browser or image tool, stays at most IMAGE_MAX_PX on
# its longer side (default 1919: both sides < 1920). Claude Code already scales what it sends the
# model to about 2000 px; this goes below that and also covers files agents upload.
#   PostToolUse Read      an image result above the limit is re-encoded smaller (updatedToolOutput,
#                         same shape: {type: image, file: {base64, type, dimensions, ...}})
#   PostToolUse mcp__*    the same for image blocks in MCP results (browser/computer screenshots)
#   PreToolUse  uploads   for the tools in UPLOAD_TOOLS (browser file uploads) and those matching
#                         STACK_IMAGE_UPLOAD_TOOLS, local image
#                         files above the limit are swapped for downscaled copies (updatedInput; no
#                         permission decision, so the usual rules still apply). A copy sits next to
#                         its original, in a `.downscaled/` folder that git ignores, under the same
#                         name (plus the old extension when the format changes), so the tool's own
#                         path checks (Playwright's workspace, Chrome's shared folders, a server's
#                         secret-path refusals) judge it as they judge the original. A copy is reused
#                         while it carries its original's modification time. Nothing is ever deleted.
#                         Left alone: files the Read deny rules protect (the tools' guards decide)
#                         and relative paths that could mean two files. When no copy can be made
#                         (a symlinked file or folder, a folder that can't be written, an animated
#                         image, no resizer) the call is refused with the command to make one.
# Formats: JPEG stays JPEG, PNG stays PNG, anything else becomes PNG when it may be transparent and
# JPEG otherwise. An image for the model also stays under IMAGE_MAX_B64 characters of base64 (the API
# refuses a tool-result image over 5 MB, and the session then fails): above it, JPEG at falling
# quality, else the image stays as it was. Resizer: macOS sips; elsewhere Pillow or ImageMagick (the
# repo's tests); with none, everything passes unchanged with a warning. This mode never blocks a tool
# call except the one refusal above: any error = no change. Work stops IMAGE_DEADLINE_S into the
# hook's 60 s timeout.
IMAGE_MIME = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".gif": "image/gif",
              ".webp": "image/webp", ".bmp": "image/bmp", ".tif": "image/tiff", ".tiff": "image/tiff",
              ".heic": "image/heic", ".heif": "image/heif", ".avif": "image/avif"}
# (tool-name regex, argument names holding local image files the tool sends off the machine)
UPLOAD_TOOLS = [
    (re.compile(r"mcp__(?:playwright__|magg__pw_)browser_(?:file_upload|drop)\Z"), ("paths",)),
    (re.compile(r"mcp__claude-in-chrome__file_upload\Z"), ("paths",)),
    (re.compile(r"mcp__magg__cdt_upload_file\Z"), ("filePaths",)),
]   # image-studio scales its own input images in memory (STACK_IMAGE_MAX_PX)
# argument names checked in tools added with STACK_IMAGE_UPLOAD_TOOLS (a regex of full tool names)
UPLOAD_KEYS = re.compile(
    r"(?:paths?|files?|file_?paths?|images?|image_?(?:paths?|files?|file_?paths?|urls?|uris?)|"
    r"(?:init|control|mask|input|source|reference|first_?frame|last_?frame)_?images?|masks?)\Z", re.I)
IMAGE_MAX_B64 = 4500000        # characters; the API's limit for one image is 5 MB of base64
IMAGE_DEADLINE_S = 40
COPY_DIR = ".downscaled"
MAX_IMAGE_FILE = 200 * 1024 * 1024
_WARNED = set()


def warn_once(msg):
    if msg not in _WARNED:
        _WARNED.add(msg)
        warn(msg)


def image_max_px():
    try:
        return int(os.environ.get("STACK_IMAGE_MAX_PX", "1919"))
    except ValueError:
        return 1919


def image_max_b64():
    try:
        return max(1000, int(os.environ.get("STACK_IMAGE_MAX_B64", str(IMAGE_MAX_B64))))
    except ValueError:
        return IMAGE_MAX_B64


def image_size(b):
    """(width, height) from a PNG, GIF, BMP, WebP or JPEG header; None if unknown."""
    if b[:8] == b"\x89PNG\r\n\x1a\n" and len(b) >= 24:
        return struct.unpack(">II", b[16:24])
    if b[:6] in (b"GIF87a", b"GIF89a") and len(b) >= 10:
        return struct.unpack("<HH", b[6:10])
    if b[:2] == b"BM" and len(b) >= 26:
        w, h = struct.unpack("<ii", b[18:26])
        return abs(w), abs(h)
    if b[:4] == b"RIFF" and b[8:12] == b"WEBP" and len(b) >= 30:
        kind = b[12:16]
        if kind == b"VP8 ":
            return (struct.unpack("<H", b[26:28])[0] & 0x3FFF, struct.unpack("<H", b[28:30])[0] & 0x3FFF)
        if kind == b"VP8L":
            bits = int.from_bytes(b[21:25], "little")
            return (bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1
        if kind == b"VP8X":
            return int.from_bytes(b[24:27], "little") + 1, int.from_bytes(b[27:30], "little") + 1
        return None
    if b[:2] == b"\xff\xd8":
        i, n = 2, len(b)
        while i + 9 < n:
            if b[i] != 0xFF:
                i += 1
                continue
            m = b[i + 1]
            if m == 0xFF or m == 0x01 or 0xD0 <= m <= 0xD8:
                i += 1 if m == 0xFF else 2
                continue
            seg = struct.unpack(">H", b[i + 2:i + 4])[0]
            if m in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
                h, w = struct.unpack(">HH", b[i + 5:i + 9])
                return w, h
            i += 2 + seg
    return None


def sniff_mime(b):
    if b[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if b[:2] == b"\xff\xd8":
        return "image/jpeg"
    if b[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if b[:4] == b"RIFF" and b[8:12] == b"WEBP":
        return "image/webp"
    if b[:2] == b"BM":
        return "image/bmp"
    if b[:4] in (b"II*\x00", b"MM\x00*"):
        return "image/tiff"
    if b[4:8] == b"ftyp":
        if b[8:12] in (b"avif", b"avis"):
            return "image/avif"
        if b[8:12] in (b"heic", b"heix", b"hevc", b"hevx", b"heim", b"heis", b"mif1", b"msf1"):
            return "image/heic"
    return ""


def image_traits(b, mime):
    """(may be transparent, animated), read from the header bytes."""
    if mime == "image/png":
        idat = b.find(b"IDAT")
        head = b[:idat] if idat > 0 else b[:1 << 16]
        return (len(b) > 25 and b[25] in (4, 6)) or b"tRNS" in head, b"acTL" in head
    if mime == "image/gif":
        return True, b.count(b"\x21\xf9\x04") > 1
    if mime == "image/webp":
        if b[12:16] == b"VP8X" and len(b) > 20:
            return bool(b[20] & 0x10), bool(b[20] & 0x02)
        if b[12:16] == b"VP8L" and len(b) >= 25:
            return bool((int.from_bytes(b[21:25], "little") >> 28) & 1), False
        return False, False
    if mime == "image/bmp":
        return len(b) >= 30 and struct.unpack("<H", b[28:30])[0] == 32, False
    if mime == "image/tiff":
        return True, False
    return False, False


def out_format(mime, alpha):
    """Encoding for a scaled copy: keep JPEG and PNG; otherwise PNG if it may be transparent."""
    if mime == "image/jpeg":
        return "jpeg"
    if mime == "image/png":
        return "png"
    return "png" if alpha else "jpeg"


def file_image_size(path, deadline=None):
    try:
        with open(path, "rb") as f:
            head = f.read(1 << 20)   # JPEG metadata can push the size header far in
    except OSError:
        return None
    size = image_size(head)
    sips = sips_path()
    left = min(15.0, (deadline or time.time() + 15) - time.time())
    if size is None and sips and left > 1:
        try:   # HEIC, TIFF, AVIF and the like: ask macOS
            out = subprocess.run([sips, "-g", "pixelWidth", "-g", "pixelHeight", path],
                                 capture_output=True, text=True, timeout=left).stdout
            w = re.search(r"pixelWidth:\s*(\d+)", out)
            h = re.search(r"pixelHeight:\s*(\d+)", out)
            size = (int(w.group(1)), int(h.group(1))) if w and h else None
        except (OSError, subprocess.SubprocessError):
            size = None
    return size


def sips_path():
    return shutil.which("sips") or ("/usr/bin/sips" if os.path.exists("/usr/bin/sips") else None)


def run_quiet(cmd, deadline):
    left = deadline - time.time()
    if left < 1:
        return False
    try:
        return subprocess.run(cmd, capture_output=True, timeout=min(25.0, left)).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def pillow_resize(src, dst, limit, jpeg, quality):
    try:
        from PIL import Image, ImageOps
        with Image.open(src) as im:
            im = ImageOps.exif_transpose(im)   # the pixels as they are shown, not as stored
            if jpeg and (im.mode in ("RGBA", "LA", "PA") or (im.mode == "P" and "transparency" in im.info)):
                rgba = im.convert("RGBA")
                flat = Image.new("RGB", rgba.size, (255, 255, 255))
                flat.paste(rgba, mask=rgba.getchannel("A"))
                im = flat
            elif jpeg and im.mode not in ("RGB", "L"):
                im = im.convert("RGB")
            im.thumbnail((limit, limit), getattr(Image, "Resampling", Image).LANCZOS)
            im.save(dst, "JPEG" if jpeg else "PNG", **({"quality": quality} if jpeg else {}))
        return True
    except Exception:   # noqa: BLE001 - Pillow missing or can't read it: try the next resizer
        return False


def resize_image(data, limit, fmt, quality=85, deadline=None, alpha=False):
    """`data` scaled to fit limit x limit (aspect ratio kept), encoded as fmt ("jpeg" or "png");
    (bytes, (w, h)) or None when no resizer managed it in time. Transparency becomes white in a JPEG
    (sips would make it black, so it isn't used for that)."""
    deadline = deadline or time.time() + 25
    jpeg = fmt == "jpeg"
    in_ext = {"image/png": "png", "image/jpeg": "jpg", "image/gif": "gif", "image/webp": "webp",
              "image/bmp": "bmp", "image/tiff": "tif", "image/heic": "heic",
              "image/avif": "avif"}.get(sniff_mime(data), "img")
    sips = sips_path()
    magick = shutil.which("magick") or shutil.which("convert")
    with tempfile.TemporaryDirectory(prefix="stack-img-") as tmp:
        src, dst = os.path.join(tmp, "in." + in_ext), os.path.join(tmp, "out." + ("jpg" if jpeg else "png"))
        with open(src, "wb") as f:
            f.write(data)
        done = bool(sips) and not (jpeg and alpha) and run_quiet([sips, "-s", "format", fmt]
                                        + (["-s", "formatOptions", str(quality)] if jpeg else [])
                                        + ["-Z", str(limit), src, "--out", dst], deadline)
        if not done and time.time() < deadline - 1:
            done = pillow_resize(src, dst, limit, jpeg, quality)
        if not done and magick:
            cmd = [magick, src + "[0]", "-auto-orient", "-resize", "%dx%d>" % (limit, limit)]
            if jpeg:
                cmd += ["-background", "white", "-alpha", "remove", "-alpha", "off", "-quality", str(quality)]
            done = run_quiet(cmd + [dst], deadline)
        if not done or not os.path.exists(dst):
            warn_once("image-limit: couldn't scale an image (needs sips, Pillow or ImageMagick): left as it was")
            return None
        with open(dst, "rb") as f:
            out = f.read()
    size = image_size(out)
    if not size or max(size) > limit:
        return None
    return out, size


def encode_for_model(data, limit, deadline):
    """(base64, mime, (w, h)) for an image above the limit, within the API's size cap; else None."""
    size = image_size(data)
    if not size or max(size) <= limit:
        return None
    mime = sniff_mime(data)
    alpha = image_traits(data, mime)[0]
    fmt = out_format(mime, alpha)
    tries = [(fmt, 85)] + [("jpeg", q) for q in (70, 55, 40) if (fmt, q) != ("jpeg", 85)]
    cap = image_max_b64()
    for f, q in tries:
        if time.time() > deadline:
            return None
        out = resize_image(data, limit, f, q, deadline, alpha)
        if not out:
            return None
        b64 = base64.b64encode(out[0]).decode("ascii")
        if len(b64) <= cap:
            return b64, "image/jpeg" if f == "jpeg" else "image/png", out[1]
    warn_once("image-limit: an image stays above the size cap even as JPEG: left as it was")
    return None


def limit_b64(b64, limit, deadline):
    if not isinstance(b64, str) or len(b64) > 96 * 1024 * 1024:
        return None
    try:
        data = base64.b64decode(b64, validate=False)
    except (ValueError, TypeError):
        return None
    return encode_for_model(data, limit, deadline)


def limit_read_result(resp, limit, deadline):
    """Read's image result, re-encoded under the limit, or None when it already fits."""
    if not (isinstance(resp, dict) and resp.get("type") == "image" and isinstance(resp.get("file"), dict)):
        return None
    f = resp["file"]
    new = limit_b64(f.get("base64"), limit, deadline)
    if not new:
        return None
    f2 = dict(f, base64=new[0], type=new[1])
    if isinstance(f.get("dimensions"), dict):
        f2["dimensions"] = dict(f["dimensions"], displayWidth=new[2][0], displayHeight=new[2][1])
    return dict(resp, file=f2)


def limit_blocks(obj, limit, deadline, depth=0):
    """Image blocks anywhere in an MCP result re-encoded under the limit. (new obj, changed)."""
    if depth > 20:
        return obj, 0
    if isinstance(obj, list):
        out, n = [], 0
        for x in obj:
            y, k = limit_blocks(x, limit, deadline, depth + 1)
            out.append(y)
            n += k
        return (out, n) if n else (obj, 0)
    if not isinstance(obj, dict):
        return obj, 0
    if obj.get("type") == "image":
        src = obj.get("source")
        if isinstance(src, dict) and src.get("type") == "base64" and isinstance(src.get("data"), str):
            new = limit_b64(src["data"], limit, deadline)
            return (dict(obj, source=dict(src, data=new[0], media_type=new[1])), 1) if new else (obj, 0)
        if isinstance(obj.get("data"), str):
            new = limit_b64(obj["data"], limit, deadline)
            return (dict(obj, data=new[0], mimeType=new[1]), 1) if new else (obj, 0)
    out, n = {}, 0
    for k, v in obj.items():
        y, c = limit_blocks(v, limit, deadline, depth + 1)
        out[k] = y
        n += c
    return (out, n) if n else (obj, 0)


def read_denied(path, ev):
    fold = (lambda x: x.lower()) if sys.platform == "darwin" else (lambda x: x)
    cands = {path, os.path.realpath(path)}
    for spec, anchors in read_deny_specs(path_bases(ev)):
        for rx, _literal in deny_patterns(spec, anchors):
            if any(rx.match(fold(c)) or rx.match(c) for c in cands):
                return True
    return False


def upload_arg_keys(tool):
    """The argument names (a tuple, or a regex for STACK_IMAGE_UPLOAD_TOOLS) under which `tool`
    takes local image files it sends off the machine; None for any other tool."""
    for rx, keys in UPLOAD_TOOLS:
        if rx.match(tool):
            return keys
    extra = os.environ.get("STACK_IMAGE_UPLOAD_TOOLS", "").strip()
    if extra:
        try:
            if re.fullmatch(extra, tool):
                return UPLOAD_KEYS
        except re.error:
            warn_once("image-limit: STACK_IMAGE_UPLOAD_TOOLS is not a valid regular expression")
    return None


def local_image_path(value, ev):
    """(path, given as a file:// URI) when `value` names one existing local file; (None, _)
    otherwise, also when a relative path would mean different files from the bases a tool uses."""
    s = value.strip()
    uri = s[:7].lower() == "file://"
    p = unquote(urlparse(s).path) if uri else os.path.expanduser(s)
    if not p:
        return None, uri
    if os.path.isabs(p):
        return (p if os.path.isfile(p) else None), uri
    hits = {}
    for b in path_bases(ev) or [os.getcwd()]:
        q = os.path.normpath(os.path.join(b, p))
        if os.path.isfile(q):
            hits.setdefault(os.path.realpath(q), q)
    return (next(iter(hits.values())) if len(hits) == 1 else None), uri


class NoCopy(Exception):
    """An oversized image the hook can't make an upload copy of; the message says why."""


def own_plain_dir(path):
    st = os.lstat(path)
    return stat.S_ISDIR(st.st_mode) and not stat.S_ISLNK(st.st_mode) and st.st_uid == os.getuid()


def copy_for_upload(path, limit, deadline):
    """The path of a copy of the image at `path` scaled under the limit, in <its folder>/.downscaled/
    under the same name (the old extension added when the format changes); None when the file is
    within the limit or not an image this can read. Raises NoCopy when it is too big but can't be
    copied."""
    st = os.stat(path)
    if st.st_size > MAX_IMAGE_FILE:
        return None
    size = file_image_size(path, deadline)
    if not size or max(size) <= limit:
        return None
    what = "%s is %dx%d px" % (path, size[0], size[1])
    if os.path.islink(path):
        raise NoCopy(what + " and a symlink (a copy next to it would sit somewhere else than the file)")
    with open(path, "rb") as f:
        data = f.read()
    mime = sniff_mime(data) or IMAGE_MIME.get(os.path.splitext(path)[1].lower(), "")
    alpha, animated = image_traits(data, mime)
    if animated:
        raise NoCopy(what + " and animated (scale every frame, e.g. ffmpeg -i in.gif -vf "
                     "\"scale='min(1919,iw)':'min(1919,ih)':force_original_aspect_ratio=decrease\" out.gif)")
    fmt = out_format(mime, alpha)
    stem, ext = os.path.splitext(os.path.basename(path))
    same = ext.lower() in ((".jpg", ".jpeg") if fmt == "jpeg" else (".png",))
    name = stem + ext if same else "%s-%s%s" % (stem, ext.lstrip(".").lower() or "img",
                                                   ".jpg" if fmt == "jpeg" else ".png")
    folder = os.path.join(os.path.dirname(path), COPY_DIR)
    dest = os.path.join(folder, name)
    try:
        os.mkdir(folder, 0o755)
    except FileExistsError:
        pass
    except OSError as exc:
        raise NoCopy("%s, and its folder can't take a %s/ copy (%s)" % (what, COPY_DIR, exc.strerror))
    if not own_plain_dir(folder):
        raise NoCopy("%s, and %s isn't a plain folder of yours" % (what, folder))
    try:   # a copy that carries its original's modification time, made for this limit, is reused
        cst = os.lstat(dest)
        if (stat.S_ISREG(cst.st_mode) and cst.st_uid == os.getuid() and cst.st_mtime_ns == st.st_mtime_ns
                and max(file_image_size(dest, deadline) or (0,)) == limit):
            return dest
    except OSError:
        pass
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(os.path.join(folder, ".gitignore"), os.O_WRONLY | os.O_CREAT | os.O_EXCL | nofollow, 0o644)
        with os.fdopen(fd, "w") as f:
            f.write("# downscaled copies of images agents uploaded (claude-agent-stack)\n*\n")
    except OSError:
        pass   # already there (or not ours to write): the copy still works
    out = resize_image(data, limit, fmt, 85, deadline, alpha)
    if not out:
        raise NoCopy(what + ", and it couldn't be scaled here")
    tmp = "%s.%d.tmp" % (dest, os.getpid())
    try:
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | nofollow, (st.st_mode & 0o777) | 0o600)
        with os.fdopen(fd, "wb") as f:
            f.write(out[0])
        os.utime(tmp, ns=(st.st_atime_ns, st.st_mtime_ns))
        os.replace(tmp, dest)
    except OSError as exc:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise NoCopy("%s, and the copy couldn't be written (%s)" % (what, exc.strerror))
    return dest


def limit_upload_input(ev, limit, deadline):
    """(tool_input with oversized local images swapped for downscaled copies or None, the reasons
    oversized images couldn't be copied)."""
    tool = ev.get("tool_name") or ""
    inp = ev.get("tool_input")
    keys = upload_arg_keys(tool)
    if keys is None or not isinstance(inp, dict):
        return None, []
    wanted = keys.match if hasattr(keys, "match") else keys.__contains__
    changed, problems = [0], []

    def swap(value):
        if not value.strip() or len(value) > MAX_PATH_ARG or time.time() > deadline:
            return value
        path, uri = local_image_path(value, ev)
        if not path or os.path.splitext(path)[1].lower() not in IMAGE_MIME or read_denied(path, ev):
            return value
        try:
            copy = copy_for_upload(path, limit, deadline)
        except NoCopy as exc:
            problems.append(str(exc))
            return value
        except OSError:
            return value
        if not copy:
            return value
        changed[0] += 1
        if not uri:
            return copy
        return "file://" + (quote(copy) if "%" in value else copy)   # escaped the way it was given

    def walk(obj, depth=0):
        if depth > 4 or not isinstance(obj, dict):
            return obj
        out = {}
        for k, v in obj.items():
            if wanted(str(k)):
                if isinstance(v, str):
                    v = swap(v)
                elif isinstance(v, list):
                    v = [swap(x) if isinstance(x, str) else walk(x, depth + 1) for x in v]
                elif isinstance(v, dict):
                    v = walk(v, depth + 1)
            elif isinstance(v, dict):
                v = walk(v, depth + 1)
            elif isinstance(v, list):
                v = [walk(x, depth + 1) if isinstance(x, dict) else x for x in v]
            out[k] = v
        return out

    new = walk(inp)
    return (new if changed[0] else None), problems


def image_limit(ev):
    """The hook output for one event, or None to leave the call alone."""
    limit = image_max_px()
    if limit <= 0 or not isinstance(ev, dict):
        return None
    deadline = time.time() + IMAGE_DEADLINE_S
    event, tool = ev.get("hook_event_name"), ev.get("tool_name") or ""
    if event == "PostToolUse" and tool == "Read":
        new = limit_read_result(ev.get("tool_response"), limit, deadline)
        return {"hookSpecificOutput": {"hookEventName": "PostToolUse", "updatedToolOutput": new}} if new else None
    if event == "PostToolUse" and tool.startswith("mcp__"):
        resp = ev.get("tool_response")
        if isinstance(resp, str):
            if '"image"' not in resp:
                return None
            try:
                resp = json.loads(resp)
            except ValueError:
                return None
        new, n = limit_blocks(resp, limit, deadline)
        return {"hookSpecificOutput": {"hookEventName": "PostToolUse", "updatedToolOutput": new}} if n else None
    if event == "PreToolUse" and tool.startswith("mcp__"):
        new, problems = limit_upload_input(ev, limit, deadline)
        if problems:
            return {"hookSpecificOutput": {
                "hookEventName": "PreToolUse", "permissionDecision": "deny",
                "permissionDecisionReason": (
                    "Uploads stay under %d px on both sides. %s. Make a copy yourself inside the project, "
                    "e.g. sips -Z %d '<file>' --out '<project>/.claude-work/<name>', and upload that."
                    % (limit + 1, "; ".join(problems), limit))}}
        return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "updatedInput": new}} if new else None
    return None


def image_limit_main(raw):
    """image-limit mode: never blocks; any failure leaves the tool call and its result unchanged."""
    low = raw.lower()
    if not os.environ.get("STACK_IMAGE_UPLOAD_TOOLS") and not any(
            w in low for w in ("image", "upload", '"read"', "photo", "picture", "drop", "img")):
        return 0   # fast path: nothing image-like in this event
    try:
        out = image_limit(json.loads(raw))
    except Exception as exc:   # noqa: BLE001 - fail open by design
        warn("image-limit: %s: %s" % (type(exc).__name__, exc))
        return 0
    if out:
        sys.stdout.write(json.dumps(out))
        sys.stdout.flush()
    return 0


# ---------------------------------------------------------------- blackcat-guard mode
def blackcat_guard(raw):
    if not policy_on():
        sys.exit(0)
    try:
        ev = json.loads(raw)
        if not isinstance(ev, dict):
            raise ValueError("hook input is not a JSON object")
    except (ValueError, RecursionError) as exc:   # RecursionError: absurdly nested JSON
        guard_error("unparseable hook input (%s)" % type(exc).__name__)
    if ev.get("agent_id"):
        sys.exit(0)  # a subagent's tool call
    tool = ev.get("tool_name") or ""
    if tool == "Agent":
        sys.exit(0)  # dispatch-once is enforced by the main hook
    if tool not in BLACKCAT_TOOLS:
        deny("BlackCat only delegates. Make one Agent call to the right specialist (or "
             "orchestrator), or SendMessage to resume the previous agent.")
    d = sdir(ev.get("session_id"))
    log(d, ev)
    steps = knob_int("BLACKCAT_MAX_STEPS", 8)
    if not claim_marker(d, "step", prompt_key(ev), steps):
        deny("BlackCat step limit (%d per prompt) reached. Call no more tools: answer the user "
             "now with what you have, or say what is still pending." % steps)
    sys.exit(0)


# ---------------------------------------------------------------- no-push mode
# The stack's Git rule: agents never push and never write to a forge. settings.json denies
# `Bash(git push *)` and the common forge writes (`gh pr create`, `tea pulls merge`, ...), but a
# permission rule sees only the plain spelling: not `git -C dir push`, `/usr/bin/git push`,
# `bash -c 'git push'` or `eval 'gh pr merge 1'`. Neither does a hook's `if` filter (tested on
# Claude Code 2.1.283: `if: "Bash(git *)"` skips `bash -c`, `sh -c`, `zsh -c`, `eval` and
# `/usr/bin/git`), so this PreToolUse hook has no `if` and runs on every Bash, Monitor and
# PowerShell call (~40 ms, mostly interpreter start-up; commands that name no git/gh/tea/fj
# return at once).
# It parses the command as bash/zsh would: quotes, `$'...'`, backslash-newline, comments,
# newlines, `$(...)`, backticks and `<(...)`, arithmetic, heredocs (a body is code only when the
# command that owns it, or its compound command, is a shell, eval, source or ssh), and the
# strings that other programs run as shell code: `sh|bash|zsh|dash|ksh|fish -c` (with `$1`/`$@`
# arguments when the code runs them), `pwsh -Command`, `eval`, `env -S`, `ssh`, `watch`, `su -c`,
# `tmux`, here-strings and pipes into a shell, `python -c`/`node -e` code that starts a process,
# `$(printf 'git %s' push)` output, and git's own command hooks (`-c alias.x=...` expanded with
# its arguments, `core.editor`, `GIT_EDITOR=`, `submodule foreach`, `rebase --exec`,
# `bisect run`). Words are compared after unquoting, so data — a commit message, a grep
# pattern, a heredoc into `git commit -F -` — passes. What the shell decides only at run time
# (`git $X`, `g${X}it`, `$G push`, `xargs git`, `echo ... | base64 -d | sh`, `pwsh
# -EncodedCommand`) is refused, and so is a command the guard cannot finish checking (a parser
# error, nesting deeper than MAX_NEST, more than 64 heredocs on a line, DEADLINE_S of work).
# PowerShell syntax is modelled only as far as `-Command`, `iex`, `Start-Process` and backtick
# escapes. Deliberately not switched off by STACK_POLICY=off: the rule is absolute. Best effort:
# an alias or function defined in an earlier command, a script file or download, a variable
# holding the whole command, or text assembled by string operations stays out of sight.
GIT_OPTS_WITH_VALUE = {"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--config-env",
                       "--super-prefix", "--exec-path", "--attr-source"}
PUSH_SUBCOMMANDS = {"push", "send-pack"}
PUSH_UNDER = {"lfs": {"push"}, "subtree": {"push"}, "svn": {"dcommit", "set-tree"},
              "p4": {"submit"}}                      # git lfs push, git svn dcommit, ...
PUSH_PROGRAMS = {"git-push", "git-send-pack"}         # "$(git --exec-path)/git-push"
PROGRAMS = {"git", "gh", "tea", "fj"} | PUSH_PROGRAMS
PUSH_RE = re.compile(r"(?:^|[\s;&|(`'\"])(?:\S*/)?git(?:\s+-{1,2}[^\s]+(?:\s+[^\s-][^\s]*)?)*?"
                     r"\s+['\"]?(?:push|send-pack|(?:lfs|subtree)\s+['\"]?push)\b")
# config keys whose value git runs as a command (git -c KEY=VALUE, git config KEY VALUE)
GIT_EXEC_KEY_RE = re.compile(
    r"(?:alias\..+|core\.(?:editor|pager|sshcommand|fsmonitor|askpass)|sequence\.editor|pager\..+|"
    r"diff\.external|diff\..+\.(?:command|textconv)|difftool\..+\.cmd|mergetool\..+\.cmd|"
    r"merge\..+\.driver|filter\..+\.(?:clean|smudge|process)|interactive\.difffilter|"
    r"gpg\.program|gpg\..+\.program|credential\.helper|credential\..+\.helper|"
    r"uploadpack\.packobjectshook|sendemail\..+)\Z", re.I)
ENV_EXEC_RE = re.compile(r"(?:GIT_[A-Z0-9_]+|EDITOR|VISUAL|PAGER|SSH_ASKPASS)=(.*)\Z", re.S)
ASSIGN_RE = re.compile(r"[A-Za-z_]\w*\+?=")
OPAQUE_SUB_RE = re.compile(r"[$`{}*?\[\]\x00]")      # expansions and globs: decided at run time
EXPANSION_RE = re.compile(r"\$(?:\{[^}]*\}|[A-Za-z_]\w*|[@*#?$!0-9-])")
PWSH = {"pwsh", "powershell", "pwsh.exe", "powershell.exe"}
SHELLS = {"sh", "bash", "rbash", "zsh", "dash", "ksh", "ksh93", "mksh", "pdksh", "ash", "yash",
          "posh", "fish", "csh", "tcsh"} | PWSH
# programs that run their (joined) arguments as shell code
STRING_RUNNERS = {"eval", "ssh", "watch", "su", "runuser", "script", "flock", "tmux", "screen",
                  "parallel", "expect", "iex", "invoke-expression"}
HEREDOC_RUNNERS = SHELLS | {"eval", "ssh"}           # read a heredoc on stdin as commands
INTERPRETER_RE = re.compile(r"(?:python|pypy|perl|ruby|node|nodejs|deno|bun|php|lua|luajit|"
                            r"osascript|Rscript|julia)[\d.]*(?:\.exe)?\Z")
CODE_FLAG_RE = re.compile(r"-[A-Za-z]*[ceErp]\Z|--(?:eval|command|print)\Z")
CODE_PUNCT_RE = re.compile(r"[\[\](){},;:+'\"`]")     # os.system("git push"), ['gh','pr','create']
# inline code is checked only when it can start a process (print('git push') is text)
EXEC_HINT_RE = re.compile(r"\b(?:system|exec\w*|popen\w*|spawn\w*|run|call|check_\w+|proc_open|"
                          r"passthru|shell_exec|start)\s*[(\"'\[{]|\bsystem\s+\S|subprocess|"
                          r"Deno\.(?:Command|run)|"
                          r"child_process|\bos\.|Runtime|ProcessBuilder|do shell script|`|%x[({\[]|"
                          r"\bqx\s*[({\[/]", re.I)
CODE_ARGS_KEY_RE = re.compile(r"\b(?:args|argv|arguments|cmd)\b")   # Deno.Command('git', {args: [..]})
# `sh -c CODE a b`: a and b are data unless CODE runs a positional parameter as a command
POSITIONAL_CMD_RE = re.compile(r"(?:^|[;&|({\n`]|\b(?:eval|exec|then|do|else|command|sudo|env|"
                               r"xargs|nohup|time)\b)\s*[\"']?\$(?:[@*0-9]|\{[@*0-9])")
HELP_BOOL_OPTS = {"--fill", "--fill-first", "--fill-verbose", "--draft", "--web", "--squash",
                  "--merge", "--rebase", "--delete-branch", "--auto", "--admin", "--approve",
                  "--dry-run", "--yes", "--no-maintainer-edit", "--disable-auto",
                  "-s", "-m", "-r", "-d", "-f", "-w", "-y", "-a", "-c"}
# words after which the next word is still a command name (`exec git-push`, `env X=1 cmd`)
PREFIX_WORDS = {"exec", "command", "builtin", "nohup", "time", "env", "sudo", "doas", "xargs",
                "timeout", "nice", "stdbuf", "noglob", "then", "do", "else", "elif", "if",
                "while", "until", "!", "{"}
SEP_RE = re.compile(r"[;&|()\n]+\Z")                  # shlex tokens that end a simple command
REDIR_OP_RE = re.compile(r"[<>]+&?\Z|&>+\Z")
# fast path: a command that names none of these (after dropping quotes, backslashes and
# expansions: g''it, g${X}it) and holds no escape that could spell one ($'\x67it', printf
# '\147it') is not checked further
TRIGGER_RE = re.compile(r"(?<![A-Za-z0-9_-])(?:git|gh|tea|fj)")
ESCAPE_RE = re.compile(r"\$'|\\(?:x[0-9A-Fa-f]|u[0-9A-Fa-f]|[0-7])")
# ... nor a command the shell only knows at run time: `$G push`, pwsh -EncodedCommand, a
# decoded pipeline into a shell (base64 -d | sh)
OPAQUE_HINT_RE = re.compile(r"\$[\w{(@*!#?-]\S*\s+(?:push|send-pack)\b|\b(?:pwsh|powershell)\b|"
                            r"\|\s*(?:\S*/)?(?:sh|bash|zsh|dash|ksh|fish|source|\.)(?:\s|$)|"
                            r"\benv\s[^;&|\n]*-S", re.I)
# a pipeline into a shell whose text starts as a literal (echo, printf, <<<) and is transformed
# on the way (base64 -d, rev, tr, sed ...) runs commands nobody can read here: refused.
# Downloads and files (curl | bash, gunzip -c x.gz | sh) are scripts, out of sight like any file.
LITERAL_SOURCES = {"echo", "printf", "print"}
PASS_THROUGH = {"cat", "tee", "echo", "printf", "print"}
LENIENT_RE = re.compile(r"\n|[;&|()<>]+|[^\s;&|()<>'\"]+")
HEREDOC_OP_RE = re.compile(r"<<(-?)[ \t]*(?:(['\"])([^'\"\n]+)\2|(\\?)([A-Za-z0-9_][\w.-]*))")
ANSI_C_RE = re.compile(r"\$'((?:[^'\\]|\\.)*)'", re.S)
ANSI_ESC_RE = re.compile(r"\\(x[0-9A-Fa-f]{1,2}|u[0-9A-Fa-f]{1,4}|U[0-9A-Fa-f]{1,8}|[0-7]{1,3}"
                         r"|c.|.)", re.S)
ANSI_ESC = {"a": "\a", "b": "\b", "e": "\x1b", "E": "\x1b", "f": "\f", "n": "\n", "r": "\r",
            "t": "\t", "v": "\v", "\\": "\\", "'": "'", '"': '"', "?": "?"}
SUBST_MARK = "\x00S%d\x00"                            # NULs never survive into a shell command
SUBST_MARK_RE = re.compile("\x00S(\\d+)\x00")
MAX_NEST, MAX_SCANS, MAX_FORGE_WORDS, DEADLINE_S = 8, 2000, 12, 8.0
MAX_COMMAND, MAX_HEREDOCS_PER_LINE = 1000000, 64   # characters of code (heredoc bodies apart)
# closer -> (opener, closer) keywords, to find the compound command a heredoc on `done` feeds
COMPOUND_OPENERS = {"done": (r"(?:while|until|for|select)", "done"), "fi": ("if", "fi"),
                    "esac": ("case", "esac"), "}": (r"\{", r"\}"), ")": (r"\(", r"\)")}
# options of prefix commands that take a value (sudo -u deploy bash, timeout -s KILL 60 sh)
PREFIX_VALUE_OPTS = {"-u", "-g", "-C", "-h", "-p", "-U", "-D", "-R", "-T", "-s", "-k", "-i",
                     "-o", "-e", "-n", "-I", "-P", "-L", "-d", "-E", "-a", "--user", "--group",
                     "--signal", "--kill-after", "--chdir", "--unset", "--adjustment"}
EXEC_OPTS = {"-exec", "-execdir", "-ok", "-okdir"}     # find -exec CMD ...
DOC_COMMANDS = {"man", "info", "help", "whatis", "apropos", "tldr", "which", "whereis", "type",
                "whence", "command -v"}               # man git push: a manual page, not a push
# pwsh command-line switches in the order pwsh matches them: (name, shortest prefix, kind);
# pwsh takes any prefix at least that long (CommandLineParameterParser.cs, MatchSwitch)
PWSH_SWITCHES = [
    ("version", "v", "flag"), ("help", "h", "flag"), ("?", "?", "flag"), ("login", "l", "flag"),
    ("noexit", "noe", "flag"), ("noprofile", "nop", "flag"), ("nologo", "nol", "flag"),
    ("noninteractive", "noni", "flag"), ("socketservermode", "so", "flag"),
    ("v2socketservermode", "v2so", "flag"), ("servermode", "s", "flag"),
    ("namedpipeservermode", "nam", "flag"), ("sshservermode", "sshs", "flag"),
    ("noprofileloadtime", "noprofileloadtime", "flag"), ("interactive", "i", "flag"),
    ("configurationfile", "configurationfile", "value"), ("configurationname", "config", "value"),
    ("custompipename", "cus", "value"), ("commandwithargs", "commandwithargs", "code"),
    ("cwa", "cwa", "code"), ("command", "c", "code"), ("windowstyle", "w", "value"),
    ("file", "f", "file"), ("isswait", "isswait", "flag"), ("outputformat", "o", "value"),
    ("of", "o", "value"), ("inputformat", "inp", "value"), ("if", "if", "value"),
    ("executionpolicy", "ex", "value"), ("ep", "ep", "value"), ("encodedcommand", "e", "encoded"),
    ("ec", "e", "encoded"), ("encodedarguments", "encodeda", "encoded"), ("ea", "ea", "encoded"),
    ("settingsfile", "settings", "value"), ("sta", "sta", "flag"), ("mta", "mta", "flag"),
    ("workingdirectory", "wo", "value"), ("wd", "wd", "value"),
    ("removeworkingdirectorytrailingcharacter", "removeworkingdirectorytrailingcharacter", "flag"),
    ("token", "to", "value"), ("utctimestamp", "utc", "value"),
]


class _TooComplex(Exception):
    """The command cannot be checked within the guard's limits: it is refused as opaque."""

# Forge CLIs: command tree -> WRITE (refused), READ (stop: fine), a subtree, or a special check.
# Checked against the gh manual (cli.github.com/manual, Sep 2026), tea's docs/CLI.md (main) and
# forgejo-cli's clap definitions (codeberg.org/forgejo-contrib/forgejo-cli, main). "a|b" spells
# aliases; "*" is what a group means when only unknown words follow it.
WRITE, READ = "write", "read"
GH_API = ("api", {"-X", "--method"}, {"-f", "-F", "--field", "--raw-field", "--input"},
          {"-H", "--header", "-q", "--jq", "-t", "--template", "-p", "--preview", "--hostname",
           "--cache"})
TEA_API = ("api", {"-X", "--method"}, {"-f", "-F", "--field", "--Field", "-d", "--data"},
           {"-H", "--header", "-l", "--login", "-o", "--output", "-R", "--remote", "-r", "--repo"})


def _forge_tree(spec):
    if not isinstance(spec, dict):
        return spec
    return {k: _forge_tree(sub) for keys, sub in spec.items() for k in keys.split("|")}


FORGE_TREES = {
    "gh": _forge_tree({
        "pr": {"create|new|merge|close|reopen|edit|comment|review|ready|lock|unlock|"
               "update-branch|revert": WRITE,
               "view|list|ls|status|checks|diff|checkout|co": READ},
        "issue": {"create|new|close|reopen|edit|comment|delete|transfer|lock|unlock|pin|unpin":
                  WRITE, "develop": ("unless-flag", ("-l", "--list")),
                  "view|list|ls|status": READ},
        "release": {"create|new|delete|delete-asset|edit|upload": WRITE,
                    "view|list|ls|download|verify|verify-asset": READ},
        "repo": {"create|new|delete|edit|fork|rename|archive|unarchive|sync": WRITE,
                 "deploy-key": {"add|delete": WRITE, "list|ls": READ},
                 "autolink": {"create|new|delete": WRITE, "list|ls|view": READ},
                 "view|list|ls|clone|set-default|read-dir|read-file|gitignore|license": READ},
        "discussion": {"create|comment|edit": WRITE, "view|list|ls": READ},
        "gist": {"create|new|delete|edit|rename": WRITE, "view|list|ls|clone": READ},
        "label": {"create|delete|edit|clone": WRITE, "list|ls": READ},
        "workflow": {"run|enable|disable": WRITE, "view|list|ls": READ},
        "run": {"rerun|cancel|delete": WRITE, "view|list|ls|download|watch": READ},
        "secret": {"set|delete|remove": WRITE, "list|ls": READ},
        "variable": {"set|delete|remove": WRITE, "get|list|ls": READ},
        "cache": {"delete": WRITE, "list|ls": READ},
        "ssh-key|gpg-key": {"add|delete": WRITE, "list|ls": READ},
        "project": {"close|copy|create|delete|edit|field-create|field-delete|item-add|"
                    "item-archive|item-create|item-delete|item-edit|link|mark-template|unlink":
                    WRITE, "view|list|ls|field-list|item-list": READ},
        "codespace|cs": {"create|delete|edit|rebuild|stop": WRITE,
                         "ports": {"visibility": WRITE, "forward": READ},
                         "view|list|ls|logs|code|jupyter|ssh|cp": READ},
        "agent-task|agent-tasks|agent|agents": {"create": WRITE, "view|list": READ},
        "skill|skills": {"publish": WRITE,
                         "install|add|list|ls|preview|show|search|update": READ},
        "api": GH_API,
        "alias": {"set": ("gh-alias",), "import|list|ls|delete": READ},
        "auth|config|extension|extensions|ext|completion|help|browse|status|search|attestation|"
        "at|ruleset|rs|org|licenses|preview|copilot|version": READ,
    }),
    "tea": _forge_tree({
        "issues|issue|i": {"create|c|edit|e|reopen|open|close": WRITE, "list|ls": READ},
        "pulls|pull|pr": {"create|c|close|reopen|open|edit|e|review|approve|lgtm|a|reject|merge|m|"
                          "reply|resolve|unresolve|clean": WRITE,
                          "list|ls|checkout|co|review-comments|rc": READ},
        "labels|label": {"create|c|update|delete|rm": WRITE, "list|ls": READ},
        "milestones|milestone|ms": {"create|c|close|delete|rm|reopen|open": WRITE,
                                    "issues|i": {"add|a|remove|r": WRITE}, "list|ls": READ},
        "releases|release|r": {"create|c|delete|rm|edit|e": WRITE,
                               "assets|asset|a": {"create|c|delete|rm": WRITE, "list|ls": READ},
                               "list|ls": READ},
        "times|time|t": {"add|a|delete|rm|reset": WRITE, "list|ls": READ},
        "organizations|organization|org": {"create|c|delete|rm": WRITE, "list|ls": READ},
        "repos|repo": {"create|c|create-from-template|ct|fork|f|migrate|m|delete|rm|edit|e": WRITE,
                       "list|ls|search|s": READ},
        "branches|branch|b": {"protect|P|unprotect|U|rename|rn": WRITE, "list|ls": READ},
        "actions|action": {
            "secrets|secret": {"create|add|set|delete|remove|rm": WRITE, "list|ls": READ},
            "variables|variable|vars|var": {"set|create|update|delete|remove|rm": WRITE,
                                            "list|ls": READ},
            "runs|run": {"delete|remove|rm|cancel": WRITE,
                         "list|ls|view|show|get|logs|log": READ},
            "workflows|workflow": {"dispatch|trigger|run|enable|disable": WRITE,
                                   "list|ls|view|show|get": READ}},
        "wiki": {"create|c|edit|e|delete|rm": WRITE, "list|ls|view|revisions|history": READ},
        "webhooks|webhook|hooks|hook": {"create|c|delete|rm|update|edit|u": WRITE, "list|ls": READ},
        # tea < 0.12 had `tea comment <index> <body>` ("*": two or more words the tree lacks)
        "comments|comment|c": {"add|a|edit|e|delete|rm": WRITE, "list|ls": READ, "*": WRITE},
        "notifications|notification|n": {"read|r|unread|u|pin|p|unpin": WRITE, "ls|list": READ},
        "ssh-keys|ssh-key": {"add|delete|rm": WRITE, "list|ls": READ},
        "admin|a": {"users|u": {"create|add|new|edit|update|e|u|delete|rm|remove": WRITE,
                                "list|ls": READ}},
        "api": TEA_API,
        "logins|login|logout|whoami|open|o|clone|C|help|h": READ,
    }),
    "fj": _forge_tree({
        "repo": {"create|fork|migrate|star|unstar|watch|unwatch|delete|edit|units|unit": WRITE,
                 "labels|label": {"create|delete|edit": WRITE, "view": READ},
                 "view|readme|clone|star-status|watch-status|browse": READ},
        "issue": {"create|edit|comment|assign|unassign|close": WRITE,
                  "depend|block": {"add|remove": WRITE, "list": READ},
                  "search|view|templates|browse": READ},
        "pr": {"create|comment|assign|unassign|edit|close|merge": WRITE,
               "depend|block": {"add|remove": WRITE, "list": READ},
               "search|view|status|checkout|browse|review": READ},
        "milestone": {"create|edit|delete": WRITE, "search|view": READ},
        "actions": {"dispatch": WRITE, "variables|secrets": {"create|delete": WRITE, "list": READ},
                    "tasks": READ},
        "release": {"create|edit|delete": WRITE, "asset": {"create|delete": WRITE, "download": READ},
                    "list|view|browse": READ},
        "tag": {"create|delete": WRITE, "list|view": READ},
        "user": {"follow|unfollow|block|unblock|edit": WRITE,
                 "key|gpg": {"upload|delete": WRITE, "list|view|verify": READ},
                 "search|view|browse|following|followers|repos|orgs|activity": READ},
        "org": {"create|edit": WRITE, "visibility": ("if-flag", ("-s", "--set")),
                "team": {"create|edit|delete": WRITE,
                         "repo|member": {"add|rm": WRITE, "list": READ}, "list|view": READ},
                "label": {"add|edit|rm": WRITE, "list": READ},
                "repo": {"create": WRITE, "list": READ},
                "list|view|activity|members": READ},
        "wiki|auth|whoami|version|completion|help": READ,
    }),
}
NO_PUSH_REASON = ("Blocked by the stack's git rule: agents never push to a remote, in any form "
                  "(git push, send-pack, lfs/subtree push; also inside bash -c, eval or $(...)). "
                  "Keep the work in the local repository: commit, merge it back into local main "
                  "(git merge --ff-only), and report the commits; pushing is the user's own step.")
FORGE_REASON = ("Blocked by the stack's git rule: agents never write to a forge, and `%s` "
                "creates, merges, comments on or changes something on GitHub/Gitea/Forgejo "
                "(gh, tea and fj, also `gh api`/`tea api` with a write method, inside bash -c or "
                "eval too). Read-only forge commands (view, list, status, checks, diff, checkout) "
                "are fine. Publishing is the user's own step: report the branch, the commits and "
                "the command for the user to run.")
OPAQUE_REASON = ("Blocked by the stack's git rule (agents never push): `%s` cannot be checked, "
                 "because the shell decides it only when the command runs. Write the git or forge "
                 "subcommand literally, without variables, globs or nesting this deep; pushing is "
                 "the user's own step.")
GUARD_FAIL_REASON = ("Blocked: the stack's no-push guard could not check this command (%s). Split "
                     "it into simpler commands; pushing and forge writes stay the user's own step.")


def _shell_words(command):
    """shlex words, with each unquoted newline kept as a "\\n" separator token."""
    lex = shlex.shlex(command, posix=True, punctuation_chars=";&|()<>\n")
    lex.whitespace = " \t\r"
    lex.whitespace_split = True
    lex.commenters = ""
    out = []
    for w in lex:
        if "\n" in w and w.strip("\n") and SEP_RE.match(w.replace("<", "").replace(">", "") or "x"):
            w = w.replace("\n", "")            # "|\n" continues the pipeline: plain "|"
        out.append(w)
    return out


def _c_unescape(s):
    """C-style escapes as bash's $'...', printf and echo -e read them."""
    def esc(m):
        e = m.group(1)
        try:
            if e[0] in "xuU":
                return chr(int(e[1:], 16))
            if e[0] in "01234567":
                return chr(int(e, 8) & 0xFF)
        except (ValueError, OverflowError):
            return ""
        if e[0] == "c" and len(e) == 2:
            return chr(ord(e[1]) & 0x1F)
        return ANSI_ESC.get(e, "\\" + e)
    return ANSI_ESC_RE.sub(esc, s)


def _command_position(prefix):
    """True when a substitution that starts after `prefix` (the text of its simple command so
    far) is the command name, so its output runs; False for an argument or a word part
    (`VAR=$(...)`, `--x=$(...)`)."""
    s = prefix.rstrip('"')                     # the opening quote of "$(...)"
    if s and not s[-1].isspace() and s[-1] not in ";&|(!{`\n":
        return False
    s = s.rstrip()
    if not s or s[-1] in ";&|(!{`\n":
        return True
    last = re.split(r"[\s;&|(]", s)[-1]
    return last in PREFIX_WORDS or bool(re.match(r"[A-Za-z_]\w*=\S*\Z", last))


def _script_position(prefix):
    """"script" when `<(...)` after `prefix` is the script a shell or `source` reads."""
    words = re.findall(r"[^\s;&|(]+", prefix.rsplit("\n", 1)[-1])
    while words and (ASSIGN_RE.match(words[0]) or words[0] in PREFIX_WORDS):
        words = words[1:]
    if words and (_base(words[0]) in SHELLS | {"source", "."}) and not any(
            w[:1] == "-" and "c" in w[1:] and not w.startswith("--") for w in words[1:]):
        return "script"
    return False


def _heredoc_owner(text, seg, i):
    """The command a heredoc feeds: its simple command, or the whole compound command when `<<`
    follows `done`, `fi`, `esac`, `}` or `)` (while read l; do eval "$l"; done <<EOF)."""
    own = text[max(seg, i - 512):i]
    words = own.split()
    if words and words[0] in COMPOUND_OPENERS:
        opener, closer = COMPOUND_OPENERS[words[0]]
        lo = max(0, seg - 4096)
        window = text[lo:seg]
        kw = r"(?<![\w-])(?:(%s)|(%s))(?![\w-])" if words[0][0].isalpha() else r"(%s)|(%s)"
        depth, start = 1, 0
        for m in reversed(list(re.finditer(kw % (opener, closer), window))):
            depth += 1 if m.group(2) else -1
            if not depth:
                start = m.start()
                break
        own = text[lo + start:i]
    return own


def _at_command_start(text, i):
    j = i - 1
    while j >= 0 and text[j] in " \t":
        j -= 1
    return j < 0 or text[j] in ";&|(\n{"


def _lex(text, deadline=None):
    """One quote-aware pass over a command, linear in its length. Returns (the text with comments,
    line continuations and heredoc bodies removed, `$'...'` decoded, and every outermost $(...)
    or `...` replaced by a SUBST_MARK placeholder; [(the command owning a heredoc, body, delimiter
    quoted?)]; [(substitution text, in command position?)]). `<<` inside quotes or arithmetic is
    no heredoc; a heredoc or substitution inside "$(...)" still counts; `$(` in single quotes is
    literal."""
    out, heredocs, substs, pending, stack, seg_stack = [], [], [], [], [], []
    i, n, nsub, seg = 0, len(text), 0, 0     # nsub: open $( and `; seg: start of the command
    sub_start = sub_pos = sub_kind = None
    glued, steps = -1, 0                     # glued: just after a $(...) or $((...)) ended
    while i < n:
        steps += 1
        if not steps & 0x3FFF and deadline is not None and time.monotonic() > deadline:
            raise _TooComplex("a command too large to check in time")
        c = text[i]
        ctx = stack[-1] if stack else None
        in_sub = nsub > 0
        opener = None
        if ctx == "'":
            if c == "'":
                stack.pop()
        elif ctx in ("A", "a"):                # arithmetic: only $(...) and parentheses count
            if text.startswith("$(", i) and not text.startswith("$((", i):
                opener = "$("
            elif c == "(":
                stack.append("a")
            elif c == ")" and ctx == "a":
                stack.pop()
            elif ctx == "A" and text.startswith("))", i):
                stack.pop()
                if not in_sub:
                    out.append("))")
                i += 2
                glued = i
                continue
        elif ctx == '"':
            if c == "\\" and i + 1 < n:
                if text[i + 1] != "\n" and not in_sub:    # backslash-newline: a continuation
                    out.append(text[i:i + 2])
                i += 2
                continue
            if c == '"':
                stack.pop()
            elif text.startswith("$((", i):
                stack.append("A")
                if not in_sub:
                    out.append("$((")
                i += 3
                continue
            elif text.startswith("$(", i):
                opener = "$("
            elif c == "`":
                opener = "`"
        else:                                  # the shell reads code here (None, "$", "(", "`")
            if c == "\\" and i + 1 < n:
                if text[i + 1] != "\n" and not in_sub:
                    out.append(text[i:i + 2])
                i += 2
                continue
            if c == "#" and (i == 0 or text[i - 1] in " \t\n;&|(<>"
                             or (text[i - 1] == ")" and glued != i)):   # a comment
                j = text.find("\n", i)
                i = n if j < 0 else j
                continue
            if c == "$" and text.startswith("$'", i):    # $'...': decoded into plain quotes
                m = ANSI_C_RE.match(text, i)
                if m:
                    if not in_sub:
                        out.append("'%s'" % _c_unescape(m.group(1)).replace("'", "'\"'\"'"))
                    i = m.end()
                    continue
            if c in "'\"":
                stack.append(c)
            elif text.startswith("$((", i) or (text.startswith("((", i)
                                               and _at_command_start(text, i)):
                stack.append("A")
                w = "$((" if c == "$" else "(("
                if not in_sub:
                    out.append(w)
                i += len(w)
                continue
            elif text.startswith("$(", i):
                opener = "$("
            elif c in "<>" and text[i + 1:i + 2] == "(" and text[i - 1:i] != c:
                opener = c + "("                   # process substitution <(...) >(...)
            elif c == "(" and ctx in ("$", "("):   # a subshell inside a substitution
                stack.append("(")
            elif c == ")" and ctx == "(":
                stack.pop()
            elif (c == ")" and ctx == "$") or (c == "`" and ctx == "`"):
                stack.pop()
                nsub -= 1
                seg = seg_stack.pop() if seg_stack else 0
                if not nsub:                   # an outermost substitution closed
                    inner = text[sub_start:i]
                    if sub_kind == "`":        # \` \$ \\ are one level of escaping
                        inner = re.sub(r"\\([\\`$])", r"\1", inner)
                    substs.append((inner, sub_pos))
                    out.append(SUBST_MARK % (len(substs) - 1))
                i += 1
                glued = i
                continue
            elif c == "`":
                opener = "`"
            elif c == "<" and text.startswith("<<", i) and not text.startswith("<<<", i) \
                    and (i == 0 or text[i - 1] != "<"):
                m = HEREDOC_OP_RE.match(text, i)
                if m:
                    if len(pending) >= MAX_HEREDOCS_PER_LINE:
                        raise _TooComplex("more than %d heredocs on one line"
                                          % MAX_HEREDOCS_PER_LINE)
                    pending.append((m.group(3) or m.group(5), bool(m.group(2) or m.group(4)),
                                    _heredoc_owner(text, seg, i), m.end()))
                    if not in_sub:
                        out.append(" ")
                    i = m.end()
                    continue
            elif c == "\n" and pending:        # the bodies start on the next line
                eol = i
                i += 1
                for delim, quoted, before, op_end in pending:
                    after = re.split(r";|&&|\|\||(?<![<>])&(?![>&])",
                                     text[op_end:min(eol, op_end + 512)])[0]
                    body, end_re = [], re.compile(r"[ \t]*%s[ \t]*(?=\)|\Z)" % re.escape(delim))
                    while i < n:
                        j = text.find("\n", i)
                        j = n if j < 0 else j
                        m = end_re.match(text, i, j)
                        if m:
                            i = m.end() if m.end() < j else j + 1
                            break
                        body.append(text[i:j])
                        i = j + 1
                    heredocs.append((before + " " + after, "\n".join(body), quoted))
                pending, seg = [], i
                if not in_sub:
                    out.append("\n")
                continue
            if c in ";|()\n" or (c == "&" and text[i - 1:i] not in ("<", ">")
                                   and text[i + 1:i + 2] != ">"):     # not 2>&1, &>
                seg = i + 1
        if opener:
            if not in_sub:
                sub_start, sub_kind = i + len(opener), opener
                before = text[max(seg, i - 256):i]
                sub_pos = _script_position(before) if opener == "<(" else \
                    False if opener == ">(" else _command_position(before)
            seg_stack.append(seg)
            seg = i + len(opener)
            stack.append("`" if opener == "`" else "$")
            nsub += 1
            i += len(opener)
            continue
        if not in_sub:
            out.append(c)
        i += 1
    if nsub and sub_start is not None:         # unterminated: the rest is the substitution
        substs.append((text[sub_start:], sub_pos))
        out.append(SUBST_MARK % (len(substs) - 1))
    return "".join(out), heredocs, substs


def _restorer(substs):
    """Put the substitutions of one _lex call back into words taken from its text."""
    def restore(s):
        if "\x00" not in s:
            return s
        return SUBST_MARK_RE.sub(lambda m: "$(%s)" % substs[int(m.group(1))][0]
                                 if int(m.group(1)) < len(substs) else "", s)
    return restore


def _printf(args):
    """What `printf FORMAT ARGS...` prints (%s-style directives; the format repeats for extra
    arguments), for reading the output of $(printf 'git %s' push) as a command."""
    while args and args[0].startswith("-") and args[0] != "--":
        args = args[2:] if args[0] == "-v" else args[1:]
    if args[:1] == ["--"]:
        args = args[1:]
    if not args:
        return ""
    fmt, vals, out = _c_unescape(args[0]), list(args[1:]), []
    directive = re.compile(r"%[-+ #0]*\d*(?:\.\d+)?([a-zA-Z%])")
    for _ in range(64):
        used = [False]

        def sub(m):
            if m.group(1) == "%":
                return "%"
            used[0] = True
            return vals.pop(0) if vals else ""
        out.append(directive.sub(sub, fmt))
        if not vals or not used[0]:
            break
    return "".join(out)


def _raw_substs(s):
    """$(...) and `...` in an unquoted heredoc body (quotes are text there; \\$ and \\` are not
    substitutions)."""
    found, i, n = [], 0, len(s)
    while i < n:
        if s[i] == "\\":
            i += 2
        elif s.startswith("$(", i):
            depth, j = 1, i + 2
            while j < n and depth:
                depth += {"(": 1, ")": -1}.get(s[j], 0)
                j += 1
            found.append(s[i + 2:j - 1] if depth == 0 else s[i + 2:])
            i = j
        elif s[i] == "`":
            j = s.find("`", i + 1)
            j = n if j < 0 else j
            found.append(s[i + 1:j])
            i = j + 1
        else:
            i += 1
    return found


def _heredoc_runs_code(owner):
    """Whether the command that owns a heredoc (or a later stage of its pipeline) reads the body
    as commands: a shell, eval or ssh, or `source /dev/stdin`."""
    if re.match(r"\s*(?:while|until|for|select|if|case)\b|\s*[{(]", owner):
        # a compound command: its stdin reaches every command in it; look at command words only
        for part in re.split(r";|&&|\|\||\||\n|[{}()]|(?<![\w-])(?:do|then|else|elif)(?![\w-])",
                             owner):
            words = [w for w in part.split() if not ASSIGN_RE.match(w)]
            if not words or words[0] in ("for", "select", "case", "done", "fi", "esac"):
                continue
            while words and words[0] in PREFIX_WORDS | {"while", "until", "if", "!"}:
                words = words[1:]
            if words and (_base(words[0]) in HEREDOC_RUNNERS or (
                    words[0] in ("source", ".") and words[1:2] and words[1] in
                    ("/dev/stdin", "/dev/fd/0", "-"))):
                return True
        return False
    for stage in owner.split("|"):
        words = re.findall(r"[^\s;&()<>'\"`]+", stage)[:8]
        if any(_base(w) in HEREDOC_RUNNERS for w in words):
            return True
        if words[:1] in (["source"], ["."]) and set(words[1:2]) & {"/dev/stdin", "/dev/fd/0", "-"}:
            return True
    return False


def _rest(words, j, limit=256):
    """words[j:] up to the next command separator (at most `limit` words)."""
    k, end = j, min(len(words), j + limit)
    while k < end and not SEP_RE.match(words[k]):
        k += 1
    return words[j:k]


def _after_pipe(words, i):
    """words[i] is the command of a pipeline stage after `|` (past env, sudo, options, X=1)."""
    j = i - 1
    while j >= 0 and not SEP_RE.match(words[j]) and (
            words[j] in PREFIX_WORDS or words[j][:1] == "-" or _duration(words[j])
            or ASSIGN_RE.match(words[j]) or (j > 0 and words[j - 1] in PREFIX_VALUE_OPTS)):
        j -= 1
    return j >= 0 and words[j] in ("|", "|&")


def _duration(word):
    return bool(re.match(r"\d+(?:\.\d+)?[smhd]?\Z", word))


def _stage_head(stage):
    """The program a pipeline stage runs (past X=1, env/sudo/timeout and their options)."""
    k, n = 0, len(stage)
    while k < n:
        w = stage[k]
        if ASSIGN_RE.match(w) or w in PREFIX_WORDS or _duration(w):
            k += 1
        elif w[:1] == "-" and k > 0:
            k += 2 if w in PREFIX_VALUE_OPTS else 1
        else:
            return _base(w)
    return ""


def _skip_redirections(words, k, end):
    """Index of the first word at or after k that is not a redirection (`2>/dev/null`, `>log`)."""
    while k < end:
        if words[k].isdigit() and k + 1 < end and REDIR_OP_RE.match(words[k + 1]):
            k += 1
        elif REDIR_OP_RE.match(words[k]):
            k += 2
        else:
            break
    return k


def _base(word):
    return word.rsplit("/", 1)[-1]


def _pwsh_switch(arg):
    """(name, kind) of a pwsh switch spelled any way pwsh accepts (-c, -Comm, --command, /c)."""
    key = arg.strip()
    if key[:1] not in ("-", "/", "\u2013", "\u2014"):
        return None, None
    key = key[1:]
    if key[:1] == arg.strip()[:1] and key[:1] in ("-", "\u2013", "\u2014"):
        key = key[1:]
    key = key.split(":", 1)[0].lower()
    for name, shortest, kind in PWSH_SWITCHES:
        if len(key) >= len(shortest) and name.startswith(key):
            return name, kind
    return key, "flag"


def _pwsh_args(base, rest):
    """How pwsh/powershell reads its arguments: ("code", text), ("encoded", None),
    ("file", None) or (None, None) when it reads commands from stdin."""
    k = 0
    while k < len(rest):
        name, kind = _pwsh_switch(rest[k])
        if name is None:                       # a bare argument
            if base.startswith("pwsh"):
                return "file", None            # pwsh: a script file
            return "code", " ".join(rest[k:])  # Windows PowerShell: a command
        if kind in ("code", "encoded", "file"):
            colon = rest[k].partition(":")[2]
            code = " ".join(([colon] if colon else []) + rest[k + 1:])
            return kind, code
        k += 2 if kind == "value" and ":" not in rest[k] else 1
    return None, None


def _expansion(word):
    return "$" in word or "\x00" in word or "`" in word


class _Scan(object):
    """One detection run: which kinds to report ("push", "forge", "opaque"), a work budget and a
    deadline (a hook that times out does not block, so a slow check must deny instead)."""

    def __init__(self, want):
        self.want, self.budget = set(want), MAX_SCANS
        self.deadline = time.monotonic() + DEADLINE_S

    def hit(self, kind, what):
        if len(what) > 200:
            what = what[:197] + "..."
        return (kind, what) if kind in self.want else None

    def scan(self, command, depth=0):
        """First remote write in a shell command: (kind, what), or None."""
        if not isinstance(command, str):
            return None
        command = command.replace("\x00", "")
        bare = re.sub(r"['\"\\]", "", command)
        if not (TRIGGER_RE.search(EXPANSION_RE.sub("", bare)) or ESCAPE_RE.search(command)
                or OPAQUE_HINT_RE.search(bare)):
            return None                        # names no git/gh/tea/fj, even obfuscated
        self.budget -= 1
        if depth > MAX_NEST or self.budget < 0:
            return self.hit("opaque", "a command nested too deeply to check")
        if time.monotonic() > self.deadline:
            return self.hit("opaque", "a command too large to check in time")
        try:
            text, heredocs, substs = _lex(command, self.deadline)
        except _TooComplex as exc:
            return self.hit("opaque", str(exc))
        if len(text) > MAX_COMMAND:            # shlex below is not interruptible (~3 s a MB)
            return self.hit("opaque", "a command too large to check in time")
        for inner, cmd_pos in substs:
            found = self.scan(inner, depth + 1)
            if not found and cmd_pos:          # its output is run: `$(echo 'git push')`
                found = self.run_output(inner, depth + 1)
            if found:
                return found
        for owner, body, quoted in heredocs:
            if time.monotonic() > self.deadline:
                return self.hit("opaque", "a command too large to check in time")
            found = self.scan(body, depth + 1) if _heredoc_runs_code(owner) else None
            for inner in ([] if quoted or found else _raw_substs(body)):
                found = found or self.scan(inner, depth + 1)
            if found:
                return found
        return self.scan_words(self.words(text), depth, _restorer(substs))

    def run_output(self, inner, depth):
        """What a substitution prints, read as commands: its multi-word words (echo 'git push')
        and heredoc bodies (cat <<EOF)."""
        try:
            text, heredocs, substs = _lex(inner, self.deadline)
        except _TooComplex as exc:
            return self.hit("opaque", str(exc))
        restore = _restorer(substs)
        words = [restore(w) for w in self.words(text)]
        found = self.each_phrase(words, depth)
        if not found and words and _base(words[0]) == "printf":   # printf 'git %s' push
            found = self.each_phrase([_printf(words[1:])], depth)
        for _, body, _ in heredocs:
            found = found or self.scan(body, depth)
        return found

    @staticmethod
    def words(text):
        try:
            return _shell_words(text)
        except ValueError:                     # unbalanced quotes: the shell would refuse it too
            return LENIENT_RE.findall(text)

    def each_phrase(self, words, depth):
        """Scan every multi-word word as a command (text that a shell will read as code)."""
        for w in words:
            for phrase in dict.fromkeys((w, _c_unescape(w))):     # printf 'git push\n' | sh
                found = self.scan(phrase, depth) if re.search(r"\s", phrase) else None
                if found:
                    return found
        return None

    def scan_words(self, words, depth, restore=lambda s: s):
        n = len(words)
        ends = [n] * (n + 1)                   # ends[k]: the first separator at or after k
        for k in range(n - 1, -1, -1):
            ends[k] = k if SEP_RE.match(words[k]) else ends[k + 1]
        covered = stdin_done = stmt_start = 0  # covered, stdin_done: words already re-scanned
        cmd_pos, xargs_seen, head = True, False, None   # head: this simple command's program
        for i, w in enumerate(words):
            if not i % 512 and time.monotonic() > self.deadline:
                return self.hit("opaque", "a command too large to check in time")
            if SEP_RE.match(w):
                if w not in ("|", "|&", "(", ")"):
                    stmt_start, xargs_seen = i + 1, False
                cmd_pos, head = True, None
                continue
            base, found, end = _base(w), None, ends[i + 1]
            if "\x00" in w:                    # $(which python3) -c ...: the program it names
                m = re.match(r"\$\((?:which|command -v|type -p|whence -p)\s+(\S+)\)\Z", restore(w))
                base = _base(m.group(1)) if m else base
            here_cmd = cmd_pos
            if here_cmd and head is None and not (ASSIGN_RE.match(w) or w in PREFIX_WORDS):
                head = base
            cmd_pos = (cmd_pos and (bool(ASSIGN_RE.match(w)) or w in PREFIX_WORDS
                                    or (w[:1] == "-" and i > 0 and words[i - 1] in PREFIX_WORDS))
                       ) or w in EXEC_OPTS
            if head in DOC_COMMANDS:           # man git push, which gh, help push
                continue
            if base in ("xargs", "parallel"):
                xargs_seen = True
            if ASSIGN_RE.match(w):             # GIT_EDITOR='git push' git commit, export PAGER=...
                m = ENV_EXEC_RE.match(w)
                found = self.scan(restore(m.group(1)), depth + 1) if m else None
            elif base in PUSH_PROGRAMS and here_cmd:
                found = self.hit("push", base)       # not `ls .../git-push`
            elif base == "git":
                found = self.git(words, i, end, xargs_seen, depth, restore)
            elif w in PUSH_SUBCOMMANDS and i > 0 and _expansion(words[i - 1]) \
                    and self.was_command(words, i - 1):
                found = self.hit("opaque", "%s %s" % (restore(words[i - 1]), w))
            elif _expansion(base) and _base(EXPANSION_RE.sub("", SUBST_MARK_RE.sub("", w))) \
                    in PROGRAMS:
                found = self.hit("opaque", restore(w))     # g${X}it: spelled at run time
            if not found and base in FORGE_TREES:
                found = self.forge(base, words, i + 1, end, depth, xargs_seen)
            if not found and w == "<<<" and i + 1 < n:     # a here-string that becomes code
                stage = words[stmt_start:end]
                if any(_base(x) in SHELLS | STRING_RUNNERS | {"xargs", "source", "."}
                       for x in stage):
                    found = self.scan(restore(words[i + 1]), depth + 1)
            lbase = base.lower()
            if not found and base == "env":    # env -S 'git push': one string, split into words
                for k in range(i + 1, end):
                    x = words[k]
                    if x in ("-S", "--split-string") or x.startswith("--split-string="):
                        val = x.split("=", 1)[1] if "=" in x else " ".join(words[k + 1:end])
                        found = self.scan(restore(val), depth + 1)
                        break
                    if x.startswith("-S") and len(x) > 2:
                        found = self.scan(restore(x[2:] + " " + " ".join(words[k + 1:end])),
                                          depth + 1)
                        break
            if not found and lbase in ("start-process", "saps"):    # PowerShell
                args = [restore(x) for x in words[i + 1:end]
                        if not x.lower().startswith(("-argumentlist", "-filepath", "-wait",
                                                     "-nonewwindow"))]
                found = self.scan(" ".join(a.replace(",", " ") for a in args), depth + 1)
            runner = base in SHELLS or lbase in STRING_RUNNERS or base == "alias" \
                or INTERPRETER_RE.match(base)
            if not found and runner and i >= covered:
                # (a runner's arguments are this runner's business: later runners among them
                # are arguments too, or were re-scanned with them)
                covered, rest = end, [restore(x) for x in words[i + 1:end]]
                if base in SHELLS:
                    found = self.shell(base, rest, depth)
                elif lbase in STRING_RUNNERS:
                    found = self.scan(" ".join(rest), depth + 1) if rest else None
                elif base == "alias":
                    for x in rest:
                        found = found or self.scan(x.partition("=")[2], depth + 1)
                else:                          # python -c, node -e, deno eval, osascript -e
                    for k in range(1, len(rest)):
                        code_flag = CODE_FLAG_RE.match(rest[k - 1]) or (k == 1 and rest[0] == "eval")
                        if code_flag and EXEC_HINT_RE.search(rest[k]):
                            code = CODE_ARGS_KEY_RE.sub(" ", CODE_PUNCT_RE.sub(" ", rest[k]))
                            found = found or self.scan(code, depth + 1)
            if not found and i >= stdin_done and base in SHELLS | {"source", "."} \
                    and self.reads_stdin(words, i):
                stdin_done = i
                while stdin_done < n and not (SEP_RE.match(words[stdin_done])
                                              and words[stdin_done] not in ("|", "|&", "(", ")")):
                    stdin_done += 1
                found = self.each_phrase([restore(x) for x in words[stmt_start:stdin_done]],
                                         depth + 1)
                if not found and self.transformed_literal(words, stmt_start, i):
                    found = self.hit("opaque", "commands decoded into %s (%s)" % (
                        base, " ".join(restore(x) for x in words[stmt_start:i + 1])[:120]))
            if found:
                return found
        return None

    @staticmethod
    def transformed_literal(words, a, i):
        """A pipeline words[a:i] that starts from literal text (echo, printf, a here-string) and
        transforms it (base64 -d, rev, tr, sed ...) before a shell reads it."""
        stages, cur = [], []
        for x in words[a:i]:
            if x in ("|", "|&"):
                stages.append(cur)
                cur = []
            else:
                cur.append(x)
        stages.append(cur)
        heads = [_stage_head(st) for st in stages if st]
        literal = bool(heads) and (heads[0] in LITERAL_SOURCES or "<<<" in words[a:i])
        return literal and any(h not in PASS_THROUGH for h in heads if h)

    @staticmethod
    def was_command(words, j):
        """words[j] is the command name of its simple command (after separators, X=1, env ...)."""
        k = j - 1
        while k >= 0 and (ASSIGN_RE.match(words[k]) or words[k] in PREFIX_WORDS):
            k -= 1
        return k < 0 or bool(SEP_RE.match(words[k]))

    def shell(self, base, rest, depth):
        """sh/bash/zsh/pwsh ...: the -c (-Command) string, the positional arguments it expands
        ($1, $@), and a here-string it reads as commands."""
        if base in PWSH:
            return self.pwsh(base, rest, depth)
        code, k = self.shell_code(rest)
        if code is None:
            for j in range(len(rest) - 1):
                if rest[j] == "<<<":           # sh <<< 'git push'
                    return self.scan(rest[j + 1], depth + 1)
            return None
        found = self.scan(code, depth + 1)
        if not found and POSITIONAL_CMD_RE.search(code):      # sh -c '"$1"' _ 'git push'
            found = self.scan(" ".join(rest[k + 1:]), depth + 1)
        return found

    def pwsh(self, base, rest, depth):
        """pwsh/powershell: the -Command text (everything after it) or commands on stdin."""
        kind, code = _pwsh_args(base, rest)
        if kind == "encoded":
            return self.hit("opaque", "%s -EncodedCommand" % base)
        return self.scan(code, depth + 1) if kind == "code" and code != "-" else None

    @staticmethod
    def shell_code(rest):
        """(the command string of `sh -c STRING`, its index), or (None, index); option clusters
        like -lc, -ec, -xc count, and fish --command, pwsh -Command."""
        seen_c, k = False, 0
        while k < len(rest):
            x = rest[k]
            xl = x.lower()
            if xl.startswith("--command=") or xl.startswith("-command="):
                return x.split("=", 1)[1], k
            if x in ("-o", "+o", "-O", "+O", "--rcfile", "--init-file"):
                k += 2
                continue
            if xl in ("-command", "-c", "-commandwithargs", "-cwa"):
                seen_c, k = True, k + 1
                continue
            if x[:1] in "-+" and len(x) > 1:
                seen_c = seen_c or x == "--command" or (not x.startswith("--") and "c" in x[1:])
                k += 1
                continue
            return (x, k) if seen_c else (None, k)
        return None, k

    @staticmethod
    def reads_stdin(words, i):
        """sh/bash/source reading commands from a pipe, a redirect or a process substitution."""
        rest = _rest(words, i + 1)
        if _base(words[i]) in PWSH:            # pwsh -Command -, or no command or file at all
            kind, code = _pwsh_args(_base(words[i]), rest)
            if kind not in (None, "stdin") and code != "-":
                return False
        elif _base(words[i]) in SHELLS and _Scan.shell_code(rest)[0] is not None:
            return False
        first = next((x for x in rest if not x.startswith("-")), "")
        return _after_pipe(words, i) or first.startswith("<") or \
            first in ("/dev/stdin", "/dev/fd/0", "-")

    def git(self, words, i, end, xargs_seen, depth, restore):
        k, aliases = i + 1, {}
        while True:                            # global options (and redirections among them)
            k = _skip_redirections(words, k, end)
            if k >= end or not words[k].startswith("-"):
                break
            opt = words[k]
            if opt in GIT_OPTS_WITH_VALUE:
                val, k = (words[k + 1] if k + 1 < end else ""), k + 2
            else:
                opt, _, val = opt.partition("=")
                k += 1
            key, _, value = restore(val).partition("=")
            if opt == "--config-env" and GIT_EXEC_KEY_RE.match(key):
                return self.hit("opaque", "git --config-env " + restore(val))
            if opt == "-c":                    # git -c alias.p=push p, -c core.editor=...
                found = self.git_config_value(key, value, depth)
                if found:
                    return found
                if key.lower().startswith("alias."):
                    aliases[key[6:]] = value
        if k >= end:
            return self.hit("opaque", "xargs git (the subcommand comes from stdin)") \
                if xargs_seen else None
        sub = words[k]
        if sub in aliases:                     # -c alias.p='!sh' p -c 'git push': with its args
            body = aliases[sub]
            tail = " ".join(shlex.quote(restore(x)) for x in words[k + 1:min(end, k + 257)])
            found = self.scan((body[1:] if body.startswith("!") else "git " + body) + " " + tail,
                              depth + 1)
            if found:
                return found
        if sub in PUSH_SUBCOMMANDS:
            return self.hit("push", "git " + sub)
        if sub in PUSH_UNDER and PUSH_UNDER[sub] & set(words[k + 1:min(end, k + 6)]):
            return self.hit("push", "git %s %s" % (sub, "/".join(sorted(PUSH_UNDER[sub]))))
        args = [restore(x) for x in words[k + 1:min(end, k + 257)]]
        found = None
        if sub == "config":                    # defining an alias or editor that pushes
            for j in range(len(args) - 1):
                if GIT_EXEC_KEY_RE.match(args[j]) and not args[j + 1].startswith("-"):
                    found = found or self.git_config_value(args[j], args[j + 1], depth)
        elif sub == "submodule" and "foreach" in args[:3]:
            cmd = args[args.index("foreach") + 1:]
            while cmd and cmd[0] in ("--recursive", "--quiet", "-q", "--"):
                cmd = cmd[1:]
            found = self.scan(" ".join(cmd), depth + 1)
        elif sub == "rebase":
            for j, a in enumerate(args):
                code = args[j + 1] if a in ("-x", "--exec") and j + 1 < len(args) else \
                    a[7:] if a.startswith("--exec=") else a[2:] if a.startswith("-x") else None
                found = found or (self.scan(code, depth + 1) if code else None)
        elif sub == "bisect" and args[:1] == ["run"]:
            found = self.scan(" ".join(args[1:]), depth + 1)
        if found:
            return found
        if OPAQUE_SUB_RE.search(sub):
            return self.hit("opaque", "git " + restore(sub))
        return None

    def git_config_value(self, key, value, depth):
        """A config value that git runs as a command: alias bodies (`!cmd` or git arguments),
        editors, pagers, ssh commands, filters, credential helpers."""
        if not GIT_EXEC_KEY_RE.match(key):
            return None
        if key.lower().startswith("alias.") and not value.startswith("!"):
            return self.scan("git " + value, depth + 1)
        return self.scan(value.lstrip("!"), depth + 1)

    def forge(self, tool, words, start, end, depth, xargs_seen=False):
        """Walk the forge's command tree over words[start:end] (options skipped; unknown words,
        such as option values, numbers and branch names, are passed over)."""
        if "forge" not in self.want:
            return None
        for k in range(start, min(end, start + 64)):
            prev = words[k - 1] if k > start else ""
            if words[k] in ("--help", "-h") and not (prev[:1] == "-" and "=" not in prev
                                                     and prev not in HELP_BOOL_OPTS):
                return None                    # help, not `--body -h`
        root = node = FORGE_TREES[tool]
        path, extra, seen, prev = [tool], 0, 0, ""
        for k in range(start, end):
            a = words[k]
            if a.startswith("-"):
                prev = a
                continue
            seen += 1
            if seen > MAX_FORGE_WORDS:
                break
            nxt = node.get(a)
            if nxt is None:
                if node is root and _expansion(a) and not (prev[:1] == "-" and "=" not in prev):
                    return self.hit("opaque", "%s %s" % (tool, a))    # gh $CMD merge 3
                extra, prev = extra + 1, a
                continue
            path.append(a)
            if nxt == WRITE:
                return self.hit("forge", " ".join(path))
            if nxt == READ:
                return None
            if isinstance(nxt, tuple):
                return self.forge_special(nxt, words[k + 1:end], path, depth)
            node, extra, prev = nxt, 0, a
        if len(path) > 1 and extra >= 2 and node.get("*") == WRITE:
            return self.hit("forge", " ".join(path))
        if len(path) == 1 and xargs_seen:
            return self.hit("opaque", "xargs %s (the subcommand comes from stdin)" % tool)
        return None

    def forge_special(self, spec, rest, path, depth):
        what = " ".join(path)
        if spec[0] == "api":
            return self.hit("forge", what + " (write method)") if _api_writes(rest, *spec[1:]) \
                else None
        if spec[0] in ("if-flag", "unless-flag"):
            flagged = any(a in spec[1] or a.split("=", 1)[0] in spec[1] for a in rest)
            return self.hit("forge", what) if flagged == (spec[0] == "if-flag") else None
        if spec[0] == "gh-alias":              # gh alias set NAME EXPANSION [--shell]
            pos = [a for a in rest if not a.startswith("-")]
            if len(pos) < 2:
                return None
            exp = pos[1]
            if exp.startswith("!") or "--shell" in rest or "-s" in rest:
                return self.scan(exp.lstrip("!"), depth + 1)
            words = self.words(exp)
            return self.forge("gh", words, 0, len(words), depth + 1)
        return None


def _api_writes(args, method_opts, body_opts, value_opts):
    """gh api / tea api: a write unless the method is GET/HEAD (default GET; gh sends POST once a
    field or --input is given). GraphQL: a write when it carries a mutation."""
    method, body, positional, k = None, False, [], 0
    while k < len(args):
        a = args[k]
        name, eq, val = a.partition("=")
        if a == "--":
            positional.extend(args[k + 1:])
            break
        if a.startswith("--") and eq:
            method = val if name in method_opts else method
            body = body or name in body_opts
        elif a in method_opts:
            method, k = (args[k + 1] if k + 1 < len(args) else ""), k + 1
        elif a in body_opts:
            body, k = True, k + 1
        elif a in value_opts:
            k += 1
        elif a[:1] == "-" and a[:2] != "--" and len(a) > 2 and a[:2] in method_opts:
            method = a[2:].lstrip("=")           # -XPOST
        elif a[:1] == "-" and a[:2] != "--" and len(a) > 2 and a[:2] in body_opts:
            body = True                          # -fkey=value
        elif not a.startswith("-"):
            positional.append(a)
        k += 1
    if positional and positional[0].strip("/").lower() == "graphql":
        return any(re.search(r"\bmutation\b", a, re.I) for a in args)
    if method is not None:
        return method.strip().upper() not in ("GET", "HEAD", "OPTIONS")
    return body


def remote_write_in(command):
    """(kind, what) for the first remote write in a shell command — kind "push" (git push and
    friends), "forge" (gh/tea/fj writes) or "opaque" (a git or forge command decided only at run
    time) — else None."""
    return _Scan(("push", "forge", "opaque")).scan(command)


def git_push_in(command):
    """True when a shell command runs `git [global options] push` (or send-pack, lfs/subtree push)."""
    return bool(_Scan(("push",)).scan(command))


def forge_write_in(command):
    """True when a shell command writes to a forge through gh, tea or fj."""
    return bool(_Scan(("forge",)).scan(command))


def no_push_main(raw):
    try:
        ev = json.loads(raw)
        command = (ev.get("tool_input") or {}).get("command") if isinstance(ev, dict) else None
        tool = ev.get("tool_name") if isinstance(ev, dict) else None
    except (ValueError, AttributeError, RecursionError):
        command, tool = raw, None            # unreadable event: judge the raw text
    if tool == "PowerShell" and isinstance(command, str):
        command = re.sub(r"`(.)", r"\1", command)          # PowerShell's escape: g`it
    try:
        found = remote_write_in(command)
    except Exception as exc:                 # a parser bug: fail closed on git/gh/tea/fj commands
        text = str(command or "")
        if PUSH_RE.search(text):
            found = ("push", "git push")
        elif TRIGGER_RE.search(EXPANSION_RE.sub("", re.sub(r"['\"\\]", "", text))):
            deny(GUARD_FAIL_REASON % ("%s: %s" % (type(exc).__name__, exc))[:200])
        else:
            found = None
    if found:
        kind, what = found
        deny(FORGE_REASON % what if kind == "forge" else
             OPAQUE_REASON % what if kind == "opaque" else NO_PUSH_REASON)
    return 0


# ---------------------------------------------------------------- CLI
def print_policy():
    sys.stdout.write(json.dumps({"policy": POLICY, "leaves": LEAVES, "agents": AGENTS,
                                 "builtins": BUILTINS, "self_spawn": SELF_SPAWN,
                                 "blackcat_tools": sorted(BLACKCAT_TOOLS)}) + "\n")
    return 0


def self_test():
    problems = []
    known = set(AGENTS) | set(BUILTINS)
    if len(set(AGENTS)) != len(AGENTS):
        problems.append("AGENTS has duplicates")
    if set(POLICY) != set(AGENTS):
        problems.append("POLICY rows != AGENTS: %s" % sorted(set(POLICY) ^ set(AGENTS)))
    for parent, row in POLICY.items():
        for child in row:
            if child not in known or child == "blackcat":
                problems.append("%s -> unknown or forbidden child %s" % (parent, child))
        if len(set(row)) != len(row):
            problems.append("%s row has duplicates" % parent)
    empty = sorted(p for p, row in POLICY.items() if not row)
    if empty != sorted(LEAVES):
        problems.append("LEAVES %s != empty rows %s" % (sorted(LEAVES), empty))
    if set(POLICY.get("blackcat", [])) != set(AGENTS) - {"blackcat"}:
        problems.append("blackcat row must list every specialist")
    for never in ("blackcat", "orchestrator", GOD, "mlx-engineer", "cuda-engineer"):
        if never in SELF_SPAWN:
            problems.append("%s must not spawn copies of itself" % never)
    # Installed layout: <config>/hooks/agent_guard.py next to <config>/agents/*.md
    agents_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                              "agents")
    if os.path.isdir(agents_dir):
        missing = [a for a in AGENTS if not os.path.isfile(os.path.join(agents_dir, a + ".md"))]
        if missing:
            problems.append("agent files missing in %s: %s" % (agents_dir, " ".join(missing)))
    try:
        root = state_root()
        os.makedirs(root, exist_ok=True)
        probe = tempfile.mkdtemp(prefix=".self-test-", dir=root)
        try:
            with mutex(probe, "probe", timeout=1):
                if not create_excl(os.path.join(probe, "m")) or create_excl(
                        os.path.join(probe, "m")):
                    problems.append("O_EXCL marker semantics broken")
        finally:
            shutil.rmtree(probe, ignore_errors=True)
    except Exception as exc:  # report, do not crash
        problems.append("state dir %s not writable: %s" % (state_root(), exc))
    if problems:
        for p in problems:
            sys.stdout.write("agent_guard self-test: FAIL %s\n" % p)
        return 1
    sys.stdout.write("agent_guard self-test: ok\n")
    return 0


HANDLERS = {
    ("PreToolUse", "Agent"): on_agent,
    ("PreToolUse", "SendMessage"): on_send,
    ("PostToolUse", "Agent"): on_agent_done,
    ("PostToolUse", "TaskStop"): on_task_stop,
    ("PostToolUseFailure", "Agent"): on_agent_failed,
    ("PermissionDenied", "Agent"): on_agent_failed,
}
LIFECYCLE = {
    "SubagentStart": on_subagent_start,
    "SubagentStop": on_subagent_stop,
    "StopFailure": on_stop_failure,
    "UserPromptSubmit": on_prompt,
    "SessionStart": on_session_start,
}


def dispatch(ev):
    if ev.get("agent_id"):
        ev["agent_id"] = ident(ev["agent_id"])
    event, tool = ev.get("hook_event_name"), ev.get("tool_name") or ""
    handler = HANDLERS.get((event, tool)) or LIFECYCLE.get(event)
    if handler is None and event == "PreToolUse" and tool.startswith("mcp__computer-use__"):
        handler = on_screen
    if handler is None and event == "PreToolUse" and local_read_keys(tool) is not None:
        handler = on_local_read
    if handler is None:
        return
    d = sdir(ev.get("session_id"))
    log(d, ev)
    handler(ev, d)


def main(argv):
    if len(argv) > 1:
        if argv[1] == "--print-policy":
            return print_policy()
        if argv[1] == "--self-test":
            return self_test()
        if argv[1] == "image-limit":
            return image_limit_main(sys.stdin.read())
        if argv[1] == "no-push":
            return no_push_main(sys.stdin.read())
        if argv[1] == "blackcat-guard":
            raw = sys.stdin.read()
            try:
                blackcat_guard(raw)
            except SystemExit:
                raise
            except Exception as exc:
                guard_error("%s: %s" % (type(exc).__name__, exc))
            return 0
        sys.stderr.write("usage: agent_guard.py [--print-policy | --self-test | blackcat-guard | image-limit | no-push]\n")
        return 2
    raw = sys.stdin.read()
    try:
        ev = json.loads(raw)
        if not isinstance(ev, dict):
            raise ValueError("hook input is not a JSON object")
    except (ValueError, RecursionError) as exc:   # RecursionError: absurdly nested JSON
        # a tool call we can't read is denied (fail closed); other events only log
        if policy_on() and re.search(r'"hook_event_name"\s*:\s*"PreToolUse"', raw):
            guard_error("unparseable hook input (%s)" % type(exc).__name__)
        warn("unparseable hook input: %s" % type(exc).__name__)
        return 0
    try:
        dispatch(ev)
    except SystemExit:
        raise
    except Exception as exc:
        if ev.get("hook_event_name") == "PreToolUse" and policy_on():
            guard_error("%s: %s" % (type(exc).__name__, exc))
        warn("%s: %s" % (type(exc).__name__, exc))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
