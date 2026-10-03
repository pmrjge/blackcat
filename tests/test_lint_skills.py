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


def test_stale_skill_refs_flags_retired_names_only():
    """A retired (folded) skill name is stale unless it is a provenance note or a references/ path."""
    f = lint_agents.stale_skill_refs
    assert f("Part of `technical-writing` (what goes on each page: `write-docs-adr`, Diátaxis).") == [
        "write-docs-adr"]
    assert f("Bit-level queries: `fm-smt-z3`.") == ["fm-smt-z3"]
    assert f("Read when writing a TS MCP server (was the `mcp-ts-server` skill).") == []
    assert f("Protocol facts: `references/net-protocols.md` in `self-hosting-ops`.") == []
    assert f("`technical-writing` `references/docs-adr.md`; `git-workflows`, `formal-methods`") == []


def test_no_shipped_text_names_a_retired_skill():
    root = SKILLS.parent
    shipped = {p.parent.name for p in SKILLS.glob("*/SKILL.md")}
    assert not lint_agents.RETIRED_SKILLS & shipped, "RETIRED_SKILLS names a shipped skill"
    bad = []
    for p in sorted(root.glob("agents/*.md")) + sorted(SKILLS.rglob("*.md")) + sorted(root.glob("rules/*.md")):
        if lint_agents.under_work_dir(p):
            continue
        for n, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
            bad += ["%s:%d %s" % (p.relative_to(root), n, s) for s in lint_agents.stale_skill_refs(line)]
    assert not bad, "text names retired skills: %s" % bad


def test_model_id_regex_catches_new_and_old_style_ids_only():
    ids = ["claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-4-5-20251001", "claude-fable-5-1",
           "claude-3-5-sonnet-20241022", "claude-3-opus-20240229", "claude-3-7-sonnet-latest", "claude-3-haiku-20240307"]
    for v in ids:
        assert lint_agents.MODEL_ID_RE.search(v), v
    for v in ["opus", "sonnet", "haiku", "claude-haiku-old", "claude-opus-old[1m]", "model-x",
              "claude-code-guide", "claude-agent-stack", "ANTHROPIC_DEFAULT_<FAMILY>_MODEL"]:
        assert not lint_agents.MODEL_ID_RE.search(v), v


def test_model_ids_only_in_the_allowed_places(tmp_path):
    (tmp_path / "stack.env.example").write_text("ANTHROPIC_DEFAULT_OPUS_MODEL=claude-opus-5-5\n")
    (tmp_path / "install.sh").write_text('OLD_DEFAULTS = {"X": {"claude-sonnet-5"}}\nY="claude-3-opus-20240229"\n')
    (tmp_path / "legacy" / "v").mkdir(parents=True)
    (tmp_path / "legacy" / "v" / "a.md").write_text("model: claude-opus-5-5\n")
    (tmp_path / "README.md").write_text("pins claude-3-5-sonnet-20241022\nmodel: opus\n")
    assert sorted(lint_agents.check_model_ids(tmp_path)) == ["README.md:1", "install.sh:2"]


BAD = "model: claude-opus-5-5\n"           # a specific model ID: the model-ID check's finding


def _git(root, *args):
    import subprocess
    subprocess.run(["git", "-c", "core.hooksPath=/dev/null", "-c", "commit.gpgsign=false", "-c",
                    "user.name=t", "-c", "user.email=t@example.invalid", "-C", str(root), *args],
                   check=True, capture_output=True, stdin=subprocess.DEVNULL)


def _tree(root):
    for rel in (".claude-work/x/a.md", "dot-claude/skills/s/.claude-work/x/b.md", "dot-claude/agents/bad.md",
                "notes.claude-work/c.md", ".claude-work-old/d.md"):
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(BAD)
    return ["dot-claude/agents/bad.md:1", ".claude-work-old/d.md:1", "notes.claude-work/c.md:1"]


def test_model_ids_skip_claude_work_at_any_depth_tracked_or_walked(tmp_path):
    """.claude-work/ is agents' scratch: skipped as a path component at any depth, also when force-added
    to git; the same content under dot-claude/agents/ and look-alike names still fail."""
    want = _tree(tmp_path)
    assert sorted(lint_agents.check_model_ids(tmp_path)) == sorted(want)          # no git: tree walk
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "add", "-f", ".")                                               # .claude-work tracked
    assert sorted(lint_agents.check_model_ids(tmp_path)) == sorted(want)          # git ls-files


def test_model_ids_skip_claude_work_through_symlinked_and_nested_roots(tmp_path):
    """A checkout reached through a symlink, or itself inside another tree's .claude-work/, lints its
    own files: only the components below the root count."""
    repo = tmp_path / "outer" / ".claude-work" / "wt"
    repo.mkdir(parents=True)
    want = _tree(repo)
    (tmp_path / "link").symlink_to(repo)
    for root in (repo, tmp_path / "link"):
        assert sorted(lint_agents.check_model_ids(root)) == sorted(want), root
    f = lint_agents.under_work_dir
    for root in (repo, tmp_path / "link"):
        assert f(root / ".claude-work" / "x" / "a.md", root)
        assert f(repo / ".claude-work" / "x" / "a.md", root)                    # resolved path, link root
        assert not f(root / "dot-claude" / "agents" / "bad.md", root)
        assert not f(repo / "dot-claude" / "agents" / "bad.md", root)
    assert f(".claude-work/x/a.md", repo) and f("a/b/.claude-work/c", repo)
    assert not f("dot-claude/agents/bad.md", repo) and not f(".claude-work-old/d.md", repo)
    rel_root = Path("outer") / ".claude-work" / "wt"                            # a relative root
    assert f(rel_root / ".claude-work" / "a.md", rel_root)
    assert not f(rel_root / "dot-claude" / "agents" / "bad.md", rel_root)


def test_text_checks_skip_claude_work_but_not_dot_claude(tmp_path, monkeypatch):
    """check_bare_python and check_stale_skill_refs: a bad file under a skill's .claude-work/ is ignored,
    the same text in dot-claude/agents/ fails."""
    dc = tmp_path / "dot-claude"
    bad = "python3 run.py and `fm-smt-z3`\n"                                       # bare python + retired skill
    for rel in ("skills/s/.claude-work/x/n.md", "agents/bad.md"):
        (dc / rel).parent.mkdir(parents=True, exist_ok=True)
        (dc / rel).write_text(bad)
    (dc / "skills" / "s" / "SKILL.md").write_text("---\nname: s\n---\n")
    for k, v in (("REPO_ROOT", tmp_path), ("AGENTS_DIR", dc / "agents"), ("SKILLS_DIR", dc / "skills")):
        monkeypatch.setattr(lint_agents, k, v)
    monkeypatch.setattr(lint_agents, "errors", [])
    lint_agents.check_bare_python()
    lint_agents.check_stale_skill_refs()
    assert lint_agents.errors and all(e.startswith("agents/bad.md:1:") for e in lint_agents.errors), \
        lint_agents.errors
    assert len(lint_agents.errors) == 2
