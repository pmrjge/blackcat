#!/usr/bin/env -S uv run --script --quiet
# /// script
# requires-python = ">=3.11"
# dependencies = ["duckdb"]
# ///
"""Analysis route 2 (DuckDB SQL) of the agent-equilibrium experiment: thin runner of eq_route2.sql.

    uv run --script harness/eq_route2.py --ledger <run dir> --out <dir> [--mediator-root <dir> ...]

<run dir> holds ledger.jsonl and (after grading) grading_results/<CLS>.jsonl, and, once collected, inputs/mediator/**/
mediator.jsonl (more mediator roots with --mediator-root; every mediator.jsonl below them is read).
Writes <out>/results.csv (quantity,class,arm,stat,value; value %.9g; rows sorted by all columns), <out>/quantities.txt
and <out>/meta.json (ledger sha256, seeds, counts, warnings).

What the runner does besides loading: (1) canonicalises each valid JSON line (sorted keys, non-finite constants as
strings): a bad line in the middle of a file is a hard error (exit 2), only a torn final fragment without a newline
(a crashed append) is skipped with a warning; (2) runs the SQL (--exclude-wall-used: every output on item-arms with
wall_used false; duplicated item_arm records and unscored item-arms are warned and counted in the n_* rows);
(3) the percentile bootstrap CIs (P1, P4, P5 and their sensitivities, AUROC of M5 and M15): SQL has no seeded
resampling, so the SQL leaves the per-item inputs in table boot_in and this script resamples them with a
`random.Random(seed)` (Mersenne Twister, stable across versions), B = 10000; (4) writes the files.
Exit codes: 0 = written (a partial or empty ledger gives partial or empty output and warnings in meta.json),
2 = input problem, 3 = internal failure. Never a traceback.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import random
import sys
from pathlib import Path
from typing import Any

BASE_SEED = 20261004
AUROC_SEED = 3066176665  # eq|auroc (COMPARE_eq 8.4)
BOOT_B = 10000
# P1/P4/P5 seeds as printed in COMPARE_eq 6 (checked against the formula in the tests)
PUBLISHED_SEEDS = {
    "eq|E-S*|P1": 943313030, "eq|E-G|P1": 391859146, "eq|EG-G|P1": 594628461,
    "eq|E-S*|P4": 1803240717, "eq|E-G|P4": 1866285162, "eq|EG-G|P4": 1599796053,
    "eq|E-S*|P5": 646548904, "eq|E-G|P5": 1744006119, "eq|EG-G|P5": 4118203276,
}
# quantities of COMPARE_eq 6 and MEDIATOR 6 that route 2 does not compute, with the reason (also in meta.json)
NOT_COMPUTED = {
    "H4": "needs the oracle score of counterfactual reducer outputs (R1, R3, ENS); the ledger has no such grades",
    "M1": "needs member-level oracle scores of round-0 answers; the ledger has item-arm grades only",
    "M6": "needs member-level correctness; the ledger has item-arm grades only",
    "M7": "needs member-level correctness; the ledger has item-arm grades only",
    "M9": "judge order-consistency data (DS, OE, selection) is not in the ledger contract",
    "M16": "needs member-level correctness; the ledger has item-arm grades only",
    "M17": "needs the accuracy-game Shapley values (analysis after grading)",
    "DS/OE win-tie-loss": "pairwise judge verdicts are not in the ledger contract",
}


def seed_for(tag: str) -> int:
    """20261004 ^ int(sha256(tag)[:8], 16): COMPARE_eq 6 / 8.4."""
    return BASE_SEED ^ int(hashlib.sha256(tag.encode()).hexdigest()[:8], 16)


class RouteError(Exception):
    pass


def read_jsonl(path: Path) -> tuple[list[tuple[int, str]], int | None]:
    """Valid lines (1-based line number, canonical JSON) and the line number of a torn last line (else None).

    Same rule as route 1: only the final fragment after the last newline may be bad JSON (a crash mid-append): it is
    skipped and reported. Any other bad line, or a line that is JSON but not an object, is a RouteError (exit 2)."""
    try:
        text = path.read_bytes().decode("utf-8", errors="replace")
    except OSError as e:
        raise RouteError(f"cannot read {path}: {e}") from e
    lines = text.split("\n")
    rows: list[tuple[int, str]] = []
    torn: int | None = None
    for i, line in enumerate(lines, 1):
        s = line.strip()
        if not s:
            continue
        try:
            obj = json.loads(s, parse_constant=lambda c: c)
        except ValueError as e:
            if i == len(lines):  # no newline after it: a torn final append
                torn = i
                continue
            raise RouteError(f"{path}: line {i} is not valid JSON ({str(e).splitlines()[0]})") from e
        if not isinstance(obj, dict):
            raise RouteError(f"{path}: line {i} is not a JSON object")
        rows.append((i, json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)))
    return rows, torn


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def fmt(v: float) -> str:
    return format(v, ".9g")


def percentile(sorted_vals: list[float], q: float) -> float:
    """Linear interpolation between order statistics (the numpy default)."""
    pos = (len(sorted_vals) - 1) * q
    lo = math.floor(pos)
    hi = min(lo + 1, len(sorted_vals) - 1)
    return sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * (pos - lo)


def median_sorted(s: list[float]) -> float:
    n = len(s)
    return (s[(n - 1) // 2] + s[n // 2]) / 2.0


def auroc(xs: list[float], ys: list[float]) -> float | None:
    """Mann-Whitney AUROC of x for y == 1 (ties half), rank form with average ranks."""
    n = len(xs)
    order = sorted(range(n), key=lambda i: xs[i])
    ranks = [0.0] * n
    i = 0
    while i < n:
        j = i
        while j + 1 < n and xs[order[j + 1]] == xs[order[i]]:
            j += 1
        r = (i + j) / 2.0 + 1.0
        for k in range(i, j + 1):
            ranks[order[k]] = r
        i = j + 1
    n1 = sum(1 for y in ys if y == 1)
    n0 = n - n1
    if n1 == 0 or n0 == 0:
        return None
    return (sum(ranks[k] for k in range(n) if ys[k] == 1) - n1 * (n1 + 1) / 2.0) / (n1 * n0)


def bootstrap_median(xs: list[float], b: int, seed: int) -> list[float]:
    rng = random.Random(seed)
    n = len(xs)
    out = []
    for _ in range(b):
        out.append(median_sorted(sorted(xs[int(rng.random() * n)] for _ in range(n))))
    return out


def bootstrap_auc(xs: list[float], ys: list[float], b: int, seed: int) -> list[float]:
    rng = random.Random(seed)
    n = len(xs)
    out = []
    for _ in range(b):
        idx = [int(rng.random() * n) for _ in range(n)]
        a = auroc([xs[i] for i in idx], [ys[i] for i in idx])
        if a is not None:
            out.append(a)
    return out


def load_tables(con: Any, ledger_dir: Path, mediator_roots: list[Path], warnings: list[str]) -> dict[str, Any]:
    con.execute("CREATE TABLE raw_ledger (ord BIGINT, rec JSON)")
    con.execute("CREATE TABLE raw_grading (cls VARCHAR, ord BIGINT, rec JSON)")
    con.execute("CREATE TABLE raw_mediator (ord BIGINT, rec JSON)")
    info: dict[str, Any] = {"torn_last_lines": 0}
    led = ledger_dir / "ledger.jsonl"
    rows, torn = read_jsonl(led)
    info["ledger_lines"] = len(rows)
    if torn:
        info["torn_last_lines"] += 1
        warnings.append(f"ledger.jsonl: torn last line {torn} skipped (malformed JSON)")
    if rows:
        con.executemany("INSERT INTO raw_ledger VALUES (?, CAST(? AS JSON))", rows)
    gdir = ledger_dir / "grading_results"
    files = sorted(gdir.glob("*.jsonl")) if gdir.is_dir() else []
    info["grading_files"] = [p.name for p in files]
    for p in files:
        grows, gtorn = read_jsonl(p)
        if gtorn:
            info["torn_last_lines"] += 1
            warnings.append(f"grading_results/{p.name}: torn last line {gtorn} skipped (malformed JSON)")
        if grows:
            con.executemany("INSERT INTO raw_grading VALUES (?, ?, CAST(? AS JSON))",
                            [(p.stem, i, s) for i, s in grows])
    seen: set[str] = set()
    med_files: list[Path] = []
    for root in [ledger_dir / "inputs" / "mediator", *mediator_roots]:
        if root.is_dir():
            med_files += sorted(root.rglob("mediator.jsonl"))
    k = 0
    n_med = 0
    for p in med_files:
        digest = sha256_file(p)
        if digest in seen:
            continue
        seen.add(digest)
        mrows, mtorn = read_jsonl(p)
        if mtorn:
            info["torn_last_lines"] += 1
            warnings.append(f"{p}: torn last line {mtorn} skipped (malformed JSON)")
        con.executemany("INSERT INTO raw_mediator VALUES (?, CAST(? AS JSON))", [(k + i, s) for i, s in mrows])
        k += len(mrows) + 1
        n_med += 1
    info["mediator_files"] = n_med
    return info


def run(ledger_dir: Path, out_dir: Path, mediator_roots: list[Path], sql_path: Path, boot_b: int,
        exclude_wall_used: bool = False) -> int:
    import duckdb

    if not ledger_dir.is_dir():
        raise RouteError(f"--ledger {ledger_dir} is not a directory")
    led = ledger_dir / "ledger.jsonl"
    if not led.is_file():
        raise RouteError(f"no ledger.jsonl in {ledger_dir}")
    if not sql_path.is_file():
        raise RouteError(f"SQL file not found: {sql_path}")
    warnings: list[str] = []
    con = duckdb.connect(":memory:")
    info = load_tables(con, ledger_dir, mediator_roots, warnings)
    if info["ledger_lines"] == 0:
        warnings.append("ledger has no valid record: empty output")
    kinds = dict(con.execute("SELECT rec->>'record', count(*) FROM raw_ledger GROUP BY 1").fetchall())
    if info["ledger_lines"] and "run_end" not in kinds:
        warnings.append("no run_end record: the run was interrupted or is still running (partial ledger)")
    if info["ledger_lines"] and "item_arm" not in kinds:
        warnings.append("no item_arm record: nothing to analyse")
    con.execute("CREATE TABLE cfg (exclude_wall_used BOOLEAN)")
    con.execute("INSERT INTO cfg VALUES (?)", [exclude_wall_used])
    try:
        con.execute(sql_path.read_text())
    except duckdb.Error as e:
        raise RouteError(f"SQL failed: {str(e).splitlines()[0]}") from e
    dups = con.execute("SELECT item, arm, label, n_same FROM ia WHERE n_same > 1 ORDER BY item, arm, label").fetchall()
    if dups:
        shown = "; ".join(f"{i}/{a}/{lab} x{n}" for i, a, lab, n in dups[:10])
        more = f" (and {len(dups) - 10} more)" if len(dups) > 10 else ""
        warnings.append(f"{len(dups)} item-arm(s) with duplicate item_arm records, the latest is used: {shown}{more}")
    n_uns, n_mis = con.execute(
        "SELECT count(*) FILTER (WHERE score IS NULL), count(*) FILTER (WHERE score IS NULL AND NOT has_grade) "
        "FROM ia WHERE cls NOT IN ('DS', 'OE')").fetchone()
    if n_uns:
        warnings.append(f"{n_uns} item-arm(s) unscored ({n_mis} with no grading line, "
                        f"{n_uns - n_mis} with a non-numeric latest line): out of every comparison set")
    wall_excl = con.execute("SELECT count(*) FROM ia_all WHERE wall_used").fetchone()[0] if exclude_wall_used else 0

    rows: list[tuple[str, str, str, str, float]] = [
        (q, c, a, s, float(v)) for q, c, a, s, v in con.execute(
            "SELECT quantity, cls, arm, stat, value FROM res WHERE value IS NOT NULL").fetchall()
    ]
    # bootstrap CIs from the per-item inputs
    boot = con.execute(
        "SELECT quantity, cls, arm, ci_prefix, kind, item, x, y FROM boot_in WHERE x IS NOT NULL "
        "ORDER BY quantity, cls, arm, ci_prefix, kind, item").fetchall()
    groups: dict[tuple[str, str, str, str, str], tuple[list[float], list[float]]] = {}
    for q, c, a, pre, kind, _item, x, y in boot:
        g = groups.setdefault((q, c, a, pre, kind), ([], []))
        g[0].append(float(x))
        g[1].append(float(y) if y is not None else 0.0)
    seeds: dict[str, int] = {}
    for (q, c, a, pre, kind), (xs, ys) in sorted(groups.items()):
        if kind == "median":
            tag = f"eq|{a}|{q.removesuffix('_sens')}"
            seed = seeds.setdefault(tag, seed_for(tag))
            dist = sorted(bootstrap_median(xs, boot_b, seed))
        else:
            seeds.setdefault("eq|auroc", AUROC_SEED)
            dist = sorted(bootstrap_auc(xs, ys, boot_b, AUROC_SEED))
            if len(dist) < boot_b:
                warnings.append(f"{q}/{c}: {boot_b - len(dist)} bootstrap resamples lacked one outcome class "
                                "and were dropped")
        if not dist:
            continue
        lo, hi = percentile(dist, 0.025), percentile(dist, 0.975)
        rows.append((q, c, a, pre + "ci_lo", lo))
        rows.append((q, c, a, pre + "ci_hi", hi))
        if kind == "median":
            rows.append((q, c, a, "measured", 1.0 if (lo > 0 or hi < 0) else 0.0))

    out_dir.mkdir(parents=True, exist_ok=True)
    body = sorted({(q, c, a, s, fmt(v)) for q, c, a, s, v in rows})
    with (out_dir / "results.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(["quantity", "class", "arm", "stat", "value"])
        w.writerows(body)
    cat = con.execute("SELECT quantity, section FROM catalog ORDER BY quantity").fetchall()
    (out_dir / "quantities.txt").write_text("".join(f"{q}\t{s}\n" for q, s in cat), encoding="utf-8")
    start = con.execute(
        "SELECT rec FROM raw_ledger WHERE (rec->>'record') = 'run_start' ORDER BY ord LIMIT 1").fetchone()
    first = json.loads(start[0]) if start else {}
    stages = sorted(r[0] for r in con.execute(
        "SELECT DISTINCT rec->>'stage' FROM raw_ledger WHERE (rec->>'stage') IS NOT NULL").fetchall())
    meta = {
        "route": "r2 (DuckDB SQL)", "ledger": str(led), "ledger_sha256": sha256_file(led),
        "sql_sha256": sha256_file(sql_path), "duckdb_version": duckdb.__version__, "python": sys.version.split()[0],
        "stages": stages, "stub_ledger": first.get("stub"), "harness_sha256": first.get("harness_sha256"),
        "bootstrap": {"B": boot_b, "seeds": dict(sorted(seeds.items())),
                      "method": "percentile, items resampled with replacement, random.Random(seed), "
                                "linear-interpolated quantiles"},
        "exclude_wall_used": exclude_wall_used, "wall_used_excluded": wall_excl,
        "record_counts": dict(sorted(kinds.items())), "inputs": info, "result_rows": len(body),
        "not_computed": NOT_COMPUTED, "warnings": warnings,
    }
    (out_dir / "meta.json").write_text(json.dumps(meta, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    for w_ in warnings:
        print(f"eq_route2: warning: {w_}", file=sys.stderr)
    print(f"eq_route2: {len(body)} rows -> {out_dir / 'results.csv'}", file=sys.stderr)
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--ledger", required=True, help="run directory ($EQ/runs/<stage>) with ledger.jsonl")
    ap.add_argument("--out", required=True, help="output directory")
    ap.add_argument("--mediator-root", action="append", default=[],
                    help="extra directory searched for mediator.jsonl (repeatable)")
    ap.add_argument("--sql", default=None, help="SQL file (default: eq_route2.sql beside this script)")
    ap.add_argument("--boot-b", type=int, default=BOOT_B, help="bootstrap resamples (pre-registered: 10000)")
    ap.add_argument("--exclude-wall-used", action="store_true",
                    help="recompute every output on the item-arms with wall_used false (X6.6 sensitivity)")
    a = ap.parse_args(argv)
    sql = Path(a.sql) if a.sql else Path(__file__).resolve().with_name("eq_route2.sql")
    try:
        return run(Path(a.ledger), Path(a.out), [Path(p) for p in a.mediator_root], sql, a.boot_b,
                   a.exclude_wall_used)
    except RouteError as e:
        print(f"eq_route2: error: {e}", file=sys.stderr)
        return 2
    except Exception as e:  # the contract is "never a traceback"
        print(f"eq_route2: internal error: {type(e).__name__}: {e}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    sys.exit(main())
