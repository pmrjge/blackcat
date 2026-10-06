#!/usr/bin/env bash
# probe hook (probe.sh section G): the TOOLS.toml rows for the image under probe. Host side; verify-tools.sh starts nothing but
# `docker create` + `docker cp` (a stopped container, removed at once). An image TOOLS.toml does not describe (the baseline eq-lean,
# the distroless candidate) gets INFO rows, never a pass it did not earn.
#   tools_manifest_valid      verify-tools.sh --manifest for this image: structure, allowlists, https-only urls, no PLACEHOLDER left
#   tools_lock_matches_manifest  verify-tools.sh --images --deep: build record, label eq.tools.sha256 = hash of the current entries,
#                             /opt/eq/TOOLS.lock = manifest (no undeclared tool), every installed tool file re-hashed from outside
set -u
here=$(cd "$(dirname "$0")/.." && pwd -P)
: "${EQ_PROBE_IMAGE:?run through probe.sh}" "${EQ_PROBE_LIB:?run through probe.sh}"
# shellcheck disable=SC1091
. "$here/tools.sh"
# shellcheck disable=SC1090
. "$EQ_PROBE_LIB"
tm_load "$here/TOOLS.toml" || { echo "T|tools_manifest_valid|FAIL|TOOLS.toml does not parse"; exit 1; }
name=""
for n in $(tm_names image); do
  if [ "$(eq_img_tag "$n")" = "$EQ_PROBE_IMAGE" ] || { [ -n "${EQ_PROBE_IMAGE_ID:-}" ] && [ "$(eq_img_get "$n" EQ_IMAGE_ID)" = "$EQ_PROBE_IMAGE_ID" ]; }; then name=$n; break; fi
done
if [ -z "$name" ]; then
  echo "T|tools_manifest_valid|INFO|$EQ_PROBE_IMAGE is not an image of TOOLS.toml (baseline or candidate): pinned by its Dockerfile only"
  echo "T|tools_lock_matches_manifest|INFO|no manifest entry for this image"
  exit 0
fi
out=$(bash "$here/verify-tools.sh" --select "$name" --manifest 2>&1); rc=$?
if [ "$rc" = 0 ]; then echo "T|tools_manifest_valid|PASS|$name: every tool pinned, allowlists hold"
else echo "T|tools_manifest_valid|FAIL|$name: rc $rc: $(printf '%s' "$out" | grep -E '^(PENDING|PROBLEM)' | head -n 2 | tr '\n' ' ')"; fi
out=$(bash "$here/verify-tools.sh" --select "$name" --images --deep 2>&1); rc=$?
if [ "$rc" = 0 ]; then echo "T|tools_lock_matches_manifest|PASS|$name: label, lock and every installed tool file match the manifest"
else echo "T|tools_lock_matches_manifest|FAIL|$name: rc $rc: $(printf '%s' "$out" | grep -E '^IMAGE' | head -n 2 | tr '\n' ' ')"; fi
exit 0
