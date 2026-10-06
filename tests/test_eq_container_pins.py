"""lib/eq-container pins and the distroless bases (DESIGN_DISTROLESS.md): every way a pin is read must fail closed on a
placeholder or a malformed value, and every gate of the new build chain refuses what it must.

build.sh's pin gates run with the fake `container` (tests/fake-container): a placeholder is exit 13, a malformed value exit 2, both
before any `container build`. The bash pins (BASH_SRC_SHA256, BASH_PATCHES_SHA256, BASH_BIN_SHA256) are UNSET in the repo until
`build.sh --resolve-tools --write-pin` has run, so the gates that come after them run on a lib copy where the tests fill them
(conftest.fill_bash_pins). verify-tools.sh --manifest runs on the real TOOLS.toml and on seeded copies; the awk reader
(tools.sh) must agree with tomllib. base-pins.sh runs with a fake cosign, eqc_json.py base-verify on crafted index/manifest
files, the perl shim against /usr/bin/perl, untar.py with tarfile.open patched to read a gzip tarball (the test interpreter has
no zstd), tc/build-bash.sh (POSIX sh) with fake curl/gpg/tar/configure/... on PATH, build.sh --resolve-tools/--write-pin with
the fake CLI printing a bash-report log. A mutated copy of the product directory can be tested by pointing EQ_CONTAINER_LIB at it.
Run: /Users/pmrj/.claude/venvs/tools/bin/python -m pytest -q tests/test_eq_container_pins.py
"""
import hashlib
import importlib.util
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import tomllib
from pathlib import Path

import pytest

from conftest import BASH, BASH_PIN_VALUES, EQC_LIB, fill_bash_pins, set_key, set_pin, set_tool

ROOT = Path(__file__).resolve().parent.parent
_TMP = Path(tempfile.mkdtemp(prefix="eqc-pins-"))      # TMPDIR of the tools run on a lib copy (the default one may be read-only)
# bash 3.2 matches a bracket range ([a-f]) by the locale's collation: under a UTF-8 locale `*[!0-9a-f]*` let A-E through, so the
# format gates are also run under one (skipped where the machine has none)
UTF8 = next((loc for loc in ("en_US.UTF-8", "C.UTF-8", "pt_PT.UTF-8")
             if loc in subprocess.run(["locale", "-a"], capture_output=True, text=True, check=False).stdout.split()), None)
needs_utf8 = pytest.mark.skipif(UTF8 is None, reason="no UTF-8 locale on this machine")
BASH_KEYS = sorted(BASH_PIN_VALUES)
D = "a" * 64


def sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def lib_digest(lib: Path) -> str:
    h = hashlib.sha256()
    for p in sorted(lib.rglob("*")):
        if p.is_file():
            h.update(str(p.relative_to(lib)).encode() + b"\0" + p.read_bytes())
    return h.hexdigest()


def copy_lib(dst: Path) -> Path:
    shutil.copytree(EQC_LIB, dst, ignore=shutil.ignore_patterns(".state", "__pycache__"))
    return dst


@pytest.fixture
def pins_lib(tmp_path):
    return copy_lib(tmp_path / "eq-container-p")


@pytest.fixture
def filled(pins_lib):
    """The lib copy with the three bash pins resolved (what --write-pin leaves behind): every later gate is reachable."""
    fill_bash_pins(pins_lib)
    return pins_lib


def unset_bash(lib: Path):
    """The lib copy in the state the repo ships: the bash pins UNSET in PINS and the Dockerfile, PLACEHOLDER in TOOLS.toml."""
    for k in BASH_KEYS:
        set_pin(lib, k, "UNSET", files=("PINS", "Dockerfile.minimal"))
    for k in ("sha256", "file_sha256", "checksum_source"):
        set_tool(lib, "bash", k, "PLACEHOLDER")


def bash_env(locale: str = "C", **extra) -> dict:
    e = {"PATH": "/usr/bin:/bin", "LC_ALL": locale, "TMPDIR": str(_TMP), "HOME": str(_TMP)}
    e.update(extra)
    return e


def run_script(lib: Path, script: str, *args, locale: str = "C", **extra):
    return subprocess.run([BASH, str(lib / script), *args], capture_output=True, text=True, timeout=120, check=False,
                          env=bash_env(locale, **extra))


def vt(lib: Path, *args, locale: str = "C"):
    return run_script(lib, "verify-tools.sh", "--manifest", *args, locale=locale)


def _no_build(env) -> bool:
    return not [c for c in env.calls() if c and c[0] == "build"]


def pending(out: str) -> set:
    """{(tool, key)} of the `PENDING tool NAME: KEY is PLACEHOLDER` lines."""
    return {(ln.split()[2].rstrip(":"), ln.split()[3]) for ln in out.splitlines() if ln.startswith("PENDING tool ")}


BASH_PENDING = {("bash", "sha256"), ("bash", "file_sha256"), ("bash", "checksum_source")}


# ================================================================================ build.sh: placeholder 13, malformed 2
def test_core_stops_at_13_while_the_bash_pins_are_unset(eqc_env, pins_lib):
    """The state the repo ships: exit 13 before any build, naming each unset pin and the command that fills them."""
    unset_bash(pins_lib)
    p = eqc_env.run("build.sh", "--profiles", "core", "--yes", lib=pins_lib)
    assert p.returncode == 13, (p.stdout, p.stderr)
    for k in BASH_KEYS:
        assert "pin %s is a placeholder in PINS" % k in p.stderr, p.stderr
    assert "build.sh --resolve-tools" in p.stderr and "--write-pin" in p.stderr
    assert _no_build(eqc_env)


@pytest.mark.parametrize("key", BASH_KEYS)
@pytest.mark.parametrize("where", ["PINS", "Dockerfile.minimal"])
def test_build_stops_at_a_placeholder_bash_pin(eqc_env, filled, key, where):
    """One bash pin UNSET in PINS or only in the Dockerfile ARG (the other holds a value): exit 13 naming the pin and the file."""
    set_pin(filled, key, "UNSET", files=(where,))
    p = eqc_env.run("build.sh", "--profiles", "core", "--yes", lib=filled)
    assert p.returncode == 13, (p.stdout, p.stderr)
    assert "pin %s is a placeholder in %s" % (key, where) in p.stderr and "--resolve-tools" in p.stderr, p.stderr
    assert _no_build(eqc_env)


@pytest.mark.parametrize("value", ["", "TODO", "fill-TODO-later"])
def test_build_a_todo_or_empty_pin_is_a_placeholder(eqc_env, filled, value):
    set_pin(filled, "BASH_BIN_SHA256", value, files=("PINS", "Dockerfile.minimal"))
    p = eqc_env.run("build.sh", "--profiles", "core", "--yes", lib=filled)
    assert p.returncode == 13 and "pin BASH_BIN_SHA256 is a placeholder in PINS" in p.stderr, (p.returncode, p.stderr)
    assert _no_build(eqc_env)


def test_a_placeholder_wins_over_a_malformed_value(eqc_env, filled):
    """A pin still UNSET (13: a maintainer step) is reported even when another pin is malformed (2)."""
    set_pin(filled, "LEAN_SHA256", "xyz", files=("PINS", "Dockerfile.minimal"))
    set_pin(filled, "BASH_SRC_SHA256", "UNSET", files=("PINS", "Dockerfile.minimal"))
    p = eqc_env.run("build.sh", "--profiles", "core", "--yes", lib=filled)
    assert p.returncode == 13, (p.returncode, p.stderr)
    assert "pin LEAN_SHA256 is malformed" in p.stderr and "pin BASH_SRC_SHA256 is a placeholder" in p.stderr
    assert _no_build(eqc_env)


def test_build_stops_at_a_placeholder_tool_checksum_source(eqc_env, filled):
    """PINS and the Dockerfile resolved but the bash entry of TOOLS.toml still says PLACEHOLDER (checksum_source, which no pin
    mirrors): the manifest gate is exit 13, nothing built."""
    set_tool(filled, "bash", "checksum_source", "PLACEHOLDER")
    p = eqc_env.run("build.sh", "--profiles", "core", "--yes", lib=filled)
    assert p.returncode == 13, (p.stdout, p.stderr)
    assert "PENDING tool bash: checksum_source is PLACEHOLDER" in p.stderr and "unresolved tool pin in TOOLS.toml" in p.stderr
    assert _no_build(eqc_env)


@pytest.mark.parametrize("key, want", [("sha256", "BASH_SRC_SHA256"), ("file_sha256", "BASH_BIN_SHA256")])
def test_build_a_tool_placeholder_against_a_resolved_pin_is_invalid(eqc_env, filled, key, want):
    """TOOLS.toml says PLACEHOLDER while PINS holds the value: the two disagree, exit 2 (not 13)."""
    set_tool(filled, "bash", key, "PLACEHOLDER")
    p = eqc_env.run("build.sh", "--profiles", "core", "--yes", lib=filled)
    assert p.returncode == 2, (p.stdout, p.stderr)
    assert "PROBLEM tool bash: %s differs from PINS %s" % (key, want) in p.stderr and "TOOLS.toml is invalid for min-both" in p.stderr
    assert _no_build(eqc_env)


MALFORMED = [
    ("BUILDER_IMAGE", "buildpack-deps:trixie"),                                       # no digest: a mutable tag
    ("BUILDER_IMAGE", "buildpack-deps:trixie@sha256:" + "a" * 63),
    ("BUILDER_IMAGE", "buildpack-deps:latest@sha256:" + D),
    ("BUILDER_IMAGE", "buildpack-deps-debug:trixie@sha256:" + D),
    ("BUILDER_IMAGE", "buildpack-deps:trixie@sha256:" + "A" * 64),
    ("BUILDER_IMAGE", "Buildpack-deps:trixie@sha256:" + D),
    ("BUILDER_IMAGE", "buildpack-deps:trixie@sha256:" + D + " --x"),
    ("MUSL_BUILDER_IMAGE", "alpine:3.24"),
    ("MUSL_BUILDER_IMAGE", "alpine:latest@sha256:" + D),
    ("DISTROLESS_CC", "gcr.io/distroless/cc-debian13:debug-nonroot@sha256:" + D),
    ("DISTROLESS_CC", "gcr.io/distroless/cc-debian13:latest@sha256:" + D),
    ("DISTROLESS_CC", "gcr.io/distroless/cc-debian13:nonroot"),
    ("DISTROLESS_CC", "gcr.io/distroless/cc-debian12@sha256:" + D),
    ("DISTROLESS_CC", "docker.io/library/cc-debian13@sha256:" + D),
    ("DISTROLESS_CC", "gcr.io/distroless/CC-debian13@sha256:" + D),
    ("DISTROLESS_CC", "gcr.io/distroless/cc-debian13@sha256:" + "B" * 64),
    ("DISTROLESS_CC_ARM64", "sha256:" + "a" * 63),
    ("DISTROLESS_CC_ARM64", D),
    ("DISTROLESS_CC_ARM64", "sha256:" + "A" * 64),
    ("BUSYBOX_ROOTFS_URL", "http://raw.example.test/rootfs.tar.gz"),
    ("BUSYBOX_ROOTFS_URL", "https://u:p@raw.example.test/rootfs.tar.gz"),
    ("BUSYBOX_ROOTFS_URL", "https://raw.example.test/rootfs.tar.gz;rm"),
    ("BUSYBOX_ROOTFS_URL", "https://raw.example.test/root fs.tar.gz"),
    ("BUSYBOX_ROOTFS_URL", "ftp://raw.example.test/rootfs.tar.gz"),
    ("BASH_GPG_FPR", "7C0135FB088AAF6C66C650B9BB5869F064EA74A"),                       # 39 characters
    ("BASH_GPG_FPR", "7c0135fb088aaf6c66c650b9bb5869f064ea74ab"),                      # lowercase
    ("BASH_GPG_FPR", "7C0135FB088AAF6C66C650B9BB5869F064EA74AG"),
    ("BASH_PATCHLEVEL", "020"), ("BASH_PATCHLEVEL", "1000"), ("BASH_PATCHLEVEL", "2x"), ("BASH_PATCHLEVEL", "-1"),
    ("BASH_BASELINE", "5"), ("BASH_BASELINE", "5.3.1"), ("BASH_BASELINE", ".3"), ("BASH_BASELINE", "5."), ("BASH_BASELINE", "5.x"),
    ("BASH_SRC_SHA256", "1" * 63), ("BASH_PATCHES_SHA256", "F" * 64), ("BASH_BIN_SHA256", "xyz"),
    ("LEAN_SHA256", "f" * 63), ("UV_SHA256", "F" * 64), ("PYTHON_SHA256", "TBD"), ("BUSYBOX_SHA256", "c" * 65),
    ("BUSYBOX_ROOTFS_SHA256", "xyz"), ("JQ_SHA256", "c" * 63),
    ("MATHLIB_REV", "d13f23b7"), ("MATHLIB_REV", "D" * 40),
    ("LEAN_VERSION", "4.34.1;x"), ("JQ_VERSION", "1.8 2"), ("PBS_TAG", "a/b"), ("PYTHON_VERSION", "3.14.8$x"),
]
# the same classes under a UTF-8 locale, where a bracket range would let A-E, accented letters or any word through
MALFORMED_UTF8 = [
    ("LEAN_SHA256", "A" * 64), ("UV_SHA256", "Ab" * 32), ("BUSYBOX_SHA256", "xyz"), ("BASH_SRC_SHA256", "C" * 64),
    ("BUILDER_IMAGE", "buildpack-deps:trixie@sha256:" + "B" * 64), ("BUILDER_IMAGE", "Buildpack-deps:trixie@sha256:" + D),
    ("DISTROLESS_CC", "gcr.io/distroless/cc-debian13@sha256:" + "B" * 64), ("DISTROLESS_CC_ARM64", "sha256:" + "A" * 64),
    ("BASH_GPG_FPR", "7c0135fb088aaf6c66c650b9bb5869f064ea74ab"), ("BASH_GPG_FPR", "7C0135FB088AAF6C66C650B9BB5869F064EA74\u00c4"),
    ("BASH_BASELINE", "5.x"), ("BASH_PATCHLEVEL", "2\u00c4"), ("MATHLIB_REV", "D" * 40), ("LEAN_VERSION", "4.34.1\u00c4"),
    ("BUSYBOX_ROOTFS_URL", "https://raw.example.test/r\u00e4.tar.gz"),
]


def _set_everywhere(lib: Path, key: str, value: str):
    """The same value in PINS and in every Dockerfile that has the ARG (so the two agree and only the format is at fault)."""
    files = ["PINS"] + [f for f in ("Dockerfile.minimal", "Dockerfile.toolchains")
                        if re.search(r"^ARG %s=" % key, (lib / f).read_text(), re.MULTILINE)]
    set_pin(lib, key, value, files=files)


def _malformed_ids(rows):
    return ["%s=%s" % (k, v[:28]) for k, v in rows]


@pytest.mark.parametrize("key, value", MALFORMED, ids=_malformed_ids(MALFORMED))
def test_build_refuses_a_malformed_pin_before_building(eqc_env, filled, key, value):
    """Exit 2 naming the key, nothing built (a BASE_IMAGE without a digest once built from the mutable tag)."""
    _set_everywhere(filled, key, value)
    p = eqc_env.run("build.sh", "--profiles", "core", "--yes", lib=filled)
    assert p.returncode == 2, (p.returncode, p.stdout, p.stderr)
    assert "pin %s is malformed in PINS" % key in p.stderr and _no_build(eqc_env), p.stderr


@needs_utf8
@pytest.mark.parametrize("key, value", MALFORMED_UTF8, ids=_malformed_ids(MALFORMED_UTF8))
def test_build_refuses_a_malformed_pin_under_a_utf8_locale(eqc_env, filled, key, value):
    """The installer runs build.sh in the user's locale: a range such as [0-9a-f] matched A-E there (bash 3.2 collation)."""
    _set_everywhere(filled, key, value)
    p = eqc_env.run("build.sh", "--profiles", "core", "--yes", lib=filled, LC_ALL=UTF8)
    assert p.returncode == 2, (p.returncode, p.stdout, p.stderr)
    assert "pin %s is malformed in PINS" % key in p.stderr and _no_build(eqc_env), p.stderr


@pytest.mark.parametrize("key, value", [("DISTROLESS_CC", "gcr.io/distroless/cc-debian13:debug-nonroot@sha256:" + D),
                                        ("DISTROLESS_CC_ARM64", D), ("BUILDER_IMAGE", "buildpack-deps:trixie")])
def test_toolchain_images_check_their_own_three_pins(eqc_env, filled, key, value):
    """tc-go needs BUILDER_IMAGE, DISTROLESS_CC and DISTROLESS_CC_ARM64 (Dockerfile.toolchains): malformed -> 2, no build."""
    _set_everywhere(filled, key, value)
    p = eqc_env.run("build.sh", "--profiles", "go", "--yes", lib=filled)
    assert p.returncode == 2 and "pin %s is malformed in PINS" % key in p.stderr and _no_build(eqc_env), (p.returncode, p.stderr)


def test_toolchain_pin_differing_from_its_dockerfile_is_refused(eqc_env, filled):
    set_pin(filled, "DISTROLESS_CC_ARM64", "sha256:" + D, files=("PINS",))
    p = eqc_env.run("build.sh", "--profiles", "go", "--yes", lib=filled)
    assert p.returncode == 2 and "pin DISTROLESS_CC_ARM64 differs: PINS=sha256:%s Dockerfile.toolchains=" % D in p.stderr, p.stderr
    assert _no_build(eqc_env)


# ------------------------------------------------------------------------------- pins_check: the structure of PINS and the ARGs
def test_a_key_twice_in_pins_is_refused(eqc_env, filled):
    with open(filled / "PINS", "a") as f:
        f.write("LEAN_VERSION=4.34.1\n")
    p = eqc_env.run("build.sh", "--profiles", "core", "--yes", lib=filled)
    assert p.returncode == 2 and "PINS holds 2 'LEAN_VERSION=' lines, want exactly one" in p.stderr, p.stderr
    assert _no_build(eqc_env)


def test_two_global_arg_lines_are_refused(eqc_env, filled):
    df = filled / "Dockerfile.minimal"
    df.write_text(df.read_text().replace("ARG LEAN_VERSION=4.34.1\n", "ARG LEAN_VERSION=4.34.1\nARG LEAN_VERSION=4.34.1\n", 1))
    p = eqc_env.run("build.sh", "--profiles", "core", "--yes", lib=filled)
    assert p.returncode == 2 and "holds more than one 'ARG LEAN_VERSION=' line" in p.stderr, p.stderr
    assert _no_build(eqc_env)


def test_an_arg_with_a_value_only_inside_a_stage_is_refused(eqc_env, filled):
    """The global default removed and the value put on the stage's ARG: a stage-local default would shadow PINS."""
    df = filled / "Dockerfile.minimal"
    t = df.read_text()
    t = t.replace("ARG LEAN_VERSION=4.34.1\n", "", 1)
    t = t.replace("ARG LEAN_VERSION\n", "ARG LEAN_VERSION=4.34.1\n", 1)
    df.write_text(t)
    p = eqc_env.run("build.sh", "--profiles", "core", "--yes", lib=filled)
    assert p.returncode == 2 and "sets 'ARG LEAN_VERSION=' inside a stage" in p.stderr, p.stderr
    assert _no_build(eqc_env)


def test_a_missing_global_arg_is_refused(eqc_env, filled):
    df = filled / "Dockerfile.minimal"
    df.write_text(df.read_text().replace("ARG LEAN_VERSION=4.34.1\n", "", 1))
    p = eqc_env.run("build.sh", "--profiles", "core", "--yes", lib=filled)
    assert p.returncode == 2 and "has no global 'ARG LEAN_VERSION=' line" in p.stderr, p.stderr
    assert _no_build(eqc_env)


def test_pins_and_the_arg_must_agree(eqc_env, filled):
    set_pin(filled, "LEAN_VERSION", "4.34.2", files=("PINS",))
    p = eqc_env.run("build.sh", "--profiles", "core", "--yes", lib=filled)
    assert p.returncode == 2 and "pin LEAN_VERSION differs: PINS=4.34.2 Dockerfile.minimal=4.34.1" in p.stderr, p.stderr
    assert _no_build(eqc_env)


def test_build_check_reports_a_malformed_pin(eqc_env, filled):
    set_pin(filled, "LEAN_SHA256", "f" * 63, files=("PINS", "Dockerfile.minimal"))
    eqc_env.record("min-both", EQ_INPUTS_SHA256="x")
    p = eqc_env.run("build.sh", "--only", "min-both", "--check", lib=filled)
    assert p.returncode == 11 and "pin LEAN_SHA256 is malformed" in p.stdout, p.stdout


def test_build_check_reports_a_placeholder_pin(eqc_env, pins_lib):
    unset_bash(pins_lib)
    eqc_env.record("min-both", EQ_INPUTS_SHA256="x")
    p = eqc_env.run("build.sh", "--only", "min-both", "--check", lib=pins_lib)
    assert p.returncode == 11 and "pin BASH_SRC_SHA256 is a placeholder in PINS" in p.stdout, p.stdout


# ================================================================================ verify-tools.sh --manifest
def test_real_manifest_core_pins():
    """The repo's TOOLS.toml: only the bash entry may still be pending (sha256, file_sha256, checksum_source), and once it is
    not, `core` passes; every other core tool is fully pinned; the distroless base files hash to the pins (21 layers)."""
    p = vt(EQC_LIB, "--profiles", "core")
    assert p.returncode in (0, 13), (p.stdout, p.stderr)
    pend = pending(p.stdout)
    assert pend <= BASH_PENDING, p.stdout
    assert (p.returncode == 13) == bool(pend) and "PROBLEM" not in p.stdout
    assert "distroless base: base/distroless-cc-debian13-nonroot.index.json" in p.stdout and "21 layers" in p.stdout, p.stdout
    m = tomllib.loads((EQC_LIB / "TOOLS.toml").read_text())
    tools = {t["name"]: t for t in m["tool"]}
    for img in ("min-both", "min-py"):
        for name in next(i for i in m["image"] if i["name"] == img)["tools"]:
            if name == "bash":
                continue
            t = tools[name]
            assert t["version"] != "PLACEHOLDER" and "PLACEHOLDER" not in t["checksum_source"], name
            assert re.fullmatch(r"[0-9a-f]{64}", t["sha256"]), name
    pins = dict(ln.split("=", 1) for ln in (EQC_LIB / "PINS").read_text().splitlines() if re.match(r"^[A-Z0-9_]+=", ln))
    unset = {k for k in BASH_KEYS if pins[k] == "UNSET"}
    assert (tools["bash"]["sha256"] == "PLACEHOLDER") == ("BASH_SRC_SHA256" in unset), "PINS and TOOLS.toml disagree"
    assert (tools["bash"]["file_sha256"] == "PLACEHOLDER") == ("BASH_BIN_SHA256" in unset)


def test_real_manifest_extension_profiles_pass():
    p = vt(EQC_LIB, "--profiles", "node,go,julia,jvm")
    assert p.returncode == 0 and "PENDING" not in p.stdout and "PROBLEM" not in p.stdout, p.stdout


def test_manifest_placeholder_is_pending_and_allow_placeholder_lists_it(pins_lib):
    unset_bash(pins_lib)
    p = vt(pins_lib, "--profiles", "core")
    assert p.returncode == 13 and pending(p.stdout) == BASH_PENDING and "PROBLEM" not in p.stdout, p.stdout
    p = vt(pins_lib, "--profiles", "core", "--allow-placeholder")
    assert p.returncode == 0 and pending(p.stdout) == BASH_PENDING, p.stdout


def test_manifest_resolved_bash_passes(filled):
    p = vt(filled, "--profiles", "core")
    assert p.returncode == 0 and "TOOLS: manifest OK" in p.stdout and "PENDING" not in p.stdout, p.stdout


def _pin(key, value):
    return lambda lib: set_pin(lib, key, value)


def _tool(tool, key, value):
    return lambda lib: set_tool(lib, tool, key, value)


def _drop_tool_key(tool, key):
    return lambda lib: set_key(lib, "tool", tool, key, "", delete=True)


def _tamper_base(name):
    def f(lib):
        with open(lib / "base" / name, "ab") as fh:
            fh.write(b"\n")
    return f


INDEX = "distroless-cc-debian13-nonroot.index.json"
MANIFEST = "distroless-cc-debian13-nonroot.arm64.manifest.json"
# (id, state of the bash pins, mutation of the lib copy, profiles, exit code, line the output must hold)
SEEDS = [
    ("apt-tool-in-min-py", "unset", _tool("jq", "url", "apt:jq"), "core", 2, "PROBLEM tool jq: an apt: url"),
    ("apt-tool-in-tc-go", "unset", _tool("go", "url", "apt:golang"), "go", 2, "PROBLEM tool go: an apt: url"),
    ("distro-package", "unset", _tool("jq", "provenance", "distro-package"), "core",
     2, "PROBLEM tool jq: provenance distro-package is refused"),
    ("dynamic-tool-in-the-scratch-image", "unset", _tool("go", "linkage", "dynamic"), "go",
     2, "PROBLEM image tc-go: tool go is not static"),
    ("dynamic-tool-in-a-distroless-image-is-fine", "unset", _tool("node", "linkage", "dynamic"), "node", 0, "manifest OK"),
    ("bad-file-sha256", "unset", _tool("bash", "file_sha256", "xyz"), "core", 2,
     "PROBLEM tool bash: file_sha256 is not 64 lowercase hex or PLACEHOLDER"),
    ("bad-file-sha256-uppercase", "unset", _tool("busybox", "file_sha256", "C" * 64), "core", 2,
     "PROBLEM tool busybox: file_sha256 is not 64 lowercase hex"),
    ("file-sha256-placeholder-is-pending", "unset", _tool("bash", "file_sha256", "PLACEHOLDER"), "core", 13,
     "PENDING tool bash: file_sha256 is PLACEHOLDER"),
    ("built-from-source-without-file-sha256", "filled", _drop_tool_key("bash", "file_sha256"), "core", 2,
     "PROBLEM tool bash: built-from-source needs file_sha256"),
    ("built-from-source-without-a-recipe", "filled", _drop_tool_key("bash", "recipe"), "core", 2,
     "PROBLEM tool bash: built-from-source needs a recipe"),
    ("recipe-edited-without-repinning", "filled", _tool("bash", "recipe_sha256", "9" * 64), "core", 2,
     "PROBLEM tool bash: recipe tc/build-bash.sh does not hash to recipe_sha256"),
    ("http-url", "filled", _tool("uv", "url", "http://example.test/uv.tar.gz"), "core", 2, "PROBLEM tool uv: url must be https://"),
    ("credentials-in-url", "filled", _tool("uv", "url", "https://u:p@example.test/uv.tar.gz"), "core", 2,
     "PROBLEM tool uv: credentials in url"),
    ("unknown-base", "filled", lambda lib: set_key(lib, "image", "min-both", "base", "centos"), "core", 2,
     "PROBLEM image min-both: base 'centos' is not one of: scratch distroless-cc"),
    ("deferred-profile-with-images", "filled",
     lambda lib: set_key(lib, "profile", "rust", "images", '["tc-go"]', raw=True), "core", 2,
     "PROBLEM profile rust: deferred but lists images"),
    ("profile-without-images-or-reason", "filled", lambda lib: set_key(lib, "profile", "rust", "deferred", "", delete=True),
     "core", 2, "PROBLEM profile rust: no images and no deferred reason"),
    ("profile-with-an-empty-image-list", "filled", lambda lib: set_key(lib, "profile", "core", "images", "[]", raw=True),
     "core", 2, "PROBLEM profile core: no images and no deferred reason"),
    # PINS pairs: lean, uv, python (+ PBS_TAG), busybox (three), jq, bash (three, and the version)
    ("pair-lean-version", "unset", _pin("LEAN_VERSION", "9.9.9"), "core", 2, "PROBLEM tool lean: version 4.34.1 differs from PINS LEAN_VERSION=9.9.9"),
    ("pair-lean-sha256", "unset", _pin("LEAN_SHA256", "9" * 64), "core", 2, "PROBLEM tool lean: sha256 differs from PINS LEAN_SHA256"),
    ("pair-uv-version", "unset", _pin("UV_VERSION", "9.9.9"), "core", 2, "PROBLEM tool uv: version 0.12.22 differs from PINS UV_VERSION=9.9.9"),
    ("pair-uv-sha256", "unset", _pin("UV_SHA256", "9" * 64), "core", 2, "PROBLEM tool uv: sha256 differs from PINS UV_SHA256"),
    ("pair-python-version", "unset", _pin("PYTHON_VERSION", "9.9.9"), "core", 2,
     "PROBLEM tool python: version 3.14.8 differs from PINS PYTHON_VERSION=9.9.9"),
    ("pair-python-sha256", "unset", _pin("PYTHON_SHA256", "9" * 64), "core", 2, "PROBLEM tool python: sha256 differs from PINS PYTHON_SHA256"),
    ("pair-python-tag", "unset", _pin("PBS_TAG", "19990101"), "core", 2, "PROBLEM tool python: tag differs from PINS PBS_TAG"),
    ("pair-busybox-rootfs-sha256", "unset", _pin("BUSYBOX_ROOTFS_SHA256", "9" * 64), "core", 2,
     "PROBLEM tool busybox: sha256 differs from PINS BUSYBOX_ROOTFS_SHA256"),
    ("pair-busybox-file-sha256", "unset", _pin("BUSYBOX_SHA256", "9" * 64), "core", 2,
     "PROBLEM tool busybox: file_sha256 differs from PINS BUSYBOX_SHA256"),
    ("pair-busybox-url", "unset", _pin("BUSYBOX_ROOTFS_URL", "https://example.test/rootfs.tar.gz"), "core", 2,
     "PROBLEM tool busybox: url differs from PINS BUSYBOX_ROOTFS_URL"),
    ("pair-jq-version", "unset", _pin("JQ_VERSION", "9.9"), "core", 2, "PROBLEM tool jq: version 1.8.2 differs from PINS JQ_VERSION=9.9"),
    ("pair-jq-sha256", "unset", _pin("JQ_SHA256", "9" * 64), "core", 2, "PROBLEM tool jq: sha256 differs from PINS JQ_SHA256"),
    ("pair-bash-src-sha256", "filled", _pin("BASH_SRC_SHA256", "9" * 64), "core", 2,
     "PROBLEM tool bash: sha256 differs from PINS BASH_SRC_SHA256"),
    ("pair-bash-bin-sha256", "filled", _pin("BASH_BIN_SHA256", "9" * 64), "core", 2,
     "PROBLEM tool bash: file_sha256 differs from PINS BASH_BIN_SHA256"),
    ("pair-bash-patchlevel", "filled", _pin("BASH_PATCHLEVEL", "19"), "core", 2,
     "PROBLEM tool bash: version 5.3.20 differs from PINS BASH_BASELINE.BASH_PATCHLEVEL=5.3.19"),
    ("pair-bash-baseline", "filled", _pin("BASH_BASELINE", "5.4"), "core", 2,
     "PROBLEM tool bash: version 5.3.20 differs from PINS BASH_BASELINE.BASH_PATCHLEVEL=5.4.20"),
    ("bash-half-applied-pins-only", "unset", _pin("BASH_SRC_SHA256", "9" * 64), "core", 2,
     "PROBLEM tool bash: sha256 differs from PINS BASH_SRC_SHA256"),
    ("bash-half-applied-tool-only", "filled", _pin("BASH_BIN_SHA256", "UNSET"), "core", 2,
     "PROBLEM tool bash: file_sha256 differs from PINS BASH_BIN_SHA256"),
    # the offline check of the distroless base
    ("base-index-byte-added", "filled", _tamper_base(INDEX), "core", 2, "PROBLEM distroless base:"),
    ("base-manifest-byte-added", "filled", _tamper_base(MANIFEST), "core", 2, "PROBLEM distroless base:"),
    ("base-arm64-pin-changed", "filled", _pin("DISTROLESS_CC_ARM64", "sha256:" + "9" * 64), "core", 2, "PROBLEM distroless base:"),
    ("base-index-pin-changed", "filled",
     _pin("DISTROLESS_CC", "gcr.io/distroless/cc-debian13@sha256:" + "9" * 64), "core", 2, "PROBLEM distroless base:"),
    ("base-index-missing", "filled", lambda lib: (lib / "base" / INDEX).unlink(), "core", 2, "PROBLEM distroless base:"),
    ("base-not-checked-for-a-scratch-image", "filled", _tamper_base(INDEX), "go", 0, "manifest OK"),
]


@pytest.mark.parametrize("base, mutate, profiles, rc, needle", [s[1:] for s in SEEDS], ids=[s[0] for s in SEEDS])
def test_manifest_seeded_faults(pins_lib, base, mutate, profiles, rc, needle):
    if base == "unset":
        unset_bash(pins_lib)
    else:
        fill_bash_pins(pins_lib)
    mutate(pins_lib)
    p = vt(pins_lib, "--profiles", profiles)
    assert p.returncode == rc, (p.returncode, p.stdout, p.stderr)
    assert needle in p.stdout, p.stdout
    if rc == 2:
        assert "TOOLS: INVALID" in p.stdout


@pytest.mark.parametrize("key, value", [("sha256", "c" * 63), ("sha256", "C" * 64), ("sha256", "TODO"), ("sha256", "n/a")])
def test_manifest_a_malformed_sha256_is_a_problem(pins_lib, key, value):
    unset_bash(pins_lib)
    set_tool(pins_lib, "uv", key, value)
    p = vt(pins_lib, "--profiles", "core")
    assert p.returncode == 2 and "PROBLEM tool uv: sha256" in p.stdout, p.stdout


@needs_utf8
@pytest.mark.parametrize("value", ["C" * 64, "Ab" * 32])
def test_manifest_uppercase_sha256_is_invalid_under_a_utf8_locale(pins_lib, value):
    unset_bash(pins_lib)
    set_tool(pins_lib, "uv", "sha256", value)
    p = vt(pins_lib, "--profiles", "core", locale=UTF8)
    assert p.returncode == 2 and "PROBLEM tool uv: sha256" in p.stdout, p.stdout


@needs_utf8
def test_manifest_uppercase_file_sha256_is_invalid_under_a_utf8_locale(pins_lib):
    set_tool(pins_lib, "busybox", "file_sha256", "C" * 64)
    p = vt(pins_lib, "--profiles", "core", locale=UTF8)
    assert p.returncode == 2 and "PROBLEM tool busybox: file_sha256" in p.stdout, p.stdout


def test_manifest_placeholders_outside_the_selected_profiles_do_not_block(pins_lib):
    unset_bash(pins_lib)
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


def tm(snippet: str, lib: Path = None):
    src = '. "%s/tools.sh"; tm_load "%s/TOOLS.toml" || exit 3; %s' % (lib or EQC_LIB, lib or EQC_LIB, snippet)
    return subprocess.run([BASH, "-c", src], capture_output=True, text=True, timeout=60, check=False, env=bash_env())


def test_all_leaves_out_the_deferred_and_the_explicit_profiles():
    p = tm('tm_expand_profiles all | tr "\\n" " "')
    assert p.returncode == 0 and p.stdout.split() == ["core", "node", "go", "julia", "jvm"], p.stdout
    m = tomllib.loads((EQC_LIB / "TOOLS.toml").read_text())
    assert {pr["name"] for pr in m["profile"] if "deferred" in pr} == {"rust", "haskell"}
    assert [pr["name"] for pr in m["profile"] if pr.get("explicit") == "yes"] == ["candidates"]


def test_refuse_deferred_names_every_deferred_profile():
    p = tm('tm_refuse_deferred "core rust node haskell"; echo "rc=$?"')
    assert "rc=10" in p.stdout and "profile rust is deferred" in p.stderr and "profile haskell is deferred" in p.stderr, p
    assert "core is deferred" not in p.stderr and "node is deferred" not in p.stderr
    p = tm('tm_refuse_deferred "core node go julia jvm candidates"; echo "rc=$?"')
    assert "rc=0" in p.stdout and p.stderr == ""


# ================================================================================ deferred profiles (build.sh, eq-container.sh)
@pytest.mark.parametrize("profiles", ["rust", "haskell", "core,rust", "rust,haskell", "node,haskell"])
def test_build_refuses_a_deferred_profile_with_exit_10(eqc_env, filled, profiles):
    p = eqc_env.run("build.sh", "--profiles", profiles, "--yes", lib=filled)
    assert p.returncode == 10, (p.stdout, p.stderr)
    assert "is deferred" in p.stderr and "Nothing is built for it" in p.stderr, p.stderr
    assert eqc_env.calls() == []


@pytest.mark.parametrize("profiles", ["rust", "haskell"])
def test_build_check_and_uninstall_refuse_a_deferred_profile_too(eqc_env, filled, profiles):
    for flag in ("--check", "--uninstall"):
        p = eqc_env.run("build.sh", "--profiles", profiles, flag, "--yes", lib=filled)
        assert p.returncode == 10 and "is deferred" in p.stderr, (flag, p.returncode, p.stderr)


def test_set_all_and_profiles_all_never_name_a_deferred_profile(eqc_env, filled):
    p = eqc_env.run("build.sh", "--profiles", "all", "--dry-run", lib=filled)
    assert p.returncode == 0, (p.stdout, p.stderr)
    names = [ln.split()[0] for ln in p.stdout.splitlines() if re.match(r"^  (min|tc)-", ln)]
    assert names == ["min-both", "min-py", "tc-node", "tc-go", "tc-julia", "tc-jvm"], p.stdout
    p = eqc_env.run("build.sh", "--set", "all", "--dry-run", lib=filled)
    assert [ln.split()[0] for ln in p.stdout.splitlines() if re.match(r"^  (min|tc)-", ln)] == ["min-lean", "min-py", "min-both"]


@pytest.fixture
def stub_driver(pins_lib, tmp_path):
    """The real eq-container.sh over a stub build.sh/verify-tools.sh/probe.sh that log their argv."""
    for s in ("build.sh", "verify-tools.sh", "probe.sh"):
        (pins_lib / s).write_text('#!/bin/bash\nprintf "%s\\n" "$*" >> "$STUB_LOG.' + s + '"\nexit ${STUB_RC:-0}\n')
    return pins_lib


@pytest.mark.parametrize("profiles", ["rust", "haskell", "node,rust"])
def test_install_with_a_deferred_profile_is_a_skip_with_the_reason(eqc_env, stub_driver, tmp_path, profiles):
    p = eqc_env.run("eq-container.sh", "install", "--yes", "--profiles", profiles, lib=stub_driver, STUB_LOG=tmp_path / "stub")
    assert p.returncode == 10, (p.returncode, p.stdout, p.stderr)
    assert eqc_env.status() == "skipped" and "deferred" in eqc_env.status("EQ_CONTAINER_STATUS_WHY")
    assert "needs a linker" in eqc_env.status("EQ_CONTAINER_STATUS_WHY")
    assert not (tmp_path / "stub.build.sh").exists() and eqc_env.calls() == []       # nothing built, no CLI call


def test_install_dry_run_with_a_deferred_profile_writes_no_state(eqc_env, stub_driver, tmp_path):
    p = eqc_env.run("eq-container.sh", "install", "--dry-run", "--profiles", "rust", lib=stub_driver, STUB_LOG=tmp_path / "stub")
    assert p.returncode == 10 and not eqc_env.state.exists(), (p.returncode, p.stderr)


def test_check_defaults_to_the_core_profile(eqc_env, stub_driver, tmp_path):
    p = eqc_env.run("eq-container.sh", "check", lib=stub_driver, STUB_LOG=tmp_path / "stub")
    assert p.returncode == 0, (p.stdout, p.stderr)
    assert (tmp_path / "stub.build.sh").read_text().splitlines() == ["--profiles core --check"]


@pytest.mark.parametrize("args, want", [(["--set", "min"], "--set min --check"), (["--profiles", "node"], "--profiles core,node --check"),
                                        (["--profiles", "core"], "--profiles core --check")])
def test_check_passes_its_selection_on(eqc_env, stub_driver, tmp_path, args, want):
    p = eqc_env.run("eq-container.sh", "check", *args, lib=stub_driver, STUB_LOG=tmp_path / "stub")
    assert p.returncode == 0 and (tmp_path / "stub.build.sh").read_text().splitlines() == [want], p.stderr


def test_check_with_a_deferred_profile_is_refused_by_build_not_skipped(eqc_env, tmp_path):
    """`check` only reads: the real build.sh refuses the deferred profile with its own exit 10."""
    p = eqc_env.run("eq-container.sh", "check", "--profiles", "rust")
    assert p.returncode == 10 and "is deferred" in p.stderr


# ================================================================================ build.sh --resolve-tools / --write-pin
H_SRC, H_PAT, H_BIN = "5" * 64, "6" * 64, "7" * 64
FPR = "7C0135FB088AAF6C66C650B9BB5869F064EA74AB"
SIG_LINE = "SIGNATURES OK: bash-5.3.tar.gz and 20 patches, primary key " + FPR


def report(src=H_SRC, pat=H_PAT, bin_=H_BIN, st="PLACEHOLDER"):
    return "\n".join([SIG_LINE, "PIN BASH_SRC_SHA256 %s pinned: %s" % (src, st), "PIN BASH_PATCHES_SHA256 %s pinned: %s" % (pat, st),
                      "PIN BASH_BIN_SHA256 %s pinned: %s" % (bin_, st)])


def resolve(eqc_env, lib, *args, rep=None, **extra):
    knobs = {"EQ_FAKE_CONTAINER_REPORT": rep if rep is not None else report()}
    knobs.update(extra)
    return eqc_env.run("build.sh", "--resolve-tools", *args, lib=lib, **knobs)


def test_resolve_tools_prints_the_signature_line_and_the_three_pins(eqc_env, pins_lib):
    unset_bash(pins_lib)
    before = lib_digest(pins_lib)
    p = resolve(eqc_env, pins_lib)
    assert p.returncode == 0, (p.stdout, p.stderr)
    assert SIG_LINE in p.stdout and report().splitlines()[1] in p.stdout and report().splitlines()[3] in p.stdout
    assert "to pin: re-run with --write-pin" in p.stdout
    assert lib_digest(pins_lib) == before                                    # nothing is written without --write-pin
    builds = [c for c in eqc_env.calls() if c[0] == "build"]
    assert len(builds) == 1, builds
    b = builds[0]
    assert b[b.index("--target") + 1] == "bash-report" and "--no-cache" in b and b[b.index("-f") + 1] == "Dockerfile.minimal", b
    tag = b[b.index("-t") + 1]
    assert re.fullmatch(r"eq\.invalid/eq-report:\d+", tag) and ["image", "delete", tag] in eqc_env.calls()


def test_resolve_tools_reads_stdout_and_stderr_of_the_build(eqc_env, pins_lib):
    unset_bash(pins_lib)
    lines = report().splitlines()
    p = resolve(eqc_env, pins_lib, rep="\n".join(lines[1:]), EQ_FAKE_CONTAINER_REPORT_ERR=lines[0])
    assert p.returncode == 0 and SIG_LINE in p.stdout, (p.stdout, p.stderr)


def test_resolve_tools_reports_same_and_differs(eqc_env, filled):
    p = resolve(eqc_env, filled, rep=report(st="same"))
    assert p.returncode == 0 and p.stdout.count("pinned: same") == 3, p.stdout


def test_write_pin_pins_everything_and_the_core_gates_then_pass(eqc_env, pins_lib):
    unset_bash(pins_lib)
    p = resolve(eqc_env, pins_lib, "--write-pin")
    assert p.returncode == 0 and "pinned BASH_SRC_SHA256, BASH_PATCHES_SHA256 and BASH_BIN_SHA256" in p.stdout, (p.stdout, p.stderr)
    for f, fmt in (("PINS", "%s=%s"), ("Dockerfile.minimal", "ARG %s=%s")):
        text = (pins_lib / f).read_text()
        for k, v in (("BASH_SRC_SHA256", H_SRC), ("BASH_PATCHES_SHA256", H_PAT), ("BASH_BIN_SHA256", H_BIN)):
            assert (fmt % (k, v)) in text.splitlines(), (f, k)
    bash = next(t for t in tomllib.loads((pins_lib / "TOOLS.toml").read_text())["tool"] if t["name"] == "bash")
    assert bash["sha256"] == H_SRC and bash["file_sha256"] == H_BIN
    assert "GPG-verified" in bash["checksum_source"] and FPR in bash["checksum_source"] and "5.3.tar.gz" in bash["checksum_source"]
    # PINS, the ARGs and the manifest agree now: the manifest passes, and the build gets as far as `container build`
    assert vt(pins_lib, "--profiles", "core").returncode == 0
    q = eqc_env.run("build.sh", "--profiles", "core", "--yes", lib=pins_lib)
    assert q.returncode == 0 and "BUILD: OK" in q.stdout, (q.stdout, q.stderr)
    # the file stays readable by the awk reader (the builder's) and by tomllib
    assert tm('tm_get tool bash sha256', pins_lib).stdout.strip() == H_SRC


@pytest.mark.parametrize("why, rep, rc_build, want", [
    ("build-fails", None, "1", "the bash-report stage failed (rc 1)"),
    ("no-signature-line", "\n".join(report().splitlines()[1:]), "0", "no 'SIGNATURES OK' line"),
    ("a-pin-line-missing", "\n".join(report().splitlines()[:3]), "0", "the report holds 0 values for BASH_BIN_SHA256"),
    ("two-values-for-one-pin", report() + "\nPIN BASH_BIN_SHA256 " + "8" * 64 + " pinned: PLACEHOLDER", "0",
     "the report holds 2 values for BASH_BIN_SHA256"),
    ("63-hex", report(src="5" * 63), "0", "the report holds 0 values for BASH_SRC_SHA256"),
    ("uppercase-hex", report(pat="A" * 64), "0", "the report holds 0 values for BASH_PATCHES_SHA256"),
    ("another-key-only", report().replace("BASH_BIN_SHA256", "BASH_OTHER_SHA256"), "0", "holds 0 values for BASH_BIN_SHA256"),
], ids=["build-fails", "no-signature-line", "a-pin-line-missing", "two-values", "63-hex", "uppercase-hex", "another-key-only"])
def test_resolve_tools_fails_closed_and_writes_nothing(eqc_env, pins_lib, why, rep, rc_build, want):
    unset_bash(pins_lib)
    before = lib_digest(pins_lib)
    p = resolve(eqc_env, pins_lib, "--write-pin", rep=rep, EQ_FAKE_CONTAINER_BUILD_RC=rc_build)
    assert p.returncode == 12, (p.returncode, p.stdout, p.stderr)
    assert want in p.stderr and "PIN BASH_" not in p.stdout, (p.stdout, p.stderr)
    assert lib_digest(pins_lib) == before


def test_resolve_tools_the_same_line_twice_is_one_value(eqc_env, pins_lib):
    unset_bash(pins_lib)
    p = resolve(eqc_env, pins_lib, rep=report() + "\n" + report().splitlines()[3])
    assert p.returncode == 0 and p.stdout.count("PIN BASH_BIN_SHA256") == 1, p.stdout


@pytest.mark.parametrize("key, value", [("MUSL_BUILDER_IMAGE", "alpine:3.24"), ("BASH_BASELINE", "5.x"),
                                        ("BASH_PATCHLEVEL", "2x"), ("BASH_GPG_FPR", "7C0135FB"),
                                        ("BASH_SRC_SHA256", "xyz"), ("BASH_BIN_SHA256", "F" * 64)])
def test_resolve_tools_refuses_a_malformed_pin_before_any_build(eqc_env, pins_lib, key, value):
    unset_bash(pins_lib)
    _set_everywhere(pins_lib, key, value)
    p = resolve(eqc_env, pins_lib)
    assert p.returncode == 2 and "must be well-formed and agree before --resolve-tools" in p.stderr, (p.returncode, p.stderr)
    assert "pin %s is malformed in PINS" % key in p.stderr and eqc_env.calls() == []


@pytest.mark.parametrize("key", ["MUSL_BUILDER_IMAGE", "BASH_BASELINE", "BASH_PATCHLEVEL", "BASH_GPG_FPR"])
def test_resolve_tools_refuses_a_placeholder_in_the_pins_it_needs(eqc_env, pins_lib, key):
    unset_bash(pins_lib)
    set_pin(pins_lib, key, "UNSET", files=("PINS", "Dockerfile.minimal"))
    p = resolve(eqc_env, pins_lib)
    assert p.returncode == 2 and eqc_env.calls() == [], (p.returncode, p.stderr)


def test_resolve_tools_refuses_a_half_set_bash_pin(eqc_env, pins_lib):
    """PINS holds a value, the Dockerfile ARG is still UNSET (or the reverse): they must agree first."""
    unset_bash(pins_lib)
    set_pin(pins_lib, "BASH_SRC_SHA256", H_SRC, files=("PINS",))
    p = resolve(eqc_env, pins_lib)
    assert p.returncode == 2 and "pin BASH_SRC_SHA256 is a placeholder in Dockerfile.minimal" in p.stderr and eqc_env.calls() == []


def test_write_pin_without_resolve_tools_is_a_usage_error(eqc_env, pins_lib):
    p = eqc_env.run("build.sh", "--write-pin", lib=pins_lib)
    assert p.returncode == 2 and "--write-pin works only with --resolve-tools" in p.stderr and eqc_env.calls() == []


def test_resolve_tools_without_the_container_is_a_skip(eqc_env, pins_lib):
    unset_bash(pins_lib)
    p = resolve(eqc_env, pins_lib, EQ_FAKE_CONTAINER_DOWN=1)
    assert p.returncode == 10 and not [c for c in eqc_env.calls() if c[0] == "build"]


# ================================================================================ base-pins.sh (cosign faked)
FAKE_COSIGN = r'''#!%s
import json, os, sys
open(os.environ["FAKE_COSIGN_LOG"], "a").write("\x1f".join(sys.argv[1:]) + "\n")
rc = int(os.environ.get("FAKE_COSIGN_RC", "0"))
if rc:
    sys.stderr.write("Error: no matching signatures\n")
    sys.exit(rc)
out = os.environ.get("FAKE_COSIGN_OUT")
if out is None:
    out = json.dumps([{"critical": {"identity": {"docker-reference": sys.argv[2].split("@")[0]},
                                    "image": {"docker-manifest-digest": os.environ["FAKE_COSIGN_DIGEST"]},
                                    "type": "cosign container image signature"}, "optional": {}}])
sys.stdout.write(out)
'''
COSIGN_ARGV = ["verify", None, "--certificate-oidc-issuer", "https://accounts.google.com", "--certificate-identity",
               "keyless@distroless.iam.gserviceaccount.com"]


def pin_of(lib: Path, key: str) -> str:
    return next(ln.split("=", 1)[1] for ln in (lib / "PINS").read_text().splitlines() if ln.startswith(key + "="))


class BasePins:
    def __init__(self, tmp: Path, lib: Path = None):
        self.t = tmp
        self.lib = lib or copy_lib(tmp / "eq-container-bp")
        self.cosign = tmp / "cosign"
        self.cosign.write_text(FAKE_COSIGN % sys.executable)
        self.cosign.chmod(0o755)
        self.log = tmp / "cosign.log"
        self.digest = "sha256:" + pin_of(self.lib, "DISTROLESS_CC").split("@sha256:")[1]      # of the PINS as shipped

    @property
    def ref(self):
        return pin_of(self.lib, "DISTROLESS_CC")

    @property
    def arm(self):
        return pin_of(self.lib, "DISTROLESS_CC_ARM64")

    def run(self, *args, locale="C", cosign=None, **extra):
        env = bash_env(locale, EQ_COSIGN_BIN=str(cosign or self.cosign), FAKE_COSIGN_LOG=str(self.log),
                       FAKE_COSIGN_DIGEST=self.digest)
        env.update({k: str(v) for k, v in extra.items()})
        return subprocess.run([BASH, str(self.lib / "base-pins.sh"), *args], capture_output=True, text=True, timeout=120,
                              check=False, env=env)

    def cosign_calls(self):
        return [ln.split("\x1f") for ln in self.log.read_text().splitlines()] if self.log.exists() else []


@pytest.fixture
def bp(tmp_path):
    return BasePins(tmp_path)


def test_base_pins_good_run(bp):
    before = lib_digest(bp.lib)
    p = bp.run()
    assert p.returncode == 0, (p.stdout, p.stderr)
    assert p.stdout == "BASE distroless-cc %s arm64 %s layers 21 cosign=OK\n" % (bp.ref, bp.arm), p.stdout
    want = [bp.ref if a is None else a for a in COSIGN_ARGV]
    assert bp.cosign_calls() == [want]
    assert lib_digest(bp.lib) == before                                       # never edits a file


def test_base_pins_on_the_real_pins_and_base_files(tmp_path):
    """The shipped PINS and base/ files, straight from the repo (EQ_PINS_FILE default), with the cosign fake."""
    b = BasePins(tmp_path, EQC_LIB)
    p = b.run()
    assert p.returncode == 0 and p.stdout.startswith("BASE distroless-cc gcr.io/distroless/cc-debian13") and " layers 21 cosign=OK" in p.stdout, p


def test_base_pins_honours_eq_pins_file(bp, tmp_path):
    other = tmp_path / "OTHER_PINS"
    other.write_text((bp.lib / "PINS").read_text().replace("DISTROLESS_CC_ARM64=sha256:", "DISTROLESS_CC_ARM64=", 1))
    p = bp.run(EQ_PINS_FILE=other)
    assert p.returncode == 2 and "DISTROLESS_CC_ARM64 is not sha256:<64 hex>" in p.stderr and p.stdout == ""
    p = bp.run(EQ_PINS_FILE=tmp_path / "nowhere")
    assert p.returncode == 2 and "not found" in p.stderr and p.stdout == ""


PAYLOAD_FAULTS = {
    "another digest": lambda d: json.dumps([{"critical": {"image": {"docker-manifest-digest": "sha256:" + "9" * 64}}}]),
    "one of two names another digest": lambda d: json.dumps([{"critical": {"image": {"docker-manifest-digest": d}}},
                                                             {"critical": {"image": {"docker-manifest-digest": "sha256:" + "9" * 64}}}]),
    "empty list": lambda d: "[]", "not json": lambda d: "Verification for x --\n", "an object": lambda d: "{}",
    "no critical": lambda d: "[{}]", "no image": lambda d: json.dumps([{"critical": {}}]), "empty output": lambda d: "",
    "null item": lambda d: "[null]",
}


@pytest.mark.parametrize("fault", sorted(PAYLOAD_FAULTS))
def test_base_pins_a_payload_that_does_not_name_the_pinned_digest_fails(bp, fault):
    d = "sha256:" + bp.ref.split("@sha256:")[1]
    p = bp.run(FAKE_COSIGN_OUT=PAYLOAD_FAULTS[fault](d))
    assert p.returncode == 1 and p.stdout == "", (p.returncode, p.stdout, p.stderr)
    assert "do not all name the pinned digest" in p.stderr, p.stderr


def test_base_pins_two_good_payloads_pass(bp):
    d = "sha256:" + bp.ref.split("@sha256:")[1]
    one = {"critical": {"image": {"docker-manifest-digest": d}}}
    p = bp.run(FAKE_COSIGN_OUT=json.dumps([one, one]))
    assert p.returncode == 0 and "cosign=OK" in p.stdout


@pytest.mark.parametrize("rc", [1, 3])
def test_base_pins_cosign_failure(bp, rc):
    p = bp.run(FAKE_COSIGN_RC=rc)
    assert p.returncode == 1 and p.stdout == "" and "cosign verify" in p.stderr and "(rc %d)" % rc in p.stderr, p.stderr


def test_base_pins_without_cosign_fails(bp):
    p = bp.run(cosign="/nonexistent/cosign")
    assert p.returncode == 1 and p.stdout == "" and "cosign not found" in p.stderr, p.stderr
    assert bp.cosign_calls() == []


def _ref(**kw):
    base = {"name": "gcr.io/distroless/cc-debian13", "tag": ":nonroot", "digest": "@sha256:" + D}
    base.update(kw)
    return base["name"] + base["tag"] + base["digest"]


BAD_REFS = {
    "debug variant": _ref(tag=":debug-nonroot"), "latest": _ref(tag=":latest"), "tag only": "gcr.io/distroless/cc-debian13:nonroot",
    "no tag no digest": "gcr.io/distroless/cc-debian13", "debian12": _ref(name="gcr.io/distroless/cc-debian12"),
    "another registry": _ref(name="docker.io/distroless/cc-debian13"), "uppercase name": _ref(name="gcr.io/distroless/CC-debian13"),
    "uppercase digest": _ref(digest="@sha256:" + "B" * 64), "63 hex": _ref(digest="@sha256:" + "a" * 63),
    "a debug name": _ref(name="gcr.io/distroless/cc-debian13-debug"), "bad character": _ref(tag=":non;root"),
}


@pytest.mark.parametrize("why", sorted(BAD_REFS))
def test_base_pins_malformed_reference_is_exit_2(bp, why):
    set_pin(bp.lib, "DISTROLESS_CC", BAD_REFS[why])
    p = bp.run()
    assert p.returncode == 2 and p.stdout == "" and "base-pins.sh: PINS:" in p.stderr, (p.returncode, p.stderr)
    assert bp.cosign_calls() == []


@pytest.mark.parametrize("value", ["a" * 64, "sha256:" + "a" * 63, "sha256:" + "A" * 64, "md5:" + "a" * 32, "sha256:"])
def test_base_pins_malformed_arm64_is_exit_2(bp, value):
    set_pin(bp.lib, "DISTROLESS_CC_ARM64", value)
    p = bp.run()
    assert p.returncode == 2 and p.stdout == "" and "DISTROLESS_CC_ARM64" in p.stderr and bp.cosign_calls() == [], p.stderr


@needs_utf8
@pytest.mark.parametrize("key, value", [("DISTROLESS_CC", _ref(digest="@sha256:" + "B" * 64)), ("DISTROLESS_CC_ARM64", "sha256:" + "A" * 64),
                                        ("DISTROLESS_CC", _ref(name="gcr.io/distroless/CC-debian13")),
                                        ("DISTROLESS_CC", _ref(name="gcr.io/distroless/c\u00c7-debian13"))])
def test_base_pins_malformed_under_a_utf8_locale(bp, key, value):
    set_pin(bp.lib, key, value)
    p = bp.run(locale=UTF8)
    assert p.returncode == 2 and p.stdout == "" and bp.cosign_calls() == [], (p.returncode, p.stderr)


@pytest.mark.parametrize("key, value", [("DISTROLESS_CC", "UNSET"), ("DISTROLESS_CC", ""), ("DISTROLESS_CC", "TODO"),
                                        ("DISTROLESS_CC_ARM64", "UNSET"), ("DISTROLESS_CC_ARM64", "see-TODO")])
def test_base_pins_placeholder_is_exit_13(bp, key, value):
    set_pin(bp.lib, key, value)
    p = bp.run()
    assert p.returncode == 13 and p.stdout == "" and "is a placeholder in PINS" in p.stderr and bp.cosign_calls() == [], p.stderr


def test_base_pins_placeholder_wins_over_a_malformed_value(bp):
    set_pin(bp.lib, "DISTROLESS_CC", BAD_REFS["debug variant"])
    set_pin(bp.lib, "DISTROLESS_CC_ARM64", "UNSET")
    assert bp.run().returncode == 13


@pytest.mark.parametrize("how", ["twice", "missing"])
def test_base_pins_a_key_twice_or_missing_is_exit_2(bp, how):
    text = (bp.lib / "PINS").read_text()
    if how == "twice":
        text += "DISTROLESS_CC_ARM64=sha256:%s\n" % D
    else:
        text = re.sub(r"^DISTROLESS_CC_ARM64=.*\n", "", text, flags=re.M)
    (bp.lib / "PINS").write_text(text)
    p = bp.run()
    assert p.returncode == 2 and "want exactly one" in p.stderr and p.stdout == "", p.stderr


@pytest.mark.parametrize("how", ["index byte", "manifest byte", "arm64 pin", "index missing", "manifest missing"])
def test_base_pins_offline_inconsistency_fails_before_cosign(bp, how):
    if how == "index byte":
        _tamper_base(INDEX)(bp.lib)
    elif how == "manifest byte":
        _tamper_base(MANIFEST)(bp.lib)
    elif how == "arm64 pin":
        set_pin(bp.lib, "DISTROLESS_CC_ARM64", "sha256:" + "9" * 64)
    elif how == "index missing":
        (bp.lib / "base" / INDEX).unlink()
    else:
        (bp.lib / "base" / MANIFEST).unlink()
    p = bp.run()
    assert p.returncode == 1 and p.stdout == "" and "FAILED" in p.stderr, (p.returncode, p.stderr)
    assert bp.cosign_calls() == []


def test_base_pins_usage(bp):
    p = bp.run("--nonsense")
    assert p.returncode == 2 and "unknown argument" in p.stderr and bp.cosign_calls() == []
    p = bp.run("--help")
    assert p.returncode == 0 and "base-pins.sh" in p.stdout and "cosign verify" in p.stdout and bp.cosign_calls() == []


# ================================================================================ eqc_json.py base-verify, on crafted files
def ej(*args):
    return subprocess.run([sys.executable, "-I", str(EQC_LIB / "eqc_json.py"), *map(str, args)], capture_output=True, text=True,
                          timeout=60, check=False)


class Base:
    """A crafted distroless base: an arm64 image manifest of `layers` layers and an index listing it (and an amd64 one)."""

    def __init__(self, tmp: Path, layers: int = 3):
        self.layers = ["sha256:" + sha(b"layer%d" % i) for i in range(layers)]
        self.manifest = {"schemaVersion": 2, "mediaType": "application/vnd.oci.image.manifest.v1+json",
                         "config": {"mediaType": "application/vnd.oci.image.config.v1+json", "digest": "sha256:" + sha(b"cfg"), "size": 3},
                         "layers": [{"mediaType": "application/vnd.oci.image.layer.v1.tar+gzip", "digest": d, "size": 5}
                                    for d in self.layers]}
        self.tmp = tmp
        self.mbytes = None
        self.size_delta = 0
        self.platforms = [("linux", "amd64"), ("linux", "arm64")]
        self.extra_entries = []

    def write(self):
        self.mbytes = json.dumps(self.manifest).encode()
        self.mdig = "sha256:" + sha(self.mbytes)
        entries = [{"mediaType": "application/vnd.oci.image.manifest.v1+json",
                    "digest": self.mdig if a == "arm64" else "sha256:" + sha(a.encode()), "size": len(self.mbytes) + self.size_delta,
                    "platform": {"architecture": a, "os": o}} for o, a in self.platforms] + self.extra_entries
        self.ibytes = json.dumps({"schemaVersion": 2, "mediaType": "application/vnd.oci.image.index.v1+json", "manifests": entries}).encode()
        self.idig = "sha256:" + sha(self.ibytes)
        self.ipath, self.mpath = self.tmp / "index.json", self.tmp / "manifest.json"
        self.ipath.write_bytes(self.ibytes)
        self.mpath.write_bytes(self.mbytes)
        return self

    def verify(self, idig=None, mdig=None):
        return ej("base-verify", self.ipath, self.mpath, idig or self.idig, mdig or self.mdig)


def test_base_verify_prints_the_layers_bottom_first(tmp_path):
    b = Base(tmp_path).write()
    p = b.verify()
    assert p.returncode == 0 and p.stdout.split() == b.layers, (p.stdout, p.stderr)


def test_base_verify_on_the_real_base_files_prints_21_layers():
    pins = {k: pin_of(EQC_LIB, k) for k in ("DISTROLESS_CC", "DISTROLESS_CC_ARM64")}
    p = ej("base-verify", EQC_LIB / "base" / INDEX, EQC_LIB / "base" / MANIFEST, "sha256:" + pins["DISTROLESS_CC"].split("@sha256:")[1],
           pins["DISTROLESS_CC_ARM64"])
    layers = p.stdout.split()
    assert p.returncode == 0 and len(layers) == 21 and all(re.fullmatch(r"sha256:[0-9a-f]{64}", d) for d in layers), p
    man = json.loads((EQC_LIB / "base" / MANIFEST).read_text())
    assert layers == [layer["digest"] for layer in man["layers"]]


def _only_amd64(b):
    b.platforms = [("linux", "amd64")]


def _two_arm64(b):
    b.platforms = [("linux", "arm64"), ("linux", "arm64")]


def _extra_arm64_other_digest(b):
    b.extra_entries = [{"mediaType": "x", "digest": "sha256:" + "9" * 64, "size": 1, "platform": {"architecture": "arm64", "os": "linux"}}]


def _size_off(b):
    b.size_delta = 1


def _windows(b):
    b.platforms = [("linux", "amd64"), ("windows", "arm64")]


def _no_layers(b):
    b.manifest["layers"] = []


def _bad_layer_digest(b):
    b.manifest["layers"][1]["digest"] = "sha256:xyz"


def _upper_layer_digest(b):
    b.manifest["layers"][1]["digest"] = "sha256:" + "A" * 64


def _no_config(b):
    del b.manifest["config"]


def _layer_not_an_object(b):
    b.manifest["layers"][0] = "sha256:" + "a" * 64


BASE_FAULTS = {
    "arm64 missing": _only_amd64, "two arm64 entries": _two_arm64, "a second arm64 entry of another digest": _extra_arm64_other_digest,
    "size mismatch": _size_off, "linux missing (windows arm64)": _windows, "manifest without layers": _no_layers,
    "a layer digest that is not hex": _bad_layer_digest, "an uppercase layer digest": _upper_layer_digest,
    "manifest without config": _no_config, "a layer that is no object": _layer_not_an_object,
}


@pytest.mark.parametrize("fault", sorted(BASE_FAULTS))
def test_base_verify_refuses_a_crafted_fault(tmp_path, fault):
    b = Base(tmp_path)
    BASE_FAULTS[fault](b)
    b.write()
    p = b.verify()
    assert p.returncode == 1 and p.stdout == "", (fault, p.stdout, p.stderr)


@pytest.mark.parametrize("which", ["index digest", "manifest digest", "index digest not sha256", "manifest digest uppercase",
                                   "index file missing", "index not json", "index an array", "manifests not a list", "manifest an array"])
def test_base_verify_refuses_a_digest_or_file_fault(tmp_path, which):
    b = Base(tmp_path).write()
    if which == "index digest":
        p = b.verify(idig="sha256:" + "9" * 64)
    elif which == "manifest digest":
        p = b.verify(mdig="sha256:" + "9" * 64)
    elif which == "index digest not sha256":
        p = b.verify(idig="md5:" + "9" * 32)
    elif which == "manifest digest uppercase":
        p = b.verify(mdig=b.mdig.upper())
    elif which == "index file missing":
        b.ipath.unlink()
        p = b.verify()
    else:
        text = {"index not json": b"{", "index an array": b"[]", "manifests not a list": b'{"manifests": 1}'}.get(which)
        if which == "manifest an array":
            b.mpath.write_bytes(b"[]")
            p = b.verify(mdig="sha256:" + sha(b"[]"))
        else:
            b.ipath.write_bytes(text)
            p = b.verify(idig="sha256:" + sha(text))
    assert p.returncode == 1 and p.stdout == "", (which, p.stdout, p.stderr)


def test_base_verify_wrong_argument_count_fails(tmp_path):
    b = Base(tmp_path).write()
    assert ej("base-verify", b.ipath, b.mpath, b.idig).returncode == 1
    assert ej("no-such-mode").returncode == 1 and ej().returncode == 1


# ================================================================================ the perl shim, against the real perl
CHECK_LEAN = ROOT / "equilibrium" / "items" / "PF" / "check_lean.sh"
SHIM = "minimal/perl-shim"
PERL = next((p for p in ("/usr/bin/perl", shutil.which("perl")) if p and os.access(p, os.X_OK)), None)
needs_perl = pytest.mark.skipif(PERL is None, reason="no perl on this machine to compare the shim with")


def wrapper_of(text: str, pattern: str) -> str:
    m = re.search(pattern, text, re.S | re.M)
    assert m, pattern
    return m.group(1)


def wrappers(lib: Path) -> dict:
    """The wrapper text in each of the four places that carry it."""
    return {
        "check_lean.sh": wrapper_of(CHECK_LEAN.read_text(), r"perl -e '(.*?)' \"\$t\" \"\$@\""),
        "minimal/perl-shim": wrapper_of((lib / SHIM).read_text(), r"^W='(.*?)'$"),
        "minimal/mkrootfs.sh": wrapper_of((lib / "minimal/mkrootfs.sh").read_text(), r"^\s*wrapper='(.*?)'$"),
        "minimal/check.sh": wrapper_of((lib / "minimal/check.sh").read_text(), r"^\s*W='(.*?)'$"),
    }


def test_the_wrapper_text_is_identical_in_all_four_places():
    w = wrappers(EQC_LIB)
    ref = w["check_lean.sh"]
    assert ref.startswith("my $t = shift;") and ref.endswith("exit($? >> 8)") and "'" not in ref
    for name, text in w.items():
        assert text == ref, name


def test_check_lean_is_the_frozen_file():
    """The wrapper reference is the hash-frozen checker: its sha256 is the one items/PF/pool.sha256 lists for it."""
    pool = (ROOT / "equilibrium" / "items" / "PF" / "pool.sha256").read_text().splitlines()
    listed = {ln.split()[1]: ln.split()[0] for ln in pool if ln.strip()}
    assert hashlib.sha256(CHECK_LEAN.read_bytes()).hexdigest() == listed["check_lean.sh"]


@pytest.fixture
def shimrun(tmp_path):
    w = wrappers(EQC_LIB)["check_lean.sh"]
    marker = tmp_path / "ran"

    def run(argv0, *args, input=None, lib: Path = EQC_LIB):
        cmd = [argv0] if argv0 == PERL else [BASH, str(lib / SHIM)]
        return subprocess.run(cmd + list(args), input=input, capture_output=True, text=True, timeout=60, check=False,
                              env={"PATH": "/usr/bin:/bin", "TMPDIR": str(_TMP), "HOME": str(_TMP)})
    run.W, run.marker = w, marker
    return run


def both(shimrun, t, *cmd, input=None):
    r = [shimrun(who, "-e", shimrun.W, t, *cmd, input=input) for who in (PERL, "shim")]
    return [(p.returncode, p.stdout, p.stderr) for p in r]


DIFF_CASES = {
    "exit 0": ("5", "/bin/sh", "-c", "exit 0"), "exit 3": ("5", "/bin/sh", "-c", "exit 3"),
    "exit 1 (lean and leanchecker's failing code)": ("5", "/bin/sh", "-c", "exit 1"),
    "timeout": ("1", "/bin/sleep", "30"),
    "self-kill TERM": ("5", "/bin/sh", "-c", "kill -TERM $$"), "self-kill KILL": ("5", "/bin/sh", "-c", "kill -KILL $$"),
    "self-kill HUP": ("5", "/bin/sh", "-c", "kill -HUP $$"),
    "missing command": ("5", "nosuch-command-eqc"), "T=0 true": ("0", "/usr/bin/true"), "T=0 exit 5": ("0", "/bin/sh", "-c", "exit 5"),
    "T with leading zeros": ("007", "/bin/sh", "-c", "exit 4"),
    "args with spaces and an empty one": ("5", "/bin/sh", "-c", 'printf "[%s]" "$@"', "sh", "a b", "c  d", "", "e'f", "$HOME"),
    "stderr passes": ("5", "/bin/sh", "-c", "echo to-stderr >&2; echo to-stdout; exit 2"),
    "path search": ("5", "printf", "%s", "x"),
}


@needs_perl
@pytest.mark.parametrize("case", sorted(DIFF_CASES), ids=sorted(DIFF_CASES))
def test_shim_matches_perl(shimrun, case):
    perl, shim = both(shimrun, *DIFF_CASES[case])
    assert shim == perl, (case, perl, shim)


@needs_perl
def test_shim_timeout_and_signal_messages_are_perls():
    """Spelled out, so a differential that happened to agree on a wrong value would still fail."""
    w = wrappers(EQC_LIB)["check_lean.sh"]
    run = lambda *a: subprocess.run([BASH, str(EQC_LIB / SHIM), "-e", w, *a], capture_output=True, text=True, timeout=60,   # noqa: E731
                                    check=False, env={"PATH": "/usr/bin:/bin", "TMPDIR": str(_TMP)})
    p = run("1", "/bin/sleep", "30")
    assert (p.returncode, p.stdout, p.stderr) == (124, "", "eqlean: timeout\n")
    p = run("5", "/bin/sh", "-c", "kill -TERM $$")
    assert (p.returncode, p.stdout, p.stderr) == (143, "", "eqlean: killed by signal 15\n")
    p = run("5", "nosuch-command-eqc")
    assert (p.returncode, p.stdout, p.stderr) == (127, "", "")
    p = run("5", "/bin/sh", "-c", "exit 3")
    assert (p.returncode, p.stdout, p.stderr) == (3, "", "")


@needs_perl
def test_shim_hands_stdin_through(shimrun):
    perl, shim = both(shimrun, "5", "/bin/cat", input="line1\nline2 with spaces\n")
    assert perl == shim == (0, "line1\nline2 with spaces\n", "")


def test_shim_a_child_exiting_129_or_more_is_reported_as_a_signal(shimrun):
    """The documented difference (bash cannot tell them apart): the exit code is the same, perl is silent, the shim says so."""
    p = shimrun("shim", "-e", shimrun.W, "5", "/bin/sh", "-c", "exit 130")
    assert p.returncode == 130 and p.stderr == "eqlean: killed by signal 2\n" and p.stdout == ""
    p = shimrun("shim", "-e", shimrun.W, "5", "/bin/sh", "-c", "exit 128")
    assert p.returncode == 128 and p.stderr == ""


def test_shim_command_runs_in_the_foreground_with_this_shells_stdout(shimrun, tmp_path):
    """The child's stdout is the caller's (a pipe here): output order and EOF behave as with perl's fork+exec."""
    p = shimrun("shim", "-e", shimrun.W, "5", "/bin/sh", "-c", "echo one; echo two >&2; echo three")
    assert p.stdout == "one\nthree\n" and p.stderr == "two\n" and p.returncode == 0


REFUSALS = {      # W = the wrapper text, M = the marker the command would touch
    "another script": lambda W, M: ["-e", "print 1", "5", "touch", M],
    "the wrapper with one byte changed": lambda W, M: ["-e", W.replace("124", "125"), "5", "touch", M],
    "a non-numeric T": lambda W, M: ["-e", W, "1x", "touch", M], "an empty T": lambda W, M: ["-e", W, "", "touch", M],
    "a negative T": lambda W, M: ["-e", W, "-1", "touch", M], "a T of 10 digits": lambda W, M: ["-e", W, "1234567890", "touch", M],
    "T with a space": lambda W, M: ["-e", W, "5 ", "touch", M],
    "no command": lambda W, M: ["-e", W, "5"], "no T and no command": lambda W, M: ["-e", W],
    "no -e": lambda W, M: [W, "5", "touch", M], "another flag": lambda W, M: ["-E", W, "5", "touch", M], "no arguments": lambda W, M: [],
    "the wrapper with a trailing newline": lambda W, M: ["-e", W + "\n", "5", "touch", M],
    "the wrapper with a leading space": lambda W, M: ["-e", " " + W, "5", "touch", M],
    "the wrapper with its first line only": lambda W, M: ["-e", W.splitlines()[0], "5", "touch", M],
}


@pytest.mark.parametrize("why", sorted(REFUSALS))
def test_shim_refuses_everything_but_the_wrapper(shimrun, why):
    p = shimrun("shim", *REFUSALS[why](shimrun.W, str(shimrun.marker)))
    assert p.returncode == 2 and "perl: not available in this image" in p.stderr and p.stdout == "", (why, p.returncode, p.stderr)
    assert not shimrun.marker.exists(), "the command ran"


def test_shim_accepts_the_largest_nine_digit_T(shimrun):
    p = shimrun("shim", "-e", shimrun.W, "999999999", "/bin/sh", "-c", "exit 6")
    assert p.returncode == 6 and p.stderr == ""


# ================================================================================ untar.py (zstd read replaced by a gzip tarball)
def load_untar():
    spec = importlib.util.spec_from_file_location("eqc_untar", EQC_LIB / "minimal" / "untar.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def make_tgz(path: Path, members) -> Path:
    """members: (name, kind, payload): kind in file|dir|hard|sym."""
    with tarfile.TarFile.open(path, "w:gz") as t:           # (tarfile.open is what the untar tests patch)
        for name, kind, payload in members:
            ti = tarfile.TarInfo(name)
            if kind == "dir":
                ti.type, ti.mode = tarfile.DIRTYPE, 0o755
                t.addfile(ti)
            elif kind == "file":
                ti.size, ti.mode = len(payload), 0o644
                t.addfile(ti, io.BytesIO(payload))
            elif kind == "hard":
                ti.type, ti.linkname = tarfile.LNKTYPE, payload
                t.addfile(ti)
            else:
                ti.type, ti.linkname = tarfile.SYMTYPE, payload
                t.addfile(ti)
    return path


@pytest.fixture
def untar(monkeypatch):
    mod = load_untar()
    modes = []
    real = tarfile.open

    def fake_open(name, mode="r", **kw):
        modes.append(mode)
        assert mode == "r:zst", "untar.py must read the archive as zstd"
        return real(name, "r:gz", **kw)
    monkeypatch.setattr(tarfile, "open", fake_open)
    mod.modes = modes
    return mod


@pytest.mark.parametrize("name, want", [("top/a/b", "a/b"), ("top", ""), ("top/", ""), ("./top/a", "a"), ("./top/.hidden", ".hidden"),
                                        ("top/.wh.x", ".wh.x"), ("./././top/x", "x"), ("a", ""), ("", "")])
def test_strip1(name, want):
    assert load_untar().strip1(name) == want


def test_untar_strips_the_top_directory(untar, tmp_path):
    a = make_tgz(tmp_path / "x.tgz", [("lean-4.34.1-linux_aarch64", "dir", None), ("lean-4.34.1-linux_aarch64/bin", "dir", None),
                                      ("lean-4.34.1-linux_aarch64/bin/lean", "file", b"LEAN"),
                                      ("lean-4.34.1-linux_aarch64/.hidden", "file", b"h"),
                                      ("lean-4.34.1-linux_aarch64/lib/lean/Init.olean", "file", b"o")])
    dest = tmp_path / "out"
    untar.main(str(a), str(dest))
    assert untar.modes == ["r:zst"]
    assert (dest / "bin" / "lean").read_bytes() == b"LEAN" and (dest / ".hidden").read_bytes() == b"h"
    assert (dest / "lib" / "lean" / "Init.olean").read_bytes() == b"o"
    assert sorted(p.name for p in dest.iterdir()) == [".hidden", "bin", "lib"]


def test_untar_retargets_a_hard_link(untar, tmp_path):
    a = make_tgz(tmp_path / "x.tgz", [("top/bin", "dir", None), ("top/bin/busybox", "file", b"BB"), ("top/bin/[", "hard", "top/bin/busybox")])
    dest = tmp_path / "out"
    untar.main(str(a), str(dest))
    assert (dest / "bin" / "[").read_bytes() == b"BB"
    assert os.path.samefile(dest / "bin" / "[", dest / "bin" / "busybox")


def test_untar_refuses_a_path_that_climbs_out(untar, tmp_path):
    a = make_tgz(tmp_path / "x.tgz", [("top/ok", "file", b"1"), ("top/../../evil", "file", b"E")])
    dest = tmp_path / "sub" / "out"
    with pytest.raises(tarfile.FilterError):
        untar.main(str(a), str(dest))
    assert not (tmp_path / "evil").exists() and not (tmp_path / "sub" / "evil").exists()


def test_untar_keeps_an_absolute_member_name_inside_dest(untar, tmp_path):
    """`top//abs/x` strips to `/abs/x`: the data filter drops the leading slash, so it lands below DEST (never at /abs)."""
    a = make_tgz(tmp_path / "x.tgz", [("top/ok", "file", b"1"), ("top//eqc-abs-test/x", "file", b"A")])
    dest = tmp_path / "out"
    untar.main(str(a), str(dest))
    assert (dest / "eqc-abs-test" / "x").read_bytes() == b"A" and not Path("/eqc-abs-test").exists()


@pytest.mark.parametrize("link", ["/etc/passwd", "../../outside"])
def test_untar_refuses_a_symlink_that_leaves_dest(untar, tmp_path, link):
    a = make_tgz(tmp_path / "x.tgz", [("top/ok", "file", b"1"), ("top/l", "sym", link)])
    with pytest.raises(tarfile.FilterError):
        untar.main(str(a), str(tmp_path / "out"))


def test_untar_clears_setuid_bits(untar, tmp_path):
    with tarfile.TarFile.open(tmp_path / "x.tgz", "w:gz") as t:
        ti = tarfile.TarInfo("top/su")
        ti.size, ti.mode = 1, 0o4755
        t.addfile(ti, io.BytesIO(b"x"))
    untar.main(str(tmp_path / "x.tgz"), str(tmp_path / "out"))
    assert (tmp_path / "out" / "su").stat().st_mode & 0o7000 == 0


def test_untar_an_archive_with_only_the_top_directory_fails(untar, tmp_path):
    a = make_tgz(tmp_path / "x.tgz", [("top", "dir", None)])
    with pytest.raises(SystemExit) as e:
        untar.main(str(a), str(tmp_path / "out"))
    assert "holds no member below its top directory" in str(e.value)


def test_untar_cli_usage_and_errors(tmp_path):
    p = subprocess.run([sys.executable, str(EQC_LIB / "minimal" / "untar.py")], capture_output=True, text=True, check=False, timeout=60)
    assert p.returncode == 1 and "usage" in p.stderr
    p = subprocess.run([sys.executable, str(EQC_LIB / "minimal" / "untar.py"), str(tmp_path / "nope.tar.zst"), str(tmp_path / "o")],
                       capture_output=True, text=True, check=False, timeout=60)
    assert p.returncode == 1 and p.stderr.startswith("untar.py: ")


@pytest.mark.skipif(sys.version_info < (3, 14), reason="tarfile reads zstd only from Python 3.14 (the fetch stage runs the pinned 3.14)")
def test_untar_real_zstd(tmp_path):
    a = tmp_path / "x.tar.zst"
    with tarfile.open(a, "w:zst") as t:
        ti = tarfile.TarInfo("top/f")
        ti.size = 2
        t.addfile(ti, io.BytesIO(b"ok"))
    p = subprocess.run([sys.executable, str(EQC_LIB / "minimal" / "untar.py"), str(a), str(tmp_path / "out")], capture_output=True,
                       text=True, check=False, timeout=60)
    assert p.returncode == 0 and (tmp_path / "out" / "f").read_bytes() == b"ok", p.stderr


# ================================================================================ tc/build-bash.sh (POSIX sh) with fakes
PY = "#!%s\n" % sys.executable
FAKE_CURL_BB = PY + r'''import os, sys
a = sys.argv[1:]
open(os.environ["FAKE_LOG"] + "/curl.log", "a").write("\x1f".join(a) + "\n")
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
name = url.rsplit("/", 1)[1]
open(out, "w").write("SIG %s\n" % name if name.endswith(".sig") else "fake bash tarball\n" if name.endswith(".tar.gz")
                     else "fake patch %s\n" % name)
'''
FAKE_GPG = PY + r'''import os, sys
a = sys.argv[1:]
open(os.environ["FAKE_LOG"] + "/gpg.log", "a").write("\x1f".join(a) + "\n")
if "--recv-keys" in a:
    sys.exit(int(os.environ.get("FAKE_GPG_RECV_RC", "0")))
if "--list-keys" in a:
    print(os.environ["FAKE_GPG_KEYS"])
    sys.exit(0)
if "--verify" in a:
    base = os.path.basename(a[-1])
    bad = os.environ.get("FAKE_GPG_BAD_FILE") == base
    print(os.environ["FAKE_GPG_STATUS_BAD" if bad else "FAKE_GPG_STATUS"])
    sys.exit(int(os.environ.get("FAKE_GPG_RC_BAD", "0")) if bad else 0)
sys.exit(2)
'''
FAKE_SHA256SUM = PY + r'''import hashlib, sys
a = sys.argv[1:]
if not a:
    print(hashlib.sha256(sys.stdin.buffer.read()).hexdigest() + "  -")
for f in a:
    print(hashlib.sha256(open(f, "rb").read()).hexdigest() + "  " + f)
'''
# BSD mktemp -d without a template ignores TMPDIR (it uses the per-user cache directory): the script under test must stay in tmp_path
FAKE_MKTEMP = '''#!/bin/sh
exec /usr/bin/mktemp -d "$TMPDIR/bb.XXXXXX"
'''
FAKE_TAR = '''#!/bin/sh
echo tar >> "$FAKE_LOG/marks"
d="bash-$BASH_BASELINE"; mkdir -p "$d"
printf '#!/bin/sh\\necho configure >> "$FAKE_LOG/marks"\\nexit 0\\n' > "$d/configure"; chmod +x "$d/configure"
'''
FAKE_MAKE = '''#!/bin/sh
echo make >> "$FAKE_LOG/marks"
cp "$FAKE_LOG/fake-bash" bash; chmod +x bash
'''
FAKE_BASH_BIN = '''#!/bin/sh
case "$*" in
  *--version*) echo "GNU bash, version ${BASH_BASELINE}.${BASH_PATCHLEVEL}(1)-release (aarch64-unknown-linux-musl)";;
  *VERSINFO*) echo "${FAKE_BASH_VERSION:-${BASH_BASELINE}.${BASH_PATCHLEVEL}}";;
  *dev/tcp*) case "${FAKE_BASH_TCP:-refused}" in
               refused) echo "bash: connect: Connection refused" >&2; exit 1;;
               missing) echo "bash: /dev/tcp/127.0.0.1/1: No such file or directory" >&2; exit 1;;
               connected) exit 0;;
             esac;;
esac
'''
FAKE_READELF = '''#!/bin/sh
[ -n "$FAKE_READELF_DYNAMIC" ] || exit 0
case "$1" in
  -lW) echo "      [Requesting program interpreter: /lib/ld-musl-aarch64.so.1]";;
  -dW) echo " 0x0000000000000001 (NEEDED)             Shared library: [libc.musl-aarch64.so.1]";;
esac
'''
GPG_KEYS = "tru::1:1:1:0:3:1:5\npub:u:4096:1:BB5869F064EA74AB:1:::u:::scESC:::::::\nfpr:::::::::%s:\nuid:u::::1::X::Chet Ramey::::::::::0:\nsub:u:4096:1:AAAA:1::::::e:::::::\nfpr:::::::::%s:"
SUBFPR = "0123456789ABCDEF0123456789ABCDEF01234567"
OTHER = "A" * 40
STATUS_GOOD = "[GNUPG:] GOODSIG BB5869F064EA74AB Chet Ramey\n[GNUPG:] VALIDSIG %s 2025-01-01 1700000000 0 4 0 1 10 00 %s" % (SUBFPR, FPR)


class BashBuild:
    """tc/build-bash.sh run under /bin/sh with fakes first on PATH; marks.log records which of tar/patch/configure/make ran."""

    def __init__(self, tmp: Path, lib: Path = EQC_LIB, patchlevel: str = "2"):
        self.t, self.lib = tmp, lib
        self.fakes, self.log = tmp / "fakes", tmp / "log"
        self.fakes.mkdir()
        self.log.mkdir()
        self.dest = tmp / "dest"
        self.tmpdir = tmp / "tmp"
        self.tmpdir.mkdir()
        for name, text in (("mktemp", FAKE_MKTEMP), ("curl", FAKE_CURL_BB), ("gpg", FAKE_GPG), ("sha256sum", FAKE_SHA256SUM), ("tar", FAKE_TAR), ("make", FAKE_MAKE),
                           ("readelf", FAKE_READELF)):
            self.stub(name, text)
        for name, body in (("patch", 'echo patch >> "$FAKE_LOG/marks"\n'), ("strip", ""), ("nproc", "echo 2\n")):
            self.stub(name, "#!/bin/sh\n" + body)
        (self.log / "fake-bash").write_text(FAKE_BASH_BIN)
        self.patchlevel = patchlevel
        self.src = sha(b"fake bash tarball\n")
        names = ["bash53-%03d" % i for i in range(1, int(patchlevel) + 1)] if patchlevel.isdigit() else []
        lines = "".join("%s  %s\n" % (sha(("fake patch %s\n" % n).encode()), n) for n in names)
        self.pat = sha(lines.encode())
        self.bin = sha(FAKE_BASH_BIN.encode())
        self.env = {"BASH_BASELINE": "5.3", "BASH_PATCHLEVEL": patchlevel, "BASH_GPG_FPR": FPR, "BASH_SRC_SHA256": self.src,
                    "BASH_PATCHES_SHA256": self.pat, "BASH_BIN_SHA256": self.bin, "FAKE_GPG_KEYS": GPG_KEYS % (FPR, SUBFPR),
                    "FAKE_GPG_STATUS": STATUS_GOOD, "FAKE_GPG_STATUS_BAD": STATUS_GOOD}

    def stub(self, name, text):
        p = self.fakes / name
        p.write_text(text)
        p.chmod(0o755)

    def run(self, mode="build", *extra_args, drop=(), **env):
        e = {"PATH": "%s:/usr/bin:/bin" % self.fakes, "TMPDIR": str(self.tmpdir), "HOME": str(self.t), "FAKE_LOG": str(self.log)}
        e.update({k: v for k, v in self.env.items() if k not in drop})
        e.update({k: str(v) for k, v in env.items()})
        args = [mode, str(self.dest)] if mode is not None else []
        return subprocess.run(["/bin/sh", str(self.lib / "tc" / "build-bash.sh"), *args, *extra_args], capture_output=True, text=True,
                              timeout=120, check=False, env=e)

    def marks(self) -> list:
        f = self.log / "marks"
        return f.read_text().split() if f.exists() else []

    def curls(self) -> list:
        f = self.log / "curl.log"
        return [ln.split("\x1f") for ln in f.read_text().splitlines()] if f.exists() else []


@pytest.fixture
def bb(tmp_path):
    return BashBuild(tmp_path)


def test_build_bash_build_mode_happy_path(bb):
    p = bb.run("build")
    assert p.returncode == 0, (p.stdout, p.stderr)
    assert "SIGNATURES OK: bash-5.3.tar.gz and 2 patches, primary key %s" % FPR in p.stdout
    assert bb.marks() == ["tar", "patch", "patch", "configure", "make"], bb.marks()
    assert (bb.dest / "bin" / "bash").exists() and "sha256 %s" % bb.bin in p.stdout
    # every download is https-only, in the order: tarball, its signature, then each patch and its signature
    base = "https://ftp.gnu.org/gnu/bash"
    want = ["%s/bash-5.3.tar.gz" % base, "%s/bash-5.3.tar.gz.sig" % base]
    for n in ("bash53-001", "bash53-002"):
        want += ["%s/bash-5.3-patches/%s" % (base, n), "%s/bash-5.3-patches/%s.sig" % (base, n)]
    assert [c[-1] for c in bb.curls()] == want
    for c in bb.curls():
        assert c[c.index("--proto") + 1] == "=https" and c[c.index("--proto-redir") + 1] == "=https" and "--tlsv1.2" in c
    gpg = [ln.split("\x1f") for ln in (bb.log / "gpg.log").read_text().splitlines()]
    assert gpg[0][-2:] == ["--recv-keys", FPR] and gpg[0][:3] == ["--batch", "--keyserver", "hkps://keyserver.ubuntu.com"], gpg[0]


@pytest.mark.parametrize("key", BASH_KEYS)
@pytest.mark.parametrize("value", ["UNSET", "", "TODO"])
def test_build_bash_placeholder_in_build_mode_fails_before_any_download(bb, key, value):
    p = bb.run("build", **{key: value})
    assert p.returncode == 1 and "%s is a placeholder in PINS" % key in p.stderr and "--resolve-tools" in p.stderr, (p.returncode, p.stderr)
    assert bb.curls() == [] and bb.marks() == [] and not (bb.log / "gpg.log").exists()


@pytest.mark.parametrize("key", BASH_KEYS)
def test_build_bash_an_unset_variable_is_a_placeholder_in_build_mode(bb, key):
    p = bb.run("build", drop=(key,))
    assert p.returncode == 1 and "%s is a placeholder" % key in p.stderr and bb.curls() == []


@pytest.mark.parametrize("key, value", [("BASH_SRC_SHA256", "1" * 63), ("BASH_PATCHES_SHA256", "F" * 64), ("BASH_BIN_SHA256", "xyz"),
                                        ("BASH_SRC_SHA256", "g" * 64)])
@pytest.mark.parametrize("mode", ["build", "resolve"])
def test_build_bash_a_malformed_hash_is_refused_in_both_modes(bb, mode, key, value):
    p = bb.run(mode, **{key: value})
    assert p.returncode == 1 and "%s is neither a placeholder nor 64 lowercase hex" % key in p.stderr, (p.returncode, p.stderr)
    assert bb.curls() == [] and bb.marks() == []


@pytest.mark.parametrize("key, value, want", [
    ("BASH_GPG_FPR", "7C0135FB088AAF6C66C650B9BB5869F064EA74A", "BASH_GPG_FPR is not 40 uppercase hex"),
    ("BASH_GPG_FPR", FPR.lower(), "BASH_GPG_FPR is not 40 uppercase hex"),
    ("BASH_GPG_FPR", FPR[:-1] + "G", "BASH_GPG_FPR is not 40 uppercase hex"),
    ("BASH_GPG_FPR", FPR + "0", "BASH_GPG_FPR is not 40 uppercase hex"),
    ("BASH_PATCHLEVEL", "2x", "is not a number"), ("BASH_PATCHLEVEL", "-1", "is not a number"),
    ("BASH_PATCHLEVEL", "1000", "is too long"),
    ("BASH_BASELINE", "5", "is not MAJOR.MINOR"), ("BASH_BASELINE", "5.3.1", "is not MAJOR.MINOR"), ("BASH_BASELINE", "5.x", "is not MAJOR.MINOR"),
    ("BASH_BASELINE", "a.3", "is not MAJOR.MINOR"), ("BASH_BASELINE", "5.3-rc", "is not MAJOR.MINOR"),
])
def test_build_bash_malformed_fingerprint_patchlevel_or_baseline_is_refused(bb, key, value, want):
    for mode in ("build", "resolve"):
        p = bb.run(mode, **{key: value})
        assert p.returncode == 1 and want in p.stderr, (mode, p.returncode, p.stderr)
    assert bb.curls() == [] and bb.marks() == [] and not (bb.log / "gpg.log").exists()


def test_build_bash_usage_errors_run_nothing(bb):
    for args in ([None], ["nonsense"]):
        p = bb.run(args[0])
        assert p.returncode != 0 and bb.curls() == [] and bb.marks() == [], args
    p = bb.run("nonsense")
    assert "mode must be build or resolve" in p.stderr
    for var in ("BASH_BASELINE", "BASH_PATCHLEVEL", "BASH_GPG_FPR"):
        p = bb.run("build", drop=(var,))
        assert p.returncode != 0 and bb.curls() == [], var


@pytest.mark.parametrize("keys", [
    "tru::1:1:1:0:3:1:5\npub:u:4096:1:BB5869F064EA74AB:1:::u:::scESC:::::::\nfpr:::::::::%s:\npub:u:4096:1:CCCC:1:::u:::scESC:::::::\nfpr:::::::::%s:" % (FPR, OTHER),
    "pub:u:4096:1:CCCC:1:::u:::scESC:::::::\nfpr:::::::::%s:" % OTHER,
    # the pinned fingerprint only as a SUBKEY of someone else's primary key
    "pub:u:4096:1:CCCC:1:::u:::scESC:::::::\nfpr:::::::::%s:\nsub:u:4096:1:AAAA:1::::::e:::::::\nfpr:::::::::%s:" % (OTHER, FPR),
    "",
], ids=["an extra primary key", "another primary key", "pinned only as a subkey", "an empty keyring"])
def test_build_bash_a_keyring_without_exactly_the_pinned_primary_stops_before_tar(bb, keys):
    for mode in ("build", "resolve"):
        p = bb.run(mode, FAKE_GPG_KEYS=keys)
        assert p.returncode == 1 and "the keyring holds the primary key(s)" in p.stderr, (mode, p.returncode, p.stderr)
        assert bb.marks() == [] and bb.curls() == []                     # no download either: the key comes first


def test_build_bash_a_failing_key_fetch_stops_everything(bb):
    p = bb.run("build", FAKE_GPG_RECV_RC=2)
    assert p.returncode != 0 and bb.curls() == [] and bb.marks() == []


@pytest.mark.parametrize("status, rc, want", [
    ("[GNUPG:] BADSIG BB5869F064EA74AB Chet Ramey", 0, "bad signature status for bash.tar.gz"),
    ("[GNUPG:] ERRSIG BB5869F064EA74AB 1 10 00 1700000000 9", 0, "bad signature status for bash.tar.gz"),
    ("[GNUPG:] NO_PUBKEY BB5869F064EA74AB", 0, "bad signature status for bash.tar.gz"),
    ("[GNUPG:] REVKEYSIG BB5869F064EA74AB Chet Ramey", 0, "bad signature status for bash.tar.gz"),
    ("[GNUPG:] EXPSIG BB5869F064EA74AB Chet Ramey", 0, "bad signature status for bash.tar.gz"),
    ("[GNUPG:] BADSIG BB5869F064EA74AB Chet Ramey", 1, "the signature of bash.tar.gz does not verify"),
    ("[GNUPG:] NO_PUBKEY BB5869F064EA74AB", 2, "the signature of bash.tar.gz does not verify"),
], ids=["BADSIG", "ERRSIG", "NO_PUBKEY", "REVKEYSIG", "EXPSIG", "BADSIG rc 1", "NO_PUBKEY rc 2"])
def test_build_bash_a_bad_signature_status_stops_before_tar(bb, status, rc, want):
    """Every other line of the status is good (GOODSIG and the right VALIDSIG): only the bad-status line may stop it."""
    for mode in ("build", "resolve"):
        p = bb.run(mode, FAKE_GPG_STATUS=STATUS_GOOD + "\n" + status, FAKE_GPG_RC_BAD=rc, FAKE_GPG_BAD_FILE="bash.tar.gz",
                   FAKE_GPG_STATUS_BAD=STATUS_GOOD + "\n" + status)
        assert p.returncode == 1 and want in p.stderr, (mode, p.returncode, p.stderr)
        assert bb.marks() == []


def test_build_bash_a_bad_signature_on_a_patch_stops_before_tar(bb):
    p = bb.run("build", FAKE_GPG_BAD_FILE="bash53-002", FAKE_GPG_STATUS_BAD=STATUS_GOOD + "\n[GNUPG:] BADSIG X y")
    assert p.returncode == 1 and "bad signature status for bash53-002" in p.stderr, p.stderr
    assert bb.marks() == [] and "SIGNATURES OK" not in p.stdout
    assert [c[-1].rsplit("/", 1)[1] for c in bb.curls()][-2:] == ["bash53-002", "bash53-002.sig"]


@pytest.mark.parametrize("status, want", [
    ("[GNUPG:] GOODSIG X Chet\n[GNUPG:] VALIDSIG %s 2025-01-01 1 0 4 0 1 10 00 %s" % (SUBFPR, OTHER), "is not signed by the primary key"),
    # the pinned fingerprint in the FIRST field (the signing key) but another primary key: only the last field counts
    ("[GNUPG:] GOODSIG X Chet\n[GNUPG:] VALIDSIG %s 2025-01-01 1 0 4 0 1 10 00 %s" % (FPR, OTHER), "is not signed by the primary key"),
    ("[GNUPG:] GOODSIG X Chet", "is not signed by the primary key"),
    ("[GNUPG:] VALIDSIG %s 2025-01-01 1 0 4 0 1 10 00 %s" % (SUBFPR, FPR), "no good signature on bash.tar.gz"),
    ("", "no good signature on bash.tar.gz"),
    ("[GNUPG:] GOODSIG X Chet\n[GNUPG:] VALIDSIG %s 2025-01-01 1 0 4 0 1 10 00 %s" % (SUBFPR, FPR[:-1] + "C"), "is not signed by the primary key"),
], ids=["another primary", "pinned only as the signing key", "no VALIDSIG", "no GOODSIG", "empty status", "one digit off"])
def test_build_bash_a_signature_by_another_primary_key_is_refused(bb, status, want):
    p = bb.run("build", FAKE_GPG_STATUS=status, FAKE_GPG_STATUS_BAD=status)
    assert p.returncode == 1 and want in p.stderr, (p.returncode, p.stderr)
    assert bb.marks() == []


@pytest.mark.parametrize("key, name", [("BASH_SRC_SHA256", "BASH_SRC_SHA256"), ("BASH_PATCHES_SHA256", "BASH_PATCHES_SHA256")])
def test_build_bash_a_hash_that_differs_from_the_pin_stops_before_tar(bb, key, name):
    p = bb.run("build", **{key: "9" * 64})
    assert p.returncode == 1 and "%s: computed" % name in p.stderr and "PINS says %s" % ("9" * 64) in p.stderr, p.stderr
    assert bb.marks() == []


@pytest.mark.parametrize("env, want", [({"FAKE_READELF_DYNAMIC": "1"}, "is not static"),
                                       ({"FAKE_BASH_VERSION": "5.3.19"}, "reports"),
                                       ({"FAKE_BASH_TCP": "connected"}, "/dev/tcp/127.0.0.1/1 connected"),
                                       ({"FAKE_BASH_TCP": "missing"}, "/dev/tcp redirection missing"),
                                       ({"BASH_BIN_SHA256": "9" * 64}, "BASH_BIN_SHA256: computed")])
def test_build_bash_the_built_binary_must_be_static_versioned_networked_and_pinned(bb, env, want):
    p = bb.run("build", **env)
    assert p.returncode == 1 and want in p.stderr, (p.returncode, p.stderr)
    assert bb.marks() == ["tar", "patch", "patch", "configure", "make"]


def test_build_bash_resolve_mode_prints_signatures_ok_and_the_pins(bb):
    p = bb.run("resolve", BASH_SRC_SHA256="UNSET", BASH_PATCHES_SHA256="9" * 64, BASH_BIN_SHA256=bb.bin)
    assert p.returncode == 0, (p.stdout, p.stderr)
    lines = p.stdout.splitlines()
    assert lines[0] == "SIGNATURES OK: bash-5.3.tar.gz and 2 patches, primary key %s" % FPR
    assert "PIN BASH_SRC_SHA256 %s pinned: PLACEHOLDER" % bb.src in lines
    assert "PIN BASH_PATCHES_SHA256 %s pinned: DIFFERS (%s)" % (bb.pat, "9" * 64) in lines
    assert "PIN BASH_BIN_SHA256 %s pinned: same" % bb.bin in lines
    assert len([ln for ln in lines if ln.startswith("PIN ")]) == 3


def test_build_bash_resolve_mode_with_every_pin_unset(bb):
    p = bb.run("resolve", BASH_SRC_SHA256="UNSET", BASH_PATCHES_SHA256="UNSET", BASH_BIN_SHA256="UNSET")
    assert p.returncode == 0 and p.stdout.count("pinned: PLACEHOLDER") == 3, (p.stdout, p.stderr)
    assert "PIN BASH_SRC_SHA256 %s " % bb.src in p.stdout and "PIN BASH_PATCHES_SHA256 %s " % bb.pat in p.stdout
    assert "PIN BASH_BIN_SHA256 %s " % bb.bin in p.stdout


def test_build_bash_resolve_mode_still_refuses_a_bad_signature(bb):
    p = bb.run("resolve", BASH_SRC_SHA256="UNSET", BASH_PATCHES_SHA256="UNSET", BASH_BIN_SHA256="UNSET",
               FAKE_GPG_BAD_FILE="bash.tar.gz", FAKE_GPG_STATUS_BAD="[GNUPG:] BADSIG X y")
    assert p.returncode == 1 and "PIN " not in p.stdout and "SIGNATURES OK" not in p.stdout and bb.marks() == []


def test_manifest_notices_an_in_repo_file_edited_without_repinning(pins_lib):
    """An in-repo tool (perl-shim) whose file no longer hashes to its manifest sha256 is a PROBLEM (exit 2): the file_sha256
    check once reused the variable holding sha256, so this comparison could never fire."""
    fill_bash_pins(pins_lib)
    set_tool(pins_lib, "perl-shim", "sha256", "9" * 64)
    p = vt(pins_lib, "--profiles", "core")
    assert p.returncode == 2 and "PROBLEM tool perl-shim: minimal/perl-shim does not hash to the sha256" in p.stdout, p.stdout


@pytest.mark.parametrize("value", ["c" * 63, "C" * 64, "TODO"])
def test_manifest_file_sha256_format_on_a_tool_without_a_pins_pair(pins_lib, value):
    """file_sha256 on a tool PINS does not describe (node): only the format check can refuse a malformed value (exit 2)."""
    t = (pins_lib / "TOOLS.toml").read_text()
    t2 = t.replace('name = "node"\n', 'name = "node"\nfile_sha256 = "%s"\n' % value, 1)
    assert t2 != t
    (pins_lib / "TOOLS.toml").write_text(t2)
    p = vt(pins_lib, "--profiles", "node")
    assert p.returncode == 2 and "PROBLEM tool node: file_sha256 is not 64 lowercase hex" in p.stdout, p.stdout

