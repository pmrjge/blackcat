"""eq_policy - the rules of the runtime Equilibrium, shared by the guard (eq_guard.py), the executor
(bin/stack-eq -> eq_cli.py) and the sandboxed check runner (bin/stack-eq-check), so all three judge one
header, one argv and one path the same way (the toolsmith_policy.py pattern).

Pure and stdlib-only (Python 3.13) except for file READS (params, manifest, JSON records) and
write_json_atomic (the one writer helper the contract asks for). What is here
(docs-design/RUNTIME_EQUILIBRIUM.md; contracts.md section 3):
  - the class table (CLASSES, KIND, MEMBER_TOOLS, WORKDIR, FALLBACK, PREDICTED_NEUTRAL, MEMBER_TYPES);
  - the leader's header grammar (parse_header) and the member/reconcile tokens;
  - the knobs (knobs: invalid values fail closed to the stricter value);
  - the calibration pin (load_params: eqparams.v1 schema, sha256 against the manifest) and the run
    bundle (resolve: caps clamps, override/manual labels, fallbacks, consent_required per spec 8.3);
  - the executor's argv grammar (parse_cli, parse_check_cli, ticket_name) and consent tokens;
  - the Level 1 check trailer (CHECK_TRAILER, parse_check_trailer);
  - the eq member predicates the guard calls: member_git_allowed, member_path_denied;
  - plan-time path checks: settings_denied (sandbox denyRead + Read() deny rules + protected paths).
"""
import base64
import fnmatch
import hashlib
import json
import math
import os
import re
import shlex
import stat
import sys
import time
import unicodedata

SCHEMA_PARAMS = "eqparams.v1"
SCHEMA_PLAN = "eqplan.v1"
SCHEMA_BRIEF = "eqbrief.v1"

CLASSES = ("PF", "CP", "CR", "RS", "ES", "DS", "OE")
KIND = {"PF": "checkable", "CP": "checkable", "CR": "finding_set", "RS": "discrete", "ES": "numeric",
        "DS": "long_form", "OE": "long_form"}
# spec 2.3 "eq member tool use": the harness's per-class allowed_tools (equilibrium/harness/eq_harness.py
# DEFAULT_FLAGS: PF and CP _BUILD, CR read + Bash, RS read, ES Read, DS/OE none) + Skill (amendment A4).
# The calibration validates exactly these lists, so they win over the spec row's shorthand for PF.
_READ = ("Read", "Glob", "Grep")
_BUILD = ("Read", "Glob", "Grep", "Edit", "Write", "Bash")
MEMBER_TOOLS = {"PF": _BUILD + ("Skill",), "CP": _BUILD + ("Skill",), "CR": _READ + ("Bash", "Skill"),
                "RS": _READ + ("Skill",), "ES": ("Read", "Skill"), "DS": ("Skill",), "OE": ("Skill",)}
# CP/CR: Agent isolation "worktree"; the others get <project>/.claude-work/eq/<R>/m<i>/ when their
# segments are files (workdir()), else nothing
WORKDIR = {"PF": "dir", "CP": "worktree", "CR": "worktree", "RS": "dir", "ES": "dir", "DS": "dir", "OE": "dir"}
# the pre-registered view scheme per class (equilibrium/harness/flags.json `view`)
VIEW = {"PF": "lens", "CP": "perm", "CR": "kcover", "RS": "kcover", "ES": "perm", "DS": "perm", "OE": "perm"}
# the a-priori S* type per class (PROPOSAL.md:125-131; flags.json s_star)
S_STAR = {"PF": "mathematician", "CP": "python-engineer", "CR": "code-reviewer", "RS": "researcher",
          "ES": "data-scientist", "DS": "planner", "OE": "writer"}
PREDICTED_NEUTRAL = frozenset(("RS", "DS", "OE"))
# spec 2.3: POLICY["equilibrium"] = the S* candidates, the judge and verifier types, and the language
# engineers (agent_guard._LANG)
_LANG = ("rust-engineer", "haskell-engineer", "julia-engineer", "go-engineer", "python-engineer",
         "jvm-engineer", "node-engineer")
MEMBER_TYPES = tuple(dict.fromkeys(("mathematician", "proof-checker", "python-engineer", "main-coder", "coder",
                                    "code-reviewer", "security-auditor", "researcher", "oracle",
                                    "data-scientist", "planner", "writer", "verifier", "plan-reviewer")
                                   + _LANG))
TAU_DEFAULT = 0.6
T_DEFAULT = 2
# spec 7.7: conservative fallbacks for unvalidated runs
FALLBACK = {"N": 5, "rounds": 1, "loo_view": "rotation", "view": dict(VIEW), "reducer": "R0",
            "member_type": dict(S_STAR), "member_model": None, "member_model_id": None,
            "tau": TAU_DEFAULT, "t": T_DEFAULT, "certainty": None, "w3": "auto"}
# per-member caps when params give none and the stack's seed has no entry for the type (stack-budget's
# seed values for builder types, 2026-10-02: soft 19M ctx, 170 turns); the CLI passes the type's seed
FALLBACK_MEMBER_CAPS = {"member_tokens": 19_000_000, "member_turns": 170}
VIEWS = ("lens", "perm", "kcover")
LOO_VIEWS = ("none", "rotation", "random", "leader")
REDUCERS = ("R0", "R1", "R2", "R3", "ENS")
STATUSES = ("validated", "not_established", "not_run", "refuted")
STATUS_REASONS = ("no_calibration", "class_not_validated", "model_drift", "n_or_rounds_capped", "override",
                  "manual")
HARD_MAX_N = 9
HARD_MAX_ROUNDS = 2

TICKET_TTL_S = 120
CHECK_TIMEOUT_S = 600
TAIL_BYTES = 65536
CHECK_TRAILER = "EQCHECK "

RUN_RE = re.compile(r"[0-9a-f]{8}\Z")
SESSION_RE = re.compile(r"[A-Za-z0-9_-]{1,128}\Z")
HEX64_RE = re.compile(r"[0-9a-f]{64}\Z")
MODEL_ID_RE = re.compile(r"[a-z0-9][a-z0-9._-]{2,99}\Z")
TYPE_RE = re.compile(r"[a-z][a-z0-9-]{1,40}\Z")
member_token_re = re.compile(r"eq ([0-9a-f]{8}) m([1-9])/([1-9])\Z")
reconcile_token_re = re.compile(r"eq ([0-9a-f]{8}) r([0-9]) m([1-9])\Z")
CONSENT_RE = re.compile(r"(?<![A-Za-z0-9])(Run|Remove) eq:([0-9a-f]{8})(?![0-9A-Za-z])")

HEADER_KEYS = ("eq-run", "eq-class", "eq-mode", "eq-type", "eq-check", "eq-segments")
MAX_PROBLEM_CHARS = 200_000
MAX_HEADER_LINE = 4096
MAX_SEGMENTS = 64
MAX_CHECK_WORDS = 64

CLI_SUBCOMMANDS = ("plan", "start", "prepare-check", "check-container", "reduce", "view", "result", "cleanup",
                   "status", "help")
ROUND_SUBS = ("prepare-check", "check-container", "reduce", "view")
HELP_ALIASES = ("-h", "--help")

# home-relative paths no eq read or mount may touch (equilibrium harness HOME_SECRETS + the stack's own)
HOME_SECRETS = (".ssh", ".aws", ".config", ".gnupg", ".docker", ".claude", ".claude.json", ".kube", ".local",
                "Library", ".netrc", ".git-credentials", ".npmrc", ".pypirc", ".cache")


class PolicyError(ValueError):
    """A header, argv, params file or path the runtime refuses; str() is the reason."""


# ---------------------------------------------------------------- header
def _clean_line(v, what):
    if any(ch in v for ch in "\0\r") or len(v) > MAX_HEADER_LINE:
        raise PolicyError("%s: control characters or longer than %d characters" % (what, MAX_HEADER_LINE))
    return v.strip()


def parse_header(text):
    """The leader's brief as a dict: run (or None), class, mode, type, check (argv list or None),
    segments (list), problem. Raises PolicyError on anything else (fail closed: an unknown key, a
    duplicate, a missing `---`, an empty problem)."""
    if not isinstance(text, str):
        raise PolicyError("the brief is not text")
    lines = text.split("\n")
    seen, k = {}, 0
    while k < len(lines):
        raw = lines[k].rstrip("\r")
        k += 1
        if raw.strip() == "---":
            break
        if not raw.strip():
            raise PolicyError("blank line inside the eq header (the header ends at a line `---`)")
        m = re.match(r"\s*(eq-[a-z]+):\s?(.*)\Z", raw, re.S)
        if not m or m.group(1) not in HEADER_KEYS:
            raise PolicyError("not an eq header line: %r (keys: %s, then `---`)" % (raw[:60], ", ".join(HEADER_KEYS)))
        key = m.group(1)
        if key in seen:
            raise PolicyError("duplicate header key %s" % key)
        seen[key] = _clean_line(m.group(2), key)
    else:
        raise PolicyError("no `---` line after the eq header")
    problem = "\n".join(lines[k:])
    if not problem.strip():
        raise PolicyError("empty problem after `---`")
    if len(problem) > MAX_PROBLEM_CHARS or "\0" in problem:
        raise PolicyError("problem longer than %d characters or holds NUL" % MAX_PROBLEM_CHARS)
    run = seen.get("eq-run")
    if run is not None and not RUN_RE.match(run):
        raise PolicyError("eq-run must be 8 lower-case hex characters")
    cls = seen.get("eq-class")
    if cls not in CLASSES:
        raise PolicyError("eq-class must be one of %s" % ", ".join(CLASSES))
    mode = seen.get("eq-mode")
    if mode not in ("auto", "manual"):
        raise PolicyError("eq-mode must be auto or manual")
    etype = seen.get("eq-type") or None
    if etype is not None and etype not in MEMBER_TYPES:
        raise PolicyError("eq-type %r is not an equilibrium member type (%s)" % (etype[:40], ", ".join(MEMBER_TYPES)))
    check = None
    if "eq-check" in seen:
        try:
            check = shlex.split(seen["eq-check"], comments=False, posix=True)
        except ValueError as exc:
            raise PolicyError("eq-check: %s" % exc) from None
        if not check or len(check) > MAX_CHECK_WORDS or any(not w or "\n" in w or "\0" in w for w in check):
            raise PolicyError("eq-check: 1-%d non-empty argv words" % MAX_CHECK_WORDS)
    segments = []
    if "eq-segments" in seen:
        segments = [s.strip() for s in seen["eq-segments"].split("|")]
        if not segments or len(segments) > MAX_SEGMENTS or any(not s for s in segments):
            raise PolicyError("eq-segments: 1-%d non-empty paths separated by |" % MAX_SEGMENTS)
        if len(set(segments)) != len(segments):
            raise PolicyError("eq-segments: a path is listed twice")
    return {"run": run, "class": cls, "mode": mode, "type": etype, "check": check, "segments": segments,
            "problem": problem}


def workdir(cls, segments):
    """`worktree` (CP/CR), `dir` (the others when they have file segments; PF always), else `none`."""
    w = WORKDIR[cls]
    if w == "dir" and cls != "PF" and not segments:
        return "none"
    return w


# ---------------------------------------------------------------- knobs
def _int_knob(environ, name, default, lo, hi, strict):
    """An integer knob: unset -> default; above hi -> hi (a hard cap the user may only lower); below lo,
    non-numeric or garbage -> `strict` (fail closed). Returns (value, error or None)."""
    raw = environ.get(name)
    if raw is None or raw.strip() == "":
        return default, None
    s = raw.strip()
    if not re.fullmatch(r"[0-9]{1,6}", s):
        return strict, "%s=%r is not a whole number: %s used" % (name, raw[:20], strict)
    v = int(s)
    if v < lo:
        return strict, "%s=%d below %d: %s used" % (name, v, lo, strict)
    if v > hi:
        return hi, "%s=%d above the hard cap %d: %d used" % (name, v, hi, hi)
    return v, None


def knobs(environ):
    """The STACK_EQ_* knobs (spec 8.1). Invalid values fail closed to the stricter value: STACK_EQ off,
    caps at their minimum, CONFIRM always, WALL required; values above a hard cap are clamped to it.
    STACK_EQ_N / STACK_EQ_ROUNDS are user overrides (None when unset; an invalid one counts as set, at
    its strictest value, so the run is labelled `override`). `errors` lists every correction."""
    errors = []

    def take(pair):
        if pair[1]:
            errors.append(pair[1])
        return pair[0]

    raw_eq = (environ.get("STACK_EQ") or "").strip()
    if raw_eq in ("", "1"):
        on = raw_eq != "0"
    elif raw_eq == "0":
        on = False
    else:
        on = False
        errors.append("STACK_EQ=%r is not 0 or 1: off" % raw_eq[:20])
    k = {"STACK_EQ": 1 if on else 0}
    k["STACK_EQ_MAX_N"] = take(_int_knob(environ, "STACK_EQ_MAX_N", HARD_MAX_N, 1, HARD_MAX_N, 1))
    k["STACK_EQ_MAX_ROUNDS"] = take(_int_knob(environ, "STACK_EQ_MAX_ROUNDS", HARD_MAX_ROUNDS, 0, HARD_MAX_ROUNDS, 0))
    # at most 12 live runs: 128 session slots / 10 per run (spec 2.3); the default stays 1
    k["STACK_EQ_MAX_CONCURRENT_RUNS"] = take(_int_knob(environ, "STACK_EQ_MAX_CONCURRENT_RUNS", 1, 1, 12, 1))
    k["STACK_EQ_SESSION_RUNS"] = take(_int_knob(environ, "STACK_EQ_SESSION_RUNS", 3, 0, 1000, 0))
    for name, cap, lo in (("STACK_EQ_N", k["STACK_EQ_MAX_N"], 1), ("STACK_EQ_ROUNDS", k["STACK_EQ_MAX_ROUNDS"], 0)):
        raw = environ.get(name)
        if raw is None or raw.strip() == "":
            k[name] = None
        else:
            k[name] = take(_int_knob(environ, name, None, lo, cap, lo))
    conf = (environ.get("STACK_EQ_CONFIRM") or "always").strip()
    if conf not in ("always", "over-cap"):
        errors.append("STACK_EQ_CONFIRM=%r: always used" % conf[:20])
        conf = "always"
    k["STACK_EQ_CONFIRM"] = conf
    wall = (environ.get("STACK_EQ_WALL") or "auto").strip()
    if wall not in ("auto", "sandbox", "required"):
        errors.append("STACK_EQ_WALL=%r: required used" % wall[:20])
        wall = "required"
    k["STACK_EQ_WALL"] = wall
    k["errors"] = errors
    return k


# ---------------------------------------------------------------- params (the calibration pin)
CLASS_KEYS = ("status", "member_type", "member_model_id", "agent_file_sha256", "N", "rounds", "view", "loo_view",
              "reducer", "tau", "t", "caps", "usd_per_mtok", "cost_ratio", "effect", "certainty", "pool")
TOP_KEYS = ("schema", "version", "created_utc", "provenance", "classes")
CAPS_KEYS = ("member_tokens", "member_turns", "run_tokens")
PARAMS_MAX_BYTES = 1 << 20


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def _is_num(v):
    return (isinstance(v, (int, float)) and not isinstance(v, bool)) and math.isfinite(v)


def _check_field(key, v):
    """None when value v is valid for class key `key` (v is not None), else the reason."""
    if key == "status":
        return None if v in STATUSES else "status must be one of %s" % ", ".join(STATUSES)
    if key == "member_type":
        return None if v in MEMBER_TYPES else "member_type %r is not an equilibrium member type" % (v,)
    if key == "member_model_id":
        return None if isinstance(v, str) and MODEL_ID_RE.match(v) else "member_model_id is not a model id"
    if key == "agent_file_sha256":
        return None if isinstance(v, str) and HEX64_RE.match(v) else "agent_file_sha256 is not 64 hex"
    if key == "N":
        return None if _is_int(v) and 1 <= v <= HARD_MAX_N else "N must be an integer 1-%d" % HARD_MAX_N
    if key == "rounds":
        return None if _is_int(v) and 0 <= v <= HARD_MAX_ROUNDS else "rounds must be 0-%d" % HARD_MAX_ROUNDS
    if key == "view":
        return None if v in VIEWS else "view must be one of %s" % ", ".join(VIEWS)
    if key == "loo_view":
        return None if v in LOO_VIEWS else "loo_view must be one of %s" % ", ".join(LOO_VIEWS)
    if key == "reducer":
        return None if v in REDUCERS else "reducer must be one of %s" % ", ".join(REDUCERS)
    if key == "tau":
        return None if _is_num(v) and 0 < v <= 1 else "tau must be in (0, 1]"
    if key == "t":
        return None if _is_int(v) and v >= 1 else "t must be an integer >= 1"
    if key == "caps":
        if not isinstance(v, dict) or set(v) != set(CAPS_KEYS):
            return "caps must hold exactly %s" % ", ".join(CAPS_KEYS)
        if not all(_is_int(v[c]) and v[c] > 0 for c in CAPS_KEYS):
            return "caps values must be positive integers"
        return None
    if key == "usd_per_mtok":
        return None if _is_num(v) and v >= 0 else "usd_per_mtok must be a number >= 0"
    if key == "cost_ratio":
        if not isinstance(v, dict) or not _is_num(v.get("median")) or not (
                isinstance(v.get("ci95"), list) and len(v["ci95"]) == 2 and all(_is_num(x) for x in v["ci95"])):
            return "cost_ratio must be {median, ci95: [lo, hi]}"
        return None
    if key in ("effect", "certainty"):
        return None if isinstance(v, dict) else "%s must be an object" % key
    if key == "pool":
        if not isinstance(v, dict) or not isinstance(v.get("name"), str) or not (
                isinstance(v.get("sha256"), str) and HEX64_RE.match(v["sha256"])) or not isinstance(
                v.get("description"), str):
            return "pool must be {name, sha256 (64 hex), description}"
        return None
    return "unknown key %s" % key


def validate_params(obj):
    """The reasons an object is not a valid eqparams.v1 file (empty list = valid). Top level exactly
    {schema, version, created_utc, provenance, classes{PF..OE}}; every class entry has every spec 7.5
    key; all but `status` may be null unless status == validated, then all non-null but `certainty`."""
    errs = []
    if not isinstance(obj, dict):
        return ["params is not a JSON object"]
    if set(obj) != set(TOP_KEYS):
        errs.append("top-level keys must be exactly %s" % ", ".join(TOP_KEYS))
    if obj.get("schema") != SCHEMA_PARAMS:
        errs.append("schema must be %s" % SCHEMA_PARAMS)
    ver = obj.get("version")
    if not _is_int(ver):
        errs.append("version must be an integer >= 1 (0 only for the all-not_run placeholder)")
    elif ver == 0:
        cl = obj.get("classes")
        if not (isinstance(cl, dict) and cl and all(
                isinstance(e, dict) and e.get("status") == "not_run" for e in cl.values())):
            errs.append("version 0 is the all-not_run placeholder: every class status must be not_run")
    elif ver < 1:
        errs.append("version must be an integer >= 1 (0 only for the all-not_run placeholder)")
    if not isinstance(obj.get("created_utc"), str):
        errs.append("created_utc must be a string")
    if not isinstance(obj.get("provenance"), dict):
        errs.append("provenance must be an object")
    classes = obj.get("classes")
    if not isinstance(classes, dict) or set(classes) != set(CLASSES):
        errs.append("classes must hold exactly %s" % ", ".join(CLASSES))
        return errs
    for cls in CLASSES:
        e = classes[cls]
        if not isinstance(e, dict) or set(e) != set(CLASS_KEYS):
            errs.append("%s: keys must be exactly %s" % (cls, ", ".join(CLASS_KEYS)))
            continue
        if e["status"] is None:
            errs.append("%s: status is required" % cls)
            continue
        for key in CLASS_KEYS:
            v = e[key]
            if v is None:
                if e["status"] == "validated" and key != "certainty":
                    errs.append("%s: %s is null in a validated entry" % (cls, key))
                continue
            why = _check_field(key, v)
            if why:
                errs.append("%s: %s" % (cls, why))
    return errs


def read_bytes_nofollow(path, limit):
    """A regular file's bytes, opened with O_NOFOLLOW (a symlink is refused), at most `limit` bytes;
    raises OSError / PolicyError."""
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise PolicyError("%s is not a regular file" % path)
        chunks, size = [], 0
        while True:
            b = os.read(fd, 65536)
            if not b:
                break
            chunks.append(b)
            size += len(b)
            if size > limit:
                raise PolicyError("%s is larger than %d bytes" % (path, limit))
        return b"".join(chunks)
    finally:
        os.close(fd)


def load_params(path, manifest_path):
    """(params, sha256, None) for a params file whose bytes hash to the manifest's
    `eq_runtime.params_sha256` and whose schema validates; else (None, sha256 or None, reason): every
    class is then treated as not_run (resolve with params None)."""
    try:
        raw = read_bytes_nofollow(path, PARAMS_MAX_BYTES)
    except (OSError, PolicyError) as exc:
        return None, None, "params unreadable (%s)" % (exc.strerror if isinstance(exc, OSError) else exc)
    sha = hashlib.sha256(raw).hexdigest()
    try:
        man = json.loads(read_bytes_nofollow(manifest_path, 16 << 20).decode("utf-8"))
    except (OSError, PolicyError, ValueError) as exc:
        return None, sha, "manifest unreadable (%s)" % type(exc).__name__
    want = (man.get("eq_runtime") or {}).get("params_sha256") if isinstance(man, dict) else None
    if not isinstance(want, str) or not HEX64_RE.match(want):
        return None, sha, "manifest has no eq_runtime.params_sha256"
    if want != sha:
        return None, sha, "params sha256 %s differs from the manifest's %s" % (sha[:12], want[:12])
    try:
        obj = json.loads(raw.decode("utf-8"))
    except ValueError:
        return None, sha, "params is not JSON"
    errs = validate_params(obj)
    if errs:
        return None, sha, "params schema: " + "; ".join(errs[:5])
    return obj, sha, None


def model_alias(model_id):
    """The family alias of a full model id (claude-opus-... -> opus), else None."""
    m = re.search(r"(opus|sonnet|haiku|fable)", model_id or "")
    return m.group(1) if m else None


def resolve(cls, params, knobs_, *, mode, eq_type=None, session_runs=0, fallback_caps=None):
    """The run bundle for class `cls` (spec 7.5-7.7, 8.3): member_type, member_model, member_model_id,
    N, rounds, view, loo_view, reducer, tau, t, caps, usd_per_mtok, validated, status_reason,
    consent_required, auto_allowed, predicted_neutral, warnings.

    validated only when the class entry is `validated` in verified params and the run uses its exact
    bundle; else status_reason is the first of no_calibration, class_not_validated, n_or_rounds_capped,
    override, manual (model_drift is applied after capture: final_label). `eq-mode: auto` is refused
    (PolicyError) unless validated. consent_required: always unless validated, auto, STACK_EQ_CONFIRM
    over-cap, not over_cap and under STACK_EQ_SESSION_RUNS. over_cap: the members' caps allow more than the
    per-run cap (N x member_tokens x (1 + rounds) > caps.run_tokens: estimate's tokens_uncapped)."""
    if cls not in CLASSES:
        raise PolicyError("unknown class %r" % (cls,))
    if mode not in ("auto", "manual"):
        raise PolicyError("mode must be auto or manual")
    k = knobs_
    if not k.get("STACK_EQ"):
        raise PolicyError("STACK_EQ=0: equilibrium runs are off")
    entry = (params or {}).get("classes", {}).get(cls) if isinstance(params, dict) else None
    warnings = list(k.get("errors") or [])
    reasons = []
    if not isinstance(entry, dict):
        reasons.append("no_calibration")
        entry = None
    elif entry.get("status") != "validated":
        reasons.append("class_not_validated")
    calibrated = entry is not None and entry.get("status") == "validated"
    if calibrated:
        b = {"member_type": entry["member_type"], "member_model_id": entry["member_model_id"],
             "N": entry["N"], "rounds": entry["rounds"], "view": entry["view"], "loo_view": entry["loo_view"],
             "reducer": entry["reducer"], "tau": entry["tau"], "t": entry["t"], "caps": dict(entry["caps"]),
             "usd_per_mtok": entry["usd_per_mtok"]}
        b["member_model"] = model_alias(b["member_model_id"])
    else:
        caps = dict(FALLBACK_MEMBER_CAPS)
        caps.update({c: v for c, v in (fallback_caps or {}).items() if c in caps and _is_int(v) and v > 0})
        b = {"member_type": FALLBACK["member_type"][cls], "member_model_id": None, "member_model": None,
             "N": FALLBACK["N"], "rounds": FALLBACK["rounds"], "view": FALLBACK["view"][cls],
             "loo_view": FALLBACK["loo_view"], "reducer": FALLBACK["reducer"], "tau": FALLBACK["tau"],
             "t": FALLBACK["t"], "caps": caps, "usd_per_mtok": None}
    if eq_type is not None and eq_type != b["member_type"]:
        if eq_type not in MEMBER_TYPES:
            raise PolicyError("eq-type %r is not an equilibrium member type" % (eq_type,))
        b["member_type"] = eq_type
        if calibrated:              # another type than the calibrated one: its model id no longer applies
            b["member_model_id"], b["member_model"] = None, None
            reasons.append("override")
    capped = False
    if b["N"] > k["STACK_EQ_MAX_N"]:
        b["N"], capped = k["STACK_EQ_MAX_N"], True
    if b["rounds"] > k["STACK_EQ_MAX_ROUNDS"]:
        b["rounds"], capped = k["STACK_EQ_MAX_ROUNDS"], True
    if capped:
        reasons.append("n_or_rounds_capped")
    if k.get("STACK_EQ_N") is not None or k.get("STACK_EQ_ROUNDS") is not None:
        if k.get("STACK_EQ_N") is not None:
            b["N"] = min(k["STACK_EQ_N"], k["STACK_EQ_MAX_N"])
        if k.get("STACK_EQ_ROUNDS") is not None:
            b["rounds"] = min(k["STACK_EQ_ROUNDS"], k["STACK_EQ_MAX_ROUNDS"])
        reasons.append("override")
    if not calibrated or capped or "override" in reasons:
        mc = b["caps"]
        if not calibrated or b["N"] != entry["N"] or b["rounds"] != entry["rounds"]:
            mc["run_tokens"] = mc["member_tokens"] * b["N"] * (1 + b["rounds"])
    validated_bundle = not reasons
    if mode == "auto" and not validated_bundle:
        raise PolicyError("eq-mode: auto needs a validated class with its exact calibrated bundle (%s); run it "
                          "manually (eq-mode: manual) or take the single-agent path" % ", ".join(reasons))
    if mode == "manual":
        reasons.append("manual")
    validated = not reasons
    est = estimate(b)
    over_cap = est["tokens_uncapped"] > b["caps"]["run_tokens"]
    if over_cap:
        warnings.append("the members' caps allow %d tokens (N x member_tokens x (1 + rounds)), above the per-run "
                        "cap %d: the run stops at the cap" % (est["tokens_uncapped"], b["caps"]["run_tokens"]))
    past_allowance = session_runs >= k["STACK_EQ_SESSION_RUNS"]
    consent = not (validated and mode == "auto" and k["STACK_EQ_CONFIRM"] == "over-cap" and not over_cap
                   and not past_allowance)
    if cls in PREDICTED_NEUTRAL:
        warnings.append("predicted neutral or worse for %s (PROPOSAL.md:133-137)" % cls)
    b.update(validated=validated, status_reason=None if validated else reasons[0], status_reasons=reasons,
             consent_required=consent, auto_allowed=validated_bundle, predicted_neutral=cls in PREDICTED_NEUTRAL,
             warnings=warnings, estimate=est, over_cap=over_cap)
    return b


def estimate(bundle):
    """Tokens and USD-equivalent of a run: worst = the per-run cap (the guard stops the run there); expected =
    round 0 only (N members at their cap; reconcile rounds run only when kappa < tau); uncapped = every member at
    its cap in every round, N x member_tokens x (1 + rounds), what the run could use without the per-run cap
    (resolve's over_cap compares it with the cap). USD only from calibrated params."""
    caps = bundle["caps"]
    worst = int(caps["run_tokens"])
    uncapped = int(caps["member_tokens"]) * int(bundle["N"]) * (1 + int(bundle.get("rounds") or 0))
    expected = min(worst, int(caps["member_tokens"]) * int(bundle["N"]))
    rate = bundle.get("usd_per_mtok")
    if _is_num(rate):
        return {"tokens_expected": expected, "tokens_worst": worst, "tokens_uncapped": uncapped,
                "usd_expected": round(expected * rate / 1e6, 2), "usd_worst": round(worst * rate / 1e6, 2),
                "usd_source": "params usd_per_mtok (calibration ledger)"}
    return {"tokens_expected": expected, "tokens_worst": worst, "tokens_uncapped": uncapped, "usd_expected": None,
            "usd_worst": None, "usd_source": "none: no calibrated USD conversion"}


def final_label(validated, status_reason, model_id, captured_models):
    """(validated, status_reason) after capture: a validated run whose members ran on another model than
    `model_id` (or whose model is unknown) becomes model_drift."""
    if not validated:
        return False, status_reason
    if not captured_models or any(m != model_id for m in captured_models):
        return False, "model_drift"
    return True, None


def w3_level(knob, level2_ok, kind):
    """`container` or `sandbox` for a run of answer kind `kind`; STACK_EQ_WALL=required refuses a
    checkable run without Level 2 (PolicyError)."""
    if knob == "sandbox":
        return "sandbox"
    if knob == "required" and kind == "checkable" and not level2_ok:
        raise PolicyError("STACK_EQ_WALL=required: Level 2 containers are not available for this checkable run")
    return "container" if level2_ok else "sandbox"


# ---------------------------------------------------------------- state layout
def state_root(environ):
    base = environ.get("XDG_STATE_HOME") or os.path.join(environ.get("HOME") or os.path.expanduser("~"),
                                                         ".local", "state")
    return os.path.join(base, "claude-agent-stack")


def safe_sid(value, default="nosession"):
    """The guard's safe(): a filesystem-safe session token."""
    s = re.sub(r"[^A-Za-z0-9_-]", "_", str(value or ""))[:128]
    return s or default


def _check_run(run):
    if not isinstance(run, str) or not RUN_RE.match(run):
        raise PolicyError("run id must be 8 lower-case hex characters")
    return run


def store_dir(environ, sid, run):
    return os.path.join(state_root(environ), safe_sid(sid), "eq", _check_run(run))


def find_run(environ, run):
    """The one store dir S/*/eq/<run> (a real directory, not a link); PolicyError on none or several."""
    _check_run(run)
    root = state_root(environ)
    try:
        names = sorted(os.listdir(root))
    except OSError:
        raise PolicyError("no eq store (%s unreadable)" % root) from None
    found = []
    for n in names:
        p = os.path.join(root, n, "eq", run)
        try:
            st_s, st_e, st = os.lstat(os.path.join(root, n)), os.lstat(os.path.join(root, n, "eq")), os.lstat(p)
        except OSError:
            continue
        if all(stat.S_ISDIR(x.st_mode) for x in (st_s, st_e, st)):
            found.append(p)
    if len(found) != 1:
        raise PolicyError("run eq:%s: %s store directories" % (run, "no" if not found else "%d" % len(found)))
    return found[0]


def project_dir(project_root, run):
    return os.path.join(project_root, ".claude-work", "eq", _check_run(run))


def ticket_dir(environ):
    return os.path.join(state_root(environ), "eq-tickets")


def ticket_name(args):
    """The guard's ticket for one stack-eq argv: sha256 of its canonical JSON."""
    blob = json.dumps(list(args), separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest() + ".json"


# ---------------------------------------------------------------- consent
def consent_token(run, kind="run"):
    _check_run(run)
    if kind == "run":
        return "Run eq:%s" % run
    if kind == "remove":
        return "Remove eq:%s" % run
    raise PolicyError("consent kind must be run or remove")


def consent_path(environ, sid, run, kind="run"):
    _check_run(run)
    if kind not in ("run", "remove"):
        raise PolicyError("consent kind must be run or remove")
    name = "%s.json" % run if kind == "run" else "%s-remove.json" % run
    return os.path.join(state_root(environ), safe_sid(sid), "eq", "consent", name)


def consent_ok(record, run, kind="run"):
    """A consent record (guard-written) that names this run's token in its answer."""
    if not isinstance(record, dict):
        return False
    tok = consent_token(run, kind)
    return (record.get("token") == tok and isinstance(record.get("answer"), str) and tok in record["answer"]
            and record.get("source") in ("ask", "file"))


# ---------------------------------------------------------------- JSON helpers
def read_json(path, limit=16 << 20):
    """A JSON file opened with O_NOFOLLOW (regular file, <= limit bytes), or None."""
    try:
        return json.loads(read_bytes_nofollow(path, limit).decode("utf-8"))
    except (OSError, PolicyError, ValueError):
        return None


def write_json_atomic(path, obj):
    """Write obj as JSON to path: a 0600 temp file beside it (O_EXCL|O_NOFOLLOW), then rename; the final
    component is never followed (rename replaces a symlink, never writes through it)."""
    d, base = os.path.split(path)
    tmp = os.path.join(d, ".%s.%d.%d.tmp" % (base, os.getpid(), time.monotonic_ns()))
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(obj, f, indent=1, sort_keys=True)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.rename(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


# ---------------------------------------------------------------- the executor's grammar
def parse_cli(args):
    """stack-eq's argv (without the program) as {"sub", "run", "round", "headless", "consent_file",
    "session", "brief_file", "args"}; PolicyError otherwise. Grammar:
        help
        plan|start|result|cleanup|status --run R
        prepare-check|check-container|reduce --run R --round r       (view: r >= 1)
        start --run R --headless --consent-file /abs/path
        plan --run R --headless --session S --brief-file /abs/path   (contracts.md 11)
    Every option once, as separate words, in any order; nothing else."""
    if not isinstance(args, (list, tuple)) or not all(isinstance(a, str) for a in args):
        raise PolicyError("argv must be a list of strings")
    args = list(args)
    if not args or args[0] in HELP_ALIASES:
        args = ["help"] + args[1:]
    sub, rest = args[0], args[1:]
    if sub not in CLI_SUBCOMMANDS:
        raise PolicyError("unknown subcommand %r: %s" % (sub[:40], ", ".join(CLI_SUBCOMMANDS)))
    p = {"sub": sub, "run": None, "round": None, "headless": False, "consent_file": None, "session": None,
         "brief_file": None, "args": list(args)}
    if sub == "help":
        if rest:
            raise PolicyError("help takes no arguments")
        return p
    k, seen = 0, set()
    while k < len(rest):
        w = rest[k]
        if w in seen:
            raise PolicyError("%s given twice" % w)
        seen.add(w)
        if w == "--run":
            if k + 1 >= len(rest) or not RUN_RE.match(rest[k + 1]):
                raise PolicyError("--run needs the run id (8 lower-case hex)")
            p["run"] = rest[k + 1]
            k += 2
        elif w == "--round" and sub in ROUND_SUBS:
            if k + 1 >= len(rest) or not re.fullmatch(r"[0-9]", rest[k + 1]):
                raise PolicyError("--round needs a round number 0-9")
            p["round"] = int(rest[k + 1])
            k += 2
        elif w == "--headless" and sub in ("start", "plan"):
            p["headless"] = True
            k += 1
        elif (w == "--consent-file" and sub == "start") or (w == "--brief-file" and sub == "plan"):
            v = rest[k + 1] if k + 1 < len(rest) else ""
            if not v.startswith("/") or len(v) > 4096 or any(ch in v for ch in "\0\n\r"):
                raise PolicyError("%s needs an absolute path" % w)
            p["consent_file" if sub == "start" else "brief_file"] = v
            k += 2
        elif w == "--session" and sub == "plan":
            v = rest[k + 1] if k + 1 < len(rest) else ""
            if not SESSION_RE.match(v):
                raise PolicyError("--session needs the session id (1-128 of A-Z a-z 0-9 _ -)")
            p["session"] = v
            k += 2
        else:
            raise PolicyError("unexpected argument %r for %s" % (w[:40], sub))
    if p["run"] is None:
        raise PolicyError("%s needs --run R" % sub)
    if sub in ROUND_SUBS and p["round"] is None:
        raise PolicyError("%s needs --round r" % sub)
    if sub == "view" and p["round"] < 1:
        raise PolicyError("view renders reconcile rounds: --round >= 1")
    if sub == "start" and p["headless"] != (p["consent_file"] is not None):
        raise PolicyError("start --headless needs --consent-file and the reverse")
    if sub == "plan" and not (p["headless"] == (p["session"] is not None) == (p["brief_file"] is not None)):
        raise PolicyError("plan --headless needs --session S and --brief-file F, and the reverse")
    return p


def headless_run(session):
    """The run id of a headless E_rt run of session S (contracts.md 11): sha256("S|headless")[:8]."""
    return hashlib.sha256(("%s|headless" % session).encode("utf-8")).hexdigest()[:8]


def parse_check_cli(args):
    """stack-eq-check's argv: exactly --run R --cand i (either order); {"run", "cand"}."""
    if not isinstance(args, (list, tuple)) or len(args) != 4 or not all(isinstance(a, str) for a in args):
        raise PolicyError("usage: stack-eq-check --run R --cand i")
    d = {}
    for k in (0, 2):
        key, val = args[k], args[k + 1]
        if key == "--run" and "run" not in d and RUN_RE.match(val):
            d["run"] = val
        elif key == "--cand" and "cand" not in d and re.fullmatch(r"[1-9]", val):
            d["cand"] = int(val)
        else:
            raise PolicyError("usage: stack-eq-check --run R --cand i (i 1-9)")
    return d


# ---------------------------------------------------------------- Level 1 check trailer
TRAILER_KEYS = ("run", "cand", "round", "exit", "timed_out", "tail_b64")


def render_check_trailer(run, cand, rnd, exit_code, timed_out, tail):
    obj = {"run": run, "cand": cand, "round": rnd, "exit": exit_code, "timed_out": bool(timed_out),
           "tail_b64": base64.b64encode(tail[-TAIL_BYTES:]).decode("ascii")}
    return CHECK_TRAILER + json.dumps(obj, separators=(",", ":"), sort_keys=True)


def parse_check_trailer(stdout):
    """The trailer dict when `stdout` is exactly one `EQCHECK {json}` line (one trailing newline
    allowed) with exactly the trailer keys and types; None otherwise (fail closed)."""
    if isinstance(stdout, bytes):
        try:
            stdout = stdout.decode("utf-8")
        except UnicodeDecodeError:
            return None
    if not isinstance(stdout, str):
        return None
    text = stdout[:-1] if stdout.endswith("\n") else stdout
    if "\n" in text or "\r" in text or not text.startswith(CHECK_TRAILER) or len(text) > 200_000:
        return None
    try:
        obj = json.loads(text[len(CHECK_TRAILER):])
    except ValueError:
        return None
    if not isinstance(obj, dict) or set(obj) != set(TRAILER_KEYS):
        return None
    if not (isinstance(obj["run"], str) and RUN_RE.match(obj["run"]) and _is_int(obj["cand"])
            and 1 <= obj["cand"] <= HARD_MAX_N and _is_int(obj["round"]) and 0 <= obj["round"] <= 9
            and (obj["exit"] is None or _is_int(obj["exit"])) and isinstance(obj["timed_out"], bool)
            and isinstance(obj["tail_b64"], str)):
        return None
    if obj["timed_out"] != (obj["exit"] is None):
        return None
    try:
        tail = base64.b64decode(obj["tail_b64"].encode("ascii"), validate=True)
    except (ValueError, UnicodeEncodeError):
        return None
    if len(tail) > TAIL_BYTES:
        return None
    return obj


# ---------------------------------------------------------------- eq members: git
_HEAD_REV = r"HEAD(?:[~^][0-9]{0,4})*"
HEAD_REV_RE = re.compile(r"%s(?:\.\.\.?%s)?\Z" % (_HEAD_REV, _HEAD_REV))
HEAD_PATH_RE = re.compile(r"%s:[^\0]*\Z" % _HEAD_REV)
GIT_GLOBAL_OK = ("--no-pager", "-P", "--no-optional-locks", "--literal-pathspecs")
GIT_READONLY = ("status", "diff", "log", "show", "ls-files")
_LOG_OPT_RE = re.compile(
    r"(?:--oneline|--stat(?:=[0-9,]+)?|--shortstat|--numstat|--summary|--name-only|--name-status|-p|-u|--patch|"
    r"--no-patch|-s|-[0-9]{1,6}|-n[0-9]{1,6}|--max-count=[0-9]{1,6}|--skip=[0-9]{1,6}|--format=[^\0]*|"
    r"--pretty(?:=[^\0]*)?|--graph|--no-decorate|--abbrev-commit|--no-abbrev-commit|--abbrev=[0-9]{1,2}|"
    r"-U[0-9]{1,4}|--unified=[0-9]{1,4}|--follow|--reverse|--date=[A-Za-z0-9:%.-]{1,40}|--no-color|"
    r"--color=never|--first-parent|--no-merges|--merges|--author=[^\0]*|--grep=[^\0]*|--since=[^\0]*|"
    r"--until=[^\0]*|--word-diff(?:=[a-z]+)?|--no-renames|-M|-C|--find-renames|-w|--ignore-all-space|"
    r"--full-history|--topo-order|--date-order|--parents|--children|--no-walk|-z|--relative-date|"
    r"--name-status|--compact-summary|--dirstat(?:=[a-z0-9,]+)?|--minimal|--histogram|--patience)\Z")
_DIFF_DENY = ("--no-index", "--output", "--ext-diff", "--textconv", "--contents")
_LSFILES_DENY = ("--with-tree",)
_STATUS_DENY = ()


def member_git_allowed(argv_words):
    """For an eq member's git command (argv words, words[0] being git or a path to it): None when it is
    allowed, else the deny reason. Allowed (spec 2.3): `status`, ref-less `diff`, `log`/`show` limited
    to HEAD (no --all/--branches/--remotes/--tags/--glob/reflogs/ref names), `ls-files`; global options
    only --no-pager/-P/--no-optional-locks/--literal-pathspecs (never -C, -c, --git-dir, --work-tree:
    they move git to a sibling's worktree or change its configuration). A non-git argv returns None."""
    words = [str(w) for w in (argv_words or [])]
    if not words or os.path.basename(words[0]) != "git":
        return None
    k = 1
    while k < len(words) and words[k].startswith("-"):
        if words[k] not in GIT_GLOBAL_OK:
            return "git option %s is refused for eq members (only %s)" % (words[k][:40], ", ".join(GIT_GLOBAL_OK))
        k += 1
    if k >= len(words):
        return "git without a subcommand is refused for eq members"
    sub, rest = words[k], words[k + 1:]
    if sub not in GIT_READONLY:
        return ("git %s is refused for eq members: only status, ref-less diff, HEAD-only log/show and ls-files "
                "(no commit, merge, stash, worktree, branch, checkout or other refs)" % sub[:40])
    after_dd = False
    j = 0
    while j < len(rest):
        w = rest[j]
        j += 1
        if after_dd:
            if "\0" in w:
                return "NUL in a git path"
            continue
        if w == "--":
            after_dd = True
            continue
        if sub == "status":
            continue
        if sub == "ls-files":
            if w.startswith("-") and any(w == d or w.startswith(d + "=") for d in _LSFILES_DENY):
                return "git ls-files %s names a tree: refused for eq members" % w[:40]
            continue
        if sub == "diff":
            if w.startswith("-"):
                if any(w == d or w.startswith(d + "=") for d in _DIFF_DENY):
                    return "git diff %s is refused for eq members (reads or writes outside the worktree)" % w[:40]
                continue
            return ("git diff %r: no ref or path before `--` (eq members compare their own worktree with its "
                    "index or HEAD only; put paths after --)" % w[:40])
        # log / show: HEAD only
        if w.startswith("-"):
            if w == "-n" and j < len(rest) and re.fullmatch(r"[0-9]{1,6}", rest[j]):
                j += 1
                continue
            if _LOG_OPT_RE.match(w):
                continue
            return "git %s %s is refused for eq members (HEAD-only history: no ref-selecting option)" % (sub, w[:40])
        if HEAD_REV_RE.match(w) or (sub == "show" and HEAD_PATH_RE.match(w)):
            continue
        return ("git %s %r: only HEAD (HEAD~n, HEAD^, HEAD:path) for eq members; put paths after --"
                % (sub, w[:40]))
    return None


# ---------------------------------------------------------------- eq members: paths
def _norm(path):
    """NFC + casefold: APFS/HFS+ resolve `.CLAUDE-WORK` and NFD names to the same file, so comparisons
    happen on this form (over-denies on a case-sensitive file system: fail closed)."""
    return unicodedata.normalize("NFC", path).casefold()


def _under(path, root):
    p, r = _norm(path), _norm(root.rstrip("/") or "/")
    return p == r or p.startswith(r + "/") or r == "/"


def _forms(path):
    """The lexical absolute form and the resolved form of a path."""
    lex = os.path.normpath(path)
    try:
        real = os.path.realpath(path)
    except (OSError, ValueError):
        real = lex
    return [lex] if real == lex else [lex, real]


def _roots(path):
    if not path:
        return []
    return list(dict.fromkeys([os.path.normpath(path), os.path.realpath(path)]))


def member_path_denied(path, *, config_dir, state_root, project_root, run, member, member_dirs=None,
                       member_worktrees=None, cwd=None, recursive=False):
    """For eq member `member` (1-based) of run `run`: None when its file tool may touch `path`, else the
    reason (spec 6.1 W1 rows). Denied, after `..` and symlinks are resolved (both the lexical and the
    real form are checked): <config>/projects/** (transcripts, tool results), state_root/** (the store,
    reports, registry), <project>/.claude-work/eq/** except the member's own m<i>/ (other members' dirs,
    check copies, patches, other runs), and every other member's worktree or work dir. `recursive`
    (Grep/Glob over a directory): also denied when the path CONTAINS one of those (a search from the
    project root would walk into them). A relative path needs `cwd`; without it it is denied."""
    if not isinstance(path, str) or not path or "\0" in path:
        return "an eq member's path must be a non-empty string"
    if not os.path.isabs(path):
        if not cwd:
            return "relative path %r without a working directory: refused for eq members" % path[:80]
        path = os.path.join(cwd, path)
    member_dirs = {str(k): v for k, v in (member_dirs or {}).items() if v}
    member_worktrees = {str(k): v for k, v in (member_worktrees or {}).items() if v}
    me = str(member)
    own = _roots(member_dirs.get(me))
    denied = []
    for root in _roots(os.path.join(config_dir, "projects")):
        denied.append((root, "Claude Code's transcripts and tool results (<config>/projects)"))
    for root in _roots(state_root):
        denied.append((root, "the stack's state (eq store, reports, registry)"))
    for root in _roots(os.path.join(project_root, ".claude-work", "eq")):
        denied.append((root, "the equilibrium work area (other members, checks, patches)"))
    for i, wt in member_worktrees.items():
        if i != me:
            denied += [(r, "member m%s's worktree" % i) for r in _roots(wt)]
    for i, d in member_dirs.items():
        if i != me:
            denied += [(r, "member m%s's work dir" % i) for r in _roots(d)]
    for form in _forms(path):
        if any(_under(form, o) for o in own):
            continue                # inside the member's own m<i>/ (this form; the other form is checked too)
        for r, why in denied:
            if _under(form, r):
                return "eq member m%s may not touch %s: %s" % (me, form[:200], why)
            if recursive and _under(r, form):
                return "eq member m%s may not search %s: it contains %s" % (me, form[:200], why)
    return None


# ---------------------------------------------------------------- plan-time path checks
def _expand(pattern, home):
    p = pattern.strip()
    if p.startswith("//"):
        p = p[1:]
    if p.startswith("~/") or p == "~":
        p = os.path.join(home, p[2:])
    return p


def _glob_match(path, pattern):
    """Gitignore-style match: `**` any depth, `*` within one component; a pattern without a leading
    slash or `**/` matches anywhere below; a match of a directory covers everything under it."""
    if not pattern:
        return False
    rx = ""
    k = 0
    while k < len(pattern):
        c = pattern[k]
        if pattern.startswith("**/", k):
            rx += "(?:.*/)?"
            k += 3
            continue
        if pattern.startswith("**", k):
            rx += ".*"
            k += 2
            continue
        if c == "*":
            rx += "[^/]*"
        elif c == "?":
            rx += "[^/]"
        else:
            rx += re.escape(c)
        k += 1
    if not pattern.startswith("/"):
        rx = "(?:.*/)?" + rx
    return re.fullmatch(rx + "(?:/.*)?", path) is not None


def settings_deny_patterns(settings, home):
    """Read-deny patterns of a rendered settings.json: sandbox.filesystem.denyRead and permissions.deny
    `Read(...)` rules, `~` expanded."""
    out = []
    if not isinstance(settings, dict):
        return out
    fs = ((settings.get("sandbox") or {}).get("filesystem") or {}) if isinstance(settings.get("sandbox"), dict) else {}
    for p in fs.get("denyRead") or []:
        if isinstance(p, str):
            out.append(_expand(p, home))
    perms = settings.get("permissions") if isinstance(settings.get("permissions"), dict) else {}
    for rule in perms.get("deny") or []:
        m = re.fullmatch(r"Read\((.+)\)", rule) if isinstance(rule, str) else None
        if m:
            out.append(_expand(m.group(1), home))
    return out


def settings_denied(path, settings, *, home, config_dir, state_root):
    """The reason a path (resolved) may never be read by stack-eq for a plan (spec 6.2), else None: it
    matches the sandbox denyRead list or a Read() deny rule, or it is a protected path (the config dir,
    the state root, the home directory itself, a home secret)."""
    forms = _forms(path)
    prot = [(r, "the Claude config dir") for r in _roots(config_dir)]
    prot += [(r, "the stack's state") for r in _roots(state_root)]
    prot += [(r, "a home secret (~/%s)" % s) for s in HOME_SECRETS for r in _roots(os.path.join(home, s))]
    homes = _roots(home)
    for form in forms:
        if any(_norm(form) == _norm(h) for h in homes):
            return "%s is the home directory" % form
        for r, why in prot:
            if _under(form, r):
                return "%s is under %s" % (form[:200], why)
        for pat in settings_deny_patterns(settings, home):
            if _glob_match(_norm(form), _norm(pat)):
                return "%s matches the deny rule %s" % (form[:200], pat[:120])
    return None


def under_root(path, root):
    """True when the resolved path lies inside root (resolved)."""
    return any(_under(f, r) for f in _forms(path)[-1:] for r in _roots(root)[-1:])


def sha256_bytes(b):
    return hashlib.sha256(b).hexdigest()


def fnmatch_any(name, patterns):
    return any(fnmatch.fnmatchcase(name, p) for p in patterns)


if __name__ == "__main__":
    sys.stderr.write("eq_policy is a library (imported by the guard, stack-eq and stack-eq-check)\n")
    sys.exit(2)
