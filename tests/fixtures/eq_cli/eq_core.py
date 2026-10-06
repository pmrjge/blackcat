"""A FAKE hooks/eq_core.py for tests/test_eq_cli.py: the contracts.md section 8 API, with the signatures of the
sibling build's real module (eqr-core 0b955c0) and trivial, deterministic bodies. Only what stack-eq calls."""
import hashlib
import json

SEED_BASE = 20261004


def seed_for(tag):
    return SEED_BASE ^ int(hashlib.sha256(tag.encode()).hexdigest()[:8], 16)


def derive_seed(base, *parts):
    if not parts:
        raise ValueError("derive_seed needs at least one key part")
    return int(base) ^ int(hashlib.sha256("|".join(str(p) for p in parts).encode()).hexdigest()[:8], 16)


def load_schemas(path=None):
    with open(path) as f:
        data = json.load(f)
    return data.get("schemas", data)


def validate(schema, obj, path="$"):
    return [] if isinstance(obj, dict) else ["not an object"]


def parse_member_reply(text, schema):
    try:
        obj = json.loads(text)
    except ValueError:
        return None, ["not JSON"]
    errs = validate(schema, obj)
    return (None, errs) if errs else (obj, [])


def member_views(cls, n, segments, seed, view, *, lenses=None, pinned=()):
    s = segments if isinstance(segments, int) else len(segments)
    out = []
    for i in range(1, n + 1):
        shift = ((i - 1) * s // n) % s if s else 0
        order = [(shift + p) % s for p in range(s)]
        if view == "kcover" and n == 5 and s >= 4 and i < 5:
            order = sorted(order)[: max(1, s // 2)]
        out.append({"member": i, "scheme": view, "order": order, "kept": sorted(order), "lens": None,
                    "lens_index": None, "blocks": None, "note": ""})
    return out


def render_brief(cls, *, run, member, n, problem, view, segments=(), schema=None, workdir=None):
    lines = ["eq %s m%d/%d" % (run, member, n), problem]
    if segments and view.get("order"):
        lines.append("Segments: " + ", ".join(str(segments[k]) for k in view["order"]))
    lines.append("Work only in %s" % (workdir or "the directory you were started in"))
    lines.append("Reply with one JSON object: %s" % json.dumps(schema, sort_keys=True))
    return "\n".join(lines) + "\n"


def _ans(o):
    return o.get("answer") if isinstance(o, dict) else o


def _key(a):
    return json.dumps(a, sort_keys=True)


def reduce_round(cls, answers, *, seed, tau=0.6, t=2, verdicts=None, facts=None, **_):
    live = {i: _ans(a) for i, a in answers.items() if a is not None}
    if not live:
        raise ValueError("no members")
    n = len(answers)
    if verdicts is not None:
        passers = sorted(i for i in live if verdicts.get(i) == "pass")
        sel = passers[0] if passers else None
        loo = {i: {"selected": sel if sel != i else (passers[1] if len(passers) > 1 else None)} for i in answers}
        return {"answer": live.get(sel), "partial": sel is None, "kappa": len(passers) / n, "clusters": {},
                "selected": sel, "top_members": passers, "loo": loo,
                "lambda": sum(1 for v in loo.values() if v["selected"] is not None) / n,
                "pivotal": [i for i, v in loo.items() if v["selected"] is None and sel is not None]}
    counts = {}
    for i, a in sorted(live.items()):
        counts.setdefault(_key(a), []).append(i)
    top = sorted(counts.items(), key=lambda kv: (-len(kv[1]), kv[0]))
    best_key, members = top[0]
    return {"answer": json.loads(best_key), "partial": False, "kappa": len(members) / n,
            "clusters": {str(i): k for k, ms in top for i in ms}, "selected": members[0], "top_members": members,
            "loo": {i: {"answer": json.loads(best_key)} for i in answers}, "lambda": 1.0, "pivotal": []}


def loo_exclude(variant, i, r, n, *, seed, top=()):
    if variant == "none" or n < 2 or r < 1:
        return None
    e = (i - 1 + r) % n + 1
    return None if e == i else e


def render_view(cls, answers, facts, *, member, exclude, round, seed, run=None, check_outputs=None, **_):
    lines = ["eq view round %d for m%d" % (round, member)]
    for i, a in sorted(answers.items()):
        if i == exclude:
            continue
        lines.append("%s %s" % ("you:" if i == member else "other:", _key(_ans(a))))
    return "\n".join(lines) + "\n"


def evidence_gate(*args, **kw):
    return True


def result_block(*, run, cls, rounds, validated=False, status_reason="no_calibration", validated_on=None,
                 checks=None, facts=None, dissent_rows=None, calibration=None, wall=None, cost=None,
                 params_sha256=None, patches=None, next_lines=()):
    last = rounds[-1]
    obj = {"schema": "eqresult.v1", "run": run, "class": cls, "answer": last.get("answer"),
           "validated": True, "status_reason": None,            # wrong on purpose: the executor's labels win
           "agreement": {"kappa_0": rounds[0].get("kappa"), "kappa_final": last.get("kappa")},
           "loo": [{"round": k, "lambda": r.get("lambda")} for k, r in enumerate(rounds)],
           "facts": {"verified": 0, "refuted": 0, "unverifiable": 0}, "dissent": [], "certainty": {"p_correct": 0.9},
           "wall": wall, "cost": cost, "params_sha256": params_sha256, "patches": patches, "next": list(next_lines)}
    return obj, "eq:%s %s: answer from %d round(s)" % (run, cls, len(rounds))
