"""lib/render.py: one full render into a scratch stage (INTERFACES §2 layout, §3 wave 2, §5, §6).

The default render runs once per module (`base`); each option variant renders a fresh stage of the
same empty CODEX_HOME and is compared file by file with it, so a flag that changes more than its own
part fails. In-process, scratch HOME/CODEX_HOME, fake codex only.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import stat

import pytest

from _render_helpers import (EXAMPLE_ENV, FAKE_CODEX, GUARD_BASE, USER_SCOPE, Env, changed, codex_state,
                             render, snapshot, toml)
from conftest import REPO, load_lib

EXCLUDED = ("claude-code-extensions", "override-agent", "stack-doctor", "stack-tree")
PROFILES = ("codex.config.toml", "codex-astra.config.toml")
ASTRA = {"ninja-coder", "main-coder", "mathematician", "planner", "proof-checker", "security-auditor"}


@pytest.fixture(scope="module")
def base(tmp_path_factory):
    env = Env()
    env.new_stage()
    out = env.ok(codex=FAKE_CODEX)
    return {"env": env, "snap": snapshot(env.stage), "work": snapshot(env.work), "out": out,
            "report": env.work_json("build-report.json")}


def variant(tmp_path, *flags, **kw):
    env = Env(tmp_path)
    env.new_stage()
    env.ok(*flags, **kw)
    return env, snapshot(env.stage)


def rels(snap, prefix):
    return {k for k in snap if k.startswith(prefix)}


# ------------------------------------------------------------------------------------- layout
def test_layout_is_interfaces_section_2(base):
    env, snap = base["env"], base["snap"]
    for rel in ("codex.config.toml", "codex-astra.config.toml", "rules/claude-agent-stack.rules", "AGENTS.md",
                "stack.env", "stack/hooks/codex_guard.py", "stack/hooks/stack_io.py",
                "stack/hooks/toolsmith_policy.py", "stack/bin/codex-hook", "stack/bin/with-stack-env",
                "stack/bin/mcp-headers", "stack/bin/codex-mcp-headers", "stack/bin/magg-private", "stack/bin/stack-install",
                "stack/magg/config.json", "stack/magg/k8s-mcp.toml", "stack/mcp/libdocs_mcp.py",
                "stack/policy/agents.json", "stack/policy/guard.json"):
        assert rel in snap, rel
    assert "config.toml" not in snap                      # off by default: never created
    assert {p.split("/")[1] for p in rels(snap, "stack/")} == {
        "agents", "agents-astra", "skills", "skill-modules", "hooks", "bin", "mcp", "magg", "policy"}
    for name in ("codex-hook", "with-stack-env", "mcp-headers", "codex-mcp-headers", "magg-private", "stack-install"):
        assert os.stat(env.stage / "stack" / "bin" / name).st_mode & 0o111 == 0o111, name
    assert not os.stat(env.stage / "stack" / "hooks" / "codex_guard.py").st_mode & 0o111


def test_toolsmith_wrapper_is_shipped_and_guard_paths_exist(base):
    env = base["env"]
    wrapper = env.stage / "stack" / "bin" / "stack-install"
    assert wrapper.read_bytes() == (REPO / "dot-config" / "dot-claude" / "bin" / "stack-install").read_bytes()
    assert os.stat(wrapper).st_mode & 0o777 == 0o755
    guard = json.loads((env.stage / "stack" / "policy" / "guard.json").read_text())
    assert guard["toolsmith_wrapper"].endswith("/stack/bin/stack-install")
    prefix = guard["stack"] + "/"
    named = [v for v in _strings(guard) if v.startswith(prefix)]
    assert guard["toolsmith_wrapper"] in named
    for v in named:
        assert (env.stage / "stack" / v[len(prefix):]).exists(), v
    # the wrapper finds its policy beside it (../hooks/) in the staged layout
    assert (env.stage / "stack" / "hooks" / "toolsmith_policy.py").is_file()


def _strings(o):
    if isinstance(o, str):
        yield o
    elif isinstance(o, list):
        for v in o:
            yield from _strings(v)
    elif isinstance(o, dict):
        for v in o.values():
            yield from _strings(v)


# no Claude install dependency: nothing staged for the servers or wrappers names the Claude config
CLAUDE_MARKERS = ("~/.claude/stack.env", ".claude/stack.env", "CLAUDE_CONFIG_DIR")
# {relative staged path: reason}
CLAUDE_ALLOW = {"bin/with-stack-env": "a shell comment (\"works under any CLAUDE_CONFIG_DIR\"); the path is resolved from $0"}


def test_no_claude_config_dependency_in_staged_scripts(base):
    stack = base["env"].stage / "stack"
    hits = []
    for sub in ("mcp", "bin", "hooks"):
        for f in sorted((stack / sub).rglob("*")):
            if f.is_file():
                text = f.read_text(errors="replace")
                rel = str(f.relative_to(stack))
                hits += ["%s: %s" % (rel, m) for m in CLAUDE_MARKERS if m in text and (rel, m) != ("bin/with-stack-env", "CLAUDE_CONFIG_DIR")]
    assert hits == []


def test_staged_servers_read_codex_home_stack_env(base):
    stack = base["env"].stage / "stack"
    for name in ("libdocs_mcp.py", "image_studio_mcp.py"):
        text = (stack / "mcp" / name).read_text()
        assert 'Path(__file__).resolve().parent.parent.parent / "stack.env"' in text, name
        assert "<CODEX_HOME>/stack.env" in text or name == "libdocs_mcp.py"
        assert text.count("cands.append(") == 2, name            # STACK_ENV_FILE and <CH>/stack.env only
    img = (stack / "mcp" / "image_studio_mcp.py").read_text()
    assert 'os.environ.get("CODEX_HOME") or home / ".codex"' in img


def test_roles_56_and_astra_6(base):
    snap = base["snap"]
    roles = {p[len("stack/agents/"):-5] for p in rels(snap, "stack/agents/")}
    assert len(roles) == 56 and "blackcat" not in roles
    assert {p[len("stack/agents-astra/"):-5] for p in rels(snap, "stack/agents-astra/")} == ASTRA
    prof = toml(base["env"].stage / "codex.config.toml")
    assert len([k for k, v in prof["agents"].items() if isinstance(v, dict)]) == 56
    c = base["report"]["counts"]
    assert (c["roles"], c["astra_roles"], c["skills_listed"], c["skill_modules"]) == (56, 6, 128, 89)


def test_excluded_skills_absent(base):
    names = {p.split("/")[2] for p in rels(base["snap"], "stack/skills/")}
    modules = {p.split("/")[2] for p in rels(base["snap"], "stack/skill-modules/")}
    assert len(names) == 128 and len(modules) == 89
    for x in EXCLUDED:
        assert x not in names and x not in modules
        assert x not in base["env"].work_json("links.json")["links"]


def test_validate_passes_on_the_stage(base):
    assert codex_state.validate(str(base["env"].stage)) == []


def test_second_render_is_byte_identical(base, tmp_path):
    env = base["env"]
    stage2, work2 = tmp_path / "stage2", tmp_path / "work2"
    shutil.copytree(env.stage, stage2, symlinks=True)       # the first render's output as the live copy
    env.ok(stage=stage2, work=work2, codex=FAKE_CODEX)
    assert changed(snapshot(stage2), base["snap"]) == set()
    # the work files differ only where the second run saw the first one's output
    rep, rep0 = json.loads((work2 / "build-report.json").read_text()), base["report"]
    assert (rep["agents_md"], rep["stack_env_seeded"], rep0["agents_md"], rep0["stack_env_seeded"]) == (
        "unchanged", False, "created", True)
    assert changed(snapshot(work2), base["work"]) == {"build-report.json", "options.json"}


def test_render_is_deterministic(base, tmp_path):
    """Two renders of the same live CODEX_HOME give the same bytes, work files included."""
    env = base["env"]
    stage2, work2 = tmp_path / "stage2", tmp_path / "work2"
    stage2.mkdir()
    codex_state.stage(str(env.ch), str(stage2))
    env.ok(stage=stage2, work=work2, codex=FAKE_CODEX)
    assert changed(snapshot(stage2), base["snap"]) == set()
    assert changed(snapshot(work2), base["work"]) == set()


def test_no_stage_path_in_any_output(base):
    env = base["env"]
    needles = {str(env.stage).encode(), os.path.realpath(env.stage).encode()}
    for snap in (base["snap"], base["work"]):
        for rel, data in snap.items():
            if isinstance(data, bytes):
                assert not any(n in data for n in needles), rel


def test_generated_paths_are_target_paths(base):
    env = base["env"]
    ch, stack = str(env.ch), str(env.ch) + "/stack"
    prof = toml(env.stage / "codex.config.toml")
    for role, e in prof["agents"].items():
        if isinstance(e, dict):
            assert e["config_file"] == "%s/agents/%s.toml" % (stack, role)
    astra = toml(env.stage / "codex-astra.config.toml")
    assert {r for r, e in astra["agents"].items() if isinstance(e, dict)
            and e["config_file"].startswith(stack + "/agents-astra/")} == ASTRA
    for groups in (v for k, v in prof["hooks"].items() if k != "state"):
        assert groups[0]["hooks"][0]["command"].startswith("/bin/sh '%s/bin/codex-hook' " % stack)
    keys = env.work_json("hook-keys.json")
    assert {k["source"] for k in keys} == {ch + "/codex.config.toml", ch + "/codex-astra.config.toml"}
    assert len(keys) == 16 and all(k["key"].startswith(k["source"] + ":") for k in keys)
    links = env.work_json("links.json")
    assert links["root"] == str(env.skills_root)
    assert all(t == "%s/skills/%s" % (stack, n) for n, t in links["links"].items())


# ------------------------------------------------------------------------------------- policy, guard
def test_guard_json_keys_and_protected_roots(base):
    env = base["env"]
    g = json.loads((env.stage / "stack" / "policy" / "guard.json").read_text())
    tmpl = json.loads(GUARD_BASE.read_text())
    assert set(g) == set(tmpl) | set(render.CTX_GUARD_KEYS)
    for k, v in tmpl.items():
        assert g[k] == v
    state = str(env.state / "codex-agent-stack")
    assert g["protected_roots"] == [str(env.ch), str(env.home / ".agents"), state,
                                    str(env.state / "codex-agent-stack-backups")]
    assert (g["codex_home"], g["home"], g["state_dir"], g["stack"]) == (str(env.ch), str(env.home), state,
                                                                        str(env.ch) + "/stack")
    assert {str(env.ch) + "/auth.json", str(env.ch) + "/stack.env"} <= set(g["credentials"]["paths"])
    assert g["toolsmith_wrapper"] == str(env.ch) + "/stack/bin/stack-install"


def test_agents_json_policy(base):
    pol = json.loads((base["env"].stage / "stack" / "policy" / "agents.json").read_text())
    assert pol["schema"] == 1 and len(pol["agents"]) == 56 and "blackcat" in pol
    assert pol["agents"]["coder"]["mcp"] == ["libdocs", "exa"]


# ------------------------------------------------------------------------------------- MCP
def test_mcp_servers_frontmatter_plus_user_scope(base):
    env = base["env"]
    servers = toml(env.stage / "codex.config.toml")["mcp_servers"]
    for sid in USER_SCOPE:
        assert sid in servers
    assert "wandb" not in servers
    assert servers["exa"]["http_headers_helper"] == "%s/stack/bin/codex-mcp-headers exa" % env.ch
    assert servers["libdocs"]["args"][-1] == "%s/stack/mcp/libdocs_mcp.py" % env.ch
    # after-effects names a vendor build no install ships: left out, with a warning
    assert "after-effects" not in servers
    assert "after-effects" in base["report"]["mcp_dropped_servers"]
    assert any("after-effects" in w for w in base["report"]["warnings"])


def test_with_wandb(tmp_path, base):
    env, snap = variant(tmp_path, "--with-wandb")
    servers = toml(env.stage / "codex.config.toml")["mcp_servers"]
    assert servers["wandb"] == {"url": "https://mcp.withwandb.com/mcp",
                                "http_headers_helper": "%s/stack/bin/codex-mcp-headers wandb" % env.ch}
    assert changed(snap, rebase(base["snap"], base["env"], env)) == set(PROFILES)


def test_same_mcp_id_twice_stops(tmp_path, monkeypatch):
    env = Env(tmp_path)
    env.new_stage()
    monkeypatch.setattr(render.convert_agents, "user_scope_servers",
                        lambda ctx, with_wandb: {"libdocs": {"url": "https://example.invalid/mcp"}})
    rc, _, err = env.run()
    assert rc == 1 and "libdocs" in err and "both" in err


def test_adapted_stack_env_paths(base):
    stack = base["env"].stage / "stack"
    assert '"$(dirname -- "$0")/../.." && pwd)/stack.env' in (stack / "bin" / "with-stack-env").read_text()
    assert "parent.parent.parent / \"stack.env\"" in (stack / "bin" / "mcp-headers").read_text()
    assert "parent.parent.parent / \"stack.env\"" in (stack / "mcp" / "libdocs_mcp.py").read_text()
    src = (REPO / "dot-config" / "dot-claude" / "bin" / "with-stack-env").read_bytes()
    assert len((stack / "bin" / "with-stack-env").read_bytes()) == len(src) + 3


def test_magg_config_rendered(base):
    env = base["env"]
    text = (env.stage / "stack" / "magg" / "config.json").read_text()
    json.loads(text)
    assert not re.search(r"__[A-Z][A-Z0-9_]*__", text)
    assert "%s/stack/magg/k8s-mcp.toml" % env.ch in text


# ------------------------------------------------------------------------------------- stack.env
def test_stack_env_seeded_0600_when_missing(base):
    p = base["env"].stage / "stack.env"
    assert stat.S_IMODE(p.stat().st_mode) == 0o600
    assert p.read_bytes() == EXAMPLE_ENV.read_bytes()
    assert base["report"]["stack_env_seeded"] is True


def test_stack_env_kept_when_present(tmp_path):
    env = Env(tmp_path)
    (env.ch / "stack.env").write_text("EXA_API_KEY=mine\n")
    (env.ch / "stack.env").chmod(0o600)
    env.new_stage()
    env.ok()
    assert (env.stage / "stack.env").read_text() == "EXA_API_KEY=mine\n"
    assert env.work_json("build-report.json")["stack_env_seeded"] is False


# ------------------------------------------------------------------------------------- variants
def rebase(snap, old_env, new_env):
    """A snapshot of another scratch machine with its paths swapped in (the renders embed CH)."""
    out = {}
    for k, v in snap.items():
        if isinstance(v, bytes):
            for a, b in ((old_env.root, new_env.root),):
                v = v.replace(str(a).encode(), str(b).encode())
        out[k] = v
    return out


@pytest.mark.parametrize("flag,changes,gone", [
    ("--legacy-sandbox", set(PROFILES), set()),
    ("--no-escalation", set(PROFILES), set()),
    ("--no-mcp", set(PROFILES), set()),
    ("--with-rollout-budget", set(PROFILES), set()),
    ("--git-allow-rules", {"rules/claude-agent-stack.rules"}, set()),
    ("--no-agents-md", set(), {"AGENTS.md"}),
    ("--no-astra-profile", set(), {"codex-astra.config.toml", "stack/agents-astra/"}),
])
def test_each_flag_changes_only_its_part(tmp_path, base, flag, changes, gone):
    env, snap = variant(tmp_path, flag)
    assert codex_state.validate(str(env.stage)) == []
    ref = rebase(base["snap"], base["env"], env)
    diff = changed(snap, ref)
    missing = {k for k in diff if k not in snap}
    assert diff - missing == changes
    assert all(any(k == g or (g.endswith("/") and k.startswith(g)) for g in gone) for k in missing), missing
    for g in gone:
        assert any(k == g or k.startswith(g) for k in missing), g
    prof = toml(env.stage / "codex.config.toml")
    if flag == "--legacy-sandbox":
        assert prof["sandbox_mode"] == "workspace-write" and "default_permissions" not in prof
    if flag == "--no-escalation":
        assert prof["approval_policy"] == "never"
    if flag == "--no-mcp":
        assert "mcp_servers" not in prof
        assert "mcp_servers" not in toml(env.stage / "codex-astra.config.toml")
    if flag == "--no-astra-profile":
        assert not (env.stage / "codex-astra.config.toml").exists()
        assert not (env.stage / "stack" / "agents-astra").exists()
        assert {k["source"] for k in env.work_json("hook-keys.json")} == {str(env.ch) + "/codex.config.toml"}
        assert env.work_json("build-report.json")["cost_notice"] is None


def test_astra_cost_notice(base):
    note = base["report"]["cost_notice"]
    assert "gpt-6-astra" in note and "$10/$50" in note and "codex --profile codex-astra" in note
    assert note in base["out"]


def test_no_astra_profile_removes_an_earlier_astra_file(tmp_path):
    env = Env(tmp_path)
    env.new_stage()
    env.ok()
    env.ok("--no-astra-profile")
    assert not (env.stage / "codex-astra.config.toml").exists()


def test_skills_root_none(tmp_path):
    env = Env(tmp_path)
    env.new_stage()
    env.ok("--skills-root", "none")
    assert env.work_json("links.json") == {"root": None, "links": {}}
    assert len(list((env.stage / "stack" / "skills").iterdir())) == 128


def test_profile_name(tmp_path):
    env = Env(tmp_path)
    env.new_stage()
    env.ok("--profile-name", "work")
    assert (env.stage / "work.config.toml").is_file() and (env.stage / "work-astra.config.toml").is_file()
    assert not (env.stage / "codex.config.toml").exists()
    opts = env.work_json("options.json")
    assert opts["profile_name"] == "work" and opts["profile_files"] == ["work.config.toml", "work-astra.config.toml"]
    assert {k["source"] for k in env.work_json("hook-keys.json")} == {
        str(env.ch) + "/work.config.toml", str(env.ch) + "/work-astra.config.toml"}


@pytest.mark.parametrize("edit", [
    lambda env: ["--stage", "/x"],
    lambda env: env.argv("--stage", "relative/stage")[:2] + env.argv()[4:] + ["--stage", "relative/stage"],
    lambda env: env.argv("--ide-default", "--no-ide-default"),
    lambda env: env.argv("--profile-name", "bad name"),
    lambda env: [x if x != str(env.ch) else "/c'x" for x in env.argv()],
])
def test_usage_errors_exit_2(tmp_path, edit):
    env = Env(tmp_path)
    env.new_stage()
    assert render.main(edit(env)) == 2


# ------------------------------------------------------------------------------------- live profile files
def test_foreign_profile_table_stops(tmp_path):
    env = Env(tmp_path)
    (env.ch / "codex.config.toml").write_text('model = "x"\n[profiles.mine]\nmodel = "y"\n')
    env.new_stage()
    before = snapshot(env.stage)
    rc, _, err = env.run()
    assert rc == 1 and "profiles" in err and "config.toml" in err
    assert snapshot(env.stage) == before                  # nothing written: the check comes first


def test_foreign_hooks_subtable_stops(tmp_path):
    env = Env(tmp_path)
    (env.ch / "codex-astra.config.toml").write_text('[hooks.mine]\nx = 1\n')
    env.new_stage()
    rc, _, err = env.run()
    assert rc == 1 and "hooks.mine" in err and "codex-astra.config.toml" in err


@pytest.mark.parametrize("rel,text,named", [
    ("codex.config.toml", '[mcp_servers.mine]\ncommand = "x"\n', "mcp_servers.mine"),
    ("codex.config.toml", '[agents.my-role]\nconfig_file = "/x/agents/my-role.toml"\n', "agents.my-role"),
    ("codex-astra.config.toml", '[permissions.x]\ndescription = "y"\n', "permissions.x"),
    ("codex-astra.config.toml", '[mcp_servers.mine]\ncommand = "x"\n', "mcp_servers.mine"),
])
def test_foreign_table_under_a_stack_root_stops(tmp_path, rel, text, named):
    """§7.4 below the root: a table of the user's under a root the stack writes is not dropped."""
    env = Env(tmp_path)
    (env.ch / rel).write_text(text)
    env.new_stage()
    rc, _, err = env.run()
    assert rc == 1 and named in err and rel in err, err


@pytest.mark.parametrize("ide", [False, True])
def test_extra_hook_handler_in_a_stack_written_file_stops(tmp_path, ide):
    """The stack's own file plus one more [[hooks.PreToolUse]] group: the extra group is named; a
    changed value of a key the stack writes, or a stack table the ide form leaves out, is not foreign
    (the install rewrites the file)."""
    env = Env(tmp_path)
    flags = ["--ide-default"] if ide else []
    env.new_stage()
    env.ok()
    text = (env.stage / "codex.config.toml").read_text()
    n = len(toml(env.stage / "codex.config.toml")["hooks"]["PreToolUse"])
    (env.ch / "codex.config.toml").write_text(text.replace('model_reasoning_effort = "', 'model_reasoning_effort = "x', 1))
    env.new_stage()
    env.ok(*flags)                             # no old manifest, yet only stack paths: goes through
    (env.ch / "codex.config.toml").write_text(
        text + '\n[[hooks.PreToolUse]]\n[[hooks.PreToolUse.hooks]]\ntype = "command"\ncommand = "mine"\n')
    env.new_stage()
    rc, _, err = env.run(*flags)
    assert rc == 1 and "hooks.PreToolUse[%d]" % n in err and "codex.config.toml" in err, err


def test_last_installs_profile_files_never_count_as_foreign(tmp_path):
    """A live profile file equal (minus hooks.state) to what the last install wrote is the stack's:
    a run whose options drop some of its tables (--no-mcp, --legacy-sandbox) goes through."""
    env = Env(tmp_path)
    env.new_stage()
    env.ok()
    env.manifest()                             # the stage now stands for the installed CODEX_HOME
    env.ok("--no-mcp", "--legacy-sandbox")
    assert "mcp_servers" not in toml(env.stage / "codex.config.toml")
    assert "permissions" not in toml(env.stage / "codex-astra.config.toml")


def trust(ch, rel, event="pre_tool_use"):
    return {"%s/%s:%s:0:0" % (ch, rel, event): {"trusted_hash": "sha256:" + "b" * 64, "enabled": True}}


def write_trust(path, state):
    path.write_text(load_lib("toml_emit").dumps({"hooks": {"state": state}}))


@pytest.mark.parametrize("ide", [False, True])
def test_hooks_state_carried_into_every_profile_file(tmp_path, ide):
    env = Env(tmp_path)
    t1, t2 = trust(env.ch, "codex.config.toml"), trust(env.ch, "codex-astra.config.toml", "session_end")
    write_trust(env.ch / "codex.config.toml", t1)
    write_trust(env.ch / "codex-astra.config.toml", t2)
    env.new_stage()
    env.ok(*(["--ide-default"] if ide else []))
    union = dict(t1, **t2)
    main, astra = toml(env.stage / "codex.config.toml"), toml(env.stage / "codex-astra.config.toml")
    assert main["hooks"]["state"] == union and astra["hooks"]["state"] == union
    if ide:                                   # the comment-only form: trust records, no handler
        assert main == {"hooks": {"state": union}}
        assert set(astra["hooks"]) == {"state"}
        assert "state" not in toml(env.stage / "config.toml").get("hooks", {})


@pytest.mark.parametrize("ide", [False, True])
def test_one_files_retrust_of_a_shared_key_keeps_the_owners_record(tmp_path, ide):
    """U1: both files carry the union, then Codex re-trusts a key in one file only. The record of the
    file the key names wins (no "differs" stop: the user can always reinstall)."""
    env = Env(tmp_path)
    key = "%s/codex.config.toml:pre_tool_use:0:0" % env.ch
    write_trust(env.ch / "codex.config.toml", {key: {"trusted_hash": "a"}})
    write_trust(env.ch / "codex-astra.config.toml", {key: {"trusted_hash": "b"}})
    env.new_stage()
    env.ok(*(["--ide-default"] if ide else []))
    for rel in PROFILES:
        assert toml(env.stage / rel)["hooks"]["state"] == {key: {"trusted_hash": "a"}}, rel
    # the astra file's own key: its record wins the other way round
    akey = "%s/codex-astra.config.toml:session_end:0:0" % env.ch
    write_trust(env.ch / "codex.config.toml", {akey: {"trusted_hash": "a"}})
    write_trust(env.ch / "codex-astra.config.toml", {akey: {"trusted_hash": "b"}})
    env.new_stage()
    env.ok()
    assert toml(env.stage / "codex.config.toml")["hooks"]["state"] == {akey: {"trusted_hash": "b"}}


# ------------------------------------------------------------------------------------- execpolicy
def test_execpolicy_examples_checked_with_the_fake_codex(tmp_path):
    env = Env(tmp_path)
    env.new_stage()
    log = tmp_path / "codex.log"
    env.ok(env={"FAKE_CODEX_LOG": str(log)}, codex=FAKE_CODEX)
    calls = log.read_text().splitlines()
    assert len(calls) > 100 and all(c.startswith("execpolicy check --rules ") for c in calls)
    assert env.work_json("build-report.json")["execpolicy_checked"] is True


def test_execpolicy_disagreement_stops(tmp_path):
    env = Env(tmp_path)
    env.new_stage()
    liar = tmp_path / "codex"
    liar.write_text('#!/bin/sh\necho \'{"matchedRules": [], "decision": "allow"}\'\n')
    liar.chmod(0o755)
    rc, _, err = env.run(codex=liar)
    assert rc == 1 and "disagrees" in err


def test_codex_none_skips_the_check_with_a_warning(tmp_path):
    env = Env(tmp_path)
    env.new_stage()
    out = env.ok("--codex", "none", codex=None)
    rep = env.work_json("build-report.json")
    assert rep["execpolicy_checked"] is False and any("not checked" in w for w in rep["warnings"])
    assert "not checked" in out


# ------------------------------------------------------------------------------------- AGENTS.md
def test_agents_md_block_and_override_warning(tmp_path):
    env = Env(tmp_path)
    (env.ch / "AGENTS.md").write_text("# mine\n\nkeep this\n")
    (env.ch / "AGENTS.override.md").write_text("override\n")
    env.new_stage()
    env.ok()
    text = (env.stage / "AGENTS.md").read_text()
    assert text.startswith("# mine\n\nkeep this\n\n<!-- claude-agent-stack: begin")
    assert "{{" not in text and str(env.ch) + "/auth.json" in text
    rep = env.work_json("build-report.json")
    assert rep["agents_md"] == "added" and any("AGENTS.override.md" in w for w in rep["warnings"])
    assert env.work_json("options.json")["agents_md_block"]["sha256"]
    env.manifest()
    env.ok("--no-agents-md")
    assert (env.stage / "AGENTS.md").read_text() == "# mine\n\nkeep this\n"


def test_work_files(base):
    env = base["env"]
    regions = env.work_json("regions.json")
    assert regions == {"ide_default": False, "A": None, "B": None, "config_toml_sha256": None}
    opts = env.work_json("options.json")
    assert opts["ide_default"] is False and opts["ide_default_source"] == "default"
    assert opts["ctx"]["codex_home"] == str(env.ch) and opts["flags"]["no_mcp"] is False
    assert set(opts["profile_digests"]) == set(PROFILES)


def test_manifest_from_the_work_files(base, tmp_path):
    env = base["env"]
    stage = tmp_path / "stage"
    shutil.copytree(env.stage, stage, symlinks=True)
    m = env.manifest(stage=stage)
    assert m["hooks"] == env.work_json("hook-keys.json") and m["astra"] is True
    assert m["options"]["profile_digests"] == env.work_json("options.json")["profile_digests"]
    assert m["ide_default"] is False and m["config_toml_sha256"] is None
