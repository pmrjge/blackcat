"""D3 (COMPARE_eq §12 A6.2): every call runs its agent's own frontmatter model. flags.json `model` pins the map
{agent type: alias}; this drift test keeps it equal to `dot-claude/agents/<type>.md` `model:` and complete for every
agent type the harness can launch. The agents directory: $EQ_AGENTS_DIR, else the repository layout beside the
harness (`../dot-claude/agents`); a staging copy without it skips the frontmatter half (the run that freezes the
package runs it with EQ_AGENTS_DIR set)."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

import pytest

import eq_harness as eh
from conftest import HARNESS, STAGE

DISK = json.loads((HARNESS / "flags.json").read_text())


def agents_dir() -> Path | None:
    for d in ([Path(os.environ["EQ_AGENTS_DIR"])] if os.environ.get("EQ_AGENTS_DIR") else []) + \
            [STAGE.parent / "dot-claude" / "agents"]:
        if d.is_dir():
            return d
    return None


def frontmatter_model(path: Path) -> str | None:
    text = path.read_text(encoding="utf-8")
    m = re.match(r"---\n(.*?)\n---\n", text, re.DOTALL)
    if not m:
        return None
    for ln in m.group(1).splitlines():
        if ln.startswith("model:"):
            return ln.split(":", 1)[1].strip().strip("\"'")
    return None


def launched_types(flags: dict) -> set[str]:
    """Every agent type a harness call can name: S* types, planner, selector, single verifier, equivalence agents,
    plan owners (G/EG nodes), and the runtime leader (E_rt)."""
    out = set(flags["s_star"].values()) | set(flags["plan_owner_types"]) | {"equilibrium"}
    out |= {flags["planner_type"], flags["selector_type"], flags["single_verifier_type"]}
    out |= {str(v["agent"]) for v in flags.get("equivalence", {}).values()}
    return out


@pytest.mark.parametrize("flags", [eh.DEFAULT_FLAGS, DISK], ids=["DEFAULT_FLAGS", "flags.json"])
def test_model_map_covers_every_launched_type_without_haiku(flags: dict) -> None:
    m = flags["model"]
    assert isinstance(m, dict) and launched_types(flags) <= set(m)
    assert all(v in ("opus", "sonnet") for v in m.values())  # aliases only; never haiku (user constraint)
    for agent in sorted(m):
        assert eh.model_for(agent, flags) == m[agent]
    assert DISK["model"] == eh.DEFAULT_FLAGS["model"] and DISK["model_decision"] == eh.DEFAULT_FLAGS["model_decision"]


def test_model_map_equals_agent_frontmatter() -> None:
    d = agents_dir()
    if d is None:
        pytest.skip("no dot-claude/agents beside this copy (set EQ_AGENTS_DIR)")
    want = {a: frontmatter_model(d / f"{a}.md") for a in eh.DEFAULT_FLAGS["model"]}
    missing = sorted(a for a in want if not (d / f"{a}.md").is_file())
    assert not missing, f"model map names agent types without an agent file: {missing}"
    assert want == eh.DEFAULT_FLAGS["model"], {a: (eh.DEFAULT_FLAGS["model"][a], v) for a, v in want.items()
                                                if v != eh.DEFAULT_FLAGS["model"][a]}


def test_model_for_rules() -> None:
    assert eh.model_for("x", {"model": "sonnet"}) == "sonnet"  # a pre-A6 plain string applies to every call
    assert eh.model_for("x", {}) is None and eh.model_for("x", {"model": ""}) is None
    with pytest.raises(ValueError, match="no entry"):
        eh.model_for("x", {"model": {"y": "opus"}})
    for bad in ({"model": {"x": "claude-haiku-x"}}, {"model": {"y": "Haiku"}}, {"model": "haiku"}):
        with pytest.raises(ValueError, match="haiku"):
            eh.model_for("x", bad)
