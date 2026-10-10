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
GUARD_DIR = ROOT / "dot-config" / "dot-claude" / "hooks"


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
# name -> (permissionMode, tools, model): blackcat as installed has no Bash (the first runs' E1 lesson)
STACK_AGENTS = {"blackcat": (None, "Agent, Read", "sonnet"), "explore": (None, None, None),
                "coder": ("acceptEdits", None, None), "verifier": (None, "Read, Bash", "sonnet")}
FAKE_SONNET = "claude-sonnet-fake"
SWITCHES = dict(
    agent_flag=True,        # E1: the CLI runs the --agent main thread (else settings.json's agent, blackcat)
    agent_setting_row=True, # E1: the session transcript has its agent-setting row
    init_model=True,        # E1: the init frame names the model
    main_tools=None,        # E1: the main agent's tools override (None: its frontmatter's)
    invalid_legs=(),        # E1: legs (cwd names) whose transcript has no agent-setting row
    trust_gate=True,        # E1: project allow rules are dropped in an untrusted workspace
    trust_warning=True,     # E1: ... and the CLI says so on stderr
    sandboxed_trusts=True,  # E1: CLAUDE_CODE_SANDBOXED=1 trusts the workspace
    sandboxed_opens=False,  # E1: CLAUDE_CODE_SANDBOXED=1 also runs Bash without a rule (the trusted control too)
    meta_early=True,        # E3e: a child's meta.json exists before its first tool call
    hook_paths=True,        # E3e: hook events carry transcript_path
    agent_meta_tid=True,    # E3c2a: an Agent child's meta.json has toolUseId
    refuse_stopped=False,   # E3d: SendMessage to a stopped child is refused (success false), nothing resumes
    refuse_any=False,       # E3c2a: every SendMessage resume is refused
    rules_bind=True,        # E1: an allow rule runs Bash under plan
    plan_open=False,        # E1: plan runs Bash without any rule
    sandbox_auto=False,     # E1: the installed sandbox auto-allows Bash (unless the session's settings turn it off)
    auto_plan=False,        # E1: the installed defaultMode is auto, and under plan its classifier runs Bash with no
                            # rule unless the session's settings say useAutoModeDuringPlan false (the CLI's default:
                            # true): the 2026-10-10 world, where the control ran
    overlay_ignored=False,  # E1: the CLI ignores useAutoModeDuringPlan in the session's settings
    guard_decides=False,    # E1: a PreToolUse hook (the guard) denies the Bash call
    ro_guard=True,          # E1: the repo's agent_guard read-only rule (READONLY_TYPES main thread) runs for real
    silent_send=False,      # E3c2a: the model makes no SendMessage call, yet the child's transcript grows
    send_denied=False,      # E3c2a: the SendMessage call is denied (an is_error result), yet the transcript grows
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
    late_wake=False,        # E3d: that wake's result lands only after the next query, whose turn then never ends
    denials_listed=True,    # E1c: a denied call shows in the result's permission_denials
    hollow=False,           # no tool is ever called
    stack_rule=True,        # E1c: the stack's exact rule is installed
    bg_any_kind=False,      # E2a: the env rules apply whatever CLAUDE_CODE_SESSION_KIND says (the control too)
    cost=0.01,              # every result's total_cost_usd (None: the field is missing)
)


class World:
    def __init__(self, tmp, **kw):
        assert not set(kw) - set(SWITCHES), set(kw) - set(SWITCHES)
        self.__dict__.update(SWITCHES, **kw)
        self.tmp, self.config = tmp, tmp / "config"
        (self.config / "agents").mkdir(parents=True)
        for name, (mode, tools, model) in STACK_AGENTS.items():
            extra = "".join("%s: %s\n" % (k, v) for k, v in (("permissionMode", mode), ("tools", tools),
                                                                ("model", model)) if v)
            (self.config / "agents" / (name + ".md")).write_text("---\nname: %s\ndescription: x\n%s---\nbody\n" % (
                name, extra))
        allow = ([P.STACK_RULE] if self.stack_rule else []) + ["mcp__exa", "Read"]
        (self.config / "settings.json").write_text(json.dumps({
            "agent": "blackcat", "hooks": {"SessionStart": [{"hooks": [{"type": "command", "command": "guard"}]}]},
            "permissions": dict({"allow": allow}, **({"defaultMode": "auto"} if self.auto_plan else {})),
            "sandbox": {"enabled": True, "autoAllowBashIfSandboxed": True}}))
        self.cli = tmp / "bin" / "claude"
        self.cli.parent.mkdir()
        self.cli.write_text("#!/bin/sh\nexit 1\n")
        self.cli.chmod(0o755)
        self.ids, self.opened, self.answers, self.scripts, self.projects = itertools.count(1), [], [], {}, {}

    def factory(self, opts):
        self.opened.append(opts)
        return FakeCLI(self, opts)

    def cfg(self, **kw):
        return P.Config(config_dir=str(self.config), cli_path=str(self.cli), transport_factory=self.factory,
                        **dict(dict(turn_s=10.0, wait_s=1.0, hold_s=5.0, settle_s=0.01), **kw))


def fm(path):
    """name and permissionMode of a markdown file's frontmatter."""
    text = Path(path).read_text()
    return {k: v.strip() for k, v in re.findall(r"(?m)^(name|permissionMode|agent|tools|model):(.*)$",
                                                text.split("\n---", 1)[0])}


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
        self.turn_open, self.hold, self.started, self.deferred = False, None, False, False
        self.agents0 = self.agent_names()
        # the main thread's agent: --agent if the CLI honours it, else settings.json's "agent" (user settings)
        self.main = (opts.extra_args or {}).get("agent") if w.agent_flag else None
        if self.main is None and self.user:
            self.main = json.loads((w.config / "settings.json").read_text()).get("agent")
        path = w.config / "agents" / ("%s.md" % self.main)
        self.main_fm = fm(path) if self.main and path.exists() else {}

    # Transport
    async def connect(self):
        proj = self.cwd / ".claude" / "settings.json"
        rules = proj.exists() and (json.loads(proj.read_text()).get("permissions") or {}).get("allow")
        if proj.exists():
            self.w.projects[self.cwd.name] = json.loads(proj.read_text())
        if rules and not self.trusted() and self.w.trust_warning and self.o.stderr is not None:
            self.o.stderr("Ignoring %d permissions.allow entry from .claude/settings.json: this workspace has not "
                          "been trusted. %s" % (len(rules), LEAK))
        if self.o.stderr is not None:
            self.o.stderr("other stderr text " + LEAK)

    def trusted(self):
        return not self.w.trust_gate or self.env.get("CLAUDE_CODE_SANDBOXED") == "1" and self.w.sandboxed_trusts

    def tools(self):
        t = self.w.main_tools if self.w.main_tools is not None else self.main_fm.get("tools")
        return [x.strip() for x in t.split(",")] if t else ["Agent", "Bash", "Read"]

    def model(self):
        return FAKE_SONNET if self.main_fm.get("model") == "sonnet" else "fake-%s" % (self.o.model or "model")

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
        if self.env.get("CLAUDE_CODE_SESSION_KIND") != "bg" and not self.w.bg_any_kind or not self.w.bg_rules:
            return None
        return json.loads(self.env.get("CLAUDE_BG_SESSION_PERMISSION_RULES") or "null")

    def rules(self):
        allow, deny = set(self.o.allowed_tools or []), set(self.o.disallowed_tools or [])
        proj = self.cwd / ".claude" / "settings.json"
        if proj.exists() and self.trusted():
            allow |= set((json.loads(proj.read_text()).get("permissions") or {}).get("allow") or [])
        if self.user:
            allow |= set(json.loads((self.w.config / "settings.json").read_text())["permissions"]["allow"])
        if self.bg():
            allow |= set(self.bg()["allow"])
            deny |= set(self.bg()["deny"])
        return allow, deny

    def settings(self):
        """The session's --settings overlay (JSON text, as the probe sends it; None or not an object: {})."""
        obj = json.loads(self.o.settings) if self.o.settings else {}
        return obj if isinstance(obj, dict) else {}

    def bash_ok(self, cmd):
        allow, deny = self.rules()
        rule = "Bash(%s)" % cmd
        if rule in deny:
            return False
        if self.env.get("CLAUDE_CODE_SANDBOXED") == "1" and self.w.sandboxed_opens:
            return True
        overlay = self.settings()
        auto = self.w.overlay_ignored or overlay.get("useAutoModeDuringPlan", True) is not False
        if self.mode == "plan" and self.user and self.w.auto_plan and auto:     # the classifier under plan
            return True
        if rule in allow:
            return self.mode != "plan" or self.w.rules_bind
        if self.mode == "plan" and self.w.plan_open:
            return True
        return self.user and self.w.sandbox_auto and (overlay.get("sandbox") or {}).get("autoAllowBashIfSandboxed") \
            is not False

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
        if self.w.wake_on_stop and self.w.late_wake:
            self.deferred = True                                # its result comes with the next query
        elif self.w.wake_on_stop:
            self.turn_open = True
            self.emit(self.asst({"type": "text", "text": LEAK}))
            self.finish()

    async def hook(self, tool, mode, aid=None, atype=None):
        """The project's PreToolUse command hooks, run for real (the probe's logger)."""
        proj = self.cwd / ".claude" / "settings.json"
        if not self.w.hooks_run or not proj.exists():
            return
        main = self.w.config / "projects" / "-fake" / (self.sid + ".jsonl")
        payload = dict({"hook_event_name": "PreToolUse", "tool_name": tool, "tool_input": {"x": LEAK},
                        "permission_mode": mode, "session_id": self.sid, "cwd": str(self.cwd), "prompt": LEAK},
                       **({"transcript_path": str(main)} if self.w.hook_paths else {}),
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

    def tool_result(self, tu, error, content=LEAK, tur=None):
        self.emit(dict({"type": "user", "message": {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": tu, "is_error": error, "content": content}]},
            "parent_tool_use_id": None, "session_id": self.sid}, **({"tool_use_result": tur} if tur else {})))

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

    def child(self, aid, agent, tu, match="fork"):
        """match: True (toolUseId = the spawning call), False (another id), None (no toolUseId); "fork": as
        the meta_tid_match switch says."""
        match = self.w.meta_tid_match if match == "fork" else match
        (self.subagents() / ("agent-%s.meta.json" % aid)).write_text(json.dumps(
            {"agentType": agent, "description": LEAK, **({} if match is None else
                                                          {"toolUseId": tu if match else "tu-other"})}))
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
            rows = [{"entrypoint": "sdk-py", "message": text}]
            if self.main and self.w.agent_setting_row and self.cwd.name not in self.w.invalid_legs:
                rows.append({"type": "agent-setting", "agentSetting": self.main, "sessionId": self.sid})
            (proj / (self.sid + ".jsonl")).write_text("".join(json.dumps(r) + "\n" for r in rows))
        self.turn_open = True
        names = self.agent_names() if self.w.late_agents else self.agents0
        self.emit(self.sysm("init", agents=sorted(names), permissionMode=self.mode, tools=self.tools(),
                            claude_code_version="2.1.287", cwd=str(self.cwd),
                            **({"model": self.model()} if self.w.init_model else {})))
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
        if "Bash" not in self.tools():                         # "I have no Bash tool" (the first runs' E1)
            self.emit(self.asst({"type": "text", "text": LEAK}))
            self.finish()
            return
        tu = self.use("Bash", {"command": command})
        if command.startswith("sh "):                          # the probe's e1.sh, as the CLI would run it
            self.w.scripts[self.cwd.name] = Path(command[3:]).read_text()
        denied = self.w.guard_decides or self.read_only_refuses(command)
        if self.o.include_hook_events:
            out = json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                                     "permissionDecisionReason": LEAK}}) if denied else ""
            self.emit(self.sysm("hook_started", hook_id="hp", hook_event="PreToolUse", hook_name="PreToolUse:Bash"))
            self.emit(self.sysm("hook_response", hook_id="hp", hook_event="PreToolUse", hook_name="PreToolUse:Bash",
                                outcome="success", exit_code=0, stdout=out, output=out))
        ok = not denied and self.bash_ok(command)
        if ok and command.startswith("sh "):                    # e1.sh: `touch <marker>`
            Path(Path(command[3:]).read_text().split(None, 1)[1].strip()).touch()
        self.tool_result(tu, not ok or command == P.STACK_RULE_CMD)        # no justfile: the command fails
        self.finish(permission_denials=[] if ok or not self.w.denials_listed else [
            {"tool_name": "Bash", "tool_use_id": tu, "tool_input": {"command": LEAK}}])

    def read_only_refuses(self, command):
        """agent_guard's PreToolUse rule for a READONLY_TYPES agent, the repo's own code: hooks see the --agent
        main thread's agent_type, and CLAUDE_PROJECT_DIR is the session's cwd (a temp project is the project)."""
        if not (self.w.ro_guard and self.user and self.main):
            return False
        g = guard()
        if self.main not in g.READONLY_TYPES:
            return False
        from unittest import mock
        with mock.patch.dict(os.environ, {"CLAUDE_PROJECT_DIR": str(self.cwd)}):
            return g.readonly_violation(command, {"cwd": str(self.cwd), "agent_type": self.main}) is not None

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

    async def play_e3_fg(self, agent, path):
        """E3P: a foreground Agent child reads a file and finishes; its meta.json is written before or after its
        first tool call (meta_early)."""
        tu = self.use("Agent", {"subagent_type": agent, "prompt": LEAK})
        if not await self.ask("Agent", {"subagent_type": agent}):
            self.tool_result(tu, True)
            self.finish()
            return
        aid = "afg%d" % self.n
        if self.w.meta_early:
            self.child(aid, agent, tu, self.w.agent_meta_tid)
        self.started_task("tg", tu, agent)
        await self.hook("Read", self.mode, aid, agent)
        if not self.w.meta_early:
            self.child(aid, agent, tu, self.w.agent_meta_tid)
        self.use("Read", {"file_path": path}, parent=tu)
        self.done_task("tg", tu)
        self.tool_result(tu, False)
        self.finish()

    async def play_e3_send(self, agent_id):
        late = self.deferred
        if late:                                                # the earlier turn's result, late
            self.deferred = False
            self.emit(self.asst({"type": "text", "text": LEAK}))
            self.finish()
            self.turn_open = True
        if self.w.silent_send:                                  # no call; the child's transcript grows anyway
            p = self.subagents() / ("agent-%s.jsonl" % agent_id)
            if p.exists():
                p.write_text(p.read_text() + json.dumps({"m": 4}) + "\n")
            self.emit(self.asst({"type": "text", "text": LEAK}))
            self.finish()
            return
        tu = self.use("SendMessage", {"to": agent_id, "message": LEAK})
        if late:
            return                                              # the resume turn is still running
        await self.hook("SendMessage", self.mode)
        p = self.subagents() / ("agent-%s.jsonl" % agent_id)
        if self.w.send_denied:                                  # denied (host or hook); the transcript grows anyway
            if p.exists():
                p.write_text(p.read_text() + json.dumps({"m": 5}) + "\n")
            self.tool_result(tu, True)
            self.finish()
            return
        mp = self.subagents() / ("agent-%s.meta.json" % agent_id)
        meta = json.loads(mp.read_text()) if mp.exists() else {}
        refuse = self.w.refuse_any or self.w.refuse_stopped and meta.get("stoppedByUser") is True
        allowed = await self.ask("SendMessage", {"to": agent_id})
        if allowed and p.exists() and refuse:                   # CLI 2.1.287 on a stopped child
            why = "Agent %s was stopped by the user and was not resumed" % agent_id
            self.tool_result(tu, False, content=json.dumps({"success": False, "message": why}),
                             tur={"success": False, "message": why})
        elif allowed and p.exists() and self.w.resume:
            if meta.get("agentType") == "e3-echo":              # E3P's resumed child calls a tool again
                await self.hook("Read", self.mode, agent_id, "e3-echo")
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


_GUARD = []


def guard():
    """The repo's hooks/agent_guard.py (imported once, from its own directory: it loads siblings lazily)."""
    if not _GUARD:
        if str(GUARD_DIR) not in sys.path:
            sys.path.insert(0, str(GUARD_DIR))
        import agent_guard
        _GUARD.append(agent_guard)
    return _GUARD[0]


def run(world, probes=None, ledger=None, total=None, **cfg):
    """The whole run, bounded; the world's config is the CLI's own (CLAUDE_CONFIG_DIR), as the probes require."""
    from unittest import mock
    with mock.patch.dict(os.environ, {"CLAUDE_CONFIG_DIR": str(world.config)}):
        return asyncio.run(asyncio.wait_for(P.run_probes(probes or P.PROBES, world.cfg(**cfg), helper(),
                                                         ledger=ledger, total=total), 120))


def answers(rows):
    return {k: v for r in rows for k, v in r.answers.items()}


def probe_of(opts):
    """The probe a session belonged to: its cwd lies under the probe's sdk-probe-<id>- temp dir."""
    return re.search(r"sdk-probe-(e\d\w*)-", str(opts.cwd)).group(1).upper()


def assert_no_prompt_text(text):
    flat = " ".join(text.split())
    for p in [*P.PROMPTS.values(), P.LATE_BODY, P.WRITER_BODY, P.HOLDER_BODY]:
        p = " ".join(p.split())
        for i in range(max(1, len(p) - 23)):
            assert p[i:i + 24] not in flat, p[i:i + 24]


GOOD = {"E1a": "yes", "E1bu": "dropped (untrusted)", "E1bt": "yes", "E1c": "unknown", "E1d": "no", "E2a": "yes",
        "E2b": "yes", "E2c1": "no", "E2c2": "no", "E3a": "yes", "E3b": "yes", "E3c1": "yes", "E3c2": "yes",
        "E3d": "yes", "E3c2a": "yes", "E3e": "yes"}
FLIPPED = dict(rules_bind=False, sandbox_auto=True, bg_rules=False, late_agents=False, above_git=True, add_subdir=True,
               own_mode=True, hook_own_mode=False, meta_tid_match=False, tid_survives=False, stopped_survives=False,
               meta_early=False)
FLIPPED_ANSWERS = {"E1a": "no", "E1bu": "dropped (untrusted)", "E1bt": "no", "E1c": "unknown", "E1d": "yes", "E2a": "no",
                   "E2b": "no", "E2c1": "yes", "E2c2": "yes", "E3a": "yes", "E3b": "no", "E3c1": "no", "E3c2": "no",
                   "E3d": "no", "E3c2a": "no", "E3e": "no"}
E1_PARTS = ["E1a", "E1bu", "E1bt", "E1c", "E1d"]
E1_RUN = [x[0] for x in P.E1_LEGS if x[1] != "stack"]       # the legs E1 runs (E1C_NOT_RUN: not the stack's rule)
LEDGERS = ROOT / "tests" / "fixtures" / "sdk" / "probes_e_ledgers"   # the first runs' three ledgers, 2026-10-09
PRIOR_USED = 1.404122                       # their worst case (analysis §0: $1.4041), replayed by hand below


# ---------------------------------------------------------------- the envelope and the caps (pure)
def test_registry_caps_fit_the_consent_envelope():
    caps = {p.pid: (p.group, p.budget_usd, p.max_turns) for p in P.PROBES}
    assert caps == {"E1": ("E1E2", 0.40, 3), "E2": ("E1E2", 0.60, 4), "E3": ("E3", 0.40, 8), "E3P": ("E3", 0.10, 6)}
    assert P.ENVELOPE == {"E1E2": 1.50, "E3": 0.50} and P.TOTAL_CAP_USD == 2.00 and P.CONSENT_VALUE == "2.00"
    assert P.MODEL == "haiku" and P.MIN_SESSION_USD == 0.02 and P.E1_AGENT == "verifier"
    assert P.E1_SESSION_USD == 0.08 and P.E3P_SESSION_USD == 0.08 and P.TRUST_ENV == {"CLAUDE_CODE_SANDBOXED": "1"}
    for p in P.PROBES:
        assert 0 < p.est_usd[0] <= p.est_usd[1], p.pid
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
    e1, e2, e3, e3p = P.PROBES
    with pytest.raises(P.BudgetError):          # E1+E2 above 1.50, each within it, the total within 2.00
        P.validate_registry([dataclasses.replace(e1, budget_usd=0.8), dataclasses.replace(e2, budget_usd=0.8),
                             dataclasses.replace(e3, budget_usd=0.3)])
    with pytest.raises(P.BudgetError):
        P.validate_registry([dataclasses.replace(e1, budget_usd=0.9), dataclasses.replace(e2, budget_usd=0.9), e3])
    with pytest.raises(P.BudgetError):          # E3 above its 0.50
        P.validate_registry([e1, e2, dataclasses.replace(e3, budget_usd=0.51)])
    with pytest.raises(P.BudgetError):          # E3+E3P above 0.50
        P.validate_registry([e1, e2, dataclasses.replace(e3, budget_usd=0.41), e3p])
    with pytest.raises(P.BudgetError):
        P.validate_registry([e1, e1])
    P.validate_registry([dataclasses.replace(e1, budget_usd=0.75), dataclasses.replace(e2, budget_usd=0.75),
                         e3, e3p])               # exactly the envelope
    assert not P.valid_cost(None) and not P.valid_cost(True) and not P.valid_cost(-0.01)
    assert not P.valid_cost(math.nan) and not P.valid_cost(math.inf) and not P.valid_cost("0.1")
    assert P.valid_cost(0) and P.valid_cost(0.25)


@pytest.fixture
def probes_dir(monkeypatch, tmp_path):
    """The default report directory (<main checkout>/.claude-work/sdk/probes) moved under tmp_path: the cross-run
    check reads only what a test puts there, never the real ledgers."""
    d = tmp_path / "default-probes"
    monkeypatch.setattr(P.base, "default_out", lambda today: str(d / (today + ".md")))
    return d


def seed(d, *names):
    """The first runs' ledgers (or some of them) in directory d."""
    d.mkdir(parents=True, exist_ok=True)
    for n in names or [p.name for p in LEDGERS.iterdir()]:
        (d / n).write_text((LEDGERS / n).read_text())


def test_dry_run_is_the_default_and_spends_nothing(capsys, monkeypatch, probes_dir):
    monkeypatch.setattr(P, "run_probes", None)                 # would raise if called
    monkeypatch.setattr(P.base, "load_helper", None)
    monkeypatch.delenv(P.CONSENT_ENV, raising=False)
    assert P.main([]) == 0
    out = capsys.readouterr().out
    assert out.startswith("DRY RUN") and "at most $2.00 in all, across runs" in out
    assert re.search(r"^E1\s+\$0\.40 ", out, re.MULTILINE) and re.search(r"^E3P\s+\$0\.10 ", out, re.MULTILINE)
    assert "this run's cap 2.00 (consent value 2.00)" in out and "model haiku" in out and "verifier" in out
    for pid in PARTS:
        assert re.search(r"^\s+%s\s" % pid, out, re.MULTILINE), pid
    assert "prior spend: 0 ledgers" in out and "would START" in out
    assert P.main(["--dry-run", "--only", "e1,e3p"]) == 0
    out = capsys.readouterr().out
    assert re.search(r"^E3P\s+\$", out, re.MULTILINE) and not re.search(r"^E2\s+\$", out, re.MULTILINE)
    assert "this run's cap 0.50 (consent value 0.50)" in out
    assert "%s=0.50 uv run --locked --script tests/sdk_probes_e.py --paid --only E1,E3P" % P.CONSENT_ENV in out
    monkeypatch.setenv(P.CONSENT_ENV, P.CONSENT_VALUE)        # the env alone is still a dry run
    assert P.main([]) == 0
    assert "without --paid this is a dry run" in capsys.readouterr().out
    with pytest.raises(SystemExit):
        P.main(["--only", "E9"])
    with pytest.raises(SystemExit):
        P.main(["--paid", "--dry-run"])


def test_the_dry_run_prints_what_the_first_runs_left(capsys, monkeypatch, probes_dir):
    """The first runs' three ledgers: $1.4041 at worst, $0.5959 left; E1+E3P (0.50) would start, all of E1-E3
    (2.00) would be refused; an unreadable ledger is reported, not a crash."""
    monkeypatch.setattr(P, "run_probes", None)
    seed(probes_dir)
    assert P.main(["--only", "E1,E3P"]) == 0
    out = capsys.readouterr().out
    assert "prior spend: 3 ledgers" in out and "= USD 1.4041 at worst; left of the 2.00: USD 0.5959" in out
    assert "would START (prior 1.4041 + cap 0.50 <= 2.00)" in out
    assert P.main([]) == 0
    assert "would be REFUSED" in capsys.readouterr().out
    (probes_dir / "broken.ledger.jsonl").write_text("{not json\n")
    assert P.main(["--only", "E1,E3P"]) == 0
    assert "prior spend: unreadable (broken.ledger.jsonl:1 is not JSON): a paid run would be refused" in \
        capsys.readouterr().out


V2_HELPER = types.SimpleNamespace(options=None, **dict.fromkeys(P.E1_NEEDS))     # the names main() checks


@pytest.fixture
def pinned(monkeypatch, probes_dir):
    monkeypatch.setattr(P.base, "versions", lambda cli: {"sdk": P.SDK_PIN, "system_cli": None, "bundled_cli": None})
    monkeypatch.setattr(P.base, "load_helper", lambda config: V2_HELPER)
    return probes_dir


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
        P.main(["--paid", "--cli", "/nonexistent/claude", "--out", str(tmp_path / "r" / "r.md")])
    assert e.value.code == 2 and called == [] and not (tmp_path / "r").exists()
    assert P.CONSENT_ENV in capsys.readouterr().err


@pytest.mark.parametrize("only, good, bad", [
    ("E1,E3P", "0.50", ["2.00", "0.40", "0.10", "0.5", "0.55"]),
    ("E3P", "0.10", ["2.00", "0.1", "0.50"]),
    ("E1,E2,E3", "2.00", ["1.40", "1.45"]),            # all of E1-E3: the first run's value
    ("E1,E2,E3,E3P", "2.00", ["1.50"]),
    ("E2,E3", "1.00", ["2.00"])])
def test_the_consent_value_is_the_runs_own_cap(pinned, monkeypatch, tmp_path, capsys, only, good, bad):
    """SDK_PROBES_E_CONSENT must equal the run's cap (the selected caps' sum as %.2f), 2.00 only when all of
    E1, E2 and E3 are selected; the run is bounded by that cap (run_probes total)."""
    probes = [p for p in P.PROBES if p.pid in only.split(",")]
    assert P.consent_value(probes) == good and P.run_cap(probes) == float(good)
    seen = []

    async def record(probes, cfg, helper, rows, ledger, total=None):
        seen.append(([p.pid for p in probes], total))
    monkeypatch.setattr(P, "run_probes", record)
    for value in bad:
        monkeypatch.setenv(P.CONSENT_ENV, value)
        with pytest.raises(SystemExit) as e:
            P.main(["--paid", "--cli", "/x", "--only", only, "--out", str(tmp_path / "r.md")])
        assert e.value.code == 2 and seen == [] and "%s=%s" % (P.CONSENT_ENV, good) in capsys.readouterr().err
    monkeypatch.setenv(P.CONSENT_ENV, good)
    P.main(["--paid", "--cli", "/x", "--only", only, "--out", str(tmp_path / "r.md")])
    assert seen == [(only.split(","), float(good))]
    env = json.loads((pinned / "r.ledger.jsonl").read_text().splitlines()[0])         # the default directory
    assert env["consent_value"] == good and env["run_cap_usd"] == float(good) and env["total_usd"] == 2.0


def test_a_paid_run_logs_the_envelope_first_and_reports(pinned, monkeypatch, tmp_path, capsys):
    monkeypatch.setenv(P.CONSENT_ENV, P.CONSENT_VALUE)
    seen = {}

    async def one(probes, cfg, helper, rows, ledger, total=None):
        seen["ledger"], seen["total"] = ledger, total
        rows.append(P.Row(probes[0], {"E1a": "yes"}, 0.45, cost=0.01, sessions=["sess-1"], models=["m-1", "m-1"]))
        ledger({"ev": "cost", "probe": "E1", "session": 0, "usd": 0.01, "note": P.PROMPTS["e1_bash"]})
        raise KeyboardInterrupt                                 # Ctrl-C: the report and the ledger still close
    monkeypatch.setattr(P, "run_probes", one)
    with pytest.raises(KeyboardInterrupt):
        P.main(["--paid", "--cli", "/nonexistent/claude", "--out", str(tmp_path / "r.md")])
    led = pinned / "r.ledger.jsonl"                             # the ledger: always the default directory
    lines = [json.loads(x) for x in led.read_text().splitlines()]
    assert lines[0]["ev"] == "envelope" and lines[0]["total_usd"] == 2.0 and lines[0]["groups_usd"] == P.ENVELOPE
    assert lines[0]["consent_env"] == P.CONSENT_ENV and lines[0]["consent_value"] == "2.00"
    assert lines[0]["caps_usd"] == {"E1": 0.4, "E2": 0.6, "E3": 0.4, "E3P": 0.1} and lines[0]["flag"] == "--paid"
    assert lines[0]["prior"] == {"ledgers": 0, "reported": 0, "unreported": 0, "used": 0, "left": 2.0}
    assert lines[0]["e1_agent"] == "verifier" and seen["total"] == 2.0
    assert lines[1]["note"] == P.base.WITHHELD and lines[-1]["ev"] == "end"
    assert os.stat(led).st_mode & 0o777 == 0o600
    text = (tmp_path / "r.md").read_text()
    assert "Consent envelope 2026-10-09: the user's decision of 2026-10-09" in text and "| E1 | ran |" in text
    assert lines[0]["envelope"] == P.LEGACY_ENVELOPE and lines[0]["consent_date"] == "2026-10-09"
    assert "main-thread models (each session's init frame): E1 m-1 x2" in text
    assert "This run's cap (%s): USD 2.00" % P.CONSENT_ENV in text
    assert "Ledger: %s" % led in capsys.readouterr().out
    monkeypatch.setenv(P.CONSENT_ENV, "0.10")                   # a second run never overwrites either file
    with pytest.raises(KeyboardInterrupt):
        P.main(["--paid", "--cli", "/x", "--only", "E3P", "--out", str(tmp_path / "r.md")])
    assert (tmp_path / "r-2.md").exists() and (pinned / "r-2.ledger.jsonl").exists()
    first = json.loads((pinned / "r-2.ledger.jsonl").read_text().splitlines()[0])
    assert first["prior"]["ledgers"] == 1 and first["prior"]["used"] == pytest.approx(0.01)


def test_an_unpinned_sdk_or_an_unwritable_report_is_refused_before_any_call(monkeypatch, tmp_path, probes_dir):
    monkeypatch.setenv(P.CONSENT_ENV, P.CONSENT_VALUE)
    monkeypatch.setattr(P, "run_probes", None)
    monkeypatch.setattr(P.base, "versions", lambda cli: {"sdk": "0.2.164", "system_cli": None, "bundled_cli": None})
    with pytest.raises(SystemExit):
        P.main(["--paid", "--cli", "/x", "--out", str(tmp_path / "r.md")])
    monkeypatch.setattr(P.base, "versions", lambda cli: {"sdk": P.SDK_PIN, "system_cli": None, "bundled_cli": None})
    monkeypatch.setattr(P.base, "load_helper", lambda config: V2_HELPER)
    with pytest.raises(SystemExit):
        P.main(["--paid", "--cli", "/x", "--out", "/dev/null/x/r.md"])
    assert not list(tmp_path.glob("r*"))


def test_e1_needs_the_v2_helper_installed_and_the_others_do_not(pinned, monkeypatch, tmp_path, capsys):
    """The installed stack_sdk.py is checked before the ledger opens: without Session & co. E1 cannot run, so
    a paid run with E1 is refused at $0; E2, E3 and E3P need only options()."""
    called = []

    async def record(probes, cfg, helper, rows, ledger, total=None):
        called.append([p.pid for p in probes])
    monkeypatch.setattr(P, "run_probes", record)
    monkeypatch.setattr(P.base, "load_helper", lambda config: types.SimpleNamespace(options=None))
    for only in ("E1,E2,E3,E3P", "E1", "E1,E3P"):
        monkeypatch.setenv(P.CONSENT_ENV, P.consent_value([p for p in P.PROBES if p.pid in only.split(",")]))
        with pytest.raises(SystemExit) as e:
            P.main(["--paid", "--cli", "/x", "--out", str(tmp_path / "r.md"), "--only", only])
        assert e.value.code == 2 and called == [] and not list(tmp_path.glob("r*"))
        assert "Session" in capsys.readouterr().err
    monkeypatch.setenv(P.CONSENT_ENV, "1.10")
    P.main(["--paid", "--cli", "/x", "--out", str(tmp_path / "r.md"), "--only", "E2,E3,E3P"])
    assert called == [["E2", "E3", "E3P"]]
    for name in P.E1_NEEDS:                     # what E1 calls on the helper is what the check asks for
        assert hasattr(helper(), name), name


# ---------------------------------------------------------------- the cross-run ledger check
def test_the_first_runs_ledgers_replay_to_the_analysis_figure():
    """analysis §0: -e 0.2568 (two reported + one session at its 0.12 cap), -e-2 0.6152 (E2c's connect-only
    0.05 and E3's open turn at its 0.20 cap), -e-3 0.5321; $1.4041 at worst, $0.5959 left. The replay sums the
    ledger's per-session costs, each rounded to 1e-6 when logged, so it lands 4e-6 above the probe_end totals
    (1.404122, not 1.404118): the larger counts. The analysis's $1.1286 'reported' counted E2c's never-reported
    0.05 bookings and E3's first turn as reported; here a session whose last ledger word is a reservation is
    unreported at its whole cap (0.12 + 0.05 + 0.20 + 0.05)."""
    per = {p.name: P.ledger_spend(str(p)) for p in LEDGERS.iterdir()}
    assert {k: round(v["used"], 6) for k, v in per.items()} == {
        "2026-10-09-e.ledger.jsonl": 0.256817, "2026-10-09-e-2.ledger.jsonl": 0.615173,
        "2026-10-09-e-3.ledger.jsonl": 0.532132}
    prior = P.prior_spend([str(LEDGERS)])
    assert prior == {"envelope": P.LEGACY_ENVELOPE, "total": 2.0, "ledgers": 3, "other_ledgers": 0,
                     "reported": 0.984122, "unreported": 0.42, "used": PRIOR_USED, "left": round(2.0 - PRIOR_USED, 6)}
    assert {P.ledger_spend(str(p))["envelope"] for p in LEDGERS.iterdir()} == {P.LEGACY_ENVELOPE}
    assert round(prior["left"], 4) == 0.5959 and PRIOR_USED + 0.50 <= 2.0
    # the same file reached twice (the default and the report directory are one) counts once
    assert P.prior_spend([str(LEDGERS), str(LEDGERS) + "/."])["used"] == PRIOR_USED


def test_ledger_replay_books_reservations_at_cap_and_fails_closed(tmp_path):
    def spend(*events):
        p = tmp_path / "x.ledger.jsonl"
        p.write_text("".join(json.dumps(e) + "\n" for e in events))
        return P.ledger_spend(str(p))
    r = {"ev": "reserve", "probe": "E1", "session": 0, "usd": 0.2}
    assert spend(r)["used"] == 0.2 and spend(r)["unreported"] == 0.2             # never reported: its cap
    c = dict(r, ev="cost", usd=0.05)
    assert spend(r, c) == {"reported": 0.05, "unreported": 0, "used": 0.05, "envelope": None}   # a result replaces it
    turn = dict(r, turn=True)
    assert spend(r, c, turn)["used"] == 0.2                                     # an open turn: its cap again
    assert spend(r, c, turn, dict(c, usd=0.07))["used"] == 0.07
    assert spend(r, c, dict(c, usd=0.03))["used"] == 0.05                       # a later cost never lowers it
    unknown = {"ev": "cost_unknown", "probe": "E1", "session": 0, "booked_usd": 0.2}
    assert spend(r, unknown, dict(c, usd=0.01))["used"] == 0.2                  # unknown: booked for good
    assert spend(r, c, {"ev": "probe_end", "probe": "E1", "usd": 0.3})["used"] == 0.3   # never below a total
    assert spend(r, c, {"ev": "end", "usd": 0.4})["used"] == 0.4
    assert spend()["used"] == 0
    for bad in ("{not json", json.dumps({"ev": "spend", "usd": 0.5}), json.dumps(dict(c, usd=None)),
                json.dumps(dict(c, usd=-1)), json.dumps(dict(c, usd=float("nan"))), json.dumps(["cost"]),
                json.dumps(dict(r, usd=True)), json.dumps({"ev": "end"})):
        (tmp_path / "x.ledger.jsonl").write_text(json.dumps(r) + "\n" + bad + "\n")
        with pytest.raises(P.LedgerUnreadable):
            P.ledger_spend(str(tmp_path / "x.ledger.jsonl"))
    with pytest.raises(P.LedgerUnreadable):
        P.ledger_spend(str(tmp_path / "missing.ledger.jsonl"))


@pytest.mark.parametrize("only, value, starts", [("E1,E3P", "0.50", True), ("E3P", "0.10", True),
                                                 ("E1,E2", "1.00", False), ("E1,E2,E3", "2.00", False)])
def test_a_paid_run_is_refused_when_the_prior_ledgers_plus_its_cap_exceed_the_consent(
        pinned, monkeypatch, tmp_path, capsys, only, value, starts):
    called = []

    async def record(probes, cfg, helper, rows, ledger, total=None):
        called.append(total)
    monkeypatch.setattr(P, "run_probes", record)
    monkeypatch.setenv(P.CONSENT_ENV, value)
    out = tmp_path / "report" / "r.md"
    seed(out.parent)
    if starts:
        P.main(["--paid", "--cli", "/x", "--only", only, "--out", str(out)])
        assert called == [float(value)]
        assert "left of the 2.00: USD 0.5959" in capsys.readouterr().out
    else:
        with pytest.raises(SystemExit) as e:
            P.main(["--paid", "--cli", "/x", "--only", only, "--out", str(out)])
        assert e.value.code == 2 and called == [] and not (out.parent / "r.ledger.jsonl").exists()
        assert not (pinned / "r.ledger.jsonl").exists()
        assert "refused: the prior spend USD 1.4041 plus this run's cap" in capsys.readouterr().err


def test_the_default_directorys_ledgers_count_when_the_report_goes_elsewhere(pinned, monkeypatch, tmp_path, capsys):
    """--out elsewhere does not hide the earlier runs: the default directory is read too; and a fourth ledger
    that takes the prior spend past 1.50 refuses E1+E3P."""
    called = []

    async def record(probes, cfg, helper, rows, ledger, total=None):
        called.append(total)
    monkeypatch.setattr(P, "run_probes", record)
    monkeypatch.setenv(P.CONSENT_ENV, "0.50")
    seed(pinned)                                                    # the default directory
    (pinned / "2026-10-10-e.ledger.jsonl").write_text(json.dumps(
        {"ev": "reserve", "probe": "E1", "session": 0, "usd": 0.10}) + "\n")
    with pytest.raises(SystemExit) as e:
        P.main(["--paid", "--cli", "/x", "--only", "E1,E3P", "--out", str(tmp_path / "elsewhere" / "r.md")])
    assert e.value.code == 2 and called == []
    assert "refused: the prior spend USD 1.5041 plus this run's cap USD 0.50" in capsys.readouterr().err
    (pinned / "2026-10-10-e.ledger.jsonl").unlink()
    P.main(["--paid", "--cli", "/x", "--only", "E1,E3P", "--out", str(tmp_path / "elsewhere" / "r.md")])
    assert called == [0.50]


def test_an_unreadable_ledger_refuses_the_paid_run(pinned, monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(P, "run_probes", None)
    monkeypatch.setenv(P.CONSENT_ENV, "0.10")
    seed(pinned, "2026-10-09-e.ledger.jsonl")
    (pinned / "2026-10-09-e-9.ledger.jsonl").write_text(json.dumps({"ev": "spend", "usd": 0.5}) + "\n")
    with pytest.raises(SystemExit) as e:
        P.main(["--paid", "--cli", "/x", "--only", "E3P", "--out", str(tmp_path / "r.md")])
    assert e.value.code == 2 and "cannot be replayed" in capsys.readouterr().err
    assert not (tmp_path / "r.ledger.jsonl").exists()
    assert sorted(p.name for p in pinned.glob(P.LEDGER_GLOB)) == ["2026-10-09-e-9.ledger.jsonl", "2026-10-09-e.ledger.jsonl"]


def test_the_run_is_bounded_by_its_own_cap(sdk, tmp_path):
    """run_probes(total=0.55): E1 reports 0.50, so E3P gets 0.05 (not its 0.10), and a total outside (0, 2.00] is
    refused before anything starts."""
    e1, _, _, e3p = P.PROBES

    async def spend(c, usd):
        c.costs[99] = usd
    w = World(tmp_path)
    rows = run(w, [dataclasses.replace(e1, fn=lambda c: spend(c, 0.50)), e3p], total=0.55)
    assert [r.status for r in rows] == ["ran", "ran"] and rows[1].cap == pytest.approx(0.05)
    assert [o.max_budget_usd for o in w.opened] == [0.05]
    for bad in (0, -1, 2.01, True, float("nan")):
        with pytest.raises(P.BudgetError):
            asyncio.run(P.run_probes([e3p], w.cfg(), helper(), total=bad))


# ---------------------------------------------------------------- the report (pure)
def test_render_never_carries_prompt_text_and_lists_every_part(tmp_path):
    facts = {k: v for k, v in P.PROMPTS.items()}
    facts.update(nested={"deep": [P.PROMPTS["e3_hold"]]}, body=P.FORK_BODY)
    rows = [P.Row(P.PROBES[0], {"E1a": "yes"}, 0.6, facts=facts, sessions=["sess-1", P.PROMPTS["ok"]],
                  transcripts=["/a/b.jsonl", P.PROMPTS["e2_calls"] + ".jsonl"])]
    text = P.render(rows, {"date": "2026-10-09", "sdk": P.PROMPTS["e3_send"]})
    assert_no_prompt_text(text)
    assert P.base.WITHHELD in text and "/a/b.jsonl" in text and "sess-1" in text
    assert "| E1a |" in text and "| yes |" in text and "| E1bu |" in text and "| unknown |" in text
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
          "agent_type": "e3-writer", "tool_input": {"content": LEAK}, "cwd": LEAK}
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


def test_the_hook_logger_checks_meta_json_where_agent_guard_looks(tmp_path):
    """E3e: for a child's row, meta_json says whether <transcript minus .jsonl>/subagents/agent-<id>.meta.json
    (or the folder of agent_transcript_path, or a subagent transcript's own folder) exists now, and
    meta_tool_use_id whether it holds a toolUseId; a main-thread row gets neither, nor does a row without a path."""
    script, log = tmp_path / "h.py", tmp_path / "log.jsonl"
    script.write_text(P.HOOK_LOGGER)
    main = tmp_path / "proj" / "sess-1.jsonl"
    sub = tmp_path / "proj" / "sess-1" / "subagents"
    sub.mkdir(parents=True)
    base_ev = {"hook_event_name": "PreToolUse", "tool_name": "Read", "permission_mode": "default",
               "session_id": "sess-1"}

    def row(**kw):
        subprocess.run([sys.executable, "-I", str(script), str(log)], input=json.dumps(dict(base_ev, **kw)), text=True,
                       capture_output=True, timeout=30, check=True)
        return json.loads(log.read_text().splitlines()[-1])
    child = dict(agent_id="a1", agent_type="e3-echo", transcript_path=str(main))
    assert (row(**child)["meta_json"], row(**child)["meta_tool_use_id"]) == (False, False)
    (sub / "agent-a1.meta.json").write_text(json.dumps({"agentType": "e3-echo"}))
    assert (row(**child)["meta_json"], row(**child)["meta_tool_use_id"]) == (True, False)
    (sub / "agent-a1.meta.json").write_text(json.dumps({"agentType": "e3-echo", "toolUseId": "toolu_1"}))
    assert (row(**child)["meta_json"], row(**child)["meta_tool_use_id"]) == (True, True)
    assert row(**dict(child, transcript_path=str(sub / "agent-a1.jsonl")))["meta_json"] is True
    assert row(agent_id="a1", agent_transcript_path=str(sub / "agent-a1.jsonl"))["meta_json"] is True
    assert "meta_json" not in row(agent_id="a1") and "meta_json" not in row(transcript_path=str(main))
    assert "meta_json" not in row(**dict(child, agent_id="a/../x"))     # not an identifier: no lookup


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
        # E1: the verifier's own model decides (no model=); every other main thread: haiku
        assert o.model == (None if pid == "E1" else "haiku")
        assert 0 < o.max_turns <= next(p.max_turns for p in P.PROBES if p.pid == pid)
        assert o.strict_mcp_config is True and {"WebSearch", "WebFetch", "mcp__exa"} <= set(o.disallowed_tools)
        scratch = re.search(r"^(.*/sdk-probe-e\d\w*-[^/]+)/", str(o.cwd) + "/").group(1)
        assert o.env["XDG_STATE_HOME"] == scratch + "/state" and str(tmp_path) in scratch
        assert "CLAUDE_CONFIG_DIR" not in o.env and o.cli_path == str(w.cli)     # the keychain entry stays the default
    assert len(per["E1"]) == 7 and len(per["E2"]) == 4 and len(per["E3"]) == 2 and len(per["E3P"]) == 1
    for o in per["E1"]:             # stack_sdk.Session("verifier"), host none: plan, no prompts, the installed stack
        assert o.permission_mode == "plan" and o.extra_args["permission-prompts"] == "none" and o.can_use_tool is None
        assert "user" in o.setting_sources and "ExitPlanMode" in o.disallowed_tools and "Agent(coder)" in o.disallowed_tools
        assert o.extra_args["agent"] == "verifier" and callable(o.stderr) and o.max_budget_usd == 0.08
    explicit, plan_auto = (json.dumps(P.E1_OVERLAYS[k]) for k in ("explicit", "plan_auto"))
    assert [o.settings for o in per["E1"]] == [explicit] * 5 + [None, plan_auto]     # as_installed: the Session's own
    assert json.loads(explicit) == {"sandbox": {"autoAllowBashIfSandboxed": False}, "useAutoModeDuringPlan": False}
    assert [o.env.get("CLAUDE_CODE_SANDBOXED") for o in per["E1"]] == [None, None, None, "1", "1", None, None]
    assert [Path(o.cwd).name for o in per["E1"]] == E1_RUN            # E1c's stack leg is not run
    script = Path(per["E1"][1].cwd) / ".claude-work" / "e1.sh"      # scratch: the read-only guard lets it run
    assert per["E1"][1].allowed_tools == ["Bash(sh %s)" % script]
    assert w.scripts["session_rule"] == "touch %s/.claude-work/e1-session_rule.marker\n" % per["E1"][1].cwd
    for leg in (2, 3):              # the repo rule, untrusted and trusted: the same rule in the temp project
        proj = w.projects[Path(per["E1"][leg].cwd).name]
        assert proj == {"permissions": {"allow": ["Bash(sh %s/.claude-work/e1.sh)" % per["E1"][leg].cwd]}}
    for o in per["E2"] + per["E3"] + per["E3P"]:  # only the temp project's settings
        assert o.setting_sources == ["project"]
    assert per["E3P"][0].max_budget_usd == 0.08 and per["E3P"][0].permission_mode == "default"
    assert isinstance(per["E3P"][0].can_use_tool, P.base.Host)
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
    assert f1["stack_rule_verdict"] == "not_run" and "stack_rule_attempted" not in f1
    for leg in E1_RUN:                          # every leg valid: the verifier, Bash, a model
        assert f1[leg + "_hook_decisions"] == {}, leg       # the real read-only guard let every call through
        assert (f1[leg + "_agent_setting"], f1[leg + "_bash_tool"], f1[leg + "_model"], f1[leg + "_valid"]) == (
            "verifier", True, FAKE_SONNET, True), leg
    assert f1["repo_rule_trust_warning"] is True and f1["trusted_repo_rule_trust_warning"] is False
    assert f1["repo_rule_verdict"] == "denied" and f1["trusted_repo_rule_verdict"] == "ran"
    assert f1["trusted_control_verdict"] == "denied" and f1["plan_auto_verdict"] == "denied"
    assert f1["plan_auto_effect"] == "denied" and f1["installed_default_mode"] is None
    assert (f1["control_settings_auto_mode_during_plan"], f1["control_settings_sandbox_auto_allow"]) == (False, False)
    assert (f1["as_installed_settings_auto_mode_during_plan"], f1["as_installed_settings_sandbox_auto_allow"]) == (
        None, None)                                             # main's Session sends no settings of its own
    assert (f1["plan_auto_settings_auto_mode_during_plan"], f1["plan_auto_settings_sandbox_auto_allow"]) == (
        True, False)
    models = {r.probe.pid: r.models for r in rows}
    assert models == {"E1": [FAKE_SONNET] * 7, "E2": ["fake-haiku"] * 3, "E3": ["fake-haiku"] * 2,
                      "E3P": ["fake-haiku"]}                    # E2c connects only: no init frame
    fp = next(r.facts for r in rows if r.probe.pid == "E3P")
    assert fp["e3p_meta_tool_use_id"] == fp["e3p_spawn_tool_use_id"] and fp["e3p_meta_tid_is_spawn"] is True
    assert fp["e3p_resumed"] is True and fp["e3p_resume_refused"] is False and fp["e3e_children"] == 1
    assert fp["e3e_meta_at_first_call"] == [True] and fp["e3e_tid_at_first_call"] == [True]


def test_the_report_and_ledger_of_a_full_run_have_no_prompt_text(sdk, tmp_path):
    w = World(tmp_path)
    events = []
    rows = run(w, ledger=events.append)
    text = P.render(rows, dict(P.base.versions(None), date="2026-10-09"))
    assert_no_prompt_text(text)
    assert_no_prompt_text(json.dumps([P.clean(e) for e in events]))
    assert P.base.WITHHELD not in text           # no probe records free text, even though the fake offers it
    assert "other stderr text" not in text and "workspace has not been trusted. " not in text
    for pid in PARTS:
        assert "| %s |" % pid in text
    assert str(w.config / "projects") in text and "Consent envelope" in text
    assert "main-thread models (each session's init frame): E1 %s x7; E2 fake-haiku x3; E3 fake-haiku x2; " \
           "E3P fake-haiku x1" % FAKE_SONNET in text
    kinds = [e["ev"] for e in events]
    assert kinds.count("probe") == 4 and kinds.count("probe_end") == 4 and kinds.count("reserve") == 18
    assert kinds.count("cost") >= 13 and "cost_unknown" not in kinds


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


def test_a_hook_decision_or_an_unloaded_stack_leaves_e1_unknown(sdk, tmp_path, monkeypatch):
    (row,) = run(World(tmp_path, guard_decides=True), [P.PROBES[0]])
    assert {k: v for k, v in row.answers.items()} == dict.fromkeys(E1_PARTS, "unknown")
    assert row.facts["session_rule_verdict"] == "hook_decided" and row.facts["session_rule_hook_decisions"] == {"deny": 1}
    w = World(tmp_path / "nomarker", marker=False)
    (row,) = run(w, [P.PROBES[0]], ledger=None)
    assert row.status == "ran" and set(row.answers.values()) == {"unknown"}
    assert row.facts["stack_not_loaded"] == "guard_marker" and len(w.opened) == 1            # one leg, then stop
    assert row.facts["stack_not_loaded_leg"] == "control"
    assert row.cost == pytest.approx(0.08) and row.facts["sessions_without_result"] == 1      # booked at its cap
    (row,) = run(World(tmp_path / "norule", stack_rule=False), [P.PROBES[0]])
    assert row.answers["E1c"] == "unknown" and row.facts["stack_rule_installed"] is False
    assert row.answers["E1a"] == "yes"
    # E1c's leg run anyway (E1C_NOT_RUN off) in a world whose guard would not decide it (ro_guard off): it reads
    # from permission_denials, calibrated by the control's denial there
    monkeypatch.setattr(P, "E1C_NOT_RUN", None)
    (row,) = run(World(tmp_path / "e1c", ro_guard=False), [P.PROBES[0]])
    assert row.answers["E1c"] == "yes" and row.facts["stack_rule_verdict"] == "ran", row.facts
    # ... and the real read-only guard decides it: hook_decided, unknown
    (row,) = run(World(tmp_path / "e1c-guard"), [P.PROBES[0]])
    assert row.answers["E1c"] == "unknown" and row.facts["stack_rule_verdict"] == "hook_decided"
    assert row.answers["E1a"] == "yes"
    # the control's denial missing from permission_denials: E1c has no calibrated observable; the markers still do
    (row,) = run(World(tmp_path / "unlisted", rules_bind=False, denials_listed=False, trust_gate=False,
                       ro_guard=False), [P.PROBES[0]])
    assert row.answers == {"E1a": "no", "E1bu": "no", "E1bt": "no", "E1c": "unknown", "E1d": "no"}, row.facts
    assert row.facts["control_verdict"] == "denied" and row.facts["denials_calibrated"] is False
    assert row.facts["stack_rule_verdict"] == "ran"          # what an uncalibrated read would take for yes


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
    assert [r.status for r in rows] == ["refused", "skipped", "skipped", "skipped"]
    assert len(w.opened) == 1 and rows[0].cost == pytest.approx(0.08)
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
    e1, e2, e3, _ = P.PROBES

    async def spend(c, usd):
        c.costs[99] = usd
    rows = run(w, [dataclasses.replace(e1, fn=lambda c: spend(c, 1.45)), e2, e3])
    assert [r.status for r in rows] == ["ran", "cap_used", "ran"]
    assert rows[1].cap == pytest.approx(0.05)                   # what E1+E2 has left, not E2's 0.60
    assert rows[2].cap == pytest.approx(0.40)                   # E3's own envelope is untouched
    e2_opts = [o for o in w.opened if probe_of(o) == "E2"]
    assert [o.max_budget_usd for o in e2_opts] == [0.05]       # E2c only; E2a would need more than is left
    assert rows[1].answers == {"E2a": "skipped", "E2b": "skipped", "E2c1": "no", "E2c2": "no"}
    assert answers(rows[2:]) == {k: v for k, v in GOOD.items() if k in [x.pid for x in e3.parts]}
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


# ---------------------------------------------------------------- review fixes (SDK probes E, round 1)
def test_an_open_turn_counts_at_the_whole_cap(sdk, tmp_path):
    """F1: another prompt on a session that already reported may spend up to the session's cap again: it is
    booked at that cap until the turn's result reports, and never below what was reported before."""
    events = []
    ctx = P.Ctx(P.PROBES[2], World(tmp_path).cfg(), helper(), 0.40, events.append)
    ctx.reserve(0, types.SimpleNamespace(max_budget_usd=0.20))
    ctx.note(0, FakeResult(0.01))
    assert ctx.spent == pytest.approx(0.01)
    ctx.open_turn(0)
    assert ctx.spent == pytest.approx(0.20) and ctx.budget() <= 0.20 and ctx.unreported == 1
    assert events[-1]["ev"] == "reserve" and events[-1]["usd"] == 0.20
    ctx.note(0, FakeResult(0.05))                    # the turn's result: the running total of the process
    assert ctx.spent == pytest.approx(0.05) and ctx.unreported == 0
    ctx.open_turn(0)
    ctx.note(0, FakeResult(0.03))                    # a lower figure never undercuts what was reported
    assert ctx.spent == pytest.approx(0.05)


def test_e1_rule_legs_need_a_denied_control(sdk, tmp_path):
    """F2: if plan runs the command without any rule, a rule leg that ran proves nothing about the rule."""
    (row,) = run(World(tmp_path, plan_open=True), [P.PROBES[0]])
    assert row.facts["control_verdict"] == "ran" and row.facts["session_rule_verdict"] == "ran"
    assert row.facts["trusted_control_verdict"] == "ran"
    assert [row.answers[k] for k in E1_PARTS] == ["uncontrolled", "uncontrolled", "uncontrolled", "unknown", "yes"]
    # a control neither denied nor ran (undecided, hook-decided): the rule leg's reading is unknown
    for control in ("undecided", "hook_decided", "not_attempted"):
        c = types.SimpleNamespace(facts={}, answers={})
        P.e1_answers(c, {"control": control, "session_rule": "ran", "repo_rule": "denied"})
        assert c.answers == {"E1a": "unknown", "E1bu": "unknown"}, control


def test_e2a_needs_a_control_the_rules_do_not_touch(sdk, tmp_path):
    """F4: the env rules acting on the control too (kind unset): no rule's effect is measured."""
    (row,) = run(World(tmp_path, bg_any_kind=True), [P.PROBES[1]])
    assert row.answers["E2a"] == "unknown", row.facts
    assert (row.facts["e2a_allow_applied"], row.facts["e2a_deny_applied"], row.facts["e2a_add_dirs_applied"]) == (
        None, None, None)
    assert row.facts["e2a_control_allow_marker"] and not row.facts["e2a_control_deny_marker"]
    assert not row.facts["e2a_control_read_failed"]


def test_e3c2_needs_a_tool_use_id(sdk, tmp_path):
    """F5: a meta.json without toolUseId before and after the resume is no evidence that it survived."""
    (row,) = run(World(tmp_path, meta_tid_match=None), [P.PROBES[2]])
    assert row.facts["e3c_resumed"] is True and row.facts["e3c_meta_tool_use_id"] is None
    assert row.answers["E3c1"] == "no" and row.answers["E3c2"] == "unknown"
    e3c2 = next(x for x in P.PROBES[2].parts if x.pid == "E3c2")
    assert e3c2.reading.endswith("unknown: no resume proven, E3c1 unknown, or no toolUseId before the resume")


# ---------------------------------------------------------------- review fixes (SDK probes E, round 2)
def test_a_late_result_does_not_close_the_resume_turn(sdk, tmp_path):
    """Round 2, 1: the wake's result lands only after the resume query, whose own turn never ends. Only a
    result after the resume's SendMessage call closes that turn's spend; here none does, so the hold session
    stays at its whole cap (and the ledger says so)."""
    events = []
    (row,) = run(World(tmp_path, late_wake=True, resume=False), [P.PROBES[2]], ledger=events.append)
    f = row.facts
    hold_cap = 0.40 - 0.01                          # the fork session reported $0.01 first
    assert row.cost == pytest.approx(0.01 + hold_cap), row.cost
    assert f["e3d_result_after_stop"] is False and f["e3d_resume_turn_ended"] is False, f
    assert [e.get("unproven") for e in events if e["ev"] == "reserve"].count(True) == 2
    assert row.answers["E3d"] == "unknown"


def test_a_session_closed_with_an_agent_running_is_rebooked_in_the_ledger(sdk, tmp_path):
    """Round 2, 3: settle() books a session closed with an agent still running at its whole cap: the ledger
    records that booking too."""
    events = []
    ctx = P.Ctx(P.PROBES[2], World(tmp_path).cfg(), helper(), 0.40, events.append)
    opts = types.SimpleNamespace(max_budget_usd=0.20)
    ctx.reserve(0, opts)
    ctx.note(0, FakeResult(0.01))
    running = type("TaskStartedMessage", (), dict(task_id="t1", tool_use_id="tu-1", description="coder: x",
                                                 task_type="local_agent", session_id="sess-fake-result"))()
    ctx.settle(0, [running], opts)
    assert ctx.spent == pytest.approx(0.20)
    assert events[-1] == dict(ev="reserve", probe="E3", session=0, usd=0.20, closed=True)
    n = len(events)
    ctx.settle(1, [], types.SimpleNamespace(max_budget_usd=0.1))          # nothing changes: no event
    assert len(events) == n


# ---------------------------------------------------------------- the second probe set (E1', E3', E3d's reading)
def test_a_blackcat_main_thread_makes_every_e1_leg_invalid(sdk, tmp_path):
    """The first runs' failure: Session(None) ran settings.json's agent, blackcat (no Bash, model sonnet), and
    no leg measured anything. Such legs are invalid now, not unknown."""
    (row,) = run(World(tmp_path, agent_flag=False), [P.PROBES[0]])
    assert row.answers == dict.fromkeys(E1_PARTS, "invalid"), row.facts
    assert row.facts["control_agent_setting"] == "blackcat" and row.facts["control_bash_tool"] is False
    assert row.facts["control_attempted"] is False and row.facts["control_verdict"] == "invalid"
    assert row.models == [FAKE_SONNET] * 7


@pytest.mark.parametrize("switch", [dict(agent_setting_row=False), dict(init_model=False), dict(main_tools="Read")])
def test_a_leg_without_the_verifier_bash_or_a_model_is_invalid(sdk, tmp_path, switch):
    (row,) = run(World(tmp_path, **switch), [P.PROBES[0]])
    assert row.answers == dict.fromkeys(E1_PARTS, "invalid"), row.facts
    assert row.facts["control_valid"] is False and row.facts["control_verdict"] == "invalid"


def test_an_invalid_control_makes_its_rule_legs_invalid(sdk, tmp_path):
    """Only the control's transcript lacks the agent setting: the legs read against it are invalid; the trusted
    pair (its own control) and the as-installed leg still answer."""
    (row,) = run(World(tmp_path, invalid_legs=("control",)), [P.PROBES[0]])
    assert row.answers == {"E1a": "invalid", "E1bu": "invalid", "E1bt": "yes", "E1c": "invalid", "E1d": "no"}, row.facts
    assert row.facts["session_rule_valid"] is True and row.facts["control_valid"] is False


def test_e1b_reads_the_trust_warning_and_the_trusted_leg_reads_its_own_control(sdk, tmp_path):
    (row,) = run(World(tmp_path), [P.PROBES[0]])
    assert (row.answers["E1bu"], row.answers["E1bt"]) == ("dropped (untrusted)", "yes"), row.facts
    # the warning absent from stderr: a denied untrusted repo rule reads plain no
    (row,) = run(World(tmp_path / "quiet", trust_warning=False), [P.PROBES[0]])
    assert (row.answers["E1bu"], row.answers["E1bt"]) == ("no", "yes") and row.facts["repo_rule_trust_warning"] is False
    # the env does not trust (2026-10-10): the warning on the trusted leg's stderr: trust unproven, and its
    # control is not run ($0)
    w = World(tmp_path / "untrusting", sandboxed_trusts=False)
    (row,) = run(w, [P.PROBES[0]])
    assert row.answers["E1bt"] == "trust unproven" and row.facts["trusted_repo_rule_trust_warning"] is True
    assert row.facts["trusted_control_verdict"] == "trust_unproven" and "trusted_control_attempted" not in row.facts
    assert "trusted_control" not in [Path(o.cwd).name for o in w.opened] and len(w.opened) == 6
    # the env runs Bash with no rule: the trusted control ran, E1bt is uncontrolled; the untrusted legs still read
    (row,) = run(World(tmp_path / "opens", sandboxed_opens=True), [P.PROBES[0]])
    assert row.facts["trusted_control_verdict"] == "ran" and row.answers["E1bt"] == "uncontrolled"
    assert row.answers["E1bu"] == "dropped (untrusted)" and row.answers["E1a"] == "yes"
    # no trust gate: the untrusted repo rule binds
    (row,) = run(World(tmp_path / "nogate", trust_gate=False), [P.PROBES[0]])
    assert row.answers["E1bu"] == "yes"


def test_a_helper_that_refuses_the_trust_env_skips_only_the_trusted_legs(sdk, tmp_path):
    """A stack_sdk.Session that refuses CLAUDE_CODE_SANDBOXED (the planned env-channel fix) starts nothing for
    the trusted legs: helper_refused, E1bt unknown, nothing booked for them."""
    w, h = World(tmp_path), helper()

    class Refusing(h.Session):
        def __init__(self, *a, **kw):
            if "CLAUDE_CODE_SANDBOXED" in (kw.get("env") or {}):
                raise ValueError("refused: env")
            super().__init__(*a, **kw)
    h.Session = Refusing
    from unittest import mock
    with mock.patch.dict(os.environ, {"CLAUDE_CONFIG_DIR": str(w.config)}):
        (row,) = asyncio.run(P.run_probes([P.PROBES[0]], w.cfg(), h))
    assert row.facts["trusted_control_verdict"] == row.facts["trusted_repo_rule_verdict"] == "helper_refused"
    assert row.answers["E1bt"] == "unknown" and row.answers["E1a"] == "yes" and len(w.opened) == 5
    assert row.cost == pytest.approx(0.05)


def test_e1_cut_by_its_cap_keeps_what_it_measured(sdk, tmp_path):
    """Sessions at $0.078: five legs use $0.39 of the $0.40, the sixth cannot start (cap_used); the five still
    answer (E1c: not run)."""
    w = World(tmp_path, cost=0.078)
    (row,) = run(w, [P.PROBES[0]])
    assert row.status == "cap_used" and len(w.opened) == 5
    assert row.answers == {"E1a": "yes", "E1bu": "dropped (untrusted)", "E1bt": "yes", "E1c": "unknown", "E1d": "skipped"}
    assert row.facts["reserve_skipped"] == ["as_installed", "plan_auto"]


def test_a_refused_resume_reads_terminal_for_e3d(sdk, tmp_path):
    """CLI 2.1.287: SendMessage to a stopped child returns success false, "was stopped by the user and was not
    resumed", and nothing resumes: the stop is final (E3d terminal), no paid run needed to read it so."""
    (row,) = run(World(tmp_path, refuse_stopped=True), [P.PROBES[2]])
    f = row.facts
    assert row.answers["E3d"] == "terminal", f
    assert f["e3d_resume_refused"] is True and f["e3d_resumed"] is False and f["e3d_meta_after_stopped_by_user"] is True
    assert row.answers["E3c2"] == "yes"                     # the fork child was never stopped: it resumes
    (row,) = run(World(tmp_path / "ok"), [P.PROBES[2]])
    assert row.answers["E3d"] == "yes" and row.facts["e3d_resume_refused"] is False


def test_e3d_reading_and_the_refusal_detector(sdk):
    assert P.e3d_reading(True, False, True, True) == "terminal"
    assert P.e3d_reading(True, True, False, True) == "yes" and P.e3d_reading(True, True, None, False) == "no"
    assert P.e3d_reading(False, False, True, True) == "unknown"            # never stopped
    assert P.e3d_reading(True, True, True, True) == "unknown"              # refused, yet the transcript grew
    assert P.e3d_reading(True, False, False, True) == P.e3d_reading(True, False, None, True) == "unknown"
    def msgs(content, tur=None, tid="tu-s", name="SendMessage"):
        return [sdk.AssistantMessage([sdk.ToolUseBlock("tu-s", name, {"to": "a1"})], "m"),
                sdk.UserMessage([sdk.ToolResultBlock(tid, content, False)], tool_use_result=tur)]
    why = "Agent a1 " + P.RESUME_REFUSED
    assert P.resume_refused(msgs(json.dumps({"success": False, "message": why}))) is True
    assert P.resume_refused(msgs([{"type": "text", "text": why}])) is True
    assert P.resume_refused(msgs("x", {"success": False, "message": why})) is True
    assert P.resume_refused(msgs(why, {"success": True})) is False          # the record says it resumed
    assert P.resume_refused(msgs("resumed")) is False
    assert P.resume_refused(msgs(why, tid="tu-other")) is None              # no result for the call
    assert P.resume_refused(msgs(why, name="Agent")) is None                # not a SendMessage call
    assert P.resume_refused([]) is None


def test_e3p_answers_from_an_agent_childs_resume_and_its_first_tool_call(sdk, tmp_path):
    e3p = P.PROBES[3]
    (row,) = run(World(tmp_path), [e3p])
    assert (row.answers["E3c2a"], row.answers["E3e"]) == ("yes", "yes") and row.cost == pytest.approx(0.01)
    # meta.json written after the child's first tool call: its first row says so, its later (resume) row not
    (row,) = run(World(tmp_path / "late", meta_early=False), [e3p])
    assert row.answers["E3e"] == "no" and row.facts["e3e_meta_at_first_call"] == [False], row.facts
    assert row.facts["e3p_hook_rows"] >= 3                      # the main thread's and the child's two
    (row,) = run(World(tmp_path / "lost", tid_survives=False), [e3p])
    assert row.answers["E3c2a"] == "no" and row.facts["e3p_meta_after_tool_use_id"] is None
    (row,) = run(World(tmp_path / "refused", refuse_any=True), [e3p])
    assert row.answers["E3c2a"] == "unknown" and row.facts["e3p_resume_refused"] is True
    assert row.facts["e3p_resumed"] is False
    (row,) = run(World(tmp_path / "notid", agent_meta_tid=None), [e3p])
    assert row.answers["E3c2a"] == "unknown" and row.facts["e3p_meta_tool_use_id"] is None
    assert row.facts["e3e_tid_at_first_call"] == [False]
    (row,) = run(World(tmp_path / "nopath", hook_paths=False), [e3p])
    assert row.answers["E3e"] == "unknown" and row.facts["e3e_meta_at_first_call"] == [None]
    (row,) = run(World(tmp_path / "noresume", resume=False), [e3p])
    assert row.answers["E3c2a"] == "unknown" and row.facts["e3p_resumed"] is False


# ---------------------------------------------------------------- review fixes (sdk/probes-e2, round 1)
def test_e1s_command_passes_the_guards_read_only_rule_for_the_verifier(tmp_path, monkeypatch):
    """Hooks see agent_type on an --agent main thread, the verifier is a READONLY_TYPES agent, and a temp project
    is the project (R3-INFO): only its ./.claude-work is scratch. E1's script and marker live there, so the guard
    lets `sh <cwd>/.claude-work/e1.sh` through; the first layout (`sh <cwd>/e1.sh`) and the stack's `just` rule
    are refused (hook_decided), which is why E1c's leg is not run (E1C_NOT_RUN)."""
    g = guard()
    assert P.E1_AGENT in g.READONLY_TYPES
    cwd = tmp_path / "e1" / "control"
    cwd.mkdir(parents=True)
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(cwd))
    ev = {"cwd": str(cwd), "agent_type": P.E1_AGENT}
    command, marker = P.e1_command(str(cwd), "control")
    assert g.readonly_violation(command, ev) is None
    assert command == "sh %s/.claude-work/e1.sh" % cwd and marker == "%s/.claude-work/e1-control.marker" % cwd
    assert (cwd / ".claude-work" / "e1.sh").read_text() == "touch %s\n" % marker
    (cwd / "e1.sh").write_text("touch %s\n" % marker)
    assert g.readonly_violation("sh %s/e1.sh" % cwd, ev) is not None
    assert g.readonly_violation(P.STACK_RULE_CMD, ev) is not None and P.E1C_NOT_RUN


def test_a_bash_call_cut_before_its_tool_result_is_not_a_denial(sdk, tmp_path):
    """A call in the stream with neither a tool result nor a denial (the session ended first: its deadline, the
    CLI's exit, its budget stop) was never decided: "undecided", not "denied", so it cannot calibrate the rule
    legs as a denied control would."""
    cmd = "sh %s/.claude-work/e1.sh" % tmp_path
    use = sdk.AssistantMessage(content=[sdk.ToolUseBlock(id="tu1", name="Bash", input={"command": cmd})], model="m")
    marker = str(tmp_path / "m.marker")
    leg = P.bash_leg(None, [use], [], cmd, marker, {"valid": True})
    assert leg["decided"] is False and P.bash_verdict(leg) == "undecided"
    assert P.bash_verdict(P.bash_leg(None, [use], [], cmd, None, {"valid": True})) == "undecided"   # no marker
    result = sdk.UserMessage(content=[sdk.ToolResultBlock(tool_use_id="tu1", content="x", is_error=True)])
    assert P.bash_verdict(P.bash_leg(None, [use, result], [], cmd, marker, {"valid": True})) == "denied"
    denial = [{"tool_name": "Bash", "tool_use_id": "tu1"}]
    assert P.bash_verdict(P.bash_leg(None, [use], denial, cmd, None, {"valid": True})) == "denied"
    Path(marker).touch()
    assert P.bash_verdict(P.bash_leg(None, [use], [], cmd, marker, {"valid": True})) == "ran"
    c = types.SimpleNamespace(facts={"control_denied": False}, answers={})
    P.e1_answers(c, {"control": "undecided", "session_rule": "ran", "as_installed": "undecided"})
    assert c.answers == {"E1a": "unknown", "E1d": "unknown"}
    for reading in (P.READ_RULE, P.READ_INSTALLED):
        assert "the call was never decided (no tool result)" in reading


def test_a_run_in_progress_counts_at_its_cap(tmp_path):
    """A ledger without its "end" (a run still going, or killed) counts at its envelope's run_cap_usd, not at what
    it booked so far; its end replaces that. The first runs' envelopes (run_cap_usd null, all ended) still
    replay to the analysis figure."""
    p = tmp_path / "a.ledger.jsonl"
    p.write_text(json.dumps({"ev": "envelope", "run_cap_usd": 0.50}) + "\n"
                 + json.dumps({"ev": "reserve", "probe": "E1", "session": 0, "usd": 0.08}) + "\n")
    assert P.ledger_spend(str(p))["used"] == 0.50
    p.write_text(p.read_text() + json.dumps({"ev": "end", "usd": 0.06}) + "\n")
    assert P.ledger_spend(str(p))["used"] == 0.08
    assert P.prior_spend([str(LEDGERS)])["used"] == PRIOR_USED


def test_a_second_run_started_while_one_runs_counts_it_at_its_cap(pinned, monkeypatch, tmp_path, capsys):
    """The review's scenario: E1+E3P (0.50) has booked only its first session when E3P (0.10) starts; the first
    run counts at its whole cap, so 1.4041 + 0.50 + 0.10 > 2.00 refuses the second."""
    seed(pinned)
    second = []

    async def noop(*a, **k):
        pass

    def start_second():                     # its own thread: its asyncio.run needs no running loop
        monkeypatch.setattr(P, "run_probes", noop)
        monkeypatch.setenv(P.CONSENT_ENV, "0.10")
        try:
            P.main(["--paid", "--cli", "/x", "--only", "E3P", "--out", str(tmp_path / "b.md")])
            second.append("started")
        except SystemExit as e:
            second.append(e.code)

    async def first(probes, cfg, helper, rows, ledger, total=None):
        ledger({"ev": "reserve", "probe": "E1", "session": 0, "usd": 0.08})
        await asyncio.to_thread(start_second)
    monkeypatch.setattr(P, "run_probes", first)
    monkeypatch.setenv(P.CONSENT_ENV, "0.50")
    P.main(["--paid", "--cli", "/x", "--only", "E1,E3P", "--out", str(tmp_path / "a.md")])
    assert second == [2] and "refused: the prior spend USD 1.9041 plus this run's cap USD 0.10" in \
        capsys.readouterr().err
    assert not (pinned / "b.ledger.jsonl").exists()


def test_two_starts_are_serialised_by_the_lock(pinned, monkeypatch, tmp_path):
    """The gate, the ledger's creation and its envelope run under an exclusive flock on <default dir>/LOCK_NAME:
    a start waits while another holds it, so two cannot pass the check on the same prior spend."""
    import fcntl
    import threading

    async def record(*a, **k):
        pass
    monkeypatch.setattr(P, "run_probes", record)
    monkeypatch.setenv(P.CONSENT_ENV, "0.10")
    pinned.mkdir(parents=True, exist_ok=True)
    t = threading.Thread(target=P.main, args=(["--paid", "--cli", "/x", "--only", "E3P", "--out",
                                                str(tmp_path / "r.md")],))
    with open(pinned / P.LOCK_NAME, "a") as held:
        fcntl.flock(held.fileno(), fcntl.LOCK_EX)
        t.start()
        t.join(1.0)
        assert t.is_alive() and not list(pinned.glob(P.LEDGER_GLOB))     # waiting: no gate passed, no ledger
    t.join(30)
    assert not t.is_alive() and [p.name for p in pinned.glob(P.LEDGER_GLOB)] == ["r.ledger.jsonl"]


def test_the_ledger_goes_to_the_default_directory_whatever_out_says(pinned, monkeypatch, tmp_path, capsys):
    """--out elsewhere puts the report there, the ledger in the default directory: a later run without --out
    (which reads only the default directory and its own) still counts it."""
    async def record(*a, **k):
        pass
    monkeypatch.setattr(P, "run_probes", record)
    monkeypatch.setenv(P.CONSENT_ENV, "0.10")
    out = tmp_path / "elsewhere" / "r.md"
    P.main(["--paid", "--cli", "/x", "--only", "E3P", "--out", str(out)])
    assert out.exists() and not list(out.parent.glob(P.LEDGER_GLOB))
    assert [p.name for p in pinned.glob(P.LEDGER_GLOB)] == ["r.ledger.jsonl"]
    capsys.readouterr()
    assert P.main(["--only", "E3P"]) == 0
    assert "prior spend: 1 ledgers" in capsys.readouterr().out


def test_e3c2a_needs_a_sendmessage_call(sdk, tmp_path):
    """A child transcript that grows without a successful SendMessage call in the resume turn (none, or one
    denied with an is_error result) proves no resume."""
    (row,) = run(World(tmp_path, silent_send=True), [P.PROBES[3]])
    f = row.facts
    assert f["e3p_child_lines_after"] > f["e3p_child_lines_before"] and f["e3p_resume_send_calls"] == 0, f
    assert f["e3p_resumed"] is False and row.answers["E3c2a"] == "unknown"
    # a SendMessage call that was denied (an is_error result) resumes nothing either
    (row,) = run(World(tmp_path / "denied", send_denied=True), [P.PROBES[3]])
    f = row.facts
    assert f["e3p_child_lines_after"] > f["e3p_child_lines_before"] and f["e3p_send_calls"] == 1, f
    assert f["e3p_resume_send_calls"] == 0 and f["e3p_resumed"] is False and row.answers["E3c2a"] == "unknown"


def test_a_helper_whose_preview_refuses_the_trust_env_skips_only_the_trusted_legs(sdk, tmp_path):
    """The planned env-channel helper may refuse CLAUDE_CODE_SANDBOXED when it builds the options (preview), not
    in __init__: the same helper_refused at $0 for the trusted legs, and the later legs still run."""
    w, h = World(tmp_path), helper()

    class Refusing(h.Session):
        def preview(self):
            if "CLAUDE_CODE_SANDBOXED" in self.env:
                raise ValueError("refused: env")
            return super().preview()
    h.Session = Refusing
    from unittest import mock
    with mock.patch.dict(os.environ, {"CLAUDE_CONFIG_DIR": str(w.config)}):
        (row,) = asyncio.run(P.run_probes([P.PROBES[0]], w.cfg(), h))
    assert row.status == "ran", row.facts
    assert row.facts["trusted_control_verdict"] == row.facts["trusted_repo_rule_verdict"] == "helper_refused"
    assert row.answers["E1bt"] == "unknown" and row.answers["E1a"] == "yes" and row.answers["E1d"] == "no"
    assert len(w.opened) == 5 and row.cost == pytest.approx(0.05)


# ---------------------------------------------------------------- the E1 rerun (sdk/probes-e3): envelope e3-2026-10-10
LEDGER_1010 = ROOT / "tests" / "fixtures" / "sdk" / "probes_e_ledgers_2026-10-10" / "2026-10-10-e.ledger.jsonl"
OLD_USED = 1.918793                         # the four runs' ledgers at worst: $1.9188 of the $2.00, $0.0812 left


def seed_all(d):
    """The four runs' ledgers before the e3 envelope: 2026-10-09 (three) and 2026-10-10 (E1+E3P, $0.5147)."""
    seed(d)
    (d / LEDGER_1010.name).write_text(LEDGER_1010.read_text())


def e3_ledger(d, name, *events):
    """A ledger of the e3 envelope: its envelope event, then `events`."""
    head = {"ev": "envelope", "envelope": P.E3_ENVELOPE, "run_cap_usd": 0.38, "total_usd": 0.45}
    (d / name).write_text("".join(json.dumps(e) + "\n" for e in (head, *events)))


def test_envelopes_count_only_their_own_ledgers(tmp_path):
    """The first envelope counts the four runs' ledgers ($1.9188, untouched by the new one); e3-2026-10-10 counts
    none of them ($0.45 left); an e3 ledger counts only in e3; a ledger with no envelope event counts in both
    (fail closed); an unknown envelope id, a null one or two envelope events cannot be replayed."""
    d = tmp_path / "l"
    seed_all(d)
    assert P.ledger_spend(str(LEDGER_1010))["envelope"] == P.LEGACY_ENVELOPE        # no id: the first envelope
    old, new = P.prior_spend([str(d)]), P.prior_spend([str(d)], P.E3_ENVELOPE)
    assert (old["envelope"], old["ledgers"], old["other_ledgers"], old["used"]) == (P.LEGACY_ENVELOPE, 4, 0, OLD_USED)
    assert round(old["left"], 4) == 0.0812 and old["total"] == 2.0
    assert new == {"envelope": P.E3_ENVELOPE, "total": 0.45, "ledgers": 0, "other_ledgers": 4, "reported": 0,
                   "unreported": 0, "used": 0, "left": 0.45}
    e3_ledger(d, "e3a.ledger.jsonl", {"ev": "reserve", "probe": "E1", "session": 0, "usd": 0.08},
              {"ev": "cost", "probe": "E1", "session": 0, "usd": 0.07}, {"ev": "end", "usd": 0.07})
    new = P.prior_spend([str(d)], P.E3_ENVELOPE)
    assert (new["ledgers"], new["other_ledgers"], new["used"], new["left"]) == (1, 4, 0.07, 0.38)
    assert P.prior_spend([str(d)])["used"] == OLD_USED                             # the first envelope: untouched
    e3_ledger(d, "e3b.ledger.jsonl", {"ev": "reserve", "probe": "E1", "session": 0, "usd": 0.08})
    assert P.prior_spend([str(d)], P.E3_ENVELOPE)["used"] == pytest.approx(0.07 + 0.38)  # no end: at its run cap
    (d / "e3b.ledger.jsonl").unlink()
    (d / "bare.ledger.jsonl").write_text(json.dumps({"ev": "reserve", "probe": "E1", "session": 0, "usd": 0.05}) + "\n")
    assert P.prior_spend([str(d)])["used"] == pytest.approx(OLD_USED + 0.05)       # whose it is is unknown: both
    assert P.prior_spend([str(d)], P.E3_ENVELOPE)["used"] == pytest.approx(0.12)
    (d / "bare.ledger.jsonl").unlink()
    env = {"ev": "envelope", "run_cap_usd": 0.1}
    for bad in ([dict(env, envelope="e9-2026-10-11")], [dict(env, envelope=None)], [dict(env, envelope=["x"])],
                [env, dict(env, envelope=P.E3_ENVELOPE)], [dict(env, envelope=P.E3_ENVELOPE), env]):
        (d / "bad.ledger.jsonl").write_text("".join(json.dumps(e) + "\n" for e in bad))
        for eid in (None, P.E3_ENVELOPE):                       # it refuses a run in either envelope
            with pytest.raises(P.LedgerUnreadable):
                P.prior_spend([str(d)], eid)


def test_the_e3_envelope_is_e1_only_and_its_consent_is_its_cap_less_one_turn(pinned, monkeypatch, tmp_path, capsys):
    """--envelope e3-2026-10-10: E1 only (the default selection, and nothing else admitted); its run cap is
    min(E1's 0.40, floor((0.45 - E1_TURN_USD) * 100) / 100) = 0.38, which SDK_PROBES_E_CONSENT must equal; the
    first envelope's rules are unchanged without the flag."""
    env = P.ENVELOPES[P.E3_ENVELOPE]
    assert (env.total_usd, env.consent_date, env.probes, env.overshoot_usd) == (0.45, "2026-10-10", {"E1"}, 0.065)
    assert env.max_run_usd == 0.38 and P.E1_TURN_USD == 0.065 and P.E1_TURN_USD >= 0.0611
    assert P.consent_value(P.PROBES[:1], P.E3_ENVELOPE) == "0.38" and P.run_cap(P.PROBES[:1], P.E3_ENVELOPE) == 0.38
    assert env.max_run_usd + env.overshoot_usd <= env.total_usd                    # the one-turn margin fits
    assert P.consent_value(P.PROBES[:1]) == "0.40" and P.ENVELOPES[P.LEGACY_ENVELOPE].max_run_usd == 2.0
    seen = []

    async def record(probes, cfg, helper, rows, ledger, total=None):
        seen.append(([p.pid for p in probes], total))
    monkeypatch.setattr(P, "run_probes", record)
    for value in ("0.40", "0.45", "0.38 ", "2.00", None):
        if value is None:
            monkeypatch.delenv(P.CONSENT_ENV, raising=False)
        else:
            monkeypatch.setenv(P.CONSENT_ENV, value)
        with pytest.raises(SystemExit) as e:
            P.main(["--paid", "--envelope", P.E3_ENVELOPE, "--cli", "/x", "--out", str(tmp_path / "r.md")])
        assert e.value.code == 2 and seen == [] and "%s=0.38" % P.CONSENT_ENV in capsys.readouterr().err
    monkeypatch.setenv(P.CONSENT_ENV, "0.38")
    for only in ("E1,E3P", "E3P", "E2"):                        # the envelope admits E1 only
        with pytest.raises(SystemExit) as e:
            P.main(["--paid", "--envelope", P.E3_ENVELOPE, "--only", only, "--cli", "/x", "--out",
                    str(tmp_path / "r.md")])
        assert e.value.code == 2 and seen == [] and "admits only E1" in capsys.readouterr().err
    with pytest.raises(SystemExit):
        P.main(["--envelope", "e9-2026-10-11"])
    with pytest.raises(SystemExit):                             # the first envelope is the default, not a choice
        P.main(["--envelope", P.LEGACY_ENVELOPE])
    capsys.readouterr()
    P.main(["--paid", "--envelope", P.E3_ENVELOPE, "--cli", "/x", "--out", str(tmp_path / "r.md")])
    assert seen == [(["E1"], 0.38)]
    head = json.loads((pinned / "r.ledger.jsonl").read_text().splitlines()[0])
    assert (head["envelope"], head["consent_date"], head["total_usd"], head["run_cap_usd"], head["consent_value"]) == (
        P.E3_ENVELOPE, "2026-10-10", 0.45, 0.38, "0.38")
    assert "Consent envelope %s: the user's decision of 2026-10-10" % P.E3_ENVELOPE in (tmp_path / "r.md").read_text()


def test_the_e3_gate_counts_its_own_runs_and_leaves_the_first_envelope_untouched(pinned, monkeypatch, tmp_path,
                                                                                capsys):
    """The four runs' ledgers in the default directory: the first envelope has $0.0812 left (E3P's 0.10 is
    refused there), the e3 envelope all of its $0.45: E1 at 0.38 starts. That run books $0.10; a second e3 run
    (0.10 + 0.38 > 0.45) is refused, and the first envelope still reads $1.9188."""
    seed_all(pinned)
    seen = []

    async def spend(probes, cfg, helper, rows, ledger, total=None):
        seen.append(total)
        ledger({"ev": "reserve", "probe": "E1", "session": 0, "usd": 0.08})
        ledger({"ev": "cost", "probe": "E1", "session": 0, "usd": 0.10})
        rows.append(P.Row(probes[0], {"E1a": "yes"}, total, cost=0.10))
    monkeypatch.setattr(P, "run_probes", spend)
    monkeypatch.setenv(P.CONSENT_ENV, "0.10")
    with pytest.raises(SystemExit) as e:                        # the first envelope: 1.9188 + 0.10 > 2.00
        P.main(["--paid", "--only", "E3P", "--cli", "/x", "--out", str(tmp_path / "a.md")])
    assert e.value.code == 2 and "refused: the prior spend USD 1.9188 plus this run's cap USD 0.10 exceeds envelope " \
        "2026-10-09's USD 2.00" in capsys.readouterr().err and seen == []
    monkeypatch.setenv(P.CONSENT_ENV, "0.38")
    P.main(["--paid", "--envelope", P.E3_ENVELOPE, "--cli", "/x", "--out", str(tmp_path / "b.md")])
    out = capsys.readouterr().out
    assert seen == [0.38] and "left of the 0.45: USD 0.4500 (envelope %s; 4 ledgers of other" % P.E3_ENVELOPE in out
    assert P.prior_spend([str(pinned)], P.E3_ENVELOPE)["used"] == pytest.approx(0.10)
    with pytest.raises(SystemExit) as e:
        P.main(["--paid", "--envelope", P.E3_ENVELOPE, "--cli", "/x", "--out", str(tmp_path / "c.md")])
    assert e.value.code == 2 and "refused: the prior spend USD 0.1000 plus this run's cap USD 0.38 exceeds envelope " \
        "%s's USD 0.45" % P.E3_ENVELOPE in capsys.readouterr().err and seen == [0.38]
    assert not (pinned / "c.ledger.jsonl").exists()
    assert P.main(["--only", "E3P"]) == 0                       # the first envelope: still the four runs
    out = capsys.readouterr().out
    assert "prior spend: 4 ledgers" in out and "= USD 1.9188 at worst; left of the 2.00: USD 0.0812" in out
    assert "1 ledgers of other envelopes not counted" in out and "would be REFUSED" in out


def test_the_e3_dry_run_prints_the_plan_the_worst_case_and_the_paid_command(capsys, monkeypatch, probes_dir):
    monkeypatch.setattr(P, "run_probes", None)
    monkeypatch.setattr(P.base, "load_helper", None)
    monkeypatch.delenv(P.CONSENT_ENV, raising=False)
    seed_all(probes_dir)
    assert P.main(["--envelope", P.E3_ENVELOPE]) == 0
    out = capsys.readouterr().out
    assert out.startswith("DRY RUN") and "this run's cap 0.38 (consent value 0.38)" in out
    assert "paid run: %s=0.38 uv run --locked --script tests/sdk_probes_e.py --paid --envelope %s --only E1" % (
        P.CONSENT_ENV, P.E3_ENVELOPE) in out
    assert "= $0.445 <= the envelope's $0.45 (margin $0.005)" in out
    assert "left of the 0.45: USD 0.4500" in out and "would START (prior 0.0000 + cap 0.38 <= 0.45)" in out
    assert "with the trust warning: control, session_rule, repo_rule, trusted_repo_rule, as_installed start, " \
           "$0.3375" in out
    assert not re.search(r"^E3P\s+\$", out, re.MULTILINE) and re.search(r"^E1\s+\$0\.40 ", out, re.MULTILINE)
    assert P.e1_schedule(0.38, P.E1_EST_USD, True) == (
        ["control", "session_rule", "repo_rule", "trusted_repo_rule", "as_installed"], 0.3375)
    assert P.e1_schedule(0.38, P.E1_EST_USD, False) == (
        ["control", "session_rule", "repo_rule", "trusted_repo_rule", "trusted_control"], 0.3375)


# ---------------------------------------------------------------- the E1 rerun: the explicit overlay and its readings
AUTO_WORLD = dict(auto_plan=True, sandboxed_trusts=False)      # 2026-10-10: auto semantics, and the env does not trust


def legs_opened(w):
    return [(Path(o.cwd).name, o.settings) for o in w.opened]


def test_the_explicit_overlay_denies_the_control_in_the_auto_world(sdk, tmp_path):
    """The 2026-10-10 world (installed defaultMode auto, useAutoModeDuringPlan default true; the trust env not
    trusting): with the explicit overlay the control is denied, so the rule legs read; E1bt is trust unproven
    and its control is not run; as installed (the Session's own settings) the classifier runs the command;
    plan_auto records the same on purpose."""
    w = World(tmp_path, **AUTO_WORLD)
    (row,) = run(w, [P.PROBES[0]])
    f = row.facts
    assert row.answers == {"E1a": "yes", "E1bu": "dropped (untrusted)", "E1bt": "trust unproven", "E1c": "unknown",
                           "E1d": "yes"}, f
    assert f["control_verdict"] == "denied" and f["installed_default_mode"] == "auto"
    assert f["plan_auto_verdict"] == "ran" and f["plan_auto_effect"] == "runs" and f["as_installed_verdict"] == "ran"
    explicit, plan_auto = (json.dumps(P.E1_OVERLAYS[k]) for k in ("explicit", "plan_auto"))
    assert legs_opened(w) == [("control", explicit), ("session_rule", explicit), ("repo_rule", explicit),
                              ("trusted_repo_rule", explicit), ("as_installed", None), ("plan_auto", plan_auto)]
    assert row.status == "ran" and row.cost == pytest.approx(0.06)


def test_a_control_that_runs_makes_its_rule_legs_uncontrolled(sdk, tmp_path, monkeypatch):
    """The control RAN: a rule leg that decided its call reads uncontrolled (not unknown), its reason from the
    control's own settings; a rule leg that decided nothing stays unknown."""
    # 2026-10-10's overlay (sandbox auto-allow off only) in the auto world: the control runs by the auto semantics
    monkeypatch.setitem(P.E1_OVERLAYS, "explicit", {"sandbox": {"autoAllowBashIfSandboxed": False}})
    (row,) = run(World(tmp_path, auto_plan=True), [P.PROBES[0]])
    f = row.facts
    assert f["control_verdict"] == "ran" and f["trusted_control_verdict"] == "ran", f
    assert [row.answers[k] for k in E1_PARTS] == ["uncontrolled", "uncontrolled", "uncontrolled", "unknown", "yes"]
    assert f["E1a_uncontrolled_reason"] == f["E1bu_uncontrolled_reason"] == "control_ran:auto_mode_during_plan_not_off"
    assert f["E1bt_uncontrolled_reason"] == "trusted_control_ran:auto_mode_during_plan_not_off"
    # the sandbox auto-allow left on: that is the reason named first
    monkeypatch.setitem(P.E1_OVERLAYS, "explicit", {"useAutoModeDuringPlan": False})
    (row,) = run(World(tmp_path / "sandbox", sandbox_auto=True), [P.PROBES[0]])
    assert row.answers["E1a"] == "uncontrolled" and row.facts["E1a_uncontrolled_reason"] == \
        "control_ran:sandbox_auto_allow_not_off", row.facts
    # both off, and the control still runs (the CLI ignores the overlay's useAutoModeDuringPlan)
    monkeypatch.setitem(P.E1_OVERLAYS, "explicit", {"sandbox": {"autoAllowBashIfSandboxed": False},
                                                    "useAutoModeDuringPlan": False})
    (row,) = run(World(tmp_path / "ignored", auto_plan=True, overlay_ignored=True), [P.PROBES[0]])
    assert row.answers["E1a"] == "uncontrolled" and row.facts["E1a_uncontrolled_reason"] == "control_ran:both_off"
    c = types.SimpleNamespace(facts={}, answers={})
    P.e1_answers(c, {"control": "ran", "session_rule": "undecided", "repo_rule": "denied"})
    assert c.answers == {"E1a": "unknown", "E1bu": "uncontrolled"} and "E1a_uncontrolled_reason" not in c.facts


def test_no_e1_leg_starts_below_a_whole_session(sdk, tmp_path):
    """Sessions at the 2026-10-10 mean ($0.0675) under the e3 run cap ($0.38): every leg gets a whole $0.08; with
    the trust warning five legs run and plan_auto is skipped (the probe still ran); without it the trusted pair
    takes the fifth session and as_installed, short of $0.08, ends the probe (cap_used, E1d skipped)."""
    w = World(tmp_path, cost=P.E1_EST_USD, sandboxed_trusts=False)
    (row,) = run(w, [P.PROBES[0]], total=0.38)
    assert [Path(o.cwd).name for o in w.opened] == P.e1_schedule(0.38, P.E1_EST_USD, True)[0]
    assert {o.max_budget_usd for o in w.opened} == {0.08} and row.status == "ran", row.facts
    assert row.facts["plan_auto_verdict"] == "reserve_skipped" and "reserve_skipped" not in row.facts
    assert row.cost == pytest.approx(5 * P.E1_EST_USD) and row.answers["E1d"] == "no"
    w = World(tmp_path / "trusted", cost=P.E1_EST_USD)
    (row,) = run(w, [P.PROBES[0]], total=0.38)
    assert [Path(o.cwd).name for o in w.opened] == P.e1_schedule(0.38, P.E1_EST_USD, False)[0]
    assert {o.max_budget_usd for o in w.opened} == {0.08} and row.status == "cap_used"
    assert row.facts["reserve_skipped"] == ["as_installed", "plan_auto"] and row.answers["E1d"] == "skipped"
    assert row.answers["E1bt"] == "yes"


def test_the_overlay_is_laid_over_the_sessions_own_settings(sdk, tmp_path):
    """A helper whose Session sends settings of its own (sdk/plan-bash-gate: useAutoModeDuringPlan false): the
    explicit legs keep its other keys under the overlay's; as_installed sends the Session's own, recorded as
    facts; a Session whose settings cannot be read starts no leg ($0, helper_refused)."""
    own = json.dumps({"useAutoModeDuringPlan": False, "keep": 1, "sandbox": {"enabled": True}})
    w, h = World(tmp_path, **AUTO_WORLD), helper()

    class Own(h.Session):
        def build(self, plan):
            return dataclasses.replace(super().build(plan), settings=own)
    h.Session = Own
    from unittest import mock
    with mock.patch.dict(os.environ, {"CLAUDE_CONFIG_DIR": str(w.config)}):
        (row,) = asyncio.run(P.run_probes([P.PROBES[0]], w.cfg(), h))
    sent = {name: s for name, s in legs_opened(w)}
    assert json.loads(sent["control"]) == {"useAutoModeDuringPlan": False, "keep": 1,
                                           "sandbox": {"enabled": True, "autoAllowBashIfSandboxed": False}}
    assert json.loads(sent["plan_auto"])["useAutoModeDuringPlan"] is True and json.loads(sent["plan_auto"])["keep"] == 1
    assert sent["as_installed"] == own and row.facts["as_installed_settings_auto_mode_during_plan"] is False
    assert row.answers["E1d"] == "no" and row.facts["as_installed_verdict"] == "denied"       # the helper's own gate
    w2, h2 = World(tmp_path / "bad"), helper()

    class Bad(h2.Session):
        def build(self, plan):
            return dataclasses.replace(super().build(plan), settings="[1]")
    h2.Session = Bad
    with mock.patch.dict(os.environ, {"CLAUDE_CONFIG_DIR": str(w2.config)}):
        (row,) = asyncio.run(P.run_probes([P.PROBES[0]], w2.cfg(), h2))
    assert row.facts["control_verdict"] == "helper_refused" and row.facts["as_installed_verdict"] == "denied"
    assert {Path(o.cwd).name for o in w2.opened} == {"as_installed"} and row.answers["E1a"] == "unknown"


def test_merged_settings_and_settings_facts(tmp_path):
    ov = P.E1_OVERLAYS["explicit"]
    assert json.loads(P.merged_settings(None, ov)) == ov
    own = {"sandbox": {"enabled": True, "autoAllowBashIfSandboxed": True}, "useAutoModeDuringPlan": True, "x": 1}
    merged = json.loads(P.merged_settings(json.dumps(own), ov))
    assert merged == {"sandbox": {"enabled": True, "autoAllowBashIfSandboxed": False}, "useAutoModeDuringPlan": False,
                      "x": 1} and own["sandbox"]["autoAllowBashIfSandboxed"] is True      # the input is not changed
    path = tmp_path / "s.json"
    path.write_text(json.dumps({"x": 2}))
    assert json.loads(P.merged_settings(str(path), ov))["x"] == 2
    assert json.loads(P.merged_settings({"sandbox": "on"}, ov))["sandbox"] == {"autoAllowBashIfSandboxed": False}
    for bad in ("[1]", "{not json", str(tmp_path / "missing.json"), 3):
        with pytest.raises(ValueError):
            P.merged_settings(bad, ov)
    assert P.settings_facts(json.dumps(ov)) == {"auto_mode_during_plan": False, "sandbox_auto_allow": False}
    assert P.settings_facts(None) == P.settings_facts("{bad") == {"auto_mode_during_plan": None,
                                                                 "sandbox_auto_allow": None}
    assert P.settings_facts(json.dumps({"useAutoModeDuringPlan": "no", "sandbox": []})) == {
        "auto_mode_during_plan": None, "sandbox_auto_allow": None}
