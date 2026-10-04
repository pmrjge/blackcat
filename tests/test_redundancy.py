"""tests/redundancy_lint.py: repeated long sentences, dangling skill/section references, dead hooks.

The repo passes against tests/redundancy_allowlist.json (its TODO entries are the baseline found on
2026-10-04); each check is proven by a mutation on a copy of dot-claude/ (seed a violation, see the
lint fail; the near-miss next to it stays clean).

Run: uv run --with pytest pytest -q tests/test_redundancy.py
"""
import importlib.util
import json
import shutil
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
_spec = importlib.util.spec_from_file_location("redundancy_lint", HERE / "redundancy_lint.py")
lint = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(lint)

EMPTY = {"repeats": [], "refs": [], "hooks": []}


@pytest.fixture
def repo(tmp_path):
    """A copy of the parts the lint reads: dot-claude/ and install.sh."""
    root = tmp_path / "repo"
    shutil.copytree(ROOT / "dot-claude", root / "dot-claude",
                    ignore=shutil.ignore_patterns("__pycache__", ".DS_Store"))
    shutil.copy2(ROOT / "install.sh", root / "install.sh")
    return root


def new_findings(root, allow=None):
    path = root / "allow.json"
    path.write_text(json.dumps(allow if allow is not None else json.loads(lint.ALLOWLIST.read_text())))
    new, _, _ = lint.run(root, path)
    return new


def append(path, text):
    path.write_text(path.read_text(encoding="utf-8") + text, encoding="utf-8")


# ---------------------------------------------------------------- the repo today

def test_repo_has_no_finding_outside_the_allowlist():
    new, allowed, _ = lint.run(ROOT, lint.ALLOWLIST)
    assert new == [], "\n".join(new)
    assert allowed, "the baseline allowlist matches nothing: the lint reads no files?"


def test_cli_exit_codes(repo):
    assert lint.main(["--root", str(ROOT)]) == 0
    append(repo / "dot-claude" / "agents" / "coder.md", "\nAlso see `no-such-skill-xyz`.\n")
    assert lint.main(["--root", str(repo)]) == 1


def test_every_allowlist_entry_has_a_reason():
    allow = json.loads(lint.ALLOWLIST.read_text())
    for kind in ("repeats", "refs", "hooks"):
        for e in allow[kind]:
            assert e.get("reason", "").strip(), (kind, e)
    assert any(e["reason"].startswith("TODO:") for k in ("repeats", "refs", "hooks") for e in allow[k])


def test_the_lint_actually_sees_references():
    """Guards against a vacuous pass: the regexes find the repo's real see/load and `x`* refs."""
    text = (ROOT / "dot-claude" / "agents" / "go-engineer.md").read_text()
    assert "go-concurrency" in lint.STAR_RE.findall(text)
    assert lint.REF_RE.search("load `review-protocol` and `proof-craft` (refereeing)")
    assert lint.installer_staged_hooks((ROOT / "install.sh").read_text()) >= {
        "agent_guard.py", "stack_usage.py", "stack_fanout_wire.py", "sched_model.json"}


# ---------------------------------------------------------------- (a) repeats

SENTENCE = ("Mutation proof: this deliberately long sentence is pasted into several agent files so the "
            "redundancy lint must notice the copy and fail.")


def test_repeat_in_three_files_fails_two_passes(repo):
    agents = repo / "dot-claude" / "agents"
    assert len(lint.normalise(SENTENCE)) >= lint.MIN_CHARS
    for name in ("coder.md", "go-engineer.md"):
        append(agents / name, "\n" + SENTENCE + "\n")
    assert new_findings(repo) == []                       # two files: below MIN_FILES
    append(repo / "dot-claude" / "skills" / "sqlite" / "SKILL.md", "\n- " + SENTENCE.upper() + "\n")
    new = new_findings(repo)
    assert len(new) == 1 and "repeat in 3 files" in new[0] and "skills/sqlite/SKILL.md" in new[0]
    # the allowlist silences it
    allow = json.loads(lint.ALLOWLIST.read_text())
    allow["repeats"].append({"contains": "mutation proof: this deliberately", "reason": "test"})
    assert new_findings(repo, allow) == []


def test_short_or_fenced_repeats_are_ignored(repo):
    short = "A short repeated sentence stays below the length threshold."
    fenced = "```\n" + SENTENCE + "\n```\n"
    for name in ("coder.md", "go-engineer.md", "rust-engineer.md"):
        append(repo / "dot-claude" / "agents" / name, "\n" + short + "\n" + fenced)
    assert new_findings(repo) == []


def test_allowlisted_template_still_found_without_allowlist(repo):
    new = new_findings(repo, EMPTY)
    assert any("two failed attempts at one failure" in n for n in new)


# ---------------------------------------------------------------- (b) refs

def test_dangling_see_load_and_module_refs_fail(repo):
    agent = repo / "dot-claude" / "agents" / "coder.md"
    append(agent, "\nFor this, see `postgresql` and `sqlite`; load `review-protocol`.\n")
    assert new_findings(repo) == []                       # all exist
    append(agent, "\nThen load `review-protocol` and `no-such-skill-b`; see `no-such-skill-a`. "
                  "Also `no-such-module-c`*.\n")
    new = new_findings(repo)
    for n in ("no-such-skill-a", "no-such-skill-b", "no-such-module-c"):
        assert any("ref agents/coder.md: `%s` (no such skill)" % n in x for x in new), (n, new)
    assert len(new) == 3


def test_external_and_plugin_skills_resolve(repo):
    append(repo / "dot-claude" / "agents" / "coder.md",
           "\nLoad `anthropic-skills:pdf` or see `skill-creator`.\n")
    assert new_findings(repo) == []


def test_removed_skill_makes_its_refs_dangle(repo):
    shutil.rmtree(repo / "dot-claude" / "skills" / "test-e2e-playwright")
    new = new_findings(repo)
    assert any("`test-e2e-playwright` (no such skill)" in n and "agents/test-engineer.md" in n for n in new)


def test_section_refs(repo):
    agent = repo / "dot-claude" / "agents" / "coder.md"
    append(agent, "\nSee `postgresql` (Migrations without downtime), `redis` § Locks, "
                  "`numerical-methods` §9 and `container-images` § Runtime hardening.\n")
    assert new_findings(repo) == []                       # real headings
    append(agent, "\nSee `postgresql` (No Such Heading). Also `redis` § Nowhere, `numerical-methods` §42.\n")
    new = new_findings(repo)
    for ref in ("postgresql § No Such Heading", "redis § Nowhere", "numerical-methods § 42"):
        assert any("`%s` (no such heading" % ref in n for n in new), (ref, new)
    assert len(new) == 3


def test_section_after_non_skill_is_not_a_ref(repo):
    append(repo / "dot-claude" / "agents" / "coder.md",
           "\nThe `--flag` § Options and see `README.md` (top).\n")
    assert new_findings(repo) == []


# ---------------------------------------------------------------- (c) hooks

def test_orphan_hook_fails_until_wired_or_staged(repo):
    hooks = repo / "dot-claude" / "hooks"
    (hooks / "orphan_hook.py").write_text("print('x')\n")
    new = new_findings(repo)
    assert new == ["hook hooks/orphan_hook.py: not wired in settings.json and not staged by install.sh"]
    # staged by install.sh: fine
    inst = repo / "install.sh"
    inst.write_text(inst.read_text().replace("stage_script 755 hooks/web_caps.py",
                                             "stage_script 755 hooks/web_caps.py\nstage_script 755 hooks/orphan_hook.py"))
    assert new_findings(repo) == []


def test_hook_wired_in_settings_passes(repo):
    (repo / "dot-claude" / "hooks" / "wired_hook.py").write_text("print('x')\n")
    s = repo / "dot-claude" / "settings.json"
    data = json.loads(s.read_text())
    data["hooks"]["SessionEnd"][0]["hooks"].append(
        {"type": "command", "command": "\"__PYTHON3__\" \"__CLAUDE_DIR__/hooks/wired_hook.py\""})
    s.write_text(json.dumps(data))
    assert new_findings(repo) == []


def test_unstaged_existing_hook_is_found(repo):
    """Removing a hook's staging line from install.sh (and it has no settings.json wiring) fails."""
    inst = repo / "install.sh"
    text = inst.read_text()
    assert "stage_script 644 hooks/stack_report.py" in text
    inst.write_text(text.replace("stage_script 644 hooks/stack_report.py", ": unstaged"))
    assert any("hooks/stack_report.py" in n for n in new_findings(repo))


def test_removed_skill_listed_in_an_agents_skills_section_dangles(repo):
    """A plain `name` in `## Skills, if needed` counts (the agents' main way to name a skill)."""
    shutil.rmtree(repo / "dot-claude" / "skills" / "cpu-performance")
    new = new_findings(repo)
    assert any("ref agents/go-engineer.md: `cpu-performance` (no such skill)" in n for n in new), new
