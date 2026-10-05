"""Synthetic fixtures only: no real probe output exists yet."""
import importlib.util
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("a4_fold", HERE.parent / "a4_fold.py")
a4 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(a4)

WRITER = HERE.parent.parent / "dot-claude" / "agents" / "writer.md"
SID = "123e4567-e89b-12d3-a456-426614174000"


def stream(tools=("Read", "Skill", "StructuredOutput"), so=True, skill_call=False, cost=0.04):
    ev = [
        {"type": "system", "subtype": "init", "cwd": "/Users/someone/tmp", "session_id": SID, "tools": list(tools),
         "mcp_servers": [], "model": "claude-sonnet-5-5", "permissionMode": "acceptEdits",
         "claude_code_version": "2.1.287", "apiKeySource": "sk-ant-api03-ABCDEFGHIJKLMNOP", "skills": ["a", "b"],
         "slash_commands": ["x"]},
        {"type": "assistant", "message": {"content": [{"type": "tool_use", "id": "t1", "name": "StructuredOutput",
                                                       "input": {"tools": list(tools)}}]}},
    ]
    if skill_call:
        ev.append({"type": "assistant", "message": {"content": [{"type": "tool_use", "id": "s1", "name": "Skill", "input": {}}]}})
        ev.append({"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "s1", "content": "ok"}]}})
    res = {"type": "result", "subtype": "success", "is_error": False, "num_turns": 2, "total_cost_usd": cost,
           "duration_ms": 900, "session_id": SID, "permission_denials": []}
    if so:
        res["structured_output"] = {"tools": list(tools)}
    ev.append(res)
    return "\n".join(json.dumps(e) for e in ev) + "\nnot json\n"


def run(tmp_path, text, extra=(), err=None):
    p = tmp_path / "p.json"
    p.write_text(text)
    args = [str(p), "--date", "2026-10-06", "--agent-file", str(WRITER), *extra]
    if err is not None:
        e = tmp_path / "p.err"
        e.write_text(err)
        args += ["--err", str(e)]
    return args


def verdict(out, key):
    line = next(ln for ln in out.splitlines() if key in ln)
    return line.split("**")[1]


def test_happy_path_and_scrub(tmp_path, capsys):
    args = run(tmp_path, stream(), err="warn user@example.com token=abc123SECRET\nexit=0\n")
    assert a4.main(args) == 0
    out = capsys.readouterr().out
    assert SID not in out and "sk-ant" not in out and "user@example.com" not in out
    assert "abc123SECRET" not in out and "/Users/someone" not in out
    assert "Read, Skill, StructuredOutput" in out
    assert "claude-sonnet-5-5" in out and "$0.04" in out
    assert verdict(out, "`--json-schema`") == "confirmed"
    assert verdict(out, "frontmatter tools combine") == "consistent"
    assert verdict(out, "`--settings`") == "unknown"
    assert verdict(out, "`Skill` loads") == "unknown"
    assert "1 non-JSON" in out


def test_skill_invoked_confirms_load(tmp_path, capsys):
    a4.main(run(tmp_path, stream(skill_call=True)))
    assert verdict(capsys.readouterr().out, "`Skill` loads") == "confirmed"


def test_missing_structured_output_refutes(tmp_path, capsys):
    a4.main(run(tmp_path, stream(so=False)))
    assert verdict(capsys.readouterr().out, "`--json-schema`") == "refuted"


def test_frontmatter_widening_is_refuted(tmp_path, capsys):
    a4.main(run(tmp_path, stream(tools=("Read", "Skill", "Write", "StructuredOutput"))))
    assert verdict(capsys.readouterr().out, "frontmatter tools combine") == "refuted"


def test_intersection_confirmed_when_flag_name_outside_frontmatter(tmp_path, capsys):
    # --tools names Bash, the frontmatter (writer) does not: Bash absent in init => intersection
    a4.main(run(tmp_path, stream(tools=("Read", "Skill", "StructuredOutput")),
                extra=("--tools-flag", "Read,Skill,Bash,StructuredOutput")))
    assert verdict(capsys.readouterr().out, "frontmatter tools combine") == "confirmed"


def test_no_result_no_init_all_unknown(tmp_path, capsys):
    p = tmp_path / "p.json"
    p.write_text("garbage\n")
    assert a4.main([str(p), "--date", "2026-10-06"]) == 0
    out = capsys.readouterr().out
    assert out.count("**unknown**") == 4
    assert "No init event" in out and "No result event" in out


def test_missing_file_rc2(tmp_path):
    assert a4.main([str(tmp_path / "nope.json")]) == 2


def test_cost_over_cap_warns(tmp_path, capsys):
    a4.main(run(tmp_path, stream(cost=0.31)))
    assert "WARNING" in capsys.readouterr().out
