"""render_profile: the stack's Codex profile, its codex-astra copy and the --ide-default regions.

Entry point (INTERFACES.md §3-B): build(parts, opts) -> dict with keys
- `codex`: the full profile dict (DESIGN.md §3 first row). Root keys `model`,
  `model_reasoning_effort` (BlackCat), `approval_policy`, `default_permissions` (or `sandbox_mode`),
  `developer_instructions` (R + "\\n\\n" + the BlackCat body), `web_search`,
  `tool_output_token_limit`; tables `[features]`, `[agents]` (limits + one `{description,
  config_file}` entry per role), `[mcp_servers.*]`, `[permissions.claude-agent-stack]`, `[skills]`,
  `[shell_environment_policy]`, `[hooks]` (the guard, plus the carried-over `hooks.state`).
- `codex_astra`: a full copy of `codex` in which only the six astra roles' `config_file` point at
  `stack/agents-astra/` (profiles overlay config.toml, not each other: F1); None with
  `no_astra_profile`.
- `region_a` / `region_b`: what --ide-default puts in config.toml (DESIGN §7.6): A = the profile's
  root keys only, B = its tables only (`hooks.state` excluded: Codex keeps config.toml's own).
  They are ALWAYS computed, so --diff can show them; the installer writes them only when
  opts["ide_default"] is true. In that mode merge(region_a, region_b) == codex exactly.
- `codex_ide`: the text of codex.config.toml under --ide-default (so `--profile codex` still
  works): comments, then the carried-over `[hooks.state]` tables when there are any (U1: Codex may
  write trust into the active profile file); None without ide_default.
- `codex_astra_ide`: the codex-astra overlay under --ide-default, only the six
  `[agents.<role>] config_file` entries plus the carried-over `hooks.state` (if any); None without
  ide_default or with no_astra_profile.

What the installer writes: without ide_default, `codex` and `codex_astra` (whole files); with it,
`codex_ide`, `codex_astra_ide` and the two regions. `codex`/`codex_astra` are still returned in
ide mode, as the reference the regions were cut from; neither carries `hooks.state` then, and no
written profile carries a hook handler (hooks load from every layer, F3: the guard would run twice);
the written ones carry only `hooks.state`.

Parts (all required, nothing else accepted): `blackcat` {model, effort, instructions};
`rules_text` (R); `agents_entries` {role: {description, config_file}}; `astra_entries` (the six,
same shape, config_file under `agents-astra/`; may be empty with no_astra_profile);
`mcp_servers` {id: final [mcp_servers.<id>] table}; `permissions` (permissions.permission_profile);
`hooks` (hook_defs.hooks_table, no `state`); `hooks_state` (the live profile files' [hooks.state],
re-emitted verbatim; {} when none; merge_hooks_state(*states, owners=(prefix, ...)) joins the codex
and codex-astra files' tables, whose keys embed their source path: every written file carries the
union, and when Codex later changes a key's record in one file only, the record from the file the key
names wins; a differing key neither file owns is refused); `skills_max_context_tokens`.
Opts (each a bool, absent = false, nothing else accepted): `legacy_sandbox` (sandbox_mode =
"workspace-write" replaces default_permissions + [permissions.*], and features.network_proxy goes
with them), `no_escalation` (approval_policy = "never"), `no_mcp` (no [mcp_servers]),
`with_rollout_budget` (features.rollout_budget = true; DESIGN §5 names the feature only, no limits),
`ide_default`, `no_astra_profile`.

Static keys live in templates/profile.base.toml (its root keys are fixed: TEMPLATE_KEYS). The
shell_environment_policy there is the port of settings.json sandbox.credentials.envVars (filters,
the schema's canonical keyed form). Unknown or malformed input raises BuildError, never a guess.
Stdlib only, Python >= 3.11 (tomllib). Serialization is toml_emit's.

Seeded-bug proofs (tests/mutations/render_profile.json; each turns the named test red): keep [hooks]
in the codex-astra overlay under ide_default; let region A hold a table; accept a 7th astra entry;
drop features.network_proxy from the template; keep default_permissions under legacy_sandbox; drop
the carried-over hooks.state; drop shell_environment_policy; copy the astra profile shallowly (the
codex profile's entries move too); put the BlackCat body before R; leave hooks.state in region B;
keep hooks.state in the reference profile under ide_default; drop hooks.state from the ide-mode
codex profile text, or from the ide-mode codex-astra overlay; let a non-owning file's record win a
hooks.state clash.
"""
from __future__ import annotations

import copy
import importlib.util
import re
import tomllib
from pathlib import Path


def _load(name):
    """A sibling module loaded by file path (CWE-427: never through sys.path)."""
    path = Path(__file__).resolve().parent / ("%s.py" % name)
    spec = importlib.util.spec_from_file_location("codex_config_%s_for_profile" % name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_toml = _load("toml_emit")

__all__ = ["BuildError", "build", "load_template", "merge_hooks_state", "TEMPLATE", "PARTS", "OPTS",
           "PERMISSION_PROFILE", "ASTRA_COUNT", "TEMPLATE_KEYS", "IDE_PROFILE_TEXT"]

TEMPLATE = Path(__file__).resolve().parent.parent / "templates" / "profile.base.toml"
PERMISSION_PROFILE = "claude-agent-stack"          # = permissions.PROFILE_NAME (pinned by a test)
ASTRA_COUNT = 6                                    # models.toml astra.agents (DESIGN §2.1)
SKILLS_TOKEN_CAP = 10000                           # "capped at 10000 tokens" (F17)
PARTS = ("blackcat", "rules_text", "agents_entries", "astra_entries", "mcp_servers", "permissions",
         "hooks", "hooks_state", "skills_max_context_tokens")
OPTS = ("legacy_sandbox", "no_escalation", "no_mcp", "with_rollout_budget", "ide_default",
        "no_astra_profile")
TEMPLATE_KEYS = ("approval_policy", "default_permissions", "web_search", "tool_output_token_limit",
                 "features", "agents", "shell_environment_policy")
# [agents] keys that are settings, not roles (config.schema.json AgentsToml)
AGENTS_SETTINGS = frozenset({"enabled", "max_depth", "max_concurrent_threads_per_session",
                             "default_subagent_model", "default_subagent_reasoning_effort",
                             "interrupt_message"})
BUILTIN_ROLES = frozenset({"default", "worker", "explorer"})   # the guard refuses them (DESIGN §5)
ROLE_ENTRY_KEYS = frozenset({"description", "config_file"})
# config.schema.json HooksToml events, RawMcpServerConfig and PermissionProfileToml keys (pinned)
HOOK_EVENTS = frozenset({"Interrupt", "PermissionRequest", "PostCompact", "PostToolUse", "PreCompact",
                         "PreToolUse", "SessionEnd", "SessionStart", "Stop", "SubagentStart",
                         "SubagentStop", "UserPromptSubmit"})
MCP_KEYS = frozenset({"args", "auth", "bearer_token_env_var", "command", "cwd",
                      "default_tools_approval_mode", "disabled_tools", "enabled", "enabled_tools",
                      "env", "env_http_headers", "env_vars", "environment_id", "http_headers",
                      "http_headers_helper", "name", "oauth", "oauth_resource", "omit_tools_from",
                      "required", "scopes", "startup_readiness", "startup_timeout_ms",
                      "startup_timeout_sec", "supports_parallel_tool_calls",
                      "tool_input_schema_max_bytes", "tool_timeout_sec", "tools", "url"})
PERMISSION_KEYS = frozenset({"description", "extends", "filesystem", "network", "workspace_roots"})
IDE_PROFILE_TEXT = (
    "# claude-agent-stack: profile `codex`, installed with --ide-default.\n"
    "# The stack's settings live in the two marked regions of config.toml, so every Codex session\n"
    "# (CLI, IDE, desktop app) uses them; this file only keeps `codex --profile codex` working.\n"
    "# It holds no [hooks]: hooks load from every config layer, so the guard would run twice.\n"
    "# Owned by codex_config/install.sh: edits are overwritten; your settings go in config.toml.\n"
)

_ROLE = re.compile(r"[a-z0-9][a-z0-9_-]*\Z")
_ID = re.compile(r"[A-Za-z0-9_-]+\Z")
_BAD = re.compile(r"[\x00-\x1f\x7f]")


class BuildError(Exception):
    """The parts, opts or template cannot be turned into a profile (never guessed)."""


# ------------------------------------------------------------------------------------- inputs


def _text(v, what):
    if not isinstance(v, str) or not v.strip():
        raise BuildError("%s must be a non-empty string, got %r" % (what, v))
    return v


def _opts(opts):
    if not isinstance(opts, dict):
        raise BuildError("opts must be a dict")
    unknown = sorted(set(opts) - set(OPTS))
    if unknown:
        raise BuildError("unknown opts: %s" % ", ".join(map(str, unknown)))
    out = {}
    for k in OPTS:
        v = opts.get(k, False)
        if not isinstance(v, bool):
            raise BuildError("opts[%r] must be a bool, got %r" % (k, v))
        out[k] = v
    return out


def _role_path(name, path, folder, what):
    """config_file must end in <folder>/<name>.toml (absolute, or relative to the profile file);
    returns its prefix (the stack directory part)."""
    if not isinstance(path, str) or not path or _BAD.search(path):
        raise BuildError("%s: config_file must be a path string, got %r" % (what, path))
    parts = path.split("/")
    if ".." in parts or "." in parts or "" in parts[1:]:
        raise BuildError("%s: config_file %r is not a normalized path" % (what, path))
    if len(parts) < 2 or parts[-2:] != [folder, name + ".toml"]:
        raise BuildError("%s: config_file %r must end in %s/%s.toml" % (what, path, folder, name))
    return "/".join(parts[:-2])


def _entries(entries, what, folder):
    if not isinstance(entries, dict):
        raise BuildError("%s must be a dict {role: {description, config_file}}" % what)
    out = {}
    for name, e in entries.items():
        w = "%s[%r]" % (what, name)
        if not isinstance(name, str) or not _ROLE.match(name):
            raise BuildError("%s: role names are lowercase [a-z0-9_-]" % w)
        if name in AGENTS_SETTINGS or name in BUILTIN_ROLES or name == "blackcat":
            raise BuildError("%s: %r is reserved (an [agents] setting, a built-in role or the main "
                             "thread)" % (w, name))
        if not isinstance(e, dict):
            raise BuildError("%s must be a table" % w)
        extra = sorted(set(e) - ROLE_ENTRY_KEYS)
        if extra:
            raise BuildError("%s: unknown keys %s" % (w, ", ".join(map(str, extra))))
        if "config_file" not in e:
            raise BuildError("%s: config_file is missing" % w)
        _role_path(name, e["config_file"], folder, w)
        if "description" in e:
            _text(e["description"], w + ".description")
        out[name] = e
    return out


def _hooks(h):
    if not isinstance(h, dict) or not h:
        raise BuildError("hooks must be the non-empty hook_defs.hooks_table() table")
    if "state" in h:
        raise BuildError("hooks must not carry `state`: the carried-over trust is hooks_state")
    for event, groups in h.items():
        if event not in HOOK_EVENTS:
            raise BuildError("hooks: unknown event %r" % (event,))
        if not isinstance(groups, list) or not groups:
            raise BuildError("hooks.%s must be a non-empty list of matcher groups" % event)
        for g in groups:
            if not isinstance(g, dict) or set(g) - {"matcher", "hooks"}:
                raise BuildError("hooks.%s: a matcher group holds only matcher and hooks" % event)
            hs = g.get("hooks")
            if not isinstance(hs, list) or not hs or not all(isinstance(x, dict) and "type" in x
                                                             for x in hs):
                raise BuildError("hooks.%s: each group needs a non-empty hooks list of handlers"
                                 % event)
    return h


def _hooks_state(s):
    if not isinstance(s, dict):
        raise BuildError("hooks_state must be a dict (the live [hooks.state] table, {} if none)")
    for k, v in s.items():
        if not isinstance(k, str) or not k or not isinstance(v, dict):
            raise BuildError("hooks_state[%r] must be a table" % (k,))
        if "trusted_hash" in v and not isinstance(v["trusted_hash"], str):
            raise BuildError("hooks_state[%r].trusted_hash must be a string" % k)
        if "enabled" in v and not isinstance(v["enabled"], bool):
            raise BuildError("hooks_state[%r].enabled must be a bool" % k)
    return s


def _parts(parts):
    if not isinstance(parts, dict):
        raise BuildError("parts must be a dict")
    unknown = sorted(map(str, set(parts) - set(PARTS)))
    if unknown:
        raise BuildError("unknown parts: %s" % ", ".join(unknown))
    missing = [k for k in PARTS if k not in parts]
    if missing:
        raise BuildError("missing parts: %s" % ", ".join(missing))
    bc = parts["blackcat"]
    if not isinstance(bc, dict) or set(bc) != {"model", "effort", "instructions"}:
        raise BuildError("blackcat must be {model, effort, instructions}")
    for k in ("model", "effort", "instructions"):
        _text(bc[k], "blackcat.%s" % k)
    _text(parts["rules_text"], "rules_text")
    agents = _entries(parts["agents_entries"], "agents_entries", "agents")
    if not agents:
        raise BuildError("agents_entries is empty")
    for name, e in agents.items():
        if "description" not in e:
            raise BuildError("agents_entries[%r]: description is missing" % name)
    _entries(parts["astra_entries"], "astra_entries", "agents-astra")
    mcp = parts["mcp_servers"]
    if not isinstance(mcp, dict):
        raise BuildError("mcp_servers must be a dict {id: table}")
    for sid, t in mcp.items():
        if not isinstance(sid, str) or not _ID.match(sid):
            raise BuildError("mcp_servers: bad server id %r" % (sid,))
        if not isinstance(t, dict) or not t:
            raise BuildError("mcp_servers[%r] must be a non-empty table" % sid)
        extra = sorted(set(t) - MCP_KEYS)
        if extra:
            raise BuildError("mcp_servers[%r]: keys Codex does not know: %s" % (sid, ", ".join(extra)))
    perm = parts["permissions"]
    if not isinstance(perm, dict) or not perm:
        raise BuildError("permissions must be the permission_profile() table")
    extra = sorted(set(perm) - PERMISSION_KEYS)
    if extra:
        raise BuildError("permissions: keys Codex does not know: %s" % ", ".join(map(str, extra)))
    _hooks(parts["hooks"])
    _hooks_state(parts["hooks_state"])
    n = parts["skills_max_context_tokens"]
    if isinstance(n, bool) or not isinstance(n, int) or not 1 <= n <= SKILLS_TOKEN_CAP:
        raise BuildError("skills_max_context_tokens must be an int in 1..%d, got %r"
                         % (SKILLS_TOKEN_CAP, n))
    return parts


def _astra(parts, opts):
    """The six {role: astra config_file} overrides, or None with no_astra_profile."""
    astra, agents = parts["astra_entries"], parts["agents_entries"]
    if opts["no_astra_profile"]:
        return None
    if len(astra) != ASTRA_COUNT:
        raise BuildError("astra_entries holds %d roles; the codex-astra profile swaps exactly %d "
                         "(models.toml astra.agents)" % (len(astra), ASTRA_COUNT))
    out = {}
    for name, e in astra.items():
        if name not in agents:
            raise BuildError("astra_entries[%r] is not a role of agents_entries" % name)
        if "description" in e and e["description"] != agents[name]["description"]:
            raise BuildError("astra_entries[%r]: only config_file may differ from agents_entries"
                             % name)
        base = _role_path(name, agents[name]["config_file"], "agents", "agents_entries")
        if _role_path(name, e["config_file"], "agents-astra", "astra_entries") != base:
            raise BuildError("astra_entries[%r]: config_file must sit next to stack/agents/ (%r)"
                             % (name, base))
        out[name] = e["config_file"]
    return out


def load_template(path=TEMPLATE) -> dict:
    """The static keys (templates/profile.base.toml), checked: exactly TEMPLATE_KEYS at the root."""
    try:
        with open(path, "rb") as f:
            base = tomllib.load(f)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise BuildError("profile template %s: %s" % (path, exc)) from None
    if set(base) != set(TEMPLATE_KEYS):
        raise BuildError("profile template root keys must be %s, got %s"
                         % (", ".join(TEMPLATE_KEYS), ", ".join(base)))
    if base["default_permissions"] != PERMISSION_PROFILE:
        raise BuildError("profile template: default_permissions must be %r" % PERMISSION_PROFILE)
    for k in ("features", "agents", "shell_environment_policy"):
        if not isinstance(base[k], dict):
            raise BuildError("profile template: %s must be a table" % k)
    roles = [k for k, v in base["agents"].items() if isinstance(v, dict) or k not in AGENTS_SETTINGS]
    if roles:
        raise BuildError("profile template: [agents] may hold settings only, not %s" % roles)
    return base


def merge_hooks_state(*states, owners=()) -> dict:
    """The union of several [hooks.state] tables (each from tomllib; None = no file). owners[i], when
    given, is the key prefix of states[i]'s own file (`"<codex_home>/<rel>:"`: a trust key embeds its
    source path). Every written profile file carries the union, so Codex re-trusting or disabling a
    key in one file only (U1) leaves two records of it: the record from the file the key names wins.
    The same key with two different records and no owning file among them is refused."""
    if len(owners) > len(states):
        raise BuildError("merge_hooks_state: %d owners for %d states" % (len(owners), len(states)))
    out, owned = {}, set()
    for i, s in enumerate(states):
        if s is None:
            continue
        prefix = owners[i] if i < len(owners) else None
        for k, v in _hooks_state(s).items():
            mine = bool(prefix) and k.startswith(prefix)
            if k in out and out[k] != v:
                if k in owned and not mine:
                    continue                      # the owner's record, already in
                if not mine:
                    raise BuildError("hooks.state[%r] differs between the live profile files" % k)
            if mine:
                owned.add(k)
            out[k] = copy.deepcopy(v)
    return out


# -------------------------------------------------------------------------------------- build


def _developer_instructions(rules_text, body):
    return rules_text.rstrip("\n") + "\n\n" + body.strip("\n") + "\n"


def build(parts: dict, opts: dict) -> dict:
    o = _opts(opts)
    p = _parts(parts)
    astra = _astra(p, o)
    base = load_template()
    bc = p["blackcat"]

    codex = {"model": bc["model"], "model_reasoning_effort": bc["effort"]}
    codex["approval_policy"] = "never" if o["no_escalation"] else base["approval_policy"]
    codex["default_permissions"] = base["default_permissions"]
    if o["legacy_sandbox"]:
        del codex["default_permissions"]
        codex["sandbox_mode"] = "workspace-write"
    codex["developer_instructions"] = _developer_instructions(p["rules_text"], bc["instructions"])
    codex["web_search"] = base["web_search"]
    codex["tool_output_token_limit"] = base["tool_output_token_limit"]

    features = copy.deepcopy(base["features"])
    if o["legacy_sandbox"]:
        features.pop("network_proxy", None)       # it only serves the permission profile's network
    if o["with_rollout_budget"]:
        features["rollout_budget"] = True
    codex["features"] = features

    agents = copy.deepcopy(base["agents"])
    for name, e in p["agents_entries"].items():
        agents[name] = {"description": e["description"], "config_file": e["config_file"]}
    codex["agents"] = agents
    if not o["no_mcp"] and p["mcp_servers"]:
        codex["mcp_servers"] = copy.deepcopy(p["mcp_servers"])
    if not o["legacy_sandbox"]:
        codex["permissions"] = {PERMISSION_PROFILE: copy.deepcopy(p["permissions"])}
    codex["skills"] = {"max_context_tokens": p["skills_max_context_tokens"]}
    codex["shell_environment_policy"] = copy.deepcopy(base["shell_environment_policy"])
    hooks = copy.deepcopy(p["hooks"])
    if p["hooks_state"] and not o["ide_default"]:
        hooks["state"] = copy.deepcopy(p["hooks_state"])
    codex["hooks"] = hooks

    codex_astra = None
    if astra is not None:
        codex_astra = copy.deepcopy(codex)
        for name, path in astra.items():
            codex_astra["agents"][name]["config_file"] = path

    region_a = {k: copy.deepcopy(v) for k, v in codex.items() if not isinstance(v, dict)}
    region_b = {k: copy.deepcopy(v) for k, v in codex.items() if isinstance(v, dict)}
    region_b["hooks"].pop("state", None)

    codex_ide = codex_astra_ide = None
    if o["ide_default"]:
        # U1: Codex may write /hooks trust into the active profile file, so the carried-over
        # [hooks.state] stays in both written profile files (state only, never a handler)
        state = {"hooks": {"state": copy.deepcopy(p["hooks_state"])}} if p["hooks_state"] else None
        codex_ide = IDE_PROFILE_TEXT + ("\n" + _toml.dumps(state) if state else "")
        if astra is not None:
            codex_astra_ide = {"agents": {n: {"config_file": path} for n, path in astra.items()}}
            if state:
                codex_astra_ide["hooks"] = copy.deepcopy(state["hooks"])
    return {"codex": codex, "codex_astra": codex_astra, "region_a": region_a, "region_b": region_b,
            "codex_ide": codex_ide, "codex_astra_ide": codex_astra_ide}
