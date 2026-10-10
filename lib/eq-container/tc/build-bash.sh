#!/bin/sh
# shellcheck disable=SC2016  # single-quoted scripts are run by the built bash, never expanded here
# build-bash.sh MODE DEST   (POSIX sh: runs in the discarded `bash` / `bash-report` stages of Dockerfile.minimal, on the
# digest-pinned Alpine image MUSL_BUILDER_IMAGE, never at run time). Recipe of the TOOLS.toml tool `bash` (built-from-source,
# USER decision 2026-10-06: static GNU bash from the GPG-signed GNU source, DESIGN_DISTROLESS.md section 4.2).
#   MODE build    every pin below must be set: the source, the patches and the built binary must hash to them (exit 1 if not)
#   MODE resolve  pins may be placeholders: after every signature has verified, print `PIN KEY VALUE` for the three hashes
#                 (build.sh --resolve-tools keeps them in a report; --write-pin pins the values that two or more reports of
#                 this recipe agree on: trust on first use AFTER the signature check)
# Env (the Dockerfile ARGs, values from PINS): BASH_BASELINE (5.3), BASH_PATCHLEVEL (20), BASH_GPG_FPR (the primary key
# fingerprint, 40 uppercase hex), BASH_SRC_SHA256 (bash-$BASELINE.tar.gz), BASH_PATCHES_SHA256 (sha256 of the ordered
# `sha256sum bash53-001 ... bash53-0NN` listing; on a Mac: shasum -a 256 bash53-0?? | shasum -a 256), BASH_BIN_SHA256 (DEST/bin/bash).
# Trust: the key is fetched by fingerprint from keyserver.ubuntu.com (an untrusted transport): the keyring must then hold
# exactly one primary key, the pinned one, and every file (tarball and each patch) must carry a valid signature whose
# PRIMARY key fingerprint (VALIDSIG's last field) is the pin; a bad, revoked or unknown-key signature stops here, before
# anything is unpacked. apk resolves its packages within Alpine 3.24 (floating), which is why the output is pinned too.
# Reproducible build (USER decision 2026-10-10: three builds of the same sources gave three different binaries). The likely
# cause, read from the earlier recipe and the toolchain (no two binaries were kept to diff, so unverified until
# repro-check.sh runs): bash's configure defaults CFLAGS to `-g -O2`, the tree was unpacked in a fresh mktemp directory, so the
# debug info named a different build directory on every run; Alpine's gcc is configured with --enable-linker-build-id, so
# the linker stamped a build id hashed over the whole unstripped output, debug info included; and `strip` drops the debug
# sections but keeps .note.gnu.build-id. Same code, a different 20-byte id. Hence, below: no -g (CFLAGS is set), a fixed
# build path mapped to /src, no build id (link option, strip -R, then refused if present), no .comment. The other settings
# are defensive (no evidence that they mattered): SOURCE_DATE_EPOCH, TZ, LC_ALL, -frandom-seed and a serial make. `DIAG`
# lines (toolchain versions, the hash of config.h, of every object and of the binary before strip) let two builds be
# compared stage by stage (repro-check.sh). BASH_REPRO_DUMP=1 (resolve mode, set by build.sh --resolve-tools --repro-dump)
# also prints the gzip+base64 of the built binary after everything else.
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
    [ "$mode" = resolve ] || fail "$k is a placeholder in PINS: run bash lib/eq-container/repro-check.sh (GPG-checked builds of the bash-report stage), then bash lib/eq-container/build.sh --resolve-tools --write-pin"
  else
    hex64 "$v" || fail "$k is neither a placeholder nor 64 lowercase hex"
  fi
done

case "${BASH_REPRO_DUMP:-0}" in 0|1) ;; *) fail "BASH_REPRO_DUMP must be 0 or 1";; esac
# the build tree: a fixed path, the same on every run (no Dockerfile ARG sets BASH_BUILD_ROOT: it exists for the tests; whatever
# it is, the compiler maps the tree to /src)
root=${BASH_BUILD_ROOT:-/build}
case "$root" in /?*) ;; *) fail "BASH_BUILD_ROOT '$root' is not an absolute path";; esac
case "$root" in *[!A-Za-z0-9._/-]*|*//*|*/../*|*/..|*/./*|*/.) fail "BASH_BUILD_ROOT '$root' holds an unexpected character";; esac
# downloads, the keyring and the signatures live in a random directory: nothing compiled is ever there
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

# ---- the build tree, under the fixed root checked above (a leftover tree of an earlier run is removed first)
bd="$root/bash-$BASH_BASELINE"
rm -rf "$bd"; mkdir -p "$root"
tar -xzf "$w/bash.tar.gz" -C "$root"
cd "$bd"
i=1
while [ "$i" -le "$BASH_PATCHLEVEL" ]; do
  patch -p0 -s -i "$w/bash$mm-$(printf '%03d' "$i")"
  i=$((i + 1))
done
# Environment. SOURCE_DATE_EPOCH is a constant tied to the pinned release (gcc's __DATE__/__TIME__ and every tool that honours
# it read it); the date below is the one the repo records for patch 020 of bash 5.3 (DESIGN_DISTROLESS.md, ftp.gnu.org
# listing). Any other release gets 0 (still a constant: it is the constancy that matters, not the value). The file mtimes of
# the tree are NOT normalised: make compares them to decide what to regenerate, and tar and patch set them in the same order on
# every run (bash53-016 patches configure.ac, then configure: configure is never the older one). None of the 20 patches
# touches parse.y or y.tab.c (their headers, read 2026-10-10), and the compiler warnings of a report carry the shipped
# y.tab.c's own #line paths: bison does not run, the shipped parser is compiled.
case "$BASH_BASELINE.$BASH_PATCHLEVEL" in
  5.3.20) SOURCE_DATE_EPOCH=1789344000;;      # 2026-09-14T00:00:00Z
  *) SOURCE_DATE_EPOCH=0;;
esac
TZ=UTC; LC_ALL=C; LANG=C
export SOURCE_DATE_EPOCH TZ LC_ALL LANG
unset LANGUAGE LC_MESSAGES LC_CTYPE LC_COLLATE LC_TIME MAKEFLAGS MAKELEVEL MFLAGS GCC_COLORS CPPFLAGS CXXFLAGS CFLAGS LDFLAGS LIBS
umask 022
echo "REPRO SOURCE_DATE_EPOCH=$SOURCE_DATE_EPOCH TZ=$TZ LC_ALL=$LC_ALL build_dir=$bd make=-j1"
# CFLAGS replaces configure's default `-g -O2`: no debug info (it named the build directory, and the build id hashed it).
# -ffile-prefix-map covers __FILE__ and assert() strings (and debug paths, were -g ever added); -fdebug-prefix-map is the
# older spelling; -frandom-seed fixes the names gcc would otherwise draw at random; --build-id=none keeps the linker (Alpine's
# gcc passes --build-id by default) from stamping an id
CFLAGS="-O2 -ffile-prefix-map=$bd=/src -fdebug-prefix-map=$bd=/src -frandom-seed=bash-$BASH_BASELINE.$BASH_PATCHLEVEL"
LDFLAGS="-Wl,--build-id=none"
export CFLAGS LDFLAGS
# toolchain provenance (apk floats within Alpine 3.24: a difference between two runs may be here)
for t in gcc ld bison make patch; do
  command -v "$t" >/dev/null 2>&1 && echo "DIAG tool $t: $("$t" --version 2>&1 | head -n 1)" || echo "DIAG tool $t: absent"
done
if command -v apk >/dev/null 2>&1; then apk info -v 2>/dev/null | LC_ALL=C sort | sed 's/^/DIAG apk /'; fi
# musl has no usable brk/sbrk, so bash's own malloc is off (the official bash image does the same); no NLS catalogs
./configure --enable-static-link --without-bash-malloc --disable-nls >/dev/null || { cat config.log >&2; fail "configure"; }
echo "DIAG config.h $(sha256sum config.h | cut -d' ' -f1)"
make -j1 >/dev/null
for f in y.tab.c y.tab.h version.h; do [ ! -f "$f" ] || echo "DIAG $f $(sha256sum "$f" | cut -d' ' -f1)"; done
find . -name '*.o' -type f | LC_ALL=C sort | while IFS= read -r f; do echo "DIAG obj $(sha256sum "$f" | cut -d' ' -f1) $f"; done
echo "DIAG unstripped $(sha256sum bash | cut -d' ' -f1)"
strip --strip-all -R .comment -R .note -R .note.gnu.build-id bash
mkdir -p "$dest/bin"
install -m 0755 bash "$dest/bin/bash"
b="$dest/bin/bash"
if readelf -lW "$b" | grep -q 'Requesting program interpreter' || readelf -dW "$b" | grep -q '(NEEDED)'; then fail "$b is not static"; fi
# the stripped binary carries no compiler ident and no build id (either would make two builds differ or hide that they do)
if readelf -SW "$b" | grep -q '\.comment'; then fail "$b still has a .comment section"; fi
if readelf -nW "$b" | grep -q 'Build ID'; then fail "$b still has a build id"; fi
[ "$("$b" -c 'echo "${BASH_VERSINFO[0]}.${BASH_VERSINFO[1]}.${BASH_VERSINFO[2]}"')" = "$BASH_BASELINE.$BASH_PATCHLEVEL" ] \
  || fail "$b reports $("$b" --version | head -n 1)"
# network redirections compiled in (probe_inner.sh's network rows use them): a refused loopback connect, never a missing file
err=$("$b" -c 'exec 3<>/dev/tcp/127.0.0.1/1' 2>&1) && fail "/dev/tcp/127.0.0.1/1 connected"
printf '%s' "$err" | grep -Eqi 'refused|unreachable' || fail "/dev/tcp redirection missing: $err"
echo "DIAG BASH_VERSION $("$b" -c 'echo "$BASH_VERSION"' 2>/dev/null || true)"
bin=$(sha256sum "$b" | cut -d' ' -f1)
check BASH_BIN_SHA256 "$bin" "$BASH_BIN_SHA256"
echo "bash $("$b" --version | head -n 1): $b sha256 $bin"
if [ "${BASH_REPRO_DUMP:-0}" = 1 ] && [ "$mode" = resolve ]; then   # last: a log limit clips the tail, never the lines above
  echo "BINB64 BEGIN $bin"
  gzip -c < "$b" | base64 | sed 's/^/BINB64 DATA /'     # from stdin: no file name or mtime in the gzip header
  echo "BINB64 END $bin"
fi
cd /; rm -rf "$w" "$bd"
