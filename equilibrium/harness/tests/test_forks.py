"""E2 (COMPARE_eq §12 A6.1; RUNTIME_EQUILIBRIUM §10.3 last bullet): reconcile and repair calls fork the member's
session (`--resume <parent> --fork-session`), the ledger records `parent_session_id`, a CP branch works on its own
workdir copy, round-0 sessions stay unmodified, `modelUsage` ids are recorded; and the stub that makes this testable
(new session id per fork, per-session turn log, `--session-id`, `modelUsage`, scripted file writes)."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any

import pytest

import eq_harness as eh
from conftest import HARNESS, dry_run, ledger

STUB = HARNESS / "stub_claude"


def stub(tmp: Path, *args: str, head: str = "XX-1 p3 m1/5", cwd: Path | None = None,
         script: dict[str, Any] | None = None) -> tuple[int, dict[str, Any]]:
    env = dict(os.environ, EQ_STUB_STATE=str(tmp / "st"))
    env.pop("EQ_STUB_SCRIPT", None)
    if script is not None:
        (tmp / "script.json").write_text(json.dumps(script))
        env["EQ_STUB_SCRIPT"] = str(tmp / "script.json")
    cp = subprocess.run(["uv", "run", "--script", "--quiet", str(STUB), "-p", *args], input=head + "\nbody\n",
                        capture_output=True, text=True, env=env, cwd=cwd or tmp, check=False)
    return cp.returncode, json.loads(cp.stdout)


def state(tmp: Path, sid: str) -> dict[str, Any]:
    out: dict[str, Any] = json.loads((tmp / "st" / f"{sid}.json").read_text())
    return out


def test_stub_fork_gives_a_new_session_and_leaves_the_parent_untouched(tmp_path: Path) -> None:
    rc, r0 = stub(tmp_path)
    assert rc == 0
    s0 = r0["session_id"]
    rc, f1 = stub(tmp_path, "--resume", s0, "--fork-session", head="XX-1 p3 r1")
    rc2, f2 = stub(tmp_path, "--resume", s0, "--fork-session", head="XX-1 p3 r1")
    assert rc == rc2 == 0 and len({s0, f1["session_id"], f2["session_id"]}) == 3  # two forks, two new ids
    assert state(tmp_path, s0)["turns"] == ["XX-1 p3 m1/5"]  # the parent is pristine
    assert state(tmp_path, f1["session_id"])["turns"] == ["XX-1 p3 m1/5", "XX-1 p3 r1"]
    assert state(tmp_path, f1["session_id"])["parent"] == s0 and state(tmp_path, f1["session_id"])["role"] == "m1/5"
    rc, g = stub(tmp_path, "--resume", f1["session_id"], "--fork-session", head="XX-1 p3 r2")  # a fork of a fork
    assert state(tmp_path, g["session_id"])["turns"] == ["XX-1 p3 m1/5", "XX-1 p3 r1", "XX-1 p3 r2"]
    assert state(tmp_path, f1["session_id"])["turns"] == ["XX-1 p3 m1/5", "XX-1 p3 r1"]
    rc, same = stub(tmp_path, "--resume", s0, head="XX-1 p3 r1")  # in place: the same id, the log grows
    assert same["session_id"] == s0 and state(tmp_path, s0)["turns"] == ["XX-1 p3 m1/5", "XX-1 p3 r1"]


def test_stub_session_id_unknown_resume_and_model_usage(tmp_path: Path) -> None:
    sid = "0f8fad5b-d9cb-469f-a165-70867728950e"
    rc, r = stub(tmp_path, "--session-id", sid, "--model", "opus")
    assert rc == 0 and r["session_id"] == sid and list(r["modelUsage"]) == ["claude-opus-stub"]
    rc, r = stub(tmp_path, "--session-id", sid)
    assert rc == 1 and r["is_error"] is True  # an id in use is refused
    rc, r = stub(tmp_path, "--resume", "no-such-session", "--fork-session")
    assert rc == 1 and r["is_error"] is True
    rc, r = stub(tmp_path, "--fork-session")
    assert rc == 1
    rc, r = stub(tmp_path, "--model", "claude-sonnet-x-1")
    assert list(r["modelUsage"]) == ["claude-sonnet-x-1"] and r["model"] == "claude-sonnet-x-1"


def test_stub_writes_scripted_files_inside_the_cwd_only(tmp_path: Path) -> None:
    wd = tmp_path / "wd"
    wd.mkdir()
    rc, _ = stub(tmp_path, cwd=wd, script={"XX-1|p3|m1/5": {"write": {"a/b.txt": "hi"}}})
    assert rc == 0 and (wd / "a" / "b.txt").read_text() == "hi"
    for bad in ("../x.txt", "/tmp/x.txt"):
        rc, _ = stub(tmp_path, cwd=wd, script={"XX-1|p3|m1/5": {"write": {bad: "no"}}})
        assert rc == 1
    assert not (tmp_path / "x.txt").exists()


def test_build_argv_fork_flags() -> None:
    flags = dict(eh.DEFAULT_FLAGS)
    a = eh.build_argv("c", "verifier", 1, {}, ["Read"], flags, resume="sid-1", fork=True)
    assert a[-3:] == ["--resume", "sid-1", "--fork-session"]
    with pytest.raises(ValueError):
        eh.build_argv("c", "verifier", 1, {}, ["Read"], flags, fork=True)


def _session_root(run: Path) -> Path:
    return run / "stub_state"


ES_SPLIT = {f"ES-DEV1|p3|m{i}/5": {"structured_output": {"answer": v, "evidence": [], "confidence": 0.5}}
            for i, v in enumerate((1.0, 100.0, 10000.0, 1e6, 1e8), start=1)}  # no quorum: a reconcile round runs


@pytest.fixture(scope="module")
def split_run(stub_bin: Path, tmp_path_factory: pytest.TempPathFactory) -> Path:
    return dry_run(stub_bin, tmp_path_factory.mktemp("split"), script=ES_SPLIT, only=["ES-DEV1", "CP-DEV1"])


def test_reconcile_and_repair_fork_the_members_session(split_run: Path) -> None:
    calls = [r for r in ledger(split_run) if r["record"] == "call"]
    by_sid = {c["session_id"]: c for c in calls}
    later = [c for c in calls if c["round"] >= 1]
    assert later and {c["cls"] for c in later} >= {"CP", "ES"}  # repair (CP) and reconcile (ES)
    for c in later:
        a = c["argv"]
        i = a.index("--resume")
        assert a[i + 1] == c["resume"] == c["parent_session_id"] and a[i + 2] == "--fork-session"
        parent = by_sid[c["parent_session_id"]]
        assert parent["round"] == c["round"] - 1 and parent["member"] == c["member"] and parent["item"] == c["item"]
        assert c["session_id"] != c["parent_session_id"]  # a fork is a new session
    for c in calls:
        if c["round"] == 0:
            assert c["parent_session_id"] is None and "--fork-session" not in c["argv"]


def test_round0_sessions_stay_unmodified(split_run: Path) -> None:
    calls = [r for r in ledger(split_run) if r["record"] == "call"]
    forked = {c["parent_session_id"] for c in calls if c["parent_session_id"]}
    assert len(forked) >= 10  # 5 ES reconcile + 5 CP repair forks (+ EG E-node repairs)
    for sid in forked:
        st = json.loads((_session_root(split_run) / f"{sid}.json").read_text())
        assert len(st["turns"]) == 1, (sid, st["turns"])  # only its own round-0 turn


def test_model_ids_recorded_per_call(full_run: Path) -> None:
    calls = [r for r in ledger(full_run) if r["record"] == "call"]
    for c in calls:
        a = c["argv"]
        alias = a[a.index("--model") + 1]
        assert c["model_ids"] == [f"claude-{alias}-stub"] and c["model_ids_reason"] is None
        assert alias == eh.DEFAULT_FLAGS["model"][c["agent"]]  # D3: the agent's own frontmatter model


def test_model_ids_of_reasons() -> None:
    assert eh.model_ids_of({}) == ([], "no result envelope (stdout is not one JSON object)")
    assert eh.model_ids_of({"x": 1})[0] == [] and eh.model_ids_of({"modelUsage": {}})[0] == []
    assert eh.model_ids_of({"modelUsage": {"b": {}, "a": {}}}) == (["a", "b"], None)


def test_cp_repair_runs_on_its_own_branch_copy(stub_bin: Path, tmp_path: Path) -> None:
    fix = {"answer": "fix", "evidence": [], "confidence": 0.5}
    run = dry_run(stub_bin, tmp_path, script={"CP-DEV1|p3|m2/5>r1": {"structured_output": fix,
                                                                       "write": {"repaired.txt": "m2"}}},
                  only=["CP-DEV1"])
    recs = ledger(run)
    rep = [c for c in recs if c["record"] == "call" and c["label"] == "p3" and c["role"] == "r1"]
    assert rep
    for c in rep:
        wd, bwd = Path(c["cwd"]), Path(c["branch_workdir"])
        assert bwd == wd.with_name(wd.name + ".live") and bwd.is_dir() and wd.with_name(wd.name + ".r0").is_dir()
        assert not (wd / "repaired.txt").exists()  # the member's own path holds the round-0 bytes again
        assert eh.tree_digest(wd) == eh.tree_digest(wd.with_name(wd.name + ".r0"))
    m2 = next(c for c in rep if c["member"] == 2)
    assert (Path(m2["branch_workdir"]) / "repaired.txt").read_text() == "m2"
    arm = next(r for r in recs if r["record"] == "item_arm" and r["label"] == "p3")
    assert arm["selected_member"] == 2 and arm["repaired"] is True
    assert arm["answer_workdir"] == m2["branch_workdir"]  # graded on the branch copy, not the round-0 copy
    chk = [r for r in recs if r["record"] == "check" and r["label"] == "p3" and r["round"] == 1]
    assert any(r["member"] == 2 and r["passed"] for r in chk)


def test_fork_workdir_restores_round0_bytes_on_error(tmp_path: Path) -> None:
    import threading

    wd = tmp_path / "m1"
    wd.mkdir()
    (wd / "a.txt").write_text("r0")
    lock = threading.Lock()
    with pytest.raises(RuntimeError), eh.fork_workdir(wd, "rotation", lock) as saved:
        (wd / "a.txt").write_text("branch")
        raise RuntimeError("boom")
    assert (wd / "a.txt").read_text() == "r0" and (saved / "a.txt").read_text() == "branch"
    with eh.fork_workdir(wd, "rotation", lock):  # the branch continues from its own state
        assert (wd / "a.txt").read_text() == "branch"
        (wd / "b.txt").write_text("2")
    with eh.fork_workdir(wd, "none", lock):  # another branch starts from round 0
        assert (wd / "a.txt").read_text() == "r0" and not (wd / "b.txt").exists()
    assert sorted(p.name for p in tmp_path.iterdir()) == ["m1", "m1.none", "m1.r0", "m1.rotation"]
    for bad in ("r0", "../x", "A", ""):
        with pytest.raises(ValueError):
            eh.fork_copy_paths(wd, bad)
