"""Argv-only launches (no shell), the exact PROPOSAL §5 flags, item head, fresh copies, and no haiku anywhere."""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path

import pytest

import eq_harness as eh
from conftest import FIXT_FLAGS, HARNESS, ledger

SHELL_FUNCS = {"system", "popen", "getoutput", "getstatusoutput", "spawnl", "spawnlp", "execl", "execlp"}


def _calls(tree: ast.AST) -> list[ast.Call]:
    return [n for n in ast.walk(tree) if isinstance(n, ast.Call)]


def test_no_shell_anywhere_in_harness() -> None:
    tree = ast.parse((HARNESS / "eq_harness.py").read_text())
    sp_calls = 0
    for c in _calls(tree):
        f = c.func
        name = f.attr if isinstance(f, ast.Attribute) else f.id if isinstance(f, ast.Name) else ""
        assert name not in SHELL_FUNCS, f"shell-style call {name} at line {c.lineno}"
        for kw in c.keywords:
            if kw.arg == "shell":
                assert isinstance(kw.value, ast.Constant) and kw.value.value is False, f"shell= at line {c.lineno}"
        if name in ("run", "Popen", "call", "check_output", "check_call") and isinstance(f, ast.Attribute) and \
                isinstance(f.value, ast.Name) and f.value.id == "subprocess":
            sp_calls += 1
            assert any(kw.arg == "shell" for kw in c.keywords), f"subprocess.{name} without shell=False, {c.lineno}"
            first = c.args[0] if c.args else None
            assert not isinstance(first, ast.Constant | ast.JoinedStr | ast.BinOp), f"string argv at {c.lineno}"
    assert sp_calls >= 5


def test_build_argv_exact_flags() -> None:
    schema = {"type": "object"}
    argv = eh.build_argv("/x/claude", "code-reviewer", 280_000, schema, ["Read", "Grep"], eh.DEFAULT_FLAGS)
    assert all(isinstance(a, str) for a in argv)
    assert argv == ["/x/claude", "-p", "--agent", "code-reviewer", "--model", "opus", "--max-budget-usd", "0.280000",
                    "--json-schema", '{"type":"object"}', "--output-format", "json", "--permission-mode",
                    "acceptEdits", "--disallowedTools", "Agent", "WebSearch", "WebFetch", "--strict-mcp-config",
                    "--tools", "Read,Grep,StructuredOutput", "--allowedTools", "Read", "Grep"]  # COMPARE_eq §12 A4
    r = eh.build_argv("c", "verifier", 1, schema, ["Read"], eh.DEFAULT_FLAGS, resume="sid-1")
    assert r[-2:] == ["--resume", "sid-1"] and r[r.index("--model") + 1] == "sonnet"  # D3: the verifier's own model
    with pytest.raises(ValueError, match="no entry for agent"):  # a type outside the D3 map is refused (fail closed)
        eh.build_argv("c", "a", 1, schema, ["Read"], eh.DEFAULT_FLAGS)


def test_launched_argv_and_heads(full_run: Path) -> None:
    log = [json.loads(ln) for ln in (full_run / "stub_log.jsonl").read_text().splitlines()]
    calls = [r for r in ledger(full_run) if r["record"] == "call"]
    assert len(log) == len(calls) > 100
    for e in log:
        a = e["argv"]
        i = a.index("--disallowedTools")
        assert a[i + 1: i + 4] == ["Agent", "WebSearch", "WebFetch"]
        agent = a[a.index("--agent") + 1]
        for flag, val in (("--output-format", "json"), ("--permission-mode", "acceptEdits"),
                          ("--model", FIXT_FLAGS["model"][agent])):  # D3: each agent's own frontmatter model
            assert a[a.index(flag) + 1] == val
        assert "--strict-mcp-config" in a and "--json-schema" in a and "--max-budget-usd" in a and "--agent" in a
        m = eh.HEAD_RE.match(e["head"])
        assert m, e["head"]
        tools = [*FIXT_FLAGS["allowed_tools"][m["item"][:2]], "Skill"]  # COMPARE_eq §12 A4: Skill in every class
        assert a[a.index("--tools") + 1] == ",".join([*tools, "StructuredOutput"])
        assert a[a.index("--allowedTools") + 1:][: len(tools)] == tools
    roles = {c["role"] for c in calls}
    assert {"s", "plan", "sel", "ver", "r1"} <= roles and any(re.fullmatch(r"m\d/[35]", r) for r in roles)
    assert any(re.fullmatch(r"n\d", r) for r in roles)
    for c in calls:
        prompt = Path(c["prompt_path"]).read_text()
        assert prompt.splitlines()[0] == f"{c['item']} {c['label']} {c['role']}"


def test_fresh_fixture_copy_per_call(full_run: Path) -> None:
    calls = [r for r in ledger(full_run) if r["record"] == "call"]
    fresh = [c["cwd"] for c in calls if not c["resume"]]
    assert len(fresh) == len(set(fresh))
    for c in calls:
        assert Path(c["cwd"]).is_dir()
        if c["resume"]:
            orig = [x for x in calls if x["session_id"] == c["resume"] and not x["resume"]]
            assert orig and orig[0]["cwd"] == c["cwd"]


def test_no_haiku_anywhere(full_run: Path) -> None:
    pat = re.compile("haiku", re.IGNORECASE)
    assert not pat.search((HARNESS / "flags.json").read_text())
    assert not pat.search(json.dumps(eh.DEFAULT_FLAGS))
    assert not pat.search((full_run / "stub_log.jsonl").read_text())  # every launched argv
    for p in (full_run / "raw").rglob("stdout.json"):  # every stub output
        assert not pat.search(p.read_text()), p
    stub_src = (HARNESS / "stub_claude").read_text()
    assert not re.search(r'MODEL = "[^"]*haiku', stub_src, re.IGNORECASE)
    with pytest.raises(ValueError):
        eh.build_argv("c", "a", 1, {}, [], dict(eh.DEFAULT_FLAGS, model="claude-haiku-4-5"))


def test_ledger_fields_are_documented(full_run: Path) -> None:
    doc = (HARNESS / "LEDGER_SCHEMA.md").read_text()
    documented = set(re.findall(r"`([A-Za-z_0-9]+)`", doc))
    recs = ledger(full_run)
    assert {r["record"] for r in recs} <= documented
    for r in recs:
        missing = set(r) - documented
        assert not missing, (r["record"], missing)
        if r["record"] == "call" and r["view"]:
            assert not set(r["view"]) - documented


def test_restart_skips_done_and_keeps_ids_unique(stub_bin: Path, tmp_path: Path) -> None:
    from conftest import dry_run

    dry_run(stub_bin, tmp_path, only=["ES-DEV1"])
    first = ledger(tmp_path)
    dry_run(stub_bin, tmp_path, only=["ES-DEV1", "OE-DEV1"])
    recs = ledger(tmp_path)
    assert [r["seq"] for r in recs] == list(range(1, len(recs) + 1))
    assert recs[: len(first)] == first  # append-only
    ids = [r["call_id"] for r in recs if r["record"] == "call"]
    assert len(ids) == len(set(ids))
    arms = [(r["item"], r["label"]) for r in recs if r["record"] == "item_arm"]
    assert len(arms) == len(set(arms)) == 8


def test_mediator_ledgers_written_and_documented(full_run: Path) -> None:
    doc = (HARNESS / "LEDGER_SCHEMA.md").read_text()
    documented = set(re.findall(r"`([A-Za-z_0-9]+)`", doc))
    files = list((full_run / "raw" / "d").glob("*/*/mediator.jsonl"))
    e_arms = {(r["item"], r["label"]) for r in ledger(full_run) if r["record"] == "item_arm" and r["arm"] in ("E",)}
    assert {(f.parent.parent.name, f.parent.name) for f in files} >= e_arms
    seen: set[str] = set()
    for f in files:
        for line in f.read_text().splitlines():
            r = json.loads(line)
            seen.add(r["record"])
            assert not set(r) - documented, (r["record"], set(r) - documented)
    assert seen >= {"claim", "fact", "result", "attribution"}
