"""CODEX_HOME state for codex_config/install.sh: stage, plan, apply, restore, validate, manifest.

Stdlib only, Python >= 3.11. One process per call. The engine is the Claude installer's
lib/install_state.py, loaded BY FILE PATH from ../../lib relative to this file (in a real run: the
private source snapshot, never the repository) and used unchanged: this module only sets its
module constants (DESIGN.md §7.2) and rewords its Claude-specific messages.

  codex_state.py home     <flag-set 0|1> <flag> [repo...]      key<TAB>value: path real source created warn
  codex_state.py stage    <codex_home> <stage> [snap.json]
  codex_state.py plan     <codex_home> <stage> <report.json> <plan.json> [snap.json]
  codex_state.py apply    <codex_home> <stage> <plan.json> <backup_root> <commit> <out-file> [snap.json]
  codex_state.py restore  <codex_home> <which|latest> <backup_root> <work> <commit> <home>
                          [--dry-run] [--force] [--force-config]
  codex_state.py validate <stage>
  codex_state.py manifest <stage> <commit> <work>
  codex_state.py retrust  <old-manifest|-> <new-manifest>
  codex_state.py latest   <codex_home> <backup_root>
  codex_state.py new-backup <codex_home> <backup_root> <commit>

Exit codes: 0 ok, 1 a problem the user must fix (message on stderr), 2 usage or a refused CODEX_HOME.

Scope. The stack's part of CODEX_HOME is stack/ plus the files in SCOPE_FILES. config.toml is always
in scope (older backups hold it), but staging copies it unchanged, so it shows in a plan only when
an --ide-default region changes. stack.env is WRITE_THROUGH (a dotfiles link is written through) and
the engine compares its whole mode: stage() sets the staged copy to 0600, so a `chmod 644` on the
live file shows as a change that the apply repairs.

Restore. The engine's restore puts back every saved file, config.toml included. Codex itself writes
config.toml (/hooks trust, [projects.*], /model), so when the backup would rewrite or remove
config.toml and the live file's sha256 differs from the manifest's config_toml_sha256, restore
refuses unless --force-config, naming --no-ide-default as the safe alternative. The engine's --force
(saved symlinks leaving CODEX_HOME) is passed only when the user gave --force.

Seeded-bug proofs (tests/mutations/codex_state.json; each turns its tests red): leave config.toml out
of SCOPE_FILES; skip the --force-config check; pass the engine's force on --force-config; stop setting
the staged stack.env to 0600; list stack/skills/ entries one by one; keep the engine's
CLAUDE_CONFIG_DIR wording; record no hook fingerprint change in retrust; widen the scope to agents/.
"""
from __future__ import annotations

import contextlib
import hashlib
import importlib.util
import io
import json
import os
import re
import stat
import sys
import tomllib

_HERE = os.path.dirname(os.path.abspath(__file__))
ENGINE_PATH = os.path.join(os.path.dirname(os.path.dirname(_HERE)), "lib", "install_state.py")
CLAUDE_MD_BLOCK_PATH = os.path.join(os.path.dirname(os.path.dirname(_HERE)), "lib", "claude_md_block.py")


def _load(name, path):
    """A module loaded by file path (CWE-427: never through sys.path)."""
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


ist = _load("codex_install_state", ENGINE_PATH)
codex_home = _load("codex_config_codex_home_for_state", os.path.join(_HERE, "codex_home.py"))
codex_home.use_engine(ist)

# ---- the engine's constants for CODEX_HOME (DESIGN.md §7.2) -------------------------------------
_FILES = ("codex.config.toml", "codex-astra.config.toml", "config.toml", "rules/claude-agent-stack.rules",
          "AGENTS.md", "stack.env", ".stack-manifest.json")
SCOPE_DIRS = ("stack",)
SCOPE_FILES = _FILES + tuple(f + ".tmp" for f in _FILES)
EXCLUDED = ("stack/hooks/__pycache__", "stack/bin/stack-python")
WRITE_THROUGH = ("stack.env",)
# the stack's own files a manifest records (config.toml, AGENTS.md and stack.env are the user's)
OWNED_FILES = ("codex.config.toml", "codex-astra.config.toml", "rules/claude-agent-stack.rules")
# summarized per directory in a printed plan, like the engine's agents/ and skills/
SUMMARIZED = ("stack/agents/", "stack/agents-astra/", "stack/skills/", "stack/skill-modules/")
# a role file is a ConfigToml layer (additionalProperties false; role.rs applies bounded keys, DESIGN F6):
# no name or description (those are the profile's [agents.<role>] entry)
REQUIRED_ROLE_KEYS = ("model", "model_reasoning_effort", "developer_instructions")
# the vendored Codex config schema (rust-v0.160.1): a role key outside ConfigToml's properties is refused
CONFIG_SCHEMA = os.path.join(os.path.dirname(_HERE), "tests", "fixtures", "vendor", "config.schema.json")
MANIFEST_FORMAT = 1


def configure(engine):
    engine.SCOPE_DIRS = SCOPE_DIRS
    engine.SCOPE_FILES = SCOPE_FILES
    engine.EXCLUDED = EXCLUDED
    engine.WRITE_THROUGH = WRITE_THROUGH


configure(ist)

# ---- wording: the engine speaks of install.sh, the config dir and CLAUDE_CONFIG_DIR ---------------
_WORDING = (
    (re.compile(r"\(set CLAUDE_CONFIG_DIR\)"), "(pass --codex-home or set CODEX_HOME)"),
    (re.compile(r"CLAUDE_CONFIG_DIR"), "CODEX_HOME"),
    (re.compile(r"(?<![\w/.-])install\.sh\b"), "codex_config/install.sh"),
    (re.compile(r"\binstall_state:"), "codex_state:"),
    (re.compile(r"\bthe config scope\b"), "the stack's part of CODEX_HOME"),
    (re.compile(r"\b(?:the )?config dir\b"), "CODEX_HOME"),
)


def wording(text: str) -> str:
    for rx, rep in _WORDING:
        text = rx.sub(rep, text)
    return text


@contextlib.contextmanager
def reworded():
    """Engine output and SystemExit messages in Codex wording."""
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            yield
    except SystemExit as exc:
        if isinstance(exc.code, str):
            raise SystemExit(wording(exc.code)) from None
        raise
    finally:
        sys.stdout.write(wording(buf.getvalue()))


def sha256_or_none(path: str):
    """sha256 of a regular file (not through a link), None when there is none."""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    except OSError:
        return None
    with os.fdopen(fd, "rb") as f:
        if not stat.S_ISREG(os.fstat(f.fileno()).st_mode):
            return None
        return hashlib.sha256(f.read()).hexdigest()


# ---- stage, plan, apply ---------------------------------------------------------------------------
def stage(c, s, snap_path=None):
    with reworded():
        snap = ist.stage(c, s, snap_path)
    for rel in SCOPE_FILES:                     # leftovers of an interrupted run: never kept
        p = os.path.join(s, rel)
        if rel.endswith(".tmp") and (os.path.islink(p) or os.path.isfile(p)):
            os.unlink(p)
    env = os.path.join(s, "stack.env")
    if os.path.isfile(env) and not os.path.islink(env):
        os.chmod(env, 0o600)                     # the keys file: a world-readable live copy is a change
    return snap


def _count(rels, prefix):
    return sum(1 for r in rels if r.startswith(prefix))


def _collapse(listing):
    out, seen = [], set()
    for rel, why in listing:
        parts = rel.split("/")
        if rel.startswith(("stack/skills/", "stack/skill-modules/")) and len(parts) >= 4:
            rel = "/".join(parts[:3]) + "/"
        if rel not in seen:
            seen.add(rel)
            out.append((rel, why))
    return out


def print_plan(plan, removed_heading="removed: not part of the stack"):
    """The engine's print_plan, in Codex wording, with the role and skill files summarized per
    directory. The engine leaves entries starting with "agents/" out of its "updated:" line, so the
    stack's summarized entries get that prefix in the copy it prints: counted, not listed."""
    view = dict(plan)
    view["changed"] = [("agents/" + r) if r.startswith(SUMMARIZED) else r for r in plan["changed"]]
    view["removed_listing"] = _collapse(plan["removed_listing"])
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        ist.print_plan(view, removed_heading)
    lines = buf.getvalue().splitlines()
    summary = ["  %s %d added, %d updated, %d removed" % (p, a, u, r) for p, a, u, r in (
        (p, _count(plan["added"], p), _count(plan["changed"], p), _count(plan["removed"], p))
        for p in SUMMARIZED) if a or u or r]
    if lines and lines[0].startswith("  changes:"):
        lines[1:1] = summary
    sys.stdout.write(wording("".join(line + "\n" for line in lines)))


def plan(c, s, report_path, plan_path, snap_path=None) -> int:
    if snap_path:
        moved = ist.drifted(c, ist.load_json(snap_path, {}))
        if moved:
            sys.stderr.write("codex_config/install.sh: %s changed while the installer ran — nothing was "
                             "changed; run it again\n" % ", ".join(moved[:5]))
            return 1
    p = ist.make_plan(c, s, report_path)
    ist.write_json(plan_path, p)
    print_plan(p)
    bad = ist.unsafe_paths(c, p)
    if bad:
        sys.stderr.write("codex_config/install.sh: refusing paths outside CODEX_HOME: %s — nothing was "
                         "changed\n" % ", ".join(map(repr, bad[:5])))
        return 1
    return 0


def apply(c, s, plan_path, root, commit, out, snap_path=None) -> str:
    snap = ist.load_json(snap_path, None) if snap_path else None
    p = ist.load_json(plan_path, None)
    if not isinstance(p, dict):
        raise SystemExit("codex_state: %s is not a plan" % plan_path)
    with reworded():
        bdir = ist.apply_plan(c, s, p, root, commit, snap=snap)
    with open(out, "w") as f:
        f.write(bdir)
    return bdir


# ---- restore --------------------------------------------------------------------------------------
def _pick_backup(c, which, root):
    """The backup the engine's restore would use (same rules), to look at it first."""
    if which == "latest":
        found = [d for d in ist.backups_of(c, root)
                 if ist.load_json(os.path.join(d, "backup.json"), {}).get("reason") == "install"]
        if not found:
            raise SystemExit(wording("install.sh --restore: no install backup of %s in %s" % (c, root)))
        return found[-1]
    bdir = os.path.realpath(which)
    if os.path.dirname(bdir) != os.path.realpath(root):
        raise SystemExit(wording("install.sh --restore: %s is not a backup folder in %s"
                                 % (which, os.path.realpath(root))))
    return bdir


def config_toml_guard(c, bdir, force_config=False):
    """SystemExit when restoring bdir would overwrite a config.toml Codex (or you) changed since the
    install: its live sha256 differs from the manifest's config_toml_sha256."""
    meta = ist.load_json(os.path.join(bdir, "backup.json"), {})
    meta = meta if isinstance(meta, dict) else {}
    touches = "config.toml" in (meta.get("entries") or {}) or "config.toml" in (meta.get("added") or [])
    if not touches or force_config:
        return
    manifest = ist.load_json(os.path.join(c, ".stack-manifest.json"), {})
    want = manifest.get("config_toml_sha256") if isinstance(manifest, dict) else None
    live = sha256_or_none(os.path.join(c, "config.toml"))
    if want is None or live != want:
        raise SystemExit(
            "codex_config/install.sh --restore: %s changed since the install (Codex writes /hooks trust, "
            "[projects.*] and /model there%s): restoring the backup would lose those edits. Nothing was "
            "changed. Use --no-ide-default to remove only the stack's regions (every later edit stays), "
            "or add --force-config to put the saved config.toml back anyway."
            % (os.path.join(c, "config.toml"),
               "" if want is not None else "; the manifest records no config_toml_sha256"))


def restore(c, which, root, work, commit, home, dry=False, force=False, force_config=False):
    bdir = _pick_backup(c, which, root)
    config_toml_guard(c, bdir, force_config)
    with reworded():
        return ist.restore(c, bdir, root, work, commit, home, dry, force)


# ---- validate -------------------------------------------------------------------------------------
_PLACEHOLDER = re.compile(r"__[A-Z][A-Z0-9_]*__|\{\{[^{}\n]*\}\}")
# skills carry code samples (${{ secrets.X }}, __INIT__-style names): only the render's own
# placeholders count there
_SKILL_PLACEHOLDER = re.compile(r"__(?:CLAUDE_DIR|UV|CODEX_HOME|STACK|STATE_DIR|PLACEHOLDER)__")


def _read(path):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, "rb") as f:
        return f.read()


def _walk_files(root):
    for d, dirs, files in os.walk(root):
        dirs.sort()
        for f in sorted(files):
            yield os.path.join(d, f)


def _bool_keys(obj, keys):
    return [k for k in keys if not isinstance(obj.get(k), bool)]


def _str_list(v):
    return isinstance(v, list) and all(isinstance(x, str) for x in v)


def _check_agents_json(doc):
    out = []
    if not isinstance(doc, dict) or doc.get("schema") != 1:
        return ["schema is not 1"]
    agents = doc.get("agents")
    if not isinstance(agents, dict) or not agents:
        out.append("agents is not a non-empty object")
        agents = {}
    for name, row in sorted(agents.items()):
        if not isinstance(row, dict):
            out.append("agents.%s is not an object" % name)
            continue
        bad = _bool_keys(row, ("apply_patch", "shell", "spawn_tool", "readonly", "web_ingesting", "installer"))
        bad += [k for k in ("spawn", "mcp") if not _str_list(row.get(k))]
        mtc = row.get("max_tool_calls", "missing")
        if not (mtc is None or (isinstance(mtc, int) and not isinstance(mtc, bool) and mtc > 0)):
            bad.append("max_tool_calls")
        out += ["agents.%s.%s: missing or wrong type" % (name, k) for k in bad]
    bc = doc.get("blackcat")
    if not isinstance(bc, dict) or not _str_list(bc.get("spawn")) or not _str_list(bc.get("mcp")) or not (
            isinstance(bc.get("max_shell_reads_per_prompt"), int)):
        out.append("blackcat: needs spawn, mcp (lists) and max_shell_reads_per_prompt (int)")
    if not _str_list(doc.get("builtin_types")):
        out.append("builtin_types is not a list of names")
    return out


def _check_guard_json(doc):
    if not isinstance(doc, dict) or doc.get("schema") != 1:
        return ["schema is not 1"]
    out = ["%s: not an absolute path" % k for k in ("codex_home", "home", "state_dir", "stack", "toolsmith_wrapper")
           if not (isinstance(doc.get(k), str) and os.path.isabs(doc[k]))]
    roots = doc.get("protected_roots")
    if not _str_list(roots) or not roots or doc.get("codex_home") not in roots:
        out.append("protected_roots: a list that holds codex_home")
    cred = doc.get("credentials")
    if not isinstance(cred, dict) or not _str_list(cred.get("paths")) or not _str_list(cred.get("globs")):
        out.append("credentials: needs paths and globs (lists)")
    if not isinstance(doc.get("caps"), dict):
        out.append("caps is not an object")
    if not (isinstance(doc.get("image_max_px"), int) and doc["image_max_px"] > 0):
        out.append("image_max_px is not a positive integer")
    return out


def validate(s) -> list:
    """Problems in a rendered stage: TOML that does not parse, role files without a required key or with
    a key outside the vendored schema's ConfigToml properties, unresolved placeholders, policy JSON off
    its schema (INTERFACES §4, §5).

    Seeded-bug proofs of the role-key part (tests/mutations/codex_state_validate.json): require name
    again; stop reporting a role key outside ConfigToml."""
    problems = []
    try:
        role_keys = frozenset(json.loads(_read(CONFIG_SCHEMA).decode("utf-8"))["properties"])
    except (OSError, ValueError, KeyError, TypeError) as exc:
        role_keys = None
        problems.append("%s: unreadable, role keys not checked (%s)" % (CONFIG_SCHEMA, exc))
    tomls = [r for r in ("codex.config.toml", "codex-astra.config.toml", "config.toml")
             if os.path.isfile(os.path.join(s, r)) and not os.path.islink(os.path.join(s, r))]
    tomls += [os.path.relpath(p, s) for p in _walk_files(os.path.join(s, "stack")) if p.endswith(".toml")]
    docs = {}
    for rel in tomls:
        try:
            docs[rel] = tomllib.loads(_read(os.path.join(s, rel)).decode("utf-8"))
        except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
            problems.append("%s: does not parse as TOML (%s)" % (rel, exc))
    for rel, doc in sorted(docs.items()):
        if rel.startswith(("stack/agents/", "stack/agents-astra/")):
            for k in REQUIRED_ROLE_KEYS:
                if not (isinstance(doc.get(k), str) and doc[k].strip()):
                    problems.append("%s: no %s" % (rel, k))
            for k in sorted(set(doc) - (role_keys or set(doc))):
                problems.append("%s: key %s is not a Codex config key (ConfigToml)" % (rel, k))
    strict = [r for r in tomls if r != "config.toml"] + [
        r for r in ("rules/claude-agent-stack.rules", "stack/policy/agents.json", "stack/policy/guard.json")
        if os.path.isfile(os.path.join(s, r))]
    texts = {}
    for rel in strict:
        try:
            texts[rel] = _read(os.path.join(s, rel)).decode("utf-8", "replace")
        except OSError as exc:
            problems.append("%s: unreadable (%s)" % (rel, exc.strerror))
    cfg = os.path.join(s, "config.toml")
    if os.path.isfile(cfg) and not os.path.islink(cfg):   # a link (yours) is never read through
        region = _load("codex_config_region_for_state", os.path.join(_HERE, "config_region.py"))
        data = _read(cfg)
        try:
            spans = region.find(data)
            texts["config.toml (stack regions)"] = "".join(
                data[a:b].decode("utf-8", "replace") for a, b in (v for v in spans.values() if v))
        except region.RegionError as exc:
            problems.append("config.toml: %s" % exc)
    agents_md = os.path.join(s, "AGENTS.md")
    if os.path.isfile(agents_md) and not os.path.islink(agents_md):
        cmb = _load("codex_claude_md_block_for_state", CLAUDE_MD_BLOCK_PATH)
        data = _read(agents_md)
        try:
            span = cmb.find_block(data)
            if span:
                texts["AGENTS.md (stack block)"] = data[span[0]:span[1]].decode("utf-8", "replace")
        except cmb.BlockError as exc:
            problems.append("AGENTS.md: %s" % exc)
    for rel, text in sorted(texts.items()):
        m = _PLACEHOLDER.search(text)
        if m:
            problems.append("%s: unresolved placeholder %s" % (rel, m.group(0)))
    for top in ("stack/skills", "stack/skill-modules"):
        for p in _walk_files(os.path.join(s, top)):
            if p.endswith((".md", ".yaml", ".yml")):
                try:
                    m = _SKILL_PLACEHOLDER.search(_read(p).decode("utf-8", "replace"))
                except OSError as exc:
                    problems.append("%s: unreadable (%s)" % (os.path.relpath(p, s), exc.strerror))
                    continue
                if m:
                    problems.append("%s: unresolved placeholder %s" % (os.path.relpath(p, s), m.group(0)))
    for rel, check in (("stack/policy/agents.json", _check_agents_json),
                       ("stack/policy/guard.json", _check_guard_json)):
        p = os.path.join(s, rel)
        if not os.path.isfile(p):
            problems.append("%s: missing" % rel)
            continue
        try:
            doc = json.loads(_read(p).decode("utf-8"))
        except (OSError, ValueError) as exc:
            problems.append("%s: invalid JSON (%s)" % (rel, exc))
            continue
        problems += ["%s: %s" % (rel, x) for x in check(doc)]
    return problems


# ---- manifest, retrust ----------------------------------------------------------------------------
def _work_json(work, name, kind):
    p = os.path.join(work, name)
    try:
        v = json.loads(_read(p).decode("utf-8"))      # a list too (the engine's reader: objects only)
    except (OSError, ValueError, RecursionError):
        v = None
    if not isinstance(v, kind):
        raise SystemExit("codex_state: %s is missing or not a JSON %s" % (p, kind.__name__))
    return v


def build_manifest(s, commit, work) -> dict:
    """The manifest for a rendered stage (INTERFACES §6), from the work files. The region hashes and
    config_toml_sha256 are computed from the staged config.toml (what the apply puts in place)."""
    links = _work_json(work, "links.json", dict)
    hooks = _work_json(work, "hook-keys.json", list)
    regions = _work_json(work, "regions.json", dict)
    options = _work_json(work, "options.json", dict)
    if not (isinstance(links.get("links"), dict) and (links.get("root") is None or isinstance(links["root"], str))):
        raise SystemExit("codex_state: links.json needs root (a path or null) and links (an object)")
    if not all(isinstance(h, dict) and isinstance(h.get("key"), str) and isinstance(h.get("fingerprint"), str)
               for h in hooks):
        raise SystemExit("codex_state: hook-keys.json entries need key and fingerprint")
    files = {}
    for rel, lf in sorted(ist.scan(s).items()):
        if lf[0] == "f" and (rel in OWNED_FILES or rel.startswith("stack/")):
            files[rel] = lf[1]
    cfg = os.path.join(s, "config.toml")
    shas = {"A": None, "B": None}
    if os.path.isfile(cfg) and not os.path.islink(cfg):   # a link (yours) is never read through
        region = _load("codex_config_region_for_state", os.path.join(_HERE, "config_region.py"))
        shas = region.region_sha(_read(cfg))
    return {
        "format": MANIFEST_FORMAT, "installer": "codex_config", "commit": commit,
        "repo": options.get("repo"), "files": files, "hooks": hooks, "links": links,
        "ide_default": bool(regions.get("ide_default")), "regions": shas,
        "config_toml_sha256": sha256_or_none(cfg),
        "profile_name": options.get("profile_name") or "codex",
        "astra": os.path.isfile(os.path.join(s, "codex-astra.config.toml")),
        "options": manifest_options(options),
    }


# How a run was invoked, not what it installed: kept out of the manifest, so a re-run that installs the
# same bytes (e.g. a flagless run after --ide-default, which keeps the regions) plans nothing.
RUN_ONLY_OPTIONS = ("ide_default_source",)
RUN_ONLY_FLAGS = ("ide_default", "no_ide_default", "force")


def manifest_options(options: dict) -> dict:
    out = {k: v for k, v in options.items() if k not in RUN_ONLY_OPTIONS}
    if isinstance(out.get("flags"), dict):
        out["flags"] = {k: v for k, v in out["flags"].items() if k not in RUN_ONLY_FLAGS}
    return out


def write_manifest(s, commit, work) -> dict:
    m = build_manifest(s, commit, work)
    ist.write_json(os.path.join(s, ".stack-manifest.json"), m, mode=0o644)
    return m


def retrust(old, new) -> list:
    """Hook keys of `new` (a manifest) that are new or whose definition fingerprint changed since
    `old` (a manifest, or None): each needs /hooks trust again."""
    def fps(m):
        hooks = m.get("hooks") if isinstance(m, dict) else None
        return {h["key"]: h.get("fingerprint") for h in hooks or [] if isinstance(h, dict) and "key" in h}
    before = fps(old)
    return [k for k, fp in fps(new).items() if before.get(k) != fp]


# ---- CLI ------------------------------------------------------------------------------------------
def _emit(k, v):
    # one value per line whatever the environment held
    print("%s\t%s" % (k, re.sub(r"[\x00-\x1f\x7f]", lambda m: "\\x%02x" % ord(m.group()), str(v))))


def _usage():
    sys.stderr.write(__doc__.split("\n\n")[2] + "\n")
    return 2


def main(argv) -> int:
    cmd = argv[1] if len(argv) > 1 else ""
    a = argv[2:]
    need = {"home": 2, "stage": 2, "plan": 4, "apply": 6, "restore": 6, "validate": 1, "manifest": 3,
            "retrust": 2, "latest": 2, "new-backup": 3}
    if cmd not in need or len(a) < need[cmd]:
        return _usage()
    try:
        if cmd == "home":
            env = dict(os.environ)
            home = env.get("HOME") or os.path.expanduser("~")
            try:
                r = codex_home.resolve(a[1] if a[0] == "1" else None, env, home, ist._cwd(), a[2:])
            except codex_home.CodexHomeError as exc:
                sys.stderr.write("codex_config/install.sh: %s. Nothing was changed.\n" % exc)
                return 2
            for k in ("path", "real", "source"):
                _emit(k, r[k])
            _emit("created", "%d" % r["created"])
            for line in r["warn"]:
                _emit("warn", line)
        elif cmd == "stage":
            stage(a[0], a[1], a[2] if len(a) > 2 else None)
        elif cmd == "plan":
            return plan(a[0], a[1], a[2], a[3], a[4] if len(a) > 4 else None)
        elif cmd == "apply":
            apply(*a[:6], snap_path=a[6] if len(a) > 6 else None)
        elif cmd == "restore":
            flags = a[6:]
            unknown = [f for f in flags if f not in ("--dry-run", "--force", "--force-config")]
            if unknown:
                return _usage()
            dry = "--dry-run" in flags
            bdir, undo, _meta = restore(*a[:6], dry=dry, force="--force" in flags,
                                        force_config="--force-config" in flags)
            fd = os.open(os.path.join(a[3], "restore.json"), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w") as f:
                json.dump({"backup": bdir, "undo": undo, "dry": dry}, f)
        elif cmd == "validate":
            problems = validate(a[0])
            for p in problems:
                print("  ! " + p)
            return 1 if problems else 0
        elif cmd == "manifest":
            write_manifest(a[0], a[1], a[2])
        elif cmd == "retrust":
            old = None if a[0] == "-" else ist.load_json(a[0], None)
            new = ist.load_json(a[1], None)
            if not isinstance(new, dict):
                sys.stderr.write("codex_state: %s is not a manifest\n" % a[1])
                return 1
            for k in retrust(old, new):
                print(k)
        elif cmd == "latest":
            found = ist.backups_of(a[0], a[1])
            print(found[-1] if found else "")
        elif cmd == "new-backup":
            with reworded():
                print(ist.empty_backup(a[0], a[1], a[2]))
    except SystemExit as exc:
        if isinstance(exc.code, str):
            sys.stderr.write(wording(exc.code) + "\n")
            return 1
        raise
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
