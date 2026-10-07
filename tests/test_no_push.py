"""Tests for agent_guard.py no-push mode: the stack's Git rule says agents never push and never
write to a forge (gh, tea, fj), also through `bash -c`, `eval`, `$(...)` and other wrappers.

Run: uv run --with pytest pytest -q tests/test_no_push.py
"""
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
GUARD = ROOT / "dot-claude" / "hooks" / "agent_guard.py"
sys.path.insert(0, str(GUARD.parent))
import agent_guard as G  # noqa: E402

PUSHES = [
    "git push", "git push origin main", "git push --force-with-lease", "git -C /x push",
    "git -c a=b push origin", "git 'push' origin", "cd x && git push", "cd x; git push", "cd x\ngit push",
    "/usr/bin/git push", "echo $(git push)", 'echo "$(git push origin)"', "echo `git push`",
    "git --git-dir=/r/.git push", "git --git-dir /r/.git push", "git --no-pager push",
    "git lfs push origin main", "git subtree push --prefix=d r main", "git send-pack r", "(git push)",
    "git -C x push 2>&1 | tail", "FOO=1 git push", "git status && git push -u origin HEAD",
    "git -C 'dir with space' push",
    "git commit -m \"$(cat <<'EOF'\nmsg\nEOF\n)\" && git push",
    "cat <<EOF > f\nx\nEOF\ngit push",
]
# A push hidden in a string that another program runs as shell code (the review's gap 1).
NESTED_PUSHES = [
    "bash -c 'git push origin main'",
    'sh -c "git push origin main"',
    "zsh -c 'git push'",
    "eval 'git push'",
    'eval "git push origin HEAD"',
    "eval git push",
    "bash -lc 'git push'",
    "bash -o pipefail -c 'git push'",
    "/bin/bash -c 'cd repo && git push'",
    "dash -c 'git push'", "ksh -c 'git push'", "fish -c 'git push'", "fish --command='git push'",
    "env FOO=1 bash -c 'git push'",
    "sudo -u me sh -c 'git push'",
    "echo hi && bash -c 'git push'",
    "bash -c 'git status' ; sh -c \"git -C repo push --force\"",
    "find . -maxdepth 0 -exec sh -c 'git push' \\;",
    "xargs -I{} sh -c '{}' <<< 'git push'",
    "bash -c 'git lfs push origin main'",
    "bash -c 'git svn dcommit'",
    "ssh host 'cd repo && git push'",
    "watch -n 60 'git push'",
    "su -c 'git push' me",
    "tmux send-keys -t s 'git push' Enter",
]
# Nesting, quoting, whitespace and substitution variants.
OBFUSCATED_PUSHES = [
    "bash -c '   git    push   '",
    "bash -c \"bash -c 'git push'\"",
    "bash -c \"sh -c \\\"eval 'git push'\\\"\"",
    "sh -c 'eval \"git push\"'",
    "bash -c \"$(echo 'git push')\"",
    "bash -c \"$(printf '%s %s' git push)\"",
    "bash -c \"$(cat <<'EOF'\ngit push\nEOF\n)\"",
    "eval \"$(echo 'git push')\"",
    "eval $(echo git push)",
    "$(echo 'git push')",
    "`echo git push`",
    "echo \"$(bash -c \"$(echo x)\"; git push)\"",
    "g''it push", "\"git\" 'push'", "g\\it pu\\sh",
    "$'\\x67it' push", "$'\\147it' push", "git $'\\x70ush'", "bash -c $'git\\x20push'",
    "echo 'git push' | sh", "printf 'git push\\n' | bash", "echo -e '\\x67it push' | sh",
    "bash <<< 'git push'", "bash <<EOF\ngit push\nEOF", "cat <<'EOF' | sh\ngit push\nEOF",
    "ssh host <<'EOF'\ncd repo && git push\nEOF",
    "source <(echo 'git push')", "bash < <(echo 'git push')",
    "cat <<EOF\n$(git push)\nEOF",                       # unquoted heredoc bodies expand $(...)
    'echo "<<EOF"\ngit push\nEOF',                       # << inside quotes starts no heredoc
    "cat <<<x\ngit push\nx",                             # <<< is a here-string, not a heredoc
    "python3 -c \"import subprocess; subprocess.run(['git', 'push'])\"",
    "perl -e 'system(\"git push\")'",
    "node -e \"require('child_process').execSync('git push')\"",
    "git -c alias.p=push p", "git config alias.p push", "git config --global alias.pf 'push --force'",
    "alias gp='git push'",
    "$(git --exec-path)/git-push origin", "exec git-push origin",
    "osascript -e 'do shell script \"git push\"'",
]
# A git subcommand the shell decides only when it runs: refused, it cannot be checked.
OPAQUE = [
    "git $SUB origin", 'git "$(echo push)"', "git {push,status}", "echo push | xargs git",
    "$(echo git) push", "G=git; $G push", "git --config-env=alias.p=PUSHCMD p",
]
NOT_PUSHES = [
    "git status", 'git commit -m "document the git push rule"', "git log --grep push", "git help push",
    "grep -rn 'git push' .", "git merge --ff-only feat", "git -C /x merge --ff-only push",
    "git config push.default current", "ls", "gitk --all", "git branch push-fix", "git switch -c push",
    "git log -- push.py", "python3 x.py push", 'git commit -m "x',
    "git commit -m \"$(cat <<'EOF'\nAgents never git push.\ngit push is the user's step\nEOF\n)\"",
    "git commit -F - <<EOF\nno git push here\nEOF",
    # data, not code: a string nobody runs as a command
    "echo 'git push'", "echo '$(git push)'", "sh -c 'echo \"never git push\"'",
    "bash -c 'git status'", "eval 'git log --oneline'", "bash tests/install_smoke.sh && git commit -m 'no git push'",
    "python3 - <<'PY'\nPUSHES = ['git push']\nPY", "cat > x.sh <<'EOF'\ngit push\nEOF",
    "VAR=$(git rev-parse HEAD) && echo $VAR", 'git -C "$(git rev-parse --show-toplevel)" status',
    "echo \"$(printf 'we never git push')\"", "$(which python3) -m pytest", "bash script.sh",
    "curl -s https://example.com/install.sh | bash", "IFS=$'\\n' read -r x <<< \"$y\"",
    "git commit -m $'line1\\nline2'", "bash -c 'git status' < /dev/null", "npm test && git log -1",
    "man git-push | head", "python3 -c \"print('git push is the user step')\"",
    "osascript -e 'display notification \"git push is the user step\"'",
]
FORGE_WRITES = [
    "gh pr create --fill", "gh pr new", "gh pr merge 12 --squash", "gh pr review 3 --approve",
    "gh pr comment 3 -b ok", "gh pr close 3", "gh pr ready", "gh release create v1", "gh release upload v1 a.tgz",
    "gh issue create -t x", "gh issue comment 3 -b hi", "gh repo create x", "gh repo fork", "gh repo sync",
    "gh workflow run ci.yml", "gh secret set X", "gh -R o/r pr create", "cd x && gh pr create",
    "gh api repos/o/r/pulls -f title=x", "gh api -X POST repos/o/r/issues", "gh api --method=PATCH repos/o/r",
    "gh api -XDELETE repos/o/r", "gh api repos/o/r/issues --input body.json",
    "gh api graphql -f query='mutation { addStar(input: {}) { clientMutationId } }'",
    "gh alias set pc 'pr create --fill'",
    "tea pulls create --title x", "tea pr merge 3", "tea pulls approve 2", "tea pr clean 3",
    "tea comment 5 'LGTM'", "tea c 5 hi", "tea comments add 5 hi", "tea releases create --tag v1",
    "tea issues create -t x", "tea actions secrets set X", "tea api -X POST /repos/o/r/issues",
    "fj pr create 'title' --body x", "fj pr merge 3", "fj pr comment 3 hi", "fj release create v1",
    "fj repo create x", "fj repo fork o/r", "fj issue close 3", "fj org visibility o --set public",
    # nested like a push
    "bash -c 'gh pr merge 1'", "sh -c \"tea pr merge 3\"", "eval 'gh release upload v1 a.tgz'",
    "zsh -c 'fj pr merge 3'", "bash -c \"$(echo 'gh pr create --fill')\"",
    "python3 -c \"import os; os.system('gh pr create --fill')\"",
]
FORGE_READS = [
    "gh pr view 12", "gh pr list", "gh pr checks 3 --watch", "gh pr diff", "gh pr checkout 3", "gh pr status",
    "gh run view 1 --log-failed", "gh run watch 1", "gh api repos/o/r/pulls", "gh api -X GET search/issues -f q=x",
    "gh api graphql -f query='query { viewer { login } }'", "gh repo clone o/r", "gh repo view", "gh auth status",
    "gh release view v1", "gh release download v1", "gh issue list --label create", "gh search prs merge",
    "gh browse -n", "gh alias set co 'pr checkout'",
    "tea pulls list", "tea pr checkout 3", "tea pr 3", "tea comments list 5", "tea issues", "tea api /repos/o/r",
    "tea login add --name x", "fj pr view 3", "fj pr checkout 3", "fj org visibility o", "fj release list",
    "brew install gh git tea", "which gh", "bash -c 'gh pr view 3'",
]


@pytest.mark.parametrize("command", PUSHES + NESTED_PUSHES + OBFUSCATED_PUSHES)
def test_push_detected(command):
    assert G.git_push_in(command)
    assert G.remote_write_in(command)[0] == "push"


@pytest.mark.parametrize("command", OPAQUE)
def test_unresolvable_git_subcommand_refused(command):
    assert G.remote_write_in(command)[0] == "opaque"


@pytest.mark.parametrize("command", NOT_PUSHES + FORGE_READS)
def test_non_push_allowed(command):
    assert not G.git_push_in(command)
    assert G.remote_write_in(command) is None


@pytest.mark.parametrize("command", FORGE_WRITES)
def test_forge_write_detected(command):
    assert G.forge_write_in(command)
    assert G.remote_write_in(command)[0] == "forge"


@pytest.mark.parametrize("command", FORGE_READS)
def test_forge_read_allowed(command):
    assert not G.forge_write_in(command)


# Found in review: each input with the kind the detector must report (None = allowed).
REVIEW_REGRESSIONS = [
    # a placeholder from one parsing level used at another crashed the scan (the hook then fell
    # back to a push-only regex and let forge writes through)
    ('$(echo "bash ~/github/$(date +%F).sh"); gh pr merge 1 --squash', "forge"),
    ("eval '$__SUBST9__'; gh pr merge 1", "forge"),
    # comments, line continuations and newlines are shell syntax
    ("# Let's publish the branch\ngit -C ~/src/app push origin main  # user's call", "push"),
    ("git status  # the user will git push later", None),
    ("git -C /repo \\\n  push origin main", "push"),
    ("bash tests/install_smoke.sh\ngit commit -m \"docs: agents never git push\"", None),
    ("eval \"$(/opt/homebrew/bin/brew shellenv)\"\ngit commit -m \"Explain why agents never git push\"", None),
    # a heredoc belongs to the command that owns its <<
    ("source .venv/bin/activate && git commit -m \"$(cat <<'EOF'\nfix: agents never git push\nEOF\n)\"", None),
    ("git add . && git commit -m \"$(cat <<'EOF'\nThe hook now denies gh pr create\nEOF\n)\"", None),
    ("bash tests/x.sh && git commit -m \"$(cat <<'EOF'\nagents never git push\nEOF\n)\"", None),
    ("git commit -F - <<'EOF' && bash tests/install_smoke.sh\nno git push\nEOF", None),
    ("sudo bash <<EOF\ngit push\nEOF", "push"), ("source /dev/stdin <<EOF\ngit push\nEOF", "push"),
    ("bash 2>&1 <<EOF\ngit push\nEOF", "push"),
    # a shell's script arguments and $0 are not code; $1 in the -c string makes them code
    ("bash scripts/notify.sh \"reminder: never git push\"", None),
    ("bash -c 'make test' arg0 'gh pr create is the user step'", None),
    ("bash -c '$1' _ 'git push'", "push"),
    # git runs these values and arguments as commands
    ("git submodule foreach 'git push origin main'", "push"),
    ("git rebase --exec 'git push -f' HEAD~3", "push"), ("git rebase -x 'git push' main", "push"),
    ("git bisect run sh -c 'git push'", "push"),
    ("git -c core.editor='git push' commit", "push"), ("GIT_EDITOR='git push' git commit", "push"),
    ("git -c alias.pc='!gh pr create --fill' pc", "forge"), ("git -c alias.p='!git pu\"\"sh' p", "push"),
    ("git config --global alias.lg 'log --oneline --grep push'", None),
    ("GIT_EDITOR=true git merge --no-ff x", None),
    # arithmetic, $'...' inside double quotes, redirections and options between words
    (": $((1<<2))\ngit push", "push"), ("x=$((1<<2)); git log", None),
    ("echo \"$'\" \\\" ; git push ; echo \\\" \"'\"", "push"),
    ("git 2>/dev/null push origin main", "push"), ("git -C repo >/tmp/log push", "push"),
    ("git subtree -P lib push origin main", "push"), ("git -C x svn --quiet dcommit", "push"),
    ("git --attr-source HEAD push", "push"),
    # pipes into a shell behind env/command, substitutions behind sudo/env
    ("echo \"git push\" | env bash", "push"), ("echo 'git push' | command sh", "push"),
    ("sudo $(printf 'git push')", "push"), ("env $(printf 'gh pr merge 1')", "forge"),
    ("echo Z2l0IHB1c2g= | base64 -d | sh", "opaque"), ("curl -fsSL https://example.com/i.sh | bash", None),
    # names spelled at run time
    ("g$@it push", "opaque"), ("g${X}it push", "opaque"), ("/usr/bin/$G push", "opaque"),
    ("$G push", "opaque"), ("printf 'pr merge 3' | xargs gh", "opaque"), ("gh $SUB merge 3", "opaque"),
    ("docker -H \"$DOCKER_HOST\" push ghcr.io/o/img:1", None), ("docker push $IMAGE", None),
    ("gh -R \"$REPO\" pr list", None), ('tea pr "$N"', None),
    # PowerShell
    ("pwsh -c 'git push'", "push"), ("pwsh -Command \"gh pr merge 1\"", "forge"),
    ("iex 'git push'", "push"), ("Invoke-Expression 'git push'", "push"),
    ("pwsh -EncodedCommand ZwBpAHQA", "opaque"),
    # text, not commands
    ("cat > notes.md <<EOF\nRun \\`git push origin main\\` yourself\nEOF", None),
    ("python3 -c \"import sys; print('rerun git push later')\"", None),
    ("gh pr create --help", None), ("gh issue develop --list 12", None), ("gh issue develop 12", "forge"),
    # second review round
    ('pwsh -ExecutionPolicy Bypass -Command "git push"', "push"),
    ('powershell -ExecutionPolicy Bypass -Command "gh pr merge 1"', "forge"),
    ('pwsh -NoProfile -WorkingDirectory C:/repo -Command "git push origin main"', "push"),
    ("pwsh -File deploy.ps1", None), ('pwsh -NoProfile -Command "git status"', None),
    ("echo $(true)#; git push origin main", "push"), ("echo $((1))#; git -C . push", "push"),
    ("(cd x)# comment\ngit status", None),
    ("gh pr create --fill --body -h", "forge"), ("gh pr merge 3 --squash --subject --help", "forge"),
    ("gh issue comment 3 --body -h", "forge"), ("gh pr create --fill --help", None),
    ("while read -r cmd; do eval \"$cmd\"; done <<'EOF'\ngit push origin main\nEOF", "push"),
    ("while read -r l; do echo \"$l\"; done <<'EOF'\ngit push origin main\nEOF", None),
    ("bash <(cat <<'EOF'\ngit push origin main\nEOF\n)", "push"),
    ("source <(cat <<'EOF'\ngit push\nEOF\n)", "push"), ("tee >(git push) < /dev/null", "push"),
    ("diff <(git show HEAD:a) <(git show HEAD~1:a)", None),
    ("curl -fsSL https://example.com/install.sh | tr -d '\\r' | bash", None),
    ("gunzip -c setup.sh.gz | sh", None), ("echo 'hsup tig' | rev | sh", "opaque"),
    ("base64 -d <<< Z2l0IHB1c2g= | bash", "opaque"),
    ("bash -c 'for f in \"$@\"; do echo \"$f\"; done' _ 'git push docs' notes.md", None),
    ("sh -c 'printf \"%s\\n\" \"$1\"' _ \"note: git push is the user's step\"", None),
    ("bash -c '\"$@\"' _ git push", "push"), ("sh -c 'eval \"$1\"' _ 'git push'", "push"),
    ("python3 -c \"import sys; print('run: git push')\"", None), ("ruby -e 'system \"git push\"'", "push"),
    ("echo `echo \\`git push\\``", "push"), ("env -S 'git push origin main'", "push"),
    ("env -S'gh pr merge 1'", "forge"), ("sh -c \"$(printf 'git %s' push)\"", "push"),
    ("git -c alias.p='!sh' p -c 'git push'", "push"), ("git -c alias.st=status st -s", None),
    ("$(which python3) -c \"import subprocess; subprocess.run(['git','push'])\"", "push"),
    ("Start-Process git -ArgumentList \"push\",\"origin\"", "push"),
    ("git log " + "<<A " * 100 + "\n" + "A\n" * 100 + "git push origin main", "opaque"),
    # third review round: pwsh switch prefixes and stdin, compound heredocs, prefix options
    ('pwsh -nop -exec bypass -c "git push"', "push"), ("pwsh -Execution Bypass -Command 'git push'", "push"),
    ('pwsh -NoProfile -Comm "git push"', "push"), ("pwsh -co 'gh pr merge 1'", "forge"),
    ("pwsh -encodedc ZwBpAHQA", "opaque"), ("echo 'git push' | pwsh -Command -", "push"),
    ("echo 'git push' | pwsh", "push"), ("pwsh /c 'git push'", "push"), ("pwsh -nop -c 'git status'", None),
    ("while read -r pat; do grep -rn \"$pat\" . ; done <<'EOF'\ngit push\ngh pr create\nEOF", None),
    ("for f in *.md; do wc -l \"$f\"; done\nbash -n x.sh\n"
     "while read -r l; do echo \"$l\"; done <<'EOF'\nagents never git push\nEOF", None),
    ("while read a; do while read b; do echo $b; done < f; eval \"$a\"; done <<'EOF'\ngit push\nEOF", "push"),
    ("{ echo start; bash; } <<'EOF'\ngit push\nEOF", "push"),
    ("echo 'git status' | env -i bash", None), ("echo 'git push' | sudo -u deploy bash", "push"),
    ("echo 'git push' | timeout -s KILL 60 sh", "push"),
    ("gh pr merge 3 -s --help", None), ("gh pr create -f -h", None),
    ("deno eval \"new Deno.Command('git',{args:['push']}).outputSync()\"", "push"),
    ("tea comments 5", None), ("man git push", None), ("ls /usr/libexec/git-core/git-push", None),
    ("find . -maxdepth 0 -exec /usr/libexec/git-core/git-push origin \\;", "push"),
    ("type git; git push", "push"),
]


@pytest.mark.parametrize("command,kind", REVIEW_REGRESSIONS)
def test_review_regressions(command, kind):
    found = G.remote_write_in(command)
    assert (found[0] if found else None) == kind, found


# T15 F1 (audit 73eec41..main): option values git hands to a shell or a transport, ext:: URLs and
# configuration from the environment run commands; each is scanned (ported from codex_guard.py).
GIT_COMMAND_VALUES = [
    "git fetch --upload-pack='git push origin main;git-upload-pack' .",
    "git pull --upload-pack='git push origin main;git-upload-pack' .",
    "git fetch --upload-p 'git push origin main' .",                   # an abbreviated long option
    "git ls-remote -u 'git push origin main; git-upload-pack' .",
    "git ls-remote --exec='git push' o",
    "git clone -u 'git push origin main; git-upload-pack' . /tmp/y",
    "git clone -u'git push' r d",
    "git fetch-pack --exec='git push' r",
    "git archive --remote=. --exec='git push origin main; git-upload-archive' HEAD",
    "git filter-branch --msg-filter 'git push origin main; cat' -- HEAD",
    "git filter-branch --tree-filter 'git push origin main' HEAD",
    "git filter-branch --msg-filter='git push' HEAD",
    "git difftool -x 'git push origin main' HEAD~1",
    "git difftool --extcmd='git push origin main' -y HEAD~1",
    "git difftool -x 'gh pr create --fill' HEAD~1",
    "git -c protocol.ext.allow=always fetch 'ext::sh -c git% push% origin% main'",
    "git -c protocol.allow=always clone 'ext::sh -c x' d",
    "GIT_ALLOW_PROTOCOL=ext git ls-remote 'ext::sh -c git% push'",
    "GIT_ALLOW_PROTOCOL=file:ext git fetch o",
    "git fetch 'ext::sh -c git% push'", "git remote add o 'ext::sh -c x'",
    "git config remote.o.url 'ext::sh -c x'", "git config protocol.ext.allow always",
    "git archive --remote=ext::sh% -c% x HEAD",
    "GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=alias.p GIT_CONFIG_VALUE_0='!git push origin main' git p",
    "GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=alias.p GIT_CONFIG_VALUE_0='!sh' git p -c 'git push'",
    "GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=core.sshCommand git fetch o",   # value set elsewhere
    "GIT_CONFIG_PARAMETERS=\"'alias.p'='!git push origin main'\" git p",
    "GIT_CONFIG_PARAMETERS=\"'protocol.ext.allow'='always'\" git fetch 'ext::sh -c x'",
    "git status; GIT_CONFIG_PARAMETERS=\"'alias.p'='!git push'\" git p",
    "git -c remote.origin.uploadpack='git push origin main;git-upload-pack' fetch origin",
    "git -c core.gitProxy='git push' fetch git://h/r",
    "git -c core.alternateRefsCommand='git push' fetch o",
    "git -c trailer.x.cmd='git push origin main' commit --trailer x=y -m m",
    "git -c trailer.x.command='git push' interpret-trailers",
    "git -c alias.P='!sh' p -c 'git push'",                            # alias names fold case
    "GIT_SSH_COMMAND='git push' git fetch",
]


@pytest.mark.parametrize("command", GIT_COMMAND_VALUES)
def test_git_command_values_are_scanned(command):
    assert (G.remote_write_in(command) or (None,))[0] in ("push", "forge", "opaque"), command


@pytest.mark.parametrize("command", [
    "git fetch origin", "git ls-remote origin", "git difftool HEAD~1", "git filter-branch --help",
    "git clone https://github.com/a/b", "git fetch --upload-pack=git-upload-pack origin",
    "git difftool -x 'diff -u' HEAD", "git filter-branch --msg-filter cat HEAD",
    "git -c protocol.ext.allow=never fetch o", "GIT_ALLOW_PROTOCOL=https:ssh git fetch o",
    "GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=user.name GIT_CONFIG_VALUE_0=x git commit -m m",
    "git -c trailer.x.key=Signed git commit -m m"])
def test_git_command_values_without_push_pass(command):
    assert G.remote_write_in(command) is None, command


def test_env_config_is_read_once():
    """Many GIT_CONFIG_KEY_<n> words: the environment is read once, not once per word."""
    cmd = " ".join("GIT_CONFIG_KEY_%d=user.k%d GIT_CONFIG_VALUE_%d=v" % (n, n, n)
                   for n in range(3000)) + " git status"
    start = time.monotonic()
    assert G.remote_write_in(cmd) is None
    assert time.monotonic() - start < 2.0


def test_deep_nesting_is_refused_not_ignored():
    def nest(levels):
        cmd = "git push"
        for _ in range(levels):
            cmd = "bash -c %s" % json.dumps(cmd)
        return cmd
    assert G.remote_write_in(nest(3))[0] == "push"
    assert G.remote_write_in(nest(G.MAX_NEST + 2)) == ("opaque", "a command nested too deeply to check")


@pytest.mark.parametrize("command", ["(git) " * 10000, "git | " * 8000, "echo " + "gh " * 100000,
                                     "cat > f <<'EOF'\n" + "git push $(x)\n" * 30000 + "EOF\ngit status",
                                     "git log " + "<<A " * 12000 + "\n" + "A\n" * 12000 + "git push",
                                     "echo " + "gh " * 1000000])
def test_large_inputs_stay_fast(command):
    start = time.monotonic()
    G.remote_write_in(command)
    assert time.monotonic() - start < 2.0


def test_reason_is_bounded():
    kind, what = G.remote_write_in("echo `" + "\\`" * 20000 + "git push")
    assert kind == "opaque" and len(what) <= 200


def test_parser_error_fails_closed(monkeypatch, capsys):
    def broken(command):
        raise IndexError("boom")
    monkeypatch.setattr(G, "remote_write_in", broken)
    ev = json.dumps({"tool_name": "Bash", "tool_input": {"command": "gh pr merge 1"}})
    with pytest.raises(SystemExit):
        G.no_push_main(ev)
    out = json.loads(capsys.readouterr().out)["hookSpecificOutput"]
    assert out["permissionDecision"] == "deny" and "could not check" in out["permissionDecisionReason"]
    assert G.no_push_main(json.dumps({"tool_name": "Bash", "tool_input": {"command": "npm test"}})) == 0


def run_hook(command, tool="Bash", agent_type=None, **env):
    ev = {"session_id": "t", "hook_event_name": "PreToolUse", "tool_name": tool,
          "tool_input": {"command": command}}
    if agent_type is not None:
        ev.update(agent_id="a1", agent_type=agent_type)
    return subprocess.run([sys.executable, str(GUARD), "no-push"], input=json.dumps(ev),
                          capture_output=True, text=True, timeout=30, env=dict(os.environ, **env))


def decision(p):
    assert p.returncode == 0, p.stderr
    return json.loads(p.stdout)["hookSpecificOutput"] if p.stdout else None


def test_hook_denies_push_even_with_policy_off():
    for policy in ("on", "off"):
        out = decision(run_hook("git -C . push origin main", STACK_POLICY=policy))
        assert out["permissionDecision"] == "deny" and "never push" in out["permissionDecisionReason"]


@pytest.mark.parametrize("command", ["bash -c 'git push origin main'", 'sh -c "git push"', "eval 'git push'",
                                     "bash -c \"$(echo 'git push')\"",
                                     "# it's the user's call\ngit -C repo push origin main"])
def test_hook_denies_nested_push(command):
    out = decision(run_hook(command, STACK_POLICY="off"))
    assert out["permissionDecision"] == "deny" and "never push" in out["permissionDecisionReason"]


@pytest.mark.parametrize("tool", ["Bash", "Monitor", "PowerShell"])
def test_hook_denies_forge_write_in_every_shell_tool(tool):
    out = decision(run_hook('$(echo "bash ~/github/$(date +%F).sh"); bash -c \'gh pr merge 1 --squash\'',
                            tool=tool))
    assert out["permissionDecision"] == "deny"
    assert "never write to a forge" in out["permissionDecisionReason"]
    assert "gh pr merge" in out["permissionDecisionReason"]


def test_hook_denies_opaque_subcommand():
    out = decision(run_hook('git "$SUB" origin'))
    assert out["permissionDecision"] == "deny" and "cannot be checked" in out["permissionDecisionReason"]


@pytest.mark.parametrize("command", ["git merge --ff-only feature", "gh pr view 3", "npm test", "ls -la"])
def test_hook_allows_other_commands(command):
    assert decision(run_hook(command)) is None


def test_hook_ignores_monitor_websocket():
    ev = {"session_id": "t", "hook_event_name": "PreToolUse", "tool_name": "Monitor",
          "tool_input": {"ws": {"url": "wss://example.com/feed"}}}
    p = subprocess.run([sys.executable, str(GUARD), "no-push"], input=json.dumps(ev),
                       capture_output=True, text=True, timeout=30)
    assert p.returncode == 0 and p.stdout == ""


def test_settings_wire_no_push():
    s = json.loads((ROOT / "dot-claude" / "settings.json").read_text())
    deny = s["permissions"]["deny"]
    assert {"Bash(git push *)", "Bash(gh pr create *)", "Bash(gh pr merge *)", "Bash(gh release create *)",
            "Bash(tea pulls merge *)", "Bash(fj pr merge *)"} <= set(deny)
    groups = [g for g in s["hooks"]["PreToolUse"] if "no-push" in json.dumps(g)]
    assert len(groups) == 1
    g = groups[0]
    # no `if`: Claude Code's `if: "Bash(git *)"` skips `bash -c 'git push'`, `eval` and /usr/bin/git
    assert set(g["matcher"].split("|")) == {"Bash", "Monitor", "PowerShell"}
    assert all("if" not in h for h in g["hooks"])
    assert any(h["command"].endswith("--fail-closed agent_guard no-push") for h in g["hooks"])
    assert s["worktree"]["baseRef"] == "head"


def test_forge_deny_rules_are_all_caught_by_the_hook():
    """Every Bash deny rule the stack ships for a push or a forge write is also a hook denial, so
    the hook is never weaker than the permission rule it backs up."""
    s = json.loads((ROOT / "dot-claude" / "settings.json").read_text())
    rules = [r[5:-3] for r in s["permissions"]["deny"] if re.match(r"Bash\((git|gh|tea|fj) .* \*\)\Z", r)]
    assert len(rules) >= 20
    for cmd in rules:
        assert G.remote_write_in(cmd + " x"), cmd
        assert G.remote_write_in("bash -c '%s x'" % cmd), cmd


# ---------------------------------------------------------------- secrets: --reveal on mcp-headers /
# with-stack-env, with-stack-env running env/printenv, and bash -x / sh -x / zsh -x on install.sh
# or doctor.sh. The default forms are redacted (C2): an agent may check a key's presence and
# length, never print it.
SECRETS_LEAKS = [
    "mcp-headers exa --reveal", "mcp-headers jina --reveal", "/opt/config/bin/mcp-headers wandb --reveal",
    '"mcp-headers" huggingface --reveal', "mcp-headers --reveal=1 exa",
    "with-stack-env --print-env --reveal", "with-stack-env --print-env --reveal sh",
    "with-stack-env --print-env sh --reveal", "STACK_EXPORT=all with-stack-env --print-env --reveal",
    "with-stack-env env", "with-stack-env printenv HF_TOKEN", "with-stack-env -- env",
    "with-stack-env --only EXA_API_KEY printenv", "with-stack-env FOO=1 env",
    "bash -x install.sh", "bash -x ./install.sh", "sh -x doctor.sh", "zsh -x /repo/doctor.sh",
    "bash -ex install.sh", "bash -xv doctor.sh",
    # the same nesting the no-push checks already cover
    "bash -c 'mcp-headers exa --reveal'", "eval \"with-stack-env --print-env --reveal\"",
    "bash -c 'bash -x install.sh'",
]
SECRETS_SAFE = [
    "mcp-headers exa", "mcp-headers jina", '"mcp-headers" huggingface',
    "with-stack-env --print-env", "with-stack-env --print-env sh",
    "STACK_EXPORT=all with-stack-env --print-env sh",
    "with-stack-env --only EXA_API_KEY -- python3 foo.py",
    "with-stack-env python3 train.py", "grep -- --reveal notes.md",
    "bash -x other-script.sh",   # bare mcp-headers and install.sh: see tests/test_guard_round2.py
]


@pytest.mark.parametrize("command", SECRETS_LEAKS)
def test_secrets_leak_detected(command):
    assert G.secrets_leak_in(command)[0] == "secrets", command


@pytest.mark.parametrize("command", SECRETS_SAFE)
def test_secrets_leak_not_flagged(command):
    assert G.secrets_leak_in(command) is None, command


@pytest.mark.parametrize("command", SECRETS_LEAKS)
def test_hook_denies_secrets_leak(command):
    out = decision(run_hook(command, STACK_POLICY="off"))
    assert out is not None and out["permissionDecision"] == "deny", command
    reason = out["permissionDecisionReason"]
    assert "real API key" in reason, command
    assert "`mcp-headers <server>`" in reason        # points at the redacted form instead


@pytest.mark.parametrize("command", SECRETS_SAFE)
def test_hook_allows_secrets_safe(command):
    assert decision(run_hook(command)) is None, command


def test_secrets_reason_never_suggests_reveal():
    tail = G.SECRETS_REASON.split("%s", 1)[1]
    assert "--reveal" not in tail


def test_settings_wire_secrets_deny_rules():
    s = json.loads((ROOT / "dot-claude" / "settings.json").read_text())
    deny = set(s["permissions"]["deny"])
    assert {"Bash(mcp-headers *--reveal*)", "Bash(with-stack-env *--reveal*)",
            "Bash(bash -x install.sh)", "Bash(sh -x doctor.sh)"} <= deny
    # the redacted default forms stay usable: no deny rule may match them
    for old in ("Bash(mcp-headers exa)", "Bash(mcp-headers exa|jina|huggingface|wandb)",
                "Bash(with-stack-env --print-env)", "Bash(with-stack-env --print-env sh)",
                "Bash(mcp-headers *)", "Bash(with-stack-env --print-env *)"):
        assert old not in deny, old


def test_rules_file_claims_match_enforcement():
    """The Git section says gh/tea/fj writes are hook-enforced: its examples must be denied."""
    text = (ROOT / "dot-claude" / "rules" / "claude-agent-stack.md").read_text()
    bullet = next(l for l in text.splitlines() if l.startswith("- **Never push.**"))
    assert "Hook-enforced for git, gh, tea and fj" in bullet
    for verb in ("create", "merge", "review", "comment", "close"):
        assert G.forge_write_in("gh pr %s 1" % verb), verb
    for cmd in ("git push", "git send-pack r", "git lfs push o", "git subtree push --prefix d r m",
                "tea pulls merge 1", "fj pr merge 1", "gh release create v1", "gh repo fork",
                "gh api -X POST repos/o/r/issues"):
        assert G.remote_write_in(cmd), cmd


# ---------------------------------------------------------------- index blinding (CWE-345):
# install.sh reviews the checkout with `git status`/`git diff`; assume-unchanged, skip-worktree,
# direct index writes and sparse checkout hide an edited file from that review.
INDEX_BLINDS = [
    "git update-index --assume-unchanged f", "git update-index --skip-worktree dot-claude/x.py",
    "git update-index --cacheinfo 100644,abc,f", "git update-index --cacheinfo=100644,abc,f",
    "git update-index --index-info", "git update-index --assume-u f", "git update-index --sk f",
    "git update-index --add --assume-unchanged f", "git -C /repo update-index --skip-worktree f",
    "git -c a=b update-index --assume-unchanged f", "/usr/bin/git update-index --index-info",
    "git update-index $FLAG f", "git update-index \"$(echo --skip-worktree)\" f",
    "git sparse-checkout set dot-claude", "git sparse-checkout init --cone", "git sparse-checkout",
    "git sparse-checkout add x", "git sparse-checkout reapply", "git -C /r sparse-checkout set d",
    "git config core.sparseCheckout true", "git config --bool core.sparsecheckout true",
    "git config set core.sparseCheckoutCone true", "git config --worktree core.sparseCheckout true",
    "git config --type bool core.sparseCheckout true", "git config core.ignoreStat true",
    "git config --add core.sparseCheckout true", "git -C /r config core.sparseCheckout true",
    "git config $KEY true",
    "git -c core.sparseCheckout=true read-tree -mu HEAD", "git -c core.sparseCheckoutCone=true checkout",
    "git --config-env=core.sparseCheckout=X checkout", "git -c \"$K=true\" checkout",
    "GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=core.sparseCheckout GIT_CONFIG_VALUE_0=true git read-tree -mu HEAD",
    "GIT_CONFIG_PARAMETERS=\"'core.sparsecheckout=true'\" git checkout",
    "git config alias.ui update-index", "git config alias.h '!git update-index --skip-worktree'",
    "git -c alias.x='update-index --assume-unchanged' x f", "git -c alias.x=update-index x --skip-worktree f",
]
NESTED_INDEX_BLINDS = [
    "bash -c 'git update-index --assume-unchanged f'", 'sh -c "git sparse-checkout set d"',
    "eval 'git config core.sparseCheckout true'", "echo $(git update-index --skip-worktree f)",
    "bash -c \"$(echo 'git update-index --assume-unchanged f')\"",
    "bash -c \"bash -c 'git -C r update-index --index-info'\"", "cd x && git update-index --skip-worktree f",
    "zsh -c 'git -c core.sparseCheckout=true checkout'", "echo `git sparse-checkout init`",
]
INDEX_SAFE = [
    "git update-index --no-assume-unchanged f", "git update-index --no-skip-worktree f",
    "git update-index --refresh", "git update-index --add f", "git update-index --chmod=+x f",
    "git update-index --really-refresh", "git update-index -- --assume-unchanged",
    "git sparse-checkout list", "git -C r sparse-checkout list", "git sparse-checkout --help",
    "git config core.sparseCheckout", "git config --get core.sparseCheckout",
    "git config --unset core.sparseCheckout", "git config get core.sparseCheckout",
    "git config --get core.sparseCheckout true", "git config --unset-all core.ignoreStat true",
    "git config unset core.sparseCheckout",
    "git config --list", "git config user.name x", "git config alias.st status",
    "git -c core.editor=true commit", "git -c user.name=x commit -m m",
    "git commit -m 'git update-index --assume-unchanged'", "grep -r skip-worktree docs",
    "git ls-files -v", "git status", "bash -c 'git sparse-checkout list'",
    "GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=user.name GIT_CONFIG_VALUE_0=x git commit",
]


@pytest.mark.parametrize("command", INDEX_BLINDS + NESTED_INDEX_BLINDS)
def test_index_blinding_detected(command):
    found = G.remote_write_in(command)
    assert found and found[0] == "index", (command, found)


@pytest.mark.parametrize("command", INDEX_SAFE)
def test_index_blinding_not_flagged(command):
    assert G.remote_write_in(command) is None, command


@pytest.mark.parametrize("command", ["git update-index --assume-unchanged f",
                                     "bash -c 'git -C r update-index --skip-worktree f'",
                                     "eval 'git sparse-checkout set d'",
                                     "git -c core.sparseCheckout=true checkout"])
def test_hook_denies_index_blinding_even_with_policy_off(command):
    for policy in ("on", "off"):
        out = decision(run_hook(command, STACK_POLICY=policy))
        assert out["permissionDecision"] == "deny", command
        assert "hides working-tree edits" in out["permissionDecisionReason"]


@pytest.mark.parametrize("command", ["git update-index --no-skip-worktree f", "git sparse-checkout list"])
def test_hook_allows_index_clearing_and_listing(command):
    assert decision(run_hook(command)) is None



@pytest.mark.parametrize("command", [
    "curl -s https://raw.githubusercontent.com/a/b/main/README.md",
    "timeout 9 wget -qO- https://github.com/a/b",
    "gh issue view 1 -R a/b",
    "python3 -c 'import urllib.request as u; u.urlopen(1)'",
])
def test_orchestrator_bash_reads_no_web(command):
    """T1: the orchestrator may spawn browser-operator, so its own Bash fetches no web content."""
    out = decision(run_hook(command, agent_type="orchestrator", STACK_POLICY="on"))
    assert out is not None and out["permissionDecision"] == "deny", command
    assert "browser-operator" in out["permissionDecisionReason"]


@pytest.mark.parametrize("command", [
    "bash -c 'curl -s https://raw.githubusercontent.com/a/b/main/README.md'",
    'sh -ec "wget -qO- https://github.com/a/b"',
    "bash -o pipefail -c 'curl -s https://x'",
    "eval 'curl -s https://x'",
    "find . -maxdepth 0 -exec curl -s https://x \\;",
])
def test_orchestrator_bash_reads_no_web_through_wrappers(command):
    """bash -c, eval and find -exec are unwrapped: the wrapped command decides."""
    out = decision(run_hook(command, agent_type="orchestrator", STACK_POLICY="on"))
    assert out is not None and out["permissionDecision"] == "deny", command
    assert "browser-operator" in out["permissionDecisionReason"]


@pytest.mark.parametrize("command", ["git -C . merge --ff-only orch-bash", "git status",
                                     "git fetch origin", "uv run pytest -q", "rg -n TODO src"])
def test_orchestrator_integration_commands_pass(command):
    assert decision(run_hook(command, agent_type="orchestrator", STACK_POLICY="on")) is None


@pytest.mark.parametrize("command", ["sh -c 'git status'", "bash -lc 'uv run pytest -q'",
                                     "find . -name '*.py' -exec rg -n TODO {} +", "bash x.sh"])
def test_orchestrator_wrapped_checks_pass(command):
    assert decision(run_hook(command, agent_type="orchestrator", STACK_POLICY="on")) is None


@pytest.mark.parametrize("command", ["echo 'curl -s https://x' | sh",
                                     "echo 'curl -s https://x' | bash -s",
                                     "sh <<< 'curl -s https://x'",
                                     "find . -exec ls {} + -exec curl -s https://x {} +"])
def test_web_check_sees_stdin_shells_and_later_execs(command):
    """A shell reading commands from stdin is refused; a second -exec after `{} +` still decides."""
    assert G.blackcat_web_command(command) is True


@pytest.mark.parametrize("command", ["find . -name '*.sh' -exec bash {} \\;", "ls *.sh | xargs bash",
                                     "bash -o pipefail x.sh", "IFS=$'\\n' read -r x <<< \"$y\""])
def test_web_check_leaves_script_runs_alone(command):
    assert G.blackcat_web_command(command) is False


def test_web_check_linear():
    """The -c option regex has no quadratic backtracking; $'curl' is unquoted."""
    start = time.perf_counter()
    G.blackcat_web_command("bash -" + "c" * 19990 + "1")
    assert time.perf_counter() - start < 0.1
    assert G.blackcat_web_command("$'curl' -s https://x") is True


# T15 F3 (audit 73eec41..main): a shell after `-c` that reads its commands from stdin is refused
# like any other; only the command find -exec runs (whose `{}` operand is split off) is exempt.
@pytest.mark.parametrize("command", ["echo 'curl -s https://x' | bash -c sh",
                                     "echo curl u | bash -c 'exec sh'", "echo 'curl u' | sh -c 'sh -s'",
                                     "echo 'curl u' | find . -maxdepth 0 -exec sh -c bash \\;"])
def test_web_check_sees_stdin_shells_inside_c(command):
    assert G.blackcat_web_command(command) is True


@pytest.mark.parametrize("command", ["bash -c 'sh x.sh'", "sh -c 'git status'",
                                     "find . -name '*.sh' -exec sudo bash {} \\;",
                                     "find . -exec sh -c 'bash \"$0\"' {} \\;"])
def test_web_check_script_runs_inside_c_pass(command):
    assert G.blackcat_web_command(command) is False


# T15 item 7: in-policy forms the T1 check missed (the reviewer's 65-string probe): -c spelled
# --command, csh/tcsh, options after `--` or a script operand are not the shell's, `xargs sh -c`
# with no command string runs stdin, a script read from /dev/stdin, `source /dev/stdin`, a line
# continuation inside a word, /dev/tcp sockets, inline code that runs an HTTP client, PHP's URL
# reads, and the arch/taskpolicy wrappers.
WEB_CHECK_CLOSED = [
    "fish --command 'curl https://x'", "fish --command='curl https://x'",
    "csh -c 'curl https://x'", "tcsh -c 'curl https://x'", "/bin/tcsh -fc 'curl https://x'",
    "echo 'curl https://x' | bash -s -- -c", "echo 'curl https://x' | sh -s -- -lc",
    "bash -s -- -c <<< 'curl https://x'", "sh -s -- -xc < cmds.txt",
    "echo 'curl https://x' | xargs -0 sh -c", "echo 'curl https://x' | xargs -0 bash -c",
    "echo 'curl https://x' | bash /dev/stdin", "echo 'curl https://x' | sh -- /dev/fd/0",
    "echo 'curl https://x' | csh", "echo 'curl https://x' | tcsh",
    "echo 'curl https://x' | source /dev/stdin", "echo 'curl https://x' | . /dev/stdin",
    "cu\\\nrl https://x", "w\\\nget -qO- https://x", "echo \\\\\ncurl https://x",
    "exec 3<>/dev/tcp/example.com/80", "cat < /dev/tcp/example.com/80",
    "bash -c 'cat </dev/tcp/example.com/80'", "zmodload zsh/net/tcp; ztcp example.com 80",
    "python3 -c \"import subprocess; subprocess.run(['curl','https://x'])\"",
    "perl -e 'exec \"curl\", \"https://x\"'", "ruby -e 'system(\"wget\", \"-q\", \"u\")'",
    "php -r 'echo file_get_contents(\"https://x\");'", "php -r '$c = curl_init(\"u\");'",
    "arch -arm64 curl https://x", "arch curl https://x", "taskpolicy -b curl https://x",
    "doas curl https://x", "busybox wget https://x",
    "python3 -c \"import socket; socket.create_connection(('x', 80))\"",
]


@pytest.mark.parametrize("command", WEB_CHECK_CLOSED)
def test_web_check_closed_probe_gaps(command):
    assert G.blackcat_web_command(command) is True, command


@pytest.mark.parametrize("command", [
    "git status", "bash x.sh", "rg -n curl src", "command -v curl", "bash x.sh -c y",
    "bash -o pipefail -c 'git log'", "python3 -c 'print(1)'", "python3 tools/use_curl.py",
    "php -r 'echo file_get_contents(\"a.txt\");'", "rg -n wget src && perl -e 'print 1'",
    "arch -arm64 uv run pytest -q", "echo a \\\n  b", "ls /dev/fd/0", "xargs sh -c 'echo \"$0\"' < f"])
def test_web_check_closed_probe_controls(command):
    assert G.blackcat_web_command(command) is False, command


def test_web_check_inline_scan_reads_to_the_end():
    """Inline code is not delimited after unquoting: a client named anywhere after it is refused
    (the documented false positive, one dispatch)."""
    assert G.blackcat_web_command("perl -e 'print 1' && rg -n wget src/README") is True


# Design limit (documented at BLACKCAT_WEB_CLIENTS): runners not unwrapped stay unseen.
@pytest.mark.parametrize("command", ["script -q /dev/null curl https://x", "uv run curl https://x",
                                     "bash <(echo curl https://x)", "ssh h curl https://x"])
def test_web_check_documented_limits(command):
    assert G.blackcat_web_command(command) is False


@pytest.mark.parametrize("unit", ["bash ", "bash -o x ", "find . -exec ", "xargs ", "sh -c ",
                                  "python3 -c x; ", "cu\\\n", "-", "--command=", "a=b ", "/dev/stdin ",
                                  "bash -s -- ", "arch -x "])
def test_web_check_stays_linear(unit):
    """Inputs up to the scan window, built from one repeated unit, are checked in linear time
    (a quadratic word loop over ~4000 words takes seconds)."""
    cmd = (unit * (G.BLACKCAT_WEB_SCAN_MAX // len(unit)))[:G.BLACKCAT_WEB_SCAN_MAX]
    start = time.perf_counter()
    G.blackcat_web_command(cmd)
    G.BLACKCAT_SHELL_C_RE.match("-" + "a" * G.BLACKCAT_WEB_SCAN_MAX)
    assert time.perf_counter() - start < 0.25, unit


def test_orchestrator_web_check_off_with_policy_off():
    out = run_hook("curl -s https://example.com", agent_type="orchestrator", STACK_POLICY="off")
    assert decision(out) is None


def test_builder_web_command_unchanged():
    out = run_hook("curl -s https://pypi.org/simple/x/", agent_type="coder", STACK_POLICY="on")
    assert decision(out) is None


def test_orchestrator_web_check_parser_error_fails_closed(monkeypatch, capsys):
    def broken(command):
        raise ZeroDivisionError("boom")
    monkeypatch.setenv("STACK_POLICY", "on")
    monkeypatch.setattr(G, "blackcat_web_command", broken)
    ev = json.dumps({"tool_name": "Bash", "agent_type": "orchestrator",
                     "tool_input": {"command": "git status"}})
    with pytest.raises(SystemExit):
        G.no_push_main(ev)
    out = json.loads(capsys.readouterr().out)["hookSpecificOutput"]
    assert out["permissionDecision"] == "deny"
    assert "orchestrator reads no web content" in out["permissionDecisionReason"]
