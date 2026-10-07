"""Contract with the Claude installer's engine (lib/install_state.py, lib/claude_md_block.py).

codex_state.py and codex_home.py reuse these by file path, unchanged (DESIGN.md §7.2). Every name
and signature they use is pinned here, so a Claude-side refactor that breaks the coupling fails in
codex_config/tests instead of at install time.
"""
from __future__ import annotations

import inspect
import io
import os
import re
from contextlib import redirect_stdout

import pytest

from conftest import LIB, REPO, load_lib

ENGINE = load_lib("install_state_contract", REPO / "lib" / "install_state.py")
CMB = load_lib("claude_md_block_contract", REPO / "lib" / "claude_md_block.py")

SIGNATURES = {
    "stage": "(c, s, snap_path=None)",
    "make_plan": "(c, s, report_path, default_why='not part of the stack', keep_linked=True)",
    "print_plan": "(plan, removed_heading='removed: not part of the stack')",
    "apply_plan": "(c, s, plan, root, commit, reason='install', extra=None, snap=None)",
    "restore": "(c, which, root, work, commit, home, dry=False, force=False)",
    "ensure_root": "(root)",
    "new_backup_dir": "(root)",
    "empty_backup": "(c, root, commit, reason='install', extra=None)",
    "drifted": "(c, snap, rels=None)",
    "unsafe_paths": "(c, plan)",
    "backups_of": "(c, root)",
    "scan": "(root)",
    "in_scope": "(rel)",
    "leaf": "(path, rel)",
    "write_json": "(path, data, mode=384)",
    "load_json": "(path, default=None, limit=None)",
    "expand_path": "(raw, home, cwd)",
    "absolute_path": "(raw, home, cwd)",
    "_inside": "(path, root)",
    "_same": "(a, b)",
    "_real": "(p)",
    "_cwd": "()",
}


@pytest.mark.parametrize("name", sorted(SIGNATURES))
def test_engine_signatures(name):
    assert str(inspect.signature(getattr(ENGINE, name))) == SIGNATURES[name]


def test_engine_constants_and_types():
    for name in ("SCOPE_DIRS", "SCOPE_FILES", "EXCLUDED", "WRITE_THROUGH", "HOME_INSIDE", "SYSTEM_INSIDE",
                 "HOME_EQUAL", "SYSTEM_EQUAL"):
        v = getattr(ENGINE, name)
        assert isinstance(v, tuple) and all(isinstance(x, str) for x in v), name
    assert isinstance(ENGINE.BAD_PATH_CHARS, re.Pattern)
    for ch in '\n\x00"`$\\':
        assert ENGINE.BAD_PATH_CHARS.search("a%sb" % ch)
    assert ENGINE.BACKUP_FORMAT == 1
    assert issubclass(ENGINE.ConfigDirError, Exception)
    for rel in (".ssh", ".gnupg", ".aws", "Library/Keychains"):
        assert rel in ENGINE.HOME_INSIDE
    assert "/etc" in ENGINE.SYSTEM_INSIDE and "Documents" in ENGINE.HOME_EQUAL


def test_engine_reads_module_constants_at_call_time(tmp_path):
    """codex_state sets the constants on the module: the functions must read them as globals."""
    eng = load_lib("install_state_contract2", REPO / "lib" / "install_state.py")
    eng.SCOPE_DIRS, eng.SCOPE_FILES, eng.EXCLUDED = ("stack",), ("config.toml",), ("stack/x",)
    (tmp_path / "stack" / "x").mkdir(parents=True)
    (tmp_path / "stack" / "a").write_text("1")
    (tmp_path / "stack" / "x" / "b").write_text("1")
    (tmp_path / "config.toml").write_text("1")
    (tmp_path / "other").write_text("1")
    assert sorted(eng.scan(str(tmp_path))) == ["config.toml", "stack/a"]
    assert eng.in_scope("config.toml") and not eng.in_scope("other")


def test_leaf_counts_whole_mode_of_stack_env_only(tmp_path):
    p = tmp_path / "stack.env"
    p.write_text("K=1\n")
    p.chmod(0o600)
    a = ENGINE.leaf(str(p), "stack.env")
    p.chmod(0o644)
    assert ENGINE.leaf(str(p), "stack.env") != a
    q = tmp_path / "other"
    q.write_text("x")
    q.chmod(0o600)
    b = ENGINE.leaf(str(q), "other")
    q.chmod(0o644)
    assert ENGINE.leaf(str(q), "other") == b


def test_plan_keys_and_print_plan_hides_agents_prefix():
    """codex_state.print_plan relies on the engine leaving "agents/..." entries out of "updated:"."""
    plan = {"added": [], "changed": ["agents/stack/agents/x.toml", "codex.config.toml"], "removed": [],
            "replaced": [], "removed_listing": [], "notes": []}
    buf = io.StringIO()
    with redirect_stdout(buf):
        ENGINE.print_plan(plan)
    out = buf.getvalue()
    assert out.splitlines()[0] == "  changes: 0 added, 2 updated, 0 removed"
    assert "updated: codex.config.toml\n" in out and "x.toml" not in out


def test_make_plan_result_keys(tmp_path):
    c, s = tmp_path / "c", tmp_path / "s"
    c.mkdir()
    s.mkdir()
    p = ENGINE.make_plan(str(c), str(s), str(tmp_path / "none.json"))
    assert {"added", "changed", "removed", "replaced", "removed_listing", "notes", "linked",
            "keep_linked"} <= set(p)


def test_engine_loads_stack_io_relative_to_its_file():
    """The snapshot must hold dot-claude/hooks/stack_io.py next to lib/ (source_snapshot copies it)."""
    src = (REPO / "lib" / "install_state.py").read_text()
    assert '"dot-claude", "hooks", "stack_io.py"' in src
    assert "spec_from_file_location" in src


def test_engine_restore_messages_still_mapped():
    """The engine texts codex_state rewords (codex_state.wording) are still there."""
    src = (REPO / "lib" / "install_state.py").read_text()
    for text in ("(set CLAUDE_CONFIG_DIR)", "install.sh --restore:", "install_state: refusing paths outside the config dir",
                 "no changes: the config dir already matches"):
        assert text in src, text
    assert '.get("reason") == "install"' in src


def test_claude_md_block_contract():
    assert str(inspect.signature(CMB.find_block)) == "(data: 'bytes')"
    assert issubclass(CMB.BlockError, ValueError)


def test_codex_modules_load_engine_by_path_only():
    for name in ("codex_state.py", "codex_home.py"):
        src = (LIB / name).read_text()
        assert "spec_from_file_location" in src, name
        assert not re.search(r"sys\.path\.(insert|append)|sys\.path\s*=|import install_state", src), name
    st = load_lib("codex_state")
    assert os.path.samefile(st.ENGINE_PATH, REPO / "lib" / "install_state.py")
    assert st.ist.__file__ == st.ENGINE_PATH
