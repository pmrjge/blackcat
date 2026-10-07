"""Moved paths stay moved (Step R, 2026-10-05; layout of 2026-10-07): a repeatable dangling-reference check.

MOVES maps every old repository directory to its new one and the files the move took there. The
suite fails when
- an old path is still in git's index, or a moved file is missing from its new directory;
- any tracked text file names an old path in any spelling: plain or backslashed, an os.path.join
  or pathlib chain ("lib", "assets" / "lib" / "assets"), a shell split ("$X/lib"/assets) or a '+'
  concatenation. Git history keeps the old paths; no tracked file is exempt (this file aside);
- a root document (README.md, NOTICE, CONFIG.md) or a document inside a new directory links to a
  file there that does not exist (a git-ignored path, such as docs/wiki/, is not a link into it);
- docs/wiki (the GitHub wiki, its own repository) is tracked or not ignored.

Run: uv run --with pytest pytest -q tests/test_moved_paths.py
"""
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
ROOT_DOCS = ("README.md", "NOTICE", "CONFIG.md")
# separators a reference to a/b can use: / or \ (optionally around quotes or after a call's ")"), a
# quoted join, a quoted '+'
_SEP = r"""(?:["']?\)?\s*/\s*["']?|\\{1,2}|["']\s*,\s*["']|/?["']\s*\+\s*["']/?)"""


def old_path_re(old):
    return re.compile(r"(?<![\w.-])" + _SEP.join(re.escape(p) for p in old.split("/")) + r"(?![\w-])")


def git(*args):
    return subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True, check=True).stdout


def ls_files(*paths):
    return sorted(p for p in git("ls-files", "-z", "--", *paths).decode("utf-8", "surrogateescape").split("\0") if p)


def ignored(rel):
    return subprocess.run(["git", "-C", str(ROOT), "check-ignore", "-q", "--", rel]).returncode == 0


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


@pytest.mark.parametrize("old", sorted(MOVES))
def test_index_holds_the_new_paths_only(old):
    new, names = MOVES[old]
    assert ls_files(old) == [], "still tracked at the old path"
    tracked = set(ls_files(new))
    assert [n for n in names if "%s/%s" % (new, n) not in tracked] == [], "moved file missing at the new path"


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
