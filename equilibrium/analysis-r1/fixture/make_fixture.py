# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Build the zero-spend stub fixture for the analysis routes (route 1 eq_analyse.py, route 2 eq_route2.sql).

Usage (from anywhere):  uv run --script analysis-r1/fixture/make_fixture.py --out <dir>

Everything model-shaped comes from harness/stub_claude (no API, no spend), on the fake pool
harness/tests/fixtures/items, stage d, isolation "off" (agent sandbox: no docker daemon), with a stub script
(EQ_STUB_SCRIPT) that adds disagreement, a reconcile round, budget-cap stops and one over-cap item-arm.

Output:
  <dir>/run/                  the run dir to analyse (= $EQ/runs/d after `eq_freeze.sh --collect`):
      ledger.jsonl            the harness ledger (LEDGER_SCHEMA.md), untouched
      grading_results/ES.jsonl   real: `eq_harness.py score --cls ES` (fake ES oracle)
      grading_results/CR.jsonl   real: `cr-grader-input --with-members` + `cr-grade` on SYNTHETIC verdicts
      grading_results/PF.jsonl, CP.jsonl   SYNTHETIC (the fake pool has no PF/CP oracle): one line per item-arm in
                              the LEDGER_SCHEMA.md format, score = seeded coin, 0 for `partial` (exit null)
      inputs/mediator/<item>/<label>/mediator.jsonl   copied from the raw root (live + offline-facts), as --collect
  <dir>/partial/ledger.jsonl  the ledger cut just before one item_arm record, plus a torn last line
  <dir>/empty/ledger.jsonl    0 bytes
  <dir>/work/                 eq-root, raw-root, stub state (scratch)

RS, DS and OE have no grading-results format in LEDGER_SCHEMA.md, so none is written.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
STAGE_DIR = HERE.parent.parent  # EQ-T
HARNESS = STAGE_DIR / "harness"
ITEMS = HARNESS / "tests" / "fixtures" / "items"


def coin(*parts: str) -> int:
    return int(hashlib.sha256("|".join(("eq-fixture", *parts)).encode()).hexdigest()[:8], 16)


STUB_SCRIPT = {
    # RS-DEV2 E: a 2-2-1 split (kappa0 = 0.4 < tau) -> one reconcile round; m5 switches without new evidence
    "RS-DEV2|p3|m1/5": {"structured_output": {"answer": "alpha", "evidence": [], "confidence": 0.9}},
    "RS-DEV2|p3|m2/5": {"structured_output": {"answer": "beta", "evidence": [], "confidence": 0.6}},
    "RS-DEV2|p3|m3/5": {"structured_output": {"answer": "alpha", "evidence": [], "confidence": 0.7}},
    "RS-DEV2|p3|m4/5": {"structured_output": {"answer": "beta", "evidence": [], "confidence": 0.4}},
    "RS-DEV2|p3|m5/5": {"structured_output": {"answer": "gamma", "evidence": [], "confidence": 0.2}},
    "RS-DEV2|p3|m5/5>r1": {"structured_output": {"answer": "alpha", "evidence": [], "confidence": 0.5}},
    # ES: spread E members, a perfect S*, an over-cap S* (cost 2.5 > 1.1 * B = 2.2), a G answer of 0 (e = inf)
    "ES-DEV1|p3|m1/5": {"structured_output": {"answer": 50.0, "evidence": [], "confidence": 0.5}},
    "ES-DEV1|p3|m2/5": {"structured_output": {"answer": 90.0, "evidence": [], "confidence": 0.5}},
    "ES-DEV1|p3|m3/5": {"structured_output": {"answer": 105.0, "evidence": [], "confidence": 0.5}},
    "ES-DEV1|p3|m4/5": {"structured_output": {"answer": 400.0, "evidence": [], "confidence": 0.5}},
    "ES-DEV1|p3|m5/5": {"structured_output": {"answer": 1000.0, "evidence": [], "confidence": 0.5}},
    "ES-DEV1|p1|s": {"structured_output": {"answer": 150.0, "evidence": [], "confidence": 0.7}, "cost": 2.5},
    "ES-DEV2|p1|s": {"structured_output": {"answer": 100.0, "evidence": [], "confidence": 0.7}},
    "ES-DEV3|p2|n2": {"structured_output": {"answer": 0.0, "evidence": [], "confidence": 0.7}},
    # budget-cap stops (cap_stop = subtype contains "budget")
    "PF-DEV2|p1|s": {"subtype": "error_max_budget_usd"},
    "CR-DEV1|p3|m2/5": {"subtype": "error_max_budget_usd"},
    "RS-DEV1|p2|n1": {"subtype": "error_max_budget_usd"},
}


def run(cmd: list[str], env: dict[str, str]) -> None:
    cp = subprocess.run(cmd, env=env, capture_output=True, text=True, check=False)
    sys.stderr.write(cp.stdout[-400:] + cp.stderr[-400:])
    if cp.returncode != 0:
        raise SystemExit(f"make_fixture: failed ({cp.returncode}): {' '.join(cmd)}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    out = Path(a.out).resolve()
    if out.exists():
        shutil.rmtree(out)
    work = out / "work"
    (work / "bin").mkdir(parents=True)
    (work / "bin" / "claude").symlink_to(HARNESS / "stub_claude")
    pg = work / "bin" / "pgrep"
    pg.write_text('#!/bin/sh\ncat "${EQ_FAKE_PGREP:-/dev/null}"\n')
    pg.chmod(0o755)
    (work / "stub_script.json").write_text(json.dumps(STUB_SCRIPT, indent=1, sort_keys=True))
    env = dict(os.environ)
    env.update({"PATH": f"{work / 'bin'}:{env.get('PATH', '')}", "EQ_STUB_STATE": str(work / "stub_state"),
                "EQ_STUB_LOG": str(work / "stub_log.jsonl"), "EQ_STUB_SCRIPT": str(work / "stub_script.json")})
    h = ["uv", "run", "--script", "--quiet", str(HARNESS / "eq_harness.py")]
    m = ["uv", "run", "--script", "--quiet", str(HARNESS / "eq_mediator.py")]
    eq, raw, flags, sched = work / "eq", work / "raw", work / "flags.json", work / "schedule.tsv"
    run([*h, "flags", "--items", str(ITEMS), "--isolation", "off", "--out", str(flags)], env)
    run([*h, "schedule", "--items", str(ITEMS), "--stage", "d", "--out", str(sched)], env)
    run([*h, "run", "--stage", "d", "--eq-root", str(eq), "--raw-root", str(raw), "--items", str(ITEMS),
         "--flags", str(flags), "--schedule", str(sched), "--no-check"], env)
    run([*m, "offline-facts", "--stage", "d", "--eq-root", str(eq), "--raw-root", str(raw), "--items", str(ITEMS),
         "--flags", str(flags)], env)
    run([*h, "score", "--stage", "d", "--cls", "ES", "--eq-root", str(eq), "--items", str(ITEMS), "--flags",
         str(flags)], env)
    run([*h, "cr-grader-input", "--stage", "d", "--eq-root", str(eq), "--items", str(ITEMS), "--with-members"], env)
    rd = eq / "runs" / "d"
    batch = json.loads((rd / "grading" / "CR" / "batch.json").read_text())
    verdicts = [{"rid": r["rid"], "verdict": "false" if coin("cr", r["rid"]) % 4 == 0 else "true", "note": "synthetic"}
                for r in batch]
    (work / "cr_verdicts.json").write_text(json.dumps(verdicts))
    run([*h, "cr-grade", "--stage", "d", "--verdicts", str(work / "cr_verdicts.json"), "--eq-root", str(eq),
         "--items", str(ITEMS)], env)
    led_lines = (rd / "ledger.jsonl").read_text().splitlines(keepends=True)
    recs = [json.loads(x) for x in led_lines]
    gr = rd / "grading_results"
    for cls in ("PF", "CP"):
        with (gr / f"{cls}.jsonl").open("w") as f:
            for r in recs:
                if r["record"] != "item_arm" or r["cls"] != cls:
                    continue
                part = r["status"] == "partial"
                s = 0 if part else coin(cls, r["item"], r["label"]) % 2
                f.write(json.dumps({"ts_utc": r["ts_utc"], "item": r["item"], "label": r["label"],
                                    "exit": None if part else 0, "score": s, "score_num": float(s),
                                    "score_inf": False, "detail": "SYNTHETIC fixture grade", "isolation": "off",
                                    "image": None}, sort_keys=True) + "\n")
    run_dir = out / "run"
    run_dir.mkdir()
    shutil.copy2(rd / "ledger.jsonl", run_dir / "ledger.jsonl")
    shutil.copytree(gr, run_dir / "grading_results")
    for med in sorted((raw / "d").glob("*/*/mediator.jsonl")):
        dst = run_dir / "inputs" / "mediator" / med.parent.parent.name / med.parent.name / "mediator.jsonl"
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(med, dst)
    # partial: cut right before the 10th item_arm record (its calls stay, its item_arm is gone), then a torn line
    idx = [i for i, r in enumerate(recs) if r["record"] == "item_arm"][9]
    (out / "partial").mkdir()
    (out / "partial" / "ledger.jsonl").write_text("".join(led_lines[:idx]) + led_lines[idx][: len(led_lines[idx]) // 2])
    (out / "empty").mkdir()
    (out / "empty" / "ledger.jsonl").write_text("")
    print(f"fixture: {run_dir} ({len(recs)} ledger records); partial and empty ledgers beside it")
    return 0


if __name__ == "__main__":
    sys.exit(main())
