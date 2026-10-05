"""The stack's block in CLAUDE.md (lib/claude_md_block.py, dot-claude/CLAUDE.block.md, install.sh).

CLAUDE.md is the user's file: the installer owns only the lines from its begin marker line to its end
marker line. Pinned here: every byte outside the block survives (prefix, suffix, CRLF, BOM, no final
newline); a second run is byte-identical; a malformed, symlinked, non-regular or non-UTF-8 file is left
as it is (a symlink's target is never written, a directory named CLAUDE.md is never removed); removal
undoes an append exactly when the user's text ended in a newline (or was empty); and, through real
scratch-HOME installs (as tests/test_install_state.py runs them), --dry-run writes nothing, the
manifest records the block, a block edited inside is replaced with the edit in the backup, --restore
puts the file back byte for byte, and a stack that stops shipping the template retracts the block.

Run: uv run --with pytest pytest -q tests/test_install_claude_md.py
"""
import importlib.util
import json
import os
import random
import subprocess

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


cmb = _load("claude_md_block", os.path.join(ROOT, "lib", "claude_md_block.py"))
_tis = _load("_tis_cmb", os.path.join(HERE, "test_install_state.py"))

BODY = "Pointer line one.\nPointer line two.\n"
BLOCK = cmb.render_block(BODY)
needs_git = pytest.mark.skipif(not os.path.exists(os.path.join(ROOT, ".git")), reason="needs the stack's git checkout")


# ------------------------------------------------------------------------------- render_block
def test_render_block_wraps_the_body_in_the_marker_lines():
    assert BLOCK == f"{cmb.BEGIN}\nPointer line one.\nPointer line two.\n{cmb.END}\n".encode()
    assert cmb.render_block("\n\nx\n\n") == f"{cmb.BEGIN}\nx\n{cmb.END}\n".encode()
    assert cmb.render_block("") == f"{cmb.BEGIN}\n{cmb.END}\n".encode()
    assert cmb.find_block(BLOCK) == (0, len(BLOCK))


@pytest.mark.parametrize("body", [f"a\n{cmb.BEGIN}\nb", "a\n  <!-- claude-agent-stack: end -->\n", "a\x00b"])
def test_render_block_refuses_a_body_that_would_break_the_block(body):
    with pytest.raises(ValueError):
        cmb.render_block(body)


def test_shipped_template_renders_and_holds_no_marker_or_volatile_text():
    with open(os.path.join(ROOT, "dot-claude", "CLAUDE.block.md"), encoding="utf-8") as f:
        text = f.read()
    block = cmb.render_block(text)
    assert cmb.find_block(block) == (0, len(block))
    assert text.strip() and "\r" not in text


# ------------------------------------------------------------------------------- find_block
def test_find_block_none_and_one():
    assert cmb.find_block(b"") is None
    assert cmb.find_block(b"# mine\nthe <!-- claude-agent-stack: begin --> marker in a sentence\n") is None
    data = b"mine\n" + BLOCK + b"after\n"
    assert cmb.find_block(data) == (5, 5 + len(BLOCK))


@pytest.mark.parametrize("data, why", [
    (b"x\n<!-- claude-agent-stack: begin -->\nbody\n", "without an end"),
    (b"x\nbody\n<!-- claude-agent-stack: end -->\n", "without a begin"),
    (b"<!-- claude-agent-stack: end -->\nx\n<!-- claude-agent-stack: begin -->\n", "before the begin"),
    (BLOCK + b"\n" + BLOCK, "2 begin and 2 end"),
    (BLOCK + b"<!-- claude-agent-stack: begin -->\n", "2 begin and 1 end"),
])
def test_find_block_refuses_malformed_markers(data, why):
    with pytest.raises(cmb.BlockError, match=why):
        cmb.find_block(data)


def test_find_block_accepts_crlf_indent_bom_other_wording_and_no_final_newline():
    crlf = b"mine\r\n  <!-- claude-agent-stack: begin (an older wording) -->\r\nold\r\n<!-- claude-agent-stack: end -->\r\nend\r\n"
    s, e = cmb.find_block(crlf)
    assert crlf[:s] == b"mine\r\n" and crlf[e:] == b"end\r\n"
    bom = cmb.BOM + BLOCK
    assert cmb.find_block(bom) == (3, len(bom))                       # the BOM stays outside
    tail = b"mine\n" + BLOCK[:-1]
    assert cmb.find_block(tail) == (5, len(tail))


# ------------------------------------------------------------------------------- splice
def test_splice_creates_appends_replaces_and_removes():
    assert cmb.splice(None, BLOCK) == BLOCK and cmb.splice(None, None) is None
    assert cmb.splice(b"", BLOCK) == BLOCK
    assert cmb.splice(b"mine\n", BLOCK) == b"mine\n\n" + BLOCK
    assert cmb.splice(b"mine", BLOCK) == b"mine\n\n" + BLOCK
    edited = b"top\n" + cmb.render_block("edited by hand") + b"bottom\n"
    assert cmb.splice(edited, BLOCK) == b"top\n" + BLOCK + b"bottom\n"
    assert cmb.splice(b"top\n" + BLOCK + b"bottom\n", None) == b"top\nbottom\n"
    assert cmb.splice(b"no block\n", None) == b"no block\n"


@pytest.mark.parametrize("mine", [b"", b"mine\n", b"mine\n\n", b"a\r\nb\r\n", "été — règles\n".encode()])
def test_splice_removal_undoes_an_append_exactly(mine):
    assert cmb.splice(cmb.splice(mine, BLOCK), None) == mine


def test_splice_properties_on_random_user_text():
    """Idempotent, a later block replaces an earlier one in place, the user's bytes are a prefix
    (append) and survive a replace, for random texts without marker lines."""
    rng = random.Random(20261005)
    alphabet = ["a", "b", " ", "\n", "\r\n", "#", "-", "<!--", "-->", "é", "claude-agent-stack", "\t"]
    other = cmb.render_block("another version of the block")
    for _ in range(500):
        mine = "".join(rng.choice(alphabet) for _ in range(rng.randrange(0, 40))).encode()
        assert cmb.find_block(mine) is None
        once = cmb.splice(mine, BLOCK)
        assert once.startswith(mine) and cmb.splice(once, BLOCK) == once
        assert cmb.splice(cmb.splice(mine, other), BLOCK) == once
        if not mine or mine.endswith(b"\n"):
            assert cmb.splice(once, None) == mine
        suffix = mine + b"\n"
        wrapped = mine + b"\n" + other + suffix
        s, e = cmb.find_block(cmb.splice(wrapped, BLOCK))
        out = cmb.splice(wrapped, BLOCK)
        assert out[:s] == mine + b"\n" and out[e:] == suffix and out[s:e] == BLOCK


# ------------------------------------------------------------------------------- stage
def _md(d):
    return os.path.join(str(d), "CLAUDE.md")


def _bytes(p):
    with open(p, "rb") as f:
        return f.read()


def test_stage_created_unchanged_updated_replaced_and_removed(tmp_path):
    r = cmb.stage(str(tmp_path), BODY)
    assert r["action"] == "created" and _bytes(_md(tmp_path)) == BLOCK
    assert r["entry"] == {"sha256": cmb.sha256(BLOCK), "created": True}
    r2 = cmb.stage(str(tmp_path), BODY, r["entry"])
    assert r2 == {"action": "unchanged", "why": "", "entry": r["entry"]}
    r3 = cmb.stage(str(tmp_path), "a newer body", r2["entry"])            # the stack's own older block
    assert r3["action"] == "updated" and r3["entry"]["created"] is True
    with open(_md(tmp_path), "ab") as f:
        f.write(b"\nmy own line\n")
    with open(_md(tmp_path), "rb") as f:
        data = f.read()
    with open(_md(tmp_path), "wb") as f:
        f.write(data.replace(b"a newer body", b"a newer body, edited"))
    r4 = cmb.stage(str(tmp_path), "a newer body", r3["entry"])
    assert r4["action"] == "replaced" and "backup keeps" in r4["why"]
    assert _bytes(_md(tmp_path)) == cmb.render_block("a newer body") + b"\nmy own line\n"
    r5 = cmb.stage(str(tmp_path), None, r4["entry"])
    assert r5["action"] == "removed" and r5["entry"] is None
    assert _bytes(_md(tmp_path)) == b"\nmy own line\n"                     # created by the stack, but not empty


def test_stage_added_to_the_users_file_and_retracted_exactly(tmp_path):
    mine = "# my rules\n- my NAS is 192.168.1.20\n- été\n".encode()
    with open(_md(tmp_path), "wb") as f:
        f.write(mine)
    r = cmb.stage(str(tmp_path), BODY)
    assert r["action"] == "added" and r["entry"]["created"] is False
    assert _bytes(_md(tmp_path)) == mine + b"\n" + BLOCK
    r2 = cmb.stage(str(tmp_path), None, r["entry"])
    assert r2["action"] == "removed" and _bytes(_md(tmp_path)) == mine
    assert cmb.stage(str(tmp_path), None)["action"] == "absent" and _bytes(_md(tmp_path)) == mine


def test_stage_retraction_deletes_a_file_the_stack_created_and_left_empty(tmp_path):
    r = cmb.stage(str(tmp_path), BODY)
    assert cmb.stage(str(tmp_path), None, r["entry"])["action"] == "removed"
    assert not os.path.lexists(_md(tmp_path))
    # the same file, not recorded as the stack's: emptied, never deleted
    cmb.stage(str(tmp_path), BODY)
    assert cmb.stage(str(tmp_path), None, {"sha256": "x", "created": False})["action"] == "removed"
    assert _bytes(_md(tmp_path)) == b""


def test_stage_never_writes_through_a_symlink(tmp_path):
    target = tmp_path / "dotfiles" / "CLAUDE.md"
    target.parent.mkdir()
    target.write_bytes(b"dotfiles text\n")
    stage_dir = tmp_path / "stage"
    stage_dir.mkdir()
    os.symlink(str(target), _md(stage_dir))
    prev = {"sha256": "abc", "created": False}
    for body in (BODY, None):
        r = cmb.stage(str(stage_dir), body, prev)
        assert r["action"] == "skipped" and r["entry"] is prev and "symlink" in r["why"]
    assert target.read_bytes() == b"dotfiles text\n" and os.readlink(_md(stage_dir)) == str(target)


@pytest.mark.parametrize("kind", ["dir", "binary", "malformed"])
def test_stage_leaves_an_unusable_file_alone(tmp_path, kind):
    p = _md(tmp_path)
    if kind == "dir":
        os.mkdir(p)
    else:
        data = b"\xff\xfe\x00m\x00i" if kind == "binary" else b"mine\n<!-- claude-agent-stack: begin -->\nhalf\n"
        with open(p, "wb") as f:
            f.write(data)
    before = None if kind == "dir" else _bytes(p)
    prev = {"sha256": "abc", "created": True}
    for body in (BODY, None):
        r = cmb.stage(str(tmp_path), body, prev)
        assert r["action"] == "skipped" and r["entry"] is prev, r
    assert os.path.isdir(p) if kind == "dir" else _bytes(p) == before
    if kind == "malformed":
        assert "without an end" in r["why"] and "./install.sh" in r["why"]


def test_stage_skips_when_the_live_file_is_not_regular(tmp_path):
    """install_state stages only files and links, so a directory (or FIFO) named CLAUDE.md in the
    config dir is absent from the staged copy: stage() must look at the live path, or the plan would
    "add" a file over it (place() would rmtree the directory, with no backup)."""
    live = tmp_path / "live"
    (live / "CLAUDE.md").mkdir(parents=True)
    stage_dir = tmp_path / "stage"
    stage_dir.mkdir()
    prev = {"sha256": "abc", "created": False}
    r = cmb.stage(str(stage_dir), BODY, prev, live=str(live / "CLAUDE.md"))
    assert r["action"] == "skipped" and r["entry"] is prev and "not a regular file" in r["why"]
    assert not os.path.lexists(_md(stage_dir))
    os.mkfifo(str(live / "fifo"))
    assert cmb.stage(str(stage_dir), BODY, None, live=str(live / "fifo"))["action"] == "skipped"
    assert cmb.stage(str(stage_dir), BODY, None, live=str(live / "absent"))["action"] == "created"


# ------------------------------------------------------------------------------- install.sh
def _home(tmp_path):
    home = str(tmp_path / "home")
    os.makedirs(home)
    return home, os.path.join(home, ".claude")


def _manifest(conf):
    with open(os.path.join(conf, ".stack-manifest.json"), encoding="utf-8") as f:
        return json.load(f)


def _expected_block(repo):
    with open(os.path.join(repo, "dot-claude", "CLAUDE.block.md"), encoding="utf-8") as f:
        return cmb.render_block(f.read().replace("__STACK_REPO__", repo))


def _actions(log):
    """The action words of install.sh's "CLAUDE.md (the stack's block)" lines."""
    label = "CLAUDE.md (the stack's block)"
    return [ln.strip()[len(label):].split()[0] for ln in log.splitlines() if ln.strip().startswith(label)]


def _backups(home):
    root = os.path.join(home, ".local", "state", "claude-agent-stack-backups")
    return sorted(os.path.join(root, n) for n in os.listdir(root) if not n.startswith("."))


@needs_git
def test_install_adds_the_block_keeps_your_text_and_restores_it(tmp_path):
    home, conf = _home(tmp_path)
    repo = _tis._scratch_repo(str(tmp_path / "repo"))
    os.makedirs(conf)
    mine = "# my rules\n- my NAS is 192.168.1.20\n- été".encode()       # no final newline
    with open(_md(conf), "wb") as f:
        f.write(mine)
    want = _expected_block(repo)

    dry = _tis._run_install(repo, home, conf, "--dry-run")
    assert dry.returncode == 0, (dry.stdout[-2000:], dry.stderr[-2000:])
    assert _bytes(_md(conf)) == mine and _actions(dry.stdout) == ["added"], _actions(dry.stdout)

    log = _tis._install(repo, home, conf)
    assert _actions(log) == ["added"]
    after = _bytes(_md(conf))
    assert after == mine + b"\n\n" + want
    assert _manifest(conf)["claude_md_block"] == {"sha256": cmb.sha256(want), "created": False}

    log = _tis._install(repo, home, conf)
    assert _actions(log) == ["unchanged"] and _bytes(_md(conf)) == after

    edited = after.replace(b"global rules", b"GLOBAL RULES") + b"\nmy line after the block\n"
    with open(_md(conf), "wb") as f:
        f.write(edited)
    n_before = len(_backups(home))
    log = _tis._install(repo, home, conf)
    assert _actions(log) == ["replaced"], log[-3000:]
    assert "~ CLAUDE.md  (the stack's block in it differed" in log
    assert _bytes(_md(conf)) == mine + b"\n\n" + want + b"\nmy line after the block\n"
    newest = _backups(home)[-1]
    assert len(_backups(home)) == n_before + 1
    assert _bytes(os.path.join(newest, "files", "CLAUDE.md")) == edited          # the backup keeps yours

    first = _backups(home)[0]                                                    # the first install's backup
    p = _tis._run_install(repo, home, conf, argv=["--restore", first])
    assert p.returncode == 0, (p.stdout[-2000:], p.stderr[-2000:])
    assert _bytes(_md(conf)) == mine                                             # byte for byte


@needs_git
def test_fresh_install_creates_the_block_and_a_later_stack_without_it_retracts(tmp_path):
    home, conf = _home(tmp_path)
    repo = _tis._scratch_repo(str(tmp_path / "repo"))
    log = _tis._install(repo, home, conf)
    want = _expected_block(repo)
    assert _actions(log) == ["created"] and _bytes(_md(conf)) == want
    assert _manifest(conf)["claude_md_block"]["created"] is True

    os.unlink(os.path.join(repo, "dot-claude", "CLAUDE.block.md"))
    git = ["git", "-c", "core.hooksPath=/dev/null", "-c", "commit.gpgsign=false", "-c", "user.name=t",
           "-c", "user.email=t@example.invalid", "-C", repo]
    for args in (["add", "-A"], ["commit", "-q", "-m", "no block"]):
        subprocess.run(git + args, check=True, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL)
    log = _tis._install(repo, home, conf, "--yes")
    assert _actions(log) == ["removed"], log[-3000:]
    assert "  - CLAUDE.md  (the stack no longer ships a CLAUDE.md block)" in log, log[-3000:]
    assert not os.path.lexists(_md(conf)) and "claude_md_block" not in _manifest(conf)


@needs_git
def test_install_leaves_a_symlinked_claude_md_and_its_target_alone(tmp_path):
    home, conf = _home(tmp_path)
    repo = _tis._scratch_repo(str(tmp_path / "repo"))
    os.makedirs(conf)
    target = os.path.join(home, "dotfiles", "CLAUDE.md")
    os.makedirs(os.path.dirname(target))
    with open(target, "wb") as f:
        f.write(b"dotfiles text\n")
    os.symlink(target, _md(conf))
    log = _tis._install(repo, home, conf)
    assert _actions(log) == ["skipped"], log[-3000:]
    assert f"note: CLAUDE.md: a symlink to {target} (yours)" in log
    assert os.readlink(_md(conf)) == target and _bytes(target) == b"dotfiles text\n"
    assert "claude_md_block" not in _manifest(conf)


@needs_git
def test_diff_reports_the_block_and_never_the_users_text(tmp_path):
    """install.sh --diff (lib/stack_diff.py): in sync after an install whatever the user writes outside
    the block; an edited block is "~ ... edited since the last install", a missing one "+", malformed
    markers "?"; nothing is written."""
    _tid = _load("_tid_cmb", os.path.join(HERE, "test_install_diff.py"))
    home, conf = _home(tmp_path)
    repo = _tis._scratch_repo(str(tmp_path / "repo"))
    _tis._install(repo, home, conf)

    def area():
        p = _tid.diff(repo, home, conf)
        assert p.returncode == 0, p.stderr
        rows = [ln for ln in p.stdout.splitlines() if ln.startswith("CLAUDE.md block:") or "CLAUDE.md  (" in ln]
        return rows

    with open(_md(conf), "ab") as f:
        f.write(b"\nmy own text after the block\n")
    assert area() == ["CLAUDE.md block: in sync"]
    data = _bytes(_md(conf))
    with open(_md(conf), "wb") as f:
        f.write(data.replace(b"global rules", b"GLOBAL RULES"))
    before = _bytes(_md(conf))
    rows = area()
    assert rows[0] == "CLAUDE.md block: 1 differs" and "the stack's block; edited since the last install" in rows[1], rows
    assert _bytes(_md(conf)) == before
    with open(_md(conf), "wb") as f:
        f.write(b"mine only\n")
    assert area()[0] == "CLAUDE.md block: 1 repo only"
    with open(_md(conf), "wb") as f:
        f.write(b"mine\n<!-- claude-agent-stack: end -->\n")
    rows = area()
    assert rows[0] == "CLAUDE.md block: 1 unreadable" and "without a begin" in rows[1], rows
    with open(_md(conf), "wb") as f:
        f.write(b"\xff\xfe mine\n")                       # install.sh skips it: never "+ repo only"
    rows = area()
    assert rows[0] == "CLAUDE.md block: 1 unreadable" and "not UTF-8" in rows[1], rows


@needs_git
def test_install_leaves_a_directory_named_claude_md_alone(tmp_path):
    home, conf = _home(tmp_path)
    repo = _tis._scratch_repo(str(tmp_path / "repo"))
    os.makedirs(os.path.join(conf, "CLAUDE.md"))
    with open(os.path.join(conf, "CLAUDE.md", "notes.txt"), "wb") as f:
        f.write(b"my notes\n")
    log = _tis._install(repo, home, conf)
    assert _actions(log) == ["skipped"], log[-3000:]
    assert "note: CLAUDE.md: not a regular file" in log
    assert _bytes(os.path.join(conf, "CLAUDE.md", "notes.txt")) == b"my notes\n"
    assert "claude_md_block" not in _manifest(conf)
