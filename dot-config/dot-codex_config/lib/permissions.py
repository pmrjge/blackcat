"""Credential set and permission profile for the Codex port (DESIGN.md §4.1 L1, §4.2, F14, F15).

Entry points (INTERFACES.md §3-F):
- credential_set(settings, ctx) -> {"paths": [...], "globs": [...]}: what the sandboxed agent must
  never read. `paths` are absolute files or directories (a directory covers everything below it);
  `globs` are fnmatch patterns over absolute paths (fnmatch's `*` also crosses `/`, so a glob covers
  everything below a match too). Always holds <codex_home>/auth.json (Codex's file credential store)
  and <codex_home>/stack.env. Consumers: guard.json "credentials" (render), the profile's `deny`
  entries, requirements.toml `deny_read`.
- permission_profile(settings, ctx) -> the `[permissions.claude-agent-stack]` table:
  `extends = ":workspace"`, `"<CODEX_HOME>" = "read"`, `"<HOME>/.agents" = "read"`, the guard state
  dir `"read"`, a `deny` for every credential path or absolute glob, `read` for the write-protected
  paths, `":workspace_roots"` scoped entries for project-relative patterns, and `network` with the
  allowed domains. The profile's `[features] network_proxy = true` is render_profile's job (F15).
- network_domains(settings) -> {"<domain>": "allow"} from sandbox.network.allowedDomains.
- report(settings, ctx) -> notes on what was translated, covered or left to the guard.

Sources (dot-claude/settings.json): `Read(...)` denies and `sandbox.filesystem.denyRead` become
read denials (Codex `deny` = no read, no write); `Edit(...)`/`Write(...)` denies and
`sandbox.filesystem.denyWrite` become write protection (Codex `read`), because a Claude Edit deny
still lets the agent read the file. Placeholders are rendered for this machine twice where the
path has a Codex analogue: once for the Codex install (`__CLAUDE_DIR__` -> <codex_home>, with
`.credentials.json` -> `auth.json`; `__STACK_STATE__` -> the guard state dir; `__STACK_BACKUPS__`
and `__STACK_CACHE__` -> its `-backups`/`-cache` siblings) and once for the Claude install that
lives on the same machine (`<home>/.claude`, `~/.local/state/claude-agent-stack…`), so a Codex
agent cannot read Claude's keys either. `__EQ_TUNNEL__` and `~/.claude.json` exist only on the
Claude side. ctx may override the Claude side with `claude_dir`, `claude_state`, `cache_home`.

Codex path grammar (vendored core/src/config/permissions.rs, rust-v0.160.1): a key is absolute,
`~/...` or `:special`; a glob is accepted only with `deny`, or as a trailing `/**` (which means the
directory) with `read`/`write`; project-relative patterns go in the `":workspace_roots"` scoped table.
A write-protect pattern with an inner glob therefore cannot be expressed and is left to the guard
(reported). `.git` and `.codex` inside a workspace are already read-only (F14).

Unverified, settled by probe P7/P7b (DESIGN U5, U6): whether a permission profile declared in the
profile file applies; whether `"<CODEX_HOME>" = "read"` outranks a `:workspace_roots` write when cwd
is inside CODEX_HOME; whether `deny` on <codex_home>/auth.json outranks the `read` on CODEX_HOME;
whether entries for paths that do not exist are accepted; whether a profile can grant `.git` write
(U6). Until then the guard's path checks (§4.2 f) are the second line.

Seeded-bug proofs (tests/mutations/permissions.json, each turns test_permissions.py red): drop
auth.json from the credential set; map Edit denies to `deny` instead of `read`; skip the CODEX_HOME
`read` entry; drop the `:workspace_roots` deny of project-relative patterns; drop them from the
credential set; drop the network allowlist.
"""
from __future__ import annotations

import os
import re

__all__ = ["BuildError", "PROFILE_NAME", "credential_set", "permission_profile", "network_domains",
           "report"]

PROFILE_NAME = "claude-agent-stack"
WORKSPACE_ROOTS = ":workspace_roots"
_GLOB = re.compile(r"[*?\[\]]")
_PLACEHOLDER = re.compile(r"__[A-Z][A-Z0-9_]*__")
_BAD = re.compile(r"[\x00-\x1f\x7f]")
_RULE = re.compile(r"(Read|Edit|Write|NotebookEdit)\((.+)\)\Z")
# __CLAUDE_DIR__ sub-paths and their Codex analogue (None: no Codex analogue, Claude side only)
_CODEX_RENAME = {".credentials.json": "auth.json", ".claude.json": None, "backup-*": None,
                 "backup-*/**": None}


class BuildError(Exception):
    """settings.json or ctx holds something this module cannot translate (never guessed)."""


def _abs(ctx, key, default=None):
    v = ctx.get(key) or default
    if not isinstance(v, str) or not os.path.isabs(v) or _BAD.search(v):
        raise BuildError("ctx[%r] must be an absolute path, got %r" % (key, v))
    return os.path.normpath(v)


def _paths(ctx):
    home = _abs(ctx, "home")
    ch = _abs(ctx, "codex_home")
    state = _abs(ctx, "state_dir", os.path.join(home, ".local", "state", "codex-agent-stack"))
    return {
        "home": home, "codex_home": ch, "state_dir": state,
        "claude_dir": _abs(ctx, "claude_dir", os.path.join(home, ".claude")),
        "claude_state": _abs(ctx, "claude_state",
                             os.path.join(os.path.dirname(state), "claude-agent-stack")),
        "cache_home": _abs(ctx, "cache_home", os.path.join(home, ".cache")),
    }


def _placeholder_targets(ph, rest, P):
    """[(base, rest)] for one placeholder: the Codex analogue first, then the Claude side."""
    if ph == "__CLAUDE_DIR__":
        out = []
        codex_rest = _CODEX_RENAME.get(rest, rest)
        if codex_rest is not None:
            out.append((P["codex_home"], codex_rest))
        out.append((P["claude_dir"], rest))
        return out
    if ph == "__STACK_STATE__":
        return [(P["state_dir"], rest), (P["claude_state"], rest)]
    if ph == "__STACK_BACKUPS__":
        return [(P["state_dir"] + "-backups", rest), (P["claude_state"] + "-backups", rest)]
    if ph == "__STACK_CACHE__":
        return [(P["state_dir"] + "-cache", rest), (P["claude_state"] + "-cache", rest)]
    if ph == "__EQ_TUNNEL__":
        return [(os.path.join(P["cache_home"], "claude-agent-stack", "eq-tunnel"), rest)]
    raise BuildError("unmapped placeholder %s" % ph)


def _render(spec, P):
    """Claude path spec -> [("abs", path-or-glob) | ("ws", project-relative pattern)]."""
    if not isinstance(spec, str) or not spec or _BAD.search(spec):
        raise BuildError("bad path spec %r" % (spec,))
    s = spec
    if s.startswith("/__"):          # "/__X__/..": the placeholder renders to an absolute path
        s = s[1:]
    m = _PLACEHOLDER.match(s)
    if m:
        ph, rest = m.group(), s[m.end():]
        if rest and not rest.startswith("/"):
            raise BuildError("unmapped placeholder use %r" % spec)
        rest = rest.lstrip("/")
        return [("abs", os.path.join(base, r) if r else base)
                for base, r in _placeholder_targets(ph, rest, P)]
    if _PLACEHOLDER.search(s):
        raise BuildError("unmapped placeholder in %r" % spec)
    if s.startswith("//"):           # Claude: absolute path
        return [("abs", s[1:])]
    if s == "~" or s.startswith("~/"):
        return [("abs", os.path.join(P["home"], s[2:]) if s != "~" else P["home"])]
    if s.startswith("/") or s.startswith("~"):
        # Claude "/x" is relative to the settings file's folder: no Codex meaning
        raise BuildError("unmapped settings-relative path %r" % spec)
    if s.startswith("./"):
        s = s[2:]
    if not s or s.split("/")[0] in ("", ".", ".."):
        raise BuildError("unmapped relative path %r" % spec)
    return [("ws", s)]


def _strip_tree(p):
    """'<x>/**' -> ('<x>', True); else (p, False)."""
    return (p[:-3], True) if p.endswith("/**") else (p, False)


def _entries(settings, P):
    """[(mode, kind, target, source)] with mode "deny" (no read) or "read" (no write)."""
    if not isinstance(settings, dict):
        raise BuildError("settings must be a dict")
    perms = settings.get("permissions") or {}
    fs = ((settings.get("sandbox") or {}).get("filesystem")) or {}
    raw = []
    for e in perms.get("deny") or []:
        m = _RULE.match(e) if isinstance(e, str) else None
        if m:
            raw.append(("deny" if m.group(1) == "Read" else "read", m.group(2), "deny " + e))
    for p in fs.get("denyRead") or []:
        raw.append(("deny", p, "sandbox.filesystem.denyRead " + str(p)))
    for p in fs.get("denyWrite") or []:
        raw.append(("read", p, "sandbox.filesystem.denyWrite " + str(p)))
    out = []
    for mode, spec, src in raw:
        for kind, target in _render(spec, P):
            out.append((mode, kind, target, src))
    return out


def _under(path, root):
    return path == root or path.startswith(root.rstrip("/") + "/")


def _build(settings, ctx):
    P = _paths(ctx)
    entries = _entries(settings, P)
    notes = []
    cred_paths, cred_globs = [], []
    ws = {}                               # project-relative subpath -> access
    deny_keys, read_paths, read_globs = [], [], []

    def add(lst, v):
        if v not in lst:
            lst.append(v)

    fixed = [os.path.join(P["codex_home"], "auth.json"), os.path.join(P["codex_home"], "stack.env")]
    for f in fixed:
        add(cred_paths, f)
        add(deny_keys, f)
    for mode, kind, target, src in entries:
        if kind == "ws":
            base, tree = _strip_tree(target)
            glob = bool(_GLOB.search(base))
            if mode == "deny":
                add(cred_globs, base if base.startswith("**/") else "**/" + base)
                key = target if glob else base
                ws[key] = "deny"
            elif glob:
                if base.split("/")[0] in (".git", ".codex"):
                    notes.append("covered by Codex itself (.git/.codex read-only in a workspace, "
                                 "F14): %s" % src)
                else:
                    notes.append("guard-only (a write-protect glob Codex cannot express): %s"
                                 % src)
            elif ws.get(base) != "deny":
                ws[base] = "read"
            continue
        base, tree = _strip_tree(target)
        glob = bool(_GLOB.search(base))
        if mode == "deny":
            if glob:
                add(cred_globs, base)
                add(deny_keys, target)
            else:
                add(cred_paths, base)
                add(deny_keys, base)
        elif glob:
            read_globs.append((base, src, target))
        else:
            add(read_paths, base)

    read_roots = [P["codex_home"], os.path.join(P["home"], ".agents"), P["state_dir"]]
    fs = {}
    for r in read_roots:
        fs[r] = "read"
    deny_paths = [k for k in deny_keys if not _GLOB.search(k)]
    for p in sorted(read_paths, key=len):
        cover = next((r for r in list(fs) if fs[r] == "read" and _under(p, r)), None) or \
            next((d for d in deny_paths if _under(p, d)), None)
        if cover:
            notes.append("covered: write protection of %s by %s" % (p, cover))
            continue
        fs[p] = "read"
    for g, src, target in read_globs:
        lit = _GLOB.split(g, 1)[0].rsplit("/", 1)[0] or "/"
        cover = next((r for r in list(fs) if fs[r] == "read" and _under(lit, r)), None)
        if cover:
            notes.append("covered: write protection of %s by %s" % (target, cover))
        else:
            notes.append("guard-only (a write-protect glob Codex cannot express): %s -> %s"
                         % (src, target))
    for k in deny_keys:
        if not _GLOB.search(k):
            outer = next((d for d in deny_paths if d != k and _under(k, d)), None)
            if outer:
                notes.append("covered: read denial of %s by %s" % (k, outer))
                continue
        fs[k] = "deny"
    if ws:
        fs[WORKSPACE_ROOTS] = dict(ws)
    notes.append("covered by Codex itself: .git and .codex inside a workspace are read-only (F14)")
    cred = {"paths": cred_paths, "globs": cred_globs}
    return cred, fs, notes


def credential_set(settings: dict, ctx: dict) -> dict:
    cred, _, _ = _build(settings, ctx)
    return {"paths": list(cred["paths"]), "globs": list(cred["globs"])}


def network_domains(settings: dict) -> dict:
    net = ((settings.get("sandbox") or {}).get("network")) or {}
    doms = net.get("allowedDomains")
    if not isinstance(doms, list) or not doms:
        raise BuildError("sandbox.network.allowedDomains is missing or empty")
    out = {}
    for d in doms:
        if not isinstance(d, str) or not d.strip() or _BAD.search(d) or "/" in d or d.strip() == "*":
            raise BuildError("bad allowed domain %r" % (d,))
        out[d.strip()] = "allow"
    return out


def permission_profile(settings: dict, ctx: dict) -> dict:
    _, fs, _ = _build(settings, ctx)
    net = ((settings.get("sandbox") or {}).get("network")) or {}
    network = {"enabled": True, "mode": "full", "domains": network_domains(settings)}
    if net.get("allowLocalBinding"):
        network["allow_local_binding"] = True
    return {
        "description": "claude-agent-stack: workspace-write; CODEX_HOME, ~/.agents and the guard "
                       "state read-only; credentials denied; network allowlist",
        "extends": ":workspace",
        "filesystem": fs,
        "network": network,
    }


def report(settings: dict, ctx: dict) -> list:
    _, _, notes = _build(settings, ctx)
    fs = (settings.get("sandbox") or {}).get("filesystem") or {}
    for p in fs.get("allowWrite") or []:
        notes.append("dropped: sandbox.filesystem.allowWrite %s (Claude sandbox cache)" % p)
    env = ((settings.get("sandbox") or {}).get("credentials") or {}).get("envVars") or []
    if env:
        notes.append("not here: %d sandbox.credentials.envVars denies belong to the profile's "
                     "shell_environment_policy (render_profile)" % len(env))
    return notes
