# /// script
# requires-python = ">=3.11"
# ///
"""PF oracle (COMPARE_eq §2): score 1 iff the answer's Lean 4 file passes check_lean.sh for the item, else 0.

  printf '<nonce>\n' | uv run oracle.py --item PF-0001 --answer answer.json [--workdir DIR]

The first stdin line is the harness nonce (missing: exit 4, no verdict). The last line printed is the authenticated
verdict `EQV1 <nonce> {"item","score","detail"}` (exit codes below are unchanged; exit 4 = no nonce).

answer.json is the arm output object; its `answer` string is the complete Lean file. The verdict object is
{"item", "score", "detail"}. Exit 0 when scored (a missing/empty/non-string `answer` scores 0, schema-invalid output
scores 0 per COMPARE_eq §2), 2 on malformed input (unknown item, unreadable or non-object JSON), 3 if the Lean
environment itself is unusable (check_lean.sh usage error). --workdir is accepted for interface uniformity and unused:
PF has no patched fixture; the oracle always checks with its own check_lean.sh and statement.txt, never the arm's copy.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent

# --- authenticated verdict channel (security finding F1) ---------------------------------------------------------
# The harness sends a fresh nonce on the first stdin line; the only line it trusts on stdout is
# `EQV1 <nonce> <json>`, printed here as the very last act. Nothing the answer runs can learn the nonce: it is read
# from stdin before anything else, children get stdin=DEVNULL and their own session, and (Linux) the process is made
# non-dumpable so a same-uid child cannot ptrace or read /proc/<pid>/mem.
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
    sys.stdout.write("EQV1 %s %s\n" % (NONCE, json.dumps(obj, ensure_ascii=True)))
    sys.stdout.flush()
    sys.exit(code)


def _run_child(argv, cwd=None, timeout=None):
    """Child with no stdin and its own session; the whole group is killed when it finishes or times out."""
    p = subprocess.Popen(argv, cwd=cwd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                         text=True, start_new_session=True)
    try:
        out, err = p.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        _killpg(p)
        p.communicate()
        raise
    finally:
        _killpg(p)
    return subprocess.CompletedProcess(argv, p.returncode, out, err)


def _killpg(p):
    try:
        os.killpg(p.pid, 9)
    except OSError:
        pass


def emit(item, score, detail, code):
    _emit({"item": item, "score": score, "detail": detail}, code)


def main():
    _begin()
    ap = argparse.ArgumentParser()
    ap.add_argument("--item", required=True)
    ap.add_argument("--answer", required=True)
    ap.add_argument("--workdir")
    a = ap.parse_args()
    items = {}
    for line in (HERE / "manifest.jsonl").read_text().splitlines():
        if line.strip():
            obj = json.loads(line)
            items[obj["id"]] = obj
    if a.item not in items:
        emit(a.item, None, "unknown item", 2)
    try:
        out = json.loads(Path(a.answer).read_text())
    except Exception as exc:  # noqa: BLE001
        emit(a.item, None, f"malformed answer file: {exc}", 2)
    if not isinstance(out, dict):
        emit(a.item, None, "malformed answer file: not a JSON object", 2)
    ans = out.get("answer")
    if not isinstance(ans, str) or not ans.strip():
        emit(a.item, 0, "missing, empty or non-string answer", 0)
    stmt = HERE / items[a.item]["fixture"] / "statement.txt"
    with tempfile.TemporaryDirectory(prefix="pforacle.") as td:
        p = Path(td) / "Answer.lean"
        p.write_text(ans)
        r = _run_child(["bash", str(HERE / "check_lean.sh"), str(p), str(stmt)])
    lines = (r.stdout or "").strip().splitlines()
    verdict = lines[-1] if lines else ""
    if r.returncode == 0 and verdict == "PASS":
        emit(a.item, 1, "PASS", 0)
    if r.returncode == 1 and verdict.startswith("FAIL"):
        emit(a.item, 0, verdict[:800], 0)
    emit(a.item, None, f"checker error rc={r.returncode}: {(r.stderr or verdict)[-400:]}", 3)


if __name__ == "__main__":
    main()
