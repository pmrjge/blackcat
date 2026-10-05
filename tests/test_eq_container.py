"""lib/eq-container with the fake `container` CLI (tests/fake-container/container; fixture eqc_env in conftest.py).

lib.sh: the argv of every `container run` (eq_run: no network, read-only root, no capabilities, an init, VM size, process
limit, unprivileged user, capped tmpfs /tmp and /work, only read-only mounts plus the /work source copy, a fixed KEY=VALUE
environment, the tag that runs), the digest check before the run (eq_require_image), the comma refusals, the watchdog, the
sweep and the services test. eq-container.sh: usage errors, the three skip paths (exit 10), status, print-env and the install
flow against stub build/verify/probe scripts (the real ones need the real CLI: probe.sh proves the isolation on the host).

What the fake assumes about the real CLI is listed, [unverified] where it is, in the fake's header.
Run: /Users/pmrj/.claude/venvs/tools/bin/python -m pytest -q tests/test_eq_container.py
"""
import os
import shutil
import stat
import time
from pathlib import Path

import pytest

from conftest import DIGEST_A, DIGEST_B, EQC_LIB, EQC_TAGS

MIN = EQC_TAGS["min-both"]


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


def test_work_root_with_a_comma_is_refused_at_source_time(eqc_env, tmp_path):
    p = eqc_env.sh("echo sourced", EQ_WORK_ROOT=tmp_path / "w,x")
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


@pytest.mark.parametrize("shape, ok", [("both", True), ("index", True), ("id", True), ("none", False),
                                       ("conflict", False)])
def test_digest_shapes_fail_closed(eqc_env, shape, ok):
    """[unverified] digest location: .configuration.index.digest and/or .id; both present must agree; neither = refused."""
    eqc_env.record("min-both")
    p = eqc_env.sh("eq_run eq-t-14 30 /usr/bin/true", EQ_FAKE_CONTAINER_INSPECT=shape)
    assert (p.returncode == 0) is ok, (shape, p.returncode, p.stderr)
    assert len(eqc_env.runs()) == (1 if ok else 0)


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
    (["install", "--set", "huge"], "--set must be min or full"),
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
case " $* " in *" --dry-run "*) echo " build min-both (stub)"; exit 0;; esac
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
