"""agent_guard.py's shell scan keeps a simple command's command position past a wrapper's own
arguments: `timeout 30 CMD` / `gtimeout 30 CMD` (the duration operand) and option values after a
prefix word (`nice -n 10 CMD`, `env -u X CMD`, `sudo -u u CMD`, `timeout -s KILL 30 CMD`). Before
the fix the word after such an argument was read as an argument, so a protected-path write
(`timeout 30 cp x ~/.claude/hooks/...`), a `git-push` program, or `mcp-headers --reveal` behind
the wrapper went unchecked. Also pins the negatives: a number or option value that is an
ordinary argument of a non-wrapper command must not open a new command position. Later rounds:
env reads -S's split words as its own arguments again (`env -iS -S 'CMD'`, `env -S '-i CMD'`);
zsh's noclobber redirections (`>! F`, `>&| F`, ...) read as bash and as zsh read them; a
redirection before the command word (`>/dev/null rm ...`); an output redirection is no operand of
a write command (`cp x <protected> >/dev/null`).

Run: uv run --with pytest pytest -q tests/test_guard_prefix_args.py
"""
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC_HOOK = ROOT / "dot-config" / "dot-claude" / "hooks" / "agent_guard.py"
SRC_SETTINGS = ROOT / "dot-config" / "dot-claude" / "settings.json"


@pytest.fixture
def installed(tmp_path, monkeypatch):
    """A rendered config dir and a project dir, as in tests/test_protected_paths.py."""
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


WRAPPED = [
    "timeout 30 {cmd}",
    "timeout 1.5m {cmd}",
    "gtimeout 30 {cmd}",
    "timeout -s KILL 30 {cmd}",
    "timeout --signal KILL -k 5 30 {cmd}",
    "timeout --kill-after=5 30 {cmd}",
    "gtimeout -k 5s 10s {cmd}",
    "nice -n 10 {cmd}",
    "nice --adjustment 5 {cmd}",
    "env -u X {cmd}",
    "env --unset X {cmd}",
    "sudo -u u {cmd}",
    "sudo -g wheel -u u {cmd}",
    "stdbuf -o L {cmd}",
    "exec -a name {cmd}",
    "time -o t.log {cmd}",
    "nohup timeout 30 {cmd}",
    "env -u X timeout 30 nice -n 5 {cmd}",
    "X=1 timeout 30 {cmd}",
    "true && timeout 30 {cmd}",
    "timeout $T {cmd}",                            # a duration spelled at run time
    "doas -u u {cmd}",
    "sudo -D /tmp {cmd}",
    "xargs -I % {cmd}",
    "xargs -n 1 -P 4 {cmd}",
    # clusters of short flags ending in a value-taking one; an attached value
    "sudo -Eu u {cmd}",
    "env -iu X {cmd}",
    "timeout -vs KILL 30 {cmd}",
    "xargs -0n 1 {cmd}",
    "timeout -k5 30 {cmd}",
    "sudo -c x {cmd}",
    "sudo -a t {cmd}",
    # caffeinate, and wrappers spelled by path
    "caffeinate {cmd}",
    "caffeinate -t 60 {cmd}",
    "/usr/bin/env -u X {cmd}",
    "/usr/bin/timeout 30 {cmd}",
    # unique prefixes of long options (getopt_long), long forms, a wrapper found at run time
    "timeout --sig KILL 30 {cmd}",
    "timeout --k 5 30 {cmd}",
    "env --un X {cmd}",
    "nice --adj 5 {cmd}",
    "sudo --user u {cmd}",
    "xargs --max-args 1 {cmd}",
    "$(which timeout) 30 {cmd}",
    "env -a name {cmd}",
    "env --argv0 name {cmd}",
    # wrappers that were no prefix words: chronic, flock (lock file operand), arch, taskpolicy,
    # busybox (the applet), watch
    "chronic {cmd}",
    "chronic -ev {cmd}",
    "flock /tmp/l {cmd}",
    "flock -w 5 /tmp/l {cmd}",
    "arch -arm64 {cmd}",
    "arch -arch arm64 {cmd}",
    "arch -e X=1 {cmd}",
    "taskpolicy -c utility {cmd}",
    "taskpolicy -b {cmd}",
    "busybox {cmd}",
    "watch -n 5 {cmd}",
    # value options added in round 2; signal names in every spelling
    "taskpolicy -P kill {cmd}",
    "watch -s /tmp {cmd}",
    "watch --shotsdir /tmp {cmd}",
    "doas -a passwd {cmd}",
    "timeout -s SIGTERM 30 {cmd}",
    "timeout -sTERM 30 {cmd}",
    "timeout --signal=TERM 30 {cmd}",
    # flags (no value) still pass the command word through, as before the fix
    "sudo -E {cmd}",
    "env -i {cmd}",
    "nice -10 {cmd}",
]


@pytest.mark.parametrize("form", WRAPPED)
def test_protect_write_behind_wrapper_args_denied(installed, form):
    g, cfg, proj = installed
    target = cfg / "hooks" / "agent_guard.py"
    for cmd in ("cp new.py %s" % target, "rm -f %s" % target, "chmod 777 %s" % target):
        line = form.format(cmd=cmd)
        got = g.protected_write_in(line, {"cwd": str(proj)})
        assert got and got[0] == "protect", line


@pytest.mark.parametrize("form", WRAPPED)
def test_push_program_behind_wrapper_args_denied(installed, form):
    g, _, _ = installed
    line = form.format(cmd="git-push origin main")
    assert g.git_push_in(line), line


@pytest.mark.parametrize("form", WRAPPED)
def test_secrets_reveal_behind_wrapper_args_denied(installed, form):
    g, _, proj = installed
    line = form.format(cmd="mcp-headers exa --reveal")
    got = g.secrets_leak_in(line, {"cwd": str(proj)})
    assert got and got[0] == "secrets", line


@pytest.mark.parametrize("form", WRAPPED)
def test_run_time_program_push_behind_wrapper_args_is_opaque(installed, form):
    """`$G push` behind a wrapper: the program is only known at run time."""
    g, _, _ = installed
    line = form.format(cmd="$G push origin main")
    got = g.remote_write_in(line)
    assert got and got[0] == "opaque", line


def test_run_time_program_as_an_argument_is_not_a_command(installed):
    g, _, _ = installed
    for line in ["echo $G push", "sleep 30 $G push", "grep -n $G push"]:
        assert g.remote_write_in(line) is None, line


@pytest.mark.parametrize("line", [
    "env -iS 'git push origin main'",
    "env -vS'git push origin main'",
    "env --split='git push origin main'",
    "env --split 'git push origin main'",
    "env -S 'git push origin main'",
    "env --split-string='git push origin main'",
])
def test_env_split_string_in_any_spelling_is_scanned(installed, line):
    g, _, _ = installed
    assert g.git_push_in(line), line


def test_env_split_string_lookalikes_pass(installed):
    g, _, _ = installed
    for line in ["env -u S 'git push origin main'", "env -iu X echo 'git push'"]:
        assert not g.git_push_in(line), line


@pytest.mark.parametrize("line", [
    "sudo -E timeout 30 git-push x",
    "sudo -E nice -n 5 git-push x",
    "sudo -E -u u git-push x",
    "sudo -E arch -arch x86_64 git-push x",
])
def test_a_flag_listed_as_taking_a_value_fails_closed(installed, monkeypatch, line):
    """A wrapper or an option in the slot of a wrongly listed value keeps its own meaning."""
    g, _, _ = installed
    monkeypatch.setitem(g.WRAPPER_VALUE_OPTS, "sudo", g.WRAPPER_VALUE_OPTS["sudo"] | {"-E"})
    assert g.git_push_in(line), line


def test_a_value_slot_holding_the_command_is_still_checked(installed):
    """`timeout CMD` (no duration): the word read as the duration is checked as a command too."""
    g, _, _ = installed
    assert g.git_push_in("timeout git-push origin main")


@pytest.mark.parametrize("form", ["which git > {t}", "timeout 30 which git > {t}",
                                  "sudo -u u man git > {t}", "man git >> {t}"])
def test_doc_command_output_redirected_into_protected_path_denied(installed, form):
    g, cfg, proj = installed
    line = form.format(t=cfg / "hooks" / "agent_guard.py")
    got = g.protected_write_in(line, {"cwd": str(proj)})
    assert got and got[0] == "protect", line


def test_a_doc_command_in_a_value_slot_does_not_hide_the_rest(installed):
    """arch's -arm64e is no cluster of -e: `find` is the program, `which` its argument. Whenever a
    wrapper took a value or operand slot, a doc-command head no longer skips the command."""
    g, cfg, proj = installed
    assert g.git_push_in("arch -arm64e find which -exec git push origin main")
    got = g.protected_write_in("arch -arm64e find which -exec cp new.py %s"
                               % (cfg / "hooks" / "agent_guard.py"), {"cwd": str(proj)})
    assert got and got[0] == "protect"


def _slot_cases(g):
    """Every (wrapper, value option) of the table: the slot holds the program (`sudo -u find`)."""
    for wrap, opts in sorted(g.WRAPPER_VALUE_OPTS.items()):
        for opt in sorted(opts):
            yield wrap, opt


@pytest.mark.parametrize("line", [
    "time --foo which find -exec git push o m",    # --foo may take `which` as its value
    "chronic which find -exec git push o m",
    "watch man find -exec git push o m",
    "stdbuf -E man builtin -0n find . -exec git push \\;",
    "/usr/bin/env man find -exec git push o m",
])
def test_doc_command_past_wrapper_arguments_is_not_trusted(installed, line):
    """A doc command is the program (and its words data) only right after X=1 and plain prefix
    words, as before this branch; past options, values, operands or another wrapper it may be a
    value, so the rest is checked."""
    g, _, _ = installed
    assert g.git_push_in(line), line


def test_arch_words_are_no_option_clusters(installed):
    """arch -arm64e is one option (no -e value): `echo` is the program, git-push its argument."""
    g, _, _ = installed
    assert not g.git_push_in("arch -arm64e echo git-push")


def test_doc_command_after_plain_prefix_words_stays_data(installed):
    g, _, _ = installed
    for line in ["man git push", "sudo man git push", "env X=1 which git-push", "nohup help push"]:
        assert not g.git_push_in(line), line


def test_every_value_option_fails_closed(installed):
    """Whatever the table says takes a value, a program in that slot is still checked, and a
    doc-command word after it hides nothing (a miss here would be a miss against main)."""
    g, cfg, proj = installed
    target = cfg / "hooks" / "agent_guard.py"
    for wrap, opt in _slot_cases(g):
        for line in ["%s %s git-push origin main" % (wrap, opt),
                     "%s %s find which -exec git push origin main" % (wrap, opt)]:
            assert g.git_push_in(line), line
        line = "%s %s find which -exec cp new.py %s" % (wrap, opt, target)
        got = g.protected_write_in(line, {"cwd": str(proj)})
        assert got and got[0] == "protect", line


@pytest.mark.parametrize("form", ["watch -n 5 '{cmd}'", "flock /tmp/l -c '{cmd}'",
                                  "flock -w 5 /tmp/l '{cmd}'", "watch -s /tmp {cmd}",
                                  "flock -E 3 /tmp/l --command '{cmd}'", "watch -n 5 -d '{cmd}'"])
def test_string_runner_command_after_its_options_is_scanned(installed, form):
    """watch/flock run their (joined) arguments as a shell command; the command starts after their
    own options, values and flock's lock file."""
    g, cfg, proj = installed
    line = form.format(cmd="cp new.py %s" % (cfg / "hooks" / "agent_guard.py"))
    got = g.protected_write_in(line, {"cwd": str(proj)})
    assert got and got[0] == "protect", line
    line = form.format(cmd="git-push origin main")
    assert g.git_push_in(line), line
    line = form.format(cmd="mcp-headers exa --reveal")
    got = g.secrets_leak_in(line, {"cwd": str(proj)})
    assert got and got[0] == "secrets", line


# zsh's noclobber overrides: `>|` and its both-stream and append forms lex as one word; `>!`
# (`>>!`, `&>!`, `>&!`, `2>!`) lexes as `>` and `!`, read both ways (_zsh_clobber_words)
CLOBBER_OPS = [">|", ">", ">>", "1>|", ">>|", "&>|", ">&|", "&>>|", ">>&|", ">!", ">>!", "&>!",
               ">&!", "2>!", ">>&!", "&>>!", ">&"]


@pytest.mark.parametrize("op", CLOBBER_OPS)
def test_clobber_redirect_into_protected_path_denied(installed, op):
    g, cfg, proj = installed
    for fmt in ("echo x %s %s", "echo x %s%s"):
        line = fmt % (op, cfg / "hooks" / "agent_guard.py")
        got = g.protected_write_in(line, {"cwd": str(proj)})
        assert got and got[0] == "protect", line


def test_arguments_that_look_like_wrapper_args_stay_arguments(installed):
    """A duration or option value is a command position only right after its wrapper."""
    g, cfg, proj = installed
    ev = {"cwd": str(proj)}
    target = cfg / "hooks" / "agent_guard.py"
    for line in [
        "sleep 30 git-push",                       # not a wrapper: `git-push` is sleep's operand
        "echo timeout 30 git-push",                # timeout is echo's argument here
        "head -n 10 git-push",
        "grep -u x git-push",
        "ls -s 30 git-push",
    ]:
        assert not g.git_push_in(line), line
    for line in [
        "echo timeout 30 cp new.py %s" % target,
        "printf '%%s' nice -n 10 rm %s" % target,
        "head -n 10 %s" % target,                  # a read, not a write
        "timeout 30 cat %s" % target,
        "nice -n 10 ls %s" % target,
    ]:
        assert not g.protected_write_in(line, ev), line
    assert not g.secrets_leak_in("timeout 30 mcp-headers exa", ev)
    assert not g.secrets_leak_in("echo nice -n 10 mcp-headers exa --reveal", ev)


# env splits -S's text and parses the words as its own arguments again (getopt restarts): a -S
# inside the text, or after an option value that looks like one, still runs the command
# (/usr/bin/env on this Mac runs `echo` for each form). Round 3 rescanned the text without an
# `env` in front and missed the first two forms, which main caught.
ENV_SPLIT_AGAIN = [
    "env -u -iS -S '{cmd}'",                   # -iS is -u's value
    "env -C --s -S '{cmd}'",                   # --s is -C's value
    "env -u -S -S '{cmd}'",                    # the first -S is -u's value
    "env -iS -S '{cmd}'",                      # -iS splits `-S`, which env reads as -S again
    "env -iS -iS '{cmd}'",
    "env -S '-i {cmd}'",                       # options inside the split text
    "env -S '-u X {cmd}'",
    "env -S'-S {cmd}'",
    "env -iuS -iS --split-string='{cmd}' >/dev/null",
]


@pytest.mark.parametrize("form", ENV_SPLIT_AGAIN)
def test_env_split_text_is_read_as_env_arguments_again(installed, form):
    g, cfg, proj = installed
    ev = {"cwd": str(proj)}
    assert g.git_push_in(form.format(cmd="git-push origin main")), form
    line = form.format(cmd="rm -f %s" % (cfg / "hooks" / "agent_guard.py"))
    got = g.protected_write_in(line, ev)
    assert got and got[0] == "protect", line
    got = g.secrets_leak_in(form.format(cmd="mcp-headers exa --reveal"), ev)
    assert got and got[0] == "secrets", form


def test_env_split_word_in_a_value_slot_is_scanned_too(installed):
    """`env -u -S 'CMD'`: getopt takes -S as -u's value, main read it as -S: still scanned."""
    g, _, _ = installed
    assert g.git_push_in("env -u -S 'git-push origin main'")


@pytest.mark.parametrize("line", [
    "git >! F push origin main", "git >>! F push origin main", "git 2>! F push origin main",
    "git >&| F push origin main", "git &>| F push origin main", "git >&! F push origin main",
    "git >! push origin main", "git > ! push origin main",     # bash: `!` is the target
])
def test_push_after_a_zsh_clobber_redirection_denied(installed, line):
    """zsh reads `>! F` as `>| F`: F is the target, not git's subcommand."""
    g, _, _ = installed
    assert g.git_push_in(line), line


@pytest.mark.parametrize("lead", ["> F", "2>/dev/null", ">/dev/null 2>&1", "2>&1", "&> F", "1>| F",
                                  ">! F", ">&| F", "< in.txt", "<<< x", "X=1 > F", "> F timeout 30",
                                  "timeout 30 >/dev/null", "sudo -u u 2>&1"])
def test_redirection_before_the_command_word_is_no_command(installed, lead):
    """A redirection may come first (`>/dev/null rm ...`): its operator and target keep the
    command position. Missed on main."""
    g, cfg, proj = installed
    ev = {"cwd": str(proj)}
    assert g.git_push_in("%s git-push origin main" % lead), lead
    line = "%s rm -f %s" % (lead, cfg / "hooks" / "agent_guard.py")
    got = g.protected_write_in(line, ev)
    assert got and got[0] == "protect", line
    got = g.secrets_leak_in("%s mcp-headers exa --reveal" % lead, ev)
    assert got and got[0] == "secrets", lead


def test_redirection_target_before_an_argument_stays_no_command(installed):
    g, _, _ = installed
    for line in ["> F echo git-push", "2>/dev/null echo git-push", "echo x > git-push"]:
        assert not g.git_push_in(line), line


@pytest.mark.parametrize("trail", ["> /dev/null", "2>/dev/null", "2>&1", ">/dev/null 2>&1",
                                   "> out.log", ">! /dev/null", ">&| /dev/null", "&> out.log"])
def test_output_redirection_is_no_operand_of_a_write_command(installed, trail):
    """`cp x <protected> >/dev/null`: the destination is <protected>, not /dev/null (missed on
    main)."""
    g, cfg, proj = installed
    t = cfg / "hooks" / "agent_guard.py"
    for cmd in ("cp new.py %s" % t, "install -m 644 new.py %s" % t, "mv new.py %s" % t):
        line = "%s %s" % (cmd, trail)
        got = g.protected_write_in(line, {"cwd": str(proj)})
        assert got and got[0] == "protect", line



@pytest.mark.parametrize("fmt", ["rm -r '>' {c}", "rm -rf \\> {c}", 'rm -r ">" {c}',
                                 "mv {c} '>' /tmp/x", "mv {c}/hooks '>' /tmp/x",
                                 "mv '>' {c} /tmp/x",
                                 'mv {c} ">" /tmp/x', "rm -r '>|' {c}", "rm -r '2>' {c}"])
def test_a_quoted_redirection_word_stays_an_operand(installed, fmt):
    """The lexer cannot tell a quoted '>' from the operator, so a write command's operands are
    also read as given: `rm -r '>' <config dir>` removes both (main caught these; dropping the
    word and the operand after it missed them)."""
    g, cfg, proj = installed
    line = fmt.format(c=cfg)
    got = g.protected_write_in(line, {"cwd": str(proj)})
    assert got and got[0] == "protect", line


def test_a_quoted_redirection_word_alone_flags_nothing(installed):
    g, _, proj = installed
    for line in ["echo '>' foo", "cp x y '>' z", "rm -r '>' build", "mv a '>' b"]:
        assert not g.protected_write_in(line, {"cwd": str(proj)}), line

def test_each_redirection_reading_starts_from_the_same_state(installed, monkeypatch):
    """bash's reading of `>! T` runs first; zsh's must not see its NAME+=... applied twice."""
    g, cfg, proj = installed
    monkeypatch.setenv("D", str(cfg.parent))
    line = "D+=/claude && echo x >! $D/hooks/agent_guard.py"
    got = g.protected_write_in(line, {"cwd": str(proj)})
    assert got and got[0] == "protect", line


OUTSIDE = "/opt/zz-not-scratch/a.py"


@pytest.mark.parametrize("line", ["echo x >&| {o}", "echo x &>| {o}", "echo x >>&| {o}",
                                  "echo x &>>| {o}", "echo x >! {o}", "echo x >>! {o}",
                                  "echo x 2>! {o}", "echo x &>! {o}", "echo x >!{o}",
                                  ">! cat rm -rf {d}"])
def test_readonly_zsh_clobber_redirection_outside_scratch_denied(installed, line):
    """A read-only agent in a scratch dir: zsh writes `>! F`'s F (bash writes `!`, scratch)."""
    g, _, proj = installed
    scratch = proj / ".claude-work" / "j"
    scratch.mkdir(parents=True)
    line = line.format(o=OUTSIDE, d="/opt/zz-not-scratch")
    assert g.readonly_violation(line, {"cwd": str(scratch)}), line


def test_readonly_readings_start_from_the_same_cwd(installed, monkeypatch):
    """zsh's reading of `cd k && echo x >! ../../../src/a.py` must not apply the cd twice."""
    g, _, proj = installed
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(proj))
    scratch = proj / ".claude-work" / "j"
    (scratch / "k").mkdir(parents=True)
    line = "cd k && echo x >! ../../../src/a.py"
    assert g.readonly_violation(line, {"cwd": str(scratch)}), line


# a wrapper that runs a separate program (timeout N, nice -n N, sudo -u U, /usr/bin/env) makes
# `cd`, `for` and `select` external: they move no $PWD and bind no variable in this shell, so the
# wider command position must not note them (main never reached them there)
@pytest.mark.parametrize("line", [
    'timeout 30 cd /tmp; rm -rf "$PWD/../claude/hooks"',
    'nice -n 5 cd /tmp; rm -rf "$PWD/../claude/hooks"',
    'sudo -u root cd /tmp; rm -rf "$PWD/../claude/hooks"',
    '/usr/bin/env cd /tmp; rm -rf "$PWD/../claude/hooks"',
    'read V < f; timeout 5 for V in x; rm -rf "$V/hooks"',
    'read V < f; nice -n 5 select V in x; rm -rf "$V/hooks"',
])
def test_cd_and_for_behind_a_program_running_wrapper_bind_nothing(installed, line):
    g, _, proj = installed
    got = g.protected_write_in(line, {"cwd": str(proj)})
    assert got and got[0] == "protect", line


def test_cds_behind_a_wrapper_do_not_fill_the_cd_list(installed):
    g, cfg, proj = installed
    line = "".join("timeout 1 cd /x%d; " % k for k in range(48)) + "cd %s && rm -rf hooks" % cfg
    got = g.protected_write_in(line, {"cwd": str(proj)})
    assert got and got[0] == "protect"


def test_cd_where_main_noted_it_is_still_noted(installed):
    """`env cd DIR` / `sudo cd DIR`: main noted the cd (a relative write is also read below DIR);
    that stays, so no line main flags is lost."""
    g, cfg, proj = installed
    for line in ["env cd %s && rm -rf hooks" % cfg, "sudo cd %s && rm -rf hooks" % cfg]:
        got = g.protected_write_in(line, {"cwd": str(proj)})
        assert got and got[0] == "protect", line


LONG = 10000


@pytest.mark.parametrize("chain", ["watch" + " -n" * LONG, "watch" + " -n 5" * LONG,
                                   "flock /tmp/l" + " -w 5" * LONG, "nice" + " -n rm" * LONG,
                                   "sudo" + " -u cp" * LONG, "env" + " -u X" * LONG,
                                   "timeout 1 " * LONG, "arch" + " -arch rm" * LONG])
def test_a_long_wrapper_value_chain_is_bounded_and_fails_closed(installed, chain):
    """Each value slot is read as a command too, and watch/flock rescan from every value: a
    chain of 10k values took quadratic time (17 s, past the deadline: no hit) where main took
    well under a second. Now each is bounded and a hit."""
    import time
    g, cfg, proj = installed
    ev = {"cwd": str(proj)}
    for tail, check in ((" x; rm -rf %s/hooks" % cfg, lambda ln: g.protected_write_in(ln, ev)),
                        (" x; git push", g.remote_write_in),
                        (" x; mcp-headers exa --reveal", lambda ln: g.secrets_leak_in(ln, ev))):
        t0 = time.monotonic()
        got = check(chain + tail)
        assert got and time.monotonic() - t0 < 5, (chain[:40], tail)


@pytest.mark.parametrize("wrap", ["watch", "nice"])
def test_too_many_runner_starts_or_wrapper_words_fail_closed(installed, wrap):
    """Past MAX_RUNNER_STARTS rescans or MAX_WRAPPER_ARGS wrapper words a command the scan reads
    (it names git or a write command) is refused even when harmless: nobody writes that, and
    checking it costs quadratic time."""
    g, _, proj = installed
    chain = wrap + " -n 5" * 70
    got = g.protected_write_in(chain + " touch x", {"cwd": str(proj)})
    assert got and got[0] == "protect", wrap
    assert g.git_push_in(chain + " echo git"), wrap


def test_runner_start_scans_charge_the_budget(installed, monkeypatch):
    """Each watch/flock start is a scan: it charges the budget even when its text names nothing
    to check (the nested scan returns before its own budget test), and an exhausted budget is a
    hit of the kind the scan reports (fail closed)."""
    g, _, proj = installed
    monkeypatch.setattr(g, "MAX_SCANS", 3)
    got = g.protected_write_in("touch x; watch -n 5 -n 5 -n 5 -n 5 echo hi", {"cwd": str(proj)})
    assert got and got[0] == "protect"


def test_option_words_in_runner_value_slots_are_no_starts(installed):
    """`watch -n -d -n -d ... CMD`: an option in a value slot is no command start. 31 of them
    (63 wrapper words, under MAX_WRAPPER_ARGS) would be 33 starts, past MAX_RUNNER_STARTS: read as
    starts they fail closed; as options a harmless command passes, quickly."""
    import time
    g, _, proj = installed
    line = "watch" + " -n -d" * 31 + " echo git"
    t0 = time.monotonic()
    assert not g.protected_write_in(line, {"cwd": str(proj)})
    assert not g.git_push_in(line)
    assert time.monotonic() - t0 < 2


# the rescans main never made (env -S text after an `env`, watch/flock past their first start)
# only add hits: a cd, pushd, for or select read there must not move $PWD or rebind a variable
# that main's own reading keeps suspect (lines from the differential fuzz)
@pytest.mark.parametrize("line", [
    'env -S-S \'cd /tmp; rm -rf "$PWD/../claude/hooks"\'',
    'read V < f; env env --s -S-i doas select V in x; rm -rf "$V/hooks"',
    'env watch -s --split-string -n -CS cd /tmp; rm -rf "$PWD/../claude/hooks"',
    'flock /tmp/l pushd /tmp; rm -rf "$PWD/../claude/hooks"',
    'true && watch watch -n KILL cd /tmp; rm -rf "$PWD/../claude/hooks"',
    'env -P -S-i cd /tmp; rm -rf "$PWD/../claude/hooks"',
    'read V < f; $(which env) X=1 -P % --split-string --s \'for V in x; rm -rf "$V/hooks"\'',
])
def test_rescans_main_never_made_bind_nothing(installed, line):
    g, _, proj = installed
    got = g.protected_write_in(line, {"cwd": str(proj)})
    assert got and got[0] == "protect", line
