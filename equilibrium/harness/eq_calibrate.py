# /// script
# requires-python = ">=3.11"
# dependencies = ["numpy==2.5.3"]
# ///
"""eq_calibrate.py: Phase-4 calibration of the equilibrium runtime (RUNTIME_EQUILIBRIUM.md §7; COMPARE_eq.md §12 A6).

Pure over a FROZEN stage (after `eq_freeze.sh --collect <p|q>`) and its grades; zero spend; deterministic (every
resampling states its seed, nothing depends on the clock except the `created_utc` stamp, which `--created-utc` pins).

  uv run --script equilibrium/harness/eq_calibrate.py --stage p --amendment A<n> --reason TEXT [--eq-root EQ]
         [--raw-root R] [--out equilibrium/calibration] [--no-route2] [--created-utc T] [--dry-run]
  uv run --script equilibrium/harness/eq_calibrate.py --stage q --primary PF[,CP] --amendment A<n> --reason TEXT [...]
  uv run --script equilibrium/harness/eq_calibrate.py --init [--out DIR] [--created-utc T]   # version 0: all not_run

Steps (§7.3): 1 verify the freeze (COMPARE_eq.sha256 lines, every items/<CLS>/pool.sha256, the stage's FROZEN_AT.txt
and MANIFEST.sha256, the live ledger equal to the frozen copy, A6 in the frozen COMPARE_eq.md) or refuse (exit 2);
2 (p) N* from the p6 nested sweep, rounds* from p7 (RS, ES) and p3 (PF, CP repair), the LOO-view variant from p7, the
certainty signal and its <= 3 isotonic bins; an eligible, complete p bundle gets status `candidate` (q's E_rt runs it,
manual mode only; USER decision 2026-10-06), else not_run; 3 (q) H1/H2 with Holm and the ship rule -> status, H4 -> reducer, H5,
the certainty AUROC CI and bin accuracies re-estimated (signal and cut points kept from p); 4 caps, model ids and the
USD conversion from member calls, with the transcript route (route 2) agreeing within 1 % on every member call used;
5 write params.v<k>.json, params.json, params.json.sha256, one params.history.jsonl line and report.v<k>.json.

Seeds (COMPARE_eq §8.4 derivation 20261004 ^ int(sha256(tag)[:8], 16), checked at import): eq|nstar 4122099631 (N*),
eq|rounds 3549083166 (rounds*), eq|auroc 3066176665 (AUROC CIs), eq|E-S*|P1 943313030 and eq|E-G|P1 391859146 (cost
ratio). B = 10,000 draws, one numpy default_rng(seed) per (rule, class), indices drawn as one (B, n) matrix.

Ledger fields consumed (LEDGER_SCHEMA.md v1 plus the E2/D3 fields the harness adds), read ONLY in read_stage():
  call: call_id item cls label arm role agent member node round cell ("p6"|"p7"|null) branch
        (none|rotation|random|leader|null) parent_session_id session_id model_ids (sorted modelUsage keys)
        total_cost_usd usage{input_tokens,cache_creation_input_tokens,cache_read_input_tokens,output_tokens}
        cap_stop answer schema_valid raw_path [num_turns, else the frozen raw envelope's num_turns]
  item_arm (via eq_analyse.Run): item cls label arm status kappa0 rounds repaired; reconcile: call_id accepted
  proposed_answer; check: item label member round passed; reduce: reducer (equivalence: keys groups;
  finding_clusters: verified_singles) item label node
  mediator (inputs/mediator/<item>/<label>/mediator.jsonl): attribution {round, loo, lambda, pivotal}; result reducers
Grades (runs/<stage>/grading_results/, written after the freeze):
  <CLS>.jsonl item-arm lines (eq_analyse); members/<CLS>.jsonl {item,label,member,round,branch,score} (PF CP RS member
  answers: 1/0; member 0 = a branch's reduced answer, H5; ES only for that);
  members/CR_findings.jsonl {item,label,member,round,finding,bug,verdict,n_seeded}; ES truth from the
  frozen items/ES/oracle/truth.jsonl; optional grader_kappa.json.
Assumption: p6 and p7 calls carry their own labels (not p3's), so (item, label) separates them from p3's records.

Exit: 0 written (or --dry-run printed), 2 refused (unfrozen or inconsistent input, a broken params chain, a
validated class with a missing field), 3 internal error (traceback with EQ_CALIBRATE_TRACEBACK=1).
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import itertools
import json
import math
import os
import re
import subprocess
import sys
import traceback
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from fractions import Fraction
from pathlib import Path
from types import ModuleType
from typing import Any

import numpy as np

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
import eq_analyse as ea  # noqa: E402  (route 1: the run reader and the pre-registered statistics)

SCHEMA = "eqparams.v1"
CLASSES = ("PF", "CP", "CR", "RS", "ES", "DS", "OE")
CAL_CLASSES = ("PF", "CP", "CR", "ES", "RS")  # D2: the calibrated classes (no view ablation)
BINARY = ("PF", "CP", "RS", "ES")  # certainty only for these (ES: "within a factor 2")
FAMILY = {"PF": "checkable", "CP": "checkable", "CR": "finding_set", "RS": "discrete", "ES": "numeric",
          "DS": "long_form", "OE": "long_form"}
M_GRID = (1, 3, 5, 7, 9)
P6_N = 9
R_GRID = (0, 1, 2)
VARIANTS = ("none", "rotation", "random", "leader")
VARIANT_PREF = ("rotation", "random", "leader")  # a tie at the top: rotation if tied, else this order
SIGNALS = ("1-kappa0", "1-lambda0", "1-lambda_final", "m15", "check_fail0")
SIGNALS_BY_FAMILY = {"discrete": ("1-kappa0", "1-lambda0", "1-lambda_final", "m15"),
                     "numeric": ("1-kappa0", "1-lambda0", "1-lambda_final", "m15"),
                     "checkable": ("1-lambda0", "1-lambda_final", "check_fail0")}
CLASS_KEYS = ("status", "member_type", "member_model_id", "agent_file_sha256", "N", "rounds", "view", "loo_view",
              "reducer", "tau", "t", "caps", "usd_per_mtok", "cost_ratio", "effect", "certainty", "pool")
PROV_KEYS = ("created_utc", "note", "stages", "harness_commit", "sha256", "amendments", "pool_sha256",
             "stage_ledgers", "config_sha256", "claude_code_version", "stack_commit", "model_ids", "grader_kappa",
             "route2", "report")
SEED_BASE = 20261004
BOOT_B = 10000
LN2 = math.log(2)
LN_1_1 = math.log(1.1)
ES_CAP = math.log(10)  # calibration score of ES: -min(e, ln 10); an abstention (e = inf) counts as ln 10
ROUTE2_RTOL = 0.01
ALPHA = 0.05
DEFAULT_M_SHIP = 2.0
NO_CAL_NOTE = "no calibration exists: every class not_run (RUNTIME_EQUILIBRIUM.md §7.6)"


def seed_for(tag: str) -> int:
    """COMPARE_eq §8.4: 20261004 ^ int(sha256(tag)[:8], 16) (the harness's seed_for)."""
    return SEED_BASE ^ int(hashlib.sha256(tag.encode()).hexdigest()[:8], 16)


SEED_NSTAR = 4122099631
SEED_ROUNDS = 3549083166
SEED_AUROC = 3066176665
SEED_P1 = {"E-S*": 943313030, "E-G": 391859146}
for _tag, _v in (("eq|nstar", SEED_NSTAR), ("eq|rounds", SEED_ROUNDS), ("eq|auroc", SEED_AUROC),
                 ("eq|E-S*|P1", SEED_P1["E-S*"]), ("eq|E-G|P1", SEED_P1["E-G"])):
    if seed_for(_tag) != _v:  # pragma: no cover - a constant typo must never ship
        raise RuntimeError(f"seed constant of {_tag} is not the harness derivation")


class CalibrationError(Exception):
    """A refusal: an unfrozen or inconsistent input; exit 2."""


# ---------------------------------------------------------------------------------------------------------------------
# small helpers
# ---------------------------------------------------------------------------------------------------------------------


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def sha256_file(p: Path) -> str:
    return sha256_bytes(p.read_bytes())


def dumps(obj: Any) -> str:
    """The one serialisation of every written JSON file (sorted keys, no NaN, trailing newline)."""
    return json.dumps(obj, indent=1, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n"


def canon(x: Any) -> str:
    return json.dumps(x, sort_keys=True, separators=(",", ":"))


def utc_now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def ceil2(v: float) -> int:
    """Round up to 2 significant figures (stack_limits.ceil2, exact on the rational value); below 10: ceil."""
    fv = Fraction(v)
    if fv <= 0:
        return 0
    digits = len(str(math.floor(fv))) if fv >= 1 else 1
    e = 10 ** max(digits - 2, 0)
    return math.ceil(fv / e) * e


def q90(xs: Sequence[float]) -> float:
    """p90 with linear interpolation (type 7: numpy's default, stack_limits._qs)."""
    return float(np.percentile(np.asarray(xs, dtype=float), 90))


def pick(d: dict[str, Any], *names: str) -> Any:
    for n in names:
        if d.get(n) is not None:
            return d[n]
    return None


def num(x: Any) -> float | None:
    """A ledger number or a mediator fraction {"num","den","float"} -> float."""
    f = ea.frac(x)
    return None if f is None else float(f)


# ---------------------------------------------------------------------------------------------------------------------
# step 1: the freeze
# ---------------------------------------------------------------------------------------------------------------------


def _verify_lines(base: Path, lines: Iterable[str], what: str) -> int:
    """`<sha256>  <path>` lines (shasum format, comments skipped) against files under base; returns the count."""
    n = 0
    for ln in lines:
        if not ln.strip() or ln.startswith("#"):
            continue
        m = re.fullmatch(r"([0-9a-f]{64}) [ *](.+)", ln.rstrip("\n"))
        if not m:
            raise CalibrationError(f"{what}: malformed line {ln.strip()[:80]!r}")
        p = base / m.group(2)
        if not p.is_file():
            raise CalibrationError(f"{what}: {m.group(2)} is missing")
        if sha256_file(p) != m.group(1):
            raise CalibrationError(f"{what}: {m.group(2)} does not match its frozen sha256")
        n += 1
    if n == 0:
        raise CalibrationError(f"{what}: no hash lines")
    return n


def parse_kv(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for ln in text.splitlines():
        m = re.match(r"\s*([A-Za-z0-9_.*-]+):\s?(.*)$", ln)
        if m and m.group(1) not in out:
            out[m.group(1)] = m.group(2).strip()
    return out


def verify_frozen(eq_root: Path, stage: str) -> dict[str, Any]:
    """§7.3 step 1: refuse an unfrozen stage. Returns the provenance facts of the freeze."""
    side = eq_root / "COMPARE_eq.sha256"
    if not side.is_file():
        raise CalibrationError(f"{side} missing: the pre-registration is not frozen")
    st = side.read_text(encoding="utf-8")
    n_files = _verify_lines(eq_root, st.splitlines(), "COMPARE_eq.sha256")
    hashed = {m.group(1) for m in re.finditer(r"^[0-9a-f]{64} [ *](?:\./)?(\S+)$", st, re.M)}
    for need in ("COMPARE_eq.md", "eq_harness.py", "flags.json"):
        if need not in hashed:
            raise CalibrationError(f"COMPARE_eq.sha256 does not pin {need}")
    compare = (eq_root / "COMPARE_eq.md").read_text(encoding="utf-8")
    sec12 = compare[compare.find("## 12. Amendments"):] if "## 12. Amendments" in compare else ""
    if not re.search(r"\*\*A6\b", sec12):
        raise CalibrationError("the frozen COMPARE_eq.md has no amendment A6: the calibration rules are not "
                               "pre-registered")
    amendments = sorted(set(re.findall(r"\*\*(A[0-9]+)\b", sec12)), key=lambda a: int(a[1:]))
    amended = [ln[2:].strip() for ln in st.splitlines() if ln.startswith("# amended")]
    pools: dict[str, str] = {}
    for c in CLASSES:
        pf = eq_root / "items" / c / "pool.sha256"
        if not pf.is_file():
            raise CalibrationError(f"items/{c}/pool.sha256 missing")
        _verify_lines(pf.parent, pf.read_text(encoding="utf-8").splitlines(), f"items/{c}/pool.sha256")
        pools[c] = sha256_file(pf)
    inp = eq_root / "runs" / stage / "inputs"
    fa, man = inp / "FROZEN_AT.txt", inp / "MANIFEST.sha256"
    if not fa.is_file() or not man.is_file():
        raise CalibrationError(f"stage {stage} is not frozen: run `eq_freeze.sh --collect {stage}` first")
    frozen = parse_kv(fa.read_text(encoding="utf-8"))
    if frozen.get("stage") != stage:
        raise CalibrationError(f"{fa}: stage {frozen.get('stage')!r} != {stage!r}")
    side_sha = sha256_file(side)
    if frozen.get("sidecar_sha256") != side_sha:
        raise CalibrationError(f"{fa}: the stage was collected under another COMPARE_eq.sha256")
    _verify_lines(inp, man.read_text(encoding="utf-8").splitlines(), f"runs/{stage}/inputs/MANIFEST.sha256")
    led_frozen = inp / "ledger.jsonl"
    if not led_frozen.is_file():
        raise CalibrationError(f"{led_frozen} missing")
    live = eq_root / "runs" / stage / "ledger.jsonl"
    if not live.is_file() or live.read_bytes() != led_frozen.read_bytes():
        raise CalibrationError(f"runs/{stage}/ledger.jsonl differs from its frozen copy (appended after the freeze?)")
    return {"sidecar_sha256": side_sha, "n_frozen_files": n_files, "amendments": amendments,
            "amended_lines": amended, "pool_sha256": pools, "frozen_at_utc": frozen.get("frozen_at_utc"),
            "manifest_sha256": sha256_file(man), "ledger_sha256": sha256_file(led_frozen)}


def load_frozen_harness(eq_root: Path) -> ModuleType:
    """The frozen package's eq_harness.py (the reducers the stage ran), imported by path."""
    p = eq_root / "eq_harness.py"
    if not p.is_file():
        raise CalibrationError(f"{p} missing")
    name = f"eq_harness_frozen_{sha256_file(p)[:16]}"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, p)
    if spec is None or spec.loader is None:
        raise CalibrationError(f"cannot import {p}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod  # dataclasses resolve their module's annotations through sys.modules
    try:
        spec.loader.exec_module(mod)
    except Exception:
        del sys.modules[name]
        raise
    for need in ("make_answer_key", "equivalence_mapping", "median_ln", "positive_number", "kappa_numeric",
                 "numeric_top", "quorum", "parse_findings", "cluster_findings", "derive_seed"):
        if not hasattr(mod, need):
            raise CalibrationError(f"the frozen eq_harness.py lacks {need}")
    return mod


# ---------------------------------------------------------------------------------------------------------------------
# the ONE ledger adapter
# ---------------------------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Call:
    call_id: str
    item: str
    cls: str
    label: str
    arm: str | None
    role: str
    agent: str | None
    member: int | None
    node: str | None
    round: int
    cell: str | None
    branch: str | None
    parent_session_id: str | None
    session_id: str | None
    model_ids: tuple[str, ...]
    cost: float | None
    ctx: int  # context tokens: input + cache_creation + cache_read (the hooks' unit, CONFIG.md soft limits)
    out: int
    cap_stop: bool
    answer: Any
    schema_valid: bool
    num_turns: int | None

    @property
    def is_member(self) -> bool:
        return self.member is not None and re.fullmatch(r"m[0-9]+/[0-9]+", self.role) is not None


@dataclass
class Stage:
    name: str
    eq_root: Path
    run_dir: Path
    run: Any  # eq_analyse.Run
    calls: list[Call]
    call_by_id: dict[str, Call]
    item_arm: dict[tuple[str, str], dict[str, Any]]
    checks: dict[tuple[str, str, int, int], bool]
    reconciles: dict[str, dict[str, Any]]
    equivalence: dict[tuple[str, str], tuple[list[str], Any]]
    verified_singles: dict[tuple[str, str], list[str]]
    attribution: dict[tuple[str, str], dict[int, dict[str, Any]]]
    results: dict[tuple[str, str], dict[str, Any]]
    member_grades: dict[tuple[str, str, int, int, str | None], float]
    finding_grades: dict[tuple[str, str], tuple[str | None, str]]
    n_seeded: dict[str, int]
    truth: dict[str, float]
    transcripts: dict[str, Path]
    config: dict[str, str]
    flags: dict[str, Any]
    inputs: dict[str, str]
    grader_kappa: Any
    warnings: list[str] = field(default_factory=list)


def _latest_lines(p: Path, key: Callable[[dict[str, Any]], Any], warnings: list[str]) -> dict[Any, dict[str, Any]]:
    """Per key the LATEST line (max of eq_analyse.ts_key, line number), as route 1/2 read grading files."""
    latest: dict[Any, tuple[Any, dict[str, Any]]] = {}
    for ln, r in ea.read_jsonl_numbered(p, warnings):
        k = key(r)
        order = (ea.ts_key(r), ln)
        if k not in latest or order > latest[k][0]:
            latest[k] = (order, r)
    return {k: v[1] for k, v in latest.items()}


def _turns_from_raw(rec: dict[str, Any], inp: Path, raw_root: Path | None) -> int | None:
    rp = rec.get("raw_path")
    if not isinstance(rp, str) or raw_root is None:
        return None
    try:
        rel = Path(rp).resolve().relative_to(raw_root.resolve())
    except ValueError:
        return None
    p = inp / "raw" / rel
    if not p.is_file():
        return None
    try:
        env = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None
    t = env.get("num_turns") if isinstance(env, dict) else None
    return int(t) if isinstance(t, int) and not isinstance(t, bool) else None


def read_stage(eq_root: Path, stage: str, raw_root: Path | None, warnings: list[str]) -> Stage:
    """Everything the calibration reads from one frozen stage. The only function that knows ledger field names."""
    run_dir = eq_root / "runs" / stage
    inp = run_dir / "inputs"
    try:
        run = ea.Run(run_dir, set(), warnings)
    except ea.AnalysisError as e:
        raise CalibrationError(f"stage {stage}: {e}") from e
    calls: list[Call] = []
    for c in run.calls:
        us = c.get("usage") or {}
        ctx = sum(int(us.get(f) or 0) for f in ("input_tokens", "cache_creation_input_tokens",
                                                 "cache_read_input_tokens"))
        turns = c.get("num_turns")
        if not isinstance(turns, int) or isinstance(turns, bool):
            turns = _turns_from_raw(c, inp, raw_root)
        mem = c.get("member")
        calls.append(Call(
            call_id=str(c.get("call_id")), item=str(c.get("item")), cls=str(c.get("cls")), label=str(c.get("label")),
            arm=c.get("arm"), role=str(c.get("role") or ""), agent=c.get("agent"),
            member=int(mem) if isinstance(mem, int) and not isinstance(mem, bool) else None, node=c.get("node"),
            round=int(c.get("round") or 0), cell=c.get("cell"), branch=c.get("branch"),
            parent_session_id=c.get("parent_session_id"), session_id=c.get("session_id"),
            model_ids=tuple(sorted(str(m) for m in (c.get("model_ids") or []))),
            cost=float(c["total_cost_usd"]) if ea.is_num(c.get("total_cost_usd")) else None,
            ctx=ctx, out=int(us.get("output_tokens") or 0), cap_stop=bool(c.get("cap_stop")),
            answer=c.get("answer"), schema_valid=bool(c.get("schema_valid")), num_turns=turns))
    by_id = {c.call_id: c for c in calls}
    item_arm = {(str(r.get("item")), str(r.get("label"))): r for r in run.by["item_arm"]}
    checks: dict[tuple[str, str, int, int], bool] = {}
    for r in run.by["check"]:
        if isinstance(r.get("member"), int):
            checks[(str(r.get("item")), str(r.get("label")), int(r["member"]), int(r.get("round") or 0))] = \
                r.get("passed") is True
    reconciles = {str(r.get("call_id")): r for r in run.by["reconcile"] if r.get("call_id") is not None}
    equivalence: dict[tuple[str, str], tuple[list[str], Any]] = {}
    verified: dict[tuple[str, str], list[str]] = {}
    for r in run.by["reduce"]:
        if r.get("node") is not None:
            continue
        k = (str(r.get("item")), str(r.get("label")))
        if r.get("reducer") == "equivalence" and r.get("valid") is not False and isinstance(r.get("keys"), list):
            equivalence[k] = ([str(x) for x in r["keys"]], r.get("groups"))
        elif r.get("reducer") == "finding_clusters":
            verified[k] = [str(x) for x in (r.get("verified_singles") or [])]
    attribution: dict[tuple[str, str], dict[int, dict[str, Any]]] = defaultdict(dict)
    results: dict[tuple[str, str], dict[str, Any]] = {}
    med_root = inp / "mediator"
    for p in sorted(med_root.glob("*/*/mediator.jsonl")) if med_root.is_dir() else []:
        for r in ea.read_jsonl(p, warnings):
            if r.get("node") is not None or r.get("branch") is not None:
                continue  # E-nodes, and p7's forked branches (four per item-arm: never the arm's own LOO or result)
            k = (str(r.get("item")), str(r.get("label")))
            if r.get("record") == "attribution" and isinstance(r.get("round"), int):
                attribution[k][int(r["round"])] = {"loo": r.get("loo"), "lambda": num(r.get("lambda")),
                                                   "pivotal": r.get("pivotal")}
            elif r.get("record") == "result":
                results[k] = r
    gdir = run_dir / "grading_results"
    inputs = dict(run.inputs)
    member_grades: dict[tuple[str, str, int, int, str | None], float] = {}
    for c in ("PF", "CP", "RS", "ES"):
        p = gdir / "members" / f"{c}.jsonl"
        if not p.is_file():
            continue
        inputs[f"grading_results/members/{c}.jsonl"] = sha256_file(p)
        for k, r in _latest_lines(p, lambda r: (r.get("item"), r.get("label"), r.get("member"), r.get("round") or 0,
                                                r.get("branch")), warnings).items():
            s = ea.grade_score(r, c)
            if s is None or not isinstance(k[2], int):
                warnings.append(f"members/{c}.jsonl {k}: no numeric score (ignored)")
                continue
            member_grades[(str(k[0]), str(k[1]), int(k[2]), int(k[3]), k[4])] = s
    finding_grades: dict[tuple[str, str], tuple[str | None, str]] = {}
    n_seeded: dict[str, int] = {}
    p = gdir / "members" / "CR_findings.jsonl"
    if p.is_file():
        inputs["grading_results/members/CR_findings.jsonl"] = sha256_file(p)
        for ln, r in ea.read_jsonl_numbered(p, warnings):
            if not isinstance(r.get("finding"), dict):
                warnings.append(f"CR_findings.jsonl line {ln}: no finding object (ignored)")
                continue
            finding_grades[(str(r.get("item")), canon(r["finding"]))] = (
                None if r.get("bug") is None else str(r["bug"]), str(r.get("verdict") or "unclear"))
            if isinstance(r.get("n_seeded"), int) and r["n_seeded"] > 0:
                n_seeded[str(r.get("item"))] = int(r["n_seeded"])
    truth: dict[str, float] = {}
    tp = eq_root / "items" / "ES" / "oracle" / "truth.jsonl"
    if tp.is_file():
        for r in ea.read_jsonl(tp, warnings):
            if ea.is_num(r.get("true_value")) and float(r["true_value"]) > 0:
                truth[str(r.get("id"))] = float(r["true_value"])
    transcripts: dict[str, Path] = {}
    if raw_root is not None:
        troot = raw_root / stage / "transcripts"
        tman = inp / "TRANSCRIPTS.sha256"
        if troot.is_dir() and tman.is_file():
            _verify_lines(troot, tman.read_text(encoding="utf-8").splitlines(), f"runs/{stage}/inputs/TRANSCRIPTS")
            for tp in sorted(troot.glob("*/*.jsonl")):
                transcripts[tp.stem] = tp
        elif troot.is_dir():
            warnings.append(f"{troot}: no TRANSCRIPTS.sha256 in inputs: transcripts not used")
    cfgp = inp / "CONFIG.txt"
    config = parse_kv(cfgp.read_text(encoding="utf-8")) if cfgp.is_file() else {}
    if cfgp.is_file():
        inputs["inputs/CONFIG.txt"] = sha256_file(cfgp)
    flags = json.loads((eq_root / "flags.json").read_text(encoding="utf-8"))
    gk = gdir / "grader_kappa.json"
    grader_kappa = json.loads(gk.read_text(encoding="utf-8")) if gk.is_file() else None
    return Stage(stage, eq_root, run_dir, run, calls, by_id, item_arm, checks, reconciles, equivalence, verified,
                 dict(attribution), results, member_grades, finding_grades, n_seeded, truth, transcripts, config,
                 flags, inputs, grader_kappa, warnings)


# ---------------------------------------------------------------------------------------------------------------------
# reducer scores (pure; the frozen harness's reducers)
# ---------------------------------------------------------------------------------------------------------------------


def plurality_expected(keys: Sequence[str | None], grade: Callable[[str], float]) -> float:
    """Expected class score of plurality over keys: ties average over the tied keys (the seeded tie-break is uniform
    over the tied set, so this is its expectation and needs no seed); all abstain -> 0."""
    c = Counter(k for k in keys if k is not None)
    if not c:
        return 0.0
    top = max(c.values())
    tied = sorted(k for k, v in c.items() if v == top)
    return math.fsum(grade(k) for k in tied) / len(tied)


def checkable_expected(passed: Sequence[bool], hidden: Sequence[float]) -> float:
    """Expected hidden-test score of verify-then-select: the seeded order picks a uniform passer; none -> 0."""
    vals = [h for p, h in zip(passed, hidden, strict=True) if p]
    return math.fsum(vals) / len(vals) if vals else 0.0


def abs_ln_ratio(a: float, b: float) -> float:
    """|ln(a / b)| for positive finite a, b, exact where the ratio leaves the float range: a / b underflows to 0
    (1e-300 against 1e300: log would raise) or overflows to inf, so those cases use |ln a - ln b| (A6 implementation
    note, as eq_harness.abs_ln_ratio, which only needs the underflow case for its threshold tests)."""
    r = a / b
    return abs(math.log(r)) if 0 < r < math.inf else abs(math.log(a) - math.log(b))


def es_error(eh: ModuleType, values: Sequence[Any], true: float) -> float:
    med = eh.median_ln(list(values))
    return math.inf if med is None else abs_ln_ratio(med, true)


def es_score(e: float) -> float:
    return -min(e, ES_CAP)


def findings_score(eh: ModuleType, findings: Sequence[Any], t: int, verified: set[tuple[int, str]],
                   grade: Callable[[str], tuple[str | None, str]], n_seeded: int, tol: int) -> float:
    """CR score of the cluster reducer on a member subset: clusters of the subset's findings, accepted iff support >= t
    or a single finding the 9-set verifier confirmed; score = matched seeded bugs / n - 0.5 x false findings / n,
    one representative per accepted cluster (Cluster.representative)."""
    bugs: set[str] = set()
    false = 0
    for c in eh.cluster_findings(findings, tol):
        if c.support >= t or (c.support == 1 and any((f.member, f.payload) in verified for f in c.findings)):
            rep = c.representative()
            bug, verdict = grade(rep.payload)
            if verdict == "false":
                false += 1
            elif bug is not None and verdict == "true":
                bugs.add(bug)
    return (len(bugs) - 0.5 * false) / n_seeded


# ---------------------------------------------------------------------------------------------------------------------
# selection rules (§7.1)
# ---------------------------------------------------------------------------------------------------------------------


def one_se_select(scores: np.ndarray, grid: Sequence[int], seed: int, b: int = BOOT_B) -> tuple[int, list[dict]]:
    """The smallest grid value whose mean score is within one bootstrap SE of the best value's, the SE being that of
    the paired difference best - value over a paired item bootstrap (B draws of item indices, one default_rng(seed));
    the best is the first maximum, so ties go to the smaller value."""
    s = np.asarray(scores, dtype=float)
    if s.ndim != 2 or s.shape[0] == 0 or s.shape[1] != len(grid):
        raise ValueError("scores must be (items, grid)")
    n = s.shape[0]
    means = s.mean(axis=0)
    best = int(np.argmax(means))
    idx = np.random.default_rng(seed).integers(0, n, size=(b, n))
    boot = s[idx].mean(axis=1)
    rows = []
    for g, v in enumerate(grid):
        d = boot[:, best] - boot[:, g]
        se = float(d.std(ddof=1))
        gap = float(means[best] - means[g])
        rows.append({"value": int(v), "mean": float(means[g]), "gap_to_best": gap, "se_diff": se,
                     "within_1se": bool(gap <= se + 1e-12)})
    choice = next(r["value"] for r in rows if r["within_1se"])
    return choice, rows


def choose_variant(wl: dict[str, tuple[int, int, int]]) -> str:
    """Pooled LOO variant: the largest (wins - losses) vs none if > 0; ties at the top -> rotation if tied, else the
    VARIANT_PREF order; none > 0 -> none."""
    net = {v: wl[v][0] - wl[v][1] for v in VARIANT_PREF if v in wl}
    if not net or max(net.values()) <= 0:
        return "none"
    top = max(net.values())
    tied = [v for v in VARIANT_PREF if net.get(v) == top]
    return tied[0]


def auroc_ranks(v: np.ndarray, err: np.ndarray) -> float:
    """AUROC (errors positive, higher signal = more risk) by average ranks: equals eq_analyse.auroc."""
    n1 = int(err.sum())
    n0 = len(v) - n1
    if n1 == 0 or n0 == 0:
        return math.nan
    order = np.argsort(v, kind="mergesort")
    _, inv, counts = np.unique(v[order], return_inverse=True, return_counts=True)
    ends = np.cumsum(counts)
    avg = (ends - counts + 1 + ends) / 2.0
    r = np.empty(len(v))
    r[order] = avg[inv]
    return float((r[err].sum() - n1 * (n1 + 1) / 2.0) / (n1 * n0))


def auroc_ci(values: Sequence[float], errors: Sequence[bool], seed: int, b: int = BOOT_B) -> dict[str, Any]:
    """AUROC and its percentile 95 % bootstrap CI over units (one default_rng(seed); draws with one outcome class are
    dropped and counted; fewer than half valid -> no CI)."""
    v = np.asarray(values, dtype=float)
    e = np.asarray(errors, dtype=bool)
    a = auroc_ranks(v, e)
    out: dict[str, Any] = {"auroc": None if math.isnan(a) else a, "ci95": None, "n": len(v), "n_err": int(e.sum()),
                           "n_degenerate_draws": None}
    if math.isnan(a):
        return out
    idx = np.random.default_rng(seed).integers(0, len(v), size=(b, len(v)))
    boots = np.array([auroc_ranks(v[i], e[i]) for i in idx])
    ok = boots[~np.isnan(boots)]
    out["n_degenerate_draws"] = int(b - len(ok))
    if len(ok) >= b / 2:
        lo, hi = np.percentile(ok, [2.5, 97.5])
        out["ci95"] = [float(lo), float(hi)]
    return out


def isotonic_cuts(values: Sequence[float], errors: Sequence[bool], max_bins: int = 3) -> list[float]:
    """Cut points of an isotonic (non-decreasing error rate in the signal) step map with <= max_bins steps: pool equal
    signal values, pool adjacent violators, join neighbours with the same fitted rate, then merge the adjacent pair
    with the smallest rate gap (leftmost on ties) until <= max_bins blocks; a cut is the midpoint between neighbouring
    blocks."""
    pts = sorted(zip((float(x) for x in values), (bool(y) for y in errors), strict=True))
    blocks: list[list[Any]] = []  # [x_lo, x_hi, n, k_err]
    for x, y in pts:
        if blocks and blocks[-1][1] == x:
            blocks[-1][2] += 1
            blocks[-1][3] += y
        else:
            blocks.append([x, x, 1, int(y)])

    def rate(b: list[Any]) -> Fraction:
        return Fraction(b[3], b[2])

    def merge(a: list[Any], b: list[Any]) -> list[Any]:
        return [a[0], b[1], a[2] + b[2], a[3] + b[3]]

    st: list[list[Any]] = []
    for b in blocks:
        st.append(b)
        while len(st) >= 2 and rate(st[-2]) > rate(st[-1]):
            b2 = st.pop()
            st[-1] = merge(st[-1], b2)
    i = 0
    while i < len(st) - 1:  # one level per distinct fitted rate
        if rate(st[i]) == rate(st[i + 1]):
            st[i:i + 2] = [merge(st[i], st[i + 1])]
        else:
            i += 1
    while len(st) > max_bins:
        gaps = [rate(st[i + 1]) - rate(st[i]) for i in range(len(st) - 1)]
        i = gaps.index(min(gaps))
        st[i:i + 2] = [merge(st[i], st[i + 1])]
    return [(st[i][1] + st[i + 1][0]) / 2.0 for i in range(len(st) - 1)]


def bin_of(x: float, cuts: Sequence[float]) -> int:
    """Bin i holds lo_i <= x < hi_i (lo_0 = -inf, hi_last = +inf)."""
    i = 0
    while i < len(cuts) and x >= cuts[i]:
        i += 1
    return i


def bins_table(values: Sequence[float], errors: Sequence[bool], cuts: Sequence[float]) -> list[dict[str, Any]]:
    out = []
    for i in range(len(cuts) + 1):
        sel = [not e for x, e in zip(values, errors, strict=True) if bin_of(x, cuts) == i]
        n, k = len(sel), sum(sel)
        out.append({"lo": None if i == 0 else float(cuts[i - 1]), "hi": None if i == len(cuts) else float(cuts[i]),
                    "n": n, "correct": k, "p_correct": None if n == 0 else k / n,
                    "ci95": None if n == 0 else list(ea.wilson(k, n))})
    return out


def wtl(cls: str, pairs: Iterable[tuple[float, float]]) -> tuple[int, int, int]:
    w = ls = t = 0
    for a, b in pairs:
        o = ea.outcome(cls, a, b)
        w, ls, t = w + (o > 0), ls + (o < 0), t + (o == 0)
    return w, ls, t


# ---------------------------------------------------------------------------------------------------------------------
# the calibration of one stage
# ---------------------------------------------------------------------------------------------------------------------


class Cal:
    """Scores, signals and selections over one Stage. Every missing grade or answer is listed, never imputed."""

    def __init__(self, st: Stage, eh: ModuleType):
        self.st = st
        self.eh = eh
        self.flags = st.flags
        self.w = st.warnings
        self.tau = Fraction(str(self.flags.get("tau", "0.6")))
        self.t = int(self.flags.get("finding_t", 2))
        self.tol = int(self.flags.get("finding_line_tol", 3))
        self.key_rs = eh.make_answer_key((self.flags.get("answer_key") or {}).get("RS"))
        self.skipped: list[dict[str, Any]] = []
        self.by_member: dict[tuple[str, str, int, int, str | None], Call] = {
            (c.item, c.label, int(c.member), c.round, c.branch): c for c in st.calls if c.member is not None}

    # -- units ---------------------------------------------------------------------------------------------------
    def member_calls(self, pred: Callable[[Call], bool]) -> dict[tuple[str, str], dict[int, Call]]:
        out: dict[tuple[str, str], dict[int, Call]] = defaultdict(dict)
        for c in self.st.calls:
            if c.is_member and c.round == 0 and c.node is None and pred(c):
                out[(c.item, c.label)][int(c.member)] = c  # type: ignore[arg-type]
        return dict(out)

    def p6_units(self) -> dict[tuple[str, str], dict[int, Call]]:
        units = self.member_calls(lambda c: c.cell == "p6")
        for k, ms in list(units.items()):
            if sorted(ms) != list(range(1, P6_N + 1)):
                self.skipped.append({"unit": list(k), "why": f"p6 needs members 1..9, has {sorted(ms)}"})
                del units[k]
        return units

    def e_units(self) -> dict[tuple[str, str], dict[int, Call]]:
        return self.member_calls(lambda c: c.cell is None and c.branch is None and c.arm in ("E", "E_rt"))

    def cls_of(self, unit: tuple[str, str], ms: dict[int, Call]) -> str:
        return next(iter(ms.values())).cls

    # -- answer keys and grades ----------------------------------------------------------------------------------
    def rs_mapping(self, unit: tuple[str, str]) -> dict[str, str]:
        e = self.st.equivalence.get(unit)
        if e is None:
            return {}
        m = self.eh.equivalence_mapping(e[0], e[1], [str(f) for f in (self.flags.get("equivalence", {}).get("RS", {})
                                                                         .get("same_fields", []))])
        return m or {}

    def rs_key(self, answer: Any, mapping: dict[str, str]) -> str | None:
        k = self.key_rs(answer)
        return None if k is None else mapping.get(k, k)

    def rs_grades(self, item: str, mapping: dict[str, str]) -> dict[str, float]:
        """Key -> mean grade of the graded RS answers with that key (graders see the answer only)."""
        acc: dict[str, list[float]] = defaultdict(list)
        for (it, label, member, rnd, branch), s in self.st.member_grades.items():
            if it != item:
                continue
            c = self._call_of(it, label, member, rnd, branch)
            if c is None:
                continue
            k = self.rs_key(c.answer, mapping)
            if k is not None:
                acc[k].append(s)
        incons = sorted(k for k, v in acc.items() if len(set(v)) > 1)
        if incons:
            self.w.append(f"RS {item}: {len(incons)} answer key(s) graded inconsistently (mean used)")
        return {k: math.fsum(v) / len(v) for k, v in acc.items()}

    def _call_of(self, item: str, label: str, member: int, rnd: int, branch: str | None) -> Call | None:
        return self.by_member.get((item, label, member, rnd, branch))

    def hidden(self, unit: tuple[str, str], member: int) -> float | None:
        return self.st.member_grades.get((unit[0], unit[1], member, 0, None))

    # -- the class reducer's score on a member subset ------------------------------------------------------------
    def subset_scorer(self, unit: tuple[str, str], ms: dict[int, Call]) -> Callable[[Sequence[int]], float] | None:
        """f(members) -> the class score of the class reducer on those members' round-0 answers; None (listed) when
        a grade the reducer could need is missing."""
        cls = self.cls_of(unit, ms)
        item = unit[0]
        if cls == "RS":
            mp = self.rs_mapping(unit)
            g = self.rs_grades(item, mp)
            keys = {m: self.rs_key(c.answer, mp) for m, c in ms.items()}
            miss = sorted({k for k in keys.values() if k is not None and k not in g})
            if miss:
                self.skipped.append({"unit": list(unit), "why": f"RS: {len(miss)} answer key(s) without a grade"})
                return None
            return lambda sub: plurality_expected([keys[m] for m in sub], lambda k: g[k])
        if cls == "ES":
            true = self.st.truth.get(item)
            if true is None:
                self.skipped.append({"unit": list(unit), "why": "ES: no true value"})
                return None
            return lambda sub: es_score(es_error(self.eh, [ms[m].answer for m in sub], true))
        if cls in ("PF", "CP"):
            passed = {m: self.st.checks.get((unit[0], unit[1], m, 0)) for m in ms}
            hid = {m: self.hidden(unit, m) for m in ms}
            if any(v is None for v in passed.values()) or any(passed[m] and hid[m] is None for m in ms):
                self.skipped.append({"unit": list(unit), "why": f"{cls}: a public check or hidden grade is missing"})
                return None
            return lambda sub: checkable_expected([bool(passed[m]) for m in sub],
                                                  [hid[m] or 0.0 for m in sub])
        if cls == "CR":
            n = self.st.n_seeded.get(item)
            fields = self.flags.get("finding_fields") or {"file": "file", "line": "line", "claim_class": None}
            fs = {m: self.eh.parse_findings(c.answer, m, fields) for m, c in ms.items()}
            allf = [f for v in fs.values() for f in v]
            miss = [f for f in allf if (item, canon(json.loads(f.payload))) not in self.st.finding_grades]
            if n is None or miss:
                self.skipped.append({"unit": list(unit), "why": f"CR: n_seeded {n}, {len(miss)} ungraded finding(s)"})
                return None
            vkeys = set(self.st.verified_singles.get(unit, []))
            verified = {(f.member, f.payload) for c in self.eh.cluster_findings(allf, self.tol)
                        if c.key in vkeys and c.support == 1 for f in c.findings}

            def grade(payload: str) -> tuple[str | None, str]:
                return self.st.finding_grades[(item, canon(json.loads(payload)))]

            return lambda sub: findings_score(self.eh, [f for m in sub for f in fs[m]], self.t, verified, grade, n,
                                              self.tol)
        return None

    # -- step 2a: N* (p6) ----------------------------------------------------------------------------------------
    def nstar(self) -> dict[str, dict[str, Any]]:
        units = self.p6_units()
        rows: dict[str, list[list[float]]] = defaultdict(list)
        cost: dict[str, list[list[float]]] = defaultdict(list)
        items: dict[str, list[str]] = defaultdict(list)
        for unit, ms in sorted(units.items()):
            cls = self.cls_of(unit, ms)
            f = self.subset_scorer(unit, ms)
            if f is None:
                continue
            members = sorted(ms)
            row = []
            for m in M_GRID:
                subs = list(itertools.combinations(members, m))
                row.append(math.fsum(f(s) for s in subs) / len(subs))
            rows[cls].append(row)
            items[cls].append(unit[0])
            usd = [ms[m].cost for m in members]
            tok = [ms[m].ctx + ms[m].out for m in members]
            mean_usd = math.fsum(x for x in usd if x is not None) / max(1, sum(x is not None for x in usd))
            cost[cls].append([m * mean_usd for m in M_GRID] + [m * (sum(tok) / len(tok)) for m in M_GRID])
        out: dict[str, dict[str, Any]] = {}
        for cls in CAL_CLASSES:
            if not rows.get(cls):
                out[cls] = {"N": None, "eligible": False, "why": "no usable p6 unit", "n_items": 0}
                continue
            s = np.array(rows[cls])
            choice, table = one_se_select(s, M_GRID, SEED_NSTAR)
            c = np.array(cost[cls])
            for i, r in enumerate(table):
                r["cost_usd_mean"] = float(c[:, i].mean())
                r["cost_tokens_mean"] = float(c[:, len(M_GRID) + i].mean())
            out[cls] = {"N": choice, "eligible": choice > 1, "n_items": len(rows[cls]), "items": items[cls],
                        "curve": table, "seed": SEED_NSTAR,
                        "why": "N* = 1: no m > 1 qualifies over m = 1 (not eligible)" if choice == 1 else None}
        return out

    # -- p7 branches: answers per round, the stop rule -----------------------------------------------------------
    def branch_rounds(self, item: str, base: tuple[str, str], base_ms: dict[int, Call], branch: str,
                      rmax: int) -> list[list[Any]] | None:
        """Member answers after rounds 0..rmax of one forked branch (the evidence gate applied: a proposal replaces
        the answer only when accepted)."""
        cur = {m: c.answer for m, c in base_ms.items()}
        seq = [[cur[m] for m in sorted(cur)]]
        bcalls = [c for c in self.st.calls if c.item == item and c.cell == "p7" and c.branch == branch
                  and c.member is not None and c.round >= 1]
        for r in range(1, rmax + 1):
            rc = {int(c.member): c for c in bcalls if c.round == r}  # type: ignore[arg-type]
            if not rc:
                return None
            sess = {m: c.session_id for m, c in base_ms.items()}
            for m, c in sorted(rc.items()):
                if c.parent_session_id is not None and c.parent_session_id not in {
                        sess.get(m), *(x.session_id for x in bcalls if x.member == m and x.round == r - 1)}:
                    self.w.append(f"p7 {item} {branch} r{r} m{m}: parent_session_id is not that member's session")
                rec = self.st.reconciles.get(c.call_id)
                if rec is not None and rec.get("accepted") is True:
                    cur[m] = rec.get("proposed_answer")
            seq.append([cur[m] for m in sorted(cur)])
        return seq

    def stop_round(self, cls: str, seq: list[list[Any]], rmax: int, mapping: dict[str, str]) -> int:
        """The round whose answers the pre-registered stop rule keeps with R_max = rmax: stop at round k when the top
        cluster reaches the quorum ceil(tau n), or when round k accepted no change (fixed point)."""
        def stop(ans: list[Any]) -> bool:
            n = len(ans)
            q = self.eh.quorum(n, str(self.flags.get("stop_quorum_rule", "tau")), self.tau)
            if cls == "ES":
                return int(self.eh.numeric_top(ans)) >= q
            c = Counter(k for k in (self.rs_key(a, mapping) for a in ans) if k is not None)
            return bool(c) and max(c.values()) >= q

        r = 0
        while r < rmax and not stop(seq[r]):
            r += 1
            if canon(seq[r]) == canon(seq[r - 1]):
                break
        return r

    def round_score(self, cls: str, item: str, ans: list[Any], mapping: dict[str, str],
                    grades: dict[str, float]) -> float | None:
        if cls == "ES":
            true = self.st.truth.get(item)
            return None if true is None else es_error(self.eh, ans, true)
        keys = [self.rs_key(a, mapping) for a in ans]
        if any(k is not None and k not in grades for k in keys):
            return None
        return plurality_expected(keys, lambda k: grades[k])

    def p7(self) -> dict[str, Any]:
        """LOO variant (pooled RS+ES, vs none at R_max = 2) and rounds* per class on the chosen variant's branch."""
        e = self.e_units()
        per: dict[str, dict[str, dict[str, list[float | None]]]] = defaultdict(dict)  # cls -> item -> v -> s[r]
        items = sorted({c.item for c in self.st.calls if c.cell == "p7"})
        for item in items:
            base = next(((u, ms) for u, ms in e.items() if u[0] == item), None)
            if base is None:
                self.skipped.append({"unit": [item, "p7"], "why": "no p3 round-0 members to branch from"})
                continue
            unit, ms = base
            cls = self.cls_of(unit, ms)
            if cls not in ("RS", "ES"):
                continue
            mp = self.rs_mapping(unit) if cls == "RS" else {}
            grades = self.rs_grades(item, mp) if cls == "RS" else {}
            vals: dict[str, list[float | None]] = {}
            for v in VARIANTS:
                seq = self.branch_rounds(item, unit, ms, v, 2)
                if seq is None:
                    break
                vals[v] = [self.round_score(cls, item, seq[self.stop_round(cls, seq, r, mp)], mp, grades)
                           for r in R_GRID]
            if len(vals) != len(VARIANTS) or any(s is None for v in vals.values() for s in v):
                self.skipped.append({"unit": [item, "p7"], "why": "a branch, round or grade is missing"})
                continue
            per[cls][item] = vals
        wl: dict[str, tuple[int, int, int]] = {}
        for v in VARIANTS[1:]:
            w = ls = t = 0
            for cls, its in per.items():
                a, b, c = wtl(cls, ((x[v][2], x["none"][2]) for x in its.values()))  # type: ignore[misc]
                w, ls, t = w + a, ls + b, t + c
            wl[v] = (w, ls, t)
        variant = choose_variant(wl) if per else "rotation"
        rounds: dict[str, Any] = {}
        for cls, its in per.items():
            # higher is better for the one-SE rule: RS expected score, ES -min(e, ln 10)
            s = np.array([[x if cls == "RS" else es_score(x) for x in its[i][variant]] for i in sorted(its)])
            choice, table = one_se_select(s, R_GRID, SEED_ROUNDS)
            rounds[cls] = {"rounds": choice, "curve": table, "n_items": len(its), "branch": variant,
                           "seed": SEED_ROUNDS}
        return {"variant": variant, "wins_losses_ties": {v: list(x) for v, x in wl.items()},
                "n_items": {c: len(v) for c, v in per.items()}, "rounds": rounds,
                "default_used": not per}

    def repair_rounds(self) -> dict[str, Any]:
        """Checkable repair in {0, 1} from p3: score(0) = 0 on items that needed the repair round, else the E score."""
        out: dict[str, Any] = {}
        for cls in ("PF", "CP"):
            rows = []
            for (item, arm), u in sorted(self.st.run.units.items()):
                if u.cls != cls or arm != "E" or u.score is None:
                    continue
                rec = self.st.item_arm.get((item, u.label), {})
                rows.append([0.0 if rec.get("repaired") else u.score, u.score])
            if not rows:
                out[cls] = {"rounds": None, "n_items": 0}
                continue
            choice, table = one_se_select(np.array(rows), (0, 1), SEED_ROUNDS)
            out[cls] = {"rounds": choice, "curve": table, "n_items": len(rows), "seed": SEED_ROUNDS}
        return out

    # -- certainty signals --------------------------------------------------------------------------------------
    def e_signals(self) -> dict[str, list[dict[str, Any]]]:
        """Per binary class: units of the E arm (p3 / q3 / E_rt) with their signals and the E error."""
        out: dict[str, list[dict[str, Any]]] = defaultdict(list)
        e = self.e_units()
        for (item, arm), u in sorted(self.st.run.units.items()):
            if arm not in ("E", "E_rt") or u.cls not in BINARY or u.score is None:
                continue
            err = (u.score > LN2) if u.cls == "ES" else (u.score == 0)
            sig: dict[str, float] = {}
            if u.kappa0 is not None and FAMILY[u.cls] in ("discrete", "numeric"):
                sig["1-kappa0"] = 1.0 - u.kappa0
            att = self.st.attribution.get((item, u.label), {})
            if att:
                r0, rf = att.get(min(att)), att.get(max(att))
                if r0 and r0.get("lambda") is not None:
                    sig["1-lambda0"] = 1.0 - float(r0["lambda"])
                if rf and rf.get("lambda") is not None:
                    sig["1-lambda_final"] = 1.0 - float(rf["lambda"])
            res = self.st.results.get((item, u.label))
            red = (res or {}).get("reducers")
            if isinstance(red, dict) and "R0" in red and "R1" in red and FAMILY[u.cls] in ("discrete", "numeric"):
                sig["m15"] = float(any(not ea.answers_equal(red[k], red["R0"]) for k in ("R1", "R2", "R3", "ENS")
                                       if k in red))
            ms = e.get((item, u.label))
            if FAMILY[u.cls] == "checkable" and ms:
                sig["check_fail0"] = 1.0 - sum(bool(self.st.checks.get((item, u.label, m, 0))) for m in ms) / len(ms)
            out[u.cls].append({"item": item, "source": u.label, "error": bool(err), "signals": sig})
        return out

    def p6_signals(self) -> dict[str, list[dict[str, Any]]]:
        """p6 round-0 units (9 members): signals computed here (no reconcile, so no lambda_final or m15); the error is
        the 9-member reducer's expected score < 0.5 (ES: e > ln 2)."""
        out: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for unit, ms in sorted(self.p6_units().items()):
            cls = self.cls_of(unit, ms)
            if cls not in BINARY:
                continue
            f = self.subset_scorer(unit, ms)
            if f is None:
                continue
            members = sorted(ms)
            full = f(members)
            err = (-full > LN2) if cls == "ES" else (full < 0.5)
            sig: dict[str, float] = {}
            fam = FAMILY[cls]
            if fam == "discrete":
                mp = self.rs_mapping(unit)
                keys = [self.rs_key(ms[m].answer, mp) for m in members]
                c = Counter(k for k in keys if k is not None)
                sig["1-kappa0"] = 1.0 - (max(c.values()) / len(keys) if c else 0.0)
                sig["1-lambda0"] = 1.0 - self.loo_lambda_discrete(unit, keys)
            elif fam == "numeric":
                vals = [ms[m].answer for m in members]
                sig["1-kappa0"] = 1.0 - float(self.eh.kappa_numeric(vals, len(vals)))
                sig["1-lambda0"] = 1.0 - self.loo_lambda_numeric(vals)
            else:
                passed = [bool(self.st.checks.get((unit[0], unit[1], m, 0))) for m in members]
                sig["check_fail0"] = 1.0 - sum(passed) / len(passed)
                # λ (checkable, §4.1): share of i such that S\i still holds a passer
                lam = sum(any(p for j, p in enumerate(passed) if j != i) for i in range(len(passed))) / len(passed)
                sig["1-lambda0"] = 1.0 - lam
            out[cls].append({"item": unit[0], "source": unit[1], "error": bool(err), "signals": sig})
        return out

    def loo_lambda_discrete(self, unit: tuple[str, str], keys: list[str | None]) -> float:
        """λ0 = share of i with R(S\\i) = R(S); ties broken by the answer key's sha256 under the unit's round-0 tie
        seed (RUNTIME_EQUILIBRIUM §4.1), so removing a member never reorders the tied answers."""
        seed = self.eh.derive_seed(seed_for("eq|ties"), f"{unit[0]}|{unit[1]}|r0")

        def red(ks: list[str | None]) -> str | None:
            c = Counter(k for k in ks if k is not None)
            if not c:
                return None
            top = max(c.values())
            return min((k for k, v in c.items() if v == top), key=lambda k: sha256_bytes(f"{seed}|{k}".encode()))

        full = red(keys)
        return sum(red(keys[:i] + keys[i + 1:]) == full for i in range(len(keys))) / len(keys)

    def loo_lambda_numeric(self, vals: list[Any]) -> float:
        full = self.eh.median_ln(vals)
        same = 0
        for i in range(len(vals)):
            r = self.eh.median_ln(vals[:i] + vals[i + 1:])
            if full is None or r is None:
                same += full is None and r is None
            else:
                same += abs_ln_ratio(r, full) <= LN_1_1 + 1e-12
        return same / len(vals)

    def choose_certainty(self) -> dict[str, Any]:
        """Per binary class: the candidate with the highest AUROC whose 95 % bootstrap lower bound > 0.5 (ties: the
        SIGNALS order); its isotonic <= 3-bin map and bin accuracies on p. None qualifies -> null with the reason."""
        units: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for d in (self.e_signals(), self.p6_signals()):
            for c, v in d.items():
                units[c] += v
        out: dict[str, Any] = {}
        for cls in BINARY:
            us = units.get(cls, [])
            cand = []
            for s in SIGNALS_BY_FAMILY[FAMILY[cls]]:
                pts = [(u["signals"][s], u["error"]) for u in us if s in u["signals"]]
                if not pts:
                    continue
                r = auroc_ci([p[0] for p in pts], [p[1] for p in pts], SEED_AUROC)
                r["signal"] = s
                r["qualifies"] = bool(r["ci95"] is not None and r["ci95"][0] > 0.5)
                cand.append((r, pts))
            ok = [(r, pts) for r, pts in cand if r["qualifies"]]
            table = [r for r, _ in cand]
            if not ok:
                out[cls] = {"certainty": None, "candidates": table,
                            "reason": "no candidate signal has a 95 % AUROC lower bound > 0.5 on p"}
                continue
            r, pts = max(ok, key=lambda x: (x[0]["auroc"], -SIGNALS.index(x[0]["signal"])))
            cuts = isotonic_cuts([p[0] for p in pts], [p[1] for p in pts])
            out[cls] = {"certainty": {"signal": r["signal"], "auroc": r["auroc"], "ci95": r["ci95"], "n": r["n"],
                                      "estimated_on": "p", "bins": bins_table([p[0] for p in pts],
                                                                              [p[1] for p in pts], cuts)},
                        "candidates": table, "cuts": cuts}
        return out

    def reestimate(self, us: list[dict[str, Any]], prev: dict[str, Any]) -> dict[str, Any]:
        """q: the signal and the cut points chosen on p are kept; the AUROC CI and the bin accuracies are estimated
        on the q E units (the signal is never re-chosen)."""
        s = prev["signal"]
        pts = [(u["signals"][s], u["error"]) for u in us if s in u["signals"]]
        if not pts:
            return {"certainty": None, "reason": f"signal {s} unavailable on q"}
        cuts = [b["hi"] for b in prev["bins"][:-1]]
        r = auroc_ci([p[0] for p in pts], [p[1] for p in pts], SEED_AUROC)
        if r["auroc"] is None or r["ci95"] is None:
            return {"certainty": None, "reason": f"AUROC of {s} undefined on q (one outcome class)"}
        return {"certainty": {"signal": s, "auroc": r["auroc"], "ci95": r["ci95"], "n": r["n"], "estimated_on": "q",
                              "bins": bins_table([p[0] for p in pts], [p[1] for p in pts], cuts)}}

    # -- caps, models, USD, route 2 -----------------------------------------------------------------------------
    def resolved_model(self, c: Call) -> str | None:
        tp = self.st.transcripts.get(c.session_id or "")
        if tp is not None:
            _, model = transcript_usage(tp, self.st.transcripts.get(c.parent_session_id or ""))
            if model is not None:
                if c.model_ids and model not in c.model_ids:
                    self.w.append(f"{c.call_id}: transcript model {model} not in model_ids {list(c.model_ids)}")
                return model
        return c.model_ids[0] if len(c.model_ids) == 1 else None

    def cap_calls(self, cls: str) -> list[Call]:
        """Round-0 member calls of the class: p6 + p3 members (stage p) or the E arm's (stage q)."""
        return [c for c in self.st.calls if c.cls == cls and c.is_member and c.round == 0 and c.node is None
                and c.branch is None and (c.cell == "p6" or c.arm in ("E", "E_rt"))]

    def route2(self, calls: Sequence[Call]) -> dict[str, Any]:
        bad, missing, worst = [], [], 0.0
        for c in calls:
            tp = self.st.transcripts.get(c.session_id or "")
            if tp is None:
                missing.append(c.call_id)
                continue
            tok, _ = transcript_usage(tp, self.st.transcripts.get(c.parent_session_id or ""))
            rel = abs(tok - c.ctx) / max(1, c.ctx)
            worst = max(worst, rel)
            if rel > ROUTE2_RTOL:
                bad.append({"call_id": c.call_id, "ledger": c.ctx, "transcript": tok})
        return {"n_calls": len(calls), "missing": missing, "disagree": bad, "max_rel_diff": worst}

    def caps(self, cls: str, n: int | None, rounds: int | None) -> dict[str, Any]:
        cs = self.cap_calls(cls)
        if not cs:
            return {"caps": None, "why": "no member calls"}
        toks = [c.ctx for c in cs]
        turns = [c.num_turns for c in cs if c.num_turns is not None]
        member_tokens = ceil2(q90(toks) * 1.25)
        member_turns = math.ceil(q90(turns) * 1.25) if turns else None
        helpers = {"CR": int(self.flags["families"]["finding_set"].get("max_verifier_calls", 5)), "RS": 1}
        extra, extra_note = 0, None
        if cls in helpers:
            hv = [c.ctx for c in self.st.calls if c.cls == cls and c.role == "ver" and (c.cell == "p6" or c.arm in
                                                                                      ("E", "E_rt"))]
            per = ceil2(q90(hv) * 1.25) if hv else member_tokens
            extra = helpers[cls] * per
            extra_note = f"{helpers[cls]} x {per} ({'ver calls' if hv else 'no ver call: member cap used'})"
        run_tokens = None if n is None or rounds is None else n * member_tokens * (1 + rounds) + extra
        caps = None if member_turns is None or run_tokens is None else {
            "member_tokens": member_tokens, "member_turns": member_turns, "run_tokens": run_tokens}
        return {"caps": caps, "n_calls": len(cs), "q90_tokens": q90(toks), "q90_turns": q90(turns) if turns else None,
                "helper_tokens": extra_note, "member_tokens": member_tokens, "member_turns": member_turns}

    def usd_per_mtok(self) -> dict[str, float]:
        acc: dict[str, list[float]] = defaultdict(lambda: [0.0, 0.0])
        for cls in CAL_CLASSES:
            for c in self.cap_calls(cls):
                m = self.resolved_model(c)
                if m is None or c.cost is None:
                    continue
                acc[m][0] += c.cost
                acc[m][1] += c.ctx
        return {m: v[0] / v[1] * 1e6 for m, v in sorted(acc.items()) if v[1] > 0}

    def model_of(self, cls: str) -> tuple[str | None, list[str]]:
        ms = sorted({m for m in (self.resolved_model(c) for c in self.cap_calls(cls)) if m is not None})
        return (ms[0] if len(ms) == 1 else None), ms

    # -- q tests --------------------------------------------------------------------------------------------------
    def e_unit(self, item: str) -> Any:
        return self.st.run.units.get((item, "E")) or self.st.run.units.get((item, "E_rt"))

    def contrast(self, cls: str, other: str) -> dict[str, Any]:
        items = sorted({u.item for u in self.st.run.units.values() if u.cls == cls})
        pairs, logs = [], []
        for it in items:
            ue, uo = self.e_unit(it), self.st.run.units.get((it, other))
            if ue is None or uo is None or ue.score is None or uo.score is None:
                continue
            pairs.append((ue.score, uo.score))
            if ue.tokens > 0 and uo.tokens > 0:
                logs.append(math.log2(ue.tokens / uo.tokens))
        w, ls, t = wtl(cls, pairs)
        d = w + ls
        res: dict[str, Any] = {"wins": w, "losses": ls, "ties": t, "n": len(pairs), "p": ea.sign_test_p(w, ls),
                               "pi_hat": None if d == 0 else w / d,
                               "ci95": None if d == 0 else list(ea.clopper_pearson(w, d))}
        cname = "E-S*" if other == "S*" else "E-G"
        if logs:
            arr = np.array(logs)
            lo, hi = ea.boot_median_ci(arr, SEED_P1[cname])
            res["cost_ratio"] = {"median": float(2 ** float(np.median(arr))), "ci95": [float(2 ** lo), float(2 ** hi)]}
        else:
            res["cost_ratio"] = None
        return res

    def h4(self, cls: str) -> dict[str, Any]:
        """{R1, R3, ENS} vs R0 on E's stored round-0 reducer outputs, Holm over 3; the reducer is a confirmed
        alternative (smallest adjusted p, then R1, R3, ENS) else R0."""
        if cls not in ("RS", "ES", "CR"):
            return {"reducer": "R0", "note": "H4 covers RS, ES, CR only"}
        rows: dict[str, list[tuple[float, float]]] = defaultdict(list)
        for (item, arm), u in sorted(self.st.run.units.items()):
            if u.cls != cls or arm not in ("E", "E_rt"):
                continue
            red = (self.st.results.get((item, u.label)) or {}).get("reducers")
            if not isinstance(red, dict) or "R0" not in red:
                continue
            g0 = self.grade_answer(cls, item, u.label, red["R0"])
            for alt in ("R1", "R3", "ENS"):
                ga = self.grade_answer(cls, item, u.label, red.get(alt)) if alt in red else None
                if g0 is not None and ga is not None:
                    rows[alt].append((ga, g0))
        if not rows:
            return {"reducer": "R0", "note": "H4 not computable: no graded reducer outputs"}
        tests = {}
        for alt in ("R1", "R3", "ENS"):
            w, ls, t = wtl(cls, rows.get(alt, []))
            tests[alt] = {"wins": w, "losses": ls, "ties": t, "p": ea.sign_test_p(w, ls)}
        adj = ea.holm([tests[a]["p"] for a in ("R1", "R3", "ENS")])
        for a, p in zip(("R1", "R3", "ENS"), adj, strict=True):
            tests[a]["p_holm"] = p
        conf = [a for a in ("R1", "R3", "ENS") if tests[a]["p_holm"] <= ALPHA and tests[a]["wins"] > tests[a]["losses"]]
        best = min(conf, key=lambda a: (tests[a]["p_holm"], ("R1", "R3", "ENS").index(a))) if conf else "R0"
        return {"reducer": best, "tests": tests}

    def grade_answer(self, cls: str, item: str, label: str, ans: Any) -> float | None:
        if ans is None:
            return math.inf if cls == "ES" else 0.0
        if cls == "ES":
            true = self.st.truth.get(item)
            v = self.eh.positive_number(ans)
            return None if true is None else (math.inf if v is None else abs_ln_ratio(v, true))
        if cls == "RS":  # the mediator stores the representative raw answer
            mp = self.rs_mapping((item, label))
            k = self.rs_key(ans, mp)
            return 0.0 if k is None else self.rs_grades(item, mp).get(k)
        if cls == "CR":
            n = self.st.n_seeded.get(item)
            if n is None or not isinstance(ans, list):
                return None
            bugs, false = set(), 0
            for f in ans:
                g = self.st.finding_grades.get((item, canon(f)))
                if g is None:
                    return None
                false += g[1] == "false"
                if g[0] is not None and g[1] == "true":
                    bugs.add(g[0])
            return (len(bugs) - 0.5 * false) / n
        return None

    def h5(self, cls: str, variant: str) -> dict[str, Any] | None:
        """H5: the chosen variant (the E run's graded answer) vs its forked `none` branch, paired sign test on items
        where reconcile ran (item_arm rounds > 0 or repaired); the none branch's reduced answer is graded as a
        branch-level line in members/<CLS>.jsonl: member 0, branch "none"."""
        if variant == "none":
            return None
        pairs = []
        for (item, arm), u in sorted(self.st.run.units.items()):
            if u.cls != cls or arm not in ("E", "E_rt") or u.score is None:
                continue
            rec = self.st.item_arm.get((item, u.label), {})
            if not (rec.get("rounds") or rec.get("repaired")):
                continue
            g = next((s for (it, _lab, mem, _r, br), s in self.st.member_grades.items()
                      if it == item and br == "none" and mem == 0), None)
            if g is not None:
                pairs.append((u.score, g))
        if not pairs:
            return {"note": "no graded none-branch result"}
        w, ls, t = wtl(cls, pairs)
        return {"variant": variant, "wins": w, "losses": ls, "ties": t, "p": ea.sign_test_p(w, ls)}


def transcript_usage(path: Path, parent: Path | None = None) -> tuple[int, str | None]:
    """Route 2 of the token count: Σ input + cache_creation + cache_read over the transcript's distinct assistant
    message ids (last occurrence; a fork's messages copied from its parent session excluded), and the majority
    `message.model` of those messages."""
    def msgs(p: Path) -> dict[str, dict[str, Any]]:
        out: dict[str, dict[str, Any]] = {}
        for ln in p.read_text(encoding="utf-8").splitlines():
            try:
                r = json.loads(ln)
            except json.JSONDecodeError:
                continue
            if not isinstance(r, dict) or r.get("type") != "assistant" or r.get("isSidechain"):
                continue
            m = r.get("message") or {}
            if isinstance(m, dict) and m.get("id"):
                out[str(m["id"])] = m
        return out

    own = msgs(path)
    if parent is not None and parent.is_file():
        for k in msgs(parent):
            own.pop(k, None)
    tok = 0
    models: Counter[str] = Counter()
    for m in own.values():
        us = m.get("usage") or {}
        tok += sum(int(us.get(f) or 0) for f in ("input_tokens", "cache_creation_input_tokens",
                                                  "cache_read_input_tokens"))
        if m.get("model") and m.get("model") != "<synthetic>":
            models[str(m["model"])] += 1
    model = min(models, key=lambda k: (-models[k], k)) if models else None
    return tok, model


# ---------------------------------------------------------------------------------------------------------------------
# params assembly
# ---------------------------------------------------------------------------------------------------------------------


def empty_class(status: str = "not_run") -> dict[str, Any]:
    return {k: None for k in CLASS_KEYS} | {"status": status}


def empty_provenance(created_utc: str, note: str) -> dict[str, Any]:
    return {k: None for k in PROV_KEYS} | {"created_utc": created_utc, "note": note, "stages": []}


def not_run_params(created_utc: str) -> dict[str, Any]:
    """Version 0: no calibration; every class not_run, every other class key null (§7.6)."""
    return {"schema": SCHEMA, "version": 0, "created_utc": created_utc,
            "provenance": empty_provenance(created_utc, NO_CAL_NOTE),
            "classes": {c: empty_class() for c in CLASSES}}


def pool_entry(eq_root: Path, cls: str, pool_sha: str) -> dict[str, Any]:
    readme = eq_root / "items" / cls / "README.md"
    desc = f"{cls} item pool"
    if readme.is_file():
        first = next((ln.strip("# ").strip() for ln in readme.read_text(encoding="utf-8").splitlines() if ln.strip()),
                     "")
        if first:
            desc = first
    return {"name": f"{cls} pool", "sha256": pool_sha, "description": desc}


def harness_commit() -> str | None:
    try:
        r = subprocess.run(["git", "-C", str(HERE), "rev-parse", "HEAD"], capture_output=True, text=True, timeout=10,
                           check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    return (r.stdout.strip() or None) if r.returncode == 0 else None


def file_shas(eq_root: Path, frozen: dict[str, Any]) -> dict[str, str | None]:
    def s(p: Path) -> str | None:
        return sha256_file(p) if p.is_file() else None
    return {"eq_harness.py": s(eq_root / "eq_harness.py"), "eq_mediator.py": s(eq_root / "eq_mediator.py"),
            "eq_calibrate.py": sha256_file(Path(__file__).resolve()), "eq_analyse.py": s(HERE / "eq_analyse.py"),
            "flags.json": s(eq_root / "flags.json"), "schedule.tsv": s(eq_root / "schedule.tsv"),
            "COMPARE_eq.sha256": frozen["sidecar_sha256"]}


def stage_ledger(st: Stage, frozen: dict[str, Any]) -> dict[str, Any]:
    return {"ledger_sha256": frozen["ledger_sha256"], "manifest_sha256": frozen["manifest_sha256"],
            "frozen_at_utc": frozen["frozen_at_utc"],
            "run_tags": sorted({str(r.get("run_tag")) for r in st.run.calls if r.get("run_tag")}),
            "inputs": dict(sorted(st.inputs.items()))}


def agent_sha(st: Stage, agent: str) -> str | None:
    v = st.config.get(f"agent_sha256_{agent}")
    return v if v and re.fullmatch(r"[0-9a-f]{64}", v) else None


def calibrate_p(st: Stage, cal: Cal, frozen: dict[str, Any], route2_on: bool,
                created_utc: str) -> tuple[dict[str, Any], dict[str, Any]]:
    flags = st.flags
    ns = cal.nstar()
    p7 = cal.p7()
    rep = cal.repair_rounds()
    cert = cal.choose_certainty()
    usd = cal.usd_per_mtok()
    report: dict[str, Any] = {"stage": "p", "nstar": ns, "p7": p7, "repair": rep, "certainty": cert, "caps": {},
                              "usd_per_mtok": usd, "models": {}}
    route_calls = [c for cls in CAL_CLASSES for c in cal.cap_calls(cls)]
    r2 = cal.route2(route_calls) if route2_on else None
    if r2 is not None and (r2["disagree"] or r2["missing"]):
        raise CalibrationError(f"route 2 (transcripts) disagrees with the ledger on {len(r2['disagree'])} member "
                               f"call(s) beyond 1 % and lacks {len(r2['missing'])}: {r2['disagree'][:5]} "
                               f"{r2['missing'][:5]}")
    classes = {c: empty_class() for c in CLASSES}
    models: set[str] = set()
    for cls in CAL_CLASSES:
        e = classes[cls]
        stype = str(flags["s_star"][cls])
        e["member_type"] = member_type(st, cls, stype)
        mid, all_m = cal.model_of(cls)
        models |= set(all_m)
        report["models"][cls] = all_m
        e["member_model_id"] = mid
        e["agent_file_sha256"] = agent_sha(st, e["member_type"])
        e["N"] = ns[cls]["N"]
        if cls in ("RS", "ES"):
            e["rounds"] = (p7["rounds"].get(cls) or {}).get("rounds")
        elif cls in ("PF", "CP"):
            e["rounds"] = rep[cls]["rounds"]
        else:
            e["rounds"] = 0  # finding sets: no member re-ask rounds (§4.2)
        e["view"] = (flags.get("view") or {}).get(cls)
        e["loo_view"] = "none" if cls == "CR" else p7["variant"]
        e["reducer"] = "R0"
        e["tau"] = float(Fraction(str(flags.get("tau", "0.6"))))
        e["t"] = int(flags.get("finding_t", 2))
        cp = cal.caps(cls, e["N"], e["rounds"])
        report["caps"][cls] = cp
        e["caps"] = cp["caps"]
        e["usd_per_mtok"] = usd.get(mid) if mid else None
        e["certainty"] = (cert.get(cls) or {}).get("certainty")
        e["pool"] = pool_entry(st.eq_root, cls, frozen["pool_sha256"][cls])
        if candidate_ok(e):
            e["status"] = "candidate"  # p's selection, untested: E_rt's bundle in q (manual mode only, unvalidated)
    prov = provenance(st, None, frozen, created_utc, ["p"], sorted(models), {"p": r2_summary(r2)})
    return {"schema": SCHEMA, "version": -1, "created_utc": created_utc, "provenance": prov, "classes": classes}, report


CANDIDATE_REQUIRED = ("member_type", "N", "rounds", "view", "loo_view", "reducer", "tau", "t", "caps", "pool")


def candidate_ok(e: dict[str, Any]) -> bool:
    """USER decision 2026-10-06 (COMPARE_eq §12 A6 note (e)): after stage p a class whose p-selected bundle is complete
    and eligible (N* >= 3; N* = 1 is not) gets status `candidate`: the runtime honours it in eq-mode manual only,
    labelled unvalidated (q's E_rt runs it); auto stays refused. Anything else stays not_run."""
    return all(e.get(k) is not None for k in CANDIDATE_REQUIRED) and int(e["N"]) >= 3


def member_type(st: Stage, cls: str, a_priori: str) -> str:
    """§1 / §7.1: the a-priori S* type (p1). The p5 screening cell was not funded (D2); a stage holding p5 calls is
    refused, because this version defines no p5 grade format (a funded p5 needs an amendment and code)."""
    if any(c.label == "p5" and c.cls == cls for c in st.calls):
        raise CalibrationError(f"stage {st.name} holds p5 (S* screening) calls for {cls}: not supported by A6")
    return a_priori


def r2_summary(r2: dict[str, Any] | None) -> dict[str, Any]:
    if r2 is None:
        return {"status": "skipped (--no-route2)"}
    return {"status": "agree", "n_calls": r2["n_calls"], "max_rel_diff": r2["max_rel_diff"]}


def provenance(st: Stage, prev: dict[str, Any] | None, frozen: dict[str, Any], created_utc: str,
               stages: list[str], models: list[str], route2: dict[str, Any]) -> dict[str, Any]:
    pp = (prev or {}).get("provenance") or {}
    ledgers = dict(pp.get("stage_ledgers") or {})
    ledgers[st.name] = stage_ledger(st, frozen)
    cfg = dict(pp.get("config_sha256") or {})
    cfg[st.name] = st.inputs.get("inputs/CONFIG.txt")
    gk = dict(pp.get("grader_kappa") or {})
    gk[st.name] = st.grader_kappa
    r2 = dict(pp.get("route2") or {}) | route2
    return {"created_utc": created_utc, "note": f"calibration stages {'+'.join(stages)}", "stages": stages,
            "harness_commit": harness_commit(), "sha256": file_shas(st.eq_root, frozen),
            "amendments": frozen["amendments"] + [f"sidecar: {x}" for x in frozen["amended_lines"]],
            "pool_sha256": frozen["pool_sha256"], "stage_ledgers": ledgers, "config_sha256": cfg,
            "claude_code_version": st.config.get("claude_version") or pp.get("claude_code_version"),
            "stack_commit": st.config.get("stack_commit") or pp.get("stack_commit"),
            "model_ids": sorted(set(models) | set(pp.get("model_ids") or [])), "grader_kappa": gk, "route2": r2,
            "report": None}


def calibrate_q(st: Stage, cal: Cal, frozen: dict[str, Any], prev: dict[str, Any], primary: list[str], m_ship: float,
                route2_on: bool, created_utc: str) -> tuple[dict[str, Any], dict[str, Any]]:
    if "p" not in ((prev.get("provenance") or {}).get("stages") or []):
        raise CalibrationError("--stage q needs the stage-p params (params.json from `--stage p`) first")
    for cls in primary:
        n = prev["classes"][cls].get("N")
        if n is None or n < 3:
            raise CalibrationError(f"primary class {cls} is not eligible (N* = {n} on p): no confirmation for it")
    tests = []
    per: dict[str, dict[str, Any]] = {}
    for cls in primary:
        per[cls] = {"H1": cal.contrast(cls, "S*"), "H2": cal.contrast(cls, "G")}
        tests += [(cls, "H1"), (cls, "H2")]
    adj = ea.holm([per[c][h]["p"] for c, h in tests])
    for (c, h), p in zip(tests, adj, strict=True):
        per[c][h]["p_holm"] = p
    classes = {c: dict(prev["classes"][c]) for c in CLASSES}
    for c in CLASSES:
        classes[c]["status"] = "not_run"
    report: dict[str, Any] = {"stage": "q", "primary": primary, "m": m_ship, "tests": per, "h4": {}, "h5": {},
                              "certainty": {}, "caps": {}, "usd_per_mtok": {}}
    h5_tests = []
    used_calls: list[Call] = []
    for cls in primary:
        e = classes[cls]
        t = per[cls]
        confirmed = {h: t[h]["p_holm"] <= ALPHA and t[h]["wins"] > t[h]["losses"] for h in ("H1", "H2")}
        ship = [h for h in ("H1", "H2") if confirmed[h] and t[h]["cost_ratio"] is not None
                and t[h]["cost_ratio"]["median"] <= m_ship]
        refuted = all((t[h]["p_holm"] <= ALPHA and t[h]["losses"] > t[h]["wins"])
                      or (t[h]["ci95"] is not None and t[h]["ci95"][1] < 0.6) for h in ("H1", "H2"))
        e["status"] = "validated" if ship else "refuted" if refuted else "not_established"
        use = ship[0] if ship else next((h for h in ("H1", "H2") if confirmed[h]), "H1")
        e["effect"] = {k: t[use][k] for k in ("wins", "losses", "ties", "pi_hat", "ci95", "p_holm")}
        e["cost_ratio"] = t[use]["cost_ratio"]
        report["tests"][cls]["used"] = use
        report["tests"][cls]["confirmed"] = confirmed
        h4 = cal.h4(cls)
        report["h4"][cls] = h4
        e["reducer"] = h4["reducer"]
        h5 = cal.h5(cls, str(e.get("loo_view")))
        if h5 and "p" in h5:
            h5_tests.append((cls, h5))
        report["h5"][cls] = h5
        pc = (prev["classes"][cls].get("certainty") or None)
        if cls in BINARY and pc:
            r = cal.reestimate(cal.e_signals().get(cls, []), pc)
            e["certainty"] = r["certainty"]
            report["certainty"][cls] = r
        else:
            e["certainty"] = None
        qcalls = cal.cap_calls(cls)
        if qcalls:  # E with harness member calls: caps and models from q; the runtime arm (E_rt): kept from p
            used_calls += qcalls
            cp = cal.caps(cls, e["N"], e["rounds"])
            report["caps"][cls] = cp
            e["caps"] = cp["caps"] or e["caps"]
            mid, _ = cal.model_of(cls)
            e["member_model_id"] = mid or e["member_model_id"]
        sha = agent_sha(st, str(e.get("member_type")))
        e["agent_file_sha256"] = sha or e["agent_file_sha256"]
    for c in CLASSES:
        if c not in primary:
            classes[c]["cost_ratio"] = classes[c]["effect"] = None
    if h5_tests:
        adj5 = ea.holm([h["p"] for _, h in h5_tests])
        for (_c, h), p in zip(h5_tests, adj5, strict=True):
            h["p_holm"] = p
    usd = cal.usd_per_mtok()
    report["usd_per_mtok"] = usd
    for cls in primary:
        mid = classes[cls]["member_model_id"]
        if mid in usd:
            classes[cls]["usd_per_mtok"] = usd[mid]
    r2 = cal.route2(used_calls) if route2_on and used_calls else None
    if r2 is not None and (r2["disagree"] or r2["missing"]):
        raise CalibrationError(f"route 2 (transcripts) disagrees with the ledger on {len(r2['disagree'])} member "
                               f"call(s) beyond 1 % and lacks {len(r2['missing'])}")
    validated = [c for c in primary if classes[c]["status"] == "validated"]
    if validated and not route2_on:
        raise CalibrationError("a class would be validated with the route-2 check skipped (--no-route2)")
    for c in validated:
        missing = [k for k in CLASS_KEYS if k != "certainty" and classes[c][k] is None]
        if missing:
            raise CalibrationError(f"class {c} passes the tests but lacks {missing}: resolve (e.g. agent_sha256_<type> "
                                   "in CONFIG.txt, an unambiguous model id) and rerun")
    models = sorted({classes[c]["member_model_id"] for c in CLASSES if classes[c]["member_model_id"]})
    r2q = (r2_summary(r2) if r2 is not None else
           {"status": "not applicable: no harness member calls in q (caps and models kept from p)"} if route2_on
           else {"status": "skipped (--no-route2)"})
    prov = provenance(st, prev, frozen, created_utc, ["p", "q"], models, {"q": r2q})
    return {"schema": SCHEMA, "version": -1, "created_utc": created_utc, "provenance": prov, "classes": classes}, report


# ---------------------------------------------------------------------------------------------------------------------
# step 5: versioned, append-only output
# ---------------------------------------------------------------------------------------------------------------------


def read_chain(out: Path) -> list[dict[str, Any]]:
    """The history, verified: every version file hashes to its line, prev_sha256 links, and params.json and its
    sidecar equal the latest version."""
    hp = out / "params.history.jsonl"
    if not hp.is_file():
        return []
    lines = [json.loads(ln) for ln in hp.read_text(encoding="utf-8").splitlines() if ln.strip()]
    prev = None
    for i, h in enumerate(lines):
        if h.get("version") != i:
            raise CalibrationError(f"params.history.jsonl line {i + 1}: version {h.get('version')} != {i}")
        vp = out / f"params.v{i}.json"
        if not vp.is_file() or sha256_file(vp) != h.get("sha256"):
            raise CalibrationError(f"params.v{i}.json is missing or differs from its history line")
        if h.get("prev_sha256") != prev:
            raise CalibrationError(f"params.history.jsonl line {i + 1}: prev_sha256 does not link")
        prev = h["sha256"]
    pj, sc = out / "params.json", out / "params.json.sha256"
    if lines:
        if not pj.is_file() or sha256_file(pj) != prev:
            raise CalibrationError("params.json is not the latest version")
        if not sc.is_file() or sc.read_text(encoding="utf-8").split()[0] != prev:
            raise CalibrationError("params.json.sha256 does not match params.json")
    return lines


def write_version(out: Path, params: dict[str, Any], report: dict[str, Any] | None, stages: list[str],
                  amendment: str | None, reason: str) -> int:
    lines = read_chain(out)
    k = len(lines)
    vp = out / f"params.v{k}.json"
    if vp.exists():
        raise CalibrationError(f"{vp} exists: a version is never rewritten")
    out.mkdir(parents=True, exist_ok=True)
    params = json.loads(json.dumps(params))
    params["version"] = k
    if report is not None:
        rp = out / f"report.v{k}.json"
        if rp.exists():
            raise CalibrationError(f"{rp} exists")
        rtext = dumps(report)
        with rp.open("x", encoding="utf-8") as f:
            f.write(rtext)
        params["provenance"]["report"] = {"path": rp.name, "sha256": sha256_bytes(rtext.encode())}
    text = dumps(params)
    with vp.open("x", encoding="utf-8") as f:
        f.write(text)
    sha = sha256_bytes(text.encode())
    tmp = out / ".params.json.tmp"
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, out / "params.json")
    tmp.write_text(f"{sha}  params.json\n", encoding="utf-8")
    os.replace(tmp, out / "params.json.sha256")
    line = {"version": k, "created_utc": params["created_utc"], "sha256": sha,
            "prev_sha256": lines[-1]["sha256"] if lines else None, "stages": stages, "amendment": amendment,
            "reason": reason}
    with (out / "params.history.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps(line, sort_keys=True, ensure_ascii=False) + "\n")
    return k


# ---------------------------------------------------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------------------------------------------------


def default_paths() -> tuple[Path, Path, Path]:
    repo = next((p for p in HERE.parents if (p / ".git").exists()), HERE.parents[1])
    return (Path(os.environ.get("EQ_ROOT", str(repo / "claude_next_steps/work_carried/equilibrium"))),
            Path(os.environ.get("EQ_RAW", str(repo / ".claude-work/equilibrium/runs"))),
            HERE.parent / "calibration")


def main(argv: Sequence[str] | None = None) -> int:
    eq_d, raw_d, out_d = default_paths()
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n")[0])
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--stage", choices=["p", "q"])
    g.add_argument("--init", action="store_true", help="write version 0 (every class not_run) into an empty --out")
    ap.add_argument("--eq-root", type=Path, default=eq_d)
    ap.add_argument("--raw-root", type=Path, default=raw_d)
    ap.add_argument("--out", type=Path, default=out_d)
    ap.add_argument("--primary", default="", help="q: the primary classes of the q amendment, comma-separated (<= 2)")
    ap.add_argument("--m", type=float, default=DEFAULT_M_SHIP, help="ship multiplier m (COMPARE_eq §7.2; D10: 2)")
    ap.add_argument("--amendment", default=None, help="the dated §12 amendment this version belongs to (A<n>)")
    ap.add_argument("--reason", default=None)
    ap.add_argument("--no-route2", action="store_true", help="skip the transcript check (refused if a class would "
                                                             "be validated)")
    ap.add_argument("--created-utc", default=None)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    created = a.created_utc or utc_now()
    try:
        if a.init:
            if read_chain(a.out):
                raise CalibrationError(f"{a.out} already holds a params history: version 0 exists")
            k = write_version(a.out, not_run_params(created), None, [], None, "no calibration")
            print(f"eq_calibrate: wrote {a.out / f'params.v{k}.json'} (every class not_run)")
            return 0
        if not a.amendment or not re.fullmatch(r"A[0-9]+", a.amendment) or not a.reason:
            raise CalibrationError("--amendment A<n> and --reason are required (a rerun is a new version and a new "
                                   "dated §12 amendment)")
        frozen = verify_frozen(a.eq_root, a.stage)
        eh = load_frozen_harness(a.eq_root)
        warnings: list[str] = []
        st = read_stage(a.eq_root, a.stage, a.raw_root, warnings)
        cal = Cal(st, eh)
        if a.stage == "p":
            params, report = calibrate_p(st, cal, frozen, not a.no_route2, created)
            stages = ["p"]
        else:
            primary = [c for c in a.primary.split(",") if c]
            if not primary or len(primary) > 2 or any(c not in CLASSES for c in primary):
                raise CalibrationError("--primary needs 1 or 2 classes (COMPARE_eq §7.1)")
            chain = read_chain(a.out)
            if not chain:
                raise CalibrationError(f"no params history in {a.out}")
            prev = json.loads((a.out / "params.json").read_text(encoding="utf-8"))
            params, report = calibrate_q(st, cal, frozen, prev, primary, a.m, not a.no_route2, created)
            stages = ["p", "q"]
        report["warnings"] = warnings
        report["skipped"] = cal.skipped
        if a.dry_run:
            print(dumps({"params": params, "report": report}), end="")
            return 0
        k = write_version(a.out, params, report, stages, a.amendment, a.reason)
        st_line = ", ".join(f"{c} {params['classes'][c]['status']}" for c in CLASSES)
        print(f"eq_calibrate: wrote {a.out / f'params.v{k}.json'} (stage {a.stage}: {st_line}); "
              f"{len(warnings)} warning(s), {len(cal.skipped)} skipped unit(s) in report.v{k}.json")
        print("eq_calibrate: nothing is installed: Phase 5 copies params.json to dot-claude/hooks/eq_params.json by "
              "a commit, then the USER runs ./install.sh")
        return 0
    except CalibrationError as e:
        print(f"eq_calibrate: refused: {e}", file=sys.stderr)
        return 2
    except Exception as e:
        if os.environ.get("EQ_CALIBRATE_TRACEBACK") == "1":
            traceback.print_exc()
        print(f"eq_calibrate: internal error: {type(e).__name__}: {e}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    sys.exit(main())
