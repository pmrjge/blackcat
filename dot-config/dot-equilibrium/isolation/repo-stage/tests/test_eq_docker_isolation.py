"""Isolation-side proofs for lib/eq-docker (security review R1, findings F4 F5 F7 F9 F10 and the probe notes). Each test fails on
the scripts as they were before the fix (run the suite with EQ_DOCKER_LIB=<directory of the older scripts> to see it) and passes now.

Hermetic: a fake `docker` on PATH (tests/fake-docker/docker), see conftest.py. The in-container properties themselves (that a write
past the cap really gets ENOSPC, that /eqsrc/work is really read-only) can only be proved by a real container: `probe.sh`, a user
step in RUNBOOK_MINIMAL.md. What is proved here is that the scripts ask Docker for exactly these properties and that a missing or
failing answer from the container is a failure, never a pass.

Run: uv run --with pytest pytest -q -p no:cacheprovider tests/test_eq_docker_isolation.py
"""
import re
import stat

import pytest

from conftest import IMAGE_ID_A, IMAGE_ID_B, LIB, fixture_lib, vals

TAG = "eq-lean:4.34.1-arm64"
TAG_PY = "eq-py:test"
HARNESS_ENV_KEYS = {"LANG", "HOME", "TMPDIR", "UV_CACHE_DIR", "UV_OFFLINE", "UV_NO_CONFIG", "UV_PYTHON_DOWNLOADS"}  # CONTAINER_ENV

ONE_RUN = ('eq_need_docker; eq_require_image "$EQ_IMAGE_TAG"; W=$(mktemp -d "$EQ_WORK_ROOT/t.XXXXXX"); '
           'EQ_RUN_MOUNTS=(--mount "type=bind,source=$W,target=/work" --mount "type=bind,source=$W,target=/fixture,readonly"); '
           'EQ_RUN_EXTRA=(); EQ_RUN_STDIN=""; eq_run eq-x 30 echo hi')


def one_run(env):
    env.docker().record("full", TAG, IMAGE_ID_A)
    r = env.sh(ONE_RUN)
    assert r.returncode == 0, r.stderr
    runs = env.runs()
    assert len(runs) == 1
    return runs[0]


# ---------------------------------------------------------------------------------------------------------------- F5
def test_f5_log_options_bound_what_a_container_can_log(env):
    argv = one_run(env)
    opts = vals(argv, "--log-opt")
    assert "max-size=1m" in opts and "max-file=1" in opts, argv
    assert vals(argv, "--log-driver") == ["json-file"]


# ---------------------------------------------------------------------------------------------------------------- F4
def test_f4_work_is_a_capped_tmpfs_copy_never_a_writable_bind(env):
    argv = one_run(env)
    mounts = vals(argv, "--mount")
    # no bind mount lands on /work (the old design: a writable host directory without a size or inode cap)
    assert not [m for m in mounts if m.endswith("target=/work") or ",target=/work," in m], mounts
    # the host copy is read-only at /eqsrc/work
    assert any(m.endswith("target=/eqsrc/work,readonly") for m in mounts), mounts
    # /work is a tmpfs with a size cap and a sticky world-writable mode (the container user is not the host user)
    work = [t for t in vals(argv, "--tmpfs") if t.startswith("/work:")]
    assert len(work) == 1 and "size=1g" in work[0] and "mode=1777" in work[0] and "nosuid" in work[0], work
    # the container copies the source in first, then execs the real command
    image = argv.index(IMAGE_ID_A)               # run by the verified ID (F9), not by the tag
    assert argv[image + 1:image + 3] == ["/bin/sh", "-c"], argv[image:]
    assert argv[image + 3] == 'cp -R /eqsrc/work/. /work/ && exec "$@"'
    assert argv[image + 4:] == ["eq-run", "echo", "hi"]
    # the pristine fixture keeps its own read-only mount; nothing else is mounted
    assert any(m.endswith("target=/fixture,readonly") for m in mounts) and len(mounts) == 2


def test_f4_a_run_without_a_work_source_still_gets_the_tmpfs(env):
    env.docker().record("full", TAG, IMAGE_ID_A)
    r = env.sh('eq_need_docker; eq_require_image; EQ_RUN_MOUNTS=(); EQ_RUN_EXTRA=(); EQ_RUN_STDIN=""; eq_run eq-y 30 echo hi')
    assert r.returncode == 0, r.stderr
    argv = env.runs()[0]
    assert [t for t in vals(argv, "--tmpfs") if t.startswith("/work:")]
    assert "/bin/sh" not in argv[argv.index(IMAGE_ID_A):]      # no copy prefix without a source


def test_f4_work_cap_is_configurable_and_per_call(env):
    env.docker().record("full", TAG, IMAGE_ID_A)
    r = env.sh('eq_need_docker; eq_require_image; EQ_RUN_MOUNTS=(); EQ_RUN_EXTRA=(); EQ_RUN_STDIN=""; '
               'EQ_RUN_WORK_TMPFS="rw,size=8m,mode=1777" eq_run eq-z 30 true', EQ_WORK_TMPFS="rw,size=3g,mode=1777")
    assert r.returncode == 0, r.stderr
    assert "/work:rw,size=8m,mode=1777" in vals(env.runs()[0], "--tmpfs")
    r = env.sh('eq_need_docker; eq_require_image; EQ_RUN_MOUNTS=(); EQ_RUN_EXTRA=(); EQ_RUN_STDIN=""; eq_run eq-z 30 true',
               EQ_WORK_TMPFS="rw,size=3g,mode=1777")
    assert "/work:rw,size=3g,mode=1777" in vals(env.runs()[1], "--tmpfs")


@pytest.mark.parametrize("name", ["Dockerfile", "Dockerfile.minimal", "Dockerfile.distroless", "minimal/mkrootfs.sh"])
def test_f4_images_carry_the_eqsrc_work_mount_point(name):
    assert "/eqsrc/work" in (LIB / name).read_text(), f"{name} does not create /eqsrc/work"


def test_f4_every_candidate_image_has_a_bin_sh():
    # the copy prefix is `/bin/sh -c`: the full image has dash, every FROM-scratch rootfs links sh -> bash (distroless layers it)
    mk = (LIB / "minimal" / "mkrootfs.sh").read_text()
    assert 'ln -s bash "$R/usr/bin/sh"' in mk and 'ln -s usr/bin "$R/bin"' in mk
    assert "cp -R /eqsrc/work/. /work/" in mk, "mkrootfs.sh must smoke-test the copy prefix in the rootfs"
    assert "COPY --from=rootfs / /" in (LIB / "Dockerfile.distroless").read_text()


def test_f4_inner_probe_reports_the_work_rows():
    inner = (LIB / "probe_inner.sh").read_text()
    for row in ("work_is_tmpfs", "work_tmpfs_size", "eqsrc_mounted_ro", "bin_sh_present"):
        assert f"t {row} " in inner, row
    assert "|/eqsrc/work|" in inner or "/eqsrc/work|" in inner     # the only host-backed mounts allowed


# ---------------------------------------------------------------------------------------------------------------- F7
def test_f7_base_flags_carry_the_harness_set_and_nothing_from_the_host(env):
    env.docker().record("full", TAG, IMAGE_ID_A)
    r = env.sh(ONE_RUN, EQ_PROBE_SECRET_ENV="host-secret-value", ANTHROPIC_API_KEY="sk-host")
    assert r.returncode == 0, r.stderr
    argv = env.runs()[0]
    assert vals(argv, "--pull") == ["never"] and vals(argv, "--stop-timeout") == ["1"] and "--init" in argv
    assert vals(argv, "--network") == ["none"] and "--read-only" in argv and vals(argv, "--cap-drop") == ["ALL"]
    assert vals(argv, "--security-opt") == ["no-new-privileges"]
    keys = {e.split("=", 1)[0] for e in vals(argv, "-e")}
    assert keys == HARNESS_ENV_KEYS, keys
    assert "host-secret-value" not in "\x1f".join(argv) and "sk-host" not in "\x1f".join(argv)
    assert "--env-file" not in argv and "--privileged" not in argv


# ---------------------------------------------------------------------------------------------------------------- F9
def rc_of(env, snippet, **extra):
    r = env.sh(snippet + '; echo "rc=$?"', **extra)
    m = re.search(r"rc=(\d+)", r.stdout)
    return (int(m.group(1)) if m else r.returncode), r


def test_f9_an_image_without_a_build_record_is_refused(env):
    env.docker().seed_image(TAG, IMAGE_ID_A)               # present in the daemon, no record anywhere
    r = env.sh(f'eq_need_docker; eq_require_image {TAG}; echo "rc=$?"')
    assert r.returncode == 11 and "no build record" in r.stderr and "rc=" not in r.stdout, (r.returncode, r.stderr)


def test_f9_unrecorded_image_can_be_accepted_knowingly(env):
    env.docker().seed_image(TAG, IMAGE_ID_A)
    rc, r = rc_of(env, f"eq_need_docker; eq_require_image {TAG}", EQ_ALLOW_UNRECORDED="1")
    assert rc == 0, r.stderr


def test_f9_a_recorded_image_passes_by_tag_by_id_and_by_manifest_digest(env):
    digest_ref = "eq-lean@sha256:" + "c" * 64
    env.docker().record("full", TAG, IMAGE_ID_A, EQ_IMAGE_MANIFEST_DIGEST="sha256:" + "c" * 64)
    env.seed_image(digest_ref, IMAGE_ID_A)                  # the daemon resolves the digest reference to the same image
    for ref in (TAG, IMAGE_ID_A, digest_ref):
        rc, r = rc_of(env, f"eq_need_docker; eq_require_image '{ref}'")
        assert rc == 0, (ref, r.stderr)


def test_f9_a_retagged_image_is_refused(env):
    env.docker().record("full", TAG, IMAGE_ID_A)
    # the tag now points at another image: record says A, the daemon says B
    (env.dstate / "images").write_text(f"{TAG}\t{IMAGE_ID_B}\t1\n")
    r = env.sh(f'eq_need_docker; eq_require_image {TAG}; echo "rc=$?"')
    assert r.returncode == 11 and "rebuilt or retagged" in r.stderr


def test_f9_containers_start_from_the_verified_id_not_the_tag(env):
    argv = one_run(env)
    assert TAG not in argv and IMAGE_ID_A in argv


def test_f9_the_first_builds_legacy_record_is_still_read_in_the_source_layout(env, tmp_path):
    # ISO/.image.env (written before build.sh kept records) covers the tag it names, so the image built first stays usable
    import shutil
    src = tmp_path / "srcdir"
    shutil.copytree(LIB, src)
    (src / "LAYOUT").unlink(missing_ok=True)
    (src / ".image.env").write_text(f"EQ_IMAGE_TAG={TAG}\nEQ_IMAGE_ID={IMAGE_ID_A}\n")
    env.docker().seed_image(TAG, IMAGE_ID_A)
    r = env.sh(f'. "{src}/lib.sh"; eq_need_docker; eq_require_image {TAG}; echo "rc=$?"')
    assert "rc=0" in r.stdout, r.stderr


# --------------------------------------------------------------------------------------------------------------- F10
def test_f10_state_and_work_root_are_private(env):
    env.docker().record("full", TAG, IMAGE_ID_A)
    work = env.t / "wr"
    work.mkdir(mode=0o755)
    r = env.sh("true", EQ_WORK_ROOT=work)
    assert r.returncode == 0, r.stderr
    assert stat.S_IMODE(work.stat().st_mode) == 0o700
    assert stat.S_IMODE(env.state.stat().st_mode) == 0o700


def test_f10_work_root_may_not_be_home_or_root(env):
    r = env.sh("true", EQ_WORK_ROOT=env.home)
    assert r.returncode == 2 and "EQ_WORK_ROOT" in r.stderr


def test_f10_check_copies_are_not_world_writable(env):
    items = env.t / "items"
    (items / "PF" / "fixtures" / "PF-T1").mkdir(parents=True)
    (items / "PF" / "oracle" / "ref").mkdir(parents=True)
    (items / "PF" / "fixtures" / "PF-T1" / "Problem.lean").write_text("theorem t : True := trivial\n")
    (items / "PF" / "oracle" / "ref" / "PF-T1.lean").write_text("theorem t : True := trivial\n")
    (items / "PF" / "check_lean.sh").write_text("exit 0\n")
    (items / "PF" / "EqVerify.lean").write_text("-- v\n")
    env.docker().record("full", TAG, IMAGE_ID_A)
    r = env.sh('eq_need_docker; eq_require_image; EQ_RUN_IMAGE_REPORT=x; eq_pf_check PF-T1 ref oracle; echo "score=$PF_SCORE"',
               EQ_ITEMS=items)
    assert r.returncode == 0 and "score=1" in r.stdout, (r.stdout, r.stderr)
    modes = (env.dstate / "modes.log").read_text().splitlines()
    copy = [m for m in modes if m.endswith(" /eqsrc/work")]
    assert copy, modes
    assert all(m[8] != "w" and m[5] != "w" for m in copy), copy       # neither group nor others may write the copy


# ------------------------------------------------------------------------------------------------------- probe.sh rows
def probe(env, images=("a",), **extra):
    env.docker()
    env.record("a", TAG, IMAGE_ID_A)
    if len(images) > 1:
        env.record("b", TAG_PY, IMAGE_ID_B)
    return env.run("probe.sh", **extra)


def rows(out):
    d = {}
    for ln in out.splitlines():
        m = re.match(r"^(\S+)\s+(PASS|FAIL|INFO)\b\s*(.*)$", ln)
        if m:
            d[m.group(1)] = (m.group(2), m.group(3))
    return d


def test_probe_passes_and_reports_the_new_isolation_rows(env):
    p = probe(env, EQ_IMAGE=TAG, EQ_IMAGE_PY=TAG)
    assert p.returncode == 0, p.stdout + p.stderr
    r = rows(p.stdout)
    for name in ("work_size_capped", "in_mount_readonly", "work_write_stays_off_host", "work_is_tmpfs", "bin_sh_present"):
        assert r.get(name, ("missing",))[0] == "PASS", (name, r.get(name), p.stdout)
    assert "PROBE: PASS" in p.stdout
    assert "host_env_canary" not in p.stdout       # the hard-coded PASS row is gone: host_env_not_passed comes from the container
    assert r["host_env_not_passed"][0] == "PASS"


def test_probe_work_cap_row_fails_when_the_write_is_not_stopped(env):
    p = probe(env, EQ_IMAGE=TAG, EQ_IMAGE_PY=TAG, FAKE_NO_CAP="1")
    assert p.returncode == 1 and rows(p.stdout)["work_size_capped"][0] == "FAIL", p.stdout


def test_probe_in_mount_row_fails_when_in_is_writable(env):
    p = probe(env, EQ_IMAGE=TAG, EQ_IMAGE_PY=TAG, FAKE_IN_WRITABLE="1")
    assert p.returncode == 1 and rows(p.stdout)["in_mount_readonly"][0] == "FAIL", p.stdout


@pytest.mark.parametrize("missing", ["host_env_not_passed", "work_tmpfs_size", "bin_sh_present"])
def test_probe_fails_when_the_container_does_not_report_a_required_row(env, missing):
    p = probe(env, EQ_IMAGE=TAG, EQ_IMAGE_PY=TAG, FAKE_PROBE_OMIT=missing)
    assert p.returncode == 1 and rows(p.stdout)[missing][0] == "FAIL", p.stdout


def test_probe_fails_when_the_container_reports_a_failing_work_row(env):
    p = probe(env, EQ_IMAGE=TAG, EQ_IMAGE_PY=TAG, FAKE_PROBE_FAIL="work_is_tmpfs")
    assert p.returncode == 1 and rows(p.stdout)["work_is_tmpfs"][0] == "FAIL"


def test_probe_honours_EQ_IMAGE_and_EQ_IMAGE_PY(env):
    p = probe(env, images=("a", "b"), EQ_IMAGE=TAG, EQ_IMAGE_PY=TAG_PY)
    assert p.returncode == 0, p.stdout + p.stderr
    assert "== probe 1/2: image " + TAG in p.stdout and "== probe 2/2: image " + TAG_PY in p.stdout
    imgs = {i for a in env.runs() if "--name" in a for i in (IMAGE_ID_A, IMAGE_ID_B) if i in a}
    assert imgs == {IMAGE_ID_A, IMAGE_ID_B}
    assert (env.state / "results").is_dir() and len(list((env.state / "results").glob("probe.*.env"))) == 2


def test_probe_extra_images_are_probed_too(env):
    p = probe(env, images=("a", "b"), EQ_IMAGE=TAG, EQ_IMAGE_PY=TAG, EQ_PROBE_EXTRA_IMAGES=TAG_PY)
    assert "== probe 2/2: image " + TAG_PY in p.stdout and p.returncode == 0, p.stdout


def test_probe_every_container_has_the_hardened_flag_set(env):
    p = probe(env, EQ_IMAGE=TAG, EQ_IMAGE_PY=TAG)
    assert p.returncode == 0
    probe_runs = [a for a in env.runs() if any(x.startswith("eq-testrun-probe") for x in a)]
    assert len(probe_runs) >= 7, [a[:4] for a in probe_runs]
    for a in probe_runs:
        assert vals(a, "--pull") == ["never"] and "max-size=1m" in vals(a, "--log-opt"), a
        # the one container of probe.d/30-internal-net.sh adds a second --network (the throw-away --internal network), which
        # overrides `none`; every other container keeps `none` only
        want = ["none", "eq-probe-testrun"] if "eq-testrun-probe-intnet" in a else ["none"]
        assert vals(a, "--network") == want and "--read-only" in a and vals(a, "--cap-drop") == ["ALL"], a
        assert [t for t in vals(a, "--tmpfs") if t.startswith("/work:")], a
        assert not [m for m in vals(a, "--mount") if m.endswith("target=/work")], a


# ---------------------------------------------------------------------------------------------- spike.sh and compare-images.sh
def test_spike_builtin_runs_under_the_tmpfs_design(env):
    env.docker().record("a", TAG, IMAGE_ID_A)
    s = env.run("spike.sh", "--builtin", EQ_IMAGE=TAG, EQ_IMAGE_PY=TAG)
    assert s.returncode == 0 and "SPIKE: PASS" in s.stdout, s.stdout + s.stderr
    for a in env.runs():
        assert not [m for m in vals(a, "--mount") if m.endswith("target=/work")], a
        assert "max-size=1m" in vals(a, "--log-opt")


def test_spike_fails_when_the_mathlib_import_fails(env):
    env.docker().record("a", TAG, IMAGE_ID_A)
    s = env.run("spike.sh", "--builtin", EQ_IMAGE=TAG, EQ_IMAGE_PY=TAG, FAKE_LEAN_RC="1")
    assert s.returncode == 1 and "SPIKE: FAIL" in s.stdout


def test_compare_images_refuses_a_candidate_without_a_build_record(env):
    env.docker().record("full", TAG, IMAGE_ID_A)
    env.seed_image("eq-lean-min:manual", IMAGE_ID_B)           # in the daemon, never built by build.sh
    c = env.run("compare-images.sh", "--skip-cp", "--skip-inventory", "--cand", "manual=eq-lean-min:manual")
    assert c.returncode == 11 and "no build record" in c.stderr, (c.returncode, c.stdout, c.stderr)


# ------------------------------------------------------------------------------------------------ build.sh keep-profile records
def test_build_keep_profile_gets_its_own_record(env, tmp_path):
    # a copy whose busybox/bash/perl/jq pins are made up (the shipped TOOLS.toml and PINS keep placeholders until
    # `build.sh --resolve-tools --write-pin`; build.sh refuses to build the min set while a tool of it is a placeholder)
    work = fixture_lib(tmp_path)
    env.docker()
    import subprocess
    from conftest import BASH
    def build(*a):
        return subprocess.run([BASH, str(work / "build.sh"), "--set", "min", "--yes", *a], env=env.environ(), capture_output=True,
                              text=True, timeout=120, cwd=str(tmp_path), check=False)
    b1 = build()
    assert b1.returncode == 0, b1.stdout + b1.stderr
    b2 = build("--keep-profile", "noprivate")
    assert b2.returncode == 0, b2.stdout + b2.stderr
    recs = sorted(p.name for p in (env.state / "images").glob("*.env"))
    assert "min-lean.env" in recs and "min-lean-noprivate.env" in recs, recs
    default = (env.state / "images" / "min-lean.env").read_text()
    prof = (env.state / "images" / "min-lean-noprivate.env").read_text()
    assert "EQ_IMAGE_TAG=eq-lean-min:4.34.1-arm64\n" in default and "EQ_IMAGE_TAG=eq-lean-min:4.34.1-arm64-noprivate\n" in prof
    # an up-to-date run still re-selects which record the summary image.env publishes (EQ_SELECT_LEAN)
    b3 = subprocess.run([BASH, str(work / "build.sh"), "--set", "min", "--yes", "--keep-profile", "noprivate"],
                        env=env.environ(EQ_SELECT_LEAN="min-lean-noprivate"), capture_output=True, text=True, timeout=120,
                        cwd=str(tmp_path), check=False)
    assert b3.returncode == 0 and "up to date" in b3.stdout, b3.stdout + b3.stderr
    image_env = (env.state / "image.env").read_text()
    prof_id = re.search(r"^EQ_IMAGE_ID=(.*)$", prof, re.M).group(1)
    assert "EQ_SELECT_LEAN=min-lean-noprivate\n" in image_env and f"EQ_IMAGE={prof_id}\n" in image_env, image_env
    # b1 built min-lean, min-py, min-both; b2 built the two keep-profile images (min-py was up to date); b3 built nothing
    assert len(env.builds()) == 5
    # both tags are now covered by a record: spike/probe/reverify accept either
    for tag in ("eq-lean-min:4.34.1-arm64", "eq-lean-min:4.34.1-arm64-noprivate"):
        r = env.sh(f'eq_need_docker; eq_require_image {tag}; echo "rc=$?"')
        assert "rc=0" in r.stdout, (tag, r.stderr)
    # uninstall removes the profile record and its image as well
    u = subprocess.run([BASH, str(work / "build.sh"), "--set", "min", "--uninstall", "--yes"], env=env.environ(),
                       capture_output=True, text=True, timeout=120, cwd=str(tmp_path), check=False)
    assert u.returncode == 0, u.stdout + u.stderr
    assert not list((env.state / "images").glob("*.env"))
    assert "eq-lean-min:4.34.1-arm64-noprivate" not in (env.dstate / "images").read_text()
