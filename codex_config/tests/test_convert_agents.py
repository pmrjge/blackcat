"""lib/convert_agents.py (DESIGN.md §8.1, INTERFACES.md §3) and bin/codex-mcp-headers.

Structure, not wording: translate.py's phrasing is part B2's; these tests check where texts go, that
every placeholder is rendered and that untranslatable input stops the build with file:line."""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys

import pytest

from _agents_helpers import (AGENTS_DIR, HEADERS_BIN, REPO, RULES_MD, ca, agent_names, conversion,  # noqa: F401
                             ctx_for, frontmatter, models, scratch_src, walk_strings)


@pytest.fixture(scope="module")
def converted(tmp_path_factory):
    return conversion(tmp_path_factory)


# ---------------------------------------------------------------------------------------- inputs
def test_57_agents_parse():
    names = agent_names()
    assert len(names) == 57 and "blackcat" in names
    for n in names:
        fm = frontmatter(n)
        assert fm["name"] == n and fm["model"] in ("opus", "sonnet") and isinstance(fm["description"], str)
    hooks = frontmatter("blackcat")["hooks"]                            # nested block: list of maps
    assert hooks["PreToolUse"][0]["matcher"] == "*"
    assert hooks["PreToolUse"][0]["hooks"][0]["timeout"] == 15
    mcp = frontmatter("mcp-broker")["mcpServers"][0]["magg"]
    assert mcp["args"][0] == "--only" and mcp["env"]["MAGG_PATH"].startswith("__CLAUDE_DIR__")


@pytest.mark.parametrize("text,needle", [
    ("---\nname: x\n  bad: indent\n---\n", "supported YAML subset"),
    ("---\nname: x\nname: y\n---\n", "duplicate key"),
    ("---\nname: &anchor x\n---\n", "supported YAML subset"),
    ("---\nname: x\n", "not closed"),
    ("name: x\n", "no frontmatter"),
])
def test_frontmatter_outside_the_subset_fails(text, needle):
    with pytest.raises(ca.BuildError, match=needle):
        ca.parse_frontmatter(text, "t.md")


# ---------------------------------------------------------------------------------------- output shape
def test_56_roles_and_the_blackcat_main_thread(converted):
    ctx, out = converted
    roles = set(agent_names()) - {"blackcat"}
    assert len(roles) == 56
    assert set(out["roles"]) == roles == set(out["agents_entries"]) == set(out["policy"]["agents"])
    assert set(out["blackcat"]) == {"model", "effort", "instructions"}
    assert out["report"]["agents"] == 57 and out["report"]["roles"] == 56
    for name, e in out["agents_entries"].items():
        assert e["config_file"] == "%s/stack/agents/%s.toml" % (ctx["codex_home"], name)
        assert e["description"] and "\n" not in e["description"]


def test_developer_instructions_are_body_then_rules(converted):
    ctx, out = converted
    rules = RULES_MD.read_text().strip()
    rules = rules.replace("{{STACK}}", ctx["stack"]).replace("{{CODEX_HOME}}", ctx["codex_home"]) \
                 .replace("{{HOME}}", ctx["home"])
    for name, role in out["roles"].items():
        instr = role["developer_instructions"]
        assert instr.endswith("\n\n" + rules + "\n"), name
        body = instr[:-len(rules) - 3]
        assert body.strip() and body == body.strip()
        assert body.count("\n") >= 2                                    # the body, not a stub
    assert out["blackcat"]["instructions"].startswith("You are BlackCat")


def test_rules_and_blackcat_texts_from_the_caller(tmp_path):
    out = ca.convert(str(REPO), ctx_for(tmp_path), models(), rules_text="RULES R\n", blackcat_text="BC TEXT\n")
    assert all(r["developer_instructions"].endswith("\n\nRULES R\n") for r in out["roles"].values())
    assert out["blackcat"]["instructions"] == "BC TEXT\n"
    with pytest.raises(ca.BuildError, match="placeholder"):
        ca.convert(str(REPO), ctx_for(tmp_path), models(), rules_text="see {{NOPE}}\n")


def test_no_placeholder_left_anywhere(converted):
    ctx, out = converted
    for s in walk_strings(out):
        assert not re.search(r"__[A-Z][A-Z0-9_]*__|\{\{[^{}\n]*\}\}", s), s[:200]
        assert "~/.claude" not in s and "__CLAUDE_DIR__" not in s


def test_dropped_frontmatter_is_reported(converted):
    _ctx, out = converted
    d = out["report"]["dropped"]
    assert "omitClaudeMd" in d["explore"] and "hooks" in d["blackcat"]
    assert {"permissionMode", "color"} <= set(d["coder"]) and "memory" in d["go-engineer"]
    assert "experimental" in d["researcher"]
    assert out["report"]["mcp_dropped"] == {"image-director:image-studio": ["alwaysLoad"]}
    keys = set(walk_strings({k: list(v) for k, v in out["roles"].items()}))
    assert not keys & {"permissionMode", "color", "memory", "experimental", "omitClaudeMd", "hooks"}


def test_unknown_frontmatter_key_fails(tmp_path):
    src = scratch_src(tmp_path, agent_edits={"coder": ("color: green\n", "color: green\nisolation: worktree\n")})
    with pytest.raises(ca.BuildError, match="coder.md: unmapped frontmatter key.*isolation"):
        ca.convert(str(src), ctx_for(tmp_path), models())


def test_unknown_tool_fails(tmp_path):
    src = scratch_src(tmp_path, agent_edits={"coder": (", mcp__libdocs, mcp__exa", ", Telepathy, mcp__libdocs, mcp__exa")})
    with pytest.raises(ca.BuildError, match="unknown tool 'Telepathy'"):
        ca.convert(str(src), ctx_for(tmp_path), models())


def test_untranslatable_text_fails_with_file_and_line(tmp_path):
    text = (AGENTS_DIR / "coder.md").read_text()
    body_line = len(text.rstrip("\n").split("\n")) + 1
    desc_line = text.split("\n").index(next(ln for ln in text.split("\n") if ln.startswith("description:"))) + 1
    src = scratch_src(tmp_path, agent_edits={
        "coder": lambda t: t.rstrip("\n").replace('description: "Small', 'description: "__BOGUS_D__ Small', 1)
        + "\nSee __BOGUS__ here.\n"})
    with pytest.raises(ca.BuildError) as ei:
        ca.convert(str(src), ctx_for(tmp_path), models())
    msg = str(ei.value)
    assert "dot-claude/agents/coder.md:%d: __BOGUS__" % body_line in msg
    assert "dot-claude/agents/coder.md:%d: __BOGUS_D__" % desc_line in msg


def test_spawn_list_needs_agent_and_names_stack_agents(tmp_path):
    src = scratch_src(tmp_path, agent_edits={"vfx-td": ("May spawn: coder,", "May spawn: wizard, coder,")})
    with pytest.raises(ca.BuildError, match="wizard"):
        ca.convert(str(src), ctx_for(tmp_path), models())
    src = scratch_src(tmp_path / "b", agent_edits={"vfx-td": ("May spawn:", "Can spawn:")})
    with pytest.raises(ca.BuildError, match="no \"May spawn:\" list"):
        ca.convert(str(src), ctx_for(tmp_path), models())


def test_name_style_underscore(tmp_path):
    ctx = ctx_for(tmp_path)
    out = ca.convert(str(REPO), ctx, models(roles={"name_style": "underscore"}))
    assert "main_coder" in out["roles"] and "main-coder" not in out["roles"]
    assert out["agents_entries"]["code_reviewer"]["config_file"] == "%s/stack/agents/code_reviewer.toml" % ctx["codex_home"]
    assert set(out["astra_roles"]) == {n.replace("-", "_") for n in
                                       ("ninja-coder", "main-coder", "mathematician", "planner", "proof-checker",
                                        "security-auditor")}
    assert "main-coder" in out["policy"]["agents"] and "main_coder" not in out["policy"]["agents"]
    assert "code-reviewer" in out["policy"]["agents"]["main-coder"]["spawn"]
    spawn = re.search(r"May spawn:[^.]*\.", out["roles"]["main_coder"]["developer_instructions"]).group()
    assert "code_reviewer" in spawn and "code-reviewer" not in spawn
    assert "main_coder" in out["blackcat"]["instructions"] and "main-coder" not in out["blackcat"]["instructions"]


# ---------------------------------------------------------------------------------------- MCP servers
def test_mcp_servers_rendered_and_merged(converted):
    ctx, out = converted
    servers, stack = out["mcp_servers"], ctx["stack"]
    assert out["report"]["mcp_servers"]["libdocs"][:2] == ["biochem-engineer", "cg-artist"]
    assert servers["libdocs"] == {"command": ctx["uv"],
                                  "args": ["run", "--quiet", "--script", stack + "/mcp/libdocs_mcp.py"]}
    assert servers["mobilebuild"]["command"] == ctx["npx"]
    assert servers["blender"]["command"] == os.path.dirname(ctx["uv"]) + "/uvx"
    assert servers["playwright"]["args"][5].startswith(ctx["home"] + "/.cache/")
    assert servers["after-effects"]["args"] == [stack + "/mcp/vendor/after-effects-mcp/build/index.js"]


def test_with_stack_env_only_where_already_used(converted):
    ctx, out = converted
    wrapper = ctx["stack"] + "/bin/with-stack-env"
    used = {}
    for n in agent_names():
        for item in frontmatter(n).get("mcpServers") or []:
            (sid, spec), = item.items()
            used[sid] = spec
    for sid, t in out["mcp_servers"].items():
        if used[sid]["command"].endswith("/bin/with-stack-env"):
            assert t["command"] == wrapper
            assert t["args"][:2] == used[sid]["args"][:2] and t["args"][0] == "--only"
            assert t["env"]["STACK_ENV_FILE"] == ctx["codex_home"] + "/stack.env"
        else:
            assert t["command"] != wrapper and "STACK_ENV_FILE" not in t.get("env", {})
    assert out["mcp_servers"]["magg"]["env"]["MAGG_PATH"] == "%s/magg:%s/.magg" % (ctx["stack"], ctx["home"])


def test_mcp_conflict_stops_the_build(tmp_path):
    src = scratch_src(tmp_path, agent_edits={"coder": ('"__CLAUDE_DIR__/mcp/libdocs_mcp.py"]',
                                                       '"__CLAUDE_DIR__/mcp/libdocs_mcp.py", "--v2"]')})
    with pytest.raises(ca.BuildError, match="MCP server 'libdocs' is defined differently by .* and coder"):
        ca.convert(str(src), ctx_for(tmp_path), models())


@pytest.mark.parametrize("edit,needle", [
    (('      type: stdio\n      command: "__NPX__"\n      args: ["-y", "mobile',
      '      type: sse\n      command: "__NPX__"\n      args: ["-y", "mobile'), "unmapped transport type 'sse'"),
    (('      env:\n        MOBILEBUILD', '      timeout: 5\n      env:\n        MOBILEBUILD'), "unmapped key"),
    (('"mobilebuildmcp@2.7.1"', '"__WHO__"'), "unknown or unset placeholder __WHO__"),
])
def test_mcp_unmapped_input_stops(tmp_path, edit, needle):
    src = scratch_src(tmp_path, agent_edits={"mobile-engineer": edit})
    with pytest.raises(ca.BuildError, match=needle):
        ca.convert(str(src), ctx_for(tmp_path), models())


def test_http_server_gets_the_headers_helper(tmp_path):
    from test_agents_schema_contract import HTTP_AGENT
    ctx = ctx_for(tmp_path)
    out = ca.convert(str(scratch_src(tmp_path, extra_agents={"web-probe": HTTP_AGENT})), ctx, models())
    assert out["mcp_servers"]["exa"] == {
        "url": "https://mcp.exa.ai/mcp",
        "http_headers_helper": "%s/stack/bin/codex-mcp-headers exa" % ctx["codex_home"]}


def test_ctx_must_be_absolute_and_consistent(tmp_path):
    ctx = ctx_for(tmp_path)
    for bad in (dict(ctx, codex_home="rel"), dict(ctx, stack="/elsewhere/stack")):
        with pytest.raises(ca.BuildError, match="ctx"):
            ca.convert(str(REPO), bad, models())


# ---------------------------------------------------------------------------------------- codex-mcp-headers
SECRETS = "EXA_API_KEY=exa-key-123\nOTHER_SECRET=zz-other-999\nexport JINA_API_KEY='jina-456' # note\n"


def run_headers(scratch_home, *args, env_file=None, script=HEADERS_BIN):
    env = {"PATH": "/usr/bin:/bin", "HOME": str(scratch_home["home"])}
    if env_file is not None:
        env["STACK_ENV_FILE"] = str(env_file)
    return subprocess.run([sys.executable, str(script), *args], capture_output=True, text=True, env=env)


def stack_env(scratch_home, mode=0o600, text=SECRETS):
    p = scratch_home["codex_home"] / "stack.env"
    p.write_text(text)
    p.chmod(mode)
    return p


def test_headers_prints_only_the_servers_header(scratch_home):
    p = stack_env(scratch_home)
    r = run_headers(scratch_home, "exa", env_file=p)
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout) == {"x-api-key": "exa-key-123"}
    assert "zz-other-999" not in r.stdout + r.stderr and "jina-456" not in r.stdout + r.stderr
    r = run_headers(scratch_home, "--env-file", str(p), "jina")
    assert json.loads(r.stdout) == {"Authorization": "Bearer jina-456"}
    assert "exa-key-123" not in r.stdout and "zz-other-999" not in r.stdout
    r = run_headers(scratch_home, "--redact", "exa", env_file=p)
    assert json.loads(r.stdout) == {"x-api-key": "<redacted:11 chars>"}
    assert json.loads(run_headers(scratch_home, "wandb", env_file=p).stdout) == {}


def test_headers_default_path_in_the_installed_layout(scratch_home):
    stack_env(scratch_home)
    bindir = scratch_home["codex_home"] / "stack" / "bin"
    bindir.mkdir(parents=True)
    script = bindir / "codex-mcp-headers"
    shutil.copy2(HEADERS_BIN, script)
    assert os.access(HEADERS_BIN, os.X_OK)
    r = run_headers(scratch_home, "exa", script=script)
    assert json.loads(r.stdout) == {"x-api-key": "exa-key-123"}


@pytest.mark.parametrize("kind", ["0644", "symlink", "0640"])
def test_headers_refuse_an_unsafe_stack_env(scratch_home, kind):
    if kind == "symlink":
        real = scratch_home["home"] / "dotfiles.env"
        real.write_text(SECRETS)
        real.chmod(0o600)
        p = scratch_home["codex_home"] / "stack.env"
        p.symlink_to(real)
    else:
        p = stack_env(scratch_home, mode=int(kind, 8))
    r = run_headers(scratch_home, "exa", env_file=p)
    assert r.returncode == 1 and r.stdout == ""
    assert ("symlink" if kind == "symlink" else "chmod 600") in r.stderr
    assert "exa-key-123" not in r.stderr


def test_headers_usage_and_missing_file(scratch_home):
    assert run_headers(scratch_home, "nope").returncode == 2
    assert run_headers(scratch_home).returncode == 2
    r = run_headers(scratch_home, "exa", env_file=scratch_home["codex_home"] / "absent.env")
    assert r.returncode == 0 and json.loads(r.stdout) == {}
