#!/bin/sh
# repro-check.sh [--runs N]: is the static GNU bash build of the eq-container images reproducible? (user-run: it builds containers)
#   Runs `build.sh --resolve-tools --repro-dump` N times (default 3, 2 to 10), the same entrypoint that prints the bash pins:
#   each run builds the bash-report stage with --no-cache (GPG-verified source, patches, the recipe tc/build-bash.sh) and keeps
#   its own log, tools-report-<UTC stamp>-<pid>.log, in the state directory. A build takes several minutes (make -j1).
#   Then it compares BASH_SRC_SHA256, BASH_PATCHES_SHA256 and BASH_BIN_SHA256 of the runs.
#   - all runs equal: the last line is `REPRODUCIBLE xN`. Next: bash lib/eq-container/build.sh --resolve-tools --write-pin
#     (builds nothing: it pins the values the agreeing reports hold; review the diff and commit).
#   - otherwise the last line is `DIFFERS (n distinct)` and the report holds a minimal diff of the first differing run against
#     run 1: the differing bytes (cmp -l | head), the printable strings that differ (strings -a), and the lines of the recipe's
#     `DIAG` output that differ (toolchain versions, config.h, every object file, the binary before strip): the first differing
#     DIAG line names the stage to fix.
#   - a failed build: the last line is `BUILD FAILED (run i, rc r)`, the exit status is build.sh's (10 no container, 12 build).
# Report: $EQ_STATE_DIR/repro-<UTC stamp>-<pid>/report.txt (state dir default: ~/.local/state/claude-agent-stack/eq-container),
# next to the run-i.out/.err/.bin files; a directory is never reused, nothing earlier is overwritten.
# Exit: 0 reproducible, 1 differs, 2 usage, otherwise the failed build's status (12 for a run that printed no REPORT line).
# POSIX sh; run it with sh, bash or zsh.
set -eu
here=$(cd "$(dirname "$0")" && pwd -P)
usage() { awk 'NR == 1 { next } /^#/ { sub(/^# ?/, ""); print; next } { exit }' "$0"; }
die2() { echo "repro-check.sh: $*" >&2; exit 2; }
runs=3
while [ $# -gt 0 ]; do
  case "$1" in
    --runs) [ $# -ge 2 ] || die2 "--runs needs a value"; runs=$2; shift;;
    --runs=*) runs=${1#--runs=};;
    -h|--help) usage; exit 0;;
    *) die2 "unknown argument: $1 (see --help)";;
  esac
  shift
done
case "$runs" in ""|*[!0123456789]*|0*) die2 "--runs must be a whole number from 2 to 10, got '$runs'";; esac
{ [ "$runs" -ge 2 ] && [ "$runs" -le 10 ]; } || die2 "--runs must be a whole number from 2 to 10, got '$runs'"
[ -f "$here/build.sh" ] || die2 "$here/build.sh not found"

if [ -n "${EQ_STATE_DIR:-}" ]; then state=$EQ_STATE_DIR
elif [ "$(cat "$here/LAYOUT" 2>/dev/null || true)" = repo ]; then state="${XDG_STATE_HOME:-${HOME:?HOME is not set}/.local/state}/claude-agent-stack/eq-container"
else state="$here/.state"; fi
mkdir -p "$state" && chmod 700 "$state" 2>/dev/null || true
rd="$state/repro-$(date -u +%Y%m%dT%H%M%SZ)-$$"
mkdir "$rd" || die2 "cannot create $rd (it must not exist: nothing earlier is overwritten)"
chmod 700 "$rd" 2>/dev/null || true
rep="$rd/report.txt"
say() { printf '%s\n' "$*" | tee -a "$rep"; }
indent() { sed 's/^/    /' | tee -a "$rep"; }
verdict() { say "$*"; }

say "repro-check: $runs builds of the bash-report stage, report $rep"
i=1
while [ "$i" -le "$runs" ]; do
  say "== run $i/$runs: build.sh --resolve-tools --repro-dump (a few minutes)"
  rc=0
  bash "$here/build.sh" --resolve-tools --repro-dump > "$rd/run-$i.out" 2> "$rd/run-$i.err" || rc=$?
  if [ "$rc" != 0 ]; then
    tail -n 20 "$rd/run-$i.err" | cut -c1-300 | indent
    say "(stdout $rd/run-$i.out, stderr $rd/run-$i.err)"
    verdict "BUILD FAILED (run $i, rc $rc)"
    exit "$rc"
  fi
  log=$(sed -n 's/^REPORT //p' "$rd/run-$i.out" | tail -n 1)
  [ -n "$log" ] && [ -f "$log" ] || { say "run $i printed no REPORT line (see $rd/run-$i.out)"; verdict "BUILD FAILED (run $i, rc 0: no report)"; exit 12; }
  printf '%s\n' "$log" > "$rd/run-$i.log"
  : > "$rd/run-$i.pins"
  for k in BASH_SRC_SHA256 BASH_PATCHES_SHA256 BASH_BIN_SHA256; do
    v=$(awk -v k="$k" '$1 == "PIN" && $2 == k { print $3 }' "$rd/run-$i.out" | head -n 1)
    printf '%s %s\n' "$k" "${v:-missing}" >> "$rd/run-$i.pins"
  done
  say "   $(tr '\n' ' ' < "$rd/run-$i.pins")"
  say "   log $log"
  i=$((i + 1))
done

# ---- compare
n=$(for j in $(seq 1 "$runs"); do tr '\n' ' ' < "$rd/run-$j.pins"; echo; done | sort -u | wc -l | tr -d ' ')
bins=$(for j in $(seq 1 "$runs"); do sed -n 's/^BASH_BIN_SHA256 //p' "$rd/run-$j.pins"; done | sort -u | wc -l | tr -d ' ')
if [ "$n" = 1 ] && ! grep -q ' missing$' "$rd/run-1.pins"; then
  say "all $runs builds: $(tr '\n' ' ' < "$rd/run-1.pins")"
  say "next: bash $here/build.sh --resolve-tools --write-pin   (builds nothing; pins these values, review the diff, then commit;"
  say "      it also refuses when an EARLIER report of this recipe in the state directory disagrees)"
  verdict "REPRODUCIBLE x$runs"
  exit 0
fi

say "the builds differ: $n distinct (SRC, PATCHES, BIN) triples, $bins distinct binaries"
b64dec() { if base64 -d < /dev/null > /dev/null 2>&1; then base64 -d; else base64 -D; fi; }
sha256() { if command -v shasum > /dev/null 2>&1; then shasum -a 256; else sha256sum; fi | cut -d' ' -f1; }
decode() { # LOG OUT WANTED-SHA: the dumped binary of a report, 0 only if it hashes to what the build printed
  LC_ALL=C grep -o 'BINB64 DATA [A-Za-z0-9+/=]*' "$1" | cut -d' ' -f3 | b64dec 2> /dev/null | gzip -dc > "$2" 2> /dev/null || return 1
  [ "$(sha256 < "$2")" = "$3" ]
}
want1=$(sed -n 's/^BASH_BIN_SHA256 //p' "$rd/run-1.pins")
log1=$(cat "$rd/run-1.log")
have1=0; decode "$log1" "$rd/run-1.bin" "$want1" && have1=1
LC_ALL=C grep -o 'DIAG .*' "$log1" > "$rd/run-1.diag" || true
LC_ALL=C grep -o 'REPRO .*' "$log1" | head -n 1 > "$rd/run-1.repro" || true
j=2
while [ "$j" -le "$runs" ]; do
  wantj=$(sed -n 's/^BASH_BIN_SHA256 //p' "$rd/run-$j.pins")
  logj=$(cat "$rd/run-$j.log")
  if ! cmp -s "$rd/run-1.pins" "$rd/run-$j.pins"; then
    say "-- run 1 vs run $j"
    diff "$rd/run-1.pins" "$rd/run-$j.pins" | indent || true
    LC_ALL=C grep -o 'DIAG .*' "$logj" > "$rd/run-$j.diag" || true
    LC_ALL=C grep -o 'REPRO .*' "$logj" | head -n 1 > "$rd/run-$j.repro" || true
    if [ "$want1" != "$wantj" ]; then
      havej=0; decode "$logj" "$rd/run-$j.bin" "$wantj" && havej=1
      if [ "$have1" = 1 ] && [ "$havej" = 1 ]; then
        say "  bytes: run 1 $(wc -c < "$rd/run-1.bin" | tr -d ' ') bytes, run $j $(wc -c < "$rd/run-$j.bin" | tr -d ' ') bytes, $(cmp -l "$rd/run-1.bin" "$rd/run-$j.bin" 2> /dev/null | wc -l | tr -d ' ') differing byte positions (offset, octal value in run 1, in run $j):"
        cmp -l "$rd/run-1.bin" "$rd/run-$j.bin" 2> /dev/null | head -n 40 | indent || true
        strings -a "$rd/run-1.bin" > "$rd/run-1.str" 2> /dev/null || true
        strings -a "$rd/run-$j.bin" > "$rd/run-$j.str" 2> /dev/null || true
        say "  strings -a, run 1 (<) vs run $j (>), first 40 lines:"
        diff "$rd/run-1.str" "$rd/run-$j.str" | head -n 40 | indent || true
      else
        say "  the binary of run 1 (decoded: $have1) or of run $j (decoded: $havej) could not be recovered from the logs (a build-log size limit clips the dump); byte comparison skipped, the DIAG lines below remain"
      fi
    fi
    say "  recipe environment (REPRO line), run 1 vs run $j:"
    diff "$rd/run-1.repro" "$rd/run-$j.repro" | indent || true
    say "  DIAG lines that differ, run 1 (<) vs run $j (>), first 40 (the first one names the stage: apk versions and gcc/ld = toolchain drift, config.h = configure, obj = a compile, unstripped/binary = the link or strip):"
    diff "$rd/run-1.diag" "$rd/run-$j.diag" | head -n 40 | indent || true
  fi
  j=$((j + 1))
done
say "files: $rd (run-N.out/.err, run-N.log = the path of each tools-report, run-N.bin = the recovered binaries)"
verdict "DIFFERS ($n distinct)"
exit 1
