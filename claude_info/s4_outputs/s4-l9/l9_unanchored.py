# /// script
# requires-python = ">=3.11"
# dependencies = ["pandas", "pyarrow"]
# ///
"""Procedure-only chains that h4_hdet.py drops because no recipe anchor is in them
(git_inspect / date_stamp / stack_tool only). Ceiling = $ of requests 2..n (no carry term, so a lower
bound on the h4 ceiling definition). Reads the h4 work dir built by h4_extract.py.
Usage: uv run --script l9_unanchored.py [WORK_DIR]   (default $TMPDIR/h4-work)
"""
import os, sys
import numpy as np
import pandas as pd

W = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.environ.get("TMPDIR", "/tmp"), "h4-work")
PROC = {"merge", "worktree", "commit", "git_inspect", "test_suite", "date_stamp", "install", "stack_tool", "bookkeeping"}
ANC = {"merge", "worktree", "test_suite", "commit", "bookkeeping", "install"}  # h4_hdet.py ANCHORS

t = pd.read_parquet(os.path.join(W, "tools.parquet"))
r = pd.read_parquet(os.path.join(W, "requests.parquet"))
t["cls"] = np.where(t.tool.isin(["Bash", "bash"]), t.proc, np.where(t.pclass == "bookkeeping", "bookkeeping", "nonproc"))
c = t.groupby(["session", "thread", "k_call"])["cls"].agg(frozenset).rename("cls")
son = r.model.str.contains("sonnet", na=False)  # MEASURE.md 1.2 list prices; recorded output (lower bound)
r["usd"] = (np.where(son, 2, 4) * r["input"] + np.where(son, 10, 20) * r["out"] + np.where(son, 2.5, 5) * r["cc5m"]
            + np.where(son, 4, 8) * r["cc1h"] + 0.2 * r["cr"]) / 1e6
tot = r.usd.sum()
print(f"total usd (recorded output) {tot:.1f}")
r2 = r.join(c, on=["session", "thread", "k"])
res = {}
for (s, th), g in r2.sort_values("k").groupby(["session", "thread"], sort=False):
    rows, i = g.to_dict("records"), 0
    while i < len(rows):
        cl = rows[i]["cls"]
        if not isinstance(cl, frozenset) or not cl <= PROC:
            i += 1
            continue
        j = i
        while j < len(rows) and isinstance(rows[j]["cls"], frozenset) and rows[j]["cls"] <= PROC:
            j += 1
        seg = rows[i:j]
        if len(seg) >= 2 and not any(x["cls"] & ANC for x in seg):
            key = "+".join(sorted(set().union(*[x["cls"] for x in seg])))
            d = res.setdefault(key, [0, 0.0, set()])
            d[0] += 1
            d[1] += sum(x["usd"] for x in seg[1:])
            d[2].add(s)
        i = max(j, i + 1)
for k, (n, u, ss) in sorted(res.items(), key=lambda kv: -kv[1][1]):
    print(f"{k:32s} n={n:3d} sessions={len(ss)} usd2..n={u:6.2f} share={100 * u / tot:.3f}%")
