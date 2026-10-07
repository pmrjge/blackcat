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
no tracked file may name the old directory in a path shape (dir_ref_hits). FROZEN lists the files and
sections that keep old strings on purpose (pooled data, recorded outputs, fixtures, pinned c0 files,
historical records); everything else is checked.

Run: uv run --with pytest pytest -q tests/test_moved_paths.py
"""
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
)
# Line-level exemptions inside otherwise scanned files: historical records that keep the names of their day.
# rel -> function(lines) -> set of 0-based line indexes exempt.


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


def _handoff_section_8(lines):
    """hand_off/HANDOFF_STATE.md '## 8.' (the progress rows, a log of what was done under the old names)."""
    out, on = set(), False
    for i, line in enumerate(lines):
        if line.startswith("## "):
            on = line.startswith("## 8.")
        if on:
            out.add(i)
    return out


LINE_EXEMPT = {
    "CONFIG.md": _changelog_before_move,
    "hand_off/HANDOFF_STATE.md": _handoff_section_8,
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
# the new spelling (dot-config/dot-claude, "dot-config" / "dot-claude") and run-output dirs are removed first
_NEW_DOTCLAUDE = re.compile(r"dot-config" + r"""(?:["']?\)?\s*[/\\]\s*["']?|["']\s*,\s*["'])""" + r"dot-claude")
_RUNS = re.compile(r"""\.claude-work(?:["']?\)?\s*[/\\]\s*["']?)equilibrium""")
# the equilibrium skill/agent/command inside the Claude tree is the agent type's own file, not the experiment dir
_AGENT_FILES = re.compile(r"""\b(skills|agents|commands)(?:["']?\)?\s*[/\\]\s*["']?)equilibrium""")
_JOIN_CTX = re.compile(r"join\(|Path\(|joinpath|PurePath|os\.path")


def dir_ref_hits(old, line):
    """True when `line` names the old directory `old` (dot-claude, codex_config, equilibrium) as a path."""
    line = _AGENT_FILES.sub(r"\1/AGENT", _RUNS.sub("RUNS", _NEW_DOTCLAUDE.sub("NEW", line)))
    n = re.escape(old)
    word = r"(?<![\w.-])" + n + r"(?![\w-])"
    if old == "dot-claude":                       # a distinctive name: any bare mention is a reference
        return re.search(word, line) is not None
    shapes = [
        r"(?<![\w.-])" + n + r"(?:/|\\{1,2}|" + _Q + r"\)?\s*/|" + _Q + r"\s*\+\s*" + _Q + r"/)",   # equilibrium/x, "equilibrium" / "x"
        r"(?:[\w}$~)]/|(?:" + _Q + r"|\))\s*/\s*" + _Q + r"?|\w\s/\s" + _Q + r"|\\{1,2})" + n + r"(?![\w-]|\.\w)",  # $M/equilibrium, ROOT / 'equilibrium'
        r"(?:\)|--\s|\bcd\s|\bls\s|\bgit add\s)" + n + r"(?![\w-])",                                      # ':(exclude)equilibrium', cd equilibrium
    ]
    if _JOIN_CTX.search(line):                    # os.path.join(root, "x", "equilibrium")
        shapes.append(_Q + n + _Q + r"\s*,\s*" + _Q)
        shapes.append(_Q + r"\s*,\s*" + _Q + n + _Q)
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
    assert _handoff_section_8(["## 7. x", "a", "## 8. Progress", "b", "c", "## 9. Next", "d"]) == {2, 3, 4}


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
        if rel == SELF or frozen(rel):
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
