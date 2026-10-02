"""tests/prompt_budget.py: the static prompt budget of the agents (--check) and its arithmetic."""
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "tests" / "prompt_budget.py"
BASE = "1a38c77"

spec = importlib.util.spec_from_file_location("prompt_budget_under_test", SCRIPT)
pb = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pb)


def run(*args):
    return subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True, text=True, cwd=ROOT)


def test_check_passes_against_base():
    """Descriptions <= 200, blackcat body <= 5,200, the caps on new agents and, when the base
    revision exists, the ratios against it (pb.RATIO)."""
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
    assert a["allowlist"] is None
    assert pb.agent_allowlist("Agent(coder, scout), Read, Skill") == ["coder", "scout"]


def test_per_spawn_composition():
    m = pb.measure(pb.Tree())
    for name, a in m["agents"].items():
        shown = m["blackcat_listing"] if name == "blackcat" else m["agent_listing"]
        want = (a["body"] + (0 if a["omit_claude_md"] else m["rules"]) + m["skill_listing"]
                + (shown if a["has_agent"] else 0))
        assert a["per_spawn"] == want, name
    assert "blackcat" in m["agents"] and m["agent_listing"] > 0 and m["skill_listing"] > 0
    allow = set(m["agents"]["blackcat"]["allowlist"])
    assert m["blackcat_listing"] == sum(a["listing"] for n, a in m["agents"].items()
                                        if n in allow and n != "blackcat")


def test_skill_listing_reads_skill_overrides():
    e = pb.skill_listing_entry
    assert e("abc", 50) == 3 + 4 + 50
    assert e("abc", 900, "on", 500) == 3 + 4 + 500
    assert e("abc", 50, "name-only") == 3 + 4
    assert e("abc", 50, "user-invocable-only") == 0 and e("abc", 50, "off") == 0
    assert e("abc", 50, "on", 500, model_invocable=False) == 0


def _agent(desc, body, has_agent=False, per_spawn=1000):
    return {"description": desc, "body": body, "has_agent": has_agent, "per_spawn": per_spawn}


def _totals(**kw):
    t = {"agent_listing": 100, "blackcat_listing": 100, "skill_listing": 100, "rules": 100}
    t.update(kw)
    return t


def test_check_flags_violations():
    head = dict(agents={"blackcat": _agent(10, 6000, True), "a": _agent(201, 100, per_spawn=2000),
                        "newx": _agent(161, 2401, True), "newl": _agent(121, 1401)},
                **_totals(agent_listing=135, blackcat_listing=132, skill_listing=66, rules=103))
    base = dict(agents={"blackcat": _agent(10, 5000, True), "a": _agent(10, 50)}, **_totals())
    bad = pb.check(head, base)
    for prefix in ("a.md: description 201", "blackcat.md: body 6000",
                   "newx.md (new, with Agent): description 161", "newx.md (new, with Agent): body 2401",
                   "newl.md (new, leaf): description 121", "newl.md (new, leaf): body 1401",
                   "bodies of base agents", "agent_listing", "blackcat_listing", "skill_listing", "rules",
                   "per_spawn_mean of base agents"):
        assert any(b.startswith(prefix) for b in bad), (prefix, bad)


def test_check_passes_within_limits():
    head = dict(agents={"blackcat": _agent(10, 5200, True), "a": _agent(200, 105, per_spawn=920),
                        "newx": _agent(160, 2400, True), "newl": _agent(120, 1400)},
                **_totals(agent_listing=134, blackcat_listing=131, skill_listing=65, rules=102))
    base = dict(agents={"blackcat": _agent(10, 5000, True), "a": _agent(10, 100)}, **_totals())
    assert pb.check(head, base) == []


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


def test_check_defaults_to_base():
    assert pb.DEFAULT_BASE == BASE


def test_missing_base_skips_ratios():
    r = run("--base", "0" * 40, "--check")
    assert "ratio checks skipped" in r.stderr
