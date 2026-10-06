"""lib/eq-container with the fake `container` CLI (tests/fake-container/container; fixture eqc_env in conftest.py).

lib.sh: the argv of every `container run` (eq_run: no network, read-only root, no capabilities, an init, VM size, process
limit, unprivileged user, capped tmpfs /tmp and /work, only read-only mounts plus the /work source copy, a fixed KEY=VALUE
environment, the tag that runs), the digest check before the run (eq_require_image), the comma refusals, the watchdog, the
sweep and the services test. eq-container.sh: usage errors, the three skip paths (exit 10), status, print-env and the install
flow against stub build/verify/probe scripts (the real ones need the real CLI: probe.sh proves the isolation on the host).

What the fake assumes about the real CLI is listed, [unverified] where it is, in the fake's header.
Run: /Users/pmrj/.claude/venvs/tools/bin/python -m pytest -q tests/test_eq_container.py
"""
import hashlib
import io
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import time
import tomllib
from pathlib import Path

import pytest

from conftest import BASH, DIGEST_A, DIGEST_B, EQC_LIB, EQC_TAGS, fill_bash_pins, san, set_pin

MIN = EQC_TAGS["min-both"]


def ej(*args, stdin: "str | None" = None):
    """eqc_json.py MODE ARGS (stdin: the CLI's JSON)."""
    return subprocess.run([sys.executable, "-I", str(EQC_LIB / "eqc_json.py"), *map(str, args)], input=stdin,
                          capture_output=True, text=True, timeout=60, check=False)


def _tar(members: dict) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as t:
        for name, data in members.items():
            ti = tarfile.TarInfo(name)
            ti.size = len(data)
            t.addfile(ti, io.BytesIO(data))
    return buf.getvalue()


def save_archive(path: Path, layers: list, config: dict) -> Path:
    """An `image save` archive in the docker-save layout (manifest.json, the config, one tar per layer); each layer maps
    member names to file bytes."""
    outer = {"config.json": json.dumps(config).encode()}
    for i, members in enumerate(layers):
        outer["layer%d.tar" % i] = _tar(members)
    outer["manifest.json"] = json.dumps([{"Config": "config.json",
                                          "Layers": ["layer%d.tar" % i for i in range(len(layers))]}]).encode()
    path.write_bytes(_tar(outer))
    return path


def vals(argv, flag):
    """Every value that follows `flag` in an argv."""
    return [argv[i + 1] for i, a in enumerate(argv[:-1]) if a == flag]


def opts(argv):
    """The `container run` options of a logged run argv: everything before the image (the tag under eq.invalid/)."""
    i = next(i for i, a in enumerate(argv) if a.startswith("eq.invalid/"))
    return argv[1:i], argv[i], argv[i + 1:]


# ---------------------------------------------------------------------------------------------------- eq_run: the argv
def test_eq_run_argv_carries_every_isolation_flag(eqc_env):
    eqc_env.record("min-both")
    p = eqc_env.sh("eq_run eq-t-1 30 /bin/echo hello")
    assert p.returncode == 0 and p.stdout.strip() == "hello", (p.stdout, p.stderr)
    calls = eqc_env.calls()
    # the digest check runs before the run, against the tag
    assert calls[0][:2] == ["image", "inspect"] and calls[0][-1] == MIN, calls
    (run,) = eqc_env.runs()
    o, image, cmd = opts(run)
    assert image == MIN and "@" not in image                  # the tag runs; the digest was checked just before
    assert cmd == ["/bin/echo", "hello"]
    for flag in ("--rm", "--read-only", "--init"):
        assert flag in o, flag
    assert vals(o, "--network") == ["none"] and vals(o, "--cap-drop") == ["ALL"]
    assert vals(o, "-m") == ["8G"] and vals(o, "-c") == ["2"] and vals(o, "--ulimit") == ["nproc=512"]
    assert vals(o, "--user") == ["10001:10001"] and vals(o, "-w") == ["/work"] and vals(o, "--name") == ["eq-t-1"]
    assert sorted(vals(o, "--tmpfs")) == ["/tmp:size=2G,mode=1777", "/work:size=1G,mode=1777"]
    assert vals(o, "--mount") == []                           # no host path at all unless the caller stages one
    envs = vals(o, "-e")
    assert envs and all("=" in e for e in envs), envs         # never `-e KEY` (it would inherit the host's value)
    assert "HOME=/tmp" in envs and not any(e.startswith(("PATH=", "SSH_", "ANTHROPIC", "GH_")) for e in envs)
    assert set(vals(o, "--label")) == {"eq-harness=1", "eq-run=testrun"}
    forbidden = {"--privileged", "-v", "--volume", "--publish", "-p", "--ssh", "--cap-add", "--env-file", "--dns"}
    assert not forbidden & set(o), forbidden & set(o)


def test_eq_run_limits_follow_the_env_knobs(eqc_env):
    eqc_env.record("min-both")
    p = eqc_env.sh("EQ_RUN_MEMORY=1G EQ_RUN_NPROC=64 EQ_RUN_WORK_SIZE=8M eq_run eq-t-2 30 /usr/bin/true",
                   EQ_CPUS=1, EQ_USER="20002:20002", EQ_TMP_SIZE="64M")
    assert p.returncode == 0, p.stderr
    o, _, _ = opts(eqc_env.runs()[0])
    assert vals(o, "-m") == ["1G"] and vals(o, "--ulimit") == ["nproc=64"] and vals(o, "-c") == ["1"]
    assert vals(o, "--user") == ["20002:20002"]
    assert sorted(vals(o, "--tmpfs")) == ["/tmp:size=64M,mode=1777", "/work:size=8M,mode=1777"]


def test_work_mount_is_a_read_only_source_copy(eqc_env, tmp_path):
    """A /work bind becomes /eqsrc/work (read-only) copied into the /work tmpfs: what the code writes never reaches the
    host directory. Other mounts must be read-only and pass through unchanged."""
    eqc_env.record("min-both")
    src = tmp_path / "src"
    src.mkdir()
    (src / "check.txt").write_text("staged\n")
    fix = tmp_path / "fix"
    fix.mkdir()
    snippet = ('EQ_RUN_MOUNTS=(--mount "type=bind,source=%s,target=/work" --mount "type=bind,source=%s,target=/fixture,readonly"); '
               'eq_run eq-t-3 30 /bin/sh -c "cat check.txt; echo new > written.txt; ls"' % (src, fix))
    p = eqc_env.sh(snippet)
    assert p.returncode == 0, p.stderr
    assert "staged" in p.stdout and "written.txt" in p.stdout
    assert sorted(x.name for x in src.iterdir()) == ["check.txt"]        # the write stayed in the tmpfs copy
    o, _, cmd = opts(eqc_env.runs()[0])
    assert vals(o, "--mount") == ["type=bind,source=%s,target=/eqsrc/work,readonly" % src,
                                  "type=bind,source=%s,target=/fixture,readonly" % fix]
    assert cmd[:6] == ["/bin/sh", "-c", cmd[2], "eq-run", "/eqsrc/work", "/work"] and cmd[6] == "--"
    assert '"$1"' in cmd[2] and str(src) not in cmd[2]                   # paths are arguments, never spliced into the script


def test_stdin_file_is_fed_with_dash_i(eqc_env, tmp_path):
    eqc_env.record("min-both")
    f = tmp_path / "in.txt"
    f.write_text("from-stdin\n")
    p = eqc_env.sh('EQ_RUN_STDIN="%s" eq_run eq-t-4 30 /bin/cat' % f)
    assert p.returncode == 0 and p.stdout.strip() == "from-stdin", (p.stdout, p.stderr)
    o, _, _ = opts(eqc_env.runs()[0])
    assert "-i" in o


def test_tunnel_is_the_one_read_write_mount(eqc_env, tmp_path):
    eqc_env.record("min-both")
    chan = tmp_path / "tun" / ("a" * 32) / ("c" + "b" * 32)
    chan.mkdir(parents=True)
    p = eqc_env.sh('EQ_RUN_TUNNEL="%s" eq_run eq-t-5 30 /usr/bin/true' % chan)
    assert p.returncode == 0, p.stderr
    o, _, _ = opts(eqc_env.runs()[0])
    assert vals(o, "--mount") == ["type=bind,source=%s,target=/eq/tunnel" % chan]


# ----------------------------------------------------------------------------------- eq_run: refusals (nothing runs)
@pytest.mark.parametrize("mount", [
    "type=bind,source=/tmp/a,b,target=/work",                         # a comma in the /work source
    "type=bind,source=/tmp/a,b,target=/fixture,readonly",             # a comma in a read-only source
    "type=bind,source=/tmp/a,target=/fix,ture,readonly",              # a comma in a target
    "type=bind,source=/tmp/a,target=/fixture,readonly=false,readonly",  # an extra key
    "type=bind,source=/tmp/a,target=/work,readonly=false",            # /work with a key appended
    "type=bind,source=/tmp/a,target=/fixture",                        # read-write outside /work
    "type=volume,source=v,target=/fixture,readonly",                  # not a bind
    "type=bind,source=,target=/fixture,readonly",                     # an empty source
    "type=bind,source=/tmp/a,target=fixture,readonly",                # a relative target
    # `--mount` (1.5.0 Parser.mount) splits each key=value at '=' and drops empty pieces: an '=' inside a path is an
    # error, a trailing one cuts the path (source=/tmp/a= mounts /tmp/a)
    "type=bind,source=/tmp/a=b,target=/fixture,readonly",             # an '=' in a read-only source
    "type=bind,source=/tmp/a=,target=/fixture,readonly",              # a trailing '=' in a source
    "type=bind,source=/tmp/a=b,target=/work",                         # an '=' in the /work source
    "type=bind,source=/tmp/a,target=/fix=ture,readonly",              # an '=' in a target
])
def test_eq_run_refuses_bad_mounts(eqc_env, mount):
    eqc_env.record("min-both")
    p = eqc_env.sh("EQ_RUN_MOUNTS=(--mount '%s'); eq_run eq-t-6 30 /usr/bin/true" % mount)
    assert p.returncode == 2, (p.returncode, p.stderr)
    assert "eq_run: mount" in p.stderr
    assert eqc_env.runs() == []


def test_eq_run_refuses_a_bare_word_in_mounts(eqc_env):
    eqc_env.record("min-both")
    p = eqc_env.sh("EQ_RUN_MOUNTS=(-v /:/host); eq_run eq-t-7 30 /usr/bin/true")
    assert p.returncode == 2 and "only --mount pairs" in p.stderr and eqc_env.runs() == []


@pytest.mark.parametrize("tunnel, why", [("/tmp/x,readonly=false", "holds a comma"),
                                         ("/tmp/c,target=/", "holds a comma"),
                                         ("/tmp/x=y", "holds a comma or '='"),
                                         ("/tmp/x/c=", "holds a comma or '='"),
                                         ("relative/chan", "absolute path")])
def test_eq_run_refuses_a_bad_tunnel(eqc_env, tunnel, why):
    eqc_env.record("min-both")
    p = eqc_env.sh("EQ_RUN_TUNNEL='%s' eq_run eq-t-8 30 /usr/bin/true" % tunnel)
    assert p.returncode == 2 and why in p.stderr, p.stderr
    assert eqc_env.runs() == []


@pytest.mark.parametrize("knob", [{"EQ_TMP_SIZE": "2G,mode=0777"}, {"EQ_WORK_SIZE": "1G,mode=0777"},
                                  {"EQ_RUN_WORK_SIZE": "8M,uid=0"}])
def test_eq_run_refuses_a_comma_in_a_tmpfs_size(eqc_env, knob):
    eqc_env.record("min-both")
    p = eqc_env.sh("eq_run eq-t-9 30 /usr/bin/true", **knob)
    assert p.returncode == 2 and "tmpfs size holds a comma" in p.stderr, p.stderr
    assert eqc_env.runs() == []


@pytest.mark.parametrize("name", ["w,x", "w:x", "w=x"])
def test_work_root_that_breaks_mount_is_refused_at_source_time(eqc_env, tmp_path, name):
    p = eqc_env.sh("echo sourced", EQ_WORK_ROOT=tmp_path / name)
    assert p.returncode == 2 and "breaks --mount" in p.stderr and "sourced" not in p.stdout


# ------------------------------------------------------------------------------------ the digest check before every run
def test_digest_mismatch_refuses_the_run(eqc_env):
    eqc_env.record("min-both", digest=DIGEST_A)
    p = eqc_env.sh("eq_run eq-t-10 30 /usr/bin/true", EQ_FAKE_CONTAINER_DIGEST=DIGEST_B)
    assert p.returncode == 11 and "rebuilt or retagged" in p.stderr, p.stderr
    assert eqc_env.runs() == []


def test_missing_image_refuses_the_run(eqc_env):
    eqc_env.record("min-both")
    p = eqc_env.sh("eq_run eq-t-11 30 /usr/bin/true", EQ_FAKE_CONTAINER_MISSING=MIN)
    assert p.returncode == 11 and "not present" in p.stderr and eqc_env.runs() == []


def test_unrecorded_image_is_not_trusted(eqc_env):
    p = eqc_env.sh("eq_run eq-t-12 30 /usr/bin/true")
    assert p.returncode == 11 and "no build record" in p.stderr and eqc_env.runs() == []
    p = eqc_env.sh("EQ_RUN_IMAGE=%s@%s eq_run eq-t-12 30 /usr/bin/true" % (MIN, DIGEST_A))
    assert p.returncode == 11 and eqc_env.runs() == []            # a pin alone is not enough without EQ_ALLOW_UNRECORDED
    p = eqc_env.sh("EQ_RUN_IMAGE=%s@%s eq_run eq-t-12 30 /usr/bin/true" % (MIN, DIGEST_A), EQ_ALLOW_UNRECORDED=1)
    assert p.returncode == 0 and len(eqc_env.runs()) == 1, p.stderr


def test_pin_that_contradicts_the_record_is_refused(eqc_env):
    eqc_env.record("min-both", digest=DIGEST_A)
    p = eqc_env.sh("EQ_RUN_IMAGE=%s@%s eq_run eq-t-13 30 /usr/bin/true" % (MIN, DIGEST_B))
    assert p.returncode == 11 and "pins" in p.stderr and eqc_env.runs() == []


@pytest.mark.parametrize("shape, ok", [("both", True), ("descriptor", True), ("id", True), ("none", False),
                                       ("conflict", False)])
def test_digest_shapes_fail_closed(eqc_env, shape, ok):
    """The digest: .configuration.descriptor.digest and/or .id (its hex); both present must agree; neither = refused."""
    eqc_env.record("min-both")
    p = eqc_env.sh("eq_run eq-t-14 30 /usr/bin/true", EQ_FAKE_CONTAINER_INSPECT=shape)
    assert (p.returncode == 0) is ok, (shape, p.returncode, p.stderr)
    assert len(eqc_env.runs()) == (1 if ok else 0)


def inspect_1_5_0(digest: str, ref: str = MIN) -> dict:
    """`container image inspect REF` as CLI 1.5.0 encodes it (Sources/ContainerResource/Image/ImageResource.swift at tag
    1.5.0: ImageResource.encode writes id, configuration, variants; configuration is {creationDate, name, descriptor};
    id is the hex part of configuration.descriptor.digest, without "sha256:")."""
    return {"id": digest.split(":", 1)[1], "variants": [],
            "configuration": {"creationDate": "2026-10-05T00:00:00Z", "name": ref,
                              "descriptor": {"mediaType": "application/vnd.oci.image.index.v1+json", "digest": digest,
                                             "size": 1}}}


def test_digest_reads_the_1_5_0_image_resource_shape():
    def digest_of(obj):
        p = ej("digest", stdin=json.dumps([obj]))
        assert p.returncode in (0, 1) and (p.returncode == 0) == bool(p.stdout), (p.returncode, p.stdout, p.stderr)
        return p.stdout.strip() or None

    good = inspect_1_5_0(DIGEST_A)
    assert digest_of(good) == DIGEST_A
    assert digest_of({**good, "id": DIGEST_B.split(":", 1)[1]}) is None   # descriptor and id disagree
    assert digest_of({**good, "id": "A" * 64}) == DIGEST_A                # an id that is no digest is not read
    no_alg = json.loads(json.dumps(good))
    no_alg["configuration"]["descriptor"]["digest"] = "a" * 64            # the descriptor names its algorithm
    del no_alg["id"]
    assert digest_of(no_alg) is None


# ------------------------------------------------------------------------------------------- watchdog, sweep, services
def test_watchdog_kills_after_the_timeout(eqc_env):
    eqc_env.record("min-both")
    t0 = time.monotonic()
    p = eqc_env.sh("eq_run eq-t-15 1 /bin/sleep 8; echo rc=$?", timeout=60)
    assert "rc=124" in p.stdout, (p.stdout, p.stderr)
    assert ["kill", "eq-t-15"] in eqc_env.calls()
    assert time.monotonic() - t0 < 30


def test_sweep_kills_and_deletes_only_this_runs_containers(eqc_env):
    rows = ('[{"configuration":{"id":"mine-1","labels":{"eq-run":"testrun"}}},'
            '{"configuration":{"id":"other","labels":{"eq-run":"another"}}},'
            '{"configuration":{"id":"mine-2","labels":{"eq-harness":"1","eq-run":"testrun"}}}]')
    p = eqc_env.sh("eq_sweep", EQ_FAKE_CONTAINER_LIST_JSON=rows)
    assert p.returncode == 0, p.stderr
    calls = eqc_env.calls()
    assert ["list", "--all", "--format", "json"] in calls
    assert ["kill", "mine-1", "mine-2"] in calls and ["delete", "--force", "mine-1", "mine-2"] in calls
    assert not [c for c in calls if "other" in c]


@pytest.mark.parametrize("extra, why", [
    ({"EQ_FAKE_CONTAINER_DOWN": "1"}, "services are not running"),
    ({"EQ_HOST_ARCH": "x86_64"}, "not arm64"),
    ({"EQ_CONTAINER_BIN": "/nonexistent/container"}, "CLI was not found"),
])
def test_eqc_state_reports_why(eqc_env, extra, why):
    p = eqc_env.sh('eqc_state; echo "ok=$EQC_OK why=$EQC_WHY"', **extra)
    assert "ok=0" in p.stdout and why in p.stdout, p.stdout
    p = eqc_env.sh("eq_need_container; echo reached", **extra)
    assert p.returncode == 10 and "reached" not in p.stdout


def test_eqc_state_ok(eqc_env):
    p = eqc_env.sh('eqc_state; echo "ok=$EQC_OK"')
    assert "ok=1" in p.stdout and ["system", "status"] in eqc_env.calls()


def test_read_only_mode_creates_nothing(eqc_env):
    p = eqc_env.sh("echo $EQ_STATE_DIR", EQ_NO_STATE_WRITE=1)
    assert p.returncode == 0 and not eqc_env.state.exists()


def test_state_dir_is_private(eqc_env):
    p = eqc_env.sh("true")
    assert p.returncode == 0
    for d in (eqc_env.state, eqc_env.state / "work"):
        assert stat.S_IMODE(d.stat().st_mode) == 0o700, d


# ---------------------------------------------------------------------------------------------- eq-container.sh
@pytest.mark.parametrize("args, want", [
    (["install", "--bogus"], "unknown option: --bogus"),
    (["install", "--set", "huge"], "--set must be min (full was removed)"),
    (["install", "--set", "full"], "--set full was removed"),
    (["install", "--set", "all"], "--set must be min (full was removed)"),
    (["install", "--no-snapshot"], "unknown option: --no-snapshot"),
    (["install", "--set", "min", "--profiles", "core"], "exclude each other"),
    (["install", "--profiles"], "--profiles needs a value"),
    (["install", "--profiles="], "--profiles needs a value"),
    (["install", "--profiles", "core,nosuch"], "unknown profile: nosuch"),
    (["frobnicate"], "unknown command: frobnicate"),
])
def test_driver_usage_errors(eqc_env, args, want):
    p = eqc_env.run("eq-container.sh", *args)
    assert p.returncode == 2 and want in p.stderr, (p.returncode, p.stderr)
    assert not eqc_env.state.exists() and eqc_env.calls() == []


@pytest.mark.parametrize("cmd", ["install", "check", "uninstall", "status"])
def test_driver_refuses_set_full_for_every_command(eqc_env, cmd):
    p = eqc_env.run("eq-container.sh", cmd, "--set", "full")
    assert p.returncode == 2 and "--set full was removed" in p.stderr and "--profiles core" in p.stderr, p.stderr
    assert eqc_env.calls() == [] and not eqc_env.state.exists()


@pytest.mark.parametrize("extra, why", [
    ({"EQ_CONTAINER_BIN": "/nonexistent/container"}, "the container CLI is not installed"),
    ({"EQ_HOST_ARCH": "x86_64"}, "this host is not arm64"),
    ({"EQ_FAKE_CONTAINER_DOWN": "1"}, "the container services are not running"),
])
def test_driver_skips_with_exit_10(eqc_env, extra, why):
    p = eqc_env.run("eq-container.sh", "install", "--yes", **extra)
    assert p.returncode == 10 and why in p.stderr, (p.returncode, p.stderr)
    assert eqc_env.status() == "skipped" and eqc_env.status("EQ_CONTAINER_STATUS_WHY").startswith(why)
    assert stat.S_IMODE((eqc_env.state / "status.env").stat().st_mode) == 0o600
    assert not [c for c in eqc_env.calls() if c[0] in ("run", "build")]
    assert not (eqc_env.state / "images").exists()


def test_driver_dry_run_skip_writes_nothing(eqc_env):
    p = eqc_env.run("eq-container.sh", "install", "--dry-run", EQ_FAKE_CONTAINER_DOWN=1)
    assert p.returncode == 10 and not eqc_env.state.exists()


def _status(env, st="ok", image="eq.invalid/eq-min:4.34.1-arm64@" + DIGEST_A):
    env.state.mkdir(parents=True, exist_ok=True)
    (env.state / "status.env").write_text("EQ_CONTAINER_STATUS=%s\nEQ_CONTAINER_STATUS_AT=2026-10-05T00:00:00Z\n" % st)
    (env.state / "image.env").write_text("EQ_IMAGE=%s\n" % image)


def test_print_env_only_after_a_verified_install(eqc_env):
    p = eqc_env.run("eq-container.sh", "print-env")
    assert p.returncode == 1 and p.stdout == ""
    _status(eqc_env)
    p = eqc_env.run("eq-container.sh", "print-env")
    assert p.returncode == 0 and p.stdout.splitlines() == ["EQ_ISOLATION=container",
                                                           "EQ_IMAGE=eq.invalid/eq-min:4.34.1-arm64@" + DIGEST_A]
    good = "eq.invalid/eq-min:4.34.1-arm64@" + DIGEST_A
    for st, img in (("skipped", good), ("failed", good), ("ok", "eq-min:4.34.1-arm64@" + DIGEST_A),
                    ("ok", "eq.invalid/eq-min:4.34.1-arm64"), ("ok", "")):
        _status(eqc_env, st, img)
        p = eqc_env.run("eq-container.sh", "print-env")
        assert p.returncode == 1 and p.stdout == "", (st, img, p.stdout)
    assert eqc_env.calls() == []                                   # reads state files only


def test_status_reads_state_files_only(eqc_env):
    p = eqc_env.run("eq-container.sh", "status")
    assert p.returncode == 1 and "not installed" in p.stdout
    _status(eqc_env)
    p = eqc_env.run("eq-container.sh", "status")
    assert p.returncode == 0 and "eq-container: EQ_CONTAINER_STATUS=ok" in p.stdout
    assert eqc_env.calls() == []


# ------------------------------------------------------------------------- eq-container.sh install with stub stages
STUB_BUILD = r"""#!/bin/bash
# stub build.sh (test): logs its argv; on a real run writes the records and image.env as build.sh does
printf '%s\n' "$*" >> "$STUB_LOG.build"
case " $* " in *" --dry-run "*) echo " ${STUB_PLAN:-build} min-both (stub)"; exit 0;; esac
cat > "$STUB_LOG.stdin"
rc=${STUB_BUILD_RC:-0}; [ "$rc" = 0 ] || exit "$rc"
mkdir -p "$EQ_STATE_DIR/images"
d=${STUB_DIGEST:-sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa}
{ echo "EQ_ISOLATION=container"
  echo "EQ_MIN_BOTH_TAG=eq.invalid/eq-min:4.34.1-arm64"; echo "EQ_MIN_BOTH_DIGEST=$d"
  echo "EQ_MIN_PY_TAG=eq.invalid/eq-py-min:4.34.1-arm64"; echo "EQ_MIN_PY_DIGEST=$d"
  echo "EQ_IMAGE=eq.invalid/eq-min:4.34.1-arm64@$d"
  echo "EQ_CONTAINER_IMAGE_PF=eq.invalid/eq-min:4.34.1-arm64@$d"
  echo "EQ_CONTAINER_IMAGE_CP=eq.invalid/eq-py-min:4.34.1-arm64@$d"
  echo "EQ_CONTAINER_IMAGE_CR=eq.invalid/eq-py-min:4.34.1-arm64@$d"; } > "$EQ_STATE_DIR/image.env"
echo "BUILD: OK (stub)"
"""
STUB_STAGE = r"""#!/bin/bash
printf '%s %s\n' "$(basename "$0")" "$*" >> "$STUB_LOG.stages"
[ -z "${STUB_FAIL:-}" ] || [ "$STUB_FAIL" != "$(basename "$0")" ] || { echo "stub failure"; exit 1; }
exit 0
"""


@pytest.fixture
def stub_lib(tmp_path):
    lib = tmp_path / "eq-container"
    shutil.copytree(EQC_LIB, lib, ignore=shutil.ignore_patterns(".state", "__pycache__"))
    (lib / "build.sh").write_text(STUB_BUILD)
    for s in ("verify-tools.sh", "probe.sh"):
        (lib / s).write_text(STUB_STAGE)
    return lib


def _stages(tmp_path):
    p = tmp_path / "stub.stages"
    return p.read_text().splitlines() if p.exists() else []


def test_install_flow_and_rerun_skip(eqc_env, stub_lib, tmp_path):
    knobs = dict(lib=stub_lib, STUB_LOG=tmp_path / "stub")
    p = eqc_env.run("eq-container.sh", "install", "--yes", **knobs)
    assert p.returncode == 0, (p.stdout, p.stderr)
    assert eqc_env.status() == "ok" and eqc_env.status("EQ_CONTAINER_STATUS_PROBE") == "PASS"
    refs = eqc_env.status("EQ_CONTAINER_STATUS_VERIFIED").split(",")
    assert refs == sorted(["eq.invalid/eq-min:4.34.1-arm64@" + DIGEST_A, "eq.invalid/eq-py-min:4.34.1-arm64@" + DIGEST_A])
    assert eqc_env.status("EQ_CONTAINER_STATUS_PROFILES") == "core"
    assert (tmp_path / "stub.build").read_text().splitlines() == ["--profiles core --yes"]
    st = _stages(tmp_path)
    assert st[0].startswith("verify-tools.sh --images --deep --inspect --profiles core") and st[-1].startswith("probe.sh"), st
    p = eqc_env.run("eq-container.sh", "print-env", lib=stub_lib)
    assert p.stdout.splitlines()[0] == "EQ_ISOLATION=container"
    # unchanged images and pins: verification and probe are not repeated
    n = len(_stages(tmp_path))
    p = eqc_env.run("eq-container.sh", "install", "--yes", **knobs)
    assert p.returncode == 0 and "already verified" in p.stdout and len(_stages(tmp_path)) == n
    # another digest: verified again
    p = eqc_env.run("eq-container.sh", "install", "--yes", STUB_DIGEST=DIGEST_B, **knobs)
    assert p.returncode == 0 and len(_stages(tmp_path)) > n


@pytest.mark.parametrize("knob, rc, status", [
    ({"STUB_BUILD_RC": "12"}, 12, "failed"), ({"STUB_BUILD_RC": "13"}, 13, "failed"),
    ({"STUB_BUILD_RC": "10"}, 10, "skipped"), ({"STUB_FAIL": "probe.sh"}, 15, "failed"),
    ({"STUB_FAIL": "verify-tools.sh"}, 16, "failed"),
])
def test_install_failures_have_their_exit_codes(eqc_env, stub_lib, tmp_path, knob, rc, status):
    p = eqc_env.run("eq-container.sh", "install", "--yes", lib=stub_lib, STUB_LOG=tmp_path / "stub", **knob)
    assert p.returncode == rc, (p.returncode, p.stdout, p.stderr)
    assert eqc_env.status() == status
    q = eqc_env.run("eq-container.sh", "print-env", lib=stub_lib)
    assert q.returncode == 1 and q.stdout == ""


def test_no_terminal_and_no_yes_never_builds(eqc_env, stub_lib, tmp_path):
    """Without --yes and without a terminal, eq-container.sh asks nothing and passes no --yes: build.sh decides (the real
    one refuses a build it cannot ask about, exit 2, which the driver turns into a skip)."""
    p = eqc_env.run("eq-container.sh", "install", lib=stub_lib, STUB_LOG=tmp_path / "stub", STUB_BUILD_RC="2")
    assert p.returncode == 10 and eqc_env.status() == "skipped", (p.stdout, p.stderr)
    assert "--yes" not in (tmp_path / "stub.build").read_text()


@pytest.mark.parametrize("changed", ["probe_inner.sh", "probe.d/50-tunnel.sh", "lib.sh", "eqc_json.py",
                                     "verify-tools.sh"])
def test_install_verifies_again_after_the_checking_code_changed(eqc_env, stub_lib, tmp_path, changed):
    """Unchanged images skip verification and probe only while the code that verified and probed them is unchanged too
    (an edit to the probe or the verifier, or another CLI, must not reuse an old PASS)."""
    knobs = dict(lib=stub_lib, STUB_LOG=tmp_path / "stub")
    assert eqc_env.run("eq-container.sh", "install", "--yes", **knobs).returncode == 0
    n = len(_stages(tmp_path))
    with open(stub_lib / changed, "a") as f:
        f.write("\n# changed\n")
    p = eqc_env.run("eq-container.sh", "install", "--yes", **knobs)
    assert p.returncode == 0 and "already verified" not in p.stdout, p.stdout
    assert len(_stages(tmp_path)) > n


def test_install_never_hands_its_stdin_to_build(eqc_env, stub_lib, tmp_path):
    """build.sh asks its own question when its stdin is a terminal, but its output goes to build.log: from a terminal,
    --no-prompt waited on a question nobody saw. The driver gives build.sh /dev/null (the stub stores what it read)."""
    p = eqc_env.run("eq-container.sh", "install", "--no-prompt", lib=stub_lib, STUB_LOG=tmp_path / "stub",
                    input="typed-by-the-caller\n")
    assert p.returncode == 0, (p.stdout, p.stderr)
    assert (tmp_path / "stub.stdin").read_text() == ""


def test_no_build_skips_a_due_build_and_build_due_reports_it(eqc_env, stub_lib, tmp_path):
    """--no-build (lib/eq-container/setup.sh without your consent to build): a due build is a skip (exit 10, "not consented"),
    never a question and never a build; with every image up to date the install goes on (verification, probe).
    build-due: 0 when build.sh's dry-run plan names a build, 1 when not, 10 without the CLI; it writes nothing."""
    knobs = dict(lib=stub_lib, STUB_LOG=tmp_path / "stub")
    assert eqc_env.run("eq-container.sh", "build-due", **knobs).returncode == 0
    assert eqc_env.run("eq-container.sh", "build-due", STUB_PLAN="skip", **knobs).returncode == 1
    p = eqc_env.run("eq-container.sh", "build-due", EQ_CONTAINER_BIN="/nonexistent/container", **knobs)
    assert p.returncode == 10 and not eqc_env.state.exists()
    assert set((tmp_path / "stub.build").read_text().splitlines()) == {"--profiles core --dry-run"}
    p = eqc_env.run("eq-container.sh", "install", "--no-build", **knobs, input="y\n")
    assert p.returncode == 10 and eqc_env.status() == "skipped", (p.stdout, p.stderr)
    assert eqc_env.status("EQ_CONTAINER_STATUS_WHY").startswith("the image build was not consented")
    assert "--build-container-images" in p.stderr and "build the images now?" not in p.stdout
    assert set((tmp_path / "stub.build").read_text().splitlines()) == {"--profiles core --dry-run"}       # never built
    p = eqc_env.run("eq-container.sh", "install", "--no-build", STUB_PLAN="skip", **knobs)
    assert p.returncode == 0 and eqc_env.status() == "ok", (p.stdout, p.stderr)
    assert (tmp_path / "stub.build").read_text().splitlines()[-1] == "--profiles core"               # no --yes
    # --yes wins over --no-build (consent given)
    p = eqc_env.run("eq-container.sh", "install", "--no-build", "--yes", STUB_DIGEST=DIGEST_B, **knobs)
    assert p.returncode == 0 and (tmp_path / "stub.build").read_text().splitlines()[-1] == "--profiles core --yes"


@pytest.mark.parametrize("args", [("--help",), ("install", "--help")])
def test_help_prints_the_header_only(eqc_env, args):
    p = eqc_env.run("eq-container.sh", *args)
    assert p.returncode == 0 and "eq-container.sh install" in p.stdout and "16 tools verification" in p.stdout
    assert "set -u" not in p.stdout and "here=" not in p.stdout and eqc_env.calls() == []


@pytest.mark.parametrize("script", ["eq-container.sh", "build.sh", "verify-tools.sh", "base-pins.sh"])
def test_help_prints_comment_lines_only(eqc_env, script):
    """--help prints the header comment and stops at the first line of code (a fixed `sed -n '2,Np'` range ran past it)."""
    p = subprocess.run([BASH, str(EQC_LIB / script), "--help"], capture_output=True, text=True, timeout=60, check=False,
                       env=eqc_env.environ())
    code = [ln for ln in p.stdout.splitlines() if not ln.startswith("#")]
    assert p.returncode == 0 and p.stdout and code == [], (code, p.stderr)


# ------------------------------------------------------------------------ eqc_json.py and verify-tools.sh on archives
def test_root_level_whiteout_and_dotfiles_keep_their_names(tmp_path):
    """Layer member names lose a leading "./" only: ".wh.opt" (a whiteout of /opt at the root) and ".profile" keep their
    dot (str.lstrip("./") ate it: /opt stayed visible and /.profile vanished)."""
    cfg = {"architecture": "arm64", "os": "linux", "config": {}}
    a = save_archive(tmp_path / "img.tar", [{"opt/eq/TOOLS.lock": b"lock\n", ".profile": b"p\n", "./etc/x": b"x\n"},
                                            {".wh.opt": b""}], cfg)
    assert ej("oci-cat", a, "/opt/eq/TOOLS.lock").returncode == 1
    p = ej("oci-cat", a, "/.profile")
    assert p.returncode == 0 and p.stdout == "p\n"
    p = ej("oci-cat", a, "/etc/x")
    assert p.returncode == 0 and p.stdout == "x\n"


def test_absolute_paths_are_found_in_the_image(tmp_path):
    """verify-tools.sh asks for absolute paths (/opt/eq/TOOLS.lock, every tool file): resolve() made them "//opt/...",
    which posixpath.normpath keeps, so no lock and no tool file was ever found (every --images run failed closed)."""
    cfg = {"architecture": "arm64", "os": "linux", "config": {}}
    a = save_archive(tmp_path / "img.tar", [{"opt/eq/TOOLS.lock": b"lock\n", "opt/bin/t": b"tool\n"}], cfg)
    p = ej("oci-cat", a, "/opt/eq/TOOLS.lock")
    assert p.returncode == 0 and p.stdout == "lock\n", (p.returncode, p.stdout)
    p = ej("oci-sha256", a, "/opt/bin/t", "/opt/none")
    want = ["%s  /opt/bin/t" % hashlib.sha256(b"tool\n").hexdigest(), "  /opt/none"]
    assert p.returncode == 0 and p.stdout.splitlines() == want, p.stdout


def test_verify_tools_saves_each_image_once_and_removes_it(eqc_env, tmp_path):
    """--images and --inspect read one `container image save` archive per image and run; its temp dir goes at exit (the
    cache lived in $(...) subshells: one multi-GB save per read, each left in TMPDIR)."""
    eqc_env.record("min-py")
    saves = tmp_path / "saves"
    saves.mkdir()
    cfg = {"architecture": "arm64", "os": "linux", "config": {"User": "10001", "Env": ["PATH=/opt/python/bin:/usr/bin"]}}
    save_archive(saves / (san(EQC_TAGS["min-py"]) + ".tar"), [{"opt/eq/TOOLS.lock": b""}], cfg)
    p = eqc_env.run("verify-tools.sh", "--select", "min-py", "--images", "--inspect", EQ_FAKE_CONTAINER_SAVE_DIR=saves)
    assert "IMAGE min-py" in p.stdout and "INSPECT min-py" in p.stdout, (p.stdout, p.stderr)
    # the one-layer archive is not the 21 pinned distroless layers plus one of ours
    assert "the bottom 21 layers are not the pinned distroless base's" in p.stdout, p.stdout
    assert len([c for c in eqc_env.calls() if c[:2] == ["image", "save"]]) == 1, eqc_env.calls()
    assert list(eqc_env.tmpdir.glob("eqc-save.*")) == []


# ---------------------------------------------------------------------------- oci-layers, --inspect and --deep on crafted images
def oci_archive(path: Path, layers: list, config: dict) -> list:
    """An `image save` archive in the OCI layout (index.json -> manifest blob -> config and layer blobs, named by their sha256);
    returns the layer digests, bottom first."""
    blobs = {}

    def put(data: bytes) -> str:
        d = hashlib.sha256(data).hexdigest()
        blobs["blobs/sha256/" + d] = data
        return "sha256:" + d

    ldig = [put(_tar(m)) for m in layers]
    man = {"schemaVersion": 2, "config": {"mediaType": "application/vnd.oci.image.config.v1+json", "digest": put(json.dumps(config).encode()),
                                          "size": 1},
           "layers": [{"mediaType": "application/vnd.oci.image.layer.v1.tar", "digest": d, "size": 1} for d in ldig]}
    idx = {"schemaVersion": 2, "manifests": [{"mediaType": "application/vnd.oci.image.manifest.v1+json", "digest": put(json.dumps(man).encode()),
                                              "platform": {"architecture": "arm64", "os": "linux"}}]}
    path.write_bytes(_tar({"index.json": json.dumps(idx).encode(), **blobs}))
    return ldig


CFG = {"architecture": "arm64", "os": "linux", "config": {"User": "10001:10001", "Env": ["PATH=/opt/eq/bin:/opt/uv:/opt/python/bin", "HOME=/tmp"]}}


def test_oci_layers_of_an_oci_layout_and_of_a_docker_save_archive(tmp_path):
    layers = [{"usr/bin/a": b"a"}, {"etc/b": b"b"}, {"opt/c": b"c"}]
    want = oci_archive(tmp_path / "oci.tar", layers, CFG)
    p = ej("oci-layers", tmp_path / "oci.tar")
    assert p.returncode == 0 and p.stdout.split() == want and len(want) == 3, (p.stdout, p.stderr)
    save_archive(tmp_path / "ds.tar", layers, CFG)
    p = ej("oci-layers", tmp_path / "ds.tar")
    assert p.returncode == 0 and p.stdout.split() == ["sha256:" + hashlib.sha256(_tar(m)).hexdigest() for m in layers] == want


def test_oci_layers_refuses_what_it_cannot_read(tmp_path):
    oci_archive(tmp_path / "empty.tar", [], CFG)
    assert ej("oci-layers", tmp_path / "empty.tar").returncode == 1
    save_archive(tmp_path / "ds0.tar", [], CFG)
    p = ej("oci-layers", tmp_path / "ds0.tar")
    assert p.returncode == 0 and p.stdout == ""                    # nothing to list: verify-tools.sh treats an empty list as unreadable
    (tmp_path / "none.tar").write_bytes(_tar({"x": b"1"}))
    assert ej("oci-layers", tmp_path / "none.tar").returncode == 1
    two = _tar({"manifest.json": json.dumps([{"Config": "c", "Layers": []}, {"Config": "c", "Layers": []}]).encode()})
    (tmp_path / "two.tar").write_bytes(two)
    assert ej("oci-layers", tmp_path / "two.tar").returncode == 1
    assert ej("oci-layers", tmp_path / "missing.tar").returncode == 1
    assert ej("oci-layers").returncode == 1 and ej("oci-layers", "a", "b").returncode == 1


def test_oci_layers_never_uses_a_blob_that_does_not_hash_to_its_name(tmp_path):
    a = tmp_path / "oci.tar"
    oci_archive(a, [{"x": b"1"}], CFG)
    outer = tarfile.open(a)
    members = {m.name: outer.extractfile(m).read() for m in outer.getmembers()}
    idx = json.loads(members["index.json"])
    name = "blobs/sha256/" + idx["manifests"][0]["digest"].split(":")[1]
    members[name] = members[name] + b" "                            # the manifest blob no longer hashes to its name
    a.write_bytes(_tar(members))
    assert ej("oci-layers", a).returncode == 1


def _crafted_base(lib: Path) -> list:
    """Replace base/*.json and the two PINS (and the ARG defaults) of a lib copy with a tiny distroless base of two layers;
    returns the layers' members."""
    members = [{"usr/bin/base-tool": b"base-tool-bytes\n"}, {"etc/base-file": b"base-file\n"}]
    ldig = ["sha256:" + hashlib.sha256(_tar(m)).hexdigest() for m in members]
    man = json.dumps({"schemaVersion": 2, "config": {"digest": "sha256:" + "c" * 64, "size": 1},
                      "layers": [{"digest": d, "size": 1} for d in ldig]}).encode()
    mdig = "sha256:" + hashlib.sha256(man).hexdigest()
    idx = json.dumps({"schemaVersion": 2, "manifests": [{"digest": mdig, "size": len(man),
                                                           "platform": {"architecture": "arm64", "os": "linux"}}]}).encode()
    (lib / "base" / "distroless-cc-debian13-nonroot.arm64.manifest.json").write_bytes(man)
    (lib / "base" / "distroless-cc-debian13-nonroot.index.json").write_bytes(idx)
    set_pin(lib, "DISTROLESS_CC", "gcr.io/distroless/cc-debian13@sha256:" + hashlib.sha256(idx).hexdigest(),
            files=("PINS", "Dockerfile.minimal", "Dockerfile.toolchains"))
    set_pin(lib, "DISTROLESS_CC_ARM64", mdig, files=("PINS", "Dockerfile.minimal", "Dockerfile.toolchains"))
    return members


def _config(**over) -> dict:
    cfg = json.loads(json.dumps(CFG))
    for k, v in over.items():
        if v is None:
            cfg["config"].pop(k, None)
        else:
            cfg["config"][k] = v
    return cfg


def _env(**kw) -> dict:
    return _config(Env=["%s=%s" % kv for kv in kw.items()])


IMGS = ("min-lean", "min-py", "min-both")          # the three distroless-cc images: one verify-tools run checks three cases at a time
PYTHON_PATH = "PATH=/opt/eq/bin:/opt/uv:/opt/python/bin"


def _ok(base):
    return base + [{"opt/eq/x": b"x"}]


# (id, layers of the image given the base's, config, docker-save layout, expected status, text the row must hold)
INSPECT_CASES = [
    ("good oci layout", _ok, CFG, False, "ok", ""),
    ("good docker-save layout", _ok, CFG, True, "ok", ""),
    ("good with /usr paths", _ok, _env(PATH="/opt/eq/bin:/usr/local/bin:/usr/bin"), False, "ok", ""),
    ("good with two layers above", lambda b: b + [{"opt/a": b"a"}, {"opt/b": b"b"}], CFG, False, "ok", ""),
    ("root user", _ok, _config(User="0"), False, "FAIL", "is not unprivileged"),
    ("empty user", _ok, _config(User=""), False, "FAIL", "is not unprivileged"),
    ("user root:root", _ok, _config(User="root:root"), False, "FAIL", "is not unprivileged"),
    ("user 0:0", _ok, _config(User="0:0"), False, "FAIL", "is not unprivileged"),
    ("exposed port", _ok, _config(ExposedPorts={"80/tcp": {}}), False, "FAIL", "EXPOSEd port"),
    ("volume", _ok, _config(Volumes={"/v": {}}), False, "FAIL", "VOLUME"),
    ("entrypoint", _ok, _config(Entrypoint=["/bin/x"]), False, "FAIL", "ENTRYPOINT"),
    ("healthcheck", _ok, _config(Healthcheck={"Test": ["CMD", "true"]}), False, "FAIL", "HEALTHCHECK"),
    ("token in env", _ok, _env(PATH="/opt/eq/bin", API_TOKEN="x"), False, "FAIL", "secret-like variable name"),
    ("anthropic in env", _ok, _env(PATH="/opt/eq/bin", ANTHROPIC_FOO="x"), False, "FAIL", "secret-like variable name"),
    ("PATH leaves /opt and /usr", _ok, _env(PATH="/opt/eq/bin:/bin"), False, "FAIL", "PATH leaves /opt and /usr"),
    ("PATH prefix trick", _ok, _env(PATH="/optx/bin"), False, "FAIL", "PATH leaves /opt and /usr"),
    ("PATH odd characters", _ok, _env(PATH="/opt/eq/bin:/opt/x y"), False, "FAIL", "odd characters in PATH"),
    ("base layers swapped", lambda b: [b[1], b[0], {"opt/eq/x": b"x"}], CFG, False, "FAIL", "the bottom 2 layers are not the pinned distroless base's"),
    ("a base layer replaced", lambda b: [b[0], {"etc/evil": b"e"}, {"opt/eq/x": b"x"}], CFG, False, "FAIL",
     "the bottom 2 layers are not the pinned distroless base's"),
    ("a base layer missing", lambda b: [b[0], {"opt/eq/x": b"x"}], CFG, False, "FAIL", "the bottom 2 layers are not the pinned distroless base's"),
    ("a foreign base", lambda b: [{"usr/bin/other": b"o"}, {"etc/other": b"o"}, {"opt/eq/x": b"x"}], CFG, False, "FAIL",
     "the bottom 2 layers are not the pinned distroless base's"),
    ("no layer above the base", lambda b: list(b), CFG, False, "FAIL", "no layer above the base"),
    ("no layer at all", lambda b: [], CFG, True, "FAIL", "the layer list is unreadable"),
]


@pytest.fixture
def inspect_world(eqc_env, tmp_path):
    lib = tmp_path / "eq-container-i"
    shutil.copytree(EQC_LIB, lib, ignore=shutil.ignore_patterns(".state", "__pycache__"))
    fill_bash_pins(lib)
    base = _crafted_base(lib)
    saves = tmp_path / "saves"
    saves.mkdir()

    class World:
        pass
    w = World()
    w.env, w.lib, w.base, w.saves = eqc_env, lib, base, saves

    def put(image, layers, cfg=None, docker=False):
        path = saves / (san(EQC_TAGS[image]) + ".tar")
        (save_archive if docker else oci_archive)(path, layers, cfg or CFG)
    w.put = put

    def inspect(*images, mode="--inspect"):
        return eqc_env.run("verify-tools.sh", "--select", ",".join(images), mode, lib=lib, EQ_FAKE_CONTAINER_SAVE_DIR=saves)
    w.inspect = inspect
    return w


def _rows3(out: str, kind: str) -> dict:
    r"""KIND NAME STATUS REASON rows; [ \t] (never \s, which spans the newline after a row with an empty reason)."""
    return {m.group(1): (m.group(2), m.group(3)) for m in re.finditer(r"^%s (\S+)[ \t]+(\S+)[ \t]*(.*)$" % kind, out, re.M)}


def _chunks(seq, n=3):
    return [seq[i:i + n] for i in range(0, len(seq), n)]


@pytest.mark.parametrize("group", _chunks(INSPECT_CASES), ids=lambda g: "+".join(c[0].replace(" ", "-") for c in g)[:60])
def test_inspect_checks_the_config_and_the_layers(inspect_world, group):
    """Three cases per run (each needs a manifest check and a saved image): good images pass, every fault is a FAIL row naming
    its reason, and the exit code is 11 exactly when a row failed."""
    w = inspect_world
    imgs = IMGS[:len(group)]
    for img, (_, layers_of, cfg, docker, _, _) in zip(imgs, group):
        w.put(img, layers_of(w.base), cfg, docker)
    p = w.inspect(*imgs)
    rows = _rows3(p.stdout, "INSPECT")
    assert set(rows) == set(imgs), (p.stdout, p.stderr)
    for img, (name, _, _, _, status, why) in zip(imgs, group):
        assert rows[img][0] == status and why in rows[img][1], (name, p.stdout)
    assert p.returncode == (0 if all(c[4] == "ok" for c in group) else 11), p.stdout
    assert ("TOOLS: inspect OK" in p.stdout) == (p.returncode == 0)


@pytest.mark.parametrize("n, ok", [(3, True), (4, False)])
def test_inspect_a_scratch_image_has_at_most_three_layers(inspect_world, n, ok):
    inspect_world.put("tc-go", [{"opt/l%d" % i: b"x"} for i in range(n)], _env(PATH="/opt/go/bin"))
    p = inspect_world.inspect("tc-go")
    assert (p.returncode == 0) is ok, p.stdout
    if not ok:
        assert "4 layers on a scratch image (want at most 3)" in p.stdout


def test_inspect_an_image_that_cannot_be_saved(inspect_world):
    p = inspect_world.inspect("min-py")
    assert p.returncode == 11 and _rows3(p.stdout, "INSPECT")["min-py"][0] == "MISSING", p.stdout


# ---- --images and --deep
def _tool_files(lib: Path, image: str) -> tuple:
    m = tomllib.loads((lib / "TOOLS.toml").read_text())
    tools = {t["name"]: t for t in m["tool"]}
    img = next(i for i in m["image"] if i["name"] == image)
    files, rows = {}, []
    for tn in img["tools"]:
        t = tools[tn]
        for f in t["files"]:
            data = ("tool %s %s" % (tn, f)).encode()
            files[f.lstrip("/")] = data
            rows.append([tn, t["version"], t["sha256"], f, hashlib.sha256(data).hexdigest()])
    return files, rows


def _lock(rows) -> bytes:
    return "".join("\t".join(r) + "\n" for r in rows).encode()


def _bex(base_members) -> bytes:
    return "".join("%s  /%s\n" % (hashlib.sha256(d).hexdigest(), n) for m in base_members for n, d in m.items()).encode()


@pytest.fixture
def images_world(inspect_world, tmp_path):
    w = inspect_world
    w.pylog = tmp_path / "py.log"
    shim = w.env.shims / "python3"
    shim.write_text('#!/bin/bash\necho "$*" >> "$PYLOG"\nexec "%s" "$@"\n' % sys.executable)
    shim.chmod(0o755)

    def build(image, files_edit=None, lock_edit=None, label=None, bex="good"):
        w.env.record(image)
        files, rows = _tool_files(w.lib, image)
        if lock_edit:
            rows = lock_edit(rows)
        if files_edit:
            files_edit(files)
        top = dict(files)
        if rows is not None:
            top["opt/eq/TOOLS.lock"] = _lock(rows)
        if bex == "good":
            top["opt/eq/BASE_EXECUTABLES.txt"] = _bex(w.base)
        elif bex is not None:
            top["opt/eq/BASE_EXECUTABLES.txt"] = bex
        cfg = json.loads(json.dumps(CFG))
        cfg["config"]["Labels"] = {"eq.tools.sha256": label or _tools_hash(w.lib, image)}
        w.put(image, w.base + [top], cfg)
    w.build = build

    def run(*images, flags=(), **extra):
        return w.env.run("verify-tools.sh", "--select", ",".join(images), "--images", *flags, lib=w.lib,
                         EQ_FAKE_CONTAINER_SAVE_DIR=w.saves, PYLOG=w.pylog, **extra)
    w.run = run
    return w


def test_images_and_deep_pass_a_consistent_image_with_one_hash_pass(images_world):
    w = images_world
    w.build("min-py")
    p = w.run("min-py")
    assert p.returncode == 0 and _rows3(p.stdout, "IMAGE")["min-py"][0] == "ok" and "TOOLS: images OK" in p.stdout, (p.stdout, p.stderr)
    p = w.run("min-py", flags=("--deep",))
    assert p.returncode == 0 and _rows3(p.stdout, "IMAGE")["min-py"][0] == "ok", (p.stdout, p.stderr)
    calls = w.pylog.read_text().splitlines()
    assert len([c for c in calls if " oci-sha256 " in c]) == 1, calls                    # tool files and base executables in ONE call
    assert len([c for c in w.env.calls() if c[:2] == ["image", "save"]]) == 2             # one save per verify-tools run, not per read


def _drop_row(tool):
    return lambda rows: [r for r in rows if r[0] != tool]


def _alter(col, value, tool):
    def f(rows):
        return [(r[:col] + [value] + r[col + 1:]) if r[0] == tool else r for r in rows]
    return f


# (id, build kwargs, deep, expected status, text the row must hold); busybox is in all three core images
IMAGES_CASES = [
    ("a stale label", dict(label="9" * 64), False, "STALE", "label eq.tools.sha256"),
    ("no lock", dict(lock_edit=lambda rows: None), False, "LOCK", "no /opt/eq/TOOLS.lock"),
    ("a tool missing in the lock", dict(lock_edit=_drop_row("busybox")), False, "LOCK", "tool busybox is in the manifest but not in the lock"),
    ("a lock hash that differs", dict(lock_edit=_alter(2, "9" * 64, "busybox")), False, "LOCK", "tool busybox lock sha256"),
    ("a lock version that differs", dict(lock_edit=_alter(1, "9.9.9", "busybox")), False, "LOCK", "tool busybox version differs"),
    ("an undeclared tool in the lock", dict(lock_edit=lambda rows: rows + [["rustc", "1", "a" * 64, "/opt/eq/bin/rustc", "b" * 64]]),
     False, "UNDECLARED", "rustc"),
    ("a tool file changed (the lock alone does not see it)", dict(files_edit=lambda f: f.update({"opt/eq/bin/busybox": b"tampered"})),
     False, "ok", ""),
    ("a tool file changed, --deep", dict(files_edit=lambda f: f.update({"opt/eq/bin/busybox": b"tampered"})), True, "DEEP",
     "/opt/eq/bin/busybox"),
    ("a tool file missing, --deep", dict(files_edit=lambda f: f.pop("opt/eq/bin/busybox")), True, "DEEP", "/opt/eq/bin/busybox"),
    ("a base executable that differs, --deep", dict(bex=("%s  /usr/bin/base-tool\n" % ("9" * 64)).encode()), True, "DEEP", "/usr/bin/base-tool"),
    ("the base executables list missing, --deep", dict(bex=None), True, "DEEP", "no /opt/eq/BASE_EXECUTABLES.txt"),
    ("the base executables list missing, no --deep", dict(bex=None), False, "ok", ""),
]


@pytest.mark.parametrize("group", _chunks(IMAGES_CASES), ids=lambda g: "+".join(c[0].split(",")[0].replace(" ", "-") for c in g)[:60])
def test_images_and_deep_refuse_what_the_lock_the_label_and_the_files_contradict(images_world, group):
    w = images_world
    for deep in (False, True):
        cases = [(img, c) for img, c in zip(IMGS, group) if c[2] is deep]
        if not cases:
            continue
        for img, c in cases:
            w.build(img, **c[1])
        p = w.run(*[img for img, _ in cases], flags=("--deep",) if deep else ())
        rows = _rows3(p.stdout, "IMAGE")
        for img, c in cases:
            assert rows[img][0] == c[3] and c[4] in rows[img][1] + " " + p.stdout, (c[0], p.stdout)
        assert p.returncode == (0 if all(c[3] == "ok" for _, c in cases) else 11), p.stdout


def test_deep_needs_images(eqc_env):
    p = eqc_env.run("verify-tools.sh", "--deep", "--manifest")
    assert p.returncode == 2 and "--deep needs --images" in p.stderr


@pytest.mark.parametrize("how", ["digest", "no record"])
def test_images_the_record_and_the_present_digest_must_match(images_world, how):
    w = images_world
    w.build("min-py")
    if how == "no record":
        (w.env.state / "images" / "min-py.env").unlink()
        p = w.run("min-py")
    else:
        p = w.run("min-py", EQ_FAKE_CONTAINER_DIGEST=DIGEST_B)
    assert p.returncode == 11 and _rows3(p.stdout, "IMAGE")["min-py"][0] in ("MISSING", "MISMATCH"), p.stdout


# ---------------------------------------------------------------------------------- build.sh against the fake CLI
@pytest.fixture
def build_lib(tmp_path):
    """A copy of the directory with the bash pins resolved (the repo ships them UNSET) and a verify-tools.sh that passes (the
    manifest gate has its own tests): build.sh then runs its whole build path against the fake CLI."""
    lib = tmp_path / "eq-container-b"
    shutil.copytree(EQC_LIB, lib, ignore=shutil.ignore_patterns(".state", "__pycache__"))
    fill_bash_pins(lib)
    (lib / "verify-tools.sh").write_text("#!/bin/bash\nexit 0\n")
    return lib


def _image_env(env) -> dict:
    return dict(ln.split("=", 1) for ln in (env.state / "image.env").read_text().splitlines() if "=" in ln)


def _record(env, name) -> dict:
    return dict(ln.split("=", 1) for ln in (env.state / "images" / (name + ".env")).read_text().splitlines() if "=" in ln)


def _builds(env) -> list:
    return [c for c in env.calls() if c and c[0] == "build"]


def _target(argv) -> str:
    return argv[argv.index("--target") + 1]


def _targets(env) -> list:
    return [_target(c) for c in _builds(env)]


def _flag(argv, f) -> str:
    return argv[argv.index(f) + 1]


def _pin(lib, key) -> str:
    return next(ln.split("=", 1)[1] for ln in (lib / "PINS").read_text().splitlines() if ln.startswith(key + "="))


def _tools_hash(lib, image) -> str:
    src = '. "%s/tools.sh"; tm_load "%s/TOOLS.toml" && tm_image_hash %s' % (lib, lib, image)
    return subprocess.run(["/bin/bash", "-c", src], capture_output=True, text=True, check=True, timeout=60).stdout.strip()


def _run(env, lib, *args, **extra):
    return env.run("build.sh", *args, lib=lib, **extra)


def test_default_build_is_the_core_profile(eqc_env, build_lib):
    p = _run(eqc_env, build_lib, "--yes")
    assert p.returncode == 0, (p.stdout[-2000:], p.stderr[-2000:])
    assert "profiles: core" in p.stdout
    assert _targets(eqc_env) == ["check-eq-min", "eq-min", "check-eq-py-min", "eq-py-min"]
    assert sorted(f.name for f in (eqc_env.state / "images").iterdir()) == ["min-both.env", "min-py.env"]
    ie = _image_env(eqc_env)
    assert ie["EQ_CONTAINER_PROFILES"] == "core" and ie["EQ_SELECT_LEAN"] == "min-both" and ie["EQ_SELECT_PY"] == "min-py"


def test_each_image_is_checked_first_then_built_from_the_same_cache(eqc_env, build_lib):
    p = _run(eqc_env, build_lib, "--yes", EQ_BUILD_MEMORY="3G", EQ_BUILD_CPUS="2")
    assert p.returncode == 0, (p.stdout[-2000:], p.stderr[-2000:])
    ops = [c for c in eqc_env.calls() if c[0] == "build" or c[:2] == ["image", "delete"]]
    assert [o[0] for o in ops] == ["build", "image", "build"] * 2, ops
    th = _tools_hash(build_lib, "min-both")
    for i, (name, tgt, tag) in enumerate((("min-both", "eq-min", EQC_TAGS["min-both"]), ("min-py", "eq-py-min", EQC_TAGS["min-py"]))):
        check, delete, final = ops[3 * i: 3 * i + 3]
        ctag = _flag(check, "-t")
        assert re.fullmatch(r"eq\.invalid/eq-check-%s:\d+" % name, ctag), ctag
        assert _target(check) == "check-" + tgt and _target(final) == tgt
        assert delete == ["image", "delete", ctag]                         # the check image's tag is deleted at once
        assert _flag(final, "-t") == tag and tag != ctag
        for b in (check, final):
            assert _flag(b, "-f") == "Dockerfile.minimal" and _flag(b, "--platform") == "linux/arm64" and b[-1] == "."
            assert _flag(b, "-m") == "3G" and _flag(b, "-c") == "2" and _flag(b, "--progress") == "plain"
            assert "--no-cache" not in b
        assert not any(a.startswith("eq.tools.sha256") for a in check)     # the check image carries no label
        assert any(a.startswith("eq.tools.sha256=") and len(a) == len("eq.tools.sha256=") + 64 for a in final)
    both_final = ops[2]
    assert "eq.tools.sha256=" + th in both_final
    assert "KEEP_EXTS=olean olean.private olean.server ir ir.sig" in ops[0] and "KEEP_EXTS=olean olean.private olean.server ir ir.sig" in ops[2]
    assert not any(a.startswith("KEEP_EXTS") for a in ops[3] + ops[5])       # min-py keeps no module files


def test_no_cache_and_keep_profile_reach_both_builds(eqc_env, build_lib):
    p = _run(eqc_env, build_lib, "--yes", "--no-cache", "--keep-profile", "slim", "--only", "min-both")
    assert p.returncode == 0, (p.stdout[-2000:], p.stderr[-2000:])
    b = _builds(eqc_env)
    assert [_target(x) for x in b] == ["check-eq-min", "eq-min"]
    assert all("KEEP_EXTS=olean ir ir.sig" in x for x in b)
    # --no-cache rebuilds every stage in the check build; the final build then takes those stages from the cache, so the image
    # recorded is the one that was checked
    assert "--no-cache" in b[0] and "--no-cache" not in b[1]
    assert _flag(b[1], "-t") == EQC_TAGS["min-both"] + "-slim"
    assert _record(eqc_env, "min-both")["EQ_BUILD_NOCACHE"] == "1"


def test_a_failing_check_stage_is_exit_12_with_no_record_and_no_final_build(eqc_env, build_lib):
    p = _run(eqc_env, build_lib, "--yes", EQ_FAKE_CONTAINER_FAIL_TARGETS="check-eq-min", EQ_FAKE_CONTAINER_FAIL_RC="7")
    assert p.returncode == 12, (p.returncode, p.stdout[-2000:], p.stderr[-2000:])
    assert "CHECK FAILED for min-both (stage check-eq-min, rc 7)" in p.stderr and "not built or recorded" in p.stderr
    assert "fake build of target check-eq-min failed" in p.stdout                      # the log's tail is shown
    assert _targets(eqc_env) == ["check-eq-min"]                                       # no final build, and min-py never starts
    ctag = _flag(_builds(eqc_env)[0], "-t")
    assert ["image", "delete", ctag] in eqc_env.calls()                                # the check tag is deleted even when it failed
    assert not (eqc_env.state / "images" / "min-both.env").exists() and not (eqc_env.state / "image.env").exists()
    assert (eqc_env.state / "build-min-both.log").exists()


def test_a_failing_check_stage_keeps_the_records_of_the_images_before_it(eqc_env, build_lib):
    p = _run(eqc_env, build_lib, "--set", "min", "--yes", EQ_FAKE_CONTAINER_FAIL_TARGETS="check-eq-py-min")
    assert p.returncode == 12 and "CHECK FAILED for min-py" in p.stderr, (p.returncode, p.stderr)
    assert _targets(eqc_env) == ["check-eq-lean-min", "eq-lean-min", "check-eq-py-min"]
    assert sorted(f.name for f in (eqc_env.state / "images").iterdir()) == ["min-lean.env"]


def test_a_failing_final_build_is_exit_12_with_no_record(eqc_env, build_lib):
    p = _run(eqc_env, build_lib, "--yes", EQ_FAKE_CONTAINER_FAIL_TARGETS="eq-min")
    assert p.returncode == 12 and "BUILD FAILED for min-both (rc 1)" in p.stderr and "CHECK FAILED" not in p.stderr, (p.returncode, p.stderr)
    assert _targets(eqc_env) == ["check-eq-min", "eq-min"]
    ctag = _flag(_builds(eqc_env)[0], "-t")
    assert ["image", "delete", ctag] in eqc_env.calls()
    assert not (eqc_env.state / "images" / "min-both.env").exists()


def test_the_record_names_the_base_and_no_longer_the_snapshot(eqc_env, build_lib):
    p = _run(eqc_env, build_lib, "--yes")
    assert p.returncode == 0, p.stderr
    for name in ("min-both", "min-py"):
        r = _record(eqc_env, name)
        assert r["EQ_BASE_REF"] == _pin(build_lib, "DISTROLESS_CC") and r["EQ_BASE_ARM64"] == _pin(build_lib, "DISTROLESS_CC_ARM64"), r
        assert "EQ_NOSNAP" not in r and not any("SNAP" in k for k in r), r
        assert r["EQ_IMAGE_TAG"] == EQC_TAGS[name] and r["EQ_IMAGE_DIGEST"] == DIGEST_A and r["EQ_BACKEND"] == "container"
        assert re.fullmatch(r"[0-9a-f]{64}", r["EQ_INPUTS_SHA256"]) and r["EQ_TOOLS_SHA256"] == _tools_hash(build_lib, name)
    assert _record(eqc_env, "min-both")["EQ_KEEP_EXTS"] == "olean olean.private olean.server ir ir.sig"
    assert _record(eqc_env, "min-py")["EQ_KEEP_EXTS"] == "" and _record(eqc_env, "min-py")["EQ_KEEP_SUFFIX"] == ""


def test_a_scratch_image_records_scratch_and_no_arm64_pin(eqc_env, build_lib):
    p = _run(eqc_env, build_lib, "--profiles", "go", "--yes")
    assert p.returncode == 0, (p.stdout[-2000:], p.stderr[-2000:])
    r = _record(eqc_env, "tc-go")
    assert r["EQ_BASE_REF"] == "scratch" and r["EQ_BASE_ARM64"] == "" and r["EQ_IMAGE_TAG"] == EQC_TAGS["tc-go"], r
    b = _builds(eqc_env)
    assert [_target(x) for x in b] == ["check-eq-go", "eq-go"] and all(_flag(x, "-f") == "Dockerfile.toolchains" for x in b)
    assert "eq.tools.sha256=" + _tools_hash(build_lib, "tc-go") in b[1]
    p = _run(eqc_env, build_lib, "--profiles", "node", "--yes")
    assert p.returncode == 0, p.stderr
    r = _record(eqc_env, "tc-node")
    assert r["EQ_BASE_REF"] == _pin(build_lib, "DISTROLESS_CC") and r["EQ_BASE_ARM64"] == _pin(build_lib, "DISTROLESS_CC_ARM64"), r


@pytest.mark.parametrize("flag", ["--set", "--profiles"])
def test_set_min_and_all_build_the_three_minimal_images_in_order(eqc_env, build_lib, flag):
    val = "min" if flag == "--set" else "candidates,core"
    p = _run(eqc_env, build_lib, flag, val, "--yes")
    assert p.returncode == 0, (p.stdout[-2000:], p.stderr[-2000:])
    want = ["check-eq-lean-min", "eq-lean-min", "check-eq-py-min", "eq-py-min", "check-eq-min", "eq-min"]
    assert _targets(eqc_env) == (want if flag == "--set" else
                                 ["check-eq-lean-min", "eq-lean-min", "check-eq-min", "eq-min", "check-eq-py-min", "eq-py-min"])
    assert sorted(f.name for f in (eqc_env.state / "images").iterdir()) == ["min-both.env", "min-lean.env", "min-py.env"]


def test_set_all_is_set_min(eqc_env, build_lib):
    p = _run(eqc_env, build_lib, "--set", "all", "--yes")
    assert p.returncode == 0 and _targets(eqc_env)[::2] == ["check-eq-lean-min", "check-eq-py-min", "check-eq-min"], p.stderr
    assert "profiles:" not in p.stdout and "EQ_CONTAINER_PROFILES" not in (eqc_env.state / "image.env").read_text()


@pytest.mark.parametrize("args, want", [
    (["--set", "full"], "--set full was removed"),
    (["--no-snapshot"], "--no-snapshot was removed"),
    (["--set", "full", "--check"], "--set full was removed"),
    (["--set", "full", "--uninstall", "--yes"], "--set full was removed"),
    (["--set", "huge"], "--set must be min or all"),
    (["--set", "min", "--profiles", "core"], "--set and --profiles exclude each other"),
    (["--profiles", "nosuch"], "unknown profile: nosuch"),
    (["--only", "nosuch"], "--only: unknown image nosuch"),
    (["--only", "full"], "--only: unknown image full"),
    (["--keep-profile", "bogus"], "--keep-profile must be conservative, noprivate or slim"),
    (["--write-pin"], "--write-pin works only with --resolve-tools"),
    (["--bogus"], "unknown argument: --bogus"),
    (["--set"], "--set needs a value"),
])
def test_build_usage_errors_stop_before_the_cli(eqc_env, build_lib, args, want):
    p = _run(eqc_env, build_lib, *args)
    assert p.returncode == 2 and want in p.stderr, (p.returncode, p.stderr)
    assert "snapshot" not in p.stderr or "--no-snapshot" in p.stderr
    assert eqc_env.calls() == []


def test_the_full_build_path_is_gone(eqc_env, build_lib):
    """No flag combination builds the Debian image: `full` is no image name, no target and has no record."""
    p = eqc_env.sh('echo "$EQ_IMAGE_NAMES|$EQ_LEGACY_IMAGE_NAMES"; for n in full tc-rust tc-haskell min-both; do eq_img_default_tag $n; done')
    names, legacy = p.stdout.splitlines()[0].split("|")
    assert "full" not in names.split() and legacy.split() == ["full", "tc-rust", "tc-haskell"]
    assert p.stdout.splitlines()[1:] == [EQC_TAGS["full"], EQC_TAGS["tc-rust"], EQC_TAGS["tc-haskell"], EQC_TAGS["min-both"]]
    p = eqc_env.run("build.sh", "--only", "full", "--yes")
    assert p.returncode == 2 and "unknown image full" in p.stderr


@pytest.mark.parametrize("flag, value, want_pf, want_cp", [("--set", "min", "min-both", "min-py")])
def test_pick_prefers_python_images_and_this_runs_builds(eqc_env, build_lib, flag, value, want_pf, want_cp):
    """PF = min-both (Lean and the Python the PF oracle's `uv run` needs), min-lean only as the last resort; CP/CR = min-py,
    else min-both. An image this run built beats an older record."""
    def run(*a, **kw):
        p = _run(eqc_env, build_lib, *a, "--yes", **kw)
        assert p.returncode == 0, (a, p.stdout[-1500:], p.stderr[-1500:])
        return _image_env(eqc_env)

    def ref(name):
        return "%s@%s" % (EQC_TAGS[name], DIGEST_A)

    ie = run("--only", "min-lean")                                   # a: the only record is min-lean
    assert ie["EQ_SELECT_LEAN"] == "min-lean" and ie["EQ_CONTAINER_IMAGE_PF"] == ref("min-lean") and ie["EQ_IMAGE"] == ref("min-lean")
    assert not {"EQ_SELECT_PY", "EQ_CONTAINER_IMAGE_CP", "EQ_CONTAINER_IMAGE_CR"} & set(ie)
    ie = run("--only", "min-both")                                   # b: min-both serves PF and, with no min-py, CP/CR
    assert ie["EQ_SELECT_LEAN"] == "min-both" and ie["EQ_CONTAINER_IMAGE_PF"] == ref("min-both")
    assert ie["EQ_SELECT_PY"] == "min-both" and ie["EQ_CONTAINER_IMAGE_CP"] == ie["EQ_CONTAINER_IMAGE_CR"] == ref("min-both")
    ie = run("--only", "min-py")                                     # c: min-py takes CP/CR; PF stays on min-both's older record
    assert ie["EQ_SELECT_PY"] == "min-py" and ie["EQ_CONTAINER_IMAGE_CP"] == ie["EQ_CONTAINER_IMAGE_CR"] == ref("min-py")
    assert ie["EQ_SELECT_LEAN"] == "min-both" and ie["EQ_CONTAINER_IMAGE_PF"] == ref("min-both")
    ie = run("--only", "min-lean", "--force")                        # d: built in this run beats the older min-both record
    assert ie["EQ_SELECT_LEAN"] == "min-lean" and ie["EQ_CONTAINER_IMAGE_PF"] == ref("min-lean")
    assert ie["EQ_SELECT_PY"] == "min-py"
    ie = run("--set", "min")                                         # e: everything up to date: the preferred pair
    assert (ie["EQ_SELECT_LEAN"], ie["EQ_SELECT_PY"]) == (want_pf, want_cp)
    for n in ("min-lean", "min-py", "min-both"):
        up = n.upper().replace("-", "_")
        assert ie["EQ_%s_TAG" % up] == EQC_TAGS[n] and ie["EQ_%s_DIGEST" % up] == DIGEST_A
    ie = run("--set", "min", EQ_SELECT_LEAN="min-lean", EQ_SELECT_PY="min-both")
    assert ie["EQ_CONTAINER_IMAGE_PF"] == ref("min-lean") and ie["EQ_CONTAINER_IMAGE_CP"] == ref("min-both")


def test_a_second_run_skips_and_force_rebuilds(eqc_env, build_lib):
    assert _run(eqc_env, build_lib, "--yes").returncode == 0
    n = len(_builds(eqc_env))
    p = _run(eqc_env, build_lib, "--yes")
    assert p.returncode == 0 and "all images up to date" in p.stdout and len(_builds(eqc_env)) == n, p.stdout
    assert re.search(r"min-both\s.*\sskip\s", p.stdout) and re.search(r"min-py\s.*\sskip\s", p.stdout)
    p = _run(eqc_env, build_lib, "--yes", "--force")
    assert p.returncode == 0 and len(_builds(eqc_env)) == n + 4 and re.search(r"min-both\s.*\sbuild\s", p.stdout)


@pytest.mark.parametrize("profile, rel, rebuild", [
    ("core", "Dockerfile.minimal", True), ("core", "minimal/check.sh", True), ("core", "minimal/mkrootfs.sh", True),
    ("core", "minimal/untar.py", True), ("core", "minimal/lake-shim", True), ("core", "tc/build-bash.sh", True),
    ("core", "base/distroless-cc-debian13-nonroot.index.json", True), ("core", "base/distroless-cc-debian13-nonroot.arm64.manifest.json", True),
    ("core", "TOOLS.toml", True), ("core", "tools.sh", True), ("core", "project/lakefile.toml", True),
    ("core", "project/StackMathlib/Basic.lean", True),
    ("core", "Dockerfile.toolchains", False), ("core", "tc/fetch-tool.sh", False), ("core", "tc/mkrootfs-tc.sh", False),
    ("core", "README.md", False), ("core", "PROBE_NOTES_NOT_AN_INPUT", False),
    ("go", "Dockerfile.toolchains", True), ("go", "tc/fetch-tool.sh", True), ("go", "tc/mkrootfs-tc.sh", True),
    ("go", "base/distroless-cc-debian13-nonroot.index.json", True), ("go", "TOOLS.toml", True), ("go", "tools.sh", True),
    ("go", "Dockerfile.minimal", False), ("go", "minimal/check.sh", False),
])
def test_an_image_is_rebuilt_exactly_when_one_of_its_inputs_changed(eqc_env, build_lib, profile, rel, rebuild):
    assert _run(eqc_env, build_lib, "--profiles", profile, "--yes").returncode == 0
    n = len(_builds(eqc_env))
    f = build_lib / rel
    if f.exists():
        with open(f, "a") as fh:
            fh.write("\n# changed\n")
    p = _run(eqc_env, build_lib, "--profiles", profile, "--yes")
    assert p.returncode == 0, (p.stdout[-1500:], p.stderr[-1500:])
    assert (len(_builds(eqc_env)) > n) is rebuild, (rel, p.stdout)


def test_another_keep_profile_rebuilds_only_the_images_that_keep_module_files(eqc_env, build_lib):
    assert _run(eqc_env, build_lib, "--yes").returncode == 0
    n = len(_builds(eqc_env))
    p = _run(eqc_env, build_lib, "--yes", "--keep-profile", "noprivate")
    assert p.returncode == 0 and [_target(x) for x in _builds(eqc_env)[n:]] == ["check-eq-min", "eq-min"], p.stdout
    assert _record(eqc_env, "min-both")["EQ_KEEP_SUFFIX"] == "-noprivate"


def test_the_dry_run_plans_and_builds_nothing(eqc_env, build_lib):
    p = _run(eqc_env, build_lib, "--dry-run")
    assert p.returncode == 0 and "dry run: nothing built" in p.stdout, p.stderr
    assert re.search(r"min-both\s+%s\s+build" % re.escape(EQC_TAGS["min-both"]), p.stdout) and _builds(eqc_env) == []
    assert not (eqc_env.state / "images").exists()


def test_building_without_yes_and_without_a_terminal_refuses(eqc_env, build_lib):
    p = _run(eqc_env, build_lib)
    assert p.returncode == 2 and "refusing to start a long build non-interactively without --yes" in p.stderr and _builds(eqc_env) == []


def test_build_without_the_container_is_exit_10(eqc_env, build_lib):
    p = _run(eqc_env, build_lib, "--yes", EQ_FAKE_CONTAINER_DOWN=1)
    assert p.returncode == 10 and "container unavailable" in p.stdout and _builds(eqc_env) == []


def test_keep_profile_build_replaces_the_one_record(eqc_env, build_lib):
    """--keep-profile slim: the image's one record holds the -slim tag, so image.env, --check and verify-tools.sh all
    see the image that was built (it wrote images/min-both-slim.env, which nothing reads)."""
    p = _run(eqc_env, build_lib, "--set", "min", "--yes", "--keep-profile", "slim")
    assert p.returncode == 0, (p.stdout[-2000:], p.stderr[-2000:])
    ie = _image_env(eqc_env)
    assert ie.get("EQ_CONTAINER_IMAGE_PF", "").startswith(EQC_TAGS["min-both"] + "-slim@"), ie
    assert sorted(f.name for f in (eqc_env.state / "images").iterdir()) == ["min-both.env", "min-lean.env", "min-py.env"]
    p = _run(eqc_env, build_lib, "--set", "min", "--check")
    assert p.returncode == 0 and "CHECK: OK" in p.stdout, p.stdout


# ---- --check
def _rows(out: str) -> dict:
    return {m.group(1): m.group(2) for m in re.finditer(r"^CHECK (\S+)\s+(\S+) ", out, re.M)}


def test_check_after_a_build_is_ok_and_defaults_to_core(eqc_env, build_lib):
    assert _run(eqc_env, build_lib, "--set", "min", "--yes").returncode == 0
    p = _run(eqc_env, build_lib, "--check")
    assert p.returncode == 0 and "CHECK: OK" in p.stdout and _rows(p.stdout) == {"min-both": "ok", "min-py": "ok"}, p.stdout
    p = _run(eqc_env, build_lib, "--check", "--set", "min")
    assert p.returncode == 0 and set(_rows(p.stdout)) == {"min-lean", "min-py", "min-both"}


@pytest.mark.parametrize("how, status", [("stale", "STALE"), ("digest", "MISMATCH"), ("missing image", "MISSING"), ("no record", "MISSING")])
def test_check_reports_what_is_wrong(eqc_env, build_lib, how, status):
    assert _run(eqc_env, build_lib, "--yes").returncode == 0
    extra = {}
    if how == "stale":
        with open(build_lib / "minimal" / "check.sh", "a") as f:
            f.write("\n# changed\n")
    elif how == "digest":
        extra["EQ_FAKE_CONTAINER_DIGEST"] = DIGEST_B
    elif how == "missing image":
        extra["EQ_FAKE_CONTAINER_MISSING"] = EQC_TAGS["min-both"]
    else:
        (eqc_env.state / "images" / "min-both.env").unlink()
    p = _run(eqc_env, build_lib, "--check", **extra)
    assert p.returncode == 11 and "CHECK: NOT OK" in p.stdout, (p.returncode, p.stdout)
    assert _rows(p.stdout)["min-both"] == status, p.stdout


def test_check_without_the_container_is_exit_10(eqc_env, build_lib):
    p = _run(eqc_env, build_lib, "--check", EQ_FAKE_CONTAINER_DOWN=1)
    assert p.returncode == 10 and "CHECK: SKIP" in p.stdout


# ---- --uninstall
LEGACY = ("full", "tc-rust", "tc-haskell")


def _records(env) -> list:
    d = env.state / "images"
    return sorted(f.name for f in d.iterdir()) if d.exists() else []


def _deleted(env) -> list:
    return [c[2] for c in env.calls() if c[:2] == ["image", "delete"] and c[2].startswith("eq.invalid/eq-") and "check" not in c[2]]


@pytest.fixture
def installed(eqc_env, build_lib):
    assert _run(eqc_env, build_lib, "--set", "min", "--yes").returncode == 0
    for n in LEGACY:
        eqc_env.record(n)
    eqc_env.log.unlink()
    return eqc_env


def test_uninstall_set_all_also_removes_the_legacy_records(installed, build_lib):
    p = _run(installed, build_lib, "--uninstall", "--set", "all", "--yes")
    assert p.returncode == 0 and "UNINSTALL: done" in p.stdout, (p.stdout, p.stderr)
    assert _records(installed) == [] and not (installed.state / "image.env").exists()
    assert sorted(_deleted(installed)) == sorted(EQC_TAGS[n] for n in ("min-lean", "min-py", "min-both") + LEGACY)


@pytest.mark.parametrize("sel, gone", [(["--set", "min"], {"min-lean", "min-py", "min-both"}), (["--profiles", "core"], {"min-py", "min-both"}),
                                       (["--only", "min-py"], {"min-py"})])
def test_uninstall_without_set_all_leaves_the_legacy_records(installed, build_lib, sel, gone):
    p = _run(installed, build_lib, "--uninstall", *sel, "--yes")
    assert p.returncode == 0, (p.stdout, p.stderr)
    left = {"min-lean", "min-py", "min-both"} - gone
    assert _records(installed) == sorted(n + ".env" for n in left | set(LEGACY))
    assert sorted(_deleted(installed)) == sorted(EQC_TAGS[n] for n in gone)


def test_uninstall_removes_keep_profile_records_of_the_same_image_only(installed, build_lib):
    d = installed.state / "images"
    (d / "min-both-old.env").write_text("EQ_IMAGE_NAME=min-both\nEQ_IMAGE_TAG=eq.invalid/eq-min:old\nEQ_IMAGE_DIGEST=%s\n" % DIGEST_A)
    (d / "min-both-other.env").write_text("EQ_IMAGE_NAME=somebody-else\nEQ_IMAGE_TAG=eq.invalid/x:1\nEQ_IMAGE_DIGEST=%s\n" % DIGEST_A)
    p = _run(installed, build_lib, "--uninstall", "--only", "min-both", "--yes")
    assert p.returncode == 0 and "min-both-old.env" not in _records(installed) and "min-both-other.env" in _records(installed), p.stdout
    assert "eq.invalid/eq-min:old" in _deleted(installed)


def test_uninstall_needs_yes_without_a_terminal(installed, build_lib):
    before = _records(installed)
    p = _run(installed, build_lib, "--uninstall", "--set", "all")
    assert p.returncode == 2 and "refusing to remove images without --yes" in p.stderr
    assert _records(installed) == before and _deleted(installed) == []


def test_uninstall_dry_run_lists_every_tag_and_removes_nothing(installed, build_lib):
    before = _records(installed)
    p = _run(installed, build_lib, "--uninstall", "--set", "all", "--dry-run", "--yes")
    assert p.returncode == 0, p.stderr
    for n in ("min-lean", "min-py", "min-both") + LEGACY:
        assert "would: container image delete %s" % EQC_TAGS[n] in p.stdout, n
    assert _records(installed) == before and _deleted(installed) == [] and (installed.state / "image.env").exists()


def test_uninstall_a_record_whose_image_is_gone_is_still_dropped(installed, build_lib):
    p = _run(installed, build_lib, "--uninstall", "--set", "all", "--yes", EQ_FAKE_CONTAINER_MISSING=EQC_TAGS["full"])
    assert p.returncode == 0 and "not present: %s" % EQC_TAGS["full"] in p.stdout and _records(installed) == []


def test_uninstall_without_the_container_keeps_the_records(installed, build_lib):
    before = _records(installed)
    p = _run(installed, build_lib, "--uninstall", "--set", "all", "--yes", EQ_FAKE_CONTAINER_DOWN=1)
    assert p.returncode == 10 and "records kept" in p.stdout and _records(installed) == before


def test_the_driver_uninstalls_with_set_all(eqc_env, stub_lib, tmp_path):
    eqc_env.state.mkdir(parents=True)
    (eqc_env.state / "image.env").write_text("EQ_IMAGE=x\n")
    (eqc_env.state / "status.env").write_text("EQ_CONTAINER_STATUS=ok\n")
    p = eqc_env.run("eq-container.sh", "uninstall", "--yes", "--purge", lib=stub_lib, STUB_LOG=tmp_path / "stub")
    assert p.returncode == 0, (p.stdout, p.stderr)
    assert (tmp_path / "stub.build").read_text().splitlines() == ["--set all --uninstall --yes"]
    assert not eqc_env.state.exists()                                          # --purge: the state dir named eq-container goes
    p = eqc_env.run("eq-container.sh", "uninstall", "--dry-run", lib=stub_lib, STUB_LOG=tmp_path / "stub")
    assert p.returncode == 0 and (tmp_path / "stub.build").read_text().splitlines()[-1] == "--set all --uninstall --dry-run --yes"


# ---- usage strings, the install flow of --set min
def test_help_texts_name_min_and_all_and_no_full_flag(eqc_env):
    p = eqc_env.run("eq-container.sh", "--help")
    assert p.returncode == 0 and "[--set min | --profiles core,jvm|all]" in p.stdout and "--set min | full" not in p.stdout
    assert "default: the profile core" in p.stdout and "FROM the pinned distroless cc image or FROM scratch" in p.stdout
    p = eqc_env.run("build.sh", "--help")
    assert p.returncode == 0 and "--set min|all" in p.stdout and "--set min|full" not in p.stdout and "min|all" in p.stdout
    assert "--resolve-tools [--write-pin]" in p.stdout and "default: core" in p.stdout
    assert eqc_env.calls() == []


def test_install_with_set_min_passes_it_to_build_and_skips_the_tools_verification(eqc_env, stub_lib, tmp_path):
    p = eqc_env.run("eq-container.sh", "install", "--yes", "--set", "min", lib=stub_lib, STUB_LOG=tmp_path / "stub")
    assert p.returncode == 0, (p.stdout, p.stderr)
    assert (tmp_path / "stub.build").read_text().splitlines() == ["--set min --yes"]
    assert eqc_env.status("EQ_CONTAINER_STATUS_SET") == "min" and eqc_env.status("EQ_CONTAINER_STATUS_PROFILES") is None
    assert [s.split()[0] for s in _stages(tmp_path)] == ["probe.sh"], _stages(tmp_path)
    assert eqc_env.status("EQ_CONTAINER_STATUS_VERIFIED").count("@") == 2


def test_install_with_profiles_core_and_node_verifies_and_smokes_the_extension_image(eqc_env, stub_lib, tmp_path):
    p = eqc_env.run("eq-container.sh", "install", "--yes", "--profiles", "node", lib=stub_lib, STUB_LOG=tmp_path / "stub")
    assert p.returncode == 0, (p.stdout, p.stderr)
    assert (tmp_path / "stub.build").read_text().splitlines() == ["--profiles core,node --yes"]
    st = _stages(tmp_path)
    assert st[0].startswith("verify-tools.sh --images --deep --inspect --profiles core,node")
    assert st[1] == "verify-tools.sh --smoke --select tc-node" and st[-1].startswith("probe.sh")


def test_fake_cli_refuses_options_the_stack_does_not_use(eqc_env):
    """The fake accepts only `container run --help` (1.5.0) options the stack uses: an unexpected one fails the test run
    instead of passing silently."""
    p = eqc_env.sh('eqc run --privileged %s /usr/bin/true; echo "rc=$?"' % MIN)
    assert "rc=2" in p.stdout and "not one the stack uses" in p.stderr


def test_fake_cli_copies_are_identical():
    """The harness keeps a byte-identical copy (harness/tests/fake_container) outside this repo; here only the one copy
    exists, and it is executable."""
    f = Path(__file__).resolve().parent / "fake-container" / "container"
    assert os.access(f, os.X_OK) and f.read_bytes().startswith(b"#!/bin/bash\n")
    assert b"[unverified]" in f.read_bytes()


def test_probe_requires_and_emits_the_distroless_rows():
    """probe.sh fails a probe that does not report no_debug_shell, no_package_manager and network_probe_control (a truncated
    probe_inner.sh is never a pass), and probe_inner.sh emits each of them with both a PASS and a FAIL branch."""
    probe = (EQC_LIB / "probe.sh").read_text()
    need = re.search(r"for need in (.*?); do", probe, re.S).group(1).replace("\\\n", " ").split()
    inner = (EQC_LIB / "probe_inner.sh").read_text()
    for row in ("no_debug_shell", "no_package_manager", "network_probe_control"):
        assert row in need, row
        assert re.search(r"\bt %s PASS\b" % row, inner) and re.search(r"\bt %s FAIL\b" % row, inner), row

