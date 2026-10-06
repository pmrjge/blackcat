"""bin/stack-eq (hooks/eq_cli.py --eq-executor): tickets, the store, plan refusals, check copies, reduce,
result patches, cleanup and Level 2 (docs-design/RUNTIME_EQUILIBRIUM.md 2.2, 6.2, 10.3; contracts.md 2-6).

Hermetic: a scratch HOME holding the config dir (hooks under test + a FAKE eq_core.py with the contract 8
API), the state root and a git project; the guard's records (brief, tickets, members, captures, consent,
verdicts) are written by tests/fixtures/eq_cli/eqworld.py. Level 2 runs tests/fake-container/container
(never the real container CLI) and lib/eq-wall's broker from a scratch copy. EQ_HOOKS_SRC points the world
at a seeded-bug copy of the hooks."""
import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / "fixtures" / "eq_cli"))
import eqworld  # noqa: E402
from eqworld import GIT, R, SID, World, mode, sh  # noqa: E402

REPO = HERE.parent
FAKE_CONTAINER = HERE / "fake-container" / "container"


def _policy():
    spec = importlib.util.spec_from_file_location("eqp_t", eqworld.HOOKS_SRC / "eq_policy.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


P = _policy()


@pytest.fixture()
def w(tmp_path):
    return World(tmp_path)


CP_HEADER = {"class": "CP", "check": ["/bin/sh", "check.sh"]}


def cp_run(w, n=2, start=True):
    """A CP run planned with N=n members (STACK_EQ_N), consent recorded and started."""
    w.project()
    w.brief(CP_HEADER)
    env = w.env(STACK_EQ_N=str(n))
    p = w.eq("plan", "--run", R, env=env)
    assert p.returncode == 0, p.stderr
    if start:
        w.consent()
        p = w.eq("start", "--run", R)
        assert p.returncode == 0, p.stderr
    return env


def two_candidates(w):
    """m1: the right answer plus a new and a binary file; m2: a wrong answer that tampers with what judges it."""
    wt1, wt2 = w.worktree(1), w.worktree(2)
    (wt1 / "src" / "value.txt").write_text("42\n")
    (wt1 / "src" / "new.txt").write_text("brand new\n")
    (wt1 / "src" / "blob.bin").write_bytes(bytes(range(256)) * 4)
    (wt2 / "src" / "value.txt").write_text("1\n")
    (wt2 / "tests" / "run.sh").write_text("echo PASS; exit 0\n")
    (wt2 / "check.sh").write_text("exit 0\n")
    (wt2 / "unittest.py").write_text("raise SystemExit(0)\n")
    w.members({"1": {"agent_id": "m1", "worktree": str(wt1), "status": "stopped", "rounds": {"0": "captured"}},
               "2": {"agent_id": "m2", "worktree": str(wt2), "status": "stopped", "rounds": {"0": "captured"}}})
    w.capture(0, 1, {"answer": "42", "evidence": [], "confidence": 0.9})
    w.capture(0, 2, {"answer": "1", "evidence": [], "confidence": 0.9})
    return wt1, wt2


def checks_and_verdicts(w):
    p = w.eq("prepare-check", "--run", R, "--round", "0")
    assert p.returncode == 0, p.stderr
    out = {}
    for i in (1, 2):
        c = w.check(R, i)
        out[i] = w.verdict(0, i, c.stdout, c.returncode, policy=P)
    return out


# ---------------------------------------------------------------- tickets
def test_no_ticket_refused(w):
    w.project()
    w.brief(CP_HEADER)
    p = w.eq("plan", "--run", R, ticket=False)
    assert p.returncode == 4 and "no guard ticket" in p.stderr
    assert not (w.store() / "plan.json").exists()


def test_ticket_single_use(w):
    w.project()
    w.brief(CP_HEADER)
    p = w.eq("status", "--run", R)
    assert p.returncode == 0, p.stderr
    p = w.eq("status", "--run", R, ticket=False)          # the first call consumed it
    assert p.returncode == 4
    assert not list((w.state / "eq-tickets").glob("*.json"))


@pytest.mark.parametrize("kw", [{"ts": time.time() - 200}, {"ts": time.time() + 60}, {"run": "ffffffff"},
                                {"argv": ["status", "--run", "ffffffff"]}])
def test_ticket_stale_or_foreign(w, kw):
    w.project()
    w.brief(CP_HEADER)
    p = w.eq("status", "--run", R, **kw)
    assert p.returncode == 4, (kw, p.stdout)


def test_ticket_session_comes_from_ticket_only(w):
    w.project()
    w.brief(CP_HEADER)
    p = w.eq("status", "--run", R, sid="other-session")   # the ticket names a session without that run
    assert p.returncode == 4 and "no store" in p.stderr


def test_usage_errors_need_no_ticket(w):
    p = w.eq("plan", ticket=False)
    assert p.returncode == 2
    p = w.eq("help", ticket=False)
    assert p.returncode == 0 and "stack-eq plan" in p.stdout


# ---------------------------------------------------------------- plan
def test_plan_writes_store_with_modes(w):
    cp_run(w, start=False)
    d = w.store()
    plan = json.loads((d / "plan.json").read_text())
    assert plan["schema"] == "eqplan.v1" and plan["N"] == 2 and plan["status_reason"] == "class_not_validated"
    assert plan["consent"] == {"required": True, "token": "Run eq:" + R}
    assert plan["w3"] == "sandbox" and plan["workdir"] == "worktree" and plan["check"]["argv"] == ["/bin/sh", "check.sh"]
    for i in (1, 2):
        b = d / "briefs" / ("m%d.txt" % i)
        assert b.read_text().startswith("eq %s m%d/2" % (R, i))
        assert (d / "briefs" / ("m%d.txt.sha256" % i)).read_text().strip() == hashlib.sha256(b.read_bytes()).hexdigest()
        assert mode(b) == 0o600
    assert mode(d / "briefs") == 0o700 and mode(d / "plan.json") == 0o600 and mode(d / "state.json") == 0o600
    assert json.loads((d / "state.json").read_text())["phase"] == "planned"


def test_plan_prints_estimate_and_consent(w):
    w.project()
    w.brief(CP_HEADER)
    p = w.eq("plan", "--run", R, env=w.env(STACK_EQ_N="2"))
    assert "estimate: tokens" in p.stdout and "ASK USER: Run eq:%s" % R in p.stdout
    assert "unvalidated (class_not_validated, override, manual)" in p.stdout


def test_plan_refuses_ssh_segment(w):
    w.project()
    (w.home / ".ssh").mkdir()
    (w.home / ".ssh" / "id_ed25519").write_text("PRIVATE")
    w.brief({"class": "CR", "segments": ["~/.ssh/id_ed25519"]})
    p = w.eq("plan", "--run", R)
    assert p.returncode == 4 and "outside the project root" in p.stderr
    assert not (w.store() / "plan.json").exists() and not (w.store() / "briefs").exists()


def test_plan_refuses_symlinked_segment_and_denied(w):
    w.project()
    (w.home / ".ssh").mkdir()
    (w.home / ".ssh" / "id_ed25519").write_text("PRIVATE")
    os.symlink(w.home / ".ssh" / "id_ed25519", w.proj / "key.txt")
    w.brief({"class": "CR", "segments": ["key.txt"]})
    p = w.eq("plan", "--run", R)
    assert p.returncode == 4 and "outside the project root" in p.stderr


def test_plan_refuses_deny_rule_and_abs_check(w):
    w.project()
    (w.proj / ".env").write_text("TOKEN=x")
    sh(GIT + ["add", "-f", ".env"], cwd=w.proj)
    sh(GIT + ["commit", "-q", "-m", "env"], cwd=w.proj)
    w.brief({"class": "CR", "segments": [".env"]})
    p = w.eq("plan", "--run", R)
    assert p.returncode == 4 and "deny rule" in p.stderr


@pytest.mark.parametrize("check, why", [
    (["/bin/sh", str(Path.home() / "x.sh")], "absolute path"),
    (["/bin/sh", "../outside.sh"], "outside the project root"),
    (["/bin/sh", "~/x.sh"], "home path"),
    (["no-such-program-eq"], "does not resolve"),
])
def test_plan_refuses_check_paths(w, check, why):
    w.project()
    w.brief({"class": "CP", "check": check})
    p = w.eq("plan", "--run", R)
    assert p.returncode == 4 and why in p.stderr, p.stderr


def test_plan_refuses_uncommitted_and_missing_check(w):
    w.project()
    (w.proj / "src" / "value.txt").write_text("dirty\n")
    w.brief(CP_HEADER)
    p = w.eq("plan", "--run", R)
    assert p.returncode == 4 and "uncommitted" in p.stderr
    (w.t / "second").mkdir()
    w2 = World(w.t / "second")
    w2.project()
    w2.brief({"class": "CP"})
    p = w2.eq("plan", "--run", R)
    assert p.returncode == 4 and "needs eq-check" in p.stderr


def test_plan_refuses_dangerous_git_config(w):
    w.project()
    sh(GIT + ["config", "filter.evil.clean", "touch %s" % (w.home / "pwned")], cwd=w.proj)
    w.brief(CP_HEADER)
    p = w.eq("plan", "--run", R)
    assert p.returncode == 4 and "filter.evil.clean" in p.stderr
    assert not (w.home / "pwned").exists()


def test_plan_auto_unvalidated_refused(w):
    w.project()
    w.brief(dict(CP_HEADER, mode="auto"))
    p = w.eq("plan", "--run", R)
    assert p.returncode == 4 and "eq-mode: auto needs a validated class" in p.stderr


def test_plan_tampered_params_mean_no_calibration(w):
    w.project()
    (w.hooks / "eq_params.json").write_text((w.hooks / "eq_params.json").read_text() + " ")
    w.brief(CP_HEADER)
    p = w.eq("plan", "--run", R)
    assert p.returncode == 0, p.stderr
    plan = json.loads((w.store() / "plan.json").read_text())
    assert plan["status_reason"] == "no_calibration" and "differs" in plan["params_reason"]
    assert plan["params_sha256"] is None


def test_plan_store_symlink_not_followed(w):
    w.project()
    d = w.brief(CP_HEADER)
    elsewhere = w.t / "elsewhere"
    elsewhere.mkdir()
    os.symlink(elsewhere, d / "briefs")
    p = w.eq("plan", "--run", R, env=w.env(STACK_EQ_N="2"))
    assert p.returncode == 4 and "symlink" in p.stderr
    assert list(elsewhere.iterdir()) == []


def test_plan_document_class_kcover_dirs(w):
    files = {"doc%d.md" % k: "segment %d\n" % k for k in range(8)}
    w.project(files)
    w.brief({"class": "RS", "segments": sorted(files)})
    p = w.eq("plan", "--run", R)
    assert p.returncode == 0, p.stderr
    plan = json.loads((w.store() / "plan.json").read_text())
    assert plan["workdir"] == "dir" and plan["N"] == 5
    eqd = w.proj / ".claude-work" / "eq" / R
    assert mode(eqd) == 0o700
    seen = [sorted(p.name for p in (eqd / ("m%d" % i)).iterdir()) for i in range(1, 6)]
    assert seen[4] == sorted(files)                       # the full member
    assert all(len(s) < len(files) for s in seen[:4])     # k-cover deletions applied to partial members
    assert plan["member_dirs"]["1"] == str(eqd / "m1")


def test_plan_project_eq_dir_symlink_refused(w):
    files = {"a.md": "a\n"}
    w.project(files)
    target = w.home / "x"
    target.mkdir()
    (w.proj / ".claude-work").mkdir()
    os.symlink(target, w.proj / ".claude-work" / "eq")
    w.brief({"class": "RS", "segments": ["a.md"]})
    p = w.eq("plan", "--run", R)
    assert p.returncode == 4 and "symlink" in p.stderr
    assert list(target.iterdir()) == []


# ---------------------------------------------------------------- start / consent
def test_start_needs_consent_record(w):
    cp_run(w, start=False)
    p = w.eq("start", "--run", R)
    assert p.returncode == 3 and "ASK USER: Run eq:%s" % R in p.stdout
    w.consent(answer="Cancel")
    assert w.eq("start", "--run", R).returncode == 3
    w.consent()
    p = w.eq("start", "--run", R)
    assert p.returncode == 0 and "eq %s m1/2" % R in p.stdout and 'isolation: "worktree"' in p.stdout


def test_start_headless_consent_file(w):
    cp_run(w, start=False)
    cf = w.t / "consent.json"
    plan_sha = hashlib.sha256((w.store() / "plan.json").read_bytes()).hexdigest()
    cf.write_text(json.dumps({"token": "Run eq:" + R, "plan_sha256": "0" * 64}))
    args = ("start", "--run", R, "--headless", "--consent-file", str(cf))
    assert w.eq(*args, ticket=False).returncode == 4                      # wrong plan hash
    cf.write_text(json.dumps({"token": "Run eq:" + R, "plan_sha256": plan_sha}))
    p = w.eq(*args, ticket=False, env=w.env(CLAUDECODE="1"))
    assert p.returncode == 4 and "CLAUDECODE" in p.stderr                  # inside Claude Code: refused
    link = w.t / "link.json"
    os.symlink(cf, link)
    assert w.eq("start", "--run", R, "--headless", "--consent-file", str(link), ticket=False).returncode == 4
    p = w.eq(*args, ticket=False)
    assert p.returncode == 0, p.stderr
    rec = json.loads((w.state / SID / "eq" / "consent" / (R + ".json")).read_text())
    assert rec["source"] == "file" and rec["token"] == "Run eq:" + R


# ---------------------------------------------------------------- checks, reduce
def test_check_copy_overlay_rules(w):
    cp_run(w)
    two_candidates(w)
    p = w.eq("prepare-check", "--run", R, "--round", "0")
    assert p.returncode == 0, p.stderr
    c1 = w.proj / ".claude-work" / "eq" / R / "checks" / "c1"
    c2 = c1.parent / "c2"
    assert (c1 / "src" / "value.txt").read_text() == "42\n"
    assert not (c1 / "src" / "new.txt").exists()          # member-added files are never taken
    assert (c2 / "src" / "value.txt").read_text() == "1\n"
    assert not (c2 / "unittest.py").exists()              # a planted module is not taken
    assert (c2 / "tests" / "run.sh").read_text() == (w.proj / "tests" / "run.sh").read_text()   # owned: pristine
    assert (c2 / "check.sh").read_text() == (w.proj / "check.sh").read_text()                    # the check script
    assert not (w.home / "check-runs.log").exists()       # stack-eq never ran the check
    for i, want in ((1, "pass"), (2, "fail")):
        c = w.check(R, i)
        assert w.verdict(0, i, c.stdout, c.returncode, policy=P) == want, c.stdout


def test_prepare_check_refuses_symlinked_checks_dir(w):
    cp_run(w)
    two_candidates(w)
    victim = w.home / "x"
    victim.mkdir()
    (victim / "keep.txt").write_text("keep")
    eqd = w.proj / ".claude-work" / "eq" / R
    eqd.mkdir(parents=True, exist_ok=True)
    os.symlink(victim, eqd / "checks")
    p = w.eq("prepare-check", "--run", R, "--round", "0")
    assert p.returncode == 4 and "symlink" in p.stderr
    assert sorted(x.name for x in victim.iterdir()) == ["keep.txt"]
    assert os.path.islink(eqd / "checks")


def test_prepare_check_refuses_unregistered_worktree(w):
    cp_run(w)
    two_candidates(w)
    fake = w.proj / ".claude" / "worktrees" / "fake"
    fake.mkdir(parents=True)
    recs = json.loads((w.store() / "members.json").read_text())
    recs["2"]["worktree"] = str(fake)
    w.members(recs)
    p = w.eq("prepare-check", "--run", R, "--round", "0")
    assert p.returncode == 4 and "not a registered worktree" in p.stderr


def test_reduce_refuses_incomplete_round(w):
    cp_run(w)
    two_candidates(w)
    recs = json.loads((w.store() / "members.json").read_text())
    recs["2"]["rounds"] = {}
    recs["2"]["status"] = "running"
    w.members(recs)
    (w.store() / "r0" / "m2.json").unlink()
    assert w.eq("prepare-check", "--run", R, "--round", "0").returncode == 0
    c = w.check(R, 1)
    w.verdict(0, 1, c.stdout, c.returncode, policy=P)
    p = w.eq("reduce", "--run", R, "--round", "0")
    assert p.returncode == 4 and "m2 not captured" in p.stderr
    assert not (w.store() / "r0" / "reduce.json").exists()


def test_reduce_refuses_missing_verdict(w):
    cp_run(w)
    two_candidates(w)
    assert w.eq("prepare-check", "--run", R, "--round", "0").returncode == 0
    c = w.check(R, 1)
    w.verdict(0, 1, c.stdout, c.returncode, policy=P)
    p = w.eq("reduce", "--run", R, "--round", "0")
    assert p.returncode == 4 and "c2's check verdict" in p.stderr


def test_reduce_requires_checks_phase(w):
    cp_run(w)
    two_candidates(w)
    p = w.eq("reduce", "--run", R, "--round", "0")
    assert p.returncode == 4 and "checks first" in p.stderr


def test_full_cp_run_patch_applies_and_cleanup(w):
    cp_run(w)
    wt1, wt2 = two_candidates(w)
    assert checks_and_verdicts(w) == {1: "pass", 2: "fail"}
    p = w.eq("reduce", "--run", R, "--round", "0")
    assert p.returncode == 0, p.stderr
    assert not (w.proj / ".claude-work" / "eq" / R / "checks").exists()      # check copies removed
    led = [json.loads(x) for x in (w.store() / "mediator.jsonl").read_text().splitlines()]
    assert {x["record"] for x in led} >= {"attribution", "reduce", "start"}
    p = w.eq("result", "--run", R)
    assert p.returncode == 0, p.stderr
    assert "NEXT: coder applies ./.claude-work/eq/%s/selected.patch" % R in p.stdout
    assert "ASK USER: Remove 2 eq worktrees and branches for eq:%s (patches kept) | Keep" % R in p.stdout
    eqd = w.proj / ".claude-work" / "eq" / R
    sel = eqd / "selected.patch"
    assert mode(sel) == 0o600 and (eqd / "cand-2.patch").exists()
    res = json.loads((w.store() / "result.json").read_text())
    assert res["validated"] is False and res["status_reason"] == "class_not_validated"
    assert res["certainty"] is None                                          # never from an unvalidated run
    assert res["wall"] == {"w3": "sandbox", "w1_file_tools": "hook", "w1_bash": "heuristic"}
    assert res["agreement"]["label"] == "agreement, not probability"
    assert json.loads((eqd / "result.json").read_text()) == res              # copied: every member stopped
    # the selected patch applies cleanly to HEAD and carries the new and the binary file
    clone = w.t / "clone"
    sh(GIT + ["clone", "-q", str(w.proj), str(clone)])
    sh(GIT + ["apply", "--check", str(sel)], cwd=clone)
    sh(GIT + ["apply", str(sel)], cwd=clone)
    assert (clone / "src" / "value.txt").read_text() == "42\n"
    assert (clone / "src" / "new.txt").read_text() == "brand new\n"
    assert (clone / "src" / "blob.bin").read_bytes() == bytes(range(256)) * 4
    # cleanup: Remove consent required; a worktree whose diff changed is refused, nothing removed
    p = w.eq("cleanup", "--run", R)
    assert p.returncode == 3
    w.consent("remove")
    (wt2 / "src" / "value.txt").write_text("changed after the result\n")
    p = w.eq("cleanup", "--run", R)
    assert p.returncode == 4 and "no longer matches" in p.stderr
    assert wt1.exists() and wt2.exists()
    (wt2 / "src" / "value.txt").write_text("1\n")
    p = w.eq("cleanup", "--run", R)
    assert p.returncode == 0, p.stderr
    assert not wt1.exists() and not wt2.exists()
    branches = sh(GIT + ["branch", "--list", "eq-m*"], cwd=w.proj).stdout.decode()
    assert branches.strip() == ""


def test_result_flags_model_drift_for_validated(w):
    params = w.params()
    params["classes"]["CP"] = {
        "status": "validated", "member_type": "python-engineer", "member_model_id": "claude-opus-test-a",
        "agent_file_sha256": "a" * 64, "N": 2, "rounds": 1, "view": "perm", "loo_view": "rotation", "reducer": "R0",
        "tau": 0.6, "t": 2, "caps": {"member_tokens": 1000, "member_turns": 10, "run_tokens": 4000},
        "usd_per_mtok": 3.0, "cost_ratio": {"median": 1.2, "ci95": [1.0, 1.5]}, "effect": {}, "certainty": None,
        "pool": {"name": "cp", "sha256": "b" * 64, "description": "d"}}
    w.set_params(params)
    w.project()
    w.brief(dict(CP_HEADER, mode="auto"))
    assert w.eq("plan", "--run", R).returncode == 0
    plan = json.loads((w.store() / "plan.json").read_text())
    assert plan["validated"] is True and plan["member_model_id"] == "claude-opus-test-a"
    w.consent()
    assert w.eq("start", "--run", R).returncode == 0
    two_candidates(w)
    w.capture(0, 2, {"answer": "1"}, model="claude-sonnet-test-b")
    w.capture(0, 1, {"answer": "42"}, model="claude-opus-test-a")
    checks_and_verdicts(w)
    assert w.eq("reduce", "--run", R, "--round", "0").returncode == 0
    p = w.eq("result", "--run", R)
    res = json.loads((w.store() / "result.json").read_text())
    assert res["validated"] is False and res["status_reason"] == "model_drift", p.stdout


def test_view_round_loo(w):
    files = {"a.md": "a\n", "b.md": "b\n"}
    w.project(files)
    w.brief({"class": "ES", "segments": ["a.md", "b.md"]})
    env = w.env(STACK_EQ_N="3", STACK_EQ_ROUNDS="2")
    assert w.eq("plan", "--run", R, env=env).returncode == 0
    w.consent()
    assert w.eq("start", "--run", R).returncode == 0
    w.members({str(i): {"agent_id": "m%d" % i, "worktree": None, "status": "running", "rounds": {"0": "captured"}}
               for i in (1, 2, 3)})
    for i, a in ((1, 10), (2, 20), (3, 30)):
        w.capture(0, i, {"answer": a})
    p = w.eq("reduce", "--run", R, "--round", "0")
    assert p.returncode == 0, p.stderr
    assert "view --run %s --round 1" % R in p.stdout                   # kappa 1/3 < tau
    assert w.eq("view", "--run", R, "--round", "2").returncode == 4     # round 1 is not reduced yet
    assert w.eq("view", "--run", R, "--round", "3").returncode == 4     # past the plan's 2 rounds
    p = w.eq("view", "--run", R, "--round", "1")
    assert p.returncode == 0, p.stderr
    for i in (1, 2, 3):
        v = w.store() / "views" / "r1" / ("m%d.txt" % i)
        assert mode(v) == 0o600
        assert (w.store() / "views" / "r1" / ("m%d.txt.sha256" % i)).read_text().strip() == \
            hashlib.sha256(v.read_bytes()).hexdigest()
        assert "eq %s r1 m%d" % (R, i) in p.stdout
    led = [json.loads(x) for x in (w.store() / "mediator.jsonl").read_text().splitlines()]
    assert [x["exclude"] for x in led if x["record"] == "loo_view"] == [2, 3, 1]


def test_executor_never_runs_the_check(w):
    """plan, start, prepare-check, reduce and result never execute the eq-check argv (contracts.md 5)."""
    cp_run(w)
    two_candidates(w)
    assert w.eq("prepare-check", "--run", R, "--round", "0").returncode == 0
    assert not (w.home / "check-runs.log").exists()
    for i in (1, 2):
        w.verdict(0, i, "", 1, policy=P)                 # unverifiable, without running anything
    assert w.eq("reduce", "--run", R, "--round", "0").returncode == 0
    assert w.eq("result", "--run", R).returncode == 0
    assert not (w.home / "check-runs.log").exists()


# ---------------------------------------------------------------- Level 2 (fake container + the real broker)
DIG = "sha256:" + "a" * 64
IMG = "eq.invalid/eq-py-min:4.34.1-arm64@" + DIG


def level2(w, tamper_policy=False):
    shims = w.t / "shims"
    shims.mkdir()
    cli = shims / "container"
    shutil.copy(FAKE_CONTAINER, cli)
    os.chmod(cli, 0o755)
    wall_dir = w.t / "eq-wall"
    wall_dir.mkdir()
    for f in ("REVIEW", "eq_wall.py", "eq_wall_client.py", "policy.default.toml"):
        shutil.copy(REPO / "lib" / "eq-wall" / f, wall_dir / f)
    if tamper_policy:
        with open(wall_dir / "policy.default.toml", "a") as f:
            f.write("# edited\n")
    ec_state = w.state / "eq-container"
    (ec_state / "results").mkdir(parents=True)
    (ec_state / "results" / "tunnel.cp.env").write_text(
        "TUNNEL_IMAGE=%s\nTUNNEL_IMAGE_DIGEST=%s\nTUNNEL_RESULT=PASS\n" % (IMG.rpartition("@")[0], DIG))
    w.manifest["eq_container"] = {"status": "ok", "image_refs": {"pf": IMG, "cp": IMG, "cr": IMG},
                                  "state_dir": str(ec_state)}
    w.manifest["eq_wall"] = {"status": "on", "tunnel_dir": str(w.home / ".cache" / "claude-agent-stack" / "eq-tunnel"),
                             "state_dir": str(w.state / "eq-wall"), "wall_dir": str(wall_dir)}
    w.write_manifest()
    log = w.t / "container.log"
    return w.env(STACK_EQ_N="2", STACK_EQ_CONTAINER_BIN=str(cli), EQ_FAKE_CONTAINER_DIGEST=DIG,
                 EQ_FAKE_CONTAINER_LOG=str(log)), log, wall_dir


def test_reviewed_pins_match_review_file():
    iso_spec = importlib.util.spec_from_file_location("eqi_t", eqworld.HOOKS_SRC / "eq_isolation.py")
    iso = importlib.util.module_from_spec(iso_spec)
    iso_spec.loader.exec_module(iso)
    review = (REPO / "lib" / "eq-wall" / "REVIEW").read_text()
    for key, name in iso.WALL_FILES.items():
        assert iso.review_value(review, key) == iso.REVIEWED[key]
        assert hashlib.sha256((REPO / "lib" / "eq-wall" / name).read_bytes()).hexdigest() == iso.REVIEWED[key]


def test_level2_container_checks_with_default_deny_broker(w):
    env, log, _ = level2(w)
    w.project()
    w.brief(CP_HEADER)
    p = w.eq("plan", "--run", R, env=env)
    assert p.returncode == 0, p.stderr
    plan = json.loads((w.store() / "plan.json").read_text())
    assert plan["w3"] == "container", plan["w3_reason"]
    w.consent()
    assert w.eq("start", "--run", R, env=env).returncode == 0
    two_candidates(w)
    p = w.eq("prepare-check", "--run", R, "--round", "0", env=env)
    assert p.returncode == 0, p.stderr
    assert "check-container" in p.stdout
    c2 = w.proj / ".claude-work" / "eq" / R / "checks" / "c2"
    assert not (c2 / "tests").exists() and not (c2 / "check.sh").exists()   # owned: mounted read-only instead
    p = w.eq("check-container", "--run", R, "--round", "0", env=env)
    assert p.returncode == 0, p.stderr
    v = {i: json.loads((w.store() / "r0" / ("check-c%d.json" % i)).read_text()) for i in (1, 2)}
    assert v[1]["verdict"] == "pass" and v[2]["verdict"] == "fail", (v, p.stdout)
    assert v[1]["exit_source"] == "container"
    runs = [ln.split("\x1f") for ln in log.read_text().splitlines() if ln.startswith("run\x1f")]
    assert len(runs) == 2
    for a in runs:
        joined = " ".join(a)
        assert "--network none" in joined and "--read-only" in joined and "--cap-drop ALL" in joined
        assert "type=bind,source=%s,target=/fixture,readonly" % (w.proj / ".claude-work" / "eq" / R / "checks" / "pristine") in a
        assert any(x.endswith("target=/work/tests,readonly") for x in a)
        assert "/fixture/check.sh" in a and str(w.home) + "," not in joined
    led = [json.loads(x) for x in (w.store() / "mediator.jsonl").read_text().splitlines()]
    wall = [x for x in led if x["record"] == "wall"]
    assert len(wall) == 1 and wall[0]["requests"] == 0 and wall[0]["audit_head"]
    assert wall[0]["policy_sha256"] == "c0ca1aaa35e4d9239b41442e60542c257a1ab617552aa31eca8df9c62f61b087"
    assert hashlib.sha256((w.store() / "wall" / "policy.toml").read_bytes()).hexdigest() == wall[0]["policy_sha256"]


def test_level2_policy_hash_differs_refused(w):
    env, log, wall_dir = level2(w, tamper_policy=True)
    w.project()
    w.brief(CP_HEADER)
    p = w.eq("plan", "--run", R, env=dict(env, STACK_EQ_WALL="required"))
    assert p.returncode == 4 and "differs from the reviewed" in p.stderr
    p = w.eq("plan", "--run", R, env=env)                    # auto: falls back to Level 1, says why
    assert p.returncode == 0
    plan = json.loads((w.store() / "plan.json").read_text())
    assert plan["w3"] == "sandbox" and "differs from the reviewed" in plan["w3_reason"]
    assert not log.exists() or "run\x1f" not in log.read_text()


def test_level2_policy_changed_after_plan_refused(w):
    env, log, wall_dir = level2(w)
    w.project()
    w.brief(CP_HEADER)
    assert w.eq("plan", "--run", R, env=env).returncode == 0
    w.consent()
    assert w.eq("start", "--run", R, env=env).returncode == 0
    two_candidates(w)
    assert w.eq("prepare-check", "--run", R, "--round", "0", env=env).returncode == 0
    with open(wall_dir / "policy.default.toml", "a") as f:
        f.write("# edited\n")
    p = w.eq("check-container", "--run", R, "--round", "0", env=env)
    assert p.returncode == 4 and "Level 2 unavailable" in p.stderr
    assert not log.exists() or not any(ln.startswith("run\x1f") for ln in log.read_text().splitlines())
    assert not (w.store() / "r0" / "check-c1.json").exists()


def _iso():
    spec = importlib.util.spec_from_file_location("eqi_u", eqworld.HOOKS_SRC / "eq_isolation.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_wall_refuses_a_policy_other_than_the_reviewed(w):
    env, _log, wall_dir = level2(w, tamper_policy=True)
    iso = _iso()
    cfg = {"wall_dir": str(wall_dir), "tunnel_dir": str(w.t / "tun"), "wall_state": str(w.t / "wst")}
    store_wall = w.t / "storewall"
    store_wall.mkdir()
    with pytest.raises(iso.IsolationError, match="reviewed default-deny policy"):
        iso.Wall(cfg, str(store_wall))
    assert not (store_wall / "policy.toml").exists()


def test_isolation_mount_and_cli_guards(w, monkeypatch):
    iso = _iso()
    monkeypatch.setenv("HOME", str(w.home))
    cfg = {"bin": "/usr/bin/true", "image": IMG, "limits": dict(iso.LIMITS)}
    st = w.state
    st.mkdir(parents=True, exist_ok=True)
    (w.home / ".ssh").mkdir()
    proj = w.home / "proj"
    proj.mkdir()
    i = iso.Isolation(cfg, forbidden=(str(st),))
    for bad in (w.home, w.home / ".ssh", st, w.t):
        with pytest.raises(iso.IsolationError):
            i.check_mount(str(bad), "/work")
    assert i.check_mount(str(proj), "/work") == os.path.realpath(proj)
    for ctr in ("/", "/tmp/x", "/eq/tunnel", "/eqsrc/work", "/work/../etc"):
        with pytest.raises(iso.IsolationError):
            i.check_mount(str(proj), ctr)
    shim = proj / "container"
    shim.write_text("#!/bin/sh\n")
    shim.chmod(0o755)
    with pytest.raises(iso.IsolationError, match="agent-writable"):
        iso.container_bin({"STACK_EQ_CONTAINER_BIN": str(shim)}, unsafe_roots=(str(proj),))
    with pytest.raises(iso.IsolationError):
        iso.container_bin({"STACK_EQ_CONTAINER_BIN": str(proj / "missing")})


def test_level2_needs_a_passing_tunnel_probe(w):
    env, log, _ = level2(w)
    f = w.state / "eq-container" / "results" / "tunnel.cp.env"
    f.write_text(f.read_text().replace("TUNNEL_RESULT=PASS", "TUNNEL_RESULT=FAIL"))
    w.project()
    w.brief(CP_HEADER)
    p = w.eq("plan", "--run", R, env=dict(env, STACK_EQ_WALL="required"))
    assert p.returncode == 4 and "tunnel probe" in p.stderr


def test_level2_needs_the_wall_on(w):
    env, log, _ = level2(w)
    w.manifest["eq_wall"]["status"] = "off"
    w.write_manifest()
    w.project()
    w.brief(CP_HEADER)
    p = w.eq("plan", "--run", R, env=dict(env, STACK_EQ_WALL="required"))
    assert p.returncode == 4 and "WALL is not on" in p.stderr


def test_level2_unavailable_without_manifest(w):
    w.project()
    w.brief(CP_HEADER)
    p = w.eq("plan", "--run", R, env=w.env(STACK_EQ_N="2", STACK_EQ_WALL="required"))
    assert p.returncode == 4 and "eq_container" in p.stderr


# ---------------------------------------------------------------- the real eq_core, once it exists
@pytest.mark.skipif(not (eqworld.REAL_CORE / "eq_core.py").exists(),
                    reason="hooks/eq_core.py (sibling build) not present yet (EQ_CORE_SRC points at its worktree)")
def test_real_eq_core_end_to_end(tmp_path):
    w = World(tmp_path, core="real")
    files = {"a.md": "segment a\n", "b.md": "segment b\n", "c.md": "c\n", "d.md": "d\n"}
    w.project(files)
    w.brief({"class": "ES", "segments": sorted(files)})
    p = w.eq("plan", "--run", R, env=w.env(STACK_EQ_N="3"))
    assert p.returncode == 0, p.stderr
    w.consent()
    assert w.eq("start", "--run", R).returncode == 0
    w.members({str(i): {"agent_id": "m%d" % i, "worktree": None, "status": "stopped", "rounds": {"0": "captured"}}
               for i in (1, 2, 3)})
    for i in (1, 2, 3):
        w.capture(0, i, {"answer": 42, "evidence": [], "confidence": 0.5})
    p = w.eq("reduce", "--run", R, "--round", "0")
    assert p.returncode == 0, p.stderr
    p = w.eq("result", "--run", R)
    assert p.returncode == 0, p.stderr
    assert json.loads((w.store() / "result.json").read_text())["validated"] is False


def test_launchers_shell_clean():
    for f in ("stack-eq", "stack-eq-check"):
        path = REPO / "dot-claude" / "bin" / f
        assert subprocess.run(["/bin/sh", "-n", str(path)]).returncode == 0
        assert os.access(path, os.X_OK)
        text = path.read_text()
        assert "--eq-executor" in text if f == "stack-eq" else "--eq-check-runner" in text
        code = [ln for ln in text.splitlines() if not ln.lstrip().startswith("#")]
        assert not any("STACK_PYTHON" in ln or "PATH" in ln for ln in code)     # the stack-python beside it only
