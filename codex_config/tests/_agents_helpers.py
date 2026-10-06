"""Shared helpers for the agent-converter tests (part B1: convert_agents, models.toml, codex-mcp-headers).

Nothing here touches the real ~/.codex, ~/.agents or ~/.claude: contexts point at scratch paths under
pytest's tmp dirs, the converter only reads the repository's dot-claude/agents and agent_effort.json
(or a scratch copy), and agent_guard.py is imported by path for its tables only.
"""
from __future__ import annotations

import copy
import importlib.util
import json
import shutil
import sys
import tomllib
from pathlib import Path

from conftest import CODEX_CONFIG, REPO, VENDOR, load_lib

ca = load_lib("convert_agents")
# Hub-module names for translate (the full-repo classification; scratch sources carry no skills/).
SKILL_MODULES = frozenset(load_lib("convert_skills").classify(str(REPO))["modules"])
AGENTS_DIR = REPO / "dot-claude" / "agents"
EFFORT_JSON = REPO / "dot-claude" / "hooks" / "agent_effort.json"
AGENT_GUARD = REPO / "dot-claude" / "hooks" / "agent_guard.py"
MODELS_TOML = CODEX_CONFIG / "models.toml"
HEADERS_BIN = CODEX_CONFIG / "bin" / "codex-mcp-headers"
RULES_MD = CODEX_CONFIG / "templates" / "rules.md"
SCHEMA = json.loads((VENDOR / "config.schema.json").read_text())
VENDORED_MODELS = json.loads((VENDOR / "models.gpt6.json").read_text())
SIX = {"ninja-coder", "main-coder", "mathematician", "planner", "proof-checker", "security-auditor"}
LEVELS = ["low", "medium", "high", "xhigh", "max"]


def ctx_for(root: Path) -> dict:
    home = Path(root) / "home"
    ch = home / ".codex"
    return {"codex_home": str(ch), "home": str(home), "stack": str(ch / "stack"),
            "state_dir": str(home / ".local" / "state" / "codex-agent-stack"), "profile_name": "codex",
            "uv": str(home / ".local" / "bin" / "uv"), "skills_root": str(home / ".agents" / "skills"),
            "npx": "/opt/node/bin/npx", "stack_repo": "/r",
            "skill_modules": SKILL_MODULES}


def models(**edits) -> dict:
    """models.toml as loaded, deep-copied, with `section.key=value` style edits: models(effort={...})
    merges the dict into that section."""
    m = copy.deepcopy(ca.load_models(str(MODELS_TOML)))
    for section, patch in edits.items():
        m[section].update(patch)
    return m


def raw_models() -> dict:
    with open(MODELS_TOML, "rb") as f:
        return tomllib.load(f)


def scratch_src(root: Path, agent_edits: dict | None = None, effort_edits: dict | None = None,
                extra_agents: dict | None = None) -> Path:
    """A scratch snapshot root: dot-claude/agents (copied, each edit a callable text -> text or a
    (old, new) pair applied once) and dot-claude/hooks/agent_effort.json (rows merged)."""
    src = Path(root) / "src"
    adir = src / "dot-claude" / "agents"
    shutil.copytree(AGENTS_DIR, adir)
    for name, edit in (agent_edits or {}).items():
        p = adir / ("%s.md" % name)
        text = p.read_text()
        if callable(edit):
            new = edit(text)
        else:
            old, rep = edit
            assert text.count(old) == 1, (name, old)
            new = text.replace(old, rep)
        p.write_text(new)
    for name, text in (extra_agents or {}).items():
        (adir / ("%s.md" % name)).write_text(text)
    eff = json.loads(EFFORT_JSON.read_text())
    for name, row in (effort_edits or {}).items():
        eff["agents"].setdefault(name, {}).update(row)
    hooks = src / "dot-claude" / "hooks"
    hooks.mkdir(parents=True)
    (hooks / "agent_effort.json").write_text(json.dumps(eff))
    return src


def frontmatter(name: str) -> dict:
    fields, _body, _n = ca.parse_frontmatter((AGENTS_DIR / ("%s.md" % name)).read_text(), name)
    return {k: v for k, (_line, v) in fields.items()}


def agent_names() -> list:
    return sorted(p.stem for p in AGENTS_DIR.glob("*.md"))


def walk_strings(obj):
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for k, v in obj.items():
            yield k
            yield from walk_strings(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from walk_strings(v)


def load_agent_guard():
    """dot-claude/hooks/agent_guard.py imported by file path (tables only; nothing is run)."""
    spec = importlib.util.spec_from_file_location("agent_guard_for_codex_contract", AGENT_GUARD)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def conversion(tmp_path_factory):
    """(ctx, output) of one conversion of the repository's agents with models.toml as shipped; each
    test module wraps it in its own module-scoped `converted` fixture."""
    ctx = ctx_for(tmp_path_factory.mktemp("conv"))
    return ctx, ca.convert(str(REPO), ctx, ca.load_models(str(MODELS_TOML)))
