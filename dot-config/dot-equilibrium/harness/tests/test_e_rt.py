"""E_rt (COMPARE_eq §12 A6.5, A6 note (d); contracts §11): `run --e-arm runtime` drives the runtime itself through a
FAKE stack-eq (plan writes the store's plan.json; start checks the consent file's token, plan sha256 and mode, then
writes result.json) and the stub claude (`--session-id`). Covered: the argv order of both steps and of the leader call,
the 0600 consent bytes, CLAUDECODE never reaching stack-eq or claude, the refusal paths (-> partial, no call), the
`e_rt` ledger steps, the answer taken from result.json, CP's selected patch, and the `bundle_mismatch` rule against
`--params` (the p-selected `candidate` bundle: USER decision 2026-10-06)."""

from __future__ import annotations

import hashlib
import json
import stat
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

import eq_harness as eh
from conftest import FIXT_FLAGS, ITEMS, ledger, run_harness, stub_env

FAKE_STACK_EQ = '''#!{python}
"""fake stack-eq: plan / start of contracts §11 (headless), logging argv and the CLAUDECODE it saw. Its knobs are
STACK_EQ_FAKE_*: e_rt_env passes stack-eq only XDG_STATE_HOME and the STACK_EQ* knobs."""
import hashlib, json, os, re, stat, sys
a = sys.argv[1:]
log = os.environ.get("STACK_EQ_FAKE_LOG")
if log:
    with open(log, "a") as f:
        f.write(json.dumps({{"argv": a, "claudecode": os.environ.get("CLAUDECODE"),
                            "xdg": os.environ.get("XDG_STATE_HOME"), "cwd": os.getcwd()}}) + "\\n")
def opt(n):
    return a[a.index(n) + 1]
run = opt("--run")
def store(sid):
    safe = re.sub(r"[^A-Za-z0-9_-]", "_", sid)
    return os.path.join(os.environ["XDG_STATE_HOME"], "claude-agent-stack", safe, "eq", run)
if a[0] == "plan":
    if os.environ.get("STACK_EQ_FAKE_PLAN_RC"):
        print("refused: fake"); sys.exit(int(os.environ["STACK_EQ_FAKE_PLAN_RC"]))
    sid = opt("--session")
    if hashlib.sha256((sid + "|headless").encode()).hexdigest()[:8] != run:
        print("run id mismatch"); sys.exit(4)
    d = store(sid)
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, ".sid"), "w") as f:
        f.write(sid)
    brief = open(opt("--brief-file")).read()
    if not brief.startswith("eq-run: " + run + "\\n") or "eq-mode: manual" not in brief:
        print("bad brief"); sys.exit(5)
    if os.environ.get("STACK_EQ_FAKE_NO_PLAN"):
        sys.exit(0)
    plan = json.load(open(os.environ["STACK_EQ_FAKE_PLAN"]))
    with open(os.path.join(d, "plan.json"), "w") as f:
        json.dump(plan, f)
    print("planned"); sys.exit(0)
if a[0] == "start":
    if os.environ.get("STACK_EQ_FAKE_START_RC"):
        sys.exit(int(os.environ["STACK_EQ_FAKE_START_RC"]))
    root = os.path.join(os.environ["XDG_STATE_HOME"], "claude-agent-stack")
    d = next(os.path.join(root, s, "eq", run) for s in os.listdir(root)
             if os.path.isdir(os.path.join(root, s, "eq", run)))
    cf = opt("--consent-file")
    if stat.S_IMODE(os.stat(cf).st_mode) != 0o600:
        print("consent file mode"); sys.exit(6)
    c = json.load(open(cf))
    psha = hashlib.sha256(open(os.path.join(d, "plan.json"), "rb").read()).hexdigest()
    if c != {{"token": "Run eq:" + run, "plan_sha256": psha}}:
        print("consent mismatch"); sys.exit(7)
    if os.environ.get("STACK_EQ_FAKE_RESULT"):
        res = json.load(open(os.environ["STACK_EQ_FAKE_RESULT"]))
        with open(os.path.join(d, "result.json"), "w") as f:
            json.dump(res, f)
    print("started"); sys.exit(0)
sys.exit(9)
'''

BUNDLE = {"member_type": "researcher", "member_model_id": "claude-opus-test-1", "N": 5, "rounds": 1, "view": "kcover",
          "loo_view": "rotation", "reducer": "R0", "tau": 0.6, "t": 2,
          "caps": {"member_tokens": 60000, "member_turns": 30, "run_tokens": 660000}}


def params_file(tmp: Path, status: str = "candidate", **over: Any) -> Path:
    classes = {c: {k: None for k in ("status", *eh.BUNDLE_KEYS)} | {"status": "not_run"} for c in eh.CLASSES}
    classes["RS"] = {**BUNDLE, "status": status, "pool": {"name": "RS pool"}, **over}
    classes["CP"] = {**BUNDLE, "member_type": "python-engineer", "view": "perm", "status": status}
    p = tmp / "params.json"
    p.write_text(json.dumps({"schema": "eqparams.v1", "version": 1, "classes": classes}))
    return p


def setup(tmp: Path, stub_bin: Path, item: str, *, plan: dict[str, Any] | None = None,
          result: dict[str, Any] | None = None, **knobs: str) -> tuple[dict[str, str], list[str]]:
    se = tmp / "stack-eq"
    se.write_text(FAKE_STACK_EQ.format(python=sys.executable))
    se.chmod(0o755)
    (tmp / "plan.json").write_text(json.dumps({"schema": "eqplan.v1", "mode": "manual", "validated": False,
                                               "status_reasons": ["manual"], "params_sha256": None,
                                               **(plan if plan is not None else BUNDLE)}))
    (tmp / "result.json").write_text(json.dumps(result if result is not None else
                                                {"answer_text": {"label": "SUPPORTED", "value": "", "why": "w"},
                                                 "validated": False, "status_reason": "manual", "partial": False}))
    flags = dict(FIXT_FLAGS)
    flags["member_env_passthrough"] = ["CLAUDE_CONFIG_DIR", "CLAUDECODE"]  # the pop in e_rt_env must matter
    (tmp / "flags.json").write_text(json.dumps(flags))
    cls = item.split("-")[0]
    (tmp / "sched.tsv").write_text("\t".join(eh.SCHEDULE_HEADER) + f"\n1\t1\t{item}\t{cls}\tE\tp3\n")
    env = stub_env(stub_bin, tmp, XDG_STATE_HOME=str(tmp / "state"), CLAUDECODE="1",
                   STACK_EQ_FAKE_LOG=str(tmp / "se.log"), STACK_EQ_FAKE_PLAN=str(tmp / "plan.json"),
                   STACK_EQ_FAKE_RESULT=str(tmp / "result.json"), **knobs)
    args = ["run", "--stage", "d", "--eq-root", str(tmp / "eq"), "--raw-root", str(tmp / "raw"), "--items",
            str(ITEMS), "--flags", str(tmp / "flags.json"), "--schedule", str(tmp / "sched.tsv"), "--no-check",
            "--e-arm", "runtime", "--stack-eq", str(se)]
    return env, args


def se_log(tmp: Path) -> list[dict[str, Any]]:
    p = tmp / "se.log"
    return [json.loads(x) for x in p.read_text().splitlines()] if p.exists() else []


def stub_calls(tmp: Path) -> list[dict[str, Any]]:
    p = tmp / "stub_log.jsonl"
    return [json.loads(x) for x in p.read_text().splitlines()] if p.exists() else []


def arm(tmp: Path) -> dict[str, Any]:
    recs = [r for r in ledger(tmp) if r["record"] == "item_arm"]
    assert len(recs) == 1
    return recs[0]


def test_e_rt_happy_path_argv_consent_env_and_answer(stub_bin: Path, tmp_path: Path) -> None:
    env, args = setup(tmp_path, stub_bin, "RS-DEV1")
    cp = run_harness(args, env)
    assert cp.returncode == 0, cp.stderr
    a = arm(tmp_path)
    sid, run8 = a["rt_session_id"], a["run8"]
    assert run8 == hashlib.sha256(f"{sid}|headless".encode()).hexdigest()[:8]
    steps = [(s["step"], s["rc"], s["output_tail"]) for s in ledger(tmp_path) if s["record"] == "e_rt"]
    assert a["status"] == "ok", (a.get("reason"), a.get("result_error"), steps)
    assert a["answer"] == {"label": "SUPPORTED", "value": "", "why": "w"}
    assert a["e_arm"] == "runtime" and a["arm"] == "E" and "h5" not in a  # COMPARE_eq §12 A7 removed H5
    assert (a["rt_validated"], a["rt_status_reason"], a["rt_partial"]) == (False, "manual", False)
    assert a["rt_plan_status_reasons"] == ["manual"] and "bundle_mismatch" not in a
    d = Path(a["answer_path"]).parent / "e_rt"
    brief, consent = d / "brief.txt", d / "consent.json"
    se = str(tmp_path / "stack-eq")
    steps = [r for r in ledger(tmp_path) if r["record"] == "e_rt"]
    assert [(s["step"], s["rc"]) for s in steps] == [("plan", 0), ("start", 0)]
    assert steps[0]["argv"] == [se, "plan", "--run", run8, "--headless", "--session", sid, "--brief-file", str(brief)]
    assert steps[1]["argv"] == [se, "start", "--run", run8, "--headless", "--consent-file", str(consent)]
    log = se_log(tmp_path)
    assert [x["argv"][0] for x in log] == ["plan", "start"]
    assert all(x["claudecode"] is None and x["xdg"] == str(tmp_path / "state") for x in log)  # CLAUDECODE dropped
    store = eh.eq_store_dir({"XDG_STATE_HOME": str(tmp_path / "state")}, sid, run8)
    plan_sha = hashlib.sha256((store / "plan.json").read_bytes()).hexdigest()
    assert consent.read_bytes() == json.dumps({"token": f"Run eq:{run8}", "plan_sha256": plan_sha},
                                              sort_keys=True).encode()
    assert stat.S_IMODE(consent.stat().st_mode) == 0o600 and stat.S_IMODE(brief.stat().st_mode) == 0o600
    text = brief.read_text()
    assert text.startswith(f"eq-run: {run8}\neq-class: RS\neq-mode: manual\neq-type: researcher\n")
    assert "\n---\nFake RS task 1." in text
    calls = [r for r in ledger(tmp_path) if r["record"] == "call"]
    assert len(calls) == 1 and calls[0]["role"] == "rt" and calls[0]["agent"] == "equilibrium"
    assert a["calls"] == [calls[0]["call_id"]] and calls[0]["e_arm"] == "runtime" and calls[0]["run8"] == run8
    st = stub_calls(tmp_path)
    assert len(st) == 1 and st[0]["head"] == f"eq-run: {run8}"
    model = eh.DEFAULT_FLAGS["model"]["equilibrium"]
    assert st[0]["argv"] == ["-p", "--agent", "equilibrium", "--model", model, "--session-id", sid,
                             "--max-budget-usd", "2.000000", "--output-format", "json"]
    assert st[0]["session_id"] == sid and st[0]["cwd"] == calls[0]["cwd"]


@pytest.mark.parametrize(("knobs", "reason", "steps"), [
    ({"STACK_EQ_FAKE_PLAN_RC": "3"}, "stack-eq plan refused", [("plan", 3)]),
    ({"STACK_EQ_FAKE_NO_PLAN": "1"}, "no plan.json in the store (FileNotFoundError)", [("plan", 0)]),
    ({"STACK_EQ_FAKE_START_RC": "2"}, "stack-eq start refused", [("plan", 0), ("start", 2)]),
])
def test_e_rt_refusals_end_partial_without_a_call(stub_bin: Path, tmp_path: Path, knobs: dict[str, str],
                                                  reason: str, steps: list[tuple[str, int]]) -> None:
    env, args = setup(tmp_path, stub_bin, "RS-DEV1", **knobs)
    cp = run_harness(args, env)
    assert cp.returncode == 0, cp.stderr
    a = arm(tmp_path)
    assert (a["status"], a["answer"], a["reason"], a["calls"]) == ("partial", None, reason, [])
    assert [(s["step"], s["rc"]) for s in ledger(tmp_path) if s["record"] == "e_rt"] == steps
    assert not [r for r in ledger(tmp_path) if r["record"] == "call"] and not stub_calls(tmp_path)


def test_e_rt_unreadable_result_is_partial_with_result_error(stub_bin: Path, tmp_path: Path) -> None:
    env, args = setup(tmp_path, stub_bin, "RS-DEV1")
    env.pop("STACK_EQ_FAKE_RESULT")  # start writes no result.json
    cp = run_harness(args, env)
    assert cp.returncode == 0, cp.stderr
    a = arm(tmp_path)
    assert a["status"] == "partial" and a["answer"] is None and a["result_error"] == "FileNotFoundError"
    assert len(a["calls"]) == 1  # the leader ran; its store holds no result


def test_bundle_mismatch_stops_before_start(stub_bin: Path, tmp_path: Path) -> None:
    env, args = setup(tmp_path, stub_bin, "RS-DEV1", plan={**BUNDLE, "N": 3})  # the runtime resolved another N
    cp = run_harness([*args, "--params", str(params_file(tmp_path))], env)
    assert cp.returncode == 0, cp.stderr
    a = arm(tmp_path)
    assert (a["status"], a["answer"], a["reason"], a["calls"]) == ("partial", None, "bundle_mismatch", [])
    assert a["bundle_mismatch"] == {"plan_bundle": {**BUNDLE, "N": 3}, "expected_bundle": BUNDLE}
    assert [s["step"] for s in ledger(tmp_path) if s["record"] == "e_rt"] == ["plan"]  # no start, no consent file
    assert not (Path(a["answer_path"]).parent / "e_rt" / "consent.json").exists() and not stub_calls(tmp_path)
    start = next(r for r in ledger(tmp_path) if r["record"] == "run_start")
    assert start["e_rt_params_sha256"] == hashlib.sha256((tmp_path / "params.json").read_bytes()).hexdigest()


def test_bundle_match_runs(stub_bin: Path, tmp_path: Path) -> None:
    env, args = setup(tmp_path, stub_bin, "RS-DEV1")
    cp = run_harness([*args, "--params", str(params_file(tmp_path))], env)
    assert cp.returncode == 0, cp.stderr
    a = arm(tmp_path)
    assert a["status"] == "ok" and "bundle_mismatch" not in a and len(a["calls"]) == 1


@pytest.mark.parametrize(("extra", "why"), [
    (["--e-arm", "harness"], "--params is E_rt's"),
    (["--stage", "q"], "needs --params"),
    (["--params", "STATUS:not_run"], "no runnable bundle"),
    (["--params", "STATUS:candidate:N=null"], "are null"),
    (["--params", "NOFILE"], "--params:"),
])
def test_run_refuses_bad_params(stub_bin: Path, tmp_path: Path, extra: list[str], why: str) -> None:
    env, args = setup(tmp_path, stub_bin, "RS-DEV1")
    if extra[:1] == ["--stage"]:
        args[args.index("--stage") + 1] = "q"
        args.remove("--no-check")
        extra = []
    elif extra[:1] == ["--e-arm"]:
        args[args.index("--e-arm") + 1] = "harness"
        extra = ["--params", str(params_file(tmp_path))]
    elif extra[1].startswith("STATUS:"):
        parts = extra[1].split(":")
        over = {"N": None} if parts[2:] == ["N=null"] else {}
        extra = ["--params", str(params_file(tmp_path, parts[1], **over))]
    else:
        extra = ["--params", str(tmp_path / "nope.json")]
    cp = run_harness([*args, *extra], env)
    assert cp.returncode == 2 and why in cp.stderr, cp.stderr
    assert not se_log(tmp_path) and not stub_calls(tmp_path)


def test_e_rt_cp_applies_the_selected_patch(stub_bin: Path, tmp_path: Path) -> None:
    """CP: result.json's patches.selected (a file in the leader's project dir) applied with git apply to a fresh
    fixture copy, the answer_workdir; a patch outside the project dir is refused with a reason."""
    fixture = ITEMS / "CP" / "fixtures" / "base"
    name = sorted(p.name for p in fixture.iterdir() if p.is_file())[0]
    old = (fixture / name).read_text()
    new = old + "# patched by E_rt\n"
    for side, text in (("a", old), ("b", new)):
        (tmp_path / "pa" / side).mkdir(parents=True)
        (tmp_path / "pa" / side / name).write_text(text)
    diff = subprocess.run(["git", "diff", "--no-index", "--no-prefix", "--no-color", f"a/{name}", f"b/{name}"],
                          cwd=tmp_path / "pa", capture_output=True, text=True, check=False).stdout
    assert f"--- a/{name}" in diff and f"+++ b/{name}" in diff  # git apply strips one level: <name>
    env, args = setup(tmp_path, stub_bin, "CP-DEV1",
                      plan={**BUNDLE, "member_type": "python-engineer", "view": "perm"},
                      result={"answer_text": "done", "patches": {"selected": "sel.patch"}})
    # the leader's project dir is the E_rt work copy: put the patch there through the stub's scripted write
    (tmp_path / "script.json").write_text(json.dumps({"*": {"write": {"sel.patch": diff}}}))
    env["EQ_STUB_SCRIPT"] = str(tmp_path / "script.json")
    cp = run_harness(args, env)
    assert cp.returncode == 0, cp.stderr
    a = arm(tmp_path)
    assert a["answer"] == "done" and a["answer_workdir"], a.get("answer_workdir_reason")
    assert (Path(a["answer_workdir"]) / name).read_text() == new
    assert (fixture / name).read_text() == old  # the frozen fixture is untouched


def test_e_rt_cp_patch_outside_the_project_dir_is_refused(stub_bin: Path, tmp_path: Path) -> None:
    outside = tmp_path / "evil.patch"
    outside.write_text("not a patch\n")
    env, args = setup(tmp_path, stub_bin, "CP-DEV1", plan={**BUNDLE, "member_type": "python-engineer", "view": "perm"},
                      result={"answer_text": "done", "patches": {"selected": str(outside)}})
    cp = run_harness(args, env)
    assert cp.returncode == 0, cp.stderr
    a = arm(tmp_path)
    assert a["answer_workdir"] is None and "not a file inside" in a["answer_workdir_reason"]


def test_e_rt_env_drops_claudecode_keeps_state_and_knobs(monkeypatch: pytest.MonkeyPatch) -> None:
    for k, v in (("CLAUDECODE", "1"), ("XDG_STATE_HOME", "/s"), ("STACK_EQ_MAX_N", "5"), ("STACK_EQX", "no"),
                 ("SECRET_TOKEN", "t")):
        monkeypatch.setenv(k, v)
    env = eh.e_rt_env({"member_env_passthrough": ["CLAUDECODE"]}, False)
    assert "CLAUDECODE" not in env and env["XDG_STATE_HOME"] == "/s" and env["STACK_EQ_MAX_N"] == "5"
    assert "STACK_EQX" not in env and "SECRET_TOKEN" not in env


def test_eq_store_dir_and_bundle_helpers() -> None:
    env = {"XDG_STATE_HOME": "/x", "HOME": "/h"}
    assert eh.eq_store_dir(env, "a b/c", "0123abcd") == Path("/x/claude-agent-stack/a_b_c/eq/0123abcd")
    assert eh.eq_store_dir({"HOME": "/h"}, "s", "0123abcd") == Path("/h/.local/state/claude-agent-stack/s/eq/0123abcd")
    for bad in ("0123ABCD", "0123abc", "../../x"):
        with pytest.raises(ValueError):
            eh.eq_store_dir(env, "s", bad)
    assert eh.bundle_of({**BUNDLE, "status": "candidate", "pool": {}}) == BUNDLE
    p = {"classes": {"RS": {**BUNDLE, "status": "candidate"}, "CP": {**BUNDLE, "status": "not_run"}}}
    assert eh.expected_bundle_problems(p, ["RS"]) == []
    assert "CP: status 'not_run'" in eh.expected_bundle_problems(p, ["CP", "RS"])[0]
    for k in eh.BUNDLE_KEYS:  # every bundle key non-null, member_model_id included (eq_policy.CANDIDATE_REQUIRED)
        q = {"classes": {"RS": {**BUNDLE, "status": "candidate", k: None}}}
        assert eh.expected_bundle_problems(q, ["RS"]) == [f"RS: bundle keys {[k]} are null"]
