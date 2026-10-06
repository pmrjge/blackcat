#!/bin/bash
# shellcheck disable=SC2016
# mkrootfs-tc.sh IMAGE|base   (runs in a builder stage of Dockerfile.toolchains; never at run time)
# base   : /rootfs of the shared minimal base eq-base: the glibc closure (loader, libc, libm, libgcc_s, libstdc++, libnss_files),
#          /etc/passwd and /etc/group with the unprivileged users (10001 eq, 10002 eqdb), nsswitch, mount points. No shell, no tools.
# IMAGE  : an [[image]] of TOOLS.toml with base = eq-base: copies the trees the image's tools were installed into by
#          tc/fetch-tool.sh, adds ONLY the shared libraries the base does not already hold (ldd closure of every ELF), links the
#          pinned busybox applets the image needs, writes /opt/eq/TOOLS.lock, TOOLS.lock.sha256, IMAGE_KIND, PROVENANCE-tc.txt,
#          then checks that every ELF resolves inside the rootfs (ld.so --list through chroot) and runs nothing else.
# The per-image layer therefore holds only what differs from eq-base, so the base layers are stored once however many language
# images exist. Final images contain binaries, their libraries, the language's own standard library files, /etc/passwd,group:
# no package manager, docs, man pages, C headers or test suites (prune lists in TOOLS.toml). UNVERIFIED until a build passes.
set -euo pipefail
what=${1:?image name or base}
T=${EQ_TOOLS_DIR:-/opt/eq-tools}
R=/rootfs; BASE=/base-rootfs
# shellcheck disable=SC1091
. "$T/tools.sh"
tm_load "$T/TOOLS.toml"
rm -rf "$R"; mkdir -p "$R"
if [ "$what" = base ]; then BASE=/nonexistent; fi

norm() { case "$1" in /usr/*) echo "$1";; /bin/*|/lib/*|/sbin/*) echo "/usr$1";; *) echo "$1";; esac; }
add_file() { # builder path -> usr-merged path in the rootfs unless the base already holds it; a symlink is kept and its target copied
  local p=$1 d t
  d=$(norm "$p")
  [ -e "$BASE$d" ] && return 0
  mkdir -p "$R$(dirname "$d")"
  if [ -L "$p" ]; then
    [ -e "$R$d" ] || cp -a "$p" "$R$d"
    t=$(readlink -f "$p"); add_file "$t"
  else
    [ -e "$R$d" ] || cp -a "$p" "$R$d"
  fi
}
elf_closure() { # shared libraries and the loader of one ELF, resolved with ldd on the builder side
  local f=$1 out l
  out=$(ldd "$f" 2>&1 || true)
  case "$out" in *"not a dynamic executable"*|*"statically linked"*) return 0;; esac
  if printf '%s\n' "$out" | grep -q 'not found'; then echo "ERROR: unresolved library for $f:" >&2; printf '%s\n' "$out" >&2; exit 1; fi
  printf '%s\n' "$out" | awk '/=>/ {print $3} /^[[:space:]]*\/.*ld-linux/ {print $1}' | grep '^/' | while read -r l; do
    case "$l" in /opt/*) ;; *) add_file "$l";; esac
  done
}
is_elf() { [ -f "$1" ] && [ "$(head -c 4 "$1" | tail -c 3)" = ELF ]; }

mkdir -p "$R/usr/bin" "$R/opt/eq"
if [ "$what" = base ]; then
  mkdir -p "$R/usr/lib/aarch64-linux-gnu" "$R/etc" "$R/tmp" "$R/work" "$R/proc" "$R/dev" "$R/sys" "$R/run"
  ln -s usr/bin "$R/bin"; ln -s usr/lib "$R/lib"
  chmod 1777 "$R/tmp"
  : > "$R/etc/hosts"; : > "$R/etc/resolv.conf"; : > "$R/etc/hostname"
  printf 'root:x:0:0:root:/:/bin/false\neq:x:10001:10001:eq:/tmp:/bin/false\neqdb:x:10002:10002:eqdb:/tmp:/bin/false\n' > "$R/etc/passwd"
  printf 'root:x:0:\neq:x:10001:\neqdb:x:10002:\n' > "$R/etc/group"
  printf 'passwd: files\ngroup: files\nhosts: files\n' > "$R/etc/nsswitch.conf"
  elf_closure /usr/bin/true
  for so in libc.so.6 libm.so.6 libgcc_s.so.1 libstdc++.so.6 libnss_files.so.2 libdl.so.2 libpthread.so.0 librt.so.1 libresolv.so.2; do
    p=$(ldconfig -p | awk -v s="$so" '$1 == s && /aarch64|AArch64|64-bit/ { print $NF; exit }')
    if [ -n "$p" ]; then add_file "$p"
    else case "$so" in libc.so.6|libm.so.6|libgcc_s.so.1|libstdc++.so.6|libnss_files.so.2) echo "ERROR: $so not found in the builder" >&2; exit 1;; *) echo "note: optional $so not in the builder";; esac; fi
  done
  : > "$R/opt/eq/.base"
  echo "image_kind: eq-base" > "$R/opt/eq/PROVENANCE-base.txt"
  echo "libc6: $(dpkg-query -W -f='${Package} ${Version}' libc6)" >> "$R/opt/eq/PROVENANCE-base.txt"
  echo "libstdc++6: $(dpkg-query -W -f='${Package} ${Version}' libstdc++6)" >> "$R/opt/eq/PROVENANCE-base.txt"
  echo "base rootfs: $(find "$R" -type f | wc -l) files, $(du -sb "$R" | cut -f1) bytes"
  exit 0
fi

tm_has image "$what" || { echo "mkrootfs-tc: $what is not an [[image]] of TOOLS.toml" >&2; exit 2; }
[ "$(tm_get image "$what" base)" = eq-base ] || { echo "mkrootfs-tc: $what is not an eq-base image" >&2; exit 2; }
: > /tmp/lock.tsv; : > /tmp/lock.sha
applets=""
for t in $(tm_get image "$what" tools); do
  g() { tm_get tool "$t" "$1"; }
  dest=$(g dest); prov=$(g provenance); msha=$(g sha256)
  case "$prov" in
    distro-package)
      [ "$msha" != PLACEHOLDER ] || { echo "mkrootfs-tc: $t sha256 is PLACEHOLDER (build.sh --resolve-tools --write-pin)" >&2; exit 13; }
      if [ "$t" = busybox ]; then
        echo "$msha  /opt/busybox" | sha256sum -c - >&2
        install -D -m 0755 /opt/busybox "$R/usr/bin/busybox"
        applets=$(tm_get image "$what" applets)
      else
        # a Debian package closure recorded by tc/apt-closure.sh (USER decision 2026-10-05: cc in the Rust/Haskell images):
        # every regular file and symlink of those packages except docs, man pages, info pages and locales
        lst="/opt/eq-pkgs/$t.list"
        [ -s "$lst" ] || { echo "mkrootfs-tc: $t: no package closure $lst (tc/apt-closure.sh did not run in this stage)" >&2; exit 2; }
        f1=$(g files | cut -d' ' -f1)
        echo "$msha  $(readlink -f "$f1")" | sha256sum -c - >&2 || { echo "mkrootfs-tc: $t: $f1 does not hash to the pinned sha256" >&2; exit 1; }
        while read -r pkg; do
          dpkg -L "$pkg" | while IFS= read -r f; do
            case "$f" in /usr/share/doc/*|/usr/share/man/*|/usr/share/info/*|/usr/share/locale/*|/usr/share/lintian/*|/usr/share/bug/*) continue;; esac
            if [ -L "$f" ] || [ -f "$f" ]; then add_file "$f"; is_elf "$f" && elf_closure "$f"; fi
          done
        done < "$lst"
        if [ "$t" = cc ]; then ln -sf gcc "$R/usr/bin/cc"; fi
      fi;;
    in-repo)
      for f in $(g files); do mkdir -p "$R$(dirname "$f")"; install -m 0755 "$f" "$R$f"; done;;
    *)
      mkdir -p "$R$(dirname "$dest")"; cp -a "$dest" "$R$dest"
      # the language's own ELF files (bins, runtime .so files) and their shared libraries
      while IFS= read -r -d '' f; do is_elf "$f" && elf_closure "$f"; done < <(find "$dest" -type f \( -perm -u+x -o -name '*.so*' \) -print0)
      ;;
  esac
  for f in $(g files); do
    [ -e "$R$f" ] || { echo "mkrootfs-tc: $t: $f missing in the rootfs" >&2; exit 1; }
    h=$(sha256sum "$R$f" | cut -d' ' -f1)
    printf '%s\t%s\t%s\t%s\t%s\n' "$t" "$(g version)" "$msha" "$f" "$h" >> /tmp/lock.tsv
    printf '%s  %s\n' "$h" "$f" >> /tmp/lock.sha
  done
done
# busybox applets this image needs (links only; the applet list is in the [[image]] entry as `applets`, default: none)
if [ -n "$applets" ]; then
  for a in $applets; do
    /opt/busybox --list | grep -qx -- "$a" || { echo "mkrootfs-tc: busybox lacks applet $a" >&2; exit 1; }
    ln -s busybox "$R/usr/bin/$a"
  done
fi
cp /tmp/lock.tsv "$R/opt/eq/TOOLS.lock"; cp /tmp/lock.sha "$R/opt/eq/TOOLS.lock.sha256"
printf '%s\n' "tc-$what" > "$R/opt/eq/IMAGE_KIND"
{ echo "image_kind: $what (FROM eq-base)"; echo "manifest_image_sha256: $(tm_image_hash "$what")"; echo "tools: $(tm_get image "$what" tools)"; } > "$R/opt/eq/PROVENANCE-tc.txt"
chmod -R a+rX "$R/opt" "$R/usr" 2>/dev/null || true

# every ELF of the layer must resolve inside base + layer (no /proc needed for --list)
rm -rf /check-root; mkdir -p /check-root
cp -a "$BASE/." /check-root/ 2>/dev/null || true
cp -a "$R/." /check-root/
bad=0
while IFS= read -r -d '' f; do
  is_elf "$f" || continue
  out=$(chroot /check-root /lib/ld-linux-aarch64.so.1 --list "/${f#/check-root/}" 2>&1) && rc=0 || rc=$?
  if printf '%s\n' "$out" | grep -q 'not found'; then echo "UNRESOLVED in the rootfs: $f"; printf '%s\n' "$out"; bad=1
  elif [ "$rc" != 0 ] && ! printf '%s\n' "$out" | grep -qE 'not a dynamic executable|statically linked'; then echo "ld.so --list failed rc=$rc for $f: $out"; bad=1; fi
done < <(find /check-root -type f \( -perm -u+x -o -name '*.so*' \) -print0)
[ "$bad" = 0 ] || { echo "ERROR: $what rootfs is not self-contained" >&2; exit 1; }
echo "layer $what: $(find "$R" -type f | wc -l) files, $(du -sb "$R" | cut -f1) bytes (the base holds the rest); lock: $(wc -l < /tmp/lock.tsv) rows"
