"""The wiki in docs/wiki/ stays consistent: every relative link and image resolves inside the wiki, every
#anchor names a heading of its target page (GitHub's slug rule), every image carries alt text, every Mermaid
block carries an accTitle, the sidebar lists every page, and every file in docs/wiki/assets/ is used.

Links that leave docs/wiki/ are refused so the pages can be copied into the GitHub wiki unchanged; repository
files are named in code spans instead. Links inside code spans and fenced blocks are not links.

Run: uv run --with pytest pytest -q tests/test_wiki_links.py
"""
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
WIKI = ROOT / "docs" / "wiki"
SPECIAL = {"_Sidebar.md", "_Footer.md", "README.md"}

_FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})")
_CODE_SPAN = re.compile(r"(?<!`)(`+)(?!`)(.+?)(?<!`)\1(?!`)")
_MD_LINK = re.compile(r"(!?)\[([^\]]*)\]\(\s*<?([^)\s>]+)>?(?:\s+\"[^\"]*\")?\s*\)")
_HTML_TAG = re.compile(r"<(img|a)\b([^>]*)>", re.I)
_ATTR = re.compile(r"""(\w+)\s*=\s*("([^"]*)"|'([^']*)')""")
_HEADING = re.compile(r"^ {0,3}(#{1,6})\s+(.*?)\s*#*\s*$")


def pages():
    return sorted(WIKI.glob("*.md"))


def prose_lines(text):
    """(line number, text) of the lines outside fenced code blocks, code spans blanked."""
    out, fence = [], None
    for n, line in enumerate(text.splitlines(), 1):
        m = _FENCE.match(line)
        if fence:
            if m and m.group(1)[0] == fence[0] and len(m.group(1)) >= len(fence):
                fence = None
            continue
        if m:
            fence = m.group(1)
            continue
        out.append((n, _CODE_SPAN.sub(lambda c: " " * len(c.group(0)), line)))
    return out


def slug(heading):
    """GitHub's heading anchor: code marks and link targets dropped, lower case, punctuation removed,
    spaces to hyphens."""
    t = re.sub(r"!?\[([^\]]*)\]\([^)]*\)", r"\1", heading).replace("`", "")
    t = re.sub(r"[^\w\- ]", "", t.strip().lower())
    return t.replace(" ", "-")


def anchors(text):
    seen, out = {}, set()
    for _n, line in prose_lines(text):
        m = _HEADING.match(line)
        if not m:
            continue
        base = slug(m.group(2))
        k = seen.get(base, 0)
        seen[base] = k + 1
        out.add(base if k == 0 else "%s-%d" % (base, k))
    return out


def refs(text):
    """(line, kind, target, alt) for every Markdown link or image and HTML <a href>/<img src>."""
    found = []
    raw = dict(enumerate(text.splitlines(), 1))
    for n, line in prose_lines(text):
        for m in _MD_LINK.finditer(line):
            found.append((n, "image" if m.group(1) else "link", m.group(3), m.group(2)))
        # attributes are read from the raw line: the blanking of code spans must not hide an alt
        for m in _HTML_TAG.finditer(raw[n]):
            attrs = {a.group(1).lower(): a.group(3) if a.group(3) is not None else a.group(4)
                     for a in _ATTR.finditer(m.group(2))}
            if m.group(1).lower() == "img":
                found.append((n, "image", attrs.get("src", ""), attrs.get("alt")))
            elif "href" in attrs:
                found.append((n, "link", attrs["href"], None))
    return found


def is_external(target):
    return bool(re.match(r"^[a-z][a-z0-9+.-]*:", target, re.I))


def problems(page):
    """Every broken reference of one page, as 'Page.md:line: why'."""
    text = page.read_text(encoding="utf-8")
    bad = []
    for n, kind, target, alt in refs(text):
        where = "%s:%d" % (page.name, n)
        if kind == "image" and not (alt or "").strip():
            bad.append("%s: image without alt text: %s" % (where, target))
        if not target or is_external(target):
            continue
        path, _, frag = target.partition("#")
        dest = (page.parent / path).resolve() if path else page.resolve()
        try:
            dest.relative_to(WIKI.resolve())
        except ValueError:
            bad.append("%s: link leaves docs/wiki: %s" % (where, target))
            continue
        if not dest.is_file():
            bad.append("%s: missing target: %s" % (where, target))
            continue
        if dest.name not in {p.name for p in dest.parent.iterdir()}:
            bad.append("%s: case differs from the file name: %s" % (where, target))
            continue
        if frag and dest.suffix == ".md" and frag not in anchors(dest.read_text(encoding="utf-8")):
            bad.append("%s: no heading for #%s in %s" % (where, frag, dest.name))
    return bad


@pytest.mark.parametrize("page", pages(), ids=lambda p: p.name)
def test_links_images_and_anchors_resolve(page):
    bad = problems(page)
    assert not bad, "\n".join(bad)


@pytest.mark.parametrize("page", pages(), ids=lambda p: p.name)
def test_mermaid_blocks_have_a_title(page):
    blocks = re.findall(r"^```mermaid\n(.*?)^```", page.read_text(encoding="utf-8"), re.M | re.S)
    assert all("accTitle:" in b and "accDescr:" in b for b in blocks), page.name


def test_the_wiki_has_its_entry_pages():
    for name in ("Home.md", "_Sidebar.md", "_Footer.md", "README.md"):
        assert (WIKI / name).is_file(), name


def test_no_page_shadows_an_instruction_file():
    # on case-insensitive APFS a page named agents.md or claude.md is AGENTS.md / CLAUDE.md, which harnesses
    # (Claude Code, Codex) load as instructions when a session starts in or below docs/wiki/
    clash = [p.name for p in WIKI.rglob("*") if p.name.upper() in {"AGENTS.MD", "CLAUDE.MD"}]
    assert not clash, "wiki file names that read as instruction files: %s" % clash


def test_sidebar_lists_every_page():
    side = {t.partition("#")[0] for _n, k, t, _a in refs((WIKI / "_Sidebar.md").read_text(encoding="utf-8"))
            if k == "link"}
    missing = [p.name for p in pages() if p.name not in SPECIAL and p.name not in side]
    assert not missing, "pages missing from _Sidebar.md: %s" % missing


def test_every_asset_is_used():
    used = set()
    for page in pages():
        for _n, _k, target, _a in refs(page.read_text(encoding="utf-8")):
            if not is_external(target):
                used.add((page.parent / target.partition("#")[0]).resolve())
    unused = [p.name for p in sorted((WIKI / "assets").iterdir()) if p.is_file() and p.resolve() not in used]
    assert not unused, "assets no page uses: %s" % unused


# The checker itself, on seeded pages: a broken link, a bad anchor, a missing alt and an escape are caught.

def test_slug_follows_github():
    assert slug("Side effect of the instructor deny rule") == "side-effect-of-the-instructor-deny-rule"
    assert slug("`RESET_TO_MAIN.sh`: back to \"only main\", safely") == "reset_to_mainsh-back-to-only-main-safely"
    assert slug("Codex (planned)") == "codex-planned"
    assert slug("Layers, depth and fan-out") == "layers-depth-and-fan-out"


def test_checker_catches_seeded_breakage(tmp_path, monkeypatch):
    wiki = tmp_path / "docs" / "wiki"
    wiki.mkdir(parents=True)
    (wiki / "A.md").write_text("# A\n\n## Real heading\n", encoding="utf-8")
    page = wiki / "B.md"
    page.write_text(
        "# B\n[ok](A.md#real-heading) [gone](Missing.md) [anchor](A.md#nope)\n"
        "![](A.md) [out](../../README.md) <img src=\"A.md\">\n"
        "`[in a span](Missing.md)`\n```\n[in a fence](Missing.md)\n```\n[web](https://example.com/x)\n"
        "[case](a.md)\n",
        encoding="utf-8")
    monkeypatch.setattr(sys.modules[__name__], "WIKI", wiki)
    bad = problems(page)
    assert any("missing target: Missing.md" in b for b in bad)
    assert any("no heading for #nope" in b for b in bad)
    assert sum("without alt text" in b for b in bad) == 2
    assert any("leaves docs/wiki" in b for b in bad)
    assert any("a.md" in b for b in bad)          # wrong case: resolves on case-insensitive APFS only
    assert len(bad) == 6, bad
