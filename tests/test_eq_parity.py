"""dot-claude/hooks/eq_core.py against the experiment harness (spec RUNTIME_EQUILIBRIUM §3, §10.3).

Golden vectors: tests/fixtures/eq_parity/*.json, generated once by `uv run --script tests/eq_parity_gen.py` from
equilibrium/harness (zero spend). Exact equality on tie-free vectors; on vectors that went through numpy's RNG
(`tie: true`) the port's choice must lie in the tied set (the port uses the sha256-v1 keyed order instead).
The schema validator is checked against `jsonschema` (tools venv) on valid, mutated and random member outputs.

EQ_CORE_PATH=<copy of eq_core.py> runs the suite against a mutant (seeded-bug proofs).
"""

import dataclasses
import hashlib
import importlib.util
import json
import math
import os
import random
from fractions import Fraction
from pathlib import Path
from typing import Any

import jsonschema
import pytest

ROOT = Path(__file__).resolve().parent.parent
FIX = ROOT / "tests" / "fixtures" / "eq_parity"
HARNESS = ROOT / "equilibrium" / "harness"
ITEMS = ROOT / "equilibrium" / "items"
CLASSES = ("PF", "CP", "CR", "RS", "ES", "DS", "OE")
RAISES = "harness raises"


def _load() -> Any:
    path = Path(os.environ.get("EQ_CORE_PATH") or ROOT / "dot-claude" / "hooks" / "eq_core.py")
    spec = importlib.util.spec_from_file_location("eq_core_parity", path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


ec = _load()
RS_KEY = ec.make_answer_key(ec.ANSWER_KEY["RS"])
KEYS = {"plain": ec.normalise_answer, "rs": RS_KEY}


def vec(name: str) -> Any:
    return json.loads((FIX / f"{name}.json").read_text())


def test_vectors_pinned_to_the_harness() -> None:
    man = vec("MANIFEST")
    for name, sha in man["vectors_sha256"].items():
        assert hashlib.sha256((FIX / f"{name}.json").read_bytes()).hexdigest() == sha, name
    for f, sha in man["harness_sha256"].items():
        got = hashlib.sha256((HARNESS / f).read_bytes()).hexdigest()
        assert got == sha, f"{f} changed since the vectors were generated: re-run tests/eq_parity_gen.py"


# --- seeds, quorum, views ------------------------------------------------------------------------------------------


def test_seeds() -> None:
    v = vec("seeds")
    for tag, s in v["seed_for"].items():
        assert ec.seed_for(tag) == s
    for b, k, s in v["derive_seed"]:
        assert ec.derive_seed(b, k) == s
    for i, m, s in v["view_seed"]:
        assert ec.view_seed(i, m) == s
    assert ec.SEED_LOO == v["seed_for"]["eq|loo"] == 568287631
    assert ec.SEED_LOO_LEADER == v["seed_for"]["eq|loo|leader"] == 1446025924
    assert v["seed_for"]["eq|ties"] == ec.SEED_TIES


def test_quorum() -> None:
    for n, rule, tau, t, q in vec("quorum"):
        assert ec.quorum(n, rule, Fraction(tau), t) == q


def test_perm_and_kcover() -> None:
    v = vec("views")
    for c in v["perm"]:
        assert [ec.perm_order(c["s"], c["n"], i, c["rule"]) for i in range(c["n"])] == c["orders"]
        assert ec.perm_collisions(c["s"], c["n"], c["rule"]) == c["collisions"]
    for c in v["kcover"]:
        got = [[seen, ids] for seen, ids in (ec.kcover_order(c["s"], i, 5, c["pinned"]) for i in range(5))]
        assert got == c["views"]
    for s, nb, blocks in v["kcover_blocks"]:
        assert ec.kcover_blocks(s, nb) == blocks
    for c in v["lens_assignment"]:
        assert ec.lens_assignment(c["item"], c["keys"], c["nlenses"]) == c["out"]


def test_member_views() -> None:
    lenses = json.loads((ITEMS / "lenses.json").read_text())
    for c in vec("views")["member_view"]:
        got = ec.member_views(c["cls"], c["n"], c["s"], c["seed"], c["view"], pinned=c["pinned"])
        for g, w in zip(got, c["out"], strict=True):
            assert (g["scheme"], g["order"], g["blocks"], g["lens_index"], g["note"]) == \
                (w["scheme"], w["order"], w["blocks"], w["lens_index"], w["note"]), c
            assert g["lens"] == lenses[c["cls"]][w["lens_index"]]


# --- keys, numeric, plurality, selection ---------------------------------------------------------------------------


def test_answer_keys() -> None:
    for c in vec("keys"):
        assert ec.normalise_answer(c["a"]) == c["plain"]
        assert RS_KEY(c["a"]) == c["rs"]


def test_numeric_helpers() -> None:
    v = vec("numeric")
    for c in v["lists"]:
        assert ec.median_ln(c["values"]) == c["median_ln"]
        for got, want in ((ec.kappa_numeric(c["values"], c["n"]), c["kappa"]),
                          (ec.kappa_numeric(c["values"]), c["kappa_default"]),
                          (ec.numeric_top(c["values"]), c["top"])):
            if want == RAISES:  # the port stays total where the harness's log(v / med) underflows
                assert isinstance(got, int | float) and math.isfinite(got)
            else:
                assert got == want, c
    for a, b, want in v["same"]:
        got = ec.same_numeric(a, b)
        assert got == want if want != RAISES else got is False
    for x, want in v["positive"]:
        assert ec.positive_number(x) == want


def test_plurality() -> None:
    for c in vec("plurality"):
        pr = ec.plurality(c["answers"], c["seed"], KEYS[c["key"]])
        assert (pr.counts, pr.top, pr.n, pr.kappa, list(pr.tied)) == \
            (c["counts"], c["top"], c["n"], c["kappa"], c["tied"])
        if not c["tie"]:
            assert pr.winner == c["winner"]
            assert ec.representative(c["answers"], pr.winner, KEYS[c["key"]]) == c["representative"]
        else:
            assert pr.winner in c["tied"] and c["winner"] in c["tied"]


def test_verify_then_select() -> None:
    for c in vec("select")["verify_then_select"]:
        passed = {int(i): bool(p) for i, p in c["passed"]}
        got = ec.verify_then_select(passed, c["seed"])
        passers = [i for i, p in passed.items() if p]
        if len(passers) <= 1:
            assert got == c["out"]
        else:
            assert got in passers and c["out"] in passers


def test_borda() -> None:
    for c in vec("select")["borda"]:
        w, scores = ec.borda(c["rankings"], c["n"], c["seed"])
        assert scores == c["scores"]
        if c["n"] == 0:
            assert w is None and c["winner"] is None
            continue
        best = [i for i, s in enumerate(scores) if s == max(scores)]
        assert w in best
        if len(best) == 1:
            assert w == c["winner"]


# --- findings, gate, facts -----------------------------------------------------------------------------------------


def test_findings() -> None:
    for c in vec("findings"):
        parsed = [ec.parse_findings(a, i + 1, c["fields"]) for i, a in enumerate(c["answers"])]
        assert [[dataclasses.asdict(f) for f in p] for p in parsed] == c["parsed"]
        cl = ec.cluster_findings([f for p in parsed for f in p], 3)
        assert [{"key": x.key, "file": x.file, "claim_class": x.claim_class, "line_lo": x.line_lo,
                 "line_hi": x.line_hi, "members": sorted(x.members), "support": x.support,
                 "representative": x.representative().payload} for x in cl] == c["clusters"]
        assert [x.key for x in ec.accept_findings(cl, c["t"], c["verified"])] == c["accepted"]
        assert ec.kappa_findings(cl, c["t"]) == c["kappa"]
        singles = [x.key for x in ec.singles_for_verifier(cl, c["t"], 12345, c["max_calls"])]
        if len(c["singles_all"]) <= c["max_calls"]:
            assert sorted(singles) == sorted(c["singles"]) == c["singles_all"]
        else:
            assert len(singles) == c["max_calls"] and set(singles) <= set(c["singles_all"])


def test_evidence_gate() -> None:
    for c in vec("gate"):
        good = {tuple(k) for k in c["good"]}
        d = ec.evidence_gate(c["prev"], c["prev_ev"], c["new"], c["new_ev"], lambda e, g=good: ec.evidence_key(e) in g,
                             ec.same_numeric if c["numeric"] else None)
        assert {"final": d.final_answer, "changed": d.changed, "accepted": d.accepted,
                "new_evidence": [list(k) for k in d.new_evidence], "verified": [list(k) for k in d.verified],
                "reason": d.reason} == c["out"]


def test_fact_helpers() -> None:
    v = vec("facts")
    for f, fid, key in v["fact_key"]:
        assert ec.fact_key(f, fid) == key
    for r, want in v["split_ref"]:
        assert list(ec.split_ref(r)) == want
    for d, want in v["claim"]:
        assert list(ec.claim_of(d)) == want
    for b, want in v["blind_text"]:
        assert ec.blind_text(b) == want
    for s, cap, want in v["quoted"]:
        assert ec.quoted(s, cap) == want
    for m, want in v["overlay_mode"]:
        assert ec.overlay_mode(m) == want
    for p, want in v["safe_rel"]:
        if want is None:
            with pytest.raises(ValueError):
                ec.safe_rel(p)
        else:
            assert ec.safe_rel(p) == want


def test_verify_decisions() -> None:
    for c in vec("verify"):
        if c["kind"] in ("file_line", "quote"):
            assert list(ec.text_fact_status(c["kind"], c["ref"], c["detail"], c["file_text"])) == \
                [c["status"], c["method"]], c
        else:
            import shlex

            argv = shlex.split(c["ref"])
            if not ec.fact_command_allowed(argv, c["public_check"], c["prefixes"]):
                assert (c["status"], c["method"]) == ("unverifiable", "not allow-listed")
            else:
                assert ec.fact_runs_status(c["detail"], [tuple(r) for r in c["runs"]]) == c["status"], c


# --- mediator ------------------------------------------------------------------------------------------------------


def _outs(c: dict[str, Any]) -> list[Any]:
    return [ec.MemberOut(o["member"], o["answer"], tuple(o["facts"]), tuple(o["fact_kinds"]), o["lens"])
            for o in c["outs"]]


def _ref(r: Any) -> Any:
    if isinstance(r, ec.FindingRef):
        return dataclasses.asdict(r)
    if isinstance(r, tuple | list):
        return [_ref(x) for x in r]
    return r


def _frac(x: Fraction | None) -> Any:
    return None if x is None else [x.numerator, x.denominator]


def test_mediator() -> None:
    exact = 0
    for c in vec("mediator"):
        outs = _outs(c)
        ctx = ec.Ctx(family=c["family"], tie_seed=c["tie_seed"], key=KEYS[c["key"]], t=c["t"], tol=c["tol"],
                     fact_kinds=frozenset(c["fact_kinds"]))
        status = c["status"]
        weights = None if c["weights"] is None else {int(k): w for k, w in c["weights"]}
        cl = ec.cluster(outs, ctx)
        assert [[k, v] for k, v in cl.items()] == c["cluster"]
        r0 = ec.reduce_r0(outs, ctx)
        if not c["r0_tie"]["tie"]:
            assert _ref(r0) == c["r0"]
        else:
            assert ctx.key(r0) in c["r0_tie"]["tie_sets"][0]
        facts = {k: ec.Fact(k, "quote", f"ref {k}", f"detail {k}", s, "m", None,
                            [(o.member, 0, cl[o.member]) for o in outs if k in o.facts]) for k, s in status.items()}
        assert ec.provenance(facts.values()) == c["provenance"]
        if c["tie"] or c["r0_tie"]["tie"]:
            continue
        exact += 1
        reds = ec.all_reducers(outs, ctx, status, weights)
        assert {k: _ref(v) for k, v in reds.items()} == c["reducers"]
        lo = ec.loo([o.member for o in outs], lambda s, outs=outs, ctx=ctx: ec.reduce_r0(
            [o for o in outs if o.member in s], ctx))
        assert [[k, _ref(v)] for k, v in lo.items()] == c["loo"]
        phi = ec.shapley([o.member for o in outs], ec.agreement_game(outs, ctx, r0))
        assert [[k, _frac(v)] for k, v in phi.items()] == c["shapley"]
        assert _frac(ec.hhi(phi)) == c["hhi"]
        assert ec.decisive_facts(outs, outs, ctx, status, c["changes"]) == c["decisive"]
        adopted = ec.normalise(r0, ctx) if c["family"] != "numeric" else "near"
        assert adopted == c["adopted"]
        assert ec.dissent(cl, adopted, {o.member: list(o.facts) for o in outs}, facts) == c["dissent"]
    assert exact >= 100  # enough tie-free vectors were compared exactly


def _blocks(text: str) -> tuple[list[str], list[list[str]]]:
    head: list[str] = []
    blocks: list[list[str]] = []
    for ln in text.split("\n"):
        if ln.startswith("- "):
            blocks.append([ln])
        elif ln.startswith("  ") and blocks:
            blocks[-1].append(ln)
        else:
            head.append(ln)
    return head, sorted(sorted(b) for b in blocks)


def test_summary() -> None:
    exact = 0
    for c in vec("summary"):
        ctx = ec.Ctx(family=c["family"], key=ec.normalise_answer)
        answers = {int(k): v for k, v in c["answers"]}
        outs = [ec.MemberOut(k, v) for k, v in answers.items()]
        cl = ec.cluster(outs, ctx)
        mf = {int(k): v for k, v in c["member_facts"]}
        facts = {k: ec.Fact(k, f["kind"], f["ref"], f["detail"], f["status"]) for k, f in c["facts"].items()}
        got = ec.summary(answers, cl, mf, facts, c["seed"], ctx)
        if not c["tie"]:
            exact += 1
            assert got == c["text"]
        elif c["max_verified"] <= 2:  # only the cluster order was drawn: same blocks
            assert _blocks(got) == _blocks(c["text"])
        else:  # which 2 of > 2 verified facts were drawn differs; the rest of every block is the same

            def strip(t: str) -> tuple[list[str], list[list[str]]]:
                head, blocks = _blocks(t)
                return head, sorted(sorted(ln if "verified fact:" not in ln else "V" for ln in b) for b in blocks)

            assert strip(got) == strip(c["text"])
    assert exact >= 50


# --- schema validator vs jsonschema --------------------------------------------------------------------------------

SCHEMAS = {k: json.loads((ITEMS / k / "schema.json").read_text()) for k in CLASSES}
EV = [{"kind": "quote", "ref": "doc.md:3", "detail": "x"}]
VALID: dict[str, Any] = {
    "PF": {"answer": "import Mathlib\ntheorem t : True := trivial", "evidence": EV, "confidence": 0.9},
    "CP": {"answer": "fixed the off-by-one", "evidence": [], "confidence": 1},
    "CR": {"answer": [{"file": "a.py", "line": 3, "claim": "bug"}], "evidence": EV, "confidence": 0},
    "RS": {"answer": {"label": "REFUTED", "value": "42", "rationale": "r"}, "evidence": EV, "confidence": 0.5},
    "ES": {"answer": 1234.5, "evidence": [], "confidence": 0.2},
    "DS": {"answer": "# Design", "evidence": [], "confidence": 0.7},
    "OE": {"answer": "text", "evidence": EV, "confidence": 0.3},
}


def js_valid(schema: Any, obj: Any) -> bool:
    return jsonschema.Draft202012Validator(schema).is_valid(obj)


def mutations(obj: Any) -> list[Any]:
    """Single-step mutations of a valid object: drop / retype / extend each node."""
    out: list[Any] = []
    junk = [None, True, False, 0, 1, -1, 1.5, 3.0, 2**70, "", "x", [], {}, float("nan"), -0.0, "é" * 13000]
    if isinstance(obj, dict):
        for k in list(obj):
            d = dict(obj)
            del d[k]
            out.append(d)
            for sub in mutations(obj[k]):
                out.append({**obj, k: sub})
        out.append({**obj, "extra": 1})
    elif isinstance(obj, list):
        out += [[], [*obj, *obj], [*obj, "x"], [*obj, {}]]
        for i, x in enumerate(obj):
            for sub in mutations(x):
                out.append([*obj[:i], sub, *obj[i + 1:]])
    out += junk
    return out


def rand_instance(s: Any, rng: random.Random, depth: int = 0) -> Any:
    junk = [None, True, False, 0, 1, -1, 0.5, 1.0, 1.5, 3.0, -1e-9, 1.0000001, 2**63, "", "x", [], {}, float("nan")]
    if rng.random() < 0.12 or depth > 4:
        return rng.choice(junk)
    if "enum" in s and rng.random() < 0.8:
        return rng.choice([*s["enum"], "other", "Command", 1])
    t = s.get("type")
    if t == "object" or "properties" in s:
        obj = {k: rand_instance(sub, rng, depth + 1) for k, sub in s.get("properties", {}).items()
               if rng.random() < 0.9}
        if rng.random() < 0.08:
            obj["extra"] = rand_instance({}, rng, depth + 1)
        return obj
    if t == "array":
        return [rand_instance(s.get("items", {}), rng, depth + 1) for _ in range(rng.randint(0, 3))]
    if t == "string":
        bounds = [0, 1, 2, 5, s.get("minLength", 0), s.get("maxLength", 3), s.get("maxLength", 3) + 1]
        return rng.choice(["a", "é", "\U0001F600"]) * max(0, rng.choice(bounds))
    if t == "number":
        return rng.choice([0, 1, 0.5, -0.0, -1e-9, 1.0000001, 2, 1e308, -5, True, float("nan"), 7.25])
    if t == "integer":
        return rng.choice([1, 0, -1, 3.0, 3.5, 2**63, True, 12])
    return rng.choice(junk)


@pytest.mark.parametrize("cls", CLASSES)
def test_validator_matches_jsonschema(cls: str) -> None:
    schema = SCHEMAS[cls]
    assert js_valid(schema, VALID[cls]) and ec.validate(schema, VALID[cls]) == []
    cases = mutations(VALID[cls])
    rng = random.Random(f"eq-{cls}")
    cases += [rand_instance(schema, rng) for _ in range(3000)]
    n_valid = 0
    for obj in cases:
        want = js_valid(schema, obj)
        n_valid += want
        assert (ec.validate(schema, obj) == []) == want, (cls, obj)
    assert 0 < n_valid < len(cases)  # both outcomes exercised


@pytest.mark.parametrize("cls", CLASSES)
def test_parse_member_reply_matches_jsonschema(cls: str) -> None:
    schema = SCHEMAS[cls]
    for obj in [VALID[cls], *mutations(VALID[cls])]:
        if isinstance(obj, float) and not math.isfinite(obj):
            continue
        text = json.dumps(obj, allow_nan=True)
        got, errs = ec.parse_member_reply(text, schema)
        has_nan = "NaN" in text
        want = js_valid(schema, obj) and isinstance(obj, dict) and not has_nan
        assert (got is not None) == want, (cls, obj, errs)
        assert (errs == []) == want
