"""eq_isolation - W3 Level 2 for the runtime Equilibrium (docs/RUNTIME_EQUILIBRIUM.md 6.1 W3, 6.2):
public checks in Apple `container` VMs plus one lib/eq-wall broker per run under the reviewed default-deny
policy. Driven only by stack-eq (unsandboxed: Seatbelt cannot reach the container services).

A stdlib port of the harness's Isolation argv builder / run / kill / sweep
(dot-config/dot-equilibrium/harness/eq_harness.py:1606-2000) and Wall lifecycle (:2039-2275); lib/eq-wall/eq_wall.py runs as
is (its bytes are REVIEW-pinned, never edited). Fail closed everywhere: Level 2 is used only when the
installer recorded a verified --with-eq-container install (manifest `eq_container.status == ok`, a
digest-pinned image for the class, a PASSing tunnel probe for that image), the WALL is on (manifest
`eq_wall.status == on`) and the policy, broker and client bytes hash to the REVIEW pins below AND to
lib/eq-wall/REVIEW (a checkout whose REVIEW and bytes were both edited still fails the pins here, which
live in the config dir). Checks never get the tunnel: the broker runs default-deny for the audit record
only; nothing crosses the WALL.
"""
import contextlib
import hashlib
import json
import os
import re
import select
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import threading
import time
import uuid
import importlib.util

# lib/eq-wall/REVIEW (2026-10-05, positive review of the default-deny policy): a REVIEW update needs these
# lines updated in the same commit (tests/test_eq_cli.py asserts equality)
REVIEWED = {"POLICY_SHA256": "c0ca1aaa35e4d9239b41442e60542c257a1ab617552aa31eca8df9c62f61b087",
            "BROKER_SHA256": "bf73be2b5893eb877049fd4f98cb18c03e7de34b61d04db011e86d989e70eda7",
            "CLIENT_SHA256": "c5b456f3bbf85b629e0d20d1a853aabaa427751fbceff035120a6b7a85fe9792"}
WALL_FILES = {"POLICY_SHA256": "policy.default.toml", "BROKER_SHA256": "eq_wall.py",
              "CLIENT_SHA256": "eq_wall_client.py"}
LEVEL2_CLASSES = ("PF", "CP", "CR")

IMAGE_REF_RE = re.compile(r"(?:[a-z0-9][a-z0-9._-]*(?::[0-9]+)?/)*[a-z0-9][a-z0-9._-]*"
                          r":[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}@sha256:[0-9a-f]{64}\Z")
DIGEST_RE = re.compile(r"sha256:[0-9a-f]{64}\Z")
HEX64_RE = re.compile(r"[0-9a-f]{64}\Z")
INSPECT_DIGEST_PATHS = (("configuration", "descriptor", "digest"), ("id",))
SIZE_RE = re.compile(r"[1-9][0-9]{0,6}[KMGkmg]?\Z")
ENV_KEY_RE = re.compile(r"[A-Z_][A-Z0-9_]*\Z")
# lib/eq-container/lib.sh defaults (the harness's DEFAULT_FLAGS container_*): limits, tmpfs sizes, user
LIMITS = {"nproc": 512, "memory": "8G", "cpus": "2", "tmp_size": "2G", "work_size": "1G", "user": "10001:10001",
          "kill_timeout_s": 30, "orphan_grace_s": 300}
CTR_TMP = "/tmp"                     # inside the container: a private tmpfs
CTR_SRC = "/eqsrc"
CTR_EQ = "/eq"
CONTAINER_ENV = {"LANG": "C.UTF-8", "HOME": CTR_TMP, "TMPDIR": CTR_TMP, "UV_CACHE_DIR": CTR_TMP + "/uv-cache",
                 "UV_OFFLINE": "1", "UV_NO_CONFIG": "1", "UV_PYTHON_DOWNLOADS": "never"}
COPY_IN = 'while [ "$1" != -- ]; do cp -R "$1"/. "$2"/ || exit 1; shift 2; done; shift; exec "$@"'
HOME_SECRETS = (".ssh", ".aws", ".config", ".gnupg", ".docker", ".claude", ".kube", ".local", "Library", ".netrc",
                ".git-credentials", ".npmrc", ".pypirc")
HOST_SOCKETS = ("/var/run/docker.sock", "/private/var/run/docker.sock")
CONTAINER_BINS = ("/usr/local/bin/container", "/opt/homebrew/bin/container")
TAIL = 65536


class IsolationError(RuntimeError):
    """Level 2 unavailable or misconfigured: nothing runs (fail closed; never unisolated)."""


# ---------------------------------------------------------------- small helpers
def sha256_file(path):
    h = hashlib.sha256()
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    with os.fdopen(fd, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def kv_file(path):
    """KEY=value lines (the installer's eq_kv files), first value per key; {} when unreadable."""
    out = {}
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
        with os.fdopen(fd, "rb") as f:
            data = f.read(1 << 20)
    except OSError:
        return out
    for line in data.decode("utf-8", "replace").splitlines():
        m = re.match(r"([A-Z0-9_]+)=(.*)\Z", line)
        if m and m.group(1) not in out:
            out[m.group(1)] = m.group(2)
    return out


def review_value(text, key):
    m = re.search(r"(?m)^%s=([^\n#]*)" % re.escape(key), text)
    return m.group(1).strip() if m else ""


def minimal_env(**extra):
    """The harness's minimal_env with a fixed PATH: nothing of the caller's environment but HOME, TMPDIR and
    UV_CACHE_DIR reaches the container CLI or the broker (and nothing at all reaches a container)."""
    env = {"PATH": "/usr/bin:/bin:/usr/sbin:/sbin", "HOME": os.environ.get("HOME", ""), "LANG": "C.UTF-8"}
    for k in ("TMPDIR", "UV_CACHE_DIR"):
        if os.environ.get(k):
            env[k] = os.environ[k]
    env.update(extra)
    return env


def run_bounded(argv, cwd, env, timeout_s, keep=TAIL, stdin_data=None):
    """argv (shell=False) in its own session; the last `keep` bytes of merged stdout+stderr; the whole
    process group killed on exit or timeout. (exit code or None on timeout, tail bytes)."""
    p = subprocess.Popen(list(argv), cwd=cwd, env=dict(env),
                         stdin=subprocess.DEVNULL if stdin_data is None else subprocess.PIPE,
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT, shell=False, start_new_session=True,
                         close_fds=True)
    if stdin_data is not None and p.stdin is not None:
        with contextlib.suppress(OSError):
            p.stdin.write(stdin_data)
        with contextlib.suppress(OSError):
            p.stdin.close()
    buf = bytearray()

    def pump():
        while True:
            chunk = os.read(p.stdout.fileno(), 65536)
            if not chunk:
                break
            buf.extend(chunk)
            if len(buf) > keep:
                del buf[: len(buf) - keep]

    th = threading.Thread(target=pump, daemon=True)
    th.start()
    try:
        rc = p.wait(timeout=timeout_s)
    except subprocess.TimeoutExpired:
        rc = None
    finally:
        with contextlib.suppress(ProcessLookupError, PermissionError):
            os.killpg(p.pid, signal.SIGKILL)
        p.wait()
        th.join(5)
        with contextlib.suppress(OSError):
            p.stdout.close()
    return rc, bytes(buf)


def inspect_digest(out):
    try:
        data = json.loads(out)
    except ValueError:
        return None
    if not (isinstance(data, list) and len(data) == 1 and isinstance(data[0], dict)):
        return None
    found = set()
    for path in INSPECT_DIGEST_PATHS:
        v = data[0]
        for k in path:
            v = v.get(k) if isinstance(v, dict) else None
        if path == ("id",) and isinstance(v, str) and HEX64_RE.match(v):
            v = "sha256:" + v
        if isinstance(v, str) and DIGEST_RE.match(v):
            found.add(v)
    return found.pop() if len(found) == 1 else None


def list_rows(out):
    try:
        data = json.loads(out)
    except ValueError:
        return []
    rows = []
    for r in data if isinstance(data, list) else []:
        c = r.get("configuration") if isinstance(r, dict) else None
        if isinstance(c, dict) and isinstance(c.get("id"), str):
            lab = c.get("labels") if isinstance(c.get("labels"), dict) else {}
            rows.append((c["id"], {str(k): str(v) for k, v in lab.items()}))
    return rows


def _under(path, root):
    return path == root or path.startswith(root.rstrip("/") + "/")


# ---------------------------------------------------------------- Level 2 configuration (fail closed)
def container_bin(environ, unsafe_roots=()):
    """The container CLI: STACK_EQ_CONTAINER_BIN (an absolute executable outside every agent-writable
    root: the tests' fake CLI) or the installed CLI's fixed paths; never a PATH search."""
    want = environ.get("STACK_EQ_CONTAINER_BIN")
    cands = [want] if want else list(CONTAINER_BINS)
    for c in cands:
        if c and os.path.isabs(c) and os.path.isfile(c) and os.access(c, os.X_OK):
            real = os.path.realpath(c)
            if any(_under(real, os.path.realpath(r)) for r in unsafe_roots if r):
                raise IsolationError("container CLI %s lies in an agent-writable directory" % c)
            return c
    raise IsolationError("no container CLI (%s)" % ", ".join(cands))


def check_wall_bytes(wall_dir):
    """The REVIEW pins: the files' sha256 must equal both REVIEWED (here, config dir) and wall_dir/REVIEW
    (positive, no open high/critical finding). Returns {key: sha256}."""
    try:
        fd = os.open(os.path.join(wall_dir, "REVIEW"), os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
        with os.fdopen(fd, "rb") as f:
            review = f.read(1 << 16).decode("utf-8", "replace")
    except OSError:
        raise IsolationError("lib/eq-wall/REVIEW unreadable in %s" % wall_dir) from None
    if review_value(review, "POSITIVE") != "1" or review_value(review, "OPEN_HIGH_CRITICAL") != "0":
        raise IsolationError("lib/eq-wall/REVIEW is not positive")
    got = {}
    for key, name in WALL_FILES.items():
        try:
            h = sha256_file(os.path.join(wall_dir, name))
        except OSError:
            raise IsolationError("%s missing in %s" % (name, wall_dir)) from None
        if h != REVIEWED[key] or review_value(review, key) != REVIEWED[key]:
            raise IsolationError("%s sha256 %s differs from the reviewed %s (lib/eq-wall/REVIEW %s): refused"
                                 % (name, h[:12], REVIEWED[key][:12], key))
        got[key] = h
    return got


def tunnel_probe_passed(state_dir, image):
    """The installer's rule (install.sh eq_tunnel_check): some results/tunnel.*.env names this image's tag
    and digest with TUNNEL_RESULT=PASS, and none for it says otherwise."""
    tag, _, digest = image.rpartition("@")
    res = os.path.join(state_dir, "results")
    ok = None
    try:
        names = sorted(os.listdir(res))
    except OSError:
        return False
    for n in names:
        if not re.fullmatch(r"tunnel\.[A-Za-z0-9_.-]+\.env", n):
            continue
        kv = kv_file(os.path.join(res, n))
        if kv.get("TUNNEL_IMAGE") != tag or kv.get("TUNNEL_IMAGE_DIGEST") != digest:
            continue
        if kv.get("TUNNEL_RESULT") == "PASS":
            ok = True if ok is None else ok
        else:
            ok = False
    return ok is True


def level2_config(environ, config_dir, cls, unsafe_roots=()):
    """(cfg, None) when Level 2 can run class `cls`, else (None, reason). Reads only the config dir's
    manifest (installer records) and the files they name."""
    if cls not in LEVEL2_CLASSES:
        return None, "class %s runs no check in a container" % cls
    try:
        fd = os.open(os.path.join(config_dir, ".stack-manifest.json"), os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
        with os.fdopen(fd, "rb") as f:
            man = json.loads(f.read(16 << 20).decode("utf-8"))
    except (OSError, ValueError):
        return None, "no readable .stack-manifest.json"
    ec = man.get("eq_container") if isinstance(man, dict) else None
    ew = man.get("eq_wall") if isinstance(man, dict) else None
    if not isinstance(ec, dict) or ec.get("status") != "ok":
        return None, "--with-eq-container not installed and verified (manifest eq_container.status != ok)"
    if not isinstance(ew, dict) or ew.get("status") != "on":
        return None, "the WALL is not on (manifest eq_wall.status != on)"
    image = ((ec.get("image_refs") or {}) if isinstance(ec.get("image_refs"), dict) else {}).get(cls.lower())
    if not isinstance(image, str) or not IMAGE_REF_RE.match(image):
        return None, "no digest-pinned %s image (name:tag@sha256:<64 hex>)" % cls
    sdir = ec.get("state_dir")
    if not isinstance(sdir, str) or not os.path.isabs(sdir) or not tunnel_probe_passed(sdir, image):
        return None, "no PASSing tunnel probe receipt for %s" % image
    for k in ("tunnel_dir", "state_dir", "wall_dir"):
        if not isinstance(ew.get(k), str) or not os.path.isabs(ew[k]):
            return None, "manifest eq_wall.%s missing" % k
    try:
        hashes = check_wall_bytes(ew["wall_dir"])
        cli = container_bin(environ, unsafe_roots)
    except IsolationError as exc:
        return None, str(exc)
    return {"cls": cls, "image": image, "bin": cli, "wall_dir": ew["wall_dir"], "tunnel_dir": ew["tunnel_dir"],
            "wall_state": ew["state_dir"], "hashes": hashes, "limits": dict(LIMITS)}, None


# ---------------------------------------------------------------- the container backend
class Isolation:
    """Port of the harness's Isolation (container backend only): a fresh `container run --rm` per check
    with --network none, --read-only, --cap-drop ALL, --init, -m/-c, --ulimit nproc, a numeric user, a
    capped tmpfs /tmp and ONLY the listed bind mounts, all read-only (a rw dir is a capped tmpfs filled by
    a /bin/sh copy-in from its read-only bind at /eqsrc<ctr>); the image digest re-checked before and after
    every run; containers labelled with this invocation's id so a sweep removes only its own."""

    def __init__(self, cfg, forbidden=()):
        self.cfg = cfg
        self.bin = cfg["bin"]
        home = os.environ.get("HOME") or "/nonexistent-home"
        self.home = os.path.realpath(home)
        self.forbidden = [os.path.join(self.home, x) for x in HOME_SECRETS] + list(HOST_SOCKETS)
        self.forbidden += [os.path.realpath(f) for f in forbidden if f]
        lim = cfg["limits"]
        if not re.fullmatch(r"[0-9]+:[0-9]+", str(lim["user"])) or int(lim["nproc"]) < 1 or not all(
                SIZE_RE.match(str(lim[k])) for k in ("memory", "tmp_size", "work_size")) or not re.fullmatch(
                r"[1-9][0-9]?", str(lim["cpus"])):
            raise IsolationError("container limits malformed")
        self.inv = uuid.uuid4().hex
        self.foreign = []

    def client_env(self):
        env = minimal_env()
        env.update({k: v for k, v in os.environ.items() if k.startswith("EQ_FAKE_CONTAINER_")})
        return env

    def _cli(self, *args, timeout_s=60.0):
        rc, out = run_bounded([self.bin, *args], tempfile.gettempdir(), self.client_env(), timeout_s)
        return rc, out.decode("utf-8", "replace")

    def require_services(self, when=""):
        try:
            rc, out = self._cli("system", "status")
        except OSError as exc:
            raise IsolationError("container CLI failed to start: %s" % type(exc).__name__) from None
        if rc != 0:
            raise IsolationError("the container services are not reachable%s: %s" % (when, out.strip()[-300:]))

    def require_image(self, ref, when=""):
        tag, _, want = ref.rpartition("@")
        rc, out = self._cli("image", "inspect", tag)
        got = inspect_digest(out) if rc == 0 else None
        if got != want:
            raise IsolationError("container image %s%s: %s" % (
                tag, when, "digest %s, pinned %s" % (got, want) if got else "not present or digest unreadable"))

    def preflight(self):
        self.require_services()
        self.require_image(self.cfg["image"])

    def refuse_forbidden(self, h):
        if _under(self.home, h):
            raise IsolationError("refusing to mount %s: the home directory or an ancestor of it" % h)
        for f in self.forbidden:
            if _under(h, f) or _under(f, h):
                raise IsolationError("refusing to mount %s: it is or contains %s" % (h, f))

    def check_mount(self, host, ctr):
        h = os.path.realpath(host)
        for s, what in ((h, "host path"), (ctr, "container path")):
            if any(ch in s for ch in ":,=\n\r\0") or not s.startswith("/"):
                raise IsolationError("%s %r is not an absolute path free of ':' ',' '=' and controls" % (what, s))
        if ctr == "/" or ctr.startswith((CTR_TMP, CTR_SRC)) or ".." in ctr.split("/") or ctr == CTR_EQ or \
                ctr.startswith(CTR_EQ + "/"):
            raise IsolationError("container path %r not allowed" % ctr)
        if not (os.path.isdir(h) or os.path.isfile(h)):
            raise IsolationError("mount source %s does not exist" % h)
        self.refuse_forbidden(h)
        return h

    def isolate(self, argv, *, rw_dirs, ro_dirs, workdir, tmp, label=""):
        lim = self.cfg["limits"]
        image = self.cfg["image"]
        name = "eq-%s" % uuid.uuid4().hex
        cmd = [self.bin, "run", "--rm", "--name", name, "--label", "eq-harness=1", "--label", "eq-inv=%s" % self.inv,
               "--label", "eq-started=%d" % int(time.time())]
        if label:
            if not re.fullmatch(r"[A-Za-z0-9_.-]{1,128}", label):
                raise IsolationError("bad label %r" % label)
            cmd += ["--label", "eq-arm=%s" % label]
        cmd += ["--network", "none", "--read-only", "--cap-drop", "ALL", "--init", "-m", str(lim["memory"]),
                "-c", str(lim["cpus"]), "--ulimit", "nproc=%d" % int(lim["nproc"]), "--user", str(lim["user"]),
                "--tmpfs", "%s:size=%s,mode=1777" % (CTR_TMP, lim["tmp_size"])]
        for ctr, host in sorted(ro_dirs.items()):
            cmd += ["--mount", "type=bind,source=%s,target=%s,readonly" % (self.check_mount(host, ctr), ctr)]
        copy_in = []
        for ctr, host in sorted(rw_dirs.items()):
            cmd += ["--mount", "type=bind,source=%s,target=%s%s,readonly" % (self.check_mount(host, ctr), CTR_SRC, ctr),
                    "--tmpfs", "%s:size=%s,mode=1777" % (ctr, lim["work_size"])]
            copy_in += [CTR_SRC + ctr, ctr]
        cmd += ["-w", workdir]
        for k, v in sorted(CONTAINER_ENV.items()):
            cmd += ["-e", "%s=%s" % (k, v)]
        cmd.append(image.rpartition("@")[0])
        if copy_in:
            cmd += ["/bin/sh", "-c", COPY_IN, "eq-run", *copy_in, "--"]
        cmd += list(argv)
        return {"argv": cmd, "cwd": tmp, "env": self.client_env(), "name": name, "image": image}

    def run(self, call, timeout_s):
        self.require_image(call["image"], " before the run")
        rc = None
        try:
            rc, out = run_bounded(call["argv"], call["cwd"], call["env"], timeout_s)
        finally:
            if rc is None:
                self.kill(call["name"])
        if rc == 0:
            self.require_image(call["image"], " after the run")
        elif rc is not None:
            self.require_services(" during the run")
            self.require_image(call["image"], " during the run")
        return rc, out

    def kill(self, name):
        with contextlib.suppress(OSError, IsolationError):
            self._cli("kill", name, timeout_s=float(self.cfg["limits"]["kill_timeout_s"]))

    def sweep(self):
        """Remove this invocation's leftover containers; another invocation's only once stale."""
        rc, out = self._cli("list", "--all", "--format", "json")
        rows = list_rows(out) if rc == 0 else []
        ids = [cid for cid, lab in rows if lab.get("eq-harness") == "1" and lab.get("eq-inv") == self.inv
               and cid.startswith("eq-")]
        now, self.foreign = time.time(), []
        stale = 600 + float(self.cfg["limits"]["orphan_grace_s"])
        for cid, lab in rows:
            if lab.get("eq-harness") != "1" or lab.get("eq-inv") == self.inv or cid in ids:
                continue
            inv, started = lab.get("eq-inv", ""), lab.get("eq-started", "")
            if cid.startswith("eq-") and re.fullmatch(r"[0-9a-f]{32}", inv) and re.fullmatch(r"[0-9]{1,12}", started) \
                    and now - int(started) > stale:
                ids.append(cid)
            else:
                self.foreign.append(cid)
        if ids:
            self._cli("delete", "--force", *ids, timeout_s=float(self.cfg["limits"]["kill_timeout_s"]))
        return len(ids)


# ---------------------------------------------------------------- the WALL (one broker per run)
def load_wall_module(path, want_sha256):
    """eq_wall.py imported from the bytes whose sha256 was just checked (nothing else is executed)."""
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    with os.fdopen(fd, "rb") as f:
        data = f.read()
    if hashlib.sha256(data).hexdigest() != want_sha256:
        raise IsolationError("%s differs from the reviewed broker" % path)
    spec = importlib.util.spec_from_loader("eq_wall_frozen", loader=None)
    mod = importlib.util.module_from_spec(spec)
    mod.__file__ = path
    sys.modules["eq_wall_frozen"] = mod
    exec(compile(data, path, "exec"), mod.__dict__)  # noqa: S102 - the hashed bytes, nothing else
    return mod


class Wall:
    """One run's broker: the per-run policy copy (<store>/wall/policy.toml, a byte copy of the reviewed
    default-deny policy whose sha256 must equal REVIEWED), the frozen broker and client bytes, a fresh
    run id and nonce, the broker process (nonce on stdin, 'ready' within 60 s, its broker_start record's
    hashes equal to the reviewed ones), then stop: stdin closed, the nonce revealed, the audit chain
    verified; the record (config_sha256, audit head) goes into mediator.jsonl."""

    def __init__(self, cfg, store_wall_dir, python=None):
        self.cfg = cfg
        wd = cfg["wall_dir"]
        self.ew = load_wall_module(os.path.join(wd, "eq_wall.py"), REVIEWED["BROKER_SHA256"])
        self.broker_path = os.path.join(wd, "eq_wall.py")
        if sha256_file(os.path.join(wd, "eq_wall_client.py")) != REVIEWED["CLIENT_SHA256"]:
            raise IsolationError("eq_wall_client.py differs from the reviewed client")
        src = os.path.join(wd, "policy.default.toml")
        fd = os.open(src, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
        with os.fdopen(fd, "rb") as f:
            pol = f.read(1 << 20)
        if hashlib.sha256(pol).hexdigest() != REVIEWED["POLICY_SHA256"]:
            raise IsolationError("the WALL policy differs from the reviewed default-deny policy: refused")
        self.policy = os.path.join(store_wall_dir, "policy.toml")
        fd = os.open(self.policy, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
        with os.fdopen(fd, "wb") as f:
            f.write(pol)
        if sha256_file(self.policy) != REVIEWED["POLICY_SHA256"]:
            raise IsolationError("the per-run policy copy differs from the reviewed policy")
        self.config_sha256 = self.ew.config_hash(REVIEWED["POLICY_SHA256"], REVIEWED["BROKER_SHA256"],
                                                 REVIEWED["CLIENT_SHA256"])
        try:
            pol_obj = self.ew.load_policy(self.ew.Path(self.policy))
            self.tunnel_root, self.state = self.ew.check_roots(self.ew.Path(cfg["tunnel_dir"]),
                                                               self.ew.Path(cfg["wall_state"]), create=True)
        except self.ew.WallError as exc:
            raise IsolationError("WALL: %s" % exc) from None
        if pol_obj.kinds_allowed or pol_obj.tools or pol_obj.domains or pol_obj.fetch_command:
            raise IsolationError("the WALL policy allows a kind, tool or domain: only default-deny runs here")
        self.python = python or sys.executable
        self.proc = None
        self.run_id = self.nonce = None

    def start(self):
        self.run_id, self.nonce = uuid.uuid4().hex, os.urandom(32).hex()
        try:
            self.ew.prepare_run(self.tunnel_root, self.state, self.run_id)
        except self.ew.WallError as exc:
            raise IsolationError("WALL: %s" % exc) from None
        errp = os.path.join(str(self.state), "runs", self.run_id, "broker.stderr")
        efd = os.open(errp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
        err = os.fdopen(efd, "w")
        argv = [self.python, "-I", self.broker_path, "serve", "--state", str(self.state), "--tunnel-root",
                str(self.tunnel_root), "--run-id", self.run_id, "--policy", self.policy,
                "--verdicts", os.path.join(str(self.state), "verdicts.jsonl"),
                "--consents", os.path.join(str(self.state), "consents.jsonl")]
        self.proc = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=err, text=True,
                                     env=minimal_env(), start_new_session=True, close_fds=True, shell=False)
        err.close()
        self.proc.stdin.write(self.nonce + "\n")
        self.proc.stdin.flush()
        ready, _, _ = select.select([self.proc.stdout], [], [], 60)
        line = self.proc.stdout.readline() if ready else ""
        if "ready" not in line:
            self.proc.kill()
            self.proc.wait()
            with open(errp) as f:
                tail = f.read()[-300:]
            raise IsolationError("the WALL broker did not start: %s" % tail.strip())
        start = next((r for r in self.audit() if r.get("record") == "broker_start"), None)
        if start is None or (start.get("broker_sha256"), start.get("policy_sha256")) != (
                REVIEWED["BROKER_SHA256"], REVIEWED["POLICY_SHA256"]):
            self.proc.kill()
            self.proc.wait()
            raise IsolationError("the WALL broker that started is not the reviewed one")

    def audit(self):
        try:
            return self.ew.verify_audit(self.ew.Path(str(self.state)) / "audit" / ("%s.jsonl" % self.run_id))
        except self.ew.WallError as exc:
            raise IsolationError("WALL audit log: %s" % exc) from None

    def stop(self):
        if self.proc is None:
            return None
        with contextlib.suppress(OSError):
            self.proc.stdin.close()
        try:
            self.proc.wait(timeout=60)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            self.proc.wait(timeout=10)
        self.proc = None
        with contextlib.suppress(OSError):
            self.ew.reveal_nonce(self.state, self.run_id, self.nonce)
        recs = self.audit()
        decisions = [r for r in recs if r.get("record") == "decision"]
        return {"record": "wall", "wall_run_id": self.run_id, "config_sha256": self.config_sha256,
                "policy_sha256": REVIEWED["POLICY_SHA256"], "broker_sha256": REVIEWED["BROKER_SHA256"],
                "client_sha256": REVIEWED["CLIENT_SHA256"], "audit_records": len(recs),
                "audit_head": recs[-1]["record_sha256"] if recs else None,
                "requests": len(decisions), "approved": sum(1 for r in decisions if r.get("approved"))}


# ---------------------------------------------------------------- one run's container checks
def run_checks(cfg, *, store_wall_dir, copies, pristine, owned, argv, timeout_s, forbidden=(), tmp_parent=None):
    """Run the plan's check argv once per candidate copy in a fresh container. copies {i: host dir of
    checks/c<i>} (owned paths already removed), pristine: the pristine copy (read-only /fixture; each
    owned path also mounted read-only over /work/<rel>), argv words naming a pristine top-level file map
    to /fixture/<a>. Returns ({i: (exit or None, timed_out, tail bytes)}, wall record)."""
    iso = Isolation(cfg, forbidden)
    wall = Wall(cfg, store_wall_dir)
    mapped = []
    for a in argv:
        p = os.path.join(pristine, a)
        mapped.append("/fixture/%s" % a if "/" not in a and a not in (".", "..") and os.path.isfile(p)
                      and not os.path.islink(p) else a)
    ro_base = {"/fixture": pristine}
    for rel in owned:
        src = os.path.join(pristine, rel)
        if os.path.islink(src) or not (os.path.isdir(src) or os.path.isfile(src)):
            continue
        ro_base["/work/" + rel.strip("/")] = src
    results = {}
    iso.preflight()
    wall.start()
    try:
        for i in sorted(copies):
            tmp = tempfile.mkdtemp(prefix="eqc-", dir=tmp_parent)
            try:
                call = iso.isolate(mapped, rw_dirs={"/work": copies[i]}, ro_dirs=ro_base, workdir="/work",
                                   tmp=tmp, label="c%d" % i)
                rc, tail = iso.run(call, timeout_s)
                results[i] = (rc, rc is None, tail)
            finally:
                shutil.rmtree(tmp, ignore_errors=True)
    finally:
        with contextlib.suppress(IsolationError):
            iso.sweep()
        rec = wall.stop()
    return results, rec


def _is_private_dir(path):
    try:
        st = os.lstat(path)
    except OSError:
        return False
    return stat.S_ISDIR(st.st_mode) and st.st_uid == os.getuid() and not st.st_mode & 0o077
