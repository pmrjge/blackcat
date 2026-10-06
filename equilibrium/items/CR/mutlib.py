"""Shared engine for the CP / CR pool generators (stdlib only).

Token-level mutation operators over frozen base modules. Mutations never move
lines: every mutated token is replaced in place, so a seeded defect keeps the
line number of the original statement.
"""
import ast
import hashlib
import io
import os
import re
import subprocess
import sys
import tempfile
import tokenize
from concurrent.futures import ThreadPoolExecutor

HIDDEN_MARK = "# ---- HIDDEN ----"

CMP = {"<": "<=", "<=": "<", ">": ">=", ">=": ">"}
EQ = {"==": "!=", "!=": "=="}
ARITH = {"+": "-", "-": "+", "//": "/", "%": "//", "+=": "-=", "-=": "+="}
BOOL = {"and": "or", "or": "and"}
LIT = {"True": "False", "False": "True"}
FUNC = {"min": "max", "max": "min", "any": "all", "all": "any",
        "startswith": "endswith", "endswith": "startswith",
        "lstrip": "rstrip", "rstrip": "lstrip"}
EXC = {"ValueError": "KeyError", "KeyError": "ValueError", "IndexError": "ValueError",
       "TypeError": "ValueError"}

DESC = {
    "cmp": "wrong boundary: `{new}` where `{old}` is required (off-by-one at the boundary)",
    "eq": "inverted equality test: `{new}` where `{old}` is required",
    "arith": "wrong arithmetic operator: `{new}` where `{old}` is required",
    "bool": "wrong boolean connective: `{new}` where `{old}` is required",
    "lit": "inverted boolean literal: `{new}` where `{old}` is required",
    "func": "wrong function/method: `{new}` where `{old}` is required",
    "exc": "wrong exception type raised: `{new}` where `{old}` is required",
    "num": "off-by-one constant: `{new}` where `{old}` is required",
    "is": "inverted identity test: `{new}` where `{old}` is required",
    "not": "missing negation: `not` was removed from the condition",
    "in": "inverted membership test: `{new}` where `{old}` is required",
    "mutdef": "mutable default argument: `[]` default shared between calls where `None` is required",
}


def split_tests(text):
    """Return (public_text, hidden_text); hidden is the full file."""
    head, _, _ = text.partition(HIDDEN_MARK)
    return head.rstrip() + "\n", text.replace(HIDDEN_MARK + "\n", "")


def func_map(src):
    """line -> qualified name of the innermost function containing it."""
    tree = ast.parse(src)
    spans = []

    def walk(node, prefix):
        for ch in ast.iter_child_nodes(node):
            if isinstance(ch, ast.ClassDef):
                walk(ch, prefix + ch.name + ".")
            elif isinstance(ch, (ast.FunctionDef, ast.AsyncFunctionDef)):
                spans.append((ch.lineno, ch.end_lineno, prefix + ch.name))
                walk(ch, prefix + ch.name + ".")
    walk(tree, "")
    out = {}
    for lo, hi, name in sorted(spans, key=lambda s: s[1] - s[0], reverse=True):
        for ln in range(lo, hi + 1):
            out[ln] = name
    return out


def find_sites(src):
    """All single-token (or two-token) mutation sites of a module source."""
    lines = src.split("\n")
    toks = [t for t in tokenize.generate_tokens(io.StringIO(src).readline)
            if t.type not in (tokenize.NL, tokenize.NEWLINE, tokenize.COMMENT,
                              tokenize.INDENT, tokenize.DEDENT, tokenize.ENDMARKER)]
    fmap = func_map(src)
    sites = []
    # docstring lines are STRING tokens only, so numbers/names inside are never seen
    for i, t in enumerate(toks):
        row, col = t.start
        erow, ecol = t.end
        if row != erow:
            continue
        s = t.string
        prev = toks[i - 1].string if i else ""
        nxt = toks[i + 1].string if i + 1 < len(toks) else ""
        line_toks = [x.string for x in toks if x.start[0] == row]
        span = (row, col, ecol)
        cands = []
        if t.type == tokenize.OP:
            if s in CMP:
                cands.append(("cmp", s, CMP[s], span))
            elif s in EQ:
                cands.append(("eq", s, EQ[s], span))
            elif s in ARITH and not (s in "+-" and prev in ("(", ",", "=", "return", "[", ":")):
                cands.append(("arith", s, ARITH[s], span))
        elif t.type == tokenize.NAME:
            if s in BOOL:
                cands.append(("bool", s, BOOL[s], span))
            elif s in LIT:
                cands.append(("lit", s, LIT[s], span))
            elif s in FUNC and (nxt == "(" or s in ("startswith", "endswith", "lstrip", "rstrip")):
                cands.append(("func", s, FUNC[s], span))
            elif s in EXC and prev == "raise":
                cands.append(("exc", s, EXC[s], span))
            elif s == "is" and nxt == "not":
                e2 = toks[i + 1].end
                if e2[0] == row:
                    cands.append(("is", "is not", "is", (row, col, e2[1])))
            elif s == "is" and nxt != "not":
                cands.append(("is", "is", "is not", span))
            elif s == "not" and prev != "is" and nxt != "in":
                nt = toks[i + 1].start
                if nt[0] == row:
                    cands.append(("not", "not ", "", (row, col, nt[1])))
            elif s == "not" and nxt == "in" and "for" not in line_toks:
                e2 = toks[i + 1].end
                if e2[0] == row:
                    cands.append(("in", "not in", "in", (row, col, e2[1])))
            elif s == "in" and prev != "not" and "for" not in line_toks:
                cands.append(("in", "in", "not in", span))
            elif s == "None" and prev == "=" and line_toks and line_toks[0] == "def":
                cands.append(("mutdef", "None", "[]", span))
        elif t.type == tokenize.NUMBER and re.fullmatch(r"\d+", s):
            n = int(s)
            cands.append(("num", s, str(n + 1), span))
            if n > 0:
                cands.append(("num", s, str(n - 1), span))
        for kind, old, new, sp in cands:
            r, c0, c1 = sp
            if lines[r - 1][c0:c1] != old:
                continue
            sites.append({"kind": kind, "line": r, "col": c0, "end": c1, "old": old,
                          "new": new, "func": fmap.get(r, "<module>")})
    return sites


def apply(src, muts):
    """Apply non-overlapping mutations (list of sites) to the source."""
    lines = src.split("\n")
    for m in sorted(muts, key=lambda m: (m["line"], m["col"]), reverse=True):
        ln = lines[m["line"] - 1]
        assert ln[m["col"]:m["end"]] == m["old"], (m, ln)
        lines[m["line"] - 1] = ln[:m["col"]] + m["new"] + ln[m["end"]:]
    return "\n".join(lines)


def describe(m):
    return ("In `%s`: %s." % (m["func"], DESC[m["kind"]].format(old=m["old"].strip(), new=m["new"].strip() or "(removed)")))


def compiles(src):
    try:
        compile(src, "<m>", "exec")
        return True
    except (SyntaxError, ValueError):
        return False


_RES = re.compile(r"Ran (\d+) tests?")
_FAIL = re.compile(r"FAILED \((.*?)\)")


def run_unittest(cwd, module, timeout=4):
    """Run `python -B -m unittest module` in cwd.
    Returns dict(rc, ran, failures, errors, timeout, tail)."""
    try:
        p = subprocess.run([sys.executable, "-B", "-m", "unittest", module], cwd=cwd,
                           capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return {"rc": None, "ran": 0, "failures": 0, "errors": 0, "timeout": True, "tail": ""}
    out = p.stderr + p.stdout
    ran = _RES.search(out)
    fm = _FAIL.search(out)
    failures = errors = 0
    if fm:
        for part in fm.group(1).split(","):
            k, _, v = part.strip().partition("=")
            if k == "failures":
                failures = int(v)
            elif k == "errors":
                errors = int(v)
    return {"rc": p.returncode, "ran": int(ran.group(1)) if ran else 0, "failures": failures,
            "errors": errors, "timeout": False, "tail": out[-1500:]}


class Base:
    def __init__(self, srcdir, name):
        self.name = name
        self.src = open(os.path.join(srcdir, "bases", name + ".py")).read()
        full = open(os.path.join(srcdir, "tests", name + ".py")).read()
        self.public_test, self.hidden_test = split_tests(full)
        self.sites = find_sites(self.src)


def write_files(d, mapping):
    for rel, text in mapping.items():
        p = os.path.join(d, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w") as f:
            f.write(text)


def eval_module_sites(base, workers=8):
    """Run public and hidden tests for every compilable single-site mutant."""
    def one(site):
        msrc = apply(base.src, [site])
        if not compiles(msrc):
            return None
        with tempfile.TemporaryDirectory() as d:
            write_files(d, {base.name + ".py": msrc, "t_pub.py": base.public_test,
                            "t_hid.py": base.hidden_test})
            pub = run_unittest(d, "t_pub")
            hid = run_unittest(d, "t_hid")
        return dict(site, pub=pub, hid=hid)
    with ThreadPoolExecutor(workers) as ex:
        res = list(ex.map(one, base.sites))
    return [r for r in res if r]


def sha256_file(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        h.update(f.read())
    return h.hexdigest()


HASH_TOP = ("manifest.jsonl", "schema.json", "oracle.py", "selftest.sh", "prove_pool.py", "mutlib.py")


def write_pool_hashes(root, cls):
    """pool.sha256: `shasum -a 256` format lines over the frozen pool files."""
    files = []
    for name in HASH_TOP + ("gen_%s.py" % cls.lower(),):
        if os.path.isfile(os.path.join(root, name)):
            files.append(name)
    for sub in ("oracle", "fixtures"):
        for dp, dn, fn in os.walk(os.path.join(root, sub)):
            dn[:] = [d for d in dn if d != "__pycache__"]
            for f in fn:
                if f.endswith(".pyc") or f == ".DS_Store":
                    continue
                files.append(os.path.relpath(os.path.join(dp, f), root))
    with open(os.path.join(root, "pool.sha256"), "w") as out:
        for rel in sorted(set(files)):
            out.write("%s  %s\n" % (sha256_file(os.path.join(root, rel)), rel))
