# /// script
# requires-python = ">=3.11"
# dependencies = ["numpy==2.5.3"]
# ///
"""eq_analyse.py: analysis route 1 of the agent-equilibrium experiment (COMPARE_eq.md §4-§6, §12 A0-A2).

Reads one run dir (`$EQ/runs/<stage>/`, after `eq_freeze.sh --collect`), written from harness/LEDGER_SCHEMA.md alone:
  ledger.jsonl                                   the harness ledger (required)
  grading_results/{PF,CP,ES,CR}.jsonl            oracle and grader results (optional; RS.jsonl read if present)
  inputs/mediator/<item>/<label>/mediator.jsonl  mediator ledgers (optional; M11-M18)

  uv run --script harness/eq_analyse.py --ledger <run dir> --out <dir> [--primary PF,CP] [--exclude <tsv>]
                                        [--exclude-wall-used]

Writes <dir>/results.csv (long: quantity,class,arm,stat,value; %.9g; sorted by all columns), <dir>/quantities.txt
(quantity <TAB> section), <dir>/item_arms.csv (per item-arm totals, for the route-2 diff) and <dir>/meta.json (input
sha256s, seeds, assumptions, warnings, listed items, quantities not computable from the schema). Deterministic:
resampling uses the pre-registered seeds; nothing depends on the clock. Exit 0 = written (possibly partial: see
meta.json warnings), 2 = input error, 3 = internal error (no traceback unless EQ_ANALYSE_TRACEBACK=1).
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import os
import re
import statistics
import sys
import traceback
from collections import defaultdict
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from fractions import Fraction
from pathlib import Path
from typing import Any

import numpy as np

SCHEMA_VERSION = 1
ARMS = ("S*", "G", "E", "EG")
# contrast label -> (first-named arm, second-named arm); COMPARE_eq §6 "log2 ratios are first-named / second-named"
CONTRASTS: dict[str, tuple[str, str]] = {"E-S*": ("E", "S*"), "E-G": ("E", "G"), "EG-G": ("EG", "G"),
                                         "EG-S*": ("EG", "S*")}
WTL_QUANTITY = {"E-S*": "H1", "E-G": "H2", "EG-G": "H3", "EG-S*": "win/tie/loss"}  # EG-S*: descriptive (§6)
BOOT_CONTRASTS = ("E-S*", "E-G", "EG-G")  # the three with pre-registered bootstrap seeds (§6)
BINARY_CLASSES = ("PF", "CP", "RS")
SCORED_CLASSES = ("PF", "CP", "RS", "CR", "ES")  # DS/OE: pairwise, no results schema
SEED_BASE = 20261004
BOOT_B = 10000
LN_1_1 = math.log(1.1)
Z975 = statistics.NormalDist().inv_cdf(0.975)
NUM_RTOL = 1e-9  # numeric answers (median_ln = exp(median ln)) compared with this relative tolerance
KAPPA_BINS = (0.2, 0.4, 0.6, 0.8, 1.0)
SECTION = {"Excluded": "§4", "Over-cap": "§4", "H1": "§6", "H2": "§6", "H3": "§6", "win/tie/loss": "§6",
           **{f"P{i}": "§6" for i in range(1, 6)}, **{f"M{i}": "§6" for i in range(1, 11)},
           **{f"M{i}": "§6 (§12 A0.5, MEDIATOR.md §6)" for i in range(11, 19)},
           **{q: "route contract (counts)" for q in ("n_unscored", "n_missing", "n_dup_item_arm", "n_wall_used")}}
NOT_COMPUTED = {
    "H1/H2/H3/win/tie/loss, P2 (DS, OE)": "pairwise preferences: no grading-results format in LEDGER_SCHEMA.md",
    "H1/H2/H3/win/tie/loss, P2 (RS)": "no RS grading-results format in LEDGER_SCHEMA.md; route 1 reads "
                                      "grading_results/RS.jsonl only if present, in the PF/CP/ES line format",
    "§4 exclusions (a), (b)": "blind item audit and DISPATCH_LOG.tsv are not in the ledger: pass --exclude",
    "M1": "needs oracle scores of member subsets' reduced answers (member-level grades exist for CR only, and "
          "a reduced finding set's score needs per-finding verdicts)",
    "M2": "needs member-level correctness for binary classes (PF/CP/RS): not in the schema",
    "M3": "needs member-level correctness (oracle@N): not in the schema for binary classes",
    "M4 (scores, flips)": "round-0 E answers are not graded; route 1 reports the conformity rate only",
    "M6": "needs member-level correctness: not in the schema for binary classes",
    "M7": "needs member-level correctness: not in the schema for binary classes",
    "M9": "pairwise grading results and both-order E selection are not in the schema",
    "M12 (unverifiable split by reason)": "fact.method is free text; no reason vocabulary in the schema",
    "M13 (LOO change in oracle score)": "LOO results are not graded",
    "M16": "needs member-level correctness: not in the schema for binary classes",
    "M17": "accuracy-game Shapley needs graded coalitions: not in the schema",
    "H4": "R1/R3/ENS answers are not graded: only their disagreement with R0 (M15) is computable",
    "M5/M15/M8 (route-2 columns: bootstrap CI)": "route 1 computes the rank formula only (§6 table)",
}


class AnalysisError(Exception):
    """An input problem: reported cleanly, exit 2."""


def seed_of(tag: str) -> int:
    """§8.4: 20261004 ^ int(sha256(tag)[:8], 16)."""
    return SEED_BASE ^ int(hashlib.sha256(tag.encode()).hexdigest()[:8], 16)


# ---------------------------------------------------------------------------------------------------------------------
# reading
# ---------------------------------------------------------------------------------------------------------------------


def read_jsonl_numbered(path: Path, warnings: list[str]) -> list[tuple[int, dict[str, Any]]]:
    """JSONL reader -> (1-based line number, record). A torn LAST line (crash mid-append) is skipped with a warning;
    any other bad line (a torn line in the middle) is an input error (exit 2)."""
    try:
        text = path.read_bytes().decode("utf-8")
    except OSError as e:
        raise AnalysisError(f"cannot read {path}: {e}") from e
    except UnicodeDecodeError as e:
        raise AnalysisError(f"{path} is not UTF-8: {e}") from e
    lines = text.split("\n")
    out: list[tuple[int, dict[str, Any]]] = []
    for i, ln in enumerate(lines):
        if not ln.strip():
            continue
        try:
            rec = json.loads(ln)
        except json.JSONDecodeError as e:
            if i == len(lines) - 1:  # no newline after it: a torn final append
                warnings.append(f"{path.name}: torn last line {i + 1} skipped ({e.msg})")
                continue
            raise AnalysisError(f"{path}: line {i + 1} is not JSON ({e.msg})") from e
        if not isinstance(rec, dict):
            raise AnalysisError(f"{path}: line {i + 1} is not a JSON object")
        out.append((i + 1, rec))
    return out


def read_jsonl(path: Path, warnings: list[str]) -> list[dict[str, Any]]:
    return [r for _, r in read_jsonl_numbered(path, warnings)]


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def parse_ts(s: Any) -> datetime | None:
    if not isinstance(s, str):
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


def to_decimal(s: Any) -> Decimal | None:
    try:
        return Decimal(str(s)) if s is not None else None
    except InvalidOperation:
        return None


def is_num(x: Any) -> bool:
    return isinstance(x, int | float) and not isinstance(x, bool)


def _sql_text(x: Any) -> str | None:
    """What route 2's `rec->>'key'` yields for a JSON value: null -> None, a string as is, anything else its JSON."""
    if x is None:
        return None
    return x if isinstance(x, str) else json.dumps(x)


def cast_bool(x: Any) -> bool | None:
    """Route 2's try_cast(rec->>'key' AS BOOLEAN) (DuckDB: true/t/yes/y/1 and false/f/no/n/0, any case)."""
    s = _sql_text(x)
    if s is None:
        return None
    s = s.lower()
    return True if s in ("true", "t", "yes", "y", "1") else False if s in ("false", "f", "no", "n", "0") else None


def cast_double(x: Any) -> float | None:
    """Route 2's try_cast(rec->>'key' AS DOUBLE): numbers, numeric strings, 'inf'/'Infinity'; None otherwise."""
    s = _sql_text(x)
    if s is None or isinstance(x, bool):
        return None
    try:
        return float(s.strip())
    except ValueError:
        return None


def grade_score(r: dict[str, Any], cls: str) -> float | None:
    """The item-arm score of one grading line, as route 2's g_latest. ES: e = inf only on score_inf true or score
    "inf". Otherwise score_num if not null (no fall-through when it does not parse), else score true/false -> 1/0,
    else score cast to a number. None = unscored: an oracle failure (score, score_num null, score_inf false), a
    non-numeric value, NaN or any other non-finite value."""
    if cls == "ES" and (cast_bool(r.get("score_inf")) is True
                        or (_sql_text(r.get("score")) or "").strip().lower() == "inf"):
        return math.inf
    if r.get("score_num") is not None:
        s = cast_double(r["score_num"])
    elif (_sql_text(r.get("score")) or "").lower() in ("true", "false"):
        s = 1.0 if str(_sql_text(r["score"])).lower() == "true" else 0.0
    else:
        s = cast_double(r.get("score"))
    return s if s is not None and math.isfinite(s) else None


_TS_MIN = datetime.min.replace(tzinfo=UTC)


def ts_key(r: dict[str, Any]) -> tuple[int, datetime, int, str]:
    """Grading-line order key, as route 2 (ORDER BY ts_utc AS TIMESTAMPTZ DESC NULLS LAST, ts_utc DESC NULLS LAST,
    line DESC): a parseable ts_utc beats an unparseable one, then time order (an offset-less time read as UTC), then
    the string, then (outside this key) the later line number."""
    s = _sql_text(r.get("ts_utc"))
    t = parse_ts(s)
    if t is not None and t.tzinfo is None:
        t = t.replace(tzinfo=UTC)
    return (t is not None, t or _TS_MIN, s is not None, s or "")


def frac(x: Any) -> Fraction | float | None:
    """A mediator fraction {"num","den","float"} (exact) or a plain number."""
    if isinstance(x, dict) and is_num(x.get("num")) and is_num(x.get("den")) and x["den"] != 0:
        return Fraction(int(x["num"]), int(x["den"]))
    if is_num(x):
        return float(x)
    return None


# ---------------------------------------------------------------------------------------------------------------------
# statistics (pure functions; tests pin each)
# ---------------------------------------------------------------------------------------------------------------------


def sign_test_p(w: int, ls: int) -> float:
    """Exact two-sided sign test at p = 0.5 on w wins and ls losses (ties dropped); 1.0 if none discordant."""
    d = w + ls
    if d == 0:
        return 1.0
    k = min(w, ls)
    tail = Fraction(sum(math.comb(d, i) for i in range(k + 1)), 2**d)
    return float(min(Fraction(1), 2 * tail))


def _binom_cdf(k: int, n: int, p: float) -> float:
    if p <= 0.0:
        return 1.0
    if p >= 1.0:
        return 1.0 if k >= n else 0.0
    return math.fsum(math.comb(n, i) * p**i * (1 - p) ** (n - i) for i in range(k + 1))


def _bisect(f: Callable[[float], float], lo: float, hi: float) -> float:
    """Root of a function decreasing in p on [lo, hi]."""
    for _ in range(200):
        mid = (lo + hi) / 2
        if f(mid) > 0:
            lo = mid
        else:
            hi = mid
        if hi - lo < 1e-15:
            break
    return (lo + hi) / 2


def clopper_pearson(k: int, n: int, alpha: float = 0.05) -> tuple[float, float]:
    """Exact two-sided (1 - alpha) interval for a binomial proportion, by bisection on the binomial tails."""
    if n <= 0:
        raise ValueError("n must be positive")
    lo = 0.0 if k == 0 else _bisect(lambda p: alpha / 2 - (1 - _binom_cdf(k - 1, n, p)), 0.0, 1.0)
    hi = 1.0 if k == n else _bisect(lambda p: _binom_cdf(k, n, p) - alpha / 2, 0.0, 1.0)
    return lo, hi


def wilson(k: int, n: int) -> tuple[float, float]:
    p = k / n
    z2 = Z975 * Z975
    den = 1 + z2 / n
    centre = (p + z2 / (2 * n)) / den
    half = Z975 * math.sqrt(p * (1 - p) / n + z2 / (4 * n * n)) / den
    return (0.0 if k == 0 else max(0.0, centre - half)), (1.0 if k == n else min(1.0, centre + half))


def holm(pvals: list[float]) -> list[float]:
    """Holm step-down adjusted p-values, returned in input order."""
    m = len(pvals)
    order = sorted(range(m), key=lambda i: (pvals[i], i))
    adj = [0.0] * m
    run = 0.0
    for rank, i in enumerate(order):
        run = max(run, min(1.0, (m - rank) * pvals[i]))
        adj[i] = run
    return adj


def outcome(cls: str, a: float, b: float) -> int:
    """§2 win (+1) / tie (0) / loss (-1) of A over B. ES: e = |ln(est/true)|, inf for missing; others: higher wins."""
    if cls == "ES":
        if math.isinf(a) and math.isinf(b):
            return 0
        if math.isinf(a):
            return -1
        if math.isinf(b):
            return 1
        if a < b - LN_1_1:
            return 1
        if a > b + LN_1_1:
            return -1
        return 0
    return (a > b) - (a < b)


def auroc(pos: list[float], neg: list[float]) -> float:
    """P(score_pos > score_neg) + 0.5 P(equal): the Mann-Whitney rank formula."""
    s = 0.0
    for x in pos:
        for y in neg:
            s += 1.0 if x > y else 0.5 if x == y else 0.0
    return s / (len(pos) * len(neg))


def boot_median_ci(r: np.ndarray, seed: int, b: int = BOOT_B) -> tuple[float, float]:
    """Percentile bootstrap (2.5, 97.5) of the median over items: one default_rng(seed), indices drawn as one
    (b, n) integers matrix, numpy's default (linear) percentile."""
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(r), size=(b, len(r)))
    meds = np.median(r[idx], axis=1)
    lo, hi = np.percentile(meds, [2.5, 97.5])
    return float(lo), float(hi)


def kappa_bin(k0: float) -> float:
    """§6 M8 bins (0.2, 0.4, 0.6, 0.8, 1.0): the smallest bin edge >= kappa0 (kappa0 = 0 goes to 0.2)."""
    for edge in KAPPA_BINS:
        if k0 <= edge + 1e-9:
            return edge
    return 1.0


def answers_equal(a: Any, b: Any) -> bool:
    """Reducer outputs equal: numbers within NUM_RTOL, finding sets as multisets, everything else canonical JSON."""
    if is_num(a) and is_num(b):
        return math.isclose(float(a), float(b), rel_tol=NUM_RTOL, abs_tol=1e-12)
    if isinstance(a, list) and isinstance(b, list):
        ca = sorted(json.dumps(x, sort_keys=True) for x in a)
        cb = sorted(json.dumps(x, sort_keys=True) for x in b)
        return ca == cb
    return json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


# ---------------------------------------------------------------------------------------------------------------------
# the model of a run dir
# ---------------------------------------------------------------------------------------------------------------------


@dataclass
class ItemArm:
    item: str
    cls: str
    label: str
    arm: str
    status: str
    seq: int
    tokens: int = 0
    cost: float = 0.0
    n_cost_null: int = 0
    cap_hit: bool = False
    wall_s: float | None = None
    b_usd: Decimal | None = None
    kappa0: float | None = None
    score: float | None = None
    wall_used: bool = False
    n_records: int = 1  # item_arm records with this (item, arm, label); > 1 = a duplicate (n_dup_item_arm)
    has_grade: bool = False  # an item-arm-level grading line exists (n_missing = unscored without one)


ARM_LABEL = re.compile(r"[pq][1-49]")  # analysed arms: p1-p4 / q1-q4 and the declared re-runs p9 / q9 (p5 = screening)


class Run:
    def __init__(self, run_dir: Path, exclude: set[tuple[str, str]], warnings: list[str],
                 exclude_wall_used: bool = False):
        self.dir = run_dir
        self.warnings = warnings
        self.inputs: dict[str, str] = {}
        led = run_dir / "ledger.jsonl"
        self.inputs["ledger.jsonl"] = sha256_file(led)
        self.records = read_jsonl(led, warnings)
        for i, r in enumerate(self.records):
            if r.get("schema_version") != SCHEMA_VERSION:
                raise AnalysisError(f"ledger record {i + 1}: schema_version {r.get('schema_version')!r} != 1")
        by: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for r in self.records:
            by[str(r.get("record"))].append(r)
        unknown = sorted(set(by) - {"run_start", "call", "plan", "reduce", "reconcile", "check", "node", "item_arm",
                                    "run_end", "e_rt"})
        if unknown:
            warnings.append(f"ledger: unknown record types ignored: {unknown}")
        if self.records and not by.get("run_end"):
            warnings.append("no run_end record: the run was interrupted or is still running (partial ledger)")
        self.by = by
        self.calls = by["call"]
        self.call_by_id = {c.get("call_id"): c for c in self.calls}
        self.cls_of: dict[str, str] = {}
        self.arm_of: dict[tuple[str, str], str] = {}
        for r in self.calls + by["item_arm"]:
            if r.get("item") is not None and r.get("cls") is not None:
                self.cls_of[r["item"]] = r["cls"]
        for r in by["item_arm"] + self.calls:
            k = (r.get("item"), r.get("label"))
            if r.get("arm") is not None and k not in self.arm_of:
                self.arm_of[k] = r["arm"]
        self.excluded: list[dict[str, str]] = []
        self.units = self._units(exclude)
        self.interrupted, self.replaced = self._interrupted()
        self.excluded_wall_used: list[dict[str, str]] = []
        if exclude_wall_used:  # sensitivity (X6.6, N24#8): everything below sees only item-arms without WALL use
            for k, u in sorted(self.units.items()):
                if u.wall_used:
                    self.excluded_wall_used.append({"item": u.item, "arm": u.arm, "label": u.label})
                    del self.units[k]
        self._totals()
        self.member_scores: dict[tuple[Any, ...], float] = {}
        self._scores()
        self.mediator = self._mediator()

    # item-arm selection: one unit per (item, arm)
    def _units(self, exclude: set[tuple[str, str]]) -> dict[tuple[str, str], ItemArm]:
        cand: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
        other_labels: dict[str, int] = defaultdict(int)
        for r in self.by["item_arm"]:
            if r.get("item") is None or r.get("arm") is None:
                self.warnings.append(f"item_arm seq {r.get('seq')} lacks item or arm: ignored")
                continue
            if not ARM_LABEL.fullmatch(str(r.get("label") or "")):
                other_labels[str(r.get("label"))] += 1
                continue
            cand[(r["item"], r["arm"])].append(r)
        if other_labels:
            self.warnings.append("item_arm records with a label outside p1-p4/q1-q4/p9/q9 not analysed (other "
                                 "[pq][1-9] labels are cells: p5 = S* screening, p6/p7 = calibration cells): "
                                 f"{dict(sorted(other_labels.items()))}")
        units: dict[tuple[str, str], ItemArm] = {}
        for (item, arm), rs in sorted(cand.items()):
            if (item, arm) in exclude or (item, "*") in exclude:
                self.excluded.append({"item": item, "arm": arm, "reason": "--exclude"})
                continue
            if len(rs) > 1:
                rerun = [r for r in rs if str(r.get("label", "")).endswith("9")]
                pick = max(rerun or rs, key=lambda r: int(r.get("seq") or 0))
                self.warnings.append(f"{item} {arm}: {len(rs)} item_arm records; using label {pick.get('label')} "
                                     "(declared p9/q9 re-run first, else the latest)")
            else:
                pick = rs[0]
            if pick.get("bundle_mismatch") is not None:  # E_rt ran another bundle than q's (A6 note (d)): report only
                self.excluded.append({"item": item, "arm": arm, "reason": "bundle_mismatch"})
                continue
            units[(item, arm)] = ItemArm(item=item, cls=str(pick.get("cls")), label=str(pick.get("label")), arm=arm,
                                         status=str(pick.get("status")), seq=int(pick.get("seq") or 0),
                                         b_usd=to_decimal(pick.get("B_usd")),
                                         kappa0=float(pick["kappa0"]) if is_num(pick.get("kappa0")) else None,
                                         wall_used=cast_bool(pick.get("wall_used")) is True,
                                         n_records=sum(r.get("label") == pick.get("label") for r in rs))
            st, en = parse_ts(pick.get("started_utc")), parse_ts(pick.get("ended_utc"))
            if st is not None and en is not None:
                units[(item, arm)].wall_s = (en - st).total_seconds()
        return units

    def _interrupted(self) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
        """§4 (c): item-arms with call records but no item_arm record; 'replaced' when another label (p9/q9) of the
        same item and arm has one."""
        have = {(r.get("item"), r.get("label")) for r in self.by["item_arm"]}
        seen: dict[tuple[str, str], str] = {}
        for c in self.calls:
            k = (c.get("item"), c.get("label"))
            if k not in have and k not in seen and c.get("arm") is not None:
                seen[k] = c["arm"]
        bad, ok = [], []
        for (item, label), arm in sorted(seen.items()):
            rec = {"item": item, "label": label, "arm": arm, "cls": self.cls_of.get(item, "")}
            (ok if (item, arm) in self.units else bad).append(rec)
        return bad, ok

    def _totals(self) -> None:
        """Tokens, USD and cap hits per item-arm: calls whose item matches and whose charged_to holds the label."""
        idx: dict[tuple[str, str], ItemArm] = {(u.item, u.label): u for u in self.units.values()}
        for c in self.calls:
            for lab in c.get("charged_to") or []:
                u = idx.get((c.get("item"), lab))
                if u is None:
                    continue
                us = c.get("usage") or {}
                u.tokens += sum(int(us.get(f) or 0) for f in ("input_tokens", "cache_creation_input_tokens",
                                                               "cache_read_input_tokens", "output_tokens"))
                if is_num(c.get("total_cost_usd")):
                    u.cost += float(c["total_cost_usd"])
                else:
                    u.n_cost_null += 1
                u.cap_hit = u.cap_hit or bool(c.get("cap_stop"))

    def _scores(self) -> None:
        """Per (item, label) the LATEST grading line wins, latest = max (ts_utc, line number) within the class file
        (as route 2's g_latest). Its score is parsed by grade_score; a latest line without a numeric score leaves
        the unit unscored (an earlier numeric line is NOT kept, nothing is imputed). CR lines with a node or member
        are member-level units (kept apart). A status=partial item-arm scores 0 (ES e = inf) whatever its line
        (COMPARE_eq §2)."""
        gr = self.dir / "grading_results"
        scores: dict[tuple[str, str], float | None] = {}
        for cls in SCORED_CLASSES:
            p = gr / f"{cls}.jsonl"
            if not p.exists():
                continue
            self.inputs[f"grading_results/{cls}.jsonl"] = sha256_file(p)
            latest: dict[tuple[Any, ...], tuple[tuple[tuple[int, str], int], dict[str, Any]]] = {}
            for ln, r in read_jsonl_numbered(p, self.warnings):
                k = (r.get("item"), r.get("label"), r.get("node"), r.get("member"))
                order = (ts_key(r), ln)
                if k not in latest or order > latest[k][0]:
                    latest[k] = (order, r)
            for (item, label, node, member), ((_, ln), r) in sorted(latest.items(), key=lambda kv: json.dumps(
                    kv[0], default=str)):
                s = grade_score(r, cls)
                if node is not None or member is not None:
                    if s is not None:
                        self.member_scores[(item, label, node, member)] = s
                    continue
                if s is None:
                    self.warnings.append(f"{cls}.jsonl {(item, label)}: the latest line ({ln}) has no numeric score "
                                         f"(score {r.get('score')!r}, exit {r.get('exit')!r}): unscored")
                scores[(item, label)] = s
        for u in self.units.values():
            s = scores.get((u.item, u.label))
            u.has_grade = (u.item, u.label) in scores
            if u.status == "partial" and u.cls in SCORED_CLASSES:
                s = math.inf if u.cls == "ES" else 0.0  # §2: a reducer "partial" scores 0 (e = inf)
            u.score = s

    def _mediator(self) -> list[dict[str, Any]]:
        root = self.dir / "inputs" / "mediator"
        out: list[dict[str, Any]] = []
        files = sorted(root.glob("*/*/mediator.jsonl")) if root.is_dir() else []
        if not files:
            self.warnings.append("no inputs/mediator/*/*/mediator.jsonl: M11-M15 and M18 not computed")
        for p in files:
            self.inputs[str(p.relative_to(self.dir))] = sha256_file(p)
            for r in read_jsonl(p, self.warnings):
                item, label = r.get("item"), r.get("label")
                arm = r.get("arm") or self.arm_of.get((item, label))
                cls = self.cls_of.get(item)
                if arm is None or cls is None:
                    self.warnings.append(f"{p.relative_to(self.dir)}: record {r.get('seq')} has no arm/class in the "
                                         "ledger: ignored")
                    continue
                unit = self.units.get((item, arm))
                if unit is None or unit.label != label:
                    continue  # excluded, interrupted or superseded item-arm
                out.append({**r, "_arm": arm, "_cls": cls})
        return out


# ---------------------------------------------------------------------------------------------------------------------
# quantities
# ---------------------------------------------------------------------------------------------------------------------


class Results:
    def __init__(self) -> None:
        self.rows: list[tuple[str, str, str, str, float]] = []

    def add(self, q: str, cls: str, arm: str, stat: str, v: float | int | bool) -> None:
        self.rows.append((q, cls, arm, stat, float(v)))

    def quantities(self) -> list[str]:
        return sorted({r[0] for r in self.rows})


def fmt(v: float) -> str:
    return "%.9g" % v  # noqa: UP031 (the contract's format, verbatim)


def classes_of(units: Iterable[ItemArm]) -> list[str]:
    return sorted({u.cls for u in units})


def q_wtl(run: Run, res: Results, primary: list[str] | None, lists: dict[str, Any]) -> list[str]:
    """H1, H2, H3 and the descriptive EG-S*: win/tie/loss, δ̂, π̂, exact sign test, Clopper-Pearson, Holm."""
    fam: dict[str, list[tuple[str, str, float]]] = {"primary": [], "H3": []}
    scored_classes = sorted({u.cls for u in run.units.values() if u.score is not None})
    holm_classes = [c for c in scored_classes if primary is None or c in primary]
    missing: list[dict[str, str]] = []
    for contrast, (a, b) in CONTRASTS.items():
        q = WTL_QUANTITY[contrast]
        for cls in scored_classes:
            items = sorted({u.item for u in run.units.values() if u.cls == cls})
            w = ls = t = 0
            n_missing = 0
            for it in items:
                ua, ub = run.units.get((it, a)), run.units.get((it, b))
                sa = ua.score if ua else None
                sb = ub.score if ub else None
                if sa is None or sb is None:
                    if (sa is None) != (sb is None):
                        n_missing += 1
                        missing.append({"contrast": contrast, "class": cls, "item": it,
                                        "missing_arm": a if sa is None else b})
                    continue
                o = outcome(cls, sa, sb)
                w, ls, t = w + (o > 0), ls + (o < 0), t + (o == 0)
            n, d = w + ls + t, w + ls
            if n == 0 and n_missing == 0:
                continue
            for stat, v in (("n", n), ("wins", w), ("losses", ls), ("ties", t), ("discordant", d),
                            ("n_missing", n_missing)):
                res.add(q, cls, contrast, stat, v)
            if n == 0:
                continue
            p = sign_test_p(w, ls)
            res.add(q, cls, contrast, "delta", d / n)
            res.add(q, cls, contrast, "p", p)
            if d > 0:
                lo, hi = clopper_pearson(w, d)
                res.add(q, cls, contrast, "pi", w / d)
                res.add(q, cls, contrast, "ci_lo", lo)
                res.add(q, cls, contrast, "ci_hi", hi)
            if cls in holm_classes and q in ("H1", "H2"):
                fam["primary"].append((q, cls, p))
            elif cls in holm_classes and q == "H3":
                fam["H3"].append((q, cls, p))
    for members in fam.values():
        for (q, cls, _), adj in zip(members, holm([m[2] for m in members]), strict=True):
            res.add(q, cls, {v: k for k, v in WTL_QUANTITY.items()}[q], "p_holm", adj)
    lists["missing_in_one_arm"] = missing
    return holm_classes


def q_paired_log2(run: Run, res: Results, lists: dict[str, Any]) -> None:
    """P1 tokens, P4 wall time, P5 USD: median paired log2 ratio, percentile bootstrap; P1/P5 censoring sensitivity
    (§4: repeated without item-arms that had any budget-cap stop)."""
    metrics: dict[str, Callable[[ItemArm], float | None]] = {
        "P1": lambda u: float(u.tokens), "P4": lambda u: u.wall_s, "P5": lambda u: u.cost}
    dropped: list[dict[str, Any]] = []
    for q, get in metrics.items():
        for contrast in BOOT_CONTRASTS:
            a, b = CONTRASTS[contrast]
            seed = seed_of(f"eq|{contrast}|{q}")
            classes = classes_of(run.units.values())
            for cls in [*classes, "all"]:
                rows: list[tuple[str, float, bool]] = []
                n_drop = 0
                for it in sorted({u.item for u in run.units.values() if cls in ("all", u.cls)}):
                    ua, ub = run.units.get((it, a)), run.units.get((it, b))
                    if ua is None or ub is None:
                        continue
                    xa, xb = get(ua), get(ub)
                    if xa is None or xb is None or not (xa > 0 and xb > 0) or math.isinf(xa) or math.isinf(xb):
                        n_drop += 1
                        dropped.append({"quantity": q, "contrast": contrast, "class": cls, "item": it})
                        continue
                    rows.append((it, math.log2(xa / xb), ua.cap_hit or ub.cap_hit))
                variants = [("", rows)]
                if q in ("P1", "P5"):
                    variants.append(("sens_", [r for r in rows if not r[2]]))
                for pre, rr in variants:
                    res.add(q, cls, contrast, f"{pre}n", len(rr))
                    if pre == "":
                        res.add(q, cls, contrast, "n_dropped", n_drop)
                    if not rr:
                        continue
                    r = np.array([x[1] for x in rr], dtype=float)
                    lo, hi = boot_median_ci(r, seed)
                    res.add(q, cls, contrast, f"{pre}estimate", float(np.median(r)))
                    res.add(q, cls, contrast, f"{pre}ci_lo", lo)
                    res.add(q, cls, contrast, f"{pre}ci_hi", hi)
    lists["log2_pairs_dropped_nonpositive"] = [d for d in dropped if d["class"] != "all"]


def q_rates(run: Run, res: Results, lists: dict[str, Any]) -> None:
    """P2 score per arm and class; P3 cap-hit rate; §4 over-cap and excluded."""
    by: dict[tuple[str, str], list[ItemArm]] = defaultdict(list)
    for u in run.units.values():
        by[(u.cls, u.arm)].append(u)
        by[("all", u.arm)].append(u)
    over: list[dict[str, Any]] = []
    for (cls, arm), us in sorted(by.items()):
        k = sum(u.cap_hit for u in us)
        res.add("P3", cls, arm, "k", k)
        res.add("P3", cls, arm, "n", len(us))
        res.add("P3", cls, arm, "estimate", k / len(us))
        lo, hi = wilson(k, len(us))
        res.add("P3", cls, arm, "ci_lo", lo)
        res.add("P3", cls, arm, "ci_hi", hi)
        ko = 0
        for u in us:
            if u.b_usd is not None and Decimal(repr(u.cost)) > u.b_usd * Decimal("1.1"):
                ko += 1
                if cls != "all":
                    over.append({"item": u.item, "arm": arm, "cost_usd": u.cost, "B_usd": str(u.b_usd)})
        res.add("Over-cap", cls, arm, "k", ko)
        res.add("Over-cap", cls, arm, "n", len(us))
        if cls == "all":
            continue
        sc = [u.score for u in us if u.score is not None]
        if not sc:
            continue
        res.add("P2", cls, arm, "n", len(sc))
        if cls in BINARY_CLASSES:
            k2 = int(sum(sc))
            res.add("P2", cls, arm, "k", k2)
            res.add("P2", cls, arm, "estimate", k2 / len(sc))
            lo, hi = wilson(k2, len(sc))
            res.add("P2", cls, arm, "ci_lo", lo)
            res.add("P2", cls, arm, "ci_hi", hi)
        elif cls == "CR":
            res.add("P2", cls, arm, "estimate", math.fsum(sc) / len(sc))
        elif cls == "ES":
            res.add("P2", cls, arm, "estimate", float(np.median(np.array(sc, dtype=float))))
            res.add("P2", cls, arm, "n_inf", sum(math.isinf(s) for s in sc))
    lists["over_cap"] = over
    exc: dict[tuple[str, str], list[int]] = defaultdict(lambda: [0, 0])
    for r in run.interrupted:
        exc[(r["cls"], r["arm"])][0] += 1
    for r in run.replaced:
        exc[(r["cls"], r["arm"])][1] += 1
    for (cls, arm), (nb, nr) in sorted(exc.items()):
        res.add("Excluded", cls, arm, "n_interrupted", nb)
        res.add("Excluded", cls, arm, "n_replaced", nr)
    for e in run.excluded:
        res.add("Excluded", run.cls_of.get(e["item"], ""), e["arm"], "n_excluded_listed", 1)
    lists["interrupted"] = run.interrupted
    lists["interrupted_replaced"] = run.replaced
    lists["excluded_listed"] = run.excluded


def q_contract(run: Run, res: Results) -> None:
    """The route contract's count rows (stat n), per class x arm with at least one analysed unit (zeros written), as
    route 2: n_unscored = units without a score (DS, OE not counted); n_missing = the part of n_unscored with no
    grading line at all (a partial unit scores by rule, never missing); n_dup_item_arm = units whose (item, arm,
    label) has > 1 item_arm records; n_wall_used = units with wall_used (0 under --exclude-wall-used)."""
    by: dict[tuple[str, str], list[ItemArm]] = defaultdict(list)
    for u in run.units.values():
        by[(u.cls, u.arm)].append(u)
    for (cls, arm), us in sorted(by.items()):
        if cls not in ("DS", "OE"):
            res.add("n_unscored", cls, arm, "n", sum(u.score is None for u in us))
            res.add("n_missing", cls, arm, "n", sum(u.score is None and not u.has_grade for u in us))
        res.add("n_dup_item_arm", cls, arm, "n", sum(u.n_records > 1 for u in us))
        res.add("n_wall_used", cls, arm, "n", sum(u.wall_used for u in us))


def merge_counts(res: Results, q: str, counts: dict[tuple[str, str, str], float]) -> None:
    for (cls, arm, stat), v in sorted(counts.items()):
        res.add(q, cls, arm, stat, v)


def q_m10(run: Run, res: Results) -> None:
    """M10 cap overshoot per call = total_cost_usd / cap_usd (calls with a cost and a positive cap)."""
    by: dict[tuple[str, str], list[float]] = defaultdict(list)
    for c in run.calls:
        cap = to_decimal(c.get("cap_usd"))
        unit = run.units.get((c.get("item"), c.get("arm")))
        if not is_num(c.get("total_cost_usd")) or cap is None or cap <= 0 or unit is None:
            continue
        x = float(c["total_cost_usd"]) / float(cap)
        by[(str(c.get("cls")), str(c.get("arm")))].append(x)
        by[("all", str(c.get("arm")))].append(x)
    for (cls, arm), xs in sorted(by.items()):
        res.add("M10", cls, arm, "n", len(xs))
        res.add("M10", cls, arm, "median", float(np.median(np.array(xs))))
        res.add("M10", cls, arm, "max", max(xs))


def q_m4(run: Run, res: Results) -> None:
    """M4 conformity rate = conformity / changed over ledger reconcile records (joined to calls by call_id)."""
    cnt: dict[tuple[str, str, str], float] = defaultdict(float)
    for r in run.by["reconcile"]:
        c = run.call_by_id.get(r.get("call_id"))
        if c is None:
            run.warnings.append(f"reconcile seq {r.get('seq')}: call_id {r.get('call_id')!r} not in the ledger")
            continue
        unit = run.units.get((c.get("item"), c.get("arm")))
        if unit is None or unit.label != c.get("label"):
            continue
        key = (str(c.get("cls")), str(c.get("arm")))
        cnt[(*key, "n")] += 1
        cnt[(*key, "k_changed")] += bool(r.get("changed"))
        cnt[(*key, "k_accepted")] += bool(r.get("accepted"))
        cnt[(*key, "k_conformity")] += bool(r.get("conformity"))
    for cls, arm, _ in [k for k in list(cnt) if k[2] == "n"]:
        ch = cnt[(cls, arm, "k_changed")]
        if ch > 0:
            cnt[(cls, arm, "conformity_rate")] = cnt[(cls, arm, "k_conformity")] / ch
    merge_counts(res, "M4", cnt)


def q_kappa(run: Run, res: Results) -> None:
    """M5 AUROC of 1 - kappa0 for an E error and M8 accuracy by kappa0 bin (binary classes, arm E)."""
    for cls in BINARY_CLASSES:
        us = [u for u in run.units.values() if u.cls == cls and u.arm == "E" and u.kappa0 is not None
              and u.score is not None]
        if not us:
            continue
        err = [1 - u.kappa0 for u in us if u.score == 0]  # type: ignore[operator]
        ok = [1 - u.kappa0 for u in us if u.score != 0]  # type: ignore[operator]
        res.add("M5", cls, "E", "n", len(us))
        res.add("M5", cls, "E", "n_err", len(err))
        if err and ok:
            res.add("M5", cls, "E", "estimate", auroc(err, ok))
        bins: dict[float, list[float]] = defaultdict(list)
        for u in us:
            bins[kappa_bin(u.kappa0)].append(u.score)  # type: ignore[arg-type]
        for edge, sc in sorted(bins.items()):
            res.add("M8", cls, "E", f"k[{edge:g}]", sum(sc))
            res.add("M8", cls, "E", f"n[{edge:g}]", len(sc))
            res.add("M8", cls, "E", f"estimate[{edge:g}]", sum(sc) / len(sc))


def q_mediator(run: Run, res: Results) -> None:
    """M11-M15, M18 over the mediator ledgers (E and EG E-nodes live; S*/G/EG facts offline)."""
    by_rec: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in run.mediator:
        by_rec[str(r.get("record"))].append(r)
    results = {(r.get("item"), r.get("label"), r.get("node")): r for r in by_rec["result"]}
    # M11 influence concentration, M13 LOO stability, M14 decisive facts, M18 CPU time
    m11: dict[tuple[str, str], dict[str, list[Any]]] = defaultdict(lambda: defaultdict(list))
    for a in by_rec["attribution"]:
        if a.get("round") is not None:
            continue  # per-round jackknife line (A6, §4.1): no shapley/hhi/loo_final (eq_calibrate's)
        key = (a["_cls"], a["_arm"])
        g = m11[key]
        g["n"].append(1)
        h = frac(a.get("hhi"))
        if h is None:
            g["hhi_null"].append(1)
        else:
            g["hhi"].append(float(h))
        phis = [frac(v) for v in (a.get("shapley") or {}).values()]
        phis = [p for p in phis if p is not None]
        if phis:
            g["dictator"].append(max(phis) >= Fraction(1, 2))
        df = a.get("decisive_facts") or {}
        g["decisive"].append(any(bool(v) for v in df.values()) if isinstance(df, dict) else False)
        if is_num(a.get("cpu_s")):
            g["cpu"].append(float(a["cpu_s"]))
        full = results.get((a.get("item"), a.get("label"), a.get("node")))
        if full is not None and isinstance(full.get("reducers"), dict) and "R0" in full["reducers"]:
            red = full["reducers"]
            for which, loo_key, ref in (("round0", "loo_round0", red["R0"]),
                                        ("final", "loo_final", red.get("R0_final", red["R0"]))):
                loo = a.get(loo_key)
                if isinstance(loo, dict):
                    g[f"loo_{which}"].append(all(answers_equal(v, ref) for v in loo.values()))
    for (cls, arm), g in sorted(m11.items()):
        n = len(g["n"])
        res.add("M11", cls, arm, "n", n)
        res.add("M11", cls, arm, "n_hhi_null", len(g["hhi_null"]))
        if g["hhi"]:
            res.add("M11", cls, arm, "hhi_mean", math.fsum(g["hhi"]) / len(g["hhi"]))
            res.add("M11", cls, arm, "hhi_median", float(np.median(np.array(g["hhi"]))))
        if g["dictator"]:
            res.add("M11", cls, arm, "k_dictator", sum(g["dictator"]))
            res.add("M11", cls, arm, "share_dictator", sum(g["dictator"]) / len(g["dictator"]))
        for which in ("round0", "final"):
            xs = g[f"loo_{which}"]
            if xs:
                res.add("M13", cls, arm, f"n_{which}", len(xs))
                res.add("M13", cls, arm, f"k_stable_{which}", sum(xs))
                res.add("M13", cls, arm, f"share_stable_{which}", sum(xs) / len(xs))
        res.add("M14", cls, arm, "n", n)
        res.add("M14", cls, arm, "k_decisive", sum(g["decisive"]))
        res.add("M14", cls, arm, "share_decisive", sum(g["decisive"]) / n)
        if g["cpu"]:
            cpu = np.array(g["cpu"])
            res.add("M18", cls, arm, "n", len(cpu))
            res.add("M18", cls, arm, "cpu_s_median", float(np.median(cpu)))
            res.add("M18", cls, arm, "cpu_s_max", float(cpu.max()))
            res.add("M18", cls, arm, "cpu_s_sum", math.fsum(g["cpu"]))
    gates: dict[tuple[str, str, str], float] = defaultdict(float)
    for c in by_rec["change"]:
        gates[(c["_cls"], c["_arm"], f"k_change_{c.get('gate')}")] += 1
    merge_counts(res, "M14", gates)
    # M12 fact status over distinct facts per item-arm
    facts: dict[tuple[str, str, str], dict[str, Any]] = {}
    for f in by_rec["fact"]:
        facts.setdefault((f.get("item"), f.get("label"), f.get("fact_key")), f)
    m12: dict[tuple[str, str], dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for f in facts.values():
        g12 = m12[(f["_cls"], f["_arm"])]
        g12["n_facts"] += 1
        g12[f"k_{f.get('status')}"] += 1
    n_ia: dict[tuple[str, str], int] = defaultdict(int)
    for u in run.units.values():
        n_ia[(u.cls, u.arm)] += 1
    for (cls, arm), g12 in sorted(m12.items()):
        for stat, v in sorted(g12.items()):
            res.add("M12", cls, arm, stat, v)
        for st in ("verified", "refuted", "unverifiable"):
            res.add("M12", cls, arm, f"share_{st}", g12.get(f"k_{st}", 0) / g12["n_facts"])
        res.add("M12", cls, arm, "n_item_arms", n_ia[(cls, arm)])
        res.add("M12", cls, arm, "facts_per_answer", g12["n_facts"] / n_ia[(cls, arm)])
    # M15 reducer disagreement (R1, R2, R3, ENS vs R0) and its AUROC for an E error vs that of 1 - kappa0
    m15: dict[tuple[str, str], list[bool]] = defaultdict(list)
    dis_e: dict[str, list[tuple[bool, ItemArm]]] = defaultdict(list)
    for (item, _label, node), r in sorted(results.items(), key=lambda kv: json.dumps(kv[0])):
        red = r.get("reducers")
        if not isinstance(red, dict) or "R0" not in red or "R1" not in red:
            continue
        dis = any(not answers_equal(red[k], red["R0"]) for k in ("R1", "R2", "R3", "ENS") if k in red)
        m15[(r["_cls"], r["_arm"])].append(dis)
        unit = run.units.get((item, "E"))
        if r["_arm"] == "E" and node is None and unit is not None:
            dis_e[r["_cls"]].append((dis, unit))
    for (cls, arm), xs in sorted(m15.items()):
        res.add("M15", cls, arm, "n", len(xs))
        res.add("M15", cls, arm, "k_disagree", sum(xs))
        res.add("M15", cls, arm, "share_disagree", sum(xs) / len(xs))
    for cls, pairs in sorted(dis_e.items()):
        if cls not in BINARY_CLASSES:
            continue
        sc = [(d, u) for d, u in pairs if u.score is not None and u.kappa0 is not None]
        err = [(d, u) for d, u in sc if u.score == 0]
        ok = [(d, u) for d, u in sc if u.score != 0]
        res.add("M15", cls, "E", "n_auroc", len(sc))
        if err and ok:
            res.add("M15", cls, "E", "auroc_disagree", auroc([float(d) for d, _ in err], [float(d) for d, _ in ok]))
            res.add("M15", cls, "E", "auroc_kappa0", auroc([1 - u.kappa0 for _, u in err],  # type: ignore[operator]
                                                           [1 - u.kappa0 for _, u in ok]))  # type: ignore[operator]
    # M18 USD of the RS equivalence call (ledger reduce records -> calls)
    usd: dict[tuple[str, str, str], float] = defaultdict(float)
    for r in run.by["reduce"]:
        if r.get("reducer") != "equivalence":
            continue
        c = run.call_by_id.get(r.get("call_id"))
        if c is None:
            continue
        unit = run.units.get((c.get("item"), c.get("arm")))
        if unit is None or unit.label != c.get("label"):
            continue
        key = (str(c.get("cls")), str(c.get("arm")))
        usd[(*key, "equivalence_n")] += 1
        usd[(*key, "equivalence_usd")] += float(c["total_cost_usd"]) if is_num(c.get("total_cost_usd")) else 0.0
    merge_counts(res, "M18", usd)


# ---------------------------------------------------------------------------------------------------------------------
# output
# ---------------------------------------------------------------------------------------------------------------------


def write_outputs(out: Path, res: Results, run: Run | None, meta: dict[str, Any]) -> None:
    out.mkdir(parents=True, exist_ok=True)
    rows = sorted((q, c, a, s, fmt(v)) for q, c, a, s, v in res.rows)
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(["quantity", "class", "arm", "stat", "value"])
    w.writerows(rows)
    (out / "results.csv").write_text(buf.getvalue())
    (out / "quantities.txt").write_text("".join(f"{q}\t{SECTION.get(q, '?')}\n" for q in res.quantities()))
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(["item", "class", "label", "arm", "status", "tokens", "cost_usd", "n_cost_null", "cap_hit", "wall_s",
                "B_usd", "kappa0", "score", "wall_used"])
    if run is not None:
        for u in sorted(run.units.values(), key=lambda u: (u.item, u.arm)):
            w.writerow([u.item, u.cls, u.label, u.arm, u.status, u.tokens, fmt(u.cost), u.n_cost_null,
                        int(u.cap_hit), "" if u.wall_s is None else fmt(u.wall_s), u.b_usd or "",
                        "" if u.kappa0 is None else fmt(u.kappa0), "" if u.score is None else fmt(u.score),
                        int(u.wall_used)])
    (out / "item_arms.csv").write_text(buf.getvalue())
    (out / "meta.json").write_text(json.dumps(meta, indent=1, sort_keys=True, default=str) + "\n")


def read_exclude(path: Path) -> set[tuple[str, str]]:
    """TSV: item <TAB> arm (or *) [<TAB> reason]; '#' comments."""
    out: set[tuple[str, str]] = set()
    try:
        lines = path.read_text().splitlines()
    except OSError as e:
        raise AnalysisError(f"cannot read --exclude {path}: {e}") from e
    for i, ln in enumerate(lines):
        if not ln.strip() or ln.lstrip().startswith("#"):
            continue
        parts = ln.split("\t")
        if len(parts) < 2 or parts[1] not in (*ARMS, "*"):
            raise AnalysisError(f"--exclude {path}: line {i + 1}: want 'item<TAB>arm|*[<TAB>reason]'")
        out.add((parts[0], parts[1]))
    return out


def analyse(run_dir: Path, out: Path, primary: list[str] | None, exclude: set[tuple[str, str]],
            exclude_wall_used: bool = False) -> int:
    warnings: list[str] = []
    if run_dir.is_file():
        run_dir = run_dir.parent
    if not (run_dir / "ledger.jsonl").is_file():
        raise AnalysisError(f"no ledger.jsonl in {run_dir}")
    run = Run(run_dir, exclude, warnings, exclude_wall_used)
    res = Results()
    lists: dict[str, Any] = {}
    holm_classes: list[str] = []
    if not run.records:
        warnings.append("empty ledger: results.csv has the header only")
    elif not run.units:
        warnings.append("no item_arm records: only call-level quantities (Excluded) written")
    if run.units:
        holm_classes = q_wtl(run, res, primary, lists)
        q_paired_log2(run, res, lists)
        q_kappa(run, res)
        q_m4(run, res)
        q_m10(run, res)
        q_mediator(run, res)
        q_contract(run, res)
    q_rates(run, res, lists)
    lists["excluded_wall_used"] = run.excluded_wall_used
    if run.units and not any(u.score is not None for u in run.units.values()):
        warnings.append("no grading_results: H1-H3, P2, M5, M8 and the M15 AUROC not computed")
    seeds = {f"eq|{c}|{q}": seed_of(f"eq|{c}|{q}") for q in ("P1", "P4", "P5") for c in BOOT_CONTRASTS}
    meta = {
        "route": 1,
        "script_sha256": sha256_file(Path(__file__)),
        "ledger_sha256": run.inputs["ledger.jsonl"],
        "inputs_sha256": run.inputs,
        "numpy_version": np.__version__,
        "seeds": seeds,
        "bootstrap": {"B": BOOT_B, "method": "numpy default_rng(seed).integers(0, n, (B, n)); median per row; "
                      "np.percentile [2.5, 97.5] (linear); one fresh generator per (quantity, contrast, class)"},
        "holm": {"primary_family": "H1 and H2 over classes " + ",".join(holm_classes),
                 "H3_family": "H3 over the same classes", "primary_classes_arg": primary},
        "records": {k: len(v) for k, v in sorted(run.by.items())},
        "item_arms": len(run.units),
        "exclude_wall_used": exclude_wall_used,
        "warnings": warnings,
        "lists": lists,
        "not_computed": NOT_COMPUTED,
        "assumptions": ASSUMPTIONS,
    }
    try:
        write_outputs(out, res, run, meta)
    except OSError as e:
        raise AnalysisError(f"cannot write {out}: {e}") from e
    for wmsg in warnings:
        print(f"eq_analyse: warning: {wmsg}", file=sys.stderr)
    print(f"eq_analyse: {len(res.rows)} rows, {len(res.quantities())} quantities -> {out / 'results.csv'}")
    return 0


ASSUMPTIONS = [
    "run dir = $EQ/runs/<stage>/ (ledger.jsonl, grading_results/, inputs/mediator/); --ledger may also name the file",
    "unit = one item_arm per (item, arm) among labels p1-p4/q1-q4/p9/q9 (others, e.g. the p5 S* screening cell, "
    "warned and not analysed); with several, the declared re-run (label ending in 9) wins, else the highest seq "
    "(counted: n_dup_item_arm)",
    "item-arm tokens/USD/cap hit = sum over calls with that item whose charged_to holds the label (LEDGER_SCHEMA "
    "Joins); USD sums non-null total_cost_usd (null counted in item_arms.csv n_cost_null)",
    "scores (as route 2): per (item, label) the latest grading_results line wins, latest = max (ts_utc as a time "
    "(parseable beats unparseable or absent), ts_utc as a string, line number); ES e = inf only on score_inf true or "
    "score 'inf'; else score_num (if not null), else score (true/false -> 1/0, numeric strings parsed); a latest "
    "line without a finite numeric score (oracle error: score and score_num null; NaN; other non-finite) leaves the "
    "unit unscored, an earlier numeric line is not kept and nothing is imputed (counted: n_unscored, warned)",
    "CR item-arm = the unit with node and member null; a status=partial item-arm scores 0 (ES inf) whatever its "
    "grading line (COMPARE_eq §2, as route 2)",
    "contract counts (stat n, per class x arm with a unit, as route 2): n_unscored (DS, OE not counted), n_missing "
    "= unscored with no grading line at all, n_dup_item_arm = (item, arm, label) with > 1 item_arm records, "
    "n_wall_used (item_arm.wall_used cast as a boolean, absent = false); an arm missing for an item shows as H "
    "n_missing and in P3 n",
    "--exclude-wall-used: item-arms with wall_used true are removed before every quantity and item_arms.csv (listed "
    "in meta.json lists.excluded_wall_used); §4 (c) interrupted/replaced is decided before that removal",
    "ledger: a torn last line is skipped with a warning, a torn line elsewhere is an input error (exit 2); no "
    "run_end record = warning (partial ledger)",
    "comparison set = items with a score in both arms; an item scored in only one arm is counted (n_missing), listed "
    "in meta.json, never imputed",
    "ES tie = |e_A - e_B| <= ln 1.1 (inclusive); inf vs inf tie; inf loses to any finite e",
    "Holm: primary family = H1 and H2 over --primary classes (default: every scored class, pilot = descriptive); "
    "H3 its own family over the same classes; EG-S* (quantity win/tie/loss) unadjusted",
    "P1/P4/P5: pairs = items with item_arm records in both arms (no score needed); a pair with a non-positive value "
    "is dropped and counted (n_dropped); class 'all' pools classes; the contrast seed is reused for every class",
    "P1/P5 censoring sensitivity (sens_*): pairs where either item-arm had a cap stop removed",
    "P3, Over-cap: over all units; over-cap = summed USD > 1.1 * B_usd",
    "M5/M8: arm E, binary classes, kappa0 from item_arm; E error = score 0; M8 bin = smallest edge >= kappa0",
    "M10: per call, arm = call.arm (the shared planner call counts under its own arm field)",
    "M13: LOO results vs result.reducers R0 (round0) and R0_final (final, else R0); numbers equal within 1e-9 rel.",
    "M15: disagreement = any of R1, R2, R3, ENS != R0 (same equality); AUROC on E (node null) for binary classes",
    "M12: distinct facts per (item, label, fact_key), first record wins; facts_per_answer = facts / units",
    "rows with an undefined value (0 denominators) are omitted, never written as nan",
]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="eq_analyse.py", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ledger", required=True, help="the run dir ($EQ/runs/<stage>/) or its ledger.jsonl")
    ap.add_argument("--out", required=True)
    ap.add_argument("--primary", help="comma-separated primary classes for the Holm families (default: all scored)")
    ap.add_argument("--exclude", help="TSV of §4 (a)/(b) exclusions: item<TAB>arm|*[<TAB>reason]")
    ap.add_argument("--exclude-wall-used", action="store_true",
                    help="sensitivity: recompute all output on item-arms with wall_used false (listed in meta.json)")
    a = ap.parse_args(argv)
    try:
        primary = [c.strip() for c in a.primary.split(",") if c.strip()] if a.primary else None
        exclude = read_exclude(Path(a.exclude)) if a.exclude else set()
        return analyse(Path(a.ledger), Path(a.out), primary, exclude, a.exclude_wall_used)
    except AnalysisError as e:
        print(f"eq_analyse: error: {e}", file=sys.stderr)
        return 2
    except Exception as e:
        if os.environ.get("EQ_ANALYSE_TRACEBACK"):
            traceback.print_exc()
        print(f"eq_analyse: internal error: {type(e).__name__}: {e} (EQ_ANALYSE_TRACEBACK=1 shows the traceback)",
              file=sys.stderr)
        return 3


if __name__ == "__main__":
    sys.exit(main())
