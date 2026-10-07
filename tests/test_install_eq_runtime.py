"""install.sh and doctor.sh for the runtime Equilibrium (docs/RUNTIME_EQUILIBRIUM.md part F): the files
it stages and their modes, the manifest's eq_runtime pin (what eq_policy.load_params accepts), the doctor.sh
section "Equilibrium runtime", settings.json's merge of the eq knobs, allow rules and excludedCommands entry,
their retraction, and --restore.

Hermetic: install.sh runs from a scratch copy of the repo (test_install_state._scratch_repo) into a scratch
HOME, XDG_STATE_HOME and config dir, with --no-mcp --no-plugins --no-deps --no-profile. Nothing paid, no
container CLI, no network.

Run: /Users/pmrj/.claude/venvs/tools/bin/python -m pytest -q tests/test_install_eq_runtime.py
"""
import hashlib
import importlib.util
import json
import os
import re
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_install_state as TS  # noqa: E402  (_scratch_repo, _run_install)

ROOT = Path(TS.ROOT)
pytestmark = pytest.mark.skipif(not (ROOT / ".git").exists(), reason="needs the stack's git checkout")
HOOKS = ("eq_core.py", "eq_policy.py", "eq_cli.py", "eq_isolation.py", "eq_guard.py")
DATA = ("eq_params.json", "eq_lenses.json", "eq_schemas.json")
BINS = ("stack-eq", "stack-eq-check")
KNOBS = ("STACK_EQ", "STACK_EQ_MAX_N", "STACK_EQ_MAX_ROUNDS", "STACK_EQ_MAX_CONCURRENT_RUNS", "STACK_EQ_CONFIRM",
         "STACK_EQ_SESSION_RUNS", "STACK_EQ_WALL")


def commit(repo, rel, text):
    p = Path(repo) / rel
    p.write_text(text)
    git = ["git", "-c", "core.hooksPath=/dev/null", "-c", "commit.gpgsign=false", "-c", "user.name=t",
           "-c", "user.email=t@example.invalid", "-C", str(repo)]
    subprocess.run(git + ["add", "-A"], check=True, stdin=subprocess.DEVNULL)
    subprocess.run(git + ["commit", "-q", "-m", "test: " + rel], check=True, stdin=subprocess.DEVNULL,
                   stdout=subprocess.DEVNULL)


def section(out, name):
    m = re.search(r"^== %s.*?$(.*?)(?=^== |\Z)" % re.escape(name), out, re.S | re.M)
    assert m, out[-3000:]
    return m.group(1)


class Box:
    def __init__(self, tmp):
        self.t = Path(tmp)
        self.home = self.t / "home"
        self.home.mkdir(parents=True, exist_ok=True)
        self.conf = self.home / ".claude"
        self.repo = Path(TS._scratch_repo(str(self.t / "repo")))
        # the shipped params file is the version-0 placeholder (valid, all not_run): these tests tamper with
        # and compare against a `"version": 1` file, so the scratch repo ships the version-1 form of it
        pp = self.repo / "dot-claude" / "hooks" / "eq_params.json"
        commit(self.repo, "dot-claude/hooks/eq_params.json", pp.read_text().replace('"version": 0', '"version": 1'))

    @property
    def state(self):
        return self.home / ".local" / "state" / "claude-agent-stack"

    def install(self, *extra, argv=None, ok=True):
        p = TS._run_install(str(self.repo), str(self.home), str(self.conf), *extra, argv=argv)
        if ok:
            assert p.returncode == 0, (p.stdout[-3000:], p.stderr[-3000:])
        return p

    def manifest(self):
        return json.loads((self.conf / ".stack-manifest.json").read_text())

    def settings(self):
        return json.loads((self.conf / "settings.json").read_text())

    def write_settings(self, s):
        (self.conf / "settings.json").write_text(json.dumps(s, indent=2))

    def doctor(self, full=False, **env):
        e = {k: v for k, v in os.environ.items() if not k.startswith(("STACK_", "CLAUDE_", "XDG_", "EQ_"))}
        e.update(HOME=str(self.home), CLAUDE_CONFIG_DIR=str(self.conf), XDG_STATE_HOME=str(self.state.parent),
                 TMPDIR=str(self.home / "tmp"), PATH="/usr/bin:/bin:/usr/sbin:/sbin")   # no uv, no claude: offline
        e.update(env)
        p = subprocess.run(["bash", str(self.conf / "bin" / "doctor.sh")], env=e, stdin=subprocess.DEVNULL,
                           capture_output=True, text=True, timeout=600, check=False)
        return p.stdout + p.stderr if full else section(p.stdout + p.stderr, "Equilibrium runtime")

    def policy(self):
        spec = importlib.util.spec_from_file_location("eq_policy_installed", self.conf / "hooks" / "eq_policy.py")
        mod = importlib.util.module_from_spec(spec)
        sys.modules["eq_policy_installed"] = mod
        spec.loader.exec_module(mod)
        return mod


@pytest.fixture(scope="module")
def box(tmp_path_factory):
    if not shutil.which("uv"):
        pytest.skip("needs uv (the installer links uv's managed Python 3.13 as stack-python)")
    b = Box(tmp_path_factory.mktemp("eqr"))
    b.install()
    return b


def mode(p):
    return stat.S_IMODE(os.stat(p).st_mode)


def test_settings_wires_the_guard_for_check_verdicts_and_consent_records():
    """Without these two groups agent_guard never sees a Bash result or an AskUserQuestion answer: no
    check verdicts (PostToolUse Bash, PostToolUseFailure Bash) and no consent records (AskUserQuestion)."""
    hooks = json.loads((ROOT / "dot-claude" / "settings.json").read_text())["hooks"]
    want = '/bin/sh "__CLAUDE_DIR__/bin/stack-hook" agent_guard'
    for event, matcher in (("PostToolUse", "Bash|AskUserQuestion"), ("PostToolUseFailure", "Bash")):
        groups = [g for g in hooks[event] if g.get("matcher") == matcher]
        assert len(groups) == 1, (event, matcher)
        assert [h["command"] for h in groups[0]["hooks"]] == [want], (event, matcher)


def test_the_shipped_params_file_validates():
    pol = TS_policy()
    obj = json.loads((ROOT / "dot-claude" / "hooks" / "eq_params.json").read_text())
    assert pol.validate_params(obj) == []


def TS_policy():
    spec = importlib.util.spec_from_file_location("eq_policy_repo", ROOT / "dot-claude" / "hooks" / "eq_policy.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["eq_policy_repo"] = mod
    spec.loader.exec_module(mod)
    return mod


def test_stages_the_files_with_their_modes(box):
    for f in HOOKS + DATA:
        p = box.conf / "hooks" / f
        assert p.is_file() and mode(p) == 0o644, (f, p.exists() and oct(mode(p)))
        assert p.read_bytes() == (box.repo / "dot-claude" / "hooks" / f).read_bytes(), f
    for f in BINS:
        p = box.conf / "bin" / f
        assert p.is_file() and mode(p) == 0o755, (f, p.exists() and oct(mode(p)))
        assert p.read_bytes() == (ROOT / "dot-claude" / "bin" / f).read_bytes(), f


def test_manifest_tracks_the_files_and_pins_the_params(box):
    m = box.manifest()
    want = {"hooks/" + f for f in HOOKS + DATA} | {"bin/" + f for f in BINS}
    assert want <= set(m["files"]), sorted(want - set(m["files"]))
    for rel in want:
        assert m["files"][rel] == hashlib.sha256((box.conf / rel).read_bytes()).hexdigest(), rel
    eq = m["eq_runtime"]
    assert eq["params_sha256"] == hashlib.sha256((box.conf / "hooks" / "eq_params.json").read_bytes()).hexdigest()
    shipped = json.loads((box.repo / "dot-claude" / "hooks" / "eq_params.json").read_text())["classes"]
    assert eq["validated"] == sorted(k for k, v in shipped.items() if v["status"] == "validated")


def test_load_params_accepts_the_installed_pair_and_refuses_a_tampered_file(box, tmp_path):
    pol = box.policy()
    params, sha, why = pol.load_params(str(box.conf / "hooks" / "eq_params.json"), str(box.conf / ".stack-manifest.json"))
    assert why is None and params is not None and sha == box.manifest()["eq_runtime"]["params_sha256"]
    tampered = tmp_path / "eq_params.json"
    tampered.write_text((box.conf / "hooks" / "eq_params.json").read_text().replace('"version": 1', '"version": 7'))
    params, sha, why = pol.load_params(str(tampered), str(box.conf / ".stack-manifest.json"))
    assert params is None and "differs from the manifest" in why, why


def test_doctor_section_on_a_clean_install(box):
    d = box.doctor()
    for row in ("ok    equilibrium runtime files installed (10)", "ok    params pin matches the manifest (sha256 %s..."
                % box.manifest()["eq_runtime"]["params_sha256"][:12],
                "ok    no class is validated yet", "ok    sandbox.excludedCommands names bin/stack-eq",
                "ok    knobs: STACK_EQ=1 STACK_EQ_MAX_N=9 STACK_EQ_MAX_ROUNDS=2 STACK_EQ_MAX_CONCURRENT_RUNS=1 "
                "STACK_EQ_N=None STACK_EQ_ROUNDS=None STACK_EQ_CONFIRM=always STACK_EQ_SESSION_RUNS=3 STACK_EQ_WALL=auto",
                "ok    W3 level available: sandbox"):
        assert row in d, (row, d)
    assert "WARN" not in d and "FAIL" not in d, d


def test_doctor_reports_a_params_mismatch_as_every_class_not_run(box):
    p = box.conf / "hooks" / "eq_params.json"
    orig = p.read_text()
    try:
        p.write_text(orig.replace('"version": 1', '"version": 7'))
        d = box.doctor()
        assert "WARN  hooks/eq_params.json sha256" in d and "every class not_run" in d, d
        assert "ok    params pin matches" not in d
    finally:
        p.write_text(orig)
    m = json.loads((box.conf / ".stack-manifest.json").read_text())
    saved = dict(m["eq_runtime"])
    try:
        del m["eq_runtime"]
        (box.conf / ".stack-manifest.json").write_text(json.dumps(m))
        assert "WARN  manifest has no eq_runtime.params_sha256: every class not_run" in box.doctor()
    finally:
        m["eq_runtime"] = saved
        (box.conf / ".stack-manifest.json").write_text(json.dumps(m))


def test_doctor_validated_classes_and_drift(box):
    p = box.conf / "hooks" / "eq_params.json"
    mp = box.conf / ".stack-manifest.json"
    orig_p, orig_m = p.read_text(), mp.read_text()
    try:
        params = json.loads(orig_p)
        params["provenance"]["claude_code_version"] = "2.1.1"
        e = params["classes"]["PF"]
        e.update(status="validated", N=5, rounds=1, view="lens", loo_view="none", reducer="R0", tau=0.5, t=1,
                 caps={"member_tokens": 1000, "member_turns": 5, "run_tokens": 9000}, member_type="coder",
                 member_model_id="claude-fake-1", agent_file_sha256="0" * 64, usd_per_mtok=1.0,
                 pool={"name": "p", "sha256": "1" * 64, "description": "d"}, effect={},
                 cost_ratio={"median": 1.0, "ci95": [0.9, 1.1]})
        raw = json.dumps(params, indent=1, sort_keys=True)
        p.write_text(raw)
        m = json.loads(orig_m)
        m["eq_runtime"]["params_sha256"] = hashlib.sha256(raw.encode()).hexdigest()
        mp.write_text(json.dumps(m))
        d = box.doctor()
        assert "ok    validated classes: PF" in d, d
        assert "drift: class PF was calibrated on agents/coder.md sha256 000000000000..." in d, d
    finally:
        p.write_text(orig_p)
        mp.write_text(orig_m)


def test_doctor_flags_a_missing_executor_entry_and_loose_store_dirs(box):
    s0 = box.settings()
    try:
        s = json.loads(json.dumps(s0))
        s["sandbox"]["excludedCommands"] = [e for e in s["sandbox"]["excludedCommands"] if "stack-eq" not in e]
        s["permissions"]["allow"] = [a for a in s["permissions"]["allow"] if "stack-eq-check" not in a]
        s["env"]["STACK_MAX_FANOUT_BY_TYPE"] = "orchestrator=32"
        box.write_settings(s)
        d = box.doctor()
        assert "WARN  sandbox.excludedCommands lacks" in d and "bin/stack-eq *" in d, d
        assert "WARN  permissions.allow lacks Bash(%s *)" % (box.conf / "bin" / "stack-eq-check") in d, d
        assert "WARN  STACK_MAX_FANOUT_BY_TYPE has no equilibrium= entry" in d, d
    finally:
        box.write_settings(s0)
    d_ = box.state / "eq-tickets"
    d_.mkdir(parents=True)
    d_.chmod(0o755)
    try:
        assert "WARN  eq store dir(s) a link, not yours, or open to others (want 0700): %s" % d_ in box.doctor()
        d_.chmod(0o700)
        assert "ok    eq store dirs are 0700" in box.doctor()
    finally:
        d_.rmdir()


def test_doctor_knobs_follow_the_environment_and_fail_closed(box):
    d = box.doctor(STACK_EQ="2", STACK_EQ_N="3")
    assert "knob: STACK_EQ='2' is not 0 or 1: off" in d and "STACK_EQ=0" in d and "STACK_EQ_N=3" in d, d


def test_doctor_w3_level_container_needs_a_verified_install_and_a_pass_receipt(box):
    eqs = box.state / "eq-container"
    (eqs / "results").mkdir(parents=True)
    try:
        (eqs / "status.env").write_text("EQ_CONTAINER_STATUS=verified\n")
        assert "W3 level available: sandbox" in box.doctor()
        for bad in ("FAIL", "SKIPPED"):
            (eqs / "results" / "probe.core.env").write_text("PROBE_RESULT=%s\n" % bad)
            assert "W3 level available: sandbox" in box.doctor(), bad
        (eqs / "results" / "probe.core.env").write_text("PROBE_RESULT=PASS\n")
        assert "W3 level available: container" in box.doctor()
        (eqs / "status.env").write_text("EQ_CONTAINER_STATUS=failed\n")
        assert "W3 level available: sandbox" in box.doctor()
    finally:
        shutil.rmtree(eqs)


def test_toolsmith_section_accepts_the_eq_executor_entry(box):
    full = box.doctor(full=True)
    assert "sandbox.excludedCommands also takes" not in full, [ln for ln in full.splitlines() if "also takes" in ln]
    assert "ok    sandbox.excludedCommands names the executor" in full


def test_settings_merge_carries_the_eq_entries_and_keeps_yours(box):
    s = box.settings()
    cd = str(box.conf)
    assert f"{cd}/bin/stack-eq *" in s["sandbox"]["excludedCommands"]
    assert f"{cd}/bin/stack-install *" in s["sandbox"]["excludedCommands"]
    for f in BINS:
        assert f"Bash({cd}/bin/{f} *)" in s["permissions"]["allow"]
    for k in KNOBS:
        assert k in s["env"], k
    assert "equilibrium=9" in s["env"]["STACK_MAX_FANOUT_BY_TYPE"]
    assert "__CLAUDE_DIR__" not in json.dumps(s)


def test_retraction_removes_what_the_stack_stopped_shipping_and_keeps_yours(tmp_path):
    if not shutil.which("uv"):
        pytest.skip("needs uv")
    b = Box(tmp_path)
    b.install()
    s = b.settings()
    s["sandbox"]["excludedCommands"].append("/opt/mine/bin/tool *")
    s["permissions"]["allow"].append("Bash(/opt/mine/bin/tool *)")
    s["env"]["STACK_EQ_MAX_N"] = "4"           # yours: a value you changed is never rewritten back
    b.write_settings(s)
    sp = b.repo / "dot-claude" / "settings.json"
    shipped = json.loads(sp.read_text())
    shipped["sandbox"]["excludedCommands"] = [e for e in shipped["sandbox"]["excludedCommands"] if "stack-eq" not in e]
    shipped["permissions"]["allow"] = [a for a in shipped["permissions"]["allow"] if "stack-eq" not in a]
    commit(b.repo, "dot-claude/settings.json", json.dumps(shipped, indent=2))
    b.install("--yes")
    s = b.settings()
    cd = str(b.conf)
    assert not any("stack-eq" in e for e in s["sandbox"]["excludedCommands"]), s["sandbox"]["excludedCommands"]
    assert not any("stack-eq" in a for a in s["permissions"]["allow"])
    assert "/opt/mine/bin/tool *" in s["sandbox"]["excludedCommands"]
    assert "Bash(/opt/mine/bin/tool *)" in s["permissions"]["allow"]
    assert f"{cd}/bin/stack-install *" in s["sandbox"]["excludedCommands"]
    assert s["env"]["STACK_EQ_MAX_N"] == "4"


def test_a_new_params_file_is_pinned_again_and_restore_brings_the_old_pin_back(tmp_path):
    if not shutil.which("uv"):
        pytest.skip("needs uv")
    b = Box(tmp_path)
    b.install()
    old = b.manifest()["eq_runtime"]["params_sha256"]
    pp = b.repo / "dot-claude" / "hooks" / "eq_params.json"
    new_text = pp.read_text().replace('"version": 1', '"version": 2')
    commit(b.repo, "dot-claude/hooks/eq_params.json", new_text)
    b.install("--yes")
    new = b.manifest()["eq_runtime"]["params_sha256"]
    assert new != old and new == hashlib.sha256(new_text.encode()).hexdigest()
    assert b.policy().load_params(str(b.conf / "hooks" / "eq_params.json"), str(b.conf / ".stack-manifest.json"))[2] is None
    p = b.install(argv=["--restore"])
    assert p.returncode == 0, (p.stdout[-2000:], p.stderr[-2000:])
    assert b.manifest()["eq_runtime"]["params_sha256"] == old
    assert hashlib.sha256((b.conf / "hooks" / "eq_params.json").read_bytes()).hexdigest() == old
    assert b.policy().load_params(str(b.conf / "hooks" / "eq_params.json"), str(b.conf / ".stack-manifest.json"))[2] is None
