"""Contracts the guard relies on (DESIGN.md §9 contracts): the hook tool-name table (F10, F22; probe
P13 updates it), the hook input fixtures against hooks_schema.rs field names, the output against
the deny_unknown_fields wire structs, guard.base.json against the guard's built-in defaults, and
SUPPORT_FILES naming real dot-config/dot-claude/hooks files."""
from __future__ import annotations

import json
import re

import pytest

from _guard_helpers import (FIXTURES, GUARD_TEMPLATE, HOOKS_SRC, REPO, VENDOR, Guard, Stack, bash,
                            event, load_by_path, pre, support_files)

G = load_by_path("codex_guard_contract", HOOKS_SRC / "codex_guard.py")
SCHEMA_RS = (VENDOR / "hooks_schema.rs").read_text()
NAMES_RS = (VENDOR / "hook_names.rs").read_text()
TABLE = json.loads((FIXTURES / "tool_names.json").read_text())


def rust_fields(struct):
    m = re.search(r"pub\(crate\) struct %s \{(.*?)\n\}" % struct, SCHEMA_RS, re.S)
    assert m, struct
    return [f.replace("r#", "") for f in re.findall(r"^\s*pub ([\w#]+):", m.group(1), re.M)]


def camel(name):
    head, *rest = name.split("_")
    return head + "".join(p.title() for p in rest)


# ---------------------------------------------------------------- tool names
def test_canonical_names_match_hook_names_rs():
    assert 'Self::new("Bash")' in NAMES_RS
    assert 'name: "apply_patch".to_string()' in NAMES_RS
    assert 'name: "spawn_agent".to_string()' in NAMES_RS
    assert G.TOOL_CLASSES[TABLE["shell"]] == "shell"
    assert G.TOOL_CLASSES[TABLE["apply_patch"]] == "patch"
    assert G.TOOL_CLASSES[TABLE["spawn"]] == "spawn"


def test_tool_table_is_pinned():
    expected = {TABLE["shell"]: "shell", TABLE["apply_patch"]: "patch", TABLE["spawn"]: "spawn",
                "update_plan": "plan", "request_user_input": "ask", "view_image": "image"}
    expected.update({n: "ma" for n in TABLE["multi_agent_v1"]})
    assert G.TOOL_CLASSES == expected
    assert sorted(TABLE["other"]) == ["request_user_input", "update_plan", "view_image"]
    assert [G.MA_PREFIX + t for t in G.MA_TOOLS] == TABLE["multi_agent_v1"]


@pytest.mark.parametrize("name", TABLE["refused"])
def test_names_outside_the_table_are_unknown(name):
    assert G.classify(name)[0] == "unknown"


def test_mcp_name_format():
    assert TABLE["mcp_format"] == "mcp__<server>__<tool>"
    assert G.classify("mcp__neural-memory__nmem_remember") == ("mcp", "neural-memory", "nmem_remember")
    assert G.classify("mcp__computer-use__left_click") == ("mcp", "computer-use", "left_click")
    for bad in ("mcp__x", "mcp____y", "mcp_x__y", "MCP__x__y"):
        assert G.classify(bad)[0] == "unknown", bad


# ---------------------------------------------------------------- inputs
@pytest.mark.parametrize("fixture,struct", [
    ("pre_tool_use", "PreToolUseCommandInput"), ("permission_request", "PermissionRequestCommandInput"),
    ("post_tool_use", "PostToolUseCommandInput"), ("subagent_start", "SubagentStartCommandInput"),
    ("subagent_stop", "SubagentStopCommandInput"), ("user_prompt_submit", "UserPromptSubmitCommandInput"),
    ("session_start", "SessionStartCommandInput"), ("session_end", "SessionEndCommandInput")])
def test_event_fixtures_match_hooks_schema_rs(fixture, struct):
    assert set(event(fixture)) == set(rust_fields(struct))


def test_guard_reads_only_schema_fields():
    src = (HOOKS_SRC / "codex_guard.py").read_text()
    used = set(re.findall(r"ev\.get\(\"(\w+)\"\)", src))
    known = set()
    for s in ("PreToolUseCommandInput", "PostToolUseCommandInput", "SubagentStartCommandInput"):
        known |= set(rust_fields(s))
    assert used and used <= known, used - known


def test_caller_fields_absent_on_the_main_thread_are_optional_in_rust():
    for s in ("PreToolUseCommandInput", "PermissionRequestCommandInput", "PostToolUseCommandInput"):
        block = re.search(r"struct %s \{(.*?)\n\}" % s, SCHEMA_RS, re.S).group(1)
        assert "pub agent_id: Option<String>" in block and "pub agent_type: Option<String>" in block


# ---------------------------------------------------------------- outputs
@pytest.fixture
def guard(tmp_path, monkeypatch):
    return Guard(Stack(tmp_path), monkeypatch)


def test_pre_tool_use_output_fits_the_wire_struct(guard):
    allowed = {camel(f) for f in rust_fields("PreToolUseHookSpecificOutputWire")}
    top = {camel(f) for f in rust_fields("PreToolUseCommandOutputWire")} - {"universal"}
    decisions = set(re.findall(r'#\[serde\(rename = "(\w+)"\)\]\s*\n\s*(?:Allow|Deny|Ask),',
                               SCHEMA_RS))
    for ev in (bash("git push"), pre("spawn_agent", {"agent_type": "coder", "model": "x"},
                                     agent_type="python-engineer")):
        out = guard.pre(ev)
        assert set(out) <= top
        spec = out["hookSpecificOutput"]
        assert set(spec) <= allowed and spec["hookEventName"] == "PreToolUse"
        assert spec["permissionDecision"] in decisions
        if "updatedInput" in spec:
            assert spec["permissionDecision"] == "allow"       # F12: updatedInput only with allow


def test_permission_request_output_fits_the_wire_struct(guard):
    out = guard.perm(event("permission_request", tool_input={"command": "git push"}))
    assert set(out) == {"hookSpecificOutput"}
    spec = out["hookSpecificOutput"]
    assert set(spec) <= {camel(f) for f in rust_fields("PermissionRequestHookSpecificOutputWire")}
    dec = spec["decision"]
    assert set(dec) == {"behavior", "message"}                 # never updatedInput/interrupt
    assert set(dec) <= {camel(f) for f in rust_fields("PermissionRequestDecisionWire")}
    assert dec["behavior"] == "deny"


# ---------------------------------------------------------------- template and support files
def test_guard_template_equals_built_in_defaults():
    t = json.loads(GUARD_TEMPLATE.read_text())
    assert t["schema"] == 1 and t["caps"] == G.DEFAULT_CAPS
    assert t["image_max_px"] == G.DEFAULT_IMAGE_MAX_PX == 1920
    assert t["non_web_mcp_servers"] == G.DEFAULT_NON_WEB_MCP
    assert t["memory_write_tools"] == G.DEFAULT_MEMORY_WRITE_TOOLS
    assert t["computer_use_server"] == G.DEFAULT_COMPUTER_USE_SERVER
    G.validate_guard(dict(t, codex_home="/c", home="/h", state_dir="/s", protected_roots=["/c"],
                          credentials={"paths": [], "globs": []}))


def test_support_modules_load_by_path(tmp_path, monkeypatch):
    stack = Stack(tmp_path)
    guard = Guard(stack, monkeypatch)
    io_mod = guard.mod.support_module("stack_io")
    assert io_mod.__file__ == str(stack.hooks_dir / "stack_io.py") and callable(io_mod.write_json_atomic)
    assert guard.mod.support_module("stack_io") is io_mod                    # loaded once
    assert "codex_guard_stack_io" not in __import__("sys").modules           # never registered


def test_support_files_exist_and_are_loaded_by_path():
    names = support_files()
    assert names == ["dot-config/dot-claude/hooks/stack_io.py", "dot-config/dot-claude/hooks/toolsmith_policy.py"]
    for rel in names:
        assert (REPO / rel).is_file()
    src = (HOOKS_SRC / "codex_guard.py").read_text()
    assert not re.search(r"sys\.path\.(?:insert|append|extend)|sys\.path\s*[+=]", src)
    # by path, through SourceFileLoader; never importlib.util (typing: ~20 ms per call on 3.9)
    assert "loader = SourceFileLoader(name, path)" in src and "load_by_path(\"codex_guard_\" + name" in src
    assert not re.search(r"^\s*(?:import importlib\.util|from importlib(?:\.util)? import util)", src,
                         re.M)
    stub = (HOOKS_SRC / "codex-hook").read_text()
    assert '"$py" -I -c ' in stub and "SourceFileLoader(\"codex_guard\", sys.argv[1])" in stub
    assert "importlib.util" not in stub


def test_guard_is_stdlib_only_and_py39_syntax():
    import ast
    src = (HOOKS_SRC / "codex_guard.py").read_text()
    tree = ast.parse(src, feature_version=(3, 9))
    mods = {n.names[0].name.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.Import)}
    mods |= {n.module.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
    assert mods <= {"contextlib", "fcntl", "fnmatch", "hashlib", "importlib", "json", "os", "re",
                    "sys", "time", "shlex", "stat", "struct", "subprocess", "urllib", "tempfile",
                    "shutil"}, mods
    assert "shell=True" not in src and "eval(" not in re.sub(r"\"[^\"\n]*\"|'[^'\n]*'", "", src)
