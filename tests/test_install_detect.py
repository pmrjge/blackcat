"""lib/devtools.sh: tools installed any other way than the installer's routes are found and skipped.

The system login PATH (path_helper), the known pkg dirs (/usr/local/go/bin, /Library/TeX/texbin,
/usr/local/texlive), the receipts database (pkgutil --pkgs, read once), app bundles in /Applications,
~/Applications, /Applications/Utilities and by Spotlight bundle id (mdfind), CLIs inside bundles and
symlinks into a bundle; the source on the skip line (brew | app | pkg | <manager>); MacTeX and Go from
their .pkg; gopls next to a non-Homebrew Go.

Hermetic: reuses test_install_devtools' Env (PATH shims, temp HOME); the system roots, path_helper,
pkgutil and mdfind are temp dirs and shims here.

Run: uv run --no-project --python 3.13 --with-requirements requirements/tools.txt pytest -q tests/test_install_detect.py
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_install_devtools import BREW_SHIM, SRC, UPDATE, Env, lines, mkexe  # noqa: E402

GOPLS_INFO = "==> gopls: stable 0.23.0 (bottled), HEAD"
BREW_EXTRA = r'''
case "$1" in
  deps) [ "$2" = gopls ] && [ -n "${BREW_GOPLS_DEPS:-}" ] && echo "$BREW_GOPLS_DEPS"; exit 0 ;;
  info) [ "$3" = gopls ] && [ -n "${BREW_GOPLS_INFO:-}" ] && echo "$BREW_GOPLS_INFO"; exit 0 ;;
esac
'''


class Sys:
    """The temp system roots Env.run points devtools.sh at, plus shims for path_helper, pkgutil, mdfind."""

    def __init__(self, e):
        self.e = e
        self.lib = e.t / "sys" / "Library"
        self.usr_local = e.t / "sys" / "usr-local"
        self.apps = e.t / "sys" / "Applications"
        for d in (self.lib, self.usr_local, self.apps):
            d.mkdir(parents=True, exist_ok=True)
        self.tools = e.t / "systools"
        self.tools.mkdir()
        self.env = {}

    def path_helper(self, *dirs):
        p = self.e.shim("path_helper", 'echo "PATH=[$PATH]" >>"$SHIM_LOG.ph"; '
                        'printf \'PATH="%s"; export PATH;\\n\' "' + ":".join(str(d) for d in dirs) + '"',
                        where=self.tools)
        self.env["DEVTOOLS_PATH_HELPER"] = str(p)

    def receipts(self, *ids):
        p = self.e.shim("pkgutil", '[ "$1" = --pkgs ] && printf "%s\\n" ' + " ".join(ids), where=self.tools)
        self.env["DEVTOOLS_PKGUTIL"] = str(p)

    def spotlight(self, bundle_id, app):
        p = self.e.shim("mdfind", 'case "$1" in *"\'%s\'"*) echo "%s" ;; esac' % (bundle_id, app), where=self.tools)
        self.env["DEVTOOLS_MDFIND"] = str(p)

    def brew(self, installed=(), **env):
        self.e.brew(installed=installed)
        self.e.shim("brew", BREW_EXTRA + BREW_SHIM)
        self.env.update(env)


def skips(out):
    return [l for l in lines(out) if l.startswith("  skip ")]


def setup(tmp_path):
    e = Env(tmp_path)
    e.present("uv", "node", "npx")
    return e, Sys(e)


# ---------------------------------------------------------------- the system login PATH
def test_path_helper_dirs_are_searched_and_never_written_to_a_profile(tmp_path):
    e, s = setup(tmp_path)
    s.brew()
    pathsd = tmp_path / "paths.d-dir"
    go = mkexe(pathsd / "go", "exit 0")
    s.path_helper(pathsd, tmp_path / "does-not-exist")
    rc, out, err = e.run("GO", **s.env)
    assert rc == 0, err
    assert "  skip go (found: %s, from PATH)" % go in lines(out), out
    assert [a.split()[1:] for a in e.argv("brew", "install")] == [["gopls"]]
    assert Path(str(e.log) + ".ph").read_text() == "PATH=[]\n"       # run with an empty PATH: the system part only
    assert not [p for p in e.home.iterdir() if p.name.startswith(".")]    # no profile written


# ---------------------------------------------------------------- .pkg installs: Go, MacTeX
def test_go_from_its_pkg_is_skipped_and_gopls_comes_from_the_bottle(tmp_path):
    e, s = setup(tmp_path)
    s.brew(BREW_GOPLS_INFO=GOPLS_INFO)
    go = mkexe(s.usr_local / "go" / "bin" / "go", 'echo "go $*" >>"$SHIM_LOG"')       # not on PATH
    s.receipts("com.apple.pkg.Core", "org.golang.go")
    rc, out, err = e.run("GO", **s.env)
    assert rc == 0, err
    assert "  skip go (found: %s, from pkg)" % go in lines(out), out
    assert e.argv("brew", "install") == ["install gopls"]
    assert "  gopls: Homebrew's bottle (go is only a build dependency of the formula; your go at %s stays the only go)" % go in out
    assert e.argv("brew", "deps") == ["deps gopls"]


def test_a_receipt_without_its_files_is_skipped_with_a_warning_never_reinstalled(tmp_path):
    e, s = setup(tmp_path)
    s.brew()
    s.receipts("org.golang.go")
    rc, out, err = e.run("GO", **s.env)
    assert rc == 0, err
    assert "  skip go (found: pkg receipt org.golang.go, from pkg)" in lines(out), out
    assert e.argv("brew", "install") == ["install gopls"]
    assert re.search(r"^  WARN go: the receipt org\.golang\.go is registered .*\(sudo pkgutil --forget org\.golang\.go\) and rerun", out, re.M)


def test_no_receipt_means_go_is_installed(tmp_path):
    e, s = setup(tmp_path)
    s.brew()
    s.receipts("org.tug.mactex.texlive2026", "com.oracle.jdk-27")
    rc, out, _ = e.run("GO", **s.env)
    assert e.argv("brew", "install") == ["install go gopls"], out


def test_mactex_from_its_pkg_is_skipped(tmp_path):
    e, s = setup(tmp_path)
    s.brew()
    real = mkexe(s.usr_local / "texlive" / "2026" / "bin" / "universal-darwin" / "pdflatex", "exit 0")
    texbin = s.lib / "TeX" / "texbin"
    texbin.mkdir(parents=True)
    (texbin / "pdflatex").symlink_to(real)
    s.receipts("org.tug.mactex.gui2026", "org.tug.mactex.texlive2026")
    rc, out, err = e.run("LATEX", tty="1", DEVTOOLS_TEX_BIN="", **s.env)
    assert rc == 0, err
    assert "  skip mactex (found: %s, from pkg)" % (texbin / "pdflatex") in lines(out), out
    assert e.calls("brew", "install") == []


def test_mactex_receipt_alone_still_means_no_cask(tmp_path):
    e, s = setup(tmp_path)
    s.brew()
    s.receipts("org.tug.mactex.basictex2026")
    rc, out, _ = e.run("LATEX", tty="1", DEVTOOLS_TEX_BIN="", **s.env)
    assert e.calls("brew", "install") == [], out
    assert "  skip mactex (found: pkg receipt org.tug.mactex.basictex2026, from pkg)" in lines(out)


def test_the_receipts_are_listed_once_per_run(tmp_path):
    e, s = setup(tmp_path)
    s.brew()
    mkexe(s.usr_local / "go" / "bin" / "go", "exit 0")
    s.receipts("org.golang.go", "org.tug.mactex.texlive2026")
    rc, out, _ = e.run("GO", "LATEX", "CXX", "POSTGRES", tty="1", DEVTOOLS_TEX_BIN="", **s.env)
    assert rc == 0
    assert e.argv("pkgutil") == ["--pkgs"], e.argv("pkgutil")


# ---------------------------------------------------------------- apps (.dmg / .app)
def test_clis_inside_app_bundles_are_found_in_all_three_app_dirs(tmp_path):
    e, s = setup(tmp_path)
    s.brew()
    psql = mkexe(s.apps / "Postgres.app" / "Contents" / "Versions" / "18" / "bin" / "psql", "exit 0")
    julia = mkexe(e.home / "Applications" / "Julia-1.13.app" / "Contents" / "Resources" / "julia" / "bin" / "julia", "exit 0")
    cmake = mkexe(s.apps / "Utilities" / "CMake.app" / "Contents" / "bin" / "cmake", "exit 0")
    rc, out, err = e.run("POSTGRES", "JULIA", "CXX", **s.env)
    assert rc == 0, err
    got = lines(out)
    assert "  skip postgresql@18 (found: %s, from app)" % psql in got, out
    assert "  skip juliaup (found: %s, from app)" % julia in got                # the manager: a tool it provides
    assert "  skip cmake (found: %s, from app)" % cmake in got
    assert "postgresql@18" not in " ".join(e.argv("brew", "install")) and "cmake " not in " ".join(e.argv("brew", "install")) + " "
    assert e.calls("curl") == []


def test_an_app_elsewhere_is_found_by_its_bundle_id(tmp_path):
    e, s = setup(tmp_path)
    s.brew()
    app = tmp_path / "Volumes" / "Postgres.app"
    psql = mkexe(app / "Contents" / "Versions" / "17" / "bin" / "postgres", "exit 0")
    s.spotlight("com.postgresapp.Postgres2", app)
    rc, out, err = e.run("POSTGRES", **s.env)
    assert rc == 0, err
    assert "  skip postgresql@18 (found: %s, from app)" % psql in lines(out), out
    assert e.argv("mdfind") == ["kMDItemCFBundleIdentifier == 'com.postgresapp.Postgres2'"]
    assert e.calls("brew", "install") == []


def test_a_symlink_into_an_app_bundle_counts_as_the_app_and_a_cellar_link_as_brew(tmp_path):
    e, s = setup(tmp_path)
    s.brew()
    real = mkexe(tmp_path / "Somewhere" / "CMake.app" / "Contents" / "bin" / "cmake", "exit 0")
    (e.bin / "cmake").symlink_to(real)
    nin = mkexe(tmp_path / "Cellar" / "ninja" / "1.13" / "bin" / "ninja", "exit 0")
    (e.bin / "ninja").symlink_to(nin)
    rc, out, _ = e.run("CXX", **s.env)
    assert "  skip cmake (found: %s/cmake, from app)" % e.bin in lines(out), out
    assert "  skip ninja (found: %s/ninja, from brew)" % e.bin in lines(out), out


def test_a_spotlight_hit_in_an_agent_writable_folder_does_not_count(tmp_path):
    e, s = setup(tmp_path)
    s.brew()
    app = e.home / "ZDone" / "proj" / "Postgres.app"                   # a project folder sandboxed agents can write
    mkexe(app / "Contents" / "Versions" / "17" / "bin" / "postgres", "exit 0")
    s.spotlight("com.postgresapp.Postgres2", app)
    rc, out, err = e.run("POSTGRES", **s.env)
    assert rc == 0, err
    assert e.argv("mdfind"), "Spotlight was asked"
    assert e.argv("brew", "install") == ["install postgresql@18"], out
    assert not skips(out), out


def test_a_spotlight_hit_in_your_applications_folder_counts(tmp_path):
    e, s = setup(tmp_path)
    s.brew()
    app = e.home / "Applications" / "Databases" / "Postgres.app"      # below ~/Applications: the directory check misses it
    psql = mkexe(app / "Contents" / "Versions" / "17" / "bin" / "postgres", "exit 0")
    s.spotlight("com.postgresapp.Postgres2", app)
    rc, out, _ = e.run("POSTGRES", **s.env)
    assert "  skip postgresql@18 (found: %s, from app)" % psql in lines(out), out
    assert e.calls("brew", "install") == []


def test_mdfind_failing_or_absent_is_silent(tmp_path):
    e, s = setup(tmp_path)
    s.brew()
    s.env["DEVTOOLS_MDFIND"] = str(e.shim("mdfind", "echo boom >&2; exit 1", where=s.tools))
    rc, out, err = e.run("POSTGRES", **s.env)
    assert rc == 0 and "boom" not in out + err
    assert e.argv("brew", "install") == ["install postgresql@18"]


def test_the_lookup_never_uses_system_profiler_or_lsregister():
    code = "\n".join(l for l in SRC.splitlines() if not l.lstrip().startswith("#"))
    assert "system_profiler" not in code and "lsregister" not in code


# ---------------------------------------------------------------- gopls next to a non-Homebrew Go
def go_pkg(e, s):
    """A stand-in for the Go .pkg's go: `go env GOBIN` prints $GOBIN, else FAKE_GO_ENV_GOBIN (a `go env -w`
    value); `go install` writes gopls where go would ($GOBIN, else ~/go/bin) and logs the caches it saw."""
    return mkexe(s.usr_local / "go" / "bin" / "go",
                 'echo "go $*" >>"$SHIM_LOG"\n'
                 'case "$1" in env) [ "$2" = GOBIN ] && echo "${GOBIN:-${FAKE_GO_ENV_GOBIN:-}}"; exit 0 ;; install) ;; *) exit 0 ;; esac\n'
                 'echo "GOMODCACHE=${GOMODCACHE-unset} GOCACHE=${GOCACHE-unset}" >>"$SHIM_LOG.go"\n'
                 'd="${GOBIN:-$HOME/go/bin}"; mkdir -p "$d" && printf "#!/bin/sh\\n" >"$d/gopls" && chmod +x "$d/gopls"')


def test_gopls_comes_from_go_install_when_the_formula_would_pull_in_homebrews_go(tmp_path):
    e, s = setup(tmp_path)
    s.brew(BREW_GOPLS_INFO=GOPLS_INFO, BREW_GOPLS_DEPS="go")
    go = go_pkg(e, s)
    s.receipts("org.golang.go")
    sandbox = e.home / ".cache" / "claude-sandbox"
    rc, out, err = e.run("GO", GOMODCACHE=str(sandbox / "go" / "mod"), GOCACHE=str(sandbox / "go" / "build"), **s.env)
    assert rc == 0, err
    assert e.calls("brew", "install") == [], out
    assert e.argv("go") == ["env GOBIN", "install golang.org/x/tools/gopls@v0.23.0"]
    assert "  gopls: Homebrew's formula would bring in Homebrew's go; gopls comes from go install with your go (%s)" % go in out
    assert re.search(r"^  \+ gopls \(%s install golang\.org/x/tools/gopls@v0\.23\.0 " % re.escape(str(go)), out, re.M), out
    # no GOBIN anywhere: ~/.local/bin (on PATH), not go's ~/go/bin; the sandbox's caches never reach go
    assert (e.home / ".local" / "bin" / "gopls").is_file() and not (e.home / "go").exists()
    assert Path(str(e.log) + ".go").read_text() == "GOMODCACHE=unset GOCACHE=unset\n"


def test_gopls_from_go_install_goes_to_your_gobin(tmp_path):
    e, s = setup(tmp_path)
    s.brew(BREW_GOPLS_INFO=GOPLS_INFO, BREW_GOPLS_DEPS="go")
    go_pkg(e, s)
    s.receipts("org.golang.go")
    mine = e.home / "bin-go"                                   # `go env -w GOBIN=...`, on the user's PATH
    rc, out, err = e.run("GO", FAKE_GO_ENV_GOBIN=str(mine), PATH="%s:%s:/usr/bin:/bin" % (e.bin, mine), **s.env)
    assert rc == 0, err
    assert re.search(r"^  \+ gopls \(", out, re.M), out
    assert (mine / "gopls").is_file() and not (e.home / ".local" / "bin" / "gopls").exists()


def test_gopls_without_a_bottle_for_this_macos_also_goes_through_go_install(tmp_path):
    e, s = setup(tmp_path)
    s.brew(BREW_GOPLS_INFO="==> gopls: stable 0.23.0, HEAD")
    go_pkg(e, s)
    rc, out, _ = e.run("GO", mode="dry-run", **s.env)
    assert e.calls("go") == [] and e.calls("brew", "install") == []
    assert "would: gopls ← %s install golang.org/x/tools/gopls@v0.23.0" % (s.usr_local / "go" / "bin" / "go") in out, out


def test_homebrews_own_go_keeps_the_brew_gopls(tmp_path):
    e, s = setup(tmp_path)
    s.brew(BREW_GOPLS_INFO="==> gopls: stable 0.23.0, HEAD", BREW_GOPLS_DEPS="go")
    real = mkexe(tmp_path / "Cellar" / "go" / "1.26" / "bin" / "go", "exit 0")
    (e.bin / "go").symlink_to(real)
    rc, out, _ = e.run("GO", **s.env)
    assert e.argv("brew", "install") == ["install gopls"] and e.calls("brew", "deps") == []


# ---------------------------------------------------------------- stack-update-tools, docs
def test_stack_update_tools_leaves_pkg_mactex_and_go_to_you(tmp_path):
    t = UPDATE.read_text()
    assert "sudo tlmgr" not in t and "tlmgr update" not in t                  # never runs tlmgr, let alone with sudo
    want = "  manual  mactex/go: installed by pkg, update with tlmgr / the Go installer"
    e, s = setup(tmp_path)
    e.brew()
    rc, out, _ = e.run(script=UPDATE, args=("--dry-run",))                   # temp roots: neither is there
    assert want not in out, out
    for d in (s.lib / "TeX" / "texbin", s.usr_local / "go" / "bin"):
        d.mkdir(parents=True)
        rc, out, _ = e.run(script=UPDATE, args=("--dry-run",))
        assert want in lines(out), (d, out)
        d.rmdir()


def test_the_detection_table_names_only_evidenced_entries():
    rows = re.search(r'^DETECT_ROWS="(.*?)"$', SRC, re.M | re.S).group(1).splitlines()
    names = [r.split("|")[0] for r in rows]
    assert names == ["go", "mactex", "jdk", "cmake", "julia", "postgres"]
    assert all(len(r.split("|")) == 7 for r in rows)
    assert "org.golang.go" in rows[0] and "org.tug.mactex.texlive*" in rows[1]


# ---------------------------------------------------------------- review items 4 and 6
def test_a_user_level_jdk_means_no_oracle_jdk_cask(tmp_path):
    e, s = setup(tmp_path)
    s.brew()
    e.present("kotlin-lsp")
    home = e.home / "Library" / "Java" / "JavaVirtualMachines" / "openjdk-27" / "Contents" / "Home"
    home.mkdir(parents=True)
    (home / "release").write_text('JAVA_VERSION="27.0.1"\n')
    rc, out, err = e.run("JAVA", tty="1", **s.env)
    assert rc == 0, err
    assert e.calls("brew", "install") == [], out
    assert "  skip oracle-jdk (found: %s, from ~/Library/Java)" % home in lines(out)


def test_an_older_user_level_jdk_is_left_alone_with_a_warning(tmp_path):
    e, s = setup(tmp_path)
    s.brew()
    e.present("kotlin-lsp")
    home = e.home / "Library" / "Java" / "JavaVirtualMachines" / "openjdk-21" / "Contents" / "Home"
    home.mkdir(parents=True)
    (home / "release").write_text('JAVA_VERSION="21.0.4"\n')
    rc, out, _ = e.run("JAVA", tty="1", **s.env)
    assert e.calls("brew", "install") == [], out
    assert "  skip oracle-jdk (found: %s, from ~/Library/Java)" % home in lines(out)
    assert "  WARN oracle-jdk: JDK 21 at %s is older than the 27 the stack targets; left alone." % home in out


def jdk(root, version):
    root.mkdir(parents=True)
    (root / "release").write_text('JAVA_VERSION="%s"\n' % version)
    return root


def test_jdks_outside_the_two_dirs_count_and_the_newest_one_is_named(tmp_path):
    e, s = setup(tmp_path)
    s.brew()
    e.present("kotlin-lsp")
    jdk(e.jvm / "zulu-8.jdk" / "Contents" / "Home", "1.8.0_392")                       # Java 8: major 8
    sdk = jdk(e.home / ".sdkman" / "candidates" / "java" / "27.0.1-tem", "27.0.1")
    rc, out, _ = e.run("JAVA", tty="1", **s.env)
    assert e.calls("brew", "install") == [] and "WARN" not in out, out
    assert "  skip oracle-jdk (found: %s, from sdkman)" % sdk in lines(out)


def test_java_8_alone_counts_as_8(tmp_path):
    e, s = setup(tmp_path)
    s.brew()
    e.present("kotlin-lsp")
    home = jdk(e.jvm / "zulu-8.jdk" / "Contents" / "Home", "1.8.0_392")
    rc, out, _ = e.run("JAVA", tty="1", **s.env)
    assert e.calls("brew", "install") == [], out
    assert "  WARN oracle-jdk: JDK 8 at %s is older than the 27" % home in out, out


def test_java_home_and_homebrews_openjdk_count(tmp_path):
    for where in ("java_home", "brew"):
        (tmp_path / where).mkdir()
        e, s = setup(tmp_path / where)
        s.brew()                                       # brew shim in e.bin: the Homebrew prefix is e.t
        e.present("kotlin-lsp")
        if where == "java_home":
            home = jdk(e.t / "custom-jdk", "25.0.2")
            extra = {"JAVA_HOME": str(home)}
        else:
            home = jdk(e.t / "opt" / "openjdk@25" / "libexec" / "openjdk.jdk" / "Contents" / "Home", "25")
            extra = {}
        rc, out, _ = e.run("JAVA", tty="1", **s.env, **extra)
        assert e.calls("brew", "install") == [], (where, out)
        assert "  WARN oracle-jdk: JDK 25 at %s is older than the 27" % home in out, (where, out)


def test_no_jdk_anywhere_still_gets_the_cask(tmp_path):
    e, s = setup(tmp_path)
    s.brew()
    e.present("kotlin-lsp", "java")                    # /usr/bin/java-like stub: not a JDK
    rc, out, _ = e.run("JAVA", tty="1", **s.env)
    assert e.argv("brew", "install") == ["install --cask oracle-jdk"], out


def test_pnpm_is_never_run_in_dry_run_or_report(tmp_path):
    e, s = setup(tmp_path)
    pnpm = e.shim("pnpm")
    for mode in ("dry-run", "report"):
        rc, out, err = e.run("NODE", mode=mode, **s.env)
        assert rc == 0, err
        assert e.calls("pnpm") == [], (mode, e.calls("pnpm"))
        assert "  skip pnpm (corepack) (found: %s, from PATH)" % pnpm in lines(out), out
    rc, out, _ = e.run("NODE", **s.env)
    assert e.argv("pnpm") == ["--version"]                                 # version_warn, real run only


# ---------------------------------------------------------------- elan: Homebrew's elan-init first
ELAN_FAKE = r'''
case "$1 $2" in
  "toolchain list") [ -f "$ELAN_TC" ] && cat "$ELAN_TC" || echo "no installed toolchains" ;;
  "toolchain install") echo "leanprover/lean4:v4.99.0" >"$ELAN_TC" ;;
esac
exit 0
'''
BREW_ELAN = r'''
if [ "$1" = install ]; then for n in "$@"; do [ "$n" = elan-init ] && cp "$ELAN_SRC" "$SHIM_DIR/elan"; done; fi
'''


def elan_brew(e, s):
    s.brew()
    src = mkexe(e.t / "elan-src", LOGGER_ELAN + ELAN_FAKE)
    e.shim("brew", BREW_ELAN + BREW_EXTRA + BREW_SHIM)
    s.env.update(ELAN_SRC=str(src), SHIM_DIR=str(e.bin), ELAN_TC=str(e.t / "elan-tc"), DEVTOOLS_NOFILE="65536")


LOGGER_ELAN = 'echo "elan $*" >>"$SHIM_LOG"\n'


def test_elan_comes_from_homebrews_elan_init_and_gets_the_stable_toolchain(tmp_path):
    e, s = setup(tmp_path)
    elan_brew(e, s)
    rc, out, err = e.run("LEAN", STACK_INSTALL_LEAN_MATHLIB="0", **s.env)
    assert rc == 0, err
    assert e.argv("brew", "install") == ["install elan-init"], out
    assert e.calls("curl") == []                                            # never the elan-init.sh route
    assert "  + elan (brew)" in lines(out)
    assert e.argv("elan") == ["toolchain list", "toolchain install leanprover/lean4:stable",
                              "default leanprover/lean4:stable", "toolchain list"], e.argv("elan")
    assert re.search(r"^  \+ lean toolchain \(stable\) \(elan toolchain install leanprover/lean4:stable", out, re.M), out


def test_elan_found_anywhere_means_no_elan_init_and_no_toolchain_step(tmp_path):
    e, s = setup(tmp_path)
    elan_brew(e, s)
    lake = mkexe(e.home / ".elan" / "bin" / "lake", "exit 0")
    rc, out, _ = e.run("LEAN", STACK_INSTALL_LEAN_MATHLIB="0", **s.env)
    assert e.calls("brew", "install") == [] and e.calls("elan") == []
    assert "  skip elan (found: %s, from elan)" % lake in lines(out), out
    assert sum(1 for l in lines(out) if l.startswith("  skip elan ")) == 1


def test_without_homebrew_the_official_elan_installer_is_the_fallback(tmp_path):
    e, s = setup(tmp_path)
    rc, out, _ = e.run("LEAN", mode="dry-run", DEVTOOLS_NOFILE="65536", **s.env)
    assert "would: elan ← elan installer (https://elan.lean-lang.org/elan-init.sh, latest; no Homebrew)" in out, out
    assert "no Homebrew, not installed" not in out


def test_elan_init_dry_run_and_the_open_file_limit(tmp_path):
    e, s = setup(tmp_path)
    elan_brew(e, s)
    rc, out, _ = e.run("LEAN", mode="dry-run", **s.env)
    assert "would: HOMEBREW_NO_ANALYTICS=1 HOMEBREW_NO_AUTO_UPDATE=1 brew install elan-init" in out
    assert "would: lean toolchain (stable) ← elan toolchain install leanprover/lean4:stable" in out
    assert e.calls("brew", "install") == [] and e.calls("elan") == []
    s.env["DEVTOOLS_NOFILE"] = "256"
    rc, out, _ = e.run("LEAN", **s.env)
    assert e.calls("brew", "install") == [] and "! lean skipped: the open-file limit is 256" in out


# ---------------------------------------------------------------- stack-update-tools: Homebrew's elan
def brew_elan_link(e, prefix):
    """PREFIX/bin/elan -> ../Cellar/elan-init/4.2.4/bin/elan -> elan-init, as the formula links it;
    the shim dir's elan points at PREFIX/bin/elan (a second hop)."""
    cbin = prefix / "Cellar" / "elan-init" / "4.2.4" / "bin"
    e.shim("elan-init", where=cbin)
    (cbin / "elan").symlink_to("elan-init")
    (prefix / "bin").mkdir(parents=True)
    (prefix / "bin" / "elan").symlink_to("../Cellar/elan-init/4.2.4/bin/elan")
    (e.bin / "elan").symlink_to(prefix / "bin" / "elan")


def test_update_tools_skips_self_update_for_homebrews_elan_on_both_prefixes(tmp_path):
    for prefix in ("usr-local", "opt-homebrew"):                  # Intel /usr/local, Apple Silicon /opt/homebrew
        (tmp_path / prefix).mkdir()
        e = Env(tmp_path / prefix)
        e.brew()                                                  # never the real brew on /opt/homebrew/bin
        brew_elan_link(e, tmp_path / prefix / "root")
        rc, out, err = e.run(script=UPDATE, args=())
        assert "  - elan self update: elan is Homebrew's (brew upgrade covers it)" in out, (prefix, out)
        assert e.argv("elan") == ["update"], (prefix, e.argv("elan"))     # the shim logs the name it was run as


def test_update_tools_self_updates_an_elan_from_its_own_installer(tmp_path):
    e = Env(tmp_path)
    e.brew()
    e.shim("elan", where=e.home / ".elan" / "bin")
    rc, out, _ = e.run(script=UPDATE, args=())
    assert e.argv("elan") == ["self update", "update"], out
    assert "ok  elan self update" in out


def test_update_tools_homebrew_uv_is_resolved_too(tmp_path):
    e = Env(tmp_path)
    e.brew()
    cbin = tmp_path / "root" / "Cellar" / "uv" / "0.12.20" / "bin"
    e.shim("uv", where=cbin)
    (e.bin / "uv").symlink_to(cbin / "uv")
    rc, out, _ = e.run(script=UPDATE, args=())
    assert "  - uv self update: uv is Homebrew's (brew upgrade covers it)" in out
    # no self update; then the hooks' Python (S2): uv's 3.13 upgraded, bin/stack-python's target looked up
    assert e.argv("uv") == ["tool upgrade --all", "python upgrade 3.13", "python dir",
                            "python find --system --managed-python --no-project --no-config 3.13"]


def test_unverified_entries_are_marked_and_config_lists_the_lookup_order():
    note = SRC[SRC.index("# UNVERIFIED on a real install"):SRC.index('DETECT_ROWS="')]
    for x in ("org.tug.mactex.basictex*", "net.temurin.*.jdk", "com.postgresapp.Postgres2", "Julia-*.app"):
        assert x in note, x
    cfg = (Path(__file__).resolve().parent.parent / "CONFIG.md").read_text()
    para = cfg[cfg.index("**The skip rule (2026-10-04)"):cfg.index("A manager is skipped when a")]
    order = ["(1) PATH", "(2) the system login PATH", "(3) the known locations", "(4) for the tools in `DETECT_ROWS`",
             "(5) their .pkg receipts", "(6) `brew list"]
    assert [para.index(o) for o in order] == sorted(para.index(o) for o in order)


# ---------------------------------------------------------------- dry-run / report write nothing under HOME
BREW_MKCACHE = r'''
mkdir -p "${HOMEBREW_CACHE:-$HOME/Library/Caches/Homebrew}" "${HOMEBREW_LOGS:-$HOME/Library/Logs/Homebrew}"
echo "cache=${HOMEBREW_CACHE:-default}" >>"$SHIM_LOG.cache"
'''


def tree(p):
    return sorted(str(x.relative_to(p)) for x in p.rglob("*"))


def test_dry_run_and_report_leave_homebrews_cache_out_of_a_fresh_home(tmp_path):
    e, s = setup(tmp_path)
    s.brew()
    e.shim("brew", BREW_MKCACHE + BREW_SHIM)
    before = tree(e.home)
    for mode in ("dry-run", "report"):
        rc, out, err = e.run("GO", "CXX", mode=mode, **s.env)
        assert rc == 0, err
        assert tree(e.home) == before, (mode, tree(e.home))
    assert e.calls("brew", "list")                                         # brew did run
    assert not list(e.tmp.glob("stack-devtools-cwd.*"))                    # the throw-away cache went with the run


def test_an_existing_homebrew_cache_is_used_as_it_is(tmp_path):
    e, s = setup(tmp_path)
    s.brew()
    e.shim("brew", BREW_MKCACHE + BREW_SHIM)
    (e.home / "Library" / "Caches" / "Homebrew").mkdir(parents=True)
    (e.home / "Library" / "Logs" / "Homebrew").mkdir(parents=True)
    rc, out, _ = e.run("GO", mode="dry-run", **s.env)
    assert set(Path(str(e.log) + ".cache").read_text().split()) == {"cache=default"}


# ---------------------------------------------------------------- review: no Homebrew, one line per tool
def test_without_homebrew_jq_gitleaks_elan_get_one_skip_line_and_the_misses_are_counted(tmp_path):
    e, s = setup(tmp_path)
    e.present("jq", "gitleaks", "elan")
    rc, out, _ = e.run("DEPS", "DEVTOOLS", "LEAN", "CXX", mode="dry-run", DEVTOOLS_NOFILE="65536",
                       STACK_INSTALL_LEAN_MATHLIB="0", **s.env)
    for tool in ("jq", "gitleaks", "elan"):
        assert sum(1 for l in lines(out) if l.startswith("  skip %s (" % tool)) == 1, (tool, out)
    nobrew = re.search(r"^  ! no Homebrew, not installed:(.*) \(install Homebrew, then rerun\)$", out, re.M)
    assert nobrew, out
    names = nobrew.group(1).split()
    assert "jq" not in names and "gitleaks" not in names and "elan-init" not in names
    m = re.search(r"summary: \d+ would be installed, (\d+) skipped \(already there\), (\d+) not installable here", out)
    assert m and int(m.group(2)) >= len(names), out
    assert int(m.group(1)) == sum(1 for l in lines(out) if l.startswith("  skip "))


# ---------------------------------------------------------------- review: a ghc without ghcup, rust without rustup
def test_a_ghc_without_ghcup_gets_the_hlint_command_not_a_failed_install(tmp_path):
    e, s = setup(tmp_path)
    ghc = e.shim("ghc")
    e.present("ormolu")
    rc, out, err = e.run("HASKELL", **s.env)
    assert rc == 0, err
    assert "  skip ghcup (found: %s, from PATH)" % ghc in lines(out)
    assert "hlint: install failed" not in out and e.calls("ghcup") == [] and e.calls("cabal") == [], out
    assert "  ! hlint missing — hlint 3.10 needs GHC 9.12.4 and your ghc is not ghcup's: cabal install" in out
    assert re.search(r"summary: 0 installed, \d+ skipped \(already there\), 0 failed, 1 not installed", out), out


def test_rust_analyzer_hints_name_rustup_only_when_it_is_there():
    t = (Path(__file__).resolve().parent.parent / "install.sh").read_text()
    block = t[t.index("# rustup's rust-analyzer proxy without the component"):t.index("# Servers for the stack's other languages")]
    assert 'if have rustup; then ra_fix="rustup component add rust-analyzer"' in block
    assert 'else note "! rust-analyzer: no rustup here (a Rust from Homebrew or elsewhere): brew install rust-analyzer"; fi' in block


# ---------------------------------------------------------------- review: found-but-broken pnpm, no runs in dry-run
def test_a_pnpm_that_fails_gets_a_warn_and_corepack_is_never_run(tmp_path):
    e, s = setup(tmp_path)
    pnpm = e.shim("pnpm", "exit 1")
    e.shim("corepack")
    rc, out, err = e.run("NODE", **s.env)
    assert rc == 0, err
    assert e.calls("corepack") == [], e.calls("corepack")
    assert "  WARN pnpm (corepack) at %s fails 'pnpm --version'; the installer leaves it alone." % pnpm in out, out


FOUND_TOOLS = ("juliaup", "rustup", "ghcup", "hlint", "ormolu", "elan", "pre-commit", "gradle", "pnpm")


def test_dry_run_and_report_execute_no_found_tool(tmp_path):
    e, s = setup(tmp_path)
    for t in FOUND_TOOLS:
        e.shim(t)
    for mode in ("dry-run", "report"):
        e.log.write_text("")
        rc, out, err = e.run("JULIA", "RUST", "HASKELL", "LEAN", "DEVTOOLS", "NODE", mode=mode,
                             DEVTOOLS_NOFILE="65536", STACK_INSTALL_LEAN_MATHLIB="0", **s.env)
        assert rc == 0, err
        ran = [c for c in e.calls() if c.split()[0] in FOUND_TOOLS]
        assert ran == [], (mode, ran)


# ---------------------------------------------------------------- review: tests that pin the lookup itself
def test_system_dirs_are_searched_from_a_brew_item(tmp_path):
    """A brew item's cmd: probe runs under item_present's IFS=,: the system dirs must still split on spaces."""
    e, s = setup(tmp_path)
    s.brew()
    a, b = tmp_path / "sysa", tmp_path / "sysb"
    a.mkdir()
    rg = mkexe(b / "rg", "exit 0")
    rc, out, _ = e.run("DEPS", DEVTOOLS_SYSTEM_DIRS="%s %s" % (a, b), **s.env)
    assert "  skip ripgrep (found: %s, from PATH)" % rg in lines(out), out
    assert "ripgrep" not in " ".join(e.argv("brew", "install"))


def test_a_link_into_the_go_pkg_dir_counts_as_pkg(tmp_path):
    e, s = setup(tmp_path)
    s.brew()
    go = mkexe(s.usr_local / "go" / "bin" / "go", "exit 0")
    (e.bin / "go").symlink_to(go)
    s.receipts("org.golang.go")
    rc, out, _ = e.run("GO", **s.env)
    assert "  skip go (found: %s/go, from pkg)" % e.bin in lines(out), out
