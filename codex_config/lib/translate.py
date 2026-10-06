"""Claude → Codex text pass for agent bodies and skill files (DESIGN.md §8.2). Stdlib only, Python ≥ 3.11.

    translate_text(text, label, ctx) -> (translated_text, problems)

`problems` lists "<label>:<line>: <token>" for every Claude tool reference left without a Codex
mapping, every forbidden enforcement phrase and every unknown `__PLACEHOLDER__`; the build fails on
any. `stats(...)` gives the counters of one call (references mapped, phrase rewrites, paths).

What counts as a Claude tool reference (outside fenced code blocks unless noted):
  R1  a DISTINCT name anywhere, as a whole word (CamelCase names that are no English word:
      SendMessage(s), TaskStop, WebSearch, AskUserQuestion, …; also `subagent_type`,
      `run_in_background` and the `isolation: "worktree"` parameter in an inline code span).
  R2  a COMMON name (Read, Write, Edit, Glob, Grep, Bash, Monitor, Agent, Task, Skill, LSP, Artifact,
      Workflow), capitalized exactly, only in one of these contexts:
      a. an inline code span holding just the name, or the name with an argument list: `Read`, `Agent(x)`;
      b. the name directly followed by "(": Agent(general-purpose), Bash(git push *);
      c. the name followed by " tool(s)" or " call(s)": "the Skill tool", "Agent calls";
      d. a tool list: the name joined to another tool name by ", ", "/", " and ", " or ";
      e. mid-sentence use as a verb or noun: preceded by a lowercase word or a determiner
         ("then Read the PNG", "each Read", "on a Monitor until-loop", "An Artifact"), or alone in
         parentheses "(Monitor)" (LSP, an acronym of the protocol, never by this rule);
      Exceptions (proper nouns, UI labels): KEEP_PHRASES ("Read the Docs", "Edit Mode",
      "Agent SDK", "Perf Monitor", …) and anything followed by "-" ("Read-only").
  Plain English at a sentence or cell start ("Read the file", "Monitor progress", "Workflow"
  headings, "LSP spec 3.18") is no reference and is left alone.

Order of the pass, per line: placeholders and `~/.claude` paths (everywhere, code included) →
PHRASES (explicit sentence rewrites: hook-enforcement claims to DESIGN §5's status column, dropped
tools, idioms) → token mapping (TOOL_MAP) → the forbidden-phrase lint (FORBIDDEN). A dropped tool
(DROPPED: ToolSearch, LSP, Artifact, Workflow, Cron*, …) has no token mapping: a sentence naming it
must be rewritten by PHRASES, else it is reported. Files under `verbatim=True` (skills whose subject
is Claude Code itself) get only the placeholder pass, with `__CLAUDE_DIR__` → `~/.claude` (the Claude
install they describe).

Seeded-bug proofs (tests/test_translate.py; tests/mutations/translate.json): an unmapped token
silently passed (the problem append dropped); fenced code no longer skipped; the article-aware
"shell" form dropped; a forbidden phrase not reported; `__CLAUDE_DIR__/skills/<module>` sent to
skills/ instead of skill-modules/.
"""
from __future__ import annotations

import re

__all__ = ["BuildError", "translate_text", "render_placeholders", "TOOL_MAP", "DISTINCT", "COMMON",
           "DROPPED", "PHRASES", "FORBIDDEN", "Stats"]


class BuildError(Exception):
    """An input the converter cannot translate (the build stops)."""


# ---------------------------------------------------------------- vocabulary
# DISTINCT: never English words, so any whole-word occurrence is a tool reference (an optional s/d
# suffix covers "SendMessages"/"SendMessaged").
DISTINCT = (
    "AskUserQuestion", "BashOutput", "CronCreate", "CronDelete", "CronList", "EnterPlanMode",
    "EnterWorktree", "ExitPlanMode", "ExitWorktree", "KillShell", "ListAgents", "MultiEdit",
    "NotebookEdit", "PushNotification", "RemoteTrigger", "ScheduleWakeup", "SendMessage",
    "SendUserFile", "SubagentHandback", "TaskCreate", "TaskGet", "TaskList", "TaskOutput", "TaskStop",
    "TaskUpdate", "TodoWrite", "ToolSearch", "WebFetch", "WebSearch", "subagent_type",
    "run_in_background",
)
# COMMON: also English words; references only in the contexts of the module docstring (R2).
COMMON = ("Agent", "Artifact", "Bash", "Edit", "Glob", "Grep", "LSP", "Monitor", "Read", "Skill",
          "Task", "Workflow", "Write")
# Claude tools Codex has no counterpart for: a sentence naming one is rewritten (PHRASES), never mapped.
DROPPED = ("ToolSearch", "LSP", "Artifact", "Workflow", "CronCreate", "CronDelete", "CronList", "Cron*",
           "ScheduleWakeup", "RemoteTrigger", "PushNotification", "SendUserFile", "ListAgents",
           "ExitPlanMode", "EnterPlanMode")

# Codex text per tool (DESIGN §8.2). "tool": the form for a named tool (backticks, lists, "X tool");
# "prose": mid-sentence use (R2e); "bare": after an article ("a Bash heredoc" → "a shell heredoc").
_WEB_SEARCH = "`mcp__jina__search_web` or `mcp__exa__web_search_exa`"
_WEB_FETCH = "`mcp__jina__read_url`"
TOOL_MAP = {
    "Read": {"tool": "`sed -n`/`cat`", "prose": "read"},
    "Glob": {"tool": "`rg --files`"},
    "Grep": {"tool": "`rg`"},
    "Write": {"tool": "`apply_patch`"},
    "Edit": {"tool": "`apply_patch`"},
    "MultiEdit": {"tool": "`apply_patch`"},
    "NotebookEdit": {"tool": "`apply_patch`"},
    "Bash": {"tool": "the shell", "bare": "shell"},
    "Monitor": {"tool": "background exec with polling", "bare": "polling loop"},
    "Agent": {"tool": "`spawn_agent`"},
    "Task": {"tool": "`spawn_agent`"},
    "subagent_type": {"tool": "`agent_type`"},
    "SendMessage": {"tool": "`send_input`"},
    "TaskStop": {"tool": "`close_agent`"},
    "SubagentHandback": {"tool": "the final report that ends your turn"},
    "Skill": {"tool": "the skill's SKILL.md (its path is in the skills list)"},
    "WebSearch": {"tool": _WEB_SEARCH},
    "WebFetch": {"tool": _WEB_FETCH},
    "EnterWorktree": {"tool": "`git worktree add`"},
    "ExitWorktree": {"tool": "`git worktree remove`"},
    "AskUserQuestion": {"tool": "`request_user_input` (if enabled; else ask in your reply)"},
    "TodoWrite": {"tool": "`update_plan`"},
    "TaskCreate": {"tool": "`update_plan`"},
    "TaskUpdate": {"tool": "`update_plan`"},
    "TaskList": {"tool": "`update_plan`"},
    "TaskGet": {"tool": "`update_plan`"},
    "TaskOutput": {"tool": "the background job's output"},
    "BashOutput": {"tool": "the background job's output"},
    "KillShell": {"tool": "`kill`"},
    "run_in_background": {"tool": "background exec"},
}
# plural / verb forms of DISTINCT names keep their suffix after the mapped text only where natural
_SUFFIX_OK = {"SendMessage": {"s": "`send_input`", "d": "`send_input`"}}

# Proper nouns and UI labels that contain a COMMON name but are no tool reference.
KEEP_PHRASES = re.compile(
    r"Read the Docs|Edit Mode|Edit\s*>|Edit menu|Perf Monitor|Activity Monitor|System Monitor|"
    r"(?:Claude )?Agent SDK|Agent Skills|Task Scheduler|Task Manager|GitHub Workflow|Artifact Registry|"
    r"Workflow managers|Bash sandbox|Allow Scripts to Write Files|Subtitle Edit")

# ---------------------------------------------------------------- explicit sentence rewrites
# (regex, replacement). Applied in order to every non-fenced line before the token pass. Enforcement
# claims follow DESIGN §5's status column: E/E* → "guard-enforced in the `codex` profile" (the guard
# runs only in that profile and only after /hooks trust); A → advisory wording.
_GUARD = "guard-enforced in the `codex` profile"
PHRASES = [
    # read-only roles (§5: E*)
    (r"\(hook-enforced Bash", "(%s: read-only shell commands, no `apply_patch`" % _GUARD),
    (r"\(hook-enforced\)", "(%s)" % _GUARD),
    (r"hook-enforced", _GUARD),
    # BlackCat main-thread gate (§5: E*): ≤ 3 read-only shell calls per prompt; no step cap ported
    (r"Hook caps per prompt: 24 tool calls, ≤ 3 Read\.",
     "Guard limit per prompt: at most 3 read-only shell calls."),
    (r"Bash, Write and Edit are not your tools", "the shell and `apply_patch` are not your tools"),
    (r"a prompt's Agent calls in one message, before any Read",
     "a prompt's `spawn_agent` calls in one message, before any read"),
    (r"\(Read the ledger: path in the hook's dispatch note, else",
     "(read the ledger:"),
    (r"One AskUserQuestion call; no question tool → plain text, end the turn\.",
     "One `request_user_input` call if enabled; else ask in plain text and end the turn."),
    (r"5\. Plan mode: planner, relay its plan, ExitPlanMode with it; builders edit even in Plan, so only once approved\.",
     "5. Planning first: planner, relay its plan, and dispatch builders only once the user approves it."),
    (r"- Workflow: only when the user asks, types `ultracode`, runs a saved one, or the job needs dozens of agents; "
     r"every `agent\(\)` names a literal `agentType` from your list, a self-contained prompt, no `model`\.",
     "- Jobs needing dozens of agents go to one orchestrator call."),
    (r"- Cron\*, ScheduleWakeup, RemoteTrigger, PushNotification: only on request\. SendUserFile hands over a file\.",
     "- Scheduling, remote triggers and notifications do not exist here: say so when asked."),
    (r"- Skill: only one the user names that drives your own tools \(/loop, /schedule\); "
     r"work needing any other skill goes to its specialist\.",
     "- Skills: work needing a skill goes to its specialist."),
    # dropped tools in role bodies
    (r"; LSP for definitions and diagnostics\.", "; the compiler or type checker for diagnostics."),
    (r"; LSP when a language server is active\.", "."),
    (r"Use LSP when a language server is active[^.;]*[.;]?", ""),
    (r" An Artifact only when the user asks for a shareable page\.", ""),
    (r"Glob for file names, Grep for symbols and strings",
     "`rg --files` for file names, `rg` for symbols and strings"),
    # idioms
    (r"(?:on |with )?a Monitor until-loop", "with a polling loop on a background job"),
    (r"watched with Monitor", "watched by polling"),
    (r"watch them with Monitor", "watch them by polling"),
    (r"\(Monitor\)", "(background exec, polled)"),
    (r"TaskStop what you started", "kill what you started"),
    (r"stop a runaway job with TaskStop", "kill a runaway job"),
    (r"Bash timeout 600000 or run_in_background", "a long shell timeout or background exec"),
    (r"`isolation: \"worktree\"`", "separate `git worktree`s"),
    (r"→ EnterWorktree", "→ a `git worktree`"),
    (r"`\*` = not in the skill listing: Read `([^`]*)/SKILL\.md` \(the Skill tool won't load it\)\.",
     r"`*` = a module, not in the skills list: open `\1/SKILL.md` (path in its row)."),
    (r"\(the Skill tool won't load it\)", "(not in the skills list)"),
    (r"`([a-z0-9:-]+)` with the Skill tool", r"`\1` (open its SKILL.md)"),
    (r"with the Skill tool by name(?: \(a plugin's as `plugin:skill`\))?", "by opening its SKILL.md"),
    (r"through the Skill tool by name", "by opening its SKILL.md"),
    (r"the Skill tool refuses them", "they are not in the skills list"),
    (r"BlackCat asks with AskUserQuestion", "the main thread asks the user"),
    (r"BlackCat SendMessages its L1 child", "the main thread sends the answer to its L1 child (`send_input`)"),
    (r"Agents without the Agent tool are leaves", "Agents that cannot spawn are leaves"),
    (r"TaskStop ends a runaway subagent\.", "`close_agent` ends a runaway subagent."),
    (r" As a main thread \(`claude-ninja`\), each Workflow `agent\(\)` call names an `agentType` from your "
     r"spawn list and no `model`\.", ""),
    (r" for figures in code and Artifact charts", " for figures in code"),
    (r"Never pass `model` or `run_in_background`\.", "Never pass `model` or `reasoning_effort`."),
    (r"Use LSP when a code-intelligence plugin is installed and `grep`/`find` through Bash "
     r"\(Claude Code's shell runs fast embedded versions\)", "Search with `rg` and `rg --files` through the shell"),
    (r"\(the global Git rule, hook-enforced\)",
     "(the global Git rule; Codex's global rules forbid pushes, and the guard blocks them in the `codex` profile)"),
    (r"Per-call caps \(results, characters, pages, depth\) and Spider's anti-bot defaults are applied by a hook "
     r"\(`hooks/web_caps\.py`, values in stack\.env\); a changed call says so in its context\. In the user's "
     r"opt-in polite mode \(`SPIDER_ANTIBOT=0`\) it instead enforces robots\.txt, a 1 s crawl delay and "
     r"concurrency 2, and refuses Spider's bypass tools and options\.",
     "The Claude stack's per-call web caps (`hooks/web_caps.py`) are not ported to Codex: keep result counts, "
     "page sizes and crawl depth small yourself; the `codex` profile's guard caps MCP calls per session."),
    # delegation reference (DESIGN §5: spawn rows E*, fan-out E, MCP cap E, resume P, depth native, tokens P/A)
    (r"The hook enforces the May-spawn lists, fan-out, tokens, MCP calls and who may resume a finished agent, "
     r"Claude Code the depth \(L8 cannot spawn\);",
     "In the `codex` profile the guard enforces the May-spawn lists, fan-out and MCP calls and checks resumes "
     "against the spawn tree it records; `agents.max_depth` sets the depth (L8 cannot spawn); token budgets "
     "are advisory;"),
    (r"≤ 8 per prompt \(hook\)", "≤ 8 per prompt (guard, `codex` profile)"),
    (r"cannot spawn \(hook\)", "cannot spawn (`agents.max_depth`)"),
    (r"; the hook enforces only prompt and session totals and measures the share in context tokens "
     r"\(`stack-budget`'s unit\) or `N calls`\.",
     "; nothing enforces token shares in Codex, so measure the share in context tokens or `N calls`."),
    (r"\(the hook refuses a name from a subagent\)",
     "(in the `codex` profile the guard checks `send_input` targets against its spawn tree)"),
    (r"^- `stack-who` \(.*it is not a directory for messaging\.$",
     "- No live agent-tree view is ported to Codex; the job's `plan.md` is the record of who runs what."),
    (r"Charts built as Artifacts, React/HTML pages", "Charts built as React/HTML pages"),
    (r"Charts as Claude Artifacts or chat-surface dashboards", "Charts as chat-surface dashboards"),
    (r"hand-drawn inline-SVG diagrams inside Artifacts → the built-in `artifact-diagramming` skill",
     "hand-drawn inline-SVG diagrams are out of scope here"),
]
PHRASES = [(re.compile(p), r) for p, r in PHRASES]

# Enforcement claims no Codex mechanism backs as written (DESIGN §5): left after the pass → problem.
FORBIDDEN = [re.compile(p) for p in (
    r"(?i)hook-enforced", r"(?i)\bhook caps\b", r"(?i)the hook (?:refuses|denies|blocks|strips|rewrites)",
    r"(?i)the guard refuses", r"(?i)hook-checked", r"SubagentHandback", r"the Skill tool",
)]

_PLACEHOLDER = re.compile(r"__[A-Z][A-Z0-9_]*__")
_FENCE = re.compile(r"^\s*(```|~~~)")
_CODE_SPAN = re.compile(r"`[^`\n]*`")
_DISTINCT_RE = re.compile(r"(?<![\w-])(%s)(s|d)?(?![\w-])" % "|".join(
    sorted((re.escape(n) for n in DISTINCT), key=len, reverse=True)) + r"|(?<![\w-])Cron\*")
_COMMON_RE = re.compile(r"(?<![\w-])(%s)(?![\w])" % "|".join(COMMON))
_TOOL_ANY = set(DISTINCT) | set(COMMON) | {"Cron*"}
_LIST_SEP = re.compile(r"\s*(?:,\s*(?:and\s+|or\s+)?|/|\s+(?:and|or)\s+)\s*\Z")
_LIST_SEP_FWD = re.compile(r"\A\s*(?:,\s*(?:and\s+|or\s+)?|/|\s+(?:and|or)\s+)\s*")
_DETERMINER = re.compile(r"(?i)(?:^|[\s(])(a|an|the|each|every|one|your|its|no|any|this|that)\s+\Z")
_LOWER_WORD = re.compile(r"(?<![\w-])[a-z][\w']*[,;]?\s+\Z")
_ARTICLE = re.compile(r"(?i)(?:^|[\s(])(a|an|each|every|one|your|its|no|any|this|that)\s+\Z")
_CALL_SUFFIX = re.compile(r"\A(?:'s)?\s+(?:tools?|calls?)\b")


class Stats(dict):
    """Counters of one translate_text call: mapped (per token), rewrites, paths, problems."""

    def __init__(self):
        super().__init__(mapped={}, rewrites=0, paths=0, references=0)


# ---------------------------------------------------------------- placeholders and paths
def _skill_target(name: str, ctx: dict) -> str:
    stack = ctx["stack"]
    modules = ctx.get("skill_modules") or ()
    if name == "<name>" or name in modules:
        return "%s/skill-modules/%s" % (stack, name)
    return "%s/skills/%s" % (stack, name)


def render_placeholders(text: str, ctx: dict, verbatim: bool = False):
    """Placeholders and ~/.claude paths → absolute Codex paths (ctx). Returns (text, n, unknown)."""
    n = [0]
    if verbatim:
        claude = "~/.claude"
        out = text.replace("__CLAUDE_DIR__", claude)
        n[0] += text.count("__CLAUDE_DIR__")
    else:
        stack, codex_home = ctx["stack"], ctx["codex_home"]

        def skills(m):
            n[0] += 1
            return _skill_target(m.group(2), ctx) + m.group(3)

        out = re.sub(r"(__CLAUDE_DIR__|~/\.claude|\$HOME/\.claude|\$\{HOME\}/\.claude)/skills/"
                     r"(<name>|[a-z0-9][a-z0-9-]*)(/|\b)", skills, text)

        def env(m):
            n[0] += 1
            return codex_home + "/stack.env"
        out = re.sub(r"(__CLAUDE_DIR__|~/\.claude)/stack\.env", env, out)

        def other(m):
            n[0] += 1
            return stack + m.group(2)
        out = re.sub(r"(__CLAUDE_DIR__|~/\.claude(?![\w.-])|\$HOME/\.claude(?![\w.-])|\$\{HOME\}/\.claude(?![\w.-]))(/?)",
                     other, out)
    simple = {
        "__HOME__": ctx.get("home"), "__STACK_STATE__": ctx.get("state_dir"),
        "__UV__": ctx.get("uv") or "uv", "__UVX__": ctx.get("uvx") or _sibling(ctx.get("uv"), "uvx"),
        "__NPX__": ctx.get("npx") or "npx", "__NODE__": ctx.get("node") or "node",
        "__MAGG__": ctx.get("magg") or "magg", "__HUETENSION__": ctx.get("huetension") or "huetension",
        "__PYTHON3__": ctx.get("python3") or "python3",
        "__STACK_REPO__": ctx.get("stack_repo") or "the claude-agent-stack repository",
    }
    unknown = []
    for m in _PLACEHOLDER.finditer(out):
        if simple.get(m.group()) is None:
            unknown.append(m.group())
    for k, v in simple.items():
        if v is not None and k in out:
            n[0] += out.count(k)
            out = out.replace(k, v)
    return out, n[0], unknown


def _sibling(uv, name):
    if uv and "/" in uv:
        return uv.rsplit("/", 1)[0] + "/" + name
    return name


# ---------------------------------------------------------------- detection
def _mask(line: str) -> str:
    """The line with inline code spans blanked (same length), for the R2 context rules."""
    return _CODE_SPAN.sub(lambda m: " " * len(m.group()), line)


def _find_refs(line: str):
    """[(start, end, token, form)] of Claude tool references in one non-fenced line.
    form: "tool" | "prose" | "call" (token followed by an argument list) ."""
    refs = []
    masked = _mask(line)
    keep = [(m.start(), m.end()) for m in KEEP_PHRASES.finditer(masked)]

    def kept(s, e):
        return any(a <= s and e <= b for a, b in keep)

    # R2a / R1 inside code spans
    for m in _CODE_SPAN.finditer(line):
        inner = m.group()[1:-1]
        cm = re.fullmatch(r"(%s)(\(.*\))?" % "|".join(sorted(_TOOL_ANY - {"Cron*"}, key=len, reverse=True)), inner)
        if cm:
            refs.append((m.start(), m.end(), cm.group(1), "call" if cm.group(2) else "tool"))
            continue
        for dm in _DISTINCT_RE.finditer(inner):
            tok = dm.group(1) or "Cron*"
            refs.append((m.start() + 1 + dm.start(), m.start() + 1 + dm.end(), tok, "tool"))
    # R1 outside code spans
    for m in _DISTINCT_RE.finditer(masked):
        tok = m.group(1) or "Cron*"
        if not kept(m.start(), m.end()):
            refs.append((m.start(), m.end(), tok, "tool" if not m.group(2) else "suffix:" + m.group(2)))
    # R2 b–e outside code spans
    names = [(m.start(), m.end(), m.group(1)) for m in _COMMON_RE.finditer(masked)]
    others = [(s, e) for s, e, *_ in refs]
    all_tools = sorted([(s, e) for s, e, _ in names] + others)
    for s, e, tok in names:
        if kept(s, e):
            continue
        after, before = masked[e:], masked[:s]
        if after.startswith("-") or after.startswith("_"):
            continue
        form = None
        if after.startswith("("):                                         # b
            depth, j = 0, e
            while j < len(masked):
                if masked[j] == "(":
                    depth += 1
                elif masked[j] == ")":
                    depth -= 1
                    if depth == 0:
                        break
                j += 1
            refs.append((s, j + 1 if j < len(masked) else e, tok, "call"))
            continue
        if _CALL_SUFFIX.match(after):                                      # c
            form = "tool"
        else:                                                              # d
            for (os_, oe) in all_tools:
                if (os_, oe) == (s, e):
                    continue
                if oe <= s and _LIST_SEP.search(masked[oe:s]) and _LIST_SEP.search(masked[oe:s]).start() == 0:
                    form = "tool"
                    break
                if os_ >= e and _LIST_SEP_FWD.fullmatch(masked[e:os_]):
                    form = "tool"
                    break
        if form is None and tok != "LSP":                                  # e
            if _DETERMINER.search(before) or _LOWER_WORD.search(before) or (
                    before.endswith("(") and after.startswith(")")):
                form = "prose"
        if form:
            refs.append((s, e, tok, form))
    # drop overlaps (keep the first, longest)
    refs.sort(key=lambda r: (r[0], -(r[1] - r[0])))
    out, last = [], -1
    for r in refs:
        if r[0] >= last:
            out.append(r)
            last = r[1]
    return out


def _replacement(tok: str, form: str, line: str, start: int):
    """Codex text for one reference, or None when the token has no mapping (dropped or unknown)."""
    entry = TOOL_MAP.get(tok)
    if entry is None:
        return None
    if form.startswith("suffix:"):
        return (_SUFFIX_OK.get(tok) or {}).get(form[7:])
    if form == "prose" and "prose" in entry:
        return entry["prose"]
    if "bare" in entry and _ARTICLE.search(line[:start]):
        return entry["bare"]
    return entry["tool"]


def _call_text(tok: str, raw: str):
    """Codex text for a call form: Agent(x) → spawn_agent with agent_type x; Bash(cmd) → shell `cmd`."""
    m = re.match(r"`?(\w+)\((.*)\)`?\Z", raw, re.S)
    arg = m.group(2).strip() if m else ""
    if tok in ("Agent", "Task"):
        return "`spawn_agent` (agent_type %s)" % arg if arg else "`spawn_agent`"
    if tok == "Bash":
        return "the shell command `%s`" % arg if arg else "the shell"
    if tok == "Read":
        return "reading `%s`" % arg if arg else TOOL_MAP["Read"]["tool"]
    if tok in ("Edit", "Write", "MultiEdit", "NotebookEdit"):
        return "`apply_patch` on `%s`" % arg if arg else "`apply_patch`"
    entry = TOOL_MAP.get(tok)
    return entry["tool"] if entry else None


# ---------------------------------------------------------------- the pass
def translate_text(text: str, label: str, ctx: dict, verbatim: bool = False, stats: Stats | None = None):
    """Translate one file's text. Returns (text, problems). `stats` (a Stats) is filled when given."""
    st = stats if stats is not None else Stats()
    problems = []
    rendered, npaths, unknown = render_placeholders(text, ctx, verbatim=verbatim)
    st["paths"] += npaths
    lines = rendered.split("\n")
    in_fence = False
    for i, line in enumerate(lines):
        lineno = i + 1
        for u in _PLACEHOLDER.findall(line):
            if u in unknown:
                problems.append("%s:%d: %s" % (label, lineno, u))
        if _FENCE.match(line):
            in_fence = not in_fence
            continue
        if in_fence or verbatim:
            continue
        for rx, rep in PHRASES:
            line, k = rx.subn(rep, line)
            st["rewrites"] += k
        refs = _find_refs(line)
        for s, e, tok, form in sorted(refs, key=lambda r: r[0], reverse=True):
            raw = line[s:e]
            new = _call_text(tok, raw) if form == "call" else _replacement(tok, form, line, s)
            st["references"] += 1
            if new is None:
                problems.append("%s:%d: %s" % (label, lineno, raw))
                continue
            st["mapped"][tok] = st["mapped"].get(tok, 0) + 1
            line = line[:s] + new + line[e:]
        for rx in FORBIDDEN:
            for m in rx.finditer(line):
                problems.append("%s:%d: %s" % (label, lineno, m.group()))
        lines[i] = line
    return "\n".join(lines), problems
