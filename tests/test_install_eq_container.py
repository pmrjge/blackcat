"""install.sh --with-eq-container: step 10b (lib/eq-container, the isolation images run with Apple `container`) and step
10c (lib/eq-wall, the WALL: the default-deny host-access broker and its ONE tunnel). The options and their usage errors,
the dry run, stack.env (non-clobbering; values quoted or refused), the manifest keys eq_container and eq_wall, the X7
default (on only for a positive lib/eq-wall/REVIEW of these bytes AND the default-deny policy, checked before any
directory is made), the WALL's directories and refusals, idempotency, --restore, the rendered deny rules, and the
doctor.sh sections "Container isolation (eq-container)" and "WALL (eq-wall)".

Hermetic: install.sh runs from a scratch copy of the repo (test_install_state._scratch_repo) into a scratch HOME,
XDG_STATE_HOME, XDG_CACHE_HOME and config dir, with --no-mcp --no-plugins --no-deps --no-profile, on a PATH without
/usr/local/bin (where the real `container` lives). The driver is a STUB committed into the scratch repo (it writes what
a run of eq-container.sh leaves behind: status.env, image.env, results/tunnel.*.env, by knob); one case runs the real
driver against the fake CLI (tests/fake-container/container) with its services down. EQ_CONTAINER_BIN always names
the fake (or nothing), so neither the driver nor doctor.sh can reach the real CLI. The broker runs only its own
checks (check-policy, config-hash, check) on the stack's Python.

Run: /Users/pmrj/.claude/venvs/tools/bin/python -m pytest -q tests/test_install_eq_container.py
"""
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_install_state as TS  # noqa: E402  (_scratch_repo, _run_install)

ROOT = Path(TS.ROOT)
FAKE_CONTAINER = ROOT / "tests" / "fake-container" / "container"
needs_git = pytest.mark.skipif(not (ROOT / ".git").exists(), reason="needs the stack's git checkout")
BASE = ("--yes", "--with-eq-container")
DA = "sha256:" + "a" * 64
DB = "sha256:" + "b" * 64
PF = "eq.invalid/eq-min:4.34.1-arm64"
PY = "eq.invalid/eq-py-min:4.34.1-arm64"
NOT_POSITIVE = "POSITIVE=0\nSECURITY_AUDITOR_REF=\nOPEN_HIGH_CRITICAL=\nCODE_REVIEWER_REF=\nTESTS_REF=\n"

# what a run of lib/eq-container/eq-container.sh leaves behind, by knob (committed over the driver in the scratch
# repo; install_smoke.sh section 21 uses the same file)
STUB_DRIVER = (ROOT / "tests" / "fake-container" / "eq-container-stub.sh").read_text()


def commit(repo: Path, rel: str, text: str):
    """Change one file of a scratch repo and commit it (install.sh installs what HEAD holds)."""
    p = Path(repo) / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)
    git = ["git", "-c", "core.hooksPath=/dev/null", "-c", "commit.gpgsign=false", "-c", "user.name=t",
           "-c", "user.email=t@example.invalid", "-C", str(repo)]
    subprocess.run(git + ["add", "-A"], check=True, stdin=subprocess.DEVNULL)
    subprocess.run(git + ["commit", "-q", "-m", "test: " + rel], check=True, stdin=subprocess.DEVNULL,
                   stdout=subprocess.DEVNULL)


def kv(path: Path) -> dict:
    p = Path(path)
    if not p.is_file():
        return {}
    return dict(ln.split("=", 1) for ln in p.read_text().splitlines() if "=" in ln and not ln.startswith("#"))


def mode(p: Path) -> int:
    return stat.S_IMODE(os.lstat(p).st_mode)


def section(out: str, name: str) -> str:
    """The lines of one doctor.sh section ("== name ..." up to the next "== ")."""
    m = re.search(r"^== %s.*?$(.*?)(?=^== |\Z)" % re.escape(name), out, re.S | re.M)
    assert m, out[-3000:]
    return m.group(1)


class Box:
    """One scratch install target: HOME (XDG state and cache under it), config dir, the fakes, a scratch repo whose
    lib/eq-container/eq-container.sh is the stub (stub=False keeps the real driver)."""

    def __init__(self, tmp: Path, stub=True, cache: Path = None):
        self.t = Path(tmp)
        self.home = self.t / "home"
        self.home.mkdir(parents=True, exist_ok=True)
        self.conf = self.home / ".claude"
        self.cache = Path(cache) if cache else self.home / ".cache"
        self.repo = Path(TS._scratch_repo(str(self.t / "repo")))
        if stub:
            commit(self.repo, "lib/eq-container/eq-container.sh", STUB_DRIVER)
        self.fakes = self.t / "fakes"
        self.fakes.mkdir(exist_ok=True)
        shutil.copyfile(FAKE_CONTAINER, self.fakes / "container")
        (self.fakes / "container").chmod(0o755)
        self.tools = self.t / "tools"            # uv only: the installer links uv's Python 3.13 as stack-python
        self.tools.mkdir(exist_ok=True)
        uv = shutil.which("uv")
        if not uv:
            pytest.skip("needs uv (the installer links uv's managed Python 3.13 as stack-python)")
        (self.tools / "uv").symlink_to(uv)
        self.slog = self.t / "stub.log"
        self.clog = self.t / "container.log"

    @property
    def state(self) -> Path:
        return self.home / ".local" / "state" / "claude-agent-stack"

    @property
    def eqs(self) -> Path:
        return self.state / "eq-container"

    @property
    def wst(self) -> Path:
        return self.state / "eq-wall"

    @property
    def tun(self) -> Path:
        return self.cache / "claude-agent-stack" / "eq-tunnel"

    def env(self, **extra) -> dict:
        shim = self.home / "shim"   # _run_install's mktemp shim
        path = os.pathsep.join(map(str, (self.fakes, self.repo / "tests" / "fake-claude", shim, self.tools,
                                         "/usr/bin", "/bin", "/usr/sbin", "/sbin")))
        e = {"PATH": path, "XDG_CACHE_HOME": str(self.cache), "EQ_CONTAINER_BIN": str(self.fakes / "container"),
             "EQ_FAKE_CONTAINER_LOG": str(self.clog), "EQ_FAKE_CONTAINER_DIGEST": DA, "EQ_HOST_ARCH": "arm64",
             "EQ_STUB_LOG": str(self.slog), "LC_ALL": "C"}
        e.update({k: (None if v is None else str(v)) for k, v in extra.items()})
        return {k: v for k, v in e.items() if v is not None}

    def install(self, *extra, ok=True, argv=None, **env):
        p = TS._run_install(str(self.repo), str(self.home), str(self.conf), *extra, env_extra=self.env(**env), argv=argv)
        if ok:
            assert p.returncode == 0, (p.stdout[-4000:], p.stderr[-3000:])
        return p

    def stub_calls(self) -> list:
        if not self.slog.exists():
            return []
        return [ln.split("\x1f", 1) for ln in self.slog.read_text().splitlines()]

    def manifest(self) -> dict:
        p = self.conf / ".stack-manifest.json"
        return json.loads(p.read_text()) if p.exists() else {}

    def wall(self) -> dict:
        return self.manifest().get("eq_wall", {})

    def stack_env(self) -> str:
        p = self.conf / "stack.env"
        return p.read_text() if p.exists() else ""

    def env_line(self, key: str):
        """The raw value of the last KEY= line in stack.env (quotes kept), None when absent."""
        val = None
        for ln in self.stack_env().splitlines():
            m = re.match(r"^\s*(?:export\s+)?%s=(.*)$" % key, ln)
            if m:
                val = m.group(1).strip()
        return val

    def doctor(self, **env) -> str:
        e = {k: v for k, v in os.environ.items() if not k.startswith(("STACK_", "CLAUDE_", "XDG_", "EQ_"))}
        e.update(HOME=str(self.home), CLAUDE_CONFIG_DIR=str(self.conf),
                 XDG_STATE_HOME=str(self.home / ".local" / "state"), TMPDIR=str(self.home / "tmp"))
        e.update(self.env(**env))
        # no uv on this PATH: doctor.sh's image-model check (a catalog lookup) stays offline
        e["PATH"] = os.pathsep.join(map(str, (self.fakes, "/usr/bin", "/bin", "/usr/sbin", "/sbin")))
        p = subprocess.run(["bash", str(self.conf / "bin" / "doctor.sh")], env=e, stdin=subprocess.DEVNULL,
                           capture_output=True, text=True, timeout=600, check=False)
        return p.stdout + p.stderr


# ---------------------------------------------------------------------------------------------- options
def _bare(tmp_path, *args, **env):
    """install.sh from the repo itself: option errors stop before anything is read or written."""
    home = tmp_path / "home"
    home.mkdir()
    e = {"PATH": "/usr/bin:/bin", "HOME": str(home), "CLAUDE_CONFIG_DIR": str(home / ".claude"), "TMPDIR": str(tmp_path)}
    e.update(env)
    p = subprocess.run([str(ROOT / "install.sh"), *args], env=e, stdin=subprocess.DEVNULL, capture_output=True,
                       text=True, timeout=60, check=False)
    return p, home


@pytest.mark.parametrize("args, env, want", [
    (["--eq-container-profiles=core,node"], {}, "--eq-container-profiles works only with --with-eq-container"),
    (["--eq-container-profiles", "core"], {}, "--eq-container-profiles works only with --with-eq-container"),
    (["--with-eq-container", "--eq-container-profiles", "core;rm"], {}, "--eq-container-profiles needs a comma list"),
    (["--with-eq-container", "--eq-container-profiles=core node"], {}, "--eq-container-profiles needs a comma list"),
    (["--with-eq-container", "--eq-container-profiles=$(id)"], {}, "--eq-container-profiles needs a comma list"),
    (["--with-eq-container", "--eq-container-profiles"], {}, "--eq-container-profiles needs a comma list"),
    (["--with-eq-container", "--eq-container-profiles", "--yes"], {}, "--eq-container-profiles needs a comma list"),
    (["--with-eq-container", "--eq-container-profiles=node"], {"STACK_EQ_CONTAINER_SET": "full"},
     "--eq-container-profiles and STACK_EQ_CONTAINER_SET exclude each other"),
    (["--no-eq-broker"], {}, "--no-eq-broker/--with-eq-broker work only with --with-eq-container"),
    (["--with-eq-broker"], {}, "--no-eq-broker/--with-eq-broker work only with --with-eq-container"),
    (["--with-eq-container", "--no-eq-broker", "--with-eq-broker"], {}, "--no-eq-broker and --with-eq-broker contradict"),
    (["--with-eq-container", "--with-eq-broker", "--no-eq-broker"], {}, "--no-eq-broker and --with-eq-broker contradict"),
])
def test_option_errors(tmp_path, args, env, want):
    p, home = _bare(tmp_path, *args, **env)
    assert p.returncode == 2, (p.returncode, p.stdout[-500:], p.stderr[-500:])
    assert want in p.stdout + p.stderr
    assert not any(home.iterdir()), sorted(os.listdir(home))
    assert sorted(os.listdir(tmp_path)) == ["home"]


def test_help_lists_the_options():
    out = subprocess.run([str(ROOT / "install.sh"), "--help"], capture_output=True, text=True, timeout=60,
                         env={"PATH": "/usr/bin:/bin", "HOME": "/nonexistent"}).stdout
    for opt in ("--with-eq-container", "--eq-container-profiles=LIST", "--no-eq-broker", "--with-eq-broker"):
        assert opt in out, opt
    assert "docker" not in out.lower()


def test_managed_settings_render_the_tunnel_root(tmp_path):
    """--print-managed-settings: the WALL's deny rules come out rendered (no __EQ_TUNNEL__ left), at the
    XDG_CACHE_HOME tunnel root and at the ~/.cache default."""
    home = tmp_path / "home"
    home.mkdir()
    cache = tmp_path / "xc"
    e = {"PATH": "/usr/bin:/bin", "HOME": str(home), "CLAUDE_CONFIG_DIR": str(home / ".claude"),
         "TMPDIR": str(tmp_path), "XDG_CACHE_HOME": str(cache), "XDG_STATE_HOME": str(tmp_path / "xs")}
    p = subprocess.run([str(ROOT / "install.sh"), "--print-managed-settings"], env=e, stdin=subprocess.DEVNULL,
                       capture_output=True, text=True, timeout=60, check=False)
    assert p.returncode == 0, p.stderr[-1000:]
    assert "__EQ_TUNNEL__" not in p.stdout and "__STACK_STATE__" not in p.stdout
    s = json.loads(p.stdout)
    tun = "%s/claude-agent-stack/eq-tunnel" % cache
    deny = set(s["permissions"]["deny"])
    for root in ("/" + tun, "/%s/claude-agent-stack/eq-wall" % (tmp_path / "xs"), "~/.cache/claude-agent-stack/eq-tunnel"):
        assert {"Read(%s/**)" % root, "Edit(%s/**)" % root} <= deny, root
    assert tun in s["sandbox"]["filesystem"]["denyWrite"]


# ------------------------------------------------------------------------------------------ the dry run
@needs_git
def test_dry_run_prints_would_and_creates_nothing(tmp_path):
    b = Box(tmp_path)
    b.install("--yes")                                     # a first install: the config dir exists
    assert b.stub_calls() == [] and "eq_container" not in b.manifest() and "eq_wall" not in b.manifest()
    env0, man0 = b.stack_env(), (b.conf / ".stack-manifest.json").read_bytes()
    p = b.install("--dry-run", *BASE)
    out = p.stdout
    assert "would: bash lib/eq-container/eq-container.sh install --profiles core --yes" in out, out[-3000:]
    assert "eq-container: dry run (stub)" in out
    assert "would: WALL on (lib/eq-wall/REVIEW positive; default: on" in out
    assert [c[1] for c in b.stub_calls()] == ["install --profiles core --yes --dry-run"]
    p = b.install("--dry-run", *BASE, "--eq-container-profiles=core,node", "--no-eq-broker")
    assert "would: bash lib/eq-container/eq-container.sh install --profiles core,node --yes" in p.stdout
    assert "would: WALL off (--no-eq-broker; default: on" in p.stdout
    p = b.install("--dry-run", *BASE, STACK_EQ_CONTAINER_SET="full")
    assert "would: bash lib/eq-container/eq-container.sh install --set full --yes" in p.stdout
    p = b.install("--dry-run", *BASE, EQ_STUB_DRY_RC=10)
    assert "container isolation would be skipped" in p.stdout
    # bad knobs: the step stops before the driver
    n = len(b.stub_calls())
    p = b.install("--dry-run", *BASE, STACK_EQ_CONTAINER_SET="huge")
    assert "! STACK_EQ_CONTAINER_SET must be min or full: container isolation skipped" in p.stdout
    p = b.install("--dry-run", *BASE, STACK_EQ_CONTAINER_PROFILES="core;touch x")
    assert "! STACK_EQ_CONTAINER_PROFILES must be a comma list" in p.stdout
    assert len(b.stub_calls()) == n
    for d in (b.eqs, b.wst, b.tun):
        assert not d.exists(), d
    assert b.stack_env() == env0 and (b.conf / ".stack-manifest.json").read_bytes() == man0


# ------------------------------------------------------------------------- the happy path, shared
@pytest.fixture(scope="module")
def happy(tmp_path_factory):
    """A plain install, then --with-eq-container (stub driver: verified, tunnel probe PASS; the shipped REVIEW)."""
    if not (ROOT / ".git").exists():
        pytest.skip("needs the stack's git checkout")
    b = Box(tmp_path_factory.mktemp("happy"))
    b.install("--yes")
    b.pre_env, b.pre_manifest = b.stack_env(), b.manifest()
    b.out = b.install(*BASE).stdout
    return b


def test_happy_container_step(happy):
    b = happy
    assert "10b/11 Container isolation (--with-eq-container)" in b.out
    assert "+ container isolation verified: EQ_IMAGE=%s@%s" % (PF, DA) in b.out, b.out[-3000:]
    # the driver ran once from the reviewed snapshot (not the repo), with the state dir the installer made 0700
    (call,) = [c for c in b.stub_calls() if c[1].startswith("install")]
    assert call[1] == "install --profiles core --yes"
    assert not call[0].startswith(str(b.repo)), call[0]
    assert [c[1] for c in b.stub_calls() if c[1] == "print-env"] == ["print-env"]
    assert mode(b.eqs) == 0o700
    m = b.manifest()["eq_container"]
    st = kv(b.eqs / "status.env")
    assert m["status"] == "ok" and m["why"] == st["EQ_CONTAINER_STATUS_WHY"] and m["at"] == st["EQ_CONTAINER_STATUS_AT"]
    assert m["profiles"] == "core" and m["probe"] == "PASS" and m["pins_sha256"] == "7" * 64
    assert m["image_refs"] == {"pf": "%s@%s" % (PF, DA), "cp": "%s@%s" % (PY, DA), "cr": "%s@%s" % (PY, DA)}
    assert m["images"] == {"min_both": DA, "min_py": DA}
    assert m["state_dir"] == str(b.eqs) and m["env_image"] == "%s@%s" % (PF, DA)
    assert b.env_line("EQ_ISOLATION") == "container" and b.env_line("EQ_IMAGE") == "%s@%s" % (PF, DA)
    assert mode(b.conf / "stack.env") == 0o600


def test_happy_wall_on(happy):
    b = happy
    assert "10c/11 WALL (host-access broker + tunnel)" in b.out and "+ WALL on" in b.out, b.out[-3000:]
    w = b.wall()
    assert w["status"] == "on" and w["default"] == "on" and w["flag"] == "default", w
    assert w["tunnel_dir"] == str(b.tun) and w["state_dir"] == str(b.wst) and w["wall_dir"] == str(b.repo / "lib" / "eq-wall")
    assert w["tunnel_probe"] == "PASS" and re.fullmatch(r"[0-9a-f]{64}", w["config_sha256"])
    for k, f in (("broker_sha256", "eq_wall.py"), ("client_sha256", "eq_wall_client.py"),
                 ("policy_sha256", "policy.default.toml")):
        assert w[k] == hashlib.sha256((b.repo / "lib" / "eq-wall" / f).read_bytes()).hexdigest(), k
    env = {"EQ_WALL": "on", "EQ_TUNNEL_DIR": str(b.tun), "EQ_WALL_STATE_DIR": str(b.wst),
           "EQ_WALL_DIR": str(b.repo / "lib" / "eq-wall")}
    assert w["env"] == env and {k: b.env_line(k) for k in env} == env
    # the single tunnel: a private, empty root (channels are created per call by the harness)
    assert b.tun.is_dir() and not b.tun.is_symlink() and mode(b.tun) == 0o700 and list(b.tun.iterdir()) == []
    assert mode(b.wst) == 0o700 and mode(b.wst / "status.env") == 0o600
    st = kv(b.wst / "status.env")
    assert st["EQ_WALL_STATUS"] == "on" and st["EQ_WALL_CONFIG_SHA256"] == w["config_sha256"]
    # the user's stores are never created by the install
    assert not (b.wst / "verdicts.jsonl").exists() and not (b.wst / "consents.jsonl").exists()


def test_happy_rendered_deny_rules(happy):
    """settings.json as installed: Read+Edit denies on the rendered tunnel root, the ~/.cache default and the WALL
    state; sandbox denyWrite on the tunnel root (Write() rules are never consulted, so none are relied on)."""
    s = json.loads((happy.conf / "settings.json").read_text())
    deny = set(s["permissions"]["deny"])
    for root in ("/" + str(happy.tun), "/%s/eq-wall" % happy.state, "~/.cache/claude-agent-stack/eq-tunnel"):
        assert {"Read(%s/**)" % root, "Edit(%s/**)" % root} <= deny, root
    dw = s["sandbox"]["filesystem"]["denyWrite"]
    assert str(happy.tun) in dw and str(happy.state) in dw
    assert "__EQ_TUNNEL__" not in json.dumps(s)


def test_happy_doctor(happy):
    b = happy
    out = b.doctor()
    d = section(out, "Container isolation (eq-container)")
    for row in ("ok    eq-container: verified 2026-10-05T00:00:00Z (set profiles, probe PASS)",
                "ok    eq-container profiles: core",
                "ok    eq-container image %s (aaaaaaaaaaaa) present" % PF,
                "ok    eq-container image %s (aaaaaaaaaaaa) present" % PY):
        assert row in d, (row, d)
    assert "FAIL" not in d and "WARN" not in d, d
    w = section(out, "WALL (eq-wall)")
    for row in ("ok    WALL tunnel root %s 0700" % b.tun, "ok    WALL state dir %s 0700" % b.wst, "ok    WALL files 0600",
                "ok    WALL tunnel holds no special files", "ok    WALL up: roots, policy (default deny), stores intact",
                "ok    WALL config %s" % b.wall()["config_sha256"][:12], "ok    WALL tunnel probe PASS at install",
                "ok    WALL stores denied to agent file tools", "ok    WALL tunnel root denied to agent file tools"):
        assert row in w, (row, w)
    assert "FAIL" not in w and "WARN" not in w, w
    # the CLI asked only read-only questions
    calls = [ln.split("\x1f")[:2] for ln in b.clog.read_text().splitlines()]
    assert {tuple(c) for c in calls} <= {("system", "status"), ("image", "inspect")}, calls


def test_happy_doctor_digest_mismatch_and_services_down(happy):
    d = section(happy.doctor(EQ_FAKE_CONTAINER_DIGEST=DB), "Container isolation (eq-container)")
    assert "FAIL  eq-container image %s is not the recorded aaaaaaaaaaaa (missing, rebuilt or retagged)" % PF in d, d
    d = section(happy.doctor(EQ_FAKE_CONTAINER_DOWN=1), "Container isolation (eq-container)")
    assert "WARN  eq-container: the container services are not running, images not checked" in d and "FAIL" not in d, d
    d = section(happy.doctor(EQ_CONTAINER_BIN="/nonexistent/container"), "Container isolation (eq-container)")
    assert "WARN  eq-container: the container CLI is not installed, images not checked" in d, d


def test_second_install_is_idempotent(happy):
    b = happy
    env0, man0, wst0 = b.stack_env(), b.manifest(), (b.wst / "status.env").read_bytes()
    out = b.install(*BASE).stdout
    assert "+ container isolation verified" in out and "+ WALL on" in out
    assert b.stack_env() == env0 and b.manifest() == man0 and (b.wst / "status.env").read_bytes() == wst0


def test_plain_install_keeps_the_keys(happy):
    b = happy
    rec = {k: b.manifest()[k] for k in ("eq_container", "eq_wall")}
    env0 = b.stack_env()
    out = b.install("--yes").stdout
    assert "10b/11" not in out and "10c/11" not in out
    assert {k: b.manifest()[k] for k in rec} == rec and b.stack_env() == env0


def test_restore_puts_back_stack_env_and_manifest_but_not_the_state(happy):
    """Last of the module: --restore undoes the latest install (a --with-eq-container run that changed stack.env); the
    images' records and the WALL's state stay, and the output names them."""
    b = happy
    env = "\n".join(ln for ln in b.stack_env().splitlines() if not ln.startswith(("EQ_IMAGE=", "EQ_TUNNEL_DIR="))) + "\n"
    (b.conf / "stack.env").write_text(env)
    before_env, before_man = b.stack_env(), b.manifest()
    b.install(*BASE)
    assert b.env_line("EQ_IMAGE") == "%s@%s" % (PF, DA) and b.env_line("EQ_TUNNEL_DIR") == str(b.tun)
    p = b.install(argv=["--restore"])
    assert b.stack_env() == before_env and b.manifest() == before_man
    assert (b.eqs / "status.env").exists() and (b.wst / "status.env").exists() and b.tun.is_dir()
    assert "eq-container.sh uninstall --yes [--purge]" in p.stdout, p.stdout[-2000:]
    assert "not restored: the WALL's state (%s" % b.wst in p.stdout


# ------------------------------------------------------------------------------- skips and failures
@needs_git
def test_driver_skip_and_unresolved_pin_are_warnings(tmp_path):
    b = Box(tmp_path)
    p = b.install(*BASE, EQ_STUB_RC=10)
    assert "! container isolation skipped (not an error)" in p.stdout, p.stdout[-3000:]
    assert b.manifest()["eq_container"]["status"] == "skipped" and b.env_line("EQ_ISOLATION") is None
    w = b.wall()
    assert w["status"] == "skipped" and w["why"] == "eq-container is not installed", w
    assert not b.tun.exists() and b.env_line("EQ_WALL") is None             # skipped: stack.env unchanged
    assert "print-env" not in [c[1] for c in b.stub_calls()]
    p = b.install(*BASE, EQ_STUB_RC=13)
    assert "a pin in lib/eq-container (PINS or TOOLS.toml) is still a placeholder" in p.stdout
    m = b.manifest()["eq_container"]
    assert m["status"] == "failed" and m["why"] == "stub failed", m
    assert (b.conf / "settings.json").is_file() and "Done. Next:" in p.stdout
    assert b.env_line("EQ_ISOLATION") is None


@needs_git
def test_real_driver_with_services_down_is_a_skip(tmp_path):
    """The real eq-container.sh (no stub) against the fake CLI whose services are down: exit 10, a skip; nothing is
    built or run, and the WALL is skipped with it."""
    b = Box(tmp_path, stub=False)
    p = b.install(*BASE, EQ_FAKE_CONTAINER_DOWN=1)
    assert "the container services are not running" in p.stdout + p.stderr, p.stdout[-3000:]
    m = b.manifest()["eq_container"]
    assert m["status"] == "skipped" and "services" in m["why"], m
    assert kv(b.eqs / "status.env")["EQ_CONTAINER_STATUS"] == "skipped"
    calls = [ln.split("\x1f") for ln in b.clog.read_text().splitlines()]
    assert calls and all(c[:2] == ["system", "status"] for c in calls), calls
    assert b.wall()["status"] == "skipped" and not b.tun.exists()


@needs_git
def test_print_env_output_is_validated_before_stack_env(tmp_path):
    """Only EQ_ISOLATION=container and an EQ_IMAGE of the form eq.invalid/NAME:TAG@sha256:<64 hex> reach stack.env."""
    b = Box(tmp_path)
    for knob in ({"EQ_STUB_PRINT_IMAGE": "eq.invalid/eq-min:4.34.1-arm64@sha256:" + "a" * 63},
                 {"EQ_STUB_PRINT_IMAGE": "docker.io/eq-min:4.34.1-arm64@" + DA},
                 {"EQ_STUB_PRINT_IMAGE": "eq.invalid/eq min:4@" + DA},
                 {"EQ_STUB_PRINT_IMAGE": "eq.invalid/eq-min:4.34.1-arm64@%s$(touch /tmp/x)" % DA},
                 {"EQ_STUB_PRINT_IMAGE": "eq.invalid/eq-min:4.34.1-arm64@" + DA.upper()},
                 {"EQ_STUB_ISOLATION": "none"}):
        p = b.install(*BASE, "--no-eq-broker", **knob)
        assert "! eq-container print-env gave no EQ_ISOLATION=container / EQ_IMAGE=" in p.stdout, (knob, p.stdout[-2000:])
        assert b.env_line("EQ_ISOLATION") is None and b.env_line("EQ_IMAGE") is None, (knob, b.stack_env())
        assert b.manifest()["eq_container"]["env_image"] == ""


@needs_git
def test_stack_env_is_not_clobbered_and_paths_are_quoted(tmp_path):
    """A value you set stays (one note); a WALL path with a blank is written double-quoted; one stack.env cannot carry
    (a $) turns the WALL off before any of its directories is made."""
    b = Box(tmp_path, cache=tmp_path / "ca che")
    b.install("--yes")
    se = b.conf / "stack.env"
    se.write_text(se.read_text() + "\nEQ_ISOLATION=\nEQ_IMAGE=custom\n")
    se.chmod(0o600)
    old = se.read_text()
    p = b.install(*BASE)
    assert b.env_line("EQ_IMAGE") == "custom" and b.env_line("EQ_ISOLATION") == "container"
    assert "= stack.env keeps your EQ_IMAGE=custom" in p.stdout
    assert b.manifest()["eq_container"]["env_image"] == ""
    assert b.wall()["status"] == "on" and b.env_line("EQ_TUNNEL_DIR") == '"%s"' % b.tun
    assert mode(se) == 0o600
    backups = b.home / ".local" / "state" / "claude-agent-stack-backups"
    saved = [Path(r) / n for r, _d, fs in os.walk(backups) for n in fs if n == "stack.env"]
    assert any(s.read_text() == old for s in saved), saved
    # doctor reads the quoted path back
    w = section(b.doctor(XDG_CACHE_HOME=b.cache), "WALL (eq-wall)")
    assert "ok    WALL tunnel root %s 0700" % b.tun in w, w
    # a $ in the cache path: refused before the tunnel root is made
    bad = tmp_path / "c$HOME"
    p = b.install(*BASE, XDG_CACHE_HOME=bad)
    w = b.wall()
    assert w["status"] == "failed" and "stack.env cannot carry it" in w["why"], w
    assert not (bad / "claude-agent-stack" / "eq-tunnel").exists()
    assert b.env_line("EQ_WALL") == "off" and "WALL NOT set up" in p.stdout


# ----------------------------------------------------------------------------- the WALL: default and flags
@needs_git
def test_review_not_positive_and_the_flags(tmp_path):
    b = Box(tmp_path)
    commit(b.repo, "lib/eq-wall/REVIEW", NOT_POSITIVE)
    out = b.install(*BASE).stdout
    w = b.wall()
    assert w["status"] == "off" and w["why"] == "review not positive (opt-in: --with-eq-broker)" and w["default"] == "off", w
    assert "WALL off (review not positive" in out and not b.tun.exists()
    assert b.env_line("EQ_WALL") == "off" and b.env_line("EQ_TUNNEL_DIR") is None
    assert kv(b.wst / "status.env")["EQ_WALL_STATUS"] == "off"
    d = section(b.doctor(), "WALL (eq-wall)")
    assert "ok    WALL: off (review not positive (opt-in: --with-eq-broker))" in d, d
    # --with-eq-broker opts in despite the review
    b.install(*BASE, "--with-eq-broker")
    w = b.wall()
    assert w["status"] == "on" and w["flag"] == "on" and w["default"] == "off", w
    assert b.env_line("EQ_WALL") == "on" and mode(b.tun) == 0o700
    # --no-eq-broker turns it off again (the paths it wrote stay: they are harmless with EQ_WALL=off)
    b.install(*BASE, "--no-eq-broker")
    w = b.wall()
    assert w["status"] == "off" and w["why"] == "--no-eq-broker" and w["flag"] == "off", w
    assert b.env_line("EQ_WALL") == "off"


@needs_git
@pytest.mark.parametrize("review", [
    "", "POSITIVE=yes\n", NOT_POSITIVE.replace("POSITIVE=0", "POSITIVE=1"),
    "POSITIVE=1\nOPEN_HIGH_CRITICAL=1\nSECURITY_AUDITOR_REF=x\nCODE_REVIEWER_REF=x\nTESTS_REF=x\n",
    "BROKER_SHA256=" + "0" * 64,
])
def test_malformed_or_stale_review_is_off(tmp_path, review):
    b = Box(tmp_path)
    if review.startswith("BROKER_SHA256="):
        rv = (b.repo / "lib/eq-wall/REVIEW").read_text()
        review = re.sub(r"^BROKER_SHA256=.*$", review, rv, flags=re.M)
        want = "would: WALL off (review not positive for these bytes: lib/eq-wall/eq_wall.py changed"
    else:
        want = "would: WALL off (review not positive"
    commit(b.repo, "lib/eq-wall/REVIEW", review)
    p = b.install("--dry-run", *BASE)
    assert want in p.stdout, p.stdout[-2000:]


@needs_git
def test_x7_default_on_covers_the_default_deny_policy_only(tmp_path):
    """REVIEW positive and naming THIS policy's bytes, but the policy allows a kind: the WALL stays off by default, decided
    before any WALL directory is made; --with-eq-broker is the user's opt-in."""
    b = Box(tmp_path)
    polf = b.repo / "lib" / "eq-wall" / "policy.default.toml"
    pol = polf.read_text().replace("allowed = []", 'allowed = ["missing-tool"]', 1)
    assert pol != polf.read_text()
    commit(b.repo, "lib/eq-wall/policy.default.toml", pol)
    rv = (b.repo / "lib/eq-wall/REVIEW").read_text()
    commit(b.repo, "lib/eq-wall/REVIEW", re.sub(r"^POLICY_SHA256=.*$", "POLICY_SHA256=" + hashlib.sha256(
        pol.encode()).hexdigest(), rv, flags=re.M))
    p = b.install("--dry-run", *BASE)
    assert "would: WALL on (lib/eq-wall/REVIEW positive" in p.stdout     # the review alone says on ...
    out = b.install(*BASE).stdout
    w = b.wall()
    assert w["status"] == "off" and w["default"] == "on", w            # ... the policy check says off
    assert "the policy allows ['missing-tool']: default-on covers the default-deny policy only" in w["why"], w
    assert not b.tun.exists(), "the tunnel root was made before the X7 check"
    assert b.env_line("EQ_WALL") == "off" and "WALL off (the policy allows" in out
    b.install(*BASE, "--with-eq-broker")
    w = b.wall()
    assert w["status"] == "on" and w["flag"] == "on" and "policy: ['missing-tool']" in w["why"], w


@needs_git
def test_tunnel_probe_fail_or_missing_leaves_the_wall_off(tmp_path):
    b = Box(tmp_path)
    p = b.install(*BASE, EQ_STUB_RC=15, EQ_STUB_TUNNEL="FAIL")
    w = b.wall()
    assert w["status"] == "failed" and "tunnel probe FAIL (4 rows)" in w["why"] and w["tunnel_probe"] == "FAIL", w
    assert b.manifest()["eq_container"]["status"] == "failed" and "WALL NOT set up (tunnel probe FAIL" in p.stdout
    assert not b.tun.exists() and b.env_line("EQ_WALL") == "off"
    shutil.rmtree(b.eqs / "results")
    b.install(*BASE, EQ_STUB_TUNNEL="none")
    w = b.wall()
    assert w["status"] == "failed" and "tunnel probe missing" in w["why"] and w["tunnel_probe"] == "none", w
    assert b.env_line("EQ_WALL") == "off" and not b.tun.exists()
    # PASS rows for other image bytes do not count: the images were rebuilt (digest B) and the probe not rerun
    b.install(*BASE, EQ_STUB_DIGEST=DA)
    assert b.wall()["status"] == "on"
    b.install(*BASE, EQ_STUB_TUNNEL="none", EQ_STUB_DIGEST=DB)
    w = b.wall()
    assert w["status"] == "failed" and "tunnel probe missing" in w["why"], w
    assert b.env_line("EQ_WALL") == "off"


@needs_git
def test_unsafe_preexisting_dirs_are_refused(tmp_path):
    """A symlinked eq-container state dir: 10b refused before the driver runs. A symlinked tunnel root: the WALL fails
    and nothing is written or chmod-ed through the link. A real eq-wall dir of yours with mode 0755 is tightened."""
    b = Box(tmp_path)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    elsewhere.chmod(0o755)
    b.state.mkdir(parents=True)
    b.eqs.symlink_to(elsewhere)
    p = b.install(*BASE)
    assert "! container isolation skipped: its state dir was refused (%s is a symlink)" % b.eqs in p.stdout, p.stdout[-2000:]
    assert b.stub_calls() == [] and list(elsewhere.iterdir()) == [] and mode(elsewhere) == 0o755
    assert b.wall()["status"] == "skipped"
    b.eqs.unlink()
    b.tun.parent.mkdir(parents=True)
    b.tun.symlink_to(elsewhere)
    p = b.install(*BASE)
    w = b.wall()
    assert w["status"] == "failed" and "tunnel root refused" in w["why"] and "is a symlink" in w["why"], w
    assert list(elsewhere.iterdir()) == [] and mode(elsewhere) == 0o755
    assert b.env_line("EQ_WALL") == "off" and "WALL NOT set up" in p.stdout
    b.tun.unlink()
    b.wst.chmod(0o755)
    b.install(*BASE)
    assert b.wall()["status"] == "on" and mode(b.wst) == 0o700 and mode(b.tun) == 0o700


@needs_git
def test_doctor_not_set_up_and_states(tmp_path):
    b = Box(tmp_path)
    b.install("--yes")
    out = b.doctor()
    d = section(out, "Container isolation (eq-container)")
    assert "ok    eq-container: not installed (optional: ./install.sh --with-eq-container)" in d and "WARN" not in d, d
    assert "ok    WALL: not set up" in section(out, "WALL (eq-wall)")
    se = b.conf / "stack.env"
    se.write_text(se.read_text() + "EQ_ISOLATION=container\n")
    d = section(b.doctor(), "Container isolation (eq-container)")
    assert "WARN  EQ_ISOLATION=container is set in stack.env but eq-container is not installed" in d, d
    b.eqs.mkdir(parents=True)
    (b.eqs / "status.env").write_text("EQ_CONTAINER_STATUS=failed\nEQ_CONTAINER_STATUS_AT=T0\nEQ_CONTAINER_STATUS_WHY=w\n"
                                      "touch %s\n$(touch %s)\n" % (tmp_path / "sourced", tmp_path / "sourced"))
    (b.eqs / "results").mkdir()
    (b.eqs / "results" / "probe.x.env").write_text("PROBE_RESULT=FAIL\nPROBE_AT=T1\nPROBE_FAILS=2\nPROBE_IMAGE=%s\n" % PF)
    d = section(b.doctor(), "Container isolation (eq-container)")
    assert "WARN  eq-container: install failed at T0: w (logs: %s/logs)" % b.eqs in d, d
    assert "WARN  eq-container: probe FAIL at T1 (2 rows) for %s" % PF in d, d
    assert not (tmp_path / "sourced").exists()                          # state files are data, never sourced
