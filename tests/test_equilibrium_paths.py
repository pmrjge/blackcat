"""The path relativisation of equilibrium/ (COMPARE_eq.md A5) changed only path text, and no file there names the old
home directory (tests/equilibrium_paths.py holds the rules and the checker; equilibrium/PATH_RELATIVISATION.json the
record).

Run: uv run --no-project --with pytest pytest -q tests/test_equilibrium_paths.py
"""
import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import equilibrium_paths as ep  # noqa: E402

SAMPLE = (b"#!/usr/bin/env bash\nset -u\nproj=${EQ_LEAN_PROJECT:-" + ep.OLD_LEAN + b"}\n# default " + ep.OLD_LEAN
          + b"\ncd " + ep.OLD_STAGE + b"/isolation && ls " + ep.OLD_M + b"/claude-local-work\nM=" + ep.OLD_M + b"\n")


def _tree(root: Path, data: bytes) -> Path:
    new, subs = ep.forward(data)
    f = root / "equilibrium" / "x.sh"
    f.parent.mkdir(parents=True)
    f.write_bytes(new)
    rec = {"files": {"equilibrium/x.sh": {"old_sha256": hashlib.sha256(data).hexdigest(),
                                          "new_sha256": hashlib.sha256(new).hexdigest(), "subs": subs}}}
    (root / ep.RECORD).write_text(json.dumps(rec))
    return f


def test_the_tracked_tree_changed_only_path_text():
    assert ep.check() == []


def test_record_covers_the_relativised_files():
    rec = json.loads((ep.ROOT / ep.RECORD).read_text())
    assert rec["rules"] == [r[0] for r in ep.RULES]
    assert len(rec["files"]) == 236 and sum(len(f["subs"]) for f in rec["files"].values()) == 504
    for rel in ("equilibrium/harness/eq_harness.py", "equilibrium/harness/eq_check.sh",
                "equilibrium/harness/eq_freeze.sh", "equilibrium/items/PF/check_lean.sh",
                "equilibrium/items/RS/gen/src/SOURCES.sha256", "equilibrium/isolation/build-metadata.json",
                "equilibrium/COMPARE_eq.md"):
        assert rel in rec["files"], rel


def test_forward_then_reverse_round_trips_and_leaves_no_home_path():
    new, subs = ep.forward(SAMPLE)
    assert ep.OLD_HOME not in new
    assert b"${EQ_LEAN_PROJECT:-${HOME:-}/lean/stack_mathlib}" in new and b"cd equilibrium/isolation" in new
    assert b"ls claude-local-work" in new and b"\nM=.\n" in new
    assert ep.reverse(new, subs) == SAMPLE and ep.forward(ep.reverse(new, subs)) == (new, subs)


def test_check_catches_a_non_path_edit(tmp_path):
    f = _tree(tmp_path, SAMPLE)
    assert ep.check(tmp_path) == []
    f.write_bytes(f.read_bytes().replace(b"set -u", b"set -e"))  # a behaviour change hidden among path edits
    rec = json.loads((tmp_path / ep.RECORD).read_text())
    rec["files"]["equilibrium/x.sh"]["new_sha256"] = hashlib.sha256(f.read_bytes()).hexdigest()  # re-pinned
    (tmp_path / ep.RECORD).write_text(json.dumps(rec))
    assert ep.check(tmp_path) == ["equilibrium/x.sh: reversed bytes differ from the recorded old digest"]


def test_check_catches_a_missed_or_new_home_path(tmp_path):
    f = _tree(tmp_path, SAMPLE)
    (tmp_path / "equilibrium" / "y.md").write_bytes(b"see " + ep.OLD_HOME + b"/x\n")
    assert ep.check(tmp_path) == ["equilibrium/y.md: names the old home directory"]
    f.write_bytes(f.read_bytes() + b"# " + ep.OLD_M + b"\n")
    assert "equilibrium/x.sh: tracked bytes differ from the recorded new digest" in ep.check(tmp_path)


PRE_A5 = "bd3a182"  # the tracked tree just before A5 (equilibrium/ as copied from EQ-T)
OLD_HAS_NON_PATH_EDIT = {"equilibrium/COMPARE_eq.md", "equilibrium/harness/eq_freeze.sh",
                         "equilibrium/harness/eq_harness.py"}  # equilibrium/README.md, "Differences from EQ-T"


def test_old_digests_are_the_pre_a5_tree():
    """Anchor the record: each recorded old digest is the file as tracked in PRE_A5, except the three files whose
    pre-pass version already carried A5's non-path edits (so a re-pinned record cannot hide a non-path edit)."""
    g = ["git", "-C", str(ep.ROOT)]
    if subprocess.run([*g, "cat-file", "-e", PRE_A5 + "^{commit}"], capture_output=True).returncode:
        pytest.skip(f"{PRE_A5} not in this clone")
    rec = json.loads((ep.ROOT / ep.RECORD).read_text())["files"]
    off = {rel for rel, f in rec.items() if hashlib.sha256(subprocess.run(
        [*g, "show", f"{PRE_A5}:{rel}"], capture_output=True, check=True).stdout).hexdigest() != f["old_sha256"]}
    assert off == OLD_HAS_NON_PATH_EDIT
