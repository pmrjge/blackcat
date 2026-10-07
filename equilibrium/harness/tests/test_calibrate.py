"""eq_calibrate.py (RUNTIME_EQUILIBRIUM.md §7, COMPARE_eq.md §12 A6): every selection rule, the freeze refusal, route 2,
the append-only params chain and the schema, on synthetic frozen stages built here (no paid call, no real ledger).

Ledger field names used by the fixtures are the harness's (LEDGER_SCHEMA.md v1) plus the E2/D3 fields: call `cell`,
`branch`, `parent_session_id`, `model_ids`; mediator `attribution` {round, loo, lambda, pivotal}.
"""

from __future__ import annotations

import hashlib
import itertools
import json
import math
import shutil
from pathlib import Path
from typing import Any

import numpy as np
import pytest

import eq_analyse as ea
import eq_calibrate as cal
import eq_harness as eh

HARNESS = Path(__file__).resolve().parent.parent
SCHEMA_PATH = HARNESS.parent / "calibration" / "params.schema.json"
MODEL = "claude-opus-test-1"
CREATED = "2026-10-06T12:00:00Z"
A = {"label": "SUPPORTED", "why": "x"}
B = {"label": "REFUTED", "value": "v1"}
C = {"label": "NOT_ENOUGH"}
GOOD = {json.dumps(A, sort_keys=True)}


def sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


# ---------------------------------------------------------------------------------------------------------------------
# synthetic frozen package + stages
# ---------------------------------------------------------------------------------------------------------------------


class Fx:
    """A frozen $EQ tree (sidecar, pools, ES truth) plus stages appended with call/record helpers, then collected."""

    def __init__(self, root: Path):
        self.root = root
        self.eq = root / "eq"
        self.raw = root / "raw"
        self.out = root / "calibration"
        self.eq.mkdir(parents=True)
        shutil.copy2(HARNESS / "eq_harness.py", self.eq / "eq_harness.py")
        shutil.copy2(HARNESS / "flags.json", self.eq / "flags.json")
        (self.eq / "schedule.tsv").write_text("item\tarms\n")
        (self.eq / "COMPARE_eq.md").write_text("# COMPARE_eq\n\n## 12. Amendments (dated; append only)\n\n"
                                               "- **A5. path relativisation.**\n- **A6. 2026-10-06, PRE-FREEZE.**\n")
        for c in cal.CLASSES:
            d = self.eq / "items" / c
            d.mkdir(parents=True)
            (d / "README.md").write_text(f"# {c} pool (synthetic)\n")
            (d / "manifest.jsonl").write_text("{}\n")
            if c == "ES":
                (d / "oracle").mkdir()
                (d / "oracle" / "truth.jsonl").write_text("".join(
                    json.dumps({"id": f"ES-{i}", "true_value": 100.0}) + "\n" for i in range(1, 30)))
            files = sorted(p for p in d.rglob("*") if p.is_file())
            (d / "pool.sha256").write_text("".join(f"{sha(p.read_bytes())}  {p.relative_to(d)}\n" for p in files))
        files = sorted(p for p in self.eq.rglob("*") if p.is_file())
        (self.eq / "COMPARE_eq.sha256").write_text(
            "# frozen_at_utc: 2026-10-07T00:00:00Z\n"
            + "".join(f"{sha(p.read_bytes())}  ./{p.relative_to(self.eq)}\n" for p in files))
        self.rec: dict[str, list[dict[str, Any]]] = {"p": [], "q": []}
        self.med: dict[str, dict[tuple[str, str], list[dict[str, Any]]]] = {"p": {}, "q": {}}
        self.grades: dict[str, dict[str, list[dict[str, Any]]]] = {"p": {}, "q": {}}
        self.tx: dict[str, dict[str, list[dict[str, Any]]]] = {"p": {}, "q": {}}
        self.config: dict[str, dict[str, str]] = {"p": {}, "q": {}}
        self.n = 0

    # -- records --------------------------------------------------------------------------------------------------
    def call(self, stage: str, item: str, cls: str, label: str, arm: str | None, role: str, *,
             member: int | None = None,
             rnd: int = 0, cell: str | None = None, branch: str | None = None, answer: Any = None,
             parent: str | None = None, ctx: int = 10_000, out: int = 500, cost: float = 0.05, turns: int = 6,
             agent: str = "researcher", charged: list[str] | None = None, model: str = MODEL) -> dict[str, Any]:
        self.n += 1
        sid = f"{self.n:08x}-0000-4000-8000-{self.n:012x}"
        r = {"record": "call", "call_id": f"{self.n:05d}_{role.replace('/', 'of')}", "run_tag": f"T-{stage}",
             "item": item, "cls": cls, "label": label, "arm": arm, "charged_to": charged or [label], "role": role,
             "agent": agent, "member": member, "node": None, "round": rnd, "cap_usd": "0.280000", "argv": [],
             "session_id": sid, "parent_session_id": parent, "model_ids": sorted({model, "claude-haiku-bg"}),
             "cell": cell, "branch": branch, "total_cost_usd": cost,
             "usage": {"input_tokens": ctx // 2, "cache_creation_input_tokens": ctx // 4,
                       "cache_read_input_tokens": ctx - ctx // 2 - ctx // 4, "output_tokens": out},
             "cap_stop": False, "schema_valid": answer is not None, "answer": answer, "num_turns": turns}
        self.rec[stage].append(r)
        # transcript: two assistant messages (the first streamed twice) summing to ctx
        self.tx[stage][sid] = [
            {"type": "assistant", "message": {"id": f"msg-{sid}-1", "model": model,
                                              "usage": {"input_tokens": 1, "output_tokens": 0}}},
            {"type": "assistant", "message": {"id": f"msg-{sid}-1", "model": model,
                                              "usage": {"input_tokens": ctx // 2, "output_tokens": 3}}},
            {"type": "assistant", "message": {"id": f"msg-{sid}-2", "model": model,
                                              "usage": {"cache_creation_input_tokens": ctx // 4,
                                                        "cache_read_input_tokens": ctx - ctx // 2 - ctx // 4}}}]
        return r

    def add(self, stage: str, record: str, **kw: Any) -> None:
        self.rec[stage].append({"record": record, **kw})

    def grade(self, stage: str, fname: str, **kw: Any) -> None:
        self.grades[stage].setdefault(fname, []).append({"ts_utc": "2026-10-08T00:00:00Z", **kw})

    def mediator(self, stage: str, item: str, label: str, record: str, **kw: Any) -> None:
        self.med[stage].setdefault((item, label), []).append({"record": record, "item": item, "label": label,
                                                             "node": None, **kw})

    # -- collection (what eq_freeze.sh --collect leaves) -----------------------------------------------------------
    def collect(self, stage: str) -> None:
        run = self.eq / "runs" / stage
        inp = run / "inputs"
        inp.mkdir(parents=True)
        lines = [{"record": "run_start", "stub": False}] + self.rec[stage] + [{"record": "run_end"}]
        text = "".join(json.dumps({"schema_version": 1, "seq": i + 1, "ts_utc": "2026-10-07T01:00:00Z",
                                   "stage": stage, **r}, sort_keys=True) + "\n" for i, r in enumerate(lines))
        (run / "ledger.jsonl").write_text(text)
        (inp / "ledger.jsonl").write_text(text)
        cfg = {"label": stage, "claude_version": "2.1.287 (Claude Code)", "stack_commit": "abc123",
               "agent_sha256_researcher": "a" * 64, "agent_sha256_data-scientist": "b" * 64,
               "agent_sha256_mathematician": "c" * 64, "agent_sha256_python-engineer": "d" * 64,
               "agent_sha256_code-reviewer": "e" * 64} | self.config[stage]
        (inp / "CONFIG.txt").write_text("".join(f"{k}: {v}\n" for k, v in cfg.items()))
        for (item, label), recs in self.med[stage].items():
            d = inp / "mediator" / item / label
            d.mkdir(parents=True)
            (d / "mediator.jsonl").write_text("".join(
                json.dumps({"schema_version": 1, "seq": i + 1, "stage": stage, **r}) + "\n"
                for i, r in enumerate(recs)))
        troot = self.raw / stage / "transcripts" / "-tmp-x"
        troot.mkdir(parents=True)
        for sid, msgs in self.tx[stage].items():
            (troot / f"{sid}.jsonl").write_text("".join(json.dumps(m) + "\n" for m in msgs))
        tr = self.raw / stage / "transcripts"
        (inp / "TRANSCRIPTS.sha256").write_text("".join(
            f"{sha(p.read_bytes())}  ./{p.relative_to(tr)}\n" for p in sorted(tr.rglob("*.jsonl"))))
        side = sha((self.eq / "COMPARE_eq.sha256").read_bytes())
        (inp / "FROZEN_AT.txt").write_text(f"frozen_at_utc: 2026-10-07T02:00:00Z\nstage: {stage}\n"
                                           f"sidecar_sha256: {side}\n")
        files = sorted(p for p in inp.rglob("*") if p.is_file() and p.name != "MANIFEST.sha256")
        (inp / "MANIFEST.sha256").write_text("".join(f"{sha(p.read_bytes())}  ./{p.relative_to(inp)}\n"
                                                     for p in files))
        g = run / "grading_results"
        for fname, rows in self.grades[stage].items():
            p = g / fname
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("".join(json.dumps(r) + "\n" for r in rows))

    def run(self, *args: str) -> int:
        return cal.main([*args, "--eq-root", str(self.eq), "--raw-root", str(self.raw), "--out", str(self.out),
                         "--created-utc", CREATED])

    def params(self) -> dict[str, Any]:
        return json.loads((self.out / "params.json").read_text())

    def report(self, k: int) -> dict[str, Any]:
        return json.loads((self.out / f"report.v{k}.json").read_text())


# ---------------------------------------------------------------------------------------------------------------------
# the scenario: stage p (p3 + p6 + p7 on RS/ES, p3 + p6 on PF/CP, p6 on CR) and stage q (RS primary)
# ---------------------------------------------------------------------------------------------------------------------

RS_P6 = {"RS-1": [A] * 6 + [B] * 3, "RS-2": [A] * 5 + [B] * 2 + [C] * 2, "RS-3": [A] * 4 + [B] * 5,
         "RS-4": [A] * 7 + [C] * 2, "RS-5": [A] * 3 + [B] * 3 + [C] * 3, "RS-6": [A] * 2 + [B] * 7}
RS_P3 = {"RS-1": [A, A, A, B, B], "RS-2": [A, B, C, A, C], "RS-3": [B, B, B, A, A], "RS-4": [A] * 5,
         "RS-5": [B, C, A, A, C], "RS-6": [B, B, B, B, A]}
ES_P6 = {"ES-1": [50, 80, 90, 100, 110, 130, 200, 300, 400], "ES-2": [10, 20, 30, 90, 95, 100, 120, 150, 1000],
         "ES-3": [300, 350, 400, 410, 420, 80, 90, 100, 110], "ES-4": [99, 100, 101, 102, 98, 97, 103, 300, 30],
         "ES-5": [5, 6, 7, 8, 100, 110, 120, 9, 10]}
ES_P3 = {"ES-1": [80, 90, 100, 110, 400], "ES-2": [20, 30, 95, 100, 1000], "ES-3": [300, 350, 400, 90, 100],
         "ES-4": [99, 100, 101, 300, 30], "ES-5": [5, 6, 7, 100, 110]}
CHECK_P6 = {"PF-1": ([1, 1, 0, 0, 0, 0, 0, 0, 0], [1, 0, 0, 0, 0, 0, 0, 0, 0]),
            "PF-2": ([1, 0, 0, 0, 0, 0, 0, 0, 0], [1, 0, 0, 0, 0, 0, 0, 0, 0]),
            "PF-3": ([0, 0, 0, 0, 0, 0, 0, 0, 1], [0, 0, 0, 0, 0, 0, 0, 0, 1]),
            "CP-1": ([1, 1, 1, 0, 0, 0, 0, 0, 0], [1, 1, 0, 0, 0, 0, 0, 0, 0]),
            "CP-2": ([0, 0, 0, 0, 1, 0, 0, 0, 0], [0, 0, 0, 0, 1, 0, 0, 0, 0])}
F1 = {"file": "a.py", "line": 10, "claim": "off by one"}
F1b = {"file": "a.py", "line": 11, "claim": "loop bound"}
F2 = {"file": "b.py", "line": 20, "claim": "null deref"}
FX = {"file": "c.py", "line": 5, "claim": "style"}
CR_P6 = {"CR-1": [[F1], [F1b, FX], [F2], [F1, F2], [], [FX], [F1], [F2], [FX]],
         "CR-2": [[F2], [F2, F1], [], [FX], [F1b], [], [F2], [FX, F1], [F2]]}
CR_GRADES = {json.dumps(F1, sort_keys=True): ("b1", "true"), json.dumps(F1b, sort_keys=True): ("b1", "true"),
             json.dumps(F2, sort_keys=True): ("b2", "true"), json.dumps(FX, sort_keys=True): (None, "false")}
AGENT = {"RS": "researcher", "ES": "data-scientist", "PF": "mathematician", "CP": "python-engineer",
         "CR": "code-reviewer"}


def rs_grade(a: Any) -> int:
    return int(isinstance(a, dict) and a.get("label") == "SUPPORTED")


def rs_variant_answers(variant: str, base: list[Any], r: int) -> list[Any]:
    """rotation: every wrong member switches to A in round 1; random: the first wrong one; leader: a right one turns
    wrong; none: no change."""
    out = list(base)
    if variant == "rotation":
        out = [A for _ in out]
    elif variant == "random":
        i = next((k for k, a in enumerate(out) if not rs_grade(a)), None)
        if i is not None:
            out[i] = A
    elif variant == "leader":
        i = next((k for k, a in enumerate(out) if rs_grade(a)), None)
        if i is not None:
            out[i] = B
    return out


def build_p(fx: Fx, *, p7: bool = True) -> None:
    st = "p"
    for item, ans in RS_P6.items():
        for m, a in enumerate(ans, 1):
            fx.call(st, item, "RS", "p6", "E", f"m{m}/9", member=m, cell="p6", answer=a, ctx=9000 + 300 * m,
                    turns=4 + m % 3)
            fx.grade(st, "members/RS.jsonl", item=item, label="p6", member=m, round=0, branch=None,
                     score=rs_grade(a))
    for cls, src in (("RS", RS_P3), ("ES", ES_P3)):
        for item, ans in src.items():
            sess = {}
            for m, a in enumerate(ans, 1):
                r = fx.call(st, item, cls, "p3", "E", f"m{m}/5", member=m, answer=a, agent=AGENT[cls],
                            ctx=8000 + 500 * m)
                sess[m] = r["session_id"]
                if cls == "RS":
                    fx.grade(st, "members/RS.jsonl", item=item, label="p3", member=m, round=0, branch=None,
                             score=rs_grade(a))
            if cls == "RS":
                keys = [eh.make_answer_key({"fields": ["label"], "when": [{"if": {"label": "REFUTED"},
                                                                          "add": ["value"]}]})(a) for a in ans]
                top = max(keys.count(k) for k in set(keys))
                win = sorted(k for k in set(keys) if keys.count(k) == top)[0]
                score = int(win == json.dumps({"label": "supported"}))
                kappa0 = top / 5
                fx.grade(st, "RS.jsonl", item=item, label="p3", score=score)
            else:
                med = eh.median_ln(ans)
                e = abs(math.log(med / 100.0))
                kappa0 = eh.kappa_numeric(ans)
                fx.grade(st, "ES.jsonl", item=item, label="p3", score=e, score_num=e, score_inf=False)
            fx.add(st, "item_arm", item=item, cls=cls, label="p3", arm="E", status="ok", answer=None, B_usd="2.00",
                   started_utc="2026-10-07T01:00:00Z", ended_utc="2026-10-07T01:10:00Z", calls=[], kappa0=kappa0,
                   rounds=1)
            lam0 = 0.6 if kappa0 < 0.8 else 1.0
            fx.mediator(st, item, "p3", "attribution", round=0, loo={}, pivotal=[],
                        **{"lambda": {"num": int(lam0 * 5), "den": 5, "float": lam0}})
            fx.mediator(st, item, "p3", "attribution", round=1, loo={}, pivotal=[], **{"lambda": lam0})
            if p7:
                for v in cal.VARIANTS:
                    prev = {m: ans[m - 1] for m in sess}
                    psess = dict(sess)
                    for r in (1, 2):
                        new = (rs_variant_answers(v, list(prev.values()), r) if cls == "RS"
                               else [x if v == "none" else (100 if v == "rotation" else x) for x in prev.values()])
                        for m in sorted(prev):
                            c = fx.call(st, item, cls, "p7", "E", f"r{r}", member=m, rnd=r, cell="p7", branch=v,
                                        answer=new[m - 1], parent=psess[m], agent=AGENT[cls])
                            psess[m] = c["session_id"]
                            changed = json.dumps(new[m - 1]) != json.dumps(prev[m])
                            ok = changed and not (v == "leader" and r == 2)  # leader round 2: conformity
                            fx.add(st, "reconcile", round=r, member=m, call_id=c["call_id"], prev_answer=prev[m],
                                   proposed_answer=new[m - 1], changed=changed, accepted=ok,
                                   conformity=changed and not ok)
                            if cls == "RS":
                                fx.grade(st, "members/RS.jsonl", item=item, label="p7", member=m, round=r, branch=v,
                                         score=rs_grade(new[m - 1]))
                        prev = {m: new[m - 1] if not (v == "leader" and r == 2) else prev[m] for m in prev}
    for item, ans in ES_P6.items():
        for m, a in enumerate(ans, 1):
            fx.call(st, item, "ES", "p6", "E", f"m{m}/9", member=m, cell="p6", answer=a, agent="data-scientist",
                    ctx=7000 + 100 * m)
    for item, (passed, hidden) in CHECK_P6.items():
        cls = item[:2]
        for m in range(1, 10):
            fx.call(st, item, cls, "p6", "E", f"m{m}/9", member=m, cell="p6", answer="proof", agent=AGENT[cls],
                    ctx=20000 + 1000 * m)
            fx.add(st, "check", item=item, label="p6", member=m, round=0, passed=bool(passed[m - 1]))
            fx.grade(st, f"members/{cls}.jsonl", item=item, label="p6", member=m, round=0, branch=None,
                     score=hidden[m - 1])
        for m in range(1, 6):
            fx.call(st, item, cls, "p3", "E", f"m{m}/5", member=m, answer="proof", agent=AGENT[cls], ctx=15000)
            fx.add(st, "check", item=item, label="p3", member=m, round=0, passed=bool(passed[m - 1]))
            fx.grade(st, f"members/{cls}.jsonl", item=item, label="p3", member=m, round=0, branch=None,
                     score=hidden[m - 1])
        repaired = not any(passed[:5])
        score = 1 if item in ("PF-1", "PF-2", "CP-1", "PF-3") else 0
        fx.add(st, "item_arm", item=item, cls=cls, label="p3", arm="E", status="ok", answer=None, B_usd="2.00",
               started_utc="2026-10-07T01:00:00Z", ended_utc="2026-10-07T01:10:00Z", calls=[], repaired=repaired)
        fx.grade(st, f"{cls}.jsonl", item=item, label="p3", score=score)
        fx.mediator(st, item, "p3", "attribution", round=0, loo={}, pivotal=[],
                    **{"lambda": 1.0 if sum(passed[:5]) >= 2 else 0.0})
    for item, ans in CR_P6.items():
        for m, a in enumerate(ans, 1):
            fx.call(st, item, "CR", "p6", "E", f"m{m}/9", member=m, cell="p6", answer=a, agent="code-reviewer",
                    ctx=30000 + 100 * m)
            for f in a:
                bug, verdict = CR_GRADES[json.dumps(f, sort_keys=True)]
                fx.grade(st, "members/CR_findings.jsonl", item=item, label="p6", member=m, round=0, finding=f,
                         bug=bug, verdict=verdict, n_seeded=2)
        fx.add(st, "reduce", item=item, label="p6", node=None, reducer="finding_clusters", t=2, kappa=None,
               clusters=[], verified_singles=["c.py||5"] if item == "CR-1" else [], answer=[])
    fx.collect(st)


def build_q(fx: Fx, *, e_tokens: int = 15_000, e_right: int = 14, s_right: int = 2, n: int = 14) -> None:
    st = "q"
    for i in range(1, n + 1):
        item = f"RS-q{i}"
        for label, arm, right in (("q1", "S*", i <= s_right), ("q2", "G", i <= s_right), ("q4", "EG", i <= 7)):
            fx.call(st, item, "RS", label, arm, "s" if arm == "S*" else "n1", answer=A if right else B, ctx=9000,
                    out=1000)
            fx.add(st, "item_arm", item=item, cls="RS", label=label, arm=arm, status="ok", answer=None,
                   B_usd="2.00", started_utc="2026-10-08T01:00:00Z", ended_utc="2026-10-08T01:05:00Z", calls=[])
            fx.grade(st, "RS.jsonl", item=item, label=label, score=int(right))
        good = i <= e_right
        ans = [A, A, A, A, B] if good else [B, B, B, A, A]
        for m, a in enumerate(ans, 1):
            fx.call(st, item, "RS", "q3", "E", f"m{m}/5", member=m, answer=a, ctx=e_tokens // 5 - 100 + 37 * i,
                    out=100)
            fx.grade(st, "members/RS.jsonl", item=item, label="q3", member=m, round=0, branch=None,
                     score=rs_grade(a))
        fx.add(st, "item_arm", item=item, cls="RS", label="q3", arm="E", status="ok", answer=None, B_usd="2.00",
               started_utc="2026-10-08T01:00:00Z", ended_utc="2026-10-08T01:05:00Z", calls=[],
               kappa0=0.8 if good else 0.6, rounds=0 if good else 1)
        fx.grade(st, "RS.jsonl", item=item, label="q3", score=int(good))
        fx.mediator(st, item, "q3", "attribution", round=0, loo={}, pivotal=[], **{"lambda": 1.0 if good else 0.4})
        fx.mediator(st, item, "q3", "result", answer=A if good else B,
                    reducers={"R0": A if good else B, "R1": A if good else B, "R2": A if good else B,
                              "R3": A, "ENS": A if good else B})
    fx.collect(st)


@pytest.fixture
def fx(tmp_path: Path) -> Fx:
    return Fx(tmp_path)


@pytest.fixture
def fxp(tmp_path: Path) -> Fx:
    f = Fx(tmp_path)
    build_p(f)
    assert f.run("--init") == 0
    return f


# ---------------------------------------------------------------------------------------------------------------------
# constants
# ---------------------------------------------------------------------------------------------------------------------


def test_seed_constants_are_the_harness_derivation():
    assert cal.SEED_NSTAR == eh.seed_for("eq|nstar") == 4122099631
    assert cal.SEED_AUROC == eh.seed_for("eq|auroc") == 3066176665
    assert cal.SEED_ROUNDS == eh.seed_for("eq|rounds") == 3549083166
    assert {"E-S*": eh.seed_for("eq|E-S*|P1"), "E-G": eh.seed_for("eq|E-G|P1")} == cal.SEED_P1


def test_ceil2_and_q90_follow_the_stack_convention():
    assert cal.ceil2(1_234_567) == 1_300_000
    assert cal.ceil2(1_200_000) == 1_200_000
    assert cal.ceil2(99.2) == 100
    assert cal.ceil2(7.2) == 8
    xs = list(range(1, 11))
    assert cal.q90(xs) == pytest.approx(9.1)  # type 7: (n-1)*0.9 = 8.1 -> 9 + 0.1


# ---------------------------------------------------------------------------------------------------------------------
# reducer scores on subsets
# ---------------------------------------------------------------------------------------------------------------------


def test_plurality_expected_averages_ties_and_scores_abstention_zero():
    g = {"a": 1.0, "b": 0.0, "c": 0.0}.__getitem__
    assert cal.plurality_expected(["a", "a", "b"], g) == 1.0
    assert cal.plurality_expected(["a", "b"], g) == 0.5
    assert cal.plurality_expected(["a", "b", "c"], g) == pytest.approx(1 / 3)
    assert cal.plurality_expected([None, None], g) == 0.0
    assert cal.plurality_expected([None, "b", "a", "a"], g) == 1.0


def test_checkable_expected_is_the_mean_hidden_score_of_the_passers():
    assert cal.checkable_expected([True, True, False], [1.0, 0.0, 1.0]) == 0.5
    assert cal.checkable_expected([False, False], [1.0, 1.0]) == 0.0
    assert cal.checkable_expected([True], [1.0]) == 1.0


def test_es_error_and_score_cap():
    assert cal.es_error(eh, [100, 200, 50], 100.0) == 0.0
    assert cal.es_error(eh, [None, "x"], 100.0) == math.inf
    assert cal.es_score(math.inf) == -math.log(10)
    assert cal.es_score(0.1) == -0.1


def test_findings_score_threshold_verified_singles_and_false_findings():
    fields = {"file": "file", "line": "line", "claim_class": None}
    f = [*eh.parse_findings([F1], 1, fields), *eh.parse_findings([F1b, FX], 2, fields),
         *eh.parse_findings([F2], 3, fields)]

    def grade(payload: str) -> tuple[str | None, str]:
        return CR_GRADES[json.dumps(json.loads(payload), sort_keys=True)]

    # a.py 10/11 cluster has support 2 (accepted, bug b1); b.py and c.py are singles, unverified -> not accepted
    assert cal.findings_score(eh, f, 2, set(), grade, 2, 3) == 0.5
    single_fx = next(x for x in f if x.file == "c.py")
    # a verified false single counts against: (1 - 0.5) / 2
    assert cal.findings_score(eh, f, 2, {(single_fx.member, single_fx.payload)}, grade, 2, 3) == 0.25
    b = next(x for x in f if x.file == "b.py")
    assert cal.findings_score(eh, f, 2, {(b.member, b.payload)}, grade, 2, 3) == 1.0


def test_score_m_is_the_mean_over_every_subset(fxp: Fx):
    """score(m) = mean over all C(9, m) subsets: checked against a brute force of the plurality on RS-1."""
    st = cal.read_stage(fxp.eq, "p", fxp.raw, [])
    c = cal.Cal(st, cal.load_frozen_harness(fxp.eq))
    ns = c.nstar()
    rs = ns["RS"]["curve"]
    brute = []
    for ans in RS_P6.values():
        row = []
        for m in cal.M_GRID:
            tot = 0.0
            for sub in itertools.combinations(range(9), m):
                ks = [json.dumps({"label": ans[i]["label"]}) for i in sub]
                cnt = {k: ks.count(k) for k in set(ks)}
                top = max(cnt.values())
                tied = [k for k, v in cnt.items() if v == top]
                tot += sum(k == json.dumps({"label": "SUPPORTED"}) for k in tied) / len(tied)
            row.append(tot / math.comb(9, m))
        brute.append(row)
    assert [r["mean"] for r in rs] == pytest.approx(list(np.mean(brute, axis=0)))
    ref = cal.one_se_select(np.array(brute), cal.M_GRID, 4122099631)  # seed eq|nstar
    assert [r["se_diff"] for r in rs] == pytest.approx([r["se_diff"] for r in ref[1]])
    assert ns["RS"]["N"] == ref[0]
    assert ns["RS"]["n_items"] == len(RS_P6)


# ---------------------------------------------------------------------------------------------------------------------
# selection rules
# ---------------------------------------------------------------------------------------------------------------------


def test_one_se_rule_picks_the_smallest_value_within_one_se():
    # m = 3 trails the best (5, 7, 9 tie at 0.8) by 0.01 with a paired spread of 0.05 per item: within one SE
    # (about 0.05 / sqrt(6) = 0.02); m = 1 trails by 0.3 with no spread: outside
    s = np.full((6, 5), 0.8)
    s[:, 0] = 0.5
    s[:, 1] = 0.79 + np.array([0.05, -0.05] * 3)
    choice, rows = cal.one_se_select(s, cal.M_GRID, cal.SEED_NSTAR)
    assert choice == 3
    assert rows[0]["within_1se"] is False and rows[1]["within_1se"] is True
    assert rows[1]["gap_to_best"] == pytest.approx(0.01) and rows[1]["se_diff"] > 0.01
    assert all(r["se_diff"] >= 0 for r in rows)
    assert cal.one_se_select(s, cal.M_GRID, cal.SEED_NSTAR) == (choice, rows)  # deterministic
    s[:, 1] = 0.79  # the same 0.01 gap without spread: no longer within one SE -> the best, 5
    assert cal.one_se_select(s, cal.M_GRID, cal.SEED_NSTAR)[0] == 5


def test_one_se_ties_go_to_the_smaller_value_and_n_one_is_possible():
    s = np.array([[1.0, 1.0, 1.0, 1.0, 1.0]] * 4)
    assert cal.one_se_select(s, cal.M_GRID, cal.SEED_NSTAR)[0] == 1
    s = np.array([[0.2, 0.9, 0.9, 0.9, 0.9]] * 4)  # identical items: SE 0, best = first max (3)
    assert cal.one_se_select(s, cal.M_GRID, cal.SEED_NSTAR)[0] == 3


def test_one_se_uses_the_paired_difference_se():
    """Two items: m=3 is better on both by 0.1 with the same item effect; paired SE of the difference is 0, so m=1 is
    not within one SE although the unpaired spread would cover it."""
    s = np.array([[0.0, 0.1, 0.1, 0.1, 0.1], [0.9, 1.0, 1.0, 1.0, 1.0]])
    assert cal.one_se_select(s, cal.M_GRID, cal.SEED_NSTAR)[0] == 3


def test_choose_variant_rules():
    assert cal.choose_variant({"rotation": (5, 1, 0), "random": (3, 0, 0), "leader": (1, 4, 0)}) == "rotation"
    assert cal.choose_variant({"rotation": (2, 1, 0), "random": (5, 0, 0), "leader": (1, 4, 0)}) == "random"
    assert cal.choose_variant({"rotation": (3, 0, 0), "random": (3, 0, 0), "leader": (0, 0, 0)}) == "rotation"
    assert cal.choose_variant({"rotation": (0, 3, 0), "random": (4, 1, 0), "leader": (4, 1, 0)}) == "random"
    assert cal.choose_variant({"rotation": (1, 1, 0), "random": (0, 2, 0), "leader": (0, 0, 0)}) == "none"


def test_auroc_ranks_equals_the_route1_rank_formula():
    rng = np.random.default_rng(7)
    for _ in range(20):
        v = rng.integers(0, 5, size=25).astype(float)
        e = rng.random(25) < 0.4
        if e.all() or not e.any():
            continue
        assert cal.auroc_ranks(v, e) == pytest.approx(ea.auroc(list(v[e]), list(v[~e])))


def test_auroc_ci_is_seeded_and_degenerate_draws_are_dropped():
    v = [0.1, 0.2, 0.3, 0.8, 0.9, 0.7, 0.4, 0.6]
    e = [False, False, False, True, True, True, False, True]
    r1 = cal.auroc_ci(v, e, cal.SEED_AUROC)
    assert r1 == cal.auroc_ci(v, e, cal.SEED_AUROC)
    assert r1["auroc"] == 1.0 and r1["ci95"] is not None and r1["n_degenerate_draws"] > 0
    assert cal.auroc_ci([0.1, 0.2], [False, False], cal.SEED_AUROC)["auroc"] is None


def test_isotonic_cuts_are_monotone_and_at_most_three_bins():
    xs = [0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9]
    es = [False, True, False, False, True, False, True, True, True, True]
    cuts = cal.isotonic_cuts(xs, es)
    assert len(cuts) <= 2
    t = cal.bins_table(xs, [bool(x) for x in es], cuts)
    acc = [b["p_correct"] for b in t]
    assert acc == sorted(acc, reverse=True)  # non-increasing accuracy in the risk signal
    assert sum(b["n"] for b in t) == len(xs)
    assert t[0]["lo"] is None and t[-1]["hi"] is None
    lo, hi = ea.wilson(t[0]["correct"], t[0]["n"])
    assert t[0]["ci95"] == [lo, hi]
    assert cal.isotonic_cuts([0.5] * 4, [True, False, True, False]) == []


def test_bin_membership_is_half_open():
    assert cal.bin_of(0.2, [0.2, 0.5]) == 1
    assert cal.bin_of(0.19, [0.2, 0.5]) == 0
    assert cal.bin_of(0.5, [0.2, 0.5]) == 2


def test_stop_rule_keeps_round_zero_at_quorum_and_stops_at_a_fixed_point(fxp: Fx):
    st = cal.read_stage(fxp.eq, "p", fxp.raw, [])
    c = cal.Cal(st, cal.load_frozen_harness(fxp.eq))
    seq = [[A, A, A, B, B], [A] * 5, [A] * 5]
    assert c.stop_round("RS", seq, 2, {}) == 0  # 3 of 5 = ceil(0.6 x 5): quorum at round 0
    seq = [[A, A, B, B, C], [A, A, B, B, C], [A] * 5]
    assert c.stop_round("RS", seq, 2, {}) == 1  # round 1 accepted nothing: fixed point
    seq = [[A, A, B, B, C], [A, A, B, C, C], [A] * 5]
    assert c.stop_round("RS", seq, 2, {}) == 2
    assert c.stop_round("RS", seq, 1, {}) == 1
    assert c.stop_round("ES", [[1, 2, 100, 400, 1000], [90, 100, 110, 400, 1000]], 2, {}) == 1


# ---------------------------------------------------------------------------------------------------------------------
# stage p end to end
# ---------------------------------------------------------------------------------------------------------------------


def test_stage_p_writes_a_valid_version_with_every_selection(fxp: Fx):
    jsonschema = pytest.importorskip("jsonschema")
    assert fxp.run("--stage", "p", "--amendment", "A7", "--reason", "pilot calibration") == 0
    p = fxp.params()
    jsonschema.Draft202012Validator(json.loads(SCHEMA_PATH.read_text())).validate(p)
    assert p["version"] == 1
    rep = fxp.report(1)
    for c in cal.CLASSES:
        assert p["classes"][c]["status"] == "not_run"  # p tests nothing
    for c in ("DS", "OE"):
        assert all(v is None for k, v in p["classes"][c].items() if k != "status")
    rs = p["classes"]["RS"]
    assert rs["member_type"] == "researcher" and rs["member_model_id"] == MODEL
    assert rs["agent_file_sha256"] == "a" * 64
    assert rs["view"] == "kcover" and rs["tau"] == 0.6 and rs["t"] == 2 and rs["reducer"] == "R0"
    assert rs["N"] == rep["nstar"]["RS"]["N"] and rs["N"] in cal.M_GRID
    assert p["classes"]["CR"]["loo_view"] == "none" and p["classes"]["CR"]["rounds"] == 0
    assert p["classes"]["CR"]["certainty"] is None
    assert rep["p7"]["variant"] == "rotation" and rs["loo_view"] == "rotation"
    assert p["classes"]["PF"]["loo_view"] == "rotation"  # checkable repair takes the pooled choice
    assert rep["p7"]["wins_losses_ties"]["rotation"][0] > 0
    assert rs["rounds"] == rep["p7"]["rounds"]["RS"]["rounds"]
    assert p["classes"]["PF"]["rounds"] == rep["repair"]["PF"]["rounds"]
    assert p["provenance"]["stages"] == ["p"] and p["provenance"]["route2"]["p"]["status"] == "agree"
    assert p["provenance"]["report"]["sha256"] == sha((fxp.out / "report.v1.json").read_bytes())
    assert p["provenance"]["pool_sha256"]["RS"] == sha((fxp.eq / "items/RS/pool.sha256").read_bytes())
    assert "A6" in p["provenance"]["amendments"]
    hist = [json.loads(x) for x in (fxp.out / "params.history.jsonl").read_text().splitlines()]
    assert hist[-1] | {} == {"version": 1, "created_utc": CREATED, "sha256": sha((fxp.out / "params.v1.json")
                                                                              .read_bytes()),
                             "prev_sha256": hist[0]["sha256"], "stages": ["p"], "amendment": "A7",
                             "reason": "pilot calibration"}


def test_stage_p_caps_usd_and_models(fxp: Fx):
    assert fxp.run("--stage", "p", "--amendment", "A7", "--reason", "r") == 0
    p, rep = fxp.params(), fxp.report(1)
    st = cal.read_stage(fxp.eq, "p", fxp.raw, [])
    calls = [c for c in st.calls if c.cls == "RS" and c.is_member and c.round == 0 and c.branch is None]
    toks = [c.ctx for c in calls]
    turns = [c.num_turns for c in calls]
    rs = p["classes"]["RS"]
    assert rs["caps"]["member_tokens"] == cal.ceil2(np.percentile(toks, 90) * 1.25)
    assert rs["caps"]["member_turns"] == math.ceil(np.percentile(turns, 90) * 1.25)
    # RS: one equivalence verifier call; no `ver` call in the fixture -> the member cap stands in
    assert rs["caps"]["run_tokens"] == rs["N"] * rs["caps"]["member_tokens"] * (1 + rs["rounds"]) \
        + rs["caps"]["member_tokens"]
    allm = [c for c in st.calls if c.cls in cal.CAL_CLASSES and c.is_member and c.round == 0 and c.branch is None]
    assert rs["usd_per_mtok"] == pytest.approx(sum(c.cost for c in allm) / sum(c.ctx for c in allm) * 1e6)
    assert rep["models"]["RS"] == [MODEL]  # the transcript model, not the background id in model_ids


def test_stage_p_n_star_one_marks_a_class_not_eligible(fx: Fx):
    """Every member right: score(m) = 1 for all m, so N* = 1 (not eligible)."""
    for item in ("RS-1", "RS-2", "RS-3"):
        for m in range(1, 10):
            fx.call("p", item, "RS", "p6", "E", f"m{m}/9", member=m, cell="p6", answer=A)
            fx.grade("p", "members/RS.jsonl", item=item, label="p6", member=m, round=0, branch=None, score=1)
    fx.collect("p")
    assert fx.run("--init") == 0
    assert fx.run("--stage", "p", "--amendment", "A7", "--reason", "r", "--no-route2") == 0
    assert fx.params()["classes"]["RS"]["N"] == 1
    assert fx.report(1)["nstar"]["RS"]["eligible"] is False


def test_stage_p_is_deterministic(tmp_path: Path):
    outs = []
    for k in (1, 2):
        f = Fx(tmp_path / f"r{k}")
        build_p(f)
        assert f.run("--init") == 0
        assert f.run("--stage", "p", "--amendment", "A7", "--reason", "r") == 0
        p = f.params()
        outs.append(json.dumps(p["classes"], sort_keys=True))
        outs.append(json.dumps({k: v for k, v in f.report(1).items() if k != "warnings"}, sort_keys=True))
    assert outs[0] == outs[2] and outs[1] == outs[3]


def test_certainty_is_chosen_on_p_by_the_lower_bound(fxp: Fx):
    st = cal.read_stage(fxp.eq, "p", fxp.raw, [])
    c = cal.Cal(st, cal.load_frozen_harness(fxp.eq))
    ch = c.choose_certainty()
    for cls in cal.BINARY:
        r = ch[cls]
        quals = [x for x in r["candidates"] if x["qualifies"]]
        if r["certainty"] is None:
            assert not quals and r["reason"]
        else:
            best = max(x["auroc"] for x in quals)
            assert r["certainty"]["auroc"] == best and r["certainty"]["ci95"][0] > 0.5
            assert 1 <= len(r["certainty"]["bins"]) <= 3
    assert "CR" not in ch


def test_p6_signals_lambda_and_kappa(fxp: Fx):
    st = cal.read_stage(fxp.eq, "p", fxp.raw, [])
    c = cal.Cal(st, cal.load_frozen_harness(fxp.eq))
    sig = {(u["item"]): u for u in c.p6_signals()["RS"]}
    assert sig["RS-4"]["signals"]["1-kappa0"] == pytest.approx(1 - 7 / 9)
    assert sig["RS-4"]["signals"]["1-lambda0"] == 0.0  # 7 vs 2: no single removal changes the winner
    assert sig["RS-3"]["error"] is True and sig["RS-4"]["error"] is False
    pf = {u["item"]: u for u in c.p6_signals()["PF"]}
    assert pf["PF-2"]["signals"]["1-lambda0"] == pytest.approx(1 / 9)  # one passer: removing it leaves none
    assert pf["PF-1"]["signals"]["check_fail0"] == pytest.approx(7 / 9)


# ---------------------------------------------------------------------------------------------------------------------
# freeze refusal
# ---------------------------------------------------------------------------------------------------------------------


def test_refuses_an_unfrozen_stage(fx: Fx):
    build_p(fx)
    (fx.eq / "runs/p/inputs/FROZEN_AT.txt").unlink()
    assert fx.run("--init") == 0
    assert fx.run("--stage", "p", "--amendment", "A7", "--reason", "r") == 2


def repin_sidecar(fx: Fx, rel: str) -> None:
    """Rewrite one sidecar line and everything that pins the sidecar (FROZEN_AT, MANIFEST) after a deliberate edit."""
    side = fx.eq / "COMPARE_eq.sha256"
    lines = [ln if not ln.endswith(f"./{rel}") else f"{sha((fx.eq / rel).read_bytes())}  ./{rel}"
             for ln in side.read_text().splitlines()]
    side.write_text("\n".join(lines) + "\n")
    fa = fx.eq / "runs/p/inputs/FROZEN_AT.txt"
    fa.write_text(fa.read_text().split("sidecar_sha256:")[0] + f"sidecar_sha256: {sha(side.read_bytes())}\n")
    inp = fx.eq / "runs/p/inputs"
    files = sorted(q for q in inp.rglob("*") if q.is_file() and q.name != "MANIFEST.sha256")
    (inp / "MANIFEST.sha256").write_text("".join(f"{sha(q.read_bytes())}  ./{q.relative_to(inp)}\n" for q in files))


@pytest.mark.parametrize("tamper", ["sidecar_file", "pool", "manifest", "ledger_appended", "no_a6", "sidecar_hash",
                                    "transcript"])
def test_refuses_a_broken_freeze(fx: Fx, tamper: str):
    build_p(fx)
    assert fx.run("--init") == 0
    if tamper == "sidecar_file":
        (fx.eq / "flags.json").write_text((fx.eq / "flags.json").read_text() + " ")
    elif tamper == "pool":
        p = fx.eq / "items/RS/manifest.jsonl"
        p.write_text("{}\n{}\n")
        repin_sidecar(fx, "items/RS/manifest.jsonl")
    elif tamper == "manifest":
        p = fx.eq / "runs/p/inputs/CONFIG.txt"
        p.write_text(p.read_text() + "x: y\n")
    elif tamper == "ledger_appended":
        p = fx.eq / "runs/p/ledger.jsonl"
        p.write_text(p.read_text() + json.dumps({"schema_version": 1, "record": "run_end"}) + "\n")
    elif tamper == "no_a6":
        p = fx.eq / "COMPARE_eq.md"
        p.write_text(p.read_text().replace("**A6", "**A5b"))
        repin_sidecar(fx, "COMPARE_eq.md")  # so only the A6 rule can refuse
    elif tamper == "sidecar_hash":
        fa = fx.eq / "runs/p/inputs/FROZEN_AT.txt"
        fa.write_text(fa.read_text().replace("sidecar_sha256: ", "sidecar_sha256: 0"))
    elif tamper == "transcript":
        p = next((fx.raw / "p/transcripts").rglob("*.jsonl"))
        p.write_text(p.read_text() + "\n")
    assert fx.run("--stage", "p", "--amendment", "A7", "--reason", "r") == 2
    assert not (fx.out / "params.v1.json").exists()


def test_route2_disagreement_beyond_one_percent_is_refused(fx: Fx):
    build_p(fx)
    st = cal.read_stage(fx.eq, "p", fx.raw, [])
    victim = next(c for c in st.calls if c.cls == "RS" and c.cell == "p6")
    tp = st.transcripts[victim.session_id]
    lines = [json.loads(x) for x in tp.read_text().splitlines()]
    lines[-1]["message"]["usage"]["cache_read_input_tokens"] += victim.ctx // 50  # +2 %
    tp.write_text("".join(json.dumps(x) + "\n" for x in lines))
    tr = fx.raw / "p/transcripts"
    (fx.eq / "runs/p/inputs/TRANSCRIPTS.sha256").write_text("".join(
        f"{sha(p.read_bytes())}  ./{p.relative_to(tr)}\n" for p in sorted(tr.rglob("*.jsonl"))))
    inp = fx.eq / "runs/p/inputs"
    files = sorted(q for q in inp.rglob("*") if q.is_file() and q.name != "MANIFEST.sha256")
    (inp / "MANIFEST.sha256").write_text("".join(f"{sha(q.read_bytes())}  ./{q.relative_to(inp)}\n" for q in files))
    assert fx.run("--init") == 0
    assert fx.run("--stage", "p", "--amendment", "A7", "--reason", "r") == 2
    assert fx.run("--stage", "p", "--amendment", "A7", "--reason", "r", "--no-route2") == 0
    assert fx.params()["provenance"]["route2"]["p"]["status"].startswith("skipped")


def test_transcript_usage_dedupes_streams_and_excludes_fork_parent(tmp_path: Path):
    parent = tmp_path / "p.jsonl"
    child = tmp_path / "c.jsonl"
    m1 = {"type": "assistant", "message": {"id": "a", "model": "M", "usage": {"input_tokens": 100}}}
    m2 = {"type": "assistant", "message": {"id": "b", "model": "M", "usage": {"input_tokens": 7,
                                                                              "cache_read_input_tokens": 3}}}
    parent.write_text(json.dumps(m1) + "\n")
    child.write_text(json.dumps(m1) + "\n" + json.dumps(m2) + "\n" + json.dumps(m2) + "\n")
    assert cal.transcript_usage(child) == (110, "M")
    assert cal.transcript_usage(child, parent) == (10, "M")


# ---------------------------------------------------------------------------------------------------------------------
# stage q
# ---------------------------------------------------------------------------------------------------------------------


def run_pq(fx: Fx, **q: Any) -> int:
    build_p(fx)
    build_q(fx, **q)
    assert fx.run("--init") == 0
    assert fx.run("--stage", "p", "--amendment", "A7", "--reason", "pilot") == 0
    return fx.run("--stage", "q", "--primary", "RS", "--amendment", "A8", "--reason", "confirmation")


def test_stage_q_validates_on_holm_and_the_ship_rule(fx: Fx):
    jsonschema = pytest.importorskip("jsonschema")
    assert run_pq(fx) == 0
    p = fx.params()
    jsonschema.Draft202012Validator(json.loads(SCHEMA_PATH.read_text())).validate(p)
    rs = p["classes"]["RS"]
    rep = fx.report(2)
    assert rs["status"] == "validated"
    assert rs["effect"]["wins"] == 12 and rs["effect"]["losses"] == 0 and rs["effect"]["ties"] == 2
    p1 = ea.sign_test_p(12, 0)
    assert rs["effect"]["p_holm"] == pytest.approx(min(1.0, 2 * p1))
    assert rs["cost_ratio"]["median"] < 2
    assert rep["tests"]["RS"]["used"] == "H1"
    for c in ("PF", "CP", "CR", "ES"):
        assert p["classes"][c]["status"] == "not_run" and p["classes"][c]["effect"] is None
    assert p["provenance"]["stages"] == ["p", "q"]
    assert set(p["provenance"]["stage_ledgers"]) == {"p", "q"}


def test_stage_q_cost_ratio_matches_route1_p1(fx: Fx):
    assert run_pq(fx) == 0
    rs = fx.params()["classes"]["RS"]
    st = cal.read_stage(fx.eq, "q", fx.raw, [])
    items = sorted(f"RS-q{i}" for i in range(1, 15))  # route 1's item order (q_paired_log2)
    logs = np.array([math.log2(st.run.units[(it, "E")].tokens / st.run.units[(it, "S*")].tokens) for it in items])
    lo, hi = ea.boot_median_ci(logs, ea.seed_of("eq|E-S*|P1"))
    assert rs["cost_ratio"]["median"] == pytest.approx(2 ** float(np.median(logs)))
    assert rs["cost_ratio"]["ci95"] == pytest.approx([2 ** lo, 2 ** hi], rel=1e-12)



def test_cost_ratio_uses_each_contrasts_p1_seed(fx: Fx, monkeypatch: pytest.MonkeyPatch):
    build_p(fx)
    build_q(fx)
    st = cal.read_stage(fx.eq, "q", fx.raw, [])
    c = cal.Cal(st, cal.load_frozen_harness(fx.eq))
    seen: list[int] = []
    real = ea.boot_median_ci

    def spy(r: np.ndarray, seed: int, b: int = ea.BOOT_B) -> tuple[float, float]:
        seen.append(seed)
        return real(r, seed, b)

    monkeypatch.setattr(cal.ea, "boot_median_ci", spy)
    c.contrast("RS", "S*")
    c.contrast("RS", "G")
    assert seen == [ea.seed_of("eq|E-S*|P1"), ea.seed_of("eq|E-G|P1")] == [943313030, 391859146]


def test_stage_q_ship_rule_fails_above_m(fx: Fx):
    assert run_pq(fx, e_tokens=60_000) == 0  # E costs ~ 6x S*: confirmed but 2^ratio > m = 2
    rs = fx.params()["classes"]["RS"]
    assert rs["status"] == "not_established"
    assert fx.report(2)["tests"]["RS"]["confirmed"]["H1"] is True


def test_stage_q_not_established_without_holm(fx: Fx):
    assert run_pq(fx, e_right=6, s_right=2, n=8) == 0
    assert fx.params()["classes"]["RS"]["status"] == "not_established"


def test_stage_q_refuted(fx: Fx):
    assert run_pq(fx, e_right=0, s_right=14) == 0  # E loses every discordant item
    assert fx.params()["classes"]["RS"]["status"] == "refuted"


def test_stage_q_h4_picks_a_confirmed_alternative(fx: Fx):
    """R3 answers A on every item (right), R0 is wrong on the E-wrong items: with enough of them H4 confirms R3."""
    assert run_pq(fx, e_right=4, s_right=0, n=14) == 0
    h4 = fx.report(2)["h4"]["RS"]
    assert h4["tests"]["R3"]["wins"] == 10 and h4["tests"]["R3"]["losses"] == 0
    assert h4["reducer"] == "R3" and fx.params()["classes"]["RS"]["reducer"] == "R3"
    assert h4["tests"]["R3"]["p_holm"] == pytest.approx(min(1.0, 3 * ea.sign_test_p(10, 0)))


def test_stage_q_keeps_the_p_signal_and_cuts(fx: Fx):
    assert run_pq(fx) == 0
    p1 = json.loads((fx.out / "params.v1.json").read_text())["classes"]["RS"]["certainty"]
    q = fx.params()["classes"]["RS"]["certainty"]
    if p1 is None:
        assert q is None
    else:
        assert q is None or (q["signal"] == p1["signal"] and q["estimated_on"] == "q"
                             and [b["hi"] for b in q["bins"]] == [b["hi"] for b in p1["bins"]])


def test_stage_q_needs_p_params_and_a_valid_primary(fx: Fx):
    build_p(fx)
    build_q(fx)
    assert fx.run("--init") == 0
    assert fx.run("--stage", "q", "--primary", "RS", "--amendment", "A8", "--reason", "r") == 2
    assert fx.run("--stage", "p", "--amendment", "A7", "--reason", "r") == 0
    assert fx.run("--stage", "q", "--primary", "RS,CP,PF", "--amendment", "A8", "--reason", "r") == 2
    assert fx.run("--stage", "q", "--primary", "", "--amendment", "A8", "--reason", "r") == 2


def test_stage_q_refuses_a_validated_class_with_a_missing_field(fx: Fx):
    fx.config["p"]["agent_sha256_researcher"] = "not-a-hash"
    fx.config["q"]["agent_sha256_researcher"] = "not-a-hash"
    assert run_pq(fx) == 2
    assert fx.params()["classes"]["RS"]["agent_file_sha256"] is None  # still version 1
    assert not (fx.out / "params.v2.json").exists()


def test_stage_q_refuses_validation_without_route2(fx: Fx):
    build_p(fx)
    build_q(fx)
    assert fx.run("--init") == 0
    assert fx.run("--stage", "p", "--amendment", "A7", "--reason", "r") == 0
    assert fx.run("--stage", "q", "--primary", "RS", "--amendment", "A8", "--reason", "r", "--no-route2") == 2


def test_stage_q_refuses_an_ineligible_primary(fx: Fx, capsys: pytest.CaptureFixture[str]):
    for item in ("RS-1", "RS-2", "RS-3"):
        for m in range(1, 10):
            fx.call("p", item, "RS", "p6", "E", f"m{m}/9", member=m, cell="p6", answer=A)
            fx.grade("p", "members/RS.jsonl", item=item, label="p6", member=m, round=0, branch=None, score=1)
    fx.collect("p")
    build_q(fx)
    assert fx.run("--init") == 0
    assert fx.run("--stage", "p", "--amendment", "A7", "--reason", "r") == 0
    assert fx.params()["classes"]["RS"]["N"] == 1
    capsys.readouterr()
    assert fx.run("--stage", "q", "--primary", "RS", "--amendment", "A8", "--reason", "r") == 2
    assert "not eligible (N* = 1" in capsys.readouterr().err


# ---------------------------------------------------------------------------------------------------------------------
# the append-only chain
# ---------------------------------------------------------------------------------------------------------------------


def test_init_writes_version_zero_equal_to_not_run_params(fx: Fx):
    assert fx.run("--init") == 0
    p = fx.params()
    assert p == cal.not_run_params(CREATED)
    assert (fx.out / "params.json.sha256").read_text() == f"{sha((fx.out / 'params.json').read_bytes())}  params.json\n"
    assert fx.run("--init") == 2


def test_the_shipped_version_zero_is_what_init_writes():
    shipped = HARNESS.parent / "calibration" / "params.v0.json"
    p = json.loads(shipped.read_text())
    assert shipped.read_text() == cal.dumps(cal.not_run_params(p["created_utc"]))


def test_chain_is_append_only_and_verified(fxp: Fx):
    assert fxp.run("--stage", "p", "--amendment", "A7", "--reason", "first") == 0
    v1 = (fxp.out / "params.v1.json").read_bytes()
    assert fxp.run("--stage", "p", "--amendment", "A9", "--reason", "rerun: a new version") == 0
    assert (fxp.out / "params.v1.json").read_bytes() == v1
    assert fxp.params()["version"] == 2
    (fxp.out / "params.v1.json").write_bytes(v1 + b" ")
    assert fxp.run("--stage", "p", "--amendment", "A10", "--reason", "x") == 2  # the chain no longer verifies
    (fxp.out / "params.v1.json").write_bytes(v1)
    (fxp.out / "params.json").write_text("{}")
    assert fxp.run("--stage", "p", "--amendment", "A10", "--reason", "x") == 2


def test_amendment_and_reason_are_required(fxp: Fx):
    assert fxp.run("--stage", "p", "--reason", "r") == 2
    assert fxp.run("--stage", "p", "--amendment", "seven", "--reason", "r") == 2
    assert fxp.run("--stage", "p", "--amendment", "A7") == 2


def test_dry_run_writes_nothing(fxp: Fx, capsys: pytest.CaptureFixture[str]):
    assert fxp.run("--stage", "p", "--amendment", "A7", "--reason", "r", "--dry-run") == 0
    assert not (fxp.out / "params.v1.json").exists()
    assert json.loads(capsys.readouterr().out)["params"]["schema"] == "eqparams.v1"


# ---------------------------------------------------------------------------------------------------------------------
# the adapter consumes the new fields
# ---------------------------------------------------------------------------------------------------------------------


def test_adapter_reads_cell_branch_parent_model_ids_and_attribution(fxp: Fx):
    st = cal.read_stage(fxp.eq, "p", fxp.raw, [])
    p7 = [c for c in st.calls if c.cell == "p7"]
    assert {c.branch for c in p7} == set(cal.VARIANTS)
    assert all(c.parent_session_id for c in p7)
    assert all(c.model_ids == tuple(sorted({MODEL, "claude-haiku-bg"})) for c in st.calls)
    att = st.attribution[("RS-1", "p3")]
    assert set(att) == {0, 1} and att[0]["lambda"] == pytest.approx(0.6)
    assert any(c.cell == "p6" and c.member == 9 for c in st.calls)


def test_adapter_skips_mediator_records_of_a_branch(fx: Fx):
    """p7's mediator records carry `branch` (cell_tag): four branches per item-arm, none of them the arm's own LOO
    attribution or result. read_stage keeps only branch-less, node-less records."""
    collect = fx.collect
    fx.collect = lambda stage: None  # type: ignore[method-assign]
    build_p(fx, p7=False)
    for v in cal.VARIANTS:  # written after the arm's own lines: without the filter they would win
        fx.mediator("p", "RS-1", "p7", "attribution", round=0, loo={}, pivotal=[], cell="p7", branch=v,
                    **{"lambda": 0.1})
        fx.mediator("p", "RS-1", "p7", "result", answer=B, reducers={"R0": B}, cell="p7", branch=v)
        fx.mediator("p", "RS-1", "p3", "attribution", round=0, loo={}, pivotal=[], cell="p7", branch=v,
                    **{"lambda": 0.2})
    collect("p")
    st = cal.read_stage(fx.eq, "p", fx.raw, [])
    assert ("RS-1", "p7") not in st.attribution and ("RS-1", "p7") not in st.results
    assert st.attribution[("RS-1", "p3")][0]["lambda"] == pytest.approx(0.6)  # the arm's own round-0 line


def test_p5_calls_are_refused(fx: Fx):
    build_p(fx)
    shutil.rmtree(fx.eq / "runs/p")
    shutil.rmtree(fx.raw / "p")
    fx.call("p", "RS-1", "RS", "p5", "S*", "s", answer=A, agent="oracle")
    fx.collect("p")
    assert fx.run("--init") == 0
    assert fx.run("--stage", "p", "--amendment", "A7", "--reason", "r") == 2


# ---------------------------------------------------------------------------------------------------------------------
# certainty (crafted units), H5, model ids
# ---------------------------------------------------------------------------------------------------------------------


def crafted_units(n: int = 40) -> list[dict[str, Any]]:
    """1-kappa0 predicts the error perfectly; 1-lambda0 weakly; m15 barely (AUROC 0.575, lower bound < 0.5)."""
    out = []
    for i in range(n):
        err = i % 2 == 0
        out.append({"item": f"x{i}", "source": "p3", "error": err,
                    "signals": {"1-kappa0": (0.6 if err else 0.2) + (i % 5) * 0.01,
                                "1-lambda0": (0.5 if err else 0.4) + ((i * 7) % 11) * 0.03,
                                "m15": float((err and i % 3 == 0) or (not err and i % 5 == 1))}})
    return out


def test_choose_certainty_takes_the_highest_qualifying_auroc(fxp: Fx, monkeypatch: pytest.MonkeyPatch):
    st = cal.read_stage(fxp.eq, "p", fxp.raw, [])
    c = cal.Cal(st, cal.load_frozen_harness(fxp.eq))
    monkeypatch.setattr(c, "e_signals", lambda: {"RS": crafted_units()})
    monkeypatch.setattr(c, "p6_signals", lambda: {})
    r = c.choose_certainty()["RS"]
    assert r["certainty"]["signal"] == "1-kappa0" and r["certainty"]["auroc"] == 1.0
    assert r["certainty"]["estimated_on"] == "p"
    assert [b["p_correct"] for b in r["certainty"]["bins"]] == [1.0, 0.0]
    kap = next(x for x in r["candidates"] if x["signal"] == "1-kappa0")
    assert kap["qualifies"] and kap["ci95"][0] > 0.5
    m15 = next(x for x in r["candidates"] if x["signal"] == "m15")
    assert not m15["qualifies"]
    us = crafted_units()
    lam = next(x for x in r["candidates"] if x["signal"] == "1-lambda0")
    assert lam["ci95"] == cal.auroc_ci([u["signals"]["1-lambda0"] for u in us], [u["error"] for u in us],
                                       3066176665)["ci95"]  # seed eq|auroc
    # without the perfect signal, a weaker one qualifies only if its lower bound clears 0.5
    units = [u | {"signals": {k: v for k, v in u["signals"].items() if k != "1-kappa0"}} for u in crafted_units()]
    monkeypatch.setattr(c, "e_signals", lambda: {"RS": units})
    r2 = c.choose_certainty()["RS"]
    lam = next(x for x in r2["candidates"] if x["signal"] == "1-lambda0")
    assert (r2["certainty"] is not None) == (lam["ci95"][0] > 0.5)
    monkeypatch.setattr(c, "e_signals", lambda: {"RS": [u | {"signals": {"m15": u["signals"]["m15"]}}
                                                        for u in crafted_units()]})
    r3 = c.choose_certainty()["RS"]
    assert r3["candidates"][0]["auroc"] == pytest.approx(0.575) and r3["candidates"][0]["ci95"][0] <= 0.5
    assert r3["certainty"] is None and "lower bound" in r3["reason"]


def test_reestimate_keeps_the_signal_and_the_p_cuts(fxp: Fx):
    st = cal.read_stage(fxp.eq, "p", fxp.raw, [])
    c = cal.Cal(st, cal.load_frozen_harness(fxp.eq))
    prev = {"signal": "1-lambda0", "auroc": 0.9, "ci95": [0.6, 1.0], "n": 40, "estimated_on": "p",
            "bins": [{"lo": None, "hi": 0.5}, {"lo": 0.5, "hi": None}]}
    us = crafted_units()
    r = c.reestimate(us, prev)["certainty"]
    assert r["signal"] == "1-lambda0" and r["estimated_on"] == "q"  # not re-chosen although 1-kappa0 is better
    assert [b["hi"] for b in r["bins"]] == [0.5, None]
    xs = [u["signals"]["1-lambda0"] for u in us]
    es = [u["error"] for u in us]
    assert r["bins"][0]["n"] == sum(x < 0.5 for x in xs)
    pairs = list(zip(xs, es, strict=True))
    assert r["auroc"] == pytest.approx(ea.auroc([x for x, e in pairs if e], [x for x, e in pairs if not e]))
    assert c.reestimate([], prev)["certainty"] is None


def test_h5_sign_test_on_reconciled_items(fx: Fx):
    build_p(fx)
    build_q(fx, e_right=8, s_right=0, n=14)
    for i in range(9, 15):  # items with a reconcile round: the none branch is right on 1, wrong on 5; E wrong on all
        fx.grade("q", "members/RS.jsonl", item=f"RS-q{i}", label="q3", member=0, round=0, branch="none",
                 score=int(i == 9))
    shutil.rmtree(fx.eq / "runs/q")
    shutil.rmtree(fx.raw / "q")
    fx.collect("q")
    assert fx.run("--init") == 0
    assert fx.run("--stage", "p", "--amendment", "A7", "--reason", "r") == 0
    assert fx.run("--stage", "q", "--primary", "RS", "--amendment", "A8", "--reason", "r") == 0
    h5 = fx.report(2)["h5"]["RS"]
    assert (h5["wins"], h5["losses"], h5["ties"]) == (0, 1, 5)
    assert h5["p"] == ea.sign_test_p(0, 1) and h5["p_holm"] == h5["p"]


def test_model_id_is_null_when_members_ran_on_two_models(fxp: Fx):
    st = cal.read_stage(fxp.eq, "p", fxp.raw, [])
    c = cal.Cal(st, cal.load_frozen_harness(fxp.eq))
    assert c.model_of("RS") == (MODEL, [MODEL])
    victim = next(x for x in st.calls if x.cls == "RS" and x.cell == "p6")
    tp = st.transcripts[victim.session_id]
    tp.write_text(tp.read_text().replace(MODEL, "claude-sonnet-other"))
    mid, all_m = c.model_of("RS")
    assert mid is None and all_m == sorted([MODEL, "claude-sonnet-other"])


def test_usd_per_mtok_is_per_model(fxp: Fx):
    st = cal.read_stage(fxp.eq, "p", fxp.raw, [])
    c = cal.Cal(st, cal.load_frozen_harness(fxp.eq))
    usd = c.usd_per_mtok()
    calls = [x for cls in cal.CAL_CLASSES for x in c.cap_calls(cls)]
    assert usd == {MODEL: pytest.approx(sum(x.cost for x in calls) / sum(x.ctx for x in calls) * 1e6)}


def test_cr_run_cap_counts_the_verifier_calls(fxp: Fx):
    st = cal.read_stage(fxp.eq, "p", fxp.raw, [])
    c = cal.Cal(st, cal.load_frozen_harness(fxp.eq))
    cp = c.caps("CR", 5, 0)
    assert cp["caps"]["run_tokens"] == 5 * cp["member_tokens"] + 5 * cp["member_tokens"]  # 5 ver calls, none seen
    assert c.caps("CR", None, 0)["caps"] is None


def test_evidence_gate_keeps_a_rejected_proposal(fxp: Fx):
    st = cal.read_stage(fxp.eq, "p", fxp.raw, [])
    c = cal.Cal(st, cal.load_frozen_harness(fxp.eq))
    unit, ms = next((u, m) for u, m in c.e_units().items() if u[0] == "RS-1")
    seq = c.branch_rounds("RS-1", unit, ms, "leader", 2)
    assert seq is not None and seq[2] == seq[1] != seq[0]  # round 2 proposals were conformity: not accepted
    rot = c.branch_rounds("RS-1", unit, ms, "rotation", 2)
    assert rot is not None and rot[1] == [A] * 5


def test_rs_equivalence_merge_is_applied(fxp: Fx):
    st = cal.read_stage(fxp.eq, "p", fxp.raw, [])
    c = cal.Cal(st, cal.load_frozen_harness(fxp.eq))
    b2 = {"label": "REFUTED", "value": "v2"}
    kb, kb2 = c.key_rs(B), c.key_rs(b2)
    assert kb != kb2
    st.equivalence[("RS-2", "p6")] = (sorted([kb, kb2]), [[0, 1]])
    mp = c.rs_mapping(("RS-2", "p6"))
    assert mp and c.rs_key(B, mp) == c.rs_key(b2, mp) == min(kb, kb2)
    assert c.rs_key(A, mp) == c.key_rs(A)
    st.equivalence[("RS-2", "p6")] = (sorted([kb, c.key_rs(C)]), [[0, 1]])  # mixes labels: refused, no merge
    assert c.rs_mapping(("RS-2", "p6")) == {}


def test_a_q_rerun_resets_classes_outside_its_primary(fx: Fx):
    assert run_pq(fx) == 0
    assert fx.params()["classes"]["RS"]["status"] == "validated"
    assert fx.run("--stage", "q", "--primary", "CP", "--amendment", "A9", "--reason", "another primary") == 0
    p = fx.params()
    assert p["version"] == 3 and p["classes"]["RS"]["status"] == "not_run" and p["classes"]["RS"]["effect"] is None
    assert p["classes"]["CP"]["status"] == "not_established"  # no q data for CP: nothing confirmed
