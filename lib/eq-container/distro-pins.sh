#!/usr/bin/env bash
# distro-pins.sh: re-derive on the host the pins of the four distro-package tools of the core images (TOOLS.toml version and
# sha256 of bash, perl, jq and busybox; BUSYBOX_SHA256 in PINS) from the official artifacts the builder itself uses, checking
# every hash on the way, and compare them with what is pinned. Never builds and never edits a file: it downloads into a
# private temp dir (removed at exit). Run it from a normal terminal (an agent's sandbox cannot reach snapshot.debian.org).
# Bash 3.2 (macOS) or Linux; needs curl, gpgv, xz, ar, tar and shasum or sha256sum (macOS: brew install gnupg xz).
#   bash lib/eq-container/distro-pins.sh
# Trust chain (the sources of Dockerfile.minimal's builder stages):
#   bash, perl   come from the base image (BASE_IMAGE), not from the snapshot: read from its arm64 layer, downloaded from
#                BASE_LAYER_URL and refused unless it hashes to BASE_LAYER_SHA256 (PINS: the layer digest of BASE_IMAGE's
#                arm64 manifest). Versions from the layer's var/lib/dpkg/status.
#   busybox, jq  apt installs them from APT_SNAPSHOT (suite trixie, component main, arm64). InRelease must verify with gpgv
#                against the Debian archive keyring OF THAT LAYER (the keyring apt uses in the builder; gpgv must exit 0, so
#                a signature by a key that keyring lacks fails closed), and only gpgv's output (the signed text) is read:
#                Codename trixie, Version equal to the layer's etc/debian_version (no other point release is accepted),
#                one SHA256 line for Packages.xz, which must match it; one arm64 stanza per package, whose .deb must match
#                its SHA256 and Size; the installed file (usr/bin/busybox, usr/bin/jq) is read from the .deb's data tarball
#                and must be a regular file.
# Output: one `TOOL name version sha256` line per tool (build.sh --resolve-tools' format) with the pinned value beside it,
# then PROVENANCE lines (URLs, hashes, the InRelease date). Nothing is printed on stdout before every check has passed.
# Exit: 0 all four derived and equal to the pins | 1 a check failed, or a pin differs from the derived value | 2 usage or a
# malformed PINS value | 13 derived, and a pin is still a placeholder: pin the TOOL values (TOOLS.toml version, sha256 and
# checksum_source; BUSYBOX_SHA256 in PINS and Dockerfile.minimal), then run this again.
set -euo pipefail
here=$(cd "$(dirname "$0")" && pwd -P)
# shellcheck disable=SC1091
. "$here/tools.sh"

case "${1:-}" in
  "") ;;
  -h|--help) sed -n '2,23p' "$0"; exit 0;;
  *) echo "distro-pins.sh: unknown argument: $1" >&2; exit 2;;
esac

SUITE=trixie; COMPONENT=main; ARCH=arm64
# tool  package (in the layer or the snapshot)  installed path (relative to /)
BASE_TOOLS="bash:bash:usr/bin/bash perl:perl-base:usr/bin/perl"
SNAP_TOOLS="busybox:busybox-static:usr/bin/busybox jq:jq:usr/bin/jq"

die() { echo "distro-pins.sh: FAILED: $*" >&2; exit 1; }
bad_pin() { echo "distro-pins.sh: PINS: $*" >&2; exit 2; }
pin() { sed -n "s/^$1=//p" "$here/PINS" | head -n 1; }
# literal character lists (tools.sh tm_only), never a bracket range: bash 3.2 ranges follow the locale's collation
is_hex64() { tm_is_hex64 "$1"; }
is_num() { tm_only "$1" "$TM_DIGITS"; }
is_debver() { tm_only "$1" "$TM_LOWER$TM_UPPER$TM_DIGITS.+~:-"; }
file_sha() { tm_sha256_stdin < "$1"; }
file_size() { wc -c < "$1" | tr -d ' '; }
regular() { [ -f "$1" ] && [ ! -L "$1" ]; }

tm_load "$here/TOOLS.toml" || exit 2
SNAP=$(pin APT_SNAPSHOT); LAYER_URL=$(pin BASE_LAYER_URL); LAYER_SHA=$(pin BASE_LAYER_SHA256)
{ [ "${#SNAP}" = 16 ] && [ "${SNAP:8:1}" = T ] && [ "${SNAP:15:1}" = Z ] && is_num "${SNAP:0:8}${SNAP:9:6}"; } \
  || bad_pin "APT_SNAPSHOT '$SNAP' is not YYYYMMDDTHHMMSSZ"
is_hex64 "$LAYER_SHA" || bad_pin "BASE_LAYER_SHA256 is not 64 lowercase hex"
case "$LAYER_URL" in https://*) ;; *) bad_pin "BASE_LAYER_URL must be an https:// URL";; esac
case "$LAYER_URL" in https://*@*) bad_pin "BASE_LAYER_URL holds credentials";; esac
tm_only "$LAYER_URL" "$TM_LOWER$TM_UPPER$TM_DIGITS._~:/%+-" || bad_pin "BASE_LAYER_URL holds characters it may not"
BB_PIN=$(pin BUSYBOX_SHA256)
case "$BB_PIN" in ""|UNSET|*TODO*) ;; *) is_hex64 "$BB_PIN" || bad_pin "BUSYBOX_SHA256 is neither a placeholder nor 64 lowercase hex";; esac
for c in curl gpgv xz ar tar; do
  command -v "$c" >/dev/null 2>&1 || die "$c not found (macOS: brew install gnupg xz; ar comes with the Xcode command line tools)"
done
SNAPURL="https://snapshot.debian.org/archive/debian/$SNAP"

W=$(mktemp -d "${TMPDIR:-/tmp}/eq-distro-pins.XXXXXX")
chmod 700 "$W"
trap 'rm -rf "$W"' EXIT
fetch() { # URL NAME: https only, redirects included; the file lands in the temp dir
  curl --proto '=https' --proto-redir '=https' --tlsv1.2 -fsSL --retry 3 --max-time 900 -o "$W/$2" "$1" || die "download failed: $1"
}
stanza() { # FILE PACKAGE ARCH(or "") -> the fields of PACKAGE's one stanza (ARCH: only that Architecture; "": Status installed)
  awk -v p="$2" -v a="$3" 'BEGIN { RS = ""; c = 0 }
    { n = split($0, l, "\n"); pk = ""; ar = ""; v = ""; f = ""; s = ""; h = ""; st = ""
      for (i = 1; i <= n; i++) {
        if (l[i] ~ /^Package: /) pk = substr(l[i], 10)
        else if (l[i] ~ /^Architecture: /) ar = substr(l[i], 15)
        else if (l[i] ~ /^Version: /) v = substr(l[i], 10)
        else if (l[i] ~ /^Filename: /) f = substr(l[i], 11)
        else if (l[i] ~ /^Size: /) s = substr(l[i], 7)
        else if (l[i] ~ /^SHA256: /) h = substr(l[i], 9)
        else if (l[i] ~ /^Status: /) st = substr(l[i], 9)
      }
      if (pk != p) next
      if (a != "" && ar != a) next
      if (a == "" && st != "install ok installed") next
      print v, f, s, h; c++ }
    END { exit c == 1 ? 0 : 1 }' "$1"
}

# ---- 1. the base layer: bash, perl, the Debian archive keyring, the point release ----------------------------------------
fetch "$LAYER_URL" layer.tar.gz
h=$(file_sha "$W/layer.tar.gz")
[ "$h" = "$LAYER_SHA" ] || die "the base layer hashes to $h, PINS BASE_LAYER_SHA256 is $LAYER_SHA"
mkdir "$W/layer"
KEYRING=usr/share/keyrings/debian-archive-keyring.pgp
tar -xzf "$W/layer.tar.gz" -C "$W/layer" usr/bin/bash usr/bin/perl var/lib/dpkg/status etc/debian_version "$KEYRING" \
  || die "the base layer lacks a file this script reads"
DEBIAN_VERSION=$(head -n 1 "$W/layer/etc/debian_version")
case "$DEBIAN_VERSION" in *.*) ;; *) die "etc/debian_version of the layer is '$DEBIAN_VERSION'";; esac
tm_only "$DEBIAN_VERSION" "$TM_DIGITS." || die "etc/debian_version of the layer is '$DEBIAN_VERSION'"
OUT=""
for spec in $BASE_TOOLS; do
  t=${spec%%:*}; rest=${spec#*:}; pkg=${rest%%:*}; path=${rest#*:}
  regular "$W/layer/$path" || die "$path in the layer is not a regular file"
  v=$(stanza "$W/layer/var/lib/dpkg/status" "$pkg" "") || die "the layer's dpkg status has no single installed $pkg"
  v=${v%% *}
  is_debver "$v" || die "the layer's $pkg version '$v' is malformed"
  OUT="$OUT$t $v $(file_sha "$W/layer/$path")
"
done

# ---- 2. the snapshot: InRelease (signed), Packages.xz, the two .debs ------------------------------------------------------
fetch "$SNAPURL/dists/$SUITE/InRelease" InRelease
mkdir -m 700 "$W/gnupg"
gpgv --homedir "$W/gnupg" --keyring "$W/layer/$KEYRING" --output "$W/Release" "$W/InRelease" 2> "$W/gpgv.log" \
  || { cat "$W/gpgv.log" >&2; die "InRelease does not verify against the Debian archive keyring of the base layer"; }
rel() { sed -n "s/^$1: //p" "$W/Release" | head -n 1; }
[ "$(rel Codename)" = "$SUITE" ] || die "InRelease is for Codename '$(rel Codename)', not $SUITE"
[ "$(rel Version)" = "$DEBIAN_VERSION" ] || die "InRelease is Debian $(rel Version) but the base image is $DEBIAN_VERSION: re-pin BASE_IMAGE, BASE_LAYER_* and APT_SNAPSHOT to one point release"
idx="$COMPONENT/binary-$ARCH/Packages.xz"
line=$(awk -v p="$idx" '/^[^ ]/ { sec = ($0 == "SHA256:"); next } sec && $3 == p { print $1, $2; c++ } END { exit c == 1 ? 0 : 1 }' "$W/Release") \
  || die "the signed InRelease has no single SHA256 line for $idx"
read -r pxsha pxsize <<EOF
$line
EOF
{ is_hex64 "$pxsha" && is_num "$pxsize"; } || die "malformed SHA256 line for $idx: $line"
fetch "$SNAPURL/dists/$SUITE/$idx" Packages.xz
{ [ "$(file_sha "$W/Packages.xz")" = "$pxsha" ] && [ "$(file_size "$W/Packages.xz")" = "$pxsize" ]; } || die "Packages.xz does not match its signed SHA256 line"
xz -dc "$W/Packages.xz" > "$W/Packages" || die "Packages.xz does not decompress"
PROV=""
for spec in $SNAP_TOOLS; do
  t=${spec%%:*}; rest=${spec#*:}; pkg=${rest%%:*}; path=${rest#*:}
  st=$(stanza "$W/Packages" "$pkg" "$ARCH") || die "Packages has no single $ARCH stanza for $pkg"
  read -r v fn sz dsha <<EOF
$st
EOF
  is_debver "$v" || die "$pkg: malformed Version '$v'"
  { is_hex64 "$dsha" && is_num "$sz"; } || die "$pkg: malformed SHA256 or Size"
  case "$fn" in pool/"$COMPONENT"/*/*/*_"$ARCH".deb) ;; *) die "$pkg: unexpected Filename '$fn'";; esac
  case "$fn" in *..*) die "$pkg: unexpected Filename '$fn'";; esac
  tm_only "$fn" "$TM_LOWER$TM_UPPER$TM_DIGITS._+~/-" || die "$pkg: unexpected Filename '$fn'"
  fetch "$SNAPURL/$fn" "$t.deb"
  { [ "$(file_sha "$W/$t.deb")" = "$dsha" ] && [ "$(file_size "$W/$t.deb")" = "$sz" ]; } || die "$fn does not match its Packages SHA256 and Size"
  m=$(cd "$W" && ar t "$t.deb" | grep -E '^data\.tar(\.(xz|gz|zst|bz2))?$') || die "$fn has no data tarball"
  [ "$(printf '%s\n' "$m" | wc -l | tr -d ' ')" = 1 ] || die "$fn has more than one data tarball"
  (cd "$W" && ar p "$t.deb" "$m") > "$W/$t.$m" || die "cannot read $m from $fn"
  mkdir "$W/$t.x"
  tar -xf "$W/$t.$m" -C "$W/$t.x" "./$path" 2>/dev/null || tar -xf "$W/$t.$m" -C "$W/$t.x" "$path" 2>/dev/null \
    || die "$fn does not install $path"
  regular "$W/$t.x/$path" || die "$path in $fn is not a regular file"
  OUT="$OUT$t $v $(file_sha "$W/$t.x/$path")
"
  PROV="${PROV}PROVENANCE deb $t $SNAPURL/$fn sha256=$dsha size=$sz
"
done

# ---- 3. report: the derived values beside the pinned ones ---------------------------------------------------------------
rc=0
while read -r t v s; do
  [ -n "$t" ] || continue
  mv=$(tm_get tool "$t" version); ms=$(tm_get tool "$t" sha256); extra=""
  if [ "$t" = busybox ]; then extra=$BB_PIN; case "$extra" in ""|UNSET|*TODO*) extra=PLACEHOLDER;; esac; fi
  if [ "$mv" = "$v" ] && [ "$ms" = "$s" ] && { [ "$t" != busybox ] || [ "$extra" = "$s" ]; }; then st="pinned: same"
  elif [ "$mv" = PLACEHOLDER ] || [ "$ms" = PLACEHOLDER ] || [ "$extra" = PLACEHOLDER ]; then
    st="pinned: PLACEHOLDER"; [ "$rc" = 1 ] || rc=13
  else st="pinned: DIFFERS (TOOLS.toml $mv $ms${extra:+, PINS BUSYBOX_SHA256 $extra})"; rc=1; fi
  printf 'TOOL %s %s %s   %s\n' "$t" "$v" "$s" "$st"
done <<EOF
$OUT
EOF
echo "PROVENANCE base_layer $LAYER_URL sha256=$LAYER_SHA debian_version=$DEBIAN_VERSION"
echo "PROVENANCE InRelease $SNAPURL/dists/$SUITE/InRelease sha256=$(file_sha "$W/InRelease") date='$(rel Date)' version=$(rel Version) gpgv=OK keyring=base-layer:/$KEYRING"
echo "PROVENANCE Packages.xz $SNAPURL/dists/$SUITE/$idx sha256=$pxsha size=$pxsize"
printf '%s' "$PROV"
case "$rc" in
  0) echo "DISTRO-PINS: OK (derived $(date -u +%FT%TZ); every pin equals the verified value)";;
  13) echo "DISTRO-PINS: PENDING (derived $(date -u +%FT%TZ); pin the PLACEHOLDER rows with the values above)";;
  *) echo "DISTRO-PINS: DIFFERS (derived $(date -u +%FT%TZ); a pin is not the verified value)";;
esac
exit "$rc"
