"""Differential proof for behaviour-neutral refactors of dot-config/dot-claude/bin/stack_sdk.py.

The helper at a base revision (`git show <base>:<path>` into a temp dir: no checkout of the base, nothing imported from
the repository's own paths) and the working copy (or --new PATH) run the same grid, one case at a time under the same
os.environ, and must give the same result: an order-sensitive snapshot (options fields, result dicts, rows, session
state) or the same exception type and message. Paths under the fixture root, memory addresses and the two module
names are normalised; first_message_s (a clock reading) is dropped.

Grid: Session() for hosts none, tty and callable x permission modes, settings overlays (every policy key, '{}', {},
files, bad JSON, NaN, non-objects), sources, env refusals (the caller's env and os.environ), the bg-wait ceiling,
extra_args (keys and values), refused keywords, output_format, cli, deadline and config_dir forms, with check(),
preview(), build(True), build(False) and a ProbeSession-style build() override; options(); the pure functions
(parse_report, files_of, wire, Reducer and parse_stream over every fixture prefix, write_row, stack_agents,
project_agent_files, session_start_hooks, policy_overlay, keep_rules, ask_callable, clean_text, resolve_cli,
exit_code, main()); connect() and ask() through a fake ClaudeSDKClient (server_info shapes, mode drift, the plan
gate's agent checks at connect and before each prompt, SessionStart frames, the guard's marker, end-of-run paths).

A runner, not a collected test: it pins the base revision's behaviour, so any intended change would fail it.

  uv run --no-project --python 3.13 --with claude-agent-sdk==0.2.163 python tests/sdk_differential.py
      [--base REF (default 7446f631)] [--new PATH] [-v]
Exit 0 iff every case matches; 1 if any differs (each listed); 2 if the base revision cannot be read.
"""
from __future__ import annotations

import argparse
import asyncio
import contextlib
import copy
import dataclasses
import importlib.util
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent
REL = "dot-config/dot-claude/bin/stack_sdk.py"
FIX = REPO / "tests" / "fixtures"
CEILING = "CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS"
SCRUB = re.compile(r"CLAUDE_BG_\w*|CLAUDE_CODE_SESSION_KIND|CLAUDE_CODE_SANDBOXED|CLAUDE_RELAUNCH_\w*|CLAUDE_CONFIG_DIR"
                   r"|XDG_STATE_HOME|" + CEILING + r"|STACK_\w*", re.IGNORECASE)
CLEAN_ENV = {k: v for k, v in os.environ.items() if not SCRUB.fullmatch(k)}
ROOTS: list[str] = []
SCEN: dict[str, Any] = {}
Case = tuple[str, Callable[[Any], Any], dict[str, str | None]]


# ---------------------------------------------------------------- snapshots
def norm(s: str) -> str:
    for r in ROOTS:
        s = s.replace(r, "<T>")
    return re.sub(r"0x[0-9a-fA-F]+", "0x?", re.sub(r"stack_sdk_(?:old|new)", "stack_sdk", s))


def snap(v: Any) -> Any:
    if dataclasses.is_dataclass(v) and not isinstance(v, type):
        return ["dc", type(v).__name__, [[f.name, snap(getattr(v, f.name))] for f in dataclasses.fields(v)]]
    if isinstance(v, dict):
        return ["dict", [[snap(k), snap(x)] for k, x in v.items()]]
    if isinstance(v, (set, frozenset)):
        return ["set", sorted(json.dumps(snap(x)) for x in v)]
    if isinstance(v, (list, tuple)):
        return [type(v).__name__, [snap(x) for x in v]]
    if isinstance(v, str):
        return norm(v)
    if isinstance(v, bytes):
        return ["bytes", norm(v.decode("utf-8", "replace"))]
    if v is None or isinstance(v, (bool, int)):
        return v
    if isinstance(v, float):
        return ["float", repr(v)]
    if callable(v):
        return ["callable", norm(getattr(v, "__qualname__", type(v).__name__))]
    return ["obj", type(v).__name__]


def attempt(fn: Callable[[], Any]) -> Any:
    try:
        return ["ok", snap(fn())]
    except SystemExit as e:
        return ["exit", e.code]
    except Exception as e:  # noqa: BLE001 - the type and message are the result
        return ["raise", type(e).__name__, norm(str(e))]


@contextlib.contextmanager
def environ(over: dict[str, str | None]):
    saved = dict(os.environ)
    os.environ.clear()
    os.environ.update(CLEAN_ENV, PATH=ROOTS[-1] + "/bin")
    for k, v in over.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
    try:
        yield
    finally:
        os.environ.clear()
        os.environ.update(saved)


def load(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, str(path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.GRACE_S, mod.INTERRUPT_S = 0.05, 1.0
    return mod


# ---------------------------------------------------------------- fixture tree
AGENTS = {"blackcat": None, "explore": None, "planner": "plan", "scout": "default", "coder": "acceptEdits",
          "newbie": "acceptEdits", "odd": "", "quoted": "'plan'  # ok"}
HOOKS = {"hooks": {"SessionStart": [{"matcher": "startup|resume|clear|compact|fork", "hooks": [{"type": "command"}]},
                                    {"hooks": [{"type": "command"}]}]}}


def tree(t: Path) -> None:
    def w(rel: str, text: str = "x") -> None:
        p = t / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    (t / ".git").mkdir()                                  # every walk stops at the fixture root
    for name, pm in AGENTS.items():
        w(f"config/agents/{name}.md", f"---\nname: {name}\ndescription: x\n"
          + ("" if pm is None else f"permissionMode: {pm}\n") + "---\nbody\n")
    w("config/settings.json", json.dumps(HOOKS))
    w("config_bad/agents/good.md", "---\nname: good\n---\n")
    w("config_bad/agents/broken.md", "no frontmatter")
    (t / "config_empty").mkdir()
    w("config_crlf/agents/a.md", "---\r\n'name': a\r\npermissionMode: \"acceptEdits\" # c\r\n---\r\n")
    for d in ("home", "late", "proj/sub", "adddir_empty"):
        (t / d).mkdir(parents=True, exist_ok=True)
    (t / "proj" / ".git").mkdir()
    w("proj/.claude/agents/x.md")
    w("projfile/.claude/agents")                          # a file, not a directory
    w("adddir/.claude/agents/y.md")
    w("adddir/deep/.claude/agents/z.md")
    w("wt/.git", "gitdir: ../main/.git/worktrees/wt\n")
    w("main/.git/worktrees/wt/commondir", "../..\n")
    w("main/.claude/agents/m.md")
    w("wt_broken/.git", "garbage\n")
    (t / "sym" / ".claude").mkdir(parents=True)
    (t / "sym" / ".claude" / "agents").symlink_to(t / "config" / "agents")
    (t / "sym" / ".git").mkdir()
    w("overlay_ok.json", '{"model": "x", "env": {"A": "1"}}')
    w("overlay_policy.json", '{"permissions": {"allow": ["Bash"]}}')
    w("overlay_text.json", "not json")
    w("bin/claude", "#!/bin/sh\n")
    (t / "bin" / "claude").chmod(0o755)
    w("bin/notexec", "#!/bin/sh\n")
    (t / "emptybin").mkdir()
    (t / "statefile").write_text("a file where the state root should be")
    for i, s in enumerate(SETTINGS_FILES):
        w(f"ssh/{i}/settings.json", s)
    w("ssh/bin/settings.json", "")
    (t / "ssh" / "bin" / "settings.json").write_bytes(b"\xff\xfe{")


SETTINGS_FILES = [json.dumps(HOOKS), "{}", "[]", "null", "not json", '{"hooks": []}', '{"hooks": {"SessionStart": {}}}',
                  '{"hooks": {"SessionStart": [{"matcher": "("}]}}',
                  '{"hooks": {"SessionStart": [{"matcher": "startup", "hooks": 5}]}}',
                  '{"hooks": {"SessionStart": [{"matcher": 5, "hooks": [1]}, {"matcher": "*", "hooks": [1, 2]}]}}',
                  '{"hooks": {"SessionStart": [{"matcher": "", "hooks": "abc"}, "x", {"matcher": null, "hooks": null}]}}',
                  '{"hooks": {"SessionStart": [{"matcher": "resume|fork", "hooks": [1]}]}}',
                  '{"hooks": null}', '"str"', "5"]


def app_host(tool: str, inp: Any, ctx: Any) -> None:
    return None


class FakeTty:
    def close(self) -> None:
        pass

    async def __call__(self, tool: str, inp: Any, ctx: Any) -> None:
        return None


# ---------------------------------------------------------------- Session() grid
def overlays(t: Path) -> list[Any]:
    policy = ("hooks", "disableAllHooks", "permissions", "defaultMode", "sandbox", "useAutoModeDuringPlan")
    return [None, "{}", {}, '{"model": "x"}', {"model": "x"}, '  {"a": 1}', "[1]", "null", "", " ", "5", '{"a": NaN}',
            {"a": float("nan")}, {"a": float("inf")}, 5, ["x"], {"a": object()}, '{"a": 1} x', '{"env": {"A": "1"}}',
            *({k: False} for k in policy), *(json.dumps({k: {}}) for k in policy), {"Hooks": 1}, {"nested": {"hooks": 1}},
            str(t / "overlay_ok.json"), str(t / "overlay_policy.json"), str(t / "overlay_text.json"),
            str(t / "missing.json"), t / "overlay_ok.json"]


def session_variants(t: Path) -> list[tuple[str, str | None, Callable[[], dict[str, Any]], dict[str, str | None]]]:
    st = str(t / "state")
    v: list[tuple[str, str | None, Callable[[], dict[str, Any]], dict[str, str | None]]] = []

    def add(label: str, mk: Callable[[], dict[str, Any]], agent: str | None = "blackcat", **env: str | None) -> None:
        v.append((label, agent, mk, env))
    add("base", dict)
    for pm in (None, "plan", "default", "acceptEdits", "dontAsk", "auto", "bypassPermissions"):
        add(f"mode={pm}", lambda pm=pm: {"permission_mode": pm})
    for i, o in enumerate(overlays(t)):
        add(f"settings#{i}", lambda o=o: {"settings": o})
        add(f"settings#{i} mode=default", lambda o=o: {"settings": o, "permission_mode": "default"})
    for src in [("user", "project", "local"), ("project",), ["user"], (), "user", ("local", "user"), ["USER"]]:
        add(f"sources={src!r}", lambda src=src: {"sources": src})
        add(f"sources={src!r} overlay", lambda src=src: {"sources": src, "settings": '{"model": "x"}'})
    envs = [{"CLAUDE_BG_X": "1"}, {"CLAUDE_BG_": "1"}, {"CLAUDE_CODE_SESSION_KIND": ""}, {"CLAUDE_CODE_SANDBOXED": "1"},
            {"CLAUDE_RELAUNCH_SESSION_ADD_DIRS": "x"}, {"claude_bg_x": "1"}, {"MY_CLAUDE_BG_X": "1"},
            {"CLAUDE_CODE_SESSION_KIND_X": "1"}, {"CLAUDE_CODE_SESSION_ID": "x"}, {5: "x"},
            {"CLAUDE_BG_A": "1", "CLAUDE_RELAUNCH_B": "2", "OK": "3"}, {CEILING: "0"}, {CEILING: "-1"}, {CEILING: "abc"},
            {CEILING: "5000"}, {CEILING: " 7 "}, {CEILING: 7}, {CEILING: "07"}, {CEILING: ""}, {CEILING: None},
            {"CLAUDE_CODE_EMIT_SESSION_STATE_EVENTS": "0"}, {"CLAUDE_CONFIG_DIR": str(t / "other")},
            {"CLAUDE_CONFIG_DIR": str(t / "config")}, {"STACK_REPORT_FORMAT": "json"}]
    for i, e in enumerate(envs):
        add(f"env#{i}", lambda e=e: {"env": dict(e, XDG_STATE_HOME=st)})
    add("env None", lambda: {"env": None})
    add("os ceiling 0", dict, **{CEILING: "0"})
    add("os ceiling 100", dict, **{CEILING: "100"})
    add("os ceiling x, env ceiling 5", lambda: {"env": {CEILING: "5", "XDG_STATE_HOME": st}}, **{CEILING: "x"})
    for i, os_env in enumerate([{"CLAUDE_BG_SESSION_PERMISSION_RULES": "x"}, {"CLAUDE_CODE_SESSION_KIND": "bg"},
                                {"CLAUDE_CODE_SANDBOXED": "1", "CLAUDE_RELAUNCH_X": "1"}, {"CLAUDE_BG": "1"},
                                {"CLAUDE_CONFIG_DIR": str(t / "config_bad")}]):
        add(f"os.environ#{i}", dict, **os_env)
        add(f"os.environ#{i} no config_dir", lambda: {"config_dir": None}, **os_env)
    extras = [{"debug": None}, {"debug": "api"}, {"verbose": None}, {"verbose": "x"}, {"verbose": ""}, {"model": "-x"},
              {"model": "m"}, {"permission-prompts": "none"}, {"--debug": None}, {"settings": "{}"}, {"name": 5},
              {"effort": "--x"}, {"agent": "x"}, {5: None}, {"fallback-model": "-"}, {"betas": "a,b"},
              {"debug-file": "/x"}, {"sandbox": None, "add-dir": "/", "model": "-m"}, None, {}]
    for i, x in enumerate(extras):
        add(f"extra_args#{i}", lambda x=x: {"extra_args": x})
    for k, val in (("hooks", {}), ("agents", {}), ("can_use_tool", app_host), ("permission_prompt_tool_name", "x"),
                   ("sandbox", {}), ("max_budget_usd", 1.0), ("setting_sources", ["user"])):
        add(f"refused {k}", lambda k=k, val=val: {k: val})
    add("refusals combined", lambda: {"hooks": {}, "sandbox": {}, "extra_args": {"settings": "x", "debug": "-x"},
                                      "env": {"CLAUDE_BG_X": "1"}, "permission_mode": "bypassPermissions"})
    add("refused + bad overlay", lambda: {"sandbox": {}, "settings": '{"hooks": {}}'})
    add("bypass + overlay", lambda: {"permission_mode": "bypassPermissions", "settings": "{}"})
    add("output_format agent", lambda: {"output_format": {"type": "json_schema"}})
    add("output_format no agent", lambda: {"output_format": {"type": "json_schema"}}, agent=None)
    add("output_format None", lambda: {"output_format": None})
    add("output_format + bad overlay", lambda: {"output_format": {"t": 1}, "settings": "[1]"})
    for d in (None, 0, -5, 12, 12.5, "10", True, float("nan")):
        add(f"deadline_s={d!r}", lambda d=d: {"deadline_s": d})
    for c in ("bundled", None, str(t / "bin" / "claude"), str(t / "bin" / "notexec"), str(t / "missing"),
              str(t / "bin"), ""):
        add(f"cli={norm(str(c))}", lambda c=c: {"cli": c})
    add("cli None, empty PATH", lambda: {"cli": None}, PATH=str(t / "emptybin"))
    add("budget None", lambda: {"budget_usd": None})
    add("budget 0", lambda: {"budget_usd": 0})
    add("budget True", lambda: {"budget_usd": True})
    add("budget '1'", lambda: {"budget_usd": "1"})
    add("config_dir conflict", lambda: {"env": {"CLAUDE_CONFIG_DIR": str(t / "x"), "XDG_STATE_HOME": st}})
    add("config_dir bad", lambda: {"config_dir": str(t / "config_bad")})
    add("config_dir empty", lambda: {"config_dir": str(t / "config_empty")})
    add("config_dir None env", lambda: {"config_dir": None, "env": {"CLAUDE_CONFIG_DIR": str(t / "config")}})
    add("config_dir crlf", lambda: {"config_dir": str(t / "config_crlf")})
    add("agent None", dict, agent=None)
    add("agent coder", dict, agent="coder")
    add("options fields", lambda: {"model": "m", "add_dirs": [str(t / "adddir")], "disallowed_tools": ["X", "Y"],
                                   "allowed_tools": ("Read",), "resume": "sid", "fork": True, "max_turns": 3,
                                   "continue_conversation": True, "json_reports": True, "strict_mcp_config": True,
                                   "system_prompt": "custom", "forward_subagent_text": True, "row": False})
    add("disallowed None", lambda: {"disallowed_tools": None})
    add("unknown field", lambda: {"bogus_field": 1})
    add("settings + disallowed", lambda: {"settings": {"model": "x"}, "disallowed_tools": ["Z"]})
    add("bg_wait/load", lambda: {"bg_wait_s": 1.5, "load_timeout_s": 0.25, "on_message": app_host})
    return v


HOSTS: dict[str, Callable[[], dict[str, Any]]] = {
    "none": lambda: {"host": "none"}, "tty": lambda: {"host": "tty", "tty": FakeTty()},
    "callable": lambda: {"host": app_host}, "bogus": lambda: {"host": "bogus"}, "5": lambda: {"host": 5}}


def session_case(t: Path, host: str, agent: str | None, mk: Callable[[], dict[str, Any]],
                 probe: bool = False) -> Callable[[Any], Any]:
    def fn(mod: Any) -> Any:
        kw = dict({"budget_usd": 0.5, "cli": "bundled", "config_dir": str(t / "config"), "cwd": str(t / "home"),
                   "env": {"XDG_STATE_HOME": str(t / "state")}}, **HOSTS[host]())
        kw.update(mk())
        if kw.get("config_dir") is None:
            kw.pop("config_dir")
        cls = mod.Session
        if probe:
            class ProbeSession(mod.Session):
                overlay = True

                def build(self, plan: bool) -> Any:
                    o = super().build(plan)
                    return dataclasses.replace(o, settings='{"sandbox": {"autoAllowBashIfSandboxed": false}}') \
                        if self.overlay else o
            cls = ProbeSession
        s = cls(agent, **kw)
        out = {"vars": {k: snap(x) for k, x in sorted(vars(s).items())}, "gate_waived": s.gate_waived,
               "client": snap(s.client), "check": attempt(s.check), "preview": attempt(s.preview)}
        out["agents"] = snap(s.agents)
        out["build_true"], out["build_false"] = attempt(lambda: s.build(True)), attempt(lambda: s.build(False))
        out["kw_after"] = snap(s.kw)
        s.close()
        return out
    return fn


# ---------------------------------------------------------------- pure functions
REPORTS = ["", "   ", None, "Just prose.", "Fix it · 2026-10-02 14:05 · coder\nDone.", "**R · 2026-10-02 · code-reviewer**",
           "STATUS: partial E: look\nRESULT: a\nb\nEVIDENCE: e\nFILES: a.py — x\n- b.py:3-4\nc.py (new), d.py\nNEXT: ASK USER: q",
           "STATUS: **Blocked**\nRESULT: r\nFILES: none\nNEXT: -", "x\n" + json.dumps({"status": "done", "result": "r",
                                                                                   "files": "one.py", "agent": "a"}),
           "```\n" + json.dumps({"status": "failed", "result": 1, "files": [1, "b"]}) + "\n```", "{not json}\nSTATUS: done",
           "STATUS:\nRESULT: empty status", "FILES: a\nSTATUS: done\nFILES: 1. x.py\n2) y.py — z\n* `w.py`\n+ n/a"]


class ToolUseBlock:
    def __init__(self, i: str, n: str) -> None:
        self.id, self.name = i, n


def fake(kind: str, **attrs: Any) -> Any:
    return type(kind, (), {})() if not attrs else type(kind, (), attrs)()


WIRE = [{"type": "x"}, fake("ResultMessage", subtype="success", is_error=False, result="r", session_id="s",
                             model_usage={"m": {}}, usage={"a": 1}, origin=None),
        fake("SystemMessage", subtype="init", data={"type": "system", "subtype": "init", "x": 1}),
        fake("SystemMessage", subtype="weird", data={"a": 1}, session_id="s"),
        fake("TaskStartedMessage", task_id="t", tool_use_id="u", description="coder: x", task_type="local_agent",
             data={}, session_id="s", status=None),
        fake("TaskUpdatedMessage", task_id="t", patch={"status": "completed"}, data=None),
        fake("HookEventMessage", subtype="hook_response", hook_event_name="SessionStart", data={"hook_id": "h"}),
        fake("AssistantMessage", parent_tool_use_id="p", content=[ToolUseBlock("tu", "Agent"), "text"]),
        fake("AssistantMessage", content=None),
        fake("RateLimitEvent", rate_limit_info=fake("I", raw={"status": "allowed"})),
        fake("RateLimitEvent", rate_limit_info=fake("I", raw=None, status="rejected", rate_limit_type="5h")),
        fake("UserMessage"), fake("StreamEvent"), fake("Mystery")]

TASKS = [
    {"type": "system", "subtype": "init", "permissionMode": "plan", "claude_code_version": "2.1", "session_id": "s0"},
    {"type": "system", "subtype": "task_started", "task_id": "t1", "tool_use_id": "tu1", "description": "coder: fix",
     "task_type": "local_agent", "session_id": "s1"},
    {"type": "system", "subtype": "task_progress", "task_id": "t1", "description": "scout: later", "usage": {"n": 5}},
    {"type": "system", "subtype": "task_updated", "task_id": "t1", "patch": {"status": "running", "usage": {"n": 9}}},
    {"type": "system", "subtype": "task_started", "task_id": "t2", "description": "scout", "task_type": "local_agent"},
    {"type": "system", "subtype": "task_started", "task_id": "t3", "description": "Run", "task_type": "local_bash"},
    {"type": "system", "subtype": "task_started", "task_id": "t4", "description": "wf: x", "task_type": "local_workflow"},
    {"type": "system", "subtype": "task_updated", "task_id": "t2", "patch": "not a dict"},
    {"type": "system", "subtype": "task_started", "tool_use_id": "tu9"},
    {"type": "assistant", "parent_tool_use_id": None, "message": {"content": [{"type": "tool_use", "id": "tu1",
                                                                                "name": "Agent"}, "junk"]}},
    {"type": "assistant", "parent_tool_use_id": "tu1", "message": {"content": [{"type": "tool_use", "id": "tu2",
                                                                                 "name": "Task"}]}},
    {"type": "system", "subtype": "task_started", "task_id": "t6", "tool_use_id": "tu2", "description": "explore",
     "task_type": "local_agent"},
    {"type": "system", "subtype": "task_notification", "task_id": "t1", "status": "completed"},
    {"type": "system", "subtype": "task_updated", "task_id": "t4", "patch": {"status": "killed"}},
    {"type": "system", "subtype": "task_progress", "task_id": "t5", "description": "", "task_type": "local_agent"},
    {"type": "system", "subtype": "task_progress", "task_id": "t5", "description": "explore: late", "status": "failed"},
    {"type": "system", "subtype": "task_updated", "task_id": "t2", "tool_use_id": "tu7", "task_type": "local_bash",
     "usage": {"n": 1}},
    {"type": "rate_limit_event", "rate_limit_info": {"status": "allowed", "rateLimitType": "five_hour"}},
    {"type": "rate_limit_event", "rate_limit_info": {"status": "rejected"}},
    {"type": "rate_limit_event"},
    {"type": "system", "subtype": "hook_started", "hook_event": "SessionStart"},
    {"type": "system", "subtype": "hook_response", "hook_name": "Stop"},
    {"type": "system", "subtype": "session_state_changed", "state": "running"},
    {"type": "result", "subtype": "success", "result": "STATUS: blocked\nRESULT: r\nNEXT: ASK USER: q", "session_id": "s2",
     "modelUsage": {"m": {"inputTokens": 3, "outputTokens": True, "cacheReadInputTokens": 2.5}, "n": "x"},
     "permission_denials": [{"tool_name": "Bash", "tool_use_id": "x"}, {"tool_name": "B", "tool_use_id": "x"}, "j"],
     "origin": {"kind": "task-notification"}, "terminal_reason": "completed", "total_cost_usd": 0.5},
    {"type": "system", "subtype": "session_state_changed", "state": "idle"},
    {"type": "result", "subtype": "error_max_budget_usd", "is_error": True, "result": 5, "origin": {"kind": 5}},
]


def stream_inputs() -> list[tuple[str, list[Any]]]:
    out = []
    for p in sorted((FIX / "sdk").glob("*.jsonl")):
        lines = p.read_text().splitlines()
        out += [(f"{p.name}[:{k}]", lines[:k]) for k in range(len(lines) + 1)]
        out.append((f"{p.name} bytes", [ln.encode() for ln in lines] + [b"", b"  ", b"{bad", b"[1]"]))
    out += [(f"TASKS[:{k}]", TASKS[:k]) for k in range(len(TASKS) + 1)]
    return out


def reducer_steps(mod: Any, frames: list[Any]) -> Any:
    r, steps = mod.Reducer(), []
    for f in frames:
        r.feed(f)
        steps.append(r.inflight())
    out = r.summary(host="none", ended_by="result", env={"XDG_STATE_HOME": ROOTS[-1] + "/state"})
    out.pop("first_message_s")
    return steps, out, r.state, r.sid


def keep_rules_inputs() -> list[Any]:
    from claude_agent_sdk.types import PermissionRuleValue, PermissionUpdate
    rv = PermissionRuleValue
    return [None, [], "x", [None], ["str"], [5],
            [{"type": "addRules", "destination": "session", "behavior": "allow",
              "rules": [{"toolName": "Bash", "ruleContent": "ls"}, {"toolName": "Read"}, {"toolName": "Bash",
                                                                                         "ruleContent": 5}, "j", None]}],
            [{"type": "addRules", "destination": "userSettings", "behavior": "allow", "rules": [{"toolName": "Bash"}]}],
            [{"type": "addRules", "destination": "session", "behavior": "nope", "rules": [{"toolName": "Bash"}]}],
            [{"type": "setMode", "destination": "session", "behavior": "allow", "mode": "bypassPermissions"}],
            [{"type": "addRules", "destination": "session", "behavior": "deny", "rules": None}],
            [{"type": "addRules", "destination": "session", "behavior": "ask", "rules": [{"toolName": "Read"}]}],
            [PermissionUpdate(type="addRules", destination="session", behavior="ask",
                              rules=[rv(tool_name="Bash", rule_content="x"), rv(tool_name="Read", rule_content=None),
                                     {"toolName": "Bash", "ruleContent": "dict in obj"}])],
            [PermissionUpdate(type="addRules", destination="projectSettings", behavior="allow",
                              rules=[rv(tool_name="Bash", rule_content="x")])],
            [PermissionUpdate(type="removeRules", destination="session", behavior="allow",
                              rules=[rv(tool_name="Bash", rule_content="x")])],
            [{"type": "addRules", "destination": "session", "behavior": "allow",
              "rules": [rv(tool_name="Bash", rule_content="obj in dict"), rv(tool_name="Bash", rule_content=7)]},
             {"type": "addRules", "destination": "session", "behavior": "deny", "rules": [{"toolName": "Bash"}]}]]


def ask_callable_hosts() -> list[tuple[str, Any, str, Any]]:
    from claude_agent_sdk import PermissionResultAllow as A
    from claude_agent_sdk import PermissionResultDeny as D

    async def slow(*a: Any) -> Any:
        await asyncio.sleep(2)
        return A()

    async def asy(*a: Any) -> Any:
        return A(updated_input={"x": 1}, updated_permissions=keep_rules_inputs()[6])

    def boom(*a: Any) -> Any:
        raise RuntimeError("x")
    ask = {"questions": [{"question": "q"}], "answers": {"q": "model"}, "annotations": {"a": 1}}
    return [("allow", lambda *a: A(), "Bash", {"command": "ls"}),
            ("allow ui", lambda *a: A(updated_input={"command": "pwd"}), "Bash", {}),
            ("allow bad ui", lambda *a: A(updated_input=["x"]), "Bash", {}),
            ("allow perms", lambda *a: A(updated_permissions=keep_rules_inputs()[6]), "Bash", {}),
            ("allow foreign perms", lambda *a: A(updated_permissions=keep_rules_inputs()[7]), "Bash", {}),
            ("deny", lambda *a: D(message="m" * 3000, interrupt=1), "Bash", {}),
            ("none", lambda *a: None, "Bash", {}), ("dict", lambda *a: {"behavior": "allow"}, "Bash", {}),
            ("raise", boom, "Bash", {}), ("async", asy, "Bash", {}), ("timeout", slow, "Bash", {}),
            ("ask no answers", lambda *a: A(), "AskUserQuestion", ask),
            ("ask echo", lambda t, i, c: A(updated_input=i), "AskUserQuestion", ask),
            ("ask answered", lambda t, i, c: A(updated_input=dict(i, answers={"q": "u"})), "AskUserQuestion", ask),
            ("ask non-dict input", lambda t, i, c: A(updated_input={"answers": {"q": 1}}), "AskUserQuestion", "x")]


def main_argvs() -> list[list[str]]:
    return [[], ["x"], ["--budget-usd", "1"], ["--budget-usd", "0", "x"], ["--print-options"],
            ["--print-options", "--budget-usd", "1", "--agent", "coder", "--allowed-tools", "Read, Grep,,",
             "--disallowed-tools", "WebFetch", "--max-turns", "3", "--json-reports", "--resume", "sid", "--continue"],
            ["--print-options", "--permission-mode", "bypassPermissions"],
            ["--print-options", "--permission-mode", "default", "--deadline-s", "5", "--bg-wait-s", "2"],
            ["--print-options", "--cli", "bundled", "--subagent-text"], ["--print-options", "--cli", "/nope"],
            ["--host", "bogus"], ["--max-turns", "x"], ["--budget-usd", "1", "hello"],
            ["--budget-usd", "1", "--permission-mode", "default", "--stream", "hello"]]


def run_main(mod: Any, argv: list[str]) -> Any:
    o, e = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(o), contextlib.redirect_stderr(e):
        try:
            rc: Any = mod.main(argv)
        except SystemExit as x:
            rc = ["exit", x.code]
    lines = []
    for ln in o.getvalue().splitlines():
        with contextlib.suppress(ValueError):
            d = json.loads(ln)
            if isinstance(d, dict):
                d.pop("first_message_s", None)
                ln = json.dumps(d)
        lines.append(norm(ln))
    return rc, lines, norm(e.getvalue())


def pure_cases(t: Path) -> list[Case]:
    c: list[Case] = []

    def add(name: str, fn: Callable[[Any], Any], **env: str | None) -> None:
        c.append((name, fn, env))
    texts = REPORTS + [p.read_text() for p in sorted((FIX / "reports").glob("*.txt"))]
    for i, x in enumerate(texts):
        add(f"parse_report#{i}", lambda m, x=x: m.parse_report(x))
        add(f"files_of#{i}", lambda m, x=x: m.files_of(x or ""))
    for i, x in enumerate(WIRE):
        add(f"wire#{i}", lambda m, x=x: m.wire(x))
    for name, frames in stream_inputs():
        for host in (None, "none", "tty"):
            add(f"parse_stream {name} host={host}", lambda m, f=frames, h=host: {
                k: v for k, v in m.parse_stream(f, host=h).items() if k != "first_message_s"})
        if not name.endswith("bytes"):
            add(f"reducer {name}", lambda m, f=frames: reducer_steps(
                m, [json.loads(x) if isinstance(x, str) else x for x in f if not isinstance(x, str) or x.strip()]))
    for i, frames in enumerate([TASKS, (FIX / "sdk" / "stream_tree.jsonl").read_text().splitlines(), []]):
        def row(m: Any, frames: Any = frames, i: int = i) -> Any:
            st = t / "rows" / m.__name__ / str(i)
            out = m.parse_stream(frames)
            p = m.write_row(dict(out, host="none", agent="coder", entrypoint="sdk-py", sdk_version="0.2",
                                 cli_version="bad text!", cost_usd=float("nan"), num_turns=True), {"XDG_STATE_HOME": str(st)})
            got = [json.loads(x) for x in Path(p).read_text().splitlines()] if p else []
            mode = oct(os.stat(p).st_mode & 0o777) if p else None
            return p and p.replace(m.__name__, "M"), [{k: v for k, v in g.items() if k != "ts"} for g in got], mode
        add(f"write_row#{i}", row)
    add("write_row unwritable", lambda m: m.write_row({"outcome": "x"}, {"XDG_STATE_HOME": str(t / "statefile")}))
    add("write_row default env", lambda m: m.write_row({"outcome": "x"}, None),
        XDG_STATE_HOME=str(t / "rows_default"))
    for cfg in ("config", "config_bad", "config_empty", "config_crlf", "missing", "proj"):
        add(f"stack_agents {cfg}", lambda m, cfg=cfg: m.stack_agents(str(t / cfg)))
    cwds = ["home", "late", "proj", "proj/sub", "projfile", "wt", "wt_broken", "sym", "config", "adddir", "missing"]
    extras: list[Any] = [(), [str(t / "adddir")], ["../adddir"], [t / "adddir_empty"], [str(t / "adddir" / "deep")],
                         ("adddir", "proj")]
    for cwd in cwds:
        for i, ex in enumerate(extras):
            add(f"project_agent_files {cwd} extra#{i}", lambda m, cwd=cwd, ex=ex: m.project_agent_files(
                str(t / cwd), str(t / "config"), ex))
    add("project_agent_files cwd None", lambda m: m.project_agent_files(None, str(t / "config")))
    add("project_agent_files no extra arg", lambda m: m.project_agent_files(str(t / "proj"), str(t / "sym" / ".claude")))
    for d in [*map(str, range(len(SETTINGS_FILES))), "bin", "missing"]:
        for src in ("startup", "resume", "fork", "compact", ""):
            add(f"session_start_hooks {d} {src}", lambda m, d=d, src=src: m.session_start_hooks(str(t / "ssh" / d), src))
    for i, o in enumerate(overlays(t)):
        add(f"policy_overlay#{i}", lambda m, o=o: m.policy_overlay(o))
    for p in ("overlay_ok.json", "overlay_text.json", "missing", "bin"):
        add(f"read_json {p}", lambda m, p=p: m.read_json(str(t / p)))
    for cli in ("bundled", None, str(t / "bin" / "claude"), str(t / "bin" / "notexec"), str(t / "bin"), "", "rel"):
        add(f"resolve_cli {norm(str(cli))}", lambda m, cli=cli: m.resolve_cli(cli))
        add(f"resolve_cli {norm(str(cli))} empty PATH", lambda m, cli=cli: m.resolve_cli(cli), PATH=str(t / "emptybin"))
    for i, s in enumerate(["plain", "a\x1b[31mred\x07\x00", "bidi\u202e\u2066x\u2028", "tab\tnl\n", "x" * 50, 5, None]):
        for cap in (0, 3, 10, 100):
            add(f"clean_text#{i} cap={cap}", lambda m, s=s, cap=cap: (m.clean_text(s, cap), m.one_line(s, cap)))
    for i, u in enumerate(keep_rules_inputs()):
        for tool in ("Bash", "Read"):
            add(f"keep_rules#{i} {tool}", lambda m, u=u, tool=tool: m.keep_rules(u, tool))
    for name, host, tool, inp in ask_callable_hosts():
        add(f"ask_callable {name}", lambda m, h=host, tool=tool, inp=inp: asyncio.run(
            m.ask_callable(h, tool, inp, None, timeout_s=0.1)))
    for o in [{}, {"outcome": "done"}, {"outcome": "blocked"}, {"outcome": "blocked", "needs_user": True},
              {"outcome": "unknown", "gate": "plan"}, {"outcome": "partial", "gate": "ask"}, {"outcome": "error"}]:
        add(f"exit_code {o}", lambda m, o=o: m.exit_code(o))
    for task in [{}, {"description": "coder: x"}, {"description": "coder"}, {"description": "coder", "task_type":
                 "local_agent"}, {"description": "a b: c"}, {"description": None}, {"description": "x:y"}]:
        add(f"agent_of {task}", lambda m, task=task: m.agent_of(task))
    for env in (None, {}, {"XDG_STATE_HOME": "/s", "CLAUDE_CONFIG_DIR": "/c"}, {"XDG_STATE_HOME": ""}):
        add(f"roots {env}", lambda m, env=env: (m.state_root(env), m.config_root(env)))
        add(f"roots {env} os", lambda m, env=env: (m.state_root(env), m.config_root(env)),
            XDG_STATE_HOME="/os/s", CLAUDE_CONFIG_DIR="/os/c")
    add("TtyHost no terminal", lambda m: m.TtyHost(path=str(t / "missing-tty")))

    def quote(m: Any) -> Any:
        r, w = os.pipe()
        h = m.TtyHost(fds=(r, w), timeout_s=0.1)
        try:
            return [h.quote(x, cap) for x in ("a\tb\n" + "y" * 90, "", "\x1b]0;t\x07z") for cap in (5, 1000)]
        finally:
            h.close()
    add("TtyHost.quote", quote)
    for i, argv in enumerate(main_argvs()):
        add(f"main#{i} {' '.join(argv)}", lambda m, argv=argv, i=i: (reset(fresh(t, f"main{i}")), run_main(m, argv))[1],
            CLAUDE_CONFIG_DIR=str(t / "config"), XDG_STATE_HOME=str(t / f"state_main{i}"))
    return c


# ---------------------------------------------------------------- connect() and ask() on a fake client
def hooks(sid: str | None, outcome: str = "success", n: int = 2, answered: int | None = None) -> list[dict[str, Any]]:
    out = [{"type": "system", "subtype": "hook_started", "hook_id": f"h{i}", "hook_event": "SessionStart",
            "session_id": sid} for i in range(n)]
    out.insert(0, {"type": "system", "subtype": "hook_started", "hook_id": "o", "hook_event": "Other"})
    return out + [{"type": "system", "subtype": "hook_response", "hook_id": f"h{i}", "hook_name": "SessionStart:startup",
                   "outcome": outcome if i == 0 else "success", "session_id": sid}
                  for i in range(n if answered is None else answered)]


def reply(sid: str, text: str = "STATUS: done\nRESULT: ok", idle: bool = True, **res: Any) -> list[Any]:
    out: list[Any] = [{"type": "system", "subtype": "session_state_changed", "state": "running"}] * idle + [
                      {"type": "assistant", "parent_tool_use_id": None, "message": {"content": []}},
                      dict({"type": "result", "subtype": "success", "is_error": False, "num_turns": 1, "duration_ms": 9,
                            "result": text, "session_id": sid, "total_cost_usd": 0.01}, **res)]
    return out + ([{"type": "system", "subtype": "session_state_changed", "state": "idle"}] if idle else [])


def fresh(t: Path, key: str, **over: Any) -> dict[str, Any]:
    sid = over.pop("sid", "sess-fake")
    return dict({"sid": sid, "info": {"agents": [{"name": n} for n in AGENTS], "current_permission_mode": "plan"},
                 "frames": hooks(sid), "marker": {"source": "startup", "policy": True}, "replies": [reply(sid)],
                 "opened": [], "state": str(t / "state_conn" / key)}, **over)


def reset(sc: dict[str, Any]) -> None:
    SCEN.clear()
    SCEN.update(sc)


class FakeClient:
    """Stands in for claude_agent_sdk.ClaudeSDKClient: connect() writes the guard's marker and queues the scenario's
    SessionStart frames; query() queues the next reply; interrupt() an aborted result."""

    def __init__(self, opts: Any, transport: Any = None) -> None:
        self.opts, self.q = opts, asyncio.Queue()
        SCEN["opened"].append(opts)

    async def connect(self) -> None:
        if SCEN.get("connect_error"):
            raise RuntimeError("the CLI exited 1")
        mk = SCEN["marker"]
        st = (self.opts.env or {}).get("XDG_STATE_HOME") or os.environ["XDG_STATE_HOME"]
        p = Path(st) / "claude-agent-stack" / SCEN["sid"] / "session-start.json"
        if mk is not None:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps(dict({"v": 1, "ts": time.time()}, **mk)))
        for f in SCEN["frames"]:
            self.q.put_nowait(f)

    async def get_server_info(self) -> Any:
        return SCEN["info"]

    def receive_messages(self) -> Any:
        return self._gen()

    async def _gen(self) -> Any:
        while (m := await self.q.get()) is not None:
            if m == "RAISE":
                raise RuntimeError("the stream broke")
            yield m

    async def query(self, prompt: str) -> None:
        for f in (SCEN["replies"].pop(0) if SCEN["replies"] else []):
            self.q.put_nowait(f)

    async def interrupt(self) -> None:
        self.q.put_nowait({"type": "result", "subtype": "error_during_execution", "is_error": True,
                           "terminal_reason": "aborted_streaming", "session_id": SCEN["sid"]})

    async def disconnect(self) -> None:
        self.q.put_nowait(None)


def scenarios(t: Path) -> list[tuple[str, dict[str, Any], dict[str, Any], Callable[[], None] | None]]:
    s = "sess-fake"
    all_agents = [{"name": n} for n in AGENTS]

    many = [str(t / "late" / ".claude" / "many" / str(i)) for i in range(12)]

    def mk_late() -> None:
        (t / "late" / ".claude" / "agents").mkdir(parents=True, exist_ok=True)

    def mk_many() -> None:                                # twelve add_dirs gain agents after connect (N2's cut)
        for d in many:
            (Path(d) / ".claude" / "agents").mkdir(parents=True, exist_ok=True)
    return [
        ("N2 many add_dirs after connect", {}, {"cwd": str(t / "home"), "add_dirs": many}, mk_many),
        ("continue resume marker", {"marker": {"source": "resume", "policy": True}}, {"continue_conversation": True},
         None),
        ("ok", {}, {}, None),
        ("ok row", {}, {"row": True}, None),
        ("ok two asks", {"replies": [reply(s), reply(s, "second · 2026-10-10 · coder")]}, {"asks": 2}, None),
        ("tty host", {}, {"host": "tty", "tty": FakeTty()}, None),
        ("callable host", {}, {"host": app_host}, None),
        ("agent missing", {"info": {"agents": all_agents[1:], "current_permission_mode": "plan"}}, {}, None),
        ("agents as strings", {"info": {"agents": list(AGENTS), "current_permission_mode": "plan"}}, {}, None),
        ("agents garbage", {"info": {"agents": [5, None, {"name": 5}, {"x": 1}, *AGENTS, ["l"]],
                                     "current_permission_mode": "plan"}}, {}, None),
        ("agents unhashable name", {"info": {"agents": [*all_agents, {"name": ["rogue"]}],
                                             "current_permission_mode": "plan"}}, {}, None),
        ("agents unhashable name callable", {"info": {"agents": [*all_agents, {"name": {"k": 1}}],
                                                      "current_permission_mode": "plan"}}, {"host": app_host}, None),
        ("rogue + project agents", {"info": {"agents": [*all_agents, {"name": "rogue"}, {"name": "b-rogue"}],
                                             "current_permission_mode": "plan"}}, {"cwd": str(t / "proj")}, None),
        ("rogue + worktree + add_dir agents", {"info": {"agents": [*all_agents, {"name": "rogue"}],
                                                        "current_permission_mode": "plan"}},
         {"cwd": str(t / "wt"), "add_dirs": [str(t / "adddir")]}, None),
        ("agents a dict", {"info": {"agents": {n: 1 for n in AGENTS}, "current_permission_mode": "plan"}}, {}, None),
        ("info a list", {"info": [1]}, {}, None),
        ("info None", {"info": None}, {}, None),
        ("rogue agent", {"info": {"agents": [*all_agents, {"name": "rogue"}, "zz", {"name": "plug:x"}],
                                  "current_permission_mode": "plan"}}, {}, None),
        ("rogue agent callable", {"info": {"agents": [*all_agents, {"name": "rogue"}], "current_permission_mode": "plan"}},
         {"host": app_host}, None),
        ("rogue agent waived", {"info": {"agents": [*all_agents, {"name": "rogue"}], "current_permission_mode": "default"}},
         {"permission_mode": "default"}, None),
        ("many rogues", {"info": {"agents": [*all_agents, *({"name": f"r{i:02d}"} for i in range(14))],
                                  "current_permission_mode": "plan"}}, {"cwd": str(t / "proj")}, None),
        ("mode drift", {"info": {"agents": all_agents, "current_permission_mode": "default"}}, {}, None),
        ("mode None", {"info": {"agents": all_agents}}, {}, None),
        ("mode bypass", {"info": {"agents": all_agents, "current_permission_mode": "bypassPermissions"}},
         {"host": app_host}, None),
        ("waived", {"info": {"agents": all_agents, "current_permission_mode": "acceptEdits"}},
         {"permission_mode": "acceptEdits"}, None),
        ("project agents", {}, {"cwd": str(t / "proj" / "sub")}, None),
        ("worktree main agents", {}, {"cwd": str(t / "wt")}, None),
        ("add_dirs agents", {}, {"add_dirs": [str(t / "adddir")]}, None),
        ("add_dirs relative", {}, {"add_dirs": ["../adddir"]}, None),
        ("project agents callable", {}, {"cwd": str(t / "proj"), "host": app_host}, None),
        ("N2 agents after connect", {}, {"cwd": str(t / "late")}, mk_late),
        ("N2 waived", {"info": {"agents": all_agents, "current_permission_mode": "default"}},
         {"cwd": str(t / "late"), "permission_mode": "default"}, mk_late),
        ("hook error", {"frames": hooks(s, "error")}, {}, None),
        ("hooks unanswered", {"frames": hooks(s, answered=1)}, {"load_timeout_s": 0.3}, None),
        ("one hook only", {"frames": hooks(s, n=1)}, {"load_timeout_s": 0.3}, None),
        ("no session id", {"frames": hooks(None)}, {}, None),
        ("bad session id", {"frames": hooks("a/b")}, {}, None),
        ("marker missing", {"marker": None}, {}, None),
        ("marker stale", {"marker": {"ts": 0, "source": "startup", "policy": True}}, {}, None),
        ("marker ts bool", {"marker": {"ts": True, "source": "startup", "policy": True}}, {}, None),
        ("marker source", {"marker": {"source": "resume", "policy": True}}, {}, None),
        ("marker policy off", {"marker": {"source": "startup", "policy": "yes"}}, {}, None),
        ("resume", {"marker": {"source": "resume", "policy": True}}, {"resume": "sess-fake"}, None),
        ("fork", {"marker": {"source": "fork", "policy": True}}, {"resume": "sess-fake", "fork": True}, None),
        ("continue", {"marker": {"source": "startup", "policy": True}}, {"continue_conversation": True}, None),
        ("connect error", {"connect_error": True}, {}, None),
        ("no budget", {}, {"budget_usd": None}, None),
        ("os.environ channel", {}, {"_os": {"CLAUDE_BG_X": "1"}}, None),
        ("error result", {"replies": [reply(s, "x", is_error=True, subtype="error_during_execution")]}, {}, None),
        ("budget result", {"replies": [reply(s, "x", is_error=True, subtype="error_max_budget_usd")]}, {}, None),
        ("no idle (grace)", {"replies": [reply(s, idle=False)]}, {}, None),
        ("bg ceiling", {"replies": [[{"type": "system", "subtype": "task_started", "task_id": "t1", "task_type":
                                      "local_agent", "description": "coder: x"}, *reply(s, idle=False)]]},
         {"bg_wait_s": 0.2}, None),
        ("deadline", {"replies": [[]]}, {"deadline_s": 0.2}, None),
        ("eof", {"replies": [[None]]}, {}, None),
        ("eof after result", {"replies": [[*reply(s, idle=False)[:3], None]]}, {}, None),
        ("stream breaks", {"replies": [["RAISE"]]}, {}, None),
        ("crash after result", {"replies": [[*reply(s, idle=False), "RAISE"]]}, {}, None),
        ("plan text report", {"replies": [reply(s, "just prose")]}, {}, None),
        ("ask user", {"replies": [reply(s, "STATUS: blocked\nRESULT: r\nNEXT: ASK USER: which?")]}, {}, None),
    ]


def scenario_case(t: Path, i: int, over: dict[str, Any], kw: dict[str, Any],
                  between: Callable[[], None] | None) -> Callable[[Any], Any]:
    def fn(mod: Any) -> Any:
        sc = fresh(t, str(i), **copy.deepcopy(over))      # replies are consumed per run
        shutil.rmtree(sc["state"], ignore_errors=True)
        shutil.rmtree(t / "late" / ".claude", ignore_errors=True)
        reset(sc)
        k = dict(kw)
        asks, os_env = k.pop("asks", 1), k.pop("_os", {})
        k = dict({"budget_usd": 0.5, "cli": "bundled", "config_dir": str(t / "config"), "cwd": str(t / "home"),
                  "env": {"XDG_STATE_HOME": sc["state"]}, "load_timeout_s": 2.0, "row": False}, **k)
        os.environ.update(os_env)

        async def go() -> Any:
            s = mod.Session("blackcat", **k)
            res: dict[str, Any] = {}
            res["ask before connect"] = await aattempt(s.ask("too early"))
            res["connect"] = await aattempt(s.connect())
            if between:
                between()
            for n in range(asks):
                res[f"ask{n}"] = await aattempt(s.ask(f"prompt {n}"))
            await s.disconnect()
            s.close()
            res["opened"] = snap(SCEN["opened"])
            res["loaded"], res["agents"] = s.loaded, snap(s.agents)
            return res
        try:
            return asyncio.run(go())
        finally:
            shutil.rmtree(t / "late" / ".claude", ignore_errors=True)
    return fn


async def aattempt(coro: Any) -> Any:
    try:
        out = await coro
    except Exception as e:  # noqa: BLE001 - the type and message are the result
        return ["raise", type(e).__name__, norm(str(e))]
    if isinstance(out, dict):
        out = {k: v for k, v in out.items() if k != "first_message_s"}
    return ["ok", snap(out)]


# ---------------------------------------------------------------- the grid and the run
def cases(t: Path) -> list[Case]:
    out: list[Case] = []
    for label, agent, mk, env in session_variants(t):
        for host in ("none", "tty", "callable"):
            out.append((f"Session[{host}] {label}", session_case(t, host, agent, mk), env))
    for host in ("bogus", "5"):
        out.append((f"Session[{host}]", session_case(t, host, "blackcat", dict), {}))
    for label, agent, mk, env in session_variants(t)[:40]:
        out.append((f"ProbeSession {label}", session_case(t, "none", agent, mk, probe=True), env))
    opts = [((), {}), ((None,), {}), (("coder", 3, 0.5, ["Read", "Grep"], ["WebFetch"], None, "sess-1"), {"json_reports": True}),
            (("scout",), {"json_reports": True, "env": {"A": "1"}, "extra_args": {"debug": None}, "system_prompt": "c"}),
            (("x",), {"extra_args": {"agent": "y"}, "env": None, "sources": "user", "fork": True, "cwd": "/w"}),
            ((None,), {"extra_args": None, "permission_mode": "plan", "max_turns": 0, "budget_usd": 0}),
            (("",), {"sources": (), "allowed_tools": "ab", "model": "m", "settings": "{}"}), ((), {"bogus": 1}),
            ((), {"env": {"STACK_REPORT_FORMAT": "text"}, "json_reports": True})]
    for i, (a, k) in enumerate(opts):
        out.append((f"options#{i}", lambda m, a=a, k=k: m.options(*a, **k), {}))
    out += pure_cases(t)
    for i, (label, over, kw, between) in enumerate(scenarios(t)):
        out.append((f"connect/ask {label}", scenario_case(t, i, over, kw, between), {}))
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--base", default="7446f631")
    ap.add_argument("--new", default=str(REPO / REL))
    ap.add_argument("-v", action="count", default=0, help="-v: every case, -vv: in full")
    ap.add_argument("-k", default="", help="only the cases whose name contains this text")
    a = ap.parse_args(argv)
    git = subprocess.run(["git", "-C", str(REPO), "show", f"{a.base}:{REL}"], capture_output=True, text=True, check=False)
    if git.returncode != 0:
        print(f"cannot read {a.base}:{REL}: {git.stderr.strip()}")
        return 2
    import claude_agent_sdk
    claude_agent_sdk.ClaudeSDKClient = FakeClient
    with tempfile.TemporaryDirectory(prefix="sdk-differential-") as tmp:
        t = Path(os.path.realpath(tmp))
        ROOTS[:] = sorted({tmp, str(t)}, key=len, reverse=True) + [str(t)]
        (t / "old").mkdir()
        (t / "old" / "stack_sdk.py").write_text(git.stdout)
        tree(t)
        mods = [load(t / "old" / "stack_sdk.py", "stack_sdk_old"), load(Path(a.new), "stack_sdk_new")]
        todo, bad, t0 = [c for c in cases(t) if a.k in c[0]], [], time.monotonic()
        for name, fn, env in todo:
            got = []
            if a.v:
                print(f"run  {name}", file=sys.stderr, flush=True)
            for m in mods:
                with environ(env):
                    got.append(json.dumps(attempt(lambda m=m, fn=fn: fn(m)), sort_keys=False, default=repr))
            if got[0] != got[1]:
                bad.append(name)
                print(f"DIFF {name}\n  old: {got[0][:1500]}\n  new: {got[1][:1500]}")
            elif a.v:
                print(f"same {name}: {got[0] if a.v > 1 else got[0][:160]}")
        print(f"{len(todo) - len(bad)} of {len(todo)} cases identical ({a.base} vs {norm(a.new)}, "
              f"{time.monotonic() - t0:.1f}s)")
        return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
