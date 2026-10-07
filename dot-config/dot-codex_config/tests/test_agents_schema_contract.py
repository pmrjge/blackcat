"""Contracts of the agent converter's output: the policy equals agent_guard.py's tables (imported by path
here only, DESIGN.md §8.1); role files, [agents.<role>] entries and [mcp_servers.<id>] tables use only
keys of the vendored Codex config schema (rust-v0.160.1)."""
from __future__ import annotations

import json
import tomllib

import pytest

from _agents_helpers import (SCHEMA, ca, conversion, ctx_for, frontmatter, load_agent_guard,  # noqa: F401
                             models, scratch_src)
from conftest import load_lib

DEFS = SCHEMA["definitions"]
CONFIG_KEYS = set(SCHEMA["properties"])
ROLE_ENTRY_KEYS = set(DEFS["AgentRoleToml"]["properties"])
MCP_KEYS = set(DEFS["RawMcpServerConfig"]["properties"])


@pytest.fixture(scope="module")
def converted(tmp_path_factory):
    return conversion(tmp_path_factory)


@pytest.fixture(scope="module")
def ag():
    return load_agent_guard()


def test_policy_spawn_rows_equal_agent_guard_policy(converted, ag):
    _ctx, out = converted
    rows = out["policy"]["agents"]
    # `equilibrium` is not ported (convert_agents.NOT_PORTED): no role, and no spawn list names it
    np_ = {"equilibrium"}
    assert set(rows) == set(ag.AGENTS) - {"blackcat"} - np_ == set(ag.POLICY) - {"blackcat"} - np_
    for name, row in rows.items():
        want = [c for c in ag.POLICY[name] if c not in np_]
        assert sorted(row["spawn"]) == sorted(want), name
        assert len(set(row["spawn"])) == len(row["spawn"])
        assert row["spawn_tool"] == bool(want)
    assert {n for n, r in rows.items() if r["spawn"] == []} == set(ag.LEAVES)
    assert sorted(out["policy"]["blackcat"]["spawn"]) == sorted(c for c in ag.POLICY["blackcat"] if c not in np_)


def test_policy_flags_equal_agent_guard_tables(converted, ag):
    _ctx, out = converted
    rows = out["policy"]["agents"]
    assert {n for n, r in rows.items() if r["readonly"]} == set(ag.READONLY_TYPES)
    assert {n for n, r in rows.items() if r["web_ingesting"]} == set(ag.WEB_INGESTING_TYPES)
    assert {n for n, r in rows.items() if r["installer"]} == set(ag.INSTALLER_TYPES)
    assert set(ag.BUILTINS) == set() and out["policy"]["builtin_types"] == ["default", "worker", "explorer"]


def test_policy_tool_classes_and_caps_from_frontmatter(converted):
    _ctx, out = converted
    for name, row in out["policy"]["agents"].items():
        fm = frontmatter(name)
        tools = [t.strip() for t in fm["tools"].split(",")]
        assert row["apply_patch"] == bool({"Write", "Edit", "NotebookEdit", "MultiEdit"} & set(tools))
        assert row["shell"] == ("Bash" in tools)
        assert row["mcp"] == [t[5:] for t in tools if t.startswith("mcp__")]
        assert row["max_tool_calls"] == fm.get("maxTurns")
    assert out["policy"]["blackcat"] == {"spawn": out["policy"]["blackcat"]["spawn"], "mcp": [],
                                         "max_shell_reads_per_prompt": 3}


def test_policy_passes_the_stage_validator(converted, tmp_path):
    _ctx, out = converted
    cs = load_lib("codex_state")
    assert cs._check_agents_json(json.loads(json.dumps(out["policy"]))) == []


def test_role_dicts_use_only_schema_keys(converted):
    _ctx, out = converted
    assert SCHEMA["additionalProperties"] is False
    for name, role in list(out["roles"].items()) + list(out["astra_roles"].items()):
        assert list(role) == ["model", "model_reasoning_effort", "developer_instructions"], name
        assert set(role) <= CONFIG_KEYS
        assert all(isinstance(v, str) and v for v in role.values())
    assert DEFS["AgentRoleToml"]["additionalProperties"] is False
    for entries in (out["agents_entries"], out["astra_entries"]):
        for name, e in entries.items():
            assert set(e) == {"description", "config_file"} <= ROLE_ENTRY_KEYS
            assert e["config_file"].startswith("/") and e["config_file"].endswith("/%s.toml" % name)


def test_mcp_tables_use_only_schema_keys(converted, tmp_path):
    _ctx, out = converted
    http = scratch_src(tmp_path, extra_agents={"web-probe": HTTP_AGENT})
    tables = list(out["mcp_servers"].values()) + list(
        ca.convert(str(http), ctx_for(tmp_path), models())["mcp_servers"].values())
    assert DEFS["RawMcpServerConfig"]["additionalProperties"] is False
    kinds = set()
    for t in tables:
        assert set(t) <= MCP_KEYS, t
        kinds |= set(t)
        assert isinstance(t.get("command", ""), str) and isinstance(t.get("url", ""), str)
        assert all(isinstance(a, str) for a in t.get("args", []))
        assert all(isinstance(k, str) and isinstance(v, str) for k, v in t.get("env", {}).items())
    assert {"command", "args", "env", "url", "http_headers_helper"} <= kinds


def test_emitted_role_files_pass_codex_state_validate(converted, tmp_path):
    """Roles written with toml_emit, as render will: they parse back equal and validate() finds no
    role problem (required keys, schema keys, placeholders)."""
    _ctx, out = converted
    emit, cs = load_lib("toml_emit"), load_lib("codex_state")
    stage = tmp_path / "stage"
    for sub, roles in (("agents", out["roles"]), ("agents-astra", out["astra_roles"])):
        d = stage / "stack" / sub
        d.mkdir(parents=True)
        for name, role in roles.items():
            text = emit.dumps(role)
            assert tomllib.loads(text) == role
            (d / ("%s.toml" % name)).write_text(text)
    pol = stage / "stack" / "policy"
    pol.mkdir()
    (pol / "agents.json").write_text(json.dumps(out["policy"]))
    problems = cs.validate(str(stage))
    assert [p for p in problems if "agents" in p.split(":")[0]] == []


HTTP_AGENT = """---
name: web-probe
description: "Scratch agent with a remote MCP server."
model: sonnet
effort: low
maxTurns: 5
tools: Read, Skill, mcp__exa
mcpServers:
  - exa:
      type: http
      url: "https://mcp.exa.ai/mcp"
      headersHelper: "__CLAUDE_DIR__/bin/mcp-headers"
---

Probe body.
"""
