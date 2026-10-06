"""Shared fixture of the lib/eq-container tests (tests/test_eq_container.py): `eqc_env`.

Hermetic: `container` is the fake CLI tests/fake-container/container (a PATH shim that logs its argv and never talks to the
real services, a VM or the network); HOME, TMPDIR and the state directory are temp directories; the scripts run under
/bin/bash (3.2 on macOS, as the installer runs them). EQ_CONTAINER_LIB overrides the directory under test (default
../lib/eq-container), so a "fails before the fix" run can point the suite at an older copy of the scripts.

The fixture is named eqc_env (not env) so it cannot shadow a test's own `env` helper or parameter elsewhere in tests/.
"""
import os
import re
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
EQC_LIB = Path(os.environ.get("EQ_CONTAINER_LIB") or HERE.parent / "lib" / "eq-container")
FAKE_CONTAINER = HERE / "fake-container" / "container"
BASH = "/bin/bash"
DIGEST_A = "sha256:" + "a" * 64
DIGEST_B = "sha256:" + "b" * 64
# lib.sh eq_img_default_tag: the images are named under the reserved TLD .invalid
# (full, tc-rust, tc-haskell are the legacy names lib.sh EQ_LEGACY_IMAGE_NAMES still knows: only --uninstall --set all uses them)
EQC_TAGS = {
    "full": "eq.invalid/eq-lean:4.34.1-arm64", "min-lean": "eq.invalid/eq-lean-min:4.34.1-arm64",
    "min-py": "eq.invalid/eq-py-min:4.34.1-arm64", "min-both": "eq.invalid/eq-min:4.34.1-arm64",
    "tc-rust": "eq.invalid/eq-rust:arm64", "tc-haskell": "eq.invalid/eq-haskell:arm64", "tc-go": "eq.invalid/eq-go:arm64",
    "tc-node": "eq.invalid/eq-node:arm64", "tc-julia": "eq.invalid/eq-julia:arm64", "tc-jvm": "eq.invalid/eq-jvm:arm64",
}
# the three bash pins that PINS keeps UNSET until `build.sh --resolve-tools --write-pin`; what the tests fill in a lib copy
BASH_PIN_VALUES = {"BASH_SRC_SHA256": "1" * 64, "BASH_PATCHES_SHA256": "2" * 64, "BASH_BIN_SHA256": "3" * 64}


def _exe(dst: Path, src: Path) -> Path:
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src, dst)
    dst.chmod(dst.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return dst


def san(tag: str) -> str:
    """lib.sh's file-name form of a tag (and the fake's `image save` archive name)."""
    return re.sub(r"[:/@]", "_", tag)


def set_pin(lib: Path, key: str, value: str, files=("PINS",)):
    """KEY=VALUE of PINS and/or `ARG KEY=VALUE` of a Dockerfile in a lib copy (exactly one line per file)."""
    for f in files:
        p = lib / f
        t, n = re.subn(r"^((?:ARG )?%s=).*$" % re.escape(key), lambda m: m.group(1) + value, p.read_text(), flags=re.MULTILINE)
        assert n == 1, (f, key)
        p.write_text(t)


def set_key(lib: Path, table: str, name: str, key: str, value: str, raw: bool = False, delete: bool = False):
    """One key of one [[TABLE]] entry of lib/TOOLS.toml (what tools.sh tm_set does); raw=True writes VALUE as the TOML text
    (an array), delete=True removes the line."""
    p = lib / "TOOLS.toml"
    cur, cur_name, out, hit = None, None, [], 0
    for ln in p.read_text().splitlines(keepends=True):
        m = re.match(r"\[\[([a-z]+)\]\]$", ln.rstrip("\n"))
        if m:
            cur, cur_name = m.group(1), None
        m = re.match(r'name = "(.*)"$', ln.rstrip("\n"))
        if m and cur_name is None:
            cur_name = m.group(1)
        if cur == table and cur_name == name and ln.startswith(key + " = "):
            hit += 1
            if delete:
                continue
            ln = "%s = %s\n" % (key, value if raw else '"%s"' % value)
        out.append(ln)
    assert hit == 1, (table, name, key)
    p.write_text("".join(out))


def set_tool(lib: Path, tool: str, key: str, value: str):
    set_key(lib, "tool", tool, key, value)


def fill_bash_pins(lib: Path, values: dict = None):
    """Resolve the three bash pins in a lib copy the way --write-pin would: PINS, the Dockerfile.minimal ARGs, and the bash entry
    of TOOLS.toml (sha256 = BASH_SRC_SHA256, file_sha256 = BASH_BIN_SHA256, a checksum_source)."""
    v = values or BASH_PIN_VALUES
    for k, val in v.items():
        set_pin(lib, k, val, files=("PINS", "Dockerfile.minimal"))
    set_tool(lib, "bash", "sha256", v["BASH_SRC_SHA256"])
    set_tool(lib, "bash", "file_sha256", v["BASH_BIN_SHA256"])
    set_tool(lib, "bash", "checksum_source", "test: filled by the tests")


class EqcEnv:
    """One scratch world for lib/eq-container: a shims dir holding the fake `container`, HOME, TMPDIR, a state dir named
    eq-container (`uninstall --purge` removes only such a directory) and the fake's argv log."""

    def __init__(self, tmp: Path):
        self.t = Path(tmp)
        self.home = self.t / "home"
        self.home.mkdir()
        self.tmpdir = self.t / "tmp"
        self.tmpdir.mkdir()
        self.shims = self.t / "shims"
        self.cli = _exe(self.shims / "container", FAKE_CONTAINER)
        self.state = self.t / "state" / "eq-container"
        self.log = self.t / "container.log"

    def record(self, name: str, tag: str = None, digest: str = DIGEST_A, **extra):
        """A build record images/NAME.env as build.sh writes it."""
        d = self.state / "images"
        d.mkdir(parents=True, exist_ok=True)
        lines = {"EQ_IMAGE_NAME": name, "EQ_IMAGE_TAG": tag or EQC_TAGS[name], "EQ_IMAGE_DIGEST": digest, **extra}
        (d / ("%s.env" % name)).write_text("".join("%s=%s\n" % kv for kv in lines.items()))

    def environ(self, **extra) -> dict:
        e = {"HOME": str(self.home), "PATH": "%s:/usr/bin:/bin" % self.shims, "TMPDIR": str(self.tmpdir),
             "EQ_STATE_DIR": str(self.state), "EQ_CONTAINER_BIN": str(self.cli), "EQ_FAKE_CONTAINER_LOG": str(self.log),
             "EQ_FAKE_CONTAINER_DIGEST": DIGEST_A, "EQ_HOST_ARCH": "arm64", "EQ_RUN_ID": "testrun", "LC_ALL": "C"}
        for k, v in extra.items():
            if v is None:
                e.pop(k, None)
            else:
                e[k] = str(v)
        return e

    def run(self, script: str, *args, lib: Path = None, input: str = "", timeout: int = 120, **extra):
        """bash LIB/script args... (lib=: a copy of the directory) -> CompletedProcess (text)."""
        return subprocess.run([BASH, str(Path(lib or EQC_LIB) / script), *map(str, args)], env=self.environ(**extra),
                              input=input, capture_output=True, text=True, timeout=timeout, cwd=str(self.t), check=False)

    def sh(self, snippet: str, timeout: int = 120, **extra):
        """A bash snippet with lib.sh sourced under set -u, the way every script of the directory uses it."""
        src = 'set -u; . "%s/lib.sh"; %s' % (EQC_LIB, snippet)
        return subprocess.run([BASH, "-c", src], env=self.environ(**extra), capture_output=True, text=True,
                              timeout=timeout, cwd=str(self.t), check=False)

    def calls(self) -> list:
        """Every fake `container` call, as an argv list, in order."""
        if not self.log.exists():
            return []
        return [ln.split("\x1f") for ln in self.log.read_text().splitlines()]

    def runs(self) -> list:
        return [a for a in self.calls() if a and a[0] == "run"]

    def status(self, key: str = "EQ_CONTAINER_STATUS"):
        f = self.state / "status.env"
        if not f.exists():
            return None
        for ln in f.read_text().splitlines():
            if ln.startswith(key + "="):
                return ln.split("=", 1)[1]
        return None


@pytest.fixture
def eqc_env(tmp_path):
    return EqcEnv(tmp_path)
