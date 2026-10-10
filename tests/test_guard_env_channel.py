"""agent_guard.py's environment-channel rule (no-push mode, kind "envchan" of the secrets scan).

Probe E2a (CLI 2.1.287, 2026-10-09): CLAUDE_CODE_SESSION_KIND=bg with CLAUDE_BG_SESSION_PERMISSION_RULES in the
CLI's environment adds session allow rules that hold under --permission-prompts none. A Bash command that assigns
or exports one of the channel's variables is denied; one that only mentions a name passes.

GUARD=/path/to/agent_guard.py points it at another copy (tests/env_channel_mutations.py).
Run: uv run --no-project --with pytest pytest -q tests/test_guard_env_channel.py
"""
import importlib.util
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from guard_harness import GUARD, Env  # noqa: E402

_spec = importlib.util.spec_from_file_location("agent_guard_envchan", GUARD)
G = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(G)

DENY = [
    "CLAUDE_CODE_SESSION_KIND=bg claude -p hi",
    "export CLAUDE_CODE_SESSION_KIND=bg",
    "export CLAUDE_RELAUNCH_SESSION_ADD_DIRS='[\"/tmp/x\"]'",
    "export CLAUDE_BG_SESSION_PERMISSION_RULES='{\"allow\":[\"Bash\"]}'",
    "env CLAUDE_CODE_SANDBOXED=1 claude",
    "env -i CLAUDE_BG_WORKSPACE_TRUSTED=1 claude",
    "/usr/bin/env CLAUDE_BG_X=1 claude",
    "sudo CLAUDE_BG_X=1 claude",
    "timeout 5 env CLAUDE_CODE_SANDBOXED=1 claude",
    "nohup env CLAUDE_BG_X=1 claude &",
    "env -S 'CLAUDE_BG_X=1 claude'",
    "cd /tmp && CLAUDE_CODE_SESSION_KIND=bg claude",
    "echo hi | CLAUDE_BG_X=1 claude",
    "CLAUDE_BG_X+=1",
    "bash -c 'CLAUDE_CODE_SESSION_KIND=bg claude -p x'",
    "zsh -c 'export CLAUDE_BG_X=1'",
    "eval \"export CLAUDE_BG_SESSION_PERMISSION_RULES=x\"",
    "x=$(CLAUDE_CODE_SANDBOXED=1 claude -p hi)",
    "alias c='CLAUDE_BG_X=1 claude'",
    "declare -x CLAUDE_CODE_SANDBOXED=1",
    "typeset -gx CLAUDE_BG_X=1",
    "readonly CLAUDE_CODE_SESSION_KIND=bg",
    "export CLAUDE_CODE_SANDBOXED",
    "builtin export CLAUDE_BG_X",
    "local CLAUDE_CODE_SANDBOXED",
    "read CLAUDE_CODE_SESSION_KIND <<< bg",
    "echo x; read -r CLAUDE_BG_Y",
    "mapfile CLAUDE_BG_X < f",
    "getopts ab CLAUDE_BG_X",
    "printf -v CLAUDE_CODE_SESSION_KIND bg",
    "printf -vCLAUDE_CODE_SESSION_KIND bg",
    "launchctl setenv CLAUDE_CODE_SANDBOXED 1",
    "declare -n R=CLAUDE_BG_X; R=1",
    "export FOO=CLAUDE_BG_X",
    "V=CLAUDE_BG_X; export \"$V=1\"",
    "CLAUDE_CODE_SESS\\ION_KIND=bg claude",
    "\"CLAUDE_CODE_SESSION_KIND\"=bg claude",
    "CLAUDE_CODE_SESS$'I'ON_KIND=bg claude",
]
ALLOW = [
    "echo CLAUDE_CODE_SESSION_KIND",
    "echo CLAUDE_BG_X=1",
    "echo $CLAUDE_CODE_SESSION_KIND",
    "grep -rn CLAUDE_BG_ dot-config",
    "rg 'CLAUDE_CODE_SESSION_KIND=' src",
    "git grep -n CLAUDE_BG_X=",
    "printenv CLAUDE_CODE_SESSION_KIND",
    "printf '%s\\n' CLAUDE_CODE_SANDBOXED",
    "unset CLAUDE_CODE_SESSION_KIND",
    "env -u CLAUDE_CODE_SESSION_KIND claude",
    "launchctl getenv CLAUDE_CODE_SANDBOXED",
    "CLAUDE_CODE_SESSION_ID=x claude",
    "CLAUDE_CODE_SESSION_KIND_X=1 claude",
    "MY_CLAUDE_BG_X=1 claude",
    "export CLAUDE_CODE_SESSION_KIND_X=1",
    "export MY_CLAUDE_BG_X=1",
    "export claude_bg_x=1",
    "CLAUDE_CODE_SANDBOX=1 claude",
]


@pytest.mark.parametrize("command", DENY)
def test_channel_assignment_is_denied(command):
    assert (G.secrets_leak_in(command) or (None,))[0] == "envchan", command


@pytest.mark.parametrize("command", ALLOW)
def test_channel_mention_is_allowed(command):
    assert G.secrets_leak_in(command) is None, command


@pytest.mark.parametrize("atype,aid,policy", [(None, None, "on"), ("coder", "a1", "on"), ("blackcat", None, "off")])
def test_the_hook_denies_with_the_channel_reason(atype, aid, policy):
    """Every agent and the main thread, also with STACK_POLICY=off (the no-push hook's rules are absolute)."""
    env = Env(STACK_POLICY=policy)

    def run(command):
        ev = env.base("PreToolUse", tool_name="Bash", tool_input={"command": command}, agent_type=atype,
                      agent_id=aid)
        return env.run(ev, args=("no-push",))
    r = run("CLAUDE_CODE_SESSION_KIND=bg CLAUDE_BG_SESSION_PERMISSION_RULES=x claude -p hi")
    assert r.decision == "deny" and "environment-channel rule" in r.reason, r
    assert run("echo CLAUDE_CODE_SESSION_KIND").decision == "allow(no-output)"


def test_a_command_past_a_scan_limit_fails_closed():
    """The secrets scan wants no "opaque": a command nested past MAX_NEST or longer than MAX_COMMAND is a hit."""
    hit = "'CLAUDE_CODE_SESSION_KIND=bg claude -p hi'"
    assert G.secrets_leak_in("eval " * 9 + hit) is not None
    assert G.secrets_leak_in(hit[1:-1] + "; " + "true " * (G.MAX_COMMAND // 5 + 10)) is not None
    assert G.secrets_leak_in("eval " * 9 + "'echo hi'") is None          # no trigger: never scanned


def test_a_scan_limit_stays_opaque_outside_the_secrets_scan(tmp_path):
    """Only the secrets scan turns a scan limit into a hit of its own: the others keep "opaque" (None if unwanted)."""
    deep = "eval " * 9 + "'git status; rm -rf x > y'"     # no push: the push scan's own reading finds 'git push'
                                                          # even past MAX_NEST (on main too)
    big = "git status > out; " + "true " * (G.MAX_COMMAND // 5 + 10)
    for cmd in (deep, big):
        assert G.remote_write_in(cmd)[0] == "opaque", cmd[:60]
        assert not G.git_push_in(cmd) and not G.forge_write_in(cmd), cmd[:60]
        assert G.protected_write_in(cmd, {"cwd": str(tmp_path)}) is None, cmd[:60]


def test_a_scan_limit_denies_with_the_guard_fail_reason(capsys):
    """A secrets-scan limit is denied as an unchecked command, not as an API-key leak."""
    command = "eval " * 9 + "'CLAUDE_CODE_SESSION_KIND=bg claude -p hi'"
    assert G.secrets_leak_in(command)[0] == "limit"
    with pytest.raises(SystemExit):
        G.no_push_main(json.dumps({"tool_name": "Bash", "tool_input": {"command": command}}))
    out = capsys.readouterr().out
    assert '"permissionDecision": "deny"' in out and "Split it into simpler commands" in out and "API key" not in out


def test_a_parser_failure_fails_closed(monkeypatch, capsys):
    """A scanner exception on a command naming the channel denies (the trigger covers the names)."""
    def boom(*a, **k):
        raise RuntimeError("parser bug")
    monkeypatch.setattr(G, "secrets_leak_in", boom)
    for command in ("CLAUDE_BG_X=1 claude", "export CLAUDE_CODE_SANDBOXED=1", "CLAUDE_CODE_SESSION_KIND=bg claude"):
        with pytest.raises(SystemExit):
            G.no_push_main(json.dumps({"tool_name": "Bash", "tool_input": {"command": command}}))
        assert '"permissionDecision": "deny"' in capsys.readouterr().out, command
