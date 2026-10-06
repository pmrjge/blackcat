"""lib/eq-container pins: every way a pin is read must fail closed on a placeholder or a malformed value.

distro-pins.sh (the host-side derivation of the distro-package pins, bash perl jq busybox) runs against a fake snapshot and a
fake base layer served by a fake `curl`, with a fake `gpgv` (both on PATH, Python scripts that log their argv): the happy
paths (placeholders reported as 13, all equal 0, a differing pin 1) and one seeded fault per link of its chain (each must stop
with rc 1 and print no TOOL line). build.sh's pin checks run with the fake `container` (tests/fake-container): a placeholder
is exit 13, a malformed value exit 2, both before any `container build`. verify-tools.sh --manifest runs on the real
TOOLS.toml (only busybox and jq may still be pending) and on seeded copies; the awk reader (tools.sh) must agree with tomllib.
Run: /Users/pmrj/.claude/venvs/tools/bin/python -m pytest -q tests/test_eq_container_pins.py
"""
import hashlib
import io
import lzma
import re
import shutil
import subprocess
import sys
import tarfile
import tomllib
from pathlib import Path

import pytest

from conftest import BASH, EQC_LIB

SNAP = "20260918T000000Z"
# bash 3.2 matches a bracket range ([a-f]) by the locale's collation: under a UTF-8 locale `*[!0-9a-f]*` let A-E through, so the
# format gates are also run under one (skipped where the machine has none)
UTF8 = next((loc for loc in ("en_US.UTF-8", "C.UTF-8", "pt_PT.UTF-8")
             if loc in subprocess.run(["locale", "-a"], capture_output=True, text=True, check=False).stdout.split()), None)
needs_utf8 = pytest.mark.skipif(UTF8 is None, reason="no UTF-8 locale on this machine")
SNAPDIR = "snapshot.debian.org/archive/debian/" + SNAP
LAYER_URL = "https://raw.example.test/artifacts/rootfs.tar.gz"
KEY = "KEY-trixie-1"


def sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def tarball(members: dict, mode: str) -> bytes:
    """members: name -> bytes (a regular 0755 file) or ("symlink", target)."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode=mode) as t:
        for name, data in members.items():
            ti = tarfile.TarInfo(name)
            if isinstance(data, tuple):
                ti.type, ti.linkname = tarfile.SYMTYPE, data[1]
                t.addfile(ti)
            else:
                ti.size, ti.mode = len(data), 0o755
                t.addfile(ti, io.BytesIO(data))
    return buf.getvalue()


def ar(members: list) -> bytes:
    """An ar archive the way dpkg-deb writes a .deb (names without a trailing slash, even-aligned members)."""
    out = b"!<arch>\n"
    for name, data in members:
        out += b"%-16s%-12d%-6d%-6d%-8s%-10d`\n" % (name.encode(), 0, 0, 0, b"100644", len(data)) + data
        out += b"\n" if len(data) % 2 else b""
    return out


def deb(files: dict) -> bytes:
    return ar([("debian-binary", b"2.0\n"), ("control.tar.xz", tarball({"./control": b"Package: x\n"}, "w:xz")),
               ("data.tar.xz", tarball(files, "w:xz"))])


def set_tool(lib: Path, tool: str, key: str, value: str):
    """One key of one [[tool]] table of lib/TOOLS.toml (what tools.sh tm_set does)."""
    p = lib / "TOOLS.toml"
    text, cur, out, hit = p.read_text(), None, [], 0
    for ln in text.splitlines(keepends=True):
        if ln.startswith("[["):
            cur = None
        m = re.match(r'name = "(.*)"$', ln.rstrip("\n"))
        if m and cur is None:
            cur = m.group(1)
        if cur == tool and ln.startswith(key + " = "):
            ln, hit = '%s = "%s"\n' % (key, value), hit + 1
        out.append(ln)
    assert hit == 1, (tool, key)
    p.write_text("".join(out))


def set_pin(lib: Path, key: str, value: str, files=("PINS",)):
    for f in files:
        p = lib / f
        t, n = re.subn(r"^((?:ARG )?%s=).*$" % re.escape(key), lambda m: m.group(1) + value, p.read_text(), flags=re.MULTILINE)
        assert n == 1, (f, key)
        p.write_text(t)


FAKE_CURL = r'''#!%s
import os, shutil, sys
a = sys.argv[1:]
open(os.environ["FAKE_CURL_LOG"], "a").write("\x1f".join(a) + "\n")
out = url = None; proto = redir = False; i = 0
while i < len(a):
    if a[i] == "-o": out = a[i + 1]; i += 2
    elif a[i] == "--proto": proto = a[i + 1] == "=https"; i += 2
    elif a[i] == "--proto-redir": redir = a[i + 1] == "=https"; i += 2
    elif a[i] in ("--retry", "--max-time"): i += 2
    elif a[i].startswith("-"): i += 1
    else: url = a[i]; i += 1
if not (proto and redir and out and url and url.startswith("https://")):
    sys.exit("fake curl: not an https-only download")
src = os.path.join(os.environ["FAKE_WEB"], url[len("https://"):])
if not os.path.isfile(src):
    sys.exit(22)
shutil.copyfile(src, out)
'''

FAKE_GPGV = r'''#!%s
import os, sys
a = sys.argv[1:]
open(os.environ["FAKE_GPGV_LOG"], "a").write("\x1f".join(a) + "\n")
o = {}; files = []; i = 0
while i < len(a):
    if a[i] in ("--homedir", "--keyring", "--output"): o[a[i]] = a[i + 1]; i += 2
    elif a[i].startswith("-"): sys.exit("fake gpgv: unexpected option " + a[i])
    else: files.append(a[i]); i += 1
if not (os.path.isdir(o.get("--homedir", "")) and os.path.isfile(o.get("--keyring", "")) and "--output" in o and len(files) == 1):
    sys.exit(2)
text = open(files[0]).read()
head, mark = "-----BEGIN PGP SIGNED MESSAGE-----\nHash: SHA256\n\n", "\n-----BEGIN PGP SIGNATURE-----\n"
if not text.startswith(head) or mark not in text:
    sys.exit("gpgv: no signed data")
body, sig = text[len(head):].split(mark, 1)
open(o["--output"], "w").write(body + "\n")      # like gpg: the signed text is written, then the verdict
if sig.split("-----END PGP SIGNATURE-----")[0].strip() != open(o["--keyring"]).read().strip():
    sys.exit("gpgv: BAD signature")
'''


class World:
    """A copy of lib/eq-container whose PINS point at a fake base layer, plus a fake web (layer, snapshot InRelease,
    Packages.xz, two .debs) and the fake curl and gpgv. Knobs change what build() serves."""

    def __init__(self, tmp: Path):
        self.t = tmp
        self.lib = tmp / "eq-container"
        shutil.copytree(EQC_LIB, self.lib, ignore=shutil.ignore_patterns(".state", "__pycache__"))
        self.web = tmp / "web"
        self.shims = tmp / "shims"
        self.shims.mkdir()
        self.tmpdir = tmp / "tmp"
        self.tmpdir.mkdir()
        for name, src in (("curl", FAKE_CURL), ("gpgv", FAKE_GPGV)):
            p = self.shims / name
            p.write_text(src % sys.executable)
            p.chmod(0o755)
        self.bins = {"bash": b"BASH-ELF\n", "perl": b"PERL-ELF\n", "busybox": b"BUSYBOX-ELF\n", "jq": b"JQ-ELF\n"}
        self.vers = {"bash": "5.2.37-2+b10", "perl": "5.40.1-6+deb13u1", "busybox": "1:1.37.0-6+b9", "jq": "1.7.1-6+deb13u3"}
        self.status_bash = "install ok installed"
        self.debian_version, self.version, self.codename, self.sig = "13.7", "13.7", "trixie", KEY
        self.jq_files = {"./usr/bin/jq": self.bins["jq"], "./usr/share/doc/jq/copyright": b"MIT\n"}
        self.jq_filename = "pool/main/j/jq/jq_1.7.1-6+deb13u3_arm64.deb"
        self.extra_stanza = ""
        self.signed_packages_sha = None     # None: the real hash of the Packages.xz served
        self.unsigned_tail = ""
        self.after = []                     # callables run after the files are written (tampering)
        for t in ("bash", "perl"):          # the repo pins bash and perl; here they are the fake layer's values
            set_tool(self.lib, t, "version", self.vers[t])
            set_tool(self.lib, t, "sha256", sha(self.bins[t]))

    def put(self, rel: str, data: bytes):
        p = self.web / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)

    def build(self):
        status = "".join("Package: %s\nStatus: %s\nArchitecture: arm64\nVersion: %s\n\n" % kv for kv in (
            ("bash", self.status_bash, self.vers["bash"]), ("perl-base", "install ok installed", self.vers["perl"]),
            ("bash-doc", "deinstall ok config-files", "9.9")))
        layer = tarball({"usr/bin/bash": self.bins["bash"], "usr/bin/perl": self.bins["perl"],
                         "var/lib/dpkg/status": status.encode(), "etc/debian_version": (self.debian_version + "\n").encode(),
                         "usr/share/keyrings/debian-archive-keyring.pgp": (KEY + "\n").encode()}, "w:gz")
        self.put(LAYER_URL[len("https://"):], layer)
        set_pin(self.lib, "BASE_LAYER_URL", LAYER_URL)
        set_pin(self.lib, "BASE_LAYER_SHA256", sha(layer))
        debs = {"busybox-static": ("pool/main/b/busybox/busybox-static_1.37.0-6+b9_arm64.deb", self.vers["busybox"],
                                   deb({"./usr/bin/busybox": self.bins["busybox"]})),
                "jq": (self.jq_filename, self.vers["jq"], deb(self.jq_files))}
        stanzas = ["Package: busybox\nArchitecture: arm64\nVersion: 1:1.37.0-6+b9\nFilename: pool/main/b/busybox/x.deb\n"
                   "Size: 1\nSHA256: %s\n" % ("0" * 64)]
        for pkg, (fn, ver, data) in debs.items():
            self.put("%s/%s" % (SNAPDIR, fn), data)
            stanzas.append("Package: %s\nArchitecture: arm64\nVersion: %s\nFilename: %s\nSize: %d\nSHA256: %s\n"
                           % (pkg, ver, fn, len(data), sha(data)))
        packages = lzma.compress(("\n".join(stanzas) + self.extra_stanza).encode(), format=lzma.FORMAT_XZ)
        evil = deb({"./usr/bin/jq": b"EVIL-JQ\n"})
        self.put("%s/pool/main/j/jq/jq_1.7.1-6+deb13u9_arm64.deb" % SNAPDIR, evil)
        self.evil_packages = lzma.compress(("\n".join(stanzas[:2]) + "\nPackage: jq\nArchitecture: arm64\nVersion: 1.7.1-6+deb13u9\n"
                                            "Filename: pool/main/j/jq/jq_1.7.1-6+deb13u9_arm64.deb\nSize: %d\nSHA256: %s\n"
                                            % (len(evil), sha(evil))).encode(), format=lzma.FORMAT_XZ)
        self.put(SNAPDIR + "/dists/trixie/main/binary-arm64/Packages.xz", packages)
        psha = self.signed_packages_sha or sha(packages)
        release = ("Origin: Debian\nLabel: Debian\nSuite: stable\nVersion: %s\nCodename: %s\nDate: Sat, 12 Sep 2026 07:55:41 UTC\n"
                   "Architectures: all amd64 arm64\nComponents: main\nMD5Sum:\n %s %d main/binary-arm64/Packages.xz\nSHA256:\n"
                   " %s %d main/binary-amd64/Packages.xz\n %s %d main/binary-arm64/Packages.xz\n %s %d main/binary-arm64/Packages\n"
                   % (self.version, self.codename, "f" * 32, len(packages), "e" * 64, 5, psha, len(packages), "d" * 64, 9))
        inrelease = ("-----BEGIN PGP SIGNED MESSAGE-----\nHash: SHA256\n\n%s\n-----BEGIN PGP SIGNATURE-----\n%s\n"
                     "-----END PGP SIGNATURE-----\n%s" % (release.rstrip("\n"), self.sig, self.unsigned_tail))
        self.put(SNAPDIR + "/dists/trixie/InRelease", inrelease.encode())
        self.packages_sha, self.packages_size = sha(packages), len(packages)
        for f in self.after:
            f(self)

    def run(self, *args, locale: str = "C"):
        env = {"PATH": "%s:%s:/usr/bin:/bin" % (self.shims, Path(shutil.which("xz")).parent), "HOME": str(self.t),
               "TMPDIR": str(self.tmpdir), "LC_ALL": locale, "FAKE_WEB": str(self.web),
               "FAKE_CURL_LOG": str(self.t / "curl.log"), "FAKE_GPGV_LOG": str(self.t / "gpgv.log")}
        return subprocess.run([BASH, str(self.lib / "distro-pins.sh"), *args], env=env, capture_output=True, text=True,
                              timeout=120, check=False)

    def log(self, name: str) -> list:
        p = self.t / name
        return [ln.split("\x1f") for ln in p.read_text().splitlines()] if p.exists() else []


needs_tools = pytest.mark.skipif(not (shutil.which("xz") and shutil.which("ar")), reason="xz and ar are needed")


@pytest.fixture
def world(tmp_path):
    return World(tmp_path)


def tool_lines(out: str) -> dict:
    return {ln.split()[1]: ln.split(None, 4)[2:] for ln in out.splitlines() if ln.startswith("TOOL ")}


def lib_digest(lib: Path) -> str:
    h = hashlib.sha256()
    for p in sorted(lib.rglob("*")):
        if p.is_file():
            h.update(str(p.relative_to(lib)).encode() + b"\0" + p.read_bytes())
    return h.hexdigest()


# ------------------------------------------------------------------------------------------- distro-pins.sh, happy paths
@needs_tools
def test_distro_pins_derives_all_four_and_reports_the_placeholders(world):
    world.build()
    before = lib_digest(world.lib)
    p = world.run()
    assert p.returncode == 13, (p.stdout, p.stderr)
    t = tool_lines(p.stdout)
    assert set(t) == {"bash", "perl", "busybox", "jq"}
    for name in t:
        assert t[name][0] == world.vers[name] and t[name][1] == sha(world.bins[name]), (name, t[name])
    assert t["bash"][2] == "pinned: same" and t["perl"][2] == "pinned: same"
    assert t["busybox"][2] == "pinned: PLACEHOLDER" and t["jq"][2] == "pinned: PLACEHOLDER"
    assert "DISTRO-PINS: PENDING" in p.stdout and "gpgv=OK" in p.stdout
    assert "PROVENANCE Packages.xz https://%s/dists/trixie/main/binary-arm64/Packages.xz sha256=%s" % (SNAPDIR, world.packages_sha) in p.stdout
    # every download is https-only (the fake refuses anything else) and these five, in order
    urls = [a[-1] for a in world.log("curl.log")]
    assert urls == [LAYER_URL, "https://%s/dists/trixie/InRelease" % SNAPDIR,
                    "https://%s/dists/trixie/main/binary-arm64/Packages.xz" % SNAPDIR,
                    "https://%s/pool/main/b/busybox/busybox-static_1.37.0-6+b9_arm64.deb" % SNAPDIR,
                    "https://%s/%s" % (SNAPDIR, world.jq_filename)], urls
    # InRelease is checked against the keyring of the downloaded layer, in a private homedir
    (g,) = world.log("gpgv.log")
    kr = g[g.index("--keyring") + 1]
    assert kr.endswith("/layer/usr/share/keyrings/debian-archive-keyring.pgp") and kr.startswith(str(world.tmpdir)), g
    # it never edits the checkout and leaves no temp dir behind
    assert lib_digest(world.lib) == before and list(world.tmpdir.iterdir()) == []


@needs_tools
def test_distro_pins_all_equal_is_ok(world):
    world.build()
    for t in ("busybox", "jq"):
        set_tool(world.lib, t, "version", world.vers[t])
        set_tool(world.lib, t, "sha256", sha(world.bins[t]))
    set_pin(world.lib, "BUSYBOX_SHA256", sha(world.bins["busybox"]))
    p = world.run()
    assert p.returncode == 0 and "DISTRO-PINS: OK" in p.stdout, (p.stdout, p.stderr)
    assert {v[2] for v in tool_lines(p.stdout).values()} == {"pinned: same"}


@needs_tools
@pytest.mark.parametrize("how", ["tools_sha", "tools_version", "pins_busybox"])
def test_distro_pins_a_differing_pin_is_rc_1(world, how):
    world.build()
    for t in ("busybox", "jq"):
        set_tool(world.lib, t, "version", world.vers[t])
        set_tool(world.lib, t, "sha256", sha(world.bins[t]))
    set_pin(world.lib, "BUSYBOX_SHA256", sha(world.bins["busybox"]))
    if how == "tools_sha":
        set_tool(world.lib, "perl", "sha256", "1" * 64)
    elif how == "tools_version":
        set_tool(world.lib, "jq", "version", "1.7.1-6+deb13u2")
    else:
        set_pin(world.lib, "BUSYBOX_SHA256", "2" * 64)
    p = world.run()
    assert p.returncode == 1 and "DISTRO-PINS: DIFFERS" in p.stdout, (p.stdout, p.stderr)
    assert sum("pinned: DIFFERS" in ln for ln in p.stdout.splitlines()) == 1


# ------------------------------------------------------------------------------- distro-pins.sh, one fault per chain link
def _unsigned_tail(w):
    """A second SHA256 section after the signature, naming the Packages.xz really served (the signed one names another)."""
    rel = SNAPDIR + "/dists/trixie/InRelease"
    w.put(rel, (w.web / rel).read_bytes() + ("SHA256:\n %s %d main/binary-arm64/Packages.xz\n"
                                             % (w.packages_sha, w.packages_size)).encode())


FAULTS = {
    # the layer is not the pinned one
    "layer_hash": lambda w: w.after.append(lambda w: set_pin(w.lib, "BASE_LAYER_SHA256", "0" * 64)),
    # a bash that dpkg does not list as installed
    "layer_not_installed": lambda w: setattr(w, "status_bash", "deinstall ok config-files"),
    # InRelease not signed by the layer's keyring
    "bad_signature": lambda w: setattr(w, "sig", "KEY-someone-else"),
    # the signed text names another Packages.xz; the right hash sits after the signature, where nothing may be read
    "unsigned_tail": lambda w: (setattr(w, "signed_packages_sha", "c" * 64), w.after.append(_unsigned_tail)),
    # an older point release replayed, or another suite
    "older_point_release": lambda w: setattr(w, "version", "13.6"),
    "other_codename": lambda w: setattr(w, "codename", "bookworm"),
    # Packages.xz or a .deb changed after the hashes were signed
    "packages_tampered": lambda w: w.after.append(lambda w: w.put(SNAPDIR + "/dists/trixie/main/binary-arm64/Packages.xz",
                                                                 w.evil_packages)),
    "deb_tampered": lambda w: w.after.append(lambda w: w.put("%s/%s" % (SNAPDIR, w.jq_filename),
                                                            deb({"./usr/bin/jq": b"EVIL\n"}))),
    # two candidate stanzas: which one apt picks is not decided here
    "two_stanzas": lambda w: setattr(w, "extra_stanza", "\nPackage: jq\nArchitecture: arm64\nVersion: 1.8.2-1\n"
                                     "Filename: pool/main/j/jq/jq_1.8.2-1_arm64.deb\nSize: 1\nSHA256: %s\n" % ("1" * 64)),
    # a Filename that climbs out of the pool
    "dotdot_filename": lambda w: setattr(w, "jq_filename", "pool/main/j/jq/../../../../x/jq_9_arm64.deb"),
    # the package does not install the file, or installs a symlink
    "missing_file": lambda w: setattr(w, "jq_files", {"./usr/share/doc/jq/copyright": b"MIT\n"}),
    "symlink": lambda w: setattr(w, "jq_files", {"./usr/bin/jq": ("symlink", "/usr/bin/true")}),
}


WHY = {
    "layer_hash": "the base layer hashes to", "layer_not_installed": "no single installed bash",
    "bad_signature": "InRelease does not verify", "unsigned_tail": "Packages.xz does not match its signed SHA256 line",
    "older_point_release": "InRelease is Debian 13.6 but the base image is 13.7", "other_codename": "Codename 'bookworm'",
    "packages_tampered": "Packages.xz does not match its signed SHA256 line",
    "deb_tampered": "does not match its Packages SHA256 and Size", "two_stanzas": "no single arm64 stanza for jq",
    "dotdot_filename": "unexpected Filename", "missing_file": "does not install usr/bin/jq", "symlink": "is not a regular file",
}


@needs_tools
@pytest.mark.parametrize("fault", sorted(FAULTS))
def test_distro_pins_every_chain_fault_stops_with_no_value(world, fault):
    """Each fault would otherwise yield a value (the attacks are self-consistent past the check that stops them)."""
    FAULTS[fault](world)
    world.build()
    p = world.run()
    assert p.returncode == 1, (fault, p.returncode, p.stdout, p.stderr)
    assert "TOOL " not in p.stdout and "FAILED: " in p.stderr and WHY[fault] in p.stderr, (p.stdout, p.stderr)
    assert list(world.tmpdir.iterdir()) == []


@needs_tools
@pytest.mark.parametrize("key, value", [
    ("APT_SNAPSHOT", "latest"), ("BASE_LAYER_SHA256", "ab" * 31), ("BASE_LAYER_SHA256", "AB" * 32),
    ("BASE_LAYER_URL", "http://raw.example.test/rootfs.tar.gz"), ("BASE_LAYER_URL", "https://u:p@raw.example.test/x.tar.gz"),
    ("BASE_LAYER_URL", "https://raw.example.test/x.tar.gz;rm"),
])
def test_distro_pins_malformed_pins_are_usage_errors(world, key, value):
    world.build()
    set_pin(world.lib, key, value)
    p = world.run()
    assert p.returncode == 2 and "TOOL " not in p.stdout, (p.stdout, p.stderr)
    assert world.log("curl.log") == []          # refused before any download


@needs_tools
@needs_utf8
@pytest.mark.parametrize("key, value", [
    ("BASE_LAYER_SHA256", "AB" * 32), ("BUSYBOX_SHA256", "C" * 64), ("BUSYBOX_SHA256", "xyz"),
    ("APT_SNAPSHOT", "2026O918T000000Z"),
])
def test_distro_pins_malformed_pins_under_a_utf8_locale(world, key, value):
    """Uppercase hex and letters for digits pass a collation range under a UTF-8 locale; the literal lists refuse them."""
    world.build()
    set_pin(world.lib, key, value)
    p = world.run(locale=UTF8)
    assert p.returncode == 2 and "TOOL " not in p.stdout, (p.stdout, p.stderr)
    assert world.log("curl.log") == []


# --------------------------------------------------------------------------------- build.sh: placeholder 13, malformed 2
@pytest.fixture
def pins_lib(tmp_path):
    lib = tmp_path / "eq-container-p"
    shutil.copytree(EQC_LIB, lib, ignore=shutil.ignore_patterns(".state", "__pycache__"))
    return lib


DOCKERFILES = ("Dockerfile", "Dockerfile.minimal", "Dockerfile.toolchains")


def _no_build(env) -> bool:
    return not [c for c in env.calls() if c and c[0] == "build"]


@pytest.mark.parametrize("where", ["PINS", "Dockerfile.minimal"])
def test_build_stops_at_a_placeholder_busybox_pin(eqc_env, pins_lib, where):
    """BUSYBOX_SHA256 UNSET in PINS or only in the Dockerfile ARG: exit 13 naming the pin, nothing built."""
    other = "Dockerfile.minimal" if where == "PINS" else "PINS"
    set_pin(pins_lib, "BUSYBOX_SHA256", "UNSET", files=(where,))
    set_pin(pins_lib, "BUSYBOX_SHA256", "c" * 64, files=(other,))
    p = eqc_env.run("build.sh", "--profiles", "core", "--yes", lib=pins_lib)
    assert p.returncode == 13, (p.stdout, p.stderr)
    assert "pin BUSYBOX_SHA256 is a placeholder in %s" % where in p.stderr and "distro-pins.sh" in p.stderr
    assert _no_build(eqc_env)


def test_build_stops_at_a_placeholder_tool_pin(eqc_env, pins_lib):
    """BUSYBOX_SHA256 filled everywhere but jq still PLACEHOLDER in TOOLS.toml (busybox resolved too): exit 13."""
    set_pin(pins_lib, "BUSYBOX_SHA256", "c" * 64, files=("PINS", "Dockerfile.minimal"))
    for k, v in (("version", "1:1.37.0-6+b9"), ("sha256", "c" * 64), ("checksum_source", "test")):
        set_tool(pins_lib, "busybox", k, v)
    p = eqc_env.run("build.sh", "--profiles", "core", "--yes", lib=pins_lib)
    assert p.returncode == 13, (p.stdout, p.stderr)
    assert "PENDING tool jq: sha256 is PLACEHOLDER" in p.stderr and _no_build(eqc_env)


@pytest.mark.parametrize("key, value, sel", [
    ("BASE_IMAGE", "debian:trixie-slim", "full"),                                 # a mutable tag, no digest
    ("BASE_IMAGE", "debian:trixie-slim@sha256:" + "a" * 63, "full"),
    ("BASE_IMAGE", "debian:trixie-slim@sha256:" + "a" * 64 + " --x", "full"),
    ("LEAN_SHA256", "f" * 63, "full"), ("LEAN_SHA256", "F" * 64, "full"), ("UV_SHA256", "TBD", "full"),
    ("MATHLIB_REV", "d13f23b7", "full"), ("APT_SNAPSHOT", "latest", "full"), ("LEAN_VERSION", "4.34.1;x", "full"),
    ("BUSYBOX_SHA256", "xyz", "min"), ("BUSYBOX_SHA256", "c" * 65, "min"),
])
def test_build_refuses_a_malformed_pin_before_building(eqc_env, pins_lib, key, value, sel):
    """The same malformed value in PINS and every Dockerfile ARG (so they agree): refused with exit 2, nothing built (a
    BASE_IMAGE without a digest used to build from the mutable tag)."""
    set_pin(pins_lib, "BUSYBOX_SHA256", "c" * 64, files=("PINS", "Dockerfile.minimal"))
    files = ["PINS"] + [f for f in DOCKERFILES if re.search(r"^ARG %s=" % key, (pins_lib / f).read_text(), re.MULTILINE)]
    set_pin(pins_lib, key, value, files=files)
    p = eqc_env.run("build.sh", "--set", sel, "--yes", lib=pins_lib)
    assert p.returncode == 2, (p.stdout, p.stderr)
    assert "pin %s is malformed in PINS" % key in p.stderr and _no_build(eqc_env), p.stderr


@needs_utf8
@pytest.mark.parametrize("key, value, sel", [
    ("LEAN_SHA256", "A" * 64, "full"), ("BASE_IMAGE", "Debian:trixie-slim@sha256:" + "a" * 64, "full"),
    ("BASE_IMAGE", "debian:trixie-slim@sha256:" + "B" * 64, "full"), ("BUSYBOX_SHA256", "C" * 64, "min"),
    ("APT_SNAPSHOT", "2026O918T000000Z", "full"), ("LEAN_VERSION", "4.34.1Ä", "full"),
])
def test_build_refuses_a_malformed_pin_under_a_utf8_locale(eqc_env, pins_lib, key, value, sel):
    """The installer runs build.sh in the user's locale: a range such as [0-9a-f] matched A-E there (bash 3.2 collation)."""
    set_pin(pins_lib, "BUSYBOX_SHA256", "c" * 64, files=("PINS", "Dockerfile.minimal"))
    files = ["PINS"] + [f for f in DOCKERFILES if re.search(r"^ARG %s=" % key, (pins_lib / f).read_text(), re.MULTILINE)]
    set_pin(pins_lib, key, value, files=files)
    p = eqc_env.run("build.sh", "--set", sel, "--yes", lib=pins_lib, LC_ALL=UTF8)
    assert p.returncode == 2, (p.stdout, p.stderr)
    assert "pin %s is malformed in PINS" % key in p.stderr and _no_build(eqc_env), p.stderr


def test_build_check_reports_a_malformed_pin(eqc_env, pins_lib):
    set_pin(pins_lib, "LEAN_SHA256", "f" * 63, files=("PINS", "Dockerfile"))
    eqc_env.record("full", EQ_INPUTS_SHA256="x")
    p = eqc_env.run("build.sh", "--set", "full", "--check", lib=pins_lib)
    assert p.returncode == 11 and "pin LEAN_SHA256 is malformed" in p.stdout, p.stdout


# ------------------------------------------------------------------------------------------- verify-tools.sh --manifest
def vt(lib: Path, *args, locale: str = "C"):
    return subprocess.run([BASH, str(lib / "verify-tools.sh"), "--manifest", *args], capture_output=True, text=True,
                          timeout=120, check=False, env={"PATH": "/usr/bin:/bin", "LC_ALL": locale})


DEBVER = re.compile(r"^(\d+:)?[0-9][A-Za-z0-9.+~-]*$")


def test_real_manifest_core_pins():
    """The repo's TOOLS.toml: bash and perl are pinned (64 hex, a Debian version, a source); only busybox and jq may still be
    pending, and once they are not, `core` passes."""
    p = vt(EQC_LIB, "--profiles", "core")
    assert p.returncode in (0, 13), (p.stdout, p.stderr)
    pend = {ln.split()[2].rstrip(":") for ln in p.stdout.splitlines() if ln.startswith("PENDING ")}
    assert pend <= {"busybox", "jq"}, p.stdout
    assert (p.returncode == 13) == bool(pend)
    m = tomllib.loads((EQC_LIB / "TOOLS.toml").read_text())
    tools = {t["name"]: t for t in m["tool"]}
    for name in ("bash", "perl"):
        t = tools[name]
        assert re.fullmatch(r"[0-9a-f]{64}", t["sha256"]) and DEBVER.match(t["version"]), t
        assert "PLACEHOLDER" not in t["checksum_source"] and t["provenance"] == "distro-package"
    for name in pend:
        assert tools[name]["sha256"] == "PLACEHOLDER"


@pytest.mark.parametrize("tool, key, value, rc", [
    ("bash", "sha256", "c" * 63, 2), ("bash", "sha256", "C" * 64, 2), ("perl", "sha256", "TODO", 2),
    ("bash", "sha256", "PLACEHOLDER", 13), ("bash", "version", "PLACEHOLDER", 13),
    ("perl", "checksum_source", "PLACEHOLDER", 13),
])
def test_manifest_seeded_pin_faults(pins_lib, tool, key, value, rc):
    set_tool(pins_lib, tool, key, value)
    p = vt(pins_lib, "--profiles", "core")
    assert p.returncode == rc, (p.stdout, p.stderr)
    want = ("PENDING tool %s: %s is PLACEHOLDER" if rc == 13 else "PROBLEM tool %s: %s") % (tool, key)
    assert want in p.stdout, p.stdout


@needs_utf8
@pytest.mark.parametrize("value", ["C" * 64, "Ab" * 32])
def test_manifest_uppercase_sha256_is_invalid_under_a_utf8_locale(pins_lib, value):
    set_tool(pins_lib, "bash", "sha256", value)
    p = vt(pins_lib, "--profiles", "core", locale=UTF8)
    assert p.returncode == 2 and "PROBLEM tool bash: sha256" in p.stdout, p.stdout


def test_manifest_half_applied_busybox_pin_is_invalid(pins_lib):
    """busybox pinned in TOOLS.toml while PINS still says UNSET (or the reverse): the two disagree, exit 2."""
    for k, v in (("version", "1:1.37.0-6+b9"), ("sha256", "c" * 64), ("checksum_source", "test")):
        set_tool(pins_lib, "busybox", k, v)
    p = vt(pins_lib, "--profiles", "core")
    assert p.returncode == 2 and "busybox: sha256 differs from PINS BUSYBOX_SHA256" in p.stdout, p.stdout
    set_tool(pins_lib, "busybox", "sha256", "PLACEHOLDER")
    set_pin(pins_lib, "BUSYBOX_SHA256", "c" * 64)
    p = vt(pins_lib, "--profiles", "core")
    assert p.returncode == 2, p.stdout


def test_manifest_placeholders_outside_the_selected_profiles_do_not_block(pins_lib):
    p = vt(pins_lib, "--profiles", "node,go,julia,jvm")
    assert p.returncode == 0 and "PENDING" not in p.stdout, p.stdout


def test_awk_reader_agrees_with_tomllib():
    """tools.sh reads TOOLS.toml with awk (bash 3.2, the builder); tomllib must see exactly the same tables and values."""
    src = '. "%s/tools.sh"; tm_load "%s/TOOLS.toml" && printf "%%s\\n" "$TM_TSV"' % (EQC_LIB, EQC_LIB)
    p = subprocess.run([BASH, "-c", src], capture_output=True, text=True, timeout=60, check=False)
    assert p.returncode == 0, p.stderr
    awk = sorted(tuple(ln.split("\t")) for ln in p.stdout.splitlines() if ln)
    m = tomllib.loads((EQC_LIB / "TOOLS.toml").read_text())
    want = sorted((table, row["name"], k, " ".join(v) if isinstance(v, list) else v)
                  for table in ("tool", "image", "profile") for row in m[table] for k, v in row.items())
    assert awk == want
