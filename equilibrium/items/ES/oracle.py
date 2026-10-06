# /// script
# requires-python = ">=3.11"
# ///
"""ES oracle (COMPARE_eq §2): score e = |ln(estimate / true)|; a non-positive, non-finite, non-numeric or missing
estimate scores e = inf (printed as the string "inf"). Lower is better; the pairwise rule (win if e_A < e_B - ln 1.1)
is applied by the analysis, not here.

  uv run oracle.py --item ES-0001 --answer answer.json [--workdir DIR]

answer.json is the arm output object; `answer` must be a JSON number. Prints one JSON line {"item","score","detail"}.
Exit 0 when scored, 2 on malformed input (unknown item, unreadable or non-object JSON). --workdir is unused (ES has no
fixture). True values live in oracle/truth.jsonl (World Bank WDI API, accessed 2026-10-04).
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
LN11 = math.log(1.1)


def emit(item, score, detail, code):
    print(json.dumps({"item": item, "score": score, "detail": detail}, ensure_ascii=False))
    sys.exit(code)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--item", required=True)
    ap.add_argument("--answer", required=True)
    ap.add_argument("--workdir")
    a = ap.parse_args()
    truth = {}
    for line in (HERE / "oracle" / "truth.jsonl").read_text().splitlines():
        if line.strip():
            t = json.loads(line)
            truth[t["id"]] = t
    if a.item not in truth:
        emit(a.item, None, "unknown item", 2)
    try:
        out = json.loads(Path(a.answer).read_text())
    except Exception as exc:  # noqa: BLE001
        emit(a.item, None, f"malformed answer file: {exc}", 2)
    if not isinstance(out, dict):
        emit(a.item, None, "malformed answer file: not a JSON object", 2)
    est = out.get("answer")
    if isinstance(est, bool) or not isinstance(est, (int, float)):
        emit(a.item, "inf", {"e": None, "reason": "missing or non-numeric answer"}, 0)
    est = float(est)
    if not math.isfinite(est) or est <= 0:
        emit(a.item, "inf", {"e": None, "reason": "non-positive or non-finite estimate"}, 0)
    true = float(truth[a.item]["true_value"])
    e = abs(math.log(est / true))
    emit(a.item, round(e, 9), {"e": e, "ratio": est / true, "within_ln1.1": e <= LN11}, 0)


if __name__ == "__main__":
    main()
