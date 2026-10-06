"""models.toml and the effort map (DESIGN.md §2): the §2 table reproduced from the frontmatter, Luna one
level up capped at max, Sol identity, none/minimal/ultra never, out-of-set efforts stop the build."""
from __future__ import annotations

import pytest

from _agents_helpers import (LEVELS, MODELS_TOML, REPO, VENDORED_MODELS, ca, conversion, ctx_for,  # noqa: F401
                             frontmatter, models, raw_models)

SOL, LUNA = "gpt-6.1-sol", "gpt-6-luna"
# DESIGN.md §2, "Codex model | Effort | Agents" (blackcat: the profile's model and effort)
DESIGN_TABLE = {
    (SOL, "max"): {"ninja-coder"},
    (SOL, "xhigh"): {"main-coder", "mathematician", "planner", "proof-checker", "security-auditor"},
    (SOL, "high"): {"biochem-engineer", "claude-code-engineer", "code-reviewer", "cuda-engineer",
                    "data-scientist", "designer", "dl-engineer", "embedded-engineer", "game-engineer",
                    "go-engineer", "haskell-engineer", "hpc-engineer", "julia-engineer", "jvm-engineer",
                    "llm-engineer", "ml-engineer", "mlx-engineer", "node-engineer", "orchestrator",
                    "plan-reviewer", "procedural-3d-ui", "python-engineer", "quantum-engineer", "researcher",
                    "robotics-engineer", "rust-engineer", "security-engineer", "vfx-td"},
    (SOL, "medium"): {"cg-artist", "frontend-engineer", "image-director", "mobile-engineer", "motion-designer",
                      "rigger-animator", "sculptor-painter", "writer"},
    (SOL, "low"): {"oracle"},
    (LUNA, "xhigh"): {"data-engineer", "devops-engineer", "verifier"},
    (LUNA, "high"): {"blackcat", "browser-operator", "coder", "doc-specialist", "mcp-broker", "test-engineer",
                     "toolsmith"},
    (LUNA, "medium"): {"build-fixer", "claude-code-guide", "explore", "scout"},
}


@pytest.fixture(scope="module")
def converted(tmp_path_factory):
    return conversion(tmp_path_factory)


def test_design_table_reproduced_from_frontmatter(converted):
    ctx, out = converted
    got = {}
    for name, row in out["report"]["effort"].items():
        got.setdefault((row["model"], row["effort"]), set()).add(name)
    assert got == DESIGN_TABLE
    assert len(DESIGN_TABLE[(SOL, "high")]) == 28
    sol = sum(len(v) for (m, _), v in got.items() if m == SOL)
    luna = sum(len(v) for (m, _), v in got.items() if m == LUNA)
    assert (sol, luna) == (43, 14)
    for name, role in out["roles"].items():           # the role files carry the same values
        assert (role["model"], role["model_reasoning_effort"]) in {
            k for k, v in DESIGN_TABLE.items() if name in v}


def test_sol_identity_luna_one_level_up(converted):
    _ctx, out = converted
    for name, row in out["report"]["effort"].items():
        fm = frontmatter(name)
        assert row["stack_effort"] == fm["effort"]
        i = LEVELS.index(fm["effort"])
        want = LEVELS[i] if fm["model"] == "opus" else LEVELS[min(i + 1, len(LEVELS) - 1)]
        assert row["effort"] == want, name


def test_luna_max_stays_max_and_xhigh_reaches_max():
    m = models()
    assert ca.codex_effort("sonnet", "max", m) == "max"
    assert ca.codex_effort("sonnet", "xhigh", m) == "max"
    assert ca.codex_effort("sonnet", "low", m) == "medium"
    assert ca.codex_effort("opus", "max", m) == "max"
    assert ca.codex_effort("opus", "low", m) == "low"


def test_none_minimal_ultra_never_emitted(converted):
    _ctx, out = converted
    m = models()
    emitted = {ca.codex_effort(t, e, m) for t in ("opus", "sonnet") for e in LEVELS}
    emitted |= {r["model_reasoning_effort"] for r in out["roles"].values()}
    emitted |= {r["model_reasoning_effort"] for r in out["astra_roles"].values()}
    emitted.add(out["blackcat"]["effort"])
    assert emitted <= set(LEVELS) and not emitted & {"none", "minimal", "ultra"}
    for bad in ("none", "minimal", "ultra"):
        with pytest.raises(ca.BuildError, match=bad):
            ca.validate_models(models(effort={"levels": [bad] + LEVELS}))
        with pytest.raises(ca.BuildError):
            ca.codex_effort("opus", bad, m)


def test_models_toml_scale_tiers_and_offset():
    raw = raw_models()
    assert raw["effort"]["levels"] == LEVELS
    assert raw["effort"]["luna_effort_offset"] == 1
    assert raw["tiers"] == {"opus": SOL, "sonnet": LUNA}
    assert raw["roles"] == {"name_style": "hyphen"}


def test_out_of_set_effort_stops_the_build(tmp_path):
    m = models()
    m["accepted"][LUNA] = ["low", "medium", "high", "max"]            # no xhigh: data-engineer high -> xhigh
    with pytest.raises(ca.BuildError, match="not accepted by gpt-6-luna"):
        ca.convert(str(REPO), ctx_for(tmp_path), m)
    with pytest.raises(ca.BuildError, match="not on the stack's scale"):
        ca.codex_effort("opus", "extreme", models())


def test_blackcat_profile_effort_is_luna_high(converted):
    _ctx, out = converted
    assert frontmatter("blackcat")["effort"] == "medium"
    assert {k: out["blackcat"][k] for k in ("model", "effort")} == {"model": LUNA, "effort": "high"}


def test_accepted_sets_equal_vendored_catalog_minus_ultra():
    want = {m["slug"]: [x for x in m["supported_reasoning_levels"] if x != "ultra"]
            for m in VENDORED_MODELS["models"]}
    assert raw_models()["accepted"] == want
    assert MODELS_TOML.is_file()
