"""The opt-in codex-astra roles (DESIGN.md §2.1): only the six models.toml astra.agents move to
gpt-6-astra, with the fable column's effort; everything else is byte-equal to the codex roles."""
from __future__ import annotations

import json
import tomllib

import pytest

from _agents_helpers import (EFFORT_JSON, SIX, ca, conversion, ctx_for, models, raw_models,  # noqa: F401
                             scratch_src)
from conftest import load_lib

ASTRA = "gpt-6-astra"
emit = load_lib("toml_emit")


@pytest.fixture(scope="module")
def converted(tmp_path_factory):
    return conversion(tmp_path_factory)


def test_only_the_six_move(converted):
    _ctx, out = converted
    assert set(raw_models()["astra"]["agents"]) == SIX and len(raw_models()["astra"]["agents"]) == 6
    assert set(out["astra_roles"]) == SIX == set(out["astra_entries"])
    assert sorted(out["report"]["astra_roles"]) == sorted(SIX)
    assert all(r["model"] != ASTRA for r in out["roles"].values())     # the codex roles never use Astra
    assert out["blackcat"]["model"] != ASTRA


def test_astra_effort_is_the_fable_column(converted):
    _ctx, out = converted
    fable = {n: r["fable"] for n, r in json.loads(EFFORT_JSON.read_text())["agents"].items()}
    for name, role in out["astra_roles"].items():
        assert role["model"] == ASTRA
        assert role["model_reasoning_effort"] == fable[name]
    assert out["astra_roles"]["ninja-coder"]["model_reasoning_effort"] == "max"


def test_astra_roles_differ_only_in_model_and_effort(converted):
    ctx, out = converted
    for name, role in out["astra_roles"].items():
        base = out["roles"][name]
        assert list(role) == list(base)
        assert {k: v for k, v in role.items() if k not in ("model", "model_reasoning_effort")} == \
               {k: v for k, v in base.items() if k not in ("model", "model_reasoning_effort")}
        # byte-equal once emitted, but for those two lines
        a = [ln for ln in emit.dumps(role).splitlines() if not ln.startswith("model")]
        b = [ln for ln in emit.dumps(base).splitlines() if not ln.startswith("model")]
        assert a == b and tomllib.loads(emit.dumps(role)) == role
        assert out["astra_entries"][name] == {
            "description": out["agents_entries"][name]["description"],
            "config_file": "%s/stack/agents-astra/%s.toml" % (ctx["codex_home"], name)}


def test_fable_not_opus_column_is_read(tmp_path):
    """agent_effort.json's opus and fable agree for the six today, so a scratch copy tells them apart."""
    src = scratch_src(tmp_path, effort_edits={"ninja-coder": {"opus": "max", "fable": "high"},
                                              "planner": {"opus": "xhigh", "fable": "medium"}})
    out = ca.convert(str(src), ctx_for(tmp_path), models())
    assert out["astra_roles"]["ninja-coder"]["model_reasoning_effort"] == "high"
    assert out["astra_roles"]["planner"]["model_reasoning_effort"] == "medium"
    assert out["roles"]["ninja-coder"]["model_reasoning_effort"] == "max"      # codex role: frontmatter


@pytest.mark.parametrize("edit,needle", [
    ({"effort_edits": {"main-coder": {"fable": "ultra"}}}, "fable = 'ultra'"),
    ({"effort_edits": {"main-coder": {"fable": "none"}}}, "fable = 'none'"),
])
def test_fable_outside_astras_set_stops(tmp_path, edit, needle):
    src = scratch_src(tmp_path, **edit)
    with pytest.raises(ca.BuildError, match=needle):
        ca.convert(str(src), ctx_for(tmp_path), models())


def test_astra_list_must_name_roles(tmp_path):
    for bad in (["blackcat"], ["no-such-agent"]):
        with pytest.raises(ca.BuildError, match="is no role"):
            ca.convert(str(scratch_src(tmp_path / bad[0])), ctx_for(tmp_path), models(astra={"agents": bad}))
    with pytest.raises(ca.BuildError, match="duplicates"):
        ca.validate_models(models(astra={"agents": ["planner", "planner"]}))
