#!/bin/bash
# shellcheck disable=SC2016
# mkrootfs-tc.sh IMAGE   (runs in a discarded assemble-* stage of Dockerfile.toolchains; never at run time)
# /rootfs = the ONE layer an extension image adds to its base (TOOLS.toml [[image]] base; USER decision 2026-10-06,
# DESIGN_DISTROLESS.md section 3):
#   distroless-cc  the pinned distroless cc image, copied to /base-rootfs by the Dockerfile: every dynamic ELF of the tool trees
#                  must resolve against base + layer (the loader's --list inside a chroot); a library from anywhere else is an
#                  ERROR naming it, never a copy ("no third source of shared objects"); /etc/passwd,group = the base's + eq
#   scratch        nothing below the layer: every AArch64 ELF must be static (no interpreter, no NEEDED); the layer gets
#                  /etc/passwd,group (root, eq 10001), /tmp (1777) and the mount points
# The layer holds the tool trees tc/fetch-tool.sh installed (pruned per TOOLS.toml), /opt/eq/TOOLS.lock (+ .sha256), IMAGE_KIND,
# PROVENANCE-tc.txt and (distroless-cc) BASE_EXECUTABLES.txt; no shell, package manager, docs, man pages or headers. A foreign-architecture ELF inside a tool tree (Go's
# testdata, for one) is reported as a NOTE and skipped; any setuid/setgid file fails. UNVERIFIED until a build passes.
set -euo pipefail
what=${1:?image name}
T=${EQ_TOOLS_DIR:-/opt/eq-tools}
R=/rootfs; B=/base-rootfs; C=/check-root
die() { echo "mkrootfs-tc: ERROR: $*" >&2; exit 1; }
# shellcheck disable=SC1091
. "$T/tools.sh"
tm_load "$T/TOOLS.toml"
tm_has image "$what" || { echo "mkrootfs-tc: $what is not an [[image]] of TOOLS.toml" >&2; exit 2; }
base=$(tm_get image "$what" base)
case "$base" in
  distroless-cc) [ -d "$B/usr" ] && [ -d "$B/etc" ] || die "$what: base distroless-cc but $B holds no base filesystem"
                 [ ! -e "$B/busybox" ] || die "the base holds /busybox: a distroless debug image is not allowed"
                 : "${DISTROLESS_CC:?}" "${DISTROLESS_CC_ARM64:?}";;
  scratch) [ ! -e "$B" ] || die "$what: base scratch but $B exists (the Dockerfile must not copy a base for it)";;
  *) echo "mkrootfs-tc: $what: base '$base' is neither distroless-cc nor scratch" >&2; exit 2;;
esac
rm -rf "$R"; mkdir -p "$R/opt/eq" "$R/etc"
mkdir -p "$R/work"
if [ "$base" = scratch ]; then
  mkdir -p "$R/tmp" "$R/proc" "$R/dev" "$R/sys"; chmod 1777 "$R/tmp"
  : > "$R/etc/hosts"; : > "$R/etc/resolv.conf"; : > "$R/etc/hostname"
  printf 'root:x:0:0:root:/:/sbin/nologin\neq:x:10001:10001:eq:/tmp:/sbin/nologin\n' > "$R/etc/passwd"
  printf 'root:x:0:\neq:x:10001:\n' > "$R/etc/group"
else
  for d in tmp proc dev sys; do [ -e "$B/$d" ] || mkdir -p "$R/$d"; done
  [ -e "$B/tmp" ] || chmod 1777 "$R/tmp"
  for f in hosts resolv.conf hostname; do [ -e "$B/etc/$f" ] || : > "$R/etc/$f"; done
  ! awk -F: '$1 == "eq" || $3 == "10001"' "$B/etc/passwd" 2>/dev/null | grep -q . || die "the base already has a user eq or uid 10001"
  { cat "$B/etc/passwd" 2>/dev/null || printf 'root:x:0:0:root:/root:/sbin/nologin\n'; printf 'eq:x:10001:10001:eq:/tmp:/sbin/nologin\n'; } > "$R/etc/passwd"
  { cat "$B/etc/group" 2>/dev/null || printf 'root:x:0:\n'; printf 'eq:x:10001:\n'; } > "$R/etc/group"
fi
chmod 0644 "$R/etc/passwd" "$R/etc/group"

: > /tmp/lock.tsv; : > /tmp/lock.sha
for t in $(tm_get image "$what" tools); do
  g() { tm_get tool "$t" "$1"; }
  dest=$(g dest); prov=$(g provenance); msha=$(g sha256)
  case "$prov" in
    prebuilt-upstream|built-from-source)
      [ -d "$dest" ] || die "$t: $dest was not installed (tc/fetch-tool.sh $t)"
      mkdir -p "$R$(dirname "$dest")"; cp -a "$dest" "$R$dest";;
    in-repo)
      for f in $(g files); do mkdir -p "$R$(dirname "$f")"; install -m 0755 "$f" "$R$f"; done;;
    *) echo "mkrootfs-tc: $t: provenance '$prov' is not allowed in an image" >&2; exit 2;;
  esac
  for f in $(g files); do
    [ -f "$R$f" ] || die "$t: $f missing in the rootfs"
    h=$(sha256sum "$R$f" | cut -d' ' -f1)
    printf '%s\t%s\t%s\t%s\t%s\n' "$t" "$(g version)" "$msha" "$f" "$h" >> /tmp/lock.tsv
    printf '%s  %s\n' "$h" "$f" >> /tmp/lock.sha
  done
done
cp /tmp/lock.tsv "$R/opt/eq/TOOLS.lock"; cp /tmp/lock.sha "$R/opt/eq/TOOLS.lock.sha256"
printf '%s %s\n' "$what" "$base" > "$R/opt/eq/IMAGE_KIND"
{ echo "image_kind: $what ($base)"
  [ "$base" = scratch ] || echo "base: $DISTROLESS_CC (linux/arm64 $DISTROLESS_CC_ARM64)"
  echo "manifest_image_sha256: $(tm_image_hash "$what")"; echo "tools: $(tm_get image "$what" tools)"; } > "$R/opt/eq/PROVENANCE-tc.txt"
if [ "$base" = distroless-cc ]; then
  # the base's executables (outside /opt), for verify-tools.sh --deep (it requires this file in every distroless-cc image);
  # the same recipe as minimal/mkrootfs.sh (tests/test_eq_container_dockerfiles.py compares the two)
  ( cd "$B" && find . -path ./opt -prune -o -type f \( -perm -u+x -o -perm -g+x -o -perm -o+x \) -print | LC_ALL=C sort \
      | while read -r f; do printf '%s  %s\n' "$(sha256sum "$f" | cut -d' ' -f1)" "${f#.}"; done ) > "$R/opt/eq/BASE_EXECUTABLES.txt"
fi
chmod -R a+rX "$R/opt"
chmod -R go-w "$R/opt" "$R/etc"

# ---- the final filesystem: layer over base (hard links), then the ELF rules
rm -rf "$C"; mkdir -p "$C"
cp -al "$R/." "$C/"
[ "$base" = scratch ] || cp -a --update=none "$B/." "$C/"
is_elf() { [ -f "$1" ] && [ "$(head -c 4 "$1" | tail -c 3)" = ELF ]; }
outside=$(cd "$R" && find . -path ./opt -prune -o -type f -print | while read -r f; do is_elf "$f" && echo "${f#.}"; done || true)
[ -z "$outside" ] || die "ELF files in the layer outside /opt: $outside"
suid=$(find "$C" -xdev -type f \( -perm -4000 -o -perm -2000 \) -print | sed "s#^$C##" | head -n 20)
[ -z "$suid" ] || die "setuid/setgid files: $suid"
bad=0; ndyn=0; nstat=0
while IFS= read -r -d '' f; do
  is_elf "$f" || continue
  p=${f#"$C"}
  mach=$(readelf -hW "$f" 2>/dev/null | sed -n 's/^ *Machine: *//p')
  if [ "$mach" != AArch64 ]; then echo "NOTE: skipped a ${mach:-unreadable} ELF (not AArch64): $p"; continue; fi
  interp=$(readelf -lW "$f" 2>/dev/null | sed -n 's/.*Requesting program interpreter: \(.*\)\]$/\1/p' | head -n 1)
  needed=$(readelf -dW "$f" 2>/dev/null | grep -c '(NEEDED)' || true)
  if [ -z "$interp" ] && [ "$needed" = 0 ]; then nstat=$((nstat + 1)); continue; fi
  if [ "$base" = scratch ]; then echo "NOT STATIC on a scratch image (interpreter '${interp:-none}', $needed NEEDED): $p"; bad=1; continue; fi
  out=$(/usr/sbin/chroot "$C" "${interp:-/lib/ld-linux-aarch64.so.1}" --list "$p" 2>&1) && rc=0 || rc=$?
  if [ "$rc" != 0 ] || printf '%s\n' "$out" | grep -q 'not found'; then
    echo "UNRESOLVED in base + layer (rc $rc): $p"; printf '%s\n' "$out" | grep -E 'not found|error|No such' | head -n 5; bad=1
  else ndyn=$((ndyn + 1)); fi
done < <(find "$C" -xdev -type f \( -perm -u+x -o -name '*.so' -o -name '*.so.*' \) -print0)
rm -rf "$C"
[ "$bad" = 0 ] || die "$what is not self-contained: a library must come from the base or the tool's own tree, and a scratch image needs static ELF files only"
echo "layer $what ($base): $(find "$R" -type f | wc -l) files, $(du -sb "$R" | cut -f1) bytes; $ndyn dynamic and $nstat static ELF files checked; lock: $(wc -l < /tmp/lock.tsv) rows"
