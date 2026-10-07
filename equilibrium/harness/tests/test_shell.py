"""eq_check.sh (E1-E11, injected faults) and eq_freeze.sh (refusal without c0, freeze and collect) in temp dirs."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import time
from pathlib import Path

import pytest

import eq_harness as eh
from conftest import FIXT, FIXT_FLAGS, HARNESS, ITEMS, STAGE, run_harness, stub_env

SID = "0f8fad5b-d9cb-469f-a165-70867728950e"


def sh(args: list[str], env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["bash", *args], env=env, capture_output=True, text=True, check=False)


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


@pytest.fixture
def world(tmp_path: Path, stub_bin: Path) -> dict[str, Path]:
    """A fake home (installed stack + manifest), main checkout W, frozen package EQ, all consistent: E1-E11 pass."""
    home, m = tmp_path / "home", tmp_path / "M"
    w = m / "claude_next_steps" / "work_carried"
    eq = w / "equilibrium"
    (home / ".claude" / "agents").mkdir(parents=True)
    (home / ".claude" / "agents" / "x.md").write_text("---\nmodel: sonnet\n---\n")
    (home / ".claude" / "stack.env").write_text("STACK_POLICY=1\n")
    man = {"commit": "a" * 40, "files": {"agents/x.md": sha(home / ".claude" / "agents" / "x.md")}}
    (home / ".claude" / ".stack-manifest.json").write_text(json.dumps(man))
    usage = home / ".local" / "state" / "claude-agent-stack" / "usage"
    usage.mkdir(parents=True)
    (usage / "runs3.csv").write_text(",".join(f"c{i}" for i in range(1, 20)) + "\n")
    c0 = w / "context-diet" / "arms" / "c0"
    (c0 / "inputs").mkdir(parents=True)
    (c0 / "DISPATCH_LOG.tsv").write_text("utc\tpid\tverdict\n2026-10-05\tP90\tPASS\n")
    (c0 / "inputs" / "FROZEN_AT.txt").write_text("frozen_at_utc: 2026-10-05T00:00:00Z\n")
    (c0 / "inputs" / "MANIFEST.sha256").write_text("")
    runs = eq / "runs" / "p"
    runs.mkdir(parents=True)
    rows = eh.build_schedule(["RS-0001", "ES-0001", "PF-0001"], "p")
    eh.write_schedule(rows, eq / "schedule.tsv")
    (eq / "COMPARE_eq.md").write_text("pre-registration\n")
    side = f"# frozen_at_utc: 2026-10-05T01:00:00Z\n{sha(eq / 'COMPARE_eq.md')}  ./COMPARE_eq.md\n"
    (eq / "COMPARE_eq.sha256").write_text(side)
    jq = subprocess.run(["jq", "-cS", ".files", str(home / ".claude" / ".stack-manifest.json")], capture_output=True,
                        text=True, check=True).stdout
    ver = subprocess.run([str(stub_bin / "claude"), "--version"], capture_output=True, text=True,
                         check=True).stdout.splitlines()[0]
    cfg = [f"claude_version: {ver}", f"stack_commit: {man['commit']}",
           f"manifest_files_digest: {hashlib.sha256(jq.encode()).hexdigest()}",
           f"stack_env_sha256: {sha(home / '.claude' / 'stack.env')}", "spend_ceiling_usd: 100",
           *[f"B_usd_{c}: 2.00" for c in eh.CLASSES]]
    (runs / "CONFIG.txt").write_text("\n".join(cfg) + "\n")
    first = rows[0].item
    return {"home": home, "m": m, "w": w, "eq": eq, "runs": runs, "c0": c0, "usage": usage, "bin": stub_bin,
            "first": Path(first), "tmp": tmp_path}


def check_env(wd: dict[str, Path], **extra: str) -> dict[str, str]:
    env = dict(os.environ)
    env.update({"PATH": f"{wd['bin']}:{env['PATH']}", "EQ_M": str(wd["m"]), "EQ_ROOT": str(wd["eq"]),
                "EQ_HOME": str(wd["home"]), "EQ_STUB_STATE": str(wd["tmp"] / "st")})
    env.update(extra)
    return env


def run_check(wd: dict[str, Path], item: str | None = None, cells: str | None = None,
              **extra: str) -> subprocess.CompletedProcess[str]:
    """eq_check.sh <item> p [<cells>]: without cells an arm-pass check, with them a cell-pass check (`run --cells`)."""
    return sh([str(HARNESS / "eq_check.sh"), item or str(wd["first"]), "p", *([cells] if cells else [])],
              check_env(wd, **extra))


def failed(cp: subprocess.CompletedProcess[str]) -> set[str]:
    return {ln.split()[1] for ln in cp.stdout.splitlines() if ln.startswith("FAIL ")}


def test_check_passes_on_a_clean_world(world: dict[str, Path]) -> None:
    cp = run_check(world)
    assert cp.returncode == 0, cp.stdout
    assert "VERDICT: PASS" in cp.stdout
    log = (world["runs"] / "DISPATCH_LOG.tsv").read_text().splitlines()
    assert log[-1].split("\t")[1:3] == [str(world["first"]), "PASS"]
    cp2 = run_check(world)  # a re-check of the last PASS with no call started
    assert cp2.returncode == 0


def test_check_fault_install_drift(world: dict[str, Path]) -> None:
    (world["home"] / ".claude" / "agents" / "x.md").write_text("edited\n")
    assert failed(run_check(world)) == {"E3"}
    man = world["home"] / ".claude" / ".stack-manifest.json"
    man.write_text(json.dumps({**json.loads(man.read_text()), "commit": "b" * 40}))
    assert {"E1", "E3"} <= failed(run_check(world))


def test_check_fault_open_c_arm(world: dict[str, Path]) -> None:
    c1 = world["w"] / "context-diet" / "arms" / "c1"
    c1.mkdir(parents=True)
    (c1 / "DISPATCH_LOG.tsv").write_text("utc\tpid\tverdict\nx\tP90\tPASS\n")
    cp = run_check(world)
    assert cp.returncode == 1 and failed(cp) == {"E6"}


def test_check_fault_concurrent_claude(world: dict[str, Path]) -> None:
    pids = world["tmp"] / "pids"
    pids.write_text("4242\n")
    cp = run_check(world, EQ_FAKE_PGREP=str(pids))
    assert cp.returncode == 1 and failed(cp) == {"E10"}
    other = world["usage"] / "runs3.csv"
    other.write_text(other.read_text() + ",".join(["x", "deadbeef-0000", *["0"] * 16, str(int(time.time()))]) + "\n")
    assert failed(run_check(world)) == {"E10"}


def test_check_fault_c0_not_collected(world: dict[str, Path]) -> None:
    (world["c0"] / "inputs" / "FROZEN_AT.txt").unlink()
    assert failed(run_check(world)) >= {"E5"}  # also E6: c0 has a PASS line and is now open


def write_ledger(path: Path, recs: list[dict[str, object]]) -> None:
    """A ledger as Ledger.append writes it: one JSON object per line, seq = its line number, final newline."""
    path.write_text("".join(json.dumps({"seq": i, **r}, sort_keys=True) + "\n" for i, r in enumerate(recs, 1)))


def test_check_fault_spend_ceiling(world: dict[str, Path]) -> None:
    led = world["runs"] / "ledger.jsonl"
    write_ledger(led, [{"record": "call", "item": "X", "total_cost_usd": c, "session_id": SID} for c in (40.0, 52.5)])
    cp = run_check(world)
    assert cp.returncode == 1 and failed(cp) == {"E11"}  # 92.5 + 4 x 2 > 100
    write_ledger(led, [{"record": "call", "item": "X", "total_cost_usd": 91.0}])
    assert run_check(world).returncode == 0  # 91 + 8 <= 100


def test_check_fault_torn_or_truncated_ledger(world: dict[str, Path]) -> None:
    """DRYRUN info: a truncated or torn ledger was caught only when a later jq call happened to fail. E12 checks it
    directly: one JSON object per line, seq = line number, a final newline."""
    led = world["runs"] / "ledger.jsonl"
    write_ledger(led, [{"record": "run_start"}, {"record": "call", "item": "X", "total_cost_usd": 1.0,
                                                 "session_id": SID}, {"record": "item_arm", "item": "X"}])
    cp = run_check(world)
    assert cp.returncode == 0 and "PASS E12 ledger intact (3 lines" in cp.stdout, cp.stdout
    data = led.read_bytes()
    lines = data.splitlines(keepends=True)
    for bad, want in ((data[:-1], {"E12"}),                      # final newline cut: every jq still parses it
                      (lines[0] + lines[2], {"E12"}),            # a line removed (seq gap): nothing else notices
                      (data[:-9], {"E11", "E12"}),               # torn last line
                      (lines[0][:-6] + b"\n" + lines[1], {"E11", "E12"})):  # torn line in the middle
        led.write_bytes(bad)
        cp = run_check(world)
        assert cp.returncode == 1 and failed(cp) == want, (bad, cp.stdout)


def test_check_faults_order_sidecar_version_env(world: dict[str, Path]) -> None:
    assert failed(run_check(world, item="PF-0001" if str(world["first"]) != "PF-0001" else "ES-0001")) == {"E7"}
    assert failed(run_check(world, item="RS-9999")) == {"E7"}
    (world["eq"] / "COMPARE_eq.md").write_text("edited\n")
    assert failed(run_check(world)) == {"E4"}
    (world["home"] / ".claude" / "stack.env").write_text("STACK_POLICY=2\n")
    cfg = world["runs"] / "CONFIG.txt"
    cfg.write_text(cfg.read_text().replace("claude_version: ", "claude_version: 9"))
    assert failed(run_check(world)) == {"E4", "E8", "E9"}
    cfg.unlink()
    assert {"E0", "E1", "E2", "E8", "E9", "E11"} <= failed(run_check(world))


def test_check_started_item_is_not_rechecked(world: dict[str, Path]) -> None:
    assert run_check(world).returncode == 0
    write_ledger(world["runs"] / "ledger.jsonl", [{"record": "call", "item": str(world["first"]), "session_id": SID,
                                                   "total_cost_usd": 0.1}])
    assert failed(run_check(world)) == {"E7"}


CELL_ITEMS = ["RS-0001", "ES-0001", "PF-0001", "DS-0001"]


def cell_world(world: dict[str, Path], armed: int | None = None,
               idle: str | None = None) -> tuple[list[eh.ScheduleRow], list[dict[str, object]]]:
    """A stage-p schedule with the p6 and p7 rows appended (PF: p6; RS, ES: p6 and p7; DS: none) and its arm pass:
    the first `armed` items (default all) checked in schedule order (each check must PASS), each then given a started
    arm call and every arm row's item_arm, except the item `idle`, which is checked and starts nothing.
    Returns the rows and the ledger records (written)."""
    rows = eh.build_schedule(CELL_ITEMS, "p")
    rows += eh.cell_rows(rows, ["p6", "p7"], eh.load_flags(None))
    eh.write_schedule(rows, world["eq"] / "schedule.tsv")
    items = list(dict.fromkeys(r.item for r in rows))
    items = items if armed is None else items[:armed]
    recs: list[dict[str, object]] = []
    for it in items:
        cp = run_check(world, it)
        assert cp.returncode == 0, cp.stdout
        if it == idle:
            continue
        recs.append({"record": "call", "item": it, "session_id": SID, "total_cost_usd": 0.01, "cell": None})
        recs += [{"record": "item_arm", "item": it, "label": r.label, "arm": r.arm}
                 for r in rows if r.item == it and r.arm not in eh.CELLS]
        write_ledger(world["runs"] / "ledger.jsonl", recs)
    return rows, recs


def cell_arms(rows: list[eh.ScheduleRow], item: str) -> list[str]:
    return [r.arm for r in rows if r.item == item and r.arm in eh.CELLS]


def cell_call(item: str, cell: str) -> dict[str, object]:
    return {"record": "call", "item": item, "label": cell, "session_id": SID, "total_cost_usd": 0.01, "cell": cell}


def cell_done(item: str, cell: str) -> dict[str, object]:
    return {"record": "item_arm", "item": item, "label": cell, "arm": "E", "cell": cell}


def test_check_cell_pass_follows_the_arm_rule_order(world: dict[str, Path]) -> None:
    """COMPARE_eq §12 A8: after the arm pass, whose E7 rule refuses every item again (each has a PASS line and started
    calls), a cell pass (`run --cells p6,p7`) walks the schedule the same way on its own PASS lines (log column
    `cells`): the next item with a <cells> row to do, or a re-check of the last cell PASS; a started row is not run
    again (§10) and done rows are not checked again."""
    rows, recs = cell_world(world)
    led = world["runs"] / "ledger.jsonl"
    order = list(dict.fromkeys(r.item for r in rows if r.arm in eh.CELLS))
    assert cell_arms(rows, "DS-0001") == [] and "DS-0001" not in order and len(order) == 3
    a, b, c = order
    assert failed(run_check(world, a)) == {"E7"}  # the arm rule: no arm row is left to check
    cp = run_check(world, b, cells="p6,p7")
    assert failed(cp) == {"E7"} and f"expected {a}, got {b}" in cp.stdout, cp.stdout
    cp = run_check(world, a, cells="p6,p7")
    assert cp.returncode == 0 and f"PASS E7 {a} is next in the p6,p7 pass" in cp.stdout, cp.stdout
    log = [ln.split("\t") for ln in (world["runs"] / "DISPATCH_LOG.tsv").read_text().splitlines()]
    assert log[0][-1] == "cells" and log[-1][1:3] == [a, "PASS"] and log[-1][6] == "p6,p7", log[-1]
    assert [ln[6] for ln in log[1:-2]] == [""] * 5  # the four arm checks and a's arm-rule FAIL (then b's cell FAIL)
    assert run_check(world, a, cells="p7,p6").returncode == 0  # a re-check of the last cell PASS (any cell order)
    assert run_check(world, b, cells="p6,p7").returncode == 0  # b is next: a was checked (its rows need not have run)
    assert failed(run_check(world, a, cells="p6,p7")) == {"E7"}  # a is neither next nor the last cell PASS now
    recs.append(cell_call(b, "p6"))
    write_ledger(led, recs)
    cp = run_check(world, b, cells="p6,p7")  # its p6 row started and is not done: not run again (§10)
    assert failed(cp) == {"E7"} and "has started" in cp.stdout, cp.stdout
    recs += [cell_done(b, x) for x in cell_arms(rows, b)]
    write_ledger(led, recs)
    cp = run_check(world, b, cells="p6,p7")
    assert failed(cp) == {"E7"} and "are done" in cp.stdout, cp.stdout
    assert run_check(world, c, cells="p6,p7").returncode == 0
    cp = run_check(world, "DS-0001", cells="p6,p7")
    assert failed(cp) == {"E7"} and "has no p6,p7 row" in cp.stdout, cp.stdout


def test_check_cell_pass_moves_past_a_held_item(world: dict[str, Path]) -> None:
    """Reviews of A8 (2026-10-07): a cell row that started and never finished (§10) holds only its own item, even when
    no cell PASS line covers it (a lost log line, a call made outside `run`): a p6,p7 pass refuses `two` and goes on
    to the next item; a p7-only walk can still run `two`'s p7 row (not started). (A row a cell check covered is out
    of the walk anyway: test_check_cell_pass_never_reruns_a_covered_row.)"""
    rows, recs = cell_world(world)
    led = world["runs"] / "ledger.jsonl"
    order = list(dict.fromkeys(r.item for r in rows if r.arm in eh.CELLS))
    two = next(it for it in order if cell_arms(rows, it) == ["p6", "p7"])
    after = order[order.index(two) + 1]
    for it in order[:order.index(two)]:
        recs += [cell_done(it, x) for x in cell_arms(rows, it)]
    recs.append(cell_call(two, "p6"))  # started, never finished, and no cell check line covers it
    write_ledger(led, recs)
    cp = run_check(world, two, cells="p6,p7")
    assert failed(cp) == {"E7"} and "has started" in cp.stdout, cp.stdout
    assert run_check(world, after, cells="p6,p7").returncode == 0  # the held item does not stop the pass
    assert run_check(world, two, cells="p7").returncode == 0  # its own p7 walk: the p7 row has not started


def two_cell_items(world: dict[str, Path]) -> tuple[list[eh.ScheduleRow], list[dict[str, object]], str, str]:
    """cell_world with every cell row done except those of the two p6+p7 items x, y (schedule order)."""
    rows, recs = cell_world(world)
    order = list(dict.fromkeys(r.item for r in rows if r.arm in eh.CELLS))
    x, y = [it for it in order if cell_arms(rows, it) == ["p6", "p7"]]
    recs += [cell_done(it, c) for it in order if it not in (x, y) for c in cell_arms(rows, it)]
    write_ledger(world["runs"] / "ledger.jsonl", recs)
    return rows, recs, x, y


def test_check_cell_recheck_covers_only_the_cells_its_line_named(world: dict[str, Path]) -> None:
    """Re-check of A8 (code-reviewer, 2026-10-07): after a p6-only walk over x then y, a p6,p7 pass must start at x;
    y's last cell PASS line named p6 only, so it is no re-check for y's p7 row (that would run before x's)."""
    _rows, recs, x, y = two_cell_items(world)
    led = world["runs"] / "ledger.jsonl"
    for it in (x, y):
        assert run_check(world, it, cells="p6").returncode == 0
        recs += [cell_call(it, "p6"), cell_done(it, "p6")]
        write_ledger(led, recs)
    cp = run_check(world, y, cells="p6,p7")
    assert failed(cp) == {"E7"} and f"expected {x}, got {y}" in cp.stdout, cp.stdout
    assert run_check(world, x, cells="p6,p7").returncode == 0


def test_check_cell_pass_never_reruns_a_covered_row(world: dict[str, Path]) -> None:
    """Re-check of A8 (security-auditor, 2026-10-07): `run --cells` runs every not-done row of the item, so an item
    is next only when no cell PASS line covers any of those rows. x's p6 row was checked and abandoned (never started)
    in a p6 walk that went on to y: a p6,p7 pass must not run it again; x's p7 row can still run in a p7 walk."""
    _rows, recs, x, y = two_cell_items(world)
    led = world["runs"] / "ledger.jsonl"
    assert run_check(world, x, cells="p6").returncode == 0
    assert run_check(world, y, cells="p6").returncode == 0
    recs += [cell_call(y, "p6"), cell_done(y, "p6")]
    write_ledger(led, recs)
    assert failed(run_check(world, x, cells="p6,p7")) == {"E7"}
    assert run_check(world, y, cells="p6,p7").returncode == 0  # y's one row to do (p7) is not covered
    assert run_check(world, x, cells="p7").returncode == 0  # x's p7 row alone, in a p7 walk


def test_check_arm_rule_reads_only_arm_check_lines(world: dict[str, Path]) -> None:
    """Re-check of A8 (security-auditor, 2026-10-07): a cell check's PASS line is not the arm rule's "last PASS". An
    item c whose arm rows were checked and abandoned (nothing started; not the last arm item) gets a cell PASS line in
    a p7 walk; an arm check of c must still fail E7 (its arm rows are not run after the cell pass started)."""
    items = list(dict.fromkeys(r.item for r in eh.build_schedule(CELL_ITEMS, "p")))
    c = next(it for it in items[:-1] if it.split("-")[0] in ("RS", "ES"))
    rows, recs = cell_world(world, idle=c)
    p7 = [it for it in dict.fromkeys(r.item for r in rows if r.arm == "p7")]
    recs += [cell_done(it, "p7") for it in p7[:p7.index(c)]]
    write_ledger(world["runs"] / "ledger.jsonl", recs)
    assert run_check(world, c, cells="p7").returncode == 0
    cp = run_check(world, c)
    assert failed(cp) == {"E7"} and "expected none (all done)" in cp.stdout, cp.stdout


def test_check_cell_pass_waits_for_every_arm_check(world: dict[str, Path]) -> None:
    """A8: a cell pass follows the arm pass: an item with no arm-check PASS line refuses every cell check."""
    rows, _recs = cell_world(world, armed=3)
    first = next(r.item for r in rows if r.arm in eh.CELLS)
    cp = run_check(world, first, cells="p6,p7")
    assert failed(cp) == {"E7"} and "1 item(s) have no arm-check PASS line" in cp.stdout, cp.stdout


def test_check_cell_pass_waits_for_the_last_arm_item(world: dict[str, Path]) -> None:
    """A8: the last arm-checked item must not still be runnable (its arm rows all done, or an arm call started: an
    environment failure, §10, which is not run again). An arm row that started and never finished, anywhere in the
    arm pass, does not block the cell pass (reviews of A8, 2026-10-07)."""
    items = list(dict.fromkeys(r.item for r in eh.build_schedule(CELL_ITEMS, "p")))
    rows, recs = cell_world(world, idle=items[-1])
    led = world["runs"] / "ledger.jsonl"
    first = next(r.item for r in rows if r.arm in eh.CELLS)
    cp = run_check(world, first, cells="p6,p7")
    assert failed(cp) == {"E7"} and f"{items[-1]} (last arm-checked) still has arm rows to run" in cp.stdout, cp.stdout
    recs.append({"record": "call", "item": items[-1], "session_id": SID, "total_cost_usd": 0.01, "cell": None})
    mid = next(r for r in rows if r.item == items[1] and r.arm not in eh.CELLS)
    recs = [r for r in recs if not (r["record"] == "item_arm" and (r["item"], r["label"]) == (mid.item, mid.label))]
    write_ledger(led, recs)  # the last item's arm calls started and never finished, and one middle arm row too
    assert run_check(world, first, cells="p6,p7").returncode == 0
    led.write_bytes(led.read_bytes()[:-9])  # a torn last line: the cell rule cannot read the ledger and fails closed
    cp = run_check(world, first, cells="p6,p7")
    assert failed(cp) == {"E7", "E11", "E12"} and "cannot be read" in cp.stdout, cp.stdout


@pytest.mark.parametrize(("stage", "cells"), [("p", "p8"), ("p", "p6,p6"), ("p", "p6,"), ("p", "p*"), ("q", "p6"),
                                              ("q", "p6,p7")])
def test_check_refuses_a_bad_cells_argument(world: dict[str, Path], stage: str, cells: str) -> None:
    cp = sh([str(HARNESS / "eq_check.sh"), str(world["first"]), stage, cells], check_env(world))
    assert cp.returncode == 2 and "cells" in cp.stderr, (cp.stdout, cp.stderr)
    assert not (world["eq"] / "runs" / stage / "DISPATCH_LOG.tsv").exists()  # a usage error logs nothing


# ---- eq_freeze.sh ---------------------------------------------------------------------------------------------------


@pytest.fixture
def staged(world: dict[str, Path]) -> dict[str, Path]:
    st = world["tmp"] / "STAGE"
    (st / "harness").mkdir(parents=True)
    for f in ("COMPARE_eq.md", "PROPOSAL.md", "MEDIATOR.md", "seeds.out"):
        shutil.copy(STAGE / f, st / f)
    for f in ("eq_harness.py", "eq_mediator.py", "eq_check.sh", "eq_freeze.sh", "flags.json", "stub_claude"):
        shutil.copy(HARNESS / f, st / "harness" / f)
    (st / "harness" / "LEDGER_SCHEMA.md").write_text("schema\n")
    (st / "harness" / "schedule.tsv").write_text("seq\titem_seq\titem\tclass\tarm\tlabel\n")
    shutil.copytree(ITEMS, st / "items")
    (st / "items" / "graders").mkdir()
    (st / "items" / "graders" / "RS.md").write_text("grader brief\n")
    for c in eh.CLASSES:
        d = st / "items" / c
        files = sorted(p for p in d.rglob("*") if p.is_file())
        (d / "pool.sha256").write_text("".join(f"{sha(p)}  {p.relative_to(d)}\n" for p in files))
    shutil.rmtree(world["eq"])
    return {**world, "stage": st}


def freeze_env(wd: dict[str, Path]) -> dict[str, str]:
    return check_env(wd, EQ_STAGE_DIR=str(wd["stage"]), EQ_RAW=str(wd["m"] / ".claude-work" / "equilibrium" / "runs"))


def test_freeze_refuses_without_c0(staged: dict[str, Path]) -> None:
    (staged["c0"] / "inputs" / "FROZEN_AT.txt").unlink()
    cp = sh([str(HARNESS / "eq_freeze.sh")], freeze_env(staged))
    assert cp.returncode == 1 and "c0 is not collected" in cp.stderr
    assert not staged["eq"].exists()
    cp = sh([str(HARNESS / "eq_freeze.sh"), "--collect", "p"], freeze_env(staged))
    assert cp.returncode == 1 and "c0 is not collected" in cp.stderr


def test_freeze_installs_and_writes_sidecar(staged: dict[str, Path]) -> None:
    env = freeze_env(staged)
    cp = sh([str(HARNESS / "eq_freeze.sh")], env)
    assert cp.returncode == 0, cp.stderr
    eq = staged["eq"]
    side = (eq / "COMPARE_eq.sha256").read_text()
    assert side.startswith("# frozen_at_utc: 20") and "  ./COMPARE_eq.md\n" in side and "  ./eq_harness.py\n" in side
    assert "  ./items/RS/manifest.jsonl\n" in side and "  ./items/lenses.json\n" in side
    body = "".join(ln for ln in side.splitlines(keepends=True) if not ln.startswith("#"))
    v = subprocess.run(["shasum", "-a", "256", "-c", "--quiet", "-"], cwd=eq, input=body, capture_output=True,
                       text=True, check=False)
    assert v.returncode == 0, v.stdout + v.stderr
    assert not os.access(eq / "eq_harness.py", os.W_OK)
    cp2 = sh([str(HARNESS / "eq_freeze.sh")], env)
    assert cp2.returncode == 1 and "already frozen" in cp2.stderr
    (eq / "runs" / "p").mkdir(parents=True)
    # collect: a ledger with one session, a transcript in the fake home, a git checkout that ignores .claude-work
    subprocess.run(["git", "init", "-q", str(staged["m"])], check=True)
    (staged["m"] / ".gitignore").write_text(".claude-work/\nclaude_next_steps/\n")
    proj = staged["home"] / ".claude" / "projects" / "-tmp-x"
    (proj / SID).mkdir(parents=True)
    (proj / f"{SID}.jsonl").write_text('{"type":"user"}\n')
    (proj / SID / "sub.jsonl").write_text("{}\n")
    raw = staged["m"] / ".claude-work" / "equilibrium" / "runs" / "p" / "RS-0001" / "p1" / "calls" / "0001_s"
    raw.mkdir(parents=True)
    (raw / "stdout.json").write_text("{}")
    (raw / "prompt.txt").write_text("RS-0001 p1 s\n")
    (raw.parents[1] / "mediator.jsonl").write_text('{"record": "claim"}\n')
    (eq / "runs" / "p" / "ledger.jsonl").write_text(json.dumps(
        {"record": "call", "session_id": SID, "raw_path": str(raw / "stdout.json"),
         "prompt_path": str(raw / "prompt.txt")}) + "\n")
    (eq / "runs" / "p" / "CONFIG.txt").write_text("label: p\n")
    cp3 = sh([str(HARNESS / "eq_freeze.sh"), "--collect", "p"], env)
    assert cp3.returncode == 0, cp3.stderr
    inp = eq / "runs" / "p" / "inputs"
    fa = (inp / "FROZEN_AT.txt").read_text()
    assert "sessions_copied: 1" in fa and "sessions_missing: none" in fa
    assert (raw.parents[4] / "p" / "transcripts" / "-tmp-x" / f"{SID}.jsonl").exists()
    assert (inp / "raw" / "p" / "RS-0001" / "p1" / "calls" / "0001_s" / "stdout.json").exists()
    assert (inp / "ledger.jsonl").exists() and (inp / "CONFIG.txt").exists()
    assert (inp / "mediator" / "RS-0001" / "p1" / "mediator.jsonl").exists()
    assert "  ./MEDIATOR.md\n" in side and "  ./eq_mediator.py\n" in side and "  ./seeds.out\n" in side
    v = subprocess.run(["shasum", "-a", "256", "-c", "--quiet", "MANIFEST.sha256"], cwd=inp, capture_output=True,
                       text=True, check=False)
    assert v.returncode == 0
    cp4 = sh([str(HARNESS / "eq_freeze.sh"), "--collect", "p"], env)
    assert cp4.returncode == 1 and "already collected" in cp4.stderr


@pytest.mark.parametrize("where", ["raw", "root"])
def test_collect_refuses_destinations_git_does_not_ignore(staged: dict[str, Path], where: str) -> None:
    """--collect copies transcripts to $R/<stage>/transcripts and inputs to $EQ/runs/<stage>/inputs: either inside a
    git work tree must be git-ignored there, whatever EQ_RAW / EQ_ROOT say (not only $M/.claude-work)."""
    env = freeze_env(staged)
    assert sh([str(HARNESS / "eq_freeze.sh")], env).returncode == 0
    subprocess.run(["git", "init", "-q", str(staged["m"])], check=True)
    (staged["m"] / ".gitignore").write_text(".claude-work/\nclaude_next_steps/\n")
    (staged["eq"] / "runs" / "p").mkdir(parents=True)
    (staged["eq"] / "runs" / "p" / "ledger.jsonl").write_text("")
    other = staged["tmp"] / "other"
    subprocess.run(["git", "init", "-q", str(other)], check=True)
    if where == "raw":
        env["EQ_RAW"] = str(other / "out")
        bad = other / "out" / "p" / "transcripts"
    else:  # inputs: point EQ_ROOT's runs/ at a tracked place by symlinking it into the other work tree
        (other / "runs").mkdir()
        shutil.rmtree(staged["eq"] / "runs")
        (staged["eq"] / "runs").symlink_to(other / "runs")
        (other / "runs" / "p").mkdir()
        (other / "runs" / "p" / "ledger.jsonl").write_text("")
        bad = staged["eq"] / "runs" / "p" / "inputs"
    cp = sh([str(HARNESS / "eq_freeze.sh"), "--collect", "p"], env)
    assert cp.returncode == 1 and f"{bad} is not git-ignored" in cp.stderr, cp.stderr
    assert not (other / "out").exists()


def test_freeze_refuses_a_broken_pool(staged: dict[str, Path]) -> None:
    (staged["stage"] / "items" / "RS" / "manifest.jsonl").write_text("tampered\n")
    cp = sh([str(HARNESS / "eq_freeze.sh")], freeze_env(staged))
    assert cp.returncode == 1 and "pool RS does not verify" in cp.stderr and not staged["eq"].exists()


def test_cell_pass_runs_through_eq_check_after_the_arm_pass(staged: dict[str, Path]) -> None:
    """COMPARE_eq §12 A8 end to end at $0 (the run plan's smoke recipe with the stub): a one-dev-item package with its
    p6/p7 rows frozen by eq_freeze.sh, `config`, the arm pass, then `run --stage p --cells p6,p7`. The harness passes
    the cells to eq_check.sh, E7 takes the cell rule, and both cell rows run (before A8 the cell pass stopped at E7)."""
    st, tmp = staged["stage"], staged["tmp"]
    env = stub_env(staged["bin"], tmp, EQ_M=str(staged["m"]), EQ_HOME=str(staged["home"]))
    allp = tmp / "sched.all.tsv"
    assert run_harness(["schedule", "--items", str(ITEMS), "--stage", "d", "--cells", "p6,p7", "--out", str(allp)],
                       env).returncode == 0
    lines = allp.read_text().splitlines()
    (st / "harness" / "schedule.tsv").write_text(
        "\n".join([lines[0], *[ln for ln in lines[1:] if ln.split("\t")[2] == "RS-DEV1"]]) + "\n")
    fl = dict(FIXT_FLAGS)
    fl["B_usd"] = {c: "0.50" for c in fl["B_usd"]}
    (st / "harness" / "flags.json").write_text(json.dumps(fl))
    seq = tmp / "smoke-eq"
    fz = subprocess.run(["bash", str(st / "harness" / "eq_freeze.sh")], capture_output=True, text=True, check=False,
                        env={**env, "EQ_STAGE_DIR": str(st), "EQ_ROOT": str(seq), "EQ_RAW": str(tmp / "rawc")})
    assert fz.returncode == 0, fz.stderr

    def h(*args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(["uv", "run", "--script", "--quiet", str(seq / "eq_harness.py"), *args],
                              env={**env, "EQ_ROOT": str(seq)}, capture_output=True, text=True, check=False)

    assert h("config", "--stage", "p", "--eq-root", str(seq), "--ceiling", "5").returncode == 0
    base = ["run", "--stage", "p", "--eq-root", str(seq), "--raw-root", str(tmp / "raw"), "--spend-ok"]
    cp = h(*base)
    assert cp.returncode == 0, cp.stdout + cp.stderr
    cp = h(*base, "--cells", "p6,p7")
    assert cp.returncode == 0, cp.stdout + cp.stderr
    assert "PASS E7 RS-DEV1 is next in the p6,p7 pass" in cp.stdout, cp.stdout
    recs = eh.read_ledger(seq / "runs" / "p" / "ledger.jsonl")
    labels = sorted(r["label"] for r in recs if r.get("record") == "item_arm" and r.get("item") == "RS-DEV1")
    assert labels == ["p1", "p2", "p3", "p4", "p6", "p7"], labels
    log = (seq / "runs" / "p" / "DISPATCH_LOG.tsv").read_text().splitlines()
    assert [ln.split("\t")[1:3] for ln in log[1:]] == [["RS-DEV1", "PASS"], ["RS-DEV1", "PASS"]]
    assert [ln.split("\t")[6] for ln in log[1:]] == ["", "p6,p7"]  # the arm check, then the cell check
    cp = h(*base, "--cells", "p6,p7")  # nothing left: no check, no call
    assert cp.returncode == 0 and len((seq / "runs" / "p" / "DISPATCH_LOG.tsv").read_text().splitlines()) == 3


def test_fixture_pool_is_untouched() -> None:
    assert not any((FIXT / "items" / c / "pool.sha256").exists() for c in eh.CLASSES)
