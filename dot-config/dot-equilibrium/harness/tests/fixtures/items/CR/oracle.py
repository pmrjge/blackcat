# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""FAKE CR oracle for the harness tests (same CLI and record format as items/CR/oracle.py, toy scoring).

Seeded bug: every finding in f1.py with line <= 5 "matches". --grader-input writes records {rid "f<i>", type,
finding, seeded_bug (match only), code_excerpt}; --grade takes [{rid, verdict, note}] or {"verdicts": [{id, verdict}]}
and prints score = number of matched findings marked true, detail = {rid: verdict}.
Verdict channel (EQV1, R1 F1): the first stdin line is the harness's nonce; the one result line is
`EQV1 <nonce> <json>`, on every exit path.
"""

import argparse
import json
import sys
from pathlib import Path

NONCE = sys.stdin.readline().strip()


def verdict(obj: dict, rc: int = 0) -> None:
    print(f"EQV1 {NONCE} {json.dumps(obj)}")
    sys.exit(rc)


ap = argparse.ArgumentParser()
ap.add_argument("--item", required=True)
ap.add_argument("--answer", required=True)
ap.add_argument("--workdir")
ap.add_argument("--grader-input")
ap.add_argument("--grade")
a = ap.parse_args()
ans = json.loads(Path(a.answer).read_text())
if not isinstance(ans, dict) or not isinstance(ans.get("answer"), list):
    verdict({"item": a.item, "score": None, "detail": "malformed"}, 2)
fs = ans["answer"]


def match(f: dict) -> bool:
    return f.get("file") == "f1.py" and int(f.get("line", 99)) <= 5


if a.grader_input:
    out = []
    for i, f in enumerate(fs):
        rec = {"rid": f"f{i}", "type": "match" if match(f) else "unmatched",
               "finding": {"file": f["file"], "line": f["line"], "claim": f["claim"]}}
        if match(f):
            rec["seeded_bug"] = {"file": "f1.py", "line": 3, "description": "toy bug"}
        rec["code_excerpt"] = f"   {f['line']}  x = 1"
        out.append(rec)
    Path(a.grader_input).write_text(json.dumps(out))
    verdict({"item": a.item, "score": None, "detail": "grader input written"})
vs = json.loads(Path(a.grade).read_text()) if a.grade else []
vs = vs.get("verdicts") if isinstance(vs, dict) else vs
got = {int(str(v.get("rid", v.get("id"))).lstrip("f")): v["verdict"] for v in vs}
if any(i not in got for i in range(len(fs))):
    verdict({"item": a.item, "score": None, "detail": "missing verdict"}, 2)
score = sum(1 for i, f in enumerate(fs) if match(f) and got[i] == "true")
verdict({"item": a.item, "score": score, "detail": {f"f{i}": got[i] for i in range(len(fs))}})
