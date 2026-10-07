"""Seeded-bug proof runner: each mutation must turn the named tests red.

Usage (from the repository root):
    uv run --no-project --python 3.13 --with pytest python dot-config/dot-codex_config/tests/mutate.py MUTATIONS.json

MUTATIONS.json is a list of {"file": "dot-config/dot-codex_config/lib/x.py", "old": "...", "new": "...",
"tests": "dot-config/dot-codex_config/tests/test_x.py[::name]", "why": "..."}. For each one the script
copies the repository's dot-config/dot-codex_config/, dot-config/dot-claude/, lib/ and tests/ into a
temporary tree (same relative paths), replaces exactly one occurrence of `old` (it must occur exactly
once, else the mutation is reported as BAD), runs pytest on `tests` there and expects a failure. Exit 0 only when every mutation was caught. Never touches the working tree.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]   # <repo>/dot-config/dot-codex_config/tests/mutate.py


def run(muts):
    bad = 0
    for i, m in enumerate(muts):
        with tempfile.TemporaryDirectory(prefix="cc-mut-") as td:
            root = Path(td)
            for d in ("dot-config/dot-codex_config", "lib", "dot-config/dot-claude", "tests"):
                if (REPO / d).exists():
                    shutil.copytree(REPO / d, root / d, symlinks=True,
                                    ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache", "build"))
            target = root / m["file"]
            text = target.read_text()
            if text.count(m["old"]) != 1:
                print("BAD  #%d %s: `old` occurs %d times" % (i, m["file"], text.count(m["old"])))
                bad += 1
                continue
            target.write_text(text.replace(m["old"], m["new"]))
            r = subprocess.run([sys.executable, "-m", "pytest", "-q", "-x", "-p", "no:cacheprovider",
                                m["tests"]], cwd=root, capture_output=True, text=True)
            # pytest exit 1 = tests ran and failed. 2-5 (interrupted, internal error, usage error, no tests
            # collected: e.g. a mistyped node id) prove nothing: reported BAD, never counted as caught.
            if r.returncode not in (0, 1):
                print("BAD  #%d %s: pytest exit %d (no test verdict): %s" % (i, m["file"], r.returncode, m["tests"]))
                bad += 1
                continue
            caught = r.returncode == 1
            print("%s #%d %s: %s" % ("ok  " if caught else "MISS", i, m["file"], m.get("why", "")))
            bad += 0 if caught else 1
    return bad


if __name__ == "__main__":
    muts = json.loads(Path(sys.argv[1]).read_text())
    sys.exit(1 if run(muts) else 0)
