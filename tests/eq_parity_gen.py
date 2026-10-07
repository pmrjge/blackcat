# /// script
# requires-python = ">=3.11"
# dependencies = ["numpy==2.5.3", "jsonschema==4.26.0"]
# ///
"""Golden vectors for tests/test_eq_parity.py, computed by the experiment harness itself (zero spend: pure functions,
no model call, no network; `verify` only on a temporary fixture with a scripted executor, so nothing is executed).

Run from the repository root and commit the output (re-run after ANY change to dot-config/dot-equilibrium/harness/eq_harness.py or
eq_mediator.py: MANIFEST.json pins both files' sha256, and test_vectors_pinned_to_the_harness fails until it is re-run):
    uv run --script tests/eq_parity_gen.py            (writes tests/fixtures/eq_parity/*.json and MANIFEST.json)
Inside the Claude Code sandbox prefix `UV_CACHE_DIR=$TMPDIR/uvcache`. The output is deterministic (fixed seeds): an
unchanged harness regenerates byte-identical vectors, so `git diff tests/fixtures/eq_parity` after a re-run shows
exactly what a harness change moved.

Leave-one-out vectors (RUNTIME_EQUILIBRIUM §4): loo_exclude.json, round_loo.json (eq_mediator.round_loo against
eq_core.reduce_round's loo / lambda / pivotal; both sides break ties by the answer key, so these are exact, ties
included) and summary_exclude.json (summary(exclude=), the LOO views).

Every vector that went through a numpy tie-break (`tie_break` with >= 2 candidates, `seeded_permutation` with n >= 2)
carries `tie: true` and the candidate sets, so the parity test can demand exact equality on tie-free vectors and
"chosen in the tied set" on the others (the runtime port replaces numpy's RNG by the sha256-v1 keyed order).
"""

import dataclasses
import hashlib
import json
import random
import sys
import tempfile
from fractions import Fraction
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
HARNESS = ROOT / "dot-config" / "dot-equilibrium" / "harness"
OUT = ROOT / "tests" / "fixtures" / "eq_parity"
sys.path.insert(0, str(HARNESS))

import eq_harness as eh  # noqa: E402
import eq_mediator as med  # noqa: E402

RS_SPEC = eh.DEFAULT_FLAGS["answer_key"]["RS"]
KEYS = {"plain": eh.normalise_answer, "rs": eh.make_answer_key(RS_SPEC)}

# --- tie instrumentation -------------------------------------------------------------------------------------------

TIES: list[list[str]] = []
PERMS: list[int] = []
_tie_break, _seeded_permutation = eh.tie_break, eh.seeded_permutation


def _tb(candidates: Any, seed: int) -> str:
    c = sorted(set(candidates))
    if len(c) > 1:
        TIES.append(c)
    return _tie_break(c, seed)


def _sp(seed: int, n: int) -> list[int]:
    if n > 1:
        PERMS.append(n)
    return _seeded_permutation(seed, n)


eh.tie_break = _tb
eh.seeded_permutation = _sp


def watch() -> None:
    TIES.clear()
    PERMS.clear()


def tied() -> dict[str, Any]:
    return {"tie": bool(TIES or PERMS), "tie_sets": [list(t) for t in TIES]}


def ref(r: Any) -> Any:
    if isinstance(r, med.FindingRef):
        return dataclasses.asdict(r)
    if isinstance(r, tuple | list):
        return [ref(x) for x in r]
    return r


def frac(x: Fraction | None) -> Any:
    return None if x is None else [x.numerator, x.denominator]


# --- generators ----------------------------------------------------------------------------------------------------


def gen_seeds() -> dict[str, Any]:
    tags = ["eq|order", "eq|items", "eq|views", "eq|ties", "eq|grader", "eq|regrade", "eq|reconcile", "eq|loo",
            "eq|loo|leader", "", "x"]
    derive = [[b, k] for b in (0, 1, 20261004, eh.SEED_TIES, 2**32 - 1) for k in ("", "a", "CR-001|p3|E", "r|1|2")]
    views = [["CR-001", "m1"], ["RS-17", "n2|m3"], ["4242", "m5"], ["", ""]]
    return {"seed_for": {t: eh.seed_for(t) for t in tags},
            "derive_seed": [[b, k, eh.derive_seed(b, k)] for b, k in derive],
            "view_seed": [[i, m, eh.view_seed(i, m)] for i, m in views]}


def gen_quorum() -> list[Any]:
    out = []
    for n in range(1, 13):
        for tau in ("0.6", "2/3", "1/2", "1", "0.01"):
            out.append([n, "tau", tau, 2, eh.quorum(n, "tau", Fraction(tau), 2)])
        out.append([n, "two_thirds", "0.6", 2, eh.quorum(n, "two_thirds")])
        for t in (1, 2, 3):
            out.append([n, "fixed_t", "0.6", t, eh.quorum(n, "fixed_t", Fraction(3, 5), t)])
    return out


def gen_views() -> dict[str, Any]:
    perm = []
    for rule in ("floor", "ceil"):
        for s in range(1, 13):
            for n in range(1, 10):
                perm.append({"rule": rule, "s": s, "n": n, "orders": [eh.perm_order(s, n, i, rule) for i in range(n)],
                             "collisions": eh.perm_collisions(s, n, rule)})
    kc = []
    for s in range(1, 15):
        for pinned in ((), (0,), (1, 3), (0, 2, 4)):
            if any(k >= s for k in pinned) or s - len(pinned) < 1:
                continue
            kc.append({"s": s, "pinned": list(pinned),
                       "views": [list(map(lambda x: x if x is None else list(x), eh.kcover_order(s, i, 5, pinned)))
                                 for i in range(5)]})
    blocks = [[s, nb, eh.kcover_blocks(s, nb)] for s in range(0, 15) for nb in (1, 2, 4)]
    lens = []
    for item in ("CR-001", "RS-17", "4242", "eq|r"):
        for n in range(1, 10):
            for prefix in ("", "n1|"):
                keys = [f"{prefix}m{i}" for i in range(1, n + 1)]
                lens.append({"item": item, "keys": keys, "nlenses": 5, "out": eh.lens_assignment(item, keys, 5)})
    mv = []
    lenses = json.loads((ROOT / "dot-config" / "dot-equilibrium" / "items" / "lenses.json").read_text())
    for cls in ("PF", "CR", "RS"):
        for kind in ("lens", "perm", "kcover"):
            for n in (1, 3, 5, 7, 9):
                for s, pinned in ((0, ()), (1, ()), (2, ()), (3, ()), (4, ()), (6, ()), (6, (0, 1)), (11, (2,))):
                    for seed in (7, 123456):
                        segs = tuple(eh.Segment(f"s{k}", f"f{k}.py", None) for k in range(s))
                        item = eh.Item(str(seed), cls, False, "discrete", "p", segs, None, None, None, (),
                                       Path("."), tuple(pinned))
                        keys = [f"m{i + 1}" for i in range(n)]
                        la = eh.lens_assignment(item.id, keys, 5)
                        views = [eh.member_view(item, kind, n, i, keys[i], lenses[cls], la[keys[i]]) for i in range(n)]
                        mv.append({"cls": cls, "view": kind, "n": n, "s": s, "pinned": list(pinned), "seed": seed,
                                   "out": [{"scheme": v.kind, "order": list(v.order),
                                            "blocks": None if v.blocks is None else list(v.blocks),
                                            "lens_index": v.lens_index, "note": v.note}
                                           for v in views]})
    return {"perm": perm, "kcover": kc, "kcover_blocks": blocks, "lens_assignment": lens, "member_view": mv}


POOL_VIEW_N = (5, 9)  # the E arm's N and p6's nested N = 9 (COMPARE_eq §12 A6.3)
POOL_VIEW_FULL = 3  # per class and n, the first items carry the views in full (diagnostics); every item its digest


def pool_view_digest(scheme: str, note: str, members: list[Any]) -> str:
    """sha256 of the canonical JSON [scheme, note, [[order, blocks, lens_index] per member]] (= test_eq_parity)."""
    blob = json.dumps([scheme, note, members], sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode()).hexdigest()


def gen_pool_views() -> list[Any]:
    """The round-0 views of every non-dev item of the REAL pools of the p6 classes at N = 5 and 9, through the
    harness's own round0_views (Runner.round0_members) with DEFAULT_FLAGS' view per class and perm_shift_rule. Per
    item: the scheme and note (shared by its members) and the digest of [scheme, note, per member [order, blocks,
    lens_index]]; the first POOL_VIEW_FULL items per class and n also carry `members` in full."""
    items_dir = ROOT / "dot-config" / "dot-equilibrium" / "items"
    lenses = json.loads((items_dir / "lenses.json").read_text())
    flags = eh.DEFAULT_FLAGS
    out = []
    for cls in flags["cells"]["p6"]["classes"]:
        for n in POOL_VIEW_N:
            k = 0
            for item in eh.load_pool(items_dir, cls):
                if item.dev:
                    continue
                vs = eh.round0_views(item, flags["view"][cls], n, lenses[cls], str(flags["perm_shift_rule"]))
                assert len({(v.kind, v.note) for v in vs}) == 1
                members = [[list(v.order), None if v.blocks is None else list(v.blocks), v.lens_index] for v in vs]
                c = {"item": item.id, "cls": cls, "view": flags["view"][cls], "n": n, "s": len(item.segments),
                     "pinned": list(item.pinned_segments), "scheme": vs[0].kind, "note": vs[0].note,
                     "sha256": pool_view_digest(vs[0].kind, vs[0].note, members)}
                if k < POOL_VIEW_FULL:
                    c["members"] = members
                k += 1
                out.append(c)
    return out


SAMPLE_ANSWERS: list[Any] = [
    None, "", "  ", "Yes", " yes ", "YES\n", "No", 1, 1.0, 0, True, False, 2.5, [], [1, 2], {"b": 1, "a": 2},
    {"label": "SUPPORTED", "value": "", "rationale": "x"}, {"label": "supported", "value": "z", "rationale": "y"},
    {"label": "REFUTED", "value": "42", "rationale": "r"}, {"label": "Refuted", "value": " 42 ", "rationale": ""},
    {"label": "REFUTED", "value": "", "rationale": ""}, {"label": None, "value": None}, {"value": "only"},
    {"label": "NOT_IN_CORPUS"}, "ümlaut ẞ", {"label": ["x"]},
]


def gen_keys() -> list[Any]:
    return [{"a": a, "plain": eh.normalise_answer(a), "rs": KEYS["rs"](a)} for a in SAMPLE_ANSWERS]


NUM_VALUES: list[Any] = [None, 0, -1, 1, 2, 3, 0.5, 1e-300, 1e300, "3.5", "x", True, False, "inf", "nan", "-inf",
                         7, 10, 100, 1000, 0.001, 4.4, 9.99]


RAISES = "harness raises"


def guard(fn: Any, *args: Any) -> Any:
    """The harness's value, or RAISES where it crashes (log of an underflowed ratio, e.g. 1e-300 / 1e300)."""
    try:
        return fn(*args)
    except ValueError:
        return RAISES


def gen_numeric(rng: random.Random) -> dict[str, Any]:
    lists = []
    for _ in range(300):
        vals = [rng.choice(NUM_VALUES) for _ in range(rng.randint(0, 9))]
        n = len(vals) + rng.choice((0, 0, 1, 2))
        lists.append({"values": vals, "n": n, "median_ln": eh.median_ln(vals),
                      "kappa": guard(eh.kappa_numeric, vals, n),
                      "kappa_default": guard(eh.kappa_numeric, vals), "top": guard(eh.numeric_top, vals)})
    pairs = [[a, b, guard(eh.same_numeric, a, b)] for a in NUM_VALUES for b in NUM_VALUES]
    pos = [[v, eh.positive_number(v)] for v in NUM_VALUES]
    return {"lists": lists, "same": pairs, "positive": pos}


def gen_plurality(rng: random.Random) -> list[Any]:
    alpha = ["A", "a ", "B", "C", None, 1, {"label": "REFUTED", "value": "1", "rationale": "q"},
             {"label": "REFUTED", "value": "2", "rationale": "q"}, {"label": "SUPPORTED", "value": "", "rationale": ""}]
    out = []
    for _ in range(400):
        ans = [rng.choice(alpha) for _ in range(rng.randint(0, 9))]
        km = rng.choice(["plain", "rs"])
        seed = rng.randrange(2**32)
        watch()
        pr = eh.plurality(ans, seed, KEYS[km])
        rep = None if pr.winner is None else eh.representative(ans, pr.winner, KEYS[km])
        out.append({"answers": ans, "key": km, "seed": seed, "winner": pr.winner, "counts": pr.counts, "top": pr.top,
                    "n": pr.n, "kappa": pr.kappa, "tied": list(pr.tied), "representative": rep, **tied()})
    return out


def gen_select(rng: random.Random) -> dict[str, Any]:
    vts = []
    for _ in range(200):
        ids = rng.sample(range(1, 10), rng.randint(0, 6))
        passed = {i: rng.random() < 0.4 for i in ids}
        seed = rng.randrange(2**32)
        vts.append({"passed": [[i, p] for i, p in passed.items()], "seed": seed,
                    "out": eh.verify_then_select(passed, seed)})
    bd = []
    for _ in range(300):
        n = rng.randint(0, 6)
        rankings = [[rng.choice([*range(-1, n + 1), True, "x"]) for _ in range(rng.randint(0, n + 2))]
                    for _ in range(rng.randint(0, 3))]
        seed = rng.randrange(2**32)
        watch()
        w, scores = eh.borda(rankings, n, seed)
        bd.append({"rankings": rankings, "n": n, "seed": seed, "winner": w, "scores": scores, **tied()})
    return {"verify_then_select": vts, "borda": bd}


FILES = ["a.py", "./a.py", "b/c.py", "b//c.py", " a.py "]


def rand_findings(rng: random.Random) -> Any:
    if rng.random() < 0.1:
        return rng.choice([None, "x", {"file": "a.py"}])
    out = []
    for _ in range(rng.randint(0, 4)):
        f: Any = {"file": rng.choice(FILES), "line": rng.choice([1, 2, 3, 4, 5, 7, 9, 12, 13, "4", "x", None]),
                  "claim": rng.choice(["bug", "Bug ", "off by one"])}
        if rng.random() < 0.05:
            f = rng.choice([7, "s", {"line": 3}])
        out.append(f)
    return out


def gen_findings(rng: random.Random) -> list[Any]:
    out = []
    for _ in range(250):
        answers = [rand_findings(rng) for _ in range(rng.randint(1, 6))]
        fields = rng.choice([{"file": "file", "line": "line", "claim_class": None},
                             {"file": "file", "line": "line", "claim_class": "claim"}])
        t = rng.choice([1, 2, 3])
        findings = [f for i, a in enumerate(answers) for f in eh.parse_findings(a, i + 1, fields)]
        cl = eh.cluster_findings(findings, 3)
        singles_all = sorted(c.key for c in cl if c.support == 1 and c.support < t)
        verified = [k for k in singles_all if rng.random() < 0.5] + ["nope|x|1"]
        acc = eh.accept_findings(cl, t, verified)
        seed = rng.randrange(2**32)
        mc = rng.choice([0, 1, 2, 5])
        watch()
        singles = [c.key for c in eh.singles_for_verifier(cl, t, seed, mc)]
        out.append({"answers": answers, "fields": fields, "t": t,
                    "parsed": [[dataclasses.asdict(f) for f in eh.parse_findings(a, i + 1, fields)]
                               for i, a in enumerate(answers)],
                    "clusters": [{"key": c.key, "file": c.file, "claim_class": c.claim_class, "line_lo": c.line_lo,
                                  "line_hi": c.line_hi, "members": sorted(c.members), "support": c.support,
                                  "representative": c.representative().payload} for c in cl],
                    "verified": verified, "accepted": [c.key for c in acc], "kappa": eh.kappa_findings(cl, t),
                    "singles_all": singles_all, "max_calls": mc, "singles": singles, **tied()})
    return out


EVID = [{"kind": "quote", "ref": "doc.md", "detail": "alpha  beta"}, {"kind": "quote", "ref": "doc.md",
        "detail": "alpha beta"}, {"kind": "command", "ref": "pytest -q", "detail": "exit 0"},
        {"kind": "file_line", "ref": "a.py:3", "detail": "x = 1"}, {"kind": "test", "ref": "t", "detail": ""},
        {"ref": "noKind"}, "notamap"]


def gen_gate(rng: random.Random) -> list[Any]:
    out = []
    answers = ["A", "a", "B", None, 3, 3.0000000001, 6, {"label": "X"}]
    for _ in range(250):
        prev, new = rng.choice(answers), rng.choice(answers)
        pe = rng.sample(EVID, rng.randint(0, 3))
        ne = rng.sample(EVID, rng.randint(0, 4))
        good = {eh.evidence_key(e) for e in EVID if isinstance(e, dict) and rng.random() < 0.5}
        num = rng.random() < 0.4
        d = eh.evidence_gate(prev, pe, new, ne, lambda e, g=good: eh.evidence_key(e) in g,
                             eh.same_numeric if num else None)
        out.append({"prev": prev, "prev_ev": pe, "new": new, "new_ev": ne, "good": [list(k) for k in sorted(good)],
                    "numeric": num, "out": {"final": d.final_answer, "changed": d.changed, "accepted": d.accepted,
                                            "new_evidence": [list(k) for k in d.new_evidence],
                                            "verified": [list(k) for k in d.verified], "reason": d.reason}})
    return out


FACTS = [
    {"kind": "file_line", "ref": "a.py:3", "detail": "x  = 1"},
    {"kind": "file_line", "ref": "./a.py:3-5", "detail": "x"},
    {"kind": "file_line", "ref": "a.py", "detail": "x"}, {"kind": "quote", "ref": "doc.md:9", "detail": "Alpha beta"}, {"kind": "quote", "ref": "./d//doc.md:2", "detail": "q"},
    {"kind": "quote", "ref": "HTTPS://Example.org/x/", "detail": "q"}, {"kind": "command", "ref": "pytest -q 'a b'",
    "detail": "exit 0"}, {"kind": "command", "ref": "echo 'unterminated", "detail": ""},
    {"kind": "test", "ref": "make test", "detail": "exit code: 2 failed"}, {"kind": "counterexample", "ref": "n=3",
    "detail": "f(3)=4"}, {"kind": "weird", "ref": " a ", "detail": " b "}, {}, {"kind": "file_line", "ref": "",
    "detail": ""},
]


def gen_facts() -> dict[str, Any]:
    keys = [[f, fid, med.fact_key(f, fid)] for f in FACTS for fid in ("", "fx1")]
    refs = [[r, list(med.split_ref(r))] for r in ("a.py:3", "a.py:3-9", " b.py:12 ", "a.py", "c:d:4", ":5", "x:-1")]
    claims = [[d, list(med._claim(d))] for d in ("exit 0", "Exit code: 2 failed", "ok", "", "exit=-3; boom.",
                                                 "exit code 1 exit 2")]
    blind = ["CR-001 p3 m2/5 said X", "see .eq_deps/n1.json", "Lens: a", "m1/5 and p1 and S* and EG",
             "123e4567-e89b-12d3-a456-426614174000 here", {"answer": "m3/5"}, ["a", 1], "  many   spaces\n"]
    blinds = [[b, eh.blind_text(b)] for b in blind]
    quoted = [[s, c, med.quoted(s, c)] for s in ("abc", "line\n\"q\"", "ü", 12) for c in (0, 2, 300)]
    modes = [[m, eh.overlay_mode(m)] for m in (0o644, 0o755, 0o4755, 0o2711, 0o1777, 0o100600, 0o000)]
    safe = []
    for p in ("a/b", "./a", "/abs", "a/../b", "", "  ", "a//b", "..", "x/"):
        try:
            safe.append([p, eh._safe_rel(p)])
        except ValueError:
            safe.append([p, None])
    return {"fact_key": keys, "split_ref": refs, "claim": claims, "blind_text": blinds, "quoted": quoted,
            "overlay_mode": modes, "safe_rel": safe}


def gen_verify() -> list[Any]:
    """verify() on a temporary fixture: text facts read files; command facts use a scripted executor (no process)."""
    out = []
    with tempfile.TemporaryDirectory() as td:
        fx = Path(td) / "fx"
        (fx / "d").mkdir(parents=True)
        files = {"a.py": "line one\nx = 1\n  y  =  2\nz\n", "d/doc.md": "Alpha  beta\ngamma\n", "empty.txt": ""}
        for k, v in files.items():
            (fx / k).write_text(v)
        text_facts = [("file_line", "a.py:2", "x = 1"), ("file_line", "a.py:3", "x = 1"),
                      ("file_line", "a.py:4", "x = 1"), ("file_line", "a.py:5", "z"), ("file_line", "a.py:1", "y = 2"),
                      ("file_line", "a.py:9", "z"), ("file_line", "a.py", "z"), ("file_line", "a.py:0", "line"),
                      ("quote", "d/doc.md", "alpha beta"), ("quote", "d/doc.md:1", "Alpha beta gamma"),
                      ("quote", "missing.md", "x"), ("quote", "../x", "x"), ("quote", "d/doc.md", "   "),
                      ("file_line", "empty.txt:1", "a"), ("quote", "/etc/hosts", "localhost")]
        for kind, r, d in text_facts:
            st, method, _ = med.verify({"kind": kind, "ref": r, "detail": d}, fx)
            path, _ = med.split_ref(r)
            inside = med._inside(fx, path)
            out.append({"kind": kind, "ref": r, "detail": d,
                        "file_text": None if inside is None else inside.read_text(errors="replace"),
                        "status": st, "method": method})
        scripted = [((0, "ok"), (0, "ok")), ((1, "x"), (1, "x")), ((0, "2 failed"), (2, "2 failed")),
                    ((2, "2 failed tests"), (2, "2 failed tests")), ((0, ""), (0, ""))]
        cmd_facts = [("pytest -q", "exit 0"), ("pytest -q", ""), ("pytest -q", "exit code: 2 failed"),
                     ("pytest -q", "ok"), ("make", "exit 0"), ("pytest -q -k x", "exit 1"), ("pytest", "exit 0")]
        for r, d in cmd_facts:
            for runs in scripted:
                it = iter(runs)
                st, method, _ = med.verify({"kind": "command", "ref": r, "detail": d}, fx,
                                           public_check=["pytest", "-q"], allowed_prefixes=[["pytest", "-q", "-k"]],
                                           execute=lambda *a, it=it: next(it))
                out.append({"kind": "command", "ref": r, "detail": d, "runs": [list(x) for x in runs],
                            "public_check": ["pytest", "-q"], "prefixes": [["pytest", "-q", "-k"]],
                            "status": st, "method": method})
    return out


def rand_outs(rng: random.Random, family: str) -> tuple[list[med.MemberOut], dict[str, str], list[dict[str, Any]]]:
    n = rng.randint(1, 6)
    fkeys = [f"quote|doc|{k}" for k in range(5)] + ["file_line|a.py|3|h", "file_line|a.py|12|h", "file_line|b|None|h"]
    kinds = {k: ("file_line" if k.startswith("file_line") else "quote") for k in fkeys}
    outs = []
    for m in range(1, n + 1):
        if family == "numeric":
            a: Any = rng.choice([None, 1, 2, 3, 10, 12, 100, 0.5, -1, "x"])
        elif family == "finding_set":
            a = rand_findings(rng)
        else:
            a = rng.choice(["A", "a", "B", "C", None, {"label": "REFUTED", "value": "1"},
                            {"label": "REFUTED", "value": "2"}, {"label": "SUPPORTED"}])
        cited = tuple(rng.sample(fkeys, rng.randint(0, 4)))
        outs.append(med.MemberOut(m, a, cited, tuple(kinds[k] for k in cited), rng.choice([None, 0, 1, 2])))
    status = {k: rng.choice([med.VERIFIED, med.REFUTED, med.UNVERIFIABLE]) for k in fkeys if rng.random() < 0.8}
    changes = []
    for o in outs:
        if rng.random() < 0.3:
            changes.append({"member": o.member, "prev_answer": rng.choice([o.answer, "B", 5, None]),
                            "gate": rng.choice(["evidence", "conformity"]),
                            "new_fact_keys": rng.sample(fkeys, rng.randint(0, 2))})
    return outs, status, changes


def out_json(o: med.MemberOut) -> dict[str, Any]:
    return {"member": o.member, "answer": o.answer, "facts": list(o.facts), "fact_kinds": list(o.fact_kinds),
            "lens": o.lens}


def gen_mediator(rng: random.Random) -> list[Any]:
    out = []
    for _ in range(300):
        family = rng.choice(["discrete", "numeric", "finding_set"])
        km = rng.choice(["plain", "rs"])
        outs, status, changes = rand_outs(rng, family)
        ctx = med.Ctx(family=family, tie_seed=rng.randrange(2**32), key=KEYS[km], t=rng.choice([1, 2]), tol=3,
                      fact_kinds=frozenset(rng.sample(list(eh.EVIDENCE_KINDS), rng.randint(1, 5))))
        weights = None if rng.random() < 0.4 else {0: rng.choice([0.0, 0.5, 1.0]), 1: rng.choice([0.0, 1.0, 2.0]),
                                                   2: rng.choice([-1.0, 1.0])}
        watch()
        r0 = med.reduce_r0(outs, ctx)
        r0_tie = tied()
        watch()
        reds = med.all_reducers(outs, ctx, status, weights)
        lo = med.loo([o.member for o in outs], lambda s, outs=outs, ctx=ctx: med.reduce_r0(
            [o for o in outs if o.member in s], ctx))
        phi = med.shapley([o.member for o in outs], med.agreement_game(outs, ctx, r0))
        dec = med.decisive_facts(outs, outs, ctx, status, changes)
        cl = med.cluster(outs, ctx)
        adopted = med.normalise(r0, ctx) if family != "numeric" else "near"
        member_facts = {o.member: list(o.facts) for o in outs}
        facts = {k: med.Fact(k, "quote", f"ref {k}", f"detail {k}", s, "m", None,
                             [(o.member, 0, cl[o.member]) for o in outs if k in o.facts]) for k, s in status.items()}
        dis = med.dissent(cl, adopted, member_facts, facts)
        prov = med.provenance(facts.values())
        rest = tied()
        out.append({"family": family, "key": km, "tie_seed": ctx.tie_seed, "t": ctx.t, "tol": ctx.tol,
                    "fact_kinds": sorted(ctx.fact_kinds), "outs": [out_json(o) for o in outs], "status": status,
                    "weights": None if weights is None else [[k, v] for k, v in weights.items()],
                    "changes": changes, "r0": ref(r0), "r0_tie": r0_tie,
                    "reducers": {k: ref(v) for k, v in reds.items()}, "loo": [[k, ref(v)] for k, v in lo.items()],
                    "shapley": [[k, frac(v)] for k, v in phi.items()], "hhi": frac(med.hhi(phi)),
                    "decisive": dec, "cluster": [[k, v] for k, v in cl.items()], "adopted": adopted,
                    "dissent": dis, "provenance": prov, **rest})
    return out


def gen_summary(rng: random.Random) -> list[Any]:
    out = []
    for _ in range(250):
        family = rng.choice(["discrete", "numeric"])
        outs, status, _ = rand_outs(rng, family)
        ctx = med.Ctx(family=family, key=KEYS["plain"])
        cl = med.cluster(outs, ctx)
        answers = {o.member: o.answer for o in outs}
        member_facts = {o.member: list(o.facts) for o in outs}
        facts = {k: med.Fact(k, rng.choice(["quote", "file_line", "odd"]), f"ref\n{k}", f"det \"{k}\"", s, "m", None)
                 for k, s in status.items()}
        seed = rng.randrange(2**32)
        watch()
        text = med.summary(answers, cl, member_facts, facts, seed, ctx)
        nclusters = len({c for c in cl.values() if c is not None})
        max_ver = max([sum(1 for f in med.cluster_facts(c, cl, member_facts, facts) if f.status == med.VERIFIED)
                       for c in {c for c in cl.values() if c is not None}] or [0])
        out.append({"family": family, "answers": [[k, v] for k, v in answers.items()],
                    "member_facts": [[k, v] for k, v in member_facts.items()],
                    "facts": {k: {"kind": f.kind, "ref": f.ref, "detail": f.detail, "status": f.status}
                              for k, f in facts.items()},
                    "seed": seed, "clusters": nclusters, "max_verified": max_ver, "text": text, **tied()})
    return out


# --- leave-one-out (RUNTIME_EQUILIBRIUM §4): loo_exclude, round_loo, summary(exclude=) --------------------------------
# Own RNG (not the shared one above), so these vectors never shift the older ones. round_loo breaks every tie by the
# answer key on both sides (sha256(f"{seed_r}|{key}")), so its vectors are compared exactly, ties included.

LOO_CLS = {"discrete": "RS", "numeric": "ES", "finding_set": "CR", "checkable": "PF", "long_form": "DS"}


def gen_loo_exclude(rng: random.Random) -> list[Any]:
    out = []
    for variant in med.LOO_VARIANTS:
        for n in range(1, 8):
            for r in range(0, n + 2):
                for i in range(1, n + 1):
                    for seed in (0, 20261006, "run-7f3a"):
                        top = sorted(rng.sample(range(0, n + 2), rng.randint(0, min(3, n + 2))))
                        out.append([variant, i, r, n, seed, top, med.loo_exclude(variant, i, r, n, seed=seed, top=top)])
    return out


def rand_loo_answer(rng: random.Random, family: str, m: int) -> Any:
    if family == "numeric":
        # dense around 10 so that S \ i medians land on both sides of the ln 1.1 band (and on it: 11 / 10)
        return rng.choice([None, 9, 9.5, 10, 10, 10.5, 11, 11, 11.5, 12, 13, 100, 0.5, -1, "x", 1e-300, 1e300])
    if family == "finding_set":
        return rand_findings(rng)
    if family == "checkable":
        return rng.choice([None, "patch-a", "patch-b", "patch-c", f"patch-{m}"])
    if family == "long_form":
        return rng.choice([None, "doc A", "doc B", f"doc {m}", "doc a"])
    return rng.choice(["A", "a ", "B", "C", None, {"label": "REFUTED", "value": "1", "rationale": "p"},
                       {"label": "REFUTED", "value": "1", "rationale": "q"}, {"label": "REFUTED", "value": "2"},
                       {"label": "SUPPORTED", "rationale": "z"}])


def gen_round_loo(rng: random.Random) -> list[Any]:
    out = []
    for k in range(600):
        family = list(LOO_CLS)[k % len(LOO_CLS)]
        n = rng.randint(1, 7)
        answers = {m: rand_loo_answer(rng, family, m) for m in range(1, n + 1)}
        seed = rng.randrange(2**32)
        t = rng.choice([1, 2, 2, 3])
        verdicts = {m: rng.choice(["pass", "fail", "unverifiable"]) for m in answers if rng.random() < 0.8}
        rankings = [rng.sample(range(0, n + 2), rng.randint(0, n + 1)) + rng.choice([[], [True], [1]])
                    for _ in range(rng.choice([0, 1, 2, 2, 3]))]
        cand_keys = None if rng.random() < 0.6 else {m: f"sha-{rng.randint(0, 3)}" for m in answers
                                                      if rng.random() < 0.7}
        outs = [med.MemberOut(m, a) for m, a in answers.items()]
        singles: list[str] = []
        if family == "finding_set":
            fs = [f for m, a in answers.items() for f in eh.parse_findings(a, m, med.Ctx("finding_set").fields)]
            singles = [c.key for c in eh.cluster_findings(fs, 3) if c.support == 1 and rng.random() < 0.5]
        ctx = med.Ctx(family=family, key=KEYS["rs"], t=t)
        opts = med.LooOpts(verdicts=verdicts, rankings=rankings, verified_singles=tuple(singles), cand_keys=cand_keys)
        res = med.round_loo(outs, ctx, seed, opts=opts)
        out.append({"family": family, "cls": LOO_CLS[family], "answers": [[m, a] for m, a in answers.items()],
                    "seed": seed, "t": t, "verdicts": [[m, v] for m, v in verdicts.items()], "rankings": rankings,
                    "verified_singles": singles,
                    "cand_keys": None if cand_keys is None else [[m, v] for m, v in cand_keys.items()],
                    "loo": [[i, r] for i, r in res["loo"].items()], "lambda": res["lambda"],
                    "pivotal": res["pivotal"]})
    return out


def gen_summary_exclude(rng: random.Random) -> list[Any]:
    out = []
    for _ in range(250):
        family = rng.choice(["discrete", "numeric"])
        outs, status, _ = rand_outs(rng, family)
        ctx = med.Ctx(family=family, key=KEYS["plain"])
        answers = {o.member: o.answer for o in outs}
        member_facts = {o.member: list(o.facts) for o in outs}
        facts = {k: med.Fact(k, rng.choice(["quote", "file_line", "odd"]), f"ref\n{k}", f"det \"{k}\"", s, "m", None)
                 for k, s in status.items()}
        seed = rng.randrange(2**32)
        j = rng.choice([*answers, None, 99])
        recluster = rng.random() < 0.7  # as eq_core.render_view / LiveMediator.summary(exclude=) do
        cl = med.cluster([o for o in outs if o.member != j] if recluster else outs, ctx)
        watch()
        text = med.summary(answers, cl, member_facts, facts, seed, ctx, exclude=j)
        kept = {m: c for m, c in cl.items() if m != j}
        mf = {m: f for m, f in member_facts.items() if m != j}
        cs = {c for c in kept.values() if c is not None}
        max_ver = max([sum(1 for f in med.cluster_facts(c, kept, mf, facts) if f.status == med.VERIFIED)
                       for c in cs] or [0])
        out.append({"family": family, "answers": [[k, v] for k, v in answers.items()],
                    "member_facts": [[k, v] for k, v in member_facts.items()],
                    "facts": {k: {"kind": f.kind, "ref": f.ref, "detail": f.detail, "status": f.status}
                              for k, f in facts.items()},
                    "seed": seed, "exclude": j, "recluster": recluster, "clusters": len(cs), "max_verified": max_ver,
                    "text": text, **tied()})
    return out


def write(name: str, data: Any) -> str:
    OUT.mkdir(parents=True, exist_ok=True)
    blob = json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n"
    (OUT / f"{name}.json").write_text(blob)
    return hashlib.sha256(blob.encode()).hexdigest()


def main() -> int:
    rng = random.Random(20261006)
    shas = {
        "seeds": write("seeds", gen_seeds()), "quorum": write("quorum", gen_quorum()),
        "views": write("views", gen_views()), "pool_views": write("pool_views", gen_pool_views()), "keys": write("keys", gen_keys()),
        "numeric": write("numeric", gen_numeric(rng)), "plurality": write("plurality", gen_plurality(rng)),
        "select": write("select", gen_select(rng)), "findings": write("findings", gen_findings(rng)),
        "gate": write("gate", gen_gate(rng)), "facts": write("facts", gen_facts()),
        "verify": write("verify", gen_verify()), "mediator": write("mediator", gen_mediator(rng)),
        "summary": write("summary", gen_summary(rng)),
    }
    loo_rng = random.Random(20261007)
    shas.update({"loo_exclude": write("loo_exclude", gen_loo_exclude(loo_rng)),
                 "round_loo": write("round_loo", gen_round_loo(loo_rng)),
                 "summary_exclude": write("summary_exclude", gen_summary_exclude(loo_rng))})
    src = {p: hashlib.sha256((HARNESS / p).read_bytes()).hexdigest() for p in ("eq_harness.py", "eq_mediator.py")}
    write("MANIFEST", {"generator": "tests/eq_parity_gen.py", "harness_sha256": src, "vectors_sha256": shas})
    print(json.dumps({"written": sorted(shas), "harness_sha256": src}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
