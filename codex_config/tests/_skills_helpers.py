"""Helpers for test_translate.py and test_convert_skills.py: the libs, a target ctx, the corpus, and a
scratch skill source tree. Nothing here touches a real ~/.codex, ~/.agents or ~/.claude: the ctx paths
are target strings only; files are written under the tmp dirs the tests pass in."""
from __future__ import annotations

import json
import os
from pathlib import Path

from conftest import REPO, load_lib

translate = load_lib("translate")
convert_skills = load_lib("convert_skills")

AGENTS = REPO / "dot-claude" / "agents"
SKILLS = REPO / "dot-claude" / "skills"
SETTINGS = REPO / "dot-claude" / "settings.json"
RULES_TEMPLATE = REPO / "codex_config" / "templates" / "rules.md"
REQUIREMENTS = REPO / "requirements"

# A realistic target: listing paths have the length of a real home (the budget counts them).
HOME = "/Users/someuser1"


def target_ctx(home: str = HOME, modules=None, **extra) -> dict:
    ch = home + "/.codex"
    ctx = {"codex_home": ch, "home": home, "stack": ch + "/stack",
           "state_dir": home + "/.local/state/codex-agent-stack", "profile_name": "codex", "uv": "uv",
           "skills_root": home + "/.agents/skills"}
    if modules is not None:
        ctx["skill_modules"] = frozenset(modules)
    ctx.update(extra)
    return ctx


def overrides() -> dict:
    return json.loads(SETTINGS.read_text())["skillOverrides"]


def corpus_modules() -> set:
    so = overrides()
    return {n for n in os.listdir(SKILLS) if so.get(n) in ("user-invocable-only", "off")}


def agent_bodies() -> dict:
    """{"agents/<n>.md": body} with the frontmatter blanked (line numbers kept), as B1 passes them."""
    out = {}
    for p in sorted(AGENTS.glob("*.md")):
        if p.stem in ("equilibrium",):                  # convert_agents.NOT_PORTED
            continue
        text = p.read_text(encoding="utf-8")
        _, fm, body = text.split("---", 2)
        out["agents/" + p.name] = "\n" * (fm.count("\n")) + body
    return out


def installed_skill_texts() -> dict:
    """{"skills/<n>/<rel>": text} for every .md of every skill convert_skills installs."""
    cls = convert_skills.classify(str(REPO))
    out = {}
    for n in cls["listed"] + cls["modules"]:
        for p in sorted((SKILLS / n).rglob("*.md")):
            out["skills/%s/%s" % (n, p.relative_to(SKILLS / n).as_posix())] = p.read_text(encoding="utf-8")
    return out


def skill_md(name: str, desc: str, body: str = "", **extra) -> str:
    head = "".join("%s: %s\n" % kv for kv in extra.items())
    return "---\nname: %s\ndescription: %s\n%s---\n# %s\n%s" % (name, desc, head, name, body)


def make_src(root: Path, skills: dict, so: dict) -> Path:
    """A snapshot root: root/dot-claude/skills/<n>/<rel> from {n: {rel: str|bytes|(bytes, mode)}}
    and settings.json with skillOverrides `so`."""
    sk = root / "dot-claude" / "skills"
    sk.mkdir(parents=True)
    for n, files in skills.items():
        for rel, content in files.items():
            p = sk / n / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            mode = 0o644
            if isinstance(content, tuple):
                content, mode = content
            if isinstance(content, str):
                p.write_text(content, encoding="utf-8")
            else:
                p.write_bytes(content)
            p.chmod(mode)
    (root / "dot-claude" / "settings.json").write_text(json.dumps({"skillOverrides": so}))
    return root


HUB_NOTE = "`*` = not in the skill listing: Read `__CLAUDE_DIR__/skills/<name>/SKILL.md` (the Skill tool won't load it)."


def hub_body(*modules: str) -> str:
    rows = "".join("| `%s`* | when %s |\n" % (m, m) for m in modules)
    return "\n## Modules\n| Module | Load when |\n|---|---|\n%s\n%s\n" % (rows, HUB_NOTE)
