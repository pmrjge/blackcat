"""Claude agents (dot-claude/agents/*.md) -> Codex roles, profile entries, policy and MCP servers.

Stdlib only, Python >= 3.11 (tomllib). DESIGN.md §2, §2.1, §8.1; INTERFACES.md §3, §4.

    load_models(path=None) -> dict            models.toml, validated (validate_models)
    codex_effort(alias, effort, models) -> str   the stack's effort on a tier -> the Codex effort
    convert(src, ctx, models, rules_text=None, blackcat_text=None) -> dict

`src` is the snapshot root (holds dot-claude/). `ctx` needs `codex_home` and `stack`
(= `<codex_home>/stack`, both absolute); `home`, `uv`, `uvx`, `npx`, `node`, `magg`, `huetension`,
`python3` render the MCP command placeholders (a missing tool path falls back to its bare name, as
in translate.py); other keys are accepted and ignored. convert() returns:

    roles          {role: {"model", "model_reasoning_effort", "developer_instructions"}}
                   (only these keys: an agent role file is a ConfigToml layer, additionalProperties
                   false, and has no name/description; role.rs applies only bounded keys, F6)
    astra_roles    the models.toml astra.agents roles, differing only in model and effort
    agents_entries {role: {"description", "config_file": "<codex_home>/stack/agents/<role>.toml"}}
    astra_entries  {role: {"description", "config_file": "<codex_home>/stack/agents-astra/<role>.toml"}}
    policy         stack/policy/agents.json (INTERFACES §4), keys always the canonical hyphenated names
    mcp_servers    {id: final [mcp_servers.<id>] table}, merged from every agent's mcpServers
    blackcat       {"model", "effort", "instructions"}: the main thread's profile values; the
                   instructions are the BlackCat text only (render_profile prepends rules R)
    report         counts, effort per agent, dropped frontmatter keys, dropped MCP keys, origins

Roles. Every agent but blackcat (the main thread) is a role. developer_instructions = the body
translated by translate.translate_text + "\\n\\n" + rules R (a role replaces the parent's
instructions, so R goes into every role). The description is translated too. Every translate
problem of every agent is collected and raised as one BuildError ("<label>:<line>: <token>", lines
of the .md file).

Effort (DESIGN §2): Sol keeps the stack's level; the sonnet tier (Luna) runs luna_effort_offset
levels higher, capped at "max"; none, minimal and ultra are never on the scale; an effort outside
the model's accepted set stops the build. Astra roles take the `fable` column of
dot-claude/hooks/agent_effort.json, which must be in Astra's accepted set.

Policy (INTERFACES §4): apply_patch = Write, Edit, MultiEdit or NotebookEdit in tools; shell = Bash;
spawn_tool = Agent; mcp = the `mcp__<server>` tools in order; spawn = the body's "May spawn:" list
(an agent without Agent: []), blackcat's from its Agent(...) list; readonly = the body's
"Read-only (hook-enforced Bash" mark (the six read-only roles; such a role must hold Bash and no edit
tool); installer = shell without apply_patch and not readonly (toolsmith); web_ingesting = the
declared WEB_INGESTING set; max_tool_calls = maxTurns or null. tests/test_agents_schema_contract.py
asserts every row equals agent_guard.py's POLICY, LEAVES, READONLY_TYPES, WEB_INGESTING_TYPES and
INSTALLER_TYPES (agent_guard is imported there, by path, never here).

MCP servers: each agent's mcpServers entry becomes a final Codex table: stdio -> command, args, env;
http -> url, http_headers_helper = "<codex_home>/stack/bin/codex-mcp-headers <id>" when the entry
has a headersHelper. Placeholders: __UV__ and the other tool names from ctx, __HOME__, and
__CLAUDE_DIR__/x -> <codex_home>/stack/x (__CLAUDE_DIR__/stack.env -> <codex_home>/stack.env).
A server already wrapped by with-stack-env keeps its --only list and gets env STACK_ENV_FILE =
<codex_home>/stack.env (the wrapper's own default, ../stack.env, would be <codex_home>/stack/stack.env).
`type` picks the table shape; `alwaysLoad` (Claude's tool-search opt-out) is dropped and reported.
The same id with a different final table in two agents stops the build. Any other key, an unknown placeholder or an unknown type stops it too.

Name style (models.toml [roles] name_style): "underscore" maps - to _ in role names, role file names
and spawn text (every whole-word stack agent name in developer_instructions and the BlackCat
instructions); policy keys stay hyphenated.

Frontmatter: name, description, model, effort, maxTurns, tools, mcpServers are mapped;
permissionMode, color, memory, experimental, omitClaudeMd and hooks (blackcat's main-thread gate,
ported as the guard) are dropped and reported; any other key stops the build.

Seeded-bug proofs (tests/mutations/convert_agents.json, models.json; each turns its named test red):
drop the Luna +1; apply the +1 to Sol; cap Luna at xhigh; start the scale at none (models.toml);
add a seventh Astra agent (models.toml); read the opus column instead of fable; flip readonly in the
policy; let an MCP conflict pass.
"""
from __future__ import annotations

import importlib.util
import json
import os
import re
import tomllib

__all__ = ["BuildError", "load_models", "validate_models", "codex_effort", "convert", "role_name",
           "parse_frontmatter", "MODELS_TOML", "WEB_INGESTING", "BUILTIN_TYPES"]

_HERE = os.path.dirname(os.path.abspath(__file__))
CODEX_CONFIG = os.path.dirname(_HERE)
MODELS_TOML = os.path.join(CODEX_CONFIG, "models.toml")
TEMPLATES = os.path.join(CODEX_CONFIG, "templates")


def _load(name, path):
    """A sibling module loaded by file path (CWE-427: never through sys.path)."""
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


translate = _load("codex_config_translate_for_agents", os.path.join(_HERE, "translate.py"))


class BuildError(Exception):
    """An agent input the converter cannot map (the build stops)."""


BLACKCAT = "blackcat"
NEVER_EFFORTS = ("none", "minimal", "ultra")
MAPPED_KEYS = ("name", "description", "model", "effort", "maxTurns", "tools", "mcpServers")
DROPPED_KEYS = ("permissionMode", "color", "memory", "experimental", "omitClaudeMd", "hooks")
EDIT_TOOLS = frozenset(("Write", "Edit", "MultiEdit", "NotebookEdit"))
# Claude Code tools an agent's tools: line may name (besides mcp__<server>); anything else stops the build
KNOWN_TOOLS = frozenset((
    "Agent", "Artifact", "AskUserQuestion", "Bash", "CronCreate", "CronDelete", "CronList", "Edit",
    "EnterWorktree", "ExitPlanMode", "ExitWorktree", "Glob", "Grep", "LSP", "ListAgents", "Monitor",
    "MultiEdit", "NotebookEdit", "PushNotification", "Read", "RemoteTrigger", "ScheduleWakeup",
    "SendMessage", "SendUserFile", "Skill", "TaskStop", "ToolSearch", "WebFetch", "WebSearch",
    "Workflow", "Write",
))
# agent_guard.WEB_INGESTING_TYPES has no marker in the agent files: declared here, pinned by the
# contract test against agent_guard.py
WEB_INGESTING = ("researcher", "scout", "browser-operator")
READONLY_MARK = "Read-only (hook-enforced Bash"
BUILTIN_TYPES = ["default", "worker", "explorer"]
BLACKCAT_SHELL_READS = 3
NAME_STYLES = ("hyphen", "underscore")
MCP_KEYS = frozenset(("type", "command", "args", "env", "url", "headersHelper", "alwaysLoad"))
MCP_DROPPED = ("alwaysLoad",)   # `type` is mapped: it picks the table shape
_ID_RE = re.compile(r"[a-z0-9][a-z0-9-]*\Z")
_SAFE_PATH = re.compile(r"/[A-Za-z0-9/._+-]*\Z")
_PLACEHOLDER = re.compile(r"__[A-Z][A-Z0-9_]*__")


# ---------------------------------------------------------------- models.toml
def validate_models(models: dict) -> dict:
    """models.toml's content, checked; returns it unchanged. Raises BuildError naming each problem."""
    bad = []
    if not isinstance(models, dict):
        raise BuildError("models.toml: not a table")
    tiers = models.get("tiers")
    if not (isinstance(tiers, dict) and tiers and all(isinstance(v, str) and v for v in tiers.values())):
        bad.append("[tiers]: needs alias = \"model id\" strings")
        tiers = {}
    eff = models.get("effort") if isinstance(models.get("effort"), dict) else {}
    levels = eff.get("levels")
    if not (isinstance(levels, list) and levels and all(isinstance(x, str) for x in levels)
            and len(set(levels)) == len(levels)):
        bad.append("[effort] levels: a non-empty list of distinct names")
        levels = []
    for x in NEVER_EFFORTS:
        if x in levels:
            bad.append("[effort] levels: %r is never emitted" % x)
    if levels and "max" not in levels:
        bad.append("[effort] levels: lacks \"max\" (the Luna cap)")
    off = eff.get("luna_effort_offset")
    if not (isinstance(off, int) and not isinstance(off, bool) and off >= 0):
        bad.append("[effort] luna_effort_offset: a whole number >= 0")
    acc = models.get("accepted")
    if not (isinstance(acc, dict) and all(isinstance(v, list) and all(isinstance(x, str) for x in v)
                                          for v in acc.values())):
        bad.append("[accepted]: needs \"model\" = [efforts]")
        acc = {}
    for mid, effs in acc.items():
        for x in NEVER_EFFORTS:
            if x in effs:
                bad.append("[accepted] %s: %r is never emitted" % (mid, x))
    for alias, mid in tiers.items():
        if mid not in acc:
            bad.append("[tiers] %s = %r has no [accepted] set" % (alias, mid))
    astra = models.get("astra")
    if not isinstance(astra, dict) or not isinstance(astra.get("model"), str) or not (
            isinstance(astra.get("agents"), list) and all(isinstance(x, str) for x in astra["agents"])):
        bad.append("[astra]: needs model (str) and agents (list)")
    else:
        if astra["model"] not in acc:
            bad.append("[astra] model %r has no [accepted] set" % astra["model"])
        if len(set(astra["agents"])) != len(astra["agents"]):
            bad.append("[astra] agents: duplicates")
    roles = models.get("roles")
    if not isinstance(roles, dict) or roles.get("name_style") not in NAME_STYLES:
        bad.append("[roles] name_style: one of %s" % ", ".join(NAME_STYLES))
    if bad:
        raise BuildError("models.toml: " + "; ".join(bad))
    return models


def load_models(path: str | None = None) -> dict:
    p = path or MODELS_TOML
    try:
        with open(p, "rb") as f:
            data = tomllib.load(f)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise BuildError("%s: %s" % (p, exc)) from None
    return validate_models(data)


def codex_effort(alias: str, effort: str, models: dict) -> str:
    """The Codex `model_reasoning_effort` for an agent on tier `alias` at the stack's `effort`."""
    levels = models["effort"]["levels"]
    if effort not in levels:
        raise BuildError("effort %r is not on the stack's scale %s" % (effort, levels))
    if alias not in models["tiers"]:
        raise BuildError("model %r has no [tiers] entry in models.toml" % alias)
    model = models["tiers"][alias]
    offset = models["effort"]["luna_effort_offset"]
    step = offset if alias == "sonnet" else 0
    top = levels.index("max")
    out = levels[min(levels.index(effort) + step, top)]
    if out not in models["accepted"][model]:
        raise BuildError("effort %r is not accepted by %s (accepted: %s)"
                         % (out, model, ", ".join(models["accepted"][model])))
    return out


def role_name(name: str, style: str) -> str:
    return name.replace("-", "_") if style == "underscore" else name


# ---------------------------------------------------------------- frontmatter (a YAML subset)
def _indent(t):
    return len(t) - len(t.lstrip(" "))


_KEY_RE = re.compile(r"( *)([A-Za-z0-9_][A-Za-z0-9_.-]*|\"[^\"\n]*\"):(?:[ ]+(.*?))?[ ]*\Z")


def _scalar(v, label, n):
    v = v.strip()
    if v[:1] in ('"', "[", "{"):
        try:
            obj, end = json.JSONDecoder().raw_decode(v)
        except ValueError:
            raise BuildError("%s:%d: value not in the supported YAML subset: %s" % (label, n, v[:60])) from None
        rest = v[end:].strip()
        if rest and not rest.startswith("#"):
            raise BuildError("%s:%d: text after a quoted value: %s" % (label, n, rest[:40]))
        return obj
    if v[:1] == "'":
        m = re.match(r"'((?:[^']|'')*)'\s*(#.*)?\Z", v)
        if not m:
            raise BuildError("%s:%d: unterminated single-quoted value" % (label, n))
        return m.group(1).replace("''", "'")
    v = re.split(r"\s+#", v, maxsplit=1)[0].strip()
    if v in ("true", "True"):
        return True
    if v in ("false", "False"):
        return False
    if v in ("null", "~", ""):
        return None
    if re.fullmatch(r"-?[0-9]+", v):
        return int(v)
    if v[:1] in "&*!|>%@`" or ": " in v:
        raise BuildError("%s:%d: value not in the supported YAML subset: %s" % (label, n, v[:60]))
    return v


def _node(items, i, indent, label):
    t = items[i][1]
    if t[indent:indent + 2] == "- " or t[indent:] == "-":
        return _seq(items, i, indent, label)
    return _map(items, i, indent, label)


def _map(items, i, indent, label):
    out = {}
    while i < len(items):
        n, t = items[i]
        ind = _indent(t)
        if ind < indent:
            break
        m = _KEY_RE.fullmatch(t)
        if ind > indent or not m:
            raise BuildError("%s:%d: frontmatter line not in the supported YAML subset" % (label, n))
        key = m.group(2).strip('"')
        if key in out:
            raise BuildError("%s:%d: duplicate key %r" % (label, n, key))
        if m.group(3):
            out[key] = _scalar(m.group(3), label, n)
            i += 1
            continue
        nxt = items[i + 1][1] if i + 1 < len(items) else None
        if nxt is not None and (_indent(nxt) > indent or (_indent(nxt) == indent and nxt[indent:indent + 1] == "-")):
            out[key], i = _node(items, i + 1, _indent(nxt), label)
        else:
            out[key] = None
            i += 1
    return out, i


def _seq(items, i, indent, label):
    out = []
    while i < len(items):
        n, t = items[i]
        ind = _indent(t)
        if ind < indent or (ind == indent and t[indent:indent + 1] != "-"):
            break
        if ind > indent:
            raise BuildError("%s:%d: frontmatter line not in the supported YAML subset" % (label, n))
        rest = t[indent + 1:]
        j = i + 1
        while j < len(items) and _indent(items[j][1]) > indent:
            j += 1
        if not rest.strip():
            if j == i + 1:
                out.append(None)
            else:
                val, used = _node(items[i + 1:j], 0, _indent(items[i + 1][1]), label)
                if used != j - i - 1:
                    raise BuildError("%s:%d: frontmatter list item not in the supported YAML subset" % (label, n))
                out.append(val)
        else:
            col = indent + 1 + _indent(rest)
            first = " " * col + rest.lstrip(" ")
            if _KEY_RE.fullmatch(first):
                sub = [(n, first)] + items[i + 1:j]
                val, used = _map(sub, 0, col, label)
                if used != len(sub):
                    raise BuildError("%s:%d: frontmatter list item not in the supported YAML subset" % (label, n))
                out.append(val)
            else:
                if j != i + 1:
                    raise BuildError("%s:%d: frontmatter list item not in the supported YAML subset" % (label, n))
                out.append(_scalar(rest, label, n))
        i = j
    return out, i


def parse_frontmatter(text: str, label: str):
    """(fields, body, body_line0): fields {key: (line, value)}; body_line0 = lines before the body."""
    lines = text.split("\n")
    if not lines or lines[0].strip() != "---":
        raise BuildError("%s:1: no frontmatter" % label)
    try:
        end = lines.index("---", 1)
    except ValueError:
        raise BuildError("%s: frontmatter not closed" % label) from None
    fields = {}
    i = 1
    while i < end:
        t = lines[i]
        if not t.strip() or t.lstrip().startswith("#"):
            i += 1
            continue
        if "\t" in t[:len(t) - len(t.lstrip())]:
            raise BuildError("%s:%d: tab indentation" % (label, i + 1))
        m = _KEY_RE.fullmatch(t)
        if not m or m.group(1):
            raise BuildError("%s:%d: frontmatter line not in the supported YAML subset" % (label, i + 1))
        key = m.group(2)
        if key in fields:
            raise BuildError("%s:%d: duplicate key %r" % (label, i + 1, key))
        if m.group(3):
            fields[key] = (i + 1, _scalar(m.group(3), label, i + 1))
            i += 1
            continue
        j = i + 1
        while j < end and (lines[j].startswith(" ") or not lines[j].strip()):
            j += 1
        items = [(k + 1, lines[k]) for k in range(i + 1, j)
                 if lines[k].strip() and not lines[k].lstrip().startswith("#")]
        if items:
            val, used = _node(items, 0, _indent(items[0][1]), label)
            if used != len(items):
                raise BuildError("%s:%d: frontmatter block not in the supported YAML subset" % (label, items[used][0]))
        else:
            val = None
        fields[key] = (i + 1, val)
        i = j
    return fields, "\n".join(lines[end + 1:]), end + 1


# ---------------------------------------------------------------- one agent
def _split_top(s):
    out, cur, depth = [], "", 0
    for ch in s:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        if ch == "," and depth == 0:
            out.append(cur.strip())
            cur = ""
        else:
            cur += ch
    if cur.strip():
        out.append(cur.strip())
    return out


def _tools(raw, label, line):
    if not isinstance(raw, str) or not raw.strip():
        raise BuildError("%s:%d: tools: not a comma-separated list" % (label, line))
    flat, children = [], None
    for tok in _split_top(raw):
        m = re.fullmatch(r"Agent\(([^()]*)\)", tok)
        if m:
            flat.append("Agent")
            children = [c.strip() for c in m.group(1).split(",") if c.strip()]
        elif tok.startswith("mcp__") and _ID_RE.match(tok[5:]):
            flat.append(tok)
        elif tok in KNOWN_TOOLS:
            flat.append(tok)
        else:
            raise BuildError("%s:%d: unknown tool %r in tools:" % (label, line, tok))
    return flat, children


def _may_spawn(body):
    m = re.search(r"May spawn:\s*([^.]*)\.", body)
    if not m:
        return None
    out = []
    for tok in m.group(1).split(","):
        lm = re.match(r"\s*`?([A-Za-z][A-Za-z0-9_-]*)", tok)
        if lm:
            out.append(lm.group(1).lower())
    return out


def _parse_agent(path, rel):
    with open(path, encoding="utf-8") as f:
        text = f.read()
    fields, body, nfront = parse_frontmatter(text, rel)
    unknown = sorted(set(fields) - set(MAPPED_KEYS) - set(DROPPED_KEYS))
    if unknown:
        raise BuildError("%s: unmapped frontmatter key(s): %s" % (rel, ", ".join(unknown)))
    for k in ("name", "description", "model", "effort", "tools"):
        if k not in fields or not isinstance(fields[k][1], str):
            raise BuildError("%s: frontmatter %s missing or not a string" % (rel, k))
    name = fields["name"][1]
    if name != os.path.basename(path)[:-3]:
        raise BuildError("%s: name %r differs from the file name" % (rel, name))
    turns = fields.get("maxTurns", (0, None))[1]
    if turns is not None and not (isinstance(turns, int) and not isinstance(turns, bool) and turns > 0):
        raise BuildError("%s:%d: maxTurns is not a positive whole number" % (rel, fields["maxTurns"][0]))
    flat, children = _tools(fields["tools"][1], rel, fields["tools"][0])
    mcp = []
    if "mcpServers" in fields:
        line, val = fields["mcpServers"]
        if not isinstance(val, list):
            raise BuildError("%s:%d: mcpServers is not a list" % (rel, line))
        for item in val:
            if not (isinstance(item, dict) and len(item) == 1):
                raise BuildError("%s:%d: mcpServers item is not `- <id>: {...}`" % (rel, line))
            (sid, spec), = item.items()
            mcp.append((sid, spec))
    return {"name": name, "description": fields["description"][1], "desc_line": fields["description"][0],
            "model": fields["model"][1], "effort": fields["effort"][1], "max_turns": turns,
            "tools": flat, "children": children, "mcp": mcp, "body": body, "body_lines": nfront,
            "dropped": [k for k in fields if k in DROPPED_KEYS], "label": rel}


# ---------------------------------------------------------------- text
def _translate(text, label, ctx, lines_before, problems):
    """translate_text with problem lines counted in the .md file (blank lines prepended, then cut)."""
    pad = "\n" * lines_before
    out, probs = translate.translate_text(pad + text, label, ctx)
    problems.extend(probs)
    if not out.startswith(pad):
        raise BuildError("%s: the text pass changed the line structure" % label)
    return out[len(pad):]


def _template(text, ctx, what):
    """A templates/ text with its {{CODEX_HOME}}, {{STACK}}, {{HOME}}, {{STATE_DIR}} rendered from ctx
    (a no-op on text the caller already rendered); any other placeholder stops the build."""
    vals = {"CODEX_HOME": ctx["codex_home"].rstrip("/"), "STACK": ctx["stack"], "HOME": ctx.get("home"),
            "STATE_DIR": ctx.get("state_dir")}

    def sub(m):
        v = vals.get(m.group(1))
        if not isinstance(v, str):
            raise BuildError("%s: unknown or unset placeholder %s" % (what, m.group()))
        return v
    out = re.sub(r"\{\{([A-Z_]+)\}\}", sub, text)
    m = _PLACEHOLDER.search(out) or re.search(r"\{\{[^{}\n]*\}\}", out)
    if m:
        raise BuildError("%s: unresolved placeholder %s" % (what, m.group()))
    return out


def _renamer(names, style):
    hy = sorted((n for n in names if "-" in n), key=len, reverse=True)
    if style != "underscore" or not hy:
        return lambda s: s
    rx = re.compile(r"(?<![\w/.-])(%s)(?![\w/-])" % "|".join(re.escape(n) for n in hy))
    return lambda s: rx.sub(lambda m: m.group(1).replace("-", "_"), s)


# ---------------------------------------------------------------- MCP
def _render(s, ctx, where):
    codex_home, stack = ctx["codex_home"], ctx["stack"]
    s = s.replace("__CLAUDE_DIR__/stack.env", codex_home + "/stack.env").replace("__CLAUDE_DIR__", stack)
    uv = ctx.get("uv") or "uv"
    tools = {"__UV__": uv, "__UVX__": ctx.get("uvx") or (uv.rsplit("/", 1)[0] + "/uvx" if "/" in uv else "uvx"),
             "__NPX__": ctx.get("npx") or "npx", "__NODE__": ctx.get("node") or "node",
             "__MAGG__": ctx.get("magg") or "magg", "__HUETENSION__": ctx.get("huetension") or "huetension",
             "__PYTHON3__": ctx.get("python3") or "python3", "__HOME__": ctx.get("home")}
    for m in _PLACEHOLDER.finditer(s):
        if tools.get(m.group()) is None:
            raise BuildError("%s: unknown or unset placeholder %s" % (where, m.group()))
    for k, v in tools.items():
        if v is not None:
            s = s.replace(k, v)
    return s


def _mcp_table(sid, spec, ctx, where):
    """(final Codex table, dropped keys) for one mcpServers entry."""
    if not _ID_RE.match(sid):
        raise BuildError("%s: MCP server id %r is not [a-z0-9-]" % (where, sid))
    if not isinstance(spec, dict):
        raise BuildError("%s: MCP server %s is not a table" % (where, sid))
    unknown = sorted(set(spec) - MCP_KEYS)
    if unknown:
        raise BuildError("%s: MCP server %s: unmapped key(s) %s" % (where, sid, ", ".join(unknown)))
    typ = spec.get("type", "stdio")
    w = "%s: MCP server %s" % (where, sid)
    table = {}
    if typ == "stdio":
        if not isinstance(spec.get("command"), str) or "url" in spec or "headersHelper" in spec:
            raise BuildError("%s: stdio needs a command and no url/headersHelper" % w)
        table["command"] = _render(spec["command"], ctx, w)
        args = spec.get("args", [])
        if not (isinstance(args, list) and all(isinstance(a, str) for a in args)):
            raise BuildError("%s: args is not a list of strings" % w)
        if args:
            table["args"] = [_render(a, ctx, w) for a in args]
        env = spec.get("env") or {}
        if not (isinstance(env, dict) and all(isinstance(v, str) for v in env.values())):
            raise BuildError("%s: env is not a table of strings" % w)
        env = {k: _render(v, ctx, w) for k, v in env.items()}
        if table["command"] == ctx["stack"] + "/bin/with-stack-env":
            want = ctx["codex_home"] + "/stack.env"
            if env.get("STACK_ENV_FILE", want) != want:
                raise BuildError("%s: STACK_ENV_FILE is set to another file" % w)
            env["STACK_ENV_FILE"] = want
        if env:
            table["env"] = env
    elif typ == "http":
        if not isinstance(spec.get("url"), str) or {"command", "args", "env"} & set(spec):
            raise BuildError("%s: http needs a url and no command/args/env" % w)
        table["url"] = _render(spec["url"], ctx, w)
        if spec.get("headersHelper"):
            helper = ctx["codex_home"] + "/stack/bin/codex-mcp-headers"
            if not _SAFE_PATH.match(helper):
                raise BuildError("%s: CODEX_HOME %r holds characters unsafe in a helper command"
                                 % (w, ctx["codex_home"]))
            table["http_headers_helper"] = "%s %s" % (helper, sid)
    else:
        raise BuildError("%s: unmapped transport type %r" % (w, typ))
    return table, [k for k in MCP_DROPPED if k in spec]


# ---------------------------------------------------------------- convert
def _check_ctx(ctx):
    for k in ("codex_home", "stack"):
        if not (isinstance(ctx.get(k), str) and os.path.isabs(ctx[k])):
            raise BuildError("ctx[%r] must be an absolute path" % k)
    if ctx["stack"] != ctx["codex_home"].rstrip("/") + "/stack":
        raise BuildError("ctx['stack'] must be <codex_home>/stack, got %r" % ctx["stack"])


def _read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def convert(src: str, ctx: dict, models: dict, rules_text: str | None = None,
            blackcat_text: str | None = None) -> dict:
    _check_ctx(ctx)
    validate_models(models)
    if "skill_modules" not in ctx:
        # translate needs the hub-module names to place `__CLAUDE_DIR__/skills/<x>` paths
        # (skills/ vs skill-modules/); the classification is convert_skills', never a guess.
        cs = _load("codex_config_convert_skills_for_agents", os.path.join(_HERE, "convert_skills.py"))
        try:
            ctx = dict(ctx, skill_modules=frozenset(cs.classify(src)["modules"]))
        except cs.BuildError as exc:
            raise BuildError(str(exc)) from None
    style = models["roles"]["name_style"]
    codex_home = ctx["codex_home"].rstrip("/")
    adir = os.path.join(src, "dot-claude", "agents")
    try:
        files = sorted(f for f in os.listdir(adir) if f.endswith(".md"))
    except OSError as exc:
        raise BuildError("%s: %s" % (adir, exc.strerror)) from None
    if not files:
        raise BuildError("%s: no agents" % adir)
    rules = _read(os.path.join(TEMPLATES, "rules.md")) if rules_text is None else rules_text
    bc_text = _read(os.path.join(TEMPLATES, "blackcat.md")) if blackcat_text is None else blackcat_text
    rules = _template(rules, ctx, "rules_text")
    bc_text = _template(bc_text, ctx, "blackcat_text")
    try:
        effort_table = json.loads(_read(os.path.join(src, "dot-claude", "hooks", "agent_effort.json")))["agents"]
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise BuildError("dot-claude/hooks/agent_effort.json: %s" % exc) from None

    agents = {}
    for f in files:
        a = _parse_agent(os.path.join(adir, f), "dot-claude/agents/" + f)
        if a["model"] not in models["tiers"]:
            raise BuildError("%s: model %r has no [tiers] entry in models.toml" % (a["label"], a["model"]))
        agents[a["name"]] = a
    if BLACKCAT not in agents:
        raise BuildError("dot-claude/agents/blackcat.md: missing (the main thread)")
    names = set(agents)
    rename = _renamer(names, style)

    problems = []
    roles, entries, policy_rows, efforts, dropped = {}, {}, {}, {}, {}
    for name in sorted(agents):
        a = agents[name]
        if a["dropped"]:
            dropped[name] = a["dropped"]
        model = models["tiers"][a["model"]]
        effort = codex_effort(a["model"], a["effort"], models)
        efforts[name] = {"model": model, "stack_effort": a["effort"], "effort": effort}
        tools = set(a["tools"])
        mcp = [t[5:] for t in a["tools"] if t.startswith("mcp__")]
        if name == BLACKCAT:
            continue
        body = _translate(a["body"], a["label"], ctx, a["body_lines"], problems)
        desc = _translate(a["description"], a["label"], ctx, a["desc_line"] - 1, problems)
        instr = rename(body.strip() + "\n\n" + rules.strip() + "\n")
        rname = role_name(name, style)
        roles[rname] = {"model": model, "model_reasoning_effort": effort, "developer_instructions": instr}
        entries[rname] = {"description": desc.strip(),
                          "config_file": "%s/stack/agents/%s.toml" % (codex_home, rname)}
        may = _may_spawn(a["body"])
        if "Agent" in tools:
            if not may:
                raise BuildError("%s: holds Agent but its body has no \"May spawn:\" list" % a["label"])
            spawn = may
        else:
            if may:
                raise BuildError("%s: a \"May spawn:\" list without the Agent tool" % a["label"])
            spawn = []
        for c in spawn:
            if c not in names or c in (BLACKCAT, name):
                raise BuildError("%s: May spawn names %r, not a spawnable stack agent" % (a["label"], c))
        apply_patch = bool(tools & EDIT_TOOLS)
        shell = "Bash" in tools
        readonly = READONLY_MARK in a["body"]
        if readonly and (apply_patch or not shell):
            raise BuildError("%s: marked read-only but holds an edit tool or no Bash" % a["label"])
        policy_rows[name] = {
            "spawn": spawn, "apply_patch": apply_patch, "shell": shell, "spawn_tool": "Agent" in tools,
            "mcp": mcp, "readonly": readonly, "web_ingesting": name in WEB_INGESTING,
            "installer": shell and not apply_patch and not readonly, "max_tool_calls": a["max_turns"]}
    if problems:
        raise BuildError("untranslatable agent text (%d):\n  %s" % (len(problems), "\n  ".join(problems)))
    for w in WEB_INGESTING:
        if w not in policy_rows:
            raise BuildError("WEB_INGESTING names %r, which is no agent" % w)

    bc = agents[BLACKCAT]
    if not bc["children"]:
        raise BuildError("%s: tools: must list Agent(<the agents it may spawn>)" % bc["label"])
    for c in bc["children"]:
        if c not in names or c == BLACKCAT:
            raise BuildError("%s: Agent(...) names %r, not a spawnable stack agent" % (bc["label"], c))
    policy = {"schema": 1, "agents": policy_rows,
              "blackcat": {"spawn": list(bc["children"]),
                           "mcp": [t[5:] for t in bc["tools"] if t.startswith("mcp__")],
                           "max_shell_reads_per_prompt": BLACKCAT_SHELL_READS},
              "builtin_types": list(BUILTIN_TYPES)}
    blackcat = {"model": efforts[BLACKCAT]["model"], "effort": efforts[BLACKCAT]["effort"],
                "instructions": rename(bc_text.strip() + "\n")}

    # opt-in Astra roles (DESIGN §2.1)
    astra_model = models["astra"]["model"]
    astra_roles, astra_entries = {}, {}
    for name in models["astra"]["agents"]:
        if name == BLACKCAT or name not in agents:
            raise BuildError("models.toml [astra] agents: %r is no role" % name)
        row = effort_table.get(name)
        fable = row.get("fable") if isinstance(row, dict) else None
        if fable not in models["effort"]["levels"] or fable not in models["accepted"][astra_model]:
            raise BuildError("agent_effort.json %s fable = %r: not an effort %s accepts" % (name, fable, astra_model))
        rname = role_name(name, style)
        astra_roles[rname] = dict(roles[rname], model=astra_model, model_reasoning_effort=fable)
        astra_entries[rname] = {"description": entries[rname]["description"],
                                "config_file": "%s/stack/agents-astra/%s.toml" % (codex_home, rname)}

    # MCP servers, merged
    servers, origin, mcp_dropped = {}, {}, {}
    for name in sorted(agents):
        a = agents[name]
        for sid, spec in a["mcp"]:
            table, gone = _mcp_table(sid, spec, ctx, a["label"])
            if gone:
                mcp_dropped["%s:%s" % (name, sid)] = gone
            if sid in servers and servers[sid] != table:
                raise BuildError("MCP server %r is defined differently by %s and %s"
                                 % (sid, ", ".join(origin[sid]), name))
            servers.setdefault(sid, table)
            origin.setdefault(sid, []).append(name)
    servers = {k: servers[k] for k in sorted(servers)}

    report = {"agents": len(agents), "roles": len(roles), "astra_roles": sorted(astra_roles),
              "name_style": style, "effort": efforts, "dropped": dropped, "mcp_dropped": mcp_dropped,
              "mcp_servers": {k: origin[k] for k in sorted(origin)}}
    return {"roles": roles, "astra_roles": astra_roles, "agents_entries": entries,
            "astra_entries": astra_entries, "policy": policy, "mcp_servers": servers,
            "blackcat": blackcat, "report": report}
