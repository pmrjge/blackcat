"""codex_guard's no-push port against its oracle: the corpus of tests/test_no_push.py (read with ast,
never imported), the same verdicts as agent_guard.remote_write_in, and the Codex additions (codex
flags, git's file/code options on escalations). DESIGN.md §4.3, §5 row 1, §8.5."""
from __future__ import annotations

import ast
import json

import pytest

from _guard_helpers import (REPO, Guard, Stack, bash, decision, event, load_by_path, perm_denied,
                            reason)

G = load_by_path("codex_guard_nopush", REPO / "dot-config" / "dot-codex_config" / "hooks" / "codex_guard.py")
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
    ag = load_by_path("agent_guard_oracle", REPO / "dot-config" / "dot-claude" / "hooks" / "agent_guard.py")
    cmds = PUSHES + C["OPAQUE"] + C["FORGE_WRITES"] + ALLOWED + C["INDEX_BLINDS"] + \
        [c for c, _ in C["REVIEW_REGRESSIONS"]] + C["GIT_COMMAND_VALUES"] + C["GIT_COMMAND_VALUES_SAFE"]
    diff = [c for c in cmds if (G.remote_write_in(c) or (None,))[0] !=
            (ag.remote_write_in(c) or (None,))[0]]
    assert diff == []


@pytest.mark.parametrize("command", C["GIT_COMMAND_VALUES"])
def test_git_command_values_are_scanned(command):
    """T15 F1 parity: option values git runs, ext:: and configuration from the environment (the oracle's list)."""
    assert (G.remote_write_in(command) or (None,))[0] in ("push", "forge", "opaque"), command


@pytest.mark.parametrize("command", C["GIT_COMMAND_VALUES_SAFE"])
def test_git_command_values_without_push_pass(command):
    assert G.remote_write_in(command) is None, command


# ---------------------------------------------------------------- Codex additions
@pytest.mark.parametrize("command", [
    "codex -c model=x exec hi", "codex --config sandbox_mode=danger-full-access",
    "codex --config=hooks.state={}", "codex exec --dangerously-bypass-approvals-and-sandbox hi",
    "codex --yolo", "codex --profile other", "codex -p other exec x", "bash -c 'codex -c a=b'",
    "/opt/homebrew/bin/codex -cfoo=bar", "co''dex -c x=1", "env X=1 codex --config a=b"])
def test_codex_overrides_refused(command):
    assert G.shell_rule_hit(command)[0] == "codex", command


@pytest.mark.parametrize("command", ["codex --version", "codex exec 'summarize -c flags'",
                                     "rg codex -c", "dot-config/dot-codex_config/tests/run.sh",
                                     "echo codex -c x"])
def test_codex_plain_use_passes(command):
    assert G.shell_rule_hit(command) is None, command


# ---------------------------------------------------------------- git flags (DESIGN 4.3; F's review)
@pytest.mark.parametrize("command", [
    # an inline alias hides push or a `!command`, under any spelling of its name
    "git -c alias.p=push p", "git -c alias.x='!git push' x", "git -c Alias.P=push p",
    "git -c alias.P='!sh' p -c 'git push'", "git -c alias.p='!f() { git push; }; f' p",
    "git -c alias.a=b -c alias.b='send-pack x' a",
    # -C and --exec-path never hide the subcommand
    "git -C /tmp/r push", "git -C/tmp/r push origin main", "git -C a -C b push",
    "git --exec-path=/tmp/x push origin main", "git --exec-path /tmp/x push",
    "git --exec-path=/tmp/x -C r -c alias.p=push p",
    # git configuration through the environment is read like -c
    "GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=alias.p GIT_CONFIG_VALUE_0=push git p",
    "GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=alias.p GIT_CONFIG_VALUE_0='!git push' git p",
    "GIT_CONFIG_PARAMETERS=\"'alias.p'='push'\" git p",
    "export GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=alias.p GIT_CONFIG_VALUE_0=push; git p",
    "GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=alias.P GIT_CONFIG_VALUE_0='!sh' git p -c 'git push'",
    "GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=core.pager GIT_CONFIG_VALUE_0='git push' git log",
    "GIT_CONFIG_PARAMETERS=\"'core.editor'='git push'\" git commit"])
def test_git_flag_evasions_are_pushes(command):
    assert G.remote_write_in(command)[0] == "push", command


@pytest.mark.parametrize("command", [
    "GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=alias.p git p",          # the value is set elsewhere
    "GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=$K GIT_CONFIG_VALUE_0=push git p",
    "GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=alias.p GIT_CONFIG_VALUE_0=$V git p",
    "GIT_CONFIG_PARAMETERS=\"'alias.p\" git p", "git --config-env alias.p=PUSHCMD p"])
def test_git_config_decided_at_run_time_is_opaque(command):
    assert G.remote_write_in(command)[0] == "opaque", command


@pytest.mark.parametrize("command", [
    "git -c alias.st=status st -s", "git --exec-path", "git -C repo log -1",
    "GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=user.name GIT_CONFIG_VALUE_0=x git commit -m x",
    "GIT_CONFIG_PARAMETERS=\"'color.ui'='never'\" git log", "git commit -F msg.txt",
    "git -c core.editor=true commit"])
def test_git_flag_plain_forms_pass(command):
    assert G.remote_write_in(command) is None, command


@pytest.mark.parametrize("command", [
    "git -C /x commit -m m", "git -C~/.codex status", "git --exec-path=/tmp/x status",
    "git --exec-path", "git --git-dir=/tmp/r.git commit -m m", "git --work-tree=/ add .",
    "git --config-env=core.pager=P log", "git -c alias.x=log x", "git -c alias.p=push p",
    "git -c core.editor=/tmp/x commit", "git -c core.fsmonitor=/tmp/x status",
    "git -c core.hooksPath=/tmp/h commit -m m", "git -c include.path=/tmp/c commit -m m",
    "git -c includeIf.gitdir:/x/.path=/tmp/c log", "git -c $K=v commit -m m",
    "git -c remote.origin.uploadpack=/tmp/x fetch",
    "git commit -F /etc/x", "git commit -aF /tmp/m", "git commit -qF/tmp/m", "git commit --file=/tmp/m",
    "git commit --fil=/tmp/m", "git commit --file /tmp/m", "git tag -a v1 -F msg",
    "git tag -u key -F msg v1", "git merge -F msg topic", "git notes add -F /tmp/n",
    "git commit -t /tmp/t", "git commit -at/tmp/t", "git commit --template=/tmp/t",
    "git commit --te=/tmp/t", "git init --template=/tmp/t r", "git clone --template /tmp/t u d",
    "git add --pathspec-from-file=/tmp/list", "git add --pathspec-from=/tmp/list",
    "git reset --pathspec-from-file /tmp/l", "git config --file /tmp/c user.name x",
    "GIT_EXEC_PATH=/tmp/x git commit -m m", "GIT_DIR=/tmp/r.git git commit -m m",
    "GIT_TEMPLATE_DIR=/tmp/t git init r", "GIT_SSH_COMMAND='sh /tmp/x' git fetch",
    "GIT_CONFIG_PARAMETERS=\"'core.pager=sh'\" git log", "EDITOR=/tmp/x git commit",
    "export GIT_EXEC_PATH=/tmp/x; git status", "bash -c 'git -C .. status'"])
def test_git_escalation_options_refused(command):
    assert G.shell_rule_hit(command, escalation=True)[0] == "gitesc", command
    found = G.shell_rule_hit(command, escalation=False)
    assert found is None or found[0] != "gitesc", command


@pytest.mark.parametrize("command", [
    "git commit -F - <<EOF\nmsg\nEOF", "git grep -F needle", "git log -F --grep x",
    "git -c core.hooksPath=/dev/null commit -m m", "git -c user.name=x commit -m m",
    "git log -n 3", "git commit -m 'read it with -F file'", "git commit -nm msg",
    "git commit -S -m m", "git commit -uno -m m", "git commit -C HEAD --reset-author",
    "git log --first-parent", "git add --patch", "GIT_AUTHOR_NAME=x git commit -m m",
    "GIT_TERMINAL_PROMPT=0 git fetch", "PAGER=cat git log", "EDITOR=vi make",
    "git --no-pager log", "git add --pathspec-from-file=- < list"])
def test_git_escalation_plain_forms_pass(command):
    assert G.shell_rule_hit(command, escalation=True) is None, command


@pytest.mark.parametrize("command", [
    "git -c core.hooksPath=/dev/null -C /etc commit -m m",
    "git -c core.hooksPath=/dev/null commit -F /tmp/x",
    "git -c core.hooksPath=/dev/null commit -aF /tmp/x",
    "git -c core.hooksPath=/dev/null commit --templ=/tmp/t",
    "git -c core.hooksPath=/dev/null add --pathspec-from=/tmp/list",
    "git -c core.hooksPath=/dev/null -c alias.c='!sh /tmp/x' c",
    "GIT_EXEC_PATH=/tmp/x git -c core.hooksPath=/dev/null commit -m m"])
def test_allow_rule_form_is_checked_in_pretooluse(command):
    # the --git-allow-rules form runs unsandboxed without a PermissionRequest: PreToolUse checks it
    assert G.shell_rule_hit(command)[0] == "gitesc", command


def test_allow_rule_plain_form_passes():
    assert G.shell_rule_hit("git -c core.hooksPath=/dev/null commit -m 'x'") is None
    assert G.shell_rule_hit("git -c core.hooksPath=/dev/null merge --ff-only topic") is None


# ---------------------------------------------------------------- through the hook
@pytest.fixture
def guard(tmp_path, monkeypatch):
    return Guard(Stack(tmp_path), monkeypatch)


@pytest.mark.parametrize("agent", [None, "coder", "python-engineer", "toolsmith", "default"])
def test_hook_denies_push_for_every_caller(guard, agent):
    out = guard.pre(bash("git -C . push origin main", agent_type=agent))
    assert decision(out) == "deny" and "never push" in reason(out)


@pytest.mark.parametrize("scope", [None, "global"])
@pytest.mark.parametrize("command", ["git -c alias.p=push p", "git -c alias.x='!git push' x",
                                     "git --exec-path=/tmp/x push", "git -C/tmp/r push",
                                     "GIT_CONFIG_PARAMETERS=\"'alias.p'='push'\" git p"])
def test_hook_denies_git_flag_evasions(guard, command, scope):
    out = guard.pre(bash(command, agent_type="python-engineer"), scope=scope)
    assert decision(out) == "deny" and "never push" in reason(out), command


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
