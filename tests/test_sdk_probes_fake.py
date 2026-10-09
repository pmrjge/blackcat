"""$0 tests of tests/sdk_probes.py (SDK-1). Every probe runs against FakeCLI, a Transport that speaks the
SDK's control protocol (initialize, can_use_tool, hook_callback, interrupt, stop_task) and plays a
scripted session; the SDK's subprocess transport is disabled, so nothing reaches a CLI or the API.
The fake puts the prompts into every free-text field it emits (replies, results, tool inputs, task
summaries, server info, transcripts, denials, structured output) to show none reaches the report.

Run: uv run --python 3.13 --with pytest --with claude-agent-sdk==0.2.163 pytest -q tests/test_sdk_probes_fake.py
(without the SDK only the pure tests run; SDK_PROBES_SCRIPT=<path> points the suite at another copy.)
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
import types
from collections import Counter
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = Path(os.environ.get("SDK_PROBES_SCRIPT") or ROOT / "tests" / "sdk_probes.py")
HELPER = ROOT / "dot-config" / "dot-claude" / "bin" / "stack_sdk.py"


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, str(path))
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod          # dataclasses resolve the module's annotations through sys.modules
    spec.loader.exec_module(mod)
    return mod


P = load(SCRIPT, "sdk_probes_under_test")
LEAK = " | ".join(P.PROMPTS.values())          # every prompt, in every free-text field the fake emits

Base: Any = object                              # without the SDK only the pure tests run
with contextlib.suppress(ImportError):
    from claude_agent_sdk import Transport as Base


@pytest.fixture
def sdk(monkeypatch):
    mod = pytest.importorskip("claude_agent_sdk")
    from claude_agent_sdk._internal.transport import subprocess_cli

    async def refuse(self):
        raise AssertionError("a probe tried to start a real CLI")
    monkeypatch.setattr(subprocess_cli.SubprocessCLITransport, "connect", refuse)
    return mod


# ---------------------------------------------------------------- the fake CLI
class World:
    """What the fake sessions share: dirs, the options each session got, the wire, kills."""

    def __init__(self, tmp, bad=False, hollow=False, child="held", child_end_s=None, shell=False):
        """bad: the measurements say no. hollow: nothing to measure (PR5: no registry record; PR6: the
        reply ends before the interrupt). child (PR5): held (asks for Bash, parked), no_bash (never
        asks), pre_stopped (its record already says stopped). child_end_s (PR7): when the CLI's
        background child ends after stdin closes (None: it outlives the run; bad: after the
        ceiling). shell: every session's first turn leaves a background shell task running."""
        self.bad, self.hollow, self.config, self.state = bad, hollow, tmp / "config", tmp / "state" / "claude-agent-stack"
        self.child, self.shell = child, shell
        self.child_end_s = 0.6 if bad and child_end_s is None else child_end_s
        (self.config / "agents").mkdir(parents=True)
        for a in ("blackcat", "coder", "orchestrator", "explore"):
            (self.config / "agents" / (a + ".md")).write_text("---\nname: %s\n---\n" % a)
        self.ids, self.opened, self.answers, self.fakes, self.killed = itertools.count(1), [], [], {}, []
        self.ok_calls = Counter()                       # per scratch dir: PR13's two calls share one

    def factory(self, opts):
        f = FakeCLI(self, opts)
        self.opened.append(opts)
        self.fakes[f._process.pid] = f
        return f

    def kill(self, pid, sig):
        self.killed.append((pid, sig))
        self.fakes[pid].killed = True

    def cfg(self, **kw):
        return P.Config(config_dir=str(self.config), cli_path="/nonexistent/claude", state_dir=str(self.state),
                        transport_factory=self.factory, killer=self.kill, bg_ceiling_ms=300, settle_s=0.01,
                        hold_s=5.0, wait_s=0.5, **kw)


class FakeCLI(Base):
    def __init__(self, w, opts):
        self.w, self.o, self.n = w, opts, next(w.ids)
        self.sid = opts.resume or "sess-%04d-fake" % self.n
        self._process = types.SimpleNamespace(pid=40000 + self.n)
        self.q, self.pending, self.tasks, self.callbacks = asyncio.Queue(), {}, set(), []
        self.killed = self.started = self.turn_open = self.input_ended = self.bg = self.exiting = False
        self.rids, self.prompts = itertools.count(1), 0

    # Transport
    async def connect(self):
        pass

    def is_ready(self):
        return True

    async def end_input(self):
        """stdin EOF: like the CLI, finish the turns already sent, then exit."""
        self.input_ended = True
        if self.prompts == 0:
            self.exit()

    def exit(self):
        if self.exiting:
            return
        self.exiting = True
        if self.bg and self.w.child_end_s is not None:          # the CLI waits for its child
            t = asyncio.ensure_future(self.child_then_exit(self.w.child_end_s))
            self.tasks.add(t)
            t.add_done_callback(self.tasks.discard)
            return
        self.emit(None)

    async def child_then_exit(self, delay):
        """The background child ends `delay` s after stdin closed; the CLI then reports a second
        result (the 2026-10-09 PR7 run: results=2) and exits."""
        await asyncio.sleep(delay)
        self.emit(self.done_task("t7", "tu-7"))
        self.emit(self.result())
        self.emit(None)

    async def close(self):
        d = self.w.state / "usage" / "sessions" / self.sid
        if d.is_dir() and (not self.killed or self.w.bad):
            (d / "end").write_text("1\n")
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
            if fut is not None:
                fut.set_result(m["response"])
        elif m["type"] == "user":
            self.prompts += 1
            t = asyncio.ensure_future(self.play(m["message"]["content"]))
            self.tasks.add(t)
            t.add_done_callback(self.tasks.discard)

    # the CLI side of the control protocol
    async def control(self, rid, req):
        resp, sub = {}, req["subtype"]
        if sub == "initialize":
            self.callbacks = [i for m in (req.get("hooks") or {}).get("PreToolUse", []) for i in m["hookCallbackIds"]]
            resp = {"commands": [{"name": "review", "description": LEAK}], "output_style": "default",
                    "agents": [{"name": "blackcat", "description": LEAK}, {"name": "coder"}]}
        self.emit({"type": "control_response", "response": {"subtype": "success", "request_id": rid, "response": resp}})
        if sub == "interrupt" and self.turn_open:
            self.finish(terminal_reason="aborted_streaming")
        elif sub == "stop_task":
            # the CLI kills the task (TaskUpdated killed); its SubagentStop runs the guard's
            # mark_stopped, which stamps the registry record and drops the child's own leases
            self.emit(self.sysm("task_updated", task_id=req["task_id"], patch={"status": "killed"}))
            rec = self.w.state / self.sid / "agents" / "a5.json"
            if not self.w.bad and rec.exists():
                rec.write_text(json.dumps(dict(json.loads(rec.read_text()), stopped=1.0)))
                (self.w.state / self.sid / "fanout" / "a5" / "tu-x.json").unlink(missing_ok=True)
                if self.o.include_hook_events:
                    self.emit(self.sysm("hook_response", hook_event="SubagentStop", output=LEAK, exit_code=0,
                                        outcome="success"))

    async def ask(self, subtype, **req):
        rid = "cli_%d" % next(self.rids)
        fut = asyncio.get_running_loop().create_future()
        self.pending[rid] = fut
        self.emit({"type": "control_request", "request_id": rid, "request": dict(req, subtype=subtype)})
        resp = await asyncio.wait_for(fut, 10)
        self.w.answers.append((subtype, req.get("tool_name"), resp))
        return resp.get("response") or {}

    async def hook(self, tool, mode, agent_id=None):
        for cid in self.callbacks:
            inp = {"hook_event_name": "PreToolUse", "tool_name": tool, "tool_input": {"x": LEAK},
                   "permission_mode": mode, **({"agent_id": agent_id} if agent_id else {})}
            await self.ask("hook_callback", callback_id=cid, input=inp, tool_use_id="tu-h")

    async def allowed(self, tool, inp, agent_id=None):
        r = await self.ask("can_use_tool", tool_name=tool, input=inp, tool_use_id="tu-%s" % tool,
                           permission_suggestions=[{"type": "addRules", "destination": "userSettings",
                                                    "rules": [{"toolName": tool}], "behavior": "allow"}],
                           **({"agent_id": agent_id} if agent_id else {}))
        return r.get("behavior") == "allow"

    # frames
    def emit(self, m):
        self.q.put_nowait(m)

    def sysm(self, subtype, **kw):
        return dict({"type": "system", "subtype": subtype, "session_id": self.sid, "uuid": "u%d" % next(self.rids)}, **kw)

    def asst(self, *content, parent=None):
        return {"type": "assistant", "message": {"content": list(content), "model": "fake-model"},
                "parent_tool_use_id": parent, "session_id": self.sid}

    def started_task(self, task_id, tuid, desc):
        return self.sysm("task_started", task_id=task_id, description=desc + LEAK, tool_use_id=tuid,
                         task_type="local_agent")

    def done_task(self, task_id, tuid, status="completed"):
        return self.sysm("task_notification", task_id=task_id, status=status, output_file="/o", summary=LEAK,
                         tool_use_id=tuid)

    def result(self, **kw):
        # a fixed 9502-token prefix read by every call; a later call in the same cwd also reads what
        # the first wrote, except in the bad world (the 2026-10-09 PR13 run: 9502 and 9502)
        reuse = not self.w.bad and self.w.ok_calls[str(self.o.cwd)] >= 2
        cache = 9502 + (18470 if reuse else 0)
        return dict({"type": "result", "subtype": "success", "duration_ms": 5, "duration_api_ms": 4,
                     "is_error": False, "num_turns": 1, "session_id": self.sid, "total_cost_usd": 0.01,
                     "result": LEAK, "terminal_reason": "completed",
                     "modelUsage": {"fake-model": {"inputTokens": 10, "cacheCreationInputTokens": 18470,
                                                   "cacheReadInputTokens": cache, "outputTokens": 1}}}, **kw)

    def finish(self, **kw):
        self.turn_open = False
        (self.w.state / self.sid / "prompt-pending.json").unlink(missing_ok=True)
        self.emit(self.result(**kw))
        self.prompts -= 1
        if self.input_ended and self.prompts == 0:
            self.exit()

    def begin(self, prompt):
        g = self.w.state / self.sid
        if not self.started:
            self.started = True
            ask_gone = "permission-prompts" in self.o.extra_args and not self.w.bad
            tools = ["Agent", "Bash", "Read"] + ([] if ask_gone else ["AskUserQuestion"])
            ver = "2.1.286" if self.o.cli_path is None else "2.1.290"
            self.emit(self.sysm("init", tools=tools, agents=["blackcat", "coder"], claude_code_version=ver,
                                cwd=str(self.o.cwd), model="fake-model", permissionMode="plan"))
            if self.o.include_hook_events:
                names = ["SessionStart"] + (["UserPromptSubmit"] if self.w.bad and self.o.cli_path is None else [])
                for name in names:
                    self.emit(self.sysm("hook_response", hook_event=name, output=LEAK, exit_code=0, outcome="success"))
            self.emit({"type": "rate_limit_event", "rate_limit_info": {"status": "allowed"}, "uuid": "r",
                       "session_id": self.sid})
            (self.w.state / "usage" / "sessions" / self.sid).mkdir(parents=True, exist_ok=True)
            proj = self.w.config / "projects" / "-tmp-fake"
            proj.mkdir(parents=True, exist_ok=True)
            entry = "cli" if self.w.bad else "sdk-py"
            (proj / (self.sid + ".jsonl")).write_text(json.dumps({"entrypoint": entry, "message": prompt}) + "\n")
            if self.w.shell:                                    # a background shell that never ends
                self.emit(self.sysm("task_started", task_id="tsh", description=LEAK, tool_use_id="tu-sh",
                                    task_type="local_bash"))
        g.mkdir(parents=True, exist_ok=True)
        with open(g / "prompt-windows.jsonl", "a") as fh:
            fh.write('{"base": 1}\n')
        (g / "prompt-pending.json").write_text("{}")
        (g / "budget.json").write_text('{"used": 1}')
        self.turn_open = True

    async def play(self, prompt):
        key = next(k for k, v in P.PROMPTS.items() if v == prompt)
        self.begin(prompt)
        await getattr(self, "play_" + key)()

    async def play_ok(self):
        self.w.ok_calls[str(self.o.cwd)] += 1
        self.emit(self.asst({"type": "text", "text": LEAK}))
        self.finish()

    async def play_ask(self):
        if "permission-prompts" in self.o.extra_args:
            self.finish(permission_denials=[{"tool_name": "AskUserQuestion", "tool_use_id": "tu-q",
                                             "tool_input": {"q": LEAK}}])
            return
        if self.o.can_use_tool is not None and self.o.hooks:
            await self.hook("AskUserQuestion", "default")
            await self.allowed("AskUserQuestion", {"questions": [
                {"question": LEAK, "options": [{"label": "red"}, {"label": "blue"}]}]})
        self.finish()

    async def play_plan(self):
        await self.hook("ExitPlanMode", "plan")
        if not self.w.bad and await self.allowed("ExitPlanMode", {"plan": LEAK}):
            await self.hook("Agent", "default")
            self.emit(self.asst({"type": "tool_use", "id": "tu-1", "name": "Agent", "input": {"prompt": LEAK}}))
            self.emit(self.started_task("t1", "tu-1", "coder: "))
            await self.hook("Write", "acceptEdits", agent_id="a1")
            if await self.allowed("Write", {"file_path": os.path.join(self.o.cwd, "hello.txt")}, agent_id="a1"):
                Path(self.o.cwd, "hello.txt").write_text("hi")
            await self.allowed("Write", {"file_path": os.path.join(self.o.cwd, "..", "escape.txt")}, agent_id="a1")
            await self.allowed("Bash", {"command": "rm -rf ~"}, agent_id="a1")
            self.emit(self.done_task("t1", "tu-1"))
        self.finish()

    async def play_stop(self):
        if not await self.allowed("Agent", {"subagent_type": "coder", "prompt": LEAK}):
            self.finish()
            return
        self.emit(self.asst({"type": "tool_use", "id": "tu-5", "name": "Agent", "input": {"prompt": LEAK}}))
        # the guard under the SDK: the launch is async, the spawn lease is gone, the child is in the
        # registry (bg, keyed by its agent id, naming the Agent call); another agent's record beside it
        g = self.w.state / self.sid
        (g / "agents").mkdir(parents=True, exist_ok=True)
        (g / "agents" / "a9.json").write_text(json.dumps({"id": "a9", "tool_use_id": "tu-9", "bg": True}))
        if not self.w.hollow:
            rec = {"id": "a5", "type": "coder", "bg": True, "tool_use_id": "tu-5", "status": "async_launched"}
            if self.w.child == "pre_stopped":
                rec["stopped"] = 1.0
            (g / "agents" / "a5.json").write_text(json.dumps(rec))
        (g / "fanout" / "a5").mkdir(parents=True, exist_ok=True)
        (g / "fanout" / "a5" / "tu-x.json").write_text("{}")      # a lease the child holds itself
        self.emit(self.started_task("t5", "tu-5", "coder: "))
        await self.allowed("Bash", {"command": "rm -rf ~"})          # the main thread's: denied, not held
        if self.w.child != "no_bash":
            await self.allowed("Read", {"file_path": "/etc/passwd"}, agent_id="a5")
            await self.allowed("Bash", {"command": "true"}, agent_id="a5")   # held until the probe lets go

    async def play_count(self):
        if self.w.hollow:                                       # the reply completes before any interrupt
            self.emit(self.asst({"type": "text", "text": "1\n2\n3"}))
            self.finish()
            return
        if self.o.include_partial_messages:
            self.emit({"type": "stream_event", "uuid": "se", "session_id": self.sid,
                       "event": {"type": "content_block_delta", "delta": {"text": LEAK}}})
        self.emit(self.asst({"type": "text", "text": "1\n2\n3"}))

    async def play_bg(self):
        self.bg = True
        self.emit(self.asst({"type": "tool_use", "id": "tu-7", "name": "Agent", "input": {"prompt": LEAK}}))
        self.emit(self.started_task("t7", "tu-7", "coder: "))
        self.finish()
        if self.o.can_use_tool is not None or self.o.hooks:    # the SDK would hold stdin open for good;
            await asyncio.sleep(0.2)                            # end anyway so the suite cannot hang
            self.exit()

    async def play_report(self):
        self.finish(structured_output={"status": "done", "result": LEAK, "files": [LEAK]})

    async def play_tree(self):
        self.emit(self.asst({"type": "tool_use", "id": "tu-a", "name": "Agent", "input": {"prompt": LEAK}}))
        self.emit(self.started_task("ta", "tu-a", "orchestrator: "))
        if self.o.forward_subagent_text:
            self.emit(self.asst({"type": "text", "text": LEAK}, parent="tu-a"))
        self.emit(self.asst({"type": "tool_use", "id": "tu-b", "name": "Agent", "input": {"prompt": LEAK}},
                            parent="tu-a"))
        self.emit(self.started_task("tb", "tu-b", "explore: "))
        self.emit(self.done_task("tb", "tu-b"))
        self.emit(self.done_task("ta", "tu-a"))
        self.finish()


def run(world, probes=None):
    helper = load(HELPER, "stack_sdk_for_probes")
    return asyncio.run(P.run_probes(probes or P.PROBES, world.cfg(), helper))


def probe_of(opts):
    """The probe a session belonged to: its scratch cwd is sdk-probe-<id>-*."""
    return Path(opts.cwd).name.split("-")[2].upper()


def assert_no_prompt_text(text):
    flat = " ".join(text.split())
    for p in P.PROMPTS.values():
        p = " ".join(p.split())
        assert p not in flat
        for i in range(max(1, len(p) - 23)):
            assert p[i:i + 24] not in flat, p[i:i + 24]


# ---------------------------------------------------------------- caps (pure)
def test_registry_caps_are_per_probe_and_sum_to_the_ceiling():
    caps = {p.pid: p.budget_usd for p in P.PROBES}
    assert sorted(caps, key=lambda s: int(s[2:])) == ["PR%d" % i for i in range(1, 14)]
    assert {k for k, v in caps.items() if v == 1.50} == {"PR3", "PR5", "PR7", "PR10"}
    assert {v for k, v in caps.items() if k not in P.LARGE} == {0.50}
    assert sum(caps.values()) == pytest.approx(10.50) and P.TOTAL_CAP_USD == 10.50
    P.validate_registry(P.PROBES)


@pytest.mark.parametrize("bad", [None, 0, 0.0, -0.5, True, "0.5", 0.51, float("nan")])
def test_a_probe_without_a_valid_cap_is_refused(bad):
    pr1 = next(p for p in P.PROBES if p.pid == "PR1")
    probes = [dataclasses.replace(pr1, budget_usd=bad) if p is pr1 else p for p in P.PROBES]
    with pytest.raises(P.BudgetError):
        P.validate_registry(probes)
    with pytest.raises(P.BudgetError):
        asyncio.run(P.run_probes(probes, P.Config(config_dir="/x", cli_path=None, state_dir="/x"), None))


def test_a_large_cap_on_a_small_probe_and_duplicates_are_refused():
    probes = [dataclasses.replace(p, budget_usd=1.50) for p in P.PROBES]
    with pytest.raises(P.BudgetError):
        P.validate_registry(probes)
    with pytest.raises(P.BudgetError):
        P.validate_registry(P.PROBES + P.PROBES[:1])


def test_the_default_command_prints_the_plan_and_spends_nothing(capsys, monkeypatch):
    monkeypatch.setattr(P, "run_probes", None)                 # would raise if called
    assert P.main(["--only", "pr1,PR10"]) == 0
    out = capsys.readouterr().out
    assert "PR1 " in out and "PR10" in out and "PR3 " not in out and "total cap $2.00" in out
    with pytest.raises(SystemExit):
        P.main(["--only", "PR99"])
    assert P.main([]) == 0                                     # the whole plan: caps unchanged
    out = capsys.readouterr().out
    assert "total cap $10.50" in out
    for pid in ("PR3", "PR5", "PR7", "PR10"):
        assert re.search(rf"^{pid}\s+\$1\.50 ", out, re.MULTILINE), pid
    assert len(re.findall(r"^PR\d+\s+\$0\.50 ", out, re.MULTILINE)) == 9
    assert P.Config(config_dir="/x", cli_path=None, state_dir="/x").bg_ceiling_ms == 2000


# ---------------------------------------------------------------- the report (pure)
def test_clean_keeps_identifiers_and_withholds_text():
    assert P.clean({"a": 1, "b": True, "v": "2.1.286", "t": ["SessionStart", "x y"], "p": P.PROMPTS["ok"]}) == {
        "a": 1, "b": True, "v": "2.1.286", "t": ["SessionStart", P.WITHHELD], "p": P.WITHHELD}
    assert P.clean({P.PROMPTS["ask"]: 1}) == {P.WITHHELD: 1}
    assert P.clean(object()) == P.WITHHELD


def test_render_and_write_never_carry_prompt_text(tmp_path):
    probe = P.PROBES[0]
    facts = {k: v for k, v in P.PROMPTS.items()}
    facts.update(nested={"deep": [P.PROMPTS["plan"]]})
    rows = [P.Row(probe, "yes", 0.5, facts=facts, sessions=["sess-1", P.PROMPTS["count"]],
                  transcripts=["/a/b.jsonl", P.PROMPTS["report"] + ".jsonl"])]
    text = P.render(rows, {"date": "2026-10-08", "sdk": P.PROMPTS["tree"]})
    assert_no_prompt_text(text)
    assert P.WITHHELD in text and "/a/b.jsonl" in text and "sess-1" in text
    for p in P.PROMPTS.values():         # an identifier-shaped copy passes clean(); the final check stops it
        squashed = "_".join(re.findall(r"[A-Za-z0-9]+", p))[:150]
        assert P.clean(squashed) == squashed
        with pytest.raises(ValueError):
            P.render([P.Row(probe, "yes", 0.5, facts={"x": squashed})], {"date": "d"})
    path = P.write_report(str(tmp_path / "r" / "2026-10-08.md"), text)
    assert P.write_report(str(tmp_path / "r" / "2026-10-08.md"), text).endswith("2026-10-08-2.md")
    assert os.stat(path).st_mode & 0o777 == 0o600
    for p in P.PROMPTS.values():
        with pytest.raises(ValueError):
            P.assert_no_prompt("x " + p + " y")
        with pytest.raises(ValueError):
            P.write_report(str(tmp_path / "leak.md"), "x " + p)
    assert not (tmp_path / "leak.md").exists()


def test_a_probe_error_keeps_only_the_exception_type(sdk, tmp_path):

    async def boom(ctx):
        raise RuntimeError(P.PROMPTS["ask"])
    probes = [dataclasses.replace(p, fn=boom) if p.pid == "PR8" else p for p in P.PROBES if p.pid == "PR8"]
    rows = asyncio.run(P.run_probes(probes, P.Config(config_dir=str(tmp_path), cli_path=None,
                                                     state_dir=str(tmp_path)), None))
    assert (rows[0].answer, rows[0].facts["error"]) == ("error", "RuntimeError")
    assert_no_prompt_text(P.render(rows, {"date": "d"}))


# ---------------------------------------------------------------- every probe over the fake CLI
def test_every_probe_answers_yes_in_the_good_world_with_its_own_cap(sdk, tmp_path):
    w = World(tmp_path)
    rows = run(w)
    got = {r.probe.pid: r.answer for r in rows}
    assert got == {p.pid: "yes" for p in P.PROBES}, {r.probe.pid: (r.answer, r.facts) for r in rows}
    # caps: every session had one, within its probe's; a probe's sessions never exceed it together
    caps = {p.pid: p.budget_usd for p in P.PROBES}
    per = {}
    for o in w.opened:
        assert isinstance(o.max_budget_usd, float) and 0 < o.max_budget_usd <= caps[probe_of(o)], o.max_budget_usd
        per.setdefault(probe_of(o), []).append(o.max_budget_usd)
    assert set(per) == set(caps)
    assert per["PR2"] == [0.25, 0.25] and per["PR3"] == [1.5] and per["PR13"] == [0.25, 0.25]
    assert per["PR6"] == [0.25, 0.25]
    for o in w.opened:              # what user allow rules would approve without asking the host
        assert json.loads(o.settings) == {"sandbox": {"autoAllowBashIfSandboxed": False}}
        assert {"WebSearch", "WebFetch", "mcp__image-studio"} <= set(o.disallowed_tools)
    pr7 = next(o for o in w.opened if probe_of(o) == "PR7")
    assert pr7.can_use_tool is None and not pr7.hooks          # else the SDK holds stdin while the child runs
    assert "Bash(sleep 110)" in pr7.allowed_tools
    pr5 = next(o for o in w.opened if probe_of(o) == "PR5")
    assert isinstance(pr5.can_use_tool, P.HoldHost) and not pr5.hooks and pr5.include_hook_events
    f5 = next(r.facts for r in rows if r.probe.pid == "PR5")
    assert f5["child_live_at_stop"] and f5["registry_is_held_agent"] and f5["registry_bg_before"]
    assert (f5["child_status_after_stop"], f5["registry_stopped_after"], f5["subagent_stop_events"]) == (
        "killed", True, 1)
    assert (f5["leases_before"], f5["leases_after"], f5["hold_released_by"]) == (1, 0, "event")
    f13 = next(r.facts for r in rows if r.probe.pid == "PR13")
    assert (f13["run1_cache_read"], f13["run2_cache_read"], f13["cache_read_gain"]) == (9502, 27972, 18470)
    for r in rows:              # PR7 closes while its child runs: counted at its whole cap
        want = 1.50 if r.probe.pid == "PR7" else 0.01 * len(per[r.probe.pid])
        assert r.cost == pytest.approx(want) and r.cap == caps[r.probe.pid], r.probe.pid
        assert r.sessions and r.facts["rate_limit_events"] >= 1
        open_at_close = {"local_agent": 1} if r.probe.pid == "PR7" else {}
        assert r.facts["open_tasks_at_close_by_type"] == open_at_close, r.probe.pid
    # the real transport would pass the cap to the CLI
    from claude_agent_sdk._internal.transport.subprocess_cli import SubprocessCLITransport

    cmd = SubprocessCLITransport(prompt="x", options=w.opened[0])._build_command()
    assert cmd[cmd.index("--max-budget-usd") + 1] == "0.5"


def test_the_report_of_a_full_run_has_no_prompt_text(sdk, tmp_path):
    w = World(tmp_path)
    rows = run(w)
    text = P.render(rows, dict(P.versions(None), date="2026-10-08"))
    assert_no_prompt_text(text)
    assert P.WITHHELD not in text            # no probe records free text, even though the fake offers it
    assert all("| %s |" % r.probe.pid in text for r in rows)
    assert "sdk-py" in text and "SessionStart" in text and str(w.config / "projects") in text
    path = P.write_report(str(tmp_path / "out" / "2026-10-08.md"), text)
    assert_no_prompt_text(Path(path).read_text())


def test_host_and_observer_never_decide_more_than_the_probe_allows(sdk, tmp_path):
    w = World(tmp_path)
    run(w, [p for p in P.PROBES if p.pid in ("PR2", "PR3", "PR5")])
    can = [(t, r["response"]) for s, t, r in w.answers if s == "can_use_tool"]
    hooks = [r["response"] for s, _, r in w.answers if s == "hook_callback"]
    assert hooks and all(h == {"continue": True} for h in hooks)                  # neutral: no decision
    assert all("updatedPermissions" not in r for _, r in can)                     # nothing persisted
    decided = [(t, r["behavior"]) for t, r in can]
    assert decided == [("AskUserQuestion", "allow"), ("ExitPlanMode", "allow"), ("Write", "allow"),
                       ("Write", "deny"), ("Bash", "deny"),
                       ("Agent", "allow"), ("Bash", "deny"), ("Read", "deny"), ("Bash", "deny")]  # PR5
    ask = next(r for t, r in can if t == "AskUserQuestion")
    assert list(ask["updatedInput"]["answers"].values()) == ["red"]


def test_answers_follow_the_measurements_in_the_bad_world(sdk, tmp_path):
    w = World(tmp_path, bad=True)
    pick = ("PR3", "PR4", "PR5", "PR7", "PR9", "PR11", "PR12", "PR13")
    got = {r.probe.pid: r.answer for r in run(w, [p for p in P.PROBES if p.pid in pick])}
    assert got == dict.fromkeys(pick, "no"), got


def test_hollow_measurements_answer_unknown(sdk, tmp_path):
    """PR5 with no registry record of the child, PR6 with no turn actually interrupted: no answer."""
    w = World(tmp_path, hollow=True)
    got = {r.probe.pid: (r.answer, r.facts) for r in run(w, [p for p in P.PROBES if p.pid in ("PR5", "PR6")])}
    assert got["PR5"][0] == "unknown" and got["PR5"][1]["registry_before"] is False
    assert got["PR5"][1]["child_pending"] is True and got["PR5"][1]["child_status_after_stop"] == "killed"
    assert got["PR6"][0] == "unknown" and got["PR6"][1]["interrupted"] is False


@pytest.mark.parametrize("child, fact", [("no_bash", "child_pending"), ("pre_stopped", "registry_stopped_before")])
def test_pr5_answers_only_for_a_child_live_at_the_stop(sdk, tmp_path, child, fact):
    """A child that never asked for Bash (not held) or whose record already says stopped: the stop
    proves nothing, although the record ends up stopped and the task terminal."""
    w = World(tmp_path, child=child)
    (row,) = run(w, [p for p in P.PROBES if p.pid == "PR5"])
    assert row.answer == "unknown", row.facts
    assert row.facts["child_live_at_stop"] is False and row.facts[fact] is (child == "pre_stopped")
    assert row.facts["child_status_after_stop"] == "killed" and row.facts["registry_stopped_after"] is True


def test_hold_host_parks_only_the_first_subagent_bash(sdk):
    async def go():
        import anyio

        def ctx(agent):
            return types.SimpleNamespace(agent_id=agent)
        h = P.HoldHost(hold_s=5.0)
        assert (await h("Agent", {}, ctx(None))).behavior == "allow"
        assert (await h("Task", {}, ctx(None))).behavior == "allow"
        assert (await h("Bash", {"command": "true"}, ctx(None))).behavior == "deny"     # main thread
        assert (await h("Read", {"file_path": "x"}, ctx("a1"))).behavior == "deny"
        assert not h.pending
        out = {}
        async with anyio.create_task_group() as tg:
            async def first():
                out["first"] = await h("Bash", {"command": "true"}, ctx("a1"))
            tg.start_soon(first)
            await P.poll(lambda: h.pending, 2)
            assert h.pending and h.pending_agent == "a1" and "first" not in out      # parked
            second = await h("Bash", {"command": "true"}, ctx("a1"))
            assert second.behavior == "deny" and "first" not in out                   # not parked
            h.release.set()
        assert out["first"].behavior == "deny" and h.released_by == "event"
        assert all(not getattr(r, "updated_permissions", None) for r in out.values())
        h2 = P.HoldHost(hold_s=0.05)
        assert (await h2("Bash", {"command": "true"}, ctx("a2"))).behavior == "deny"
        assert h2.released_by == "timeout"
    asyncio.run(go())


def test_a_session_without_a_cap_never_connects_and_stops_the_run(sdk, tmp_path):
    w = World(tmp_path)

    async def no_cap(c):                  # builds the stack's options directly: no max_budget_usd
        async with c.client(c.helper.options("blackcat", cwd=c.scratch, cli_path=c.cfg.cli_path)) as s:
            await s.turn(P.PROMPTS["ok"], 5)
        return P.Outcome("yes", {})
    probes = [dataclasses.replace(p, fn=no_cap) if p.pid == "PR1" else p for p in P.PROBES]
    rows = run(w, probes)
    assert [(r.probe.pid, r.answer) for r in rows] == [("PR1", "refused")]
    assert w.opened == []                                                         # no transport made


def test_over_spend_shrinks_later_caps_and_skips_once_the_total_is_used(sdk, tmp_path):
    w = World(tmp_path)
    probes = [p for p in P.PROBES if p.pid in ("PR1", "PR11")]

    async def spend(c):
        c.costs[99] = 10.48                                     # an overshooting probe
        return P.Outcome("yes", {})
    probes = [dataclasses.replace(probes[0], fn=spend), probes[1]]
    rows = run(w, probes)
    assert [r.answer for r in rows] == ["yes", "skipped"] and w.opened == []
    probes[0] = dataclasses.replace(probes[0], fn=lambda c: _spend(c, 10.30))
    w2 = World(tmp_path / "2")
    rows = run(w2, probes)
    assert rows[1].answer == "yes" and rows[1].cap == pytest.approx(0.20)
    assert [o.max_budget_usd for o in w2.opened] == [0.2]


def test_a_session_without_a_result_counts_at_its_whole_cap(sdk, tmp_path):
    w = World(tmp_path)

    async def silent(c):                  # connects, never gets a result (a timeout, a crash, a kill)
        async with c.client(c.options(share=0.5)):
            pass
        async with c.client(c.options()) as s:          # only what is left: 0.25, not 0.5
            await s.turn(P.PROMPTS["ok"], 5)
        return P.Outcome("yes", {})
    pr11 = next(p for p in P.PROBES if p.pid == "PR11")
    rows = run(w, [dataclasses.replace(pr11, fn=silent)])
    assert [o.max_budget_usd for o in w.opened] == [0.25, 0.25]
    assert rows[0].cost == pytest.approx(0.26) and rows[0].facts["sessions_without_result"] == 1


def test_host_paths_globs_and_questions(sdk, tmp_path):
    h = P.Host(str(tmp_path), ("Glob", "Read", "Bash"))
    ok = lambda tool, inp: h._ok(tool, inp)  # noqa: E731
    assert ok("Glob", {"pattern": "**/*.py"}) and ok("Read", {"file_path": "a/b.txt"})
    for pattern in ("/Users/**", "../*", "~/.ssh/*", "a/../../x"):
        assert not ok("Glob", {"pattern": pattern}), pattern
    assert not ok("Read", {"file_path": "/etc/passwd"}) and not ok("Read", {"file_path": "../x"})
    assert not ok("Bash", {"command": "sleep 1 && curl x"}) and ok("Bash", {"command": "sleep 5"})
    deny = asyncio.run(h("AskUserQuestion", {"questions": [{"question": "q", "options": [{"label": "a"}]}]}, None))
    assert deny.behavior == "deny"                    # answered only where the probe allows it (PR2)


def test_mcp_tools_the_user_allows_never_reach_a_probe_session(sdk, tmp_path):
    w = World(tmp_path)
    (w.config / "settings.json").write_text(json.dumps({"permissions": {"allow": [
        "mcp__exa", "mcp__neural-memory", "Bash(ls)", "Read"]}}))
    (w.config / "settings.local.json").write_text(json.dumps({"permissions": {"allow": ["mcp__magg__pw_*"]}}))
    run(w, [p for p in P.PROBES if p.pid in ("PR3", "PR10")])
    assert {probe_of(o) for o in w.opened} == {"PR3", "PR10"}
    for o in w.opened:
        assert o.strict_mcp_config is True
        assert {"mcp__exa", "mcp__neural-memory", "mcp__magg__pw_*", "WebSearch"} <= set(o.disallowed_tools)
        assert "Bash(ls)" not in o.disallowed_tools and "Read" not in o.disallowed_tools
    assert P.allowed_mcp(str(tmp_path / "missing")) == []


def test_a_cap_left_with_many_decimals_is_not_rounded_above_it(sdk, tmp_path):
    w = World(tmp_path)

    async def after_overshoot(c):
        c.costs[99] = 0.2512345                     # an earlier session's odd cost
        async with c.client(c.options()) as s:
            await s.turn(P.PROMPTS["ok"], 5)
        return P.Outcome("yes", {})
    pr11 = next(p for p in P.PROBES if p.pid == "PR11")
    rows = run(w, [dataclasses.replace(pr11, fn=after_overshoot)])
    assert rows[0].answer == "yes"
    assert 0 < w.opened[0].max_budget_usd <= 0.5 - 0.2512345


def test_a_session_closed_while_its_child_runs_counts_at_its_whole_cap(sdk, tmp_path):
    w = World(tmp_path)

    async def leave_child(c):             # the result arrives, the child still runs, the session closes
        async with c.client(c.options()) as s:
            await s.turn(P.PROMPTS["bg"], 5)
        return P.Outcome("yes", {})
    pr11 = next(p for p in P.PROBES if p.pid == "PR11")
    rows = run(w, [dataclasses.replace(pr11, fn=leave_child)])
    assert rows[0].cost == pytest.approx(0.5) and rows[0].facts["sessions_without_result"] == 1
    assert rows[0].facts["open_tasks_at_close_by_type"] == {"local_agent": 1}


def test_a_background_shell_left_running_does_not_count_the_whole_cap(sdk, tmp_path):
    """Only agent tasks (the SDK's DEFERRING_TASK_TYPES) hold a session at its cap: the 2026-10-09
    PR5 session was counted at $1.50 for a background shell."""
    w = World(tmp_path, shell=True)
    rows = run(w, [p for p in P.PROBES if p.pid in ("PR11", "PR13")])
    for r in rows:
        n = len([o for o in w.opened if probe_of(o) == r.probe.pid])
        assert r.cost == pytest.approx(0.01 * n) and r.facts["sessions_without_result"] == 0, r.probe.pid
        assert r.facts["open_tasks_at_close_by_type"] == {"local_bash": n}, r.probe.pid
    from claude_agent_sdk._internal.query import DEFERRING_TASK_TYPES
    assert P.AGENT_TASKS == DEFERRING_TASK_TYPES == {"local_agent", "local_workflow"}


def test_pr7_a_child_that_ends_before_the_ceiling_gives_no_answer(sdk, tmp_path):
    """The 2026-10-09 run: the child ended 7.4 s after the first result, under the 30 s ceiling, and
    query() streamed on to a second result. That is no measurement of the ceiling: unknown."""
    w = World(tmp_path, child_end_s=0.0)
    (row,) = run(w, [p for p in P.PROBES if p.pid == "PR7"])
    assert row.answer == "unknown", row.facts
    assert row.facts["results"] == 2 and row.facts["ended_at_first_result"] is False
    assert row.facts["child_status_at_end"] == "completed" and row.facts["child_end_s"] is not None
    w = World(tmp_path / "late", child_end_s=0.6)               # past the 300 ms ceiling: the run waited
    (row,) = run(w, [p for p in P.PROBES if p.pid == "PR7"])
    assert row.answer == "no" and row.facts["results"] == 2, row.facts
    w = World(tmp_path / "cut")                                  # the run ends while the child runs
    (row,) = run(w, [p for p in P.PROBES if p.pid == "PR7"])
    assert row.answer == "yes" and row.facts["ended_at_first_result"] is True, row.facts


@pytest.fixture
def pinned(monkeypatch):
    monkeypatch.setattr(P, "versions", lambda cli: {"sdk": P.SDK_PIN, "system_cli": None, "bundled_cli": None})
    monkeypatch.setattr(P, "load_helper", lambda config: None)


def test_the_report_path_is_checked_before_any_billed_call(pinned, monkeypatch, tmp_path):
    called = []

    async def never(*a, **k):
        called.append(1)
    monkeypatch.setattr(P, "run_probes", never)
    locked = tmp_path / "locked"
    locked.mkdir(mode=0o500)
    for out in ("/dev/null/x/r.md", str(locked / "r.md")):
        with pytest.raises(SystemExit):
            P.main(["--run", "--cli", "/nonexistent/claude", "--out", out])
    locked.chmod(0o700)
    assert called == []
    # a bare file name lands in the current directory; Ctrl-C still writes what finished
    monkeypatch.chdir(tmp_path)

    async def one_then_ctrl_c(probes, cfg, helper, rows):
        rows.append(P.Row(probes[0], "yes", 0.5, cost=0.01, sessions=["sess-1"]))
        raise KeyboardInterrupt
    monkeypatch.setattr(P, "run_probes", one_then_ctrl_c)
    with pytest.raises(KeyboardInterrupt):
        P.main(["--run", "--cli", "/nonexistent/claude", "--out", "report.md", "--config", str(tmp_path)])
    text = (tmp_path / "report.md").read_text()
    assert "| PR1 |" in text and "| yes |" in text and "sess-1" in text


def test_an_unpinned_sdk_is_refused_before_any_call(monkeypatch, tmp_path):
    monkeypatch.setattr(P, "versions", lambda cli: {"sdk": "0.2.164", "system_cli": None, "bundled_cli": None})
    monkeypatch.setattr(P, "run_probes", None)                 # would raise if called
    with pytest.raises(SystemExit):
        P.main(["--run", "--cli", "/nonexistent/claude", "--out", str(tmp_path / "r.md")])
    assert not (tmp_path / "r.md").exists()


async def _spend(c, usd):
    c.costs[99] = usd
    return P.Outcome("yes", {})


def test_pr12_kills_the_cli_with_sigkill_and_pr7_sets_the_ceiling(sdk, tmp_path):
    w = World(tmp_path)
    run(w, [p for p in P.PROBES if p.pid in ("PR7", "PR12")])
    assert len(w.killed) == 1 and w.killed[0][1] == signal.SIGKILL
    pr7 = [o for o in w.opened if probe_of(o) == "PR7"]
    assert pr7[0].env["CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS"] == "300"
    assert all(o.cli_path == "/nonexistent/claude" for o in w.opened)


def test_default_report_path_is_the_main_checkout(monkeypatch):
    p = P.default_out("2026-10-08")
    assert p.endswith(os.path.join(".claude-work", "sdk", "probes", "2026-10-08.md"))
    assert ".claude-work/wt-" not in p
