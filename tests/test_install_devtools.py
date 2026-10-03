"""lib/devtools.sh (install.sh step 2) and bin/stack-update-tools: one line per tool, a present tool
is never touched, one brew batch per type with only the missing names, unresolved names dropped and
reported, a failed batch retried name by name, casks and Homebrew's installer only on a terminal,
the upstream installers fetched over HTTPS and run with their non-interactive flags, one group's
failure never stops the others, a required tool still missing stops the run with one message, and
dry-run / report modes install nothing.

Hermetic: every program it could call (brew, curl, uv, npx, ghcup, cabal, ...) is a PATH shim that
logs its argv; PATH is the shim dir plus /usr/bin:/bin, HOME a temp dir, Homebrew candidates,
the JDK dir and the TeX dir point into the temp dir, and every group is off unless a test turns it on.

Run: uv run --with pytest pytest -q tests/test_install_devtools.py
"""
import gzip
import io
import os
import re
import stat
import subprocess
import tarfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "lib" / "devtools.sh"
UPDATE = ROOT / "dot-claude" / "bin" / "stack-update-tools"
SRC = SCRIPT.read_text()
PW_REV = re.search(r"^PLAYWRIGHT_CHROMIUM_REVISION=(\d+)", SRC, re.M).group(1)
GRADLE_V = re.search(r"^GRADLE_VERSION=(\S+)", SRC, re.M).group(1)
GROUPS = re.search(r'^GROUPS_ALL="([^"]+)"', SRC, re.M).group(1).split()
BREW_ITEMS = [l.split() for l in re.search(r'^BREW_ITEMS="(.*?)"$', SRC, re.M | re.S).group(1).splitlines()]

LOGGER = ('printf "%s %s | PROFILE=%s UV_NO_MODIFY_PATH=%s CABAL_DIR=%s ANALYTICS=%s\\n" '
          '"$(basename "$0")" "$*" "${PROFILE:-}" "${UV_NO_MODIFY_PATH:-}" "${CABAL_DIR:-}" '
          '"${HOMEBREW_NO_ANALYTICS:-}" >>"$SHIM_LOG"\n')

BREW_SHIM = r'''
state="$BREW_STATE"; touch "$state"
case "$1" in
  list) t=formula; [ "$2" = --cask ] && t=cask; grep "^$t " "$state" | cut -d' ' -f2 ;;
  info) case " ${BREW_BAD:-} " in *" $3 "*) exit 1 ;; esac ;;
  tap) [ $# -eq 1 ] && echo homebrew/core ;;
  --prefix) echo /opt/fake/$2 ;;
  install)
    shift; t=formula; [ "$1" = --cask ] && { t=cask; shift; }
    [ $# -gt 1 ] && [ -n "${BREW_BATCH_FAIL:-}" ] && exit 1
    for n in "$@"; do case " ${BREW_FAIL:-} " in *" $n "*) exit 1 ;; esac; done
    for n in "$@"; do echo "$t ${n##*/}" >>"$state"; done ;;
esac
exit 0
'''

CURL_SHIM = r'''
out=""; url=""
while [ $# -gt 0 ]; do case "$1" in -o) out="$2"; shift ;; https://*) url="$1" ;; esac; shift; done
f="$SERVE_DIR/$(printf '%s' "$url" | tr -c 'A-Za-z0-9' _)"
[ -f "$f" ] && [ -n "$out" ] && cp "$f" "$out" && exit 0
exit 22
'''


def mkexe(path, body):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/bin/bash\n" + body + "\n")
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return path


def key(url):
    return re.sub(r"[^A-Za-z0-9]", "_", url)


class Env:
    def __init__(self, tmp_path):
        self.t = tmp_path
        self.home = tmp_path / "home"
        self.home.mkdir()
        self.bin = tmp_path / "shims"
        self.bin.mkdir()
        self.log = tmp_path / "shim.log"
        self.log.write_text("")
        self.serve = tmp_path / "serve"
        self.serve.mkdir()
        self.tmp = tmp_path / "tmp"
        self.tmp.mkdir()
        self.state = tmp_path / "brew.state"
        self.jvm = tmp_path / "jvm"
        self.jvm.mkdir()
        mkexe(self.bin / "curl", LOGGER + CURL_SHIM)

    def shim(self, name, body="exit 0", where=None):
        return mkexe((where or self.bin) / name, LOGGER + body)

    def present(self, *names):
        for n in names:
            mkexe(self.bin / n, "exit 0")

    def brew(self, installed=(), casks=()):
        self.state.write_text("".join("formula %s\n" % n for n in installed) + "".join("cask %s\n" % n for n in casks))
        self.shim("brew", BREW_SHIM)

    def serve_file(self, url, data):
        p = self.serve / key(url)
        p.write_bytes(data if isinstance(data, bytes) else data.encode())
        return p

    def run(self, *groups, mode="install", tty="0", args=("all",), script=SCRIPT, **extra):
        env = {"HOME": str(self.home), "PATH": "%s:/usr/bin:/bin" % self.bin, "SHIM_LOG": str(self.log),
               "TMPDIR": str(self.tmp), "SERVE_DIR": str(self.serve), "BREW_STATE": str(self.state),
               "DEVTOOLS_BREW_CANDIDATES": "", "DEVTOOLS_JAVA_HOME_TOOL": "", "DEVTOOLS_TTY": tty,
               "DEVTOOLS_JVM_DIR": str(self.jvm), "DEVTOOLS_TEX_BIN": str(self.t / "notex"),
               "DEVTOOLS_MODE": mode}
        for g in GROUPS:
            env["STACK_INSTALL_" + g] = "1" if g in groups else "0"
        env.update(extra)
        p = subprocess.run(["bash", str(script)] + list(args), env=env, capture_output=True, text=True, timeout=120)
        return p.returncode, p.stdout, p.stderr

    def calls(self, name=None, sub=None):
        out = []
        for l in self.log.read_text().splitlines():
            if not l:
                continue
            prog, _, rest = l.partition(" ")
            argv = rest.split(" | ")[0]
            if (name is None or prog == name) and (sub is None or argv.startswith(sub)):
                out.append(l)
        return out

    def argv(self, name, sub=None):
        return [l.partition(" ")[2].split(" | ")[0] for l in self.calls(name, sub)]

    def pw_dir(self):
        return self.home / ("Library/Caches/ms-playwright" if os.uname().sysname == "Darwin" else ".cache/ms-playwright")

    def playwright_installed(self):
        for d in ("chromium-" + PW_REV, "chromium_headless_shell-" + PW_REV):
            (self.pw_dir() / d).mkdir(parents=True, exist_ok=True)
            (self.pw_dir() / d / "INSTALLATION_COMPLETE").write_text("")


def lines(out):
    return [l for l in out.splitlines() if l.strip()]


def group_items(*groups):
    return [(t, n) for g, t, n, _ in BREW_ITEMS if g in groups]


# ---------------------------------------------------------------- Homebrew batch
def test_all_present_means_no_brew_install_and_no_download(tmp_path):
    e = Env(tmp_path)
    groups = ("DEPS", "DEVTOOLS", "CXX", "GO", "JAVA", "LATEX")
    items = group_items(*groups)
    e.brew(installed=[n.split("/")[-1] for t, n in items if t == "formula"], casks=[n for t, n in items if t == "cask"])
    e.present("uv", "node", "npx", "pre-commit", "gradle")
    e.playwright_installed()
    rc, out, err = e.run(*groups)
    assert rc == 0, err
    assert e.calls("brew", "install") == [] and e.calls("brew", "info") == []
    assert e.calls("curl") == [] and e.calls("uv") == [] and e.calls("npx") == []
    assert any(l.startswith("  ok  already installed:") for l in lines(out))
    assert not [l for l in lines(out) if l.lstrip().startswith(("!", "+", "would"))], out


def test_present_from_other_sources_is_skipped(tmp_path):
    """A go or cmake on PATH from elsewhere, a JDK >= 27 in the JDK dir and a TeX bin dir count as
    present, though brew never installed them."""
    e = Env(tmp_path)
    e.brew()
    e.present("go", "gopls", "uv", "node", "npx", "kotlin-lsp")
    home = e.jvm / "jdk-27.jdk" / "Contents" / "Home"
    home.mkdir(parents=True)
    (home / "release").write_text('JAVA_VERSION="27.0.1"\n')
    tex = tmp_path / "tex"
    mkexe(tex / "pdflatex", "exit 0")
    rc, out, _ = e.run("GO", "JAVA", "LATEX", DEVTOOLS_TEX_BIN=str(tex))
    assert rc == 0
    assert e.calls("brew", "install") == []
    skipped = next(l for l in lines(out) if "already installed:" in l).split(":", 1)[1].split()
    assert set(skipped) == {"go", "gopls", "oracle-jdk", "kotlin-lsp", "mactex"}


def test_an_older_jdk_does_not_count(tmp_path):
    e = Env(tmp_path)
    e.brew()
    e.present("uv", "node", "npx", "kotlin-lsp")
    home = e.jvm / "jdk-21.jdk" / "Contents" / "Home"
    home.mkdir(parents=True)
    (home / "release").write_text('JAVA_VERSION="21.0.4"\n')
    rc, out, _ = e.run("JAVA", tty="1")
    assert e.argv("brew", "install") == ["install --cask oracle-jdk"]


def test_missing_names_go_in_one_formula_and_one_cask_batch(tmp_path):
    e = Env(tmp_path)
    e.brew(installed=["cmake"])
    e.present("uv", "node", "npx")
    rc, out, err = e.run("GO", "CXX", "JAVA", tty="1", BREW_BAD="gopls")
    assert rc == 0, err
    f = e.argv("brew", "install")
    formulae = [a for a in f if not a.startswith("install --cask")]
    casks = [a for a in f if a.startswith("install --cask")]
    assert len(formulae) == 1 and len(casks) == 1, f
    want_f = [n for t, n in group_items("CXX", "GO") if t == "formula" and n not in ("cmake", "gopls")]
    assert formulae[0].split()[1:] == want_f
    assert casks[0].split()[2:] == [n for t, n in group_items("JAVA") if t == "cask"]
    assert "! brew could not resolve: gopls (left out)" in out
    assert all(("+ %s (brew)" % n) in out for n in want_f)
    assert all(l.endswith("ANALYTICS=1") for l in e.calls("brew"))   # HOMEBREW_NO_ANALYTICS on every call


def test_failed_batch_is_retried_name_by_name(tmp_path):
    e = Env(tmp_path)
    e.brew()
    e.present("uv", "node", "npx")
    rc, out, _ = e.run("GO", BREW_BATCH_FAIL="1", BREW_FAIL="gopls")
    assert rc == 0
    assert e.argv("brew", "install") == ["install go gopls", "install go", "install gopls"]
    assert "! the batch failed: retrying one by one" in out
    assert "+ go (brew)" in out and "! gopls: brew install failed" in out


def test_casks_without_a_terminal_are_printed_not_run(tmp_path):
    e = Env(tmp_path)
    e.brew()
    e.present("uv", "node", "npx")
    rc, out, _ = e.run("JAVA", "LATEX", tty="0")
    assert rc == 0
    assert e.calls("brew", "install") == []
    assert re.search(r"! casks not installed .*brew install --cask oracle-jdk kotlin-lsp mactex", out), out
    assert "mactex is about 5 GB" in out


def test_mongodb_taps_first_and_postgres_mongodb_are_off_by_default(tmp_path):
    e = Env(tmp_path)
    e.brew()
    e.present("uv", "node", "npx")
    rc, out, _ = e.run("MONGODB")
    assert rc == 0
    assert e.argv("brew", "tap") == ["tap", "tap mongodb/brew"]
    assert e.argv("brew", "install") == ["install mongodb/brew/mongodb-community"]
    assert 'case "$1" in POSTGRES|MONGODB) d=0 ;; esac' in SRC


# ---------------------------------------------------------------- Homebrew bootstrap
def url(name):
    u = re.search(r'^URL_%s="([^"]+)"' % name, SRC, re.M).group(1)
    arch = "aarch64" if os.uname().machine in ("arm64", "aarch64") else "x86_64"
    return u.replace("$NVM_VERSION", "v0.40.8").replace("$CS_ARCH", arch)


def test_homebrew_needs_a_terminal(tmp_path):
    e = Env(tmp_path)
    e.present("uv", "node", "npx")
    rc, out, _ = e.run("DEPS", tty="0")
    assert rc == 0 and e.calls("curl") == []
    assert re.search(r"! homebrew missing — no terminal: run /bin/bash -c .*Homebrew/install/HEAD/install\.sh", out)


def test_homebrew_bootstrap_on_a_terminal_and_one_shellenv_line(tmp_path):
    e = Env(tmp_path)
    e.present("uv", "node", "npx", "jq", "rg", "gh", "ffmpeg", "magick", "rsvg-convert", "pdftoppm")
    hb = tmp_path / "hb" / "bin" / "brew"
    e.shim("fake-brew", BREW_SHIM, where=tmp_path)
    e.serve_file(url("HOMEBREW"), "mkdir -p %s; cp %s %s; chmod +x %s\n" % (hb.parent, tmp_path / "fake-brew", hb, hb))
    rc, out, err = e.run("DEPS", tty="1", DEVTOOLS_BREW_CANDIDATES=str(hb))
    assert rc == 0, err
    curl = e.argv("curl")
    assert curl and curl[0].startswith("--proto =https --tlsv1.2") and curl[0].endswith(url("HOMEBREW"))
    assert "+ homebrew" in out
    zp = (e.home / ".zprofile").read_text()
    assert zp.count("brew shellenv") == 1 and str(hb) in zp
    e.run("DEPS", tty="1", DEVTOOLS_BREW_CANDIDATES=str(hb))
    assert (e.home / ".zprofile").read_text().count("brew shellenv") == 1
    home2 = tmp_path / "home2"
    home2.mkdir()
    e.run("DEPS", tty="1", DEVTOOLS_BREW_CANDIDATES=str(hb), DEVTOOLS_NO_PROFILE="1", HOME=str(home2))
    assert not (home2 / ".zprofile").exists()


# ---------------------------------------------------------------- upstream managers
def installer(e, name, creates):
    """Serve an installer script that logs its args/env and creates CREATES (paths under HOME)."""
    body = ('printf "installer-%s %%s | BHN=%%s BHHLS=%%s BHRC=%%s UV_NO_MODIFY_PATH=%%s PROFILE=%%s\\n" "$*" '
            '"${BOOTSTRAP_HASKELL_NONINTERACTIVE:-}" "${BOOTSTRAP_HASKELL_INSTALL_HLS:-}" '
            '"${BOOTSTRAP_HASKELL_ADJUST_BASHRC:-}" "${UV_NO_MODIFY_PATH:-}" "${PROFILE:-}" >>"$SHIM_LOG"\n' % name)
    for c in creates:
        d, b = os.path.dirname(c), os.path.basename(c)
        body += 'mkdir -p "$HOME/%s"; printf "#!/bin/sh\\nexit 0\\n" >"$HOME/%s/%s"; chmod +x "$HOME/%s/%s"\n' % (d, d, b, d, b)
    e.serve_file(url(name), body)


def inst_line(e, name):
    return [l for l in e.log.read_text().splitlines() if l.startswith("installer-%s " % name)]


def test_upstream_installers_run_with_their_noninteractive_flags(tmp_path):
    e = Env(tmp_path)
    e.present("node", "npx", "hlint", "ormolu")
    installer(e, "RUSTUP", [".cargo/bin/rustup"])
    installer(e, "JULIAUP", [".juliaup/bin/juliaup"])
    installer(e, "UV", [".local/bin/uv"])
    installer(e, "GHCUP", [".ghcup/bin/ghcup", ".ghcup/bin/cabal"])
    rc, out, err = e.run("RUST", "JULIA", "UV", "HASKELL")
    assert rc == 0, err
    assert inst_line(e, "RUSTUP")[0].split(" | ")[0] == "installer-RUSTUP -y"
    assert inst_line(e, "JULIAUP")[0].split(" | ")[0] == "installer-JULIAUP --yes"
    assert "BHN=1 BHHLS=1 BHRC=1" in inst_line(e, "GHCUP")[0]
    for c in e.argv("curl"):
        assert c.startswith("--proto =https --tlsv1.2 "), c
    for label in ("rustup", "juliaup", "uv", "ghcup"):
        assert re.search(r"^  \+ %s \(" % label, out, re.M), out


def test_no_profile_is_passed_to_the_installers(tmp_path):
    e = Env(tmp_path)
    e.present("node", "npx", "hlint", "ormolu")
    installer(e, "RUSTUP", [".cargo/bin/rustup"])
    installer(e, "JULIAUP", [".juliaup/bin/juliaup"])
    installer(e, "UV", [".local/bin/uv"])
    installer(e, "GHCUP", [".ghcup/bin/ghcup"])
    installer(e, "NVM", [])
    e.run("RUST", "JULIA", "UV", "HASKELL", "NODE", DEVTOOLS_NO_PROFILE="1")
    assert inst_line(e, "RUSTUP")[0].split(" | ")[0] == "installer-RUSTUP -y --no-modify-path"
    assert inst_line(e, "JULIAUP")[0].split(" | ")[0] == "installer-JULIAUP --yes --add-to-path=no"
    assert "UV_NO_MODIFY_PATH=1" in inst_line(e, "UV")[0]
    assert "BHRC= " in inst_line(e, "GHCUP")[0]
    assert inst_line(e, "NVM")[0].endswith("PROFILE=/dev/null")


def test_one_failing_installer_does_not_stop_the_others(tmp_path):
    e = Env(tmp_path)
    e.present("uv", "node", "npx")
    e.serve_file(url("RUSTUP"), "exit 1\n")
    installer(e, "JULIAUP", [".juliaup/bin/juliaup"])
    rc, out, _ = e.run("RUST", "JULIA")
    assert rc == 0
    assert re.search(r"^  ! rustup: install failed \(log \S+\)", out, re.M), out
    assert re.search(r"^  \+ juliaup", out, re.M)


def test_present_managers_are_never_rerun(tmp_path):
    e = Env(tmp_path)
    e.present("node", "npx", "rustup", "juliaup", "cs", "hlint", "ormolu", "ghcup", "cabal", "pnpm")
    nb = e.home / ".nvm" / "versions" / "node" / "v24.3.0" / "bin"
    mkexe(nb / "node", "exit 0")
    (e.home / ".nvm" / "nvm.sh").write_text("nvm(){ :; }\n")
    mkexe(e.bin / "uv", 'case "$*" in "python find 3.14") exit 0 ;; "python pin --global") echo 3.14 ;; esac; exit 0')
    rc, out, _ = e.run("UV", "NODE", "RUST", "JULIA", "SCALA", "HASKELL")
    assert rc == 0
    assert e.calls("curl") == []
    assert not [l for l in lines(out) if not l.startswith(("  ok  ", "  groups off:"))], out


def test_nvm_node24_and_pnpm_without_keystrokes(tmp_path):
    e = Env(tmp_path)
    e.present("uv")
    # the fake nvm.sh: `nvm install 24` makes node, npx and a corepack whose `enable pnpm` makes pnpm
    corepack = ('#!/bin/bash\necho "corepack $* | PROMPT=${COREPACK_ENABLE_DOWNLOAD_PROMPT:-}" >>"$SHIM_LOG"\n'
                'printf \'#!/bin/bash\\necho "pnpm $* | PROMPT=${COREPACK_ENABLE_DOWNLOAD_PROMPT:-}" >>"$SHIM_LOG"\\n\' '
                '>"$(dirname "$0")/pnpm"; chmod +x "$(dirname "$0")/pnpm"\n')
    (e.t / "corepack.src").write_text(corepack)
    nvm_sh = ('nvm(){ d="$NVM_DIR/versions/node/v24.9.0/bin"; mkdir -p "$d"; '
              'for t in node npx; do printf "#!/bin/sh\\nexit 0\\n" >"$d/$t"; chmod +x "$d/$t"; done; '
              'cp "%s" "$d/corepack"; chmod +x "$d/corepack"; }\n' % (e.t / "corepack.src"))
    (e.t / "nvm.sh.src").write_text(nvm_sh)
    e.serve_file(url("NVM"), 'mkdir -p "$HOME/.nvm"; cp "%s" "$HOME/.nvm/nvm.sh"\n' % (e.t / "nvm.sh.src"))
    rc, out, err = e.run("NODE")
    assert rc == 0, out + err
    for label in ("nvm", "node 24 (nvm)", "pnpm (corepack)"):
        assert re.search(r"^  \+ %s" % re.escape(label), out, re.M), out
    log = e.log.read_text()
    assert "corepack enable pnpm" in log
    assert re.search(r"^pnpm -v \| PROMPT=0$", log, re.M), log


def test_coursier_from_the_upstream_asset(tmp_path):
    e = Env(tmp_path)
    e.present("uv", "node", "npx")
    cs = ('#!/bin/bash\necho "cs $*" >>"$SHIM_LOG"\n'
          'd="$HOME/Library/Application Support/Coursier/bin"; mkdir -p "$d"; printf "#!/bin/sh\\n" >"$d/cs"; chmod +x "$d/cs"\n')
    e.serve_file(url("COURSIER"), gzip.compress(cs.encode()))
    rc, out, err = e.run("SCALA")
    assert rc == 0, err
    assert "cs setup -y" in e.log.read_text()
    assert re.search(r"^  \+ coursier", out, re.M), out
    assert not list(e.tmp.glob("stack-devtools.*/cs"))       # the temp cs is gone


def test_haskell_plan_uses_the_users_cabal_dirs_and_drops_the_broken_ormolu(tmp_path):
    e = Env(tmp_path)
    e.present("uv", "node", "npx")
    broken = mkexe(tmp_path / "ghcup-ormolu", "kill -ABRT $$")
    e.shim("ghcup", 'case "$1 $2" in "whereis ghc") exit 1 ;; "whereis ormolu") echo %s ;; esac; exit 0' % broken)
    e.shim("cabal", 'case "$*" in *ormolu-*) mkdir -p "$HOME/.cabal/bin"; printf "#!/bin/sh\\nexit 0\\n" >"$HOME/.cabal/bin/ormolu"; '
                    'chmod +x "$HOME/.cabal/bin/ormolu" ;; *hlint-*) printf "#!/bin/sh\\nexit 0\\n" >"%s/hlint"; chmod +x "%s/hlint" ;; esac'
           % (e.bin, e.bin))
    rc, out, err = e.run("HASKELL", CABAL_DIR=str(tmp_path / "sandboxed-cabal"))
    assert rc == 0, err
    assert e.argv("ghcup")[:2] == ["whereis ghc 9.12.4", "install ghc 9.12.4"]
    assert "rm ormolu 0.8.0.2" in e.argv("ghcup")
    assert e.argv("cabal") == [
        "update", "install --ignore-project -w ghc-9.12.4 hlint-3.10 --overwrite-policy=always",
        "update", "install --ignore-project ormolu-0.9.0.0 --overwrite-policy=always"]
    assert all("CABAL_DIR= " in c for c in e.calls("cabal"))
    assert "- ormolu 0.8.0.2 (ghcup, broken) removed" in out


# ---------------------------------------------------------------- required tools
def test_required_missing_stops_with_one_message(tmp_path):
    e = Env(tmp_path)
    rc, out, err = e.run("DEPS")                      # no brew, the uv tarball download fails, no node
    assert rc == 3
    assert "required tools are missing and could not be installed" in err
    assert re.search(r"^  uv — ", err, re.M) and re.search(r"^  node \+ npx — ", err, re.M), err


def test_optional_failure_continues(tmp_path):
    e = Env(tmp_path)
    e.brew()
    e.present("uv", "node", "npx")
    rc, out, _ = e.run("GO", BREW_FAIL="go gopls")
    assert rc == 0 and "! go: brew install failed" in out


# ---------------------------------------------------------------- dev tools (pinned downloads)
def gradle_zip(path):
    with zipfile.ZipFile(path, "w") as z:
        info = zipfile.ZipInfo("gradle-%s/bin/gradle" % GRADLE_V)
        info.external_attr = 0o100755 << 16
        z.writestr(info, "#!/bin/sh\nexit 0\n")
    return path.read_bytes()


def gitleaks_tgz():
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as t:
        data = b"#!/bin/sh\nexit 0\n"
        info = tarfile.TarInfo("gitleaks")
        info.size, info.mode = len(data), 0o755
        t.addfile(info, io.BytesIO(data))
    return buf.getvalue()


def test_checksums_refuse_a_wrong_download(tmp_path):
    e = Env(tmp_path)
    e.present("uv", "node", "npx", "pre-commit", "jq")
    e.playwright_installed()
    gurl = re.search(r'^GRADLE_URL="([^"]+)"', SRC, re.M).group(1).replace("$GRADLE_VERSION", GRADLE_V)
    e.serve_file(gurl, gradle_zip(tmp_path / "g.zip"))      # a well-formed zip, not the pinned sha256
    sysname, machine = os.uname().sysname, os.uname().machine
    arm = machine in ("arm64", "aarch64")
    arch = ("darwin_arm64" if arm else "darwin_x64") if sysname == "Darwin" else ("linux_arm64" if arm else "linux_x64")
    e.serve_file("https://github.com/gitleaks/gitleaks/releases/download/v8.30.1/gitleaks_8.30.1_%s.tar.gz" % arch,
                 gitleaks_tgz())
    rc, out, _ = e.run("DEPS", "DEVTOOLS")
    assert rc == 0
    assert re.search(r"^  ! gradle: install failed", out, re.M) and re.search(r"^  ! gitleaks: install failed", out, re.M), out
    assert not (e.home / ".local" / "opt" / ("gradle-" + GRADLE_V)).exists()
    assert not (e.home / ".local" / "bin" / "gradle").exists() and not (e.home / ".local" / "bin" / "gitleaks").exists()


def test_devtools_install_lines(tmp_path):
    e = Env(tmp_path)
    e.brew(installed=["gitleaks"])
    e.present("node")
    e.shim("uv", '[ "$1 $2" = "tool install" ] && { printf "#!/bin/sh\\n" >"%s/pre-commit"; chmod +x "%s/pre-commit"; }; exit 0'
           % (e.bin, e.bin))
    pw = e.pw_dir()
    e.shim("npx", 'for d in chromium-{r} chromium_headless_shell-{r}; do mkdir -p "{pw}/$d"; : >"{pw}/$d/INSTALLATION_COMPLETE"; done'
           .format(r=PW_REV, pw=pw))
    gdir = e.home / ".local" / "opt" / ("gradle-" + GRADLE_V) / "bin"
    mkexe(gdir / "gradle", "exit 0")                       # unpacked by an earlier run: only the link is made
    rc, out, err = e.run("DEVTOOLS", PATH="%s:%s:/usr/bin:/bin" % (e.bin, e.home / ".local" / "bin"))
    assert rc == 0, err
    assert e.argv("uv", "tool install") == ["tool install --python 3.14 --exclude-newer 2026-09-26T00:00:00Z pre-commit==4.6.2"]
    assert re.search(r"-y playwright@\d+\.\d+\.\d+ install chromium chromium-headless-shell", e.argv("npx")[0])
    assert os.readlink(e.home / ".local" / "bin" / "gradle") == str(gdir / "gradle")
    for label in ("pre-commit", "gradle", "playwright browsers"):
        assert re.search(r"^  \+ %s \(" % label, out, re.M), out


# ---------------------------------------------------------------- modes and switches
def test_dry_run_and_report_run_nothing(tmp_path):
    e = Env(tmp_path)
    e.brew()
    for mode in ("dry-run", "report"):
        rc, out, err = e.run(*GROUPS, mode=mode, tty="1")
        assert rc == 0, err
        assert e.calls("brew", "install") == [] and e.calls("curl") == []
        assert [c for c in e.calls() if not c.startswith("brew ")] == [], e.calls()
        if mode == "dry-run":
            assert re.search(r"^  would: HOMEBREW_NO_ANALYTICS=1 HOMEBREW_NO_AUTO_UPDATE=1 brew install \S", out, re.M)
            assert re.search(r"^  would: HOMEBREW_NO_ANALYTICS=1 HOMEBREW_NO_AUTO_UPDATE=1 brew install --cask oracle-jdk", out, re.M)
            assert "would: rustup ← rustup installer (https://sh.rustup.rs" in out
        else:
            assert "! missing formulae:" in out
    assert not (e.home / ".local").exists() and not (e.home / ".zprofile").exists()


def test_all_groups_off(tmp_path):
    e = Env(tmp_path)
    e.brew()
    e.present("uv", "node", "npx")
    rc, out, _ = e.run()
    assert rc == 0
    assert lines(out) == ["  groups off: " + " ".join(GROUPS)]
    assert [c for c in e.calls() if not c.startswith("brew list ")] == []


# ---------------------------------------------------------------- stack-update-tools
def test_update_tools_dry_run_and_failure_isolation(tmp_path):
    e = Env(tmp_path)
    e.brew()
    e.shim("rustup", "exit 1")
    e.shim("juliaup")
    rc, out, _ = e.run(script=UPDATE, args=("--dry-run",))
    assert rc == 0 and e.calls() == []
    assert "would: homebrew: brew update && brew upgrade" in out and "would: rustup: rustup update" in out
    assert "- ghcup: absent" in out
    rc, out, _ = e.run(script=UPDATE, args=())
    assert rc == 1
    assert re.search(r"^  ! rustup failed: rustup update \(log \S+\)", out, re.M), out
    assert "ok  juliaup" in out and "ok  homebrew" in out
    assert e.argv("brew") == ["update", "upgrade"]


# ---------------------------------------------------------------- install.sh wiring
def test_install_sh_wires_modes_and_stops_on_required():
    text = (ROOT / "install.sh").read_text()
    assert re.search(r'if \[ "\$NO_DEPS" = 1 \]; then DT_MODE=report; elif \[ "\$DRY_RUN" = 1 \]; then DT_MODE=dry-run; '
                     r'else DT_MODE=install; fi', text)
    assert 'DEVTOOLS_MODE="$DT_MODE" DEVTOOLS_NO_PROFILE="$NO_PROFILE" bash "$HERE/lib/devtools.sh" all || dt_rc=$?' in text
    assert '[ "$dt_rc" = 3 ] && exit 1' in text
    # after the change-review question (R4), never before it
    assert text.index('say "2/11') < text.index('lib/devtools.sh" all')
    assert "stack-update-tools stack-budget stack-tree; do stage_script 755" in text and '"bin/stack-update-tools",' in text
    # no sudo call in the tool installer; every download HTTPS-only into a file (no curl | sh)
    code = "\n".join(l for l in SRC.splitlines() if not l.lstrip().startswith("#"))
    assert not re.search(r"(^|[;&|]\s*)sudo\b", code, re.M)
    assert not re.search(r"curl[^\n|]*\|\s*(ba|z)?sh\b", code)
    for m in re.finditer(r"\bcurl --[^\n]*", code):
        assert "--proto '=https' --tlsv1.2" in m.group(0), m.group(0)
