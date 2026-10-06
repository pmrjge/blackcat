"""lib/render_profile.py: the opt-in codex-astra profile (DESIGN.md §2.1, §7.6; the "codex-astra 6"
tests of §9)."""
from __future__ import annotations

import pytest

from _profile_helpers import ASTRA, STACK, TRUST, changed_paths, parts
from conftest import load_lib

rp = load_lib("render_profile")

SIX = {("agents", n, "config_file") for n in ASTRA}


def test_only_the_six_config_files_differ():
    out = rp.build(parts(), {})
    assert changed_paths(out["codex"], out["codex_astra"]) == SIX
    for n in ASTRA:
        assert out["codex_astra"]["agents"][n]["config_file"] == "%s/agents-astra/%s.toml" % (STACK, n)
        assert out["codex"]["agents"][n]["config_file"] == "%s/agents/%s.toml" % (STACK, n)


def test_full_copy_equals_codex_otherwise():
    out = rp.build(parts(hooks_state=TRUST), {"legacy_sandbox": True, "with_rollout_budget": True})
    a, c = out["codex_astra"], out["codex"]
    assert set(a) == set(c)
    for k in c:
        if k != "agents":
            assert a[k] == c[k], k
    assert a["hooks"]["state"] == TRUST          # a full copy: the guard and the carried trust too
    rest = {k: v for k, v in a["agents"].items() if k not in ASTRA}
    assert rest == {k: v for k, v in c["agents"].items() if k not in ASTRA}


def test_astra_copy_is_independent():
    out = rp.build(parts(), {})
    out["codex_astra"]["agents"][ASTRA[0]]["description"] = "changed"
    out["codex_astra"]["hooks"]["PreToolUse"][0]["matcher"] = "changed"
    assert out["codex"]["agents"][ASTRA[0]]["description"] != "changed"
    assert out["codex"]["hooks"]["PreToolUse"][0]["matcher"] == ".*"


def test_ide_overlay_holds_only_the_six_entries():
    out = rp.build(parts(hooks_state=TRUST), {"ide_default": True})
    ov = out["codex_astra_ide"]
    assert ov == {"agents": {n: {"config_file": "%s/agents-astra/%s.toml" % (STACK, n)} for n in ASTRA},
                  "hooks": {"state": TRUST}}      # the carried-over trust only (U1), no handler
    assert rp.build(parts(), {"ide_default": True})["codex_astra_ide"] == {"agents": ov["agents"]}


@pytest.mark.parametrize("ide", [False, True])
def test_no_astra_profile(ide):
    out = rp.build(parts(), {"no_astra_profile": True, "ide_default": ide})
    assert out["codex_astra"] is None and out["codex_astra_ide"] is None
    out = rp.build(parts(astra_entries={}), {"no_astra_profile": True, "ide_default": ide})
    assert out["codex_astra"] is None


def test_a_seventh_entry_fails():
    p = parts()
    p["astra_entries"]["coder"] = {"config_file": "%s/agents-astra/coder.toml" % STACK}
    assert len(p["astra_entries"]) == 7
    with pytest.raises(rp.BuildError, match="exactly 6"):
        rp.build(p, {})


def test_five_entries_fail():
    p = parts()
    del p["astra_entries"][ASTRA[0]]
    with pytest.raises(rp.BuildError, match="exactly 6"):
        rp.build(p, {})


@pytest.mark.parametrize("edit, match", [
    (lambda e: e.update({"description": "another"}), "only config_file"),
    (lambda e: e.update({"config_file": "%s/agents/ninja-coder.toml" % STACK}), "must end in"),
    (lambda e: e.update({"config_file": "/elsewhere/agents-astra/ninja-coder.toml"}), "next to"),
    (lambda e: e.update({"model": "gpt-6-astra"}), "unknown keys"),
])
def test_astra_entry_may_differ_only_in_config_file(edit, match):
    p = parts()
    edit(p["astra_entries"]["ninja-coder"])
    with pytest.raises(rp.BuildError, match=match):
        rp.build(p, {})


def test_astra_role_must_exist():
    p = parts()
    del p["astra_entries"]["planner"]
    p["astra_entries"]["ghost"] = {"config_file": "%s/agents-astra/ghost.toml" % STACK}
    with pytest.raises(rp.BuildError, match="not a role"):
        rp.build(p, {})
