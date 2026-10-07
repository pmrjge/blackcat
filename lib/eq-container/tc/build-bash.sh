#!/bin/sh
# shellcheck disable=SC2016  # single-quoted scripts are run by the built bash, never expanded here
# build-bash.sh MODE DEST   (POSIX sh: runs in the discarded `bash` / `bash-report` stages of Dockerfile.minimal, on the
# digest-pinned Alpine image MUSL_BUILDER_IMAGE, never at run time). Recipe of the TOOLS.toml tool `bash` (built-from-source,
# USER decision 2026-10-06: static GNU bash from the GPG-signed GNU source, DESIGN_DISTROLESS.md section 4.2).
#   MODE build    every pin below must be set: the source, the patches and the built binary must hash to them (exit 1 if not)
#   MODE resolve  pins may be placeholders: after every signature has verified, print `PIN KEY VALUE` for the three hashes
#                 (build.sh --resolve-tools reads them; --write-pin writes them: trust on first use AFTER the signature check)
# Env (the Dockerfile ARGs, values from PINS): BASH_BASELINE (5.3), BASH_PATCHLEVEL (20), BASH_GPG_FPR (the primary key
# fingerprint, 40 uppercase hex), BASH_SRC_SHA256 (bash-$BASELINE.tar.gz), BASH_PATCHES_SHA256 (sha256 of the ordered
# `sha256sum bash53-001 ... bash53-0NN` listing; on a Mac: shasum -a 256 bash53-0?? | shasum -a 256), BASH_BIN_SHA256 (DEST/bin/bash).
# Trust: the key is fetched by fingerprint from keyserver.ubuntu.com (an untrusted transport): the keyring must then hold
# exactly one primary key, the pinned one, and every file (tarball and each patch) must carry a valid signature whose
# PRIMARY key fingerprint (VALIDSIG's last field) is the pin; a bad, revoked or unknown-key signature stops here, before
# anything is unpacked. apk resolves its packages within Alpine 3.24 (floating), which is why the output is pinned too.
set -eu
mode=${1:?mode build|resolve}; dest=${2:?install prefix}
fail() { echo "build-bash: FAILED: $*" >&2; exit 1; }
unset_pin() { case "$1" in ""|UNSET|*TODO*) return 0;; esac; return 1; }
hex64() { case "$1" in *[!0123456789abcdef]*) return 1;; esac; [ "${#1}" = 64 ]; }
case "$mode" in build|resolve) ;; *) fail "mode must be build or resolve";; esac
: "${BASH_BASELINE:?}" "${BASH_PATCHLEVEL:?}" "${BASH_GPG_FPR:?}"
BASH_SRC_SHA256=${BASH_SRC_SHA256:-UNSET}; BASH_PATCHES_SHA256=${BASH_PATCHES_SHA256:-UNSET}; BASH_BIN_SHA256=${BASH_BIN_SHA256:-UNSET}
case "$BASH_BASELINE" in [0-9]*.[0-9]*) ;; *) fail "BASH_BASELINE '$BASH_BASELINE' is not MAJOR.MINOR";; esac
case "$BASH_BASELINE" in *[!0123456789.]*|*.*.*) fail "BASH_BASELINE '$BASH_BASELINE' is not MAJOR.MINOR";; esac
case "$BASH_PATCHLEVEL" in ""|*[!0123456789]*) fail "BASH_PATCHLEVEL '$BASH_PATCHLEVEL' is not a number";; esac
[ "${#BASH_PATCHLEVEL}" -le 3 ] || fail "BASH_PATCHLEVEL '$BASH_PATCHLEVEL' is too long"
case "$BASH_GPG_FPR" in *[!0123456789ABCDEF]*) fail "BASH_GPG_FPR is not 40 uppercase hex";; esac
[ "${#BASH_GPG_FPR}" = 40 ] || fail "BASH_GPG_FPR is not 40 uppercase hex"
for k in BASH_SRC_SHA256 BASH_PATCHES_SHA256 BASH_BIN_SHA256; do
  v=""; eval "v=\$$k"
  if unset_pin "$v"; then
    [ "$mode" = resolve ] || fail "$k is a placeholder in PINS: run bash lib/eq-container/build.sh --resolve-tools (it checks the GPG signatures and prints the value)"
  else
    hex64 "$v" || fail "$k is neither a placeholder nor 64 lowercase hex"
  fi
done

w=$(mktemp -d); cd "$w"
GNUPGHOME="$w/gnupg"; export GNUPGHOME; mkdir -m 700 "$GNUPGHOME"
get() { curl --proto '=https' --proto-redir '=https' --tlsv1.2 -fsSL --retry 5 -o "$1" "$2"; }
gpg --batch --keyserver hkps://keyserver.ubuntu.com --recv-keys "$BASH_GPG_FPR"
prim=$(gpg --batch --with-colons --fingerprint --list-keys | awk -F: '$1 == "pub" { p = 1; next } p && $1 == "fpr" { print $10; p = 0 }')
[ "$prim" = "$BASH_GPG_FPR" ] || fail "the keyring holds the primary key(s) '$prim', want exactly $BASH_GPG_FPR"
verify() { # FILE: FILE.sig must be a good signature whose primary key is the pinned one
  out=$(gpg --batch --status-fd 1 --verify "$1.sig" "$1" 2>/dev/null) || fail "the signature of $1 does not verify"
  if printf '%s\n' "$out" | grep -Eq '^\[GNUPG:\] (BADSIG|ERRSIG|REVKEYSIG|EXPSIG|NO_PUBKEY) '; then fail "bad signature status for $1"; fi
  printf '%s\n' "$out" | grep -Eq '^\[GNUPG:\] (GOODSIG|EXPKEYSIG) ' || fail "no good signature on $1"
  printf '%s\n' "$out" | awk -v f="$BASH_GPG_FPR" '$1 == "[GNUPG:]" && $2 == "VALIDSIG" && $NF == f { ok = 1 } END { exit !ok }' \
    || fail "$1 is not signed by the primary key $BASH_GPG_FPR"
}
mm=$(printf '%s' "$BASH_BASELINE" | tr -d .)
base="https://ftp.gnu.org/gnu/bash"
get bash.tar.gz "$base/bash-$BASH_BASELINE.tar.gz"; get bash.tar.gz.sig "$base/bash-$BASH_BASELINE.tar.gz.sig"
verify bash.tar.gz
: > patches.sha256
i=1
while [ "$i" -le "$BASH_PATCHLEVEL" ]; do
  p="bash$mm-$(printf '%03d' "$i")"
  get "$p" "$base/bash-$BASH_BASELINE-patches/$p"; get "$p.sig" "$base/bash-$BASH_BASELINE-patches/$p.sig"
  verify "$p"
  sha256sum "$p" >> patches.sha256
  i=$((i + 1))
done
echo "SIGNATURES OK: bash-$BASH_BASELINE.tar.gz and $BASH_PATCHLEVEL patches, primary key $BASH_GPG_FPR"
src=$(sha256sum bash.tar.gz | cut -d' ' -f1)
pat=$(sha256sum < patches.sha256 | cut -d' ' -f1)
check() { # KEY COMPUTED PINNED
  if [ "$mode" = resolve ]; then
    if unset_pin "$3"; then st="pinned: PLACEHOLDER"; elif [ "$2" = "$3" ]; then st="pinned: same"; else st="pinned: DIFFERS ($3)"; fi
    echo "PIN $1 $2 $st"
  elif [ "$2" != "$3" ]; then fail "$1: computed $2, PINS says $3"; fi
}
check BASH_SRC_SHA256 "$src" "$BASH_SRC_SHA256"
check BASH_PATCHES_SHA256 "$pat" "$BASH_PATCHES_SHA256"

tar -xzf bash.tar.gz
cd "bash-$BASH_BASELINE"
i=1
while [ "$i" -le "$BASH_PATCHLEVEL" ]; do
  patch -p0 -s -i "$w/bash$mm-$(printf '%03d' "$i")"
  i=$((i + 1))
done
# musl has no usable brk/sbrk, so bash's own malloc is off (the official bash image does the same); no NLS catalogs
./configure --enable-static-link --without-bash-malloc --disable-nls >/dev/null || { cat config.log >&2; fail "configure"; }
make -j"$(nproc)" >/dev/null
strip bash
mkdir -p "$dest/bin"
install -m 0755 bash "$dest/bin/bash"
b="$dest/bin/bash"
if readelf -lW "$b" | grep -q 'Requesting program interpreter' || readelf -dW "$b" | grep -q '(NEEDED)'; then fail "$b is not static"; fi
[ "$("$b" -c 'echo "${BASH_VERSINFO[0]}.${BASH_VERSINFO[1]}.${BASH_VERSINFO[2]}"')" = "$BASH_BASELINE.$BASH_PATCHLEVEL" ] \
  || fail "$b reports $("$b" --version | head -n 1)"
# network redirections compiled in (probe_inner.sh's network rows use them): a refused loopback connect, never a missing file
err=$("$b" -c 'exec 3<>/dev/tcp/127.0.0.1/1' 2>&1) && fail "/dev/tcp/127.0.0.1/1 connected"
printf '%s' "$err" | grep -Eqi 'refused|unreachable' || fail "/dev/tcp redirection missing: $err"
bin=$(sha256sum "$b" | cut -d' ' -f1)
check BASH_BIN_SHA256 "$bin" "$BASH_BIN_SHA256"
echo "bash $("$b" --version | head -n 1): $b sha256 $bin"
cd /; rm -rf "$w"
