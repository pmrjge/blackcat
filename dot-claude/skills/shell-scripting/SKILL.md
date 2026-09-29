---
name: shell-scripting
description: Load before writing or fixing a shell script or non-trivial one-liner — bash 3.2 vs zsh vs POSIX sh, BSD vs GNU tools, quoting, strict mode, traps, shellcheck.
---
# Shell scripting

## Scope
Scripts and pipelines in sh/bash/zsh that must run on this Mac and usually on Linux too. Git plumbing in `git-workflows`; CI job steps in `ci-cd-pipelines`; Dockerfile `RUN` lines in `container-images`; untrusted input in `secure-coding`.

## Pick the interpreter
- `#!/usr/bin/env bash` for bash scripts; `#!/bin/sh` only for code you have checked as POSIX (`/bin/sh` is dash on Debian/Ubuntu, bash 3.2 in POSIX mode on macOS).
- macOS `/bin/bash` is **3.2.57** (checked on macOS 27): no `declare -A`, `mapfile`/`readarray`, `${var,,}`/`${var^^}`, `shopt -s inherit_errexit`, `wait -n`, `${arr[-1]}`. Either stay 3.2-compatible or require Homebrew bash explicitly and say so (`#!/opt/homebrew/bin/bash` is not portable; check `BASH_VERSINFO[0] -ge 5` at the top instead).
- zsh is the macOS login shell; never write scripts that depend on it unless the shebang says zsh (arrays are 1-based, unquoted `$var` does not word-split).
- The interactive shell here may wrap `grep`/`find` in functions or shims (ugrep, bfs). Test portability with absolute paths (`/usr/bin/grep`, `/usr/bin/find`) or in a Linux container.

## macOS (BSD) vs GNU — verified on macOS 27
| Task | macOS | GNU/Linux | Portable choice |
|---|---|---|---|
| In-place edit | `sed -i '' 's/a/b/' f` (`sed -i 's/…/' f` fails) | `sed -i 's/a/b/' f` | `sed -i.bak 's/a/b/' f && rm f.bak`, or `perl -pi -e` |
| Relative date | `date -v+1d +%F` (no `-d`) | `date -d tomorrow +%F` | a PEP 723 helper run with `uv run --script`, or branch on `uname` |
| File size | `stat -f %z f` (no `-c`) | `stat -c %s f` | `wc -c < f` |
| Canonical path | `realpath`, `readlink -f` exist | same | `realpath` |
| PCRE grep | `/usr/bin/grep -P` → invalid option | `grep -P` | `grep -E`, or `perl -ne` / `rg` |
| No-input xargs | `-r` accepted | `-r` needed to skip empty input | `xargs -r` (both) with `-0` |
| Version sort | `sort -V` works | works | ok |
| base64 decode | `-d` or `-D` | `-d` | `base64 -d` |
| `timeout` | absent | coreutils | `gtimeout` (Homebrew coreutils) or `perl -e 'alarm …'` |
| `sed` extended regex | `-E` | `-E` (or `-r`) | `-E` |

Homebrew `coreutils`/`gnu-sed`/`grep` give `g`-prefixed GNU tools (`gsed`, `gdate`, `gstat`); require them explicitly rather than assuming.

## Strict mode, done right
```bash
#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'                      # optional; keep default IFS if you rely on space splitting
trap 'echo "error: line $LINENO: $BASH_COMMAND" >&2' ERR
```
- `set -e` is ignored inside `if`/`while` conditions, `&&`/`||` chains and any function called from them; a failing `$(…)` inside `local x=$(…)` is masked by `local` (declare first, assign second).
- In bash < 4.4 (macOS), command substitutions do not inherit `-e`; check critical ones explicitly: `out=$(cmd) || die "cmd failed"`.
- `pipefail` + `head`/`grep -q` can fail with SIGPIPE (exit 141) upstream; tolerate it where intended (`… | head -1 || true`, or capture first).
- `set -u`: use `${var:-}` for optional variables and `"${arr[@]+"${arr[@]}"}"` for possibly empty arrays on bash 3.2.
- Prefer explicit handling for the few commands that may fail: `if ! out=$(cmd 2>&1); then …; fi`.

## Quoting and arguments
- Quote every expansion: `"$var"`, `"$(cmd)"`, `"$@"`. Build argument lists in arrays: `args=(--flag "$path"); cmd "${args[@]}"`.
- `--` before user-supplied paths (`rm -- "$f"`, `grep -- "$pat" "$f"`); never `eval` user data.
- Filenames with spaces/newlines: `find … -print0 | xargs -0 …`, or `while IFS= read -r -d '' f; do …; done < <(find … -print0)`.
- Globs: guard no-match (`[ -e "$f" ] || continue`, or `shopt -s nullglob` in bash).
- Loop over lines: `while IFS= read -r line; do …; done < file` (never `for line in $(cat file)`). Process substitution `< <(cmd)` keeps the loop in the current shell (variables survive), unlike `cmd | while`.
- Here-docs: `<<'EOF'` for literal text, `<<EOF` to expand; `<<-EOF` strips leading tabs only.

## Temp files, cleanup, signals
```bash
tmp=$(mktemp -d "${TMPDIR:-/tmp}/job.XXXXXX")
trap 'rm -rf -- "$tmp"' EXIT
trap 'exit 130' INT; trap 'exit 143' TERM   # EXIT trap still runs
```
- `mktemp` template: trailing `XXXXXX` works on both; macOS `mktemp -t prefix` differs from GNU `-t` — use a full template.
- Make re-runs idempotent: `mkdir -p`, `ln -sfn`, check-before-create, write to a temp file then `mv` atomically.
- Locking for concurrent runs: `mkdir "$lockdir"` as a mutex (atomic everywhere); `flock` is Linux-only.

## Tests and arithmetic
- bash: `[[ $a == "$b" ]]` (quote the right side to compare literally), `[[ $s =~ $re ]]` (regex unquoted in a variable), `(( n > 3 ))` for integers.
- POSIX sh: `[ "$a" = "$b" ]`, `-eq/-lt` for integers, no `[[`, no `==`, no arrays, `$(( ))` is fine.
- `printf '%s\n' "$x"` instead of `echo` for arbitrary data (`echo -e`/`-n` differ between shells).

## Lint and format
- `shellcheck -x script.sh` (v0.11.0, Aug 2025; installed here). `-s sh|bash` to force a dialect; `-o all` for optional checks during review. Disable a check only on the line, with a reason: `# shellcheck disable=SC2086 # intentional splitting of $FLAGS`.
- Never silence: SC2086 (unquoted expansion) without reason, SC2155 (masked return in `local x=$(…)`), SC2046, SC2164 (`cd` without `|| exit`), SC2064 (trap quoting), SC3xxx (non-POSIX in sh).
- `shfmt -d -i 2 -ci script.sh` (shfmt v3.14.1; `brew install shfmt`) for formatting diffs; `-w` to apply.
- Test: run with `bash -n` (syntax), then on macOS and in `docker run --rm -v "$PWD":/w -w /w debian:stable-slim sh script.sh` for dash; bats-core for suites.

## When to stop using shell
Past ~100 lines, or when you need data structures, JSON beyond a `jq` filter, retries with backoff, or concurrency: write a PEP 723 script and run it with `uv run --script` (`python-engineering`).

## Checklist
Shebang matches the dialect · bash 3.2-safe or version-checked · shellcheck clean · every expansion quoted · `--` before paths · temp dir with EXIT trap · idempotent · tested on macOS and one Linux shell.

Sources (checked 2026-09-29): https://github.com/koalaman/shellcheck/releases (v0.11.0) · https://github.com/mvdan/sh/releases (v3.14.1) · https://www.gnu.org/software/bash/manual/bash.html · https://pubs.opengroup.org/onlinepubs/9799919799/ · local probes of /bin/bash, sed, date, stat, grep, xargs, sort, base64, mktemp on macOS 27.0.1.
