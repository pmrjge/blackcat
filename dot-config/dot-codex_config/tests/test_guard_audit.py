"""Proofs for the security-auditor findings on codex_guard (2026-10, audited tip b820171), each run
as a Bash event through the guard's public entry (codex_guard.run):

1. read-only allowlist bypasses (CWE-184/78): a program run by path, trap, rg --pre, sort
   --compress-program, attached/clustered output values, xxd/uniq output operands, mktemp outside
   scratch, git grep -O<cmd>, hash -p / read / printf -v on exec variables, bare env/set/export;
2. credential containment (CWE-552): a recursive reader (grep -r, rg, tar, find -exec, ...) handed
   a directory that holds a credential, and globs that match one;
3. codex launched with the spelled-out --yolo equivalents (CWE-693);
4. git options that run a command (upload-pack, filter-branch filters, difftool -x, ext::) are
   scanned for pushes like rebase -x already is.
"""
from __future__ import annotations

import os

import pytest

from _guard_helpers import REPO, Guard, Stack, bash, decision, load_by_path, reason

G = load_by_path("codex_guard_audit", REPO / "codex_config" / "hooks" / "codex_guard.py")


@pytest.fixture
def stack(tmp_path):
    return Stack(tmp_path)


@pytest.fixture
def guard(stack, monkeypatch):
    return Guard(stack, monkeypatch)


def fmt(command, stack):
    return command.format(proj=stack.project, tmp=stack.root / "tmp", ch=stack.codex_home,
                          home=stack.home)


# ---------------------------------------------------------------- 1. read-only allowlist
RO_BYPASSES = [
    # a program by path: a scratch copy of /bin/sh named cat, a relative ./cat
    "$TMPDIR/x/cat -c 'touch {proj}/pwned'", "{tmp}/x/cat -c 'touch {proj}/pwned'",
    "/tmp/x/cat y", "./cat y", "sub/cat y", "{tmp}/x/time cat a", "~/bin/cat a",
    "find . -name x -exec {tmp}/x/cat {{}} +", "xargs ./cat < list", "uvx ./cat x",
    "uv run --no-project ./cat x",
    # plain commands that run code or write
    "trap 'touch {proj}/pwned' EXIT", "rg --pre=sh foo dir", "rg --pre ./evil.sh foo .",
    "sort --compress-program=./evil.sh in", "sort --compress=sh in",
    "bat --pager='sh -c x' f", "env -S'sh -c \"touch {proj}/p\"'", "env --split-string='touch x'",
    # output operands and attached / clustered / abbreviated output options
    "xxd -r in {proj}/f", "xxd in {proj}/f", "uniq in {proj}/f", "uniq -c - {proj}/f",
    "sort -o{proj}/f in", "sort -ro{proj}/f in", "sort -ro {proj}/f in", "sort --outp={proj}/f in",
    "sort --out {proj}/f in", "tree -o{proj}/f", "ruff check -o{proj}/f",
    "cloc --report-file={proj}/r .", "cloc --sql={proj}/s .", "time -o {proj}/t ls",
    "time --output={proj}/t ls", "mktemp {proj}/x.XXXX", "mktemp -p {proj} x.XXXX",
    "mktemp --tmpdir={proj} x.XXXX", "mktemp x.XXXX", "mktemp -t ../x",
    # git: -O<cmd> attached or abbreviated, ls-remote --upload-pack, --ext-diff abbreviated
    "git grep '-Osh -c \"touch {proj}/p\"' foo", "git grep --open-files sh foo",
    "git grep --op=sh foo", "git ls-remote --upload-pack='touch {proj}/p' .",
    "git ls-remote -u 'touch {proj}/p' .", "git ls-remote --exec='touch p' .",
    "git diff --ext HEAD", "git log --outp={proj}/o",
    # exec-relevant variables set without an assignment word; printing the environment
    "hash -p {tmp}/evil cat; cat x", "read PATH <<< {tmp}/x; ls", "read -a PATH <<< x",
    "read 'PATH?p' <<< x", "printf -v PATH %s {tmp}/x; ls", "printf -vPATH %s x",
    "printf -v 'PATH[0]' %s x", "declare -n r=PATH", "env", "env -0", "env -u X", "set",
    "export", "export -p", "declare -p", "typeset",
]


@pytest.mark.parametrize("agent", ["code-reviewer", None])
@pytest.mark.parametrize("command", RO_BYPASSES)
def test_readonly_bypasses_refused(guard, stack, command, agent):
    cmd = fmt(command, stack)
    out = guard.pre(bash(cmd, agent_type=agent))
    assert decision(out) == "deny" and "read-only" in reason(out), (cmd, out)


RO_STILL_PASS = [
    "set -e", "set -euo pipefail", "set +x", "trap - EXIT", "trap 'echo done' EXIT", "trap -l",
    "rg -n foo src", "rg --pre-glob '*.gz' foo", "sort -o $TMPDIR/s in", "sort -o{tmp}/s in",
    "sort -u f", "sort -k2 -t, f", "sort -rn f", "mktemp", "mktemp -d", "mktemp -t x",
    "mktemp $TMPDIR/x.XXXX", "mktemp -p $TMPDIR x.XXXX", "mktemp --tmpdir x.XXXX",
    "uniq -c in", "uniq in $TMPDIR/out", "uniq -f 1 in", "xxd f", "xxd -r in $TMPDIR/o",
    "xxd -l 64 f", "hash", "hash -r", "read x <<< y", "printf -v line %s x", "printf %s x",
    "env FOO=1 ls", "export X=1", "declare -a arr", "/usr/bin/grep x f", "/bin/ls -la",
    "git grep -n foo", "git grep --or -e a -e b", "git log --output-indicator-new=+ -1",
    ".venv/bin/pytest -q", "time ls", "git ls-remote --heads .", "tree -L 2", "ls -R",
]


@pytest.mark.parametrize("command", RO_STILL_PASS)
def test_readonly_ordinary_reads_still_pass(guard, stack, command):
    os.makedirs(stack.project / ".venv" / "bin", exist_ok=True)
    cmd = fmt(command, stack)
    assert guard.pre(bash(cmd, agent_type="code-reviewer")) is None, cmd


def test_readonly_scratch_venv_is_not_trusted(guard, stack):
    """A .venv/bin under scratch is whatever was written there: refused like any path program."""
    cmd = fmt("{tmp}/.venv/bin/pytest -q", stack)
    out = guard.pre(bash(cmd, agent_type="code-reviewer"))
    assert decision(out) == "deny" and "read-only" in reason(out)


# ---------------------------------------------------------------- 2. credential containment
CRED_DIR_READS = [
    "grep -r access_token {ch}", "grep -R x ~/.codex", "grep -rn x ~/.codex/",
    "grep --recursive x $CODEX_HOME", "grep -d recurse x {ch}", "rg -uu token {ch}",
    "rg token {home}/.codex", "ag token {ch}", "cd {ch} && grep -r x .", "cd {ch} && rg x",
    "cd {home} && rg x .codex", "tar czf $TMPDIR/c.tgz {ch}", "zip -r $TMPDIR/c.zip {ch}",
    "find {ch} -type f -exec cat {{}} +", "find {ch} -type f | xargs cat",
    "rsync -a {ch}/ $TMPDIR/c", "git diff --no-index {ch} $TMPDIR/e",
    "diff -rN {ch} $TMPDIR/e", "grep -r x {home}/.*", "cat {ch}/*.json", "cat {ch}/a*",
    "grep -r x {ch}/stack/..", "rg x ~/.aws", "grep -r x {home}/..",
    "cp -r {ch} $TMPDIR/c", "cp {ch}/auth.json $TMPDIR/c/",
]


@pytest.mark.parametrize("scope", [None, "global"])
@pytest.mark.parametrize("command", CRED_DIR_READS)
def test_recursive_reads_of_a_credential_holder_denied(guard, stack, command, scope):
    cmd = fmt(command, stack)
    out = guard.pre(bash(cmd), scope=scope)
    assert decision(out) == "deny", (cmd, out)
    assert "credential" in reason(out) or "protected root" in reason(out), reason(out)


def test_recursive_read_through_a_symlink_denied(guard, stack):
    os.symlink(stack.codex_home, stack.project / "l")
    out = guard.pre(bash("grep -r token l"))
    assert decision(out) == "deny" and "credential" in reason(out)


CRED_DIR_PASS = [
    "ls {ch}", "ls -la ~/.codex", "ls -R {ch}", "cat {ch}/config.toml",
    "grep model {ch}/config.toml", "rg model {ch}/config.toml", "rg foo src", "grep -r foo src",
    "tree {ch}", "find {ch} -name '*.toml'", "du -sh {ch}", "grep -r foo ~", "rg foo {proj}",
    "cat {ch}/c*.toml", "grep -r x {ch}/stack",
]


@pytest.mark.parametrize("command", CRED_DIR_PASS)
def test_non_recursive_and_unrelated_reads_pass(guard, stack, command):
    os.makedirs(stack.codex_home / "stack", exist_ok=True)
    cmd = fmt(command, stack)
    assert guard.pre(bash(cmd, agent_type="python-engineer")) is None, cmd


# ---------------------------------------------------------------- 3. codex launched without its guards
CODEX_BYPASSES = [
    "codex -s danger-full-access -a never exec x", "codex --sandbox=danger-full-access exec x",
    "codex --sandbox danger-full-access exec x", "codex -sdanger-full-access exec x",
    "codex -s=danger-full-access exec x", "codex -a never exec x",
    "codex --ask-for-approval=never exec x", "codex -anever exec x",
    "codex --disable hooks exec x", "codex --enable=x exec y", "codex --disable=hooks exec x",
    "codex exec --sandbox danger-full-access x", "codex exec -s danger-full-access x",
    "codex exec --dangerously-bypass-approvals-and-sandbox x", "codex --sand danger-full-access",
    "codex --ask never exec x", "codex -s $MODE exec x", "codex --add-dir / exec x",
    "bash -c 'codex -s danger-full-access exec x'", "env A=1 codex -a never exec x",
]


@pytest.mark.parametrize("command", CODEX_BYPASSES)
def test_codex_sandbox_and_approval_bypasses_refused(command):
    assert (G.shell_rule_hit(command) or (None,))[0] == "codex", command


@pytest.mark.parametrize("command", CODEX_BYPASSES[:6])
def test_codex_bypasses_denied_by_the_hook(guard, command):
    out = guard.pre(bash(command, agent_type="python-engineer"))
    assert decision(out) == "deny" and "Codex" in reason(out), reason(out)


@pytest.mark.parametrize("command", [
    "codex -s read-only exec x", "codex --sandbox=workspace-write exec x",
    "codex -a on-request exec x", "codex --ask-for-approval untrusted exec x",
    "codex exec --full-auto x", "codex --version", "codex exec 'run -s danger-full-access'",
    "codex exec -m gpt-x 'summarize -a never'"])
def test_codex_safe_modes_pass(command):
    assert G.shell_rule_hit(command) is None, command


# ---------------------------------------------------------------- 4. git options that run a command
GIT_RUNS_PUSH = [
    "git fetch --upload-pack='sh -c \"git push\"' origin", "git fetch --upload-pack='git push' o",
    "git clone -u 'git push' repo d", "git clone -u'git push' repo d",
    "git clone --upload-pack='git push' r d", "git ls-remote --upload-pack='git push' o",
    "git pull --upload-pack 'git push'", "git fetch-pack --exec='git push' r",
    "git archive --remote=. --exec='git push' HEAD",
    "git filter-branch --tree-filter 'git push' HEAD",
    "git filter-branch --msg-filter='git push' HEAD", "git filter-branch --env-filter 'git push'",
    "git difftool -x 'git push' HEAD", "git difftool --extcmd='git push'",
    "git -c core.sshCommand='git push' fetch", "git -c remote.origin.uploadpack='git push' fetch",
    "GIT_SSH_COMMAND='git push' git fetch", "git rebase -x 'git push' main",
    "git rebase --exec='git push origin' main", "git submodule foreach 'git push'",
    "git submodule foreach --recursive 'git push origin HEAD'", "git bisect run git push",
    "git bisect run sh -c 'git push'",
]


@pytest.mark.parametrize("command", GIT_RUNS_PUSH)
def test_git_command_options_are_scanned_for_pushes(command):
    assert (G.shell_rule_hit(command) or (None,))[0] in ("push", "opaque"), command


@pytest.mark.parametrize("command", [
    "git fetch 'ext::sh -c git% push'", "git -c protocol.ext.allow=always clone 'ext::sh -c x' d",
    "git remote add o 'ext::sh -c x'", "git fetch ext::$CMD"])
def test_git_ext_transport_is_opaque(command):
    assert (G.shell_rule_hit(command) or (None,))[0] == "opaque", command


@pytest.mark.parametrize("command", [
    "git fetch origin", "git clone https://example.com/r d", "git rebase -x 'make test' main",
    "git filter-branch --msg-filter cat HEAD", "git bisect run make test",
    "git submodule foreach git status", "git -c core.sshCommand='ssh -i k' fetch",
    "git fetch --upload-pack=git-upload-pack origin", "git difftool -x 'diff -u' HEAD"])
def test_git_command_options_without_push_pass(command):
    assert G.shell_rule_hit(command) is None, command


@pytest.mark.parametrize("command", GIT_RUNS_PUSH[:4] + ["git filter-branch --tree-filter 'git push' HEAD"])
def test_git_command_option_pushes_denied_by_the_hook(guard, command):
    out = guard.pre(bash(command, agent_type="python-engineer"))
    assert decision(out) == "deny" and "never push" in reason(out), reason(out)


@pytest.mark.parametrize("ws", ["\x0b", "\x0c", "\xa0", "\x85", "\u2003", " \t\x0c"])
def test_patch_header_after_unicode_whitespace_is_seen(ws):
    """Final security review: Codex trims a patch header line with str::trim(), so a header after a
    form feed, vertical tab, NBSP, NEL or a Unicode space is a real hunk and must be checked."""
    text = "*** Begin Patch\n%s*** Add File: ../../.codex/config.toml  %s\n+x\n*** End Patch" % (ws, ws)
    assert G.PATCH_HEADER_RE.findall(text) == ["../../.codex/config.toml"]
