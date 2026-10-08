"""Moved paths stay moved (Step R, 2026-10-05; layout of 2026-10-07): a repeatable dangling-reference check.

MOVES maps every old repository directory to its new one and the files the move took there. The
suite fails when
- an old path is still in git's index, or a moved file is missing from its new directory;
- any tracked text file names an old path in any spelling: plain or backslashed, an os.path.join
  or pathlib chain ("lib", "assets" / "lib" / "assets"), a shell split ("$X/lib"/assets) or a '+'
  concatenation. Git history keeps the old paths; no tracked file is exempt (this file aside);
- a root document (README.md, NOTICE, CONFIG.md) or a document inside a new directory links to a
  file there that does not exist (a mention of the git-ignored wiki checkout docs/wiki/ is not a link);
- docs/wiki (the GitHub wiki, its own repository) is tracked or not ignored.

2026-10-07 (dot-config): DIR_MOVES covers dot-claude, codex_config and equilibrium, which moved whole under
dot-config/ (renames only). Every file of the pre-move tree (PRE_MOVE_COMMIT) must exist at its new path, and
no tracked file may name the old directory in a path shape (dir_ref_hits). FROZEN lists the files that keep
old strings on purpose (pooled data, recorded or pinned bytes, fixtures, pinned c0 files, files agents may not
edit), MOVE_TOOLS the files whose job is the old layout (mapping it, testing the fallbacks for it), and
LINE_EXEMPT the sections, functions and single lines inside scanned files (dated records, pre-move fallbacks);
everything else is checked.

Run: uv run --with pytest pytest -q tests/test_moved_paths.py
"""
import ast
import fnmatch
import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SELF = "tests/test_moved_paths.py"
# old dir -> (new dir, the files the move took there)
MOVES = {
    "lib/assets": ("assets", ("LICENSE-CC-BY-4.0.txt", "PROVENANCE.md", "README.md", "blackcat-avatar-640.png",
                              "blackcat-hero-original.png", "blackcat-hero.jpg", "blackcat-social-1280x640.jpg")),
    # 2026-10-07: the README's architecture diagram joins the images; the runtime Equilibrium spec joins docs/
    "docs/diagrams": ("assets/diagrams", ("architecture.mmd", "architecture.svg")),
    "docs-design": ("docs", ("RUNTIME_EQUILIBRIUM.md",)),
}
# 2026-10-07: whole directories moved under dot-config/ (old dir -> new dir). The pre-move commit lists the files.
PRE_MOVE_COMMIT = "63ab4f04"
DIR_MOVES = {
    "dot-claude": "dot-config/dot-claude",
    "codex_config": "dot-config/dot-codex_config",
    "equilibrium": "dot-config/dot-equilibrium",
}
# Files that keep old path strings on purpose (recorded, pooled or pinned bytes), matched with fnmatch on the
# repo-relative path ('*' crosses '/'). Everything else is scanned.
FROZEN = (
    "dot-config/dot-equilibrium/items/*",          # pooled data: pool.sha256, gen/src/prompts.csv, RS fixtures
    "dot-config/dot-equilibrium/PATH_RELATIVISATION.json",
    "tests/fixtures/sched/*",
    "tests/fixtures/reports/*.txt",
    "*.out",                                         # recorded outputs (mutations.out, derive_numbers.out, ...)
    "hand_off/c0_support/*",                         # pinned by PINS.sha256
    # A5-recorded bytes (PATH_RELATIVISATION.json "files": an edit needs a COMPARE_eq §12 amendment), among them
    # the stage-text outputs; the A5 record's prose; a dated run record
    "dot-config/dot-equilibrium/PROPOSAL.md",
    "dot-config/dot-equilibrium/isolation/INSTALLER_SPEC.md",
    "dot-config/dot-equilibrium/isolation/RUNBOOK.md",
    "dot-config/dot-equilibrium/isolation/RUNBOOK_MINIMAL.md",
    "dot-config/dot-equilibrium/wall/*",             # the staging copy of lib/eq-wall
    "dot-config/dot-equilibrium/PATH_RELATIVISATION.md",
    "dot-config/dot-equilibrium/harness/R2_RUN.md",
    # lib/eq-wall: agents never edit it (REVIEW-pinned)
    "lib/eq-wall/*",
)
# Files whose job is the old layout: the A5/A9 record's tool and its tests (old_rel() maps keys back to the
# pre-move paths; pre-move commits are read at them) and the installer's pre-move fallback tests. Not scanned.
MOVE_TOOLS = (
    "tests/equilibrium_paths.py",
    "tests/test_equilibrium_paths.py",
    "tests/test_install_dot_config.py",
)
# Line-level exemptions inside otherwise scanned files: historical records that keep the names of their day,
# and code that reads the old layout on purpose. rel -> function(lines) -> set of 0-based line indexes exempt.


def _section(prefix):
    """The lines of the '## ' section whose heading starts with `prefix`, through the next '## ' heading."""
    def f(lines):
        out, on = set(), False
        for i, line in enumerate(lines):
            if line.startswith("## "):
                on = line.startswith(prefix)
            if on:
                out.add(i)
        return out
    f.section = prefix
    return f


def _lines(*patterns):
    """The single lines matching one of `patterns` (regexes); test_exemptions_still_apply keeps each live."""
    rxs = [re.compile(p) for p in patterns]

    def f(lines):
        return {i for i, line in enumerate(lines) if any(rx.search(line) for rx in rxs)}
    f.patterns = rxs
    return f


def _defs(*names):
    """The lines of the named top-level Python functions: tests that rebuild the pre-move layout on purpose."""
    def f(lines):
        tree = ast.parse("\n".join(lines))
        return {i for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in names
                for i in range(node.lineno - 1, node.end_lineno)}
    f.names = names
    return f


def _changelog_before_move(lines):
    """CONFIG.md '## 9. Changelog': the '### YYYY-MM-DD' entries dated before 2026-10-07."""
    out, in_log, old = set(), False, False
    for i, line in enumerate(lines):
        if line.startswith("## "):
            in_log, old = line.startswith("## 9."), False
        elif in_log and line.startswith("### "):
            m = re.match(r"### (\d{4}-\d{2}-\d{2})", line)
            old = bool(m) and m.group(1) < "2026-10-07"
        if in_log and old:
            out.add(i)
    return out


LINE_EXEMPT = {
    "CONFIG.md": _changelog_before_move,
    # the dated amendments (append only), each in the names of its day; A9 records the move itself
    "dot-config/dot-equilibrium/COMPARE_eq.md": _section("## 12."),
    # the A9 note and a dated record
    "dot-config/dot-equilibrium/README.md": _lines(r"the A5 record name it `equilibrium/`",
                                                   r"to `equilibrium/` for the commits before the move",
                                                   r"EQ-T against `equilibrium/`, caches excluded, 2026-10-06"),
    # pre-move fallbacks (a manifest commit from before the move holds the old layout)
    "install.sh": _lines(r"before the dot-config/ move", r"prev_commit:dot-claude\b",
                         r'prev_paths="\$SUPPLY_PATHS dot-claude"', r'"dot-claude/settings\.json"\):'),
    "tests/prompt_budget.py": _lines(r'^OLD_DOT = "dot-claude"'),
    "dot-config/dot-codex_config/lib/source_snapshot.py": _lines(r"^LEGACY_PATHS = "),
    "dot-config/dot-codex_config/tests/test_source_snapshot.py":
        _defs("test_changes_since_a_pre_move_commit_covers_the_old_paths"),
    "dot-config/dot-codex_config/tests/test_installer_e2e.py":
        _defs("test_supply_review_from_a_pre_move_install_covers_the_old_paths"),
    # provenance at a commit, in the installed guard (its bytes stay unchanged)
    "dot-config/dot-codex_config/hooks/codex_guard.py":
        _lines(r"Ported from dot-claude/hooks/agent_guard\.py at commit"),
    # frozen prose: flags.json (a freeze input) and its copy DEFAULT_FLAGS; a comment in the sha-pinned mediator
    "dot-config/dot-equilibrium/harness/flags.json": _lines(r"\(dot-claude/agents/<type>\.md `model:`"),
    "dot-config/dot-equilibrium/harness/eq_harness.py": _lines(r"\(dot-claude/agents/<type>\.md `model:`"),
    "dot-config/dot-equilibrium/harness/eq_mediator.py": _lines(r"stdlib port is dot-claude/hooks/eq_core\.py"),
    # the agents dir as this tree's sibling inside dot-config/ (STAGE.parent): right after the move too
    "dot-config/dot-equilibrium/harness/tests/test_model_map.py": _lines(r"`\.\./dot-claude/agents`",
                                                                         r'STAGE\.parent / "dot-claude" / "agents"',
                                                                         r"no dot-claude/agents beside this copy"),
    # scratch trees: the frozen package under work_carried (eq_check.sh's $W/equilibrium), a mutant's copy
    "dot-config/dot-equilibrium/harness/tests/test_shell.py": _lines(r'^\s*eq = w / "equilibrium"$'),
    "dot-config/dot-equilibrium/harness/tests/test_calibrate_mutants.py":
        _lines(r'^\s*root = tmp_path / mid / "equilibrium"$'),
    # the c0 arm's commits (a22c5b4, 7d12c58, the installed 73eec41) hold the pre-move layout
    "hand_off/RUNBOOK_c0.md": _lines(r"\b(?:a22c5b4|7d12c58|73eec41)\b"),
}


def frozen(rel):
    return any(fnmatch.fnmatchcase(rel, g) for g in FROZEN)


ROOT_DOCS = ("README.md", "NOTICE", "CONFIG.md")
# separators a reference to a/b can use: / or \ (optionally around quotes or after a call's ")"), a
# quoted join, a quoted '+'
_SEP = r"""(?:["']?\)?\s*/\s*["']?|\\{1,2}|["']\s*,\s*["']|/?["']\s*\+\s*["']/?)"""


def old_path_re(old):
    return re.compile(r"(?<![\w.-])" + _SEP.join(re.escape(p) for p in old.split("/")) + r"(?![\w-])")


# --- the three moved directories: path-shaped references only ---------------------------------------------
# `equilibrium` is also an agent type (subagent_type, settings/flags/limits keys) and `codex_config` an identity
# ("installer": "codex_config", codex_config_* modules): only a path shape counts, never the bare word.
_Q = r"""["']"""
# the new spelling (dot-config/dot-claude, "dot-config" / "dot-claude", a brace list dot-config/{dot-claude,...})
# and run-output dirs are removed first: .claude-work/equilibrium/runs, the frozen package under
# claude_next_steps/work_carried (EQ_ROOT's default, `EQ=$W/equilibrium` in the eq scripts and their docs)
_NEW_DOTCLAUDE = re.compile(r"dot-config" + r"""(?:["']?\)?\s*[/\\]\s*["']?|["']\s*,\s*["'])""" + r"dot-claude")
_NEW_BRACES = re.compile(r"dot-config/\{[\w,.-]*\}")
_RUNS = re.compile(r"""(?:\.claude-work|work_carried)(?:["']?\)?\s*[/\\]\s*["']?)equilibrium"""
                   r"""|\bEQ=(?:\$\{EQ_ROOT:-)?\$W/equilibrium""")
# the equilibrium skill/agent/command inside the Claude tree is the agent type's own file, not the experiment dir
_AGENT_FILES = re.compile(r"""\b(skills|agents|commands)(?:["']?\)?\s*[/\\]\s*["']?)equilibrium""")
_JOIN_CTX = re.compile(r"join\(|Path\(|joinpath|PurePath|os\.path")


def dir_ref_hits(old, line):
    """True when `line` names the old directory `old` (dot-claude, codex_config, equilibrium) as a path."""
    line = _AGENT_FILES.sub(r"\1/AGENT", _RUNS.sub("RUNS", _NEW_DOTCLAUDE.sub("NEW", _NEW_BRACES.sub("NEW", line))))
    n = re.escape(old)
    word = r"(?<![\w.-])" + n + r"(?![\w-])"
    if old == "dot-claude":                       # a distinctive name: any bare mention is a reference
        return re.search(word, line) is not None
    shapes = [
        r"(?<![\w.-])" + n + r"(?:/|\\{1,2}(?!`)|" + _Q + r"\)?\s*/|" + _Q + r"\s*\+\s*" + _Q + r"/)",   # equilibrium/x, "equilibrium" / "x"
        r"(?:[\w}$~)]/|(?:" + _Q + r"|\))\s*/\s*" + _Q + r"?|\w\s/\s" + _Q + r"|\\{1,2})" + n + r"(?![\w-]|\.\w)",  # $M/equilibrium, ROOT / 'equilibrium'
        r"(?:\)|(?<!-)--\s|\bcd\s|\bls\s|\bgit add\s|\bls-files\s)" + n + r"(?![\w-])",                        # ':(exclude)equilibrium', cd equilibrium
        r"(?<=\s)-[A-Za-z]+\s" + n + r"(?![\w.-])",                                                          # cp -pR equilibrium x
    ]
    if _JOIN_CTX.search(line):                    # os.path.join(root, "x", "equilibrium"), join(ROOT, "equilibrium")
        shapes.append(_Q + n + _Q + r"\s*,\s*" + _Q)
        shapes.append(_Q + r"\s*,\s*" + _Q + n + _Q)
        shapes.append(r",\s*" + _Q + n + _Q + r"\s*\)")
    return any(re.search(s, line) for s in shapes)


def git(*args):
    return subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True, check=True).stdout


def ls_files(*paths):
    return sorted(p for p in git("ls-files", "-z", "--", *paths).decode("utf-8", "surrogateescape").split("\0") if p)


WIKI = "docs/wiki/"     # the GitHub wiki's local checkout: git-ignored, absent in a fresh clone


def ignored(rel):
    """A mention of the ignored wiki checkout, not a link into a moved dir (test_wiki_is_its_own_repository
    proves the ignore). Only this prefix: a check-ignore lookup would also honour local excludes."""
    return rel == WIKI or rel.startswith(WIKI)


@pytest.mark.parametrize("old,text,hit", [
    ("lib/assets", "see lib/assets/README.md", True),
    ("lib/assets", '<img src="lib/assets/blackcat-hero.jpg">', True),
    ("lib/assets", "':(exclude)lib/assets'", True),
    ("lib/assets", 'os.path.join(ROOT, "lib", "assets", "x.png")', True),
    ("lib/assets", "ROOT / 'lib' / 'assets'", True),
    ("lib/assets", '"$HERE/lib"/assets/x', True),
    ("lib/assets", 'Path("lib") / "assets"', True),
    ("lib/assets", 'ROOT.joinpath("lib") / "assets"', True),
    ("lib/assets", '"lib/" + "assets"', True),
    ("lib/assets", "lib\\assets\\x", True),
    ("lib/assets", '"lib" + "/assets"', True),
    ("lib/assets", "assets/blackcat-hero.jpg", False),
    ("lib/assets", "lib/install_state.py and assets/", False),
    ("lib/assets", "stdlib/assets", False),
    ("lib/assets", "mylib/assets", False),
    ("lib/assets", "lib, assets and docs", False),
    ("lib/assets", "lib/assets-old", False),
    ("docs/diagrams", '<img src="docs/diagrams/architecture.svg">', True),
    ("docs/diagrams", "ROOT / 'docs' / 'diagrams'", True),
    ("docs/diagrams", '<img src="assets/diagrams/architecture.svg">', False),
    ("docs/diagrams", "code.claude.com/docs/en/hooks", False),
    ("docs-design", "spec: `docs-design/RUNTIME_EQUILIBRIUM.md` rev 2", True),
    ("docs-design", '"$M/docs-design"/RUNTIME_EQUILIBRIUM.md', True),
    ("docs-design", "spec: `docs/RUNTIME_EQUILIBRIUM.md` rev 2", False),
    ("docs-design", "my-docs-design or docs-designs", False),
])
def test_old_path_pattern(old, text, hit):
    assert bool(old_path_re(old).search(text)) is hit


@pytest.mark.parametrize("old,text,hit", [
    # old forms
    ("dot-claude", "see dot-claude/agents/blackcat.md", True),
    ("dot-claude", "git add dot-claude", True),
    ("dot-claude", 'os.path.join(ROOT, "dot-claude", "hooks")', True),
    ("dot-claude", 'ROOT / "dot-claude" / "hooks"', True),
    ("dot-claude", "'$HERE/dot-claude'/hooks", True),
    ("dot-claude", "cp -r dot-claude\\\\hooks x", True),
    ("dot-claude", "see dot-config/dot-claude/hooks and dot-claude/hooks", True),
    ("codex_config", "bash codex_config/install.sh", True),
    ("codex_config", "':(exclude)codex_config'", True),
    ("codex_config", 'os.path.join(ROOT, "codex_config", "probes")', True),
    ("codex_config", 'ROOT / "codex_config" / "probes"', True),
    ("codex_config", '"$HERE/codex_config"/install.sh', True),
    ("codex_config", '"codex_config" + "/x"', True),
    ("codex_config", "$M/codex_config", True),
    ("codex_config", "cd codex_config", True),
    ("equilibrium", "see equilibrium/COMPARE_eq.md", True),
    ("equilibrium", "$M/equilibrium", True),
    ("equilibrium", "ROOT / 'equilibrium' / 'wall'", True),
    ("equilibrium", 'Path(ROOT) / "equilibrium"', True),
    ("equilibrium", 'os.path.join(ROOT, "equilibrium", "items")', True),
    ("equilibrium", '"$HERE/equilibrium"/items', True),
    ("equilibrium", "':(exclude)equilibrium'", True),
    ("equilibrium", 'git ls-files -- equilibrium', True),
    # new forms are not references
    ("dot-claude", "dot-config/dot-claude/agents/x.md", False),
    ("dot-claude", 'ROOT / "dot-config" / "dot-claude" / "hooks"', False),
    ("dot-claude", 'os.path.join(ROOT, "dot-config", "dot-claude")', False),
    ("dot-claude", "~/.claude/hooks and dot-claude-code", False),
    ("codex_config", "dot-config/dot-codex_config/install.sh", False),
    ("codex_config", 'ROOT / "dot-config" / "dot-codex_config"', False),
    ("equilibrium", "dot-config/dot-equilibrium/items", False),
    ("equilibrium", 'ROOT / "dot-config" / "dot-equilibrium" / "wall"', False),
    # identities and the agent type are not paths
    ("codex_config", '"installer": "codex_config"', False),
    ("codex_config", "importlib: codex_config_install, codex_config_probe", False),
    ("codex_config", "the codex_config installer", False),
    ("equilibrium", "subagent_type: equilibrium", False),
    ("equilibrium", '"equilibrium": {"effort": "max"}', False),
    ("equilibrium", '"agent_effort": {"equilibrium": "max"}', False),
    ("equilibrium", 'AGENTS = ["blackcat", "equilibrium", "reviewer"]', False),
    ("equilibrium", "--agent equilibrium", False),
    ("equilibrium", "agents/equilibrium.md", False),
    ("equilibrium", "the equilibrium agent", False),
    ("equilibrium", "docs/equilibrium.md and notes/equilibrium.txt", False),
    ("dot-claude", "my-dot-claude, x.dot-claude, mydot-claude", False),
    ("equilibrium", "dot-config/dot-claude/skills/equilibrium/SKILL.md, agents/equilibrium.md", False),
    ("equilibrium", "dot-config/dot-claude/skills/equilibrium/ and equilibrium/harness", True),
    # run-output dirs and installed paths
    ("equilibrium", ".claude-work/equilibrium/runs/r1", False),
    ("equilibrium", 'ROOT / ".claude-work" / "equilibrium" / "runs"', False),
    ("equilibrium", "$HOME/.claude/agents/equilibrium.md", False),
    ("dot-claude", "$HOME/.claude/settings.json", False),
    # the frozen package under work_carried is a run location, not the experiment dir
    ("equilibrium", "claude_next_steps/work_carried/equilibrium", False),
    ("equilibrium", 'repo / "claude_next_steps" / "work_carried" / "equilibrium"', False),
    ("equilibrium", "EQ=${EQ_ROOT:-$W/equilibrium}", False),
    ("equilibrium", "`M=.`, `W=$M/claude_next_steps/work_carried`, `EQ=$W/equilibrium`,", False),
    ("equilibrium", "rsync -a $W/equilibrium/ x", True),
    ("equilibrium", "work_carried and equilibrium/harness", True),
    # integration sweep, 2026-10-07: false positives fixed narrowly
    ("dot-claude", "Move to `dot-config/{dot-claude,dot-codex_config,dot-equilibrium}` with", False),
    ("dot-claude", "cp -r {dot-claude,lib} x", True),
    ("equilibrium", "(exception: an \\`equilibrium\\` run's members, spawned only by that agent)", False),
    ("equilibrium", "equilibrium\\harness\\eq_check.sh", True),
    ("equilibrium", "# -------------------------------------------------------- equilibrium: the eq rules", False),
    ("equilibrium", "git diff a b -- equilibrium", True),
    # review round, 2026-10-07: after a short-option cluster, after ls-files, as a join's last argument
    ("equilibrium", "cp -pR equilibrium x", True),
    ("equilibrium", 'S=$(mktemp -d) && cp -pR equilibrium "$S/stage"', True),
    ("equilibrium", "rsync -a equilibrium x", True),
    ("codex_config", "git ls-files codex_config", True),
    ("equilibrium", 'os.path.join(ROOT, "equilibrium")', True),
    ("codex_config", "Path(ROOT, 'codex_config')", True),
    ("equilibrium", "claude -p --agent equilibrium --max-budget-usd 0.50", False),
    ("equilibrium", 'os.path.join(ROOT, "equilibrium.md")', False),
    ("equilibrium", 'json.dumps({"agent": "equilibrium"})', False),
])
def test_dir_ref_pattern(old, text, hit):
    assert dir_ref_hits(old, text) is hit


def test_frozen_and_line_exemptions():
    assert frozen("dot-config/dot-equilibrium/items/CP/pool.sha256")
    assert frozen("dot-config/dot-equilibrium/items/RS/gen/src/prompts.csv")
    assert frozen("dot-config/dot-equilibrium/PATH_RELATIVISATION.json")
    assert frozen("tests/fixtures/sched/4e2da3ce/prompts.csv")
    assert frozen("tests/fixtures/reports/a.txt")
    assert frozen("dot-config/dot-equilibrium/harness/tests/mutations.out")
    assert frozen("hand_off/c0_support/c0_check.sh")
    assert not frozen("dot-config/dot-equilibrium/harness/eq_harness.py")
    assert not frozen("tests/fixtures/reports/a.py")
    assert not frozen("hand_off/RUNBOOK_c0.md")
    log = ["## 8. Validation", "x", "## 9. Changelog", "intro", "### 2026-10-07 (new)", "a", "### 2026-10-06 (old)", "b",
           "### 2026-10-05 (older)", "c", "## 10. Tail", "d"]
    assert _changelog_before_move(log) == {6, 7, 8, 9}
    assert frozen("dot-config/dot-equilibrium/isolation/RUNBOOK_MINIMAL.md") and frozen("lib/eq-wall/INSTALLER_WALL.md")
    assert not frozen("tools/instructor/bin/check_suite.py")
    assert not frozen("dot-config/dot-equilibrium/COMPARE_eq.md") and not frozen("install.sh")
    assert _section("## 12.")(["## 11. x", "a", "## 12. Amendments", "b", "### A9", "c"]) == {2, 3, 4, 5}
    assert _lines(r"^OLD = ")(["x", "OLD = 1", "NOLD = 2"]) == {1}
    src = ["def t_new():", "    pass", "", "def t_old():", '    """doc', '    """', "    pass", "x = 1"]
    assert _defs("t_old")(src) == {3, 4, 5, 6}


def test_instructor_files_no_longer_name_the_old_guard_path():
    """The instructor patch is on main: its three files carry the new path and need no line exemption."""
    for rel in ("tools/instructor/bin/check_suite.py", "tools/instructor/tests/test_instr_check_suite.py",
                "tools/instructor/tests/test_instr_ff_merge.py"):
        assert rel not in LINE_EXEMPT
        assert '"dot-claude/hooks/agent_guard.py"' not in (ROOT / rel).read_text(encoding="utf-8"), rel


def test_exemptions_still_apply():
    """Every exemption names something that exists, and every line exemption still covers an old-path line:
    a stale entry (the line fixed, the file or function gone) fails here and is removed."""
    tracked = ls_files()
    assert all(any(fnmatch.fnmatchcase(rel, g) for rel in tracked) for g in FROZEN), "a FROZEN glob matches no file"
    assert all(rel in tracked for rel in MOVE_TOOLS), "a MOVE_TOOLS file is not tracked"
    stale = []
    for rel, f in LINE_EXEMPT.items():
        assert rel in tracked, rel
        lines = (ROOT / rel).read_text(encoding="utf-8").splitlines()
        hit = {i for i, line in enumerate(lines) if any(dir_ref_hits(old, line) for old in DIR_MOVES)}
        for rx in getattr(f, "patterns", ()):
            if not {i for i, line in enumerate(lines) if rx.search(line)} & hit:
                stale.append("%s: %s" % (rel, rx.pattern))
        for name in getattr(f, "names", ()):
            if not _defs(name)(lines) & hit:
                stale.append("%s: def %s" % (rel, name))
        if not f(lines) & hit:
            stale.append("%s: %s" % (rel, getattr(f, "section", f.__name__)))
    assert not stale, "line exemptions that cover no old-path line:\n" + "\n".join(stale)


@pytest.mark.parametrize("old", sorted(DIR_MOVES))
def test_dir_moves_leave_nothing_at_the_old_path(old):
    assert ls_files(old) == [], "still tracked at the old path"
    assert ls_files(DIR_MOVES[old]) != [], "nothing tracked at the new path"


def test_every_pre_move_file_exists_at_its_new_path():
    pre = subprocess.run(["git", "-C", str(ROOT), "ls-tree", "-r", "--name-only", "-z", PRE_MOVE_COMMIT, "--",
                          *DIR_MOVES], capture_output=True)
    if pre.returncode != 0:
        pytest.skip("%s is not in this clone's history" % PRE_MOVE_COMMIT)
    old_files = [p for p in pre.stdout.decode("utf-8", "surrogateescape").split("\0") if p]
    assert old_files, "the pre-move listing is empty"
    tracked = set(ls_files())
    missing = []
    for f in old_files:
        top, _, rest = f.partition("/")
        assert top in DIR_MOVES, f
        if "%s/%s" % (DIR_MOVES[top], rest) not in tracked:
            missing.append(f)
    assert not missing, "%d pre-move files have no counterpart at the new path:\n%s" % (len(missing), "\n".join(missing[:40]))


@pytest.mark.parametrize("old", sorted(MOVES))
def test_index_holds_the_new_paths_only(old):
    new, names = MOVES[old]
    assert ls_files(old) == [], "still tracked at the old path"
    tracked = set(ls_files(new))
    assert [n for n in names if "%s/%s" % (new, n) not in tracked] == [], "moved file missing at the new path"


def scan_dir_refs():
    """['rel:line: old', ...] for every unfrozen tracked text line naming a moved directory by its old path."""
    hits = []
    for rel in ls_files():
        if rel == SELF or rel in MOVE_TOOLS or frozen(rel):
            continue
        p = ROOT / rel
        if p.is_symlink() or not p.is_file():
            continue
        data = p.read_bytes()
        if b"\0" in data[:8192]:
            continue
        lines = data.decode("utf-8", "replace").splitlines()
        skip = LINE_EXEMPT[rel](lines) if rel in LINE_EXEMPT else ()
        for n, line in enumerate(lines):
            if n not in skip:
                hits += ["%s:%d: %s" % (rel, n + 1, old) for old in DIR_MOVES if dir_ref_hits(old, line)]
    return hits


def test_no_tracked_file_names_an_old_directory():
    hits = scan_dir_refs()
    assert not hits, "%d old directory paths named again (use dot-config/...):\n%s" % (len(hits), "\n".join(hits[:60]))


def test_no_tracked_file_names_an_old_path():
    pats = {old: old_path_re(old) for old in MOVES}
    hits = []
    for rel in ls_files():
        if rel == SELF:
            continue
        p = ROOT / rel
        if p.is_symlink() or not p.is_file():
            continue
        data = p.read_bytes()
        if b"\0" in data[:8192]:           # binary
            continue
        for n, line in enumerate(data.decode("utf-8", "replace").splitlines(), 1):
            hits += ["%s:%d: %s" % (rel, n, old) for old, rx in pats.items() if rx.search(line)]
    assert not hits, "old paths named again (use the new ones):\n" + "\n".join(hits[:40])


def test_links_into_the_new_dirs_resolve():
    bad = []
    for new, _names in MOVES.values():
        ref = re.compile(r"(?<![\w./-])(?:\./)?%s/[\w./-]*" % re.escape(new))     # assets/x or ./assets/x
        for doc in ROOT_DOCS:
            for n, line in enumerate((ROOT / doc).read_text(encoding="utf-8").splitlines(), 1):
                for m in ref.finditer(line):
                    target = m.group(0).rstrip(".")
                    if not (ROOT / target).exists() and not ignored(target):
                        bad.append("%s:%d: %s" % (doc, n, target))
        # relative links inside the moved folder ([text](target), no scheme, no anchor-only)
        for md in sorted((ROOT / new).glob("*.md")):
            for n, line in enumerate(md.read_text(encoding="utf-8").splitlines(), 1):
                for target in re.findall(r"\]\(([^)#\s]+)\)", line):
                    if "://" not in target and not (md.parent / target).exists():
                        bad.append("%s:%d: %s" % (md.relative_to(ROOT), n, target))
    assert not bad, "dangling links:\n" + "\n".join(bad)


def test_wiki_is_its_own_repository():
    assert ls_files("docs/wiki") == []
    rc = subprocess.run(["git", "-C", str(ROOT), "check-ignore", "-q", "docs/wiki/Home.md"]).returncode
    assert rc == 0, "docs/wiki/ must be git-ignored"
