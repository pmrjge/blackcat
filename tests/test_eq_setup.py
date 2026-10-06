"""lib/eq-container/setup.sh: the guided set-up of Apple `container` (install.sh --with-eq-container, step 10b). Consent
(typed on a terminal: all / step + yes / no; or one flag per step, --yes never), the CLI package's pins and checks (size,
sha256, signer; placeholder or malformed pins fail closed before any network), the one sudo call, the service start, the
build consent handed to the driver (--yes or --no-build), resumability, the records (cli.env, setup.env), the dry run, and
one seeded fault per security rule: each mutated copy of setup.sh must break the property its test checks.

Hermetic: a copy of lib/eq-container whose eq-container.sh is the stub (tests/fake-container/eq-container-stub.sh) and whose
setup.sh has its absolute-path constants rewritten to fakes (tests/fake-container/setup-tool as curl, pkgutil, installer,
sudo and sw_vers; tests/fake-container/container-cli as the CLI that the fake installer "installs"). PATH starts with a
directory of HIJACK programs (sudo, installer, pkgutil, curl, ...) that must never run. Every run is in a new session (no
controlling terminal); a terminal is simulated by replacing `test` (BASH_FUNC_test%%), as tests/test_install_devtools.py does.
No network, no sudo, no real container CLI.

Run: /Users/pmrj/.claude/venvs/tools/bin/python -m pytest -q tests/test_eq_setup.py
"""
import hashlib
import os
import re
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_install_devtools import TTY_FN, TTY_FN_NAME, shell_code  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
LIB = ROOT / "lib" / "eq-container"
FAKES = ROOT / "tests" / "fake-container"
SETUP = (LIB / "setup.sh").read_text()
STUB = (FAKES / "eq-container-stub.sh").read_text()
CONSTS = {"EQS_SUDO": "/usr/bin/sudo", "EQS_INSTALLER": "/usr/sbin/installer", "EQS_PKGUTIL": "/usr/sbin/pkgutil",
          "EQS_CURL": "/usr/bin/curl", "EQS_SW_VERS": "/usr/bin/sw_vers", "EQS_CLI": "/usr/local/bin/container"}
SIGNER = "Developer ID Installer: Fake Apple (FAKE000000)"
PKG = b"fake container installer package\n" * 64
PKG_SHA = hashlib.sha256(PKG).hexdigest()
URL = "https://github.com/apple/container/releases/download/1.5.0/container-1.5.0-installer-signed.pkg"
HIJACKED = ("sudo", "installer", "pkgutil", "curl", "sw_vers", "shasum", "uname", "mktemp", "cmp")
needs_shasum = pytest.mark.skipif(not os.path.exists("/usr/bin/shasum"), reason="needs /usr/bin/shasum")


def rewrite(text: str, fakes: Path, cli: Path) -> str:
    """setup.sh with its absolute-path constants pointing at the fakes (each line replaced exactly once)."""
    for k, v in CONSTS.items():
        line = "readonly %s=%s\n" % (k, v)
        assert text.count(line) == 1, k
        text = text.replace(line, "readonly %s=%s\n" % (k, cli if k == "EQS_CLI" else fakes / v.rsplit("/", 1)[1]))
    return text


def set_pins(lib: Path, **kv):
    p = lib / "PINS"
    t = p.read_text()
    for k, v in kv.items():
        t, n = re.subn(r"^%s=.*$" % k, "%s=%s" % (k, v), t, flags=re.M)
        assert n == 1, k
    p.write_text(t)


def mutate(old: str, new: str) -> str:
    assert SETUP.count(old) == 1, old
    return SETUP.replace(old, new)


class Env:
    def __init__(self, tmp: Path, text: str = None):
        self.t = Path(tmp)
        self.lib = self.t / "eq-container"
        shutil.copytree(LIB, self.lib, ignore=shutil.ignore_patterns(".state", "__pycache__"))
        (self.lib / "eq-container.sh").write_text(STUB)
        self.fakes = self.t / "fakes"
        self.fakes.mkdir()
        for n in ("curl", "pkgutil", "installer", "sudo", "sw_vers"):
            shutil.copyfile(FAKES / "setup-tool", self.fakes / n)
            (self.fakes / n).chmod(0o755)
        self.cli = self.t / "usr-local" / "bin" / "container"
        self.hijack = self.t / "hijack"
        self.hijack.mkdir()
        self.hlog = self.t / "hijack.log"
        for n in HIJACKED:
            (self.hijack / n).write_text('#!/bin/sh\necho "HIJACK %s $*" >> %s\nexit 1\n' % (n, self.hlog))
            (self.hijack / n).chmod(0o755)
        self.pkg = self.t / "served.pkg"
        self.pkg.write_bytes(PKG)
        set_pins(self.lib, CONTAINER_PKG_VERSION="1.5.0", CONTAINER_PKG_URL=URL, CONTAINER_PKG_SIZE=len(PKG),
                 CONTAINER_PKG_SHA256=PKG_SHA, CONTAINER_PKG_SIGNER=SIGNER, CONTAINER_MIN_MACOS="26")
        self.write_setup(text if text is not None else SETUP)
        self.state = self.t / "state"
        self.log = self.t / "setup.log"
        self.clog = self.t / "container.log"
        self.slog = self.t / "stub.log"
        self.svc = self.t / "svc.down"

    def write_setup(self, text: str):
        (self.lib / "setup.sh").write_text(rewrite(text, self.fakes, self.cli))

    def give_cli(self, version="1.5.0", up=True):
        """A CLI already at the package path (as a previous install left it)."""
        self.cli.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(FAKES / "container-cli", self.cli)
        self.cli.chmod(0o755)
        Path(str(self.cli) + ".version").write_text(version + "\n")
        if not up:
            self.svc.write_text("")

    def run(self, *args, tty=False, stdin="", drv=("install", "--profiles", "core"), cmd="run", **env):
        e = {"PATH": "%s:/usr/bin:/bin:/usr/sbin:/sbin" % self.hijack, "HOME": str(self.t / "home"),
             "TMPDIR": str(self.t), "EQ_STATE_DIR": str(self.state), "EQ_HOST_ARCH": "arm64", "LC_ALL": "C",
             "EQ_FAKE_SETUP_LOG": str(self.log), "EQ_FAKE_CONTAINER_LOG": str(self.clog),
             "EQ_FAKE_CONTAINER_CORE": str(FAKES / "container"), "EQ_FAKE_PKG": str(self.pkg),
             "EQ_FAKE_CLI_SRC": str(FAKES / "container-cli"), "EQ_FAKE_CLI_PATH": str(self.cli),
             "EQ_FAKE_SIGNER": SIGNER, "EQ_FAKE_SVC_DOWN": str(self.svc), "EQ_STUB_LOG": str(self.slog),
             "EQ_STUB_REAL_SKIPS": "1"}
        if tty:
            e[TTY_FN_NAME] = TTY_FN
        e.update({k: str(v) for k, v in env.items() if v is not None})
        argv = ["/bin/bash", str(self.lib / "setup.sh"), cmd, *args]
        if cmd == "run":
            argv += ["--", *drv]
        p = subprocess.run(argv, env=e, input=stdin, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                           timeout=120, start_new_session=True, check=False)
        assert not self.hlog.exists(), self.hlog.read_text()           # nothing from PATH ever ran
        return p

    def calls(self, name=None):
        if not self.log.exists():
            return []
        c = self.log.read_text().splitlines()
        return [x for x in c if name is None or x.split(" ", 1)[0] == name]

    def root_or_net(self):
        """Calls that download or need root: curl, sudo, installer (pkgutil and sw_vers only read)."""
        return [c for c in self.calls() if c.split(" ", 1)[0] in ("curl", "sudo", "installer")]

    def stub_calls(self):
        if not self.slog.exists():
            return []
        return [ln.split("\x1f", 1)[1] for ln in self.slog.read_text().splitlines()]

    def kv(self, name):
        p = self.state / name
        if not p.is_file():
            return {}
        return dict(ln.split("=", 1) for ln in p.read_text().splitlines() if "=" in ln)

    def cli_calls(self):
        if not self.clog.exists():
            return []
        return [tuple(ln.split("\x1f")) for ln in self.clog.read_text().splitlines()]


@pytest.fixture
def env(tmp_path):
    return Env(tmp_path)


# ------------------------------------------------------------------------------------------------- no consent: nothing runs
@needs_shasum
def test_no_terminal_and_no_flags_downloads_nothing_and_runs_no_sudo(env):
    p = env.run()
    out = p.stdout
    assert p.returncode == 10, out
    assert env.root_or_net() == [] and env.calls("pkgutil") == [], env.calls()
    assert "! not installed: Apple container 1.5.0 (no consent)" in out and "--install-container" in out
    assert "--setup-container" in out
    # the step was named in full before it was skipped
    assert out.index("Step: install Apple container 1.5.0") < out.index("! not installed")
    assert "/usr/bin/sudo /usr/sbin/installer -pkg <the checked file> -target /" in out
    # the driver still ran (it records why it skipped), without consent to build
    assert env.stub_calls() == ["install --profiles core --no-build --no-prompt"]
    assert env.kv("setup.env")["EQ_SETUP_STEP"] == "cli" and env.kv("setup.env")["EQ_SETUP_RC"] == "10"
    assert not env.cli.exists() and not (env.state / "cli.env").exists()


@needs_shasum
@pytest.mark.parametrize("answer", ["no\n", "\n", "", "yes\n", "y\n", "ALL please\n"])
def test_terminal_answer_other_than_all_or_step_is_no(env, answer):
    p = env.run(tty=True, stdin=answer)
    assert p.returncode == 10 and env.root_or_net() == [], (answer, p.stdout)
    assert "[all/step/no]" in p.stdout and "= no: the container steps are skipped" in p.stdout


@needs_shasum
@pytest.mark.parametrize("answer", ["step\ny\n", "step\nok\n", "step\n\n", "step\n"])
def test_step_mode_needs_a_typed_yes(env, answer):
    p = env.run(tty=True, stdin=answer)
    assert p.returncode == 10 and env.root_or_net() == [], (answer, p.stdout)
    assert "Type yes to run this step" in p.stdout


@needs_shasum
def test_no_prompt_never_asks_even_on_a_terminal(env):
    p = env.run("--no-prompt", tty=True, stdin="all\n")
    assert p.returncode == 10 and env.root_or_net() == [] and "[all/step/no]" not in p.stdout


# ------------------------------------------------------------------------------------------------- consent: the whole flow
def _assert_full_flow(env, p):
    out = p.stdout
    assert p.returncode == 0, out
    curls = env.calls("curl")
    assert len(curls) == 2, curls
    assert curls[0].endswith(URL) and "https://release-assets.githubusercontent.com/" in curls[1]
    for c in curls:
        a = c.split(" ")
        assert a[1] == "-q", c                                   # first: no ~/.curlrc
        for flag in ("--proto =https", "--proto-redir =https", "--max-redirs 0", "--fail", "--max-filesize %d" % len(PKG)):
            assert flag in c, (flag, c)
    progs = [c.split(" ", 2)[:2] for c in env.calls()]
    names = [x[0] for x in progs]
    # read-only sw_vers, two downloads, the signature, then sudo -> installer, then the receipt
    assert names == ["sw_vers", "curl", "curl", "pkgutil", "sudo", "installer", "pkgutil"], env.calls()
    sudo = env.calls("sudo")[0].split(" ")
    assert sudo[1] == str(env.fakes / "installer") and sudo[2] == "-pkg" and sudo[4:] == ["-target", "/"], sudo
    assert re.fullmatch(re.escape(str(env.state)) + r"/pkg\.\w+/container-1\.5\.0-installer-signed\.pkg", sudo[3]), sudo
    assert not list(env.state.glob("pkg.*"))                     # the private temp dir is gone
    # the consent text came before the first download
    assert out.index("Step: install Apple container 1.5.0") < out.index("FAKE curl")
    assert out.index("FAKE sudo") < out.index("5. %s --version: 1.5.0" % env.cli)
    assert out.index("Step: start the container service") < out.index("2. container system status: running")
    assert ("system", "start", "--enable-kernel-install") in env.cli_calls()
    calls = env.stub_calls()                       # step mode asks the driver first whether a build is due (read-only)
    assert calls[-1] == "install --profiles core --yes --no-prompt" and set(calls[:-1]) <= {"build-due --profiles core"}, calls
    cli = env.kv("cli.env")
    assert cli["EQ_CLI_INSTALLED_BY"] == "stack" and cli["EQ_CLI_VERSION"] == "1.5.0" and cli["EQ_CLI_PREVIOUS"] == "none"
    assert cli["EQ_CLI_PKG_SHA256"] == PKG_SHA and cli["EQ_CLI_PATH"] == str(env.cli) and cli["EQ_CLI_PIN"] == "1.5.0"
    for f in ("cli.env", "setup.env"):
        assert stat.S_IMODE((env.state / f).stat().st_mode) == 0o600
    assert stat.S_IMODE(env.state.stat().st_mode) == 0o700
    assert env.kv("setup.env")["EQ_SETUP_RC"] == "0"


@needs_shasum
@pytest.mark.parametrize("flags", [("--setup-container",),
                                   ("--install-container", "--start-container-service", "--build-container-images")])
def test_flags_give_consent_without_a_terminal(env, flags):
    env.svc.write_text("")                                         # a fresh install: the service is not running
    p = env.run(*flags)
    _assert_full_flow(env, p)
    assert "consent: given by flag" in p.stdout and "[all/step/no]" not in p.stdout


@needs_shasum
def test_terminal_all(env):
    env.svc.write_text("")
    p = env.run(tty=True, stdin="all\n")
    _assert_full_flow(env, p)
    out = p.stdout
    assert out.index("these steps are needed (nothing has run yet)") < out.index("[all/step/no]") < out.index("FAKE curl")
    for step in ("1. install Apple container 1.5.0", "2. start the container service", "3. build the isolation images"):
        assert step in out
    assert out.count("consent: you answered all") == 3


@needs_shasum
def test_terminal_step_by_step(env):
    env.svc.write_text("")
    p = env.run(tty=True, stdin="step\nyes\nyes\nyes\n", EQ_STUB_BUILD_DUE=0)
    _assert_full_flow(env, p)
    assert p.stdout.count("Type yes to run this step") == 3


@needs_shasum
def test_step_mode_yes_then_no_stops_before_the_service(env):
    env.svc.write_text("")
    p = env.run(tty=True, stdin="step\nyes\nno\n")
    assert p.returncode == 10, p.stdout
    assert env.calls("sudo") and ("system", "start", "--enable-kernel-install") not in env.cli_calls()
    assert "! not started: the container service (no consent)" in p.stdout
    assert env.stub_calls() == ["install --profiles core --no-build --no-prompt"]
    assert env.kv("setup.env")["EQ_SETUP_STEP"] == "service"


# ------------------------------------------------------------------------------------------------- already done: resumable
@needs_shasum
def test_everything_in_place_asks_nothing_and_runs_no_sudo(env):
    env.give_cli("1.5.0")
    p = env.run(tty=True, stdin="")
    assert p.returncode == 0, p.stdout
    assert env.root_or_net() == [] and "[all/step/no]" not in p.stdout
    assert "ok  container CLI 1.5.0 at %s (pinned 1.5.0)" % env.cli in p.stdout and "ok  container service running" in p.stdout
    assert env.stub_calls() == ["build-due --profiles core", "install --profiles core --no-build --no-prompt"]
    cli = env.kv("cli.env")
    assert cli["EQ_CLI_INSTALLED_BY"] == "preexisting" and cli["EQ_CLI_PKG_SHA256"] == ""
    before = (env.state / "cli.env").read_bytes()
    env.run(tty=True, stdin="")
    assert (env.state / "cli.env").read_bytes() == before          # rewritten only when a field changes


@needs_shasum
def test_a_due_build_alone_is_asked(env):
    env.give_cli("1.5.0")
    p = env.run(tty=True, stdin="step\nyes\n", EQ_STUB_BUILD_DUE=0)
    assert p.returncode == 0 and env.root_or_net() == [], p.stdout
    assert "1. build the isolation images (profiles core)" in p.stdout
    assert env.stub_calls()[-1] == "install --profiles core --yes --no-prompt"
    p = env.run(tty=True, stdin="no\n", EQ_STUB_BUILD_DUE=0)
    assert p.returncode == 10 and env.stub_calls()[-1] == "install --profiles core --no-build --no-prompt"


@needs_shasum
def test_service_down_only_starts_with_consent(env):
    env.give_cli("1.5.0", up=False)
    p = env.run()
    assert p.returncode == 10 and ("system", "start", "--enable-kernel-install") not in env.cli_calls()
    assert "! not started: the container service (no consent)" in p.stdout and env.root_or_net() == []
    p = env.run("--start-container-service")
    assert p.returncode == 0 and ("system", "start", "--enable-kernel-install") in env.cli_calls(), p.stdout
    assert env.root_or_net() == [] and not env.svc.exists()


@needs_shasum
def test_upgrade_stops_the_running_service_first(env):
    env.give_cli("1.4.1")
    p = env.run("--setup-container")
    assert p.returncode == 0, p.stdout
    calls = env.cli_calls()
    assert calls.index(("system", "stop")) < calls.index(("system", "start", "--enable-kernel-install"))
    out = p.stdout
    assert "! container CLI 1.4.1 at %s is older than the pinned 1.5.0" % env.cli in out
    assert out.index("FAKE sudo") > out.index("first    %s system stop" % env.cli)
    cli = env.kv("cli.env")
    assert cli["EQ_CLI_INSTALLED_BY"] == "stack" and cli["EQ_CLI_PREVIOUS"] == "1.4.1" and cli["EQ_CLI_VERSION"] == "1.5.0"


@needs_shasum
def test_failed_upgrade_starts_again_the_service_it_stopped(env):
    """An upgrade stops the running service first; when the install then fails, the service it stopped runs again (its
    kernel is there: --disable-kernel-install, nothing downloaded), or the run says it is still stopped."""
    env.give_cli("1.4.1")
    p = env.run("--install-container", EQ_FAKE_SUDO_RC="1")
    calls = env.cli_calls()
    assert p.returncode == 17 and ("system", "stop") in calls, p.stdout
    assert calls.index(("system", "stop")) < calls.index(("system", "start", "--disable-kernel-install")), calls
    assert not env.svc.exists() and "service this run stopped for the upgrade is running again" in p.stdout, p.stdout
    assert ("system", "start", "--enable-kernel-install") not in calls and env.stub_calls() == []
    p = env.run("--install-container", EQ_FAKE_SUDO_RC="1", EQ_FAKE_SVC_START_RC="1")
    assert p.returncode == 17 and env.svc.exists(), p.stdout
    assert "! the container service this run stopped for the upgrade is still stopped: container system start" in p.stdout


@needs_shasum
def test_newer_or_foreign_cli_is_left_alone(env):
    env.give_cli("1.6.0")
    p = env.run("--setup-container")
    assert p.returncode == 0 and env.root_or_net() == [], p.stdout
    assert "newer than the pinned 1.5.0: left alone" in p.stdout
    other = env.t / "elsewhere" / "container"
    other.parent.mkdir()
    shutil.copyfile(FAKES / "container-cli", other)
    other.chmod(0o755)
    Path(str(other) + ".version").write_text("1.2.0\n")
    p = env.run("--setup-container", EQ_CONTAINER_BIN=other)
    assert env.root_or_net() == [] and "update it yourself" in p.stdout, p.stdout
    p = env.run("--setup-container", EQ_CONTAINER_BIN=env.t / "nope" / "container")
    assert env.root_or_net() == [] and "which does not exist: nothing is installed over it" in p.stdout


# ------------------------------------------------------------------------------------------------- pins: fail closed
@needs_shasum
@pytest.mark.parametrize("key", ["CONTAINER_PKG_SIGNER", "CONTAINER_PKG_SHA256", "CONTAINER_PKG_URL", "CONTAINER_PKG_SIZE"])
@pytest.mark.parametrize("value", ["UNSET", "TODO", ""])
def test_placeholder_pin_refuses_before_any_network(env, key, value):
    set_pins(env.lib, **{key: value})
    p = env.run("--setup-container", tty=True, stdin="all\n")
    assert p.returncode == 13, p.stdout
    assert env.root_or_net() == [] and env.calls("pkgutil") == []
    assert "placeholder pin(s) in lib/eq-container/PINS: %s" % key in p.stdout
    assert "shasum -a 256" in p.stdout and "/usr/sbin/pkgutil --check-signature" in p.stdout
    assert "[all/step/no]" not in p.stdout                       # nothing left to ask about
    assert env.kv("setup.env")["EQ_SETUP_RC"] == "13"


@needs_shasum
@pytest.mark.parametrize("key, value", [
    ("CONTAINER_PKG_URL", "https://evil.example.com/container-1.5.0-installer-signed.pkg"),
    ("CONTAINER_PKG_URL", "http://github.com/apple/container/releases/download/1.5.0/container-1.5.0-installer-signed.pkg"),
    ("CONTAINER_PKG_URL", "https://github.com/apple/container/releases/download/1.5.0/../x/container-1.5.0-installer-signed.pkg"),
    ("CONTAINER_PKG_URL", "https://github.com/apple/container/releases/download/1.5.0/evil;rm.pkg"),
    ("CONTAINER_PKG_URL", "https://github.com/apple/container/releases/download/1.4.0/container-1.4.0-installer-signed.pkg"),
    ("CONTAINER_PKG_SHA256", "a" * 63), ("CONTAINER_PKG_SHA256", "A" * 64),
    ("CONTAINER_PKG_SIZE", "12x"), ("CONTAINER_PKG_SIZE", "0"),
    ("CONTAINER_PKG_SIGNER", "Developer ID $(id)"), ("CONTAINER_PKG_SIGNER", 'Apple "Inc"'),
    ("CONTAINER_PKG_VERSION", "1.5"), ("CONTAINER_PKG_VERSION", "1..5"),
    ("CONTAINER_PKG_ID", "com.apple/x"), ("CONTAINER_MIN_MACOS", "26.1"),
])
def test_malformed_pin_refuses_before_any_network(env, key, value):
    set_pins(env.lib, **{key: value})
    p = env.run("--setup-container")
    assert p.returncode in (2, 10), p.stdout                      # CONTAINER_PKG_VERSION 1.5: the CLI cannot be compared
    assert env.root_or_net() == [], (key, value, env.calls())
    if key != "CONTAINER_PKG_VERSION":
        assert p.returncode == 2 and "malformed pin(s) in lib/eq-container/PINS:" in p.stdout and key in p.stdout


# ------------------------------------------------------------------------------------------------- the package's checks
@needs_shasum
@pytest.mark.parametrize("knob, pins, want", [
    ({}, {"CONTAINER_PKG_SHA256": "b" * 64}, "REFUSED: sha256 %s differs from the pin" % PKG_SHA),
    ({}, {"CONTAINER_PKG_SIZE": len(PKG) + 1}, "REFUSED: the package is %d bytes" % len(PKG)),
    ({"EQ_FAKE_SIGNER": "Developer ID Installer: Someone Else (EVIL000000)"}, {}, "REFUSED: pkgutil --check-signature"),
    ({"EQ_FAKE_SIG_RC": "1"}, {}, "REFUSED: pkgutil --check-signature"),
])
def test_a_package_that_differs_from_the_pins_is_never_installed(env, knob, pins, want):
    if pins:
        set_pins(env.lib, **pins)
    p = env.run("--setup-container", **knob)
    assert p.returncode == 14, p.stdout
    assert want in p.stdout and "nothing installed" in p.stdout
    assert env.calls("sudo") == [] and env.calls("installer") == [] and not env.cli.exists()
    assert not list(env.state.glob("pkg.*")) and env.stub_calls() == []      # the flow stopped there
    assert env.kv("setup.env")["EQ_SETUP_RC"] == "14"


@needs_shasum
@pytest.mark.parametrize("status", ["signed by untrusted certificate", "no signature", "signed, but the certificate is revoked",
                                    "signed by a certificate that has since expired", ""])
def test_signature_status_must_be_a_valid_signed_one(env, status):
    sig = env.t / "sig.txt"
    sig.write_text("Package \"x\":\n   Status: %s\n   Certificate Chain:\n    1. %s\n" % (status, SIGNER))
    p = env.run("--setup-container", EQ_FAKE_SIG_FILE=sig)
    assert p.returncode == 14 and env.calls("sudo") == [], (status, p.stdout)


@needs_shasum
@pytest.mark.parametrize("target", ["https://evil.example.com/asset", "http://release-assets.githubusercontent.com/x",
                                    "https://user@release-assets.githubusercontent.com/x",
                                    "https://release-assets.githubusercontent.com:8443/x", ""])
def test_redirects_stay_on_githubs_release_hosts(env, target):
    p = env.run("--setup-container", EQ_FAKE_REDIRECT=target)
    assert p.returncode == 17, p.stdout
    assert len(env.calls("curl")) == 1 and env.calls("sudo") == [], env.calls()
    assert "refused" in p.stdout and "download failed: nothing installed" in p.stdout


@needs_shasum
def test_download_and_install_failures_name_the_retry(env):
    p = env.run("--setup-container", EQ_FAKE_CURL_RC="22")
    assert p.returncode == 17 and env.calls("sudo") == [] and "retry: ./install.sh --with-eq-container --install-container" in p.stdout
    p = env.run("--setup-container", EQ_FAKE_SUDO_RC="1")
    assert p.returncode == 17 and env.calls("installer") == [] and not env.cli.exists(), p.stdout
    assert "! sudo installer failed; retry" in p.stdout and not list(env.state.glob("pkg.*"))
    p = env.run("--setup-container", EQ_FAKE_PKG_VERSION="1.4.0")      # the installed CLI is not the pinned one
    assert p.returncode == 17 and "not 1.5.0" in p.stdout, p.stdout
    assert ("system", "start", "--enable-kernel-install") not in env.cli_calls()     # nothing unverified is started
    assert env.kv("cli.env")["EQ_CLI_INSTALLED_BY"] == "stack" and env.kv("setup.env")["EQ_SETUP_STEP"] == "cli"


@needs_shasum
def test_service_start_failure_stops_the_flow(env):
    env.give_cli("1.5.0", up=False)
    p = env.run("--start-container-service", EQ_FAKE_SVC_START_RC="1")
    assert p.returncode == 18 and "retry from a normal terminal: container system start" in p.stdout, p.stdout
    assert env.stub_calls() == [] and env.kv("setup.env")["EQ_SETUP_STEP"] == "service"


@needs_shasum
def test_the_drivers_own_skip_is_not_relabelled_as_a_step_1_stop(env):
    """A step 1 that could not run (13) is the outcome only when the driver then skipped for want of a CLI or a running
    service; with both there, the driver's own skip (here: a due build without consent) is the outcome."""
    env.give_cli("1.4.1")                                            # older than the pin, at the package path, running
    set_pins(env.lib, CONTAINER_PKG_SIGNER="UNSET")                  # so step 1 cannot be offered (13)
    p = env.run(EQ_STUB_BUILD_DUE=0)
    assert p.returncode == 10 and env.kv("setup.env")["EQ_SETUP_STEP"] == "build", p.stdout
    assert env.stub_calls()[-1] == "install --profiles core --no-build --no-prompt"
    env.svc.write_text("")                                           # the service down: the driver skips for want of it
    p = env.run(EQ_STUB_BUILD_DUE=0)
    assert p.returncode == 13 and env.kv("setup.env")["EQ_SETUP_STEP"] == "cli", p.stdout


# ------------------------------------------------------------------------------------------------- platform and agents
@needs_shasum
@pytest.mark.parametrize("knob, want", [({"EQ_FAKE_MACOS": "15.6"}, "macOS 15.6 is older than 26"),
                                        ({"EQ_HOST_ARCH": "x86_64"}, "not Apple silicon (x86_64)"),
                                        ({"EQ_FAKE_MACOS": "garbage"}, "macOS version could not be read")])
def test_unsupported_mac_is_a_skip(env, knob, want):
    p = env.run("--setup-container", **knob)
    assert p.returncode == 10 and want in p.stdout and env.root_or_net() == [], p.stdout


@needs_shasum
def test_an_agent_shell_never_runs_steps_1_and_2(env):
    p = env.run("--setup-container", tty=True, stdin="all\n", CLAUDECODE="1")
    assert p.returncode == 10 and env.root_or_net() == [], p.stdout
    assert "agent's shell (CLAUDECODE is set)" in p.stdout
    env.give_cli("1.5.0", up=False)
    p = env.run("--setup-container", CLAUDECODE="1")
    assert ("system", "start", "--enable-kernel-install") not in env.cli_calls() and p.returncode == 10


# ------------------------------------------------------------------------------------------------- dry run, records, usage
@needs_shasum
def test_dry_run_changes_nothing(env):
    p = env.run("--dry-run", "--setup-container", tty=True, stdin="all\n")
    assert p.returncode == 0, p.stdout
    assert env.root_or_net() == [] and not env.state.exists() and "[all/step/no]" not in p.stdout
    assert "would: Step: install Apple container 1.5.0" in p.stdout and "(consent: --install-container)" in p.stdout
    assert "would: bash lib/eq-container/eq-container.sh install --profiles core --yes --no-prompt" in p.stdout
    p = env.run("--dry-run")
    assert p.returncode == 10 and "(needs consent: a terminal answer, --install-container" in p.stdout
    env.give_cli("1.5.0")
    p = env.run("--dry-run")
    assert p.returncode == 0 and env.stub_calls()[-1] == "install --profiles core --no-build --no-prompt --dry-run"
    assert ("system", "start", "--enable-kernel-install") not in env.cli_calls() and not env.state.exists()


@needs_shasum
def test_removal_prints_apples_commands_and_removes_nothing(env):
    env.svc.write_text("")
    env.run("--setup-container")
    n = len(env.calls())
    p = env.run(cmd="removal")
    assert "container system stop; /usr/local/bin/uninstall-container.sh -k" in p.stdout, p.stdout
    assert env.cli.exists() and len(env.calls()) == n                # printed, nothing run
    (env.state / "cli.env").write_text("EQ_CLI_INSTALLED_BY=preexisting\n")
    assert "installed before the stack: left alone" in env.run(cmd="removal").stdout


def test_a_refused_state_dir_gets_no_record(env):
    """A state dir refused as a symlink gets no setup.env written through the link (standalone runs; install.sh refuses
    such a dir before setup.sh runs)."""
    env.give_cli()
    real = env.t / "elsewhere"
    real.mkdir()
    link = env.t / "statelink"
    link.symlink_to(real)
    p = env.run("--no-prompt", EQ_STATE_DIR=link)
    assert p.returncode == 10 and "is a symlink or not a directory: refused" in p.stdout, p.stdout
    assert list(real.iterdir()) == [] and env.stub_calls() == []


@pytest.mark.parametrize("args, want", [
    (("run", "--bogus", "--", "install"), "unknown option: --bogus"),
    (("run", "--install-container", "--no-install-container", "--", "install"), "contradicts"),
    (("run", "--setup-container", "--no-install-container", "--", "install"), "contradicts"),
    (("run", "--", "uninstall"), "run needs -- install"),
    (("frobnicate",), "unknown command"),
])
def test_usage_errors(env, args, want):
    p = subprocess.run(["/bin/bash", str(env.lib / "setup.sh"), *args], env={"PATH": "/usr/bin:/bin", "HOME": str(env.t)},
                       stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=60, start_new_session=True)
    assert p.returncode == 2 and want in p.stderr, (p.returncode, p.stderr)
    assert env.calls() == [] and not env.state.exists()


def test_help_is_the_header():
    p = subprocess.run(["/bin/bash", str(LIB / "setup.sh"), "--help"], capture_output=True, text=True, timeout=60)
    assert p.returncode == 0 and "setup.sh run" in p.stdout and "18 the service did not start" in p.stdout
    assert "readonly" not in p.stdout and "set -u" not in p.stdout


# ------------------------------------------------------------------------------------------------- static rules
def test_sudo_is_one_call_with_absolute_paths():
    """The one sudo: "$EQS_SUDO" "$EQS_INSTALLER" -pkg <file> -target /. The tools are readonly absolute constants, assigned
    once; none is ever called by its bare name (shell code with plain strings blanked and comments removed)."""
    raw = [ln for ln in SETUP.splitlines() if not ln.lstrip().startswith("#")]
    assert [ln.strip() for ln in raw if '"$EQS_SUDO"' in ln] == ['if ! "$EQS_SUDO" "$EQS_INSTALLER" -pkg "$f" -target /; then']
    for name, path in CONSTS.items():
        assert "readonly %s=%s\n" % (name, path) in SETUP, name
        assert len(re.findall(r"\b%s=" % name, SETUP)) == 1, name                     # assigned once, never re-set
    code = [ln for ln in shell_code(SETUP).splitlines() if not ln.startswith("readonly EQS_")]
    bare = [ln for ln in code if re.search(r"\b(sudo|curl|pkgutil|installer|sw_vers|shasum)\b", ln)]
    assert bare == [], bare
    assert not re.search(r"\|\s*(ba|z)?sh\b|\beval\b|\bsource\b|^\s*\.\s", "\n".join(code), re.M)
    assert "PATH=/usr/bin:/bin:/usr/sbin:/sbin\nexport PATH\n" in SETUP


def test_no_other_eq_script_calls_sudo():
    for f in sorted(LIB.rglob("*.sh")):
        # probe_inner.sh runs INSIDE the container and only reports whether a `sudo` is on the image's PATH
        if f.name in ("setup.sh", "probe_inner.sh"):
            continue
        assert not re.search(r"\bsudo\b", shell_code(f.read_text())), f


# ------------------------------------------------------------------------------------------------- seeded faults
# Each rule's check, run against a copy of setup.sh with that rule broken: the check must see the break (else the test that
# guards the rule would pass on broken code).
def _no_consent_downloads(e):
    e.run()
    return bool(e.root_or_net())


def _wrong_hash_installs(e):
    set_pins(e.lib, CONTAINER_PKG_SHA256="b" * 64)
    e.run("--setup-container")
    return bool(e.calls("sudo"))


def _wrong_signer_installs(e):
    e.run("--setup-container", EQ_FAKE_SIGNER="Developer ID Installer: Someone Else (EVIL000000)")
    return bool(e.calls("sudo"))


def _placeholder_downloads(e):
    set_pins(e.lib, CONTAINER_PKG_SIGNER="UNSET")
    e.run("--setup-container")
    return bool(e.calls("curl"))


def _y_installs(e):
    e.run(tty=True, stdin="step\ny\n")
    return bool(e.calls("sudo"))


def _evil_redirect_followed(e):
    e.run("--setup-container", EQ_FAKE_REDIRECT="https://evil.example.com/x")
    return len(e.calls("curl")) > 1


def _agent_installs(e):
    e.run("--setup-container", CLAUDECODE="1")
    return bool(e.calls("sudo"))


def _path_sudo_runs(e):
    try:
        e.run("--setup-container")
    except AssertionError as err:                                # the HIJACK log is the detection
        return "HIJACK" in str(err)
    return False


SEEDED = [
    ("consent ignored", _no_consent_downloads, mutate(
        'consent() { # FLAG(0/1) STEP-TEXT-FUNCTION QUESTION: 0 when the step may run; its full text is printed first in any case\n  "$2"\n',
        'consent() {\n  "$2"; return 0\n')),
    ("sha256 not compared", _wrong_hash_installs, mutate('[ "$got" = "$PSHA" ] ||', 'true ||')),
    ("signer not compared", _wrong_signer_installs, mutate('[ "$leaf" != "$PSIGNER" ]', 'false')),
    ("placeholder pins accepted", _placeholder_downloads, mutate(
        'pins_state() { # PIN_ST ok | placeholder | malformed, PIN_WHY the keys\n',
        'pins_state() { # PIN_ST ok | placeholder | malformed, PIN_WHY the keys\n  return 0\n')),
    ("y counts as yes", _y_installs, mutate('typed_yes() { case "$ANS" in yes|YES|Yes)', 'typed_yes() { case "$ANS" in y*|Y*)')),
    ("any redirect host", _evil_redirect_followed, mutate('case " $EQS_HOSTS " in *" $host "*) ;;', 'case " $EQS_HOSTS " in *) ;;')),
    ("agent shell allowed", _agent_installs, mutate('elif [ -n "${CLAUDECODE:-}" ]; then block=', 'elif false; then block=')),
    ("sudo from PATH", _path_sudo_runs, mutate('PATH=/usr/bin:/bin:/usr/sbin:/sbin\nexport PATH\n', 'export PATH\n').replace(
        'if ! "$EQS_SUDO" "$EQS_INSTALLER"', 'if ! sudo "$EQS_INSTALLER"')),
]


@needs_shasum
@pytest.mark.parametrize("name, broken, text", SEEDED, ids=[s[0] for s in SEEDED])
def test_seeded_fault_is_caught(tmp_path, name, broken, text):
    good = Env(tmp_path / "good")
    assert not broken(good), name                                  # the shipped script keeps the rule
    bad = Env(tmp_path / "bad", text)
    assert broken(bad), name                                       # the seeded copy breaks it, and the check sees that
