#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["claude-agent-sdk==0.2.163"]
# [tool.uv]
# exclude-newer = "2026-10-01T00:00:00Z"
# ///
"""Agent SDK probes PR1-PR13 (work package SDK-1) against the INSTALLED stack. They make real, billed
API calls, so the user runs them: never pytest (no test_ prefix), never an agent. Hash-locked by
tests/sdk_probes.py.lock (`uv lock --script tests/sdk_probes.py`).

    uv run --locked --script tests/sdk_probes.py                 # the plan: probes, caps, total ($0)
    uv run --locked --script tests/sdk_probes.py --run [--only PR1,PR4] [--cli PATH] [--out FILE]

Every probe has its own cap (max_budget_usd): nine at $0.50, the four that spawn children (PR3, PR5,
PR7, PR10) at $1.50, total <= $10.50. A probe's sessions share its cap: each session gets at most what
the probe has left, and no session starts without a positive cap within it. The run stops starting
probes once the total cap is used up. The CLI checks a cap after each turn, so one turn can overshoot;
total_cost_usd is the CLI's client-side estimate.

Sessions use the installed `claude` (--cli, default the one on PATH; PR9 also runs the SDK's bundled
CLI), the stack's own files (<config>/bin/stack_sdk.py options(): user/project/local settings, an agent
as main thread) and a fresh scratch directory per probe as cwd. The probes' permission host
(can_use_tool) allows only what each probe names, never persists a rule, and denies everything else
that reaches it; what the user's settings already allow never reaches it, so every session also gets
a settings overlay with sandbox.autoAllowBashIfSandboxed false (sandboxed Bash would otherwise run
without asking), strict_mcp_config (no MCP server from the user's or a project's config is loaded),
and disallows WebSearch, WebFetch, the image-studio server and every mcp__ rule in the permissions.allow
of <config>/settings.json and settings.local.json (spend outside max_budget_usd). A session that ends
without a result, or is closed while an agent task (local_agent, local_workflow: the SDK's
DEFERRING_TASK_TYPES) still runs, is counted at its whole cap; a background shell left running is not
(fact open_tasks_at_close_by_type).

The report (default <main checkout>/.claude-work/sdk/probes/<date>.md) holds per probe the question,
yes / no / unknown / error / skipped / refused, cost, cap, session ids, transcript paths and measured
facts (numbers, booleans, ids, versions, tool and event names). No prompt, reply, tool input or error
text is written: every string fact must look like an identifier, and the finished text is checked
against every prompt before it is written.
"""
from __future__ import annotations

import argparse
import asyncio
import contextlib
import dataclasses
import datetime
import glob
import importlib.util
import itertools
import json
import math
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from collections import Counter
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

SDK_PIN = "0.2.163"
SMALL_USD, LARGE_USD, TOTAL_CAP_USD = 0.50, 1.50, 10.50
LARGE = frozenset({"PR3", "PR5", "PR7", "PR10"})        # the probes that spawn children
TERMINAL = frozenset({"completed", "failed", "stopped", "killed"})
# the task types whose end the SDK waits for (claude_agent_sdk/_internal/query.py DEFERRING_TASK_TYPES,
# 0.2.163): agent work, not background shells or monitors, which may run for good
AGENT_TASKS = frozenset({"local_agent", "local_workflow"})
FILE_TOOLS = frozenset({"Read", "Write", "Edit", "MultiEdit", "Glob", "Grep", "LS", "NotebookEdit"})
# every session: what user allow rules would otherwise approve without asking the host
SETTINGS_OVERLAY = json.dumps({"sandbox": {"autoAllowBashIfSandboxed": False}})
DISALLOWED = ("WebSearch", "WebFetch", "mcp__image-studio")


def allowed_mcp(config_dir: str) -> list[str]:
    """The mcp__ rules in permissions.allow of <config>/settings.json and settings.local.json: decided
    before can_use_tool, so each is disallowed in the probes' sessions."""
    out: set[str] = set()
    for name in ("settings.json", "settings.local.json"):
        try:
            with open(os.path.join(config_dir, name), encoding="utf-8") as fh:
                allow = (json.load(fh).get("permissions") or {}).get("allow") or []
        except (OSError, ValueError, AttributeError):
            continue
        out.update(a for a in allow if isinstance(a, str) and a.startswith("mcp__"))
    return sorted(out)
IDENT = re.compile(r"[A-Za-z0-9_.:/@+=-]{0,200}")        # what a string fact may look like
WITHHELD = "<withheld>"

PROMPTS = {
    "ok": "Reply with exactly: ok",
    "ask": ("Call the AskUserQuestion tool once, now, with one question 'Which colour?' and the two "
            "options red and blue. Then reply with only the chosen colour. Do not plan or delegate."),
    "plan": ("Plan, then have one builder create the file hello.txt in the current directory "
             "containing the single word hi. Keep the plan to one step."),
    "stop": ("Dispatch exactly one coder subagent whose only task is to run the Bash command `true` "
             "once and reply done. Then wait for it."),
    "count": "Count from 1 to 400, one number per line, with no other text.",
    "bg": ("Dispatch exactly one coder subagent in the background whose only task is to run the Bash "
           "command `sleep 110` and then reply done. End your turn right after dispatching it."),
    "report": "The task is finished: report status done with result ok, no files and no next step.",
    "tree": ("Dispatch exactly one orchestrator subagent whose only task is to dispatch one explore "
             "subagent that lists the files in the current directory, and to relay its answer."),
}
REPORT_SCHEMA = {"type": "object", "required": ["status", "result"],
                 "properties": {"status": {"type": "string", "enum": ["done", "partial", "blocked"]},
                                "result": {"type": "string"}, "evidence": {"type": "string"},
                                "files": {"type": "array", "items": {"type": "string"}},
                                "next": {"type": "string"}}}


class BudgetError(RuntimeError):
    """A session without a positive cap within its probe's: nothing is sent and the run stops."""


@dataclasses.dataclass(frozen=True)
class Outcome:
    answer: str                       # yes | no | unknown
    facts: dict[str, Any]


@dataclasses.dataclass(frozen=True)
class Probe:
    pid: str
    question: str
    budget_usd: float | None
    timeout_s: float
    fn: Callable[[Ctx], Awaitable[Outcome]]


@dataclasses.dataclass
class Config:
    config_dir: str                   # the installed stack (CLAUDE_CONFIG_DIR, ~/.claude)
    cli_path: str | None              # Q3: the user's installed claude
    state_dir: str                    # $XDG_STATE_HOME/claude-agent-stack (guard and usage state)
    transport_factory: Callable[[Any], Any] | None = None   # tests: a fake Transport per session
    killer: Callable[[int, int], None] = os.kill
    bg_ceiling_ms: int = 2_000        # PR7: CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS (the 2026-10-09 child
                                      # ended 7.4 s after the first result: a 30 s ceiling never acted)
    settle_s: float = 5.0             # wait for hook side effects (SessionEnd marker, lease release)
    hold_s: float = 45.0              # PR5: the longest the host parks the child's Bash request
    wait_s: float = 60.0              # PR5: each wait (child parked, terminal status, closing result)


def validate_registry(probes: list[Probe]) -> None:
    """Every probe has its own cap (the LARGE ones $1.50, the rest $0.50); the caps sum to <= $10.50."""
    ids = [p.pid for p in probes]
    if len(set(ids)) != len(ids):
        raise BudgetError("duplicate probe ids")
    for p in probes:
        b, want = p.budget_usd, LARGE_USD if p.pid in LARGE else SMALL_USD
        if isinstance(b, bool) or not isinstance(b, (int, float)) or not 0 < b <= want:
            raise BudgetError("%s: cap %r is not in (0, %.2f]" % (p.pid, b, want))
    if sum(p.budget_usd or 0 for p in probes) > TOTAL_CAP_USD + 1e-9:
        raise BudgetError("caps sum above %.2f" % TOTAL_CAP_USD)


# ---------------------------------------------------------------- reading the stream (names only)
def kind(m: Any) -> str:
    return type(m).__name__


def is_result(m: Any) -> bool:
    return kind(m) == "ResultMessage"


def result_of(msgs: list[Any]) -> Any:
    return next((m for m in reversed(msgs) if is_result(m)), None)


def init_data(msgs: list[Any]) -> dict[str, Any]:
    m = next((m for m in msgs if kind(m) == "SystemMessage" and getattr(m, "subtype", "") == "init"), None)
    return dict(m.data) if m is not None and isinstance(m.data, dict) else {}


def session_of(msgs: list[Any]) -> str | None:
    r = result_of(msgs)
    return r.session_id if r is not None else init_data(msgs).get("session_id")


def hook_events(msgs: list[Any]) -> dict[str, int]:
    return dict(Counter(m.hook_event_name for m in msgs if kind(m) == "HookEventMessage"))


def tool_uses(msgs: list[Any]) -> list[tuple[str, str, str | None]]:
    """(tool name, tool_use id, parent_tool_use_id) of every assistant tool call."""
    return [(b.name, b.id, m.parent_tool_use_id) for m in msgs if kind(m) == "AssistantMessage"
            for b in m.content if kind(b) == "ToolUseBlock"]


def task_status(m: Any) -> str | None:
    """The status a task message reports: TaskNotification.status or TaskUpdated.patch.status."""
    return getattr(m, "status", None) or (getattr(m, "patch", None) or {}).get("status")


def task_states(msgs: list[Any]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for m in msgs:
        k = kind(m)
        if k not in ("TaskStartedMessage", "TaskNotificationMessage", "TaskUpdatedMessage"):
            continue
        t = out.setdefault(m.task_id, {"tool_use_id": None, "type": None, "task_type": None, "status": "running"})
        t["tool_use_id"] = getattr(m, "tool_use_id", None) or t["tool_use_id"]
        if k == "TaskStartedMessage":
            label = re.match(r"([\w-]+): ", m.description or "")
            t.update(type=label and label.group(1), task_type=m.task_type)
        t["status"] = task_status(m) or t["status"]
    return out


def open_tasks(msgs: list[Any]) -> Counter[str]:
    """Tasks not yet terminal, by task_type (any type: shells and monitors too)."""
    return Counter(str(t["task_type"] or "unknown") for t in task_states(msgs).values()
                   if t["status"] not in TERMINAL)


def agents_running(msgs: list[Any]) -> bool:
    """An agent task (AGENT_TASKS) is still running: a background shell does not count."""
    return any(t["status"] not in TERMINAL and t["task_type"] in AGENT_TASKS for t in task_states(msgs).values())


def tokens(model_usage: Any) -> dict[str, int]:
    t: Counter[str] = Counter()
    for u in (model_usage or {}).values():
        for k in ("inputTokens", "cacheCreationInputTokens", "cacheReadInputTokens", "outputTokens"):
            t[k] += int(u.get(k) or 0)
    return dict(t)


def names_in(obj: Any, names: set[str]) -> int:
    """How many of `names` occur as a whole string value anywhere in obj."""
    found, todo = set(), [obj]
    while todo:
        o = todo.pop()
        if isinstance(o, str) and o in names:
            found.add(o)
        elif isinstance(o, dict):
            todo += list(o.values())
        elif isinstance(o, (list, tuple)):
            todo += list(o)
    return len(found)


def yn(cond: bool | None) -> str:
    return "unknown" if cond is None else "yes" if cond else "no"


# ---------------------------------------------------------------- the probes' host and observer hook
class Host:
    """can_use_tool for the probes: allows only the tools in `allow` (file tools inside the scratch dir,
    Glob only with a relative pattern, Bash only `sleep N`; AskUserQuestion, when allowed, answered
    with each question's first option); denies the rest. Never returns updated_permissions, so no rule
    is ever persisted. Records tool names only."""

    def __init__(self, scratch: str, allow: tuple[str, ...] = ()):
        self.scratch, self.allow, self.seen = os.path.realpath(scratch), frozenset(allow), []

    def _ok(self, tool: str, inp: dict[str, Any]) -> bool:
        if tool not in self.allow:
            return False
        if tool == "Bash":
            return re.fullmatch(r"sleep \d{1,3}", str(inp.get("command") or "").strip()) is not None
        if tool == "Glob":
            pattern = str(inp.get("pattern") or "")
            if os.path.isabs(pattern) or pattern.startswith("~") or ".." in pattern:
                return False
        if tool in FILE_TOOLS:
            p = inp.get("file_path") or inp.get("path") or inp.get("notebook_path") or self.scratch
            p = os.path.realpath(os.path.join(self.scratch, str(p)))
            return p == self.scratch or p.startswith(self.scratch + os.sep)
        return True

    async def __call__(self, tool: str, inp: dict[str, Any], context: Any) -> Any:
        from claude_agent_sdk import PermissionResultAllow, PermissionResultDeny
        self.seen.append(tool)
        if tool == "AskUserQuestion" and tool in self.allow:
            answers = {str(q.get("question", "")): str(((q.get("options") or [{}])[0]).get("label", ""))
                       for q in inp.get("questions") or [] if isinstance(q, dict)}
            return PermissionResultAllow(updated_input=dict(inp, answers=answers))
        if self._ok(tool, inp):
            return PermissionResultAllow()
        return PermissionResultDeny(message="denied by the probe host")


class HoldHost:
    """can_use_tool for PR5: allows Agent and Task; parks the first Bash request of a subagent
    (records `pending`, waits for `release` at most `hold_s`) and then denies it; denies everything
    else at once. The parked request keeps the child alive whatever the CLI lets a command do (CLI
    2.1.287 blocked a standalone `sleep 110`, so a sleeping child ended on its own). Never returns
    updated_permissions. Records tool names only."""

    def __init__(self, hold_s: float):
        import anyio
        self.hold_s, self.release, self.seen = hold_s, anyio.Event(), []
        self.pending, self.pending_agent, self.released_by = False, None, None

    async def __call__(self, tool: str, inp: dict[str, Any], context: Any) -> Any:
        import anyio
        from claude_agent_sdk import PermissionResultAllow, PermissionResultDeny
        self.seen.append(tool)
        if tool in ("Agent", "Task"):
            return PermissionResultAllow()      # HoldHost: dispatching only
        agent = getattr(context, "agent_id", None)
        if tool == "Bash" and agent and not self.pending:
            self.pending, self.pending_agent, self.released_by = True, agent, "cancelled"
            with anyio.move_on_after(self.hold_s) as scope:
                await self.release.wait()
            self.released_by = "timeout" if scope.cancelled_caught else "event"
        return PermissionResultDeny(message="denied by the probe host")


def observer(log: list[tuple[bool, Any]]) -> dict[str, list[Any]]:
    """The neutral PreToolUse hook (the Python can_use_tool workaround): records (in a subagent?,
    permission_mode) and returns only {"continue_": True}, never a decision."""
    from claude_agent_sdk import HookMatcher
    from claude_agent_sdk.types import SyncHookJSONOutput

    async def hook(inp: Any, tool_use_id: Any, context: Any) -> SyncHookJSONOutput:
        log.append((bool(inp.get("agent_id")), inp.get("permission_mode")))
        return {"continue_": True}
    return {"PreToolUse": [HookMatcher(matcher=None, hooks=[hook])]}


# ---------------------------------------------------------------- per-probe context
class Session:
    def __init__(self, ctx: Ctx, client: Any):
        self.ctx, self.c, self.msgs, self.killed, self._it = ctx, client, [], False, None
        self.key = next(ctx.keys)

    async def next(self) -> Any:
        if self._it is None:
            self._it = self.c.receive_messages().__aiter__()
        m = await self._it.__anext__()
        self.ctx.note(self.key, m)
        self.msgs.append(m)
        return m

    async def wait_for(self, pred: Callable[[Any], bool], timeout: float) -> Any:
        import anyio
        with anyio.move_on_after(timeout):
            try:
                while True:
                    m = await self.next()
                    if pred(m):
                        return m
            except StopAsyncIteration:
                return None
        self._it = None                  # a cancelled generator is finished; the next read opens one
        return None

    async def drain(self) -> None:
        """Read every message into self.msgs until the stream ends or the task is cancelled (PR5's
        reader: the SDK buffers 100 messages, and the probe polls instead of reading)."""
        try:
            while True:
                await self.next()
        except StopAsyncIteration:
            pass
        finally:
            self._it = None

    async def turn(self, prompt: str, timeout: float) -> list[Any]:
        n = len(self.msgs)
        await self.c.query(prompt)
        await self.wait_for(is_result, timeout)
        return self.msgs[n:]

    async def until_idle(self, timeout: float) -> list[Any]:
        """Read on until no started task is still running and the last message is a result."""
        n = len(self.msgs)
        if agents_running(self.msgs) or not (self.msgs and is_result(self.msgs[-1])):
            await self.wait_for(lambda m: is_result(m) and not agents_running(self.msgs), timeout)
        return self.msgs[n:]


class Ctx:
    def __init__(self, probe: Probe, cfg: Config, helper: Any, cap_left: float):
        self.probe, self.cfg, self.helper = probe, cfg, helper
        self.cap = min(float(probe.budget_usd or 0), cap_left)
        self.costs: dict[int, float] = {}
        self.session_ids: list[str] = []
        self.rate_limit_events = 0
        self.open_at_close: Counter[str] = Counter()  # tasks still open when a session closed, by type
        self.keys = itertools.count()             # one cost entry per session
        self.reported: set[int] = set()           # sessions that have sent a result
        self.scratch = tempfile.mkdtemp(prefix="sdk-probe-%s-" % probe.pid.lower())

    @property
    def spent(self) -> float:
        return sum(self.costs.values())

    def options(self, agent: str | None = "blackcat", share: float = 1.0, **kw: Any) -> Any:
        """The stack's options (the installed stack_sdk.options) under this probe's cap: at most what
        the probe has left, and at most `share` of its cap."""
        # rounded down to 1/10000 USD: rounding to nearest could exceed what is left (check() refuses)
        budget = math.floor(min(self.cap - self.spent, self.cap * share) * 10_000 + 1e-5) / 10_000
        if not budget > 0:
            raise BudgetError("%s: no cap left for another session" % self.probe.pid)
        kw.setdefault("cli_path", self.cfg.cli_path)
        kw.setdefault("max_turns", 8)
        kw.setdefault("settings", SETTINGS_OVERLAY)
        kw.setdefault("strict_mcp_config", True)
        kw["disallowed_tools"] = [*DISALLOWED, *allowed_mcp(self.cfg.config_dir), *kw.get("disallowed_tools", ())]
        return self.helper.options(agent, budget_usd=budget, cwd=self.scratch, **kw)

    def check(self, opts: Any) -> None:
        b, left = getattr(opts, "max_budget_usd", None), self.cap - self.spent
        if isinstance(b, bool) or not isinstance(b, (int, float)) or not 0 < b <= left + 1e-9:
            raise BudgetError("%s: session cap %r outside (0, %.4f]" % (self.probe.pid, b, left))

    def _transport(self, opts: Any) -> Any:
        return self.cfg.transport_factory(opts) if self.cfg.transport_factory else None

    def reserve(self, key: int, opts: Any) -> None:
        """A session counts at its whole cap until its first result reports the real cost."""
        self.check(opts)
        self.costs[key] = float(opts.max_budget_usd)

    def settle(self, key: int, msgs: list[Any], opts: Any) -> None:
        """Closed while an agent task still runs: what it spends after the last result is not
        reported, so the session counts at its whole cap. A shell or monitor task costs no tokens
        of its own: it is only recorded (open_at_close)."""
        self.open_at_close.update(open_tasks(msgs))
        if agents_running(msgs):
            self.costs[key] = max(self.costs.get(key, 0.0), float(opts.max_budget_usd))
            self.reported.discard(key)

    @property
    def unreported(self) -> int:
        return len(set(self.costs) - self.reported)

    def note(self, key: int, m: Any) -> None:
        if is_result(m):            # the first result replaces the reservation; cumulative after that
            cost = float(m.total_cost_usd or 0)
            self.costs[key] = max(self.costs.get(key, 0.0), cost) if key in self.reported else cost
            self.reported.add(key)
        elif kind(m) == "RateLimitEvent":
            self.rate_limit_events += 1
        sid = getattr(m, "session_id", None)
        if kind(m) == "SystemMessage" and isinstance(getattr(m, "data", None), dict):
            sid = m.data.get("session_id") or sid
        if isinstance(sid, str) and re.fullmatch(r"[\w-]{8,80}", sid) and sid not in self.session_ids:
            self.session_ids.append(sid)

    @contextlib.asynccontextmanager
    async def client(self, opts: Any) -> AsyncIterator[Session]:
        self.check(opts)
        from claude_agent_sdk import ClaudeSDKClient
        c = ClaudeSDKClient(opts, transport=self._transport(opts))
        s = Session(self, c)
        self.reserve(s.key, opts)
        await c.connect()
        try:
            yield s
        finally:
            self.settle(s.key, s.msgs, opts)
            try:
                await c.disconnect()
            except Exception:
                if not s.killed:
                    raise

    async def one_shot(self, prompt: str, opts: Any) -> list[tuple[float, Any]]:
        """query(), the SDK's single-message mode: (monotonic time, message) pairs."""
        self.check(opts)
        from claude_agent_sdk import query
        key, out = next(self.keys), []
        self.reserve(key, opts)
        try:
            async for m in query(prompt=prompt, options=opts, transport=self._transport(opts)):
                self.note(key, m)
                out.append((time.monotonic(), m))
        finally:
            self.settle(key, [m for _, m in out], opts)
        return out

    def kill(self, s: Session) -> bool:
        pid = getattr(getattr(getattr(s.c, "_transport", None), "_process", None), "pid", None)
        if not isinstance(pid, int) or pid <= 0:
            return False
        s.killed = True
        self.cfg.killer(pid, signal.SIGKILL)
        return True

    def stack_agents(self) -> set[str]:
        return {os.path.basename(p)[:-3] for p in glob.glob(os.path.join(self.cfg.config_dir, "agents", "*.md"))}

    def guard_dir(self, sid: str) -> str:
        return os.path.join(self.cfg.state_dir, sid)

    def leases(self, sid: str) -> list[str]:
        return sorted(p for p in glob.glob(os.path.join(self.guard_dir(sid), "fanout", "*", "*.json"))
                      if not os.path.basename(p).startswith("resume-"))

    def registry(self, sid: str, tool_use_id: str | None) -> dict[str, Any] | None:
        """The guard's registry record (<state>/<session>/agents/<agent id>.json) of the child that
        the Agent call `tool_use_id` spawned. Under the SDK a BlackCat dispatch runs in the
        background (agent_guard drops run_in_background false), so the child lives here, with its
        bg and stopped fields, and its spawn lease is gone once the launch returns."""
        if not tool_use_id:
            return None
        for p in sorted(glob.glob(os.path.join(self.guard_dir(sid), "agents", "*.json"))):
            try:
                with open(p, encoding="utf-8") as fh:
                    rec = json.load(fh)
            except (OSError, ValueError):
                continue
            if isinstance(rec, dict) and rec.get("tool_use_id") == tool_use_id:
                return rec
        return None

    def transcripts(self, sid: str) -> list[str]:
        return sorted(glob.glob(os.path.join(self.cfg.config_dir, "projects", "*", sid + ".jsonl")))


# ---------------------------------------------------------------- PR1-PR13
async def pr1(c: Ctx) -> Outcome:
    async with c.client(c.options(include_hook_events=True, max_turns=2)) as s:
        info = await s.c.get_server_info() or {}
        msgs = await s.turn(PROMPTS["ok"], 180)
    init, names, hooks = init_data(msgs), c.stack_agents(), hook_events(msgs)
    f = {"server_info_keys": sorted(info)[:40] if isinstance(info, dict) else None,
         "init_keys": sorted(init)[:60], "hook_events": hooks, "session_start_hook_seen": "SessionStart" in hooks,
         "stack_agents_installed": len(names), "stack_agents_in_server_info": names_in(info, names),
         "stack_agents_in_init": names_in(init.get("agents"), names)}
    loaded = f["stack_agents_in_server_info"] > 0 or f["stack_agents_in_init"] > 0
    return Outcome(yn(f["session_start_hook_seen"] and loaded), f)


async def pr2(c: Ctx) -> Outcome:
    f: dict[str, Any] = {}
    for label, with_hook in (("with_hook", True), ("without_hook", False)):
        host, log = Host(c.scratch, ("AskUserQuestion",)), []
        kw: dict[str, Any] = {"can_use_tool": host, "max_turns": 4, "share": 0.5}
        if with_hook:
            kw["hooks"] = observer(log)
        async with c.client(c.options(**kw)) as s:
            await s.turn(PROMPTS["ask"], 240)
        f[label + "_ask_reached_callback"] = "AskUserQuestion" in host.seen
        f[label + "_callback_tools"] = sorted(set(host.seen))
        if with_hook:
            f["observer_calls"] = len(log)
    f["hook_still_needed"] = f["with_hook_ask_reached_callback"] and not f["without_hook_ask_reached_callback"]
    return Outcome(yn(f["with_hook_ask_reached_callback"]), f)


async def pr3(c: Ctx) -> Outcome:
    host, log = Host(c.scratch, ("ExitPlanMode", "Agent", "Task", *sorted(FILE_TOOLS))), []
    o = c.options(permission_mode="plan", can_use_tool=host, hooks=observer(log), max_turns=12)
    async with c.client(o) as s:
        await s.turn(PROMPTS["plan"], 600)
        await s.until_idle(600)
    tasks = task_states(s.msgs)
    f = {"exit_plan_reached_callback": "ExitPlanMode" in host.seen, "callback_tools": sorted(set(host.seen)),
         "modes_main": list(dict.fromkeys(m for sub, m in log if not sub)),
         "modes_children": list(dict.fromkeys(m for sub, m in log if sub)),
         "tasks_started": len(tasks), "task_types": sorted({t["type"] for t in tasks.values() if t["type"]}),
         "file_created": os.path.isfile(os.path.join(c.scratch, "hello.txt"))}
    return Outcome(yn(f["exit_plan_reached_callback"] and f["tasks_started"] > 0), f)


async def pr4(c: Ctx) -> Outcome:
    async with c.client(c.options(extra_args={"permission-prompts": "none"}, max_turns=4)) as s:
        msgs = await s.turn(PROMPTS["ask"], 240)
    init, r = init_data(msgs), result_of(msgs)
    tools = init.get("tools") if isinstance(init.get("tools"), list) else None
    denials = (r.permission_denials or []) if r is not None else []
    f = {"init_tools_listed": tools is not None, "ask_in_init_tools": tools is not None and "AskUserQuestion" in tools,
         "ask_tool_use_attempted": any(n == "AskUserQuestion" for n, _, _ in tool_uses(msgs)),
         "ended": r is not None, "permission_denials": len(denials),
         "denied_tools": sorted({str(d.get("tool_name")) for d in denials if isinstance(d, dict)}),
         "result_subtype": r and r.subtype, "terminal_reason": r and r.terminal_reason}
    return Outcome(yn(None if tools is None else f["ended"] and not f["ask_in_init_tools"]), f)


async def poll(pred: Callable[[], bool], timeout: float, step: float = 0.05) -> bool:
    """Wait until pred() holds, at most `timeout` seconds; pred()'s last value."""
    import anyio
    with anyio.move_on_after(timeout):
        while not pred():
            await anyio.sleep(step)
    return pred()


async def pr5(c: Ctx) -> Outcome:
    """PR5b: the child is held live by its own parked Bash permission request, stopped with
    stop_task, and the guard's registry record of it (R0 before, R1 after) shows whether the stop
    reached the guard (SubagentStop -> mark_stopped, which also drops its locks and leases)."""
    import anyio
    import anyio.lowlevel
    host, wait = HoldHost(c.cfg.hold_s), c.cfg.wait_s
    o = c.options(permission_mode="default", can_use_tool=host, include_hook_events=True, max_turns=6)
    f: dict[str, Any] = {"child_started": False, "child_pending": False, "child_live_at_stop": False}
    async with c.client(o) as s, anyio.create_task_group() as tg:
        tg.start_soon(s.drain)

        def child() -> Any:
            return next((m for m in s.msgs if kind(m) == "TaskStartedMessage" and m.task_type == "local_agent"), None)
        await s.c.query(PROMPTS["stop"])
        await poll(lambda: host.pending and child() is not None, wait)
        t, f["child_pending"] = child(), host.pending
        if t is not None:
            sid, tuid = t.session_id, t.tool_use_id

            def own(paths: list[str]) -> bool:
                return any(tuid and tuid in os.path.basename(p) for p in paths)
            r0, before = c.registry(sid, tuid), c.leases(sid)
            live = host.pending and r0 is not None and not r0.get("stopped")
            f.update(child_started=True, child_live_at_stop=live, registry_before=r0 is not None,
                     registry_bg_before=bool(r0 and r0.get("bg")), registry_stopped_before=bool(r0 and r0.get("stopped")),
                     registry_is_held_agent=bool(r0 and host.pending_agent and r0.get("id") == host.pending_agent),
                     leases_before=len(before), child_lease_before=own(before))
            n = len(s.msgs)
            await s.c.stop_task(t.task_id)

            def status() -> Any:
                return task_states(s.msgs).get(t.task_id, {}).get("status")
            await poll(lambda: status() in TERMINAL, wait)
            host.release.set()
            await anyio.sleep(c.cfg.settle_s)
            r1, after = c.registry(sid, tuid), c.leases(sid)
            f.update(child_status_after_stop=status(), registry_after=r1 is not None,
                     registry_stopped_after=bool(r1 and r1.get("stopped")),
                     subagent_stop_events=sum(1 for m in s.msgs[n:] if kind(m) == "HookEventMessage"
                                              and m.hook_event_name == "SubagentStop"),
                     leases_after=len(after), child_lease_after=own(after),
                     locks_after=len(glob.glob(os.path.join(c.guard_dir(sid), "**", "*.lock"), recursive=True)))
        host.release.set()
        await anyio.lowlevel.checkpoint()               # the parked callback records how it ended
        if not any(map(is_result, s.msgs)):             # the turn is still open: end it
            n = len(s.msgs)
            await s.c.interrupt()
            await poll(lambda: any(map(is_result, s.msgs[n:])), wait)
        f["hold_released_by"] = host.released_by
        tg.cancel_scope.cancel()
    if not f["child_live_at_stop"]:
        return Outcome("unknown", f)                    # no live child at the stop: nothing measured
    return Outcome(yn(f["child_status_after_stop"] in TERMINAL and f["registry_stopped_after"]), f)


def guard_snapshot(c: Ctx, sid: str | None) -> dict[str, Any]:
    if not sid:
        return {}
    d = c.guard_dir(sid)
    try:
        with open(os.path.join(d, "budget.json")) as fh:
            budget_parses: bool | None = isinstance(json.load(fh), dict)
    except FileNotFoundError:
        budget_parses = None
    except ValueError:
        budget_parses = False
    try:
        with open(os.path.join(d, "prompt-windows.jsonl")) as fh:
            windows: int | None = sum(1 for ln in fh if ln.strip())
    except FileNotFoundError:
        windows = None
    return {"budget_parses": budget_parses, "prompt_windows": windows,
            "prompt_pending": os.path.exists(os.path.join(d, "prompt-pending.json")),
            "ledger": os.path.exists(os.path.join(d, "delegations.md"))}


async def pr6(c: Ctx) -> Outcome:
    async with c.client(c.options(max_turns=2, share=0.5, include_partial_messages=True)) as s:
        await s.c.query(PROMPTS["count"])
        first = await s.wait_for(lambda m: kind(m) in ("StreamEvent", "ResultMessage"), 120)
        streaming = first is not None and kind(first) == "StreamEvent"
        r1 = first if first is not None and is_result(first) else None
        if streaming:                                   # interrupt mid-reply
            await s.c.interrupt()
            r1 = await s.wait_for(is_result, 60)
    sid = r1.session_id if r1 is not None else session_of(s.msgs)
    before = guard_snapshot(c, sid)
    async with c.client(c.options(max_turns=2, resume=sid, share=0.5)) as s2:
        r2 = result_of(await s2.turn(PROMPTS["ok"], 180))
    after = guard_snapshot(c, sid)
    interrupted = streaming and r1 is not None and r1.terminal_reason in ("aborted_streaming",
                                                                                        "aborted_tools")
    f = {"interrupted": interrupted, "interrupted_terminal_reason": r1 and r1.terminal_reason,
         "resumed": r2 is not None,
         "resumed_same_session": bool(r2 is not None and r2.session_id == sid),
         **{k + "_after_interrupt": v for k, v in before.items()}, **{k + "_after_resume": v for k, v in after.items()}}
    w0, w1 = before.get("prompt_windows"), after.get("prompt_windows")
    if not interrupted or r2 is None or w0 is None or w1 is None or after.get("budget_parses") is None:
        return Outcome("unknown", f)
    ok = f["resumed_same_session"] and not after["prompt_pending"] and after["budget_parses"] and w1 == w0 + 1
    return Outcome(yn(ok), f)


async def pr7(c: Ctx) -> Outcome:
    # No can_use_tool and no SDK hook: with either, the SDK keeps stdin open while a tracked agent runs
    # and its own ceiling never ends the run (query.py _end_run_at_ceiling), so "yes" could not happen.
    # Without them query() closes stdin after the first result and the CLI's ceiling is measured.
    # Approval by rules; whether the child inherits them is part of what PR7 shows.
    env = {"CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS": str(c.cfg.bg_ceiling_ms)}
    o = c.options(permission_mode="default", allowed_tools=["Agent", "Task", "Bash(sleep 110)"], env=env,
                  max_turns=6)
    t0 = time.monotonic()
    out = await c.one_shot(PROMPTS["bg"], o)
    t_end, msgs = time.monotonic(), [m for _, m in out]
    t_res = next((t for t, m in out if is_result(m)), None)
    tasks = [(i, t) for i, t in task_states(msgs).items() if t["task_type"] == "local_agent"]
    tid = tasks[0][0] if tasks else None
    t_child = next((t for t, m in out if kind(m) in ("TaskNotificationMessage", "TaskUpdatedMessage")
                    and m.task_id == tid and task_status(m) in TERMINAL), None)
    ceiling, results = c.cfg.bg_ceiling_ms / 1000, sum(map(is_result, msgs))
    f = {"ceiling_ms": c.cfg.bg_ceiling_ms, "sdk_bidirectional": bool(o.can_use_tool or o.hooks), "results": results,
         "ended_at_first_result": results == 1, "child_started": bool(tasks),
         "child_status_at_end": tasks[0][1]["status"] if tasks else None, "end_s": round(t_end - t0, 1),
         "first_result_s": None if t_res is None else round(t_res - t0, 1),
         "child_end_s": None if t_child is None else round(t_child - t0, 1),
         "wait_after_first_result_s": None if t_res is None else round(t_end - t_res, 1)}
    if not tasks or t_res is None:
        return Outcome("unknown", f)
    if t_child is not None and t_child <= t_res + ceiling:
        return Outcome("unknown", f)                    # the child ended before the ceiling could act
    cut = t_child is None and t_end - t_res <= ceiling + 60
    return Outcome(yn(cut), f)


async def pr8(c: Ctx) -> Outcome:
    o = c.options(output_format={"type": "json_schema", "schema": REPORT_SCHEMA}, max_turns=3)
    async with c.client(o) as s:
        r = result_of(await s.turn(PROMPTS["report"], 180))
    so = r.structured_output if r is not None else None
    st = so.get("status") if isinstance(so, dict) else None
    f = {"result_subtype": r and r.subtype, "structured_output_type": type(so).__name__,
         "structured_keys": sorted(so)[:20] if isinstance(so, dict) else None,
         "status_value": st if st in ("done", "partial", "blocked") else None if st is None else "other"}
    return Outcome(yn(r is not None and isinstance(so, dict) and {"status", "result"} <= set(so)), f)


async def pr9(c: Ctx) -> Outcome:
    f: dict[str, Any] = {"system_cli_found": bool(c.cfg.cli_path)}
    events: dict[str, list[str]] = {}
    for label, cli in (("system", c.cfg.cli_path), ("bundled", None)):
        if label == "system" and not cli:
            continue
        async with c.client(c.options(cli_path=cli, include_hook_events=True, max_turns=2, share=0.5)) as s:
            msgs = await s.turn(PROMPTS["ok"], 180)
        events[label] = sorted(hook_events(msgs))
        f[label + "_version"] = init_data(msgs).get("claude_code_version")
        f[label + "_hook_events"] = events[label]
    if len(events) < 2:
        return Outcome("unknown", f)
    f["hook_parity"] = events["system"] == events["bundled"]
    return Outcome(yn(f["hook_parity"]), f)


async def pr10(c: Ctx) -> Outcome:
    f: dict[str, Any] = {}
    read_only = tuple(sorted(FILE_TOOLS - {"Write", "Edit", "MultiEdit", "NotebookEdit"}))
    for label, fwd in (("forward_on", True), ("forward_off", False)):
        o = c.options(permission_mode="default", can_use_tool=Host(c.scratch, ("Agent", "Task", *read_only)),
                      hooks=observer([]), forward_subagent_text=fwd, max_turns=6, share=0.5)
        async with c.client(o) as s:
            await s.turn(PROMPTS["tree"], 600)
            await s.until_idle(600)
        parent = {i: p for n, i, p in tool_uses(s.msgs) if n in ("Agent", "Task")}
        tasks, sub = task_states(s.msgs), [m for m in s.msgs if kind(m) == "AssistantMessage" and m.parent_tool_use_id]
        f[label + "_tasks"] = len(tasks)
        f[label + "_l2_tasks"] = sum(1 for t in tasks.values() if parent.get(t["tool_use_id"]))
        f[label + "_max_depth"] = max((depth(parent, i) for i in parent), default=0)
        f[label + "_subagent_messages"] = len(sub)
        f[label + "_subagent_text_messages"] = sum(1 for m in sub if any(kind(b) == "TextBlock" for b in m.content))
    return Outcome(yn(f["forward_on_l2_tasks"] + f["forward_off_l2_tasks"] > 0), f)


def depth(parent: dict[str, str | None], i: str | None) -> int:
    """Agent calls from tool_use id `i` up to the main thread (cycles cut at 16)."""
    d = 0
    while i is not None and d <= 16:
        i, d = parent.get(i), d + 1
    return d


def entrypoints(paths: list[str]) -> set[str]:
    """The `entrypoint` values of the transcript lines; nothing else is read out."""
    values = set()
    for p in paths:
        with open(p, encoding="utf-8", errors="replace") as fh:
            for ln in fh:
                try:
                    v = json.loads(ln).get("entrypoint")
                except (ValueError, AttributeError):
                    continue
                if isinstance(v, str):
                    values.add(v)
    return values


async def pr11(c: Ctx) -> Outcome:
    async with c.client(c.options(max_turns=2)) as s:
        msgs = await s.turn(PROMPTS["ok"], 180)
    paths = c.transcripts(session_of(msgs) or "-")
    values = entrypoints(paths)
    f = {"transcript_found": bool(paths), "entrypoint_values": sorted(values)}
    return Outcome(yn(None if not paths else "sdk-py" in values), f)


async def pr12(c: Ctx) -> Outcome:
    import anyio
    f: dict[str, Any] = {"killed": False}
    for label in ("disconnect", "sigkill"):
        async with c.client(c.options(max_turns=2, share=0.5)) as s:
            msgs = await s.turn(PROMPTS["ok"], 180)
            if label == "sigkill":
                f["killed"] = c.kill(s)
        await anyio.sleep(c.cfg.settle_s)
        d = os.path.join(c.cfg.state_dir, "usage", "sessions", session_of(msgs) or "-")
        f[label + "_session_dir"] = os.path.isdir(d)
        f[label + "_end_marker"] = os.path.exists(os.path.join(d, "end"))
    if not (f["killed"] and f["disconnect_session_dir"] and f["sigkill_session_dir"]):
        return Outcome("unknown", f)
    return Outcome(yn(f["disconnect_end_marker"] and not f["sigkill_end_marker"]), f)


async def pr13(c: Ctx) -> Outcome:
    f: dict[str, Any] = {}
    for i in (1, 2):
        r = result_of([m for _, m in await c.one_shot(PROMPTS["ok"], c.options(max_turns=2, share=0.5))])
        t = tokens(r.model_usage if r is not None else None)
        f.update({"run%d_input" % i: t.get("inputTokens"), "run%d_cache_write" % i: t.get("cacheCreationInputTokens"),
                  "run%d_cache_read" % i: t.get("cacheReadInputTokens")})
    # reuse = what the second call reads beyond the first (2026-10-09: both read 9,502 and wrote 18,470)
    r1, r2 = f["run1_cache_read"], f["run2_cache_read"]
    f["cache_read_gain"] = gain = None if r1 is None or r2 is None else r2 - r1
    return Outcome(yn(None if gain is None else gain > 0), f)


PROBES = [
    Probe("PR1", "get_server_info() and init show the stack agents; agent_guard's SessionStart reaches the "
                 "stream (include_hook_events)", SMALL_USD, 300, pr1),
    Probe("PR2", "AskUserQuestion from BlackCat reaches can_use_tool with the neutral PreToolUse hook "
                 "(hook_still_needed: not without it)", SMALL_USD, 600, pr2),
    Probe("PR3", "ExitPlanMode reaches can_use_tool in plan mode and approving it lets builders dispatch",
          LARGE_USD, 1500, pr3),
    Probe("PR4", "extra_args passes --permission-prompts none: AskUserQuestion is gone from the init tools "
                 "and the run ends", SMALL_USD, 300, pr4),
    Probe("PR5", "stop_task on a live child (held by a parked permission request) marks it stopped in the "
                 "guard's registry", LARGE_USD, 600, pr5),
    Probe("PR6", "interrupt() then resume: same session, no pending prompt, one prompt window per prompt",
          SMALL_USD, 420, pr6),
    Probe("PR7", "the background-wait ceiling ends an SDK single-message run while its child still runs",
          LARGE_USD, 900, pr7),
    Probe("PR8", "output_format json_schema with --agent blackcat yields structured_output with status and "
                 "result", SMALL_USD, 300, pr8),
    Probe("PR9", "the system and the bundled CLI fire the same hook events", SMALL_USD, 420, pr9),
    Probe("PR10", "L2 Task messages appear and parent_tool_use_id builds the tree (forward_subagent_text on "
                  "and off)", LARGE_USD, 1500, pr10),
    Probe("PR11", "the session transcript carries entrypoint sdk-py", SMALL_USD, 300, pr11),
    Probe("PR12", "SessionEnd (the usage end marker) runs on disconnect() and not on SIGKILL", SMALL_USD, 420, pr12),
    Probe("PR13", "the second identical call reads more from the cache than the first (exclude_dynamic_sections "
                  "plus --agent)",
          SMALL_USD, 420, pr13),
]


# ---------------------------------------------------------------- the run and the report
@dataclasses.dataclass
class Row:
    probe: Probe
    answer: str
    cap: float
    cost: float = 0.0
    sessions: list[str] = dataclasses.field(default_factory=list)
    transcripts: list[str] = dataclasses.field(default_factory=list)
    facts: dict[str, Any] = dataclasses.field(default_factory=dict)
    seconds: float = 0.0


async def run_probes(probes: list[Probe], cfg: Config, helper: Any, rows: list[Row] | None = None) -> list[Row]:
    """Each probe in turn under its own cap; stops at a BudgetError or once the total cap is used.
    Finished rows go into `rows` as they finish (main reports them even after Ctrl-C)."""
    validate_registry(probes)
    import anyio
    rows = [] if rows is None else rows
    total = 0.0
    for p in probes:
        left = TOTAL_CAP_USD - total
        if left < 0.05:
            rows.append(Row(p, "skipped", 0.0, facts={"reason": "total_cap_used"}))
            continue
        ctx, t0 = Ctx(p, cfg, helper, left), time.monotonic()
        row = Row(p, "error", ctx.cap)
        try:
            with anyio.fail_after(p.timeout_s):
                out = await p.fn(ctx)
            row.answer, row.facts = out.answer, dict(out.facts)
        except BudgetError:
            row.answer, row.facts = "refused", {"reason": "budget_guard"}
        except TimeoutError:
            row.answer, row.facts = "unknown", {"timeout": True}
        except Exception as e:  # noqa: BLE001 - any probe failure; the type only (a message may quote a prompt)
            row.answer, row.facts = "error", {"error": type(e).__name__}
        finally:
            shutil.rmtree(ctx.scratch, ignore_errors=True)
        row.cost, row.sessions, row.seconds = ctx.spent, list(ctx.session_ids), round(time.monotonic() - t0, 1)
        row.transcripts = [t for sid in ctx.session_ids for t in ctx.transcripts(sid)]
        row.facts["rate_limit_events"] = ctx.rate_limit_events
        row.facts["open_tasks_at_close_by_type"] = dict(sorted(ctx.open_at_close.items()))
        row.facts["sessions_without_result"] = ctx.unreported      # counted at their whole cap
        total += ctx.spent
        rows.append(row)
        if row.answer == "refused":
            break                       # a cap bug: spend nothing more
    return rows


def clean(v: Any, depth: int = 0) -> Any:
    """A fact as the report may hold it: numbers, booleans, None and identifier-like strings; any other
    string (prose, a prompt, a reply, an error message) becomes <withheld>."""
    if v is None or isinstance(v, (bool, int)):
        return v
    if isinstance(v, float):
        return round(v, 6)
    if isinstance(v, str):
        return v if IDENT.fullmatch(v) else WITHHELD
    if depth > 3:
        return WITHHELD
    if isinstance(v, dict):
        return {clean(str(k), depth + 1): clean(x, depth + 1) for k, x in list(v.items())[:60]}
    if isinstance(v, (list, tuple, set, frozenset)):
        return [clean(x, depth + 1) for x in list(v)[:60]]
    return WITHHELD


def words(s: str) -> str:
    """Lower-case alphanumeric runs joined by one space: `Reply_with exactly:ok` -> `reply with exactly ok`."""
    return " ".join(re.findall(r"[a-z0-9]+", s.lower()))


def prompt_fragments() -> list[str]:
    """Every prompt and every 32-character window of it, as words()."""
    out = set()
    for p in map(words, PROMPTS.values()):
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

    def path_ok(t: str) -> bool:
        return os.path.isabs(t) and t.endswith(".jsonl") and not re.search(r"[\s|`]", t)
    out = ["# Agent SDK probes, %s" % meta["date"], "",
           "claude-agent-sdk %s · system CLI %s · bundled CLI %s · spent USD %.4f of the %.2f cap (CLI "
           "estimates)" % (cell(meta.get("sdk")), cell(meta.get("system_cli")), cell(meta.get("bundled_cli")),
                           sum(r.cost for r in rows), TOTAL_CAP_USD), "",
           "| probe | question | answer | cost USD | cap USD | seconds | sessions | transcripts |",
           "|---|---|---|---:|---:|---:|---|---|"]
    for r in rows:
        out.append("| %s | %s | %s | %.4f | %.2f | %.1f | %s | %s |" % (
            r.probe.pid, r.probe.question, r.answer, r.cost, r.cap, r.seconds,
            " ".join(s for s in r.sessions if IDENT.fullmatch(s)) or "-",
            " ".join(t for t in r.transcripts if path_ok(t)) or "-"))
    out += ["", "## Facts", ""]
    for r in rows:
        out.append("- **%s**: %s" % (r.probe.pid, ", ".join(
            "%s=%s" % (clean(str(k)), cell(v)) for k, v in sorted(r.facts.items()))))
    text = "\n".join(out) + "\n"
    assert_no_prompt(text)
    return text


def write_report(path: str, text: str) -> str:
    """Write a new file (0600; never overwrites: <date>-2.md and on) after the prompt check."""
    assert_no_prompt(text)
    os.makedirs(os.path.dirname(path), mode=0o700, exist_ok=True)
    stem, n = path.removesuffix(".md"), 1
    while os.path.exists(path):
        n += 1
        path = "%s-%d.md" % (stem, n)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(text)
    return path


def default_out(today: str) -> str:
    """<main checkout>/.claude-work/sdk/probes/<date>.md, also when run from a linked worktree."""
    here = os.path.dirname(os.path.abspath(__file__))
    try:
        common = subprocess.run(["git", "-C", here, "rev-parse", "--path-format=absolute", "--git-common-dir"],
                                capture_output=True, text=True, timeout=10, check=True).stdout.strip()
        root = os.path.dirname(common)
    except (OSError, subprocess.SubprocessError):
        root = os.path.dirname(here)
    return os.path.join(root, ".claude-work", "sdk", "probes", today + ".md")


def load_helper(config_dir: str) -> Any:
    path = os.path.join(config_dir, "bin", "stack_sdk.py")
    spec = importlib.util.spec_from_file_location("stack_sdk", path)
    if spec is None or spec.loader is None or not os.path.isfile(path):
        raise SystemExit("no installed stack helper at %s" % path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def versions(cli: str | None) -> dict[str, Any]:
    out: dict[str, Any] = {"sdk": None, "system_cli": None, "bundled_cli": None}
    with contextlib.suppress(Exception):
        import claude_agent_sdk
        out["sdk"] = claude_agent_sdk.__version__
        from claude_agent_sdk._cli_version import __cli_version__
        out["bundled_cli"] = __cli_version__
    if cli:
        with contextlib.suppress(OSError, subprocess.SubprocessError):
            p = subprocess.run([cli, "--version"], capture_output=True, text=True, timeout=20, check=False)
            m = re.search(r"\d+\.\d+\.\d+", p.stdout)
            out["system_cli"] = m and m.group(0)
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Agent SDK probes PR1-PR13 (billed; run by the user).")
    ap.add_argument("--run", action="store_true", help="make the billed calls (default: print the plan, $0)")
    ap.add_argument("--only", default="", help="comma-separated probe ids, e.g. PR1,PR4")
    ap.add_argument("--config", default=os.environ.get("CLAUDE_CONFIG_DIR") or "~/.claude")
    ap.add_argument("--cli", default=shutil.which("claude"), help="the installed claude (default: PATH)")
    ap.add_argument("--out", help="report path (default <main checkout>/.claude-work/sdk/probes/<date>.md)")
    ap.add_argument("--bg-ceiling-ms", type=int, default=Config.bg_ceiling_ms, help="PR7's background-wait ceiling")
    a = ap.parse_args(argv)
    only = {x.strip().upper() for x in a.only.split(",") if x.strip()}
    if only - {p.pid for p in PROBES}:
        ap.error("unknown probe ids: %s" % ", ".join(sorted(only - {p.pid for p in PROBES})))
    probes = [p for p in PROBES if not only or p.pid in only]
    validate_registry(probes)
    if not a.run:
        for p in probes:
            print("%-5s $%.2f  %s" % (p.pid, p.budget_usd, p.question))
        print("total cap $%.2f; pass --run to make the billed calls" % sum(p.budget_usd or 0 for p in probes))
        return 0
    if (v := versions(None)["sdk"]) != SDK_PIN:
        ap.error("claude-agent-sdk %s is not the pinned %s: uv run --locked --script %s" % (v, SDK_PIN, __file__))
    if not a.cli:
        ap.error("no `claude` on PATH: pass --cli /path/to/claude (Q3: the installed CLI)")
    today = datetime.date.today().isoformat()
    out = os.path.abspath(os.path.expanduser(a.out)) if a.out else default_out(today)
    try:                                       # before any billed call, not after
        os.makedirs(os.path.dirname(out), mode=0o700, exist_ok=True)
        if not os.access(os.path.dirname(out), os.W_OK):
            raise PermissionError("not writable")
    except OSError as e:
        ap.error("cannot write the report to %s: %s" % (out, e.strerror or e))
    config = os.path.expanduser(a.config)
    state = os.path.join(os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state"),
                         "claude-agent-stack")
    cfg = Config(config_dir=config, cli_path=a.cli, state_dir=state, bg_ceiling_ms=a.bg_ceiling_ms)
    rows: list[Row] = []
    try:
        asyncio.run(run_probes(probes, cfg, load_helper(config), rows))
    finally:                                   # Ctrl-C or a crash: the finished probes are still reported
        print(write_report(out, render(rows, dict(versions(a.cli), date=today))))
        for r in rows:
            print("%-5s %-8s $%.4f" % (r.probe.pid, r.answer, r.cost))
    return 1 if any(r.answer in ("error", "refused") for r in rows) else 0


if __name__ == "__main__":
    sys.exit(main())
