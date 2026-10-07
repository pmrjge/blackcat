# check.sh VARIANT   (busybox sh, POSIX; the check-<target> stages of Dockerfile.minimal run it in exec form:
#   RUN ["/opt/eq/bin/busybox", "sh", "/opt/eq-check/check.sh", "both"]
# FROM the final target, so it sees the REAL final filesystem (distroless base + the assembled layer) as the image's user 10001.
# build.sh builds check-<target> before the target itself (same cache): a failure here is exit 12 and nothing is recorded.
# It re-checks, in the image, what minimal/mkrootfs.sh checked in its chroot: the user, /bin/sh = the pinned bash, every dynamic
# ELF under /opt resolves (the loader's --list over /opt/eq/ELF.tsv), the tool and base executables hash to their lists, no
# setuid/setgid file, no debug shell, no package manager, bash's /dev/tcp compiled in, the perl shim's timeout wrapper, the
# cp -R copy-in, and the tools' versions.
# shellcheck shell=sh disable=SC2016,SC2015  # ok() and bad() always return 0
set -u
v=${1:?variant lean|py|both}
B=/opt/eq/bin/busybox
PATH=/opt/eq/bin:/opt/lean/bin:/opt/uv:/opt/python/bin; export PATH
fails=0
ok() { echo "CHECK ok   $*"; }
bad() { echo "CHECK FAIL $*"; fails=$((fails + 1)); }
lockver() { awk -F'\t' -v n="$1" '$1 == n { print $2; exit }' /opt/eq/TOOLS.lock; }
has() { awk -F'\t' -v n="$1" '$1 == n { f = 1 } END { exit !f }' /opt/eq/TOOLS.lock; }

[ "$(id -u):$(id -g)" = 10001:10001 ] && ok "user 10001:10001" || bad "user is $(id -u):$(id -g), want 10001:10001"
[ "$(readlink -f /bin/sh)" = /opt/eq/bin/bash ] && ok "/bin/sh -> /opt/eq/bin/bash" || bad "/bin/sh resolves to $(readlink -f /bin/sh)"
[ "$(readlink -f /usr/bin/bash)" = /opt/eq/bin/bash ] && ok "/usr/bin/bash -> /opt/eq/bin/bash" || bad "/usr/bin/bash resolves to $(readlink -f /usr/bin/bash)"
case "$(cat /opt/eq/IMAGE_KIND 2>/dev/null)" in *" distroless-cc") ok "IMAGE_KIND $(cat /opt/eq/IMAGE_KIND)";; *) bad "IMAGE_KIND is '$(cat /opt/eq/IMAGE_KIND 2>/dev/null)'";; esac

# hashes: the tool files (TOOLS.lock) and the base's executables (recorded by mkrootfs.sh from the base it was given)
sha256sum -c -s /opt/eq/TOOLS.lock.sha256 && ok "TOOLS.lock.sha256: $(wc -l < /opt/eq/TOOLS.lock.sha256) files" || bad "a tool file differs from TOOLS.lock.sha256"
if [ -s /opt/eq/BASE_EXECUTABLES.txt ]; then
  sha256sum -c -s /opt/eq/BASE_EXECUTABLES.txt && ok "BASE_EXECUTABLES.txt: $(wc -l < /opt/eq/BASE_EXECUTABLES.txt) base executables" || bad "a base executable differs from BASE_EXECUTABLES.txt (the base is not the one the layer was checked against)"
else ok "BASE_EXECUTABLES.txt: the base has no executable file outside /opt"; fi

# every dynamic ELF under /opt (mkrootfs.sh's list, readelf-classified): the loader resolves all of its libraries here
n=0
while IFS="$(printf '\t')" read -r kind ld p; do
  [ "$kind" = dynamic ] || continue
  n=$((n + 1))
  out=$("$ld" --list "$p" 2>&1); rc=$?
  if [ "$rc" != 0 ] || printf '%s\n' "$out" | grep -q 'not found'; then bad "unresolved: $p: $(printf '%s' "$out" | grep -E 'not found|No such' | head -n 3 | tr '\n' ' ')"; fi
done < /opt/eq/ELF.tsv
[ "$n" -gt 0 ] && ok "$n dynamic ELF files resolve against the base" || bad "no dynamic ELF in /opt/eq/ELF.tsv"

# nothing privileged, no debug shell, no package manager, anywhere in the image
s=$(find / \( -path /proc -o -path /sys -o -path /dev \) -prune -o -type f \( -perm -4000 -o -perm -2000 \) -print 2>/dev/null | head -n 5 | tr '\n' ' ')
[ -z "$s" ] && ok "no setuid/setgid file" || bad "setuid/setgid: $s"
[ ! -e /busybox ] && ok "no /busybox (no distroless debug shell)" || bad "/busybox exists"
s=$(find / \( -path /proc -o -path /sys -o -path /dev \) -prune -o -type f \( -name apt -o -name apt-get -o -name dpkg -o -name apk -o -name rpm -o -name yum -o -name dnf \) -print 2>/dev/null | head -n 5 | tr '\n' ' ')
[ -z "$s" ] && ok "no package manager" || bad "package manager files: $s"

# bash: the pinned version, network redirections compiled in (a refused loopback connect, never a missing /dev/tcp file)
bv=$(lockver bash)
[ "$(bash -c 'echo "${BASH_VERSINFO[0]}.${BASH_VERSINFO[1]}.${BASH_VERSINFO[2]}"')" = "$bv" ] && ok "bash $bv" || bad "bash is not $bv: $(bash --version | head -n 1)"
err=$(bash -c 'exec 3<>/dev/tcp/127.0.0.1/1' 2>&1) && bad "/dev/tcp/127.0.0.1/1 connected" || {
  case "$err" in *[Rr]efused*|*[Uu]nreachable*) ok "bash /dev/tcp: $(printf '%s' "$err" | tr '\n' ' ' | cut -c1-80)";; *) bad "bash /dev/tcp missing: $err";; esac; }

# the perl shim: check_lean.sh's wrapper (literal copy; tests/test_eq_container_pins.py compares it with check_lean.sh)
if has perl-shim; then
  W='my $t = shift; my $pid = fork(); defined $pid or exit 125; if ($pid == 0) { exec @ARGV or exit 127 }
           local $SIG{ALRM} = sub { kill "KILL", $pid; print STDERR "eqlean: timeout\n"; exit 124 };
           alarm $t; waitpid($pid, 0); alarm 0;
           if ($? & 127) { print STDERR "eqlean: killed by signal ", ($? & 127), "\n"; exit(128 + ($? & 127)) }
           exit($? >> 8)'
  perl -e "$W" 1 sleep 5 2>/dev/null; rc=$?
  [ "$rc" = 124 ] && ok "perl shim: timeout 124" || bad "perl shim: timeout returned $rc, want 124"
  perl -e "$W" 5 sh -c 'exit 3'; rc=$?
  [ "$rc" = 3 ] && ok "perl shim: exit code passed through" || bad "perl shim: exit 3 returned $rc"
  perl -e 'print 1' 2>/dev/null; rc=$?
  [ "$rc" = 2 ] && ok "perl shim: other scripts refused" || bad "perl shim: another script returned $rc, want 2"
fi

# the harness's copy-in prefix: /bin/sh -c 'cp -R SRC/. DST/' (dot files and subdirectories)
d=$(mktemp -d /tmp/eqchk.XXXXXX) && mkdir -p "$d/a/b" "$d/c" && echo x > "$d/a/b/f" && echo y > "$d/a/.d" \
  && /bin/sh -c 'cp -R "$1"/. "$2"/' eq "$d/a" "$d/c" && [ -f "$d/c/b/f" ] && [ -f "$d/c/.d" ] && ok "cp -R copy-in" || bad "cp -R copy-in"
rm -rf "$d"

# the tools of this variant run, at the pinned versions
if [ "$v" != py ]; then
  lean --version | grep -qF "version $(lockver lean)" && ok "lean $(lockver lean)" || bad "lean --version"
  [ "$(lake env printenv LEAN_PATH)" = "$(cat /opt/eq/LEAN_PATH.real)" ] && ok "lake shim LEAN_PATH" || bad "lake shim LEAN_PATH"
fi
if [ "$v" != lean ]; then
  python3 --version | grep -qF "$(lockver python)" && ok "python3 $(lockver python)" || bad "python3 --version"
  uv --version | grep -qF "$(lockver uv)" && ok "uv $(lockver uv)" || bad "uv --version"
  [ "$(jq --version)" = "jq-$(lockver jq)" ] && ok "jq $(lockver jq)" || bad "jq --version"
  printf 'import json, ssl, sqlite3, zlib, zoneinfo\nprint(json.dumps(1))\n' > /tmp/eqchk.py
  [ "$(python3 -I /tmp/eqchk.py)" = 1 ] && ok "python3 imports json ssl sqlite3 zlib zoneinfo" || bad "python3 stdlib imports"
  rm -f /tmp/eqchk.py
fi
"$B" true && ok "busybox" || bad "busybox true"

if [ "$fails" = 0 ]; then echo "CHECK: PASS ($v)"; exit 0; fi
echo "CHECK: FAIL ($fails) ($v)"
exit 1
