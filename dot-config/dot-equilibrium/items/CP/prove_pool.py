# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""Proof that every CP item fails on its seed and passes on its reference fix.

  uv run prove_pool.py [--regen]

Per item (dev items included, reported separately):
  1. seeded fixture: public tests fail (rc != 0) and `oracle.py` scores 0.0
  2. reference fix (base module restored): public tests pass and `oracle.py` scores 1.0
  3. seeded module differs from the reference in exactly the one recorded line, at the recorded token
  4. the prompt is one pool-wide constant (it cannot encode the location) and does not name the module
  5. fixture holds no hidden material (no hidden_*.py, no 'hidden' directory)
--regen additionally regenerates the pool with gen_cp.py into a scratch dir and compares hashes of the
generated files (manifest, schema, items.json, fixtures, hidden tests): the pool is reproducible.
Writes proof_report.txt next to this script. Exit 1 on any failure.
"""
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "oracle"))
import refs  # noqa: E402

PROMPT0 = []
PUBLIC = [sys.executable, "-B", "-m", "unittest", "discover", "-s", "tests", "-t", ".", "-q"]


def sh(argv, cwd=None, timeout=120):
    return subprocess.run(argv, cwd=cwd, capture_output=True, text=True, timeout=timeout)


NONCE = "00112233445566778899aabbccddeeff"


def oracle_score(item, ans, wd):
    """Score from the authenticated `EQV1 <nonce> <json>` line (the nonce goes in on stdin)."""
    p = subprocess.run([sys.executable, os.path.join(HERE, "oracle.py"), "--item", item, "--answer", ans, "--workdir", wd],
                       input=NONCE + "\n", capture_output=True, text=True, timeout=120)
    lines = [ln for ln in p.stdout.splitlines() if ln.startswith("EQV1 ")]
    if p.returncode != 0 or len(lines) != 1 or not lines[0].startswith("EQV1 %s " % NONCE):
        return "rc%d/%d verdict lines" % (p.returncode, len(lines))
    return json.loads(lines[0][len("EQV1 %s " % NONCE):])["score"]


def prove(args):
    iid, it, man = args
    errs = []
    with tempfile.TemporaryDirectory() as tmp:
        ans = os.path.join(tmp, "a.json")
        refs.answer_json(ans)
        seed = refs.seeded_workdir(iid, os.path.join(tmp, "seed"))
        ref = refs.reference_workdir(iid, os.path.join(tmp, "ref"))
        mod = it["module"]
        if sh(PUBLIC, seed).returncode == 0:
            errs.append("public tests PASS on seed")
        if oracle_score(iid, ans, seed) != 0.0:
            errs.append("hidden tests do not fail on seed")
        if sh(PUBLIC, ref).returncode != 0:
            errs.append("public tests fail on reference")
        if oracle_score(iid, ans, ref) != 1.0:
            errs.append("hidden tests do not pass on reference")
        a = open(os.path.join(HERE, "oracle", "bases", mod + ".py")).read().split("\n")
        b = open(os.path.join(seed, mod + ".py")).read().split("\n")
        diff = [i + 1 for i, (x, y) in enumerate(zip(a, b)) if x != y]
        m = it["mutation"]
        if len(a) != len(b) or diff != [m["line"]]:
            errs.append("seed differs from reference in lines %s, expected [%d]" % (diff, m["line"]))
        elif b[m["line"] - 1][m["col"]:m["col"] + len(m["new"])] != m["new"] or a[m["line"] - 1][m["col"]:m["end"]] != m["old"]:
            errs.append("recorded token does not match")
        if man["prompt"] != PROMPT0[0]:
            errs.append("prompt differs from the pool-wide constant prompt (could encode the location)")
        if mod in man["prompt"]:
            errs.append("prompt names the module")
        for dp, dn, fn in os.walk(seed):
            for f in fn:
                if f.startswith("hidden") or "hidden" in dp:
                    errs.append("hidden material in fixture: " + f)
    return iid, errs


def tree_hashes(root):
    out = {}
    for sub in ("fixtures", os.path.join("oracle", "hidden")):
        for dp, dn, fn in os.walk(os.path.join(root, sub)):
            dn[:] = [d for d in dn if d != "__pycache__"]
            for f in fn:
                p = os.path.join(dp, f)
                out[os.path.relpath(p, root)] = hashlib.sha256(open(p, "rb").read()).hexdigest()
    for f in ("manifest.jsonl", "schema.json", os.path.join("oracle", "items.json")):
        out[f] = hashlib.sha256(open(os.path.join(root, f), "rb").read()).hexdigest()
    return out


def main():
    items = refs.items()
    manifest = {}
    with open(os.path.join(HERE, "manifest.jsonl")) as f:
        for line in f:
            r = json.loads(line)
            manifest[r["id"]] = r
    PROMPT0.append(next(iter(manifest.values()))["prompt"])
    assert set(items) == set(manifest), "manifest and items.json disagree"
    with ThreadPoolExecutor(8) as ex:
        results = list(ex.map(prove, [(i, items[i], manifest[i]) for i in sorted(items)]))
    lines = []
    bad = 0
    nd = sum(1 for i, e in results if "DEV" not in i)
    ok_nd = sum(1 for i, e in results if "DEV" not in i and not e)
    ok_d = sum(1 for i, e in results if "DEV" in i and not e)
    for iid, errs in results:
        if errs:
            bad += 1
            lines.append("FAIL %s: %s" % (iid, "; ".join(errs)))
    lines.append("non-dev proven: %d / %d" % (ok_nd, nd))
    lines.append("dev proven: %d / %d" % (ok_d, len(results) - nd))
    modules = {}
    for i in items.values():
        modules[i["module"]] = modules.get(i["module"], 0) + 1
    lines.append("modules: %d, items per module min/max: %d/%d" % (len(modules), min(modules.values()), max(modules.values())))
    if "--regen" in sys.argv:
        with tempfile.TemporaryDirectory() as tmp:
            p = sh(["uv", "run", os.path.join(HERE, "gen_cp.py"), "--out", tmp], timeout=1800)
            if p.returncode != 0:
                lines.append("FAIL regen: " + p.stderr[-300:])
                bad += 1
            else:
                same = tree_hashes(tmp) == tree_hashes(HERE)
                lines.append("regeneration identical to frozen pool: %s" % same)
                bad += 0 if same else 1
    with open(os.path.join(HERE, "proof_report.txt"), "w") as f:
        f.write("\n".join(lines) + "\n")
    print("\n".join(lines))
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
