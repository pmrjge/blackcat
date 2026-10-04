"""Static checks of the repo source: the stack must not ship the same skill, agent, hook
registration, MCP entry, rule or plugin skill from two sources. (The installer's runtime dedupe
is tested elsewhere; nothing here runs the installer.)

Run: uv run --with pytest pytest -q tests/test_no_duplicates.py
"""
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
DOT = ROOT / "dot-claude"
INSTALL = ROOT / "install.sh"
SETTINGS = DOT / "settings.json"
MAGG = DOT / "magg" / "config.json"

# Skill names owned by Claude Code itself, Anthropic plugins or the desktop app.
EXTERNAL_SKILLS = {
    "dataviz", "claude-api", "update-config", "workflow-authoring", "loop", "schedule", "run",
    "docx", "xlsx", "pptx", "pdf", "skill-creator", "build-mcp-server", "build-mcp-app",
    "build-mcpb", "math-olympiad", "consolidate-memory", "deep-research", "docs", "explain-usage",
    "google-workspace", "import-memory", "morning", "setup-claude", "chrome-browser",
    "built-in-browser", "computer-use", "session-report",
}
EXTERNAL_PREFIXES = ("artifact-",)

PLUGIN_SKILLS = {
    "document-skills": ["docx", "xlsx", "pptx", "pdf"],
    "skill-creator": ["skill-creator"],
    "math-olympiad": ["math-olympiad"],
    "mcp-server-dev": ["build-mcp-server", "build-mcp-app", "build-mcpb"],
    "session-report": ["session-report"],
}


# ---------------------------------------------------------------- helpers

def frontmatter(path):
    """Text between the first two `---` lines ('' when absent)."""
    lines = path.read_text().splitlines()
    if not lines or lines[0].strip() != "---":
        return ""
    out = []
    for ln in lines[1:]:
        if ln.strip() == "---":
            break
        out.append(ln)
    return "\n".join(out)


def fm_value(fm, key):
    m = re.search(r"^%s:[ \t]*(.*)$" % re.escape(key), fm, re.M)
    if not m:
        return None
    v = m.group(1).strip()
    if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
        v = v[1:-1]
    return v


def fm_block(fm, key):
    """Lines of a top-level `key:` block (indented lines up to the next top-level key)."""
    out, on = [], False
    for ln in fm.splitlines():
        if re.match(r"^%s:" % re.escape(key), ln):
            on = True
            continue
        if on:
            if ln and not ln[0].isspace() and not ln.startswith("#"):
                break
            out.append(ln)
    return out


def skills():
    return sorted((DOT / "skills").glob("*/SKILL.md"))


def agents():
    return sorted((DOT / "agents").glob("*.md"))


def dup_pairs(pairs):
    """[(key, source)] -> {key: [sources]} for keys seen more than once."""
    seen = defaultdict(list)
    for k, s in pairs:
        seen[k].append(s)
    return {k: v for k, v in seen.items() if len(v) > 1}


def rel(p):
    return str(Path(p).relative_to(ROOT)) if isinstance(p, Path) else str(p)


def strict_pairs(pairs):
    seen = set()
    for k, _ in pairs:
        if k in seen:
            raise ValueError("duplicate JSON key %r" % k)
        seen.add(k)
    return dict(pairs)


def load_json_strict(path):
    return json.loads(path.read_text(), object_pairs_hook=strict_pairs)


def settings():
    return json.loads(SETTINGS.read_text())


def install_text():
    return INSTALL.read_text()


def yaml_command(raw):
    raw = raw.strip()
    if raw.startswith('"'):
        try:
            return json.loads(raw)
        except ValueError:
            pass
    return raw.strip("'\"")


def agent_hook_commands(path):
    fm = frontmatter(path)
    return [yaml_command(m.group(1)) for ln in fm_block(fm, "hooks")
            if (m := re.match(r"\s*(?:-\s*)?command:\s*(.+)$", ln))]


def inline_servers(path):
    names = []
    for ln in fm_block(frontmatter(path), "mcpServers"):
        m = re.match(r"^  - ([A-Za-z0-9_.-]+):?\s*$", ln)
        if m:
            names.append(m.group(1))
    return names


def agent_tools(path):
    return [t.strip() for t in (fm_value(frontmatter(path), "tools") or "").split(",")]


def magg_names():
    return set(load_json_strict(MAGG)["servers"])


def user_scope_servers():
    txt = install_text()
    names = re.findall(r'^\s*\("([a-z0-9-]+)", "[a-z0-9.]+", \{', txt, re.M)
    names += re.findall(r'rows\.append\(\("(wandb)"', txt)
    return names


def stack_skill_names():
    return {fm_value(frontmatter(p), "name") for p in skills()}


# ---------------------------------------------------------------- 1. skills

def test_skill_names_unique_and_match_dir():
    pairs, bad = [], []
    for p in skills():
        name = fm_value(frontmatter(p), "name")
        if name != p.parent.name:
            bad.append("%s: name %r != directory %r" % (rel(p), name, p.parent.name))
        pairs.append((name, rel(p)))
    assert not bad, "\n".join(bad)
    d = dup_pairs(pairs)
    assert not d, "skill name shipped twice: %s" % d


def test_skill_names_do_not_shadow_external_skills():
    bad = []
    for p in skills():
        name = fm_value(frontmatter(p), "name")
        if name in EXTERNAL_SKILLS or (name or "").startswith(EXTERNAL_PREFIXES):
            bad.append("%s: stack skill %r collides with an external skill of the same name"
                       % (rel(p), name))
    assert not bad, "\n".join(bad)


# ---------------------------------------------------------------- 2. agents

def test_agent_names_unique_and_match_file_stem():
    pairs, bad = [], []
    for p in agents():
        name = fm_value(frontmatter(p), "name")
        if name != p.stem:
            bad.append("%s: name %r != file stem %r" % (rel(p), name, p.stem))
        pairs.append((name, rel(p)))
    assert not bad, "\n".join(bad)
    d = dup_pairs(pairs)
    assert not d, "agent name shipped twice: %s" % d


# ---------------------------------------------------------------- 3. JSON keys

@pytest.mark.parametrize("path", [SETTINGS, MAGG], ids=lambda p: p.name if p == SETTINGS else "magg/config.json")
def test_json_has_no_duplicate_keys(path):
    try:
        load_json_strict(path)
    except ValueError as e:
        pytest.fail("%s: %s" % (rel(path), e))


# ---------------------------------------------------------------- 4. settings lists

def _dig(d, dotted):
    for k in dotted.split("."):
        if not isinstance(d, dict) or k not in d:
            return []
        d = d[k]
    return d


@pytest.mark.parametrize("dotted", [
    "permissions.allow", "permissions.deny", "permissions.ask",
    "sandbox.filesystem.allowWrite", "sandbox.filesystem.denyWrite", "sandbox.filesystem.denyRead",
    "sandbox.network.allowedDomains",
])
def test_settings_list_has_no_duplicates(dotted):
    items = _dig(settings(), dotted)
    d = [k for k, n in Counter(items).items() if n > 1]
    assert not d, "settings.json %s repeats: %s" % (dotted, d)


def test_settings_allow_and_deny_disjoint():
    perms = settings().get("permissions", {})
    both = set(perms.get("allow", [])) & set(perms.get("deny", []))
    assert not both, "settings.json rule in both permissions.allow and permissions.deny: %s" % sorted(both)


def test_settings_allow_and_ask_disjoint():
    perms = settings().get("permissions", {})
    both = set(perms.get("allow", [])) & set(perms.get("ask", []))
    assert not both, "settings.json rule in both permissions.allow and permissions.ask: %s" % sorted(both)


def test_magg_prefix_rules_name_catalog_prefixes():
    """Every mcp__magg__<prefix>_* rule names a prefix of the magg catalog (a typo such as
    qiskit-runtime_* would match nothing and leave the tools unprompted), and the servers that act
    outside the machine or run code ask at every call: ask rules prompt even in bypassPermissions."""
    prefixes = {v.get("prefix") or k for k, v in load_json_strict(MAGG)["servers"].items()}
    perms = settings().get("permissions", {})
    for kind in ("allow", "ask"):
        for rule in perms.get(kind, []):
            m = re.match(r"mcp__magg__(.+)_\*\Z", rule)
            if m:
                assert m.group(1) in prefixes, "%s rule %s names no magg catalog prefix" % (kind, rule)
    for p in ("duckdb", "jupyter", "ros", "qiskit", "docspace"):
        assert p in prefixes, p
        assert "mcp__magg__%s_*" % p in perms.get("ask", []), p


def test_every_magg_prefix_has_exactly_one_allow_or_ask_rule():
    """No catalog server runs unprompted without a decision: in bypassPermissions a tool with no
    rule runs silently, so each prefix is either allowed (read-only or local) or asks — never both,
    never neither. A new catalog entry fails here until someone picks one."""
    perms = settings().get("permissions", {})
    allow, ask = set(perms.get("allow", [])), set(perms.get("ask", []))
    bad = []
    for name, entry in sorted(load_json_strict(MAGG)["servers"].items()):
        rule = "mcp__magg__%s_*" % (entry.get("prefix") or name)
        n = (rule in allow) + (rule in ask)
        if n != 1:
            bad.append("%s (%s): %s" % (name, rule, "in both allow and ask" if n else "no rule"))
    assert not bad, "magg catalog servers without exactly one allow/ask rule: %s" % bad


def test_allowed_magg_database_servers_stay_read_only():
    """mongodb_* and postgres_* are allowed unprompted only because their catalog flags keep them
    read-only: --readOnly registers no write tools, --access-mode=restricted runs read-only
    transactions. Dropping a flag must come with moving the rule to ask."""
    servers = load_json_strict(MAGG)["servers"]
    allow = set(settings().get("permissions", {}).get("allow", []))
    assert "--readOnly" in servers["mongodb"]["args"]
    assert "--access-mode=restricted" in servers["postgres"]["args"]
    assert not any(a.startswith("--access-mode=") and a != "--access-mode=restricted"
                   for a in servers["postgres"]["args"])
    assert {"mcp__magg__mongodb_*", "mcp__magg__postgres_*"} <= allow


def test_settings_credential_envvars_unique_by_name():
    names = [e["name"] for e in _dig(settings(), "sandbox.credentials.envVars")]
    d = [k for k, n in Counter(names).items() if n > 1]
    assert not d, "settings.json sandbox.credentials.envVars repeats name: %s" % d


# ---------------------------------------------------------------- 5. hooks

def _settings_hook_entries():
    out = []
    for event, groups in settings().get("hooks", {}).items():
        for gi, g in enumerate(groups):
            for h in g.get("hooks", []):
                if "command" in h:
                    out.append((event, g.get("matcher"), h["command"], gi))
    return out


def test_settings_hooks_no_duplicate_registration():
    entries = _settings_hook_entries()
    d = dup_pairs([((e, m, c), "group #%d" % gi) for e, m, c, gi in entries])
    assert not d, "settings.json registers the same (event, matcher, command) twice: %s" % d
    # no group repeats a command
    for event, groups in settings().get("hooks", {}).items():
        for gi, g in enumerate(groups):
            cmds = [h.get("command") for h in g.get("hooks", [])]
            rep = [c for c, n in Counter(cmds).items() if n > 1]
            assert not rep, "settings.json hooks.%s group #%d repeats command %s" % (event, gi, rep)


def test_agent_frontmatter_hooks_do_not_repeat_settings_hooks():
    # Known intentional double wiring: blackcat.md's frontmatter PreToolUse hook runs
    # `agent_guard.py" blackcat-guard` and settings.json's PreToolUse "*" group runs
    # `agent_guard.py" blackcat-guard --settings`. The guard claims each tool_use_id once, so the
    # pair cannot double count. The commands differ (`--settings`), so plain equality is the
    # right check and this pair passes it; any other equal command is a real duplicate.
    settings_cmds = {}
    for e, m, c, _ in _settings_hook_entries():
        settings_cmds.setdefault(c, "settings.json %s[%s]" % (e, m))
    bad = []
    for p in agents():
        for c in agent_hook_commands(p):
            if c in settings_cmds:
                bad.append("%s frontmatter hook duplicates %s: %s" % (rel(p), settings_cmds[c], c))
    assert not bad, "\n".join(bad)


# ---------------------------------------------------------------- 6. MCP entries

def test_user_scope_servers_unique_and_not_elsewhere():
    us = user_scope_servers()
    assert us, "no user-scope rows parsed from install.sh compute_mcp_plan"
    d = [k for k, n in Counter(us).items() if n > 1]
    assert not d, "install.sh registers user-scope server twice: %s" % d
    clash = sorted(set(us) & magg_names())
    assert not clash, "user-scope server also in the magg catalog (magg/config.json): %s" % clash
    inline = {}
    for p in agents():
        for n in inline_servers(p):
            inline.setdefault(n, rel(p))
    clash = ["%s: user-scope in install.sh and inline in %s" % (n, inline[n]) for n in us if n in inline]
    assert not clash, "\n".join(clash)


def test_inline_servers_not_reached_through_two_sources():
    magg = magg_names()
    bad = []
    for p in agents():
        inl = inline_servers(p)
        rep = [k for k, n in Counter(inl).items() if n > 1]
        if rep:
            bad.append("%s lists inline server twice: %s" % (rel(p), rep))
        if "mcp__magg" in agent_tools(p):
            for n in inl:
                if n in magg:
                    bad.append("%s reaches %r twice: `mcp__magg` in tools and inline mcpServers"
                               % (rel(p), n))
    assert not bad, "\n".join(bad)


def test_playwright_magg_and_inline_never_in_one_agent():
    # `playwright` is a magg catalog name AND inline in browser-operator/frontend-engineer/verifier
    # (one instance per agent, by design). Allowed only while no agent has both.
    both = [rel(p) for p in agents()
            if "mcp__magg" in agent_tools(p) and "playwright" in inline_servers(p)]
    assert not both, "agent has mcp__magg and inline playwright: %s" % both


def test_mcp_servers_md_tables_have_no_duplicate_rows():
    # the former mcp_servers.md is CONFIG.md §10 ("Apps, connectors and MCP servers")
    lines = (ROOT / "CONFIG.md").read_text().splitlines()
    sec = next(i for i, ln in enumerate(lines) if ln.startswith("## 10. "))
    tables, cur, start = [], [], 0
    for i, ln in enumerate(lines, 1):
        if i <= sec:
            continue
        if ln.lstrip().startswith("|"):
            if not cur:
                start = i
            cur.append((i, ln))
        elif cur:
            tables.append((start, cur))
            cur = []
    if cur:
        tables.append((start, cur))
    bad = []
    for start, rows in tables:
        seen = {}
        for i, ln in rows:
            cells = [c.strip() for c in ln.strip().strip("|").split("|")]
            first = cells[0] if cells else ""
            if not first or set(first) <= set("-: "):
                continue
            if first in seen:
                bad.append("CONFIG.md:%d duplicates row %r first seen at line %d (table at line %d)"
                           % (i, first, seen[first], start))
            seen.setdefault(first, i)
    assert not bad, "\n".join(bad)


# ---------------------------------------------------------------- 7. rules

def test_rules_no_shared_heading_or_repeated_long_lines():
    files = sorted((DOT / "rules").glob("*.md"))
    heads, lines = [], []
    for p in files:
        for n, ln in enumerate(p.read_text().splitlines(), 1):
            s = ln.strip()
            if len(s) > 40:
                lines.append((s, "%s:%d" % (rel(p), n)))
        m = next((re.match(r"# (.+)", ln) for ln in p.read_text().splitlines()
                  if re.match(r"# \S", ln)), None)
        if m:
            heads.append((m.group(1).strip(), rel(p)))
    d = dup_pairs(heads)
    assert not d, "rules files share a first `# ` heading: %s" % d
    d = dup_pairs(lines)
    assert not d, "rules line (>40 chars) appears twice: %s" % {k[:60]: v for k, v in d.items()}


# ---------------------------------------------------------------- 8. plugins

def _anthropic_plugins():
    m = re.search(r'^ANTHROPIC_PLUGINS="([^"]*)"$', install_text(), re.M)
    assert m, 'install.sh has no ANTHROPIC_PLUGINS="..." line'
    return [w.split("@")[0] for w in m.group(1).split()]


def test_anthropic_plugins_have_known_skills():
    missing = [p for p in _anthropic_plugins() if p not in PLUGIN_SKILLS]
    assert not missing, "install.sh ANTHROPIC_PLUGINS names plugins with no skill list here: %s" % missing


def test_plugin_skills_do_not_equal_stack_skills():
    stack = stack_skill_names()
    bad = []
    for plugin in ["document-skills"] + _anthropic_plugins():
        for s in PLUGIN_SKILLS.get(plugin, []):
            if s in stack:
                bad.append("plugin %s ships skill %r and dot-claude/skills/%s/ also does" % (plugin, s, s))
    assert not bad, "\n".join(bad)


def test_mcp_server_craft_retired_for_mcp_server_dev():
    """S1 (2026-10-04): the stack's mcp-server-craft gave way to Anthropic's mcp-server-dev plugin."""
    assert "mcp-server-dev" in _anthropic_plugins()
    assert not (DOT / "skills" / "mcp-server-craft").exists()
    assert "RETIRED_PLUGINS" not in install_text()
