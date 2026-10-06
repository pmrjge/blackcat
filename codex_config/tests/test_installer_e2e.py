"""codex_config/install.sh end to end (DESIGN section 9, "installer 27"): the real installer, real render, real
engine, on a scratch HOME / CODEX_HOME / XDG_STATE_HOME / TMPDIR, the fake codex first on PATH.

Each test starts from an archived scratch tree ("fresh" = before any install, "installed" = after one
`install.sh --yes`; see _installer_helpers.Sandbox), so a test costs a few install runs, not a whole build.
The scratch git repository is built from the tree this file lives in, so the module also runs from the
temporary copy mutate.py makes.

Covered at other levels (not repeated): region splice/conflict/drift in the renderer (test_render_regions.py),
the CODEX_HOME refusal rules (test_codex_home.py), foreign skill entries in the link manager
(test_skill_links.py), the engine's --force-config (test_codex_state.py), flag parsing
(test_install_cli.py). The --ide-default list is test_installer_ide.py.

Seeded-bug proofs: tests/mutations/install_sh.json (one-line mutants of install.sh, each caught by the
named test) and tests/mutations/*_e2e.json (lib mutants the existing rows already seed, aimed at these tests).
"""
# ruff: noqa: F401, F811  (fixtures imported by name, used as arguments)
from __future__ import annotations

import os
import re
import stat
import subprocess
import tomllib
from pathlib import Path

import pytest

from _installer_helpers import (EXCLUDED_SKILLS, Sandbox, _sandbox, fresh, installed, out,  # noqa: F401
                                tree_hash)

AGENTS_BEGIN = "claude-agent-stack"


def _mode(p) -> int:
    return stat.S_IMODE(os.lstat(p).st_mode)


def _links(sbx):
    return sorted(p.name for p in sbx.skills.iterdir() if p.is_symlink())


# ---- snapshot --------------------------------------------------------------------------------------------
def test_edit_after_the_snapshot_is_never_executed(fresh):
    """An edit of the engine (and of installer modules) made after the snapshot point is not run: every
    later step reads $WORK/src."""
    marker = fresh.root / "engine-ran"
    targets = ("lib/install_state.py", "codex_config/lib/codex_state.py", "codex_config/lib/skill_links.py")
    cmd = "; ".join("printf '\\nopen(%%s, \"w\").write(\"x\")\\n' %s >> '%s'" % (
        repr(str(marker)).replace("'", "'\"'\"'"), fresh.repo / t) for t in targets)
    r = fresh.run("--yes", extra=fresh.hook_env(cmd), check=0)
    for t in targets:   # the hook did fire: the working tree holds the edit
        assert str(marker) in (fresh.repo / t).read_text(), t
    assert not marker.exists(), "an edit made after the snapshot was executed"
    assert "Backup:" in r.stdout and (fresh.ch / ".stack-manifest.json").is_file()


def test_uncommitted_edit_is_refused_and_nothing_changes(fresh):
    (fresh.repo / "lib" / "install_state.py").write_text(
        (fresh.repo / "lib" / "install_state.py").read_text() + "\n# local edit\n")
    before = fresh.fingerprint()
    r = fresh.run("--yes")
    assert r.returncode != 0
    assert "source snapshot" in r.stderr and "Nothing was changed" in r.stderr
    assert "install_state.py" in out(r)
    assert fresh.fingerprint() == before and not (fresh.ch / "stack").exists()


# ---- dry-run / diff --------------------------------------------------------------------------------------
@pytest.mark.parametrize("state", ["fresh", "installed"])
def test_dry_run_writes_nothing(state, request):
    sbx = request.getfixturevalue(state)
    before = (sbx.fingerprint(), tree_hash(sbx.root / "repo"))
    r = sbx.run("--dry-run", check=0)
    assert "Dry run done: nothing was applied." in r.stdout
    assert "Plan:" in r.stdout
    assert (sbx.fingerprint(), tree_hash(sbx.root / "repo")) == before
    assert not list((sbx.tmp).iterdir()), "the work folder was left behind"
    assert not sbx.backups() or state == "installed"


def test_dry_run_on_fresh_home_plans_the_whole_stack_without_a_backup(fresh):
    r = fresh.run("--dry-run", check=0)
    assert re.search(r"re-trust \d+ hook", r.stdout)
    assert not fresh.backups() and not (fresh.ch / "stack").exists() and _links(fresh) == []


def test_diff_names_the_areas_and_writes_nothing(fresh):
    before = fresh.fingerprint()
    r = fresh.run("--diff", check=0)
    for area in ("profiles:", "rules:", "AGENTS.md", "stack/agents", "stack/skills", "stack/policy", "stack/hooks",
                 "links:"):
        assert re.search(r"^%s" % re.escape(area), r.stdout, re.M), area
    assert re.search(r"^    \+ ", r.stdout, re.M)
    assert fresh.fingerprint() == before and not fresh.backups()


def test_diff_after_install_shows_no_difference_and_a_change_shows_in_its_area(installed):
    r = installed.run("--diff", check=0)
    assert not re.search(r"^    [-+~] ", r.stdout, re.M), r.stdout
    rules = installed.ch / "rules" / "claude-agent-stack.rules"
    rules.write_text(rules.read_text() + "# hand edit\n")
    before = installed.fingerprint()
    r = installed.run("--diff", check=0)
    sect = r.stdout.split("rules:", 1)[1].split("\nAGENTS.md", 1)[0]
    assert "hand edit" in sect and re.search(r"^    [-+~] ", sect, re.M)
    assert installed.fingerprint() == before


# ---- apply, idempotence, backup, restore ------------------------------------------------------------------
def test_second_run_plans_nothing_and_writes_nothing(installed):
    before = installed.fingerprint()
    n = len(installed.backups())
    r = installed.run("--yes", check=0)
    assert "Nothing to change" in r.stdout and "Backup:" not in r.stdout
    assert installed.fingerprint() == before and len(installed.backups()) == n
    d = installed.run("--dry-run", check=0)
    assert "no changes" in d.stdout and "no hook definition changed" in d.stdout


def test_apply_then_restore_gives_back_every_original_byte(fresh):
    ch = fresh.ch
    (ch / "AGENTS.md").write_text("# my notes\nkeep me\n")
    (ch / "config.toml").write_text('model = "mine"\n')
    (ch / "auth.json").write_text("{}")
    (ch / "auth.json").chmod(0o600)
    (ch / "rules").mkdir()
    (ch / "rules" / "mine.rules").write_text("# mine\n")
    before = tree_hash(ch, fresh.skills)
    fresh.run("--yes", check=0)
    assert tree_hash(ch, fresh.skills) != before and _links(fresh)
    assert len(fresh.backups()) == 1
    r = fresh.run("--restore", "latest", "--yes", check=0)
    assert "Restored from " in r.stdout
    assert tree_hash(ch, fresh.skills) == before
    assert _links(fresh) == [] and not (ch / "stack").exists()


def test_restore_undoes_the_skill_links_before_the_engine(installed):
    assert len(_links(installed)) > 50
    installed.run("--restore", "latest", "--yes", check=0)
    assert _links(installed) == []


def test_restore_dry_run_changes_nothing(installed):
    before = installed.fingerprint()
    r = installed.run("--restore", "--dry-run", check=0)
    assert "Dry run done: nothing was restored." in r.stdout
    assert installed.fingerprint() == before


# ---- drift between stage and plan -------------------------------------------------------------------------
def test_live_owned_file_edited_while_the_installer_runs_aborts(installed):
    """A live file the install owns changes between the staging and the plan: the run stops, nothing is
    applied, and the edit survives."""
    rules = installed.ch / "rules" / "claude-agent-stack.rules"
    base = rules.read_text()
    # make the plan non-empty so an apply would follow: a stack file differs from the render
    (installed.ch / "stack" / "policy" / "guard.json").write_text("{}\n")
    n = len(installed.backups())
    r = installed.run("--yes", extra=installed.hook_env("echo '# edited meanwhile' >> '%s'" % rules))
    assert r.returncode != 0
    assert "changed while the installer ran" in r.stderr and "claude-agent-stack.rules" in r.stderr
    assert rules.read_text() == base + "# edited meanwhile\n"
    assert (installed.ch / "stack" / "policy" / "guard.json").read_text() == "{}\n"
    assert len(installed.backups()) == n


# ---- stack.env ---------------------------------------------------------------------------------------------
def test_stack_env_644_is_reported_as_a_change_and_repaired_to_0600(installed):
    env = installed.ch / "stack.env"
    assert _mode(env) == 0o600
    env.chmod(0o644)
    d = installed.run("--dry-run", check=0)
    assert "no changes" not in d.stdout and "stack.env" in d.stdout
    assert _mode(env) == 0o644
    r = installed.run("--yes", check=0)
    assert "Nothing to change" not in r.stdout and "Backup:" in r.stdout
    assert _mode(env) == 0o600
    assert "Nothing to change" in installed.run("--yes", check=0).stdout


def test_stack_env_content_is_never_overwritten(installed):
    env = installed.ch / "stack.env"
    env.write_text("MY_KEY=secret-value\n")
    env.chmod(0o644)
    installed.run("--yes", check=0)
    assert env.read_text() == "MY_KEY=secret-value\n" and _mode(env) == 0o600


# ---- refusals ----------------------------------------------------------------------------------------------
def _refusal_dirs(sbx):
    (sbx.home / ".claude" / "agents").mkdir(parents=True)
    return {
        "inside ~/.claude": sbx.home / ".claude" / "agents",
        "~/.claude itself": sbx.home / ".claude",
        "HOME": sbx.home,
        "root": Path("/"),
        "system dir": Path("/etc"),
        "the repository": sbx.repo,
        "inside the repository": sbx.repo / "codex_config",
        "the backups root": sbx.state / "codex-agent-stack-backups",
    }


@pytest.mark.parametrize("which", ["inside ~/.claude", "~/.claude itself", "HOME", "root", "system dir",
                                   "the repository", "inside the repository", "the backups root"])
def test_refused_codex_homes_exit_2_and_touch_nothing(which, fresh):
    d = _refusal_dirs(fresh)[which]
    d.mkdir(parents=True, exist_ok=True)
    before = (fresh.fingerprint(), tree_hash(fresh.repo))
    r = subprocess.run(["bash", str(fresh.repo / "codex_config/install.sh"), "--codex-home", str(d), "--yes"],
                       capture_output=True, text=True, env=fresh.env(), cwd=str(fresh.tmp),
                       start_new_session=True)
    assert r.returncode == 2, out(r)
    assert "CODEX_HOME" in r.stderr or "codex" in r.stderr.lower()
    assert (fresh.fingerprint(), tree_hash(fresh.repo)) == before
    assert not (d / "stack").exists() and not (d / ".stack-manifest.json").exists()
    assert not fresh.backups()


def test_codex_home_from_the_environment_is_checked_too(fresh):
    (fresh.home / ".claude").mkdir()
    r = fresh.run("--yes", extra={"CODEX_HOME": str(fresh.home / ".claude")}, ch_flag=False)
    assert r.returncode == 2 and not (fresh.home / ".claude" / "stack").exists()


def test_a_foreign_skill_entry_stops_the_run_naming_it(fresh):
    mine = fresh.skills / "algorithm-design"
    mine.mkdir()
    (mine / "SKILL.md").write_text("mine\n")
    ch_before = tree_hash(fresh.ch)
    r = fresh.run("--yes")
    assert r.returncode != 0
    assert "algorithm-design" in out(r) and "Nothing was changed" in r.stderr
    assert (mine / "SKILL.md").read_text() == "mine\n"
    assert tree_hash(fresh.ch) == ch_before and not fresh.backups()
    assert [p.name for p in fresh.skills.iterdir()] == ["algorithm-design"]


def test_codex_older_than_the_floor_is_refused_before_any_change(fresh):
    before = fresh.fingerprint()
    r = fresh.run("--yes", extra={"FAKE_CODEX_VERSION": "0.150.0"})
    assert r.returncode == 1 and "older than 0.160.1" in r.stderr
    assert fresh.fingerprint() == before


# ---- carry-over, AGENTS.md ---------------------------------------------------------------------------------
HS_KEY = "/some/where/codex.config.toml:pre_tool_use:0:0"
HS_APPEND = '\n[hooks.state."%s"]\ntrusted_hash = "sha256:%s"\nenabled = false\n' % (HS_KEY, "ab" * 32)


def test_hooks_state_survives_a_rerun_in_both_profiles(installed):
    for name in ("codex.config.toml", "codex-astra.config.toml"):
        p = installed.ch / name
        p.write_text(p.read_text() + HS_APPEND.replace("/some/where/" + "codex.config", "/some/where/" + name[:-5]))
    # a changed stack definition so the re-run really rewrites the profile files
    installed.edit_repo("codex_config/lib/hook_defs.py", "TIMEOUT_S, SESSION_END_TIMEOUT_S = 10, 3",
                        "TIMEOUT_S, SESSION_END_TIMEOUT_S = 11, 3")
    installed.run("--yes", check=0)
    for name in ("codex.config.toml", "codex-astra.config.toml"):
        doc = tomllib.loads((installed.ch / name).read_text())
        key = "/some/where/%s:pre_tool_use:0:0" % name
        assert doc["hooks"]["state"][key] == {"trusted_hash": "sha256:" + "ab" * 32, "enabled": False}, name
        assert doc["hooks"]["PreToolUse"][0]["hooks"][0]["timeout"] == 11, "the rewrite did not happen"


def test_a_foreign_table_in_a_profile_file_stops_the_run_naming_it(installed):
    p = installed.ch / "codex.config.toml"
    p.write_text(p.read_text() + "\n[my_table]\nx = 1\n")
    before = installed.fingerprint()
    r = installed.run("--yes")
    assert r.returncode != 0 and "my_table" in r.stderr and "config.toml" in r.stderr
    assert installed.fingerprint() == before


def test_agents_md_block_is_spliced_around_the_users_text(fresh):
    agents = fresh.ch / "AGENTS.md"
    agents.write_text("# My own rules\nalways say hi\n")
    fresh.run("--yes", check=0)
    text = agents.read_text()
    assert text.startswith("# My own rules\nalways say hi\n") and AGENTS_BEGIN in text
    assert "<!-- claude-agent-stack: begin" in text and text.rstrip().endswith("<!-- claude-agent-stack: end -->")
    # user text added after the block, then a re-run with a changed stack: the block is replaced, the text stays
    agents.write_text(text + "\ntrailing user note\n")
    again = fresh.run("--yes", check=0)
    assert "Nothing to change" in again.stdout
    assert "trailing user note" in agents.read_text() and agents.read_text().startswith("# My own rules\n")


def test_agents_md_block_follows_a_template_change_and_keeps_user_text(fresh):
    agents = fresh.ch / "AGENTS.md"
    agents.write_text("# Mine\nuser line\n")
    fresh.run("--yes", check=0)
    first = agents.read_text()
    tpl = (fresh.repo / "codex_config" / "templates" / "AGENTS.block.md").read_text()
    fresh.edit_repo("codex_config/templates/AGENTS.block.md", tpl.splitlines()[0],
                    tpl.splitlines()[0] + " SPLICE-PROBE")
    fresh.run("--yes", check=0)
    second = agents.read_text()
    assert "SPLICE-PROBE" in second and "SPLICE-PROBE" not in first
    assert second.startswith("# Mine\nuser line\n") and second.count(AGENTS_BEGIN) == first.count(AGENTS_BEGIN)


def test_agents_override_md_warning_is_printed(fresh):
    (fresh.ch / "AGENTS.override.md").write_text("override\n")
    r = fresh.run("--yes", check=0)
    lines = [ln for ln in r.stdout.splitlines() if "AGENTS.override.md" in ln]
    assert lines and all(ln.lstrip().startswith("!") for ln in lines), r.stdout
    assert "shadows AGENTS.md" in " ".join(lines)
    assert (fresh.ch / "AGENTS.override.md").read_text() == "override\n"
    quiet = fresh.run("--yes", "--no-agents-md", check=0)
    assert quiet.returncode == 0


def test_no_override_warning_without_an_override_file(fresh):
    r = fresh.run("--yes", check=0)
    assert "AGENTS.override.md" not in r.stdout


# ---- re-trust -----------------------------------------------------------------------------------------------
def test_first_install_lists_every_hook_for_trust(fresh):
    r = fresh.run("--yes", check=0)
    m = re.search(r"re-trust (\d+) hook\(s\) in /hooks:\n((?:      .*\n)+)", r.stdout)
    assert m and int(m.group(1)) == 16
    keys = m.group(2).split()
    assert len(keys) == 16 and len(set(keys)) == 16
    assert all(re.search(r"/(codex|codex-astra)\.config\.toml:[a-z_]+:\d+:\d+$", k) for k in keys)
    assert str(fresh.ch) + "/codex.config.toml:pre_tool_use:0:0" in keys


def test_a_changed_hook_definition_is_listed_for_re_trust(installed):
    quiet = installed.run("--dry-run", check=0)
    assert "no hook definition changed" in quiet.stdout
    installed.edit_repo("codex_config/lib/hook_defs.py", "TIMEOUT_S, SESSION_END_TIMEOUT_S = 10, 3",
                        "TIMEOUT_S, SESSION_END_TIMEOUT_S = 11, 3")
    r = installed.run("--yes", check=0)
    assert "no hook definition changed" not in r.stdout
    m = re.search(r"re-trust: re-trust (\d+) hook\(s\) in /hooks:\n((?:      .*\n)+)", r.stdout)
    assert m, r.stdout
    keys = m.group(2).split()
    # SessionEnd keeps its 3 s timeout: its two hooks are not in the list
    assert len(keys) == 14 and not [k for k in keys if ":session_end:" in k]
    assert any(":pre_tool_use:" in k for k in keys)
    assert "no hook definition changed" in installed.run("--dry-run", check=0).stdout


# ---- stack-python, bytecode, skills ---------------------------------------------------------------------------
def test_stack_python_is_a_link_to_a_real_working_binary(installed):
    link = installed.ch / "stack" / "bin" / "stack-python"
    assert link.is_symlink()
    target = os.readlink(link)
    assert target.startswith("/") and target != "/usr/bin/python3"
    assert os.path.realpath(target) == target and os.access(target, os.X_OK)
    r = subprocess.run([str(link), "-I", "-c", "import sys, tomllib; print(sys.version_info[:2] >= (3, 11))"],
                       capture_output=True, text=True)
    assert r.returncode == 0 and r.stdout.strip() == "True"
    r = subprocess.run([str(link), "-I", str(installed.ch / "stack" / "hooks" / "codex_guard.py"), "--self-test"],
                       capture_output=True, text=True, env={"HOME": str(installed.home)})
    assert r.returncode == 0, r.stderr


def test_hooks_are_precompiled_with_checked_hash_bytecode(installed):
    cache = installed.ch / "stack" / "hooks" / "__pycache__"
    pycs = sorted(cache.glob("*.pyc"))
    names = {p.name.split(".")[0] for p in pycs}
    srcs = {p.stem for p in (installed.ch / "stack" / "hooks").glob("*.py")}
    assert srcs and srcs <= names, (srcs, names)
    for p in pycs:   # PEP 552: flags 0b11 = hash-based, checked
        assert int.from_bytes(p.read_bytes()[4:8], "little") == 3, p.name


def test_excluded_skills_are_never_linked_or_installed(installed):
    assert len(_links(installed)) > 50
    for name in EXCLUDED_SKILLS:
        assert not (installed.skills / name).exists() and not (installed.skills / name).is_symlink(), name
        assert not (installed.ch / "stack" / "skills" / name).exists(), name
        assert not (installed.ch / "stack" / "skill-modules" / name).exists(), name
    assert not any(n in installed.manifest()["links"]["links"] for n in EXCLUDED_SKILLS)


def test_links_point_into_the_stack_and_resolve(installed):
    for p in installed.skills.iterdir():
        t = os.readlink(p)
        assert t == str(installed.ch / "stack" / "skills" / p.name), p.name
        assert (p / "SKILL.md").is_file(), p.name


def test_skills_root_none_links_nothing(fresh):
    r = fresh.run("--yes", "--skills-root", "none", check=0)
    assert _links(fresh) == [] and (fresh.ch / "stack" / "skills").is_dir()
    assert "Backup:" in r.stdout


# ---- --restore after a Codex write to config.toml --------------------------------------------------------------
def test_restore_after_a_codex_style_append_refuses_without_force_config(fresh):
    fresh.run("--yes", "--ide-default", check=0)
    cfg = fresh.ch / "config.toml"
    cfg.write_text(cfg.read_text() + '\n[projects."/work/x"]\ntrust_level = "trusted"\n')
    before = fresh.fingerprint()
    r = fresh.run("--restore", "latest", "--yes")
    assert r.returncode != 0
    assert "--no-ide-default" in r.stderr and "--force-config" in r.stderr and "changed since the install" in r.stderr
    assert "Nothing was changed" in r.stderr
    assert fresh.fingerprint() == before and _links(fresh)


def test_restore_force_config_puts_the_saved_config_back(fresh):
    cfg = fresh.ch / "config.toml"
    cfg.write_text('my_setting = "mine"\n')
    fresh.run("--yes", "--ide-default", check=0)
    cfg.write_text(cfg.read_text() + '\n[projects."/work/x"]\ntrust_level = "trusted"\n')
    fresh.run("--restore", "latest", "--yes", "--force-config", check=0)
    assert cfg.read_text() == 'my_setting = "mine"\n' and _links(fresh) == []


# ---- --print-requirements ----------------------------------------------------------------------------------------
def test_print_requirements_writes_only_under_its_out_dir_and_never_runs_sudo(fresh):
    fakebin = fresh.root / "bin-sudo"
    fakebin.mkdir()
    sudo_log = fresh.root / "sudo-ran"
    (fakebin / "sudo").write_text('#!/bin/sh\necho "$@" >> "%s"\nexit 1\n' % sudo_log)
    (fakebin / "sudo").chmod(0o755)
    etc = Path("/etc/codex/requirements.toml")
    etc_before = (etc.exists(), etc.stat().st_mtime_ns if etc.exists() else None)
    before_home = fresh.fingerprint()
    before_repo = {p.relative_to(fresh.repo) for p in fresh.repo.rglob("*") if ".git" not in p.parts}
    path = str(fakebin) + os.pathsep + os.environ.get("PATH", "")
    r = fresh.run("--print-requirements", extra={"PATH": str(fakebin) + os.pathsep + str(
        Path(__file__).parent / "fake-codex") + os.pathsep + path}, check=0)
    assert "sudo install" in r.stdout and "/etc/codex/requirements.toml" in r.stdout
    assert not sudo_log.exists(), "sudo was run"
    assert fresh.fingerprint() == before_home
    new = {p.relative_to(fresh.repo) for p in fresh.repo.rglob("*") if ".git" not in p.parts} - before_repo
    build = Path("codex_config") / "build"
    assert new and all(p == build or build in p.parents for p in new), sorted(map(str, new))
    assert (fresh.repo / build / "requirements.toml").is_file() and (fresh.repo / build / "managed-hooks").is_dir()
    assert (etc.exists(), etc.stat().st_mtime_ns if etc.exists() else None) == etc_before
    assert not (fresh.ch / "stack").exists()
