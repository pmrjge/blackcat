#!/usr/bin/env python3
"""Behavior enforcement for the Claude Code multi-agent stack (stdlib only, Python 3.8+, POSIX).

Wired in settings.json (every event below) and, in `blackcat-guard` mode, in agents/blackcat.md. The
installer renders every hook command with an absolute interpreter path (never a pyenv/asdf shim):
a hook that cannot start is a non-blocking error in Claude Code, i.e. every gate silently open.
Reads the hook JSON on stdin.

  PreToolUse  every tool            `budget` mode: the prompt and session context-token budgets,
                                    and each subagent's MCP call cap (the tools below check both
                                    in this mode's place, first)
  PreToolUse  Agent                 spawn policy, copy rule, depth limit, fan-out caps (spawn
                                    lease), session copy cap, blackcat dispatch and step limits
                                    (atomic markers), god-coder singleton (pending lease), strip
                                    `model`, and drop a BlackCat `run_in_background: false` (its
                                    children run in the background: BLACKCAT_BACKGROUND)
  PreToolUse  SendMessage           resuming a finished agent follows the spawn policy (the caller's
                                    row, or its own child/parent), its parent's fan-out cap and the
                                    copy cap, and holds a resume reservation until it starts;
                                    resuming a finished god-coder takes the god-coder lock;
                                    blackcat's call is one of its steps (claimed with the
                                    reservation, both rolled back on a refusal)
  PreToolUse  mcp__computer-use__*  one agent on the screen at a time
  PreToolUse  Bash|Monitor|PowerShell  `no-push` mode: agents never push and never write to a
                                    forge (gh/tea/fj), in any form, also inside bash -c, eval, $(...)
                                    (absolute; not switched off by STACK_POLICY=off); the same hook
                                    also denies `--reveal` on mcp-headers/with-stack-env and
                                    `with-stack-env env|printenv` (real API keys in the transcript;
                                    the default output is redacted), `bash -x`/`sh -x`/`zsh -x` on
                                    install.sh or doctor.sh, and a Bash-level write, delete,
                                    rename or mode change (redirection, cp/mv/tee/sed -i, rm,
                                    find -delete, chmod, inline python/node code, ...) of a path
                                    already denied to Read/Edit/Write or of the hook state dir —
                                    the replacement for Claude Code's own protected-path check,
                                    which covers only Edit/Write and is skipped entirely in
                                    bypassPermissions mode; for code-reviewer, security-auditor,
                                    verifier, plan-reviewer and claude-code-guide it also holds
                                    Bash to read-only commands (READONLY_TYPES, _ReadOnly)
  PreToolUse  nmem_remember         web-reading agents (researcher, scout, browser-operator) don't
                                    write the shared memory
  PreToolUse  *                     `blackcat-guard --settings`: blackcat's own gate, also wired
                                    from settings.json (acts only when agent_type is blackcat)
  PreToolUse  local-file MCP tools  context-mode ctx_index, markitdown, docling, playwright: a path
                                    or file: URI argument is held to the Read deny rules (Claude Code
                                    cannot see inside MCP arguments)
  PostToolUse Agent                 drop the spawn lease; record child id/type/depth/parent (once,
                                    from the caller's own event) and, for "async_launched", the
                                    child as a live background child; confirm or release the
                                    god-coder lock
  SubagentStart / SubagentStop      registry bookkeeping (a start of a stopped agent is a resume:
                                    a live background child again, its resume reservation gone);
                                    confirm / release locks; a starting or stopped agent's own
                                    spawn leases are voided, and a stopped child's spawn lease too
  PostToolUse TaskStop, StopFailure mark the agent stopped and release its locks and leases (a
                                    stopped or failed subagent is not promised a SubagentStop)
  PostToolUseFailure / PermissionDenied (Agent)   roll back god-coder lease, blackcat marker and
                                    spawn lease
  UserPromptSubmit                  start the prompt token budget; prune blackcat markers of
                                    earlier prompts
  SessionStart                      startup|resume: clear locks, leases and blackcat markers, prune
                                    old session dirs; resume|fork: bring the token count up to date
                                    (settings.json's matcher must list all three)

Concurrency model (the user's spec): depth 4 below the main thread (blackcat -> L1 -> L2 -> L3 ->
L4; settings.json sets CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH=4, and the fallback here stays at
Claude Code's own default of 3); any agent whose row allows it may launch several children in ONE
message (they run concurrently); at most STACK_MAX_FANOUT running children per parent
(STACK_MAX_FANOUT_BY_TYPE per type; BlackCat: BLACKCAT_MAX_DISPATCH per prompt instead). Copies:
only the COPY_TYPES spawn copies of themselves, as the separate agent type `<type>-copy`, whose row
lists neither its base nor any copy (one generation, decided on agent_type alone); at most
STACK_MAX_SELF_FANOUT live `<type>-copy` agents per type in the whole session. Running children =
live spawn leases + resume reservations + live background children (see the fan-out section);
nothing is linked by guessing. Token budgets: see the token-budget section.

State: ${XDG_STATE_HOME:-~/.local/state}/claude-agent-stack/<session_id>/
  agents/<agent_id>.json  registry {type, depth, parent, parent_type, name, spawned, started,
                          stopped, transcript, bg, tool_use_id, resumed}
  names/<name>.json       {type, id} for agents spawned with a `name`
  fanout/<caller>/<tool_use_id>.json   spawn leases {type, caller, caller_type, ts}
  fanout/<parent>/resume-<agent>.json  resume reservations {type, caller, caller_type, resume, by,
                          ts}, counted like spawn leases
  budget.json             token counts {files: {path: {off, ino, keys}}, total, prompt_base,
                          prompt_id}
  mcp-calls/<agent_id>.json  MCP tool calls of one subagent's current run {calls, run (its
                          registry `started` stamp), type, cap, ts}
  blackcat/dispatch.<prompt>.<k>, blackcat/step.<prompt>.<k>   O_EXCL markers
  god-coder.lock, screen.lock  JSON, replaced atomically; transitions under flock(*.mutex)

Failure policy: an exception in a PreToolUse handler (or in blackcat-guard mode) denies the call
(fail closed); lifecycle events log to stderr and exit 0. The token budgets fail open: a transcript
or state that can't be read warns on stderr and allows the call. The escape hatch
(STACK_POLICY=off) is shown to the user in `systemMessage`, never to the model in the deny reason.

Citations `hooks.md:N` / `sub-agents.md:N` are line numbers in code.claude.com/docs/en/hooks.md and
sub-agents.md as fetched on 2026-09-28 (Claude Code 2.1.283).

Liveness: an agent counts as gone on SubagentStop, PostToolUse(TaskStop) or StopFailure; while it
waits for background children its own transcript is quiet, so idle rules look at the whole live
subtree (the agent's transcript and every live descendant's).

CLI: `agent_guard.py --print-policy` (JSON consumed by doctor.sh and tests/lint_agents.py),
`--self-test`, `--check-budget [transcript]` (doctor: the budgets still read real transcripts),
`blackcat-guard [--settings]` (PreToolUse hook of the blackcat main thread; --settings: the
settings.json wiring, which checks agent_type), `budget` (PreToolUse hook on every
tool: token budgets and the MCP call cap), `image-limit` (PreToolUse/PostToolUse hook that keeps images under
STACK_IMAGE_MAX_PX), `no-push` (PreToolUse Bash/Monitor/PowerShell hook that denies any git push or
forge write, a --reveal key print, `-x` tracing of install.sh/doctor.sh, a write to a protected
path, and for the read-only agent types any command outside the read-only allowlist), no argument
= event.

Knobs (env):
  STACK_POLICY=off        disable every deny and lock (bookkeeping and model strip continue)
  BLACKCAT_MAX_DISPATCH=8   blackcat Agent calls per user prompt (parallel fan-out of independent asks)
  BLACKCAT_DISPATCH_WINDOW_S=120  all blackcat dispatches for one prompt must start within this many
                          seconds of the first one (one parallel burst, not ad-hoc orchestration)
  BLACKCAT_MAX_STEPS=12     blackcat tool calls per user prompt, Agent dispatches included
  STACK_MAX_FANOUT=3      running + starting children per parent agent (0 = no cap); the main
                          thread has none (BLACKCAT_MAX_DISPATCH bounds BlackCat per prompt)
  STACK_MAX_FANOUT_BY_TYPE="orchestrator=10,god-coder=6,main-coder=6,ninja-coder=5,researcher=4,
                          planner=8,plan-reviewer=8" (DEFAULT_FANOUT_BY_TYPE)
                          per-type overrides of STACK_MAX_FANOUT
                          (type=N, separated by , ; or newlines; a copy type falls back to its base)
  STACK_MAX_SELF_FANOUT=2 live `<type>-copy` agents per copy type in the whole session (0 = no cap)
  STACK_LEASE_TTL_S=21600 ceiling on a spawn lease whose Agent call never reported back
  STACK_RESUME_TTL_S=120  a resume reservation whose agent never started (the SendMessage was
                          refused after this hook allowed it) stops counting after this
  STACK_FANOUT_IDLE_S=1800  a background child whose live subtree shows no activity for this long
                          no longer counts as running (settings.json ships 600)
  STACK_PROMPT_CTX_BUDGET=100000000   context tokens per human prompt, whole session tree (0 = off)
  STACK_SESSION_CTX_BUDGET=666000000  context tokens per session, whole session tree (0 = off)
  STACK_MAX_MCP_CALLS=64  MCP tool calls (mcp__*) per subagent per prompt (a spawn or a resume
                          starts a new count); an agent whose frontmatter maxTurns is lower
                          gets that instead (0 = off)
  GOD_SPAWNERS=orchestrator  parent types that may spawn god-coder ("main" = a main thread without
                          an agent type); the POLICY rows list it for the orchestrator only
  GOD_ONCE_PER_SESSION=1  at most one god-coder spawn per session (a SendMessage resume of it is the
                          same instance); 0 = only the one-at-a-time lock
  GOD_PENDING_TTL_S=120   an unconfirmed god-coder lease (spawn or resume) is reclaimable after this
  GOD_IDLE_S=900          a holder whose live subtree is idle this long is presumed gone
                          (settings.json ships 1800)
  GOD_LOCK_TTL_S=21600    hard ceiling on any god-coder lock
  SCREEN_LOCK_TTL_S=900   screen lock expiry
  STRIP_AGENT_MODEL=1     remove per-call `model` from Agent input
  BLACKCAT_BACKGROUND=1   drop `run_in_background: false` from the BlackCat main thread's Agent
                          calls, so its children never run in the foreground (0 = keep it)
  STACK_MAX_DEPTH         deny Agent from callers at this depth (default
                          CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH, else 3)
  STACK_GUARD_LOG=0       1 = append every raw event to <session>/guard.log (`budget` mode, which
                          sees every tool call: the tool name and ids only, never the input)
  STACK_IMAGE_MAX_PX=1919 image-limit mode: longest side of any image an agent sees or uploads
                          (0 = off)
  STACK_IMAGE_UPLOAD_TOOLS  image-limit mode: regex of more MCP tool names whose image-file
                          arguments get downscaled copies (the built-in list: UPLOAD_TOOLS)
  STACK_IMAGE_MAX_B64=4500000  image-limit mode: most base64 characters of one image sent to the
                          model (the API refuses more than 5 MB)
"""
import contextlib
import errno
import fcntl
import json
import os
import re
import stat
import sys
import time
# base64, shlex, shutil, struct, subprocess, tempfile and urllib.parse are imported where they are
# used: every tool call starts this script at least once, and they cost ~9 ms of start-up.

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
          "claude-code-guide", "browser-operator", "plan-reviewer", "image-director"]

# god-coder is spawned by the orchestrator only, once per session (GOD_SPAWNERS, GOD_ONCE_PER_SESSION):
# the last resort after ninja-coder, decided where the whole job is visible. No other row lists it.
_BLACKCAT_ROW = [a for a in AGENTS if a not in ("blackcat", "god-coder")]
_ACCEL_ROW = ["coder", "explore", "scout", "verifier", "code-reviewer", "mathematician",
              "mcp-broker", "ninja-coder"]

# Copies: a base type in COPY_TYPES spawns copies of itself only as its own `<type>-copy` agent
# type (install.sh renders agents/<type>-copy.md from agents/<type>.md). One generation is then a
# static rule on the caller's agent_type, which PreToolUse carries inside subagents
# (hooks.md:745-750): a copy's row never lists its base type or any copy. No other agent may spawn
# its own type.
COPY_TYPES = ["researcher", "coder"]
COPY_OF = {base: base + "-copy" for base in COPY_TYPES}          # base -> copy type
COPY_BASE = {copy: base for base, copy in COPY_OF.items()}       # copy type -> base

# parent agent_type -> child agent types it may spawn. Parents not listed are unrestricted.
POLICY = {
    "blackcat": list(_BLACKCAT_ROW),
    "orchestrator": [a for a in AGENTS if a not in ("blackcat", "orchestrator")] + ["explore"],
    "planner": ["scout", "explore", "claude-code-guide"],
    # Web-reading agents never reach browser-operator (the user's logged-in Chrome sessions): a
    # page they read could steer it. Only blackcat and orchestrator keep it (T1; the prompts' "May
    # spawn" lines match: .claude-work/stack-tighten/spawn-browser-operator.txt).
    "researcher": ["researcher-copy", "scout", "doc-specialist", "mathematician", "data-engineer",
                   "data-scientist", "mcp-broker"],
    "writer": ["scout", "researcher", "mathematician"],
    "mathematician": ["scout", "mcp-broker", "quantum-engineer"],
    "doc-specialist": ["scout", "mcp-broker"],
    "designer": ["image-director", "scout", "mcp-broker", "cg-artist"],
    "motion-designer": ["image-director", "designer", "scout", "mcp-broker", "cg-artist"],
    "coder": ["coder-copy", "explore", "scout"],
    "main-coder": ["coder", "explore", "scout", "verifier", "code-reviewer",
                   "security-auditor", "plan-reviewer", "mlx-engineer", "cuda-engineer",
                   "ml-engineer", "dl-engineer", "llm-engineer", "mcp-broker", "claude-code-guide",
                   "ninja-coder"],
    "ninja-coder": ["main-coder", "coder", "mathematician", "explore", "scout",
                    "verifier", "code-reviewer", "security-auditor", "researcher", "mlx-engineer",
                    "cuda-engineer", "ml-engineer", "dl-engineer", "llm-engineer", "mcp-broker",
                    "quantum-engineer"],
    "god-coder": ["coder", "main-coder", "ninja-coder", "mlx-engineer", "cuda-engineer",
                  "ml-engineer", "dl-engineer", "llm-engineer", "explore", "scout", "verifier",
                  "code-reviewer", "security-auditor", "mathematician", "researcher"],
    "mlx-engineer": list(_ACCEL_ROW),
    # browser-only ML environments (Kaggle notebooks, cloud GPU consoles) go through BlackCat or the
    # orchestrator, which keep browser-operator; these engineers read the web themselves (T1)
    "cuda-engineer": ["coder", "explore", "scout", "verifier", "code-reviewer", "mathematician",
                      "mcp-broker", "ninja-coder"],
    "devops-engineer": ["coder", "explore", "scout", "verifier", "security-auditor", "mcp-broker"],
    "data-engineer": ["coder", "explore", "scout", "verifier", "mathematician",
                      "data-scientist", "doc-specialist", "mcp-broker"],
    "frontend-engineer": ["coder", "explore", "scout", "verifier", "code-reviewer", "designer",
                          "image-director", "mcp-broker"],
    "ml-engineer": ["data-scientist", "data-engineer", "coder", "explore", "scout",
                    "verifier", "code-reviewer", "mathematician", "mcp-broker"],
    "dl-engineer": ["mlx-engineer", "cuda-engineer", "data-engineer", "coder",
                    "explore", "scout", "researcher", "verifier", "code-reviewer",
                    "mathematician", "mcp-broker", "ninja-coder"],
    "llm-engineer": ["mlx-engineer", "cuda-engineer", "dl-engineer",
                     "data-scientist", "coder", "explore", "scout", "researcher", "verifier",
                     "code-reviewer", "mathematician", "mcp-broker",
                     "claude-code-guide", "ninja-coder"],
    "data-scientist": ["data-engineer", "ml-engineer", "mathematician", "coder",
                       "explore", "scout", "verifier", "doc-specialist", "writer", "mcp-broker"],
    "claude-code-engineer": ["claude-code-guide", "scout", "explore", "verifier", "code-reviewer",
                             "mcp-broker"],
    # quantum computing and quantum-physics numerics; derivations stay with mathematician
    "quantum-engineer": ["mathematician", "coder", "explore", "scout",
                         "researcher", "verifier", "code-reviewer", "cuda-engineer", "mlx-engineer",
                         "mcp-broker", "ninja-coder"],
    "robotics-engineer": ["coder", "explore", "scout", "researcher",
                          "verifier", "code-reviewer", "mathematician", "dl-engineer",
                          "cuda-engineer", "mlx-engineer", "cg-artist", "mcp-broker",
                          "ninja-coder"],
    # a GUI agent (ZBrush, Substance, Houdini through computer use): no copies, one screen
    "cg-artist": ["image-director", "coder", "scout", "verifier", "mcp-broker"],
    "oracle": [], "scout": [], "code-reviewer": [], "verifier": [], "security-auditor": [],
    "mcp-broker": [], "claude-code-guide": [], "browser-operator": [],
    # a review or an image job is one bounded task: no delegation (planner keeps Agent)
    "plan-reviewer": [], "image-director": [],
}
# A copy's row: its base's row without the base type and without any copy type.
for _base, _copy in COPY_OF.items():
    POLICY[_copy] = [c for c in POLICY[_base] if c != _base and c not in COPY_BASE]
# Agents that may spawn copies of themselves (derived: the row lists the agent's copy type).
SELF_SPAWN = sorted(b for b, c in COPY_OF.items() if c in POLICY.get(b, []))

# Main-thread blackcat: delegation tools plus the main-thread-only features subagents never get
# (dynamic workflows, scheduled tasks, routines, push notifications, file hand-off, skills).
# ExitPlanMode: the main thread leaves plan mode with it (Desktop/Conductor/CLI plan mode).
# mcp__conductor__AskUserQuestion: Conductor disables AskUserQuestion and serves its own.
# Read, Grep, Glob: read-only looks (a file the user names, where a result landed) to route and
# relay well; every call counts against BLACKCAT_MAX_STEPS. Nothing that writes or runs.
BLACKCAT_TOOLS = {"Agent", "SendMessage", "AskUserQuestion", "mcp__conductor__AskUserQuestion",
                  "ExitPlanMode", "TaskStop", "ListAgents", "ToolSearch", "Skill", "Workflow",
                  "CronCreate", "CronDelete", "CronList", "ScheduleWakeup", "RemoteTrigger",
                  "PushNotification", "SendUserFile", "Read", "Grep", "Glob"}
# Reviewers and guides are read-only by role but hold Bash: their Bash runs read-only commands only
# (READONLY_REASON, _ReadOnly). STACK_POLICY=off lifts it with the other policy gates.
READONLY_TYPES = {"code-reviewer", "security-auditor", "verifier", "plan-reviewer", "claude-code-guide"}
# Agents that ingest web pages never write the shared memory (a page could plant "decisions" other
# agents recall later): their nmem_remember calls are refused (on_memory_write).
WEB_INGESTING_TYPES = {"researcher", "researcher-copy", "scout", "browser-operator"}
MEMORY_WRITE_TOOLS = re.compile(r"mcp__neural-memory__nmem_remember\Z")
# The only rows that may list browser-operator (self-test; T1)
BROWSER_SPAWNERS = {"blackcat", "orchestrator"}
STEP_LIMIT_REASON = ("BlackCat step limit (%d tool calls per prompt, dispatches included) reached. "
                     "Call no more tools: answer the user now with what you have, or say what is "
                     "still pending.")
GOD = "god-coder"
GOD_LOCK = "god-coder.lock"
GOD_ONCE = "god-coder.spawned"        # the session's one god-coder spawn (its Agent tool_use_id)
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
                        for a in AGENTS + list(COPY_BASE) + BUILTINS
                        + ["general-purpose", "fork", "plan", "claude", "statusline-setup"]}
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
    tmp = os.path.join(folder, ".tmp-%d-%s" % (os.getpid(), os.urandom(6).hex()))
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
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


def reg_put(d, aid, fields, clear=(), keep=(), resumed=None):
    """Drop `clear` keys, then merge `fields`; None values only fill absent keys, and `keep` keys
    are never overwritten once set. `resumed`: fields merged too when the record says the agent
    had stopped (read under the same lock)."""
    with mutex(d, "registry"):
        cur = reg_get(d, aid) or {}
        if resumed and cur.get("stopped"):
            fields = dict(fields, **resumed)
        for k in clear:
            cur.pop(k, None)
        for k, v in fields.items():
            if k in keep and cur.get(k) is not None:
                continue
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
    window = knob_int("BLACKCAT_DISPATCH_WINDOW_S", 120)
    first = first_marker_ts(d, "dispatch", pid, limit, now)
    return window > 0 and first is not None and now - first > window


# ---------------------------------------------------------------- fan-out caps and copies
# Running children of a parent = its live spawn leases + its live background children. Nothing
# links a child to a lease: SubagentStart names no parent (hooks.md:2349), so there is no guessing.
#   lease        fanout/<caller>/<tool_use_id>.json, taken by PreToolUse(Agent), dropped by the same
#                tool_use_id's PostToolUse, PostToolUseFailure or PermissionDenied (hooks.md:1585,
#                2004, 2207). For a foreground call that spans the child's whole run: PostToolUse
#                comes with status "completed" when the child is done (hooks.md:1751). Also
#                dropped when the child it spawned stops (its meta.json names the call: see
#                spawn_meta), voided when the caller starts (a resume: nothing of its old run is in
#                flight) or stops, at SessionStart, and after STACK_LEASE_TTL_S. Paths that fire
#                none of these (a deny rule, another hook's deny) keep it until then.
#   resume       fanout/<parent>/resume-<agent>.json, taken by PreToolUse(SendMessage) when it
#   reservation  resumes a finished agent (under the same mutex as the counts, so resumes sent in
#                one message are counted one by one), turned into the background child below by
#                that agent's SubagentStart, and void after STACK_RESUME_TTL_S if it never starts.
#                It belongs to the resumed agent, not to <parent>: voiding <parent>'s leases
#                leaves it alone.
#   background   registry entry with bg=true, written by PostToolUse status "async_launched" (a
#   child        background launch, or a foreground run moved to the background; hooks.md:1751,
#                1763), or by the SubagentStart of a stopped agent: a resume, which runs in the
#                background (hooks.md:2343, sub-agents.md:1102). Gone at SubagentStop, TaskStop,
#                StopFailure or SessionStart, or once its live subtree is idle STACK_FANOUT_IDLE_S.
# Lock order: the 'fanout' mutex, then 'registry' (reg_put); nothing takes them the other way.
# Running children per spawning agent, by task type (the one table; STACK_MAX_FANOUT_BY_TYPE in
# settings.json overrides it as a whole). Coordinators and the implementer escalation chain fan out
# widest: orchestrator 10 (a job of up to 10 independent tasks), god-coder and main-coder 6 (parallel
# work on disjoint modules of a large codebase plus a reviewer and a verifier), ninja-coder 5 (a
# mathematical core stays with it; racing approach, reviewer, verifier, mathematician, one coder);
# researcher 4 (its 2 session-wide copies plus 2 lookups). planner keeps 8 and plan-reviewer's entry
# is inert (it has no Agent tool). Every other agent: STACK_MAX_FANOUT.
DEFAULT_FANOUT_BY_TYPE = ("orchestrator=10,god-coder=6,main-coder=6,ninja-coder=5,researcher=4,"
                          "planner=8,plan-reviewer=8")
RESUME_PREFIX = "resume-"


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


def live_leases(d, now, caller=None):
    """[(caller folder, lease id, lease)] of the unexpired spawn leases and resume reservations
    of `caller` (of every caller when None). Leases older than STACK_LEASE_TTL_S, reservations
    older than STACK_RESUME_TTL_S, and unreadable files are removed."""
    root = os.path.join(d, "fanout")
    try:
        callers = [safe(caller)] if caller else os.listdir(root)
    except (FileNotFoundError, NotADirectoryError):
        return []
    ttl, rttl, out = knob_int("STACK_LEASE_TTL_S", 21600), knob_int("STACK_RESUME_TTL_S", 120), []
    for c in callers:
        try:
            entries = os.listdir(os.path.join(root, c))
        except (FileNotFoundError, NotADirectoryError):
            continue
        for f in entries:
            if f.startswith(".") or not f.endswith(".json"):
                continue
            path = os.path.join(root, c, f)
            rec = read_json(path)
            try:
                ts = float((rec or {}).get("ts") or 0)
            except (TypeError, ValueError):
                ts = 0.0
            limit = rttl if f.startswith(RESUME_PREFIX) else ttl
            if not rec or (limit > 0 and now - ts > limit):
                unlink(path)
                continue
            out.append((c, f[:-len(".json")], rec))
    return out


def bg_running(d, now, ev, reg, skip, parent=None, ctype=None):
    """Number of live background agents (bg, not stopped, subtree active within
    STACK_FANOUT_IDLE_S): the children of `parent`, or the agents of type `ctype`. `skip`: lease
    ids still live, never counted twice."""
    idle = knob_int("STACK_FANOUT_IDLE_S", 1800)
    n = 0
    for aid, rec in reg.items():
        if not rec.get("bg") or rec.get("stopped") or safe(rec.get("tool_use_id"), "") in skip:
            continue
        if parent is not None and rec.get("parent") != parent:
            continue
        if ctype is not None and norm(rec.get("type")) != ctype:
            continue
        last, _ = subtree_activity(d, aid, ev, reg)
        if idle > 0 and last and now - last > idle:
            continue
        n += 1
    return n


def running_children(d, caller, now, ev, reg):
    """Children of `caller` running or starting: its live leases plus its live background
    children."""
    leases = live_leases(d, now, caller)
    return len(leases) + bg_running(d, now, ev, reg, {lid for _, lid, _ in leases}, parent=caller)


def copies_running(d, ctype, now, ev, reg):
    """Session-wide number of `ctype` agents running or starting: leases for that type (any
    caller) plus live background agents of that type."""
    leases = [x for x in live_leases(d, now) if norm(x[2].get("type")) == ctype]
    return len(leases) + bg_running(d, now, ev, reg, {lid for _, lid, _ in leases}, ctype=ctype)


def parse_fanout_by_type(raw):
    """{type: cap} from "orchestrator=8,planner=8" (separators , ; or newline; spaces, quotes and
    any spelling of a type are fine). Malformed items are skipped with a warning."""
    out = {}
    for item in re.split(r"[,;\n]+", str(raw or "").strip().strip("'\"")):
        item = item.strip().strip("'\"")
        if not item:
            continue
        name, sep, value = item.rpartition("=")
        try:
            cap = int(value.strip())
        except ValueError:
            cap = -1
        if not sep or not name.strip() or cap < 0:
            warn_once("STACK_MAX_FANOUT_BY_TYPE: ignoring %r (expected type=N with N >= 0)" % item)
            continue
        out[norm(name)] = cap
    return out


def fanout_limit(caller, caller_type):
    """(cap on the running children of this caller, the knob that set it); 0 = no cap. A copy
    type falls back to its base type's entry. The main thread has no per-parent cap unless
    STACK_MAX_FANOUT_BY_TYPE names its agent: BlackCat is held to BLACKCAT_MAX_DISPATCH per
    prompt, and a new prompt is the user's own call."""
    raw = os.environ.get("STACK_MAX_FANOUT_BY_TYPE")
    by = parse_fanout_by_type(DEFAULT_FANOUT_BY_TYPE if raw is None else raw)
    for t in (caller_type, COPY_BASE.get(caller_type)):
        if t and t in by:
            return by[t], "STACK_MAX_FANOUT_BY_TYPE %s=%d" % (t, by[t])
    if caller == "main":
        return 0, None
    cap = knob_int("STACK_MAX_FANOUT", 3)
    return cap, "STACK_MAX_FANOUT=%d" % cap


def fanout_acquire(d, ev, caller, caller_type, child):
    """Check the caller's fan-out cap and the session's copy cap and, if they allow it, take a
    lease for this spawn, atomically (one session-wide mutex). Returns a denial reason, or None
    when the spawn may proceed."""
    limit, knob = fanout_limit(caller, caller_type)
    max_copies = knob_int("STACK_MAX_SELF_FANOUT", 2)
    copy = child in COPY_BASE and max_copies > 0
    tid = ev.get("tool_use_id")
    lease = {"type": child, "caller": caller, "caller_type": caller_type or None}
    if limit <= 0 and not copy:        # no cap to check: no lock, no registry scan (review #15)
        if tid:
            write_json_atomic(os.path.join(fanout_dir(d, caller), safe(tid) + ".json"),
                              dict(lease, ts=time.time()))
        return None
    with mutex(d, "fanout"):
        now = time.time()
        reg = load_registry(d)
        if limit > 0:
            n = running_children(d, caller, now, ev, reg)
            if n >= limit:
                return ("Fan-out limit: '%s' already has %d children running or starting (%s). "
                        "Wait for a task notification before spawning more, or do this part "
                        "yourself." % (caller_type or caller, n, knob))
        if copy:
            n = copies_running(d, child, now, ev, reg)
            if n >= max_copies:
                return ("Copy limit: %d %s agents are already running or starting in this "
                        "session (STACK_MAX_SELF_FANOUT=%d). Wait for one to finish, or do this "
                        "part yourself." % (n, child, max_copies))
        if tid:
            write_json_atomic(os.path.join(fanout_dir(d, caller), safe(tid) + ".json"),
                              dict(lease, ts=now))
    return None


def fanout_release(d, caller, tool_use_id):
    if tool_use_id:
        unlink(os.path.join(fanout_dir(d, caller), safe(tool_use_id) + ".json"))


def own_lease_files(d, caller):
    """Paths of `caller`'s own spawn leases. The resume reservations in its folder are other
    resumes of its children, not calls of its own, and are left out."""
    folder = fanout_dir(d, caller)
    try:
        entries = os.listdir(folder)
    except (FileNotFoundError, NotADirectoryError):
        return []
    return [os.path.join(folder, f) for f in entries
            if f.endswith(".json") and not f.startswith((".", RESUME_PREFIX))]


def void_leases(d, caller):
    """Drop every spawn lease of `caller`: it stopped (or starts again), and its pending Agent
    calls with it."""
    if not own_lease_files(d, caller):      # look before taking the lock (review #15)
        return
    with mutex(d, "fanout"):
        for path in own_lease_files(d, caller):
            unlink(path)


def resume_reservations(d, aid):
    """Paths of every resume reservation for agent `aid`, whichever parent folder holds it."""
    root = os.path.join(d, "fanout")
    try:
        callers = os.listdir(root)
    except (FileNotFoundError, NotADirectoryError):
        return []
    name = RESUME_PREFIX + safe(aid) + ".json"
    return [p for p in (os.path.join(root, c, name) for c in callers) if os.path.isfile(p)]


def copy_rule_violation(parent_type, child):
    """One generation of copies, decided on the caller's own agent_type alone (no registry, so
    no timing): a copy spawns neither its base type nor any copy."""
    base = COPY_BASE.get(parent_type)
    if base and (child == base or child in COPY_BASE):
        return ("Copies cannot spawn copies: %s may not spawn %s. Do this part yourself or "
                "return STATUS: partial listing what is left." % (parent_type, child))
    return None


def spawn_meta(ev, aid):
    """Claude Code's own record of a subagent's spawn, <session>/subagents/agent-<id>.meta.json:
    {agentType, spawnDepth, toolUseId (the Agent call), parentAgentId (absent at depth 1), ...}
    as observed on 2.1.283. Not a documented interface: {} when absent or unreadable, and used
    only where a missing file costs nothing (a depth the registry lacks, an early lease drop)."""
    folders = []
    atp = ev.get("agent_transcript_path")
    if isinstance(atp, str) and atp.strip():
        folders.append(os.path.dirname(os.path.expanduser(atp.strip())))
    files = transcript_files(ev)
    if files and files[1] not in folders:
        folders.append(files[1])
    for folder in folders:
        meta = read_json(os.path.join(folder, "agent-%s.meta.json" % safe(aid)))
        if meta is not None:
            return meta
    return {}


def meta_depth(d, ev, aid):
    """The caller's depth from its meta.json `spawnDepth` (spawn_meta), when the registry has
    none (a foreground child's PostToolUse comes only when it is done). Read only at the agent's
    own PreToolUse(Agent), and used only for the depth check (review #1 iii)."""
    dep = spawn_meta(ev, aid).get("spawnDepth")
    if not isinstance(dep, int) or isinstance(dep, bool) or not 0 < dep < 64:
        return None
    reg_put(d, aid, {"depth": dep})
    return dep


def drop_spawn_lease(d, ev, aid):
    """A child that stopped no longer runs under the Agent call that spawned it: drop that call's
    lease, whose PostToolUse may never come (a cancelled call). The call is known only from the
    child's meta.json (toolUseId, parentAgentId; no parent = the main thread); without it nothing
    is guessed."""
    meta = spawn_meta(ev, aid)
    tid, parent = meta.get("toolUseId"), meta.get("parentAgentId")
    if isinstance(tid, str) and tid.strip():
        fanout_release(d, ident(parent.strip()) if isinstance(parent, str) and parent.strip()
                       else "main", tid.strip())


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


GOD_ONCE_REASON = (
    "One god-coder per session: this session already spawned one, and god-coder is the last "
    "resort. SendMessage that god-coder to continue its work, or return STATUS: partial naming "
    "what is left.")


def god_spawners():
    """Parent types allowed to spawn god-coder (GOD_SPAWNERS, default the orchestrator only;
    "main" = a main thread without an agent type)."""
    raw = os.environ.get("GOD_SPAWNERS", "orchestrator")
    return {norm(x) for x in re.split(r"[,\s]+", raw) if x.strip()}


def god_claim_session(d, ev):
    """At most one god-coder spawn per session (GOD_ONCE_PER_SESSION=1, the default): the marker's
    path when this spawn claimed the session's slot, False when another spawn holds it, None when
    the rule is off. The marker holds the Agent call's tool_use_id, so a failed call frees it; a
    SendMessage resume of that god-coder is the same instance and needs no slot."""
    if os.environ.get("GOD_ONCE_PER_SESSION", "1").strip() == "0":
        return None
    path = os.path.join(d, GOD_ONCE)
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        return False
    os.write(fd, str(ev.get("tool_use_id") or "").encode())
    os.close(fd)
    return path


def god_unclaim_session(d, ev):
    """A god-coder Agent call that failed or was refused never ran: free the session's slot."""
    path = os.path.join(d, GOD_ONCE)
    try:
        with open(path) as f:
            holder = f.read().strip()
    except OSError:
        return
    if holder and holder == str(ev.get("tool_use_id") or ""):
        unlink(path)


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
    max_dispatch = knob_int("BLACKCAT_MAX_DISPATCH", 8)
    max_steps = knob_int("BLACKCAT_MAX_STEPS", 12)

    if policy_on():
        is_blackcat = not aid and parent == "blackcat"
        # 1. pure checks (the token budget ran before this handler: dispatch())
        if str(ti.get("isolation") or "").strip().lower() == "remote":
            deny("Remote isolation runs the agent in a cloud session that does not load this "
                 "stack's hooks (no spawn policy, depth, fan-out, god-coder or screen locks). Omit "
                 "isolation or use isolation: \"worktree\".")
        why = copy_rule_violation(parent, child)
        if why:
            deny(why)
        if child == GOD and (parent or "main") not in god_spawners():
            deny("Spawn policy: only the orchestrator spawns god-coder (once per session, the last "
                 "resort after ninja-coder). Return STATUS: partial with NEXT: god-coder and a "
                 "dossier (goal, constraints, what failed and why, logs, minimal repro).")
        if parent in POLICY and child not in POLICY[parent]:
            deny("Spawn policy: '%s' may not spawn '%s'. Allowed: %s. Return STATUS: partial "
                 "with NEXT naming the agent you need."
                 % (parent, child, ", ".join(POLICY[parent]) or "none"))
        depth, limit = caller_depth(d, ev), max_depth()
        if depth is None and aid:
            depth = meta_depth(d, ev, aid)
        if depth is not None and depth >= limit:
            deny("Depth limit: '%s' runs at depth %d and agents at depth >= %d cannot spawn. "
                 "Do the work yourself or return STATUS: partial with NEXT naming the agent."
                 % (parent or caller, depth, limit))
        if is_blackcat:
            if markers_full(d, "dispatch", pid, max_dispatch):
                deny("BlackCat dispatch limit (%d per prompt) reached. Use SendMessage to resume an "
                     "agent, or tell the user what is missing; work that needs coordination goes "
                     "to ONE orchestrator call." % max_dispatch)
            if dispatch_window_closed(d, pid, max_dispatch, time.time()):
                deny("BlackCat already dispatched for this prompt: parallel dispatches must go out "
                     "together in one message. Relay the results as they arrive; follow-ups go "
                     "through SendMessage, and multi-step work goes to the orchestrator.")
            if markers_full(d, "step", pid, max_steps):
                deny(STEP_LIMIT_REASON % max_steps)
        # 2. side effects, each rolled back if a later step denies or fails
        leased, took_god, claimed, stepped, god_mark = False, False, None, None, None

        def rollback():
            if god_mark:
                unlink(god_mark)
            if stepped:
                unlink(stepped)
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
                god_mark = god_claim_session(d, ev)
                if god_mark is False:
                    god_mark = None
                    rollback()
                    deny(GOD_ONCE_REASON)
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
                # BLACKCAT_MAX_STEPS counts every blackcat tool call, dispatches included; this
                # one is counted here, with its lease and dispatch marker, as one decision
                # (blackcat-guard counts the other tools).
                stepped = claim_marker(d, "step", pid, max_steps)
                if not stepped:
                    rollback()
                    deny(STEP_LIMIT_REASON % max_steps)
            record_name(d, ti, child, caller)
        except SystemExit:
            raise
        except Exception:
            rollback()
            raise
    else:
        record_name(d, ti, child, caller)

    # 3. input rewrites: models are fixed by agent definitions, and BlackCat never blocks on a child
    new_input, why = dict(ti), []
    if os.environ.get("STRIP_AGENT_MODEL", "1") == "1" and "model" in ti:
        new_input.pop("model")
        why.append("model override removed; agent definition decides")
    if blackcat_foreground(ev, ti):
        new_input.pop("run_in_background")
        why.append("BlackCat dispatches run in the background")
    if why:
        emit({"hookSpecificOutput": {"hookEventName": "PreToolUse",
                                     "permissionDecision": "allow",
                                     "permissionDecisionReason": "; ".join(why),
                                     "updatedInput": new_input}})


def blackcat_foreground(ev, ti):
    """True when the BlackCat main thread asks for a foreground child (`run_in_background` false,
    which the Agent tool offers only where fork mode is off: Claude Desktop, Conductor and the other
    Agent SDK apps, `claude -p`). A foreground child blocks the main thread for its whole run: the
    app shows nothing, and the next dispatch waits for it. Dropping the key launches the child in
    the background, the default when the parameter is omitted (sub-agents.md, "Run subagents in
    foreground or background"); its result comes back as a notification. Subagents keep their
    foreground calls: in those apps a subagent does not wait for its background children.
    BLACKCAT_BACKGROUND=0 turns this off."""
    if os.environ.get("BLACKCAT_BACKGROUND", "1").strip() == "0":
        return False
    if ev.get("agent_id") or norm(ev.get("agent_type")) != "blackcat":
        return False
    if "run_in_background" not in ti:
        return False
    flag = ti.get("run_in_background")
    return flag is not True and str(flag).strip().lower() not in ("true", "1", "yes")


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


def resume_reserve(d, ev, target_id, ttype):
    """Resuming a finished agent starts a background run of it under its registry parent
    (sub-agents.md:1102), so it counts against that parent's fan-out cap and, for a copy, against
    the session's copy cap, like a new spawn. The check and a reservation
    fanout/<parent>/resume-<target>.json are one step under the 'fanout' mutex, so resumes sent in
    one message are counted one by one. The target's SubagentStart turns the reservation into a
    live background child (on_subagent_start); one that never starts (the call was refused after
    this hook) stops counting after STACK_RESUME_TTL_S. Returns (denial reason or None, the
    reservation this call wrote or None)."""
    rec = reg_get(d, target_id) if target_id else None
    if not rec or not rec.get("stopped"):      # the registry decides before any lock (review #15)
        return None, None
    owner = rec.get("parent") or ev.get("agent_id") or "main"
    owner_type = norm(rec.get("parent_type")) or None
    limit, knob = fanout_limit(owner, owner_type)
    max_copies = knob_int("STACK_MAX_SELF_FANOUT", 2)
    copy = ttype in COPY_BASE and max_copies > 0
    if limit <= 0 and not copy:
        return None, None
    rid = RESUME_PREFIX + safe(target_id)
    with mutex(d, "fanout"):
        now = time.time()
        if not (reg_get(d, target_id) or {}).get("stopped"):
            return None, None       # it started meanwhile: now a message to a running agent
        if rid in {lid for _, lid, _ in live_leases(d, now, owner)}:
            return None, None       # already resumed in this burst: one run, one reservation
        reg = load_registry(d)
        if limit > 0:
            n = running_children(d, owner, now, ev, reg)
            if n >= limit:
                return ("Fan-out limit: resuming '%s' would give '%s' more than %d running "
                        "children (%s). Wait for a task notification, then resume it."
                        % (target_id, owner_type or owner, limit, knob)), None
        if copy and copies_running(d, ttype, now, ev, reg) >= max_copies:
            return ("Copy limit: resuming '%s' would make more than %d %s agents run in this "
                    "session (STACK_MAX_SELF_FANOUT=%d). Wait for one to finish."
                    % (target_id, max_copies, ttype, max_copies)), None
        path = os.path.join(fanout_dir(d, owner), rid + ".json")
        write_json_atomic(path, {"type": ttype, "caller": owner, "caller_type": owner_type,
                                 "resume": target_id, "by": ev.get("agent_id") or "main",
                                 "ts": now})
    return None, path


def on_send(ev, d):
    if not policy_on():
        return
    ti = tool_input(ev)
    to = None
    for key in ("to", "recipient", "agentId", "agent_id", "name"):
        if isinstance(ti.get(key), str) and ti[key].strip():
            to = ti[key].strip()
            break
    # BlackCat's SendMessage is one of its BLACKCAT_MAX_STEPS. It is counted here, not in
    # blackcat-guard (which runs in parallel for the same call and leaves SendMessage to this hook,
    # as it does Agent), so the step and the resume reservation are one decision: a call refused
    # at the step limit holds no slot, and a refused resume spends no step.
    is_blackcat = not ev.get("agent_id") and norm(ev.get("agent_type")) == "blackcat"
    pid, max_steps = prompt_key(ev), knob_int("BLACKCAT_MAX_STEPS", 12)
    if is_blackcat and markers_full(d, "step", pid, max_steps):
        deny(STEP_LIMIT_REASON % max_steps)
    target_id, ttype, tname = resolve_target(d, to) if to else (None, None, None)
    why = send_policy_violation(d, ev, target_id, ttype)
    if why:
        deny(why)
    why, reserved = resume_reserve(d, ev, target_id, ttype)
    if why:
        deny(why)
    stepped = None

    def rollback():
        if stepped:
            unlink(stepped)
        if reserved:            # a refused resume holds no slot
            unlink(reserved)

    try:
        if is_blackcat:
            stepped = claim_marker(d, "step", pid, max_steps)
            if not stepped:
                rollback()
                deny(STEP_LIMIT_REASON % max_steps)
        if ttype == GOD:
            blocking = god_resume(d, ev, to, target_id, tname)
            if blocking:
                rollback()
                deny(god_busy_reason(blocking))
    except SystemExit:
        raise
    except Exception:
        rollback()
        raise


def god_resume(d, ev, to, target_id, tname):
    """Resuming a finished god-coder takes the god-coder lock ('resumed'). Returns the blocking
    lock, or None when the call may go ahead."""
    holder = target_id or "name:" + norm(to)
    caller = ev.get("agent_id") or "main"
    with mutex(d, "god"):
        now = time.time()
        lock = read_json(god_path(d))
        if lock and (lock.get("holder") == holder
                     or holder_matches(d, lock.get("holder"), target_id, tname)):
            return None  # talking to the current holder
        if lock and not god_stale(d, lock, ev, now):
            return lock
        write_json_atomic(god_path(d), {"state": "resumed", "holder": holder, "by": caller,
                                        "ts": now})
    return None


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


def _deny_spec_files(bases):
    """(path, anchors for `/x`) for every settings file whose deny rules apply here."""
    conf = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    files = [(os.path.join(conf, "settings.json"), (conf,))]
    for b in bases:
        for name in ("settings.json", "settings.local.json"):
            files.append((os.path.join(b, ".claude", name), (b, os.path.join(b, ".claude"))))
    seen = set()
    for path, anchors in files:
        if path not in seen:
            seen.add(path)
            yield path, anchors


def deny_specs_for(tools, bases):
    """(spec, anchors for `/x`) for every deny rule of the given tool names (e.g. {"Read"} or
    {"Edit", "Write"})."""
    specs = []
    for path, anchors in _deny_spec_files(bases):
        rules = ((read_json(path) or {}).get("permissions") or {}).get("deny")
        for rule in rules if isinstance(rules, list) else []:
            if not isinstance(rule, str):
                continue
            s = rule.strip()
            if s in tools:
                specs.append(("//**", anchors))
                continue
            m = re.match(r"\s*(\w+)\((.+)\)\s*\Z", s)
            if m and m.group(1) in tools and not m.group(2).strip().startswith("!"):
                specs.append((m.group(2).strip(), anchors))
    return specs


def read_deny_specs(bases):
    """(spec, anchors for `/x`) for every Read(...) deny rule: the user settings next to this hook
    (`/x` = <config dir>/x) and each project's .claude/settings{,.local}.json (`/x` = <project>/x;
    <project>/.claude/x too, to be safe). Also blocks Edit/Write on the same path."""
    return deny_specs_for({"Read"}, bases)


def edit_deny_specs(bases):
    """(spec, anchors for `/x`) for every Edit(...) or Write(...) deny rule."""
    return deny_specs_for({"Edit", "Write"}, bases)


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
    from urllib.parse import unquote, urlparse
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


def on_memory_write(ev, d):
    """neural-memory is shared by every agent of every session: an agent that reads web pages
    (researcher, its copies, scout, browser-operator) never writes it, so a page cannot plant a
    "decision" that other agents recall later (T3)."""
    if not policy_on():
        return
    atype = norm(ev.get("agent_type"))
    if ev.get("agent_id") and atype in WEB_INGESTING_TYPES:
        deny("Refused: %s reads web pages, so it does not write the shared memory (a page could "
             "plant a false decision there). Put the finding in your report with its source; the "
             "agent that verifies it against local evidence may remember it." % atype)


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
    tid = ev.get("tool_use_id")
    child_id, status = agent_response(ev)
    if not child_id:
        fanout_release(d, caller, tid)
        return
    child_id = ident(child_id)
    child = norm(ti.get("subagent_type") or "general-purpose")
    pdepth = caller_depth(d, ev)
    name = ti.get("name") if isinstance(ti.get("name"), str) and ti["name"].strip() else None
    # "completed": a foreground child that is done; "async_launched": a child now running in the
    # background (hooks.md:1751, 1763), counted as a live background child from here on.
    bg = str(status or "").lower() == "async_launched"
    # The registry write and the lease drop happen under the 'fanout' mutex, so a count never sees
    # this child twice or not at all (lock order fanout -> registry; nothing takes them in the
    # other order). The parent is this event's own agent_id (hooks.md:267): exact, and written
    # once, so no later event swaps it. An unknown caller depth leaves a known child depth alone.
    try:
        with mutex(d, "fanout"):
            reg_put(d, child_id, {"id": child_id, "type": child,
                                  "depth": None if pdepth is None else pdepth + 1,
                                  "parent": caller,
                                  "parent_type": norm(ev.get("agent_type")) or None,
                                  "spawned": time.time(), "name": norm(name) if name else None,
                                  "bg": bg, "tool_use_id": tid},
                    clear=("depth",) if pdepth is not None else (),
                    keep=("parent", "parent_type"))
            fanout_release(d, caller, tid)
    finally:
        # a lock timeout (or any failure above) must not leave the call's lease counting for
        # STACK_LEASE_TTL_S: drop it outside the mutex (a no-op when it is already gone)
        fanout_release(d, caller, tid)
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
    # SubagentStart also fires on a resume (hooks.md:2343). A stopped agent starting again runs in
    # the background (sub-agents.md:1102): a live background child of its own registry parent.
    # Nothing else is inferred: the event names no parent and no tool_use_id (hooks.md:2349).
    # Its resume reservation goes in the same step, under the 'fanout' mutex (then 'registry', as
    # in on_agent_done), so a count sees the resume exactly once. A starting agent has no Agent
    # call in flight: leases left from an earlier run of it (calls that never reported back) go.
    now = time.time()

    def start():
        reg_put(d, aid, {"type": atype or None, "started": now}, clear=("stopped",),
                resumed={"bg": True, "resumed": now})

    def drop():
        for path in resume_reservations(d, aid) + own_lease_files(d, aid):
            unlink(path)

    if resume_reservations(d, aid) or own_lease_files(d, aid):   # look before the lock
        locked = False
        try:
            with mutex(d, "fanout"):
                locked = True
                start()
                drop()
        except MutexTimeout:
            if locked:
                raise           # the registry lock inside timed out: nothing to redo here
            # A stuck fan-out lock must not leave a resumed agent 'stopped' (no background child,
            # no god-coder confirmation) with its reservation counting for STACK_RESUME_TTL_S:
            # record the start and drop the reservation without the lock (as on_agent_done drops
            # its lease); a count running meanwhile may miss this resume once.
            start()
            drop()
    else:
        start()
    if atype == GOD and policy_on():
        god_confirm(d, ev, aid)


def mark_stopped(d, aid, atype, transcript=None, ev=None):
    """Record that `aid` is no longer running and drop the locks and spawn leases it holds, and
    the lease of the call that spawned it (drop_spawn_lease). Agents the registry has never seen
    (Claude Code's internal agents: prompt suggestions, /btw) get no new entry."""
    if reg_get(d, aid):
        reg_put(d, aid, {"type": atype or None, "stopped": time.time(),
                         "transcript": transcript or None})
    void_leases(d, aid)
    if ev is not None:
        drop_spawn_lease(d, ev, aid)
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
    mark_stopped(d, aid, norm(ev.get("agent_type")), ev.get("agent_transcript_path"), ev)


def on_task_stop(ev, d):
    """PostToolUse TaskStop: a subagent stopped by TaskStop is not guaranteed a SubagentStop."""
    ti = ev.get("tool_input") if isinstance(ev.get("tool_input"), dict) else {}
    tr = ev.get("tool_response") if isinstance(ev.get("tool_response"), dict) else {}
    target = ti.get("task_id") or ti.get("shell_id") or tr.get("task_id")
    if not target:
        return
    aid, atype, _ = resolve_target(d, str(target))
    if aid:
        mark_stopped(d, aid, atype, ev=ev)


def on_stop_failure(ev, d):
    """StopFailure replaces Stop when a turn ends on an API error; inside a subagent it is the
    only end-of-run signal there may be."""
    aid = ev.get("agent_id")
    if aid:
        mark_stopped(d, aid, norm(ev.get("agent_type")), ev=ev)


def on_agent_failed(ev, d):
    ti = ev.get("tool_input") if isinstance(ev.get("tool_input"), dict) else {}
    aid = ev.get("agent_id")
    fanout_release(d, aid or "main", ev.get("tool_use_id"))
    if norm(ti.get("subagent_type")) == GOD:
        god_release_pending(d, aid or "main", ev.get("tool_use_id"))
        god_unclaim_session(d, ev)
    if not aid and norm(ev.get("agent_type")) == "blackcat":
        drop_highest_marker(d, "dispatch", prompt_key(ev), knob_int("BLACKCAT_MAX_DISPATCH", 8))


def on_prompt(ev, d):
    """A human prompt: the prompt token budget starts again; blackcat markers of earlier prompts
    go."""
    try:
        budget_prompt(d, ev)
    except Exception as exc:  # noqa: BLE001 - bookkeeping must never block a prompt
        warn("token budget: prompt boundary not recorded (%s: %s)" % (type(exc).__name__, exc))
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
    try:
        budget_session_start(d, ev)
    except Exception as exc:  # noqa: BLE001 - bookkeeping must never block a session
        warn("token budget: session start not recorded (%s: %s)" % (type(exc).__name__, exc))
    if ev.get("source") not in ("startup", "resume"):
        return
    import shutil
    with mutex(d, "god"):
        unlink(god_path(d))
    with mutex(d, "screen"):
        unlink(os.path.join(d, SCREEN_LOCK))
    shutil.rmtree(os.path.join(d, "blackcat"), ignore_errors=True)
    shutil.rmtree(os.path.join(d, "fanout"), ignore_errors=True)
    # Subagents never outlive the process that ran them: after a restart or --resume nothing from
    # the registry is running any more (a SendMessage resume fires SubagentStart, which clears
    # this again). Without this, dead children would count against the fan-out caps. The spawn
    # leases (fanout/) died with that process too.
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


# ---------------------------------------------------------------- token budgets
# Context tokens = input + cache_creation + cache_read tokens of every API call (the usage fields,
# hooks.md:1759), summed over the whole session tree: the main transcript (transcript_path,
# hooks.md:738) and each subagent's own <session>/subagents/agent-<id>.jsonl (hooks.md:2385, 2405).
# STACK_PROMPT_CTX_BUDGET covers the calls since the last UserPromptSubmit, STACK_SESSION_CTX_BUDGET
# the whole session; both are checked on every PreToolUse of every agent (`budget` mode, and the
# main hook's own tools in dispatch()). Once spent, every call is refused except the ones an agent
# needs to report or stop (REPORT_TOOLS, ToolSearch loading one of them, Write/Edit under a
# .claude-work/ folder or the session scratchpad).
# The transcript format is not documented. As observed (118 files, 12,231 assistant lines): one API
# call is one line per content block, every line with the same message.id, requestId and usage,
# always adjacent and never split across files; so each call counts once per (message.id,
# requestId). Anything that doesn't parse is skipped with a warning (the call is allowed, never
# refused), and `--check-budget` (doctor) tells when real transcripts stop yielding usage.
# Incremental: budget.json in the session's state folder keeps each file's byte offset (complete
# lines only), its last keys, the running total and the total at the prompt boundary.
BUDGET_STATE = "budget.json"
BUDGET_KEYS_KEPT = 8
BUDGET_SCAN_S = 2.0          # most seconds of reading in one PreToolUse; the rest waits for the next
BUDGET_LONG_SCAN_S = 10.0    # UserPromptSubmit and SessionStart (hook timeout 15 s)
USAGE_KEYS = ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")
REPORT_TOOLS = ("SubagentHandback", "TaskStop", "AskUserQuestion", "mcp__conductor__AskUserQuestion")
BUDGET_LOG_KEYS = ("hook_event_name", "session_id", "prompt_id", "tool_name", "tool_use_id",
                   "agent_id", "agent_type")
BUDGET_CHECK_MIN_LINES = 50  # --check-budget: this many lines and no assistant line = format drift


def budget_caps():
    return (knob_int("STACK_PROMPT_CTX_BUDGET", 100000000),
            knob_int("STACK_SESSION_CTX_BUDGET", 666000000))


def transcript_files(ev):
    """(main transcript, subagents folder) of the event's session; None without transcript_path.
    transcript_path is the main session's (hooks.md:2385); a subagent's own path is mapped back."""
    tp = ev.get("transcript_path")
    if not isinstance(tp, str) or not tp.strip():
        return None
    tp = os.path.expanduser(tp.strip())
    folder = os.path.dirname(tp)
    if os.path.basename(folder) == "subagents":
        return os.path.dirname(folder) + ".jsonl", folder
    stem = os.path.basename(tp)
    stem = stem[:-len(".jsonl")] if stem.endswith(".jsonl") else str(ev.get("session_id") or stem)
    return tp, os.path.join(folder, stem, "subagents")


def session_transcripts(files):
    main, sub = files
    try:
        subs = sorted(os.path.join(sub, f) for f in os.listdir(sub) if f.endswith(".jsonl"))
    except (FileNotFoundError, NotADirectoryError):
        subs = []
    return [main] + subs


def scan_stats():
    return {"calls": 0, "assistant": 0, "no_usage": 0, "bad": 0, "lines": 0, "partial": False}


def scan_transcript(path, fst, deadline, stats):
    """Context tokens of the API calls appended to `path` since fst["off"] (fst is updated: offset,
    inode, last keys). Stops at an incomplete last line or at `deadline` (time.monotonic)."""
    try:
        st = os.stat(path)
    except OSError:
        return 0
    off = int(fst.get("off") or 0)
    if fst.get("ino") not in (None, st.st_ino) or st.st_size < off:
        warn("token budget: %s was replaced or truncated; counting resumes at its end" % path)
        fst.update(off=st.st_size, ino=st.st_ino, keys=[])
        return 0
    fst["ino"] = st.st_ino
    if st.st_size == off:
        return 0
    keys, added = list(fst.get("keys") or []), 0
    with open(path, "rb") as f:
        f.seek(off)
        for line in f:
            if not line.endswith(b"\n"):
                break                            # still being written: read it next time
            if time.monotonic() > deadline:
                stats["partial"] = True
                break
            off += len(line)
            stats["lines"] += 1
            if b'"assistant"' not in line:
                continue
            try:
                e = json.loads(line)
            except (ValueError, RecursionError):
                stats["bad"] += 1
                continue
            if not isinstance(e, dict) or e.get("type") != "assistant":
                continue
            stats["assistant"] += 1
            msg = e.get("message")
            usage = msg.get("usage") if isinstance(msg, dict) else None
            if not isinstance(usage, dict):
                stats["no_usage"] += 1
                continue
            key = "%s|%s" % (msg.get("id"), e.get("requestId"))
            if key == "None|None":
                key = "uuid|%s" % e.get("uuid")
            if key in keys:
                continue
            keys = (keys + [key])[-BUDGET_KEYS_KEPT:]
            try:
                tokens = sum(int(usage.get(k) or 0) for k in USAGE_KEYS)
            except (TypeError, ValueError):
                stats["bad"] += 1
                continue
            added += max(tokens, 0)
            stats["calls"] += 1
    fst["off"], fst["keys"] = off, keys
    return added


def budget_update(d, ev, scan_s=BUDGET_SCAN_S, mutate=None, start_at_end=False, lock_s=1.0):
    """Bring budget.json up to date with the session's transcripts and return it. When another
    hook holds the lock, the last saved state is returned as it is. None: no transcript_path.
    start_at_end: files seen for the first time count only what is appended later (a fork)."""
    files = transcript_files(ev)
    if files is None:
        warn_once("token budget: the hook input has no transcript_path; budgets not checked")
        return None
    path = os.path.join(d, BUDGET_STATE)
    try:
        with mutex(d, "budget", timeout=lock_s):
            st = read_json(path) or {}
            if not isinstance(st.get("files"), dict):
                st = {"files": {}, "total": 0, "prompt_base": 0, "prompt_id": None}
            deadline, stats = time.monotonic() + scan_s, scan_stats()
            for p in session_transcripts(files):
                fst = st["files"].get(p)
                if fst is None:
                    fst = st["files"][p] = {"off": 0}
                    if start_at_end:
                        with contextlib.suppress(OSError):
                            s = os.stat(p)
                            fst.update(off=s.st_size, ino=s.st_ino)
                st["total"] = int(st.get("total") or 0) + scan_transcript(p, fst, deadline, stats)
            if stats["bad"]:
                warn("token budget: %d transcript lines could not be read and are not counted"
                     % stats["bad"])
            if mutate:
                mutate(st)
            st["ts"] = time.time()
            write_json_atomic(path, st)
            return st
    except MutexTimeout:
        return read_json(path)


def budget_prompt(d, ev):
    """UserPromptSubmit: the prompt budget restarts from the session total at this point."""
    if not policy_on() or max(budget_caps()) <= 0:
        return

    def mark(st):
        st["prompt_id"], st["prompt_base"] = ev.get("prompt_id"), st["total"]
    budget_update(d, ev, scan_s=BUDGET_LONG_SCAN_S, mutate=mark, lock_s=5.0)


def budget_session_start(d, ev):
    """SessionStart: a resumed session catches up on its transcripts (the session budget spans
    the whole session); a fork counts only what it adds itself (hooks.md:1138)."""
    source = ev.get("source")
    if not policy_on() or max(budget_caps()) <= 0 or source not in ("resume", "fork"):
        return
    budget_update(d, ev, scan_s=BUDGET_LONG_SCAN_S, start_at_end=source == "fork", lock_s=5.0)


def own_output_file(ev, path):
    """A path under a .claude-work/ folder (the stack's job folders) or the session scratchpad
    (scratchpad_dir, hooks.md:740): where an agent writes the report or file it hands back."""
    if not isinstance(path, str) or not path.strip():
        return False
    p = os.path.normpath(os.path.join(ev.get("cwd") or os.getcwd(),
                                      os.path.expanduser(path.strip())))
    if ".claude-work" in p.split(os.sep):
        return True
    sp = ev.get("scratchpad_dir")
    if isinstance(sp, str) and sp.strip():
        sp = os.path.normpath(sp.strip())
        return p == sp or p.startswith(sp.rstrip(os.sep) + os.sep)
    return False


def budget_exempt(ev):
    """Calls an agent needs to report or stop are never refused."""
    tool = ev.get("tool_name") or ""
    ti = ev.get("tool_input") if isinstance(ev.get("tool_input"), dict) else {}
    if tool in REPORT_TOOLS:
        return True
    if tool == "ToolSearch":        # loading the schema of one of them
        q = str(ti.get("query") or "").lower()
        return any(t.lower() in q for t in REPORT_TOOLS)
    if tool in ("Write", "Edit"):
        return own_output_file(ev, ti.get("file_path"))
    return False


def budget_note_prompt(st, ev):
    """Main-thread calls carry the prompt being processed (prompt_id, hooks.md:737): a new one the
    UserPromptSubmit hook never recorded starts the prompt budget here."""
    pid = ev.get("prompt_id")
    if pid and not ev.get("agent_id") and st.get("prompt_id") != pid:
        st["prompt_id"], st["prompt_base"] = pid, st["total"]


def budget_gate(ev, d):
    """PreToolUse: refuse the call once the prompt or session context-token budget is spent.
    Fails open: any error only warns."""
    if not policy_on():
        return
    prompt_cap, session_cap = budget_caps()
    if (prompt_cap <= 0 and session_cap <= 0) or budget_exempt(ev):
        return
    try:
        st = budget_update(d, ev, mutate=lambda s: budget_note_prompt(s, ev))
        total = int((st or {}).get("total") or 0)
        used = total - int((st or {}).get("prompt_base") or 0)
    except Exception as exc:  # noqa: BLE001 - a budget we cannot count never blocks work
        warn("token budget not checked (%s: %s); the call is allowed" % (type(exc).__name__, exc))
        return
    # The budget knobs are OWNED_ENV in install.sh: a raised value is reset by the next install.
    if session_cap > 0 and total >= session_cap:
        deny(budget_reason("Session", "in this session", total, "STACK_SESSION_CTX_BUDGET",
                           session_cap, ev),
             "claude-agent-stack: the session token budget is spent (%s of %s context tokens); "
             "agents are told to wrap up. Start a new session, or raise STACK_SESSION_CTX_BUDGET "
             "in the env block of ~/.claude/settings.json (it holds until the next install.sh "
             "run, which resets the stack's budget knobs)."
             % (fmt_int(total), fmt_int(session_cap)))
    if prompt_cap > 0 and used >= prompt_cap:
        deny(budget_reason("Prompt", "since the user's last prompt", used,
                           "STACK_PROMPT_CTX_BUDGET", prompt_cap, ev),
             "claude-agent-stack: this prompt's token budget is spent (%s of %s context tokens); "
             "agents are told to wrap up. Your next prompt starts a new budget; to allow more per "
             "prompt, raise STACK_PROMPT_CTX_BUDGET in the env block of ~/.claude/settings.json "
             "(it holds until the next install.sh run, which resets the stack's budget knobs)."
             % (fmt_int(used), fmt_int(prompt_cap)))


def fmt_int(n):
    return "{:,}".format(int(n))


def budget_reason(kind, span, used, knob, cap, ev):
    head = ("%s token budget reached: the agents of this session have used %s context tokens %s "
            "(%s=%d). " % (kind, fmt_int(used), span, knob, cap))
    if not ev.get("agent_id"):
        return head + ("Call no more tools: answer the user now with what you have, and say what "
                       "is left.")
    return head + ("Finish with what you have: make no more tool calls except to report or stop, "
                   "and return STATUS: partial listing what is left.")


# ---------------------------------------------------------------- MCP call cap
# Every subagent may make at most min(STACK_MAX_MCP_CALLS, its frontmatter maxTurns) calls to MCP
# tools (`mcp__<server>__<tool>`) per prompt it is given: MCP round trips (remote APIs, browsers,
# large payloads) cost more than local tools, and maxTurns alone lets an agent spend all its turns
# on them. A subagent's prompt is one run of it: the Agent call that spawns it (a fresh agent_id)
# or a SendMessage that resumes it (same agent_id). Each run starts with SubagentStart
# (hooks.md:2343, also on a resume), which rewrites the registry's `started` stamp; the counter
# stores the stamp it counts for, and a different stamp starts it again from 0. No stamp (the
# SubagentStart hook never ran) keeps one count for the agent: stricter, never looser. A message to
# a still-running agent is part of its current run and gets no new allowance. Counted at
# PreToolUse; a call this gate allows counts even if another hook or the permission system then
# refuses it. The main thread is not counted: BlackCat's BLACKCAT_MAX_STEPS already bounds every
# one of its calls per prompt.
# maxTurns comes from <config>/agents/<type>.md (a copy type falls back to its base file); a type
# with no file or no maxTurns (explore, general-purpose, plugin agents) gets STACK_MAX_MCP_CALLS.
# Past the cap only MCP calls are refused (REPORT_TOOLS never), other tools keep working. Fails
# open like the token budgets: state it cannot read or lock warns and allows the call.
MCP_CALLS_DIR = "mcp-calls"
MAX_TURNS_RE = re.compile(r"^maxTurns:\s*(\d+)\s*$", re.M)


def mcp_calls_knob():
    return knob_int("STACK_MAX_MCP_CALLS", 64)


def agent_max_turns(agent_type, agents_dir=None):
    """The frontmatter maxTurns of an installed agent type (a copy type: its base's file when its
    own is missing); None when there is none."""
    if agents_dir is None:
        agents_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                  "agents")
    t = norm(agent_type)
    for name in (t, COPY_BASE.get(t)):
        if not name or safe(name) != name:
            continue
        try:
            with open(os.path.join(agents_dir, name + ".md")) as f:
                head = f.read(8192)
        except OSError:
            continue
        parts = head.split("\n---", 1) if head.startswith("---") else None
        m = MAX_TURNS_RE.search(parts[0]) if parts and len(parts) == 2 else None
        return int(m.group(1)) if m else None
    return None


def mcp_cap(agent_type, knob=None):
    knob = mcp_calls_knob() if knob is None else knob
    turns = agent_max_turns(agent_type)
    return min(knob, turns) if turns and turns > 0 else knob


def mcp_gate(ev, d):
    """PreToolUse: count a subagent's MCP call; refuse it once the agent's cap is reached."""
    tool = str(ev.get("tool_name") or "")
    aid = ev.get("agent_id")
    knob = mcp_calls_knob()
    if not policy_on() or knob <= 0 or not aid or not tool.startswith("mcp__") \
            or tool in REPORT_TOOLS:
        return
    atype = norm(ev.get("agent_type")) or "unknown"
    try:
        cap = mcp_cap(atype, knob)
        folder = os.path.join(d, MCP_CALLS_DIR)
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, safe(aid) + ".json")
        run = (reg_get(d, aid) or {}).get("started")       # this run's SubagentStart
        with mutex(folder, safe(aid), timeout=2.0):
            cur = read_json(path) or {}
            n = int(cur.get("calls") or 0) if cur.get("run") == run else 0
            if n < cap:
                write_json_atomic(path, {"calls": n + 1, "run": run, "type": atype, "cap": cap,
                                         "ts": time.time()})
                return
    except MutexTimeout:
        warn("MCP call cap: %s's counter is busy; the call is allowed" % atype)
        return
    except Exception as exc:  # noqa: BLE001 - a count we cannot keep never blocks work
        warn("MCP call cap not checked (%s: %s); the call is allowed" % (type(exc).__name__, exc))
        return
    # The knob is OWNED_ENV in install.sh: a raised value is reset by the next install.
    limit = ("STACK_MAX_MCP_CALLS=%d" % knob if cap == knob
             else "its maxTurns %d, below STACK_MAX_MCP_CALLS=%d" % (cap, knob))
    deny("MCP call limit reached: this %s has made %d MCP tool calls for its current prompt (%s). "
         "Make no more MCP tool calls; other tools still work. Finish with what you have, or "
         "return STATUS: partial naming what the remaining MCP calls were for." % (atype, n, limit),
         "claude-agent-stack: a %s reached its MCP call limit (%d per agent per prompt; a resume "
         "starts a new count). To allow more, raise STACK_MAX_MCP_CALLS in the env block of ~/.claude/settings.json (it "
         "holds until the next install.sh run, which resets the stack's budget knobs); the "
         "agent's maxTurns still caps it." % (atype, cap))


def budget_main(raw):
    """`budget` mode, a PreToolUse hook on every tool: the token budgets and the MCP call cap for
    the calls the main hook doesn't see (it checks its own before taking any lease). Fails open."""
    if not policy_on():
        return 0
    try:
        ev = json.loads(raw)
    except (ValueError, RecursionError) as exc:
        warn("token budget: unparseable hook input (%s); not checked" % type(exc).__name__)
        return 0
    if not isinstance(ev, dict) or ev.get("hook_event_name") != "PreToolUse" \
            or pre_handler(str(ev.get("tool_name") or "")) is not None:
        return 0
    if ev.get("agent_id"):
        ev["agent_id"] = ident(ev["agent_id"])
    try:
        d = sdir(ev.get("session_id"))
        # every tool call of every agent passes here: log the call, never its input (commands,
        # file bodies, pasted secrets)
        log(d, {k: ev[k] for k in BUDGET_LOG_KEYS if ev.get(k) is not None})
        budget_gate(ev, d)
        mcp_gate(ev, d)
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001 - fail open by design
        warn("token budget: %s: %s" % (type(exc).__name__, exc))
    return 0


def check_budget(argv):
    """`--check-budget [transcript]` (doctor): count the newest session (or the given one) the way
    the budgets do. FAIL when its assistant lines carry no usage this parser can read, or when
    BUDGET_CHECK_MIN_LINES lines hold no assistant line at all: the transcript format changed, and
    the budgets would silently stop counting. Fewer lines and no API call yet: skipped."""
    main = argv[2] if len(argv) > 2 else None
    if main is None:
        root = os.path.join(os.environ.get("CLAUDE_CONFIG_DIR") or os.path.expanduser("~/.claude"),
                            "projects")
        cands = []
        with contextlib.suppress(OSError):
            for proj in os.listdir(root):
                with contextlib.suppress(OSError):
                    cands += [os.path.join(root, proj, f) for f in os.listdir(os.path.join(root, proj))
                              if f.endswith(".jsonl")]
        main = max(cands, key=lambda p: os.path.getmtime(p)) if cands else None
    if not main or not os.path.isfile(main):
        sys.stdout.write("agent_guard budget check: skipped (no session transcript found)\n")
        return 0
    stats, total = scan_stats(), 0
    deadline = time.monotonic() + 60
    paths = session_transcripts(transcript_files({"transcript_path": main}))
    for p in paths:
        total += scan_transcript(p, {}, deadline, stats)
    where = "%s (+%d subagent transcripts)" % (main, len(paths) - 1)
    if stats["assistant"] and not stats["calls"]:
        sys.stdout.write("agent_guard budget check: FAIL %d assistant lines but no readable usage "
                         "in %s: the token budgets would count nothing\n" % (stats["assistant"], where))
        return 1
    if not stats["assistant"]:
        if stats["lines"] >= BUDGET_CHECK_MIN_LINES:
            sys.stdout.write("agent_guard budget check: FAIL %d lines but no assistant lines in %s: "
                             "the transcript format changed, and the token budgets would count "
                             "nothing\n" % (stats["lines"], where))
            return 1
        sys.stdout.write("agent_guard budget check: skipped (%d lines and no API call yet in %s)\n"
                         % (stats["lines"], where))
        return 0
    sys.stdout.write("agent_guard budget check: ok (%d API calls, %s context tokens, %d unreadable "
                     "lines in %s)\n" % (stats["calls"], fmt_int(total), stats["bad"], where))
    return 0


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
    import struct
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
        import struct
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
    import subprocess
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
    import shutil
    return shutil.which("sips") or ("/usr/bin/sips" if os.path.exists("/usr/bin/sips") else None)


def run_quiet(cmd, deadline):
    import subprocess
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
    import shutil
    import tempfile
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
    import base64
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
    import base64
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
    from urllib.parse import unquote, urlparse
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
        from urllib.parse import quote
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
def blackcat_guard(raw, from_settings=False):
    """BlackCat's own gate. Wired twice: in agents/blackcat.md's frontmatter (runs only when
    blackcat is the main thread) and in settings.json (`blackcat-guard --settings`, every main
    thread: it acts only when the event names agent_type "blackcat", which hooks.md documents for
    sessions run with an agent; with no agent_type it leaves the call to the frontmatter wiring).
    Both wirings count one step per call: the first to claim the call's tool_use_id decides."""
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
    if from_settings and norm(ev.get("agent_type")) != "blackcat":
        sys.exit(0)  # another main thread (claude, ninja-coder, ...) or no agent_type to go by
    tool = ev.get("tool_name") or ""
    if tool in ("Agent", "SendMessage"):
        # the main hook counts a dispatch against BLACKCAT_MAX_DISPATCH and BLACKCAT_MAX_STEPS
        # together with its fan-out lease (on_agent), and a SendMessage against
        # BLACKCAT_MAX_STEPS together with its resume reservation (on_send): one call, one
        # decision (this hook runs in parallel with that one and cannot roll it back)
        sys.exit(0)
    if tool not in BLACKCAT_TOOLS:
        deny("BlackCat only delegates (it may look with Read, Grep and Glob, but writes and runs "
             "nothing). Make one Agent call to the right specialist (or orchestrator), or "
             "SendMessage to resume the previous agent.")
    d = sdir(ev.get("session_id"))
    log(d, ev)
    tuid = safe(ev.get("tool_use_id"), "")
    if tuid:
        os.makedirs(os.path.join(d, "blackcat"), exist_ok=True)
        # named like the step markers (kind.prompt.n) so on_prompt prunes it with them
        if not create_excl(os.path.join(d, "blackcat", "call.%s.%s" % (prompt_key(ev), tuid))):
            sys.exit(0)  # the other wiring already counted (and judged) this call
    steps = knob_int("BLACKCAT_MAX_STEPS", 12)
    if not claim_marker(d, "step", prompt_key(ev), steps):
        deny(STEP_LIMIT_REASON % steps)
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
# fast path for the "secrets" scan kind (below): checked only when that kind is requested. Not
# word-bounded (unlike TRIGGER_RE): over-matching only causes an extra full parse, never a miss.
SECRETS_TRIGGER_RE = re.compile(r"mcp-headers|with-stack-env|install\.sh|doctor\.sh")
SECRETS_PROGRAMS = {"mcp-headers", "with-stack-env"}
INSTALLER_SCRIPTS = {"install.sh", "doctor.sh"}
# fast path for the "protect" scan kind: a redirect character or one of the write-capable
# commands it understands. Over-matches on purpose (e.g. "cp" inside an unrelated word via \b
# still needs a word boundary, but ">" alone is enough) — a miss here would be the real bug.
PROTECT_TRIGGER_RE = re.compile(
    r">|\b(?:cp|mv|tee|dd|sed|gsed|perl|install|rsync|ditto|rm|unlink|rmdir|shred|truncate|ln|"
    r"chmod|chown|chflags|touch|find|xargs|parallel|tar|unzip|cd|pushd|python[\d.]*|pypy[\d.]*|"
    r"node|nodejs|ruby|php|deno|bun|osascript)\b")
PROTECT_WRITE_CMDS = {"cp", "mv", "install", "rsync", "ditto", "tee", "dd", "sed", "gsed", "perl",
                      "rm", "unlink", "rmdir", "shred", "truncate", "ln", "chmod", "chown",
                      "chflags", "touch", "find", "tar", "unzip"}
# removals, renames and mode changes: every operand is a target, and a directory operand that
# holds a protected path counts (rm -rf ~/.claude, chmod -R 000 ~/.claude/hooks/..)
PROTECT_ALL_ARGS = {"rm", "unlink", "rmdir", "shred", "truncate", "ln", "chmod", "chown",
                    "chflags", "touch"}
# the stack's own files under the config dir (<config>/<entry>) and its hook state: protected even
# if settings.json lost its deny rules (installed copies only; see protect_specs)
PROTECTED_CONFIG = ("hooks", "bin", "settings.json", "agents", "rules", "mcp", "magg", "skills",
                    "stack-plugins", "CLAUDE.md", "backup-*", "stack.env", ".stack-manifest.json",
                    ".credentials.json")
# inline interpreter code (python -c, node -e, a heredoc into python -) that changes a file
MUTATE_CODE_RE = re.compile(
    r"\b(?:remove|removedirs|unlink|unlinkSync|rmtree|rmdir|rmdirSync|rmSync|rename|renames|"
    r"renameSync|truncate|chmod|lchmod|chown|symlink|symlinkSync|link|write_text|write_bytes|"
    r"writeFile|writeFileSync|appendFile|appendFileSync|copyfile|copy2|copytree|copyFile|"
    r"copyFileSync|move|touch|utime|system|popen)\s*\(|\bos\.replace\s*\(|"
    r"\bopen\s*\([^)]*,\s*['\"][^'\"]*[wax+]|\bopen\s*\(?\s*\w+\s*,\s*['\"]\s*(?:>|\+<|\|)|"
    r"\bunlink\b|\brename\b|subprocess|child_process|File\.(?:delete|write|rename|unlink)|"
    r"FileUtils", re.I)
CODE_LITERAL_RE = re.compile(r"'''(.*?)'''|\"\"\"(.*?)\"\"\"|'([^'\n]*)'|\"([^\"\n]*)\"", re.S)
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
SECRETS_REASON = ("Blocked by the stack's secret-hardening rule: `%s` would put a real API key or "
                  "token into this transcript (also inside bash -c, eval or $(...)). Agents never "
                  "print key values. The default output is redacted and is enough to check a "
                  "key: `mcp-headers <server>` shows the header name and the key's length, "
                  "`with-stack-env --print-env` shows which variables are set. If a real value "
                  "must be checked, stop and ask the user to check it themselves.")
PROTECT_REASON = ("Blocked by the stack's protected-path rule: `%s` writes to, removes, renames or "
                  "changes the mode of a path denied to Edit/Write (the stack's config: hooks, "
                  "bin, settings.json, agents, rules, mcp, magg, skills, stack-plugins, "
                  "CLAUDE.md, backups; the hook state dir; a project's .git and .claude settings; "
                  "or a Read-denied path), also inside bash -c, eval, find -exec, xargs or inline "
                  "interpreter code. The stack is changed only by editing the repository and "
                  "re-running its installer: report the change you need, or ask the user to make "
                  "it themselves.")


def _shell_words(command):
    """shlex words, with each unquoted newline kept as a "\\n" separator token."""
    import shlex
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


TRUNCATE_VALUE_OPTS = {"-s", "--size", "-r", "--reference"}


def _operands(args, value_opts=()):
    """The non-option arguments of a command (everything after `--` counts; an option in
    value_opts also takes the next word)."""
    out, k = [], 0
    while k < len(args):
        a = args[k]
        if a == "--":
            out.extend(args[k + 1:])
            break
        if a in value_opts:
            k += 2
            continue
        if not a.startswith("-") or a == "-":
            out.append(a)
        k += 1
    return out


def _heredoc_interpreter(owner):
    """The command that owns a heredoc is an interpreter reading its program from stdin
    (`python3 - <<EOF`, `node <<EOF`, `perl <<EOF`)."""
    words = [w for w in re.findall(r"[^\s;&|()<>'\"`]+", owner.rsplit("\n", 1)[-1])
             if not ASSIGN_RE.match(w) and w not in PREFIX_WORDS]
    return bool(words) and bool(INTERPRETER_RE.match(_base(words[0])))


def builtin_protect_specs():
    """`//abs` deny specs for the stack's own files in an installed config dir (the hook lives in
    <config>/hooks/; the repo's dot-claude/ still holds __CLAUDE_DIR__ and is skipped) and for the
    hook state dir. Backs up the settings.json deny rules the protect scan reads."""
    specs = [("/" + os.path.join(state_root(), "**"), ())]
    conf = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    try:
        with open(os.path.join(conf, "settings.json"), encoding="utf-8") as f:
            installed = "__CLAUDE_DIR__" not in f.read()
    except OSError:
        installed = False
    if installed:
        for rel in PROTECTED_CONFIG:
            specs.append(("/" + os.path.join(conf, rel), ()))
    return specs


class _Scan(object):
    """One detection run: which kinds to report ("push", "forge", "opaque", "secrets", "protect"),
    a work budget and a deadline (a hook that times out does not block, so a slow check must deny
    instead). "secrets" flags `--reveal` on mcp-headers or with-stack-env, env/printenv under
    with-stack-env (each prints real API keys) and `bash -x`/`sh -x`/`zsh -x` on install.sh or
    doctor.sh (an xtrace of either script echoes every key it reads). "protect" flags a
    Bash-level write, delete, rename or mode change (redirection, cp/mv/install/rsync, tee, dd,
    sed/perl -i, rm, find -delete, chmod, tar -x, inline code, ...; `cd DIR` is followed) that
    targets a path already denied to the Edit/Write/Read tools, the stack's own config files or
    the hook state dir — Claude Code's own protected-path checks
    apply to Edit/Write, not to Bash, and bypassPermissions mode skips even those; needs `ev` (the
    hook event) to resolve relative paths and read the deny rules that apply here."""

    def __init__(self, want, ev=None):
        self.want, self.budget = set(want), MAX_SCANS
        self.deadline = time.monotonic() + DEADLINE_S
        self.ev = ev
        self._protect_specs = None
        self.cd = []                          # directories a `cd`/`pushd` earlier in the command named

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
        secrets_trigger = "secrets" in self.want and SECRETS_TRIGGER_RE.search(bare)
        protect_trigger = "protect" in self.want and PROTECT_TRIGGER_RE.search(bare)
        if not (TRIGGER_RE.search(EXPANSION_RE.sub("", bare)) or ESCAPE_RE.search(command)
                or OPAQUE_HINT_RE.search(bare) or secrets_trigger or protect_trigger):
            return None                        # names no git/gh/tea/fj/mcp-headers/..., even obfuscated
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
            if not found and "protect" in self.want and _heredoc_interpreter(owner):
                found = self.protect_code(body)      # python3 - <<'EOF' ... os.remove(...)
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
            if not found and "secrets" in self.want and base in SECRETS_PROGRAMS and here_cmd:
                found = self.secrets_helper(base, words, i + 1, end, restore)
            if not found and "secrets" in self.want and base in SHELLS and here_cmd:
                found = self.secrets_bash_x(base, words, i + 1, end, restore)
            if not found and "protect" in self.want:
                if ">" in w and REDIR_OP_RE.match(w) and i + 1 < end:
                    found = self.protect_hit(restore(words[i + 1]), "redirect (%s)" % w)
                elif here_cmd and base in ("cd", "pushd"):
                    self.note_cd([restore(x) for x in words[i + 1:end]])
                elif here_cmd and base in PROTECT_WRITE_CMDS:
                    found = self.protect_command(base, [restore(x) for x in words[i + 1:end]])
                    if not found and xargs_seen:   # ls ~/.claude/hooks | xargs rm: operands on stdin
                        for x in words[stmt_start:end]:
                            found = found or self.protect_hit(restore(x), "xargs %s" % base,
                                                              contains=True)
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
                        if code_flag and not found and "protect" in self.want:
                            found = self.protect_code(rest[k])
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
            import shlex
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

    def secrets_helper(self, base, words, start, end, restore):
        """mcp-headers and with-stack-env redact key values by default; `--reveal` prints them in
        plaintext, so any agent call carrying it is refused (`--reveal=...` and a `--` before it
        too: the helpers look for the bare word anywhere). with-stack-env in exec mode hands the
        keys to its command, so a command that only dumps the environment (env, printenv, set,
        export, declare) is refused as well. The redacted forms pass. Claude Code's own
        mcp-headers invocation (CLAUDE_CODE_MCP_SERVER_NAME, no argument) never reaches a Bash
        hook."""
        args = [restore(x) for x in words[start:end]]
        if any(a == "--reveal" or a.startswith("--reveal=") for a in args):
            return self.hit("secrets", "%s --reveal" % base)
        if base == "with-stack-env" and args[:1] != ["--print-env"]:
            rest = args[2:] if args[:1] == ["--only"] else args
            k = 0
            while k < len(rest) - 1 and (ASSIGN_RE.match(rest[k]) or rest[k] in ("env", "-i", "--")):
                k += 1                         # with-stack-env env X=1 printenv
            cmd = _base(rest[k]) if rest else ""
            if cmd in ("env", "printenv", "set", "export", "declare", "typeset", "compgen"):
                return self.hit("secrets", "with-stack-env ... %s" % cmd)
        return None

    def secrets_bash_x(self, base, words, start, end, restore):
        """bash -x / sh -x / zsh -x (or a combined short option: -xv, -ex) on install.sh or
        doctor.sh: xtrace echoes every key the script reads or masks as it runs."""
        args = [restore(x) for x in words[start:end]]
        has_x = any(a == "-x" or a == "--xtrace"
                    or (a[:1] == "-" and a[:2] != "--" and "x" in a[1:]) for a in args)
        if not has_x:
            return None
        for a in args:
            if not a.startswith("-") and _base(a) in INSTALLER_SCRIPTS:
                return self.hit("secrets", "%s -x %s" % (base, _base(a)))
        return None

    def protect_specs(self):
        """([(compiled regex, literal prefix)], bases) for every path a Bash write must not
        resolve to: the Read/Edit/Write deny rules that apply here (a Read deny also blocks
        Edit/Write on the same path), plus, in an installed config dir, the stack's own files
        (PROTECTED_CONFIG) and the hook state dir — the god-coder lock and the step markers."""
        if self._protect_specs is None:
            bases = (path_bases(self.ev) if self.ev is not None else []) or [os.getcwd()]
            specs = read_deny_specs(bases) + edit_deny_specs(bases) + builtin_protect_specs()
            compiled = [(rx, lit) for spec, anchors in specs
                        for rx, lit in deny_patterns(spec, anchors)]
            self._protect_specs = (compiled, bases)
        return self._protect_specs

    def protect_hit(self, raw_path, how, contains=False):
        """`raw_path` resolved the way a shell would (absolute as given, relative to each base
        and to a directory an earlier `cd` named, `~` expanded; lexical and symlink-resolved),
        checked against every protected-path pattern. contains=True: a directory that holds a
        protected path counts too (rm -rf, find -delete, mv, chmod -R)."""
        s = (raw_path or "").strip()
        if not s or s.startswith("-") or s in ("/dev/null", "/dev/stdout", "/dev/stderr", "&1",
                                               "&2") or "\n" in s:
            return None
        compiled, bases = self.protect_specs()
        if not compiled:
            return None
        s = os.path.expanduser(s) if s.startswith("~") else s
        candidates = [s] if os.path.isabs(s) else [os.path.join(b, s) for b in bases + self.cd]
        fold = (lambda x: x.lower()) if sys.platform == "darwin" else (lambda x: x)
        for cand in candidates:
            for c in dict.fromkeys((os.path.normpath(cand), os.path.realpath(cand))):
                under = fold(c).rstrip("/") + "/"
                for rx, literal in compiled:
                    inside = contains and literal is not None and fold(literal).startswith(under)
                    if inside or rx.match(c):
                        return self.hit("protect", "%s: %s%s" % (
                            how, c, " (it holds protected files)" if inside else ""))
        return None

    def note_cd(self, args):
        """`cd DIR` / `pushd DIR`: later relative paths are also resolved against DIR (in
        addition to the working directories: a cd inside a subshell does not last)."""
        pos = [a for a in args if not a.startswith("-") or a == "-"]
        target = pos[0] if pos else "~"
        if _expansion(target) or target == "-":
            return
        target = os.path.expanduser(target) if target.startswith("~") else target
        _, bases = self.protect_specs()
        for b in ([None] if os.path.isabs(target) else bases + self.cd):
            p = os.path.normpath(target if b is None else os.path.join(b, target))
            if p not in self.cd and len(self.cd) < 16:
                self.cd.append(p)

    def protect_code(self, code):
        """Inline interpreter code (python -c, node -e, perl -e, a heredoc into `python3 -`) that
        names a protected path in a string literal and calls something that changes files."""
        if not isinstance(code, str) or not MUTATE_CODE_RE.search(code):
            return None
        for m in CODE_LITERAL_RE.finditer(code[:200000]):
            lit = next(g for g in m.groups() if g is not None).strip()
            if lit.startswith(("/", "~", ".")) or "/" in lit:
                found = self.protect_hit(lit, "inline code changes", contains=True)
                if found:
                    return found
        return None

    def protect_command(self, base, args):
        """The path(s) a write-capable command changes: tee writes every non-option argument; dd
        writes `of=`; sed/perl -i rewrites its last file argument in place; cp/mv/install/rsync/
        ditto write their last positional argument, or -t/--target-directory's value (and
        DIR/basename(SRC) when that is a directory); mv also removes its sources; rm, unlink,
        rmdir, shred, truncate, ln, chmod, chown, chflags and touch change every operand; find
        with -delete or -exec/-ok of a writer changes its start paths; tar -x and unzip write into
        -C / -d (or the working directory)."""
        targets, whole = [], []                # whole: directories whose protected contents count
        pos = _operands(args, TRUNCATE_VALUE_OPTS if base == "truncate" else ())
        if base == "tee":
            targets = pos
        elif base == "dd":
            targets = [a[3:] for a in args if a.startswith("of=")]
        elif base in ("sed", "gsed", "perl"):
            has_i = any(a in ("-i", "--in-place") or a.startswith("-i") or a.startswith("--in-place=")
                        or (a[:1] == "-" and a[:2] != "--" and "i" in a[1:] and base == "perl")
                        for a in args)
            if has_i:
                targets = pos[-1:]
        elif base in PROTECT_ALL_ARGS:
            whole = pos
        elif base == "find":
            whole = self.find_targets(args)
        elif base in ("tar", "unzip"):
            whole = self.extract_targets(base, args)
        else:                                   # cp, mv, install, rsync, ditto
            target_dir = None
            for j, a in enumerate(args):
                if a in ("-t", "--target-directory") and j + 1 < len(args):
                    target_dir = args[j + 1]
                elif a.startswith("--target-directory="):
                    target_dir = a.split("=", 1)[1]
            if target_dir:
                srcs, dest = pos, target_dir
            else:
                srcs, dest = (pos[:-1], pos[-1]) if len(pos) >= 2 else ([], None)
            if dest is not None:
                # DIR/basename(SRC) for each source; DIR itself may be an exact protected path;
                # `cp -R src/ DIR` and `rsync src/ DIR` copy src's contents into DIR itself
                targets = [dest] + [dest.rstrip("/") + "/" + os.path.basename(p.rstrip("/"))
                                    for p in srcs]
                if any(p.endswith(("/", "/.")) for p in srcs):
                    whole.append(dest)
            if base == "mv":
                whole += srcs                  # a rename removes the source
        for t in targets:
            found = self.protect_hit(t, "%s writes" % base)
            if found:
                return found
        for t in whole:
            found = self.protect_hit(t, "%s changes" % base, contains=True)
            if found:
                return found
        return None

    @staticmethod
    def find_targets(args):
        """find's start paths when its expression deletes or runs a writer on what it finds."""
        k = 0
        while k < len(args) and args[k] in ("-H", "-L", "-P", "-E", "-X", "-s", "-x", "-d"):
            k += 1
        starts = []
        while k < len(args) and not args[k].startswith(("-", "(", "!", ")", "\\(")):
            starts.append(args[k])
            k += 1
        expr = args[k:]
        writes = "-delete" in expr
        for j, a in enumerate(expr):
            if a in EXEC_OPTS and j + 1 < len(expr):
                cmd = _base(expr[j + 1])
                writes = writes or cmd in PROTECT_WRITE_CMDS or cmd in SHELLS or \
                    bool(INTERPRETER_RE.match(cmd)) or cmd in ("xargs", "env", "sudo")
            if a in ("-fprint", "-fprint0", "-fprintf", "-fls") and j + 1 < len(expr):
                starts.append(expr[j + 1])
                writes = True
        return (starts or ["."]) if writes else []

    @staticmethod
    def extract_targets(base, args):
        """tar -x / unzip: the directory the archive is unpacked into."""
        if base == "tar":
            mode = next((a for a in args if not a.startswith("--")), "")
            extracting = any(a in ("-x", "--extract", "--get") for a in args) or (
                re.fullmatch(r"-?[A-Za-z]*x[A-Za-z]*", mode) is not None)
            if not extracting:
                return []
            for j, a in enumerate(args):
                if a in ("-C", "--directory") and j + 1 < len(args):
                    return [args[j + 1]]
                if a.startswith("--directory="):
                    return [a.split("=", 1)[1]]
            return ["."]
        for j, a in enumerate(args):             # unzip [-o] archive -d DIR
            if a == "-d" and j + 1 < len(args):
                return [args[j + 1]]
        return ["."] if not any(a in ("-l", "-t", "-v", "-p", "-Z") for a in args) else []


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


# ---------------------------------------------------------------- read-only mode (T2)
# code-reviewer, security-auditor, verifier, plan-reviewer and claude-code-guide are read-only by
# role but hold Bash. For them (READONLY_TYPES) the no-push hook also runs this allowlist: tests,
# linters, type checkers and scanners; builds whose output goes to a scratch dir (./.claude-work/,
# $TMPDIR, /tmp); git and gh reads; inspection commands; `--version`/`--help`. Files are written
# in scratch dirs only (redirections, cp/mv/rm/mkdir/tee/..., archives, -o/--output values);
# git mutations, package installs, formatter write modes, network writes, sudo, pipes into a
# shell or interpreter, and commands the guard can't read are refused. Inline code (python -c,
# node -e, a heredoc into python -) passes only without file, process, module or network calls.
# What a test suite, a build or a script in scratch does once it runs is out of sight: this stops
# casual and injected mutations through the shell; the sandbox (settings.json) is the boundary.
READONLY_REASON = ("Blocked by the stack's read-only rule: %s runs read-only Bash only, and `%s` %s. "
                   "Allowed: tests, linters, type checkers and scanners; builds into scratch "
                   "(./.claude-work/<job>/ or $TMPDIR); git diff/log/show/status/blame and other "
                   "git reads; gh views; inspection (ls, cat, rg, jq, find without -delete/-exec "
                   "of a writer, --version, --help). Files are written in scratch dirs only. "
                   "Report the change you would make as a finding instead of making it.")
# inspection commands: they write nothing but their redirections (and the -o values below)
RO_PLAIN = {
    "ls", "cat", "head", "tail", "wc", "file", "stat", "du", "df", "pwd", "echo", "printf", "true",
    "false", "test", "[", "[[", "which", "whereis", "type", "date", "cal", "uname", "sw_vers", "id",
    "whoami", "groups", "hostname", "basename", "dirname", "realpath", "readlink", "sort", "uniq",
    "cut", "tr", "grep", "egrep", "fgrep", "zgrep", "rg", "ag", "ack", "tree", "jq", "xxd",
    "hexdump", "od", "strings", "diff", "cmp", "comm", "column", "nl", "fold", "fmt", "tac", "rev",
    "paste", "join", "shasum", "sha1sum", "sha256sum", "sha512sum", "md5", "md5sum", "b2sum",
    "cksum", "base64", "sleep", "seq", "expr", "bc", "locale", "getconf", "nproc", "ps", "uptime",
    "vm_stat", "iostat", "lsof", "otool", "nm", "objdump", "size", "zcat", "bzcat", "xzcat",
    "gzcat", "cd", "pushd", "popd", ":", "wait", "read", "unset", "local", "shopt", "hash",
    "exit", "return", "break", "continue", "dig", "nslookup", "host", "mdls", "mdfind",
    "system_profiler", "ioreg", "nvidia-smi", "tput", "clear", "iconv", "look", "tsort", "numfmt",
    "factor", "shuf", "apropos", "whatis", "ping", "traceroute", "netstat", "ifconfig", "sysctl",
    "pathchk", "mktemp", "cloc", "tokei", "scc", "gron", "xsv", "qsv", "bat", "difft", "delta",
    "wdiff", "colordiff", "z3", "cvc5", "set", "trap",
}
RO_OUT_OPTS_PLAIN = {"sort", "iconv", "shuf", "base64", "tree", "cloc", "scc", "xsv", "qsv"}
# wrappers: the command they run is checked; options that take a value, per wrapper
RO_WRAPPERS = {"time": {"-f", "--format", "-o", "--output"}, "nice": {"-n", "--adjustment"},
               "nohup": set(), "stdbuf": {"-i", "-o", "-e", "--input", "--output", "--error"},
               "timeout": {"-s", "--signal", "-k", "--kill-after"},
               "gtimeout": {"-s", "--signal", "-k", "--kill-after"}, "command": set(),
               "builtin": set(), "noglob": set(), "caffeinate": {"-t", "-w"}, "chronic": set(),
               "env": {"-u", "--unset"}, "exec": {"-a"}}
RO_KEYWORDS = {"if", "then", "else", "elif", "do", "while", "until", "!", "{", "}", "fi", "done"}
RO_VERSION_FLAGS = {"--version", "-V", "--help", "-h", "-help", "--usage"}
RO_WRITERS = {"mkdir", "touch", "rm", "rmdir", "unlink", "tee", "truncate", "chmod", "ln", "cp",
              "mv", "install", "rsync", "ditto", "dd", "shred"}
RO_WRITER_VALUE_OPTS = {
    "touch": {"-t", "-d", "-r", "--date", "--reference"}, "mkdir": {"-m", "--mode"},
    "install": {"-m", "--mode", "-o", "--owner", "-g", "--group", "-t", "--target-directory",
                "-S", "--suffix"},
    "cp": {"-t", "--target-directory", "-S", "--suffix"},
    "mv": {"-t", "--target-directory", "-S", "--suffix"},
    "ln": {"-t", "--target-directory", "-S", "--suffix"}, "truncate": TRUNCATE_VALUE_OPTS,
    "rsync": {"-e", "--rsh", "--exclude", "--include", "--filter", "-f", "--files-from",
              "--exclude-from", "--include-from", "--log-file", "--partial-dir", "--temp-dir",
              "-T", "--backup-dir", "--chmod", "--chown", "--rsync-path", "-B", "--block-size",
              "--compare-dest", "--copy-dest", "--link-dest", "--suffix"},
}
RO_CHMOD_FLAGS = {"-R", "-f", "-v", "-h", "-H", "-L", "-P", "-c", "--recursive", "--verbose",
                  "--changes", "--silent", "--quiet", "--no-preserve-root", "--preserve-root"}
# option names whose value is an output file or dir: must be scratch
RO_OUT_OPTS = {"-o", "--output", "--output-file", "--out", "--outdir", "--out-dir", "--outfile",
               "--report-path", "--report", "--sarif-output", "--json-output", "--junitxml",
               "--junit-xml", "--html", "--cov-report", "--basetemp", "--target-dir",
               "--build-dir", "--output-dir", "--log-file", "--result-log",
               "--test-reporter-destination", "--text-output", "--junit-xml-output",
               "--gitlab-sast-output", "--gitlab-secrets-output", "--vim-output",
               "--emacs-output"}
RO_TOOL_OUTS = {"pytest": RO_OUT_OPTS - {"-o"}, "py.test": RO_OUT_OPTS - {"-o"},
                "grype": {"--file"}, "syft": {"--file"}, "gitleaks": RO_OUT_OPTS | {"-r"}}
# `python -m X`: modules that only check, test or print
RO_PY_MODULES = {"pytest", "unittest", "doctest", "mypy", "pyright", "basedpyright", "pylint",
                 "flake8", "pyflakes", "pycodestyle", "pydocstyle", "bandit", "pip_audit",
                 "json.tool", "tabnanny", "py_compile", "compileall", "site", "sysconfig",
                 "platform", "tokenize", "ast", "dis", "ruff", "black", "isort", "semgrep",
                 "detect_secrets", "vulture", "radon", "xenon", "pipdeptree", "pip", "mccabe",
                 "codespell", "ty", "pyrefly", "coverage"}
# formatters: allowed only with a flag that makes them report instead of rewrite
RO_CHECK_ONLY = {
    "black": ({"--check", "--diff"}, set()),
    "isort": ({"--check", "--check-only", "-c", "--diff"}, set()),
    "prettier": ({"--check", "-c", "--list-different", "-l"}, {"--write", "-w"}),
    "rustfmt": ({"--check"}, set()), "gofmt": ({"-l", "-d"}, {"-w"}),
    "shfmt": ({"-d", "-l"}, {"-w", "--write"}), "clang-format": ({"--dry-run", "-n"}, {"-i"}),
    "autopep8": ({"--diff"}, {"-i", "--in-place"}), "yapf": ({"--diff", "-d"}, {"-i", "--in-place"}),
    "mdformat": ({"--check"}, set()), "stylua": ({"--check"}, set()),
    "taplo": ({"check", "--check"}, set()), "dprint": ({"check"}, {"fmt"}),
    "nixfmt": ({"--check", "-c"}, set()),
}
# linters, scanners and test runners: allowed; these arguments would change files or post results
RO_TOOLS = {
    "mypy": set(), "pyright": set(), "basedpyright": set(), "pylint": set(), "flake8": set(),
    "pyflakes": set(), "pycodestyle": set(), "pydocstyle": set(), "bandit": set(),
    "vulture": set(), "shellcheck": set(), "hadolint": set(), "actionlint": set(),
    "yamllint": set(), "vale": {"sync"}, "markdownlint": {"--fix", "-f"},
    "markdownlint-cli2": {"--fix"}, "eslint": {"--fix"}, "stylelint": {"--fix"},
    "golangci-lint": {"--fix"}, "staticcheck": set(), "govulncheck": set(),
    "codespell": {"-w", "--write-changes", "-i", "--interactive"},
    "typos": {"-w", "--write-changes"}, "lychee": set(), "gitleaks": set(), "trufflehog": set(),
    "osv-scanner": {"fix"}, "pip-audit": {"--fix"},
    "trivy": {"plugin", "clean", "server", "module", "registry"}, "grype": set(), "syft": set(),
    "checkov": set(), "tfsec": set(), "kube-linter": set(),
    "semgrep": {"--autofix", "ci", "publish", "login", "logout", "install-semgrep-pro"},
    "detect-secrets": {"audit"},
    "pytest": {"--snapshot-update", "--inline-snapshot", "--force-regen", "--regen-all"},
    "py.test": {"--snapshot-update", "--inline-snapshot"},
    "jest": {"-u", "--updateSnapshot"}, "vitest": {"-u", "--update"}, "mocha": set(),
    "ava": {"-u", "--update-snapshots"},
    "playwright": {"install", "install-deps", "codegen", "--update-snapshots", "-u", "open"},
    "cypress": {"open", "install"}, "ctest": set(), "ty": set(), "pyrefly": {"init"},
    "sqlfluff": {"fix", "format"}, "svelte-check": set(), "vue-tsc": set(),
    "cargo-deny": {"fix", "init"}, "radon": set(), "xenon": set(), "pipdeptree": set(),
    "lean": set(), "coverage": {"erase", "combine"},
}
RO_GIT_READ = {"diff", "log", "show", "status", "blame", "annotate", "grep", "ls-files", "ls-tree",
               "rev-parse", "rev-list", "describe", "cat-file", "merge-base", "shortlog",
               "for-each-ref", "name-rev", "count-objects", "whatchanged", "range-diff", "cherry",
               "check-ignore", "check-attr", "check-ref-format", "var", "help", "version",
               "show-ref", "show-branch", "diff-tree", "diff-files", "diff-index", "verify-commit",
               "verify-tag", "ls-remote"}
# git subcommands that only read when used with one of these words or flags
RO_GIT_LIST = {"branch": {"-a", "-r", "-v", "-vv", "--list", "-l", "--contains", "--merged",
                          "--no-merged", "--show-current", "--format", "--sort", "--points-at",
                          "--all", "--remotes", "--verbose", "--color", "--no-color", "--column",
                          "--no-column", "--abbrev", "--no-abbrev", "--ignore-case"},
               "tag": {"-l", "--list", "-n", "--contains", "--merged", "--no-merged", "--sort",
                       "--format", "--points-at", "--column", "--color", "--ignore-case"},
               "remote": {"-v", "--verbose", "show", "get-url"}, "stash": {"list", "show"},
               "worktree": {"list"}, "notes": {"list", "show"}, "submodule": {"status", "summary"},
               "lfs": {"ls-files", "status", "env"}, "sparse-checkout": {"list"},
               "bisect": {"log", "visualize", "view"}}
RO_GIT_BARE_OK = {"remote", "notes", "submodule"}       # the bare subcommand lists
RO_GIT_CONFIG_READ = {"--get", "--get-all", "--get-regexp", "--get-urlmatch", "--list", "-l",
                      "get", "list"}
RO_GIT_CONFIG_WRITE = {"--add", "--unset", "--unset-all", "--replace-all", "--rename-section",
                       "--remove-section", "-e", "--edit", "set", "unset", "rename-section",
                       "remove-section", "edit"}
RO_GH_VERBS = {"view", "list", "ls", "status", "checks", "diff", "verify", "logs"}
RO_NET_WRITE_FLAGS = {"-X", "--request", "-d", "--data", "--data-raw", "--data-binary",
                      "--data-urlencode", "--data-ascii", "-F", "--form", "--form-string", "-T",
                      "--upload-file", "--json", "--post-data", "--post-file", "--method",
                      "--body-data", "--body-file", "-K", "--config"}
# variables whose value runs code or moves programs, config or temp files
RO_EXEC_VAR_RE = re.compile(
    r"(?:PATH|LD_\w+|DYLD_\w+|BASH_ENV|ENV|PROMPT_COMMAND|PS[0-4]|IFS|SHELLOPTS|BASHOPTS|CDPATH|"
    r"TMPDIR|PYTHONSTARTUP|PYTHONHOME|PYTHONINSPECT|NODE_OPTIONS|NODE_PATH|PERL5OPT|PERL5LIB|"
    r"PERLLIB|RUBYOPT|RUBYLIB|JAVA_TOOL_OPTIONS|_JAVA_OPTIONS|JDK_JAVA_OPTIONS|GIT_\w+|EDITOR|"
    r"VISUAL|PAGER|MANPAGER|LESSOPEN|LESSCLOSE|SSH_ASKPASS|SUDO_ASKPASS|BROWSER|HISTFILE|ZDOTDIR|"
    r"XDG_CONFIG_HOME|HOME|SHELL|CARGO_HOME|RUSTC_WRAPPER|RUSTC|CC|CXX|MAKEFLAGS|NPM_CONFIG_\w+|"
    r"npm_config_\w+|UV_\w+|PIP_\w+)\Z")
RO_SAFE_VARS = {"GIT_TERMINAL_PROMPT", "GIT_OPTIONAL_LOCKS", "GIT_LITERAL_PATHSPECS",
                "GIT_NO_REPLACE_OBJECTS", "UV_NO_SYNC", "UV_FROZEN", "UV_OFFLINE", "UV_PYTHON",
                "UV_NO_PROGRESS", "UV_LOCKED", "PIP_DISABLE_PIP_VERSION_CHECK"}
RO_PAGER_VARS = {"PAGER", "GIT_PAGER", "MANPAGER"}
RO_SYSTEM_BIN = {"/bin", "/sbin", "/usr/bin", "/usr/sbin", "/usr/local/bin", "/opt/homebrew/bin",
                 "/opt/local/bin", "/Library/Developer/CommandLineTools/usr/bin"}
RO_VENV_BIN_RE = re.compile(r"/(?:\.?venv|venvs/[^/]+|\.tox/[^/]+)/bin\Z|/node_modules/\.bin\Z")
RO_DEVICES = {"/dev/null", "/dev/stdout", "/dev/stderr", "/dev/tty", "-"}
# inline code that writes, removes, runs, loads or talks to the network (heuristic: a determined
# payload can hide from any pattern; that is what the sandbox is for)
RO_CODE_BAD_RE = re.compile(
    MUTATE_CODE_RE.pattern + r"|\b(?:exec|eval|compile|__import__|getattr|setattr|globals|"
    r"execfile|spawn\w*|fork|execute|execSync|execFile\w*|shell_exec|passthru|proc_open|"
    r"file_put_contents|fopen|fwrite|mkdir|makedirs|mkdtemp|rm|rmSync|cp|cpSync|"
    r"createWriteStream|writelines|urlopen|urlretrieve|download\w*|install\.packages|"
    r"saveRDS|writeLines|sink)\s*\(|__builtins__|importlib|ctypes|\bpty\b|\bsocket\b|urllib|"
    r"\brequests\b|httpx|http\.client|aiohttp|\bfetch\s*\(|XMLHttpRequest|\bdgram\b|"
    r"\bos\.(?:system|exec\w*|spawn\w*|fork|kill|putenv|environ|getenv)|process\.(?:env|binding|"
    r"kill)|\.write\s*\(|\.(?:to_csv|to_parquet|to_json|to_excel|to_feather|to_pickle|to_sql|"
    r"savefig|save|savez\w*|tofile|dump)\s*\(|Pkg\.|Deno\.|Bun\.|IO\.(?:popen|write)|%x|\bqx\b|"
    r"\bENV\b|\bgetenv\b|\bsignal\.|\bshutil\b|\.(?:unlink|rmdir|rename|replace|mkdir|touch|"
    r"symlink_to|hardlink_to|chmod)\s*\(", re.I)


def _ro_scratch_roots(bases):
    """Scratch dirs: ./.claude-work of each base, $TMPDIR, the temp dirs (as given and resolved)."""
    import tempfile
    roots = [os.path.join(b, ".claude-work") for b in bases]
    for r in (os.environ.get("TMPDIR"), os.environ.get("CLAUDE_CODE_TMPDIR"),
              tempfile.gettempdir(), "/tmp", "/private/tmp", "/var/folders",
              "/private/var/folders"):
        if r and os.path.isabs(r):
            roots.append(r)
    out = []
    for r in roots:
        for v in (os.path.normpath(r), os.path.realpath(r)):
            if v not in out and v != "/":
                out.append(v)
    return out


def _within(path, root):
    return path == root or path.startswith(root.rstrip("/") + "/")


class _ReadOnly(object):
    """The read-only check of one Bash command for a READONLY_TYPES agent: the first violation as
    (what, why), else None. ctx (per simple command): piped (stdin comes from a pipe), herestr
    (<<< words), infile (< file), assigns (NAME=value prefixes), dynamic (run by xargs or find
    -exec, whose operands are chosen at run time)."""

    def __init__(self, ev):
        cwd = ev.get("cwd")
        first = [cwd] if isinstance(cwd, str) and os.path.isabs(cwd) else []
        self.bases = first + [b for b in path_bases(ev) if b not in first] or [os.getcwd()]
        self.home = os.path.expanduser("~")
        self.roots = _ro_scratch_roots(self.bases)
        conf = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.confs = [os.path.realpath(c) for c in (conf, os.environ.get("CLAUDE_CONFIG_DIR"),
                                                     os.path.join(self.home, ".claude")) if c]
        self.cwd = None                         # the last `cd DIR` seen
        self.deadline = time.monotonic() + DEADLINE_S
        self.budget = MAX_SCANS

    # -- paths
    def expand(self, p):
        if p[:1] == "$":
            p = re.sub(r"\A\$(?:HOME\b|\{HOME\})", lambda m: self.home, p)
        return os.path.expanduser(p) if p[:1] == "~" else p

    def resolve(self, p):
        return os.path.normpath(os.path.join(self.cwd or self.bases[0], self.expand(p)))

    def in_scratch(self, a):
        if any(_within(a, r) for r in self.roots):
            return True
        return ".claude-work" in a.split("/") and not any(_within(a, c) for c in self.confs)

    def scratch(self, p):
        """p names only scratch locations (lexically and after resolving symlinks; a glob by
        what it matches now)."""
        if p in RO_DEVICES:
            return True
        if not p or _expansion(self.expand(p)):
            return False
        a = self.resolve(p)
        cands = [a]
        if any(c in p for c in "*?["):
            import glob
            cands += glob.glob(a)[:256]
        return all(self.in_scratch(c) and self.in_scratch(os.path.realpath(c)) for c in cands)

    def runnable(self, p):
        """A script the agent may run: in scratch, or a test file of the project."""
        if not p or _expansion(self.expand(p)):
            return False
        if self.scratch(p):
            return True
        a = self.resolve(p)
        return bool(re.search(r"/(?:tests?|spec|specs|__tests__|testing)/", a) or
                    re.match(r"(?:tests?|test_.*|.*_tests?|.*\.(?:test|spec)|conftest)"
                             r"(?:\.[A-Za-z]+)?\Z", os.path.basename(a)))

    # -- commands
    def check(self, command, depth=0):
        if not isinstance(command, str) or not command.strip():
            return None
        self.budget -= 1
        if depth > MAX_NEST or self.budget < 0 or time.monotonic() > self.deadline:
            return (command[:120], "is nested too deeply or too long to check")
        try:
            text, heredocs, substs = _lex(command.replace("\x00", ""), self.deadline)
        except _TooComplex as exc:
            return (command[:120], "can't be checked (%s)" % exc)
        if len(text) > MAX_COMMAND:
            return (command[:120], "is too long to check")
        for inner, _pos in substs:              # $(...), `...`, <(...): all of them run
            found = self.check(inner, depth + 1)
            if found:
                return found
        for owner, body, quoted in heredocs:
            found = self.heredoc(owner, body, quoted, depth)
            if found:
                return found
        try:
            words = _shell_words(text)
        except ValueError:
            return (command[:120], "has unbalanced quotes")
        restore = _restorer(substs)
        seg, piped = [], False
        for w in words + [";"]:
            if SEP_RE.match(w):
                found = self.simple([restore(x) for x in seg], piped, depth) if seg else None
                if found:
                    return found
                seg, piped = [], w in ("|", "|&")
            else:
                seg.append(w)
        return None

    def heredoc(self, owner, body, quoted, depth):
        """A heredoc body is shell code when a shell or eval on its line reads it, program text
        when an interpreter does, data otherwise ($(...) in an unquoted body still runs)."""
        words = [_base(w) for w in re.findall(r"[^\s;&|()<>'\"`]+", owner)]
        found = None
        if _heredoc_runs_code(owner) or any(w in HEREDOC_RUNNERS for w in words):
            found = self.check(body, depth + 1)
        interp = next((w for w in words if INTERPRETER_RE.match(w)), None)
        if not found and interp:
            found = self.code(body, owner.strip()[:80], self.family(interp))
        for inner in ([] if quoted or found else _raw_substs(body)):
            found = found or self.check(inner, depth + 1)
        return found

    def simple(self, words, piped, depth):
        """One simple command: redirections, NAME=value prefixes, then the program."""
        ctx = {"piped": piped, "herestr": [], "infile": None, "assigns": {}, "dynamic": False}
        args, k = [], 0
        while k < len(words):
            w = words[k]
            if w.isdigit() and k + 1 < len(words) and (REDIR_OP_RE.match(words[k + 1])
                                                        or words[k + 1] in (">|", "<>")):
                k += 1
                continue
            if REDIR_OP_RE.match(w) or w in (">|", "<>"):
                target = words[k + 1] if k + 1 < len(words) else ""
                if w == "<<<":
                    ctx["herestr"].append(target)
                elif w == "<":
                    ctx["infile"] = target
                elif ">" in w and not (w in (">&", "<&") and (target.isdigit() or target == "-")):
                    if not self.scratch(target):
                        return (" ".join(words)[:160], "redirects output to %s, outside the "
                                "scratch dirs" % target)
                k += 2
                continue
            args.append(w)
            k += 1
        while args and (ASSIGN_RE.match(args[0]) or args[0] in RO_KEYWORDS):
            if ASSIGN_RE.match(args[0]):
                bad = self.assign(args[0])
                if bad:
                    return bad
                name, _, value = args[0].partition("=")
                ctx["assigns"][name.rstrip("+")] = value
            args = args[1:]
        if not args or args[0] in ("for", "select", "in", "esac", "]]", "]", "fi", "done"):
            return None                         # an assignment, a loop header, a lone keyword
        return self.command(args, ctx, depth)

    def assign(self, word):
        name, _, value = word.partition("=")
        name = name.rstrip("+")
        if name in RO_SAFE_VARS or (name in RO_PAGER_VARS and value in ("", "cat", "less")):
            return None
        if RO_EXEC_VAR_RE.match(name):
            return (word[:160], "sets %s, which can run commands or move programs, config or "
                                "temp files" % name)
        return None

    def command(self, args, ctx, depth):
        what = " ".join(args)[:160]
        head = args[0]
        if head in ("case", "function") or head.endswith("()"):
            return (what, "is a case statement or a function definition, too complex to check")
        if _expansion(self.expand(head)):
            return (what, "names its program in a variable or substitution")
        if "/" in head:
            return self.by_path(head, args, ctx, depth, what)
        base, rest = head, args[1:]
        if base in RO_WRAPPERS:
            return self.wrapper(base, rest, ctx, depth, what)
        if base in ("sudo", "doas", "su", "runuser", "pkexec"):
            return (what, "runs as another user")
        if len(rest) == 1 and rest[0] in RO_VERSION_FLAGS and base not in SHELLS \
                and not INTERPRETER_RE.match(base):
            return None
        if base in RO_PLAIN:
            return self.plain(base, rest, ctx, depth, what)
        if base in RO_WRITERS:
            return self.writes(base, rest, ctx, what)
        if base in ("sed", "gsed", "yq"):
            return self.sed(base, rest, ctx, what)
        if base in ("awk", "gawk", "mawk", "nawk"):
            return self.awk(rest, what)
        if base in ("find", "xargs", "fd"):
            return self.runner(base, rest, ctx, depth, what)
        if base in SHELLS or base in ("eval", "source", "."):
            return self.shell(base, rest, ctx, depth, what)
        if INTERPRETER_RE.match(base):
            return self.interpreter(base, rest, ctx, depth, what)
        if base == "git":
            return self.git(rest, what)
        if base == "gh":
            return self.gh(rest, what)
        if base in ("curl", "wget", "http", "https", "xh"):
            return self.net(base, rest, what)
        if base in RO_CHECK_ONLY:
            need, bad = RO_CHECK_ONLY[base]
            if any(a in bad for a in rest) or not any(a in need for a in rest):
                return (what, "rewrites files (allowed only with %s)" % " or ".join(sorted(need)))
            return self.outputs(rest, what)
        if base in RO_TOOLS:
            return self.linter(base, rest, ctx, depth, what)
        return self.tool(base, rest, ctx, depth, what)

    def by_path(self, head, args, ctx, depth, what):
        a = self.resolve(head)
        d = os.path.dirname(a)
        user_bins = [os.path.join(self.home, x) for x in (".local/bin", ".cargo/bin", "go/bin")]
        if d in RO_SYSTEM_BIN or d in user_bins or RO_VENV_BIN_RE.search(d) or \
                re.search(r"(?:\A|/)(?:gradlew|mvnw)\Z", head):
            return self.command([_base(head)] + args[1:], ctx, depth)
        if self.runnable(head):
            return None                         # built or written into scratch, or a test script
        return (what, "runs a program outside the scratch dirs and tests (run the project's "
                      "tests or linters by name)")

    def wrapper(self, base, rest, ctx, depth, what):
        if base == "command" and rest[:1] and rest[0] in ("-v", "-V"):
            return None
        if base == "env" and all(ASSIGN_RE.match(a) or a.startswith("-") for a in rest):
            return (what, "prints the environment (it can hold keys)")
        value_opts, k = RO_WRAPPERS[base], 0
        while k < len(rest):
            a = rest[k]
            if ASSIGN_RE.match(a) and base == "env":
                bad = self.assign(a)
                if bad:
                    return bad
                k += 1
            elif base == "env" and a.split("=")[0] in ("-S", "--split-string"):
                return self.check(" ".join(rest[k + 1:]), depth + 1)
            elif base == "env" and a.split("=")[0] in ("-C", "--chdir"):
                return (what, "changes directory inside env (cd first)")
            elif base == "time" and a.split("=")[0] in ("-o", "--output"):
                val = a.split("=", 1)[1] if "=" in a else (rest[k + 1] if k + 1 < len(rest) else "")
                if not self.scratch(val):
                    return (what, "writes %s outside the scratch dirs" % val)
                k += 1 if "=" in a else 2
            elif a == "--":
                k += 1
                break
            elif a.startswith("-"):
                k += 2 if a in value_opts else 1
            elif base in ("timeout", "gtimeout") and _duration(a):
                k += 1
                break
            else:
                break
        return self.command(rest[k:], ctx, depth) if rest[k:] else None

    # -- families
    def outputs(self, rest, what, names=RO_OUT_OPTS):
        """Values of output options (-o, --output, --report-path, ...) must be scratch."""
        for j, a in enumerate(rest):
            name, eq, val = a.partition("=")
            if name not in names:
                continue
            val = val if eq else (rest[j + 1] if j + 1 < len(rest) else "")
            if name == "--cov-report":
                kind, colon, val = val.partition(":")
                if not colon:
                    if kind.split("-")[0] in ("html", "xml", "json", "lcov", "markdown"):
                        return (what, "writes a coverage report into the project (use "
                                      "--cov-report=%s:./.claude-work/<job>/cov)" % kind)
                    continue
            if val and not val.startswith("-") and not self.scratch(val):
                return (what, "writes %s outside the scratch dirs" % val)
        return None

    def linter(self, base, rest, ctx, depth, what):
        bad = [a for a in rest if a in RO_TOOLS[base] or a.split("=", 1)[0] in RO_TOOLS[base]]
        if bad:
            return (what, "changes files or posts results (%s)" % bad[0])
        if base == "coverage":
            return self.coverage(rest, ctx, depth, what)
        if base in ("grype", "syft"):                      # -o FORMAT=FILE
            for j, a in enumerate(rest):
                if a.split("=")[0] in ("-o", "--output"):
                    val = a.split("=", 1)[1] if a.startswith("--output=") else \
                        (rest[j + 1] if j + 1 < len(rest) else "")
                    if "=" in val and not self.scratch(val.split("=", 1)[1]):
                        return (what, "writes %s outside the scratch dirs" % val.split("=", 1)[1])
        return self.outputs(rest, what, RO_TOOL_OUTS.get(base, RO_OUT_OPTS))

    def plain(self, base, rest, ctx, depth, what):
        pos = [a for a in rest if not a.startswith("-")]
        if base in ("cd", "pushd"):
            if pos and not _expansion(self.expand(pos[0])):
                self.cwd = self.resolve(pos[0])
            return None
        if base == "trap":
            code = rest[0] if rest and rest[0] not in ("-", "--", "-l", "-p") else ""
            return self.check(code, depth + 1) if code.strip() else None
        if base == "set":
            return None if rest and rest[0][:1] in "-+" else \
                (what, "prints every shell variable (they can hold keys)")
        if base == "sysctl" and any(a == "-w" or "=" in a for a in rest):
            return (what, "changes a kernel setting")
        if base == "sort" and any(a.startswith("--compress-program") for a in rest):
            return (what, "runs a compression program")
        if base == "rg" and any(a.split("=")[0] == "--pre" for a in rest):
            return (what, "runs a preprocessor command (rg --pre)")
        if base == "mktemp":
            tdir = next((rest[j + 1] for j, a in enumerate(rest)
                         if a in ("-p", "--tmpdir") and j + 1 < len(rest)), None)
            if any(not self.scratch(p) for p in pos if "/" in p) or \
                    (tdir and not self.scratch(tdir)):
                return (what, "creates a file outside the scratch dirs")
            return None
        if base in ("uniq", "xxd") and len(pos) >= 2 and not self.scratch(pos[1]):
            return (what, "writes %s outside the scratch dirs" % pos[1])
        if base in RO_OUT_OPTS_PLAIN:
            return self.outputs(rest, what, {"-o", "--output", "--out"})
        return None

    def writes(self, base, rest, ctx, what):
        if ctx["dynamic"]:
            return (what, "writes or removes paths chosen at run time (xargs, find -exec)")
        if base == "chmod":
            k = 0
            while k < len(rest) and rest[k] in RO_CHMOD_FLAGS:
                k += 1
            reference = any(a.startswith("--reference") for a in rest)
            pos = [a for a in rest[k:] if not a.startswith("--reference")]
            targets = pos if reference else pos[1:]
        elif base == "dd":
            targets = [a[3:] for a in rest if a.startswith("of=")]
        else:
            pos = _operands(rest, RO_WRITER_VALUE_OPTS.get(base, ()))
            tdir = next((a.split("=", 1)[1] if "=" in a else
                         (rest[j + 1] if j + 1 < len(rest) else "")
                         for j, a in enumerate(rest)
                         if a.split("=")[0] in ("-t", "--target-directory")), None)
            if base in ("cp", "install", "rsync", "ditto", "ln", "mv") and not (
                    base == "install" and any(a in ("-d", "-D", "--directory") for a in rest)):
                links = base == "ln" or any(
                    a in ("-l", "--link", "-s", "--symbolic-link", "-H", "--hard-links")
                    or a.startswith("--link-dest")
                    or (base == "cp" and re.fullmatch(r"-[A-Za-z]*[ls][A-Za-z]*", a)) for a in rest)
                if base == "ln" and len(pos) == 1 and not tdir:
                    pos = pos + [os.path.basename(pos[0].rstrip("/")) or "."]
                dest = [tdir] if tdir else pos[-1:]
                srcs = pos if tdir else pos[:-1]
                removes = base == "mv" or "--remove-source-files" in rest
                targets = dest + (srcs if removes or links else [])
            else:
                targets = pos
        for t in targets:
            if not self.scratch(t):
                return (what, "writes, links, removes or changes %s, outside the scratch dirs" % t)
        return self.outputs(rest, what, {"--log-file", "--backup-dir", "--temp-dir",
                                         "--partial-dir"}) if base == "rsync" else None

    def sed(self, base, rest, ctx, what):
        if base == "yq":
            inplace = any(a in ("-i", "--inplace") for a in rest)
        else:
            inplace = any(a == "--in-place" or a.startswith("--in-place=") or
                          (not a.startswith("--") and re.match(r"-[nEersuzl0-9]*i", a))
                          for a in rest)
        vals, scripts, k = [], [], 0
        while k < len(rest):
            a = rest[k]
            if a in ("-e", "--expression") and k + 1 < len(rest):
                scripts.append(rest[k + 1])
                k += 2
                continue
            if base != "yq" and (a in ("-f", "--file") or a.startswith("--file=")):
                return (what, "runs a sed script file")
            if not a.startswith("-") or a == "-":
                vals.append(a)
            k += 1
        if not scripts and vals:
            scripts, vals = vals[:1], vals[1:]
        if inplace and (ctx["dynamic"] or not vals or not all(self.scratch(v) for v in vals)):
            return (what, "edits files in place outside the scratch dirs")
        if base != "yq":
            for s in scripts:
                if re.search(r"(?:\A|[;{}\n])\s*[0-9,$!~+]*\s*[weW](?:\s|\Z)|/[gpIiMm0-9]*[weW]"
                             r"(?:\s|\Z|;|\})", s):
                    return (what, "writes files or runs commands from a sed script (w, W, e)")
        return None

    def awk(self, rest, what):
        progs, k = [], 0
        while k < len(rest):
            a = rest[k]
            if a in ("-F", "-v") and k + 1 < len(rest):
                k += 2
                continue
            if a in ("-e", "--source") and k + 1 < len(rest):
                progs.append(rest[k + 1])
                k += 2
                continue
            if a in ("-f", "--file") or (a.startswith("-f") and len(a) > 2) or a in (
                    "-i", "--include", "-l", "--load", "-E", "--exec"):
                return (what, "runs awk program files or extensions")
            if a == "--":
                k += 1
                break
            if not a.startswith("-"):
                break
            k += 1
        if not progs and k < len(rest):
            progs.append(rest[k])
        for p in progs:
            if re.search(r"system\s*\(|\|\s*getline|getline\s*<|\bprintf?\b[^;{}]*[>|]|\|&|"
                         r"fflush|close\s*\(|@load|@include", p):
                return (what, "runs commands or writes files from awk")
        return None

    def runner(self, base, rest, ctx, depth, what):
        inner_ctx = dict(ctx, dynamic=True, piped=False, herestr=[], infile=None)
        if base in ("find", "fd"):
            execs = EXEC_OPTS if base == "find" else {"-x", "--exec", "-X", "--exec-batch"}
            for j, a in enumerate(rest):
                if a == "-delete":
                    return (what, "deletes files")
                if a in ("-fprint", "-fprint0", "-fprintf", "-fls") and j + 1 < len(rest) \
                        and not self.scratch(rest[j + 1]):
                    return (what, "writes %s outside the scratch dirs" % rest[j + 1])
                if a in execs:
                    end = next((m for m in range(j + 1, len(rest))
                                if rest[m] in (";", "+", "\\;")), len(rest))
                    inner = [x for x in rest[j + 1:end] if x not in ("{}", "{/}", "{.}", "{//}")]
                    found = self.command(inner, inner_ctx, depth + 1) if inner else None
                    if found:
                        return found
            return None
        k = 0                                   # xargs [options] command args
        while k < len(rest) and rest[k].startswith("-"):
            k += 2 if rest[k] in ("-I", "-n", "-P", "-L", "-s", "-d", "-E", "-a", "-R", "-S",
                                  "--delimiter", "--arg-file", "--max-args",
                                  "--max-procs") else 1
        return self.command(rest[k:], inner_ctx, depth + 1) if rest[k:] else None

    def stdin_program(self, ctx, depth, what, as_code=None):
        """A shell or interpreter reading its program on stdin: a heredoc (checked already), a
        here-string or a scratch/test file; never a pipe."""
        if ctx["piped"] or ctx["dynamic"]:
            return (what, "runs commands piped in from another command")
        for s in ctx["herestr"]:
            found = as_code(s) if as_code else self.check(s, depth + 1)
            if found:
                return found
        if ctx["infile"] and not self.runnable(ctx["infile"]):
            return (what, "runs a script outside the scratch dirs and tests")
        return None

    def shell(self, base, rest, ctx, depth, what):
        if base == "eval":
            return self.check(" ".join(rest), depth + 1)
        if base in ("source", "."):
            if rest and (self.runnable(rest[0]) or re.search(
                    r"/(?:\.?venv|venvs/[^/]+)/bin/activate(?:\.\w+)?\Z", self.resolve(rest[0]))):
                return None
            return (what, "runs a script file outside the scratch dirs and tests in this shell")
        if base in PWSH:
            return (what, "runs PowerShell, which this check can't read")
        code, _k = _Scan.shell_code(rest)
        if code is not None:
            return self.check(code, depth + 1)
        k = 0
        while k < len(rest) and rest[k][:1] in "-+" and rest[k] != "--":
            k += 2 if rest[k] in ("-o", "+o", "-O", "+O", "--rcfile", "--init-file") else 1
        stdin = any(re.fullmatch(r"-[A-Za-z]*s[A-Za-z]*", a) for a in rest[:k])
        if rest[k:k + 1] == ["--"]:
            k += 1
        if k < len(rest) and not stdin:
            return None if self.runnable(rest[k]) else \
                (what, "runs a script outside the scratch dirs and tests")
        return self.stdin_program(ctx, depth, what)

    # interpreters: (code flags, module flag, options that take a value, preload options)
    INTERP = {
        "python": (re.compile(r"-[A-Za-z]*c"), re.compile(r"-[A-Za-z]*m"),
                   {"-W", "-X", "--check-hash-based-pycs"}, set()),
        "node": (re.compile(r"-e|--eval|-p|--print|-pe|-ep"), None,
                 {"--input-type", "--env-file", "-C", "--conditions", "--test-reporter",
                  "--test-name-pattern", "--test-concurrency", "--title", "--stack-size",
                  "--test-reporter-destination", "-r", "--require", "--import", "--loader",
                  "--experimental-loader"},
                 {"-r", "--require", "--import", "--loader", "--experimental-loader"}),
        "perl": (re.compile(r"-(?![MmIxCdDV])[A-Za-z0-9]*[eE]"), None, {"-x"}, set()),
        "ruby": (re.compile(r"-(?![rIECKx])[A-Za-z]*e"), None, {"-r", "-I", "-C", "-E", "-K"},
                 {"-r"}),
        "php": (re.compile(r"-r"), None, {"-d", "-c", "-z"}, set()),
        "lua": (re.compile(r"-e"), None, {"-l"}, {"-l"}),
        "julia": (re.compile(r"-e|-E|--eval|--print"), None,
                  {"-t", "--threads", "-p", "--procs", "-L", "--load", "-J", "--sysimage",
                   "-C", "--cpu-target", "-O", "--machine-file"}, {"-L", "--load"}),
        "Rscript": (re.compile(r"-e"), None, set(), set()),
    }

    @staticmethod
    def family(base):
        fam = re.sub(r"[\d.]*(?:\.exe)?\Z", "", base)
        return {"pypy": "python", "nodejs": "node", "luajit": "lua", "bun": "node"}.get(fam, fam)

    def interpreter(self, base, rest, ctx, depth, what):
        fam = self.family(base)
        if fam == "osascript":
            return (what, "runs AppleScript, which can run any command")
        if base.startswith(("deno", "bun")):
            found = self.js_runtime(base, rest, ctx, depth, what)
            if found != "fallthrough":
                return found
        if fam not in self.INTERP:
            return (what, "is not on the read-only list")
        code_re, mod_re, value_opts, preload = self.INTERP[fam]
        if fam in ("perl", "ruby") and any(re.match(r"-(?![MmIxCdDVrEK-])[A-Za-z0-9]*i", a)
                                           for a in rest):
            files = [a for a in rest if not a.startswith("-")][1:] if not any(
                code_re.fullmatch(a) for a in rest) else \
                [a for j, a in enumerate(rest) if not a.startswith("-") and j > 0
                 and not code_re.fullmatch(rest[j - 1])]
            if ctx["dynamic"] or not files or not all(self.scratch(f) for f in files):
                return (what, "edits files in place outside the scratch dirs")
        k, inline = 0, False
        while k < len(rest):
            a = rest[k]
            if a == "--":
                k += 1
                break
            name = a.split("=", 1)[0]
            if code_re.fullmatch(a) and k + 1 < len(rest):
                inline = True
                found = self.code(rest[k + 1], what, fam)
                if found:
                    return found
                k += 2
                continue
            if mod_re is not None and mod_re.fullmatch(a) and k + 1 < len(rest):
                return self.py_module(rest[k + 1], rest[k + 2:], ctx, depth, what)
            if name in preload or (fam in ("perl", "ruby") and a[:2] in ("-M", "-r") and
                                   len(a) > 2):
                val = a.split("=", 1)[1] if "=" in a else a[2:] if a[:2] in ("-M", "-r") and \
                    len(a) > 2 else (rest[k + 1] if k + 1 < len(rest) else "")
                if val.startswith((".", "/", "~")) and not self.runnable(val):
                    return (what, "preloads code from outside the scratch dirs and tests")
            if fam == "node" and a == "--test":
                return None                     # node's test runner on the files that follow
            if fam == "php" and a == "-S":
                return (what, "starts a server")
            if fam == "php" and a == "-f" and k + 1 < len(rest):
                return None if self.runnable(rest[k + 1]) else \
                    (what, "runs a script outside the scratch dirs and tests")
            if a in value_opts and "=" not in a:
                k += 2
                continue
            if a == "-" or not a.startswith("-"):
                break
            k += 1
        if inline:
            return None
        if k < len(rest) and rest[k] != "-":
            return None if self.runnable(rest[k]) else \
                (what, "runs a script outside the scratch dirs and tests")
        return self.stdin_program(ctx, depth, what, lambda s: self.code(s, what, fam))

    def js_runtime(self, base, rest, ctx, depth, what):
        """deno and bun subcommands; "fallthrough" for bun running code like node."""
        pos = [a for a in rest if not a.startswith("-")]
        sub = pos[0] if pos else ""
        if base.startswith("deno"):
            if sub in ("test", "lint", "check", "info", "doc", "bench") or \
                    (sub == "fmt" and "--check" in rest):
                return None
            if sub == "eval" and len(pos) > 1:
                return self.code(pos[1], what, "node")
            if sub == "run" and len(pos) > 1:
                return None if self.runnable(pos[1]) else \
                    (what, "runs a script outside the scratch dirs and tests")
            if sub == "task" and len(pos) > 1 and self.test_script(pos[1]):
                return None
            return (what, "is not a read-only deno command")
        if sub == "test":
            return None
        if sub == "run" and len(pos) > 1 and self.test_script(pos[1]):
            return None
        if sub == "x" and len(pos) > 1:
            return self.command(rest[rest.index("x") + 1:], ctx, depth + 1)
        if sub in ("install", "i", "add", "remove", "rm", "update", "link", "unlink", "upgrade",
                   "create", "init", "publish", "pm", "build", "run", "patch"):
            return (what, "installs packages, builds or runs project scripts (bun %s)" % sub)
        return "fallthrough"

    @staticmethod
    def test_script(name):
        return bool(re.match(r"(?:test|tests|lint|check|typecheck|type-check|types|format:check|"
                             r"fmt:check|(?:test|lint|check):[\w:.-]+)\Z", name))

    def code(self, code, what, fam="python"):
        s = re.sub(r"\b(?:sys|process)\.(?:stdout|stderr)\.write\s*\(", "print(", code or "")
        bad = RO_CODE_BAD_RE.search(s) or \
            (fam in ("perl", "ruby", "php") and re.search(r"`|\bsystem\b|\bexec\b|\bopen\b", s)) or \
            (fam in ("julia", "Rscript") and re.search(r"\brun\s*\(|\bsystem2?\s*\(|"
                                                         r"file\.(?:remove|create|rename|copy)|"
                                                         r"\bwrite\s*\(", s)) or \
            (fam == "node" and re.search(r"\brequire\s*\(|\bimport\s*\(|\bfs\b", s))
        if bad:
            return (what, "runs inline code that writes files, starts processes, loads modules "
                          "or uses the network (put it in a script under ./.claude-work/<job>/ "
                          "if it must run)")
        return None

    def py_module(self, mod, rest, ctx, depth, what):
        if mod not in RO_PY_MODULES and mod.split(".")[0] not in ("pytest", "unittest", "mypy"):
            return (what, "runs a module that is not on the read-only list")
        if mod == "pip":
            return None if rest[:1] and rest[0] in ("list", "show", "freeze", "check", "debug",
                                                    "index", "--version", "-V") \
                else (what, "changes installed packages")
        name = {"pip_audit": "pip-audit", "detect_secrets": "detect-secrets"}.get(mod, mod)
        if name in RO_CHECK_ONLY or name in RO_TOOLS or name == "ruff":
            return self.command([name] + rest, ctx, depth + 1)
        return self.outputs(rest, what)

    def coverage(self, rest, ctx, depth, what):
        pos = [a for a in rest if not a.startswith("-")]
        sub = pos[0] if pos else ""
        if sub == "run":
            k = rest.index("run") + 1
            while k < len(rest) and rest[k].startswith("-"):
                if rest[k] == "-m" and k + 1 < len(rest):
                    return self.py_module(rest[k + 1], rest[k + 2:], ctx, depth, what)
                k += 2 if rest[k] in ("--rcfile", "--source", "--omit", "--include",
                                      "--data-file", "--context", "--concurrency") else 1
            return None if k < len(rest) and self.runnable(rest[k]) else \
                (what, "runs a script outside the scratch dirs and tests")
        if sub in ("html", "xml", "json", "lcov", "annotate"):
            if not any(a.split("=")[0] in ("-o", "-d", "--directory") for a in rest):
                return (what, "writes a report into the project (add -o or -d under "
                              "./.claude-work/<job>/)")
            return self.outputs(rest, what, {"-o", "-d", "--directory"})
        return None

    def git(self, rest, what):
        k = 0
        while k < len(rest) and rest[k].startswith("-"):
            opt = rest[k].split("=", 1)[0]
            if opt in ("-c", "--config-env"):
                attached = opt == "--config-env" and "=" in rest[k]
                val = rest[k].split("=", 1)[1] if attached else \
                    (rest[k + 1] if k + 1 < len(rest) else "")
                if GIT_EXEC_KEY_RE.match(val.split("=", 1)[0]):
                    return (what, "sets a git config key that runs a command")
                k += 1 if attached else 2
            elif opt == "--exec-path" and "=" in rest[k]:
                return (what, "runs git commands from another directory")
            elif opt in GIT_OPTS_WITH_VALUE and "=" not in rest[k]:
                k += 2
            else:
                k += 1
        if k >= len(rest):
            return None
        sub, args = rest[k], rest[k + 1:]
        if sub in ("diff", "log", "show", "whatchanged", "range-diff", "diff-tree"):
            found = self.outputs(args, what, {"--output"})
            if found:
                return found
            if any(a.startswith("--ext-diff") or a == "--textconv" for a in args):
                return (what, "runs the repository's configured diff programs")
        if sub in RO_GIT_READ:
            if sub == "grep" and any(a in ("-O", "--open-files-in-pager") or
                                     a.startswith(("--open-files-in-pager=", "-O")) for a in args):
                return (what, "opens files in a program")
            return None
        words = [a.split("=", 1)[0] for a in args]
        if sub == "config":
            if any(w in RO_GIT_CONFIG_READ for w in words) and \
                    not any(w in RO_GIT_CONFIG_WRITE for w in words):
                return None
        elif sub == "reflog":
            if not any(w in ("expire", "delete", "drop") for w in words):
                return None
        elif sub in ("branch", "tag"):
            pos = [a for a in args if not a.startswith("-")]
            flags = [w for w in words if w.startswith("-")]
            listing = any(f in ("--list", "-l", "--contains", "--merged", "--no-merged",
                                "--points-at") for f in flags) or (sub == "tag" and "-n" in flags)
            if all(f in RO_GIT_LIST[sub] for f in flags) and (not pos or listing):
                return None
        elif sub in RO_GIT_LIST:
            if (words[:1] and words[0] in RO_GIT_LIST[sub]) or (not words and sub in RO_GIT_BARE_OK):
                return None
        return (what, "changes the repository, its refs or its config (git %s)" % sub)

    def gh(self, rest, what):
        args, k = [], 0
        while k < len(rest):                    # global options that take a value
            if rest[k] in ("-R", "--repo", "--hostname"):
                k += 2
                continue
            args.append(rest[k])
            k += 1
        pos = [a for a in args if not a.startswith("-")]
        if not pos:
            return None
        if pos[0] == "auth":
            return None if pos[1:2] == ["status"] and not any(
                a.split("=")[0] in ("--show-token", "-t") for a in args) else \
                (what, "manages or prints GitHub credentials")
        if pos[0] == "api":
            return (what, "writes through the GitHub API") if _api_writes(args[1:], *GH_API[1:]) \
                else None
        if pos[0] in ("search", "status") or (len(pos) >= 2 and pos[1] in RO_GH_VERBS):
            return None
        return (what, "is not a read-only gh command (view, list, status, checks, diff, "
                      "search, api GET)")

    def net(self, base, rest, what):
        if base in ("http", "https", "xh"):
            pos = [a for a in rest if not a.startswith("-")]
            if not pos or pos[0].upper() not in ("GET", "HEAD"):
                return (what, "may send data (HTTPie: name the method GET or HEAD first)")
            if any(re.search(r"(?<![=:])(?::=|=|@)(?!=)", p) for p in pos[2:]):
                return (what, "sends data over the network")
            return self.outputs(rest, what, {"-o", "--output"})
        for j, a in enumerate(rest):
            name = a.split("=", 1)[0]
            if name in RO_NET_WRITE_FLAGS or (base == "curl" and re.fullmatch(
                    r"-[A-Za-z0-9#:]*[dFTXK][A-Za-z0-9#:]*", a)):
                if name in ("-X", "--request", "--method"):
                    m = a.split("=", 1)[1] if "=" in a else (rest[j + 1] if j + 1 < len(rest) else "")
                    if m.upper() in ("GET", "HEAD", "OPTIONS"):
                        continue
                return (what, "sends data over the network")
            if base == "curl" and (a in ("-O", "--remote-name", "--remote-name-all", "-J",
                                         "--remote-header-name") or
                                   re.fullmatch(r"-[A-Za-z0-9#:]*O[A-Za-z0-9#:]*", a)):
                return (what, "saves a download next to your files (use -o ./.claude-work/...)")
            outs = ("-o", "--output", "-D", "--dump-header", "-c", "--cookie-jar", "--trace",
                    "--trace-ascii", "--stderr", "--output-dir", "--etag-save", "--hsts",
                    "--alt-svc") if base == "curl" else \
                ("-O", "--output-document", "-P", "--directory-prefix", "-o", "--output-file",
                 "-a", "--append-output", "--save-cookies", "--warc-file")
            clustered_o = base == "curl" and a != "-o" and re.fullmatch(r"-[A-Za-z0-9#:]*o", a)
            wget_o = None if base != "wget" or a.startswith("--") or a in outs else \
                re.fullmatch(r"-[A-Za-z]*[OPoa](.*)", a)
            if wget_o:                            # -qO- / -qO FILE / -P DIR clustered
                val = wget_o.group(1) or (rest[j + 1] if j + 1 < len(rest) else "")
                if val and val != "-" and not self.scratch(val):
                    return (what, "writes %s outside the scratch dirs" % val)
            elif name in outs or clustered_o:
                val = a.split("=", 1)[1] if "=" in a else (rest[j + 1] if j + 1 < len(rest) else "")
                if val and val != "-" and not self.scratch(val):
                    return (what, "writes %s outside the scratch dirs" % val)
        if base == "wget" and not any(a.split("=", 1)[0] in ("-O", "--output-document", "-P",
                                                             "--directory-prefix", "--spider")
                                      or re.fullmatch(r"-[A-Za-z]*[OP].*", a) for a in rest):
            return (what, "saves a download in the working directory (use -O ./.claude-work/...)")
        return None

    def tool(self, base, rest, ctx, depth, what):
        pos = [a for a in rest if not a.startswith("-")]
        sub = pos[0] if pos else ""
        if base == "uv":
            return self.uv(rest, pos, sub, ctx, depth, what)
        if base in ("uvx", "npx", "pnpx", "bunx", "pipx"):
            k = 0
            if base == "pipx":
                if sub != "run":
                    return (what, "installs tools (pipx %s)" % sub)
                k = rest.index("run") + 1
            while k < len(rest) and rest[k].startswith("-"):
                k += 2 if rest[k] in ("--from", "--with", "-p", "--package", "--python",
                                      "--spec", "--index", "--with-requirements",
                                      "--with-editable", "--index-url") else 1
            if k < len(rest):
                name = rest[k].rsplit("/", 1)[-1].split("@")[0]
                name = {"typescript": "tsc", "pip_audit": "pip-audit"}.get(name, name)
                return self.command([name] + rest[k + 1:], ctx, depth + 1)
            return None
        if base in ("npm", "pnpm", "yarn"):
            if sub in ("test", "t", "tst") or (sub in ("run", "run-script") and len(pos) > 1
                                                and self.test_script(pos[1])):
                return None
            if base == "yarn" and self.test_script(sub):
                return None
            if base in ("pnpm", "yarn") and sub in ("exec", "dlx"):
                return self.command(rest[rest.index(sub) + 1:], ctx, depth + 1)
            if sub in ("ls", "list", "view", "info", "outdated", "explain", "why", "audit",
                       "config", "root", "bin", "prefix", "help", "doctor", "search", "query",
                       "licenses"):
                if sub == "audit" and "fix" in pos:
                    return (what, "changes dependencies (audit fix)")
                if sub == "config" and len(pos) > 1 and pos[1] not in ("get", "list", "ls"):
                    return (what, "changes the package manager's config")
                return self.outputs(rest, what)
            return (what, "installs packages, runs project scripts or builds into the project "
                          "(%s %s)" % (base, sub))
        if base == "cargo":
            if sub in ("test", "check", "clippy", "bench", "doc", "tree", "metadata", "search",
                       "audit", "deny", "outdated", "vet", "geiger", "nextest", "miri", "kani",
                       "llvm-cov", "udeps", "machete", "verify-project", "locate-project",
                       "pkgid", "read-manifest", "version", "help"):
                bad = sorted({"--fix", "--allow-dirty", "--allow-staged", "--bless"} & set(rest))
                if sub in ("audit", "deny") and ("fix" in pos or "init" in pos):
                    bad = ["fix/init"]
                return (what, "changes files (%s)" % bad[0]) if bad else self.outputs(rest, what)
            if sub == "fmt":
                return None if "--check" in rest else (what, "rewrites files (use --check)")
            if sub in ("build", "run"):
                tdir = next((a.split("=", 1)[1] if "=" in a else
                             (rest[j + 1] if j + 1 < len(rest) else "")
                             for j, a in enumerate(rest) if a.split("=")[0] == "--target-dir"),
                            None) or ctx["assigns"].get("CARGO_TARGET_DIR")
                if tdir and self.scratch(tdir):
                    return None
                return (what, "builds into the project (use --target-dir ./.claude-work/<job>/"
                              "target)")
            return (what, "changes the project or installs (cargo %s)" % sub)
        if base == "go":
            if sub in ("test", "vet", "list", "env", "version", "doc", "help") or \
                    (sub == "mod" and len(pos) > 1 and pos[1] in ("graph", "why", "verify")):
                if sub == "env" and any(a in ("-w", "-u") for a in rest):
                    return (what, "changes go's environment file")
                return self.outputs(rest, what, {"-o", "-coverprofile", "-cpuprofile",
                                                 "-memprofile", "-blockprofile", "-trace",
                                                 "-outputdir"})
            if sub == "build":
                o = next((rest[j + 1] for j, a in enumerate(rest) if a == "-o" and j + 1 < len(rest)),
                         None)
                return None if o and self.scratch(o) else \
                    (what, "builds into the project (use -o ./.claude-work/<job>/bin)")
            if sub == "run":
                return None if len(pos) > 1 and self.runnable(pos[1]) else \
                    (what, "runs a program outside the scratch dirs and tests")
            return (what, "changes the module or installs (go %s)" % sub)
        if base in ("make", "gmake"):
            targets = [a for a in rest if not a.startswith("-") and "=" not in a]
            if any(a.split("=")[0] in ("-f", "--file", "--makefile", "-C", "--directory",
                                       "--eval", "-E") for a in rest) or \
                    any("=" in a and not a.startswith("-") for a in rest):
                return (what, "runs another makefile or overrides make variables")
            if "-n" in rest or "--dry-run" in rest or "--just-print" in rest or \
                    (targets and all(re.match(r"(?:test|tests|check|lint|typecheck|vet|"
                                              r"fmt-check|format-check|test-[\w-]+|"
                                              r"check-[\w-]+|lint-[\w-]+)\Z", t) for t in targets)):
                return None
            return (what, "runs make targets beyond test/check/lint")
        if base in ("gradlew", "mvnw", "gradle", "mvn", "swift", "dotnet", "bazel", "mix", "sbt"):
            return None if sub in ("test", "check", "verify") else \
                (what, "builds, installs or changes the project")
        if base in ("cabal", "stack", "lake"):
            return None if sub in ("test", "check", "build", "env", "print-paths", "list", "path",
                                   "info", "lint") else \
                (what, "installs or changes the project")
        if base == "cmake":
            if "-E" in rest and "capabilities" in rest:
                return None
            b = next((rest[j + 1] if a in ("-B", "--build") and j + 1 < len(rest) else a[2:]
                      for j, a in enumerate(rest) if a in ("-B", "--build") or
                      (a.startswith("-B") and len(a) > 2)), None)
            if b and self.scratch(b) and not any(a in ("--install", "-P", "install") for a in rest):
                return None
            return (what, "configures or builds outside a scratch build dir (cmake -B "
                          "./.claude-work/<job>/build)")
        if base in ("ninja", "meson"):
            d = next((rest[j + 1] for j, a in enumerate(rest) if a == "-C" and j + 1 < len(rest)),
                     None) or (pos[1] if base == "meson" and sub in ("setup", "test", "compile")
                               and len(pos) > 1 else None)
            if "install" in pos:
                return (what, "installs")
            return None if d and self.scratch(d) else (what, "builds outside a scratch dir")
        if base == "tsc":
            if "--noEmit" in rest:
                return None
            if any(a.split("=")[0] == "--outDir" for a in rest):
                return self.outputs(rest, what, {"--outDir"})
            return (what, "emits JavaScript into the project (use --noEmit)")
        if base == "claude":
            if rest[:2] in (["mcp", "list"], ["mcp", "get"], ["plugin", "list"],
                            ["plugins", "list"], ["plugin", "details"]) \
                    or rest[:1] in (["--version"], ["-v"], ["--help"], ["-h"]):
                return None
            return (what, "is not a read-only claude command (--version, mcp list, mcp get, "
                          "plugin list)")
        if base == "tar":
            return self.tar(rest, what)
        if base == "unzip":
            if any(a in ("-l", "-t", "-v", "-p", "-Z", "-z") for a in rest):
                return None
            d = next((rest[j + 1] for j, a in enumerate(rest) if a == "-d" and j + 1 < len(rest)),
                     None)
            return None if d and self.scratch(d) else (what, "unpacks outside the scratch dirs")
        if base == "zip":
            return None if pos and self.scratch(pos[0]) and not any(
                a in ("-T", "-TT", "--unzip-command") for a in rest) \
                else (what, "writes an archive outside the scratch dirs")
        if base in ("gzip", "gunzip", "bzip2", "bunzip2", "xz", "unxz", "zstd"):
            if any(a in ("-c", "--stdout", "-l", "--list", "-t", "--test") or
                   re.fullmatch(r"-[A-Za-z0-9]*[ct][A-Za-z0-9]*", a) for a in rest):
                return None
            return None if pos and all(self.scratch(p) for p in pos) else \
                (what, "compresses or unpacks files in place")
        if base in ("pip", "pip3"):
            return None if sub in ("list", "show", "freeze", "check", "debug", "index") else \
                (what, "changes installed packages")
        if base == "brew":
            return None if sub in ("list", "ls", "info", "search", "config", "doctor", "deps",
                                   "uses", "outdated", "leaves", "desc", "--prefix",
                                   "--cellar", "--repository") or rest[:1] == ["--prefix"] \
                else (what, "changes installed software")
        if base == "docker":
            return None if sub in ("ps", "images", "inspect", "logs", "version", "info", "top",
                                   "stats", "history", "diff") else \
                (what, "runs or changes containers")
        if base == "kubectl":
            return None if sub in ("get", "describe", "logs", "explain", "version", "top",
                                   "api-resources", "api-versions", "cluster-info") else \
                (what, "changes the cluster")
        if base == "terraform":
            return None if sub in ("validate", "show", "version", "providers") or \
                (sub == "fmt" and "-check" in rest) else (what, "changes infrastructure or state")
        if base == "ruff":
            if sub == "format":
                return None if any(a in ("--check", "--diff") for a in rest) else \
                    (what, "rewrites files (use --check or --diff)")
            if sub == "clean":
                return (what, "removes caches in the project")
            if any(a in ("--fix", "--unsafe-fixes", "--add-noqa", "--fix-only") for a in rest) \
                    and "--no-fix" not in rest:
                return (what, "rewrites files (--fix)")
            return self.outputs(rest, what)
        if base == "biome":
            return (what, "rewrites files (--write)") if any(a.split("=")[0] in (
                "--write", "--apply", "--apply-unsafe", "--fix", "--unsafe") for a in rest) \
                else None
        if base == "codesign":
            return None if any(re.fullmatch(r"-d[v]*|--display|-v+|--verify|-dv+", a)
                               for a in rest) and not any(a in ("-s", "--sign", "-f", "--force",
                                                                "--remove-signature")
                                                          for a in rest) \
                else (what, "signs files")
        if base == "defaults":
            return None if sub in ("read", "read-type", "domains", "find") else \
                (what, "changes preferences")
        if base in ("sqlite3", "duckdb"):
            return None if any(a in ("-readonly", "--readonly") for a in rest) and \
                any(a in ("-safe", "--safe") for a in rest) else \
                (what, "can write the database or files (add -readonly -safe)")
        if base == "openssl":
            if sub in ("x509", "s_client", "version", "dgst", "verify", "asn1parse", "req",
                       "crl", "ciphers", "list", "rand", "base64", "sha256", "sha1", "md5"):
                return self.outputs(rest, what, {"-out", "-keyout"})
            return (what, "writes keys or files")
        if base in ("xcrun", "xcode-select", "pkgutil"):
            return None if any(a in ("--show-sdk-path", "--show-sdk-version", "-p",
                                     "--print-path", "--pkgs", "--files", "--pkg-info",
                                     "--find", "-f") for a in rest) else \
                (what, "is not a read-only form")
        return (what, "is not on the read-only list")

    def tar(self, rest, what):
        bad = [a for a in rest if a.split("=")[0] in ("-I", "--use-compress-program",
                                                      "--to-command", "--checkpoint-action",
                                                      "--info-script", "--new-volume-script",
                                                      "-F", "--rsh-command")]
        if bad:
            return (what, "runs a program from tar (%s)" % bad[0])
        mode = next((a for a in rest if not a.startswith("--")), "")
        if re.fullmatch(r"-?[A-Za-z]*t[A-Za-z]*", mode) or "--list" in rest:
            return None
        if re.fullmatch(r"-?[A-Za-z]*x[A-Za-z]*", mode) or "--extract" in rest or "--get" in rest:
            d = next((rest[j + 1] for j, a in enumerate(rest) if a in ("-C", "--directory")
                      and j + 1 < len(rest)), None)
            return None if d and self.scratch(d) else (what, "unpacks outside the scratch dirs")
        f = next((rest[j + 1] for j, a in enumerate(rest) if a in ("-f", "--file")
                  and j + 1 < len(rest)), None)
        if f is None and re.fullmatch(r"-?[A-Za-z]*f", mode):
            idx = rest.index(mode) + 1
            f = rest[idx] if idx < len(rest) else None
        return None if f and self.scratch(f) else \
            (what, "writes an archive outside the scratch dirs")

    def uv(self, rest, pos, sub, ctx, depth, what):
        if sub == "run":
            k = rest.index("run") + 1
            opts_with_value = {"--with", "--with-requirements", "--with-editable", "--python",
                               "-p", "--project", "--directory", "--index", "--extra",
                               "--group", "--only-group", "--env-file", "--package",
                               "--default-index", "--index-url", "--extra-index-url",
                               "--exclude-newer", "--cache-dir", "--config-file", "--no-group",
                               "--refresh-package", "--reinstall-package", "--upgrade-package"}
            while k < len(rest) and rest[k].startswith("-"):
                if rest[k].split("=")[0] == "--directory":
                    return (what, "changes directory inside uv (cd first)")
                if rest[k] == "-m" and k + 1 < len(rest):
                    return self.py_module(rest[k + 1], rest[k + 2:], ctx, depth, what)
                k += 2 if rest[k] in opts_with_value else 1
            if k < len(rest) and re.search(r"\.pyw?\Z", rest[k]):
                return None if self.runnable(rest[k]) else \
                    (what, "runs a script outside the scratch dirs and tests")
            return self.command(rest[k:], ctx, depth + 1) if rest[k:] else \
                (what, "opens a REPL")
        if sub in ("tree", "help") or rest[:1] in (["--version"], ["-V"]):
            return None
        if sub == "version":
            return (what, "changes the project version") if any(
                a.split("=")[0] in ("--bump", "--set") for a in rest) or len(pos) > 1 else None
        if sub == "pip" and len(pos) > 1 and pos[1] in ("list", "show", "freeze", "tree", "check"):
            return None
        if sub == "lock" and any(a in ("--check", "--dry-run", "--locked", "--check-exists")
                                 for a in rest):
            return None
        if sub == "sync" and any(a in ("--dry-run", "--check") for a in rest):
            return None
        if sub == "python" and len(pos) > 1 and pos[1] in ("list", "find", "dir"):
            return None
        if sub == "tool" and len(pos) > 1 and pos[1] in ("list", "dir"):
            return None
        if sub == "tool" and len(pos) > 1 and pos[1] == "run":
            return self.command(["uvx"] + rest[rest.index("run") + 1:], ctx, depth + 1)
        if sub == "cache" and len(pos) > 1 and pos[1] in ("dir", "size"):
            return None
        if sub == "export":
            return self.outputs(rest, what)
        if sub == "build":
            return self.outputs(rest, what, {"-o", "--out-dir"}) if any(
                a.split("=")[0] in ("-o", "--out-dir") for a in rest) else \
                (what, "builds into dist/ (use --out-dir ./.claude-work/<job>/dist)")
        if sub == "venv":
            return None if len(pos) > 1 and self.scratch(pos[1]) else \
                (what, "creates a venv outside the scratch dirs")
        return (what, "changes the environment or the project (uv %s)" % sub)


def readonly_violation(command, ev):
    """(what, why) when a READONLY_TYPES agent's Bash command is not read-only, else None."""
    return _ReadOnly(ev).check(command)


def remote_write_in(command):
    """(kind, what) for the first remote write in a shell command — kind "push" (git push and
    friends), "forge" (gh/tea/fj writes) or "opaque" (a git or forge command decided only at run
    time) — else None."""
    return _Scan(("push", "forge", "opaque")).scan(command)


def git_push_in(command):
    """True when a shell command runs `git [global options] push` (or send-pack, lfs/subtree push)."""
    return bool(_Scan(("push",)).scan(command))


def secrets_leak_in(command):
    """(kind, what) when a shell command runs mcp-headers/with-stack-env with --reveal, runs
    env/printenv/set/export under with-stack-env, or bash -x / sh -x / zsh -x on install.sh or
    doctor.sh — else None. Shares the same shell lexer and shell/eval/here-doc unwrapping as
    remote_write_in, so `bash -c "mcp-headers exa --reveal"` etc. are caught the same way
    `git push` is. The redacted default forms (`mcp-headers exa`, `with-stack-env --print-env`)
    pass."""
    return _Scan(("secrets",)).scan(command)


def forge_write_in(command):
    """True when a shell command writes to a forge through gh, tea or fj."""
    return bool(_Scan(("forge",)).scan(command))


def protected_write_in(command, ev):
    """(kind, what) when a shell command writes, deletes, renames or re-modes (redirection,
    cp/mv/install/rsync, tee, dd, sed/perl -i, rm/unlink/rmdir, find -delete/-exec, chmod/ln/touch/
    truncate, tar -x/unzip, inline interpreter code) a path already denied to Read/Edit/Write, one
    of the stack's own files in the config dir, or the hook state dir — else None. Needs `ev` (the hook
    event) to resolve relative paths the way the tool would and to read the deny rules that apply
    in this project. Closes the gap Claude Code's own protected-path check doesn't cover: it
    applies to Edit/Write, not to Bash, and bypassPermissions mode skips it even there."""
    return _Scan(("protect",), ev=ev).scan(command)


def no_push_main(raw):
    try:
        ev = json.loads(raw)
        ev = ev if isinstance(ev, dict) else {}
        command = (ev.get("tool_input") or {}).get("command")
        tool = ev.get("tool_name")
    except (ValueError, AttributeError, RecursionError):
        command, tool, ev = raw, None, {}    # unreadable event: judge the raw text
    if tool == "PowerShell" and isinstance(command, str):
        command = re.sub(r"`(.)", r"\1", command)          # PowerShell's escape: g`it
    text = str(command or "")
    bare = re.sub(r"['\"\\]", "", text)
    try:
        found = remote_write_in(command)
    except Exception as exc:                 # a parser bug: fail closed on git/gh/tea/fj commands
        if PUSH_RE.search(text):
            found = ("push", "git push")
        elif TRIGGER_RE.search(EXPANSION_RE.sub("", bare)):
            deny(GUARD_FAIL_REASON % ("%s: %s" % (type(exc).__name__, exc))[:200])
        else:
            found = None
    if not found:
        try:
            found = secrets_leak_in(command)
        except Exception as exc:              # a parser bug: fail closed on the same triggers
            if SECRETS_TRIGGER_RE.search(bare):
                deny(GUARD_FAIL_REASON % ("%s: %s" % (type(exc).__name__, exc))[:200])
            found = None
    if not found:
        try:
            found = protected_write_in(command, ev)
        except Exception as exc:              # a parser bug: fail closed on the same trigger
            if PROTECT_TRIGGER_RE.search(bare):
                deny(GUARD_FAIL_REASON % ("%s: %s" % (type(exc).__name__, exc))[:200])
            found = None
    if found:
        kind, what = found
        deny(FORGE_REASON % what if kind == "forge" else
             OPAQUE_REASON % what if kind == "opaque" else
             SECRETS_REASON % what if kind == "secrets" else
             PROTECT_REASON % what if kind == "protect" else NO_PUSH_REASON)
    agent_type = norm(ev.get("agent_type"))
    if agent_type in READONLY_TYPES and policy_on() and command is not None:
        try:
            bad = (("PowerShell", "runs PowerShell, which the read-only check can't read")
                   if tool == "PowerShell" else readonly_violation(command, ev))
        except Exception as exc:              # a parser bug: fail closed
            bad = (text[:120], "could not be checked (%s: %s)" % (type(exc).__name__, exc))
        if bad:
            deny(READONLY_REASON % (agent_type, bad[0][:160], bad[1][:300]))
    return 0


# ---------------------------------------------------------------- CLI
def print_policy():
    sys.stdout.write(json.dumps({"policy": POLICY, "leaves": LEAVES, "agents": AGENTS,
                                 "builtins": BUILTINS, "self_spawn": SELF_SPAWN,
                                 "copy_types": COPY_OF,
                                 "blackcat_tools": sorted(BLACKCAT_TOOLS)}) + "\n")
    return 0


def self_test():
    import shutil
    import tempfile
    problems = []
    known = set(AGENTS) | set(BUILTINS) | set(COPY_BASE)
    if len(set(AGENTS)) != len(AGENTS):
        problems.append("AGENTS has duplicates")
    if set(POLICY) != set(AGENTS) | set(COPY_BASE):
        problems.append("POLICY rows != AGENTS + copy types: %s"
                        % sorted(set(POLICY) ^ (set(AGENTS) | set(COPY_BASE))))
    for parent, row in POLICY.items():
        for child in row:
            if child not in known or child == "blackcat":
                problems.append("%s -> unknown or forbidden child %s" % (parent, child))
        if len(set(row)) != len(row):
            problems.append("%s row has duplicates" % parent)
        if parent in row:
            problems.append("%s may spawn its own type (copies go through COPY_TYPES)" % parent)
        for child in row:
            if child in COPY_BASE and COPY_BASE[child] != parent:
                problems.append("%s -> %s: only %s spawns its copies" % (parent, child,
                                                                          COPY_BASE[child]))
    for base, copy in COPY_OF.items():
        if base not in AGENTS or copy not in POLICY.get(base, []):
            problems.append("copy type %s: %s must list it" % (copy, base))
        if copy_rule_violation(copy, base) is None:
            problems.append("%s may spawn %s" % (copy, base))
    empty = sorted(p for p, row in POLICY.items() if not row)
    if empty != sorted(LEAVES):
        problems.append("LEAVES %s != empty rows %s" % (sorted(LEAVES), empty))
    if set(POLICY.get("blackcat", [])) != set(AGENTS) - {"blackcat", GOD}:
        problems.append("blackcat row must list every specialist but god-coder")
    spawners = sorted(p for p, row in POLICY.items() if GOD in row)
    if spawners != ["orchestrator"]:
        problems.append("only the orchestrator's row may list god-coder, not %s" % spawners)
    browsers = {p for p, row in POLICY.items() if "browser-operator" in row}
    if browsers != BROWSER_SPAWNERS:
        problems.append("only %s may list browser-operator, not %s"
                        % (sorted(BROWSER_SPAWNERS), sorted(browsers)))
    for never in ("blackcat", "orchestrator", GOD, "mlx-engineer", "cuda-engineer"):
        if never in SELF_SPAWN:
            problems.append("%s must not spawn copies of itself" % never)
    if parse_fanout_by_type(DEFAULT_FANOUT_BY_TYPE) != {
            "orchestrator": 10, "god-coder": 6, "main-coder": 6, "ninja-coder": 5, "researcher": 4,
            "planner": 8, "plan-reviewer": 8}:
        problems.append("STACK_MAX_FANOUT_BY_TYPE default does not parse")
    # Installed layout: <config>/hooks/agent_guard.py next to <config>/agents/*.md; install.sh
    # renders the copy types' files (the repo's dot-claude/ still holds __CLAUDE_DIR__).
    conf = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    agents_dir = os.path.join(conf, "agents")
    if os.path.isdir(agents_dir):
        try:
            with open(os.path.join(conf, "settings.json")) as f:
                installed = "__CLAUDE_DIR__" not in f.read()
        except OSError:
            installed = False
        want = AGENTS + (list(COPY_BASE) if installed else [])
        missing = [a for a in want if not os.path.isfile(os.path.join(agents_dir, a + ".md"))]
        if missing:
            problems.append("agent files missing in %s: %s" % (agents_dir, " ".join(missing)))
        # the MCP call cap reads maxTurns from these files: every subagent type must yield one
        unread = [a for a in want if a != "blackcat" and a not in missing
                  and agent_max_turns(a, agents_dir) is None]
        if unread:
            problems.append("MCP call cap: no maxTurns read from %s" % " ".join(unread))
    problems += budget_self_test()
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


def budget_self_test():
    """The transcript parser on a synthetic session: duplicate content-block lines counted once,
    an unfinished last line left for later, subagent files included, reads incremental."""
    import shutil
    import tempfile
    problems = []
    tmp = tempfile.mkdtemp(prefix="agent-guard-budget-")
    try:
        main = os.path.join(tmp, "s1.jsonl")
        os.makedirs(os.path.join(tmp, "s1", "subagents"))

        def call(mid, n, extra=""):
            return (json.dumps({"type": "assistant", "requestId": "r" + mid, "message": {
                "id": mid, "role": "assistant", "content": [],
                "usage": {"input_tokens": n, "cache_creation_input_tokens": n,
                          "cache_read_input_tokens": n, "output_tokens": 7}}}) + extra)
        with open(main, "w") as f:
            f.write(call("m1", 1, "\n") + call("m1", 1, "\n") + '{"type":"user"}\n'
                    + call("m2", 10, "\n") + call("m3", 100))            # m3 still being written
        with open(os.path.join(tmp, "s1", "subagents", "agent-a1.jsonl"), "w") as f:
            f.write(call("m4", 1000, "\n"))
        files = transcript_files({"transcript_path": main})
        states, stats = {}, scan_stats()

        def total():
            return sum(scan_transcript(p, states.setdefault(p, {}), time.monotonic() + 5, stats)
                       for p in session_transcripts(files))
        first = total()
        with open(main, "a") as f:
            f.write("\n" + call("m3", 100, "\n"))    # m3 finished; its duplicate line follows
        second = total()
        if (first, second) != (3 + 30 + 3000, 300) or stats["calls"] != 4:
            problems.append("token budget parser counted %s, %s (%d calls); expected 3033, 300 "
                            "(4 calls)" % (first, second, stats["calls"]))
    except Exception as exc:  # noqa: BLE001 - report, do not crash
        problems.append("token budget parser: %s: %s" % (type(exc).__name__, exc))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return problems


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


def pre_handler(tool):
    """This (default-mode) hook's PreToolUse handler for `tool`; None for the tools it leaves to
    other modes (`budget` mode then checks the token budgets of those)."""
    handler = HANDLERS.get(("PreToolUse", tool))
    if handler is None and tool.startswith("mcp__computer-use__"):
        handler = on_screen
    if handler is None and local_read_keys(tool) is not None:
        handler = on_local_read
    if handler is None and MEMORY_WRITE_TOOLS.match(tool):
        handler = on_memory_write
    return handler


def dispatch(ev):
    if ev.get("agent_id"):
        ev["agent_id"] = ident(ev["agent_id"])
    event, tool = ev.get("hook_event_name"), ev.get("tool_name") or ""
    if event == "PreToolUse":
        handler = pre_handler(tool)
    else:
        handler = HANDLERS.get((event, tool)) or LIFECYCLE.get(event)
    if handler is None:
        return
    d = sdir(ev.get("session_id"))
    log(d, ev)
    if event == "PreToolUse":
        # the token budgets and the MCP call cap first, before any lease or lock is taken; they
        # fail open
        try:
            budget_gate(ev, d)
            mcp_gate(ev, d)
        except SystemExit:
            raise
        except Exception as exc:  # noqa: BLE001
            warn("token budget: %s: %s" % (type(exc).__name__, exc))
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
        if argv[1] == "budget":
            return budget_main(sys.stdin.read())
        if argv[1] == "--check-budget":
            return check_budget(argv)
        if argv[1] == "blackcat-guard":
            raw = sys.stdin.read()
            try:
                blackcat_guard(raw, from_settings="--settings" in argv[2:])
            except SystemExit:
                raise
            except Exception as exc:
                guard_error("%s: %s" % (type(exc).__name__, exc))
            return 0
        sys.stderr.write("usage: agent_guard.py [--print-policy | --self-test | --check-budget [transcript] | "
                         "blackcat-guard [--settings] | budget | image-limit | no-push]\n")
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
