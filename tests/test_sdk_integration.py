"""Agent SDK integration (Q7): the settings hooks with no TTY and SDK-shaped events, the opt-in JSON
report line (STACK_REPORT_FORMAT), and the optional helper dot-config/dot-claude/bin/stack_sdk.py (parser,
options, run() over a fake query, nothing loads it).

Run: uv run --python 3.13 --with pytest pytest -q tests/test_sdk_integration.py
     (the options test also runs with --with claude-agent-sdk==<the helper's pin>)
"""
import asyncio
import importlib.util
import json
import os
import re
import subprocess
import sys
import types
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DOT = ROOT / "dot-config" / "dot-claude"
GUARD = DOT / "hooks" / "agent_guard.py"
HELPER = DOT / "bin" / "stack_sdk.py"
PREFIXES = ("STACK_", "BLACKCAT_", "SCREEN_", "STRIP_", "CLAUDE_CODE_MAX")
# What the Python SDK 0.2.163 adds to the CLI's environment (subprocess_cli.py), which every hook
# inherits; CLAUDECODE is removed.
SDK_ENV = {"CLAUDE_CODE_ENTRYPOINT": "sdk-py", "CLAUDE_AGENT_SDK_VERSION": "0.2.163"}


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, str(path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


sdk = load(HELPER, "stack_sdk")
guard = load(GUARD, "agent_guard_sdk")


@pytest.fixture
def env(tmp_path):
    e = {k: v for k, v in os.environ.items()
         if not k.startswith(PREFIXES) and k not in ("TERM", "CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT")}
    e["XDG_STATE_HOME"] = str(tmp_path / "state")
    return e


def hook(ev, env, *args, rc=0, **knobs):
    """The hook as Claude Code runs it under the SDK or `claude -p`: its own session, no controlling
    terminal (hooks.md), stdin a pipe, stdout and stderr pipes."""
    p = subprocess.run([sys.executable, str(GUARD), *args], input=json.dumps(ev), capture_output=True,
                       text=True, env=dict(env, **knobs), timeout=60, start_new_session=True)
    assert p.returncode == rc, p.stderr
    return json.loads(p.stdout)["hookSpecificOutput"] if p.stdout.strip() else None


def sid():
    return "s-" + uuid.uuid4().hex[:8]


def agent_call(s, child, **ti):
    return {"session_id": s, "hook_event_name": "PreToolUse", "tool_name": "Agent", "prompt_id": "p1",
            "tool_use_id": "tu-" + uuid.uuid4().hex[:8], "agent_type": "blackcat", "cwd": "/tmp",
            "permission_mode": "bypassPermissions", "transcript_path": "/nonexistent.jsonl",
            "tool_input": dict({"subagent_type": child, "prompt": "do it"}, **ti)}


def strip_clock(out):
    return json.loads(re.sub(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}", "<t>", json.dumps(out)))


# ---------------------------------------------------------------- B: hooks without a TTY, SDK events
@pytest.mark.parametrize("entry", [SDK_ENV, {"CLAUDE_CODE_ENTRYPOINT": "sdk-cli"}, {}])
def test_label_background_ledger_and_start_are_the_same_under_every_entrypoint(env, entry):
    s = sid()
    pre = agent_call(s, "orchestrator", description="ship it", run_in_background=False)
    ui = hook(pre, env, **entry)["updatedInput"]
    assert ui["description"] == "orchestrator: ship it" and "run_in_background" not in ui
    post = dict(pre, hook_event_name="PostToolUse", tool_input=ui,
                tool_response={"agentId": "c1", "status": "async_launched"})
    hint = hook(post, env, **entry)
    assert hint["additionalContext"].startswith("Delegation ledger (live, hook-written): ")
    ledger = Path(env["XDG_STATE_HOME"]) / "claude-agent-stack" / s / "delegations.md"
    assert '- orchestrator · "ship it" · running' in ledger.read_text()
    start = {"session_id": s, "hook_event_name": "SubagentStart", "agent_id": "c1",
             "agent_type": "orchestrator", "cwd": "/tmp"}
    assert strip_clock(hook(start, env, **entry)) == {
        "hookEventName": "SubagentStart", "additionalContext": "Started <t> (local)."}


def test_no_push_and_session_start_need_no_terminal(env):
    ev = {"session_id": sid(), "hook_event_name": "PreToolUse", "tool_name": "Bash", "agent_id": "a1",
          "agent_type": "coder", "tool_input": {"command": "git push origin main"}}
    p = subprocess.run([sys.executable, str(GUARD), "no-push"], input=json.dumps(ev), text=True,
                       capture_output=True, env=dict(env, **SDK_ENV), start_new_session=True, timeout=60)
    assert '"permissionDecision": "deny"' in p.stdout, (p.stdout, p.stderr)
    for src in ("startup", "resume", "clear", "compact", "fork"):
        assert hook({"session_id": sid(), "hook_event_name": "SessionStart", "source": src}, env,
                    **SDK_ENV) is None                     # default: no output, prompt unchanged


# ---------------------------------------------------------------- C: the opt-in JSON report line
def test_json_line_reaches_main_thread_on_every_source_and_stack_agents(env):
    for src in ("startup", "resume", "clear", "compact", "fork"):
        out = hook({"session_id": sid(), "hook_event_name": "SessionStart", "source": src}, env,
                   STACK_REPORT_FORMAT="json")
        assert out == {"hookEventName": "SessionStart", "additionalContext": guard.REPORT_JSON_LINE}
    start = {"session_id": sid(), "hook_event_name": "SubagentStart", "agent_id": "a1",
             "agent_type": "coder"}
    ctx = hook(start, env, STACK_REPORT_FORMAT="JSON")["additionalContext"].splitlines()
    assert re.fullmatch(r"Started \S+ \S+ \(local\)\.", ctx[0]) and ctx[1:] == [guard.REPORT_JSON_LINE]
    assert hook(start, env, STACK_REPORT_FORMAT="json", STACK_AGENT_STARTED="0")[
        "additionalContext"] == guard.REPORT_JSON_LINE
    assert hook(dict(start, agent_type="plugin:x"), env, STACK_REPORT_FORMAT="json") is None
    assert hook(start, env, STACK_REPORT_FORMAT="text")["additionalContext"].count("\n") == 0
    assert len(guard.REPORT_JSON_LINE) <= 400


def test_session_start_bookkeeping_still_runs_in_json_mode(env):
    s = sid()
    d = Path(env["XDG_STATE_HOME"]) / "claude-agent-stack" / s
    d.mkdir(parents=True)
    (d / "screen.lock").write_text('{"holder": "x"}')
    hook({"session_id": s, "hook_event_name": "SessionStart", "source": "startup"}, env,
         STACK_REPORT_FORMAT="json")
    assert not (d / "screen.lock").exists()


def test_json_line_schema_is_what_the_parser_reads():
    example = re.search(r"(\{.*\})", guard.REPORT_JSON_LINE).group(1)
    keys = re.findall(r'"(\w+)":', example)
    assert keys == ["input", "timestamp", "agent", "status", "eflag", "result", "evidence", "files", "next"]
    assert set(keys) | {"format"} == set(sdk.parse_report("").keys())


# ---------------------------------------------------------------- the parser
def test_parse_clean_finish():
    r = sdk.parse_report("Fix the parser crash · 2026-10-02 14:05 · coder\nFixed in src/p.py; 41 tests pass.")
    assert r == {"format": "clean", "input": "Fix the parser crash", "timestamp": "2026-10-02 14:05",
                 "agent": "coder", "status": "done", "eflag": None,
                 "result": "Fixed in src/p.py; 41 tests pass.", "evidence": None, "files": [], "next": None}
    r = sdk.parse_report("**Review diff · 2026-10-02 · code-reviewer**\nVERDICT: pass — ran: pytest")
    assert (r["format"], r["timestamp"], r["agent"], r["result"]) == (
        "clean", "2026-10-02", "code-reviewer", "VERDICT: pass — ran: pytest")


def test_parse_status_block_multiline_and_fenced():
    text = ("```\nSTATUS: partial\nRESULT: built the CLI\n  two of three commands\nEVIDENCE: "
            "`pytest -q` 2 failed\nFILES: src/a.py, src/b.py\nNEXT: verifier\n```")
    r = sdk.parse_report(text)
    assert r["format"] == "status" and r["status"] == "partial"
    assert r["result"] == "built the CLI\ntwo of three commands"
    assert r["files"] == ["src/a.py", "src/b.py"] and r["next"] == "verifier"
    assert sdk.parse_report("STATUS: done | partial | blocked\nRESULT: x\nFILES: none")["files"] == []


def test_parse_json_last_line_wins_and_text_fallback():
    line = json.dumps({"input": "t", "timestamp": "2026-10-02 09:00", "agent": "scout",
                       "status": "done", "result": "uv 0.9", "evidence": "", "files": "a.md",
                       "next": ""})
    r = sdk.parse_report("noise {not json}\n" + line)
    assert r["format"] == "json" and r["agent"] == "scout" and r["files"] == ["a.md"]
    r = sdk.parse_report("Just prose, no format.")
    assert r["format"] == "text" and r["status"] is None and r["result"] == "Just prose, no format."


# ---------------------------------------------------------------- the helper
def test_run_collects_result_and_per_subagent_usage(monkeypatch):
    def msg(name, **kw):
        return type(name, (), kw)()

    async def query(prompt, options):
        yield msg("SystemMessage", subtype="init", data={})
        yield msg("TaskStartedMessage", task_id="t1", tool_use_id="tu1", description="coder: fix it",
                  status=None, usage=None)
        yield msg("TaskNotificationMessage", task_id="t1", tool_use_id="tu1", description=None,
                  status="completed", usage={"total_tokens": 1200, "tool_uses": 3, "duration_ms": 900})
        yield msg("ResultMessage", result="fix it · 2026-10-02 10:00 · blackcat\ndone", session_id="S1",
                  subtype="success", is_error=False, num_turns=2, duration_ms=1500, total_cost_usd=0.01,
                  usage={"input_tokens": 5}, model_usage={"model-x": {"inputTokens": 9}})

    monkeypatch.setitem(sys.modules, "claude_agent_sdk", types.SimpleNamespace(query=query))
    monkeypatch.setenv("XDG_STATE_HOME", "/st")
    out = asyncio.run(sdk.run("fix it", None))
    assert out["report"]["agent"] == "blackcat" and out["session_id"] == "S1"
    assert out["agents"] == [{"task_id": "t1", "description": "coder: fix it", "status": "completed",
                              "usage": {"total_tokens": 1200, "tool_uses": 3, "duration_ms": 900},
                              "tool_use_id": "tu1", "agent": "coder"}]
    assert out["ledger"] == "/st/claude-agent-stack/S1/delegations.md"
    assert out["model_usage"]["model-x"]["inputTokens"] == 9


def test_run_names_agents_only_from_labels_and_takes_task_updated_status(monkeypatch):
    def msg(name, **kw):
        return type(name, (), kw)()

    async def query(prompt, options):
        yield msg("TaskStartedMessage", task_id="t1", tool_use_id="tu1", description="fix it",
                  task_type="local_agent")                      # STACK_AGENT_LABEL=off: no type
        yield msg("TaskStartedMessage", task_id="t2", tool_use_id="tu2", description="scout",
                  task_type="local_agent")                      # a bare type
        yield msg("TaskStartedMessage", task_id="t3", tool_use_id="tu3", description="build",
                  task_type="local_bash")
        yield msg("TaskUpdatedMessage", task_id="t2", patch={"status": "killed"}, status=None)
        yield msg("ResultMessage", result="x", session_id="S", subtype="success", is_error=False,
                  num_turns=1, duration_ms=1, total_cost_usd=0, usage={}, model_usage={})

    monkeypatch.setitem(sys.modules, "claude_agent_sdk", types.SimpleNamespace(query=query))
    got = {a["tool_use_id"]: a for a in asyncio.run(sdk.run("x", None))["agents"]}
    assert set(got) == {"tu1", "tu2", "tu3"}                      # the update joined its tool_use_id
    assert (got["tu1"]["agent"], got["tu2"]["agent"], got["tu3"]["agent"]) == (None, "scout", None)
    assert got["tu2"]["status"] == "killed" and "status" not in got["tu1"]


def test_options_with_the_pinned_sdk():
    pytest.importorskip("claude_agent_sdk")
    o = sdk.options("coder", max_turns=5, budget_usd=0.5, allowed_tools=["Read"],
                    permission_mode="dontAsk", json_reports=True, model="sonnet")
    assert o.setting_sources == ["user", "project", "local"] and o.extra_args == {"agent": "coder"}
    assert o.system_prompt == {"type": "preset", "preset": "claude_code",
                               "exclude_dynamic_sections": True}
    assert (o.max_turns, o.max_budget_usd, o.allowed_tools, o.permission_mode, o.model) == (
        5, 0.5, ["Read"], "dontAsk", "sonnet")
    assert o.env == {"STACK_REPORT_FORMAT": "json"} and o.agents is None   # no programmatic agents
    assert sdk.options(None, json_reports=False).extra_args == {}
    o = sdk.options("scout", json_reports=True, env={"A": "1"}, extra_args={"debug": None},
                    system_prompt="custom")               # merged, and any field can be overridden
    assert o.env == {"A": "1", "STACK_REPORT_FORMAT": "json"}
    assert o.extra_args == {"debug": None, "agent": "scout"} and o.system_prompt == "custom"


def test_helper_is_small_pinned_installed_and_never_loaded():
    text = HELPER.read_text()
    # 135: the hand-back protocol's FILES forms (files_of) and E flag; still one small file
    assert len(text.splitlines()) <= 135 and os.access(HELPER, os.X_OK)
    pin = re.search(r'"claude-agent-sdk==([\d.]+)"', text)
    assert pin, "the PEP 723 header pins the SDK"
    install = (ROOT / "install.sh").read_text()
    assert install.count("stack_sdk.py") >= 2               # staged and tracked in the manifest
    for p in [DOT / "settings.json", *DOT.glob("agents/*.md"), *DOT.glob("rules/*.md"),
              *DOT.glob("skills/*/SKILL.md")]:
        if p.name == "SKILL.md" and p.parent.name == "claude-code-extensions":
            continue                                      # its one-line pointer to the reference
        assert "stack_sdk" not in p.read_text(encoding="utf-8"), p
