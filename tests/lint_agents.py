#!/usr/bin/env python3
"""Lint dot-claude/agents/*.md against the spawn policy and frontmatter rules.

Usage:
    python3 tests/lint_agents.py [--policy-json PATH]

By default the policy is obtained by running:
    python3 dot-claude/hooks/agent_guard.py --print-policy
which must print JSON: {"policy": {...}, "leaves": [...], "agents": [...], "builtins": ["explore"],
"self_spawn": [...], "copy_types": {base: copy}, "blackcat_tools": [...]}.

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
# Agents name a family alias; Claude Code resolves it through ANTHROPIC_DEFAULT_<FAMILY>_MODEL, which
# install.sh copies from stack.env into settings.json's env. Two families: no Haiku in the stack.
STACK_MODELS = {"opus", "sonnet"}
# A specific Claude model ID (claude-<family>-<version>[-<date>]). Allowed only in the
# places below: lib/stack.env.example (the single source), PREVIOUS_GIT_COMMITS.md (the pre-publication
# history, quoted as committed), the installer's migration list of old IDs
# (the OLD_DEFAULTS line), the record of the models the token limits were measured on (doctor.sh's
# MEASURED_MODELS line), and legacy/ (byte-exact templates of released versions the installer
# recognizes on upgrade; none kept today, install.sh still reads one). Untracked files and anything
# under .claude-work/ (agents' scratch, some of it force-committed) are not scanned.
# new style (claude-<family>-<n>...) and old style (claude-<n>[-<n>]-<family>-<date or latest>)
MODEL_ID_RE = re.compile(r"claude-(?:(?:opus|sonnet|haiku|fable)-\d|\d(?:-\d)?-(?:opus|sonnet|haiku))")
# the second: this regex's test vectors; the effort table records which model IDs take which
# effort levels (Claude Code's own checks), and its test's vectors
MODEL_ID_FILES = {"lib/stack.env.example", "tests/test_lint_skills.py", "dot-claude/hooks/agent_effort.json",
                  "tests/test_override_agent.py", "PREVIOUS_GIT_COMMITS.md"}
MODEL_ID_DIRS = ("legacy/",)
# the usage/limits/budget tests: synthetic transcript model IDs and the model matcher's vectors, on
# module-level constant lines only (NAME[, NAME...] = "...")
MODEL_ID_CONST = re.compile(r'^[A-Z][A-Z0-9_]*(?:, [A-Z][A-Z0-9_]*)* = "')
MODEL_ID_LINES = {"install.sh": re.compile(r"^OLD_DEFAULTS = "),
                  "dot-claude/bin/doctor.sh": re.compile(r'^MEASURED_MODELS="'),
                  "tests/test_stack_usage.py": MODEL_ID_CONST, "tests/test_stack_limits.py": MODEL_ID_CONST,
                  "tests/test_stack_budget.py": MODEL_ID_CONST}
VALID_MEMORY = {"user", "project", "local"}
ANTHROPIC_DOC_SKILLS = {"docx", "xlsx", "pptx", "pdf"}
KNOWN_PLACEHOLDERS = {
    "__CLAUDE_DIR__", "__HOME__", "__PYTHON3__", "__UV__", "__UVX__", "__NPX__",
    "__NODE__", "__MAGG__", "__HUETENSION__", "__STACK_REPO__", "__STACK_STATE__",
}
TASK_TOOL_RE = re.compile(r"^Task(Create|Get|Update|List|Output)$")
# what a delegate-only main thread needs: dispatch, resume, stop, list, ask, plan exit, tool and skill lookup
BLACKCAT_DELEGATION_TOOLS = {"Agent", "SendMessage", "TaskStop", "ListAgents", "AskUserQuestion",
                             "ExitPlanMode", "ToolSearch", "Skill"}
PLACEHOLDER_RE = re.compile(r"__[A-Z_]+__")
INSTALL_SH = REPO_ROOT / "install.sh"

# maxTurns tiers (a runaway bound, not a budget): every agent at most MAX_TURNS_CAP; the agents whose
# work is iterative by nature (coordination, the implementer escalation chain) may go higher than
# the bounded set, which stays below BOUNDED_TURNS_LIMIT. blackcat has none: as the main thread its
# hard cap is the hook's BLACKCAT_MAX_STEPS, and frontmatter maxTurns does not bind a main thread.
MAX_TURNS_CAP = 350
BOUNDED_TURNS_LIMIT = 200
ITERATIVE_AGENTS = {"orchestrator", "main-coder", "ninja-coder", "supreme-coder"}

# Python runs through uv in agent and skill text: a bare `python`, `python3`, `pip` or `pip3` used as
# a command (at the start of a line or command, after a backtick, `$`, `(`, `;`, `|`, `&` or `--`).
# `uv run python`, `uvx`, path-qualified interpreters (the hooks' /usr/bin/python3, the stack's
# uv-built venvs) and ```python fences don't match.
BARE_PY_RE = re.compile(r"(?:^|[`(;|&$]|--(?=[ \t]))[ \t]*(python3?|pip3?)[ \t]+(?=\S)", re.M)
# (path relative to dot-claude/, substring of the line) pairs a bare interpreter is right for
BARE_PY_ALLOW = [
]

errors = []
# Agents' scratch and hand-off notes (rules: Files & safety); never linted, tracked or not, at any depth.
WORK_DIR = ".claude-work"


def under_work_dir(path, root=None):
    """True when `path` has a .claude-work component below `root`. Only the part below root counts:
    a checkout that itself sits inside some .claude-work/ still lints its own files. `path` may be
    relative to root (git ls-files), built on a relative root, or absolute under root as given,
    absolute or resolved (a symlinked checkout). Lexical: a shipped file that is a symlink stays linted."""
    p, r = Path(path), Path(REPO_ROOT if root is None else root)
    if not p.is_absolute():
        try:
            p = p.relative_to(r)
        except ValueError:
            pass
        return WORK_DIR in p.parts
    for base in (r.absolute(), r.resolve()):
        try:
            return WORK_DIR in p.relative_to(base).parts
        except ValueError:
            continue
    return False


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


EDIT_TOOLS = {"Write", "Edit", "MultiEdit", "NotebookEdit"}


def permission_mode_problem(data):
    """Why an agent file's `permissionMode` is not allowed, else None. The docs (sub-agents.md,
    permission-modes.md, fetched 2026-10-03): with the parent in bypassPermissions, acceptEdits or
    auto the parent's mode wins; with the parent in plan, default or dontAsk the agent file's value
    wins (bypassPermissions excepted). So the file decides a subagent's mode in a Plan session (the
    stack's default): builders (Write/Edit in tools) carry acceptEdits so their subagent runs never
    stop at an edit prompt, read-only agents may carry plan (it only tightens), and nothing else."""
    if "permissionMode" not in data:
        return None
    mode = (get_inline(data, "permissionMode") or "").strip("\"'")
    flat, _ = get_tools(data)
    can_edit = not flat or bool(EDIT_TOOLS & set(flat))      # no tools: line = every tool
    if mode == "acceptEdits":
        return None if can_edit else (
            "permissionMode: acceptEdits on an agent without Write/Edit/NotebookEdit: a read-only agent "
            "declares no acceptEdits (plan, or nothing, which inherits the parent's mode)")
    if mode == "plan":
        return None if not can_edit else (
            "permissionMode: plan on an agent with Write/Edit: as a subagent it could never edit "
            "(subagents in plan are read-only); builders carry acceptEdits")
    return (f"permissionMode: {mode or '(not an inline value)'!r} is not allowed: only acceptEdits (agents "
            "with Write/Edit) or plan (read-only agents). An agent file's mode wins over a parent in plan, "
            "default or dontAsk (the docs; bypassPermissions excepted), so default, auto, dontAsk or "
            "bypassPermissions here would change what that agent may do in a Plan session")


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


# skillOverrides values (code.claude.com/docs/en/skills.md, "Override skill visibility from settings"):
# "on" lists name and description, "name-only" the name, "user-invocable-only" and "off" nothing.
OVERRIDE_STATES = {"on", "name-only", "user-invocable-only", "off"}
# Skill-listing budget (see main()): what shares it besides the stack's own skills, 2026-10-02.
# Plugins the installer enables (measured from their SKILL.md files, entries "- name: description" cut
# at skillListingMaxDescChars 500): document-skills docx/xlsx/pptx/pdf 2,032, math-olympiad 531,
# skill-creator 350; the LSP plugins have no skills. Bundled Claude Code skills (dataviz, artifact-*,
# update-config, loop, schedule, claude-api, workflow-authoring, run, plugin-authoring): ~3,950,
# estimated from a 2.1.287 session's listing. claude.ai-synced skills (anthropic-skills:*, only in
# sessions signed in to claude.ai; the stack can't see them): ~7,300 margin, estimated likewise.
NON_STACK = {"plugins": 2_913 + 6, "bundled (est.)": 3_950, "claude.ai synced (est. margin)": 7_300}
NON_STACK_LISTING = sum(NON_STACK.values())
LISTING_NOTE = ("0.012 set 2026-10-02 from stack 14,564 (83 hub modules hidden) + non-stack %d = %d chars "
                "plus 25%%; see tests/prompt_budget.py SKILL_BUDGET" % (NON_STACK_LISTING, 14_564 + NON_STACK_LISTING))


def skill_listing_entry(name, desc_len, override="on", desc_cap=1536, model_invocable=True):
    """Characters one skill adds to the skill listing every agent sees (separators not counted).
    As Claude Code 2.1.287 builds it: "- <name>: <description>" (name + 4 + description cut at
    skillListingMaxDescChars) and "- <name>" (name + 2) for a "name-only" skill."""
    if not model_invocable or override in ("user-invocable-only", "off"):
        return 0
    if override == "name-only":
        return len(name) + 2
    return len(name) + 4 + min(desc_len, desc_cap)


def skill_names():
    return {d.name for d in SKILLS_DIR.iterdir() if (d / "SKILL.md").is_file()}


FORCED_LOAD_RES = [
    re.compile(r"(?i)\b(?:always|must|first)\s+(?:load|invoke)\b[^.;\n]*"),
    re.compile(r"(?i)\b(?:load|invoke)\b[^.;\n]{0,80}`[a-z0-9-]+`\*?[^.;\n(]{0,40}\bfirst\b"),
    re.compile(r"(?i)\b(?:load|invoke)\s+(?:it\s+|them\s+)?(?:always|on every task|every time)\b"),
    re.compile(r"(?i)\bevery\s+\w+:\s*load\b[^.;\n]*"),
]
# The five reviewers load review-protocol on every review: each of their tasks is a review, and the
# protocol holds the VERDICT format and the severity rubric their one-line evidence gate refers to (the
# user asked for that gate in reviewer and verifier prompts). Their "Every review: load ..." trigger is
# situational, so only these files may use it; no other forced-load wording is allowed anywhere.
FORCED_LOAD_OK = {"code-reviewer.md": [3], "plan-reviewer.md": [3], "security-auditor.md": [3],
                  "verifier.md": [3], "proof-checker.md": [3]}


def hidden_skills():
    """Shipped skills skillOverrides keeps out of the listing ("user-invocable-only" or "off"): hub
    modules an agent Reads at <config>/skills/<name>/SKILL.md (the Skill tool refuses them)."""
    try:
        so = json.loads(SETTINGS.read_text()).get("skillOverrides") or {}
    except (OSError, ValueError):
        return set()
    return {k for k, v in so.items() if v in ("user-invocable-only", "off")} & skill_names()


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
    elif model not in STACK_MODELS:
        fail(f"{path.name}: model {model!r} — every agent names a family alias, one of "
             f"{sorted(STACK_MODELS)}: the specific ID comes from ANTHROPIC_DEFAULT_<FAMILY>_MODEL "
             "(stack.env)")

    # effort
    effort = get_inline(data, "effort")
    if effort is not None and effort not in VALID_EFFORTS:
        fail(f"{path.name}: invalid effort {effort!r} (expected one of {sorted(VALID_EFFORTS)})")

    # maxTurns tiers
    turns = get_inline(data, "maxTurns")
    if name_from_file == "blackcat":
        if turns is not None:
            fail(f"{path.name}: blackcat must not set maxTurns (the hook's BLACKCAT_MAX_STEPS caps it)")
    elif turns is None or not turns.isdigit():
        fail(f"{path.name}: maxTurns missing or not a whole number ({turns!r})")
    else:
        limit = MAX_TURNS_CAP if name_from_file in ITERATIVE_AGENTS else BOUNDED_TURNS_LIMIT - 1
        if int(turns) > limit:
            tier = "iterative" if name_from_file in ITERATIVE_AGENTS else "bounded"
            fail(f"{path.name}: maxTurns {turns} over the {tier} tier's {limit}")

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

    problem = permission_mode_problem(data)
    if problem:
        fail(f"{path.name}: {problem}")

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
        # BlackCat only delegates: no work tool on its line (hook-independent), the delegation set present
        work = sorted({"Bash", "Write", "Edit", "NotebookEdit"} & set(flat_tools))
        if work:
            fail(f"{path.name}: blackcat only delegates; drop {work} from tools:")
        missing = sorted(BLACKCAT_DELEGATION_TOOLS - set(flat_tools))
        if missing:
            fail(f"{path.name}: blackcat tools: lacks delegation tools {missing}")
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
    # skills are looked up when a step needs them (the user, 2026-10-02: "## Skills are not always on,
    # required, just looked up if needed"): no body forces a load on every task
    for i, rx in enumerate(FORCED_LOAD_RES):
        if i in FORCED_LOAD_OK.get(path.name, []):
            continue
        for m in rx.finditer(body):
            fail(f"{path.name}: {m.group(0)!r} forces a skill load; name the situation instead "
                 "(\"`x` for <situation>\", \"If needed: …\")")
    for m in re.finditer(r"`([a-z0-9-]+)`\*?,? first\b", body):
        if m.group(1) in skill_names():
            fail(f"{path.name}: {m.group(0)!r} forces a skill load first; name the situation instead")
    # a skill hidden from the listing (skillOverrides user-invocable-only/off) is Read by path, and the
    # Skill tool refuses it: the body marks it `name`* (the rules explain the mark); a listed one is unmarked
    hidden, shipped = hidden_skills(), skill_names()
    for m in re.finditer(r"`([a-z0-9-]+)`(\*?)", body):
        s, star = m.group(1), m.group(2)
        if s in hidden and not star:
            fail(f"{path.name}: `{s}` is hidden from the skill listing; write `{s}`* (read by path)")
        elif star and s in shipped and s not in hidden:
            fail(f"{path.name}: `{s}`* is marked hidden but the skill is listed; drop the *")


def installer_copy_types():
    """COPY_TYPES as install.sh declares it (the tuple of base agent types that get a -copy)."""
    m = re.search(r"(?m)^COPY_TYPES = \(([^)]*)\)", INSTALL_SH.read_text())
    if not m:
        fail("install.sh: no COPY_TYPES = (...) line")
        return []
    return re.findall(r'"([a-z0-9-]+)"', m.group(1))


def check_copy_policy(policy_row, copy_bases, hook_copy_of):
    """One generation of copies as a static policy: <base> lists <base>-copy and not itself; a copy's
    row is the base row minus the base and every copy; nobody else lists a copy; no other agent
    lists its own type. `hook_copy_of` is agent_guard's COPY_OF ({base: copy}, `copy_types` in
    --print-policy); the hook keeps AGENTS to the shipped files and adds the copies as POLICY rows."""
    copies = {b + "-copy" for b in copy_bases}
    for b in copy_bases:
        c = b + "-copy"
        if hook_copy_of.get(b) != c:
            fail(f"copy type {c}: missing from agent_guard COPY_OF/copy_types (the hook would not know it)")
        base_row, copy_row = policy_row.get(b), policy_row.get(c)
        if base_row is None or copy_row is None:
            fail(f"copy type {c}: agent_guard POLICY needs rows for {b} and {c}")
            continue
        if c not in base_row or b in base_row:
            fail(f"POLICY[{b}] must list {c} and not {b} (copies are their own type)")
        want = sorted(x for x in base_row if x != b and x not in copies)
        if sorted(copy_row) != want:
            fail(f"POLICY[{c}] {sorted(copy_row)} != POLICY[{b}] minus {b} and copies {want}")
    for parent, row in policy_row.items():
        if parent in row:
            fail(f"POLICY[{parent}] lists {parent} itself: only copy types may run copies")
        base = parent[:-len("-copy")] if parent in copies else parent
        for c in copies & set(row):
            if c != base + "-copy" or parent in copies:
                fail(f"POLICY[{parent}] lists {c}: only {c[:-len('-copy')]} may spawn it")


def check_bare_python():
    """Agent and skill text runs Python through uv (rules: Tools); see BARE_PY_RE / BARE_PY_ALLOW."""
    root = REPO_ROOT / "dot-claude"
    paths = sorted(AGENTS_DIR.glob("*.md")) + sorted(SKILLS_DIR.rglob("*.md"))
    for p in paths:
        if under_work_dir(p):
            continue
        rel = p.relative_to(root).as_posix()
        for n, line in enumerate(p.read_text().splitlines(), 1):
            if not BARE_PY_RE.search(line):
                continue
            if any(rel == a and s in line for a, s in BARE_PY_ALLOW):
                continue
            fail(f"{rel}:{n}: bare python/pip command — use uv (`uv run`, `uv run --with`, `uvx`, "
                 f"`uv add`, `uv pip` in a uv venv) or add a reasoned BARE_PY_ALLOW entry: {line.strip()[:120]}")


# Skills folded into a hub, another skill or a references/ file (git log --diff-filter=D on
# dot-claude/skills/*/SKILL.md, 2026-10-02). Text that still names one sends an agent to a skill that no
# longer loads. The one allowed mention is a provenance note: "(was the `x` skill)". Add a name here
# whenever a skill directory is removed.
RETIRED_SKILLS = frozenset("""
audio-analysis audio-dsp audio-plugins compiler-backend-jit compiler-frontend compiler-ir-llvm
compiler-types diag-graphviz-d2 diag-mermaid diag-tikz ffmpeg-audio-subs ffmpeg-edit ffmpeg-encode
fm-rust-kani-miri fm-smt-z3 fm-tla geo-crs-gdal geo-raster-vector geo-tiles-webmaps git-history-edit
git-large-repos git-recovery-bisect git-worktrees l10n-qa linux-desktop-btrfs macos-dmg-sparkle-brew
macos-sign-notarize mcp-http-release mcp-python-server mcp-ts-server net-protocols net-vpn-firewall
num-optimization ops-runbooks quant-backtesting quant-pricing quant-risk sec-local-servers
sec-threat-model test-mutation viz-interactive write-articles write-docs-adr write-reports
""".split())
# a references/<name>.md path is a file, not a skill: "/" before or ".md" after does not count
RETIRED_RE = re.compile(r"(?<![\w/-])(%s)(?![\w-]|\.md\b)" % "|".join(sorted(map(re.escape, RETIRED_SKILLS))))
PROVENANCE_RE = re.compile(r"was the `[a-z0-9-]+` skill")


def check_model_ids(root=REPO_ROOT):
    """No specific Claude model ID in a tracked file outside the allowed places (MODEL_ID_*)."""
    try:
        files = subprocess.run(["git", "-C", str(root), "ls-files", "-z"], capture_output=True,
                               check=True).stdout.decode().split("\0")
    except (OSError, subprocess.CalledProcessError):     # an export without .git: walk the tree
        files = [str(p.relative_to(root)) for p in root.rglob("*")
                 if p.is_file() and ".git" not in p.relative_to(root).parts]
    found = []
    for rel in filter(None, files):
        if under_work_dir(rel, root) or rel in MODEL_ID_FILES or rel.startswith(MODEL_ID_DIRS):
            continue
        try:
            text = (root / rel).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        allowed = MODEL_ID_LINES.get(rel)
        for n, line in enumerate(text.splitlines(), 1):
            if MODEL_ID_RE.search(line) and not (allowed and allowed.search(line)):
                found.append(f"{rel}:{n}")
    return found


def stale_skill_refs(text):
    """Retired skill names in `text`, outside "(was the `x` skill)" provenance notes."""
    return sorted(set(RETIRED_RE.findall(PROVENANCE_RE.sub("", text))))


def check_stale_skill_refs():
    """No agent, skill, reference or rules file names a skill that was folded away."""
    root = REPO_ROOT / "dot-claude"
    shipped = skill_names()
    for name in sorted(RETIRED_SKILLS & shipped):
        fail(f"RETIRED_SKILLS lists {name!r}, which is shipped under {SKILLS_DIR}")
    paths = (sorted(AGENTS_DIR.glob("*.md")) + sorted(SKILLS_DIR.rglob("*.md"))
             + sorted((root / "rules").glob("*.md")))
    for p in paths:
        if under_work_dir(p):
            continue
        for n, line in enumerate(p.read_text().splitlines(), 1):
            for old in stale_skill_refs(line):
                if old in shipped:
                    continue
                fail(f"{p.relative_to(root).as_posix()}:{n}: names retired skill {old!r} — point to the "
                     "skill or references/ file that absorbed it")


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

    # Copy types: install.sh renders <base>-copy.md from <base>.md, so the repo has no file for them.
    copy_bases = installer_copy_types()
    hook_copy_of = policy_data.get("copy_types") or {}
    if not isinstance(hook_copy_of, dict):
        hook_copy_of = {b: b + "-copy" for b in hook_copy_of}
    if set(hook_copy_of) != set(copy_bases):
        fail(f"copy types: agent_guard {sorted(hook_copy_of)} != install.sh COPY_TYPES {sorted(copy_bases)}")
    copy_names = {b + "-copy" for b in copy_bases}
    check_copy_policy(policy_row, copy_bases, hook_copy_of)
    # leaves by decision (a review or an image job is one bounded task); planner keeps delegation
    for a in ("plan-reviewer", "image-director"):
        if a not in leaves or policy_row.get(a):
            fail(f"{a} must be a leaf (empty POLICY row, in LEAVES)")
    if not policy_row.get("planner"):
        fail("planner must keep a non-empty POLICY row (it keeps Agent + SendMessage)")

    files = sorted(AGENTS_DIR.glob("*.md"))
    for f in files:
        if f.stem in copy_names:
            fail(f"{f.name}: a copy type is rendered by install.sh from its base agent; don't ship the file")
    if expected_agents is not None:
        got_names = {f.stem for f in files}
        want_names = set(expected_agents) - copy_names
        if got_names != want_names:
            fail(
                f"agent file set {sorted(got_names)} != policy agents without copies {sorted(want_names)}"
            )

    blackcat_tools = policy_data.get("blackcat_tools")
    for f in files:
        check_agent_file(f, policy_row, leaves, builtins, blackcat_tools)

    check_bare_python()
    check_stale_skill_refs()

    # every model-invocable skill is pre-approved, or background agents hit permission prompts
    try:
        allow = set(json.loads(SETTINGS.read_text()).get("permissions", {}).get("allow", []))
    except (OSError, ValueError) as exc:
        fail(f"settings.json unreadable: {exc}")
        allow = set()
    agents = set(expected_agents or [])
    try:
        desc_cap = int(json.loads(SETTINGS.read_text()).get("skillListingMaxDescChars", 1536))
    except (OSError, ValueError, TypeError):
        desc_cap = 1536
    try:
        overrides = json.loads(SETTINGS.read_text()).get("skillOverrides") or {}
    except (OSError, ValueError):
        overrides = {}
    if not isinstance(overrides, dict):
        fail("settings.json skillOverrides is not an object")
        overrides = {}
    for k, v in sorted(overrides.items()):
        if v not in OVERRIDE_STATES:
            fail(f"settings.json skillOverrides[{k!r}] = {v!r}: not one of {sorted(OVERRIDE_STATES)}")
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
        entry = skill_listing_entry(s, len(d.group(1).strip()) if d else 0, overrides.get(s, "on"), desc_cap)
        if entry:
            listing.append(entry)
        if overrides.get(s) in ("user-invocable-only", "off"):
            continue
        if "Skill" not in allow and f"Skill({s})" not in allow:
            fail(f"settings.json permissions.allow lacks Skill (or Skill({s})) — agents loading it on "
                 "demand would stop at a permission prompt")
    # Claude Code lists every skill (name + description) to every agent within a character budget of
    # context window x chars per token x skillListingBudgetFraction (default 0.01). Claude Code 2.1.287
    # counts 3 characters per token for the 5.5 models (4 for older ones); every agent here runs a
    # 1M-context model. Over the budget it drops the descriptions of the least-used skills, silently.
    # The same budget holds plugin, bundled and claude.ai skills (NON_STACK_LISTING, measured), so the
    # stack's own listing must leave that much room.
    try:
        frac = float(json.loads(SETTINGS.read_text()).get("skillListingBudgetFraction", 0.01))
    except (OSError, ValueError, TypeError):
        frac = 0.01
    used, budget = sum(listing) + max(0, len(listing) - 1), int(1_000_000 * 3 * frac)
    if used + NON_STACK_LISTING > budget:
        fail(f"skill listing is {used} characters; with {NON_STACK_LISTING} for plugin, bundled and "
             f"claude.ai skills that is over the {budget}-character budget (skillListingBudgetFraction="
             f"{frac}; {LISTING_NOTE}): Claude Code would drop descriptions silently. Shorten or merge "
             "skills, or raise the fraction by the overflow plus ~3%")

    for where in check_model_ids():
        fail(f"{where}: a specific Claude model ID — name the alias (opus, sonnet) or read "
             "ANTHROPIC_DEFAULT_<FAMILY>_MODEL; the IDs live in lib/stack.env.example only")

    if errors:
        print(f"lint_agents: {len(errors)} failure(s):", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        sys.exit(1)

    print("lint_agents: ok")
    sys.exit(0)


if __name__ == "__main__":
    main()
