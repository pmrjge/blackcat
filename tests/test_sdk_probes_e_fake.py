"""$0 tests of tests/sdk_probes_e.py (E1-E3). Every probe runs against FakeCLI, a Transport that speaks the SDK's
control protocol (initialize, can_use_tool, interrupt, stop_task) and plays sessions decided by World's switches
(what the real CLI does is exactly what the probes ask; the fake answers either way). The SDK's subprocess
transport is disabled, so nothing reaches a CLI or the API. The fake puts the prompts into every free-text field
it emits (replies, results, tool inputs, task labels, server info, hook payloads, meta.json, transcripts) to show
none reaches the report or the ledger. The temp dirs of the probes land under pytest's tmp_path.

Run: uv run --no-project --python 3.13 --with pytest --with claude-agent-sdk==0.2.163 pytest -q tests/test_sdk_probes_e_fake.py
(without the SDK only the pure tests run; SDK_PROBES_E_SCRIPT=<path> points the suite at another copy, as
tests/sdk_probes_e_mutations.py does.)
"""
import asyncio
import contextlib
import dataclasses
import importlib.util
import itertools
import json
import math
import os
import re
import subprocess
import sys
import tempfile
import types
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = Path(os.environ.get("SDK_PROBES_E_SCRIPT") or ROOT / "tests" / "sdk_probes_e.py")
HELPER = ROOT / "dot-config" / "dot-claude" / "bin" / "stack_sdk.py"


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, str(path))
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod          # dataclasses resolve the module's annotations through sys.modules
    spec.loader.exec_module(mod)
    return mod


P = load(SCRIPT, "sdk_probes_e_under_test")
LEAK = " | ".join(P.PROMPTS.values())
PARTS = [x.pid for p in P.PROBES for x in p.parts]

Base: Any = object                              # without the SDK only the pure tests run
with contextlib.suppress(ImportError):
    from claude_agent_sdk import Transport as Base


@pytest.fixture
def sdk(monkeypatch, tmp_path):
    mod = pytest.importorskip("claude_agent_sdk")
    from claude_agent_sdk._internal.transport import subprocess_cli

    async def refuse(self):
        raise AssertionError("a probe tried to start a real CLI")
    monkeypatch.setattr(subprocess_cli.SubprocessCLITransport, "connect", refuse)
    (tmp_path / "t").mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path / "t"))     # the probes' temp dirs: under tmp_path
    return mod


# ---------------------------------------------------------------- the fake CLI
STACK_AGENTS = {"blackcat": None, "explore": None, "coder": "acceptEdits"}
SWITCHES = dict(
    rules_bind=True,        # E1: an allow rule runs Bash under plan
    plan_open=False,        # E1: plan runs Bash without any rule
    sandbox_auto=False,     # E1: the installed sandbox auto-allows Bash (no overlay)
    guard_decides=False,    # E1: a PreToolUse hook (the guard) denies the Bash call
    marker=True,            # E1: agent_guard writes its session-start marker (D17)
    bg_rules=True,          # E2a: the CLI reads CLAUDE_BG_SESSION_PERMISSION_RULES in a bg session
    late_agents=True,       # E2b: agent files are re-read for every turn
    above_git=False,        # E2c1: .claude/agents above the repository root load
    add_subdir=False,       # E2c2: .claude/agents in a subdirectory of an --add-dir load
    own_mode=True,          # E3a/E3d: a child runs in its frontmatter permissionMode
    hook_own_mode=True,     # E3b: the child's PreToolUse event carries its own mode (else its caller's)
    hooks_run=True,         # E3b: the project's command hooks run
    meta_tid_match=True,    # E3c1: the fork child's meta toolUseId is the Skill call's id
    tid_survives=True,      # E3c2
    stopped_written=True,   # E3d: stop_task writes stoppedByUser
    stopped_survives=True,  # E3d
    resume=True,            # E3c2/E3d: SendMessage resumes the child (its transcript grows)
    wake_on_stop=True,      # E3d: the stopped child's end wakes the main thread (a result after the stop)
    denials_listed=True,    # E1c: a denied call shows in the result's permission_denials
    hollow=False,           # no tool is ever called
    stack_rule=True,        # E1c: the stack's exact rule is installed
    cost=0.01,              # every result's total_cost_usd (None: the field is missing)
)


class World:
    def __init__(self, tmp, **kw):
        assert not set(kw) - set(SWITCHES), set(kw) - set(SWITCHES)
        self.__dict__.update(SWITCHES, **kw)
        self.tmp, self.config = tmp, tmp / "config"
        (self.config / "agents").mkdir(parents=True)
        for name, mode in STACK_AGENTS.items():
            pm = "permissionMode: %s\n" % mode if mode else ""
            (self.config / "agents" / (name + ".md")).write_text("---\nname: %s\ndescription: x\n%s---\nbody\n" % (name, pm))
        allow = ([P.STACK_RULE] if self.stack_rule else []) + ["mcp__exa", "Read"]
        (self.config / "settings.json").write_text(json.dumps({
            "hooks": {"SessionStart": [{"hooks": [{"type": "command", "command": "guard"}]}]},
            "permissions": {"allow": allow}, "sandbox": {"enabled": True, "autoAllowBashIfSandboxed": True}}))
        self.cli = tmp / "bin" / "claude"
        self.cli.parent.mkdir()
        self.cli.write_text("#!/bin/sh\nexit 1\n")
        self.cli.chmod(0o755)
        self.ids, self.opened, self.answers = itertools.count(1), [], []

    def factory(self, opts):
        self.opened.append(opts)
        return FakeCLI(self, opts)

    def cfg(self, **kw):
        return P.Config(config_dir=str(self.config), cli_path=str(self.cli), transport_factory=self.factory,
                        **dict(dict(turn_s=10.0, wait_s=1.0, hold_s=5.0, settle_s=0.01), **kw))


def fm(path):
    """name and permissionMode of a markdown file's frontmatter."""
    text = Path(path).read_text()
    return {k: v.strip() for k, v in re.findall(r"(?m)^(name|permissionMode|agent):(.*)$", text.split("\n---", 1)[0])}


def match(text):
    for key, tpl in P.PROMPTS.items():
        rx = "^" + re.sub(r"\\\{(\w+)\\\}", lambda m: "(?P<%s>.+?)" % m.group(1), re.escape(tpl)) + "$"
        m = re.match(rx, text, re.DOTALL)
        if m:
            return key, m.groupdict()
    raise AssertionError("a prompt the fake does not know")


class FakeCLI(Base):
    def __init__(self, w, opts):
        self.w, self.o, self.n = w, opts, next(w.ids)
        self.sid = "sess-%04d-fake" % self.n
        self.q, self.pending, self.tasks, self.rids = asyncio.Queue(), {}, set(), itertools.count(1)
        self.cwd, self.env = Path(opts.cwd), dict(opts.env or {})
        self.user = "user" in (opts.setting_sources or [])
        self.mode = opts.permission_mode or "default"
        self.turn_open, self.hold, self.started = False, None, False
        self.agents0 = self.agent_names()

    # Transport
    async def connect(self):
        pass

    def is_ready(self):
        return True

    async def end_input(self):
        pass

    async def close(self):
        self.q.put_nowait(None)

    async def read_messages(self):
        while (m := await self.q.get()) is not None:
            yield m

    async def write(self, data):
        m = json.loads(data)
        if m["type"] == "control_request":
            await self.control(m["request_id"], m["request"])
        elif m["type"] == "control_response":
            fut = self.pending.pop(m["response"]["request_id"], None)
            if fut is not None and not fut.done():
                fut.set_result(m["response"])
        elif m["type"] == "user":
            self.spawn(self.play(m["message"]["content"]))

    def spawn(self, coro):
        t = asyncio.ensure_future(coro)
        self.tasks.add(t)
        t.add_done_callback(self.tasks.discard)

    # what the CLI loads
    def agent_dirs(self):
        dirs = [self.w.config / "agents"] if self.user else []
        d = self.cwd
        while True:
            dirs.append(d / ".claude" / "agents")
            if (d / ".git").exists() and not self.w.above_git or d == self.w.tmp or d.parent == d:
                break
            d = d.parent
        for a in map(Path, self.o.add_dirs or []):
            dirs.append(a / ".claude" / "agents")
            if self.w.add_subdir:
                dirs += [p for p in a.rglob("agents") if p.parent.name == ".claude" and p.parent.parent != a]
        return dirs

    def agent_names(self):
        return {fm(p).get("name") for d in self.agent_dirs() if d.is_dir() for p in d.glob("*.md")} - {None}

    def bg(self):
        if self.env.get("CLAUDE_CODE_SESSION_KIND") != "bg" or not self.w.bg_rules:
            return None
        return json.loads(self.env.get("CLAUDE_BG_SESSION_PERMISSION_RULES") or "null")

    def rules(self):
        allow, deny = set(self.o.allowed_tools or []), set(self.o.disallowed_tools or [])
        proj = self.cwd / ".claude" / "settings.json"
        if proj.exists():
            allow |= set((json.loads(proj.read_text()).get("permissions") or {}).get("allow") or [])
        if self.user:
            allow |= set(json.loads((self.w.config / "settings.json").read_text())["permissions"]["allow"])
        if self.bg():
            allow |= set(self.bg()["allow"])
            deny |= set(self.bg()["deny"])
        return allow, deny

    def bash_ok(self, cmd):
        allow, deny = self.rules()
        rule = "Bash(%s)" % cmd
        if rule in deny:
            return False
        if rule in allow:
            return self.mode != "plan" or self.w.rules_bind
        if self.mode == "plan" and self.w.plan_open:
            return True
        return self.user and self.w.sandbox_auto and '"autoAllowBashIfSandboxed": false' not in (self.o.settings or "")

    def read_ok(self, path):
        roots = [self.cwd, *map(Path, self.o.add_dirs or []), *map(Path, (self.bg() or {}).get("addDirs") or [])]
        return any(Path(path).is_relative_to(r) for r in roots)

    # the control protocol, CLI side
    async def control(self, rid, req):
        sub, resp = req["subtype"], {}
        if sub == "initialize":
            if self.user and self.w.marker:      # agent_guard's D17 marker, written during connect
                p = Path(self.env["XDG_STATE_HOME"]) / "claude-agent-stack" / self.sid / "session-start.json"
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(json.dumps({"v": 1, "ts": __import__("time").time(), "source": "startup", "policy": True}))
            resp = {"agents": [{"name": n, "description": LEAK, "model": "x"} for n in sorted(self.agents0)],
                    "current_permission_mode": self.mode, "commands": [{"name": "c", "description": LEAK}]}
            if self.user and self.o.include_hook_events:
                self.spawn(self.session_start())
        self.emit({"type": "control_response", "response": {"subtype": "success", "request_id": rid, "response": resp}})
        if sub == "interrupt" and self.turn_open:
            self.finish(terminal_reason="aborted_streaming")
        elif sub == "stop_task":
            self.stop(req["task_id"])

    async def session_start(self):
        for sub in ("hook_started", "hook_response"):
            self.emit(self.sysm(sub, hook_id="h1", hook_event="SessionStart", hook_name="SessionStart:startup",
                                **({"outcome": "success", "exit_code": 0, "stdout": LEAK, "output": LEAK}
                                   if sub == "hook_response" else {})))

    async def ask(self, tool, inp, agent_id=None):
        rid = "cli_%d" % next(self.rids)
        fut = asyncio.get_running_loop().create_future()
        self.pending[rid] = fut
        self.emit({"type": "control_request", "request_id": rid, "request": dict(
            subtype="can_use_tool", tool_name=tool, input=inp, tool_use_id="tu-%s" % tool,
            permission_suggestions=[{"type": "addRules", "destination": "userSettings", "rules": [{"toolName": tool}],
                                     "behavior": "allow"}], **({"agent_id": agent_id} if agent_id else {}))})
        resp = await asyncio.wait_for(fut, 30)
        self.w.answers.append((tool, resp.get("response") or {}))
        return (resp.get("response") or {}).get("behavior") == "allow"

    def stop(self, task_id):
        if not self.hold or self.hold[0] != task_id:
            return
        _, aid = self.hold
        self.hold = None
        for prid, fut in list(self.pending.items()):           # the abort withdraws the held request
            self.emit({"type": "control_cancel_request", "request_id": prid})
            self.pending.pop(prid, None)
            if not fut.done():
                fut.set_result({"response": {}})
        self.emit(self.sysm("task_updated", task_id=task_id, patch={"status": "killed"}))
        if self.w.stopped_written:
            self.edit_meta(aid, stoppedByUser=True)
        if self.w.wake_on_stop:
            self.turn_open = True
            self.emit(self.asst({"type": "text", "text": LEAK}))
            self.finish()

    async def hook(self, tool, mode, aid=None, atype=None):
        """The project's PreToolUse command hooks, run for real (the probe's logger)."""
        proj = self.cwd / ".claude" / "settings.json"
        if not self.w.hooks_run or not proj.exists():
            return
        payload = dict({"hook_event_name": "PreToolUse", "tool_name": tool, "tool_input": {"x": LEAK},
                        "permission_mode": mode, "session_id": self.sid, "cwd": str(self.cwd), "transcript_path": LEAK},
                       **({"agent_id": aid, "agent_type": atype} if aid else {}))
        for group in (json.loads(proj.read_text()).get("hooks") or {}).get("PreToolUse") or []:
            for h in group["hooks"]:
                await asyncio.to_thread(subprocess.run, h["command"], shell=True, input=json.dumps(payload), text=True,
                                        timeout=30, check=True)

    # frames
    def emit(self, m):
        self.q.put_nowait(m)

    def sysm(self, subtype, **kw):
        return dict({"type": "system", "subtype": subtype, "session_id": self.sid, "uuid": "u%d" % next(self.rids)}, **kw)

    def asst(self, *content, parent=None):
        return {"type": "assistant", "message": {"content": list(content), "model": "fake-model"},
                "parent_tool_use_id": parent, "session_id": self.sid}

    def use(self, name, inp, parent=None):
        tu = "tu-%s-%d" % (name.lower(), next(self.rids))
        self.emit(self.asst({"type": "tool_use", "id": tu, "name": name, "input": dict(inp, note=LEAK)}, parent=parent))
        return tu

    def tool_result(self, tu, error):
        self.emit({"type": "user", "message": {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": tu, "is_error": error, "content": LEAK}]},
            "parent_tool_use_id": None, "session_id": self.sid})

    def started_task(self, task_id, tu, agent):
        self.emit(self.sysm("task_started", task_id=task_id, description=agent + ": " + LEAK, tool_use_id=tu,
                            task_type="local_agent"))

    def done_task(self, task_id, tu):
        self.emit(self.sysm("task_notification", task_id=task_id, status="completed", output_file="/o", summary=LEAK,
                            tool_use_id=tu))

    def finish(self, **kw):
        self.turn_open = False
        cost = {} if self.w.cost is None else {"total_cost_usd": self.w.cost}
        self.emit(dict({"type": "result", "subtype": "success", "duration_ms": 5, "duration_api_ms": 4, "is_error": False,
                        "num_turns": 1, "session_id": self.sid, "result": LEAK, "terminal_reason": "completed"},
                       **cost, **kw))
        self.emit(self.sysm("session_state_changed", state="idle"))

    # Claude Code's own files
    def subagents(self):
        d = self.w.config / "projects" / "-fake" / self.sid / "subagents"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def child(self, aid, agent, tu):
        (self.subagents() / ("agent-%s.meta.json" % aid)).write_text(json.dumps(
            {"agentType": agent, "toolUseId": tu if self.w.meta_tid_match else "tu-other", "description": LEAK}))
        (self.subagents() / ("agent-%s.jsonl" % aid)).write_text(json.dumps({"m": LEAK}) + "\n" + json.dumps({"m": 2}) + "\n")

    def edit_meta(self, aid, **kw):
        p = self.subagents() / ("agent-%s.meta.json" % aid)
        meta = dict(json.loads(p.read_text()), **kw)
        p.write_text(json.dumps({k: v for k, v in meta.items() if v is not None}))

    # the turns
    async def play(self, text):
        key, v = match(text)
        if not self.started:
            self.started = True
            proj = self.w.config / "projects" / "-fake"
            proj.mkdir(parents=True, exist_ok=True)
            (proj / (self.sid + ".jsonl")).write_text(json.dumps({"entrypoint": "sdk-py", "message": text}) + "\n")
        self.turn_open = True
        names = self.agent_names() if self.w.late_agents else self.agents0
        self.emit(self.sysm("init", agents=sorted(names), permissionMode=self.mode, tools=["Agent", "Bash", "Read"],
                            claude_code_version="2.1.287", model="fake-model", cwd=str(self.cwd)))
        self.emit({"type": "rate_limit_event", "rate_limit_info": {"status": "allowed"}, "uuid": "r", "session_id": self.sid})
        if self.w.hollow:
            self.emit(self.asst({"type": "text", "text": LEAK}))
            self.finish()
            return
        await getattr(self, "play_" + key)(**v)

    async def play_ok(self):
        self.emit(self.asst({"type": "text", "text": LEAK}))
        self.finish()

    async def play_e1_bash(self, command):
        tu = self.use("Bash", {"command": command})
        if self.o.include_hook_events:
            out = json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                                     "permissionDecisionReason": LEAK}}) if self.w.guard_decides else ""
            self.emit(self.sysm("hook_started", hook_id="hp", hook_event="PreToolUse", hook_name="PreToolUse:Bash"))
            self.emit(self.sysm("hook_response", hook_id="hp", hook_event="PreToolUse", hook_name="PreToolUse:Bash",
                                outcome="success", exit_code=0, stdout=out, output=out))
        ok = not self.w.guard_decides and self.bash_ok(command)
        if ok and command.startswith("touch "):
            Path(command[6:]).touch()
        self.tool_result(tu, not ok or command == P.STACK_RULE_CMD)        # no justfile: the command fails
        self.finish(permission_denials=[] if ok or not self.w.denials_listed else [
            {"tool_name": "Bash", "tool_use_id": tu, "tool_input": {"command": LEAK}}])

    async def play_e2_calls(self, allow, deny, read):
        denials = []
        for cmd in (allow, deny):
            tu = self.use("Bash", {"command": cmd})
            ok = self.bash_ok(cmd)
            if ok:
                Path(cmd[6:]).touch()
            else:
                denials.append({"tool_name": "Bash", "tool_use_id": tu, "tool_input": {"x": LEAK}})
            self.tool_result(tu, not ok)
        tu = self.use("Read", {"file_path": read})
        ok = self.read_ok(read)
        if not ok:
            denials.append({"tool_name": "Read", "tool_use_id": tu, "tool_input": {"x": LEAK}})
        self.tool_result(tu, not ok)
        self.finish(permission_denials=denials)

    async def play_e2_dispatch(self, agent):
        tu = self.use("Agent", {"subagent_type": agent, "prompt": LEAK})
        if agent in (self.agent_names() if self.w.late_agents else self.agents0):
            self.started_task("t2", tu, agent)
            self.done_task("t2", tu)
            self.tool_result(tu, False)
        else:
            self.tool_result(tu, True)
        self.finish()

    async def play_e3_skill(self, skill):
        tu = self.use("Skill", {"skill": skill})
        await self.hook("Skill", self.mode)
        sk = self.cwd / ".claude" / "skills" / skill / "SKILL.md"
        if not await self.ask("Skill", {"skill": skill}) or not sk.exists():
            self.tool_result(tu, True)
            self.finish()
            return
        agent = fm(sk)["agent"]
        marker = re.search(r"Write the file (\S+)", sk.read_text()).group(1)
        own = fm(self.cwd / ".claude" / "agents" / (agent + ".md")).get("permissionMode")
        actual = own if self.w.own_mode else self.mode
        aid = "afork%d" % self.n
        self.child(aid, agent, tu)
        self.started_task("tf", tu, agent)
        await self.hook("Write", actual if self.w.hook_own_mode else self.mode, aid, agent)
        self.use("Write", {"file_path": marker, "content": LEAK}, parent=tu)
        if actual == "acceptEdits":
            Path(marker).write_text("ok")
        elif actual != "plan":
            await self.ask("Write", {"file_path": marker}, agent_id=aid)
        self.done_task("tf", tu)
        self.tool_result(tu, False)
        self.finish()

    async def play_e3_hold(self, agent, marker):
        tu = self.use("Agent", {"subagent_type": agent, "run_in_background": True, "prompt": LEAK})
        if not await self.ask("Agent", {"subagent_type": agent}):
            self.tool_result(tu, True)
            self.finish()
            return
        aid = "ahold%d" % self.n
        self.child(aid, agent, tu)
        self.started_task("th", tu, agent)
        self.tool_result(tu, False)
        self.finish()                                           # a background dispatch: the turn ends
        self.spawn(self.hold_child(aid, agent, marker))

    async def hold_child(self, aid, agent, marker):
        own = fm(self.cwd / ".claude" / "agents" / (agent + ".md")).get("permissionMode")
        actual = own if self.w.own_mode else self.mode
        reported = actual if self.w.hook_own_mode else self.mode
        await self.hook("Write", reported, aid, agent)
        if actual == "acceptEdits":
            Path(marker).write_text("ok")
        else:
            await self.ask("Write", {"file_path": marker}, agent_id=aid)
        await self.hook("Bash", reported, aid, agent)
        self.hold = ("th", aid)
        await self.ask("Bash", {"command": "uv --version"}, agent_id=aid)     # parked by the host
        if self.hold:                                           # not stopped: it ends on its own
            self.hold = None
            self.done_task("th", "tu-x")

    async def play_e3_send(self, agent_id):
        tu = self.use("SendMessage", {"to": agent_id, "message": LEAK})
        await self.hook("SendMessage", self.mode)
        p = self.subagents() / ("agent-%s.jsonl" % agent_id)
        if await self.ask("SendMessage", {"to": agent_id}) and p.exists() and self.w.resume:
            p.write_text(p.read_text() + json.dumps({"m": LEAK}) + "\n" + json.dumps({"m": 3}) + "\n")
            self.edit_meta(agent_id, toolUseId=None if not self.w.tid_survives else json.loads(
                (self.subagents() / ("agent-%s.meta.json" % agent_id)).read_text()).get("toolUseId"),
                stoppedByUser=None if not self.w.stopped_survives else json.loads(
                (self.subagents() / ("agent-%s.meta.json" % agent_id)).read_text()).get("stoppedByUser"))
            self.tool_result(tu, False)
        else:
            self.tool_result(tu, True)
        self.finish()


def helper():
    return load(HELPER, "stack_sdk_for_probes_e")


def run(world, probes=None, ledger=None, **cfg):
    """The whole run, bounded; the world's config is the CLI's own (CLAUDE_CONFIG_DIR), as the probes require."""
    from unittest import mock
    with mock.patch.dict(os.environ, {"CLAUDE_CONFIG_DIR": str(world.config)}):
        return asyncio.run(asyncio.wait_for(P.run_probes(probes or P.PROBES, world.cfg(**cfg), helper(),
                                                         ledger=ledger), 120))


def answers(rows):
    return {k: v for r in rows for k, v in r.answers.items()}


def probe_of(opts):
    """The probe a session belonged to: its cwd lies under the probe's sdk-probe-<id>- temp dir."""
    return re.search(r"sdk-probe-(e\d)-", str(opts.cwd)).group(1).upper()


def assert_no_prompt_text(text):
    flat = " ".join(text.split())
    for p in [*P.PROMPTS.values(), P.LATE_BODY, P.WRITER_BODY, P.HOLDER_BODY]:
        p = " ".join(p.split())
        for i in range(max(1, len(p) - 23)):
            assert p[i:i + 24] not in flat, p[i:i + 24]


GOOD = {"E1a": "yes", "E1b": "yes", "E1c": "yes", "E1d": "no", "E2a": "yes", "E2b": "yes", "E2c1": "no",
        "E2c2": "no", "E3a": "yes", "E3b": "yes", "E3c1": "yes", "E3c2": "yes", "E3d": "yes"}
FLIPPED = dict(rules_bind=False, sandbox_auto=True, bg_rules=False, late_agents=False, above_git=True, add_subdir=True,
               own_mode=True, hook_own_mode=False, meta_tid_match=False, tid_survives=False, stopped_survives=False)
FLIPPED_ANSWERS = {"E1a": "no", "E1b": "no", "E1c": "no", "E1d": "yes", "E2a": "no", "E2b": "no", "E2c1": "yes",
                   "E2c2": "yes", "E3a": "yes", "E3b": "no", "E3c1": "no", "E3c2": "no", "E3d": "no"}


# ---------------------------------------------------------------- the envelope and the caps (pure)
def test_registry_caps_fit_the_consent_envelope():
    caps = {p.pid: (p.group, p.budget_usd, p.max_turns) for p in P.PROBES}
    assert caps == {"E1": ("E1E2", 0.60, 3), "E2": ("E1E2", 0.60, 4), "E3": ("E3", 0.40, 8)}
    assert P.ENVELOPE == {"E1E2": 1.50, "E3": 0.50} and P.TOTAL_CAP_USD == 2.00 and P.CONSENT_VALUE == "2.00"
    assert P.MODEL == "haiku" and P.MIN_SESSION_USD == 0.02
    md = P.agent_md("e3-writer", P.WRITER_BODY, "acceptEdits", "Write")
    assert "\nmodel: haiku\n" in md and "\nmaxTurns: 4\n" in md and "\npermissionMode: acceptEdits\n" in md
    assert PARTS == list(GOOD)
    P.validate_registry(P.PROBES)
    for p in P.PROBES:
        assert p.timeout_s > 0 and all(x.question and x.observable and x.reading for x in p.parts)


@pytest.mark.parametrize("field, bad", [
    ("budget_usd", None), ("budget_usd", 0), ("budget_usd", -0.1), ("budget_usd", True), ("budget_usd", "0.5"),
    ("budget_usd", float("nan")), ("budget_usd", float("inf")), ("budget_usd", 1.51), ("group", "E9"),
    ("max_turns", 0), ("max_turns", 13), ("max_turns", True), ("max_turns", None), ("max_turns", 2.0)])
def test_a_probe_outside_its_envelope_or_without_a_turn_limit_is_refused(field, bad):
    e1 = P.PROBES[0]
    probes = [dataclasses.replace(e1, **{field: bad}), *P.PROBES[1:]]
    with pytest.raises(P.BudgetError):
        P.validate_registry(probes)
    with pytest.raises(P.BudgetError):
        asyncio.run(P.run_probes(probes, P.Config(config_dir="/x", cli_path=None), None))


def test_group_sums_and_the_total_are_enforced():
    e1, e2, e3 = P.PROBES
    with pytest.raises(P.BudgetError):          # E1+E2 above 1.50, each within it, the total within 2.00
        P.validate_registry([dataclasses.replace(e1, budget_usd=0.8), dataclasses.replace(e2, budget_usd=0.8),
                             dataclasses.replace(e3, budget_usd=0.3)])
    with pytest.raises(P.BudgetError):
        P.validate_registry([dataclasses.replace(e1, budget_usd=0.9), dataclasses.replace(e2, budget_usd=0.9), e3])
    with pytest.raises(P.BudgetError):          # E3 above its 0.50
        P.validate_registry([e1, e2, dataclasses.replace(e3, budget_usd=0.51)])
    with pytest.raises(P.BudgetError):
        P.validate_registry([e1, e1])
    P.validate_registry([dataclasses.replace(e1, budget_usd=0.75), dataclasses.replace(e2, budget_usd=0.75),
                         dataclasses.replace(e3, budget_usd=0.50)])        # exactly the envelope
    assert not P.valid_cost(None) and not P.valid_cost(True) and not P.valid_cost(-0.01)
    assert not P.valid_cost(math.nan) and not P.valid_cost(math.inf) and not P.valid_cost("0.1")
    assert P.valid_cost(0) and P.valid_cost(0.25)


def test_dry_run_is_the_default_and_spends_nothing(capsys, monkeypatch):
    monkeypatch.setattr(P, "run_probes", None)                 # would raise if called
    monkeypatch.setattr(P.base, "load_helper", None)
    monkeypatch.delenv(P.CONSENT_ENV, raising=False)
    assert P.main([]) == 0
    out = capsys.readouterr().out
    assert out.startswith("DRY RUN") and "at most $2.00 in all, E1+E2 at most $1.50 plus E3 at most $0.50" in out
    assert re.search(r"^E1\s+\$0\.60 ", out, re.MULTILINE) and re.search(r"^E3\s+\$0\.40 ", out, re.MULTILINE)
    assert "total 1.60 of 2.00" in out and "model haiku" in out
    for pid in PARTS:
        assert re.search(r"^\s+%s\s" % pid, out, re.MULTILINE), pid
    assert P.main(["--dry-run", "--only", "e3"]) == 0
    out = capsys.readouterr().out
    assert "E3 " in out and "E1 " not in out
    monkeypatch.setenv(P.CONSENT_ENV, P.CONSENT_VALUE)        # the env alone is still a dry run
    assert P.main([]) == 0
    assert "without --paid this is a dry run" in capsys.readouterr().out
    with pytest.raises(SystemExit):
        P.main(["--only", "E9"])
    with pytest.raises(SystemExit):
        P.main(["--paid", "--dry-run"])


@pytest.fixture
def pinned(monkeypatch):
    monkeypatch.setattr(P.base, "versions", lambda cli: {"sdk": P.SDK_PIN, "system_cli": None, "bundled_cli": None})
    monkeypatch.setattr(P.base, "load_helper", lambda config: None)


@pytest.mark.parametrize("env", [None, "", "1", "yes", "2", "2.0", "10.50", " 2.00"])
def test_a_paid_run_needs_the_flag_and_the_exact_consent_env(pinned, monkeypatch, tmp_path, env, capsys):
    called = []

    async def never(*a, **k):
        called.append(1)
    monkeypatch.setattr(P, "run_probes", never)
    if env is None:
        monkeypatch.delenv(P.CONSENT_ENV, raising=False)
    else:
        monkeypatch.setenv(P.CONSENT_ENV, env)
    with pytest.raises(SystemExit) as e:
        P.main(["--paid", "--cli", "/nonexistent/claude", "--out", str(tmp_path / "r.md")])
    assert e.value.code == 2 and called == [] and not list(tmp_path.iterdir())
    assert P.CONSENT_ENV in capsys.readouterr().err


def test_a_paid_run_logs_the_envelope_first_and_reports(pinned, monkeypatch, tmp_path, capsys):
    monkeypatch.setenv(P.CONSENT_ENV, P.CONSENT_VALUE)
    seen = {}

    async def one(probes, cfg, helper, rows, ledger):
        seen["ledger"] = ledger
        rows.append(P.Row(probes[0], {"E1a": "yes"}, 0.6, cost=0.01, sessions=["sess-1"]))
        ledger({"ev": "cost", "probe": "E1", "usd": 0.01, "note": P.PROMPTS["e1_bash"]})
        raise KeyboardInterrupt                                 # Ctrl-C: the report and the ledger still close
    monkeypatch.setattr(P, "run_probes", one)
    with pytest.raises(KeyboardInterrupt):
        P.main(["--paid", "--cli", "/nonexistent/claude", "--out", str(tmp_path / "r.md")])
    led = tmp_path / "r.ledger.jsonl"
    lines = [json.loads(x) for x in led.read_text().splitlines()]
    assert lines[0]["ev"] == "envelope" and lines[0]["total_usd"] == 2.0 and lines[0]["groups_usd"] == P.ENVELOPE
    assert lines[0]["consent_env"] == P.CONSENT_ENV and lines[0]["consent_value"] == "2.00"
    assert lines[0]["caps_usd"] == {"E1": 0.6, "E2": 0.6, "E3": 0.4} and lines[0]["flag"] == "--paid"
    assert lines[1]["note"] == P.base.WITHHELD and lines[-1]["ev"] == "end"
    assert os.stat(led).st_mode & 0o777 == 0o600
    text = (tmp_path / "r.md").read_text()
    assert "Consent envelope: the user's decision of 2026-10-09" in text and "| E1 | ran |" in text
    assert "Ledger: %s" % led in capsys.readouterr().out
    monkeypatch.setattr(P, "run_probes", one)                   # a second run never overwrites either file
    with pytest.raises(KeyboardInterrupt):
        P.main(["--paid", "--cli", "/x", "--out", str(tmp_path / "r.md")])
    assert (tmp_path / "r-2.md").exists() and (tmp_path / "r-2.ledger.jsonl").exists()


def test_an_unpinned_sdk_or_an_unwritable_report_is_refused_before_any_call(monkeypatch, tmp_path):
    monkeypatch.setenv(P.CONSENT_ENV, P.CONSENT_VALUE)
    monkeypatch.setattr(P, "run_probes", None)
    monkeypatch.setattr(P.base, "versions", lambda cli: {"sdk": "0.2.164", "system_cli": None, "bundled_cli": None})
    with pytest.raises(SystemExit):
        P.main(["--paid", "--cli", "/x", "--out", str(tmp_path / "r.md")])
    monkeypatch.setattr(P.base, "versions", lambda cli: {"sdk": P.SDK_PIN, "system_cli": None, "bundled_cli": None})
    with pytest.raises(SystemExit):
        P.main(["--paid", "--cli", "/x", "--out", "/dev/null/x/r.md"])
    assert not list(tmp_path.iterdir())


# ---------------------------------------------------------------- the report (pure)
def test_render_never_carries_prompt_text_and_lists_every_part(tmp_path):
    facts = {k: v for k, v in P.PROMPTS.items()}
    facts.update(nested={"deep": [P.PROMPTS["e3_hold"]]}, body=P.FORK_BODY)
    rows = [P.Row(P.PROBES[0], {"E1a": "yes"}, 0.6, facts=facts, sessions=["sess-1", P.PROMPTS["ok"]],
                  transcripts=["/a/b.jsonl", P.PROMPTS["e2_calls"] + ".jsonl"])]
    text = P.render(rows, {"date": "2026-10-09", "sdk": P.PROMPTS["e3_send"]})
    assert_no_prompt_text(text)
    assert P.base.WITHHELD in text and "/a/b.jsonl" in text and "sess-1" in text
    assert "| E1a |" in text and "| yes |" in text and "| E1b |" in text and "| unknown |" in text
    for p in P.PROMPTS.values():         # an identifier-shaped copy passes clean(); the final check stops it
        squashed = "_".join(re.findall(r"[A-Za-z0-9]+", p))[:150]
        with pytest.raises(ValueError):
            P.render([P.Row(P.PROBES[0], {}, 0.6, facts={"x": squashed})], {"date": "d"})
    path = P.write_report(str(tmp_path / "r" / "2026-10-09-e.md"), text)
    assert P.write_report(str(tmp_path / "r" / "2026-10-09-e.md"), text).endswith("2026-10-09-e-2.md")
    assert os.stat(path).st_mode & 0o777 == 0o600


def test_the_hook_logger_keeps_identifiers_only(tmp_path):
    script, log = tmp_path / "h.py", tmp_path / "log.jsonl"
    script.write_text(P.HOOK_LOGGER)
    ev = {"hook_event_name": "PreToolUse", "tool_name": "Write", "permission_mode": "acceptEdits", "agent_id": "a1b2",
          "agent_type": "e3-writer", "tool_input": {"content": LEAK}, "transcript_path": "/x/y.jsonl", "cwd": LEAK}
    for payload in (json.dumps(ev), json.dumps(dict(ev, agent_type=LEAK, permission_mode=["x"])), "not json"):
        p = subprocess.run([sys.executable, "-I", str(script), str(log)], input=payload, text=True, capture_output=True,
                           timeout=30, check=False)
        assert p.returncode == 0 and p.stdout == ""                    # no decision, ever
    rows = [json.loads(x) for x in log.read_text().splitlines()]
    assert rows == [{"hook_event_name": "PreToolUse", "tool_name": "Write", "permission_mode": "acceptEdits",
                     "agent_id": "a1b2", "agent_type": "e3-writer"},
                    {"hook_event_name": "PreToolUse", "tool_name": "Write", "agent_id": "a1b2"}]
    cmd = P.hook_command(str(script), str(log))
    assert cmd.startswith(sys.executable) and " -I " in cmd


# ---------------------------------------------------------------- every probe over the fake CLI
def test_every_part_answers_in_the_good_world_within_its_caps(sdk, tmp_path):
    w = World(tmp_path)
    rows = run(w)
    assert answers(rows) == GOOD, {r.probe.pid: (r.answers, r.facts) for r in rows}
    caps = {p.pid: p.budget_usd for p in P.PROBES}
    per = {}
    for o in w.opened:
        pid = probe_of(o)
        assert isinstance(o.max_budget_usd, float) and P.MIN_SESSION_USD <= o.max_budget_usd <= caps[pid]
        per.setdefault(pid, []).append(o)
        assert o.model == "haiku" and 0 < o.max_turns <= next(p.max_turns for p in P.PROBES if p.pid == pid)
        assert o.strict_mcp_config is True and {"WebSearch", "WebFetch", "mcp__exa"} <= set(o.disallowed_tools)
        scratch = re.search(r"^(.*/sdk-probe-e\d-[^/]+)/", str(o.cwd) + "/").group(1)
        assert o.env["XDG_STATE_HOME"] == scratch + "/state" and str(tmp_path) in scratch
        assert "CLAUDE_CONFIG_DIR" not in o.env and o.cli_path == str(w.cli)     # the keychain entry stays the default
    assert len(per["E1"]) == 5 and len(per["E2"]) == 4 and len(per["E3"]) == 2
    for o in per["E1"]:             # stack_sdk.Session, host none: plan, no prompts, the installed stack
        assert o.permission_mode == "plan" and o.extra_args["permission-prompts"] == "none" and o.can_use_tool is None
        assert "user" in o.setting_sources and "ExitPlanMode" in o.disallowed_tools and "Agent(coder)" in o.disallowed_tools
    assert [o.settings for o in per["E1"]] == [P.SANDBOX_OVERLAY] * 4 + [None]
    assert per["E1"][1].allowed_tools == ["Bash(touch %s/e1-session_rule.marker)" % per["E1"][1].cwd]
    for o in per["E2"] + per["E3"]:  # only the temp project's settings
        assert o.setting_sources == ["project"]
    e2a = [o for o in per["E2"] if "CLAUDE_BG_SESSION_PERMISSION_RULES" in o.env]
    assert [o.env["CLAUDE_CODE_SESSION_KIND"] for o in e2a] == ["bg", ""]
    assert per["E2"][0].max_budget_usd == 0.05 and per["E2"][0].add_dirs        # E2c: connect only
    assert isinstance(per["E3"][0].can_use_tool, P.base.Host) and per["E3"][0].permission_mode == "plan"
    assert isinstance(per["E3"][1].can_use_tool, P.SendHoldHost) and per["E3"][1].permission_mode == "default"
    for r in rows:
        assert r.status == "ran" and r.cap == caps[r.probe.pid] and r.sessions
        n = len(per[r.probe.pid])
        booked = 0.05 if r.probe.pid == "E2" else 0.0               # E2c reports no cost: its whole cap
        assert r.cost == pytest.approx(booked + 0.01 * (n - (1 if booked else 0))), (r.probe.pid, r.cost)
    f3 = next(r.facts for r in rows if r.probe.pid == "E3")
    assert f3["e3c_meta_tool_use_id"] == f3["e3c_skill_tool_use_id"] and f3["e3d_meta_stopped_by_user"] is True
    assert f3["e3d_hold_released_by"] == "cancelled" and f3["e3_child_modes_fork"] == ["acceptEdits"]
    assert f3["e3_main_modes_fork"] == ["plan"] and f3["e3d_child_lines_after"] > f3["e3d_child_lines_before"]
    f1 = next(r.facts for r in rows if r.probe.pid == "E1")
    assert f1["control_verdict"] == "denied" and f1["denials_calibrated"] is True and f1["stack_rule_installed"]
    assert f1["sandbox_auto_allow"] is True and f1["as_installed_verdict"] == "denied"


def test_the_report_and_ledger_of_a_full_run_have_no_prompt_text(sdk, tmp_path):
    w = World(tmp_path)
    events = []
    rows = run(w, ledger=events.append)
    text = P.render(rows, dict(P.base.versions(None), date="2026-10-09"))
    assert_no_prompt_text(text)
    assert_no_prompt_text(json.dumps([P.clean(e) for e in events]))
    assert P.base.WITHHELD not in text           # no probe records free text, even though the fake offers it
    for pid in PARTS:
        assert "| %s |" % pid in text
    assert str(w.config / "projects") in text and "Consent envelope" in text
    kinds = [e["ev"] for e in events]
    assert kinds.count("probe") == 3 and kinds.count("probe_end") == 3 and kinds.count("reserve") == 11
    assert kinds.count("cost") >= 10 and "cost_unknown" not in kinds


def test_answers_follow_the_measurements_in_the_flipped_world(sdk, tmp_path):
    rows = run(World(tmp_path, **FLIPPED))
    assert answers(rows) == FLIPPED_ANSWERS, {r.probe.pid: r.facts for r in rows}
    f = next(r.facts for r in rows if r.probe.pid == "E1")
    assert f["control_verdict"] == "denied" and f["as_installed_verdict"] == "ran"


def test_a_child_in_its_callers_mode_gives_no_for_e3a(sdk, tmp_path):
    rows = run(World(tmp_path, own_mode=False), [P.PROBES[2]])
    got = answers(rows)
    assert got["E3a"] == "no" and got["E3b"] == "unknown", rows[0].facts     # no marker: the real mode unproven
    assert rows[0].facts["e3a_child_write_rows"] == 1 and rows[0].facts["e3a_marker"] is False


def test_nothing_measured_answers_unknown(sdk, tmp_path):
    rows = run(World(tmp_path, hollow=True, hooks_run=False))
    got = answers(rows)
    assert {k: v for k, v in got.items() if k not in ("E2c1", "E2c2")} == dict.fromkeys(set(PARTS) - {"E2c1", "E2c2"},
                                                                                         "unknown"), got
    assert all(r.status == "ran" for r in rows)
    rows = run(World(tmp_path / "noresume", resume=False, wake_on_stop=False), [P.PROBES[2]])
    got = answers(rows)
    assert (got["E3c2"], got["E3d"]) == ("unknown", "unknown") and got["E3c1"] == "yes", rows[0].facts
    assert rows[0].facts["e3d_result_after_stop"] is False


def test_a_hook_decision_or_an_unloaded_stack_leaves_e1_unknown(sdk, tmp_path):
    (row,) = run(World(tmp_path, guard_decides=True), [P.PROBES[0]])
    assert {k: v for k, v in row.answers.items()} == dict.fromkeys(["E1a", "E1b", "E1c", "E1d"], "unknown")
    assert row.facts["session_rule_verdict"] == "hook_decided" and row.facts["session_rule_hook_decisions"] == {"deny": 1}
    w = World(tmp_path / "nomarker", marker=False)
    (row,) = run(w, [P.PROBES[0]], ledger=None)
    assert row.status == "ran" and set(row.answers.values()) == {"unknown"}
    assert row.facts["stack_not_loaded"] == "guard_marker" and len(w.opened) == 1            # one leg, then stop
    assert row.cost == pytest.approx(0.12) and row.facts["sessions_without_result"] == 1      # booked at its cap
    (row,) = run(World(tmp_path / "norule", stack_rule=False), [P.PROBES[0]])
    assert row.answers["E1c"] == "unknown" and row.facts["stack_rule_installed"] is False
    assert row.answers["E1a"] == "yes"
    # the control's denial missing from permission_denials: E1c has no calibrated observable; the markers still do
    (row,) = run(World(tmp_path / "unlisted", rules_bind=False, denials_listed=False), [P.PROBES[0]])
    assert row.answers == {"E1a": "no", "E1b": "no", "E1c": "unknown", "E1d": "no"}, row.facts
    assert row.facts["control_verdict"] == "denied" and row.facts["denials_calibrated"] is False


def test_e1_runs_only_on_the_clis_own_config_dir(sdk, tmp_path):
    """No CLAUDE_CONFIG_DIR is exported (it renames the login's keychain entry), so the probe's config must be
    the one the CLI resolves by itself."""
    w = World(tmp_path)
    from unittest import mock
    with mock.patch.dict(os.environ, {"CLAUDE_CONFIG_DIR": str(tmp_path / "elsewhere")}):
        (row,) = asyncio.run(P.run_probes([P.PROBES[0]], w.cfg(), helper()))
    assert row.status == "error" and row.facts["error"] == "RuntimeError" and w.opened == []


def test_an_unreported_cost_fails_closed(sdk, tmp_path):
    """A result without total_cost_usd: that session stays at its whole cap, the probe starts nothing more,
    and the run skips every later probe."""
    events = []
    w = World(tmp_path, cost=None)
    rows = run(w, ledger=events.append)
    assert [r.status for r in rows] == ["refused", "skipped", "skipped"]
    assert len(w.opened) == 1 and rows[0].cost == pytest.approx(0.12)
    assert rows[0].facts["cost_unknown"] is True and rows[1].facts["reason"] == "cost_unknown"
    assert set(rows[1].answers.values()) == {"skipped"} and set(rows[0].answers.values()) == {"refused"}
    assert [e["ev"] for e in events if e["ev"].startswith("cost")] == ["cost_unknown"]
    # a later valid result of the same session never lowers its booking
    ctx = P.Ctx(P.PROBES[0], w.cfg(), helper(), 0.6)
    opts = types.SimpleNamespace(max_budget_usd=0.12)
    ctx.reserve(0, opts)
    ctx.note(0, FakeResult(float("nan")))
    ctx.note(0, FakeResult(0.01))
    assert ctx.spent == pytest.approx(0.12) and ctx.unknown_cost
    with pytest.raises(P.BudgetError):
        ctx.budget()


class FakeResult:
    """Only its class name and total_cost_usd matter to Ctx.note (base.kind)."""

    def __init__(self, cost):
        self.total_cost_usd, self.session_id = cost, "sess-fake-result"


FakeResult.__name__ = "ResultMessage"


def test_caps_shrink_with_the_reported_spend_and_stop_before_the_envelope(sdk, tmp_path):
    w = World(tmp_path)
    e1, e2, e3 = P.PROBES

    async def spend(c, usd):
        c.costs[99] = usd
    rows = run(w, [dataclasses.replace(e1, fn=lambda c: spend(c, 1.45)), e2, e3])
    assert [r.status for r in rows] == ["ran", "cap_used", "ran"]
    assert rows[1].cap == pytest.approx(0.05)                   # what E1+E2 has left, not E2's 0.60
    assert rows[2].cap == pytest.approx(0.40)                   # E3's own envelope is untouched
    e2_opts = [o for o in w.opened if probe_of(o) == "E2"]
    assert [o.max_budget_usd for o in e2_opts] == [0.05]       # E2c only; E2a would need more than is left
    assert rows[1].answers == {"E2a": "skipped", "E2b": "skipped", "E2c1": "no", "E2c2": "no"}
    assert answers(rows[2:]) == {k: v for k, v in GOOD.items() if k.startswith("E3")}
    assert sum(r.cost for r in rows[:2]) <= P.ENVELOPE["E1E2"] + 1e-9
    w2 = World(tmp_path / "2")
    rows = run(w2, [dataclasses.replace(e1, fn=lambda c: spend(c, 1.49)), e2, dataclasses.replace(
        e3, fn=lambda c: spend(c, 0.49))])
    assert [r.status for r in rows] == ["ran", "skipped", "ran"] and rows[1].facts["reason"] == "envelope_used"
    assert not [o for o in w2.opened if probe_of(o) == "E2"]
    total = sum(r.cost for r in rows)
    assert total <= P.TOTAL_CAP_USD
    # an overshoot past E1+E2's envelope (one turn over a cap): E3 gets what the $2.00 total has left
    rows = run(World(tmp_path / "3"), [dataclasses.replace(e1, fn=lambda c: spend(c, 1.70)), e2, e3])
    assert [r.status for r in rows] == ["ran", "skipped", "ran"] and rows[2].cap == pytest.approx(0.30)
    assert sum(r.cost for r in rows) <= P.TOTAL_CAP_USD + 1e-9


def test_a_session_never_gets_more_than_its_probe_has_left(sdk, tmp_path):
    w = World(tmp_path)
    ctx = P.Ctx(P.PROBES[2], w.cfg(), helper(), 0.40)
    assert ctx.budget(0.5) == 0.2 and ctx.budget(1.0, usd=0.05) == 0.05
    ctx.costs[1] = 0.2512345
    assert 0 < ctx.budget() <= 0.40 - 0.2512345
    ctx.costs[2] = 0.13
    with pytest.raises(P.BudgetError):                          # 0.0187 left: under MIN_SESSION_USD
        ctx.budget()
    with pytest.raises(P.BudgetError):
        ctx.check(types.SimpleNamespace(max_budget_usd=0.05))
    assert P.Ctx(P.PROBES[0], w.cfg(), helper(), 0.05).cap == 0.05


def test_e2c_counts_at_its_whole_cap_and_reads_server_info_only(sdk, tmp_path):
    w = World(tmp_path)
    (row,) = run(w, [P.PROBES[1]])
    e2c = w.opened[0]
    assert e2c.max_budget_usd == 0.05 and row.facts["sessions_without_result"] == 1
    assert row.facts["e2c_e2_cwd"] is True and row.facts["e2c_e2_adddir"] is True
    assert row.facts["e2c_e2_above"] is False and row.facts["e2c_e2_subdir"] is False
    assert row.facts["e2b_init_frames"] == 2 and row.facts["e2b_in_first_init"] is False
    assert row.facts["e2b_in_last_init"] is True
