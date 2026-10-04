#!/usr/bin/env bash
# Claude Code multi-agent stack — installer for macOS (Apple Silicon first).
#   ./install.sh                 core install
#   ./install.sh --with-ml       also create the ML venv ($C/venvs/ml: PyTorch, Transformers, PEFT,
#                                 scikit-learn/XGBoost/LightGBM, MLX + mlx-lm on Apple Silicon; several GB)
#   ./install.sh --with-lsp      also install missing language servers (pyright, typescript-language-server,
#                                 rust-analyzer, kotlin-lsp; jdtls through step 2's LSP group; HLS,
#                                 LanguageServer.jl, Metals when ghcup, julia, cs are present) before
#                                 enabling the code-intelligence plugins; the end of step 10 says why
#                                 any server is still missing
#   ./install.sh --with-adobe    also build the After Effects MCP + install the Premiere connector (macOS)
#   ./install.sh --with-extra-plugins  also install Anthropic's skill-creator and math-olympiad
#                                 plugins (their skills load on demand)
#   ./install.sh --no-mcp        skip registering user-scope MCP servers
#   ./install.sh --no-plugins    skip plugins (document skills, code-intelligence/LSP plugins)
#   ./install.sh --keep-plugin-duplicates  keep the document-skills and skill-creator plugins enabled
#                                 where claude.ai syncs the same skills (default: disabled, one copy)
#   ./install.sh --replace-mcp   re-register exa/jina/wolfram/huggingface/wandb even if you configured them
#   ./install.sh --no-deps       skip every tool install (prerequisites, dev tools, magg, huetension,
#                                 serial-mcp, venvs) and the MCP dep prefetch (missing tools become warnings)
#   ./install.sh --no-profile    leave your shell rc file alone (don't add the stack.env source line)
#   ./install.sh --dry-run       print every change (files, removals, MCP, plugins, rc) and make none
#   ./install.sh --write-through-links  a symlinked agents/, skills/, ... dir (a dotfiles checkout)
#                                 stops the run unless you give this: it then writes the stack's
#                                 files through the link(s); nothing there is ever removed
#   ./install.sh --restore [DIR] put the config dir back as it was before an install (DIR: a backup;
#                                 default: the latest), then exit
#   ./install.sh --restore [DIR] --force  also put back saved symlinks that point outside the
#                                 config dir (--force is valid only with --restore)
#   ./install.sh --print-managed-settings  print an optional managed-settings.json that pins the
#                                 stack's guards against edits (you install it; see CONFIG.md)
#   ./install.sh --mcp-plan      print the MCP server add/migrate/replace/keep plan and make no changes
#   ./install.sh --diff          list what differs between this repo's dot-claude/ and the installed
#                                 config dir (repo-only, installed-only and changed agents, skills,
#                                 rules, hooks, scripts, hook wiring, magg entries); writes nothing,
#                                 runs from any branch, exit 0 (2: usage error). Takes only --config-dir
#   ./install.sh --yes           install without asking when the stack's files changed since the last
#                                 install (asked on the terminal; with no terminal, e.g. in CI, the
#                                 run stops unless --yes is given), and without the target question
#   ./install.sh --config-dir PATH  (or --config-dir=PATH) install into PATH instead of ~/.claude.
#                                 Precedence: --config-dir > CLAUDE_CONFIG_DIR > ~/.claude. PATH may
#                                 use ~ and be relative; symlinks are resolved and shown. Refused (exit
#                                 2, nothing changed): /, your home folder or a folder containing it,
#                                 anything inside this repo checkout, ~/.ssh ~/.gnupg ~/.aws ~/.kube
#                                 ~/.docker ~/Library/Keychains and system folders, a file, a folder
#                                 you can't write or create, the stack's state and backup folders, a
#                                 path with a control character or one of " ` $ \. A --config-dir
#                                 target that is a non-empty folder with no Claude Code files (none of
#                                 .stack-manifest.json settings.json .claude.json CLAUDE.md stack.env
#                                 agents/ skills/ rules/ hooks/ projects/ plugins/ ...) needs a yes on
#                                 the terminal; without one the run stops (under CLAUDE_CONFIG_DIR it
#                                 is only a warning).
#                                 Every run prints the target, how it was chosen and the .claude.json
#                                 it implies. On a terminal (stdin and stdout), a non-default or
#                                 ambiguous target (--config-dir other than ~/.claude, CLAUDE_CONFIG_DIR
#                                 set, or two differing stack installs) is confirmed first [y/N];
#                                 --yes, --no-prompt, --dry-run, --mcp-plan and runs without a terminal
#                                 never ask. A non-default folder works only with
#                                 export CLAUDE_CONFIG_DIR=PATH in your shell profile (~/.zshrc; bash:
#                                 ~/.bash_profile), and moving it later means reinstalling.
#   ./install.sh --no-prompt     never ask on the terminal: the target question is skipped (the run
#                                 proceeds, a foreign non-empty target stops it) and a changed stack
#                                 stops the run unless --yes is given
# Pruning (always on): in agents/ and skills/ every shipped file matches the stack's (an edited one is
# replaced), and of the rest only files the stack installed and nobody edited go (agents, skills and
# files of yours, and stack files you edited, stay); stack config the
# stack no longer ships (hooks, rules, magg catalog entries, MCP entries it registered, duplicate hook
# wiring) goes. There is no opt-out. Everything changed or removed is backed up first, into one
# backup outside the config dir,
# ${XDG_STATE_HOME:-~/.local/state}/claude-agent-stack-backups/<timestamp>-*/ (0700; agents can't
# read it), and the run prints the list and the restore command. A run that changes nothing makes
# no backup. Never touched: credentials, ~/.claude.json (MCP changes go through `claude mcp`),
# the claude.ai-synced skills, plugins' own files, projects and sessions.
# Step 2 installs what is missing (lib/devtools.sh, CONFIG.md §7 "Prerequisites and toolchains"):
# Homebrew, one brew batch per type, the upstream version managers, the dev tools; one line per
# tool, a present one never touched. Groups: STACK_INSTALL_<GROUP>=0 skips one (DEPS DEVTOOLS UV
# NODE RUST HASKELL JULIA SCALA JAVA LATEX CXX GO LEAN, all on), =1 adds POSTGRES, MONGODB or LSP
# (off; --with-lsp turns LSP, the jdtls formula, on unless STACK_INSTALL_LSP=0);
# STACK_INSTALL_LEAN_MATHLIB=1 makes the Mathlib project also without a terminal (=0 never).
# Before step 2: the open-file limit. On a terminal the run offers a LaunchDaemon
# (/Library/LaunchDaemons/ulimit.max-files.plist: launchd soft 65536, hard 524288) and asks [y/N];
# only a yes runs sudo (install, launchctl bootstrap). STACK_INSTALL_MAXFILES=ask (default) | 0
# (never; prints the commands) | 1 (no question, terminal only). Then the run raises its own soft
# limit to 65536 (else the highest accepted; below 65536 the Lean group is skipped).
# CLAUDE_CONFIG_DIR overrides the install target (default ~/.claude); --config-dir overrides both.
# STACK_CLAUDE_JSON overrides which JSON file the MCP plan reads (default: $C/.claude.json when
# CLAUDE_CONFIG_DIR is set, or --config-dir names another folder — Claude Code then uses only that
# file —, else ~/.claude.json). The installer never writes that file itself: every MCP change goes
# through `claude mcp`, run with CLAUDE_CONFIG_DIR pointing at the target.
# Runs from any clone location (also through a symlink to this script), with bash 3.2 or later.
set -euo pipefail

WITH_ADOBE=0; WITH_ML=0; WITH_LSP=0; WITH_EXTRA_PLUGINS=0; SKIP_MCP=0; SKIP_PLUGINS=0; REPLACE_MCP=0; FORCE=0; WRITE_LINKS=0; NO_DEPS=0
NO_PROFILE=0; MCP_PLAN=0; DEDUPE_PLUGINS=1; DRY_RUN=0; RESTORE=""; PRINT_MANAGED=0; ASSUME_YES=0; ORIG_ARGS="$*"
NO_PROMPT=0; CONFIG_DIR_SET=0; CONFIG_DIR_ARG=""; DIFF=0; DIFF_CONFLICT=""
i=0; argv=("$@")
while [ "$i" -lt "${#argv[@]}" ]; do
  a="${argv[$i]}"
  case "$a" in --diff|--config-dir|--config-dir=*|-h|--help) ;; *) [ -n "$DIFF_CONFLICT" ] || DIFF_CONFLICT="$a" ;; esac
  case "$a" in
    --diff) DIFF=1 ;;
    --with-adobe) WITH_ADOBE=1 ;;
    --with-ml) WITH_ML=1 ;;
    --with-lsp) WITH_LSP=1 ;;
    --with-extra-plugins) WITH_EXTRA_PLUGINS=1 ;;
    --no-mcp) SKIP_MCP=1 ;;
    --no-plugins) SKIP_PLUGINS=1 ;;
    --keep-plugin-duplicates) DEDUPE_PLUGINS=0 ;;
    --replace-mcp) REPLACE_MCP=1 ;;
    --force) FORCE=1 ;;
    --write-through-links) WRITE_LINKS=1 ;;
    --no-deps) NO_DEPS=1 ;;
    --no-profile) NO_PROFILE=1 ;;
    --mcp-plan) MCP_PLAN=1 ;;
    --dry-run) DRY_RUN=1 ;;
    --no-prune) echo "--no-prune was removed: the installer always prunes (the backup keeps what it removes or replaces; ./install.sh --restore puts it back; ./install.sh --dry-run shows the plan)"; exit 2 ;;
    --print-managed-settings) PRINT_MANAGED=1 ;;
    --yes|-y) ASSUME_YES=1 ;;
    --no-prompt) NO_PROMPT=1 ;;
    --config-dir)
      case "${argv[$((i + 1))]:-}" in
        ""|-*) echo "--config-dir needs a path (--config-dir PATH or --config-dir=PATH; ./-name for a folder starting with -)"; exit 2 ;;
      esac
      CONFIG_DIR_SET=1; CONFIG_DIR_ARG="${argv[$((i + 1))]}"; i=$((i + 1)) ;;
    --config-dir=*) CONFIG_DIR_SET=1; CONFIG_DIR_ARG="${a#--config-dir=}" ;;
    --restore)
      nxt="${argv[$((i + 1))]:-}"
      case "$nxt" in ""|-*) RESTORE=latest ;; *) RESTORE="$nxt"; i=$((i + 1)) ;; esac ;;
    --restore=*) RESTORE="${a#--restore=}" ;;
    -h|--help) sed -n '2,/^set -euo pipefail$/p' "$0" | sed '$d'; exit 0 ;;
    *) echo "unknown option: $a"; exit 2 ;;
  esac
  i=$((i + 1))
done
if [ "$FORCE" = 1 ] && [ -z "$RESTORE" ]; then
  echo "--force works only with --restore (it puts back saved symlinks that point outside the config dir)"; exit 2
fi
# Every python3 this script starts is isolated (security audit, CWE-427): -I puts neither the script's
# dir (lib/), the caller's cwd nor PYTHON* variables on sys.path, and -B with a pycache_prefix that
# cannot exist means no __pycache__ (a planted .pyc in the agent-writable repo) is ever read or
# written. Repo modules are loaded by file path (spec_from_file_location), never through sys.path.
PY_ISOLATE="-I -B -X pycache_prefix=/dev/null/claude-agent-stack-no-bytecode"
# shellcheck disable=SC2086
python3(){ command python3 $PY_ISOLATE "$@"; }
# Run from a Claude Code Bash command, the environment carries the sandbox's cache dirs (agent_guard
# SANDBOX_ENV: CARGO_HOME, UV_CACHE_DIR, GOMODCACHE, npm_config_cache, ...), which sandboxed agents
# can write: no installer, build or prefetch of this run may read from or write to them (security
# audit, CWE-427). Every exported variable naming that dir is dropped (PATH aside).
SANDBOX_DROPPED=""
for v in $(compgen -e); do
  [ "$v" = PATH ] || case "${!v}" in *"$HOME/.cache/claude-sandbox"*) unset "$v"; SANDBOX_DROPPED="$SANDBOX_DROPPED $v" ;; esac
done
[ -z "$SANDBOX_DROPPED" ] || printf 'install.sh: ignoring the sandbox cache variables of this shell:%s\n' "$SANDBOX_DROPPED" >&2
# --print-managed-settings: the JSON is the only thing on stdout (fd 3); progress goes to stderr
if [ "$PRINT_MANAGED" = 1 ]; then exec 3>&1 1>&2; fi
# the plugin lists the installer manages (tests/test_no_duplicates.py reads these two lines)
EXTRA_PLUGINS="skill-creator math-olympiad"
RETIRED_PLUGINS="mcp-server-dev@claude-plugins-official"
# macOS only. Linux support was dropped; the repo's own tests run the installer on Linux with
# STACK_ALLOW_NON_MACOS=1 (nothing else is supported there).
if [ "$(uname)" != "Darwin" ] && [ "${STACK_ALLOW_NON_MACOS:-0}" != 1 ]; then
  echo "claude-agent-stack installs on macOS only (this is $(uname))."
  exit 1
fi

# The repo is wherever this script really lives: follow a symlink to the script itself (a link in
# ~/bin, say) to the clone; a symlinked clone directory keeps its logical path. Spaces are fine.
self="${BASH_SOURCE[0]}"
while [ -L "$self" ]; do
  link="$(readlink "$self")"
  case "$link" in /*) self="$link" ;; *) self="$(dirname "$self")/$link" ;; esac
done
HERE="$(cd "$(dirname "$self")" && pwd)"
unset self link
STATE_PY="$HERE/lib/install_state.py"

# --diff: read-only comparison (lib/stack_diff.py), before anything that could write, merge or ask
if [ "$DIFF" = 1 ]; then
  [ -z "$DIFF_CONFLICT" ] || { echo "--diff takes only --config-dir (got $DIFF_CONFLICT)" >&2; exit 2; }
  if [ "$CONFIG_DIR_SET" = 1 ]; then
    exec python3 $PY_ISOLATE "$HERE/lib/stack_diff.py" --repo "$HERE" --config-dir "$CONFIG_DIR_ARG"
  fi
  exec python3 $PY_ISOLATE "$HERE/lib/stack_diff.py" --repo "$HERE"
fi

# ---- Main-branch rule (hard-coded; no flag or variable turns it off) ----------------------------
# The stack installs only from its repo's `main` branch, the same Git rule the agents follow
# (rules/claude-agent-stack.md → Git). Run from any other branch or worktree, the installer first
# fast-forwards local `main` to this checkout's commit (`git merge --ff-only`, in the worktree where
# `main` is checked out; if none, this checkout switches to `main`), then re-runs itself from the
# `main` checkout. Whatever blocks a fast-forward (uncommitted or untracked files here, uncommitted
# changes in the main checkout, diverged history) stops it before anything is installed, with the
# fix. It NEVER pushes: repo_git refuses push-like subcommands, and git hooks are off for these
# calls, so a post-merge or post-checkout hook cannot push either. Nothing else here pushes.
MAIN_BRANCH=main
guard_fail(){ printf '\ninstall.sh: main-branch rule — %s\n' "$1" >&2; shift; for l in "$@"; do printf '  %s\n' "$l" >&2; done; exit 1; }
repo_git(){
  local a sub="" skip=0
  for a in "$@"; do
    if [ "$skip" = 1 ]; then skip=0; continue; fi
    case "$a" in -C|-c) skip=1 ;; -*) ;; *) sub="$a"; break ;; esac
  done
  case "$sub" in push|send-pack) echo "install.sh: refusing 'git $sub' — the installer never pushes" >&2; return 97 ;; esac
  # core.fsmonitor names a program `status` would run (the repo's .git/config is agent-writable)
  GIT_TERMINAL_PROMPT=0 git -c core.hooksPath=/dev/null -c core.fsmonitor=false "$@" </dev/null
}
main_branch_rule(){
  local here_p top cur head main_sha label dirty main_wt target out ahead behind
  git --version >/dev/null 2>&1 || { echo "git is required (macOS: xcode-select --install)"; exit 1; }
  here_p="$(cd "$HERE" && pwd -P)"
  top="$(repo_git -C "$HERE" rev-parse --show-toplevel 2>/dev/null || true)"
  [ -n "$top" ] && top="$(cd "$top" && pwd -P)"
  [ "$top" = "$here_p" ] || guard_fail "$HERE is not a git checkout of claude-agent-stack." \
    "The installer runs only from the $MAIN_BRANCH branch of a git clone:" \
    "git clone <repository-url> claude-agent-stack && cd claude-agent-stack && ./install.sh"
  repo_git -C "$HERE" show-ref --verify -q "refs/heads/$MAIN_BRANCH" \
    || guard_fail "this clone has no local '$MAIN_BRANCH' branch." \
         "Create it from the commit you want installed (e.g. git -C '$HERE' branch $MAIN_BRANCH origin/$MAIN_BRANCH), then re-run."
  cur="$(repo_git -C "$HERE" symbolic-ref -q --short HEAD 2>/dev/null || true)"
  if [ "$cur" = "$MAIN_BRANCH" ]; then
    unset STACK_MAIN_REEXEC
    printf 'stack repo: %s (branch %s)\n' "$HERE" "$MAIN_BRANCH"
    return 0
  fi
  head="$(repo_git -C "$HERE" rev-parse --verify HEAD)"
  label="${cur:-detached HEAD $(repo_git -C "$HERE" rev-parse --short HEAD)}"
  [ "${STACK_MAIN_REEXEC:-}" != 1 ] || guard_fail "the re-run from the $MAIN_BRANCH checkout found $HERE on '$label' — stopping."
  [ "$MCP_PLAN" != 1 ] || guard_fail "$HERE is on '$label', not $MAIN_BRANCH, and --mcp-plan changes nothing (so it does not merge)." \
    "Run it from the checkout on $MAIN_BRANCH, or run ./install.sh here without --mcp-plan to fast-forward $MAIN_BRANCH first."
  [ "$DRY_RUN" != 1 ] || guard_fail "$HERE is on '$label', not $MAIN_BRANCH, and --dry-run changes nothing (so it does not merge)." \
    "Run it from the checkout on $MAIN_BRANCH, or run ./install.sh here without --dry-run to fast-forward $MAIN_BRANCH first."
  [ "$PRINT_MANAGED" != 1 ] || guard_fail "$HERE is on '$label', not $MAIN_BRANCH, and --print-managed-settings changes nothing (so it does not merge)." \
    "Run it from the checkout on $MAIN_BRANCH."
  [ -z "$RESTORE" ] || guard_fail "$HERE is on '$label', not $MAIN_BRANCH, and --restore installs nothing from the repo (so it does not merge)." \
    "Run it from the checkout on $MAIN_BRANCH."

  # 0. no filter driver in the repo's own git config (agent-writable, like .git/info/attributes): git
  # would run its clean command on `status` below and its smudge command on `switch` and `merge`
  out="$(repo_git -C "$HERE" config --show-scope --get-regexp '^filter\..*\.(clean|smudge|process)$' 2>/dev/null \
    | awk '$1 == "local" || $1 == "worktree" {print $2}' || true)"
  [ -z "$out" ] || guard_fail "the stack repo's git config sets a filter driver, which git would run as you while switching or merging:" \
    "$out" "Remove it (git -C '$HERE' config --unset <key>), then re-run ./install.sh."
  # 1. this checkout is clean: uncommitted or untracked files would not reach main
  dirty="$(repo_git -C "$HERE" status --porcelain --untracked-files=normal)"
  [ -z "$dirty" ] || guard_fail "$HERE ('$label') has uncommitted or untracked files, which would not reach $MAIN_BRANCH:" \
    "$(printf '%s\n' "$dirty" | head -n 20)" \
    "Commit them on '$label' (or remove them), then re-run ./install.sh."
  # 2. the history allows a fast-forward
  main_sha="$(repo_git -C "$HERE" rev-parse --verify "refs/heads/$MAIN_BRANCH")"
  if repo_git -C "$HERE" merge-base --is-ancestor "$head" "$main_sha"; then
    printf 'stack repo: %s is on %s; %s already contains it — installing from %s\n' "$HERE" "$label" "$MAIN_BRANCH" "$MAIN_BRANCH"
  elif ! repo_git -C "$HERE" merge-base --is-ancestor "$main_sha" "$head"; then
    ahead="$(repo_git -C "$HERE" rev-list --count "$main_sha..$head")"
    behind="$(repo_git -C "$HERE" rev-list --count "$head..$main_sha")"
    guard_fail "'$label' and $MAIN_BRANCH have diverged ($ahead commit(s) only on '$label', $behind only on $MAIN_BRANCH), so $MAIN_BRANCH cannot fast-forward." \
      "Commits on $MAIN_BRANCH that '$label' lacks:" \
      "$(repo_git -C "$HERE" log --oneline -n 10 "$head..$main_sha" | sed 's/^/  /')" \
      "Fix (no push involved): git -C '$HERE' rebase $MAIN_BRANCH   (or: git -C '$HERE' merge $MAIN_BRANCH)," \
      "resolve any conflicts, run the tests, then re-run ./install.sh here. In Claude Code, main-coder does this (Git rule)."
  fi
  # 3. where main is checked out; else this checkout switches to it
  main_wt="$(repo_git -C "$HERE" worktree list --porcelain \
    | awk -v ref="branch refs/heads/$MAIN_BRANCH" '/^worktree /{wt=substr($0, 10)} $0 == ref {print wt; exit}')"
  if [ -n "$main_wt" ]; then
    [ -d "$main_wt" ] || guard_fail "$MAIN_BRANCH is checked out at $main_wt, which no longer exists." \
      "Run git -C '$HERE' worktree prune, then re-run ./install.sh."
    target="$(cd "$main_wt" && pwd -P)"
    dirty="$(repo_git -C "$target" status --porcelain --untracked-files=no)"
    [ -z "$dirty" ] || guard_fail "the $MAIN_BRANCH checkout at $target has uncommitted changes, so it cannot fast-forward safely:" \
      "$(printf '%s\n' "$dirty" | head -n 20)" \
      "They are someone's work: commit them on $MAIN_BRANCH there (then '$label' must include them), or finish them first; then re-run."
  else
    target="$here_p"
    out="$(repo_git -C "$target" switch -q "$MAIN_BRANCH" 2>&1)" \
      || guard_fail "could not switch $target to $MAIN_BRANCH:" "$out"
  fi
  # 4. fast-forward main, then re-run from the main checkout
  if [ "$(repo_git -C "$target" rev-parse HEAD)" != "$head" ] && ! repo_git -C "$target" merge-base --is-ancestor "$head" HEAD; then
    if ! out="$(repo_git -C "$target" merge --ff-only -q "$head" 2>&1)"; then
      [ "$target" = "$here_p" ] && { if [ -n "$cur" ]; then repo_git -C "$target" switch -q "$cur"; else repo_git -C "$target" switch -q --detach "$head"; fi; } >/dev/null 2>&1
      guard_fail "git merge --ff-only $label failed in $target:" "$out" "Fix what git names above, then re-run ./install.sh."
    fi
    printf 'stack repo: fast-forwarded %s to %s (%s) in %s\n' "$MAIN_BRANCH" "$label" "$(repo_git -C "$target" rev-parse --short HEAD)" "$target"
  fi
  [ -x "$target/install.sh" ] || guard_fail "$target/install.sh is missing or not executable."
  printf 'stack repo: re-running the installer from the %s checkout %s\n' "$MAIN_BRANCH" "$target"
  STACK_MAIN_REEXEC=1 exec "$target/install.sh" ${1+"$@"}
}
# ---- Install target: --config-dir > CLAUDE_CONFIG_DIR > ~/.claude --------------------------------
# lib/install_state.py (config-dir) resolves and checks it; an unsafe target stops here, before the
# main-branch rule merges anything. Sets CD_PATH CD_EXPORT CD_DECISION and the banner, warning and
# question lines. Checked against this checkout and the repo's main checkout.
resolve_target(){
  local out k v tty=0 quiet=0 common repos
  [ -t 0 ] && [ -t 1 ] && tty=1
  [ "$DRY_RUN$MCP_PLAN$PRINT_MANAGED" != 000 ] && quiet=1
  repos=("$HERE")
  common="$(repo_git -C "$HERE" rev-parse --path-format=absolute --git-common-dir 2>/dev/null || true)"
  case "$common" in */.git) repos+=("${common%/.git}") ;; esac
  out="$(python3 "$STATE_PY" config-dir "$CONFIG_DIR_SET" "$CONFIG_DIR_ARG" "$tty" "$quiet" \
         "$ASSUME_YES" "$NO_PROMPT" "${repos[@]}")" || exit 2
  CD_PATH=""; CD_EXPORT=""; CD_DECISION=""; CD_BANNER=""; CD_WARN=""; CD_ASK=""
  while IFS=$'\t' read -r k v; do
    case "$k" in
      path) [ -n "$CD_PATH" ] || CD_PATH="$v" ;; export) CD_EXPORT="$v" ;; decision) CD_DECISION="$v" ;;
      banner) CD_BANNER="$CD_BANNER$v"$'\n' ;; warn) CD_WARN="$CD_WARN  $v"$'\n' ;; ask) CD_ASK="$CD_ASK$v"$'\n' ;;
    esac
  done < <(printf '%s\n' "$out")    # a pipe, not a here-document's temp file in $TMPDIR (agent-writable?)
  [ -n "$CD_PATH" ] || { echo "install.sh: could not resolve the install target"; exit 2; }
}
resolve_target
# The banner: always, on stdout (stderr under --print-managed-settings, whose stdout is the JSON).
show_banner(){ printf '\n%s' "$CD_BANNER"; [ -z "$CD_WARN" ] || printf '%s' "$CD_WARN"; CD_SHOWN=1; }
CD_SHOWN=0
# Refuse or ask before the main-branch rule can fast-forward main or switch this checkout. The re-run
# from the main checkout inherits the yes (same target, and only together with STACK_MAIN_REEXEC).
if [ "${STACK_MAIN_REEXEC:-}" = 1 ] && [ "${STACK_TARGET_CONFIRMED:-}" = "$CD_PATH" ]; then
  CD_DECISION=proceed
fi
unset STACK_TARGET_CONFIRMED
case "$CD_DECISION" in
  refuse)
    show_banner
    echo "install.sh: $CD_PATH is a non-empty folder with no Claude Code files, and there is no terminal to confirm it (or --yes/--no-prompt was given). Empty it, pick another folder, or run on a terminal and answer y. Nothing was changed." >&2
    exit 2 ;;
  ask)
    show_banner
    printf '\n%s' "$CD_ASK"
    if ! python3 "$STATE_PY" ask "Install into $CD_PATH? [y/N] "; then
      echo "install.sh: stopped before changing anything (answer was not y). Nothing was changed." >&2
      exit 1
    fi
    export STACK_TARGET_CONFIRMED="$CD_PATH" ;;
esac

main_branch_rule ${1+"$@"}
unset STACK_TARGET_CONFIRMED
# From here on nothing depends on the caller's directory (the stack repo, which sandboxed agents can
# write): no tool this run starts reads a planted uv.toml, .npmrc, node_modules, rust-toolchain.toml
# or module from it. A relative --restore DIR is made absolute first (the target already is).
case "$RESTORE" in ""|latest|/*) ;; *) RESTORE="$PWD/$RESTORE" ;; esac
cd / || exit 2

SRC="$HERE/dot-claude"
[ "$CD_SHOWN" = 1 ] || show_banner
# the claude commands this run starts (mcp, plugin) act on the target, as Claude Code will
case "$CD_EXPORT" in
  set) export CLAUDE_CONFIG_DIR="$CD_PATH" ;;
  unset) unset CLAUDE_CONFIG_DIR ;;
esac
C="$CD_PATH"
# The same (logical) path in every mode, so a dry run renders exactly what a real run would.
if [ "$DRY_RUN" = 1 ] || [ "$PRINT_MANAGED" = 1 ] || [ -n "$RESTORE" ]; then
  [ -d "$C" ] || [ "$DRY_RUN" = 1 ] || [ "$PRINT_MANAGED" = 1 ] || { echo "no config dir at $C"; exit 1; }
else
  mkdir -p "$C"
fi
if [ -d "$C" ]; then C="$(cd "$C" && pwd)"
else C="$(python3 -c 'import os, sys; print(os.path.abspath(sys.argv[1]))' "$C")"; fi
OS="$(uname)"
# Hook state (agent_guard.py) and the installer's backups. Backups live beside the state dir, not in
# it: the guard deletes state-dir folders idle for three days. Agents can't read or write either
# (settings.json deny rules, sandbox denyRead/denyWrite, the guard's protected paths).
STACK_STATE="${XDG_STATE_HOME:-$HOME/.local/state}/claude-agent-stack"
BACKUP_ROOT="${STACK_STATE}-backups"
# The local MCP servers' own uv/npm caches (sandbox denyWrite: sandboxed commands can't plant code there)
STACK_CACHE="${STACK_STATE}-cache"
STATE_PY="$HERE/lib/install_state.py"
STACK_COMMIT="$(git -C "$HERE" rev-parse --short HEAD 2>/dev/null || echo unknown)"
STACK_COMMIT_FULL="$(git -C "$HERE" rev-parse HEAD 2>/dev/null || echo unknown)"
# The working dir (the staged copy of $C, stack.env with your keys included, MCP entries on their way
# to `claude mcp`) lives inside the backup root: a real directory of yours, 0700 (a symlink there is
# refused), which agents can neither read nor write. A run that changes nothing (--dry-run,
# --mcp-plan, --print-managed-settings) and had to create the root removes it again, with the
# parent dirs it had to create for it (an XDG_STATE_HOME that did not exist yet, ~/.local/state).
BR_NEW_TOP="$(python3 -c 'import os, sys
p, top = os.path.abspath(sys.argv[1]), ""
while not os.path.lexists(p) and os.path.dirname(p) != p:
    top, p = p, os.path.dirname(p)
print(top)' "$BACKUP_ROOT")"
ROOT_STATE="$(python3 "$STATE_PY" private-root "$BACKUP_ROOT")" || exit 1
find "$BACKUP_ROOT" -maxdepth 1 -name '.work.*' -type d -mtime +1 -exec rm -rf {} + 2>/dev/null || true
WORK="$(mktemp -d "$BACKUP_ROOT/.work.XXXXXX")"
# the rest runs in $WORK: private (agents can neither read nor write it), and where macOS's bash 3.2
# falls back to for here-document temp files when /tmp is not writable (a sandboxed test run)
cd "$WORK" || exit 2
# A TMPDIR inherited from a Claude Code shell (/tmp/claude-<uid>, the sandbox's own temp dir) is
# agent-writable: bash 4+'s here-document files (written, closed, then reopened by name: the python
# scripts below), this run's mktemp files and dirs and every tool's temp files would sit where an agent
# can swap them (security re-check, CWE-377). Such a TMPDIR is replaced by $WORK/tmp for the whole run.
case "$(cd "${TMPDIR:-/tmp}" 2>/dev/null && pwd -P)/" in
  /private/tmp/claude*|/tmp/claude*|"$HOME/.cache/claude-sandbox/"*)
    mkdir -m 700 "$WORK/tmp" && export TMPDIR="$WORK/tmp" ;;
esac
cleanup(){
  rm -rf "$WORK"
  if [ "$ROOT_STATE" = created ] && [ "$DRY_RUN$PRINT_MANAGED$MCP_PLAN" != 000 ]; then
    rmdir "$BACKUP_ROOT" 2>/dev/null || true
    # then each empty parent this run created, up to the first one that existed before it
    local d="${BACKUP_ROOT%/*}"
    while [ -n "$BR_NEW_TOP" ] && case "$d/" in "$BR_NEW_TOP"/*) true ;; *) false ;; esac; do
      rmdir "$d" 2>/dev/null || break
      d="${d%/*}"
    done
  fi
}
trap cleanup EXIT
# --dry-run: nothing outside $WORK is written; commands that would change something are printed.
would(){ printf '  would: %s\n' "$*"; }
say(){ printf '\n\033[1m%s\033[0m\n' "$*"; }
note(){ printf '  %s\n' "$*"; }
have(){ command -v "$1" >/dev/null 2>&1; }
# rustup installs a rust-analyzer proxy even without the component: run it, don't just find it.
# --dry-run runs none of them (a rustup proxy writes ~/.rustup, julia ~/.julia): found counts, and
# LanguageServer.jl counts when an environment's Project.toml lists it.
lsp_works(){
  if [ "$DRY_RUN" = 1 ]; then
    local depot="${JULIA_DEPOT_PATH:-}"; depot="${depot%%:*}"; [ -n "$depot" ] || depot="$HOME/.julia"
    case "$1" in
      julia-languageserver) have julia && grep -qs '^LanguageServer *=' "$depot/environments/claude-lsp/Project.toml" "$depot"/environments/v*/Project.toml ;;
      *) have "$1" ;;
    esac
    return
  fi
  case "$1" in
  rust-analyzer) rust-analyzer --version >/dev/null 2>&1 ;;
  # LanguageServer.jl is a package, not a binary: loadable from the @claude-lsp environment (or the
  # default one, also on that load path)
  julia-languageserver) have julia && julia --startup-file=no --history-file=no --project=@claude-lsp \
    -e 'exit(Base.find_package("LanguageServer") === nothing ? 1 : 0)' >/dev/null 2>&1 ;;
  *) have "$1" ;; esac
}
# ~/.local/bin (uv, magg, huetension, npm --prefix installs) is APPENDED, so tools already on your
# PATH win — including a test double of `claude` — and the uv installer still sees the original PATH.
ORIG_PATH="$PATH"
case ":$PATH:" in *":$HOME/.local/bin:"*) ;; *) export PATH="$PATH:$HOME/.local/bin" ;; esac
MIN_CLAUDE=2.1.271

if [ -n "$RESTORE" ]; then
  say "Restore ($C)"
  RFLAGS=""; [ "$FORCE" = 1 ] && RFLAGS="--force"
  if [ "$DRY_RUN" = 1 ]; then
    python3 "$STATE_PY" restore "$C" "$RESTORE" "$BACKUP_ROOT" "$WORK" "$STACK_COMMIT" "$HOME" --dry-run $RFLAGS || exit 1
  else
    python3 "$STATE_PY" restore "$C" "$RESTORE" "$BACKUP_ROOT" "$WORK" "$STACK_COMMIT" "$HOME" $RFLAGS || exit 1
  fi
  # MCP entries (removed, or replaced by the stack's) come back from the backup, plugins it disabled
  # are enabled again. The entries go to `claude mcp add-json` through a 0600 file in $WORK, one per
  # line of the list, never through this shell's variables or a log.
  python3 - "$WORK/restore.json" "$WORK" >"$WORK/restore.tsv" <<'PY'
import json, os, sys
r, work = json.load(open(sys.argv[1])), sys.argv[2]
for kind in ("mcp_removed", "mcp_replaced"):
    for i, (name, entry) in enumerate(sorted(r[kind].items())):
        p = os.path.join(work, "mcp-%s-%d.json" % (kind, i))
        fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            json.dump(entry, f)
        print("%s\t%s\t%s" % (kind, name, p))
for pid in r["plugins_disabled"]:
    print("plugin\t%s\t-" % pid)
if r["undo"]:
    print("undo\t%s\t-" % r["undo"])
PY
  while IFS=$'\t' read -r kind name val; do
    case "$kind" in
      mcp_removed|mcp_replaced)
        if [ "$DRY_RUN" = 1 ]; then would "claude mcp add-json -s user $name <its entry in the backup>  (${kind#mcp_} by the install)"
        elif [ "$kind" = mcp_removed ] && claude mcp get "$name" >/dev/null 2>&1 </dev/null; then note "= MCP server $name exists — kept as is"
        else
          # already gone is fine; under set -e a failing `[ ] && cmd` would end the restore here
          if [ "$kind" = mcp_replaced ]; then claude mcp remove -s user "$name" >/dev/null 2>&1 </dev/null || true; fi
          if claude mcp add-json -s user "$name" "$(cat "$val")" >/dev/null 2>&1 </dev/null; then note "+ put back MCP server $name"
          else note "! put back MCP server $name yourself: claude mcp add-json -s user $name '<its entry in the backup.json>'"; fi
        fi ;;
      plugin)
        if [ "$DRY_RUN" = 1 ]; then would "claude plugin enable $name --scope user"
        elif claude plugin enable "$name" --scope user >/dev/null 2>&1 </dev/null; then note "+ re-enabled plugin $name"
        else note "! claude plugin enable $name --scope user"; fi ;;
      undo) [ -n "$name" ] && note "undo this restore: $0 --restore $name" ;;
    esac
  done <"$WORK/restore.tsv"
  [ "$DRY_RUN" = 1 ] && say "Dry run done: nothing was restored."
  exit 0
fi

say "1/11 Prerequisites"
# Run them, don't just look them up: on a Mac without the Command Line Tools /usr/bin/python3 and
# /usr/bin/git exist as stubs that only open the CLT installer.
python3 -c 'import sys; sys.exit(sys.version_info < (3, 8))' >/dev/null 2>&1 \
  || { echo "python3 (3.8+) is required and must run (macOS: xcode-select --install)"; exit 1; }
git --version >/dev/null 2>&1 || { echo "git is required (macOS: xcode-select --install)"; exit 1; }
have claude || [ "$PRINT_MANAGED" = 1 ] || { echo "Claude Code is required: curl -fsSL https://claude.ai/install.sh | bash"; exit 1; }
CLAUDE_V="$( { have claude && claude --version 2>/dev/null </dev/null; } | awk '{print $1}' || true)"
note "claude ${CLAUDE_V:-unknown}"
if [ -n "$CLAUDE_V" ] && [ "$(printf '%s\n%s\n' "$MIN_CLAUDE" "$CLAUDE_V" | sort -t. -k1,1n -k2,2n -k3,3n | head -n1)" != "$MIN_CLAUDE" ]; then
  note "! claude $CLAUDE_V is older than $MIN_CLAUDE, which this stack is built for — run: claude update"
fi
note "install target: $C"

# ==== stack-python (S2): the hooks' interpreter ===================================================
# Every hook (through bin/stack-hook), the status line, /stack-tree's hook and the MCP header helper
# run on one stable path, $C/bin/stack-python: a symlink to uv's managed Python 3.13 (uv's
# minor-version link, which survives patch upgrades; never a version-manager shim or a project venv).
# STACK_PYTHON (rendered as __PYTHON3__) is that path. Step 2 installs 3.13 when none is found; the
# link is made and smoke-tested after step 6, before step 7 writes the hook commands (they fail
# closed). A STACK_PYTHON already in the environment names another interpreter for the link: it
# must be Python >= 3.13 (an absolute path or a command on PATH).
STACK_PYTHON_TARGET=""
if [ -n "${STACK_PYTHON:-}" ]; then
  case "$STACK_PYTHON" in
    "$C/bin/stack-python") STACK_PYTHON_TARGET="$(python3 -c 'import os, sys; print(os.path.realpath(sys.argv[1]))' "$STACK_PYTHON")" ;;
    /*) STACK_PYTHON_TARGET="$STACK_PYTHON" ;;
    *) STACK_PYTHON_TARGET="$(command -v "$STACK_PYTHON" 2>/dev/null || true)" ;;
  esac
  if [ -z "$STACK_PYTHON_TARGET" ] || ! "$STACK_PYTHON_TARGET" -c 'import sys; sys.exit(sys.version_info < (3, 13))' >/dev/null 2>&1 </dev/null; then
    echo "STACK_PYTHON=$STACK_PYTHON is not a working Python >= 3.13, which the hooks need: unset it (the installer then uses uv's managed 3.13), or point it at one (uv python find 3.13)"
    exit 1
  fi
fi
STACK_PYTHON="$C/bin/stack-python"
export STACK_PYTHON
note "hook interpreter: $STACK_PYTHON -> ${STACK_PYTHON_TARGET:-the uv-managed Python 3.13 (step 2)}"
# ==== stack-python: END ===========================================================================

# ==== source snapshot (security re-check 2026-10-04: CWE-829, CWE-345, CWE-367) ==================
# This run installs exactly the files HEAD tracks under dot-claude/ (and the two tests/derive_*.py
# scripts copied into hooks/), read ONCE from the working tree into $WORK/src (private: agents can
# neither read nor write it); every later step reads that copy, never the repo, so a file swapped in
# the repo after this point never reaches $C. Each file is opened without following a link on any
# path component (O_NOFOLLOW) and must be a regular file. The supply review below compares those
# bytes, not git's index, with HEAD: the index (stat cache, assume-unchanged and skip-worktree bits,
# fsmonitor and untracked-cache data), .gitignore, .git/info/exclude and the repo's git config are all
# writable by an agent, so none of them can hide an edit; git runs with hooks, fsmonitor, the
# untracked cache, replace refs and your global excludes file off. Untracked and staged-only files
# are listed and never copied (commit a file to ship it); a file git's index marks assume-unchanged
# or skip-worktree stops the run, as does a symlink anywhere under dot-claude/.
# What the review covers: the whole shipped tree, the installer and all of lib/ (a file added there
# shows as untracked), the pinned requirements, tests/lint_agents.py (run in step 7) and the two
# tests/derive_*.py scripts. lib/assets (the README's images) is neither installed nor run: left out.
SUPPLY_PATHS="dot-claude install.sh lib requirements tests/lint_agents.py tests/derive_sched_model.py tests/derive_thresholds.py :(exclude)lib/assets"
SUPPLY_SHOW="${SUPPLY_PATHS% *} ':(exclude)lib/assets'"     # the same, quoted for pasting into a shell
SNAP_ROOT="$WORK/src"
SUPPLY_LIST="$WORK/supply-review.txt"
python3 - "$HERE" "$SNAP_ROOT" "$SUPPLY_LIST" "$C" "$SUPPLY_PATHS" <<'PY' || exit 1
import errno, hashlib, os, stat, subprocess, sys
here, root, out, c, supply = sys.argv[1:6]


def die(msg):
    sys.exit("install.sh: %s — nothing in %s was changed" % (msg, c))


GIT = ["git", "--no-replace-objects", "-c", "core.hooksPath=/dev/null", "-c", "core.fsmonitor=false",
       "-c", "core.untrackedCache=false", "-c", "core.excludesFile=/dev/null", "-c", "core.sparseCheckout=false",
       "-c", "core.commitGraph=false", "-C", here]     # the commit-graph file could name another tree for HEAD
ENV = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
ENV.update(GIT_TERMINAL_PROMPT="0", GIT_OPTIONAL_LOCKS="0")


def git(*args):
    p = subprocess.run(GIT + list(args), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                       stderr=subprocess.PIPE, env=ENV)
    if p.returncode:
        die("git %s failed in %s: %s" % (args[0], here, p.stderr.decode("utf-8", "replace").strip()[:300]))
    return p.stdout


def paths(blob):
    return [os.fsdecode(x) for x in blob.split(b"\0") if x]


def show(p):        # a name with control characters (a terminal escape could hide its line) is quoted
    return p if p.isprintable() else ascii(p)


spec = supply.split()
inc = [p for p in spec if not p.startswith(":")]
exc = [p[len(":(exclude)"):] for p in spec if p.startswith(":(exclude)")]


def under(p, xs):
    return any(p == x or p.startswith(x + "/") for x in xs)


# everything a later step reads or runs: the shipped tree, the derive scripts copied into hooks/, lib/
# (install_state.py, devtools.sh, stack.env.example), the pinned requirements and the lint script
COPY = ["dot-claude", "tests/derive_sched_model.py", "tests/derive_thresholds.py", "lib", "requirements",
        "tests/lint_agents.py"]
# a link anywhere under dot-claude/, tracked or not (a skill's notes.log -> ~/.ssh/id_ed25519, which
# .gitignore hides from the review): the stack ships none
links = sorted(os.path.relpath(os.path.join(r, n), here) for r, ds, fs in os.walk(os.path.join(here, "dot-claude"))
               for n in ds + fs if os.path.islink(os.path.join(r, n)))
if links:
    sys.exit("install.sh: %s is a symlink; the stack ships none — remove it (nothing in %s was changed)"
             % (", ".join(map(show, links[:5])), c))
index = [(e[0], e[2:]) for e in paths(git("ls-files", "-v", "-z", "--", *spec))]
hidden = sorted(p for t, p in index if t.islower() or t == "S")
if hidden:
    sys.stderr.write("install.sh: git's index marks these stack files assume-unchanged or skip-worktree, so git"
                     " status hides their edits:\n%s\n  clear the marks, then re-run: git -C '%s' update-index"
                     " --no-assume-unchanged --no-skip-worktree -- <file>...   (a sparse checkout: git -C '%s'"
                     " sparse-checkout disable)\n" % ("\n".join("    " + show(p) for p in hidden[:40]), here, here))
    die("the stack repo's index hides %d file(s) from the review" % len(hidden))
# .git/objects is agent-writable too, and git never re-hashes an object it reads: a blob and its tree
# chain rewritten in place (HEAD unchanged) would make ls-tree, status and prev..HEAD all agree with a
# tampered working tree. git fsck re-hashes every object; fsck.* keys in the repo's own config (skip
# lists, severities) could tell it to look away, so they are refused first.
_cfg = subprocess.run(GIT + ["config", "--show-scope", "--get-regexp", r"^fsck\."], stdin=subprocess.DEVNULL,
                      stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=ENV).stdout.decode("utf-8", "replace")
_fsck_keys = [ln.split()[1] for ln in _cfg.splitlines() if len(ln.split()) > 1 and ln.split()[0] in ("local", "worktree")]
if _fsck_keys:
    die("the stack repo's git config sets %s, which tells git fsck what to skip: remove it (git -C '%s' config"
        " --unset <key>)" % (", ".join(map(show, _fsck_keys[:5])), here))
_fsck = subprocess.run(GIT + ["fsck", "--no-dangling", "--no-reflogs", "--no-progress"], stdin=subprocess.DEVNULL,
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=ENV)
if _fsck.returncode:
    die("git fsck finds a damaged or altered object in %s, so HEAD cannot vouch for the review: %s"
        % (here, show((_fsck.stderr or _fsck.stdout).decode("utf-8", "replace").strip()[:200])))
fmt =git("rev-parse", "--show-object-format").decode().strip()
fmt = fmt if fmt in ("sha1", "sha256") else "sha1"
tree = {}
for ent in git("ls-tree", "-r", "-z", "--full-tree", "HEAD").split(b"\0"):
    meta, _, p = ent.partition(b"\t")
    p = os.fsdecode(p)
    if meta and under(p, inc) and not under(p, exc):
        tree[p] = meta.decode().split()


def open_nofollow(rel):
    """An fd on here/rel, following no link on any component (a swapped-in link is refused)."""
    d = os.open(here, os.O_RDONLY | os.O_DIRECTORY)
    try:
        parts = rel.split("/")
        for part in parts[:-1]:
            n = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=d)
            os.close(d)
            d = n
        return os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=d)
    finally:
        os.close(d)


changed = []
for rel in sorted(tree):
    mode, _kind, oid = tree[rel]
    if mode == "120000":
        die("%s is a symlink; the stack ships none" % show(rel))
    if mode not in ("100644", "100755"):
        die("%s is not a regular file in HEAD (mode %s)" % (show(rel), mode))
    try:
        fd = open_nofollow(rel)
    except OSError as e:
        if e.errno == errno.ENOENT:
            changed.append(" D " + show(rel))
            continue
        if e.errno == errno.ELOOP:
            die("%s is a symlink; the stack ships none" % show(rel))
        die("%s cannot be read as a regular file (%s)" % (show(rel), e.strerror))
    with os.fdopen(fd, "rb") as f:
        st = os.fstat(f.fileno())
        if not stat.S_ISREG(st.st_mode):
            die("%s is not a regular file" % show(rel))
        data = f.read()
    h = hashlib.new(fmt)
    h.update(b"blob %d\0" % len(data))
    h.update(data)
    exe = bool(st.st_mode & 0o100)
    if h.hexdigest() != oid or exe != (mode == "100755"):
        changed.append(" M " + show(rel))
    if under(rel, COPY):
        dst = os.path.join(root, rel)
        os.makedirs(os.path.dirname(dst), mode=0o700, exist_ok=True)
        wfd = os.open(dst, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o755 if exe else 0o644)
        with os.fdopen(wfd, "wb") as f:
            f.write(data)
# not in HEAD, so never copied: staged only (in the index) or untracked (and not ignored)
changed += ["A  %s  (staged, not committed: not installed)" % show(p) for _t, p in sorted(index) if p not in tree]
changed += ["?? %s  (untracked: not installed)" % show(p)
            for p in sorted(paths(git("ls-files", "-z", "--others", "--exclude-standard", "--", *spec)))]
with open(out, "w", encoding="utf-8", errors="surrogateescape") as f:
    f.write("".join(line + "\n" for line in changed))
PY
SRC="$SNAP_ROOT/dot-claude"
# lib/, the requirements and the lint script are run and read from the snapshot from here on (a file
# swapped in the repo after the review never runs); bash re-reading install.sh itself is inherent.
STATE_PY="$SNAP_ROOT/lib/install_state.py"

# Optional hardening the installer never installs itself (it would be root-owned): a
# managed-settings.json that repeats the stack's guard hook, its protected-path deny rules and its
# sandbox, so editing ~/.claude/settings.json can no longer switch them off. JSON on stdout,
# instructions on stderr: ./install.sh --print-managed-settings > managed-settings.json
if [ "$PRINT_MANAGED" = 1 ]; then
  python3 - "$SRC/settings.json" "$C" "$STACK_PYTHON" "$BACKUP_ROOT" "$STACK_CACHE" "$HOME" "$STACK_STATE" <<'PY' >&3
import json, sys
src, c, py, backups, cache, home, state = sys.argv[1:8]
text = open(src, encoding="utf-8").read()
for k, v in (("__CLAUDE_DIR__", c), ("__PYTHON3__", py), ("__STACK_BACKUPS__", backups),
             ("__STACK_CACHE__", cache), ("__HOME__", home), ("__STACK_STATE__", state)):
    text = text.replace(k, json.dumps(v)[1:-1])
s = json.loads(text)
deny = [r for r in s["permissions"]["deny"]
        if r.startswith(("Edit(//", "Read(//", "Read(~/")) or r.startswith(("Edit(.git", "Edit(.claude", "Edit(~/"))]
guard = [g for g in s["hooks"]["PreToolUse"] if "no-push" in json.dumps(g)]
sb = s["sandbox"]
managed = {
    "permissions": {"deny": deny},
    "hooks": {"PreToolUse": guard},
    "sandbox": {"enabled": True, "failIfUnavailable": True, "allowUnsandboxedCommands": False,
                "filesystem": {"denyWrite": sb["filesystem"]["denyWrite"], "denyRead": sb["filesystem"]["denyRead"]},
                "network": {"strictAllowlist": True, "allowedDomains": sb["network"]["allowedDomains"]},
                "credentials": sb.get("credentials", {})},
}
json.dump(managed, sys.stdout, indent=2)
sys.stdout.write("\n")
sys.stderr.write(
    "\nOptional hardening (CONFIG.md, 'Managed settings'). Review the JSON above, then install it yourself:\n"
    "  macOS: sudo mkdir -p '/Library/Application Support/ClaudeCode' && sudo cp managed-settings.json "
    "'/Library/Application Support/ClaudeCode/managed-settings.json'\n"
    "  Linux: sudo mkdir -p /etc/claude-code && sudo cp managed-settings.json /etc/claude-code/managed-settings.json\n"
    "Managed settings outrank ~/.claude/settings.json; an invalid file stops Claude Code from starting.\n"
    "Re-print and re-install it after an install that changed the stack's hook or deny rules.\n")
PY
  exit 0
fi

# MCP plan: which user-scope remote servers to add, migrate (plaintext key -> headersHelper),
# replace (--replace-mcp) or keep. Read-only: sets PLAN (action, name, desired JSON, previous
# JSON, reason — tab-separated) and CFG.
compute_mcp_plan() {
  local envfile="$C/stack.env"
  [ -f "$envfile" ] || envfile="$SNAP_ROOT/lib/stack.env.example"
  # stack.env is NOT sourced here: sourcing ran user code under set -u (an unset $VAR aborted the
  # installer, with exit 0 under bash 3.2's EXIT trap) and let an empty KEY= override a key already
  # exported in the environment. The plan parses it with the headersHelper's own parser instead.
  if [ -n "${STACK_CLAUDE_JSON:-}" ]; then
    CFG="$STACK_CLAUDE_JSON"
  elif [ -n "${CLAUDE_CONFIG_DIR:-}" ]; then
    CFG="$C/.claude.json"   # claude reads and creates it there under CLAUDE_CONFIG_DIR, even before it exists
  else
    CFG="$HOME/.claude.json"
  fi
  note "config read for the plan: $CFG (written only through 'claude mcp')"
  # Keys are never embedded: bin/mcp-headers reads them from stack.env at connection time.
  # wandb is registered only when WANDB_API_KEY is set (it has no anonymous access).
  # (Python writes to a temp file: bash 3.2, macOS's /bin/bash, mis-parses heredocs inside $(...).)
  local planfile
  planfile="$(mktemp "${TMPDIR:-/tmp}/stack-install.XXXXXX")"
  ENVFILE="$envfile" PARSER="$SRC/bin/mcp-headers" HELPER="$C/bin/mcp-headers" CFG="$CFG" PY="$STACK_PYTHON" \
    REPLACE_MCP="$REPLACE_MCP" python3 - >"$planfile" <<'PY'
import json, os, re, runpy
from pathlib import Path
from urllib.parse import urlsplit
cfg_path, helper = os.environ["CFG"], os.environ["HELPER"]
replace_all = os.environ.get("REPLACE_MCP") == "1"
mh = runpy.run_path(os.environ["PARSER"], run_name="mcp_headers")
fileenv = mh["read_env_file"](Path(os.environ["ENVFILE"]))
def e(var):
    """Exactly what bin/mcp-headers would send: a non-empty stack.env value, else the environment;
    a value the helper rejects (unexpanded $VAR, spaces) counts as no key."""
    v = (fileenv.get(var) or os.environ.get(var) or "").strip()
    return v if v and "$" not in v and mh["VALUE_RE"].fullmatch(v) else ""
def url_display(u):
    """scheme://host/path only: a query string (a literal API key on an unmigrated entry, say
    ?exaApiKey=...) or userinfo never reaches the plan's output."""
    p = urlsplit(str(u or ""))
    if not p.scheme:
        return str(u or "")
    netloc = p.hostname or ""
    if p.port:
        netloc += ":%d" % p.port
    return "%s://%s%s" % (p.scheme, netloc, p.path)
def endpoint_display(cur):
    """scheme+host+path for a URL entry; a masked placeholder for a stdio command entry, whose
    argv can itself carry a key (an env assignment, a `op run ... -- ...` wrapper, ...)."""
    if cur.get("url"):
        return url_display(cur["url"])
    return "(your own command)" if cur.get("command") else "?"
try:
    cfg = json.load(open(cfg_path))
except (OSError, ValueError):
    cfg = {}
existing = (cfg.get("mcpServers") or {}) if isinstance(cfg, dict) else {}
# the helper runs through the same absolute interpreter as the hooks (not `#!/usr/bin/env python3`)
helper_cmd = '"%s" "%s"' % (os.environ["PY"], helper)
# Exa: an explicit tools= list is the only way to get web_search_advanced_exa; agent_run is left out
# because requesting it without a key fails the connection (401), and keys may be added later.
EXA_URL = "https://mcp.exa.ai/mcp?tools=web_search_exa,web_fetch_exa,web_search_advanced_exa"
rows = [
    ("exa", "mcp.exa.ai", {"type": "http", "url": EXA_URL, "headersHelper": helper_cmd}),
    ("jina", "mcp.jina.ai", {"type": "http", "url": "https://mcp.jina.ai/v1?exclude_tools=search_jina_blog",
                             "headersHelper": helper_cmd}),
    ("wolfram", "agenttools.wolfram.com", {"type": "http", "url": "https://agenttools.wolfram.com/mcp"}),
    ("huggingface", "huggingface.co", {"type": "http", "url": "https://huggingface.co/mcp",
                                       "headersHelper": helper_cmd}),
]
if e("WANDB_API_KEY"):
    rows.append(("wandb", "mcp.withwandb.com", {"type": "http", "url": "https://mcp.withwandb.com/mcp",
                                                "headersHelper": helper_cmd}))
KEYVAR = {"exa": "EXA_API_KEY", "jina": "JINA_API_KEY", "huggingface": "HF_TOKEN", "wandb": "WANDB_API_KEY"}
# the stack's own helper, as any version registered it: [interpreter] <config>/bin/mcp-headers, each
# optionally quoted. Anything else (a wrapper such as `op run … -- …/mcp-headers`) is the user's.
STACK_HELPER = re.compile(r"""(?:(?:(["'])[^"']+\1|[^"'\s]+)\s+)?(["']?)[^"'\s]*/bin/mcp-headers\2""")
for name, host, desired in rows:
    cur = existing.get(name)
    save = "-"   # stack.env variable a literal key must be copied into before the entry is replaced
    if not isinstance(cur, dict):
        action, why = "add", "not configured"
    elif urlsplit(str(cur.get("url", ""))).hostname != host and not replace_all:
        action, why = "keep", "points elsewhere (%s), left alone" % endpoint_display(cur)
    else:
        literal = mh["key_from_entry"](name, cur)
        if replace_all:
            action, why = "replace", "--replace-mcp"
        elif cur.get("headers") or literal:
            action, why = "migrate", "key in plaintext config, moving it to headersHelper"
        elif "headersHelper" in desired and not cur.get("headersHelper"):
            action, why = "migrate", "no headersHelper yet, keys will come from stack.env"
        elif "headersHelper" in desired and not STACK_HELPER.fullmatch(str(cur.get("headersHelper")).strip()):
            action, why = "keep", "your own headersHelper (your own command) kept"
        elif "headersHelper" in desired and cur.get("headersHelper") != desired["headersHelper"]:
            action, why = "migrate", "the stack's headersHelper, now run by %s" % os.environ["PY"]
        elif cur.get("url") != desired["url"]:
            action, why = "keep", "your URL (%s) kept; the stack's is %s" % (
                url_display(cur.get("url")), url_display(desired["url"]))
        else:
            action, why = "keep", "up to date"
        if action != "keep" and literal and name in KEYVAR and not e(KEYVAR[name]):
            save = KEYVAR[name]
            why += "; its key is copied to stack.env as %s first" % save
    prev = json.dumps(cur) if isinstance(cur, dict) else "null"
    print("\t".join([action, name, json.dumps(desired), prev, save, why]))
PY
  PLAN="$(cat "$planfile")"
  rm -f "$planfile"
}

if [ "$MCP_PLAN" = 1 ]; then
  say "MCP plan (--mcp-plan: nothing is installed or changed)"
  compute_mcp_plan
  printf '%s\n' "$PLAN" | while IFS=$'\t' read -r action name _cfg _prev _save why; do
    [ -n "$name" ] && printf '%s\t%s\t%s\n' "$action" "$name" "$why"
  done
  exit 0
fi

# What changed in what this run installs since the last install (the manifest records the commit each
# install shipped), and edits not committed yet (the source snapshot above, over SUPPLY_PATHS). Read
# them before applying. On a terminal the run asks here, before step 2 changes anything (the venvs
# sync from requirements/) (--yes: don't).
SUPPLY_CHANGED=0
prev_commit="$(python3 -c 'import json, re, sys
try:
    v = json.load(open(sys.argv[1])).get("commit") or ""
except Exception:
    v = ""
print(v if re.fullmatch(r"[0-9a-f]{7,64}", str(v)) else "")' "$C/.stack-manifest.json" 2>/dev/null || true)"
if git -C "$HERE" rev-parse -q --verify HEAD >/dev/null 2>&1; then
  if [ -s "$SUPPLY_LIST" ]; then
    SUPPLY_CHANGED=1
    note "! uncommitted changes in the stack repo's shipped files or installer — this run installs (or runs) the M lines as they are in the working tree:"
    # every edit of a file HEAD tracks is listed; files not in HEAD (never copied) past the first 40 are counted
    grep -v '^[A?][A?] ' "$SUPPLY_LIST" | sed 's/^/      /' || true
    grep '^[A?][A?] ' "$SUPPLY_LIST" | head -n 40 | sed 's/^/      /' || true
    n_new="$(grep -c '^[A?][A?] ' "$SUPPLY_LIST" || true)"
    [ "${n_new:-0}" -le 40 ] || note "  ... and $((n_new - 40)) more file(s) not in HEAD (not installed)"
  fi
  if [ -n "$prev_commit" ] && [ "$prev_commit" != "$STACK_COMMIT_FULL" ]; then
    # shellcheck disable=SC2086
    if supply="$(git --no-replace-objects -c core.hooksPath=/dev/null -c core.fsmonitor=false -c core.quotePath=true \
                 -C "$HERE" diff --no-ext-diff --no-textconv --stat "$prev_commit" HEAD -- $SUPPLY_PATHS 2>/dev/null)"; then
      if [ -n "$supply" ]; then
        SUPPLY_CHANGED=1
        note "changes to the stack's shipped files and installer since the last install (${prev_commit:0:12}..$STACK_COMMIT):"
        n_supply="$(printf '%s\n' "$supply" | wc -l | tr -d ' ')"
        if [ "$n_supply" -gt 41 ]; then
          printf '%s\n' "$supply" | head -n 40 | sed 's/^/      /'
          note "  ... $((n_supply - 41)) more file(s);$(printf '%s\n' "$supply" | tail -n 1)"
        else
          printf '%s\n' "$supply" | sed 's/^/      /'
        fi
        note "review: git -C $HERE diff ${prev_commit:0:12} HEAD -- $SUPPLY_SHOW"
      fi
    else
      SUPPLY_CHANGED=1
      note "! the last install shipped commit ${prev_commit:0:12}, which this repo doesn't have: review the stack's files before applying"
    fi
  fi
fi

# the stack's files changed since the last install (above): ask before anything changes, on stdin and
# stderr when both are a terminal, else on the controlling terminal (`./install.sh 2>&1 | tee log`);
# with no terminal at all the run stops unless --yes says to go on (R4: never proceed unasked)
if [ "$SUPPLY_CHANGED" = 1 ] && [ "$DRY_RUN" = 0 ] && [ "$ASSUME_YES" = 0 ]; then
  q="The stack changed since the last install (listed above). Install it? (see the whole plan first: $0 --dry-run) [y/N] "
  ans=""
  if [ "$NO_PROMPT" = 1 ]; then
    echo "install.sh: the stack changed since the last install (listed above) and --no-prompt forbids asking: rerun with --yes to install it (--dry-run shows the whole plan). Nothing in $C was changed." >&2
    exit 1
  elif [ -t 0 ] && [ -t 2 ]; then
    printf '%s' "$q" >&2; read -r ans || true
  elif { : </dev/tty; } 2>/dev/null && { : >/dev/tty; } 2>/dev/null; then
    printf '%s' "$q" >/dev/tty; read -r ans </dev/tty || true
  else
    echo "install.sh: the stack changed since the last install (listed above) and there is no terminal to ask: rerun with --yes to install it (--dry-run shows the whole plan). Nothing in $C was changed." >&2
    exit 1
  fi
  case "$ans" in
    y|Y|yes|YES|Yes) ;;
    *) echo "install.sh: stopped before changing anything. Nothing in $C was changed." >&2; exit 1 ;;
  esac
fi

# ==== open-file limit (maxfiles): BEGIN ==========================================================
# Before step 2 installs anything: elan and lake (`lake exe cache get`), cargo, ghcup/cabal builds and
# brew open more files than macOS's default soft limit (256); elan needs 65536. Offered here: a
# LaunchDaemon that sets launchd's limit at every boot (soft 65536, hard 524288). Then this run raises
# its own soft limit, which every program it starts inherits (CONFIG.md §7 "Open-file limit").
# The ONE place install.sh calls sudo: only after y/yes on a terminal, only `install` (owner, group and
# mode in one step), `launchctl bootout|bootstrap system` and `rm -f` (a copy that differs from the
# template) on the one file below. Never in a dry run.
#   STACK_INSTALL_MAXFILES=ask (default: asks on a terminal, default answer No) | 0 (never: prints
#   the commands) | 1 (set by you: no question, still only on a terminal, never in --dry-run)
MF_DIR=/Library/LaunchDaemons
MF_LABEL=ulimit.max-files
MF_PLIST="$MF_DIR/$MF_LABEL.plist"
MF_SOFT=65536
# a fixed template: nothing is interpolated (the quoted heredoc); tests/test_install_devtools.py
# snapshots it and checks it against MF_SOFT
mf_plist(){
  cat <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>ulimit.max-files</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/launchctl</string>
    <string>limit</string>
    <string>maxfiles</string>
    <string>65536</string>
    <string>524288</string>
  </array>
  <key>RunAtLoad</key>
  <true/>
</dict>
</plist>
PLIST
}
# launchd's soft maxfiles (a number or "unlimited"; empty when launchctl can't say)
mf_launchd_soft(){ launchctl limit maxfiles 2>/dev/null | awk '$1 == "maxfiles" {print $2; exit}' || true; }
mf_ge(){ case "$1" in unlimited) return 0 ;; ''|*[!0-9]*) return 1 ;; esac; [ "$1" -ge "$2" ]; }
mf_loaded(){ launchctl print "system/$MF_LABEL" >/dev/null 2>&1; }
# other LaunchDaemons that set maxfiles (XML plists naming it); never touched, only reported
mf_others(){ grep -l '<string>maxfiles</string>' "$MF_DIR"/*.plist 2>/dev/null | grep -vxF "$MF_PLIST" || true; }
# mf_diff FILE: FILE -> the stack's plist, unified, indented (diff exits 1 on a difference)
mf_diff(){
  local t
  t="$(mktemp "${TMPDIR:-/tmp}/$MF_LABEL.diff.XXXXXX")" || return 0
  mf_plist >"$t"
  { diff -u "$1" "$t" || true; } | sed 's/^/      /'
  rm -f "$t"
}
mf_ask(){
  local ans=""
  printf '%s' "$1"; read -r ans || ans=""
  case "$ans" in y|Y|yes|YES|Yes) return 0 ;; *) return 1 ;; esac
}
mf_print_later(){
  note "to set it up later, in a terminal (sudo asks for your admin password):"
  note "  1. save this as ./$MF_LABEL.plist, then: plutil -lint ./$MF_LABEL.plist"
  mf_plist | sed 's/^/         /'
  note "  2. sudo install -m 644 -o root -g wheel ./$MF_LABEL.plist $MF_PLIST"
  note "  3. sudo launchctl bootstrap system $MF_PLIST   (already loaded: sudo launchctl bootout system $MF_PLIST first)"
  note "  check: launchctl limit maxfiles; or rerun ./install.sh in a terminal and answer y"
  note "  remove: sudo launchctl bootout system $MF_PLIST; sudo rm $MF_PLIST"
}
mf_show_plan(){
  note "Proposed: a LaunchDaemon that raises launchd's open-file limit at every boot to soft 65536,"
  note "hard 524288 (elan/Lean need 65536; macOS starts programs with 256)."
  note "  file: $MF_PLIST (owner root:wheel, mode 644), exactly:"
  mf_plist | sed 's/^/      /'
  note "  1. write it from the fixed template above to a temp file and check it: plutil -lint <temp file>"
  note "  2. sudo install -m 644 -o root -g wheel <temp file> $MF_PLIST  (then stat must show root:wheel 644)"
  if mf_loaded; then
    note "  3. sudo launchctl bootout system $MF_PLIST (loaded now), then sudo launchctl bootstrap system $MF_PLIST"
  else
    note "  3. sudo launchctl bootstrap system $MF_PLIST"
  fi
  note "  then: launchctl limit maxfiles (read-only check, one line)"
  note "sudo asks for your admin password through its own prompt (this script never sees it). Apps"
  note "already running keep their old limit: a re-login or reboot may be needed for them."
  note "Remove it later: sudo launchctl bootout system $MF_PLIST; sudo rm $MF_PLIST"
}
# after a yes: the three steps in order, stopping at the first failure
mf_install(){
  local tmp st soft="" i
  # in $WORK (0700, agents can neither read nor write it), not TMPDIR: the file waits there during
  # sudo's password prompt
  tmp="$(mktemp "$WORK/$MF_LABEL.XXXXXX")" || { note "! mktemp failed"; return 1; }
  mf_plist >"$tmp"
  if ! plutil -lint "$tmp" >/dev/null 2>&1; then rm -f "$tmp"; note "! 1. plutil -lint rejected the generated plist"; return 1; fi
  note "1. plutil -lint: OK"
  if ! sudo install -m 644 -o root -g wheel "$tmp" "$MF_PLIST"; then rm -f "$tmp"; note "! 2. sudo install failed"; return 1; fi
  rm -f "$tmp"
  st="$(stat -f '%Su:%Sg %Lp' "$MF_PLIST" 2>/dev/null || true)"
  note "2. $MF_PLIST: $st"
  [ "$st" = "root:wheel 644" ] || { note "! 2. expected owner root:wheel and mode 644"; return 1; }
  # load only the template's exact bytes; a file that differs is removed at once, since RunAtLoad
  # would load it at the next boot
  if [ "$(cat "$MF_PLIST" 2>/dev/null || true)" != "$(mf_plist)" ]; then
    if sudo rm -f "$MF_PLIST"; then note "! 2. $MF_PLIST differs from the template: removed, not loaded"
    else note "! 2. $MF_PLIST differs from the template: not loaded, and sudo rm failed — remove it yourself: sudo rm $MF_PLIST"; fi
    return 1
  fi
  if mf_loaded; then
    sudo launchctl bootout system "$MF_PLIST" || { note "! 3. sudo launchctl bootout system $MF_PLIST failed"; return 1; }
  fi
  if ! sudo launchctl bootstrap system "$MF_PLIST"; then
    # a bootout just before can still be finishing: one retry after a second
    sleep 1
    sudo launchctl bootstrap system "$MF_PLIST" || { note "! 3. sudo launchctl bootstrap system $MF_PLIST failed"; return 1; }
  fi
  note "3. launchctl bootstrap system: OK"
  for i in 1 2 3; do soft="$(mf_launchd_soft)"; mf_ge "$soft" "$MF_SOFT" && break; [ "$i" = 3 ] || sleep 1; done
  note "4. launchctl limit maxfiles: $(launchctl limit maxfiles 2>/dev/null | awk '{$1 = $1; print}')"
  mf_ge "$soft" "$MF_SOFT" || note "! launchd still reports soft ${soft:-unknown}: check with launchctl print system/$MF_LABEL"
  return 0
}
maxfiles_step(){
  local want="${STACK_INSTALL_MAXFILES:-ask}" tty=0 soft state=absent others o why=""
  # a real terminal only: a variable can take it away (DEVTOOLS_TTY=0), never stand in for one
  # (`test -t`, not `[ -t ]`: the tests simulate a terminal by replacing `test`)
  if [ "${DEVTOOLS_TTY:-}" != 0 ] && test -t 0 && test -t 1; then tty=1; fi
  case "$want" in ask|0|1) ;; *) note "! STACK_INSTALL_MAXFILES=$want is not ask, 0 or 1: treated as ask"; want=ask ;; esac
  soft="$(mf_launchd_soft)"
  if [ -f "$MF_PLIST" ]; then
    if [ "$(cat "$MF_PLIST" 2>/dev/null || true)" = "$(mf_plist)" ]; then state=same; else state=different; fi
  fi
  others="$(mf_others)"
  if mf_ge "$soft" "$MF_SOFT" && [ "$state" = same ]; then
    note "ok  open-file limit: launchd soft $soft ($MF_PLIST in place)"; return 0
  fi
  if mf_ge "$soft" "$MF_SOFT" && [ "$state" = absent ] && [ -n "$others" ]; then
    note "ok  open-file limit: launchd soft $soft, set by $(printf '%s ' $others)(the stack's $MF_PLIST is not needed)"; return 0
  fi
  note "launchd's open-file limit: soft ${soft:-unknown} (elan/Lean need $MF_SOFT)"
  if [ "$DRY_RUN" = 1 ]; then why="--dry-run"
  elif [ "$want" = 0 ]; then why="STACK_INSTALL_MAXFILES=0"
  elif [ "$NO_DEPS" = 1 ]; then why="--no-deps"
  elif [ "$tty" != 1 ]; then why="no terminal"
  elif [ "$want" = ask ] && [ "$NO_PROMPT$ASSUME_YES" != 00 ]; then why="--yes/--no-prompt never ask; STACK_INSTALL_MAXFILES=1 installs without the question"
  fi
  if [ -n "$why" ]; then
    note "not installed ($why): $MF_PLIST"
    mf_print_later; return 0
  fi
  mf_show_plan
  if [ "$want" = ask ] && ! mf_ask "  Install $MF_PLIST now (sudo, 3 steps above)? [y/N] "; then
    note "not installed (the answer was not y)"; mf_print_later; return 0
  fi
  if [ "$state" = different ] || [ -n "$others" ]; then
    if [ "$state" = different ]; then
      note "$MF_PLIST exists with other content (diff: now -> the stack's):"
      mf_diff "$MF_PLIST"
    fi
    printf '%s\n' "$others" | while IFS= read -r o; do
      [ -n "$o" ] || continue
      note "$o also sets maxfiles; it stays (remove: sudo launchctl bootout system $o; sudo rm $o). diff: it -> the stack's:"
      note "  both daemons run at boot in no fixed order (the last one's limit wins): remove $o if you keep the stack's"
      mf_diff "$o"
    done
    if [ "$want" = ask ] && ! mf_ask "  Write the stack's $MF_PLIST anyway$([ "$state" = different ] && echo ', replacing the one there')? [y/N] "; then
      note "not installed (the answer was not y)"; mf_print_later; return 0
    fi
  fi
  mf_install || { note "! the open-file limit step stopped at the step above; the run goes on"; mf_print_later; }
  return 0
}
# This run's own soft limit, raised for every program it starts (resource limits are inherited:
# elan, lake, rustup, cargo, brew, ghcup/cabal). launchctl's limit reaches only programs started
# after it, so this is done whatever happened above. 65536 refused: the highest value accepted.
MF_NOFILE=""
mf_raise_ulimit(){
  local cur hard perproc cap="" v
  cur="$(ulimit -Sn)"; hard="$(ulimit -Hn)"
  perproc="$(sysctl -n kern.maxfilesperproc 2>/dev/null || true)"
  if ! mf_ge "$cur" "$MF_SOFT"; then
    for v in "$hard" "$perproc"; do
      case "$v" in ''|unlimited|*[!0-9]*) ;; *) if [ -z "$cap" ] || [ "$v" -lt "$cap" ]; then cap="$v"; fi ;; esac
    done
    for v in "$MF_SOFT" $cap 49152 32768 16384 10240 8192 4096 2048 1024; do
      case "$cur" in ''|*[!0-9]*) ;; *) [ "$v" -gt "$cur" ] || continue ;; esac
      if ulimit -Sn "$v" 2>/dev/null; then break; fi
    done
  fi
  MF_NOFILE="$(ulimit -Sn)"
  note "open files for this run and every tool it starts: $MF_NOFILE (was $cur; hard $hard, kern.maxfilesperproc ${perproc:-unknown})"
  mf_ge "$MF_NOFILE" "$MF_SOFT" \
    || note "! below $MF_SOFT: elan/Lean may fail, so step 2 skips the Lean group (the commands above raise the limit)"
}
# ==== open-file limit (maxfiles): END ============================================================
say "Open-file limit (maxfiles), before anything is installed"
maxfiles_step
mf_raise_ulimit

say "2/11 Tools: prerequisites, dev tools, magg, huetension, serial-mcp, science and tools venvs"
# Supply chain (C7, CONFIG.md §7 "Supply chain"): what the stack installs itself is pinned to a version
# and, where the project publishes one, a checksum; the Python venvs install from hash-locked lockfiles
# (requirements/, 7-day cooldown); the stack's PEP 723 scripts resolve as of their header's
# exclude-newer date. NOT pinned beyond the top-level version: the uvx/npx MCP servers' dependencies
# (resolved at first start), and the upstream managers' official "latest" installers (rustup, nvm,
# ghcup, juliaup, coursier, elan, Homebrew: their URL and sha256 are logged, not checked).
# Prerequisites and toolchains are lib/devtools.sh's (pins, routes and groups there; CONFIG.md §7):
# Homebrew, one brew batch for every missing formula and one for every missing cask, the upstream
# managers (uv, nvm, rustup, ghcup, juliaup, coursier, elan), then gitleaks, pre-commit, Gradle,
# Playwright's Chromium and the Mathlib project. One line per tool, a present tool never touched, a failed optional install
# only reported; a required one (uv, node) still missing stops the run here.
#   --no-deps: no installs at all (missing tools are listed);
#   STACK_INSTALL_<GROUP>=0 skips a group (DEPS DEVTOOLS UV NODE RUST HASKELL JULIA SCALA JAVA LATEX
#   CXX GO LEAN), STACK_INSTALL_POSTGRES=1 / STACK_INSTALL_MONGODB=1 add those; LSP (jdtls) follows
#   --with-lsp unless STACK_INSTALL_LSP is set.
MAGG_VERSION=1.2.1                         # 1.3.0 (2026-09-26) is inside the 7-day cooldown
MAGG_EXCLUDE_NEWER=2026-09-22T00:00:00Z    # dependency cooldown for magg's own requirements
HUETENSION_VERSION=0.3.0
if [ "$NO_DEPS" = 1 ]; then DT_MODE=report; elif [ "$DRY_RUN" = 1 ]; then DT_MODE=dry-run; else DT_MODE=install; fi
note "prerequisites and toolchains (lib/devtools.sh):"
# the Lean group uses your LEAN_PROJECT_PATH (stack.env, else the environment) instead of making a project
# (read by bin/mcp-headers' read_env_file, the stack's one stack.env parser: export, quotes, comments)
lean_proj="$(python3 -c 'import runpy, sys; from pathlib import Path
print(runpy.run_path(sys.argv[1], run_name="mcp_headers")["read_env_file"](Path(sys.argv[2])).get("LEAN_PROJECT_PATH", ""))' \
  "$SRC/bin/mcp-headers" "$C/stack.env" 2>/dev/null || true)"
[ -n "$lean_proj" ] || lean_proj="${LEAN_PROJECT_PATH:-}"
dt_rc=0
# --no-prompt: never ask, also not through Homebrew's installer or the pkg casks
dt_tty="${DEVTOOLS_TTY:-}"; [ "$NO_PROMPT" = 1 ] && dt_tty=0
STACK_INSTALL_LSP="${STACK_INSTALL_LSP:-$WITH_LSP}" DEVTOOLS_TTY="$dt_tty" DEVTOOLS_LEAN_PROJECT="$lean_proj" DEVTOOLS_MODE="$DT_MODE" DEVTOOLS_NO_PROFILE="$NO_PROFILE" bash "$SNAP_ROOT/lib/devtools.sh" all || dt_rc=$?
# a required tool still missing: devtools.sh listed each with its command
[ "$dt_rc" = 3 ] && exit 1
[ "$dt_rc" = 0 ] || note "! lib/devtools.sh exited $dt_rc (see above); the install goes on"
# what devtools.sh installed must be found below, also before your shell profile has its PATH line:
# Homebrew's bin dir, nvm's node 24, rustup's, ghcup's and elan's bins; appended, so your own PATH order wins.
# DEVTOOLS_SYSTEM_DIRS (tests: "") replaces the Homebrew prefixes, as it does in devtools.sh's lookup.
# shellcheck disable=SC2086
for b in ${DEVTOOLS_SYSTEM_DIRS-/opt/homebrew/bin /usr/local/bin} "$HOME/.cargo/bin" "$HOME/.ghcup/bin" "$HOME/.elan/bin" \
         "$HOME/.juliaup/bin" "$HOME/Library/Application Support/Coursier/bin"; do
  { [ -x "$b/brew" ] || [ -x "$b/cargo" ] || [ -x "$b/ghcup" ] || [ -x "$b/lake" ] || [ -x "$b/julia" ] || [ -x "$b/cs" ]; } || continue
  case ":$PATH:" in *":$b:"*) ;; *) PATH="$PATH:$b"; export PATH ;; esac
done
if ! have node; then
  for b in "${NVM_DIR:-$HOME/.nvm}"/versions/node/v24.*/bin; do [ -x "$b/node" ] && PATH="$PATH:$b" && export PATH && break; done
fi
huetension_target(){ case "$(uname -s)-$(uname -m)" in
  Darwin-arm64) echo "darwin_arm64 06515cb8a60275314d0d5a8a7c8bc455f34e644979f7c213c5200b9fefedc5b8" ;;
  Darwin-x86_64) echo "darwin_amd64 820915b40b75ddfb8a0e50f8e2c3b862066595d401f54722b67043aaefb8c9c6" ;;
  Linux-x86_64) echo "linux_amd64 af433e75fa0db503a9d71fc6930cd6cbaddff9d0077c4b71e22ed8e1972389c2" ;;
  Linux-aarch64|Linux-arm64) echo "linux_arm64 9179f76692822b59fe7ea7ddf03c42c49530474710e48562468835dee653bfac" ;;
esac; }
sha256_ok(){ printf '%s  %s\n' "$1" "$2" | shasum -a 256 -c - >/dev/null 2>&1; }
# fetch URL, check its sha256, extract MEMBER(s) of the tarball into DIR: fetch_verified URL SUM DIR MEMBER...
fetch_verified(){
  local url="$1" sum="$2" dir="$3"; shift 3
  local t; t="$(mktemp -d "${TMPDIR:-/tmp}/stack-install.XXXXXX")"
  if curl -fsSL -o "$t/a.tgz" "$url" && sha256_ok "$sum" "$t/a.tgz" && tar -xzf "$t/a.tgz" -C "$dir" "$@"; then
    rm -rf "$t"; return 0
  fi
  rm -rf "$t"; return 1
}
# tools venv: what the stack's own scripts, MCP servers and tests import (hooks stay stdlib on
# bin/stack-python). A future extra (e.g. a Bayesian stack) is its own lock, requirements/tools-<extra>.in
# starting with "-r tools.in", installed by pointing TOOLS_REQS at its .txt (requirements/README.md).
TOOLS_REQS="$SNAP_ROOT/requirements/tools.txt"
TOOLS_IMPORTS='import pytest, numpy, pandas, httpx, mcp, PIL, neural_memory'
venv_sync(){  # venv_sync NAME REQS [uv pip flags]: hash-locked install into $C/venvs/NAME (Python 3.13)
  local name="$1" reqs="$2"; shift 2
  local want=3.13 vdir="$C/venvs/$name" have=""
  case "$name" in ''|*[!A-Za-z0-9_-]*) note "! venv_sync: refusing venv name '$name'"; return 1 ;; esac
  # a venv built for another Python (3.12 before the move to 3.13) is rebuilt in place; only $C/venvs/NAME is touched
  if [ -x "$vdir/bin/python" ]; then
    have="$(sed -n 's/^version_info *= *\([0-9]*\.[0-9]*\).*/\1/p' "$vdir/pyvenv.cfg" 2>/dev/null | head -n 1)"
    [ -z "$have" ] || [ "$have" = "$want" ] || {
      note "venv $name is Python $have, rebuilding with Python $want"
      uv venv --quiet --clear --python "$want" "$vdir" || return 1
    }
  fi
  [ -x "$vdir/bin/python" ] || uv venv --quiet --python "$want" "$vdir"
  uv pip install --quiet --python "$C/venvs/$name/bin/python" --require-hashes "$@" -r "$reqs"
}
# serial-mcp: the magg catalog's `serial` server (embedded-engineer, through mcp-broker), built from
# crates.io with cargo when cargo exists; Rust itself is never installed here. The pinned version
# lives in one place, the catalog entry's notes ("cargo install serial-mcp@X --locked"); --root puts
# the binary where the entry's command looks (__HOME__/.cargo/bin), whatever CARGO_INSTALL_ROOT says.
SERIAL_MCP_VERSION="$(python3 -c 'import json, re, sys
try:
    n = json.load(open(sys.argv[1]))["servers"]["serial"]["notes"]
except Exception:
    n = ""
m = re.search(r"cargo install serial-mcp@([0-9][0-9A-Za-z.+-]*) --locked", n)
print(m.group(1) if m else "")' "$SRC/magg/config.json" 2>/dev/null || true)"
SERIAL_MCP_BIN="$HOME/.cargo/bin/serial-mcp"
SERIAL_MCP_CMD="cargo install serial-mcp@$SERIAL_MCP_VERSION --locked --root $HOME/.cargo"
cargo_bin(){ command -v cargo 2>/dev/null || { [ -x "$HOME/.cargo/bin/cargo" ] && echo "$HOME/.cargo/bin/cargo"; } || true; }
# the pinned serial-mcp is in place (a binary cargo has no record of is yours, and stays)
# The skip rule (lib/devtools.sh, CONFIG.md §7): a tool found anywhere is never installed, upgraded
# or replaced; another version than the pin is a WARN with the command. tool_where NAME: "PATH<tab>SOURCE".
tool_where(){ bash "$SNAP_ROOT/lib/devtools.sh" where "$@" 2>/dev/null; }
tool_skip(){ local w tab; tab="$(printf "\t")"; w="$(tool_where "$1")" || return 1; note "skip $1 (found: ${w%%"$tab"*}, from ${w#*"$tab"})"; }
serial_mcp_current(){
  [ -x "$SERIAL_MCP_BIN" ] || return 1
  local rec; rec="$(grep -o '"serial-mcp [^ ]*' "$HOME/.cargo/.crates2.json" 2>/dev/null | head -n 1 | cut -d' ' -f2 || true)"
  [ -z "$rec" ] || [ "$rec" = "$SERIAL_MCP_VERSION" ] \
    || note "WARN serial-mcp $rec found, the catalog pins $SERIAL_MCP_VERSION; left alone. To align: $SERIAL_MCP_CMD --force"
  return 0
}
serial_mcp_step(){  # serial_mcp_step install|plan (plan: --dry-run, lists the build)
  if [ -z "$SERIAL_MCP_VERSION" ]; then
    note "! serial-mcp: no pinned version in the serial entry of $HERE/dot-claude/magg/config.json — skipped"; return 0
  fi
  if serial_mcp_current; then note "skip serial-mcp (found: $SERIAL_MCP_BIN, from rustup/cargo)"; return 0; fi
  local cargo; cargo="$(cargo_bin)"
  if [ -z "$cargo" ]; then
    note "serial-mcp: skipped, no cargo (install Rust, then rerun or: $SERIAL_MCP_CMD)"; return 0
  fi
  if [ "$1" = plan ]; then would "$SERIAL_MCP_CMD"; return 0; fi
  note "building serial-mcp $SERIAL_MCP_VERSION with cargo (a few minutes the first time)"
  if "$cargo" install "serial-mcp@$SERIAL_MCP_VERSION" --locked --root "$HOME/.cargo" </dev/null; then
    note "+ serial-mcp $SERIAL_MCP_VERSION in $HOME/.cargo/bin"
  else
    note "! serial-mcp $SERIAL_MCP_VERSION build failed — $SERIAL_MCP_CMD"
  fi
}
if [ "$NO_DEPS" = 1 ] || [ "$DRY_RUN" = 1 ]; then
  if [ "$NO_DEPS" = 1 ]; then note "--no-deps: skipping brew/uv/node/magg/huetension/serial-mcp/venv installs"
  else note "--dry-run: listing the tool installs a real run would do"; fi
  miss(){ if [ "$DRY_RUN" = 1 ] && [ "$NO_DEPS" = 0 ]; then would "$2"; else note "! $1 missing — $2"; fi; }
  tool_skip magg || miss magg "uv tool install --exclude-newer $MAGG_EXCLUDE_NEWER magg==$MAGG_VERSION"
  tool_skip huetension || miss huetension "install huetension v$HUETENSION_VERSION (checksummed release tarball; designer works without it)"
  if [ "$DRY_RUN" = 1 ] && [ "$NO_DEPS" = 0 ]; then serial_mcp_step plan; fi
  if [ -x "$C/venvs/sci/bin/python" ]; then [ "$DRY_RUN" = 1 ] && [ "$NO_DEPS" = 0 ] && would "sync $C/venvs/sci to requirements/sci.txt (--require-hashes)"
  else miss "science venv at $C/venvs/sci" "uv venv $C/venvs/sci && uv pip install --require-hashes --only-binary :all: -r requirements/sci.txt"; fi
  if [ -x "$C/venvs/tools/bin/python" ]; then [ "$DRY_RUN" = 1 ] && [ "$NO_DEPS" = 0 ] && would "sync $C/venvs/tools to $TOOLS_REQS (--require-hashes)"
  else miss "tools venv at $C/venvs/tools" "uv venv --python 3.13 $C/venvs/tools && uv pip install --require-hashes --only-binary :all: -r requirements/$(basename "$TOOLS_REQS")"; fi
else
  # context-mode (researcher, doc-specialist) needs Node >= 22.5, typescript-language-server 6
  # (--with-lsp) >= 22, premiere-pro-mcp >= 20.19.
  node -e 'const [a, b] = process.versions.node.split(".").map(Number); process.exit(a > 22 || (a === 22 && b >= 5) ? 0 : 1)' 2>/dev/null \
    || note "! node $(node --version 2>/dev/null) is older than 22.5 — upgrade (brew upgrade node / nvm install 22); context-mode, some npx MCP servers and the TypeScript language server need it"
  # magg pinned; its dependencies resolved as of the cooldown date. A magg found anywhere is left
  # alone (the skip rule); another version than the pin is a WARN with the command.
  if tool_skip magg; then
    mv_="$("$(tool_where magg | cut -f1)" --version 2>/dev/null | awk '{print $2}' || true)"
    [ "$mv_" = "$MAGG_VERSION" ] || note "WARN magg ${mv_:-?} found, the stack pins $MAGG_VERSION; left alone. To align: uv tool install --force --exclude-newer $MAGG_EXCLUDE_NEWER magg==$MAGG_VERSION"
  else
    uv tool install --quiet --exclude-newer "$MAGG_EXCLUDE_NEWER" "magg==$MAGG_VERSION" \
      && note "+ magg $MAGG_VERSION" \
      || note "! magg $MAGG_VERSION install failed — uv tool install --exclude-newer $MAGG_EXCLUDE_NEWER magg==$MAGG_VERSION"
  fi
  if ! tool_skip huetension; then
    mkdir -p "$HOME/.local/bin"
    set -- $(huetension_target)
    d="$(mktemp -d "${TMPDIR:-/tmp}/stack-install.XXXXXX")"
    if [ -n "${1:-}" ] && fetch_verified "https://github.com/leporel/huetension/releases/download/v$HUETENSION_VERSION/huetension_${HUETENSION_VERSION}_$1.tar.gz" "$2" "$d" huetension; then
      install -m 755 "$d/huetension" "$HOME/.local/bin/huetension"
    elif have go; then
      # module checksums come from sum.golang.org (default GOSUMDB); never GONOSUMDB/GOFLAGS=-insecure
      gobin="$(go env GOBIN 2>/dev/null)"; [ -n "$gobin" ] || gobin="$(go env GOPATH | cut -d: -f1)/bin"
      go install "github.com/leporel/huetension/cmd/huetension@v$HUETENSION_VERSION" \
        && ln -sf "$gobin/huetension" "$HOME/.local/bin/huetension" \
        || note "huetension: go install failed (needs Go >= 1.26; Go >= 1.21 fetches it automatically)"
    fi
    rm -rf "$d"
    have huetension && note "+ huetension $HUETENSION_VERSION" || note "! huetension missing — designer works without color MCP; see README"
  fi
  serial_mcp_step install
  if venv_sync sci "$SNAP_ROOT/requirements/sci.txt" --only-binary :all:; then note "science venv: $C/venvs/sci (hash-locked)"
  else note "! science venv install failed — uv pip install --python $C/venvs/sci/bin/python --require-hashes --only-binary :all: -r $HERE/requirements/sci.txt"; fi
  if venv_sync tools "$TOOLS_REQS" --only-binary :all:; then
    note "tools venv: $C/venvs/tools ($("$C/venvs/tools/bin/python" -c "$TOOLS_IMPORTS"'; print("imports ok")' 2>/dev/null || echo '! imports failed'))"
  else note "! tools venv install failed — uv pip install --python $C/venvs/tools/bin/python --require-hashes --only-binary :all: -r $TOOLS_REQS"; fi
fi

# ==== stack-python (S2): Python 3.13 for the hooks ================================================
# uv's managed 3.13 (never a project's .venv or uv.toml: --system --managed-python --no-project
# --no-config, the launcher's own lookup). Present: used, not touched. Missing: `uv python install
# 3.13` (configuration of uv, which step 2 already has); not under --no-deps or STACK_INSTALL_UV=0,
# printed under --dry-run. Still missing: the step after 6/11 stops the run before settings.json.
stack_python_find(){ have uv && uv python find --system --managed-python --no-project --no-config 3.13 2>/dev/null </dev/null || true; }
if [ -z "$STACK_PYTHON_TARGET" ]; then
  STACK_PYTHON_TARGET="$(stack_python_find)"
  if [ -n "$STACK_PYTHON_TARGET" ]; then
    note "Python 3.13 for the hooks: $STACK_PYTHON_TARGET (present)"
  elif ! have uv; then
    note "! no Python 3.13 for the hooks and no uv: install uv, then rerun ./install.sh"
  elif [ "$NO_DEPS" = 1 ] || [ "${STACK_INSTALL_UV:-1}" = 0 ]; then
    note "! no uv-managed Python 3.13 for the hooks (--no-deps / STACK_INSTALL_UV=0): uv python install 3.13, then rerun ./install.sh"
  elif [ "$DRY_RUN" = 1 ]; then
    would "uv python install 3.13   (the hooks' interpreter, linked as $STACK_PYTHON)"
  elif uv python install 3.13 </dev/null; then
    STACK_PYTHON_TARGET="$(stack_python_find)"
    note "+ Python 3.13 for the hooks: ${STACK_PYTHON_TARGET:-? (uv python find 3.13 found nothing after the install)}"
  else
    note "! uv python install 3.13 failed: the hooks need it (run it yourself, then rerun ./install.sh)"
  fi
fi
# ==== stack-python: END ===========================================================================

say "3/11 ML venv (--with-ml)"
if [ "$WITH_ML" = 0 ]; then
  if [ -x "$C/venvs/ml/bin/python" ]; then note "ML venv present: $C/venvs/ml (rerun with --with-ml to update)"; else note "skipped — ML agents use the project's environment or the science venv; add --with-ml for a shared ML venv"; fi
elif [ "$DRY_RUN" = 1 ]; then
  would "sync $C/venvs/ml to requirements/ml.txt (--require-hashes)"
elif [ "$NO_DEPS" = 1 ] || ! have uv; then
  note "! --with-ml needs uv and is skipped under --no-deps"
else
  # ml.txt holds one sdist-only package (rouge-score, hashed), so no --only-binary here
  if venv_sync ml "$SNAP_ROOT/requirements/ml.txt"; then
    note "ML venv: $C/venvs/ml ($("$C/venvs/ml/bin/python" -c 'import torch,transformers;print("torch",torch.__version__,"· transformers",transformers.__version__)' 2>/dev/null || echo 'installed'))"
  else
    note "! ML venv install failed — rerun ./install.sh --with-ml, or use project environments"
  fi
fi

say "4/11 Adobe (--with-adobe)"
# Runs before rendering: motion-designer gets the After Effects server only once its build exists.
AE="$C/mcp/vendor/after-effects-mcp"
AE_SHA=88d5fbf08b7ae9f015ee98e5f8c4904095cf8202    # pinned commit (has package-lock.json)
if [ "$WITH_ADOBE" = 0 ]; then
  if [ -f "$AE/build/index.js" ]; then note "After Effects MCP present (rerun with --with-adobe to update)"
  elif [ "$OS" = "Darwin" ]; then note "skipped — motion-designer gets the After Effects server once you run --with-adobe"
  else note "skipped (macOS only)"; fi
elif [ "$OS" != "Darwin" ]; then
  note "Adobe apps are macOS/Windows only — skipped"
elif [ "$DRY_RUN" = 1 ]; then
  would "check out after-effects-mcp at $AE_SHA in $AE, npm ci --ignore-scripts, npm run build, npm run install-bridge"
  would "npx -y premiere-pro-mcp@1.18.2 --install-cep"
else
  mkdir -p "$C/mcp/vendor"
  # Optional step: a failed fetch must not abort the installer (set -e) before the profile step, and
  # must never sit at a git credential prompt. The checkout is the pinned commit, verified; npm ci
  # installs exactly package-lock.json with install scripts off (the build runs explicitly).
  [ -d "$AE/.git" ] || GIT_TERMINAL_PROMPT=0 git clone -q https://github.com/Dakkshin/after-effects-mcp "$AE" </dev/null \
    || note "! After Effects MCP: git clone failed"
  if [ -d "$AE/.git" ]; then
    { GIT_TERMINAL_PROMPT=0 git -C "$AE" cat-file -e "$AE_SHA^{commit}" 2>/dev/null \
        || GIT_TERMINAL_PROMPT=0 git -C "$AE" fetch -q origin </dev/null; } \
      && git -C "$AE" -c advice.detachedHead=false checkout -q --detach "$AE_SHA" 2>/dev/null \
      || note "! After Effects MCP: could not check out $AE_SHA"
  fi
  if [ -d "$AE/.git" ] && [ "$(git -C "$AE" rev-parse HEAD 2>/dev/null)" = "$AE_SHA" ] && [ -f "$AE/package-lock.json" ]; then
    if (cd "$AE" && npm ci --ignore-scripts --no-audit --no-fund --silent && npm run -s build && test -f build/index.js); then note "+ After Effects MCP built ($AE_SHA)"
    else note "! After Effects MCP build failed — cd \"$AE\" && npm ci --ignore-scripts && npm run build"; fi
    if (cd "$AE" && npm run -s install-bridge); then note "+ After Effects bridge panel installed"
    else note "! AE bridge: close After Effects and run: cd \"$AE\" && npm run install-bridge  (may need sudo)"; fi
  else
    note "! After Effects MCP: not at the pinned commit $AE_SHA — not built"
  fi
  if (cd / && npx -y premiere-pro-mcp@1.18.2 --install-cep); then note "+ Premiere Pro CEP connector installed (restart Premiere; Window > Extensions > MCP for Adobe Premiere Pro)"
  else note "! Premiere connector: npx -y premiere-pro-mcp@1.18.2 --install-cep"; fi
  note "Illustrator: first tool call asks for Automation permission (System Settings > Privacy & Security > Automation)"
fi

say "5/11 Stage (a working copy of the stack's part of $C)"
# Nothing in $C changes until step 7 has validated the result: the stack's part of it (agents/,
# skills/ but the synced ones, rules/, hooks/, bin/, mcp/ but vendor/, stack-plugins/, magg's
# catalog, settings.json, stack.env, the manifest) is copied to $S, and steps 5-7 work there.
S="$WORK/stage"; REPORT="$WORK/report.json"; PLAN_JSON="$WORK/plan.json"; SNAP="$WORK/snapshot.json"
# A top-level dir of the stack's part that is a symlink (a dotfiles checkout: agents/, skills/, ...)
# holds your files: nothing there is ever removed, and the stack's files are written through the link
# only with --write-through-links (otherwise the run stops here; --dry-run shows what it would do).
LINKED="$(python3 "$STATE_PY" linked "$C")"; LINK_REFUSAL=""
if [ -n "$LINKED" ]; then
  while IFS=$'\t' read -r d target; do
    note "! $C/$d is a symlink to $target: yours; nothing there is removed"
  done <<EOF_LINKED
$LINKED
EOF_LINKED
  if [ "$WRITE_LINKS" = 0 ]; then
    LINK_REFUSAL="symlinked dir(s) above: rerun with --write-through-links to write the stack's files through the link(s) (nothing there is removed), or replace them with real directories. Nothing in $C was changed."
    if [ "$DRY_RUN" = 0 ]; then
      echo "install.sh: $LINK_REFUSAL" >&2
      exit 1
    fi
    note "! --dry-run: the real run stops here without --write-through-links; the plan below is what it would do with it"
  fi
fi
mkdir -p "$S"
python3 "$STATE_PY" stage "$C" "$S" "$SNAP"
note "staged in $S"

say "6/11 Render (agents, rules, skills, scripts, settings.json)"
# Everything below reads $SRC, the private source snapshot (regular files HEAD tracks, no links: a
# link under dot-claude/ already stopped the run there), never the repo (security audit, CWE-59/367).
mkdir -p "$S"/{agents,skills,hooks,mcp,magg,bin,rules}
# The stack's scripts replace whatever is staged there — a symlink too (removed first: a copy onto
# it would write through the link, out of the staging dir; the backup keeps the link).
stage_script(){ rm -rf "$S/$2" && cp "$SRC/$2" "$S/$2" && chmod "$1" "$S/$2"; }
stage_script 755 hooks/agent_guard.py
# every hook command runs /bin/sh bin/stack-hook (finds stack-python), which runs hooks/stack_hook.py
# (imports the hook module, so its bytecode in hooks/__pycache__ is reused)
stage_script 755 bin/stack-hook
stage_script 644 hooks/stack_hook.py
# /override-agent's built-in effort per (agent, model): read by agent_guard.py, beside it
stage_script 644 hooks/agent_effort.json
# per-call caps for exa/jina/spider and Spider's anti-bot defaults (PreToolUse ^mcp__(exa|jina|spider)__)
stage_script 755 hooks/web_caps.py
# the token gate on reads of build output, dependencies, data, media and binaries (PreToolUse Read|Grep|Glob|Bash)
stage_script 755 hooks/read_gate.py
# the hand-back protocol's parser and checks (STACK_REPORT_FORMAT): imported by agent_guard.py, beside it
stage_script 644 hooks/stack_report.py
# the hooks' shared file helpers (read_json, atomic writes, timestamps): imported by agent_guard.py,
# stack_usage.py, stack_limits.py, stack_fanout.py and stack_sched_refresh.py, beside them
stage_script 644 hooks/stack_io.py
# the usage collector (SubagentStart/SessionEnd hooks; agent_guard.py starts it at SessionStart), the
# scheduler advisor, its shipped cost model and the refit (stack_sched_refresh.py imports fit() from the
# two tests/ scripts beside it), and the learned limits (stack_limits.py: per-session snapshots the
# guard reads; its seed: the floors, ceilings and starting values)
for f in stack_usage.py stack_sched.py stack_limits.py stack_fanout.py; do stage_script 755 "hooks/$f"; done
for f in stack_sched_refresh.py sched_model.json stack_limits_seed.json stack_fanout_wire.py; do stage_script 644 "hooks/$f"; done
for f in derive_sched_model.py derive_thresholds.py; do
  rm -rf "$S/hooks/$f" && cp "$SNAP_ROOT/tests/$f" "$S/hooks/$f" && chmod 644 "$S/hooks/$f"
done
for f in statusline.py doctor.sh with-stack-env mcp-headers magg-private claude-ultracode stack_sdk.py stack-budget stack-tree; do stage_script 755 "bin/$f"; done
stage_script 755 "bin/stack-who"
for f in image_studio_mcp.py libdocs_mcp.py neural_memory_mcp.py; do stage_script 644 "mcp/$f"; done
stage_script 644 magg/k8s-mcp.toml    # the magg catalog's kubernetes entry reads it (--config)
# The stack's local LSP marketplace (step 10 registers it): replaced as a whole.
if [ "$SKIP_PLUGINS" = 0 ] && [ -d "$SRC/stack-plugins" ]; then
  rm -rf "$S/stack-plugins" && cp -R "$SRC/stack-plugins" "$S/stack-plugins"
fi
[ -f "$S/stack.env" ] || cp "$SNAP_ROOT/lib/stack.env.example" "$S/stack.env"
chmod 600 "$S/stack.env"
# Variables stack.env.example gained since your stack.env was created: appended with their comment
# lines, commented out — except the image models, appended set to image-studio's own defaults (the
# same models either way, now named where you change them), and the Claude model variables, appended
# set to the stack's IDs (step 7 copies them into settings.json's env). A key already in your file,
# even commented out, is never added again, and a value you wrote is never changed. The
# image comment lines earlier versions of stack.env.example put in your file get today's wording;
# the previous file is kept in the backup folder.
python3 - "$SNAP_ROOT/lib/stack.env.example" "$S/stack.env" <<'PY'
import os, re, sys, time
example, target = sys.argv[1], sys.argv[2]
VAR = re.compile(r"^\s*(?:#\s?)?(?:export\s+)?([A-Z][A-Z0-9_]*)=")
LIVE = {"IMAGE_STUDIO_SVG_MODEL", "IMAGE_STUDIO_IMAGE_MODEL", "IMAGE_STUDIO_EDIT_MODEL"}
MODELS = {"ANTHROPIC_DEFAULT_OPUS_MODEL", "ANTHROPIC_DEFAULT_SONNET_MODEL", "ANTHROPIC_DEFAULT_HAIKU_MODEL"}
OPENROUTER_LINES = ("# OpenRouter — generate_svg (vector art) and edit_image (edits, retouching, composites).\n"
                    "# https://openrouter.ai/settings/keys — an account limited to some providers must allow the ones your\n"
                    "# models run on: recraft and sourceful for the defaults (https://openrouter.ai/settings/preferences).")
OPPER_LINE = "# Opper — generate_image: photographs and other raster images. https://platform.opper.ai"
# Exact lines of earlier stack.env.example versions → today's wording (None: dropped).
REWORD = {
    # the first versions, up to 26 Sep 2026 (opper-image)
    "# Opper gateway — image generation/editing (image-director). https://platform.opper.ai": OPPER_LINE,
    # 26 Sep 2026 (openrouter-image: Recraft SVG only)
    "# OpenRouter — the stack's only image model: Recraft V4.1 Pro Vector, SVG output only (designer,":
        OPENROUTER_LINES.split("\n")[0],
    "# image-director; about $0.30 an image from your OpenRouter credits). https://openrouter.ai/settings/keys":
        "\n".join(OPENROUTER_LINES.split("\n")[1:]),
    "# Where generated SVGs go when an agent names no folder (optional)":
        "# Where generated images go when an agent names no folder (optional; IMAGE_STUDIO_OUT_DIR wins when set)",
    # 27 Sep 2026 (image-studio with Lumenfall for SVG)
    "# Images (designer, image-director) come from image-studio, one tool per provider, each billed to its":
        "# Images (designer, image-director) come from image-studio: generate_svg and edit_image through",
    "# own account; a missing key disables only its tool.":
        "# OpenRouter, generate_image through Opper; a missing key disables only the tools that need it.",
    "# Opper — generate_image: GPT Image 2.5 Sunburst for photographs and other raster images (about": OPPER_LINE,
    "# $0.006-$0.21 an image, by quality). https://platform.opper.ai": None,
    "# OpenRouter — edit_image: Riverflow V2.5 Pro for edits, retouching and composites (from about $0.13).":
        OPENROUTER_LINES.split("\n")[0],
    "# https://openrouter.ai/settings/keys — an account limited to some providers must allow sourceful":
        OPENROUTER_LINES.split("\n")[1],
    "# (https://openrouter.ai/settings/preferences).": OPENROUTER_LINES.split("\n")[2],
}
text = open(target, encoding="utf-8", errors="surrogateescape").read()
before = text.split("\n")
lines = []
for line in before:
    key = line.rstrip()
    if key in REWORD:
        if REWORD[key] is not None:
            lines.extend(REWORD[key].split("\n"))
    else:
        lines.append(line)
reworded = lines != before
have = {m.group(1) for m in map(VAR.match, lines) if m}
out, names, live, models, comments = [], [], [], [], []
for line in open(example, encoding="utf-8").read().splitlines():
    m = VAR.match(line)
    if m:
        if m.group(1) not in have:
            if m.group(1) in LIVE | MODELS:
                out += comments + [line]
                (models if m.group(1) in MODELS else live).append(m.group(1))
            else:
                out += comments + [line if line.lstrip().startswith("#") else "#" + line.lstrip()]
                names.append(m.group(1))
        comments = []
    elif line.lstrip().startswith("#"):
        comments.append(line)
    else:
        comments = []
if out or reworded:
    new_text = "\n".join(lines)
    if out:
        new_text += ("" if new_text.endswith("\n") or not new_text else "\n") + (
            "\n# --- added by install.sh %s: new in stack.env.example (lines starting with # are off: "
            "uncomment to use) ---\n%s\n" % (time.strftime("%Y-%m-%d"), "\n".join(out)))
    fd = os.open(target + ".tmp", os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8", errors="surrogateescape") as f:
        f.write(new_text)
    os.replace(target + ".tmp", target)
    if live:
        print("  stack.env: appended the image models, set to the defaults: " + ", ".join(live))
    if models:
        print("  stack.env: appended the Claude model variables, set to the stack's IDs: " + ", ".join(models))
    if names:
        print("  stack.env: appended new variables (commented out): " + ", ".join(names))
    if reworded:
        print("  stack.env: brought the image lines of an earlier version up to date (the backup keeps the previous copy)")
PY

# Researcher's spider mcpServers block is only rewritten (to reuse an already-configured
# 'spider' server) when MCP registration is active and the user already has one.
SPIDER_REWRITE=0
if [ "$SKIP_MCP" = 0 ] && [ "$MCP_PLAN" = 0 ] && [ "$DRY_RUN" = 1 ]; then
  would "claude mcp get spider  (skipped in a dry run: the CLI may write ~/.claude.json; researcher's spider block stays as shipped)"
elif [ "$SKIP_MCP" = 0 ] && [ "$MCP_PLAN" = 0 ] && claude mcp get spider >/dev/null 2>&1 </dev/null; then SPIDER_REWRITE=1; fi

RENDERED_SETTINGS="$WORK/settings.rendered.json"

SPIDER_REWRITE="$SPIDER_REWRITE" RENDERED_SETTINGS="$RENDERED_SETTINGS" DEST="$S" \
REPORT="$REPORT" STACK_BACKUPS="$BACKUP_ROOT" STACK_CACHE="$STACK_CACHE" STACK_STATE="$STACK_STATE" STACK_COMMIT_FULL="$STACK_COMMIT_FULL" python3 - "$SRC" "$C" "$HERE" <<'PY'
import glob, hashlib, json, os, re, shutil, subprocess, sys

# C is where the files will live (every rendered path names it); DEST is the staged copy of C
# they are written to (install_state.py compares it with C afterwards and applies the difference).
SRC, C, REPO = sys.argv[1], sys.argv[2], sys.argv[3]
DEST = os.environ["DEST"]
report = {"removed": {}, "replaced": {}, "config_removed": [], "config_replaced": [], "notes": []}


def save_report():
    with open(os.environ["REPORT"], "w") as rf:
        json.dump(report, rf, indent=2, sort_keys=True)


import importlib.util  # noqa: E402
# by file path, never through sys.path (lib/ is agent-writable: nothing there may shadow a stdlib module)
_spec = importlib.util.spec_from_file_location("install_state", os.path.join(os.path.dirname(SRC), "lib", "install_state.py"))   # the snapshot
_ist = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_ist)
SCOPE_DIRS, in_scope, within = _ist.SCOPE_DIRS, _ist.in_scope, _ist.within   # the backups' scope rule

# a whole scope dir (bin/, mcp/, ...) is never removed by name; .stack-plugins.new is a leftover
WHOLE_DIRS = tuple(d for d in SCOPE_DIRS if d != ".stack-plugins.new")

DEST_REAL = os.path.realpath(DEST)


def drop(rel, why):
    """Remove DEST/rel (a file, link or directory) and say why in the listing. Only a SCOPE path
    whose parent resolves inside the staging dir: a name from the manifest can't reach elsewhere."""
    p = os.path.join(DEST, rel.rstrip("/"))
    if rel.rstrip("/") in WHOLE_DIRS or not in_scope(rel.rstrip("/")) or \
            not within(os.path.realpath(os.path.dirname(p)), DEST_REAL):
        sys.exit("install.sh: refusing to remove %r: not a path inside the config dir's stack part "
                 "— nothing in %s was changed" % (rel, C))
    if os.path.isdir(p) and not os.path.islink(p):
        shutil.rmtree(p)
        report["removed"][rel.rstrip("/") + "/"] = why
    elif os.path.lexists(p):
        os.unlink(p)
        report["removed"][rel] = why


# Leftovers of an interrupted install (temp files of earlier versions) go first, before anything
# here writes a temp file of the same name: always removed.
for _rel in (".stack-plugins.new", "settings.json.tmp", "stack.env.tmp", ".stack-manifest.json.tmp",
             "magg/config.json.tmp"):
    if os.path.lexists(os.path.join(DEST, _rel)):
        drop(_rel, "leftover of an interrupted install")
SPIDER_REWRITE = os.environ.get("SPIDER_REWRITE") == "1"
home = os.path.expanduser("~")


def which(b, fallback):
    return shutil.which(b) or fallback


def stable_which(b, fallback):
    """Like which(), but prefer a package-manager path that survives upgrades (Homebrew, the
    distro) over nvm's versioned ~/.nvm/versions/node/vX/bin, which `nvm uninstall` deletes."""
    found = shutil.which(b)
    if found and "/.nvm/versions/" not in found:
        return found
    for d in ("/opt/homebrew/bin", "/usr/local/bin", "/usr/bin"):
        cand = os.path.join(d, b)
        if os.path.isfile(cand) and os.access(cand, os.X_OK):
            return cand
    return found or fallback


SUBS = {
    "__CLAUDE_DIR__": C,
    "__HOME__": home,
    "__PYTHON3__": os.environ["STACK_PYTHON"],
    "__UV__": which("uv", home + "/.local/bin/uv"),
    "__UVX__": which("uvx", home + "/.local/bin/uvx"),
    "__NPX__": stable_which("npx", "npx"),
    "__NODE__": stable_which("node", "node"),
    "__MAGG__": which("magg", home + "/.local/bin/magg"),
    "__HUETENSION__": which("huetension", home + "/.local/bin/huetension"),
    "__STACK_REPO__": REPO,
    "__STACK_BACKUPS__": os.environ["STACK_BACKUPS"],
    "__STACK_CACHE__": os.environ["STACK_CACHE"],
    "__STACK_STATE__": os.environ["STACK_STATE"],
}


def render(text, json_escape=False):
    out = text
    for k, v in SUBS.items():
        rv = json.dumps(v)[1:-1] if json_escape else v
        out = out.replace(k, rv)
    return out


def sha256(path):
    if not os.path.isfile(path):
        return None
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_text(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


manifest_path = os.path.join(DEST, ".stack-manifest.json")
try:
    manifest = json.load(open(manifest_path))
except (OSError, ValueError):
    manifest = {}
# Every path the manifest names is checked before anything uses it (N-MANIFEST): a name with "..",
# an absolute path or anything outside the stack's part of the config dir stops the install.
if not isinstance(manifest, dict):
    manifest = {}
manifest.pop("offered", None)      # renders earlier installs left as <file>.new: no longer kept
_bad = []
for _key in ("files",):
    _val = manifest.get(_key)
    if _val is None:
        continue
    if not isinstance(_val, dict):
        _bad.append("%s (not an object)" % _key)
        continue
    # a file below a scope dir (agents/x.md, bin/doctor.sh) or a scope file: never a whole dir ("bin")
    _bad += ["%s: %r" % (_key, _rel) for _rel in _val
             if not in_scope(_rel) or _rel in SCOPE_DIRS or _rel.endswith("/")]
if _bad:
    sys.exit("install.sh: %s names paths outside the stack's part of the config dir (%s) — stopping; "
             "nothing in %s was changed. Remove those entries (or the file: the next run rebuilds it)."
             % (os.path.join(C, ".stack-manifest.json"), ", ".join(_bad[:5]), C))
files_entry = manifest.setdefault("files", {})
manifest["repo"] = REPO     # where the stack's source lives (claude-code-engineer, mcp-broker)
manifest["commit"] = os.environ.get("STACK_COMMIT_FULL") or "unknown"   # what this install ships


def save_manifest():
    with open(manifest_path + ".tmp", "w") as mf:
        json.dump(manifest, mf, indent=2, sort_keys=True)
    os.replace(manifest_path + ".tmp", manifest_path)


# --- magg catalog: add the servers the shipped catalog has and yours doesn't; an entry of a server
# the stack ships that differs from the stack's is replaced (an unedited earlier version is updated,
# keeping its state); a server an earlier stack version shipped and this one doesn't goes. Servers of
# your own (mcp-broker adds them) are never touched.
# Catalog servers are reset to disabled: mcp-broker enables one for a task and disables it after. ---
def fingerprint(entry):
    """Entry minus the state magg itself changes (enabled, kits)."""
    core = {k: v for k, v in entry.items() if k not in ("enabled", "kits")}
    return hashlib.sha256(json.dumps(core, sort_keys=True).encode()).hexdigest()[:16]


magg_dst = os.path.join(DEST, "magg", "config.json")
shipped_magg = json.loads(render(open(os.path.join(SRC, "magg", "config.json")).read(), json_escape=True))
prev_magg = manifest.get("magg_shipped") or {}
try:
    cur_magg = json.load(open(magg_dst))
    magg_ok = isinstance(cur_magg, dict)
except FileNotFoundError:
    cur_magg, magg_ok = {"servers": {}}, True
except ValueError as exc:
    print("  ! magg/config.json is not valid JSON (%s) — replaced by the stack's catalog" % exc)
    report["replaced"]["magg/config.json"] = "not valid JSON"
    cur_magg, magg_ok = {"servers": {}}, True
if magg_ok:
    servers = cur_magg.setdefault("servers", {})
    added, updated, disabled, replaced, gone = [], [], [], [], []
    for k, entry in shipped_magg.get("servers", {}).items():
        mine = servers.get(k)
        if mine is None:
            servers[k] = entry
            added.append(k)
            continue
        if not isinstance(mine, dict):
            continue
        if fingerprint(mine) == fingerprint(entry):
            pass
        elif k in prev_magg and fingerprint(mine) == prev_magg[k]:
            servers[k] = dict(entry, enabled=mine.get("enabled", True))
            updated.append(k)
        else:
            servers[k] = dict(entry)
            replaced.append(k)
            report["config_replaced"].append(["magg catalog: " + k, "differed from the stack's entry"])
        if servers[k].get("enabled", True):          # magg leaves "enabled" out when true
            servers[k]["enabled"] = False
            disabled.append(k)
    for k in sorted(set(prev_magg) - set(shipped_magg.get("servers", {}))):
        if k in servers:
            servers.pop(k)
            gone.append(k)
            report["config_removed"].append(["magg catalog: " + k, "no longer shipped by the stack"])
    if added or updated or disabled or replaced or gone or not os.path.exists(magg_dst):
        os.makedirs(os.path.dirname(magg_dst), exist_ok=True)
        with open(magg_dst + ".tmp", "w") as f:
            json.dump(cur_magg, f, indent=2)
            f.write("\n")
        os.replace(magg_dst + ".tmp", magg_dst)
    manifest["magg_shipped"] = {k: fingerprint(e) for k, e in shipped_magg.get("servers", {}).items()}
    parts = [("added " + ", ".join(added)) if added else "", ("updated " + ", ".join(updated)) if updated else "",
             ("disabled again " + ", ".join(disabled)) if disabled else "",
             ("replaced " + ", ".join(replaced)) if replaced else "", ("removed " + ", ".join(gone)) if gone else ""]
    print("  magg catalog: %s" % ("; ".join(x for x in parts if x) or "up to date"))

# --- agents/*.md + rules/claude-agent-stack.md: a file that differs from the render is replaced,
# whatever made it differ (the backup keeps it). ---
targets = [("agents/" + os.path.basename(p), p) for p in sorted(glob.glob(os.path.join(SRC, "agents", "*.md")))]
targets.append(("rules/claude-agent-stack.md", os.path.join(SRC, "rules", "claude-agent-stack.md")))
AE_BUILT = os.path.isfile(os.path.join(C, "mcp", "vendor", "after-effects-mcp", "build", "index.js"))

total_agents = sum(1 for rel, _ in targets if rel.startswith("agents/"))

# Adobe servers exist only on macOS: elsewhere they are left out of the renders, so designer and
# motion-designer don't start servers that can only fail (their prompts fall back to SVG/ffmpeg).
MACOS_ONLY_SERVERS = ("illustrator", "after-effects", "premiere", "mobilebuild")


def drop_servers(rendered, names):
    for n in names:
        rendered = re.sub(r"(?m)^  - %s:\n(?:      .*\n)+" % re.escape(n), "", rendered)
        rendered = re.sub(r",[ \t]*mcp__%s(?=[,\n])" % re.escape(n), "", rendered)
    return re.sub(r"(?m)^mcpServers:\n(?=[A-Za-z])", "", rendered)   # a block left empty


# Local MCP servers run outside the sandbox, with keys: they get their own uv and npm caches under
# __STACK_CACHE__ (sandbox denyWrite), which only these servers and the install's prefetch use (magg
# passes its environment on to the servers it runs). Sandboxed Bash gets ~/.cache/claude-sandbox from
# the guard's session-env SessionStart hook; no other cache is sandbox-writable.
MCP_CACHE_ENV = (("UV_CACHE_DIR", os.path.join(SUBS["__STACK_CACHE__"], "uv")),
                 ("npm_config_cache", os.path.join(SUBS["__STACK_CACHE__"], "npm")))


def mcp_cache_env(rendered):
    """Add MCP_CACHE_ENV to the env of every inline stdio server in the frontmatter."""
    if not rendered.startswith("---\n"):
        return rendered
    end = rendered.find("\n---", 4)
    if end < 0 or "\nmcpServers:\n" not in rendered[:end + 1]:
        return rendered
    lines = rendered[:end + 1].split("\n")
    out, i = [], 0
    while i < len(lines):
        line = lines[i]
        out.append(line)
        i += 1
        if not re.match(r"  - [A-Za-z0-9_-]+:\s*$", line):
            continue
        body = []
        while i < len(lines) and lines[i].startswith("      "):
            body.append(lines[i])
            i += 1
        if any(re.match(r"      command:", b) for b in body):
            have = {m.group(1) for m in (re.match(r"        ([A-Za-z_][A-Za-z0-9_]*):", b) for b in body) if m}
            add = ["        %s: %s" % (k, json.dumps(v)) for k, v in MCP_CACHE_ENV if k not in have]
            if add:
                at = next((k for k, b in enumerate(body) if re.match(r"      env:\s*$", b)), None)
                if at is None:
                    body += ["      env:"] + add
                else:
                    body[at + 1:at + 1] = add
        out.extend(body)
    return "\n".join(out) + rendered[end + 1:]


for rel, src_path in targets:
    text = open(src_path, encoding="utf-8").read()
    rendered = render(text)
    if sys.platform != "darwin" and rel.startswith("agents/"):
        rendered = drop_servers(rendered, MACOS_ONLY_SERVERS)
    elif rel == "agents/motion-designer.md" and not AE_BUILT:
        rendered = drop_servers(rendered, ("after-effects",))    # added once --with-adobe built it
    if rel == "agents/researcher.md" and SPIDER_REWRITE:
        rendered = re.sub(r"mcpServers:\n  - spider:\n(?:      .*\n)+", "mcpServers:\n  - spider\n", rendered)
    if rel.startswith("agents/"):
        rendered = mcp_cache_env(rendered)
    dest = os.path.join(DEST, rel)
    entry = files_entry.get(rel)
    if os.path.islink(dest) or os.path.isdir(dest):
        (shutil.rmtree if os.path.isdir(dest) and not os.path.islink(dest) else os.unlink)(dest)
        report["replaced"][rel] = "not a regular file"
    installed_hash = sha256(dest)
    rendered_hash = sha256_text(rendered)

    def write(dest=dest, rendered=rendered, rendered_hash=rendered_hash, rel=rel):
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        with open(dest, "w", encoding="utf-8") as f:
            f.write(rendered)
        files_entry[rel] = rendered_hash

    if installed_hash is None:
        write()
        action = "installed"
    elif installed_hash == rendered_hash:
        write()
        action = "unchanged"
    elif entry is not None and installed_hash == entry:
        write()
        action = "overwritten"
    else:
        report["replaced"][rel] = ("edited since the last install" if entry is not None
                                   else "a same-named file that isn't the stack's")
        write()
        action = "replaced"
    print("  %-34s %s" % (rel, action))

# What the stack doesn't ship, in agents/ and skills/: only files the stack installed and nobody
# changed since (the manifest's hash still matches) go; files of your own (untracked) and stack files
# you edited stay, named in the run's notes.
def stack_unedited(rel):
    p = os.path.join(DEST, rel)
    h = files_entry.get(rel)
    return h is not None and not os.path.islink(p) and sha256(p) == h


def entries_below(top):
    """Files and links below DEST/top (a link to a directory is one entry, never followed)."""
    out = []
    for root, dirs, files in os.walk(os.path.join(DEST, top)):
        out += [os.path.relpath(os.path.join(root, f), DEST) for f in files]
        out += [os.path.relpath(os.path.join(root, d), DEST) for d in dirs if os.path.islink(os.path.join(root, d))]
    return sorted(out)


def kept_why(rel):
    return "edited since the stack installed it" if rel in files_entry else "not installed by the stack: yours"


def drop_empty_dirs(top):
    """Remove the directories below DEST/top (top included) that the removals left empty."""
    t = os.path.join(DEST, top)
    if os.path.islink(t) or not os.path.isdir(t):
        return
    for root, dirs, files in os.walk(t, topdown=False):
        if not os.listdir(root):
            os.rmdir(root)


# Everything else in agents/: an agent the stack installed, no longer ships and nobody edited goes (the
# backup keeps it); agents of your own or of other tools, and stack agents you edited, stay (noted).
shipped = {rel for rel, _ in targets}
for rel in entries_below("agents"):
    if rel in shipped:
        continue
    if stack_unedited(rel):
        drop(rel, "no longer shipped by the stack")
    else:
        report["notes"].append("%s: kept (%s)" % (rel, kept_why(rel)))
for rel in [r for r in list(files_entry) if r.startswith("agents/") and r not in shipped]:
    files_entry.pop(rel, None)

# rules/: files of your own stay; rules the stack installed and no longer ships go
for fn in sorted(os.listdir(os.path.join(DEST, "rules"))):
    rel = "rules/" + fn
    if rel not in shipped and rel in files_entry:
        drop(rel, "no longer shipped by the stack")
        files_entry.pop(rel, None)

save_manifest()
print("  %d/%d agents installed" % (total_agents, total_agents))

# --- skills/: claude.ai's synced/ aside (never staged). Every shipped file matches its render (an
# edited one is replaced; the backup keeps it); of what the stack doesn't ship, only files it installed
# and nobody edited go (manifest hashes): skills and files of your own, and stack files you edited,
# stay (named in the notes). ---
def install_tracked(rel, dest, rendered):
    """Write the render; "replaced" when it replaced a file that differed, else None."""
    rendered_hash = sha256_text(rendered)
    if os.path.islink(dest) or os.path.isdir(dest):
        (shutil.rmtree if os.path.isdir(dest) and not os.path.islink(dest) else os.unlink)(dest)
    installed_hash = sha256(dest)
    entry = files_entry.get(rel)
    in_sync = installed_hash is None or installed_hash == rendered_hash or installed_hash == entry
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    with open(dest, "w", encoding="utf-8") as f:
        f.write(rendered)
    files_entry[rel] = rendered_hash
    if in_sync:
        return None
    report["replaced"][rel] = ("edited since the last install" if entry is not None
                               else "a same-named file that isn't the stack's")
    return "replaced"


# SRC is the private source snapshot: only the files HEAD tracks (what the review above showed), read
# once from the repo; an ignored or untracked file planted in a skill never reaches the config dir,
# and nothing swapped in the repo after the snapshot does either. Each must be a regular file inside
# dot-claude/skills.
SKILLS_SRC = os.path.realpath(os.path.join(SRC, "skills"))
listed = {}                                    # skill name -> [path relative to its dir]
for _rel in sorted(os.path.relpath(os.path.join(_r, _n), os.path.dirname(SRC))
                   for _r, _ds, _fs in os.walk(os.path.join(SRC, "skills")) for _n in _fs):
    _sp = os.path.join(os.path.dirname(SRC), _rel)
    _parts = os.path.relpath(_sp, os.path.join(SRC, "skills")).split(os.sep)
    if not os.path.lexists(_sp) or len(_parts) < 2:
        continue                               # deleted in the working tree; a file beside the skills
    if os.path.islink(_sp) or not os.path.isfile(_sp) or not within(os.path.realpath(_sp), SKILLS_SRC):
        sys.exit("install.sh: %s is not a regular file inside dot-claude/skills — nothing in %s was changed"
                 % (_rel, C))
    if _parts[-1].endswith((".pyc", ".new")) or _parts[-1] == ".DS_Store" or "__pycache__" in _parts:
        continue
    listed.setdefault(_parts[0], []).append(os.path.join(*_parts[1:]))
skill_names = sorted(listed)
skills_replaced = []
skill_files = set()
for name in skill_names:
    sdir = os.path.join(SRC, "skills", name)
    ddir = os.path.join(DEST, "skills", name)
    if os.path.islink(ddir) or os.path.isfile(ddir):
        os.unlink(ddir)
        report["replaced"]["skills/%s" % name] = "not a directory"
    for frel in listed[name]:
        sp = os.path.join(sdir, frel)
        op = os.path.join(ddir, frel)
        out_root = os.path.dirname(op)
        # never write through a link: a staged link or file where a directory goes is removed
        _d = ddir
        for _part in [""] + os.path.dirname(frel).split(os.sep):
            _d = os.path.join(_d, _part) if _part else _d
            if os.path.islink(_d) or os.path.isfile(_d):
                os.unlink(_d)
        os.makedirs(out_root, exist_ok=True)
        rel = os.path.relpath(op, DEST)
        skill_files.add(rel)
        try:
            text = open(sp, encoding="utf-8").read()
        except (UnicodeDecodeError, ValueError):
            if os.path.islink(op) or os.path.isdir(op):
                (shutil.rmtree if os.path.isdir(op) and not os.path.islink(op) else os.unlink)(op)
            shutil.copy2(sp, op)
            files_entry[rel] = sha256(op)       # tracked like a render: a later prune may drop it unedited
            continue
        state = install_tracked(rel, op, render(text))
        if state == "replaced":
            skills_replaced.append(rel)
# what the stack doesn't ship: whole skills, and files inside shipped skills. The prune removes only
# files the stack installed and nobody changed since (the manifest's hash still matches): a skill or
# file of your own (untracked) and a stack file you edited stay, named in the run's notes.
skills_root = os.path.join(DEST, "skills")
for name in sorted(os.listdir(skills_root)):
    rel_dir = "skills/%s" % name
    p_dir = os.path.join(skills_root, name)
    is_dir = os.path.isdir(p_dir) and not os.path.islink(p_dir)
    if name not in skill_names:
        rels = entries_below(rel_dir) if is_dir else [rel_dir]
        ours = [r for r in rels if stack_unedited(r)]
        why = "no longer shipped by the stack"
        if ours and len(ours) == len(rels):
            drop(rel_dir + "/" * is_dir, why)                  # all the stack's, unedited: the whole skill
        elif not any(r in files_entry for r in rels):
            report["notes"].append("%s: kept (not installed by the stack: yours or another tool's)"
                                   % (rel_dir + "/" * is_dir))
        else:
            for rel in rels:
                if rel in ours:
                    drop(rel, why)
                else:
                    report["notes"].append("%s: kept (%s)" % (rel, kept_why(rel)))
            drop_empty_dirs(rel_dir)
        continue
    for rel in entries_below(rel_dir) if is_dir else []:
        if rel in skill_files:
            continue
        if stack_unedited(rel):
            drop(rel, "no longer part of the stack's %s skill" % name)
        else:
            report["notes"].append("%s: kept (%s)" % (rel, kept_why(rel)))
    if is_dir:                                  # directories the removals left empty (not the skill's own)
        for sub in sorted(os.listdir(p_dir)):
            drop_empty_dirs(os.path.join(rel_dir, sub))
for rel in [r for r in list(files_entry) if r.startswith("skills/")]:
    if rel not in skill_files:
        files_entry.pop(rel, None)
print("  skills rendered (%d): %s" % (len(skill_names), ", ".join(skill_names)))
for rel in skills_replaced:
    print("  %-34s replaced (it differed from the stack's; the backup keeps it)" % rel)

# --- scripts the stack copies into hooks/, bin/ and mcp/ (step 6 put them in DEST): tracked in the
# manifest, so a later version that stops shipping one removes it. Files of your own there stay. ---
STACK_SCRIPTS = ["hooks/agent_guard.py", "hooks/stack_hook.py", "bin/stack-hook", "hooks/agent_effort.json", "hooks/web_caps.py", "hooks/read_gate.py", "hooks/stack_report.py", "hooks/stack_io.py", "hooks/stack_usage.py", "hooks/stack_sched.py",
                 "hooks/stack_sched_refresh.py", "hooks/sched_model.json", "hooks/derive_sched_model.py",
                 "hooks/stack_limits.py", "hooks/stack_limits_seed.json", "hooks/stack_fanout.py", "hooks/stack_fanout_wire.py",
                 "hooks/derive_thresholds.py", "bin/statusline.py", "bin/doctor.sh", "bin/with-stack-env",
                 "bin/mcp-headers", "bin/magg-private", "bin/claude-ultracode", "bin/stack_sdk.py", "bin/stack-budget",
                 "bin/stack-tree",
                 "bin/stack-who",
                 "mcp/image_studio_mcp.py",
                 "mcp/libdocs_mcp.py", "mcp/neural_memory_mcp.py"]
_missing = [rel for rel in STACK_SCRIPTS if not os.path.isfile(os.path.join(DEST, rel))]
if _missing:
    sys.exit("install.sh: the staged copy lacks the stack's scripts (%s) — stopping; nothing in %s "
             "was changed" % (", ".join(_missing), C))
for rel in STACK_SCRIPTS:
    files_entry[rel] = sha256(os.path.join(DEST, rel))
stale_scripts = {r: "no longer shipped by the stack" for r in files_entry
                 if r.split("/")[0] in ("hooks", "bin", "mcp") and r not in STACK_SCRIPTS}
for rel, why in sorted(stale_scripts.items()):
    _p = os.path.join(DEST, rel)
    if not os.path.lexists(_p) or (os.path.isdir(_p) and not os.path.islink(_p)):
        files_entry.pop(rel, None)          # a script is a file: a directory there is yours
        continue
    drop(rel, why)
    files_entry.pop(rel, None)
save_manifest()
save_report()

# --- settings.json: JSON-escaped render, written to a temp file for the merge step ---
settings_text = open(os.path.join(SRC, "settings.json")).read()
open(os.environ["RENDERED_SETTINGS"], "w").write(render(settings_text, json_escape=True))

print("  " + ", ".join("%s=%s" % (k.strip("_").lower(), v) for k, v in SUBS.items()))
PY

# ==== stack-python (S2): link and smoke test, before settings.json ================================
say "Hook interpreter: $STACK_PYTHON, smoke-tested before settings.json changes"
# The hook commands step 7 writes run /bin/sh bin/stack-hook, and its PreToolUse entries FAIL CLOSED
# when no Python >= 3.13 starts: the link must exist and work first. The smoke test runs the staged
# launcher, stub and guard on it as a session will (PreToolUse events on stdin, the config dir's
# stack-python, a scratch state dir, STACK_POLICY on): a Read through `--fail-closed agent_guard
# budget` must be allowed (exit 0, no deny), and `git push` through `--fail-closed agent_guard
# no-push` denied (the guard really decides). A failure stops the run here with the previous link
# back: the installed hook commands, and everything else in $C, stay as they were.
smoke_event(){  # smoke_event TOOL INPUT-JSON
  printf '{"hook_event_name":"PreToolUse","session_id":"install-smoke","tool_name":"%s","tool_input":%s,"tool_use_id":"tu-install-smoke","cwd":"%s","permission_mode":"default"}' \
    "$1" "$2" "$WORK/smoke/proj"
}
smoke_run(){  # smoke_run INTERPRETER-OVERRIDE|"" ARGS...: the staged launcher, as a hook runs it
  local py="$1"; shift
  ( cd "$WORK/smoke/proj" && if [ -n "$py" ]; then export STACK_PYTHON="$py"; else unset STACK_PYTHON; fi \
    && unset PYTHONPATH PYTHONHOME PYTHONPYCACHEPREFIX STACK_POLICY \
    && CLAUDE_CONFIG_DIR="$C" XDG_STATE_HOME="$WORK/smoke/state" STACK_USAGE_COLLECT=0 \
       /bin/sh "$S/bin/stack-hook" --fail-closed agent_guard "$@" 2>>"$WORK/smoke/err" )
}
stack_python_smoke(){  # stack_python_smoke [interpreter override]: 0 when both probes pass
  local py="${1:-}" out rc
  rm -rf "$WORK/smoke"; mkdir -p "$WORK/smoke/proj" "$WORK/smoke/state"; : >"$WORK/smoke/err"
  rc=0; out="$(smoke_event Read "{\"file_path\":\"$WORK/smoke/proj/a.py\"}" | smoke_run "$py" budget)" || rc=$?
  if [ "$rc" != 0 ] || printf '%s' "$out" | grep -qE '"permissionDecision": *"(deny|ask)"'; then
    SMOKE_WHY="a Read was not allowed (exit $rc): $(printf '%s %s' "$out" "$(cat "$WORK/smoke/err")" | tr '\n' ' ' | cut -c1-400)"
    return 1
  fi
  rc=0; out="$(smoke_event Bash '{"command":"git push origin main"}' | smoke_run "$py" no-push)" || rc=$?
  if [ "$rc" != 0 ] || ! printf '%s' "$out" | grep -qE '"permissionDecision": *"deny"' \
      || printf '%s' "$out" | grep -q 'stack guard error'; then
    SMOKE_WHY="git push was not denied by the guard (exit $rc): $(printf '%s %s' "$out" "$(cat "$WORK/smoke/err")" | tr '\n' ' ' | cut -c1-400)"
    return 1
  fi
  return 0
}
# link_stack_python TARGET: $STACK_PYTHON -> TARGET atomically (a session running hooks meanwhile
# sees the old link or the new one, never none)
link_stack_python(){ python3 -c 'import os, sys
tmp = sys.argv[2] + ".tmp-%d" % os.getpid()
os.symlink(sys.argv[1], tmp)
os.replace(tmp, sys.argv[2])' "$1" "$STACK_PYTHON"; }
SMOKE_WHY=""
SMOKE_FIX="fix: uv python install 3.13 (or STACK_PYTHON=/path/to/python3.13+), then rerun ./install.sh; until then the previously installed hooks stay"
RUN_PY="$STACK_PYTHON"     # what this run executes the staged and installed scripts with
if [ -z "$STACK_PYTHON_TARGET" ]; then
  if [ "$DRY_RUN" = 0 ]; then
    echo "install.sh: no Python 3.13 for the hooks (uv python find 3.13 found none; step 2 above says why). Nothing in $C was changed. $SMOKE_FIX" >&2
    exit 1
  fi
  would "ln -s <uv's Python 3.13, installed above> $STACK_PYTHON"
  would "smoke-test the staged hooks on it: PreToolUse Read via stack-hook --fail-closed agent_guard budget (allow), git push via no-push (deny)"
  RUN_PY="python3"; note "--dry-run: validation below runs the guard's self-test on python3 (no 3.13 yet)"
elif [ "$DRY_RUN" = 1 ]; then
  [ "$(readlink "$STACK_PYTHON" 2>/dev/null || true)" = "$STACK_PYTHON_TARGET" ] \
    && note "$STACK_PYTHON -> $STACK_PYTHON_TARGET (in place)" || would "ln -sfn $STACK_PYTHON_TARGET $STACK_PYTHON"
  if stack_python_smoke "$STACK_PYTHON_TARGET"; then note "smoke test passed on $STACK_PYTHON_TARGET (Read allowed, git push denied)"
  else note "! smoke test failed: $SMOKE_WHY — the real run stops here. $SMOKE_FIX"; fi
  RUN_PY="$STACK_PYTHON_TARGET"
else
  prev_link=""; [ -L "$STACK_PYTHON" ] && prev_link="$(readlink "$STACK_PYTHON")"
  mkdir -p "$C/bin"
  link_stack_python "$STACK_PYTHON_TARGET"
  if stack_python_smoke; then
    note "$STACK_PYTHON -> $STACK_PYTHON_TARGET; smoke test passed (Read allowed, git push denied)"
  else
    if [ -n "$prev_link" ]; then
      link_stack_python "$prev_link"
    else
      rm -f "$STACK_PYTHON"
    fi
    echo "install.sh: the hook smoke test failed on $STACK_PYTHON_TARGET: $SMOKE_WHY" >&2
    echo "install.sh: nothing else in $C was changed (stack-python restored${prev_link:+ to $prev_link}). $SMOKE_FIX" >&2
    exit 1
  fi
fi
# ==== stack-python: END ===========================================================================

say "7/11 Merge settings.json, validate, apply"
[ -f "$S/settings.json" ] || echo '{}' > "$S/settings.json"
# PREV_COMMIT (the commit the last install shipped, read from $C's manifest above) and the repo let
# the merge tell a permission setting the stack shipped from one you chose (settings_permission_scalars)
PREV_COMMIT="$prev_commit" STACK_REPO="$HERE" python3 - "$RENDERED_SETTINGS" "$S/settings.json" \
  "$S/.stack-manifest.json" "$REPORT" "$C/settings.json" "$S/stack.env" "$SRC/bin/mcp-headers" <<'PY'
import json, os, re, runpy, subprocess, sys
from pathlib import Path
src, manifest_path, report_path, shown = sys.argv[1], sys.argv[3], sys.argv[4], sys.argv[5]
dst = sys.argv[2]            # the staged copy (install_state.py writes through a symlinked original)


# A JSON string value under a key that looks like it holds a secret (key/token/secret/password/
# auth*, case-insensitive) — masked before any excerpt of the user's settings.json is printed.
SECRET_VALUE_RE = re.compile(
    r'("(?:[^"\\]|\\.)*(?:key|token|secret|password|auth\w*)"\s*:\s*")((?:[^"\\]|\\.)+)(")', re.I)


def mask_secrets(line):
    return SECRET_VALUE_RE.sub(lambda m: m.group(1) + "<redacted>" + m.group(3), line)


def load_lenient(p):
    """Strict JSON first; then repair // comments, trailing commas and missing end-of-line commas."""
    raw = open(p, encoding="utf-8").read()
    try:
        return json.loads(raw), []
    except json.JSONDecodeError as first:
        err = first
    fixes, text = [], re.sub(r'(?m)^\s*//.*$', '', raw)
    if text != raw:
        fixes.append("removed // comment lines")
    t2 = re.sub(r',(\s*[}\]])', r'\1', text)
    if t2 != text:
        fixes.append("removed trailing commas")
    text = t2
    for _ in range(20):
        try:
            return json.loads(text), fixes
        except json.JSONDecodeError as e:
            err = e
            if e.msg != "Expecting ',' delimiter":
                break
            j = e.pos - 1
            while j >= 0 and text[j] in " \t\r\n":
                j -= 1
            # repair a comma missing after a complete value, before the next "key" (same or next line)
            if j < 0 or text[j] not in '"}]0123456789el' or text[e.pos:e.pos + 1] not in ('"', '{', '['):
                break
            text = text[:j + 1] + "," + text[j + 1:]
            fixes.append("added missing comma on line %d" % (text.count("\n", 0, j) + 1))
    lines = raw.splitlines()
    print("\n  ERROR: %s is not valid JSON — line %d, column %d: %s" % (shown, err.lineno, err.colno, err.msg))
    for i in range(max(1, err.lineno - 2), min(len(lines), err.lineno + 1) + 1):
        print("  %5d | %s" % (i, mask_secrets(lines[i - 1])))
        if i == err.lineno:
            print("        | " + " " * (err.colno - 1) + "^")
    print("  Fix that spot (often a missing comma or an unescaped \" inside a string), then rerun ./install.sh")
    sys.exit(3)


new = json.load(open(src))
# The Claude model IDs come from stack.env, their single source (stack.env.example ships the stack's):
# each non-empty ANTHROPIC_DEFAULT_<FAMILY>_MODEL joins the shipped env block, so the aliases the
# agents name (model: opus / sonnet) resolve to it wherever settings.json applies. They merge like any
# other shipped default: a value you set in settings.json yourself is kept (and reported).
MODEL_ENV = ("ANTHROPIC_DEFAULT_OPUS_MODEL", "ANTHROPIC_DEFAULT_SONNET_MODEL", "ANTHROPIC_DEFAULT_HAIKU_MODEL")
stack_env = runpy.run_path(sys.argv[7], run_name="mcp_headers")["read_env_file"](Path(sys.argv[6]))
for k in MODEL_ENV:
    if stack_env.get(k):
        new.setdefault("env", {})[k] = stack_env[k]
cur, fixes = load_lenient(dst)
for f in fixes:
    print("  repaired your settings.json:", f, "(original kept in the backup folder)")


def uniq(xs):
    out = []
    for x in xs:
        if x not in out:
            out.append(x)
    return out


try:
    manifest = json.load(open(manifest_path))
except (OSError, ValueError):
    manifest = {}
prev_env = manifest.get("settings_env") or {}
prev_perm = manifest.get("settings_permissions") or {}
prev_owned = manifest.get("settings_set_if_absent") or {}


def shipped_permission_scalars(commit):
    """The scalar permissions keys (defaultMode) the stack's settings.json held at `commit`, read
    from this repo; None when that can't be told (no commit, or one this repo doesn't have)."""
    if not re.fullmatch(r"[0-9a-f]{7,64}", commit or ""):
        return None
    try:
        out = subprocess.run(["git", "--no-replace-objects", "-c", "core.hooksPath=/dev/null", "-C", os.environ.get("STACK_REPO") or ".", "show",
                              commit + ":dot-claude/settings.json"],
                             stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=20)
        doc = json.loads(out.stdout) if out.returncode == 0 else None
    except (OSError, ValueError, subprocess.SubprocessError):
        return None
    if not isinstance(doc, dict):
        return None
    perm = doc.get("permissions")
    return {k: v for k, v in perm.items() if not isinstance(v, list)} if isinstance(perm, dict) else {}


# Scalar permissions keys (defaultMode) follow the unowned env keys' rule: the stack's value is set
# while you have none or still hold the value the stack shipped last time; a value you chose is
# kept ("kept your permissions..."). The last install's shipped values come from the manifest; a
# manifest older than "settings_permission_scalars" (installers up to 2026-10-03 overwrote the
# scalar on every run, so the value then in place was the one that commit shipped) from the
# settings.json of the commit it records. Neither: nothing of yours is changed.
# An installer older than that key keeps it but rewrites "commit" (a rollback): the record counts only
# for the commit it was written with.
prev_perm_scalars = manifest.get("settings_permission_scalars")
if not isinstance(prev_perm_scalars, dict) or (
        os.environ.get("PREV_COMMIT")
        and manifest.get("settings_permission_scalars_commit") != os.environ["PREV_COMMIT"]):
    prev_perm_scalars = shipped_permission_scalars(os.environ.get("PREV_COMMIT"))
MODE_NOTICE = ("default permission mode is now plan; you were on %s by default; Shift+Tab or "
               "ExitPlanMode to change it. To start every session in %s again, set "
               "\"permissions\": {\"defaultMode\": \"%s\"} in %s (later runs keep it), or start one "
               "session with claude --permission-mode %s")
# sandbox list entries the last install shipped and this one doesn't go through "settings_sandbox"
# (a first install, with no manifest, retracts nothing of yours).
prev_sandbox = manifest.get("settings_sandbox")
if not isinstance(prev_sandbox, dict):
    prev_sandbox = {}
# top-level keys the stack sets only when you have none (or still have the stack's own value).
# "agent": set "agent": "claude" to keep the plain main thread (then: claude --agent blackcat).
# "skillListingBudgetFraction" (Claude Code's default 0.01: about 30K characters on a 1M-context
# model; over it, the least-used skills are listed by name only), "skillListingMaxDescChars" (per-skill
# cut) and "skillOverrides" (per skill: a stack entry is set while you have none for that skill, or
# still the stack's own) keep every description inside it. tests/lint_agents.py checks the size.
SET_IF_ABSENT = {"statusLine", "agent", "skillListingBudgetFraction", "skillListingMaxDescChars",
                 "skillOverrides"}
# env keys the stack re-asserts on every run; every other shipped env key is a default the user
# may tune (README "knobs"): it follows stack upgrades only while the user has not changed it.
# The spawn knobs are owned too: they are the stack's guarantees (BlackCat's step cap, fan-out
# caps, the per-agent MCP call cap), not preferences. The token budgets are learned limits
# (stack_limits.py), fixed per session by its snapshot, not env knobs the stack ships.
OWNED_ENV = {"STACK_ENV_FILE", "CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH",
             "MCP_DISCOVERY_CACHE", "CLAUDE_CODE_MAX_CONCURRENT_SUBAGENTS",
             "BLACKCAT_MAX_STEPS", "BLACKCAT_MAX_DISPATCH", "STACK_MAX_FANOUT",
             "STACK_MAX_FANOUT_BY_TYPE", "STACK_MAX_MCP_CALLS"}
try:
    report = json.load(open(report_path))
except (OSError, ValueError):
    report = {}
for key in ("removed", "replaced"):
    report.setdefault(key, {})
for key in ("config_removed", "config_replaced", "notes"):
    report.setdefault(key, [])
# hook commands of the stack, any version: its launcher bin/stack-hook (any module), its guard run
# directly (`<python> .../hooks/agent_guard.py ...`, whatever config dir or interpreter an earlier
# install rendered), the usage collector, the web caps, the read gate, /stack-doctor's bin/doctor.sh --hook,
# /stack-tree's bin/stack-tree --hook. Every hook script settings.json ships must match, or each re-run keeps
# the installed copy as yours and appends the shipped one again (tests/test_install_state.py checks this)
STACK_HOOK_RE = re.compile(r"/bin/stack-hook\b|agent_guard\.py|stack_usage\.py|web_caps\.py|read_gate\.py|/bin/doctor\.sh[^ ]{0,2} --hook|/bin/stack-tree[^ ]{0,2} --hook")


def canon(x):
    return json.dumps(x, sort_keys=True)


def merge_list(mine, shipped, retired=()):
    """Your list plus the stack's, each item once, in order; items the stack stopped shipping go.
    Lists of objects with a "name" (sandbox.credentials.envVars) merge by name: the stack's wins."""
    if all(isinstance(x, dict) and "name" in x for x in list(mine) + list(shipped)):
        names = {x["name"] for x in shipped}
        gone = {canon(x) for x in retired}
        out = [x for x in mine if x["name"] not in names and canon(x) not in gone] + list(shipped)
    else:
        out = [x for x in mine if x not in retired] + list(shipped)
    seen, res = set(), []
    for x in out:
        if canon(x) not in seen:
            seen.add(canon(x))
            res.append(x)
    return res


def merge_tree(mine, shipped, prev, path):
    """sandbox: the stack's scalars win (its security baseline: set in ~/.claude/settings.json they
    also apply in bypassPermissions mode); lists keep your own entries; a value you set differently
    is reported."""
    out = dict(mine) if isinstance(mine, dict) else {}
    for k, v in shipped.items():
        p = prev.get(k) if isinstance(prev, dict) else None
        if isinstance(v, dict):
            out[k] = merge_tree(out.get(k), v, p or {}, path + [k])
        elif isinstance(v, list):
            retired = [x for x in (p or []) if x not in v] if isinstance(p, list) else []
            have = out.get(k) if isinstance(out.get(k), list) else []
            gone = [x for x in have if x in retired and not isinstance(x, dict)]
            if gone:
                print("  retracted %s entries the stack no longer ships: %s"
                      % (".".join(path + [k]), ", ".join(map(str, gone))))
            out[k] = merge_list(have, v, retired)
        else:
            if k in out and out[k] != v and out[k] != p:
                print("  set %s=%s (was %s): the stack's sandbox baseline" % (".".join(path + [k]), json.dumps(v), json.dumps(out[k])))
            out[k] = v
    return out


def hook_label(x):
    cmd = x.get("command") if isinstance(x, dict) else None
    cmd = cmd if isinstance(cmd, str) else json.dumps(x, sort_keys=True)
    return cmd if len(cmd) <= 110 else cmd[:107] + "..."


merged = dict(cur)
for k, v in new.items():
    if k == "hooks":
        h = dict(cur.get("hooks") or {})
        dropped_dups = 0
        for ev, groups in v.items():
            kept, seen = [], set()
            # the stack's hook entries of this event as the stack ships them now: a copy found in
            # your settings is replaced by the same entry (not listed); any other copy of the stack's
            # guard (an earlier path or interpreter, a duplicate) goes and is listed one by one
            current = {}
            for sg in groups:
                for sx in (sg.get("hooks") or []) if isinstance(sg, dict) else []:
                    key = (sg.get("matcher"), canon(sx))
                    current[key] = current.get(key, 0) + 1

            def stack_entry_gone(g, x, ev=ev, current=current):
                key = (g.get("matcher") if isinstance(g, dict) else None, canon(x))
                if current.get(key, 0) > 0:
                    current[key] -= 1
                    return
                where = "settings.json hooks.%s%s" % (
                    ev, "[%s]" % g.get("matcher") if isinstance(g, dict) and g.get("matcher") else "")
                why = ("a second copy of the stack's hook" if any(c == canon(x) for _, c in current)
                       else "an earlier copy of the stack's guard hook; the current one replaces it")
                report["config_removed"].append(["%s: %s" % (where, hook_label(x)), why])

            for g in h.get(ev) or []:
                if isinstance(g, dict) and isinstance(g.get("hooks"), list):
                    mine, own_seen, had_stack = [], set(), False
                    for x in g["hooks"]:
                        if STACK_HOOK_RE.search(json.dumps(x)):
                            had_stack = True
                            stack_entry_gone(g, x)
                            continue
                        if canon(x) in own_seen:
                            dropped_dups += 1
                            continue
                        own_seen.add(canon(x))
                        mine.append(x)
                    if len(mine) < len(g["hooks"]):   # the stack's guard shared this group, or duplicates
                        if not mine:
                            continue
                        g = dict(g, hooks=mine)       # keep the user's own hooks of that group
                        if had_stack:
                            print("  kept %d hook(s) of yours from a %s group shared with the stack's guard" % (len(mine), ev))
                elif STACK_HOOK_RE.search(json.dumps(g)):
                    stack_entry_gone(g, g)
                    continue
                if canon(g) in seen:                  # the same group twice: once is enough
                    dropped_dups += 1
                    continue
                seen.add(canon(g))
                kept.append(g)
            h[ev] = kept + groups
        # events the stack no longer wires: its old hooks there go, yours stay
        for ev in [e for e in h if e not in v]:
            groups = h[ev] if isinstance(h[ev], list) else []
            keep = []
            for g in groups:
                if not STACK_HOOK_RE.search(json.dumps(g)):
                    keep.append(g)
                    continue
                entries = g.get("hooks") if isinstance(g, dict) and isinstance(g.get("hooks"), list) else [g]
                for x in entries:
                    if STACK_HOOK_RE.search(json.dumps(x)):
                        report["config_removed"].append(["settings.json hooks.%s: %s" % (ev, hook_label(x)),
                                                         "the stack's guard no longer runs on it"])
                mine = [x for x in entries if not STACK_HOOK_RE.search(json.dumps(x))]
                if mine:
                    keep.append(dict(g, hooks=mine))    # your own hooks of that group stay
            if keep:
                h[ev] = keep
            else:
                h.pop(ev)
        if dropped_dups:
            report["config_removed"].append(["settings.json hooks", "%d duplicate hook entr%s" % (
                dropped_dups, "y" if dropped_dups == 1 else "ies")])
        merged["hooks"] = h
    elif k == "sandbox":
        merged[k] = merge_tree(cur.get(k), v, prev_sandbox, [k])
    elif k == "permissions":
        p = dict(cur.get("permissions") or {})
        for pk, pv in v.items():
            if not isinstance(pv, list):
                mine = p.get(pk)
                was = (prev_perm_scalars or {}).get(pk)
                if mine is None or mine == pv or (was is not None and mine == was):
                    if mine is not None and mine != pv:
                        print("  set permissions.%s=%s (was %s, the stack's earlier default)"
                              % (pk, json.dumps(pv), json.dumps(mine)))
                        if pk == "defaultMode":
                            report["notes"].append(MODE_NOTICE % (mine, mine, mine, shown, mine))
                    p[pk] = pv
                else:
                    print("  kept your permissions.%s=%s (the stack's: %s)" % (pk, json.dumps(mine), json.dumps(pv)))
                    if prev_perm_scalars is None and os.environ.get("PREV_COMMIT"):
                        print("    (the last install's commit %s is not in this repository, so the installer can't "
                              "tell the stack's earlier default from your choice; set it to %s yourself if you "
                              "want the stack's)" % (os.environ["PREV_COMMIT"][:12], json.dumps(pv)))
                continue
            retired = set(prev_perm.get(pk) or []) - set(pv)
            have = list(p.get(pk) or [])
            dropped = [x for x in have if x in retired]
            if dropped:
                print("  retracted stack permission rule(s) from %s: %s" % (pk, ", ".join(dropped)))
            dups = len(have) - len(uniq(have))
            if dups:
                report["config_removed"].append(["settings.json permissions.%s" % pk, "%d duplicate rule%s" % (
                    dups, "" if dups == 1 else "s")])
            p[pk] = uniq([x for x in have if x not in retired] + pv)
        for pk in sorted(set(prev_perm_scalars or {}) - set(v)):      # a scalar no longer shipped
            if pk in p and p[pk] == prev_perm_scalars[pk]:
                print("  retracted stack setting permissions.%s=%s (no longer shipped)" % (pk, json.dumps(p.pop(pk))))
        merged["permissions"] = p
    elif k == "worktree":
        # the stack owns worktree.baseRef ("head": agents never push, so origin/main goes stale and
        # a worktree must start from local work to merge back); other worktree keys stay yours
        w = dict(cur.get(k) or {}) if isinstance(cur.get(k), dict) else {}
        for wk, wv in v.items():
            if wk in w and w[wk] != wv:
                print("  set worktree.%s=%s (was %s): the stack's git rule needs it" % (wk, json.dumps(wv), json.dumps(w[wk])))
            w[wk] = wv
        merged[k] = w
    elif k == "skillOverrides":
        so = dict(cur.get(k)) if isinstance(cur.get(k), dict) else {}
        prev_so = prev_owned.get(k) if isinstance(prev_owned.get(k), dict) else {}
        for sk, sv in v.items():
            if sk not in so or so[sk] == prev_so.get(sk):
                so[sk] = sv
        # an entry an earlier version shipped and this one doesn't goes while it still holds the
        # stack's value (the skill is listed again, or gone); one you changed stays
        gone = sorted(sk for sk, sv in prev_so.items() if sk not in v and so.get(sk) == sv)
        for sk in gone:
            so.pop(sk)
        if gone:
            print("  retracted stack skillOverrides for %s (no longer shipped)" % ", ".join(gone))
        merged[k] = so
    elif k in SET_IF_ABSENT:
        if k not in cur or cur.get(k) == prev_owned.get(k) or cur.get(k) == v:
            merged[k] = v
        else:
            print("  kept your %s (the stack's: %s)" % (k, json.dumps(v)))
    elif k == "env":
        e = dict(cur.get("env") or {})
        for ek, sv in v.items():
            mine = e.get(ek)
            if mine is None or ek in OWNED_ENV or str(mine) == str(sv) or str(mine) == str(prev_env.get(ek)):
                if (mine is not None and ek in OWNED_ENV and str(mine) != str(sv)
                        and str(mine) != str(prev_env.get(ek))):
                    print("  set env %s=%s (was %s): the stack owns this knob" % (ek, sv, mine))
                e[ek] = sv
            elif ek == "ANTHROPIC_DEFAULT_HAIKU_MODEL" and "haiku" in str(mine).lower():
                # the stack runs no Haiku: the haiku alias and background tasks use stack.env's haiku slot
                print("  replaced env %s=%s with %s (the stack runs no Haiku)" % (ek, mine, sv))
                e[ek] = sv
            elif ek in MODEL_ENV and str(mine).endswith("[1m]"):
                pass                # the stale-pin loop below replaces it and says so
            elif ek in MODEL_ENV:
                print("  kept your env %s=%s in settings.json (stack.env: %s; delete the settings.json entry "
                      "to use stack.env's)" % (ek, mine, sv))
            else:
                print("  kept your env %s=%s (stack default: %s)" % (ek, mine, sv))
        # keys an earlier stack version shipped and this one doesn't: removed while unchanged
        for ek in sorted(set(prev_env) - set(v)):
            if ek in e and str(e[ek]) == str(prev_env[ek]):
                print("  retracted stack env %s=%s (no longer shipped)" % (ek, e.pop(ek)))
        merged["env"] = e
    else:
        merged[k] = v
# Set-if-absent keys an earlier stack version shipped and this one doesn't (a rollback, or a key the
# stack stopped setting): removed while they still hold the stack's value; a value of yours stays.
# skillOverrides is retracted per skill.
for k in sorted(set(prev_owned) - set(new)):
    pv = prev_owned[k]
    if k == "skillOverrides" and isinstance(pv, dict) and isinstance(merged.get(k), dict):
        so = dict(merged[k])
        gone = sorted(sk for sk, sv in pv.items() if sk in so and so[sk] == sv)
        for sk in gone:
            so.pop(sk)
        if gone:
            print("  retracted stack skillOverrides for %s (no longer shipped)" % ", ".join(gone))
        if so:
            merged[k] = so
        else:
            merged.pop(k, None)
    elif k in merged and merged[k] == pv:
        print("  retracted stack setting %s=%s (no longer shipped)" % (k, json.dumps(merged.pop(k))))
env = merged.get("env", {})
for k in ("ANTHROPIC_DEFAULT_OPUS_MODEL", "ANTHROPIC_DEFAULT_SONNET_MODEL",
          "ANTHROPIC_DEFAULT_FABLE_MODEL", "ANTHROPIC_DEFAULT_HAIKU_MODEL"):
    if str(env.get(k, "")).endswith("[1m]"):
        stale, sv = env.pop(k), str((new.get("env") or {}).get(k, ""))
        if sv and not sv.endswith("[1m]"):
            env[k] = sv
        print("  %s stale %s=%s%s (current models have 1M natively; the pin broke subagent models in Claude Desktop)"
              % ("replaced" if k in env else "removed", k, stale, " with %s from stack.env" % sv if k in env else ""))
if "CLAUDE_CODE_MAX_SUBAGENTS_PER_SESSION" in env:
    print("  removed no-op env CLAUDE_CODE_MAX_SUBAGENTS_PER_SESSION=%s (removed from Claude Code in v2.1.224; use CLAUDE_CODE_MAX_CONCURRENT_SUBAGENTS)" % env.pop("CLAUDE_CODE_MAX_SUBAGENTS_PER_SESSION"))
for bad in ("CLAUDE_CODE_SUBAGENT_MODEL", "CLAUDE_CODE_SUBAGENT_MODEL_FORCE", "CLAUDE_CODE_EFFORT_LEVEL"):
    if bad in env:
        print("  WARNING: env %s overrides per-agent model/effort — removed" % bad)
        env.pop(bad)
# Auto-compaction is part of the spec (on, autoCompactWindow 629K of the models' 1M window): drop settings that silently defeat it.
for bad, why in (("DISABLE_AUTO_COMPACT", "turns auto-compaction off"),
                 ("DISABLE_COMPACT", "turns every compaction off"),
                 ("CLAUDE_CODE_AUTO_COMPACT_WINDOW", "overrides autoCompactWindow")):
    if bad in env:
        print("  WARNING: env %s=%s %s — removed (autoCompactWindow=%s is the stack's setting)"
              % (bad, env.pop(bad), why, new.get("autoCompactWindow")))
# Subagent scheduling is part of the spec: BlackCat's children run in the background, a subagent's
# own children in the Agent SDK apps in the foreground (their results reach it). Either key breaks
# that: 1 forces every subagent into the foreground (the main thread blocks on each child, as the
# Desktop "hang" did), or turns fork mode on in the SDK apps, where a subagent then stops waiting
# for its children (their results skip it).
for bad, why in (("CLAUDE_CODE_DISABLE_BACKGROUND_TASKS", "runs every subagent in the foreground, so BlackCat blocks on each child"),
                 ("CLAUDE_CODE_FORK_SUBAGENT", "changes how the Agent SDK apps schedule subagents")):
    if bad in env:
        print("  WARNING: env %s=%s %s — removed" % (bad, env.pop(bad), why))
for warn_only, why in (("CLAUDE_CODE_DISABLE_1M_CONTEXT", "caps every model at 200K, so compaction happens at 200K, not at autoCompactWindow"),
                       ("CLAUDE_AUTOCOMPACT_PCT_OVERRIDE", "makes compaction trigger earlier than autoCompactWindow")):
    if warn_only in env:
        print("  note: env %s=%s %s (kept — remove it if unintended)" % (warn_only, env[warn_only], why))
merged["env"] = env
if "model" in cur:
    print("  note: kept your 'model' setting (%s); the blackcat agent sets the main-thread model" % cur["model"])
order = ["$schema", "agent", "autoCompactEnabled", "autoCompactWindow"]
merged = {**{k: merged[k] for k in order if k in merged}, **{k: v for k, v in merged.items() if k not in order}}
with open(dst + ".tmp", "w", encoding="utf-8") as f:
    json.dump(merged, f, indent=2, ensure_ascii=False)
    f.write("\n")
try:
    os.chmod(dst + ".tmp", os.stat(dst).st_mode & 0o7777)
except OSError:
    pass
os.replace(dst + ".tmp", dst)
manifest["settings_env"] = new.get("env", {})
manifest["settings_permissions"] = {pk: pv for pk, pv in (new.get("permissions") or {}).items()
                                    if isinstance(pv, list)}
manifest["settings_permission_scalars"] = {pk: pv for pk, pv in (new.get("permissions") or {}).items()
                                           if not isinstance(pv, list)}
manifest["settings_permission_scalars_commit"] = manifest.get("commit")
manifest["settings_set_if_absent"] = {k: new[k] for k in SET_IF_ABSENT if k in new}
manifest["settings_sandbox"] = new.get("sandbox") or {}
with open(manifest_path + ".tmp", "w") as f:
    json.dump(manifest, f, indent=2, sort_keys=True)
os.replace(manifest_path + ".tmp", manifest_path)
with open(report_path, "w") as f:
    json.dump(report, f, indent=2, sort_keys=True)
print("  merged into", shown)
PY

# Validate the staged result before anything in $C changes: JSON files parse, every agent and skill
# has sound frontmatter, no placeholder is left, and the staged guard passes its --self-test.
# The self-test probes the guard's state dir by writing to it (creating it): a dry run points it at
# a scratch dir inside $WORK, so it leaves nothing behind.
if ! ( if [ "$DRY_RUN" = 1 ]; then export XDG_STATE_HOME="$WORK/validate-state"; fi
       python3 "$STATE_PY" validate "$S" "$RUN_PY" ); then
  echo "install.sh: the staged install failed validation (above) — nothing in $C was changed." >&2
  exit 1
fi
note "validated: JSON, agent and skill frontmatter, placeholders, agent_guard.py --self-test"
if [ "$NO_DEPS" = 0 ] && [ "$DRY_RUN" = 0 ]; then
  # stdlib only, isolated python3 (no uv run: no environment or config is resolved from the repo);
  # tests/lint_agents.py is in SUPPLY_PATHS, so a change to it was shown before this runs. The policy
  # comes from the STAGED guard (security re-check, CWE-427): agent_guard.py puts its own dir first on
  # sys.path, and the repo's dot-claude/hooks may hold an ignored json.pyc that git never shows;
  # nothing in the repo's dot-claude/ is ever executed.
  # shellcheck disable=SC2086
  if "$RUN_PY" $PY_ISOLATE "$S/hooks/agent_guard.py" --print-policy >"$WORK/policy.json" 2>"$WORK/lint.log" </dev/null \
     && python3 "$SNAP_ROOT/tests/lint_agents.py" --policy-json "$WORK/policy.json" >>"$WORK/lint.log" 2>&1; then note "lint: tests/lint_agents.py ok"
  else note "! tests/lint_agents.py reports problems in the stack repo (installing anyway):"; sed 's/^/      /' "$WORK/lint.log" | head -n 20; fi
fi

echo
python3 "$STATE_PY" plan "$C" "$S" "$REPORT" "$PLAN_JSON" "$SNAP"
B=""
if [ "$DRY_RUN" = 1 ]; then
  note "--dry-run: nothing above was applied"
else
  python3 "$STATE_PY" apply "$C" "$S" "$PLAN_JSON" "$BACKUP_ROOT" "$STACK_COMMIT" "$WORK/backup-dir" "$SNAP"
  B="$(cat "$WORK/backup-dir")"
  mkdir -p "$C"/{agents,skills,hooks,mcp/vendor,magg/kit.d,bin,venvs}
  # The Playwright MCP's --output-dir, rendered into the agents' inline entries and the magg catalog:
  # doctor.sh checks the paths in MCP args and FAILs while it is missing, so it is not left to the
  # server's first write. 0700, like the session-env hook's ~/.cache/claude-sandbox.
  pw_out="${HOME%/}/.cache/claude-sandbox/playwright-mcp"
  if grep -qsF -e "\"$pw_out\"" "$C"/agents/*.md "$C/magg/config.json"; then
    { (umask 077 && mkdir -p "$pw_out") && chmod 700 "$pw_out"; } || note "! could not create $pw_out (the Playwright MCP needs it): mkdir -p it yourself"
  fi
  # the learned limits' live.json: created from the seed only when absent (an older schema is copied
  # to live.v<N>.json and migrated); a variable still at its seed (unset, no evidence, not frozen or
  # held now, never rolled back) takes the new seed when the shipped seed changed, unless that would
  # move a learned partner (soft <= ratio x hard); learned and frozen values are never rewritten.
  # Sessions snapshot it.
  # ==== stack-python (S2): bytecode for the hook modules =========================================
  # compiled by the interpreter the hooks run on, so a session's first hook call is warm; TIMESTAMP
  # pycs (a source whose mtime or size differs from what its pyc records is recompiled on import, so
  # a restore or an edit never runs stale code), beside the sources in the protected
  # hooks/__pycache__ (no PYTHONPYCACHEPREFIX; SOURCE_DATE_EPOCH would switch to checked-hash)
  hook_mods=()
  for m in agent_guard stack_io stack_usage stack_limits stack_report stack_fanout stack_fanout_wire read_gate web_caps stack_hook stack_sched; do
    if [ -f "$C/hooks/$m.py" ]; then hook_mods+=("$C/hooks/$m.py"); fi
  done
  if (unset PYTHONPYCACHEPREFIX SOURCE_DATE_EPOCH
      "$STACK_PYTHON" -m compileall -q -f --invalidation-mode timestamp ${hook_mods[@]+"${hook_mods[@]}"} >"$WORK/compileall.log" 2>&1); then
    note "hook bytecode: ${#hook_mods[@]} modules compiled (timestamp) in $C/hooks/__pycache__"
  else
    note "! compileall of the hook modules failed (the hooks still run, compiling on first use):"
    sed 's/^/      /' "$WORK/compileall.log" | head -n 10
  fi
  # ==== stack-python: END =========================================================================
  if ! seed_out="$("$STACK_PYTHON" "$C/hooks/stack_limits.py" seed 2>&1)"; then
    note "! stack_limits.py seed failed (sessions use the seed values): $seed_out"
  elif [ -n "$seed_out" ]; then
    note "$seed_out"
  fi
  if [ -n "$B" ]; then
    note "backup: $B"
    note "restore: $HERE/install.sh --restore $B"
  fi
fi
# a backup for what the later steps change outside the files (MCP entries, plugins, rc files)
ensure_backup(){
  [ -n "$B" ] && return 0
  B="$(python3 "$STATE_PY" new-backup "$C" "$BACKUP_ROOT" "$STACK_COMMIT")"
  note "backup: $B"
  note "restore: $HERE/install.sh --restore $B"
}

say "8/11 MCP dependency prefetch"
if [ "$NO_DEPS" = 1 ]; then
  note "--no-deps: skipping MCP dependency prefetch"
elif [ "$DRY_RUN" = 1 ]; then
  would "prefetch the MCP servers' packages (libdocs, image-studio, neural-memory, markitdown, mcp-for-blender, lean-lsp-mcp, postgres-mcp, playwright, context-mode, mongodb-mcp-server, mobilebuildmcp)"
elif ! have uv; then
  note "! uv missing — skipping MCP dependency prefetch"
else
  # First starts of stdio servers otherwise race MCP_TIMEOUT while packages download. The servers
  # run with their caches in $STACK_CACHE (the env step 6 rendered into each agent's servers), so
  # that is the cache warmed here, not your own ~/.cache/uv and ~/.npm.
  mkdir -p "$STACK_CACHE" && chmod 700 "$STACK_CACHE"
  (
    # never in the caller's directory (the stack repo, which sandboxed agents can write): npx/npm exec
    # prefer a matching package in ./node_modules, and npm/uv read .npmrc, package.json, uv.toml from cwd up
    cd / || exit 0
    export UV_CACHE_DIR="$STACK_CACHE/uv" npm_config_cache="$STACK_CACHE/npm"
    for f in image_studio_mcp.py libdocs_mcp.py neural_memory_mcp.py; do uv run --quiet --script "$C/mcp/$f" --help >/dev/null 2>&1 </dev/null || true; done
    # the usage collector's model refit (pandas, numpy) runs offline from this cache at session end, with
    # the environment stack_usage.refresh_env() gives it (no venv/conda/uv interpreter vars, fixed PATH,
    # --no-config, cwd /), so the interpreter and the script env chosen here are the ones it finds
    (cd / && env -u VIRTUAL_ENV -u CONDA_PREFIX -u CONDA_DEFAULT_ENV -u UV_INTERNAL__PARENT_INTERPRETER \
       -u UV_PYTHON -u UV_CONFIG_FILE -u PYTHONPATH -u PYTHONHOME PATH=/usr/bin:/bin:/usr/sbin:/sbin \
       PYTHONDONTWRITEBYTECODE=1 "$(command -v uv)" run --quiet --no-config --script \
       "$C/hooks/stack_sched_refresh.py" --help) >/dev/null 2>&1 </dev/null || true
    ! have uvx || uvx --quiet markitdown-mcp@0.0.1a7 --help >/dev/null 2>&1 </dev/null || true
    # cg-artist's Blender server: download only (it would wait on the Blender add-on's socket)
    uv tool run --quiet --from mcp-for-blender==2.1.1 python -c pass >/dev/null 2>&1 </dev/null || true
    # proof-checker's Lean server: download only (starting it would start the Lean toolchain)
    uv tool run --quiet --from lean-lsp-mcp==0.30.0 python -c pass >/dev/null 2>&1 </dev/null || true
    # data-engineer's Postgres server: download only (starting it needs DATABASE_URI)
    uv tool run --quiet --from postgres-mcp==0.3.0 python -c pass >/dev/null 2>&1 </dev/null || true
    ! have npx || npx -y @playwright/mcp@0.0.82 --help >/dev/null 2>&1 </dev/null || true
    ! have npx || npx -y context-mode@1.0.169 --help >/dev/null 2>&1 </dev/null || true
    # data-engineer's MongoDB and mobile-engineer's MobileBuildMCP servers: download only (fills npx's
    # cache with the package and its dependencies; runs only `node -e 0`)
    ! have npx || npm exec --yes --package=mongodb-mcp-server@3.0.5 -- node -e 0 >/dev/null 2>&1 </dev/null || true
    [ "$(uname -s)" != Darwin ] || ! have npx || npm exec --yes --package=mobilebuildmcp@2.7.1 -- node -e 0 >/dev/null 2>&1 </dev/null || true
  )
  note "prefetched libdocs, image-studio, neural-memory, markitdown, mcp-for-blender, lean-lsp-mcp, postgres-mcp, playwright, context-mode, mongodb-mcp-server, mobilebuildmcp (cache: $STACK_CACHE)"
fi

say "9/11 MCP servers (user scope, remote HTTP — lazy connect, tools deferred, keys via headersHelper)"
compute_mcp_plan

# User-scope servers the stack registered once and no longer uses: removed through `claude mcp`
# (the backup keeps each entry; --restore re-adds it): the names the manifest recorded
# (mcp_registered) that the stack stopped shipping. An entry that
# points elsewhere than the stack's host is yours and stays.
stale_mcp(){ python3 - "$CFG" "$C/.stack-manifest.json" "$PLAN" <<'PY'
import json, re, sys
from urllib.parse import urlsplit
cfg_path, manifest_path, plan = sys.argv[1:4]
def load(p):
    try:
        v = json.load(open(p))
        return v if isinstance(v, dict) else {}
    except (OSError, ValueError):
        return {}
servers = (load(cfg_path).get("mcpServers") or {})
shipped = {line.split("\t")[1] for line in plan.splitlines() if line.count("\t") >= 1}
known = {}
NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}\Z")
HOST = re.compile(r"(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}\Z")
reg = load(manifest_path).get("mcp_registered")
for name, host in (reg.items() if isinstance(reg, dict) else ()):
    # a manifest entry names one of the stack's servers by its host: a name or host that isn't
    # one (empty, a bare TLD, odd characters) matches nothing
    if isinstance(name, str) and isinstance(host, str) and NAME.match(name) and HOST.match(host) \
            and name not in shipped:
        known[name] = (host, "no longer shipped by the stack")
for name, (host, why) in sorted(known.items()):
    cur = servers.get(name)
    got = (urlsplit(str(cur.get("url", ""))).hostname or "") if isinstance(cur, dict) else ""
    if got and (got == host or got.endswith("." + host)):
        print("%s\t%s\t%s" % (name, json.dumps(cur), why))
PY
}
if [ "$SKIP_MCP" = 1 ]; then
  note "--no-mcp: skipped registering user-scope MCP servers"
elif [ "$DRY_RUN" = 1 ]; then
  stale_mcp | while IFS=$'\t' read -r name _prev why; do
    would "claude mcp remove -s user $name  (removed: $why)"
  done
  printf '%s\n' "$PLAN" | while IFS=$'\t' read -r action name _cfg _prev _save why; do
    [ -n "$name" ] || continue
    case "$action" in keep) note "= $name ($why)" ;; *) would "claude mcp add-json -s user $name ...  ($action: $why)" ;; esac
  done
else
  stale="$(stale_mcp)"
  if [ -n "$stale" ]; then
    ensure_backup
    while IFS=$'\t' read -r name prev why; do
      [ -n "$name" ] || continue
      STACK_MCP_ENTRY="$prev" python3 "$STATE_PY" record "$B" mcp_removed "$name"
      if claude mcp remove -s user "$name" >/dev/null 2>&1 </dev/null; then note "- removed MCP server $name ($why; the backup keeps its entry)"
      else note "! could not remove MCP server $name — claude mcp remove -s user $name"; fi
    done <<EOF_STALE
$stale
EOF_STALE
  fi
  # (a here-document, not a pipe: the loop runs in this shell, so the backup it may create is the run's)
  while IFS=$'\t' read -r action name cfg prev save why; do
    [ -n "$name" ] || continue
    case "$action" in
      keep) note "= $name ($why)"; continue ;;
      add)
        if claude mcp get "$name" >/dev/null 2>&1 </dev/null; then
          note "= $name already configured where claude looks — kept yours (--replace-mcp to overwrite)"; continue
        fi ;;
    esac
    ensure_backup
    # the entry this replaces goes into the backup (--restore puts it back)
    [ "$prev" != "null" ] && STACK_MCP_ENTRY="$prev" python3 "$STATE_PY" record "$B" mcp_replaced "$name"
    if [ "$save" != "-" ]; then
      python3 "$STATE_PY" record "$B" file stack.env
      # The entry carries a literal key and stack.env has none: copy it there first, or the
      # migration would silently discard the user's key. (Passed via env, not argv.)
      if ! PREV="$prev" python3 - "$C/stack.env" "$name" "$save" "$SRC/bin/mcp-headers" <<'PY'
import json, os, re, runpy, sys
from pathlib import Path
envfile, name, var, parser = sys.argv[1:5]
mh = runpy.run_path(parser, run_name="mcp_headers")
key = mh["key_from_entry"](name, json.loads(os.environ["PREV"]))
if not key:
    sys.exit(1)
envfile = os.path.realpath(envfile)
try:
    lines = open(envfile, encoding="utf-8").read().splitlines(keepends=True)
except FileNotFoundError:
    lines = []
have = mh["read_env_file"](Path(envfile)).get(var, "")
if have and "$" not in have and mh["VALUE_RE"].fullmatch(have):
    sys.exit(0)                         # a usable value is already there: never overwrite it
pat = re.compile(r"^\s*(?:export\s+)?%s\s*=" % re.escape(var))
done = False
if not have:                            # fill the empty KEY= line in place
    for i, l in enumerate(lines):
        if pat.match(l):
            lines[i] = "%s=%s\n" % (var, key)
            done = True
            break
if not done:                            # keep the user's (unusable) line; a later assignment wins
    if lines and not lines[-1].endswith("\n"):
        lines[-1] += "\n"
    lines.append("# copied by install.sh from the %s MCP entry\n%s=%s\n" % (name, var, key))
tmp = envfile + ".tmp"
fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
with os.fdopen(fd, "w", encoding="utf-8") as f:
    f.writelines(lines)
os.replace(tmp, envfile)
PY
      then
        note "! could not copy $name's key into $C/stack.env — left the $name entry unchanged"; continue
      fi
      note "  copied $name's key from $CFG into $C/stack.env ($save)"
    fi
    claude mcp remove -s user "$name" >/dev/null 2>&1 </dev/null || true
    if claude mcp add-json -s user "$name" "$cfg" >/dev/null 2>&1 </dev/null; then
      note "+ $name ($action: $why)"
    else
      note "! failed to add $name — run: claude mcp add-json -s user $name '$cfg'"
      if [ "$prev" != "null" ] && claude mcp add-json -s user "$name" "$prev" >/dev/null 2>&1 </dev/null; then
        note "  restored your previous $name entry"
      fi
    fi
  done <<EOF_PLAN
$PLAN
EOF_PLAN
  # the servers the stack registered (a later version that stops shipping one removes it, above)
  for mode in check write; do
  python3 - "$C/.stack-manifest.json" "$PLAN" "$mode" <<'PY' || break
import json, os, sys
from urllib.parse import urlsplit
path, plan, mode = sys.argv[1:4]
try:
    m = json.load(open(path))
except (OSError, ValueError):
    m = {}
reg = {}
for line in plan.splitlines():
    f = line.split("\t")
    if len(f) >= 6 and (f[0] != "keep" or f[5] == "up to date"):
        reg[f[1]] = urlsplit(json.loads(f[2]).get("url", "")).hostname or ""
if m.get("mcp_registered") == reg:
    sys.exit(3)
if mode == "write":
    m["mcp_registered"] = reg
    with open(path + ".tmp", "w") as out:
        json.dump(m, out, indent=2, sort_keys=True)
    os.replace(path + ".tmp", path)
PY
  if [ "$mode" = check ]; then ensure_backup; python3 "$STATE_PY" record "$B" file .stack-manifest.json; fi
  done
  if [ -f "$CFG" ]; then
    chmod 600 "$CFG" 2>/dev/null || true
    if grep -Eq '"(x-api-key|Authorization)"[[:space:]]*:[[:space:]]*"[^"$]{8,}' "$CFG" 2>/dev/null; then
      note "! $CFG still contains a literal API key in some MCP server's headers — run: ./install.sh --mcp-plan, or move it to stack.env"
    fi
  fi
  # Same services registered under other names won't match the agents' tool allowlists.
  claude mcp list 2>/dev/null </dev/null | while IFS= read -r l; do
    n="${l%%:*}"
    case "$l" in
      *mcp.exa.ai*|*exa-mcp*) [ "$n" = exa ] || note "! '$n' looks like Exa — rename it to 'exa' (agents allow mcp__exa)";;
      *mcp.jina.ai*|*jina-mcp*) [ "$n" = jina ] || note "! '$n' looks like Jina — rename it to 'jina'";;
      *huggingface.co/mcp*) [ "$n" = huggingface ] || note "! '$n' looks like the Hugging Face MCP — rename it to 'huggingface'";;
      *spider-cloud-mcp*|*spider.cloud*) [ "$n" = spider ] || note "! '$n' looks like Spider — rename it to 'spider'";;
      *mcp.context7.com*) note "- '$n' (Context7) is no longer used — libdocs replaces it; remove with: claude mcp remove -s user $n";;
    esac
  done
fi

say "10/11 Plugins and code intelligence"
if [ "$SKIP_PLUGINS" = 0 ] && [ "$MCP_PLAN" = 0 ]; then
  # `claude plugin ...`, or under --dry-run the line it would run
  pcmd(){ if [ "$DRY_RUN" = 1 ]; then would "claude $*"; else claude "$@" >/dev/null 2>&1 </dev/null; fi; }
  # claude.ai sync puts Anthropic's skills in $C/skills/synced/<id>/<name> (older builds:
  # $C/skills/synced/<name>); a plugin copy of a synced skill only doubles its skill-listing entry.
  synced_skill(){ for d in "$C/skills/synced/$1" "$C"/skills/synced/*/"$1"; do [ -f "$d/SKILL.md" ] && return 0; done; return 1; }
  plugin_on(){ python3 -c 'import json,sys; sys.exit(0 if (json.load(open(sys.argv[1])).get("enabledPlugins") or {}).get(sys.argv[2]) is True else 1)' "$C/settings.json" "$1" 2>/dev/null; }
  # The manifest's "plugins_deduped" lists the plugins the installer disabled ($1 add|drop|has).
  deduped(){ [ "$DRY_RUN" = 1 ] && [ "$1" != has ] && return 0; python3 - "$C/.stack-manifest.json" "$1" "$2" <<'PY'
import json, os, sys
p, op, pid = sys.argv[1:4]
try:
    m = json.load(open(p))
except (OSError, ValueError):
    m = {}
xs = [x for x in m.get("plugins_deduped") or [] if isinstance(x, str)]
if op == "has":
    sys.exit(0 if pid in xs else 1)
xs = sorted(set(xs) | {pid}) if op == "add" else [x for x in xs if x != pid]
m["plugins_deduped"] = xs
with open(p + ".tmp", "w") as f:
    json.dump(m, f, indent=2, sort_keys=True)
os.replace(p + ".tmp", p)
PY
  }
  plugin_off(){  # $1 plugin id, $2 why: disabled, recorded in the backup (--restore re-enables it)
    if [ "$DRY_RUN" = 1 ]; then would "claude plugin disable $1 --scope user  ($2)"; return 0; fi
    ensure_backup
    python3 "$STATE_PY" record "$B" file .stack-manifest.json
    if claude plugin disable "$1" --scope user >/dev/null 2>&1 </dev/null; then
      python3 "$STATE_PY" record "$B" plugins_disabled "$1"
      deduped add "$1"
      note "- disabled plugin $1: $2"
      note "  To undo: claude plugin enable $1 --scope user"
    else
      note "! inside claude: /plugin disable $1 ($2)"
    fi
  }
  # One copy of each skill (the default): a plugin copy of a claude.ai-synced skill is disabled, the
  # synced copy (which can't be removed) stays. Synced skills load only in sessions signed in to
  # claude.ai (/login); API-key, gateway, Bedrock/Vertex and --bare sessions see none of them, so
  # --keep-plugin-duplicates keeps both.
  dup_plugin(){  # $1 plugin id, $2 synced skill name(s) that duplicate it
    plugin_on "$1" || return 0
    if [ "$DEDUPE_PLUGINS" = 1 ]; then
      plugin_off "$1" "the synced anthropic-skills:$2 already provides it (claude.ai-login sessions; --keep-plugin-duplicates keeps both)"
    else
      note "plugin $1 duplicates the synced anthropic-skills:$2 in the skill listing (kept: --keep-plugin-duplicates)"
    fi
  }
  # A plugin the installer disabled comes back once claude.ai no longer syncs its skills.
  undedupe(){  # $1 plugin id, $2 synced skill it stood in for
    deduped has "$1" || return 0
    synced_skill "$2" && return 0
    if [ "$DRY_RUN" = 1 ]; then would "claude plugin enable $1 --scope user  (the synced $2 skill is gone)"
    elif ensure_backup && python3 "$STATE_PY" record "$B" file .stack-manifest.json \
         && claude plugin enable "$1" --scope user >/dev/null 2>&1 </dev/null; then
      deduped drop "$1"; note "+ re-enabled plugin $1: the synced $2 skill is gone"
    else
      note "! the synced $2 skill is gone: claude plugin enable $1 --scope user"
    fi
  }
  undedupe skill-creator@claude-plugins-official skill-creator
  undedupe document-skills@anthropic-agent-skills docx
  synced_skill skill-creator && dup_plugin skill-creator@claude-plugins-official skill-creator
  if synced_skill docx; then
    note "docx/xlsx/pptx/pdf skills already synced from claude.ai — skipping document-skills plugin"
    dup_plugin document-skills@anthropic-agent-skills "docx/xlsx/pptx/pdf"
  elif [ "$DRY_RUN" = 1 ]; then
    plugin_on document-skills@anthropic-agent-skills || would "claude plugin install document-skills@anthropic-agent-skills --scope user"
  else
    claude plugin marketplace add anthropics/skills >/dev/null 2>&1 </dev/null || true
    claude plugin install document-skills@anthropic-agent-skills --scope user >/dev/null 2>&1 </dev/null \
      && note "+ document-skills (docx, xlsx, pptx, pdf)" \
      || note "! run inside claude: /plugin marketplace add anthropics/skills  then  /plugin install document-skills@anthropic-agent-skills"
  fi
  # Plugins the stack's own skills replaced (mcp-server-craft absorbed mcp-server-dev's three
  # skills): disabled with the duplicates.
  for p in $RETIRED_PLUGINS; do
    plugin_on "$p" || continue
    if [ "$DEDUPE_PLUGINS" = 1 ]; then plugin_off "$p" "the stack's mcp-server-craft skill covers it (one copy of each skill)"
    else note "plugin $p overlaps the stack's mcp-server-craft skill (kept: --keep-plugin-duplicates)"; fi
  done
  # Code intelligence: a language server starts only when Claude edits a matching file (on demand).
  # --with-lsp installs the missing servers: jdtls in step 2 (lib/devtools.sh's LSP group, Homebrew's
  # formula), the others here, each by its language's own route. Each install's output goes to its
  # own log in a private dir under $TMPDIR (mktemp -d: 0700), kept when an install failed (the line
  # names the log and shows its end), else removed. Why a server is still missing is recorded
  # (lsp_why: "server|cause" lines) for the line that ends this step.
  lsp_why=""; lsp_logs=""; lsp_keep=0
  lsp_cause(){ lsp_why="$lsp_why$1|$2
"; }
  lsp_cause_of(){ local l; while IFS= read -r l; do case "$l" in "$1|"*) printf '%s' "${l#*|}"; break ;; esac; done <<<"$lsp_why"; return 0; }
  # lsp_get SERVER ROUTE CMD...: run CMD (ROUTE names it in the lines) into SERVER's log, then SERVER must run
  lsp_get(){
    local s="$1" route="$2" log rc=0 why; shift 2
    if [ -z "$lsp_logs" ] && ! lsp_logs="$(mktemp -d "${TMPDIR:-/tmp}/stack-lsp.XXXXXX")"; then
      lsp_logs=""; lsp_cause "$s" "not tried (no temp dir for its log): $route"; note "! $s: not tried (no temp dir for its log): $route"
      return 0
    fi
    log="$lsp_logs/$s.log"
    "$@" >"$log" 2>&1 </dev/null || rc=$?
    if lsp_works "$s"; then note "+ $s ($route)"; return 0; fi
    if [ "$rc" = 0 ]; then why="$route ran, but $s still does not run (log $log)"; else why="$route failed (log $log)"; fi
    lsp_keep=1; lsp_cause "$s" "$why"; note "! $s: $why"
    { tail -n 5 "$log" | sed 's/^/      /'; } 2>/dev/null || true
    return 0
  }
  brew_q(){ HOMEBREW_NO_ANALYTICS=1 HOMEBREW_NO_AUTO_UPDATE=1 brew "$@"; }
  # the skip rule: a server found outside this run's PATH (MacPorts, a nix profile, ...) is never installed again
  lsp_off_path(){
    local w tab; tab="$(printf '\t')"
    w="$(tool_where "$1")" || return 1
    lsp_cause "$1" "found at ${w%%"$tab"*} (from ${w#*"$tab"}), which is not on PATH: add its folder to PATH"
  }
  # Pinned versions, install scripts off (none of these packages needs one): what runs is what
  # was reviewed (versions checked against the npm registry 2026-09-29).
  PYRIGHT_PIN="pyright@1.1.414"
  # typescript-language-server 6 needs Node >= 22.22.2; older Node gets the 5.x line. TypeScript 7
  # (the native compiler) ships no tsserver, which the language server runs: 6.x it is.
  TSLS="typescript-language-server@6.0.1"
  TS_PIN="typescript@6.0.3"
  if [ "$WITH_LSP" = 1 ]; then
    node -e 'const [a,b,c]=process.versions.node.split(".").map(Number); process.exit(a>22||(a===22&&(b>22||(b===22&&c>=2)))?0:1)' 2>/dev/null \
      || TSLS="typescript-language-server@5.3.0"
  fi
  # how each server comes: the dry-run lines, and the end of this step when nothing more is known
  lsp_route(){ case "$1" in
    pyright-langserver) echo "npm install -g --ignore-scripts $PYRIGHT_PIN" ;;
    typescript-language-server) echo "npm install -g --ignore-scripts $TSLS $TS_PIN" ;;
    rust-analyzer) echo "rustup component add rust-analyzer (no rustup: brew install rust-analyzer)" ;;
    jdtls) echo "brew install jdtls in step 2's Homebrew batch (the LSP group; it brings Homebrew's openjdk and python@3.14)" ;;
    kotlin-lsp) echo "brew install --cask kotlin-lsp" ;;
    haskell-language-server-wrapper) echo "ghcup install hls recommended (ghcup: step 2's HASKELL group)" ;;
    julia-languageserver) echo "LanguageServer.jl into the Julia environment @claude-lsp (julia: step 2's JULIA group)" ;;
    metals) echo "cs install metals (Coursier: step 2's SCALA group)" ;;
    lake) echo "comes with elan (step 2's LEAN group, skipped while the open-file limit is below 65536)" ;;
    gopls) echo "brew install gopls (step 2's GO group)" ;;
    sourcekit-lsp|clangd) echo "comes with Xcode's Command Line Tools: xcode-select --install" ;;
    *) echo "no install route in the stack" ;;
  esac; }
  if [ "$WITH_LSP" = 1 ] && [ "$NO_DEPS" = 0 ] && [ "$DRY_RUN" = 1 ]; then
    # jdtls is in step 2's would: line (the brew batch)
    for s in pyright-langserver typescript-language-server rust-analyzer kotlin-lsp haskell-language-server-wrapper julia-languageserver metals; do
      lsp_works "$s" || would "$s ← $(lsp_route "$s")"
    done
  elif [ "$WITH_LSP" = 1 ] && [ "$NO_DEPS" = 0 ]; then
    # npm -g goes into Node's own prefix when that is writable and outlives Node upgrades (Homebrew);
    # a root-owned distro prefix (/usr: EACCES) or a version manager's per-version prefix under
    # $HOME (nvm, fnm, volta) gets ~/.local instead (bin/ there is on PATH via the profile line).
    npm_g(){
      local pfx; pfx="$(npm prefix -g 2>/dev/null || true)"
      case "$pfx" in
        ""|"$HOME"/*) npm install -g --ignore-scripts --prefix "$HOME/.local" --silent "$@" ;;
        *) if [ -w "$pfx/lib" ]; then npm install -g --ignore-scripts --silent "$@"; else npm install -g --ignore-scripts --prefix "$HOME/.local" --silent "$@"; fi ;;
      esac
    }
    for s in pyright-langserver typescript-language-server; do
      lsp_works "$s" && continue
      if ! have npm; then lsp_cause "$s" "no npm (node: step 2's NODE group), then $(lsp_route "$s")"
      elif [ "$s" = pyright-langserver ]; then lsp_get "$s" "$(lsp_route "$s")" npm_g "$PYRIGHT_PIN"
      else lsp_get "$s" "$(lsp_route "$s")" npm_g "$TSLS" "$TS_PIN"; fi
    done
    # rustup's rust-analyzer proxy without the component is a found tool that doesn't run: WARN, not installed
    if lsp_works rust-analyzer; then :
    elif have rust-analyzer; then
      if have rustup; then ra_fix="rustup component add rust-analyzer"; else ra_fix="reinstall it the way you installed it (no rustup here)"; fi
      note "WARN rust-analyzer at $(command -v rust-analyzer) fails 'rust-analyzer --version'; left alone. Fix: $ra_fix"
      lsp_cause rust-analyzer "$(command -v rust-analyzer) fails 'rust-analyzer --version' (left alone). Fix: $ra_fix"
    elif have rustup; then lsp_get rust-analyzer "rustup component add rust-analyzer" rustup component add rust-analyzer
    elif lsp_off_path rust-analyzer; then :
    elif have brew; then lsp_get rust-analyzer "brew install rust-analyzer" brew_q install rust-analyzer
    else lsp_cause rust-analyzer "no rustup and no Homebrew (rustup: step 2's RUST group, then rustup component add rust-analyzer)"; fi
    # kotlin-lsp: Homebrew's cask (a plain binary, no installer that asks for a password), as in step 2's JAVA group
    if ! lsp_works kotlin-lsp && ! lsp_off_path kotlin-lsp; then
      if have brew; then lsp_get kotlin-lsp "brew install --cask kotlin-lsp" brew_q install --cask kotlin-lsp
      else lsp_cause kotlin-lsp "no Homebrew (step 2 installs it on a terminal), then brew install --cask kotlin-lsp"; fi
    fi
    # jdtls comes from step 2's Homebrew batch (the LSP group); still missing here, that batch failed or
    # left it out: one more try, with its own log for the lines below
    if ! lsp_works jdtls && ! lsp_off_path jdtls; then
      if [ "${STACK_INSTALL_LSP:-1}" = 0 ]; then lsp_cause jdtls "STACK_INSTALL_LSP=0 kept it out of step 2: brew install jdtls"
      elif have brew; then lsp_get jdtls "brew install jdtls" brew_q install jdtls
      else lsp_cause jdtls "no Homebrew (step 2 installs it on a terminal; then run the installer again), or brew install jdtls"; fi
    fi
    # Servers for the stack's other languages come from each language's own toolchain manager, and
    # only when that manager is already here (step 2 installs GHCup, juliaup, elan and Coursier unless
    # their group is off). Lean needs nothing extra (elan's `lake serve` is the server).
    if ! lsp_works haskell-language-server-wrapper; then
      if have ghcup; then lsp_get haskell-language-server-wrapper "ghcup install hls recommended (then ghcup set hls recommended)" ghcup install hls recommended
      else lsp_cause haskell-language-server-wrapper "no ghcup (step 2's HASKELL group installs it, with HLS)"; fi
    fi
    if ! lsp_works julia-languageserver; then
      if have julia; then
        note "  installing LanguageServer.jl into the Julia environment @claude-lsp (a few minutes the first time)"
        lsp_get julia-languageserver "julia --project=@claude-lsp -e 'using Pkg; Pkg.add(\"LanguageServer\")'" \
          julia --startup-file=no --history-file=no --project=@claude-lsp -e 'using Pkg; Pkg.add("LanguageServer")'
      else lsp_cause julia-languageserver "no julia (step 2's JULIA group installs juliaup)"; fi
    fi
    if ! lsp_works metals; then
      if have cs; then lsp_get metals "cs install metals" cs install metals
      else lsp_cause metals "no Coursier (step 2's SCALA group installs cs)"; fi
    fi
  fi
  [ -z "$lsp_logs" ] || [ "$lsp_keep" = 1 ] || rm -rf "$lsp_logs"
  [ "$DRY_RUN" = 1 ] || claude plugin marketplace add anthropics/claude-plugins-official >/dev/null 2>&1 </dev/null || true
  lsp_added=""; lsp_failed=""; lsp_missing=""
  for pair in pyright-langserver:pyright-lsp typescript-language-server:typescript-lsp rust-analyzer:rust-analyzer-lsp sourcekit-lsp:swift-lsp clangd:clangd-lsp gopls:gopls-lsp jdtls:jdtls-lsp kotlin-lsp:kotlin-lsp; do
    b="${pair%%:*}"; p="${pair##*:}"
    if lsp_works "$b"; then
      # `claude plugin install` exits 0 when the plugin is already installed, so a failure is real
      if plugin_on "$p@claude-plugins-official" && [ "$DRY_RUN" = 1 ]; then :
      elif pcmd plugin install "$p@claude-plugins-official" --scope user; then lsp_added="$lsp_added $p"; else lsp_failed="$lsp_failed $p"; fi
    else
      lsp_missing="$lsp_missing $b"
    fi
  done
  # Languages the official marketplace has no code-intelligence plugin for (Haskell, Julia, Lean 4,
  # Scala) come from the stack's own local marketplace, installed at $C/stack-plugins (step 7). A
  # directory marketplace loads its plugins in place, so a re-run's copy takes effect at the next session.
  if [ -d "$SRC/stack-plugins" ]; then
    if pcmd plugin marketplace add "$C/stack-plugins"; then
      for pair in haskell-language-server-wrapper:haskell-lsp julia-languageserver:julia-lsp lake:lean-lsp metals:metals-lsp; do
        b="${pair%%:*}"; p="${pair##*:}"
        if lsp_works "$b"; then
          if plugin_on "$p@agent-stack" && [ "$DRY_RUN" = 1 ]; then :
          elif pcmd plugin install "$p@agent-stack" --scope user; then lsp_added="$lsp_added $p"; else lsp_failed="$lsp_failed $p@agent-stack"; fi
        else
          lsp_missing="$lsp_missing $b"
        fi
      done
    else
      note "! could not add the stack's plugin marketplace — inside claude: /plugin marketplace add $C/stack-plugins"
    fi
  fi
  [ -n "$lsp_added" ] && [ "$DRY_RUN" = 0 ] && note "+ code intelligence:$lsp_added"
  [ -n "$lsp_failed" ] && note "! plugin install failed:$lsp_failed (inside claude: /plugin install <name>@claude-plugins-official, or <name>@agent-stack)"
  # Still missing: without --with-lsp, how to get them; with it, why each one is missing (what failed,
  # with its log, or what it needs), never "use --with-lsp".
  if [ -n "$lsp_missing" ] && [ "$WITH_LSP" = 0 ]; then
    note "- no language server for:$lsp_missing (./install.sh --with-lsp installs pyright, typescript-language-server, rust-analyzer, jdtls and kotlin-lsp, and HLS, LanguageServer.jl, Metals through ghcup, julia, cs when those are present; sourcekit-lsp and clangd come with Xcode's Command Line Tools: xcode-select --install; lake with elan)"
  elif [ -n "$lsp_missing" ]; then
    lsp_tag=""
    if [ "$NO_DEPS" = 1 ]; then lsp_tag=" (--no-deps: nothing was installed)"
    elif [ "$DRY_RUN" = 1 ]; then lsp_tag=" (dry run: a real run tries the routes below)"; fi
    note "- no language server for:$lsp_missing$lsp_tag"
    for b in $lsp_missing; do
      c="$(lsp_cause_of "$b")"; [ -n "$c" ] || c="$(lsp_route "$b")"
      note "    $b: $c"
    done
  fi
  # Optional Anthropic skill plugins (skill-creator for claude-code-engineer, math-olympiad for the
  # mathematician). Only their descriptions sit in context; the skills load when a task matches. A
  # plugin whose skills claude.ai already syncs is skipped (one copy of each skill).
  if [ "$WITH_EXTRA_PLUGINS" = 1 ]; then
    extra_added=""; extra_failed=""
    for p in $EXTRA_PLUGINS; do
      [ "$DEDUPE_PLUGINS" = 1 ] && synced_skill "$p" && continue
      if plugin_on "$p@claude-plugins-official" && [ "$DRY_RUN" = 1 ]; then continue; fi
      if pcmd plugin install "$p@claude-plugins-official" --scope user; then extra_added="$extra_added $p"; else extra_failed="$extra_failed $p"; fi
    done
    [ -n "$extra_added" ] && [ "$DRY_RUN" = 0 ] && note "+ extra skill plugins:$extra_added"
    [ -n "$extra_failed" ] && note "! plugin install failed:$extra_failed (inside claude: /plugin install <name>@claude-plugins-official)"
  fi
else
  note "plugins skipped"
fi

say "11/11 Shell profile"
PROFILE_NOTE=""
if [ "$NO_PROFILE" = 1 ]; then
  note "--no-profile: leaving shell rc files alone"
elif [ "$DRY_RUN" = 1 ]; then
  for rc in "$HOME/.zshrc" "$HOME/.bashrc"; do
    if [ -f "$rc" ] || { [ "$rc" = "$HOME/.zshrc" ] && [ "$OS" = "Darwin" ]; }; then
      if grep -qE '# claude-agent-stack[[:space:]]*$' "$rc" 2>/dev/null && grep -q 'with-stack-env\" --print-env --reveal sh' "$rc" 2>/dev/null; then
        note "= $rc already sources stack.env"
      else
        would "add (or update) the stack.env line in $rc (backed up first)"
      fi
    fi
  done
  for n in claude-ninja; do
    [ -e "$HOME/.local/bin/$n" ] || [ -L "$HOME/.local/bin/$n" ] || would "ln -s $C/bin/claude-ultracode $HOME/.local/bin/$n"
  done
else
  # Exports only the NON-EMPTY keys (an empty KEY= must not blank a token exported earlier in the
  # rc file) and parses stack.env exactly like with-stack-env/mcp-headers.
  # --reveal: this line exports real values into the user's own shell (that is its job); the
  # default redaction in with-stack-env --print-env is for a human running it by hand to inspect.
  LINE="[ -x \"$C/bin/with-stack-env\" ] && eval \"\$(\"$C/bin/with-stack-env\" --print-env --reveal sh)\"  # claude-agent-stack"
  for rc in "$HOME/.zshrc" "$HOME/.bashrc"; do
    if [ -f "$rc" ] || { [ "$rc" = "$HOME/.zshrc" ] && [ "$OS" = "Darwin" ]; }; then
      # Only the line this installer wrote (it ENDS with the marker) is replaced — never other lines
      # that merely mention claude-agent-stack (an alias or PATH entry for this repo, say). A check
      # pass first, so the rc file is backed up only when it will change.
      set +e
      for mode in check write; do
      python3 - "$rc" "$LINE" "$mode" <<'PY'
import os, sys
rc, line, mode = sys.argv[1], sys.argv[2], sys.argv[3]
try:
    text = open(rc, encoding="utf-8", errors="surrogateescape").read()
except FileNotFoundError:
    text = ""
def ours(l):
    s = l.rstrip("\r\n").rstrip()
    return s.endswith("# claude-agent-stack") and ("stack.env" in s or "with-stack-env" in s)
out, placed = [], False
for l in text.splitlines(keepends=True):
    if ours(l):
        if not placed:
            out.append(line + "\n")
            placed = True
        continue
    out.append(l)
if not placed:
    if text and not text.endswith("\n"):
        out.append("\n")
    out.append("\n" + line + "\n")
new = "".join(out)
if new == text:
    sys.exit(3)
if mode == "check":
    sys.exit(0)
with open(os.path.realpath(rc), "w", encoding="utf-8", errors="surrogateescape") as f:
    f.write(new)
PY
      st=$?
      [ "$mode" = check ] && [ "$st" = 0 ] || break
      ensure_backup
      [ -f "$rc" ] && python3 "$STATE_PY" record "$B" rc "$(python3 -c 'import os,sys;print(os.path.realpath(sys.argv[1]))' "$rc")"
      done
      set -e
      case "$st" in
        0) note "+ $rc sources stack.env (the backup keeps the previous copy)" ;;
        3) note "= $rc already sources stack.env" ;;
        *) note "! could not update $rc — add this line yourself: $LINE" ;;
      esac
    fi
  done
  # claude-ninja: ninja-coder as the main thread at ultracode, the only
  # place ultracode runs (an agent file's effort reaches subagents only, and they can't run workflows).
  mkdir -p "$HOME/.local/bin"
  for n in claude-ninja; do
    l="$HOME/.local/bin/$n"
    if [ "$(readlink "$l" 2>/dev/null)" = "$C/bin/claude-ultracode" ]; then
      note "= $n (ultracode launcher)"
    elif [ ! -e "$l" ] && [ ! -L "$l" ]; then
      ln -s "$C/bin/claude-ultracode" "$l" && note "+ $l: ${n#claude-}-coder as the main thread at ultracode"
    else
      note "! $l exists and isn't the stack's: left alone ($C/bin/claude-ultracode ${n#claude-}-coder does the same)"
    fi
  done
  case "$(basename "${SHELL:-}")" in
    zsh|"") ;;
    bash)  # macOS Terminal starts login shells: bash reads ~/.bash_profile there, not ~/.bashrc
      if [ -f "$HOME/.bashrc" ] && ! grep -qs 'bashrc' "$HOME/.bash_profile"; then
        PROFILE_NOTE="your login shell is bash, whose login shells (macOS Terminal) read ~/.bash_profile, not ~/.bashrc: add  [ -f ~/.bashrc ] && . ~/.bashrc  to ~/.bash_profile"
      fi ;;
    *) PROFILE_NOTE="your login shell is $SHELL: export the keys of $C/stack.env there yourself" ;;
  esac
fi

# Backups of this config dir: say when they pile up (the installer never deletes one).
n_b="$(python3 - "$STATE_PY" "$C" "$BACKUP_ROOT" <<'PY'
import importlib.util, sys
spec = importlib.util.spec_from_file_location("install_state", sys.argv[1])
st = importlib.util.module_from_spec(spec)
spec.loader.exec_module(st)
print(len(st.backups_of(sys.argv[2], sys.argv[3])))
PY
)"
[ "${n_b:-0}" -gt 10 ] && note "$n_b backups of $C in $BACKUP_ROOT: delete the old ones you no longer need"
case ":$ORIG_PATH:" in
  *":$HOME/.local/bin:"*) ;;
  *) [ "$NO_PROFILE" = 1 ] && note "! ~/.local/bin is not on your PATH (uv, magg, huetension, language servers): add it to your shell profile" ;;
esac

if [ "$DRY_RUN" = 1 ]; then
  if [ -n "$LINK_REFUSAL" ]; then
    echo "install.sh --dry-run: the real run would stop: $LINK_REFUSAL" >&2
    exit 1
  fi
  say "Dry run done: nothing was changed. Run without --dry-run to apply the plan above."
  exit 0
fi
say "Done. Next:"
[ -n "$PROFILE_NOTE" ] && note "! $PROFILE_NOTE"
[ -n "$CD_WARN" ] && printf '%s' "$CD_WARN"
if [ -n "$B" ]; then
  note "backup of everything this run changed or removed: $B"
  note "restore it: $HERE/install.sh --restore $B"
else
  note "nothing changed in $C (no backup needed)"
fi
cat <<EOF
  1. Put your API keys in $C/stack.env: OPENROUTER (SVG and image edits), OPPER (photos and
     raster images) — uncomment the lines an upgrade appended; EXA (keyless works, rate-limited),
     JINA (needed for read_url/search_arxiv/PDF tools), SPIDER (crawls), HF_TOKEN and WANDB
     (optional). The image model of each tool is set there too (IMAGE_STUDIO_SVG_MODEL, _IMAGE_MODEL,
     _EDIT_MODEL; /stack-doctor checks them).
     MCP servers read that file at connect time — no reinstall needed (except the first time you add
     WANDB_API_KEY: rerun ./install.sh $ORIG_ARGS). Open a new terminal so CLI tools see them too.
  2. Start: claude        (main thread = BlackCat; the status line shows context vs the auto-compact
     window, 629K of the models' 1M). Claude Desktop's Code tab, Conductor, VS Code and Zed load the same
     setup (README → Apps). A plain session without BlackCat: claude --agent claude.
     Inside: /stack-doctor   (health check)   /stack-tree   (agents and their commands)
     /mcp   (server status; no sign-in needed with keys)
     Once, in that first session: /effort medium — BlackCat runs at the session's level (saved
     for Sonnet 5.5); an agent file's effort applies only to subagents.
     Hardest problems at ultracode, as a session of their own: claude-ninja
     (dispatched by BlackCat they run at max: ultracode exists only on a main thread).
EOF
cat <<EOF
  3. macOS computer use (designer, motion-designer, doc-specialist, verifier):
     /mcp → computer-use → Enable  (once per project), then grant Accessibility + Screen Recording.
  4. Browser agent with your logins: start with  claude --chrome  (or /chrome → Enabled by default).
  5. Optional: ./install.sh --with-ml (shared ML venv) · --with-lsp (language servers) · --with-adobe
     · --with-extra-plugins (skill-creator, math-olympiad skills)
EOF
