# /// script
# requires-python = ">=3.10"
# dependencies = ["numpy"]
# ///
"""Seeded generator of the CP (code patch) pool.

Frozen inputs: oracle/bases/*.py (reference modules) and oracle/tests/*.py (test
sources: the part above the HIDDEN marker is the public test file, the whole file is
the hidden suite), the operators in mutlib.py, SEED below. Everything is deterministic.

  uv run gen_cp.py --out <pool dir>      (default: this folder)

An item is accepted only if the mutant fails the public tests AND the hidden tests
(and does not time out); the reference module passes both.
"""
import argparse
import json
import os
import random
import shutil
import sys
import tempfile

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import mutlib  # noqa: E402

SEED = "eq|CP|pool|v1"
N_ITEMS = 200
N_DEV = 3
MAX_PER_MODULE = 9
ITEMS_SEED = 3725927731  # eq|items (COMPARE_eq 3)
PUBLIC_CHECK = ["uv", "run", "--no-project", "python", "-m", "unittest", "discover",
                "-s", "tests", "-t", ".", "-q"]
ALLOWED = ["Read", "Edit", "Write", "Bash", "Glob", "Grep"]
PROMPT = (
    "The working directory holds a small Python project: one module and a tests/ directory. "
    "The module has a defect, so some of its documented behaviour is wrong; the public tests "
    "currently fail (run them with `uv run --no-project python -m unittest discover -s tests -t . -q`). "
    "Fix the defect in the module so that it behaves as its docstrings state. Do not edit files under tests/. "
    "Make the smallest correct change. A larger hidden test suite that checks the documented behaviour more "
    "broadly will be run on your patched copy. Leave the patched files in the working directory and put a "
    "one-sentence description of the fix in `answer`."
)
SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "title": "CP arm output",
    "type": "object",
    "required": ["answer", "evidence", "confidence"],
    "additionalProperties": False,
    "properties": {
        "answer": {"type": "string", "description": "one-sentence description of the fix; the patch itself is the edited working directory"},
        "evidence": {"type": "array", "items": {
            "type": "object", "required": ["kind", "ref", "detail"], "additionalProperties": False,
            "properties": {"kind": {"enum": ["command", "file_line", "quote", "counterexample", "test"]},
                           "ref": {"type": "string"}, "detail": {"type": "string"}}}},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
    },
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=HERE)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--hash-only", action="store_true", help="only rewrite pool.sha256")
    args = ap.parse_args()
    out = os.path.abspath(args.out)
    if args.hash_only:
        mutlib.write_pool_hashes(out, "CP")
        return
    src = os.path.join(HERE, "oracle")
    names = sorted(f[:-3] for f in os.listdir(os.path.join(src, "bases")) if f.endswith(".py"))
    bases = {n: mutlib.Base(src, n) for n in names}

    # 1. sanity: reference passes everything
    pools = {}
    for n in names:
        b = bases[n]
        ev = mutlib.eval_module_sites(b, args.workers)
        seen = set()
        pool = []
        for r in ev:
            if r["hid"]["timeout"] or r["pub"]["timeout"]:
                continue
            if r["hid"]["rc"] == 1 and r["pub"]["rc"] == 1:
                key = (r["line"], r["col"], r["new"])
                if key not in seen:
                    seen.add(key)
                    pool.append({k: r[k] for k in ("kind", "line", "col", "end", "old", "new", "func")})
        pools[n] = pool

    # 2. seeded selection: round robin over shuffled modules
    rng = random.Random(SEED)
    for n in names:
        rng.shuffle(pools[n])
    order = list(names)
    rng.shuffle(order)
    picks = []
    cursor = {n: 0 for n in names}
    while len(picks) < N_ITEMS + N_DEV:
        progressed = False
        for n in order:
            if len(picks) >= N_ITEMS + N_DEV:
                break
            if cursor[n] < min(len(pools[n]), MAX_PER_MODULE):
                picks.append((n, pools[n][cursor[n]]))
                cursor[n] += 1
                progressed = True
        if not progressed:
            break
    if len(picks) < N_ITEMS + N_DEV:
        print("WARNING: only %d items available" % len(picks), file=sys.stderr)
    # dev items: first N_DEV picks (distinct modules by construction); rest shuffled
    dev, rest = picks[:N_DEV], picks[N_DEV:]
    rng.shuffle(rest)

    # 3. write the pool
    shutil.rmtree(os.path.join(out, "fixtures"), ignore_errors=True)
    os.makedirs(os.path.join(out, "fixtures"), exist_ok=True)
    os.makedirs(os.path.join(out, "oracle", "hidden"), exist_ok=True)
    if out != HERE:
        for sub in ("bases", "tests"):
            shutil.rmtree(os.path.join(out, "oracle", sub), ignore_errors=True)
            shutil.copytree(os.path.join(src, sub), os.path.join(out, "oracle", sub))
    nrng = np.random.default_rng(ITEMS_SEED)
    items = {}
    manifest = []
    for idx, (n, site) in enumerate(dev + rest):
        iid = "CP-DEV%d" % (idx + 1) if idx < N_DEV else "CP-%04d" % (idx - N_DEV + 1)
        b = bases[n]
        msrc = mutlib.apply(b.src, [site])
        fx = os.path.join(out, "fixtures", iid)
        mutlib.write_files(fx, {n + ".py": msrc, "tests/__init__.py": "",
                                "tests/test_%s.py" % n: b.public_test})
        hid_path = os.path.join(out, "oracle", "hidden", n + ".py")
        with open(hid_path, "w") as f:
            f.write(b.hidden_test)
        items[iid] = {"module": n, "mutation": dict(site, claim=mutlib.describe(site)),
                      "hidden_count": None}
        segs = [{"id": "src", "path": n + ".py"}, {"id": "tests", "path": "tests/test_%s.py" % n}]
        perm = [int(i) for i in nrng.permutation(len(segs))]
        segs = [segs[i] for i in perm]
        manifest.append({
            "id": iid, "class": "CP", "dev": iid.startswith("CP-DEV"), "answer_kind": "checkable",
            "prompt": PROMPT, "segments": segs, "decisive_segment": [s["id"] for s in segs].index("src"),
            "fixture": "fixtures/" + iid, "public_check": PUBLIC_CHECK, "allowed_tools": ALLOWED})
    # hidden counts from the reference run
    for n in names:
        with tempfile.TemporaryDirectory() as d:
            mutlib.write_files(d, {n + ".py": bases[n].src, "t_hid.py": bases[n].hidden_test})
            r = mutlib.run_unittest(d, "t_hid")
            assert r["rc"] == 0, (n, r["tail"])
            for it in items.values():
                if it["module"] == n:
                    it["hidden_count"] = r["ran"]
    with open(os.path.join(out, "oracle", "items.json"), "w") as f:
        json.dump(items, f, indent=1, sort_keys=True)
    with open(os.path.join(out, "manifest.jsonl"), "w") as f:
        for m in manifest:
            f.write(json.dumps(m, sort_keys=True) + "\n")
    with open(os.path.join(out, "schema.json"), "w") as f:
        json.dump(SCHEMA, f, indent=1, sort_keys=True)
    mutlib.write_pool_hashes(out, "CP")
    print("generated %d items (%d dev) in %s" % (len(manifest), N_DEV, out))


if __name__ == "__main__":
    main()
