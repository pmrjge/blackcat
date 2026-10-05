#!/usr/bin/env bash
# install.sh's tool installer (step 2): the prerequisites the stack needs and the toolchains its
# agents run. You run it (through ./install.sh) in a terminal, outside the sandbox; bash 3.2. It
# never calls sudo itself (Homebrew's installer and the pkg casks ask for your password on their own).
#
#   devtools.sh all        every enabled group, in this order:
#     1. Homebrew          bootstrap when missing, only on a terminal (it prompts) [STACK_INSTALL_DEPS]
#     2. Homebrew batch    every MISSING formula of the enabled groups in ONE `brew install`, every
#                          missing cask in ONE `brew install --cask` (on a terminal only: the pkg casks
#                          ask for a password); each name checked with `brew info` first (an
#                          unresolved one is reported and left out); a failed batch is retried name by
#                          name. elan comes from here too (the elan-init formula, a sha256-pinned bottle)
#     3. upstream managers uv (+ Python 3.14 global pin), nvm (+ node 24, pnpm via corepack), rustup,
#                          ghcup (+ hlint, ormolu), juliaup, coursier, and elan only without Homebrew:
#                          each through its official installer (HTTPS only, into a temp file, URL and
#                          sha256 logged, then run); Homebrew's fresh elan gets the stable toolchain
#     4. required check    uv, node + npx: still missing -> one message listing them, exit 3
#     5. the rest          the Mathlib project (~/lean/stack_mathlib unless LEAN_PROJECT_PATH names
#                          one), pre-commit, Gradle, Playwright's browsers, `git lfs install`
#
# Groups (environment; =0 skips one, =1 turns on an off-by-default one):
#   STACK_INSTALL_DEPS      1  Homebrew itself; jq rg gh ffmpeg imagemagick librsvg poppler just; the uv
#                              tarball and jq/gitleaks binary fallbacks
#   STACK_INSTALL_DEVTOOLS  1  gitleaks, pre-commit, Gradle, Playwright's Chromium
#   STACK_INSTALL_UV NODE RUST HASKELL JULIA SCALA JAVA LATEX CXX GO  1 each
#   STACK_INSTALL_LEAN      1  elan (stable toolchain) and the Mathlib project; skipped while the
#                              open-file limit (ulimit -Sn, raised by install.sh first) is below 65536
#   STACK_INSTALL_LEAN_MATHLIB  auto: the Mathlib project (about 8 GB) only on a terminal; 1 also
#                              without one; 0 never (the commands are printed)
#   STACK_INSTALL_LSP       0  jdtls (Homebrew's formula: it brings Homebrew's openjdk, keg-only, and
#                              python@3.14); install.sh --with-lsp turns it on
#   STACK_INSTALL_POSTGRES MONGODB                                     0 each
# DEVTOOLS_MODE: install (default) | dry-run (print what a real run would do, run nothing) |
# report (--no-deps: list what is missing, install nothing, never fail).
# DEVTOOLS_LEAN_PROJECT: install.sh's LEAN_PROJECT_PATH (stack.env, else the environment); a project
# there is used as it is. DEVTOOLS_NOFILE (tests): the open-file limit instead of `ulimit -Sn`.
# DEVTOOLS_NO_PROFILE=1 (install.sh --no-profile): installers are told not to edit shell profiles
# where they have a switch for it.
# THE SKIP RULE: every command is looked up first, from any source, in this order: PATH, plus the
# system login PATH (`path_helper -s`: /etc/paths, /etc/paths.d/*, where the Go and MacTeX .pkgs
# register /usr/local/go/bin and /Library/TeX/texbin; this process only, never your profile); the
# known bin dirs (~/.local/bin ~/.cargo/bin ~/.ghcup/bin ~/.cabal/bin ~/.elan/bin ~/.juliaup/bin,
# Coursier's, ~/go/bin, mise/asdf/nix shims, ~/.nvm/versions/node/*/bin, /opt/homebrew/bin
# /usr/local/bin /opt/local/bin, /usr/local/go/bin, /Library/TeX/texbin, /usr/local/texlive/*/bin/*);
# brew list; for the tools in DETECT_ROWS their apps (/Applications, ~/Applications,
# /Applications/Utilities, then Spotlight by bundle id, never a hit elsewhere under HOME; CLIs inside
# the bundle) and their .pkg receipts
# (`pkgutil --pkgs`, read once); the JDK, TeX and Playwright paths. Found = "skip <tool> (found:
# <path>, from brew|app|pkg|<manager>|macOS|PATH)": never installed, upgraded, replaced or removed.
# A found tool that fails `--version` (or a receipt whose files are gone) gets a WARN line with the
# fix to run yourself. A manager counts as found when a tool it provides is (rustup: cargo/rustc; ghcup: ghc;
# juliaup: julia; elan: lake/lean; nvm + node 24: any node). Configuration (uv's Python pin, git
# lfs filters, the brew shellenv line) is not an install: "ok" when set, set when not. Other lines:
# "+" installed, "!" missing or failed (with the log and the command); a summary line at the end.
# DEVTOOLS_SYSTEM_DIRS (tests: "") replaces the system dirs in the lookup (/opt/homebrew/bin /usr/local/bin
# /opt/local/bin and the nix profiles).
set -u
# Never in the caller's directory: install.sh starts here from the stack repo, which sandboxed agents
# can write, and npx/npm exec prefer a matching package in ./node_modules (its .bin would run outside
# the sandbox), npm, corepack and uv read .npmrc, package.json, uv.toml from cwd and its parents, and
# `git lfs install` inside a repository adds hooks there. So the run moves into a fresh private empty
# directory (not /: macOS's bash 3.2 then can't create here-document temp files). Every path below is
# absolute.
DT_CWD="$(mktemp -d "${TMPDIR:-/tmp}/stack-devtools-cwd.XXXXXX")" && cd "$DT_CWD" || exit 2
# Run from a Claude Code Bash command, the environment carries the sandbox's cache dirs (agent_guard
# SANDBOX_ENV: CARGO_HOME, UV_CACHE_DIR, GOMODCACHE, npm_config_cache, ...), which sandboxed agents
# can write: nothing installed here may build from or land in them (security audit, CWE-427).
for v in $(compgen -e); do
  [ "$v" = PATH ] || case "${!v}" in *"$HOME/.cache/claude-sandbox"*) unset "$v" ;; esac
done

MODE="${DEVTOOLS_MODE:-install}"
case "$MODE" in install|dry-run|report) ;; *) echo "devtools.sh: DEVTOOLS_MODE must be install, dry-run or report" >&2; exit 2 ;; esac
NO_PROFILE="${DEVTOOLS_NO_PROFILE:-0}"
# stdin is a terminal (Homebrew's installer and the cask batch need one); the tests set it
# A variable can only take the terminal away (DEVTOOLS_TTY=0: install.sh --no-prompt), never stand
# in for one. (`test -t`, not `[ -t ]`: the tests simulate a terminal by replacing `test`.)
if [ "${DEVTOOLS_TTY:-}" != 0 ] && test -t 0; then TTY=1; else TTY=0; fi
export HOMEBREW_NO_ANALYTICS=1 HOMEBREW_NO_AUTO_UPDATE=1
# dry-run and report create nothing under HOME, yet brew's list/info/deps calls make its cache and
# log dirs there. A cache that exists is used as it is (it holds the formula/cask API JSON: pointed
# elsewhere, brew info would download it again); a missing one, and missing logs, go to this run's
# private dir (removed at exit). Your own HOMEBREW_CACHE/HOMEBREW_LOGS win. HOMEBREW_TEMP's default
# is outside HOME (/private/tmp).
if [ "$MODE" != install ]; then
  case "$(uname -s)" in
    Darwin) _bc="$HOME/Library/Caches/Homebrew"; _bl="$HOME/Library/Logs/Homebrew" ;;
    *) _bc="${XDG_CACHE_HOME:-$HOME/.cache}/Homebrew"; _bl="$_bc/Logs" ;;
  esac
  [ -n "${HOMEBREW_CACHE:-}" ] || [ -d "$_bc" ] || { HOMEBREW_CACHE="$DT_CWD/brew-cache"; export HOMEBREW_CACHE; }
  [ -n "${HOMEBREW_LOGS:-}" ] || [ -d "$_bl" ] || { HOMEBREW_LOGS="$DT_CWD/brew-logs"; export HOMEBREW_LOGS; }
fi

GROUPS_ALL="DEPS DEVTOOLS UV NODE RUST HASKELL JULIA SCALA JAVA LATEX CXX GO LEAN LSP POSTGRES MONGODB"
on(){ # on GROUP: its switch; LSP, POSTGRES and MONGODB default off
  local v d=1
  case "$1" in POSTGRES|MONGODB|LSP) d=0 ;; esac
  eval "v=\${STACK_INSTALL_$1:-$d}"
  [ "$v" != 0 ]
}

# ---- pins (CONFIG.md §7 "Prerequisites and toolchains"): bump version and checksum together ------
UV_VERSION=0.12.20                  # the tarball fallback when astral.sh's installer fails
uv_target(){ case "$(uname -s)-$(uname -m)" in
  Darwin-arm64) echo "aarch64-apple-darwin 848fdeb602ff1a1baacd4f6c8b7bdc6cf1ad026a6d9cf59475fda17c179743ca" ;;
  Darwin-x86_64) echo "x86_64-apple-darwin ac54283d211fd77cdc152b67606dbaf6406ff4ab03f3af4ae99468fa8e887141" ;;
  Linux-x86_64) echo "x86_64-unknown-linux-gnu 6590717592ace991ff83a63fef799e3ad9d33ecc8f96c5d6bdd732496e79337f" ;;
  Linux-aarch64|Linux-arm64) echo "aarch64-unknown-linux-gnu 8a7aad7bc76a2fae5151566ff3e43eacce0b2a113d5e4de3e4afe3e58fa2441e" ;;
esac; }
JQ_VERSION=1.8.2                    # github.com/jqlang/jq releases, sha256sum.txt (no-Homebrew fallback)
jq_target(){ case "$(uname -s)-$(uname -m)" in
  Darwin-arm64) echo "macos-arm64 2d75340ba57a4b4b4c8708a21c2dc8e958a48aaa8bba13b27f77f6e4c0eca07e" ;;
  Darwin-x86_64) echo "macos-amd64 e94b266e3c26690550006abe63152b782280f4e14374accdf04cbde844f00bc0" ;;
  Linux-x86_64) echo "linux-amd64 b1c22172dd303f3be49e935aa56aa48a8b7a46e0bc838b4997d3bb451495870f" ;;
  Linux-aarch64|Linux-arm64) echo "linux-arm64 8b85c817833814ddca00a144c33705546355afccf0cf39b188f3cdb48b852309" ;;
esac; }
GITLEAKS_VERSION=8.30.1             # gitleaks_<v>_checksums.txt (no-Homebrew fallback)
gitleaks_target(){ case "$(uname -s)-$(uname -m)" in
  Darwin-arm64) echo "darwin_arm64 b40ab0ae55c505963e365f271a8d3846efbc170aa17f2607f13df610a9aeb6a5" ;;
  Darwin-x86_64) echo "darwin_x64 dfe101a4db2255fc85120ac7f3d25e4342c3c20cf749f2c20a18081af1952709" ;;
  Linux-x86_64) echo "linux_x64 551f6fc83ea457d62a0d98237cbad105af8d557003051f41f3e7ca7b3f2470eb" ;;
  Linux-aarch64|Linux-arm64) echo "linux_arm64 e4a487ee7ccd7d3a7f7ec08657610aa3606637dab924210b3aee62570fb4b080" ;;
esac; }
PRE_COMMIT_VERSION=4.6.2
PRE_COMMIT_PYTHON=3.14
PRE_COMMIT_EXCLUDE_NEWER=2026-09-26T00:00:00Z   # dependency cooldown, as for magg
# Gradle: the -all zip from GitHub (services.gradle.org is not on the sandbox allowlist, and
# Homebrew's gradle pulls a second JDK); the sha256 equals Homebrew's for the same zip.
GRADLE_VERSION=9.8.0
GRADLE_SHA256=46ac66d47f30f3dacfdf306e0b714a91a34fb94a22ba0a744b280933f47bc0cf
GRADLE_URL="https://github.com/gradle/gradle-distributions/releases/download/v$GRADLE_VERSION/gradle-$GRADLE_VERSION-all.zip"
# Playwright: the npm package (npm checks its registry integrity) downloads the browsers its
# version pins; the revision is that version's chromium / chromium-headless-shell build.
PLAYWRIGHT_VERSION=1.63.0
PLAYWRIGHT_CHROMIUM_REVISION=1243
PYTHON_PIN=3.14                     # uv's global Python pin
NODE_MAJOR=24
JAVA_MAJOR=27                       # the JDK the stack targets; ANY JDK found means no cask (older: WARN)
HLINT_VERSION=3.10                  # builds only with GHC 9.12.*
HLINT_GHC=9.12.4
ORMOLU_VERSION=0.9.0.0              # builds with the GHC already set
ORMOLU_BROKEN=0.8.0.2               # ghcup's: its zip's libraries are not copied, so it crashes
# the upstream installers (user-approved; HTTPS only; "latest" unless a version is in the URL)
URL_HOMEBREW="https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh"
URL_UV="https://astral.sh/uv/install.sh"
NVM_VERSION=v0.40.8
URL_NVM="https://raw.githubusercontent.com/nvm-sh/nvm/$NVM_VERSION/install.sh"
URL_RUSTUP="https://sh.rustup.rs"
URL_GHCUP="https://get-ghcup.haskell.org"
URL_JULIAUP="https://install.julialang.org"
case "$(uname -m)" in arm64|aarch64) CS_ARCH=aarch64 ;; *) CS_ARCH=x86_64 ;; esac
URL_COURSIER="https://github.com/coursier/coursier/releases/latest/download/cs-$CS_ARCH-apple-darwin.gz"
URL_ELAN="https://elan.lean-lang.org/elan-init.sh"   # flags from its usage text: -y, --default-toolchain, --no-modify-path
LEAN_NOFILE_MIN=65536               # open files elan and lake need
LEAN_DEFAULT_PROJECT="$HOME/lean/stack_mathlib"
LEAN_USER_PROJECT="${DEVTOOLS_LEAN_PROJECT:-${LEAN_PROJECT_PATH:-}}"

LOCAL_BIN="$HOME/.local/bin"
LOCAL_OPT="$HOME/.local/opt"
NVM_DIR="${NVM_DIR:-$HOME/.nvm}"
# System roots and the macOS lookup tools, overridable for the tests (a variable set to "" turns a
# lookup tool off): DEVTOOLS_LIBRARY, DEVTOOLS_USR_LOCAL, DEVTOOLS_APPLICATIONS,
# DEVTOOLS_PATH_HELPER, DEVTOOLS_PKGUTIL, DEVTOOLS_MDFIND.
LIBRARY_ROOT="${DEVTOOLS_LIBRARY-/Library}"
USR_LOCAL="${DEVTOOLS_USR_LOCAL-/usr/local}"
APPS_ROOT="${DEVTOOLS_APPLICATIONS-/Applications}"
PATH_HELPER="${DEVTOOLS_PATH_HELPER-/usr/libexec/path_helper}"
PKGUTIL="${DEVTOOLS_PKGUTIL-/usr/sbin/pkgutil}"
MDFIND="${DEVTOOLS_MDFIND-/usr/bin/mdfind}"
JVM_DIR="${DEVTOOLS_JVM_DIR:-$LIBRARY_ROOT/Java/JavaVirtualMachines}"
USER_JVM_DIR="$HOME/Library/Java/JavaVirtualMachines"   # JDKs IntelliJ and others download per user
TEX_BIN="${DEVTOOLS_TEX_BIN:-$LIBRARY_ROOT/TeX/texbin}"

have(){ command -v "$1" >/dev/null 2>&1; }
line(){ printf '  %s\n' "$*"; }
sha256_ok(){ printf '%s  %s\n' "$1" "$2" | shasum -a 256 -c - >/dev/null 2>&1; }
path_add(){ [ -d "$1" ] || return 0; case ":$PATH:" in *":$1:"*) ;; *) PATH="$PATH:$1"; export PATH ;; esac; }
runs(){ ("$@" >/dev/null 2>&1 </dev/null; exit $?) 2>/dev/null; }   # run it; the subshell keeps a crash report quiet

# The system login PATH (what /etc/paths and /etc/paths.d/* give every login shell: the Go .pkg adds
# /usr/local/go/bin, MacTeX /Library/TeX/texbin, Postgres.app its bin dir) joins this process's PATH
# at the end, so every lookup below sees what a new terminal would. Never written to a profile.
# path_helper is run with an empty PATH so it prints only the system part.
sys_path_dirs(){
  [ -n "$PATH_HELPER" ] && [ -x "$PATH_HELPER" ] || return 0
  PATH="" "$PATH_HELPER" -s 2>/dev/null </dev/null | sed -n 's/^PATH="\([^"]*\)"; export PATH;$/\1/p' | tr ':' '\n'
}
while IFS= read -r _d; do [ -n "$_d" ] && path_add "$_d"; done <<EOF_SYSPATH
$(sys_path_dirs)
EOF_SYSPATH

# ---- the skip rule: a command found ANYWHERE is never installed, upgraded, replaced or removed ----
# Found = on PATH (command -v, the system login PATH included), or in a known bin dir while that is
# not on PATH yet. DEVTOOLS_SYSTEM_DIRS (tests: "") replaces the system prefixes in that list.
known_dirs(){
  local d IFS=$' \t\n'   # also when called under item_present's IFS=,
  printf '%s\n' "$HOME/.local/bin" "$HOME/.cargo/bin" "$HOME/.ghcup/bin" "$HOME/.cabal/bin" "$HOME/.elan/bin" \
    "$HOME/.juliaup/bin" "$HOME/Library/Application Support/Coursier/bin" "$HOME/go/bin" \
    "$HOME/.local/share/mise/shims" "$HOME/.asdf/shims" "$HOME/.nix-profile/bin" \
    "$USR_LOCAL/go/bin" "$TEX_BIN"
  for d in ${DEVTOOLS_SYSTEM_DIRS-/opt/homebrew/bin /usr/local/bin /opt/local/bin /nix/var/nix/profiles/default/bin /run/current-system/sw/bin}; do
    printf '%s\n' "$d"
  done
  for d in "${NVM_DIR:-$HOME/.nvm}"/versions/node/*/bin "$USR_LOCAL"/texlive/*/bin/*; do [ -d "$d" ] && printf '%s\n' "$d"; done
  return 0
}

# ---- tools installed some other way: .pkg receipts, apps (.dmg/.app), CLIs inside app bundles ----
# One row per tool with evidence; '-' = none. Columns (comma lists; globs allowed):
#   ROW | COMMANDS | RECEIPT IDS (pkgutil --pkgs) | PKG DIRS (where that pkg puts files)
#       | BUNDLE IDS (mdfind) | APP BUNDLES (in /Applications, ~/Applications, /Applications/Utilities)
#       | CLI DIRS inside the bundle (besides Contents/MacOS, Contents/Resources/bin,
#         Contents/Versions/*/bin, Contents/Home/bin, always tried)
# Evidence: go, mactex texlive, jdk com.oracle.jdk-27: this machine's `pkgutil --pkgs` (2026-10-04);
# basictex, the other JDK ids, the app bundles and CLI dirs, Postgres.app's bundle id: the casks'
# pkgutil/app/binary/quit stanzas (`brew info --cask --json=v2 mactex basictex oracle-jdk temurin zulu
# corretto microsoft-openjdk cmake julia-app postgres-app`), not seen installed here.
# UNVERIFIED on a real install (cask JSON only; check with `pkgutil --pkgs` / `mdfind` after installing):
#   receipts org.tug.mactex.basictex*, net.temurin.*.jdk, com.azulsystems.zulu.*, com.amazon.corretto.*,
#   com.microsoft.*.jdk; bundle id com.postgresapp.Postgres2; CLI dirs CMake.app/Contents/bin,
#   Julia-*.app/Contents/Resources/julia/bin, Postgres.app/Contents/Versions/*/bin. Julia.app and
#   CMake.app have no bundle id here (unknown): they are found by the directory check only.
DETECT_ROWS="go|go,gofmt|org.golang.go|$USR_LOCAL/go|-|-|-
mactex|pdflatex,tex|org.tug.mactex.texlive*,org.tug.mactex.basictex*|$LIBRARY_ROOT/TeX,$USR_LOCAL/texlive|-|-|-
jdk|java|com.oracle.jdk-*,net.temurin.*.jdk,com.azulsystems.zulu.*,com.amazon.corretto.*,com.microsoft.*.jdk|$JVM_DIR|-|-|-
cmake|cmake|-|-|-|CMake.app|Contents/bin
julia|julia|-|-|-|Julia-*.app|Contents/Resources/julia/bin
postgres|postgres,psql|-|-|com.postgresapp.Postgres2|Postgres.app|Contents/Versions/*/bin"
ROW=""
row(){ # row NAME: ROW = its line of DETECT_ROWS
  ROW=""
  local r
  while IFS= read -r r; do case "$r" in "$1|"*) ROW="$r"; return 0 ;; esac; done <<EOF_ROWS
$DETECT_ROWS
EOF_ROWS
  return 1
}
col(){ printf '%s' "$ROW" | cut -d'|' -f"$1"; }   # field N of ROW
PKGS_LIST=""; PKGS_READ=0
pkgs(){ # the receipts database, listed once per run
  [ "$PKGS_READ" = 0 ] || return 0
  PKGS_READ=1
  if [ -n "$PKGUTIL" ] && [ -x "$PKGUTIL" ]; then PKGS_LIST="$("$PKGUTIL" --pkgs 2>/dev/null </dev/null)"; fi
  return 0
}
RECEIPT=""
receipt_of(){ # receipt_of ROWNAME: RECEIPT = the first of its receipt ids pkgutil lists
  local g id globs
  RECEIPT=""
  row "$1" || return 1
  globs="$(col 3)"; [ "$globs" = - ] && return 1
  pkgs
  set -f
  local IFS=,
  for g in $globs; do
    while IFS= read -r id; do
      # shellcheck disable=SC2254
      case "$id" in $g) RECEIPT="$id"; set +f; return 0 ;; esac
    done <<EOF_PKGS
$PKGS_LIST
EOF_PKGS
  done
  set +f
  return 1
}
under(){ # under PATH DIR,DIR...: PATH lies in one of the dirs
  local d IFS=,
  for d in $2; do case "$1" in "$d"/*) return 0 ;; esac; done
  return 1
}
resolve(){ # follow symlinks (no readlink -f on older macOS)
  local p="$1" l n=0
  while [ -L "$p" ] && [ "$n" -lt 20 ]; do
    l="$(readlink "$p")"; case "$l" in /*) p="$l" ;; *) p="$(dirname "$p")/$l" ;; esac; n=$((n + 1))
  done
  printf '%s' "$p"
}
app_cli(){ # app_cli APP CLIDIRS NAME...: FOUND = NAME inside the bundle APP
  local app="$1" subs="$2" s d n; shift 2
  local IFS=$' \t\n'
  for s in $(printf '%s' "$subs" | tr ',' ' ') Contents/MacOS Contents/Resources/bin 'Contents/Versions/*/bin' Contents/Home/bin; do
    [ "$s" = - ] && continue
    for d in "$app"/$s; do
      for n in "$@"; do [ -x "$d/$n" ] && [ ! -d "$d/$n" ] && { FOUND="$d/$n"; return 0; }; done
    done
  done
  return 1
}
find_app(){ # find_app ROWNAME: FOUND = one of its commands inside an app bundle
  local apps subs ids cmds root a g id IFS=$' \t\n'
  row "$1" || return 1
  cmds="$(col 2 | tr ',' ' ')"; ids="$(col 5)"; apps="$(col 6)"; subs="$(col 7)"
  if [ "$apps" != - ]; then
    for root in "$APPS_ROOT" "$HOME/Applications" "$APPS_ROOT/Utilities"; do
      [ -d "$root" ] || continue                                 # the cheap directory check first
      for g in $(printf '%s' "$apps" | tr ',' ' '); do
        for a in "$root"/$g; do
          # shellcheck disable=SC2086
          [ -d "$a" ] && app_cli "$a" "$subs" $cmds && return 0
        done
      done
    done
  fi
  if [ "$ids" != - ] && [ -n "$MDFIND" ] && [ -x "$MDFIND" ]; then  # an app elsewhere (Spotlight; silent when off)
    for id in $(printf '%s' "$ids" | tr ',' ' '); do
      while IFS= read -r a; do
        # a Spotlight hit elsewhere under HOME (a project, ~/Downloads) does not count: sandboxed
        # agents can write the projects, and a planted bundle would join this run's PATH
        case "$a" in "$HOME"/Applications/*) ;; "$HOME"/*) continue ;; esac
        # shellcheck disable=SC2086
        [ -n "$a" ] && [ -d "$a" ] && app_cli "$a" "$subs" $cmds && return 0
      done <<EOF_MD
$("$MDFIND" "kMDItemCFBundleIdentifier == '$id'" 2>/dev/null </dev/null)
EOF_MD
    done
  fi
  return 1
}
# find_tool ROWNAME: past PATH and the known dirs, the row's apps, then its receipt alone
# (FOUND "pkg receipt ID": registered, but none of its commands is where the pkg puts them)
find_tool(){
  find_app "$1" && return 0
  receipt_of "$1" && { FOUND="pkg receipt $RECEIPT"; return 0; }
  return 1
}
FOUND=""
# find_cmd NAME...: FOUND = the path of the first NAME found (PATH first, then known_dirs)
find_cmd(){
  local n d p dirs
  FOUND=""
  for n in "$@"; do
    p="$(command -v "$n" 2>/dev/null || true)"
    case "$p" in /*) FOUND="$p"; return 0 ;; esac
  done
  dirs="$(known_dirs)"
  for n in "$@"; do
    while IFS= read -r d; do
      [ -n "$d" ] && [ -x "$d/$n" ] && [ ! -d "$d/$n" ] && { FOUND="$d/$n"; return 0; }
    done <<EOF_DIRS
$dirs
EOF_DIRS
  done
  return 1
}
manager_of(){ case "$1" in
  "$HOME"/.cargo/*) echo "rustup/cargo" ;; "$HOME"/.ghcup/*) echo ghcup ;; "$HOME"/.cabal/*) echo cabal ;;
  "$HOME"/.elan/*) echo elan ;; "$HOME"/.juliaup/*) echo juliaup ;; "${NVM_DIR:-$HOME/.nvm}"/*) echo nvm ;;
  "$HOME/Library/Application Support/Coursier"/*) echo coursier ;; "$HOME"/.local/share/mise/*) echo mise ;;
  "$HOME"/.asdf/*) echo asdf ;; "$HOME"/.nix-profile/*|/nix/*|/run/current-system/*) echo nix ;;
  "$HOME"/go/*) echo "go install" ;; "$HOME"/.local/*) echo "~/.local" ;; "$HOME"/Library/Java/*) echo "~/Library/Java" ;;
  "$HOME"/Library/Caches/*) echo "Playwright's cache" ;; "$HOME"/.sdkman/*) echo sdkman ;; /opt/local/*) echo MacPorts ;;
  *) return 1 ;; esac; }
SRC=""
# src_of PATH: SRC = brew | app | pkg | <manager> | macOS | PATH (no subshell: the receipts list is
# read once into this shell). A path is checked as given and with its symlinks followed.
src_of(){
  local p="$1" r n IFS=$' \t\n'
  case "$p" in "brew list"*) SRC=brew; return 0 ;; "pkg receipt "*) SRC=pkg; return 0 ;; esac
  SRC="$(manager_of "$p")" && return 0
  r="$(resolve "$p")"
  case "$r" in
    */Cellar/*|*/Caskroom/*|/opt/homebrew/*|/usr/local/opt/*|/home/linuxbrew/*) SRC=brew; return 0 ;;
    *.app/*) SRC=app; return 0 ;;
  esac
  for n in $(printf '%s\n' "$DETECT_ROWS" | cut -d'|' -f1); do
    row "$n"; [ "$(col 4)" = - ] && continue
    if { under "$p" "$(col 4)" || under "$r" "$(col 4)"; } && receipt_of "$n"; then SRC=pkg; return 0; fi
  done
  SRC="$(manager_of "$r")" && return 0
  case "$r" in /usr/bin/*|/bin/*|/usr/sbin/*|/sbin/*|/System/*) SRC=macOS ;; *) SRC=PATH ;; esac
}
N_INST=0; N_SKIP=0; N_FAIL=0; N_WARN=0; N_WOULD=0; N_MISS=0
skip_line(){
  src_of "$2"
  line "skip $1 (found: $2, from $SRC)"; N_SKIP=$((N_SKIP + 1))
  case "$2" in "pkg receipt "*)       # registered, its files gone: reported, never reinstalled over
    warn_line "$1: the receipt ${2#pkg receipt } is registered but its commands are not where the pkg puts them; the installer leaves it alone. Fix: reinstall it from its .pkg, or forget the receipt (sudo pkgutil --forget ${2#pkg receipt }) and rerun ./install.sh" ;;
  esac
}
warn_line(){ line "WARN $*"; N_WARN=$((N_WARN + 1)); }
# a found tool that doesn't run is reported with the fix, never removed or reinstalled
VERSION_CHECKED=" uv rustup juliaup elan ghcup hlint ormolu pre-commit gradle pnpm (corepack) "
fix_for(){ case "$1" in
  ormolu) case "$2" in "$HOME"/.ghcup/*) printf 'ghcup rm ormolu %s; ' "$ORMOLU_BROKEN" ;; esac
          printf 'cabal update; cabal install --ignore-project ormolu-%s --overwrite-policy=always' "$ORMOLU_VERSION" ;;
  hlint) printf 'ghcup install ghc %s; cabal update; cabal install --ignore-project -w ghc-%s hlint-%s --overwrite-policy=always' "$HLINT_GHC" "$HLINT_GHC" "$HLINT_VERSION" ;;
  *) printf '%s' "$3" ;; esac; }
# Only in a real run: dry-run and report execute none of the tools they find (pnpm --version can
# make corepack download pnpm; COREPACK_ENABLE_DOWNLOAD_PROMPT=0 keeps that from asking).
version_warn(){ # version_warn LABEL PATH ROUTE
  [ "$MODE" = install ] || return 0
  case "$VERSION_CHECKED" in *" $1 "*) ;; *) return 0 ;; esac
  COREPACK_ENABLE_DOWNLOAD_PROMPT=0 runs "$2" --version && return 0
  warn_line "$1 at $2 fails '$(basename "$2") --version'; the installer leaves it alone. Fix: $(fix_for "$1" "$2" "$3")"
}
# temp dirs under $TMPDIR (macOS mktemp -d without a template ignores it)
tmpd(){ mktemp -d "${TMPDIR:-/tmp}/stack-devtools.XXXXXX"; }
LOGDIR=""
logfile(){ [ -n "$LOGDIR" ] || LOGDIR="$(tmpd)"; printf '%s/%s.log' "$LOGDIR" "$(printf '%s' "$1" | tr -c 'A-Za-z0-9._-' _)"; }
KEEP_LOGS=0
finish(){ if [ -n "$LOGDIR" ] && [ "$KEEP_LOGS" = 0 ]; then rm -rf "$LOGDIR"; fi; cd / 2>/dev/null; rm -rf "$DT_CWD"; }
trap finish EXIT
fetch_sum(){ curl --proto '=https' --tlsv1.2 -fsSL --retry 2 -o "$3" "$1" && sha256_ok "$2" "$3"; }

# Homebrew, also when its bin dir is not on PATH yet (a fresh shell); DEVTOOLS_BREW_CANDIDATES lets
# the tests keep a real Homebrew out.
BREW=""
BREW_ON_PATH_AT_START=0; have brew && BREW_ON_PATH_AT_START=1
find_brew(){
  if have brew; then BREW="$(command -v brew)"; return 0; fi
  local b
  for b in ${DEVTOOLS_BREW_CANDIDATES-/opt/homebrew/bin/brew /usr/local/bin/brew}; do
    if [ -x "$b" ]; then BREW="$b"; path_add "$(dirname "$b")"; return 0; fi
  done
  return 1
}
find_brew

# remote_installer URL INTERPRETER [ARGS...]: an upstream installer (user-approved), fetched over
# HTTPS only into a temp file (never a pipe: a cut-off download never runs half a script), its URL
# and sha256 printed into the log, then run. Environment for it: VAR=value remote_installer ...
# INSTALLER_RAN: "URL sha256 HEX" of what ran, printed on the tool's result line (the log goes on success)
INSTALLER_RAN=""
remote_installer(){
  local url="$1" interp="$2" d rc sum; shift 2
  d="$(tmpd)" || return 1
  echo "installer: $url"
  if ! curl --proto '=https' --tlsv1.2 -fsSL --retry 2 -o "$d/installer.sh" "$url"; then rm -rf "$d"; echo "download failed"; return 1; fi
  sum="$(shasum -a 256 "$d/installer.sh" | cut -d' ' -f1)"
  echo "sha256: $sum"
  INSTALLER_RAN="${INSTALLER_RAN:+$INSTALLER_RAN; }$url sha256 $sum"
  "$interp" "$d/installer.sh" "$@"; rc=$?
  rm -rf "$d"; return $rc
}

MISSING_REQ=""     # "label|command" lines of required tools still missing
# ensure LABEL REQ(1|0) CHECK ROUTE INSTALL [interactive]: one line per tool. CHECK and INSTALL
# are function names (INSTALL "" = no route here); ROUTE is what a real run does (printed by
# dry-run, report and on failure). "interactive": output stays on the terminal, not in a log.
# A CHECK that finds a command sets FOUND: "skip LABEL (found: PATH, from SOURCE)"; a CHECK of
# configuration (a pin, git's lfs filters, a project) leaves it empty: "ok  LABEL".
ensure(){
  local label="$1" req="$2" check="$3" route="$4" inst="$5" inter="${6:-}" log="" rc cr=""
  FOUND=""
  if "$check"; then
    if [ -n "$FOUND" ]; then
      skip_line "$label" "$FOUND"; version_warn "$label" "$FOUND" "$route"
      case "$FOUND" in /*) [ -f "$FOUND" ] && path_add "$(dirname "$FOUND")" ;; esac   # later steps of this run use it
    else line "ok  $label"; fi
    return 0
  fi
  if [ -z "$inst" ]; then
    N_MISS=$((N_MISS + 1))
    line "! $label missing — $route"
    [ "$req" = 1 ] && MISSING_REQ="$MISSING_REQ$label|$route
"
    return 0
  fi
  case "$MODE" in
    report) N_MISS=$((N_MISS + 1)); line "! $label missing — $route"; return 0 ;;
    dry-run) N_WOULD=$((N_WOULD + 1)); line "would: $label ← $route"; return 0 ;;
  esac
  INSTALLER_RAN=""
  if [ -n "$inter" ]; then
    line "… $label: $route"
    "$inst"; rc=$?
  else
    log="$(logfile "$label")"
    # a terminal sees the tool being installed; the result overwrites that line (one line per tool).
    # Not in a subshell: INSTALLER_RAN set by the installer function must reach the result line.
    if [ -t 1 ]; then printf '  … %s: %s' "$label" "$route"; cr="$(printf '\r\033[K')"; fi
    "$inst" >"$log" 2>&1 </dev/null; rc=$?
  fi
  if [ "$rc" = 0 ] && "$check"; then
    N_INST=$((N_INST + 1))
    printf '%s  + %s (%s)\n' "$cr" "$label" "$route"
    [ -z "$INSTALLER_RAN" ] || line "  ran $INSTALLER_RAN"
  else
    KEEP_LOGS=1; N_FAIL=$((N_FAIL + 1))
    printf '%s  ! %s: install failed%s — %s\n' "$cr" "$label" "${log:+ (log $log)}" "$route"
    [ "$req" = 1 ] && MISSING_REQ="$MISSING_REQ$label|$route
"
  fi
  return 0
}

# ==== 1. Homebrew ================================================================================
chk_brew(){ [ -n "$BREW" ] && FOUND="$BREW"; }
inst_brew(){
  # interactive on purpose: NONINTERACTIVE=1 makes Homebrew's installer use `sudo -n`, which fails
  # unless your sudo is cached; run on a terminal it asks for RETURN and your password itself
  remote_installer "$URL_HOMEBREW" /bin/bash && find_brew
}
brew_profile(){
  # Homebrew found off PATH (just installed): its shellenv line in ~/.zprofile, once
  [ -n "$BREW" ] && [ "$BREW_ON_PATH_AT_START" = 0 ] && [ "$NO_PROFILE" != 1 ] || return 0
  local f
  for f in "$HOME/.zprofile" "$HOME/.zshrc" "$HOME/.bash_profile" "$HOME/.profile"; do
    [ -f "$f" ] && grep -q 'brew shellenv' "$f" && return 0
  done
  if [ "$MODE" = install ]; then
    printf '\neval "$(%s shellenv)"\n' "$BREW" >>"$HOME/.zprofile" && line "+ ~/.zprofile: eval \"\$($BREW shellenv)\""
  else
    line "would: add eval \"\$($BREW shellenv)\" to ~/.zprofile"
  fi
}
homebrew_step(){
  on DEPS || return 0
  if [ "$TTY" = 1 ]; then
    ensure homebrew 0 chk_brew "Homebrew's installer ($URL_HOMEBREW, latest; asks for your password)" inst_brew interactive
  else
    ensure homebrew 0 chk_brew "no terminal: run /bin/bash -c \"\$(curl -fsSL $URL_HOMEBREW)\" yourself, then rerun ./install.sh" ""
  fi
  brew_profile
}

# ==== 2. Homebrew batch ==========================================================================
# GROUP TYPE NAME PROBES: a probe is cmd:<binary> (PATH, the system login PATH, the known dirs),
# path:<file>, tool:<row> (DETECT_ROWS: its apps, then its pkg receipt), jdk:<major> (the newest JDK
# found anywhere, see jdk_at_least, is >= major; oracle-jdk uses jdk:1, so any JDK counts and an older
# one than JAVA_MAJOR gets a WARN, never the cask) or - (brew list only).
# LEAN's elan-init is Homebrew's bottle of elan (sha256-pinned in the formula; elan, lake and lean are
# its links; built without self-update); without Homebrew the official elan installer runs (step 3).
# LSP's jdtls (the Java language server; install.sh --with-lsp) depends on Homebrew's openjdk (keg-only:
# java_home doesn't see it, jdk_at_least does) and python@3.14 (links python3 into Homebrew's bin dir).
BREW_ITEMS="DEPS formula jq cmd:jq
DEPS formula ripgrep cmd:rg
DEPS formula gh cmd:gh
DEPS formula ffmpeg cmd:ffmpeg
DEPS formula imagemagick cmd:magick
DEPS formula librsvg cmd:rsvg-convert
DEPS formula poppler cmd:pdftoppm
DEPS formula just cmd:just
DEVTOOLS formula gitleaks cmd:gitleaks
CXX formula cmake cmd:cmake,tool:cmake
CXX formula cmake-docs -
CXX formula ninja cmd:ninja
CXX formula ffmpeg-full -
CXX formula pandoc cmd:pandoc
CXX formula git-lfs cmd:git-lfs
CXX formula tesseract cmd:tesseract
CXX formula typst cmd:typst
CXX formula shellcheck cmd:shellcheck
CXX formula markdownlint-cli2 cmd:markdownlint-cli2
GO formula go cmd:go,tool:go
GO formula gopls cmd:gopls
JAVA cask oracle-jdk jdk:1
JAVA cask kotlin-lsp cmd:kotlin-lsp
LSP formula jdtls cmd:jdtls
LATEX cask mactex cmd:pdflatex,path:$TEX_BIN/pdflatex,tool:mactex
POSTGRES formula postgresql@18 cmd:postgres,cmd:psql,tool:postgres
MONGODB formula mongodb/brew/mongodb-community cmd:mongod
LEAN formula elan-init cmd:elan,cmd:lake,cmd:lean"

# jdk_at_least MAJOR: the NEWEST JDK found anywhere is >= MAJOR (JDK_AT, JDK_MAJOR_FOUND: where and
# which). Read from each JDK's release file (java_home fails in the sandbox; /usr/bin/java is only
# macOS's stub): /Library/Java/JavaVirtualMachines, ~/Library/Java/JavaVirtualMachines, $JAVA_HOME,
# SDKMAN's candidates, Homebrew's openjdk kegs. Java 8 says JAVA_VERSION="1.8.0_x": major 8.
JDK_AT=""; JDK_MAJOR_FOUND=0
jdk_at_least(){
  local r v m bp=""
  [ -n "$BREW" ] && bp="$(dirname "$(dirname "$BREW")")"
  JDK_AT=""; JDK_MAJOR_FOUND=0
  for r in "$JVM_DIR"/*/Contents/Home/release "$USER_JVM_DIR"/*/Contents/Home/release \
           ${JAVA_HOME:+"$JAVA_HOME/release"} "$HOME"/.sdkman/candidates/java/*/release \
           ${bp:+"$bp"/opt/openjdk*/libexec/openjdk.jdk/Contents/Home/release}; do
    [ -f "$r" ] || continue
    v="$(sed -n 's/^JAVA_VERSION="\([0-9][0-9._]*\).*/\1/p' "$r" | head -n 1)"
    case "$v" in 1.*) m="${v#1.}"; m="${m%%[._]*}" ;; *) m="${v%%[._]*}" ;; esac
    case "$m" in ''|*[!0-9]*) continue ;; esac
    [ "$m" -gt "$JDK_MAJOR_FOUND" ] && { JDK_MAJOR_FOUND="$m"; JDK_AT="${r%/release}"; }
  done
  [ "$JDK_MAJOR_FOUND" -gt 0 ] && [ "$JDK_MAJOR_FOUND" -ge "$1" ]
}
jdk_old_warn(){ # after oracle-jdk was skipped: an older JDK than the stack targets is left alone
  [ "$JDK_MAJOR_FOUND" -lt "$JAVA_MAJOR" ] || return 0
  warn_line "oracle-jdk: JDK $JDK_MAJOR_FOUND at $JDK_AT is older than the $JAVA_MAJOR the stack targets; left alone. To add one: brew install --cask oracle-jdk"
}
BREW_FORMULAE_LIST=""; BREW_CASKS_LIST=""
brew_lists(){
  [ -n "$BREW" ] || return 0
  BREW_FORMULAE_LIST=" $("$BREW" list --formula -1 2>/dev/null </dev/null | tr '\n' ' ') "
  BREW_CASKS_LIST=" $("$BREW" list --cask -1 2>/dev/null </dev/null | tr '\n' ' ') "
}
ITEM_AT=""
item_present(){ # TYPE NAME PROBES: ITEM_AT = where it was found (a path, or "brew list --formula|--cask")
  local type="$1" name="$2" probes="$3" short p
  short="${name##*/}"; ITEM_AT=""
  local IFS=,
  for p in $probes; do
    case "$p" in
      cmd:*) find_cmd "${p#cmd:}" && { ITEM_AT="$FOUND"; return 0; } ;;
      path:*) [ -e "${p#path:}" ] && { ITEM_AT="${p#path:}"; return 0; } ;;
      tool:*) find_tool "${p#tool:}" && { ITEM_AT="$FOUND"; return 0; } ;;
      jdk:*) jdk_at_least "${p#jdk:}" && { ITEM_AT="$JDK_AT"; return 0; } ;;
    esac
  done
  case "$type" in
    formula) case "$BREW_FORMULAE_LIST" in *" $short "*) ITEM_AT="brew list --formula"; return 0 ;; esac ;;
    cask) case "$BREW_CASKS_LIST" in *" $short "*) ITEM_AT="brew list --cask"; return 0 ;; esac ;;
  esac
  return 1
}
brew_resolves(){ # TYPE NAME: brew info knows it
  if [ "$1" = cask ]; then "$BREW" info --cask "$2" >/dev/null 2>&1 </dev/null
  else "$BREW" info --formula "$2" >/dev/null 2>&1 </dev/null; fi
}
# brew_batch TYPE NAMES...: one install for all of them; a failed batch is retried name by name.
# Casks keep the terminal (the pkg installers ask for your password); formulae go to a log.
brew_batch(){
  local type="$1" log n; shift
  [ $# -gt 0 ] || return 0
  if [ "$type" = cask ]; then
    line "… brew install --cask $*"
    "$BREW" install --cask "$@" && return 0
  else
    log="$(logfile brew-formulae)"
    line "… brew install $* (log $log)"
    "$BREW" install "$@" >"$log" 2>&1 </dev/null && return 0
  fi
  KEEP_LOGS=1
  line "! the batch failed: retrying one by one"
  for n in "$@"; do
    if [ "$type" = cask ]; then "$BREW" install --cask "$n" || true
    else "$BREW" install "$n" >>"$log" 2>&1 </dev/null || true; fi
  done
}
# gopls next to a Go that is not Homebrew's (the official .pkg in /usr/local/go, say). The formula's
# bottle needs no go (`brew deps gopls` is empty; go is a build-only dependency), so brew pours it and
# your go stays the only one. Should the formula ever pull Homebrew's go in (a runtime dependency, or
# no bottle for this macOS, which means a source build), gopls comes from
# `go install golang.org/x/tools/gopls@v<the formula's version>` with your go instead.
GOPLS_GO=""; GOPLS_VER=""
gopls_route(){ # gopls_route GO
  local info deps
  info="$("$BREW" info --formula gopls 2>/dev/null </dev/null | head -n 1)"
  deps="$("$BREW" deps gopls 2>/dev/null </dev/null)"
  if printf '%s\n' "$deps" | grep -qx go || { [ -n "$info" ] && ! printf '%s' "$info" | grep -q '(bottled)'; }; then
    GOPLS_GO="$1"
    GOPLS_VER="$(printf '%s' "$info" | sed -n 's/^==> gopls: stable \([0-9][0-9A-Za-z.]*\).*/\1/p')"
    line "gopls: Homebrew's formula would bring in Homebrew's go; gopls comes from go install with your go ($1)"
  else
    line "gopls: Homebrew's bottle (go is only a build dependency of the formula; your go at $1 stays the only go)"
  fi
}
chk_gopls(){ find_cmd gopls; }
# Into your GOBIN (`go env GOBIN`: the variable or `go env -w`), else ~/.local/bin, which is on PATH;
# go's own default, $(go env GOPATH)/bin = ~/go/bin, is often on no PATH. The sandbox's GOMODCACHE and
# GOCACHE, if inherited, would build it from ~/.cache/claude-sandbox, which sandboxed agents can write.
go_u(){ env -u GOMODCACHE -u GOCACHE "$@" </dev/null; }
inst_gopls_go(){
  local gobin
  [ -n "$GOPLS_VER" ] || { echo "the gopls formula's version is unknown (brew info --formula gopls)"; return 1; }
  gobin="$(go_u "$GOPLS_GO" env GOBIN 2>/dev/null)"
  [ -n "$gobin" ] || gobin="$LOCAL_BIN"
  mkdir -p "$gobin" && go_u GOBIN="$gobin" "$GOPLS_GO" install "golang.org/x/tools/gopls@v$GOPLS_VER"
}
gopls_step(){
  [ -n "$GOPLS_GO" ] || return 0
  ensure gopls 0 chk_gopls "$GOPLS_GO install golang.org/x/tools/gopls@v${GOPLS_VER:-?} (your go, into your GOBIN, else ~/.local/bin; the Go module proxy's checksum database verifies it)" inst_gopls_go
}
item_label(){ case "$1" in elan-init) echo elan ;; *) echo "${1##*/}" ;; esac; }
ELAN_VIA_BREW=0    # elan-init joined the batch: its fresh elan gets the stable toolchain in step 3
brew_step(){
  local unresolved="" want_f="" want_c="" nobrew="" g type name probes t
  brew_lists
  if [ -n "$BREW" ] && on MONGODB && ! item_present formula mongodb/brew/mongodb-community cmd:mongod && ! "$BREW" tap 2>/dev/null </dev/null | grep -qx 'mongodb/brew'; then
    if [ "$MODE" = install ]; then "$BREW" tap mongodb/brew >/dev/null 2>&1 </dev/null || line "! brew tap mongodb/brew failed"
    else line "would: brew tap mongodb/brew"; fi
  fi
  while read -r g type name probes; do
    [ -n "$g" ] || continue
    on "$g" || continue
    # without Homebrew these have their own step below (one line each there, not two)
    if [ -z "$BREW" ]; then case "$name" in jq|elan-init) continue ;; gitleaks) on DEPS && continue ;; esac; fi
    if item_present "$type" "$name" "$probes"; then skip_line "$(item_label "$name")" "$ITEM_AT"; [ "$name" = oracle-jdk ] && jdk_old_warn; continue; fi
    # elan: the open-file limit gates installing it; without Homebrew its official installer (step 3)
    if [ "$g" = LEAN ] && { [ -z "$BREW" ] || ! lean_limit_ok; }; then continue; fi
    if [ -z "$BREW" ]; then nobrew="$nobrew ${name##*/}"; continue; fi
    if ! brew_resolves "$type" "$name"; then unresolved="$unresolved $name"; continue; fi
    if [ "$type" = cask ]; then want_c="$want_c $name"; else want_f="$want_f $name"; fi
    [ "$name" = elan-init ] && ELAN_VIA_BREW=1
  done <<EOF_ITEMS
$BREW_ITEMS
EOF_ITEMS
  # shellcheck disable=SC2086
  [ -z "$unresolved" ] || { line "! brew could not resolve:$unresolved (left out)"; N_MISS=$((N_MISS + $(echo $unresolved | wc -w))); }
  # shellcheck disable=SC2086
  [ -z "$nobrew" ] || { line "! no Homebrew, not installed:$nobrew (install Homebrew, then rerun)"; N_MISS=$((N_MISS + $(echo $nobrew | wc -w))); }
  case " $want_f " in *" gopls "*)
    if find_cmd go; then src_of "$FOUND"; [ "$SRC" = brew ] || gopls_route "$FOUND"; fi ;;
  esac
  if [ -n "$GOPLS_GO" ]; then
    t=""; for name in $want_f; do [ "$name" = gopls ] || t="$t $name"; done; want_f="$t"
  fi
  [ -n "$want_f$want_c" ] || return 0
  case "$MODE" in
    report)
      [ -z "$want_f" ] || line "! missing formulae:$want_f"
      [ -z "$want_c" ] || line "! missing casks:$want_c"
      N_MISS=$((N_MISS + $(echo $want_f $want_c | wc -w)))
      return 0 ;;
    dry-run)
      N_WOULD=$((N_WOULD + $(echo $want_f $want_c | wc -w)))
      [ -z "$want_f" ] || line "would: HOMEBREW_NO_ANALYTICS=1 HOMEBREW_NO_AUTO_UPDATE=1 brew install$want_f"
      [ -z "$want_c" ] || line "would: HOMEBREW_NO_ANALYTICS=1 HOMEBREW_NO_AUTO_UPDATE=1 brew install --cask$want_c$([ "$TTY" = 1 ] || echo '  (no terminal: printed, not run)')"
      case "$want_c" in *mactex*) line "  (mactex is about 5 GB; STACK_INSTALL_LATEX=0 skips it; brew install --cask mactex-no-gui is the smaller one)" ;; esac
      return 0 ;;
  esac
  # shellcheck disable=SC2086
  brew_batch formula $want_f
  if [ -n "$want_c" ]; then
    case "$want_c" in *mactex*) line "  mactex is about 5 GB and takes a while (STACK_INSTALL_LATEX=0 skips it)" ;; esac
    if [ "$TTY" = 1 ]; then
      # shellcheck disable=SC2086
      brew_batch cask $want_c
    else
      line "! casks not installed (the pkg installers need a terminal): HOMEBREW_NO_ANALYTICS=1 brew install --cask$want_c"
      N_MISS=$((N_MISS + $(echo $want_c | wc -w)))
      want_c=""
    fi
  fi
  brew_lists
  for name in $want_f $want_c; do
    t=formula; case " $want_c " in *" $name "*) t=cask ;; esac
    if item_present "$t" "$name" "-"; then N_INST=$((N_INST + 1)); line "+ $(item_label "$name") (brew)"
    else KEEP_LOGS=1; N_FAIL=$((N_FAIL + 1)); line "! $(item_label "$name"): brew install failed"; fi
  done
}

# ==== 3. upstream managers =======================================================================
chk_uv(){ find_cmd uv; }
inst_uv(){
  if [ "$NO_PROFILE" = 1 ]; then UV_NO_MODIFY_PATH=1 remote_installer "$URL_UV" sh && return 0
  else remote_installer "$URL_UV" sh && return 0; fi
  echo "astral.sh installer failed: the pinned tarball"
  inst_uv_tarball
}
inst_uv_tarball(){
  set -- $(uv_target)
  [ -n "${1:-}" ] || { echo "no uv build for $(uname -s)-$(uname -m)"; return 1; }
  local d rc; d="$(tmpd)" || return 1
  mkdir -p "$LOCAL_BIN" && fetch_sum "https://github.com/astral-sh/uv/releases/download/$UV_VERSION/uv-$1.tar.gz" "$2" "$d/uv.tgz" \
    && tar -xzf "$d/uv.tgz" -C "$d" && install -m 0755 "$d/uv-$1/uv" "$d/uv-$1/uvx" "$LOCAL_BIN/"
  rc=$?; rm -rf "$d"; return $rc
}
# dry-run and report read uv's global pin file and run no uv command (uv 0.12 keeps the pin in
# $XDG_CONFIG_HOME/uv/.python-version, ~/.config without it); a real run asks uv itself
chk_pypin(){
  if [ "$MODE" != install ]; then
    have uv && grep -qs "^$PYTHON_PIN" "${XDG_CONFIG_HOME:-$HOME/.config}/uv/.python-version"; return
  fi
  have uv && uv python find "$PYTHON_PIN" >/dev/null 2>&1 && uv python pin --global 2>/dev/null | grep -q "^$PYTHON_PIN"
}
inst_pypin(){ uv python install "$PYTHON_PIN" && uv python pin --global "$PYTHON_PIN"; }

nvm_node_bin(){ local d; for d in "$NVM_DIR"/versions/node/v"$NODE_MAJOR".*; do [ -x "$d/bin/node" ] && { printf '%s' "$d/bin"; return 0; }; done; return 1; }
chk_nvm(){ [ -s "$NVM_DIR/nvm.sh" ] && FOUND="$NVM_DIR/nvm.sh"; }
inst_nvm(){
  if [ "$NO_PROFILE" = 1 ]; then PROFILE=/dev/null remote_installer "$URL_NVM" bash
  else remote_installer "$URL_NVM" bash; fi
}
chk_node24(){ local b; b="$(nvm_node_bin)" && FOUND="$b/node"; }
# nvm is a shell function: sourced in a child bash (nvm.sh does not run under set -u)
inst_node24(){ NVM_DIR="$NVM_DIR" bash -c '. "$NVM_DIR/nvm.sh" && nvm install '"$NODE_MAJOR"; }
# a pnpm found counts; one that does not run gets version_warn's WARN (real runs only), never
# `corepack enable` over it
chk_pnpm(){ find_cmd pnpm; }
inst_pnpm(){
  local b; b="$(nvm_node_bin)" || { echo "no node $NODE_MAJOR from nvm"; return 1; }
  # corepack's one-time "download pnpm?" question is answered by the variable, never by keystrokes
  PATH="$b:$PATH" corepack enable pnpm && PATH="$b:$PATH" COREPACK_ENABLE_DOWNLOAD_PROMPT=0 pnpm -v
}

chk_rustup(){ find_cmd rustup cargo rustc; }
inst_rustup(){
  if [ "$NO_PROFILE" = 1 ]; then remote_installer "$URL_RUSTUP" sh -y --no-modify-path
  else remote_installer "$URL_RUSTUP" sh -y; fi
}

chk_ghcup(){ find_cmd ghcup ghc; }
inst_ghcup(){
  # ghcup's documented non-interactive variables (bootstrap-haskell's header): HLS on, stack on
  # (its default; BOOTSTRAP_HASKELL_INSTALL_NO_STACK would skip it), PATH line in the rc files
  if [ "$NO_PROFILE" = 1 ]; then
    BOOTSTRAP_HASKELL_NONINTERACTIVE=1 BOOTSTRAP_HASKELL_INSTALL_HLS=1 remote_installer "$URL_GHCUP" sh
  else
    BOOTSTRAP_HASKELL_NONINTERACTIVE=1 BOOTSTRAP_HASKELL_INSTALL_HLS=1 BOOTSTRAP_HASKELL_ADJUST_BASHRC=1 remote_installer "$URL_GHCUP" sh
  fi
}
# Outside the sandbox with your own cabal dirs: the sandbox's CABAL_DIR/XDG_CACHE_HOME, if inherited,
# would send the build into ~/.cache/claude-sandbox.
cabal_u(){ env -u CABAL_DIR -u XDG_CACHE_HOME cabal "$@" </dev/null; }
chk_hlint(){ find_cmd hlint; }
inst_hlint(){
  ghcup whereis ghc "$HLINT_GHC" >/dev/null 2>&1 || ghcup install ghc "$HLINT_GHC" </dev/null || return 1
  cabal_u update && cabal_u install --ignore-project -w "ghc-$HLINT_GHC" "hlint-$HLINT_VERSION" --overwrite-policy=always
}
# an ormolu or hlint found anywhere is skipped; one that fails --version (ghcup's ormolu 0.8.0.2
# crashes) gets a WARN line with the fix to run yourself: never removed or reinstalled here
chk_ormolu(){ find_cmd ormolu; }
inst_ormolu(){ cabal_u update && cabal_u install --ignore-project "ormolu-$ORMOLU_VERSION" --overwrite-policy=always; }

chk_juliaup(){ find_cmd juliaup julia || find_tool julia; }   # Julia.app (the julia cask, a .dmg) counts
inst_juliaup(){
  if [ "$NO_PROFILE" = 1 ]; then remote_installer "$URL_JULIAUP" sh --yes --add-to-path=no
  else remote_installer "$URL_JULIAUP" sh --yes; fi
}

chk_cs(){ find_cmd cs coursier; }
inst_cs(){
  local d rc; d="$(tmpd)" || return 1
  echo "download: $URL_COURSIER"
  ( cd "$d" && curl --proto '=https' --tlsv1.2 -fsSL --retry 2 -o cs.gz "$URL_COURSIER" && gzip -d cs.gz && chmod +x cs \
      && { xattr -d com.apple.quarantine cs 2>/dev/null || true; } \
      && echo "sha256: $(shasum -a 256 cs | cut -d' ' -f1)" && ./cs setup -y )
  rc=$?
  [ -f "$d/cs" ] && INSTALLER_RAN="$URL_COURSIER (gunzipped) sha256 $(shasum -a 256 "$d/cs" | cut -d' ' -f1)"
  rm -rf "$d"; return $rc
}

chk_elan(){ find_cmd elan lake lean; }
# configuration of a fresh Homebrew elan (built without self-update): a default toolchain
LEAN_STABLE="leanprover/lean4:stable"
chk_elan_tc(){
  local l; have elan || return 1
  l="$(elan toolchain list 2>/dev/null </dev/null)"
  [ -n "$l" ] || return 1
  case "$l" in *"no installed toolchains"*) return 1 ;; esac
}
inst_elan_tc(){ elan toolchain install "$LEAN_STABLE" && elan default "$LEAN_STABLE"; }
inst_elan(){
  if [ "$NO_PROFILE" = 1 ]; then remote_installer "$URL_ELAN" sh -y --default-toolchain stable --no-modify-path
  else remote_installer "$URL_ELAN" sh -y --default-toolchain stable; fi
}
# the open-file limit this process got from install.sh (resource limits are inherited)
nofile(){ if [ -n "${DEVTOOLS_NOFILE:-}" ]; then printf '%s' "$DEVTOOLS_NOFILE"; else ulimit -Sn; fi; }
LEAN_LIMIT_SAID=0; LEAN_LIMIT_OK=1
# below 65536 a real run skips the Lean group (said once); dry-run and report only note it
lean_limit_ok(){
  local n; n="$(nofile)"
  case "$n" in unlimited) return 0 ;; ''|*[!0-9]*) n=0 ;; esac
  [ "$n" -lt "$LEAN_NOFILE_MIN" ] || return 0
  if [ "$LEAN_LIMIT_SAID" = 0 ]; then
    LEAN_LIMIT_SAID=1
    if [ "$MODE" = install ]; then
      LEAN_LIMIT_OK=0
      line "! lean skipped: the open-file limit is $n (< $LEAN_NOFILE_MIN, which elan and lake need). Raise it, then rerun ./install.sh:"
      line "    its open-file limit step (first, on a terminal) installs /Library/LaunchDaemons/ulimit.max-files.plist and prints every command;"
      line "    for one shell only: sudo launchctl limit maxfiles 65536 524288; ulimit -Sn 65536"
    else
      line "  (lean: the open-file limit here is $n; a real run raises it first and skips Lean if it stays below $LEAN_NOFILE_MIN)"
    fi
  fi
  [ "$LEAN_LIMIT_OK" = 1 ]
}

upstream_step(){
  local nb
  if on UV; then
    ensure uv 0 chk_uv "astral.sh installer ($URL_UV, latest), else the uv $UV_VERSION tarball (sha256)" inst_uv
    path_add "$LOCAL_BIN"
    ensure "python $PYTHON_PIN (uv global pin)" 0 chk_pypin "uv python install $PYTHON_PIN && uv python pin --global $PYTHON_PIN" inst_pypin
  fi
  if on NODE; then
    # a node found anywhere: nvm and node 24 are skipped (nvm's installer never runs again)
    if find_cmd node; then
      skip_line node "$FOUND"; path_add "$(dirname "$FOUND")"
    else
      ensure nvm 0 chk_nvm "nvm $NVM_VERSION installer ($URL_NVM)" inst_nvm
      ensure "node $NODE_MAJOR (nvm)" 0 chk_node24 "nvm install $NODE_MAJOR" inst_node24
    fi
    nb="$(nvm_node_bin)" && path_add "$nb"
    # pnpm through corepack only on nvm's own node 24 (never written into another node's install)
    if nvm_node_bin >/dev/null; then
      ensure "pnpm (corepack)" 0 chk_pnpm "corepack enable pnpm; COREPACK_ENABLE_DOWNLOAD_PROMPT=0 pnpm -v" inst_pnpm
    else
      ensure "pnpm (corepack)" 0 chk_pnpm "corepack enable pnpm with your node (left to you: it writes into that node's install)" ""
    fi
  fi
  if on RUST; then
    ensure rustup 0 chk_rustup "rustup installer ($URL_RUSTUP, latest) -y" inst_rustup
    path_add "$HOME/.cargo/bin"
  fi
  if on HASKELL; then
    ensure ghcup 0 chk_ghcup "ghcup bootstrap ($URL_GHCUP, latest; non-interactive, with HLS and stack)" inst_ghcup
    path_add "$HOME/.ghcup/bin"; path_add "$HOME/.cabal/bin"
    # ghcup present, or (dry-run/report) about to be installed because no ghc exists either
    if have ghcup || { [ "$MODE" != install ] && ! find_cmd ghcup ghc; }; then
      ensure hlint 0 chk_hlint "ghcup install ghc $HLINT_GHC; cabal update; cabal install --ignore-project -w ghc-$HLINT_GHC hlint-$HLINT_VERSION --overwrite-policy=always" inst_hlint
    else   # a ghc that is not ghcup's (Homebrew, a GHC pkg): no side GHC from here, the command only
      ensure hlint 0 chk_hlint "hlint $HLINT_VERSION needs GHC $HLINT_GHC and your ghc is not ghcup's: cabal install --ignore-project -w ghc-$HLINT_GHC hlint-$HLINT_VERSION with that GHC" ""
    fi
    ensure ormolu 0 chk_ormolu "cabal update; cabal install --ignore-project ormolu-$ORMOLU_VERSION --overwrite-policy=always" inst_ormolu
  fi
  if on JULIA; then
    ensure juliaup 0 chk_juliaup "juliaup installer ($URL_JULIAUP, latest) --yes" inst_juliaup
  fi
  if on SCALA; then
    ensure coursier 0 chk_cs "cs from $URL_COURSIER (latest), then cs setup -y" inst_cs
  fi
  if on LEAN; then
    if [ -n "$BREW" ]; then
      # Homebrew's elan-init came with the batch (step 2); a fresh elan has no toolchain yet
      if [ "$ELAN_VIA_BREW" = 1 ] && { have elan || [ "$MODE" != install ]; }; then
        ensure "lean toolchain (stable)" 0 chk_elan_tc "elan toolchain install $LEAN_STABLE && elan default $LEAN_STABLE" inst_elan_tc
      fi
    # no Homebrew: the official installer (the fallback route). elan found anywhere: skipped whatever
    # the open-file limit (the limit gates installing only)
    elif chk_elan || lean_limit_ok; then
      ensure elan 0 chk_elan "elan installer ($URL_ELAN, latest; no Homebrew) -y --default-toolchain stable$([ "$NO_PROFILE" = 1 ] && echo ' --no-modify-path')" inst_elan
    fi
    path_add "$HOME/.elan/bin"
  fi
  return 0
}

# ==== 4. required check ==========================================================================
chk_node(){ have node && have npx; }
chk_jq(){ find_cmd jq; }
inst_jq_binary(){
  set -- $(jq_target)
  [ -n "${1:-}" ] || return 1
  local d rc; d="$(tmpd)" || return 1
  mkdir -p "$LOCAL_BIN" && fetch_sum "https://github.com/jqlang/jq/releases/download/jq-$JQ_VERSION/jq-$1" "$2" "$d/jq" \
    && install -m 0755 "$d/jq" "$LOCAL_BIN/jq"
  rc=$?; rm -rf "$d"; return $rc
}
required_step(){
  # silent when present (step 3 already said so)
  if chk_uv; then :
  elif on DEPS; then ensure uv 1 chk_uv "uv $UV_VERSION release tarball (sha256 checked) into ~/.local/bin" inst_uv_tarball
  else ensure uv 1 chk_uv "install uv: https://docs.astral.sh/uv/ (STACK_INSTALL_UV=1 does it)" ""; fi
  chk_node || ensure "node + npx" 1 chk_node "Node.js 22.5+: STACK_INSTALL_NODE=1 (nvm), or Homebrew's node" ""
  if [ -z "$BREW" ] && on DEPS; then
    ensure jq 0 chk_jq "jq $JQ_VERSION release binary (sha256 checked) into ~/.local/bin" inst_jq_binary
  fi
  if [ -n "$MISSING_REQ" ] && [ "$MODE" = install ]; then
    printf '\ninstall.sh: required tools are missing and could not be installed:\n' >&2
    printf '%s' "$MISSING_REQ" | while IFS='|' read -r l c; do [ -n "$l" ] && printf '  %s — %s\n' "$l" "$c" >&2; done
    printf 'Install them, then rerun ./install.sh (the logs of failed installs are named above).\n' >&2
    return 3
  fi
  return 0
}

# ==== 5. the rest ================================================================================
chk_gitleaks(){ find_cmd gitleaks; }
inst_gitleaks_tarball(){
  set -- $(gitleaks_target)
  [ -n "${1:-}" ] || return 1
  local d rc; d="$(tmpd)" || return 1
  mkdir -p "$LOCAL_BIN" \
    && fetch_sum "https://github.com/gitleaks/gitleaks/releases/download/v$GITLEAKS_VERSION/gitleaks_${GITLEAKS_VERSION}_$1.tar.gz" "$2" "$d/g.tgz" \
    && tar -xzf "$d/g.tgz" -C "$d" gitleaks && install -m 0755 "$d/gitleaks" "$LOCAL_BIN/gitleaks"
  rc=$?; rm -rf "$d"; return $rc
}
chk_pre_commit(){ find_cmd pre-commit; }
inst_pre_commit(){
  have uv || { echo "uv is missing"; return 1; }
  uv tool install --python "$PRE_COMMIT_PYTHON" --exclude-newer "$PRE_COMMIT_EXCLUDE_NEWER" "pre-commit==$PRE_COMMIT_VERSION"
}
GRADLE_HOME_DIR="$LOCAL_OPT/gradle-$GRADLE_VERSION"
chk_gradle(){ find_cmd gradle; }
inst_gradle(){
  # already unpacked (an earlier run, or a link removed since): only the link is (re)made
  if [ ! -x "$GRADLE_HOME_DIR/bin/gradle" ]; then
    local d rc; d="$(tmpd)" || return 1
    mkdir -p "$LOCAL_OPT" && fetch_sum "$GRADLE_URL" "$GRADLE_SHA256" "$d/gradle.zip" \
      && unzip -q "$d/gradle.zip" -d "$d/x" && [ -x "$d/x/gradle-$GRADLE_VERSION/bin/gradle" ] \
      && rm -rf "$GRADLE_HOME_DIR" && mv "$d/x/gradle-$GRADLE_VERSION" "$GRADLE_HOME_DIR"
    rc=$?; rm -rf "$d"; [ "$rc" = 0 ] || return "$rc"
  fi
  mkdir -p "$LOCAL_BIN" && ln -sfn "$GRADLE_HOME_DIR/bin/gradle" "$LOCAL_BIN/gradle"
}
# Playwright's browsers go where Playwright looks by default (macOS ~/Library/Caches/ms-playwright)
# unless PLAYWRIGHT_BROWSERS_PATH says otherwise: readable by sandboxed runs, writable only from
# outside the sandbox (settings.json denyWrite), so no sandboxed command can plant a browser your
# terminal or the playwright MCP later starts.
pw_dir(){
  if [ -n "${PLAYWRIGHT_BROWSERS_PATH:-}" ] && [ "$PLAYWRIGHT_BROWSERS_PATH" != 0 ]; then printf '%s' "$PLAYWRIGHT_BROWSERS_PATH"
  elif [ "$(uname -s)" = Darwin ]; then printf '%s' "$HOME/Library/Caches/ms-playwright"
  else printf '%s' "${XDG_CACHE_HOME:-$HOME/.cache}/ms-playwright"; fi
}
# the revision Playwright $PLAYWRIGHT_VERSION uses, both browsers complete under the browsers path
chk_playwright(){
  local d; d="$(pw_dir)"
  [ -f "$d/chromium-$PLAYWRIGHT_CHROMIUM_REVISION/INSTALLATION_COMPLETE" ] \
    && [ -f "$d/chromium_headless_shell-$PLAYWRIGHT_CHROMIUM_REVISION/INSTALLATION_COMPLETE" ] \
    && FOUND="$d/chromium-$PLAYWRIGHT_CHROMIUM_REVISION"
}
inst_playwright(){
  have npx || { echo "npx is missing"; return 1; }
  npx -y "playwright@$PLAYWRIGHT_VERSION" install chromium chromium-headless-shell
}
chk_lfs(){ [ -n "$(git config --global --get filter.lfs.process 2>/dev/null)" ]; }
inst_lfs(){ git lfs install --skip-repo; }   # global filters only, never a repository's hooks

# The Mathlib project, by the repo's convention (lib/stack.env.example, the lean-formalization skill):
# `lake +stable new <name> math` (its lakefile requires Mathlib at the tag of its lean-toolchain), then
# `lake exe cache get` (the prebuilt cache) and `lake build` (cheap once the cache is there). A
# project LEAN_PROJECT_PATH names is used as it is, never touched.
chk_mathlib(){ local p="$LEAN_DEFAULT_PROJECT"; { [ -f "$p/lakefile.toml" ] || [ -f "$p/lakefile.lean" ]; } && [ -d "$p/.lake/build" ]; }
inst_mathlib(){
  local p="$LEAN_DEFAULT_PROJECT" tc rev
  have lake || { echo "lake is missing (elan installs it)"; return 1; }
  if [ ! -f "$p/lakefile.toml" ] && [ ! -f "$p/lakefile.lean" ]; then
    [ ! -e "$p" ] || { echo "$p exists and is not a Lake project: left alone"; return 1; }
    mkdir -p "$(dirname "$p")" && (cd "$(dirname "$p")" && lake +stable new "$(basename "$p")" math) || return 1
  fi
  tc="$(sed -n 's|^leanprover/lean4:\(v[0-9][^[:space:]]*\)$|\1|p' "$p/lean-toolchain" 2>/dev/null | head -n 1)"
  rev="$(sed -n 's/^rev = "\(.*\)"$/\1/p' "$p/lakefile.toml" 2>/dev/null | head -n 1)"
  echo "lean-toolchain: ${tc:-?}; Mathlib rev: ${rev:-?}"
  if [ -z "$tc" ] || [ "$rev" != "$tc" ]; then
    echo "Mathlib is not pinned to the lean-toolchain's tag: set rev = \"$tc\" in $p/lakefile.toml, then lake update mathlib"
    return 1
  fi
  # a failed cache download must not start a build of all of Mathlib (hours)
  (cd "$p" && lake exe cache get) || return 1
  (cd "$p" && lake build)
}
mathlib_step(){
  local p="$LEAN_USER_PROJECT" route m="${STACK_INSTALL_LEAN_MATHLIB:-auto}"
  case "$p" in ""|/*) ;; *) line "! LEAN_PROJECT_PATH=$p is not an absolute path (stack.env takes absolute paths only): ignored, no project made"; return 0 ;; esac
  if [ -n "$p" ]; then
    if [ -f "$p/lakefile.toml" ] || [ -f "$p/lakefile.lean" ]; then line "ok  mathlib project (LEAN_PROJECT_PATH=$p)"
    else line "! LEAN_PROJECT_PATH=$p has no lakefile: make the project there (lake +stable new <name> math; lake exe cache get) or point it at one"; fi
    return 0
  fi
  p="$LEAN_DEFAULT_PROJECT"
  route="cd $(dirname "$p") && lake +stable new $(basename "$p") math; cd $p && lake exe cache get && lake build  (about 8 GB: Mathlib's checkout and prebuilt cache)"
  if [ "$MODE" = install ] && ! chk_mathlib; then
    if [ "$m" = 0 ]; then line "! mathlib project not made (STACK_INSTALL_LEAN_MATHLIB=0) — $route"; return 0; fi
    if [ "$m" != 1 ] && [ "$TTY" != 1 ]; then
      line "! mathlib project not made (no terminal; STACK_INSTALL_LEAN_MATHLIB=1 makes it anyway) — $route"; return 0
    fi
    line "  Mathlib: a large download (about 8 GB on disk, 10-30 minutes); STACK_INSTALL_LEAN_MATHLIB=0 skips it"
  fi
  ensure "mathlib project" 0 chk_mathlib "$route" inst_mathlib
  if [ "$MODE" = install ] && chk_mathlib; then
    line "  set LEAN_PROJECT_PATH=$p in your stack.env (proof-checker's lean server reads it)"
  fi
  return 0
}

rest_step(){
  if on LEAN && lean_limit_ok; then
    mathlib_step
  fi
  if on DEVTOOLS; then
    if [ -z "$BREW" ] && on DEPS; then
      ensure gitleaks 0 chk_gitleaks "gitleaks $GITLEAKS_VERSION release tarball (sha256 checked) into ~/.local/bin" inst_gitleaks_tarball
    fi
    ensure pre-commit 0 chk_pre_commit "uv tool install --python $PRE_COMMIT_PYTHON --exclude-newer $PRE_COMMIT_EXCLUDE_NEWER pre-commit==$PRE_COMMIT_VERSION" inst_pre_commit
    ensure gradle 0 chk_gradle "gradle-$GRADLE_VERSION-all.zip from GitHub (sha256 checked) into ~/.local/opt, linked from ~/.local/bin/gradle" inst_gradle
    ensure "playwright browsers" 0 chk_playwright "npx -y playwright@$PLAYWRIGHT_VERSION install chromium chromium-headless-shell  (into $(pw_dir))" inst_playwright
  fi
  if on CXX && have git-lfs; then
    ensure "git lfs (global filters)" 0 chk_lfs "git lfs install --skip-repo" inst_lfs
  fi
  if on JAVA && [ "$MODE" = install ]; then
    local jh="${DEVTOOLS_JAVA_HOME_TOOL-/usr/libexec/java_home}"
    if [ -n "$jh" ] && [ -x "$jh" ]; then line "java: default JDK $("$jh" 2>/dev/null </dev/null || echo 'none found')"; fi
  fi
  if on POSTGRES && [ -n "$BREW" ] && [ "$MODE" = install ]; then
    line "postgresql@18 is keg-only: its binaries are in $("$BREW" --prefix postgresql@18 2>/dev/null </dev/null)/bin; brew services start postgresql@18 runs it"
  fi
  return 0
}

all(){
  local g off=""
  for g in $GROUPS_ALL; do on "$g" || off="$off $g"; done
  [ -z "$off" ] || line "groups off:$off"
  homebrew_step
  brew_step
  gopls_step
  upstream_step
  required_step || { summary; return 3; }
  rest_step
  summary
}
summary(){
  local w=""; [ "$N_WARN" = 0 ] || w=", $N_WARN warning(s) (WARN above)"
  case "$MODE" in
    install) line "summary: $N_INST installed, $N_SKIP skipped (already there), $N_FAIL failed, $N_MISS not installed$w" ;;
    dry-run) line "summary: $N_WOULD would be installed, $N_SKIP skipped (already there), $N_MISS not installable here$w" ;;
    report) line "summary: $N_MISS missing, $N_SKIP present$w" ;;
  esac
}

case "${1:-}" in
  all) all ;;
  # where NAME...: "PATH<tab>SOURCE" of the first one found (install.sh's own tools use the same rule)
  where) shift; find_cmd "$@" || exit 1; src_of "$FOUND"; printf '%s\t%s\n' "$FOUND" "$SRC" ;;
  *) echo "usage: devtools.sh all | where NAME..." >&2; exit 2 ;;
esac
