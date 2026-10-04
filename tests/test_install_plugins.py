"""install.sh step 10's Anthropic skill plugins (ANTHROPIC_PLUGINS, simplification phase 1A,
2026-10-04) and the skills prune's keep rules, run against a scratch HOME with the fake `claude`
(tests/fake-claude/claude: FAKE_CLAUDE_PLUGINS=1 writes enabledPlugins into the scratch config's
settings.json like the real CLI does, FAKE_CLAUDE_OFFLINE=1 fails every plugin install). Never the
real HOME: every run goes through test_install_state._run_install (HOME, CLAUDE_CONFIG_DIR, XDG
state and TMPDIR all scratch)."""
import hashlib
import importlib.util
import json
import os
import re
import subprocess

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
pytestmark = pytest.mark.skipif(not os.path.exists(os.path.join(ROOT, ".git")),
                                reason="needs the stack's git checkout")
OFFICIAL = "claude-plugins-official"
WANT = ["mcp-server-dev", "session-report", "skill-creator", "math-olympiad"]
IDS = sorted("%s@%s" % (p, OFFICIAL) for p in WANT)
BASE = ["--no-mcp", "--no-deps", "--no-profile"]


def _tis():
    spec = importlib.util.spec_from_file_location("_tis", os.path.join(ROOT, "tests", "test_install_state.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


tis = _tis()


@pytest.fixture(scope="module")
def repo(tmp_path_factory):
    return tis._scratch_repo(str(tmp_path_factory.mktemp("stack") / "repo"))


def _home(tmp_path):
    home = str(tmp_path / "home")
    os.makedirs(home)
    return home, os.path.join(home, ".claude")


def _run(repo, home, conf, *args, log=None, **env):
    extra = {"FAKE_CLAUDE_PLUGINS": "1"}
    if log:
        extra["FAKE_CLAUDE_LOG"] = log
    extra.update(env)
    p = tis._run_install(repo, home, conf, argv=[*BASE, *args], env_extra=extra)
    assert p.returncode == 0, (p.stdout[-3000:], p.stderr[-3000:])
    return p.stdout + p.stderr


def _calls(log):
    if not os.path.exists(log):
        return []
    return [json.loads(line) for line in open(log)]


def _plugin_calls(log, verb):
    """The ANTHROPIC_PLUGINS ids the fake claude saw `claude plugin <verb>` for."""
    return sorted(c[2] for c in _calls(log) if c[:2] == ["plugin", verb] and len(c) > 2 and c[2] in IDS)


def _manifest(conf):
    return json.load(open(os.path.join(conf, ".stack-manifest.json")))


def _settings(conf):
    return json.load(open(os.path.join(conf, "settings.json")))


def _doctor(conf):
    """stdout of the installed doctor.sh's "== Anthropic plugins" section (it reads only the manifest
    and settings.json: no network, no claude call)."""
    text = open(os.path.join(conf, "bin", "doctor.sh")).read()
    snippet = re.search(r'echo "== Anthropic plugins"\n.*?\nPY\n', text, re.S).group(0)
    p = subprocess.run(["/bin/bash", "-c", 'C="$1"; python3(){ command python3 -I "$@"; }\n' + snippet, "_", conf],
                       capture_output=True, text=True, timeout=60)
    assert p.returncode == 0 and not p.stderr, (p.stdout, p.stderr)
    return p.stdout


def _tree(root, skip=("tmp", "shim")):
    """{relative path: sha256 or 'dir' or 'link:<target>'} for everything below root."""
    out = {}
    for r, ds, fs in os.walk(root):
        rel_r = os.path.relpath(r, root)
        if rel_r.split(os.sep)[0] in skip:
            ds[:] = []
            continue
        for d in ds:
            p = os.path.join(r, d)
            out[os.path.relpath(p, root)] = "link:" + os.readlink(p) if os.path.islink(p) else "dir"
        for f in fs:
            p = os.path.join(r, f)
            out[os.path.relpath(p, root)] = ("link:" + os.readlink(p) if os.path.islink(p)
                                             else hashlib.sha256(open(p, "rb").read()).hexdigest())
    return out


def test_plugins_installed_once_recorded_and_idempotent(repo, tmp_path):
    home, conf = _home(tmp_path)
    log1, log2 = str(tmp_path / "c1.log"), str(tmp_path / "c2.log")
    out1 = _run(repo, home, conf, log=log1)
    assert _plugin_calls(log1, "install") == IDS, _calls(log1)
    assert "+ Anthropic skill plugins: mcp-server-dev session-report skill-creator math-olympiad" in out1
    m = _manifest(conf)
    assert m["plugins_installed"] == IDS and m["plugins_missing"] == [], m.get("plugins_installed")
    assert all(_settings(conf)["enabledPlugins"].get(i) is True for i in IDS)
    before = _tree(conf)
    bk = os.path.join(home, ".local", "state", "claude-agent-stack-backups")
    backups = sorted(os.listdir(bk))
    out2 = _run(repo, home, conf, log=log2)
    # second run: no install or enable for a plugin already enabled, nothing recorded again
    assert _plugin_calls(log2, "install") == [] and _plugin_calls(log2, "enable") == [], _calls(log2)
    assert "+ Anthropic skill plugins" not in out2
    assert _manifest(conf)["plugins_installed"] == IDS
    assert _tree(conf) == before
    assert sorted(os.listdir(bk)) == backups          # a run that changes nothing makes no backup


def test_dry_run_prints_would_and_changes_nothing(repo, tmp_path):
    home, conf = _home(tmp_path)
    _run(repo, home, conf, "--no-anthropic-plugins")
    before = _tree(home)
    log = str(tmp_path / "dry.log")
    out = _run(repo, home, conf, "--dry-run", log=log)
    for i in IDS:
        assert "  would: claude plugin install %s --scope user" % i in out, out[-3000:]
    assert _plugin_calls(log, "install") == [] and _plugin_calls(log, "enable") == []
    assert _tree(home) == before


def test_no_anthropic_plugins_skips_the_step(repo, tmp_path):
    home, conf = _home(tmp_path)
    log = str(tmp_path / "c.log")
    out = _run(repo, home, conf, "--no-anthropic-plugins", log=log)
    assert _plugin_calls(log, "install") == [], _calls(log)
    assert "Anthropic skill plugins skipped (--no-anthropic-plugins)" in out
    m = _manifest(conf)
    assert m["plugins_installed"] == [] and m["plugins_missing"] == []
    # doctor's section says so instead of a bare header
    assert _doctor(conf) == "== Anthropic plugins\n  ok    none recorded (installed with --no-anthropic-plugins)\n"


def test_offline_notes_missing_and_doctor_warns(repo, tmp_path):
    home, conf = _home(tmp_path)
    out = _run(repo, home, conf, FAKE_CLAUDE_OFFLINE="1")
    assert "! Anthropic plugins not installed: " + " ".join(
        "%s@%s" % (p, OFFICIAL) for p in WANT) in out, out[-3000:]
    m = _manifest(conf)
    assert m["plugins_missing"] == IDS and m["plugins_installed"] == []
    assert "  WARN  not installed: " + " ".join(IDS) in _doctor(conf)
    # you ran /plugin install for one, as the WARN says: it is no longer missing
    s = _settings(conf)
    s.setdefault("enabledPlugins", {})[IDS[0]] = True
    json.dump(s, open(os.path.join(conf, "settings.json"), "w"))
    out = _doctor(conf)
    assert "  WARN  not installed: " + " ".join(IDS[1:]) + " (" in out, out
    assert IDS[0] in out.split("ok    enabled: ")[1], out
    # back online: the next run installs them and doctor is satisfied
    _run(repo, home, conf)
    assert _manifest(conf)["plugins_missing"] == [] and _manifest(conf)["plugins_installed"] == IDS
    out = _doctor(conf)
    assert "WARN" not in out and "  ok    enabled: " + " ".join(IDS) in out, out


def test_mcp_server_dev_reenabled_after_the_old_dedupe_user_disable_kept(repo, tmp_path):
    """mcp-server-dev, disabled by an install that still shipped mcp-server-craft (plugins_deduped),
    is enabled again; a plugin you disabled yourself stays off."""
    home, conf = _home(tmp_path)
    _run(repo, home, conf)
    s = _settings(conf)
    s["enabledPlugins"]["mcp-server-dev@" + OFFICIAL] = False
    s["enabledPlugins"]["session-report@" + OFFICIAL] = False
    json.dump(s, open(os.path.join(conf, "settings.json"), "w"))
    mp = os.path.join(conf, ".stack-manifest.json")
    m = _manifest(conf)
    m["plugins_deduped"] = ["mcp-server-dev@" + OFFICIAL]
    json.dump(m, open(mp, "w"))
    log = str(tmp_path / "c.log")
    out = _run(repo, home, conf, log=log)
    assert _plugin_calls(log, "enable") == ["mcp-server-dev@" + OFFICIAL], _calls(log)
    assert _plugin_calls(log, "install") == []
    assert "= plugin session-report@%s: disabled by you, left off" % OFFICIAL in out
    assert _manifest(conf)["plugins_deduped"] == []
    assert _settings(conf)["enabledPlugins"]["session-report@" + OFFICIAL] is False


def test_plugin_you_uninstalled_is_not_reinstalled(repo, tmp_path):
    """`claude plugin uninstall` drops the enabledPlugins entry; the next ./install.sh leaves that
    plugin out (plugins_installed still names it) and doctor reports it without a WARN."""
    home, conf = _home(tmp_path)
    _run(repo, home, conf)
    gone = "session-report@" + OFFICIAL
    s = _settings(conf)
    del s["enabledPlugins"][gone]
    json.dump(s, open(os.path.join(conf, "settings.json"), "w"))
    log = str(tmp_path / "c.log")
    out = _run(repo, home, conf, log=log)
    assert _plugin_calls(log, "install") == [] and _plugin_calls(log, "enable") == [], _calls(log)
    assert "= plugin %s: uninstalled by you, left out" % gone in out, out[-3000:]
    assert gone not in _settings(conf)["enabledPlugins"]
    assert _manifest(conf)["plugins_installed"] == IDS
    doc = _doctor(conf)
    assert "WARN" not in doc and "  ok    uninstalled by you (./install.sh leaves them out): " + gone in doc, doc
    assert "  ok    enabled: " + " ".join(i for i in IDS if i != gone) + "\n" in doc, doc


def test_installed_settings_deny_edits_to_plugins(repo, tmp_path):
    home, conf = _home(tmp_path)
    _run(repo, home, conf, "--no-plugins")
    deny = _settings(conf)["permissions"]["deny"]
    assert "Edit(/%s/plugins/**)" % os.path.realpath(conf) in deny or "Edit(/%s/plugins/**)" % conf in deny, \
        [d for d in deny if "plugins" in d]


def test_prune_keeps_your_skill_dirs_and_edited_stack_files(repo, tmp_path):
    """The skills prune drops only files the manifest tracks and nobody edited: a skill directory of
    yours (nested files and an empty folder included), your file inside a shipped skill and an edited
    file of a retired stack skill survive; the retired skill's unedited file goes (the control)."""
    home, conf = _home(tmp_path)
    _run(repo, home, conf, "--no-plugins")
    sk = os.path.join(conf, "skills")

    def put(rel, text):
        os.makedirs(os.path.dirname(os.path.join(sk, rel)), exist_ok=True)
        with open(os.path.join(sk, rel), "w") as f:
            f.write(text)

    put("my-own/SKILL.md", "---\nname: my-own\ndescription: Use for my things\n---\nbody\n")
    put("my-own/references/notes.md", "mine\n")
    os.makedirs(os.path.join(sk, "my-own", "empty"))
    put("python-engineering/mine/notes.md", "mine too\n")
    put("retired/SKILL.md", "R\n")
    put("retired-edited/SKILL.md", "edited\n")
    m = _manifest(conf)
    m["files"]["skills/retired/SKILL.md"] = hashlib.sha256(b"R\n").hexdigest()        # unedited
    m["files"]["skills/retired-edited/SKILL.md"] = "0" * 64                           # edited since
    json.dump(m, open(os.path.join(conf, ".stack-manifest.json"), "w"))
    out = _run(repo, home, conf, "--no-plugins", "--yes")
    for rel in ("my-own/SKILL.md", "my-own/references/notes.md", "my-own/empty",
                "python-engineering/mine/notes.md", "retired-edited/SKILL.md"):
        assert os.path.exists(os.path.join(sk, rel)), (rel, out[-3000:])
    assert not os.path.exists(os.path.join(sk, "retired", "SKILL.md")), out[-3000:]
    assert "note: skills/my-own/: kept (not installed by the stack: yours or another tool's)" in out
    assert "note: skills/retired-edited/SKILL.md: kept (edited since the stack installed it)" in out
