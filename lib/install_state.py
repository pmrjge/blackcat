"""State handling for install.sh: stage, plan, back up, apply, restore, validate.

install.sh never edits the config dir ($C, default ~/.claude) in place. It copies the part of $C the
stack manages (SCOPE) into a staging directory, renders, merges and prunes there, validates the
result, and compares it with $C. The plan (files added, changed and removed) is printed; --dry-run
stops there. A real run first saves every file it will change or remove, plus the list of files it
will add, into one backup directory outside $C (0700, files 0600), then applies the plan. Restoring
a backup is the same operation in reverse, so a restore is itself backed up.

Runs on the system python3 (3.8+), standard library only.

  install_state.py stage    <C> <S> [snapshot.json]          copy SCOPE of C into the empty dir S
                            (snapshot: the state of C now, which plan/apply check again)
  install_state.py plan     <C> <S> <report.json> <plan.json> [snapshot.json]
                            compare, print, write the plan
  install_state.py apply    <C> <S> <plan.json> <backup-root> <commit> <out-file> [snapshot.json]
  install_state.py restore  <C> <backup-dir|latest> <backup-root> <work-dir> <commit> <home>
                            [--dry-run] [--force]
  install_state.py linked   <C>                              top-level scope dirs that are symlinks
  install_state.py private-root <backup-root>                create/check the backup root (0700)
  install_state.py validate <S> <python>                     JSON, frontmatter, placeholders, self-test
  install_state.py legacy-backups <C> <backup-root> list|move
  install_state.py record   <backup-dir> <key> <name>        key: plugins_disabled, rc (a path),
                            file (a path relative to C), mcp_removed / mcp_replaced (the entry's
                            JSON in $STACK_MCP_ENTRY)
  install_state.py latest   <C> <backup-root>
  install_state.py new-backup <C> <backup-root> <commit>       an empty backup (prints its path)
  install_state.py config-dir <flag-set> <flag> <interactive> <quiet> <yes> <no-prompt> [repo...]
                            resolve and check the install target (key<TAB>value lines; exit 2: refused)
  install_state.py ask      <question>                       y/Y/yes on stdin: exit 0, else 1
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
               "magg/config.json", "magg/k8s-mcp.toml", "settings.json.tmp", "stack.env.tmp",
               ".stack-manifest.json.tmp", "magg/config.json.tmp", "magg/k8s-mcp.toml.tmp")
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


def snapshot(c):
    """The state of C's SCOPE as JSON-comparable data (what the plan was computed against)."""
    return {rel: list(v) for rel, v in scan(c).items()}


def drifted(c, snap, rels=None):
    """Paths whose state in C differs from `snap` (all of SCOPE, or just `rels`): something else
    changed them while the installer ran (Claude Code saving settings.json, an editor)."""
    now = snapshot(c)
    keys = (set(snap) | set(now)) if rels is None else set(rels)
    return sorted(r for r in keys if snap.get(r) != now.get(r))


def linked_dirs(c):
    """{dir: resolved target} for the top-level scope dirs of C that are symlinks (a dotfiles
    checkout). Their contents are the user's: the installer never removes anything through them,
    and install.sh writes the stack's files through them only with --force."""
    out = {}
    for d in SCOPE_DIRS + ("magg",):
        p = os.path.join(c, d)
        if os.path.islink(p):
            out[d] = os.path.realpath(p)
    return out


def within(path, root):
    return path == root or path.startswith(root.rstrip(os.sep) + os.sep)


def stage(c, s, snap_path=None):
    snap = snapshot(c)
    for rel in snap:
        copy_entry(os.path.join(c, rel), os.path.join(s, rel), rel)
    for d in SCOPE_DIRS:                    # empty scope dirs too, so renders see the same layout
        if os.path.isdir(os.path.join(c, d)):
            os.makedirs(os.path.join(s, d), exist_ok=True)
    if snap_path:
        write_json(snap_path, snap)
    return snap


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


def make_plan(c, s, report_path, default_why="not part of the stack", keep_linked=True):
    """keep_linked: nothing below a symlinked top-level scope dir is removed (an install); a
    restore passes False, since the files it removes there are the ones the install added."""
    before, after = scan(c), scan(s)
    report = load_json(report_path, {})
    linked = linked_dirs(c)
    added = sorted(r for r in after if r not in before)
    removed = sorted(r for r in before if r not in after)
    kept_linked = [r for r in removed if keep_linked and r.split("/")[0] in linked]
    removed = [r for r in removed if r not in kept_linked]
    changed = sorted(r for r in after if r in before and after[r] != before[r])
    # a link inside a symlinked top-level dir (skills -> ~/dot/skills, ~/dot/skills/x -> x-local)
    # stays, so the stack's files below its name would land in the link's target, unsaved: skipped
    kept_links = [r for r in kept_linked if before[r][0] == "l"]
    through = [r for r in added + changed if any(r.startswith(k + "/") for k in kept_links)]
    added = [r for r in added if r not in through]
    changed = [r for r in changed if r not in through]
    # a file link there (agents -> ~/dot/agents, ~/dot/agents/coder.md -> elsewhere) stays too:
    # the stack's version would replace your link in the checkout with a regular file
    inner_links = [r for r in changed
                   if keep_linked and r.split("/")[0] in linked and before[r][0] == "l"]
    changed = [r for r in changed if r not in inner_links]
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
            default_why)
        listing.append((key, why))
    listing += [tuple(x) for x in report.get("config_removed") or []]
    notes = list(report.get("notes") or [])
    for d, target in sorted(linked.items()):
        mine = [r for r in kept_linked if r.split("/")[0] == d]
        writes = [r for r in added + changed if r.split("/")[0] == d]
        notes.append("%s/ is a symlink to %s (yours): nothing there is removed%s" % (
            d, target, "; %d stack file(s) written through it" % len(writes) if writes else ""))
        for k in [k for k in kept_links if k.split("/")[0] == d]:
            n = len([r for r in through if r.startswith(k + "/")])
            if n:                              # one note per link: not again as "doesn't ship it"
                notes.append("%s: kept (a link inside your symlinked %s/); the stack's %d file(s) "
                             "there are not written through it" % (k, d, n))
                mine.remove(k)
        for r in [r for r in inner_links if r.split("/")[0] == d]:
            notes.append("%s: kept (a link inside your symlinked %s/); the stack's version is not "
                         "written over it" % (r, d))
        for r in mine[:20]:
            notes.append("%s: kept (%s/ is a symlink; the stack doesn't ship it)" % (r, d))
        if len(mine) > 20:
            notes.append("... and %d more kept under %s/" % (len(mine) - 20, d))
    return {
        "added": added, "changed": changed, "removed": removed,
        "replaced": sorted((r, replaced[r]) for r in changed if r in replaced)
                    + [tuple(x) for x in report.get("config_replaced") or []],
        "removed_listing": listing,
        "notes": notes,
        "linked": linked,
        "keep_linked": keep_linked,
    }


def print_plan(plan, removed_heading="removed: not part of the stack"):
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
        print(removed_heading)
        for rel, why in plan["removed_listing"]:
            print("  - %s  (%s)" % (rel, why))
    for n in plan["notes"]:
        print("  note: " + n)


# ------------------------------------------------------------------------------ backup, apply
def ensure_root(root):
    """The backup root as a private directory of this user, 0700: created when missing; a symlink,
    a file or another user's directory there is refused, never followed. True when created."""
    root = os.path.abspath(root)
    os.makedirs(os.path.dirname(root), exist_ok=True)
    try:
        os.mkdir(root, 0o700)
        created = True
    except FileExistsError:
        created = False
    try:
        fd = os.open(root, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | os.O_NOFOLLOW)
    except OSError:
        raise SystemExit("install.sh: the backup folder %s is a symlink or not a directory: "
                         "refusing to use it (move it away)" % root)
    try:
        st = os.fstat(fd)
        if not stat.S_ISDIR(st.st_mode) or st.st_uid != os.getuid():
            raise SystemExit("install.sh: the backup folder %s is not a directory of yours: "
                             "refusing to use it" % root)
        if stat.S_IMODE(st.st_mode) != 0o700:
            os.fchmod(fd, 0o700)
    finally:
        os.close(fd)
    return created


def copy_private(src, dst):
    """Copy src's bytes into a new 0600 file dst (never through a link planted at dst)."""
    fd = os.open(dst, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb") as out, open(src, "rb") as inp:
        shutil.copyfileobj(inp, out)


def new_backup_dir(root):
    ensure_root(root)
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
    copy_private(src, dst)
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
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, mode)
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


def placed_parent(c, rel, gone=()):
    """The directory C/rel lands in, resolved as it will be when the plan is applied: through the
    symlinks that stay, lexically below one the plan removes first (`gone`: rels of C)."""
    parts = rel.split("/")[:-1]
    for i in range(1, len(parts) + 1):
        if "/".join(parts[:i]) in gone:
            above = os.path.realpath(os.path.join(c, *parts[:i - 1]))
            return os.path.normpath(os.path.join(above, *parts[i - 1:]))
    return os.path.realpath(os.path.join(c, *parts))


def unsafe_paths(c, plan):
    """Plan paths that are not SCOPE paths, or that resolve (through a symlinked directory) out of
    C — except the stack's files written through a symlinked top-level dir, which install.sh
    allows only with --force — and removals below such a dir unless the plan says it may."""
    real_c = os.path.realpath(c)
    linked = linked_dirs(c)
    # a symlink the plan removes (skills/x -> ~/dotfiles/x, replaced by the stack's skills/x/) is
    # gone before anything is placed: the path below it is then created, not followed
    gone = {r for r in plan["removed"] if os.path.islink(os.path.join(c, r))}
    bad = []
    for kind in ("removed", "changed", "added"):
        for rel in plan[kind]:
            top = rel.split("/")[0]
            if not in_scope(rel):
                bad.append(rel)
                continue
            parent = placed_parent(c, rel, gone)
            if within(parent, real_c):
                continue
            # through a symlinked top-level dir: only straight below its target, never through a
            # further link inside it (that file would be the link target's, never backed up)
            parts = rel.split("/")
            if top in linked and parent == os.path.normpath(
                    os.path.join(linked[top], *parts[1:-1])) and (
                    kind != "removed" or not plan.get("keep_linked", True)):
                continue
            bad.append(rel)
    return bad


def apply_plan(c, s, plan, root, commit, reason="install", extra=None, snap=None):
    """Back up, then apply. Returns the backup dir ("" when nothing changed). snap: the state of C
    the plan was made against; C must still be in it (checked before the backup and again right
    before the first change), or nothing is changed."""
    touched = plan["changed"] + plan["removed"]
    if not (touched or plan["added"]):
        return ""
    bad = unsafe_paths(c, plan)
    if bad:
        raise SystemExit("install_state: refusing paths outside the config dir: %s — nothing was "
                         "changed" % ", ".join(map(repr, bad[:5])))

    def check_drift(where):
        moved = drifted(c, snap, touched + plan["added"]) if snap is not None else []
        if moved:
            raise SystemExit("install.sh: %s changed while the installer ran (%s) — nothing was "
                             "changed; run it again" % (", ".join(moved[:5]), where))

    check_drift("before the backup")
    bdir = new_backup_dir(root)
    meta = backup_meta(c, reason, commit, plan["added"])
    meta.update(extra or {})
    for rel in touched:
        meta["entries"][rel] = save_entry(c, rel, bdir)
    fix_dir_modes(bdir)
    write_json(os.path.join(bdir, "backup.json"), meta)      # complete before anything changes
    try:
        check_drift("during the backup")
    except SystemExit:
        shutil.rmtree(bdir, ignore_errors=True)
        raise
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
            copy_private(src, dst)
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


def restore(c, which, root, work, commit, home, dry=False, force=False):
    """Put C back as it was before the install that made the backup: its saved files return, the
    files it added go. Done as a staged plan, so the current state is backed up first. dry: print
    the plan only. Only backups under root are read; every path in backup.json is checked. A saved
    symlink whose target leaves C comes back only with force (else it is named and skipped)."""
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
    snap = stage(c, s)
    real_c = os.path.realpath(c)
    # a saved link whose target leaves C comes back only with force; without it, what is at that
    # path now stays (the files the install added below it too), so nothing goes missing
    skipped = []
    for rel, e in entries.items():
        if e.get("type") != "l" or force:
            continue
        target = str(e.get("target") or "")
        at = os.path.join(real_c, os.path.dirname(rel), target)
        if not target or "\x00" in target or not (
                within(os.path.normpath(at), real_c) and within(os.path.realpath(at), real_c)):
            print("  ! skipped %s: it was a link to %s, outside %s; what is there now stays "
                  "(restore it with --force, or: ln -s '%s' '%s')"
                  % (rel, target, c, target, os.path.join(c, rel)))
            skipped.append(rel)

    def kept(rel):
        return any(rel == k or rel.startswith(k + "/") for k in skipped)

    for rel in added:
        p = os.path.join(s, rel)
        if not kept(rel) and (os.path.islink(p) or os.path.isfile(p)):
            os.unlink(p)
    for rel, e in entries.items():
        if kept(rel):
            continue
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
    plan = make_plan(c, s, os.path.join(work, "no-report.json"), "added by that install",
                     keep_linked=False)
    print("  restoring %s" % bdir)
    print_plan(plan, "removed: added by the install being undone")
    if dry:
        for rc in sorted(rcs):
            print("  would restore %s" % rc)
        return bdir, "", meta
    undo = apply_plan(c, s, plan, root, commit, reason="restore", extra={"restored_from": bdir},
                      snap=snap)
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
    # the usage collector runs under the hooks' interpreter (stdlib only): it must parse there; the
    # shipped scheduler model must be a JSON object
    usage = os.path.join(s, "hooks", "stack_usage.py")
    if os.path.isfile(usage):
        try:
            p = subprocess.run([python, "-c", "import ast, sys; ast.parse(open(sys.argv[1]).read())", usage],
                               stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=60)
            if p.returncode != 0:
                problems.append("hooks/stack_usage.py does not parse under %s: %s" % (
                    python, (p.stderr.strip().splitlines() or ["?"])[-1]))
        except (OSError, subprocess.SubprocessError) as exc:
            problems.append("hooks/stack_usage.py could not be checked: %s" % exc)
    model = os.path.join(s, "hooks", "sched_model.json")
    if os.path.isfile(model):
        try:
            with open(model, encoding="utf-8") as fh:
                if not isinstance(json.load(fh).get("types"), dict):
                    raise ValueError("no types")
        except (OSError, ValueError, AttributeError) as exc:
            problems.append("hooks/sched_model.json: %s" % exc)
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
    ensure_root(root)
    dest_root = os.path.join(root, "legacy")
    os.makedirs(dest_root, mode=0o700, exist_ok=True)
    if os.path.islink(dest_root):
        raise SystemExit("install.sh: %s is a symlink: refusing to move backups into it" % dest_root)
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


# ---- install target (--config-dir) -------------------------------------------------------------
# Precedence: --config-dir PATH > CLAUDE_CONFIG_DIR > ~/.claude. A target is refused (exit 2, nothing
# changed) when it is unusable or dangerous; a non-default or ambiguous one is confirmed on a terminal.
# Files and folders that mark a directory as Claude Code's own (or the stack's): a non-default target
# that is a non-empty directory with none of them is "foreign" and needs a yes on the terminal.
CONFIG_MARKERS = (".stack-manifest.json", "settings.json", "settings.local.json", ".claude.json",
                  ".credentials.json", "CLAUDE.md", "stack.env", "agents", "skills", "rules", "hooks",
                  "commands", "output-styles", "projects", "plugins", "statsig", "todos",
                  "shell-snapshots")
IGNORED_ENTRIES = (".DS_Store",)
# shell metacharacters that would break the double-quoted hook commands settings.json runs, plus
# control characters (newline, NUL, tab: the installer passes paths through lines and tabs)
BAD_PATH_CHARS = re.compile(r'[\x00-\x1f\x7f"`$\\]')
# never a config dir: equal to one of these (relative to $HOME, or absolute) ...
HOME_EQUAL = (".config", ".local", ".local/bin", ".cache", "Library", "Desktop", "Documents",
              "Downloads", "Applications")
SYSTEM_EQUAL = ("/Users", "/Volumes", "/private", "/var", "/tmp", "/private/tmp", "/private/var", "/opt")
# ... nor inside (or equal to) one of these
HOME_INSIDE = (".ssh", ".gnupg", ".aws", ".kube", ".docker", "Library/Keychains")
SYSTEM_INSIDE = ("/System", "/usr", "/bin", "/sbin", "/etc", "/private/etc", "/dev", "/Library",
                 "/Applications")


class ConfigDirError(Exception):
    """An unsafe or unusable install target; the message says why."""


def _real(p):
    return os.path.realpath(p)


def _same(a, b):
    """The same directory entry: by inode when both exist (APFS and HFS+ are case-insensitive by
    default, so ~/.SSH is ~/.ssh there), else by string."""
    if a == b:
        return True
    try:
        return os.path.samefile(a, b)
    except OSError:
        return False


def _inside(path, root):
    """path equals root or lies below it (both absolute and normalised): by string, then by inode
    for each existing ancestor of path (a different letter case on a case-insensitive volume)."""
    if path == root or path.startswith(root.rstrip("/") + "/"):
        return True
    if not os.path.exists(root):
        return False
    p = path
    while True:
        if os.path.exists(p) and _same(p, root):
            return True
        up = os.path.dirname(p)
        if up == p:
            return False
        p = up


def choose_config_dir(flag, flag_set, env, home):
    """(raw path, source) by precedence: --config-dir > CLAUDE_CONFIG_DIR > ~/.claude. An empty
    CLAUDE_CONFIG_DIR counts as unset (as ${CLAUDE_CONFIG_DIR:-} did); an empty flag is an error."""
    if flag_set:
        if not flag:
            raise ConfigDirError("--config-dir needs a path")
        return flag, "flag"
    if env:
        return env, "env"
    return os.path.join(home, ".claude"), "default"


def absolute_path(raw, home, cwd):
    """~ and ~/... expand to `home`, ~user to that user's home; a relative path is taken from `cwd`.
    Not normalised: `..` is still there (see expand_path)."""
    if not raw:
        raise ConfigDirError("empty path")
    if BAD_PATH_CHARS.search(raw):
        raise ConfigDirError("the path contains a newline, NUL, tab, other control character or one "
                             "of \" ` $ \\ (they would break the hook commands): %r" % raw)
    p = raw
    if p == "~" or p.startswith("~/"):
        p = home + p[1:]
    elif p.startswith("~"):
        p = os.path.expanduser(p)
        if p.startswith("~"):
            raise ConfigDirError("unknown user in %r" % raw)
    return p if os.path.isabs(p) else os.path.join(cwd, p)


def expand_path(raw, home, cwd):
    """absolute_path with `.` and `..` folded lexically, as the shell's `cd DIR && pwd` does."""
    p = os.path.normpath(absolute_path(raw, home, cwd))
    return "/" + p.lstrip("/") if p.startswith("//") else p


def dir_kind(path):
    """missing | empty | stack (has .stack-manifest.json) | claude (a CONFIG_MARKERS entry) | foreign"""
    if not os.path.isdir(path):
        return "missing"
    try:
        names = [n for n in os.listdir(path) if n not in IGNORED_ENTRIES]
    except OSError:
        return "foreign"
    if not names:
        return "empty"
    if ".stack-manifest.json" in names:
        return "stack"
    return "claude" if any(m in names for m in CONFIG_MARKERS) else "foreign"


def manifest_id(c):
    """(repo, commit) a stack install recorded in C/.stack-manifest.json, or None."""
    m = load_json(os.path.join(c, ".stack-manifest.json"), None)
    if not isinstance(m, dict):
        return None
    return (str(m.get("repo") or "?"), str(m.get("commit") or "?"))


def check_config_dir(path, home, repos=(), state_root=None):
    """Raise ConfigDirError when `path` (absolute, normalised) must not be an install target."""
    real, rhome = _real(path), _real(home)
    if path == "/" or real == "/" or _same(real, "/"):
        raise ConfigDirError("refusing / as the config dir")
    if _same(real, rhome) or _inside(rhome, real):
        raise ConfigDirError("refusing %s: it is your home folder or contains it" % path)
    for r in repos:
        if r and (_inside(real, _real(r)) or _inside(path, os.path.normpath(r))):
            raise ConfigDirError("refusing %s: it is inside the stack's repo checkout %s (the installer "
                                 "copies from there)" % (path, r))
    for rel in HOME_EQUAL:
        if _same(real, _real(os.path.join(home, rel))):
            raise ConfigDirError("refusing %s: a general-purpose folder, not a config dir" % path)
    for p in SYSTEM_EQUAL:
        if _same(real, _real(p)):
            raise ConfigDirError("refusing %s: a system folder" % path)
    inside = [os.path.join(home, rel) for rel in HOME_INSIDE] + list(SYSTEM_INSIDE)
    if state_root:
        inside += [os.path.join(state_root, "claude-agent-stack" + s) for s in ("", "-backups", "-cache")]
    for p in inside:
        if _inside(real, _real(p)) or _inside(path, os.path.normpath(p)):
            raise ConfigDirError("refusing %s: inside %s (credentials, system or the stack's own state)"
                                 % (path, p))
    if os.path.lexists(path) and not os.path.isdir(path):
        raise ConfigDirError("refusing %s: it exists and is not a directory" % path)
    if os.path.isdir(path):
        if not os.access(real, os.W_OK | os.X_OK):
            raise ConfigDirError("refusing %s: not writable by you" % path)
        return
    up = os.path.dirname(path)
    while up != os.path.dirname(up) and not os.path.lexists(up):
        up = os.path.dirname(up)
    if not os.path.isdir(up) or not os.access(_real(up), os.W_OK | os.X_OK):
        raise ConfigDirError("refusing %s: it cannot be created (%s is not a writable directory)" % (path, up))


def decide_prompt(reasons, foreign, interactive, quiet=False, yes=False, no_prompt=False):
    """What the installer does about the target: proceed | ask | refuse | warn.
    quiet: --dry-run, --mcp-plan or --print-managed-settings (nothing changes, never asks).
    interactive: stdin AND stdout are terminals."""
    if foreign:
        if quiet:
            return "warn"
        return "ask" if interactive and not yes and not no_prompt else "refuse"
    if not reasons or quiet or yes or no_prompt or not interactive:
        return "proceed"
    return "ask"


def profile_hint(shell):
    """Which startup file exports a variable for the user's login shell on macOS."""
    name = os.path.basename(shell or "")
    if name == "zsh":
        return "~/.zshrc (zsh reads it in every interactive shell; ~/.zprofile only in login shells)"
    if name == "bash":
        return ("~/.bash_profile (macOS Terminal starts bash as a login shell, which reads "
                "~/.bash_profile, not ~/.bashrc)")
    return "your shell's startup file (zsh: ~/.zshrc; bash: ~/.bash_profile)"


def _sq(s):
    return "'" + s.replace("'", "'\"'\"'") + "'"


def resolve_config_dir(flag, flag_set, env, home, cwd, repos=(), state_root=None,
                       stack_claude_json="", shell="", interactive=False, quiet=False, yes=False,
                       no_prompt=False):
    """Everything install.sh needs to know about its target, as a dict (see main: config-dir)."""
    raw, source = choose_config_dir(flag, flag_set, env, home)
    path = expand_path(raw, home, cwd)
    raw_abs = absolute_path(raw, home, cwd)
    if _real(path) != _real(raw_abs):
        raise ConfigDirError("%r goes through a symlink before a '..' (the shell would read it as %s, the "
                             "file system as %s): give the resolved path" % (raw, path, _real(raw_abs)))
    check_config_dir(path, home, repos, state_root)
    real = _real(path)
    default = os.path.join(home, ".claude")
    is_default = _same(real, _real(default))
    env_path = ""
    if env:
        try:
            env_path = expand_path(env, home, cwd)
        except ConfigDirError:
            env_path = env
    env_same = bool(env_path) and _same(_real(env_path), real)
    if source == "flag":
        export = "keep" if env_same else ("unset" if is_default else "set")
    else:
        export = "keep"
    claude_dir_set = (export == "set") or (export == "keep" and bool(env))
    if stack_claude_json:
        claude_json = stack_claude_json
    elif claude_dir_set:
        claude_json = os.path.join(path, ".claude.json")
    else:
        claude_json = os.path.join(home, ".claude.json")
    kind = dir_kind(path)
    nondefault = claude_dir_set or not is_default
    # a foreign folder blocks only a --config-dir target; under CLAUDE_CONFIG_DIR (what Claude Code
    # itself reads, and what CI runs set) it is a warning and, on a terminal, a reason to ask
    foreign_any = kind == "foreign" and not is_default
    foreign = foreign_any and source == "flag"
    reasons = []
    if source == "flag" and not is_default:
        reasons.append("--config-dir names a folder other than ~/.claude")
    if source == "env":
        reasons.append("CLAUDE_CONFIG_DIR is set in this shell (%s)" % env)
    if source == "flag" and env and not env_same:
        reasons.append("CLAUDE_CONFIG_DIR=%s in this shell points elsewhere: a Claude Code started from it "
                       "reads that folder, not this target" % env)
    other = manifest_id(default) if not is_default else None
    mine = manifest_id(path)
    if other and mine and other != mine:
        reasons.append("~/.claude and the target both hold a stack install, and they differ "
                       "(%s at %s vs %s at %s)" % (other[0], other[1][:12], mine[0], mine[1][:12]))
    if foreign_any:
        reasons.append("the target is a non-empty folder with no Claude Code files (none of: %s)"
                       % ", ".join(CONFIG_MARKERS))
    decision = decide_prompt(reasons, foreign, interactive, quiet, yes, no_prompt)
    how = {"flag": "--config-dir", "env": "CLAUDE_CONFIG_DIR",
           "default": "the default (no --config-dir, CLAUDE_CONFIG_DIR unset)"}[source]
    banner = ["install target: %s" % path,
              "  chosen by: %s   (precedence: --config-dir > CLAUDE_CONFIG_DIR > ~/.claude)" % how]
    if real != path:
        banner.append("  resolved: %s (through a symlink)" % real)
    banner.append("  Claude Code's .claude.json for it: %s%s" % (
        claude_json, " (STACK_CLAUDE_JSON)" if stack_claude_json else ""))
    if export == "set":
        banner.append("  this run sets CLAUDE_CONFIG_DIR=%s for the claude commands it runs" % path)
    elif export == "unset" and env:
        banner.append("  this run unsets CLAUDE_CONFIG_DIR for the claude commands it runs")
    if source == "flag" and env and not env_same:
        banner.append("  ! CLAUDE_CONFIG_DIR=%s in this shell is overridden for this run; a Claude Code started "
                      "from this shell still reads that folder" % env)
    if other and not is_default:
        banner.append("  ~/.claude holds another stack install (commit %s): left untouched" % other[1][:12])
    warn = []
    if nondefault:
        if real == _real(default):
            warn.append("! CLAUDE_CONFIG_DIR is set to the default folder: Claude Code then keeps its "
                        ".claude.json inside it (%s), not in ~/.claude.json" % claude_json)
        else:
            warn.append("! a non-default config folder: Claude Code reads it only when CLAUDE_CONFIG_DIR is "
                        "exported%s. Add" % (" (it is set in this shell; keep it in your profile)"
                                             if env_same else ""))
            warn.append("      export CLAUDE_CONFIG_DIR=%s" % _sq(path))
            warn.append("  to %s, then open a new terminal. Apps opened from the Dock or Finder do not read "
                        "shell startup files." % profile_hint(shell))
            warn.append("! settings.json, the hooks and the MCP entries hold absolute paths to this folder: "
                        "to move it, reinstall with --config-dir <new path> (a plain mv breaks them)")
    if foreign and decision in ("refuse", "warn"):
        warn.append("! %s is a non-empty folder with no Claude Code files: a real run asks on a terminal "
                    "and stops without one (empty it, or pick another folder)" % path)
    elif foreign_any and not foreign:
        warn.append("! CLAUDE_CONFIG_DIR names a non-empty folder with no Claude Code files (%s): the stack's "
                    "files go in beside what is there" % path)
    ask = []
    if decision == "ask":
        ask = ["About to install the stack into a folder that is not the plain default:",
               "  target: %s  (from %s)" % (path, how)]
        ask += ["  why you are asked: " + r for r in reasons]
        ask += ["  this run writes agents/, skills/, rules/, hooks/, bin/, mcp/, settings.json, stack.env "
                "and .stack-manifest.json there (files it replaces or removes go to a backup first),",
                "  registers MCP servers in %s through `claude mcp` and enables plugins for that folder%s."
                % (claude_json, "; ~/.claude is not touched" if not is_default else "")]
    return {"path": path, "real": real, "source": source, "export": export, "claude_json": claude_json,
            "kind": kind, "decision": decision, "reasons": reasons, "banner": banner, "warn": warn,
            "ask": ask, "nondefault": nondefault, "is_default": is_default}


def ask_yes_no(question, inp=None, out=None):
    """Print `question`, read one line; True only for y/Y/yes (the default is No, EOF is No)."""
    inp, out = inp or sys.stdin, out or sys.stdout
    out.write(question)
    out.flush()
    ans = inp.readline()
    return ans.strip() in ("y", "Y", "yes", "Yes", "YES")


def _cwd():
    """The shell's logical working directory when $PWD names it, else the physical one."""
    pwd, cwd = os.environ.get("PWD", ""), os.getcwd()
    try:
        if pwd and os.path.isabs(pwd) and os.path.samefile(pwd, cwd):
            return pwd
    except OSError:
        pass
    return cwd


def main(argv):
    cmd = argv[1] if len(argv) > 1 else ""
    a = argv[2:]
    if cmd == "config-dir":
        # config-dir <flag-set 0|1> <flag> <interactive 0|1> <quiet 0|1> <yes 0|1> <no-prompt 0|1> [repo...]
        # reads HOME, CLAUDE_CONFIG_DIR, STACK_CLAUDE_JSON, XDG_STATE_HOME, SHELL, PWD; prints key<TAB>value
        env = os.environ
        home = env.get("HOME") or os.path.expanduser("~")
        try:
            r = resolve_config_dir(a[1], a[0] == "1", env.get("CLAUDE_CONFIG_DIR", ""), home, _cwd(),
                                   repos=a[6:], state_root=env.get("XDG_STATE_HOME") or
                                   os.path.join(home, ".local", "state"),
                                   stack_claude_json=env.get("STACK_CLAUDE_JSON", ""),
                                   shell=env.get("SHELL", ""), interactive=a[2] == "1", quiet=a[3] == "1",
                                   yes=a[4] == "1", no_prompt=a[5] == "1")
        except ConfigDirError as e:
            sys.stderr.write("install.sh: %s. Nothing was changed.\n" % e)
            return 2
        def emit(k, v):
            # one value per line whatever the environment held (a newline in CLAUDE_CONFIG_DIR or
            # STACK_CLAUDE_JSON must not forge a second "path" line)
            print("%s\t%s" % (k, re.sub(r"[\x00-\x1f\x7f]", lambda m: "\\x%02x" % ord(m.group()), str(v))))
        for k in ("path", "real", "source", "export", "claude_json", "kind", "decision"):
            emit(k, r[k])
        emit("nondefault", "%d" % r["nondefault"])
        for k in ("banner", "warn", "ask"):
            for line in r[k]:
                emit(k, line)
        return 0
    if cmd == "ask":
        return 0 if ask_yes_no(a[0]) else 1
    if cmd == "stage":
        stage(a[0], a[1], a[2] if len(a) > 2 else None)
    elif cmd == "plan":
        c, s = a[0], a[1]
        if len(a) > 4:
            moved = drifted(c, load_json(a[4], {}))
            if moved:
                sys.stderr.write("install.sh: %s changed while the installer ran — nothing was "
                                 "changed; run it again\n" % ", ".join(moved[:5]))
                return 1
        plan = make_plan(c, s, a[2])
        write_json(a[3], plan)
        print_plan(plan)
        bad = unsafe_paths(c, plan)             # the check apply makes: --dry-run says it too
        if bad:
            sys.stderr.write("install.sh: refusing paths outside the config dir: %s — nothing was "
                             "changed\n" % ", ".join(map(repr, bad[:5])))
            return 1
    elif cmd == "apply":
        c, s, plan_path, root, commit, out = a[:6]
        snap = load_json(a[6], None) if len(a) > 6 else None
        bdir = apply_plan(c, s, load_json(plan_path, None), root, commit, snap=snap)
        with open(out, "w") as f:
            f.write(bdir)
    elif cmd == "restore":
        c, which, root, work, commit, home = a[:6]
        dry, force = "--dry-run" in a[6:], "--force" in a[6:]
        bdir, undo, meta = restore(c, which, root, work, commit, home, dry, force)
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
    elif cmd == "linked":
        for d, target in sorted(linked_dirs(a[0]).items()):
            print("%s\t%s" % (d, target))
    elif cmd == "private-root":
        print("created" if ensure_root(a[0]) else "exists")
    elif cmd == "latest":
        found = backups_of(a[0], a[1])
        print(found[-1] if found else "")
    else:
        sys.stderr.write(__doc__)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
