"""Agent registration: every agent file is enumerated wherever the stack lists agent types, and
git-engineer (repository operations, 2026-10-10) is registered and shaped as decided.

A new agent touches: agents/<name>.md; agent_guard.py AGENTS, BlackCat's row, its POLICY row (LEAVES
for a leaf) and SOFT_LIMITS; blackcat.md's Agent(...) list and orchestrator.md's "May spawn"; the
effort table (agent_effort.json); the limits seed (stack_limits_seed.json: pool, turns, soft.agent,
hard.agent); the scheduler's SONNET_TYPES for a Sonnet agent; derive_thresholds.py TIER. lint_agents
and the guard self-test check some of these pairwise; this file checks them all from the agent files.

Run: uv run --python 3.13 --with pytest pytest -q tests/test_agent_registry.py
"""
import ast
import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CONF = ROOT / "dot-config" / "dot-claude"
AGENTS_DIR = CONF / "agents"
HOOKS = CONF / "hooks"
sys.path.insert(0, str(ROOT / "tests"))
import lint_agents  # noqa: E402


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


G = _load("agent_guard_registry", HOOKS / "agent_guard.py")
SCHED = _load("stack_sched_registry", HOOKS / "stack_sched.py")


def _frontmatter(name):
    return lint_agents.parse_frontmatter((AGENTS_DIR / f"{name}.md").read_text())


def _tier_of():
    """derive_thresholds.py TIER, read without importing it (it needs numpy and pandas)."""
    tree = ast.parse((ROOT / "tests" / "derive_thresholds.py").read_text())
    tier = next(ast.literal_eval(n.value) for n in tree.body if isinstance(n, ast.Assign)
                and getattr(n.targets[0], "id", "") == "TIER")
    return {t: k for k, v in tier.items() for t in v.split()}


FILES = sorted(f.stem for f in AGENTS_DIR.glob("*.md"))
SUBAGENTS = [a for a in FILES if a != "blackcat"]
EFFORT = json.loads((HOOKS / "agent_effort.json").read_text())["agents"]
SEED = json.loads((HOOKS / "stack_limits_seed.json").read_text())
BLACKCAT_AGENT_LIST = {c.lower() for c in lint_agents.get_tools(_frontmatter("blackcat")[0])[1]}
ORCH_MAY_SPAWN = set(lint_agents.get_may_spawn(_frontmatter("orchestrator")[1]))
TIER_OF = _tier_of()
SEED_POOL_OF = {t: p for p, ts in SEED["pools"].items() for t in ts}
# Sonnet agents missing from stack_sched SONNET_TYPES on main before git-engineer (a scheduling estimate
# only; fixing it is outside that change)
SONNET_TYPES_GAP = {"equilibrium"}


@pytest.mark.parametrize("agent", SUBAGENTS)
def test_every_agent_file_is_registered_everywhere(agent):
    missing = [where for where, ok in (
        ("agent_guard.py AGENTS", agent in G.AGENTS),
        ("agent_guard.py POLICY", agent in G.POLICY),
        ("agent_guard.py BlackCat row", agent in G._BLACKCAT_ROW),
        ("agent_guard.py SOFT_LIMITS", agent in G.SOFT_LIMITS),
        ("agent_guard.py LEAVES (empty POLICY row)", (agent in G.LEAVES) == (G.POLICY.get(agent) == [])),
        ("blackcat.md Agent(...)", agent in BLACKCAT_AGENT_LIST),
        ("orchestrator.md May spawn", agent == "orchestrator" or agent in ORCH_MAY_SPAWN),
        ("agent_effort.json", agent in EFFORT),
        ("derive_thresholds.py TIER", agent in TIER_OF),
        ("stack_limits_seed.json pools", agent in SEED_POOL_OF),
        ("stack_sched.py SONNET_TYPES (Sonnet agents)", agent in SONNET_TYPES_GAP or
         (lint_agents.get_inline(_frontmatter(agent)[0], "model") == "sonnet") == (agent in SCHED.SONNET_TYPES)),
        *((f"stack_limits_seed.json {fam}.{agent}", f"{fam}.{agent}" in SEED["vars"])
          for fam in ("turns", "soft.agent", "hard.agent")),
    ) if not ok]
    assert not missing, f"{agent} is missing from: {missing}"


def test_no_registry_names_an_agent_without_a_file():
    files = set(FILES)
    assert set(G.AGENTS) == files
    assert BLACKCAT_AGENT_LIST <= files and ORCH_MAY_SPAWN <= files
    assert set(EFFORT) <= files and set(SEED_POOL_OF) <= files and set(TIER_OF) <= files


# ---------------------------------------------------------------- git-engineer as decided
GE = "git-engineer"


def test_git_engineer_frontmatter():
    data, body = _frontmatter(GE)
    def get(k):
        return lint_agents.get_inline(data, k)
    assert get("name") == GE and get("model") == "sonnet" and get("effort") == "xhigh"
    assert get("maxTurns") == "80"                  # = turns.git-engineer in the limits seed
    tools = set(lint_agents.get_tools(data)[0])
    # pure git work: Bash, no file editing, no delegation (conflicts go back as NEXT: main-coder)
    assert tools == {"Read", "Bash", "Skill"}
    assert get("permissionMode") == "acceptEdits" and GE in lint_agents.GIT_TYPES
    assert lint_agents.permission_mode_problem(data) is None
    assert len(get("description").strip('"')) <= 120 and len(body) <= 1400   # prompt_budget NEW_CAPS leaf
    assert "main-coder" in body and "ASK USER" in body and "--ff-only" in body
    assert "`git-workflows`" in body and "references/repo-ops.md" in body


def test_git_engineer_policy():
    assert G.POLICY[GE] == [] and GE in G.LEAVES
    assert GE not in G.PLAN_SAFE_TYPES               # it writes git state: a builder for the plan gate
    assert GE not in G.READONLY_TYPES
    assert G.SOFT_LIMITS[GE] == G._SOFT_BUILDER and TIER_OF[GE] == "builder"
    assert GE in SCHED.SONNET_TYPES
    assert EFFORT[GE] == {"sonnet": "xhigh", "opus": "xhigh", "fable": "xhigh"}
    parents = sorted(p for p, row in G.POLICY.items() if GE in row)
    assert parents == ["blackcat", "orchestrator"]


def test_git_engineer_routing_and_skill():
    blackcat = _frontmatter("blackcat")[1]
    assert any("git-engineer" in ln and "main-coder" in ln and ln.lstrip().startswith("- Git operations")
               for ln in blackcat.splitlines())
    ref = CONF / "skills" / "git-workflows" / "references" / "repo-ops.md"
    assert ref.is_file() and "references/repo-ops.md" in (ref.parent.parent / "SKILL.md").read_text()
    text = ref.read_text()
    for must in ("merge-base --is-ancestor", "--ff-only", "rescue/", "--update-refs", "git add --"):
        assert must in text, must


def test_bash_only_writer_exception_is_narrow(tmp_path):
    """acceptEdits without Write/Edit is accepted for git-engineer with Bash, refused for it without
    Bash and for any other Bash-only agent."""
    def errors(name, tools):
        p = tmp_path / f"{name}.md"
        p.write_text("\n".join(["---", f"name: {name}", 'description: "A fixture agent."', "model: sonnet",
                                "maxTurns: 10", f"tools: {tools}", "permissionMode: acceptEdits",
                                "color: red", "---", "Body."]) + "\n")
        data, _ = lint_agents.parse_frontmatter(p.read_text())
        return lint_agents.permission_mode_problem(data)
    assert errors(GE, "Read, Bash, Skill") is None
    assert errors(GE, "Read, Skill") is not None
    assert errors("bash-only", "Read, Bash, Skill") is not None
