"""dot-claude/hooks/eq_core.py: views, reducers, the LOO jackknife and views, briefs, results, data files
(spec RUNTIME_EQUILIBRIUM §2.4, §4, §5, §10.3). Harness parity lives in tests/test_eq_parity.py.

EQ_CORE_PATH=<copy of eq_core.py, with eq_lenses.json and eq_schemas.json beside it> runs the suite against a mutant.
"""

import ast
import hashlib
import importlib.util
import itertools
import json
import math
import os
import random
import statistics
import subprocess
import sys
from collections import Counter
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parent.parent
HOOKS = ROOT / "dot-claude" / "hooks"
ITEMS = ROOT / "equilibrium" / "items"
CORE = Path(os.environ.get("EQ_CORE_PATH") or HOOKS / "eq_core.py")
CLASSES = ("PF", "CP", "CR", "RS", "ES", "DS", "OE")


def _load() -> Any:
    spec = importlib.util.spec_from_file_location("eq_core_test", CORE)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


ec = _load()


def rs(label: str, value: str = "", rationale: str = "r") -> dict[str, Any]:
    return {"answer": {"label": label, "value": value, "rationale": rationale}, "evidence": [], "confidence": 0.5}


def reply(answer: Any, evidence: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return {"answer": answer, "evidence": evidence or [], "confidence": 0.5}


# --- data files and import shape -----------------------------------------------------------------------------------


def test_lenses_are_a_byte_copy() -> None:
    assert (CORE.parent / "eq_lenses.json").read_bytes() == (ITEMS / "lenses.json").read_bytes()
    lenses = ec.load_lenses()
    assert set(lenses) == set(CLASSES) and all(len(v) == 5 for v in lenses.values())


def test_schemas_match_their_sources() -> None:
    data = json.loads((CORE.parent / "eq_schemas.json").read_text())
    assert set(data["sources"]) == set(data["schemas"]) == set(CLASSES)
    for k in CLASSES:
        raw = (ITEMS / k / "schema.json").read_bytes()
        assert data["sources"][k] == hashlib.sha256(raw).hexdigest(), k
        assert data["schemas"][k] == json.loads(raw), k
    assert ec.load_schemas() == data["schemas"]


def _keywords(s: Any, out: set[str]) -> set[str]:
    if isinstance(s, dict):
        out |= set(s)
        for k in ("items", "additionalProperties"):
            if isinstance(s.get(k), dict):
                _keywords(s[k], out)
        for sub in s.get("properties", {}).values():
            _keywords(sub, out)
    return out


def test_validator_covers_every_schema_keyword() -> None:
    used: set[str] = set()
    for s in ec.load_schemas().values():
        _keywords(s, used)
    assert used <= ec.SUPPORTED_KEYWORDS, used - ec.SUPPORTED_KEYWORDS
    assert ec.validate({"type": "string", "pattern": "x"}, "x") != []  # unknown keyword: fail closed


def test_stdlib_only_and_loads_by_path_under_isolated_mode() -> None:
    tree = ast.parse(CORE.read_text())
    mods = {a.name.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    mods |= {n.module.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
    assert mods <= set(sys.stdlib_module_names), mods - set(sys.stdlib_module_names)
    code = ("import importlib.util, sys\n"
            f"s = importlib.util.spec_from_file_location('x', {str(CORE)!r})\n"
            "m = importlib.util.module_from_spec(s); s.loader.exec_module(m)\n"  # not registered in sys.modules
            "assert 'numpy' not in sys.modules and 'jsonschema' not in sys.modules\n"
            "print(m.RNG, m.SEED_LOO)\n")
    out = subprocess.run([sys.executable, "-I", "-c", code], capture_output=True, text=True, check=True, cwd="/")
    assert out.stdout.split() == ["sha256-v1", "568287631"]


# --- views ---------------------------------------------------------------------------------------------------------


def test_perm_shifts_distinct_when_segments_cover_members() -> None:
    for n in range(1, 10):
        for s in range(2, 41):
            orders = [ec.perm_order(s, n, i) for i in range(n)]
            assert all(sorted(o) == list(range(s)) for o in orders)
            shifts = [o[0] for o in orders]
            if s >= n:
                assert len(set(shifts)) == n, (n, s)
                assert not ec.perm_collisions(s, n)
            views = ec.member_views("CP", n, s, 1, "perm")
            assert [v["order"] for v in views] == orders
            assert all(v["kept"] == list(range(s)) for v in views)


def test_kcover_counts() -> None:
    for s in range(4, 30):
        for pinned in ((), (0,), (1, 2)):
            views = ec.member_views("CR", 5, s, 9, "kcover", pinned=pinned)
            assert all(v["scheme"] == "kcover" for v in views)
            seen = Counter(k for v in views for k in v["kept"])
            for k in range(s):
                assert seen[k] == (5 if k in pinned else 3), (s, pinned, k)  # 2 partial members + the full one
            assert views[4]["kept"] == list(range(s)) and views[4]["blocks"] is None
            assert all(views[i]["blocks"] == [i, (i + 1) % 4] for i in range(4))
    assert ec.member_views("CR", 6, 8, 9, "kcover")[0]["scheme"] == "perm"  # N != 5: perm, as the harness
    assert ec.member_views("CR", 5, 3, 9, "kcover")[0]["scheme"] == "perm"
    assert ec.member_views("CR", 5, 1, 9, "kcover")[0]["scheme"] == "lens"


def test_lens_assignment() -> None:
    lenses = ec.load_lenses()
    for n in range(1, 10):
        for seed in (0, 7, 2**31):
            views = ec.member_views("PF", n, 0, seed, "lens")
            idx = [v["lens_index"] for v in views]
            assert Counter(idx) == Counter(r % 5 for r in range(n))  # ranks 0..n-1 mod 5
            assert all(v["lens"] == lenses["PF"][v["lens_index"]] for v in views)
            ranked = sorted((f"m{i}" for i in range(1, n + 1)), key=lambda m: (ec.view_seed(str(seed), m), m))
            assert [views[int(m[1:]) - 1]["lens_index"] for m in ranked] == [r % 5 for r in range(n)]
    a = [v["lens_index"] for v in ec.member_views("PF", 5, 0, 1, "lens")]
    b = [v["lens_index"] for v in ec.member_views("PF", 5, 0, 2, "lens")]
    assert a != b  # the run seed decides the lens ranking


def test_render_brief_layout() -> None:
    segs = ["src/a.py", "src/b.py", {"id": "s3", "text": "inline segment"}]
    view = ec.member_views("CR", 5, segs, 3, "perm")[2]
    text = ec.render_brief("CR", run="0a1b2c3d", member=3, n=5, problem="Review the module.", view=view,
                           segments=segs, workdir="/w/m3")
    lines = text.splitlines()
    assert lines[0] == "eq 0a1b2c3d m3/5"
    assert lines[1] == f"Lens: {view['lens']}"
    assert lines[2] == "Review the module."
    shown = [text.index(x) for x in ("src/a.py", "src/b.py", "inline segment")]
    assert [k for _, k in sorted(zip(shown, range(3), strict=True))] == view["order"]  # listed in the view's order
    assert view["order"] != [0, 1, 2]  # member 3 of 5 over 3 segments is rotated
    assert json.dumps(ec.load_schemas()["CR"], sort_keys=True, separators=(",", ":")) in text
    assert "Integrator: the equilibrium leader. Do not commit, merge, stash, rebase" in text
    assert "/w/m3" in text and "no code fence" in text
    with pytest.raises(ValueError):
        ec.render_brief("CR", run="x", member=6, n=5, problem="p", view=view)


# --- reply parsing -------------------------------------------------------------------------------------------------


def test_parse_member_reply_whole_reply_only() -> None:
    sch = ec.load_schemas()["RS"]
    obj = rs("SUPPORTED")
    text = json.dumps(obj)
    assert ec.parse_member_reply(text, sch) == (obj, [])
    assert ec.parse_member_reply("\n " + text + "\n", sch) == (obj, [])
    for bad in ("```json\n" + text + "\n```", "Here it is: " + text, text + " done", "[1]", "", "{",
                text.replace("0.5", "NaN"), text.replace("0.5", "Infinity"), None, "[" * 100000):
        got, errs = ec.parse_member_reply(bad, sch)
        assert got is None and errs, bad if bad is None else bad[:40]
    got, errs = ec.parse_member_reply(json.dumps({**obj, "extra": 1}), sch)
    assert got is None and any("extra" in e for e in errs)


# --- reducers: invariance ------------------------------------------------------------------------------------------


def rand_round(cls: str, rng: random.Random, n: int) -> tuple[dict[int, Any], dict[str, Any]]:
    kind = ec.KIND[cls]
    answers: dict[int, Any] = {}
    for m in range(1, n + 1):
        if rng.random() < 0.15:
            answers[m] = None
        elif kind == "discrete":
            answers[m] = rs(rng.choice(["SUPPORTED", "REFUTED", "NOT_IN_CORPUS"]), rng.choice(["", "1", "2"]),
                            rng.choice(["a", "b"]))
        elif kind == "numeric":
            answers[m] = reply(rng.choice([1, 2, 3, 5, 8, 100, 0.25]))
        elif kind == "finding_set":
            answers[m] = reply([{"file": rng.choice(["a.py", "b.py"]), "line": rng.randint(1, 12), "claim": "c"}
                                for _ in range(rng.randint(0, 3))])
        else:
            answers[m] = reply(rng.choice(["alpha", "beta", "gamma", "delta"]) + rng.choice(["", " x"]))
    extra: dict[str, Any] = {}
    if kind == "checkable":
        extra["verdicts"] = {m: rng.choice(["pass", "fail", "unverifiable"]) for m in answers}
    if kind == "long_form":
        cands = [m for m, a in answers.items() if a is not None]
        extra["rankings"] = [rng.sample(cands, len(cands)) for _ in range(2)]
    return answers, extra


def permute(answers: dict[int, Any], extra: dict[str, Any], pi: dict[int, int]) -> tuple[dict[int, Any], dict]:
    pa = {pi[m]: a for m, a in answers.items()}
    pa = dict(random.Random(len(pa)).sample(list(pa.items()), len(pa)))  # insertion order shuffled too
    pe: dict[str, Any] = {}
    if "verdicts" in extra:
        pe["verdicts"] = {pi[m]: v for m, v in extra["verdicts"].items()}
    if "rankings" in extra:
        pe["rankings"] = [[pi[m] for m in r] for r in extra["rankings"]]
    return pa, pe


@pytest.mark.parametrize("cls", CLASSES)
def test_every_reducer_invariant_under_member_permutation(cls: str) -> None:
    rng = random.Random(f"perm-{cls}")
    for _ in range(150):
        n = rng.randint(1, 9)
        answers, extra = rand_round(cls, rng, n)
        perm = rng.sample(range(1, n + 1), n)
        pi = {m: perm[m - 1] for m in range(1, n + 1)}
        seed = rng.randrange(2**32)
        a = ec.reduce_round(cls, answers, seed=seed, **extra)
        pa, pe = permute(answers, extra, pi)
        b = ec.reduce_round(cls, pa, seed=seed, **pe)
        for k in ("answer", "partial", "kappa", "lambda", "histogram", "tied", "top", "quorum", "stop"):
            assert a.get(k) == b.get(k), (cls, k, answers, pi)
        assert sorted(pi[m] for m in a["pivotal"]) == sorted(b["pivotal"])
        assert {pi[m]: c for m, c in a["clusters"].items()} == b["clusters"]
        assert {pi[m]: v["stable"] for m, v in a["loo"].items()} == {m: v["stable"] for m, v in b["loo"].items()}
        if a["selected"] is not None:
            # the selected candidate's identity (its answer) is invariant; its label follows the permutation when
            # candidate answers are distinct
            assert b["selected"] is not None and answers[a["selected"]]["answer"] == pa[b["selected"]]["answer"]


# --- reducers: LOO definitions (spec §4.1) -------------------------------------------------------------------------


def test_loo_discrete() -> None:
    labels = ["SUPPORTED", "SUPPORTED", "SUPPORTED", "REFUTED", "NOT_IN_CORPUS"]
    r = ec.reduce_round("RS", {i + 1: rs(x) for i, x in enumerate(labels)}, seed=5)
    assert r["answer"]["label"] == "SUPPORTED" and r["kappa"] == 0.6 and r["stop"] is True
    assert r["lambda"] == 1.0 and r["pivotal"] == []
    labels = ["SUPPORTED", "SUPPORTED", "REFUTED", "REFUTED", "NOT_IN_CORPUS"]
    for seed in range(20):
        r = ec.reduce_round("RS", {i + 1: rs(x) for i, x in enumerate(labels)}, seed=seed)
        win = r["answer"]["label"]
        winners = [i + 1 for i, x in enumerate(labels) if x == win]
        assert r["pivotal"] == winners  # removing a winner breaks the tie the other way
        assert r["lambda"] == 1 - len(winners) / 5
        assert r["loo"][5]["answer"]["label"] == win  # an untied member's removal keeps the tie's winner
        assert r["kappa_label"] == "agreement, not probability" and r["rng"] == "sha256-v1"


def _oracle_median(vals: list[float]) -> float | None:
    vs = [v for v in vals if v is not None]
    return None if not vs else math.exp(statistics.median(math.log(v) for v in vs))


def test_loo_numeric_band() -> None:
    rng = random.Random(3)
    for _ in range(300):
        vals = [rng.choice([None, 1, 1.05, 2, 4, 8, 16, 100]) for _ in range(rng.randint(1, 8))]
        ans = {i + 1: reply(v) for i, v in enumerate(vals)}
        r = ec.reduce_round("ES", ans, seed=1)
        full = _oracle_median(vals)
        assert (r["answer"] is None and full is None) or math.isclose(r["answer"], full, rel_tol=1e-12)
        stable = 0
        for i in range(len(vals)):
            sub = _oracle_median(vals[:i] + vals[i + 1:])
            same = (sub is None and full is None) or (
                sub is not None and full is not None and abs(math.log(sub / full)) <= math.log(1.1) + 1e-12)
            stable += same
            assert r["loo"][i + 1]["stable"] == same and ((i + 1) in r["pivotal"]) == (not same)
        assert math.isclose(r["lambda"], stable / len(vals))
    # 1e-300 vs 1e300: the harness's log(v / med) underflows and raises; the port stays total
    r = ec.reduce_round("ES", {1: reply(1e-300), 2: reply(1e300), 3: reply(1e300)}, seed=1)
    assert r["answer"] == 1e300 and r["kappa"] == pytest.approx(2 / 3)


def test_loo_checkable() -> None:
    ans = {i: reply(f"fix {i}") for i in range(1, 6)}
    one = ec.reduce_round("CP", ans, seed=3, verdicts={1: "fail", 2: "pass", 3: "fail", 4: "unverifiable"})
    assert one["selected"] == 2 and one["answer"] == "fix 2" and one["lambda"] == 0.8 and one["pivotal"] == [2]
    two = ec.reduce_round("CP", ans, seed=3, verdicts={2: "pass", 4: "pass"})
    assert two["selected"] in (2, 4) and two["lambda"] == 1.0 and two["pivotal"] == [two["selected"]]
    other = 6 - two["selected"]
    assert two["loo"][two["selected"]]["selected"] == other
    none = ec.reduce_round("CP", ans, seed=3, verdicts={1: "fail"})
    assert none["partial"] is True and none["answer"] is None and none["lambda"] == 0.0 and none["pivotal"] == []
    # an abstainer is never a candidate even with a "pass" verdict
    r = ec.reduce_round("PF", {1: None, 2: reply("x")}, seed=1, verdicts={1: "pass", 2: "fail"})
    assert r["selected"] is None


def test_loo_finding_set() -> None:
    a = {"file": "a.py", "line": 10, "claim": "bug"}
    b = {"file": "b.py", "line": 20, "claim": "leak"}
    ans = {1: reply([a]), 2: reply([dict(a, line=11)]), 3: reply([a]), 4: reply([b]), 5: reply([dict(b, line=22)])}
    r = ec.reduce_round("CR", ans, seed=1, t=2)
    assert sorted(f["file"] for f in r["answer"]) == ["a.py", "b.py"]
    assert r["lambda"] == 0.6 and r["pivotal"] == [4, 5]
    stab = {c["key"]: c["stable"] for c in r["finding_clusters"] if c["accepted"]}
    assert stab == {"a.py||10": True, "b.py||20": False}  # stable iff support - 1 >= t
    single = ec.reduce_round("CR", {1: reply([a]), 2: reply([])}, seed=1, t=2, verified_singles=["a.py||10"])
    assert single["answer"] == [a] and single["pivotal"] == [1]
    assert ec.reduce_round("CR", {1: None, 2: None}, seed=1)["partial"] is True


def test_loo_long_form() -> None:
    ans = {1: reply("A text"), 2: reply("B text"), 3: reply("C text"), 4: None}
    rankings = [[1, 2, 3], [1, 3, 2]]
    r = ec.reduce_round("DS", ans, seed=1, rankings=rankings)
    assert r["selected"] == 1 and r["answer"] == "A text" and r["scores"] == {1: 4, 2: 1, 3: 1}
    assert r["pivotal"] == [1] and r["lambda"] == 0.75  # Borda over the stored rankings without i
    assert r["loo"][1]["selected"] in (2, 3) and r["loo"][4]["selected"] == 1


def test_removing_a_member_never_reorders_remaining_tied_answers() -> None:
    rng = random.Random(11)
    for _ in range(400):
        keys = [f"k{j}" for j in range(rng.randint(2, 7))]
        seed = rng.randrange(2**32)
        w = ec.tie_break(keys, seed)
        rest = [k for k in keys if k != w]
        sub = [w, *rng.sample(rest, rng.randint(1, len(rest)))]
        assert ec.tie_break(sub, seed) == w
    # within reduce_round: A A B B C D (tie A/B): removing C or D keeps the tie's winner, for every seed
    labels = ["A", "A", "B", "B", "C", "D"]
    for seed in range(200):
        r = ec.reduce_round("RS", {i + 1: rs("REFUTED", x) for i, x in enumerate(labels)}, seed=seed)
        assert r["loo"][5]["answer"] == r["answer"] and r["loo"][6]["answer"] == r["answer"]
    # verify-then-select: removing a non-selected passer never changes the selection
    for seed in range(200):
        ans = {i: reply(f"c{i}") for i in range(1, 7)}
        r = ec.reduce_round("CP", ans, seed=seed, verdicts=dict.fromkeys(ans, "pass"))
        assert all(r["loo"][i]["selected"] == r["selected"] for i in ans if i != r["selected"])


def test_reduce_round_api_shape() -> None:
    r = ec.reduce_round("RS", {"1": rs("SUPPORTED"), "2": None}, seed=1)
    for k in ("answer", "partial", "kappa", "clusters", "selected", "loo", "lambda", "pivotal", "rng"):
        assert k in r
    json.dumps(r)  # JSON-serialisable as is
    with pytest.raises(ValueError):
        ec.reduce_round("XX", {1: None}, seed=1)
    with pytest.raises(ValueError):
        ec.reduce_round("RS", {0: None}, seed=1)
    r = ec.reduce_round("RS", {1: rs("SUPPORTED"), 2: rs("REFUTED", "1")}, seed=1,
                        equivalence={'{"label": "refuted", "value": "1"}': '{"label": "supported"}'})
    assert r["kappa"] == 1.0  # the verifier's partition merged the two keys
    facts = {ec.fact_key({"kind": "quote", "ref": "d", "detail": "q"}): {"status": "refuted"}}
    cited = [{"kind": "quote", "ref": "d", "detail": "q"}]
    ans = {1: reply({"label": "SUPPORTED", "value": "", "rationale": ""}, cited),
           2: rs("REFUTED", "2"), 3: rs("REFUTED", "2")}
    r = ec.reduce_round("RS", ans, seed=1, facts=facts)
    assert set(r["counterfactual"]) == {"R0", "R1", "R2", "R3", "ENS"}


# --- LOO views (spec §4.2) -----------------------------------------------------------------------------------------


def test_rotation_excludes_each_member_once_per_round() -> None:
    for n in range(2, 10):
        for r in range(1, n):
            ex = {i: ec.loo_exclude("rotation", i, r, n, seed=0) for i in range(1, n + 1)}
            assert all(ex[i] == (i - 1 + r) % n + 1 for i in ex)  # (i + r) mod N on 0-based positions
            assert all(ex[i] != i for i in ex)
            assert sorted(ex.values()) == list(range(1, n + 1))  # each member excluded from exactly one view
        assert ec.loo_exclude("rotation", 1, n, n, seed=0) is None  # r = N would pick i itself
    assert ec.loo_exclude("rotation", 1, 0, 5, seed=0) is None  # round 0 is blind
    assert ec.loo_exclude("rotation", 1, 1, 1, seed=0) is None
    assert ec.loo_exclude("none", 2, 1, 5, seed=0) is None
    with pytest.raises(ValueError):
        ec.loo_exclude("rotation", 0, 1, 5, seed=0)
    with pytest.raises(ValueError):
        ec.loo_exclude("bogus", 1, 1, 5, seed=0)


def test_random_variant_reproducible_and_uniform() -> None:
    n = 5
    for i in range(1, n + 1):
        picks = Counter()
        for run in range(400):
            e = ec.loo_exclude("random", i, 1, n, seed=f"run{run}")
            assert e == ec.loo_exclude("random", i, 1, n, seed=f"run{run}")
            assert e != i and 1 <= e <= n
            picks[e] += 1
        assert set(picks) == set(range(1, n + 1)) - {i}
        assert min(picks.values()) > 60  # ~100 each
    s = ec.derive_seed(ec.SEED_LOO, "R", 2, 3)
    assert s == ec.SEED_LOO ^ int(hashlib.sha256(b"R|2|3").hexdigest()[:8], 16)
    others = [1, 2, 4, 5]
    assert ec.loo_exclude("random", 3, 2, 5, seed="R") == min(
        others, key=lambda j: hashlib.sha256(f"{s}|{j}".encode()).hexdigest())


def test_leader_variant() -> None:
    seen = set()
    for run in range(60):
        top = [2, 4, 5]
        ex = {i: ec.loo_exclude("leader", i, 1, 6, seed=run, top=top) for i in range(1, 7)}
        leader = ex[1]
        assert leader in top
        seen.add(leader)
        assert all(ex[i] == leader for i in ex if i != leader)
        assert ex[leader] == ec.loo_exclude("rotation", leader, 1, 6, seed=run)
    assert seen == {2, 4, 5}  # the seed decides among the top cluster
    assert ec.loo_exclude("leader", 1, 1, 4, seed=0, top=[]) == 2  # no top cluster: rotation


def _canary_round(rng: random.Random, n: int) -> tuple[dict[int, Any], dict[str, Any]]:
    answers: dict[int, Any] = {}
    facts: dict[str, Any] = {}
    shared = {"kind": "quote", "ref": "corpus/shared.md", "detail": "SHAREDFACT words"}
    for m in range(1, n + 1):
        own = {"kind": "quote", "ref": f"corpus/only-m{m}.md", "detail": f"ONLYFACT{m}X text"}
        ev = [own] + ([shared] if rng.random() < 0.5 else [])
        answers[m] = {"answer": {"label": rng.choice(["SUPPORTED", "REFUTED", "NOT_IN_CORPUS"]),
                                 "value": f"VAL{m}Q" if rng.random() < 0.5 else "",
                                 "rationale": f"RATIONALE{m}Z because"}, "evidence": ev, "confidence": 0.5}
        for e in ev:
            facts[ec.fact_key(e)] = {**e, "status": rng.choice(["verified", "refuted", "verified"])}
    return answers, facts


def test_canary_view_never_shows_the_excluded_member() -> None:
    rng = random.Random(99)
    for _ in range(300):
        n = rng.randint(2, 9)
        answers, facts = _canary_round(rng, n)
        for i in range(1, n + 1):
            for variant in ("rotation", "random", "leader"):
                j = ec.loo_exclude(variant, i, rng.randint(1, n - 1), n, seed=rng.random(), top=[1])
                if j is None:
                    continue
                text = ec.render_view("RS", answers, facts, member=i, exclude=j, round=1, seed=rng.randrange(99))
                assert f"RATIONALE{j}Z" not in text and f"VAL{j}Q" not in text
                assert f"ONLYFACT{j}X" not in text and f"only-m{j}.md" not in text
                assert f"RATIONALE{i}Z" in text  # the member's own answer stays
                n_left = sum(int(line.rsplit(": ", 1)[1]) for line in text.splitlines()
                             if line.startswith("- ") and line.rsplit(": ", 1)[1].isdigit())
                assert n_left == n - 1  # the histogram counts every member but the excluded one


def test_canary_numeric_and_repair_views() -> None:
    rng = random.Random(5)
    for _ in range(200):
        n = rng.randint(2, 9)
        vals = rng.sample([111.111, 222.222, 333.333, 4444.44, 55555.5, 6.66666, 77.7777, 8888.88, 0.999999], n)
        answers = {m: reply(vals[m - 1]) for m in range(1, n + 1)}
        i = rng.randint(1, n)
        j = ec.loo_exclude("rotation", i, 1, n, seed=0)
        if j is None:
            continue
        text = ec.render_view("ES", answers, {}, member=i, exclude=j, round=1, seed=3)
        est = next(line for line in text.splitlines() if "Estimates (sorted):" in line)
        listed = est.split("Estimates (sorted): ", 1)[1].split(";", 1)[0].split(", ")
        assert f"{vals[j - 1]:.6g}" not in listed and len(listed) == n - 1
        outs = {m: f"FAILOUT{m}Y" for m in range(1, n + 1)}
        rep = ec.render_view("CP", {m: reply(f"fix {m}") for m in range(1, n + 1)}, None, member=i, exclude=j,
                             round=1, seed=4, check_outputs=outs)
        assert f"FAILOUT{j}Y" not in rep and f"FAILOUT{i}Y" in rep and rep.count("Candidate ") == n - 1
    with pytest.raises(ValueError):
        ec.render_view("CR", {1: reply([])}, None, member=1, exclude=None, round=1, seed=1)
    with pytest.raises(ValueError):
        ec.render_view("RS", {1: rs("SUPPORTED"), 2: rs("REFUTED")}, None, member=1, exclude=1, round=1, seed=1)


def test_view_is_a_function_of_the_other_members_only() -> None:
    """render_view(exclude=j) equals the view of a round in which j never answered: j cannot move a count, the
    numeric near/far split or a fact line."""
    rng = random.Random(21)
    for _ in range(200):
        n = rng.randint(2, 8)
        answers, facts = _canary_round(rng, n)
        i = rng.randint(1, n)
        j = ec.loo_exclude("rotation", i, rng.randint(1, n - 1), n, seed=0)
        if j is None:
            continue
        without = {m: a for m, a in answers.items() if m != j}
        mf = {m: [ec.fact_key(e) for e in a["evidence"]] for m, a in answers.items()}
        for kw in ({}, {"member_facts": mf}):
            got = ec.render_view("RS", answers, facts, member=i, exclude=j, round=1, seed=7, **kw)
            assert got == ec.render_view("RS", without, facts, member=i, exclude=None, round=1, seed=7)
    # numeric: j's outlier moved the full median (3) but must not move the view's near/far split
    vals = {1: 1, 2: 1, 3: 3, 4: 3, 5: 100}
    text = ec.render_view("ES", {m: reply(v) for m, v in vals.items()}, {}, member=1, exclude=5, round=1, seed=1)
    assert "- members within a factor 2 of the median: 4" in text


def test_summary_exclude_drops_citations_of_the_excluded_member() -> None:
    rng = random.Random(8)
    for _ in range(200):
        n = rng.randint(2, 8)
        answers, facts = _canary_round(rng, n)
        outs = ec.member_outs(answers)
        ctx = ec.Ctx("discrete", key=ec.class_key("RS"))
        cl = ec.cluster(outs, ctx)  # clusters and citations of ALL members, as the harness passes them
        mf = {o.member: list(o.facts) for o in outs}
        j = rng.randint(1, n)
        text = ec.summary({o.member: o.answer for o in outs}, cl, mf, ec._facts(facts), 3, ctx, exclude=j)
        assert f"ONLYFACT{j}X" not in text and f"RATIONALE{j}Z" not in text
        others = [m for m in range(1, n + 1) if m != j]
        assert sum(int(ln.rsplit(": ", 1)[1]) for ln in text.splitlines() if ln.startswith("- ")) == len(others)


def test_r3_cluster_tie_falls_back_to_r0() -> None:
    ctx = ec.Ctx("discrete")
    outs = [ec.MemberOut(1, "A", ("f1",), ("quote",)), ec.MemberOut(2, "B", ("f2",), ("quote",)),
            ec.MemberOut(3, "B")]
    st = {"f1": "verified", "f2": "verified"}
    assert ec.reduce_r0(outs, ctx) == "B" and ec.reduce_r3(outs, ctx, st) == "B"  # 1 verified member each: tie
    assert ec.reduce_r3(outs, ctx, {"f1": "verified"}) == "A"


def test_view_keeps_facts_an_included_member_also_cited() -> None:
    shared = {"kind": "quote", "ref": "c.md", "detail": "SHARED"}
    answers = {1: {**rs("SUPPORTED"), "evidence": [shared]}, 2: {**rs("REFUTED", "9"), "evidence": [shared]},
               3: rs("NOT_IN_CORPUS")}
    facts = {ec.fact_key(shared): {**shared, "status": "refuted"}}
    text = ec.render_view("RS", answers, facts, member=3, exclude=1, round=1, seed=2, run="abcd0123")
    assert text.startswith("eq abcd0123 r1 m3\n") and "SHARED" in text


# --- gate, result block, overlay predicates ------------------------------------------------------------------------


def test_gate_change() -> None:
    ev = {"kind": "quote", "ref": "c.md", "detail": "new fact"}
    prev = rs("SUPPORTED")
    new = {**rs("REFUTED", "3"), "evidence": [ev]}
    st = {ec.fact_key(ev): "verified"}
    d = ec.gate_change("RS", prev, new, st)
    assert d.accepted and d.final_answer == new["answer"]
    d = ec.gate_change("RS", prev, new, {})
    assert d.changed and not d.accepted and d.final_answer == prev["answer"]
    assert ec.gate_change("RS", prev, rs("SUPPORTED", "", "other words"), {}).changed is False  # same key
    assert ec.gate_change("ES", reply(2.0), reply(2.0 + 1e-12), {}).changed is False


def test_result_block() -> None:
    r0 = ec.reduce_round("RS", {1: rs("SUPPORTED"), 2: rs("SUPPORTED"), 3: rs("REFUTED", "1")}, seed=1)
    cal = {"p_correct": 0.8, "ci95": [0.7, 0.9], "n": 120, "signal": "kappa", "bin": "1.0", "params_sha256": "ab"}
    obj, line = ec.result_block(run="0a1b2c3d", cls="RS", rounds=[r0])
    assert obj["agreement"]["label"] == "agreement, not probability" and "agreement, not probability" in line
    assert obj["certainty"] is None and obj["validated"] is False and obj["status_reason"] == "no_calibration"
    assert obj["loo"] == [{"round": 0, "lambda": r0["lambda"], "pivotal": len(r0["pivotal"]), "of": 3}]
    assert obj["wall"]["w1_bash"] == "n/a"
    obj, line = ec.result_block(run="0a1b2c3d", cls="RS", rounds=[r0], validated=True, status_reason=None,
                                calibration=cal)
    assert obj["certainty"] == cal and obj["validated"] is True and "p_correct=0.8" in line
    obj, _ = ec.result_block(run="r", cls="RS", rounds=[r0], validated=True, status_reason="model_drift",
                             calibration=cal)
    assert obj["validated"] is False and obj["certainty"] is None
    for cls in ("CR", "DS", "OE"):
        rr = ec.reduce_round(cls, {1: reply([] if cls == "CR" else "t")}, seed=1, rankings=[[1]])
        obj, _ = ec.result_block(run="r", cls=cls, rounds=[rr], validated=True, status_reason=None, calibration=cal)
        assert obj["certainty"] is None and obj["certainty_reason"]
    cp = ec.reduce_round("CP", {1: reply("fix")}, seed=1, verdicts={1: "pass"})
    patch = "./.claude-work/eq/r/selected.patch"
    obj, line = ec.result_block(run="r", cls="CP", rounds=[cp], patches={"selected": patch})
    assert obj["answer"].endswith("selected.patch") and obj["wall"]["w1_bash"] == "heuristic"
    facts = {"k1": {"kind": "quote", "status": "verified"}, "k2": {"kind": "quote", "status": "unverifiable",
                                                                   "method": "url (network off)"}}
    obj, _ = ec.result_block(run="r", cls="RS", rounds=[r0], facts=facts)
    assert obj["facts"]["verified"] == 1 and obj["facts"]["unverifiable_reasons"] == {"url (network off)": 1}
    json.dumps(obj)


def test_overlay_predicates() -> None:
    assert ec.is_owned("tests/test_a.py", ["tests"]) and ec.is_owned("tests", ["tests/"])
    assert not ec.is_owned("tests2/a.py", ["tests"]) and not ec.is_owned("src/tests/a.py", ["tests"])
    base = {"pristine_regular": True, "member_regular": True, "member_inside": True, "target_regular": True,
            "owned": ["tests", "check.sh"]}
    assert ec.overlay_takes("src/a.py", **base)
    assert not ec.overlay_takes("check.sh", **base) and not ec.overlay_takes("tests/x.py", **base)
    for k in ("pristine_regular", "member_regular", "member_inside", "target_regular"):
        assert not ec.overlay_takes("src/a.py", **{**base, k: False})
    assert ec.check_owned_args(["bash", "check.sh", "sub/x.sh", ".."], {"check.sh", "sub/x.sh"}) == ["check.sh"]
    assert ec.overlay_mode(0o4755) == 0o755 and ec.overlay_mode(0o444) == 0o644


def test_keyed_orders_are_the_documented_sha256_v1() -> None:
    for seed, n in itertools.product((0, 17, 2**40), range(0, 8)):
        assert ec.seeded_permutation(seed, n) == sorted(range(n), key=lambda k: hashlib.sha256(
            f"{seed}|{k}".encode()).hexdigest())
    assert ec.tie_break(["b", "a", "c"], 9) == min("abc", key=lambda k: hashlib.sha256(f"9|{k}".encode()).hexdigest())
