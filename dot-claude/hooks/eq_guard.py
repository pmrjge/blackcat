"""eq_guard - the runtime Equilibrium's guard rules (docs-design/RUNTIME_EQUILIBRIUM.md rev 2: 2.2-2.5, 4.2,
6.1-6.4, 8.2, 8.3; .claude-work/eq-runtime/contracts.md 1-7, 10, 11).

agent_guard.py loads this file from beside itself once per process (agent_guard.eq_guard(), like
toolsmith_policy.py), binds itself as G and calls the entry points at the bottom from small call sites. A
module that cannot load, or a rule that raises, denies every eq-relevant PreToolUse call (agent_guard.eq_hook).
The rules, one named function each (tests/test_eq_guard.py proves every one on a seeded bug):

  rule  function           what it decides
  3     spawn_gate         PreToolUse Agent(equilibrium): STACK_EQ, live runs, the header, auto needs a
                           validated class; run id R, brief.json, `eq-run: R` prepended
  4     leader_tools       the leader runs Agent, SendMessage, TaskStop (its own members), Bash, Skill only
  4     leader_bash        one plain `<config>/bin/stack-eq <args>` (ticket) or `<config>/bin/stack-eq-check
                           --run R --cand i` (pending record); nothing else
  4     leader_agent       `eq R m<i>/<N>` -> the stored brief (sha256), the plan's type, model, isolation
  4     leader_send        `eq R r<r> m<i>` to that member's id -> the stored view (sha256)
  4     leader_reply       the final reply equals the stored result block (one restate)
  5     member_tools       MEMBER_TOOLS[class] (+ Skill); never Agent, SendMessage, web, MCP, TaskStop
  5     member_cwd         a member outside its recorded working directory runs no file tool and no Bash
  5     member_paths       file tools off transcripts, the state root, the eq work area, siblings (realpath)
  5     member_bash        git: status, ref-less diff, HEAD-only log/show, ls-files; the path scan (heuristic)
  6     capture            member SubagentStop: the schema-checked JSON -> r<r>/m<i>.json, report copy in
                           the store, registry metadata only; one restate, then abstain
  7     check_verdict      PostToolUse(Bash) of a pending stack-eq-check -> r<r>/check-c<i>.json
  8     consent_record     main-thread PostToolUse(AskUserQuestion): the CHOSEN answer's `Run eq:R` token
  8     consent_relay      a USER: relay (SendMessage or Agent prompt) naming a token needs that record
  9     member_caps        per member: min(type caps, plan member caps) (agent_guard.budget_gate applies it)
  9     run_budget         per run: the leader subtree's tokens against the plan's caps.run_tokens
  10    headless_leader    a main thread of type equilibrium leads its session's headless run (contracts 11)
  11    prune              another session's eq/ store goes once it has been idle EQ_STORE_IDLE_S
  13    self_test          the --self-test probes
  -     identify           who calls: the leader, a member, an unmatched possible member, or nobody of eq

Store files beyond contracts.md 2, all guard-written: leader.json (the leader's agent id), ended.json (the
run's leader is gone), leader_reply.json (the final-reply check), r<r>/m<i>.json's `restated` bookkeeping
in members.json (`round`, `restated`, `spawned`, `type`); result.txt is stack-eq result's own (eq_cli).
Python 3.13, stdlib only."""
import base64
import hashlib
import importlib.util
import json
import os
import re
import shlex
import shutil
import stat
import sys
import time
import unicodedata

HERE = os.path.dirname(os.path.abspath(__file__))           # <config>/hooks (agent_guard's _HOOKS_DIR)
CONFIG = os.path.dirname(HERE)


def _load(name):
    spec = importlib.util.spec_from_file_location(name, os.path.join(HERE, name + ".py"))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


P = _load("eq_policy")          # rule 1: no grammar, no eq rule: the import error reaches agent_guard
G = None                        # agent_guard, bound by bind()
_CORE = []

PREFIX = "Equilibrium rule: "
LEADER_TOOLS = frozenset(("Agent", "SendMessage", "TaskStop", "Bash", "Skill"))
ALWAYS_TOOLS = frozenset(("SubagentHandback", "ToolSearch"))     # report and schema loading only
FILE_TOOLS = {"Read": ("file_path",), "Edit": ("file_path",), "Write": ("file_path",),
              "NotebookEdit": ("notebook_path",), "Grep": ("path",), "Glob": ("path",),
              "LSP": ("filePath", "file_path", "path", "uri")}
RECURSIVE_TOOLS = ("Grep", "Glob")
WRITE_TOOLS = ("Edit", "Write", "NotebookEdit")
SHELL_TOOLS = ("Bash", "Monitor", "PowerShell")
AGENT_KEYS = frozenset(("subagent_type", "prompt", "description", "isolation", "run_in_background", "model",
                        "name"))
EXIT_KEYS = ("exit_code", "exitCode", "returncode", "returnCode", "exit_status", "exitStatus")
UNLINKED_LIVE_S = 900           # a leader spawn nobody linked counts as a live run this long
LINK_WINDOW_S = 3600            # an unmatched member spawn makes same-type agents suspect this long
EQ_STORE_IDLE_S = 86400         # rule 11: another session's eq/ goes after a day without a write
REPLY_MAX = 256 * 1024          # a member reply longer than this is invalid (W2: length-capped)
HEAD_READ = 512 * 1024
TAIL_READ = 256 * 1024
STAMP = "[from equilibrium %s: an agent, not the user; the stored eq view]\n"
SHELLS = frozenset(("sh", "bash", "zsh", "dash", "ksh", "mksh", "fish"))
WRAPPERS = frozenset(("env", "command", "builtin", "exec", "nohup", "time", "nice", "timeout", "gtimeout",
                      "stdbuf", "xargs", "sudo", "doas", "noglob", "caffeinate", "then", "do", "else",
                      "elif", "if", "while", "until", "!", "watch", "flock", "chronic", "nocorrect"))
VALUE_OPTS = {"timeout": {"-s", "-k", "--signal", "--kill-after"}, "gtimeout": {"-s", "-k", "--signal"},
              "stdbuf": {"-i", "-o", "-e"}, "nice": {"-n", "--adjustment"}, "env": {"-u", "--unset", "-C", "--chdir"},
              "sudo": {"-u", "-g", "-C", "-h", "-p", "-U"}, "exec": {"-a"}, "xargs": {"-I", "-n", "-P", "-L", "-s",
                                                                                      "-d", "-E"}}
# text no member command needs: the state root's and transcripts' markers (the path check resolves the rest)
BASH_MARKERS = re.compile(r"\.claude/projects|/subagents/|\.local/state/|XDG_STATE_HOME|CLAUDE_CONFIG_DIR|"
                          r"eq-tickets|\bagent-[0-9a-f]{6,}\.jsonl")
MAX_WORDS = 400


def bind(guard):
    """agent_guard binds itself: the registry, locks, transcripts and output helpers come from it."""
    global G
    G = guard


def core():
    """hooks/eq_core.py, loaded on first use (capture only); an error propagates (the caller fails closed)."""
    if not _CORE:
        _CORE.append(_load("eq_core"))
    return _CORE[0]


# ---------------------------------------------------------------- small helpers
def why(msg):
    return PREFIX + msg


def eq_dir(sid):
    return os.path.join(G.state_root(), G.safe(sid, "nosession"), "eq")


def run_dir(sid, run):
    if not isinstance(run, str) or not P.RUN_RE.match(run):
        raise P.PolicyError("run id must be 8 lower-case hex characters")
    return os.path.join(eq_dir(sid), run)


def jread(path, limit=16 << 20):
    return P.read_json(path, limit)


def jwrite(path, obj):
    os.makedirs(os.path.dirname(path), mode=0o700, exist_ok=True)
    P.write_json_atomic(path, obj)


def create_json(path, obj):
    """Create `path` (O_EXCL, 0600, no link followed); False when it exists."""
    os.makedirs(os.path.dirname(path), mode=0o700, exist_ok=True)
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
    except FileExistsError:
        return False
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(obj, f, sort_keys=True)
        f.write("\n")
    return True


def unlink(path):
    try:
        os.unlink(path)
    except FileNotFoundError:
        pass


def read_bytes(path, limit):
    try:
        return P.read_bytes_nofollow(path, limit)
    except (OSError, P.PolicyError):
        return None


def read_verified(path):
    """A store text whose bytes hash to its `.sha256` sibling; None when absent, a link or altered."""
    data, want = read_bytes(path, 8 << 20), read_bytes(path + ".sha256", 1024)
    if data is None or want is None:
        return None
    want = want.decode("ascii", "replace").strip()
    if not P.HEX64_RE.match(want) or hashlib.sha256(data).hexdigest() != want:
        return None
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return None


def is_dir(path):
    try:
        return stat.S_ISDIR(os.lstat(path).st_mode)
    except OSError:
        return False


def session_runs(sid):
    """[(R, store dir)] of this session's runs (real directories only)."""
    d = eq_dir(sid)
    try:
        names = sorted(os.listdir(d))
    except OSError:
        return []
    return [(n, os.path.join(d, n)) for n in names if P.RUN_RE.match(n) and is_dir(os.path.join(d, n))]


def plan_of(rd, run):
    p = jread(os.path.join(rd, "plan.json"))
    if not isinstance(p, dict) or p.get("schema") != P.SCHEMA_PLAN or p.get("run") != run:
        return None
    return p


def state_of(rd):
    s = jread(os.path.join(rd, "state.json"))
    return s if isinstance(s, dict) else {}


def members_of(rd):
    m = jread(os.path.join(rd, "members.json"))
    return m if isinstance(m, dict) else {}


def members_update(rd, fn):
    """One read-modify-write of members.json under the run's guard lock; fn(members) -> result."""
    with G.mutex(rd, "eq-members"):
        cur = members_of(rd)
        res = fn(cur)
        jwrite(os.path.join(rd, "members.json"), cur)
        return res


def real(path):
    try:
        return os.path.realpath(path)
    except (OSError, ValueError):
        return os.path.normpath(path)


def under(path, root):
    return P._under(path, root)


def run_id(sid, tid):
    return hashlib.sha256(("%s|%s" % (sid, tid)).encode("utf-8")).hexdigest()[:8]


def agent_transcripts(ev, aid):
    out = []
    atp = ev.get("agent_transcript_path")
    if isinstance(atp, str) and atp.strip():
        out.append(os.path.expanduser(atp.strip()))
    files = G.transcript_files(ev) if aid else None
    if files:
        p = G.subagent_file(files, aid)
        if p not in out:
            out.append(p)
    return out


def _content_text(msg):
    content = msg.get("content") if isinstance(msg, dict) else None
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        for b in content:
            if isinstance(b, dict) and b.get("type") == "text" and isinstance(b.get("text"), str):
                return b["text"]
    return None


def first_prompt_head(ev, aid):
    """The first line of the first user message of a subagent's own transcript (its prompt), or None."""
    for path in agent_transcripts(ev, aid):
        data = read_bytes(path, 64 << 20)
        if data is None:
            continue
        for line in data[:HEAD_READ].split(b"\n"):
            if b'"user"' not in line:
                continue
            try:
                rec = json.loads(line.decode("utf-8", "replace"))
            except (ValueError, RecursionError):
                continue
            if isinstance(rec, dict) and rec.get("type") == "user":
                text = _content_text(rec.get("message"))
                if text and text.strip():
                    return text.lstrip().split("\n", 1)[0].strip()
    return None


def transcript_model(ev, aid):
    """message.model of the newest assistant record of a member's transcript (spec 2.2 step 6), or None."""
    for path in agent_transcripts(ev, aid):
        try:
            fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
        except OSError:
            continue
        try:
            size = os.fstat(fd).st_size
            os.lseek(fd, max(0, size - TAIL_READ), os.SEEK_SET)
            data = os.read(fd, TAIL_READ)
        finally:
            os.close(fd)
        for line in reversed(data.split(b"\n")):
            if b'"assistant"' not in line:
                continue
            try:
                rec = json.loads(line.decode("utf-8", "replace"))
            except (ValueError, RecursionError):
                continue
            msg = rec.get("message") if isinstance(rec, dict) and rec.get("type") == "assistant" else None
            if isinstance(msg, dict) and isinstance(msg.get("model"), str) and msg["model"].strip():
                return msg["model"].strip()
    return None


def who(role, sid, run, member=None, aid=None):
    rd = None
    if run:
        try:
            rd = run_dir(sid, run)
        except P.PolicyError:
            run = None
    return {"role": role, "sid": sid, "run": run, "member": member, "aid": aid, "rd": rd}


# ---------------------------------------------------------------- identify (support)
def link_leader(ev, d, aid):
    """Bind a subagent of type equilibrium to its run: Claude Code's meta.json toolUseId, else its prompt's
    `eq-run: R` line, else the session's only unbound run. The run id, or None."""
    sid = ev.get("session_id")
    cands = []
    for run, rd in session_runs(sid):
        brief = jread(os.path.join(rd, "brief.json"))
        if not isinstance(brief, dict) or brief.get("caller_type") == "headless":
            continue
        if os.path.lexists(os.path.join(rd, "leader.json")) or os.path.lexists(os.path.join(rd, "ended.json")):
            continue
        cands.append((run, rd, brief))
    if not cands:
        return None
    tid = G.spawn_meta(ev, aid).get("toolUseId")
    pick = [c for c in cands if tid and c[2].get("tool_use_id") == tid]
    if not pick:
        head = first_prompt_head(ev, aid) or ""
        m = re.fullmatch(r"eq-run:\s*([0-9a-f]{8})", head)
        pick = [c for c in cands if m and c[0] == m.group(1)]
    if not pick and len(cands) == 1:
        pick = cands
    if len(pick) != 1:
        return None
    run, rd, _ = pick[0]
    if not create_json(os.path.join(rd, "leader.json"), {"agent_id": aid, "ts": time.time()}):
        cur = jread(os.path.join(rd, "leader.json")) or {}
        if cur.get("agent_id") != aid:
            return None
    G.reg_put(d, aid, {"eq_run": run, "eq_role": "leader"})
    return run


def link_member(ev, d, aid, atype):
    """Bind a subagent to its member slot: meta.json toolUseId, else its brief's head line `eq R m<i>/<N>`,
    else the session's only unbound slot of its type. who() or None."""
    sid = ev.get("session_id")
    cands = []
    for run, rd in session_runs(sid):
        plan = plan_of(rd, run)
        if not plan or G.norm(plan.get("member_type")) != atype:
            continue
        for k, m in members_of(rd).items():
            if isinstance(m, dict) and not m.get("agent_id") and str(k).isdigit():
                cands.append((run, rd, int(k), m))
    if not cands:
        return None
    tid = G.spawn_meta(ev, aid).get("toolUseId")
    pick = [c for c in cands if tid and c[3].get("tool_use_id") == tid]
    if not pick:
        m = P.member_token_re.match(first_prompt_head(ev, aid) or "")
        pick = [c for c in cands if m and c[0] == m.group(1) and c[2] == int(m.group(2))]
    if not pick and len(cands) == 1:
        pick = cands
    if len(pick) != 1:
        return None
    run, rd, i, _ = pick[0]

    def bind_slot(cur):
        rec = cur.get(str(i))
        if not isinstance(rec, dict) or (rec.get("agent_id") and rec.get("agent_id") != aid):
            return False
        rec["agent_id"] = aid
        return True

    if not members_update(rd, bind_slot):
        return None
    G.reg_put(d, aid, {"eq_run": run, "eq_role": "member", "eq_member": i})
    return who("member", sid, run, i, aid)


def unmatched_member(ev, aid, atype, rec):
    """True when an unbound member slot of this agent's type was spawned shortly before it started: the agent
    may be that member, so it runs nothing until it is matched (fail closed)."""
    now = time.time()
    try:
        started = float(rec.get("started") or now)
    except (TypeError, ValueError):
        started = now
    for run, rd in session_runs(ev.get("session_id")):
        plan = plan_of(rd, run)
        if not plan or G.norm(plan.get("member_type")) != atype:
            continue
        for m in members_of(rd).values():
            if not isinstance(m, dict) or m.get("agent_id"):
                continue
            try:
                ts = float(m.get("spawned") or 0)
            except (TypeError, ValueError):
                ts = 0
            if ts - 5 <= started and now - ts < LINK_WINDOW_S:
                return True
    return False


def identify(ev, d):
    """Who calls, for the eq rules: who("leader"|"member"|"unmatched", ...) or None (no eq role). Links an
    unbound leader or member on the way (SubagentStart, else its first tool call)."""
    sid, aid = ev.get("session_id"), ev.get("agent_id")
    atype = G.norm(ev.get("agent_type"))
    if not aid:
        return headless_leader(ev, d) if atype in G.EQ_TYPES else None
    aid = G.ident(aid)
    rec = G.reg_get(d, aid) or {}
    role = rec.get("eq_role")
    if role in ("leader", "member") and isinstance(rec.get("eq_run"), str):
        return who(role, sid, rec["eq_run"], rec.get("eq_member"), aid)
    if atype in G.EQ_TYPES:
        return who("leader", sid, link_leader(ev, d, aid), None, aid)
    if not os.path.isdir(eq_dir(sid)):
        return None
    got = link_member(ev, d, aid, atype)
    if got:
        return got
    if unmatched_member(ev, aid, atype, rec):
        return who("unmatched", sid, None, None, aid)
    return None


# ---------------------------------------------------------------- rule 10: the headless leader
def headless_leader(ev, d):
    """A main thread whose agent_type is equilibrium (`claude -p --agent equilibrium`, no agent_id) leads the
    one run of this session whose brief.json says caller_type headless (contracts 11); else it leads none."""
    sid = ev.get("session_id")
    found = []
    for run, rd in session_runs(sid):
        brief = jread(os.path.join(rd, "brief.json"))
        if isinstance(brief, dict) and brief.get("caller_type") == "headless" and \
                P.safe_sid(brief.get("session")) == P.safe_sid(sid) and \
                not os.path.lexists(os.path.join(rd, "ended.json")):
            found.append(run)
    return who("leader", sid, found[0] if len(found) == 1 else None, None, None)


# ---------------------------------------------------------------- run liveness
def run_live(d, sid, run, rd, reg, now):
    """A run counts against STACK_EQ_MAX_CONCURRENT_RUNS while its leader runs: linked and not stopped,
    headless and not finished, or spawned less than UNLINKED_LIVE_S ago and not yet linked."""
    if os.path.lexists(os.path.join(rd, "ended.json")):
        return False
    brief = jread(os.path.join(rd, "brief.json"))
    if not isinstance(brief, dict):
        return False
    if brief.get("caller_type") == "headless":
        return state_of(rd).get("phase") not in ("result", "cleaned")
    leader = jread(os.path.join(rd, "leader.json"))
    if isinstance(leader, dict) and leader.get("agent_id"):
        rec = reg.get(G.ident(leader["agent_id"]))
        return not (isinstance(rec, dict) and rec.get("stopped"))
    try:
        return now - float(brief.get("created") or 0) < UNLINKED_LIVE_S
    except (TypeError, ValueError):
        return True


# ---------------------------------------------------------------- rule 3: the spawn gate
def spawn_gate(ev, d, ti):
    """PreToolUse Agent(subagent_type equilibrium) for an allowed caller: the deny reason, or the allowed
    spawn {"patch": {prompt: "eq-run: R\\n" + prompt}, "commit": writes brief.json}."""
    if not G.policy_on():
        return why("STACK_POLICY=off: the equilibrium runtime needs the guard's eq rules, so no run starts. "
                   "Take the single-agent path.")
    k = P.knobs(os.environ)
    if not k["STACK_EQ"]:
        return why("STACK_EQ=0: equilibrium runs are off. Take the single-agent path.")
    sid, tid = ev.get("session_id"), ev.get("tool_use_id")
    if not sid or not tid:
        return why("the event has no session_id or tool_use_id, so no run id can be derived.")
    prompt = ti.get("prompt")
    try:
        h = P.parse_header(prompt)
    except P.PolicyError as exc:
        return why("the brief's eq header does not parse: %s. Start the prompt with eq-class, eq-mode (and "
                   "optional eq-type, eq-check, eq-segments), a line ---, then the problem." % str(exc)[:300])
    if h["run"] is not None:
        return why("eq-run is the guard's: leave it out of the brief.")
    cwd = ev.get("cwd")
    if not isinstance(cwd, str) or not os.path.isabs(cwd):
        return why("the event has no absolute cwd: the run's project is unknown.")
    now, reg = time.time(), G.load_registry(d)
    runs = session_runs(sid)
    live = sum(1 for run, rd in runs if run_live(d, sid, run, rd, reg, now))
    if live >= k["STACK_EQ_MAX_CONCURRENT_RUNS"]:
        return why("%d equilibrium run(s) of this session are live (STACK_EQ_MAX_CONCURRENT_RUNS=%d): wait for "
                   "its task notification, then spawn this one." % (live, k["STACK_EQ_MAX_CONCURRENT_RUNS"]))
    params, _sha, _pwhy = P.load_params(os.path.join(HERE, "eq_params.json"),
                                        os.path.join(CONFIG, ".stack-manifest.json"))
    planned = sum(1 for _r, rd in runs if os.path.lexists(os.path.join(rd, "plan.json")))
    try:
        P.resolve(h["class"], params, k, mode=h["mode"], eq_type=h["type"], session_runs=planned)
    except P.PolicyError as exc:
        return why(str(exc)[:500])
    run = run_id(sid, tid)
    rd = run_dir(sid, run)
    if os.path.lexists(rd):
        return why("run eq:%s already has a store: one spawn, one run." % run)
    parent = G.norm(ev.get("agent_type")) or ("main" if not ev.get("agent_id") else None)
    brief = {"schema": P.SCHEMA_BRIEF, "run": run, "session": sid, "tool_use_id": tid, "caller_type": parent,
             "caller_id": G.ident(ev["agent_id"]) if ev.get("agent_id") else None, "cwd": cwd,
             "created": time.time(),
             "header": {"class": h["class"], "mode": h["mode"], "type": h["type"], "check": h["check"],
                        "segments": h["segments"]},
             "problem": h["problem"]}

    def commit():
        os.makedirs(os.path.dirname(rd), mode=0o700, exist_ok=True)
        os.mkdir(rd, 0o700)                          # FileExistsError: the run was taken meanwhile
        jwrite(os.path.join(rd, "brief.json"), brief)

    return {"patch": {"prompt": "eq-run: %s\n%s" % (run, prompt)}, "commit": commit,
            "why": "eq: run eq:%s, brief.json written" % run}


# ---------------------------------------------------------------- rule 4: the leader
def leader_tools(ev, d, w, tool, ti):
    """The leader's allowlist (spec 2.1: no file, web or memory tool); TaskStop only on its own members."""
    if tool in ALWAYS_TOOLS:
        return None
    if tool not in LEADER_TOOLS:
        return why("the equilibrium leader runs Agent, SendMessage, TaskStop, Bash and Skill only; %s is "
                   "refused. Relay through stack-eq, report what you need in your hand-back." % tool[:60])
    if tool == "TaskStop":
        target = ti.get("task_id") or ti.get("shell_id")
        target = G.ident(target) if isinstance(target, str) else None
        ids = {m.get("agent_id") for m in members_of(w["rd"]).values() if isinstance(m, dict)} if w["rd"] else set()
        if not target or target not in ids:
            return why("TaskStop is for your own run's members only (their agent ids in this run).")
    return None


def _shape(command, wrapper_names):
    """(words, None) of one plain command, or (None, reason)."""
    if not isinstance(command, str) or not command.strip():
        return None, "an empty command"
    text = command.strip()
    bad = G.TOOLSMITH_META_RE.search(text)
    if bad:
        return None, "%r is shell syntax" % bad.group(0)
    try:
        words = shlex.split(text)
    except ValueError as exc:
        return None, "unbalanced quotes (%s)" % exc
    if not words or words[0] not in wrapper_names:
        return None, "the first word is %r" % (words[0][:80] if words else "")
    return words, None


def leader_bash(ev, d, w, command, tool):
    """The leader's Bash: exactly `<config>/bin/stack-eq <args>` (a one-use ticket for its own run, none for
    help) or `<config>/bin/stack-eq-check --run R --cand i` (a pending record when contracts 6 allows it)."""
    exe, chk = os.path.join(CONFIG, "bin", "stack-eq"), os.path.join(CONFIG, "bin", "stack-eq-check")
    shape = ("Bash runs only `%s <subcommand> --run R ...` or `%s --run R --cand i`, one plain command by its "
             "absolute path (no ; && | redirection $(...) globs or ~)" % (exe, chk))
    if tool != "Bash":
        return why("the equilibrium leader's shell is Bash only (%s refused)." % tool)
    if not G.policy_on():
        return why("STACK_POLICY=off: stack-eq gets no ticket.")
    words, bad = _shape(command, (exe, chk))
    if bad:
        return why("%s: %s." % (shape, bad))
    args = words[1:]
    if words[0] == chk:
        return leader_check(ev, w, args)
    try:
        p = P.parse_cli(args)
    except P.PolicyError as exc:
        return why("`stack-eq %s` is refused: %s (`%s help`)." % (" ".join(args)[:160], str(exc)[:300], exe))
    if p["sub"] == "help":
        return None                                  # needs no ticket: stack-eq prints its help without one
    if p["headless"]:
        return why("--headless is the harness's, from a terminal; the leader never uses it.")
    if not w["run"] or p["run"] != w["run"]:
        return why("stack-eq calls name your own run (--run %s)." % (w["run"] or "<none bound>"))
    folder = P.ticket_dir(os.environ)
    os.makedirs(folder, mode=0o700, exist_ok=True)
    P.write_json_atomic(os.path.join(folder, P.ticket_name(args)),
                        {"argv": list(args), "ts": time.time(), "session": G.safe(ev.get("session_id"), None),
                         "run": w["run"], "agent_id": w["aid"], "agent_type": "equilibrium"})
    return None


def leader_check(ev, w, args):
    """stack-eq-check: only the leader's own run, a plan check, phase `checks`, an existing check copy, no
    verdict yet; writes r<r>/check-c<i>.pending.json (contracts 6)."""
    try:
        a = P.parse_check_cli(args)
    except P.PolicyError as exc:
        return why("stack-eq-check: %s." % exc)
    if not w["run"] or a["run"] != w["run"]:
        return why("stack-eq-check names your own run (--run %s)." % (w["run"] or "<none bound>"))
    rd = w["rd"]
    plan, st = plan_of(rd, w["run"]), state_of(rd)
    if not plan or not isinstance(plan.get("check"), dict) or not plan["check"].get("argv"):
        return why("run eq:%s lists no check: no stack-eq-check." % w["run"])
    if plan.get("w3") == "container":
        return why("run eq:%s checks at Level 2: use stack-eq check-container." % w["run"])
    if st.get("phase") != "checks" or not isinstance(st.get("round"), int):
        return why("stack-eq-check runs in the checks phase only (run `stack-eq prepare-check` first).")
    i, rnd = a["cand"], st["round"]
    if not 1 <= i <= int(plan.get("N") or 0):
        return why("candidate c%d is not a member of this run." % i)
    copy = os.path.join(str(plan.get("project_root")), ".claude-work", "eq", w["run"], "checks", "c%d" % i)
    if not is_dir(copy) or real(copy) != os.path.normpath(copy):
        return why("no check copy c%d (or a linked one): stack-eq prepare-check first." % i)
    rr = os.path.join(rd, "r%d" % rnd)
    if os.path.lexists(os.path.join(rr, "check-c%d.json" % i)):
        return why("c%d already has a round-%d verdict: one check per candidate per round." % (i, rnd))
    jwrite(os.path.join(rr, "check-c%d.pending.json" % i), {"tool_use_id": ev.get("tool_use_id"), "ts": time.time()})
    return None


def leader_agent(ev, d, w, ti):
    """Leader -> member spawn: `eq R m<i>/<N>` as prompt and description, the plan's member type, isolation
    worktree for worktree classes, each member once in phase started; the prompt becomes the stored brief and
    `model` the plan's model. The deny reason, or {"patch", "commit"}."""
    run, rd = w["run"], w["rd"]
    if not run:
        return why("no equilibrium run is bound to this leader (its spawn was not seen by the guard).")
    if not G.policy_on():
        return why("STACK_POLICY=off: no member spawns.")
    extra = sorted(k for k, v in ti.items() if k not in AGENT_KEYS and v not in (None, "", False))
    if extra:
        return why("member spawns take subagent_type, prompt, description, isolation and run_in_background "
                   "only (%s refused)." % ", ".join(extra)[:120])
    prompt, desc = ti.get("prompt"), ti.get("description")
    m = P.member_token_re.match(prompt.strip()) if isinstance(prompt, str) else None
    if not m or not isinstance(desc, str) or desc.strip() != prompt.strip():
        return why("a member spawn's prompt and description are both exactly `eq %s m<i>/<N>` (the guard "
                   "substitutes the stored brief)." % run)
    r_, i, n = m.group(1), int(m.group(2)), int(m.group(3))
    if r_ != run:
        return why("eq:%s is not your run (eq:%s)." % (r_, run))
    plan, st = plan_of(rd, run), state_of(rd)
    if not plan:
        return why("run eq:%s has no plan: stack-eq plan first." % run)
    if st.get("phase") != "started" or st.get("round") != 0:
        return why("members are spawned once, after `stack-eq start` (phase started; the run is %s)."
                   % st.get("phase"))
    N = int(plan.get("N") or 0)
    if n != N or not 1 <= i <= N:
        return why("the plan has N=%d members: tokens m1/%d .. m%d/%d." % (N, N, N, N))
    want = G.norm(plan.get("member_type"))
    if G.norm(ti.get("subagent_type")) != want:
        return why("members of eq:%s are %s (the plan's member type)." % (run, want))
    iso = str(ti.get("isolation") or "").strip().lower()
    if plan.get("workdir") == "worktree" and iso != "worktree":
        return why('class %s members need isolation: "worktree".' % plan.get("class"))
    if plan.get("workdir") != "worktree" and iso:
        return why("class %s members work in .claude-work/eq/%s/m<i>/, not with isolation."
                   % (plan.get("class"), run))
    if str(i) in members_of(rd):
        return why("m%d of eq:%s was already spawned: each member once (follow-ups go by SendMessage)." % (i, run))
    brief = read_verified(os.path.join(rd, "briefs", "m%d.txt" % i))
    if brief is None or not brief.startswith("eq %s m%d/%d" % (run, i, N)):
        return why("m%d's stored brief is missing or does not match its sha256: nothing spawned." % i)
    model = plan.get("member_model_id") or plan.get("member_model")
    if model and os.environ.get("CLAUDE_CODE_SUBAGENT_MODEL_FORCE", "").strip():
        return why("CLAUDE_CODE_SUBAGENT_MODEL_FORCE is set, so Claude Code would drop the plan's member model "
                   "%s: no member spawns." % model)
    over = run_budget(ev, d, w, plan)
    if over:
        return over
    tid, wt = ev.get("tool_use_id"), plan.get("workdir")

    def commit():
        def slot(cur):
            if str(i) in cur:
                raise RuntimeError("m%d was spawned twice in one message" % i)
            cur[str(i)] = {"agent_id": None, "tool_use_id": tid, "cwd": None, "worktree": None,
                           "status": "running", "rounds": {}, "round": 0, "spawned": time.time(), "type": want,
                           "workdir": wt}
        members_update(rd, slot)

    return {"patch": {"prompt": brief, "model": model or None}, "commit": commit,
            "why": "eq: m%d's brief substituted (sha256 %s)" % (i, hashlib.sha256(brief.encode()).hexdigest()[:12])}


def leader_send(ev, d, w, ti, target_id):
    """Leader -> member reconcile: `eq R r<r> m<i>` to that member's agent id in phase viewed of round r,
    once per round; the text becomes the stored view. The deny reason, or {"message", "commit"}."""
    run, rd = w["run"], w["rd"]
    msg = ti.get("message")
    m = P.reconcile_token_re.match(msg.strip()) if isinstance(msg, str) else None
    if not run or not m:
        return why("the leader's SendMessage text is exactly `eq %s r<r> m<i>` to that member's agent id (the "
                   "guard substitutes the stored view)." % (run or "R"))
    r_, rnd, i = m.group(1), int(m.group(2)), int(m.group(3))
    if r_ != run:
        return why("eq:%s is not your run (eq:%s)." % (r_, run))
    plan, st = plan_of(rd, run), state_of(rd)
    if not plan or st.get("phase") != "viewed" or st.get("round") != rnd or rnd < 1:
        return why("round %d's views are not ready (the run is %s round %s): stack-eq view first."
                   % (rnd, st.get("phase"), st.get("round")))
    rec = members_of(rd).get(str(i))
    if not isinstance(rec, dict) or not rec.get("agent_id"):
        return why("m%d has no agent id on record." % i)
    if not target_id or G.ident(target_id) != rec["agent_id"]:
        return why("send `eq %s r%d m%d` to m%d's agent id %s." % (run, rnd, i, i, rec["agent_id"]))
    if rec.get("status") == "abstain":
        return why("m%d was stopped: it abstains for the rest of the run." % i)
    try:
        last = int(rec.get("round") or 0)
    except (TypeError, ValueError):
        last = 0
    if last >= rnd:
        return why("m%d already got its round-%d view." % (i, rnd))
    view = read_verified(os.path.join(rd, "views", "r%d" % rnd, "m%d.txt" % i))
    if view is None:
        return why("m%d's round-%d view is missing or does not match its sha256: nothing sent." % (i, rnd))
    over = run_budget(ev, d, w, plan)
    if over:
        return over

    def commit():
        def mark(cur):
            r2 = cur.get(str(i))
            if isinstance(r2, dict):
                r2["round"], r2["status"] = rnd, "running"
        members_update(rd, mark)

    return {"message": view, "commit": commit}


def norm_reply(text):
    t = (text or "").replace("\r\n", "\n").strip()
    m = re.fullmatch(r"```[A-Za-z0-9_-]*\n(.*)\n```", t, re.S)
    if m:
        t = m.group(1).strip()
    return "\n".join(line.rstrip() for line in t.split("\n"))


def leader_reply(ev, d, w):
    """Leader SubagentStop once result.json exists: the reply must equal stack-eq result's block (result.txt);
    one restate (decision block), then the outcome is recorded. The block reason or None."""
    rd = w["rd"]
    if not rd or not os.path.lexists(os.path.join(rd, "result.json")):
        return None
    hb = G.report_module().transcript_handback(ev.get("agent_transcript_path"))
    text = hb if hb else ev.get("last_assistant_message")
    text = text if isinstance(text, str) else ""
    want = read_bytes(os.path.join(rd, "result.txt"), 4 << 20)
    want = want.decode("utf-8", "replace") if want is not None else None
    ok = want is not None and norm_reply(text) == norm_reply(want)
    key = str((G.reg_get(d, w["aid"]) or {}).get("started") or "none") if w["aid"] else "headless"
    prev = jread(os.path.join(rd, "leader_reply.json")) or {}
    if not ok and prev.get("restated") != key and not G.stop_hook_active(ev):
        jwrite(os.path.join(rd, "leader_reply.json"), {"restated": key, "matched": False, "ts": time.time()})
        if want is None:
            return why("run `stack-eq result --run %s` again and reply with exactly its output." % w["run"])
        return why("your final reply must be exactly the output of `stack-eq result --run %s`, nothing added or "
                   "left out. Reply again with exactly this:\n%s" % (w["run"], want[:20000]))
    jwrite(os.path.join(rd, "leader_reply.json"), {"restated": prev.get("restated"), "matched": ok,
                                                    "ts": time.time()})
    return None


# ---------------------------------------------------------------- rule 5: the members
def member_context(w):
    """(plan, members, own record) of a member, or None when its run lost its plan."""
    plan = plan_of(w["rd"], w["run"]) if w["rd"] else None
    if not plan:
        return None
    members = members_of(w["rd"])
    rec = members.get(str(w["member"]))
    return plan, members, rec if isinstance(rec, dict) else {}


def member_tools(ev, d, w, tool):
    """MEMBER_TOOLS[class] (Skill included) plus SubagentHandback and ToolSearch; everything else, so always
    Agent, SendMessage, TaskStop, WebSearch, WebFetch and mcp__*, refused (W1)."""
    ctx = member_context(w)
    if ctx is None:
        return why("this eq member's run has no plan: it runs nothing.")
    plan = ctx[0]
    allowed = set(plan.get("member_tools") or P.MEMBER_TOOLS.get(plan.get("class"), ())) | {"Skill"}
    allowed &= set(P.MEMBER_TOOLS.get(plan.get("class"), ())) | {"Skill"}
    if tool in ALWAYS_TOOLS or tool in allowed:
        return None
    return why("eq members of class %s use %s only: %s is refused (no spawns, messages, web, memory or MCP: "
               "your answer must be your own). Reply with your JSON object when done."
               % (plan.get("class"), ", ".join(sorted(allowed)), tool[:60]))


def own_dir(plan, w):
    d_ = (plan.get("member_dirs") or {}).get(str(w["member"]))
    return d_ if isinstance(d_, str) and d_ else None


def member_cwd(ev, d, w):
    """A member's file tools and Bash run only in its recorded working directory (its worktree for CP/CR,
    never the project root; its own m<i>/ also passes). The first call records it."""
    ctx = member_context(w)
    if ctx is None:
        return why("this eq member's run has no plan: it runs nothing.")
    plan, _members, rec = ctx
    cwd = ev.get("cwd")
    if not isinstance(cwd, str) or not os.path.isabs(cwd):
        return why("the event names no working directory, so this eq member's place cannot be checked.")
    here, root = real(cwd), real(str(plan.get("project_root")))
    if plan.get("workdir") == "worktree" and (here == root or not under(here, root)):
        return why('this eq member runs outside a worktree of the project (%s): isolation "worktree" did '
                   "not hold, so it touches nothing. Reply with your JSON object." % here)
    recorded = rec.get("cwd")
    if not recorded:
        def first(cur):
            r2 = cur.get(str(w["member"]))
            if isinstance(r2, dict) and not r2.get("cwd"):
                r2["cwd"] = here
                if plan.get("workdir") == "worktree" and not r2.get("worktree"):
                    r2["worktree"] = here
            return (r2 or {}).get("cwd") if isinstance(r2, dict) else here
        recorded = members_update(w["rd"], first) or here
    rec_real = real(recorded)
    own = own_dir(plan, w)
    if here == rec_real or (plan.get("workdir") == "worktree" and under(here, rec_real)) or \
            (own and under(here, real(own))):
        return None
    return why("this eq member's working directory changed (%s, recorded %s; a resume may have moved it): its "
               "file tools and Bash are refused. Reply with your JSON object." % (here, rec_real))


def member_roots(plan, members, w):
    """The member_path_denied keyword arguments for member w."""
    root = real(str(plan.get("project_root")))
    wts = {}
    for k, m in members.items():
        if not isinstance(m, dict):
            continue
        wt = m.get("worktree") or (m.get("cwd") if plan.get("workdir") == "worktree" else None)
        if isinstance(wt, str) and wt and real(wt) != root:
            wts[str(k)] = wt
    if plan.get("workdir") == "worktree":
        # Claude Code's isolation worktrees (<project>/.claude/worktrees/<name>): every one but the member's
        # own, so a sibling whose cwd is not on record yet is covered too
        mine = members.get(str(w["member"]))
        mine = mine if isinstance(mine, dict) else {}
        own = mine.get("worktree") or mine.get("cwd")
        base = os.path.join(root, ".claude", "worktrees")
        try:
            names = os.listdir(base)
        except OSError:
            names = []
        for n in names:
            p = os.path.join(base, n)
            if not own or real(p) != real(own):
                wts["wt:" + n] = p
    return {"config_dir": CONFIG, "state_root": G.state_root(), "project_root": plan.get("project_root"),
            "run": w["run"], "member": w["member"], "member_dirs": plan.get("member_dirs") or {},
            "member_worktrees": wts}


def _glob_base(pattern):
    """The literal directory prefix of a glob pattern."""
    parts = pattern.split("/")
    keep = []
    for p in parts:
        if any(c in p for c in "*?[{"):
            break
        keep.append(p)
    return "/".join(keep) or ("/" if pattern.startswith("/") else ".")


def member_paths(ev, d, w, tool, ti):
    """File tools of a member, realpath-resolved (eq_policy.member_path_denied): never <config>/projects/**,
    the state root, <project>/.claude-work/eq/** but its own m<i>/, another member's worktree or m<j>/;
    Grep/Glob also not from an ancestor of those; Edit/Write/NotebookEdit never under the config dir."""
    keys = FILE_TOOLS.get(tool)
    if not keys:
        return None
    ctx = member_context(w)
    if ctx is None:
        return why("this eq member's run has no plan: it runs nothing.")
    plan, members, _rec = ctx
    cwd = ev.get("cwd") if isinstance(ev.get("cwd"), str) else None
    paths = []
    for k in keys:
        v = ti.get(k)
        if v is None or v == "":
            continue
        if not isinstance(v, str):
            return why("%s's %s must be one path." % (tool, k))
        if v.startswith("file://"):
            v = v[len("file://"):]
        paths.append(v)
    if tool in RECURSIVE_TOOLS and not paths:
        paths.append(cwd or "")
    if tool == "Glob" and isinstance(ti.get("pattern"), str):
        pat = ti["pattern"]
        if pat.startswith(("/", "~")) or ".." in pat.split("/"):
            base = paths[0] if paths else (cwd or "")
            paths.append(os.path.join(base, os.path.expanduser(_glob_base(pat))))
    kw = member_roots(plan, members, w)
    for p in paths:
        p = os.path.expanduser(p)
        bad = P.member_path_denied(p, cwd=cwd, recursive=tool in RECURSIVE_TOOLS, **kw)
        if bad:
            return why(bad + ". Work only in your own working directory.")
        if tool in WRITE_TOOLS:
            full = p if os.path.isabs(p) else os.path.join(cwd or "/", p)
            if any(under(f, r) for f in {os.path.normpath(full), real(full)} for r in {CONFIG, real(CONFIG)}):
                return why("eq members never write under the Claude config dir.")
    return None


# shell reading (a heuristic: spec 2.3 "enforced for the command word, heuristic for wrappers")
def split_segments(text):
    """Quote-aware split of a shell command at unquoted ; & | ( ) { } newlines, backticks and `$(`: each
    command substitution's text becomes a segment of its own."""
    segs, cur, i, n, quote = [], [], 0, len(text), None

    def flush():
        s = "".join(cur).strip()
        if s:
            segs.append(s)
        cur.clear()

    while i < n:
        c = text[i]
        if quote == "'":
            cur.append(c)
            quote = None if c == "'" else quote
            i += 1
            continue
        if c == "\\" and i + 1 < n:
            cur.append(text[i:i + 2])
            i += 2
            continue
        if c == "`" or text.startswith("$(", i):
            flush()
            i += 2 if c == "$" else 1
            continue
        if quote == '"':
            cur.append(c)
            quote = None if c == '"' else quote
            i += 1
            continue
        if c in "'\"":
            quote = c
            cur.append(c)
            i += 1
            continue
        if c in ";&|(){}\n":
            flush()
            i += 1
            continue
        if c == "#" and (not cur or cur[-1].isspace()):
            j = text.find("\n", i)
            i = n if j < 0 else j
            continue
        cur.append(c)
        i += 1
    flush()
    return segs


def command_words(words):
    """The words from the command word on (assignments, wrappers and their options skipped)."""
    k, wrapper = 0, None
    while k < len(words):
        w_ = words[k]
        low = w_.lower()
        if wrapper and low in VALUE_OPTS.get(wrapper, ()):
            k += 2
            continue
        if low in WRAPPERS:
            wrapper = low
            k += 1
            continue
        if wrapper and (low[:1] in "-+" or low[:1].isdigit()):
            k += 1
            continue
        if re.match(r"[A-Za-z_][A-Za-z0-9_]*\+?=", w_):
            k += 1
            continue
        return words[k:]
    return []


def nested_texts(words):
    """Command texts a command runs itself: sh/bash -c TEXT, eval ..., env -S TEXT, find -exec ... ;"""
    out = []
    cw = command_words(words)
    if not cw:
        return out
    base = os.path.basename(cw[0]).lower()
    if base in SHELLS:
        for j in range(1, len(cw)):
            a = cw[j]
            if a.startswith("-") and not a.startswith("--") and "c" in a[1:] and j + 1 < len(cw):
                out.append(cw[j + 1])
                break
    if base == "eval" and len(cw) > 1:
        out.append(" ".join(cw[1:]))
    for j, a in enumerate(words):
        if a.lower() in ("-s", "--split-string") and j and words[j - 1].lower() == "env" and j + 1 < len(words):
            out.append(words[j + 1])
    for j, a in enumerate(cw):
        if a in ("-exec", "-execdir", "-ok", "-okdir"):
            rest = []
            for b in cw[j + 1:]:
                if b in (";", "+", "\\;"):
                    break
                rest.append(b)
            if rest:
                out.append(" ".join(shlex.quote(x) for x in rest))
    return out


def simple_commands(text, depth=0):
    """[(words or None, segment text)] of every simple command, nested shells included (depth <= 3)."""
    out = []
    for seg in split_segments(text):
        try:
            words = shlex.split(seg, comments=False, posix=True)
        except ValueError:
            out.append((None, seg))
            continue
        out.append((words, seg))
        if depth < 3:
            for inner in nested_texts(words):
                out.extend(simple_commands(inner, depth + 1))
    return out


def invokes(command, names):
    """True when a simple command of `command` has one of `names` as its command word."""
    text = re.sub(r"\\\r?\n", "", str(command or ""))
    if not any(nm in text for nm in names):
        return False
    for words, seg in simple_commands(text):
        if words is None:
            if any(nm in seg for nm in names):
                return True
            continue
        cw = command_words(words)
        if cw and os.path.basename(cw[0]) in names:
            return True
    return False


GIT_WORD_RE = re.compile(r"(?<![\w./-])git(?![\w.-])")


def git_rule(command):
    """The deny reason for an eq member's git use (eq_policy.member_git_allowed on every command word git,
    wrappers and nested shells included), else None."""
    for words, seg in simple_commands(re.sub(r"\\\r?\n", "", command)):
        if words is None:
            if GIT_WORD_RE.search(seg):
                return "a command this check cannot read names git"
            continue
        cw = command_words(words)
        if cw and os.path.basename(cw[0]) == "git":
            bad = P.member_git_allowed(cw)
            if bad:
                return bad
    return None


def _expand(word, cwd):
    home = os.environ.get("HOME") or os.path.expanduser("~")
    w_ = word
    if w_.startswith("~"):
        w_ = home + w_[1:] if w_ == "~" or w_.startswith("~/") else w_
    for name, val in (("HOME", home), ("PWD", cwd or ""), ("CLAUDE_CONFIG_DIR", CONFIG),
                      ("XDG_STATE_HOME", os.path.dirname(G.state_root()))):
        w_ = w_.replace("${%s}" % name, val).replace("$%s" % name, val)
    return w_


def path_scan(command, ev, w, plan, members):
    """The heuristic path check of a member's Bash: every word that is (or holds) a path, expanded and
    resolved against the cwd, through member_path_denied with recursive=True; marker text refused."""
    if BASH_MARKERS.search(command):
        return "the command names Claude Code's transcripts or the stack's state"
    cwd = ev.get("cwd") if isinstance(ev.get("cwd"), str) else None
    kw = member_roots(plan, members, w)
    count = 0
    for words, seg in simple_commands(command):
        for word in (words if words is not None else seg.split()):
            count += 1
            if count > MAX_WORDS:
                return "too long a command to check"
            cand = word.lstrip("<>&0123456789") if re.match(r"\d*[<>]", word) else word
            if cand.startswith("-") and "=" in cand:
                cand = cand.split("=", 1)[1]
            cand = _expand(cand, cwd)
            if "$" in cand or not cand:
                continue
            looks = "/" in cand or cand in (".", "..") or cand.startswith("~")
            if not looks and cwd and not cand.startswith("-"):
                looks = os.path.lexists(os.path.join(cwd, cand))
            if not looks:
                continue
            base = _glob_base(cand) if any(c in cand for c in "*?[{") else cand
            bad = P.member_path_denied(base, cwd=cwd, recursive=True, **kw)
            if bad:
                return bad
    return None


def member_bash(ev, d, w, command, tool):
    """A member's Bash: no stack-eq, git only the read-only subset (command word enforced, wrappers
    heuristic), and the path scan (heuristic) on the paths its file tools may not touch."""
    if tool != "Bash":
        return why("eq members' shell is Bash only (%s refused)." % tool)
    if not isinstance(command, str):
        return why("Bash needs a command string.")
    if invokes(command, ("stack-eq", "stack-eq-check")):
        return why("stack-eq and stack-eq-check are the leader's.")
    bad = git_rule(command)
    if bad:
        return why(bad + ". Leave your edits uncommitted in your working directory.")
    ctx = member_context(w)
    if ctx is None:
        return why("this eq member's run has no plan: it runs nothing.")
    bad = path_scan(command, ev, w, ctx[0], ctx[1])
    if bad:
        return why("%s (Bash path check, a heuristic). Work only in your own working directory." % bad)
    return None


# ---------------------------------------------------------------- rule 6: capture
def capture(ev, d, w):
    """Member SubagentStop: parse the reply (the SubagentHandback message, else the last assistant message)
    against the class schema; r<r>/m<i>.json per contracts 2 (model from the transcript, model_drift); the
    report copy into the store's reports/; registry metadata only; members.json status/rounds/worktree.
    Invalid: one restate (the block reason is returned), then the member abstains for the round."""
    rd, i, aid = w["rd"], w["member"], w["aid"]
    plan = plan_of(rd, w["run"]) if rd else None
    if not plan:
        return None
    rec = members_of(rd).get(str(i))
    rec = rec if isinstance(rec, dict) else {}
    try:
        rnd = int(rec.get("round") or 0)
    except (TypeError, ValueError):
        rnd = 0
    hb = G.report_module().transcript_handback(ev.get("agent_transcript_path"))
    via = "handback" if hb else "text"
    text = hb if hb else ev.get("last_assistant_message")
    text = text if isinstance(text, str) else ""
    obj, errs = None, []
    if len(text) > REPLY_MAX:
        errs = ["reply longer than %d characters" % REPLY_MAX]
    else:
        try:
            schema = core().load_schemas(os.path.join(HERE, "eq_schemas.json")).get(plan.get("class"))
            if not isinstance(schema, dict):
                raise ValueError("no %s schema" % plan.get("class"))
            obj, errs = core().parse_member_reply(text.strip(), schema)
        except Exception as exc:  # noqa: BLE001 - no parser, no answer: the member abstains (fail closed)
            obj, errs = None, ["the guard could not check the reply (%s)" % type(exc).__name__]
    restated = rnd in (rec.get("restated") or [])
    if obj is None and not restated and not G.stop_hook_active(ev) and text.strip():
        def note(cur):
            r2 = cur.get(str(i))
            if isinstance(r2, dict):
                r2["restated"] = sorted(set(r2.get("restated") or []) | {rnd})
        members_update(rd, note)
        return why("your final reply must be exactly one JSON object for class %s (no prose, no code fence): "
                   "%s. Reply again with only that JSON object." % (plan.get("class"), "; ".join(errs)[:600]))
    model = transcript_model(ev, aid)
    want_id, want_alias = plan.get("member_model_id"), plan.get("member_model")
    drift = (model != want_id) if want_id else bool(want_alias and (not model or want_alias not in model))
    now = time.time()
    status = "ok" if obj is not None else "abstain"
    jwrite(os.path.join(rd, "r%d" % rnd, "m%d.json" % i),
           {"run": w["run"], "round": rnd, "member": i, "status": status, "answer": obj, "errors": errs[:20],
            "model": model, "model_drift": drift, "agent_id": aid, "ts": now})
    path = report_copy(rd, aid, rnd, text)
    cwd = ev.get("cwd") if isinstance(ev.get("cwd"), str) and os.path.isabs(ev.get("cwd")) else None
    root = real(str(plan.get("project_root")))

    def done(cur):
        r2 = cur.setdefault(str(i), {})
        if not isinstance(r2, dict):
            return
        r2.setdefault("rounds", {})[str(rnd)] = "captured" if obj is not None else ("invalid" if text.strip()
                                                                                   else "abstain")
        if r2.get("status") != "abstain":
            r2["status"] = "stopped"
        if plan.get("workdir") == "worktree" and not r2.get("worktree"):
            cand = r2.get("cwd") or (real(cwd) if cwd else None)
            r2["worktree"] = cand if cand and real(cand) != root else None
        if not r2.get("cwd") and cwd:
            r2["cwd"] = real(cwd)
    members_update(rd, done)
    key = str((G.reg_get(d, aid) or {}).get("started") or "none")

    def meta(cur):
        cur["report"] = {"run": key, "eq_run": w["run"], "round": rnd, "member": i, "status": status,
                         "chars": len(text), "via": via, "path": path, "ts": round(now, 3)}
        return True, None
    G.reg_update(d, aid, meta)
    return None


def report_copy(rd, aid, rnd, text):
    """reports/<agent_id>.r<r>.<n>.md in the STORE (never the session's reports/), O_EXCL 0600."""
    folder = os.path.join(rd, "reports")
    os.makedirs(folder, mode=0o700, exist_ok=True)
    data = text[:G.REPORT_COPY_MAX].encode("utf-8", "replace")
    for n in range(20):
        path = os.path.join(folder, "%s.r%d.%d.md" % (G.safe(aid), rnd, n))
        try:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
        except FileExistsError:
            continue
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        return path
    return None


# ---------------------------------------------------------------- rule 7: check verdicts
def _response(ev):
    tr = ev.get("tool_response")
    if isinstance(tr, str):
        try:
            tr2 = json.loads(tr)
            tr = tr2 if isinstance(tr2, dict) else {"stdout": tr}
        except ValueError:
            tr = {"stdout": tr}
    return tr if isinstance(tr, dict) else {}


def check_verdict(ev, w, rnd, cand):
    """PostToolUse(Bash) of the pending stack-eq-check call: pass iff the trailer parses as the only line,
    matches run/cand/round, exit 0, not timed out, and the payload's exit status (when it has one) agrees;
    a failure event or any doubt is never a pass (contracts 6)."""
    tr = _response(ev)
    failed = ev.get("hook_event_name") == "PostToolUseFailure"
    stdout = tr.get("stdout") if isinstance(tr.get("stdout"), str) else None
    if failed and stdout is None:
        err = ev.get("error") if isinstance(ev.get("error"), str) else tr.get("error")
        stdout = err if isinstance(err, str) else None
    t = P.parse_check_trailer(stdout) if stdout is not None and not failed else None
    if failed and stdout:
        for line in stdout.split("\n"):
            t2 = P.parse_check_trailer(line) if line.startswith(P.CHECK_TRAILER) else None
            t = t2 or t
    rc = next((tr[k] for k in EXIT_KEYS if isinstance(tr.get(k), int) and not isinstance(tr.get(k), bool)), None)
    verdict, exit_, source, timed, tail = "unverifiable", None, "none", False, ""
    if t is not None and t["run"] == w["run"] and t["cand"] == cand and t["round"] == rnd:
        exit_, timed = t["exit"], bool(t["timed_out"])
        try:
            tail = base64.b64decode(t["tail_b64"].encode("ascii"), validate=True).decode("utf-8", "replace")
        except (ValueError, UnicodeEncodeError):
            tail = ""
        source = "tool_response" if rc is not None else "trailer"
        expect = 124 if timed else exit_
        if rc is not None and rc != expect:
            verdict = "unverifiable"
        elif tr.get("interrupted") is True:
            verdict = "unverifiable"
        elif timed or exit_ != 0 or failed:
            verdict = "fail"
        else:
            verdict = "pass"
    rec = {"cand": cand, "round": rnd, "exit": exit_, "exit_source": source, "timed_out": timed, "tail": tail,
           "verdict": verdict}
    jwrite(os.path.join(w["rd"], "r%d" % rnd, "check-c%d.json" % cand), rec)
    unlink(os.path.join(w["rd"], "r%d" % rnd, "check-c%d.pending.json" % cand))
    return rec


# ---------------------------------------------------------------- rule 8: consent
def _answer_strings(v):
    if isinstance(v, str):
        return [v]
    if isinstance(v, list):
        return [x for x in v if isinstance(x, str)]
    if isinstance(v, dict):
        return [v[k] for k in ("answer", "label", "value") if isinstance(v.get(k), str)]
    return []


def chosen_answers(ev):
    """The chosen answers of an AskUserQuestion result, read only from answer fields (never the question or
    option text, which always holds the token): `answers` maps of question -> answer in tool_response or
    tool_input, or an answer/selected field. Any other shape yields nothing (no record)."""
    out = []
    for src in (ev.get("tool_response"), ev.get("tool_input")):
        if isinstance(src, str):
            try:
                src = json.loads(src)
            except ValueError:
                continue                     # free text mixes questions and answers: unrecognised
        if not isinstance(src, dict):
            continue
        ans = src.get("answers")
        if isinstance(ans, dict):
            for v in ans.values():
                out += _answer_strings(v)
        elif isinstance(ans, list):
            for v in ans:
                out += [v] if isinstance(v, str) else _answer_strings(v if isinstance(v, dict) else None)
        for k in ("answer", "selected", "selectedOption", "selected_option", "choice"):
            out += _answer_strings(src.get(k))
    return out


def _fold(s):
    return unicodedata.normalize("NFKC", s)


def consent_record(ev, d):
    """Main-thread PostToolUse(AskUserQuestion): consent/<R>.json (or <R>-remove.json) when the CHOSEN answer
    contains `Run eq:<R>` (`Remove eq:<R>`) for a run of this session. Returns the tokens recorded."""
    if ev.get("agent_id"):
        return []
    sid, done = ev.get("session_id"), []
    for a in chosen_answers(ev):
        for m in P.CONSENT_RE.finditer(_fold(a)):
            kind, run = ("run" if m.group(1) == "Run" else "remove"), m.group(2)
            if not is_dir(run_dir(sid, run)):
                continue
            name = "%s.json" % run if kind == "run" else "%s-remove.json" % run
            tok = P.consent_token(run, kind)
            jwrite(os.path.join(eq_dir(sid), "consent", name),
                   {"token": tok, "answer": a[:500], "ts": time.time(), "source": "ask"})
            done.append(tok)
    return done


def consent_relay(ev, d, payload):
    """A USER: relay (any caller, the main thread included) naming `Run eq:R` / `Remove eq:R` needs the
    record of that answer in this session first (E4); the deny reason or None."""
    texts = [payload] if isinstance(payload, str) else list(G.strings_in(payload))
    sid = ev.get("session_id")
    for s in texts:
        if not isinstance(s, str) or "eq:" not in _fold(s) or not G.user_line(s):
            continue
        for m in P.CONSENT_RE.finditer(_fold(s)):
            kind, run = ("run" if m.group(1) == "Run" else "remove"), m.group(2)
            name = "%s.json" % run if kind == "run" else "%s-remove.json" % run
            rec = jread(os.path.join(eq_dir(sid), "consent", name))
            if not P.consent_ok(rec, run, kind):
                return why("a USER: relay naming '%s' needs the user's AskUserQuestion answer recorded first (the "
                           "main thread asks; the guard records the chosen option). Ask the user, then relay."
                           % P.consent_token(run, kind))
    return None


# ---------------------------------------------------------------- rule 9: budgets
def member_caps(ev, d):
    """{"tokens", "turns"}: an eq member's plan caps (budget_gate takes the min with the type's), else None."""
    w = identify(ev, d) if ev.get("agent_id") else None
    if not w or w["role"] != "member":
        return None
    plan = plan_of(w["rd"], w["run"]) if w["rd"] else None
    caps = (plan or {}).get("caps") if isinstance((plan or {}).get("caps"), dict) else {}
    out = {}
    for src, dst in (("member_tokens", "tokens"), ("member_turns", "turns")):
        v = caps.get(src)
        out[dst] = v if isinstance(v, int) and not isinstance(v, bool) and v > 0 else None
    return out


def run_tokens_used(ev, d, w, st=None):
    """Context tokens of the run's leader and members (budget.json `tot` per transcript), or None."""
    files = G.transcript_files(ev)
    if not files or not w["rd"]:
        return None
    st = st if isinstance(st, dict) else (G.read_json(os.path.join(d, G.BUDGET_STATE)) or {})
    fst = st.get("files") if isinstance(st.get("files"), dict) else {}
    ids = set()
    leader = jread(os.path.join(w["rd"], "leader.json")) or {}
    if leader.get("agent_id"):
        ids.add(G.ident(leader["agent_id"]))
    for m in members_of(w["rd"]).values():
        if isinstance(m, dict) and m.get("agent_id"):
            ids.add(G.ident(m["agent_id"]))
    total = sum(int((fst.get(G.subagent_file(files, a)) or {}).get("tot") or 0) for a in ids)
    brief = jread(os.path.join(w["rd"], "brief.json")) or {}
    if brief.get("caller_type") == "headless":
        total += int((fst.get(files[0]) or {}).get("tot") or 0)
    return total


def run_budget(ev, d, w, plan, st=None):
    """The deny reason once the run's tokens reach the plan's caps.run_tokens, else None (no count: None, as
    the token budgets fail open)."""
    cap = ((plan or {}).get("caps") or {}).get("run_tokens")
    if not isinstance(cap, int) or isinstance(cap, bool) or cap <= 0:
        return None
    used = run_tokens_used(ev, d, w, st)
    if used is None or used < cap:
        return None
    return why("run eq:%s has used %s of its %s context tokens (the plan's caps.run_tokens): no more member "
               "spawns or resumes; members hand back now. Reduce what you have (stack-eq reduce), then stack-eq "
               "result." % (w["run"], "{:,}".format(used), "{:,}".format(cap)))


def member_run_budget(ev, d, st):
    """budget_gate, for an eq member: the hand-back order once its run's cap is spent, else None."""
    w = identify(ev, d) if ev.get("agent_id") else None
    if not w or w["role"] != "member":
        return None
    plan = plan_of(w["rd"], w["run"]) if w["rd"] else None
    bad = run_budget(ev, d, w, plan, st)
    if not bad:
        return None
    return why("run eq:%s's token cap is spent: make no more tool calls and give your final reply now (your "
               "JSON object with what you have)." % w["run"])


# ---------------------------------------------------------------- rule 11: prune
def prune(root, current, now):
    """SessionStart: another session's eq/ store is removed once nothing under it changed for
    EQ_STORE_IDLE_S (results were copied to the project); stale tickets (> 2 x TTL) go too."""
    removed = []
    try:
        names = os.listdir(root)
    except OSError:
        return removed
    for s in names:
        p = os.path.join(root, s)
        e = os.path.join(p, "eq")
        if os.path.normpath(p) == os.path.normpath(current) or not is_dir(e):
            continue
        newest, seen = 0.0, 0
        for base, dirs, files in os.walk(e):
            for f in [base] + [os.path.join(base, x) for x in files]:
                seen += 1
                try:
                    newest = max(newest, os.lstat(f).st_mtime)
                except OSError:
                    pass
            if seen > 20000:
                newest = now                    # too big to judge here: kept
                break
        if now - newest > EQ_STORE_IDLE_S:
            shutil.rmtree(e, ignore_errors=True)
            removed.append(e)
    tickets = os.path.join(root, "eq-tickets")
    try:
        for f in os.listdir(tickets):
            fp = os.path.join(tickets, f)
            if now - os.lstat(fp).st_mtime > 2 * P.TICKET_TTL_S:
                unlink(fp)
    except OSError:
        pass
    return removed


# ---------------------------------------------------------------- entry points (agent_guard call sites)
def _deny_unmatched():
    return why("this agent may be an equilibrium member the guard could not match to its run (an unbound "
               "member slot of its type is pending), so it runs nothing. Report STATUS: blocked.")


def pre_tool(ev, d):
    """`budget` mode, every PreToolUse: the tool allowlists (leader, members), a member's cwd and file paths.
    Denies through agent_guard; None when nothing applies."""
    w = identify(ev, d)
    if w is None:
        return None
    tool = G.canonical_tool(ev.get("tool_name"))
    ti = ev.get("tool_input") if isinstance(ev.get("tool_input"), dict) else {}
    if w["role"] == "unmatched":
        bad = None if tool in ALWAYS_TOOLS else _deny_unmatched()
    elif w["role"] == "leader":
        bad = leader_tools(ev, d, w, tool, ti)
    else:
        bad = member_tools(ev, d, w, tool)
        if not bad and (tool in FILE_TOOLS or tool in SHELL_TOOLS):
            bad = member_cwd(ev, d, w) or member_paths(ev, d, w, tool, ti)
    if bad:
        G.deny(bad)
    return None


def bash_pre(ev, command, tool):
    """`no-push` mode (Bash, Monitor, PowerShell): the leader's executor calls, the members' shell rules, and
    no stack-eq or stack-eq-check for anyone else."""
    d = G.sdir(ev.get("session_id"))
    w = identify(ev, d)
    bad = None
    if w is not None and w["role"] == "leader":
        bad = leader_bash(ev, d, w, command, tool)
    elif w is not None and w["role"] == "member":
        bad = member_cwd(ev, d, w) or member_bash(ev, d, w, command, tool)
    elif w is not None:
        bad = _deny_unmatched()
    elif isinstance(command, str) and invokes(command, ("stack-eq", "stack-eq-check")):
        bad = why("only the equilibrium leader runs stack-eq and stack-eq-check (stack-eq runs outside the "
                  "sandbox with the guard's ticket). Spawn equilibrium with an eq header instead.")
    if bad:
        G.deny(bad)
    return None


def agent_pre(ev, d, ti):
    """PreToolUse Agent: the consent-relay check, the spawn gate (child equilibrium), the leader's member
    spawns; members and unmatched agents spawn nothing. None, or {"patch", "commit", "why"} for on_agent."""
    bad = consent_relay(ev, d, ti.get("prompt"))
    if bad:
        G.deny(bad)
    child = G.norm(ti.get("subagent_type"))
    w = identify(ev, d)
    if w is not None and w["role"] == "leader":
        got = leader_agent(ev, d, w, ti)
    elif w is not None:
        got = why("eq members spawn nothing.") if w["role"] == "member" else _deny_unmatched()
    elif child in G.EQ_TYPES:
        got = spawn_gate(ev, d, ti)
    else:
        return None
    if isinstance(got, str):
        G.deny(got)
    return got


def agent_commit(ev, eqd):
    """on_agent, after every other gate allowed the call: write what the eq decision needs."""
    eqd["commit"]()
    return None


def send_pre(ev, d, ti, target_id):
    """PreToolUse SendMessage: the consent-relay check for every sender; the leader's reconcile tokens become
    the stored view (stamped here, never as a user relay); members send nothing. None or {"message"}."""
    bad = consent_relay(ev, d, ti.get("message"))
    if bad:
        G.deny(bad)
    w = identify(ev, d)
    if w is None:
        return None
    if w["role"] == "leader":
        got = leader_send(ev, d, w, ti, target_id)
    else:
        got = why("eq members send no messages (W1).") if w["role"] == "member" else _deny_unmatched()
    if isinstance(got, str):
        G.deny(got)
    got["stamp"] = STAMP % w["aid"] if w["aid"] else ""
    return got


def send_commit(ev, eqs):
    eqs["commit"]()
    return None


def agent_post(ev, d, child_id, status):
    """PostToolUse Agent: bind the spawned member's (or leader's) agent id from tool_response; a foreground
    leader that completed ends its run."""
    ti = ev.get("tool_input") if isinstance(ev.get("tool_input"), dict) else {}
    tid, sid = ev.get("tool_use_id"), ev.get("session_id")
    if not child_id or not tid:
        return None
    child_id = G.ident(child_id)
    if G.norm(ti.get("subagent_type")) in G.EQ_TYPES:
        try:
            rd = run_dir(sid, run_id(sid, tid))
        except P.PolicyError:
            return None
        if not is_dir(rd):
            return None
        create_json(os.path.join(rd, "leader.json"), {"agent_id": child_id, "ts": time.time()})
        G.reg_put(d, child_id, {"eq_run": os.path.basename(rd), "eq_role": "leader"})
        if str(status or "").lower() == "completed":
            create_json(os.path.join(rd, "ended.json"), {"ts": time.time(), "why": "leader completed"})
        return None
    w = identify(ev, d)
    if not w or w["role"] != "leader" or not w["rd"]:
        return None
    found = []

    def bind_slot(cur):
        for k, m in cur.items():
            if isinstance(m, dict) and m.get("tool_use_id") == tid and m.get("agent_id") in (None, child_id):
                m["agent_id"] = child_id
                found.append(int(k))
    members_update(w["rd"], bind_slot)
    if found:
        G.reg_put(d, child_id, {"eq_run": w["run"], "eq_role": "member", "eq_member": found[0]})
    return None


def agent_failed(ev, d):
    """PostToolUseFailure / PermissionDenied Agent: a leader spawn that never ran ends its run; a member
    spawn that never ran frees its slot (it may be spawned again)."""
    ti = ev.get("tool_input") if isinstance(ev.get("tool_input"), dict) else {}
    tid, sid = ev.get("tool_use_id"), ev.get("session_id")
    if not tid:
        return None
    if G.norm(ti.get("subagent_type")) in G.EQ_TYPES:
        rd = run_dir(sid, run_id(sid, tid))
        if is_dir(rd):
            create_json(os.path.join(rd, "ended.json"), {"ts": time.time(), "why": "spawn failed"})
        return None
    w = identify(ev, d)
    if not w or w["role"] != "leader" or not w["rd"]:
        return None

    def free(cur):
        for k in [k for k, m in cur.items() if isinstance(m, dict) and m.get("tool_use_id") == tid
                  and not m.get("agent_id")]:
            del cur[k]
    members_update(w["rd"], free)
    return None


def subagent_start(ev, d):
    """SubagentStart: link the agent; a member is running again; a resumed leader's run is live again."""
    w = identify(ev, d)
    if not w or not w["rd"]:
        return None
    if w["role"] == "leader":
        unlink(os.path.join(w["rd"], "ended.json"))
    elif w["role"] == "member":
        def running(cur):
            r2 = cur.get(str(w["member"]))
            if isinstance(r2, dict) and r2.get("status") != "abstain":
                r2["status"] = "running"
        members_update(w["rd"], running)
    return None


def subagent_stop(ev, d):
    """SubagentStop: members are captured (rule 6; their copy goes to the store, not reports/), the leader's
    reply checked (rule 4). {"block": reason} | {"member": True} | {"leader": True} | None."""
    w = identify(ev, d)
    if w is None or w["role"] == "unmatched":
        return None
    if w["role"] == "member":
        bad = capture(ev, d, w)
        return {"block": bad} if bad else {"member": True}
    bad = leader_reply(ev, d, w)
    if bad:
        return {"block": bad}
    if w["rd"]:
        create_json(os.path.join(w["rd"], "ended.json"), {"ts": time.time(), "why": "leader stopped"})
    return {"leader": True}


def task_stop_post(ev, d):
    """PostToolUse TaskStop: a stopped member abstains for the rest of its run."""
    ti = ev.get("tool_input") if isinstance(ev.get("tool_input"), dict) else {}
    target = ti.get("task_id") or ti.get("shell_id")
    if not isinstance(target, str):
        return None
    target = G.ident(target)
    for run, rd in session_runs(ev.get("session_id")):
        def stop(cur):
            for m in cur.values():
                if isinstance(m, dict) and m.get("agent_id") == target:
                    m["status"] = "abstain"
                    rnd = str(m.get("round") or 0)
                    rounds = m.setdefault("rounds", {})
                    if rounds.get(rnd) != "captured":
                        rounds[rnd] = "abstain"
        if any(isinstance(m, dict) and m.get("agent_id") == target for m in members_of(rd).values()):
            members_update(rd, stop)
    return None


def bash_post(ev, d):
    """PostToolUse / PostToolUseFailure Bash: the leader's pending stack-eq-check call gets its verdict."""
    w = identify(ev, d)
    tid = ev.get("tool_use_id")
    if not w or w["role"] != "leader" or not w["rd"] or not tid:
        return None
    for name in sorted(os.listdir(w["rd"])):
        m = re.fullmatch(r"r([0-9])", name)
        if not m:
            continue
        rr = os.path.join(w["rd"], name)
        for f in sorted(os.listdir(rr)):
            mm = re.fullmatch(r"check-c([1-9])\.pending\.json", f)
            if mm and (jread(os.path.join(rr, f)) or {}).get("tool_use_id") == tid:
                return check_verdict(ev, w, int(m.group(1)), int(mm.group(1)))
    return None


def ask_post(ev, d):
    return consent_record(ev, d)


# ---------------------------------------------------------------- rule 13: self-test
def self_test():
    """Problems (empty = fine): the tables, the shapes, the git and path rules, the trailer and consent
    readers, eq_core's capture API."""
    problems = []
    if not G.EQ_TYPES <= set(G.AGENTS):
        problems.append("eq: EQ_TYPES %s not all stack agents" % sorted(G.EQ_TYPES))
    for t in G.EQ_TYPES:
        row = set(G.POLICY.get(t) or ())
        if row - set(P.MEMBER_TYPES) or t in row:
            problems.append("eq: POLICY[%s] must list member types only" % t)
        for reader in G.WEB_INGESTING_TYPES:
            if t in G.POLICY.get(reader, []):
                problems.append("eq: web reader %s may spawn %s" % (reader, t))
    exe = os.path.join(CONFIG, "bin", "stack-eq")
    for cmd, ok in (("%s plan --run 0123abcd" % exe, True), ("%s help" % exe, True),
                    ("%s plan --run 0123abcd; rm -rf ~" % exe, False), ("stack-eq plan --run 0123abcd", False),
                    ("%s plan --run 0123abcd | sh" % exe, False)):
        words, bad = _shape(cmd, (exe,))
        if (bad is None) != ok:
            problems.append("eq: leader shape check misjudges %r" % cmd[:60])
    for cmd, ok in (("git status", True), ("git diff", True), ("git log --oneline -5", True), ("git ls-files", True),
                    ("git show HEAD:README.md", True), ("git commit -qm x", False), ("git stash", False),
                    ("git log --all", False), ("git diff main", False), ("git -C ../x status", False),
                    ("env git worktree list", False), ("sh -c 'git merge x'", False), ("x=$(git branch -a)", False),
                    ("xargs git checkout", False), ("echo ok", True)):
        if (git_rule(cmd) is None) != ok:
            problems.append("eq: member git rule misjudges %r" % cmd)
    for cmd, want in (("%s help" % exe, True), ("FOO=1 stack-eq-check --run x", True), ("git log -- %s" % exe, False),
                      ("bash -c 'stack-eq x'", True)):
        if invokes(cmd, ("stack-eq", "stack-eq-check")) != want:
            problems.append("eq: stack-eq caller check misjudges %r" % cmd)
    tr = P.render_check_trailer("0123abcd", 1, 0, 0, False, b"ok")
    if P.parse_check_trailer(tr) is None or P.parse_check_trailer(tr + "\nx") is not None:
        problems.append("eq: the check trailer reader misjudges its probes")
    ev = {"tool_response": {"answers": {"Run eq:0123abcd (est. 5 tokens) or Cancel?": "Cancel"}},
          "tool_input": {"questions": [{"options": [{"label": "Run eq:0123abcd"}]}]}}
    if any(P.CONSENT_RE.search(a) for a in chosen_answers(ev)):
        problems.append("eq: consent reads a question or an option, not only the chosen answer")
    if not any(P.CONSENT_RE.search(a) for a in chosen_answers({"tool_response": {"answers": {"q": "Run eq:0123abcd"}}})):
        problems.append("eq: consent misses a chosen `Run eq:R` answer")
    root = "/tmp/eqst/proj"
    kw = {"config_dir": "/tmp/eqst/cfg", "state_root": "/tmp/eqst/state", "project_root": root, "run": "0123abcd",
          "member": 1, "member_dirs": {"1": root + "/.claude-work/eq/0123abcd/m1",
                                       "2": root + "/.claude-work/eq/0123abcd/m2"}, "member_worktrees": {}}
    for path, ok in ((root + "/.claude-work/eq/0123abcd/m1/x", True), (root + "/.claude-work/eq/0123abcd/m2/x", False),
                     ("/tmp/eqst/cfg/projects/p/s/subagents/agent-1.jsonl", False), ("/tmp/eqst/state/s/reports", False),
                     (root + "/src/a.py", True)):
        if (P.member_path_denied(path, **kw) is None) != ok:
            problems.append("eq: member path rule misjudges %s" % path)
    if P.member_path_denied(root, recursive=True, **kw) is None:
        problems.append("eq: a search from the project root passes its eq work area")
    if sys.version_info < (3, 13):          # hooks run on >= 3.13 (bin/stack-hook); eq_core needs it
        return problems
    try:
        c = core()
        schemas = c.load_schemas(os.path.join(HERE, "eq_schemas.json"))
        if not all(isinstance(schemas.get(k), dict) for k in P.CLASSES):
            problems.append("eq: eq_schemas.json lacks a class schema")
        if c.parse_member_reply("not json", schemas.get("RS") or {})[0] is not None:
            problems.append("eq: eq_core.parse_member_reply accepts prose")
    except Exception as exc:  # noqa: BLE001
        problems.append("eq: eq_core.py or eq_schemas.json not loadable (%s: %s)" % (type(exc).__name__, exc))
    return problems
