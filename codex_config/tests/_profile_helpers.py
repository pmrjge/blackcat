"""Shared helpers for the render_profile tests (part B3): synthetic parts shaped like INTERFACES.md §3,
a strict checker against the vendored config.schema.json, and key-path utilities.

Nothing here touches the real ~/.codex, ~/.agents, ~/.claude or /etc: paths are scratch strings, the
only repository files read are dot-claude/settings.json and the agent file names (read-only inputs).
"""
from __future__ import annotations

import copy
import json
import tomllib

from conftest import REPO, VENDOR, load_lib

SCHEMA = json.loads((VENDOR / "config.schema.json").read_text())
DEFS = SCHEMA["definitions"]
SETTINGS = json.loads((REPO / "dot-claude" / "settings.json").read_text())
ASTRA = ("ninja-coder", "main-coder", "mathematician", "planner", "proof-checker", "security-auditor")
CODEX_HOME = "/scratch/home/.codex"
STACK = CODEX_HOME + "/stack"
STUB = STACK + "/bin/codex-hook"


def role_names() -> list:
    """The 56 roles: every dot-claude agent but the main thread."""
    names = sorted(p.stem for p in (REPO / "dot-claude" / "agents").glob("*.md"))
    return [n for n in names if n not in ("blackcat", "equilibrium")]   # equilibrium: convert_agents.NOT_PORTED


def parts(**over) -> dict:
    """Synthetic parts matching INTERFACES §3 (what convert_agents, permissions, hook_defs give)."""
    hd = load_lib("hook_defs")
    agents = {n: {"description": "The %s role." % n, "config_file": "%s/agents/%s.toml" % (STACK, n)}
              for n in role_names()}
    astra = {n: {"description": agents[n]["description"],
                 "config_file": "%s/agents-astra/%s.toml" % (STACK, n)} for n in ASTRA}
    out = {
        "blackcat": {"model": "gpt-6-luna", "effort": "high",
                     "instructions": "You are BlackCat, the main thread: you only delegate.\n"},
        "rules_text": "# claude-agent-stack rules\n- Never push.\n",
        "agents_entries": agents,
        "astra_entries": astra,
        "mcp_servers": {
            "jina": {"url": "https://mcp.jina.ai/sse",
                     "http_headers_helper": STACK + "/bin/mcp-headers jina",
                     "omit_tools_from": ["direct"]},
            "libdocs": {"command": STACK + "/bin/with-stack-env",
                        "args": ["uv", "run", STACK + "/mcp/libdocs/server.py"],
                        "default_tools_approval_mode": "auto"},
        },
        "permissions": {
            "description": "claude-agent-stack test profile",
            "extends": ":workspace",
            "filesystem": {CODEX_HOME: "read", CODEX_HOME + "/auth.json": "deny",
                           ":workspace_roots": {"**/.env": "deny"}},
            "network": {"enabled": True, "mode": "full",
                        "domains": {"pypi.org": "allow", "*.hf.co": "allow"}},
        },
        "hooks": hd.hooks_table(STUB),
        "hooks_state": {},
        "skills_max_context_tokens": 6000,
    }
    out.update(copy.deepcopy(over))
    return out


TRUST = {CODEX_HOME + "/codex.config.toml:pre_tool_use:0:0": {"trusted_hash": "sha256:" + "a" * 64},
         CODEX_HOME + "/codex.config.toml:session_end:0:0": {"trusted_hash": "sha256:" + "b" * 64,
                                                             "enabled": True}}


def denied_env_vars() -> list:
    envs = SETTINGS["sandbox"]["credentials"]["envVars"]
    assert all(e["mode"] == "deny" for e in envs), envs
    return [e["name"] for e in envs]


def roundtrip(doc: dict) -> dict:
    te = load_lib("toml_emit")
    return tomllib.loads(te.dumps(doc))


def leaves(doc, prefix=()):
    """{key path tuple: leaf value}; arrays of tables and lists are leaves (compared whole)."""
    out = {}
    for k, v in doc.items():
        if isinstance(v, dict) and v:
            out.update(leaves(v, prefix + (k,)))
        else:
            out[prefix + (k,)] = v
    return out


def changed_paths(a: dict, b: dict) -> set:
    la, lb = leaves(a), leaves(b)
    return {p for p in set(la) | set(lb) if la.get(p, KeyError) != lb.get(p, KeyError)}


# ------------------------------------------------------------- a strict JSON-schema checker
# The vendored schema is schemars output. Two of its object types are flattened maps that schemars
# writes as a bare {"type": "object"}: PermissionsToml (name -> PermissionProfileToml) and the entries
# of FilesystemPermissionsToml (path -> FilesystemPermissionToml), likewise NetworkDomainPermissionsToml
# (domain -> NetworkDomainPermissionToml). OPEN_MAPS supplies their value schema; any other key not
# declared by `properties` or a schema-valued `additionalProperties` is an error ("undeclared"),
# stricter than JSON Schema's default, so every emitted key path is one the schema names.

OPEN_MAPS = {
    "PermissionsToml": {"$ref": "#/definitions/PermissionProfileToml"},
    "FilesystemPermissionsToml": {"$ref": "#/definitions/FilesystemPermissionToml"},
    "NetworkDomainPermissionsToml": {"$ref": "#/definitions/NetworkDomainPermissionToml"},
}
_TYPES = {"object": dict, "string": str, "array": list, "boolean": bool, "integer": int,
          "number": (int, float)}


def _ref(node):
    name = None
    while "$ref" in node:
        name = node["$ref"].rsplit("/", 1)[1]
        node = DEFS[name]
    return node, name


def check(value, node=None, path="$") -> list:
    """Errors of `value` against a schema node (default: the root ConfigToml)."""
    node, name = _ref(SCHEMA if node is None else node)
    errs = []
    for sub in node.get("allOf", []):
        errs += check(value, sub, path)
    for key in ("oneOf", "anyOf"):
        if key in node:
            ok = [s for s in node[key] if not check(value, s, path)]
            if not ok or (key == "oneOf" and len(ok) > 1):
                errs.append("%s: %r matches %d of the %s branches" % (path, value, len(ok), key))
    if "not" in node and not check(value, node["not"], path):
        errs.append("%s: matches a `not` schema %s" % (path, node["not"]))
    if "enum" in node and value not in node["enum"]:
        errs.append("%s: %r not in %s" % (path, value, node["enum"]))
    t = node.get("type")
    if isinstance(t, str) and t in _TYPES:
        if not isinstance(value, _TYPES[t]) or (t in ("integer", "number") and isinstance(value, bool)):
            return errs + ["%s: %r is not %s" % (path, value, t)]
    if isinstance(value, (int, float)) and not isinstance(value, bool) and "minimum" in node \
            and value < node["minimum"]:
        errs.append("%s: %r < minimum %s" % (path, value, node["minimum"]))
    if isinstance(value, str) and len(value) < node.get("minLength", 0):
        errs.append("%s: shorter than %d" % (path, node["minLength"]))
    if isinstance(value, dict):
        for k in node.get("required", []):
            if k not in value:
                errs.append("%s: missing %s" % (path, k))
        branches = "oneOf" in node or "anyOf" in node
        props = node.get("properties", {})
        extra = node.get("additionalProperties")
        if extra is None and name in OPEN_MAPS:
            extra = OPEN_MAPS[name]
        for k, v in value.items():
            p = "%s.%s" % (path, k)
            if k in props:
                errs += check(v, props[k], p)
            elif isinstance(extra, dict):
                errs += check(v, extra, p)
            elif extra is False or (node.get("type") == "object" and not branches
                                    and "allOf" not in node):
                errs.append("%s: key not declared by the schema" % p)
    if isinstance(value, list) and "items" in node:
        for i, v in enumerate(value):
            errs += check(v, node["items"], "%s[%d]" % (path, i))
    return errs
