"""render: one staged CODEX_HOME for the claude-agent-stack's Codex port (INTERFACES.md §2, §3 wave 2).

    render.py --src SRC --stage STAGE --work WORK --codex-home CH --home H [--state-dir D]
              [--profile-name N] [--skills-root P|none] [--uv PATH] [--codex PATH|none] [--with-wandb]
              [--no-agents-md] [--no-mcp] [--legacy-sandbox] [--git-allow-rules] [--no-escalation]
              [--with-rollout-budget] [--ide-default|--no-ide-default] [--no-astra-profile] [--force]

Stdlib only, Python >= 3.11; the sibling modules are loaded by path. SRC is the source snapshot
(dot-claude/, lib/), STAGE a copy of the live CODEX_HOME made by `codex_state.py stage`, WORK the
installer's scratch directory. Nothing is written outside STAGE and WORK (CH is only read: the
AGENTS.md / AGENTS.override.md checks). Exit 0 ok, 1 a build error (stderr), 2 usage.

What it writes (every path inside a generated file is an absolute TARGET path under CH, never a
stage path):
- STAGE/stack/ is cleared and rewritten: agents/<role>.toml (56), agents-astra/<role>.toml (6,
  unless --no-astra-profile), skills/ and skill-modules/ (convert_skills; never the excluded four),
  hooks/ (codex_guard.py + the hooks/SUPPORT_FILES files), bin/ (codex-hook, codex-mcp-headers,
  with-stack-env, mcp-headers, magg-private; 0755), mcp/ (dot-claude/mcp), magg/ (config.json with
  its placeholders rendered, the rest copied), policy/agents.json (§4) and policy/guard.json (§5:
  templates/guard.base.json's keys plus codex_home, home, state_dir, stack, protected_roots,
  credentials, toolsmith_wrapper). with-stack-env, mcp-headers and the Python MCP servers find
  stack.env one level higher than in the Claude layout (<CH>/stack.env, not <CH>/stack/stack.env):
  that one path is adapted, nothing else; the servers' `~/.claude/stack.env` fallback is dropped
  (error texts name <CODEX_HOME>/stack.env) and image-studio's protected config dir is CODEX_HOME
  (was CLAUDE_CONFIG_DIR / ~/.claude). bin/stack-install (the toolsmith wrapper guard.json names)
  is copied byte-exact, 0755: it loads ../hooks/toolsmith_policy.py (staged from SUPPORT_FILES) and
  shares the guard's ticket folder (both use toolsmith_policy.state_dir).
- Profile files. --profile-name N (default codex) writes `<N>.config.toml` and
  `<N>-astra.config.toml` (Codex reads profile N from $CODEX_HOME/N.config.toml, DESIGN §3); the
  live files of those names are the ones whose [hooks.state] is carried over (§7.4). Any other
  table or key the stack does not write in a live profile file stops the run, naming it.
  --no-astra-profile removes the staged astra file. Under --ide-default the codex file is the
  comment-only form and the astra file the six-entry overlay, both with the carried trust records.
- rules/claude-agent-stack.rules (convert_rules), then `codex execpolicy check` on every example
  (--codex PATH; default `codex` from PATH; `none` or not found: skipped with a warning); any
  disagreement stops the run.
- AGENTS.md: the stack's block (claude_md_block with NAME = "AGENTS.md", templates/AGENTS.block.md);
  --no-agents-md ships no block (an earlier one is removed). An AGENTS.override.md in CH shadows
  AGENTS.md: reported as a warning.
- stack.env: seeded 0600 from SRC/lib/stack.env.example only when the stage has none.
- config.toml regions (DESIGN §7.6). --ide-default splices region A (root keys) at the very start
  and region B (tables) at the end (config_region.splice: no key on both sides and
  tomllib(result) == merge(user, stack), else exit 1 naming the keys); a symlinked config.toml is
  refused. --no-ide-default removes exactly the two regions. DECISION, neither flag: the mode of the
  last install is kept. When config.toml holds the stack's regions they are re-rendered in place
  (options.json `ide_default_source` = "kept"); without regions the file is not touched (bytes
  unchanged, source "default"). Drift: a region present in config.toml whose sha256 differs from
  the old manifest's `regions` (and from what this run would write) stops the run with a unified
  diff unless --force; no old manifest = every existing region counts as changed.
- MCP: the agents' frontmatter servers plus convert_agents.user_scope_servers(ctx, --with-wandb);
  the same id from both stops the run. A frontmatter server whose table names a <stack> path this
  install does not ship (after-effects' vendor build) or, off macOS, an Adobe/mobile server
  (install.sh MACOS_ONLY_SERVERS) is dropped with a warning, as the Claude installer does.
  --no-mcp emits no [mcp_servers] (the files stay).
- WORK/build-report.json (counts, warnings, dropped keys and servers, the Astra cost notice),
  links.json, hook-keys.json (hook_defs.hook_keys per written source: each profile file, or
  config.toml under --ide-default), regions.json, options.json (flags, ctx, the resolved
  ide_default, the AGENTS.md block entry the next run passes to claude_md_block as `prev`, and
  `profile_digests`: doctor.semantic_digest of each written profile file, so doctor.py can tell
  Codex's own [hooks.state] writes from drift).

Seeded-bug proofs (tests/mutations/render.json; each turns its named test red): a stage path leaked
into a profile (the hook stub); a foreign profile table accepted; the conflict check skipped; region
drift ignored; region A written after the user's first table (config_region); the backups root
missing from protected_roots; stack.env overwritten when present; wandb emitted without
--with-wandb; an execpolicy disagreement ignored; the astra file kept under --no-astra-profile;
--no-ide-default leaving the regions; the codex profile keeping [hooks] under --ide-default; the live
profile files' hooks.state dropped.
"""
from __future__ import annotations

import argparse
import difflib
import hashlib
import importlib.util
import json
import os
import re
import shutil
import stat
import sys
import tomllib

_HERE = os.path.dirname(os.path.abspath(__file__))
CODEX_CONFIG = os.path.dirname(_HERE)
TEMPLATES = os.path.join(CODEX_CONFIG, "templates")


def _load(name, path=None):
    """A module loaded by file path (CWE-427: never through sys.path)."""
    path = path or os.path.join(_HERE, name + ".py")
    spec = importlib.util.spec_from_file_location("codex_config_%s_for_render" % name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


toml_emit = _load("toml_emit")
convert_agents = _load("convert_agents")
convert_skills = _load("convert_skills")
convert_rules = _load("convert_rules")
permissions = _load("permissions")
hook_defs = _load("hook_defs")
render_profile = _load("render_profile")
config_region = _load("config_region")
doctor = _load("doctor")

RULES_FILE = convert_rules.RULES_FILE
CTX_GUARD_KEYS = ("codex_home", "home", "state_dir", "stack", "protected_roots", "credentials",
                  "toolsmith_wrapper")
MACOS_ONLY_SERVERS = ("illustrator", "after-effects", "premiere", "mobilebuild")   # install.sh
# keys and tables a stack-written profile file may hold (render_profile's output, every option)
PROFILE_KEYS = frozenset(render_profile.TEMPLATE_KEYS) | {
    "model", "model_reasoning_effort", "sandbox_mode", "developer_instructions", "mcp_servers",
    "permissions", "skills", "hooks"}
# files of the stack's bin/: (name, source, relative to "codex_config" or "src")
BIN_FILES = (("codex-hook", "codex_config", "hooks/codex-hook"),
             ("codex-mcp-headers", "codex_config", "bin/codex-mcp-headers"),
             ("with-stack-env", "src", "dot-claude/bin/with-stack-env"),
             ("mcp-headers", "src", "dot-claude/bin/mcp-headers"),
             ("magg-private", "src", "dot-claude/bin/magg-private"),
             ("stack-install", "src", "dot-claude/bin/stack-install"))
# stack.env sits at <CH>/stack.env, one level above the Claude layout's <dir>/stack.env
ADAPT = {
    "with-stack-env": ('$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)/stack.env',
                       '$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)/stack.env'),
    "mcp-headers": ('Path(__file__).resolve().parent.parent / "stack.env"',
                    'Path(__file__).resolve().parent.parent.parent / "stack.env"'),
}
MCP_ADAPT = ('Path(__file__).resolve().parent.parent / "stack.env"',
             'Path(__file__).resolve().parent.parent.parent / "stack.env"')
# A Codex install does not depend on the Claude one: the servers' ~/.claude fallbacks go (each
# replacement optional: only the file that has the text is touched, any other occurrence is replaced
# by the last, generic rule so no `.claude/stack.env` survives).
MCP_DROP_CLAUDE = (
    ('    cands.append(Path("~/.claude/stack.env").expanduser())\n', ""),
    ("), else ~/.claude/stack.env.\n", ").\n"),
    (", else ~/.claude/stack.env): OPENROUTER", "): OPENROUTER"),
    ('Path(os.environ.get("CLAUDE_CONFIG_DIR") or home / ".claude")',
     'Path(os.environ.get("CODEX_HOME") or home / ".codex")'),
    ("~/.claude/stack.env", "<CODEX_HOME>/stack.env"),
)
PROFILE_HEADER = ("# claude-agent-stack: profile `%s` (codex --profile %s). Generated by codex_config/install.sh,\n"
                  "# which overwrites this file: your own settings go in config.toml.\n")
ASTRA_IDE_HEADER = ("# claude-agent-stack: profile `%s` under --ide-default: only the Astra roles' config_file\n"
                    "# overrides on top of the config.toml regions. Generated by codex_config/install.sh.\n")
COST_NOTICE = ("codex-astra: sessions started with `codex --profile %s` run the six top-tier roles (%s) on "
               "%s, billed at Astra rates ($10/$50 per 1M input/output tokens, DESIGN §2.1).")
_BAD_PATH = re.compile(r"[\x00-\x1f\x7f'\"\\]")
_PROFILE_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]*\Z")
_BARE = re.compile(r"[A-Za-z0-9_-]+\Z")


class RenderError(Exception):
    """A build error the user must fix: printed to stderr, exit 1."""


class UsageError(Exception):
    """Bad arguments: exit 2."""


# ------------------------------------------------------------------------------------- files
def _read(path):
    """A file's bytes, not through a link at its last component; None when missing."""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise RenderError("cannot read %s: %s" % (path, exc.strerror)) from None
    with os.fdopen(fd, "rb") as f:
        if not stat.S_ISREG(os.fstat(f.fileno()).st_mode):
            raise RenderError("%s is not a regular file" % path)
        return f.read()


def _need(path):
    data = _read(path)
    if data is None:
        raise RenderError("%s: missing from the source" % path)
    return data


def _write(path, data, mode=0o644):
    """Write a regular file in the stage (a link or file in the way is replaced, never followed)."""
    if isinstance(data, str):
        data = data.encode("utf-8")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if os.path.islink(path):
        os.unlink(path)
    elif os.path.lexists(path) and not os.path.isfile(path):
        raise RenderError("%s is not a regular file: move it away, then run the installer again" % path)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, mode)
    with os.fdopen(fd, "wb") as f:
        f.write(data)
        os.fchmod(f.fileno(), mode)


def _copy_tree(src, dst, adapt=None):
    """Copy a source tree file by file (exec bit kept as 0755, else 0644); a symlink or special file
    in the source is refused; __pycache__ is skipped. adapt(rel, data) may rewrite a file."""
    if not os.path.isdir(src) or os.path.islink(src):
        raise RenderError("%s: missing from the source (or not a folder)" % src)
    for d, dirs, files in os.walk(src):
        dirs[:] = sorted(x for x in dirs if x != "__pycache__")
        for x in dirs:
            if os.path.islink(os.path.join(d, x)):
                raise RenderError("%s is a symlink: refused" % os.path.join(d, x))
        for name in sorted(files):
            p = os.path.join(d, name)
            if name.endswith(".pyc"):
                continue
            st = os.lstat(p)
            if not stat.S_ISREG(st.st_mode):
                raise RenderError("%s is not a regular file: refused" % p)
            rel = os.path.relpath(p, src)
            data = _need(p)
            if adapt:
                data = adapt(rel, data)
            _write(os.path.join(dst, rel), data, 0o755 if st.st_mode & 0o111 else 0o644)


def _adapt_mcp(rel, data):
    if not rel.endswith(".py"):
        return data
    data = _replace_once(data, *MCP_ADAPT, what="dot-claude/mcp/" + rel, optional=True)
    for old, new in MCP_DROP_CLAUDE[:-1]:
        data = data.replace(old.encode(), new.encode())
    return data.replace(MCP_DROP_CLAUDE[-1][0].encode(), MCP_DROP_CLAUDE[-1][1].encode())


def _replace_once(data, old, new, what, optional=False):
    n = data.count(old.encode())
    if n == 0 and optional:
        return data
    if n != 1:
        raise RenderError("%s: the stack.env path to adapt occurs %d times (expected once): the "
                          "source changed, adapt render.py" % (what, n))
    return data.replace(old.encode(), new.encode())


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _dotted(path):
    return ".".join(k if _BARE.match(k) else json.dumps(k, ensure_ascii=False) for k in path)


# ------------------------------------------------------------------------------------- args
def parse_args(argv):
    p = argparse.ArgumentParser(prog="render.py", description="Render a staged CODEX_HOME.")
    for flag in ("--src", "--stage", "--work", "--codex-home", "--home"):
        p.add_argument(flag, required=True)
    p.add_argument("--state-dir")
    p.add_argument("--profile-name", default="codex")
    p.add_argument("--skills-root")
    p.add_argument("--uv")
    p.add_argument("--codex")
    for flag in ("--with-wandb", "--no-agents-md", "--no-mcp", "--legacy-sandbox", "--git-allow-rules",
                 "--no-escalation", "--with-rollout-budget", "--no-astra-profile", "--force"):
        p.add_argument(flag, action="store_true")
    g = p.add_mutually_exclusive_group()
    g.add_argument("--ide-default", action="store_true")
    g.add_argument("--no-ide-default", action="store_true")
    return p.parse_args(argv)


def _abs_arg(v, flag):
    if not isinstance(v, str) or not os.path.isabs(v) or _BAD_PATH.search(v):
        raise UsageError("%s must be an absolute path without quotes, backslashes or control "
                         "characters, got %r" % (flag, v))
    return os.path.normpath(v)


def make_ctx(a):
    home = _abs_arg(a.home, "--home")
    codex_home = _abs_arg(a.codex_home, "--codex-home")
    xdg = os.environ.get("XDG_STATE_HOME") or ""
    if not os.path.isabs(xdg):                       # XDG: a relative value is ignored
        xdg = os.path.join(home, ".local", "state")
    state_dir = _abs_arg(a.state_dir, "--state-dir") if a.state_dir else os.path.join(xdg, "codex-agent-stack")
    if a.skills_root == "none":
        skills_root = None
    else:
        skills_root = (_abs_arg(a.skills_root, "--skills-root") if a.skills_root
                       else os.path.join(home, ".agents", "skills"))
    uv = a.uv or "uv"
    if uv != "uv":
        uv = _abs_arg(uv, "--uv")
    if not _PROFILE_NAME.match(a.profile_name or ""):
        raise UsageError("--profile-name must be [A-Za-z0-9][A-Za-z0-9_-]*, got %r" % (a.profile_name,))
    ctx = {"codex_home": codex_home, "home": home, "stack": codex_home + "/stack", "state_dir": state_dir,
           "profile_name": a.profile_name, "uv": uv, "skills_root": skills_root,
           "backup_root": os.path.join(xdg, "codex-agent-stack-backups")}
    for tool in ("npx", "node"):                     # absolute where found: IDE sessions have a short PATH
        found = shutil.which(tool)
        if found and os.path.isabs(found) and not _BAD_PATH.search(found):
            ctx[tool] = found
    return ctx


def profile_files(name):
    return name + ".config.toml", name + "-astra.config.toml"


# ------------------------------------------------------------------------------------- live state
def _old_manifest(stage, warnings):
    data = _read(os.path.join(stage, ".stack-manifest.json")) if not os.path.islink(
        os.path.join(stage, ".stack-manifest.json")) else None
    if data is None:
        return None
    try:
        m = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        m = None
    if not isinstance(m, dict):
        warnings.append(".stack-manifest.json is not a manifest: treated as a first install")
        return None
    return m


def foreign_keys(doc):
    """Dotted names in a live profile file that the stack never writes there."""
    out = [_dotted((k,)) for k in doc if k not in PROFILE_KEYS]
    hooks = doc.get("hooks")
    if "hooks" in doc and not isinstance(hooks, dict):
        out.append("hooks")
    elif isinstance(hooks, dict):
        out += [_dotted(("hooks", k)) for k in hooks
                if k != "state" and k not in render_profile.HOOK_EVENTS]
        if "state" in hooks and not isinstance(hooks["state"], dict):
            out.append("hooks.state")
    return out


def live_hooks_state(stage, names, warnings):
    """The merged [hooks.state] of the live profile files (§7.4); a foreign table stops the run."""
    states = []
    for rel in names:
        p = os.path.join(stage, rel)
        if os.path.islink(p):
            warnings.append("%s is a symlink: it is replaced by the stack's file (the backup keeps "
                            "it); trust records in its target are not carried over" % rel)
            continue
        data = _read(p)
        if data is None:
            continue
        try:
            doc = tomllib.loads(data.decode("utf-8"))
        except (UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
            raise RenderError("%s does not parse as TOML (%s): fix or remove it, then run the installer "
                              "again" % (rel, exc)) from None
        bad = foreign_keys(doc)
        if bad:
            raise RenderError("%s holds settings the stack does not write: %s. The installer owns this "
                              "file whole; move your settings to config.toml, then run it again"
                              % (rel, ", ".join(bad)))
        states.append((doc.get("hooks") or {}).get("state"))
    try:
        return render_profile.merge_hooks_state(*states)
    except render_profile.BuildError as exc:
        raise RenderError(str(exc)) from None


# ------------------------------------------------------------------------------------- stack/
def clear_stack(stage):
    s = os.path.join(stage, "stack")
    if os.path.islink(s):
        raise RenderError("%s is a symlink: the render never writes through it" % s)
    if os.path.isdir(s):
        shutil.rmtree(s)
    elif os.path.lexists(s):
        os.unlink(s)
    os.mkdir(s, 0o755)
    return s


def write_support(src, stage_stack):
    hooks = os.path.join(stage_stack, "hooks")
    _write(os.path.join(hooks, "codex_guard.py"), _need(os.path.join(CODEX_CONFIG, "hooks", "codex_guard.py")))
    for line in _need(os.path.join(CODEX_CONFIG, "hooks", "SUPPORT_FILES")).decode("utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if not line.startswith("dot-claude/hooks/") or ".." in line.split("/") or line.count("/") != 2:
            raise RenderError("hooks/SUPPORT_FILES: %r is not a dot-claude/hooks/<file> line" % line)
        _write(os.path.join(hooks, os.path.basename(line)), _need(os.path.join(src, line)))
    for name, base, rel in BIN_FILES:
        data = _need(os.path.join(CODEX_CONFIG if base == "codex_config" else src, rel))
        if name in ADAPT:
            data = _replace_once(data, *ADAPT[name], what=rel)
        _write(os.path.join(stage_stack, "bin", name), data, 0o755)
    _copy_tree(os.path.join(src, "dot-claude", "mcp"), os.path.join(stage_stack, "mcp"),
               adapt=_adapt_mcp)


def _walk_strings(obj, fn):
    if isinstance(obj, str):
        return fn(obj)
    if isinstance(obj, list):
        return [_walk_strings(v, fn) for v in obj]
    if isinstance(obj, dict):
        return {k: _walk_strings(v, fn) for k, v in obj.items()}
    return obj


def write_magg(src, stage_stack, ctx):
    srcdir = os.path.join(src, "dot-claude", "magg")
    try:
        doc = json.loads(_need(os.path.join(srcdir, "config.json")).decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise RenderError("dot-claude/magg/config.json is not valid JSON: %s" % exc) from None
    try:
        doc = _walk_strings(doc, lambda s: convert_agents._render(s, ctx, "dot-claude/magg/config.json"))
    except convert_agents.BuildError as exc:
        raise RenderError(str(exc)) from None
    _copy_tree(srcdir, os.path.join(stage_stack, "magg"))
    _write(os.path.join(stage_stack, "magg", "config.json"), json.dumps(doc, indent=2) + "\n")


def _stack_paths(table, stack):
    rx = re.compile(re.escape(stack) + r"/([^\s:'\"]+)")
    found = []
    _walk_strings(table, lambda s: found.extend(rx.findall(s)))
    return found


def mcp_servers(conv, ctx, stage_stack, with_wandb, warnings):
    """The frontmatter servers (minus those this install cannot run) plus the user-scope servers."""
    servers, dropped = {}, {}
    for sid, table in conv["mcp_servers"].items():
        missing = sorted({p for p in _stack_paths(table, ctx["stack"])
                          if not os.path.lexists(os.path.join(stage_stack, p))})
        if sys.platform != "darwin" and sid in MACOS_ONLY_SERVERS:
            dropped[sid] = "macOS only"
        elif missing:
            dropped[sid] = "names %s, which this install does not ship" % ", ".join(
                ctx["stack"] + "/" + p for p in missing)
        else:
            servers[sid] = table
    for sid, why in dropped.items():
        warnings.append("MCP server %s left out: %s" % (sid, why))
    try:
        user = convert_agents.user_scope_servers(ctx, with_wandb)
    except convert_agents.BuildError as exc:
        raise RenderError(str(exc)) from None
    both = sorted(set(conv["mcp_servers"]) & set(user))
    if both:
        raise RenderError("MCP server id(s) %s defined both by an agent's frontmatter and by the "
                          "user-scope servers (convert_agents.user_scope_servers)" % ", ".join(both))
    servers.update(user)
    return {k: servers[k] for k in sorted(servers)}, dropped


def guard_json(ctx, settings):
    try:
        base = json.loads(_need(os.path.join(TEMPLATES, "guard.base.json")).decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise RenderError("templates/guard.base.json: %s" % exc) from None
    if not isinstance(base, dict) or base.get("schema") != 1:
        raise RenderError("templates/guard.base.json: not a schema 1 object")
    clash = sorted(set(base) & set(CTX_GUARD_KEYS))
    if clash:
        raise RenderError("templates/guard.base.json defines %s, which render fills in" % ", ".join(clash))
    roots = [ctx["codex_home"], os.path.join(ctx["home"], ".agents"), ctx["state_dir"], ctx["backup_root"]]
    sr = ctx["skills_root"]
    if sr and not any(sr == r or sr.startswith(r + "/") for r in roots):
        roots.append(sr)
    try:
        cred = permissions.credential_set(settings, ctx)
    except permissions.BuildError as exc:
        raise RenderError(str(exc)) from None
    doc = {"schema": base["schema"], "codex_home": ctx["codex_home"], "home": ctx["home"],
           "state_dir": ctx["state_dir"], "stack": ctx["stack"], "protected_roots": roots,
           "credentials": cred, "toolsmith_wrapper": ctx["stack"] + "/bin/stack-install"}
    doc.update((k, v) for k, v in base.items() if k != "schema")
    return doc


# ------------------------------------------------------------------------------------- regions
def ide_mode(a, stage):
    """(ide_default, source): the flag, else the mode the file shows (regions present: kept)."""
    if a.ide_default:
        return True, "flag"
    if a.no_ide_default:
        return False, "flag"
    cfg = os.path.join(stage, "config.toml")
    if os.path.islink(cfg) or not os.path.isfile(cfg):
        return False, "default"
    try:
        spans = config_region.find(_read(cfg))
    except config_region.RegionError as exc:
        raise RenderError(str(exc) + "; nothing was changed") from None
    return (True, "kept") if any(spans.values()) else (False, "default")


def _drift(data, new, old_manifest, force, warnings):
    """Stop when a region in `data` changed since the last install (and differs from the new one)."""
    old = (old_manifest or {}).get("regions") if isinstance(old_manifest, dict) else None
    old = old if isinstance(old, dict) else {}
    cur, nxt = config_region.find(data), config_region.find(new)
    diffs = []
    for r in config_region.REGIONS:
        if not cur[r]:
            continue
        mine = data[cur[r][0]:cur[r][1]]
        theirs = new[nxt[r][0]:nxt[r][1]] if nxt[r] else b""
        if _sha(mine) == old.get(r) or mine == theirs:
            continue
        diffs.append("".join(difflib.unified_diff(
            mine.decode("utf-8", "replace").splitlines(True), theirs.decode("utf-8", "replace").splitlines(True),
            "config.toml region %s (as found)" % r, "config.toml region %s (this install)" % r)))
    if not diffs:
        return
    if not force:
        raise RenderError("config.toml: the stack's region(s) changed since the last install (Codex's "
                          "/model, the IDE settings or a hand edit). Move your change outside the "
                          "regions, or pass --force to overwrite it:\n" + "\n".join(diffs))
    warnings.append("config.toml: --force overwrote edited stack region(s)")


def regions_step(a, stage, mode, source, out, old_manifest, warnings):
    cfg = os.path.join(stage, "config.toml")
    if mode:
        if os.path.islink(cfg):
            raise RenderError("config.toml is a symlink: --ide-default never writes through a link "
                              "(yours). Replace it with a regular file, or install without --ide-default")
        if os.path.lexists(cfg) and not os.path.isfile(cfg):
            raise RenderError("config.toml is not a regular file")
        data = _read(cfg)
        fmode = 0o600 if data is None else stat.S_IMODE(os.lstat(cfg).st_mode)
        data = data or b""
        a_text, b_text = toml_emit.dumps(out["region_a"]), toml_emit.dumps(out["region_b"])
        try:
            new = config_region.splice(data, a_text, b_text)
        except config_region.RegionConflict as exc:
            raise RenderError(_conflict_message(exc.keys)) from None
        except config_region.RegionError as exc:
            raise RenderError("%s; config.toml was left as it is" % exc) from None
        _drift(data, new, old_manifest, a.force, warnings)
        if new != data or not os.path.isfile(cfg):
            _write(cfg, new, fmode)
    elif source == "flag":
        if os.path.islink(cfg):
            warnings.append("config.toml is a symlink: --no-ide-default removes nothing through it")
        elif os.path.isfile(cfg):
            data = _read(cfg)
            try:
                new = config_region.remove(data)
            except config_region.RegionError as exc:
                raise RenderError("%s; config.toml was left as it is" % exc) from None
            _drift(data, new, old_manifest, a.force, warnings)
            if new != data:
                _write(cfg, new, stat.S_IMODE(os.lstat(cfg).st_mode))
    elif isinstance(old_manifest, dict) and old_manifest.get("ide_default") and os.path.islink(cfg):
        warnings.append("config.toml is now a symlink: the stack's regions in it are no longer managed")
    shas, cfg_sha = {"A": None, "B": None}, None
    if os.path.isfile(cfg) and not os.path.islink(cfg):
        data = _read(cfg)
        shas, cfg_sha = config_region.region_sha(data), _sha(data)
    return {"ide_default": mode, "A": shas["A"], "B": shas["B"], "config_toml_sha256": cfg_sha}


def _conflict_message(keys):
    return ("config.toml: %s defined both by you and by the stack's --ide-default regions. The "
            "installer never edits your keys: remove or rename them (they would override the "
            "stack's), or install without --ide-default; config.toml was left as it is"
            % ", ".join(keys))


# ------------------------------------------------------------------------------------- render
def render(a):
    """Render the stage (module docstring); returns the build report."""
    ctx = make_ctx(a)
    src, stage, work = (_abs_arg(a.src, "--src"), _abs_arg(a.stage, "--stage"), _abs_arg(a.work, "--work"))
    if not os.path.isdir(os.path.join(src, "dot-claude")):
        raise UsageError("--src %s holds no dot-claude/ (the source snapshot)" % src)
    if not os.path.isdir(stage) or os.path.islink(stage):
        raise UsageError("--stage %s is not a folder (make it with codex_state.py stage)" % stage)
    os.makedirs(work, exist_ok=True)
    warnings = []
    names = profile_files(ctx["profile_name"])
    old_manifest = _old_manifest(stage, warnings)
    hooks_state = live_hooks_state(stage, names, warnings)
    mode, source = ide_mode(a, stage)
    try:
        settings = json.loads(_need(os.path.join(src, "dot-claude", "settings.json")).decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise RenderError("dot-claude/settings.json: %s" % exc) from None
    try:
        models = convert_agents.load_models()
    except convert_agents.BuildError as exc:
        raise RenderError(str(exc)) from None

    stage_stack = clear_stack(stage)
    try:
        skills = convert_skills.convert(src, stage_stack, ctx)
        conv = convert_agents.convert(src, dict(ctx, skill_modules=frozenset(skills["modules"])), models)
        rules_text, examples = convert_rules.render_rules(settings, ctx, {"git_allow_rules": a.git_allow_rules})
        perm = permissions.permission_profile(settings, ctx)
        r_text = convert_agents._template(_need(os.path.join(TEMPLATES, "rules.md")).decode("utf-8"),
                                          ctx, "templates/rules.md")
        r_text = convert_agents._renamer(set(conv["policy"]["agents"]) | {"blackcat"},
                                         models["roles"]["name_style"])(r_text)
        block = None if a.no_agents_md else convert_agents._template(
            _need(os.path.join(TEMPLATES, "AGENTS.block.md")).decode("utf-8"), ctx, "templates/AGENTS.block.md")
        table = hook_defs.hooks_table(ctx["stack"] + "/bin/codex-hook")
    except (convert_skills.BuildError, convert_agents.BuildError, convert_rules.BuildError,
            permissions.BuildError, hook_defs.BuildError) as exc:
        raise RenderError(str(exc)) from None

    for role, doc in conv["roles"].items():
        _write(os.path.join(stage_stack, "agents", role + ".toml"), toml_emit.dumps(doc))
    if not a.no_astra_profile:
        for role, doc in conv["astra_roles"].items():
            _write(os.path.join(stage_stack, "agents-astra", role + ".toml"), toml_emit.dumps(doc))
    write_support(src, stage_stack)
    write_magg(src, stage_stack, ctx)
    _write(os.path.join(stage_stack, "policy", "agents.json"), json.dumps(conv["policy"], indent=2) + "\n")
    _write(os.path.join(stage_stack, "policy", "guard.json"), json.dumps(guard_json(ctx, settings), indent=2) + "\n")
    servers, dropped_servers = mcp_servers(conv, ctx, stage_stack, a.with_wandb, warnings)

    rules_path = os.path.join(stage, RULES_FILE)
    _write(rules_path, rules_text)
    codex = None if a.codex == "none" else (a.codex or shutil.which("codex"))
    if codex is None:
        warnings.append("execpolicy examples not checked (%s): run the installer with Codex on PATH "
                        "before relying on the rules" % ("--codex none" if a.codex == "none" else "no codex on PATH"))
    else:
        bad = convert_rules.check_examples(rules_path, codex)
        if bad:
            raise RenderError("codex execpolicy disagrees with %d rule example(s) of %s:\n  %s"
                              % (len(bad), RULES_FILE, "\n  ".join(bad[:30])))

    parts = {"blackcat": conv["blackcat"], "rules_text": r_text, "agents_entries": conv["agents_entries"],
             "astra_entries": {} if a.no_astra_profile else conv["astra_entries"], "mcp_servers": servers,
             "permissions": perm, "hooks": table, "hooks_state": hooks_state,
             "skills_max_context_tokens": convert_skills.SKILLS_MAX_CONTEXT_TOKENS}
    opts = {"legacy_sandbox": a.legacy_sandbox, "no_escalation": a.no_escalation, "no_mcp": a.no_mcp,
            "with_rollout_budget": a.with_rollout_budget, "ide_default": mode,
            "no_astra_profile": a.no_astra_profile}
    try:
        out = render_profile.build(parts, opts)
    except render_profile.BuildError as exc:
        raise RenderError(str(exc)) from None
    main_rel, astra_rel = names
    written = [main_rel]
    if mode:
        _write(os.path.join(stage, main_rel), out["codex_ide"])
    else:
        _write(os.path.join(stage, main_rel), PROFILE_HEADER % ((ctx["profile_name"],) * 2)
               + toml_emit.dumps(out["codex"]))
    astra_path = os.path.join(stage, astra_rel)
    astra_name = astra_rel[:-len(".config.toml")]
    if a.no_astra_profile:
        if os.path.lexists(astra_path):
            os.unlink(astra_path)
    else:
        written.append(astra_rel)
        text = (ASTRA_IDE_HEADER % astra_name + toml_emit.dumps(out["codex_astra_ide"]) if mode
                else PROFILE_HEADER % (astra_name, astra_name) + toml_emit.dumps(out["codex_astra"]))
        _write(astra_path, text)

    digests = {rel: doctor.semantic_digest(tomllib.loads(_need(os.path.join(stage, rel)).decode("utf-8")))
               for rel in written}
    regions = regions_step(a, stage, mode, source, out, old_manifest, warnings)
    hook_sources = ["config.toml"] if mode else written
    hook_keys = []
    for rel in hook_sources:
        target = ctx["codex_home"] + "/" + rel
        hook_keys += [dict(k, source=target) for k in hook_defs.hook_keys(target, table)]

    cmb = _load("claude_md_block", os.path.join(src, "lib", "claude_md_block.py"))
    cmb.NAME = "AGENTS.md"
    prev = ((old_manifest or {}).get("options") or {}).get("agents_md_block") if isinstance(
        (old_manifest or {}).get("options"), dict) else None
    try:
        agents_md = cmb.stage(stage, block, prev, live=os.path.join(ctx["codex_home"], "AGENTS.md"))
    except ValueError as exc:
        raise RenderError("templates/AGENTS.block.md: %s" % exc) from None
    if agents_md["action"] == "skipped":
        warnings.append("AGENTS.md: %s" % agents_md["why"])
    if os.path.lexists(os.path.join(ctx["codex_home"], "AGENTS.override.md")) and not a.no_agents_md:
        warnings.append("AGENTS.override.md in %s shadows AGENTS.md: Codex reads the override instead, so "
                        "the stack's global rules block is not loaded" % ctx["codex_home"])

    env = os.path.join(stage, "stack.env")
    seeded = not os.path.lexists(env)
    if seeded:
        data = _need(os.path.join(src, "lib", "stack.env.example"))
        fd = os.open(env, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            os.fchmod(f.fileno(), 0o600)

    links = {"root": ctx["skills_root"], "links": skills["links"] if ctx["skills_root"] else {}}
    flags = {k: getattr(a, k) for k in ("with_wandb", "no_agents_md", "no_mcp", "legacy_sandbox",
                                        "git_allow_rules", "no_escalation", "with_rollout_budget",
                                        "ide_default", "no_ide_default", "no_astra_profile", "force")}
    options = {"profile_name": ctx["profile_name"], "profile_files": written, "ide_default": mode,
               "ide_default_source": source, "astra": not a.no_astra_profile, "flags": flags,
               "ctx": {k: ctx[k] for k in ("codex_home", "home", "stack", "state_dir", "profile_name", "uv",
                                           "skills_root", "backup_root")},
               "codex": codex, "agents_md_block": agents_md["entry"], "profile_digests": digests}
    cost = None if a.no_astra_profile else COST_NOTICE % (
        astra_name, ", ".join(sorted(conv["astra_roles"])), models["astra"]["model"])
    report = {
        "counts": {"roles": len(conv["roles"]), "astra_roles": 0 if a.no_astra_profile else len(conv["astra_roles"]),
                   "skills_listed": len(skills["listed"]), "skill_modules": len(skills["modules"]),
                   "skills_budget_tokens": skills["budget_tokens"],
                   "mcp_servers": 0 if a.no_mcp else len(servers),
                   "rules": {d: sum(1 for e in examples if e["decision"] == d) for d in convert_rules.DECISIONS},
                   "rule_examples": sum(len(e["match"]) + len(e["not_match"]) for e in examples),
                   "hook_keys": len(hook_keys)},
        "profile_files": written, "ide_default": mode, "agents_md": agents_md["action"],
        "stack_env_seeded": seeded, "execpolicy_checked": codex is not None,
        "warnings": warnings,
        "dropped_keys": {"frontmatter": conv["report"]["dropped"], "mcp": conv["report"]["mcp_dropped"]},
        "mcp_dropped_servers": dropped_servers, "cost_notice": cost,
    }
    for name, obj in (("build-report.json", report), ("links.json", links), ("hook-keys.json", hook_keys),
                      ("regions.json", regions), ("options.json", options)):
        _write(os.path.join(work, name), json.dumps(obj, indent=2) + "\n", 0o600)
    return report


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    try:
        a = parse_args(argv)
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else 2
    try:
        report = render(a)
    except UsageError as exc:
        sys.stderr.write("render.py: %s\n" % exc)
        return 2
    except RenderError as exc:
        sys.stderr.write("render.py: %s\n" % exc)
        return 1
    c = report["counts"]
    print("rendered: %d roles (+%d astra), %d skills listed (+%d modules), %d MCP servers, %d rules, %d hook keys"
          % (c["roles"], c["astra_roles"], c["skills_listed"], c["skill_modules"], c["mcp_servers"],
             sum(c["rules"].values()), c["hook_keys"]))
    for w in report["warnings"]:
        print("  ! " + w)
    if report["cost_notice"]:
        print("  " + report["cost_notice"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
