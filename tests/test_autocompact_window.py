"""autoCompactWindow has one source, dot-claude/settings.json (the installer re-asserts it, the smoke
test checks the installed value against it); doctor.sh checks the same value.

Run: uv run --with pytest pytest -q tests/test_autocompact_window.py
"""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SHIPPED = json.loads((ROOT / "dot-claude" / "settings.json").read_text())


def test_shipped_window_is_629k():
    # the user's decision (2026-10-03); Claude Code accepts 100000-1000000, capped at the model's window
    assert SHIPPED["autoCompactWindow"] == 629_000
    # autoCompactEnabled is retired (Claude Code's default is true; doctor.sh reads absent as true)
    assert "autoCompactEnabled" not in SHIPPED


def test_doctor_checks_the_shipped_value():
    m = re.search(r'autoCompactWindow"\) == (\d+) else warn\)\("autoCompactWindow=%s \(stack: (\d+)\)"',
                  (ROOT / "dot-claude" / "bin" / "doctor.sh").read_text())
    assert m and int(m.group(1)) == int(m.group(2)) == SHIPPED["autoCompactWindow"]


def test_docs_name_the_shipped_value():
    config = (ROOT / "CONFIG.md").read_text()      # §5 is the only knob table (the README points there)
    assert "| `autoCompactWindow` | 629000 |" in config
