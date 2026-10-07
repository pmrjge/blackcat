#!/bin/bash
# shellcheck disable=SC2016,SC2012,SC2086,SC2329,SC2015
# mkrootfs.sh VARIANT   (runs in the builder stage of Dockerfile.minimal; never at run time)
# Assembles /rootfs for the FROM-scratch image. VARIANT = lean | py | both.
# Everything the checks execute is copied explicitly; shared libraries are resolved with ldd in THIS stage (Debian trixie,
# pinned by digest in the Dockerfile), including the dynamic loader at its exact path. Then the result is checked inside
# `chroot /rootfs` (ld.so --list on every ELF: any "not found" fails the build) and a sha256 manifest is written.
# Inputs (already in place from earlier stages): /opt/lean, /opt/eq (project + .lake + PROVENANCE.txt), /opt/python,
# /opt/uv, /opt/busybox (static, sha256-verified), /opt/eq/LEAN_PATH.real.   Env: KEEP_EXTS (module file extensions kept).
set -euo pipefail
variant=${1:?variant lean|py|both}
case "$variant" in lean|py|both) ;; *) echo "bad variant $variant" >&2; exit 2;; esac
R=/rootfs
KEEP_EXTS=${KEEP_EXTS:-olean olean.private olean.server ir ir.sig}
want_lean=0; want_py=0
[ "$variant" != py ] && want_lean=1
[ "$variant" != lean ] && want_py=1

rm -rf "$R"; mkdir -p "$R"
mkdir -p "$R/usr/bin" "$R/usr/lib/aarch64-linux-gnu" "$R/usr/local/bin" "$R/etc" "$R/tmp" "$R/work" "$R/fixture" \
         "$R/items" "$R/hostlake" "$R/opt/eq" "$R/proc" "$R/dev" "$R/sys" "$R/eqsrc/work"
ln -s usr/bin "$R/bin"; ln -s usr/lib "$R/lib"
chmod 1777 "$R/tmp"
: > "$R/etc/hosts"; : > "$R/etc/resolv.conf"; : > "$R/etc/hostname"
printf 'root:x:0:0:root:/:/bin/false\neq:x:10001:10001:eq:/tmp:/bin/false\n' > "$R/etc/passwd"
printf 'root:x:0:\neq:x:10001:\n' > "$R/etc/group"
printf 'passwd: files\ngroup: files\nhosts: files\n' > "$R/etc/nsswitch.conf"
: > /tmp/sysfiles.list      # system (Debian) files copied, for the package manifest

norm() { case "$1" in /usr/*) echo "$1";; /bin/*|/lib/*|/sbin/*) echo "/usr$1";; *) echo "$1";; esac; }

add_file() { # builder path -> same (usr-merged) path in the rootfs; symlink kept as a symlink plus its target copied
  local p=$1 d t
  d=$(norm "$p")
  mkdir -p "$R$(dirname "$d")"
  if [ -L "$p" ]; then
    [ -e "$R$d" ] || cp -a "$p" "$R$d"
    t=$(readlink -f "$p")
    add_file "$t"
  else
    [ -e "$R$d" ] || cp -a "$p" "$R$d"
  fi
  case "$d" in /opt/*) ;; *) echo "$d" >> /tmp/sysfiles.list;; esac
}

add_elf_closure() { # shared libraries and the loader of an ELF (ldd, builder side); /opt/* trees are copied whole
  local f=$1 out l
  out=$(ldd "$f" 2>&1 || true)
  case "$out" in *"not a dynamic executable"*|*"statically linked"*) return 0;; esac
  if printf '%s\n' "$out" | grep -q 'not found'; then
    echo "ERROR: unresolved library for $f:" >&2; printf '%s\n' "$out" >&2; exit 1
  fi
  printf '%s\n' "$out" | awk '/=>/ {print $3} /^[[:space:]]*\/.*ld-linux/ {print $1}' | grep '^/' | while read -r l; do
    case "$l" in /opt/*) ;; *) add_file "$l";; esac
  done
}

add_bin() { # a real Debian binary (not busybox) and its libraries
  local src=$1 dst=${2:-}
  [ -e "$src" ] || { echo "ERROR: $src missing in the builder" >&2; exit 1; }
  add_file "$(readlink -f "$src")"
  [ -n "$dst" ] && { mkdir -p "$R$(dirname "$dst")"; ln -sf "$(norm "$(readlink -f "$src")")" "$R$dst"; }
  add_elf_closure "$(readlink -f "$src")"
}

# ---- shell, timeout wrapper, coreutils-ish -----------------------------------------------------------------------
# bash and perl cannot be avoided (see RUNBOOK_MINIMAL.md): the harness argv is `bash check_lean.sh Answer.lean` and
# check_lean.sh runs `perl -e <alarm wrapper>`; the script is frozen (pool.sha256) so it is not edited. Both are the real
# Debian binaries from the digest-pinned base. Everything else comes from ONE static busybox pinned by sha256.
add_bin /usr/bin/bash
add_bin /usr/bin/perl
ln -s bash "$R/usr/bin/sh"
install -m 0755 /opt/busybox "$R/usr/bin/busybox"
APPLETS="[ [[ awk basename cat chmod cmp cp cut date diff dirname env expr false find grep head id ls mkdir mktemp mv od printenv pwd readlink rm sed seq sha256sum sleep sort tail tee test timeout touch tr true uniq wc xargs"
for a in $APPLETS; do
  /opt/busybox --list | grep -qx -- "$a" || { echo "ERROR: busybox lacks applet $a" >&2; exit 1; }
  ln -s busybox "$R/usr/bin/$a"
done
echo "busybox: $(/opt/busybox | head -n 1)" > /tmp/busybox.version

[ $want_lean = 1 ] && install -m 0755 /opt/eq-min/lake-shim "$R/usr/local/bin/lake"   # only the PF checker calls lake

# ---- Lean + Mathlib -----------------------------------------------------------------------------------------------
if [ $want_lean = 1 ]; then
  mkdir -p "$R/opt/lean/bin" "$R/opt/lean/lib/lean" "$R/opt/eq/stack_mathlib"
  install -m 0755 /opt/lean/bin/lean "$R/opt/lean/bin/lean"
  cp -a /opt/lean/lib/lean/*.so "$R/opt/lean/lib/lean/"
  add_elf_closure /opt/lean/bin/lean
  for so in /opt/lean/lib/lean/*.so; do add_elf_closure "$so"; done
  # module files: only the KEEP_EXTS suffixes; never the sysroot (clang, glibc, crt*.o, libLLVM), static libs, .ilean, .c
  expr_args=()
  for e in $KEEP_EXTS; do
    [ ${#expr_args[@]} -gt 0 ] && expr_args+=(-o)
    expr_args+=(-name "*.$e")
  done
  ( cd / && find opt/lean/lib/lean -type f \( "${expr_args[@]}" \) ! -path 'opt/lean/lib/lean/clang/*' ! -path 'opt/lean/lib/lean/glibc/*' -print0 \
      | tar --null -T - -cf - ) | tar -C "$R" -xf -
  ( cd / && find opt/eq/stack_mathlib/.lake -type f -path '*/.lake/build/lib/lean/*' \( "${expr_args[@]}" \) -print0 \
      | tar --null -T - -cf - ) | tar -C "$R" -xf -
  cp /opt/eq/stack_mathlib/lakefile.toml /opt/eq/stack_mathlib/lake-manifest.json /opt/eq/stack_mathlib/lean-toolchain "$R/opt/eq/stack_mathlib/"
  # LEAN_PATH computed by the real lake at build time; the same absolute paths exist in the rootfs
  cp /opt/eq/LEAN_PATH.real "$R/opt/eq/LEAN_PATH.real"
  cp /opt/eq/LEAN_PATH.real "$R/opt/eq/LEAN_PATH"
  IFS=: read -r -a lp_dirs < /opt/eq/LEAN_PATH.real
  found_mathlib=0
  for d in "${lp_dirs[@]}"; do
    if [ -d "/$d" ] || [ -d "$d" ]; then
      [ -d "$R$d" ] || { echo "ERROR: LEAN_PATH dir $d exists in the builder but not in the rootfs" >&2; exit 1; }
      [ "$(find "$d" -name '*.olean' | wc -l)" = "$(find "$R$d" -name '*.olean' | wc -l)" ] || { echo "ERROR: olean count differs in $d" >&2; exit 1; }
    fi
    [ -f "$R$d/Mathlib.olean" ] && found_mathlib=1
  done
  [ $found_mathlib = 1 ] || { echo "ERROR: Mathlib.olean not under any LEAN_PATH dir" >&2; exit 1; }
fi

# ---- Python (CP/CR/ES) ---------------------------------------------------------------------------------------------
if [ $want_py = 1 ]; then
  mkdir -p "$R/opt"
  cp -a /opt/python "$R/opt/python"
  pyroot="$R/opt/python"
  rm -rf "$pyroot/include" "$pyroot/share" "$pyroot/lib/pkgconfig" "$pyroot/lib/tcl"* "$pyroot/lib/tk"* "$pyroot/lib/itcl"* "$pyroot/lib/thread"* \
         "$pyroot"/bin/pip* "$pyroot"/bin/idle* "$pyroot"/bin/pydoc* "$pyroot"/bin/python3*-config "$pyroot"/bin/2to3*
  pyl=$(echo "$pyroot"/lib/python3.*)
  rm -rf "$pyl"/test "$pyl"/idlelib "$pyl"/tkinter "$pyl"/turtledemo "$pyl"/turtle.py "$pyl"/ensurepip "$pyl"/lib2to3 "$pyl"/pydoc_data \
         "$pyl"/config-* "$pyl"/site-packages/* "$pyl"/lib-dynload/_tkinter* "$pyl"/__pycache__/turtle*
  find "$pyroot" -name '*.a' -delete
  mkdir -p "$R/opt/uv"; install -m 0755 /opt/uv/uv "$R/opt/uv/uv"
  while IFS= read -r f; do
    case "$f" in /opt/*) ;; *) continue;; esac
  done < /dev/null
  for f in "$pyroot"/bin/python3* "$pyroot"/lib/*.so* "$pyroot"/lib/python3.*/lib-dynload/*.so /opt/uv/uv; do
    [ -f "$f" ] && add_elf_closure "$f"
  done
  add_bin /usr/bin/jq
  : > "$R/opt/eq/.py"
fi

# ---- provenance and the check that the rootfs is self-contained ------------------------------------------------------
cp /opt/eq/PROVENANCE.txt "$R/opt/eq/PROVENANCE.txt"
{
  echo "image_kind: min-$variant (FROM scratch)"
  echo "keep_exts: $KEEP_EXTS"
  cat /tmp/busybox.version
  echo "busybox_sha256: $(sha256sum /opt/busybox | cut -d' ' -f1)"
  echo "bash: $(dpkg-query -W -f='${Package} ${Version}' bash)"
  echo "perl-base: $(dpkg-query -W -f='${Package} ${Version}' perl-base)"
  echo "libc6: $(dpkg-query -W -f='${Package} ${Version}' libc6)"
  [ $want_py = 1 ] && echo "jq: $(dpkg-query -W -f='${Package} ${Version}' jq)"
} >> "$R/opt/eq/PROVENANCE.txt"
if [ $want_lean = 1 ]; then
  h=$(cd "$R/opt/eq/stack_mathlib/.lake/packages" && find . -name '*.olean' | LC_ALL=C sort | xargs sha256sum | sha256sum | cut -d' ' -f1)
  want=$(sed -n 's/^olean_tree_sha256: //p' /opt/eq/PROVENANCE.txt | head -n 1)
  [ "$h" = "$want" ] || { echo "ERROR: olean tree hash in the rootfs ($h) differs from the full build ($want)" >&2; exit 1; }
  echo "olean tree hash equals the full image's: $h"
fi
printf '%s\n' "$variant" > "$R/opt/eq/IMAGE_KIND"

# ---- the tools lock (X2): every tool TOOLS.toml gives this image, with the manifest pin and the hash of the installed file.
# distro-package and in-repo tools must be pinned in the manifest and hash to the pin (build.sh --resolve-tools --write-pin fills it);
# the archives of prebuilt-upstream tools were verified against the same manifest/PINS values in the fetch stage.
# verify-tools.sh reads /opt/eq/TOOLS.lock from outside, probe_inner.sh checks TOOLS.lock.sha256 from inside.
if [ -f /opt/eq-min/TOOLS.toml ]; then
  # shellcheck disable=SC1091
  . /opt/eq-min/tools.sh; tm_load /opt/eq-min/TOOLS.toml
  case "$variant" in lean) img=min-lean;; py) img=min-py;; both) img=min-both;; esac
  : > "$R/opt/eq/TOOLS.lock"; : > "$R/opt/eq/TOOLS.lock.sha256"
  for t in $(tm_get image "$img" tools); do
    msha=$(tm_get tool "$t" sha256); mver=$(tm_get tool "$t" version); mprov=$(tm_get tool "$t" provenance)
    for f in $(tm_get tool "$t" files); do
      [ -e "$R$f" ] || { echo "ERROR: tool $t: $f is missing in the rootfs" >&2; exit 1; }
      h=$(sha256sum "$R$f" | cut -d' ' -f1)
      case "$mprov" in
        distro-package|in-repo)
          [ "$msha" != PLACEHOLDER ] || { echo "ERROR: tool $t is unpinned (sha256 PLACEHOLDER in TOOLS.toml): run build.sh --resolve-tools --write-pin" >&2; exit 13; }
          [ "$h" = "$msha" ] || { echo "ERROR: tool $t: installed $f hashes to $h but TOOLS.toml pins $msha" >&2; exit 1; };;
      esac
      printf '%s\t%s\t%s\t%s\t%s\n' "$t" "$mver" "$msha" "$f" "$h" >> "$R/opt/eq/TOOLS.lock"
      printf '%s  %s\n' "$h" "$f" >> "$R/opt/eq/TOOLS.lock.sha256"
    done
  done
  echo "tools lock: $(wc -l < "$R/opt/eq/TOOLS.lock") rows for image $img"
fi
chmod -R a+rX "$R/opt" "$R/usr"

# dpkg package of every copied Debian file (best effort), for the manifest
sort -u /tmp/sysfiles.list | while read -r f; do
  pk=$(dpkg-query -S "$f" 2>/dev/null | head -n 1 | cut -d: -f1 || true)
  [ -n "$pk" ] || pk=$(dpkg-query -S "/usr${f#/usr}" 2>/dev/null | head -n 1 | cut -d: -f1 || true)
  printf '%s\t%s\t%s\n' "$f" "${pk:-?}" "$( [ -n "$pk" ] && dpkg-query -W -f='${Version}' "${pk%%,*}" 2>/dev/null || true)"
done > "$R/opt/eq/MANIFEST.debian-files.tsv"
ldconfig -r "$R" 2>/dev/null || true

# every ELF must load completely inside the rootfs (no /proc needed for --list)
bad=0
while IFS= read -r -d '' f; do
  [ "$(head -c 4 "$f" | tail -c 3)" = ELF ] || continue
  out=$(chroot "$R" /lib/ld-linux-aarch64.so.1 --list "/${f#"$R"/}" 2>&1) && rc=0 || rc=$?
  if printf '%s\n' "$out" | grep -q 'not found'; then echo "UNRESOLVED in rootfs: $f"; printf '%s\n' "$out"; bad=1
  elif [ $rc != 0 ] && ! printf '%s\n' "$out" | grep -qE 'not a dynamic executable|statically linked'; then echo "ld.so --list failed rc=$rc for $f: $out"; bad=1; fi
done < <(find "$R" -type f \( -perm -u+x -o -name '*.so*' \) -print0)
[ $bad = 0 ] || { echo "ERROR: rootfs is not self-contained" >&2; exit 1; }

# the perl alarm wrapper of check_lean.sh, run for real in the rootfs (needs only perl built-ins)
wrapper='my $t = shift; my $pid = fork(); defined $pid or exit 125; if ($pid == 0) { exec @ARGV or exit 127 }
           local $SIG{ALRM} = sub { kill "KILL", $pid; print STDERR "eqlean: timeout\n"; exit 124 };
           alarm $t; waitpid($pid, 0); alarm 0;
           if ($? & 127) { print STDERR "eqlean: killed by signal ", ($? & 127), "\n"; exit(128 + ($? & 127)) }
           exit($? >> 8)'
rc=0; chroot "$R" /usr/bin/perl -e "$wrapper" 1 /usr/bin/sleep 5 2>/dev/null || rc=$?
[ "$rc" = 124 ] || { echo "ERROR: perl timeout wrapper returned $rc, want 124" >&2; exit 1; }
rc=0; chroot "$R" /usr/bin/perl -e "$wrapper" 5 /usr/bin/true || rc=$?
[ "$rc" = 0 ] || { echo "ERROR: perl wrapper on /usr/bin/true returned $rc" >&2; exit 1; }
[ "$(chroot "$R" /usr/bin/bash -c 'echo ok; cd /tmp && mktemp -d eqx.XXXXXX >/dev/null && echo ok2' | tr '\n' ' ')" = "ok ok2 " ] || { echo "ERROR: bash/mktemp smoke failed" >&2; exit 1; }
# F4: the harness and eq-docker's lib.sh start every check as `/bin/sh -c 'cp -R /eqsrc/work/. /work/ && exec "$@"'`:
# the mount point, /bin/sh and cp must exist, and a recursive copy of dot-files and subdirectories must work
[ -d "$R/eqsrc/work" ] && [ -x "$R/usr/bin/sh" ] && [ -e "$R/usr/bin/cp" ] || { echo "ERROR: /eqsrc/work, /bin/sh or cp missing in the rootfs" >&2; exit 1; }
chroot "$R" /bin/sh -c 'cd /tmp && mkdir -p a/b && echo x > a/b/f && echo y > a/.d && mkdir -p c && cp -R a/. c/ && test -f c/b/f && test -f c/.d' \
  || { echo "ERROR: the cp -R copy smoke test failed in the rootfs" >&2; exit 1; }
echo "rootfs self-containment checks passed"

# manifest of every file (sha256), then its root hash; sizes
( cd "$R" && find . \( -type f -o -type l \) ! -path './opt/eq/MANIFEST*' -print0 | LC_ALL=C sort -z \
    | while IFS= read -r -d '' f; do
        if [ -L "$f" ]; then printf 'LINK %s -> %s\n' "$f" "$(readlink "$f")"; else printf '%s  %s\n' "$(sha256sum "$f" | cut -d' ' -f1)" "$f"; fi
      done ) > "$R/opt/eq/MANIFEST.sha256"
root=$(sha256sum "$R/opt/eq/MANIFEST.sha256" | cut -d' ' -f1)
echo "$root" > "$R/opt/eq/MANIFEST.root"
echo "files: $(find "$R" -type f | wc -l)  links: $(find "$R" -type l | wc -l)  bytes: $(du -sb "$R" | cut -f1)"
echo "MANIFEST_ROOT_SHA256=$root"
