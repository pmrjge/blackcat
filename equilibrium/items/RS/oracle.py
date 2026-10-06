# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""RS oracle (closed-book claim verification over fixtures/corpus). Stdlib only; no network.

Score (COMPARE_eq §2, RS): 1 iff the label equals the key, the correction value matches the key when the key is
REFUTED, and the blinded grader marks the rationale `pass` against the item rubric; else 0.

  uv run oracle.py --item RS-0001 --answer out.json                 mechanical part; exit 0 scored (0), 3 needs grade
  uv run oracle.py --item RS-0001 --answer out.json --grader-input g.json   write the blinded grader record
  uv run oracle.py --item RS-0001 --answer out.json --grade grades.json      finalise (exit 0)
  uv run oracle.py --check-blind g.json                             exit 2 if an arm/member token is present
  uv run oracle.py --audit                                          pool consistency checks (exit 1 on a defect)
Answer file: the arm's JSON output ({"answer": {...}, "evidence": [...], "confidence": x}) or {"answer": null} for a
missing answer. Unparsable JSON or an unknown item: exit 2. Parsed but schema-invalid answer: score 0 (data).
Grades file: a JSON list (or {"grades": [...]}) of {"rid": <rid from the grader input>, "verdict": "pass"|"fail"}.
"""
import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
LABELS = ("SUPPORTED", "REFUTED", "NOT_IN_CORPUS")

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


# ---- pool access ----
def jsonl(path):
    with open(path, encoding="utf-8") as fh:
        return [json.loads(ln) for ln in fh if ln.strip()]


def item_and_key(iid):
    m = next((x for x in jsonl(HERE / "manifest.jsonl") if x["id"] == iid), None)
    k = next((x for x in jsonl(HERE / "oracle" / "keys.jsonl") if x["id"] == iid), None)
    return m, k


# ---- value matching ----
NUM_RE = re.compile(r"[-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?\s*(?:million|[MkK])?(?![A-Za-z0-9])")


def parse_num(s: str):
    s = re.sub(r"(?<=\d)[,_](?=\d{3}(?!\d))", "", s)
    m = NUM_RE.search(s)
    if not m:
        return None
    t = m.group(0).strip()
    mult = 1.0
    if t.endswith("million"):
        mult, t = 1e6, t[:-7].strip()
    elif t[-1] in "MkK":
        mult, t = (1e6 if t[-1] == "M" else 1e3), t[:-1].strip()
    return float(t) * mult


def snorm(s: str) -> str:
    return re.sub(r"[^a-z0-9.+\-_]", "", s.casefold())


def whole(alias: str, text: str) -> bool:
    return re.search(r"(?<![a-z0-9])" + re.escape(alias.casefold()) + r"(?![a-z0-9])", text.casefold()) is not None


def value_matches(given: str, key: dict) -> bool:
    if not isinstance(given, str) or not given.strip():
        return False
    if key["value_kind"] == "num":
        a, b = parse_num(given), parse_num(key["value"])
        return a is not None and abs(a - b) <= 1e-9 + 1e-6 * abs(b)
    aliases = [key["value"]] + list(key.get("aliases") or [])
    if any(snorm(given) == snorm(a) for a in aliases):
        return True
    false = key.get("claimed_false_value")
    return any(whole(a, given) for a in aliases) and not (false and whole(false, given))


# ---- answer handling ----
def load_json(path):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, json.JSONDecodeError) as e:
        fail_input(f"cannot read JSON {path}: {e}")


def fail_input(msg):
    print(json.dumps({"item": ARGS.item if "ARGS" in globals() else None, "score": None, "detail": msg}))
    sys.exit(2)


def extract(data):
    """Return (answer dict or None, reason)."""
    ans = data.get("answer") if isinstance(data, dict) else None
    if ans is None:
        return None, "missing answer"
    if not isinstance(ans, dict):
        return None, "schema-invalid: answer is not an object"
    if ans.get("label") not in LABELS:
        return None, "schema-invalid: label"
    for f in ("value", "rationale"):
        if f in ans and not isinstance(ans[f], str):
            return None, f"schema-invalid: {f}"
    return {"label": ans["label"], "value": ans.get("value") or "", "rationale": ans.get("rationale") or ""}, "ok"


def mechanical(ans, key):
    if ans is None:
        return False, "no valid answer"
    if ans["label"] != key["label"]:
        return False, f"label {ans['label']} != key {key['label']}"
    if key["label"] == "REFUTED" and not value_matches(ans["value"], key):
        return False, f"correction value {ans['value']!r} does not match the key"
    return True, "label (and value) match the key"


def rubric(key):
    p = key["decisive_path"]
    if key["label"] == "SUPPORTED":
        return (f"PASS iff the rationale treats the claim as supported and identifies the deciding record ({p}) or "
                f"its content, and asserts nothing that contradicts the reference excerpt. FAIL otherwise, including a "
                f"rationale that rests on a different record (another batch or variant) or on no record.")
    if key["label"] == "REFUTED":
        return (f"PASS iff the rationale treats the claim as contradicted, identifies the deciding record ({p}) or its "
                f"content, and gives the correct value {key['value']!r} (not {key['claimed_false_value']!r}); nothing "
                f"may contradict the reference excerpt. FAIL otherwise.")
    return ("PASS iff the rationale says that no corpus record states or contradicts the claim (reason: "
            f"{key['reason']}) and does not invent a value or a record. FAIL if it treats any record as settling "
            "the claim.")


def rid_of(iid, ans):
    blob = json.dumps([iid, ans], sort_keys=True, ensure_ascii=False) if ans else json.dumps([iid, None])
    return hashlib.sha256(blob.encode()).hexdigest()[:16]


def grader_record(iid, ans, key):
    shown, n = ({"label": None, "value": "", "rationale": "(no answer)"}, 0) if ans is None else (None, 0)
    if ans is not None:
        shown = {}
        for f in ("label", "value", "rationale"):
            t, k = redact(norm_ws(ans[f]))
            shown[f], n = t, n + k
    rec = {"rid": rid_of(iid, ans), "item": iid, "class": "RS", "claim": key["claim"], "answer": shown,
           "key": {"label": key["label"], "value": key["value"] if key["label"] == "REFUTED" else None},
           "rubric": rubric(key), "reference_excerpt": key["reference_excerpt"] or "(no record: " + key["reason"] + ")",
           "vocabulary": ["pass", "fail"]}
    hits = blind_hits(json.dumps(rec, ensure_ascii=False))
    if hits:
        fail_input(f"blinding check failed after redaction: {hits[:5]}")
    return rec, n


def load_grades(path):
    g = load_json(path)
    if isinstance(g, dict):
        g = g.get("grades", [g])
    if not isinstance(g, list):
        fail_input("grades file must be a list of {rid, verdict}")
    return {x.get("rid"): x for x in g if isinstance(x, dict)}


def emit(iid, score, detail, code=0):
    print(json.dumps({"item": iid, "score": score, "detail": detail}, ensure_ascii=False))
    sys.exit(code)


def audit():
    man = jsonl(HERE / "manifest.jsonl")
    keys = {k["id"]: k for k in jsonl(HERE / "oracle" / "keys.jsonl")}
    bad = []
    ids = [m["id"] for m in man]
    if len(ids) != len(set(ids)) or set(ids) != set(keys):
        bad.append("manifest and keys disagree on ids")
    for m in man:
        k = keys[m["id"]]
        corpus = HERE / m["fixture"]
        paths = [s["path"] for s in m["segments"]]
        if sorted(paths) != sorted(str(p.relative_to(corpus)) for p in corpus.rglob("*.md")):
            bad.append(f"{m['id']}: segments are not exactly the corpus files")
        if k["decisive_path"] is not None:
            if paths[m["decisive_segment"]] != k["decisive_path"]:
                bad.append(f"{m['id']}: decisive_segment index wrong")
        elif m["decisive_segment"] is not None:
            bad.append(f"{m['id']}: decisive_segment should be null")
        if "oracle" in m["prompt"] or blind_hits(m["prompt"]):
            bad.append(f"{m['id']}: prompt contains oracle path or blind token")
        if k["label"] == "REFUTED":
            if not value_matches(k["value"], k) or value_matches(k["claimed_false_value"], k):
                bad.append(f"{m['id']}: key value does not discriminate")
        grader_record(m["id"], {"label": "SUPPORTED", "value": "", "rationale": "x"}, k)
    print(json.dumps({"audit_items": len(man), "defects": bad[:20], "n_defects": len(bad)}))
    sys.exit(1 if bad else 0)


def main():
    global ARGS
    ap = argparse.ArgumentParser()
    ap.add_argument("--item")
    ap.add_argument("--answer")
    ap.add_argument("--workdir")  # accepted for interface uniformity; unused by RS
    ap.add_argument("--grader-input")
    ap.add_argument("--grade")
    ap.add_argument("--check-blind")
    ap.add_argument("--audit", action="store_true")
    ARGS = ap.parse_args()
    if ARGS.audit:
        audit()
    if ARGS.check_blind:
        hits = blind_hits(Path(ARGS.check_blind).read_text(encoding="utf-8"))
        emit(None, None, {"blind_hits": hits[:10]}, 2 if hits else 0)
    if not ARGS.item or not ARGS.answer:
        fail_input("--item and --answer are required")
    m, key = item_and_key(ARGS.item)
    if m is None or key is None:
        fail_input(f"unknown item {ARGS.item}")
    ans, why = extract(load_json(ARGS.answer))
    ok, mdetail = mechanical(ans, key)
    detail = {"answer_status": why, "mechanical": ok, "mechanical_detail": mdetail, "rid": rid_of(ARGS.item, ans)}
    if ARGS.grader_input:
        rec, n = grader_record(ARGS.item, ans, key)
        Path(ARGS.grader_input).write_text(json.dumps(rec, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        detail.update(grader_input=ARGS.grader_input, redactions=n)
    if ARGS.grade:
        g = load_grades(ARGS.grade).get(detail["rid"])
        if g is None or g.get("verdict") not in ("pass", "fail"):
            fail_input(f"no pass|fail grade for rid {detail['rid']} in {ARGS.grade}")
        detail["grader_verdict"] = g["verdict"]
        emit(ARGS.item, int(ok and g["verdict"] == "pass"), detail)
    if not ok:
        emit(ARGS.item, 0, detail)
    if ARGS.grader_input:
        emit(ARGS.item, None, dict(detail, needs_grade=True), 0)
    emit(ARGS.item, None, dict(detail, needs_grade=True), 3)


if __name__ == "__main__":
    main()
