"""The knob table's markers follow the installer: ● marks exactly the env keys install.sh owns
(OWNED_ENV: reset on every install), ○ the other keys dot-claude/settings.json ships (a default that
follows upgrades while unchanged; a changed value is kept). The table is CONFIG.md §5, its only copy;
the README's Knobs sections point there and list no knob table of their own.

Run: uv run --with pytest pytest -q tests/test_readme_knobs.py
"""
import ast
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OWNED, DEFAULT = "●", "○"


def owned_env():
    """install.sh's OWNED_ENV set literal (the embedded Python)."""
    m = re.search(r"(?ms)^OWNED_ENV = (\{.*?\})$", (ROOT / "install.sh").read_text())
    assert m, "OWNED_ENV not found in install.sh"
    return set(ast.literal_eval(m.group(1)))


def shipped_env():
    return set(json.loads((ROOT / "dot-claude" / "settings.json").read_text())["env"])


def readme_marks():
    """{variable: marker} for every marked name in CONFIG.md §5's table. A name that starts
    with `_` continues the row's first name (`MCP_DISCOVERY_CACHE` / `_TTL_S`)."""
    text = (ROOT / "CONFIG.md").read_text()
    section = text.split("\n## 5. Guard knobs and settings\n", 1)[1].split("\n### ", 1)[0]
    marks = {}
    for line in section.splitlines():
        if not line.startswith("| `"):
            continue
        first = None
        for name, mark in re.findall(r"`([A-Z_][A-Z0-9_]*)`(?:\s*([%s%s]))?" % (OWNED, DEFAULT),
                                     line.split(" | ", 1)[0]):
            full = first + name if name.startswith("_") and first else name
            first = first or name
            if mark:
                assert full not in marks, "%s marked twice" % full
                marks[full] = mark
    return marks


def test_owned_marker_is_exactly_owned_env():
    marks = readme_marks()
    assert {k for k, m in marks.items() if m == OWNED} == owned_env()


def test_every_shipped_key_is_marked_and_nothing_else():
    marks = readme_marks()
    assert set(marks) == shipped_env()
    assert {k for k, m in marks.items() if m == DEFAULT} == shipped_env() - owned_env()


def test_owned_keys_are_shipped():
    assert owned_env() <= shipped_env()


def test_readme_has_no_knob_table():
    """One copy: the README's Main knobs and Knobs sections point to CONFIG.md §5."""
    text = (ROOT / "README.md").read_text()
    for head in ("\n### Main knobs\n", "\n### Knobs\n"):
        section = text.split(head, 1)[1].split("\n### ", 1)[0]
        assert "CONFIG.md" in section and "\n|" not in section, head


def test_concurrency_value_is_the_shipped_one_everywhere():
    """CLAUDE_CODE_MAX_CONCURRENT_SUBAGENTS has one source, dot-claude/settings.json (128, the user's
    value); CONFIG.md §5, the README, /stack-doctor's threshold and the smoke test follow it."""
    env = json.loads((ROOT / "dot-claude" / "settings.json").read_text())["env"]
    n = env["CLAUDE_CODE_MAX_CONCURRENT_SUBAGENTS"]
    assert n == "128" and env["CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH"] == "8"
    assert "| `CLAUDE_CODE_MAX_CONCURRENT_SUBAGENTS` ● | %s | 20 |" % n in (ROOT / "CONFIG.md").read_text()
    readme = (ROOT / "README.md").read_text()
    assert "); %s subagents running at once per session (`CLAUDE_CODE_MAX_CONCURRENT_SUBAGENTS`" % n in readme
    assert "Depth 4, %s at once," % n in readme
    doctor = (ROOT / "dot-claude" / "bin" / "doctor.sh").read_text()
    assert doctor.count("conc >= %s else" % n) == 2 and "the stack ships %s (" % n in doctor
    assert not re.search(r"conc >= (?!%s )\d+" % n, doctor)
    assert 'plan-reviewer=8", None, None, "%s", "64")' % n in (ROOT / "tests" / "install_smoke.sh").read_text()
