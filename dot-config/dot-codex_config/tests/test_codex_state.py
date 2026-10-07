"""lib/codex_state.py: the engine driven for CODEX_HOME (DESIGN.md §7.2, §7.3, §7.6 restore)."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
from pathlib import Path

import pytest

from conftest import LIB, load_lib
from _foundation_helpers import run_py, write, write_json

cs = load_lib("codex_state")
cr = load_lib("config_region")
ist = cs.ist
STATE_PY = LIB / "codex_state.py"

A = 'model = "gpt-6-luna"\nmodel_reasoning_effort = "high"\n'
B = '[features]\nmulti_agent_v2 = false\n'
# a role file holds only ConfigToml keys: no name or description ({n} keeps the call sites uniform)
ROLE = ('model = "gpt-6.1-sol"\nmodel_reasoning_effort = "high"\n'
        'developer_instructions = """x{n}"""\n')
AGENTS_JSON = {"schema": 1, "agents": {"coder": {
    "spawn": [], "apply_patch": True, "shell": True, "spawn_tool": False, "mcp": [], "readonly": False,
    "web_ingesting": False, "installer": False, "max_tool_calls": None}},
    "blackcat": {"spawn": ["coder"], "mcp": [], "max_shell_reads_per_prompt": 3}, "builtin_types": ["default"]}


def guard_json(ch):
    return {"schema": 1, "codex_home": ch, "home": "/h", "state_dir": "/s", "stack": ch + "/stack",
            "protected_roots": [ch], "credentials": {"paths": [], "globs": []},
            "toolsmith_wrapper": ch + "/stack/bin/stack-install", "caps": {}, "image_max_px": 1920}


def tree(root: Path) -> dict:
    out = {}
    for p in sorted(root.rglob("*")):
        rel = str(p.relative_to(root))
        if p.is_symlink():
            out[rel] = ("l", os.readlink(p))
        elif p.is_file():
            out[rel] = ("f", hashlib.sha256(p.read_bytes()).hexdigest(), stat.S_IMODE(p.stat().st_mode))
    return out


def render(s: Path, ch: str, roles=("coder", "verifier"), skills=("s1", "s2"), regions=False):
    """What the render step would leave in the stage (a small stand-in): stack/ is owned whole."""
    shutil.rmtree(s / "stack", ignore_errors=True)
    for n in roles:
        write(s / "stack" / "agents" / ("%s.toml" % n), ROLE.format(n=n))
    for n in skills:
        write(s / "stack" / "skills" / n / "SKILL.md", "---\nname: %s\ndescription: x\n---\nbody\n" % n)
    write(s / "codex.config.toml", 'model = "gpt-6-luna"\n')
    write(s / "rules" / "claude-agent-stack.rules", 'prefix_rule(pattern=["git", "push"], decision="forbidden")\n')
    write_json(s / "stack" / "policy" / "agents.json", AGENTS_JSON)
    write_json(s / "stack" / "policy" / "guard.json", guard_json(ch))
    if regions:
        cfg = s / "config.toml"
        cfg.write_bytes(cr.splice(cfg.read_bytes() if cfg.exists() else b"", A, B))


def work_files(work: Path, links=None):
    write_json(work / "links.json", {"root": None, "links": {}} if links is None else links)
    write_json(work / "hook-keys.json", [{"key": "/c/codex.config.toml:pre_tool_use:0:0", "event": "PreToolUse",
                                          "fingerprint": "f1", "source": "/c/codex.config.toml"}])
    write_json(work / "regions.json", {"ide_default": True, "A": None, "B": None, "config_toml_sha256": None})
    write_json(work / "options.json", {"profile_name": "codex", "repo": "/r"})


@pytest.fixture
def env(scratch_home, tmp_path):
    ch = scratch_home["codex_home"]
    write(ch / "auth.json", '{"secret": 1}')
    write(ch / "config.toml", 'notify = ["say"]\n\n[projects."/w"]\ntrust_level = "trusted"\n')
    write(ch / "hooks.json", "{}")
    write(ch / "rules" / "default.rules", "x\n")
    write(ch / "stack.env", "KEY=1\n", 0o600)
    return {"ch": ch, "root": tmp_path / "backups", "work": tmp_path / "work", "n": [0], **scratch_home}


def install(env, regions=False, **kw):
    """stage, render, manifest, plan, apply (in-process); returns (stage, plan, backup dir)."""
    env["n"][0] += 1
    i = env["n"][0]
    ch, work = str(env["ch"]), env["work"] / str(i)
    s = work / "stage"
    s.mkdir(parents=True)
    snap = work / "snap.json"
    cs.stage(ch, str(s), str(snap))
    render(s, ch, regions=regions, **kw)
    work_files(work)
    cs.write_manifest(str(s), "a" * 40, str(work))
    rep = write_json(work / "report.json", {})
    assert cs.plan(ch, str(s), str(rep), str(work / "plan.json"), str(snap)) == 0
    bdir = cs.apply(ch, str(s), str(work / "plan.json"), str(env["root"]), "a" * 40, str(work / "out"), str(snap))
    return s, ist.load_json(str(work / "plan.json"), None), bdir


def restore(env, which="latest", **kw):
    env["n"][0] += 1
    work = env["work"] / ("r%d" % env["n"][0])
    work.mkdir(parents=True)
    return cs.restore(str(env["ch"]), which, str(env["root"]), str(work), "b" * 40, str(env["home"]), **kw)


# ---------------------------------------------------------------------------------------- scope


def test_engine_constants_set():
    assert ist.SCOPE_DIRS == ("stack",)
    for f in ("config.toml", "config.toml.tmp", "codex.config.toml", "stack.env", "AGENTS.md",
              ".stack-manifest.json", "rules/claude-agent-stack.rules", "codex-astra.config.toml.tmp"):
        assert ist.in_scope(f), f
    for f in ("auth.json", "hooks.json", "rules/default.rules", "agents/x.toml", "stack/bin/stack-python",
              "stack/hooks/__pycache__/x.pyc", "../x"):
        assert not ist.in_scope(f), f
    assert ist.WRITE_THROUGH == ("stack.env",)


def test_install_touches_only_scope_and_restore_round_trips(env):
    before = tree(env["ch"])
    s, plan, bdir = install(env)
    assert bdir and "stack/agents/coder.toml" in plan["added"]
    after = tree(env["ch"])
    for rel in ("auth.json", "hooks.json", "rules/default.rules", "config.toml"):
        assert after[rel] == before[rel]
    assert "config.toml" not in plan["changed"] + plan["added"]       # staged unchanged: no change
    restore(env)
    assert tree(env["ch"]) == before


def test_idempotent_second_run(env, capsys):
    install(env)
    capsys.readouterr()
    s, plan, bdir = install(env)
    assert (plan["added"], plan["changed"], plan["removed"]) == ([], [], []) and bdir == ""
    assert "no changes: CODEX_HOME already matches" in capsys.readouterr().out


def test_stack_env_chmod_644_shows_as_change_and_is_repaired(env):
    install(env)
    os.chmod(env["ch"] / "stack.env", 0o644)
    s, plan, _ = install(env)
    assert "stack.env" in plan["changed"]
    assert stat.S_IMODE(os.stat(env["ch"] / "stack.env").st_mode) == 0o600


def test_stack_env_symlink_written_through(env, tmp_path):
    dot = write(tmp_path / "dotfiles" / "stack.env", "KEY=1\n", 0o644)
    (env["ch"] / "stack.env").unlink()
    (env["ch"] / "stack.env").symlink_to(dot)
    install(env)
    assert (env["ch"] / "stack.env").is_symlink()
    assert stat.S_IMODE(dot.stat().st_mode) == 0o600


def test_region_change_plans_config_toml_and_backs_it_up(env):
    s, plan, bdir = install(env, regions=True)
    assert "config.toml" in plan["changed"]
    meta = ist.load_json(os.path.join(bdir, "backup.json"), None)
    assert "config.toml" in meta["entries"]
    live = (env["ch"] / "config.toml").read_bytes()
    assert cr.find(live)["A"] is not None
    m = json.loads((env["ch"] / ".stack-manifest.json").read_text())
    assert m["config_toml_sha256"] == hashlib.sha256(live).hexdigest()
    assert m["regions"] == cr.region_sha(live)


def test_dry_run_plan_writes_nothing(env, tmp_path):
    before = tree(env["ch"])
    s = tmp_path / "st"
    s.mkdir()
    cs.stage(str(env["ch"]), str(s))
    render(s, str(env["ch"]), regions=True)
    assert cs.plan(str(env["ch"]), str(s), str(write_json(tmp_path / "r.json", {})), str(tmp_path / "p.json")) == 0
    assert tree(env["ch"]) == before


def test_drift_between_plan_and_apply_aborts_in_codex_wording(env, tmp_path):
    ch, s = str(env["ch"]), tmp_path / "st"
    s.mkdir()
    snap = tmp_path / "snap.json"
    cs.stage(ch, str(s), str(snap))
    render(s, ch, regions=True)
    cs.plan(ch, str(s), str(write_json(tmp_path / "r.json", {})), str(tmp_path / "p.json"), str(snap))
    with open(env["ch"] / "config.toml", "a") as f:
        f.write('\n[projects."/new"]\ntrust_level = "trusted"\n')
    with pytest.raises(SystemExit) as ei:
        cs.apply(ch, str(s), str(tmp_path / "p.json"), str(env["root"]), "c", str(tmp_path / "o"), str(snap))
    assert "./install.sh --codex: config.toml changed while the installer ran" in str(ei.value.code)


def test_stale_tmp_leftovers_are_removed(env, tmp_path):
    write(env["ch"] / "codex.config.toml.tmp", "x")
    s, plan, _ = install(env)
    assert "codex.config.toml.tmp" in plan["removed"]


# ---------------------------------------------------------------------------------------- printing


def test_print_plan_summarizes_roles_and_skills(env, capsys):
    install(env)
    capsys.readouterr()
    s, plan, _ = install(env, roles=("coder", "planner"), skills=("s1", "s3"))
    out = capsys.readouterr().out
    assert "stack/agents/ 1 added, 0 updated, 1 removed" in out
    assert "stack/skills/ 1 added, 0 updated, 1 removed" in out
    assert "  - stack/skills/s2/  (" in out and "SKILL.md" not in out
    assert "updated: .stack-manifest.json" in out


def test_print_plan_hides_changed_role_files(capsys):
    plan = {"added": [], "changed": ["stack/agents/coder.toml", "stack/skills/s/SKILL.md", "codex.config.toml"],
            "removed": [], "replaced": [], "removed_listing": [], "notes": []}
    cs.print_plan(plan)
    out = capsys.readouterr().out
    assert "changes: 0 added, 3 updated, 0 removed" in out
    assert "updated: codex.config.toml\n" in out and "coder.toml" not in out


@pytest.mark.parametrize("msg,want", [
    ("install.sh --restore: /b backs up /x, not /y (set CLAUDE_CONFIG_DIR)",
     "./install.sh --codex --restore: /b backs up /x, not /y (pass --codex-home or set CODEX_HOME)"),
    ("install_state: refusing paths outside the config dir: 'x'", "codex_state: refusing paths outside CODEX_HOME: 'x'"),
    ("install.sh --restore: /b names paths outside the config scope (x)",
     "./install.sh --codex --restore: /b names paths outside the stack's part of CODEX_HOME (x)"),
    ("  no changes: the config dir already matches this stack version",
     "  no changes: CODEX_HOME already matches this stack version"),
    ("./install.sh --codex: x", "./install.sh --codex: x"),
])
def test_wording(msg, want):
    assert cs.wording(msg) == want


def test_restore_of_another_home_in_codex_wording(env, tmp_path):
    install(env)
    bdir = ist.backups_of(str(env["ch"]), str(env["root"]))[-1]
    other = tmp_path / "other"
    other.mkdir()
    work = tmp_path / "w"
    work.mkdir()
    with pytest.raises(SystemExit) as ei:
        cs.restore(str(other), bdir, str(env["root"]), str(work), "c", str(env["home"]))
    msg = str(ei.value.code)
    assert "CLAUDE_CONFIG_DIR" not in msg and "set CODEX_HOME" in msg and msg.startswith("./install.sh --codex")


# ---------------------------------------------------------------------------------------- restore guard


def test_restore_refuses_after_codex_append_unless_force_config(env):
    original = (env["ch"] / "config.toml").read_bytes()
    install(env, regions=True)
    with open(env["ch"] / "config.toml", "ab") as f:
        f.write(b'\n[hooks.state."/c/config.toml:pre_tool_use:0:0"]\ntrusted_hash = "h"\n')
    changed = (env["ch"] / "config.toml").read_bytes()
    with pytest.raises(SystemExit) as ei:
        restore(env)
    assert "--no-ide-default" in str(ei.value.code) and "--force-config" in str(ei.value.code)
    assert (env["ch"] / "config.toml").read_bytes() == changed
    restore(env, force_config=True)
    assert (env["ch"] / "config.toml").read_bytes() == original


def test_restore_of_unchanged_config_toml_needs_no_flag(env):
    original = (env["ch"] / "config.toml").read_bytes()
    install(env, regions=True)
    restore(env)
    assert (env["ch"] / "config.toml").read_bytes() == original


def test_restore_ignores_config_toml_when_backup_does_not_hold_it(env):
    install(env)
    with open(env["ch"] / "config.toml", "a") as f:
        f.write('\n[projects."/n"]\ntrust_level = "trusted"\n')
    kept = (env["ch"] / "config.toml").read_bytes()
    restore(env)
    assert (env["ch"] / "config.toml").read_bytes() == kept


@pytest.mark.parametrize("flags,force", [({"force_config": True}, False),
                                         ({"force_config": True, "force": True}, True)])
def test_engine_force_only_from_force(env, monkeypatch, flags, force):
    """--force-config never becomes the engine's --force (out-of-dir symlinks)."""
    install(env, regions=True)
    with open(env["ch"] / "config.toml", "a") as f:
        f.write("\n")
    seen = {}

    def fake(c, which, root, work, commit, home, dry=False, force=False):
        seen["force"] = force
        return which, "", {}

    monkeypatch.setattr(ist, "restore", fake)
    restore(env, **flags)
    assert seen["force"] is force


# ---------------------------------------------------------------------------------------- validate


def good_stage(tmp_path):
    s = tmp_path / "vs"
    render(s, "/c", regions=True)
    write(s / "AGENTS.md", "mine\n")
    return s


def test_validate_good_stage(tmp_path):
    assert cs.validate(str(good_stage(tmp_path))) == []


@pytest.mark.parametrize("breakage,needle", [
    (lambda s: write(s / "codex.config.toml", "x = = 1\n"), "codex.config.toml: does not parse"),
    (lambda s: write(s / "stack/agents/coder.toml", 'name = "coder"\n'), "stack/agents/coder.toml: no model"),
    (lambda s: write(s / "stack/agents/coder.toml", ROLE.format(n="") + 'name = "coder"\n'),
     "stack/agents/coder.toml: key name is not a Codex config key"),
    (lambda s: write(s / "stack/agents/coder.toml", ROLE.format(n="") + 'description = "d"\n'),
     "stack/agents/coder.toml: key description is not a Codex config key"),
    (lambda s: write(s / "stack/agents-astra/coder.toml", ROLE.format(n="") + 'sandbox_modes = "x"\n'),
     "stack/agents-astra/coder.toml: key sandbox_modes is not a Codex config key"),
    (lambda s: write(s / "stack/agents/coder.toml", 'model = "m"\ndeveloper_instructions = "x"\n'),
     "stack/agents/coder.toml: no model_reasoning_effort"),
    (lambda s: write(s / "rules/claude-agent-stack.rules", "x __UV__\n"), "placeholder __UV__"),
    (lambda s: write(s / "codex.config.toml", 'x = "{{model}}"\n'), "placeholder {{model}}"),
    (lambda s: write(s / "stack/skills/s1/SKILL.md", "__CLAUDE_DIR__/x\n"), "s1/SKILL.md: unresolved placeholder"),
    (lambda s: write_json(s / "stack/policy/agents.json", {"schema": 1, "agents": {"coder": {}}}), "agents.coder.shell"),
    (lambda s: write_json(s / "stack/policy/guard.json", {"schema": 2}), "guard.json: schema is not 1"),
    (lambda s: (s / "stack/policy/guard.json").unlink(), "guard.json: missing"),
    (lambda s: write(s / "config.toml", cr.BEGIN_A + "\n"), "config.toml:"),
])
def test_validate_finds_problems(tmp_path, breakage, needle):
    s = good_stage(tmp_path)
    breakage(s)
    problems = cs.validate(str(s))
    assert any(needle in p for p in problems), problems


def test_validate_role_keys_are_the_three_codex_keys(tmp_path):
    """Required: model, model_reasoning_effort, developer_instructions; never name or description
    (the vendored ConfigToml has neither, and additionalProperties is false)."""
    schema = json.loads((Path(cs.CONFIG_SCHEMA)).read_text())
    assert schema["additionalProperties"] is False
    assert set(cs.REQUIRED_ROLE_KEYS) == {"model", "model_reasoning_effort", "developer_instructions"}
    assert set(cs.REQUIRED_ROLE_KEYS) <= set(schema["properties"])
    assert not {"name", "description"} & set(schema["properties"])
    s = good_stage(tmp_path)
    write(s / "stack/agents-astra/coder.toml", ROLE.format(n="a"))
    assert cs.validate(str(s)) == []


def test_validate_fails_closed_without_the_schema(tmp_path, monkeypatch):
    monkeypatch.setattr(cs, "CONFIG_SCHEMA", str(tmp_path / "missing.json"))
    assert any("role keys not checked" in p for p in cs.validate(str(good_stage(tmp_path))))


def test_validate_ignores_code_samples_in_skills_and_user_config(tmp_path):
    s = good_stage(tmp_path)
    write(s / "stack/skills/s1/SKILL.md", "uses: ${{ secrets.TOKEN }} and __INIT__\n")
    with open(s / "config.toml", "a") as f:
        f.write('\n[mine]\nx = "{{not ours}}"\n')
    assert cs.validate(str(s)) == []


# ---------------------------------------------------------------------------------------- manifest, retrust


def test_manifest_contents(tmp_path):
    s = good_stage(tmp_path)
    write(s / "stack.env", "K=1\n")
    work = tmp_path / "w"
    work_files(work, {"root": "/h/.agents/skills", "links": {"s1": "/c/stack/skills/s1"}})
    m = cs.write_manifest(str(s), "f" * 40, str(work))
    on_disk = json.loads((s / ".stack-manifest.json").read_text())
    assert on_disk == m
    assert m["format"] == 1 and m["installer"] == "codex_config" and m["commit"] == "f" * 40
    assert "stack/agents/coder.toml" in m["files"] and "codex.config.toml" in m["files"]
    assert not {"config.toml", "AGENTS.md", "stack.env", ".stack-manifest.json"} & set(m["files"])
    assert all(ist.in_scope(r) for r in m["files"])                  # what install_state accepts
    data = (s / "config.toml").read_bytes()
    assert m["config_toml_sha256"] == hashlib.sha256(data).hexdigest()
    assert m["regions"] == cr.region_sha(data) and m["ide_default"] is True
    assert m["links"]["links"] == {"s1": "/c/stack/skills/s1"} and m["hooks"][0]["fingerprint"] == "f1"
    assert m["astra"] is False and m["profile_name"] == "codex" and m["repo"] == "/r"


def test_symlinked_user_config_toml_is_never_read_through(tmp_path):
    s = good_stage(tmp_path)
    dot = write(tmp_path / "dotfiles" / "config.toml", 'x = "{{not checked}}"\n')
    (s / "config.toml").unlink()
    (s / "config.toml").symlink_to(dot)
    assert cs.validate(str(s)) == []
    work = tmp_path / "w"
    work_files(work)
    m = cs.build_manifest(str(s), "c", str(work))
    assert m["config_toml_sha256"] is None and m["regions"] == {"A": None, "B": None}


def test_manifest_rejects_bad_work_files(tmp_path):
    s = good_stage(tmp_path)
    work = tmp_path / "w"
    work_files(work)
    write_json(work / "hook-keys.json", [{"key": 1}])
    with pytest.raises(SystemExit):
        cs.build_manifest(str(s), "c", str(work))


def test_retrust_lists_new_and_changed_keys():
    old = {"hooks": [{"key": "k1", "fingerprint": "a"}, {"key": "k2", "fingerprint": "b"}]}
    new = {"hooks": [{"key": "k1", "fingerprint": "a"}, {"key": "k2", "fingerprint": "B"},
                     {"key": "k3", "fingerprint": "c"}]}
    assert cs.retrust(old, new) == ["k2", "k3"]
    assert cs.retrust(None, new) == ["k1", "k2", "k3"]


# ---------------------------------------------------------------------------------------- CLI


def cli_env(sh):
    e = dict(os.environ)
    e.update(HOME=str(sh["home"]), CODEX_HOME="", XDG_STATE_HOME=str(sh["state"]))
    return e


def test_cli_home(scratch_home, tmp_path):
    r = run_py(STATE_PY, "home", "0", "", env=cli_env(scratch_home), cwd=str(scratch_home["home"]))
    assert r.returncode == 0, r.stderr
    kv = [line.split("\t", 1) for line in r.stdout.splitlines()]
    assert ["path", str(scratch_home["codex_home"])] in kv and ["source", "default"] in kv and ["created", "0"] in kv
    r = run_py(STATE_PY, "home", "1", str(scratch_home["home"] / ".claude"), env=cli_env(scratch_home))
    assert r.returncode == 2 and "Nothing was changed" in r.stderr and r.stdout == ""


def test_cli_full_cycle(env, tmp_path):
    e = cli_env(env)
    ch, root, w = str(env["ch"]), str(env["root"]), tmp_path / "cw"
    s = w / "stage"
    w.mkdir()
    before = tree(env["ch"])
    assert run_py(STATE_PY, "stage", ch, s, w / "snap.json", env=e).returncode == 0
    render(s, ch, regions=True)
    work_files(w)
    assert run_py(STATE_PY, "validate", s, env=e).returncode == 0
    assert run_py(STATE_PY, "manifest", s, "d" * 40, w, env=e).returncode == 0
    write_json(w / "report.json", {})
    r = run_py(STATE_PY, "plan", ch, s, w / "report.json", w / "plan.json", w / "snap.json", env=e)
    assert r.returncode == 0 and "stack/agents/ 2 added" in r.stdout and "config dir" not in r.stdout
    r = run_py(STATE_PY, "apply", ch, s, w / "plan.json", root, "d" * 40, w / "out", w / "snap.json", env=e)
    assert r.returncode == 0, r.stderr
    bdir = (w / "out").read_text()
    assert run_py(STATE_PY, "latest", ch, root, env=e).stdout.strip() == bdir
    r = run_py(STATE_PY, "retrust", "-", env["ch"] / ".stack-manifest.json", env=e)
    assert r.stdout.split() == ["/c/codex.config.toml:pre_tool_use:0:0"]
    (w / "rw").mkdir()
    r = run_py(STATE_PY, "restore", ch, "latest", root, w / "rw", "e" * 40, env["home"], env=e)
    assert r.returncode == 0, r.stderr
    assert tree(env["ch"]) == before
    assert json.loads((w / "rw" / "restore.json").read_text())["backup"] == bdir
    r = run_py(STATE_PY, "new-backup", ch, root, "e" * 40, env=e)
    assert r.returncode == 0 and os.path.isdir(r.stdout.strip())


def test_cli_usage_errors():
    assert run_py(STATE_PY, "plan", "x").returncode == 2
    assert run_py(STATE_PY, "nope").returncode == 2
    assert run_py(STATE_PY, "restore", "a", "b", "c", "d", "e", "f", "--bogus").returncode == 2


def test_manifest_options_leave_out_how_the_run_was_invoked():
    """A flagless re-run after --ide-default/--no-ide-default (or a --force run) installs the same bytes:
    its manifest must be byte-equal, so ide_default_source and the run-only flags stay out."""
    opts = {"profile_name": "codex", "ide_default": True, "ide_default_source": "flag",
            "flags": {"ide_default": True, "no_ide_default": False, "force": True, "no_mcp": False}}
    kept = dict(opts, ide_default_source="kept", flags=dict(opts["flags"], ide_default=False, force=False))
    assert cs.manifest_options(opts) == cs.manifest_options(kept)
    assert cs.manifest_options(opts) == {"profile_name": "codex", "ide_default": True, "flags": {"no_mcp": False}}
