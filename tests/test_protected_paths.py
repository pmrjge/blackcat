"""Tests for agent_guard.py's "protect" scan kind: a Bash-level write, delete, rename or mode
change (redirection, cp/mv/install/rsync, tee, dd, sed/perl -i, rm/unlink/rmdir, find -delete,
chmod/ln/touch/truncate, tar -x/unzip, inline python/node/perl code) is denied when it targets a
path already denied to the Read/Edit/Write tools (the stack's config dir: hooks/, bin/, agents/,
rules/, mcp/, magg/, skills/, CLAUDE.md, backup-*/, settings.json; the hook state dir; the
project's .git hooks/config and .claude settings). Claude Code's own protected-path check applies
to the Edit/Write tools, not to raw Bash, and bypassPermissions mode (the stack's default) skips
even that — this hook is the replacement, and it must not block ordinary Bash writes elsewhere.

Run: uv run --with pytest pytest -q tests/test_protected_paths.py
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC_HOOK = ROOT / "dot-claude" / "hooks" / "agent_guard.py"
SRC_SETTINGS = ROOT / "dot-claude" / "settings.json"


@pytest.fixture
def installed(tmp_path, monkeypatch):
    """A rendered, installed-looking config dir (__CLAUDE_DIR__ substituted for real) plus a
    project directory with its own .claude/, so the deny rules the hook reads actually resolve to
    real paths instead of the literal template placeholder. The process runs in the project (as
    the hook does) and the hook state lives under tmp_path/state."""
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    cfg = tmp_path / "claude"
    (cfg / "hooks").mkdir(parents=True)
    shutil.copy(SRC_HOOK, cfg / "hooks" / "agent_guard.py")
    settings = SRC_SETTINGS.read_text().replace("__CLAUDE_DIR__", str(cfg))
    (cfg / "settings.json").write_text(settings)
    proj = tmp_path / "proj"
    (proj / ".claude" / "agents").mkdir(parents=True)
    (proj / ".git").mkdir()
    monkeypatch.chdir(proj)
    sys.path.insert(0, str(cfg / "hooks"))
    sys.modules.pop("agent_guard", None)
    import agent_guard as g
    yield g, cfg, proj
    sys.path.remove(str(cfg / "hooks"))
    sys.modules.pop("agent_guard", None)


def test_redirect_into_hooks_or_settings_or_bin_denied(installed):
    g, cfg, proj = installed
    ev = {"cwd": str(proj)}
    for target, op in [(cfg / "hooks" / "agent_guard.py", ">"), (cfg / "settings.json", ">>"),
                       (cfg / "bin" / "mcp-headers", ">")]:
        got = g.protected_write_in("echo x %s %s" % (op, target), ev)
        assert got and got[0] == "protect", target


def test_write_commands_denied(installed):
    g, cfg, proj = installed
    ev = {"cwd": str(proj)}
    target = str(cfg / "hooks" / "agent_guard.py")
    cases = [
        "cp new.py %s" % target,
        "mv new.py %s" % target,
        "sed -i s/x/y/ %s" % target,
        "sed -i.bak s/x/y/ %s" % target,
        "tee %s <<< x" % target,
        "dd if=/dev/zero of=%s" % target,
        "cp -t %s new.py" % (cfg / "hooks"),
        "install -m 0644 new.py %s" % target,
    ]
    for cmd in cases:
        got = g.protected_write_in(cmd, ev)
        assert got and got[0] == "protect", cmd


def test_nested_shells_still_caught(installed):
    g, cfg, proj = installed
    ev = {"cwd": str(proj)}
    target = str(cfg / "hooks" / "agent_guard.py")
    for cmd in ["bash -c 'echo x > %s'" % target, "eval \"echo x > %s\"" % target,
               "sh -c \"sed -i s/x/y/ %s\"" % target]:
        got = g.protected_write_in(cmd, ev)
        assert got and got[0] == "protect", cmd


def test_project_git_and_claude_settings_denied(installed):
    g, cfg, proj = installed
    ev = {"cwd": str(proj)}
    for cmd in ["echo x > .git/config", "echo x > .claude/settings.json",
               "echo x > .claude/settings.local.json", "echo x > .claude/hooks/x.py"]:
        got = g.protected_write_in(cmd, ev)
        assert got and got[0] == "protect", cmd


def test_ordinary_writes_allowed(installed):
    g, cfg, proj = installed
    ev = {"cwd": str(proj)}
    for cmd in ["echo x > /tmp/whatever.txt", "cp foo.txt bar.txt", "echo hi",
               "echo x > .claude/agents/coder.md", "sed -i s/x/y/ README.md",
               "cp a.py b.py", "tee out.log <<< x", "git commit -am 'x'",
               # C1 widened the scan to deletes, renames and inline code: ordinary ones still pass
               "rm -rf build/", "mv a b", "find . -name '*.pyc' -delete",
               "python3 -c \"import os; os.remove('x.tmp')\"", "touch .claude/agents/x.md",
               "rm .claude-work/x", "echo .claude-work/ >> .git/info/exclude",
               "cp %s/agents/coder.md /tmp/coder.md" % cfg, "cat %s/settings.json" % cfg,
               "python3 -c \"print(open('%s/settings.json').read())\"" % cfg]:
        got = g.protected_write_in(cmd, ev)
        assert got is None, (cmd, got)


C1_TARGETS = ["agents/coder.md", "rules/claude-agent-stack.md", "mcp/libdocs_mcp.py",
              "magg/config.json", "skills/x/SKILL.md", "CLAUDE.md",
              "backup-20260101-000000-abc/settings.json", "stack.env", ".stack-manifest.json"]


@pytest.mark.parametrize("rel", C1_TARGETS)
def test_c1_config_dirs_protected(installed, rel):
    g, cfg, proj = installed
    got = g.protected_write_in("echo x > %s/%s" % (cfg, rel), {"cwd": str(proj)})
    assert got and got[0] == "protect", rel


def c1_deletes(cfg):
    return [
        "rm -rf {c}/agents", "rm {c}/CLAUDE.md", "unlink {c}/settings.json", "rmdir {c}/rules",
        "mv {c}/agents /tmp/x", "mv {c}/skills/a {c}/skills/b", "find {c}/skills -delete",
        "find {c} -name '*.md' -exec rm {{}} \\;", "chmod 000 {c}/hooks/agent_guard.py",
        "ln -sf /dev/null {c}/hooks/agent_guard.py", "truncate -s0 {c}/settings.json",
        "touch {c}/agents/new.md", "cd {c} && rm -rf agents", "cd {c}/agents; rm coder.md",
        "echo {c}/agents/a.md | xargs rm -f", "tar -xf a.tar -C {c}",
        "unzip -o a.zip -d {c}/skills",
        "python3 -c \"import os; os.remove('{c}/settings.json')\"",
        "python3 -c \"import shutil; shutil.rmtree('{c}/hooks')\"",
        "perl -e 'unlink \"{c}/CLAUDE.md\"'",
        "node -e \"require('fs').rmSync('{c}/agents',{{recursive:true}})\"",
        "python3 - <<'EOF'\nimport os\nos.remove('{c}/settings.json')\nEOF",
        "bash -c 'rm -rf {c}/skills'",
        # review of Part A: interpreters outside the first trigger list, and their write idioms
        "julia -e 'rm(\"{c}/settings.json\")'",
        "julia -e 'write(\"{c}/hooks/agent_guard.py\", \"x\")'",
        "lua -e 'os.remove(\"{c}/settings.json\")'",
        "luajit -e 'io.output(\"{c}/settings.json\")'",
        "Rscript -e 'file.remove(\"{c}/settings.json\")'",
        "Rscript -e 'cat(1, file=\"{c}/settings.json\")'",
        "Rscript -e 'write.csv(x, \"{c}/agents/a.md\")'",
        "Rscript -e 'writeLines(\"x\", \"{c}/rules/r.md\")'",
        "php -r 'file_put_contents(\"{c}/settings.json\", \"x\");'",
        "php -r '$f = fopen(\"{c}/settings.json\", \"w\");'",
        # review of Part B: the plain R interpreter
        "R -e 'file.remove(\"{c}/settings.json\")'",
        "R --slave -e 'file.copy(\"x\", \"{c}/settings.json\", overwrite=TRUE)'",
    ]


def test_c1_deletes_renames_and_mode_changes_denied(installed):
    g, cfg, proj = installed
    for tmpl in c1_deletes(cfg):
        cmd = tmpl.format(c=cfg)
        got = g.protected_write_in(cmd, {"cwd": str(proj)})
        assert got and got[0] == "protect", cmd


def test_c1_reading_config_in_code_is_not_a_write(installed):
    """Method calls named write (sys.stdout.write, process.stdout.write), fopen in read mode and
    Julia's write to stdout read the config dir: not protected writes."""
    g, cfg, proj = installed
    for tmpl in [
        "python3 -c 'import sys; sys.stdout.write(open(\"{c}/settings.json\").read())'",
        "node -e 'process.stdout.write(require(\"fs\").readFileSync(\"{c}/settings.json\", \"utf8\"))'",
        "php -r '$f = fopen(\"{c}/settings.json\", \"r\"); echo fread($f, 100);'",
        "julia -e 'write(stdout, read(\"{c}/settings.json\"))'",
    ]:
        cmd = tmpl.format(c=cfg)
        assert g.protected_write_in(cmd, {"cwd": str(proj)}) is None, cmd


def test_c1_hook_state_dir_protected(installed, tmp_path):
    g, cfg, proj = installed
    st = tmp_path / "state" / "claude-agent-stack"
    assert g.state_root() == str(st)
    for cmd in ["rm -rf %s/s1/blackcat" % st, "echo x > %s/s1/god.lock" % st, "rm -rf %s" % st,
                "mv %s/s1 /tmp/y" % st, "find %s -delete" % st.parent]:
        got = g.protected_write_in(cmd, {"cwd": str(proj)})
        assert got and got[0] == "protect", cmd


def test_installer_backups_protected(installed, tmp_path):
    """install.sh keeps its backups beside the state dir (the guard prunes idle state folders);
    agents can neither change them through Bash nor read them through the tools or the sandbox."""
    g, cfg, proj = installed
    bk = tmp_path / "state" / "claude-agent-stack-backups"
    assert g.backup_root() == str(bk)
    for cmd in ["rm -rf %s" % bk, "echo x > %s/20260101-000000-abc/files/settings.json" % bk,
                "mv %s/20260101-000000-abc /tmp/y" % bk, "chmod -R 777 %s" % bk]:
        got = g.protected_write_in(cmd, {"cwd": str(proj)})
        assert got and got[0] == "protect", cmd
    s = json.loads((ROOT / "dot-claude" / "settings.json").read_text())
    assert {"Read(/__STACK_BACKUPS__/**)", "Edit(/__STACK_BACKUPS__/**)"} <= set(s["permissions"]["deny"])
    fs = s["sandbox"]["filesystem"]
    assert "__STACK_BACKUPS__" in fs["denyRead"] and "__STACK_BACKUPS__" in fs["denyWrite"]


def run_hook(installed_hook_path, command, **env):
    ev = {"session_id": "t", "hook_event_name": "PreToolUse", "tool_name": "Bash",
          "tool_input": {"command": command}, "cwd": env.pop("cwd", None)}
    return subprocess.run([sys.executable, str(installed_hook_path), "no-push"],
                          input=json.dumps(ev), capture_output=True, text=True, timeout=30,
                          env=dict(os.environ, **env))


def test_hook_denies_protected_write_end_to_end(installed):
    g, cfg, proj = installed
    hook_path = cfg / "hooks" / "agent_guard.py"
    target = str(cfg / "settings.json")
    p = run_hook(hook_path, "echo x > %s" % target, cwd=str(proj), STACK_POLICY="off")
    assert p.returncode == 0, p.stderr
    out = json.loads(p.stdout)["hookSpecificOutput"]
    assert out["permissionDecision"] == "deny"
    assert "protected-path rule" in out["permissionDecisionReason"]


def test_hook_allows_ordinary_write_end_to_end(installed):
    g, cfg, proj = installed
    hook_path = cfg / "hooks" / "agent_guard.py"
    p = run_hook(hook_path, "echo x > /tmp/whatever.txt", cwd=str(proj))
    assert p.returncode == 0 and p.stdout == "", p.stderr


def test_settings_wire_ask_rules_and_protected_paths():
    s = json.loads(SRC_SETTINGS.read_text())
    ask = set(s["permissions"].get("ask") or [])
    # P3: scheduling and routines prompt even in bypassPermissions (explicit ask rules do)
    assert {"mcp__magg__magg_add_server", "mcp__magg__magg_load_kit",
            "mcp__magg__proxy", "CronCreate", "RemoteTrigger"} <= ask
    deny = set(s["permissions"]["deny"])
    assert {"Edit(.git/hooks/**)", "Edit(.git/config)", "Edit(.claude/settings.json)",
            "Edit(.claude/settings.local.json)", "Edit(.claude/hooks/**)"} <= deny
    # a whole-.git deny would become a sandbox denyWrite on the project's .git and break commits
    assert "Edit(.git/**)" not in deny
    # agents/, skills/ etc. in a project's .claude/ stay editable: only the settings/hooks are
    # locked down, matching the global config's own scope
    assert "Edit(.claude/**)" not in deny
    # C1: the stack's own config is denied to Edit/Write
    for rel in ("hooks/**", "bin/**", "settings.json", "agents/**", "rules/**", "mcp/**",
                "magg/**", "skills/**", "CLAUDE.md", "backup-*/**", "stack-plugins/**"):
        assert "Edit(/__CLAUDE_DIR__/%s)" % rel in deny, rel
    assert "Edit(~/.local/state/claude-agent-stack/**)" in deny
    # C4/C8: secrets and backups are Read-denied (a Read deny also blocks Edit/Write)
    for r in ("Read(/__CLAUDE_DIR__/**/stack.env)", "Read(/__CLAUDE_DIR__/backup-*/**)",
              "Read(~/.git-credentials)", "Read(~/.npmrc)", "Read(~/.pypirc)",
              "Read(~/.docker/config.json)", "Read(~/.kube/**)", "Read(~/.gnupg/**)",
              "Read(~/.config/gcloud/**)", "Read(~/.ssh/**)", "Read(~/.aws/**)",
              "Read(~/.netrc)", "Read(~/.config/gh/hosts.yml)"):
        assert r in deny, r


def test_settings_sandbox_block():
    s = json.loads(SRC_SETTINGS.read_text())
    sb = s["sandbox"]
    assert sb["enabled"] is True and sb["allowUnsandboxedCommands"] is False
    fs = sb["filesystem"]
    # sandbox paths: `/` absolute (the installer renders __CLAUDE_DIR__ absolute), `~/` home
    assert "__CLAUDE_DIR__" in fs["denyWrite"]
    assert "~/.local/state/claude-agent-stack" in fs["denyWrite"]
    assert {"__CLAUDE_DIR__/**/stack.env", "__CLAUDE_DIR__/backup-*"} <= set(fs["denyRead"])
    assert "~/.cache" in fs["allowWrite"]                  # uv, pip, HF caches keep working
    for lst in ("allowWrite", "denyWrite", "denyRead"):
        assert len(fs[lst]) == len(set(fs[lst])), lst
        for p in fs[lst]:
            assert p.startswith(("~/", "__CLAUDE_DIR__", "__STACK_BACKUPS__")), p
    net = sb["network"]
    assert net["strictAllowlist"] is True
    doms = net["allowedDomains"]
    assert len(doms) == len(set(doms))
    assert {"pypi.org", "files.pythonhosted.org", "registry.npmjs.org", "github.com",
            "huggingface.co", "crates.io", "proxy.golang.org"} <= set(doms)
    known = {"enabled", "failIfUnavailable", "autoAllowBashIfSandboxed", "excludedCommands",
             "allowUnsandboxedCommands", "enableWeakerNestedSandbox",
             "enableWeakerNetworkIsolation", "allowAppleEvents", "ignoreViolations", "ripgrep",
             "filesystem", "network", "credentials"}
    assert set(sb) <= known
    assert set(fs) <= {"allowWrite", "denyWrite", "denyRead", "allowRead", "disabled"}
    # C6: forge tokens never reach a sandboxed command
    env_deny = {e["name"] for e in sb["credentials"]["envVars"] if e["mode"] == "deny"}
    assert {"GITHUB_TOKEN", "GH_TOKEN", "GITLAB_TOKEN"} <= env_deny
    assert set(net) <= {"allowedDomains", "deniedDomains", "strictAllowlist", "allowLocalBinding",
                        "allowUnixSockets", "allowAllUnixSockets", "allowMachLookup",
                        "httpProxyPort", "socksProxyPort", "tlsTerminate"}


def test_settings_wire_blackcat_guard_and_memory_hooks():
    s = json.loads(SRC_SETTINGS.read_text())
    pre = s["hooks"]["PreToolUse"]
    cmds = [(g["matcher"], h["command"]) for g in pre for h in g["hooks"]]
    assert [m for m, c in cmds if c.endswith("blackcat-guard --settings")] == ["*"]
    assert any(m == "mcp__neural-memory__nmem_remember" and c.endswith('agent_guard.py"')
               for m, c in cmds)
    assert len(cmds) == len(set(cmds))
