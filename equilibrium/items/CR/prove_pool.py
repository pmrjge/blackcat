# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""Proof that every CR item's manifest points at its seeded defects and that the reference finding set scores 1.

  uv run prove_pool.py [--regen]

Per item (dev items reported separately):
  1. seeded fixture: public tests pass in both modules (defects are not trivially revealed); hidden tests fail
     in every module that holds a defect
  2. reference (base modules): public and hidden tests pass
  3. every bug alone (reference + that one mutation) fails its module's hidden tests while public tests pass
  4. seeded vs reference differ in exactly the manifest lines of each file; the line text equals the manifest's
     orig_line / seeded_line; bug lines in one file are more than 6 apart
  5. oracle.py: the reference finding set scores 1.0 (provisional path and graded path with all-true verdicts);
     a single finding shifted by +3 lines still matches, shifted by +4 does not (location rule pinned);
     an empty finding set scores 0.0; a finding in the wrong file does not match
  6. the prompt is one pool-wide constant (cannot encode a location)
--regen additionally regenerates the pool with gen_cr.py into a scratch dir and compares file hashes.
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
sys.path.insert(0, HERE)
import refs  # noqa: E402
import mutlib  # noqa: E402

PROMPT0 = []
PUBLIC = [sys.executable, "-B", "-m", "unittest", "discover", "-s", "tests", "-t", ".", "-q"]


def sh(argv, cwd=None, timeout=120):
    return subprocess.run(argv, cwd=cwd, capture_output=True, text=True, timeout=timeout)


NONCE = "00112233445566778899aabbccddeeff"


def oracle(item, answer, *extra):
    """Score from the authenticated `EQV1 <nonce> <json>` line (the nonce goes in on stdin)."""
    p = subprocess.run([sys.executable, os.path.join(HERE, "oracle.py"), "--item", item, "--answer", answer, *extra],
                       input=NONCE + "\n", capture_output=True, text=True, timeout=120)
    lines = [ln for ln in p.stdout.splitlines() if ln.startswith("EQV1 %s " % NONCE)]
    if p.returncode != 0 or len(lines) != 1:
        return None
    return json.loads(lines[0][len("EQV1 %s " % NONCE):])["score"]


def hidden_rc(workdir, mod):
    with tempfile.TemporaryDirectory() as d:
        mutlib.write_files(d, {mod + ".py": open(os.path.join(workdir, mod + ".py")).read(),
                               "h_" + mod + ".py": open(os.path.join(HERE, "oracle", "hidden", mod + ".py")).read()})
        return mutlib.run_unittest(d, "h_" + mod)["rc"]


def prove(args):
    iid, it, man = args
    errs = []
    bugs = it["bugs"]
    with tempfile.TemporaryDirectory() as tmp:
        seed = refs.seeded_workdir(iid, os.path.join(tmp, "seed"))
        ref = refs.reference_workdir(iid, os.path.join(tmp, "ref"))
        buggy = {b["file"][:-3] for b in bugs}
        if sh(PUBLIC, seed).returncode != 0:
            errs.append("public tests fail on the seeded fixture")
        if sh(PUBLIC, ref).returncode != 0:
            errs.append("public tests fail on the reference")
        for mod in it["files"]:
            if mod in buggy and hidden_rc(seed, mod) != 1:
                errs.append("hidden tests do not fail on seeded %s" % mod)
            if hidden_rc(ref, mod) != 0:
                errs.append("hidden tests fail on reference %s" % mod)
        # 3. each bug alone
        for b in bugs:
            mod = b["file"][:-3]
            base = open(os.path.join(HERE, "oracle", "bases", b["file"])).read()
            site = {k: b[k] for k in ("col", "old", "new")}
            site.update(line=b["line"], end=b["col"] + len(b["old"]))
            single = mutlib.apply(base, [site])
            with tempfile.TemporaryDirectory() as d:
                mutlib.write_files(d, {mod + ".py": single, "h_" + mod + ".py": open(os.path.join(HERE, "oracle", "hidden", mod + ".py")).read(),
                                       "p_" + mod + ".py": open(os.path.join(HERE, "fixtures", iid, "tests", "test_%s.py" % mod)).read()})
                if mutlib.run_unittest(d, "h_" + mod)["rc"] != 1:
                    errs.append("bug %s:%d alone does not fail hidden tests" % (b["file"], b["line"]))
                if mutlib.run_unittest(d, "p_" + mod)["rc"] != 0:
                    errs.append("bug %s:%d alone fails public tests" % (b["file"], b["line"]))
        # 4. manifest lines == differing lines
        for mod in it["files"]:
            a = open(os.path.join(HERE, "oracle", "bases", mod + ".py")).read().split("\n")
            c = open(os.path.join(seed, mod + ".py")).read().split("\n")
            diff = [i + 1 for i, (x, y) in enumerate(zip(a, c)) if x != y]
            mine = sorted(b["line"] for b in bugs if b["file"] == mod + ".py")
            if len(a) != len(c) or diff != mine:
                errs.append("%s: differing lines %s != manifest lines %s" % (mod, diff, mine))
            for b in bugs:
                if b["file"] == mod + ".py" and (a[b["line"] - 1] != b["orig_line"] or c[b["line"] - 1] != b["seeded_line"]):
                    errs.append("%s:%d line text mismatch" % (mod, b["line"]))
            for x in mine:
                for y in mine:
                    if x < y and y - x <= 6:
                        errs.append("%s: bugs at %d and %d closer than 7 lines" % (mod, x, y))
        # 5. oracle behaviour
        good = refs.reference_findings(iid)
        p = os.path.join(tmp, "good.json")
        refs.write_answer(p, good)
        if oracle(iid, p) != 1.0:
            errs.append("reference findings do not score 1.0 (provisional)")
        gin = os.path.join(tmp, "gin.json")
        oracle(iid, p, "--grader-input", gin)
        g = json.load(open(gin))
        gr = os.path.join(tmp, "gr.json")
        json.dump([{"rid": f["rid"], "verdict": "true", "note": ""} for f in g], open(gr, "w"))
        if oracle(iid, p, "--grade", gr) != 1.0:
            errs.append("reference findings do not score 1.0 (graded)")
        n = len(bugs)
        for bi, bg in enumerate(bugs):
            # one finding shifted by d lines: +3 must match some bug (score 1/n); +4 matches only if another
            # seeded bug of the same file lies within 3 lines of the shifted line (then 1/n), else it is false
            for d in (3, 4):
                q = os.path.join(tmp, "s%d_%d.json" % (bi, d))
                refs.write_answer(q, [dict(good[bi], line=good[bi]["line"] + d)])
                s = oracle(iid, q)
                near = any(o["file"] == bg["file"] and abs(bg["line"] + d - o["line"]) <= 3 for o in bugs)
                want = 1.0 / n if (d == 3 or near) else -0.5 / n
                if s is None or abs(s - want) > 1e-5:
                    errs.append("bug %d shifted +%d scored %s, wanted %.4f" % (bi, d, s, want))
        q = os.path.join(tmp, "e.json")
        refs.write_answer(q, [])
        if oracle(iid, q) != 0.0:
            errs.append("empty set does not score 0.0")
        other = [m for m in ("stats", "trie", "rle") if m not in it["files"]][0] + ".py"
        q = os.path.join(tmp, "w.json")
        refs.write_answer(q, [dict(f, file=other) for f in good])
        s = oracle(iid, q)
        if s is None or s >= 0:
            errs.append("wrong-file findings score %s, wanted < 0" % s)
        # 6. prompt / fixture hygiene
        if man["prompt"] != PROMPT0[0]:
            errs.append("prompt differs from the pool-wide constant")
        for dp, dn, fn in os.walk(seed):
            for f in fn:
                if f.startswith("hid") or "hidden" in dp:
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
    with ThreadPoolExecutor(6) as ex:
        results = list(ex.map(prove, [(i, items[i], manifest[i]) for i in sorted(items)]))
    lines, bad = [], 0
    nd = sum(1 for i, e in results if "DEV" not in i)
    for iid, errs in results:
        if errs:
            bad += 1
            lines.append("FAIL %s: %s" % (iid, "; ".join(errs)))
    lines.append("non-dev proven: %d / %d" % (sum(1 for i, e in results if "DEV" not in i and not e), nd))
    lines.append("dev proven: %d / %d" % (sum(1 for i, e in results if "DEV" in i and not e), len(results) - nd))
    ks = {}
    kinds = {}
    for it in items.values():
        ks[it["n_seeded"]] = ks.get(it["n_seeded"], 0) + 1
        for b in it["bugs"]:
            kinds[b["kind"]] = kinds.get(b["kind"], 0) + 1
    lines.append("seeded bugs per item: %s; bug kinds: %s" % (dict(sorted(ks.items())), dict(sorted(kinds.items()))))
    if "--regen" in sys.argv:
        with tempfile.TemporaryDirectory() as tmp:
            p = sh(["uv", "run", os.path.join(HERE, "gen_cr.py"), "--out", tmp], timeout=1800)
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
