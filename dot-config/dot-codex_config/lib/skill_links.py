"""The $HOME/.agents/skills symlink manager (DESIGN.md §3, §7.3 steps 8 and restore, §8.3 "Links").

Stdlib only, Python >= 3.11. Codex lists user skills from $HOME/.agents/skills (F5); the stack's
skill files live in <codex_home>/stack/skills/<skill>, and this module keeps one symlink per listed
skill in the root. The root is shared with you and other tools, so:

- An entry is the stack's only when it is a symlink whose target is exactly the one the last
  install's manifest records for that name, and that target is <...>/stack/skills/<name>. A link that
  already points exactly at the new target is kept as it is.
- Any other entry under a name the stack would write (a folder, a file, a link elsewhere, a link
  the old manifest does not record) is foreign: the run stops naming it, and nothing is changed.
- A foreign entry under a name the stack only stops shipping is left alone (noted). Entries under
  other names are never looked at. Nothing foreign is ever overwritten or removed.
- The root itself must be a real directory of this user (not a symlink); every operation is
  relative to an O_NOFOLLOW directory descriptor of it, and no link is ever followed.
- apply writes <backup-dir>/skill-links.json (0600, O_EXCL) BEFORE changing anything: per entry its
  state before and after. Each entry is re-checked right before it is changed. restore undoes an
  entry only when it is still in its recorded "after" state; an entry back in its "before" state
  is skipped, anything else is named and left alone (exit 1).

  skill_links.py plan    <links.json> <old-manifest|->
  skill_links.py apply   <links.json> <old-manifest|-> <backup-dir>
  skill_links.py restore <backup-dir>

links.json: {"root": "<abs>|null", "links": {"<skill>": "<abs target>"}} (INTERFACES §6). The old
manifest's "links" is that same object (codex_state.py manifest) or a plain {skill: target} map.
Exit codes: 0 ok, 1 a foreign entry or another problem (stderr), 2 usage.

Seeded-bug proofs (tests/mutations/skill_links.json; each turns tests/test_skill_links.py red):
treat any link into stack/skills as the stack's without the old manifest; prune a foreign entry
under a name no longer shipped; restore without checking the entry's current state; open the root
following a symlink; write the record after the changes.
"""
from __future__ import annotations

import json
import os
import re
import stat
import sys

RECORD = "skill-links.json"
USAGE = ("usage: skill_links.py plan <links.json> <old-manifest|->\n"
         "       skill_links.py apply <links.json> <old-manifest|-> <backup-dir>\n"
         "       skill_links.py restore <backup-dir>\n")
FORMAT = 1
NAME_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*\Z")
MISSING = {"type": "missing"}


class LinkError(Exception):
    """A problem the user must fix; nothing was changed unless the message says otherwise."""


def _link(target):
    return {"type": "link", "target": target}


def _valid_name(name):
    return isinstance(name, str) and bool(NAME_RE.match(name)) and name not in (".", "..")


def stack_target(name, target):
    """True for an absolute, normalised <...>/stack/skills/<name>."""
    if not isinstance(target, str) or not os.path.isabs(target) or "\x00" in target:
        return False
    if os.path.normpath(target) != target:
        return False
    parent = os.path.dirname(target)
    return (os.path.basename(target) == name and os.path.basename(parent) == "skills"
            and os.path.basename(os.path.dirname(parent)) == "stack")


def _read_json(path):
    """A JSON file read without following a link at its last component."""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    except OSError as exc:
        raise LinkError("cannot read %s: %s" % (path, exc.strerror)) from None
    with os.fdopen(fd, "rb") as f:
        try:
            return json.loads(f.read().decode("utf-8"))
        except ValueError as exc:
            raise LinkError("%s is not valid JSON: %s" % (path, exc)) from None


def _links_obj(obj, what, default_root=None):
    """(root or None, {name: target}) from a links.json object (or a plain map, root = default_root)."""
    if isinstance(obj, dict) and "links" in obj and ("root" in obj):
        root, links = obj["root"], obj["links"]
    elif isinstance(obj, dict) and all(isinstance(v, str) for v in obj.values()):
        root, links = default_root, obj
    else:
        raise LinkError("%s: links must be {\"root\": ..., \"links\": {...}}" % what)
    if root is not None and not (isinstance(root, str) and os.path.isabs(root)
                                 and os.path.normpath(root) == root and "\x00" not in root):
        raise LinkError("%s: root %r is not an absolute, normalised path" % (what, root))
    if not isinstance(links, dict):
        raise LinkError("%s: links is not an object" % what)
    for name, target in links.items():
        if not _valid_name(name):
            raise LinkError("%s: %r is not a skill name" % (what, name))
        if not stack_target(name, target):
            raise LinkError("%s: %s -> %r is not a link into a stack/skills folder" % (what, name, target))
    return root, dict(links)


def load_new(path):
    root, links = _links_obj(_read_json(path), path)
    if len({os.path.dirname(t) for t in links.values()}) > 1:
        raise LinkError("%s: the link targets are in more than one stack/skills folder" % path)
    return root, links


def load_old(path, new_root):
    if path == "-":
        return None, {}
    m = _read_json(path)
    if not isinstance(m, dict) or m.get("links") is None:
        return None, {}
    return _links_obj(m["links"], path + " (links)", default_root=new_root)


# ---- the root: one O_NOFOLLOW directory descriptor -------------------------------------------------
def open_root(root, create=False):
    """An fd on root, which must be a directory of this user and not a symlink (created 0755 with its
    parents when missing and create is set); None when it is missing and create is not set."""
    if create and not os.path.lexists(root):
        os.makedirs(os.path.dirname(root), exist_ok=True)
        try:
            os.mkdir(root, 0o755)
        except FileExistsError:
            pass
    try:
        fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    except FileNotFoundError:
        return None
    except OSError:
        raise LinkError("%s is a symlink or not a directory: the stack writes its skill links only into a "
                        "real folder (move it away, or use --skills-root)" % root) from None
    st = os.fstat(fd)
    if st.st_uid != os.getuid():
        os.close(fd)
        raise LinkError("%s is not a folder of yours" % root)
    return fd


def state(fd, name):
    """{"type": "missing"} | {"type": "link", "target"} | {"type": "other"}; never follows a link."""
    if fd is None:
        return dict(MISSING)
    try:
        st = os.stat(name, dir_fd=fd, follow_symlinks=False)
    except FileNotFoundError:
        return dict(MISSING)
    if stat.S_ISLNK(st.st_mode):
        return _link(os.readlink(name, dir_fd=fd))
    return {"type": "other"}


# ---- plan -----------------------------------------------------------------------------------------
def make_plan(new_root, new_links, old_root, old_links):
    """{"ops": [{"op", "root", "name", "before", "after"}], "keep": [names], "foreign": [paths],
    "notes": [lines]}. Opens (never creates) the roots it reads."""
    ops, keep, foreign, notes = [], [], [], []
    fds = {}

    def fd_of(root):
        if root not in fds:
            fds[root] = open_root(root)
        return fds[root]

    try:
        same_root = old_root is not None and new_root is not None and (
            os.path.realpath(old_root) == os.path.realpath(new_root))

        def ours(cur, name):
            return (cur["type"] == "link" and name in old_links and cur["target"] == old_links[name]
                    and stack_target(name, cur["target"]))

        if new_root is not None:
            fd = fd_of(new_root)
            for name in sorted(new_links):
                want = _link(new_links[name])
                cur = state(fd, name)
                if cur == want:
                    keep.append(name)
                elif cur["type"] == "missing":
                    ops.append({"op": "add", "root": new_root, "name": name, "before": cur, "after": want})
                elif same_root and ours(cur, name):
                    ops.append({"op": "update", "root": new_root, "name": name, "before": cur, "after": want})
                else:
                    foreign.append(os.path.join(new_root, name))
        if old_root is not None:
            fd = fd_of(old_root)
            for name in sorted(old_links):
                if same_root and name in new_links:
                    continue
                cur = state(fd, name)
                if cur["type"] == "missing":
                    continue
                if ours(cur, name):
                    ops.append({"op": "remove", "root": old_root, "name": name, "before": cur, "after": dict(MISSING)})
                else:
                    notes.append("%s: kept (no longer the stack's link: yours now)" % os.path.join(old_root, name))
    finally:
        for fd in fds.values():
            if fd is not None:
                os.close(fd)
    return {"ops": ops, "keep": keep, "foreign": foreign, "notes": notes}


def foreign_error(paths):
    return LinkError("%s: not the stack's (not a link the last install made into stack/skills) — move or "
                     "rename %s, then run the installer again. Nothing was changed."
                     % (", ".join(paths[:10]), "it" if len(paths) == 1 else "them"))


def print_plan(p, out=sys.stdout):
    sym = {"add": "+", "update": "~", "remove": "-"}
    for op in p["ops"]:
        line = "  %s %s" % (sym[op["op"]], os.path.join(op["root"], op["name"]))
        if op["op"] != "remove":
            line += " -> " + op["after"]["target"]
        out.write(line + "\n")
    if p["keep"]:
        out.write("  = %d skill link(s) unchanged\n" % len(p["keep"]))
    for n in p["notes"]:
        out.write("  note: %s\n" % n)


# ---- apply, restore -------------------------------------------------------------------------------
def _open_backup(bdir):
    try:
        fd = os.open(bdir, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    except OSError:
        raise LinkError("%s is not a backup folder (missing, a symlink or not a directory)" % bdir) from None
    st = os.fstat(fd)
    if st.st_uid != os.getuid():
        os.close(fd)
        raise LinkError("%s is not a folder of yours" % bdir)
    return fd


def _write_record(bdir, record):
    bfd = _open_backup(bdir)
    try:
        try:
            fd = os.open(RECORD, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=bfd)
        except FileExistsError:
            raise LinkError("%s already holds %s: use a new backup folder" % (bdir, RECORD)) from None
        with os.fdopen(fd, "w") as f:
            json.dump(record, f, indent=2, sort_keys=True)
            f.flush()
            os.fsync(f.fileno())
    finally:
        os.close(bfd)


def _put(fd, name, target, replace):
    """name -> target in the directory fd: a new link, or an atomic swap of the existing link."""
    if not replace:
        os.symlink(target, name, dir_fd=fd)
        return
    tmp = ".%s.skill-link-%d" % (name, os.getpid())
    os.symlink(target, tmp, dir_fd=fd)
    try:
        os.replace(tmp, name, src_dir_fd=fd, dst_dir_fd=fd)
    except OSError:
        os.unlink(tmp, dir_fd=fd)
        raise


def _change(fd, name, before, after):
    if after["type"] == "missing":
        os.unlink(name, dir_fd=fd)
    else:
        _put(fd, name, after["target"], replace=before["type"] == "link")


def apply(links_path, old_manifest, bdir, out=sys.stdout):
    new_root, new_links = load_new(links_path)
    old_root, old_links = load_old(old_manifest, new_root)
    p = make_plan(new_root, new_links, old_root, old_links)
    if p["foreign"]:
        raise foreign_error(p["foreign"])
    entries = [{"root": op["root"], "name": op["name"], "before": op["before"], "after": op["after"]}
               for op in p["ops"]]
    _write_record(bdir, {"format": FORMAT, "entries": entries})
    print_plan(p, out)
    if new_root is not None and any(e["root"] == new_root for e in entries):
        fd = open_root(new_root, create=True)          # a missing root is created (0755), never a link
        os.close(fd)
    for e in entries:
        fd = open_root(e["root"])
        try:
            if fd is None or state(fd, e["name"]) != e["before"]:
                raise LinkError("%s changed while the installer ran: stopped (the links changed so far are "
                                "in %s; restore undoes them)" % (os.path.join(e["root"], e["name"]),
                                                                  os.path.join(bdir, RECORD)))
            _change(fd, e["name"], e["before"], e["after"])
        finally:
            if fd is not None:
                os.close(fd)
    return entries


def _valid_state(s, name):
    if s == MISSING:
        return True
    return (isinstance(s, dict) and s.get("type") == "link" and set(s) == {"type", "target"}
            and stack_target(name, s["target"]))


def restore(bdir, out=sys.stdout):
    """Undo what apply recorded in bdir. Returns the entries left alone (empty: all undone)."""
    bfd = _open_backup(bdir)
    os.close(bfd)
    rec = _read_json(os.path.join(bdir, RECORD))
    if not isinstance(rec, dict) or rec.get("format") != FORMAT or not isinstance(rec.get("entries"), list):
        raise LinkError("%s is not a skill-link record of this installer" % os.path.join(bdir, RECORD))
    left = []
    for e in reversed(rec["entries"]):
        ok = (isinstance(e, dict) and isinstance(e.get("root"), str) and os.path.isabs(e["root"])
              and _valid_name(e.get("name")) and _valid_state(e.get("before"), e.get("name"))
              and _valid_state(e.get("after"), e.get("name")))
        if not ok:
            left.append("%r: not a valid record entry" % (e,))
            continue
        path = os.path.join(e["root"], e["name"])
        fd = open_root(e["root"])
        try:
            cur = state(fd, e["name"])
            if cur == e["before"]:
                continue
            if cur != e["after"] or fd is None:
                left.append("%s: changed since the install; left as it is" % path)
                continue
            _change(fd, e["name"], e["after"], e["before"])
            out.write("  restored %s\n" % path)
        finally:
            if fd is not None:
                os.close(fd)
    return left


def main(argv):
    cmd, a = (argv[1] if len(argv) > 1 else ""), argv[2:]
    need = {"plan": 2, "apply": 3, "restore": 1}
    if cmd not in need or len(a) != need[cmd]:
        sys.stderr.write(USAGE)
        return 2
    try:
        if cmd == "plan":
            new_root, new_links = load_new(a[0])
            old_root, old_links = load_old(a[1], new_root)
            p = make_plan(new_root, new_links, old_root, old_links)
            if p["foreign"]:
                raise foreign_error(p["foreign"])
            print_plan(p)
        elif cmd == "apply":
            apply(a[0], a[1], a[2])
        else:
            left = restore(a[0])
            for line in left:
                sys.stderr.write("skill_links: %s\n" % line)
            return 1 if left else 0
    except (LinkError, OSError) as exc:
        sys.stderr.write("skill_links: %s\n" % exc)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
