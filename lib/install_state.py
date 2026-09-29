"""State handling for install.sh: stage, plan, back up, apply, restore, validate.

install.sh never edits the config dir ($C, default ~/.claude) in place. It copies the part of $C the
stack manages (SCOPE) into a staging directory, renders, merges and prunes there, validates the
result, and compares it with $C. The plan (files added, changed and removed) is printed; --dry-run
stops there. A real run first saves every file it will change or remove, plus the list of files it
will add, into one backup directory outside $C (0700, files 0600), then applies the plan. Restoring
a backup is the same operation in reverse, so a restore is itself backed up.

Runs on the system python3 (3.8+), standard library only.

  install_state.py stage    <C> <S>                          copy SCOPE of C into the empty dir S
  install_state.py plan     <C> <S> <report.json> <plan.json>  compare, print, write the plan
  install_state.py apply    <C> <S> <plan.json> <backup-root> <commit> <out-file>
  install_state.py restore  <C> <backup-dir|latest> <backup-root> <work-dir> <commit> <home> [--dry-run]
  install_state.py validate <S> <python>                     JSON, frontmatter, placeholders, self-test
  install_state.py legacy-backups <C> <backup-root> list|move
  install_state.py record   <backup-dir> <key> <name>        key: plugins_disabled, rc (a path),
                            file (a path relative to C), mcp_removed / mcp_replaced (the entry's
                            JSON in $STACK_MCP_ENTRY)
  install_state.py latest   <C> <backup-root>
  install_state.py new-backup <C> <backup-root> <commit>       an empty backup (prints its path)
"""
from __future__ import annotations

import datetime
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile

# What install.sh manages inside the config dir. Everything else there (projects/, sessions,
# credentials, plugins/, venvs/, mcp/vendor/, the claude.ai-synced skills) is never staged, compared,
# backed up or touched.
SCOPE_DIRS = ("agents", "skills", "rules", "hooks", "bin", "mcp", "stack-plugins", ".stack-plugins.new")
SCOPE_FILES = ("settings.json", "stack.env", ".stack-manifest.json", "CLAUDE.md", "CLAUDE.md.new",
               "magg/config.json", "settings.json.tmp", "stack.env.tmp", ".stack-manifest.json.tmp",
               "magg/config.json.tmp")
EXCLUDED = ("skills/synced", "mcp/vendor")
# Written through a symlink (a dotfiles repo) instead of replacing the link.
WRITE_THROUGH = ("settings.json", "stack.env")
BACKUP_FORMAT = 1


def excluded(rel):
    return any(rel == x or rel.startswith(x + "/") for x in EXCLUDED)


def in_scope(rel):
    """True for a relative path inside SCOPE (what a backup may hold): no absolute path, no "..",
    nothing excluded."""
    if not isinstance(rel, str) or not rel or os.path.isabs(rel) or "\\" in rel:
        return False
    norm = os.path.normpath(rel)
    if norm != rel or norm.startswith("..") or "/../" in "/%s/" % norm or excluded(norm):
        return False
    return norm in SCOPE_FILES or any(norm == d or norm.startswith(d + "/") for d in SCOPE_DIRS)


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def leaf(path, rel):
    """(kind, identity) of one entry: a symlink is compared by its target (not followed), a file by
    content and executable bit; WRITE_THROUGH files are followed through a link. stack.env holds
    the API keys: its whole mode counts, so a world-readable copy is a change the plan repairs."""
    if os.path.islink(path) and rel not in WRITE_THROUGH:
        return ("l", os.readlink(path))
    mode = os.stat(path).st_mode
    return ("f", sha256_file(path), stat.S_IMODE(mode) if rel == "stack.env" else bool(mode & 0o111))


def scan(root):
    """{rel: leaf} for every file and symlink of SCOPE under root. A scope directory that is itself
    a symlink (a dotfiles checkout) is followed; links below it are leaves."""
    out = {}

    def walk(d, rel_d):
        try:
            entries = sorted(os.scandir(d), key=lambda e: e.name)
        except (FileNotFoundError, NotADirectoryError):
            return
        for e in entries:
            rel = rel_d + "/" + e.name
            if excluded(rel):
                continue
            if e.is_symlink():
                out[rel] = ("l", os.readlink(e.path))
            elif e.is_dir():
                walk(e.path, rel)
            elif e.is_file():
                out[rel] = leaf(e.path, rel)

    for d in SCOPE_DIRS:
        p = os.path.join(root, d)
        if os.path.isdir(p):
            walk(p, d)
        elif os.path.lexists(p):            # a stray file or dangling link where a dir belongs
            out[d] = ("l", os.readlink(p)) if os.path.islink(p) else leaf(p, d)
    for rel in SCOPE_FILES:
        p = os.path.join(root, rel)
        if os.path.isfile(p) or (os.path.islink(p) and rel not in WRITE_THROUGH):
            out[rel] = leaf(p, rel)
    return out


def copy_entry(src, dst, rel):
    """Copy one leaf (a symlink as a symlink, except WRITE_THROUGH files) keeping its mode."""
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    if os.path.lexists(dst):
        if os.path.isdir(dst) and not os.path.islink(dst):
            shutil.rmtree(dst)
        else:
            os.unlink(dst)
    if os.path.islink(src) and rel not in WRITE_THROUGH:
        os.symlink(os.readlink(src), dst)
    else:
        shutil.copy2(src, dst)


def stage(c, s):
    for rel in scan(c):
        copy_entry(os.path.join(c, rel), os.path.join(s, rel), rel)
    for d in SCOPE_DIRS:                    # empty scope dirs too, so renders see the same layout
        if os.path.isdir(os.path.join(c, d)):
            os.makedirs(os.path.join(s, d), exist_ok=True)


# --------------------------------------------------------------------------------------- plan
def load_json(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def gone_dir(rel, dirs, removed, before, after):
    """The directory (a report key ending in "/") holding rel when every file of it goes and
    nothing of it stays: the listing names it once. Skills count as such directories anyway."""
    parts = rel.split("/")
    cands = [d for d in dirs if rel.startswith(d)]
    if parts[0] == "skills" and len(parts) >= 3:
        cands.append("skills/%s/" % parts[1])
    for prefix in sorted(set(cands), key=len):
        if any(r.startswith(prefix) for r in after):
            continue
        if all(r in removed for r in before if r.startswith(prefix)):
            return prefix
    return None


def make_plan(c, s, report_path):
    before, after = scan(c), scan(s)
    report = load_json(report_path, {})
    added = sorted(r for r in after if r not in before)
    removed = sorted(r for r in before if r not in after)
    changed = sorted(r for r in after if r in before and after[r] != before[r])
    reasons = report.get("removed") or {}
    replaced = report.get("replaced") or {}
    dirs = [k for k in reasons if k.endswith("/")]
    removed_set = set(removed)
    listing, seen = [], set()
    for rel in removed:
        key = gone_dir(rel, dirs, removed_set, before, after) or rel
        if key in seen:
            continue
        seen.add(key)
        why = reasons.get(key) or reasons.get(rel) or next(
            (reasons[d] for d in sorted(dirs, key=len, reverse=True) if rel.startswith(d)),
            "not part of the stack")
        listing.append((key, why))
    listing += [tuple(x) for x in report.get("config_removed") or []]
    return {
        "added": added, "changed": changed, "removed": removed,
        "replaced": sorted((r, replaced[r]) for r in changed if r in replaced)
                    + [tuple(x) for x in report.get("config_replaced") or []],
        "removed_listing": listing,
        "notes": report.get("notes") or [],
    }


def print_plan(plan):
    a, ch, rm = plan["added"], plan["changed"], plan["removed"]
    if not (a or ch or rm):
        print("  no changes: the config dir already matches this stack version")
        for n in plan["notes"]:
            print("  note: " + n)
        return
    print("  changes: %d added, %d updated, %d removed" % (len(a), len(ch), len(rm)))
    rep = {r for r, _ in plan["replaced"]}
    other = [r for r in ch if not r.startswith(("agents/", "skills/")) and r not in rep]
    if other:
        print("  updated: " + ", ".join(other))
    if plan["replaced"]:
        print("replaced: differed from the stack's version (the backup keeps yours)")
        for rel, why in plan["replaced"]:
            print("  ~ %s  (%s)" % (rel, why))
    if plan["removed_listing"]:
        print("removed: not part of the stack")
        for rel, why in plan["removed_listing"]:
            print("  - %s  (%s)" % (rel, why))
    for n in plan["notes"]:
        print("  note: " + n)


# ------------------------------------------------------------------------------ backup, apply
def new_backup_dir(root):
    os.makedirs(root, mode=0o700, exist_ok=True)
    os.chmod(root, 0o700)
    ts = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    d = tempfile.mkdtemp(prefix=ts + "-", dir=root)       # 0700; unique even within one second
    os.chmod(d, 0o700)
    return d


def save_entry(c, rel, bdir):
    """Copy C/rel into the backup (0600; a symlink as a symlink) and describe it."""
    src = os.path.join(c, rel)
    dst = os.path.join(bdir, "files", rel)
    os.makedirs(os.path.dirname(dst), mode=0o700, exist_ok=True)
    if os.path.islink(src) and rel not in WRITE_THROUGH:
        os.symlink(os.readlink(src), dst)
        return {"type": "l", "target": os.readlink(src)}
    through = os.path.islink(src)
    shutil.copyfile(src, dst)
    os.chmod(dst, 0o600)
    return {"type": "f", "mode": stat.S_IMODE(os.stat(src).st_mode), "sha256": sha256_file(dst),
            "through": through}


def fix_dir_modes(bdir):
    for root, dirs, _files in os.walk(bdir):
        for d in dirs:
            p = os.path.join(root, d)
            if not os.path.islink(p):
                os.chmod(p, 0o700)


def write_json(path, data, mode=0o600):
    tmp = path + ".tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, mode)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, sort_keys=True)
        f.write("\n")
    os.replace(tmp, path)


def place(src, c, rel):
    """Put S/rel at C/rel: atomically for files (write-through for a symlinked WRITE_THROUGH
    file), as a symlink for a link."""
    dst = os.path.join(c, rel)
    if os.path.islink(src):
        if os.path.lexists(dst):
            if os.path.isdir(dst) and not os.path.islink(dst):
                shutil.rmtree(dst)
            else:
                os.unlink(dst)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        os.symlink(os.readlink(src), dst)
        return
    if rel in WRITE_THROUGH and os.path.islink(dst):
        dst = os.path.realpath(dst)
    elif os.path.islink(dst):
        os.unlink(dst)
    elif os.path.isdir(dst):
        shutil.rmtree(dst)
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(dst), prefix="." + os.path.basename(dst) + ".")
    try:
        with os.fdopen(fd, "wb") as out, open(src, "rb") as inp:
            shutil.copyfileobj(inp, out)
        os.chmod(tmp, stat.S_IMODE(os.stat(src).st_mode))
        os.replace(tmp, dst)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def remove_empty_parents(c, rel):
    top = rel.split("/")[0]
    d = os.path.dirname(rel)
    while d and d != top:
        p = os.path.join(c, d)
        try:
            if os.path.isdir(p) and not os.path.islink(p) and not os.listdir(p):
                os.rmdir(p)
            else:
                break
        except OSError:
            break
        d = os.path.dirname(d)


def backup_meta(c, reason, commit, added=()):
    now = datetime.datetime.now().astimezone()
    return {"format": BACKUP_FORMAT, "config_dir": c, "reason": reason, "stack_commit": commit,
            "created": now.isoformat(timespec="seconds"), "created_epoch": now.timestamp(),
            "entries": {}, "added": list(added), "mcp_removed": {}, "mcp_replaced": {},
            "plugins_disabled": [], "rc": {}}


def empty_backup(c, root, commit, reason="install", extra=None):
    """A backup with no files yet, for the MCP entries, plugins and rc files a run changes later."""
    bdir = new_backup_dir(root)
    meta = backup_meta(c, reason, commit)
    meta.update(extra or {})
    write_json(os.path.join(bdir, "backup.json"), meta)
    return bdir


def apply_plan(c, s, plan, root, commit, reason="install", extra=None):
    """Back up, then apply. Returns the backup dir ("" when nothing changed)."""
    touched = plan["changed"] + plan["removed"]
    if not (touched or plan["added"]):
        return ""
    bdir = new_backup_dir(root)
    meta = backup_meta(c, reason, commit, plan["added"])
    meta.update(extra or {})
    for rel in touched:
        meta["entries"][rel] = save_entry(c, rel, bdir)
    fix_dir_modes(bdir)
    write_json(os.path.join(bdir, "backup.json"), meta)      # complete before anything changes
    for rel in plan["removed"]:
        p = os.path.join(c, rel)
        if os.path.islink(p) or os.path.isfile(p):
            os.unlink(p)
        remove_empty_parents(c, rel)
    for rel in plan["changed"] + plan["added"]:
        place(os.path.join(s, rel), c, rel)
    return bdir


def record(bdir, key, name, value=None):
    path = os.path.join(bdir, "backup.json")
    meta = load_json(path, None)
    if meta is None:
        raise SystemExit("install_state: no backup.json in %s" % bdir)
    if key == "plugins_disabled":
        if name not in meta.setdefault(key, []):
            meta[key].append(name)
    elif key in ("mcp_removed", "mcp_replaced"):
        # the entry comes in the environment (STACK_MCP_ENTRY), never on the command line: an MCP
        # entry can hold a key in its headers
        entry = os.environ.get("STACK_MCP_ENTRY") if value is None else value
        meta.setdefault(key, {}).setdefault(name, json.loads(entry))   # the first (pre-install) one
    elif key == "file":
        # a file of C a later step changes after the apply (the manifest, stack.env): saved as it
        # is now, unless the backup already holds its pre-install version or it was just added
        c, rel = meta["config_dir"], name
        if not in_scope(rel):
            raise SystemExit("install_state: %s is outside the backup scope" % rel)
        if rel not in meta["entries"] and rel not in meta.get("added", []):
            if os.path.lexists(os.path.join(c, rel)):
                meta["entries"][rel] = save_entry(c, rel, bdir)
                fix_dir_modes(bdir)
            else:
                meta.setdefault("added", []).append(rel)
    elif key == "rc":
        src = name
        rcs = meta.setdefault(key, {})
        if src not in rcs:                          # the first (pre-install) copy wins
            fname = "%d-%s" % (len(rcs), os.path.basename(src))
            dst = os.path.join(bdir, "rc", fname)
            os.makedirs(os.path.dirname(dst), mode=0o700, exist_ok=True)
            shutil.copyfile(src, dst)
            os.chmod(dst, 0o600)
            rcs[src] = {"mode": stat.S_IMODE(os.stat(src).st_mode), "file": fname}
    else:
        raise SystemExit("install_state: unknown record key %s" % key)
    write_json(path, meta)


def backups_of(c, root):
    out = []
    try:
        names = sorted(os.listdir(root))
    except FileNotFoundError:
        return out
    for n in names:
        meta = load_json(os.path.join(root, n, "backup.json"), None)
        if isinstance(meta, dict) and os.path.realpath(meta.get("config_dir", "")) == os.path.realpath(c):
            try:
                t = float(meta.get("created_epoch"))
            except (TypeError, ValueError):
                t = 0.0
            out.append((t, meta.get("created", ""), os.path.join(root, n)))
    return [d for _, _, d in sorted(out)]


def restore(c, which, root, work, commit, home, dry=False):
    """Put C back as it was before the install that made the backup: its saved files return, the
    files it added go. Done as a staged plan, so the current state is backed up first. dry: print
    the plan only. Only backups under root are read; every path in backup.json is checked."""
    if which == "latest":
        found = [d for d in backups_of(c, root)
                 if load_json(os.path.join(d, "backup.json"), {}).get("reason") == "install"]
        if not found:
            raise SystemExit("install.sh --restore: no install backup of %s in %s" % (c, root))
        bdir = found[-1]
    else:
        bdir = os.path.realpath(which)
        real_root = os.path.realpath(root)
        if os.path.dirname(bdir) != real_root:
            raise SystemExit("install.sh --restore: %s is not a backup folder in %s" % (which, real_root))
    meta = load_json(os.path.join(bdir, "backup.json"), None)
    if not isinstance(meta, dict) or meta.get("format") != BACKUP_FORMAT:
        raise SystemExit("install.sh --restore: %s is not a backup made by this installer" % bdir)
    if os.path.realpath(meta.get("config_dir", "")) != os.path.realpath(c):
        raise SystemExit("install.sh --restore: %s backs up %s, not %s (set CLAUDE_CONFIG_DIR)"
                         % (bdir, meta.get("config_dir"), c))
    entries, added = meta.get("entries") or {}, meta.get("added") or []
    bad = [r for r in list(entries) + list(added) if not in_scope(r)]
    if bad:
        raise SystemExit("install.sh --restore: %s names paths outside the config scope (%s) — stopping"
                         % (bdir, ", ".join(map(repr, bad[:3]))))
    # rc files: only the shell rc files the installer edits (~/.zshrc, ~/.bashrc), by realpath
    allowed_rc = {os.path.realpath(os.path.join(home, f)) for f in (".zshrc", ".bashrc")}
    rcs = {}
    for rc, info in (meta.get("rc") or {}).items():
        fname = info.get("file") or os.path.basename(rc)
        if os.path.realpath(rc) not in allowed_rc or os.path.basename(fname) != fname:
            print("  ! skipped %s: not a shell rc file the installer edits" % rc)
            continue
        rcs[rc] = (os.path.join(bdir, "rc", fname), info)
    s = os.path.join(work, "restore")
    os.makedirs(s)
    stage(c, s)
    for rel in added:
        p = os.path.join(s, rel)
        if os.path.islink(p) or os.path.isfile(p):
            os.unlink(p)
    for rel, e in entries.items():
        src = os.path.join(bdir, "files", rel)
        dst = os.path.join(s, rel)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        if os.path.lexists(dst):
            if os.path.isdir(dst) and not os.path.islink(dst):
                shutil.rmtree(dst)
            else:
                os.unlink(dst)
        if e.get("type") == "l":
            os.symlink(e["target"], dst)
        else:
            if os.path.islink(src) or sha256_file(src) != e.get("sha256"):
                raise SystemExit("install.sh --restore: %s changed inside the backup — stopping" % rel)
            shutil.copyfile(src, dst)
            os.chmod(dst, e.get("mode", 0o644) & 0o7777)
    plan = make_plan(c, s, os.path.join(work, "no-report.json"))
    print("  restoring %s" % bdir)
    print_plan(plan)
    if dry:
        for rc in sorted(rcs):
            print("  would restore %s" % rc)
        return bdir, "", meta
    undo = apply_plan(c, s, plan, root, commit, reason="restore", extra={"restored_from": bdir})
    for rc, (src, info) in sorted(rcs.items()):
        if os.path.isfile(src) and not os.path.islink(src):
            real = os.path.realpath(rc)             # a dotfiles symlink stays a symlink
            if os.path.isfile(real):
                if not undo:
                    undo = empty_backup(c, root, commit, reason="restore", extra={"restored_from": bdir})
                record(undo, "rc", real)
            place(src, os.path.dirname(real), os.path.basename(real))
            os.chmod(real, info.get("mode", 0o644) & 0o7777)
            print("  restored %s" % rc)
    return bdir, undo, meta


# ------------------------------------------------------------------------------- validation
KEY_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_-]*):(?:[ \t]+(.*))?$")
PLACEHOLDER_RE = re.compile(r"__[A-Z][A-Z0-9_]*__")


def scalar_problem(v):
    """Why a one-line YAML value would not parse as the plain or quoted scalar it means to be."""
    v = v.strip()
    if not v or v[0] in "|>[{":
        return None
    if v[0] == '"':
        m = re.match(r'"(?:[^"\\]|\\.)*"\s*(#.*)?$', v)
        return None if m else "unterminated double-quoted string"
    if v[0] == "'":
        m = re.match(r"'(?:[^']|'')*'\s*(#.*)?$", v)
        return None if m else "unterminated single-quoted string"
    if v[0] in "*&!%@`":
        return "a plain value cannot start with %r" % v[0]
    if ": " in v or v.endswith(":"):
        return "': ' inside a plain value (quote it)"
    if " #" in v:
        return "' #' starts a comment inside a plain value (quote it)"
    return None


def frontmatter_problems(path, want_name):
    try:
        text = open(path, encoding="utf-8").read()
    except (OSError, UnicodeDecodeError) as exc:
        return ["%s: unreadable (%s)" % (path, exc)]
    if not text.startswith("---\n"):
        return ["%s: no frontmatter" % path]
    end = text.find("\n---\n", 3)
    if end < 0:
        return ["%s: frontmatter not closed" % path]
    keys, problems = {}, []
    for n, line in enumerate(text[4:end].split("\n"), 2):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if "\t" in line[:len(line) - len(line.lstrip())]:
            problems.append("%s:%d: tab indentation" % (path, n))
        if line[0] in " -":
            continue
        m = KEY_RE.match(line)
        if not m:
            problems.append("%s:%d: not a 'key: value' line" % (path, n))
            continue
        if m.group(1) in keys:
            problems.append("%s:%d: duplicate key %s" % (path, n, m.group(1)))
        keys[m.group(1)] = (m.group(2) or "").strip()
        why = scalar_problem(m.group(2) or "")
        if why:
            problems.append("%s:%d: %s: %s" % (path, n, m.group(1), why))
    name = keys.get("name", "").strip("\"'")
    if name != want_name:
        problems.append("%s: name %r should be %r" % (path, name, want_name))
    if not keys.get("description"):
        problems.append("%s: no description" % path)
    return problems


def validate(s, python):
    """(problems, warnings). Problems — anything the stack itself wrote (a file whose hash is the
    manifest's) — stop the install; the same checks on files the stack doesn't own (kept by
    --no-prune: yours, or stack files you edited) only warn."""
    problems, warnings = [], []
    manifest = load_json(os.path.join(s, ".stack-manifest.json"), {})
    ours = manifest.get("files") or {}

    def owned(rel):
        p = os.path.join(s, rel)
        return rel in ours and os.path.isfile(p) and sha256_file(p) == ours[rel]

    for rel in ("settings.json", "magg/config.json", ".stack-manifest.json"):
        p = os.path.join(s, rel)
        if os.path.isfile(p):
            try:
                with open(p, encoding="utf-8") as f:
                    text = f.read()
                json.loads(text)
            except ValueError as exc:
                problems.append("%s: invalid JSON (%s)" % (rel, exc))
                continue
            m = PLACEHOLDER_RE.search(text)
            if m and rel != ".stack-manifest.json":
                problems.append("%s: unresolved placeholder %s" % (rel, m.group(0)))
    checks = []
    for f in sorted(os.listdir(os.path.join(s, "agents"))):
        if f.endswith(".md"):
            checks.append(("agents/" + f, f[:-3]))
    skills_dir = os.path.join(s, "skills")
    for name in sorted(os.listdir(skills_dir)):
        if os.path.isfile(os.path.join(skills_dir, name, "SKILL.md")):
            checks.append(("skills/%s/SKILL.md" % name, name))
    for rel, want in checks:
        (problems if owned(rel) else warnings).extend(frontmatter_problems(os.path.join(s, rel), want))
    for d in ("agents", "rules", "skills"):
        for root, _dirs, files in os.walk(os.path.join(s, d)):
            for f in files:
                if not f.endswith(".md"):
                    continue
                p = os.path.join(root, f)
                rel = os.path.relpath(p, s)
                try:
                    with open(p, encoding="utf-8") as fh:
                        m = PLACEHOLDER_RE.search(fh.read())
                except (OSError, UnicodeDecodeError):
                    continue
                if m:
                    (problems if owned(rel) else warnings).append(
                        "%s: unresolved placeholder %s" % (rel, m.group(0)))
    guard = os.path.join(s, "hooks", "agent_guard.py")
    try:
        p = subprocess.run([python, guard, "--self-test"], stdin=subprocess.DEVNULL, capture_output=True,
                           text=True, timeout=120)
        if p.returncode != 0:
            problems.append("hooks/agent_guard.py --self-test: " + " | ".join(
                (p.stdout + p.stderr).strip().splitlines()[-5:]))
    except (OSError, subprocess.SubprocessError) as exc:
        problems.append("hooks/agent_guard.py --self-test could not run: %s" % exc)
    return problems, warnings


# ---------------------------------------------------------------------------- legacy backups
def legacy_backups(c):
    try:
        return sorted(os.path.join(c, n) for n in os.listdir(c)
                      if n.startswith("backup-") and os.path.isdir(os.path.join(c, n))
                      and not os.path.islink(os.path.join(c, n)))
    except FileNotFoundError:
        return []


def move_legacy(c, root):
    dest_root = os.path.join(root, "legacy")
    os.makedirs(dest_root, mode=0o700, exist_ok=True)
    os.chmod(root, 0o700)
    os.chmod(dest_root, 0o700)
    moved = []
    for d in legacy_backups(c):
        dst = os.path.join(dest_root, os.path.basename(d))
        if os.path.exists(dst):
            dst = tempfile.mkdtemp(prefix=os.path.basename(d) + "-", dir=dest_root)
            os.rmdir(dst)
        shutil.move(d, dst)
        for r, dirs, files in os.walk(dst):
            for x in dirs:
                p = os.path.join(r, x)
                if not os.path.islink(p):
                    os.chmod(p, 0o700)
            for x in files:
                p = os.path.join(r, x)
                if not os.path.islink(p):
                    os.chmod(p, stat.S_IMODE(os.stat(p).st_mode) & 0o700)
        os.chmod(dst, 0o700)
        moved.append((d, dst))
    return moved


def main(argv):
    cmd = argv[1] if len(argv) > 1 else ""
    a = argv[2:]
    if cmd == "stage":
        stage(a[0], a[1])
    elif cmd == "plan":
        plan = make_plan(a[0], a[1], a[2])
        write_json(a[3], plan)
        print_plan(plan)
    elif cmd == "apply":
        c, s, plan_path, root, commit, out = a
        bdir = apply_plan(c, s, load_json(plan_path, None), root, commit)
        with open(out, "w") as f:
            f.write(bdir)
    elif cmd == "restore":
        c, which, root, work, commit, home = a[:6]
        dry = a[6:] == ["--dry-run"]
        bdir, undo, meta = restore(c, which, root, work, commit, home, dry)
        fd = os.open(os.path.join(work, "restore.json"), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            json.dump({"backup": bdir, "undo": undo, "dry": dry,
                       "mcp_removed": meta.get("mcp_removed") or {},
                       "mcp_replaced": meta.get("mcp_replaced") or {},
                       "plugins_disabled": meta.get("plugins_disabled") or []}, f)
    elif cmd == "validate":
        problems, warnings = validate(a[0], a[1])
        for w in warnings:
            print("  note: %s (a file the stack doesn't own: left as is)" % w)
        for p in problems:
            print("  ! " + p)
        return 1 if problems else 0
    elif cmd == "legacy-backups":
        c, root, op = a
        if op == "list":
            for d in legacy_backups(c):
                print(d)
        else:
            for src, dst in move_legacy(c, root):
                print("  moved %s -> %s" % (src, dst))
    elif cmd == "record":
        record(a[0], a[1], a[2], a[3] if len(a) > 3 else None)
    elif cmd == "new-backup":
        print(empty_backup(a[0], a[1], a[2]))
    elif cmd == "latest":
        found = backups_of(a[0], a[1])
        print(found[-1] if found else "")
    else:
        sys.stderr.write(__doc__)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
