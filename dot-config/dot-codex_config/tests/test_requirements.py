"""lib/requirements.py: the optional machine-wide tier (DESIGN.md §4.5, §9 step 6). Every path is under
tmp_path: --etc-dir and --managed-dir point there, and nothing reads or writes the real /etc."""
from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import tomllib

import pytest

from _rules_helpers import (definition, make_src, rust_fields, schema_errors, tree_state, vendored)
from conftest import LIB, load_lib

rq = load_lib("requirements")


@pytest.fixture
def env(tmp_path, monkeypatch):
    home = tmp_path / "home"
    (home / ".codex").mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("XDG_STATE_HOME", str(home / ".local" / "state"))
    etc = tmp_path / "etc" / "codex"
    managed = tmp_path / "Library" / "Application Support" / "claude-agent-stack" / "codex-hooks"
    src = make_src(tmp_path / "src")
    out = tmp_path / "build"
    argv = ["--codex-home", str(home / ".codex"), "--home", str(home), "--src", str(src),
            "--out", str(out), "--etc-dir", str(etc), "--managed-dir", str(managed)]
    return {"tmp": tmp_path, "home": home, "etc": etc, "managed": managed, "src": src, "out": out,
            "argv": argv}


def run(argv):
    buf = io.StringIO()
    assert rq.run(argv, out_stream=buf) == 0
    return buf.getvalue()


def doc_of(env):
    return tomllib.loads((env["out"] / "requirements.toml").read_text())


def test_writes_only_inside_out(env):
    before = tree_state(env["tmp"], skip=env["out"])
    run(env["argv"])
    after = tree_state(env["tmp"], skip=env["out"])
    assert before == after
    assert not env["etc"].exists() and not env["managed"].exists()
    assert sorted(os.listdir(env["out"])) == ["managed-hooks", "requirements.toml"]


def test_requirements_keys_and_values(env):
    run(env["argv"])
    d = doc_of(env)
    home, ch = str(env["home"]), str(env["home"] / ".codex")
    assert d["allowed_approval_policies"] == ["on-request", "never"]
    assert d["allowed_sandbox_modes"] == ["read-only", "workspace-write"]
    assert d["allowed_permission_profiles"] == {"claude-agent-stack": True, ":workspace": True,
                                                ":read-only": True}
    assert d["allowed_web_search_modes"] == ["disabled"]
    assert d["allow_managed_hooks_only"] is False
    assert d["features"] == {"hooks": True}
    deny = d["permissions"]["filesystem"]["deny_read"]
    assert ch + "/auth.json" in deny and ch + "/stack.env" in deny and home + "/.ssh" in deny
    assert home + "/**/.env" in deny and all(p.startswith("/") for p in deny)
    rules = d["rules"]["prefix_rules"]
    assert len(rules) == 30 and {r["decision"] for r in rules} == {"forbidden"}
    pats = [[t.get("token") or t.get("any_of") for t in r["pattern"]] for r in rules]
    assert ["git", "push"] in pats and ["gh", "pr", "create"] in pats
    assert ["gh", "release", "upload"] in pats and ["bash", "-x", "install.sh"] not in pats
    for r in rules:
        for t in r["pattern"]:
            assert len(t) == 1 and set(t) <= {"token", "any_of"}
    assert "MACHINE-WIDE" in (env["out"] / "requirements.toml").read_text().splitlines()[1]
    assert any(":workspace" in line and line.startswith("#")
               for line in (env["out"] / "requirements.toml").read_text().splitlines())


def test_managed_hooks_run_the_guard_in_global_scope(env):
    run(env["argv"])
    hooks = doc_of(env)["hooks"]
    assert hooks["managed_dir"] == str(env["managed"])
    assert set(hooks) == {"managed_dir", "PreToolUse", "PermissionRequest"}
    for event, mode in (("PreToolUse", "pre_tool_use"), ("PermissionRequest", "permission_request")):
        (group,) = hooks[event]
        assert schema_errors(group, definition("MatcherGroup")) == []
        (h,) = group["hooks"]
        assert h["command"] == "/bin/sh '%s/codex-hook' %s --scope global" % (env["managed"], mode)


def test_managed_hooks_folder_is_a_flat_copy(env):
    run(env["argv"])
    mh = env["out"] / "managed-hooks"
    assert sorted(os.listdir(mh)) == ["codex-hook", "codex_guard.py", "guard.json", "stack_io.py",
                                      "toolsmith_policy.py"]
    stub = env["src"] / "dot-config/dot-codex_config/hooks/codex-hook"
    assert (mh / "codex-hook").read_bytes() == stub.read_bytes()
    assert os.stat(mh / "codex-hook").st_mode & 0o777 == 0o755
    g = json.loads((mh / "guard.json").read_text())
    ch = str(env["home"] / ".codex")
    assert g["schema"] == 1 and g["codex_home"] == ch and g["caps"] == {"max_spawns": 8}
    assert g["protected_roots"] == [ch, str(env["home"] / ".agents"),
                                    str(env["home"] / ".local/state/codex-agent-stack")]
    assert ch + "/auth.json" in g["credentials"]["paths"]
    assert g["toolsmith_wrapper"] == ch + "/stack/bin/stack-install"


def test_prints_root_commands_and_warning(env):
    text = run(env["argv"])
    assert text.startswith("MACHINE-WIDE")
    cmds = [line.strip() for line in text.splitlines() if line.strip().startswith("sudo ")]
    assert len(cmds) == 4
    assert cmds[0].startswith("sudo install -d -o root -g wheel -m 0755 ")
    assert "'%s'" % env["managed"] in cmds[0]          # the space in the path is quoted
    # the managed hooks ship no __pycache__: compiled once as root with the stub's interpreter
    assert cmds[2].startswith("sudo /usr/bin/python3 -I -c ") and "CHECKED_HASH" in cmds[2]
    assert cmds[2].endswith("'%s'/*.py" % env["managed"])
    assert cmds[3].endswith("%s %s" % (env["out"] / "requirements.toml",
                                       env["etc"] / "requirements.toml"))


def test_existing_etc_file_is_never_replaced(env):
    env["etc"].mkdir(parents=True)
    mine = env["etc"] / "requirements.toml"
    mine.write_text('allowed_web_search_modes = ["cached"]\n')
    before = tree_state(env["tmp"], skip=env["out"])
    text = run(env["argv"])
    assert tree_state(env["tmp"], skip=env["out"]) == before
    assert mine.read_text() == 'allowed_web_search_modes = ["cached"]\n'
    assert "NEVER replaced" in text and '-allowed_web_search_modes = ["cached"]' in text
    assert '+allowed_web_search_modes = ["disabled"]' in text
    assert not any(line.strip().startswith("sudo") and str(mine) in line
                   for line in text.splitlines())
    assert "Merge" in text


def test_missing_guard_file_is_an_error(env):
    os.unlink(env["src"] / "dot-config" / "dot-claude" / "hooks" / "stack_io.py")
    with pytest.raises(rq.BuildError):
        run(env["argv"])
    assert not env["out"].exists()            # nothing written before the inputs are complete


@pytest.mark.parametrize("bad", ["../x.py", "/etc/passwd", "dot-config/dot-claude/other/x.py"])
def test_support_files_must_name_dot_claude_hooks(env, bad):
    (env["src"] / "dot-config/dot-codex_config/hooks/SUPPORT_FILES").write_text(bad + "\n")
    with pytest.raises(rq.BuildError):
        run(env["argv"])


def test_out_inside_etc_or_system_is_refused(env):
    for out in (env["etc"] / "build", env["managed"], "/etc/codex-build", "/Library/x"):
        argv = list(env["argv"])
        argv[argv.index("--out") + 1] = str(out)
        with pytest.raises(rq.BuildError):
            run(argv)
    assert not env["etc"].exists()


def test_cli_exit_codes(env):
    script = str(LIB / "requirements.py")
    ok = subprocess.run([sys.executable, script] + env["argv"], capture_output=True, text=True)
    assert ok.returncode == 0, ok.stderr
    usage = subprocess.run([sys.executable, script, "--home", "rel"], capture_output=True, text=True)
    assert usage.returncode == 2
    bad = list(env["argv"])
    bad[bad.index("--managed-dir") + 1] = "/Library/it's"
    assert subprocess.run([sys.executable, script] + bad, capture_output=True).returncode == 2
    os.unlink(env["src"] / "dot-config" / "dot-codex_config" / "templates" / "guard.base.json")
    miss = subprocess.run([sys.executable, script] + env["argv"], capture_output=True, text=True)
    assert miss.returncode == 1 and "guard.base.json" in miss.stderr


def test_never_runs_sudo(env, monkeypatch):
    calls = []
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: calls.append(a) or None)
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: calls.append(a) or None)
    monkeypatch.setattr(os, "system", lambda *a: calls.append(a) or 0)
    run(env["argv"])
    assert calls == []


def test_requirements_schema_contract(env):
    """Every emitted key exists in the vendored Codex source at rust-v0.160.1; values use the enums
    of config.schema.json where the requirement types are shared with config.toml."""
    run(env["argv"])
    d = doc_of(env)
    top = rust_fields(vendored("config_requirements.ConfigRequirementsToml.extract.rs"),
                      "ConfigRequirementsToml")
    assert set(d) <= top, set(d) - top
    perm = vendored("config_requirements.permissions.extract.rs")
    assert set(d["permissions"]) <= rust_fields(perm, "PermissionsRequirementsToml")
    assert set(d["permissions"]["filesystem"]) <= {"deny_read"}
    hooks = vendored("hook_config.extract.rs")
    assert set(d["hooks"]) <= rust_fields(hooks, "ManagedHooksRequirementsToml") | \
        rust_fields(hooks, "HookEventsToml")
    rq_src = vendored("requirements_exec_policy.rs")
    assert set(d["rules"]) <= rust_fields(rq_src, "RequirementsExecPolicyToml")
    for r in d["rules"]["prefix_rules"]:
        assert set(r) <= rust_fields(rq_src, "RequirementsExecPolicyPrefixRuleToml")
        for t in r["pattern"]:
            assert set(t) <= rust_fields(rq_src, "RequirementsExecPolicyPatternTokenToml")
    enums = vendored("config_requirements.enums.extract.rs")
    for mode in d["allowed_sandbox_modes"]:
        assert '#[serde(rename = "%s")]' % mode in enums
        assert schema_errors(mode, definition("SandboxMode")) == []
    for m in d["allowed_web_search_modes"]:
        assert schema_errors(m, definition("WebSearchMode")) == []
    for a in d["allowed_approval_policies"]:
        assert schema_errors(a, definition("AskForApproval")) == []
    from _rules_helpers import SCHEMA
    assert set(d["features"]) <= set(SCHEMA["properties"]["features"]["properties"])
    builtin = vendored("protocol_models.builtin_profiles.extract.rs")
    for pid in d["allowed_permission_profiles"]:
        assert pid == "claude-agent-stack" or '"%s"' % pid in builtin
    assert '":danger-full-access"' in builtin and ":danger-full-access" not in \
        d["allowed_permission_profiles"]
