"""lib/permissions.py: credential set and the [permissions.claude-agent-stack] profile (DESIGN.md §4.1 L1)."""
from __future__ import annotations

import fnmatch
import json
import tomllib

import pytest

from _rules_helpers import ctx_for, definition, schema_errors, settings
from conftest import load_lib

pm = load_lib("permissions")
te = load_lib("toml_emit")

S = settings()


@pytest.fixture
def ctx(tmp_path):
    return ctx_for(tmp_path / "home")


def denied(cred, path):
    return any(path == p or path.startswith(p.rstrip("/") + "/") for p in cred["paths"]) or \
        any(fnmatch.fnmatchcase(path, g) for g in cred["globs"])


def test_settings_input_counts():
    deny = S["permissions"]["deny"]
    assert sum(e.startswith("Read(") for e in deny) == 33
    assert sum(e.startswith("Edit(") for e in deny) == 28
    assert len(S["sandbox"]["network"]["allowedDomains"]) == 49


def test_credential_set_always_has_codex_secrets(ctx):
    cred = pm.credential_set(S, ctx)
    ch, home = ctx["codex_home"], ctx["home"]
    assert ch + "/auth.json" in cred["paths"] and ch + "/stack.env" in cred["paths"]
    # even with no Claude rules at all
    bare = pm.credential_set({"sandbox": {"network": {"allowedDomains": ["x.org"]}}}, ctx)
    assert bare["paths"][:2] == [ch + "/auth.json", ch + "/stack.env"]
    for p in (home + "/.ssh/id_ed25519", home + "/.aws/credentials", home + "/.netrc",
              home + "/.config/gh/hosts.yml", home + "/Library/Keychains/login.keychain-db",
              home + "/.claude/.credentials.json", home + "/.claude.json",
              home + "/.claude/stack.env", ch + "/stack/mcp/x/stack.env",
              home + "/src/app/.env", home + "/src/app/.env.production", "/srv/x/.env.dev.local"):
        assert denied(cred, p), p
    for p in (ch + "/config.toml", home + "/src/app/main.py", home + "/.agents/skills/x/SKILL.md",
              home + "/.envrc"):
        assert not denied(cred, p), p
    assert all(p.startswith("/") for p in cred["paths"])


def test_profile_shape_and_key_entries(ctx):
    prof = pm.permission_profile(S, ctx)
    fs = prof["filesystem"]
    ch, home = ctx["codex_home"], ctx["home"]
    assert prof["extends"] == ":workspace"
    assert fs[ch] == "read" and fs[home + "/.agents"] == "read" and fs[ctx["state_dir"]] == "read"
    assert fs[ch + "/auth.json"] == "deny" and fs[ch + "/stack.env"] == "deny"
    assert fs[home + "/.ssh"] == "deny" and fs[home + "/.claude"] == "read"
    ws = fs[":workspace_roots"]
    assert ws["**/.env"] == "deny" and ws[".claude/settings.json"] == "read"
    assert ws[".git/hooks"] == "read"
    # Claude Edit denies protect writes only: never a read denial
    assert fs[home + "/.cache/uv"] == "read"
    assert ".claude/hooks" in ws and ws[".claude/hooks"] == "read"
    # the self-protection roots do not depend on settings.json (DESIGN §4.2 a)
    bare = pm.permission_profile({"sandbox": {"network": {"allowedDomains": ["x.org"]}}}, ctx)
    assert {k: v for k, v in bare["filesystem"].items() if v == "read"} == {
        ch: "read", home + "/.agents": "read", ctx["state_dir"]: "read"}
    assert bare["filesystem"][ch + "/auth.json"] == "deny"


def test_profile_keys_follow_codex_path_grammar(ctx):
    fs = pm.permission_profile(S, ctx)["filesystem"]
    for k, v in fs.items():
        if k == ":workspace_roots":
            for sub, acc in v.items():
                assert sub.split("/")[0] not in ("", ".", ".."), sub
                if any(c in sub for c in "*?["):
                    assert acc == "deny", sub
            continue
        assert k.startswith("/"), k
        if any(c in k.removesuffix("/**") for c in "*?[]"):
            assert v == "deny", k                  # globs only with deny (permissions.rs)
        assert v in ("read", "deny"), (k, v)       # nothing is ever granted write


def test_profile_schema_contract(ctx):
    prof = pm.permission_profile(S, ctx)
    assert schema_errors(prof, definition("PermissionProfileToml")) == []
    for k, v in prof["filesystem"].items():
        assert schema_errors(v, definition("FilesystemPermissionToml")) == [], k
    for d, v in prof["network"]["domains"].items():
        assert schema_errors(v, definition("NetworkDomainPermissionToml")) == [], d
    # the whole profile as render_profile will emit it: TOML round trip and the root schema keys
    doc = {"default_permissions": pm.PROFILE_NAME, "permissions": {pm.PROFILE_NAME: prof},
           "features": {"network_proxy": True}}
    assert tomllib.loads(te.dumps(doc)) == doc
    from _rules_helpers import SCHEMA
    for key in doc:
        assert key in SCHEMA["properties"], key
    assert "network_proxy" in SCHEMA["properties"]["features"]["properties"]


def test_builtin_parent_spelling_is_vendored():
    from _rules_helpers import vendored
    src = vendored("protocol_models.builtin_profiles.extract.rs")
    assert 'BUILT_IN_PERMISSION_PROFILE_WORKSPACE: &str = ":workspace"' in src


def test_network_domains(ctx):
    doms = pm.network_domains(S)
    assert len(doms) == 49 and set(doms.values()) == {"allow"}
    assert doms["*.huggingface.co"] == "allow" and "github.com" in doms
    net = pm.permission_profile(S, ctx)["network"]
    assert net["enabled"] is True and net["mode"] == "full" and net["allow_local_binding"] is True
    assert net["domains"] == doms
    with pytest.raises(pm.BuildError):
        pm.network_domains({"sandbox": {"network": {"allowedDomains": ["*"]}}})


def test_claude_and_codex_sides_both_rendered(ctx):
    home = ctx["home"]
    cred = pm.credential_set(S, ctx)
    assert home + "/.local/state/codex-agent-stack-backups" in cred["paths"]
    assert home + "/.local/state/claude-agent-stack-backups" in cred["paths"]
    assert home + "/.cache/claude-agent-stack/eq-tunnel" in cred["paths"]
    # Codex has no ~/.codex/.credentials.json: it is renamed to auth.json, never copied verbatim
    assert ctx["codex_home"] + "/.credentials.json" not in cred["paths"]


def test_unmapped_input_is_an_error(ctx):
    for bad in ({"permissions": {"deny": ["Read(/__NEW_DIR__/x)"]}},
                {"permissions": {"deny": ["Read(/etc-relative/x)"]}},
                {"sandbox": {"filesystem": {"denyRead": ["../up"]}}}):
        with pytest.raises(pm.BuildError):
            pm.credential_set(bad, ctx)
    with pytest.raises(pm.BuildError):
        pm.credential_set(S, dict(ctx, codex_home="relative/.codex"))


def test_report_names_guard_only_and_covered(ctx):
    notes = pm.report(S, ctx)
    assert any("tools/instructor" in n and n.startswith("guard-only") for n in notes)
    assert any(n.startswith("covered: write protection") for n in notes)
    assert any("envVars" in n for n in notes)
    assert json.dumps(notes)
