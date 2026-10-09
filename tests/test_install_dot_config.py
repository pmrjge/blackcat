"""install.sh after the dot-config/ move (2026-10-07): dot-claude/ and equilibrium/ live under dot-config/ as
dot-claude and dot-equilibrium.

An install whose manifest records a commit from before the move still reads that commit's shipped
settings.json (at dot-claude/settings.json) and reviews prev..HEAD over the old path too, with each
moved file paired to its new path."""
import importlib.util
import json
import os
import subprocess

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

needs_git = pytest.mark.skipif(not os.path.exists(os.path.join(ROOT, ".git")), reason="needs the stack's git checkout")


# ---------------------------------------------------------------- a manifest commit from before the move
def _tis():
    spec = importlib.util.spec_from_file_location("_tis", os.path.join(HERE, "test_install_state.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _git(repo, *args, env=None, inp=None):
    p = subprocess.run(["git", "-c", "core.hooksPath=/dev/null", "-c", "commit.gpgsign=false", "-c", "user.name=t",
                        "-c", "user.email=t@example.invalid", "-C", repo, *args],
                       env=dict(os.environ, **(env or {})), input=inp, capture_output=True, text=True, check=True)
    return p.stdout.strip()


def _pre_move_commit(repo, tmp_path, settings_text):
    """A commit (off every branch, as the smoke test's N-SUPPLY one) with the pre-move layout: the
    shipped tree at dot-claude/ instead of dot-config/dot-claude/, its settings.json = settings_text."""
    idx = {"GIT_INDEX_FILE": str(tmp_path / "pre-move.idx")}
    _git(repo, "read-tree", "HEAD", env=idx)
    _git(repo, "rm", "--cached", "-r", "-q", "dot-config/dot-claude", env=idx)
    _git(repo, "read-tree", "--prefix=dot-claude/", "HEAD:dot-config/dot-claude", env=idx)
    blob = _git(repo, "hash-object", "-w", "--stdin", inp=settings_text)
    _git(repo, "update-index", "--cacheinfo", "100644,%s,dot-claude/settings.json" % blob, env=idx)
    tree = _git(repo, "write-tree", env=idx)
    return _git(repo, "commit-tree", tree, "-p", "HEAD", "-m", "pre-move layout")


@needs_git
def test_pre_move_manifest_commit_settings_and_supply_review_use_the_old_path(tmp_path):
    """The first install after the move, over one whose manifest (older than settings_permission_scalars)
    records a pre-move commit that shipped defaultMode bypassPermissions: the shipped mode still comes
    from <commit>:dot-claude/settings.json (else: "can't tell", and the old default would stay), and the
    supply review over <commit>..HEAD covers dot-claude/ too, -M pairing each moved file with its new
    path, so only the real edit counts (1 line), not the whole tree as new."""
    tis = _tis()
    repo = tis._scratch_repo(str(tmp_path / "repo"))
    shipped_text = open(os.path.join(repo, "dot-config", "dot-claude", "settings.json"), encoding="utf-8").read()
    shipped_mode = json.loads(shipped_text)["permissions"]["defaultMode"]
    assert shipped_mode != "bypassPermissions" and shipped_text.count('"defaultMode": "%s"' % shipped_mode) == 1
    pre = _pre_move_commit(repo, tmp_path, shipped_text.replace('"defaultMode": "%s"' % shipped_mode,
                                                                '"defaultMode": "bypassPermissions"'))
    with pytest.raises(subprocess.CalledProcessError):
        _git(repo, "cat-file", "-e", pre + ":dot-config/dot-claude")
    home = str(tmp_path / "home")
    os.makedirs(home)
    conf = os.path.join(home, ".claude")
    tis._install(repo, home, conf)
    mp = os.path.join(conf, ".stack-manifest.json")
    m = json.load(open(mp))
    m["commit"] = pre
    for k in ("settings_permission_scalars", "settings_permission_scalars_commit"):
        m.pop(k, None)
    json.dump(m, open(mp, "w"), indent=2)
    sp = os.path.join(conf, "settings.json")
    s = json.load(open(sp))
    s["permissions"]["defaultMode"] = "bypassPermissions"           # what that install left in place
    json.dump(s, open(sp, "w"), indent=2)

    out = tis._run_install(repo, home, conf, "--yes")
    log = out.stdout + out.stderr
    assert out.returncode == 0, (out.stdout[-3000:], out.stderr[-3000:])
    assert json.load(open(sp))["permissions"]["defaultMode"] == shipped_mode, log[-3000:]
    assert ('set permissions.defaultMode="%s" (was "bypassPermissions", the stack\'s earlier default)'
            % shipped_mode) in log, log[-3000:]
    assert "can't tell the stack's earlier default" not in log
    assert "changes to the stack's shipped files and installer since the last install (%s" % pre[:12] in log
    assert "{dot-claude => dot-config/dot-claude}/" in log, log[-3000:]
    assert " 1 insertion(+), 1 deletion(-)" in log, log[-3000:]
    assert ("diff -M %s HEAD -- dot-config/dot-claude install.sh lib requirements tests/lint_agents.py "
            "tests/derive_sched_model.py tests/derive_thresholds.py dot-claude\n" % pre[:12]) in log, log[-3000:]
