# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""CR oracle: recall of seeded bugs minus 0.5 x false findings, over #seeded (COMPARE_eq 2).

  printf '<nonce>\n' | uv run oracle.py --item CR-0001 --answer answer.json [--workdir DIR]
  uv run oracle.py --item CR-0001 --answer answer.json --grader-input grader_in.json
  uv run oracle.py --item CR-0001 --answer answer.json --grade grader_out.json

answer.json: {"answer": [{"file": "x.py", "line": 12, "claim": "..."}], "evidence": [...], "confidence": 0.7}
A finding matches a seeded bug iff same file and |line - bug line| <= 3 AND the grader does not mark the claim
false (verdicts true | false | unclear; unclear counts as not false, COMPARE_eq 9). Findings that match no bug
are false iff the grader marks them false. Duplicate findings (same file, line, claim) count once; several
findings on one bug count that bug once.

--grader-input writes the blinded grader input (no arm label, no member ids) as the list of records of
graders/grader_brief_CR.md: `rid` ("f<finding index>"), `type` (match | unmatched), `finding` {file,line,claim},
`seeded_bug` {file,line,description} (match only), `code_excerpt` (cited line +-6, numbered). Duplicates are omitted.
--grade finalises the score from the brief's output, a list [{"rid": "f0", "verdict": "true", "note": "..."}]
(the older {"verdicts": [{"id": 0, "verdict": "true"}]} is also accepted).
Without either flag the score is PROVISIONAL (location match only; every unmatched finding counts as false).
--workdir is accepted for interface symmetry and ignored (CR is scored from the answer only).
The first stdin line is the harness nonce (missing: exit 4, no verdict) in every mode; the last line printed is the
authenticated verdict `EQV1 <nonce> {"item","score","detail"}`.
Exit 0 scored, 2 malformed input, 4 no nonce. Stdlib only, no network, no children.
"""
import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TOL = 3

# --- authenticated verdict channel (security finding F1) ---------------------------------------------------------
# The harness sends a fresh nonce on the first stdin line; the only line it trusts on stdout is
# `EQV1 <nonce> <json>`, printed here as the very last act. CR runs no answer code and starts no children; the
# nonce discipline is kept so every oracle speaks the same protocol (and the process is non-dumpable on Linux).
NONCE = None


def _begin():
    """Read the nonce first; no nonce, no verdict (exit 4, nothing on stdout)."""
    global NONCE
    line = sys.stdin.readline()
    nonce = line.strip()
    if not nonce or len(nonce.split()) != 1:
        sys.stderr.write("oracle: missing or malformed nonce on the first stdin line\n")
        sys.exit(4)
    NONCE = nonce
    if sys.platform.startswith("linux"):
        try:
            import ctypes
            ctypes.CDLL(None).prctl(4, 0, 0, 0, 0)  # PR_SET_DUMPABLE = 0
        except Exception:  # noqa: BLE001  (best effort; the container is the real boundary)
            pass


def _emit(obj, code=0):
    """The last act: one authenticated verdict line, then exit."""
    sys.stdout.flush()
    sys.stdout.write("EQV1 %s %s\n" % (NONCE, json.dumps(obj, ensure_ascii=True, sort_keys=True)))
    sys.stdout.flush()
    sys.exit(code)


def die(msg):
    _emit({"item": None, "score": None, "detail": "malformed: " + msg}, 2)


def load_json(path, what):
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError) as exc:
        die("%s is not readable JSON: %s" % (what, exc))


def norm_file(p):
    p = p.replace("\\", "/")
    while p.startswith("./"):
        p = p[2:]
    return p


def parse_findings(ans):
    if not isinstance(ans, dict) or not isinstance(ans.get("answer"), list):
        die("answer.json must be an object whose `answer` is an array of findings")
    out = []
    for i, f in enumerate(ans["answer"]):
        if (not isinstance(f, dict) or not isinstance(f.get("file"), str) or isinstance(f.get("line"), bool)
                or not isinstance(f.get("line"), int) or not isinstance(f.get("claim"), str)):
            die("finding %d needs string file, integer line, string claim" % i)
        out.append({"file": norm_file(f["file"]), "line": f["line"], "claim": f["claim"].strip()})
    return out


def dedupe(findings):
    seen, keep = set(), []
    for i, f in enumerate(findings):
        key = (f["file"], f["line"], f["claim"].lower())
        if key not in seen:
            seen.add(key)
            keep.append(i)
    return keep


def match_bug(f, bugs):
    best = None
    for j, b in enumerate(bugs):
        if (f["file"] == b["file"] or f["file"].endswith("/" + b["file"])) and abs(f["line"] - b["line"]) <= TOL:
            d = abs(f["line"] - b["line"])
            if best is None or d < best[0]:
                best = (d, j)
    return None if best is None else best[1]


def compute(findings, bugs, verdicts):
    keep = dedupe(findings)
    confirmed, false, per = set(), 0, []
    for i in keep:
        f = findings[i]
        j = match_bug(f, bugs)
        v = None if verdicts is None else verdicts[i]
        if v is None:  # provisional
            v = "true" if j is not None else "false"
        if j is not None:
            if v != "false":
                confirmed.add(j)
            else:
                false += 1
        elif v == "false":
            false += 1
        per.append({"id": i, "bug": j, "verdict": v})
    n = len(bugs)
    recall = len(confirmed) / n
    return {"score": round(recall - 0.5 * false / n, 6), "recall": round(recall, 6), "false_findings": false,
            "n_seeded": n, "findings": len(findings), "per_finding": per}


def grader_input(item_id, item, findings, bugs):
    """Blinded grader records (graders/grader_brief_CR.md): a JSON list; `match` records carry the seeded bug."""
    fx = os.path.join(HERE, "fixtures", item_id)
    cache = {}
    out = []
    for i in dedupe(findings):
        f = findings[i]
        j = match_bug(f, bugs)
        path = os.path.join(fx, f["file"])
        if f["file"] not in cache:
            cache[f["file"]] = open(path).read().split("\n") if os.path.isfile(path) else []
        src = cache[f["file"]]
        lo, hi = max(1, f["line"] - 6), min(len(src), f["line"] + 6)
        excerpt = "\n".join("%4d  %s" % (n, src[n - 1]) for n in range(lo, hi + 1))
        rec = {"rid": "f%d" % i, "type": "match" if j is not None else "unmatched",
               "finding": {"file": f["file"], "line": f["line"], "claim": f["claim"]}}
        if j is not None:
            rec["seeded_bug"] = {"file": bugs[j]["file"], "line": bugs[j]["line"], "description": bugs[j]["claim"]}
        rec["code_excerpt"] = excerpt
        out.append(rec)
    return out


def main():
    _begin()
    ap = argparse.ArgumentParser()
    ap.add_argument("--item", required=True)
    ap.add_argument("--answer", required=True)
    ap.add_argument("--workdir")
    ap.add_argument("--grader-input")
    ap.add_argument("--grade")
    a = ap.parse_args()
    items = load_json(os.path.join(HERE, "oracle", "items.json"), "items.json")
    if a.item not in items:
        die("unknown item " + a.item)
    item = items[a.item]
    bugs = item["bugs"]
    findings = parse_findings(load_json(a.answer, "answer"))
    if a.grader_input:
        with open(a.grader_input, "w") as f:
            json.dump(grader_input(a.item, item, findings, bugs), f, indent=1)
        _emit({"item": a.item, "score": None, "detail": "grader input written (%d findings)" % len(findings)})
    verdicts = None
    provisional = True
    if a.grade:
        g = load_json(a.grade, "grader output")
        vs = g.get("verdicts") if isinstance(g, dict) else g  # brief format: a list of {"rid","verdict","note"}
        if not isinstance(vs, list):
            die("grader output must be a list of {rid, verdict} (or {\"verdicts\": [...]})")
        vs = [dict(v, id=int(str(v["rid"]).lstrip("f"))) if isinstance(v, dict) and "rid" in v and str(v["rid"]).lstrip("f").isdigit() else v for v in vs]
        verdicts = {}
        for v in vs:
            if not isinstance(v, dict) or v.get("verdict") not in ("true", "false", "unclear") or not isinstance(v.get("id"), int):
                die("bad verdict entry")
            verdicts[v["id"]] = v["verdict"]
        keep = dedupe(findings)
        if any(i not in verdicts for i in keep):
            die("missing verdict for a finding")
        verdicts = [verdicts.get(i) for i in range(len(findings))]
        provisional = False
    res = compute(findings, bugs, verdicts)
    detail = dict(res)
    detail.pop("score")
    detail["provisional"] = provisional
    _emit({"item": a.item, "score": res["score"], "detail": detail})


if __name__ == "__main__":
    main()
