"""tests/wiki_check.py: the GitHub-wiki link and asset checker, proven on a fixture wiki.

The project wiki is a GitHub wiki repository prepared in the git-ignored github-wiki/ folder; nothing
here reads it. A clean mini-wiki passes; each seeded breakage (case mismatches, missing images and
pages, .md suffixes, bad anchors, missing alt text, escapes, sidebar gaps, bad names, instruction-file
names, checksums, Mermaid titles) raises exactly its rule; links in code spans and fences are ignored.

Run: uv run --with pytest pytest -q tests/test_wiki_check.py
"""
import hashlib
import importlib.util
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("wiki_check", HERE / "wiki_check.py")
wc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(wc)

HOME = """<!-- markdownlint-disable MD033 MD041 -->
<p align="center"><img src="assets/logo.png" alt="Logo" width="96"></p>

# Fixture wiki

See [Page one](Page-One), [its section](Page-One#a-section), [[the same section|Page-One#a-section]],
[[Page One]], [this page](#fixture-wiki), [a local id](#top) and [the web](https://example.com/x).
<a id="top"></a>

| Page | Link |
|---|---|
| one | [Page one](Page-One) |

`[in a span](Missing)`, `[[In a span]]` and `<img src="gone.png">` are code.

```text
[in a fence](Missing) [[Missing too]] ![](nope.png) <img src="gone.png">
```

```mermaid
accTitle: Fixture
accDescr: Two boxes
flowchart LR
  a --> b
```
"""
PAGE_ONE = "# Page one\n\n## A section\n\nBack to [[Home]]; the licence text: [licence](assets/LICENCE.txt).\n"
SIDEBAR = '<img src="assets/logo.png" alt="Logo" width="48">\n\n- [[Home]]\n- [[Page one|Page-One]]\n'
FOOTER = "Fixture footer · [[Home]] · [licence](assets/LICENCE.txt)\n"


def write_sums(root):
    assets = root / "assets"
    lines = ["%s  %s" % (hashlib.sha256(p.read_bytes()).hexdigest(), p.name)
             for p in sorted(assets.iterdir()) if p.is_file() and p.name != "SHA256SUMS"]
    (assets / "SHA256SUMS").write_text("\n".join(lines) + "\n", encoding="utf-8")


@pytest.fixture
def wiki(tmp_path):
    root = tmp_path / "github-wiki"
    (root / "assets").mkdir(parents=True)
    (root / "Home.md").write_text(HOME, encoding="utf-8")
    (root / "Page-One.md").write_text(PAGE_ONE, encoding="utf-8")
    (root / "_Sidebar.md").write_text(SIDEBAR, encoding="utf-8")
    (root / "_Footer.md").write_text(FOOTER, encoding="utf-8")
    (root / "assets" / "logo.png").write_bytes(b"\x89PNG\r\n\x1a\nfixture")
    (root / "assets" / "LICENCE.txt").write_text("licence text\n", encoding="utf-8")
    write_sums(root)
    return root


def rules(root):
    return {rule for _where, rule, _msg in wc.check(root)}


def append(root, name, text):
    p = root / name
    p.write_text(p.read_text(encoding="utf-8") + text, encoding="utf-8")


def test_the_clean_fixture_passes(wiki):
    assert wc.check(wiki) == []


def _add_svg(root):
    (root / "assets" / "pic.svg").write_text("<svg/>", encoding="utf-8")
    append(root, "Home.md", "\n![Pic](assets/pic.svg)\n")


def _add_unused(root):
    (root / "assets" / "extra.png").write_bytes(b"\x89PNG extra")


SEEDS = {
    "page link in the wrong case": (lambda r: append(r, "Home.md", "\n[x](page-one)\n"), {"case"}),
    "image in the wrong case": (lambda r: append(r, "Home.md", "\n![Logo](assets/Logo.png)\n"), {"case"}),
    "html image in the wrong case": (lambda r: append(r, "Home.md", '\n<img src="assets/LOGO.png" alt="L">\n'),
                                     {"case"}),
    "wikilink in the wrong case": (lambda r: append(r, "Home.md", "\n[[x|page-one]]\n"), {"case"}),
    "missing image": (lambda r: append(r, "Home.md", "\n![Gone](assets/gone.png)\n"), {"missing-file"}),
    "missing html image": (lambda r: append(r, "Page-One.md", '\n<img src="assets/gone.jpg" alt="G">\n'),
                           {"missing-file"}),
    "missing file link": (lambda r: append(r, "Home.md", "\n[t](assets/gone.txt)\n"), {"missing-file"}),
    ".md suffix": (lambda r: append(r, "Home.md", "\n[x](Page-One.md)\n"), {"md-suffix"}),
    "missing page": (lambda r: append(r, "Home.md", "\n[x](No-Such-Page)\n"), {"missing-page"}),
    "wikilink to a missing page": (lambda r: append(r, "Home.md", "\n[[No Such Page]]\n"), {"missing-page"}),
    "wikilink in the docs' order": (lambda r: append(r, "Home.md", "\n[[Page-One|Some text]]\n"),
                                    {"missing-page"}),
    "bad anchor": (lambda r: append(r, "Home.md", "\n[x](Page-One#nope)\n"), {"anchor"}),
    "bad wikilink anchor": (lambda r: append(r, "Home.md", "\n[[x|Page-One#nope]]\n"), {"anchor"}),
    "bad local anchor": (lambda r: append(r, "Home.md", "\n[x](#nope)\n"), {"anchor"}),
    "image without alt": (lambda r: append(r, "Home.md", "\n![](assets/logo.png)\n"), {"alt"}),
    "html image without alt": (lambda r: append(r, "Home.md", '\n<img src="assets/logo.png">\n'), {"alt"}),
    "link out of the wiki": (lambda r: append(r, "Home.md", "\n[x](../README.md)\n"), {"escape"}),
    "root-relative link": (lambda r: append(r, "Home.md", "\n[x](/owner/repo/wiki/Page-One)\n"),
                           {"root-relative"}),
    "svg image": (_add_svg, {"image-format"}),
    "page below the top level": (lambda r: (r / "sub").mkdir() or (r / "sub" / "Deep.md").write_text("# D\n"),
                                 {"nested"}),
    "AGENTS.md in another case": (lambda r: (r / "Agents.md").write_text("# A\n") and append(r, "_Sidebar.md",
                                                                                              "- [[Agents]]\n"),
                                  {"instruction-file"}),
    "claude.md among the assets": (lambda r: (r / "assets" / "claude.md").write_text("x\n"),
                                   {"instruction-file", "nested"}),
    "page name with a space": (lambda r: (r / "Bad Name.md").write_text("# B\n"), {"page-name", "sidebar"}),
    "page missing from the sidebar": (lambda r: (r / "Orphan.md").write_text("# Orphan\n"), {"sidebar"}),
    "relative page link in the sidebar": (
        lambda r: (r / "_Sidebar.md").write_text(SIDEBAR.replace("[[Page one|Page-One]]", "[Page one](Page-One)")),
        {"sidebar-link"}),
    "relative page link in the footer": (lambda r: append(r, "_Footer.md", "[Home](Home)\n"), {"sidebar-link"}),
    "unused asset": (_add_unused, {"unused-asset"}),
    "wikilink pipe in a table": (lambda r: append(r, "Home.md", "| two | [[x|Page-One]] |\n"),
                                 {"wikilink-in-table"}),
    "mermaid without a title": (lambda r: append(r, "Home.md", "\n```mermaid\nflowchart LR\n  a --> b\n```\n"),
                                {"mermaid"}),
    "missing footer": (lambda r: (r / "_Footer.md").unlink(), {"entry"}),
}


@pytest.mark.parametrize("name", sorted(SEEDS))
def test_seeded_breakage_raises_its_rule(wiki, name):
    seed, expected = SEEDS[name]
    seed(wiki)
    write_sums(wiki)
    assert rules(wiki) == expected, wc.check(wiki)


def test_a_changed_asset_fails_its_checksum(wiki):
    (wiki / "assets" / "logo.png").write_bytes(b"\x89PNG changed")
    assert rules(wiki) == {"checksum"}


def test_an_unlisted_asset_fails_the_checksum_list(wiki):
    (wiki / "assets" / "new.png").write_bytes(b"\x89PNG new")
    append(wiki, "Home.md", "\n![New](assets/new.png)\n")
    assert rules(wiki) == {"checksum"}


def test_slug_follows_github():
    assert wc.slug("Side effect of the instructor deny rule") == "side-effect-of-the-instructor-deny-rule"
    assert wc.slug("`RESET_TO_MAIN.sh`: back to \"only main\", safely") == "reset_to_mainsh-back-to-only-main-safely"
    assert wc.slug("Codex (planned)") == "codex-planned"
    assert wc.slug("Layers, depth and fan-out") == "layers-depth-and-fan-out"


def test_repeated_headings_get_numbered_anchors():
    assert {"notes", "notes-1", "notes-2"} <= wc.anchors("# Notes\n## Notes\n### Notes\n")


def test_cli_skips_an_absent_folder(tmp_path, capsys):
    assert wc.main([str(tmp_path / "github-wiki")]) == 0
    assert "skip" in capsys.readouterr().out


def test_cli_exit_codes(wiki, tmp_path, capsys):
    assert wc.main([str(wiki)]) == 0
    append(wiki, "Home.md", "\n[x](page-one)\n")
    assert wc.main([str(wiki)]) == 1
    out = capsys.readouterr().out
    assert "Home.md:" in out and ": case: " in out
    (tmp_path / "file").write_text("x")
    assert wc.main([str(tmp_path / "file")]) == 2


def test_default_folder_is_github_wiki_at_the_root():
    assert wc.DEFAULT_WIKI == HERE.parent / "github-wiki"
