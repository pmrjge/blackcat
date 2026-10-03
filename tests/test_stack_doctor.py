"""/stack-doctor = `bin/doctor.sh --hook` on UserPromptExpansion (matcher stack-doctor): the hook
runs the check outside the Bash sandbox and blocks the expansion (exit 2) with a FAIL/WARN summary
on stderr, so no model turn runs and BlackCat needs no Bash."""
import json
import os
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCTOR = ROOT / "dot-claude" / "bin" / "doctor.sh"


def test_hook_mode_blocks_with_a_sorted_summary(tmp_path):
    # a copy in an empty config dir: C is the copy's parent, so most checks FAIL or WARN quickly
    (tmp_path / "bin").mkdir()
    shutil.copy(DOCTOR, tmp_path / "bin" / "doctor.sh")
    ev = {"session_id": "t", "hook_event_name": "UserPromptExpansion", "expansion_type": "slash_command",
          "command_name": "stack-doctor", "command_args": "", "command_source": "userSettings",
          "prompt": "/stack-doctor"}
    p = subprocess.run(["/bin/bash", str(tmp_path / "bin" / "doctor.sh"), "--hook"], input=json.dumps(ev),
                       capture_output=True, text=True, timeout=300)
    assert p.returncode == 2 and p.stdout == ""
    lines = p.stderr.splitlines()
    assert lines[0].startswith("stack-doctor: ") and " FAIL, " in lines[0] and " WARN, " in lines[0]
    body = lines[1:-2]
    kinds = [l.split()[0] for l in body]
    assert kinds and set(kinds) <= {"FAIL", "WARN"} and kinds == sorted(kinds)   # FAIL before WARN
    assert all(l.split()[1].startswith("[") for l in body)                      # each names its section
    assert "FAIL" in kinds                                                      # an empty config dir fails
    assert lines[-2].startswith("healthy: ") and lines[-1].startswith("full report: bash ")


def test_a_hung_check_is_stopped_and_reported(tmp_path):
    # Claude Code drops a hook's output at its timeout: the hook stops doctor.sh itself first
    (tmp_path / "bin").mkdir()
    shutil.copy(DOCTOR, tmp_path / "bin" / "doctor.sh")
    fake = tmp_path / "fakebin"
    fake.mkdir()
    (fake / "claude").write_text("#!/bin/sh\nsleep 120\n")
    (fake / "claude").chmod(0o755)
    env = dict(os.environ, PATH="%s:%s" % (fake, os.environ.get("PATH", "")), STACK_DOCTOR_HOOK_BUDGET="3")
    p = subprocess.run(["/bin/bash", str(tmp_path / "bin" / "doctor.sh"), "--hook"], input="{}",
                       capture_output=True, text=True, timeout=60, env=env)
    assert p.returncode == 2 and p.stdout == ""
    assert "FAIL  [Claude Code] doctor.sh did not finish (stopped after 3 s: a check hung)" in p.stderr
    assert p.stderr.splitlines()[-1].startswith("full report: bash ")
