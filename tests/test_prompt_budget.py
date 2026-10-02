"""tests/prompt_budget.py: the static prompt budget of the agents (--check) and its arithmetic."""
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "tests" / "prompt_budget.py"
BASE = "75dfdfc"

spec = importlib.util.spec_from_file_location("prompt_budget_under_test", SCRIPT)
pb = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pb)


def run(*args):
    return subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True, text=True, cwd=ROOT)


def test_check_passes_against_base():
    """Descriptions <= 200, blackcat body <= 5,200 and, when the base revision exists, the
    ratios against it (bodies 0.75, agent listing 0.70, rules 1.05)."""
    args = ["--check"] + (["--base", BASE] if pb.rev_exists(BASE) else [])
    r = run(*args)
    assert r.returncode == 0, r.stderr


def test_agent_record_counts():
    text = ('---\nname: x\ndescription: "a \\"b\\" c"\nmaxTurns: 40\n'
            "tools: Read, Agent, SendMessage\nomitClaudeMd: true\n---\n\nBody text.\n")
    a = pb.agent_record("x", text)
    assert a["description"] == len('a "b" c')
    assert a["body"] == len("Body text.")
    assert a["maxTurns"] == 40 and a["has_agent"] and a["omit_claude_md"]
    assert a["listing"] == len("x") + len('a "b" c') + len("Read, Agent, SendMessage") + 12


def test_per_spawn_composition():
    m = pb.measure(pb.Tree())
    for name, a in m["agents"].items():
        want = (a["body"] + (0 if a["omit_claude_md"] else m["rules"]) + m["skill_listing"]
                + (m["agent_listing"] if a["has_agent"] else 0))
        assert a["per_spawn"] == want, name
    assert "blackcat" in m["agents"] and m["agent_listing"] > 0 and m["skill_listing"] > 0


def test_check_flags_violations():
    head = {"agents": {"blackcat": {"description": 10, "body": 6000},
                       "a": {"description": 201, "body": 100}},
            "agent_listing": 80, "rules": 120}
    base = {"agents": {"a": {"description": 10, "body": 100}}, "agent_listing": 100, "rules": 100}
    bad = pb.check(head, base)
    assert any(b.startswith("a.md: description 201") for b in bad)
    assert any(b.startswith("blackcat.md: body 6000") for b in bad)
    assert any(b.startswith("bodies of base agents") for b in bad)
    assert any(b.startswith("agent_listing") for b in bad)
    assert any(b.startswith("rules") for b in bad)


def test_turns_counts_longest_segment(tmp_path):
    d = tmp_path / "p" / "s" / "subagents"
    d.mkdir(parents=True)
    (d / "agent-a1.meta.json").write_text(json.dumps({"agentType": "coder"}))
    rows = [{"type": "user", "message": {"role": "user", "content": "task"}}]
    rows += [{"type": "assistant", "message": {"id": "m%d" % i}} for i in range(3)]
    rows += [{"type": "assistant", "message": {"id": "m2"}}]           # same response, two blocks
    rows += [{"type": "user", "message": {"content": [{"type": "tool_result"}]}}]
    rows += [{"type": "user", "message": {"content": "resume"}}]        # SendMessage: fresh budget
    rows += [{"type": "assistant", "message": {"id": "n%d" % i}} for i in range(2)]
    (d / "agent-a1.jsonl").write_text("\n".join(json.dumps(r) for r in rows))
    _, data = pb.turns(str(tmp_path / "**" / "agent-*.meta.json"))
    assert data == {"coder": [3]}


def test_missing_base_skips_ratios():
    r = run("--base", "0" * 40, "--check")
    assert "ratio checks skipped" in r.stderr
