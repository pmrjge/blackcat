# /// script
# requires-python = ">=3.11"
# dependencies = ["numpy==2.5.3"]
# ///
"""OE pool generator: one open-ended item per (topic, kind) from topics.py; kinds explain, compare, critique.

Outputs (class folder): manifest.jsonl, oracle/criteria.jsonl, selftest/*.json.
Segment order: numpy.random.default_rng(3725927731) (seed eq|items), one permutation per item in manifest order.
Item order: content RNG 20261004 ^ int(sha256("eq|items|OE|gen")[:8], 16) permutes the (topic, kind) list.
Run: uv run --offline --script gen_oe.py
"""
import hashlib
import json
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
CLS_DIR = HERE.parent
sys.path.insert(0, str(HERE))
from topics import DEV, T  # noqa: E402

SEED_ITEMS = 3725927731
SEED_GEN = 20261004 ^ int(hashlib.sha256(b"eq|items|OE|gen").hexdigest()[:8], 16)
LIMIT = {"explain": 400, "compare": 500, "critique": 450}
SEGS = {
    "explain": ["Include one concrete worked example.", "Name one common misconception and correct it.",
                "Use at most one equation unless the audience needs more.", "End with a one-sentence takeaway."],
    "compare": ["State the criteria you compare on.", "Give at least one situation where each option is the better "
                "choice.", "Quantify at least one difference (an order of magnitude is enough).",
                "End with a recommendation and what would change it."],
    "critique": ["List each error separately, with the reason it is wrong.", "Distinguish outright errors from mere "
                 "imprecision.", "Say which parts, if any, are correct; do not invent errors.",
                 "Give a corrected passage of similar length."],
}


def prompt(t, k):
    tail = (f"\n\nLimits: at most {LIMIT[k]} words of Markdown in `answer`; `evidence` may stay empty.\n\n"
            "Requirements (all apply):")
    if k == "explain":
        return f"Explanation task.\n\nExplain {t['concept']} to {t['audience']}." + tail
    if k == "compare":
        return f"Analysis task.\n\nCompare {t['a']} and {t['b']} {t['ctx']}, for {t['audience']}." + tail
    return (f"Critique task.\n\nThe passage below was written for {t['audience']}. Identify what is wrong or "
            f"misleading in it, explain why, and give a corrected version.\n\nPassage: \"{t['passage']}\"" + tail)


def criteria(t, k):
    lim = (f"Stays within {LIMIT[k]} words; extra length is not a merit, and padding counts against an answer.")
    facts = [f.split(" [passage:")[0] for f in t["facts"]]
    if k == "explain":
        return (["The explanation is correct and pitched at the stated audience; the example is concrete and correct; "
                 "the misconception is real and correctly addressed."]
                + [f"A strong answer gets this right: {f}" for f in facts]
                + ["Every listed requirement is met.", lim])
    if k == "compare":
        return (["The comparison criteria fit the stated context; both options are described accurately."]
                + [f"Relevant correct background (use where it bears on the comparison): {f}" for f in facts]
                + ["The recommendation follows from the analysis and states what would change it; every listed "
                   "requirement is met.", lim])
    return ([f"Identifies and correctly explains this error: {f}" for f in t["facts"]]
            + ["Invents no errors in correct statements; the corrected passage is accurate and of similar length; "
               "every listed requirement is met.", lim])


REFS = {
    "explain": """Recursion means a function solves a problem by calling itself on a smaller piece of the same problem,
until it reaches a case small enough to answer directly (the base case).

**Example.** Counting files in a folder: `count(folder)` = number of files directly inside + `count(sub)` for each
sub-folder. A folder with no sub-folders is the base case: just count its files.

**How it runs.** Each call gets its own frame on the call stack holding its local variables. When `count(a)` calls
`count(a/b)`, the frame for `a` waits; when `a/b` returns, its frame is popped and `a` continues. The stack is what
remembers "where we were".

**Misconception.** "Recursion is always slow and should be avoided." Not so: it is often the clearest way to write tree
and divide-and-conquer code. Its real limits are call overhead and stack depth: Python stops at about 1000 nested
calls (RecursionError) and does not optimise tail calls, so very deep trees need a loop with an explicit stack.

**Takeaway:** recursion = base case + smaller self-call, with the call stack keeping track; mind the depth limit.""",
    "compare": """**Criteria:** depth limits, clarity, memory, control over traversal order.

**Recursion** is the most readable for trees: one function, the call stack does the bookkeeping. But CPython's default
limit is about 1000 frames, ten times below the 10,000 levels required here, and raising it risks crashing the
interpreter (the C stack is finite).

**Iteration with an explicit stack** keeps pending directories in a list on the heap, so depth is limited only by
memory (10,000 entries is trivial). It also allows breadth-first order by swapping the stack for a queue, and makes
it easy to skip symlink loops.

**When each wins:** recursion for shallow, well-bounded trees and quick scripts; explicit stack for untrusted or very
deep structures.

**Recommendation:** explicit stack (or `os.walk`, which is iterative). I would switch to recursion only if depth were
guaranteed below a few hundred levels and readability mattered most.""",
    "critique": """1. **"Always slower and should be avoided"**: an overstatement (imprecision). Recursion has call
overhead, but it is often clearer, and for tree-shaped problems the difference is usually small.
2. **"Without a base case it returns zero"**: wrong. It never terminates; each call adds a stack frame until the stack
is exhausted (Python raises RecursionError).
3. **"Python optimises tail calls, so deep recursion is safe"**: wrong. CPython has no tail-call optimisation and
limits recursion to about 1000 frames by default.

Correct part: none of the three sentences is fully right, though recursion does cost more per step than a loop.

**Corrected:** "Recursion trades some call overhead for clarity and suits tree-shaped problems. A recursive function
without a base case never stops and ends in a stack overflow (RecursionError in Python). Python does not optimise tail
calls, so very deep recursion must be rewritten as a loop.\"""",
}
WRONG = "Recursion is a programming concept. It is used in many languages. It can be useful or not, depending."


def main():
    rng = np.random.default_rng(SEED_GEN)
    kinds = ["explain", "compare", "critique"]
    keys = [t["key"] for t in T]
    assert len(keys) == len(set(keys)) and DEV["key"] not in keys
    pool = [(t, k) for t in T for k in kinds]
    order = rng.permutation(len(pool))
    items = [(f"OE-DEV{i + 1}", True, DEV, k) for i, k in enumerate(kinds)] + \
            [(f"OE-{n + 1:04d}", False, *pool[j]) for n, j in enumerate(order)]
    seg_rng = np.random.default_rng(SEED_ITEMS)
    man, crit = [], []
    for iid, dev, t, k in items:
        perm = seg_rng.permutation(len(SEGS[k]))
        segs = [{"id": f"r{j + 1}", "text": SEGS[k][j]} for j in perm]
        man.append({"id": iid, "class": "OE", "dev": dev, "answer_kind": "long_form", "prompt": prompt(t, k),
                    "segments": segs, "decisive_segment": None, "fixture": None, "public_check": None,
                    "allowed_tools": []})
        crit.append({"id": iid, "topic": t["key"], "kind": k, "source": t["src"], "word_limit": LIMIT[k],
                     "criteria": criteria(t, k)})
    (CLS_DIR / "manifest.jsonl").write_text("".join(json.dumps(m, ensure_ascii=False) + "\n" for m in man))
    (CLS_DIR / "oracle").mkdir(exist_ok=True)
    (CLS_DIR / "oracle" / "criteria.jsonl").write_text("".join(json.dumps(c, ensure_ascii=False) + "\n" for c in crit))
    st = CLS_DIR / "selftest"
    st.mkdir(exist_ok=True)
    for iid, _, _, k in items[:3]:
        assert len(REFS[k].split()) <= LIMIT[k], (k, len(REFS[k].split()))
        (st / f"{iid}.ref.json").write_text(json.dumps({"answer": REFS[k], "evidence": [], "confidence": 0.7},
                                                       ensure_ascii=False, indent=1) + "\n")
        (st / f"{iid}.wrong.json").write_text(json.dumps({"answer": WRONG, "evidence": [], "confidence": 0.9},
                                                         ensure_ascii=False, indent=1) + "\n")
    from collections import Counter
    print("items", len(man), "non-dev", len(man) - 3, Counter(c["kind"] for c in crit[3:]),
          "from graded prompts", sum(c["source"] != "authored" for c in crit[3:]), "gen seed", SEED_GEN)


if __name__ == "__main__":
    main()
