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

    def __init__(self, tmp, bad=False):
        self.bad, self.config, self.state = bad, tmp / "config", tmp / "state" / "claude-agent-stack"
        (self.config / "agents").mkdir(parents=True)
        for a in ("blackcat", "coder", "orchestrator", "explore"):
            (self.config / "agents" / (a + ".md")).write_text("---\nname: %s\n---\n" % a)
        self.ids, self.opened, self.answers, self.fakes, self.killed = itertools.count(1), [], [], {}, []
        self.ok_calls = 0

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
                        transport_factory=self.factory, killer=self.kill, bg_ceiling_ms=300, settle_s=0.01, **kw)


class FakeCLI(Base):
    def __init__(self, w, opts):
        self.w, self.o, self.n = w, opts, next(w.ids)
        self.sid = opts.resume or "sess-%04d-fake" % self.n
        self._process = types.SimpleNamespace(pid=40000 + self.n)
        self.q, self.pending, self.tasks, self.callbacks = asyncio.Queue(), {}, set(), []
        self.killed = self.started = self.turn_open = False
        self.rids = itertools.count(1)

    # Transport
    async def connect(self):
        pass

    def is_ready(self):
        return True

    async def end_input(self):
        self.q.put_nowait(None)

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
            lease = self.w.state / self.sid / "fanout" / "blackcat" / "tu-5.json"
            if not self.w.bad:
                lease.unlink(missing_ok=True)
            self.emit(self.sysm("task_notification", task_id=req["task_id"], status="stopped", output_file="/o",
                                summary=LEAK, tool_use_id="tu-5"))

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

    def finish(self, **kw):
        self.turn_open = False
        (self.w.state / self.sid / "prompt-pending.json").unlink(missing_ok=True)
        cache = 0 if self.w.bad or self.w.ok_calls < 2 else 700
        self.emit(dict({"type": "result", "subtype": "success", "duration_ms": 5, "duration_api_ms": 4,
                        "is_error": False, "num_turns": 1, "session_id": self.sid, "total_cost_usd": 0.01,
                        "result": LEAK, "terminal_reason": "completed",
                        "modelUsage": {"fake-model": {"inputTokens": 10, "cacheCreationInputTokens": 5,
                                                      "cacheReadInputTokens": cache, "outputTokens": 1}}}, **kw))

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
        self.w.ok_calls += 1
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
        self.emit(self.asst({"type": "tool_use", "id": "tu-5", "name": "Agent", "input": {"prompt": LEAK}}))
        lease = self.w.state / self.sid / "fanout" / "blackcat" / "tu-5.json"
        lease.parent.mkdir(parents=True, exist_ok=True)
        lease.write_text("{}")
        self.emit(self.started_task("t5", "tu-5", "coder: "))
        await self.allowed("Bash", {"command": "sleep 110; rm -rf ~"}, agent_id="a5")
        await self.allowed("Bash", {"command": "sleep 110"}, agent_id="a5")

    async def play_count(self):
        self.emit(self.asst({"type": "text", "text": "1\n2\n3"}))

    async def play_bg(self):
        self.emit(self.asst({"type": "tool_use", "id": "tu-7", "name": "Agent", "input": {"prompt": LEAK}}))
        self.emit(self.started_task("t7", "tu-7", "coder: "))
        self.finish()
        await asyncio.sleep(0.2)
        if self.w.bad:
            self.emit(self.done_task("t7", "tu-7"))
        self.emit(None)                                        # the CLI exits: the stream ends

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
    for r in rows:
        assert r.cost == pytest.approx(0.01 * len(per[r.probe.pid])) and r.cap == caps[r.probe.pid]
        assert r.sessions and r.facts["rate_limit_events"] >= 1
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
                       ("Write", "deny"), ("Bash", "deny"), ("Bash", "deny"), ("Bash", "allow")]
    ask = next(r for t, r in can if t == "AskUserQuestion")
    assert list(ask["updatedInput"]["answers"].values()) == ["red"]


def test_answers_follow_the_measurements_in_the_bad_world(sdk, tmp_path):
    w = World(tmp_path, bad=True)
    pick = ("PR3", "PR4", "PR5", "PR7", "PR9", "PR11", "PR12", "PR13")
    got = {r.probe.pid: r.answer for r in run(w, [p for p in P.PROBES if p.pid in pick])}
    assert got == dict.fromkeys(pick, "no"), got


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
