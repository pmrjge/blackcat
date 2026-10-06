"""Schema contract: every key path render_profile emits validates against the vendored Codex
config.schema.json (rust-v0.160.1: ConfigToml and its sub-definitions, additionalProperties respected,
and stricter: a key must be declared by the schema). Also pins render_profile's key allowlists to the
schema, and runs end to end on convert_agents' real output once that module exists."""
from __future__ import annotations

import itertools
import tomllib

import pytest

from _profile_helpers import ASTRA, DEFS, SCHEMA, SETTINGS, TRUST, changed_paths, check, parts
from _rules_helpers import ctx_for
from conftest import CODEX_CONFIG, LIB, REPO, load_lib

rp = load_lib("render_profile")

OPT_SETS = [{}] + [{o: True} for o in rp.OPTS] + [
    dict.fromkeys(c, True) for c in itertools.combinations(rp.OPTS, 3)] + [dict.fromkeys(rp.OPTS, True)]


def _outputs(out):
    docs = {k: out[k] for k in ("codex", "codex_astra", "region_a", "region_b", "codex_astra_ide")
            if out[k] is not None}
    if out["codex_ide"] is not None:
        docs["codex_ide"] = tomllib.loads(out["codex_ide"])
    return docs


@pytest.mark.parametrize("opts", OPT_SETS, ids=lambda o: "+".join(sorted(o)) or "default")
def test_every_output_validates(opts):
    out = rp.build(parts(hooks_state=TRUST), opts)
    for name, doc in _outputs(out).items():
        assert check(doc) == [], name


def test_template_validates():
    assert check(rp.load_template()) == []


# ------------------------------------------------- the checker is not vacuous (it rejects these)


@pytest.mark.parametrize("doc", [
    {"profiles": {"codex": {"model": 1}}},
    {"no_such_key": 1},
    {"features": {"no_such_feature": True}},
    {"agents": {"coder": {"description": "d", "sandbox_mode": "read-only"}}},
    {"mcp_servers": {"x": {"command": "c", "transport": "stdio"}}},
    {"shell_environment_policy": {"exclude": ["A"], "filters": {"B": "exclude"}}},
    {"shell_environment_policy": {"filters": {"A": "deny"}}},
    {"permissions": {"p": {"filesystem": {"/x": "rw"}}}},
    {"permissions": {"p": {"sandbox": "x"}}},
    {"hooks": {"PreToolUse": [{"matcher": ".*", "hooks": [{"type": "command"}]}]}},
    {"hooks": {"state": {"k": {"trusted_hash": 1}}}},
    {"web_search": "on"},
    {"skills": {"max_context_tokens": 0}},
    {"approval_policy": "untrusted-ish"},
])
def test_checker_rejects(doc):
    assert check(doc) != []


# ------------------------------------------------- render_profile's allowlists equal the schema's


def test_allowlists_pinned_to_schema():
    assert rp.HOOK_EVENTS == set(DEFS["HooksToml"]["properties"]) - {"state"}
    assert rp.MCP_KEYS == set(DEFS["RawMcpServerConfig"]["properties"])
    assert rp.PERMISSION_KEYS == set(DEFS["PermissionProfileToml"]["properties"])
    assert rp.AGENTS_SETTINGS == set(DEFS["AgentsToml"]["properties"])
    assert rp.ROLE_ENTRY_KEYS <= set(DEFS["AgentRoleToml"]["properties"])
    assert SCHEMA["properties"]["permissions"]["allOf"][0]["$ref"].endswith("/PermissionsToml")


def test_backing_definitions():
    """The definitions behind the profile's less obvious keys (named in the hand-back)."""
    P = SCHEMA["properties"]
    assert P["shell_environment_policy"]["allOf"][0]["$ref"].endswith("/ShellEnvironmentPolicyToml")
    sep = DEFS["ShellEnvironmentPolicyToml"]
    assert sep["properties"]["filters"]["additionalProperties"]["$ref"].endswith(
        "/ShellEnvironmentPolicyFilter")
    assert set(DEFS["ShellEnvironmentPolicyFilter"]["enum"]) == {"include", "exclude"}
    assert {"not": {"required": ["exclude", "filters"]}} in sep["allOf"]
    f = P["features"]["properties"]
    assert f["network_proxy"]["$ref"].endswith("/FeatureToml_for_NetworkProxyConfigToml")
    assert f["rollout_budget"]["$ref"].endswith("/FeatureToml_for_RolloutBudgetConfigToml")
    assert f["multi_agent_v2"]["$ref"].endswith("/FeatureToml_for_MultiAgentV2ConfigToml")
    assert f["hooks"] == {"type": "boolean"} and f["multi_agent"] == {"type": "boolean"}


# ------------------------------------------------- end to end on convert_agents (after integration)


@pytest.mark.skipif(not (LIB / "convert_agents.py").exists() or not (CODEX_CONFIG / "models.toml").exists(),
                    reason="lib/convert_agents.py or models.toml not on this branch yet (part B1)")
def test_end_to_end_with_convert_agents(tmp_path):
    ca = load_lib("convert_agents")
    pm, hd = load_lib("permissions"), load_lib("hook_defs")
    models = tomllib.loads((CODEX_CONFIG / "models.toml").read_text())
    ctx = ctx_for(tmp_path / "home")
    conv = ca.convert(str(REPO), ctx, models)
    p = {"blackcat": conv["blackcat"],
         "rules_text": (CODEX_CONFIG / "templates" / "rules.md").read_text(),
         "agents_entries": conv["agents_entries"], "astra_entries": conv["astra_entries"],
         "mcp_servers": conv["mcp_servers"], "permissions": pm.permission_profile(SETTINGS, ctx),
         "hooks": hd.hooks_table(ctx["stack"] + "/bin/codex-hook"), "hooks_state": {},
         "skills_max_context_tokens": 6000}
    for opts in ({}, {"ide_default": True}, {"legacy_sandbox": True, "no_escalation": True}):
        out = rp.build(p, opts)
        for name, doc in _outputs(out).items():
            assert check(doc) == [], (opts, name)
        c = out["codex"]
        assert (c["model"], c["model_reasoning_effort"]) == ("gpt-6-luna", "high")
        assert len([v for v in c["agents"].values() if isinstance(v, dict)]) == 56
        assert changed_paths(c, out["codex_astra"]) == {("agents", n, "config_file") for n in ASTRA}
