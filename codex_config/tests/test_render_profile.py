"""lib/render_profile.py: the `codex` profile, its opts, hooks.state carry-over and --ide-default
regions (DESIGN.md §3, §4.1, §7.4, §7.6; INTERFACES.md §3-B)."""
from __future__ import annotations

import copy
import tomllib

import pytest

from _profile_helpers import ASTRA, TRUST, changed_paths, denied_env_vars, parts, role_names, roundtrip
from conftest import load_lib

rp = load_lib("render_profile")
te = load_lib("toml_emit")
cr = load_lib("config_region")
hd = load_lib("hook_defs")
pm = load_lib("permissions")

ROOT_KEYS = {"model", "model_reasoning_effort", "approval_policy", "default_permissions",
             "developer_instructions", "web_search", "tool_output_token_limit"}
TABLES = {"features", "agents", "mcp_servers", "permissions", "skills", "shell_environment_policy",
          "hooks"}


def build(opts=None, **over):
    return rp.build(parts(**over), opts or {})


# ----------------------------------------------------------------------------- content


def test_profile_content():
    p = parts()
    c = rp.build(p, {})["codex"]
    assert set(c) == ROOT_KEYS | TABLES
    assert (c["model"], c["model_reasoning_effort"]) == ("gpt-6-luna", "high")
    assert c["approval_policy"] == "on-request"
    assert c["default_permissions"] == "claude-agent-stack" == pm.PROFILE_NAME
    assert c["permissions"] == {"claude-agent-stack": p["permissions"]}
    assert c["web_search"] == "disabled"
    assert isinstance(c["tool_output_token_limit"], int) and c["tool_output_token_limit"] > 0
    assert c["skills"] == {"max_context_tokens": 6000}
    assert c["mcp_servers"] == p["mcp_servers"]
    assert c["hooks"] == hd.hooks_table("/scratch/home/.codex/stack/bin/codex-hook")
    assert "sandbox_mode" not in c


def test_features():
    f = build()["codex"]["features"]
    assert f.get("network_proxy") is True
    assert f.get("multi_agent_v2") is False and f.get("multi_agent") is True
    assert f.get("hooks") is True
    assert "rollout_budget" not in f


def test_agents_table():
    a = build()["codex"]["agents"]
    assert a["max_depth"] == 8
    assert a["default_subagent_model"] == "gpt-6-luna"
    assert a["default_subagent_reasoning_effort"] == "high"
    assert isinstance(a["max_concurrent_threads_per_session"], int)
    roles = {k: v for k, v in a.items() if isinstance(v, dict)}
    assert sorted(roles) == role_names() and len(roles) == 56
    assert "blackcat" not in roles
    for n, e in roles.items():
        assert set(e) == {"description", "config_file"}
        assert e["config_file"].endswith("/stack/agents/%s.toml" % n)


def test_developer_instructions_rules_then_blackcat():
    p = parts(rules_text="RULES R\n\n", blackcat={"model": "m", "effort": "high",
                                                   "instructions": "\nBLACKCAT BODY\n"})
    di = rp.build(p, {})["codex"]["developer_instructions"]
    assert di == "RULES R\n\nBLACKCAT BODY\n"
    assert roundtrip({"developer_instructions": di})["developer_instructions"] == di


def test_shell_environment_policy_ports_settings_env_denies():
    sep = build()["codex"].get("shell_environment_policy", {})
    names = denied_env_vars()
    assert len(names) == 12
    assert sep == {"filters": {n: "exclude" for n in names}}


@pytest.mark.parametrize("opts", [{}, {"legacy_sandbox": True}, {"ide_default": True},
                                  {"no_mcp": True, "no_escalation": True, "with_rollout_budget": True},
                                  {"no_astra_profile": True, "ide_default": True}])
def test_roundtrip(opts):
    out = build(opts, hooks_state=TRUST)
    for k in ("codex", "codex_astra", "region_a", "region_b", "codex_astra_ide"):
        if out[k] is not None:
            assert roundtrip(out[k]) == out[k], k


def test_template_is_pinned():
    base = rp.load_template()
    assert tuple(base) == rp.TEMPLATE_KEYS
    assert rp.PERMISSION_PROFILE == pm.PROFILE_NAME


def test_template_with_a_foreign_key_is_refused(tmp_path):
    t = tmp_path / "profile.base.toml"
    t.write_text(rp.TEMPLATE.read_text() + "\n[tui]\nanimations = false\n")
    with pytest.raises(rp.BuildError, match="root keys"):
        rp.load_template(t)
    t.write_text(rp.TEMPLATE.read_text().replace("[agents]\n", "[agents]\ncoder = 1\n"))
    with pytest.raises(rp.BuildError, match="settings only"):
        rp.load_template(t)


# ----------------------------------------------------------------------------- opts


def _diff(opts, **over):
    a, b = build({}, **over), build(opts, **over)
    return a, b, changed_paths(a["codex"], b["codex"])


def test_opt_legacy_sandbox():
    a, b, d = _diff({"legacy_sandbox": True})
    perm = {p for p in d if p[0] == "permissions"}
    assert perm and d - perm == {("default_permissions",), ("sandbox_mode",),
                                 ("features", "network_proxy")}
    c = b["codex"]
    assert c["sandbox_mode"] == "workspace-write"
    assert "default_permissions" not in c and "permissions" not in c
    assert "network_proxy" not in c["features"]
    assert b["region_a"]["sandbox_mode"] == "workspace-write"
    assert "default_permissions" not in b["region_a"] and "permissions" not in b["region_b"]


def test_opt_no_escalation():
    a, b, d = _diff({"no_escalation": True})
    assert d == {("approval_policy",)} and b["codex"]["approval_policy"] == "never"


def test_opt_no_mcp():
    a, b, d = _diff({"no_mcp": True})
    assert d and all(p[0] == "mcp_servers" for p in d)
    assert "mcp_servers" not in b["codex"] and "mcp_servers" not in b["region_b"]


def test_opt_with_rollout_budget():
    a, b, d = _diff({"with_rollout_budget": True})
    assert d == {("features", "rollout_budget")}
    assert b["codex"]["features"]["rollout_budget"] is True


def test_opt_ide_default_changes_only_the_carried_state():
    a, b, d = _diff({"ide_default": True}, hooks_state=TRUST)
    assert {p[:3] for p in d} == {("hooks", "state", k) for k in TRUST}
    assert a["codex_ide"] is None and a["codex_astra_ide"] is None
    assert isinstance(b["codex_ide"], str) and b["codex_astra_ide"] is not None


def test_opt_no_astra_profile_leaves_codex_alone():
    a, b, d = _diff({"no_astra_profile": True})
    assert d == set() and b["codex_astra"] is None and a["codex_astra"] is not None


def test_opts_are_checked():
    with pytest.raises(rp.BuildError, match="unknown opts"):
        build({"ide": True})
    with pytest.raises(rp.BuildError, match="bool"):
        build({"no_mcp": "yes"})


# ----------------------------------------------------------------------------- hooks.state


def test_hooks_state_carried_over_verbatim():
    state = copy.deepcopy(TRUST)
    state["/scratch/home/.codex/codex.config.toml:stop:0:0"] = {"enabled": False}
    out = build(hooks_state=state)
    for k in ("codex", "codex_astra"):
        got = out[k]["hooks"].get("state")
        assert got == state, k
        assert roundtrip(out[k])["hooks"]["state"] == state, k
    text = te.dumps(out["codex"])
    assert tomllib.loads(text)["hooks"]["state"] == state
    # the guard's groups are untouched by the carried state
    assert {k: v for k, v in out["codex"]["hooks"].items() if k != "state"} == parts()["hooks"]


def test_hooks_state_is_copied_not_aliased():
    state = copy.deepcopy(TRUST)
    p = parts(hooks_state=state)
    out = rp.build(p, {})
    p["hooks_state"][next(iter(TRUST))]["trusted_hash"] = "changed"
    assert out["codex"]["hooks"]["state"] == TRUST


def test_no_hooks_state_no_state_table():
    out = build()
    assert "state" not in out["codex"]["hooks"]


def test_hooks_state_not_in_regions():
    out = build(hooks_state=TRUST)
    assert "state" not in out["region_b"]["hooks"]


def test_merge_hooks_state():
    other = {"/scratch/home/.codex/codex-astra.config.toml:pre_tool_use:0:0": {"trusted_hash": "x"}}
    m = rp.merge_hooks_state(TRUST, None, other, TRUST)
    assert m == {**TRUST, **other}
    with pytest.raises(rp.BuildError, match="differs"):
        rp.merge_hooks_state(TRUST, {next(iter(TRUST)): {"trusted_hash": "other"}})
    with pytest.raises(rp.BuildError):
        rp.merge_hooks_state({"k": "not a table"})


@pytest.mark.parametrize("bad", [[], {"k": 1}, {"k": {"trusted_hash": 5}}, {"k": {"enabled": "y"}}])
def test_bad_hooks_state(bad):
    with pytest.raises(rp.BuildError):
        build(hooks_state=bad)


# ----------------------------------------------------------------------------- --ide-default


def test_ide_regions_split_root_keys_and_tables():
    out = build({"ide_default": True}, hooks_state=TRUST)
    a, b = out["region_a"], out["region_b"]
    assert set(a) == ROOT_KEYS
    assert all(not isinstance(v, dict) for v in a.values())
    assert set(b) == TABLES
    assert all(isinstance(v, dict) for v in b.values())
    assert b["hooks"] == parts()["hooks"]


def test_ide_union_of_regions_is_the_profile():
    out = build({"ide_default": True}, hooks_state=TRUST)
    assert cr.merge(out["region_a"], out["region_b"]) == out["codex"]
    assert tomllib.loads(out["codex_ide"]) == {}
    assert out["codex_ide"].strip() and all(
        ln.startswith("#") for ln in out["codex_ide"].splitlines() if ln.strip())


def test_regions_without_ide_default_are_the_profile_minus_its_state():
    out = build({}, hooks_state=TRUST)
    full = copy.deepcopy(out["codex"])
    del full["hooks"]["state"]
    assert cr.merge(out["region_a"], out["region_b"]) == full
    assert out["codex_ide"] is None and out["codex_astra_ide"] is None


def test_ide_no_profile_carries_hooks():
    out = build({"ide_default": True}, hooks_state=TRUST)
    assert "hooks" not in tomllib.loads(out["codex_ide"])
    assert "hooks" not in out["codex_astra_ide"]
    assert set(out["codex_astra_ide"]) == {"agents"}


@pytest.mark.parametrize("user", [b"", b'model_provider = "openai"\n',
                                  b'model_provider = "openai"\n\n[projects."/w"]\ntrust_level = "trusted"\n'
                                  b'\n[hooks.state."/x/config.toml:pre_tool_use:0:0"]\ntrusted_hash = "h"\n'])
def test_ide_regions_splice_into_config_toml(user):
    out = build({"ide_default": True})
    data = cr.splice(user, te.dumps(out["region_a"]), te.dumps(out["region_b"]))
    got = tomllib.loads(data.decode())
    assert got == cr.merge(tomllib.loads(user.decode()), out["codex"])


# ----------------------------------------------------------------------------- input errors


@pytest.mark.parametrize("mutate, match", [
    (lambda p: p.update(extra=1), "unknown parts"),
    (lambda p: p.pop("hooks_state"), "missing parts"),
    (lambda p: p["blackcat"].pop("effort"), "blackcat"),
    (lambda p: p["blackcat"].update(model=""), "blackcat.model"),
    (lambda p: p.update(rules_text="  "), "rules_text"),
    (lambda p: p.update(agents_entries={}), "empty"),
    (lambda p: p["agents_entries"].update(Coder={"description": "d", "config_file": "/s/agents/Coder.toml"}),
     "lowercase"),
    (lambda p: p["agents_entries"].update(max_depth={"description": "d", "config_file": "/s/agents/max_depth.toml"}),
     "reserved"),
    (lambda p: p["agents_entries"].update(worker={"description": "d", "config_file": "/s/agents/worker.toml"}),
     "reserved"),
    (lambda p: p["agents_entries"]["coder"].update(nickname_candidates=["c"]), "unknown keys"),
    (lambda p: p["agents_entries"]["coder"].pop("description"), "description is missing"),
    (lambda p: p["agents_entries"]["coder"].update(config_file="/s/roles/coder.toml"), "must end in"),
    (lambda p: p["agents_entries"]["coder"].update(config_file="/s/agents/../agents/coder.toml"),
     "normalized"),
    (lambda p: p["mcp_servers"].update(bad={"command": "x", "transport": "stdio"}), "does not know"),
    (lambda p: p["mcp_servers"].update({"a b": {"command": "x"}}), "server id"),
    (lambda p: p["permissions"].update(sandbox="x"), "does not know"),
    (lambda p: p["hooks"].update(state={}), "state"),
    (lambda p: p["hooks"].update(OnFire=[]), "unknown event"),
    (lambda p: p["hooks"].update(PreToolUse=[{"matcher": ".*", "hooks": []}]), "handlers"),
    (lambda p: p.update(skills_max_context_tokens=0), "skills_max_context_tokens"),
    (lambda p: p.update(skills_max_context_tokens=10001), "skills_max_context_tokens"),
    (lambda p: p.update(skills_max_context_tokens=True), "skills_max_context_tokens"),
])
def test_unknown_or_bad_parts_are_errors(mutate, match):
    p = parts()
    mutate(p)
    with pytest.raises(rp.BuildError, match=match):
        rp.build(p, {})


def test_relative_config_files_are_accepted():
    p = parts()
    for n, e in p["agents_entries"].items():
        e["config_file"] = "stack/agents/%s.toml" % n
    for n, e in p["astra_entries"].items():
        e["config_file"] = "stack/agents-astra/%s.toml" % n
    out = rp.build(p, {})
    assert out["codex"]["agents"]["coder"]["config_file"] == "stack/agents/coder.toml"
    assert out["codex_astra"]["agents"][ASTRA[0]]["config_file"] == "stack/agents-astra/%s.toml" % ASTRA[0]


def test_parts_are_not_mutated():
    p = parts(hooks_state=TRUST)
    before = copy.deepcopy(p)
    out = rp.build(p, {"ide_default": True})
    out["codex"]["agents"]["coder"]["description"] = "x"
    out["region_b"]["mcp_servers"]["jina"]["url"] = "x"
    assert p == before
