#!/usr/bin/env -S uv run --script --quiet
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Synthetic grading_results for the stub fixture (SYNTHETIC: the stub arms all answer alike, so the oracle files would
be flat). Writes <run dir>/grading_results/{PF,CP,ES,CR}.jsonl exactly in the LEDGER_SCHEMA.md shape, one line per
item-arm of those classes, with deterministic pseudo-random scores (sha256 of item|label), plus a CR per-member line
(node/member set) that an analysis must ignore, and one superseded older line per class (the later ts_utc must win).

    uv run --script analysis-r2/synth_grading.py <run dir>
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

# P(score = 1) per arm for the binary classes; the order of arms makes E look better, on purpose
P_ONE = {"E": 0.75, "EG": 0.6, "G": 0.45, "S*": 0.4}


def u(*parts: str) -> float:
    return int(hashlib.sha256("|".join(parts).encode()).hexdigest()[:8], 16) / 16**8


def main(run_dir: Path) -> None:
    ia = [json.loads(line) for line in (run_dir / "ledger.jsonl").read_text().splitlines()
          if line.strip() and json.loads(line).get("record") == "item_arm"]
    out: dict[str, list[dict]] = {k: [] for k in ("PF", "CP", "ES", "CR")}
    for r in ia:
        cls, item, label, arm = r["cls"], r["item"], r["label"], r["arm"]
        if cls not in out:
            continue
        partial = r["status"] == "partial"
        x = u(item, label)
        if cls in ("PF", "CP"):
            s = 0 if partial else int(x < P_ONE[arm])
            line = {"score": str(s), "score_num": float(s)}
        elif cls == "ES":
            if partial or x > 0.9:
                line = {"score": "inf", "score_num": None, "score_inf": True}
            else:
                e = round(x * 1.5 * (0.6 if arm == "E" else 1.0), 6)
                line = {"score": str(e), "score_num": e, "score_inf": False}
        else:
            s = 0.0 if partial else round(max(-0.5, x * (1.1 if arm == "E" else 0.8) - 0.1), 6)
            line = {"score": s, "score_num": s, "node": None, "member": None}
        rec = {"ts_utc": "2026-10-05T12:00:00.000000Z", "item": item, "label": label,
               "exit": None if partial else 0, "detail": {"synthetic": True}, **line}
        out[cls].append(rec)
    gdir = run_dir / "grading_results"
    gdir.mkdir(exist_ok=True)
    for cls, recs in out.items():
        lines = []
        if recs:  # an older, superseded line for the first item-arm: the later one must win
            old = dict(recs[0])
            old.update(ts_utc="2026-10-04T12:00:00.000000Z", score="999", score_num=999.0)
            lines.append(old)
        lines += recs
        if cls == "CR" and recs:  # a per-member unit line (node/member set): not an item-arm score
            lines.append({**recs[0], "node": "n1", "member": 2, "score": 123.0, "score_num": 123.0})
        (gdir / f"{cls}.jsonl").write_text("".join(json.dumps(x, sort_keys=True) + "\n" for x in lines))
        print(f"{cls}: {len(recs)} item-arms", file=sys.stderr)


if __name__ == "__main__":
    main(Path(sys.argv[1]))
