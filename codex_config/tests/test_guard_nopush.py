"""codex_guard's no-push port against its oracle: the corpus of tests/test_no_push.py (read with ast,
never imported), the same verdicts as agent_guard.remote_write_in, and the Codex additions (codex
flags, git's file/code options on escalations). DESIGN.md §4.3, §5 row 1, §8.5."""
from __future__ import annotations

import ast
import json

import pytest

from _guard_helpers import (REPO, Guard, Stack, bash, decision, event, load_by_path, perm_denied,
                            reason)

G = load_by_path("codex_guard_nopush", REPO / "codex_config" / "hooks" / "codex_guard.py")
ORACLE = REPO / "tests" / "test_no_push.py"


def _const(node):
    """Evaluate a literal expression of strings, lists, tuples, None, + and * (no eval)."""
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, (ast.List, ast.Tuple)):
        items = [_const(e) for e in node.elts]
        return items if isinstance(node, ast.List) else tuple(items)
    if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Mult)):
        a, b = _const(node.left), _const(node.right)
        return a + b if isinstance(node.op, ast.Add) else a * b
    raise ValueError("not a literal: %s" % ast.dump(node)[:80])


def corpus():
    tree = ast.parse(ORACLE.read_text())
    out = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and \
                isinstance(node.targets[0], ast.Name) and node.targets[0].id.isupper():
            try:
                out[node.targets[0].id] = _const(node.value)
            except ValueError:
                pass
    return out


C = corpus()
PUSHES = C["PUSHES"] + C["NESTED_PUSHES"] + C["OBFUSCATED_PUSHES"]
ALLOWED = C["NOT_PUSHES"] + C["FORGE_READS"] + C["INDEX_SAFE"]


def test_corpus_was_read():
    assert len(PUSHES) > 90 and len(C["FORGE_WRITES"]) >= 50 and len(C["REVIEW_REGRESSIONS"]) > 100
    assert len(C["INDEX_BLINDS"]) > 30 and len(ALLOWED) > 80


@pytest.mark.parametrize("command", PUSHES)
def test_push_detected(command):
    assert G.remote_write_in(command)[0] == "push", command


@pytest.mark.parametrize("command", C["OPAQUE"])
def test_opaque_refused(command):
    assert G.remote_write_in(command)[0] == "opaque", command


@pytest.mark.parametrize("command", C["FORGE_WRITES"])
def test_forge_write_detected(command):
    assert G.remote_write_in(command)[0] == "forge", command


@pytest.mark.parametrize("command", C["INDEX_BLINDS"] + C["NESTED_INDEX_BLINDS"])
def test_index_blinding_detected(command):
    assert G.remote_write_in(command)[0] == "index", command


@pytest.mark.parametrize("command", ALLOWED)
def test_allowed_commands_pass(command):
    assert G.remote_write_in(command) is None, command


@pytest.mark.parametrize("command,kind", C["REVIEW_REGRESSIONS"])
def test_review_regressions(command, kind):
    found = G.remote_write_in(command)
    assert (found[0] if found else None) == kind, (command, found)


@pytest.mark.parametrize("command", C["SECRETS_LEAKS"])
def test_secrets_leaks_refused(command):
    assert G.shell_rule_hit(command)[0] == "secrets", command


@pytest.mark.parametrize("command", C["SECRETS_SAFE"])
def test_secrets_safe_forms_pass(command):
    assert G.shell_rule_hit(command) is None, command


def test_deep_nesting_is_refused_not_ignored():
    cmd = "git push"
    for _ in range(G.MAX_NEST + 2):
        cmd = "bash -c %s" % json.dumps(cmd)
    assert G.remote_write_in(cmd)[0] == "opaque"


def test_same_verdicts_as_agent_guard():
    """Differential: the port and the original agree on every corpus command."""
    ag = load_by_path("agent_guard_oracle", REPO / "dot-claude" / "hooks" / "agent_guard.py")
    cmds = PUSHES + C["OPAQUE"] + C["FORGE_WRITES"] + ALLOWED + C["INDEX_BLINDS"] + \
        [c for c, _ in C["REVIEW_REGRESSIONS"]]
    diff = [c for c in cmds if (G.remote_write_in(c) or (None,))[0] !=
            (ag.remote_write_in(c) or (None,))[0]]
    assert diff == []


# ---------------------------------------------------------------- Codex additions
@pytest.mark.parametrize("command", [
    "codex -c model=x exec hi", "codex --config sandbox_mode=danger-full-access",
    "codex --config=hooks.state={}", "codex exec --dangerously-bypass-approvals-and-sandbox hi",
    "codex --yolo", "codex --profile other", "codex -p other exec x", "bash -c 'codex -c a=b'",
    "/opt/homebrew/bin/codex -cfoo=bar", "co''dex -c x=1", "env X=1 codex --config a=b"])
def test_codex_overrides_refused(command):
    assert G.shell_rule_hit(command)[0] == "codex", command


@pytest.mark.parametrize("command", ["codex --version", "codex exec 'summarize -c flags'",
                                     "rg codex -c", "codex_config/tests/run.sh",
                                     "echo codex -c x"])
def test_codex_plain_use_passes(command):
    assert G.shell_rule_hit(command) is None, command


@pytest.mark.parametrize("command", [
    "git -C /x commit -m m", "git --exec-path=/tmp/x status", "git -c alias.x=log x",
    "git commit -F /etc/x", "git commit --file=/tmp/m", "git tag -a v1 -F msg",
    "git config --file /tmp/c user.name x", "bash -c 'git -C .. status'"])
def test_git_escalation_options_refused(command):
    assert G.shell_rule_hit(command, escalation=True)[0] == "gitesc", command
    assert G.shell_rule_hit(command, escalation=False) is None or \
        G.shell_rule_hit(command)[0] != "gitesc"


@pytest.mark.parametrize("command", ["git commit -F - <<EOF\nmsg\nEOF", "git grep -F needle",
                                     "git -c core.hooksPath=/dev/null commit -m m",
                                     "git log -n 3"])
def test_git_escalation_plain_forms_pass(command):
    assert G.shell_rule_hit(command, escalation=True) is None, command


def test_allow_rule_form_is_checked_in_pretooluse():
    # the --git-allow-rules form runs unsandboxed without a PermissionRequest: PreToolUse checks it
    assert G.shell_rule_hit("git -c core.hooksPath=/dev/null -C /etc commit -m m")[0] == "gitesc"
    assert G.shell_rule_hit("git -c core.hooksPath=/dev/null commit -F /tmp/x")[0] == "gitesc"


# ---------------------------------------------------------------- through the hook
@pytest.fixture
def guard(tmp_path, monkeypatch):
    return Guard(Stack(tmp_path), monkeypatch)


@pytest.mark.parametrize("agent", [None, "coder", "python-engineer", "toolsmith", "default"])
def test_hook_denies_push_for_every_caller(guard, agent):
    out = guard.pre(bash("git -C . push origin main", agent_type=agent))
    assert decision(out) == "deny" and "never push" in reason(out)


@pytest.mark.parametrize("command", ["bash -c 'git push origin main'", "eval 'git push'",
                                     "gh pr merge 1 --squash", "git update-index --skip-worktree f"])
def test_hook_denies_rule_hits_in_global_scope(guard, command):
    out = guard.pre(bash(command), scope="global")
    assert decision(out) == "deny"


def test_hook_forge_reason_names_the_command(guard):
    out = guard.pre(bash("bash -c 'gh pr merge 1 --squash'"))
    assert "never write to a forge" in reason(out) and "gh pr merge" in reason(out)


def test_permission_request_denies_push_and_gitesc(guard):
    assert perm_denied(guard.perm(event("permission_request", tool_input={"command": "git push"})))
    out = guard.perm(event("permission_request", tool_input={"command": "git -C /x commit -m m"}))
    assert perm_denied(out) and "-C" in out["hookSpecificOutput"]["decision"]["message"]
    assert guard.perm(event("permission_request",
                            tool_input={"command": "git commit -m m"})) is None
