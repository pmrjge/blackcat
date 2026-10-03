#!/usr/bin/env bash
# Claude Code multi-agent stack — installer for macOS (Apple Silicon first).
#   ./install.sh                 core install
#   ./install.sh --with-ml       also create the ML venv ($C/venvs/ml: PyTorch, Transformers, PEFT,
#                                 scikit-learn/XGBoost/LightGBM, MLX + mlx-lm on Apple Silicon; several GB)
#   ./install.sh --with-lsp      also install missing language servers (pyright, typescript-language-server,
#                                 rust-analyzer; HLS, LanguageServer.jl, Metals, kotlin-lsp when ghcup,
#                                 julia, cs, kotlin are present) before enabling the code-intelligence plugins
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
#   ./install.sh --no-prune      keep what isn't part of the stack and your edits to stack files
#                                 (default: they are backed up, then removed or replaced)
#   ./install.sh --force         with --no-prune: still replace stack files you edited; with
#                                 --restore: also put back saved symlinks that point outside the
#                                 config dir (it does not write through symlinked dirs)
#   ./install.sh --write-through-links  a symlinked agents/, skills/, ... dir (a dotfiles checkout)
#                                 stops the run unless you give this: it then writes the stack's
#                                 files through the link(s); nothing there is ever removed
#   ./install.sh --restore [DIR] put the config dir back as it was before an install (DIR: a backup;
#                                 default: the latest), then exit
#   ./install.sh --print-managed-settings  print an optional managed-settings.json that pins the
#                                 stack's guards against edits (you install it; see CONFIG.md)
#   ./install.sh --mcp-plan      print the MCP server add/migrate/replace/keep plan and make no changes
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
# Default pruning: the installed agents/ and skills/ hold exactly the stack's files (your own and
# edited ones are removed or replaced), and stack config the stack no longer ships (hooks, rules,
# magg catalog entries, MCP entries it registered, duplicate hook wiring) goes. Everything changed
# or removed is saved first into one backup outside the config dir,
# ${XDG_STATE_HOME:-~/.local/state}/claude-agent-stack-backups/<timestamp>-*/ (0700; agents can't
# read it), and the run prints the list and the restore command. A run that changes nothing makes
# no backup. Never touched: credentials, ~/.claude.json (MCP changes go through `claude mcp`),
# the claude.ai-synced skills, plugins' own files, projects and sessions.
# Step 2 installs what is missing (lib/devtools.sh, CONFIG.md §7 "Prerequisites and toolchains"):
# Homebrew, one brew batch per type, the upstream version managers, the dev tools; one line per
# tool, a present one never touched. Groups: STACK_INSTALL_<GROUP>=0 skips one (DEPS DEVTOOLS UV
# NODE RUST HASKELL JULIA SCALA JAVA LATEX CXX GO, all on), =1 adds POSTGRES or MONGODB (off).
# CLAUDE_CONFIG_DIR overrides the install target (default ~/.claude); --config-dir overrides both.
# STACK_CLAUDE_JSON overrides which JSON file the MCP plan reads (default: $C/.claude.json when
# CLAUDE_CONFIG_DIR is set, or --config-dir names another folder — Claude Code then uses only that
# file —, else ~/.claude.json). The installer never writes that file itself: every MCP change goes
# through `claude mcp`, run with CLAUDE_CONFIG_DIR pointing at the target.
# Runs from any clone location (also through a symlink to this script), with bash 3.2 or later.
set -euo pipefail

WITH_ADOBE=0; WITH_ML=0; WITH_LSP=0; WITH_EXTRA_PLUGINS=0; SKIP_MCP=0; SKIP_PLUGINS=0; REPLACE_MCP=0; FORCE=0; WRITE_LINKS=0; NO_DEPS=0
NO_PROFILE=0; MCP_PLAN=0; DEDUPE_PLUGINS=1; DRY_RUN=0; PRUNE=1; RESTORE=""; PRINT_MANAGED=0; ASSUME_YES=0; ORIG_ARGS="$*"
NO_PROMPT=0; CONFIG_DIR_SET=0; CONFIG_DIR_ARG=""
i=0; argv=("$@")
while [ "$i" -lt "${#argv[@]}" ]; do
  a="${argv[$i]}"
  case "$a" in
    --with-adobe) WITH_ADOBE=1 ;;
    --with-ml) WITH_ML=1 ;;
    --with-lsp) WITH_LSP=1 ;;
    --with-extra-plugins) WITH_EXTRA_PLUGINS=1 ;;
    --no-mcp) SKIP_MCP=1 ;;
    --no-plugins) SKIP_PLUGINS=1 ;;
    --dedupe-plugins) DEDUPE_PLUGINS=1 ;;          # the default now; accepted for old scripts
    --keep-plugin-duplicates) DEDUPE_PLUGINS=0 ;;
    --replace-mcp) REPLACE_MCP=1 ;;
    --force) FORCE=1 ;;
    --write-through-links) WRITE_LINKS=1 ;;
    --no-deps) NO_DEPS=1 ;;
    --no-profile) NO_PROFILE=1 ;;
    --mcp-plan) MCP_PLAN=1 ;;
    --dry-run) DRY_RUN=1 ;;
    --no-prune) PRUNE=0 ;;
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
  GIT_TERMINAL_PROMPT=0 git -c core.hooksPath=/dev/null "$@" </dev/null
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
  done <<EOF
$out
EOF
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
# --mcp-plan, --print-managed-settings) and had to create the root removes it again.
ROOT_STATE="$(python3 "$STATE_PY" private-root "$BACKUP_ROOT")" || exit 1
find "$BACKUP_ROOT" -maxdepth 1 -name '.work.*' -type d -mtime +1 -exec rm -rf {} + 2>/dev/null || true
WORK="$(mktemp -d "$BACKUP_ROOT/.work.XXXXXX")"
cleanup(){
  rm -rf "$WORK"
  if [ "$ROOT_STATE" = created ] && [ "$DRY_RUN$PRINT_MANAGED$MCP_PLAN" != 000 ]; then rmdir "$BACKUP_ROOT" 2>/dev/null || true; fi
}
trap cleanup EXIT
# --dry-run: nothing outside $WORK is written; commands that would change something are printed.
would(){ printf '  would: %s\n' "$*"; }
say(){ printf '\n\033[1m%s\033[0m\n' "$*"; }
note(){ printf '  %s\n' "$*"; }
have(){ command -v "$1" >/dev/null 2>&1; }
# rustup installs a rust-analyzer proxy even without the component: run it, don't just find it
lsp_works(){ case "$1" in
  rust-analyzer) rust-analyzer --version >/dev/null 2>&1 ;;
  # LanguageServer.jl is a package, not a binary: loadable from the @claude-lsp environment (or the
  # default one, also on that load path)
  julia-languageserver) have julia && julia --startup-file=no --history-file=no --project=@claude-lsp \
    -e 'exit(Base.find_package("LanguageServer") === nothing ? 1 : 0)' >/dev/null 2>&1 ;;
  *) have "$1" ;; esac; }
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
          [ "$kind" = mcp_replaced ] && claude mcp remove -s user "$name" >/dev/null 2>&1 </dev/null
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

# The interpreter every hook, the status line and the MCP header helper run with: absolute, stable
# across upgrades and never a version-manager shim (a shim that fails in some project makes every
# hook fail to start, which Claude Code treats as a non-blocking error: every gate silently open).
# (Output goes through a temp file: bash 3.2, macOS's /bin/bash, mis-parses heredocs inside $(...).)
if [ -z "${STACK_PYTHON:-}" ]; then
  pyfile="$(mktemp)"
  python3 - >"$pyfile" <<'PY'
import os, re, shutil, subprocess, sys


def works(py):
    try:
        return subprocess.run([py, "-c", "import fcntl, json, sys; sys.exit(sys.version_info < (3, 8))"],
                              stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                              stderr=subprocess.DEVNULL, timeout=30).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def clt_installed():
    try:
        return subprocess.run(["/usr/bin/xcode-select", "-p"], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                              stderr=subprocess.DEVNULL, timeout=30).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


cands = []
# macOS: /usr/bin/python3 is real only with the Command Line Tools (else a stub that opens an installer)
if sys.platform != "darwin" or clt_installed():
    cands.append("/usr/bin/python3")
cands += ["/opt/homebrew/bin/python3", "/usr/local/bin/python3"]
found = shutil.which("python3")
if found and not re.search(r"/(shims|\.pyenv|\.asdf|mise|\.rye)/", found):
    cands.append(found)
cands.append(os.path.realpath(sys.executable))
print(next((c for c in cands if os.path.isfile(c) and os.access(c, os.X_OK) and works(c)), "python3"))
PY
  STACK_PYTHON="$(cat "$pyfile")"; rm -f "$pyfile"
fi
export STACK_PYTHON
note "hook interpreter: $STACK_PYTHON"

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
  [ -f "$envfile" ] || envfile="$HERE/lib/stack.env.example"
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
  planfile="$(mktemp)"
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
# URLs earlier stack versions registered: an entry still on one of these follows the stack's URL;
# any other URL on the same host is the user's own choice and is kept.
OLD_URLS = {"exa": {"https://mcp.exa.ai/mcp"}}
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
        elif cur.get("url") != desired["url"] and cur.get("url") in OLD_URLS.get(name, ()):
            action, why = "migrate", "stack URL changed (%s)" % url_display(desired["url"])
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
# install shipped), and edits not committed yet: the whole shipped tree (agents and their MCP servers
# and hooks, skills, rules, hooks, settings, bin, mcp, magg's catalog, the LSP marketplace), the
# installer and its library, stack.env.example, the pinned requirements, the two tests/derive_*.py
# scripts copied into hooks/ (not lib/assets/: README images, never installed). Read them before
# applying. On a terminal the run asks here, before step 2 changes anything (the venvs sync from requirements/) (--yes: don't).
SUPPLY_PATHS="dot-claude install.sh lib/install_state.py lib/devtools.sh lib/stack.env.example requirements tests/derive_sched_model.py tests/derive_thresholds.py"
SUPPLY_CHANGED=0
prev_commit="$(python3 -c 'import json, re, sys
try:
    v = json.load(open(sys.argv[1])).get("commit") or ""
except Exception:
    v = ""
print(v if re.fullmatch(r"[0-9a-f]{7,64}", str(v)) else "")' "$C/.stack-manifest.json" 2>/dev/null || true)"
if git -C "$HERE" rev-parse -q --verify HEAD >/dev/null 2>&1; then
  # shellcheck disable=SC2086
  dirty="$(git -C "$HERE" status --porcelain -- $SUPPLY_PATHS 2>/dev/null || true)"
  if [ -n "$dirty" ]; then
    SUPPLY_CHANGED=1
    note "! uncommitted changes in the stack repo's shipped files or installer — this run installs them:"
    printf '%s\n' "$dirty" | head -n 40 | sed 's/^/      /'
    [ "$(printf '%s\n' "$dirty" | wc -l)" -gt 40 ] && note "  ... and more: git -C $HERE status -- $SUPPLY_PATHS"
  fi
  if [ -n "$prev_commit" ] && [ "$prev_commit" != "$STACK_COMMIT_FULL" ]; then
    # shellcheck disable=SC2086
    if supply="$(git -C "$HERE" diff --stat "$prev_commit" HEAD -- $SUPPLY_PATHS 2>/dev/null)"; then
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
        note "review: git -C $HERE diff ${prev_commit:0:12} HEAD -- $SUPPLY_PATHS"
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

say "2/11 Tools: prerequisites, dev tools, magg, huetension, serial-mcp, science and tools venvs"
# Supply chain (C7): every download is pinned to a version and, where the project publishes one, a
# checksum; the Python venvs install from hash-locked lockfiles (requirements/, 7-day cooldown).
# Prerequisites and toolchains are lib/devtools.sh's (pins, routes and groups there; CONFIG.md §7):
# Homebrew, one brew batch for every missing formula and one for every missing cask, the upstream
# managers (uv, nvm, rustup, ghcup, juliaup, coursier), then gitleaks, pre-commit, Gradle and
# Playwright's Chromium. One line per tool, a present tool never touched, a failed optional install
# only reported; a required one (uv, node) still missing stops the run here.
#   --no-deps: no installs at all (missing tools are listed);
#   STACK_INSTALL_<GROUP>=0 skips a group (DEPS DEVTOOLS UV NODE RUST HASKELL JULIA SCALA JAVA LATEX
#   CXX GO), STACK_INSTALL_POSTGRES=1 / STACK_INSTALL_MONGODB=1 add those.
MAGG_VERSION=1.2.1                         # 1.3.0 (2026-09-26) is inside the 7-day cooldown
MAGG_EXCLUDE_NEWER=2026-09-22T00:00:00Z    # dependency cooldown for magg's own requirements
HUETENSION_VERSION=0.3.0
if [ "$NO_DEPS" = 1 ]; then DT_MODE=report; elif [ "$DRY_RUN" = 1 ]; then DT_MODE=dry-run; else DT_MODE=install; fi
note "prerequisites and toolchains (lib/devtools.sh):"
dt_rc=0
DEVTOOLS_MODE="$DT_MODE" DEVTOOLS_NO_PROFILE="$NO_PROFILE" bash "$HERE/lib/devtools.sh" all || dt_rc=$?
# a required tool still missing: devtools.sh listed each with its command
[ "$dt_rc" = 3 ] && exit 1
[ "$dt_rc" = 0 ] || note "! lib/devtools.sh exited $dt_rc (see above); the install goes on"
# what devtools.sh installed must be found below, also before your shell profile has its PATH line:
# Homebrew's bin dir, nvm's node 24, rustup's and ghcup's bins; appended, so your own PATH order wins
for b in /opt/homebrew/bin /usr/local/bin "$HOME/.cargo/bin" "$HOME/.ghcup/bin"; do
  { [ -x "$b/brew" ] || [ -x "$b/cargo" ] || [ -x "$b/ghcup" ]; } || continue
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
  local t; t="$(mktemp -d)"
  if curl -fsSL -o "$t/a.tgz" "$url" && sha256_ok "$sum" "$t/a.tgz" && tar -xzf "$t/a.tgz" -C "$dir" "$@"; then
    rm -rf "$t"; return 0
  fi
  rm -rf "$t"; return 1
}
# tools venv: what the stack's own scripts, MCP servers and tests import (hooks stay stdlib on
# /usr/bin/python3). A future extra (e.g. a Bayesian stack) is its own lock, requirements/tools-<extra>.in
# starting with "-r tools.in", installed by pointing TOOLS_REQS at its .txt (requirements/README.md).
TOOLS_REQS="$HERE/requirements/tools.txt"
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
print(m.group(1) if m else "")' "$HERE/dot-claude/magg/config.json" 2>/dev/null || true)"
SERIAL_MCP_BIN="$HOME/.cargo/bin/serial-mcp"
SERIAL_MCP_CMD="cargo install serial-mcp@$SERIAL_MCP_VERSION --locked --root $HOME/.cargo"
cargo_bin(){ command -v cargo 2>/dev/null || { [ -x "$HOME/.cargo/bin/cargo" ] && echo "$HOME/.cargo/bin/cargo"; } || true; }
# the pinned serial-mcp is in place (a binary cargo has no record of is yours, and stays)
serial_mcp_current(){
  [ -x "$SERIAL_MCP_BIN" ] || return 1
  local rec; rec="$(grep -o '"serial-mcp [^ ]*' "$HOME/.cargo/.crates2.json" 2>/dev/null | head -n 1 | cut -d' ' -f2 || true)"
  [ -z "$rec" ] || [ "$rec" = "$SERIAL_MCP_VERSION" ]
}
serial_mcp_step(){  # serial_mcp_step install|plan (plan: --dry-run, lists the build)
  if [ -z "$SERIAL_MCP_VERSION" ]; then
    note "! serial-mcp: no pinned version in the serial entry of $HERE/dot-claude/magg/config.json — skipped"; return 0
  fi
  if serial_mcp_current; then [ "$1" = plan ] || note "serial-mcp present ($SERIAL_MCP_BIN)"; return 0; fi
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
  have magg || miss magg "uv tool install --exclude-newer $MAGG_EXCLUDE_NEWER magg==$MAGG_VERSION"
  have huetension || miss huetension "install huetension v$HUETENSION_VERSION (checksummed release tarball; designer works without it)"
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
  # magg pinned; its dependencies resolved as of the cooldown date. --force replaces another version.
  if [ "$(magg --version 2>/dev/null | awk '{print $2}')" != "$MAGG_VERSION" ]; then
    uv tool install --quiet --force --exclude-newer "$MAGG_EXCLUDE_NEWER" "magg==$MAGG_VERSION" \
      || note "! magg $MAGG_VERSION install failed — uv tool install --exclude-newer $MAGG_EXCLUDE_NEWER magg==$MAGG_VERSION"
  fi
  have magg && note "magg $(magg --version 2>/dev/null | awk '{print $2}')"
  if ! have huetension; then
    mkdir -p "$HOME/.local/bin"
    set -- $(huetension_target)
    d="$(mktemp -d)"
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
  fi
  have huetension && note "huetension ok" || note "! huetension missing — designer works without color MCP; see README"
  serial_mcp_step install
  if venv_sync sci "$HERE/requirements/sci.txt" --only-binary :all:; then note "science venv: $C/venvs/sci (hash-locked)"
  else note "! science venv install failed — uv pip install --python $C/venvs/sci/bin/python --require-hashes --only-binary :all: -r $HERE/requirements/sci.txt"; fi
  if venv_sync tools "$TOOLS_REQS" --only-binary :all:; then
    note "tools venv: $C/venvs/tools ($("$C/venvs/tools/bin/python" -c "$TOOLS_IMPORTS"'; print("imports ok")' 2>/dev/null || echo '! imports failed'))"
  else note "! tools venv install failed — uv pip install --python $C/venvs/tools/bin/python --require-hashes --only-binary :all: -r $TOOLS_REQS"; fi
fi

say "3/11 ML venv (--with-ml)"
if [ "$WITH_ML" = 0 ]; then
  if [ -x "$C/venvs/ml/bin/python" ]; then note "ML venv present: $C/venvs/ml (rerun with --with-ml to update)"; else note "skipped — ML agents use the project's environment or the science venv; add --with-ml for a shared ML venv"; fi
elif [ "$DRY_RUN" = 1 ]; then
  would "sync $C/venvs/ml to requirements/ml.txt (--require-hashes)"
elif [ "$NO_DEPS" = 1 ] || ! have uv; then
  note "! --with-ml needs uv and is skipped under --no-deps"
else
  # ml.txt holds one sdist-only package (rouge-score, hashed), so no --only-binary here
  if venv_sync ml "$HERE/requirements/ml.txt"; then
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
  if npx -y premiere-pro-mcp@1.18.2 --install-cep; then note "+ Premiere Pro CEP connector installed (restart Premiere; Window > Extensions > MCP for Adobe Premiere Pro)"
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
note "staged in $S (prune: $([ "$PRUNE" = 1 ] && echo on || echo 'off (--no-prune)'))"
# backups earlier versions kept inside $C (with copies of stack.env) move out on every run
legacy_b="$(python3 "$STATE_PY" legacy-backups "$C" "$BACKUP_ROOT" list)"

say "6/11 Render (agents, rules, skills, scripts, settings.json)"
mkdir -p "$S"/{agents,skills,hooks,mcp,magg,bin,rules}
# The stack's scripts replace whatever is staged there — a symlink too (removed first: a copy onto
# it would write through the link, out of the staging dir; the backup keeps the link).
stage_script(){ rm -rf "$S/$2" && cp "$SRC/$2" "$S/$2" && chmod "$1" "$S/$2"; }
stage_script 755 hooks/agent_guard.py
# /override-agent's built-in effort per (agent, model): read by agent_guard.py, beside it
stage_script 644 hooks/agent_effort.json
# per-call caps for exa/jina/spider and Spider's anti-bot defaults (PreToolUse ^mcp__(exa|jina|spider)__)
stage_script 755 hooks/web_caps.py
# the token gate on reads of build output, dependencies, data, media and binaries (PreToolUse Read|Grep|Glob|Bash)
stage_script 755 hooks/read_gate.py
# the hand-back protocol's parser and checks (STACK_REPORT_FORMAT): imported by agent_guard.py, beside it
stage_script 644 hooks/stack_report.py
# the usage collector (SubagentStart/SessionEnd hooks; agent_guard.py starts it at SessionStart), the
# scheduler advisor, its shipped cost model and the refit (stack_sched_refresh.py imports fit() from the
# two tests/ scripts beside it), and the learned limits (stack_limits.py: per-session snapshots the
# guard reads; its seed: the floors, ceilings and starting values)
for f in stack_usage.py stack_sched.py stack_limits.py stack_fanout.py; do stage_script 755 "hooks/$f"; done
for f in stack_sched_refresh.py sched_model.json stack_limits_seed.json; do stage_script 644 "hooks/$f"; done
for f in derive_sched_model.py derive_thresholds.py; do
  rm -rf "$S/hooks/$f" && cp "$HERE/tests/$f" "$S/hooks/$f" && chmod 644 "$S/hooks/$f"
done
for f in statusline.py doctor.sh with-stack-env mcp-headers magg-private claude-ultracode stack_sdk.py stack-update-tools stack-budget stack-tree; do stage_script 755 "bin/$f"; done
for f in image_studio_mcp.py libdocs_mcp.py neural_memory_mcp.py; do stage_script 644 "mcp/$f"; done
stage_script 644 magg/k8s-mcp.toml    # the magg catalog's kubernetes entry reads it (--config)
# The stack's local LSP marketplace (step 10 registers it): replaced as a whole.
if [ "$SKIP_PLUGINS" = 0 ] && [ -d "$SRC/stack-plugins" ]; then
  rm -rf "$S/stack-plugins" && cp -R "$SRC/stack-plugins" "$S/stack-plugins"
fi
[ -f "$S/stack.env" ] || cp "$HERE/lib/stack.env.example" "$S/stack.env"
chmod 600 "$S/stack.env"
# Variables stack.env.example gained since your stack.env was created: appended with their comment
# lines, commented out — except the image models, appended set to image-studio's own defaults (the
# same models either way, now named where you change them), and the Claude model variables, appended
# set to the stack's IDs (step 7 copies them into settings.json's env). A key already in your file,
# even commented out, is never added again, and a value you wrote is never changed. The
# image lines earlier versions of stack.env.example put in your file are brought up to date: stale
# comments get today's wording, and settings nothing reads any more go while they still hold the
# stack's own default (Lumenfall's empty key, the old Opper model and folder); the previous file is
# kept in the backup folder.
python3 - "$HERE/lib/stack.env.example" "$S/stack.env" <<'PY'
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
    "# Default image model and output folder (optional)": None,
    "OPPER_IMAGE_MODEL=bytedance:ap/seedream-5-pro": None,
    "OPPER_IMAGE_OUT_DIR=$HOME/Pictures/opper": None,
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
    "# Lumenfall — generate_svg: Recraft V4.1 Pro SVG for logos, icons, illustrations and other graphics": None,
    "# (about $0.30 an image). https://lumenfall.ai/app": None,
    "LUMENFALL_API_KEY=": None,
    "#LUMENFALL_API_KEY=": None,
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


def value(raw):
    v = raw.strip()
    if v[:1] in ("'", '"') and v[0] in v[1:]:
        return v[1:v.index(v[0], 1)]
    return re.split(r"\s+#", v, maxsplit=1)[0].strip()


set_now = {m.group(1): value(m.group(2)) for m in (re.match(r"^\s*(?:export\s+)?([A-Z][A-Z0-9_]*)=(.*)$", l)
                                                   for l in lines) if m}
for old, now in (("LUMENFALL_API_KEY", "generate_svg runs on OpenRouter now, with OPENROUTER_API_KEY"),
                 ("OPPER_IMAGE_MODEL", "generate_image's model is IMAGE_STUDIO_IMAGE_MODEL"),
                 ("OPPER_IMAGE_OUT_DIR", "the output folder is IMAGE_STUDIO_OUT_DIR")):
    if set_now.get(old):
        print("  note: stack.env sets %s, which image-studio doesn't read (%s): delete that line" % (old, now))
PY

# The previous profile line ({ set -a; . stack.env; set +a; }) exported EVERY variable of stack.env;
# the new one (step 11) exports only STACK_EXPORT: variables of your own stay exported through it.
# Done on the staged stack.env, so the plan lists it and the backup keeps the previous file.
if [ "$NO_PROFILE" = 0 ] && grep -qE 'set -a.*stack\.env.*# claude-agent-stack[[:space:]]*$' "$HOME/.zshrc" "$HOME/.bashrc" 2>/dev/null; then
  python3 - "$HERE/lib/stack.env.example" "$S/stack.env" "$SRC/bin/mcp-headers" "$SRC/bin/with-stack-env" <<'PY' || true
import os, re, runpy, sys
from pathlib import Path
example, target, parser, wse = sys.argv[1:5]
mh = runpy.run_path(parser, run_name="mcp_headers")
VAR = re.compile(r"^\s*(?:#\s?)?(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)=")
stack_keys = {m.group(1) for m in map(VAR.match, open(example, encoding="utf-8").read().splitlines()) if m}
text = open(target, encoding="utf-8", errors="surrogateescape").read()
vals = mh["read_env_file"](Path(target))
own = {k: v for k, v in vals.items() if v and k not in stack_keys and not k.startswith(("LUMENFALL_", "OPPER_", "OPENROUTER_", "IMAGE_STUDIO_", "LIBDOCS_"))}
mine = sorted(k for k, v in own.items() if "$" not in v)
expanding = sorted(k for k, v in own.items() if "$" in v)
if expanding:
    print("  note: %s use $VAR expansion, which the profile line doesn't do: set them in your shell rc file"
          % ", ".join(expanding))
if mine and not re.search(r"(?m)^\s*(?:export\s+)?STACK_EXPORT=", text):
    default = re.search(r'(?m)^DEFAULT_EXPORT="([^"]*)"', open(wse, encoding="utf-8").read()).group(1)
    block = ("\n# added by install.sh: your previous profile line exported every variable in this file;\n"
             "# these of your own stay exported (the stack's API keys no longer are)\n"
             'STACK_EXPORT="%s %s"\n' % (default, " ".join(mine)))
    fd = os.open(target + ".tmp", os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8", errors="surrogateescape") as f:
        f.write(text + ("" if text.endswith("\n") or not text else "\n") + block)
    os.replace(target + ".tmp", target)
    print("  stack.env: STACK_EXPORT keeps exporting your own variables: " + ", ".join(mine))
gone = [k for k in ("OPPER_API_KEY", "OPENROUTER_API_KEY", "EXA_API_KEY", "JINA_API_KEY", "SPIDER_API_KEY")
        if vals.get(k)]
if gone:
    print("  note: no longer exported to your shells: %s (the MCP servers read stack.env themselves)" % ", ".join(gone))
PY
fi

# Researcher's spider mcpServers block is only rewritten (to reuse an already-configured
# 'spider' server) when MCP registration is active and the user already has one.
SPIDER_REWRITE=0
if [ "$SKIP_MCP" = 0 ] && [ "$MCP_PLAN" = 0 ] && claude mcp get spider >/dev/null 2>&1 </dev/null; then SPIDER_REWRITE=1; fi

RENDERED_SETTINGS="$WORK/settings.rendered.json"

FORCE="$FORCE" SPIDER_REWRITE="$SPIDER_REWRITE" RENDERED_SETTINGS="$RENDERED_SETTINGS" DEST="$S" PRUNE="$PRUNE" \
REPORT="$REPORT" STACK_BACKUPS="$BACKUP_ROOT" STACK_CACHE="$STACK_CACHE" STACK_STATE="$STACK_STATE" STACK_COMMIT_FULL="$STACK_COMMIT_FULL" python3 - "$SRC" "$C" "$HERE" <<'PY'
import difflib, glob, hashlib, json, os, re, shutil, subprocess, sys

# C is where the files will live (every rendered path names it); DEST is the staged copy of C
# they are written to (install_state.py compares it with C afterwards and applies the difference).
SRC, C, REPO = sys.argv[1], sys.argv[2], sys.argv[3]
DEST = os.environ["DEST"]
PRUNE = os.environ.get("PRUNE") == "1"
FORCE = os.environ.get("FORCE") == "1"
report = {"removed": {}, "replaced": {}, "config_removed": [], "config_replaced": [], "notes": []}


def save_report():
    with open(os.environ["REPORT"], "w") as rf:
        json.dump(report, rf, indent=2, sort_keys=True)


sys.path.insert(0, os.path.join(REPO, "lib"))
from install_state import SCOPE_DIRS, in_scope, within  # noqa: E402  (the backups' scope rule)

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


def wopen(path):
    """open(path, "w") for a file in DEST that never writes through a staged symlink."""
    if os.path.islink(path):
        os.unlink(path)
    return open(path, "w", encoding="utf-8")


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


def frontmatter_sets(text):
    """(tools set, mcpServers-name set) parsed loosely from an agent's frontmatter."""
    tools = set()
    m = re.search(r"(?m)^tools:\s*(.*)$", text)
    if m:
        tools = {t.strip() for t in m.group(1).split(",") if t.strip()}
    mcps = set(re.findall(r"(?m)^\s*-\s*([A-Za-z0-9_-]+):\s*$", text.split("mcpServers:", 1)[-1])) \
        if "mcpServers:" in text else set()
    return tools, mcps


def similar(installed_text, rendered_text):
    # old stack versions share >= 59% of their lines with the current render; user files <= 18%
    return difflib.SequenceMatcher(None, installed_text.splitlines(), rendered_text.splitlines(),
                                   autojunk=False).ratio() >= 0.4


def is_legacy_safe_overwrite(installed_text, rendered_text):
    """Heuristic for files installed before the manifest existed: safe to overwrite
    unless the installed copy has tools/mcpServers not present in the new render
    (a sign of a manual mcp-broker edit worth keeping), or is not an older copy of this
    stack's file at all (a same-named agent of the user's own: few shared lines)."""
    it, im = frontmatter_sets(installed_text)
    rt, rm = frontmatter_sets(rendered_text)
    if not (it.issubset(rt) and im.issubset(rm)):
        return False
    return similar(installed_text, rendered_text)


def legacy_renders(rel):
    """Renders of `rel` ("CLAUDE.md", "skills/<name>/SKILL.md") exactly as earlier stack versions
    shipped them (the repo's legacy/<version>/<rel>). The repo keeps no legacy/ today (the last
    release's templates are in git history): then this is empty and template_copy finds nothing,
    so an untracked file is recognised as the stack's only when it is a copy of the current render."""
    out = []
    for p in sorted(glob.glob(os.path.join(REPO, "legacy", "*", rel))):
        try:
            out.append(render(open(p, encoding="utf-8").read()))
        except (OSError, UnicodeDecodeError):
            pass
    return out


def only_stack_lines(installed_text, renders):
    """True when every non-blank line of a file is a line some stack version shipped: it holds
    nothing of the user's own. A similarity ratio can't tell "the stack's old copy" from "the
    stack's copy plus my notes"."""
    known = {ln.strip() for r in renders for ln in r.splitlines() if ln.strip()}
    return all(ln.strip() in known for ln in installed_text.splitlines() if ln.strip())


def template_copy(installed_text, rel):
    """The file is a legacy/<version>/<rel> template with its placeholders filled in any way (another
    uv or npx path, another config dir than today's render would use): the stack's own, unedited."""
    for p in sorted(glob.glob(os.path.join(REPO, "legacy", "*", rel))):
        try:
            parts = re.split(r"(__[A-Z0-9_]+__)", open(p, encoding="utf-8").read())
        except (OSError, UnicodeDecodeError):
            continue
        rx = "".join(r"[^\n]*" if k % 2 else re.escape(part) for k, part in enumerate(parts))
        if re.fullmatch(rx, installed_text):
            return True
    return False


def pure_stack_copy(installed_text, renders):
    """An untracked file that is exactly some version the stack shipped (line for line, blank lines
    and order aside): nothing added, nothing removed. Replacing it (after the backup) loses nothing;
    a copy the user trimmed is a customization and is kept."""
    have = {ln.strip() for ln in installed_text.splitlines() if ln.strip()}
    return only_stack_lines(installed_text, renders) and any(
        {ln.strip() for ln in r.splitlines() if ln.strip()} <= have for r in renders)


manifest_path = os.path.join(DEST, ".stack-manifest.json")
try:
    manifest = json.load(open(manifest_path))
except (OSError, ValueError):
    manifest = {}
# Every path the manifest names is checked before anything uses it (N-MANIFEST): a name with "..",
# an absolute path or anything outside the stack's part of the config dir stops the install.
if not isinstance(manifest, dict):
    manifest = {}
_bad = []
for _key in ("files", "offered"):
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
offered = manifest.setdefault("offered", {})
manifest["repo"] = REPO     # where the stack's source lives (claude-code-engineer, mcp-broker)
manifest["commit"] = os.environ.get("STACK_COMMIT_FULL") or "unknown"   # what this install ships


def save_manifest():
    with open(manifest_path + ".tmp", "w") as mf:
        json.dump(manifest, mf, indent=2, sort_keys=True)
    os.replace(manifest_path + ".tmp", manifest_path)


# --- magg catalog: add the servers the shipped catalog has and yours doesn't; an entry of a server
# the stack ships that differs from the stack's is replaced (--no-prune: kept while you edited it; an
# unedited earlier version is updated either way); a server an earlier stack version shipped and this
# one doesn't goes (--no-prune: stays). Servers of your own (mcp-broker adds them) are never touched.
# Catalog servers are reset to disabled: mcp-broker enables one for a task and disables it after. ---
def fingerprint(entry):
    """Entry minus the state magg itself changes (enabled, kits)."""
    core = {k: v for k, v in entry.items() if k not in ("enabled", "kits")}
    return hashlib.sha256(json.dumps(core, sort_keys=True).encode()).hexdigest()[:16]


# fingerprints of entries earlier stack versions shipped (before the manifest recorded them)
LEGACY_MAGG = {"docling": {"84d001fc6386deb0"}, "playwright": {"604f97c45597d8e6"},
               "lean": {"ef061039770a7579"}, "docspace": {"d93d837abbebe4ed"},
               "duckdb": {"529df3589fc6a3f6"}, "arxiv": {"484fdabd5d7ac75e"},
               "jupyter": {"4df0d303a3d2f0d2"}, "mlflow": {"4ca92ebdcfb8dd81"}}
magg_dst = os.path.join(DEST, "magg", "config.json")
shipped_magg = json.loads(render(open(os.path.join(SRC, "magg", "config.json")).read(), json_escape=True))
prev_magg = manifest.get("magg_shipped") or {}
try:
    cur_magg = json.load(open(magg_dst))
    magg_ok = isinstance(cur_magg, dict)
except FileNotFoundError:
    cur_magg, magg_ok = {"servers": {}}, True
except ValueError as exc:
    if PRUNE:
        print("  ! magg/config.json is not valid JSON (%s) — replaced by the stack's catalog" % exc)
        report["replaced"]["magg/config.json"] = "not valid JSON"
        cur_magg, magg_ok = {"servers": {}}, True
    else:
        print("  ! %s is not valid JSON (%s) — left unchanged; the catalog update was skipped" % (magg_dst, exc))
        magg_ok = False
if magg_ok:
    servers = cur_magg.setdefault("servers", {})
    added, updated, kept, disabled, replaced, gone = [], [], [], [], [], []
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
        elif fingerprint(mine) in LEGACY_MAGG.get(k, set()) | ({prev_magg[k]} if k in prev_magg else set()):
            servers[k] = dict(entry, enabled=mine.get("enabled", True))
            updated.append(k)
        elif PRUNE:
            servers[k] = dict(entry)
            replaced.append(k)
            report["config_replaced"].append(["magg catalog: " + k, "differed from the stack's entry"])
        else:
            kept.append(k)
            continue
        if servers[k].get("enabled", True):          # magg leaves "enabled" out when true
            servers[k]["enabled"] = False
            disabled.append(k)
    for k in sorted(set(prev_magg) - set(shipped_magg.get("servers", {}))):
        if k in servers:
            if PRUNE:
                servers.pop(k)
                gone.append(k)
                report["config_removed"].append(["magg catalog: " + k, "no longer shipped by the stack"])
            else:
                report["notes"].append("magg catalog: %s is no longer shipped (kept: --no-prune)" % k)
    if added or updated or disabled or replaced or gone or not os.path.exists(magg_dst):
        os.makedirs(os.path.dirname(magg_dst), exist_ok=True)
        with open(magg_dst + ".tmp", "w") as f:
            json.dump(cur_magg, f, indent=2)
            f.write("\n")
        os.replace(magg_dst + ".tmp", magg_dst)
    manifest["magg_shipped"] = {k: fingerprint(e) for k, e in shipped_magg.get("servers", {}).items()}
    parts = [("added " + ", ".join(added)) if added else "", ("updated " + ", ".join(updated)) if updated else "",
             ("disabled again " + ", ".join(disabled)) if disabled else "",
             ("replaced " + ", ".join(replaced)) if replaced else "", ("removed " + ", ".join(gone)) if gone else "",
             ("kept your edited " + ", ".join(kept)) if kept else ""]
    print("  magg catalog: %s" % ("; ".join(x for x in parts if x) or "up to date"))

# --- copy types: the only agents that may run copies of themselves get a rendered <type>-copy.md
# (own name, short description, same tools/model/maxTurns/mcpServers and body; "May spawn" = the
# base list minus the base type and every copy). The hook's POLICY lists <type>-copy in the base
# row and never lets a copy spawn its base or a copy, so one generation is a static check.
COPY_TYPES = ("researcher", "coder")


def split_top_level(s):
    parts, cur, depth = [], "", 0
    for ch in s:
        depth += (ch in "([") - (ch in ")]")
        if ch == "," and depth == 0:
            parts.append(cur.strip())
            cur = ""
        else:
            cur += ch
    return parts + ([cur.strip()] if cur.strip() else [])


def make_copy(text, base):
    """<base>.md -> <base>-copy.md (see COPY_TYPES)."""
    name = base + "-copy"
    out, n = re.subn(r"(?m)^name: %s$" % re.escape(base), "name: " + name, text, count=1)
    if n != 1:
        raise SystemExit("install.sh: agents/%s.md has no 'name: %s' line to copy" % (base, base))
    out = re.sub(r"(?m)^description: .*$", lambda m: 'description: "Copy of %s for one independent part; '
                 'spawned only by %s."' % (base, base), out, count=1)

    def may_spawn(m):
        keep = [t for t in split_top_level(m.group(1))
                if not re.match(r"(%s|[A-Za-z0-9_-]+-copy)\b(?!-)" % re.escape(base), t)]
        return "May spawn: %s." % ", ".join(keep) if keep else "Spawn nothing."
    out, n = re.subn(r"May spawn:\s*([^.]*)\.", may_spawn, out, count=1)
    if n != 1:
        raise SystemExit("install.sh: agents/%s.md has no 'May spawn:' sentence to copy" % base)
    head, sep, body = out.partition("\n---\n")
    # The base body tells its agent when to spawn copies ("sub-tasks can go to coder-copy agents");
    # a copy spawns none, so every sentence naming a <type>-copy agent goes, and a line (list item)
    # left empty goes with it.
    copy_name = re.compile(r"[A-Za-z0-9_]-copy\b")
    lines = []
    for line in body.split("\n"):
        if not copy_name.search(line):
            lines.append(line)
            continue
        m = re.match(r"(\s*(?:[-*+]|\d+[.)])\s+)?(.*)\Z", line, re.S)
        sentences = re.split(r"(?<!\be\.g\.)(?<!\bi\.e\.)(?<=[.!?])\s+", m.group(2))
        keep = [s for s in sentences if not copy_name.search(s)]
        if keep:
            lines.append((m.group(1) or "") + " ".join(keep))
    body = "\n".join(lines)
    note = ("You are a copy of %s, spawned by a %s for one independent part of its job. Do that part "
            "yourself: a copy never spawns %s or another copy. Skip any Memory lines below: what memory "
            "holds for your part is already in your brief, and you write nothing to memory yourself.\n\n"
            % (base, base, base))
    return head + sep + note + body


# --- agents/*.md + rules/claude-agent-stack.md. Pruning (the default): a file that differs from
# the render is replaced, whatever made it differ (the backup keeps it). --no-prune: manifest-guarded
# as before — a file you edited since the last install is kept and the render goes next to it as
# <name>.new (--force replaces it anyway). ---
targets = [("agents/" + os.path.basename(p), p, None) for p in sorted(glob.glob(os.path.join(SRC, "agents", "*.md")))]
targets += [("agents/%s-copy.md" % b, os.path.join(SRC, "agents", b + ".md"), b) for b in COPY_TYPES]
targets.append(("rules/claude-agent-stack.md", os.path.join(SRC, "rules", "claude-agent-stack.md"), None))
AE_BUILT = os.path.isfile(os.path.join(C, "mcp", "vendor", "after-effects-mcp", "build", "index.js"))

installed_count = 0
total_agents = sum(1 for rel, _, _ in targets if rel.startswith("agents/"))
IN_SYNC = {"installed", "unchanged", "overwritten", "overwritten (legacy)", "overwritten (--force)", "replaced"}

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


for rel, src_path, copy_of in targets:
    text = open(src_path, encoding="utf-8").read()
    if copy_of:
        text = make_copy(text, copy_of)
    rendered = render(text)
    if sys.platform != "darwin" and rel.startswith("agents/"):
        rendered = drop_servers(rendered, MACOS_ONLY_SERVERS)
    elif rel == "agents/motion-designer.md" and not AE_BUILT:
        rendered = drop_servers(rendered, ("after-effects",))    # added once --with-adobe built it
    if rel in ("agents/researcher.md", "agents/researcher-copy.md") and SPIDER_REWRITE:
        rendered = re.sub(r"mcpServers:\n  - spider:\n(?:      .*\n)+", "mcpServers:\n  - spider\n", rendered)
    if rel.startswith("agents/"):
        rendered = mcp_cache_env(rendered)
    dest = os.path.join(DEST, rel)
    shown = os.path.join(C, rel)
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
        offered.pop(rel, None)
        if os.path.lexists(dest + ".new"):
            drop(rel + ".new", "leftover render of a stack file")

    if installed_hash is None:
        write()
        action = "installed"
    elif installed_hash == rendered_hash:
        write()
        action = "unchanged"
    elif entry is not None and installed_hash == entry:
        write()
        action = "overwritten"
    elif entry is None and is_legacy_safe_overwrite(open(dest, encoding="utf-8", errors="replace").read(), rendered):
        write()
        action = "overwritten (legacy)"
    elif PRUNE:
        report["replaced"][rel] = ("edited since the last install" if entry is not None
                                   else "a same-named file that isn't the stack's")
        write()
        action = "replaced"
    elif FORCE:
        write()
        action = "overwritten (--force)"
    else:
        # --no-prune: dest was hand-edited since the last install (or a legacy file with extra
        # tools/mcpServers) — keep it, and drop the new render next to it as <name>.new.
        nd = dest + ".new"
        if offered.get(rel) == rendered_hash and not os.path.exists(nd):
            # this exact render was already offered and its .new removed after review: don't nag
            action = "kept (modified) -- this render was already offered; --force to take it"
        else:
            with wopen(nd) as f:
                f.write(rendered)
            offered[rel] = rendered_hash
            action = "kept (modified) -- new render at %s.new (diff -u %s %s.new)" % (shown, shown, shown)
    if action in IN_SYNC and rel.startswith("agents/"):
        installed_count += 1
    print("  %-34s %s" % (rel, action))

# Everything else in agents/: the stack owns that directory. Pruning removes it — agents an earlier
# stack version shipped (senior-coder is now main-coder, the main-thread router is now blackcat),
# leftover .new renders, and agents of your own or of other tools (the backup keeps them all; run
# with --no-prune to keep them). --no-prune lists them instead.
RENAMED = {"agents/senior-coder.md": "agents/main-coder.md", "agents/router.md": "agents/blackcat.md"}
shipped = {rel for rel, _, _ in targets}
stale_kept = []


def agent_reason(rel):
    if rel.endswith(".new") and rel[:-4] in shipped:
        return "leftover render of a stack file"
    if rel in RENAMED:
        return "renamed: now %s" % RENAMED[rel]
    if rel in files_entry or rel in offered:
        return "no longer shipped by the stack"
    p = os.path.join(DEST, rel)
    if rel.endswith(".md") and os.path.isfile(p):
        text = open(p, encoding="utf-8", errors="replace").read()
        if template_copy(text, rel) or pure_stack_copy(text, legacy_renders(rel)):
            return "an earlier stack version's agent"
    return "not shipped by the stack: yours or another tool's"


agents_dir = os.path.join(DEST, "agents")
for fn in sorted(os.listdir(agents_dir)):
    rel = "agents/" + fn
    if rel in shipped:
        continue
    why = agent_reason(rel)
    if PRUNE:
        drop(rel, why)
    elif why == "leftover render of a stack file":
        continue                                   # the pending .new of a kept, edited agent
    else:
        stale_kept.append((rel, why))
for rel in [r for r in list(files_entry) + list(offered) if r.startswith("agents/") and r not in shipped]:
    if PRUNE or not os.path.lexists(os.path.join(DEST, rel)):
        files_entry.pop(rel, None)
        offered.pop(rel, None)

# The global rules used to be installed as CLAUDE.md. That file is yours now: the stack's old copy
# goes while still unedited (tracked: the hash decides; untracked: only an exact old version), an
# edited one, or your own, stays. Decided once — CLAUDE.md is never looked at again. (Not under
# --no-prune: a later run decides.)
old_md = os.path.join(DEST, "CLAUDE.md")
if PRUNE and not manifest.get("claude_md_migrated"):
    rules_render = render(open(os.path.join(SRC, "rules", "claude-agent-stack.md"), encoding="utf-8").read())
    stack_versions = legacy_renders("CLAUDE.md") + [rules_render]
    if os.path.isfile(old_md):
        old_entry = files_entry.get("CLAUDE.md")
        old_text = open(old_md, encoding="utf-8", errors="replace").read()
        if sha256(old_md) == old_entry if old_entry is not None else pure_stack_copy(old_text, stack_versions):
            drop("CLAUDE.md", "the stack's old rules file: they live in rules/claude-agent-stack.md now")
        elif old_entry is not None or any(similar(old_text, r) for r in stack_versions):
            print("  %-34s kept (it has lines of your own): the stack's rules moved to rules/claude-agent-stack.md —"
                  " delete the stack's old sections from CLAUDE.md so the two versions don't conflict" % "CLAUDE.md")
    # an old render of the rules the previous installer left next to an edited CLAUDE.md
    old_new = old_md + ".new"
    if os.path.isfile(old_new):
        new_text = open(old_new, encoding="utf-8", errors="replace").read()
        if "CLAUDE.md" in offered or only_stack_lines(new_text, stack_versions):
            drop("CLAUDE.md.new", "an old render of the stack's rules")
    files_entry.pop("CLAUDE.md", None)
    offered.pop("CLAUDE.md", None)
    manifest["claude_md_migrated"] = True

# rules/: files of your own stay; rules the stack installed and no longer ships go, as do .new renders
for fn in sorted(os.listdir(os.path.join(DEST, "rules"))):
    rel = "rules/" + fn
    if rel in shipped:
        continue
    why = ("leftover render of a stack file" if rel.endswith(".new") and rel[:-4] in shipped
           else "no longer shipped by the stack" if rel in files_entry else None)
    if why is None or (not PRUNE and why.startswith("leftover")):
        continue
    if PRUNE:
        drop(rel, why)
        files_entry.pop(rel, None)
    else:
        stale_kept.append((rel, why))

save_manifest()
print("  %d/%d agents installed" % (installed_count, total_agents))
if installed_count < total_agents:
    print("  ! %d agent file(s) kept with local edits: merge the .new renders (or rerun with --force)"
          % (total_agents - installed_count))

# --- skills/: the stack owns this directory (claude.ai's synced/ aside, never staged). Pruning: every
# shipped file matches its render (an edited one is replaced), and files and skills the stack doesn't
# ship go (yours included: the backup keeps them). --no-prune: manifest-guarded — a file you edited
# since the last install, or a same-named file of your own, is kept with the render next to it as
# <file>.new; an untracked file that is an older copy of the stack's is refreshed; nothing goes. ---
def install_tracked(rel, dest, rendered):
    """None when the file is (now) in sync; "refreshed" when an untracked copy made only of lines
    some stack version shipped was replaced; "replaced" when pruning replaced a file that differed;
    "kept" when --no-prune kept yours."""
    rendered_hash = sha256_text(rendered)
    if os.path.islink(dest) or os.path.isdir(dest):
        (shutil.rmtree if os.path.isdir(dest) and not os.path.islink(dest) else os.unlink)(dest)
    installed_hash = sha256(dest)
    entry = files_entry.get(rel)
    nd = dest + ".new"
    legacy_ours = entry is None and installed_hash not in (None, rendered_hash) and pure_stack_copy(
        open(dest, encoding="utf-8", errors="replace").read(), [rendered] + legacy_renders(rel))
    in_sync = installed_hash is None or installed_hash == rendered_hash or installed_hash == entry or legacy_ours
    if in_sync or PRUNE or FORCE:
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        with open(dest, "w", encoding="utf-8") as f:
            f.write(rendered)
        files_entry[rel] = rendered_hash
        offered.pop(rel, None)
        if os.path.lexists(nd):
            drop(rel + ".new", "leftover render of a stack file")
        if in_sync:
            return "refreshed" if legacy_ours else None
        if PRUNE:
            report["replaced"][rel] = ("edited since the last install" if entry is not None
                                       else "a same-named file that isn't the stack's")
            return "replaced"
        return None
    if not (offered.get(rel) == rendered_hash and not os.path.exists(nd)):
        with wopen(nd) as f:
            f.write(rendered)
        offered[rel] = rendered_hash
    return "kept"


skill_names = sorted(os.path.basename(d) for d in glob.glob(os.path.join(SRC, "skills", "*")) if os.path.isdir(d))
skills_kept, skills_refreshed, skills_replaced = [], [], []
skill_files = set()
for name in skill_names:
    sdir = os.path.join(SRC, "skills", name)
    ddir = os.path.join(DEST, "skills", name)
    if os.path.islink(ddir) or os.path.isfile(ddir):
        os.unlink(ddir)
        report["replaced"]["skills/%s" % name] = "not a directory"
    for root, dirs, files in os.walk(sdir):
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        rel_root = os.path.relpath(root, sdir)
        out_root = ddir if rel_root == "." else os.path.join(ddir, rel_root)
        if os.path.islink(out_root) or os.path.isfile(out_root):   # never write through a link
            os.unlink(out_root)
        os.makedirs(out_root, exist_ok=True)
        for fn in files:
            if fn.endswith((".pyc", ".new")) or fn == ".DS_Store":
                continue
            sp = os.path.join(root, fn)
            op = os.path.join(out_root, fn)
            rel = os.path.relpath(op, DEST)
            skill_files.add(rel)
            try:
                text = open(sp, encoding="utf-8").read()
            except (UnicodeDecodeError, ValueError):
                if os.path.islink(op) or os.path.isdir(op):
                    (shutil.rmtree if os.path.isdir(op) and not os.path.islink(op) else os.unlink)(op)
                shutil.copy2(sp, op)
                continue
            state = install_tracked(rel, op, render(text))
            if state == "kept":
                skills_kept.append(rel)
            elif state == "refreshed":
                skills_refreshed.append(rel)
            elif state == "replaced":
                skills_replaced.append(rel)
# what the stack doesn't ship: whole skills, and files inside shipped skills
skills_root = os.path.join(DEST, "skills")
for name in sorted(os.listdir(skills_root)):
    rel_dir = "skills/%s" % name
    if name not in skill_names:
        tracked = any(r.startswith(rel_dir + "/") for r in list(files_entry) + list(offered))
        why = "no longer shipped by the stack" if tracked else "not shipped by the stack: yours or another tool's"
        if PRUNE:
            drop(rel_dir + "/" if os.path.isdir(os.path.join(skills_root, name)) else rel_dir, why)
        else:
            stale_kept.append((rel_dir + "/", why))
        continue
    for root, dirs, files in os.walk(os.path.join(skills_root, name)):
        for fn in sorted(files) + sorted(d for d in dirs if os.path.islink(os.path.join(root, d))):
            rel = os.path.relpath(os.path.join(root, fn), DEST)
            if rel in skill_files:
                continue
            why = ("leftover render of a stack file" if rel.endswith(".new") and rel[:-4] in skill_files
                   else "not part of the stack's %s skill" % name)
            if PRUNE:
                drop(rel, why)
            elif not why.startswith("leftover"):
                stale_kept.append((rel, why))
    if PRUNE:                                   # directories the removals left empty
        for root, dirs, files in os.walk(os.path.join(skills_root, name), topdown=False):
            if root != os.path.join(skills_root, name) and not os.listdir(root):
                os.rmdir(root)
for rel in [r for r in list(files_entry) + list(offered) if r.startswith("skills/")]:
    if rel not in skill_files and (PRUNE or not os.path.lexists(os.path.join(DEST, rel))):
        files_entry.pop(rel, None)
        offered.pop(rel, None)
print("  skills rendered (%d): %s" % (len(skill_names), ", ".join(skill_names)))
for rel in skills_refreshed:
    print("  %-34s refreshed (an older copy of the stack's; the backup keeps it)" % rel)
for rel in skills_replaced:
    print("  %-34s replaced (it differed from the stack's; the backup keeps it)" % rel)
for rel in skills_kept:
    print("  %-34s kept (yours or edited) -- new render at %s.new" % (rel, os.path.join(C, rel)))

# --- scripts the stack copies into hooks/, bin/ and mcp/ (step 6 put them in DEST): tracked in the
# manifest, so a later version that stops shipping one removes it. Files of your own there stay. ---
STACK_SCRIPTS = ["hooks/agent_guard.py", "hooks/agent_effort.json", "hooks/web_caps.py", "hooks/read_gate.py", "hooks/stack_report.py", "hooks/stack_usage.py", "hooks/stack_sched.py",
                 "hooks/stack_sched_refresh.py", "hooks/sched_model.json", "hooks/derive_sched_model.py",
                 "hooks/stack_limits.py", "hooks/stack_limits_seed.json", "hooks/stack_fanout.py",
                 "hooks/derive_thresholds.py", "bin/statusline.py", "bin/doctor.sh", "bin/with-stack-env",
                 "bin/mcp-headers", "bin/magg-private", "bin/claude-ultracode", "bin/stack_sdk.py", "bin/stack-update-tools", "bin/stack-budget",
                 "bin/stack-tree",
                 "mcp/image_studio_mcp.py",
                 "mcp/libdocs_mcp.py", "mcp/neural_memory_mcp.py"]
# files earlier stack versions installed before the manifest tracked scripts
LEGACY_SCRIPTS = {"hooks/router-guard.sh": "blackcat.md runs agent_guard.py directly now",
                  "mcp/opper_image_mcp.py": "images come from image-studio now",
                  "mcp/openrouter_image_mcp.py": "images come from image-studio now"}
_missing = [rel for rel in STACK_SCRIPTS if not os.path.isfile(os.path.join(DEST, rel))]
if _missing:
    sys.exit("install.sh: the staged copy lacks the stack's scripts (%s) — stopping; nothing in %s "
             "was changed" % (", ".join(_missing), C))
for rel in STACK_SCRIPTS:
    files_entry[rel] = sha256(os.path.join(DEST, rel))
stale_scripts = {r: "no longer shipped by the stack" for r in files_entry
                 if r.split("/")[0] in ("hooks", "bin", "mcp") and r not in STACK_SCRIPTS}
stale_scripts.update(LEGACY_SCRIPTS)
for rel, why in sorted(stale_scripts.items()):
    _p = os.path.join(DEST, rel)
    if not os.path.lexists(_p) or (os.path.isdir(_p) and not os.path.islink(_p)):
        files_entry.pop(rel, None)          # a script is a file: a directory there is yours
        continue
    if PRUNE:
        drop(rel, why)
        files_entry.pop(rel, None)
    else:
        stale_kept.append((rel, why))

for rel, why in stale_kept:
    report["notes"].append("%s: %s — kept (--no-prune)" % (rel, why))
save_manifest()
save_report()

# --- settings.json: JSON-escaped render, written to a temp file for the merge step ---
settings_text = open(os.path.join(SRC, "settings.json")).read()
open(os.environ["RENDERED_SETTINGS"], "w").write(render(settings_text, json_escape=True))

print("  " + ", ".join("%s=%s" % (k.strip("_").lower(), v) for k, v in SUBS.items()))
PY

say "7/11 Merge settings.json, validate, apply"
[ -f "$S/settings.json" ] || echo '{}' > "$S/settings.json"
# PREV_COMMIT (the commit the last install shipped, read from $C's manifest above) and the repo let
# the merge tell a permission setting the stack shipped from one you chose (settings_permission_scalars)
PRUNE="$PRUNE" PREV_COMMIT="$prev_commit" STACK_REPO="$HERE" python3 - "$RENDERED_SETTINGS" "$S/settings.json" \
  "$S/.stack-manifest.json" "$REPORT" "$C/settings.json" "$S/stack.env" "$SRC/bin/mcp-headers" <<'PY'
import json, os, re, runpy, subprocess, sys
from pathlib import Path
src, manifest_path, report_path, shown = sys.argv[1], sys.argv[3], sys.argv[4], sys.argv[5]
PRUNE = os.environ.get("PRUNE") == "1"
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
        out = subprocess.run(["git", "-C", os.environ.get("STACK_REPO") or ".", "show",
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
# permission rules earlier stack versions shipped before the manifest recorded them, and no longer
# ship: retracted on upgrade (a stack-shipped "mcp__magg" allowed every tool of every mounted server;
# "Read(**/.env.*)" also blocked agents from writing .env.example / .env.test — Read denies cover Edit)
RETIRED_PERMISSIONS = {"allow": {"mcp__magg"}, "deny": {"Read(**/.env.*)"}}
# env values earlier stack versions shipped before the manifest recorded them, and no longer ship:
# removed while they still hold that value. ENABLE_TOOL_SEARCH=true: tool search is on by default on
# the Anthropic API, and "true" forces it through gateways (ANTHROPIC_BASE_URL) that reject it.
# STACK_PROMPT_CTX_BUDGET / STACK_SESSION_CTX_BUDGET: the per-prompt and per-session caps are learned
# limits now (hard.prompt / hard.session in stack_limits.py, seeded at these values); a shipped env
# value would mask the learned one. A value you set yourself stays, as an override (doctor.sh says so).
RETIRED_ENV = {"ENABLE_TOOL_SEARCH": {"true"}, "STACK_PROMPT_CTX_BUDGET": {"100000000"},
               "STACK_SESSION_CTX_BUDGET": {"666000000"}}
# Both apply once, to an install whose manifest predates "settings_permissions"/"settings_env";
# later retractions come from the manifest itself. A value you add back afterwards stays.
# sandbox list entries go the same way through "settings_sandbox"; a manifest of an earlier install
# older than that key retires the cache dirs earlier versions let the sandbox write (R3-CACHES:
# unsandboxed tools load code from them). A first install (no manifest in $C: the staged one is
# already this run's) retracts nothing of yours.
prev_sandbox = manifest.get("settings_sandbox")
if not isinstance(prev_sandbox, dict):
    prev_sandbox = {"filesystem": {"allowWrite": [
        "~/.cache", "~/Library/Caches", "~/.cargo/registry", "~/.cargo/git", "~/go/pkg",
        "~/.gradle/caches", "~/.m2/repository", "~/.bun/install/cache", "~/.matplotlib",
        "~/.local/share/uv", "~/.npm", "~/.rustup", "~/.julia", "~/.elan"]}} \
        if os.path.exists(os.path.join(os.path.dirname(shown), ".stack-manifest.json")) else {}
if "settings_permissions" in manifest:
    RETIRED_PERMISSIONS = {}
if "settings_env" in manifest:
    RETIRED_ENV = {}
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
# The spawn knobs are owned too: they are the stack's guarantees (BlackCat's step cap, fan-out and
# copy caps, the per-agent MCP call cap), not preferences. The token budgets are learned limits
# (stack_limits.py), fixed per session by its snapshot, not env knobs the stack ships.
OWNED_ENV = {"STACK_ENV_FILE", "CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH",
             "MCP_DISCOVERY_CACHE", "CLAUDE_CODE_MAX_CONCURRENT_SUBAGENTS",
             "BLACKCAT_MAX_STEPS", "BLACKCAT_MAX_DISPATCH", "STACK_MAX_FANOUT",
             "STACK_MAX_FANOUT_BY_TYPE", "STACK_MAX_SELF_FANOUT", "STACK_MAX_MCP_CALLS"}
# values shipped by stack versions whose manifest predates "settings_env"
OLD_DEFAULTS = {"ROUTER_MAX_DISPATCH": {"1"}, "ANTHROPIC_DEFAULT_HAIKU_MODEL": {"claude-sonnet-5"}}
# The main-thread agent "router" is now "blackcat": its "agent" value and its knobs follow the
# rename. A knob you tuned moves to the new name; one still at a stack default is dropped (the
# merge below sets the new default).
OLD_SET_IF_ABSENT = {"agent": {"router"}}
RENAMED_ENV = {"ROUTER_MAX_STEPS": "BLACKCAT_MAX_STEPS", "ROUTER_MAX_DISPATCH": "BLACKCAT_MAX_DISPATCH",
               "ROUTER_DISPATCH_WINDOW_S": "BLACKCAT_DISPATCH_WINDOW_S"}
cur_env = dict(cur.get("env") or {})
for old, now in RENAMED_ENV.items():
    if old not in cur_env:
        continue
    val = cur_env.pop(old)
    if (now not in cur_env and str(val) != str(prev_env.get(old))
            and str(val) not in OLD_DEFAULTS.get(old, ()) and str(val) != str((new.get("env") or {}).get(now))):
        cur_env[now] = val
        print("  moved your env %s=%s to %s (the router is now blackcat)" % (old, val, now))
if cur_env != (cur.get("env") or {}):
    cur = dict(cur, env=cur_env)

try:
    report = json.load(open(report_path))
except (OSError, ValueError):
    report = {}
for key in ("removed", "replaced"):
    report.setdefault(key, {})
for key in ("config_removed", "config_replaced", "notes"):
    report.setdefault(key, [])
# hook commands of the stack, any version: its guard (whatever config dir or interpreter an earlier
# install rendered), the usage collector, the web caps, the read gate, /stack-doctor's bin/doctor.sh --hook,
# /stack-tree's bin/stack-tree --hook and the retired router-guard.sh. Every hook script settings.json ships must match, or each re-run keeps
# the installed copy as yours and appends the shipped one again (tests/test_install_state.py checks this)
STACK_HOOK_RE = re.compile(r"agent_guard\.py|router-guard\.sh|stack_usage\.py|web_caps\.py|read_gate\.py|/bin/doctor\.sh[^ ]{0,2} --hook|/bin/stack-tree[^ ]{0,2} --hook")


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
            retired = (set(prev_perm.get(pk) or []) | RETIRED_PERMISSIONS.get(pk, set())) - set(pv)
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
        if (k not in cur or cur.get(k) == prev_owned.get(k) or cur.get(k) == v
                or cur.get(k) in OLD_SET_IF_ABSENT.get(k, ())):
            merged[k] = v
        else:
            print("  kept your %s (the stack's: %s)" % (k, json.dumps(v)))
    elif k == "env":
        e = dict(cur.get("env") or {})
        for ek, sv in v.items():
            mine = e.get(ek)
            if (mine is None or ek in OWNED_ENV or str(mine) == str(sv) or str(mine) == str(prev_env.get(ek))
                    or str(mine) in OLD_DEFAULTS.get(ek, ())):
                if (mine is not None and ek in OWNED_ENV and str(mine) != str(sv)
                        and str(mine) != str(prev_env.get(ek)) and str(mine) not in OLD_DEFAULTS.get(ek, ())):
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
        for ek in sorted((set(prev_env) | set(RETIRED_ENV)) - set(v)):
            shipped = set(RETIRED_ENV.get(ek, ()))
            if ek in prev_env:
                shipped.add(str(prev_env[ek]))
            if ek in e and str(e[ek]) in shipped:
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
if ! python3 "$STATE_PY" validate "$S" "$STACK_PYTHON"; then
  echo "install.sh: the staged install failed validation (above) — nothing in $C was changed." >&2
  exit 1
fi
note "validated: JSON, agent and skill frontmatter, placeholders, agent_guard.py --self-test"
if have uv && [ "$NO_DEPS" = 0 ] && [ "$DRY_RUN" = 0 ]; then
  if (cd "$HERE" && uv run --quiet tests/lint_agents.py >"$WORK/lint.log" 2>&1); then note "lint: tests/lint_agents.py ok"
  else note "! tests/lint_agents.py reports problems in the stack repo (installing anyway):"; sed 's/^/      /' "$WORK/lint.log" | head -n 20; fi
fi

echo
python3 "$STATE_PY" plan "$C" "$S" "$REPORT" "$PLAN_JSON" "$SNAP"
if [ -n "$legacy_b" ]; then
  echo "moved out of the config dir: backups of earlier installs (they may hold a copy of stack.env)"
  printf '%s\n' "$legacy_b" | sed "s|^|  > |; s|\$| -> $BACKUP_ROOT/legacy/|"
fi
B=""
if [ "$DRY_RUN" = 1 ]; then
  note "--dry-run: nothing above was applied"
else
  python3 "$STATE_PY" apply "$C" "$S" "$PLAN_JSON" "$BACKUP_ROOT" "$STACK_COMMIT" "$WORK/backup-dir" "$SNAP"
  B="$(cat "$WORK/backup-dir")"
  [ -n "$legacy_b" ] && python3 "$STATE_PY" legacy-backups "$C" "$BACKUP_ROOT" move >/dev/null
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
    # db-engineer's Postgres server: download only (starting it needs DATABASE_URI)
    uv tool run --quiet --from postgres-mcp==0.3.0 python -c pass >/dev/null 2>&1 </dev/null || true
    ! have npx || npx -y @playwright/mcp@0.0.82 --help >/dev/null 2>&1 </dev/null || true
    ! have npx || npx -y context-mode@1.0.169 --help >/dev/null 2>&1 </dev/null || true
    # db-engineer's MongoDB and mobile-engineer's MobileBuildMCP servers: download only (fills npx's
    # cache with the package and its dependencies; runs only `node -e 0`)
    ! have npx || npm exec --yes --package=mongodb-mcp-server@3.0.5 -- node -e 0 >/dev/null 2>&1 </dev/null || true
    [ "$(uname -s)" != Darwin ] || ! have npx || npm exec --yes --package=mobilebuildmcp@2.7.1 -- node -e 0 >/dev/null 2>&1 </dev/null || true
  )
  note "prefetched libdocs, image-studio, neural-memory, markitdown, mcp-for-blender, lean-lsp-mcp, postgres-mcp, playwright, context-mode, mongodb-mcp-server, mobilebuildmcp (cache: $STACK_CACHE)"
fi

say "9/11 MCP servers (user scope, remote HTTP — lazy connect, tools deferred, keys via headersHelper)"
compute_mcp_plan

# User-scope servers the stack registered once and no longer uses: removed through `claude mcp`
# (the backup keeps each entry; --restore re-adds it). Context7 came before libdocs; later ones are
# the names the manifest recorded (mcp_registered) that the stack stopped shipping. An entry that
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
known = {"context7": ("mcp.context7.com", "libdocs replaced Context7")}
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
    if [ "$PRUNE" = 1 ]; then would "claude mcp remove -s user $name  (removed: $why)"
    else note "= $name: $why — kept (--no-prune)"; fi
  done
  printf '%s\n' "$PLAN" | while IFS=$'\t' read -r action name _cfg _prev _save why; do
    [ -n "$name" ] || continue
    case "$action" in keep) note "= $name ($why)" ;; *) would "claude mcp add-json -s user $name ...  ($action: $why)" ;; esac
  done
else
  stale="$(stale_mcp)"
  if [ -n "$stale" ] && [ "$PRUNE" = 1 ]; then
    ensure_backup
    while IFS=$'\t' read -r name prev why; do
      [ -n "$name" ] || continue
      STACK_MCP_ENTRY="$prev" python3 "$STATE_PY" record "$B" mcp_removed "$name"
      if claude mcp remove -s user "$name" >/dev/null 2>&1 </dev/null; then note "- removed MCP server $name ($why; the backup keeps its entry)"
      else note "! could not remove MCP server $name — claude mcp remove -s user $name"; fi
    done <<EOF_STALE
$stale
EOF_STALE
  elif [ -n "$stale" ]; then
    printf '%s\n' "$stale" | while IFS=$'\t' read -r name _prev why; do note "= $name: $why — kept (--no-prune)"; done
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
  if [ "$WITH_LSP" = 1 ] && [ "$NO_DEPS" = 0 ] && [ "$DRY_RUN" = 1 ]; then
    would "install the missing language servers (pyright, typescript-language-server, rust-analyzer, ...)"
  elif [ "$WITH_LSP" = 1 ] && [ "$NO_DEPS" = 0 ]; then
    # npm -g goes into Node's own prefix when that is writable and outlives Node upgrades (Homebrew);
    # a root-owned distro prefix (/usr: EACCES) or a version manager's per-version prefix under
    # $HOME (nvm, fnm, volta) gets ~/.local instead (bin/ there is on PATH via the profile line).
    # Pinned versions, install scripts off (none of these packages needs one): what runs is what
    # was reviewed (versions checked against the npm registry 2026-09-29).
    npm_g(){
      local pfx; pfx="$(npm prefix -g 2>/dev/null || true)"
      case "$pfx" in
        ""|"$HOME"/*) npm install -g --ignore-scripts --prefix "$HOME/.local" --silent "$@" ;;
        *) if [ -w "$pfx/lib" ]; then npm install -g --ignore-scripts --silent "$@"; else npm install -g --ignore-scripts --prefix "$HOME/.local" --silent "$@"; fi ;;
      esac
    }
    PYRIGHT_PIN="pyright@1.1.414"
    have pyright-langserver || { have npm && npm_g "$PYRIGHT_PIN" >/dev/null 2>&1; } \
      || note "! pyright install failed — npm install -g --ignore-scripts --prefix ~/.local $PYRIGHT_PIN"
    # typescript-language-server 6 needs Node >= 22.22.2; older Node gets the 5.x line. TypeScript 7
    # (the native compiler) ships no tsserver, which the language server runs: 6.x it is.
    TSLS="typescript-language-server@6.0.1"
    node -e 'const [a,b,c]=process.versions.node.split(".").map(Number); process.exit(a>22||(a===22&&(b>22||(b===22&&c>=2)))?0:1)' 2>/dev/null \
      || TSLS="typescript-language-server@5.3.0"
    TS_PIN="typescript@6.0.3"
    have typescript-language-server || { have npm && npm_g "$TSLS" "$TS_PIN" >/dev/null 2>&1; } \
      || note "! typescript-language-server install failed — npm install -g --ignore-scripts --prefix ~/.local $TSLS $TS_PIN"
    lsp_works rust-analyzer || { have rustup && rustup component add rust-analyzer >/dev/null 2>&1; } || note "! rust-analyzer: rustup component add rust-analyzer"
    # Servers for the stack's other languages come from each language's own toolchain manager, and
    # only when that manager is already here: the installer never installs GHCup, juliaup, elan,
    # Coursier or Kotlin for you. Lean needs nothing extra (elan's `lake serve` is the server).
    if ! lsp_works haskell-language-server-wrapper && have ghcup; then
      ghcup install hls recommended >/dev/null 2>&1 || true
      lsp_works haskell-language-server-wrapper || note "! haskell-language-server: ghcup install hls recommended (then ghcup set hls recommended)"
    fi
    if ! lsp_works julia-languageserver && have julia; then
      note "  installing LanguageServer.jl into the Julia environment @claude-lsp (a few minutes the first time)"
      julia --startup-file=no --history-file=no --project=@claude-lsp -e 'using Pkg; Pkg.add("LanguageServer")' >/dev/null 2>&1 \
        || note "! LanguageServer.jl: julia --project=@claude-lsp -e 'using Pkg; Pkg.add(\"LanguageServer\")'"
    fi
    if ! lsp_works metals && have cs; then
      cs install metals >/dev/null 2>&1 || note "! metals: cs install metals"
    fi
    if ! lsp_works kotlin-lsp && { have kotlin || have kotlinc; } && have brew; then
      brew install JetBrains/utils/kotlin-lsp >/dev/null 2>&1 || note "! kotlin-lsp: brew install JetBrains/utils/kotlin-lsp"
    fi
  fi
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
  [ -n "$lsp_missing" ] && note "- no language server for:$lsp_missing (./install.sh --with-lsp installs pyright, typescript-language-server, rust-analyzer, and HLS, LanguageServer.jl, Metals, kotlin-lsp through ghcup, julia, cs, brew when those are present; Java: brew install jdtls; Lean: elan)"
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
  for n in claude-ninja claude-supreme; do
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
  # claude-ninja / claude-supreme: ninja-coder or supreme-coder as the main thread at ultracode, the only
  # place ultracode runs (an agent file's effort reaches subagents only, and they can't run workflows).
  mkdir -p "$HOME/.local/bin"
  for n in claude-ninja claude-supreme; do
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
pending="$( (cd "$C" && find agents rules skills -name '*.new' -type f 2>/dev/null) | sort || true)"
if [ -n "$pending" ]; then
  note "! You edited these files, so they were kept; the stack's new versions wait next to them."
  note "  Merge each (diff -u <file> <file>.new), then delete the .new — or rerun without --no-prune:"
  printf '%s\n' "$pending" | sed "s|^|      $C/|"
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
     Hardest problems at ultracode, as a session of their own: claude-ninja, or claude-supreme
     (dispatched by BlackCat they run at max: ultracode exists only on a main thread).
EOF
cat <<EOF
  3. macOS computer use (designer, motion-designer, doc-specialist, verifier):
     /mcp → computer-use → Enable  (once per project), then grant Accessibility + Screen Recording.
  4. Browser agent with your logins: start with  claude --chrome  (or /chrome → Enabled by default).
  5. Optional: ./install.sh --with-ml (shared ML venv) · --with-lsp (language servers) · --with-adobe
     · --with-extra-plugins (skill-creator, math-olympiad skills)
EOF
