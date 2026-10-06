#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.9"
# ///
"""Link and asset checker for a GitHub wiki checkout (stdlib only).

The project wiki is GitHub's wiki for this repository (the separate <repo>.wiki.git). Its pages are
prepared in github-wiki/ at the repository root, a git-ignored repository of its own; this repository
tracks none of them. The checker reads such a folder and reports, as `file:line: rule: message`:

  absent           the folder does not exist: one skip line, exit 0 (nothing to check)
  entry            Home.md, _Sidebar.md or _Footer.md is missing
  nested           a page (*.md) below the top level: GitHub flattens page names, keep pages flat
  page-name        a page name with a space or a character GitHub refuses (\\ / : * ? " < > |)
  instruction-file a file named AGENTS.md, CLAUDE.md or CLAUDE.local.md in any case: harnesses load
                   it as instructions when a session runs in or below the folder (case-insensitive APFS)
  md-suffix        a page link ending in .md: GitHub serves Page.md as the raw source, not the page
  missing-page     a page link (Markdown `[text](Page-Name)` or `[[text|Page-Name]]`) names no page
  missing-file     an image or file link names no file in the wiki repository
  case             a link differs in case from the page or file it names (GitHub looks pages up
                   case-insensitively but serves files case-sensitively; exact case is required)
  anchor           a #fragment names no heading (GitHub's slug rule) or HTML id of the target page
  escape           a relative link leaves the wiki folder
  root-relative    a link starting with / depends on the owner and repository in the hosting URL
  alt              an image without alt text
  image-format     an image GitHub wikis do not list (PNG, JPEG, GIF)
  sidebar          a page the sidebar does not link
  sidebar-link     a relative Markdown page link in _Sidebar.md or _Footer.md: they render on every page,
                   so page links there use [[text|Page-Name]], which GitHub turns into absolute links
  wikilink-in-table a [[text|Page]] link with a pipe on a table row: the pipe splits the cell
  unused-asset     a file in the wiki no page links (SHA256SUMS aside)
  checksum         assets/SHA256SUMS (`shasum -a 256` format) disagrees with a file or misses one
  mermaid          a ```mermaid block without accTitle and accDescr

GitHub-wiki link rules, as checked on 2026-10-06 against docs.github.com and live wiki pages:
`[[Link Text|Page-Name]]` (text first) renders as an absolute link to /<owner>/<repo>/wiki/Page-Name
(#anchor kept); `[text](Page-Name)` stays relative, which resolves on /wiki/<Page> URLs, and on Home,
served at the bare /wiki URL, GitHub rewrites it to wiki/Page-Name; /wiki/<path> of a non-page file
redirects to raw.githubusercontent.com/wiki/<owner>/<repo>/<path>. Links inside code spans and fenced
blocks are not links. External links (a scheme or //) are not fetched; an absolute URL into a wiki
(https://raw.githubusercontent.com/wiki/<owner>/<repo>/<path> or https://github.com/<owner>/<repo>/wiki/<path>)
is checked as the relative <path> it names, whatever the owner and repository.

Run: uv run tests/wiki_check.py [WIKI_DIR]     (default: github-wiki/ at the repository root)
Exit: 0 clean or skipped, 1 problems found, 2 WIKI_DIR is not a directory.
"""
import hashlib
import re
import sys
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_WIKI = ROOT / "github-wiki"

ENTRY = ("Home.md", "_Sidebar.md", "_Footer.md")
CHROME = {"_Sidebar.md", "_Footer.md"}
INSTRUCTION_FILES = {"AGENTS.MD", "CLAUDE.MD", "CLAUDE.LOCAL.MD"}
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".gif"}
LOOKS_LIKE_IMAGE = IMAGE_EXT | {".svg", ".webp", ".bmp", ".tif", ".tiff", ".avif", ".heic"}
SUMS = PurePosixPath("assets/SHA256SUMS")
BAD_NAME = re.compile(r'[\\/:*?"<>|\s]')

_FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})")
_CODE_SPAN = re.compile(r"(?<!`)(`+)(?!`)(.+?)(?<!`)\1(?!`)")
_TITLE = r"""(?:\s+(?:"[^"]*"|'[^']*'|\([^)]*\)))?"""
_IMAGE = re.compile(r"!\[([^\]]*)\]\(\s*(?:<([^>]*)>|([^)\s]+))" + _TITLE + r"\s*\)")
_MD_LINK = re.compile(r"\[([^\]]*)\]\(\s*(?:<([^>]*)>|([^)\s]+))" + _TITLE + r"\s*\)")
_REF_DEF = re.compile(r"^ {0,3}\[[^\]]+\]:\s*(?:<([^>]*)>|(\S+))")
_TABLE_DELIM = re.compile(r"^\s*\|?\s*:?-+:?\s*(?:\|\s*:?-+:?\s*)*\|?\s*$")
_WIKILINK = re.compile(r"\[\[([^\[\]]+)\]\]")
_HTML_TAG = re.compile(r"<(img|a)\b([^>]*)>", re.I)
_HTML_ID = re.compile(r"""<[a-z][^>]*\s(?:id|name)\s*=\s*["']([^"']+)["']""", re.I)
_ATTR = re.compile(r"""(\w+)\s*=\s*("([^"]*)"|'([^']*)')""")
_HEADING = re.compile(r"^ {0,3}(#{1,6})\s+(.*?)\s*#*\s*$")
_EXTERNAL = re.compile(r"^(?:[a-z][a-z0-9+.-]*:|//)", re.I)
# an absolute URL into a GitHub wiki: checked like the relative path it names
_WIKI_URL = re.compile(r"^https://(?:raw\.githubusercontent\.com/wiki/[^/]+/[^/]+|github\.com/[^/]+/[^/]+/wiki)/([^?]+)$")


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
    """Every #fragment a page answers: heading slugs (repeats get -1, -2, ...) and HTML id/name values."""
    seen, out = {}, set()
    for _n, line in prose_lines(text):
        out.update(_HTML_ID.findall(line))
        m = _HEADING.match(line)
        if not m:
            continue
        base = slug(m.group(2))
        k = seen.get(base, 0)
        seen[base] = k + 1
        out.add(base if k == 0 else "%s-%d" % (base, k))
    return out


def refs(text):
    """(line, kind, target, alt, form) for every link: kind 'link' or 'image'; form 'md', 'html' or 'wiki'.
    alt is the image's alt text (None when absent)."""
    found = []
    raw = dict(enumerate(text.splitlines(), 1))
    for n, line in prose_lines(text):
        for m in _WIKILINK.finditer(line):
            parts = [p.strip() for p in m.group(1).split("|")]
            first = parts[0]
            if PurePosixPath(first.partition("#")[0]).suffix.lower() in LOOKS_LIKE_IMAGE:
                opts = ",".join(parts[1:])
                alt = re.search(r"(?:^|,)\s*alt=([^,]*)", opts)
                found.append((n, "image", first, alt.group(1).strip() if alt else None, "wiki"))
            else:
                found.append((n, "link", parts[1] if len(parts) > 1 else first, None, "wiki"))
        rest = _WIKILINK.sub(lambda w: " " * len(w.group(0)), line)
        for m in _IMAGE.finditer(rest):
            found.append((n, "image", m.group(2) if m.group(2) is not None else m.group(3), m.group(1), "md"))
        rest = _IMAGE.sub(lambda i: "x" * len(i.group(0)), rest)      # a linked image keeps its outer link
        for m in _MD_LINK.finditer(rest):
            found.append((n, "link", m.group(2) if m.group(2) is not None else m.group(3), None, "md"))
        d = _REF_DEF.match(rest)
        if d:                                                        # [label]: target
            found.append((n, "link", d.group(1) if d.group(1) is not None else d.group(2), None, "md"))
        # attributes are read from the raw line: the blanking of code spans must not hide an alt
        for m in _HTML_TAG.finditer(raw[n]):
            if m.start() < len(line) and line[m.start()] != "<":
                continue                                  # the tag sits inside a code span
            attrs = {a.group(1).lower(): a.group(3) if a.group(3) is not None else a.group(4)
                     for a in _ATTR.finditer(m.group(2))}
            if m.group(1).lower() == "img":
                found.append((n, "image", attrs.get("src", ""), attrs.get("alt"), "html"))
            elif "href" in attrs:
                found.append((n, "link", attrs["href"], None, "html"))
    return found


class Wiki:
    def __init__(self, root):
        self.root = Path(root)
        self.files = {}                               # posix path relative to root -> Path
        for p in sorted(self.root.rglob("*")):
            rel = p.relative_to(self.root)
            if rel.parts[0] == ".git" or not p.is_file():
                continue
            self.files[rel.as_posix()] = p
        self.pages = {PurePosixPath(k).stem: p for k, p in self.files.items()
                      if "/" not in k and k.endswith(".md")}
        self._anchors = {}

    def anchors_of(self, name):
        if name not in self._anchors:
            self._anchors[name] = anchors(self.pages[name].read_text(encoding="utf-8"))
        return self._anchors[name]


def _case_twin(name, names):
    low = name.lower()
    return next((k for k in names if k.lower() == low), None)


def _norm(path):
    """Normalise a relative POSIX path; None when it climbs above the wiki root."""
    out = []
    for part in PurePosixPath(path).parts:
        if part in ("", "."):
            continue
        if part == "..":
            if not out:
                return None
            out.pop()
        else:
            out.append(part)
    return "/".join(out)


def _check_ref(wiki, page, n, kind, target, alt, form, used, linked):
    where = (page, n)
    bad = []
    if kind == "image" and not (alt or "").strip():
        bad.append((where, "alt", "image without alt text: %s" % target))
    absolute = _WIKI_URL.match(target or "")
    if absolute:
        target = absolute.group(1)
    if not target or _EXTERNAL.match(target):
        return bad
    if target.startswith("/"):
        return bad + [(where, "root-relative", "%s depends on the hosting URL; use a relative link" % target)]
    path, _, frag = target.partition("#")
    if form == "wiki" and kind == "link":
        path = path.strip().replace(" ", "-")
    if not path:                                      # a fragment of this page
        if frag and frag not in wiki.anchors_of(PurePosixPath(page).stem):
            bad.append((where, "anchor", "no heading or id for #%s in %s" % (frag, page)))
        return bad
    norm = _norm(path)
    if norm is None:
        return bad + [(where, "escape", "link leaves the wiki: %s" % target)]
    suffix = PurePosixPath(norm).suffix.lower()
    if kind == "link" and "/" not in norm and suffix == ".md":
        stem = PurePosixPath(norm).stem
        hint = " (use %s)" % stem if stem in wiki.pages else ""
        return bad + [(where, "md-suffix", "%s links to the raw page source%s" % (target, hint))]
    is_page = kind == "link" and "/" not in norm and (norm in wiki.pages or not suffix
                                                       or _case_twin(norm, wiki.pages) is not None)
    if is_page:
        if norm not in wiki.pages:
            twin = _case_twin(norm, wiki.pages)
            if twin:
                return bad + [(where, "case", "%s differs in case from the page %s" % (target, twin))]
            return bad + [(where, "missing-page", "no page named %s" % norm)]
        linked.add(norm)
        if frag and frag not in wiki.anchors_of(norm):
            bad.append((where, "anchor", "no heading or id for #%s in %s.md" % (frag, norm)))
        return bad
    if norm not in wiki.files:
        twin = _case_twin(norm, wiki.files)
        if twin:
            return bad + [(where, "case", "%s differs in case from the file %s" % (target, twin))]
        return bad + [(where, "missing-file", "no file %s in the wiki" % norm)]
    used.add(norm)
    if kind == "image" and suffix not in IMAGE_EXT:
        bad.append((where, "image-format", "%s: GitHub wikis list PNG, JPEG and GIF" % target))
    return bad


def check(root):
    """Every problem of the wiki at root, as ((file, line), rule, message); line 0 = the whole file."""
    wiki = Wiki(root)
    bad = []
    for name in ENTRY:
        if name not in wiki.files:
            bad.append(((name, 0), "entry", "missing %s" % name))
    for rel in wiki.files:
        p = PurePosixPath(rel)
        if p.name.upper() in INSTRUCTION_FILES:
            bad.append(((rel, 0), "instruction-file", "%s reads as an instruction file" % rel))
        if p.suffix == ".md" and "/" in rel:
            bad.append(((rel, 0), "nested", "page below the top level: %s" % rel))
        elif p.suffix == ".md" and BAD_NAME.search(p.stem):
            bad.append(((rel, 0), "page-name", "page name with a space or a refused character: %s" % rel))
    used, sidebar_links = set(), set()
    for name in sorted(wiki.pages):
        page = name + ".md"
        text = wiki.pages[name].read_text(encoding="utf-8")
        linked = set()
        for n, kind, target, alt, form in refs(text):
            bad += _check_ref(wiki, page, n, kind, target, alt, form, used, linked)
            if (page in CHROME and kind == "link" and form != "wiki" and target
                    and not _EXTERNAL.match(target) and not target.startswith(("#", "/"))
                    and "/" not in target.partition("#")[0]):
                bad.append(((page, n), "sidebar-link",
                            "use [[text|%s]]: %s renders on every page" % (target, page)))
        if page == "_Sidebar.md":
            sidebar_links = linked
        in_table = False                          # a GFM table runs from its delimiter row to a blank line
        for n, line in prose_lines(text):
            if not line.strip():
                in_table = False
            elif "|" in line and _TABLE_DELIM.match(line):
                in_table = True
            if (in_table or line.lstrip().startswith("|")) and any("|" in w for w in _WIKILINK.findall(line)):
                bad.append(((page, n), "wikilink-in-table", "a [[text|Page]] pipe splits the table cell"))
        for m in re.finditer(r"^```mermaid\n(.*?)^```", text, re.M | re.S):
            if "accTitle:" not in m.group(1) or "accDescr:" not in m.group(1):
                line = text.count("\n", 0, m.start()) + 1
                bad.append(((page, line), "mermaid", "Mermaid block without accTitle and accDescr"))
    if "_Sidebar.md" in wiki.files:
        for name in sorted(wiki.pages):
            if name + ".md" not in CHROME and name not in sidebar_links:
                bad.append((("_Sidebar.md", 0), "sidebar", "the sidebar does not link %s" % name))
    sums = SUMS.as_posix()
    for rel in wiki.files:
        if not rel.endswith(".md") and rel != sums and rel not in used:
            bad.append(((rel, 0), "unused-asset", "no page links %s" % rel))
    if sums in wiki.files:
        bad += _check_sums(wiki)
    return bad


def _check_sums(wiki):
    bad, listed = [], set()
    base = SUMS.parent
    for n, line in enumerate(wiki.files[SUMS.as_posix()].read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        m = re.match(r"^([0-9a-f]{64}) [ *](.+)$", line)
        if not m:
            bad.append(((SUMS.as_posix(), n), "checksum", "not a `shasum -a 256` line"))
            continue
        rel = (base / m.group(2)).as_posix()
        listed.add(rel)
        if rel not in wiki.files:
            bad.append(((SUMS.as_posix(), n), "checksum", "lists a missing file %s" % m.group(2)))
        elif hashlib.sha256(wiki.files[rel].read_bytes()).hexdigest() != m.group(1):
            bad.append(((SUMS.as_posix(), n), "checksum", "%s does not match its SHA-256" % m.group(2)))
    for rel in wiki.files:
        if rel.startswith(base.as_posix() + "/") and rel != SUMS.as_posix() and rel not in listed:
            bad.append(((SUMS.as_posix(), 0), "checksum", "%s is not listed" % rel))
    return bad


def main(argv=None):
    args = sys.argv[1:] if argv is None else argv
    if len(args) > 1 or (args and args[0] in ("-h", "--help")):
        print("usage: wiki_check.py [WIKI_DIR]  (default: %s)" % DEFAULT_WIKI, file=sys.stderr)
        return 2
    root = Path(args[0]) if args else DEFAULT_WIKI
    if not root.exists():
        print("wiki_check: skip: %s does not exist" % root)
        return 0
    if not root.is_dir():
        print("wiki_check: %s is not a directory" % root, file=sys.stderr)
        return 2
    bad = check(root)
    for (rel, n), rule, msg in sorted(bad):
        print("%s:%d: %s: %s" % (rel, n, rule, msg))
    pages = len(Wiki(root).pages)
    print("wiki_check: %s: %d pages, %d problems" % (root, pages, len(bad)))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
