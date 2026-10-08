"""bin/stack-run: a command's output in a masked log, one PASS/FAIL line, the decisive lines on failure.

Run: uv run --no-project --python 3.13 --with pytest pytest -q tests/test_stack_run.py
Every test runs a copy of dot-config/dot-claude/bin/stack-run, bin/stack-tree and hooks/output_shrink.py under
tmp_path, with its own HOME, project and CLAUDE_CONFIG_DIR; the commands it runs are `python -c` snippets.
Nothing in the repository or ~ is written. OUTPUT_SHRINK_ROOT=<checkout> tests another checkout (the
mutation check uses it). The last section checks that the guard reads `stack-run ... -- CMD` as CMD.
"""
import json
import os
import re
import shutil
import signal
import stat
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(os.environ.get("OUTPUT_SHRINK_ROOT") or Path(__file__).resolve().parents[1])
DOT = ROOT / "dot-config" / "dot-claude"
PY = sys.executable
LINE_RE = re.compile(r"^(PASS|FAIL) rc=(\d+) (\d+\.\d)s lines=(\d+) log=(\S+)$")

pytestmark = pytest.mark.skipif(sys.version_info < (3, 9), reason="stack-run's floor is Python 3.9")

GHP = "ghp" + "_" + "Q7wX" * 9                     # fake credentials, assembled so no scanner flags the file
AKIA = "AKIA" + "Z" * 16
BEARER = "Authorization: Bearer " + "abcdefghijklmnop" + "123456"
PEM = ["-----BEGIN RSA PRIVATE" + " KEY-----", "MIIEowIBAAKCAQEA" + "x" * 48, "-----END RSA PRIVATE" + " KEY-----"]


@pytest.fixture
def sr(tmp_path):
    tmp = tmp_path.resolve()
    c = tmp / "C"
    (c / "bin").mkdir(parents=True)
    (c / "hooks").mkdir()
    for rel in ("bin/stack-run", "bin/stack-tree", "hooks/output_shrink.py"):
        shutil.copy2(DOT / rel, c / rel)
    home, proj = tmp / "home", tmp / "proj"
    home.mkdir()
    proj.mkdir()
    env = {k: v for k, v in os.environ.items() if not k.startswith(("STACK_", "CLAUDE_"))}
    env.update(HOME=str(home), CLAUDE_PROJECT_DIR=str(proj), CLAUDE_CONFIG_DIR=str(tmp / "cfgdir"),
               CLAUDE_CODE_SESSION_ID="sid-1")

    def run(*args, cwd=proj, stdin=None, extra=None, argv0=None, timeout=120):
        e = dict(env, **(extra or {}))
        cmd = [str(argv0)] if argv0 else [PY, str(c / "bin" / "stack-run")]
        p = subprocess.run(cmd + list(args), cwd=str(cwd), input=stdin, capture_output=True, env=e,
                           timeout=timeout, check=False)
        p.out = p.stdout.decode("utf-8")
        p.err = p.stderr.decode("utf-8", "replace")
        return p

    return SimpleNamespace(tmp=tmp, c=c, home=home, proj=proj, env=env, run=run)


def py(code):
    """argv of a child that runs `code`."""
    return ["--", PY, "-c", code]


def head(p):
    """(status, rc, lines, log path or None) of the first stdout line; asserts its shape."""
    first = p.out.split("\n")[0]
    m = LINE_RE.match(first)
    assert m, p.out[:300] + p.err[:300]
    return m.group(1), int(m.group(2)), int(m.group(4)), None if m.group(5) == "-" else Path(m.group(5))


def shown(p):
    """The L<n> lines after the first line: [(n, text)]."""
    out = []
    for x in p.out.split("\n")[1:]:
        if x:
            m = re.match(r"L(\d+): (.*)\Z", x, re.DOTALL)
            assert m, x
            out.append((int(m.group(1)), m.group(2)))
    return out


def runs_dir(sr):
    return sr.proj / ".claude-work" / "runs"


def size_rows(sr):
    p = sr.proj / ".claude-work" / "output-shrink" / "log.jsonl"
    return [json.loads(x) for x in p.read_text().splitlines()] if p.exists() else []


FAILING = ("import sys\n"
           "for i in range(3000): print('step %05d ok' % i)\n"
           "sys.stdout.flush()\n"
           "print('error: the decisive failure', file=sys.stderr, flush=True)\n"
           "for i in range(3000, 3500): print('step %05d ok' % i)\n"
           "print('=== 1 failed, 99 passed in 3.2s ===')\n"
           "sys.exit(1)\n")


# ---------------------------------------------------------------- the one line, the log
def test_pass_prints_exactly_one_line_and_logs_everything(sr):
    p = sr.run(*py("for i in range(5000): print('line %d' % i)"))
    assert p.returncode == 0, p.err
    status, rc, lines, log = head(p)
    assert (status, rc, lines) == ("PASS", 0, 5000) and p.out.count("\n") == 1
    assert log.parent == runs_dir(sr) and re.fullmatch(r"python[\w.]*-\d{8}-\d{6}\.log", log.name), log.name
    assert log.read_text().split("\n")[:-1] == ["line %d" % i for i in range(5000)]


def test_fail_prints_the_line_and_the_decisive_lines(sr):
    p = sr.run(*py(FAILING))
    assert p.returncode == 1
    status, rc, lines, log = head(p)
    assert (status, rc, lines) == ("FAIL", 1, 3502)
    got = shown(p)
    texts = [t for _, t in got]
    assert "error: the decisive failure" in texts and "=== 1 failed, 99 passed in 3.2s ===" in texts
    assert len(got) == 20 and [n for n, _ in got] == sorted(n for n, _ in got)
    logged = log.read_text().split("\n")
    assert all(logged[n - 1] == t for n, t in got)                  # L<n> is the log's line n


@pytest.mark.parametrize("code,rc", [(0, 0), (1, 1), (3, 3), (255, 255)])
def test_exit_status_is_the_commands(sr, code, rc):
    p = sr.run(*py("import sys; print('x'); sys.exit(%d)" % code))
    assert p.returncode == rc and head(p)[:2] == ("PASS" if rc == 0 else "FAIL", rc)


def test_command_not_found_is_127(sr):
    p = sr.run("--", "no-such-command-zz9")
    assert p.returncode == 127 and head(p)[:3] == ("FAIL", 127, 1)
    assert shown(p) == [(1, "stack-run: cannot run no-such-command-zz9: command not found")]


def test_command_not_executable_is_126(sr):
    f = sr.tmp / "plain.txt"
    f.write_text("not a program")
    os.chmod(f, 0o644)
    p = sr.run("--", str(f))
    assert p.returncode == 126 and head(p)[1] == 126


@pytest.mark.parametrize("sig", [signal.SIGTERM, signal.SIGKILL])
def test_a_command_ended_by_a_signal_is_128_plus_n(sr, sig):
    p = sr.run(*py("import os, signal; print('before', flush=True); os.kill(os.getpid(), %d)" % sig))
    assert p.returncode == 128 + sig and head(p)[:3] == ("FAIL", 128 + sig, 1)


@pytest.mark.parametrize("sig,name,code", [(signal.SIGTERM, "TERM", 7), (signal.SIGINT, "INT", 5)])
def test_sigint_and_sigterm_are_passed_on(sr, sig, name, code):
    ready = sr.tmp / "ready"
    child = ("import signal, sys, time, pathlib\n"
             "def h(s, f):\n    print('got %s', flush=True); sys.exit(%d)\n"
             "signal.signal(%d, h)\n"
             "pathlib.Path(%r).write_text('1')\n"
             "time.sleep(60)\n" % (name, code, sig, str(ready)))
    proc = subprocess.Popen([PY, str(sr.c / "bin" / "stack-run"), *py(child)], cwd=str(sr.proj), env=sr.env,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    deadline = time.time() + 30
    while not ready.exists() and time.time() < deadline:
        time.sleep(0.05)
    assert ready.exists()
    os.kill(proc.pid, sig)                               # stack-run only: the child hears it through stack-run
    out, _ = proc.communicate(timeout=30)
    assert proc.returncode == code
    log = Path(out.decode().split("log=")[1].split("\n")[0])
    assert log.read_text() == "got %s\n" % name


def test_stdin_is_inherited(sr):
    p = sr.run(*py("import sys; print(sys.stdin.read().upper())"), stdin=b"hello\n")
    assert p.returncode == 0 and head(p)[3].read_text() == "HELLO\n\n"


# ---------------------------------------------------------------- files: modes, names, masking
def test_log_is_0600_in_a_0700_dir_with_a_gitignore(sr):
    log = head(sr.run(*py("print(1)")))[3]
    assert stat.S_IMODE(log.stat().st_mode) == 0o600
    assert stat.S_IMODE(runs_dir(sr).stat().st_mode) == 0o700
    assert (runs_dir(sr) / ".gitignore").read_text() == "*\n"


def test_an_existing_wide_runs_dir_is_tightened_and_a_symlink_refused(sr):
    runs_dir(sr).mkdir(parents=True, mode=0o755)
    os.chmod(runs_dir(sr), 0o755)
    assert head(sr.run(*py("print(1)")))[3] is not None
    assert stat.S_IMODE(runs_dir(sr).stat().st_mode) == 0o700
    shutil.rmtree(runs_dir(sr))
    elsewhere = sr.tmp / "elsewhere"
    elsewhere.mkdir()
    runs_dir(sr).symlink_to(elsewhere)
    p = sr.run(*py("print(1)"))
    assert p.returncode == 0 and head(p)[3] is None and list(elsewhere.iterdir()) == []


@pytest.mark.parametrize("name,want", [("../../etc/passwd", "_.._etc_passwd"), ("a b/c;d$(x)", "a_b_c_d__x_"),
                                       ("...", "run"), ("-rf", "rf"), (".hidden", "hidden"), ("x" * 99, "x" * 64),
                                       ("ok.name-1_2", "ok.name-1_2")])
def test_name_is_sanitised_and_cannot_leave_the_runs_dir(sr, name, want):
    log = head(sr.run("--name", name, *py("print(1)")))[3]
    assert log.parent == runs_dir(sr) and re.fullmatch(re.escape(want) + r"-\d{8}-\d{6}\.log", log.name), log.name
    assert sorted(p.name for p in (sr.proj / ".claude-work").iterdir()) == ["output-shrink", "runs"]


def test_same_name_in_the_same_second_gets_a_new_file(sr):
    logs = {head(sr.run("--name", "t", *py("print(%d)" % i)))[3] for i in range(3)}
    assert len(logs) == 3 and all(p.exists() for p in logs)


def test_credentials_are_masked_in_the_log_and_the_printed_lines(sr):
    lines = ["export API_KEY=sk-live-Abc123Def456Ghi789", BEARER, "token " + GHP, "aws " + AKIA] + PEM
    code = "import sys\nfor s in %r: print(s)\nprint('error: boom ' + %r)\nsys.exit(2)\n" % (lines, GHP)
    p = sr.run("--grep", "Bearer|token|aws|API_KEY", *py(code))
    log = head(p)[3]
    data = log.read_text()
    for needle in ("sk-live-Abc123Def456Ghi789", "abcdefghijklmnop123456", GHP, AKIA, PEM[1]):
        assert needle not in data and needle not in p.out, needle
    assert data.count("\n") == len(lines) + 1                          # one line in, one line out
    assert any(t.startswith("error: boom ") for _, t in shown(p))


# ---------------------------------------------------------------- --tail, --grep
@pytest.mark.parametrize("k", [0, 1, 7, 50])
def test_tail_caps_the_decisive_lines(sr, k):
    code = "import sys\nfor i in range(400): print('error: case %d' % i)\nsys.exit(1)\n"
    p = sr.run("--tail", str(k), *py(code))
    assert head(p)[0] == "FAIL" and len(shown(p)) == k
    if k:
        assert shown(p)[-1] == (400, "error: case 399")                # the last error line first in the pick


def test_tail_takes_the_equals_form(sr):
    p = sr.run("--tail=2", *py("import sys\nfor i in range(30): print('error %d' % i)\nsys.exit(1)"))
    assert len(shown(p)) == 2


def test_grep_prints_the_first_k_matches_on_pass(sr):
    p = sr.run("--grep", r"item 1\d$", "--tail", "5", *py("for i in range(100): print('item %d' % i)"))
    assert head(p)[0] == "PASS"
    assert shown(p) == [(11 + i, "item %d" % (10 + i)) for i in range(5)]


def test_grep_on_fail_adds_matches_to_the_decisive_lines_once(sr):
    p = sr.run("--grep", "^step 0000[0-2] ok$|decisive", *py(FAILING))
    got = shown(p)
    assert (1, "step 00000 ok") in got and (3, "step 00002 ok") in got
    assert len({n for n, _ in got}) == len(got) == 23                  # 20 decisive, 3 more matches, none twice


@pytest.mark.parametrize("args", [["CHILD"], ["--"], ["--tail", "1001", "--", "CHILD"], ["--tail", "-1", "--", "CHILD"],
                                  ["--tail", "x", "--", "CHILD"], ["--grep", "(", "--", "CHILD"],
                                  ["--grep", "--", "CHILD"], ["--frob", "1", "--", "CHILD"], ["stray", "--", "CHILD"],
                                  ["--name", "CHILD"]])
def test_usage_errors_exit_2_and_run_nothing(sr, args):
    marker = sr.tmp / "ran"
    child = [PY, "-c", "import pathlib; pathlib.Path(%r).write_text('1')" % str(marker)]
    argv = [x for a in args for x in (child if a == "CHILD" else [a])]
    p = sr.run(*argv)
    assert p.returncode == 2 and "usage: stack-run" in p.err and p.out == ""
    assert not marker.exists() and not (sr.proj / ".claude-work").exists()


def test_help(sr):
    p = sr.run("--help")
    assert p.returncode == 0 and "stack-run [--name N] [--tail K] [--grep PATTERN] -- CMD" in p.out


# ---------------------------------------------------------------- odd output
def test_invalid_utf8_and_binary_output(sr):
    code = ("import sys\nb = sys.stdout.buffer\nb.write(b'ok\\n\\xff\\xfe bad \\x00 nul\\n\\xc3\\x28\\n')\n"
            "b.write(bytes(range(256)))\nb.flush()\nsys.exit(4)\n")
    p = sr.run(*py(code))
    assert p.returncode == 4
    _, _, lines, log = head(p)
    data = log.read_bytes().decode("utf-8")
    assert data.startswith("ok\n") and "�" in data and lines == data.count("\n") == 5
    assert any("\\0" in t for _, t in shown(p)) and "\x00" not in p.out


def test_a_line_over_1_mib_is_logged_in_pieces(sr):
    p = sr.run(*py("import sys; sys.stdout.write('y' * (3 * 2 ** 20 + 5))"))
    status, _, lines, log = head(p)
    assert (status, lines) == ("PASS", 4) and log.stat().st_size == 3 * 2 ** 20 + 5 + 4


def test_large_output_streams(sr):
    p = sr.run(*py("import sys\nw = sys.stdout.write\nfor i in range(200000): w('row %07d %s\\n' % (i, 'z' * 60))\n"
                   "print('error: at the end')\nsys.exit(9)\n"), timeout=300)
    _, rc, lines, log = head(p)
    assert (rc, lines) == (9, 200001) and log.stat().st_size > 14_000_000
    assert (200001, "error: at the end") in shown(p)


# ---------------------------------------------------------------- degraded: no module, no masker, no safe dir
def test_without_output_shrink_no_log_and_the_last_k_lines(sr):
    empty = sr.tmp / "nohooks"
    empty.mkdir()
    code = "import sys\nfor i in range(50): print('n%%d' %% i)\nprint(%r)\nprint('w' * 1000)\nsys.exit(3)\n" % GHP
    p = sr.run("--tail", "4", *py(code), extra={"STACK_HOOKS_DIR": str(empty)})
    assert p.returncode == 3 and head(p) == ("FAIL", 3, 52, None)
    assert shown(p) == [(49, "n48"), (50, "n49"), (51, GHP), (52, "w" * 300 + "… [+700 chars]")]
    assert "cannot load hooks/output_shrink.py" in p.err and not (sr.proj / ".claude-work").exists()
    p = sr.run("--tail", "0", *py(code), extra={"STACK_HOOKS_DIR": str(empty)})
    assert head(p) == ("FAIL", 3, 52, None) and shown(p) == []


def test_without_credential_tables_nothing_is_written(sr):
    (sr.c / "bin" / "stack-tree").unlink()
    p = sr.run("--tail", "2", *py("import sys\nfor i in range(9): print('m%d' % i)\nsys.exit(1)"))
    assert head(p) == ("FAIL", 1, 9, None) and shown(p) == [(8, "m7"), (9, "m8")]
    assert "credential tables unavailable" in p.err and not runs_dir(sr).exists()


@pytest.mark.parametrize("where", ["home", "config"])
def test_no_log_in_home_or_a_config_dir(sr, where):
    cwd = sr.home if where == "home" else sr.tmp / "cfgdir" / "x"
    cwd.mkdir(parents=True, exist_ok=True)
    p = sr.run(*py(FAILING), cwd=cwd)
    assert head(p) == ("FAIL", 1, 3502, None) and "error: the decisive failure" in [t for _, t in shown(p)]
    assert not list(sr.tmp.glob("home/.claude-work")) and not list(sr.tmp.glob("cfgdir/**/.claude-work"))


def test_runs_by_its_shebang_on_the_system_python(sr):
    if not os.access("/usr/bin/python3", os.X_OK):
        pytest.skip("no /usr/bin/python3")
    p = sr.run(*py(FAILING), argv0=sr.c / "bin" / "stack-run")
    assert head(p)[:3] == ("FAIL", 1, 3502) and len(shown(p)) == 20, p.err
    assert not (sr.c / "hooks" / "__pycache__").exists() and not (sr.c / "bin" / "__pycache__").exists()


# ---------------------------------------------------------------- D: the size row
def test_each_run_appends_one_size_row(sr):
    p = sr.run("--tail", "3", *py(FAILING + "#" + GHP))
    rows = size_rows(sr)
    assert len(rows) == 1
    r = rows[0]
    out_chars = sum(len(x) + 1 for x in p.out.split("\n")[:-1])
    assert (r["v"], r["tool"], r["mode"], r["cls"], r["rc"], r["lines"]) == (1, "stack-run", "on", "run", 1, 3502)
    assert r["kept_chars"] == out_chars and r["kept_lines"] == 4 and r["applied"] is True and r["cut"] is True
    assert r["chars"] == len(head(p)[3].read_text()) and r["sid"] == "sid-1" and r["aid"] == ""
    assert re.fullmatch(r"[0-9a-f]{16}", r["key"]) and r["fam"].startswith("python")
    raw = (sr.proj / ".claude-work" / "output-shrink" / "log.jsonl").read_text()
    assert GHP[:12] not in raw and "decisive" not in raw and "step" not in raw
    rep = subprocess.run([PY, str(sr.c / "hooks" / "output_shrink.py"), "--report", str(sr.proj), "--json"],
                         capture_output=True, text=True, env=sr.env, timeout=60, check=False)
    t = json.loads(rep.stdout)["by_tool_mode"]["stack-run/on"]
    assert t["rows"] == 1 and t["cut"] == r["chars"] - r["kept_chars"] and t["kept"] == r["kept_chars"]


def test_no_size_row_outside_a_safe_project(sr):
    env = {"CLAUDE_PROJECT_DIR": str(sr.home)}
    p = sr.run(*py("print(1)"), extra=env)
    assert p.returncode == 0 and size_rows(sr) == [] and not (sr.home / ".claude-work").exists()


# ---------------------------------------------------------------- shipped: installer, rules
def test_installer_ships_it_and_the_rules_name_it():
    inst = (ROOT / "install.sh").read_text()
    assert '\nstage_script 755 "bin/stack-run"\n' in inst
    assert '"bin/stack-run"' in re.search(r"(?s)STACK_SCRIPTS = \[(.*?)\]", inst).group(1)
    assert os.access(DOT / "bin" / "stack-run", os.X_OK)
    assert (DOT / "bin" / "stack-run").read_text().startswith("#!/usr/bin/python3 -B\n")
    rules = (DOT / "rules" / "claude-agent-stack.md").read_text()
    assert "`__CLAUDE_DIR__/bin/stack-run -- cmd`" in rules


# ---------------------------------------------------------------- the guard reads `stack-run ... -- CMD` as CMD
@pytest.fixture
def guard(tmp_path, monkeypatch):
    """An installed-looking config dir (as in test_protected_paths) with bin/stack-run, and a project."""
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    cfg = tmp_path / "claude"
    (cfg / "hooks").mkdir(parents=True)
    (cfg / "bin").mkdir()
    for f in ("agent_guard.py", "stack_io.py"):
        shutil.copy(DOT / "hooks" / f, cfg / "hooks" / f)
    shutil.copy2(DOT / "bin" / "stack-run", cfg / "bin" / "stack-run")
    (cfg / "settings.json").write_text((DOT / "settings.json").read_text().replace("__CLAUDE_DIR__", str(cfg)))
    proj = tmp_path / "proj"
    (proj / ".claude" / "agents").mkdir(parents=True)
    (proj / ".git").mkdir()
    monkeypatch.chdir(proj)
    sys.path.insert(0, str(cfg / "hooks"))
    sys.modules.pop("agent_guard", None)
    import agent_guard as g
    yield SimpleNamespace(g=g, cfg=cfg, proj=proj, ev={"cwd": str(proj)})
    sys.path.remove(str(cfg / "hooks"))
    sys.modules.pop("agent_guard", None)


@pytest.mark.parametrize("cmd,kind", [("stack-run -- git push origin main", "push"),
                                      ("stack-run --name man -- git push", "push"),
                                      ("x/bin/stack-run --tail 3 --grep=e -- gh pr create --fill", "forge"),
                                      ("stack-run -- $(echo git) push", "opaque")])
def test_guard_no_push_sees_the_wrapped_command(guard, cmd, kind):
    got = guard.g.remote_write_in(cmd)
    assert got and got[0] == kind, got


@pytest.mark.parametrize("form", ["stack-run -- {w}", "stack-run --name x --tail 3 --grep=e -- {w}",
                                  "{cfg}/bin/stack-run --grep x -- {w}", "timeout 9 stack-run -- {w}",
                                  "/usr/bin/python3 -B {cfg}/bin/stack-run -- {w}", "stack-run -- stack-run -- {w}",
                                  "xargs stack-run -- {w}"])
@pytest.mark.parametrize("w", ["cp new.py {cfg}/hooks/agent_guard.py", "rm -rf {cfg}/hooks"])
def test_guard_protected_paths_see_the_wrapped_command(guard, form, w):
    cmd = form.format(w=w, cfg=guard.cfg).format(cfg=guard.cfg)
    got = guard.g.protected_write_in(cmd, guard.ev)
    assert got and got[0] == "protect", cmd


def test_guard_wrapped_ordinary_commands_pass(guard):
    for cmd in ("stack-run -- rm -rf build", "stack-run --grep FAIL -- uv run pytest -q",
                "stack-run --name 'cp' -- make test", "stack-run --name x", "stack-run --name git-log"):
        assert guard.g.protected_write_in(cmd, guard.ev) is None, cmd
        assert guard.g.remote_write_in(cmd) is None, cmd


def test_guard_secrets_see_the_wrapped_command(guard):
    got = guard.g.secrets_leak_in("stack-run --tail 1 -- mcp-headers --reveal exa", guard.ev)
    assert got and got[0] == "secrets"


@pytest.mark.parametrize("cmd,web", [("stack-run -- curl https://example.com", True),
                                     ("stack-run --name x --grep y -- wget u", True),
                                     ("python3 /c/bin/stack-run -- curl u", True),
                                     ("stack-run --name curl -- pytest -q", False),
                                     ("stack-run -- pytest -q", False), ("stack-run --name x", False),
                                     ("stack-run --name curl", False)])
def test_guard_web_check_reads_the_wrapped_command(guard, cmd, web):
    assert guard.g.blackcat_web_command(cmd) is web


@pytest.mark.parametrize("cmd,bad", [("stack-run -- rm -rf build", True),
                                     ("stack-run --name x --tail 5 -- git push", True),
                                     ("stack-run -- git status", False),
                                     ("stack-run --name t --grep=x -- git log -3", False),
                                     ("{cfg}/bin/stack-run --tail 3 -- git status", False),
                                     ("{cfg}/bin/stack-run -- rm -rf build", True)])
def test_guard_read_only_check_reads_the_wrapped_command(guard, cmd, bad):
    cmd = cmd.format(cfg=guard.cfg)
    ev = {"cwd": str(guard.proj), "agent_type": "verifier", "tool_name": "Bash", "tool_input": {"command": cmd}}
    got = guard.g.readonly_violation(cmd, ev)
    assert bool(got) is bad, got
    if got:
        assert "stack-run" not in got[0]                                # judged on the wrapped command


# ---------------------------------------------------------------- review fixes (2026-10-08): S1-S4, R2
@pytest.mark.parametrize("cmd", ["STACK_HOOKS_DIR=./.claude-work/p stack-run -- git status",
                                 "env STACK_HOOKS_DIR=./.claude-work/p stack-run -- git status",
                                 "export STACK_HOOKS_DIR=./.claude-work/p; stack-run -- git status"])
def test_guard_read_only_refuses_a_hooks_dir_for_stack_run(guard, cmd):
    """S1: a reviewer could plant .claude-work/p/output_shrink.py and have stack-run import it."""
    ev = {"cwd": str(guard.proj), "agent_type": "verifier", "tool_name": "Bash", "tool_input": {"command": cmd}}
    got = guard.g.readonly_violation(cmd, ev)
    assert got and "STACK_HOOKS_DIR" in got[1], got


@pytest.mark.parametrize("cmd", ["ls {cfg}/hooks/agent_guard.py | xargs stack-run -- rm",
                                 "echo {cfg}/hooks | xargs -n1 stack-run --name x -- rm -rf",
                                 "echo {cfg} | xargs stack-run -- rm -rf"])
def test_guard_protected_paths_see_xargs_into_stack_run(guard, cmd):
    """S2: the operands come from stdin, as for `... | xargs rm`."""
    got = guard.g.protected_write_in(cmd.format(cfg=guard.cfg), guard.ev)
    assert got and got[0] == "protect", got


@pytest.mark.parametrize("tail", ["", " -- true"])
def test_guard_web_check_keeps_inline_code_before_stack_run(guard, tail):
    """S3: inline interpreter code that names a client is still read when stack-run follows it."""
    assert guard.g.blackcat_web_command("perl -e 'system+q[curl],q[https://example.com]' stack-run" + tail) is True
    assert guard.g.blackcat_web_command("python3 -B /c/bin/stack-run --" + (tail or " curl u")) is (not tail)


def test_a_long_word_line_is_masked_in_bounded_time(sr):
    """S4: the credential patterns backtrack quadratically on one long word; a 1 MiB line is masked
    in windows, in linear time."""
    t0 = time.monotonic()
    p = sr.run(*py("import sys; sys.stdout.write('pass' * 2 ** 18 + '\\n')"), timeout=90)
    assert time.monotonic() - t0 < 30
    status, _, lines, log = head(p)
    assert (status, lines) == ("PASS", 1) and log.stat().st_size > 2 ** 20
    code = "print('x' * 3580 + ' token ' + %r + ' ' + 'y' * 9000 + ' aws ' + %r)" % (GHP, AKIA)
    data = head(sr.run(*py(code)))[3].read_text()
    assert GHP not in data and AKIA not in data and data.startswith("x" * 3580 + " ***")


def test_log_keeps_its_first_log_max_bytes(sr):
    """R2: a log stops at LOG_MAX (patched to 1 MiB here); lines= and the selection see every line."""
    f = sr.c / "bin" / "stack-run"
    f.write_text(f.read_text().replace("LOG_MAX = 256 << 20", "LOG_MAX = 1 << 20"))
    p = sr.run(*py("import sys\nsys.stdout.write('y\\n' * 2500000)\nprint('error: last')\nsys.exit(1)"))
    status, _, lines, log = head(p)
    assert (status, lines) == ("FAIL", 2500001) and (2500001, "error: last") in shown(p)
    assert 2 ** 20 - 2 <= log.stat().st_size <= 2 ** 20 + 200
    assert log.read_text().split("\n")[-2].startswith("... [stack-run: the log stops here")
    assert "size cap reached" in p.err


def test_each_run_prunes_old_and_excess_logs_of_its_own(sr):
    """R2: this tool's logs older than 7 days go, then the oldest past the cap (patched to 5,000
    bytes); other files stay."""
    f = sr.c / "bin" / "stack-run"
    f.write_text(f.read_text().replace("RUNS_AGE_S, RUNS_MAX = 7 * 86400, 1 << 30", "RUNS_AGE_S, RUNS_MAX = 7 * 86400, 5000"))
    d = runs_dir(sr)
    d.mkdir(parents=True, mode=0o700)
    now = time.time()
    files = {"old-20200101-000000.log": (now - 8 * 86400, 10), "a-20261001-000000.log": (now - 3000, 2000),
             "b-20261001-000001-3.log": (now - 2000, 2000), "c-20261001-000002.log": (now - 1000, 2000),
             "mine-20200101-000000.txt": (now - 9 * 86400, 10), "notes.log": (now - 9 * 86400, 10)}
    for name, (t, size) in files.items():
        (d / name).write_text("z" * size)
        os.utime(d / name, (t, t))
    (d / "link-20200101-000000.log").symlink_to(sr.tmp / "nowhere")
    log = head(sr.run(*py("print(1)")))[3]
    left = sorted(x.name for x in d.iterdir())
    assert left == sorted([".gitignore", "b-20261001-000001-3.log", "c-20261001-000002.log", "mine-20200101-000000.txt",
                           "notes.log", "link-20200101-000000.log", log.name])
