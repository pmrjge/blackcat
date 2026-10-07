"""install.sh --diff (lib/stack_diff.py): read-only comparison of the repo's dot-config/dot-claude/ with an installed
config dir.

A real scratch install (fresh HOME, fake `claude`, as tests/test_install_state.py runs it) must diff
clean, which pins the helper's render to the installer's; seeded drift on either side must show up
(mutation proof); nothing in HOME or the repo may change; exit 0 except usage errors (2).

Run: uv run --with pytest pytest -q tests/test_install_diff.py
"""
import hashlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
_spec = importlib.util.spec_from_file_location("_tis", os.path.join(HERE, "test_install_state.py"))
_tis = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_tis)
sys.path.insert(0, os.path.join(ROOT, "lib"))
import stack_diff  # noqa: E402

needs_git = pytest.mark.skipif(not os.path.exists(os.path.join(ROOT, ".git")), reason="needs the stack's git checkout")


def diff(repo, home, conf, *extra, env_conf=True):
    env = {k: v for k, v in os.environ.items() if not k.startswith(("STACK_", "CLAUDE_", "XDG_"))}
    env.update(HOME=home, XDG_STATE_HOME=os.path.join(home, ".local", "state"), STACK_ALLOW_NON_MACOS="1",
               PYTHONDONTWRITEBYTECODE="")
    if env_conf:
        env["CLAUDE_CONFIG_DIR"] = conf
    return subprocess.run([os.path.join(repo, "install.sh"), "--diff", *extra], env=env, stdin=subprocess.DEVNULL,
                          capture_output=True, text=True, timeout=120, check=False)


def fingerprint(*roots):
    """path -> (sha256, mtime_ns, mode) of every file and link below roots (dirs by their listing)."""
    out = {}
    for root in roots:
        for d, dirs, files in os.walk(root):
            out[d] = tuple(sorted(os.listdir(d)))
            for fn in files:
                p = os.path.join(d, fn)
                st = os.lstat(p)
                h = os.readlink(p) if os.path.islink(p) else hashlib.sha256(open(p, "rb").read()).hexdigest()
                out[p] = (h, st.st_mtime_ns, st.st_mode)
    return out


@pytest.fixture
def installed(tmp_path):
    repo = _tis._scratch_repo(str(tmp_path / "repo"))
    home = str(tmp_path / "home")
    os.makedirs(home)
    conf = os.path.join(home, ".claude")
    _tis._install(repo, home, conf, "--yes")
    return repo, home, conf


def summary(out):
    m = re.search(r"summary: (\d+) repo only, (\d+) installed only, (\d+) differ", out)
    assert m, out[-2000:]
    return tuple(int(x) for x in m.groups())


@needs_git
def test_fresh_install_diffs_clean_and_writes_nothing(installed):
    repo, home, conf = installed
    before = fingerprint(home, repo)
    p = diff(repo, home, conf)
    assert p.returncode == 0, p.stderr
    # the one difference: the scratch install ran with --no-plugins (the stack's LSP marketplace)
    assert summary(p.stdout) == (1, 0, 0), p.stdout
    assert re.search(r"\+ repo only\s+stack-plugins/\s+\(whole folder, \d+ files; install.sh --no-plugins", p.stdout)
    assert "installed %s (CLAUDE_CONFIG_DIR)" % os.path.realpath(conf) in p.stdout
    for area in ("agents", "rules", "skills", "hooks", "bin", "mcp", "magg", "magg catalog", "settings.json hooks",
                 "CLAUDE.md block"):
        assert "\n%s: in sync" % area in p.stdout, (area, p.stdout)
    # --config-dir wins over CLAUDE_CONFIG_DIR, as in a real install
    p2 = diff(repo, home, conf, "--config-dir", conf, env_conf=False)
    assert p2.returncode == 0 and summary(p2.stdout) == (1, 0, 0) and "(--config-dir)" in p2.stdout
    assert fingerprint(home, repo) == before, "--diff wrote something"


@needs_git
def test_seeded_drift_is_listed(installed):
    """Mutation proof: each kind of drift, on either side, appears as its own line; exit stays 0."""
    repo, home, conf = installed
    # installed side
    os.unlink(os.path.join(conf, "agents", "scout.md"))                                   # repo only
    os.makedirs(os.path.join(conf, "skills", "my-own-skill"))
    open(os.path.join(conf, "skills", "my-own-skill", "SKILL.md"), "w").write("---\nname: x\n---\n")
    with open(os.path.join(conf, "skills", "sqlite", "SKILL.md"), "a") as f:            # edited
        f.write("\nlocal edit\n")
    with open(os.path.join(conf, "hooks", "web_caps.py"), "a") as f:
        f.write("# tweak\n")
    open(os.path.join(conf, "bin", "my-tool"), "w").write("#!/bin/sh\n")
    with open(os.path.join(conf, "agents", "coder.md"), "a") as f:                      # rendered agent edited
        f.write("local edit\n")
    s = json.load(open(os.path.join(conf, "settings.json")))
    s["hooks"]["SessionEnd"] = []                                                         # wiring gone
    s["hooks"].setdefault("Stop", []).append({"hooks": [{"type": "command", "command": "/bin/echo mine"}]})
    json.dump(s, open(os.path.join(conf, "settings.json"), "w"), indent=2)
    m = json.load(open(os.path.join(conf, "magg", "config.json")))
    m["servers"]["docling"]["prefix"] = "changed"
    m["servers"]["mine"] = {"command": "x"}
    json.dump(m, open(os.path.join(conf, "magg", "config.json"), "w"), indent=2)
    # repo side
    shutil.copy(os.path.join(repo, "dot-config", "dot-claude", "agents", "oracle.md"), os.path.join(repo, "dot-config", "dot-claude", "agents", "zz-new.md"))
    with open(os.path.join(repo, "dot-config", "dot-claude", "rules", "claude-agent-stack.md"), "a") as f:
        f.write("- a new rule line\n")
    shutil.rmtree(os.path.join(repo, "dot-config", "dot-claude", "skills", "typography"))   # a stack skill retired: pruned

    before = fingerprint(home)
    p = diff(repo, home, conf)
    assert p.returncode == 0, p.stderr
    out = p.stdout
    for pat in (r"\+ repo only\s+agents/scout\.md",
                r"\+ repo only\s+agents/zz-new\.md",
                # the user's own skill (no manifest entry) is kept; a retired stack skill is not
                r"- installed only\s+skills/my-own-skill/\s+\(whole skill; yours: install\.sh keeps it\)",
                r"- installed only\s+skills/typography/\s+\(whole skill\)\n",
                r"~ differs\s+skills/sqlite/SKILL\.md\s+\(\+0 -2 lines to install; edited since the last install\)",
                r"~ differs\s+rules/claude-agent-stack\.md\s+\(\+1 -0 lines",
                r"~ differs\s+hooks/web_caps\.py",
                r"- installed only\s+bin/my-tool",
                r"\+ repo only\s+SessionEnd \[\*\] /bin/sh \"[^\"]+/bin/stack-hook\" stack_usage end",
                r"- installed only\s+Stop \[\*\] /bin/echo mine",
                r"~ differs\s+docling\s+\(entry differs\)",
                r"- installed only\s+mine",
                r"~ differs\s+agents/coder\.md\s+\(\+0 -1 lines to install; edited since the last install\)"):
        assert re.search(pat, out), pat + "\n" + out
    assert summary(out) == (4, 5, 5), out
    assert fingerprint(home) == before


def test_usage_errors_and_missing_target(tmp_path):
    home = str(tmp_path / "home")
    os.makedirs(home)
    for extra in (("--dry-run",), ("--yes",), ("--restore",), ("--mcp-plan",)):
        p = diff(ROOT, home, os.path.join(home, ".claude"), *extra)
        assert p.returncode == 2 and "--diff takes only --config-dir" in p.stderr, (extra, p.stderr)
    f = tmp_path / "afile"
    f.write_text("x")
    p = diff(ROOT, home, str(f))
    assert p.returncode == 2 and "is not a folder" in p.stderr
    p = diff(ROOT, home, os.path.join(home, "missing"))
    assert p.returncode == 0 and "nothing installed" in p.stdout
    assert not os.path.exists(os.path.join(home, "missing")) and os.listdir(home) == []


def test_staged_files_follow_install_sh():
    text = open(os.path.join(ROOT, "install.sh"), encoding="utf-8").read()
    staged = stack_diff.staged_files(text)
    assert staged["hooks/agent_guard.py"] == "dot-config/dot-claude/hooks/agent_guard.py"
    assert staged["hooks/stack_fanout_wire.py"] == "dot-config/dot-claude/hooks/stack_fanout_wire.py"
    assert staged["hooks/derive_thresholds.py"] == "tests/derive_thresholds.py"
    assert staged["bin/statusline.py"] == "dot-config/dot-claude/bin/statusline.py"
    assert staged["mcp/libdocs_mcp.py"] == "dot-config/dot-claude/mcp/libdocs_mcp.py"
    assert staged["magg/k8s-mcp.toml"] == "dot-config/dot-claude/magg/k8s-mcp.toml"
    for rel, src in staged.items():
        assert os.path.isfile(os.path.join(ROOT, src)), (rel, src)
    code = stack_diff.installer_code(text, {"__STACK_CACHE__": "/c"})
    assert "after-effects" in code["MACOS_ONLY_SERVERS"] and callable(code["drop_servers"])


def test_broken_installer_code_is_a_note_not_a_crash(tmp_path):
    text = open(os.path.join(ROOT, "install.sh"), encoding="utf-8").read().replace("def drop_servers(", "def renamed(")
    d = stack_diff.Diff(ROOT, str(tmp_path), {"__CLAUDE_DIR__": str(tmp_path)}, text)
    assert d.code is None and any("drop_servers" in n for n in d.notes)


@needs_git
def test_symlinked_config_dir_diffs_clean(tmp_path):
    """A dotfiles ~/.claude (a symlink): rendered paths name the link, as install.sh renders them."""
    repo = _tis._scratch_repo(str(tmp_path / "repo"))
    home = str(tmp_path / "home")
    os.makedirs(home)
    real = str(tmp_path / "dotfiles-claude")
    os.makedirs(real)
    conf = os.path.join(home, ".claude")
    os.symlink(real, conf)
    _tis._install(repo, home, conf, "--yes")
    p = diff(repo, home, conf)
    assert p.returncode == 0 and summary(p.stdout) == (1, 0, 0), p.stdout


def test_empty_config_dir_is_a_usage_error(tmp_path):
    home = str(tmp_path / "home")
    os.makedirs(home)
    p = diff(ROOT, home, "", "--config-dir=", env_conf=False)
    assert p.returncode == 2 and "--config-dir needs a path" in p.stderr, (p.stdout, p.stderr)


def test_malformed_install_files_become_notes_not_crashes(tmp_path):
    conf = tmp_path / "conf"
    (conf / "magg").mkdir(parents=True)
    (conf / "settings.json").write_text("[1]")
    (conf / ".stack-manifest.json").write_text("[]")
    (conf / "magg" / "config.json").write_text("[1]")
    (conf / "skills").write_text("not a folder")
    text = open(os.path.join(ROOT, "install.sh"), encoding="utf-8").read()
    d = stack_diff.Diff(ROOT, str(conf), {"__CLAUDE_DIR__": str(conf), "__STACK_CACHE__": "/c"}, text)
    d.run()
    assert d.manifest == {} and d.code is not None
    assert d.rows["magg catalog"] == [("?", "magg/config.json", "unreadable: 'list' object has no attribute 'get'")]
    assert any(r[0] == "+" for r in d.rows["settings.json hooks"])     # wiring read as empty, no crash
    assert d.rows["skills"][0][0] == "+"                               # a file where skills/ should be


@pytest.mark.skipif(os.geteuid() == 0, reason="root reads a mode-000 folder")
def test_an_area_that_raises_is_a_note_and_the_rest_still_runs(tmp_path):
    """run()'s per-area guard: an unreadable skills/ (listdir raises) becomes a note, later areas still run."""
    conf = tmp_path / "conf"
    (conf / "skills").mkdir(parents=True)
    text = open(os.path.join(ROOT, "install.sh"), encoding="utf-8").read()
    d = stack_diff.Diff(ROOT, str(conf), {"__CLAUDE_DIR__": str(conf), "__STACK_CACHE__": "/c"}, text)
    os.chmod(conf / "skills", 0)
    try:
        d.run()
    finally:
        os.chmod(conf / "skills", 0o755)
    assert any(n.startswith("skills: not compared (PermissionError") for n in d.notes), d.notes
    assert "skills" not in d.rows
    assert any(r[0] == "+" for r in d.rows["settings.json hooks"])     # a later area still compared


def test_tool_placeholders_match_consistently():
    m = stack_diff.Matcher({"__CLAUDE_DIR__": "/c"})
    assert m.same('cmd: "__UV__" run __CLAUDE_DIR__/x; again __UV__', 'cmd: "/opt/uv" run /c/x; again /opt/uv')
    assert not m.same('"__UV__" and __UV__', '"/opt/uv" and /other/uv')
    assert not m.same("__CLAUDE_DIR__/x", "/elsewhere/x")
    assert m.counts("a\n__UV__ b\n", "a\n/opt/uv c\n") == (1, 1)
