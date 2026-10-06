# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""CP oracle: score 1 iff the hidden test suite passes on the patched fixture copy.

printf '<nonce>\n' | uv run oracle.py --item CP-0001 --answer answer.json --workdir <patched fixture copy>
The first stdin line is the harness nonce (missing: exit 4, no verdict). The last line printed is the authenticated
verdict `EQV1 <nonce> {"item","score","detail"}`. Exit 0 scored, 2 malformed input, 4 no nonce.
Stdlib only, no network. Hidden material lives under oracle/ (never in a fixture).
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))

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


def die(msg):
    _emit({"item": None, "score": None, "detail": "malformed: " + msg}, 2)


def load_items():
    with open(os.path.join(HERE, "oracle", "items.json")) as f:
        return json.load(f)


def check_answer(path):
    try:
        with open(path) as f:
            ans = json.load(f)
    except (OSError, ValueError) as exc:
        die("answer is not readable JSON: %s" % exc)
    if not isinstance(ans, dict) or not isinstance(ans.get("answer"), str):
        die("answer.json must be an object with a string field `answer`")
    return ans


def run_hidden(item, workdir, timeout=60):
    mod = item["module"]
    if not os.path.isfile(os.path.join(workdir, mod + ".py")):
        return 0.0, "module file %s.py missing in workdir" % mod
    with tempfile.TemporaryDirectory() as tmp:
        dst = os.path.join(tmp, "w")
        shutil.copytree(workdir, dst, ignore=shutil.ignore_patterns("__pycache__", ".git"))
        hidden = "hidden_" + mod
        shutil.copyfile(os.path.join(HERE, "oracle", "hidden", mod + ".py"), os.path.join(dst, hidden + ".py"))
        try:
            p = _run_child([sys.executable, "-B", "-m", "unittest", hidden], cwd=dst, timeout=timeout)
        except subprocess.TimeoutExpired:
            return 0.0, "hidden tests timed out"
    out = p.stderr + p.stdout
    m = re.search(r"Ran (\d+) tests?", out)
    ran = int(m.group(1)) if m else 0
    if p.returncode == 0 and ran == item["hidden_count"]:
        return 1.0, "hidden tests passed (%d)" % ran
    return 0.0, "hidden tests failed: ran=%d rc=%d; %s" % (ran, p.returncode, out.strip().splitlines()[-1] if out.strip() else "")


def main():
    _begin()
    ap = argparse.ArgumentParser()
    ap.add_argument("--item", required=True)
    ap.add_argument("--answer", required=True)
    ap.add_argument("--workdir")
    a = ap.parse_args()
    items = load_items()
    if a.item not in items:
        die("unknown item " + a.item)
    check_answer(a.answer)
    if not a.workdir or not os.path.isdir(a.workdir):
        die("--workdir (patched fixture copy) is required for CP")
    score, detail = run_hidden(items[a.item], a.workdir)
    _emit({"item": a.item, "score": score, "detail": detail})


if __name__ == "__main__":
    main()
