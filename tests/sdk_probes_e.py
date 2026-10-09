#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["claude-agent-sdk==0.2.163"]
# [tool.uv]
# exclude-newer = "2026-10-01T00:00:00Z"
# ///
"""Agent SDK probes E1-E3 and E3P: what the SDK-2r and SDK-3 reviews left open (sec-r10 NOT CHECKED and N2,
the SDK-3 plan-gate assumptions). They make real, billed API calls, so the user runs them: never pytest (no
test_ prefix), never an agent. Hash-locked by tests/sdk_probes_e.py.lock (`uv lock --script tests/sdk_probes_e.py`).

    uv run --locked --script tests/sdk_probes_e.py --only E1,E3P          # dry run, the default: the plan, $0
    SDK_PROBES_E_CONSENT=0.55 uv run --locked --script tests/sdk_probes_e.py --paid --only E1,E3P [--cli PATH]

Consent (the user's decision, 2026-10-09): at most $2.00 in all, ACROSS RUNS, E1+E2 at most $1.50 and E3+E3P at
most $0.50 within a run. A paid run needs --paid and SDK_PROBES_E_CONSENT equal to the run's own cap: the sum
of the selected probes' caps as %.2f (E1+E3P: 0.55); a run with all of E1, E2 and E3 selected keeps the first
run's value, 2.00, and the $2.00 as its own cap. Without --paid it is a dry run; --paid alone is a usage error.
Before the ledger opens, every <name>.ledger.jsonl in the report's directory (and in the default one,
<main checkout>/.claude-work/sdk/probes/) is replayed: a session counts at its last reported cost, or at its
whole cap where its last event is a reservation (never reported, an open turn, closed with an agent running);
an unreadable ledger refuses the run. The run is refused when that prior spend plus its own cap exceeds $2.00;
the dry run and the paid run print what is left (2.00 - prior). The first paid runs (2026-10-09: -e, -e-2, -e-3)
used $1.4041 at worst, so $0.5959 is left. E1 needs the v2 stack_sdk.py installed (Session, StackNotLoaded,
config_root, wire: checked before the ledger opens); E2, E3 and E3P need only options().

Caps: E1 $0.45 (seven Sonnet sessions, each at most $0.08), E2 $0.60, E3 $0.40, E3P $0.10 (one session at most
$0.08). The margins cover the CLI checking max_budget_usd only after a turn (a session may overshoot its cap by
one turn). Every session gets at most what its probe, its envelope group and the run's cap have left by the
reported costs, and none starts below $0.02. A session counts at its whole cap until a ResultMessage reports
its cost (E2c's connect-only session stays there: U15 measured $0, but nothing reports it). A result without
a finite, non-negative total_cost_usd keeps its session at the whole cap and stops the run: nothing more starts
(fail closed). A probe left with less than a session needs ends there (cap_used, its unmeasured parts skipped);
any other refusal by the cap logic stops the run.

E1 (the analysis's E1', 2026-10-09): the first runs' E1 measured nothing (Session(None) ran the settings.json
agent, blackcat: no Bash tool, its model sonnet beat model=haiku). E1 now runs Session("verifier") (Bash, no
permissionMode, model sonnet: the agent's model decides); a leg is INVALID unless its session's agent setting
(the transcript's agent-setting row; CLI 2.1.287's init frame has no agent field) is the verifier, Bash is in
the init tool list and the init frame names a model. E1b is split: untrusted (the CLI's stderr, read through
the SDK's stderr callback for the trust warning only, answers "dropped (untrusted)") and trusted
(CLAUDE_CODE_SANDBOXED=1 in that leg's env, against its own no-rule control under the same env). No temp
CLAUDE_CONFIG_DIR (the login's keychain entry is named after it) and no edit of ~/.claude.json.
E3P (the analysis's E3'): a foreground Agent child, then a SendMessage resume (E3c2a: does its meta.json
toolUseId survive?) and the hook logger's meta.json check at each child's first tool call (E3e). E3d now reads
a refused resume (SendMessage: "was stopped by the user and was not resumed") as "terminal". E2 is not re-run
(its E2a one-call-per-turn rewrite is out of scope).

Models: E1 the verifier's own (sonnet); every other main thread "haiku" (a session option; nothing in stack.env
changes) and the throwaway agents say `model: haiku`; the report records each session's model from its init
frame. Every session has max_turns (E1 3, E2 4, E3 8, E3P 6), the throwaway agents `maxTurns: 4`, and every
probe a wall-clock limit.

State: each probe works in fresh temp dirs and every session's XDG_STATE_HOME points into them, so the stack's
hooks (E1 loads the installed stack through stack_sdk.Session) write their state there. E2, E3 and E3P load
only the temp project's settings (setting_sources ["project"]): no user settings, hooks or allow rules, so the
PreToolUse logger is a throwaway hook in the temp project. Nothing here writes ~/.claude, ~/.codex or this
repository; the CLI itself writes what it writes for any session, its transcripts under
<config>/projects/<temp cwd>/ (E1 reads the agent setting there, E3 and E3P the subagents' meta.json).

The report (default <main checkout>/.claude-work/sdk/probes/<date>-e.md, never overwritten) holds, per part,
the question, the observable, the reading and the answer (yes / no / unknown: the observable is missing /
invalid / dropped (untrusted) / terminal / error / skipped / refused), and per probe the cost, cap, session
ids, models, transcript paths and measured facts (numbers, booleans, identifiers). No prompt, reply, tool
input, stderr or error text is written. The ledger (<report>.ledger.jsonl, 0600, appended as the run goes)
holds the envelope (with the prior spend), every reservation and every reported cost.
"""
from __future__ import annotations

import argparse
import asyncio
import contextlib
import dataclasses
import datetime
import glob
import importlib.util
import json
import math
import os
import re
import shlex
import shutil
import sys
import time
from collections import Counter
from collections.abc import Awaitable, Callable
from typing import Any


def _load_base() -> Any:
    """tests/sdk_probes.py (PR1-PR13), beside this file: its stream readers, hosts, cost book and cleaner."""
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sdk_probes.py")
    spec = importlib.util.spec_from_file_location("sdk_probes_base", path)
    if spec is None or spec.loader is None or not os.path.isfile(path):
        raise SystemExit("no tests/sdk_probes.py beside %s" % __file__)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["sdk_probes_base"] = mod           # dataclasses resolve annotations through sys.modules
    spec.loader.exec_module(mod)
    return mod


base = _load_base()
kind, is_result, result_of, init_data, session_of = base.kind, base.is_result, base.result_of, base.init_data, \
    base.session_of
task_states, agents_running, poll, clean, BudgetError = base.task_states, base.agents_running, base.poll, \
    base.clean, base.BudgetError

SDK_PIN = base.SDK_PIN
TOTAL_CAP_USD = 2.00                                # the user's consent of 2026-10-09, across all runs
ENVELOPE = {"E1E2": 1.50, "E3": 0.50}                # within one run
CONSENT_ENV, CONSENT_VALUE = "SDK_PROBES_E_CONSENT", "%.2f" % TOTAL_CAP_USD   # CONSENT_VALUE: FULL_SET runs only
FULL_SET = frozenset({"E1", "E2", "E3"})            # a run with all three keeps the first run's 2.00 consent
CONSENT_TEXT = ("the user's decision of 2026-10-09: at most $2.00 in all, across runs (every ledger in the "
                "report directory counts), E1+E2 at most $1.50 plus E3+E3P at most $0.50 per run; user-run only "
                "(--paid and %s=<the run's cap>)" % CONSENT_ENV)
MIN_SESSION_USD = 0.02
MODEL = "haiku"
E1_AGENT = "verifier"                               # E1's main thread: Bash, no permissionMode, model sonnet
E1_SESSION_USD = 0.08                               # one E1 Sonnet session (measured ~0.054 as blackcat)
E3P_SESSION_USD = 0.08                              # E3P's one session (E3c2a and E3e)
TRUST_WARNING = "this workspace has not been trusted"           # CLI 2.1.287, stderr (console.error)
TRUST_ENV = {"CLAUDE_CODE_SANDBOXED": "1"}          # E1's trusted legs: a trust switch by the CLI's text
RESUME_REFUSED = "was stopped by the user and was not resumed"  # CLI 2.1.287, SendMessage on a stopped child
LEDGER_GLOB = "*.ledger.jsonl"
IDENT_RX = re.compile(r"[\w.:@+-]{1,128}")           # a model, an agent name: what a fact may record
CHILD_MAX_TURNS = 4                                 # the throwaway agents' frontmatter maxTurns
CEILING_ENV = "CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS"
SANDBOX_OVERLAY = base.SETTINGS_OVERLAY             # sandbox.autoAllowBashIfSandboxed false
STACK_RULE_CMD = "just -f tools/instructor/justfile --list"
STACK_RULE = "Bash(%s)" % STACK_RULE_CMD           # an exact Bash allow rule of the stack's settings.json
# what E1 needs of the INSTALLED <config>/bin/stack_sdk.py (the v2 helper, SDK-2); E2 and E3 need only options(),
# which the v1 helper has too, so `--only E2,E3` runs on an older install
E1_NEEDS = ("Session", "StackNotLoaded", "config_root", "wire")
UNVERIFIED = (
    "how far the CLI overshoots max_budget_usd within a turn, and whether subagent spend counts against it",
    "whether make_git's bare .git (HEAD, objects, refs) stops the CLI's walk to the repository root (E2c1)",
    "whether an unknown subagent_type makes the Agent call fail rather than fall back to another agent (E2b)",
    "whether CLAUDE_CODE_SESSION_KIND=bg makes the CLI write outside the temp dirs (E2a)",
    "whether a growing subagent transcript proves a SendMessage resume (E3c2, E3c2a, E3d)",
    "whether the CLI prints the trust warning to stderr under the SDK at all (E1b untrusted reads no without it)",
    "what CLAUDE_CODE_SANDBOXED=1 changes besides trust (E1b trusted has its own control under the same env)",
    "that the transcript's agent-setting row names the main thread's agent (E1's validity check)",
)
ANSWERS = ("yes", "no", "unknown", "invalid", "dropped (untrusted)", "terminal")
DECISIONS = ("allow", "deny", "ask", "defer")

PROMPTS = {
    "ok": "Reply with exactly: ok",
    "e1_bash": ("This is a test of how plan mode treats one Bash call: the call itself is the test, and the "
                "permission system, not you, decides whether it runs, so make it even though plan mode is on. Call "
                "the Bash tool exactly once with the command `{command}` and nothing else. Do not plan, delegate or "
                "retry. Then reply with one word: done."),
    "e2_calls": ("This is a permission test: the permission system decides, not you. Make exactly these three tool "
                 "calls, one at a time, and nothing else: the Bash tool with the command `{allow}`; the Bash tool "
                 "with the command `{deny}`; the Read tool on the file {read}. Do not retry a denied call. Then "
                 "reply with one word: done."),
    "e2_dispatch": ("Call the Agent tool exactly once with subagent_type {agent} (even if that type is not listed) "
                    "and the prompt: reply with the single word ok. Then reply with only its answer."),
    "e3_skill": ("Call the Skill tool exactly once with the skill {skill}, wait for it to finish, then reply with one "
                 "word: done. Do nothing else."),
    "e3_hold": ("Call the Agent tool exactly once with subagent_type {agent}, run_in_background true, and the prompt: "
                "write the file {marker} containing ok, then run the Bash command `uv --version` once, then reply "
                "done. Then end your turn without waiting for it."),
    "e3_send": ("Call the SendMessage tool exactly once, to the agent {agent_id}, with the message: reply with the "
                "single word ok. Wait for its reply, then reply with one word: done."),
    "e3_fg": ("Call the Agent tool exactly once with subagent_type {agent}, in the foreground (run_in_background "
              "false), and the prompt: read the file {path} with the Read tool, then reply done. Wait for it to "
              "finish, then reply with one word: done."),
}
# the throwaway agents and skill (files in the temp projects, never in the report)
LATE_BODY = "Reply with exactly: ok"
WRITER_BODY = "Write exactly the file you are asked to write, with the Write tool, then reply: done."
FORK_BODY = "Write the file {marker} containing the single word ok with the Write tool, then reply: done."
HOLDER_BODY = ("Do exactly what you are asked, in order: write the file with the Write tool, then run the Bash "
               "command once, then reply: done.")
ECHO_BODY = "Do exactly what you are asked: read the file with the Read tool, then reply: done."
E1_SCRIPT = "touch {marker}\n"                       # E1's <cwd>/e1.sh: the marker write, behind `sh <script>`
# the throwaway PreToolUse command hook (E3, E3P): logs identifiers and booleans only, decides nothing. For a
# child's row (E3e) it also logs whether the child's meta.json exists now and holds a toolUseId, looked up
# where agent_guard's spawn_meta looks (meta_folders: agent_transcript_path's folder, then
# <transcript_path minus .jsonl>/subagents, a subagent's own transcript mapped back to its folder)
HOOK_LOGGER = '''import json, os, re, sys
OK = re.compile(r"[A-Za-z0-9_.:@+-]{1,128}")
try:
    ev = json.load(sys.stdin)
except Exception:
    sys.exit(0)
row = {k: ev.get(k) for k in ("hook_event_name", "tool_name", "permission_mode", "agent_id", "agent_type")}
row = {k: v for k, v in row.items() if isinstance(v, str) and OK.fullmatch(v)}
aid, folders = row.get("agent_id"), []
atp, tp = ev.get("agent_transcript_path"), ev.get("transcript_path")
if aid and isinstance(atp, str) and atp.strip():
    folders.append(os.path.dirname(os.path.expanduser(atp.strip())))
if aid and isinstance(tp, str) and tp.strip():
    tp = os.path.expanduser(tp.strip())
    d, stem = os.path.dirname(tp), os.path.basename(tp)
    if os.path.basename(d) == "subagents":
        folders.append(d)
    else:
        stem = stem[:-len(".jsonl")] if stem.endswith(".jsonl") else str(ev.get("session_id") or stem)
        folders.append(os.path.join(d, stem, "subagents"))
if folders:
    metas = [os.path.join(f, "agent-%s.meta.json" % aid) for f in folders]
    row["meta_json"], row["meta_tool_use_id"] = any(os.path.isfile(p) for p in metas), False
    for p in metas:
        try:
            with open(p, encoding="utf-8") as fh:
                m = json.load(fh)
        except Exception:
            continue
        if isinstance(m, dict) and isinstance(m.get("toolUseId"), str) and m["toolUseId"].strip():
            row["meta_tool_use_id"] = True
with open(sys.argv[1], "a", encoding="utf-8") as fh:
    fh.write(json.dumps(row) + "\\n")
'''


@dataclasses.dataclass(frozen=True)
class Part:
    pid: str
    question: str
    observable: str
    reading: str


@dataclasses.dataclass(frozen=True)
class Probe:
    pid: str
    group: str                        # its ENVELOPE key
    budget_usd: float                 # the probe's cap: all its sessions together
    timeout_s: float
    max_turns: int                    # every session's main-thread turn limit
    parts: tuple[Part, ...]
    fn: Callable[[Ctx], Awaitable[None]]
    est_usd: tuple[float, float] = (0.0, 0.0)   # the expected spend (low, high): the plan's estimate, not a cap


@dataclasses.dataclass
class Config:
    config_dir: str                   # the installed stack (CLAUDE_CONFIG_DIR, ~/.claude): read, never written
    cli_path: str | None              # the user's installed claude (Q3)
    transport_factory: Callable[[Any], Any] | None = None   # tests: a fake Transport per session
    killer: Callable[[int, int], None] = os.kill
    state_dir: str = ""               # base.Ctx's guard paths (unused here)
    turn_s: float = 240.0             # one prompt's reply
    wait_s: float = 90.0              # each wait: a child, a stop, a resumed child
    hold_s: float = 150.0             # E3d: the longest the host parks the child's Bash request
    settle_s: float = 3.0             # file side effects: an agent file watched, a meta.json rewritten


def consent_value(probes: list[Probe]) -> str:
    """The SDK_PROBES_E_CONSENT value a paid run of `probes` needs: its own cap, the sum of the selected caps as
    %.2f; a run with all of E1, E2 and E3 keeps the first run's 2.00 (the whole consent as its cap)."""
    if FULL_SET <= {p.pid for p in probes}:
        return CONSENT_VALUE
    return "%.2f" % sum(p.budget_usd for p in probes)


def run_cap(probes: list[Probe]) -> float:
    """What the run may book in all: its consent value in dollars."""
    return float(consent_value(probes))


def validate_registry(probes: list[Probe]) -> None:
    """Every probe has its own cap within its envelope group; the caps of a group stay within the group's
    envelope and all of them within the total; every probe has a turn limit."""
    ids = [p.pid for p in probes]
    if len(set(ids)) != len(ids):
        raise BudgetError("duplicate probe ids")
    if sum(ENVELOPE.values()) > TOTAL_CAP_USD + 1e-9:
        raise BudgetError("the envelope groups sum above the total")
    by: Counter[str] = Counter()
    for p in probes:
        env, b = ENVELOPE.get(p.group), p.budget_usd
        if env is None:
            raise BudgetError("%s: no envelope group %r" % (p.pid, p.group))
        if isinstance(b, bool) or not isinstance(b, (int, float)) or not math.isfinite(b) or not 0 < b <= env:
            raise BudgetError("%s: cap %r is not in (0, %.2f]" % (p.pid, b, env))
        t = p.max_turns
        if isinstance(t, bool) or not isinstance(t, int) or not 0 < t <= 12:
            raise BudgetError("%s: max_turns %r is not in [1, 12]" % (p.pid, t))
        by[p.group] += b
    for g, s in by.items():
        if s > ENVELOPE[g] + 1e-9:
            raise BudgetError("the caps of %s sum above %.2f" % (g, ENVELOPE[g]))
    if sum(by.values()) > TOTAL_CAP_USD + 1e-9:
        raise BudgetError("the caps sum above %.2f" % TOTAL_CAP_USD)


class CapUsed(BudgetError):
    """The probe has less left than a session needs: the probe ends there (status cap_used), its unmeasured
    parts skipped; the run goes on with the next probe under its own cap. Any other BudgetError (an unreported
    cost, a session cap outside what is left) stops the run."""


def valid_cost(c: Any) -> bool:
    return not isinstance(c, bool) and isinstance(c, (int, float)) and math.isfinite(c) and c >= 0


# ---------------------------------------------------------------- the probe context: caps, cost book, sessions
class Ctx(base.Ctx):
    """base.Ctx's cost book (a session at its whole cap until its first result; closed with an agent running:
    whole cap) plus: an unreported cost fails closed, the ledger, and sessions on temp projects."""

    def __init__(self, probe: Probe, cfg: Config, helper: Any, cap_left: float,
                 ledger: Callable[[dict[str, Any]], None] | None = None):
        super().__init__(probe, cfg, helper, cap_left)      # cap = min(the probe's cap, what is left)
        self.ledger = ledger or (lambda ev: None)
        self.unknown_cost, self.unknown_keys, self.caps = False, set(), {}
        self.floor: dict[int, float] = {}               # open_turn: the session's total before the open turn
        self.answers: dict[str, str] = {}
        self.facts: dict[str, Any] = {}
        self.models: dict[int, str] = {}                # session key -> the model its init frame names
        self.state = self.mkdir("state")

    def mkdir(self, *parts: str) -> str:
        p = os.path.join(self.scratch, *parts)
        os.makedirs(p, exist_ok=True)
        return p

    def budget(self, share: float = 1.0, usd: float | None = None) -> float:
        """The next session's cap: at most what the probe has left, `share` of its cap and `usd`; rounded down
        to 1/10000 USD; never below MIN_SESSION_USD; nothing after an unreported cost."""
        if self.unknown_cost:
            raise BudgetError("%s: a session's cost was not reported: nothing more starts" % self.probe.pid)
        b = min(self.cap - self.spent, self.cap * share, math.inf if usd is None else usd)
        b = math.floor(b * 10_000 + 1e-5) / 10_000
        if not b >= MIN_SESSION_USD:
            raise CapUsed("%s: %.4f left, under the %.2f a session needs" % (self.probe.pid, b, MIN_SESSION_USD))
        return b

    def check(self, opts: Any) -> None:
        if self.unknown_cost:
            raise BudgetError("%s: a session's cost was not reported: nothing more starts" % self.probe.pid)
        super().check(opts)

    def reserve(self, key: int, opts: Any) -> None:
        super().reserve(key, opts)
        self.caps[key] = float(opts.max_budget_usd)
        self.ledger({"ev": "reserve", "probe": self.probe.pid, "session": key, "usd": self.caps[key]})

    def rebook(self, key: int, usd: float) -> None:
        """No result proves what a session spent: it counts at its whole cap again (ledger 'reserve')."""
        self.reported.discard(key)
        self.costs[key] = max(self.costs.get(key, 0.0), usd)
        self.ledger({"ev": "reserve", "probe": self.probe.pid, "session": key, "usd": self.costs[key], "unproven": True})

    def open_turn(self, key: int) -> None:
        """Before another prompt on a session that already reported: the CLI may spend up to the session's
        cap again, so the session counts at its whole cap until that turn's result replaces it (never below
        the total reported so far: `floor`)."""
        if key in self.unknown_keys or key not in self.caps:
            return
        if key in self.reported:
            self.floor[key] = max(self.floor.get(key, 0.0), self.costs.get(key, 0.0))
            self.reported.discard(key)
        self.costs[key] = max(self.costs.get(key, 0.0), self.caps[key])
        self.ledger({"ev": "reserve", "probe": self.probe.pid, "session": key, "usd": self.caps[key], "turn": True})

    def note(self, key: int, m: Any) -> None:
        if is_result(m):
            c = getattr(m, "total_cost_usd", None)
            if key in self.unknown_keys:
                pass                                    # its cap stays booked whatever comes later
            elif not valid_cost(c):
                self.unknown_cost = True                # fail closed: the whole cap, and nothing more starts
                self.unknown_keys.add(key)
                self.reported.discard(key)
                self.costs[key] = max(self.costs.get(key, 0.0), self.caps.get(key, self.cap))
                self.ledger({"ev": "cost_unknown", "probe": self.probe.pid, "session": key,
                             "booked_usd": self.costs[key]})
            else:                                       # the first result replaces the reservation; cumulative after
                cost = max(self.floor.pop(key, 0.0), float(c))
                self.costs[key] = max(self.costs.get(key, 0.0), cost) if key in self.reported else cost
                self.reported.add(key)
                self.ledger({"ev": "cost", "probe": self.probe.pid, "session": key, "usd": round(cost, 6)})
        elif kind(m) == "RateLimitEvent":
            self.rate_limit_events += 1
        sid = getattr(m, "session_id", None)
        if kind(m) == "SystemMessage" and isinstance(getattr(m, "data", None), dict):
            sid = m.data.get("session_id") or sid
            model = m.data.get("model")
            if getattr(m, "subtype", "") == "init" and isinstance(model, str) and IDENT_RX.fullmatch(model):
                self.models[key] = model
        if isinstance(sid, str) and re.fullmatch(r"[\w-]{8,80}", sid) and sid not in self.session_ids:
            self.session_ids.append(sid)

    def settle(self, key: int, msgs: list[Any], opts: Any) -> None:
        before = self.costs.get(key)
        super().settle(key, msgs, opts)          # closed with an agent running: its whole cap
        if self.costs.get(key) != before:
            self.ledger({"ev": "reserve", "probe": self.probe.pid, "session": key, "usd": self.costs[key], "closed": True})
        if key in self.unknown_keys:
            self.reported.discard(key)

    def options(self, cwd: str, *, share: float = 1.0, usd: float | None = None, sources: tuple[str, ...] = ("project",),
                env: dict[str, str] | None = None, **kw: Any) -> Any:
        """A raw session on a temp project: only `sources` (the temp project's settings by default), the probe's
        turn limit, model haiku, no MCP, state in the probe's temp dir."""
        kw.setdefault("cli_path", self.cfg.cli_path)
        kw.setdefault("model", MODEL)
        kw.setdefault("max_turns", self.probe.max_turns)
        kw.setdefault("strict_mcp_config", True)
        kw["disallowed_tools"] = [*base.DISALLOWED, *base.allowed_mcp(self.cfg.config_dir),
                                  *kw.get("disallowed_tools", ())]
        env = dict({"XDG_STATE_HOME": self.state, CEILING_ENV: "3000"}, **(env or {}))   # never CLAUDE_CONFIG_DIR
        return self.helper.options(None, budget_usd=self.budget(share, usd), cwd=cwd, sources=sources, env=env, **kw)

    @contextlib.asynccontextmanager
    async def stack_session(self, cwd: str, msgs: list[Any], *, usd: float | None = None, overlay: bool = True,
                            env: dict[str, str] | None = None, **kw: Any):
        """A stack_sdk.Session on the INSTALLED stack, host none (unattended: plan, --permission-prompts none),
        main thread the E1_AGENT agent (Session("verifier"): Bash, no permissionMode; its own model, sonnet,
        decides: no model= is passed, and an agent's frontmatter model beat model= in the first run); with
        `overlay`, sandbox.autoAllowBashIfSandboxed false (the Session itself refuses overlays: the probe adds it
        to isolate the allow rules from the sandbox). `env` is added to the session's (E1's trusted legs). No
        config_dir: Session would export CLAUDE_CONFIG_DIR, and CLI 2.1.287 names the keychain entry of the
        login after it whenever that variable is set (jF(): "Claude Code-credentials-<sha256(dir)[:8]>"), so a
        subscription login under the default ~/.claude would not be found."""
        if os.path.realpath(self.helper.config_root({})) != os.path.realpath(self.cfg.config_dir):
            raise RuntimeError("the CLI's config dir is not the one the probe reads")
        key = next(self.keys)

        def on(m: Any) -> None:
            self.note(key, m)
            msgs.append(m)
        budget = self.budget(usd=usd)
        try:
            s = probe_session_class(self.helper)(
                E1_AGENT, host="none", budget_usd=budget, cli=self.cfg.cli_path,
                transport=self.cfg.transport_factory, on_message=on, row=False, deadline_s=self.cfg.turn_s,
                bg_wait_s=self.cfg.wait_s, env=dict(env or {}, XDG_STATE_HOME=self.state), cwd=cwd,
                max_turns=self.probe.max_turns, strict_mcp_config=True,
                disallowed_tools=[*base.DISALLOWED, *base.allowed_mcp(self.cfg.config_dir)], **kw)
        except ValueError as e:         # e.g. a helper that refuses CLAUDE_CODE_SANDBOXED (sdk/env-channel)
            raise HelperRefused(type(e).__name__) from e
        s.overlay = overlay
        opts = s.preview()
        self.reserve(key, opts)
        try:
            async with s:
                yield s
        finally:
            self.settle(key, msgs, opts)


def probe_session_class(helper: Any) -> Any:
    class ProbeSession(helper.Session):
        overlay = True

        def build(self, plan: bool) -> Any:
            o = super().build(plan)
            return dataclasses.replace(o, settings=SANDBOX_OVERLAY) if self.overlay else o
    return ProbeSession


# ---------------------------------------------------------------- reading the stream and the files
def calls(msgs: list[Any], name: str) -> list[tuple[str, dict[str, Any], str | None]]:
    """(tool_use id, input, parent_tool_use_id) of every assistant call of `name`."""
    return [(b.id, b.input if isinstance(b.input, dict) else {}, getattr(m, "parent_tool_use_id", None))
            for m in msgs if kind(m) == "AssistantMessage" for b in m.content if kind(b) == "ToolUseBlock"
            and b.name == name]


def tool_errors(msgs: list[Any]) -> dict[str, bool]:
    """tool_use id -> is_error of every tool result in the stream."""
    out = {}
    for m in msgs:
        if kind(m) == "UserMessage" and isinstance(m.content, list):
            for b in m.content:
                if kind(b) == "ToolResultBlock":
                    out[b.tool_use_id] = bool(b.is_error)
    return out


def denied_ids(denials: Any) -> set[str]:
    return {str(d.get("tool_use_id")) for d in denials or [] if isinstance(d, dict)}


def result_denials(msgs: list[Any]) -> set[str]:
    return set().union(*[denied_ids(m.permission_denials) for m in msgs if is_result(m)])


def argv(cmd: Any) -> list[str] | None:
    try:
        return shlex.split(str(cmd))
    except ValueError:
        return None


def hook_decisions(helper: Any, msgs: list[Any]) -> Counter[str]:
    """The decisions of the PreToolUse hook responses (include_hook_events): permissionDecision values, and
    "block" for exit code 2. Only these enum values are kept."""
    out: Counter[str] = Counter()
    for m in msgs:
        if kind(m) != "HookEventMessage":
            continue
        d = helper.wire(m)
        if d.get("subtype") != "hook_response" or (d.get("hook_event") or "").split(":")[0] != "PreToolUse":
            continue
        if d.get("exit_code") == 2:
            out["block"] += 1
        for raw in (d.get("stdout"), d.get("output")):
            try:
                hso = (json.loads(raw) or {}).get("hookSpecificOutput") or {} if isinstance(raw, str) else {}
            except (ValueError, AttributeError):
                continue
            v = hso.get("permissionDecision") if isinstance(hso, dict) else None
            if v is not None:
                out[v if v in DECISIONS else "other"] += 1
                break
    return out


def agent_names(items: Any) -> set[str] | None:
    """The names in an agents list (server_info or init: dicts with `name`, or strings); None if no list."""
    if not isinstance(items, list):
        return None
    names = {i.get("name") if isinstance(i, dict) else i for i in items}
    return {n for n in names if isinstance(n, str)}


def init_frames(msgs: list[Any]) -> list[dict[str, Any]]:
    return [m.data for m in msgs if kind(m) == "SystemMessage" and getattr(m, "subtype", "") == "init"
            and isinstance(m.data, dict)]


def read_json(path: str) -> Any:
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def subagent_files(config: str, sid: str | None, aid: str | None, suffix: str) -> list[str]:
    if not sid or not aid or not re.fullmatch(r"[\w-]{1,128}", sid) or not re.fullmatch(r"[\w-]{1,128}", aid):
        return []
    return sorted(glob.glob(os.path.join(glob.escape(config), "projects", "*", sid, "subagents",
                                         "agent-%s%s" % (aid, suffix))))


def metas(config: str, sid: str | None) -> dict[str, dict[str, Any]]:
    """agent id -> Claude Code's agent-<id>.meta.json of the session (not a documented interface)."""
    if not sid or not re.fullmatch(r"[\w-]{1,128}", sid):
        return {}
    out = {}
    for p in sorted(glob.glob(os.path.join(glob.escape(config), "projects", "*", sid, "subagents",
                                           "agent-*.meta.json"))):
        meta = read_json(p)
        if isinstance(meta, dict):
            out[os.path.basename(p)[len("agent-"):-len(".meta.json")]] = meta
    return out


def read_meta(config: str, sid: str | None, aid: str | None) -> dict[str, Any] | None:
    for p in subagent_files(config, sid, aid, ".meta.json"):
        meta = read_json(p)
        if isinstance(meta, dict):
            return meta
    return None


def meta_facts(meta: dict[str, Any] | None) -> dict[str, Any]:
    if meta is None:
        return {"present": False}
    tid, stopped = meta.get("toolUseId"), meta.get("stoppedByUser")
    return {"present": True, "agent_type": meta.get("agentType"), "tool_use_id": tid if isinstance(tid, str) else None,
            "stopped_by_user": stopped if isinstance(stopped, bool) else None}


def transcript_lines(config: str, sid: str | None, aid: str | None) -> int | None:
    for p in subagent_files(config, sid, aid, ".jsonl"):
        with open(p, encoding="utf-8", errors="replace") as fh:
            return sum(1 for ln in fh if ln.strip())
    return None


def hook_rows(path: str) -> list[dict[str, Any]]:
    """The logger's rows: its string identifiers and its booleans (E3e's meta_json, meta_tool_use_id)."""
    rows = []
    with contextlib.suppress(OSError), open(path, encoding="utf-8") as fh:
        for ln in fh:
            with contextlib.suppress(ValueError):
                r = json.loads(ln)
                if isinstance(r, dict):
                    rows.append({k: v for k, v in r.items() if isinstance(v, (str, bool))})
    return rows


def agent_setting(config: str, sid: str | None, init: dict[str, Any]) -> str | None:
    """The main thread's agent: an agent field of the init frame if a CLI ever sends one, else the session
    transcript's last `{"type": "agent-setting", "agentSetting": ...}` row (CLI 2.1.287 writes it there, last
    wins; its init frame has no agent field). None if neither names one."""
    for k in ("agentSetting", "agent_setting", "agent"):
        v = init.get(k)
        if isinstance(v, str):
            return v if IDENT_RX.fullmatch(v) else None
    if not sid or not re.fullmatch(r"[\w-]{1,128}", sid):
        return None
    found = None
    for p in sorted(glob.glob(os.path.join(glob.escape(config), "projects", "*", sid + ".jsonl"))):
        with contextlib.suppress(OSError), open(p, encoding="utf-8", errors="replace") as fh:
            for ln in fh:
                if '"agent-setting"' not in ln:
                    continue
                with contextlib.suppress(ValueError):
                    r = json.loads(ln)
                    if isinstance(r, dict) and r.get("type") == "agent-setting" and r.get("sessionId", sid) == sid:
                        v = r.get("agentSetting")
                        found = v if isinstance(v, str) and IDENT_RX.fullmatch(v) else None
    return found


def write_text(path: str, text: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


def agent_md(name: str, body: str, mode: str | None = None, tools: str | None = None) -> str:
    fm = ["name: %s" % name, "description: Probe agent %s, for a permissions test only." % name, "model: %s" % MODEL,
          "maxTurns: %d" % CHILD_MAX_TURNS]
    fm += ["permissionMode: %s" % mode] if mode else []
    fm += ["tools: %s" % tools] if tools else []
    return "---\n%s\n---\n%s\n" % ("\n".join(fm), body)


def write_project(root: str, agents: tuple[tuple[str, str, str | None, str | None], ...] = (),
                  skills: tuple[tuple[str, str, str], ...] = (), hook: str | None = None) -> None:
    """A temp project: .claude/agents/<name>.md (name, body, mode, tools), .claude/skills/<name>/SKILL.md
    (name, agent, body: `context: fork`), and .claude/settings.json with one PreToolUse command hook."""
    for name, body, mode, tools in agents:
        write_text(os.path.join(root, ".claude", "agents", name + ".md"), agent_md(name, body, mode, tools))
    for name, agent, body in skills:
        write_text(os.path.join(root, ".claude", "skills", name, "SKILL.md"),
                   "---\nname: %s\ndescription: Probe skill %s, for a permissions test only.\ncontext: fork\n"
                   "agent: %s\n---\n%s\n" % (name, name, agent, body))
    if hook:
        write_text(os.path.join(root, ".claude", "settings.json"), json.dumps(
            {"hooks": {"PreToolUse": [{"matcher": "*", "hooks": [{"type": "command", "command": hook}]}]}}, indent=1))


def hook_command(script: str, log: str) -> str:
    return " ".join(shlex.quote(x) for x in (sys.executable, "-I", script, log))


def make_git(path: str) -> None:
    """An empty repository's .git (HEAD, objects, refs): what the CLI's walk stops at; no git process."""
    for d in ("objects", "refs"):
        os.makedirs(os.path.join(path, ".git", d), exist_ok=True)
    write_text(os.path.join(path, ".git", "HEAD"), "ref: refs/heads/main\n")


def installed(config: str) -> dict[str, Any]:
    """Read-only: the Bash allow rules and the sandbox switches of <config>/settings.json and settings.local.json."""
    allow: set[str] = set()
    sandbox: dict[str, Any] = {}
    for name in ("settings.json", "settings.local.json"):
        s = read_json(os.path.join(config, name))
        if not isinstance(s, dict):
            continue
        allow.update(a for a in ((s.get("permissions") or {}).get("allow") or []) if isinstance(a, str))
        sb = s.get("sandbox")
        if isinstance(sb, dict):
            sandbox.update({k: sb[k] for k in ("enabled", "autoAllowBashIfSandboxed") if isinstance(sb.get(k), bool)})
    return {"allow": allow, "sandbox": sandbox}


def load_reason(e: BaseException) -> str:
    """StackNotLoaded's message as a code (the message itself holds paths and names)."""
    s = str(e)
    for needle, code in (("marker", "guard_marker"), ("missing from server_info", "agents_missing"),
                         ("SessionStart hooks", "session_start_hooks"), ("did not succeed", "session_start_failed"),
                         ("drifted", "mode_drift"), ("outside <config>/agents", "project_agents"),
                         ("policy off", "policy_off"), ("bypassPermissions", "bypass")):
        if needle in s:
            return code
    return "other"


def yn(cond: bool | None) -> str:
    return "unknown" if cond is None else "yes" if cond else "no"


# ---------------------------------------------------------------- E1 (E1'): Bash allow rules under host none + plan
class HelperRefused(RuntimeError):
    """The installed stack_sdk.Session refused a leg's arguments (an env it will not pass): nothing started."""


def leg_validity(config: str, msgs: list[Any]) -> dict[str, Any]:
    """A leg measures the rules only if its main thread really was E1_AGENT with the Bash tool, and the init
    frame names its model (the first runs' E1 ran blackcat: no Bash, so nothing was measured)."""
    init = init_data(msgs)
    tools, model = init.get("tools"), init.get("model")
    out = {"agent_setting": agent_setting(config, session_of(msgs), init),
           "bash_tool": isinstance(tools, list) and "Bash" in tools,
           "model": model if isinstance(model, str) and IDENT_RX.fullmatch(model) else None}
    out["valid"] = out["agent_setting"] == E1_AGENT and out["bash_tool"] and out["model"] is not None
    return out


def bash_leg(helper: Any, msgs: list[Any], denials: Any, command: str, marker: str | None,
             validity: dict[str, Any]) -> dict[str, Any]:
    want = argv(command)
    ids = [i for i, inp, _ in calls(msgs, "Bash") if argv(inp.get("command")) == want]
    errs, den, hooks = tool_errors(msgs), denied_ids(denials), hook_decisions(helper, msgs)
    return {**validity, "attempted": bool(ids), "calls": len(ids), "denied": any(i in den for i in ids),
            "tool_error": any(errs.get(i) for i in ids), "marker": None if marker is None else os.path.exists(marker),
            "hook_decisions": dict(hooks), "mode": init_data(msgs).get("permissionMode")}


def bash_verdict(leg: dict[str, Any]) -> str:
    """invalid / not_plan / hook_decided / not_attempted / ran / denied. Invalid first: a leg whose main
    thread was not the verifier with Bash and a recorded model measured nothing. With a marker it decides;
    without one the call's denial does (permission_denials)."""
    if not leg.get("valid"):
        return "invalid"
    if leg["mode"] not in (None, "plan"):
        return "not_plan"
    if sum(leg["hook_decisions"].values()):
        return "hook_decided"
    if not leg["attempted"]:
        return "not_attempted"
    if leg["marker"] is not None:
        return "ran" if leg["marker"] else "denied"
    return "denied" if leg["denied"] else "ran"


def e1_command(cwd: str, marker: str) -> str:
    """`sh <cwd>/e1.sh`, the script touching the marker: the call does not look like a write (analysis §2).
    The rule names the command verbatim, so the path must be one plain shell word."""
    script = os.path.join(cwd, "e1.sh")
    if not re.fullmatch(r"[\w./@+:-]+", script) or not re.fullmatch(r"[\w./@+:-]+", marker):
        raise RuntimeError("E1's temp path is not a plain shell word")
    write_text(script, E1_SCRIPT.format(marker=marker))
    return "sh " + script


# (leg, rule, overlay, trusted): untrusted legs first (control first: the rule legs read against it), then the
# trusted pair (CLAUDE_CODE_SANDBOXED=1, its own control), then the stack's rule and the stack as installed
E1_LEGS = (("control", "", True, False), ("session_rule", "session", True, False), ("repo_rule", "repo", True, False),
           ("trusted_control", "", True, True), ("trusted_repo_rule", "repo", True, True),
           ("stack_rule", "stack", True, False), ("as_installed", "", False, False))
# part -> (its leg, the control whose denial makes the leg's reading mean something)
E1_READ = {"E1a": ("session_rule", "control"), "E1bu": ("repo_rule", "control"),
           "E1bt": ("trusted_repo_rule", "trusted_control"), "E1c": ("stack_rule", "control"),
           "E1d": ("as_installed", None)}


async def e1(c: Ctx) -> None:
    inst = installed(c.cfg.config_dir)
    f = c.facts
    f.update(e1_agent=E1_AGENT, stack_rule_installed=STACK_RULE in inst["allow"],
             sandbox_enabled=inst["sandbox"].get("enabled"),
             sandbox_auto_allow=inst["sandbox"].get("autoAllowBashIfSandboxed"))
    v: dict[str, str] = {}
    try:
        for name, rule, overlay, trusted in E1_LEGS:
            if rule == "stack" and not f["stack_rule_installed"]:
                v[name] = "skipped"
                continue
            cwd = c.mkdir("e1", name)
            marker = None if rule == "stack" else os.path.join(cwd, "e1-%s.marker" % name)
            command = STACK_RULE_CMD if marker is None else e1_command(cwd, marker)
            kw: dict[str, Any] = {}
            if rule == "session":
                kw["allowed_tools"] = ["Bash(%s)" % command]
            if rule == "repo":
                write_text(os.path.join(cwd, ".claude", "settings.json"),
                           json.dumps({"permissions": {"allow": ["Bash(%s)" % command]}}))
            msgs: list[Any] = []
            warned = Counter()

            def on_stderr(line: str, warned: Counter[str] = warned) -> None:
                """The CLI's stderr: only whether the trust warning came; no line is kept."""
                if TRUST_WARNING in str(line):
                    warned["trust"] += 1
            try:
                async with c.stack_session(cwd, msgs, usd=E1_SESSION_USD, overlay=overlay,
                                           env=dict(TRUST_ENV) if trusted else None, stderr=on_stderr, **kw) as s:
                    out = await s.ask(PROMPTS["e1_bash"].format(command=command))
            except c.helper.StackNotLoaded as e:           # $0 so far for this leg, but booked at its cap
                f["stack_not_loaded"], f["stack_not_loaded_leg"] = load_reason(e), name
                break
            except HelperRefused:                           # nothing started, nothing booked
                v[name] = f[name + "_verdict"] = "helper_refused"
                continue
            leg = bash_leg(c.helper, msgs, out.get("permission_denials"), command, marker,
                           leg_validity(c.cfg.config_dir, msgs))
            leg["trust_warning"] = warned["trust"] > 0
            f.update({"%s_%s" % (name, k): x for k, x in leg.items()})
            v[name] = f[name + "_verdict"] = bash_verdict(leg)
    except CapUsed:                                     # the legs measured so far still answer
        e1_answers(c, v)
        raise
    e1_answers(c, v)


def e1_answers(c: Ctx, v: dict[str, str]) -> None:
    """Per part: invalid if its leg or its control is invalid; unknown unless its control was denied (PR5b's
    lesson: a rule leg means something only if the same call without a rule was denied); E1c (no marker) also
    needs the control's denial to show in permission_denials (calibrated); a denied repo rule with the trust
    warning on stderr is "dropped (untrusted)". A leg that never ran leaves its part to the run (skipped)."""
    f, ans = c.facts, {"ran": "yes", "denied": "no"}
    f["denials_calibrated"] = calibrated = v.get("control") == "denied" and f.get("control_denied") is True
    for part, (leg, control) in E1_READ.items():
        lv = v.get(leg)
        if lv is None:
            continue
        if lv == "invalid" or (control is not None and v.get(control) == "invalid"):
            c.answers[part] = "invalid"
        elif control is not None and v.get(control) != "denied" or part == "E1c" and not calibrated:
            c.answers[part] = "unknown"
        else:
            a = ans.get(lv, "unknown")
            dropped = a == "no" and leg in ("repo_rule", "trusted_repo_rule") and f.get(leg + "_trust_warning")
            c.answers[part] = "dropped (untrusted)" if dropped else a


# ---------------------------------------------------------------- E2: the env channel, late and far agents
async def e2(c: Ctx) -> None:
    await e2c(c)
    await e2a(c)
    await e2b(c)


async def e2c(c: Ctx) -> None:
    """Layouts 1b and 6-subdir: connect only (no prompt; U15: $0, booked at the session's cap)."""
    root = c.mkdir("e2c")
    outer, extra = os.path.join(root, "outer"), os.path.join(root, "extra")
    repo = os.path.join(outer, "repo")
    for d, name in ((outer, "e2-above"), (repo, "e2-cwd"), (extra, "e2-adddir"), (os.path.join(extra, "sub"), "e2-subdir")):
        write_text(os.path.join(d, ".claude", "agents", name + ".md"), agent_md(name, LATE_BODY))
    make_git(repo)
    async with c.client(c.options(repo, usd=0.05, add_dirs=[extra])) as s:
        info = await s.c.get_server_info() or {}
    names = agent_names(info.get("agents") if isinstance(info, dict) else None)
    f = c.facts
    f["e2c_agents_listed"] = names is not None
    for n in ("e2-cwd", "e2-above", "e2-adddir", "e2-subdir"):
        f["e2c_%s" % n.replace("-", "_")] = None if names is None else n in names
    c.answers["E2c1"] = yn(f["e2c_e2_above"]) if f["e2c_e2_cwd"] else "unknown"
    c.answers["E2c2"] = yn(f["e2c_e2_subdir"]) if f["e2c_e2_adddir"] else "unknown"


async def e2a(c: Ctx) -> None:
    """CLAUDE_CODE_SESSION_KIND=bg + CLAUDE_BG_SESSION_PERMISSION_RULES (CLI 2.1.287 ic(): read only when the
    kind is bg; allow and deny become session rules, addDirs working directories) against a control with the
    same rules and the kind unset. Default mode, --permission-prompts none: what no rule allows is denied."""
    legs: dict[str, dict[str, Any]] = {}
    for leg in ("bg", "control"):
        cwd, extra = c.mkdir("e2a", leg, "cwd"), c.mkdir("e2a", leg, "extra")
        read = os.path.join(extra, "e2a-read.txt")
        write_text(read, "probe\n")
        a_mark, d_mark = os.path.join(cwd, "e2a-allow.marker"), os.path.join(cwd, "e2a-deny.marker")
        a_cmd, d_cmd = "touch " + a_mark, "touch " + d_mark
        rules = {"allow": ["Bash(%s)" % a_cmd], "deny": ["Bash(%s)" % d_cmd], "addDirs": [extra]}
        env = {"CLAUDE_BG_SESSION_PERMISSION_RULES": json.dumps(rules),
               "CLAUDE_CODE_SESSION_KIND": "bg" if leg == "bg" else ""}
        o = c.options(cwd, share=0.3, env=env, permission_mode="default", allowed_tools=["Bash(%s)" % d_cmd],
                      extra_args={"permission-prompts": "none"})
        async with c.client(o) as s:
            await s.turn(PROMPTS["e2_calls"].format(allow=a_cmd, deny=d_cmd, read=read), c.cfg.turn_s)
        errs, den = tool_errors(s.msgs), result_denials(s.msgs)
        bash = {k: [i for i, inp, _ in calls(s.msgs, "Bash") if argv(inp.get("command")) == argv(cmd)]
                for k, cmd in (("allow", a_cmd), ("deny", d_cmd))}
        reads = [i for i, inp, _ in calls(s.msgs, "Read") if str(inp.get("file_path") or "") == read]
        legs[leg] = {"allow_attempted": bool(bash["allow"]), "deny_attempted": bool(bash["deny"]),
                     "allow_marker": os.path.exists(a_mark), "deny_marker": os.path.exists(d_mark),
                     "read_attempted": bool(reads), "read_failed": any(i in den or errs.get(i, True) for i in reads),
                     "result": result_of(s.msgs) is not None}
    b, k = legs["bg"], legs["control"]
    for leg, d in legs.items():
        c.facts.update({"e2a_%s_%s" % (leg, x): y for x, y in d.items()})
    allow = None if not (b["allow_attempted"] and k["allow_attempted"]) or k["allow_marker"] else b["allow_marker"]
    deny = None if not (b["deny_attempted"] and k["deny_attempted"]) or not k["deny_marker"] else not b["deny_marker"]
    dirs = None if not (b["read_attempted"] and k["read_attempted"]) or not k["read_failed"] else not b["read_failed"]
    c.facts.update(e2a_allow_applied=allow, e2a_deny_applied=deny, e2a_add_dirs_applied=dirs)
    got = [allow, deny, dirs]
    c.answers["E2a"] = "yes" if True in got else "no" if None not in got else "unknown"


async def e2b(c: Ctx) -> None:
    """N2's window: a project agent file created after the first prompt, before the next one."""
    import anyio
    cwd, name = c.mkdir("e2b"), "e2-late"
    o = c.options(cwd, share=0.5, permission_mode="default", allowed_tools=["Agent", "Task"],
                  extra_args={"permission-prompts": "none"})
    async with c.client(o) as s:
        await s.turn(PROMPTS["ok"], c.cfg.turn_s)
        write_text(os.path.join(cwd, ".claude", "agents", name + ".md"), agent_md(name, LATE_BODY))
        await anyio.sleep(c.cfg.settle_s)               # a file watcher's debounce
        n = len(s.msgs)
        c.open_turn(s.key)
        await s.turn(PROMPTS["e2_dispatch"].format(agent=name), c.cfg.turn_s)
        await s.until_idle(c.cfg.turn_s)
    later, inits = s.msgs[n:], init_frames(s.msgs)
    mine = [i for tool in ("Agent", "Task") for i, inp, _ in calls(later, tool) if inp.get("subagent_type") == name]
    errs = tool_errors(later)
    started = any(t["type"] == name for t in task_states(later).values())
    ok = started or any(i in errs and not errs[i] for i in mine)
    last = agent_names(inits[-1].get("agents")) if inits else None
    c.facts.update(e2b_init_frames=len(inits), e2b_in_first_init=None if not inits else name in (agent_names(
        inits[0].get("agents")) or ()), e2b_in_last_init=None if last is None else name in last,
        e2b_attempted=bool(mine), e2b_task_started=started, e2b_call_ok=ok)
    c.answers["E2b"] = yn(ok) if mine or started else "unknown"


# ---------------------------------------------------------------- E3: the plan-gate assumptions
class SendHoldHost(base.HoldHost):
    """PR5b's HoldHost (Agent and Task allowed; the first subagent Bash request parked, then denied; the rest
    denied) that also allows SendMessage, for the resume."""

    async def __call__(self, tool: str, inp: dict[str, Any], context: Any) -> Any:
        if tool == "SendMessage":
            from claude_agent_sdk import PermissionResultAllow
            self.seen.append(tool)
            return PermissionResultAllow()
        return await super().__call__(tool, inp, context)


def own_mode(rows: list[dict[str, str]], actual: str | None, caller: str | None) -> str:
    """E3b on one session: the child's rows carry `actual` (proven by its marker) where the caller's differs."""
    child = {r.get("permission_mode") for r in rows if r.get("agent_id")}
    if not child or actual is None or caller is None or actual == caller:
        return "unknown"
    if child == {actual}:
        return "yes"
    return "no" if caller in child else "unknown"


async def e3(c: Ctx) -> None:
    logger = os.path.join(c.scratch, "hook_logger.py")
    write_text(logger, HOOK_LOGGER)
    await e3_fork(c, logger)
    e3b(c)
    await e3_hold(c, logger)
    e3b(c)


def e3b(c: Ctx) -> None:
    """E3b over the sessions measured so far: no if any says no, yes if any says yes."""
    b = [c.facts.get("e3b_fork"), c.facts.get("e3b_hold")]
    c.answers["E3b"] = "no" if "no" in b else "yes" if "yes" in b else "unknown"


async def e3_fork(c: Ctx, logger: str) -> None:
    """E3a, E3b (first data point), E3c: a `context: fork` skill into an acceptEdits agent, main thread in plan."""
    import anyio
    p, log = c.mkdir("e3", "fork"), os.path.join(c.scratch, "hooks-fork.jsonl")
    marker = os.path.join(p, "e3-fork.marker")
    write_project(p, agents=(("e3-writer", WRITER_BODY, "acceptEdits", "Write, Read"),),
                  skills=(("e3-fork", "e3-writer", FORK_BODY.format(marker=marker)),), hook=hook_command(logger, log))
    host = base.Host(p, ("Skill", "SendMessage"))     # every Write that reaches the host is denied
    f, cfg = c.facts, c.cfg
    async with c.client(c.options(p, share=0.5, permission_mode="plan", can_use_tool=host)) as s:
        await s.turn(PROMPTS["e3_skill"].format(skill="e3-fork"), cfg.turn_s)
        await s.until_idle(cfg.turn_s)
        sid, rows = session_of(s.msgs), hook_rows(log)
        skill = [i for i, _, parent in calls(s.msgs, "Skill") if parent is None]
        found = [a for a, m in metas(cfg.config_dir, sid).items() if m.get("agentType") == "e3-writer"]
        found += [r["agent_id"] for r in rows if r.get("agent_type") == "e3-writer" and r.get("agent_id")]
        aid = found[0] if found else None
        meta0, lines0, lines1, meta1 = read_meta(cfg.config_dir, sid, aid), transcript_lines(cfg.config_dir, sid, aid), \
            None, None
        if aid and lines0 is not None:
            c.open_turn(s.key)
            await s.turn(PROMPTS["e3_send"].format(agent_id=aid), cfg.turn_s)
            await s.until_idle(cfg.turn_s)
            await anyio.sleep(cfg.settle_s)
            lines1, meta1 = transcript_lines(cfg.config_dir, sid, aid), read_meta(cfg.config_dir, sid, aid)
    rows = hook_rows(log)
    main_mode = init_data(s.msgs).get("permissionMode")
    child_rows = [r for r in rows if r.get("agent_id")]
    writes = [r for r in child_rows if r.get("tool_name") == "Write"]
    sub_writes = [i for i, _, parent in calls(s.msgs, "Write") if parent]
    made = os.path.exists(marker)
    f.update(e3_main_mode=main_mode, e3a_marker=made, e3a_write_reached_host="Write" in host.seen,
             e3a_child_write_rows=len(writes), e3a_child_write_calls=len(sub_writes), e3_fork_child_found=aid is not None,
             e3_hook_rows_fork=len(rows), e3_child_modes_fork=sorted({r.get("permission_mode", "") for r in child_rows}),
             e3_main_modes_fork=sorted({r.get("permission_mode", "") for r in rows if not r.get("agent_id")}),
             e3c_skill_calls=len(skill), e3c_skill_tool_use_id=skill[0] if skill else None,
             **{"e3c_meta_%s" % k: v for k, v in meta_facts(meta0).items()},
             **{"e3c_meta_after_%s" % k: v for k, v in meta_facts(meta1).items()},
             e3c_child_lines_before=lines0, e3c_child_lines_after=lines1, e3c_send_calls=len(calls(s.msgs, "SendMessage")))
    attempted = bool(writes or sub_writes or "Write" in host.seen)
    if main_mode != "plan":
        c.answers["E3a"] = "unknown"
    else:
        c.answers["E3a"] = "yes" if made and "Write" not in host.seen else "no" if attempted else "unknown"
    actual = "acceptEdits" if made and "Write" not in host.seen else None
    f["e3b_fork"] = own_mode(rows, actual, main_mode)
    tid0, tid1 = (meta0 or {}).get("toolUseId"), (meta1 or {}).get("toolUseId")
    c1 = None if meta0 is None or not skill else tid0 == skill[0]
    c.answers["E3c1"] = yn(c1)
    resumed = lines0 is not None and lines1 is not None and lines1 > lines0
    f["e3c_resumed"] = resumed
    c.answers["E3c2"] = yn(tid1 == tid0 and meta1 is not None) if resumed and isinstance(tid0, str) and c1 is not None \
        else "unknown"


async def e3_hold(c: Ctx, logger: str) -> None:
    """E3d (and E3b's second data point): a background child held by its parked Bash request (PR5b), stopped
    with stop_task, then resumed with SendMessage; its meta.json read after each."""
    import anyio
    import anyio.lowlevel
    p, log = c.mkdir("e3", "hold"), os.path.join(c.scratch, "hooks-hold.jsonl")
    marker = os.path.join(p, "e3-hold.marker")
    write_project(p, agents=(("e3-holder", HOLDER_BODY, "acceptEdits", "Write, Bash"),), hook=hook_command(logger, log))
    host, cfg, f = SendHoldHost(c.cfg.hold_s), c.cfg, c.facts
    o = c.options(p, permission_mode="default", can_use_tool=host)
    sid = aid = meta0 = meta1 = lines0 = lines1 = refused = None
    n_stop = 0
    async with c.client(o) as s, anyio.create_task_group() as tg:
        tg.start_soon(s.drain)

        def child() -> Any:
            return next((m for m in s.msgs if kind(m) == "TaskStartedMessage" and m.task_type == "local_agent"), None)
        await s.c.query(PROMPTS["e3_hold"].format(agent="e3-holder", marker=marker))
        await poll(lambda: host.pending and child() is not None, cfg.wait_s)
        t = child()
        f.update(e3d_child_started=t is not None, e3d_child_pending=host.pending)
        if t is not None and host.holding:
            sid, aid = t.session_id or session_of(s.msgs), host.pending_agent
            n_stop = len(s.msgs)
            await s.c.stop_task(t.task_id)

            def status() -> Any:
                return task_states(s.msgs).get(t.task_id, {}).get("status")
            ended = await poll(lambda: status() in base.TERMINAL, cfg.wait_s)
            f.update(e3d_status_at_stop=status(), e3d_stop_ended_held_child=ended and host.holding)
            host.release.set()
            await anyio.sleep(cfg.settle_s)
            meta0, lines0 = read_meta(cfg.config_dir, sid, aid), transcript_lines(cfg.config_dir, sid, aid)
        host.release.set()
        await anyio.lowlevel.checkpoint()
        # the turn the stop may wake: only a result after the stop closes the session's spend (as PR5)
        closed = await poll(lambda: any(map(is_result, s.msgs[n_stop:])), cfg.wait_s)
        if not closed:
            m = len(s.msgs)
            await s.c.interrupt()
            closed = await poll(lambda: any(map(is_result, s.msgs[m:])), cfg.wait_s)
        if not closed:      # its whole cap; the resume's result (a running total per process, D8) replaces it
            c.rebook(s.key, float(o.max_budget_usd))
        f["e3d_result_after_stop"] = closed
        if aid and (meta0 or {}).get("stoppedByUser") is True:
            m = len(s.msgs)
            c.open_turn(s.key)
            await s.c.query(PROMPTS["e3_send"].format(agent_id=aid))

            def resume_done() -> bool:
                """The resume turn ended: its own SendMessage call, a result after it, no agent running (a
                result of an earlier turn landing late proves nothing about this one)."""
                later = s.msgs[m:]
                at = next((i for i, x in enumerate(later) if kind(x) == "AssistantMessage" and any(
                    kind(b) == "ToolUseBlock" and b.name == "SendMessage" for b in x.content)), None)
                return at is not None and any(map(is_result, later[at:])) and not agents_running(s.msgs)
            await poll(resume_done, cfg.wait_s)
            await anyio.sleep(cfg.settle_s)
            meta1, lines1 = read_meta(cfg.config_dir, sid, aid), transcript_lines(cfg.config_dir, sid, aid)
            # decided after the last read, with no await before the reader stops: no frame lands in between
            f["e3d_resume_turn_ended"] = done = resume_done()
            refused = resume_refused(s.msgs[m:])
            if not done:
                c.rebook(s.key, float(o.max_budget_usd))
        tg.cancel_scope.cancel()
    rows = hook_rows(log)
    made = os.path.exists(marker)
    resumed = lines0 is not None and lines1 is not None and lines1 > lines0
    f.update(e3d_hold_released_by=host.released_by, e3d_callback_tools=sorted(set(host.seen)), e3d_marker=made,
             e3_hook_rows_hold=len(rows),
             e3_child_modes_hold=sorted({r.get("permission_mode", "") for r in rows if r.get("agent_id")}),
             e3_main_modes_hold=sorted({r.get("permission_mode", "") for r in rows if not r.get("agent_id")}),
             **{"e3d_meta_%s" % k: v for k, v in meta_facts(meta0).items()},
             **{"e3d_meta_after_%s" % k: v for k, v in meta_facts(meta1).items()},
             e3d_child_lines_before=lines0, e3d_child_lines_after=lines1, e3d_resumed=resumed,
             e3d_resume_refused=refused)
    caller = init_data(s.msgs).get("permissionMode") or "default"
    f["e3b_hold"] = own_mode(rows, "acceptEdits" if made and "Write" not in host.seen else None, caller)
    c.answers["E3d"] = e3d_reading((meta0 or {}).get("stoppedByUser") is True, resumed, refused,
                                   (meta1 or {}).get("stoppedByUser") is True)


async def e3p(c: Ctx) -> None:
    """E3P (the analysis's E3'), one session: a foreground Agent child (e3-echo: default mode, Read only) reads a
    file and finishes; a SendMessage resumes it; its meta.json is read after each (E3c2a). The throwaway hook
    logger records at every child row whether the child's meta.json exists where agent_guard looks (E3e)."""
    import anyio
    logger, log = os.path.join(c.scratch, "hook_logger.py"), os.path.join(c.scratch, "hooks-e3p.jsonl")
    write_text(logger, HOOK_LOGGER)
    p = c.mkdir("e3p", "agent")
    target = os.path.join(p, "e3p-read.txt")
    write_text(target, "probe\n")
    write_project(p, agents=(("e3-echo", ECHO_BODY, None, "Read"),), hook=hook_command(logger, log))
    host, f, cfg = base.Host(p, ("Agent", "Task", "SendMessage", "Read")), c.facts, c.cfg
    aid = meta0 = meta1 = lines0 = lines1 = refused = None
    async with c.client(c.options(p, usd=E3P_SESSION_USD, permission_mode="default", can_use_tool=host)) as s:
        await s.turn(PROMPTS["e3_fg"].format(agent="e3-echo", path=target), cfg.turn_s)
        await s.until_idle(cfg.turn_s)
        sid = session_of(s.msgs)
        spawn = [i for tool in ("Agent", "Task") for i, inp, parent in calls(s.msgs, tool)
                 if parent is None and inp.get("subagent_type") == "e3-echo"]
        found = [a for a, m in metas(cfg.config_dir, sid).items() if m.get("agentType") == "e3-echo"]
        found += [r["agent_id"] for r in hook_rows(log) if r.get("agent_type") == "e3-echo" and r.get("agent_id")]
        aid = found[0] if found else None
        meta0, lines0 = read_meta(cfg.config_dir, sid, aid), transcript_lines(cfg.config_dir, sid, aid)
        if aid and lines0 is not None:
            n = len(s.msgs)
            c.open_turn(s.key)
            await s.turn(PROMPTS["e3_send"].format(agent_id=aid), cfg.turn_s)
            await s.until_idle(cfg.turn_s)
            await anyio.sleep(cfg.settle_s)
            lines1, meta1 = transcript_lines(cfg.config_dir, sid, aid), read_meta(cfg.config_dir, sid, aid)
            refused = resume_refused(s.msgs[n:])
    rows = hook_rows(log)
    first: dict[str, dict[str, Any]] = {}
    for r in rows:
        if isinstance(r.get("agent_id"), str):
            first.setdefault(r["agent_id"], r)
    at_first = [r.get("meta_json") for r in first.values()]
    tid0, tid1 = (meta0 or {}).get("toolUseId"), (meta1 or {}).get("toolUseId")
    resumed = lines0 is not None and lines1 is not None and lines1 > lines0
    f.update(e3p_main_mode=init_data(s.msgs).get("permissionMode"), e3p_spawn_calls=len(spawn),
             e3p_spawn_tool_use_id=spawn[0] if spawn else None, e3p_child_found=aid is not None,
             e3p_meta_tid_is_spawn=tid0 == spawn[0] if spawn and isinstance(tid0, str) else None,
             **{"e3p_meta_%s" % k: v for k, v in meta_facts(meta0).items()},
             **{"e3p_meta_after_%s" % k: v for k, v in meta_facts(meta1).items()},
             e3p_child_lines_before=lines0, e3p_child_lines_after=lines1, e3p_resumed=resumed,
             e3p_resume_refused=refused, e3p_send_calls=len(calls(s.msgs, "SendMessage")), e3p_hook_rows=len(rows),
             e3e_children=len(first), e3e_meta_at_first_call=at_first,
             e3e_tid_at_first_call=[r.get("meta_tool_use_id") for r in first.values()])
    c.answers["E3c2a"] = yn(tid1 == tid0 and meta1 is not None) if resumed and not refused and isinstance(tid0, str) \
        else "unknown"
    c.answers["E3e"] = "no" if False in at_first else "yes" if at_first and all(x is True for x in at_first) \
        else "unknown"


def e3d_reading(stopped0: bool, resumed: bool, refused: bool | None, stopped1: bool) -> str:
    """E3d: terminal when the CLI refused to resume the stopped child (SendMessage success false, "was stopped
    by the user and was not resumed") and its transcript did not grow: the stop is final, there is nothing to
    survive; else yes / no by stoppedByUser after a proven resume; unknown otherwise."""
    if not stopped0:
        return "unknown"
    if refused and not resumed:
        return "terminal"
    if resumed and not refused:
        return yn(stopped1)
    return "unknown"


def result_text(content: Any) -> str:
    """A tool result's text (a string, or a list of text blocks), for a fixed-phrase test only: never kept."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(str(b.get("text", "")) if isinstance(b, dict) else str(getattr(b, "text", "")) for b in content)
    return ""


def resume_refused(msgs: list[Any]) -> bool | None:
    """Did the result of a main-thread SendMessage call in `msgs` refuse the resume (RESUME_REFUSED in its text
    or its tool_use_result, and that record's success not true)? None: no such result."""
    ids = {i for i, _, parent in calls(msgs, "SendMessage") if parent is None}
    seen: bool | None = None
    for m in msgs:
        if kind(m) != "UserMessage" or not isinstance(m.content, list):
            continue
        tur = getattr(m, "tool_use_result", None)
        tur = tur if isinstance(tur, dict) else {}
        for b in m.content:
            if kind(b) != "ToolResultBlock" or b.tool_use_id not in ids:
                continue
            text = result_text(b.content) + " " + json.dumps(tur, default=str)
            refused = RESUME_REFUSED in text and tur.get("success") is not True
            seen = refused or bool(seen)
    return seen


# ---------------------------------------------------------------- the registry
OBS_TOUCH = ("the marker that `sh <temp cwd>/e1.sh` (it touches the marker; Bash, main thread the verifier) "
             "creates; sandbox auto-allow off by a settings overlay; the leg's validity: the transcript's agent "
             "setting, Bash in the init tools, the init model")
READ_VALID = "invalid: the leg's (or its control's) main thread was not the verifier with Bash and a recorded model; "
READ_RULE = (READ_VALID + "yes: the marker exists; no: the call was made, no marker; unknown: no such call, a "
             "PreToolUse hook decided it, the session was not in plan, or the control (the same call, no rule) was "
             "not denied")
READ_REPO = (READ_RULE + "; dropped (untrusted): no, and the CLI's stderr had the warning \"%s\"" % TRUST_WARNING)
READ_INSTALLED = (READ_VALID + "yes: the marker exists; no: the call was made, no marker; unknown: no such call, a "
                  "PreToolUse hook decided it, or the session was not in plan (fact control_verdict: the same call, "
                  "overlay on)")
PROBES = [
    Probe("E1", "E1E2", 0.45, 1200, 3, (
        Part("E1a", "Host none + plan + --permission-prompts none (stack_sdk.Session(\"verifier\"), installed stack): "
                    "does a Session allowed_tools Bash(...) allow rule run its command?", OBS_TOUCH, READ_RULE),
        Part("E1bu", "Same, with the Bash(...) allow rule in the repository's .claude/settings.json, the temp "
                     "workspace untrusted?", OBS_TOUCH + "; the CLI's stderr (SDK stderr callback): the trust "
                     "warning, as a boolean", READ_REPO),
        Part("E1bt", "Same, the workspace trusted by CLAUDE_CODE_SANDBOXED=1 in the session's env?",
             OBS_TOUCH + "; its control: the same call, no rule, the same env", READ_REPO),
        Part("E1c", "Same, with the stack's own exact rule %s (user settings)?" % STACK_RULE,
             "the call's tool_use_id in the result's permission_denials (the command writes nothing)",
             READ_VALID + "yes: called, not denied; no: denied; unknown: no such call, a hook decided it, the rule "
             "is not installed, or the control's denial did not show in permission_denials (uncalibrated)"),
        Part("E1d", "Same with no rule at all and the sandbox settings as installed (no overlay): does the command run?",
             "the touch marker, no overlay", READ_INSTALLED)), e1, est_usd=(0.39, 0.56)),
    Probe("E2", "E1E2", 0.60, 900, 4, (
        Part("E2a", "CLAUDE_CODE_SESSION_KIND=bg with CLAUDE_BG_SESSION_PERMISSION_RULES {allow, deny, addDirs} in "
                    "options.env: do the rules take effect in an SDK session?",
             "a bg session and a control (same rules, kind unset), default mode, --permission-prompts none: markers of "
             "an env-allowed and an env-denied (allowed_tools-allowed) touch, and a Read in the env addDir",
             "per rule (facts e2a_*_applied): applied when bg differs from the control in the rule's direction; yes: "
             "any applied; no: all three measured, none applied; unknown: otherwise"),
        Part("E2b", "Is a .claude/agents file created after connect (after the first prompt) loaded before the next "
                    "prompt in the same session (N2's window)?",
             "the second prompt's Agent call for the new type: a task_started of it, or a tool result without error",
             "yes: dispatched; no: the call failed with no task; unknown: no such call"),
        Part("E2c1", "Does the CLI load agents from .claude/agents in a directory above the repository root (layout 1b)?",
             "get_server_info() agents at connect, no prompt; control: the cwd's own .claude/agents",
             "yes: listed; no: not listed; unknown: the control is not listed"),
        Part("E2c2", "Does the CLI load agents from .claude/agents in a subdirectory of an --add-dir (layout 6-subdir)?",
             "get_server_info() agents at connect; control: the add-dir's own .claude/agents",
             "yes: listed; no: not listed; unknown: the control is not listed")), e2, est_usd=(0.11, 0.15)),
    Probe("E3", "E3", 0.40, 1200, 8, (
        Part("E3a", "Main thread in plan mode: does a `context: fork` skill whose `agent:` has permissionMode acceptEdits "
                    "run in that mode (its Write succeeds)?",
             "the fork child's marker in the temp project; every Write that reaches the host is denied",
             "yes: the marker exists; no: the child tried to write (hook row, host or stream), no marker; unknown: no "
             "try seen, or the main thread was not in plan"),
        Part("E3b", "Does a subagent's PreToolUse hook event carry its OWN permission_mode (PR3 saw it through an SDK "
                    "callback; this is a settings command hook)?",
             "a throwaway project PreToolUse hook logs permission_mode, agent_id, agent_type; the child's real mode "
             "from its marker (E3a's child under plan, E3d's under default)",
             "yes: the child rows say acceptEdits where the marker proves it and the caller differs; no: they carry "
             "the caller's mode; unknown: no child rows or the real mode unproven"),
        Part("E3c1", "Does a forked skill child's meta.json toolUseId equal the Skill call's tool_use_id?",
             "<config>/projects/*/<session>/subagents/agent-<id>.meta.json against the main thread's Skill call",
             "yes: equal; no: different or missing; unknown: no meta.json or no Skill call"),
        Part("E3c2", "Does that toolUseId survive a SendMessage resume of the child?",
             "the meta.json re-read after the resume; the resume proven by the child's transcript growing",
             "yes: unchanged; no: changed or gone; unknown: no resume proven, E3c1 unknown, or no toolUseId before the resume"),
        Part("E3d", "Does stoppedByUser in meta.json survive a SendMessage resume after stop_task?",
             "the held child's meta.json after stop_task (PR5b's hold) and after the resume (its transcript grows); "
             "the SendMessage result (a refusal as a boolean)",
             "terminal: the CLI refused the resume (SendMessage success false, \"%s\") and the transcript did not "
             "grow: the stop is final; yes: true after both; no: true after the stop, not after the resume; "
             "unknown: not true after the stop, or neither a resume nor a refusal proven" % RESUME_REFUSED)),
          e3, est_usd=(0.15, 0.20)),
    Probe("E3P", "E3", 0.10, 600, 6, (
        Part("E3c2a", "Does an Agent-spawned child's meta.json toolUseId survive a SendMessage resume (a foreground "
                      "child that finished, then resumed)?",
             "the child's meta.json before and after the resume; the resume proven by its transcript growing",
             "yes: unchanged; no: changed or gone; unknown: no resume proven, the resume refused, or no toolUseId "
             "before the resume"),
        Part("E3e", "Does a child's meta.json exist at its first tool call (agent_guard's plan backstop fails open "
                    "without it)?",
             "the throwaway PreToolUse logger at each child row: meta.json where agent_guard's spawn_meta looks "
             "(meta_json, meta_tool_use_id booleans); each child's first row",
             "yes: every child's first row saw it; no: one did not; unknown: no child row, or no transcript_path "
             "to look from")), e3p, est_usd=(0.04, 0.08)),
]


# ---------------------------------------------------------------- the run, the ledger and the report
@dataclasses.dataclass
class Row:
    probe: Probe
    answers: dict[str, str]
    cap: float
    cost: float = 0.0
    sessions: list[str] = dataclasses.field(default_factory=list)
    transcripts: list[str] = dataclasses.field(default_factory=list)
    facts: dict[str, Any] = dataclasses.field(default_factory=dict)
    seconds: float = 0.0
    status: str = "ran"               # ran | cap_used | refused | error | timeout | skipped
    models: list[str] = dataclasses.field(default_factory=list)    # each session's model, from its init frame


async def run_probes(probes: list[Probe], cfg: Config, helper: Any, rows: list[Row] | None = None,
                     ledger: Callable[[dict[str, Any]], None] | None = None, total: float | None = None) -> list[Row]:
    """Each probe in turn under its cap, its group's envelope and the run's cap `total` (main(): the consent
    value; default TOTAL_CAP_USD), by the reported costs. A probe whose cap is used up ends (cap_used); any other
    BudgetError or an unreported cost stops the run: the rest is skipped. Rows go into `rows` as they finish."""
    validate_registry(probes)
    import anyio
    rows = [] if rows is None else rows
    led = ledger or (lambda ev: None)
    total = TOTAL_CAP_USD if total is None else total
    if isinstance(total, bool) or not isinstance(total, (int, float)) or not 0 < total <= TOTAL_CAP_USD + 1e-9:
        raise BudgetError("the run's cap %r is not in (0, %.2f]" % (total, TOTAL_CAP_USD))
    spent, by, stop = 0.0, Counter(), None
    for p in probes:
        ids = [x.pid for x in p.parts]
        left = min(total - spent, ENVELOPE[p.group] - by[p.group])
        if stop or left < MIN_SESSION_USD:
            rows.append(Row(p, dict.fromkeys(ids, "skipped"), 0.0, facts={"reason": stop or "envelope_used"},
                            status="skipped"))
            continue
        ctx, t0 = Ctx(p, cfg, helper, left, led), time.monotonic()
        led({"ev": "probe", "probe": p.pid, "cap": ctx.cap, "left_total": round(total - spent, 6),
             "left_group": round(ENVELOPE[p.group] - by[p.group], 6)})
        row, fail = Row(p, {}, ctx.cap), None
        try:
            with anyio.fail_after(p.timeout_s):
                await p.fn(ctx)
        except CapUsed:
            fail = "cap_used"
        except BudgetError:
            fail = "refused"
        except TimeoutError:
            fail = "timeout"
        except Exception as e:  # noqa: BLE001 - any probe failure; the type only (a message may quote a prompt)
            fail, ctx.facts["error"] = "error", type(e).__name__
        finally:
            shutil.rmtree(ctx.scratch, ignore_errors=True)
        rest = {"refused": "refused", "error": "error", "cap_used": "skipped"}.get(fail or "", "unknown")
        row.answers = {k: ctx.answers[k] if ctx.answers.get(k) in ANSWERS else rest for k in ids}
        row.status, row.facts = fail or "ran", dict(ctx.facts)
        row.cost, row.sessions, row.seconds = ctx.spent, list(ctx.session_ids), round(time.monotonic() - t0, 1)
        row.models = [ctx.models[k] for k in sorted(ctx.models)]
        row.transcripts = [t for sid in ctx.session_ids for t in ctx.transcripts(sid)]
        row.facts.update(rate_limit_events=ctx.rate_limit_events, sessions_without_result=ctx.unreported,
                         open_tasks_at_close_by_type=dict(sorted(ctx.open_at_close.items())))
        spent += ctx.spent
        by[p.group] += ctx.spent
        led({"ev": "probe_end", "probe": p.pid, "status": row.status, "usd": round(ctx.spent, 6)})
        if ctx.unknown_cost:
            row.facts["cost_unknown"], stop = True, "cost_unknown"
        if fail == "refused":
            stop = stop or "refused"
        rows.append(row)
    return rows


def words(s: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", s.lower()))


def prompt_fragments() -> list[str]:
    """Every prompt and throwaway text (as words(), placeholders as words) and every 32-character window."""
    out = set()
    for p in map(words, [*PROMPTS.values(), LATE_BODY, WRITER_BODY, FORK_BODY, HOLDER_BODY, ECHO_BODY]):
        out.add(p)
        out.update(p[i:i + 32] for i in range(max(0, len(p) - 31)))
    return sorted(out, key=len, reverse=True)


def assert_no_prompt(text: str) -> None:
    flat = words(text)
    if any(frag in flat for frag in prompt_fragments()):
        raise ValueError("the report would contain prompt text")


def render(rows: list[Row], meta: dict[str, Any]) -> str:
    def cell(v: Any) -> str:
        return json.dumps(clean(v)).replace("|", "\\|")

    def esc(s: str) -> str:
        return s.replace("|", "\\|").replace("\n", " ")

    def path_ok(t: str) -> bool:
        return os.path.isabs(t) and t.endswith(".jsonl") and not re.search(r"[\s|`]", t)
    by: Counter[str] = Counter()
    for r in rows:
        by[r.probe.group] += r.cost
    total = meta.get("run_cap", TOTAL_CAP_USD)
    prior = meta.get("prior") or {}
    models = "; ".join("%s %s" % (r.probe.pid, ", ".join("%s x%d" % (clean(m), n) for m, n in Counter(r.models).items())
                                   or "-") for r in rows) or "-"
    out = ["# Agent SDK probes %s, %s" % (", ".join(r.probe.pid for r in rows) or "-", meta["date"]), "",
           "Consent envelope: %s." % CONSENT_TEXT, "",
           "This run's cap (%s): USD %.2f. Prior spend (%s ledgers in the report directory, at worst): USD %s, so "
           "USD %s of the %.2f was left before this run." % (
               CONSENT_ENV, total, cell(prior.get("ledgers")), cell(prior.get("used")), cell(prior.get("left")),
               TOTAL_CAP_USD),
           "",
           "Spent USD %.4f of the run's %.2f: E1+E2 %.4f of %.2f, E3+E3P %.4f of %.2f (CLI estimates; a session "
           "without a reported cost counts at its whole cap) · claude-agent-sdk %s · system CLI %s · main-thread "
           "models (each session's init frame): %s" % (sum(r.cost for r in rows), total, by["E1E2"], ENVELOPE["E1E2"],
                                                       by["E3"], ENVELOPE["E3"], cell(meta.get("sdk")),
                                                       cell(meta.get("system_cli")), models), "",
           "| probe | status | answers | cost USD | cap USD | seconds | sessions | transcripts |",
           "|---|---|---|---:|---:|---:|---|---|"]
    for r in rows:
        out.append("| %s | %s | %s | %.4f | %.2f | %.1f | %s | %s |" % (
            r.probe.pid, r.status, " ".join("%s=%s" % kv for kv in r.answers.items()), r.cost, r.cap, r.seconds,
            " ".join(s for s in r.sessions if base.IDENT.fullmatch(s)) or "-",
            " ".join(t for t in r.transcripts if path_ok(t)) or "-"))
    out += ["", "| part | question | observable | reading | answer |", "|---|---|---|---|---|"]
    for r in rows:
        for part in r.probe.parts:
            out.append("| %s | %s | %s | %s | %s |" % (part.pid, esc(part.question), esc(part.observable),
                                                       esc(part.reading), r.answers.get(part.pid, "unknown")))
    out += ["", "Unverified, read the answers with these in mind:", ""] + ["- " + u for u in UNVERIFIED]
    out += ["", "## Facts", ""]
    for r in rows:
        out.append("- **%s**: %s" % (r.probe.pid, ", ".join(
            "%s=%s" % (clean(str(k)), cell(v)) for k, v in sorted(r.facts.items()))))
    text = "\n".join(out) + "\n"
    assert_no_prompt(text)
    return text


def write_report(path: str, text: str) -> str:
    assert_no_prompt(text)
    return base.write_report(path, text)


def free_path(path: str, suffix: str) -> str:
    stem, n = path.removesuffix(suffix), 1
    while os.path.exists(path):
        n += 1
        path = "%s-%d%s" % (stem, n, suffix)
    return path


class Ledger:
    """<report>.ledger.jsonl, 0600, never overwritten: one cleaned event per line, flushed as the run goes."""

    def __init__(self, path: str):
        self.path = free_path(path, ".ledger.jsonl")
        fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_APPEND, 0o600)
        self.fh = os.fdopen(fd, "a", encoding="utf-8")

    def write(self, ev: dict[str, Any]) -> None:
        self.fh.write(json.dumps(dict(clean(ev), t=round(time.time(), 3))) + "\n")
        self.fh.flush()

    def close(self) -> None:
        self.fh.close()


class LedgerUnreadable(BudgetError):
    """A ledger in the report directory that cannot be replayed: the prior spend is unknown, so the run is
    refused (fail closed)."""


LEDGER_EVENTS = frozenset({"envelope", "probe", "probe_end", "end", "reserve", "cost", "cost_unknown"})


def ledger_spend(path: str) -> dict[str, float]:
    """Replay one ledger as Ctx kept its book: per (probe, session), a reservation books its usd (never lowering
    the booking: an open turn, an unproven or closed session), the first cost after a reservation replaces it
    (the ledger's cost already holds the floor of earlier turns), a later cost never lowers it, a cost_unknown
    books its booked_usd for good. reported: the sessions whose last word is a cost; unreported: those still at a
    reservation; used: their sum, never below the run's own probe_end or end totals."""
    book: dict[tuple[str, str], float] = {}
    reported: dict[tuple[str, str], bool] = {}
    sticky: set[tuple[str, str]] = set()
    ends: dict[str, float] = {}
    end_usd, name = 0.0, os.path.basename(path)
    try:
        with open(path, encoding="utf-8") as fh:
            lines = fh.read().splitlines()
    except (OSError, UnicodeDecodeError) as e:
        raise LedgerUnreadable("%s: unreadable (%s)" % (name, type(e).__name__)) from e
    for n, ln in enumerate(lines, 1):
        if not ln.strip():
            continue
        try:
            ev = json.loads(ln)
        except ValueError as e:
            raise LedgerUnreadable("%s:%d is not JSON" % (name, n)) from e
        what = ev.get("ev") if isinstance(ev, dict) else None
        if what not in LEDGER_EVENTS:
            raise LedgerUnreadable("%s:%d: an event this replay does not know" % (name, n))
        usd = ev.get("booked_usd" if what == "cost_unknown" else "usd")
        if what in ("envelope", "probe"):
            continue
        if not valid_cost(usd):
            raise LedgerUnreadable("%s:%d: %s without a valid amount" % (name, n, what))
        if what == "probe_end":
            ends[str(ev.get("probe"))] = float(usd)
            continue
        if what == "end":
            end_usd = float(usd)
            continue
        key = (str(ev.get("probe")), json.dumps(ev.get("session")))
        if what == "cost" and reported.get(key) is False and key not in sticky:
            book[key] = float(usd)                      # a result replaces its session's reservation
        else:
            book[key] = max(book.get(key, 0.0), float(usd))
        if what == "cost_unknown":
            sticky.add(key)
        reported[key] = what == "cost" and key not in sticky
    rep = sum(v for k, v in book.items() if reported.get(k))
    unrep = sum(v for k, v in book.items() if not reported.get(k))
    return {"reported": rep, "unreported": unrep, "used": max(rep + unrep, sum(ends.values()), end_usd)}


def ledger_dirs(out: str | None, today: str) -> list[str]:
    """Where earlier runs' ledgers are: the report's directory and the default one, each once."""
    dirs = [os.path.dirname(base.default_out(today + "-e"))] + ([os.path.dirname(out)] if out else [])
    seen, keep = set(), []
    for d in dirs:
        r = os.path.realpath(d)
        if r not in seen:
            seen.add(r)
            keep.append(d)
    return keep


def prior_spend(dirs: list[str]) -> dict[str, Any]:
    """Every <name>.ledger.jsonl in `dirs` (each file once), replayed: what the earlier runs used at worst and
    what is left of the $2.00. Raises LedgerUnreadable for any ledger it cannot replay."""
    files, seen = [], set()
    for d in dirs:
        for p in sorted(glob.glob(os.path.join(glob.escape(d), LEDGER_GLOB))):
            if os.path.realpath(p) not in seen:
                seen.add(os.path.realpath(p))
                files.append(p)
    spend = [ledger_spend(p) for p in files]
    used = sum(s["used"] for s in spend)
    return {"ledgers": len(files), "reported": round(sum(s["reported"] for s in spend), 6),
            "unreported": round(sum(s["unreported"] for s in spend), 6), "used": round(used, 6),
            "left": round(TOTAL_CAP_USD - used, 6)}


def prior_line(prior: dict[str, Any]) -> str:
    return ("prior spend: %d ledgers, reported USD %.4f + booked at cap without a report USD %.4f = USD %.4f at "
            "worst; left of the %.2f: USD %.4f" % (prior["ledgers"], prior["reported"], prior["unreported"],
                                                    prior["used"], TOTAL_CAP_USD, prior["left"]))


def envelope_event(probes: list[Probe], today: str, prior: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"ev": "envelope", "date": today, "total_usd": TOTAL_CAP_USD, "groups_usd": dict(ENVELOPE),
            "caps_usd": {p.pid: p.budget_usd for p in probes}, "consent_env": CONSENT_ENV,
            "consent_value": consent_value(probes), "run_cap_usd": run_cap(probes), "flag": "--paid",
            "probes": [p.pid for p in probes], "model": MODEL, "e1_agent": E1_AGENT,
            "prior": {k: v for k, v in (prior or {}).items()
                      if k in ("ledgers", "reported", "unreported", "used", "left")}}


def print_plan(probes: list[Probe], consent: str | None, prior: dict[str, Any] | str) -> None:
    need, cap = consent_value(probes), run_cap(probes)
    print("DRY RUN: no call is made, $0.")
    print("Consent envelope: %s." % CONSENT_TEXT)
    print("%-4s %-6s %-11s %-5s %-9s %-8s %s" % ("id", "cap", "est.", "group", "max_turns", "timeout", "main thread"))
    for p in probes:
        print("%-4s $%.2f  $%.2f-%.2f  %-5s %-9d %-8s %s" % (
            p.pid, p.budget_usd, p.est_usd[0], p.est_usd[1], p.group, p.max_turns, "%ds" % p.timeout_s,
            "%s (its own model, sonnet)" % E1_AGENT if p.pid == "E1" else "model %s" % MODEL))
        for part in p.parts:
            print("     %-6s %s" % (part.pid, part.question))
    by: Counter[str] = Counter()
    for p in probes:
        by[p.group] += p.budget_usd
    print("caps: %s; this run's cap %.2f (consent value %s); expected %.2f-%.2f" % (
        ", ".join("%s %.2f of %.2f" % (g, by[g], ENVELOPE[g]) for g in ENVELOPE), cap, need,
        sum(p.est_usd[0] for p in probes), sum(p.est_usd[1] for p in probes)))
    print("worst case: the run's cap (%.2f) plus at most one turn over each session's cap (the CLI checks after each "
          "turn); no session starts whose cap would take the reported spend past its group or the run's cap" % cap)
    if isinstance(prior, str):
        print("prior spend: unreadable (%s): a paid run would be refused" % prior)
    else:
        print(prior_line(prior))
        print("a paid run of this selection would %s (prior %.4f + cap %.2f %s %.2f)" % (
            "START" if prior["used"] + cap <= TOTAL_CAP_USD + 1e-9 else "be REFUSED", prior["used"], cap,
            "<=" if prior["used"] + cap <= TOTAL_CAP_USD + 1e-9 else ">", TOTAL_CAP_USD))
    if consent is not None:
        print("%s is set, but without --paid this is a dry run." % CONSENT_ENV)
    print("paid run: %s=%s uv run --locked --script tests/sdk_probes_e.py --paid --only %s" % (
        CONSENT_ENV, need, ",".join(p.pid for p in probes)))
    print("E1 needs the v2 stack_sdk.py installed (%s); E2, E3 and E3P need only options()." % ", ".join(E1_NEEDS))
    print("unverified, read the answers with these in mind:")
    for u in UNVERIFIED:
        print("  - " + u)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Agent SDK probes E1-E3 and E3P (billed; run by the user).",
        epilog="Consent: %s must equal the run's own cap, the sum of the selected probes' caps as %%.2f (E1,E3P: "
               "0.55); only a run with all of E1, E2 and E3 selected keeps the first run's value %s. A paid run is "
               "refused when the ledgers already in the report directory (replayed at worst) plus its cap exceed "
               "$%.2f." % (CONSENT_ENV, CONSENT_VALUE, TOTAL_CAP_USD))
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="print the plan, spend nothing (the default)")
    mode.add_argument("--paid", action="store_true", help="make the billed calls; needs %s=<the run's cap> too" %
                      CONSENT_ENV)
    ap.add_argument("--only", default="", help="comma-separated probe ids, e.g. E1,E3P (default: all)")
    # no --config: the CLI's own (CLAUDE_CONFIG_DIR, else ~/.claude); exporting another would also rename the
    # keychain entry the CLI looks the login up in
    ap.add_argument("--cli", default=shutil.which("claude"), help="the installed claude (default: PATH)")
    ap.add_argument("--out", help="report path (default <main checkout>/.claude-work/sdk/probes/<date>-e.md)")
    a = ap.parse_args(argv)
    only = {x.strip().upper() for x in a.only.split(",") if x.strip()}
    if only - {p.pid for p in PROBES}:
        ap.error("unknown probe ids: %s" % ", ".join(sorted(only - {p.pid for p in PROBES})))
    probes = [p for p in PROBES if not only or p.pid in only]
    validate_registry(probes)
    consent, need, cap = os.environ.get(CONSENT_ENV), consent_value(probes), run_cap(probes)
    today = datetime.date.today().isoformat()
    out = os.path.abspath(os.path.expanduser(a.out)) if a.out else base.default_out(today + "-e")
    if not a.paid:
        try:
            prior: dict[str, Any] | str = prior_spend(ledger_dirs(out, today))
        except LedgerUnreadable as e:
            prior = str(e)
        print_plan(probes, consent, prior)
        return 0
    if consent != need:
        ap.error("a paid run of %s needs %s=%s (this run's cap) in the environment as well as --paid (%s)" % (
            ",".join(p.pid for p in probes), CONSENT_ENV, need, CONSENT_TEXT))
    if (v := base.versions(None)["sdk"]) != SDK_PIN:
        ap.error("claude-agent-sdk %s is not the pinned %s: uv run --locked --script %s" % (v, SDK_PIN, __file__))
    if not a.cli:
        ap.error("no `claude` on PATH: pass --cli /path/to/claude (Q3: the installed CLI)")
    config = os.path.expanduser(os.environ.get("CLAUDE_CONFIG_DIR") or "~/.claude")
    helper = base.load_helper(config)          # once, before the ledger: E1 needs the v2 helper (SDK-2)
    need_names = ("options",) + (E1_NEEDS if any(p.pid == "E1" for p in probes) else ())
    if missing := [n for n in need_names if not hasattr(helper, n)]:
        ap.error("the installed %s/bin/stack_sdk.py lacks %s: reinstall the stack (./install.sh) or run "
                 "--only E2,E3,E3P (they need only options())" % (config, ", ".join(missing)))
    try:                                       # the cross-run check: before the ledger, before any billed call
        prior = prior_spend(ledger_dirs(out, today))
    except LedgerUnreadable as e:
        ap.error("refused: a ledger in the report directory cannot be replayed, so the prior spend is unknown: %s" % e)
    print(prior_line(prior))
    if prior["used"] + cap > TOTAL_CAP_USD + 1e-9:
        ap.error("refused: the prior spend USD %.4f plus this run's cap USD %.2f exceeds the USD %.2f consent "
                 "(left: USD %.4f)" % (prior["used"], cap, TOTAL_CAP_USD, prior["left"]))
    try:                                       # before any billed call, not after
        os.makedirs(os.path.dirname(out), mode=0o700, exist_ok=True)
        if not os.access(os.path.dirname(out), os.W_OK):
            raise PermissionError("not writable")
        ledger = Ledger(out[:-3] + ".ledger.jsonl" if out.endswith(".md") else out + ".ledger.jsonl")
    except OSError as e:
        ap.error("cannot write the report or its ledger beside %s: %s" % (out, e.strerror or e))
    ledger.write(envelope_event(probes, today, prior))
    print("Consent envelope: %s. This run's cap: USD %.2f. Ledger: %s" % (CONSENT_TEXT, cap, ledger.path))
    cfg = Config(config_dir=config, cli_path=a.cli)
    rows: list[Row] = []
    try:
        asyncio.run(run_probes(probes, cfg, helper, rows, ledger.write, total=cap))
    finally:                                   # Ctrl-C or a crash: the finished probes are still reported
        ledger.write({"ev": "end", "usd": round(sum(r.cost for r in rows), 6),
                      "probes": {r.probe.pid: r.status for r in rows}})
        ledger.close()
        print(write_report(out, render(rows, dict(base.versions(a.cli), date=today, run_cap=cap, prior=prior))))
        for r in rows:
            print("%-4s %-8s $%.4f  %s" % (r.probe.pid, r.status, r.cost,
                                           " ".join("%s=%s" % kv for kv in r.answers.items())))
    return 1 if any(r.status in ("error", "refused") for r in rows) else 0


if __name__ == "__main__":
    sys.exit(main())
