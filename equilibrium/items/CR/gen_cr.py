# /// script
# requires-python = ">=3.10"
# dependencies = ["numpy"]
# ///
"""Seeded generator of the CR (code review) pool.

Frozen inputs: oracle/bases/*.py, oracle/tests/*.py (public part above the HIDDEN marker, whole file = hidden
suite), the operators in mutlib.py, SEED below. A fixture = two base modules (each with its public tests) with
1-3 seeded defects spread over them. A seeded defect is a single-token mutation that
  - passes the module's public tests (not trivially revealed),
  - fails the module's hidden tests when applied alone (it is a real behaviour defect),
  - never times out,
and defects in one file are more than 6 lines apart (the +-3 matching windows never overlap).
The combined fixture is re-verified: public tests pass for both modules, hidden tests fail for each buggy module.

  uv run gen_cr.py --out <pool dir>      (default: this folder);  --hash-only rewrites pool.sha256
"""
import argparse
import itertools
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

SEED = "eq|CR|pool|v1"
N_ITEMS = 200
N_DEV = 3
ITEMS_SEED = 3725927731  # eq|items (COMPARE_eq 3)
K_CHOICES = [1, 1, 2, 2, 2, 3]
PUBLIC_CHECK = ["uv", "run", "--no-project", "python", "-m", "unittest", "discover",
                "-s", "tests", "-t", ".", "-q"]
ALLOWED = ["Read", "Glob", "Grep", "Bash"]
PROMPT = (
    "The working directory holds a small Python package: two source modules and a tests/ directory whose tests "
    "currently pass (`uv run --no-project python -m unittest discover -s tests -t . -q`). The source modules contain "
    "between one and three seeded defects, each a place where the code deviates from the behaviour its docstrings "
    "state. Review the two source modules (not the tests). In `answer` return an array of findings, each an object "
    "{\"file\": path relative to the working directory, \"line\": 1-based line number of the defective statement, "
    "\"claim\": one sentence saying what is wrong and what it should be}. Do not modify any file. A finding counts "
    "only if it is a real defect against the documented behaviour; wrong or unsupported findings are penalised, so "
    "report only what you can justify."
)
SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "title": "CR arm output",
    "type": "object",
    "required": ["answer", "evidence", "confidence"],
    "additionalProperties": False,
    "properties": {
        "answer": {"type": "array", "items": {
            "type": "object", "required": ["file", "line", "claim"], "additionalProperties": False,
            "properties": {"file": {"type": "string"}, "line": {"type": "integer", "minimum": 1},
                           "claim": {"type": "string"}}}},
        "evidence": {"type": "array", "items": {
            "type": "object", "required": ["kind", "ref", "detail"], "additionalProperties": False,
            "properties": {"kind": {"enum": ["command", "file_line", "quote", "counterexample", "test"]},
                           "ref": {"type": "string"}, "detail": {"type": "string"}}}},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
    },
}


def verify_fixture(bases, files, chosen):
    """Public tests must pass in every module; hidden tests must fail in each buggy module."""
    with tempfile.TemporaryDirectory() as d:
        for n in files:
            muts = [m for m in chosen if m["file"] == n]
            mutlib.write_files(d, {n + ".py": mutlib.apply(bases[n].src, [m["site"] for m in muts]),
                                   "pub_" + n + ".py": bases[n].public_test,
                                   "hid_" + n + ".py": bases[n].hidden_test})
            pub = mutlib.run_unittest(d, "pub_" + n)
            if pub["rc"] != 0 or pub["ran"] == 0:
                return False
            if muts:
                hid = mutlib.run_unittest(d, "hid_" + n)
                if hid["rc"] != 1 or hid["timeout"]:
                    return False
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=HERE)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--hash-only", action="store_true")
    args = ap.parse_args()
    out = os.path.abspath(args.out)
    if args.hash_only:
        mutlib.write_pool_hashes(out, "CR")
        return
    src = os.path.join(HERE, "oracle")
    names = sorted(f[:-3] for f in os.listdir(os.path.join(src, "bases")) if f.endswith(".py"))
    bases = {n: mutlib.Base(src, n) for n in names}
    pools = {}
    for n in names:
        seen, pool = set(), []
        for r in mutlib.eval_module_sites(bases[n], args.workers):
            if r["hid"]["timeout"] or r["pub"]["timeout"]:
                continue
            if r["hid"]["rc"] == 1 and r["pub"]["rc"] == 0:
                key = (r["line"], r["col"], r["new"])
                if key not in seen:
                    seen.add(key)
                    pool.append({k: r[k] for k in ("kind", "line", "col", "end", "old", "new", "func")})
        pools[n] = pool

    rng = random.Random(SEED)
    pairs = list(itertools.combinations(names, 2))
    rng.shuffle(pairs)
    chosen_items = []
    sigs = set()
    for pair in pairs:
        if len(chosen_items) >= N_ITEMS + N_DEV:
            break
        files = list(pair)
        rng.shuffle(files)
        k = rng.choice(K_CHOICES)
        for _attempt in range(25):
            chosen = []
            for _ in range(k):
                n = rng.choice(files)
                site = rng.choice(pools[n])
                if any(c["file"] == n and abs(c["site"]["line"] - site["line"]) <= 6 for c in chosen):
                    continue
                chosen.append({"file": n, "site": site})
            if len(chosen) != k:
                continue
            sig = tuple(sorted((c["file"], c["site"]["line"], c["site"]["col"], c["site"]["new"]) for c in chosen))
            if sig in sigs or not verify_fixture(bases, files, chosen):
                continue
            sigs.add(sig)
            chosen_items.append((files, sorted(chosen, key=lambda c: (files.index(c["file"]), c["site"]["line"]))))
            break
    if len(chosen_items) < N_ITEMS + N_DEV:
        print("WARNING: only %d items built" % len(chosen_items), file=sys.stderr)
    dev, rest = chosen_items[:N_DEV], chosen_items[N_DEV:]

    shutil.rmtree(os.path.join(out, "fixtures"), ignore_errors=True)
    os.makedirs(os.path.join(out, "fixtures"), exist_ok=True)
    os.makedirs(os.path.join(out, "oracle", "hidden"), exist_ok=True)
    if out != HERE:
        for sub in ("bases", "tests"):
            shutil.rmtree(os.path.join(out, "oracle", sub), ignore_errors=True)
            shutil.copytree(os.path.join(src, sub), os.path.join(out, "oracle", sub))
    for n in names:
        with open(os.path.join(out, "oracle", "hidden", n + ".py"), "w") as f:
            f.write(bases[n].hidden_test)
    nrng = np.random.default_rng(ITEMS_SEED)
    items, manifest = {}, []
    for idx, (files, chosen) in enumerate(dev + rest):
        iid = "CR-DEV%d" % (idx + 1) if idx < N_DEV else "CR-%04d" % (idx - N_DEV + 1)
        fx = {"tests/__init__.py": ""}
        bugs = []
        for n in files:
            muts = [c["site"] for c in chosen if c["file"] == n]
            fx[n + ".py"] = mutlib.apply(bases[n].src, muts)
            fx["tests/test_%s.py" % n] = bases[n].public_test
        for c in chosen:
            s = c["site"]
            orig = bases[c["file"]].src.split("\n")[s["line"] - 1]
            seeded = fx[c["file"] + ".py"].split("\n")[s["line"] - 1]
            bugs.append({"file": c["file"] + ".py", "line": s["line"], "col": s["col"], "kind": s["kind"],
                         "func": s["func"], "old": s["old"], "new": s["new"], "orig_line": orig,
                         "seeded_line": seeded, "claim": mutlib.describe(s)})
        mutlib.write_files(os.path.join(out, "fixtures", iid), fx)
        items[iid] = {"files": files, "bugs": bugs, "n_seeded": len(bugs)}
        segs = []
        for n in files:
            segs.append({"id": "src_" + n, "path": n + ".py"})
            segs.append({"id": "test_" + n, "path": "tests/test_%s.py" % n})
        perm = [int(i) for i in nrng.permutation(len(segs))]
        segs = [segs[i] for i in perm]
        roles = ["source" if s["id"].startswith("src_") else "test" for s in segs]
        pinned = [i for i, r in enumerate(roles) if r == "source"]
        buggy = sorted({b["file"] for b in bugs})
        decisive = None
        if len(buggy) == 1:
            decisive = [s["path"] for s in segs].index(buggy[0])
        manifest.append({
            "id": iid, "class": "CR", "dev": iid.startswith("CR-DEV"), "answer_kind": "finding_set",
            "prompt": PROMPT, "segments": segs, "segment_roles": roles,
            "pinned_segments": pinned, "decisive_segment": decisive,
            "fixture": "fixtures/" + iid, "public_check": PUBLIC_CHECK, "allowed_tools": ALLOWED})
    with open(os.path.join(out, "oracle", "items.json"), "w") as f:
        json.dump(items, f, indent=1, sort_keys=True)
    with open(os.path.join(out, "manifest.jsonl"), "w") as f:
        for m in manifest:
            f.write(json.dumps(m, sort_keys=True) + "\n")
    with open(os.path.join(out, "schema.json"), "w") as f:
        json.dump(SCHEMA, f, indent=1, sort_keys=True)
    mutlib.write_pool_hashes(out, "CR")
    print("generated %d items (%d dev) in %s" % (len(manifest), N_DEV, out))


if __name__ == "__main__":
    main()
