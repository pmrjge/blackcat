"""Claude skills → Codex skills and hub modules (DESIGN.md §8.3, INTERFACES.md §3). Stdlib only, Python ≥ 3.11.

    convert(src, stage_stack, ctx) -> {"listed", "modules", "budget_chars", "budget_tokens", "report", "links"}
    classify(src) -> {"listed", "modules", "core", "excluded", "excluded_modules"}

`src` is the snapshot root (holds dot-config/dot-claude/). Classification is settings.json `skillOverrides`, the
same as tests/test_skill_modules.py: `user-invocable-only`/`off` = hub module, everything else
listed; a listed skill whose override is `on` or absent keeps its full description (LISTED_CORE),
the rest (`name-only`) get a ≤ 60-character description cut from the first clause. EXCLUDED_SKILLS
(translate.py: skills about Claude Code itself) are not installed, nor is a module reachable only
from them. Listed skills go to `stage_stack/skills/<n>/`, modules to `stage_stack/skill-modules/<n>/`
(never a scanned root); `.md` files are translated (translate.py), every other file is copied byte
for byte with its exec bit. A `*`-marked hub-table row gets the module's absolute path
`<stack>/skill-modules/<m>/SKILL.md`, and the reachability check of tests/test_skill_modules.py is
re-run on the output (every module reached from a listed skill through marked rows, every named
stack skill path exists). Frontmatter keeps `name` and `description`; `argument-hint` is dropped; any
other key (`disable-model-invocation` included: its only users were the excluded skills, so no
`agents/openai.yaml` mapping is kept) is an error. A symlink or special file in the source tree is
refused (lstat), never followed. Any translate problem is a BuildError naming file:line.

Seeded-bug proofs (tests/test_convert_skills.py; tests/mutations/convert_skills.json): an excluded
skill re-included; the modules installed into skills/ (listed); a hub path left relative; the
description not shortened; the exec bit lost; a symlink followed instead of refused; a listing over
skills.max_context_tokens accepted; translate problems ignored.
"""
from __future__ import annotations

import importlib.util
import json
import math
import os
import re
import stat

__all__ = ["BuildError", "convert", "classify", "short_description", "EXCLUDED_SKILLS",
           "SKILLS_MAX_CONTEXT_TOKENS", "SHORT_DESC_MAX"]


def _load(name):
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), name + ".py")
    spec = importlib.util.spec_from_file_location("codex_config_" + name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_tr = _load("translate")


class BuildError(Exception):
    """A skill tree the converter cannot install as asked (the build stops)."""


EXCLUDED_SKILLS = _tr.EXCLUDED_SKILLS          # the one list, with its reason, lives in translate.py
SKILLS_MAX_CONTEXT_TOKENS = 6000               # the profile's skills.max_context_tokens (DESIGN §8.3)
SHORT_DESC_MAX = 60
OVERRIDE_VALUES = {"on", "name-only", "user-invocable-only", "off"}
MODULE_VALUES = {"user-invocable-only", "off"}
FRONTMATTER_KEEP = ("name", "description")
FRONTMATTER_DROP = {"argument-hint"}           # a Claude slash-command hint: no Codex counterpart
ROW_RE = re.compile(r"^(\|\s*`([a-z0-9-]+)`)\*", re.M)
_FENCE = re.compile(r"^\s*(```|~~~)")
# never written raw in a frontmatter value: C0 and C1 controls, DEL, NEL (U+0085, in \x7f-\x9f), LS,
# PS, BOM. A line break there would add YAML structure (a key, a `---` that ends the frontmatter).
_YAML_CTRL = re.compile("[\\x00-\\x1f\\x7f-\\x9f\\u2028\\u2029\\ufeff]")
# what json.dumps(ensure_ascii=False) leaves raw of those (it escapes the C0 range itself)
_YAML_RAW = re.compile("[\\x7f-\\x9f\\u2028\\u2029\\ufeff]")


# ---------------------------------------------------------------- source tree (lstat, no follow)
def _walk(root: str, rel: str = "") -> list[str]:
    """Relative paths of the regular files under root/rel, sorted; a symlink or special file → error."""
    out = []
    here = os.path.join(root, rel) if rel else root
    with os.scandir(here) as it:
        entries = sorted(it, key=lambda e: e.name)
    for e in entries:
        r = os.path.join(rel, e.name) if rel else e.name
        if e.is_symlink():
            raise BuildError("symlink in the skill source tree (refused, never followed): %s"
                             % os.path.join(root, r))
        if e.is_dir(follow_symlinks=False):
            out += _walk(root, r)
        elif e.is_file(follow_symlinks=False):
            out.append(r)
        else:
            raise BuildError("not a regular file in the skill source tree: %s" % os.path.join(root, r))
    return out


def _read(path: str) -> tuple[bytes, int]:
    """(bytes, st_mode) of a regular file, opened without following a symlink."""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    except OSError as e:
        raise BuildError("cannot read %s: %s" % (path, e)) from None
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode):
            raise BuildError("not a regular file: %s" % path)
        chunks = []
        while True:
            b = os.read(fd, 1 << 16)
            if not b:
                break
            chunks.append(b)
        return b"".join(chunks), st.st_mode
    finally:
        os.close(fd)


def _skills_dir(src: str) -> str:
    d = os.path.join(src, "dot-config", "dot-claude", "skills")
    for p in (os.path.join(src, "dot-config", "dot-claude"), d):
        try:
            st = os.lstat(p)
        except OSError as e:
            raise BuildError("no skill source: %s (%s)" % (p, e)) from None
        if stat.S_ISLNK(st.st_mode) or not stat.S_ISDIR(st.st_mode):
            raise BuildError("skill source is not a real directory (refused): %s" % p)
    return d


def _text(data: bytes, label: str) -> str:
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError as e:
        raise BuildError("%s: not UTF-8 (%s)" % (label, e)) from None


# ---------------------------------------------------------------- frontmatter
def _frontmatter(text: str, label: str) -> tuple[dict, str]:
    """({key: value}, rest after the closing ---) of a SKILL.md; one `key: value` line per key."""
    lines = text.split("\n")
    if not lines or lines[0].strip() != "---":
        raise BuildError("%s:1: no frontmatter" % label)
    try:
        end = next(i for i in range(1, len(lines)) if lines[i].strip() == "---")
    except StopIteration:
        raise BuildError("%s:1: frontmatter not closed" % label) from None
    fm = {}
    for i in range(1, end):
        line = lines[i]
        if not line.strip():
            continue
        m = re.match(r"([A-Za-z][\w-]*):\s?(.*)\Z", line)
        if not m:
            raise BuildError("%s:%d: frontmatter line not `key: value`: %s" % (label, i + 1, line))
        key, raw = m.group(1), m.group(2).strip()
        if key in fm:
            raise BuildError("%s:%d: duplicate frontmatter key %s" % (label, i + 1, key))
        fm[key] = (_unquote(raw, "%s:%d" % (label, i + 1)), i + 1)
    return fm, "\n".join(lines[end + 1:])


def _unquote(raw: str, where: str) -> str:
    if raw[:1] == '"':
        try:
            v = json.loads(raw)
        except ValueError:
            raise BuildError("%s: double-quoted value this converter cannot read: %s" % (where, raw)) from None
        if not isinstance(v, str):
            raise BuildError("%s: not a string: %s" % (where, raw))
        return v
    if raw[:1] == "'":
        if len(raw) < 2 or raw[-1] != "'":
            raise BuildError("%s: unbalanced quote: %s" % (where, raw))
        return raw[1:-1].replace("''", "'")
    if raw[:1] in ("|", ">", "[", "{", "&", "*", "!"):
        raise BuildError("%s: YAML form this converter does not map: %s" % (where, raw))
    return raw


def _yaml_scalar(v: str) -> str:
    """v as a one-line YAML scalar: plain when that is safe, else double-quoted (JSON escapes are valid
    YAML), with every control character, DEL, C1 (NEL included), LS, PS and BOM escaped as \\uXXXX."""
    if v and not _YAML_CTRL.search(v) and not re.search(
            r":\s|\s#|:\Z|\A[\s\-?:,\[\]{}#&*!|>'\"%@`]|\s\Z", v) and v.lower() not in (
            "true", "false", "yes", "no", "on", "off", "null", "~"):
        return v
    return _YAML_RAW.sub(lambda m: "\\u%04x" % ord(m.group()), json.dumps(v, ensure_ascii=False))


def short_description(desc: str) -> str:
    """The first clause of `desc`, at most SHORT_DESC_MAX characters (cut at a word, "…" added)."""
    c = re.split(r"\s+—\s+|;\s|:\s|\.\s|\s\(", desc.strip(), maxsplit=1)[0].strip().rstrip(".")
    if len(c) > SHORT_DESC_MAX:
        cut = c[:SHORT_DESC_MAX - 1]
        if " " in cut:
            cut = cut[:cut.rfind(" ")]
        c = cut.rstrip(" ,;:-—") + "…"
    return c


# ---------------------------------------------------------------- classification
def _overrides(src: str) -> dict:
    p = os.path.join(src, "dot-config", "dot-claude", "settings.json")
    data, _ = _read(p)
    try:
        so = json.loads(_text(data, p)).get("skillOverrides")
    except ValueError as e:
        raise BuildError("%s: %s" % (p, e)) from None
    if not isinstance(so, dict):
        raise BuildError("%s: skillOverrides must be an object" % p)
    bad = sorted("%s=%r" % (k, v) for k, v in so.items() if v not in OVERRIDE_VALUES)
    if bad:
        raise BuildError("%s: unknown skillOverrides values: %s" % (p, ", ".join(bad)))
    return so


def _marked_rows(text: str) -> list[str]:
    """Names in `name`* first cells of table rows (outside fenced code)."""
    out, fence = [], False
    for line in text.split("\n"):
        if _FENCE.match(line):
            fence = not fence
            continue
        if not fence:
            m = ROW_RE.match(line)
            if m:
                out.append(m.group(2))
    return out


def _reach(start, rows: dict) -> set:
    """Skills reached from `start` through marked rows (rows: {skill: [module, ...]})."""
    seen, todo = set(start), list(start)
    while todo:
        for m in rows.get(todo.pop(), ()):
            if m not in seen:
                seen.add(m)
                todo.append(m)
    return seen


def classify(src: str) -> dict:
    """{"listed", "modules", "core", "excluded", "excluded_modules"} (sorted name lists)."""
    root = _skills_dir(src)
    so = _overrides(src)
    shipped, rows = [], {}
    with os.scandir(root) as it:
        entries = sorted(it, key=lambda e: e.name)
    for e in entries:
        if e.is_symlink():
            raise BuildError("symlink in the skill source tree (refused, never followed): %s" % e.path)
        if not e.is_dir(follow_symlinks=False):
            raise BuildError("not a skill directory: %s" % e.path)
        p = os.path.join(e.path, "SKILL.md")
        data, _ = _read(p)
        shipped.append(e.name)
        rows[e.name] = _marked_rows(_text(data, p))
    excluded = [n for n in shipped if n in EXCLUDED_SKILLS]
    modules = {n for n in shipped if so.get(n) in MODULE_VALUES}
    listed = [n for n in shipped if n not in modules and n not in EXCLUDED_SKILLS]
    reached = _reach(listed, {k: v for k, v in rows.items() if k not in EXCLUDED_SKILLS})
    via_excluded = _reach(excluded, rows)
    excluded_modules = sorted(m for m in modules if m not in reached and m in via_excluded)
    lost = sorted(m for m in modules if m not in reached and m not in via_excluded)
    if lost:
        raise BuildError("hub modules no listed skill reaches through a `name`* table row: %s" % ", ".join(lost))
    stray = sorted({"%s (row in %s)" % (m, k) for k, v in rows.items() if k not in EXCLUDED_SKILLS
                    for m in v if m not in modules})
    if stray:
        raise BuildError("rows marked * for skills that are not hub modules: %s" % ", ".join(stray))
    mods = sorted(m for m in modules if m not in excluded_modules and m not in EXCLUDED_SKILLS)
    core = sorted(n for n in listed if so.get(n, "on") == "on")
    return {"listed": listed, "modules": mods, "core": core, "excluded": excluded,
            "excluded_modules": excluded_modules}


# ---------------------------------------------------------------- output
def _mkdir_new(path: str):
    try:
        st = os.lstat(path)
    except FileNotFoundError:
        os.makedirs(path, mode=0o755)
        return
    if stat.S_ISLNK(st.st_mode) or not stat.S_ISDIR(st.st_mode) or os.listdir(path):
        raise BuildError("stage target exists and is not an empty directory: %s" % path)


def _write(path: str, data: bytes, mode: int):
    os.makedirs(os.path.dirname(path), mode=0o755, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, mode)
    try:
        os.fchmod(fd, mode)
        view = memoryview(data)
        while view:
            view = view[os.write(fd, view):]
    finally:
        os.close(fd)


def _skill_md(text: str, name: str, label: str, short: bool) -> tuple[str, str]:
    """(SKILL.md with the Codex frontmatter, final description) from the translated text."""
    fm, rest = _frontmatter(text, label)
    unknown = sorted(k for k in fm if k not in FRONTMATTER_KEEP and k not in FRONTMATTER_DROP)
    if unknown:
        raise BuildError("%s:%d: frontmatter key(s) with no Codex mapping: %s"
                         % (label, fm[unknown[0]][1], ", ".join(unknown)))
    for k in FRONTMATTER_KEEP:
        if not fm.get(k, ("", 0))[0]:
            raise BuildError("%s: frontmatter lacks %s" % (label, k))
    if fm["name"][0] != name:
        raise BuildError("%s:%d: name %r is not the directory name %r" % (label, fm["name"][1], fm["name"][0], name))
    desc = fm["description"][0]
    if short:
        desc = short_description(desc)
    head = "---\nname: %s\ndescription: %s\n---\n" % (_yaml_scalar(name), _yaml_scalar(desc))
    return head + rest, desc


def _link_rows(text: str, stack: str, modules: set, label: str) -> str:
    """`m`* first cells → `m`* (`<stack>/skill-modules/m/SKILL.md`), outside fenced code."""
    out, fence = [], False
    for line in text.split("\n"):
        if _FENCE.match(line):
            fence = not fence
        elif not fence:
            m = ROW_RE.match(line)
            if m:
                if m.group(2) not in modules:
                    raise BuildError("%s: row marks %s as a module, but it is not one" % (label, m.group(2)))
                line = "%s* (`%s/skill-modules/%s/SKILL.md`)%s" % (
                    m.group(1), stack, m.group(2), line[m.end():])
        out.append(line)
    return "\n".join(out)


def _check_output(stage_stack: str, stack: str, listed: list, modules: list):
    """The reachability check of tests/test_skill_modules.py, on the output: every module reached from
    a listed skill through marked rows that carry its absolute path; every stack skill path that an
    installed text names exists in the stage."""
    path_re = re.compile(re.escape(stack) + r"/(skills|skill-modules)/([a-z0-9][a-z0-9-]*)")
    row_re = re.compile(r"^\|\s*`([a-z0-9-]+)`\* \(`" + re.escape(stack)
                        + r"/skill-modules/([a-z0-9-]+)/SKILL\.md`\)", re.M)
    rows, missing = {}, []
    for kind, names in (("skills", listed), ("skill-modules", modules)):
        for n in names:
            base = os.path.join(stage_stack, kind, n)
            for rel in _walk(base):
                if not rel.endswith(".md"):
                    continue
                text = _read(os.path.join(base, rel))[0].decode("utf-8")
                for m in path_re.finditer(text):
                    if not os.path.isdir(os.path.join(stage_stack, m.group(1), m.group(2))):
                        missing.append("%s/%s/%s names %s" % (kind, n, rel, m.group()))
                if rel == "SKILL.md":
                    rows[n] = [a for a, b in row_re.findall(text) if a == b]
    if missing:
        raise BuildError("stack paths with no installed target: %s" % "; ".join(sorted(set(missing))))
    reached = _reach(listed, rows)
    lost = sorted(m for m in modules if m not in reached
                  or not os.path.isfile(os.path.join(stage_stack, "skill-modules", m, "SKILL.md")))
    if lost:
        raise BuildError("modules unreachable in the output (no marked row with their absolute path "
                         "from a listed skill): %s" % ", ".join(lost))


def convert(src: str, stage_stack: str, ctx: dict) -> dict:
    """Write stage_stack/skills/ and stage_stack/skill-modules/ (module docstring)."""
    cls = classify(src)
    listed, modules = cls["listed"], cls["modules"]
    core, mods = set(cls["core"]), set(modules)
    stack = ctx["stack"]
    tctx = dict(ctx, skill_modules=frozenset(modules))
    root = _skills_dir(src)
    for kind in ("skills", "skill-modules"):
        _mkdir_new(os.path.join(stage_stack, kind))
    problems, descs = [], {}
    stats = _tr.Stats()
    counts = {"files": 0, "md_translated": 0, "copied": 0, "executable": 0, "rows_linked": 0}
    for kind, names in (("skills", listed), ("skill-modules", modules)):
        for n in names:
            src_dir = os.path.join(root, n)
            for rel in _walk(src_dir):
                label = "skills/%s/%s" % (n, rel)
                data, mode = _read(os.path.join(src_dir, rel))
                out_mode = 0o755 if mode & 0o111 else 0o644
                counts["files"] += 1
                counts["executable"] += bool(mode & 0o111)
                if rel.endswith(".md"):
                    text, probs = _tr.translate_text(_text(data, label), label, tctx, stats=stats)
                    problems += probs
                    counts["md_translated"] += 1
                    if rel == "SKILL.md" and not probs:
                        text, descs[n] = _skill_md(text, n, label, short=(kind == "skills" and n not in core))
                        before = text
                        text = _link_rows(text, stack, mods, label)
                        counts["rows_linked"] += sum(a != b for a, b in zip(before.split("\n"), text.split("\n")))
                    data = text.encode("utf-8")
                else:
                    counts["copied"] += 1
                _write(os.path.join(stage_stack, kind, n, rel), data, out_mode)
    if problems:
        raise BuildError("untranslatable skill text (%d):\n%s" % (len(problems), "\n".join(problems)))
    _check_output(stage_stack, stack, listed, modules)
    listing_root = ctx.get("skills_root")
    budget_chars = 0
    for n in listed:
        paths = ["%s/skills/%s/SKILL.md" % (stack, n)]
        if listing_root:
            paths.append("%s/%s/SKILL.md" % (listing_root, n))
        path = max(paths, key=len)
        budget_chars += len("- %s: %s (file: %s)\n" % (n, descs[n], path))
    budget_tokens = math.ceil(budget_chars / 4)
    if budget_tokens > SKILLS_MAX_CONTEXT_TOKENS:
        raise BuildError("skills listing ≈ %d tokens (%d chars) > skills.max_context_tokens %d"
                         % (budget_tokens, budget_chars, SKILLS_MAX_CONTEXT_TOKENS))
    report = dict(counts, listed=len(listed), modules=len(modules), core=len(core),
                  short=len(listed) - len(core), excluded=cls["excluded"],
                  excluded_modules=cls["excluded_modules"], references_mapped=stats["references"],
                  phrase_rewrites=stats["rewrites"], paths_rendered=stats["paths"])
    return {"listed": listed, "modules": modules, "budget_chars": budget_chars,
            "budget_tokens": budget_tokens, "report": report,
            "links": {n: "%s/skills/%s" % (stack, n) for n in listed}}
