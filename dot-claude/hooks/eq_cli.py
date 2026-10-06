"""eq_cli - the runtime Equilibrium's executor (bin/stack-eq) and Level 1 check runner (bin/stack-eq-check).

  stack-eq help
  stack-eq plan --run R              validate the problem, resolve the parameters, render the member briefs,
                                     make the work dirs, print the estimate and the consent token
  stack-eq start --run R             the consent record (when the plan needs one), then the member tokens
  stack-eq start --run R --headless --consent-file /abs/consent.json      (a terminal, CLAUDECODE unset)
  stack-eq prepare-check --run R --round r     one check copy per candidate (harness overlay rules)
  stack-eq check-container --run R --round r   Level 2: every check in a container + the default-deny WALL
  stack-eq reduce --run R --round r  the reducer, kappa, the LOO jackknife, the mediator ledger
  stack-eq view --run R --round r    the members' LOO views for reconcile round r >= 1
  stack-eq result --run R            the hand-back block, selected.patch and cand-<i>.patch
  stack-eq cleanup --run R           remove the run's member worktrees/branches (a Remove consent record)
  stack-eq status --run R
  stack-eq-check --run R --cand i    (sandboxed) run the plan's check in checks/c<i>/; one EQCHECK line

Two entry points, chosen by the launcher's first argument and nothing else: `--eq-executor` (bin/stack-eq:
runs OUTSIDE the Bash sandbox, so every call needs the guard's one-use ticket for its exact argv; it never
executes candidate or member text nor any eq-check argv) and `--eq-check-runner` (bin/stack-eq-check:
sandboxed, runs exactly the plan's check argv in a prepared copy with a minimal environment).

Rules, state layout and grammar: hooks/eq_policy.py; the reducer, views and briefs: hooks/eq_core.py;
Level 2: hooks/eq_isolation.py. All three load from beside this file only (never an environment override).
Every write under <project>/.claude-work/eq/ and the store is openat + O_NOFOLLOW per component; a
symlinked ancestor is refused. Exit: 0 done, 2 usage, 3 needs the user (consent), 4 refused, 5 failed.
Python 3.13, stdlib only.
"""
import sys

sys.dont_write_bytecode = True        # modules load from <config>/hooks: no __pycache__ beside them
import contextlib  # noqa: E402
import fcntl  # noqa: E402
import hashlib  # noqa: E402
import importlib.util  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import re  # noqa: E402
import secrets  # noqa: E402
import shutil  # noqa: E402
import signal  # noqa: E402
import stat  # noqa: E402
import subprocess  # noqa: E402
import tempfile  # noqa: E402
import threading  # noqa: E402
import time  # noqa: E402

HERE = os.path.dirname(os.path.realpath(__file__))           # <config>/hooks
CONFIG = os.path.dirname(HERE)                                # <config>
EXIT_OK, EXIT_USAGE, EXIT_ASK, EXIT_REFUSED, EXIT_FAILED = 0, 2, 3, 4, 5
GIT_TIMEOUT_S = 120
MAX_FILE = 64 << 20
OWNED_PATHS = {"CP": ("tests",), "CR": ("tests",)}            # flags.json check_owned_paths
SYSTEM_DIRS = ("/opt/homebrew/bin", "/usr/local/bin", "/usr/bin", "/bin", "/usr/sbin", "/sbin")
GIT_CANDIDATES = ("/usr/bin/git", "/opt/homebrew/bin/git", "/usr/local/bin/git")
# repository configuration that makes diff/status/add run a program: refused before any git call (hooks
# and fsmonitor are switched off per call with -c; textconv and external diff by flags)
GIT_DANGER_RE = re.compile(r"(?:filter\..+\.(?:clean|smudge|process)|diff\.external|diff\..+\.command|"
                           r"core\.fsmonitor|core\.hookspath|include(?:if\..*)?\.path)\Z")
GIT_SAFE_CONFIG = ("-c", "core.hooksPath=/dev/null", "-c", "core.fsmonitor=false", "-c", "core.quotePath=true",
                   "-c", "diff.noprefix=false", "-c", "diff.mnemonicPrefix=false", "-c", "diff.relative=false",
                   "-c", "color.ui=never", "-c", "core.untrackedCache=false")


def _load(name):
    spec = importlib.util.spec_from_file_location(name, os.path.join(HERE, name + ".py"))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


try:
    P = _load("eq_policy")
except Exception as _exc:  # noqa: BLE001 - nothing runs without the rules
    sys.stderr.write("stack-eq: cannot load %s/eq_policy.py (%s: %s); nothing done\n"
                     % (HERE, type(_exc).__name__, _exc))
    sys.exit(EXIT_REFUSED)


class Refused(Exception):
    def __init__(self, code, msg):
        Exception.__init__(self, msg)
        self.code = code


_MODS = {}


def core():
    """hooks/eq_core.py (the reducer/view/brief port), loaded once; Refused when absent or broken."""
    if "core" not in _MODS:
        path = os.path.join(HERE, "eq_core.py")
        if not os.path.isfile(path):
            raise Refused(EXIT_FAILED, "hooks/eq_core.py is not installed: the reducer is missing")
        try:
            _MODS["core"] = _load("eq_core")
        except Exception as exc:  # noqa: BLE001
            raise Refused(EXIT_FAILED, "hooks/eq_core.py failed to load (%s: %s)" % (type(exc).__name__, exc))
    return _MODS["core"]


def isolation():
    if "iso" not in _MODS:
        _MODS["iso"] = _load("eq_isolation")
    return _MODS["iso"]


def call_core(fn, *args, **kw):
    """One eq_core API call; a signature mismatch is a failure named as such (contract 8)."""
    f = getattr(core(), fn, None)
    if not callable(f):
        raise Refused(EXIT_FAILED, "eq_core.%s is missing (contracts.md 8)" % fn)
    try:
        return f(*args, **kw)
    except TypeError as exc:
        raise Refused(EXIT_FAILED, "eq_core.%s: API mismatch with contracts.md 8 (%s)" % (fn, exc))
    except ValueError as exc:
        raise Refused(EXIT_FAILED, "eq_core.%s refused its input (%s)" % (fn, exc))


def seed_of(tag, *parts):
    """derive_seed(seed_for(tag), *parts): the harness's seed shape (COMPARE_eq 8.4)."""
    return int(call_core("derive_seed", int(call_core("seed_for", tag)), *parts))


def out(line=""):
    sys.stdout.write(line + "\n")


def now():
    return time.time()


def iso_utc(ts=None):
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now() if ts is None else ts))


def sha256_bytes(b):
    return hashlib.sha256(b).hexdigest()


def canon(obj):
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


# ---------------------------------------------------------------- openat file system (no symlink anywhere)
class Tree:
    """A directory tree reached only through openat with O_NOFOLLOW per component below `root` (a real
    path): a symlinked ancestor, a non-directory where a directory is expected, or another owner refuses."""

    def __init__(self, root):
        self.root = os.path.realpath(root)
        try:
            self.fd = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
        except OSError as exc:
            raise Refused(EXIT_REFUSED, "%s unusable (%s)" % (self.root, exc.strerror))

    def close(self):
        with contextlib.suppress(OSError):
            os.close(self.fd)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def _step(self, dfd, name, create, mode, where):
        if name in ("", ".", "..") or "/" in name or "\0" in name:
            raise Refused(EXIT_REFUSED, "bad path component %r under %s" % (name, self.root))
        try:
            st = os.stat(name, dir_fd=dfd, follow_symlinks=False)
        except FileNotFoundError:
            if not create:
                raise
            try:
                os.mkdir(name, mode, dir_fd=dfd)
            except FileExistsError:
                pass
            st = os.stat(name, dir_fd=dfd, follow_symlinks=False)
        if stat.S_ISLNK(st.st_mode):
            raise Refused(EXIT_REFUSED, "%s/%s is a symlink: refused (nothing is written or read through a link)"
                          % (where, name))
        if not stat.S_ISDIR(st.st_mode):
            raise Refused(EXIT_REFUSED, "%s/%s is not a directory" % (where, name))
        if st.st_uid != os.getuid():
            raise Refused(EXIT_REFUSED, "%s/%s is not yours" % (where, name))
        return os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=dfd)

    def opendir(self, parts, create=False, mode=0o700):
        """fd of root/parts... (caller closes); FileNotFoundError when absent and not create."""
        fd = os.dup(self.fd)
        where = self.root
        try:
            for name in parts:
                nfd = self._step(fd, name, create, mode, where)
                os.close(fd)
                fd = nfd
                where = os.path.join(where, name)
            return fd
        except BaseException:
            os.close(fd)
            raise

    @contextlib.contextmanager
    def dir(self, parts, create=False, mode=0o700):
        fd = self.opendir(parts, create, mode)
        try:
            yield fd
        finally:
            os.close(fd)

    def write(self, parts, name, data, mode=0o600):
        """root/parts/name := data, atomically (temp O_EXCL|O_NOFOLLOW + renameat in the same dir)."""
        if isinstance(data, str):
            data = data.encode("utf-8")
        with self.dir(parts, create=True) as dfd:
            tmp = ".%s.%s.tmp" % (name, secrets.token_hex(4))
            fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, mode, dir_fd=dfd)
            try:
                with os.fdopen(fd, "wb") as f:
                    f.write(data)
                    f.flush()
                    os.fchmod(f.fileno(), mode)
                os.rename(tmp, name, src_dir_fd=dfd, dst_dir_fd=dfd)
            except BaseException:
                with contextlib.suppress(OSError):
                    os.unlink(tmp, dir_fd=dfd)
                raise

    def write_json(self, parts, name, obj):
        self.write(parts, name, json.dumps(obj, indent=1, sort_keys=True) + "\n")

    def read(self, rel, limit=MAX_FILE):
        """(bytes, mode) of the regular file root/rel reached without following any link; None if it is
        absent, a link, special or larger than limit."""
        parts = [p for p in rel.split("/") if p]
        if not parts or any(p in (".", "..") for p in parts):
            return None
        try:
            dfd = self.opendir(parts[:-1])
        except (OSError, Refused):
            return None
        try:
            fd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC, dir_fd=dfd)
        except OSError:
            return None
        finally:
            os.close(dfd)
        try:
            st = os.fstat(fd)
            if not stat.S_ISREG(st.st_mode) or st.st_size > limit:
                return None
            chunks, size = [], 0
            while True:
                b = os.read(fd, 1 << 20)
                if not b:
                    break
                chunks.append(b)
                size += len(b)
                if size > limit:
                    return None
            return b"".join(chunks), st.st_mode
        finally:
            os.close(fd)

    def read_json(self, rel, limit=16 << 20):
        got = self.read(rel, limit)
        if got is None:
            return None
        try:
            return json.loads(got[0].decode("utf-8"))
        except ValueError:
            return None

    def put_file(self, rel, data, mode):
        parts = [p for p in rel.split("/") if p]
        self.write(parts[:-1], parts[-1], data, mode)

    def rmtree(self, parts, name):
        """Remove root/parts/name (fd-relative; shutil.rmtree with dir_fd never follows a link)."""
        try:
            with self.dir(parts) as dfd:
                try:
                    st = os.stat(name, dir_fd=dfd, follow_symlinks=False)
                except FileNotFoundError:
                    return False
                if stat.S_ISLNK(st.st_mode):
                    raise Refused(EXIT_REFUSED, "%s is a symlink: refused (planted links are never followed or "
                                  "silently removed)" % os.path.join(self.root, *parts, name))
                if stat.S_ISDIR(st.st_mode):
                    shutil.rmtree(name, dir_fd=dfd)
                else:
                    os.unlink(name, dir_fd=dfd)
                return True
        except FileNotFoundError:
            return False

    def exists(self, parts):
        try:
            with self.dir(parts):
                return True
        except (FileNotFoundError, Refused):
            return False


# ---------------------------------------------------------------- the store and the ticket
def state_tree():
    root = P.state_root(os.environ)
    os.makedirs(root, mode=0o700, exist_ok=True)
    return Tree(root)


def store_parts(sid, run):
    return [P.safe_sid(sid), "eq", run]


def claim_ticket(args):
    """The guard's ticket for exactly this argv: claimed by rename, removed, within TICKET_TTL_S; None if
    there is none, it is stale, a link, or names another argv."""
    d = P.ticket_dir(os.environ)
    path = os.path.join(d, P.ticket_name(args))
    claimed = "%s.%s.claimed" % (path, secrets.token_hex(4))
    try:
        st = os.lstat(d)
        if not stat.S_ISDIR(st.st_mode) or st.st_uid != os.getuid():
            return None
        os.rename(path, claimed)
    except OSError:
        return None
    try:
        data = P.read_json(claimed, 1 << 20)
    finally:
        with contextlib.suppress(OSError):
            os.unlink(claimed)
    if not isinstance(data, dict) or data.get("argv") != list(args):
        return None
    try:
        age = now() - float(data.get("ts"))
    except (TypeError, ValueError):
        return None
    if not 0 <= age <= P.TICKET_TTL_S:
        return None
    if not isinstance(data.get("session"), str) or not data["session"] or not isinstance(data.get("run"), str) \
            or not P.RUN_RE.match(data["run"]):
        return None
    return data


class Run:
    """One run's store (S/<sid>/eq/<R>) and its project-side work area."""

    def __init__(self, sid, run):
        self.sid, self.run = sid, run
        self.st = state_tree()
        self.parts = store_parts(sid, run)
        if not self.st.exists(self.parts):
            raise Refused(EXIT_REFUSED, "run eq:%s has no store (the guard writes brief.json at the spawn)" % run)
        self._lock = None

    def lock(self):
        with self.st.dir(self.parts) as dfd:
            fd = os.open("eq.lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600, dir_fd=dfd)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            os.close(fd)
            raise Refused(EXIT_REFUSED, "another stack-eq call holds run eq:%s" % self.run)
        self._lock = fd

    def get(self, *rel):
        return self.st.read_json("/".join(self.parts + list(rel)))

    def raw(self, *rel):
        got = self.st.read("/".join(self.parts + list(rel)))
        return None if got is None else got[0]

    def put(self, *rel, obj=None, text=None):
        rel = list(rel)
        if text is not None:
            self.st.write(self.parts + rel[:-1], rel[-1], text)
        else:
            self.st.write_json(self.parts + rel[:-1], rel[-1], obj)

    def append_ledger(self, rec):
        line = json.dumps(dict(rec, ts=iso_utc()), sort_keys=True, separators=(",", ":")) + "\n"
        with self.st.dir(self.parts) as dfd:
            fd = os.open("mediator.jsonl", os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC,
                         0o600, dir_fd=dfd)
            with os.fdopen(fd, "a") as f:
                f.write(line)

    def state(self):
        return self.get("state.json") or {}

    def set_state(self, phase, rnd):
        self.put("state.json", obj={"phase": phase, "round": rnd, "updated": now()})

    def plan(self):
        p = self.get("plan.json")
        if not isinstance(p, dict) or p.get("schema") != P.SCHEMA_PLAN or p.get("run") != self.run:
            raise Refused(EXIT_REFUSED, "run eq:%s has no plan: run `stack-eq plan --run %s` first" % (self.run, self.run))
        return p

    def members(self):
        m = self.get("members.json")
        return m if isinstance(m, dict) else {}

    def capture(self, rnd, i):
        c = self.get("r%d" % rnd, "m%d.json" % i)
        if not isinstance(c, dict) or c.get("run") != self.run or c.get("round") != rnd or c.get("member") != i:
            return None
        return c

    def project(self, plan):
        return Tree(plan["project_root"])


def proj_parts(run, *rest):
    return [".claude-work", "eq", run] + list(rest)


# ---------------------------------------------------------------- git, safely
def git_bin():
    for g in GIT_CANDIDATES:
        if os.path.isfile(g) and os.access(g, os.X_OK):
            return g
    raise Refused(EXIT_FAILED, "no git at %s" % ", ".join(GIT_CANDIDATES))


def git_env():
    home = tempfile.gettempdir()
    return {"PATH": "/usr/bin:/bin:/usr/sbin:/sbin", "HOME": home, "LANG": "C", "LC_ALL": "C",
            "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_TERMINAL_PROMPT": "0",
            "GIT_OPTIONAL_LOCKS": "0", "GIT_PAGER": "cat", "PAGER": "cat"}


def git(cwd, *args, ok=(0,), timeout=GIT_TIMEOUT_S, overrides=True):
    """git -C cwd <safe -c> args, a fixed environment (no GIT_* from the caller, no global or system
    configuration), never a shell; (rc, stdout bytes). rc not in ok -> Refused."""
    argv = [git_bin(), "--no-pager", "-C", cwd, *(GIT_SAFE_CONFIG if overrides else ()), *args]
    try:
        p = subprocess.run(argv, stdin=subprocess.DEVNULL, capture_output=True, env=git_env(), timeout=timeout,
                           shell=False, close_fds=True)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise Refused(EXIT_FAILED, "git %s failed (%s)" % (args[0], type(exc).__name__))
    if p.returncode not in ok:
        raise Refused(EXIT_FAILED, "git %s exited %d: %s" % (" ".join(args[:2]), p.returncode,
                                                             p.stderr.decode("utf-8", "replace").strip()[-300:]))
    return p.returncode, p.stdout


def git_config_safe(cwd):
    """Refuse a repository whose configuration makes diff/status/add run a program (filters, external
    diff drivers, an fsmonitor or hooks path) or includes other files."""
    _, outb = git(cwd, "config", "-z", "--list", ok=(0, 1), overrides=False)     # the repository's own only
    for ent in outb.split(b"\0"):
        if not ent:
            continue
        key = ent.split(b"\n", 1)[0].decode("utf-8", "replace").lower()
        if GIT_DANGER_RE.match(key):
            raise Refused(EXIT_REFUSED, "the repository's git configuration sets %s (runs a program on diff/status): "
                          "stack-eq refuses to drive git here" % key)


def find_git_root(start, home):
    """The nearest ancestor of start holding .git (dir or file), stopping before home's ancestors."""
    d = os.path.realpath(start)
    while True:
        try:
            os.lstat(os.path.join(d, ".git"))
            return d
        except OSError:
            pass
        parent = os.path.dirname(d)
        if parent == d or d == home:
            return None
        d = parent


def worktrees(project_root):
    """{realpath: branch or None} of `git worktree list --porcelain -z`."""
    _, outb = git(project_root, "worktree", "list", "--porcelain", "-z")
    res, cur = {}, None
    for f in outb.decode("utf-8", "replace").split("\0"):
        if f.startswith("worktree "):
            cur = os.path.realpath(f[len("worktree "):])
            res[cur] = None
        elif f.startswith("branch ") and cur:
            res[cur] = f[len("branch "):]
    return res


def head_commit(project_root):
    rc, outb = git(project_root, "rev-parse", "--verify", "-q", "HEAD^{commit}", ok=(0, 1))
    return outb.decode().strip() if rc == 0 else None


def tracked_files(project_root):
    """[(rel, mode)] of the index's regular files (links and gitlinks are never copied)."""
    _, outb = git(project_root, "ls-files", "-z", "-s")
    res = []
    for ent in outb.split(b"\0"):
        if not ent:
            continue
        meta, _, path = ent.partition(b"\t")
        mode = meta.split(b" ")[0]
        rel = path.decode("utf-8", "surrogateescape")
        if mode in (b"100644", b"100755"):
            res.append((rel, 0o755 if mode == b"100755" else 0o644))
    return res


def dirty(project_root, paths=()):
    _, outb = git(project_root, "--no-optional-locks", "status", "--porcelain=v1", "-z", "--untracked-files=no",
                  "--", *paths)
    return [e.decode("utf-8", "replace")[3:] for e in outb.split(b"\0") if len(e) > 3]


def member_patch(wt):
    """The member worktree's change as a binary patch against HEAD: its untracked files are first added
    intent-to-add to that worktree's own index (spec 2.2 step 10)."""
    git_config_safe(wt)
    _, outb = git(wt, "ls-files", "-z", "--others", "--exclude-standard")
    new = [p for p in outb.decode("utf-8", "surrogateescape").split("\0") if p]
    if new:
        git(wt, "add", "--intent-to-add", "--", *new)
    _, patch = git(wt, "diff", "--binary", "--no-ext-diff", "--no-textconv", "--no-color", "--src-prefix=a/",
                   "--dst-prefix=b/", "HEAD")
    return patch


# ---------------------------------------------------------------- plan
def _validate_brief(brief, sid, run):
    if not isinstance(brief, dict) or brief.get("schema") != P.SCHEMA_BRIEF or brief.get("run") != run:
        raise Refused(EXIT_REFUSED, "brief.json missing or not this run's (eqbrief.v1)")
    if P.safe_sid(brief.get("session")) != P.safe_sid(sid):
        raise Refused(EXIT_REFUSED, "brief.json belongs to another session")
    h = brief.get("header")
    if not isinstance(h, dict) or h.get("class") not in P.CLASSES or h.get("mode") not in ("auto", "manual"):
        raise Refused(EXIT_REFUSED, "brief.json header malformed")
    if h.get("type") is not None and h["type"] not in P.MEMBER_TYPES:
        raise Refused(EXIT_REFUSED, "brief.json eq-type is not a member type")
    chk = h.get("check")
    if chk is not None and (not isinstance(chk, list) or not chk or not all(isinstance(w, str) and w for w in chk)):
        raise Refused(EXIT_REFUSED, "brief.json check malformed")
    segs = h.get("segments") or []
    if not isinstance(segs, list) or not all(isinstance(s, str) and s for s in segs):
        raise Refused(EXIT_REFUSED, "brief.json segments malformed")
    if not isinstance(brief.get("problem"), str) or not brief["problem"].strip():
        raise Refused(EXIT_REFUSED, "brief.json problem missing")
    cwd = brief.get("cwd")
    if not isinstance(cwd, str) or not os.path.isabs(cwd):
        raise Refused(EXIT_REFUSED, "brief.json cwd missing")
    return h


def _settings():
    s = P.read_json(os.path.join(CONFIG, "settings.json"))
    if not isinstance(s, dict):
        raise Refused(EXIT_REFUSED, "%s/settings.json unreadable: the deny list is unknown, nothing read" % CONFIG)
    return s


def _path_ok(path, project_root, settings, home, what):
    """Refuse a path outside the project root (after realpath) or matching the deny list/protected paths."""
    if not P.under_root(path, project_root):
        raise Refused(EXIT_REFUSED, "%s %s lies outside the project root %s (after resolving links): refused"
                      % (what, path, project_root))
    why = P.settings_denied(path, settings, home=home, config_dir=CONFIG, state_root=P.state_root(os.environ))
    if why:
        raise Refused(EXIT_REFUSED, "%s refused: %s" % (what, why))
    return os.path.realpath(path)


def _check_argv(argv, project_root, settings, home):
    """The check argv's paths stay inside the project (relative: the check copy is its cwd); its program
    resolves. Returns the resolved program."""
    prog = argv[0]
    for k, w in enumerate(argv):
        cand = []
        if k and w.startswith("-") and "=" in w:
            cand.append(w.split("=", 1)[1])
        elif not w.startswith("-"):
            cand.append(w)
        for v in cand:
            if v.startswith("~"):
                raise Refused(EXIT_REFUSED, "eq-check %r names a home path: refused" % w)
            if os.path.isabs(v) and not (k == 0 and any(v.startswith(d + "/") for d in SYSTEM_DIRS)):
                raise Refused(EXIT_REFUSED, "eq-check %r is an absolute path: use a path relative to the project "
                              "root (the check runs in a copy of it)" % w)
            if not os.path.isabs(v) and ("/" in v or os.path.lexists(os.path.join(project_root, v))):
                _path_ok(os.path.join(project_root, v), project_root, settings, home, "eq-check path %r" % v)
    if os.path.isabs(prog):
        res = prog if os.access(prog, os.X_OK) else None
    elif "/" in prog:
        p = os.path.join(project_root, prog)
        res = p if os.path.isfile(p) else None
    else:
        res = shutil.which(prog, path=os.environ.get("PATH") or "/usr/bin:/bin")
    if not res:
        raise Refused(EXIT_REFUSED, "eq-check program %r does not resolve" % prog)
    return res


def _fallback_caps(member_type):
    seed = P.read_json(os.path.join(HERE, "stack_limits_seed.json"))
    v = (seed or {}).get("vars") if isinstance(seed, dict) else None
    if not isinstance(v, dict):
        return None
    tok = (v.get("soft.agent." + member_type) or {}).get("seed")
    turns = (v.get("turns." + member_type) or {}).get("seed")
    caps = {}
    if isinstance(tok, int) and tok > 0:
        caps["member_tokens"] = tok
    if isinstance(turns, int) and turns > 0:
        caps["member_turns"] = turns
    return caps


def _session_runs(r):
    """Earlier eq runs of this session (a plan.json in a sibling run dir)."""
    n = 0
    try:
        with r.st.dir(r.parts[:-1]) as dfd:
            for name in os.listdir(dfd):
                if name != r.run and P.RUN_RE.match(name) and r.st.read("/".join(r.parts[:-1] + [name, "plan.json"])):
                    n += 1
    except OSError:
        pass
    return n


def _views_ok(views, n, nseg):
    if not isinstance(views, list) or len(views) != n:
        return False
    for v in views:
        if not isinstance(v, dict):
            return False
        for k in ("order", "kept"):
            if not isinstance(v.get(k), list) or not all(isinstance(x, int) and 0 <= x < max(nseg, 1) for x in v[k]):
                if nseg or v.get(k):
                    return False
    return True


def _copy_files(src, dst, rels, mode_of=None):
    """Copy regular files src/rel -> dst/rel (no link followed on either side); returns the count."""
    n = 0
    for rel in rels:
        got = src.read(rel)
        if got is None:
            continue
        data, mode = got
        m = mode_of(rel, mode) if mode_of else (stat.S_IMODE(mode) & 0o755) | 0o600
        dst.put_file(rel, data, m)
        n += 1
    return n


def cmd_plan(r, ticket):
    if r.get("plan.json") is not None:
        raise Refused(EXIT_REFUSED, "run eq:%s is already planned" % r.run)
    brief = r.get("brief.json")
    h = _validate_brief(brief, r.sid, r.run)
    cls, kind = h["class"], P.KIND[h["class"]]
    k = P.knobs(os.environ)
    if not k["STACK_EQ"]:
        raise Refused(EXIT_REFUSED, "STACK_EQ=0: equilibrium runs are off")
    home = os.path.realpath(os.environ.get("HOME") or os.path.expanduser("~"))
    settings = _settings()
    cwd = os.path.realpath(brief["cwd"])
    groot = find_git_root(cwd, home)
    root = groot or cwd
    if root == home or home.startswith(root.rstrip("/") + "/") or root == "/":
        raise Refused(EXIT_REFUSED, "project root %s is the home directory or an ancestor of it" % root)
    why = P.settings_denied(root, settings, home=home, config_dir=CONFIG, state_root=P.state_root(os.environ))
    if why:
        raise Refused(EXIT_REFUSED, "project root refused: %s" % why)
    segs = []
    for s in h.get("segments") or []:
        e = os.path.expanduser(s)
        full = e if os.path.isabs(e) else os.path.join(cwd, e)
        real = _path_ok(full, root, settings, home, "eq-segments path %r" % s)
        if not os.path.isfile(real):
            raise Refused(EXIT_REFUSED, "eq-segments path %r is not a regular file" % s)
        segs.append(os.path.relpath(real, root))
    check = h.get("check")
    prog = None
    if check is not None:
        if kind != "checkable":
            raise Refused(EXIT_REFUSED, "eq-check is for the checkable classes PF/CP only (%s runs no code)" % cls)
        prog = _check_argv(check, root, settings, home)
    elif kind == "checkable":
        raise Refused(EXIT_REFUSED, "%s needs eq-check: the public check that selects a candidate" % cls)
    head = None
    if cls in ("CP", "CR", "PF"):
        if not groot:
            raise Refused(EXIT_REFUSED, "%s needs a git repository (no .git above %s)" % (cls, cwd))
        git_config_safe(root)
        head = head_commit(root)
        if not head:
            raise Refused(EXIT_REFUSED, "%s needs a committed HEAD in %s" % (cls, root))
        changed = dirty(root, segs)
        if changed:
            raise Refused(EXIT_REFUSED, "uncommitted change under the problem paths (%s): commit or stash it first"
                          % ", ".join(changed[:5]))
    if cls == "PF" and not any(os.path.isfile(os.path.join(root, f)) for f in ("lakefile.lean", "lakefile.toml")):
        raise Refused(EXIT_REFUSED, "PF needs a lake project (lakefile.lean or lakefile.toml at %s)" % root)
    if cls == "CR" and not segs:
        raise Refused(EXIT_REFUSED, "CR needs at least one file to review (eq-segments)")
    params, psha, pwhy = P.load_params(os.path.join(HERE, "eq_params.json"), os.path.join(CONFIG, ".stack-manifest.json"))
    member_type = h.get("type") or P.S_STAR[cls]
    try:
        b = P.resolve(cls, params, k, mode=h["mode"], eq_type=h.get("type"), session_runs=_session_runs(r),
                      fallback_caps=_fallback_caps(member_type))
    except P.PolicyError as exc:
        raise Refused(EXIT_REFUSED, str(exc))
    level2, l2why = False, "not a checkable class"
    if kind == "checkable" and k["STACK_EQ_WALL"] != "sandbox":
        cfg, l2why = isolation().level2_config(os.environ, CONFIG, cls, unsafe_roots=(root, cwd))
        level2 = cfg is not None
    try:
        w3 = P.w3_level(k["STACK_EQ_WALL"], level2, kind)
    except P.PolicyError as exc:
        raise Refused(EXIT_REFUSED, "%s (%s)" % (exc, l2why))
    n = b["N"]
    seed = seed_of("eq|run", r.run)
    views = call_core("member_views", cls, n, segs, seed, b["view"])
    if not _views_ok(views, n, len(segs)):
        raise Refused(EXIT_FAILED, "eq_core.member_views returned a malformed view list")
    schemas = call_core("load_schemas", os.path.join(HERE, "eq_schemas.json"))
    schema = schemas.get(cls) if isinstance(schemas, dict) else None
    if not isinstance(schema, dict):
        raise Refused(EXIT_FAILED, "eq_schemas.json has no %s schema" % cls)
    wd = P.workdir(cls, segs)
    member_dirs = {}
    if wd == "dir":
        with Tree(root) as proj:
            pristine = [rel for rel, _m in tracked_files(root)] if cls == "PF" else None
            for i in range(1, n + 1):
                parts = proj_parts(r.run, "m%d" % i)
                proj.rmtree(parts[:-1], parts[-1])
                with proj.dir(parts, create=True):
                    pass
                dst = Tree(os.path.join(root, *parts))
                try:
                    if cls == "PF":
                        _copy_files(proj, dst, pristine)
                    else:
                        kept = [segs[x] for x in views[i - 1]["kept"]]
                        _copy_files(proj, dst, kept)
                finally:
                    dst.close()
                member_dirs[str(i)] = os.path.join(root, *parts)
    for i in range(1, n + 1):
        text = call_core("render_brief", cls, run=r.run, member=i, n=n, view=views[i - 1], problem=brief["problem"],
                         segments=segs, schema=schema, workdir=member_dirs.get(str(i)))
        if not isinstance(text, str) or not text.startswith("eq %s m%d/%d" % (r.run, i, n)):
            raise Refused(EXIT_FAILED, "eq_core.render_brief: the brief must start with `eq %s m%d/%d`" % (r.run, i, n))
        data = text.encode("utf-8")
        r.put("briefs", "m%d.txt" % i, text=text)
        r.put("briefs", "m%d.txt.sha256" % i, text=sha256_bytes(data) + "\n")
    plan = {"schema": P.SCHEMA_PLAN, "run": r.run, "session": r.sid, "class": cls, "kind": kind, "mode": h["mode"],
            "validated": b["validated"], "status_reason": b["status_reason"], "status_reasons": b["status_reasons"],
            "params_sha256": psha if params is not None else None, "params_reason": pwhy,
            "member_type": b["member_type"], "member_model": b["member_model"], "member_model_id": b["member_model_id"],
            "N": n, "rounds": b["rounds"], "view": b["view"], "loo_view": b["loo_view"], "reducer": b["reducer"],
            "tau": b["tau"], "t": b["t"], "member_tools": list(P.MEMBER_TOOLS[cls]), "workdir": wd,
            "project_root": root, "member_dirs": member_dirs, "segments": segs, "head": head,
            "check": {"argv": list(check), "program": prog} if check is not None else None,
            "caps": b["caps"], "estimate": b["estimate"],
            "consent": {"required": b["consent_required"], "token": P.consent_token(r.run)}, "seed": seed,
            "w3": w3, "w3_reason": None if level2 else l2why, "views": views, "warnings": b["warnings"],
            "created": now()}
    if params is not None and b["validated"]:
        plan["validated_on"] = params["classes"][cls].get("pool")
    r.put("plan.json", obj=plan)
    r.set_state("planned", 0)
    e = b["estimate"]
    usd = ("USD %s expected, %s worst (%s)" % (e["usd_expected"], e["usd_worst"], e["usd_source"])
           if e["usd_worst"] is not None else "USD: %s" % e["usd_source"])
    out("eq:%s planned: class %s, %d x %s, %d reconcile round(s), view %s, LOO %s, W3 %s" % (
        r.run, cls, n, b["member_type"], b["rounds"], b["view"], b["loo_view"], w3))
    out("label: %s" % ("validated" if b["validated"] else "unvalidated (%s)" % ", ".join(b["status_reasons"])))
    for w in b["warnings"]:
        out("warning: %s" % w)
    out("estimate: tokens %d expected, %d worst; %s" % (e["tokens_expected"], e["tokens_worst"], usd))
    if b["consent_required"]:
        out("consent: required. Return STATUS: blocked with NEXT: ASK USER: Run eq:%s (est. %d-%d tokens%s) | Cancel"
            % (r.run, e["tokens_expected"], e["tokens_worst"],
               ", USD %s-%s" % (e["usd_expected"], e["usd_worst"]) if e["usd_worst"] is not None else ""))
    else:
        out("consent: not required (validated, auto, within the cap and the session allowance)")
    out("next: %s/bin/stack-eq start --run %s" % (CONFIG, r.run))
    return EXIT_OK


# ---------------------------------------------------------------- start
def cmd_start(r, p, plan):
    st = r.state()
    if st.get("phase") != "planned":
        raise Refused(EXIT_REFUSED, "run eq:%s is %s, not planned" % (r.run, st.get("phase")))
    if p["headless"]:
        if os.environ.get("CLAUDECODE"):
            raise Refused(EXIT_REFUSED, "start --headless runs from a terminal (CLAUDECODE is set): refused")
        try:
            raw = P.read_bytes_nofollow(p["consent_file"], 1 << 16)
            cf = json.loads(raw.decode("utf-8"))
        except (OSError, P.PolicyError, ValueError):
            raise Refused(EXIT_REFUSED, "consent file %s unreadable (a regular file, not a link)" % p["consent_file"])
        plan_raw = r.raw("plan.json")
        if not isinstance(cf, dict) or cf.get("token") != P.consent_token(r.run) or \
                cf.get("plan_sha256") != sha256_bytes(plan_raw or b""):
            raise Refused(EXIT_REFUSED, "consent file must hold {\"token\": \"Run eq:%s\", \"plan_sha256\": "
                          "sha256(plan.json)}" % r.run)
        rec = {"token": P.consent_token(r.run), "answer": P.consent_token(r.run), "ts": now(), "source": "file",
               "plan_sha256": cf["plan_sha256"]}
        r.st.write_json([P.safe_sid(r.sid), "eq", "consent"], "%s.json" % r.run, rec)
    elif plan["consent"]["required"]:
        rec = P.read_json(P.consent_path(os.environ, r.sid, r.run, "run"))
        if not P.consent_ok(rec, r.run, "run"):
            out("consent: missing. Return STATUS: blocked with NEXT: ASK USER: Run eq:%s (est. %s-%s tokens) | Cancel"
                % (r.run, plan["estimate"]["tokens_expected"], plan["estimate"]["tokens_worst"]))
            raise Refused(EXIT_ASK, "no consent record for Run eq:%s (the user's AskUserQuestion answer)" % r.run)
    r.set_state("started", 0)
    r.append_ledger({"record": "start", "run": r.run, "consent": "file" if p["headless"] else (
        "ask" if plan["consent"]["required"] else "not required")})
    n = plan["N"]
    out("eq:%s started. Round 0 (blind): issue these %d Agent calls in ONE message, run_in_background: false, "
        "subagent_type %s%s, each prompt and description exactly:" % (
            r.run, n, plan["member_type"], ', isolation: "worktree"' if plan["workdir"] == "worktree" else ""))
    for i in range(1, n + 1):
        out("  eq %s m%d/%d" % (r.run, i, n))
    return EXIT_OK


# ---------------------------------------------------------------- checks
def _candidates(r, plan, rnd):
    """{i: capture} of members whose round-rnd reply was captured with an answer."""
    res = {}
    for i in range(1, plan["N"] + 1):
        c = r.capture(rnd, i)
        if c and c.get("status") == "ok" and c.get("answer") is not None:
            res[i] = c
    return res


def _member_source(r, plan, i, wts=None):
    """The candidate's directory: CP/CR its registered worktree (never the main one), PF its m<i>/."""
    if plan["workdir"] == "worktree":
        rec = r.members().get(str(i)) or {}
        wt = rec.get("worktree")
        if not isinstance(wt, str) or not os.path.isabs(wt):
            raise Refused(EXIT_REFUSED, "member m%d has no recorded worktree" % i)
        real = os.path.realpath(wt)
        wts = wts if wts is not None else worktrees(plan["project_root"])
        if real not in wts or real == os.path.realpath(plan["project_root"]) or \
                not P.under_root(real, plan["project_root"]):
            raise Refused(EXIT_REFUSED, "member m%d's worktree %s is not a registered worktree of this project"
                          % (i, wt))
        return real
    d = (plan.get("member_dirs") or {}).get(str(i))
    if not d:
        raise Refused(EXIT_REFUSED, "member m%d has no work dir" % i)
    return d


def owned_paths(plan, pristine_set):
    """Pristine paths a candidate never overrides: the class's owned dirs (tests) + every check argument
    naming a pristine top-level file (the check script)."""
    own = list(OWNED_PATHS.get(plan["class"], ()))
    for a in (plan.get("check") or {}).get("argv", []):
        if "/" not in a and a not in (".", "..") and a in pristine_set:
            own.append(a)
    return own


def _is_owned(rel, own):
    return any(rel == o or rel.startswith(o.rstrip("/") + "/") for o in own)


def cmd_prepare_check(r, rnd, plan):
    if plan["kind"] != "checkable" or not plan.get("check"):
        raise Refused(EXIT_REFUSED, "run eq:%s has no check (class %s)" % (r.run, plan["class"]))
    st = r.state()
    if st.get("phase") not in ("started", "viewed", "checks") or st.get("round") != rnd:
        raise Refused(EXIT_REFUSED, "prepare-check --round %d: the run is %s round %s" % (rnd, st.get("phase"),
                                                                                         st.get("round")))
    root = plan["project_root"]
    git_config_safe(root)
    if head_commit(root) != plan.get("head") or dirty(root):
        raise Refused(EXIT_REFUSED, "the project changed since the plan (HEAD or a tracked file): the pristine copy "
                      "would not be the planned one")
    files = tracked_files(root)
    pset = {rel for rel, _ in files}
    own = owned_paths(plan, pset)
    cands = _candidates(r, plan, rnd)
    if not cands:
        raise Refused(EXIT_REFUSED, "round %d has no captured candidate" % rnd)
    wts = worktrees(root) if plan["workdir"] == "worktree" else None
    report = {}
    with Tree(root) as proj:
        proj.rmtree(proj_parts(r.run), "checks")
        with proj.dir(proj_parts(r.run, "checks"), create=True):
            pass
        if plan["w3"] == "container":
            dstp = Tree(os.path.join(root, *proj_parts(r.run, "checks")))
            with dstp.dir(["pristine"], create=True):
                pass
            dstp.close()
            pr = Tree(os.path.join(root, *proj_parts(r.run, "checks", "pristine")))
            try:
                _copy_files(proj, pr, [rel for rel, _ in files])
            finally:
                pr.close()
        for i in sorted(cands):
            src = Tree(_member_source(r, plan, i, wts))
            with proj.dir(proj_parts(r.run, "checks", "c%d" % i), create=True):
                pass
            dst = Tree(os.path.join(root, *proj_parts(r.run, "checks", "c%d" % i)))
            n_over = 0
            try:
                for rel, mode in files:
                    got = proj.read(rel)
                    if got is None:
                        continue                      # a link or special file in the pristine tree: never copied
                    data, pmode = got
                    keep_mode = (stat.S_IMODE(pmode) & 0o755) | 0o600
                    if plan["w3"] == "container" and _is_owned(rel, own):
                        continue                      # mounted read-only from the pristine copy instead
                    if not _is_owned(rel, own):
                        theirs = src.read(rel)
                        if theirs is not None:
                            n_over += theirs[0] != data
                            data = theirs[0]
                    dst.put_file(rel, data, keep_mode)
            finally:
                src.close()
                dst.close()
            report[str(i)] = {"files": len(files), "overlaid": n_over}
    r.put("r%d" % rnd, "checks.json", obj={"round": rnd, "owned": own, "candidates": report, "w3": plan["w3"]})
    r.set_state("checks", rnd)
    out("eq:%s round %d: %d check copies under .claude-work/eq/%s/checks/ (owned, never from a candidate: %s)"
        % (r.run, rnd, len(cands), r.run, ", ".join(own) or "none"))
    if plan["w3"] == "container":
        out("next: %s/bin/stack-eq check-container --run %s --round %d" % (CONFIG, r.run, rnd))
    else:
        for i in sorted(cands):
            out("next: %s/bin/stack-eq-check --run %s --cand %d" % (CONFIG, r.run, i))
    return EXIT_OK


def cmd_check_container(r, rnd, plan):
    if plan.get("w3") != "container" or not plan.get("check"):
        raise Refused(EXIT_REFUSED, "run eq:%s checks at Level 1 (w3 %s): use stack-eq-check" % (r.run, plan.get("w3")))
    st = r.state()
    if st.get("phase") != "checks" or st.get("round") != rnd:
        raise Refused(EXIT_REFUSED, "check-container: run prepare-check --round %d first" % rnd)
    iso = isolation()
    root = plan["project_root"]
    cfg, why = iso.level2_config(os.environ, CONFIG, plan["class"], unsafe_roots=(root,))
    if cfg is None:
        raise Refused(EXIT_REFUSED, "Level 2 unavailable: %s" % why)
    meta = r.get("r%d" % rnd, "checks.json") or {}
    base = os.path.join(root, *proj_parts(r.run, "checks"))
    copies = {}
    for k in sorted((meta.get("candidates") or {}), key=int):
        i = int(k)
        with Tree(root) as proj:
            with proj.dir(proj_parts(r.run, "checks", "c%d" % i)):
                copies[i] = os.path.join(base, "c%d" % i)
    with Tree(root) as proj:
        with proj.dir(proj_parts(r.run, "checks", "pristine")):
            pass
    with r.st.dir(r.parts + ["wall"], create=True):
        pass
    wall_dir = os.path.join(r.st.root, *r.parts, "wall")
    try:
        results, rec = iso.run_checks(cfg, store_wall_dir=wall_dir, copies=copies,
                                      pristine=os.path.join(base, "pristine"), owned=meta.get("owned") or [],
                                      argv=plan["check"]["argv"], timeout_s=P.CHECK_TIMEOUT_S,
                                      forbidden=(r.st.root, CONFIG))
    except iso.IsolationError as exc:
        raise Refused(EXIT_REFUSED, "Level 2 refused: %s" % exc)
    for i, (rc, timed_out, tail) in sorted(results.items()):
        verdict = "pass" if rc == 0 and not timed_out else "fail"
        r.put("r%d" % rnd, "check-c%d.json" % i, obj={"cand": i, "round": rnd, "exit": rc, "exit_source": "container",
                                                       "timed_out": timed_out, "tail": tail.decode("utf-8", "replace"),
                                                       "verdict": verdict})
        out("c%d: %s (exit %s%s)" % (i, verdict, rc, ", timed out" if timed_out else ""))
    if rec:
        r.append_ledger(dict(rec, round=rnd))
        r.put("wall", "audit_head.json", obj=rec)
    return EXIT_OK


# ---------------------------------------------------------------- reduce, view, result
def _round_complete(r, plan, rnd):
    """[] when every member of round rnd is captured (or abstained/stopped) and every candidate's check
    has a verdict; else the missing pieces."""
    missing = []
    members = r.members()
    for i in range(1, plan["N"] + 1):
        rec = members.get(str(i))
        if not isinstance(rec, dict):
            missing.append("m%d never spawned" % i)
            continue
        state = (rec.get("rounds") or {}).get(str(rnd))
        if state == "captured":
            if r.capture(rnd, i) is None:
                missing.append("m%d's capture file" % i)
        elif state in ("abstain", "invalid") or rec.get("status") in ("stopped", "abstain"):
            continue
        else:
            missing.append("m%d not captured" % i)
    if plan["kind"] == "checkable" and plan.get("check"):
        for i in _candidates(r, plan, rnd):
            v = r.get("r%d" % rnd, "check-c%d.json" % i)
            if not isinstance(v, dict) or v.get("verdict") not in ("pass", "fail", "unverifiable") or \
                    v.get("cand") != i or v.get("round") != rnd:
                missing.append("c%d's check verdict" % i)
    return missing


def _answers(r, plan, rnd):
    res = {}
    for i in range(1, plan["N"] + 1):
        c = r.capture(rnd, i)
        res[i] = c.get("answer") if c and c.get("status") == "ok" else None
    return res


def _verdicts(r, plan, rnd):
    if plan["kind"] != "checkable" or not plan.get("check"):
        return None
    res = {}
    for i in range(1, plan["N"] + 1):
        v = r.get("r%d" % rnd, "check-c%d.json" % i)
        res[i] = v.get("verdict") if isinstance(v, dict) and v.get("verdict") in ("pass", "fail") else "unverifiable"
    return res


REDUCE_KEYS = ("answer", "partial", "kappa", "clusters", "selected", "loo", "lambda", "pivotal")


def cmd_reduce(r, rnd, plan):
    st = r.state()
    if st.get("round") != rnd or st.get("phase") not in ("started", "viewed", "checks"):
        raise Refused(EXIT_REFUSED, "reduce --round %d: the run is %s round %s" % (rnd, st.get("phase"), st.get("round")))
    if plan["kind"] == "checkable" and plan.get("check") and st.get("phase") != "checks":
        raise Refused(EXIT_REFUSED, "reduce --round %d: prepare and run the checks first" % rnd)
    missing = _round_complete(r, plan, rnd)
    if missing:
        raise Refused(EXIT_REFUSED, "round %d is incomplete: %s" % (rnd, "; ".join(missing[:10])))
    answers = _answers(r, plan, rnd)
    seed_r = seed_of("eq|ties", r.run, rnd)
    res = call_core("reduce_round", plan["class"], answers, seed=seed_r, tau=plan["tau"], t=plan["t"],
                    verdicts=_verdicts(r, plan, rnd), facts=None)
    if not isinstance(res, dict) or not all(k in res for k in REDUCE_KEYS):
        raise Refused(EXIT_FAILED, "eq_core.reduce_round must return %s" % ", ".join(REDUCE_KEYS))
    r.put("r%d" % rnd, "reduce.json", obj={"round": rnd, "seed": seed_r, "result": res,
                                           "answers_sha256": sha256_bytes(canon(answers))})
    r.append_ledger({"record": "attribution", "round": rnd, "loo": res["loo"], "lambda": res["lambda"],
                     "pivotal": res["pivotal"]})
    r.append_ledger({"record": "reduce", "round": rnd, "kappa": res["kappa"], "selected": res["selected"],
                     "partial": res["partial"], "facts": "not re-run (fact re-runs need stack-eq-check or Level 2)"})
    with Tree(plan["project_root"]) as proj:
        if proj.exists(proj_parts(r.run)):
            proj.rmtree(proj_parts(r.run), "checks")
    r.set_state("reduced", rnd)
    out("eq:%s round %d reduced: kappa %s (agreement, not probability), selected %s%s" % (
        r.run, rnd, res["kappa"], res["selected"], ", partial" if res["partial"] else ""))
    more = rnd < plan["rounds"] and (
        (plan["kind"] in ("discrete", "numeric") and isinstance(res["kappa"], (int, float)) and res["kappa"] < plan["tau"])
        or (plan["kind"] == "checkable" and res["selected"] is None))
    if more:
        out("next: %s/bin/stack-eq view --run %s --round %d" % (CONFIG, r.run, rnd + 1))
    else:
        out("next: %s/bin/stack-eq result --run %s" % (CONFIG, r.run))
    return EXIT_OK


def cmd_view(r, rnd, plan):
    st = r.state()
    if rnd > plan["rounds"]:
        raise Refused(EXIT_REFUSED, "the plan has %d reconcile round(s)" % plan["rounds"])
    if st.get("phase") != "reduced" or st.get("round") != rnd - 1:
        raise Refused(EXIT_REFUSED, "view --round %d needs round %d reduced (the run is %s round %s)"
                      % (rnd, rnd - 1, st.get("phase"), st.get("round")))
    prev = (r.get("r%d" % (rnd - 1), "reduce.json") or {}).get("result") or {}
    answers = _answers(r, plan, rnd - 1)
    seed_r = seed_of("eq|ties", r.run, rnd)
    top = [int(x) for x in (prev.get("top_members") or []) if isinstance(x, int)]
    outputs = None
    if plan["kind"] == "checkable":              # repair round: the anonymised failing-check outputs
        outputs = {}
        for i in range(1, plan["N"] + 1):
            v = r.get("r%d" % (rnd - 1), "check-c%d.json" % i)
            if isinstance(v, dict) and v.get("verdict") != "pass" and isinstance(v.get("tail"), str):
                outputs[i] = v["tail"][-4000:]
    n = plan["N"]
    for i in range(1, n + 1):
        e = call_core("loo_exclude", plan["loo_view"], i, rnd, n, seed=plan["seed"], top=top)
        if e is not None and (not isinstance(e, int) or not 1 <= e <= n or e == i):
            raise Refused(EXIT_FAILED, "eq_core.loo_exclude returned %r for m%d" % (e, i))
        text = call_core("render_view", plan["class"], answers, None, member=i, exclude=e, round=rnd, seed=seed_r,
                         run=r.run, check_outputs=outputs)
        if not isinstance(text, str):
            raise Refused(EXIT_FAILED, "eq_core.render_view must return text")
        r.put("views", "r%d" % rnd, "m%d.txt" % i, text=text)
        r.put("views", "r%d" % rnd, "m%d.txt.sha256" % i, text=sha256_bytes(text.encode("utf-8")) + "\n")
        r.append_ledger({"record": "loo_view", "round": rnd, "member": i, "exclude": e, "variant": plan["loo_view"]})
    r.set_state("viewed", rnd)
    out("eq:%s round %d views ready. Send each member exactly (SendMessage to its agent id):" % (r.run, rnd))
    for i in range(1, n + 1):
        out("  eq %s r%d m%d" % (r.run, rnd, i))
    return EXIT_OK


def _all_stopped(r, plan):
    m = r.members()
    return all(isinstance(m.get(str(i)), dict) and m[str(i)].get("status") in ("stopped", "abstain")
               for i in range(1, plan["N"] + 1))


def cmd_result(r, plan, params_ok=True):
    st = r.state()
    if st.get("phase") not in ("reduced", "result"):
        raise Refused(EXIT_REFUSED, "result: reduce the last round first (the run is %s)" % st.get("phase"))
    final = st.get("round")
    reduces = []
    for rnd in range(0, final + 1):
        rr = r.get("r%d" % rnd, "reduce.json")
        if not isinstance(rr, dict):
            raise Refused(EXIT_REFUSED, "round %d has no reduce.json" % rnd)
        reduces.append(rr["result"])
    models = []
    for rnd in range(0, final + 1):
        for i in range(1, plan["N"] + 1):
            c = r.capture(rnd, i)
            if c and c.get("status") == "ok":
                models.append(c.get("model"))
    validated, reason = P.final_label(plan["validated"], plan["status_reason"], plan.get("member_model_id"), models)
    sel = reduces[-1].get("selected")
    members_p, nxt = {}, []
    root = plan["project_root"]
    if plan["class"] == "CP":
        wts = worktrees(root)
        with Tree(root) as proj:
            for i in range(1, plan["N"] + 1):
                rec = r.members().get(str(i)) or {}
                if not rec.get("worktree"):
                    continue
                wt = _member_source(r, plan, i, wts)
                patch = member_patch(wt)
                name = "selected.patch" if i == sel else "cand-%d.patch" % i
                proj.write(proj_parts(r.run), name, patch, 0o600)
                members_p[str(i)] = {"path": os.path.join(".claude-work", "eq", r.run, name),
                                     "sha256": sha256_bytes(patch), "worktree": wt, "branch": wts.get(wt)}
        if sel is not None and str(sel) in members_p:
            nxt.append("NEXT: coder applies ./.claude-work/eq/%s/selected.patch" % r.run)
        if members_p:
            nxt.append("ASK USER: Remove %d eq worktrees and branches for eq:%s (patches kept) | Keep"
                       % (len(members_p), r.run))
    patches = None
    if members_p:
        patches = {"selected": members_p[str(sel)]["path"] if str(sel) in members_p else None, "members": members_p}
    checks = None
    if plan["kind"] == "checkable" and plan.get("check"):
        checks = {"argv": plan["check"]["argv"], "w3": plan["w3"], "selected": sel, "candidates": {}}
        for rnd in range(0, final + 1):
            for i in range(1, plan["N"] + 1):
                v = r.get("r%d" % rnd, "check-c%d.json" % i)
                if isinstance(v, dict):
                    checks["candidates"]["r%d/c%d" % (rnd, i)] = {"verdict": v.get("verdict"),
                                                                  "exit_source": v.get("exit_source")}
    fields = {"run": r.run, "class": plan["class"], "validated": validated, "status_reason": reason,
              "validated_on": plan.get("validated_on") if validated else None,
              "params_sha256": plan.get("params_sha256"), "checks": checks,
              "wall": {"w3": plan["w3"], "w1_file_tools": "hook",
                       "w1_bash": "heuristic" if plan["class"] in ("PF", "CP", "CR") else "n/a"},
              "cost": {"estimate": plan["estimate"], "actual": None,
                       "actual_note": "per-member tokens are in the guard's usage rows (eq_run=%s)" % r.run},
              "patches": patches, "next": nxt}
    got = call_core("result_block", run=r.run, cls=plan["class"], rounds=reduces, validated=validated,
                    status_reason=reason, validated_on=fields["validated_on"], checks=checks, wall=fields["wall"],
                    cost=fields["cost"], params_sha256=fields["params_sha256"], patches=patches, next_lines=nxt)
    if not (isinstance(got, (tuple, list)) and len(got) == 2 and isinstance(got[0], dict) and isinstance(got[1], str)):
        raise Refused(EXIT_FAILED, "eq_core.result_block must return (json object, prose line)")
    obj, prose = dict(got[0]), got[1]
    obj.update(fields)                       # labels, provenance, wall and patches are the executor's, never core's
    if not validated or plan["class"] in ("CR", "DS", "OE"):
        obj["certainty"] = None
    obj.setdefault("agreement", {})
    if isinstance(obj["agreement"], dict):
        obj["agreement"]["label"] = "agreement, not probability"
    r.put("result.json", obj=obj)
    copied = False
    if _all_stopped(r, plan):
        with Tree(root) as proj:
            proj.write_json(proj_parts(r.run), "result.json", obj)
        copied = True
    r.set_state("result", final)
    out(prose)
    out(json.dumps(obj, indent=1, sort_keys=True))
    for line in nxt:
        out(line)
    if not copied:
        out("note: result.json goes to ./.claude-work/eq/%s/ once every member has stopped" % r.run)
    return EXIT_OK


def cmd_cleanup(r, plan):
    rec = P.read_json(P.consent_path(os.environ, r.sid, r.run, "remove"))
    if not P.consent_ok(rec, r.run, "remove"):
        out("consent: missing. NEXT: ASK USER: Remove eq worktrees and branches for eq:%s (patches kept) | Keep" % r.run)
        raise Refused(EXIT_ASK, "no Remove consent record for eq:%s" % r.run)
    res = r.get("result.json")
    if not isinstance(res, dict) or not isinstance(res.get("patches"), dict) or \
            not isinstance(res["patches"].get("members"), dict):
        raise Refused(EXIT_REFUSED, "cleanup needs the result (stack-eq result) and its patches")
    root = plan["project_root"]
    wts = worktrees(root)
    members = r.members()
    todo = []
    for k, ent in sorted(res["patches"]["members"].items()):
        rec_m = members.get(k) or {}
        wt = os.path.realpath(rec_m.get("worktree") or "")
        if not rec_m.get("worktree") or wt != ent.get("worktree"):
            raise Refused(EXIT_REFUSED, "m%s: the registry does not record %s as this run's member worktree" % (k, ent.get("worktree")))
        if wt not in wts or wt == os.path.realpath(root):
            raise Refused(EXIT_REFUSED, "m%s: %s is not a registered worktree of this project" % (k, wt))
        patch = member_patch(wt)
        if sha256_bytes(patch) != ent.get("sha256"):
            raise Refused(EXIT_REFUSED, "m%s: the worktree's diff no longer matches %s: nothing removed (keep it, or "
                          "save its change first)" % (k, ent.get("path")))
        todo.append((k, wt, wts.get(wt)))
    for k, wt, branch in todo:
        git(root, "worktree", "remove", "--force", wt)
        if branch and branch.startswith("refs/heads/"):
            git(root, "branch", "-d", branch[len("refs/heads/"):], ok=(0, 1))
        out("removed m%s: %s%s" % (k, wt, " and %s" % branch if branch else ""))
    r.set_state("cleaned", r.state().get("round", 0))
    r.append_ledger({"record": "cleanup", "removed": [t[0] for t in todo]})
    return EXIT_OK


def cmd_status(r):
    st = r.state()
    plan = r.get("plan.json") or {}
    out("eq:%s %s round %s; class %s, N %s, w3 %s" % (r.run, st.get("phase", "spawned"), st.get("round"),
                                                       plan.get("class"), plan.get("N"), plan.get("w3")))
    for k, rec in sorted(r.members().items()):
        if isinstance(rec, dict):
            out("  m%s %s rounds %s" % (k, rec.get("status"), json.dumps(rec.get("rounds") or {}, sort_keys=True)))
    return EXIT_OK


HELP = __doc__.split("\n\n")[1]


# ---------------------------------------------------------------- the executor's main
def executor(args):
    try:
        try:
            p = P.parse_cli(args)
        except P.PolicyError as exc:
            raise Refused(EXIT_USAGE, "usage: %s (stack-eq help)" % exc)
        if p["sub"] == "help":
            out(HELP)
            return EXIT_OK
        if p["headless"]:
            try:
                store = P.find_run(os.environ, p["run"])
            except P.PolicyError as exc:
                raise Refused(EXIT_REFUSED, str(exc))
            sid = os.path.basename(os.path.dirname(os.path.dirname(store)))
            ticket = None
        else:
            ticket = claim_ticket(args)
            if ticket is None:
                raise Refused(EXIT_REFUSED, "no guard ticket for this call: stack-eq runs only for the equilibrium "
                              "agent, through the stack's hook, as one plain command by its absolute path")
            if ticket["run"] != p["run"]:
                raise Refused(EXIT_REFUSED, "the ticket is for run eq:%s, not eq:%s" % (ticket["run"], p["run"]))
            sid = ticket["session"]
        r = Run(sid, p["run"])
        r.lock()
        sub = p["sub"]
        if sub == "plan":
            return cmd_plan(r, ticket)
        if sub == "status":
            return cmd_status(r)
        plan = r.plan()
        if sub == "start":
            return cmd_start(r, p, plan)
        if sub == "prepare-check":
            return cmd_prepare_check(r, p["round"], plan)
        if sub == "check-container":
            return cmd_check_container(r, p["round"], plan)
        if sub == "reduce":
            return cmd_reduce(r, p["round"], plan)
        if sub == "view":
            return cmd_view(r, p["round"], plan)
        if sub == "result":
            return cmd_result(r, plan)
        if sub == "cleanup":
            return cmd_cleanup(r, plan)
        raise Refused(EXIT_USAGE, "unhandled subcommand %s" % sub)
    except Refused as exc:
        sys.stdout.flush()
        sys.stderr.write("stack-eq: %s\n" % exc)
        return exc.code
    except OSError as exc:
        sys.stdout.flush()
        sys.stderr.write("stack-eq: %s: %s\n" % (type(exc).__name__, exc))
        return EXIT_FAILED


# ---------------------------------------------------------------- stack-eq-check (sandboxed)
def check_env(tmp):
    env = {"PATH": os.environ.get("PATH") or "/usr/bin:/bin", "HOME": os.environ.get("HOME", ""), "LANG": "C.UTF-8",
           "TMPDIR": tmp}
    if os.environ.get("UV_CACHE_DIR"):
        env["UV_CACHE_DIR"] = os.environ["UV_CACHE_DIR"]
    return env


def run_bounded(argv, cwd, env, timeout_s, keep=P.TAIL_BYTES):
    """argv (shell=False) in its own process group, stdin /dev/null, merged output kept as the last
    `keep` bytes (never printed); the group killed on exit or timeout. (rc or None on timeout, tail)."""
    proc = subprocess.Popen(list(argv), cwd=cwd, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, shell=False, start_new_session=True, close_fds=True)
    buf = bytearray()

    def pump():
        while True:
            chunk = os.read(proc.stdout.fileno(), 65536)
            if not chunk:
                break
            buf.extend(chunk)
            if len(buf) > keep:
                del buf[: len(buf) - keep]

    th = threading.Thread(target=pump, daemon=True)
    th.start()
    try:
        rc = proc.wait(timeout=timeout_s)
    except subprocess.TimeoutExpired:
        rc = None
    finally:
        with contextlib.suppress(ProcessLookupError, PermissionError):
            os.killpg(proc.pid, signal.SIGKILL)
        proc.wait()
        th.join(5)
        with contextlib.suppress(OSError):
            proc.stdout.close()
    return rc, bytes(buf)


def check_runner(args):
    """stack-eq-check --run R --cand i: exactly one EQCHECK line on stdout, exit = the check's (124 on
    timeout); any refusal: a message on stderr, nothing on stdout, exit 4 (the guard's verdict is then
    `unverifiable`, never `pass`)."""
    try:
        try:
            a = P.parse_check_cli(args)
        except P.PolicyError as exc:
            raise Refused(EXIT_USAGE, str(exc))
        try:
            store = P.find_run(os.environ, a["run"])
        except P.PolicyError as exc:
            raise Refused(EXIT_REFUSED, str(exc))
        plan = P.read_json(os.path.join(store, "plan.json"))
        state = P.read_json(os.path.join(store, "state.json")) or {}
        if not isinstance(plan, dict) or plan.get("schema") != P.SCHEMA_PLAN or plan.get("run") != a["run"]:
            raise Refused(EXIT_REFUSED, "run eq:%s has no plan" % a["run"])
        chk = plan.get("check")
        if not isinstance(chk, dict) or not isinstance(chk.get("argv"), list) or not chk["argv"] or \
                not all(isinstance(w, str) and w for w in chk["argv"]):
            raise Refused(EXIT_REFUSED, "run eq:%s lists no check" % a["run"])
        if state.get("phase") != "checks" or not isinstance(state.get("round"), int):
            raise Refused(EXIT_REFUSED, "run eq:%s is not in its checks phase" % a["run"])
        rnd = state["round"]
        root = plan.get("project_root")
        if not isinstance(root, str) or not os.path.isabs(root):
            raise Refused(EXIT_REFUSED, "plan.json has no project root")
        with Tree(root) as proj:
            try:
                with proj.dir(proj_parts(a["run"], "checks", "c%d" % a["cand"])):
                    pass
            except FileNotFoundError:
                raise Refused(EXIT_REFUSED, "no check copy c%d (stack-eq prepare-check first)" % a["cand"])
        cwd = os.path.join(os.path.realpath(root), *proj_parts(a["run"], "checks", "c%d" % a["cand"]))
        timeout = P.CHECK_TIMEOUT_S
        raw = (os.environ.get("STACK_EQ_CHECK_TIMEOUT_S") or "").strip()
        if raw.isdigit() and 0 < int(raw) < timeout:
            timeout = int(raw)                 # may only shorten: a timeout is a fail, never a pass
        tmp = tempfile.mkdtemp(prefix="eqcheck-")
        try:
            try:
                rc, tail = run_bounded(chk["argv"], cwd, check_env(tmp), timeout)
            except OSError as exc:
                rc, tail = 127, ("stack-eq-check: cannot run %s: %s\n" % (chk["argv"][0], exc.strerror)).encode()
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        if rc is not None and rc < 0:
            rc = 128 - rc
        sys.stdout.write(P.render_check_trailer(a["run"], a["cand"], rnd, rc, rc is None, tail) + "\n")
        sys.stdout.flush()
        return 124 if rc is None else rc
    except Refused as exc:
        sys.stderr.write("stack-eq-check: %s\n" % exc)
        return exc.code


def main(argv):
    if len(argv) >= 2 and argv[1] == "--eq-executor":
        return executor(argv[2:])
    if len(argv) >= 2 and argv[1] == "--eq-check-runner":
        return check_runner(argv[2:])
    sys.stderr.write("eq_cli: run through bin/stack-eq or bin/stack-eq-check\n")
    return EXIT_USAGE


if __name__ == "__main__":
    sys.exit(main(sys.argv))

