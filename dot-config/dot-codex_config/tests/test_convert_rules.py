"""lib/convert_rules.py: settings.json Bash rules -> Codex prefix rules (DESIGN.md §4.1 L2, §4.3, §8.4)."""
from __future__ import annotations

import json
import os
import re

import pytest

from _rules_helpers import FAKE_CODEX, codex_env, ctx_for, decision, settings
from conftest import load_lib

cr = load_lib("convert_rules")

S = settings()
BASH_DENIES = [e for e in S["permissions"]["deny"] if e.startswith("Bash(")]


@pytest.fixture
def ctx(tmp_path):
    return ctx_for(tmp_path / "home")


@pytest.fixture
def rules_file(tmp_path, ctx, monkeypatch):
    """Write the default rules (no --git-allow-rules) and point the fake codex at this Python."""
    monkeypatch.setenv("FAKE_CODEX_PYTHON", codex_env()["FAKE_CODEX_PYTHON"])

    def make(opts=None, settings_=None):
        text, _ = cr.render_rules(settings_ or S, ctx, opts or {})
        p = tmp_path / "rules" / "claude-agent-stack.rules"
        p.parent.mkdir(exist_ok=True)
        p.write_text(text)
        return p
    return make


def by_decision(res, d):
    return [r for r in res["rules"] if r["decision"] == d]


def test_settings_have_the_expected_bash_denies():
    assert len(BASH_DENIES) == 34


def test_counts_and_every_convertible_deny_is_forbidden(ctx):
    res = cr.convert(S, ctx, {})
    assert res["counts"] == {"allow": 0, "prompt": 7, "forbidden": 36}
    sources = {r["source"] for r in by_decision(res, "forbidden")}
    converted = [e for e in BASH_DENIES if "settings.json deny " + e in sources]
    guard_only = [e for e in BASH_DENIES if e not in converted]
    assert guard_only == ["Bash(mcp-headers *--reveal*)", "Bash(with-stack-env *--reveal*)"]
    assert all(any(e in n for n in res["report"] if n.startswith("guard-only")) for e in guard_only)
    for r in res["rules"]:
        assert not any(re.search(r"[*?\[]", t) for tok in r["pattern"] for t in cr._alts(tok)), r


def test_claude_allow_never_becomes_codex_allow(ctx):
    text, examples = cr.render_rules(S, ctx, {})
    assert 'decision = "allow"' not in text
    assert all(e["decision"] != "allow" for e in examples)
    # even a settings file that allows push-like and arbitrary commands yields no allow
    s2 = json.loads(json.dumps(S))
    s2["permissions"]["allow"] += ["Bash(git commit *)", "Bash(rm -rf *)", "Bash"]
    res = cr.convert(s2, ctx, {})
    assert res["counts"]["allow"] == 0
    assert sum("dropped Claude allow" in n for n in res["report"]) >= 6


def test_claude_ask_becomes_prompt(ctx):
    res = cr.convert({"permissions": {"ask": ["Bash(docker run *)", "mcp__x"]}}, ctx, {})
    (r,) = [r for r in res["rules"] if r["source"].startswith("settings.json ask")]
    assert r["pattern"] == ["docker", "run"] and r["decision"] == "prompt"


def test_stack_install_allow_becomes_prompt(ctx):
    res = cr.convert(S, ctx, {})
    inst = os.path.join(ctx["stack"], "bin", "stack-install")
    (r,) = [r for r in res["rules"] if r["pattern"] == [inst]]
    assert r["decision"] == "prompt"
    assert any(n.startswith("allow -> prompt") for n in res["report"])


def test_push_and_forge_forms_are_forbidden(rules_file):
    p = rules_file()
    for cmd in (["git", "push"], ["git", "push", "origin", "main"], ["git", "send-pack", "r"],
                ["git", "lfs", "push", "origin"], ["git", "subtree", "push", "--prefix=d"],
                ["/usr/bin/git", "push"], ["git-push"], ["git-send-pack"], ["git", "svn", "dcommit"],
                ["gh", "pr", "create", "--fill"], ["gh", "pr", "merge", "1"],
                ["gh", "pr", "review", "1"], ["gh", "pr", "comment", "1", "-b", "x"],
                ["gh", "pr", "new"], ["gh", "release", "create", "v1"],
                ["gh", "release", "upload", "v1", "f"], ["gh", "repo", "fork"],
                ["gh", "workflow", "run", "ci"], ["tea", "pulls", "merge", "1"],
                ["fj", "release", "create", "v1"], ["bash", "-x", "install.sh"],
                ["zsh", "-x", "doctor.sh"]):
        assert decision(p, *cmd) == "forbidden", cmd


def test_reads_are_not_forbidden(rules_file):
    p = rules_file()
    for cmd in (["git", "status"], ["git", "log"], ["gh", "pr", "view", "1"], ["gh", "pr", "list"],
                ["gh", "release", "view"], ["echo", "git", "push"], ["bash", "install.sh"],
                ["tea", "pulls", "list"], ["git", "branch"], ["git", "worktree", "list"]):
        assert decision(p, *cmd) is None, cmd


def test_git_writes_prompt(rules_file):
    p = rules_file()
    for cmd in (["git", "commit", "-m", "x"], ["git", "merge", "--ff-only", "b"],
                ["git", "rebase", "main"], ["git", "worktree", "add", "../w"],
                ["git", "worktree", "remove", "../w"], ["git", "branch", "-d", "b"],
                ["git", "tag", "-a", "v1"], ["git", "reset", "--hard"], ["git", "add", "f"],
                ["git", "stash", "pop"], ["git", "remote", "set-url", "o", "u"]):
        assert decision(p, *cmd) == "prompt", cmd


def test_git_allow_rules_only_with_the_flag(rules_file, ctx):
    assert cr.convert(S, ctx, {})["counts"]["allow"] == 0
    res = cr.convert(S, ctx, {"git_allow_rules": True})
    assert res["counts"] == {"allow": 2, "prompt": 7, "forbidden": 36}
    p = rules_file({"git_allow_rules": True})
    hf = ["git", "-c", "core.hooksPath=/dev/null"]
    assert decision(p, *hf, "commit", "-m", "x") == "allow"
    assert decision(p, *hf, "add", "f") == "allow"
    assert decision(p, *hf, "merge", "--ff-only", "b") == "allow"
    assert decision(p, "git", "commit", "-m", "x") == "prompt"          # plain form still asks
    assert decision(p, *hf, "merge", "b") is None                        # not --ff-only
    assert decision(p, *hf, "rebase", "-x", "sh") is None                # rebase never allowed
    assert decision(p, *hf, "worktree", "add", "/tmp/w") is None         # writes any path
    assert decision(p, "git", "-c", "core.hooksPath=/tmp/h", "commit") is None
    assert decision(p, "git", "push") == "forbidden"


def test_every_example_agrees_with_the_mirror(rules_file):
    for opts in ({}, {"git_allow_rules": True}):
        p = rules_file(opts)
        assert cr.check_examples(str(p), str(FAKE_CODEX)) == []


def test_check_examples_reports_disagreements(tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_CODEX_PYTHON", codex_env()["FAKE_CODEX_PYTHON"])
    p = tmp_path / "x.rules"
    # loads (each call's examples hold on their own), but in the whole file `git commit` is
    # forbidden, so rule 1's match example disagrees with its own decision
    p.write_text('prefix_rule(pattern = ["git"], decision = "prompt", match = [["git", "commit"]])\n'
                 'prefix_rule(pattern = ["git", "commit"], decision = "forbidden")\n')
    out = cr.check_examples(str(p), str(FAKE_CODEX))
    assert len(out) == 1 and "decision forbidden, rule says prompt" in out[0]
    p.write_text('prefix_rule(pattern = ["git", "push"], match = [["git", "pull"]])\n')
    out = cr.check_examples(str(p), str(FAKE_CODEX))
    assert len(out) == 1 and "cannot load" in out[0]


def test_check_examples_resolves_absolute_programs_like_the_runtime(tmp_path, monkeypatch):
    # Codex validates examples and evaluates commands with basename fallback on
    # (resolve_host_executables: true), so /usr/bin/git must count as git here too
    monkeypatch.setenv("FAKE_CODEX_PYTHON", codex_env()["FAKE_CODEX_PYTHON"])
    p = tmp_path / "abs.rules"
    p.write_text('prefix_rule(pattern = ["git", "push"], decision = "forbidden",\n'
                 '    match = [["/usr/bin/git", "push"]], not_match = [["/usr/bin/git", "pull"]])\n')
    assert cr.check_examples(str(p), str(FAKE_CODEX)) == []


def test_examples_returned_match_the_text(ctx):
    text, examples = cr.render_rules(S, ctx, {"git_allow_rules": True})
    parsed = cr.parse_rules_text(text)
    assert [(r["pattern"], r["decision"], r["match"], r["not_match"]) for r in parsed] == \
        [(e["pattern"], e["decision"], e["match"], e["not_match"]) for e in examples]
    assert all(e["match"] and e["not_match"] for e in examples)


def test_finite_glob_expansion_and_guard_only(ctx):
    s2 = {"permissions": {"deny": ["Bash(gh pr cre* *)", "Bash(gh release *load *)",
                                   "Bash(gh * create *)", "Bash(foo *bar*)", "Bash(git push:*)"]}}
    res = cr.convert(s2, ctx, {})
    pats = [r["pattern"] for r in by_decision(res, "forbidden") if r["source"].startswith("settings")]
    assert ["gh", "pr", "create"] in pats
    assert ["gh", "release", ["upload", "download"]] in pats
    assert ["git", "push"] in pats
    notes = [n for n in res["report"] if n.startswith("guard-only")]
    assert len(notes) == 2 and any("gh * create" in n for n in notes)


def test_unmapped_input_is_an_error(ctx):
    for bad in (["Bash(__STACK_STATE__/x *)"], ["Bash"], ["Bash(*)"]):
        with pytest.raises(cr.BuildError):
            cr.convert({"permissions": {"deny": bad}}, ctx, {})


def test_never_default_rules_and_global_header(ctx):
    assert cr.RULES_FILE == "rules/claude-agent-stack.rules"
    assert not cr.RULES_FILE.endswith("default.rules")
    text, _ = cr.render_rules(S, ctx, {})
    assert text.startswith("# claude-agent-stack") and "GLOBAL" in text.splitlines()[0]


def test_strings_are_starlark_safe(ctx):
    weird = dict(ctx, stack='/h/a "b"\\c/stack')
    text, _ = cr.render_rules(S, weird, {})
    parsed = cr.parse_rules_text(text)
    assert ['/h/a "b"\\c/stack/bin/stack-install'] in [r["pattern"] for r in parsed]
    with pytest.raises(cr.BuildError):
        cr.render_rules(S, dict(ctx, stack="/h/a\nb"), {})


def test_forbidden_push_forge_set(ctx):
    rs = cr.forbidden_push_forge(S, ctx)
    assert {r["category"] for r in rs} == {"push", "forge"}
    heads = {cr._alts(r["pattern"][0])[0] for r in rs}
    assert heads == {"git", "git-push", "git-send-pack", "gh", "tea", "fj"}
    assert len(rs) == 30 and all(r["decision"] == "forbidden" for r in rs)
