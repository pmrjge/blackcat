#!/bin/bash
# shellcheck disable=SC2016,SC2012,SC2086,SC2329,SC2015
# mkrootfs.sh VARIANT   (runs in the discarded assemble-* stages of Dockerfile.minimal; never at run time)
# Assembles /rootfs, the ONE layer the final image adds on top of the pinned distroless cc base. VARIANT = lean | py | both.
# Rules (USER decision 2026-10-06, DESIGN_DISTROLESS.md section 5):
#   - the layer holds /opt trees, the /opt/eq/bin toolbox, /etc/passwd and /etc/group (the base's plus eq 10001), the mount
#     points and /usr/bin/{sh,bash,env} links; no shared object is ever copied: every library a binary needs must come from the
#     base or from the tool's own /opt tree ("no third source of shared objects"), else the build fails naming it;
#   - no ELF in the layer outside /opt; every ELF must be AArch64; every dynamic ELF is listed by the loader inside a chroot of
#     base + layer (/check-root) and any "not found" fails; no setuid or setgid file anywhere (base or layer);
#   - every installed tool file is pinned: file_sha256 (busybox, bash), or sha256 itself for archive = binary and in-repo tools
#     (PLACEHOLDER: exit 13); the archives were checked in the fetch stage.
# Inputs: /base-rootfs (the distroless cc filesystem), /opt/lean, /opt/eq (project + .lake + PROVENANCE.txt + LEAN_PATH.real),
# /opt/python, /opt/uv, /opt/eq-dl/{busybox,jq,bash}, /opt/eq-min (this directory, TOOLS.toml, tools.sh).
# Env: KEEP_EXTS (module file extensions kept), DISTROLESS_CC and DISTROLESS_CC_ARM64 (the pins, for the SBOM).
# Outputs in the layer: /opt/eq/{TOOLS.lock,TOOLS.lock.sha256,SBOM.tsv,BASE_EXECUTABLES.txt,ELF.tsv,IMAGE_KIND,PROVENANCE.txt,
# MANIFEST.sha256,MANIFEST.root}; minimal/check.sh re-checks them in the final filesystem.
set -euo pipefail
variant=${1:?variant lean|py|both}
case "$variant" in lean|py|both) ;; *) echo "bad variant $variant" >&2; exit 2;; esac
R=/rootfs; B=/base-rootfs; C=/check-root; M=/opt/eq-min
KEEP_EXTS=${KEEP_EXTS:-olean olean.private olean.server ir ir.sig}
: "${DISTROLESS_CC:?DISTROLESS_CC (the base pin) is not set}" "${DISTROLESS_CC_ARM64:?DISTROLESS_CC_ARM64 is not set}"
want_lean=0; want_py=0
[ "$variant" != py ] && want_lean=1
[ "$variant" != lean ] && want_py=1
case "$variant" in lean) img=min-lean;; py) img=min-py;; both) img=min-both;; esac
die() { echo "ERROR: $*" >&2; exit 1; }
[ -d "$B/usr" ] && [ -d "$B/etc" ] || die "$B is not the distroless base filesystem (no /usr or /etc)"
[ ! -e "$B/busybox" ] || die "the base holds /busybox: a distroless debug image is not allowed"

# shellcheck disable=SC1091
. "$M/tools.sh"; tm_load "$M/TOOLS.toml"
tm_has image "$img" || die "$img is not an [[image]] of TOOLS.toml"
[ "$(tm_get image "$img" base)" = distroless-cc ] || die "$img: TOOLS.toml base is not distroless-cc"
TOOLS=" $(tm_get image "$img" tools) "
has_tool() { case "$TOOLS" in *" $1 "*) return 0;; esac; return 1; }

rm -rf "$R"; mkdir -p "$R"
mkdir -p "$R/opt/eq/bin" "$R/usr/bin" "$R/etc"
# mount points the runtime binds (the read-only rootfs of `container run --read-only` cannot get new directories) and the
# kernel/runtime directories, each only when the base lacks it
for d in work eqsrc/work fixture in eq/tunnel items hostlake; do mkdir -p "$R/$d"; done
for d in tmp proc dev sys; do [ -e "$B/$d" ] || mkdir -p "$R/$d"; done
[ -e "$B/tmp" ] || chmod 1777 "$R/tmp"
for f in hosts resolv.conf hostname; do [ -e "$B/etc/$f" ] || : > "$R/etc/$f"; done
# users: the base's own entries (root, nobody, nonroot 65532) plus eq 10001, so getpwuid works for the run user
if [ -f "$B/etc/passwd" ]; then
  ! awk -F: '$1 == "eq" || $3 == "10001"' "$B/etc/passwd" | grep -q . || die "the base already has a user eq or uid 10001"
  cp "$B/etc/passwd" "$R/etc/passwd"
else printf 'root:x:0:0:root:/root:/sbin/nologin\n' > "$R/etc/passwd"; fi
if [ -f "$B/etc/group" ]; then
  ! awk -F: '$1 == "eq" || $3 == "10001"' "$B/etc/group" | grep -q . || die "the base already has a group eq or gid 10001"
  cp "$B/etc/group" "$R/etc/group"
else printf 'root:x:0:\n' > "$R/etc/group"; fi
printf 'eq:x:10001:10001:eq:/tmp:/sbin/nologin\n' >> "$R/etc/passwd"
printf 'eq:x:10001:\n' >> "$R/etc/group"
chmod 0644 "$R/etc/passwd" "$R/etc/group"
[ -e "$B/etc/nsswitch.conf" ] || printf 'passwd: files\ngroup: files\nhosts: files\n' > "$R/etc/nsswitch.conf"

# ---- the toolbox /opt/eq/bin ------------------------------------------------------------------------------------------------
# bash and the shims reach /bin/sh and /bin/bash through the base's /bin: usr-merged (a symlink to usr/bin) in distroless
# Debian 13, so the links go to /usr/bin; a base with a real /bin directory gets them there too, a base without /bin a link
install -m 0755 /opt/eq-dl/busybox "$R/opt/eq/bin/busybox"
install -m 0755 /opt/eq-dl/bash "$R/opt/eq/bin/bash"
ln -s bash "$R/opt/eq/bin/sh"
for d in usr/bin bin; do
  case "$d" in bin) if [ -L "$B/bin" ]; then continue; elif [ ! -e "$B/bin" ]; then ln -s usr/bin "$R/bin"; continue; fi;; esac
  mkdir -p "$R/$d"
  ln -s /opt/eq/bin/bash "$R/$d/sh"; ln -s /opt/eq/bin/bash "$R/$d/bash"; ln -s /opt/eq/bin/busybox "$R/$d/env"
done
APPLETS="[ [[ awk basename cat chmod cmp cp cut date diff dirname env expr false find grep head id ls mkdir mktemp mv od printenv pwd readlink rm sed seq sha256sum sleep sort tail tee test timeout touch tr true uniq wc xargs"
bblist=$(/opt/eq-dl/busybox --list)
for a in $APPLETS; do
  printf '%s\n' "$bblist" | grep -qx -- "$a" || die "busybox lacks applet $a"
  ln -s busybox "$R/opt/eq/bin/$a"
done
has_tool jq && install -m 0755 /opt/eq-dl/jq "$R/opt/eq/bin/jq"
has_tool perl-shim && install -m 0755 "$M/perl-shim" "$R/opt/eq/bin/perl"
has_tool lake-shim && install -m 0755 "$M/lake-shim" "$R/opt/eq/bin/lake"   # only the PF checker calls lake

# ---- Lean + Mathlib -----------------------------------------------------------------------------------------------------------
if [ $want_lean = 1 ]; then
  mkdir -p "$R/opt/lean/bin" "$R/opt/lean/lib/lean" "$R/opt/eq/stack_mathlib"
  install -m 0755 /opt/lean/bin/lean "$R/opt/lean/bin/lean"
  cp -a /opt/lean/lib/lean/*.so "$R/opt/lean/lib/lean/"
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
    if [ -d "$d" ]; then
      [ -d "$R$d" ] || die "LEAN_PATH dir $d exists in the builder but not in the rootfs"
      [ "$(find "$d" -name '*.olean' | wc -l)" = "$(find "$R$d" -name '*.olean' | wc -l)" ] || die "olean count differs in $d"
    fi
    [ -f "$R$d/Mathlib.olean" ] && found_mathlib=1
  done
  [ $found_mathlib = 1 ] || die "Mathlib.olean not under any LEAN_PATH dir"
fi

# ---- Python + uv (CP/CR, and the PF oracle's `uv run`) ---------------------------------------------------------------------------
if [ $want_py = 1 ]; then
  cp -a /opt/python "$R/opt/python"
  pyroot="$R/opt/python"
  rm -rf "$pyroot/include" "$pyroot/share" "$pyroot/lib/pkgconfig" "$pyroot/lib/tcl"* "$pyroot/lib/tk"* "$pyroot/lib/itcl"* "$pyroot/lib/thread"* \
         "$pyroot"/bin/pip* "$pyroot"/bin/idle* "$pyroot"/bin/pydoc* "$pyroot"/bin/python3*-config "$pyroot"/bin/2to3*
  pyl=$(echo "$pyroot"/lib/python3.*)
  rm -rf "$pyl"/test "$pyl"/idlelib "$pyl"/tkinter "$pyl"/turtledemo "$pyl"/turtle.py "$pyl"/ensurepip "$pyl"/lib2to3 "$pyl"/pydoc_data \
         "$pyl"/config-* "$pyl"/site-packages/* "$pyl"/lib-dynload/_tkinter* "$pyl"/__pycache__/turtle*
  find "$pyroot" -name '*.a' -delete
  mkdir -p "$R/opt/uv"; install -m 0755 /opt/uv/uv "$R/opt/uv/uv"   # uvx is not installed (not in the lock, not needed)
  : > "$R/opt/eq/.py"
fi
chmod -R a+rX "$R/opt"
chmod -R go-w "$R/opt" "$R/etc"

# ---- the tools lock (X2) and the SBOM: every tool TOOLS.toml gives this image, with its pins and the installed file's hash ---
: > "$R/opt/eq/TOOLS.lock"; : > "$R/opt/eq/TOOLS.lock.sha256"
printf 'name\tversion\turl\tarchive_sha256\tinstalled_sha256\tlicence\tprovenance\n' > "$R/opt/eq/SBOM.tsv"
for t in $(tm_get image "$img" tools); do
  msha=$(tm_get tool "$t" sha256); mver=$(tm_get tool "$t" version); mprov=$(tm_get tool "$t" provenance)
  fsha=$(tm_get tool "$t" file_sha256); march=$(tm_get tool "$t" archive)
  url=$(tm_get tool "$t" url); url=${url//\{version\}/$mver}; url=${url//\{tag\}/$(tm_get tool "$t" tag)}
  case "$mprov" in prebuilt-upstream|built-from-source|in-repo) ;; *) die "tool $t: provenance '$mprov' is not allowed in an image";; esac
  first=1
  for f in $(tm_get tool "$t" files); do
    [ -f "$R$f" ] || die "tool $t: $f is missing in the rootfs"
    h=$(sha256sum "$R$f" | cut -d' ' -f1)
    if [ "$first" = 1 ]; then
      # the installed-file pin: file_sha256 when the entry has one, else the archive's sha256 when the archive IS the file
      want=""
      if [ -n "$fsha" ]; then want=$fsha
      elif [ "$march" = binary ] || [ "$mprov" = in-repo ]; then want=$msha; fi
      if [ -n "$want" ]; then
        case "$want" in PLACEHOLDER|UNSET|"") echo "ERROR: tool $t: the installed file is unpinned (PLACEHOLDER in TOOLS.toml): run bash lib/eq-container/repro-check.sh, then bash lib/eq-container/build.sh --resolve-tools --write-pin" >&2; exit 13;; esac
        [ "$h" = "$want" ] || die "tool $t: installed $f hashes to $h but TOOLS.toml pins $want"
      fi
      printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\n' "$t" "$mver" "$url" "$msha" "$h" "$(tm_get tool "$t" licence)" "$mprov" >> "$R/opt/eq/SBOM.tsv"
      first=0
    fi
    printf '%s\t%s\t%s\t%s\t%s\n' "$t" "$mver" "$msha" "$f" "$h" >> "$R/opt/eq/TOOLS.lock"
    printf '%s  %s\n' "$h" "$f" >> "$R/opt/eq/TOOLS.lock.sha256"
  done
done
printf 'distroless-cc\tcc-debian13:nonroot\t%s\t%s\t%s\t%s\t%s\n' "$DISTROLESS_CC" "${DISTROLESS_CC##*@sha256:}" \
  "${DISTROLESS_CC_ARM64#sha256:}" "see the image's signed attestation (cosign verify-attestation)" "distroless-base" >> "$R/opt/eq/SBOM.tsv"
echo "tools lock: $(wc -l < "$R/opt/eq/TOOLS.lock") rows for image $img"

# ---- provenance -----------------------------------------------------------------------------------------------------------------
if [ $want_lean = 1 ]; then cp /opt/eq/PROVENANCE.txt "$R/opt/eq/PROVENANCE.txt"; else : > "$R/opt/eq/PROVENANCE.txt"; fi
{
  echo "image_kind: $img distroless-cc"
  echo "base: $DISTROLESS_CC (linux/arm64 $DISTROLESS_CC_ARM64)"
  echo "keep_exts: $([ $want_lean = 1 ] && echo "$KEEP_EXTS" || echo n/a)"
  echo "busybox: $(/opt/eq-dl/busybox | head -n 1)"
  echo "bash: $(/opt/eq-dl/bash --version | head -n 1)"
  if has_tool jq; then echo "jq: $(/opt/eq-dl/jq --version)"; fi
} >> "$R/opt/eq/PROVENANCE.txt"
if [ $want_lean = 1 ]; then
  h=$(cd "$R/opt/eq/stack_mathlib/.lake/packages" && find . -name '*.olean' | LC_ALL=C sort | xargs sha256sum | sha256sum | cut -d' ' -f1)
  want=$(sed -n 's/^olean_tree_sha256: //p' /opt/eq/PROVENANCE.txt | head -n 1)
  [ "$h" = "$want" ] || die "olean tree hash in the rootfs ($h) differs from the Mathlib stage's ($want)"
  echo "olean tree hash equals the Mathlib stage's: $h"
fi
printf '%s distroless-cc\n' "$img" > "$R/opt/eq/IMAGE_KIND"

# ---- the ELF rules over base + layer ----------------------------------------------------------------------------------------------
# /check-root = the final filesystem: the layer wins over the base (hard links: nothing is copied twice)
rm -rf "$C"; mkdir -p "$C"
cp -al "$R/." "$C/"
cp -a --update=none "$B/." "$C/"
is_elf() { [ -f "$1" ] && [ "$(head -c 4 "$1" | tail -c 3)" = ELF ]; }
# no ELF in the layer outside /opt (a shared object or binary there would be a third source)
outside=$(cd "$R" && find . -path ./opt -prune -o -type f -print | while read -r f; do is_elf "$f" && echo "${f#.}"; done || true)
[ -z "$outside" ] || die "ELF files in the layer outside /opt: $outside"
# no setuid/setgid file in the final filesystem (base included)
suid=$(find "$C" -xdev -type f \( -perm -4000 -o -perm -2000 \) -print | sed "s#^$C##" | head -n 20)
[ -z "$suid" ] || die "setuid/setgid files: $suid"
# no package manager or debug shell anywhere
pm=$(find "$C" -xdev -type f \( -name apt -o -name apt-get -o -name dpkg -o -name apk -o -name rpm -o -name yum -o -name dnf \) -print | sed "s#^$C##")
[ -z "$pm" ] || die "package manager executables in the final filesystem: $pm"
[ ! -e "$C/busybox" ] || die "/busybox (a debug shell) in the final filesystem"
LDSO=/lib/ld-linux-aarch64.so.1
: > /tmp/elf.tsv; bad=0
while IFS= read -r -d '' f; do
  is_elf "$f" || continue
  p=${f#"$C"}
  mach=$(readelf -hW "$f" 2>/dev/null | sed -n 's/^ *Machine: *//p')
  [ "$mach" = AArch64 ] || { echo "NOT AArch64 ($mach): $p"; bad=1; continue; }
  interp=$(readelf -lW "$f" 2>/dev/null | sed -n 's/.*Requesting program interpreter: \(.*\)\]$/\1/p' | head -n 1)
  needed=$(readelf -dW "$f" 2>/dev/null | grep -c '(NEEDED)' || true)
  if [ -z "$interp" ] && [ "$needed" = 0 ]; then
    case "$p" in /opt/*) printf 'static\t-\t%s\n' "$p" >> /tmp/elf.tsv;; esac
    continue
  fi
  ld=${interp:-$LDSO}
  out=$(/usr/sbin/chroot "$C" "$ld" --list "$p" 2>&1) && rc=0 || rc=$?
  if [ "$rc" != 0 ] || printf '%s\n' "$out" | grep -q 'not found'; then
    echo "UNRESOLVED in base + layer (rc $rc): $p"; printf '%s\n' "$out" | grep -E 'not found|error|No such' | head -n 5; bad=1; continue
  fi
  case "$p" in /opt/*) printf 'dynamic\t%s\t%s\n' "$ld" "$p" >> /tmp/elf.tsv;; esac
done < <(find "$C" -xdev -type f \( -perm -u+x -o -name '*.so' -o -name '*.so.*' \) -print0)
[ "$bad" = 0 ] || die "the final filesystem is not self-contained: a library must come from the distroless base or the tool's own /opt tree (no third source of shared objects)"
LC_ALL=C sort -k3 /tmp/elf.tsv > "$R/opt/eq/ELF.tsv"
echo "ELF check: $(grep -c '^dynamic' "$R/opt/eq/ELF.tsv" || true) dynamic, $(grep -c '^static' "$R/opt/eq/ELF.tsv" || true) static ELF files under /opt resolve in base + layer"
# the base's executables (outside /opt), for verify-tools.sh --deep and check.sh: what the distroless packages bring
( cd "$B" && find . -path ./opt -prune -o -type f \( -perm -u+x -o -perm -g+x -o -perm -o+x \) -print | LC_ALL=C sort \
    | while read -r f; do printf '%s  %s\n' "$(sha256sum "$f" | cut -d' ' -f1)" "${f#.}"; done ) > "$R/opt/eq/BASE_EXECUTABLES.txt"
echo "base executables recorded: $(wc -l < "$R/opt/eq/BASE_EXECUTABLES.txt")"

# ---- smoke tests in the chroot (the final filesystem, as root here; check.sh repeats them as 10001 in the real image) ------------
PATH_IN=/opt/eq/bin:/opt/lean/bin:/opt/uv:/opt/python/bin
inroot() { env -i PATH="$PATH_IN" HOME=/tmp TMPDIR=/tmp LANG=C.UTF-8 /usr/sbin/chroot "$C" "$@"; }
[ "$(inroot /bin/sh -c 'echo "${BASH_VERSINFO[0]}.${BASH_VERSINFO[1]}"')" = "$(tm_get tool bash version | cut -d. -f1-2)" ] || die "/bin/sh is not the pinned bash"
if has_tool perl-shim; then
  # the perl alarm wrapper of check_lean.sh (literal copy; tests/test_eq_container_pins.py compares it with check_lean.sh)
  wrapper='my $t = shift; my $pid = fork(); defined $pid or exit 125; if ($pid == 0) { exec @ARGV or exit 127 }
           local $SIG{ALRM} = sub { kill "KILL", $pid; print STDERR "eqlean: timeout\n"; exit 124 };
           alarm $t; waitpid($pid, 0); alarm 0;
           if ($? & 127) { print STDERR "eqlean: killed by signal ", ($? & 127), "\n"; exit(128 + ($? & 127)) }
           exit($? >> 8)'
  rc=0; inroot /opt/eq/bin/perl -e "$wrapper" 1 sleep 5 2>/dev/null || rc=$?
  [ "$rc" = 124 ] || die "perl shim: the timeout wrapper returned $rc, want 124"
  rc=0; inroot /opt/eq/bin/perl -e "$wrapper" 5 true || rc=$?
  [ "$rc" = 0 ] || die "perl shim: the wrapper on true returned $rc"
  rc=0; inroot /opt/eq/bin/perl -e 'print 1' 2>/dev/null || rc=$?
  [ "$rc" = 2 ] || die "perl shim: another script returned $rc, want the refusal 2"
fi
[ "$(inroot bash -c 'echo ok; cd /tmp && mktemp -d eqx.XXXXXX >/dev/null && echo ok2' | tr '\n' ' ')" = "ok ok2 " ] || die "bash/mktemp smoke failed"
# F4: the harness and lib.sh start every check as `/bin/sh -c 'cp -R /eqsrc/work/. /work/ && exec "$@"'`
[ -d "$R/eqsrc/work" ] || die "/eqsrc/work missing in the layer"
inroot /bin/sh -c 'cd /tmp && rm -rf eqcp && mkdir -p eqcp/a/b && echo x > eqcp/a/b/f && echo y > eqcp/a/.d && mkdir -p eqcp/c && cp -R eqcp/a/. eqcp/c/ && test -f eqcp/c/b/f && test -f eqcp/c/.d && rm -rf eqcp' \
  || die "the cp -R copy smoke test failed"
if has_tool lake-shim; then
  [ "$(inroot lake env printenv LEAN_PATH)" = "$(cat /opt/eq/LEAN_PATH.real)" ] || die "lake shim: LEAN_PATH differs from the real lake's"
fi
has_tool lean && { inroot lean --version | grep -F "version $(tm_get tool lean version)" || die "lean --version"; }
has_tool python && { inroot python3 --version | grep -F "$(tm_get tool python version)" || die "python3 --version"; }
has_tool uv && { inroot uv --version | grep -F "$(tm_get tool uv version)" || die "uv --version"; }
has_tool jq && { [ "$(inroot jq --version)" = "jq-$(tm_get tool jq version)" ] || die "jq --version"; }
inroot busybox true || die "busybox true"
rm -rf "$C"
echo "rootfs checks passed"

# ---- manifest of every file of the layer (sha256), then its root hash (two builds from the same pins: equal, checklist D4) ---------
( cd "$R" && find . \( -type f -o -type l \) ! -path './opt/eq/MANIFEST*' -print0 | LC_ALL=C sort -z \
    | while IFS= read -r -d '' f; do
        if [ -L "$f" ]; then printf 'LINK %s -> %s\n' "$f" "$(readlink "$f")"; else printf '%s  %s\n' "$(sha256sum "$f" | cut -d' ' -f1)" "$f"; fi
      done ) > "$R/opt/eq/MANIFEST.sha256"
root=$(sha256sum "$R/opt/eq/MANIFEST.sha256" | cut -d' ' -f1)
echo "$root" > "$R/opt/eq/MANIFEST.root"
echo "files: $(find "$R" -type f | wc -l)  links: $(find "$R" -type l | wc -l)  bytes: $(du -sb "$R" | cut -f1)"
echo "MANIFEST_ROOT_SHA256=$root"
