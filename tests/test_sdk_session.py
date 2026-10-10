"""$0 tests of stack_sdk v2 (SDK-2): Session over FakeCLI, a Transport that speaks the SDK's control protocol
(initialize, can_use_tool, interrupt) and plays the synthetic streams in tests/fixtures/sdk/stream_*.jsonl.
The SDK's subprocess transport is disabled: nothing reaches a CLI or the API. Each T_* test names the
design's mutants (M1-M33, .claude-work/sdk/sdk2-design.md) it kills.

Run: uv run --no-project --python 3.13 --with pytest --with claude-agent-sdk==0.2.163 pytest -q tests/test_sdk_session.py
"""
import asyncio
import contextlib
import dataclasses
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
from claude_agent_sdk._internal.transport.subprocess_cli import SubprocessCLITransport
from claude_agent_sdk.types import PermissionRuleValue, PermissionUpdate

ROOT = Path(__file__).resolve().parents[1]
HELPER = Path(os.environ.get("SDK_HELPER") or ROOT / "dot-config" / "dot-claude" / "bin" / "stack_sdk.py")  # tests/sdk_mutations.py
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
        kw.setdefault("cwd", str(self.config.parent))       # no repository's .claude/agents above it
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
        if events:
            self.hook("hook_response", "h1", self.w.outcome)
        if self.w.late_marker and self.w.marker:     # the guard is the later hook: its marker lands between
            await asyncio.sleep(0.2)
            self.write_marker()
        if events:
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


async def connect_only(w, **kw):
    async with w.session(**kw):
        pass


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
    with pytest.raises(sdk.StackNotLoaded, match="drifted off plan: 'acceptEdits'"):
        run(one(w3))                                                 # assumed plan; the server says otherwise
    assert len(w3.opened) == 1 and "prompt" not in w3.log            # SDK-2r S3: fail closed, no reconnect


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
    out = run(one(World(tmp_path / "e", script=blocked), host=lambda *a: None))
    assert (out["gate"], exit_of(out)) == (None, 1)                  # the plan gate is host none's only


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


GATE = {"useAutoModeDuringPlan": False, "sandbox": {"autoAllowBashIfSandboxed": False}}   # probe E1


def test_no_policy_overlay(tmp_path):
    """M21: no caller overlay by default (host none: the E1 gate only), user always a source; overlays touching
    the policy, not an object or not strict JSON are refused."""
    w = World(tmp_path)
    o = w.session().build(True)
    assert json.loads(o.settings) == GATE and "user" in o.setting_sources
    assert w.session(host=lambda *a: None).build(True).settings is None
    for bad in ('{"hooks": {}}', '{"permissions": {"allow": ["Bash"]}}', '{"defaultMode": "acceptEdits"}',
                '{"disableAllHooks": true}', "/nonexistent/settings.json", [1], '{"x": NaN}', {"x": float("inf")}):
        for host in ("none", lambda *a: None):
            with pytest.raises(ValueError, match="may touch") as e:
                w.session(settings=bad, host=host)
            assert "host none" not in str(e.value)                  # the policy check refused it, not host none
    with pytest.raises(ValueError):
        w.session(sources=("project", "local"))
    with pytest.raises(ValueError, match="none under host none"):
        w.session(settings='{"model": "sonnet"}')
    assert w.session(settings='{"model": "sonnet"}', host=lambda *a: None).build(True).settings == '{"model": "sonnet"}'


def test_host_none_refuses_every_overlay(tmp_path):
    """E1 review F1: CLI 2.1.287 skips a whole --settings source on any schema error, so a caller key sharing
    PLAN_GATE's source could drop the gate: host none refuses every non-empty overlay and sends the gate alone."""
    w = World(tmp_path)
    for v in ('{"cleanupPeriodDays": 0}', '{"model": "sonnet"}', {"model": "x"}, '{"PreToolUse": []}'):
        with pytest.raises(ValueError, match="none under host none"):
            w.session(settings=v)
        assert w.session(settings=v, host=lambda *a: None).build(True).settings is not None
    for v in ("{}", {}):
        assert json.loads(w.session(settings=v).build(True).settings) == GATE
    with pytest.raises(ValueError, match="sources must include user") as e:     # another cause, another host
        w.session(settings='{"model": "x"}', host=lambda *a: None, sources=("project",))
    assert "host none" not in str(e.value)


def test_overlay_sent_as_read_for_every_host(tmp_path, monkeypatch):
    """E1 review F2: tty and callable hosts get the overlay that passed the check, as JSON text read once at
    Session(): never the raw path (the CLI would resolve it against its own cwd and re-read it) nor a dict."""
    app, repo = tmp_path / "app", tmp_path / "repo"
    for d, body in ((app, {"model": "x"}), (repo, {"permissions": {"allow": ["Bash"]}, "hooks": {}})):
        d.mkdir()
        (d / "o.json").write_text(json.dumps(body))
    monkeypatch.chdir(app)
    w = World(tmp_path / "w")
    for v in ("o.json", str(app / "o.json"), {"model": "x"}, '{"model": "x"}'):
        o = w.session(settings=v, host=lambda *a: None, cwd=str(repo)).build(True)
        assert isinstance(o.settings, str) and json.loads(o.settings) == {"model": "x"}
        cmd = SubprocessCLITransport(prompt="x", options=dataclasses.replace(o, cli_path=sys.executable))._build_command()
        assert cmd.count("--settings") == 1 and json.loads(cmd[cmd.index("--settings") + 1]) == {"model": "x"}


def test_plan_gate_overlay(tmp_path):
    """E1: host none's --settings turns plan's auto-mode classifier and the sandbox's Bash auto-allow off, under
    plan and a waived gate alike; no caller overlay (text, file, dict) can set either key, nor change after the check."""
    w = World(tmp_path)
    f = tmp_path / "s.json"
    for v in ('{"useAutoModeDuringPlan": true}', '{"sandbox": {"autoAllowBashIfSandboxed": true}}', str(f),
              {"useAutoModeDuringPlan": True}, '{"model": "x", "useAutoModeDuringPlan": null}'):
        f.write_text('{"useAutoModeDuringPlan": true}')
        for host in ("none", lambda *a: None):
            with pytest.raises(ValueError, match="useAutoModeDuringPlan") as e:
                w.session(settings=v, host=host)
            assert "host none" not in str(e.value)                  # refused as a policy key, for every host
    for mode in (None, "plan", "acceptEdits", "default"):
        assert json.loads(w.session(permission_mode=mode).build(mode in (None, "plan")).settings) == GATE
    f.write_text('{"model": "x"}')
    for v in (str(f), {"model": "x"}):
        s = w.session(settings=v, host=lambda *a: None)
        f.write_text('{"model": "y", "hooks": {}}')                 # swapped after the check: never read again
        if isinstance(v, dict):
            v["hooks"] = {}                                          # the caller's dict, changed after the check
        s.kw["settings"] = '{"useAutoModeDuringPlan": true}'
        assert json.loads(s.build(True).settings) == {"model": "x"}
        f.write_text('{"model": "x"}')
    o = dataclasses.replace(w.session().build(True), cli_path=sys.executable)
    cmd = SubprocessCLITransport(prompt="x", options=o)._build_command()             # what the CLI would get
    assert cmd.count("--settings") == 1 and json.loads(cmd[cmd.index("--settings") + 1]) == GATE


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
    assert diff == {"disallowed_tools", "extra_args", "env", "include_hook_events", "permission_mode", "settings"}
    assert new["permission_mode"] == "plan" and json.loads(new["settings"]) == GATE   # host none: the gate explicitly
    assert new["disallowed_tools"] == ["WebFetch", "ExitPlanMode", "Agent(coder)", "Agent(newbie)", "Workflow"]
    assert new["extra_args"] == {"permission-prompts": "none", "agent": "coder"} and new["include_hook_events"]
    assert new["env"] == {"CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS": "3000", "CLAUDE_CODE_EMIT_SESSION_STATE_EVENTS": "1",
                          "STACK_REPORT_FORMAT": "json", "CLAUDE_CODE_SESSION_KIND": ""}     # E2a


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
    assert "more chars]" in "".join(ln[4:] for ln in out.splitlines()) and len(out) < 4000


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


# ---------------------------------------------------------------- SDK-2r review findings (each proof failed on d1531a73)
def test_project_agents_do_not_pass_the_plan_gate(tmp_path):
    """S1: a repository's .claude/agents (a new builder, or an inherit name reused as acceptEdits) fails closed."""
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    (repo / ".claude" / "agents").mkdir(parents=True)
    (repo / ".claude" / "agents" / "explore.md").write_text("---\nname: explore\npermissionMode: acceptEdits\n---\nx\n")
    w = World(tmp_path / "w", script=script("stream_plan.jsonl"))
    with pytest.raises(sdk.StackNotLoaded, match="plan gate"):
        run(connect_only(w, cwd=str(repo / "sub" if (repo / "sub").mkdir() is None else repo)))  # at connect()
    assert "prompt" not in w.log
    w2 = World(tmp_path / "w2", script=script("stream_plan.jsonl"), server_agents=[*AGENTS, "repo-builder"])
    with pytest.raises(sdk.StackNotLoaded, match="plan gate"):
        run(one(w2))                                                 # a name the stack does not know
    assert "prompt" not in w2.log
    w3 = World(tmp_path / "w3", script=script("stream_tree.jsonl"), mode="acceptEdits",
               server_agents=[*AGENTS, "repo-builder", "plug:helper"])
    assert run(one(w3, cwd=str(repo), permission_mode="acceptEdits"))["gate_waived"] is True   # explicit: waived


def test_refusals_hold_for_every_spelling(tmp_path):
    """S2 C2: D5/M5/M21 refusals cover every spelling and alias; a server in bypassPermissions is refused."""
    w = World(tmp_path)
    for extra in ({"permission-mode=bypassPermissions": None}, {"Permission_Mode": "bypassPermissions"},
                  {"permission-prompt-tool=mcp__x__y": None}, {"--permission-mode": "plan"},
                  {"settings": '{"permissions": {"defaultMode": "bypassPermissions"}}'},
                  {"setting-sources": "project,local"}, {"disallowed-tools": "x"}, {"add-dir": "/"}):
        with pytest.raises(ValueError, match="refused"):
            w.session(extra_args=extra)
    for kw in ({"sandbox": {"enabled": False}}, {"settings": '{"sandbox": {"enabled": false}}'},
               {"max_budget_usd": None}, {"max_budget_usd": 1000.0}, {"setting_sources": ["project"]}):
        with pytest.raises(ValueError):
            w.session(**kw)
    with pytest.raises(ValueError, match="may touch"):         # a callable too: not host none's no-overlay rule (F1)
        w.session(settings='{"sandbox": {"enabled": false}}', host=lambda *a: None)
    assert w.session(extra_args={"debug": None, "model": "x"}).build(True).extra_args["debug"] is None
    for i, host in enumerate(("none", lambda *a: None)):
        b = World(tmp_path / f"b{i}", script=script("stream_plan.jsonl"), mode="bypassPermissions")
        with pytest.raises(sdk.StackNotLoaded, match="bypassPermissions"):
            run(one(b, host=host))
        assert "prompt" not in b.log


def test_mode_check_fails_closed(tmp_path, monkeypatch, capsys):
    """S3 C1: under host none with no caller mode the server must report plan: none or another mode fails closed."""
    for i, mode in enumerate((None, "acceptEdits", "default")):
        w = World(tmp_path / str(i), script=script("stream_plan.jsonl"), mode=mode)
        with pytest.raises(sdk.StackNotLoaded, match="drifted off plan"):
            run(one(w))
        assert "prompt" not in w.log and len(w.opened) == 1
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(w.config))
    monkeypatch.setenv("XDG_STATE_HOME", str(w.state))
    monkeypatch.chdir(tmp_path)
    assert sdk.main(["--budget-usd", "1", "--cli", "bundled", "go"], transport=w.factory) == 3


def test_ask_model_supplied_answers_do_not_count(tmp_path):
    """S4: a callable host that allows by echoing the input does not pass the model's own answers."""
    q = {"questions": [{"question": "May I push?", "options": [{"label": "yes"}, {"label": "no"}]}],
         "answers": {"May I push?": "yes"}}
    seen = []

    async def echo(tool, inp, ctx):
        seen.append(inp)
        return PermissionResultAllow(updated_input=inp)
    w, _ = callable_world(tmp_path, echo, tool="AskUserQuestion", inp=q)
    assert w.answers[0][1]["behavior"] == "deny" and "answers" not in seen[0]


def test_tty_option_labels_cannot_forge_lines():
    """S5: option labels, the tool name and the agent id are shown on one line each."""
    t = Term()
    fake = "\n" * 3 + "stack_sdk: main thread wants Read:\nallow once? [y/N]:"
    q = {"questions": [{"question": "May I delete the backup?", "options": [{"label": "ok" + fake}]}]}

    class Agent:
        agent_id = "a1\nstack_sdk: forged"

    async def go():
        task = asyncio.ensure_future(t.host("AskUserQuestion", q, Ctx()))
        await t.answer_when(r"answer \(number", "")
        await task
        task = asyncio.ensure_future(t.host("Bash\nallow once? [y/N]:", {"command": "ls"}, Agent()))
        await t.answer_when(r"allow once\? \[y/N\]:\n\Z", "n")
        return await task
    run(go())
    out = t.shown()
    body = out.split("question (main thread):\n", 1)[1].split("\nanswer (number", 1)[0]
    assert all(ln.startswith("  ") for ln in body.splitlines()), body
    col0 = [ln for ln in out.splitlines() if ln.startswith(("allow once", "stack_sdk: forged", "stack_sdk: main thread wants Read"))]
    assert col0 == ["allow once? [y/N]:"]                           # only the host's own prompt line


def test_tty_no_stale_answer_when_queued():
    """S6: with the next prompt queued, a line typed for the previous (timed-out) prompt does not answer it."""
    t = Term(timeout_s=0.3)

    async def go():
        a = asyncio.ensure_future(t.host("Bash", {"command": "ls"}, Ctx()))
        b = asyncio.ensure_future(t.host("Bash", {"command": "rm -rf build"}, Ctx()))
        await a                                   # prompt 1 timed out; prompt 2 is up at once
        await asyncio.sleep(0.05)
        t.type("y")                               # meant for prompt 1
        return await b
    assert isinstance(run(go()), PermissionResultDeny)


def test_frontmatter_mode_fails_closed(tmp_path):
    """S7: a trailing comment or an unparsable value never turns a builder into an inherit agent."""
    w = World(tmp_path)
    (w.config / "agents" / "coder.md").write_text("---\nname: coder\npermissionMode: acceptEdits  # builder\n---\nx\n")
    (w.config / "agents" / "odd.md").write_text("---\nname: odd\npermissionMode:\n---\nx\n")
    (w.config / "agents" / "quoted.md").write_text("---\nname: quoted\npermissionMode: 'plan'  # ok\n---\nx\n")
    deny = w.session().preview().disallowed_tools
    assert {"Agent(coder)", "Agent(odd)"} <= set(deny) and "Agent(quoted)" not in deny


def test_deadline_zero_keeps_the_bound(tmp_path):
    """S8: deadline_s <= 0 never removes host none's time bound."""
    w = World(tmp_path)
    assert w.session(deadline_s=0).deadline_s == 3600 and w.session(deadline_s=-5).deadline_s == 3600
    assert w.session(deadline_s=12).deadline_s == 12


def test_cli_crash_is_an_error_outcome(tmp_path, monkeypatch, capsys):
    """C3: a CLI that exits non-zero gives outcome error (dict and row); the CLI prints one JSON line."""
    from claude_agent_sdk import ProcessError

    class Crash(FakeCLI):
        async def play(self):
            self.emit(sys_frame("init", permissionMode="plan"))
            await asyncio.sleep(0.05)
            self.emit({"_crash": 1})

        async def read_messages(self):
            while (m := await self.q.get()) is not None:
                if "_crash" in m:
                    raise ProcessError("Command failed with exit code 137", exit_code=137)
                yield m
    w = World(tmp_path)
    w.factory = lambda o: (w.opened.append(o), Crash(w, o))[1]
    out = run(one(w))
    assert (out["outcome"], out["ended_by"]) == ("error", "eof") and "exit code 137" in out["error"]
    assert w.rows()[-1]["outcome"] == "error"
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(w.config))
    monkeypatch.setenv("XDG_STATE_HOME", str(w.state))
    monkeypatch.chdir(tmp_path)
    assert sdk.main(["--budget-usd", "1", "--cli", "bundled", "go"], transport=w.factory) == 1
    assert json.loads(capsys.readouterr().out)["outcome"] == "error"

    class BadResume(FakeCLI):
        async def write(self, data):
            if json.loads(data).get("request", {}).get("subtype") == "initialize":
                raise ProcessError("No conversation found", exit_code=1)
            await super().write(data)
    w.factory = lambda o: (w.opened.append(o), BadResume(w, o))[1]
    assert sdk.main(["--budget-usd", "1", "--cli", "bundled", "go"], transport=w.factory) == 1
    out = json.loads(capsys.readouterr().out)
    assert out["outcome"] == "error" and w.rows()[-1]["outcome"] == "error"


def test_second_ask_gets_its_own_reply(tmp_path):
    """C4: frames of a turn the CLI woke for after an ask returned never answer the next ask."""
    class Woken(FakeCLI):
        async def play(self):
            self.k = getattr(self, "k", 0) + 1
            self.emit(sys_frame("session_state_changed", state="running"))
            self.emit(result(f"STATUS: done\nRESULT: reply {self.k}", 0.1 * self.k))
            self.emit(sys_frame("session_state_changed", state="idle"))
            if self.k == 1:                       # a background task wakes the session after ask 1 returned
                await asyncio.sleep(0.2)
                self.emit(sys_frame("session_state_changed", state="running"))
                self.emit(result("STATUS: done\nRESULT: woken turn", 0.15, origin={"kind": "task-notification"}))
                self.emit(sys_frame("session_state_changed", state="idle"))
    w = World(tmp_path)
    w.factory = lambda o: (w.opened.append(o), Woken(w, o))[1]

    async def go():
        async with w.session() as s:
            a = await s.ask("one")
            await asyncio.sleep(0.5)
            return a, await s.ask("two")
    a, b = run(go())
    assert a["report"]["result"] == "reply 1" and b["report"]["result"] == "reply 2"


def test_first_message_s_measures_the_prompt(tmp_path):
    """C5: first_message_s counts from the prompt, not from the pre-prompt hook frames."""
    w = World(tmp_path, script=[{"_sleep": 0.3}] + script("stream_plan.jsonl"))
    assert run(one(w))["first_message_s"] >= 0.25


def test_stop_with_a_reason_interrupts(tmp_path):
    """C6: stop(why) with any reason interrupts and reports interrupted."""
    w = World(tmp_path, script=[sys_frame("init", permissionMode="plan"), {"_hang": 1}])

    async def go():
        async with w.session() as s:
            t = asyncio.ensure_future(s.ask("go"))
            await asyncio.sleep(0.3)
            s.stop("user")
            return await t
    out = run(go())
    assert (out["outcome"], out["ended_by"], w.interrupts) == ("interrupted", "cancelled", 1)


def test_reconnect_after_eof_still_bounds(tmp_path):
    """C7: a Session reconnected after its CLI exited still enforces the deadline and interrupts."""
    class Eof(FakeCLI):
        async def play(self):
            if self.n == 1:
                self.emit(result("STATUS: done\nRESULT: x", 0.1))
                self.q.put_nowait(None)                       # the CLI exits after the result
    w = World(tmp_path)
    w.factory = lambda o: (w.opened.append(o), Eof(w, o))[1]

    async def go():
        s = w.session(deadline_s=0.5)
        async with s:
            a = await s.ask("one")
        async with s:
            return a, await s.ask("two")
    _a, b = run(go())
    assert (b["ended_by"], b["outcome"], w.interrupts) == ("deadline", "partial", 1)


def test_closed_tty_reader_does_not_steal_a_reused_fd():
    """C8: close() stops the reader thread before the fd number can be reused, and is idempotent."""
    kr, kw = os.pipe()
    _sr, sw = os.pipe()
    h = sdk.TtyHost(fds=(kr, sw))
    time.sleep(0.2)
    t0 = time.monotonic()
    h.close()
    assert not h.thread.is_alive() and time.monotonic() - t0 < 0.8   # it stopped itself (no 1 s join timeout)
    nr, nw = os.pipe()                                            # likely the reader's old fd number
    h.close()                                                     # idempotent: never closes a reused number
    with contextlib.suppress(OSError):
        os.write(kw, b"x\n")
    time.sleep(0.2)
    os.write(nw, b"app-data\n")
    time.sleep(0.4)
    got = []
    while not h.q.empty():
        got.append(h.q.get_nowait()[1])
    assert "app-data" not in got and not h.thread.is_alive()
    assert os.read(nr, 100) == b"app-data\n"                     # still there for its real owner


# ---------------------------------------------------------------- SDK-2r round 2 (each proof failed on 29bf3224)
def test_project_agents_any_layout_fail_closed(tmp_path):
    """R1: subdirectories, dotfiles, an empty directory and a linked worktree's main checkout (CLI 2.1.287)."""
    fm = "---\nname: explore\ndescription: x\npermissionMode: acceptEdits\n---\nx\n"
    for i, rel in enumerate(("team/explore.md", ".explore.md", None)):
        repo = tmp_path / f"r{i}"
        (repo / ".git").mkdir(parents=True)
        (repo / ".claude" / "agents").mkdir(parents=True)
        if rel:
            f = repo / ".claude" / "agents" / rel
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text(fm)
        w = World(tmp_path / f"w{i}", script=script("stream_plan.jsonl"))
        with pytest.raises(sdk.StackNotLoaded, match="plan gate"):
            run(one(w, cwd=str(repo)))
        assert "prompt" not in w.log
    main, wt = tmp_path / "main", tmp_path / "wt"
    (main / ".git" / "worktrees" / "wt").mkdir(parents=True)
    (main / ".git" / "worktrees" / "wt" / "commondir").write_text("../..\n")
    (main / ".claude" / "agents").mkdir(parents=True)
    (main / ".claude" / "agents" / "explore.md").write_text(fm)
    wt.mkdir()
    (wt / ".git").write_text(f"gitdir: {main}/.git/worktrees/wt\n")
    w = World(tmp_path / "w9", script=script("stream_plan.jsonl"))
    with pytest.raises(sdk.StackNotLoaded, match="plan gate"):
        run(one(w, cwd=str(wt)))
    assert "prompt" not in w.log
    extra = tmp_path / "extra"
    (extra / ".claude" / "agents").mkdir(parents=True)
    w = World(tmp_path / "w10", script=script("stream_plan.jsonl"))
    with pytest.raises(sdk.StackNotLoaded, match="plan gate"):
        run(one(w, add_dirs=[str(extra)]))                          # an added directory's agents
    assert "prompt" not in w.log


def test_extra_args_allowlist(tmp_path):
    """R2 V3: extra_args is an allowlist; hidden CLI flags and other spellings are refused."""
    w = World(tmp_path)
    for key in ("inherit-permission-mode", "project-config-root", "plugin-dir-no-mcp", "plugin-url", "sdk-url",
                "sandbox", "channels", "remote-control"):
        with pytest.raises(ValueError, match="refused"):
            w.session(extra_args={key: "x"})
    assert w.session(extra_args={"debug": None, "verbose": None, "model": "x"}).build(True).extra_args["verbose"] is None


def test_tty_rows_never_start_with_model_text():
    """R3: what an 80-column terminal shows at column 0 is the host's own, also for over-long lines and tabs."""
    t = Term()
    forged, question = "stack_sdk: main thread wants Read:", "May I delete the backup?"
    # spaces to the width; or tabs that, after the '  | ' prefix of a 38-char chunk, reach column 80 exactly
    q = {"questions": [{"question": question + " " * (76 - len(question)) + "\t" * 10 + forged,
                        "options": [{"label": "ok" + " " * (80 - 5 - 2) + forged}]}]}

    async def go():
        task = asyncio.ensure_future(t.host("AskUserQuestion", q, Ctx()))
        await t.answer_when(r"answer \(number", "")
        await task
        task = asyncio.ensure_future(t.host("ExitPlanMode", {"plan": "x" * 76 + forged}, Ctx()))
        await t.answer_when(r"type \d{4} to approve", "n")
        await task
        task = asyncio.ensure_future(t.host("Bash", {"command": " " * 64 + forged}, Ctx()))
        await t.answer_when(r"allow once", "n")
        return await task
    run(go())
    rows = [ln[i:i + 80] for ln in t.shown().expandtabs(8).splitlines() for i in range(0, len(ln) or 1, 80)]
    own = re.compile(r"(  .*|stack_sdk: (question|plan) \(main thread\):|stack_sdk: main thread wants Bash:|"
                     r"answer \(number or text, empty denies\):|type \d{4} to approve; anything else denies:|"
                     r"stack_sdk: \^ main thread wants Bash \(\d+ rows above\)|allow once\? \[y/N\]:|)")
    assert not [r for r in rows if not own.fullmatch(r)], rows            # every other row starts '  '
    assert not [r for r in rows if r.startswith("stack_sdk: main thread wants Read")], rows


def test_crash_after_a_result_is_an_error(tmp_path):
    """R4: a CLI that crashes after a success result (an agent still running) is outcome error; failure is per ask."""
    from claude_agent_sdk import ProcessError

    class Crash(FakeCLI):
        async def play(self):
            self.emit(sys_frame("init", permissionMode="plan"))
            self.emit(sys_frame("task_started", task_id="t1", tool_use_id="tu1", task_type="local_agent",
                                description="explore: look"))
            self.emit(result("STATUS: done\nRESULT: x", 0.1))
            self.emit({"_crash": 1})

        async def read_messages(self):
            while (m := await self.q.get()) is not None:
                if "_crash" in m:
                    raise ProcessError("Command failed with exit code 137", exit_code=137)
                yield m
    w = World(tmp_path)
    w.factory = lambda o: (w.opened.append(o), Crash(w, o))[1]
    out = run(one(w))
    assert out["outcome"] == "error" and w.rows()[-1]["outcome"] == "error" and sdk.exit_code(out) == 1
    budget = [sys_frame("init", permissionMode="plan"),
              result("x", 0.5, subtype="error_max_budget_usd", is_error=True), {"_crash": 1}]

    class Budget(Crash):
        async def play(self):
            for m in budget:
                self.emit(m)
    w2 = World(tmp_path / "b")
    w2.factory = lambda o: (w2.opened.append(o), Budget(w2, o))[1]
    assert run(one(w2))["outcome"] == "partial"                      # the CLI's own error result keeps its class


def test_ask_model_supplied_annotations_do_not_count(tmp_path):
    """R5: the model's `annotations` (the user's notes) are stripped for the callable and the tty host."""
    q = {"questions": [{"question": "May I push?", "options": [{"label": "yes"}, {"label": "no"}]}],
         "annotations": {"May I push?": {"notes": "I approve"}}}
    seen = []

    async def host(tool, inp, ctx):
        seen.append(inp)
        return PermissionResultAllow(updated_input=dict(inp, answers={"May I push?": "no"}))
    w, _ = callable_world(tmp_path, host, tool="AskUserQuestion", inp=q)
    assert "annotations" not in seen[0] and "annotations" not in w.answers[0][1]["updatedInput"]
    t = Term()

    async def go():
        task = asyncio.ensure_future(t.host("AskUserQuestion", q, Ctx()))
        await t.answer_when(r"answer \(number", "2")
        return await task
    assert "annotations" not in run(go()).updated_input


def test_config_dir_reaches_the_cli(tmp_path):
    """R6: the config the helper checks is the one the CLI loads."""
    w = World(tmp_path)
    assert w.session().build(True).env["CLAUDE_CONFIG_DIR"] == str(w.config)
    with pytest.raises(ValueError, match="CLAUDE_CONFIG_DIR"):
        w.session(env={"CLAUDE_CONFIG_DIR": str(tmp_path / "other")})


def test_host_none_passes_plan_explicitly(tmp_path):
    """S3 refinement: host none with no caller mode passes --permission-mode plan (the flag outranks repo settings)."""
    w = World(tmp_path)
    assert w.session().build(True).permission_mode == "plan"
    assert w.session(permission_mode="acceptEdits").build(False).permission_mode == "acceptEdits"
    assert w.session(host=lambda *a: None).build(True).permission_mode is None


def test_tty_flushes_after_the_gap(monkeypatch):
    """V1: TCIFLUSH runs once per prompt, after the gap (with the prompt's own sequence number)."""
    import termios
    t = Term()
    seen = []
    monkeypatch.setattr(termios, "tcflush", lambda fd, q: seen.append((fd, q, t.host.seq)))

    async def go():
        for _ in range(2):
            task = asyncio.ensure_future(t.host("Bash", {"command": "ls"}, Ctx()))
            await t.answer_when(r"allow once", "n")
            await task
    run(go())
    assert seen == [(t.kr, termios.TCIFLUSH, 2), (t.kr, termios.TCIFLUSH, 4)]


def test_no_state_frames_agent_in_flight_keeps_reading(tmp_path):
    """V2 (D7 fallback): without state frames a result with an agent in flight does not end the run."""
    frames = [sys_frame("init", permissionMode="acceptEdits"),
              sys_frame("task_started", task_id="t1", tool_use_id="tu-1", description="coder: x", task_type="local_agent"),
              result("dispatched", 0.05), {"_sleep": 0.4},
              sys_frame("task_notification", task_id="t1", tool_use_id="tu-1", status="completed", output_file="/o",
                        summary="s"),
              result("STATUS: done\nRESULT: built", 0.2), {"_hang": 1}]
    w = World(tmp_path, script=frames)
    out = run(one(w, bg_wait_s=5))
    assert (len(out["results"]), out["ended_by"], out["outcome"], w.interrupts) == (2, "result", "done", 0)


# ---------------------------------------------------------------- SDK-2r round 4 (sec-r10; each proof failed on 0eecc14a)
def test_relative_add_dirs_resolve_against_the_session_cwd(tmp_path, monkeypatch):
    """N1: the CLI resolves --add-dir against its own cwd (GRn: path.resolve), not the app's cwd."""
    repo, team, app = tmp_path / "repo", tmp_path / "team", tmp_path / "app" / "x"
    (repo / ".git").mkdir(parents=True)
    (team / ".claude" / "agents").mkdir(parents=True)
    app.mkdir(parents=True)
    monkeypatch.chdir(app)                               # ../team from the app's cwd does not exist
    w = World(tmp_path / "w", script=script("stream_plan.jsonl"))
    with pytest.raises(sdk.StackNotLoaded, match="plan gate"):
        run(one(w, cwd=str(repo), add_dirs=["../team"]))
    assert "prompt" not in w.log


def test_project_agents_appearing_after_connect_fail_the_ask(tmp_path):
    """N2: the gate is re-checked when a prompt is sent, not only at connect."""
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    w = World(tmp_path / "w", script=script("stream_plan.jsonl"))

    async def go():
        async with w.session(cwd=str(repo)) as s:
            (repo / ".claude" / "agents").mkdir(parents=True)     # after the connect-time check
            return await s.ask("go")
    with pytest.raises(sdk.StackNotLoaded, match="plan gate"):
        run(go())
    assert "prompt" not in w.log


def test_extra_args_values_cannot_carry_flags(tmp_path):
    """N3: SDK < 0.2.124 passes ['--debug', '--agents=...'] as two tokens; commander binds no value to an
    optional-value or boolean flag when the next token starts with '-'."""
    w = World(tmp_path)
    for kv in ({"debug": "--agents={}"}, {"verbose": "--settings={}"}, {"verbose": "x"}):
        with pytest.raises(ValueError, match="refused"):
            w.session(extra_args=kv)


def test_tty_answer_line_names_the_tool():
    """N4: a 2000-char input fills more than a 24-row screen; the y/N row must still say what is approved."""
    t = Term()

    async def go():
        task = asyncio.ensure_future(t.host("Bash", {"command": "rm -rf ~/backup; " + " " * 1900 + "# list"}, Ctx()))
        await t.answer_when(r"\[y/N\]:", "n")
        return await task
    run(go())
    rows = t.shown().splitlines()
    host_rows = [r for r in rows[-24:] if not r.startswith("  | ")]
    assert len(rows) > 24 and any("Bash" in r for r in host_rows), host_rows


@pytest.mark.parametrize("kind", ["file", "symlink", "dangling"])
def test_agents_path_of_any_kind_fails_closed(tmp_path, kind):
    """OWN1: .claude/agents as a file, a symlink to a directory, or a dangling symlink fails the gate (lexists)."""
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    (repo / ".claude").mkdir()
    a = repo / ".claude" / "agents"
    if kind == "file":
        a.write_text("x")
    else:
        (tmp_path / "real").mkdir()
        a.symlink_to(tmp_path / ("real" if kind == "symlink" else "missing"))
    w = World(tmp_path / "w", script=script("stream_plan.jsonl"))
    with pytest.raises(sdk.StackNotLoaded, match="plan gate"):
        run(one(w, cwd=str(repo)))
    assert "prompt" not in w.log


def test_agents_found_up_the_parent_chain(tmp_path):
    """OWN2: the walk goes from cwd up through every parent to the repository root."""
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    (repo / ".claude" / "agents").mkdir(parents=True)
    deep = repo / "a" / "b" / "c"
    deep.mkdir(parents=True)
    w = World(tmp_path / "w", script=script("stream_plan.jsonl"))
    with pytest.raises(sdk.StackNotLoaded, match="plan gate"):
        run(one(w, cwd=str(deep)))
    assert "prompt" not in w.log
    assert sdk.project_agent_files(str(deep), str(w.config)) == [str(repo.resolve() / ".claude" / "agents")]


# ---------------------------------------------------------------- E2a: the CLI's env channel (probe E2a, 2026-10-09)
CHANNEL = ["CLAUDE_CODE_SESSION_KIND", "CLAUDE_BG_SESSION_PERMISSION_RULES", "CLAUDE_BG_WORKSPACE_TRUSTED",
           "CLAUDE_BG_", "CLAUDE_CODE_SANDBOXED", "CLAUDE_RELAUNCH_SESSION_ADD_DIRS"]
NOT_CHANNEL = {"CLAUDE_CODE_SESSION_ID": "x", "CLAUDE_CODE_SESSION_KIND_X": "1", "MY_CLAUDE_BG_X": "1",
               "CLAUDE_BGX": "1", "CLAUDE_CODE_SANDBOX": "1", "claude_bg_x": "1", "claude_code_session_kind": "bg"}


@pytest.mark.parametrize("key", CHANNEL)
def test_env_channel_refused_in_the_callers_env(tmp_path, key):
    """E2a: env CLAUDE_CODE_SESSION_KIND=bg + CLAUDE_BG_SESSION_PERMISSION_RULES add allow rules under host none;
    the key is refused by name, whatever its value (no silent drop)."""
    for value in ("bg", ""):
        with pytest.raises(ValueError, match=f"refused: {key}( |$)"):
            World(tmp_path / value).session(env={key: value})


@pytest.mark.parametrize("key", CHANNEL)
def test_env_channel_refused_in_os_environ_at_connect(tmp_path, monkeypatch, key):
    """E2a: the SDK passes os.environ to the CLI under options.env: a channel key there stops connect()."""
    monkeypatch.setenv(key, "bg")
    w = World(tmp_path, script=script("stream_plan.jsonl"))
    with pytest.raises(sdk.UsageError, match=f"refused: {key} in os.environ"):
        run(one(w))
    assert not w.opened and "prompt" not in w.log


def test_env_channel_forced_off_and_unrelated_keys_pass(tmp_path, monkeypatch):
    """E2a control: CLAUDE_CODE_SESSION_KIND="" reaches the CLI; look-alike keys (env and os.environ) pass."""
    for k, v in NOT_CHANNEL.items():
        monkeypatch.setenv(k, v)
    w = World(tmp_path, script=script("stream_plan.jsonl"))
    run(one(w, env=NOT_CHANNEL))
    env = w.opened[0].env
    assert env["CLAUDE_CODE_SESSION_KIND"] == "" and {k: env[k] for k in NOT_CHANNEL} == NOT_CHANNEL
