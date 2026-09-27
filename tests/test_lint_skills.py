"""Skill frontmatter rules the lint enforces: YAML-safe one-line descriptions."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import lint_agents  # noqa: E402

SKILLS = Path(__file__).resolve().parent.parent / "dot-claude" / "skills"


def test_yaml_plain_hazard_flags_what_yaml_rejects_or_truncates():
    bad = ["Load before x: y", "ends with a colon:", "a #comment", "[bracket] start", "- dash start",
           "'unclosed", "&anchor", "*alias", "! tag", "% directive", "@ reserved", "`backtick"]
    for v in bad:
        assert lint_agents.yaml_plain_hazard(v), v


def test_yaml_plain_hazard_accepts_ordinary_descriptions():
    good = ["Load before x — y, z and w.", "ratio 3:1 and C#", "http://example.org/path is fine",
            '"quoted: value"', "'quoted: value'", "Use when a#b appears", ""]
    for v in good:
        assert lint_agents.yaml_plain_hazard(v) is None, v


def test_every_shipped_skill_description_is_yaml_safe_and_trigger_first():
    for f in sorted(SKILLS.glob("*/SKILL.md")):
        head = f.read_text(encoding="utf-8").split("---", 2)[1]
        line = next(x for x in head.splitlines() if x.startswith("description:"))
        desc = line.split(":", 1)[1].strip()
        assert lint_agents.yaml_plain_hazard(desc) is None, f
        if "disable-model-invocation: true" not in head:
            assert desc.startswith(("Load ", "Use ")), f
