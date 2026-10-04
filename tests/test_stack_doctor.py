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


def agent_files_block():
    """doctor.sh's agent-files check: the python heredoc after `== Agents`."""
    text = DOCTOR.read_text()
    start = text.index("<<'PY'\n", text.index('echo "== Agents"')) + len("<<'PY'\n")
    return text[start:text.index("\nPY\n", start)]


def test_retired_agent_files_are_named_retired_not_your_own(tmp_path):
    # install.sh --no-prune keeps the files of retired agent types: doctor names them retired
    agents = tmp_path / "agents"
    agents.mkdir()
    for a in ("blackcat", "data-engineer", "db-engineer", "localizer", "supreme-coder", "coder-copy",
              "mine"):
        (agents / (a + ".md")).write_text("---\nname: %s\n---\n" % a)
    policy = json.dumps({"agents": ["blackcat", "data-engineer"]})
    p = subprocess.run(["/usr/bin/python3", "-", policy, str(agents)], input=agent_files_block(),
                       capture_output=True, text=True, timeout=30)
    assert p.returncode == 0, p.stderr
    out = p.stdout
    for a in ("db-engineer", "localizer", "supreme-coder", "coder-copy"):
        assert "WARN  agents/%s.md is " % a in out
    assert "data-engineer took its databases" in out and "coder (catalogs) and writer (prose)" in out
    own = [l for l in out.splitlines() if "your own agents" in l]
    assert len(own) == 1 and own[0].rstrip().endswith("mine — run one with `claude --agent <name>`")
