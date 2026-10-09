"""with-stack-env skips the claude CLI's environment-channel keys in stack.env, with a warning (probe E2a, 2026-10-09):
CLAUDE_CODE_SESSION_KIND=bg with CLAUDE_BG_SESSION_PERMISSION_RULES adds session allow rules; CLAUDE_CODE_SANDBOXED
and CLAUDE_BG_WORKSPACE_TRUSTED are trust switches in the CLI's text.

WITH_STACK_ENV=/path/to/with-stack-env points it at another copy (tests/env_channel_mutations.py).
Run: uv run --no-project --with pytest pytest -q tests/test_with_stack_env.py
"""
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WSE = os.environ.get("WITH_STACK_ENV") or str(ROOT / "dot-config" / "dot-claude" / "bin" / "with-stack-env")
CHANNEL = ["CLAUDE_CODE_SESSION_KIND", "CLAUDE_BG_SESSION_PERMISSION_RULES", "CLAUDE_BG_WORKSPACE_TRUSTED",
           "CLAUDE_CODE_SANDBOXED"]
KEPT = {"CLAUDE_CODE_SESSION_KIND_X": "keep1", "CLAUDE_BGX": "keep2", "HF_TOKEN": "hf_keep3"}
STACK_ENV = ("CLAUDE_CODE_SESSION_KIND=bg\n"
             "export CLAUDE_BG_SESSION_PERMISSION_RULES='{\"allow\":[\"Bash\"]}'\n"
             "  CLAUDE_BG_WORKSPACE_TRUSTED=1  # trust\n"
             "CLAUDE_CODE_SANDBOXED=\"1\"\n" + "".join(f"{k}={v}\n" for k, v in KEPT.items()))


def wse(tmp_path, *args, **env):
    f = tmp_path / "stack.env"
    f.write_text(STACK_ENV)
    e = dict({"PATH": os.environ["PATH"], "HOME": str(tmp_path), "STACK_ENV_FILE": str(f)}, **env)
    return subprocess.run(["sh", WSE, *args], env=e, capture_output=True, text=True, timeout=30, check=False)


def warned(stderr):
    return sorted(k for k in CHANNEL if f"with-stack-env: {k} in stack.env skipped" in stderr)


def test_exec_mode_skips_the_channel_keys_with_a_warning(tmp_path):
    p = wse(tmp_path, "env")
    got = dict(ln.split("=", 1) for ln in p.stdout.splitlines() if "=" in ln)
    assert p.returncode == 0 and not set(CHANNEL) & set(got), p.stdout
    assert {k: got.get(k) for k in KEPT} == KEPT
    assert warned(p.stderr) == sorted(CHANNEL), p.stderr


def test_only_and_print_env_skip_them_too(tmp_path):
    p = wse(tmp_path, "--only", "CLAUDE_CODE_SANDBOXED,CLAUDE_BG_WORKSPACE_TRUSTED,HF_TOKEN", "env")
    got = dict(ln.split("=", 1) for ln in p.stdout.splitlines() if "=" in ln)
    assert got.get("HF_TOKEN") == "hf_keep3" and "CLAUDE_CODE_SANDBOXED" not in got
    assert "CLAUDE_BG_WORKSPACE_TRUSTED" not in got
    p = wse(tmp_path, "--print-env", "sh", "--reveal", STACK_EXPORT="all")
    assert p.returncode == 0 and "export HF_TOKEN='hf_keep3'" in p.stdout and "export CLAUDE_BGX='keep2'" in p.stdout
    assert not [k for k in CHANNEL if f"export {k}=" in p.stdout], p.stdout
    assert warned(p.stderr) == sorted(CHANNEL), p.stderr
