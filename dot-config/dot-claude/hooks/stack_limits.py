#!/usr/bin/env python3
"""stack_limits.py - learned limits with per-session immutable snapshots (stdlib only, Python 3.8+).

Learnable variables (stack_limits_seed.json beside this file; each with a repo floor and ceiling
that no evidence, file or command can cross):
  turns.<type>                 the guard's turn budget per run, in API calls (seed and ceiling: the
                               agent's frontmatter maxTurns, which stays the backstop)
  soft.agent.<type>            soft context limit per agent segment (seed: agent_guard SOFT_LIMITS)
  hard.agent.<type>            hard context cap per agent segment (seed: unset = off)
  soft.prompt, hard.prompt     per human prompt (seed 33M / 300M; hard.prompt user-set: seed = floor)
  soft.prompt.<type>           per human prompt while an agent of that type runs (agent_guard
                               SOFT_PROMPT_CTX_BY_TYPE, user-set: seed = floor, so the learner only
                               raises it; prompt_soft_limit() applies the largest running one)
  soft.session, hard.session   per session (seed unset / 1.92B)
blackcat has no per-agent variable. Fixed
guards (depth, fan-out, BlackCat, TTLs, MCP cap, images, policy, read gate, the scale
and sched-policy knobs) are never variables: a fixed-guard name in live.json or proposals.json
invalidates that file (FIXED_GUARDS).

Evidence: the collector's rows (stack_usage.py: usage/runs*.csv v1, runs2*.csv v2, runs3*.csv v3).
An agent row whose `model` (v3) is set and is not its type's frontmatter model (model_mismatch: a
/override-agent run, which is that session's only) is no evidence for the type, its pool or the
prompt windows it ran in; v1/v2 rows and an empty model (unknown) count as before. Rows are never
rewritten: the filter is at read time, and proposals.json counts the rows it skipped.
An agent row with `eq_run` (the collector copies it from the guard's registry record of an
equilibrium leader or member: they run with a brief shape and caps no ordinary run has) is no
evidence either, counted apart (eq_run).

Files under ${XDG_STATE_HOME:-~/.local/state}/claude-agent-stack/limits/ (0700):
  live.json                    learned values, replaced atomically; written only by
                               apply_and_snapshot (SessionStart), the user commands below and
                               `seed` (install.sh: a changed seed reaches the unlearned variables)
  snapshots/<sid>.json         one session's frozen values (0444, created once, hash-checked) and
  snapshots/<sid>.sched_model.json   the scheduler model copied for that session
  proposals.json               the evidence for the next SessionStart (propose(); changes no value)
  bayes.json                   the detached Bayes fitter's output (docs/BAYES.md; read, never written
                               here: untrusted, validated whole, section 4 on any failure)
  history.jsonl                one line per decision (rotated at 5 MB to history.1.jsonl)
  limits.log                   one line per fallback, migration or set-aside file
  limits.lock, proposals.lock  flock files (never nested)

U4, one swap per session: values change only inside apply_and_snapshot for a session id that has
no snapshot yet (SessionStart). Every consumer reads that session's snapshot (session_limits);
resume, compact and clear keep the id and so the snapshot. propose() only writes proposals.json.

Python API: apply_and_snapshot(ev) -> (path, notice), ensure_snapshot(sid, src), propose(paths,
out), seed(), env_name(type[, family]), session_limits(sid), lookup(values, family, type),
prompt_soft_limit(values, running_types); the
shared statistics q, ceil2, derive, boot_ci, support, step (tests/derive_thresholds.py).

CLI (the user's terminal: agents cannot write the state folder; effects reach the next snapshot):
  stack_limits.py show [PATTERN] [--json] [--session SID]
  stack_limits.py history [VAR] [--limit N]
  stack_limits.py stability
  stack_limits.py hold VAR|--all [--sessions N]        release VAR|--all
  stack_limits.py freeze VAR|--all [--value X]         unfreeze VAR|--all
  stack_limits.py rollback VAR|--all --to prev|seed     (also sets hold 1 and d = 1/2)
  stack_limits.py propose [--quiet]    apply --dry-run    seed    status
VAR is a variable name or an fnmatch pattern (soft.agent.*).

Environment: STACK_LIMITS_AUTO=0 (snapshot = seed + env overrides, nothing applied),
STACK_USAGE_COLLECT=0 (no proposals), overrides STACK_MAXTURNS_<TYPE>, STACK_SOFTCTX_<TYPE>,
STACK_HARDCTX_<TYPE>, STACK_SOFT_PROMPT_CTX[_<TYPE>], STACK_PROMPT_CTX_BUDGET, STACK_SOFT_SESSION_CTX,
STACK_SESSION_CTX_BUDGET (digits; 0 = off), recorded with origin "env" in the snapshot.
STACK_BAYES=off|shadow|on (default shadow, a fixed knob): off reads no bayes.json; shadow logs each
Bayes decision as a `bayes-shadow` history record and changes nothing; on lets a family in BAYES_LIVE
(empty: the user's step) act. Deny-type families (turns, hard.*) are shadow-only (docs/BAYES.md 3, A).
"""
import errno
import fcntl
import hashlib
import json
import math
import os
import re
import sys
import time
from bisect import bisect_left, bisect_right

SCHEMA = 1                      # proposals.json, snapshots, seed
LIVE_SCHEMA = 2                 # live.json only (2: each state's `bayes` block and `method`, docs/BAYES.md 2.4)
CODE_VERSION = "stack_limits/1"
HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:      # stack_io.py beside this file, also when loaded by path
    sys.path.insert(0, HERE)
from stack_io import now_iso as iso, write_atomic as _write_atomic  # noqa: E402
SEED_PATH = os.path.join(HERE, "stack_limits_seed.json")
SHIPPED_MODEL = os.path.join(HERE, "sched_model.json")

# decision rules (design s6-design-v2 section 4)
M_GRID = (1.25, 1.3, 1.35, 1.4, 1.45, 1.5)
FT_OK = 0.05                    # soft target: smallest m whose false-trip rate is <= 5 %
FT_LOOSEN = 0.10                # loosen only when FT(c) > 10 % (or a tight run)
STEP_MAX = 0.25                 # one step moves at most 25 % x d
D_LEVELS = (1.0, 0.5, 0.25, 0.125)
DEAD_MIN = 0.10                 # dead band: max(10 %, CI width / 2)
STABLE_REL = 0.05
RECENT = 5
SUPPORT_W = 0.35
PROMPT_MIN_N, PROMPT_MIN_SESSIONS, SESSION_MIN_SESSIONS = 30, 3, 5
HARD_P90_MULT, HARD_HMAX_MULT, HARD_OVER_SOFT = 1.5, 1.1, 2.0

# evidence (hostile-CSV limits)
WINDOW_SESSIONS = 20
MAX_X = 400
MAX_TOP = 50
MAX_ROWS = 50000
MAX_LINES_PER_FILE = 200000
SESSION_SHARE = 0.5
CTX_MAX = 1e10
TURNS_MAX = 1e4
TS_MAX = 1e11
BOOT_B = 1000

LOCK_WAIT_S = 1.0               # SessionStart: wait this long for limits.lock, then snapshot live
CMD_LOCK_WAIT_S = 10.0
DEADLINE_S = 2.0                # past it, snapshot from live with no apply
SNAP_KEEP_S = 30 * 86400
HISTORY_MAX = 5 << 20
LOG_MAX = 1 << 20
NOTICE_MAX = 300
SCHED_POLICIES = ("report", "fresh_fixer")
SCHED_POLICY_DEFAULT = "report"         # fresh_fixer: opt-in (user decision 2026-10-03)
SOURCES = ("startup", "resume", "clear", "compact", "fork")
STATUSES = ("supported", "provisional", "pooled", "unset")

ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}\Z")
TYPE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,79}\Z")
HEX16_RE = re.compile(r"^[0-9a-f]{16}\Z")
EQ_RUN_RE = re.compile(r"^[0-9a-f]{8}\Z")                                  # stack_usage.EQ_RUN_RE
HEX64_RE = re.compile(r"^[0-9a-f]{64}\Z")
FIT_SRC_RE = re.compile(r"^fit:[0-9a-f]{16}\Z")                              # proposals' bayes_hyper_source
SEED_SHA_RE = re.compile(r"^sha256:[0-9a-f]{64}\Z")
COMMIT_RE = re.compile(r"^[0-9a-f]{7,40}\Z")
MODEL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:@/\[\]-]{0,127}\Z")     # stack_usage.MODEL_RE
# the model families a recorded segment can name (model_family); haiku only to tell such a run apart
# (a built-in agent, an older session): no stack agent or /override-agent picks it
MODEL_ALIASES = ("haiku", "sonnet", "opus", "fable")
FM_MODEL_RE = re.compile(r"(?m)^model:\s*([A-Za-z0-9._-]+)\s*(?:#.*)?$")   # agent_guard.MODEL_RE
VAR_RE = re.compile(r"^(?:(?:turns|soft\.agent|hard\.agent|soft\.prompt)\.[a-z0-9][a-z0-9_.:-]{0,79}"
                    r"|(?:soft|hard)\.(?:prompt|session))$")

TYPE_FAMILIES = ("turns", "soft.agent", "hard.agent")
SCOPE = {"turns": "type", "soft.agent": "type", "hard.agent": "type", "soft.prompt": "prompt",
         "hard.prompt": "prompt", "soft.session": "session", "hard.session": "session"}
QUANTITY = {"turns": "api_calls", "soft.agent": "ctx", "hard.agent": "ctx", "soft.prompt": "window_ctx",
            "hard.prompt": "window_ctx", "soft.session": "ctx", "hard.session": "ctx"}
# the hit columns of a variable's own kind (limit-hits.jsonl folded into runs2.csv by the collector)
OWN_HITS = {"turns": ("hit_turn", "turn_limited"), "soft.agent": ("hit_soft",),
            "hard.agent": ("hit_hard_agent",), "soft.prompt": ("hit_soft",),
            "hard.prompt": ("hit_hard_prompt",), "soft.session": ("hit_soft",),
            "hard.session": ("hit_hard_session",)}
PAIR_RATIO = {"soft.agent": 0.8, "soft.prompt": 0.67, "soft.session": 0.8}   # soft <= ratio x hard
# soft.prompt.<type> (agent_guard SOFT_PROMPT_CTX_BY_TYPE): the per-prompt soft limit while an agent
# of that type runs, user-set; its seed is its floor, so only a user command can lower it. Its sample
# is the prompt windows (main rows) in which such an agent ran (agent rows' `window`). hard.prompt is
# user-set too (2026-10-08: seed = floor = ceiling = 300M): a learned value below the floor is read
# as the floor (validate_live), and soft.prompt.<type> <= ratio x hard.prompt holds for every
# shipped pin (140M <= 0.67 x 300M), so the invariant never needs to raise it.
ENV_PREFIX = {"turns": "STACK_MAXTURNS_", "soft.agent": "STACK_SOFTCTX_", "hard.agent": "STACK_HARDCTX_",
              "soft.prompt": "STACK_SOFT_PROMPT_CTX_"}
ENV_SCOPE = {"soft.prompt": "STACK_SOFT_PROMPT_CTX", "hard.prompt": "STACK_PROMPT_CTX_BUDGET",
             "soft.session": "STACK_SOFT_SESSION_CTX", "hard.session": "STACK_SESSION_CTX_BUDGET"}

# Fixed guards: env-only, never learned (design section 1). Names compare upper-case with every run
# of non-alphanumerics as "_".
FIXED_GUARDS = frozenset((
    "CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH",
    "STACK_MAX_FANOUT", "STACK_MAX_FANOUT_BY_TYPE",
    "STACK_BLACKCAT_DELEGATE_ONLY", "BLACKCAT_MAX_STEPS", "BLACKCAT_DISPATCH_WINDOW_S", "BLACKCAT_BACKGROUND",
    "SCREEN_LOCK_TTL_S", "STACK_LEASE_TTL_S", "STACK_RESUME_TTL_S", "STACK_FANOUT_IDLE_S",
    "CLAUDE_CODE_MAX_CONCURRENT_SUBAGENTS", "CLAUDE_CODE_MAX_WEB_SEARCHES_PER_SESSION",
    "STACK_MAX_MCP_CALLS", "POLICY", "READONLY_TYPES", "NO_PUSH", "PROTECTED_PATHS", "STACK_POLICY",
    "STACK_SOFT_LIMIT_SCALE", "STACK_SCHED_POLICY", "READ_GATE", "STACK_BAYES",
    "FLOOR", "CEILING", "FLOORS", "CEILINGS", "MAXTURNS", "MAX_TURNS",
))
FIXED_PREFIXES = ("STACK_IMAGE_", "READ_GATE_", "EXA_MAX_", "JINA_MAX_", "SPIDER_MAX_", "STACK_FANOUT_",
                  "BLACKCAT_")

# Bayes limits (docs/BAYES.md sections 2, 3, A; WP3a): read from limits/bayes.json (the detached fitter's
# output, untrusted) and from the grid blocks propose() adds. In `shadow` (the default) section 4 decides
# every value and each Bayes decision is only logged ("bayes-shadow"); `on` lets a family in BAYES_LIVE
# act. Both sets are empty here: they change only by a reviewed commit with the user's yes (WP6).
RISK = {"soft.agent": 0.1, "soft.prompt": 0.1, "soft.session": 0.1, "turns": 0.02,
        "hard.agent": 0.01, "hard.prompt": 0.01, "hard.session": 0.01}
BAYES_GATE = {"rhat": 1.01, "ess": 400, "div": 0, "ebfmi": 0.3, "edge": 1e-3, "mcse_rel": 0.02}
NEAR = 0.5                      # censoring proxy (A.3 row 6): a row at >= NEAR x the limit in force
QTAB_P = (0.5, 0.8, 0.9, 0.95, 0.975, 0.99, 0.995, 0.999)
CONSTANT_BY_CONSTRUCTION = frozenset({"z_s", "z_g"})
BAYES_MODES = ("off", "shadow", "on")
BAYES_LIVE = frozenset()
BAYES_GRID_LIVE = frozenset()
SOFT_FAMILIES = frozenset({"soft.agent", "soft.prompt", "soft.session"})
DENY_FAMILIES = frozenset({"turns", "hard.agent", "hard.prompt", "hard.session"})
BAYES_FAMILIES = frozenset(TYPE_FAMILIES)       # WP3a: no scope variable gets a block (A.8 item 13)
GRID_FAMILIES = frozenset({"soft.agent"})       # the grid tier: soft families with a type model only
BAYES_MODEL = {"turns": "turns-nb2s-h4", "soft.agent": "ctx-ln-h4", "hard.agent": "ctx-ln-h4"}
HYPER_MODEL = {"turns": "turns-nb2s-h4", "ctx": "ctx-ln-h4"}
BAYES_MAX_BYTES = 4 << 20
BAYES_MAX_DEPTH = 12
HARD_AGENT_T_MIN, HARD_AGENT_T_MAX = 2000000, 200000000
BAYES_TIERS = ("nuts", "grid")
BAYES_STATUSES = ("supported", "pooled", "prior")
LIVE_METHODS = ("empirical", "bayes-nuts", "bayes-grid")
# Q1 (the user, 2026-10-07): deny-type families are shadow-only; a raise here is a programming error
if not (BAYES_LIVE <= SOFT_FAMILIES and BAYES_GRID_LIVE <= BAYES_LIVE):
    raise AssertionError("BAYES_LIVE holds a deny-type family or BAYES_GRID_LIVE is not within BAYES_LIVE")


class SeedError(Exception):
    pass


class LiveInvalid(Exception):
    pass


class CmdError(Exception):
    pass


def is_fixed_guard(name):
    k = re.sub(r"[^A-Z0-9]+", "_", str(name).upper()).strip("_")
    return k in FIXED_GUARDS or k.startswith(FIXED_PREFIXES)


def env_name(atype, family=None):
    """<TYPE> of an agent type (CODE_REVIEWER); with a family, the override's full name
    (env_name("code-reviewer", "turns") -> STACK_MAXTURNS_CODE_REVIEWER)."""
    t = re.sub(r"[^A-Z0-9]", "_", str(atype).upper())
    return ENV_PREFIX[family] + t if family else t


def split_var(var):
    """(family, type or None) of a variable name (soft.prompt.<type> -> ("soft.prompt", type));
    ValueError for anything else."""
    for fam in TYPE_FAMILIES + ("soft.prompt",):
        if var.startswith(fam + "."):
            return fam, var[len(fam) + 1:]
    if var in ENV_SCOPE:
        return var, None
    raise ValueError(f"not a limits variable: {var!r}")


def env_var(var):
    fam, t = split_var(var)
    return env_name(t, fam) if t else ENV_SCOPE[fam]


def lookup(values, family, atype):
    """A type's value in a snapshot's values."""
    return values.get(f"{family}.{atype}")


def prompt_soft_limit(values, running_types=()):
    """The per-prompt soft limit of a snapshot's values (agent_guard.soft_prompt_ctx): soft.prompt,
    raised to the largest soft.prompt.<type> of the agent types running now. None when soft.prompt is off (an env
    override of 0)."""
    best = values.get("soft.prompt")
    if best is None:
        return None
    for t in running_types:
        v = lookup(values, "soft.prompt", t)
        if v is not None and v > best:
            best = v
    return best


# ---------------------------------------------------------------- paths and small I/O
def state_root():
    base = os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state")
    return os.path.join(base, "claude-agent-stack")


def limits_dir():
    return os.path.join(state_root(), "limits")


def usage_dir():
    return os.path.join(state_root(), "usage")


def _p(name):
    return os.path.join(limits_dir(), name)


def snapshots_dir():
    return _p("snapshots")


def snapshot_path(sid):
    """Path of a session's snapshot; pure (session-env computes it without waiting for the file)."""
    if not isinstance(sid, str) or not ID_RE.match(sid):
        raise ValueError("bad session id")
    return os.path.join(snapshots_dir(), sid + ".json")


def candidate_model_path():
    return os.path.join(state_root(), "sched_model.json")


def csv_paths():
    u = usage_dir()
    return [os.path.join(u, n) for n in ("runs.1.csv", "runs.csv", "runs2.1.csv", "runs2.csv", "runs3.1.csv",
                                         "runs3.csv")]


def _mkdirs():
    for d in (state_root(), limits_dir(), snapshots_dir()):
        os.makedirs(d, mode=0o700, exist_ok=True)


def auto_on():
    return os.environ.get("STACK_LIMITS_AUTO", "1").strip() != "0"


def collect_on():
    return os.environ.get("STACK_USAGE_COLLECT", "1").strip() != "0"


def sched_policy():
    v = os.environ.get("STACK_SCHED_POLICY", "").strip().lower()
    return v if v in SCHED_POLICIES else SCHED_POLICY_DEFAULT


_BAYES_WARNED = []


def bayes_mode():
    """STACK_BAYES (env only, a fixed knob): off | shadow | on, lower-cased; unset or anything else is
    `shadow` (an unknown value logged once per process)."""
    raw = os.environ.get("STACK_BAYES")
    v = (raw or "").strip().lower()
    if v in BAYES_MODES:
        return v
    if raw is not None and v and not _BAYES_WARNED:
        _BAYES_WARNED.append(1)
        log(f"STACK_BAYES={raw[:40]!r} is not one of off|shadow|on; shadow")
    return "shadow"


def soft_scale():
    """STACK_SOFT_LIMIT_SCALE as agent_guard.soft_scale reads it (1 when unset or unreadable)."""
    raw = os.environ.get("STACK_SOFT_LIMIT_SCALE", "").strip()
    try:
        v = float(raw) if raw else 1.0
    except ValueError:
        return 1.0
    return v if 0 <= v < float("inf") else 1.0


def _isnum(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def _sha(data):
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _dumps(obj):
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _create_excl(path, data, mode=0o444):
    """Create `path` with `data` only if it does not exist (atomic: a hard link of a complete
    temporary file, else O_EXCL). True when created, False when it existed."""
    tmp = f"{path}.{os.getpid()}.{os.urandom(4).hex()}.tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        os.chmod(tmp, mode)
        try:
            os.link(tmp, path)
            return True
        except FileExistsError:
            return False
        except OSError:          # a file system without hard links
            try:
                fd2 = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
            except FileExistsError:
                return False
            with os.fdopen(fd2, "wb") as fh:
                fh.write(data)
            return True
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass


def _append(path, text, cap):
    try:
        if os.path.getsize(path) > cap:
            root, ext = os.path.splitext(path)
            os.replace(path, root + ".1" + ext)
    except OSError:
        pass
    fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
    try:
        os.write(fd, text.encode("utf-8"))
    finally:
        os.close(fd)


def log(msg):
    """One line in limits.log (fallbacks, migrations, set-aside files). Never raises."""
    try:
        os.makedirs(limits_dir(), mode=0o700, exist_ok=True)
        _append(_p("limits.log"), "{} {}\n".format(iso(), str(msg).replace("\n", " ")[:500]), LOG_MAX)
    except OSError:
        pass


def _history_append(recs):
    if recs:
        _append(_p("history.jsonl"), "".join(_dumps(r) + "\n" for r in recs), HISTORY_MAX)


class Lock:
    """flock on `path`; `ok` tells whether it was taken within `wait` seconds (0 = one try)."""

    def __init__(self, path, wait=0.0):
        self.path, self.wait, self.fd, self.ok = path, wait, None, False

    def __enter__(self):
        try:
            self.fd = os.open(self.path, os.O_RDWR | os.O_CREAT, 0o600)
        except OSError:
            return self
        end = time.monotonic() + self.wait
        while True:
            try:
                fcntl.flock(self.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                self.ok = True
                return self
            except OSError as exc:
                if exc.errno not in (errno.EAGAIN, errno.EACCES, errno.EWOULDBLOCK) or time.monotonic() >= end:
                    return self
            time.sleep(0.005)

    def __exit__(self, *exc):
        if self.fd is not None:
            if self.ok:
                try:
                    fcntl.flock(self.fd, fcntl.LOCK_UN)
                except OSError:
                    pass
            os.close(self.fd)
        return False


# ---------------------------------------------------------------- statistics (shared)
def _qs(xs, p):
    """Linear quantile (numpy's default) of an ascending list."""
    n = len(xs)
    h = (n - 1) * p
    lo = math.floor(h)
    hi = min(lo + 1, n - 1)
    return xs[lo] + (h - lo) * (xs[hi] - xs[lo])


def q(x, p):
    xs = sorted(float(v) for v in x)
    return _qs(xs, p) if xs else float("nan")


def ceil2(v):
    """Round up to 2 significant figures (never below the computed value)."""
    if not v or not math.isfinite(v) or v < 0:
        return v
    e = 10 ** (math.floor(math.log10(v)) - 1)
    return math.ceil(v / e) * e


def _frac_above(xs, t):
    return (len(xs) - bisect_right(xs, t)) / float(len(xs)) if xs else 0.0


def _derive_core(xs, p90, hard=False):
    med = _qs(xs, 0.5)
    grid = (M_GRID[-1],) if hard else M_GRID
    best = None
    for m in grid:
        soft = max(p90 * m, 2 * med)
        ft = _frac_above(xs, soft)
        if best is None or ft < best[2] - 1e-12:
            best = (m, soft, ft)
        if ft <= FT_OK:
            best = (m, soft, ft)
            break
    m, soft, _ = best
    soft = ceil2(soft) if not hard else float(math.ceil(soft))
    return m, soft, med


def derive(x, names=None, hard=False, p90=None):
    """soft = p90 x m with floor 2 x median (tests/derive_thresholds.derive). Soft limits: the
    smallest m in M_GRID with false-trip rate <= 5 %, else the m with the lowest rate; hard: m = 1.5.
    p90 replaces the sample's p90 (a provisional value uses the CI's upper end)."""
    xs = sorted(float(v) for v in x)
    if not xs:
        return {"n": 0, "median": float("nan"), "p90": float("nan"), "max": float("nan"), "m": None,
                    "soft": float("nan"), "ft": float("nan"), "tripped": [], "floor": False, "ci": (None, None),
                    "mult_p90": float("nan")}
    p = _qs(xs, 0.9) if p90 is None else float(p90)
    m, soft, med = _derive_core(xs, p, hard)
    nm = list(names) if names is not None else [None] * len(xs)
    return {"n": len(xs), "median": med, "p90": p, "max": xs[-1], "m": m, "soft": soft, "ft": _frac_above(xs, soft),
                "tripped": [k for v, k in zip(x, nm) if float(v) > soft], "floor": 2 * med > p * m,
                "ci": boot_ci(xs), "mult_p90": soft / p if p else float("nan")}


def _boot_p90s(xs, B, seed):
    import random
    rnd = random.Random(seed).random
    n = len(xs)
    h = (n - 1) * 0.9
    lo = int(h)
    fr = h - lo
    hi = min(lo + 1, n - 1)
    out = []
    for _ in range(B):
        s = sorted([xs[int(rnd() * n)] for _ in range(n)])
        out.append(s[lo] + fr * (s[hi] - s[lo]))
    out.sort()
    return out


def boot_ci(x, B=BOOT_B, seed=0, level=0.90):
    """Bootstrap `level` CI of the p90 (stdlib RNG, seeded); (None, None) below 3 values."""
    xs = sorted(float(v) for v in x)
    if len(xs) < 3:
        return (None, None)
    d = _boot_p90s(xs, B, seed)
    a = (1 - level) / 2
    return (_qs(d, a), _qs(d, 1 - a))


def _width(ci, p90):
    lo, hi = (list(ci or ()) + [None, None])[:2]
    if lo is None or hi is None or not p90 or p90 <= 0:
        return float("inf")
    return (hi - lo) / p90


def support(n, agents, ci, p90, scope="type", sessions=0):
    """A5: (n >= 5 and agents >= 3) or (n >= 3 and agents >= 2 and CI width / p90 <= 0.35);
    the prompt scope needs >= 30 windows from >= 3 sessions, the session scope >= 5 sessions."""
    if scope == "prompt":
        return n >= PROMPT_MIN_N and sessions >= PROMPT_MIN_SESSIONS
    if scope == "session":
        return sessions >= SESSION_MIN_SESSIONS
    if n >= 5 and agents >= 3:
        return True
    return n >= 3 and agents >= 2 and _width(ci, p90) <= SUPPORT_W


def step(c, T, d):
    """The bounded step: T clamped to c x (1 -/+ 0.25 d)."""
    return min(max(T, c * (1 - STEP_MAX * d)), c * (1 + STEP_MAX * d))


def _round_up(v, unit):
    if v <= 0:
        return 0
    return math.ceil(v) if unit == "turns" else int(ceil2(v))


def _round_toward(x, c, unit):
    """Round a stepped value toward c: integers for turns, 3 significant figures for context."""
    if unit == "turns" or x < 1000:
        return math.floor(x) if x > c else math.ceil(x)
    e = 10 ** (math.floor(math.log10(x)) - 2)
    return int(math.floor(x / e) * e) if x > c else int(math.ceil(x / e) * e)


def _clamp(x, f, g):
    return min(max(x, f), g)


def target(kind, unit, xs, p90, soft_ref=None):
    """T of a variable: soft = ceil2(max(p90 m*, 2 med)); hard = max(1.5 p90, 1.1 hmax) rounded
    up, and for hard.agent at least 2 x the soft side (soft_ref)."""
    if kind == "soft":
        return _round_up(_derive_core(xs, p90)[1], unit)
    T = _round_up(max(HARD_P90_MULT * p90, HARD_HMAX_MULT * xs[-1]), unit)
    if soft_ref:
        T = max(T, _round_up(HARD_OVER_SOFT * soft_ref, unit))
    return T


# ---------------------------------------------------------------- seed
_SEED_CACHE = {}


def load_seed(path=None):
    """The validated seed: {schema_version, measured_on, pools, vars, sha}. SeedError when the file
    is missing or invalid (the guard then falls back to its own SOFT_LIMITS)."""
    path = path or SEED_PATH
    try:
        st = os.stat(path)
        key = (path, st.st_mtime_ns, st.st_size)
        if key in _SEED_CACHE:
            return _SEED_CACHE[key]
        with open(path, "rb") as fh:
            raw = fh.read()
        doc = json.loads(raw.decode("utf-8"))
    except (OSError, ValueError) as exc:
        raise SeedError(f"seed {path} unreadable: {exc}")
    seed = _validate_seed(doc)
    seed["sha"] = _sha(raw)
    _SEED_CACHE.clear()
    _SEED_CACHE[key] = seed
    return seed


def _validate_seed(doc):
    if not isinstance(doc, dict) or doc.get("schema_version") != SCHEMA:
        raise SeedError(f"seed: schema_version is not {SCHEMA}")
    V, pools = doc.get("vars"), doc.get("pools")
    if not isinstance(V, dict) or not V or not isinstance(pools, dict):
        raise SeedError("seed: vars/pools missing")
    out = {}
    for v, s in V.items():
        if not isinstance(v, str) or not VAR_RE.match(v) or is_fixed_guard(v) or not isinstance(s, dict):
            raise SeedError(f"seed: bad variable {v!r}")
        fam, _ = split_var(v)
        f, g, sd = s.get("floor"), s.get("ceiling"), s.get("seed")
        unit = "turns" if fam == "turns" else "ctx"
        ok = (isinstance(f, int) and isinstance(g, int) and not isinstance(f, bool) and 0 < f <= g
              and s.get("unit") == unit and s.get("kind") in ("soft", "hard")
              and (sd is None or (isinstance(sd, int) and not isinstance(sd, bool) and f <= sd <= g)))
        if not ok:
            raise SeedError(f"seed: bad entry for {v}")
        out[v] = {"seed": sd, "floor": f, "ceiling": g, "unit": unit, "kind": s["kind"]}
    P = {}
    for k, members in pools.items():
        if not isinstance(members, list) or not all(isinstance(m, str) for m in members):
            raise SeedError(f"seed: bad pool {k!r}")
        P[str(k)] = list(members)
    return {"schema_version": SCHEMA, "measured_on": doc.get("measured_on"), "pools": P, "vars": out}


def _types(seed):
    return sorted({split_var(v)[1] for v in seed["vars"] if split_var(v)[1]})


def _pool_of(seed):
    return {t: p for p, members in seed["pools"].items() for t in members}


# ---------------------------------------------------------------- rows (usage/runs*.csv)
def _num(r, k, cap):
    s = r.get(k)
    if s is None:
        return None
    s = s.strip()
    if not s:
        return None
    v = float(s)
    if not 0 <= v <= cap:          # NaN fails both
        raise ValueError(k)
    return v


def _flag(r, k):
    s = (r.get(k) or "").strip()
    if not s:
        return None
    if s in ("0", "1"):
        return int(s)
    raise ValueError(k)


_HIT_COLS = ("hit_soft", "hit_turn", "hit_hard_agent", "hit_hard_prompt", "hit_hard_session")


def agents_dir_default():
    return os.path.join(os.path.dirname(HERE), "agents")


def agent_models(agents_dir=None):
    """{type: its frontmatter `model`, lower-cased} over <agents>/*.md, parsed as
    agent_guard.agent_defaults does (the first 8 KB, the block between the leading `---` lines); a file
    without a model line, or unreadable, is left out."""
    agents_dir = agents_dir or agents_dir_default()
    out = {}
    try:
        names = sorted(os.listdir(agents_dir))
    except OSError:
        return out
    for n in names:
        if not n.endswith(".md") or not TYPE_RE.match(n[:-3]):
            continue
        try:
            with open(os.path.join(agents_dir, n), encoding="utf-8", errors="replace") as fh:
                head = fh.read(8192)
        except OSError:
            continue
        parts = head.split("\n---", 1) if head.startswith("---") else None
        m = FM_MODEL_RE.search(parts[0]) if parts and len(parts) == 2 else None
        if m:
            out[n[:-3]] = m.group(1).lower()
    return out


def model_family(model):
    """The alias (haiku, sonnet, opus, fable) a model alias or id names, by substring; None when it
    names none (`inherit`, a custom id)."""
    s = (model or "").lower()
    for a in MODEL_ALIASES:
        if a in s:
            return a
    return None


def model_mismatch(models, atype, model):
    """Whether an agent row of type `atype` measured on `model` ran on another model than the type's
    frontmatter `model` (models: agent_models()): the frontmatter names an alias family and the row's
    model id does not contain it (`mixed`, a segment on two models, never does). Never a mismatch: an empty model (v1/v2 rows, none reported), a
    type without a file or a model line, a frontmatter model of no family (`inherit` follows the parent,
    whose model the row does not say: kept, as before)."""
    if not model:
        return False
    exp = models.get(atype)
    fam = model_family(exp)
    return fam is not None and fam not in model.lower()


def parse_row(r):
    """A runs*.csv row (dict of strings) -> the fields the proposer reads, or None when it fails
    the hostile-CSV filter (schema, ids, type, finite non-negative numbers within bounds)."""
    sv = (r.get("schema_version") or "").strip()
    if sv not in ("1", "2", "3"):
        return None
    sess, aid = (r.get("session") or "").strip(), (r.get("id") or "").strip()
    if not ID_RE.match(sess) or not ID_RE.match(aid):
        return None
    try:
        seg = int((r.get("seg") or "").strip())
        ts_s = (r.get("last_ts") or "").strip()
        ts = float(ts_s)
        if not 0 <= seg < 1000000 or not 0 < ts < TS_MAX:
            return None
        comp = _num(r, "compacted", 1e6)          # the collector writes a count: a flag here
        row = {"session": sess, "id": aid, "seg": seg, "ts": ts, "ts_s": ts_s, "sv": int(sv),
               "status": (r.get("status") or "").strip(),
               "api_calls": _num(r, "api_calls", TURNS_MAX), "ctx": _num(r, "ctx", CTX_MAX),
               "window_ctx": _num(r, "window_ctx", CTX_MAX),
               "compacted": None if comp is None else int(comp >= 1), "turn_limited": _flag(r, "turn_limited"),
               "is_main": _flag(r, "is_main"), "window": _num(r, "window", 1e6)}
        for k in _HIT_COLS:
            row[k] = _flag(r, k)
        code = (r.get("status_code") or "").strip()
        if code not in ("", "0", "1", "2"):
            return None
        row["status_code"] = int(code) if code else None
    except ValueError:
        return None
    reg = (r.get("regime") or "").strip()
    row["regime"] = reg if HEX16_RE.match(reg) else None
    src = (r.get("src") or "").strip()
    row["src"] = "seed_v1" if sv == "1" else (src if src in ("measured", "seed_v1") else "measured")
    mdl = (r.get("model") or "").strip() if sv == "3" else ""
    row["model"] = mdl if MODEL_RE.match(mdl) else None      # None: unknown (v1/v2, unmeasured, invalid)
    eqr = (r.get("eq_run") or "").strip() if sv == "3" else ""
    row["eq_run"] = eqr if EQ_RUN_RE.match(eqr) else None   # None: not an equilibrium agent's row
    if aid == "session":
        row["scope"], row["type"] = "session", "blackcat"
    elif aid == "main" or row["is_main"] == 1:
        row["scope"], row["type"] = "main", "blackcat"
    else:
        t = (r.get("type") or "").strip()
        if not TYPE_RE.match(t):
            return None
        row["scope"], row["type"] = "agent", t
    return row


def _csv_rows(fh):
    """The rows of a CSV file as csv.DictReader gives them (a short row's missing cells None, extra
    cells under the key None), each physical line parsed on its own: no valid cell holds a quote, comma
    or newline, so a line the csv module refuses or a NUL (csv on Python < 3.11 refuses it) costs that
    line only, never the rest of the file, and an unbalanced quote cannot swallow the lines after it.
    The same helper as stack_usage._csv_rows (whose strict mode is rotation's)."""
    import csv
    header = None
    for ln in fh:
        try:
            cells = next(csv.reader((ln.replace("\x00", ""),)), None)
        except csv.Error:
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


def read_rows(paths=None, models=None):
    """(rows, stats) over runs.1.csv, runs.csv, runs2.1.csv, runs2.csv, runs3.1.csv, runs3.csv (v1 rows
    read as src = seed_v1), the last row per (session, id, seg) winning; at most MAX_LINES_PER_FILE lines
    a file and MAX_ROWS rows (the newest). Missing files or columns are fine; bad rows are dropped, and a
    malformed line (csv, NUL, bad UTF-8) costs only itself (_csv_rows). Then an agent row that ran on
    another model than its type's frontmatter one (model_mismatch over `models`, default agent_models())
    is left out and counted in stats["model_mismatch"]: after the last-row-wins merge, so an earlier
    row of the same key (a v2 row, a partial one) never stands in for it. A session row older than
    another row of its session is left out too (stats["stale_session"]): a final scan's session row
    spans every row it saw (last_ts = their max), so a later row means the session went on after it
    (an older collector stopped mid-session by the upgrade hand-off, or a resumed session whose last
    collector idled out) and its ctx is no whole session's."""
    rows, stats = {}, {"read": 0, "dropped": 0, "truncated": False, "errors": 0, "model_mismatch": 0,
                       "eq_run": 0, "stale_session": 0}
    for p in csv_paths() if paths is None else paths:
        try:
            with open(p, encoding="utf-8", errors="replace", newline="") as fh:
                for i, r in enumerate(_csv_rows(fh)):
                    if i >= MAX_LINES_PER_FILE:
                        stats["truncated"] = True
                        break
                    stats["read"] += 1
                    pr = parse_row(r)
                    if pr is None:
                        stats["dropped"] += 1
                        continue
                    k = (pr["session"], pr["id"], pr["seg"])
                    rows.pop(k, None)
                    rows[k] = pr
        except FileNotFoundError:
            continue
        except (OSError, ValueError):
            stats["errors"] += 1
    models = agent_models() if models is None else models
    out = [r for r in rows.values() if r["scope"] != "agent" or not model_mismatch(models, r["type"], r["model"])]
    stats["model_mismatch"] = len(rows) - len(out)
    n = len(out)
    out = [r for r in out if r["scope"] != "agent" or r["eq_run"] is None]      # equilibrium runs: no evidence
    stats["eq_run"] = n - len(out)
    newest = {}
    for r in rows.values():
        if r["scope"] != "session":
            newest[r["session"]] = max(newest.get(r["session"], 0.0), r["ts"])
    n = len(out)
    out = [r for r in out if r["scope"] != "session" or r["ts"] >= newest.get(r["session"], 0.0)]
    stats["stale_session"] = n - len(out)
    if len(out) > MAX_ROWS:
        out.sort(key=lambda r: r["ts"], reverse=True)
        out = out[:MAX_ROWS]
        stats["truncated"] = True
    return out, stats


def evidence_id(rows):
    keys = sorted("|".join((r["session"], r["id"], str(r["seg"]), r["ts_s"])) for r in rows)
    return hashlib.sha256("\n".join(keys).encode("utf-8")).hexdigest()


def fingerprint(paths=None):
    fp = []
    for p in csv_paths() if paths is None else paths:
        try:
            s = os.stat(p)
            fp.append([os.path.basename(p), s.st_size, s.st_mtime_ns])
        except OSError:
            fp.append([os.path.basename(p), 0, 0])
    return fp


# ---------------------------------------------------------------- proposer
def _window(rows):
    last = {}
    for r in rows:
        last[r["session"]] = max(last.get(r["session"], 0.0), r["ts"])
    keep = set(sorted(last, key=lambda s: (last[s], s), reverse=True)[:WINDOW_SESSIONS])
    return [r for r in rows if r["session"] in keep]


def _cap_sessions(sample):
    """At most SESSION_SHARE of a sample from one session (time-evenly thinned)."""
    by = {}
    for r in sample:
        by.setdefault(r["session"], []).append(r)
    if not by:
        return sample
    big = max(by, key=lambda s: (len(by[s]), s))
    others = len(sample) - len(by[big])
    cap = math.floor(others * SESSION_SHARE / (1 - SESSION_SHARE))
    if len(by[big]) <= cap:
        return sample
    rs = sorted(by[big], key=lambda r: (r["ts"], r["id"], r["seg"]))
    keep = [rs[(i * len(rs)) // cap] for i in range(cap)] if cap > 0 else []
    return [r for s, v in by.items() if s != big for r in v] + keep


def _intish(v):
    return int(v) if float(v).is_integer() else round(v, 3)


_SCOPE_HITS = {"soft.prompt": ("hit_soft", "hit_hard_prompt"), "hard.prompt": ("hit_soft", "hit_hard_prompt"),
               "soft.session": ("hit_soft", "hit_hard_session"), "hard.session": ("hit_soft", "hit_hard_session")}


def censor_flags(row, fam, lim_in_force, win_hits):
    """Whether a row's quantity is a lower bound (right-censored: it contributes log P(Y >= y)),
    docs/BAYES.md A.3. Agent rows: fam "turns" (api_calls) or "ctx"; first match wins:
    1 not complete, 2 compacted, 3 turn-limited or hit_turn, 4 any measured hit_* = 1, 5 its prompt
    window's main row hit soft or hard.prompt (the main-window join: (session, int(window)) in
    win_hits), 6 status_code 1 with every hit_* empty (a pre-697a685 row): at >= NEAR x the limit in
    force (lim_in_force: that limit, None = off), 7 status_code 1 with hit_* measured 0, 8 status_code
    2: observed, 9 a schema-3 complete row without status_code (ended on a tool_use). Main and session
    rows: fam is the variable family; censored when not complete or on their own scope's hit_soft or
    hard hit."""
    if fam in _SCOPE_HITS:
        return row.get("status") != "complete" or any(row.get(h) == 1 for h in _SCOPE_HITS[fam])
    if row.get("status") != "complete":
        return True
    if row.get("compacted") == 1:
        return True
    if row.get("turn_limited") == 1 or row.get("hit_turn") == 1:
        return True
    hits = [row.get(h) for h in _HIT_COLS]
    if any(h == 1 for h in hits):
        return True
    w = row.get("window")
    if w is not None and (row.get("session"), int(w)) in win_hits:
        return True
    code = row.get("status_code")
    if code == 1:
        if all(h is None for h in hits):
            y = row.get("api_calls" if fam == "turns" else "ctx")
            return y is not None and lim_in_force is not None and y >= NEAR * lim_in_force
        return False
    if code == 2:
        return False
    return code is None and row.get("sv") == 3


def win_hits_of(rows):
    """The (session, prompt window) keys whose main row hit soft or hard.prompt (A.3 row 5): the key
    build_proposals uses for soft.prompt.<type> (an agent row's (session, int(window)) = the main
    row's (session, seg))."""
    return {(r["session"], r["seg"]) for r in rows
            if r["scope"] == "main" and (r.get("hit_soft") == 1 or r.get("hit_hard_prompt") == 1)}


def _bayes_lists(win, qn, cfam, limit_of, win_hits):
    """`b` of a proposals entry (A.8 item 5): the windowed rows with the quantity set, censored rows
    included, no session cap, sorted by (ts, session, id, seg), the newest MAX_X; resume = seg > 0;
    sess = the index of the row's session in order of first appearance."""
    rs = sorted(win, key=lambda r: (r["ts"], r["session"], r["id"], r["seg"]))[-MAX_X:]
    order = {}
    for r in rs:
        order.setdefault(r["session"], len(order))
    return {"y": [_intish(r[qn]) for r in rs],
            "cens": [int(censor_flags(r, cfam, limit_of(r), win_hits)) for r in rs],
            "resume": [int(r["seg"] > 0) for r in rs], "sess": [order[r["session"]] for r in rs]}


def _entry(rows, fam, kind, upto_ref, rng_key, cache, bctx=None):
    qn, hits = QUANTITY[fam], OWN_HITS[fam]
    win = _window([r for r in rows if r[qn] is not None])
    if not win:
        return None

    def base(r):
        if r["status"] != "complete" or r["compacted"] == 1:
            return False
        return fam == "turns" or (r["turn_limited"] != 1 and r["hit_turn"] != 1)

    samp = _cap_sessions([r for r in win if base(r)])
    samp.sort(key=lambda r: (r["ts"], r["session"], r["id"], r["seg"]))
    samp = samp[-MAX_X:]
    if not samp:
        return None
    xs = sorted(r[qn] for r in samp)
    codes = (1,) if kind == "soft" else (0, 1)
    # main-window and session rows carry no status code (the collector leaves it empty): a hit of their
    # own kind there is tight as it stands; an agent row needs done (hard) or partial
    scoped = SCOPE[fam] != "type"
    hit = (lambda r: any(r[h] == 1 for h in hits))
    tight = (lambda r: hit(r) and (r["status_code"] in codes or (scoped and r["status_code"] is None)))
    key = tuple(xs)
    if key not in cache:
        cache[key] = _boot_p90s(xs, BOOT_B, rng_key) if len(xs) >= 3 else []
    dist = cache[key]
    ci = [round(_qs(dist, 0.05), 3), round(_qs(dist, 0.95), 3)] if dist else [None, None]
    prob = [round((len(dist) - bisect_left(dist, v)) / float(len(dist)), 4) if dist else None for v in xs]
    out = {"x": [_intish(v) for v in xs], "prob": prob, "ci": ci, "n": len(xs),
           "agents": len({(r["session"], r["id"]) for r in samp}),
           "sessions": len({r["session"] for r in samp}),
           "healthy": sum(1 for r in samp if not hit(r)),
           "tight": sum(1 for r in win if tight(r)),
           "top": [_intish(v) for v in sorted((r[qn] for r in win), reverse=True)[:MAX_TOP]],
           "n_new": sum(1 for r in samp if r["ts"] > upto_ref),
           "upto": max(r["ts"] for r in samp)}
    if bctx is not None:                                 # the Bayes tier's data (section 4 reads none of it)
        out["b"] = _bayes_lists(win, qn, "turns" if fam == "turns" else "ctx", bctx["limit_of"], bctx["win_hits"])
    return out


def _entry_regime(rows, fam, kind, upto_ref, rng_key, regime, cache, bctx=None):
    """Rows of the current regime when they meet support, else all rows (regime_ok false: at
    most provisional)."""
    if regime:
        reg = [r for r in rows if r["regime"] == regime]
        if reg:
            e = _entry(reg, fam, kind, upto_ref, rng_key, cache, bctx)
            if e and support(e["n"], e["agents"], e["ci"], _qs(e["x"], 0.9), SCOPE[fam], e["sessions"]):
                e["regime_ok"] = True
                return e
    e = _entry(rows, fam, kind, upto_ref, rng_key, cache, bctx)
    if e:
        e["regime_ok"] = False
    return e


def _limits_in_force(seed):
    """limit_of(var) -> function(row) -> the value of `var` in force for that row's session: its
    snapshot's value when limits/snapshots/<session>.json reads ok, else the seed's (A.3)."""
    snaps = {}

    def values(sess):
        if sess not in snaps:
            try:
                doc, state = read_snapshot(sess)
            except (ValueError, OSError):
                doc, state = None, "bad"
            v = doc.get("values") if state == "ok" and isinstance(doc, dict) else None
            snaps[sess] = v if isinstance(v, dict) else None
        return snaps[sess]

    def limit_of(var):
        dflt = seed["vars"].get(var, {}).get("seed")

        def f(r):
            v = values(r["session"])
            x = v.get(var, dflt) if v is not None else dflt
            return x if _isnum(x) and x > 0 else None
        return f
    return limit_of


_UNSET = object()


def build_proposals(seed, paths=None, regime=None, live=None, now=None, models=None, hyper=_UNSET):
    """The proposals document over the given CSV files (pure apart from reading them, the session
    snapshots for the censoring proxy, limits/bayes.json for the grid hyperparameters (load_hyper;
    `hyper` = (hyper, source) given or (None, None)) and, without `models`, the agent files'
    frontmatter models). A soft.agent entry gains a grid `bayes` block only with the hyperparameters
    of a gated fit (no moment path: docs/BAYES.md 2.1)."""
    now = time.time() if now is None else now
    rows, stats = read_rows(paths, models=models)
    eid = evidence_id(rows)
    regime = regime if regime is not None else current_regime()
    if live is None:
        live = read_live(seed)[0]
    lv = (live or {}).get("vars", {})
    upto = (lambda v: float((lv.get(v) or {}).get("upto") or 0))
    by_type, main, sess, windows = {}, [], [], {}
    for r in rows:
        if r["scope"] == "agent":
            by_type.setdefault(r["type"], []).append(r)
            if r["window"] is not None:
                windows.setdefault(r["type"], set()).add((r["session"], int(r["window"])))
        else:
            (main if r["scope"] == "main" else sess).append(r)
    cache, V, P = {}, {}, {}
    win_hits, limit_of = win_hits_of(rows), _limits_in_force(seed)
    if hyper is _UNSET:                                  # STACK_BAYES=off: bayes.json is not read
        hyper, hsrc = load_hyper(seed) if bayes_mode() != "off" else (None, None)
    else:
        hyper, hsrc = hyper or (None, None)
    if not hyper or not isinstance(hsrc, str) or not FIT_SRC_RE.match(hsrc):
        hyper, hsrc = None, None
    for v in sorted(seed["vars"]):
        fam, t = split_var(v)
        if fam == "soft.prompt" and t:          # the prompt windows in which an agent of type t ran
            rs = [r for r in main if (r["session"], r["seg"]) in windows.get(t, ())]
        else:
            rs = by_type.get(t, []) if t else (main if SCOPE[fam] == "prompt" else sess)
        if rs:
            bctx = None
            if fam in BAYES_FAMILIES and t:
                lim_var = ("turns." if fam == "turns" else "soft.agent.") + t
                bctx = {"win_hits": win_hits, "limit_of": limit_of(lim_var)}
            e = _entry_regime(rs, fam, seed["vars"][v]["kind"], upto(v), f"{eid}:{v}", regime, cache, bctx)
            if e:
                if hyper and fam in GRID_FAMILIES:
                    blk = _grid_block_safe(e, hyper, v, seed["vars"][v])
                    if blk:
                        e["bayes"] = blk
                V[v] = e
    for fam in TYPE_FAMILIES:
        kind = "soft" if fam == "soft.agent" else "hard"
        for pool in sorted(seed["pools"]):
            members = [t for t in seed["pools"][pool] if f"{fam}.{t}" in seed["vars"]]
            rs = [r for t in members for r in by_type.get(t, [])]
            if rs:
                ref = min(upto(f"{fam}.{t}") for t in members)
                e = _entry_regime(rs, fam, kind, ref, f"{eid}:{fam}:{pool}", regime, cache)
                if e:
                    P[f"{fam}:{pool}"] = e
    return {"schema_version": SCHEMA, "generated": iso(now), "evidence_id": eid,
            "rows_upto": max([r["ts"] for r in rows] or [0]), "rows": len(rows),
            "dropped": stats["dropped"], "model_mismatch": stats["model_mismatch"],
            "eq_run": stats["eq_run"], "stale_session": stats["stale_session"], "truncated": stats["truncated"], "regime": regime,
            "fingerprint": fingerprint(paths), "vars": V, "pools": P,
            "bayes_hyper_source": hsrc, "bayes_seed_sha": seed["sha"] if hsrc else None}


def propose(paths=None, out=None, regime=None, now=None):
    """Rows -> proposals.json (under proposals.lock, non-blocking). Changes no live value (U4).
    None when collection is off (STACK_USAGE_COLLECT=0) or another proposer holds the lock."""
    if not collect_on():
        return None
    seed = load_seed()
    out = out or _p("proposals.json")
    d = os.path.dirname(out)
    os.makedirs(d, mode=0o700, exist_ok=True)
    with Lock(os.path.join(d, "proposals.lock")) as lk:
        if not lk.ok:
            return None
        doc = build_proposals(seed, paths, regime, now=now)
        _write_atomic(out, _dumps(doc).encode("utf-8"))
    return doc


def _valid_entry(e, unit):
    """A proposals entry, normalized; None when malformed (it is then ignored)."""
    if not isinstance(e, dict):
        return None
    cap = TURNS_MAX if unit == "turns" else CTX_MAX
    x = e.get("x")
    if not isinstance(x, list) or not 1 <= len(x) <= MAX_X or not all(_isnum(v) and 0 <= v <= cap for v in x):
        return None
    ci = e.get("ci")
    if not isinstance(ci, list) or len(ci) != 2:
        return None
    if ci[0] is None or ci[1] is None:
        ci = [None, None]
    elif not (_isnum(ci[0]) and _isnum(ci[1]) and 0 <= ci[0] <= ci[1] <= cap):
        return None
    xs = sorted(float(v) for v in x)
    n = len(xs)
    ints = {}
    for k in ("agents", "sessions", "tight", "n_new"):
        v = e.get(k, 0)
        if not isinstance(v, int) or isinstance(v, bool) or v < 0:
            return None
        ints[k] = min(v, n) if k in ("agents", "sessions") else v
    up = e.get("upto", 0)
    if not _isnum(up) or not 0 <= up < TS_MAX:
        return None
    top = e.get("top") or []
    if not isinstance(top, list) or len(top) > MAX_TOP or not all(_isnum(v) and 0 <= v <= cap for v in top):
        return None
    out = dict(ints, x=xs, ci=ci, n=n, upto=float(up), top=[float(v) for v in top],
               regime_ok=e.get("regime_ok") is True)
    if "b" in e:                                         # Bayes-tier keys: kept only when they validate
        b = _valid_b(e["b"], cap)
        if b is not None:
            out["b"] = b
    if "bayes" in e:
        blk = _valid_block(e["bayes"], unit)
        if blk is not None and blk["tier"] == "grid":
            out["bayes"] = blk
    return out


def _valid_b(b, cap):
    """A proposals entry's `b` lists (A.8 item 5), normalized; None when malformed."""
    if not isinstance(b, dict):
        return None
    y, c, r, s = b.get("y"), b.get("cens"), b.get("resume"), b.get("sess")
    if not all(isinstance(v, list) for v in (y, c, r, s)) or not len(y) == len(c) == len(r) == len(s) <= MAX_X:
        return None
    if not all(_isnum(v) and 0 <= v <= cap for v in y):
        return None
    if not all(type(v) is int and v in (0, 1) for v in c + r):         # type() is int: no bools
        return None
    if not all(type(v) is int and 0 <= v <= MAX_X for v in s):
        return None
    return {"y": [float(v) for v in y], "cens": list(c), "resume": list(r), "sess": list(s)}


def validate_proposals(doc, seed):
    """(proposals, None) or (None, reason). A fixed-guard name anywhere in vars/pools invalidates
    the whole file; malformed entries and unknown names are dropped."""
    if not isinstance(doc, dict) or doc.get("schema_version") != SCHEMA:
        return None, "schema"
    eid, V, P = doc.get("evidence_id"), doc.get("vars"), doc.get("pools", {})
    if not isinstance(eid, str) or not HEX64_RE.match(eid) or not isinstance(V, dict) or not isinstance(P, dict):
        return None, "structure"
    for k in list(V) + [str(k).split(":", 1)[-1] for k in P] + list(P):
        if is_fixed_guard(k):
            return None, f"fixed guard {k}"
    out_v, out_p = {}, {}
    hsrc, hsha = doc.get("bayes_hyper_source"), doc.get("bayes_seed_sha")
    grid_ok = isinstance(hsrc, str) and FIT_SRC_RE.match(hsrc) is not None and hsha == seed["sha"]
    for v, e in V.items():
        if v in seed["vars"]:
            ne = _valid_entry(e, seed["vars"][v]["unit"])
            if ne:
                if "bayes" in ne and not (grid_ok and split_var(v)[0] in GRID_FAMILIES):
                    del ne["bayes"]                      # a grid block only on a gated fit's hyperparameters
                out_v[v] = ne
    for k, e in P.items():
        fam, _, pool = str(k).partition(":")
        if fam in TYPE_FAMILIES and pool in seed["pools"]:
            ne = _valid_entry(e, "turns" if fam == "turns" else "ctx")
            if ne:
                ne.pop("b", None)
                ne.pop("bayes", None)
                out_p[k] = ne
    return {"schema_version": SCHEMA, "evidence_id": eid, "generated": doc.get("generated"),
            "regime": doc.get("regime"), "fingerprint": doc.get("fingerprint"),
            "vars": out_v, "pools": out_p, "bayes_hyper_source": hsrc if grid_ok else None,
            "bayes_seed_sha": hsha if grid_ok else None}, None


def load_proposals(seed):
    try:
        with open(_p("proposals.json"), "rb") as fh:
            doc = json.loads(fh.read().decode("utf-8"))
    except FileNotFoundError:
        return None, None
    except (OSError, ValueError, RecursionError) as exc:   # json's C decoder: RecursionError on deep nesting
        return None, f"unreadable ({type(exc).__name__})"
    return validate_proposals(doc, seed)


def proposals_stale():
    try:
        with open(_p("proposals.json"), "rb") as fh:
            doc = json.loads(fh.read().decode("utf-8"))
    except (OSError, ValueError):
        return True
    return not isinstance(doc, dict) or doc.get("fingerprint") != fingerprint()


def maybe_spawn_propose():
    """SessionStart step 6: proposals older than the CSV fingerprint -> `propose` detached."""
    if not collect_on() or not any(os.path.exists(p) for p in csv_paths()) or not proposals_stale():
        return False
    import subprocess
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    try:
        subprocess.Popen([sys.executable or "/usr/bin/python3", os.path.abspath(__file__), "propose", "--quiet"],
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         start_new_session=True, close_fds=True, env=env)
        return True
    except OSError:
        return False


# ---------------------------------------------------------------- Bayes tier: bayes.json, grid blocks
# docs/BAYES.md 2.1 (the file and its validation), A.4-A.6 (gates, decision, fallback chain), A.8.
# limits/bayes.json is written by the detached fitter (WP3b) and is untrusted here: every reader
# validates the whole file and falls back to section 4 on any failure, never raising into a hook.
MODEL_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_.:-]{0,63}\Z")
P_HIT_BELOW, P_HIT_ABOVE = 0.5, 0.001          # p_hit(c) outside the predictive table (A.5)
BAYES_MAX_NODES = 50000           # a full file (176 blocks, hyper, sched) is about 12k values


class _BayesInvalid(Exception):
    pass


def _bad(why):
    raise _BayesInvalid(why)


def _json_int(s):
    if len(s) > 24:                 # Python 3.9 converts a 4-MiB digit string in quadratic time
        raise ValueError("integer too long")
    return int(s)


def _json_float(s):
    if len(s) > 64:
        raise ValueError("number too long")
    return float(s)


def _json_const(s):
    raise ValueError(f"{s} is not a number")


def bayes_path():
    return _p("bayes.json")


def _read_bayes(path=None):
    """(parsed document, None) or (None, "absent" | "size" | "unreadable" | "invalid"): at most
    BAYES_MAX_BYTES, NaN/Infinity tokens and over-long numbers refused (rule 1)."""
    try:
        with open(path or bayes_path(), "rb") as fh:
            raw = fh.read(BAYES_MAX_BYTES + 1)
    except FileNotFoundError:
        return None, "absent"
    except OSError:
        return None, "unreadable"
    if len(raw) > BAYES_MAX_BYTES:
        return None, "size"
    try:
        return json.loads(raw.decode("utf-8"), parse_int=_json_int, parse_float=_json_float,
                          parse_constant=_json_const), None
    except (ValueError, RecursionError, MemoryError):
        return None, "invalid"


def _scan(doc):
    """Structure of the whole file (rules 3, 4): depth <= BAYES_MAX_DEPTH, at most BAYES_MAX_NODES
    values, every float finite, no fixed-guard name as a key anywhere."""
    stack, nodes = [(doc, 0)], 0
    while stack:
        x, d = stack.pop()
        nodes += 1
        if d > BAYES_MAX_DEPTH or nodes > BAYES_MAX_NODES:
            _bad("too deep or too large")
        if isinstance(x, (dict, list)) and nodes + len(stack) + len(x) > BAYES_MAX_NODES:
            _bad("too deep or too large")                # before walking it
        if isinstance(x, dict):
            for k, v in x.items():
                if is_fixed_guard(k):
                    _bad(f"fixed guard {str(k)[:60]}")
                stack.append((v, d + 1))
        elif isinstance(x, list):
            stack.extend((v, d + 1) for v in x)
        elif isinstance(x, float) and not math.isfinite(x):
            _bad("a number is not finite")


def _num_in(x, lo, hi, lo_open=False):
    return _isnum(x) and (x > lo if lo_open else x >= lo) and x <= hi


def _count(x):
    return type(x) is int and x >= 0


def _nonneg_or_none(x):
    return x is None or (_isnum(x) and x >= 0)


def _norm_block(blk, unit):
    """A section 2.1 per-variable block normalized (rule 4); _BayesInvalid otherwise."""
    if not isinstance(blk, dict):
        _bad("block is not an object")
    cap = TURNS_MAX if unit == "turns" else CTX_MAX
    tier, model, status = blk.get("tier"), blk.get("model"), blk.get("status")
    if tier not in BAYES_TIERS or not isinstance(model, str) or not MODEL_ID_RE.match(model) \
            or status not in BAYES_STATUSES:
        _bad("block tier, model or status")
    if not _num_in(blk.get("risk"), 0, 1):
        _bad("block risk")
    T, Traw, pi = blk.get("T"), blk.get("T_raw"), blk.get("pi90")
    if not (_num_in(T, 0, cap) and _num_in(Traw, 0, cap)):
        _bad("block T")
    if not (isinstance(pi, list) and len(pi) == 2 and all(_num_in(v, 0, cap) for v in pi) and pi[0] <= pi[1]):
        _bad("block pi90")
    qt = blk.get("qtab")
    if not isinstance(qt, dict) or qt.get("p") != list(QTAB_P):
        _bad("block qtab.p")
    x = qt.get("x")
    if not (isinstance(x, list) and len(x) == len(QTAB_P) and all(_num_in(v, 0, cap, lo_open=True) for v in x)
            and all(a <= b for a, b in zip(x, x[1:]))):
        _bad("block qtab.x")
    if not isinstance(blk.get("at_bound"), bool):
        _bad("block at_bound")
    if not blk["at_bound"] and max([T, Traw, pi[1]] + x) >= cap:
        _bad("block at the cap without at_bound")        # the writer clamps there and flags it (WP3b)
    cnt = {k: blk.get(k) for k in ("n", "n_cens", "agents", "sessions")}
    if not all(_count(v) for v in cnt.values()) or cnt["n_cens"] > cnt["n"]:
        _bad("block counts")
    sh = blk.get("shrink")
    if not (sh is None or _num_in(sh, -10, 1)):
        _bad("block shrink")
    dg = blk.get("diag")
    if not isinstance(dg, dict):
        _bad("block diag")
    diag = {k: dg.get(k) for k in ("rhat", "ess_bulk", "ess_tail", "mcse_rel", "edge_mass")}
    if not all(_nonneg_or_none(v) for v in diag.values()):
        _bad("block diag values")
    fid = blk.get("fit_id")
    if fid is not None and not (isinstance(fid, str) and HEX16_RE.match(fid)):
        _bad("block fit_id")
    out = dict(cnt, tier=tier, model=model, status=status, risk=blk["risk"], T=T, T_raw=Traw, pi90=list(pi),
               qtab={"p": list(QTAB_P), "x": list(x)}, at_bound=blk["at_bound"], shrink=sh, diag=diag)
    if fid is not None:
        out["fit_id"] = fid
    return out


def _valid_block(blk, unit):
    """A block that passes rule 4, normalized; None otherwise (proposals' grid blocks, live states)."""
    try:
        return _norm_block(blk, unit)
    except _BayesInvalid:
        return None


def _norm_hyper(h, types):
    if not isinstance(h, dict):
        _bad("hyper is not an object")
    if not (_num_in(h.get("tau_t"), 0, 50, lo_open=True) and _num_in(h.get("tau_new"), 0, 50, lo_open=True)
            and _num_in(h.get("rho"), -50, 50) and _num_in(h.get("p_resume"), 0, 1)):
        _bad("hyper scalars")
    T = h.get("types")
    if not isinstance(T, dict):
        _bad("hyper types")
    out = {}
    for t, x in T.items():
        if t not in types:
            _bad(f"hyper type {str(t)[:60]} is not a seed type")
        if not (isinstance(x, dict) and _num_in(x.get("mu"), -50, 50) and _num_in(x.get("scale"), 0, 50, lo_open=True)):
            _bad(f"hyper type {t}")
        out[t] = {"mu": x["mu"], "scale": x["scale"]}
    return {"tau_t": h["tau_t"], "tau_new": h["tau_new"], "rho": h["rho"], "p_resume": h["p_resume"], "types": out}


def _norm_model(m):
    if not isinstance(m, dict) or not isinstance(m.get("gate"), bool) or not isinstance(m.get("diag"), dict):
        _bad("model")
    d = m["diag"]
    out = {k: d.get(k) for k in ("rhat_max", "ess_bulk_min", "ess_tail_min", "ebfmi_min")}
    if not all(_nonneg_or_none(v) for v in out.values()):
        _bad("model diag values")
    dv = d.get("divergences")
    if not (dv is None or _count(dv)):
        _bad("model divergences")
    lists = {k: d.get(k, []) for k in ("constant", "nan")}
    if not all(isinstance(v, list) and all(isinstance(s, str) for s in v) for v in lists.values()):
        _bad("model constant/nan")
    return {"gate": m["gate"], "diag": dict(out, divergences=dv, constant=lists["constant"], nan=lists["nan"])}


def _bayes_doc_checked(doc, seed):
    """Rules 1, 3, 4 and the fields every reader checks (fit_id, seed_sha) of a parsed bayes.json:
    the normalized document; _BayesInvalid otherwise (the whole file is dropped)."""
    if not isinstance(doc, dict):
        _bad("not an object")
    sv = doc.get("schema_version")
    if type(sv) is not int or sv != 1:
        _bad("schema_version")
    code = doc.get("code")
    if not isinstance(code, str) or not code.startswith("stack_bayes/"):
        _bad("code")
    _scan(doc)
    eid, fid = doc.get("evidence_id"), doc.get("fit_id")
    if not (isinstance(eid, str) and HEX64_RE.match(eid)):
        _bad("evidence_id")
    if not (isinstance(fid, str) and HEX16_RE.match(fid)):
        _bad("fit_id")
    if doc.get("seed_sha") != seed["sha"]:
        _bad("seed_sha is not the loaded seed's")
    risk = doc.get("risk")
    if not isinstance(risk, dict) or not all(_num_in(v, 0, 1) for v in risk.values()):
        _bad("risk")
    models = doc.get("models")
    if not isinstance(models, dict):
        _bad("models")
    nm = {}
    for k, m in models.items():
        if not MODEL_ID_RE.match(k):
            _bad("model id")
        nm[k] = _norm_model(m)
    types = set(_types(seed))
    hy = doc.get("hyper") or {}
    if not isinstance(hy, dict) or not set(hy) <= set(HYPER_MODEL):
        _bad("hyper keys")
    nh = {k: _norm_hyper(h, types) for k, h in hy.items()}
    dr = doc.get("drift") or {}
    if not isinstance(dr, dict) or not set(dr) <= set(RISK):
        _bad("drift keys")
    nd = {}
    for f, x in dr.items():
        if not (isinstance(x, dict) and _num_in(x.get("ks_p"), 0, 1) and _count(x.get("sessions"))
                and isinstance(x.get("breach"), bool)):
            _bad(f"drift {f}")
        nd[f] = x["breach"]
    V = doc.get("vars")
    if not isinstance(V, dict):
        _bad("vars")
    nv = {}
    for v, blk in V.items():
        if v not in seed["vars"]:                      # rule 3: an unknown name drops the whole file
            _bad(f"unknown variable {str(v)[:60]}")
        nv[v] = _norm_block(blk, seed["vars"][v]["unit"])
    sc = doc.get("sched")
    if sc is not None:
        if not isinstance(sc, dict):
            _bad("sched")
        st_, sp = sc.get("types") or {}, sc.get("pools") or {}
        if not isinstance(st_, dict) or not isinstance(sp, dict) or not set(st_) <= types \
                or not set(sp) <= set(seed["pools"]):
            _bad("sched names")
    return {"evidence_id": eid, "fit_id": fid, "risk": risk, "models": nm, "hyper": nh, "breach": nd,
            "vars": nv}


def diag_summary(params, divergences, ebfmi_min):
    """models.<id>.diag (section 2.1) from per-parameter diagnostics {name: {"rhat", "ess_bulk",
    "ess_tail"}} (a stdlib helper for the fitter; NaN-strict, A.4): a parameter whose R-hat or ESS
    is not a finite number is listed under `constant` when its name (before any "[") is in
    CONSTANT_BY_CONSTRUCTION, else under `nan`, which fails the gate; max R-hat and min ESS run over
    the rest. max() alone would skip a NaN that is not first (T4a fix 4)."""
    rmax, eb, et, const, nan = 0.0, None, None, [], []
    for name in sorted(params):
        d = params[name] if isinstance(params[name], dict) else {}
        r, b, t = d.get("rhat"), d.get("ess_bulk"), d.get("ess_tail")
        if not (_isnum(r) and _isnum(b) and _isnum(t)):
            base = str(name).split("[", 1)[0]
            lst = const if base in CONSTANT_BY_CONSTRUCTION else nan
            if base not in lst:
                lst.append(base)
            continue
        rmax = max(rmax, r)
        eb = b if eb is None else min(eb, b)
        et = t if et is None else min(et, t)
    return {"rhat_max": rmax, "ess_bulk_min": eb, "ess_tail_min": et, "divergences": divergences,
            "ebfmi_min": ebfmi_min, "constant": const, "nan": nan}


def model_gate(m):
    """Rule 6: recomputed from diag (the `gate` flag must be true but is not trusted alone)."""
    d = m.get("diag") or {}
    G = BAYES_GATE
    return (m.get("gate") is True and _isnum(d.get("rhat_max")) and d["rhat_max"] <= G["rhat"]
            and _isnum(d.get("ess_bulk_min")) and d["ess_bulk_min"] >= G["ess"]
            and _isnum(d.get("ess_tail_min")) and d["ess_tail_min"] >= G["ess"]
            and _count(d.get("divergences")) and d["divergences"] <= G["div"]
            and _isnum(d.get("ebfmi_min")) and d["ebfmi_min"] > G["ebfmi"]
            and d.get("nan") == [] and all(str(c).split("[", 1)[0] in CONSTANT_BY_CONSTRUCTION
                                           for c in d.get("constant") or []))


def quantity_gate(diag):
    """Rule 5: R-hat <= 1.01, bulk and tail ESS >= 400, MCSE(T)/T <= 0.02; a missing value fails."""
    G = BAYES_GATE
    d = diag or {}
    return (_isnum(d.get("rhat")) and d["rhat"] <= G["rhat"] and _isnum(d.get("ess_bulk")) and d["ess_bulk"] >= G["ess"]
            and _isnum(d.get("ess_tail")) and d["ess_tail"] >= G["ess"]
            and _isnum(d.get("mcse_rel")) and d["mcse_rel"] <= G["mcse_rel"])


def _accept_nuts(d, evidence_id):
    """Rules 2, 5, 6, 7 over a checked document: {var: block} of the accepted blocks, or None."""
    if d["evidence_id"] != evidence_id or d["risk"] != RISK:
        return None
    gates = {k: model_gate(m) for k, m in d["models"].items()}
    out = {}
    for v, blk in d["vars"].items():
        fam = split_var(v)[0]
        if fam not in BAYES_FAMILIES:                  # A.8 item 13: that block only
            continue
        if blk["tier"] != "nuts" or blk["risk"] != RISK[fam] or blk["model"] != BAYES_MODEL[fam]:
            continue
        if not gates.get(blk["model"]) or not quantity_gate(blk["diag"]) or d["breach"].get(fam):
            continue
        out[v] = dict(blk, fit_id=d["fit_id"])
    return out


def _accept_hyper(d):
    """load_hyper over a checked document: ({"turns"|"ctx": hyper, "breach": [families]}, "fit:<id>")
    for the models whose gate passes, or (None, None)."""
    hy = {}
    for k, model in HYPER_MODEL.items():
        if k in d["hyper"] and d["models"].get(model) and model_gate(d["models"][model]):
            hy[k] = d["hyper"][k]
    if not hy:
        return None, None
    hy["breach"] = sorted(f for f, b in d["breach"].items() if b)
    return hy, "fit:" + d["fit_id"]


def _checked_doc(seed, doc, who):
    if doc is _UNSET:
        doc, why = _read_bayes()
        if doc is None:
            if why != "absent":
                log(f"bayes.json ignored ({who}): {why}")
            return None
    if doc is None:
        return None
    try:
        return _bayes_doc_checked(doc, seed)
    except _BayesInvalid as exc:
        log(f"bayes.json ignored ({who}): {exc}")
        return None


def load_bayes(seed, evidence_id, doc=_UNSET):
    """{var: block} of the accepted tier-nuts blocks of limits/bayes.json (docs/BAYES.md 2.1 rules
    1-7), or None when the file is absent, invalid, for other evidence or another risk table. Never
    raises. `doc`: an already parsed document (one read per apply)."""
    try:
        d = _checked_doc(seed, doc, "load_bayes")
        return _accept_nuts(d, evidence_id) if d else None
    except Exception as exc:  # noqa: BLE001 - untrusted file, hook context
        log(f"bayes.json ignored (load_bayes): {type(exc).__name__}")
        return None


def load_hyper(seed, doc=_UNSET):
    """(hyperparameters, "fit:<fit_id>") of a gated bayes.json for this seed (rules 1, 3, 4, 6, 7;
    the evidence id may differ), else (None, None). There is no moment-hyperparameter path: without
    a gated fit propose() writes no grid block (T4a BLOCKING 2). Never raises."""
    try:
        d = _checked_doc(seed, doc, "load_hyper")
        return _accept_hyper(d) if d else (None, None)
    except Exception as exc:  # noqa: BLE001
        log(f"bayes.json ignored (load_hyper): {type(exc).__name__}")
        return None, None


def bayes_context(seed, props):
    """The Bayes inputs of one apply from one read of bayes.json: {"nuts": {var: block}, "hyper_source":
    "fit:<id>" | None, "breach": set, "fit_id"}; None when nothing is usable. Never raises."""
    try:
        doc, why = _read_bayes()
        if doc is None:
            if why != "absent":
                log(f"bayes.json ignored: {why}")
            return None
        d = _checked_doc(seed, doc, "apply")
        if d is None:
            return None
        nuts = _accept_nuts(d, props["evidence_id"]) if props else None
        hy, src = _accept_hyper(d)
        if not nuts and src is None:
            return None
        return {"nuts": nuts or {}, "hyper_source": src, "breach": set((hy or {}).get("breach", ())),
                "fit_id": d["fit_id"]}
    except Exception as exc:  # noqa: BLE001
        log(f"bayes.json ignored: {type(exc).__name__}")
        return None


def p_hit(qtab, c):
    """Predicted P(demand > c) from a block's qtab (A.5): F(x_k) = p_k, log(1 - F) linear in log c
    between two table points; below x_0 0.5 ("at least 0.5"), above x_7 0.001; at equal x's the
    larger 1 - p."""
    P, X = qtab["p"], qtab["x"]
    if not _isnum(c) or c <= 0 or c < X[0]:
        return P_HIT_BELOW
    if c > X[-1]:
        return P_HIT_ABOVE
    ties = [1.0 - p for p, x in zip(P, X) if x == c]
    if ties:
        return max(ties)
    for k in range(len(X) - 1):
        if X[k] < c < X[k + 1]:
            den = math.log(X[k + 1]) - math.log(X[k])
            if not den > 0:                                  # adjacent floats: no log gap to interpolate over
                return 1.0 - P[k]
            t = (math.log(c) - math.log(X[k])) / den
            return math.exp((1 - t) * math.log(1.0 - P[k]) + t * math.log(1.0 - P[k + 1]))
    return P_HIT_ABOVE


def hard_agent_T(q99, soft_T):
    """A.8 item 11: hard.agent's T = ceil2(max(q_.99, 2 x soft T)) clamped to [2M, 200M]; (T,
    at_bound)."""
    t = ceil2(max(q99, HARD_OVER_SOFT * soft_T) if _isnum(soft_T) and soft_T > 0 else q99)
    x = _clamp(t, HARD_AGENT_T_MIN, HARD_AGENT_T_MAX)
    return int(x), x != t


_GRID = {}


def _grid_mod():
    """stack_bayes_grid.py beside this file, loaded by path once per process (never through sys.path: a
    module of that name elsewhere is not ours); None when it is missing or fails, logged once."""
    if "m" not in _GRID:
        path = os.path.join(HERE, "stack_bayes_grid.py")
        m = sys.modules.get("stack_bayes_grid")
        if m is None or os.path.abspath(getattr(m, "__file__", "") or "") != os.path.abspath(path):
            m = None
            try:
                if os.path.isfile(path):
                    import importlib.util                    # here only: the hooks never pay for it
                    sp = importlib.util.spec_from_file_location("stack_bayes_grid", path)
                    mod = importlib.util.module_from_spec(sp)
                    sp.loader.exec_module(mod)
                    sys.modules["stack_bayes_grid"] = m = mod
            except Exception as exc:  # noqa: BLE001 - no grid tier, section 4 and nuts blocks unaffected
                log(f"stack_bayes_grid unusable ({type(exc).__name__}); no grid blocks")
                _GRID["m"] = None
                return None
            if m is None:
                log(f"stack_bayes_grid.py missing in {HERE}; no grid blocks")
        _GRID["m"] = m
    return _GRID["m"]


def bayes_grid_block(entry, hyper, var, spec):
    """A tier-grid block (section 2.1) for a soft.agent variable from its proposals entry's `b` and
    the gated fit's ctx hyperparameters: the exact grid posterior of the type's location
    (stack_bayes_grid, censored rows as lower bounds, resume offsets rho), the new-session predictive
    quantiles at QTAB_P, T = ceil2(q_(1-r)). None when the family is not a grid family, is breached,
    the type has no hyperparameters (first seen after the fit) or there is no data."""
    fam, t = split_var(var)
    h = (hyper or {}).get("ctx")
    if fam not in GRID_FAMILIES or not t or not h or fam in (hyper.get("breach") or ()):
        return None
    G = _grid_mod()
    if G is None:
        return None
    tp, b = h["types"].get(t), entry.get("b")
    if not tp or not b or not b.get("y"):
        return None
    r, rho, tau, tnew, pres = RISK[fam], h["rho"], h["tau_t"], h["tau_new"], h["p_resume"]
    mu, sig = tp["mu"], tp["scale"]
    obs, cens, oo, oc = [], [], [], []
    for y, c, rs in zip(b["y"], b["cens"], b["resume"]):
        if y > 0:
            (cens if c else obs).append(math.log(y))
            (oc if c else oo).append(rho * rs)
    if not obs and not cens:
        return None
    etas, w, info = G.lognormal_post(obs, cens, mu, tau, sig, oo, oc)
    qx, ci = [], None
    for p in QTAB_P:
        lq, (l5, l95) = G.lognormal_quantile(etas, w, p, sig, tnew, rho, pres)
        qx.append(math.exp(lq))
        if abs(p - (1 - r)) < 1e-12:
            ci = [math.exp(l5), math.exp(l95)]
    for k in range(1, len(qx)):
        qx[k] = max(qx[k], qx[k - 1])
    T_raw = qx[QTAB_P.index(0.9)] if ci is not None else None
    if T_raw is None or not math.isfinite(T_raw) or qx[-1] > CTX_MAX:
        return None
    m = sum(e * wi for e, wi in zip(etas, w))
    sd = math.sqrt(max(sum(wi * (e - m) ** 2 for e, wi in zip(etas, w)), 0.0))
    sup = entry.get("regime_ok") is not False and support(entry["n"], entry["agents"], entry["ci"],
                                                          _qs(sorted(entry["x"]), 0.9), "type", entry["sessions"])
    n = len(b["y"])
    blk = {"tier": "grid", "model": HYPER_MODEL["ctx"], "risk": r, "T": int(ceil2(T_raw)), "T_raw": round(T_raw, 1),
           "pi90": [round(min(ci), 1), round(max(ci), 1)], "qtab": {"p": list(QTAB_P), "x": [round(v, 1) for v in qx]},
           "at_bound": False, "n": n, "n_cens": sum(b["cens"]), "agents": int(entry.get("agents", 0)),
           "sessions": len(set(b["sess"])), "shrink": round(max(-10.0, 1 - sd / tau), 4),
           "status": "supported" if sup else "pooled",
           "diag": {"rhat": None, "ess_bulk": None, "ess_tail": None, "mcse_rel": None,
                    "edge_mass": info["edge_mass"]}}
    return _valid_block(blk, spec["unit"])


def _grid_block_safe(entry, hyper, var, spec):
    try:
        return bayes_grid_block(entry, hyper, var, spec)
    except Exception as exc:  # noqa: BLE001 - propose() is best effort per variable
        log(f"grid block {var} not built: {type(exc).__name__}")
        return None


def choose_block(v, bctx, props):
    """A.6 for one variable: (block, tier) - the nuts block of bayes.json, else the proposals entry's
    grid block when apply's own load_hyper names the same fit as the proposals, the family is not
    breached and the grid gate passes (edge mass < 1e-3), soft families only; else (None, None)."""
    fam = split_var(v)[0]
    if not bctx or fam not in BAYES_FAMILIES:
        return None, None
    blk = bctx["nuts"].get(v)
    if blk:
        return blk, "nuts"
    ent = (props or {}).get("vars", {}).get(v) or {}
    g = ent.get("bayes")
    src = bctx.get("hyper_source")
    if g and fam in GRID_FAMILIES and src and (props or {}).get("bayes_hyper_source") == src \
            and fam not in bctx["breach"] and g["risk"] == RISK[fam] and g["model"] == HYPER_MODEL["ctx"]:
        edge = g["diag"].get("edge_mass")
        if _isnum(edge) and edge < BAYES_GATE["edge"]:
            return dict(g, fit_id=src[4:]), "grid"
    return None, None


def acts_live(fam, tier, mode):
    """Whether a Bayes decision is the live one (section 3.1): mode on, the family in BAYES_LIVE, and
    for the grid tier also in BAYES_GRID_LIVE. Deny-type families never (Q1)."""
    return mode == "on" and fam in BAYES_LIVE and (tier == "nuts" or fam in BAYES_GRID_LIVE)


# ---------------------------------------------------------------- decision rules (pure)
def _var_state(value):
    return {"value": value, "status": "unset", "n": 0, "agents": 0, "ci": [None, None], "hmax": None,
            "d": 1.0, "upto": 0, "hold": 0, "frozen": None, "changed": None, "recent": [], "prev": None,
            "streak": 0, "bayes": None, "method": None}


def _eff(st):
    return st["frozen"] if st["frozen"] is not None else st["value"]


def _copy_state(st):
    s = dict(st)
    s["recent"] = [dict(r) for r in st.get("recent", [])]
    s["ci"] = list(st.get("ci") or [None, None])
    return s


def _push(s, dec, sign, rel):
    s["recent"] = (s["recent"] + [{"dec": dec, "sign": sign, "rel": None if rel is None else round(rel, 4)}])[-RECENT:]


def classify(fam, ent, pool):
    """(status, entry used, p90 used) - supported: the own sample (current regime) meets support;
    pooled: else the pool's does (T from the pool's CI upper end); provisional: else n >= 3 (T from
    the own CI upper end); (None, ...) below that (the value holds)."""
    scope = SCOPE[fam]
    if ent:
        p = _qs(ent["x"], 0.9)
        if ent["regime_ok"] and support(ent["n"], ent["agents"], ent["ci"], p, scope, ent["sessions"]):
            return "supported", ent, p
    if pool and pool["regime_ok"] and pool["ci"][1] is not None and \
            support(pool["n"], pool["agents"], pool["ci"], _qs(pool["x"], 0.9), "type", pool["sessions"]):
        return "pooled", pool, pool["ci"][1]
    if ent and ent["n"] >= 3 and ent["ci"][1] is not None:
        return "provisional", ent, ent["ci"][1]
    return None, ent or pool, None


def stable(st):
    r = st.get("recent") or []
    return (st.get("status") == "supported" and st.get("d") == 1.0 and len(r) >= RECENT and
            all(x.get("dec") in ("dead", "hold") or abs(x.get("rel") or 0) <= STABLE_REL for x in r[-RECENT:]))


def decide(name, spec, st, ent, pool=None, soft_ref=None, now=None):
    """One variable's decision on new evidence (pure): (new state, history record or None).
    ent: the variable's proposals entry (None without own rows); pool: its pool's entry."""
    fam, _ = split_var(name)
    kind, unit, f, g = spec["kind"], spec["unit"], spec["floor"], spec["ceiling"]
    if not ent and not pool:
        return st, None
    status, use, p90e = classify(fam, ent, pool)
    if status is None and ent is None:
        return st, None                                  # only an unusable pool: nothing to decide
    last = float(st.get("upto") or 0)
    if not (use["n_new"] > 0 and use["upto"] > last):
        return st, None                                  # no new rows in the sample the rules use
    now = time.time() if now is None else now
    s = _copy_state(st)
    s["upto"] = max(last, use["upto"])
    c = st["value"]
    rec = {"var": name, "old": c, "new": c, "decision": None, "n": 0, "p90": None, "ci": [None, None],
           "hmax": None, "ft": None, "tight": (ent or {}).get("tight", 0), "loose": None, "d": s["d"]}

    def done(dec, sign=0, rel=None):
        rec["decision"] = dec
        _push(s, dec, sign, rel)
        return s, rec

    if st["frozen"] is not None:
        return done("frozen")
    if st["hold"]:
        if st["hold"] > 0:
            s["hold"] = st["hold"] - 1
        return done("hold")
    xs = use["x"]
    p90, hmax = _qs(xs, 0.9), xs[-1]
    s.update(n=use["n"], agents=use["agents"], ci=list(use["ci"]), hmax=_intish(hmax))
    rec.update(n=use["n"], p90=round(p90, 3), ci=list(use["ci"]), hmax=_intish(hmax))
    if status is None:
        return done("hold")                              # n < 3
    s["status"] = rec["status"] = status
    T = target(kind, unit, xs, p90e, soft_ref if fam == "hard.agent" else None)
    rec["T"] = T
    if c is None:                                        # unset: set once supported (soft.agent: provisional too)
        if status != "supported" and not (fam == "soft.agent" and status in ("provisional", "pooled")):
            return done("hold")
        x = _clamp(T, f, g)
        s.update(value=x, prev=None, changed=now)
        rec["new"] = x
        return done("step" if x == T else "clamp", 1, None)
    ft_c = _frac_above(xs, c)
    rec.update(ft=round(ft_c, 4), loose=round(c / hmax, 4) if hmax > 0 else None)
    if kind == "hard" and status != "supported":
        return done("hold")                              # hard caps and turns move only when supported
    delta = max(DEAD_MIN, _width(use["ci"], p90) / 2)
    if abs(T - c) <= delta * c:
        _streak(s, True, False)
        return done("dead", 0, 0.0)
    if T > c:
        if not (ft_c > FT_LOOSEN or rec["tight"] >= 1):
            return done("hold")
        sign = 1
    else:
        top = (ent or use)["top"]
        missed = sum(1 for v in top if max(HARD_P90_MULT * p90, T) < v < c)
        rec["missed"] = missed
        if not ((hmax <= 0 or c / hmax > 1.5) or missed >= 1):
            return done("hold")
        T = max(T, min(c, hmax))                         # never below the observed maximum
        if T >= c:
            return done("hold")
        sign = -1
    moves = [r for r in s["recent"] if r.get("sign")][-3:]
    reversal = any(r["sign"] == -sign for r in moves)
    if reversal:
        s["d"] = max(D_LEVELS[-1], s["d"] / 2)
    d = s["d"]
    xr = _round_toward(step(c, T, d), c, unit)
    x = _clamp(xr, f, g)
    rec.update(d=d, new=x, stepped=xr)
    if x == c:
        _streak(s, False, reversal)
        return done("clamp" if x != xr else "hold")
    s.update(prev=c, value=x, changed=now)
    _streak(s, True, reversal)
    return done("step" if x == xr else "clamp", sign, (x - c) / float(c))


def decide_bayes(name, spec, st, block, ent, pool=None, soft_ref=None, now=None):
    """One variable's Bayes decision (docs/BAYES.md A.5, pure): (new state, record or None). block:
    an accepted section 2.1 block (choose_block); ent, pool: as decide(). The prelude (no evidence,
    no new rows, frozen, held) is decide()'s. Then: no own rows -> hold:prior; unset -> set (soft.agent
    with an own row, a deny-type variable only when supported), else hold:unsupported; a deny-type
    variable that is not supported -> hold:unsupported; a soft one that is not supported never falls
    (hold:sparse); dead band r/2 <= p_hit(c) <= 2r or |T - c| <= 10 % c; a deny-type tightening never
    goes below the observed maximum (hold:hmax); else the bounded, damped step of decide()."""
    fam, _ = split_var(name)
    unit, f, g = spec["unit"], spec["floor"], spec["ceiling"]
    if not ent and not pool:
        return st, None
    status, use, _p90e = classify(fam, ent, pool)
    if status is None and ent is None:
        return st, None
    last = float(st.get("upto") or 0)
    if not (use["n_new"] > 0 and use["upto"] > last):
        return st, None
    now = time.time() if now is None else now
    s = _copy_state(st)
    s["upto"] = max(last, use["upto"])
    c = st["value"]
    r = RISK[fam]
    T, at_bound = block["T"], block["at_bound"]
    if fam == "hard.agent":                              # the block's T is already max(q_.99, 2 x soft T): clamp only
        T, ab = hard_agent_T(T, None)
        at_bound = at_bound or ab
    rec = {"var": name, "old": c, "new": c, "decision": None, "n": 0, "T": T, "pi90": list(block["pi90"]),
           "risk": r, "p_hit_c": None, "fit_id": block.get("fit_id"), "tier": block["tier"],
           "at_bound": at_bound, "d": s["d"]}

    def done(dec, sign=0, rel=None):
        rec["decision"] = dec
        _push(s, "hold" if dec.startswith("hold:") else dec, sign, rel)
        return s, rec

    if st["frozen"] is not None:
        return done("frozen")
    if st["hold"]:
        if st["hold"] > 0:
            s["hold"] = st["hold"] - 1
        return done("hold")
    if not ent or block["n"] == 0:
        return done("hold:prior")
    xs = use["x"]
    hmax = xs[-1]
    s.update(n=use["n"], agents=use["agents"], ci=list(use["ci"]), hmax=_intish(hmax), status=status)
    rec.update(n=use["n"], status=status, hmax=_intish(hmax))
    supported = status == "supported"
    deny = fam in DENY_FAMILIES
    if c is None:
        if (fam == "soft.agent" and ent["n"] >= 1) or (deny and supported):
            x = int(_clamp(math.ceil(T), f, g))
            s.update(value=x, prev=None, changed=now)
            rec["new"] = x
            return done("set", 1)
        return done("hold:unsupported")
    ph = p_hit(block["qtab"], c)
    rec["p_hit_c"] = round(ph, 6)
    if deny and not supported:
        return done("hold:unsupported")
    if not deny and not supported and T < c:
        return done("hold:sparse")                       # T4a step 2b: sparse may rise, never fall
    if r / 2 <= ph <= 2 * r or abs(T - c) <= DEAD_MIN * c:
        _streak(s, True, False)
        return done("dead", 0, 0.0)
    if deny and T < c:
        T = max(T, min(c, hmax))                         # never below the observed maximum
        if T >= c:
            return done("hold:hmax")
    sign = 1 if T > c else -1
    moves = [x for x in s["recent"] if x.get("sign")][-3:]
    reversal = any(x["sign"] == -sign for x in moves)
    if reversal:
        s["d"] = max(D_LEVELS[-1], s["d"] / 2)
    d = s["d"]
    xr = _round_toward(step(c, T, d), c, unit)
    x = _clamp(xr, f, g)
    rec.update(d=d, new=x, stepped=xr)
    if x == c:
        _streak(s, False, reversal)
        return done("clamp" if x != xr else "hold")
    s.update(prev=c, value=x, changed=now)
    _streak(s, True, reversal)
    return done("step" if x == xr else "clamp", sign, (x - c) / float(c))


def _streak(s, qualifies, reversal):
    """Three same-sign or dead-band decisions in a row double d (cap 1); a reversal restarts the
    count (it has halved d already)."""
    if reversal:
        s["streak"] = 0
    elif qualifies:
        s["streak"] = s.get("streak", 0) + 1
        if s["streak"] >= 3:
            s["d"] = min(1.0, s["d"] * 2)
            s["streak"] = 0


def _pairs(seed):
    out = [(f"soft.agent.{t}", f"hard.agent.{t}", PAIR_RATIO["soft.agent"]) for t in _types(seed)]
    out += [("soft.prompt", "hard.prompt", PAIR_RATIO["soft.prompt"]),
            ("soft.session", "hard.session", PAIR_RATIO["soft.session"])]
    return [p for p in out if p[0] in seed["vars"] and p[1] in seed["vars"]]


def _raise_hard(seed, live, hv, es, ratio, recs, now):
    """Raise hard variable hv (not frozen) within its ceiling so that es <= ratio x hv; its value."""
    H = live["vars"][hv]
    nh = math.ceil(es / ratio)
    while nh * ratio < es:
        nh += 1
    nh = min(seed["vars"][hv]["ceiling"], max(H["value"], nh))
    if nh != H["value"]:
        recs.append({"var": hv, "old": H["value"], "new": nh, "decision": "clamp", "why": "invariant"})
        H.update(prev=H["value"], value=nh, changed=now)
    return nh


def enforce_invariants(seed, live, now=None):
    """soft <= ratio x hard when both sides are set: raise the hard side within its ceiling, else
    lower the soft side. Frozen sides are not moved; an unset hard side is never set. A user-set
    soft.prompt.<type> is never lowered: only while hard.prompt is set and supported, hard.prompt is
    raised within its ceiling for it, else the pair holds. Mutates live; returns the history records."""
    recs = []
    for sv, hv, ratio in _pairs(seed):
        S, H = live["vars"][sv], live["vars"][hv]
        es, eh = _eff(S), _eff(H)
        if es is None or eh is None or es <= ratio * eh:
            continue
        if H["frozen"] is None:
            eh = _raise_hard(seed, live, hv, es, ratio, recs, now)
        if es > ratio * eh and S["frozen"] is None:
            ns = math.floor(ratio * eh)
            while ns > ratio * eh:
                ns -= 1
            ns = max(ns, seed["vars"][sv]["floor"])
            recs.append({"var": sv, "old": S["value"], "new": ns, "decision": "clamp", "why": "invariant"})
            S.update(prev=S["value"], value=ns, changed=now)
    H, ratio = live["vars"].get("hard.prompt"), PAIR_RATIO["soft.prompt"]
    for sv in sorted(v for v in seed["vars"] if v.startswith("soft.prompt.")):
        es, eh = _eff(live["vars"][sv]), _eff(H) if H else None
        if es is None or eh is None or H["status"] != "supported" or es <= ratio * eh:
            continue
        if H["frozen"] is None:
            eh = _raise_hard(seed, live, "hard.prompt", es, ratio, recs, now)
        if es > ratio * eh:                     # hard.prompt at its ceiling or frozen: hold both
            recs.append({"var": sv, "old": live["vars"][sv]["value"], "new": live["vars"][sv]["value"],
                         "decision": "hold", "why": "invariant: hard.prompt cannot rise"})
    return recs


def _shadow_record(srec, block):
    return {"var": srec["var"], "method": "bayes-shadow", "old": srec["old"], "would": srec["new"],
            "decision": srec["decision"], "applied": False, "T": srec["T"], "pi90": srec["pi90"],
            "risk": srec["risk"], "p_hit_c": srec["p_hit_c"], "fit_id": srec["fit_id"], "tier": block["tier"]}


def apply_proposals(seed, live, props, sid=None, now=None, *, bayes=None, mode=None):
    """(new live, history records, changes): the section 4 rules over every variable when the
    proposals carry a new evidence_id; otherwise the live document unchanged. Pure.
    bayes: bayes_context() (None: no Bayes block anywhere); mode: off | shadow | on (default
    bayes_mode()). Per variable the block is chosen by A.6 (choose_block); a family that acts live
    (acts_live: mode on and in BAYES_LIVE) is decided by decide_bayes, every other by decide(), and,
    when a block exists and mode is not off, decide_bayes also runs on a copy of the state and its
    result is logged as a `bayes-shadow` record (applied false) that changes nothing (S1)."""
    if not props or not live or props.get("evidence_id") == live.get("evidence_id"):
        return live, [], []
    mode = bayes_mode() if mode is None else mode
    if mode == "off":
        bayes = None
    now = time.time() if now is None else now
    new = dict(live)
    new["vars"] = {v: _copy_state(s) for v, s in live["vars"].items()}
    new.update(version=int(live["version"]) + 1, evidence_id=props["evidence_id"], updated=iso(now))
    pool_of = _pool_of(seed)
    recs = []
    order = sorted(seed["vars"], key=lambda v: (seed["vars"][v]["kind"] != "soft", v))
    for v in order:
        fam, t = split_var(v)
        pool = props["pools"].get(f"{fam}:{pool_of[t]}") if t and t in pool_of else None
        soft_ref = _eff(new["vars"]["soft.agent." + t]) if fam == "hard.agent" and \
            "soft.agent." + t in new["vars"] else None
        cur, ent = new["vars"][v], props["vars"].get(v)
        blk, tier = choose_block(v, bayes, props)
        live_bayes = blk is not None and acts_live(fam, tier, mode)
        if live_bayes:
            try:
                st, rec = decide_bayes(v, seed["vars"][v], cur, blk, ent, pool, soft_ref, now)
            except Exception as exc:  # noqa: BLE001 - a bad block costs its Bayes decision, never the apply
                log(f"bayes {v} skipped, section 4 decides: {type(exc).__name__}")
                live_bayes, blk = False, None
            else:
                if rec:
                    rec["method"] = "bayes-" + tier
                    st.update(method=rec["method"], bayes=blk)
        if not live_bayes:
            st, rec = decide(v, seed["vars"][v], cur, ent, pool, soft_ref, now)
            if rec:
                rec["method"] = "empirical"
                st.update(method="empirical", bayes=None)
            if blk is not None:
                try:
                    _sst, srec = decide_bayes(v, seed["vars"][v], _copy_state(cur), blk, ent, pool, soft_ref, now)
                except Exception as exc:  # noqa: BLE001 - the shadow never affects the live decision
                    log(f"bayes-shadow {v} skipped: {type(exc).__name__}")
                    srec = None
                if srec:
                    if rec:                              # the last block a decision used (shadow too)
                        st["bayes"] = blk
                    rec = [rec, _shadow_record(srec, blk)] if rec else [_shadow_record(srec, blk)]
        new["vars"][v] = st
        if isinstance(rec, list):
            recs.extend(r for r in rec if r)
        elif rec:
            recs.append(rec)
    inv = enforce_invariants(seed, new, now)
    for r in inv:
        r["method"] = "empirical"
    recs += inv
    for r in recs:
        r.update(ts=round(now, 3), session=sid, live_version=new["version"])
    return new, recs, [r for r in recs if r.get("method") != "bayes-shadow" and r["new"] != r["old"]]


# ---------------------------------------------------------------- live.json
def live_from_seed(seed, now=None, version=1):
    return {"schema_version": LIVE_SCHEMA, "version": version, "updated": iso(now), "seed_sha": seed["sha"],
            "evidence_id": None, "vars": {v: _var_state(s["seed"]) for v, s in seed["vars"].items()}}


def _norm_value(x, spec, what):
    if x is None:
        return None
    if not _isnum(x):
        raise LiveInvalid(f"{what} is not a number")
    return int(_clamp(round(x), spec["floor"], spec["ceiling"]))


def validate_live(doc, seed):
    """A current-schema live document normalized against the seed (values clamped to the seed's
    bounds, new variables added, retired ones dropped); LiveInvalid otherwise."""
    if not isinstance(doc, dict) or doc.get("schema_version") != LIVE_SCHEMA:
        raise LiveInvalid("schema")
    V, ver = doc.get("vars"), doc.get("version")
    if not isinstance(V, dict) or not isinstance(ver, int) or isinstance(ver, bool) or ver < 0:
        raise LiveInvalid("structure")
    for k in V:
        if is_fixed_guard(k):
            raise LiveInvalid(f"fixed guard {k}")
    eid = doc.get("evidence_id")
    if eid is not None and (not isinstance(eid, str) or not HEX64_RE.match(eid)):
        raise LiveInvalid("evidence_id")
    out = {}
    for v, spec in seed["vars"].items():
        st = V.get(v)
        if st is None:
            out[v] = _var_state(spec["seed"])
            continue
        if not isinstance(st, dict) or "value" not in st:
            raise LiveInvalid(f"{v}: not a variable")
        s = _var_state(_norm_value(st["value"], spec, v))
        s["frozen"] = _norm_value(st.get("frozen"), spec, v + ".frozen")
        s["prev"] = _norm_value(st.get("prev"), spec, v + ".prev") if _isnum(st.get("prev")) else None
        d = st.get("d", 1.0)
        s["d"] = min(D_LEVELS, key=lambda lv: abs(lv - d)) if _isnum(d) else 1.0
        h = st.get("hold", 0)
        s["hold"] = h if isinstance(h, int) and not isinstance(h, bool) and h >= -1 else 0
        up = st.get("upto", 0)
        s["upto"] = up if _isnum(up) and 0 <= up < TS_MAX else 0
        s["status"] = st.get("status") if st.get("status") in STATUSES else "unset"
        for k in ("n", "agents", "streak"):
            x = st.get(k, 0)
            s[k] = x if isinstance(x, int) and not isinstance(x, bool) and x >= 0 else 0
        ci = st.get("ci")
        s["ci"] = list(ci) if isinstance(ci, list) and len(ci) == 2 and all(c is None or _isnum(c) for c in ci) \
            else [None, None]
        s["hmax"] = st.get("hmax") if _isnum(st.get("hmax")) else None
        s["changed"] = st.get("changed") if _isnum(st.get("changed")) else None
        rec = st.get("recent")
        s["recent"] = [{"dec": str(r.get("dec"))[:12], "sign": r.get("sign") if r.get("sign") in (-1, 0, 1) else 0,
                        "rel": r.get("rel") if _isnum(r.get("rel")) else None}
                       for r in (rec if isinstance(rec, list) else []) if isinstance(r, dict)][-RECENT:]
        s["bayes"] = _valid_block(st.get("bayes"), spec["unit"]) if st.get("bayes") is not None else None
        s["method"] = st.get("method") if st.get("method") in LIVE_METHODS else None
        out[v] = s
    return {"schema_version": LIVE_SCHEMA, "version": ver, "updated": doc.get("updated") if isinstance(
        doc.get("updated"), str) else None, "seed_sha": seed["sha"], "evidence_id": eid, "vars": out}


def _migrate_0(doc, seed):
    """Schema 0 (pre-release): {"version": N, "values": {var: number|null}}."""
    vals = doc.get("values")
    if not isinstance(vals, dict):
        raise LiveInvalid("schema 0 without values")
    for k in vals:
        if is_fixed_guard(k):
            raise LiveInvalid(f"fixed guard {k}")
    ver = doc.get("version")
    live = live_from_seed(seed, version=ver if isinstance(ver, int) and not isinstance(ver, bool) and ver >= 1 else 1)
    for v, x in vals.items():
        if v in live["vars"]:
            if x is not None and not _isnum(x):
                raise LiveInvalid(f"{v} is not a number")
            st = live["vars"][v]
            if x != st["value"]:                 # not the seed's: learned or set, so never re-seeded
                st["recent"] = [{"dec": "migrated", "sign": 0, "rel": None}]
            st["value"] = x
    return live


def _migrate_1(doc, seed):
    """Schema 1 -> 2 (docs/BAYES.md 2.4): every state gains `bayes` and `method`, both null; the
    learned values and the rest of the state are kept as they are (validate_live then normalizes)."""
    V = doc.get("vars")
    if not isinstance(V, dict):
        raise LiveInvalid("schema 1 without vars")
    out = dict(doc, schema_version=2)
    out["vars"] = {k: (dict(st, bayes=None, method=None) if isinstance(st, dict) else st) for k, st in V.items()}
    return out


MIGRATIONS = {0: _migrate_0, 1: _migrate_1}


def _schema_of(doc):
    if not isinstance(doc, dict):
        return None
    sv = doc.get("schema_version", 0)
    return sv if isinstance(sv, int) and not isinstance(sv, bool) and sv >= 0 else None


def _migrate(doc, sv, seed):
    while sv < LIVE_SCHEMA:
        fn = MIGRATIONS.get(sv)
        if fn is None:
            raise LiveInvalid(f"no migration from schema {sv}")
        doc = fn(doc, seed)
        sv = doc["schema_version"]
    return doc


def read_live(seed):
    """(live, reason) without the lock and without writing: reason is None, "absent", "newer",
    "invalid" or "unreadable" (live None for every reason but None and an in-memory migration)."""
    try:
        with open(_p("live.json"), "rb") as fh:
            raw = fh.read()
    except FileNotFoundError:
        return None, "absent"
    except OSError:
        return None, "unreadable"
    try:
        doc = json.loads(raw.decode("utf-8"))
        sv = _schema_of(doc)
        if sv is None:
            return None, "invalid"
        if sv > LIVE_SCHEMA:
            return None, "newer"
        return validate_live(_migrate(doc, sv, seed) if sv < LIVE_SCHEMA else doc, seed), None
    except (ValueError, LiveInvalid, RecursionError):     # json's C decoder raises RecursionError on deep nesting
        return None, "invalid"


def _write_live(live):
    _write_atomic(_p("live.json"), _dumps(live).encode("utf-8"), fsync=True)


def _aside(path, stem):
    base = os.path.join(os.path.dirname(path), f"{stem}-{int(time.time())}")
    dest, k = base + ".json", 1
    while os.path.exists(dest):
        dest, k = f"{base}-{k}.json", k + 1
    os.replace(path, dest)
    return dest


def load_live_locked(seed, now=None):
    """Under limits.lock: (live, note). Absent -> created from the seed; older schema -> copied to
    live.v<N>.json and migrated; invalid -> set aside as live.invalid-<ts>.json and reseeded;
    newer -> left untouched, (None, "newer") (the snapshot uses the seed). Logs each case once."""
    path = _p("live.json")
    try:
        with open(path, "rb") as fh:
            raw = fh.read()
    except FileNotFoundError:
        live = live_from_seed(seed, now)
        _write_live(live)
        _history_append([{"ts": round(time.time(), 3), "var": "*", "decision": "seeded",
                          "live_version": live["version"], "old": None, "new": None}])
        return live, "created"
    except OSError as exc:
        log(f"live.json unreadable ({type(exc).__name__}); seed values")
        return None, "unreadable"
    why, doc, sv = None, None, None
    try:
        doc = json.loads(raw.decode("utf-8"))
        sv = _schema_of(doc)
        if sv is None:
            why = "no schema_version"
    except ValueError:
        why = "not JSON"
    if why is None and sv > LIVE_SCHEMA:
        log(f"live.json has schema {sv} > {LIVE_SCHEMA} (a newer stack?): left untouched, seed values used")
        return None, "newer"
    migrated = False
    if why is None and sv < LIVE_SCHEMA:
        keep = _p(f"live.v{sv}.json")
        if os.path.exists(keep):
            keep = _p(f"live.v{sv}-{int(time.time())}.json")
        _write_atomic(keep, raw)
        try:
            doc = _migrate(doc, sv, seed)
            migrated = True
        except LiveInvalid as exc:
            why = f"migration from schema {sv} failed: {exc}"
    if why is None:
        try:
            live = validate_live(doc, seed)
        except LiveInvalid as exc:
            why = str(exc)
    if why is not None:
        dest = _aside(path, "live.invalid")
        live = live_from_seed(seed, now)
        _write_live(live)
        log(f"live.json invalid ({why}): moved to {os.path.basename(dest)}, reseeded")
        _history_append([{"ts": round(time.time(), 3), "var": "*", "decision": "seeded", "why": "invalid",
                          "live_version": live["version"], "old": None, "new": None}])
        return live, "reseeded"
    if migrated:
        _write_live(live)
        log(f"live.json migrated from schema {sv} to {LIVE_SCHEMA} (copy kept)")
        return live, "migrated"
    return live, None


def pristine(st):
    """True for a variable nothing has touched since it was seeded: no evidence, decision, rollback
    or value change, and not frozen or held now. Only such a value is still the seed's."""
    return (st["status"] == "unset" and st["n"] == 0 and st["agents"] == 0 and st["frozen"] is None
            and st["hold"] == 0 and st["changed"] is None and st["prev"] is None and not st["recent"]
            and st["d"] == 1.0 and st["streak"] == 0)


def reseed_pristine(seed, live, now=None):
    """A shipped seed value that changed reaches the pristine variables (pristine()); a learned,
    frozen, held or rolled-back value is kept. Mutates live (the variable stays pristine, so a later
    seed change reaches it too); returns the history records, invariant clamps included."""
    recs = []
    for v, spec in seed["vars"].items():
        st = live["vars"][v]
        if not pristine(st) or st["value"] == spec["seed"]:
            continue
        trial = dict(live)
        trial["vars"] = {k: _copy_state(x) for k, x in live["vars"].items()}
        trial["vars"][v]["value"] = spec["seed"]
        if any(not pristine(live["vars"][r["var"]]) for r in enforce_invariants(seed, trial, now)
               if r["new"] != r["old"]):
            continue                    # soft <= ratio x hard would move a learned or frozen partner
        recs.append({"var": v, "old": st["value"], "new": spec["seed"], "decision": "reseeded",
                     "why": "seed changed, variable unlearned"})
        st["value"] = spec["seed"]
    if recs:
        recs += enforce_invariants(seed, live, now)
    return recs


def _bounds_notes(raw, seed):
    """The stored values of a current-schema live document that the seed's [floor, ceiling] moves
    when read (validate_live clamps value and frozen; a seed whose bounds moved past them): one
    "var X -> Y" each; a frozen one names the env override that keeps it (env is not bounded)."""
    V = raw.get("vars") if isinstance(raw, dict) and raw.get("schema_version") == LIVE_SCHEMA else None
    out = []
    for v, spec in sorted(seed["vars"].items()) if isinstance(V, dict) else ():
        st = V.get(v)
        for key in ("value", "frozen") if isinstance(st, dict) else ():
            x = st.get(key)
            if not _isnum(x) or spec["floor"] <= round(x) <= spec["ceiling"]:
                continue
            u, y = spec["unit"], int(_clamp(round(x), spec["floor"], spec["ceiling"]))
            if key == "value":
                out.append("{} {} -> {}".format(v, fmt(x, u), fmt(y, u)))
            else:
                out.append("{} frozen {} -> {} (to keep it: {}={} in settings.json env)".format(
                    v, fmt(x, u), fmt(y, u), env_var(v), int(round(x))))
    return out


def seed():
    """`stack_limits.py seed` (install.sh): create live.json only if absent, migrate an older
    schema after copying it to live.v<N>.json, and re-seed the pristine variables whose shipped seed
    changed (reseed_pristine); a learned, frozen or user-set value is never rewritten, but one the
    seed's new [floor, ceiling] no longer holds is read at that bound, and the outcome names it
    (_bounds_notes). Returns the outcome."""
    s = load_seed()
    _mkdirs()
    now = time.time()
    with Lock(_p("limits.lock"), wait=CMD_LOCK_WAIT_S) as lk:
        if not lk.ok:
            return "busy"
        try:
            with open(_p("live.json"), "rb") as fh:
                raw = json.loads(fh.read().decode("utf-8"))
        except (OSError, ValueError, RecursionError):
            raw = None
        live, note = load_live_locked(s, now)
        if live is None:
            return note
        bounds = _bounds_notes(raw, s) if note is None else []
        tail = "; read at the seed's bounds: " + ", ".join(bounds) if bounds else ""
        new = dict(live)
        new["vars"] = {v: _copy_state(x) for v, x in live["vars"].items()}
        recs = reseed_pristine(s, new, now)
        if not recs:
            return (note or "present") + tail
        new.update(version=live["version"] + 1, updated=iso(now))
        for r in recs:
            r.update(ts=round(now, 3), session=None, live_version=new["version"])
        _write_live(new)
        _history_append(recs)
        moved = ", ".join("{} {} -> {}".format(r["var"], fmt(r["old"], s["vars"][r["var"]]["unit"]),
                                               fmt(r["new"], s["vars"][r["var"]]["unit"])) for r in recs)
        return "{}reseeded from the new seed: {}; live v{}{}".format(note + "; " if note else "", moved,
                                                                    new["version"], tail)


# ---------------------------------------------------------------- snapshots
def _model_source():
    """(bytes, "candidate"|"shipped") of the scheduler model a new snapshot copies: the refit's
    candidate (state sched_model.json) when well-formed, else the shipped one; (None, None)."""
    for path, label in ((candidate_model_path(), "candidate"), (SHIPPED_MODEL, "shipped")):
        try:
            with open(path, "rb") as fh:
                data = fh.read(16 << 20)
            doc = json.loads(data.decode("utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(doc, dict) and isinstance(doc.get("types"), dict) and doc["types"]:
            return data, label
    return None, None


def _stack_hash_of(data):
    try:
        v = json.loads(data.decode("utf-8")).get("stack_hash")
    except (ValueError, AttributeError):
        return None
    return v if isinstance(v, str) else None


def regime_of(stack_hash, policy, scale):
    """First 16 hex of sha256 over (sched_model stack_hash, sched_policy, STACK_SOFT_LIMIT_SCALE)."""
    canon = json.dumps([stack_hash or "", policy, f"{float(scale):g}"], separators=(",", ":"))
    return hashlib.sha256(canon.encode("utf-8")).hexdigest()[:16]


def current_regime():
    data, _ = _model_source()
    return regime_of(_stack_hash_of(data) if data else None, sched_policy(), soft_scale())


def _stack_commit():
    base = os.environ.get("CLAUDE_CONFIG_DIR") or os.path.expanduser("~/.claude")
    try:
        with open(os.path.join(base, ".stack-manifest.json"), "rb") as fh:
            v = json.loads(fh.read(8 << 20).decode("utf-8")).get("commit")
    except (OSError, ValueError, AttributeError):
        return ""
    return v if isinstance(v, str) and COMMIT_RE.match(v) else ""


def snap_hash(doc):
    rest = {k: v for k, v in doc.items() if k != "hash"}
    return "sha256:" + hashlib.sha256(_dumps(rest).encode("utf-8")).hexdigest()


def read_snapshot(sid):
    """(doc, "ok") for a snapshot whose schema, session id and hash check; else (None, state) with
    state "missing", "unreadable" or "tamper"."""
    p = snapshot_path(sid)
    try:
        with open(p, "rb") as fh:
            raw = fh.read(4 << 20)
    except FileNotFoundError:
        return None, "missing"
    except OSError:
        return None, "unreadable"
    try:
        doc = json.loads(raw.decode("utf-8"))
        ok = isinstance(doc, dict) and doc.get("schema_version") == SCHEMA and doc.get("session_id") == sid \
            and isinstance(doc.get("values"), dict) and isinstance(doc.get("origin"), dict) \
            and doc.get("hash") == snap_hash(doc)          # snap_hash raises ValueError on NaN (allow_nan=False)
    except (ValueError, RecursionError):
        return None, "tamper"
    if not ok:
        return None, "tamper"
    return doc, "ok"


_ENV_WARNED = set()


def env_override(var):
    """(present, value) of a variable's env override: digits only, 0 = off (None)."""
    name = env_var(var)
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return False, None
    raw = raw.strip()
    if not re.match(r"^[0-9]{1,13}$", raw):
        if name not in _ENV_WARNED:
            _ENV_WARNED.add(name)
            log(f"{name}={raw[:40]!r} is not a whole number >= 0; ignored")
        return False, None
    n = int(raw)
    return True, (None if n == 0 else n)


def fallback_values(seed):
    """(values, origin) for a session without a usable snapshot (session_limits' fallback, the
    guard's no-session branch): the seed values, origin "fallback", except a hard.* variable whose
    env override is a cap below the seed (or the seed leaves it off): that value, origin "env". On
    this path an env value can only lower a hard cap, never raise it or turn it off (the user,
    2026-10-08); every other variable keeps its seed whatever the env says."""
    values = {v: x["seed"] for v, x in seed["vars"].items()}
    origin = {v: "fallback" for v in seed["vars"]}
    for v, x in seed["vars"].items():
        if x["kind"] != "hard" or not v.startswith("hard."):
            continue
        present, ov = env_override(v)
        if present and ov is not None and (x["seed"] is None or ov < x["seed"]):
            values[v], origin[v] = ov, "env"
    return values, origin


def snapshot_values(seed, live, auto, fallback=False):
    """(values, origin): env override > frozen > live; the seed when auto is off ("seed") or live
    is absent ("seed") or unusable ("fallback")."""
    values, origin = {}, {}
    for v, spec in seed["vars"].items():
        present, ov = env_override(v)
        if present:
            values[v], origin[v] = ov, "env"
        elif not auto or live is None:
            values[v], origin[v] = spec["seed"], ("fallback" if auto and fallback else "seed")
        else:
            st = live["vars"][v]
            if st["frozen"] is not None:
                values[v], origin[v] = st["frozen"], "frozen"
            else:
                values[v], origin[v] = st["value"], "live"
    return values, origin


def _write_snapshot(sid, src, seed, live, values, origin, auto, now=None, prov=None):
    """Create snapshots/<sid>.json (0444, O_EXCL semantics) with the copied scheduler model beside
    it. A lost race returns the winner's verified document (or None when it fails its check).
    prov: the Bayes provenance (section 2.5; default: the mode and no variable), hashed with the rest."""
    _mkdirs()
    data, label = _model_source()
    model = {"file": None, "sha": None, "stack_hash": None, "source": None}
    if data is not None:
        mname = sid + ".sched_model.json"
        mp = os.path.join(snapshots_dir(), mname)
        if not _create_excl(mp, data, 0o444):
            try:
                with open(mp, "rb") as fh:
                    data = fh.read(16 << 20)
                label = "existing"
            except OSError:
                data = None
        if data is not None:
            model = {"file": mname, "sha": _sha(data), "stack_hash": _stack_hash_of(data), "source": label}
    policy, scale = sched_policy(), soft_scale()
    doc = {"schema_version": SCHEMA, "session_id": sid, "created": iso(now), "source_event": src,
           "stack_version": CODE_VERSION, "stack_commit": _stack_commit(), "seed_sha": seed["sha"],
           "live_version": live["version"] if live else None,
           "live_sha": _sha(_dumps(live).encode("utf-8")) if live else None,
           "auto": bool(auto), "collect": collect_on(), "scale": scale, "sched_policy": policy,
           "regime": regime_of(model["stack_hash"], policy, scale),
           "values": values, "origin": origin, "sched_model": model,
           "prov": prov if prov is not None else {"bayes_mode": bayes_mode(), "fit_id": None, "vars": {}}}
    doc["hash"] = snap_hash(doc)
    p = snapshot_path(sid)
    if _create_excl(p, _dumps(doc).encode("utf-8"), 0o444):
        return p, doc
    return p, read_snapshot(sid)[0]


def _touch_snapshot(sid, doc):
    """Refresh the mtime of a session's snapshot and its scheduler model copy (the prune's clock)."""
    names = [sid + ".json"]
    m = (doc or {}).get("sched_model") or {}
    if isinstance(m.get("file"), str) and m["file"] == sid + ".sched_model.json":
        names.append(m["file"])
    for name in names:
        try:
            os.utime(os.path.join(snapshots_dir(), name))
        except OSError:
            pass


def _prune_snapshots(keep=None, now=None):
    """Snapshots (and their model copies) idle for SNAP_KEEP_S: neither the snapshot (touched at every
    SessionStart of its session) nor the guard's session folder state_root()/<sid> changed since. A
    session that is still running keeps its values (U4)."""
    cutoff = (time.time() if now is None else now) - SNAP_KEEP_S
    try:
        names = os.listdir(snapshots_dir())
    except OSError:
        return 0
    n = 0
    for name in names:
        if name.endswith(".sched_model.json"):
            sid = name[:-len(".sched_model.json")]
        elif name.endswith(".json"):
            sid = name[:-len(".json")]
        else:
            continue
        if sid == keep:
            continue
        p = os.path.join(snapshots_dir(), name)
        try:
            if os.lstat(p).st_mtime >= cutoff:
                continue
        except OSError:
            continue
        try:
            if ID_RE.match(sid) and os.stat(os.path.join(state_root(), sid)).st_mtime >= cutoff:
                continue                       # the guard still writes this session's state
        except OSError:
            pass
        try:
            os.unlink(p)
            n += 1
        except OSError:
            pass
    return n


def ensure_snapshot(sid, src="ensure"):
    """A consumer that finds no snapshot for `sid`: write one without applying (live as it is, the
    seed when auto is off or live is unusable). Returns the snapshot path (an existing file, even
    one that fails its check, is never replaced)."""
    p = snapshot_path(sid)
    if os.path.exists(p):
        return p
    s = load_seed()
    auto = auto_on()
    live, why = read_live(s) if auto else (None, None)
    values, origin = snapshot_values(s, live, auto, fallback=auto and live is None and why != "absent")
    return _write_snapshot(sid, src, s, live, values, origin, auto)[0]


def snapshot_view(doc):
    """session_limits' answer for a verified snapshot document (read_snapshot's "ok"). Reads only."""
    m = doc.get("sched_model")
    m = m if isinstance(m, dict) else {}
    mp = None
    if isinstance(m.get("file"), str) and m["file"]:
        cand = os.path.join(snapshots_dir(), m["file"])
        try:
            with open(cand, "rb") as fh:
                mp = cand if _sha(fh.read(16 << 20)) == m.get("sha") else None
        except OSError:
            mp = None
    return {"state": "ok", "values": doc["values"], "origin": doc["origin"], "snap": doc["hash"][7:23],
            "regime": doc.get("regime"), "scale": doc.get("scale"), "sched_policy": doc.get("sched_policy"),
            "sched_model": mp, "live_version": doc.get("live_version")}


def session_limits(sid, sdir=None):
    """The values every consumer uses for `sid`: the verified snapshot (ensure_snapshot when
    missing), else the seed (fallback_values: a hard.* env override only lowers it) with one stderr
    line per session (O_EXCL marker <sdir>/limits-tamper)."""
    doc, state = read_snapshot(sid)
    if state == "missing":
        try:
            ensure_snapshot(sid)
        except (OSError, SeedError):
            pass
        doc, state = read_snapshot(sid)
    if state == "ok":
        return snapshot_view(doc)
    s = load_seed()
    sdir = sdir or os.path.join(state_root(), sid)
    try:
        os.makedirs(sdir, mode=0o700, exist_ok=True)
        os.close(os.open(os.path.join(sdir, "limits-tamper"), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600))
        sys.stderr.write(f"stack_limits: the limits snapshot of session {sid} is {state}; seed values in use\n")
        log(f"snapshot of {sid} {state}; seed values")
    except OSError:
        pass
    values, origin = fallback_values(s)
    return {"state": state, "values": values,
            "origin": origin, "snap": None, "regime": None, "scale": soft_scale(),
            "sched_policy": sched_policy(), "sched_model": None, "live_version": None}


# ---------------------------------------------------------------- SessionStart
def _short(var):
    fam, t = split_var(var)
    return {"turns": "%s.turns", "soft.agent": "%s.soft", "hard.agent": "%s.hard",
            "soft.prompt": "%s.prompt"}[fam] % t if t \
        else "{}.{}".format(fam.split(".")[1], fam.split(".")[0])


def fmt(v, unit="ctx"):
    if v is None:
        return "off"
    if unit == "turns":
        return str(int(v))
    if v >= 1e9:
        return "%.3gB" % (v / 1e9)
    if v >= 1e6:
        return "%.3gM" % (v / 1e6)
    return f"{round(v / 1e3)}k"


def _notice(seed, live, changes, notes):
    tail = " — stack_limits.py show"
    if not changes and not notes:
        return None
    parts = list(notes)
    if changes:
        items = []
        # own evidence before pooled values, larger relative moves first
        for r in sorted(changes, key=lambda r: (r.get("status") == "pooled",
                                                -abs((r["new"] or 0) - (r["old"] or 0)) / float(r["old"] or 1))):
            u = seed["vars"][r["var"]]["unit"]
            it = "{} {}→{}".format(_short(r["var"]), fmt(r["old"], u), fmt(r["new"], u))
            if r.get("why") != "invariant" and r.get("n"):
                ci = r.get("ci") or [None, None]
                it += " (n={}".format(r["n"])
                if r.get("p90") is not None:
                    it += ", p90 {}".format(fmt(r["p90"], u))
                if ci[0] is not None:
                    it += f" [{fmt(ci[0], u)}–{fmt(ci[1], u)}]"
                if r.get("ft") is not None:
                    it += ", ft {}%".format(round(100 * r["ft"]))
                it += ")"
            items.append(it)
        head = "limits v{}: ".format(live["version"])
        held = sum(1 for s in live["vars"].values() if s["hold"])
        extra = f" · held {held}" if held else ""
        body, shown = "", 0
        for it in items:
            cand = (body + "; " if body else "") + it
            more = len(items) - shown - 1
            if len(head + cand + (f" · +{more}" if more else "") + extra + tail) > NOTICE_MAX:
                break
            body, shown = cand, shown + 1
        if shown < len(items):
            body += f" · +{len(items) - shown}"
        parts.append(head + body + extra)
    return ("; ".join(parts) + tail)[:NOTICE_MAX]


def snapshot_prov(seed, mode, bctx, props, values, recs):
    """The snapshot's `prov` (section 2.5): every variable with an accepted block (choose_block),
    its method (bayes-nuts / bayes-grid when it acts live, else bayes-shadow), T, pi90, risk,
    p_hit at the session's value, and `would`: this apply's shadow value when it differs from it."""
    out = {"bayes_mode": mode, "fit_id": (bctx or {}).get("fit_id") if mode != "off" else None, "vars": {}}
    if mode == "off" or not bctx:
        return out
    would = {r["var"]: r["would"] for r in recs if r.get("method") == "bayes-shadow"}
    for v in sorted(seed["vars"]):
        blk, tier = choose_block(v, bctx, props)
        if blk is None:
            continue
        fam = split_var(v)[0]
        x = values.get(v)
        w = would.get(v)
        out["vars"][v] = {"method": "bayes-" + tier if acts_live(fam, tier, mode) else "bayes-shadow",
                          "T": blk["T"], "pi90": list(blk["pi90"]), "risk": blk["risk"],
                          "p_hit": round(p_hit(blk["qtab"], x), 6) if _isnum(x) else None,
                          "would": w if w is not None and w != x else None}
    return out


def _apply_and_snapshot(ev, spawn=True, now=None):
    t0 = time.monotonic()
    sid = ev.get("session_id") if isinstance(ev, dict) else None
    if not isinstance(sid, str) or not ID_RE.match(sid):
        return None, None
    src = ev.get("source") if ev.get("source") in SOURCES else "unknown"
    path = snapshot_path(sid)
    mode = bayes_mode()
    doc, state = read_snapshot(sid)
    if state == "ok":                                    # resume / compact / clear: the same values
        _touch_snapshot(sid, doc)                        # a live session's snapshot is never pruned
        return path, None
    if state != "missing":
        log(f"snapshot of {sid} {state} (not replaced)")
        return path, f"limits: this session's snapshot is {state}; seed values in use — stack_limits.py status"
    s = load_seed()
    auto = auto_on()
    live, note, notes, changes = None, None, [], []
    props, bctx, recs = None, None, []
    if auto:
        _mkdirs()
        with Lock(_p("limits.lock"), wait=LOCK_WAIT_S) as lk:
            if lk.ok:
                live, note = load_live_locked(s, now)
                if live is not None:
                    props, why = load_proposals(s)
                    if why:
                        log(f"proposals.json ignored: {why}")
                    if props and mode != "off":           # off: bayes.json is not read at all
                        bctx = bayes_context(s, props)
                    if props and props["evidence_id"] != live.get("evidence_id"):
                        if time.monotonic() - t0 > DEADLINE_S:
                            notes.append("limits: deadline passed, v{} kept without apply".format(live["version"]))
                        else:
                            live, recs, changes = apply_proposals(s, live, props, sid, now, bayes=bctx, mode=mode)
                            _write_live(live)
                            _history_append(recs)
                            _prune_snapshots(keep=sid, now=now)
        if not lk.ok:
            live, why = read_live(s)
            note = why if live is None else None
            notes.append("limits: limits.lock busy, snapshot of live v{} without apply".format(
                live["version"] if live else "-"))
        if note == "reseeded":
            notes.append("limits: live.json was invalid, set aside and reseeded")
        elif note in ("newer", "unreadable", "invalid"):
            what = "has a newer schema" if note == "newer" else "is " + note
            notes.append(f"limits: live.json {what}; seed values in use")
    values, origin = snapshot_values(s, live, auto, fallback=auto and live is None and note != "absent")
    try:
        prov = snapshot_prov(s, mode, bctx, props, values, recs)
    except Exception as exc:  # noqa: BLE001 - provenance is a report: never the reason a snapshot fails
        log(f"prov not built: {type(exc).__name__}")
        prov = {"bayes_mode": mode, "fit_id": None, "vars": {}}
    path, _ = _write_snapshot(sid, src, s, live, values, origin, auto, now, prov)
    if spawn:
        try:
            maybe_spawn_propose()
        except Exception as exc:  # noqa: BLE001 - step 6 is best effort
            log(f"propose not started: {type(exc).__name__}")
    return path, _notice(s, live, changes, notes)


def apply_and_snapshot(ev, spawn=True, now=None):
    """SessionStart (design section 3, steps 1-4, 6, 7): (snapshot path, notice or None). The only
    place a limit changes (U4). Never raises: an error leaves a seed snapshot when it can."""
    try:
        return _apply_and_snapshot(ev, spawn, now)
    except Exception as exc:  # noqa: BLE001 - a hook must not fail on this
        log(f"apply_and_snapshot failed: {type(exc).__name__}: {exc}")
        sid = ev.get("session_id") if isinstance(ev, dict) else None
        path = None
        try:
            if isinstance(sid, str) and ID_RE.match(sid) and not os.path.exists(snapshot_path(sid)):
                s = load_seed()
                values, origin = snapshot_values(s, None, auto_on(), fallback=True)
                path = _write_snapshot(sid, "error", s, None, values, origin, auto_on(), now)[0]
            elif isinstance(sid, str) and ID_RE.match(sid):
                path = snapshot_path(sid)
        except Exception:  # noqa: BLE001 - nothing more to try
            path = None
        return path, f"limits: error ({type(exc).__name__}); seed values in use — stack_limits.py status"


# ---------------------------------------------------------------- user commands
def _select(seed, pattern, all_):
    import fnmatch
    if all_:
        return sorted(seed["vars"])
    if not pattern:
        raise CmdError("name a variable (or a pattern) or use --all")
    names = sorted(v for v in seed["vars"] if fnmatch.fnmatchcase(v, pattern))
    if not names:
        raise CmdError(f"no variable matches {pattern!r} (stack_limits.py show)")
    return names


def mutate(fn):
    """Run fn(seed, live, now) -> history records under limits.lock; write live (version + 1) and
    history when it changed something. Effective from the next snapshot (U4)."""
    s = load_seed()
    _mkdirs()
    now = time.time()
    with Lock(_p("limits.lock"), wait=CMD_LOCK_WAIT_S) as lk:
        if not lk.ok:
            raise CmdError("limits.lock is busy; try again")
        live, note = load_live_locked(s, now)
        if live is None:
            raise CmdError(f"live.json is unusable ({note}); see limits.log")
        new = dict(live)
        new["vars"] = {v: _copy_state(x) for v, x in live["vars"].items()}
        recs = fn(s, new, now)
        if not recs:
            return live, []
        recs += enforce_invariants(s, new, now)
        new.update(version=live["version"] + 1, updated=iso(now))
        for r in recs:
            r.update(ts=round(now, 3), session=None, live_version=new["version"])
        _write_live(new)
        _history_append(recs)
        return new, recs


def cmd_hold(pattern=None, all_=False, sessions=-1):
    def fn(s, live, now):
        out = []
        for v in _select(s, pattern, all_):
            st = live["vars"][v]
            if st["hold"] != sessions:
                out.append({"var": v, "old": st["value"], "new": st["value"], "decision": "hold",
                            "cmd": "hold" if sessions else "release", "hold": sessions})
                st["hold"] = sessions
        return out
    return mutate(fn)


def cmd_freeze(pattern=None, all_=False, value=None, unfreeze=False):
    def fn(s, live, now):
        out = []
        for v in _select(s, pattern, all_):
            st, spec = live["vars"][v], s["vars"][v]
            if unfreeze:
                new = None
            elif value is not None:
                if not spec["floor"] <= value <= spec["ceiling"]:
                    raise CmdError("{}: {} is outside [{}, {}]".format(v, value, spec["floor"], spec["ceiling"]))
                new = int(value)
            else:
                new = st["value"]
                if new is None:
                    if not all_:
                        raise CmdError(f"{v} is unset; give --value")
                    continue
            if st["frozen"] != new:
                out.append({"var": v, "old": st["value"], "new": st["value"], "decision": "frozen",
                            "cmd": "unfreeze" if unfreeze else "freeze", "frozen": new})
                st["frozen"] = new
        return out
    return mutate(fn)


def cmd_rollback(pattern=None, all_=False, to="prev"):
    if to not in ("prev", "seed"):
        raise CmdError("--to prev|seed")

    def fn(s, live, now):
        out = []
        for v in _select(s, pattern, all_):
            st, spec = live["vars"][v], s["vars"][v]
            new = spec["seed"] if to == "seed" else (st["prev"] if st["changed"] is not None else st["value"])
            out.append({"var": v, "old": st["value"], "new": new, "decision": "rollback", "to": to})
            if new != st["value"]:
                st.update(prev=st["value"], value=new, changed=now)
            st.update(hold=1, d=0.5, streak=0)
        return out
    return mutate(fn)


def dry_run():
    """`apply --dry-run`: what the next SessionStart would change with the current proposals."""
    s = load_seed()
    live = read_live(s)[0] or live_from_seed(s)
    props, pwhy = load_proposals(s)
    if not props:
        return ["no usable proposals.json (%s)" % (pwhy or "absent")]
    if props["evidence_id"] == live.get("evidence_id"):
        return ["proposals {} already applied in live v{}: nothing would change".format(
            props["evidence_id"][:12], live["version"])]
    mode = bayes_mode()
    bctx = bayes_context(s, props) if mode != "off" else None
    new, recs, changes = apply_proposals(s, live, props, bayes=bctx, mode=mode)
    shadow = [r for r in recs if r.get("method") == "bayes-shadow"]
    out = ["live v{} -> v{} with proposals {} ({} decisions, {} changes; bayes {}, {} shadow)".format(
        live["version"], new["version"], props["evidence_id"][:12], len(recs) - len(shadow), len(changes), mode,
        len(shadow))]
    for r in recs:
        u = s["vars"][r["var"]]["unit"]
        if r.get("method") == "bayes-shadow":
            out.append("  {:<40} {:<8} would {} -> {}  T {} [{}-{}] p_hit {}".format(
                r["var"], r["decision"][:16], fmt(r["old"], u), fmt(r["would"], u), fmt(r["T"], u),
                fmt(r["pi90"][0], u), fmt(r["pi90"][1], u), "-" if r["p_hit_c"] is None else "%.3g" % r["p_hit_c"]))
            continue
        n = "  n={}".format(r["n"]) if r.get("n") else ""
        out.append("  {:<40} {:<8} {} -> {}{}".format(r["var"], r["decision"], fmt(r["old"], u), fmt(r["new"], u), n))
    return out


def _latest_snapshot(sid=None):
    if sid:
        return read_snapshot(sid)[0]
    d = snapshots_dir()
    try:
        names = [n for n in os.listdir(d) if n.endswith(".json") and not n.endswith(".sched_model.json")
                 and ID_RE.match(n[:-len(".json")])]       # another name made read_snapshot raise ValueError
    except OSError:
        return None

    def mtime(n):
        try:
            return os.path.getmtime(os.path.join(d, n))
        except OSError:                                    # pruned since listdir (_prune_snapshots)
            return -1.0
    names.sort(key=mtime, reverse=True)
    for n in names[:5]:
        doc = read_snapshot(n[:-len(".json")])[0]
        if doc:
            return doc
    return None


def show(pattern=None, as_json=False, sid=None):
    import fnmatch
    s = load_seed()
    live, why = read_live(s)
    snap = _latest_snapshot(sid)
    prov = (snap or {}).get("prov") if isinstance((snap or {}).get("prov"), dict) else {}
    pv = prov.get("vars") if isinstance(prov.get("vars"), dict) else {}
    rows = {}
    for v in sorted(s["vars"]):
        if pattern and not fnmatch.fnmatchcase(v, pattern):
            continue
        spec = s["vars"][v]
        st = (live or {}).get("vars", {}).get(v) or _var_state(spec["seed"])
        val = _eff(st)
        drift = (val - spec["seed"]) / float(spec["seed"]) if val is not None and spec["seed"] else None
        rows[v] = {"seed": spec["seed"], "live": st["value"], "frozen": st["frozen"], "hold": st["hold"],
                   "drift": drift, "status": st["status"], "n": st["n"], "ci": st["ci"], "d": st["d"],
                   "stable": stable(st), "floor": spec["floor"], "ceiling": spec["ceiling"],
                   "snapshot": (snap or {}).get("values", {}).get(v),
                   "origin": (snap or {}).get("origin", {}).get(v), "env": env_var(v),
                   "method": st.get("method"), "bayes": _bayes_view(st.get("bayes"), val, pv.get(v))}
    head = {"live_version": live["version"] if live else None, "live": why or "ok",
            "evidence_id": (live or {}).get("evidence_id"), "snapshot": (snap or {}).get("session_id"),
            "auto": auto_on(), "bayes_mode": bayes_mode(), "fit_id": prov.get("fit_id")}
    if as_json:
        return json.dumps(dict(head, vars=rows), indent=1, sort_keys=True)
    out = ["limits: live v{} ({}), auto {}, snapshot {}, bayes {}{}".format(
        head["live_version"], head["live"], "on" if head["auto"] else "off", head["snapshot"], head["bayes_mode"],
        " (fit {})".format(head["fit_id"]) if head["fit_id"] else "")]
    line = "{:<36} {:>8} {:>8} {:>7} {:<11} {:>4} {:<17} {:<8} {}"
    out.append(line.format("var", "seed", "live", "drift", "status", "n", "ci (p90)", "origin", "flags"))
    for v, r in rows.items():
        u = s["vars"][v]["unit"]
        ci = r["ci"] if r["ci"][0] is not None else None
        flags = " ".join(x for x in ("hold {}".format(r["hold"]) if r["hold"] else "",
                                     "frozen {}".format(fmt(r["frozen"], u)) if r["frozen"] is not None else "",
                                     "d={:g}".format(r["d"]) if r["d"] != 1 else "", "stable" if r["stable"] else "",
                                     _bayes_flag(r, u)) if x)
        drift = "" if r["drift"] is None else "{:+.0f}%".format(100 * r["drift"])
        out.append(line.format(v, fmt(r["seed"], u), fmt(r["live"], u), drift, r["status"], r["n"],
                               f"{fmt(ci[0], u)}-{fmt(ci[1], u)}" if ci else "", r["origin"] or "", flags))
    return "\n".join(out)


def _bayes_view(blk, c, pv):
    """show's Bayes columns of one variable: the last block a decision used (live state) and this
    session's shadow would-value (snapshot prov)."""
    pv = pv if isinstance(pv, dict) else {}
    if not isinstance(blk, dict) and not pv:
        return None
    out = {"would": pv.get("would"), "prov_method": pv.get("method")}
    if isinstance(blk, dict):
        out.update(tier=blk.get("tier"), T=blk.get("T"), pi90=blk.get("pi90"), risk=blk.get("risk"),
                   p_hit=round(p_hit(blk["qtab"], c), 4) if _isnum(c) else None, fit_id=blk.get("fit_id"))
    else:
        out.update(T=pv.get("T"), pi90=pv.get("pi90"), risk=pv.get("risk"), p_hit=pv.get("p_hit"))
    return out


def _bayes_flag(r, u):
    b = r.get("bayes")
    if not b:
        return "method {}".format(r["method"]) if r.get("method") not in (None, "empirical") else ""
    pi = b.get("pi90") or [None, None]
    txt = "{} T {} [{}-{}]".format(b.get("prov_method") or r.get("method") or "bayes", fmt(b.get("T"), u),
                                   fmt(pi[0], u), fmt(pi[1], u))
    if b.get("p_hit") is not None:
        txt += " p_hit {:.3g}".format(b["p_hit"])
    if b.get("would") is not None:
        txt += " would {}".format(fmt(b["would"], u))
    return txt


def history(pattern=None, limit=50):
    import fnmatch
    out = []
    for p in (_p("history.1.jsonl"), _p("history.jsonl")):
        try:
            with open(p, encoding="utf-8") as fh:
                for line in fh:
                    try:
                        r = json.loads(line)
                    except ValueError:
                        continue
                    if isinstance(r, dict) and (not pattern or fnmatch.fnmatchcase(str(r.get("var")), pattern)):
                        out.append(r)
        except OSError:
            pass
    return out[-limit:] if limit else out


def stability_lines():
    s = load_seed()
    live, why = read_live(s)
    if not live:
        return [f"no live.json ({why})"]
    out = []
    for v in sorted(s["vars"]):
        st = live["vars"][v]
        if st["status"] == "unset" and not st["recent"]:
            continue
        out.append("{:<36} {:<11} d={:<5g} {}  recent: {}{}".format(
            v, st["status"], st["d"], "stable" if stable(st) else "moving", " ".join(r["dec"] for r in st["recent"]),
            "  method: " + st["method"] if st.get("method") else ""))
    return out or ["no variable has evidence yet"]


def status_line():
    try:
        s = load_seed()
    except SeedError as exc:
        return f"limits: {exc}"
    live, why = read_live(s)
    auto = "on" if auto_on() else "off (STACK_LIMITS_AUTO=0)"
    try:
        snaps = sum(1 for n in os.listdir(snapshots_dir()) if not n.endswith(".sched_model.json"))
    except OSError:
        snaps = 0
    props, pwhy = load_proposals(s)
    if props:
        pend = "applied" if live and props["evidence_id"] == live.get("evidence_id") else "pending"
        pp = "proposals {} ({}, {})".format(props.get("generated"), props["evidence_id"][:8], pend)
    else:
        pp = "no proposals" + (f" ({pwhy})" if pwhy else "")
    if not live:
        return f"limits: no usable live.json ({why}); seed values; {pp}; auto {auto}; {snaps} snapshots"
    st = [x["status"] for x in live["vars"].values()]
    held = sum(1 for x in live["vars"].values() if x["hold"])
    frozen = sum(1 for x in live["vars"].values() if x["frozen"] is not None)
    nb = sum(1 for x in live["vars"].values() if x.get("bayes"))
    return ("limits: live v{} ({}), {} vars: {} supported, {} pooled, {} provisional; held {}, frozen {}; "
            "{}; auto {}; bayes {} ({} with a block); {} snapshots".format(
                live["version"], live.get("updated"), len(st), st.count("supported"), st.count("pooled"),
                st.count("provisional"), held, frozen, pp, auto, bayes_mode(), nb, snaps))


def main(argv):
    import argparse
    ap = argparse.ArgumentParser(prog="stack_limits.py", description="learned limits (see the module docstring)")
    sub = ap.add_subparsers(dest="cmd")
    p = sub.add_parser("show")
    p.add_argument("pattern", nargs="?")
    p.add_argument("--json", action="store_true")
    p.add_argument("--session")
    p = sub.add_parser("history")
    p.add_argument("var", nargs="?")
    p.add_argument("--limit", type=int, default=50)
    sub.add_parser("stability")
    for name in ("hold", "release", "freeze", "unfreeze", "rollback"):
        p = sub.add_parser(name)
        p.add_argument("var", nargs="?")
        p.add_argument("--all", action="store_true")
        if name == "hold":
            p.add_argument("--sessions", type=int, default=-1)
        if name == "freeze":
            p.add_argument("--value", type=int)
        if name == "rollback":
            p.add_argument("--to", choices=("prev", "seed"), required=True)
    p = sub.add_parser("propose")
    p.add_argument("--quiet", action="store_true")
    p.add_argument("--csv", action="append")
    p.add_argument("--out")
    p = sub.add_parser("apply")
    p.add_argument("--dry-run", action="store_true")
    sub.add_parser("seed")
    sub.add_parser("status")
    a = ap.parse_args(argv)
    try:
        if a.cmd == "show":
            print(show(a.pattern, a.json, a.session))
        elif a.cmd == "history":
            for r in history(a.var, a.limit):
                print(json.dumps(r, sort_keys=True))
        elif a.cmd == "stability":
            print("\n".join(stability_lines()))
        elif a.cmd in ("hold", "release"):
            if a.cmd == "hold" and (a.sessions == 0 or a.sessions < -1):
                raise CmdError("--sessions N needs N >= 1")
            live, recs = cmd_hold(a.var, a.all, a.sessions if a.cmd == "hold" else 0)
            print("{}: {} variables; live v{} (from the next session)".format(a.cmd, len(recs), live["version"]))
        elif a.cmd in ("freeze", "unfreeze"):
            live, recs = cmd_freeze(a.var, a.all, getattr(a, "value", None), unfreeze=a.cmd == "unfreeze")
            print("{}: {} variables; live v{} (from the next session)".format(a.cmd, len(recs), live["version"]))
        elif a.cmd == "rollback":
            live, recs = cmd_rollback(a.var, a.all, a.to)
            print("rollback --to {}: {} variables, held 1; live v{} (from the next session)".format(
                a.to, len(recs), live["version"]))
        elif a.cmd == "propose":
            doc = propose(paths=a.csv, out=a.out)
            if not a.quiet:
                print("no proposals (collection off or another proposer runs)" if doc is None else
                      "proposals: {} rows ({} dropped, {} skipped: another model than the frontmatter's), "
                      "{} variables with evidence, evidence {}".format(
                          doc["rows"], doc["dropped"], doc["model_mismatch"], len(doc["vars"]),
                          doc["evidence_id"][:12]))
        elif a.cmd == "apply":
            if not a.dry_run:
                raise CmdError("values change only at SessionStart (one swap per session); use --dry-run")
            print("\n".join(dry_run()))
        elif a.cmd == "seed":
            print(f"limits seed: {seed()}")
        elif a.cmd == "status":
            print(status_line())
        else:
            ap.print_help()
            return 2
    except (CmdError, SeedError) as exc:
        sys.stderr.write(f"stack_limits.py: {exc}\n")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
