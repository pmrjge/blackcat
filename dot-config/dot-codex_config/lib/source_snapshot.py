"""Private source snapshot for codex_config/install.sh (DESIGN.md §7.2; port of install.sh's block).

Stdlib only, Python >= 3.11. Security-relevant (CWE-829, CWE-345, CWE-367): keep it small.

  source_snapshot.py <repo> <dest> [--allow-dirty]

Copies, ONCE, the files HEAD tracks under SNAPSHOT_PATHS from the working tree into <dest> (created
0700; it must not exist and must lie outside the repository) and prints the commit SHA. Every later
step of the run reads and executes that copy, never the repository, so an edit made in the repo
after this point (lib/install_state.py, the guard, a skill) is never run or installed.

What it checks, as install.sh does:
- every file is opened without following a link on any path component (O_NOFOLLOW per component,
  from an O_DIRECTORY fd of the repo) and must be a regular file; HEAD entries must be modes
  100644/100755 (no symlinks, no submodules); any symlink under dot-claude/ or codex_config/,
  tracked or not, stops the run;
- the bytes read are hashed as git blobs and compared with HEAD's object ids (not with git's
  index, whose stat cache and flags an agent can write); a file the index marks assume-unchanged or
  skip-worktree stops the run; git fsck re-hashes the objects, and fsck.* keys in the repo's own
  config (which could tell fsck to look away) stop the run;
- git runs with hooks, fsmonitor, the untracked cache, the commit graph, replace refs, sparse
  checkout and your global excludes file off, no GIT_* variable from the environment, no prompt;
- HEAD is resolved once to a SHA, and that SHA (not HEAD) is listed, so a commit made meanwhile
  cannot change what is compared.
Differences from HEAD (" M" edited, " D" deleted) stop the run (exit 1, the snapshot removed) unless
--allow-dirty, which copies the edited bytes as install.sh does and lists them on stderr. Files not
in HEAD (staged only, untracked) are never copied; they are listed on stderr ("A ", "??").

changes_since(repo, prev_commit, commit) gives the `git diff --stat` of SNAPSHOT_PATHS from an earlier
install's commit to the SNAPSHOT's commit (the SHA this module printed, never HEAD: a commit made
after the snapshot is not what the run installs), for the installer's supply review.

Seeded-bug proofs (tests/mutations/source_snapshot.json; each turns tests/test_source_snapshot.py
red): link the snapshot files to the repository instead of copying the bytes read; follow a link on
the last path component; drop the assume-unchanged/skip-worktree check; never compare the bytes
read with HEAD's blob; skip the fsck config check; keep GIT_* variables from the environment.
"""
from __future__ import annotations

import errno
import hashlib
import os
import re
import shutil
import stat
import subprocess
import sys

SNAPSHOT_PATHS = ("codex_config", "lib/install_state.py", "lib/claude_md_block.py", "lib/stack.env.example",
                  "dot-claude")
NO_LINKS = ("dot-claude", "codex_config")
_SHA = re.compile(r"[0-9a-f]{7,64}\Z")


class SnapshotError(Exception):
    """The snapshot cannot vouch for the files: nothing is installed."""


def _git_cmd(repo):
    return ["git", "--no-replace-objects", "-c", "core.hooksPath=/dev/null", "-c", "core.fsmonitor=false",
            "-c", "core.untrackedCache=false", "-c", "core.excludesFile=/dev/null",
            "-c", "core.sparseCheckout=false", "-c", "core.commitGraph=false", "-c", "core.quotePath=true",
            "-C", repo]


def _env():
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update(GIT_TERMINAL_PROMPT="0", GIT_OPTIONAL_LOCKS="0")
    return env


def _git(repo, *args, check=True):
    p = subprocess.run(_git_cmd(repo) + list(args), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                       stderr=subprocess.PIPE, env=_env())
    if check and p.returncode:
        raise SnapshotError("git %s failed in %s: %s"
                            % (args[0], repo, p.stderr.decode("utf-8", "replace").strip()[:300]))
    return p


def _paths(blob):
    return [os.fsdecode(x) for x in blob.split(b"\0") if x]


def show(p):
    """A name with control characters (a terminal escape could hide its line) is quoted."""
    return p if p.isprintable() else ascii(p)


def _under(p, roots):
    return any(p == r or p.startswith(r + "/") for r in roots)


def open_nofollow(repo, rel):
    """An fd on repo/rel, following no link on any component (a swapped-in link is refused)."""
    d = os.open(repo, os.O_RDONLY | os.O_DIRECTORY)
    try:
        parts = rel.split("/")
        for part in parts[:-1]:
            n = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=d)
            os.close(d)
            d = n
        return os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=d)
    finally:
        os.close(d)


def _check_repo(repo):
    links = sorted(os.path.relpath(os.path.join(r, n), repo)
                   for top in NO_LINKS for r, ds, fs in os.walk(os.path.join(repo, top))
                   for n in ds + fs if os.path.islink(os.path.join(r, n)))
    if links:
        raise SnapshotError("%s is a symlink; the stack ships none — remove it" % ", ".join(map(show, links[:5])))
    index = [(e[0], e[2:]) for e in _paths(_git(repo, "ls-files", "-v", "-z", "--", *SNAPSHOT_PATHS).stdout)]
    hidden = sorted(p for t, p in index if t.islower() or t == "S")
    if hidden:
        raise SnapshotError("git's index marks %s assume-unchanged or skip-worktree, which hides edits from "
                            "the review: clear the marks (git -C '%s' update-index --no-assume-unchanged "
                            "--no-skip-worktree -- <file>...)" % (", ".join(map(show, hidden[:10])), repo))
    cfg = _git(repo, "config", "--show-scope", "--get-regexp", r"^fsck\.", check=False).stdout
    keys = [ln.split()[1] for ln in cfg.decode("utf-8", "replace").splitlines()
            if len(ln.split()) > 1 and ln.split()[0] in ("local", "worktree")]
    if keys:
        raise SnapshotError("the repo's git config sets %s, which tells git fsck what to skip: remove it"
                            % ", ".join(map(show, keys[:5])))
    fsck = _git(repo, "fsck", "--no-dangling", "--no-reflogs", "--no-progress", check=False)
    if fsck.returncode:
        raise SnapshotError("git fsck finds a damaged or altered object, so HEAD cannot vouch for the files: %s"
                            % show((fsck.stderr or fsck.stdout).decode("utf-8", "replace").strip()[:200]))
    return index


def _copy(dest, rel, data, exe):
    dst = os.path.join(dest, rel)
    os.makedirs(os.path.dirname(dst), mode=0o700, exist_ok=True)
    wfd = os.open(dst, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o755 if exe else 0o644)
    with os.fdopen(wfd, "wb") as f:
        f.write(data)


def snapshot(repo, dest, allow_dirty=False):
    """(commit SHA, review lines). SnapshotError: nothing usable is left at dest."""
    repo, dest = os.path.abspath(repo), os.path.abspath(dest)
    rr = os.path.realpath(repo)
    if _under(os.path.realpath(os.path.dirname(dest)), [rr]):
        raise SnapshotError("the snapshot %s must lie outside the repository %s" % (dest, repo))
    index = _check_repo(repo)
    commit = _git(repo, "rev-parse", "--verify", "HEAD^{commit}").stdout.decode().strip()
    if not _SHA.match(commit):
        raise SnapshotError("HEAD of %s is not a commit" % repo)
    fmt = _git(repo, "rev-parse", "--show-object-format").stdout.decode().strip()
    fmt = fmt if fmt in ("sha1", "sha256") else "sha1"
    tree = {}
    for ent in _git(repo, "ls-tree", "-r", "-z", "--full-tree", commit).stdout.split(b"\0"):
        meta, _, p = ent.partition(b"\t")
        p = os.fsdecode(p)
        if meta and _under(p, SNAPSHOT_PATHS):
            tree[p] = meta.decode().split()
    os.mkdir(dest, 0o700)
    review = []
    try:
        for rel in sorted(tree):
            mode, _kind, oid = tree[rel]
            if mode == "120000":
                raise SnapshotError("%s is a symlink; the stack ships none" % show(rel))
            if mode not in ("100644", "100755"):
                raise SnapshotError("%s is not a regular file in HEAD (mode %s)" % (show(rel), mode))
            try:
                fd = open_nofollow(repo, rel)
            except OSError as e:
                if e.errno == errno.ENOENT:
                    review.append(" D " + show(rel))
                    continue
                if e.errno == errno.ELOOP:
                    raise SnapshotError("%s is a symlink; the stack ships none" % show(rel)) from None
                raise SnapshotError("%s cannot be read as a regular file (%s)" % (show(rel), e.strerror)) from None
            with os.fdopen(fd, "rb") as f:
                st = os.fstat(f.fileno())
                if not stat.S_ISREG(st.st_mode):
                    raise SnapshotError("%s is not a regular file" % show(rel))
                data = f.read()
            h = hashlib.new(fmt)
            h.update(b"blob %d\0" % len(data))
            h.update(data)
            exe = bool(st.st_mode & 0o100)
            if h.hexdigest() != oid or exe != (mode == "100755"):
                review.append(" M " + show(rel))
            _copy(dest, rel, data, exe)
        dirty = [r for r in review if r.startswith((" M ", " D "))]
        if dirty and not allow_dirty:
            raise SnapshotError("uncommitted changes in files the Codex installer ships or runs (commit them, or "
                                "pass --allow-dirty to install them as they are):\n%s"
                                % "\n".join("    " + r for r in dirty[:40]))
    except BaseException:
        shutil.rmtree(dest, ignore_errors=True)
        raise
    review += ["A  %s  (staged, not committed: not installed)" % show(p) for _t, p in sorted(index) if p not in tree]
    review += ["?? %s  (untracked: not installed)" % show(p) for p in sorted(_paths(
        _git(repo, "ls-files", "-z", "--others", "--exclude-standard", "--", *SNAPSHOT_PATHS).stdout))]
    return commit, review


def changes_since(repo, prev_commit, commit):
    """`git diff --stat` of SNAPSHOT_PATHS from prev_commit to `commit` (the snapshot's SHA, not HEAD;
    "" when none); None when either is not a SHA this repo has (review everything then)."""
    if not all(isinstance(c, str) and _SHA.match(c) for c in (prev_commit, commit)):
        return None
    p = _git(os.path.abspath(repo), "diff", "--no-ext-diff", "--no-textconv", "--stat", prev_commit, commit,
             "--", *SNAPSHOT_PATHS, check=False)
    return p.stdout.decode("utf-8", "replace") if p.returncode == 0 else None


def main(argv):
    a = argv[1:]
    allow = "--allow-dirty" in a
    a = [x for x in a if x != "--allow-dirty"]
    if len(a) != 2:
        sys.stderr.write("usage: source_snapshot.py <repo> <dest> [--allow-dirty]\n")
        return 2
    try:
        commit, review = snapshot(a[0], a[1], allow)
    except (SnapshotError, OSError) as exc:
        sys.stderr.write("codex_config/install.sh: source snapshot: %s — nothing was installed\n" % exc)
        return 1
    for line in review:
        sys.stderr.write("note: %s\n" % line)
    print(commit)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
