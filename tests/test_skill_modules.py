"""Skill layout: hubs, modules, references/ and the skillOverrides block in dot-claude/settings.json.

A hub is a SKILL.md with a `## Modules` section; its modules are the backticked skill names in the
first column of that section's table. Caps: every SKILL.md <= 500 lines, a hub <= 80, a module <= 150
with a description <= 100 characters. Detail lives in references/<topic>.md, which must exist where a
skill names it. Every skillOverrides key is a shipped skill or one of Claude Code's bundled skills the
stack hides (EXTERNAL); every "name-only" skill is named by another skill or an agent body, since the
listing no longer carries its description.
"""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKILLS = ROOT / "dot-claude" / "skills"
AGENTS = ROOT / "dot-claude" / "agents"
SETTINGS = ROOT / "dot-claude" / "settings.json"

SKILL_MAX_LINES = 500
HUB_MAX_LINES = 80
MODULE_MAX_LINES = 150
MODULE_DESC_MAX = 100
# Claude Code's bundled skills the stack hides from the model (user-run commands); not shipped here.
EXTERNAL = {"code-review", "security-review", "simplify", "fewer-permission-prompts", "keybindings-help",
            "init"}
REF_RE = re.compile(r"(?<![\w/.-])((?:\.\./[\w-]+/)?references/[\w./-]+?\.md)\b")


def shipped():
    return {p.parent.name: p for p in sorted(SKILLS.glob("*/SKILL.md"))}


def overrides():
    so = json.loads(SETTINGS.read_text()).get("skillOverrides") or {}
    assert isinstance(so, dict), "settings.json skillOverrides must be an object"
    return so


def split(text):
    """(frontmatter, body) of a SKILL.md."""
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) == 3:
            return parts[1], parts[2]
    return "", text


def description(text):
    m = re.search(r"(?m)^description:\s*(.*)$", split(text)[0])
    v = m.group(1).strip() if m else ""
    return v[1:-1] if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'" else v


def module_table(text):
    """Backticked names in the first column of the `## Modules` section's table rows."""
    names, inside = [], False
    for line in split(text)[1].splitlines():
        if line.startswith("#"):
            inside = line.lstrip("#").strip().lower().startswith("modules")
            continue
        if inside and line.startswith("|"):
            first = line.strip("|").split("|", 1)[0]
            names += re.findall(r"`([a-z0-9-]+)`", first)
    return names


def hubs_and_modules():
    sk = shipped()
    hubs, modules = {}, {}
    for name, p in sk.items():
        mods = module_table(p.read_text(encoding="utf-8"))
        if mods:
            hubs[name] = mods
            for m in mods:
                modules.setdefault(m, name)
    return hubs, modules


def test_skill_md_line_cap():
    over = ["%s (%d lines)" % (n, len(p.read_text(encoding="utf-8").splitlines()))
            for n, p in shipped().items() if len(p.read_text(encoding="utf-8").splitlines()) > SKILL_MAX_LINES]
    assert not over, "SKILL.md over %d lines (move detail to references/): %s" % (SKILL_MAX_LINES, over)


def test_hub_line_cap():
    sk = shipped()
    hubs, _ = hubs_and_modules()
    over = ["%s (%d lines)" % (h, len(sk[h].read_text(encoding="utf-8").splitlines()))
            for h in hubs if len(sk[h].read_text(encoding="utf-8").splitlines()) > HUB_MAX_LINES]
    assert not over, "hub SKILL.md over %d lines: %s" % (HUB_MAX_LINES, over)


def test_modules_exist_and_fit():
    sk = shipped()
    _, modules = hubs_and_modules()
    missing = sorted("%s (hub %s)" % (m, h) for m, h in modules.items() if m not in sk)
    assert not missing, "modules named in a hub's Modules table but not shipped: %s" % missing
    long_ = []
    for m in sorted(modules):
        text = sk[m].read_text(encoding="utf-8")
        n, d = len(text.splitlines()), description(text)
        if n > MODULE_MAX_LINES:
            long_.append("%s: %d lines > %d" % (m, n, MODULE_MAX_LINES))
        if len(d) > MODULE_DESC_MAX:
            long_.append("%s: description %d chars > %d" % (m, len(d), MODULE_DESC_MAX))
    assert not long_, "modules over their caps: %s" % long_


def test_referenced_reference_files_exist():
    """A references/ path resolves from the naming skill's directory, or from the directory of a
    skill named in backticks on the same line (`rust-engineering` `references/performance.md`)."""
    sk = shipped()
    missing = []
    for p in sk.values():
        d = p.parent
        for f in [p] + sorted((d / "references").glob("**/*.md")):
            for line in f.read_text(encoding="utf-8").splitlines():
                for ref in REF_RE.findall(line):
                    dirs = [d] + [sk[n].parent for n in re.findall(r"`([a-z0-9-]+)`", line) if n in sk]
                    if not any((x / ref).resolve().is_file() for x in dirs):
                        missing.append("%s → %s" % (f.relative_to(SKILLS).as_posix(), ref))
    assert not missing, "references named but missing: %s" % sorted(set(missing))


def test_skill_overrides_keys_are_shipped_or_external():
    so, sk = overrides(), shipped()
    unknown = sorted(k for k in so if k not in sk and k not in EXTERNAL)
    assert not unknown, ("%d skillOverrides keys have no dot-claude/skills/<name>/SKILL.md (not yet "
                         "written, renamed, or a typo): %s" % (len(unknown), ", ".join(unknown)))
    shadow = sorted(k for k in EXTERNAL if k in sk)
    assert not shadow, "EXTERNAL names a shipped skill: %s" % shadow


def test_name_only_skills_are_named_somewhere():
    so, sk = overrides(), shipped()
    texts = {"agents/" + p.name: p.read_text(encoding="utf-8") for p in sorted(AGENTS.glob("*.md"))}
    texts.update({"skills/" + n: p.read_text(encoding="utf-8") for n, p in sk.items()})
    orphans = []
    for name in sorted(k for k, v in so.items() if v == "name-only" and k in sk):
        rx = re.compile(r"(?<![\w-])%s(?![\w-])" % re.escape(name))
        if not any(rx.search(t) for where, t in texts.items() if where != "skills/" + name):
            orphans.append(name)
    assert not orphans, ("name-only skills that no hub, other skill or agent body names (the listing "
                         "shows no description, so nothing points an agent at them): %s" % orphans)


def test_module_table_parser():
    text = ("---\nname: h\ndescription: Load x.\n---\n# H\n\n## Modules\n| module | when |\n|---|---|\n"
            "| `a-b` | uses `not-me` |\n| `c` | z |\n\n## Other\n| `d` | e |\n")
    assert module_table(text) == ["a-b", "c"]
    assert REF_RE.findall("see `references/x-y.md` and ../rust-engineering/references/z.md.") == [
        "references/x-y.md", "../rust-engineering/references/z.md"]
