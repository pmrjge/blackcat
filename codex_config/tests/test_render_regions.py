"""lib/render.py and config.toml (DESIGN §7.6, --ide-default): splice, conflicts, drift, removal.

Each test renders a fresh scratch machine (in-process, fake codex never needed: --codex none). The
stage stands for the live CODEX_HOME after an apply once its manifest is written (Env.manifest), so
a second render sees the first one's regions and manifest exactly as a re-install would.
"""
from __future__ import annotations

import os
import stat
import tomllib

import pytest

from _render_helpers import Env, codex_state, config_region, region_docs, snapshot, toml

ROOT_ONLY = b'model_provider = "openai"\nfile_opener = "none"\n'
WITH_TABLES = (b'# my settings\nmodel_provider = "openai"\n\n[projects."/w"]\ntrust_level = "trusted"\n\n'
               b'[mcp_servers.mine]\ncommand = "mine"\n\n[hooks.state."/x/config.toml:pre_tool_use:0:0"]\n'
               b'trusted_hash = "h"\n')
CODEX_APPEND = b'\n[projects."/later"]\ntrust_level = "trusted"\n'


def env_with(config: bytes | None) -> Env:
    env = Env()
    if config is not None:
        (env.ch / "config.toml").write_bytes(config)
        (env.ch / "config.toml").chmod(0o600)
    env.new_stage()
    return env


def cfg(env) -> bytes:
    return (env.stage / "config.toml").read_bytes()


def test_off_by_default_config_bytes_unchanged():
    env = env_with(WITH_TABLES + b'model = "mine"\n')     # even a key the regions would hold
    env.ok()
    assert cfg(env) == WITH_TABLES + b'model = "mine"\n'
    r = env.work_json("regions.json")
    assert (r["ide_default"], r["A"], r["B"]) == (False, None, None)
    assert env.work_json("options.json")["ide_default_source"] == "default"


@pytest.mark.parametrize("user", [None, b"", ROOT_ONLY, WITH_TABLES], ids=["no-file", "empty", "root-keys", "tables"])
def test_splice(user):
    env = env_with(user)
    env.ok("--ide-default")
    data = cfg(env)
    assert data.startswith(config_region.BEGIN_A.encode() + b"\n")          # A at the very start
    assert data.rstrip(b"\n").endswith(config_region.END_B.encode())        # B at the very end
    assert config_region.remove(data) == (user or b"")                       # user bytes untouched
    a, b = region_docs(data)
    assert all(not isinstance(v, dict) for v in a.values()) and all(isinstance(v, dict) for v in b.values())
    user_doc = tomllib.loads((user or b"").decode())
    assert tomllib.loads(data.decode()) == config_region.merge(user_doc, config_region.merge(a, b))
    assert (a["model"], a["model_reasoning_effort"]) == ("gpt-6-luna", "high")
    assert set(b["hooks"]) == set(load_events()) and "state" not in b["hooks"]
    if user is None:
        assert stat.S_IMODE(os.stat(env.stage / "config.toml").st_mode) == 0o600
    r = env.work_json("regions.json")
    assert r["ide_default"] is True and (r["A"], r["B"]) == (
        config_region.region_sha(data)["A"], config_region.region_sha(data)["B"])
    keys = env.work_json("hook-keys.json")
    assert {k["source"] for k in keys} == {str(env.ch) + "/config.toml"} and len(keys) == 8


def load_events():
    from _render_helpers import hook_defs
    return hook_defs.EVENTS


def test_no_profile_file_carries_hooks_under_ide_default():
    env = env_with(None)
    env.ok("--ide-default")
    main = (env.stage / "codex.config.toml").read_text()
    assert toml(env.stage / "codex.config.toml") == {}
    assert all(ln.startswith("#") for ln in main.splitlines() if ln.strip())
    astra = toml(env.stage / "codex-astra.config.toml")
    assert set(astra) == {"agents"} and len(astra["agents"]) == 6
    assert "hooks" not in astra and "hooks" not in toml(env.stage / "codex.config.toml")
    assert codex_state.validate(str(env.stage)) == []


@pytest.mark.parametrize("user,key", [
    (b'model = "gpt-mine"\n', "model"),
    (b'approval_policy = "never"\n', "approval_policy"),
    (b'[features]\nnetwork_proxy = false\n', "features.network_proxy"),
    (b'[agents.coder]\ndescription = "mine"\n', "agents.coder.description"),
])
def test_conflict_stops_naming_the_key(user, key):
    env = env_with(user)
    before = snapshot(env.stage)
    rc, _, err = env.run("--ide-default")
    assert rc == 1 and key in err and "config.toml was left as it is" in err
    assert cfg(env) == user
    assert {k for k in before if k != "config.toml"} <= set(snapshot(env.stage))


def test_symlinked_config_toml_refused():
    env = env_with(None)
    real = env.home / "dotfiles-config.toml"
    real.write_bytes(ROOT_ONLY)
    (env.ch / "config.toml").symlink_to(real)
    env.new_stage()
    assert os.path.islink(env.stage / "config.toml")
    rc, _, err = env.run("--ide-default")
    assert rc == 1 and "symlink" in err
    assert real.read_bytes() == ROOT_ONLY and os.path.islink(env.stage / "config.toml")


def install_ide(user=WITH_TABLES) -> Env:
    env = env_with(user)
    env.ok("--ide-default")
    env.manifest()
    return env


def test_drift_stops_with_a_diff_unless_force():
    env = install_ide()
    data = cfg(env)
    edited = data.replace(b'model = "gpt-6-luna"\n', b'model = "gpt-via-slash-model"\n', 1)
    assert edited != data
    (env.stage / "config.toml").write_bytes(edited)
    rc, _, err = env.run("--ide-default")
    assert rc == 1 and "changed since the last install" in err and "--force" in err
    assert '-model = "gpt-via-slash-model"' in err and '+model = "gpt-6-luna"' in err
    assert cfg(env) == edited                                     # left as it was
    env.ok("--ide-default", "--force")
    assert cfg(env) == data
    assert any("--force" in w for w in env.work_json("build-report.json")["warnings"])


def test_drift_also_guards_removal():
    env = install_ide()
    data = cfg(env)
    (env.stage / "config.toml").write_bytes(data.replace(b'web_search = "disabled"', b'web_search = "live"', 1))
    rc, _, err = env.run("--no-ide-default")
    assert rc == 1 and "changed since the last install" in err


def test_unknown_regions_without_a_manifest_count_as_changed():
    env = install_ide()
    os.unlink(env.stage / ".stack-manifest.json")
    data = cfg(env)
    env.ok("--ide-default")                       # identical to what this run writes: no stop
    (env.stage / "config.toml").write_bytes(data.replace(b'"high"', b'"low"', 1))
    rc, _, err = env.run("--ide-default")
    assert rc == 1 and "region A" in err


def test_rerun_is_idempotent_and_keeps_codex_appends():
    env = install_ide()
    data = cfg(env) + CODEX_APPEND                # Codex writes [projects.*] after region B
    (env.stage / "config.toml").write_bytes(data)
    env.ok("--ide-default")
    new = cfg(env)
    assert config_region.remove(new) == WITH_TABLES + CODEX_APPEND
    assert new.rstrip(b"\n").endswith(config_region.END_B.encode())
    env.manifest()
    env.ok("--ide-default")
    assert cfg(env) == new


def test_no_ide_default_removes_exactly_the_regions():
    env = install_ide()
    (env.stage / "config.toml").write_bytes(cfg(env) + CODEX_APPEND)
    env.ok("--no-ide-default")
    assert cfg(env) == WITH_TABLES + CODEX_APPEND
    prof = toml(env.stage / "codex.config.toml")              # the full profile is back
    assert prof["model"] == "gpt-6-luna" and "PreToolUse" in prof["hooks"]
    r = env.work_json("regions.json")
    assert (r["ide_default"], r["A"], r["B"]) == (False, None, None)
    assert {k["source"] for k in env.work_json("hook-keys.json")} == {
        str(env.ch) + "/codex.config.toml", str(env.ch) + "/codex-astra.config.toml"}


def test_neither_flag_keeps_an_ide_install():
    env = install_ide()
    data = cfg(env)
    env.ok()
    assert cfg(env) == data
    opts = env.work_json("options.json")
    assert (opts["ide_default"], opts["ide_default_source"]) == (True, "kept")
    assert toml(env.stage / "codex.config.toml") == {}
    assert {k["source"] for k in env.work_json("hook-keys.json")} == {str(env.ch) + "/config.toml"}


def test_malformed_markers_stop_and_leave_the_file():
    bad = config_region.BEGIN_A.encode() + b'\nmodel = "x"\n'
    env = env_with(bad)
    rc, _, err = env.run("--ide-default")
    assert rc == 1 and "config.toml" in err
    assert cfg(env) == bad
    rc, _, _ = env.run()                         # neither flag: the file is read to find regions
    assert rc == 1 and cfg(env) == bad
