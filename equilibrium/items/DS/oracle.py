# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Pairwise oracle for the long-form classes DS and OE (byte-identical in both folders). Stdlib only; no network.

Score (COMPARE_eq §2, DS/OE): blinded pairwise preference judged twice, A/B swapped, in separate grader sessions.
The pair file names no arm: {"first": <arm output or null>, "second": <arm output or null>}, where "first" is the
first-named arm of the contrast (the harness keeps that mapping; nothing of it reaches the grader).
  score  1 = first preferred in both orders (win), 0 = orders disagree or "equal" (tie), -1 = second preferred in both.
  An invalid or missing side loses to a valid one without grading; two invalid sides tie.

  uv run oracle.py --item DS-0001 --answer pair.json                      exit 0 scored mechanically, 3 needs grade
  uv run oracle.py --item DS-0001 --answer pair.json --grader-input g.json   write 2 blinded records (order 1, 2)
  uv run oracle.py --item DS-0001 --answer pair.json --grade grades.json      finalise (exit 0)
  uv run oracle.py --check-blind g.json                                   exit 2 if an arm/member token is present
  uv run oracle.py --audit                                                pool consistency checks (exit 1 on defect)
Arm output: {"answer": "<markdown>", "evidence": [...], "confidence": x}; only `answer` reaches the grader.
Grades file: JSON list (or {"grades": [...]}) of {"rid": ..., "verdict": "X"|"Y"|"equal"}, one per order record.
Unparsable JSON, an unknown item or a missing grade: exit 2.
"""
import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent

# ---- blinding (identical in RS, DS, OE oracles) ----
BLIND_PATTERNS = [
    r"\b(?:PF|CP|CR|RS|ES|DS|OE)-(?:\d{4}|DEV\d)\s+[pq]\d\s+\S+",      # prompt head line <ITEM> <label> <role>
    r"(?<![A-Za-z0-9_])[pq][1-59](?![A-Za-z0-9_])",                    # arm labels p1-p5, p9, q1-q5, q9
    r"(?<![A-Za-z0-9_])m\d{1,2}/\d{1,2}(?![0-9])",                     # member role m<i>/<N>
    r"(?i)\bmember\s*#?\s*\d+\b",                                      # "member 3"
    r"\bS\*",                                                          # arm name S*
    r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b",  # session ids
    r"\ba[0-9a-f]{16}\b",                                              # agent ids
]
BLIND_RE = [re.compile(p) for p in BLIND_PATTERNS]


def redact(text: str) -> tuple[str, int]:
    n = 0
    for rx in BLIND_RE:
        text, k = rx.subn("[redacted]", text)
        n += k
    return text, n


def blind_hits(text: str) -> list[str]:
    return [m.group(0) for rx in BLIND_RE for m in rx.finditer(text)]


def norm_ws(text: str) -> str:
    lines = [ln.rstrip() for ln in text.replace("\r\n", "\n").split("\n")]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def jsonl(path):
    with open(path, encoding="utf-8") as fh:
        return [json.loads(ln) for ln in fh if ln.strip()]


def item_and_crit(iid):
    m = next((x for x in jsonl(HERE / "manifest.jsonl") if x["id"] == iid), None)
    c = next((x for x in jsonl(HERE / "oracle" / "criteria.jsonl") if x["id"] == iid), None)
    return m, c


def fail_input(msg):
    print(json.dumps({"item": getattr(ARGS, "item", None), "score": None, "detail": msg}))
    sys.exit(2)


def load_json(path):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, json.JSONDecodeError) as e:
        fail_input(f"cannot read JSON {path}: {e}")


def side_text(out):
    """Return the normalised answer text, or None if missing / schema-invalid / empty."""
    if not isinstance(out, dict):
        return None
    a = out.get("answer")
    if not isinstance(a, str) or not a.strip():
        return None
    return norm_ws(a)


def words(t):
    return len(t.split()) if t else 0


def task_text(m):
    """The task as S* sees it: prompt, then the text segments as a bulleted list in canonical order."""
    reqs = "\n".join(f"- {s['text']}" for s in m["segments"])
    return f"{m['prompt']}\n\n{reqs}"


def records(iid, m, crit, a, b):
    """Two blinded records: order 1 shows (X=first, Y=second), order 2 (X=second, Y=first)."""
    ra, na = redact(a)
    rb, nb = redact(b)
    out = []
    for order, (x, y) in ((1, (ra, rb)), (2, (rb, ra))):
        rid = hashlib.sha256(json.dumps([iid, order, x, y], ensure_ascii=False).encode()).hexdigest()[:16]
        out.append({"rid": rid, "item": iid, "class": m["class"], "order": order, "task": task_text(m),
                    "word_limit": crit["word_limit"], "criteria": crit["criteria"],
                    "response_X": x, "response_Y": y, "vocabulary": ["X", "Y", "equal"]})
    hits = blind_hits(json.dumps(out, ensure_ascii=False))
    if hits:
        fail_input(f"blinding check failed after redaction: {hits[:5]}")
    return out, na + nb


def emit(iid, score, detail, code=0):
    outcome = {1: "win", 0: "tie", -1: "loss", None: None}[score]
    print(json.dumps({"item": iid, "score": score, "detail": dict(detail, outcome=outcome)}, ensure_ascii=False))
    sys.exit(code)


def audit():
    man = jsonl(HERE / "manifest.jsonl")
    crit = {c["id"]: c for c in jsonl(HERE / "oracle" / "criteria.jsonl")}
    bad = []
    ids = [m["id"] for m in man]
    if len(ids) != len(set(ids)) or set(ids) != set(crit):
        bad.append("manifest and criteria disagree on ids")
    for m in man:
        c = crit.get(m["id"])
        if not c or not c["criteria"] or not c["word_limit"]:
            bad.append(f"{m['id']}: criteria or word limit missing")
            continue
        if len(m["segments"]) < 2 or any(not s.get("text") for s in m["segments"]):
            bad.append(f"{m['id']}: needs >= 2 text segments")
        if m["decisive_segment"] is not None or m["fixture"] is not None:
            bad.append(f"{m['id']}: long-form items have no fixture and no decisive segment")
        if "oracle" in m["prompt"] or blind_hits(task_text(m)) or blind_hits(json.dumps(c)):
            bad.append(f"{m['id']}: prompt/criteria contain an oracle path or a blind token")
        records(m["id"], m, c, "x", "y")
    print(json.dumps({"audit_items": len(man), "defects": bad[:20], "n_defects": len(bad)}))
    sys.exit(1 if bad else 0)


def main():
    global ARGS
    ap = argparse.ArgumentParser()
    ap.add_argument("--item")
    ap.add_argument("--answer")
    ap.add_argument("--workdir")  # accepted for interface uniformity; unused
    ap.add_argument("--grader-input")
    ap.add_argument("--grade")
    ap.add_argument("--check-blind")
    ap.add_argument("--audit", action="store_true")
    ARGS = ap.parse_args()
    if ARGS.audit:
        audit()
    if ARGS.check_blind:
        hits = blind_hits(Path(ARGS.check_blind).read_text(encoding="utf-8"))
        print(json.dumps({"item": None, "score": None, "detail": {"blind_hits": hits[:10]}}))
        sys.exit(2 if hits else 0)
    if not ARGS.item or not ARGS.answer:
        fail_input("--item and --answer are required")
    m, crit = item_and_crit(ARGS.item)
    if m is None or crit is None:
        fail_input(f"unknown item {ARGS.item}")
    pair = load_json(ARGS.answer)
    if not isinstance(pair, dict) or "first" not in pair or "second" not in pair:
        fail_input("pair file must have keys 'first' and 'second'")
    a, b = side_text(pair["first"]), side_text(pair["second"])
    wa, wb = words(a), words(b)
    detail = {"valid_first": a is not None, "valid_second": b is not None, "words_first": wa, "words_second": wb,
              "length_ratio": round(wa / wb, 3) if wa and wb else None, "word_limit": crit["word_limit"]}
    if a is None or b is None:
        emit(ARGS.item, 0 if a is None and b is None else (1 if b is None else -1),
             dict(detail, mechanical="invalid or missing side"))
    recs, n = records(ARGS.item, m, crit, a, b)
    detail.update(rids=[r["rid"] for r in recs], redactions=n)
    if ARGS.grader_input:
        Path(ARGS.grader_input).write_text(json.dumps(recs, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        detail["grader_input"] = ARGS.grader_input
    if ARGS.grade:
        g = load_json(ARGS.grade)
        if isinstance(g, dict):
            g = g.get("grades", [g])
        byrid = {x.get("rid"): x.get("verdict") for x in g if isinstance(x, dict)} if isinstance(g, list) else {}
        v1, v2 = byrid.get(recs[0]["rid"]), byrid.get(recs[1]["rid"])
        if v1 not in ("X", "Y", "equal") or v2 not in ("X", "Y", "equal"):
            fail_input(f"grades for both rids {detail['rids']} with verdict X|Y|equal are required")
        p1 = {"X": "first", "Y": "second"}.get(v1)
        p2 = {"X": "second", "Y": "first"}.get(v2)
        score = 1 if p1 == p2 == "first" else -1 if p1 == p2 == "second" else 0
        emit(ARGS.item, score, dict(detail, verdict_order1=v1, verdict_order2=v2, orders_agree=p1 == p2))
    emit(ARGS.item, None, dict(detail, needs_grade=True), 0 if ARGS.grader_input else 3)


if __name__ == "__main__":
    main()
