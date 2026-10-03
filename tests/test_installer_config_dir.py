"""install.sh's target selection (lib/install_state.py: config-dir, ask): precedence, path checks,
the banner, the confirmation decision and the answer parser. End-to-end runs: tests/install_smoke.sh
(section 19)."""
import io
import json
import os
import stat
import subprocess
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lib"))
import install_state as st  # noqa: E402


@pytest.fixture
def home(tmp_path):
    h = tmp_path / "home user"          # a space in every path below
    (h / ".claude").mkdir(parents=True)
    (h / ".ssh").mkdir()
    (h / ".ssh" / "id_ed25519").write_text("k")
    return str(h)


def resolve(home, flag=None, env="", cwd=None, **kw):
    return st.resolve_config_dir(flag or "", flag is not None, env, home, cwd or home,
                                 repos=kw.pop("repos", (ROOT,)), state_root=os.path.join(home, ".local", "state"),
                                 **kw)


# ---- precedence ----------------------------------------------------------------------------------

def test_default_when_nothing_given(home):
    r = resolve(home)
    assert r["source"] == "default" and r["path"] == os.path.join(home, ".claude")
    assert r["is_default"] and not r["nondefault"] and r["export"] == "keep"
    assert r["claude_json"] == os.path.join(home, ".claude.json")
    assert r["decision"] == "proceed" and not r["warn"]


def test_env_beats_default(home, tmp_path):
    env = str(tmp_path / "env dir")
    r = resolve(home, env=env, interactive=True)
    assert r["source"] == "env" and r["path"] == env
    assert r["claude_json"] == os.path.join(env, ".claude.json")
    assert r["decision"] == "ask" and any("CLAUDE_CONFIG_DIR is set" in x for x in r["reasons"])


def test_flag_beats_env(home, tmp_path):
    env, flag = str(tmp_path / "env"), str(tmp_path / "flag")
    r = resolve(home, flag=flag, env=env, interactive=True)
    assert r["source"] == "flag" and r["path"] == flag and r["export"] == "set"
    assert r["claude_json"] == os.path.join(flag, ".claude.json")
    assert any("points elsewhere" in x for x in r["reasons"])


def test_flag_naming_the_default_unsets_env(home, tmp_path):
    r = resolve(home, flag="~/.claude", env=str(tmp_path / "other"))
    assert r["is_default"] and r["export"] == "unset"
    assert r["claude_json"] == os.path.join(home, ".claude.json")


def test_flag_equal_to_env_keeps_it(home, tmp_path):
    d = str(tmp_path / "same")
    r = resolve(home, flag=d, env=d)
    assert r["export"] == "keep" and r["claude_json"] == os.path.join(d, ".claude.json")


def test_env_equal_to_default_moves_claude_json(home):
    r = resolve(home, env=os.path.join(home, ".claude"))
    assert r["is_default"] and r["nondefault"]
    assert r["claude_json"] == os.path.join(home, ".claude", ".claude.json")
    assert any("set to the default folder" in w for w in r["warn"])


def test_stack_claude_json_wins(home, tmp_path):
    r = resolve(home, flag=str(tmp_path / "x"), stack_claude_json="/elsewhere/c.json")
    assert r["claude_json"] == "/elsewhere/c.json"


def test_empty_flag_refused(home):
    with pytest.raises(st.ConfigDirError):
        resolve(home, flag="")


# ---- expansion -----------------------------------------------------------------------------------

def test_tilde_relative_and_dotdot(home, tmp_path):
    assert resolve(home, flag="~/alt dir")["path"] == os.path.join(home, "alt dir")
    cwd = str(tmp_path)
    assert resolve(home, flag="rel/c", cwd=cwd)["path"] == os.path.join(cwd, "rel", "c")
    assert resolve(home, flag=os.path.join(cwd, "a", "..", "b"))["path"] == os.path.join(cwd, "b")


def test_symlink_resolved_and_shown(home, tmp_path):
    real = tmp_path / "real cfg"
    real.mkdir()
    link = tmp_path / "link"
    link.symlink_to(real)
    r = resolve(home, flag=str(link))
    assert r["path"] == str(link) and r["real"] == os.path.realpath(str(real))
    assert any(line.startswith("  resolved: ") for line in r["banner"])


def test_dotdot_through_symlink_refused(home, tmp_path):
    (tmp_path / "deep" / "inner").mkdir(parents=True)
    (tmp_path / "ln").symlink_to(tmp_path / "deep" / "inner")
    with pytest.raises(st.ConfigDirError, match="symlink before a '..'"):
        resolve(home, flag=str(tmp_path / "ln" / ".." / "c"))


# ---- refusals ------------------------------------------------------------------------------------

@pytest.mark.parametrize("bad", ["/", "~", "~/.ssh", "~/.ssh/claude", "~/.gnupg", "~/Library/Keychains/x",
                                 "~/.config", "~/Documents", "/usr/local/claude", "/etc/claude",
                                 "/System/x", "/Users", "/tmp", "~/.local/state/claude-agent-stack-backups/x",
                                 "~/.local/state/claude-agent-stack"])
def test_unsafe_targets_refused(home, bad):
    with pytest.raises(st.ConfigDirError):
        resolve(home, flag=bad)


@pytest.mark.parametrize("bad", ["/tmp/a\nb", "/tmp/a\x00b", "/tmp/a\tb", '/tmp/a"b', "/tmp/$HOME",
                                 "/tmp/a`id`", "/tmp/a\\b"])
def test_unsafe_characters_refused(home, bad):
    with pytest.raises(st.ConfigDirError, match="control character"):
        resolve(home, flag=bad)


def test_parent_of_home_refused(home):
    with pytest.raises(st.ConfigDirError, match="home folder"):
        resolve(home, flag=os.path.dirname(home))


def test_inside_repo_refused_also_through_a_symlink(home, tmp_path):
    with pytest.raises(st.ConfigDirError, match="repo checkout"):
        resolve(home, flag=os.path.join(ROOT, "dot-claude"))
    with pytest.raises(st.ConfigDirError, match="repo checkout"):
        resolve(home, flag=ROOT)
    (tmp_path / "sneaky").symlink_to(os.path.join(ROOT, "lib"))
    with pytest.raises(st.ConfigDirError, match="repo checkout"):
        resolve(home, flag=str(tmp_path / "sneaky"))


def test_file_refused(home, tmp_path):
    f = tmp_path / "afile"
    f.write_text("x")
    with pytest.raises(st.ConfigDirError, match="not a directory"):
        resolve(home, flag=str(f))
    with pytest.raises(st.ConfigDirError, match="cannot be created"):
        resolve(home, flag=str(f / "below"))


@pytest.mark.skipif(os.geteuid() == 0, reason="root writes anywhere")
def test_read_only_dir_refused(home, tmp_path):
    ro = tmp_path / "ro"
    ro.mkdir()
    ro.chmod(stat.S_IRUSR | stat.S_IXUSR)
    try:
        with pytest.raises(st.ConfigDirError, match="not writable"):
            resolve(home, flag=str(ro))
        with pytest.raises(st.ConfigDirError, match="cannot be created"):
            resolve(home, flag=str(ro / "new" / "deeper"))
    finally:
        ro.chmod(0o700)


def test_missing_dir_under_writable_parent_ok(home, tmp_path):
    r = resolve(home, flag=str(tmp_path / "a" / "b" / "c"))
    assert r["kind"] == "missing" and r["decision"] == "proceed"


# ---- foreign folders and the decision ------------------------------------------------------------

def test_foreign_nonempty_dir(home, tmp_path):
    d = tmp_path / "photos"
    d.mkdir()
    (d / "cat.jpg").write_text("x")
    assert resolve(home, flag=str(d), interactive=True)["decision"] == "ask"
    for kw in ({}, {"yes": True}, {"no_prompt": True}):
        assert resolve(home, flag=str(d), **kw)["decision"] == "refuse"
    r = resolve(home, flag=str(d), quiet=True)
    assert r["decision"] == "warn" and any("non-empty folder" in w for w in r["warn"])


def test_foreign_dir_under_env_warns_but_proceeds(home, tmp_path):
    d = tmp_path / "ci target"
    d.mkdir()
    (d / ".install.log").write_text("x")           # what a CI run may write there first
    r = resolve(home, env=str(d))
    assert r["kind"] == "foreign" and r["decision"] == "proceed"
    assert any("beside what is there" in w for w in r["warn"])
    r = resolve(home, env=str(d), interactive=True)
    assert r["decision"] == "ask" and any("no Claude Code files" in x for x in r["reasons"])


CASE_INSENSITIVE = os.path.exists(ROOT.swapcase())


@pytest.mark.skipif(not CASE_INSENSITIVE, reason="case-sensitive volume")
@pytest.mark.parametrize("which", ["home", "ssh", "keychains", "repo"])
def test_case_variants_refused(home, which):
    os.makedirs(os.path.join(home, "Library", "Keychains"), exist_ok=True)
    t = {"home": home.swapcase(), "ssh": "~/.SSH", "keychains": "~/library/keychains/x",
         "repo": os.path.join(ROOT, "dot-claude").swapcase()}[which]
    with pytest.raises(st.ConfigDirError):
        resolve(home, flag=t, yes=True)


@pytest.mark.skipif(not CASE_INSENSITIVE, reason="case-sensitive volume")
def test_case_variant_of_default_is_default(home):
    r = resolve(home, flag="~/.CLAUDE")
    assert r["is_default"] and r["export"] == "unset"
    assert r["claude_json"] == os.path.join(home, ".claude.json")


def test_cli_output_cannot_be_forged_by_the_environment(home, tmp_path):
    env = dict(os.environ, HOME=home, CLAUDE_CONFIG_DIR="x\npath\t/", STACK_CLAUDE_JSON="j\npath\t/")
    p = subprocess.run([sys.executable, os.path.join(ROOT, "lib", "install_state.py"), "config-dir",
                        "1", str(tmp_path / "t"), "0", "0", "1", "0", ROOT], env=env,
                       capture_output=True, text=True)
    assert p.returncode == 0, p.stderr
    paths = [line for line in p.stdout.splitlines() if line.startswith("path\t")]
    assert paths == ["path\t" + str(tmp_path / "t")]


@pytest.mark.parametrize("marker", ["settings.json", ".claude.json", ".stack-manifest.json", "projects"])
def test_claude_markers_make_it_not_foreign(home, tmp_path, marker):
    d = tmp_path / "cfg"
    d.mkdir()
    (d / "junk").write_text("x")
    if marker == "projects":
        (d / marker).mkdir()
    else:
        (d / marker).write_text("{}")
    assert resolve(home, flag=str(d))["kind"] in ("claude", "stack")
    assert resolve(home, flag=str(d))["decision"] == "proceed"


def test_ds_store_only_is_empty(home, tmp_path):
    d = tmp_path / "e"
    d.mkdir()
    (d / ".DS_Store").write_text("x")
    assert st.dir_kind(str(d)) == "empty"


def test_default_dir_is_never_foreign(home):
    open(os.path.join(home, ".claude", "notes.txt"), "w").close()
    assert resolve(home)["decision"] == "proceed"


def test_differing_manifests_are_a_reason(home, tmp_path):
    d = tmp_path / "second"
    d.mkdir()
    with open(os.path.join(home, ".claude", ".stack-manifest.json"), "w") as f:
        json.dump({"repo": "/r", "commit": "aaaaaaa"}, f)
    with open(str(d / ".stack-manifest.json"), "w") as f:
        json.dump({"repo": "/r", "commit": "bbbbbbb"}, f)
    r = resolve(home, flag=str(d), interactive=True)
    assert any("both hold a stack install" in x for x in r["reasons"])
    assert any("another stack install" in b for b in r["banner"])


@pytest.mark.parametrize("kw,want", [
    ({"interactive": True}, "ask"),
    ({"interactive": False}, "proceed"),
    ({"interactive": True, "quiet": True}, "proceed"),
    ({"interactive": True, "yes": True}, "proceed"),
    ({"interactive": True, "no_prompt": True}, "proceed"),
])
def test_decision_for_a_nondefault_target(home, tmp_path, kw, want):
    assert resolve(home, flag=str(tmp_path / "alt"), **kw)["decision"] == want


def test_default_target_never_asks(home):
    assert resolve(home, interactive=True)["decision"] == "proceed"


# ---- banner, warning, question -------------------------------------------------------------------

def test_banner_and_warning_text(home, tmp_path):
    d = str(tmp_path / "alt dir")
    r = resolve(home, flag=d, shell="/bin/zsh", interactive=True)
    assert r["banner"][0] == "install target: " + d
    assert "chosen by: --config-dir" in r["banner"][1]
    assert any(".claude.json for it: " + os.path.join(d, ".claude.json") in b for b in r["banner"])
    text = "\n".join(r["warn"])
    assert "export CLAUDE_CONFIG_DIR='%s'" % d in text and "~/.zshrc" in text
    assert "reinstall with --config-dir" in text
    assert "~/.bash_profile" in "\n".join(resolve(home, flag=d, shell="/bin/bash")["warn"])
    assert any(line.startswith("  target: " + d) for line in r["ask"])


def test_profile_hint():
    assert st.profile_hint("/bin/zsh").startswith("~/.zshrc")
    assert st.profile_hint("/opt/homebrew/bin/bash").startswith("~/.bash_profile")
    assert "zsh: ~/.zshrc" in st.profile_hint("/usr/local/bin/fish")


@pytest.mark.parametrize("answer,ok", [("y\n", True), ("Y\n", True), ("yes\n", True), ("\n", False),
                                       ("n\n", False), ("", False), ("yep\n", False), (" y \n", True)])
def test_ask_yes_no(answer, ok):
    out = io.StringIO()
    assert st.ask_yes_no("Install? [y/N] ", io.StringIO(answer), out) is ok
    assert out.getvalue() == "Install? [y/N] "


def test_cli_ask_reads_stdin():
    for answer, rc in (("y\n", 0), ("\n", 1)):
        p = subprocess.run([sys.executable, os.path.join(ROOT, "lib", "install_state.py"), "ask", "Q? "],
                           input=answer, capture_output=True, text=True)
        assert p.returncode == rc and p.stdout == "Q? "


def test_cli_config_dir(home, tmp_path):
    env = dict(os.environ, HOME=home, SHELL="/bin/zsh", PWD=str(tmp_path))
    env.pop("CLAUDE_CONFIG_DIR", None)
    env.pop("STACK_CLAUDE_JSON", None)
    target = str(tmp_path / "t dir")
    p = subprocess.run([sys.executable, os.path.join(ROOT, "lib", "install_state.py"), "config-dir",
                        "1", target, "0", "0", "0", "0", ROOT], env=env, cwd=str(tmp_path),
                       capture_output=True, text=True)
    assert p.returncode == 0, p.stderr
    kv = {}
    for line in p.stdout.splitlines():
        k, v = line.split("\t", 1)
        kv.setdefault(k, v)
    assert kv["path"] == target and kv["source"] == "flag" and kv["export"] == "set"
    assert kv["decision"] == "proceed"
    p = subprocess.run([sys.executable, os.path.join(ROOT, "lib", "install_state.py"), "config-dir",
                        "1", "/", "0", "0", "0", "0", ROOT], env=env, capture_output=True, text=True)
    assert p.returncode == 2 and "refusing /" in p.stderr and p.stdout == ""
