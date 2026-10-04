"""install.sh's removed options (cut 5b, 2026-10-04): the installer always prunes, so --no-prune is a
usage error, and --force is valid only with --restore. Both stop at option parsing: exit 2, one line
naming the fix, nothing written (HOME and the target stay empty)."""
import os
import subprocess

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INSTALL = os.path.join(ROOT, "install.sh")


def _run(tmp_path, *args):
    home = tmp_path / "home"
    home.mkdir()
    env = {"PATH": "/usr/bin:/bin", "HOME": str(home), "CLAUDE_CONFIG_DIR": str(home / ".claude"),
           "TMPDIR": str(tmp_path)}
    p = subprocess.run([INSTALL, *args], env=env, stdin=subprocess.DEVNULL, capture_output=True, text=True,
                       timeout=60, check=False)
    return p, home


@pytest.mark.parametrize("args, want", [
    (["--no-prune"], "--no-prune was removed: the installer always prunes"),
    (["--dry-run", "--no-prune"], "--no-prune was removed: the installer always prunes"),
    (["--no-prune", "--force"], "--no-prune was removed: the installer always prunes"),
    (["--force"], "--force works only with --restore"),
    (["--dry-run", "--force"], "--force works only with --restore"),
])
def test_removed_options_are_usage_errors_that_change_nothing(tmp_path, args, want):
    p, home = _run(tmp_path, *args)
    assert p.returncode == 2, (p.returncode, p.stdout[-500:], p.stderr[-500:])
    assert want in p.stdout + p.stderr
    assert not any(home.iterdir()), sorted(os.listdir(home))
    assert sorted(os.listdir(tmp_path)) == ["home"]          # no work dir, backup root or temp file


@pytest.mark.skipif(not os.path.exists(os.path.join(ROOT, ".git")), reason="needs the stack's git checkout")
def test_agents_prune_keeps_your_own_and_edited_agents(tmp_path):
    """With no --no-prune, the agents/ prune follows the skills rule: an agent the stack installed,
    no longer ships and nobody edited goes (backup); your own agents and stack agents you edited stay,
    named in the notes; an edited agent the stack still ships is replaced."""
    import hashlib
    import importlib.util
    import json
    spec = importlib.util.spec_from_file_location("_tis", os.path.join(ROOT, "tests", "test_install_state.py"))
    tis = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tis)
    repo = tis._scratch_repo(str(tmp_path / "repo"))
    home = str(tmp_path / "home")
    os.makedirs(home)
    conf = os.path.join(home, ".claude")
    tis._install(repo, home, conf)
    agents = os.path.join(conf, "agents")
    files = {"my-own.md": "---\nname: my-own\ndescription: mine\n---\nhello\n",
             "retired.md": "---\nname: retired\ndescription: old\n---\n",
             "retired-edited.md": "---\nname: retired-edited\ndescription: old, then edited\n---\n"}
    for fn, text in files.items():
        with open(os.path.join(agents, fn), "w") as f:
            f.write(text)
    with open(os.path.join(agents, "coder.md"), "a") as f:
        f.write("\n<!-- local edit -->\n")
    mp = os.path.join(conf, ".stack-manifest.json")
    m = json.load(open(mp))
    m["files"]["agents/retired.md"] = hashlib.sha256(files["retired.md"].encode()).hexdigest()   # unedited
    m["files"]["agents/retired-edited.md"] = "0" * 64                                            # edited since
    json.dump(m, open(mp, "w"))
    log = tis._install(repo, home, conf, "--yes")
    left = set(os.listdir(agents))
    assert "my-own.md" in left and "retired-edited.md" in left and "retired.md" not in left, sorted(left)
    assert "<!-- local edit -->" not in open(os.path.join(agents, "coder.md")).read()
    assert "  - agents/retired.md  (no longer shipped by the stack)" in log, log[-3000:]
    assert "note: agents/my-own.md: kept (not installed by the stack: yours)" in log
    assert "note: agents/retired-edited.md: kept (edited since the stack installed it)" in log
    assert "agents/retired.md" not in json.load(open(mp))["files"]


def test_help_names_force_only_with_restore_and_no_longer_no_prune():
    p = subprocess.run([INSTALL, "--help"], stdin=subprocess.DEVNULL, capture_output=True, text=True,
                       timeout=60, check=False)
    assert p.returncode == 0
    assert "--no-prune" not in p.stdout and ".new" not in p.stdout
    assert "--restore [DIR] --force" in p.stdout
