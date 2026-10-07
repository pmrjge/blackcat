"""lib/skill_links.py: the $HOME/.agents/skills link manager (DESIGN.md §7.3, §8.3 "Links")."""
from __future__ import annotations

import io
import json
import os
import stat

import pytest

from conftest import LIB, load_lib
from _foundation_helpers import run_py, write_json

sl = load_lib("skill_links")
SL_PY = LIB / "skill_links.py"


@pytest.fixture
def L(scratch_home, tmp_path):
    ch = scratch_home["codex_home"]
    for n in ("s1", "s2", "s3"):
        (ch / "stack" / "skills" / n).mkdir(parents=True)
    root = scratch_home["skills_root"]
    bk = tmp_path / "backups"
    bk.mkdir(mode=0o700)
    n = [0]

    def links(*names, root_=root, stack=ch / "stack" / "skills"):
        return write_json(tmp_path / ("links%d.json" % len(list(tmp_path.glob("links*.json")))),
                          {"root": None if root_ is None else str(root_),
                           "links": {x: str(stack / x) for x in names}})

    def manifest(links_path):
        p = tmp_path / ("manifest%d.json" % len(list(tmp_path.glob("manifest*.json"))))
        return write_json(p, {"format": 1, "links": json.loads(open(links_path).read())})

    def bdir():
        n[0] += 1
        d = bk / str(n[0])
        d.mkdir(mode=0o700)
        return d

    return {"ch": ch, "root": root, "links": links, "manifest": manifest, "bdir": bdir, "tmp": tmp_path}


def entries(root):
    out = {}
    for name in sorted(os.listdir(root)):
        p = os.path.join(root, name)
        out[name] = ("l", os.readlink(p)) if os.path.islink(p) else ("d" if os.path.isdir(p) else "f")
    return out


def apply(L, links, old="-"):
    b = L["bdir"]()
    sl.apply(str(links), str(old), str(b), out=io.StringIO())
    return b


def test_first_install_and_restore(L):
    ln = L["links"]("s1", "s2")
    b = apply(L, ln)
    assert entries(L["root"]) == {n: ("l", str(L["ch"] / "stack" / "skills" / n)) for n in ("s1", "s2")}
    rec = b / sl.RECORD
    assert stat.S_IMODE(rec.stat().st_mode) == 0o600
    assert [e["before"] for e in json.loads(rec.read_text())["entries"]] == [sl.MISSING, sl.MISSING]
    assert sl.restore(str(b), out=io.StringIO()) == []
    assert entries(L["root"]) == {}


def test_missing_root_created(L):
    os.rmdir(L["root"])
    apply(L, L["links"]("s1"))
    assert not os.path.islink(L["root"]) and "s1" in entries(L["root"])


def test_second_run_keeps_and_is_empty(L):
    ln = L["links"]("s1")
    apply(L, ln)
    b = apply(L, L["links"]("s1"), L["manifest"](ln))
    assert json.loads((b / sl.RECORD).read_text())["entries"] == []


@pytest.mark.parametrize("make", ["dir", "file", "link-elsewhere"])
def test_foreign_entry_stops_and_changes_nothing(L, make):
    p = L["root"] / "s2"
    if make == "dir":
        p.mkdir()
    elif make == "file":
        p.write_text("x")
    else:
        p.symlink_to(L["tmp"])
    before = entries(L["root"])
    b = L["bdir"]()
    with pytest.raises(sl.LinkError, match="s2"):
        sl.apply(str(L["links"]("s1", "s2")), "-", str(b), out=io.StringIO())
    assert entries(L["root"]) == before and not (b / sl.RECORD).exists()


def test_stack_like_link_not_in_old_manifest_is_foreign(L, tmp_path):
    ln = L["links"]("s1")
    apply(L, ln)
    other = tmp_path / "other" / "stack" / "skills" / "s2"
    (L["root"] / "s2").symlink_to(other)
    with pytest.raises(sl.LinkError, match="s2"):
        apply(L, L["links"]("s1", "s2"), L["manifest"](ln))
    assert os.readlink(L["root"] / "s2") == str(other)


def test_identical_link_without_manifest_is_kept(L):
    (L["root"] / "s1").symlink_to(L["ch"] / "stack" / "skills" / "s1")
    b = apply(L, L["links"]("s1"))
    assert json.loads((b / sl.RECORD).read_text())["entries"] == []


def test_update_and_restore(L, tmp_path):
    old_stack = tmp_path / "old" / "stack" / "skills"
    ln_old = L["links"]("s1", stack=old_stack)
    apply(L, ln_old)
    b = apply(L, L["links"]("s1"), L["manifest"](ln_old))
    assert os.readlink(L["root"] / "s1") == str(L["ch"] / "stack" / "skills" / "s1")
    sl.restore(str(b), out=io.StringIO())
    assert os.readlink(L["root"] / "s1") == str(old_stack / "s1")


def test_remove_and_restore(L):
    ln = L["links"]("s1", "s2")
    apply(L, ln)
    b = apply(L, L["links"]("s1"), L["manifest"](ln))
    assert set(entries(L["root"])) == {"s1"}
    sl.restore(str(b), out=io.StringIO())
    assert set(entries(L["root"])) == {"s1", "s2"}


def test_foreign_entry_under_dropped_name_is_left_alone(L, tmp_path):
    ln = L["links"]("s1", "s2")
    apply(L, ln)
    os.unlink(L["root"] / "s2")
    mine = tmp_path / "my-s2"
    mine.mkdir()
    (L["root"] / "s2").symlink_to(mine)
    out = io.StringIO()
    sl.apply(str(L["links"]("s1")), str(L["manifest"](ln)), str(L["bdir"]()), out=out)
    assert os.readlink(L["root"] / "s2") == str(mine)
    assert "s2: kept" in out.getvalue()


def test_unrelated_entries_never_touched(L, tmp_path):
    (L["root"] / "mine").mkdir()
    (L["root"] / "theirs").symlink_to(tmp_path)
    before = entries(L["root"])
    b = apply(L, L["links"]("s1", "s2", "s3"))
    sl.restore(str(b), out=io.StringIO())
    assert entries(L["root"]) == before


def test_symlinked_root_refused(L, tmp_path):
    real = tmp_path / "real-skills"
    real.mkdir()
    os.rmdir(L["root"])
    os.symlink(real, L["root"])
    with pytest.raises(sl.LinkError, match="symlink"):
        apply(L, L["links"]("s1"))
    assert os.listdir(real) == []


def test_restore_leaves_entries_changed_after_apply(L, tmp_path):
    b = apply(L, L["links"]("s1", "s2"))
    os.unlink(L["root"] / "s1")
    (L["root"] / "s1").symlink_to(tmp_path)              # yours now
    left = sl.restore(str(b), out=io.StringIO())
    assert len(left) == 1 and "s1" in left[0]
    assert os.readlink(L["root"] / "s1") == str(tmp_path)
    assert "s2" not in entries(L["root"])


def test_record_written_before_any_change(L):
    b = L["bdir"]()
    (b / sl.RECORD).write_text("{}")
    with pytest.raises(sl.LinkError, match="already holds"):
        sl.apply(str(L["links"]("s1")), "-", str(b), out=io.StringIO())
    assert entries(L["root"]) == {}


@pytest.mark.parametrize("bad", [
    {"root": "/r", "links": {"../x": "/c/stack/skills/../x"}},
    {"root": "/r", "links": {"s1": "/c/elsewhere/s1"}},
    {"root": "/r", "links": {"s1": "/c/stack/skills/s2"}},
    {"root": "rel", "links": {}},
    {"root": "/r", "links": {"s1": "/a/stack/skills/s1", "s2": "/b/stack/skills/s2"}},
])
def test_links_json_validated(tmp_path, bad):
    with pytest.raises(sl.LinkError):
        sl.load_new(str(write_json(tmp_path / "l.json", bad)))


def test_skills_root_none_removes_old_links(L):
    ln = L["links"]("s1", "s2")
    apply(L, ln)
    b = apply(L, L["links"](root_=None), L["manifest"](ln))
    assert entries(L["root"]) == {}
    sl.restore(str(b), out=io.StringIO())
    assert set(entries(L["root"])) == {"s1", "s2"}


def test_cli(L):
    ln = L["links"]("s1")
    r = run_py(SL_PY, "plan", ln, "-")
    assert r.returncode == 0 and "+ " in r.stdout and entries(L["root"]) == {}
    b = L["bdir"]()
    assert run_py(SL_PY, "apply", ln, "-", b).returncode == 0
    assert "s1" in entries(L["root"])
    (L["root"] / "s2").mkdir()
    r = run_py(SL_PY, "plan", L["links"]("s1", "s2"), L["manifest"](ln))
    assert r.returncode == 1 and "s2" in r.stderr
    assert run_py(SL_PY, "restore", b).returncode == 0 and set(entries(L["root"])) == {"s2"}
    assert run_py(SL_PY, "plan", ln).returncode == 2
