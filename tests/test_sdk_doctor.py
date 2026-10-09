"""doctor.sh's sdk line (SDK-3): `sdk: pin X, lock ok, uv ok, cli system vA / bundled vB`, run as its block alone.

bin/stack_sdk.py is optional, so the line never FAILs: a missing or stale lock, no uv or no pin WARNs. Fakes stand in
for uv and claude (argv recorded); one test runs the real uv's offline lock check on the repo's helper and lock.

Run: uv run --with pytest pytest -q tests/test_sdk_doctor.py
SDK_DOCTOR=/path/to/doctor.sh points them at another copy (mutation runs)."""
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
BIN = ROOT / "dot-config" / "dot-claude" / "bin"
DOCTOR = Path(os.environ.get("SDK_DOCTOR") or BIN / "doctor.sh")
PIN = re.search(r'claude-agent-sdk==([0-9.]+)"', (BIN / "stack_sdk.py").read_text()).group(1)


def block():
    text = DOCTOR.read_text()
    m = re.search(r"(?ms)^# >>> sdk line.*?^# <<< sdk line\n", text)
    assert m and text.count("\nsdk_line\n") == 1
    assert text.index("# <<< bayes line") < m.start() < text.index("for f in with-stack-env")
    return m.group(0)


def conf_with(tmp_path, lock=True, pin=PIN):
    conf = tmp_path / "conf"
    (conf / "bin").mkdir(parents=True)
    (conf / "bin" / "stack_sdk.py").write_text((BIN / "stack_sdk.py").read_text().replace(PIN, pin, 1))
    if lock:
        (conf / "bin" / "stack_sdk.py.lock").write_bytes((BIN / "stack_sdk.py.lock").read_bytes())
    return conf


def fake_bin(tmp_path, lock_rc=0, env_python="", claude="2.1.287 (Claude Code)"):
    b = tmp_path / "fakebin"
    b.mkdir(exist_ok=True)
    log = tmp_path / "argv.log"
    (b / "uv").write_text('#!/bin/sh\necho "uv $*" >> "%s"\ncase "$1 $2" in\n  "lock --script") exit %d ;;\n'
                          '  "python find") [ -n "%s" ] && echo "%s"; exit 0 ;;\nesac\nexit 9\n'
                          % (log, lock_rc, env_python, env_python))
    (b / "claude").write_text('#!/bin/sh\necho "%s"\n' % claude)
    for f in ("uv", "claude"):
        os.chmod(b / f, 0o755)
    return b, log


def fake_env(tmp_path, sdk="0.2.163", cli="2.1.286"):
    """A uv-style script environment (…/environments-v2/<name>/bin/python: a venv over this interpreter) holding a
    stub claude_agent_sdk whose package must never be imported (its __init__ raises)."""
    env = tmp_path / "cache" / "environments-v2" / "stack-sdk-0123456789abcdef"
    (env / "bin").mkdir(parents=True)
    os.symlink(os.path.realpath(sys.executable), env / "bin" / "python")
    (env / "pyvenv.cfg").write_text("home = %s\ninclude-system-site-packages = false\n"
                                    % os.path.dirname(os.path.realpath(sys.executable)))
    sp = env / "lib" / ("python%d.%d" % sys.version_info[:2]) / "site-packages"
    pkg = sp / "claude_agent_sdk"
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text("raise SystemExit('imported')\n")
    (pkg / "_cli_version.py").write_text('"""Bundled Claude Code CLI version."""\n\n__cli_version__ = "%s"\n' % cli)
    dist = sp / ("claude_agent_sdk-%s.dist-info" % sdk)
    dist.mkdir()
    (dist / "METADATA").write_text("Metadata-Version: 2.1\nName: claude-agent-sdk\nVersion: %s\n" % sdk)
    return str(env / "bin" / "python")


def doctor(tmp_path, conf, path):
    script = ('ok(){ printf "  ok    %s\\n" "$*"; }\nwarn(){ printf "  WARN  %s\\n" "$*"; }\n'
              'fail(){ printf "  FAIL  %s\\n" "$*"; }\n' + block())
    env = {"PATH": "%s:/usr/bin:/bin" % path, "HOME": str(tmp_path / "home"), "C": str(conf), "TMPDIR": str(tmp_path)}
    for k in ("UV_CACHE_DIR", "UV_PYTHON_INSTALL_DIR"):
        if os.environ.get(k):
            env[k] = os.environ[k]
    p = subprocess.run(["/bin/bash", "-c", script], env=env, capture_output=True, text=True, timeout=120)
    assert p.returncode == 0 and p.stderr == "" and "FAIL" not in p.stdout, (p.stdout, p.stderr)
    lines = p.stdout.splitlines()
    assert len(lines) == 1, lines
    return lines[0]


def test_all_present_reads_both_versions_without_importing_the_sdk(tmp_path):
    b, log = fake_bin(tmp_path, env_python=fake_env(tmp_path))
    line = doctor(tmp_path, conf_with(tmp_path), b)
    assert line == "  ok    sdk: pin %s, lock ok, uv ok, cli system v2.1.287 / bundled v2.1.286" % PIN
    argv = log.read_text().splitlines()
    assert all("--offline" in a for a in argv)
    assert any(a.startswith("uv lock --script ") and "--check" in a for a in argv)


def test_a_stale_or_missing_lock_warns(tmp_path):
    b, _ = fake_bin(tmp_path, lock_rc=1)
    line = doctor(tmp_path, conf_with(tmp_path), b)
    assert line.startswith("  WARN  sdk: pin %s, lock stale, uv ok" % PIN) and line.endswith("— rerun install.sh")
    b, log = fake_bin(tmp_path, lock_rc=0)
    line = doctor(tmp_path, conf_with(tmp_path / "x", lock=False), b)
    assert "lock missing" in line and line.startswith("  WARN") and "uv lock" not in log.read_text().split("\n")[-2]


def test_no_environment_yet_and_an_environment_of_another_version(tmp_path):
    b, _ = fake_bin(tmp_path, env_python="/usr/bin/python3")          # uv's answer before the first run
    assert doctor(tmp_path, conf_with(tmp_path), b).endswith("bundled ? (no environment yet: the first run creates it)")
    b, _ = fake_bin(tmp_path, env_python=fake_env(tmp_path / "e", sdk="0.2.160", cli="2.1.270"))
    line = doctor(tmp_path, conf_with(tmp_path / "x"), b)
    assert line.startswith("  ok") and "holds 0.2.160: the next run re-syncs it to %s" % PIN in line
    assert "2.1.270" not in line


def test_no_uv_no_claude_no_helper(tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    assert doctor(tmp_path, conf_with(tmp_path), empty).startswith("  WARN  sdk: pin %s, uv missing" % PIN)
    b, _ = fake_bin(tmp_path, env_python=fake_env(tmp_path))
    os.unlink(b / "claude")
    assert "cli system none on PATH (Session needs it)" in doctor(tmp_path, conf_with(tmp_path / "x"), b)
    (tmp_path / "bare" / "bin").mkdir(parents=True)
    assert doctor(tmp_path, tmp_path / "bare", b) == "  WARN  sdk: bin/stack_sdk.py missing — rerun install.sh"


def test_a_helper_without_a_readable_pin_warns(tmp_path):
    b, _ = fake_bin(tmp_path)
    conf = conf_with(tmp_path)
    s = conf / "bin" / "stack_sdk.py"
    s.write_text(s.read_text().replace("claude-agent-sdk==", "claude-agent-sdk>=", 1))
    assert doctor(tmp_path, conf, b).startswith("  WARN  sdk: no claude-agent-sdk==<version> pin")


@pytest.mark.skipif(not shutil.which("uv"), reason="needs uv")
def test_the_real_uv_checks_the_repo_lock_offline(tmp_path):
    uv = os.path.dirname(shutil.which("uv"))
    b, _ = fake_bin(tmp_path)
    os.unlink(b / "uv")
    path = "%s:%s" % (b, uv)
    conf = conf_with(tmp_path)
    lock = (conf / "bin" / "stack_sdk.py.lock").read_bytes()
    assert ", lock ok, uv ok," in doctor(tmp_path, conf, path)
    assert (conf / "bin" / "stack_sdk.py.lock").read_bytes() == lock                 # --check writes nothing
    other = conf_with(tmp_path / "x", pin="0.2.160")
    assert ", lock stale, uv ok," in doctor(tmp_path, other, path)
