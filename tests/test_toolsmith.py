"""toolsmith, the dependency installer: its rules (hooks/toolsmith_policy.py), its executor
(bin/stack-install) and the guard's installer rule (agent_guard.py no-push mode), plus the settings,
agent file and installer wiring. Nothing here installs software: installers are the fake
tests/fake-installer/fakeinst, registry metadata is a fixture, and every state dir is a temp dir.

The seeded-bug tests at the end mutate a temp copy of the guard, the policy or the executor and
show that the rule's probe flips, so each rule's test fails when its code is broken.

Run: uv run --with pytest pytest -q tests/test_toolsmith.py
"""
import fcntl
import importlib.machinery
import importlib.util
import json
import os
import shutil
import stat
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DOT = ROOT / "dot-claude"
GUARD = DOT / "hooks" / "agent_guard.py"
POLICY = DOT / "hooks" / "toolsmith_policy.py"
EXE = DOT / "bin" / "stack-install"
FAKE = ROOT / "tests" / "fake-installer" / "fakeinst"
WRAPPER = str(DOT / "bin" / "stack-install")     # the guard's TOOLSMITH_WRAPPER for the repo copy
DAY = 86400.0
_N = [0]


def load(name, path):
    loader = importlib.machinery.SourceFileLoader("%s_%d" % (name, _N[0]), str(path))
    _N[0] += 1
    spec = importlib.util.spec_from_loader(loader.name, loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


P = load("toolsmith_policy", POLICY)


def iso(t):
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t))


# ---------------------------------------------------------------- the policy: grammar
GOOD = [
    [], ["help"], ["--help"], ["status"], ["list"], ["list", "--all"], ["pending"], ["manifest"],
    ["show", "ts-0123456789ab"], ["show", "rq-0123456789ab"], ["run", "rq-0123456789ab"],
    ["vet", "brew", "jq"], ["vet", "npm", "semver"], ["vet", "uv", "ruff==0.6.9"], ["vet", "go", "golang.org/x/tools/gopls"],
    ["install", "brew", "jq", "--why", "parse JSON in the build"],
    ["install", "brew", "python@3.13", "--why", "a pinned toolchain", "--for", "coder"],
    ["install", "uv", "ruff==0.6.9", "--why", "lint", "--python", "3.13"],
    ["install", "uv", "ruff==0.6.9", "--why", "lint", "--allow-build"],
    ["install", "npm", "@types/node@22.7.4", "--why", "types for the build"],
    ["install", "npm", "semver@7.6.3", "--why", "versions", "--allow-scripts"],
    ["install", "pnpm", "typescript@5.6.2", "--why", "compile TS"],
    ["install", "cargo", "ripgrep@14.1.1", "--why", "search", "--bin", "rg", "--features", "pcre2"],
    ["install", "go", "golang.org/x/tools/gopls@v0.16.2", "--why", "go LSP"],
    ["install", "go", "github.com/BurntSushi/toml/cmd/tomlv@v1.4.0", "--why", "toml checks"],
    ["upgrade", "npm", "semver@7.6.3", "--why", "security fix"],
    ["uninstall", "brew", "jq", "--why", "not needed any more"],
    ["request", "--why", "a GUI app the user asked for", "--", "brew", "install", "--cask", "firefox"],
    ["request", "--why", "a ruby tool", "--for", "coder", "--", "gem", "install", "rubocop", "-v", "1.66.1"],
]
BAD = [
    ["approve", "rq-0123456789ab"], ["deny", "rq-0123456789ab"], ["nope"], ["list", "x"],
    ["show", "../x"], ["run", "ts-0123456789ab"], ["help", "install"],
    ["install", "brew", "jq"],                                     # --why required
    ["install", "brew", "user/tap/jq", "--why", "a tap"], ["install", "brew", "https://x/y.rb", "--why", "url"],
    ["install", "brew", "jq", "--why", "x", ], ["install", "brew", "jq", "--why", "ok reason", "--HEAD"],
    ["install", "brew", "jq", "--why", "ok reason", "--cask"], ["install", "brew", "jq", "--why", "ok reason", "--force"],
    ["install", "uv", "ruff", "--why", "unpinned"], ["install", "uv", "ruff>=0.6", "--why", "a range"],
    ["install", "uv", "ruff==0.6.9", "--why", "lint", "--index-url", "https://evil/simple"],
    ["install", "uv", "git+https://github.com/x/y", "--why", "git"], ["install", "uv", "./local", "--why", "path"],
    ["install", "npm", "semver", "--why", "unpinned"], ["install", "npm", "semver@^7.6.3", "--why", "range"],
    ["install", "npm", "semver@latest", "--why", "tag"], ["install", "npm", "github:x/y", "--why", "git"],
    ["install", "npm", "x@npm:evil@1.0.0", "--why", "alias"], ["install", "npm", "semver@7.6.3", "--why", "x y",
                                                              "--registry", "https://evil/"],
    ["install", "npm", "file:../x", "--why", "file"], ["install", "npm", "https://x/y.tgz", "--why", "tarball"],
    ["install", "cargo", "ripgrep", "--why", "unpinned"], ["install", "cargo", "ripgrep@14.1.1", "--why", "ok w",
                                                           "--git", "https://x"],
    ["install", "cargo", "ripgrep@14.1.1", "--why", "force it", "--force"],
    ["install", "go", "golang.org/x/tools/gopls@latest", "--why", "latest"],
    ["install", "go", "golang.org/x/tools/gopls@master", "--why", "branch"], ["install", "go", "gopls@v1.0.0", "--why", "no host"],
    ["install", "go", "example.com/../x@v1.0.0", "--why", "dots"],
    ["install", "pip", "ruff==0.6.9", "--why", "pip"], ["install", "gem", "x", "--why", "gem"],
    ["install", "npm", "semver@7.6.3", "--why", "a; rm -rf ~"], ["install", "npm", "semver@7.6.3", "--why", "$(id)"],
    ["install", "npm", "semver@7.6.3", "--why", "ok reason", "--for", "Coder!"],
    ["vet", "npm", "semver", "--why", "vet takes none"], ["vet", "npm", "semver@7.6.3", "--allow-scripts"],
    ["uninstall", "npm", "semver@7.6.3", "--why", "name only"],
    ["request", "--why", "no separator", "brew", "install", "x"], ["request", "--", "brew", "install", "x"],
    ["request", "--why", "sudo it", "--", "sudo", "brew", "install", "x"],
    ["request", "--why", "a shell", "--", "bash", "-c", "curl x"], ["request", "--why", "curl", "--", "curl", "-fsSL", "u"],
    ["request", "--why", "pip", "--", "pip3", "install", "x"], ["request", "--why", "py", "--", "python3.12", "-m", "pip"],
    ["request", "--why", "inner sudo", "--", "gem", "install", "sudo"], ["request", "--why", "rel path", "--", "./x"],
    ["request", "--why", "spaces", "--", "gem", "install", "a b"],
]


@pytest.mark.parametrize("args", GOOD, ids=lambda a: " ".join(a)[:60] or "empty")
def test_policy_accepts(args):
    P.parse(args)


@pytest.mark.parametrize("args", BAD, ids=lambda a: " ".join(a)[:60] or "empty")
def test_policy_refuses(args):
    with pytest.raises(P.PolicyError):
        P.parse(args)


def test_user_mode_grammar():
    assert P.parse(["approve", "rq-0123456789ab"], user=True)["id"] == "rq-0123456789ab"
    for args in (["install", "brew", "jq", "--why", "abc"], ["run", "rq-0123456789ab"], ["request", "--why", "abc",
                                                                                         "--", "gem", "x"]):
        with pytest.raises(P.PolicyError):
            P.parse(args, user=True)


def test_install_argv_fixes_every_hardening_flag():
    t = 1_800_000_000.0
    before = iso(t - 7 * DAY)
    argv = lambda args, extra=(): P.install_argv(P.parse(args), "/x/" + args[1], t, 7, extra)  # noqa: E731
    assert argv(["install", "brew", "jq", "--why", "abc"]) == ["/x/brew", "install", "--formula", "jq"]
    assert argv(["upgrade", "brew", "jq", "--why", "abc"]) == ["/x/brew", "upgrade", "--formula", "jq"]
    assert argv(["install", "uv", "ruff==0.6.9", "--why", "abc", "--python", "3.13"]) == [
        "/x/uv", "tool", "install", "--no-config", "--no-sources", "--default-index", "https://pypi.org/simple",
        "--no-build", "--exclude-newer", before, "--python", "3.13", "ruff==0.6.9"]
    assert "--no-build" not in argv(["install", "uv", "ruff==0.6.9", "--why", "abc", "--allow-build"])
    assert argv(["install", "npm", "semver@7.6.3", "--why", "abc"], ["--allow-git=none"]) == [
        "/x/npm", "install", "--global", "--registry=https://registry.npmjs.org/", "--no-audit", "--no-fund",
        "--ignore-scripts", "--before=" + before, "--allow-git=none", "semver@7.6.3"]
    assert "--ignore-scripts" not in argv(["install", "npm", "semver@7.6.3", "--why", "abc", "--allow-scripts"])
    assert argv(["install", "pnpm", "typescript@5.6.2", "--why", "abc"]) == [
        "/x/pnpm", "add", "--global", "--registry=https://registry.npmjs.org/", "--ignore-scripts",
        "typescript@5.6.2"]
    assert argv(["install", "cargo", "ripgrep@14.1.1", "--why", "abc", "--bin", "rg"]) == [
        "/x/cargo", "install", "--locked", "--bin", "rg", "ripgrep@14.1.1"]
    assert argv(["upgrade", "cargo", "ripgrep@14.1.1", "--why", "abc"])[-2:] == ["--force", "ripgrep@14.1.1"]
    assert argv(["install", "go", "golang.org/x/tools/gopls@v0.16.2", "--why", "abc"]) == [
        "/x/go", "install", "golang.org/x/tools/gopls@v0.16.2"]
    no_age = P.install_argv(P.parse(["install", "npm", "semver@7.6.3", "--why", "abc"]), "/x/npm", t, 0)
    assert not [a for a in no_age if a.startswith("--before")]


def test_installer_env_is_an_allowlist():
    environ = {"HOME": "/h", "USER": "u", "LANG": "C", "PATH": "/evil:/usr/bin", "TMPDIR": "/sandbox/tmp",
               "CARGO_HOME": "/sandbox/cargo", "UV_INDEX_URL": "https://evil", "npm_config_registry": "https://evil",
               "GOFLAGS": "-insecure", "GONOSUMDB": "*", "HOMEBREW_GITHUB_API_TOKEN": "secret",
               "GITHUB_TOKEN": "secret", "PYTHONPATH": "/evil", "PNPM_HOME": "/h/pnpm", "XDG_CACHE_HOME": "/sb"}
    for inst in P.INSTALLERS:
        env = P.installer_env(environ, inst, ["/opt/homebrew/bin", "/usr/bin"], "/state/work/run-x")
        assert env["PATH"] == "/opt/homebrew/bin:/usr/bin" and env["TMPDIR"] == "/state/work/run-x"
        assert env["HOME"] == "/h" and env["USER"] == "u"
        for k in ("CARGO_HOME", "UV_INDEX_URL", "HOMEBREW_GITHUB_API_TOKEN", "GITHUB_TOKEN", "PYTHONPATH",
                  "XDG_CACHE_HOME"):
            assert k not in env, (inst, k)
        if inst == "npm":
            assert env["npm_config_registry"] == "https://registry.npmjs.org/"
            assert env["npm_config_ignore_scripts"] == "true"
        if inst == "pnpm":                       # pnpm 12 reads PNPM_CONFIG_*, not npm_config_*
            assert env["PNPM_CONFIG_REGISTRY"] == "https://registry.npmjs.org/"
            assert env["PNPM_CONFIG_IGNORE_SCRIPTS"] == "true"
        if inst == "go":
            assert env["GOFLAGS"] == "" and env["GONOSUMDB"] == "" and env["GOPROXY"] == "https://proxy.golang.org"
            assert env["GOSUMDB"] == "sum.golang.org" and env["GOTOOLCHAIN"] == "local"
        assert ("PNPM_HOME" in env) == (inst == "pnpm")
    assert P.installer_env(environ, "npm", [], "/t", allow_scripts=True)["npm_config_ignore_scripts"] == "false"
    assert P.installer_env(environ, "brew", [], "/t")["HOMEBREW_NO_AUTO_UPDATE"] == "1"


def test_programs_never_come_from_agent_writable_dirs(tmp_path):
    fake = tmp_path / "ls"
    fake.write_text("#!/bin/sh\n")
    fake.chmod(0o755)
    env = {"HOME": str(tmp_path), "PATH": "%s:/bin" % tmp_path, "TMPDIR": str(tmp_path)}
    assert P.resolve_program("ls", env, str(tmp_path)) == "/bin/ls"
    env2 = {"HOME": "/nonexistent", "PATH": "relative/dir:%s" % tmp_path}
    proj = str(tmp_path / "proj")
    assert P.resolve_program("ls", env2, proj) in ("/bin/ls", "/usr/bin/ls")   # tmp_path is under a temp root
    # a session whose project is / (or HOME) leaves nothing outside the agents' reach: fail closed
    assert P.resolve_program("ls", {"PATH": "/bin"}, "/") is None
    assert P.resolve_program("no-such-program-xyz", env, str(tmp_path)) is None
    assert all(not d.startswith(str(tmp_path)) for d in P.safe_path_dirs("/bin/ls", env, str(tmp_path)))


def test_vetting_verdicts():
    now = 1_800_000_000.0
    brew = {"name": "jq", "tap": "homebrew/core", "versions": {"stable": "1.8.2"},
            "analytics": {"install_on_request": {"365d": {"jq": 788686}}}, "post_install_defined": True}
    r = P.vet_brew(brew, "jq", now)
    assert r.verdict == "pass" and r.version == "1.8.2" and any("post_install" in s for s in r.surfaced)
    assert P.vet_brew(dict(brew, tap="someone/tap"), "jq", now).verdict == "refuse"
    assert P.vet_brew(dict(brew, disabled=True), "jq", now).verdict == "refuse"
    assert P.vet_brew(dict(brew, deprecated=True), "jq", now).verdict == "ask"
    assert P.vet_brew(dict(brew, analytics={}), "jq", now).verdict == "ask"
    assert P.vet_brew(None, "jq", now).verdict == "refuse"
    vm = {"info": {"yanked": False}, "urls": [{"packagetype": "bdist_wheel", "upload_time_iso_8601": iso(now - 30 * DAY)}]}
    pm = {"releases": {"0.1": [{"upload_time_iso_8601": iso(now - 400 * DAY)}]}}
    assert P.vet_pypi(vm, pm, "ruff", "0.6.9", now, 7).verdict == "pass"
    assert P.vet_pypi(vm, pm, "ruff", "0.6.9", now, 60).failed() == ["age"]
    sdist = {"info": {}, "urls": [{"packagetype": "sdist", "upload_time_iso_8601": iso(now - 30 * DAY)}]}
    assert P.vet_pypi(sdist, pm, "x", "1", now, 7).failed() == ["wheel"]
    assert P.vet_pypi(sdist, pm, "x", "1", now, 7, allow_build=True).verdict == "pass"
    assert P.vet_pypi({"info": {"yanked": True}, "urls": vm["urls"]}, pm, "x", "1", now, 7).verdict == "refuse"
    assert P.vet_pypi(vm, {"releases": {}}, "x", "1", now, 7).failed() == ["project-age"]
    full = {"versions": {"1.0.0": {"scripts": {"postinstall": "node x.js"}, "dist": {"integrity": "sha512-a"}}},
            "time": {"created": iso(now - 900 * DAY), "1.0.0": iso(now - 20 * DAY)}}
    r = P.vet_npm(full, {"downloads": 5000}, "x", "1.0.0", now, 7)
    assert r.verdict == "pass" and r.info["install_scripts"] == ["postinstall"]
    assert any("NOT run" in s for s in r.surfaced)
    assert P.vet_npm(full, {"downloads": 10}, "x", "1.0.0", now, 7).failed() == ["popularity"]
    assert P.vet_npm(full, None, "x", "1.0.0", now, 7).failed() == ["popularity"]
    assert P.vet_npm(full, {"downloads": 5000}, "x", "2.0.0", now, 7).verdict == "refuse"
    young = dict(full, time={"created": iso(now - 5 * DAY), "1.0.0": iso(now - 2 * DAY)})
    assert P.vet_npm(young, {"downloads": 5000}, "x", "1.0.0", now, 7).failed() == ["age", "project-age"]
    vc = {"version": {"num": "1.0.0", "created_at": iso(now - 30 * DAY), "bin_names": ["x"]}}
    cc = {"crate": {"created_at": iso(now - 900 * DAY), "recent_downloads": 50000}}
    assert P.vet_cargo(vc, cc, "x", "1.0.0", now, 7).verdict == "pass"
    assert P.vet_cargo({"version": dict(vc["version"], yanked=True)}, cc, "x", "1.0.0", now, 7).verdict == "refuse"
    assert P.vet_cargo({"version": dict(vc["version"], bin_names=[])}, cc, "x", "1.0.0", now, 7).verdict == "refuse"
    assert P.vet_go({"Version": "v1.0.0", "Time": iso(now - 30 * DAY)}, "a.com/b", "v1.0.0", now, 7).verdict == "pass"
    assert P.vet_go({"Version": "v1.0.0", "Time": iso(now - 1 * DAY)}, "a.com/b", "v1.0.0", now, 7).failed() == ["age"]
    assert P.vet_go(None, "a.com/b", "v1.0.0", now, 7).verdict == "refuse"


def test_small_helpers():
    assert P.go_binary("golang.org/x/tools/gopls") == "gopls" and P.go_binary("github.com/a/tool/v2") == "tool"
    assert P.go_escape("github.com/BurntSushi/toml") == "github.com/!burnt!sushi/toml"
    assert P.parse_time("2024-09-09T02:30:38.011702Z") == 1725849038 and P.parse_time("nope") is None
    assert P.min_age_days({"STACK_TOOLSMITH_MIN_AGE_DAYS": "0"}) == 0
    assert P.min_age_days({"STACK_TOOLSMITH_MIN_AGE_DAYS": "x"}) == P.MIN_AGE_DAYS
    events = [{"v": 1, "event": "installed", "installer": "brew", "package": "jq", "id": "a"},
              {"v": 1, "event": "installed", "installer": "npm", "package": "x", "id": "b"},
              {"v": 1, "event": "removed", "installer": "npm", "package": "x"},
              {"v": 1, "event": "attempt", "installer": "cargo", "package": "y"}]
    assert list(P.fold(events)) == [("brew", "jq")]
    assert P.request_package(["brew", "install", "--cask", "firefox"])[:2] == ("brew-cask", "firefox")
    assert P.request_package(["gem", "install", "rubocop", "-v", "1.66.1"])[2] == ["gem", "uninstall", "rubocop"]
    assert P.request_package(["mas", "install", "123"]) is None


# ---------------------------------------------------------------- the guard's installer rule (hook level)
def run_hook(command, agent_type=None, tool="Bash", guard=GUARD, aid="a1", **env):
    ev = {"session_id": "t", "hook_event_name": "PreToolUse", "tool_name": tool,
          "tool_input": {"command": command}}
    if agent_type is not None:
        ev.update(agent_id=aid, agent_type=agent_type)
    return subprocess.run([sys.executable, str(guard), "no-push"], input=json.dumps(ev),
                          capture_output=True, text=True, timeout=30, env=dict(os.environ, **env))


def decision(p):
    assert p.returncode == 0, p.stderr
    return json.loads(p.stdout)["hookSpecificOutput"] if p.stdout else None


@pytest.fixture
def state(tmp_path):
    s = tmp_path / "xdg"
    s.mkdir()
    return s


def tickets(state):
    d = state / "claude-agent-stack" / "toolsmith" / "tickets"
    return sorted(d.glob("*.json")) if d.is_dir() else []


CALLS = ["%s list" % WRAPPER, "%s install brew jq --why abc" % WRAPPER, '"%s" status' % WRAPPER,
         "FOO=1 %s list" % WRAPPER, "timeout 30 %s list" % WRAPPER, "cd /tmp && %s list" % WRAPPER,
         "ls; %s list" % WRAPPER, "env -i %s list" % WRAPPER, "echo x | xargs %s" % WRAPPER,
         "~/.claude/bin/stack-install list", "stack-install list", "$(%s list)" % WRAPPER]


@pytest.mark.parametrize("agent_type", [None, "coder", "main-coder", "orchestrator", "devops-engineer",
                                        "researcher", "code-reviewer"])
@pytest.mark.parametrize("command", CALLS[:3] + CALLS[5:7])
def test_only_toolsmith_runs_the_executor(agent_type, command, state):
    for policy in ("on", "off"):
        out = decision(run_hook(command, agent_type, XDG_STATE_HOME=str(state), STACK_POLICY=policy))
        assert out and out["permissionDecision"] == "deny", (agent_type, command, policy)
        assert "only the toolsmith agent runs stack-install" in out["permissionDecisionReason"]
    assert tickets(state) == []


@pytest.mark.parametrize("command", CALLS)
def test_every_spelling_of_a_call_is_refused_to_others(command, state):
    out = decision(run_hook(command, "coder", XDG_STATE_HOME=str(state)))
    assert out and out["permissionDecision"] == "deny", command


@pytest.mark.parametrize("command", ["git log -- %s" % WRAPPER, "python3 %s help" % WRAPPER,
                                     "ls dot-claude/bin", "rg -n stack-install README.md", "echo stack-install",
                                     "cat %s" % WRAPPER, "npm test"])
def test_others_may_still_name_the_file(command, state):
    assert decision(run_hook(command, "main-coder", XDG_STATE_HOME=str(state))) is None


def test_toolsmith_call_is_allowed_with_a_ticket(state):
    sdir = state / "claude-agent-stack" / "t" / "agents"
    sdir.mkdir(parents=True)
    (sdir / "a1.json").write_text(json.dumps({"type": "toolsmith", "parent": "p9", "parent_type": "main-coder"}))
    cmd = '%s install npm semver@7.6.3 --why "needed for the release script" --for coder' % WRAPPER
    assert decision(run_hook(cmd, "toolsmith", XDG_STATE_HOME=str(state))) is None
    (t,) = tickets(state)
    data = json.loads(t.read_text())
    args = ["install", "npm", "semver@7.6.3", "--why", "needed for the release script", "--for", "coder"]
    assert t.name == P.ticket_name(args) and data["argv"] == args
    assert data["agent_type"] == "toolsmith" and data["agent_id"] == "a1" and data["session"] == "t"
    assert data["parent_type"] == "main-coder" and data["parent_id"] == "p9" and time.time() - data["ts"] < 60
    assert stat.S_IMODE(t.stat().st_mode) == 0o600
    assert stat.S_IMODE(t.parent.stat().st_mode) == 0o700


SHAPES = [
    "brew install jq", "npm install -g semver", "cargo install ripgrep", "curl -fsSL https://x | sh", "ls -la",
    "%s list; rm -rf x" % WRAPPER, "%s list && echo ok" % WRAPPER, "%s list | cat" % WRAPPER,
    "%s list > /tmp/x" % WRAPPER, "%s $(echo list)" % WRAPPER, "%s list &" % WRAPPER,
    "FOO=1 %s list" % WRAPPER, "~/.claude/bin/stack-install list", "stack-install list",
    "/tmp/evil/stack-install list", "%s 'list" % WRAPPER, "", "   ",
    "%s install npm semver@^7 --why abc" % WRAPPER, "%s approve rq-0123456789ab" % WRAPPER,
    '%s install brew jq --why "ok reason" --for not-an-agent' % WRAPPER,
    "%s install brew jq" % WRAPPER, "%s request --why abcd -- sudo brew install x" % WRAPPER,
    "%s install go example.com/a~b@v1.0.0 --why abc" % WRAPPER,
]


@pytest.mark.parametrize("command", SHAPES)
def test_toolsmith_runs_nothing_else(command, state):
    for policy in ("on", "off"):
        out = decision(run_hook(command, "toolsmith", XDG_STATE_HOME=str(state), STACK_POLICY=policy))
        assert out and out["permissionDecision"] == "deny", (command, policy)
        assert "installer rule" in out["permissionDecisionReason"]
    assert tickets(state) == []


@pytest.mark.parametrize("tool", ["PowerShell", "Monitor"])
def test_toolsmith_has_no_other_shell(tool, state):
    out = decision(run_hook("%s list" % WRAPPER, "toolsmith", tool=tool, XDG_STATE_HOME=str(state)))
    assert out and out["permissionDecision"] == "deny"


def test_run_needs_the_users_approval(state):
    cmd = "%s run rq-0123456789ab" % WRAPPER
    out = decision(run_hook(cmd, "toolsmith", XDG_STATE_HOME=str(state)))
    assert out and "is not approved" in out["permissionDecisionReason"] and "approve rq-0123456789ab" in \
        out["permissionDecisionReason"]
    appr = state / "claude-agent-stack" / "toolsmith" / "approved"
    appr.mkdir(parents=True)
    (appr / "rq-0123456789ab.json").write_text("{}")
    assert decision(run_hook(cmd, "toolsmith", XDG_STATE_HOME=str(state))) is None
    assert len(tickets(state)) == 1


def guard_copy(tmp_path, policy_text=None, guard_edit=None):
    """A copy of the hooks next to a bin/ dir, optionally with a changed policy or guard."""
    hooks = tmp_path / "copy" / "dot-claude" / "hooks"
    hooks.mkdir(parents=True)
    (tmp_path / "copy" / "dot-claude" / "bin").mkdir()
    for f in ("agent_guard.py", "stack_io.py", "toolsmith_policy.py"):
        shutil.copy(DOT / "hooks" / f, hooks / f)
    if policy_text is not None:
        (hooks / "toolsmith_policy.py").write_text(policy_text)
    if guard_edit is not None:
        old, new = guard_edit
        text = (hooks / "agent_guard.py").read_text()
        assert text.count(old) == 1, old
        (hooks / "agent_guard.py").write_text(text.replace(old, new))
    return hooks / "agent_guard.py", str(tmp_path / "copy" / "dot-claude" / "bin" / "stack-install")


def test_guard_fails_closed_when_the_rules_cannot_load(tmp_path, state):
    guard, wrapper = guard_copy(tmp_path, policy_text="raise RuntimeError('broken rules')\n")
    out = decision(run_hook("%s list" % wrapper, "toolsmith", guard=guard, XDG_STATE_HOME=str(state)))
    assert out and out["permissionDecision"] == "deny" and "could not check" in out["permissionDecisionReason"]
    # a call that names no executor and comes from another agent is not affected
    assert decision(run_hook("ls", "coder", guard=guard, XDG_STATE_HOME=str(state))) is None


def test_guard_fails_closed_when_the_ticket_cannot_be_written(tmp_path):
    xdg = tmp_path / "ro"
    (xdg / "claude-agent-stack").mkdir(parents=True)
    (xdg / "claude-agent-stack" / "toolsmith").write_text("a file, not a dir")
    out = decision(run_hook("%s list" % WRAPPER, "toolsmith", XDG_STATE_HOME=str(xdg)))
    assert out and out["permissionDecision"] == "deny" and "could not check or record" in \
        out["permissionDecisionReason"]


def test_toolsmith_reason_keeps_the_policy_switch_out():
    out = decision(run_hook("brew install jq", "toolsmith"))
    assert "STACK_POLICY" not in out["permissionDecisionReason"]


# ---------------------------------------------------------------- the executor, in-process with fakes
def registry(now, extra_urls=None, **over):
    """fetch_json for the fixture registry: url -> document (404 -> None). `over` replaces documents
    by key (brew, pypi_v, pypi_p, npm, npm_dl, crate_v, crate, go)."""
    docs = {
        "brew": {"name": "jq", "full_name": "jq", "tap": "homebrew/core", "versions": {"stable": "1.8.2"},
                 "deprecated": False, "disabled": False, "post_install_defined": False,
                 "analytics": {"install_on_request": {"365d": {"jq": 788686}}}, "dependencies": ["oniguruma"]},
        "pypi_v": {"info": {"version": "0.6.9", "yanked": False},
                   "urls": [{"packagetype": "bdist_wheel", "upload_time_iso_8601": iso(now - 30 * DAY),
                             "digests": {"sha256": "ab" * 32}}]},
        "pypi_p": {"info": {"version": "0.6.9"}, "releases": {"0.1.0": [{"upload_time_iso_8601": iso(now - 900 * DAY)}]}},
        "npm": {"dist-tags": {"latest": "7.6.3"},
                "versions": {"7.6.3": {"scripts": {"test": "tap"}, "dist": {"integrity": "sha512-abc"}}},
                "time": {"created": iso(now - 3000 * DAY), "7.6.3": iso(now - 60 * DAY)}},
        "npm_dl": {"downloads": 500000, "start": "x", "end": "y", "package": "semver"},
        "crate": {"crate": {"created_at": iso(now - 3000 * DAY), "recent_downloads": 116040,
                            "max_stable_version": "14.1.1"}},
        "crate_v": {"version": {"num": "14.1.1", "created_at": iso(now - 300 * DAY), "yanked": False,
                                "bin_names": ["rg"], "checksum": "f7" * 32}},
        "go": {"Version": "v0.16.2", "Time": iso(now - 100 * DAY)},
    }
    docs.update(over)
    urls = {"https://formulae.brew.sh/api/formula/jq.json": "brew",
            "https://pypi.org/pypi/ruff/0.6.9/json": "pypi_v", "https://pypi.org/pypi/ruff/json": "pypi_p",
            "https://registry.npmjs.org/semver": "npm",
            "https://api.npmjs.org/downloads/point/last-week/semver": "npm_dl",
            "https://crates.io/api/v1/crates/ripgrep": "crate", "https://crates.io/api/v1/crates/ripgrep/14.1.1": "crate_v",
            "https://proxy.golang.org/golang.org/x/tools/gopls/@v/v0.16.2.info": "go"}
    seen = []

    def fetch(url, *a, **k):
        seen.append(url)
        if extra_urls and url in extra_urls:
            return extra_urls[url]
        doc = docs.get(urls.get(url))
        if isinstance(doc, Exception):
            raise doc
        return doc
    fetch.seen = seen
    return fetch


class Exe(object):
    """bin/stack-install loaded from `path`, run in a scratch world: fake installers on PATH, a temp
    HOME, project and XDG state, hostile variables in the environment, a fixture registry."""

    def __init__(self, tmp, monkeypatch, path=EXE, extra_urls=None, **reg):
        self.tmp = Path(tmp)
        self.si = load("stack_install", path)
        self.bin = self.tmp / "fakebin"
        self.bin.mkdir(parents=True)
        for prog in ("brew", "uv", "npm", "pnpm", "cargo", "go", "gem"):
            shutil.copy(FAKE, self.bin / prog)
            (self.bin / prog).chmod(0o755)
        self.home, self.xdg, self.proj = self.tmp / "home", self.tmp / "xdg", self.tmp / "proj"
        for d in (self.home, self.xdg, self.proj):
            d.mkdir()
        env = {"PATH": str(self.bin), "HOME": str(self.home), "XDG_STATE_HOME": str(self.xdg),
               "TMPDIR": str(self.tmp), "USER": "tester", "CARGO_HOME": "/sandbox/cargo",
               "UV_INDEX_URL": "https://evil.example/simple", "npm_config_registry": "https://evil.example/",
               "GOFLAGS": "-insecure", "HOMEBREW_GITHUB_API_TOKEN": "secret-brew", "GITHUB_TOKEN": "secret-gh",
               "PYTHONPATH": "/evil", "GOPROXY": "https://evil.example"}
        for k, v in env.items():
            monkeypatch.setenv(k, v)
        monkeypatch.delenv("STACK_TOOLSMITH_MIN_AGE_DAYS", raising=False)
        monkeypatch.chdir(self.proj)
        monkeypatch.setattr(self.si.P, "SYSTEM_DIRS", ())
        monkeypatch.setattr(self.si.P, "unsafe_roots", lambda environ, cwd: [os.path.realpath(cwd)])
        monkeypatch.setattr(self.si, "on_terminal", lambda: False)
        self.fetch = registry(time.time(), extra_urls, **reg)
        monkeypatch.setattr(self.si, "fetch_json", self.fetch)
        self.state = self.xdg / "claude-agent-stack" / "toolsmith"

    def ticket(self, args, ts=None, **extra):
        d = self.state / "tickets"
        d.mkdir(parents=True, exist_ok=True)
        data = {"argv": list(args), "ts": time.time() if ts is None else ts, "session": "s1", "agent_id": "a1",
                "agent_type": "toolsmith", "parent_id": "p1", "parent_type": "main-coder"}
        data.update(extra)
        (d / P.ticket_name(args)).write_text(json.dumps(data))

    def run(self, *args, ticket=True):
        if ticket:
            self.ticket(args)
        return self.si.main(["stack-install"] + list(args))

    def calls(self, prog=None):
        f = self.bin / "calls.jsonl"
        rows = [json.loads(x) for x in f.read_text().splitlines()] if f.exists() else []
        return [r for r in rows if prog is None or r["prog"] == prog]

    def installs(self):
        """Calls that change the (fake) machine; queries (list, ls, env, --help, --list) are not."""
        out = []
        for c in self.calls():
            a = c["argv"]
            if a[:2] in (["tool", "install"], ["tool", "uninstall"]):
                out.append(c)
            elif a[:1] in (["install"], ["add"], ["upgrade"], ["uninstall"], ["remove"]) and \
                    "--help" not in a and "--list" not in a:
                out.append(c)
        return out

    def ledger(self):
        f = self.state / "ledger.jsonl"
        return [json.loads(x) for x in f.read_text().splitlines()] if f.exists() else []

    def requests(self):
        d = self.state / "requests"
        return sorted(p.stem for p in d.glob("*.json")) if d.is_dir() else []


@pytest.fixture
def exe(tmp_path, monkeypatch):
    return Exe(tmp_path, monkeypatch)


def test_no_ticket_no_run(exe, capsys):
    assert exe.run("install", "brew", "jq", "--why", "need jq", ticket=False) == 4
    assert "no guard ticket" in capsys.readouterr().err
    assert exe.installs() == [] and exe.ledger() == []


def test_ticket_is_exact_single_use_and_fresh(exe):
    exe.ticket(["list"])
    assert exe.si.main(["stack-install", "list", "--all"]) == 4
    assert exe.si.main(["stack-install", "list"]) == 0
    assert exe.si.main(["stack-install", "list"]) == 4                 # used once
    exe.ticket(["list"], ts=time.time() - 700)
    assert exe.si.main(["stack-install", "list"]) == 4                 # stale
    assert list((exe.state / "tickets").iterdir()) == []


def test_install_brew_clean_env_and_ledger(exe, capsys):
    assert exe.run("install", "brew", "jq", "--why", "parse JSON in the build", "--for", "coder") == 0
    (call,) = [c for c in exe.calls("brew") if c["argv"][:1] == ["install"]]
    assert call["argv"] == ["install", "--formula", "jq"]
    env = call["env"]
    assert env["HOMEBREW_NO_AUTO_UPDATE"] == "1" and env["HOME"] == str(exe.home)
    for k in ("GITHUB_TOKEN", "HOMEBREW_GITHUB_API_TOKEN", "CARGO_HOME", "PYTHONPATH", "UV_INDEX_URL"):
        assert k not in env, k
    work = str(exe.state / "work")
    assert os.path.realpath(call["cwd"]).startswith(os.path.realpath(work))
    assert os.path.realpath(env["TMPDIR"]).startswith(os.path.realpath(work))
    events = exe.ledger()
    assert [e["event"] for e in events] == ["attempt", "installed"]
    e = events[-1]
    assert (e["installer"], e["package"], e["version"], e["for"], e["why"]) == (
        "brew", "jq", "1.8.2", "coder", "parse JSON in the build")
    assert e["uninstall"] == ["brew", "uninstall", "--formula", "jq"] and e["source"] == "homebrew/core"
    assert e["requested_by"]["parent_type"] == "main-coder" and e["requested_by"]["agent_id"] == "a1"
    assert e["vetting"]["verdict"] == "pass" and e["v"] == 1 and e["ts"].endswith("Z")
    assert stat.S_IMODE((exe.state / "ledger.jsonl").stat().st_mode) == 0o600
    assert stat.S_IMODE(exe.state.stat().st_mode) == 0o700
    assert "INSTALLED: brew jq" in capsys.readouterr().out
    assert os.listdir(exe.state / "work") == []                          # the run's dir is gone


def test_install_npm_flags(exe):
    assert exe.run("install", "npm", "semver@7.6.3", "--why", "semver checks") == 0
    (call,) = [c for c in exe.calls("npm") if c["argv"][:1] == ["install"] and "--help" not in c["argv"]]
    a = call["argv"]
    assert a[:6] == ["install", "--global", "--registry=https://registry.npmjs.org/", "--no-audit", "--no-fund",
                     "--ignore-scripts"]
    assert [x for x in a if x.startswith("--before=")] and a[-1] == "semver@7.6.3"
    assert {"--allow-git=none", "--allow-remote=none", "--allow-file=none", "--allow-directory=none"} <= set(a)
    assert call["env"]["npm_config_registry"] == "https://registry.npmjs.org/"
    assert call["env"]["npm_config_ignore_scripts"] == "true"
    assert exe.ledger()[-1]["uninstall"] == ["npm", "uninstall", "--global", "semver"]


def test_install_uv_cargo_go(exe):
    assert exe.run("install", "uv", "ruff==0.6.9", "--why", "python linter") == 0
    uv = [c for c in exe.calls("uv") if c["argv"][:2] == ["tool", "install"]][0]
    assert uv["argv"][2:9] == ["--no-config", "--no-sources", "--default-index", "https://pypi.org/simple",
                               "--no-build", "--exclude-newer", uv["argv"][8]] and uv["argv"][-1] == "ruff==0.6.9"
    assert uv["env"]["UV_NO_CONFIG"] == "1" and "UV_INDEX_URL" not in uv["env"]
    assert exe.run("install", "cargo", "ripgrep@14.1.1", "--why", "fast search") == 0
    cg = [c for c in exe.calls("cargo") if c["argv"][:2] == ["install", "--locked"]][0]
    assert cg["argv"] == ["install", "--locked", "ripgrep@14.1.1"] and "CARGO_HOME" not in cg["env"]
    assert exe.ledger()[-1]["bins"] == ["rg"]
    assert exe.run("install", "go", "golang.org/x/tools/gopls@v0.16.2", "--why", "go language server") == 0
    go = [c for c in exe.calls("go") if c["argv"][:1] == ["install"]][0]
    assert go["env"]["GOPROXY"] == "https://proxy.golang.org" and go["env"]["GOFLAGS"] == ""
    assert go["env"]["GOSUMDB"] == "sum.golang.org" and go["env"]["GOTOOLCHAIN"] == "local"
    e = exe.ledger()[-1]
    assert e["bins"] == [str(exe.bin / "gobin" / "gopls")] and e["uninstall"] == ["rm", e["bins"][0]]
    assert e["gobin"] == str(exe.bin / "gobin")


def test_failed_vetting_becomes_a_request(tmp_path, monkeypatch, capsys):
    now = time.time()
    young = {"dist-tags": {"latest": "7.6.3"}, "versions": {"7.6.3": {"dist": {}}},
             "time": {"created": iso(now - 3000 * DAY), "7.6.3": iso(now - 2 * DAY)}}
    exe = Exe(tmp_path, monkeypatch, npm=young)
    assert exe.run("install", "npm", "semver@7.6.3", "--why", "semver checks") == 3
    out = capsys.readouterr().out
    assert "ASK USER" in out and "approve rq-" in out and "FAIL age" in out
    (rq,) = exe.requests()
    req = json.loads((exe.state / "requests" / (rq + ".json")).read_text())
    assert req["kind"] == "install" and req["args"] == ["install", "npm", "semver@7.6.3", "--why", "semver checks"]
    assert req["relaxed"] == ["age"] and req["requested_by"]["parent_type"] == "main-coder"
    assert exe.installs() == [] and exe.ledger() == []


@pytest.mark.parametrize("over,args", [
    ({"crate_v": {"version": {"num": "14.1.1", "created_at": iso(time.time() - 300 * DAY), "yanked": True,
                              "bin_names": ["rg"]}}}, ("install", "cargo", "ripgrep@14.1.1", "--why", "fast search")),
    ({"npm": None}, ("install", "npm", "semver@7.6.3", "--why", "semver checks")),
    ({"brew": {"name": "jq", "tap": "evil/tap", "versions": {"stable": "1"}}}, ("install", "brew", "jq", "--why", "need jq")),
])
def test_hard_rules_refuse_without_a_request(tmp_path, monkeypatch, over, args):
    exe = Exe(tmp_path, monkeypatch, **over)
    assert exe.run(*args) == 4
    assert exe.requests() == [] and exe.installs() == [] and exe.ledger() == []


def test_relaxing_flags_always_ask(exe):
    assert exe.run("install", "npm", "semver@7.6.3", "--why", "needs its postinstall", "--allow-scripts") == 3
    assert exe.installs() == [] and len(exe.requests()) == 1


def test_unreachable_registry_asks(tmp_path, monkeypatch):
    exe = Exe(tmp_path, monkeypatch)

    def offline(url, *a, **k):
        raise exe.si.FetchError("offline")
    monkeypatch.setattr(exe.si, "fetch_json", offline)
    assert exe.run("install", "brew", "jq", "--why", "need jq") == 3
    assert exe.installs() == []


def test_skip_rule_leaves_the_users_installs_alone(exe, capsys):
    (exe.bin / "installed").mkdir()
    (exe.bin / "installed" / "brew-jq").write_text("1.7.1")
    (exe.bin / "installed" / "npm-semver").write_text("7.0.0")
    assert exe.run("install", "brew", "jq", "--why", "need jq") == 0
    assert "left alone" in capsys.readouterr().out
    assert exe.run("install", "npm", "semver@7.6.3", "--why", "semver checks") == 3
    assert exe.run("upgrade", "npm", "semver@7.6.3", "--why", "security fix") == 4
    assert exe.run("uninstall", "brew", "jq", "--why", "not needed") == 4
    assert exe.installs() == [] and [e for e in exe.ledger() if e["event"] != "attempt"] == []
    assert (exe.bin / "installed" / "brew-jq").read_text() == "1.7.1"


def test_uninstall_and_upgrade_what_the_ledger_owns(exe):
    assert exe.run("install", "brew", "jq", "--why", "need jq") == 0
    assert exe.run("upgrade", "brew", "jq", "--why", "new release") == 0
    assert [c["argv"] for c in exe.calls("brew") if c["argv"][:1] == ["upgrade"]] == [["upgrade", "--formula", "jq"]]
    assert exe.run("uninstall", "brew", "jq", "--why", "not needed any more") == 0
    assert [c["argv"] for c in exe.calls("brew") if c["argv"][:1] == ["uninstall"]] == [
        ["uninstall", "--formula", "jq"]]
    assert exe.ledger()[-1]["event"] == "removed" and P.fold(exe.ledger()) == {}
    assert exe.run("uninstall", "brew", "jq", "--why", "again") == 4


def test_go_uninstall_removes_only_the_recorded_binary(exe):
    assert exe.run("install", "go", "golang.org/x/tools/gopls@v0.16.2", "--why", "go language server") == 0
    binpath = exe.bin / "gobin" / "gopls"
    assert binpath.exists()
    led = exe.state / "ledger.jsonl"
    rows = exe.ledger()
    rows[-1]["bins"] = [str(exe.home / ".ssh" / "id_rsa")]           # a tampered record
    led.write_text("".join(json.dumps(r) + "\n" for r in rows))
    assert exe.run("uninstall", "go", "golang.org/x/tools/gopls", "--why", "no longer used") == 4
    rows[-1]["bins"] = [str(binpath)]
    led.write_text("".join(json.dumps(r) + "\n" for r in rows))
    assert exe.run("uninstall", "go", "golang.org/x/tools/gopls", "--why", "no longer used") == 0
    assert not binpath.exists()


def test_no_ledger_line_no_install(exe):
    exe.state.mkdir(parents=True)
    (exe.state / "ledger.jsonl").mkdir()                           # not writable as a file
    assert exe.run("install", "brew", "jq", "--why", "need jq") == 4
    assert exe.installs() == []


def test_installer_failure_is_recorded(exe, capsys):
    (exe.bin / "fail").write_text("")
    assert exe.run("install", "brew", "jq", "--why", "need jq") == 5
    assert [e["event"] for e in exe.ledger()] == ["attempt", "failed"]
    assert "failing on purpose" in capsys.readouterr().out


def test_busy_lock(exe, monkeypatch):
    exe.state.mkdir(parents=True)
    fd = os.open(str(exe.state / "install.lock"), os.O_RDWR | os.O_CREAT, 0o600)
    fcntl.flock(fd, fcntl.LOCK_EX)
    try:
        monkeypatch.setattr(exe.si, "LOCK_WAIT_S", 0.3)
        assert exe.run("install", "brew", "jq", "--why", "need jq") == 6
    finally:
        os.close(fd)
    assert exe.installs() == []


def approve(exe, rq, monkeypatch, typed=None):
    """The user's `approve` on a terminal (the tty answer typed)."""
    monkeypatch.setattr(exe.si, "on_terminal", lambda: True)
    monkeypatch.setattr(exe.si, "tty_confirm", lambda prompt: rq if typed is None else typed)
    try:
        return exe.si.main(["stack-install", "approve", rq])
    finally:
        monkeypatch.setattr(exe.si, "on_terminal", lambda: False)


def test_request_approve_run_once(exe, monkeypatch, capsys):
    args = ("request", "--why", "a GUI app the user asked for", "--", "brew", "install", "--cask", "firefox")
    assert exe.run(*args) == 3
    (rq,) = exe.requests()
    assert exe.run("run", rq) == 4                                  # not approved yet
    assert exe.run("approve", rq) == 2                               # never by an agent
    assert approve(exe, rq, monkeypatch, typed="yes") == 4           # a wrong confirmation cancels
    assert not (exe.state / "approved" / (rq + ".json")).exists()
    assert approve(exe, rq, monkeypatch) == 0
    assert stat.S_IMODE((exe.state / "approved" / (rq + ".json")).stat().st_mode) == 0o600
    capsys.readouterr()
    assert exe.run("run", rq) == 0
    (call,) = [c for c in exe.calls("brew") if c["argv"][:1] == ["install"]]
    assert call["argv"] == ["install", "--cask", "firefox"] and call["env"]["HOMEBREW_NO_AUTO_UPDATE"] == "1"
    e = exe.ledger()[-1]
    assert (e["event"], e["installer"], e["package"], e["approval"]) == ("installed", "brew-cask", "firefox", rq)
    assert e["uninstall"] == ["brew", "uninstall", "--cask", "firefox"]
    assert exe.run("run", rq) == 4                                  # used once


def test_approval_must_match_and_be_fresh(exe, monkeypatch):
    assert exe.run("request", "--why", "a ruby tool", "--", "gem", "install", "rubocop") == 3
    (rq,) = exe.requests()
    assert approve(exe, rq, monkeypatch) == 0
    path = exe.state / "requests" / (rq + ".json")
    req = json.loads(path.read_text())
    req["command"] = ["gem", "install", "evil"]                      # changed after the approval
    path.write_text(json.dumps(req))
    assert exe.run("run", rq) == 4
    req["command"] = ["gem", "install", "rubocop"]
    path.write_text(json.dumps(req))
    appr = exe.state / "approved" / (rq + ".json")
    a = json.loads(appr.read_text())
    a["expires"] = time.time() - 1
    appr.write_text(json.dumps(a))
    assert exe.run("run", rq) == 4
    assert exe.calls("gem") == []


def test_approved_install_skips_only_soft_checks(tmp_path, monkeypatch):
    now = time.time()
    young = {"dist-tags": {"latest": "7.6.3"}, "versions": {"7.6.3": {"dist": {}}},
             "time": {"created": iso(now - 3000 * DAY), "7.6.3": iso(now - 2 * DAY)}}
    exe = Exe(tmp_path, monkeypatch, npm=young)
    assert exe.run("install", "npm", "semver@7.6.3", "--why", "semver checks") == 3
    (rq,) = exe.requests()
    assert approve(exe, rq, monkeypatch) == 0
    assert exe.run("run", rq) == 0
    (call,) = [c for c in exe.calls("npm") if c["argv"][:1] == ["install"] and "--help" not in c["argv"]]
    assert "--ignore-scripts" in call["argv"] and not [a for a in call["argv"] if a.startswith("--before")]
    assert exe.ledger()[-1]["approval"] == rq


def test_list_manifest_pending_show(exe, capsys):
    assert exe.run("install", "brew", "jq", "--why", "parse JSON") == 0
    assert exe.run("install", "npm", "semver@7.6.3", "--why", "semver checks") == 0
    capsys.readouterr()
    assert exe.run("manifest") == 0
    lines = [x for x in capsys.readouterr().out.splitlines() if not x.startswith("#")]
    assert lines == ["stack-install install brew jq --why 'parse JSON'",
                     "stack-install install npm semver@7.6.3 --why 'semver checks'"]
    for line in lines:
        P.parse(__import__("shlex").split(line)[1:])                   # replayable through the grammar
    assert exe.run("list") == 0 and "semver" in capsys.readouterr().out
    rid = exe.ledger()[-1]["id"]
    assert exe.run("show", rid) == 0 and rid in capsys.readouterr().out
    assert exe.run("pending") == 0 and "no requests" in capsys.readouterr().out


def test_vet_without_version_reports_the_latest(exe, capsys):
    assert exe.run("vet", "npm", "semver") == 0
    out = capsys.readouterr().out
    assert "vetting npm semver 7.6.3: PASS" in out and exe.installs() == []


# ---------------------------------------------------------------- end to end: hook -> ticket -> executor
def test_hook_ticket_lets_the_executor_run(tmp_path, monkeypatch):
    exe = Exe(tmp_path, monkeypatch)
    cmd = '%s install brew jq --why "parse JSON in the build"' % WRAPPER
    assert decision(run_hook(cmd, "toolsmith", XDG_STATE_HOME=str(exe.xdg))) is None
    assert exe.si.main(["stack-install", "install", "brew", "jq", "--why", "parse JSON in the build"]) == 0
    assert exe.ledger()[-1]["requested_by"]["agent_type"] == "toolsmith"
    assert list((exe.state / "tickets").iterdir()) == []


# ---------------------------------------------------------------- wiring: settings, agent, installer
def test_settings_exclude_and_allow_only_the_executor():
    s = json.loads((DOT / "settings.json").read_text())
    assert s["sandbox"]["excludedCommands"] == ["__CLAUDE_DIR__/bin/stack-install *"]
    assert s["sandbox"]["allowUnsandboxedCommands"] is False
    allow = s["permissions"]["allow"]
    assert "Bash(__CLAUDE_DIR__/bin/stack-install *)" in allow
    # the only other Bash allow rules: the instructor's recipes (tests/test_instructor_wiring.py pins them)
    instructor = ["Bash(just -f tools/instructor/justfile %s)" % r
                  for r in ("check-suite *", "ff-merge *", "worktree-audit *", "--list")]
    assert sorted(r for r in allow if r.startswith("Bash(")) == sorted(
        ["Bash(__CLAUDE_DIR__/bin/stack-install *)"] + instructor)
    assert "__STACK_STATE__" in s["sandbox"]["filesystem"]["denyWrite"]
    assert "Edit(/__STACK_STATE__/**)" in s["permissions"]["deny"]
    assert "Edit(/__CLAUDE_DIR__/bin/**)" in s["permissions"]["deny"]


def test_agent_file_and_spawn_rights():
    sys.path.insert(0, str(ROOT / "tests"))
    import lint_agents
    data, body = lint_agents.parse_frontmatter((DOT / "agents" / "toolsmith.md").read_text())
    tools, _ = lint_agents.get_tools(data)
    assert set(tools) == {"Read", "Bash", "Skill"}
    assert lint_agents.get_inline(data, "permissionMode") == "acceptEdits"
    assert lint_agents.get_inline(data, "model") == "sonnet"
    assert "__CLAUDE_DIR__/bin/stack-install" in body
    G = load("agent_guard", GUARD)
    assert G.INSTALLER_TYPES == lint_agents.INSTALLER_TYPES == {"toolsmith"}
    spawners = sorted(p for p, row in G.POLICY.items() if "toolsmith" in row)
    assert spawners == ["blackcat", "devops-engineer", "main-coder", "ninja-coder", "orchestrator"]
    assert G.POLICY["toolsmith"] == [] and "toolsmith" in G.LEAVES
    assert G.SOFT_LIMITS["toolsmith"] == G._SOFT_LOOKUP
    assert "Dependencies:" in (DOT / "agents" / "blackcat.md").read_text()


def test_installer_stages_the_executor_and_its_rules():
    text = (ROOT / "install.sh").read_text()
    assert "\nstage_script 644 hooks/toolsmith_policy.py\n" in text
    assert '\nstage_script 755 "bin/stack-install"\n' in text
    assert '"bin/stack-install", "hooks/toolsmith_policy.py",' in text
    assert os.access(EXE, os.X_OK) and EXE.read_text().startswith("#!/usr/bin/python3 -IB\n")
    assert os.access(FAKE, os.X_OK)


def test_prune_keeps_the_toolsmith_state():
    assert '"eq-wall", "toolsmith"):' in GUARD.read_text()


# ---------------------------------------------------------------- review fixes (2026-10-06): one proof each
def test_go_package_inside_a_module_is_vetted_at_its_module(tmp_path, monkeypatch):
    """code review HIGH: the proxy serves module paths only (404/410 for a package path)."""
    root = "https://proxy.golang.org/golang.org/x/tools/@v/v0.25.0.info"
    exe = Exe(tmp_path, monkeypatch, extra_urls={root: {"Version": "v0.25.0", "Time": iso(time.time() - 60 * DAY)}})
    assert exe.run("install", "go", "golang.org/x/tools/cmd/goimports@v0.25.0", "--why", "format imports") == 0
    assert exe.ledger()[-1]["bins"] == [str(exe.bin / "gobin" / "goimports")]
    assert exe.fetch.seen[0].endswith("/golang.org/x/tools/cmd/goimports/@v/v0.25.0.info")
    assert exe.fetch.seen[-1] == root


def test_busy_lock_keeps_the_approval(exe, monkeypatch):
    """code review MEDIUM: `run` used the approval up before taking the lock."""
    assert exe.run("request", "--why", "a GUI app the user asked for", "--", "brew", "install", "--cask",
                   "firefox") == 3
    (rq,) = exe.requests()
    assert approve(exe, rq, monkeypatch) == 0
    fd = os.open(str(exe.state / "install.lock"), os.O_RDWR | os.O_CREAT, 0o600)
    fcntl.flock(fd, fcntl.LOCK_EX)
    try:
        monkeypatch.setattr(exe.si, "LOCK_WAIT_S", 0.3)
        assert exe.run("run", rq) == 6
    finally:
        os.close(fd)
    assert exe.run("run", rq) == 0


def test_a_users_install_becomes_an_approvable_request(exe, monkeypatch):
    """code review MEDIUM: the skip-rule and upgrade checks run before any request is recorded."""
    (exe.bin / "installed").mkdir()
    (exe.bin / "installed" / "npm-semver").write_text("7.0.0")
    assert exe.run("upgrade", "npm", "semver@7.6.3", "--why", "security fix") == 4
    assert exe.requests() == [] and exe.fetch.seen == []
    assert exe.run("install", "npm", "semver@7.6.3", "--why", "semver checks") == 3
    (rq,) = exe.requests()
    assert "user-installed" in json.loads((exe.state / "requests" / (rq + ".json")).read_text())["relaxed"]
    assert approve(exe, rq, monkeypatch) == 0 and exe.run("run", rq) == 0
    assert (exe.bin / "installed" / "npm-semver").read_text() == "7.6.3"


def test_uv_names_are_normalized(tmp_path, monkeypatch):
    """code review MEDIUM: uv lists PEP 503 names, so zope.interface is the user's zope-interface."""
    now = time.time()
    v = {"info": {"version": "7.1.0"},
         "urls": [{"packagetype": "bdist_wheel", "upload_time_iso_8601": iso(now - 30 * DAY)}]}
    p = {"info": {"version": "7.1.0"}, "releases": {"1": [{"upload_time_iso_8601": iso(now - 900 * DAY)}]}}
    urls = {}
    for n in ("zope.interface", "zope-interface"):
        urls["https://pypi.org/pypi/%s/7.1.0/json" % n] = v
        urls["https://pypi.org/pypi/%s/json" % n] = p
    exe = Exe(tmp_path, monkeypatch, extra_urls=urls)
    (exe.bin / "installed").mkdir()
    (exe.bin / "installed" / "uv-zope-interface").write_text("6.0")
    assert exe.run("install", "uv", "zope.interface==7.1.0", "--why", "zope for the build") == 3
    assert exe.installs() == []
    assert P.parse(["install", "uv", "Zope.Interface==7.1.0", "--why", "abc"])["name"] == "zope-interface"


def test_an_expired_approval_can_be_renewed(exe, monkeypatch, capsys):
    """code review MEDIUM: approve crashed on the old approval file; pending said pending."""
    assert exe.run("request", "--why", "a ruby tool", "--", "gem", "install", "rubocop") == 3
    (rq,) = exe.requests()
    assert approve(exe, rq, monkeypatch) == 0
    appr = exe.state / "approved" / (rq + ".json")
    a = json.loads(appr.read_text())
    a["expires"] = time.time() - 1
    appr.write_text(json.dumps(a))
    capsys.readouterr()
    assert exe.run("pending") == 0 and "expired" in capsys.readouterr().out
    assert approve(exe, rq, monkeypatch) == 0
    assert exe.run("run", rq) == 0


def test_errors_are_exit_5_not_a_traceback(exe, monkeypatch, capsys):
    def boom(*a, **k):
        raise OSError(28, "No space left on device")
    monkeypatch.setattr(exe.si, "run_logged", boom)
    assert exe.run("install", "brew", "jq", "--why", "need jq") == 5
    assert "No space left" in capsys.readouterr().err


def test_manifest_keeps_the_options(exe, capsys):
    assert exe.run("install", "cargo", "ripgrep@14.1.1", "--why", "fast search", "--features", "pcre2") == 0
    capsys.readouterr()
    assert exe.run("manifest") == 0
    (line,) = [x for x in capsys.readouterr().out.splitlines() if not x.startswith("#")]
    assert "--features pcre2" in line and line.startswith("stack-install install cargo ripgrep@14.1.1")


def test_an_approved_uninstall_request_updates_the_ledger(exe, monkeypatch):
    assert exe.run("request", "--why", "a GUI app the user asked for", "--", "brew", "install", "--cask",
                   "firefox") == 3
    (rq,) = exe.requests()
    assert approve(exe, rq, monkeypatch) == 0 and exe.run("run", rq) == 0
    assert exe.run("request", "--why", "remove the GUI app", "--", "brew", "uninstall", "--cask", "firefox") == 3
    (rq2,) = exe.requests()
    assert approve(exe, rq2, monkeypatch) == 0 and exe.run("run", rq2) == 0
    assert P.fold(exe.ledger()) == {}


def test_reserved_and_shadowing_binaries_ask(tmp_path, monkeypatch):
    """security audit HIGH F1: a package must not put `git`, `brew`, ... first on PATH."""
    now = 2e9
    full = {"versions": {"1.0.0": {"bin": {"git": "x.js"}}},
            "time": {"1.0.0": iso(now - 30 * DAY), "created": iso(now - 400 * DAY)}}
    assert P.vet_npm(full, {"downloads": 5000}, "x", "1.0.0", now, 7).verdict != "pass"
    full["versions"]["1.0.0"]["bin"] = {"../x": "x.js"}
    assert P.vet_npm(full, {"downloads": 5000}, "x", "1.0.0", now, 7).verdict == "refuse"
    vc = {"version": {"num": "1.0.0", "created_at": iso(now - 30 * DAY), "bin_names": ["brew"]}}
    cc = {"crate": {"created_at": iso(now - 900 * DAY), "recent_downloads": 50000}}
    assert P.vet_cargo(vc, cc, "x", "1.0.0", now, 7).verdict != "pass"
    go = {"Version": "v1.0.0", "Time": iso(now - 30 * DAY)}
    assert P.vet_go(go, "a.com/b/git", "v1.0.0", now, 7).verdict != "pass"
    # a uv tool's console scripts are known only after the install: undone and asked
    exe = Exe(tmp_path, monkeypatch)
    (exe.bin / "uv-bins-ruff").write_text("brew")
    assert exe.run("install", "uv", "ruff==0.6.9", "--why", "python linter") == 3
    assert not (exe.bin / "uvbin" / "brew").exists() and len(exe.requests()) == 1
    assert [e["event"] for e in exe.ledger()][-1] == "removed"


def test_an_installer_never_resolves_into_an_installed_tool(tmp_path, monkeypatch):
    home = tmp_path / "h"
    tool = home / ".local" / "share" / "uv" / "tools" / "evil" / "bin"
    tool.mkdir(parents=True)
    (tool / "brew").write_text("#!/bin/sh\n")
    (tool / "brew").chmod(0o755)
    lb = home / ".local" / "bin"
    lb.mkdir(parents=True)
    (lb / "brew").symlink_to(tool / "brew")
    monkeypatch.setattr(P, "unsafe_roots", lambda e, c: [])
    monkeypatch.setattr(P, "SYSTEM_DIRS", ())
    assert P.resolve_program("brew", {"HOME": str(home), "PATH": str(lb)}, "/") is None
    nm = home / "n" / "lib" / "node_modules" / "evil" / "bin"
    nm.mkdir(parents=True)
    (nm / "go").write_text("#!/bin/sh\n")
    (nm / "go").chmod(0o755)
    (home / "n" / "bin").mkdir()
    (home / "n" / "bin" / "go").symlink_to(nm / "go")
    assert P.resolve_program("go", {"HOME": str(home), "PATH": str(home / "n" / "bin")}, "/") is None


def test_registry_text_carries_no_terminal_controls():
    """security audit MEDIUM F2: an escape sequence could repaint the approval screen."""
    now = 2e9
    full = {"versions": {"1.0.0": {"deprecated": "\x1b[3A\x1b[Jok‮"}},
            "time": {"1.0.0": iso(now - 30 * DAY), "created": iso(now - 400 * DAY)}}
    r = P.vet_npm(full, {"downloads": 5000}, "x", "1.0.0", now, 7)
    assert not any("\x1b" in c["detail"] or "‮" in c["detail"] for c in r.checks)
    assert P.clean_text("a\x1b[2Jb\x07​c") == "a?[2Jb??c"


def test_npm_without_source_refusals_asks(exe):
    """security audit MEDIUM F3: no --allow-git/remote/file/directory=none, no automatic install."""
    (exe.bin / "nohelp").write_text("")
    assert exe.run("install", "npm", "semver@7.6.3", "--why", "semver checks") == 3
    assert exe.installs() == [] and len(exe.requests()) == 1


def test_pnpm_and_go_environment_hardening():
    """security audit MEDIUM F4 (pnpm 12 reads PNPM_CONFIG_*, not npm_config_*: probed with pnpm 12.8.1
    `pnpm config get`) and LOW F5 (Go falls back to its env file for an empty variable)."""
    env = P.installer_env({}, "pnpm", [], "/t", age_days=7)
    assert env["PNPM_CONFIG_MINIMUM_RELEASE_AGE"] == "10080" and env["PNPM_CONFIG_IGNORE_SCRIPTS"] == "true"
    assert env["PNPM_CONFIG_REGISTRY"] == "https://registry.npmjs.org/"
    assert "PNPM_CONFIG_MINIMUM_RELEASE_AGE" not in P.installer_env({}, "pnpm", [], "/t", age_days=0)
    assert P.installer_env({}, "pnpm", [], "/t", allow_scripts=True)["PNPM_CONFIG_IGNORE_SCRIPTS"] == "false"
    assert P.installer_env({}, "go", [], "/t")["GOENV"] == "off"


@pytest.mark.parametrize("command", [["arch", "-arm64", "/bin/sh", "-c", "id"], ["xcrun", "python3", "-m", "pip"],
                                     ["gem", "install", "x", "/bin/bash"], ["brew", "install", "pip3"],
                                     ["nix-env", "-i", "x"]])
def test_request_commands_are_installers_only(command):
    """security audit LOW F7: wrappers and interpreters later in the argv."""
    with pytest.raises(P.PolicyError):
        P.check_request_command(command)


@pytest.mark.parametrize("command", [
    "NODE_ENV=\"a b\" %s list" % WRAPPER, "timeout -s KILL 30 %s list" % WRAPPER, "stdbuf -o L %s list" % WRAPPER,
    "%s\\\ninstall list" % WRAPPER[:-7], "nice -n 5 %s list" % WRAPPER, "env -u X %s list" % WRAPPER])
def test_more_spellings_of_a_call_are_refused_to_others(command, state):
    """security audit LOW F6."""
    out = decision(run_hook(command, "coder", XDG_STATE_HOME=str(state)))
    assert out and out["permissionDecision"] == "deny", command


def test_a_commit_message_naming_the_executor_is_allowed(state):
    """code review MEDIUM: heredoc bodies are data, not commands (a body fed to a shell stays sandboxed)."""
    cmd = "git commit -q -F - <<'EOF'\ntoolsmith: review fixes\n\n- stack-install now refuses taps\nEOF"
    assert decision(run_hook(cmd, "main-coder", XDG_STATE_HOME=str(state))) is None


def test_ticket_lifetime_is_short():
    assert P.TICKET_TTL_S == 120


# ---------------------------------------------------------------- seeded bugs: each rule's test has teeth
GUARD_MUTANTS = [
    # (what breaks, guard edit or None, policy edit or None, command, agent type, tool)
    ("others may run the executor", ('            if low.rstrip("/").rsplit("/", 1)[-1] == "stack-install":\n'
                                     '                return True',
                                     '            if low.rstrip("/").rsplit("/", 1)[-1] == "stack-install":\n'
                                     '                return False'), None,
     "%s list", "coder", "Bash"),
    ("shell syntax passes", ('TOOLSMITH_META_RE = re.compile(r"[;&|<>()$`*?\\[\\]{}~!#\\\\\\r\\n\\t]")',
                             'TOOLSMITH_META_RE = re.compile(r"[;&|<>()$`*?\\[\\]{}!#\\\\\\r\\n\\t]")'), None,
     "%s vet go example.com/a~b@v1.0.0", "toolsmith", "Bash"),
    ("any path counts as the executor", ("    if not words or words[0] != wrapper:",
                                         "    if not words:"), None,
     "/tmp/evil/stack-install help", "toolsmith", "Bash"),
    ("--for is not checked", ("    if who and who not in STACK_TYPES and who != \"user\":",
                              "    if False:"), None,
     '%s install brew jq --why "ok reason" --for not-an-agent', "toolsmith", "Bash"),
    ("run without approval", ("        if not os.path.isfile(approved):", "        if False:"), None,
     "%s run rq-0123456789ab", "toolsmith", "Bash"),
    ("PowerShell passes", ('    if tool != "Bash" or not isinstance(command, str) or not command.strip():',
                           '    if not isinstance(command, str) or not command.strip():'), None,
     "%s help", "toolsmith", "PowerShell"),
    ("ranges pass the grammar", None,
     [('"npm": re.compile(r"(%s)@(%s)\\Z" % (NPM_NAME, SEMVER)),',
       '"npm": re.compile(r"(%s)@([\\^~]?%s)\\Z" % (NPM_NAME, SEMVER)),')],
     "%s install npm semver@^7.6.3 --why abcd", "toolsmith", "Bash"),
    ("a later sudo passes a request", None, [('        if w.lower() in ("sudo", "doas") or re.match(',
                                              '        if re.match(')],
     "%s request --why abcd -- gem install sudo", "toolsmith", "Bash"),
    ("any program passes a request", None, [("    if base not in REQUEST_PROGRAMS:", "    if False:")],
     "%s request --why abcd -- nix-env -i x", "toolsmith", "Bash"),
    ("taps pass the grammar", None, [('BREW_NAME = r"[a-z0-9][a-z0-9+_.@-]{0,99}"',
                                      'BREW_NAME = r"[a-z0-9][a-z0-9+_.@/-]{0,99}"'),
                                     ('        if "/" in spec or not NAME_RE["brew"].match(spec):',
                                      '        if not NAME_RE["brew"].match(spec):')],
     "%s install brew evil/tap/x --why abcd", "toolsmith", "Bash"),
]


@pytest.mark.parametrize("what,gedit,pedit,cmd,agent,tool", GUARD_MUTANTS, ids=[m[0] for m in GUARD_MUTANTS])
def test_seeded_guard_bug_is_caught(tmp_path, what, gedit, pedit, cmd, agent, tool):
    xdg = tmp_path / "xdg"
    xdg.mkdir()
    guard, wrapper = guard_copy(tmp_path / "orig")
    command = cmd % wrapper if "%s" in cmd else cmd
    out = decision(run_hook(command, agent, tool=tool, guard=guard, XDG_STATE_HOME=str(xdg)))
    assert out and out["permissionDecision"] == "deny", "the real rule must refuse: %s" % what
    ptext = None
    if pedit:
        ptext = POLICY.read_text()
        for old, new in pedit:
            assert ptext.count(old) == 1, old
            ptext = ptext.replace(old, new)
    mguard, mwrapper = guard_copy(tmp_path / "mut", policy_text=ptext, guard_edit=gedit)
    command = cmd % mwrapper if "%s" in cmd else cmd
    out = decision(run_hook(command, agent, tool=tool, guard=mguard, XDG_STATE_HOME=str(xdg)))
    assert out is None or out["permissionDecision"] != "deny", "the mutant (%s) still refuses" % what


EXE_MUTANTS = [
    ("no ticket needed", "            if ticket is None:\n", "            if False:\n",
     lambda e: e.run("install", "brew", "jq", "--why", "need jq", ticket=False), 0),
    ("uninstall anything", "    owned = P.fold(ledger_read(d)).get((inst, name))\n    if not owned:",
     "    owned = P.fold(ledger_read(d)).get((inst, name)) or {\"uninstall\": P.uninstall_argv(inst, name)}\n"
     "    if not owned:",
     lambda e: e.run("uninstall", "brew", "jq", "--why", "not needed"), 0),
    ("relaxers install directly", "        elif report.verdict == \"ask\" or p.get(\"relax\") or ask:",
     "        elif report.verdict == \"ask\" or ask:",
     lambda e: e.run("install", "npm", "semver@7.6.3", "--why", "needs scripts", "--allow-scripts"), 0),
]


@pytest.mark.parametrize("what,old,new,act,mutant_rc", EXE_MUTANTS, ids=[m[0] for m in EXE_MUTANTS])
def test_seeded_executor_bug_is_caught(tmp_path, monkeypatch, what, old, new, act, mutant_rc):
    real = Exe(tmp_path / "real", monkeypatch)
    if what == "uninstall anything":                 # jq is the user's own install
        (real.bin / "installed").mkdir()
        (real.bin / "installed" / "brew-jq").write_text("1.7.1")
    assert act(real) in (3, 4), "the real executor must refuse: %s" % what
    assert real.installs() == []
    root = tmp_path / "mut" / "dot-claude"
    (root / "bin").mkdir(parents=True)
    (root / "hooks").mkdir()
    shutil.copy(POLICY, root / "hooks" / "toolsmith_policy.py")
    text = EXE.read_text()
    assert text.count(old) == 1, old
    (root / "bin" / "stack-install").write_text(text.replace(old, new))
    mut = Exe(tmp_path / "mutworld", monkeypatch, path=root / "bin" / "stack-install")
    if what == "uninstall anything":
        (mut.bin / "installed").mkdir()
        (mut.bin / "installed" / "brew-jq").write_text("1.7.1")
    assert act(mut) == mutant_rc, "the mutant (%s) did not do the unsafe thing" % what
    assert mut.installs(), what
