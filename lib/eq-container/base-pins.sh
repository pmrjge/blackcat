#!/usr/bin/env bash
# base-pins.sh: verify, on the host, the pinned distroless base of the eq-container images (PINS DISTROLESS_CC, the image INDEX
# digest, and DISTROLESS_CC_ARM64, its linux/arm64 manifest): checklist D1. Never builds, never edits a file, starts no
# container. Run it from a normal terminal (an agent's sandbox cannot reach gcr.io or Sigstore). Bash 3.2 (macOS) or Linux;
# needs cosign (https://github.com/sigstore/cosign; macOS: brew install cosign) and python3.
#   bash lib/eq-container/base-pins.sh
# Checks, in order (nothing is printed on stdout before every one has passed):
#   1. format: DISTROLESS_CC = gcr.io/distroless/<name>-debian13[:tag]@sha256:<64 hex> (never a tag alone, `latest` or a `debug`
#      variant, which carries a busybox shell), DISTROLESS_CC_ARM64 = sha256:<64 hex>                               (else exit 2)
#   2. placeholders: an empty, UNSET or TODO value                                                                 (exit 13)
#   3. offline: base/distroless-cc-debian13-nonroot.index.json and .arm64.manifest.json (the bytes the pins were read from)
#      hash to the two pins, the index lists exactly that linux/arm64 manifest with its size, and the manifest has layers
#      (eqc_json.py base-verify): consistency of the kept files with the pins                                      (else exit 1)
#   4. authenticity: `cosign verify DISTROLESS_CC --certificate-oidc-issuer https://accounts.google.com --certificate-identity
#      keyless@distroless.iam.gserviceaccount.com` (the identity the distroless README names) must exit 0, and every verified
#      signature payload must name exactly the pinned index digest                                                 (else exit 1)
# Output: `BASE distroless-cc <DISTROLESS_CC> arm64 <DISTROLESS_CC_ARM64> layers <N> cosign=OK`, exit 0.
# Env: EQ_COSIGN_BIN (default: cosign on PATH; the tests use a fake), EQ_PINS_FILE (default ./PINS beside this script).
# A re-pin (distroless rebuilds often): fetch the new index and arm64 manifest bytes into base/, change PINS and the ARG defaults of
# both Dockerfiles together, run this, then rebuild (README.md).
set -euo pipefail
here=$(cd "$(dirname "$0")" && pwd -P)
# shellcheck disable=SC1091
. "$here/tools.sh"

case "${1:-}" in
  "") ;;
  -h|--help) awk 'NR == 1 { next } /^#/ { print; next } { exit }' "$0"; exit 0;;
  *) echo "base-pins.sh: unknown argument: $1" >&2; exit 2;;
esac

ISSUER=https://accounts.google.com
IDENTITY=keyless@distroless.iam.gserviceaccount.com
INDEX="$here/base/distroless-cc-debian13-nonroot.index.json"
MANIFEST="$here/base/distroless-cc-debian13-nonroot.arm64.manifest.json"
PINS_FILE=${EQ_PINS_FILE:-$here/PINS}
COSIGN=${EQ_COSIGN_BIN:-cosign}

die() { echo "base-pins.sh: FAILED: $*" >&2; exit 1; }
bad_pin() { echo "base-pins.sh: PINS: $*" >&2; exit 2; }
pin() { sed -n "s/^$1=//p" "$PINS_FILE" | head -n 1; }
placeholder() { case "$1" in ""|UNSET|*TODO*) return 0;; esac; return 1; }
hex64() { tm_is_hex64 "$1"; }   # literal character lists (tools.sh): never a locale-dependent bracket range

[ -f "$PINS_FILE" ] || bad_pin "$PINS_FILE not found"
REF=$(pin DISTROLESS_CC); ARM=$(pin DISTROLESS_CC_ARM64)
for k in DISTROLESS_CC DISTROLESS_CC_ARM64; do
  n=$(grep -c "^$k=" "$PINS_FILE" || true)
  [ "$n" = 1 ] || bad_pin "$k: $n lines in PINS, want exactly one"
done
if placeholder "$REF" || placeholder "$ARM"; then
  echo "base-pins.sh: DISTROLESS_CC or DISTROLESS_CC_ARM64 is a placeholder in PINS: read the index and its linux/arm64 manifest of gcr.io/distroless/cc-debian13:nonroot, keep their bytes in base/, pin both digests, then run this again" >&2
  exit 13
fi
# 1. format
case "$REF" in *@sha256:*) ;; *) bad_pin "DISTROLESS_CC '$REF' is not pinned by digest (NAME[:TAG]@sha256:<64 hex>)";; esac
hex64 "${REF#*@sha256:}" || bad_pin "DISTROLESS_CC's digest is not 64 lowercase hex"
name=${REF%%@sha256:*}
tm_only "$name" "$TM_LOWER$TM_DIGITS./:_-" || bad_pin "DISTROLESS_CC '$name' holds characters it may not"
case "$name" in *debug*) bad_pin "DISTROLESS_CC is a debug variant (it carries a busybox shell): refused";; esac
last=${name##*/}
case "$last" in *:*) repo=${name%:*}; [ "${last#*:}" != latest ] || bad_pin "DISTROLESS_CC names the tag latest";; *) repo=$name;; esac
case "$repo" in gcr.io/distroless/*-debian13) ;; *) bad_pin "DISTROLESS_CC '$repo' is not gcr.io/distroless/<name>-debian13";; esac
mid=${repo#gcr.io/distroless/}; mid=${mid%-debian13}
tm_only "$mid" "$TM_LOWER$TM_DIGITS-" || bad_pin "DISTROLESS_CC '$repo' is not gcr.io/distroless/<name>-debian13"
case "$ARM" in sha256:*) hex64 "${ARM#sha256:}" || bad_pin "DISTROLESS_CC_ARM64 is not sha256:<64 hex>";; *) bad_pin "DISTROLESS_CC_ARM64 is not sha256:<64 hex>";; esac
DIGEST="sha256:${REF#*@sha256:}"

# 3. offline consistency of the kept bytes with the pins
[ -f "$INDEX" ] && [ -f "$MANIFEST" ] || die "base/ lacks the index or the arm64 manifest ($INDEX, $MANIFEST)"
layers=$(python3 -I "$here/eqc_json.py" base-verify "$INDEX" "$MANIFEST" "$DIGEST" "$ARM" 2>/dev/null) \
  || die "base/: the index or the arm64 manifest does not hash to the pins, or the index does not list that linux/arm64 manifest"
nl=$(printf '%s\n' "$layers" | sed '/^$/d' | wc -l | tr -d ' ')
[ "$nl" -gt 0 ] || die "the arm64 manifest lists no layer"

# 4. authenticity: the keyless signature of the pinned index, by the distroless identity
command -v "$COSIGN" >/dev/null 2>&1 || die "cosign not found (https://github.com/sigstore/cosign; macOS: brew install cosign)"
tmp=$(mktemp -d "${TMPDIR:-/tmp}/eq-base-pins.XXXXXX"); trap 'rm -rf "$tmp"' EXIT
rc=0
"$COSIGN" verify "$REF" --certificate-oidc-issuer "$ISSUER" --certificate-identity "$IDENTITY" > "$tmp/out" 2> "$tmp/err" || rc=$?
[ "$rc" = 0 ] || { sed 's/^/  cosign: /' "$tmp/err" >&2; die "cosign verify $REF failed (rc $rc) for identity $IDENTITY, issuer $ISSUER"; }
# every verified payload must name the pinned digest (cosign prints a JSON array of the verified simple-signing payloads)
python3 -I - "$tmp/out" "$DIGEST" <<'PY' || die "cosign's verified payloads do not all name the pinned digest $DIGEST"
import json, sys
try:
    with open(sys.argv[1]) as f:
        data = json.load(f)
except (OSError, ValueError):
    sys.exit(1)
if not isinstance(data, list) or not data:
    sys.exit(1)
for item in data:
    d = ((item or {}).get("critical") or {}).get("image") or {}
    if not isinstance(d, dict) or d.get("docker-manifest-digest") != sys.argv[2]:
        sys.exit(1)
PY
echo "BASE distroless-cc $REF arm64 $ARM layers $nl cosign=OK"
