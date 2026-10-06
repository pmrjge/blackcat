"""Self-protection and credentials (DESIGN.md §4.2 b-d, f): apply_patch paths resolved against cwd
with symlinks resolved; shell writes under CODEX_HOME, ~/.agents and the guard state; auth.json and
stack.env through shell, apply_patch, view_image and MCP path arguments; escalations that touch a
protected root. Both scopes: these checks are profile-neutral."""
from __future__ import annotations

import json
import os

import pytest

from _guard_helpers import Guard, Stack, bash, decision, event, perm_denied, pre, reason


@pytest.fixture
def stack(tmp_path):
    return Stack(tmp_path)


@pytest.fixture
def guard(stack, monkeypatch):
    return Guard(stack, monkeypatch)


def patch(*headers, body="+x\n"):
    lines = ["*** Begin Patch"]
    for h in headers:
        lines += [h, body.rstrip("\n")]
    return "\n".join(lines + ["*** End Patch"]) + "\n"


# ---------------------------------------------------------------- apply_patch
@pytest.mark.parametrize("scope", [None, "global"])
@pytest.mark.parametrize("header", ["*** Add File: {ch}/stack/hooks/codex_guard.py",
                                    "*** Update File: {ch}/codex.config.toml",
                                    "*** Delete File: {ch}/rules/claude-agent-stack.rules",
                                    "*** Update File: {home}/.agents/skills/x/SKILL.md",
                                    "*** Add File: {state}/sessions/s/state.json"])
def test_apply_patch_into_protected_roots_denied(guard, stack, header, scope):
    h = header.format(ch=stack.codex_home, home=stack.home, state=stack.state)
    out = guard.pre(pre("apply_patch", {"command": patch(h)}), scope=scope)
    assert decision(out) == "deny" and "protected root" in reason(out)


def test_apply_patch_relative_path_resolves_against_cwd(guard, stack):
    ev = pre("apply_patch", {"command": patch("*** Update File: config.toml")},
             cwd=str(stack.codex_home))
    assert decision(guard.pre(ev)) == "deny"
    ev = pre("apply_patch", {"command": patch("*** Update File: ../.codex/config.toml")},
             cwd=str(stack.home / ".agents"))
    assert decision(guard.pre(ev)) == "deny"
    ok = pre("apply_patch", {"command": patch("*** Update File: src/app.py")})
    assert guard.pre(ok) is None


def test_apply_patch_through_a_symlink_into_codex_home_denied(guard, stack):
    os.symlink(stack.codex_home, stack.project / "innocent")
    ev = pre("apply_patch", {"command": patch("*** Add File: innocent/rules/x.rules")})
    assert decision(guard.pre(ev)) == "deny"


def test_apply_patch_move_target_checked(guard, stack):
    text = patch("*** Update File: notes.md\n*** Move to: %s/AGENTS.md" % stack.codex_home)
    assert decision(guard.pre(pre("apply_patch", {"command": text}))) == "deny"


def test_apply_patch_credentials_denied(guard, stack):
    for target in ("%s/auth.json" % stack.codex_home, ".env", "%s/.ssh/config" % stack.home):
        out = guard.pre(pre("apply_patch", {"command": patch("*** Add File: " + target)}))
        assert decision(out) == "deny" and "credential" in reason(out), target


def test_apply_patch_unreadable_input_denied(guard):
    assert decision(guard.pre(pre("apply_patch", 42))) == "deny"
    ev = pre("apply_patch", {"command": patch("*** Add File: x.py")}, cwd="relative/dir")
    assert decision(guard.pre(ev)) == "deny"


def test_apply_patch_inside_a_shell_command_checked(guard, stack):
    cmd = "apply_patch <<'EOF'\n%sEOF" % patch("*** Update File: %s/config.toml" % stack.codex_home)
    assert decision(guard.pre(bash(cmd))) == "deny"


# ---------------------------------------------------------------- shell writes under protected roots
@pytest.mark.parametrize("command", [
    "rm -rf {ch}", "rm -rf ~/.codex", "echo x > ~/.codex/config.toml", "echo x >> $CODEX_HOME/AGENTS.md",
    "cp /tmp/evil.py {ch}/stack/hooks/codex_guard.py", "mv {ch}/codex.config.toml /tmp/x",
    "chmod 777 {ch}/stack/hooks", "ln -sf /tmp/x ~/.agents/skills/y", "touch {state}/x",
    "cd ~/.codex && rm -rf stack", "cd {ch}; echo hi > rules/x.rules", "sed -i '' s/a/b/ ~/.codex/config.toml",
    "bash -c 'rm -rf ~/.codex/stack'", "find ~/.codex -name '*.toml' -delete",
    "D=~/.codex; rm -rf $D", "python3 -c 'import os; os.remove(\"x\")' ~/.codex/x",
    "tee ~/.agents/skills/x/SKILL.md < /tmp/x", "git -C ~/.codex init",
    "dd if=/dev/zero of={ch}/auth2.json", "curl -o ~/.codex/x https://example.com"])
@pytest.mark.parametrize("scope", [None, "global"])
def test_shell_writes_under_protected_roots_denied(guard, stack, command, scope):
    cmd = command.format(ch=stack.codex_home, state=stack.state)
    out = guard.pre(bash(cmd, agent_type="python-engineer"), scope=scope)
    assert decision(out) == "deny", cmd
    assert "protected root" in reason(out) or "credential" in reason(out), reason(out)


@pytest.mark.parametrize("command", [
    "cat ~/.codex/config.toml", "sed -n 1,40p ~/.agents/skills/x/SKILL.md", "ls -la ~/.codex/stack",
    "rg -n model {ch}/codex.config.toml", "git commit -m 'never touch ~/.codex or .agents'",
    "echo 'see ~/.codex/config.toml' > notes.md", "python3 ~/.agents/skills/x/scripts/tool.py in.txt",
    "cat ~/.codex/config.toml | tee /tmp/copy", "echo hi > /dev/null"])
def test_shell_reads_and_mentions_pass(guard, stack, command):
    cmd = command.format(ch=stack.codex_home)
    assert guard.pre(bash(cmd, agent_type="python-engineer")) is None, cmd


# ---------------------------------------------------------------- credentials
@pytest.mark.parametrize("command", [
    "cat ~/.codex/auth.json", "cat {ch}/auth.json", "cd ~/.codex && cat auth.json",
    "cat ~/.co''dex/auth.json", "jq . \"$CODEX_HOME/auth.json\"", "cat ~/.codex/stack.env",
    "source stack.env", "cat ~/.ssh/id_ed25519", "cd ~/.ssh && cat id_ed25519", "cat .env",
    "bash -c 'cat ~/.codex/auth.json'", "grep TOKEN {proj}/.env.local"])
@pytest.mark.parametrize("scope", [None, "global"])
def test_credentials_through_shell_denied(guard, stack, command, scope):
    cmd = command.format(ch=stack.codex_home, proj=stack.project)
    out = guard.pre(bash(cmd), scope=scope)
    assert decision(out) == "deny" and "credential" in reason(out), cmd


def test_auth_json_elsewhere_is_not_a_credential(guard):
    assert guard.pre(bash("cat package/auth.json")) is None


@pytest.mark.parametrize("args", [
    {"path": "{ch}/auth.json"}, {"file_path": "~/.codex/stack.env"}, {"uri": "file://{ch}/auth.json"},
    {"paths": ["/tmp/a.txt", "{home}/.ssh/id_rsa"]}, {"nested": {"source": "{home}/.aws/credentials"}}])
def test_credentials_through_mcp_path_args_denied(guard, stack, args):
    raw = json.loads(json.dumps(args).replace("{ch}", str(stack.codex_home)).replace(
        "{home}", str(stack.home)))
    out = guard.pre(pre("mcp__libdocs__read_file", raw, agent_type="python-engineer"))
    assert decision(out) == "deny" and "credential" in reason(out)
    out = guard.pre(pre("mcp__anything__read", raw), scope="global")
    assert decision(out) == "deny"


def test_mcp_write_under_protected_root_denied_read_allowed(guard, stack):
    target = {"path": str(stack.codex_home / "config.toml")}
    assert decision(guard.pre(pre("mcp__fs__write_file", target), scope="global")) == "deny"
    assert guard.pre(pre("mcp__fs__read_file", target), scope="global") is None


def test_view_image_of_a_credential_denied(guard, stack):
    out = guard.pre(pre("view_image", {"path": str(stack.codex_home / "auth.json")}),
                    scope="global")
    assert decision(out) == "deny"


# ---------------------------------------------------------------- the roots themselves
def test_codex_home_is_protected_even_when_the_list_omits_it(tmp_path, monkeypatch):
    stack = Stack(tmp_path, guard_overrides={"protected_roots": []})
    guard = Guard(stack, monkeypatch)
    out = guard.pre(bash("rm -rf %s/stack" % stack.codex_home, agent_type="python-engineer"))
    assert decision(out) == "deny"
    out = guard.pre(pre("apply_patch", {"command": patch(
        "*** Update File: %s/codex.config.toml" % stack.codex_home)}))
    assert decision(out) == "deny"
    out = guard.pre(bash("echo x > %s/f" % stack.state, agent_type="python-engineer"))
    assert decision(out) == "deny"


def test_extra_protected_root_from_guard_json(tmp_path, monkeypatch):
    extra = tmp_path / "extra"
    stack = Stack(tmp_path, guard_overrides={"protected_roots": [str(extra)]})
    guard = Guard(stack, monkeypatch)
    assert decision(guard.pre(bash("rm -rf %s/x" % extra, agent_type="python-engineer"))) == "deny"


# ---------------------------------------------------------------- escalations
@pytest.mark.parametrize("command", ["cat ~/.codex/config.toml", "ls ~/.agents",
                                     "rg x {ch}", "cat ~/.codex/auth.json"])
def test_escalation_touching_protected_roots_denied(guard, stack, command):
    ev = event("permission_request", tool_input={"command": command.format(ch=stack.codex_home)})
    assert perm_denied(guard.perm(ev))
    assert perm_denied(guard.perm(ev, scope="global"))


def test_escalated_patch_into_codex_home_denied(guard, stack):
    ev = event("permission_request", tool_name="apply_patch",
               tool_input={"command": patch("*** Add File: %s/x" % stack.codex_home)})
    assert perm_denied(guard.perm(ev))


def test_plain_escalation_reaches_the_user(guard):
    ev = event("permission_request", tool_input={"command": "git commit -m 'x'"})
    assert guard.perm(ev) is None
