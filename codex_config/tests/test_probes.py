"""probes/run.sh: syntax, --list, --dry-run isolation, refusal of the real ~/.codex, a real-mode run against the
fake codex (valid JSON report) and the P12 file checks. Never a real codex (the fake only answers --version)."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from pathlib import Path

import pytest

RUN = Path(__file__).resolve().parents[1] / "probes" / "run.sh"
IDS = ["P1", "P2", "P3", "P4", "P5", "P6", "P7", "P7b", "P8", "P9", "P10", "P11", "P12", "P13"]


def snapshot(root: Path):
    out = {}
    for p in sorted(root.rglob("*")):
        rel = str(p.relative_to(root))
        out[rel] = (p.is_symlink(), None if p.is_dir() or p.is_symlink() else p.read_bytes())
    return out


def run(args, scratch_home, tmp_path, stdin="", env_extra=None, codex_home=None):
    tmp = tmp_path / "tmpdir"
    tmp.mkdir(exist_ok=True)
    env = dict(os.environ, TMPDIR=str(tmp), FAKE_CODEX_LOG=str(tmp_path / "codex.log"))
    env.pop("CODEX_HOME", None)      # the fixture points it at the (refused) ~/.codex
    if codex_home is not None:
        env["CODEX_HOME"] = str(codex_home)
    env.update(env_extra or {})
    r = subprocess.run(["bash", str(RUN)] + args, input=stdin, capture_output=True, text=True, env=env)
    return r, tmp


def test_bash_syntax():
    assert subprocess.run(["bash", "-n", str(RUN)]).returncode == 0
    assert subprocess.run(["bash", "-n", str(RUN.parent / "fixtures" / "hooklog.sh")]).returncode == 0


def test_list_names_all_ids(scratch_home, tmp_path):
    r, _ = run(["--list"], scratch_home, tmp_path)
    assert r.returncode == 0
    got = [ln.split()[0] for ln in r.stdout.splitlines() if ln.strip()]
    assert got == IDS


def test_dry_run_writes_only_in_removed_temp_dir(scratch_home, tmp_path):
    before = snapshot(scratch_home["home"])
    r, tmp = run(["--dry-run"], scratch_home, tmp_path)
    assert r.returncode == 0, r.stderr
    assert snapshot(scratch_home["home"]) == before            # scratch HOME, ~/.codex, ~/.agents untouched
    assert list(tmp.iterdir()) == []                             # temp dir removed
    assert "write: " in r.stdout and "codex login" in r.stdout and "/hooks" in r.stdout
    for pid in IDS:
        assert "== %s:" % pid in r.stdout
    log = (tmp_path / "codex.log").read_text().split("\n") if (tmp_path / "codex.log").exists() else []
    assert [ln for ln in log if ln] == ["--version"]            # no codex subcommand beyond --version


@pytest.mark.parametrize("target", [".codex", ".agents", ""])
def test_refuses_protected_codex_home(scratch_home, tmp_path, target):
    home = scratch_home["home"]
    path = home / target if target else home
    r, tmp = run(["--dry-run"], scratch_home, tmp_path, codex_home=path)
    assert r.returncode == 3 and "refusing" in r.stderr
    assert list(tmp.iterdir()) == []


def test_refuses_nonempty_dir(scratch_home, tmp_path):
    d = tmp_path / "mine"
    d.mkdir()
    (d / "x").write_text("keep")
    r, _ = run(["--dry-run"], scratch_home, tmp_path, codex_home=d)
    assert r.returncode == 3
    assert (d / "x").read_text() == "keep"


def test_real_mode_without_answers_gives_valid_report(scratch_home, tmp_path):
    r, tmp = run([], scratch_home, tmp_path, stdin="")
    assert r.returncode == 0, r.stderr
    report = Path([ln.split("Report: ", 1)[1] for ln in r.stdout.splitlines() if ln.startswith("Report: ")][0])
    data = json.loads(report.read_text())
    assert list(data["probes"]) == IDS
    for v in data["probes"].values():
        assert v["result"] in ("pass", "fail", "unknown") and "evidence" in v and "notes" in v
    assert data["meta"]["codex_version"].startswith("codex-cli")
    assert not (scratch_home["codex_home"] / "config.toml").exists()   # the real(-looking) ~/.codex untouched
    for ln in (tmp_path / "codex.log").read_text().splitlines():
        assert ln == "--version"


def test_p12_detects_codex_style_writes(scratch_home, tmp_path):
    """Drive run.sh --probe P12 and play Codex: append trust and model keys outside the regions."""
    tmp = tmp_path / "tmpdir"
    tmp.mkdir()
    env = dict(os.environ, TMPDIR=str(tmp), FAKE_CODEX_LOG=str(tmp_path / "codex.log"))
    env.pop("CODEX_HOME", None)
    p = subprocess.Popen(["bash", str(RUN), "--probe", "P12"], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                         stderr=subprocess.STDOUT, text=True, env=env)
    p.stdin.write("\n")                      # login prompt
    p.stdin.flush()
    out = []
    cfg = None
    for line in p.stdout:
        out.append(line)
        if "config.toml (stack regions" in line:
            cfg = Path(line.split("write: ", 1)[1].split(" (stack", 1)[0])
            text = cfg.read_text()
            cfg.write_text(text + '\nmodel = "x"\n[hooks.state."k"]\ntrusted_hash = "sha256:00"\nenabled = true\n'
                           '[projects."/w"]\ntrust_level = "trusted"\n')
            p.stdin.write("\n")
            p.stdin.flush()
            break
    rest = p.communicate(timeout=60)[0]
    text = "".join(out) + rest
    assert p.returncode == 0, text
    assert "=> P12: pass" in text, text
    # a Codex that drops the comments must be reported as fail
    p = subprocess.Popen(["bash", str(RUN), "--probe", "P12"], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                         stderr=subprocess.STDOUT, text=True, env=env)
    p.stdin.write("\n")
    p.stdin.flush()
    for line in p.stdout:
        if "config.toml (stack regions" in line:
            cfg = Path(line.split("write: ", 1)[1].split(" (stack", 1)[0])
            kept = [ln for ln in cfg.read_text().splitlines() if not ln.startswith("# user comment")]
            cfg.write_text("\n".join(kept) + '\nmodel = "x"\n')
            p.stdin.write("\n")
            p.stdin.flush()
            break
    rest = p.communicate(timeout=60)[0]
    assert "=> P12: fail" in rest, rest


def test_hooklog_script_records_stdin_and_meta(tmp_path):
    root = tmp_path / "root"
    ch = tmp_path / "ch"
    (ch).mkdir()
    src = (RUN.parent / "fixtures" / "hooklog.sh").read_text().replace("@ROOT@", str(root)).replace("@CODEX_HOME@", str(ch))
    script = tmp_path / "hooklog.sh"
    script.write_text(src)
    r = subprocess.run(["/bin/sh", str(script), "PreToolUse", "$X"], input='{"tool_name":"Bash",\n"agent_type":"a-b"}',
                       capture_output=True, text=True)
    assert r.returncode == 0 and r.stdout == ""
    lines = (root / "logs" / "hooks.jsonl").read_text().splitlines()
    assert lines[0].startswith("#meta event=PreToolUse argc=2 arg2=$X write_outside=ok read_auth=fail")
    assert lines[1].startswith("PreToolUse\t") and '"agent_type":"a-b"' in lines[1]
