"""Shared fixtures for the eq-docker tests (test_eq_docker.py, test_eq_docker_isolation.py, test_eq_docker_toolchains.py,
test_eq_docker_compose.py).

Hermetic: `docker` and `brew` are PATH shims (tests/fake-docker/docker, tests/fake-brew/brew) that log their argv and never talk to a
daemon, a network or Homebrew; HOME, TMPDIR and the state directory are temp directories; the scripts run under /bin/bash (3.2 on
macOS, as the installer does). EQ_DOCKER_LIB overrides the directory under test (default: ../lib/eq-docker), which is how the
"fails before the fix" runs point the suite at an older copy of the scripts.

Every run gets EQ_DOCKER_WAIT_S=0 (no wait for a daemon that is down: a test that wants the wait passes --wait-daemon) and
EQ_PROBE_D = a directory of wrappers around the two probe hooks this suite can prove against the fake docker (probe.d/20 and 30):
probe.d/50-tunnel.sh builds a tunnel, a listener and a sleeper on the host and is proven by the WALL tests, not here.

Run: uv run --with pytest --with pyyaml pytest -q tests
"""
import hashlib
import os
import re
import shutil
import stat
import subprocess
import tomllib
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
LIB = Path(os.environ.get("EQ_DOCKER_LIB") or HERE.parent / "lib" / "eq-docker")
FAKE_DOCKER = HERE / "fake-docker" / "docker"
FAKE_BREW = HERE / "fake-brew" / "brew"
BASH = "/bin/bash"

# A terminal, for the scripts under test: `test -t N` answers yes (eq-docker.sh asks with `test -t 0`; bash imports an exported
# function, which wins over the builtin). Same trick as tests/test_install_devtools.py.
TTY_FN_NAME = "BASH_FUNC_test%%"
TTY_FN = '() { if [ "$1" = -t ] && [ $# -eq 2 ]; then return 0; fi; builtin test "$@"; }'

IMAGE_ID_A = "sha256:" + "a" * 64
IMAGE_ID_B = "sha256:" + "b" * 64

# default tags of the manifest images (lib.sh eq_img_default_tag): the fake daemon and the records use them
IMAGE_TAGS = {
    "full": "eq-lean:4.34.1-arm64", "min-lean": "eq-lean-min:4.34.1-arm64", "min-py": "eq-py-min:4.34.1-arm64",
    "min-both": "eq-min:4.34.1-arm64", "dl-lean": "eq-lean-dl:4.34.1-arm64",
    "tc-node": "eq-node:arm64", "tc-rust": "eq-rust:arm64", "tc-go": "eq-go:arm64", "tc-julia": "eq-julia:arm64",
    "tc-haskell": "eq-haskell:arm64", "tc-jvm": "eq-jvm:arm64", "tc-pg": "eq-pg:arm64", "tc-mongo": "eq-mongo:arm64",
}
PROBE_HOOKS_UNDER_TEST = ("20-tools-manifest.sh", "30-internal-net.sh")


def mkexe(dst: Path, src: Path) -> Path:
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src, dst)
    dst.chmod(dst.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return dst


def vals(argv, flag):
    """Every value following `flag` in a docker argv (a list of strings)."""
    return [argv[i + 1] for i, a in enumerate(argv[:-1]) if a == flag]


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def san(tag: str) -> str:
    """The fake docker's file-name form of a tag."""
    return re.sub(r"[:/@]", "_", tag)


# ---------------------------------------------------------------------------------------------------------- manifest helpers
def load_manifest(path: Path) -> dict:
    """TOOLS.toml parsed by a real TOML parser: {"tool": [...], "image": [...], "profile": [...]}."""
    return tomllib.loads(Path(path).read_text())


def tool_block(text: str, name: str):
    """(start, end) character offsets of the [[tool]] table whose name is `name`."""
    for m in re.finditer(r"^\[\[tool\]\]\n(?:.*\n)*?(?=^\[\[|\Z)", text, re.M):
        if re.search(rf'^name = "{re.escape(name)}"$', m.group(0), re.M):
            return m.start(), m.end()
    raise KeyError(name)


def _toml_value(v):
    if isinstance(v, (list, tuple)):
        return "[" + ", ".join(f'"{x}"' for x in v) + "]"
    return f'"{v}"'


def set_tool(path: Path, name: str, **kv):
    """Rewrite (or add) keys of one [[tool]] table in a TOOLS.toml copy."""
    path = Path(path)
    text = path.read_text()
    s, e = tool_block(text, name)
    block = text[s:e]
    for k, v in kv.items():
        line = f"{k} = {_toml_value(v)}"
        if re.search(rf"^{k} = .*$", block, re.M):
            block = re.sub(rf"^{k} = .*$", lambda m: line, block, count=1, flags=re.M)
        else:
            block = block.rstrip("\n") + "\n" + line + "\n\n"
    path.write_text(text[:s] + block + text[e:])


def set_image(path: Path, name: str, **kv):
    path = Path(path)
    text = path.read_text()
    for m in re.finditer(r"^\[\[image\]\]\n(?:.*\n)*?(?=^\[\[|\Z)", text, re.M):
        if re.search(rf'^name = "{re.escape(name)}"$', m.group(0), re.M):
            block = m.group(0)
            for k, v in kv.items():
                line = f"{k} = {_toml_value(v)}"
                if re.search(rf"^{k} = .*$", block, re.M):
                    block = re.sub(rf"^{k} = .*$", lambda mm: line, block, count=1, flags=re.M)
                else:
                    block = block.rstrip("\n") + "\n" + line + "\n\n"
            path.write_text(text[:m.start()] + block + text[m.end():])
            return
    raise KeyError(name)


def fake_hex(seed: str) -> str:
    return sha256_hex(seed.encode())


def fixture_lib(tmp: Path, *, pin_distro=True, fill_all=False, busybox_sha=None, pin_busybox=True) -> Path:
    """A private copy of the directory under test whose distro-package tools (busybox, bash, perl, jq) carry made-up pins, as after
    `build.sh --resolve-tools --write-pin`, and whose PINS and Dockerfile.minimal carry a BUSYBOX_SHA256: the shipped files keep
    placeholders until a maintainer resolves them (nothing is invented there), so every test that must get past the pin checks builds
    from this copy. fill_all also fills every other PLACEHOLDER value (scala3, mongosh) with made-up ones."""
    work = Path(tmp) / "scripts"
    shutil.copytree(LIB, work, ignore=shutil.ignore_patterns(".state", "__pycache__"))
    bb = busybox_sha or fake_hex("busybox")
    # pin_busybox=False + pin_distro=False is the directory exactly as shipped (a copy, so scripts that `cd` into their own directory
    # never touch the tree under test)
    for f in ("PINS", "Dockerfile.minimal") if pin_busybox else ():
        p = work / f
        p.write_text(re.sub(r"^(ARG )?BUSYBOX_SHA256=.*$", lambda m: f"{m.group(1) or ''}BUSYBOX_SHA256={bb}", p.read_text(), flags=re.M))
    tf = work / "TOOLS.toml"
    if not tf.exists():
        return work
    if pin_distro:
        for t in ("busybox", "bash", "perl", "jq"):
            set_tool(tf, t, version="1.0-fixture", sha256=bb if t == "busybox" else fake_hex(t), checksum_source="fixture (test)")
    if fill_all:
        m = load_manifest(tf)
        for t in m["tool"]:
            ph = {k: v for k, v in t.items() if v == "PLACEHOLDER"}
            if not ph:
                continue
            fill = {"version": "1", "url": "https://example.invalid/x-{version}.tar.gz", "sha256": fake_hex(t["name"]), "archive": "tar.gz",
                    "linkage": "dynamic", "provenance": "prebuilt-upstream", "checksum_source": "fixture (test)"}
            set_tool(tf, t["name"], **{k: fill[k] for k in ph if k in fill})
    return work


def tsv_via_bash(lib: Path, manifest: Path) -> list:
    """What tools.sh (the awk reader every script uses) makes of a manifest: [(table, name, key, value)]."""
    r = subprocess.run([BASH, "-c", f'. "{lib}/tools.sh"; tm_load "{manifest}" || exit 3; printf "%s\\n" "$TM_TSV"'],
                       capture_output=True, text=True, check=False)
    assert r.returncode == 0, r.stderr
    return [tuple(ln.split("\t", 3)) for ln in r.stdout.splitlines() if ln]


def image_label(lib: Path, manifest: Path, image: str) -> str:
    """eq.tools.sha256 of an image: tm_image_hash from tools.sh."""
    r = subprocess.run([BASH, "-c", f'. "{lib}/tools.sh"; tm_load "{manifest}" || exit 3; tm_image_hash "{image}"'],
                       capture_output=True, text=True, check=False)
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


class Env:
    def __init__(self, tmp: Path):
        self.t = tmp
        self.home = tmp / "home"
        self.home.mkdir()
        self.shims = tmp / "shims"
        self.shims.mkdir()
        self.state = tmp / "state" / "eq-docker"          # named eq-docker: --purge only removes such a directory
        self.dstate = tmp / "dstate"                       # the fake docker's own state
        self.blog = tmp / "brew.log"
        self.bstate = tmp / "brew.state"
        self.tmpdir = tmp / "tmp"
        self.tmpdir.mkdir()
        self.apps = tmp / "apps"                           # stands for /Applications: Docker.app lives here when a test says so
        self.apps.mkdir()
        self.have_docker = False
        self.have_brew = False
        self.probe_d = self._probe_d()

    def _probe_d(self) -> Path:
        d = self.t / "probe.d"
        d.mkdir()
        self.use_probe_hooks(LIB, d)
        return d

    def use_probe_hooks(self, lib: Path, d: Path = None):
        """Point the probe-hook wrappers at the hooks of another directory (a fixture_lib copy): a hook finds verify-tools.sh and
        TOOLS.toml next to its own real path, so a test that wants the hooks to see a fixture manifest wraps the fixture's hooks."""
        d = d or self.probe_d
        for name in PROBE_HOOKS_UNDER_TEST:
            if (lib / "probe.d" / name).exists():
                (d / name).write_text(f'#!/bin/bash\nexec /bin/bash "{lib}/probe.d/{name}"\n')

    # ---- shims
    def docker(self, **kw):
        mkexe(self.shims / "docker", FAKE_DOCKER)
        self.have_docker = True
        return self

    def brew(self):
        mkexe(self.shims / "brew", FAKE_BREW)
        self.have_brew = True
        return self

    def seed_image(self, tag, image_id, size=12345):
        self.dstate.mkdir(exist_ok=True)
        with open(self.dstate / "images", "a") as f:
            f.write(f"{tag}\t{image_id}\t{size}\n")

    def record(self, name, tag, image_id, **extra):
        """A build record images/NAME.env as build.sh writes it (and the image in the fake daemon)."""
        d = self.state / "images"
        d.mkdir(parents=True, exist_ok=True)
        lines = {"EQ_IMAGE_NAME": name, "EQ_IMAGE_TAG": tag, "EQ_IMAGE_ID": image_id, **extra}
        (d / f"{name}.env").write_text("".join(f"{k}={v}\n" for k, v in lines.items()))
        self.seed_image(tag, image_id)

    def built_image(self, lib: Path, image: str, *, manifest: Path = None, label=True, lock=True, tamper=None, undeclared=None,
                    image_id=None):
        """A manifest image as a finished build leaves it in the fake daemon: record, image, label eq.tools.sha256, and a tree holding
        /opt/eq/TOOLS.lock plus every installed tool file (content = a made-up string, hashed into the lock).
        tamper = (path, content): that file in the image differs from what the lock hashed (verify-tools --deep must notice);
        undeclared = a tool name the lock lists although the manifest does not give it to this image."""
        manifest = manifest or lib / "TOOLS.toml"
        m = load_manifest(manifest)
        tools = {t["name"]: t for t in m["tool"]}
        img = next(i for i in m["image"] if i["name"] == image)
        tag = IMAGE_TAGS[image]
        iid = image_id or "sha256:" + fake_hex("id-" + image)
        self.record(image, tag, iid)
        sn = san(tag)
        tree = self.dstate / f"tree.{sn}"
        shutil.rmtree(tree, ignore_errors=True)
        rows = []
        for t in img["tools"] + ([undeclared] if undeclared else []):
            spec = tools.get(t, {"version": "1", "sha256": fake_hex(t), "files": [f"/opt/{t}/bin/{t}"]})
            for f in spec["files"]:
                content = f"fake file {f}\n".encode()
                p = tree / f.lstrip("/")
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_bytes(content)
                rows.append("\t".join([t, spec["version"], spec["sha256"], f, sha256_hex(content)]))
        if lock:
            p = tree / "opt" / "eq" / "TOOLS.lock"
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("\n".join(rows) + "\n")
        if tamper:
            tp = tree / tamper[0].lstrip("/")
            tp.write_bytes(tamper[1].encode())
        self.dstate.mkdir(exist_ok=True)
        (self.dstate / f"label.{sn}").write_text(f"eq.tools.sha256={image_label(lib, manifest, image) if label is True else label}\n" if label else "")
        return tag, iid

    # ---- running
    def environ(self, tty=False, **extra):
        env = {
            "HOME": str(self.home), "PATH": f"{self.shims}:/usr/bin:/bin", "TMPDIR": str(self.tmpdir),
            "EQ_STATE_DIR": str(self.state), "FAKE_DOCKER_STATE": str(self.dstate),
            "FAKE_BREW_LOG": str(self.blog), "FAKE_BREW_STATE": str(self.bstate),
            # no real Docker.app, no real Homebrew or docker directories
            "EQ_DOCKER_APP_DIRS": "", "EQ_DOCKER_BIN_DIRS": "", "EQ_BREW_DIRS": "",
            "EQ_RUN_ID": "testrun", "LC_ALL": "C",
            "EQ_DOCKER_WAIT_S": "0", "EQ_PROBE_D": str(self.probe_d),
        }
        if tty:
            env[TTY_FN_NAME] = TTY_FN
        env.update({k: str(v) for k, v in extra.items()})
        return env

    def run(self, script, *args, tty=False, input="", timeout=240, lib=None, **extra):
        """bash LIB/script args... -> CompletedProcess (text). lib= runs the script of another directory (a fixture_lib copy)."""
        return subprocess.run([BASH, str((lib or LIB) / script), *args], env=self.environ(tty=tty, **extra), input=input,
                              capture_output=True, text=True, timeout=timeout, cwd=str(self.t), check=False)

    def sh(self, snippet, timeout=120, **extra):
        """Run a bash snippet with lib.sh sourced (set -u): the way every user-run script uses it."""
        src = f'set -u; . "{LIB}/lib.sh"; {snippet}'
        return subprocess.run([BASH, "-c", src], env=self.environ(**extra), capture_output=True, text=True, timeout=timeout,
                              cwd=str(self.t), check=False)

    # ---- what the fakes saw
    def docker_log(self):
        p = self.dstate / "log"
        return p.read_text().splitlines() if p.exists() else []

    def argv_log(self):
        p = self.dstate / "argv.log"
        return [ln.split("\x1f") for ln in p.read_text().splitlines()] if p.exists() else []

    def runs(self):
        return [a for a in self.argv_log() if a and a[0] == "run"]

    def builds(self):
        return [a for a in self.argv_log() if a[:2] == ["buildx", "build"]]

    def composes(self):
        return [a for a in self.argv_log() if a and a[0] == "compose"]

    def compose_env(self, n=None):
        """The variables the n-th (default: last) `docker compose` call saw, as a dict."""
        files = sorted(self.dstate.glob("compose.*.env"), key=lambda p: int(p.name.split(".")[1]))
        p = files[-1] if n is None else files[n]
        return dict(ln.split("=", 1) for ln in p.read_text().splitlines() if "=" in ln)

    def compose_envs(self):
        """What every `docker compose` call except `version` saw, in call order (see compose_env)."""
        files = sorted(self.dstate.glob("compose.*.env"), key=lambda p: int(p.name.split(".")[1])) if self.dstate.exists() else []
        return [dict(ln.split("=", 1) for ln in p.read_text().splitlines() if "=" in ln) for p in files]

    def brew_log(self):
        return self.blog.read_text().splitlines() if self.blog.exists() else []

    def brew_installs(self):
        return [ln for ln in self.brew_log() if ln.startswith("install")]

    def status(self, key="EQ_DOCKER_STATUS"):
        f = self.state / "status.env"
        if not f.exists():
            return None
        for ln in f.read_text().splitlines():
            if ln.startswith(key + "="):
                return ln.split("=", 1)[1]
        return None


@pytest.fixture
def env(tmp_path):
    return Env(tmp_path)
