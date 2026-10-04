"""Skill layout: hubs, modules, references/ and the skillOverrides block in dot-claude/settings.json.

A hub is a SKILL.md with a `## Modules` section; its modules are the backticked skill names in the
first column of that section's table. Caps: every SKILL.md <= 500 lines, a hub <= 80, a module <= 150
with a description <= 140 characters. Detail lives in references/<topic>.md, which must exist where a
skill names it. Every skillOverrides key is a shipped skill or one of Claude Code's bundled skills the
stack hides (EXTERNAL). Every skill but a hub is named by a hub, another skill, an agent body or the
rules (reachability: a module is found through its hub, not only through the listing).
Hidden modules (design B1x+C, 2026-10-02): a skill named in the first column of another skill's table
is a module and is "user-invocable-only" (out of the listing, Read by path) unless KEEP_LISTED names
it; its table row marks it `name`* next to one note line giving the path. No agent preloads skills.
"""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKILLS = ROOT / "dot-claude" / "skills"
AGENTS = ROOT / "dot-claude" / "agents"
SETTINGS = ROOT / "dot-claude" / "settings.json"
RULES = ROOT / "dot-claude" / "rules"

SKILL_MAX_LINES = 500
HUB_MAX_LINES = 80
MODULE_MAX_LINES = 150
# 140 holds "what it covers, when to load it, its hub or siblings" in one line; 100 forced cryptic
# text. The description is in the listing only for LISTED_CORE (below); every other listed skill is
# "name-only" and its description is read when the skill is invoked; a hidden module is picked from
# its hub's table row instead.
MODULE_DESC_MAX = 140
# Skills the stack hides from the model (user-run commands; they stay /name commands); not shipped here.
# Bundled with Claude Code: the first six and dataviz. Synced from claude.ai, keyed by the full name the
# listing shows (Claude Code 2.1.287 matches the full name, then the short one unless another command
# holds it): a plain "schedule" key would hide Claude Code's own cloud-routines /schedule instead.
EXTERNAL = {"code-review", "security-review", "simplify", "fewer-permission-prompts", "keybindings-help",
            "init", "dataviz"} | {"anthropic-skills:" + s for s in (
                "deep-research", "morning", "import-memory", "consolidate-memory", "setup-claude",
                "explain-usage", "google-workspace", "schedule")}
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


# General skills an agent reaches by their listed description alone (no hub, nothing to route from).
STANDALONE = {"code-standards"}


def test_skills_are_reachable():
    sk = shipped()
    hubs, _ = hubs_and_modules()
    texts = {"agents/" + p.name: p.read_text(encoding="utf-8") for p in sorted(AGENTS.glob("*.md"))}
    texts.update({"rules/" + p.name: p.read_text(encoding="utf-8") for p in sorted(RULES.glob("*.md"))})
    texts.update({"skills/" + n: p.read_text(encoding="utf-8") for n, p in sk.items()})
    orphans = []
    for name in sorted(set(sk) - set(hubs) - STANDALONE):
        rx = re.compile(r"(?<![\w-])%s(?![\w-])" % re.escape(name))
        if not any(rx.search(t) for where, t in texts.items() if where != "skills/" + name):
            orphans.append(name)
    assert not orphans, ("skills no hub, other skill, agent body or rules file names (add them to a "
                         "hub's Modules table or an agent's Skills line): %s" % orphans)
    assert not STANDALONE - set(sk), "STANDALONE names a skill that is not shipped"


def test_module_table_parser():
    text = ("---\nname: h\ndescription: Load x.\n---\n# H\n\n## Modules\n| module | when |\n|---|---|\n"
            "| `a-b` | uses `not-me` |\n| `c` | z |\n\n## Other\n| `d` | e |\n")
    assert module_table(text) == ["a-b", "c"]
    assert REF_RE.findall("see `references/x-y.md` and ../rust-engineering/references/z.md.") == [
        "references/x-y.md", "../rust-engineering/references/z.md"]


# Modules that stay in the listing with their description: entry points in their own right, reached
# by agents outside the hub's family (main-coder, planner) who would otherwise need an unrelated hub
# first (postgresql via db-design, obs-otel via self-hosting-ops). Measured in
# .claude-work/agents-p3/lookup/lookup-eval.md: this set cuts the hub-hop rate from 4% to 3% for
# 1.5K listing characters.
KEEP_LISTED = {"postgresql", "mysql", "mongodb", "redis", "sqlite", "cloud-aws", "cloud-gcp", "k8s-ops",
               "obs-otel", "net-diagnostics", "flutter", "react-native", "docs-sites", "wasm",
               "linux-nvidia-cuda"}
ROW_RE = re.compile(r"^\|\s*`([a-z0-9-]+)`(\*?)", re.M)
HIDDEN_NOTE = "`*` = not in the skill listing: Read `__CLAUDE_DIR__/skills/<name>/SKILL.md`"


def table_rows():
    """{skill: [(table owner, marked)]} for skills named in the first column of another skill's table."""
    rows = {}
    for owner, p in shipped().items():
        for m in ROW_RE.finditer(p.read_text(encoding="utf-8")):
            if m.group(1) != owner:
                rows.setdefault(m.group(1), []).append((owner, bool(m.group(2))))
    return rows


def hidden():
    return {k for k, v in overrides().items() if v in ("user-invocable-only", "off")} & set(shipped())


def test_hub_modules_hidden_except_keep_listed():
    sk, rows = shipped(), table_rows()
    modules = set(rows) & set(sk)   # a hub named in a table row would need KEEP_LISTED too
    want = modules - KEEP_LISTED
    assert hidden() == want, ("skillOverrides user-invocable-only != table modules - KEEP_LISTED: "
                              "missing %s, extra %s" % (sorted(want - hidden()), sorted(hidden() - want)))
    assert not KEEP_LISTED - modules, "KEEP_LISTED names a skill no table row names: %s" % sorted(
        KEEP_LISTED - modules)
    bad = sorted(k for k, v in overrides().items() if k in sk and v not in ("user-invocable-only", "name-only"))
    assert not bad, "shipped skills use only user-invocable-only or name-only (no off, no on): %s" % bad


# Lazy skill listing (2026-10-04, the user's decision: most skills listed by name only). These keep
# their description in the listing: cross-domain entry skills any agent may need without its Skills
# line naming them (workflow, review, config, prompts, security, shell, git, web, tests, writing,
# diagrams, browser and screen, pt-PT), the skills loaded more than 3 times in 360 subagent runs
# (image-prompting, python-engineering beyond the above), and the language, database, ops and media
# entries generalist coders, planners and reviewers reach without a row. Every other listed skill is
# "name-only": still invocable through the Skill tool by name. Offline lookup eval (52 tasks, a
# name-only skill counted as found only when the agent's own Skills line names it): one-call reach
# 98.7% (misses: hf-hub for llm-engineer, category-theory for mathematician), listing 14,564 -> 5,433.
LISTED_CORE = {
    "code-standards", "review-protocol", "claude-code-extensions", "prompt-and-brief-design",
    "secure-coding", "shell-scripting", "git-workflows", "web-research", "test-strategy",
    "technical-writing", "diagrams-as-code", "browser-automation", "computer-use-apps",
    "portuguese-pt-writing", "image-prompting", "python-engineering", "typescript-engineering",
    "go-engineering", "rust-engineering", "cpp-engineering", "jvm-engineering", "db-design",
    "postgresql", "mysql", "sqlite", "obs-otel", "container-images", "ci-cd-pipelines",
    "raster-imaging", "media-ffmpeg", "api-design", "algorithm-design"}


def test_listed_skills_are_name_only_except_core():
    sk, so = shipped(), overrides()
    invocable = {n for n, p in sk.items()
                 if not re.search(r"(?m)^disable-model-invocation:\s*true", split(p.read_text())[0])}
    listed = invocable - hidden()
    assert LISTED_CORE <= listed, "LISTED_CORE names a hidden, user-only or missing skill: %s" % sorted(
        LISTED_CORE - listed)
    described = sorted(n for n in listed if so.get(n, "on") == "on")
    assert set(described) == LISTED_CORE, ("described skills != LISTED_CORE: extra %s, missing %s" % (
        sorted(set(described) - LISTED_CORE), sorted(LISTED_CORE - set(described))))
    wrong = sorted(n for n in listed - LISTED_CORE if so.get(n) != "name-only")
    assert not wrong, "listed skills outside LISTED_CORE must be name-only: %s" % wrong


def test_hidden_modules_reachable_by_path_from_a_marked_row():
    sk, rows, hid = shipped(), table_rows(), hidden()
    for name in sorted(hid):
        marked = [o for o, star in rows.get(name, []) if star]
        assert marked, "hidden %s has no `%s`* row in a hub table" % (name, name)
        for o in marked:
            assert HIDDEN_NOTE in sk[o].read_text(encoding="utf-8"), "%s marks %s but lacks the note" % (o, name)
    wrong = sorted("%s in %s" % (n, o) for n, v in rows.items() for o, star in v
                   if star and n not in hid)
    assert not wrong, "rows marked * for skills that are listed: %s" % wrong
    unmarked = sorted("%s in %s" % (n, o) for n, v in rows.items() for o, star in v
                      if not star and n in hid)
    assert not unmarked, "hidden modules in a table without the * mark: %s" % unmarked


def test_listing_math_counts_hidden_as_zero():
    import sys
    sys.path.insert(0, str(ROOT / "tests"))
    from lint_agents import skill_listing_entry
    assert skill_listing_entry("rust-async", 90, "user-invocable-only") == 0
    assert skill_listing_entry("rust-async", 90, "off") == 0
    assert skill_listing_entry("rust-async", 90, "on") == len("rust-async") + 4 + 90


def test_listing_settings_keys():
    s = json.loads(SETTINGS.read_text())
    assert 0.01 <= float(s["skillListingBudgetFraction"]) <= 0.02
    assert isinstance(s["skillListingMaxDescChars"], int)
    assert isinstance(s["skillOverrides"], dict) and set(s["skillOverrides"].values()) <= {
        "on", "name-only", "user-invocable-only", "off"}


def test_no_agent_preloads_skills():
    pre = sorted(p.name for p in AGENTS.glob("*.md")
                 if re.search(r"(?m)^skills\s*:", split(p.read_text(encoding="utf-8"))[0]))
    assert not pre, "agents with a skills: preload (skills load on demand, lazily): %s" % pre


def test_forced_load_lint_patterns():
    """Skills lines are lookups (the user, 2026-10-02): lint rejects wording that forces a load."""
    import sys
    sys.path.insert(0, str(ROOT / "tests"))
    from lint_agents import FORCED_LOAD_RES
    forced = ["Load `go-engineering` first (x)", "always load `x`", "You must load the skill", "First load `a`",
              "Every task: load `x`"]
    fine = ["Load `browser-automation` before a multi-step flow", "check the load first.", "`x` for scripts",
            "load `image-prompting` before generating ("]
    assert all(any(r.search(s) for r in FORCED_LOAD_RES) for s in forced)
    assert not any(r.search(s) for r in FORCED_LOAD_RES for s in fine)
