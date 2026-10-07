"""COMPARE_eq §12 A4: every class gets the Skill tool, the same tool list in every arm and role of a class, passed with
`--tools` (restricts the built-in set) plus `--allowedTools` (auto-approves), and no haiku anywhere."""

from __future__ import annotations

import copy
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

import pytest

import eq_harness as eh
from conftest import FIXT_FLAGS, HARNESS, STAGE, ledger

DISK_FLAGS: dict[str, Any] = json.loads((HARNESS / "flags.json").read_text())
SCHEMA = {"type": "object"}
# D3 (COMPARE_eq §12 A6.2): the writer runs its own frontmatter model, opus
HEAD = ["/x/claude", "-p", "--agent", "writer", "--model", "opus", "--max-budget-usd", "0.280000",
        "--json-schema", '{"type":"object"}', "--output-format", "json", "--permission-mode", "acceptEdits",
        "--disallowedTools", "Agent", "WebSearch", "WebFetch", "--strict-mcp-config"]
# the frozen pool lists (flags.json allowed_tools, owned by the pools) + Skill; StructuredOutput is --tools only
EXPECTED = {
    "PF": ["Read", "Write", "Edit", "Bash", "Skill"],
    "CP": ["Read", "Edit", "Write", "Bash", "Glob", "Grep", "Skill"],
    "CR": ["Read", "Glob", "Grep", "Bash", "Skill"],
    "RS": ["Read", "Grep", "Glob", "Skill"],
    "ES": ["Read", "Skill"],
    "DS": ["Skill"],
    "OE": ["Skill"],
}


def _opt_list(argv: list[str], flag: str) -> list[str]:
    """The values of a variadic option: everything after `flag` up to the next `--option`."""
    out = []
    for a in argv[argv.index(flag) + 1:]:
        if a.startswith("--"):
            break
        out.append(a)
    return out


@pytest.mark.parametrize("cls", eh.CLASSES)
def test_exact_argv_per_class(cls: str) -> None:
    """The frozen flags.json, literally; DEFAULT_FLAGS (pre-pool lists) gets the same Skill rule."""
    tools, boxed = eh.member_tools(DISK_FLAGS, cls)
    assert not boxed and tools == EXPECTED[cls] and tools.count("Skill") == 1
    argv = eh.build_argv("/x/claude", "writer", 280_000, SCHEMA, tools, DISK_FLAGS)
    assert argv == [*HEAD, "--tools", ",".join([*EXPECTED[cls], "StructuredOutput"]),
                    "--allowedTools", *EXPECTED[cls]]
    want = [*eh.DEFAULT_FLAGS["allowed_tools"][cls], "Skill"]
    assert eh.member_tools(eh.DEFAULT_FLAGS, cls) == (want, False)
    argv = eh.build_argv("/x/claude", "writer", 280_000, SCHEMA, want, eh.DEFAULT_FLAGS)
    assert argv[len(HEAD):] == ["--tools", ",".join([*want, "StructuredOutput"]), "--allowedTools", *want]
    assert argv.count("--tools") == 1 and argv.count("--allowedTools") == 1
    assert not any("haiku" in a.casefold() for a in argv)


def test_disk_flags_match_default_on_common_tools() -> None:
    assert DISK_FLAGS["common_tools"] == eh.DEFAULT_FLAGS["common_tools"] == ["Skill"]
    for c in eh.CLASSES:  # the pool-owned lists stay unchanged: Skill is added at launch, not in the pools
        assert "Skill" not in DISK_FLAGS["allowed_tools"][c]


def test_real_pools_still_match_flags_json() -> None:
    items = eh.load_items(STAGE / "items")
    assert items and all(eh.check_item_flags(it, DISK_FLAGS) == [] for it in items.values())


def test_same_tool_list_in_every_arm_and_role(full_run: Path) -> None:
    """Every launched call of a class carries the identical --tools value and --allowedTools list, whatever the arm
    (S*, E, G, EG), label or role; and that list holds Skill."""
    seen: dict[str, set[tuple[str, tuple[str, ...]]]] = defaultdict(set)
    arms: dict[str, set[str]] = defaultdict(set)
    calls = [r for r in ledger(full_run) if r["record"] == "call"]
    assert len(calls) > 100
    for c in calls:
        argv = c["argv"]
        cls = c["item"][:2]
        seen[cls].add((argv[argv.index("--tools") + 1], tuple(_opt_list(argv, "--allowedTools"))))
        arms[cls].add(f"{c.get('arm')}|{c['label']}|{c['role']}")
        assert not any("haiku" in a.casefold() for a in argv)
    assert seen, "no calls"
    for cls, sets in seen.items():
        assert len(sets) == 1, (cls, sets)
        (tv, allowed), = sets
        want = [*FIXT_FLAGS["allowed_tools"][cls], "Skill"]
        assert tv == ",".join([*want, "StructuredOutput"]) and list(allowed) == want
        assert len(arms[cls]) > 3, (cls, arms[cls])  # several arms/roles really were compared


def test_stub_log_argv_has_tools_and_no_haiku(full_run: Path) -> None:
    for line in (full_run / "stub_log.jsonl").read_text().splitlines():
        a = json.loads(line)["argv"]
        tv = a[a.index("--tools") + 1].split(",")
        assert "Skill" in tv and "Skill" in _opt_list(a, "--allowedTools")
        assert not any("haiku" in x.casefold() for x in a)


def test_boxed_member_keeps_mcp_out_of_tools() -> None:
    f = copy.deepcopy(DISK_FLAGS)
    f["member_exec"] = "sandbox"
    tools, boxed = eh.member_tools(f, "PF")
    assert boxed and tools == ["Read", "Write", "Edit", eh.MEMBER_EXEC_TOOL, "Skill"]
    argv = eh.build_argv("c", "verifier", 1, SCHEMA, tools, f)
    assert argv[argv.index("--tools") + 1] == "Read,Write,Edit,Skill,StructuredOutput"  # Bash withheld, no mcp__
    assert _opt_list(argv, "--allowedTools") == tools


def test_tools_value_rejects_rule_syntax_and_exclusions() -> None:
    for bad in (["Bash(git *)"], ["Read,Write"], ["Read Write"], ["!Bash"], [""]):
        with pytest.raises(ValueError):
            eh.tools_value(bad)
    assert eh.tools_value([]) == "StructuredOutput"
    assert eh.tools_value(["Read", "Read", "mcp__x__y"]) == "Read,StructuredOutput"


def test_missing_common_tools_fails_closed() -> None:
    f = copy.deepcopy(eh.DEFAULT_FLAGS)
    del f["common_tools"]
    with pytest.raises(ValueError, match="common_tools"):
        eh.member_tools(f, "DS")
    f["common_tools"] = "Skill"
    with pytest.raises(ValueError, match="common_tools"):
        eh.member_tools(f, "DS")


def test_haiku_still_refused() -> None:
    with pytest.raises(ValueError, match="haiku"):
        eh.build_argv("c", "a", 1, SCHEMA, ["Skill"], dict(eh.DEFAULT_FLAGS, model="claude-haiku-4-5"))
