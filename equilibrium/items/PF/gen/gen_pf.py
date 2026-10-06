# /// script
# requires-python = ">=3.11"
# dependencies = ["numpy>=1.26"]
# ///
"""PF pool generator and verifier.

  uv run gen_pf.py verify   [--jobs N]   # candidates -> ref compiles, gap-following wrong answer fails,
                                         # gap refutation compiles, automation battery fails (non-triviality)
  uv run gen_pf.py assemble              # keep candidates passing every check; write manifest, fixtures, oracle/
  uv run gen_pf.py finalcheck [--jobs N] # oracle.py on every item's reference answer and gap-following wrong answer

Deterministic: parameters are explicit lists in families.py; segment shuffle uses
numpy.random.default_rng(3725927731) (seed `eq|items`, COMPARE_eq §3/§8.4), items processed in id order.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from families import all_candidates  # noqa: E402

GEN = Path(__file__).resolve().parent
PF = GEN.parent
ORACLE = PF / "oracle"
BUILD = ORACLE / "build"
CHECK = PF / "check_lean.sh"
PROJ = os.environ.get("EQ_LEAN_PROJECT", os.path.expanduser("~/lean/stack_mathlib"))
SEED_ITEMS = 3725927731
DEV_FAMILIES = ("gcdlin", "divind", "amgm")
ALLOWED_TOOLS = ["Read", "Write", "Edit", "Bash"]
LEAN_HEADER = "import Mathlib\n\n"

BATTERY = ["simp", "simp_all", "decide", "omega", "norm_num", "linarith", "nlinarith", "positivity", "aesop",
           "tauto", "ring_nf", "field_simp", "exact?"]


def ref_file(name, c):
    return f"{LEAN_HEADER}theorem {name} : {c['stmt']} := by\n{c['ref']}\n"


def wrong_file(name, c):
    return (f"{LEAN_HEADER}theorem {name} : {c['stmt']} := by\n"
            f"  have eq_gap : {c['gap_lean']} := by\n    {c['wrong_tac']}\n{c['ref']}\n")


def gap_file(c):
    return f"{LEAN_HEADER}theorem eq_gap_refutation : ¬ ({c['gap_lean']}) := by\n{c['gap_refute']}\n"


def battery_file(c):
    lines = [LEAN_HEADER.rstrip("\n"), "", "set_option maxHeartbeats 200000"]
    ranges = []
    for tac in BATTERY:
        for intro in (False, True):
            start = len(lines) + 1
            lines.append(f"example : {c['stmt']} := by")
            if intro:
                lines.append("  intros")
            lines.append(f"  {tac}")
            ranges.append((f"{'intros; ' if intro else ''}{tac}", start, len(lines)))
    s1 = len(lines) + 1
    lines += ["example : (1 : ℕ) + 1 = 2 := by", "  norm_num"]
    ranges.append(("SENTINEL_OK", s1, len(lines)))
    s2 = len(lines) + 1
    lines += ["example : (1 : ℕ) = 2 := by", "  norm_num"]
    ranges.append(("SENTINEL_FAIL", s2, len(lines)))
    return "\n".join(lines) + "\n", ranges


def lean_path():
    return subprocess.run(["lake", "env", "printenv", "LEAN_PATH"], cwd=PROJ, capture_output=True, text=True,
                          check=True).stdout.strip()


def run_lean(path, lp, timeout=900):
    env = dict(os.environ, LEAN_PATH=lp)
    try:
        p = subprocess.run(["lean", str(path)], cwd=PROJ, env=env, capture_output=True, text=True, timeout=timeout)
        return p.returncode, p.stdout + p.stderr
    except subprocess.TimeoutExpired:
        return 124, "timeout"


def run_check(ans_path, stmt_path):
    p = subprocess.run(["bash", str(CHECK), str(ans_path), str(stmt_path)], capture_output=True, text=True)
    return p.returncode, (p.stdout + p.stderr).strip()


def statement_txt(name, stmt):
    return f"{name}\n{stmt}\n"


def verify_one(c, lp, tmp):
    d = Path(tmp) / c["key"]
    d.mkdir(parents=True, exist_ok=True)
    name = "pf_item"
    (d / "statement.txt").write_text(statement_txt(name, c["stmt"]))
    (d / "ref.lean").write_text(ref_file(name, c))
    (d / "wrong.lean").write_text(wrong_file(name, c))
    (d / "gap.lean").write_text(gap_file(c))
    bat, ranges = battery_file(c)
    (d / "battery.lean").write_text(bat)
    res = {"key": c["key"], "family": c["family"]}
    rc, out = run_check(d / "ref.lean", d / "statement.txt")
    res["ref_pass"] = rc == 0 and out.endswith("PASS")
    res["ref_out"] = out[-400:]
    rc, out = run_check(d / "wrong.lean", d / "statement.txt")
    res["wrong_rejected"] = rc == 1 and out.startswith("FAIL")
    res["wrong_out"] = out[-300:]
    rc, out = run_lean(d / "gap.lean", lp)
    res["gap_refuted"] = rc == 0 and "error" not in out
    res["gap_out"] = out[-300:]
    rc, out = run_lean(d / "battery.lean", lp, timeout=1500)
    err_lines = {int(m.group(1)) for m in re.finditer(r"battery\.lean:(\d+):\d+: error", out)}
    solved = []
    ok_sent = fail_sent = False
    for label, a, b in ranges:
        has_err = any(a <= ln <= b for ln in err_lines)
        if label == "SENTINEL_OK":
            ok_sent = not has_err
        elif label == "SENTINEL_FAIL":
            fail_sent = has_err
        elif not has_err:
            solved.append(label)
    res["battery_valid"] = ok_sent and fail_sent and rc != 124
    res["battery_solved_by"] = solved
    res["battery_nontrivial"] = res["battery_valid"] and not solved
    res["ok"] = res["ref_pass"] and res["wrong_rejected"] and res["gap_refuted"] and res["battery_nontrivial"]
    print(f"{c['key']}: ok={res['ok']} ref={res['ref_pass']} wrong_rej={res['wrong_rejected']} "
          f"gap={res['gap_refuted']} battery_valid={res['battery_valid']} solved_by={solved}", flush=True)
    return res


def cmd_verify(args):
    cands = all_candidates()
    if args.only:
        cands = [c for c in cands if re.search(args.only, c["key"])]
    lp = lean_path()
    BUILD.mkdir(parents=True, exist_ok=True)
    tmp = tempfile.mkdtemp(prefix="pfverify.", dir=os.environ.get("TMPDIR"))
    with ThreadPoolExecutor(max_workers=args.jobs) as ex:
        results = list(ex.map(lambda c: verify_one(c, lp, tmp), cands))
    out = BUILD / ("verify_results.jsonl" if not args.only else "verify_results_partial.jsonl")
    with out.open("w") as f:
        for r in results:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    n_ok = sum(r["ok"] for r in results)
    print(f"verified {n_ok}/{len(results)} candidates ok -> {out}")
    if not args.keep:
        shutil.rmtree(tmp, ignore_errors=True)


PROMPT = """PF item {id}. Prove the theorem below in Lean 4 with Mathlib.

theorem {name} : {stmt}

Your working directory has Problem.lean (this statement with `sorry`), statement.txt, check_lean.sh and
EqVerify.lean. Toolchain: Lean 4.34.1 with Mathlib v4.34.1 (the project check_lean.sh uses). Write a complete Lean
file that starts with `import Mathlib` and proves a top-level theorem named `{name}` with exactly this statement; the
proof may use no axioms beyond propext, Classical.choice and Quot.sound (so no `sorry`, no `native_decide`).
Check it with `bash check_lean.sh Answer.lean` (prints PASS or FAIL). Return the complete file text in `answer`.

An informal proof sketch follows as segments, each labelled with its step number (segments may be shown out of
order). The sketch has not been checked."""


def cmd_assemble(args):
    cands = {c["key"]: c for c in all_candidates()}
    results = [json.loads(line) for line in (BUILD / "verify_results.jsonl").read_text().splitlines()]
    ok_keys = [r["key"] for r in results if r["ok"]]
    order = [c["key"] for c in all_candidates() if c["key"] in set(ok_keys)]
    dev = []
    for fam in DEV_FAMILIES:
        k = next(k for k in order if cands[k]["family"] == fam)
        dev.append(k)
    pool = [k for k in order if k not in dev]
    ids = {k: f"PF-{i + 1:04d}" for i, k in enumerate(pool)}
    ids.update({k: f"PF-DEV{i + 1}" for i, k in enumerate(dev)})
    for sub in ("fixtures", "oracle/ref", "oracle/wrong", "oracle/gap"):
        shutil.rmtree(PF / sub, ignore_errors=True) if sub == "fixtures" or sub.startswith("oracle/") else None
        (PF / sub).mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(SEED_ITEMS)
    manifest, meta = [], []
    for key in sorted(ids, key=lambda k: ids[k]):
        c, iid = cands[key], ids[key]
        name = "pf_" + iid.split("-", 1)[1].lower()
        K = len(c["steps"])
        labelled = [f"Step {i + 1} of {K}: {s}" for i, s in enumerate(c["steps"])]
        perm = rng.permutation(K)
        segments = [{"id": f"s{int(p) + 1}", "text": labelled[int(p)]} for p in perm]
        decisive = int(np.where(perm == c["gap_step"])[0][0])
        fx = PF / "fixtures" / iid
        fx.mkdir(parents=True, exist_ok=True)
        (fx / "Problem.lean").write_text(f"{LEAN_HEADER}theorem {name} : {c['stmt']} := by\n  sorry\n")
        (fx / "statement.txt").write_text(statement_txt(name, c["stmt"]))
        shutil.copy2(CHECK, fx / "check_lean.sh")
        shutil.copy2(PF / "EqVerify.lean", fx / "EqVerify.lean")
        (ORACLE / "ref" / f"{iid}.lean").write_text(ref_file(name, c))
        (ORACLE / "wrong" / f"{iid}.lean").write_text(wrong_file(name, c))
        (ORACLE / "gap" / f"{iid}.lean").write_text(gap_file(c))
        manifest.append({
            "id": iid, "class": "PF", "dev": iid.startswith("PF-DEV"), "answer_kind": "checkable",
            "prompt": PROMPT.format(id=iid, name=name, stmt=c["stmt"]),
            "segments": segments, "decisive_segment": decisive,
            "fixture": f"fixtures/{iid}", "public_check": ["bash", "check_lean.sh", "Answer.lean"],
            "allowed_tools": ALLOWED_TOOLS,
        })
        meta.append({"id": iid, "family": c["family"], "key": key, "theorem": name, "gap_step": c["gap_step"],
                     "gap_segment_index": decisive, "gap_lean": c["gap_lean"], "segment_perm": [int(p) for p in perm]})
    with (PF / "manifest.jsonl").open("w") as f:
        for m in manifest:
            f.write(json.dumps(m, ensure_ascii=False) + "\n")
    with (ORACLE / "items_meta.jsonl").open("w") as f:
        for m in meta:
            f.write(json.dumps(m, ensure_ascii=False) + "\n")
    print(f"assembled {len(pool)} pool items + {len(dev)} dev items")


def final_one(item, tmp):
    iid = item["id"]
    out = {"id": iid}
    for kind in ("ref", "wrong"):
        txt = (ORACLE / kind / f"{iid}.lean").read_text()
        aj = Path(tmp) / f"{iid}.{kind}.json"
        aj.write_text(json.dumps({"answer": txt, "evidence": [], "confidence": 0.5}))
        t0 = time.monotonic()
        p = subprocess.run(["uv", "run", "--quiet", str(PF / "oracle.py"), "--item", iid, "--answer", str(aj)],
                           capture_output=True, text=True)
        try:
            out[kind] = json.loads(p.stdout.strip().splitlines()[-1])["score"]
        except Exception:  # noqa: BLE001
            out[kind] = f"error rc={p.returncode} {p.stderr[-200:]}"
        out[kind + "_s"] = round(time.monotonic() - t0, 1)
    print(f"{iid}\tref={out['ref']}\twrong={out['wrong']}", flush=True)
    return out


def cmd_finalcheck(args):
    items = [json.loads(line) for line in (PF / "manifest.jsonl").read_text().splitlines()]
    tmp = tempfile.mkdtemp(prefix="pffinal.", dir=os.environ.get("TMPDIR"))
    with ThreadPoolExecutor(max_workers=args.jobs) as ex:
        res = list(ex.map(lambda it: final_one(it, tmp), items))
    with (BUILD / "final_check.tsv").open("w") as f:
        f.write("id\tref_score\twrong_score\tref_seconds\twrong_seconds\n")
        for r in res:
            f.write(f"{r['id']}\t{r['ref']}\t{r['wrong']}\t{r['ref_s']}\t{r['wrong_s']}\n")
    n_ref = sum(r["ref"] == 1 for r in res)
    n_wrong = sum(r["wrong"] == 0 for r in res)
    print(f"reference compiled (oracle score 1): {n_ref}/{len(res)}; gap-following wrong rejected: {n_wrong}/{len(res)}")
    shutil.rmtree(tmp, ignore_errors=True)
    sys.exit(0 if n_ref == len(res) == n_wrong else 1)


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    v = sub.add_parser("verify")
    v.add_argument("--jobs", type=int, default=10)
    v.add_argument("--only", default="")
    v.add_argument("--keep", action="store_true")
    sub.add_parser("assemble")
    f = sub.add_parser("finalcheck")
    f.add_argument("--jobs", type=int, default=10)
    a = ap.parse_args()
    {"verify": cmd_verify, "assemble": cmd_assemble, "finalcheck": cmd_finalcheck}[a.cmd](a)


if __name__ == "__main__":
    main()
