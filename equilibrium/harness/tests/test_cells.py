"""A6.3 calibration cells and the stage-p/q CLI (COMPARE_eq §12 A6.3, A6.5): `schedule --cells p6,p7` appends cell
rows after the arm rows (whose bytes stay a prefix), `run` skips them, `run --cells p6,p7` runs only them; p6 = 9
round-0 members at the N = 5 per-member cap, every record tagged cell p6; p7 = one forked branch per LOO variant from
p3's pristine round-0 sessions, each forced through 2 rounds (r2 forks r1's fork) at 0.025 B per member-round, with
the variant's exclusion on every call; p7 is skipped without p3's round 0; stage q's --primary/--n draw; the
blinding regex knows the cell labels. Stage d with the stub (zero spend)."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import eq_mediator as em
import pytest

import eq_harness as eh
from conftest import FIXT_FLAGS, ITEMS, STAGE, run_harness, stub_env

ONLY = ["RS-DEV1", "CP-DEV1"]


def run_args(tmp: Path, sched: Path, *extra: str) -> list[str]:
    return ["run", "--stage", "d", "--eq-root", str(tmp / "eq"), "--raw-root", str(tmp / "raw"), "--items",
            str(ITEMS), "--flags", str(tmp / "flags.json"), "--schedule", str(sched), "--no-check", *extra]


def ledger_of(tmp: Path) -> list[dict[str, Any]]:
    return eh.read_ledger(tmp / "eq" / "runs" / "d" / "ledger.jsonl")


@pytest.fixture(scope="module")
def cells_run(stub_bin: Path, tmp_path_factory: pytest.TempPathFactory) -> Iterator[dict[str, Any]]:
    """schedule --cells p6,p7; run (arm rows only); run --cells p6,p7; RS-DEV1 and CP-DEV1."""
    tmp = tmp_path_factory.mktemp("cells")
    env = stub_env(stub_bin, tmp)
    sched = tmp / "schedule.tsv"
    cp = run_harness(["schedule", "--items", str(ITEMS), "--stage", "d", "--cells", "p6,p7", "--out", str(sched)], env)
    assert cp.returncode == 0, cp.stderr
    (tmp / "flags.json").write_text(json.dumps(FIXT_FLAGS))
    cp = run_harness(run_args(tmp, sched, "--only", *ONLY), env)
    assert cp.returncode == 0, cp.stderr
    after_arms = ledger_of(tmp)
    cp = run_harness(run_args(tmp, sched, "--only", *ONLY, "--cells", "p6,p7"), env)
    assert cp.returncode == 0, cp.stderr
    yield {"tmp": tmp, "env": env, "sched": sched, "after_arms": after_arms, "recs": ledger_of(tmp)}


# ---- schedule -------------------------------------------------------------------------------------------------

def test_cell_rows_are_appended_after_an_unchanged_prefix(stub_bin: Path, tmp_path: Path) -> None:
    env = stub_env(stub_bin, tmp_path)
    plain, cells = tmp_path / "plain.tsv", tmp_path / "cells.tsv"
    assert run_harness(["schedule", "--items", str(ITEMS), "--stage", "d", "--out", str(plain)], env).returncode == 0
    cp = run_harness(["schedule", "--items", str(ITEMS), "--stage", "d", "--cells", "p7,p6", "--out", str(cells)], env)
    assert cp.returncode == 0 and "cell rows" in cp.stdout, cp.stderr
    assert cells.read_bytes().startswith(plain.read_bytes())
    arms, rows = eh.read_schedule(plain), eh.read_schedule(cells)
    extra = rows[len(arms):]
    flags = eh.load_flags(None)
    first_seq = {r.item: r.item_seq for r in arms}
    want = [(it, c) for it in sorted(first_seq, key=first_seq.__getitem__) for c in eh.CELLS
            if it.split("-")[0] in flags["cells"][c]["classes"]]
    assert [(r.item, r.arm) for r in extra] == want  # item order of the arm rows, p6 before p7, cell classes only
    assert all(r.arm == r.label and r.item_seq == first_seq[r.item] and r.cls == r.item.split("-")[0] for r in extra)
    assert [r.seq for r in rows] == list(range(1, len(rows) + 1))
    assert {r.cls for r in extra if r.arm == "p7"} == {"RS", "ES"}
    assert {r.cls for r in extra if r.arm == "p6"} == {"PF", "CP", "CR", "ES", "RS"}


def test_cell_rows_follow_the_flags_cell_classes() -> None:
    arms = eh.build_schedule(["RS-DEV1", "PF-DEV1"], "d")
    flags = eh.load_flags(None)
    flags["cells"]["p6"]["classes"] = ["PF"]
    got = eh.cell_rows(arms, ["p6", "p7"], flags)
    assert sorted((r.item, r.arm) for r in got) == [("PF-DEV1", "p6"), ("RS-DEV1", "p7")]
    assert got[0].seq == len(arms) + 1 and eh.cell_rows(arms, [], flags) == []
    for bad in (["p8"], ["p6", "p6"], ["E"]):
        with pytest.raises(ValueError, match="--cells"):
            eh.cell_rows(arms, bad, flags)


@pytest.mark.parametrize(("args", "msg"), [
    (["--stage", "q", "--primary", "PF", "--n", "2", "--cells", "p6"], "belong to stage p"),
    (["--stage", "d", "--primary", "PF"], "stage q's"),
    (["--stage", "p", "--n", "3"], "stage q's"),
    (["--stage", "d", "--cells", "p6,p9"], "--cells"),
    (["--stage", "q"], "needs --primary"),
    (["--stage", "q", "--primary", "PF,CP,RS", "--n", "2"], "--primary"),
    (["--stage", "q", "--primary", "PF,PF", "--n", "2"], "--primary"),
    (["--stage", "q", "--primary", "XX", "--n", "2"], "--primary"),
    (["--stage", "q", "--primary", "PF", "--n", "0"], "needs --primary"),
])
def test_schedule_refusals(stub_bin: Path, tmp_path: Path, args: list[str], msg: str) -> None:
    out = tmp_path / "s.tsv"
    cp = run_harness(["schedule", "--items", str(ITEMS), *args, "--out", str(out), "--allow-missing"],
                     stub_env(stub_bin, tmp_path))
    assert cp.returncode == 2 and msg in cp.stderr and not out.exists(), (cp.stdout, cp.stderr)


def test_stage_q_draws_right_after_the_pilot() -> None:
    pools = {c: eh.load_pool(STAGE / "items", c) for c in eh.CLASSES}
    p = eh.stage_items(pools, "p")
    q = eh.stage_items(pools, "q", ["RS", "PF"], 7)
    for c in ("PF", "RS"):
        order = eh.draw_order([it.id for it in pools[c] if not it.dev])
        k = eh.PILOT_PER_CLASS[c]
        assert [i for i in p if i.startswith(c)] == order[:k]
        assert [i for i in q if i.startswith(c)] == order[k:k + 7]
    assert [i.split("-")[0] for i in q] == ["PF"] * 7 + ["RS"] * 7  # CLASSES order, primary classes only
    assert not set(p) & set(q)
    big = len([it for it in pools["CP"] if not it.dev]) - eh.PILOT_PER_CLASS["CP"] + 1
    with pytest.raises(ValueError, match="cannot be primary"):
        eh.stage_items(pools, "q", ["CP"], big)
    assert len(eh.stage_items(pools, "q", ["CP"], big - 1)) == big - 1
    rows = eh.build_schedule(q, "q")
    assert {r.label[0] for r in rows} == {"q"} and len(rows) == 4 * len(q)


# ---- run: arm rows, then --cells ------------------------------------------------------------------------------

def test_run_without_cells_skips_the_cell_rows(cells_run: dict[str, Any]) -> None:
    first = cells_run["after_arms"]
    assert not any(r.get("cell") for r in first) and not any(r.get("label") in eh.CELLS for r in first)
    assert {(r["item"], r["label"]) for r in first if r["record"] == "item_arm"} == {
        (i, f"p{k}") for i in ONLY for k in (1, 2, 3, 4)}
    rs = [r for r in cells_run["recs"] if r["record"] == "run_start"]
    assert [r["cells"] for r in rs] == [[], ["p6", "p7"]]
    arms_after = [r for r in cells_run["recs"] if r["record"] == "item_arm" and r["label"] not in eh.CELLS]
    assert len(arms_after) == 8  # the cells run re-ran no arm row


def p6_cap(flags: dict[str, Any], cls: str, family: str) -> eh.CapPlan:
    b = eh.usd_to_micro(flags["B_usd"][cls])
    eqv = flags.get("equivalence", {}).get(cls) if family == "discrete" else None
    return eh.caps_enode(b, family, int(flags["N"]), min(int(flags["R_max"]), int(flags["R_max_ceiling"])), flags,
                         None if eqv is None else str(eqv["frac"]))


@pytest.mark.parametrize(("item", "family"), [("RS-DEV1", "discrete"), ("CP-DEV1", "checkable")])
def test_p6_nine_members_at_the_n5_cap_tagged(cells_run: dict[str, Any], item: str, family: str) -> None:
    recs = [r for r in cells_run["recs"] if r.get("item") == item and r.get("label") == "p6"]
    arm = next(r for r in recs if r["record"] == "item_arm")
    assert arm["arm"] == "E" and arm["cell"] == "p6" and arm["n_members"] == 9
    members = [r for r in recs if r["record"] == "call" and r.get("member") is not None]
    assert sorted(r["member"] for r in members) == list(range(1, 10))
    assert {r["role"] for r in members} == {f"m{i}/9" for i in range(1, 10)}
    assert all(r["round"] == 0 and r["cell"] == "p6" and r["branch"] is None and r["arm"] == "E" for r in members)
    c5 = p6_cap(FIXT_FLAGS, item.split("-")[0], family)
    assert {r["cap_usd"] for r in members} == {eh.micro_to_str(c5.calls["member"][0])}
    members_total = eh.frac_of(eh.usd_to_micro(FIXT_FLAGS["B_usd"][item.split("-")[0]]),
                               FIXT_FLAGS["families"][family]["members"])
    assert c5.calls["member"][0] == members_total // 5 > members_total // 9  # the N = 5 cap, not the N = 9 split
    assert len({r["session_id"] for r in members}) == 9 and not any(r["parent_session_id"] for r in members)
    assert set(arm["calls"]) == {r["call_id"] for r in recs if r["record"] == "call"}
    tagged = [r for r in recs if r["record"] in ("check", "reduce", "reconcile")]
    assert tagged and all(r.get("cell") == "p6" for r in tagged)
    assert not any(r["record"] == "reconcile" for r in recs) and not any(r.get("round", 0) for r in members)
    if family == "checkable":  # the public check once per candidate with an answer
        checks = [r for r in recs if r["record"] == "check"]
        assert sorted(r["member"] for r in checks) == sorted(r["member"] for r in members if r["answer"] is not None)
        assert next(r for r in recs if r["record"] == "reduce")["reducer"] == "verify_then_select"
    else:  # RS: the answer equivalence once on the 9-set, at the N = 5 equivalence cap
        eqs = [r for r in recs if r["record"] == "call" and r.get("member") is None]
        assert len(eqs) == 1 and eqs[0]["cap_usd"] == eh.micro_to_str(c5.calls["equivalence"][0])
        assert eqs[0]["cell"] == "p6"
        red = [r for r in recs if r["record"] == "reduce" and r["reducer"] == "plurality"]
        assert len(red) == 1 and red[0]["n"] == 9


def p7_calls(recs: list[dict[str, Any]], branch: str) -> list[dict[str, Any]]:
    return [r for r in recs if r["record"] == "call" and r.get("label") == "p7" and r.get("branch") == branch]


def test_p7_four_branches_two_forced_rounds_forked_from_p3(cells_run: dict[str, Any]) -> None:
    recs = cells_run["recs"]
    flags = FIXT_FLAGS
    cfg = flags["cells"]["p7"]
    arm = next(r for r in recs if r["record"] == "item_arm" and r["item"] == "RS-DEV1" and r["label"] == "p7")
    assert arm["cell"] == "p7" and arm["base_label"] == "p3" and arm["arm"] == "E"
    assert sorted(arm["branches"]) == sorted(cfg["branches"]) == ["leader", "none", "random", "rotation"]
    assert not any(r["item"] == "CP-DEV1" and r["label"] == "p7" for r in recs if r["record"] == "item_arm")
    p3 = next(r for r in recs if r["record"] == "item_arm" and r["item"] == "RS-DEV1" and r["label"] == "p3")
    r0 = {r["member"]: r for r in recs if r["record"] == "call" and r["call_id"] in p3["calls"]
          and r["round"] == 0 and r.get("member") is not None}
    n = len(r0)
    assert n == int(flags["N"]) == 5
    b = eh.usd_to_micro(flags["B_usd"]["RS"])
    cap = eh.caps_enode(b, "discrete", n, int(cfg["rounds"]), flags).calls["reconcile"][0]
    assert eh.micro_to_str(cap) == "0.050000"  # 0.25 B / (N * rounds) = 0.025 B
    all_ids: set[str] = set()
    for v in cfg["branches"]:
        calls = p7_calls(recs, v)
        assert len(calls) == n * int(cfg["rounds"])  # forced: every member, every round (no κ stop)
        assert all(c["cell"] == "p7" and c["cap_usd"] == eh.micro_to_str(cap) and c["loo_view"] == v for c in calls)
        by = {(c["member"], c["round"]): c for c in calls}
        assert set(by) == {(m, k) for m in range(1, n + 1) for k in (1, 2)}
        for m in range(1, n + 1):
            assert by[(m, 1)]["role"] == "r1" and by[(m, 2)]["role"] == "r2"
            assert by[(m, 1)]["parent_session_id"] == r0[m]["session_id"]  # r1 forks p3's round-0 session
            assert by[(m, 2)]["parent_session_id"] == by[(m, 1)]["session_id"]  # r2 forks r1's fork
            assert by[(m, 1)]["session_id"] != r0[m]["session_id"]
        all_ids |= {c["session_id"] for c in calls}
        tagged = [r for r in recs if r.get("label") == "p7" and r["record"] in ("reduce", "reconcile")
                  and r.get("branch") == v]
        assert tagged and all(r["cell"] == "p7" for r in tagged)
    assert len(all_ids) == 4 * n * 2  # no branch shares a session
    assert set(arm["calls"]) == {c["call_id"] for v in cfg["branches"] for c in p7_calls(recs, v)}
    for m, c in r0.items():  # the p3 round-0 sessions stay pristine (one turn): every branch forked a copy
        st = json.loads((cells_run["tmp"] / "stub_state" / f"{c['session_id']}.json").read_text())
        assert len(st["turns"]) == 1, (m, st["turns"])


def test_p7_exclusions_per_variant(cells_run: dict[str, Any]) -> None:
    recs = cells_run["recs"]
    n, seed = 5, "RS-DEV1|p7|E"
    ex = {v: {(c["member"], c["round"]): c["loo_exclude"] for c in p7_calls(recs, v)}
          for v in ("none", "rotation", "random", "leader")}
    assert set(ex["none"].values()) == {None}
    for (m, r), e in ex["rotation"].items():  # e_r(i) = (i - 1 + r) mod N, 1-based
        assert e == (m - 1 + r) % n + 1 and e != m
    for (m, r), e in ex["random"].items():
        assert e == em.loo_exclude("random", m, r, n, seed=seed) and e != m and 1 <= e <= n
    for r in (1, 2):  # leader: every other member leaves out the round's leader L; L itself its rotation
        es = {m: ex["leader"][(m, r)] for m in range(1, n + 1)}
        leaders = {e for m, e in es.items() if e != (m - 1 + r) % n + 1}
        assert len(leaders) <= 1
        lead = leaders.pop() if leaders else None
        if lead is not None:
            assert es[lead] == (lead - 1 + r) % n + 1
            assert all(e == lead for m, e in es.items() if m != lead)


def test_p7_is_skipped_without_p3_round0(stub_bin: Path, tmp_path: Path) -> None:
    env = stub_env(stub_bin, tmp_path)
    sched = tmp_path / "s.tsv"
    assert run_harness(["schedule", "--items", str(ITEMS), "--stage", "d", "--cells", "p7", "--out", str(sched)],
                       env).returncode == 0
    (tmp_path / "flags.json").write_text(json.dumps(FIXT_FLAGS))
    cp = run_harness(run_args(tmp_path, sched, "--only", "ES-DEV1", "--cells", "p7"), env)
    assert cp.returncode == 0 and "no complete harness E round 0 under p3" in cp.stderr, cp.stderr
    recs = ledger_of(tmp_path)
    assert not any(r["record"] in ("item_arm", "call") for r in recs)
    assert not (tmp_path / "stub_log.jsonl").exists() or not (tmp_path / "stub_log.jsonl").read_text().strip()


def test_run_cells_refusals(cells_run: dict[str, Any]) -> None:
    tmp, env, sched = cells_run["tmp"], cells_run["env"], cells_run["sched"]
    cp = run_harness(run_args(tmp, sched, "--only", "RS-DEV1", "--cells", "p6,p8"), env)
    assert cp.returncode == 2 and "--cells takes" in cp.stderr, cp.stderr
    n = len(ledger_of(tmp))
    cp = run_harness(["run", "--stage", "q", "--eq-root", str(tmp / "eq"), "--raw-root", str(tmp / "raw"), "--items",
                      str(ITEMS), "--flags", str(tmp / "flags.json"), "--schedule", str(sched), "--cells", "p6"], env)
    assert cp.returncode == 2 and "--cells takes" in cp.stderr, cp.stderr
    assert len(ledger_of(tmp)) == n


def test_role_token_re_redacts_cell_labels() -> None:
    s = eh.blind_text("p6 and p7 said; q9 m3/9 m10/9 too; p0 p10 xp6 p6x m3 stay")
    assert s == "[redacted] and [redacted] said; [redacted] [redacted] [redacted] too; p0 p10 xp6 p6x m3 stay"
    assert eh.ROLE_TOKEN_RE.fullmatch("p6") and eh.ROLE_TOKEN_RE.fullmatch("m9/9")
    assert not eh.ROLE_TOKEN_RE.search("p0") and not eh.ROLE_TOKEN_RE.search("p10")
