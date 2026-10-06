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

Order of the pass. Whole text first (a rewrite there may join a sentence that wraps onto the next
line; problems still name the source line): EXCLUDED_PHRASES (sentences that send the reader to an
EXCLUDED_SKILLS skill) → VENV_PHRASES (prose about the Claude stack's shared venvs) → venv paths
(`__CLAUDE_DIR__/venvs/<v>/bin/python` → `uv run --with <pkg>… python`, code included) →
placeholders and `~/.claude` paths (code included). Then per line, outside fenced code: PHRASES
(explicit sentence rewrites: hook-enforcement claims to DESIGN §5's status column, dropped tools,
idioms) → token mapping (TOOL_MAP) → the lints: FORBIDDEN phrases, venv prose; on every line, code
included: a surviving `venvs/` path, a named excluded skill, an unknown `__PLACEHOLDER__`. A dropped
tool (DROPPED: ToolSearch, LSP, Artifact, Workflow, Cron*, …) has no token mapping: a sentence naming
it must be rewritten by PHRASES, else it is reported.

Venv rule (the user's decision, 2026-10-06): no Codex text names the Claude stack's venvs. A venv
path becomes `uv run --with <p> … python` with the packages the sentence names: a parenthesized list
right after the path, a "has <list>" after it, "<pkg> in <path>" before it, else the venv's packages
named earlier in the same clause, else VENV_DEFAULT; in fenced code, the packages the block imports
(a non-stdlib import outside VENV_PACKAGES is a problem). VENV_PACKAGES is a fixed copy of
requirements/{sci,ml,tools}.in (the install snapshot does not carry requirements/).

Seeded-bug proofs (tests/test_translate.py; tests/mutations/translate.json): an unmapped token
silently passed (the problem append dropped); fenced code no longer skipped; the article-aware
"shell" form dropped; a forbidden phrase not reported; `__CLAUDE_DIR__/skills/<module>` sent to
skills/ instead of skill-modules/; a venv path passed through (no uv rewrite); a surviving `venvs/`
path not reported; an excluded skill not reported; the old Monitor rule ("a polling loop on a
background job on the log"); the old `__STACK_REPO__` fallback (prose inside a code span); a joined
line shifting the source line numbers of later problems.
"""
from __future__ import annotations

import re
import sys

__all__ = ["BuildError", "translate_text", "render_placeholders", "TOOL_MAP", "DISTINCT", "COMMON",
           "DROPPED", "PHRASES", "FORBIDDEN", "Stats", "EXCLUDED_SKILLS", "VENV_PACKAGES",
           "VENV_DEFAULT", "excluded_refs"]


class BuildError(Exception):
    """An input the converter cannot translate (the build stops)."""


# Skills not installed for Codex (the user's decision, 2026-10-06): their subject is Claude Code
# itself (its config formats, and three user commands answered by Claude hooks: /override-agent,
# /stack-doctor, /stack-tree), so nothing in them applies to a Codex session. convert_skills skips
# them (and any hub module reachable only from them); no installed text may name one (lint below).
EXCLUDED_SKILLS = ("claude-code-extensions", "override-agent", "stack-doctor", "stack-tree")
_EXCLUDED_RE = re.compile(r"(?<![\w-])(%s)(?![\w-])" % "|".join(EXCLUDED_SKILLS))


def excluded_refs(text: str) -> list[tuple[int, str]]:
    """(line, name) for every whole-word mention of an excluded skill (code included)."""
    return [(i + 1, m.group(1)) for i, line in enumerate(text.split("\n"))
            for m in _EXCLUDED_RE.finditer(line)]


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
    # idioms ("on a Monitor until-loop" → "with a polling loop": the clause may go on, "… on the log")
    (r"(?:on |with )a Monitor until-loop", "with a polling loop"),
    (r"a Monitor until-loop", "a polling loop"),
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

# ---------------------------------------------------------------- excluded skills (whole text, prose)
# Sentences or list items that send the reader to an EXCLUDED_SKILLS skill: dropped (the pointer has
# no target in a Codex install). Whatever these miss is reported by the excluded-skill lint.
EXCLUDED_PHRASES = [(re.compile(p), r) for p, r in (
    (r" Claude Code file formats \(agent frontmatter, skills, settings\) → `claude-code-extensions`\.", ""),
    (r" \(`claude-code-extensions` has the shapes\)", ""),
    (r", `claude-code-extensions` \([^()\n]*\)", ""),
    (r"Load `claude-code-extensions` before writing any configuration, and ", "Load "),
    (r", `claude-code-extensions` for the stack's MCP lifecycle; vetting, permanent edits and audits: "
     r"Read `[^`\n]*/skills/claude-code-extensions/references/mcp-broker\.md`\.", "."),
    (r",? per the reference(?=[;.])", ""),     # mcp-broker: "the reference" was that excluded file
    (r" /stack-doctor shows the models\n[ \t]*in use and checks each in its provider's catalog\.", ""),
)]

# ---------------------------------------------------------------- the Claude stack's venvs
# Package names per venv: a fixed copy of requirements/{sci,ml,tools}.in (2026-10-06), plus pillow
# for sci and ml (a matplotlib dependency the skills import as PIL). Used only to read package names
# out of sentences and imports, never to install anything.
VENV_PACKAGES = {
    "sci": ("sympy", "numpy", "scipy", "mpmath", "pandas", "polars", "duckdb", "pyarrow", "matplotlib",
            "seaborn", "networkx", "pint", "statsmodels", "scikit-learn", "pdfplumber", "pypdf",
            "openpyxl", "python-docx", "python-pptx", "nbformat", "nbclient", "ipykernel", "z3-solver",
            "hypothesis", "pillow"),
    "ml": ("numpy", "scipy", "pandas", "polars", "pyarrow", "scikit-learn", "statsmodels", "xgboost",
           "lightgbm", "matplotlib", "seaborn", "torch", "transformers", "datasets", "accelerate", "peft",
           "safetensors", "huggingface_hub", "evaluate", "sentencepiece", "ipykernel", "nbclient", "mlx",
           "mlx-lm", "pillow"),
    "tools": ("pytest", "numpy", "pandas", "httpx", "mcp", "pillow", "neural-memory"),
}
# A path no sentence or import qualifies: the venv's core libraries.
VENV_DEFAULT = {"sci": ("numpy", "scipy"), "ml": ("torch",), "tools": ("pytest",)}
# Spellings in prose → package name (keys lowercase).
PACKAGE_ALIASES = {"pytorch": "torch", "z3": "z3-solver", "pil": "pillow", "sklearn": "scikit-learn",
                   "huggingface-hub": "huggingface_hub"}
# Import name → package name where they differ.
MODULE_PACKAGES = {"PIL": "pillow", "z3": "z3-solver", "sklearn": "scikit-learn", "docx": "python-docx",
                   "pptx": "python-pptx", "mlx_lm": "mlx-lm", "neural_memory": "neural-memory"}

_VENV_ROOT = r"(?:__CLAUDE_DIR__|~/\.claude|\$HOME/\.claude|\$\{HOME\}/\.claude|\{\{STACK\}\})"
_VENV_PATH = _VENV_ROOT + r"/venvs/[\w-]+/bin/python3?"
# Prose about the venvs (outside fenced code), rewritten before the paths are.
VENV_PHRASES = [(re.compile(p), r) for p, r in (
    (r" \(from `\./install\.sh --with-ml`\)", ""),
    (r"The shared venvs \(`%s`, `%s`\) are for ad-hoc analysis — never install project dependencies "
     r"into them\." % (_VENV_PATH, _VENV_PATH),
     "Ad-hoc analysis outside a project runs as `uv run --with <package> python` (a cached throwaway "
     "environment); never add its packages to a project."),
    (r"the (?:sci|science) venv (?=`%s`)" % _VENV_PATH, ""),
    (r" is in the sci venv: (?=`%s`)" % _VENV_PATH, " runs with "),
    (r" \((?:the )?(?:sci|science) venv\)", ""),
    (r"not in the (?:sci|science) venv(?: —|;) ", ""),
    (r" \(not in the venvs\)", ""),
    (r" \(the shared sci venv has no quantum libraries\)", ""),
    (r"the sci venv has no quantum libraries\. Make", "make"),
    (r"\(([\w-]+) is also in the science venv\)", r"(\1: `uv run --with \1`)"),
    (r"(?:sci|science) venv has [^;)\n]*; ", ""),
    (r"runs in the (?:sci|science) venv", "runs with `uv run --with <package>`"),
)]
_VENV_RE = re.compile(
    r"(?P<pre>(?P<pkg>[A-Za-z][\w-]*) in )?(?P<tick>`?)" + _VENV_ROOT + r"/venvs/(?P<venv>[\w-]+)/bin/python3?"
    r"(?P=tick)(?P<post>\s*\((?P<paren>[^()`]*)\)| has (?P<has>[^;.\n]*))?")
_VENV_LEFT = re.compile(r"\S*venvs/\S*")
_VENV_PROSE = re.compile(r"(?i)\b(?:sci|science|shared|ml|tools) venvs?\b|\bthe venvs\b")

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
# A determiner, maybe one or two adjectives, then the token: "a separate Bash call", "the Bash tool",
# "your own Bash calls" take the bare form ("a separate shell call"), never "a separate the shell".
_ARTICLE = re.compile(r"(?i)(?:^|[\s(])(?:a|an|the|each|every|one|your|its|their|our|no|any|this|that|another)\s+"
                      r"(?:(?:separate|own|single|new|long|short|plain|same|next|first|other|later|fresh|"
                      r"extra)\s+){0,2}\Z")
_CALL_SUFFIX = re.compile(r"\A(?:'s)?\s+(?:tools?|calls?)\b")


class Stats(dict):
    """Counters of one translate_text call: mapped (per token), rewrites, paths, problems."""

    def __init__(self):
        super().__init__(mapped={}, rewrites=0, paths=0, references=0)


# ---------------------------------------------------------------- placeholders and paths
_UNCLASSIFIED = "__UNCLASSIFIED_SKILL__:"
_UNCLASSIFIED_RE = re.compile(r"__UNCLASSIFIED_SKILL__:([\w-]+)")


def _skill_target(name: str, ctx: dict) -> str:
    """Absolute Codex directory of skill `name` (a module → skill-modules/). Without
    ctx["skill_modules"] a named skill cannot be classified: the marker is reported, never guessed."""
    stack = ctx["stack"]
    if name == "<name>":
        return "%s/skill-modules/<name>" % stack
    if "skill_modules" not in ctx:
        return _UNCLASSIFIED + name
    if name in ctx["skill_modules"]:
        return "%s/skill-modules/%s" % (stack, name)
    return "%s/skills/%s" % (stack, name)


def render_placeholders(text: str, ctx: dict):
    """Placeholders and ~/.claude paths → absolute Codex paths (ctx). Returns (text, n, unknown).
    ctx keys read: stack, codex_home, home, state_dir, uv, skill_modules (the hub-module names; needed
    as soon as the text names `__CLAUDE_DIR__/skills/<skill>`), optional stack_repo, uvx, npx, node,
    magg, huetension, python3."""
    n = [0]
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
    if not ctx.get("stack_repo"):
        # No repository path known: name it in words, outside code spans, and drop a parenthesis that
        # only held the path ("Edit the stack repo (`__STACK_REPO__`), …" → "Edit the stack repo, …").
        k = out.count("__STACK_REPO__")
        out = re.sub(r"(?<=repo) \(`__STACK_REPO__`\)", "", out)
        out = re.sub(r"`__STACK_REPO__`|__STACK_REPO__", "the claude-agent-stack repository", out)
        n[0] += k
    simple = {
        "__HOME__": ctx.get("home"), "__STACK_STATE__": ctx.get("state_dir"),
        "__UV__": ctx.get("uv") or "uv", "__UVX__": ctx.get("uvx") or _sibling(ctx.get("uv"), "uvx"),
        "__NPX__": ctx.get("npx") or "npx", "__NODE__": ctx.get("node") or "node",
        "__MAGG__": ctx.get("magg") or "magg", "__HUETENSION__": ctx.get("huetension") or "huetension",
        "__PYTHON3__": ctx.get("python3") or "python3", "__STACK_REPO__": ctx.get("stack_repo"),
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


# ---------------------------------------------------------------- whole-text passes
def _resub(text: str, src: list, rx, fn):
    """rx.sub(fn) over the whole text, keeping `src` (the source line of each line) aligned. fn returns
    the replacement or None (match left alone); a replacement may join lines, never add one."""
    pieces, out_src, line, last = [], [src[0]], 0, 0
    for m in rx.finditer(text):
        rep = fn(m)
        if rep is None:
            continue
        if "\n" in rep:
            raise ValueError("a rewrite may not add a line: %r" % rep)
        seg = text[last:m.start()]
        for _ in range(seg.count("\n")):
            line += 1
            out_src.append(src[line])
        pieces += [seg, rep]
        line += m.group().count("\n")
        last = m.end()
    seg = text[last:]
    for _ in range(seg.count("\n")):
        line += 1
        out_src.append(src[line])
    pieces.append(seg)
    return "".join(pieces), out_src


def _fences(text: str) -> list[tuple[int, int]]:
    """(start, end) offsets of the fenced code blocks, fence lines included."""
    spans, pos, start = [], 0, None
    for line in text.split("\n"):
        if _FENCE.match(line):
            if start is None:
                start = pos
            else:
                spans.append((start, pos + len(line)))
                start = None
        pos += len(line) + 1
    if start is not None:
        spans.append((start, len(text)))
    return spans


def _in(spans, at):
    for a, b in spans:
        if a <= at < b:
            return (a, b)
    return None


def _prose_sub(text, src, rx, rep):
    """A PHRASES-style rewrite over the whole text, outside fenced code."""
    spans = _fences(text)
    return _resub(text, src, rx, lambda m: None if _in(spans, m.start()) else m.expand(rep))


def _package_list(items: str, venv: str):
    """Package names of a list ("sympy, mpmath, numpy/scipy", "a and b"), or None when any item is
    not a package of `venv` (then the list is prose and stays)."""
    out = []
    for it in re.split(r"[,;/]|\band\b", items):
        it = it.strip()
        if not it:
            continue
        p = PACKAGE_ALIASES.get(it.lower(), it.lower())
        if p not in VENV_PACKAGES[venv]:
            return None
        if p not in out:
            out.append(p)
    return out or None


def _named_packages(segment: str, venv: str) -> list:
    """Packages of `venv` named as words in `segment` (lowercase as written, or a known alias)."""
    out = []
    for m in re.finditer(r"(?<![\w-])[A-Za-z][\w-]*(?![\w-])", segment):
        w = m.group()
        p = PACKAGE_ALIASES.get(w.lower()) or (w if w in VENV_PACKAGES[venv] else None)
        if p and p in VENV_PACKAGES[venv] and p not in out:
            out.append(p)
    return out


_NAMES = r"[\w.*]+(?:\s+as\s+\w+)?(?:\s*,\s*[\w.]+(?:\s+as\s+\w+)?)*"
_FROM_IMPORT = re.compile(r"(?:^|(?<=[\s;'\"]))from\s+([\w.]+)\s+import\s+" + _NAMES, re.M)
_IMPORT = re.compile(r"(?:^|(?<=[\s;'\"]))import\s+(" + _NAMES + ")", re.M)


def _imported_packages(block: str, venv: str):
    """(packages, unmapped modules) a fenced block imports, stdlib skipped."""
    found = [(m.start(), m.group(1)) for m in _FROM_IMPORT.finditer(block)]
    for m in _IMPORT.finditer(_FROM_IMPORT.sub(lambda f: " " * len(f.group()), block)):
        found += [(m.start(), part.split()[0]) for part in m.group(1).split(",")]
    mods = [mod for _, mod in sorted(found, key=lambda x: x[0])]
    pk, bad = [], []
    for mod in mods:
        top = mod.split(".")[0]
        if top in sys.stdlib_module_names:
            continue
        p = MODULE_PACKAGES.get(top, top.replace("_", "-"))
        if p in VENV_PACKAGES[venv] or top in VENV_PACKAGES[venv]:
            p = p if p in VENV_PACKAGES[venv] else top
            if p not in pk:
                pk.append(p)
        elif top not in bad:
            bad.append(top)
    return pk, bad


def _uv_python(pkgs) -> str:
    return "uv run %s python" % " ".join("--with " + p for p in pkgs)


def _venv_pass(text: str, src: list, label: str, problems: list):
    """Venv prose and venv paths → uv forms (module docstring, "Venv rule")."""
    for rx, rep in VENV_PHRASES:
        text, src = _prose_sub(text, src, rx, rep)
    spans = _fences(text)
    prev_end = [0]

    def lineno(at):
        return src[text.count("\n", 0, at)]

    def fn(m):
        venv = m.group("venv")
        if venv not in VENV_PACKAGES:
            problems.append("%s:%d: unknown venv %s" % (label, lineno(m.start("venv")), m.group()))
            return None
        fence = _in(spans, m.start())
        pre, post, pkgs = m.group("pre") or "", m.group("post") or "", None
        if fence:
            pkgs, bad = _imported_packages(text[fence[0]:fence[1]], venv)
            for mod in bad:
                problems.append("%s:%d: import %s (no package mapping for the %s venv)"
                                % (label, lineno(m.start()), mod, venv))
            tail = post
        else:
            if m.group("paren") is not None:
                pkgs = _package_list(m.group("paren"), venv)
            elif m.group("has") is not None:
                pkgs = _package_list(m.group("has"), venv)
            tail = "" if pkgs else post
            if pre and not pkgs:
                pkgs = _package_list(m.group("pkg"), venv)
                pre = "" if pkgs else pre
            if not pkgs:
                line_start = text.rfind("\n", 0, m.start("tick")) + 1
                seg = text[max(line_start, prev_end[0]):m.start("tick")]
                seg = re.split(r"[.;:]\s", seg)[-1]
                pkgs = _named_packages(seg, venv)
        prev_end[0] = m.end()
        tick = m.group("tick")
        return "%s%s%s%s%s" % (pre, tick, _uv_python(pkgs or VENV_DEFAULT[venv]), tick, tail)

    return _resub(text, src, _VENV_RE, fn)


# ---------------------------------------------------------------- the pass
def translate_text(text: str, label: str, ctx: dict, stats: Stats | None = None):
    """Translate one file's text. Returns (text, problems); problems name `label`:<source line>.
    `stats` (a Stats) is filled when given."""
    st = stats if stats is not None else Stats()
    problems = []
    src = list(range(1, text.count("\n") + 2))
    for rx, rep in EXCLUDED_PHRASES:
        text, src = _prose_sub(text, src, rx, rep)
    text, src = _venv_pass(text, src, label, problems)
    rendered, npaths, unknown = render_placeholders(text, ctx)
    st["paths"] += npaths
    lines = rendered.split("\n")
    in_fence = False
    for i, line in enumerate(lines):
        lineno = src[i]
        for u in _PLACEHOLDER.findall(line):
            if u in unknown and u != "__UNCLASSIFIED_SKILL__":
                problems.append("%s:%d: %s" % (label, lineno, u))
        for m in _UNCLASSIFIED_RE.finditer(line):
            problems.append("%s:%d: skills/%s (ctx has no skill_modules to classify it)"
                            % (label, lineno, m.group(1)))
        for m in _VENV_LEFT.finditer(line):
            problems.append("%s:%d: %s (a Claude stack venv)" % (label, lineno, m.group()))
        for m in _EXCLUDED_RE.finditer(line):
            problems.append("%s:%d: %s (a skill not installed for Codex)" % (label, lineno, m.group()))
        if _FENCE.match(line):
            in_fence = not in_fence
            continue
        if in_fence:
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
        for rx in FORBIDDEN + [_VENV_PROSE]:
            for m in rx.finditer(line):
                problems.append("%s:%d: %s" % (label, lineno, m.group()))
        lines[i] = line
    return "\n".join(lines), problems
