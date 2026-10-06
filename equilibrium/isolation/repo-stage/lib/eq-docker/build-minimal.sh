#!/usr/bin/env bash
# build-minimal.sh: build the minimal candidates. Same options as build.sh (it is a thin wrapper).
#   ./build-minimal.sh [scratch|distroless|all] [--keep-profile conservative|noprivate|slim] [--yes] [--dry-run] [--check]
#                      [--no-cache] [--force] [--uninstall] ...
#   scratch     (default) eq-lean-min + eq-py-min + eq-min, FROM scratch (Dockerfile.minimal)
#   distroless  eq-lean-min (if missing) + eq-lean-dl on a distroless cc base (Dockerfile.distroless); needs DISTROLESS_BASE in PINS
#   all         scratch, then distroless
# First use: ./build.sh --resolve-busybox --write-pin   (BUSYBOX_SHA256 in PINS is a placeholder until you do).
# The baseline eq-lean is built by ./build.sh (no argument). Files are started through `bash`, so no execute bit is needed.
here=$(cd "$(dirname "$0")" && pwd -P)
cand=scratch
case "${1:-}" in scratch|distroless|all) cand=$1; shift;; esac
case "$cand" in
  scratch)    exec bash "$here/build.sh" --set min "$@";;
  distroless) exec bash "$here/build.sh" --set dl "$@";;
  all)        bash "$here/build.sh" --set min "$@" || exit $?
              exec bash "$here/build.sh" --set dl "$@";;
esac
