"""Bayes WP3c wiring (docs/BAYES.md §2.9, §3.1): the opt-in `install.sh --with-bayes`, the hash-locked
requirements/tools-bayes.txt, doctor.sh's `bayes:` line and STACK_BAYES among the guard's FIXED_LIMIT_KNOBS.
Nothing here installs a package or touches the stack's state: fake venvs and scratch dirs under tmp_path.

Run: ~/.claude/venvs/tools/bin/python -m pytest -q tests/test_bayes_wiring.py
"""
import ast
import importlib.util
import json
import os
import re
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
REQ = ROOT / "requirements"
INSTALL = ROOT / "install.sh"
DOCTOR = ROOT / "dot-config" / "dot-claude" / "bin" / "doctor.sh"
HOOKS = ROOT / "dot-config" / "dot-claude" / "hooks"
PROTO_LOCK = ROOT / "docs" / "bayes" / "b1v2" / "fit_prototype.py.lock"
HPY = "/usr/bin/python3" if os.path.exists("/usr/bin/python3") else sys.executable
FITTER = ("pymc", "pytensor", "nutpie", "arviz", "scipy", "numpy")      # stack_bayes.DEPS (a test checks)
# Pins that differ from the prototype's lock, with the reason (requirements/tools-bayes.in)
PROTO_EXCEPTIONS = {"pytensor": "3.3.2"}     # 3.3.3 was published 2026-10-02T14:13Z, inside the cooldown
HASHED = re.compile(r"(?m)^([A-Za-z0-9][A-Za-z0-9._-]*)==(\S+) \\\n((?:\s+--hash=sha256:[0-9a-f]{64}.*\n)+)")
norm = lambda n: re.sub(r"[-_.]+", "-", n).lower()  # noqa: E731


def _tis():
    spec = importlib.util.spec_from_file_location("_tis_bw", ROOT / "tests" / "test_install_state.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------- flag parsing: install.sh --with-bayes
def test_with_bayes_is_a_known_option(tmp_path):
    """--with-bayes parses (the run stops at the next usage error, --force without --restore, instead of at
    "unknown option"), writing nothing."""
    home = tmp_path / "home"
    home.mkdir()
    env = {"PATH": "/usr/bin:/bin", "HOME": str(home), "CLAUDE_CONFIG_DIR": str(home / ".claude"),
           "TMPDIR": str(tmp_path)}
    p = subprocess.run([str(INSTALL), "--with-bayes", "--force"], env=env, stdin=subprocess.DEVNULL,
                       capture_output=True, text=True, timeout=60, check=False)
    out = p.stdout + p.stderr
    assert p.returncode == 2 and "unknown option" not in out, out[-500:]
    assert "--force works only with --restore" in out
    assert not any(home.iterdir()) and sorted(os.listdir(tmp_path)) == ["home"]


@pytest.mark.skipif(not (ROOT / ".git").exists(), reason="needs the stack's git checkout")
def test_with_bayes_points_the_tools_venv_at_the_bayes_lock_and_only_then(tmp_path):
    """A dry run with --no-deps names the lock the tools venv would come from: tools-bayes.txt with
    --with-bayes (plus the line that --no-deps skips it), tools.txt without; nothing is written."""
    tis = _tis()
    repo = tis._scratch_repo(str(tmp_path / "repo"))
    outs = {}
    for flag in ([], ["--with-bayes"]):
        home = tmp_path / ("home" + "".join(flag))
        home.mkdir()
        p = tis._run_install(repo, str(home), str(home / ".claude"),
                             argv=["--dry-run", "--no-deps", "--no-profile", "--no-mcp", "--no-plugins", *flag])
        assert p.returncode == 0, (p.stdout[-1500:], p.stderr[-1500:])
        outs[bool(flag)] = p.stdout + p.stderr
        written = sorted(str(q.relative_to(home)) for q in home.rglob("*")
                         if q.relative_to(home).parts[0] not in ("shim", "tmp"))
        assert written == [], written
    assert "-r requirements/tools-bayes.txt" in outs[True], outs[True][-3000:]
    assert "--with-bayes needs uv and is skipped under --no-deps" in outs[True]
    assert "-r requirements/tools.txt" in outs[False] and "tools-bayes" not in outs[False]


def _fake_venv(conf, dists):
    """conf/venvs/tools: a venv of the hooks' python with no pip, holding only dist-info metadata."""
    venv = conf / "venvs" / "tools"
    if not venv.exists():
        subprocess.run([HPY, "-m", "venv", "--without-pip", str(venv)], check=True, capture_output=True)
    site = next(venv.glob("lib/python3*/site-packages"))
    for d in site.glob("*.dist-info"):
        for f in d.iterdir():
            f.unlink()
        d.rmdir()
    for name, ver in dists.items():
        d = site / f"{name}-{ver}.dist-info"
        d.mkdir()
        (d / "METADATA").write_text(f"Metadata-Version: 2.1\nName: {name}\nVersion: {ver}\n")
    return venv


ALL = {"pymc": "6.3.2", "pytensor": "3.3.2", "nutpie": "0.16.11", "arviz": "1.3.0", "scipy": "1.18.1",
       "numpy": "2.5.3"}


def test_install_reports_the_bayes_packages_it_finds(tmp_path):
    """The step after the tools venv sync: --with-bayes names the installed versions; a plain run says
    nothing without pymc and names an earlier --with-bayes's packages when they are there."""
    text = INSTALL.read_text()
    fn = re.search(r"(?ms)^bayes_dists\(\)\{\n.*?^\}\n", text).group(0)
    body = re.search(r'(?ms)^    bd="\$\(bayes_dists\)"\n.*?^    fi\n', text).group(0)
    conf = tmp_path / "conf"

    def run(with_bayes):
        script = 'note(){ printf "NOTE %s\\n" "$*"; }\n' + fn + body
        p = subprocess.run(["/bin/bash", "-c", script], capture_output=True, text=True, timeout=60,
                           env={"PATH": "/usr/bin:/bin", "C": str(conf), "WITH_BAYES": str(with_bayes),
                                "TMPDIR": str(tmp_path)})
        assert p.returncode == 0, p.stderr
        return p.stdout

    _fake_venv(conf, {"numpy": "2.5.3"})
    assert run(0) == ""
    assert "Bayes lock in the tools venv" in run(1) and "pymc - pytensor - nutpie - arviz -" in run(1)
    _fake_venv(conf, ALL)
    assert "NOTE Bayes lock in the tools venv (shadow only; STACK_BAYES=off stops the fits): " \
           "pymc 6.3.2 pytensor 3.3.2 nutpie 0.16.11 arviz 1.3.0" in run(1)
    out = run(0)
    assert "Bayes packages from an earlier --with-bayes stay in the tools venv" in out
    assert "(pymc 6.3.2 pytensor 3.3.2 nutpie 0.16.11 arviz 1.3.0; ./install.sh --with-bayes" in out


# ---------------------------------------------------------------- lock verification: tools-bayes.txt
def _pins(text, hashes=False):
    """{name: version}, or {name: (version, sorted sha256s)} with hashes=True."""
    if hashes:
        return {norm(n): (v, sorted(re.findall(r"--hash=sha256:([0-9a-f]{64})", h))) for n, v, h in HASHED.findall(text)}
    return {norm(n): v for n, v, _h in HASHED.findall(text)}


# The only lines a hash lock may hold besides comments and blanks: a pinned name and its sha256 lines. Anything
# else (-i/--index-url, --extra-index-url, --trusted-host, -f/--find-links, --no-index, --no-binary, -e, -r/-c,
# a URL, a VCS or path requirement, an environment marker) would change where or what pip/uv installs.
LOCK_LINE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*==[A-Za-z0-9.+!-]+ \\|    --hash=sha256:[0-9a-f]{64}( \\)?")


def _foreign_lines(text):
    return [ln for ln in text.splitlines() if ln.strip() and not ln.lstrip().startswith("#")
            and not LOCK_LINE.fullmatch(ln)]


def test_bayes_lock_is_hashed_and_compiled_with_the_tools_command():
    txt = (REQ / "tools-bayes.txt").read_text()
    cmd = txt.splitlines()[1]
    assert cmd.startswith("#    uv pip compile requirements/tools-bayes.in "), cmd
    for flag in ("-c requirements/tools.txt", "-o requirements/tools-bayes.txt", "--generate-hashes",
                 "--python-version 3.13", "--python-platform aarch64-apple-darwin", "--only-binary :all:"):
        assert flag in cmd, flag
    cut = re.search(r"--exclude-newer (\S+)", cmd).group(1)
    base = re.search(r"--exclude-newer (\S+)", (REQ / "tools.txt").read_text().splitlines()[1]).group(1)
    assert re.fullmatch(r"\d{4}-\d\d-\d\dT00:00:00Z", cut) and cut >= base, (cut, base)
    # every pin carries hashes (no unhashed line that --require-hashes would refuse at install)
    assert len(HASHED.findall(txt)) == len(re.findall(r"(?m)^[A-Za-z0-9][A-Za-z0-9._-]*==", txt)) > 0
    assert "--hash=sha256:" in txt and _foreign_lines(txt) == []


@pytest.mark.parametrize("line", ["--trusted-host evil.example", "-i https://evil.example/simple",
                                  "--index-url https://evil.example/simple", "--extra-index-url https://x.example",
                                  "--find-links /tmp/w", "-f /tmp/w", "--no-index", "--no-binary :all:",
                                  "-e ./pkg", "-r other.txt", "pymc @ https://evil.example/pymc.whl",
                                  "git+https://evil.example/pymc", "./pymc-6.3.2.whl",
                                  'pymc==6.3.2 ; sys_platform == "linux" \\'])
def test_lock_line_allowlist_refuses_install_source_changes(line):
    txt = (REQ / "tools-bayes.txt").read_text()
    assert _foreign_lines(txt) == []
    assert _foreign_lines(txt.replace("\naiosqlite==", "\n" + line + "\naiosqlite==", 1)) == [line]


def test_bayes_lock_keeps_the_base_pins_and_the_inputs_pins():
    """Every tools.txt package with the same version (a plain install, which syncs tools.txt into the same
    venv, changes none of them), and every == pin of tools-bayes.in as written."""
    bayes = _pins((REQ / "tools-bayes.txt").read_text())
    base = _pins((REQ / "tools.txt").read_text())
    assert base and {k: (v, bayes.get(k)) for k, v in base.items() if bayes.get(k) != v} == {}
    # and the same files: every shared package carries exactly tools.txt's sha256 set
    bh, th = (_pins((REQ / f).read_text(), hashes=True) for f in ("tools-bayes.txt", "tools.txt"))
    assert {k: v for k, v in th.items() if bh.get(k) != v} == {}
    tin = (REQ / "tools-bayes.in").read_text()
    want = {norm(n): v for n, v in re.findall(r"(?m)^([A-Za-z0-9][A-Za-z0-9._-]*)==(\S+)", tin)}
    assert set(want) >= set(FITTER) - {"numpy"}
    assert {k: (v, bayes.get(k)) for k, v in want.items() if bayes.get(k) != v} == {}
    assert tin.count("\n-r tools.in\n") == 1


def test_fitter_is_stack_bayes_deps():
    m = re.search(r"(?m)^DEPS = (\(.*\))$", (HOOKS / "stack_bayes.py").read_text())
    assert m and set(ast.literal_eval(m.group(1))) == set(FITTER)


def test_bayes_lock_matches_the_prototype_lock_but_for_named_exceptions():
    proto = {norm(p["name"]): p["version"] for p in tomllib.loads(PROTO_LOCK.read_text())["package"]}
    bayes = _pins((REQ / "tools-bayes.txt").read_text())
    got = {d: bayes.get(d) for d in FITTER}
    assert got == {d: PROTO_EXCEPTIONS.get(d, proto[d]) for d in FITTER}, got
    assert all(proto[d] != v for d, v in PROTO_EXCEPTIONS.items())     # an exception that is no longer one goes


# ---------------------------------------------------------------- doctor.sh: the bayes line
def _doctor_block():
    text = DOCTOR.read_text()
    m = re.search(r"(?ms)^# >>> bayes line.*?^# <<< bayes line\n", text)
    assert m and text.count("\nbayes_line\n") == 1
    assert text.index('ok "ML venv ($C/venvs/ml)"') < m.start() < text.index("for f in with-stack-env")
    return m.group(0)


def _doctor(tmp_path, conf, mode=None):
    script = ('ok(){ printf "  ok    %s\\n" "$*"; }\nwarn(){ printf "  WARN  %s\\n" "$*"; }\n'
              'fail(){ printf "  FAIL  %s\\n" "$*"; }\n'
              'python3(){ command ' + sys.executable + ' -I -B "$@"; }\n' + _doctor_block())
    env = {"PATH": "/usr/bin:/bin", "HOME": str(tmp_path / "home"), "C": str(conf),
           "XDG_STATE_HOME": str(tmp_path / "state"), "TMPDIR": str(tmp_path)}
    if mode is not None:
        env["STACK_BAYES"] = mode
    p = subprocess.run(["/bin/bash", "-c", script], env=env, capture_output=True, text=True, timeout=60)
    assert p.returncode == 0 and p.stderr == "" and "FAIL" not in p.stdout, (p.stdout, p.stderr)
    lines = p.stdout.splitlines()
    assert len(lines) == 1, lines
    return lines[0]


def test_doctor_bayes_line_never_fails_when_the_extra_is_absent(tmp_path):
    conf = tmp_path / "conf"
    conf.mkdir()
    assert _doctor(tmp_path, conf).startswith("  ok    bayes: venv missing (no tools venv")
    _fake_venv(conf, {"numpy": "2.5.3", "pandas": "3.0.6"})
    assert _doctor(tmp_path, conf).startswith("  ok    bayes: venv missing (optional: ./install.sh --with-bayes")
    _fake_venv(conf, {"numpy": "2.5.3", "pymc": "6.3.2"})
    line = _doctor(tmp_path, conf)
    assert line.startswith("  WARN  bayes: venv incomplete (pymc 6.3.2, pytensor -, nutpie -,"), line
    assert line.endswith("rerun ./install.sh --with-bayes")


def test_doctor_bayes_line_reports_versions_mode_and_the_last_fit(tmp_path):
    conf = tmp_path / "conf"
    _fake_venv(conf, ALL)
    head = ("  ok    bayes: venv ok (pymc 6.3.2, pytensor 3.3.2, nutpie 0.16.11, arviz 1.3.0, scipy 1.18.1, "
            "numpy 2.5.3; STACK_BAYES=")
    assert _doctor(tmp_path, conf) == head + "shadow; last fit: none yet)"
    assert _doctor(tmp_path, conf, "bogus") == head + "shadow; last fit: none yet)"
    assert _doctor(tmp_path, conf, "On") == head + "on; last fit: none yet)"
    rec = tmp_path / "state" / "claude-agent-stack" / "usage" / "bayes.json.rec"
    rec.parent.mkdir(parents=True)
    rec.write_text(json.dumps({"status": "ok"}) + "\n" + json.dumps({"status": "failed:exit -9"}) + "\n{broken\n")
    assert _doctor(tmp_path, conf).endswith("last fit: failed:exit -9)")
    rec.write_text(json.dumps({"status": "ok\x1b]0;pwned\x07"}) + "\n")
    assert _doctor(tmp_path, conf).endswith("last fit: unreadable)")
    rec.write_text("[1, 2]\n")
    assert _doctor(tmp_path, conf).endswith("last fit: none yet)")
    rec.unlink()
    rec.mkdir()                                     # there but unreadable: not "none yet"
    assert _doctor(tmp_path, conf).endswith("last fit: unreadable)")
    rec.rmdir()
    rec.write_text("[" * 200000 + "]" * 200000 + "\n")    # RecursionError: skipped, no traceback (stderr == "")
    assert _doctor(tmp_path, conf).endswith("last fit: none yet)")


@pytest.mark.parametrize("mode", ["off", " OFF ", "Off"])
def test_doctor_bayes_line_skipped_when_off(tmp_path, mode):
    conf = tmp_path / "conf"
    _fake_venv(conf, ALL)
    assert _doctor(tmp_path, conf, mode).startswith("  ok    bayes: skipped (STACK_BAYES=off")


# ---------------------------------------------------------------- knobs: STACK_BAYES in FIXED_LIMIT_KNOBS
def _guard(tmp_path, drop):
    code = ("import json, sys; sys.path.insert(0, sys.argv[1]); import agent_guard as g\n"
            "if sys.argv[2] == 'drop':\n"
            "    g.FIXED_LIMIT_KNOBS = tuple(k for k in g.FIXED_LIMIT_KNOBS if k != 'STACK_BAYES')\n"
            "print(json.dumps({'listed': 'STACK_BAYES' in g.FIXED_LIMIT_KNOBS,\n"
            "                  'problems': [p for p in g.limits_self_test(None) if p.startswith('limits:')]}))\n")
    env = {k: v for k, v in os.environ.items() if not k.startswith(("STACK_", "CLAUDE_"))}
    env.update(XDG_STATE_HOME=str(tmp_path / "st"), PYTHONDONTWRITEBYTECODE="1")
    p = subprocess.run([HPY, "-I", "-c", code, str(HOOKS), "drop" if drop else "keep"], env=env,
                       capture_output=True, text=True, timeout=120)
    assert p.returncode == 0, p.stderr[-2000:]
    return json.loads(p.stdout.splitlines()[-1])


def test_stack_bayes_is_a_fixed_limit_knob_and_the_self_test_holds_it(tmp_path):
    ok = _guard(tmp_path, drop=False)
    assert ok == {"listed": True, "problems": []}, ok
    bad = _guard(tmp_path, drop=True)
    assert not bad["listed"]
    assert "limits: fixed STACK_* guards of stack_limits not in FIXED_LIMIT_KNOBS: STACK_BAYES" in bad["problems"]


def test_config_knob_row_for_stack_bayes():
    text = (ROOT / "CONFIG.md").read_text()
    section = text.split("\n## 5. Guard knobs and settings\n", 1)[1].split("\n### ", 1)[0]
    row = [ln for ln in section.splitlines() if ln.startswith("| `STACK_BAYES` |")]
    assert len(row) == 1 and "| `shadow` (code" in row[0] and "--with-bayes" in row[0], row
    assert "STACK_BAYES" not in json.loads((ROOT / "dot-config" / "dot-claude" / "settings.json").read_text())["env"]
