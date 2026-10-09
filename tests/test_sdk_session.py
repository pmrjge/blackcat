"""$0 tests of stack_sdk v2 (SDK-2): Session over FakeCLI, a Transport that speaks the SDK's control protocol
(initialize, can_use_tool, interrupt) and plays the synthetic streams in tests/fixtures/sdk/stream_*.jsonl.
The SDK's subprocess transport is disabled: nothing reaches a CLI or the API. Each T_* test names the
design's mutants (M1-M33, .claude-work/sdk/sdk2-design.md) it kills.

Run: uv run --no-project --python 3.13 --with pytest --with claude-agent-sdk==0.2.163 pytest -q tests/test_sdk_session.py
"""
import asyncio
import contextlib
import importlib.util
import itertools
import json
import os
import re
import signal
import sys
import time
from pathlib import Path

import pytest

pytest.importorskip("claude_agent_sdk")
from claude_agent_sdk import (
    PermissionResultAllow,
    PermissionResultDeny,
    Transport,
)
from claude_agent_sdk._internal.message_parser import parse_message
from claude_agent_sdk.types import PermissionRuleValue, PermissionUpdate

ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / "dot-config" / "dot-claude" / "bin" / "stack_sdk.py"
FIX = ROOT / "tests" / "fixtures" / "sdk"
LEAK = "ZEBRA-LEAK-42"
spec = importlib.util.spec_from_file_location("stack_sdk_v2", str(HELPER))
sdk = importlib.util.module_from_spec(spec)
sys.modules["stack_sdk_v2"] = sdk
spec.loader.exec_module(sdk)

BUILDERS = ["coder", "newbie"]                       # acceptEdits in their frontmatter; newbie is "new"
AGENTS = {"blackcat": None, "explore": None, "planner": "plan", "scout": "default", "coder": "acceptEdits",
          "newbie": "acceptEdits"}


def script(name):
    return [json.loads(ln) for ln in (FIX / name).read_text().splitlines() if ln.strip()]


@pytest.fixture(autouse=True)
def no_real_cli(monkeypatch):
    from claude_agent_sdk._internal.transport import subprocess_cli

    async def refuse(self):
        raise AssertionError("a test tried to start a real CLI")
    monkeypatch.setattr(subprocess_cli.SubprocessCLITransport, "connect", refuse)
    monkeypatch.setattr(sdk, "GRACE_S", 0.05)
    monkeypatch.setattr(sdk, "INTERRUPT_S", 1.0)


# ---------------------------------------------------------------- the fake CLI
class World:
    """What the fake sessions share: the stack's files, the guard's state, the wire log."""

    def __init__(self, tmp, script=(), agents=None, server_agents=None, mode="plan", outcome="success",
                 marker=True, marker_source=None, policy=True, late=0.0, late_marker=False, extra_info=None):
        self.config, self.state = tmp / "config", tmp / "state"
        (self.config / "agents").mkdir(parents=True)
        for name, pm in (AGENTS if agents is None else agents).items():
            pm_line = f"permissionMode: {pm}\n" if pm else ""
            fm = f"---\nname: {name}\ndescription: \"x\"\n{pm_line}---\nbody\n"
            (self.config / "agents" / (name + ".md")).write_text(fm)
        (self.config / "settings.json").write_text(json.dumps({"hooks": {"SessionStart": [
            {"matcher": "startup|resume|clear|compact|fork", "hooks": [{"type": "command", "command": "guard"}]},
            {"hooks": [{"type": "command", "command": "guard session-env"}]}]}}))
        self.script, self.mode, self.outcome, self.marker, self.marker_source = list(script), mode, outcome, marker, marker_source
        self.policy, self.late, self.late_marker, self.extra_info = policy, late, late_marker, extra_info or {}
        self.server_agents = [{"name": n, "description": LEAK, "model": "x"} for n in (
            server_agents if server_agents is not None else (agents or AGENTS))]
        self.ids, self.opened, self.log, self.answers, self.closed, self.interrupts = itertools.count(1), [], [], [], 0, 0

    def env(self, **kw):
        return dict({"XDG_STATE_HOME": str(self.state)}, **kw)

    def factory(self, opts):
        self.opened.append(opts)
        return FakeCLI(self, opts)

    def session(self, **kw):
        kw.setdefault("budget_usd", 0.5)
        kw.setdefault("cli", "bundled")
        kw.setdefault("load_timeout_s", 2.0)
        kw["env"] = dict(self.env(), **kw.get("env", {}))
        return sdk.Session(kw.pop("agent", "blackcat"), config_dir=str(self.config), transport=self.factory, **kw)

    def marker_path(self, sid):
        return self.state / "claude-agent-stack" / sid / "session-start.json"

    def rows(self):
        p = self.state / "claude-agent-stack" / "usage" / "sdk-runs.jsonl"
        return [json.loads(x) for x in p.read_text().splitlines()] if p.exists() else []


class FakeCLI(Transport):
    def __init__(self, w, opts):
        self.w, self.o, self.n = w, opts, next(w.ids)
        self.sid = opts.resume if opts.resume and not opts.fork_session else f"sess-{self.n:04d}-fake"
        self.q, self.pending, self.tasks, self.rids, self.turn = asyncio.Queue(), {}, set(), itertools.count(1), False

    async def connect(self):
        pass

    def is_ready(self):
        return True

    async def end_input(self):
        pass

    async def close(self):
        self.w.closed += 1
        self.q.put_nowait(None)

    async def read_messages(self):
        while (m := await self.q.get()) is not None:
            yield m

    def emit(self, m):
        self.q.put_nowait(m)

    def spawn(self, coro):
        t = asyncio.ensure_future(coro)
        self.tasks.add(t)
        t.add_done_callback(self.tasks.discard)

    def source(self):
        o = self.o
        return "fork" if o.resume and o.fork_session else "resume" if o.resume or o.continue_conversation else "startup"

    def write_marker(self):
        p = self.w.marker_path(self.sid)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({"v": 1, "ts": time.time(), "source": self.w.marker_source or self.source(),
                                 "policy": self.w.policy}))
        self.w.log.append("marker")
        time.sleep(0.002)                        # the marker is strictly older than anything after it

    def hook(self, sub, hid, outcome="success"):
        d = {"type": "system", "subtype": sub, "hook_id": hid, "hook_event": "SessionStart",
             "hook_name": "SessionStart:" + self.source(), "session_id": self.sid, "uuid": "u-" + hid + sub}
        if sub == "hook_response":
            d.update(outcome=outcome, exit_code=0 if outcome == "success" else 1, stdout=LEAK, stderr="", output=LEAK)
            self.w.log.append("hook_response")
        self.emit(d)

    async def session_start(self):
        """The CLI's SessionStart: two hooks; the guard writes its marker (during connect by default)."""
        events = self.o.include_hook_events
        if events:
            for h in ("h1", "h2"):
                self.hook("hook_started", h)
        await asyncio.sleep(self.w.late)
        if self.w.late_marker and self.w.marker:
            await asyncio.sleep(0.2)
            self.write_marker()
        if events:
            self.hook("hook_response", "h1", self.w.outcome)
            self.hook("hook_response", "h2")

    async def write(self, data):
        m = json.loads(data)
        if m["type"] == "control_request":
            rid, req = m["request_id"], m["request"]
            resp = {}
            if req["subtype"] == "initialize":
                if self.w.marker and not self.w.late_marker:
                    self.write_marker()          # the guard ran during connect (U1: +0.3 s of +0.77 s)
                resp = dict({"agents": self.w.server_agents, "current_permission_mode": self.w.mode,
                             "commands": [{"name": "c", "description": " ".join(AGENTS)}]}, **self.w.extra_info)
                self.spawn(self.session_start())
            elif req["subtype"] == "interrupt":
                self.w.interrupts += 1
                if self.turn:
                    self.turn = False
                    self.emit(result("aborted", 0.2, terminal_reason="aborted_streaming", subtype="error_during_execution",
                                     is_error=True))
            self.emit({"type": "control_response", "response": {"subtype": "success", "request_id": rid, "response": resp}})
        elif m["type"] == "control_response":
            fut = self.pending.pop(m["response"]["request_id"], None)
            if fut is not None:
                fut.set_result(m["response"])
        elif m["type"] == "user":
            self.w.log.append("prompt")
            self.spawn(self.play())

    async def ask(self, req):
        rid = f"cli_{next(self.rids)}"
        fut = asyncio.get_running_loop().create_future()
        self.pending[rid] = fut
        self.emit({"type": "control_request", "request_id": rid, "request": dict(req, subtype="can_use_tool")})
        resp = await asyncio.wait_for(fut, 30)
        self.w.answers.append((req["tool_name"], resp.get("response") or {}))

    async def play(self):
        self.turn = True
        for line in self.w.script:
            if "_sleep" in line:
                await asyncio.sleep(line["_sleep"])
            elif "_can_use_tool" in line:
                await self.ask(line["_can_use_tool"])
            elif "_signal" in line:
                os.kill(os.getpid(), getattr(signal, line["_signal"]))
            elif "_hang" in line:
                return
            else:
                if line.get("type") == "result":
                    self.turn = False
                self.emit(line)


def result(body, cost, **kw):
    return dict({"type": "result", "subtype": "success", "duration_ms": 5, "duration_api_ms": 4, "is_error": False,
                 "num_turns": 1, "session_id": "sess-fixture", "total_cost_usd": cost, "result": body,
                 "terminal_reason": "completed", "uuid": "u-r"}, **kw)


def sys_frame(subtype, **kw):
    return dict({"type": "system", "subtype": subtype, "session_id": "sess-fixture", "uuid": "u"}, **kw)


def run(coro, limit=20):
    """Every test run is bounded: a hang (a mutant that never ends the run) fails instead."""
    return asyncio.run(asyncio.wait_for(coro, limit))


async def one(w, prompt="go", **kw):
    async with w.session(**kw) as s:
        return await s.ask(prompt)


# ---------------------------------------------------------------- D2 load check
def test_load_fails_closed(tmp_path):
    """M1 M24 M25 M32 M33: every leg below raises StackNotLoaded with no prompt sent; the good world passes."""
    w = World(tmp_path / "ok", script=script("stream_plan.jsonl"))
    out = run(one(w))
    assert w.opened[0].include_hook_events is True                       # M33
    assert out["outcome"] == "unknown" and w.log.count("prompt") == 1    # t0 before connect() (M32 half 1)
    late = World(tmp_path / "late", script=script("stream_plan.jsonl"), late_marker=True)
    assert run(one(late))["session_id"] and late.log.index("marker") < late.log.index("prompt")   # M32 half 2
    bad = {
        "name only elsewhere": {"server_agents": ["blackcat", "explore", "planner", "scout", "coder"]},  # M1
        "error outcome": {"outcome": "error"},                                                     # M25
        "no marker": {"marker": False},                                                            # M1
        "policy off": {"policy": False},
        "wrong source": {"marker_source": "clear"},
    }
    for i, (what, kw) in enumerate(bad.items()):
        b = World(tmp_path / f"b{i}", script=script("stream_plan.jsonl"), **kw)
        with pytest.raises(sdk.StackNotLoaded) as e:
            run(one(b))
        assert "prompt" not in b.log and b.closed >= 1, what
        if what == "policy off":
            assert str(e.value) == "policy off: STACK_POLICY=off"
    # M24: an earlier run's marker (source startup, older than t0) does not satisfy a resume
    r = World(tmp_path / "resume", script=script("stream_plan.jsonl"), marker=False)
    old = r.marker_path("sess-old")
    old.parent.mkdir(parents=True)
    old.write_text(json.dumps({"v": 1, "ts": time.time() - 60, "source": "resume", "policy": True}))
    with pytest.raises(sdk.StackNotLoaded, match="stale"):
        run(one(r, resume="sess-old"))
    assert "prompt" not in r.log
    # M33: without include_hook_events no SessionStart event arrives, so the check cannot pass
    s = World(tmp_path / "s", script=script("stream_plan.jsonl")).session(load_timeout_s=0.3)
    assert s.build(True).include_hook_events is True


def test_load_check_preprompt(tmp_path):
    """M23: the prompt goes out only after every SessionStart response and the marker (U1 = pre-prompt)."""
    w = World(tmp_path, script=script("stream_plan.jsonl"), late=0.3)
    run(one(w))
    assert w.log == ["marker", "hook_response", "hook_response", "prompt"]
    s = World(tmp_path / "x", script=script("stream_plan.jsonl")).session()
    with pytest.raises(sdk.StackNotLoaded):
        run(s.ask("go"))                                                 # never connected: no prompt


def test_cli_not_loaded_exit_3_and_row(tmp_path, monkeypatch, capsys):
    w = World(tmp_path, script=script("stream_plan.jsonl"), marker=False)
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(w.config))
    monkeypatch.setenv("XDG_STATE_HOME", str(w.state))
    assert sdk.main(["--budget-usd", "1", "--cli", "bundled", LEAK], transport=w.factory) == 3
    assert json.loads(capsys.readouterr().out)["outcome"] == "not_loaded" and "prompt" not in w.log
    assert w.rows()[-1]["outcome"] == "not_loaded" and LEAK not in json.dumps(w.rows())


def test_unparsable_agent_file_fails_closed(tmp_path):
    w = World(tmp_path, script=script("stream_plan.jsonl"))
    (w.config / "agents" / "broken.md").write_text("no frontmatter")
    with pytest.raises(sdk.StackNotLoaded, match="broken.md"):
        run(one(w))
    assert w.opened == []


# ---------------------------------------------------------------- D3 hosts, D5 modes
def test_host_none(tmp_path):
    """M2: permission-prompts none, no can_use_tool, ExitPlanMode denied; the caller cannot set host keys."""
    w = World(tmp_path, script=script("stream_plan.jsonl"))
    s = w.session(extra_args={"debug": None})
    o = s.build(True)
    assert o.extra_args == {"debug": None, "permission-prompts": "none", "agent": "blackcat"}
    assert o.can_use_tool is None and "ExitPlanMode" in o.disallowed_tools
    run(one(w))
    assert w.opened[0].extra_args["permission-prompts"] == "none" and w.opened[0].can_use_tool is None
    for key in ("permission-prompts", "permission-prompt-tool", "--permission-prompts"):
        with pytest.raises(ValueError, match="refused"):
            w.session(extra_args={key: "stdio"})


def test_host_none_denies_builders(tmp_path):
    """M22 M31: under plan every non-inherit agent (a new one too) and Workflow are denied; an explicit
    non-plan mode drops them and is logged gate_waived; a server mode mismatch reconnects once."""
    w = World(tmp_path / "a", script=script("stream_plan.jsonl"))
    run(one(w))
    deny = w.opened[0].disallowed_tools
    assert {"Agent(coder)", "Agent(newbie)", "Workflow", "ExitPlanMode"} <= set(deny)
    assert not {"Agent(blackcat)", "Agent(explore)", "Agent(planner)", "Agent(scout)"} & set(deny)
    w2 = World(tmp_path / "b", script=script("stream_tree.jsonl"), mode="acceptEdits")
    out = run(one(w2, permission_mode="acceptEdits"))
    assert out["gate_waived"] is True and w2.rows()[-1]["gate_waived"] is True
    assert not any(x.startswith("Agent(") for x in w2.opened[0].disallowed_tools) and len(w2.opened) == 1
    w3 = World(tmp_path / "c", script=script("stream_tree.jsonl"), mode="acceptEdits")
    out = run(one(w3))                                               # assumed plan; the server says otherwise
    assert len(w3.opened) == 2 and "Agent(coder)" in w3.opened[0].disallowed_tools
    assert "Agent(coder)" not in w3.opened[1].disallowed_tools and out["gate_waived"] is False


def callable_world(tmp_path, host, tool="Bash", inp=None, **req):
    w = World(tmp_path, script=[{"_can_use_tool": dict({"tool_name": tool, "input": inp or {"command": "ls"},
                                                       "tool_use_id": "tu-x"}, **req)},
                                result("STATUS: done\nRESULT: ok", 0.01), sys_frame("session_state_changed", state="idle")])
    out = run(one(w, host=host))
    return w, out


def test_no_persist(tmp_path):
    """M3: of updated_permissions only session addRules naming the requested tool survive."""
    def ups(tool):
        R = [PermissionRuleValue(tool_name=tool)]
        return [PermissionUpdate(type="addRules", destination="session", behavior="allow", rules=R),
                PermissionUpdate(type="addRules", destination="session", behavior="allow",
                                 rules=[PermissionRuleValue(tool_name="Write")]),
                PermissionUpdate(type="addRules", destination="userSettings", behavior="allow", rules=R),
                PermissionUpdate(type="addRules", destination="localSettings", behavior="allow", rules=R),
                PermissionUpdate(type="setMode", destination="session", mode="bypassPermissions"),
                PermissionUpdate(type="replaceRules", destination="session", behavior="allow", rules=R),
                PermissionUpdate(type="removeRules", destination="session", behavior="deny", rules=R),
                PermissionUpdate(type="addDirectories", destination="session", directories=["/"]),
                PermissionUpdate(type="removeDirectories", destination="session", directories=["/tmp"])]

    async def host(tool, inp, ctx):
        return PermissionResultAllow(updated_permissions=ups(tool) + list(ctx.suggestions))
    w, _out = callable_world(tmp_path / "a", host, permission_suggestions=[
        {"type": "addRules", "destination": "userSettings", "rules": [{"toolName": "Bash"}], "behavior": "allow"}])
    _tool, resp = w.answers[0]
    assert resp["behavior"] == "allow"
    assert resp["updatedPermissions"] == [{"type": "addRules", "destination": "session", "behavior": "allow",
                                           "rules": [{"toolName": "Bash", "ruleContent": None}]}]

    async def only_bad(tool, inp, ctx):
        return PermissionResultAllow(updated_permissions=ups(tool)[2:])
    w, _ = callable_world(tmp_path / "b", only_bad)
    assert "updatedPermissions" not in w.answers[0][1]


def test_callable_host_denies_failures(tmp_path):
    async def boom(tool, inp, ctx):
        raise RuntimeError("x")
    for i, host in enumerate((boom, lambda *a: "yes", lambda *a: None)):
        w, _ = callable_world(tmp_path / str(i), host)
        assert w.answers[0][1]["behavior"] == "deny"


def test_ask_requires_callable(tmp_path):
    """M4: AskUserQuestion is answered only with the user's answers: host none never answers it (the
    CLI removes it), a callable Allow without answers becomes Deny, with answers it passes."""
    q = {"questions": [{"question": "which db? " + LEAK, "options": [{"label": "sqlite"}, {"label": "pg"}]}]}

    async def lazy(tool, inp, ctx):
        return PermissionResultAllow()

    async def user(tool, inp, ctx):
        return PermissionResultAllow(updated_input=dict(inp, answers={inp["questions"][0]["question"]: "pg"}))
    w, _ = callable_world(tmp_path / "a", lazy, tool="AskUserQuestion", inp=q)
    assert w.answers[0][1]["behavior"] == "deny"
    w, _ = callable_world(tmp_path / "b", user, tool="AskUserQuestion", inp=q)
    assert w.answers[0][1]["behavior"] == "allow" and w.answers[0][1]["updatedInput"]["answers"]
    s = World(tmp_path / "c").session()
    assert s.build(True).can_use_tool is None and s.build(True).extra_args["permission-prompts"] == "none"


def test_budget_required(tmp_path, capsys):
    """M5: an unattended run needs a budget: the library raises before any transport, the CLI exits 2."""
    w = World(tmp_path)
    for b in (None, 0, -1.0):
        with pytest.raises(sdk.UsageError):
            run(one(w, budget_usd=b))
    assert w.opened == []
    assert sdk.main(["--cli", "bundled", "hi"], transport=w.factory) == 2 and w.opened == []


def test_cli_modes(tmp_path, monkeypatch):
    """M6: bypassPermissions is refused through permission_mode and every dangerous extra_args key."""
    w = World(tmp_path)
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(w.config))
    assert sdk.main(["--permission-mode", "bypassPermissions", "--budget-usd", "1", "--cli", "bundled", "x"],
                    transport=w.factory) == 2
    with pytest.raises(ValueError):
        w.session(permission_mode="bypassPermissions")
    for key in ("permission-mode", "dangerously-skip-permissions", "allow-dangerously-skip-permissions"):
        with pytest.raises(ValueError, match="refused"):
            w.session(extra_args={key: None})
    assert w.opened == []
    assert sdk.options(permission_mode="bypassPermissions").permission_mode == "bypassPermissions"  # v1 kept


# ---------------------------------------------------------------- D14 parity, D6 outcome, D8, D10
@pytest.mark.parametrize("name", sorted(p.name for p in FIX.glob("stream_*.jsonl")))
def test_parity(name):
    """M7: parse_stream(lines) == the SDK path (the SDK's own parser, then wire()) on every fixture."""
    lines = [ln for ln in (FIX / name).read_text().splitlines() if ln.strip() and not ln.startswith('{"_')]
    a = sdk.parse_stream(lines)
    r = sdk.Reducer()
    for ln in lines:
        m = parse_message(json.loads(ln))
        if m is not None:
            r.feed(sdk.wire(m))
    b = r.summary(ended_by="result" if r.results else "eof")
    a.pop("first_message_s"), b.pop("first_message_s")
    assert a == b
    assert sdk.parse_stream([ln.encode() for ln in lines] + ["", "not json"])["results"] == a["results"]


def test_tree_and_telemetry():
    out = sdk.parse_stream((FIX / "stream_tree.jsonl").read_text().splitlines())
    tree = {t["task_id"]: t for t in out["tasks"]}
    assert tree["t2"]["parent_tool_use_id"] == "tu-1" and tree["t1"]["parent_tool_use_id"] is None
    assert (tree["t1"]["agent"], tree["t2"]["agent"], tree["t3"]["agent"]) == ("orchestrator", "coder", None)
    assert out["outcome"] == "done" and out["report"]["source"] == "status" and out["cost_usd"] == 0.31
    assert out["system_subtypes"]["task_started"] == 3 and out["permission_mode"] == "acceptEdits"
    assert out["inflight_at_end"] == []


def test_ratelimit():
    """M10: rate limits are counted by status, then type."""
    out = sdk.parse_stream((FIX / "stream_tree.jsonl").read_text().splitlines())
    assert out["rate_limits"] == {"allowed": {"five_hour": 1}, "allowed_warning": {"seven_day": 1},
                                  "rejected": {"five_hour": 1}}


def test_last_result(tmp_path):
    """M12 (D8): every result kept with its origin; the report and cost come from the last one."""
    lines = (FIX / "stream_bg.jsonl").read_text().splitlines()
    out = sdk.parse_stream([ln for ln in lines if not ln.startswith('{"_')])
    assert len(out["results"]) == 2 and out["report"]["format"] == "clean" and out["outcome"] == "done"
    assert out["cost_usd"] == 0.12 and out["num_turns"] == 4
    o = sdk.parse_stream([json.dumps(result("first", 0.1, origin={"kind": "task-notification"})),
                          json.dumps(result("STATUS: failed\nRESULT: x", 0.3, origin="junk"))])
    assert [r["origin"] for r in o["results"]] == [{"kind": "task-notification"}, None]
    assert o["outcome"] == "failed" and o["cost_usd"] == 0.3


def test_row_no_text(tmp_path):
    """M8: one row per run, 0600, numbers and identifiers only (no prompt, reply or tool text)."""
    w = World(tmp_path, script=script("stream_tree.jsonl"), mode="acceptEdits")
    out = run(one(w, prompt=LEAK + " build me a thing", permission_mode="acceptEdits", agent=LEAK + " sentence"))
    p = w.state / "claude-agent-stack" / "usage" / "sdk-runs.jsonl"
    assert out["row"] == str(p) and p.stat().st_mode & 0o777 == 0o600
    text = p.read_text()
    assert LEAK not in text and "ZEBRA" not in text and len(text.splitlines()) == 1
    row = json.loads(text)

    def flat(v):
        return [x for y in v.values() for x in flat(y)] if isinstance(v, dict) else [v]
    for v in flat(row):
        assert v is None or isinstance(v, (bool, int, float)) or re.fullmatch(r"[\w.:@+-]{1,128}", v), v
    assert row["agent"] is None and row["outcome"] == "done" and row["rate_limited"] == 1 and row["tasks"] == 3


# ---------------------------------------------------------------- D7 end of run and bounds, D9
def test_run_end_idle_first(tmp_path, monkeypatch):
    """M26: idle that arrives before the result ends the run at the result, without the bg wait."""
    monkeypatch.setattr(sdk, "GRACE_S", 30.0)
    w = World(tmp_path, script=[sys_frame("init", permissionMode="plan"), sys_frame("session_state_changed", state="running"),
                                sys_frame("session_state_changed", state="idle"), result("STATUS: done\nRESULT: x", 0.1),
                                {"_hang": 1}])
    t = time.monotonic()
    out = run(one(w, bg_wait_s=3))
    assert out["ended_by"] == "result" and out["outcome"] == "done" and time.monotonic() - t < 2.5


def test_bg_wait_keeps_reading(tmp_path):
    """M13: a result while an agent is in flight does not end the run: the second result does."""
    w = World(tmp_path, script=script("stream_bg.jsonl"))
    out = run(one(w, bg_wait_s=10))
    assert len(out["results"]) == 2 and out["ended_by"] == "result" and out["report"]["format"] == "clean"
    assert w.interrupts == 0 and out["inflight_at_end"] == []


def test_bg_wait_ceiling(tmp_path, monkeypatch):
    """M14 M30: the ceiling cuts a run whose agent never ends (interrupt, partial, inflight listed),
    paused while requires_action; host none's default deadline is 3600 and enforced; the CLI ceiling env
    defaults to 3000 and 0 is refused."""
    base = [sys_frame("init", permissionMode="acceptEdits"), sys_frame("session_state_changed", state="running"),
            sys_frame("task_started", task_id="t1", tool_use_id="tu-1", description="coder: x", task_type="local_agent"),
            result("dispatched", 0.05)]
    w = World(tmp_path / "a", script=base + [{"_hang": 1}])
    out = run(one(w, bg_wait_s=0.3))
    assert (out["ended_by"], out["outcome"], w.interrupts) == ("bg_wait_ceiling", "partial", 1)
    assert out["inflight_at_end"] == [{"task_id": "t1", "task_type": "local_agent", "agent": "coder"}]
    w = World(tmp_path / "b", script=base + [sys_frame("session_state_changed", state="requires_action"),
                                             {"_sleep": 0.6}, sys_frame("session_state_changed", state="idle")])
    out = run(one(w, bg_wait_s=0.3))
    assert out["ended_by"] == "result" and w.interrupts == 0          # 0.6 s of requires_action: paused
    w = World(tmp_path / "c", script=[sys_frame("init", permissionMode="plan"), {"_hang": 1}])
    s = w.session()
    assert s.deadline_s == 3600 and w.session(host=lambda *a: None).deadline_s is None
    out = run(one(w, deadline_s=0.3))
    assert (out["ended_by"], out["outcome"]) == ("deadline", "partial") and exit_of(out) == 1
    o = s.build(True)
    assert o.env["CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS"] == "3000" and o.env["CLAUDE_CODE_EMIT_SESSION_STATE_EVENTS"] == "1"
    assert w.session(env={"CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS": "5000"}).env["CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS"] == "5000"
    for bad in ("0", "-1", "x"):
        with pytest.raises(ValueError, match="positive"):
            w.session(env={"CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS": bad})
    monkeypatch.setenv("CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS", "0")
    with pytest.raises(ValueError):
        w.session()


def test_inflight_agent_types_only(tmp_path):
    """M15: without state frames a running local_bash does not hold the run; a local_agent does."""
    frames = [sys_frame("init", permissionMode="acceptEdits"),
              sys_frame("task_started", task_id="t9", tool_use_id="tu-9", description="dev server", task_type="local_bash"),
              result("STATUS: done\nRESULT: x", 0.1), {"_hang": 1}]
    out = run(one(World(tmp_path / "a", script=frames), bg_wait_s=2))
    assert out["ended_by"] == "result" and out["outcome"] == "done"
    frames[1] = dict(frames[1], task_type="local_agent")
    w = World(tmp_path / "b", script=frames)
    out = run(one(w, bg_wait_s=0.3))
    assert out["ended_by"] == "bg_wait_ceiling" and w.interrupts == 1


def test_no_schema_with_agent(tmp_path):
    """M16: output_format with an agent main thread is refused (PR8: the report is parsed)."""
    w = World(tmp_path)
    with pytest.raises(ValueError, match="output_format"):
        w.session(output_format={"type": "json_schema", "schema": {}})
    assert w.session(agent=None, output_format={"type": "json_schema", "schema": {}})


def exit_of(out):
    return sdk.exit_code(out)


def test_plan_gate_unattended(tmp_path):
    """M17: host none + init plan + status blocked or None -> gate plan, exit 5; done -> no gate."""
    out = run(one(World(tmp_path / "a", script=script("stream_plan.jsonl"))))
    assert (out["outcome"], out["gate"], out["needs_user"], exit_of(out)) == ("unknown", "plan", None, 5)
    blocked = [sys_frame("init", permissionMode="plan"), result("STATUS: blocked\nRESULT: the plan", 0.1),
               sys_frame("session_state_changed", state="idle")]
    out = run(one(World(tmp_path / "b", script=blocked)))
    assert (out["outcome"], out["gate"], exit_of(out)) == ("blocked", "plan", 5)
    done = [blocked[0], result("STATUS: done\nRESULT: x", 0.1), blocked[2]]
    out = run(one(World(tmp_path / "c", script=done)))
    assert (out["gate"], exit_of(out)) == (None, 0)
    out = run(one(World(tmp_path / "d", script=script("stream_ask.jsonl"))))
    assert (out["outcome"], out["needs_user"], out["gate"], exit_of(out)) == ("blocked", True, "ask", 5)


def test_text_report_outcome(tmp_path):
    """M29: a text report is unknown, never done; needs_user None under host none, False otherwise."""
    frames = [sys_frame("init", permissionMode="acceptEdits"), result("Just prose " + LEAK, 0.1),
              sys_frame("session_state_changed", state="idle")]
    out = run(one(World(tmp_path / "a", script=frames), permission_mode="acceptEdits"))
    assert (out["outcome"], out["needs_user"], out["gate"], exit_of(out)) == ("unknown", None, None, 1)
    out = run(one(World(tmp_path / "b", script=frames), host=lambda *a: None))
    assert (out["outcome"], out["needs_user"], exit_of(out)) == ("unknown", False, 1)


def test_interrupt_outcome(tmp_path):
    """M19: aborted_* is interrupted, even with a done report in the text."""
    o = sdk.parse_stream([json.dumps(result("STATUS: done\nRESULT: x", 0.1, terminal_reason="aborted_tools"))])
    assert o["outcome"] == "interrupted" and sdk.exit_code(o) == 1
    o = sdk.parse_stream([json.dumps(result("x", 0.1, subtype="error_max_budget_usd", is_error=True))])
    assert o["outcome"] == "partial"
    o = sdk.parse_stream([json.dumps(result("x", 0.1, subtype="error_during_execution", is_error=True))])
    assert o["outcome"] == "error" and sdk.parse_stream([])["outcome"] == "error"


def test_graceful_close(tmp_path, monkeypatch, capsys):
    """M9: disconnect() on an exception, on a cancellation, and on SIGTERM/SIGHUP to the CLI."""
    w = World(tmp_path / "a", script=[{"_hang": 1}])

    async def boom():
        async with w.session():
            raise KeyError("app bug")
    with pytest.raises(KeyError):
        run(boom())
    assert w.closed == 1

    async def cancelled():
        t = asyncio.ensure_future(one(w))
        await asyncio.sleep(0.3)
        t.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await t
    run(cancelled())
    assert w.closed == 2
    cli = tmp_path / "claude"
    cli.write_text("#!/bin/sh\n")
    cli.chmod(0o755)
    for sig in ("SIGTERM", "SIGHUP"):
        x = World(tmp_path / sig, script=[sys_frame("init", permissionMode="plan"), {"_signal": sig}, {"_hang": 1}])
        monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(x.config))
        monkeypatch.setenv("XDG_STATE_HOME", str(x.state))
        assert sdk.main(["--budget-usd", "1", "--cli", str(cli), "go"], transport=x.factory) == 1
        out = json.loads(capsys.readouterr().out)
        assert (out["outcome"], out["ended_by"], x.interrupts, x.closed) == ("interrupted", "signal", 1, 1), sig


def test_no_sdk_hooks(tmp_path):
    """M11: no programmatic hook by default, for every host; hooks and agents are refused."""
    w = World(tmp_path)
    for host in ("none", lambda *a: None):
        assert w.session(host=host).build(True).hooks is None
    for k in ("hooks", "agents", "can_use_tool"):
        with pytest.raises(ValueError, match="refused"):
            w.session(**{k: {"x": 1}})


def test_no_policy_overlay(tmp_path):
    """M21: no settings overlay by default, user always a source; overlays touching the policy are refused."""
    w = World(tmp_path)
    o = w.session().build(True)
    assert o.settings is None and "user" in o.setting_sources
    for bad in ('{"hooks": {}}', '{"permissions": {"allow": ["Bash"]}}', '{"defaultMode": "acceptEdits"}',
                '{"disableAllHooks": true}', "/nonexistent/settings.json"):
        with pytest.raises(ValueError):
            w.session(settings=bad)
    with pytest.raises(ValueError):
        w.session(sources=("project", "local"))
    assert w.session(settings='{"model": "sonnet"}').build(True).settings == '{"model": "sonnet"}'


def test_cli_path_policy(tmp_path, monkeypatch, capsys):
    """M18: no silent fallback to the bundled CLI."""
    monkeypatch.setenv("PATH", str(tmp_path / "empty"))
    w = World(tmp_path)
    with pytest.raises(sdk.CliNotFound):
        sdk.Session(config_dir=str(w.config), budget_usd=1)
    with pytest.raises(sdk.CliNotFound):
        sdk.Session(config_dir=str(w.config), budget_usd=1, cli=str(tmp_path / "nope"))
    assert sdk.main(["--budget-usd", "1", "go"], transport=w.factory) == 4 and w.opened == []
    assert sdk.Session(config_dir=str(w.config), budget_usd=1, cli="bundled").cli_path is None
    (tmp_path / "empty").mkdir()
    (tmp_path / "empty" / "claude").write_text("#!/bin/sh\n")
    (tmp_path / "empty" / "claude").chmod(0o755)
    assert sdk.Session(config_dir=str(w.config), budget_usd=1).cli_path == str(tmp_path / "empty" / "claude")


def test_print_options_diff(tmp_path, monkeypatch, capsys):
    """D15: for the v1 flags, --print-options differs from v1 only by the host-none keys."""
    w = World(tmp_path)
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(w.config))
    argv = ["--agent", "coder", "--max-turns", "3", "--budget-usd", "0.5", "--allowed-tools", "Read,Grep",
            "--disallowed-tools", "WebFetch", "--resume", "sess-1", "--json-reports", "hi"]
    assert sdk.main(argv + ["--print-options", "--cli", "bundled"]) == 0
    new = json.loads(capsys.readouterr().out)
    o = sdk.options("coder", 3, 0.5, ["Read", "Grep"], ["WebFetch"], None, "sess-1", json_reports=True)
    old = json.loads(json.dumps({f.name: getattr(o, f.name) for f in __import__("dataclasses").fields(o)}, default=repr))
    diff = {k for k in old if old[k] != new[k]}
    assert diff == {"disallowed_tools", "extra_args", "env", "include_hook_events"}
    assert new["disallowed_tools"] == ["WebFetch", "ExitPlanMode", "Agent(coder)", "Agent(newbie)", "Workflow"]
    assert new["extra_args"] == {"permission-prompts": "none", "agent": "coder"} and new["include_hook_events"]
    assert new["env"] == {"CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS": "3000", "CLAUDE_CODE_EMIT_SESSION_STATE_EVENTS": "1",
                          "STACK_REPORT_FORMAT": "json"}


# ---------------------------------------------------------------- D3 tty
class Term:
    """A TtyHost on two pipes: `type()` is the user's keyboard, `shown()` the terminal output."""

    def __init__(self, timeout_s=2.0):
        self.kr, self.kw = os.pipe()
        self.sr, self.sw = os.pipe()
        os.set_blocking(self.sr, False)
        self.host, self.buf, self.at = sdk.TtyHost(fds=(self.kr, self.sw), timeout_s=timeout_s), "", 0

    def type(self, text):
        os.write(self.kw, (text + "\n").encode())

    def shown(self):
        with contextlib.suppress(BlockingIOError):
            while chunk := os.read(self.sr, 65536):
                self.buf += chunk.decode("utf-8", "replace")
        return self.buf

    async def answer_when(self, pattern, reply, timeout=3):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            m = re.search(pattern, self.shown()[self.at:])      # only what the newest prompt showed
            if m:
                self.at = len(self.buf)
                self.type(reply(m) if callable(reply) else reply)
                return
            await asyncio.sleep(0.02)
        raise AssertionError(f"never shown: {pattern}")


class Ctx:
    agent_id = None


def test_tty_sanitizes():
    """M20: control, escape, OSC and bidi characters never reach the terminal; long text is capped."""
    t = Term()
    evil = "\x1b[2J\x1b]0;pwned\x07\u202eevil\u2066 \x9b31m \r" + "A" * 5000

    async def go():
        task = asyncio.ensure_future(t.host("Bash", {"command": evil}, Ctx()))
        await t.answer_when(r"allow once\? \[y/N\]:", "n")
        return await task
    r = run(go())
    out = t.shown()
    assert isinstance(r, PermissionResultDeny) and getattr(r, "updated_permissions", None) is None
    assert not re.search("[\x00-\x08\x0b-\x1f\x7f-\x9f\u202a-\u202e\u2066-\u2069]", out)
    assert "more chars]" in out and len(out) < 3000


def test_tty_answers_and_never_persists():
    t = Term()
    q = {"questions": [{"question": "db?", "options": [{"label": "sqlite"}, {"label": "pg"}]}]}

    async def go():
        task = asyncio.ensure_future(t.host("AskUserQuestion", q, Ctx()))
        await t.answer_when(r"answer \(number", "2")
        a = await task
        task = asyncio.ensure_future(t.host("Bash", {"command": "ls"}, Ctx()))
        await t.answer_when(r"allow once", "y")
        return a, await task
    a, b = run(go())
    assert a.updated_input["answers"] == {"db?": "pg"} and a.updated_permissions is None
    assert isinstance(b, PermissionResultAllow) and b.updated_permissions is None


def test_tty_no_stale_answer():
    """M27: a line typed after a prompt timed out does not answer the next prompt."""
    t = Term(timeout_s=0.3)

    async def go():
        first = await t.host("Bash", {"command": "ls"}, Ctx())          # nobody answers: denied
        t.type("y")                                                      # too late: typed for prompt 1
        await asyncio.sleep(0.2)
        second = await t.host("Bash", {"command": "rm -rf build"}, Ctx())
        return first, second
    first, second = run(go())
    assert isinstance(first, PermissionResultDeny) and isinstance(second, PermissionResultDeny)


def test_tty_plan_nonce():
    """M28: plan approval needs the 4-digit nonce printed with the plan; y is not enough."""
    t = Term()

    async def go(reply):
        task = asyncio.ensure_future(t.host("ExitPlanMode", {"plan": "1. build " + LEAK}, Ctx()))
        await t.answer_when(r"type (\d{4}) to approve", reply)
        return await task
    assert isinstance(run(go("y")), PermissionResultDeny)
    assert isinstance(run(go(lambda m: m.group(1))), PermissionResultAllow)
    assert isinstance(run(go(lambda m: f"{(int(m.group(1)) + 1) % 10000:04d}")), PermissionResultDeny)


def test_tty_eof_denies_and_no_tty_is_usage(tmp_path):
    t = Term()
    os.close(t.kw)

    async def go():
        return await t.host("Bash", {"command": "ls"}, Ctx())
    assert isinstance(run(go()), PermissionResultDeny)
    with pytest.raises(sdk.UsageError):
        sdk.TtyHost(path=str(tmp_path / "no-tty"))


def test_tty_session_denies_before_load_check(tmp_path):
    """D2: the tty and callable hosts deny every tool until the load check passed."""
    seen = []
    w = World(tmp_path)
    s = w.session(host=lambda *a: seen.append(a) or PermissionResultAllow())
    r = run(s._can_use_tool("Bash", {"command": "ls"}, Ctx()))
    assert isinstance(r, PermissionResultDeny) and seen == []
