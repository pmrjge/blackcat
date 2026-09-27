#!/usr/bin/env python3
"""Lint dot-claude/agents/*.md against the spawn policy and frontmatter rules.

Usage:
    python3 tests/lint_agents.py [--policy-json PATH]

By default the policy is obtained by running:
    python3 dot-claude/hooks/agent_guard.py --print-policy
which must print JSON: {"policy": {...}, "leaves": [...], "agents": [...], "builtins": ["explore"],
"self_spawn": [...], "blackcat_tools": [...]}.

If that invocation fails (e.g. agent_guard.py isn't rewritten yet in a parallel
branch of work), pass --policy-json pointing at a JSON file with the same shape
as a fallback fixture.

Exits 0 and prints "lint_agents: ok" when every check passes; otherwise prints
each failure and exits 1.
"""
import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
AGENTS_DIR = REPO_ROOT / "dot-claude" / "agents"
SKILLS_DIR = REPO_ROOT / "dot-claude" / "skills"
AGENT_GUARD = REPO_ROOT / "dot-claude" / "hooks" / "agent_guard.py"
SETTINGS = REPO_ROOT / "dot-claude" / "settings.json"

VALID_COLORS = {"red", "blue", "green", "yellow", "purple", "orange", "pink", "cyan"}
VALID_EFFORTS = {"low", "medium", "high", "xhigh", "max"}
VALID_MEMORY = {"user", "project", "local"}
ANTHROPIC_DOC_SKILLS = {"docx", "xlsx", "pptx", "pdf"}
KNOWN_PLACEHOLDERS = {
    "__CLAUDE_DIR__", "__HOME__", "__PYTHON3__", "__UV__", "__UVX__", "__NPX__",
    "__NODE__", "__MAGG__", "__HUETENSION__", "__STACK_REPO__",
}
TASK_TOOL_RE = re.compile(r"^Task(Create|Get|Update|List|Output)$")
PLACEHOLDER_RE = re.compile(r"__[A-Z_]+__")

errors = []


def fail(msg):
    errors.append(msg)


def load_policy(policy_json_path):
    if policy_json_path:
        data = json.loads(Path(policy_json_path).read_text())
        return data, f"fixture {policy_json_path}"
    try:
        out = subprocess.run(
            [sys.executable, str(AGENT_GUARD), "--print-policy"],
            capture_output=True, text=True, timeout=15, check=True,
        )
        return json.loads(out.stdout), "agent_guard.py --print-policy"
    except Exception as exc:  # noqa: BLE001 - report and let caller decide
        return None, f"unavailable ({exc})"


def split_top_level(s, sep=","):
    """Split on sep at paren-depth 0."""
    tokens, cur, depth = [], "", 0
    for ch in s:
        if ch in "([":
            depth += 1
            cur += ch
        elif ch in ")]":
            depth -= 1
            cur += ch
        elif ch == sep and depth == 0:
            tokens.append(cur.strip())
            cur = ""
        else:
            cur += ch
    if cur.strip():
        tokens.append(cur.strip())
    return tokens


def leading_name(token):
    m = re.match(r"^([A-Za-z][A-Za-z0-9_-]*)", token.strip())
    return m.group(1) if m else token.strip()


def parse_frontmatter(text):
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        raise ValueError("missing frontmatter delimiter")
    try:
        end = lines[1:].index("---") + 1
    except ValueError:
        raise ValueError("missing closing frontmatter delimiter")
    fm_lines = lines[1:end]
    body = "\n".join(lines[end + 1:])

    data = {}
    i, n = 0, len(fm_lines)
    while i < n:
        line = fm_lines[i]
        if not line.strip() or line.lstrip().startswith("#"):
            i += 1
            continue
        m = re.match(r"^([A-Za-z_]+):\s*(.*)$", line)
        if not m:
            i += 1
            continue
        key, val = m.group(1), m.group(2)
        if val.strip() == "":
            block, j = [], i + 1
            while j < n and (fm_lines[j].startswith(" ") or not fm_lines[j].strip()):
                block.append(fm_lines[j])
                j += 1
            data[key] = ("block", block)
            i = j
        else:
            data[key] = ("inline", val.strip())
            i += 1
    return data, body


def yaml_plain_hazard(val):
    """Why a one-line frontmatter value would not parse as YAML (or would lose text), else None.
    Claude Code quotes some such values itself as a fallback; other tools that read skills don't."""
    v = val.strip()
    if not v:
        return None
    if v[0] in "\"'":
        return None if len(v) >= 2 and v[-1] == v[0] else "starts with a quote it never closes"
    if v[0] in "[]{}&*!|>%@`,#":
        return "starts with %r" % v[0]
    if v[:2] in ("- ", "? ", ": "):
        return "starts with %r" % v[:2]
    if ": " in v or v.endswith(":"):
        return "contains ': ' or ends with ':' — a plain YAML value can't (use ' — ' or quote it)"
    if " #" in v:
        return "contains ' #' — YAML reads the rest as a comment"
    return None


def get_inline(data, key, default=None):
    v = data.get(key)
    if v is None:
        return default
    kind, val = v
    return val if kind == "inline" else default


def get_tools(data):
    """Return (flat_tool_names, agent_paren_contents_or_None)."""
    raw = get_inline(data, "tools")
    if raw is None:
        return [], None
    tokens = split_top_level(raw, ",")
    flat = []
    agent_children = None
    for t in tokens:
        m = re.match(r"^Agent\(([^)]*)\)$", t.strip())
        if m:
            flat.append("Agent")
            agent_children = [leading_name(x) for x in split_top_level(m.group(1), ",")]
        else:
            flat.append(t.strip())
    return flat, agent_children


def get_skills(data):
    v = data.get("skills")
    if v is None:
        return []
    kind, val = v
    if kind == "inline":
        val = val.strip()
        if val.startswith("[") and val.endswith("]"):
            inner = val[1:-1]
            return [x.strip() for x in inner.split(",") if x.strip()]
        return [val] if val else []
    # block style: "  - name"
    names = []
    for line in val:
        m = re.match(r"^\s*-\s*(\S+)\s*$", line)
        if m:
            names.append(m.group(1))
    return names


def get_mcp_server_names(data):
    v = data.get("mcpServers")
    if v is None:
        return []
    kind, val = v
    names = []
    if kind == "block":
        for line in val:
            m = re.match(r"^\s*-\s*([A-Za-z0-9_-]+):\s*$", line)
            if m:
                names.append(m.group(1))
    return names


def get_may_spawn(body):
    m = re.search(r"May spawn:\s*([^.]*)\.", body)
    if not m:
        return None
    tokens = split_top_level(m.group(1), ",")
    return [leading_name(t).lower() for t in tokens if leading_name(t)]


def skill_names():
    return {d.name for d in SKILLS_DIR.iterdir() if (d / "SKILL.md").is_file()}


def referenced_skills(body):
    """Skill names an agent body tells the agent to load: backticked names in a 'Skills' section
    and 'Load the `x` skill' / '`x` with the Skill tool' phrases."""
    names = set(re.findall(r"[Ll]oad (?:the )?`([a-z0-9-]+)`", body))
    names |= set(re.findall(r"`([a-z0-9-]+)` with the Skill tool", body))
    in_skills = False
    for line in body.splitlines():
        if line.startswith("#"):
            in_skills = "skill" in line.lower()
            continue
        if in_skills:
            names |= set(re.findall(r"`([a-z0-9-]+)`", line))
    return names


def check_agent_file(path, policy_row, leaves, builtins, blackcat_tools=None):
    name_from_file = path.stem
    text = path.read_text()
    try:
        data, body = parse_frontmatter(text)
    except ValueError as exc:
        fail(f"{path.name}: cannot parse frontmatter: {exc}")
        return

    # name == filename
    name = get_inline(data, "name")
    if name != name_from_file:
        fail(f"{path.name}: name: {name!r} != filename stem {name_from_file!r}")
    hazard = yaml_plain_hazard(get_inline(data, "description", ""))
    if hazard:
        fail(f"{path.name}: description {hazard}")

    # model
    model = get_inline(data, "model")
    if not model:
        fail(f"{path.name}: missing model")
    else:
        known_model_words = ("sonnet", "opus", "haiku", "fable", "inherit")
        if not any(w in model.lower() for w in known_model_words):
            fail(f"{path.name}: model {model!r} doesn't look like a known model id/alias")

    # effort
    effort = get_inline(data, "effort")
    if effort is not None and effort not in VALID_EFFORTS:
        fail(f"{path.name}: invalid effort {effort!r} (expected one of {sorted(VALID_EFFORTS)})")

    # the stack runs no Haiku: Sonnet 5 wherever a small model would do
    if model and "haiku" in model.lower():
        fail(f"{path.name}: model {model!r} — this stack uses claude-sonnet-5 instead of Haiku")

    # color
    color = get_inline(data, "color")
    if not color:
        fail(f"{path.name}: missing color")
    elif color not in VALID_COLORS:
        fail(f"{path.name}: invalid color {color!r} (expected one of {sorted(VALID_COLORS)})")

    # memory
    memory = get_inline(data, "memory")
    if memory is not None and memory not in VALID_MEMORY:
        fail(f"{path.name}: invalid memory {memory!r} (expected one of {sorted(VALID_MEMORY)})")

    # tools / Agent / SendMessage / Task*
    flat_tools, agent_children = get_tools(data)
    if "Bash" in flat_tools and ({"Glob", "Grep"} & set(flat_tools)):
        fail(f"{path.name}: Glob/Grep listed together with Bash never resolve on macOS/Linux "
             "(Claude Code only restores them when Bash is absent); drop them")
    for t in flat_tools:
        if TASK_TOOL_RE.match(t):
            fail(f"{path.name}: forbidden tool {t!r} in tools: (only TaskStop is allowed)")

    has_agent = "Agent" in flat_tools
    has_send = "SendMessage" in flat_tools
    if has_agent and not has_send:
        fail(f"{path.name}: has Agent in tools but no SendMessage")

    row = policy_row.get(name_from_file, [])
    if (name_from_file in leaves) != (not row and name_from_file != "blackcat"):
        fail(f"{path.name}: LEAVES and the policy row disagree (a leaf has an empty row)")
    if name_from_file == "blackcat":
        if agent_children is None:
            fail(f"{path.name}: blackcat tools: must list Agent(<row>)")
        else:
            got = {c.lower() for c in agent_children}
            want = {r.lower() for r in row}
            if got != want:
                fail(
                    f"{path.name}: blackcat Agent(...) {sorted(got)} != blackcat policy row "
                    f"{sorted(want)}"
                )
        if blackcat_tools is not None and set(flat_tools) != set(blackcat_tools):
            fail(f"{path.name}: blackcat tools {sorted(flat_tools)} != agent_guard BLACKCAT_TOOLS "
                 f"{sorted(blackcat_tools)} (the blackcat-guard hook would deny the difference)")
    else:
        if row:
            if not has_agent:
                fail(f"{path.name}: policy row is non-empty but tools: has no Agent")
        else:
            if has_agent:
                fail(f"{path.name}: policy row is empty (leaf) but tools: has Agent")

        may_spawn = get_may_spawn(body)
        if row:
            if may_spawn is None:
                fail(f"{path.name}: no 'May spawn:' sentence found in body")
            else:
                got = set(may_spawn)
                want = {r.lower() for r in row}
                if got != want:
                    fail(
                        f"{path.name}: 'May spawn' {sorted(got)} != policy row {sorted(want)}"
                    )
        else:
            if may_spawn:
                fail(
                    f"{path.name}: leaf agent has a non-empty 'May spawn' sentence: "
                    f"{may_spawn}"
                )

    # mcpServers entries have a matching mcp__<name> tool
    for server in get_mcp_server_names(data):
        wanted = f"mcp__{server}"
        if wanted not in flat_tools:
            fail(f"{path.name}: mcpServers entry {server!r} has no {wanted!r} in tools:")

    # placeholders
    for m in PLACEHOLDER_RE.finditer(text):
        if m.group(0) not in KNOWN_PLACEHOLDERS:
            fail(f"{path.name}: unknown placeholder {m.group(0)!r}")

    # skills are dynamic: no agent preloads one, every agent can load any of them
    if get_skills(data) or "skills" in data:
        fail(f"{path.name}: preloads skills {get_skills(data)} — skills are loaded on demand by any agent "
             "whose task matches their description; remove the skills: field")
    if "Skill" not in flat_tools:
        fail(f"{path.name}: tools: has no Skill — every agent must be able to load any skill")

    # on-demand skills named in the body exist, and the agent can call the Skill tool
    wanted = referenced_skills(body)
    known = skill_names() | ANTHROPIC_DOC_SKILLS | {"document-skills", "anthropic-skills"}
    for s in sorted(wanted - known):
        fail(f"{path.name}: body refers to skill {s!r}, which does not exist under {SKILLS_DIR}")
    if wanted and "Skill" not in flat_tools:
        fail(f"{path.name}: body tells the agent to load skills but tools: has no Skill")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--policy-json", default=None, help="fallback policy fixture path")
    args = ap.parse_args()

    policy_data, source = load_policy(args.policy_json)
    if policy_data is None:
        print(
            f"lint_agents: --print-policy {source}; no --policy-json fallback given, "
            "cannot run policy-dependent checks",
            file=sys.stderr,
        )
        sys.exit(1)
    print(f"lint_agents: policy source = {source}", file=sys.stderr)

    policy_row = policy_data["policy"]
    leaves = set(policy_data["leaves"])
    builtins = set(policy_data.get("builtins", ["explore"]))
    expected_agents = policy_data.get("agents")

    files = sorted(AGENTS_DIR.glob("*.md"))
    if expected_agents is not None and len(files) != len(expected_agents):
        fail(f"expected {len(expected_agents)} agent files (policy AGENTS), found {len(files)}: "
             f"{[f.name for f in files]}")

    if expected_agents is not None:
        got_names = {f.stem for f in files}
        want_names = set(expected_agents)
        if got_names != want_names:
            fail(
                f"agent file set {sorted(got_names)} != policy agents {sorted(want_names)}"
            )

    blackcat_tools = policy_data.get("blackcat_tools")
    for f in files:
        check_agent_file(f, policy_row, leaves, builtins, blackcat_tools)

    # every model-invocable skill is pre-approved, or background agents hit permission prompts
    try:
        allow = set(json.loads(SETTINGS.read_text()).get("permissions", {}).get("allow", []))
    except (OSError, ValueError) as exc:
        fail(f"settings.json unreadable: {exc}")
        allow = set()
    agents = set(expected_agents or [])
    listing = []
    for s in sorted(skill_names()):
        text = (SKILLS_DIR / s / "SKILL.md").read_text()
        head = text.split("---", 2)[1] if text.startswith("---") else ""
        m = re.search(r"(?m)^name:\s*(\S+)", head)
        if m and m.group(1) != s:
            fail(f"skills/{s}/SKILL.md: name {m.group(1)!r} != directory name")
        d = re.search(r"(?m)^description:\s*(.*)$", head)
        if not d or not d.group(1).strip():
            fail(f"skills/{s}/SKILL.md: no one-line description — it is what agents choose skills by")
        else:
            hazard = yaml_plain_hazard(d.group(1))
            if hazard:
                fail(f"skills/{s}/SKILL.md: description {hazard}")
            if len(d.group(1).strip()) > 1536:
                fail(f"skills/{s}/SKILL.md: description over 1,536 characters is cut in the skill listing")
        named = sorted(a for a in agents
                       if d and re.search(r"(?<![\w-])%s(?![\w-])" % re.escape(a), d.group(1)))
        if named:
            fail(f"skills/{s}/SKILL.md: description names agents {named} — say when to load it, not who")
        if re.search(r"(?m)^disable-model-invocation:\s*(true|yes|on|1)\s*$", head):
            continue
        listing.append(len(s) + 4 + min(len(d.group(1).strip()) if d else 0, 1536))
        if "Skill" not in allow and f"Skill({s})" not in allow:
            fail(f"settings.json permissions.allow lacks Skill (or Skill({s})) — agents loading it on "
                 "demand would stop at a permission prompt")
    # Claude Code lists every skill (name + description) to every agent within
    # skillListingBudgetFraction (default 0.01) of the context window, at ~3 characters per token on
    # current models; over it, the least-used skills show by name only. The stack's own skills must
    # leave half of that for plugin and claude.ai skills.
    try:
        frac = float(json.loads(SETTINGS.read_text()).get("skillListingBudgetFraction", 0.01))
    except (OSError, ValueError, TypeError):
        frac = 0.01
    used, budget = sum(listing) + max(0, len(listing) - 1), int(1_000_000 * 3 * frac)
    if used > budget // 2:
        fail(f"skill listing is {used} characters, over half the {budget}-character budget "
             f"(skillListingBudgetFraction={frac}): shorten descriptions or raise the fraction")

    if errors:
        print(f"lint_agents: {len(errors)} failure(s):", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        sys.exit(1)

    print("lint_agents: ok")
    sys.exit(0)


if __name__ == "__main__":
    main()
