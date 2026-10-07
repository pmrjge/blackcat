"""lib/eq-docker/eq-docker.sh, the installer-facing driver of the equilibrium isolation images: docker missing, Homebrew missing,
daemon down, consent (a prompt answer or --install-docker; --yes alone is NOT consent), the Homebrew install paths and their
failure, Docker.app already present (no cask install), dry-run creating nothing, an idempotent build, --check, uninstall and
--purge, an unresolved pin (exit 13), and spike/probe skipped while the verified image IDs are unchanged.

Hermetic: `docker` and `brew` are PATH shims (tests/fake-docker/docker, tests/fake-brew/brew); HOME, TMPDIR and the state directory
are temp directories; no real Docker.app, Homebrew or daemon is looked at (EQ_DOCKER_APP_DIRS / EQ_DOCKER_BIN_DIRS / EQ_BREW_DIRS
point nowhere); a terminal is faked for `test -t` (tests/conftest.py). Nothing is built, pulled or installed for real.

Run: uv run --with pytest pytest -q -p no:cacheprovider tests/test_eq_docker.py
"""
import re
import shutil
import subprocess

import pytest

from conftest import BASH, LIB

SET = ("--set", "full")          # the full set needs no BUSYBOX_SHA256 pin; the min set is covered by the pin test


def install(env, *args, **kw):
    return env.run("eq-docker.sh", "install", *SET, *args, **kw)


def count(env, prefix):
    return len([ln for ln in env.docker_log() if ln.startswith(prefix)])


def spike_probe_runs(env):
    return [a for a in env.runs() if any(re.match(r"eq-testrun-(spike|probe)", x) for x in a)]


# ------------------------------------------------------------------------------------------------ docker or brew missing
def test_docker_and_brew_missing_is_a_warning_and_a_skip(env):
    r = install(env, "--yes")
    assert r.returncode == 10, r.stdout + r.stderr
    assert "Homebrew is not available" in r.stderr and "never installs Homebrew" in r.stderr
    assert env.status() == "skipped"
    assert env.brew_log() == [] and env.builds() == []


def test_yes_alone_is_not_consent_to_install_docker(env):
    env.brew()
    r = install(env, "--yes")                       # no terminal, no --install-docker
    assert r.returncode == 10, r.stdout + r.stderr
    assert "no consent" in r.stderr and "--yes is not enough" in r.stderr
    assert env.brew_installs() == [] and env.status() == "skipped"


def test_consent_declined_on_the_terminal(env):
    env.brew()
    r = install(env, tty=True, input="n\n")
    assert r.returncode == 10 and "no consent" in r.stderr, r.stdout + r.stderr
    assert "brew install --cask docker-desktop" in r.stdout          # the offer was shown, with the licence/admin notes
    assert "UNVERIFIED" in r.stdout and "administrator" in r.stdout
    assert env.brew_installs() == []


def test_no_prompt_keeps_a_terminal_from_being_asked(env):
    env.brew()
    r = install(env, "--no-prompt", tty=True, input="y\n")
    assert r.returncode == 10 and env.brew_installs() == [], r.stdout + r.stderr


def test_consent_given_on_the_terminal_installs_the_cask_and_stops_until_docker_runs(env):
    env.brew()
    r = install(env, tty=True, input="y\n")
    assert r.returncode == 10, r.stdout + r.stderr
    assert env.brew_installs() == ["install --cask docker-desktop"], env.brew_log()
    assert "info --cask docker-desktop" in env.brew_log()
    assert "not running yet" in r.stderr and "open -a Docker" in r.stderr
    assert env.builds() == []                         # nothing is built until the daemon answers


def test_install_docker_flag_is_consent_without_a_terminal(env):
    env.brew()
    r = install(env, "--install-docker")
    assert r.returncode == 10, r.stdout + r.stderr
    assert env.brew_installs() == ["install --cask docker-desktop"]
    assert "Docker Desktop is free for personal use" in r.stdout and "UNVERIFIED" in r.stdout    # licence note, marked unverified


def test_install_docker_via_colima_installs_the_three_formulae(env):
    env.brew()
    r = install(env, "--install-docker", "--docker-via", "colima")
    assert r.returncode == 10, r.stdout + r.stderr
    assert env.brew_installs() == ["install colima docker docker-buildx"]
    assert "cliPluginsExtraDirs" in r.stdout and "colima start" in r.stderr


def test_brew_failure_is_a_skip_not_a_failed_install(env):
    env.brew()
    r = install(env, "--install-docker", FAKE_BREW_FAIL="1")
    assert r.returncode == 10, r.stdout + r.stderr
    assert "failed" in r.stderr and len(env.brew_installs()) == 1
    assert env.status() == "skipped" and env.builds() == []


def test_unknown_cask_name_is_a_skip_without_an_install(env):
    env.brew()
    r = install(env, "--install-docker", FAKE_BREW_UNKNOWN="docker-desktop")
    assert r.returncode == 10 and "does not know the cask docker-desktop" in r.stderr
    assert env.brew_installs() == []


def test_docker_app_present_means_no_cask_install(env):
    env.brew()
    app = env.apps / "Docker.app"
    app.mkdir()
    r = install(env, "--install-docker", EQ_DOCKER_APP_DIRS=app)   # /Applications/Docker.app exists outside brew
    assert r.returncode == 10, r.stdout + r.stderr
    assert "Docker Desktop is installed but its docker CLI was not found" in r.stderr
    assert env.brew_installs() == [] and env.brew_log() == []


def test_daemon_down_with_docker_app_says_start_docker_desktop(env):
    env.docker()
    app = env.apps / "Docker.app"
    app.mkdir()
    r = install(env, "--yes", FAKE_DOCKER_DOWN="1", EQ_DOCKER_APP_DIRS=app)
    assert r.returncode == 10 and "daemon is not reachable" in r.stderr and "open -a Docker" in r.stderr
    assert env.builds() == [] and env.status() == "skipped"


def test_daemon_down_without_an_app_is_still_only_a_skip(env):
    env.docker()
    r = install(env, "--yes", FAKE_DOCKER_DOWN="1")
    assert r.returncode == 10 and "daemon is not reachable" in r.stderr
    assert env.builds() == [] and env.status() == "skipped"


def test_wrong_architecture_is_a_skip(env):
    env.docker()
    r = install(env, "--yes", FAKE_DOCKER_ARCH="x86_64")
    assert r.returncode == 10 and "not aarch64" in r.stderr and env.builds() == []


# ------------------------------------------------------------------------------------------------------------- dry run
def test_dry_run_creates_nothing_and_builds_nothing(env):
    env.docker()
    r = install(env, "--dry-run", "--yes")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "dry run" in r.stdout
    assert not env.state.exists() and not env.state.parent.exists()
    assert env.builds() == []
    assert not [a for a in env.runs()]                # no container either


def test_dry_run_with_docker_missing_only_says_what_it_would_offer(env):
    env.brew()
    r = install(env, "--dry-run")
    assert r.returncode == 0 and "would offer to install Docker with Homebrew" in r.stdout, r.stdout + r.stderr
    assert env.brew_installs() == [] and not env.state.parent.exists()


# ------------------------------------------------------------------------------------- build, verify, idempotence, status
def test_install_builds_verifies_and_is_idempotent(env):
    env.docker()
    r1 = install(env, "--yes")
    assert r1.returncode == 0, r1.stdout + r1.stderr
    assert len(env.builds()) == 1 and env.status() == "ok"
    assert env.status("EQ_DOCKER_STATUS_SPIKE") == "PASS" and env.status("EQ_DOCKER_STATUS_PROBE") == "PASS"
    ids = env.status("EQ_DOCKER_STATUS_VERIFIED_IDS")
    assert re.fullmatch(r"sha256:[0-9a-f]{64},sha256:[0-9a-f]{64}", ids), ids
    first = len(spike_probe_runs(env))
    assert first >= 8                                   # spike and probe containers ran
    assert (env.state / "image.env").exists() and (env.state / "logs" / "probe.log").exists()
    # second run: the image is up to date, the IDs are unchanged, so neither spike nor probe runs again
    r2 = install(env, "--yes")
    assert r2.returncode == 0, r2.stdout + r2.stderr
    assert len(env.builds()) == 1, "an up-to-date image must not be rebuilt"
    assert "spike and probe skipped" in r2.stdout
    assert len(spike_probe_runs(env)) == first
    # --force-verify runs them again
    r3 = install(env, "--yes", "--force-verify")
    assert r3.returncode == 0 and len(spike_probe_runs(env)) > first


def test_a_rebuilt_image_with_a_new_id_is_verified_again(env):
    env.docker()
    assert install(env, "--yes").returncode == 0
    first = len(spike_probe_runs(env))
    (env.dstate / "images").write_text("")              # the image vanished from the daemon: the next install rebuilds it
    r = install(env, "--yes", FAKE_BUILD_SALT="rebuilt")
    assert r.returncode == 0, r.stdout + r.stderr
    assert len(env.builds()) == 2 and len(spike_probe_runs(env)) > first
    assert "spike and probe skipped" not in r.stdout


def test_state_files_are_private(env):
    env.docker()
    assert install(env, "--yes").returncode == 0
    assert (env.state.stat().st_mode & 0o777) == 0o700
    assert ((env.state / "status.env").stat().st_mode & 0o777) == 0o600


def test_pin_placeholder_is_exit_13_and_builds_nothing(env):
    env.docker()
    r = env.run("eq-docker.sh", "install", "--set", "min", "--yes")      # PINS: BUSYBOX_SHA256=UNSET until a maintainer fills it
    assert (LIB / "PINS").read_text().count("BUSYBOX_SHA256=UNSET") == 1, "this test needs the shipped placeholder"
    assert r.returncode == 13, r.stdout + r.stderr
    assert "placeholder" in r.stderr
    assert env.builds() == [] and env.status() == "failed" and env.status("EQ_DOCKER_STATUS_WHY") == "unresolved pin"


def test_build_failure_is_exit_12(env):
    env.docker()
    r = install(env, "--yes", FAKE_BUILD_FAIL="1")
    assert r.returncode == 12 and env.status() == "failed", r.stdout + r.stderr


def test_spike_failure_is_exit_14_and_never_ok(env):
    env.docker()
    r = install(env, "--yes", FAKE_LEAN_RC="1")
    assert r.returncode == 14 and env.status() == "failed" and env.status("EQ_DOCKER_STATUS_SPIKE") == "FAIL", r.stdout + r.stderr
    p = env.run("eq-docker.sh", "print-env")
    assert p.returncode == 1 and p.stdout == ""         # an unverified install publishes nothing


def test_probe_failure_is_exit_15(env):
    env.docker()
    r = install(env, "--yes", FAKE_NO_CAP="1")
    assert r.returncode == 15 and env.status("EQ_DOCKER_STATUS_PROBE") == "FAIL", r.stdout + r.stderr


def test_build_declined_on_the_terminal(env):
    env.docker()
    r = install(env, tty=True, input="n\n")
    assert r.returncode == 10 and "declined" in r.stderr and env.builds() == []


def test_build_accepted_on_the_terminal(env):
    env.docker()
    r = install(env, tty=True, input="y\n")
    assert r.returncode == 0 and len(env.builds()) == 1 and env.status() == "ok", r.stdout + r.stderr


def test_no_terminal_and_no_yes_does_not_build(env):
    env.docker()
    r = install(env)
    assert r.returncode == 10 and "re-run with --yes" in r.stderr and env.builds() == []


# ------------------------------------------------------------------------------------------ check, status, print-env
def test_check_ok_then_missing_then_docker_down(env):
    env.docker()
    assert install(env, "--yes").returncode == 0
    ok = env.run("eq-docker.sh", "check", *SET)
    assert ok.returncode == 0 and "CHECK: OK" in ok.stdout, ok.stdout + ok.stderr
    (env.dstate / "images").write_text("")
    gone = env.run("eq-docker.sh", "check", *SET)
    assert gone.returncode == 11 and "MISSING" in gone.stdout
    down = env.run("eq-docker.sh", "check", *SET, FAKE_DOCKER_DOWN="1")
    assert down.returncode == 10 and "SKIP" in down.stdout


def test_check_creates_nothing_on_a_machine_that_never_installed(env):
    env.docker()
    r = env.run("eq-docker.sh", "check", *SET)
    assert r.returncode == 11 and not env.state.parent.exists()


def test_status_and_print_env(env):
    env.docker()
    s0 = env.run("eq-docker.sh", "status")
    assert s0.returncode == 1 and "not installed" in s0.stdout
    assert env.run("eq-docker.sh", "print-env").returncode == 1
    assert install(env, "--yes").returncode == 0
    s1 = env.run("eq-docker.sh", "status")
    assert s1.returncode == 0 and "EQ_DOCKER_STATUS=ok" in s1.stdout
    p = env.run("eq-docker.sh", "print-env")
    assert p.returncode == 0
    lines = p.stdout.splitlines()
    assert lines[0] == "EQ_ISOLATION=docker" and re.fullmatch(r"EQ_IMAGE=sha256:[0-9a-f]{64}", lines[1]) and len(lines) == 2


# ------------------------------------------------------------------------------------------------ uninstall and --purge
def test_uninstall_needs_yes_without_a_terminal(env):
    env.docker()
    assert install(env, "--yes").returncode == 0
    r = env.run("eq-docker.sh", "uninstall")
    assert r.returncode == 2 and "refusing to remove images without --yes" in r.stderr
    assert (env.dstate / "images").read_text().strip() != ""


def test_uninstall_dry_run_removes_nothing(env):
    env.docker()
    assert install(env, "--yes").returncode == 0
    r = env.run("eq-docker.sh", "uninstall", "--dry-run", "--purge")
    assert r.returncode == 0 and "would" in r.stdout
    assert (env.state / "status.env").exists() and (env.dstate / "images").read_text().strip() != ""


def test_uninstall_purge_removes_images_records_and_the_state_dir(env):
    env.docker()
    assert install(env, "--yes").returncode == 0
    r = env.run("eq-docker.sh", "uninstall", "--yes", "--purge")
    assert r.returncode == 0, r.stdout + r.stderr
    assert (env.dstate / "images").read_text().strip() == ""
    assert not env.state.exists()


def test_uninstall_without_purge_keeps_logs_but_drops_the_published_image(env):
    env.docker()
    assert install(env, "--yes").returncode == 0
    r = env.run("eq-docker.sh", "uninstall", "--yes")
    assert r.returncode == 0
    assert not (env.state / "image.env").exists() and not (env.state / "status.env").exists()
    assert (env.state / "logs").is_dir()


def test_purge_only_removes_a_directory_named_eq_docker(env, tmp_path):
    env.docker()
    other = tmp_path / "somewhere"
    assert install(env, "--yes", EQ_STATE_DIR=other).returncode == 0
    r = env.run("eq-docker.sh", "uninstall", "--yes", "--purge", EQ_STATE_DIR=other)
    assert r.returncode == 0 and other.exists() and "only removes a directory named eq-docker" in r.stderr


def test_uninstall_with_docker_down_keeps_the_records(env):
    env.docker()
    assert install(env, "--yes").returncode == 0
    r = env.run("eq-docker.sh", "uninstall", "--yes", "--purge", FAKE_DOCKER_DOWN="1")
    assert r.returncode == 10 and (env.state / "status.env").exists()


# ----------------------------------------------------------------------------------------------------------- usage
@pytest.mark.parametrize("args", [("install", "--bogus"), ("frobnicate",), ("install", "--docker-via", "pip"), ("install", "--set", "tiny")])
def test_usage_errors_are_exit_2(env, args):
    r = env.run("eq-docker.sh", *args)
    assert r.returncode == 2, (args, r.stdout, r.stderr)


def test_help_lists_the_commands(env):
    r = env.run("eq-docker.sh", "--help")
    assert r.returncode == 0 and "install" in r.stdout and "uninstall" in r.stdout and "--install-docker" in r.stdout


# ------------------------------------------------------------------------------------------- static: syntax and lint
SCRIPTS = ["eq-docker.sh", "lib.sh", "build.sh", "build-minimal.sh", "spike.sh", "probe.sh", "probe_inner.sh", "reverify.sh",
           "compare-images.sh", "trace-reads.sh", "make-seccomp.sh", "minimal/mkrootfs.sh", "minimal/lake-shim",
           # the tools manifest, the compose wrapper, the extension-image scripts and the probe hooks
           "tools.sh", "verify-tools.sh", "eq-compose.sh", "tc/fetch-tool.sh", "tc/mkrootfs-tc.sh", "tc/entry-pg.sh",
           "tc/entry-mongo.sh", "tc/build-postgresql.sh", "tc/install-rust.sh", "tc/install-ghc.sh",
           "probe.d/20-tools-manifest.sh", "probe.d/30-internal-net.sh", "probe.d/50-tunnel.sh"]


@pytest.mark.parametrize("name", SCRIPTS)
def test_scripts_parse_under_bash(name):
    p = LIB / name
    if not p.exists():
        pytest.skip(f"{name} not in the directory under test")
    assert subprocess.run([BASH, "-n", str(p)], capture_output=True, text=True, check=False).returncode == 0


def test_shellcheck_is_clean_when_installed():
    sc = shutil.which("shellcheck")
    if not sc:
        pytest.skip("shellcheck not installed")
    files = [n for n in SCRIPTS if (LIB / n).exists()]
    # cwd = the script directory: shellcheck then follows `. "$here/lib.sh"`, so the variables lib.sh uses count as used
    r = subprocess.run([sc, "-x", *files], capture_output=True, text=True, check=False, cwd=str(LIB))
    assert r.returncode == 0, r.stdout


def test_no_script_pushes_or_uses_sudo():
    for n in SCRIPTS:
        p = LIB / n
        if not p.exists():
            continue
        code = "\n".join(ln for ln in p.read_text().splitlines() if not ln.lstrip().startswith("#"))
        assert not re.search(r"\bgit\s+push\b|--privileged", code), n
        # these only LIST tool names / paths to look for (inventory, absence checks of the sockets a container must not have)
        if n not in ("probe_inner.sh", "compare-images.sh", "probe.d/50-tunnel.sh"):
            assert not re.search(r"\bsudo\b", code), n
            assert "docker.sock" not in code, n


def test_pins_agree_with_the_dockerfiles():
    pins = dict(ln.split("=", 1) for ln in (LIB / "PINS").read_text().splitlines() if re.match(r"^[A-Z_0-9]+=", ln))
    keys = {
        "Dockerfile": ("BASE_IMAGE", "APT_SNAPSHOT", "LEAN_VERSION", "LEAN_SHA256", "UV_VERSION", "UV_SHA256", "PYTHON_VERSION",
                       "PBS_TAG", "PYTHON_SHA256", "MATHLIB_REV"),
        "Dockerfile.minimal": ("BASE_IMAGE", "APT_SNAPSHOT", "LEAN_VERSION", "LEAN_SHA256", "UV_VERSION", "UV_SHA256",
                               "PYTHON_VERSION", "PBS_TAG", "PYTHON_SHA256", "MATHLIB_REV"),
        # the extension images take every tool pin from TOOLS.toml; only the Debian base and its snapshot are PINS values
        "Dockerfile.toolchains": ("BASE_IMAGE", "APT_SNAPSHOT"),
    }
    for df, ks in keys.items():
        text = (LIB / df).read_text()
        for k in ks:
            m = re.search(rf"^ARG {k}=(.*)$", text, re.M)
            assert m and m.group(1) == pins[k], (df, k)
