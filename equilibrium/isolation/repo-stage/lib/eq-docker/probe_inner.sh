#!/bin/bash
# shellcheck disable=SC2016,SC2012,SC2086,SC2329,SC2015,SC2013
# probe_inner.sh: runs INSIDE the container (passed by probe.sh as `bash -c "$(cat probe_inner.sh)" probe ARGS`).
# It only reads and tries benign writes/connects; each result line is  T|name|PASS/FAIL/INFO|detail
# args: $1 canary that exists only OUTSIDE the mounts on the host, $2 canary in /work (control), $3 canary in a host env
#       var, $4 expected pids.max, $5 expected memory.max (bytes), $6 expected cpu.max quota (us per 100000),
#       $7 expected size of the tmpfs /work in bytes (empty: only report it)
set -u
out=$1; in=$2; envc=$3; want_pids=$4; want_mem=$5; want_cpu=$6; want_work=${7:-}
t() { echo "T|$1|$2|$3"; }

# identity, capabilities, privilege escalation
uid=$(id -u)
if [ "$uid" != 0 ]; then t user_nonroot PASS "uid=$uid gid=$(id -g)"; else t user_nonroot FAIL "uid 0"; fi
ce=$(awk '/^CapEff/{print $2}' /proc/self/status); cb=$(awk '/^CapBnd/{print $2}' /proc/self/status)
if [ "$ce" = 0000000000000000 ] && [ "$cb" = 0000000000000000 ]; then t caps_dropped PASS "CapEff=$ce CapBnd=$cb"; else t caps_dropped FAIL "CapEff=$ce CapBnd=$cb"; fi
nnp=$(awk '/^NoNewPrivs/{print $2}' /proc/self/status)
if [ "$nnp" = 1 ]; then t no_new_privs PASS "NoNewPrivs=1"; else t no_new_privs FAIL "NoNewPrivs=$nnp"; fi
sc=$(awk '/^Seccomp:/{print $2}' /proc/self/status)
if [ "$sc" = 2 ]; then t seccomp_filter PASS "Seccomp=2 (filter)"; else t seccomp_filter INFO "Seccomp=$sc"; fi

# filesystem: only /work (rw) and /tmp (tmpfs) are writable
rootopts=$(awk '$2=="/"{print $4}' /proc/mounts | head -n 1)
case ",$rootopts," in *,ro,*) t rootfs_readonly PASS "/ mounted ro";; *) t rootfs_readonly FAIL "/ options: $rootopts";; esac
wrote=""
for p in /usr/eq_probe /opt/eq_probe /opt/eq/stack_mathlib/eq_probe /opt/lean/eq_probe /etc/eq_probe /var/eq_probe /home/eq_probe \
         /root/eq_probe /bin/eq_probe /eq_probe /work/../eq_probe /fixture/eq_probe /fixture/statement.txt \
         /eqsrc/work/eq_probe /eqsrc/work/in_scope.txt /eqsrc/eq_probe; do
  if ( : >> "$p" ) 2>/dev/null; then wrote="$wrote $p"; fi
done
if [ -z "$wrote" ]; then t write_outside_copy PASS "all targets refused (/usr /opt /etc /var /home /root /bin / /fixture)"; else t write_outside_copy FAIL "writable:$wrote"; fi
wd=$(find / \( -path /proc -o -path /sys -o -path /dev -o -path /tmp -o -path /work \) -prune -o -type d -print 2>/dev/null | while read -r d; do [ -w "$d" ] && echo "$d"; done | head -n 5 | tr '\n' ' ')
if [ -z "$wd" ]; then t no_writable_dirs_elsewhere PASS "no directory outside /tmp,/work passes test -w"; else t no_writable_dirs_elsewhere FAIL "$wd"; fi
if ( echo ok > /work/eq_probe_write ) 2>/dev/null; then t work_writable PASS "positive control: /work accepts writes"; else t work_writable FAIL "cannot write /work (the tmpfs /work must be mode 1777)"; fi
if ( echo ok > /tmp/eq_probe_tmp && echo marker > /tmp/eq_probe_marker ) 2>/dev/null; then t tmp_writable PASS "positive control: /tmp tmpfs"; else t tmp_writable FAIL "cannot write /tmp"; fi
ft=$(awk '$2=="/tmp"{print $3}' /proc/mounts | head -n 1)
if [ "$ft" = tmpfs ]; then t tmp_is_tmpfs PASS "/tmp fstype tmpfs"; else t tmp_is_tmpfs FAIL "/tmp fstype '$ft'"; fi
# F4: /work is a capped tmpfs (a copy), never a writable host directory; the host copy is /eqsrc/work, read-only
wt=$(awk '$2=="/work"{print $3; exit}' /proc/mounts); wo=$(awk '$2=="/work"{print $4; exit}' /proc/mounts)
if [ "$wt" = tmpfs ]; then t work_is_tmpfs PASS "/work fstype tmpfs ($wo)"; else t work_is_tmpfs FAIL "/work fstype '${wt:-none}': a host directory is writable from the container"; fi
wk=$(printf '%s' "$wo" | tr ',' '\n' | sed -n 's/^size=\([0-9][0-9]*\)k$/\1/p' | head -n 1)
if [ -n "$wk" ]; then wbytes=$((wk * 1024)); else wbytes=none; fi
if [ -z "$want_work" ]; then t work_tmpfs_size INFO "size option: $wbytes bytes"
elif [ "$wbytes" = "$want_work" ]; then t work_tmpfs_size PASS "/work tmpfs size=$wbytes bytes"
else t work_tmpfs_size FAIL "/work tmpfs size is $wbytes bytes, want $want_work"; fi
ero=$(awk '$2=="/eqsrc/work"{print $4; exit}' /proc/mounts)
case ",$ero," in *,ro,*) t eqsrc_mounted_ro PASS "/eqsrc/work ro";; *) t eqsrc_mounted_ro FAIL "/eqsrc/work options: ${ero:-not mounted}";; esac
if [ -x /bin/sh ] && /bin/sh -c 'exit 0' 2>/dev/null; then t bin_sh_present PASS "/bin/sh runs (the /work copy prefix needs it)"; else t bin_sh_present FAIL "/bin/sh missing or not executable"; fi

# visibility: planted secrets, oracle-like dirs, host paths, docker socket, mount table
hits=$(grep -rls -- "$out" /work /eqsrc /fixture /in /tmp /etc /home /root /mnt /srv /var /run /media /opt/eq/PROVENANCE.txt 2>/dev/null | tr '\n' ' ')
ctl=$(grep -rls -- "$in" /work 2>/dev/null | tr '\n' ' ')
if [ -z "$ctl" ]; then t grep_control INFO "WARN: control canary in /work not found, scan result unreliable"; fi
if [ -z "$hits" ]; then t planted_secret_invisible PASS "host canary (sibling dirs of the copy) not found; grep control ok: ${ctl:-none}"; else t planted_secret_invisible FAIL "found in: $hits"; fi
if grep -qs -- "$envc" /proc/self/environ; then t host_env_not_passed FAIL "host env canary present"; else t host_env_not_passed PASS "host env var not inherited"; fi
sens=$(env | cut -d= -f1 | grep -iE 'token|secret|key|passw|credential|anthropic|aws|github|ssh|proxy' | tr '\n' ' ')
if [ -z "$sens" ]; then t env_names_clean PASS "no secret-like variable names"; else t env_names_clean FAIL "$sens"; fi
seen=""
for p in /Users /Volumes /host_mnt /mnt/host /private /oracle /grading_keys /.eq /run/host-services /var/run/docker.sock /run/docker.sock \
         /var/run/secrets /root/.ssh /root/.aws /home/pmrj /fixture/oracle /work/oracle; do
  [ -e "$p" ] && seen="$seen $p"
done
if [ -z "$seen" ]; then t host_paths_absent PASS "no /Users /Volumes /oracle /grading_keys docker.sock ..."; else t host_paths_absent FAIL "exist:$seen"; fi
if [ -z "$(ls -A /items 2>/dev/null)" ]; then t items_dir_empty PASS "/items empty (only mounted by selftest stages)"; else t items_dir_empty FAIL "/items not empty"; fi
mt=$(awk '$3 ~ /^(virtiofs|fuse.*|9p|grpcfuse|fakeowner|ext4|btrfs|xfs|nfs.*|vboxsf)$/ {print $2}' /proc/mounts | sort -u | tr '\n' ' ')
bad=""
for m in $mt; do case "$m" in /eqsrc/work|/fixture|/in|/eq/tunnel|/etc/resolv.conf|/etc/hostname|/etc/hosts) ;; *) bad="$bad $m";; esac; done
if [ -z "$bad" ]; then t only_expected_host_mounts PASS "host-backed mounts: $mt"; else t only_expected_host_mounts FAIL "unexpected:$bad (all: $mt)"; fi
fro=$(awk '$2=="/fixture"{print $4}' /proc/mounts | head -n 1)
case ",$fro," in *,ro,*) t fixture_mounted_ro PASS "/fixture ro";; *) t fixture_mounted_ro FAIL "/fixture options: $fro";; esac

# network: loopback only (pure bash /dev/tcp so it also runs in the FROM-scratch images that have no python)
reach=""
for hp in 1.1.1.1:443 8.8.8.8:53 172.17.0.1:80 192.168.65.254:80; do
  h=${hp%:*}; p=${hp#*:}
  err=$(timeout 3 bash -c "exec 3<>/dev/tcp/$h/$p" 2>&1); rc=$?
  if [ $rc = 0 ] || printf '%s' "$err" | grep -qi 'refused'; then reach="$reach $hp"; fi
done
if [ -z "$reach" ]; then t network_connect_fails PASS "4 external connects failed"; else t network_connect_fails FAIL "reachable:$reach"; fi
err=$(timeout 3 bash -c 'exec 3<>/dev/tcp/example.com/443' 2>&1); rc=$?
if [ $rc = 0 ]; then t dns_fails FAIL "example.com resolved and connected"; else t dns_fails PASS "$(printf '%s' "$err" | tr '\n' ' ' | cut -c1-80)"; fi
ifs=$(ls /sys/class/net 2>/dev/null | tr '\n' ',' | sed 's/,$//')
if [ "$ifs" = lo ]; then t only_loopback_interface PASS "interfaces: lo"; else t only_loopback_interface FAIL "interfaces: ${ifs:-unreadable}"; fi

# cgroup limits actually applied (cgroup v2, as `docker info` reports)
cg=/sys/fs/cgroup
pm=$(cat $cg/pids.max 2>/dev/null); mm=$(cat $cg/memory.max 2>/dev/null); cm=$(cat $cg/cpu.max 2>/dev/null); sm=$(cat $cg/memory.swap.max 2>/dev/null)
if [ "$pm" = "$want_pids" ]; then t pids_limit_set PASS "pids.max=$pm"; else t pids_limit_set FAIL "pids.max=$pm want $want_pids"; fi
if [ "$mm" = "$want_mem" ]; then t memory_limit_set PASS "memory.max=$mm"; else t memory_limit_set FAIL "memory.max=$mm want $want_mem"; fi
case "$cm" in "$want_cpu 100000") t cpu_limit_set PASS "cpu.max=$cm";; *) t cpu_limit_set FAIL "cpu.max=$cm want '$want_cpu 100000'";; esac
if [ "$sm" = 0 ]; then t swap_disabled PASS "memory.swap.max=0"; else t swap_disabled INFO "memory.swap.max=${sm:-unreadable}"; fi

# X2 allowlist rows: no host PATH, no docker socket, no home mount, no route out, the tools are the manifest's and hash-verified, and
# nothing that holds a tool is writable. (The image's PATH is fixed by its ENV; env_extra could only add to it, and these rows would see it.)
badp=""
oldifs=$IFS; IFS=:
for d in $PATH; do
  case "$d" in ""|.|./*|*..*|/tmp|/tmp/*|/work|/work/*|/eqsrc|/eqsrc/*|/eq/*|/Users/*|/Volumes/*|/home/*|/root|/root/*|/opt/homebrew*|/usr/local/Cellar*) badp="$badp [$d]";; esac
  [ -d "$d" ] || badp="$badp [missing:$d]"
done
IFS=$oldifs
if [ -z "$badp" ]; then t host_path_not_inherited PASS "PATH=$PATH: image directories only"; else t host_path_not_inherited FAIL "PATH has:$badp"; fi
mopts() { awk -v p="$1" '{ m = $2; if ((m == "/" || p == m || index(p, m "/") == 1) && length(m) >= best) { best = length(m); o = $4 } } END { print o }' /proc/mounts; }
rwp=""
oldifs=$IFS; IFS=:
for d in $PATH; do
  [ -d "$d" ] || continue
  case ",$(mopts "$d")," in *,ro,*) ;; *) rwp="$rwp $d";; esac
  [ -w "$d" ] && rwp="$rwp $d(test -w)"
done
IFS=$oldifs
if [ -z "$rwp" ]; then t path_dirs_readonly PASS "every PATH directory is on a read-only mount and not writable"; else t path_dirs_readonly FAIL "writable:$rwp"; fi
lockf=/opt/eq/TOOLS.lock.sha256
if [ -f "$lockf" ]; then
  nlock=$(wc -l < "$lockf" | tr -d ' ')
  if sha256sum -c "$lockf" >/tmp/eq_lock.out 2>&1; then t tools_hash_verified PASS "sha256sum -c TOOLS.lock.sha256: $nlock tool files match the build-time lock"
  else t tools_hash_verified FAIL "$(head -n 3 /tmp/eq_lock.out | tr '\n' ' ')"; fi
  locks=" $(cut -d' ' -f1 "$lockf" | tr '\n' ' ')"
  extra=""
  oldifs=$IFS; IFS=:
  for d in $PATH; do
    for f in "$d"/*; do
      [ -f "$f" ] && [ -x "$f" ] || continue
      h=$(sha256sum "$f" | cut -d' ' -f1)
      case "$locks" in *" $h "*) ;; *) extra="$extra $f";; esac
    done
  done
  IFS=$oldifs
  if [ -z "$extra" ]; then t path_executables_allowlisted PASS "every executable on PATH hashes to a tool in the lock (symlinks followed)"; else t path_executables_allowlisted FAIL "not in the manifest lock:$extra"; fi
elif [ -f /opt/eq/IMAGE_KIND ]; then
  t tools_hash_verified FAIL "no /opt/eq/TOOLS.lock.sha256 in a manifest-built image"
  t path_executables_allowlisted FAIL "no lock to check PATH against"
else
  t tools_hash_verified INFO "baseline image (no TOOLS.lock): the tools are pinned by the Dockerfile only"
  t path_executables_allowlisted INFO "baseline image (no TOOLS.lock)"
fi
tm=""
for m in $(awk '$2 ~ /^\/(eq\/tools|opt|usr)(\/|$)/ { print $2 }' /proc/mounts | sort -u); do
  case ",$(mopts "$m")," in *,ro,*) ;; *) tm="$tm $m";; esac
done
if [ -z "$tm" ]; then t tools_mount_readonly PASS "no writable mount under /opt, /usr or /eq/tools (tools are baked into the image or mounted read-only)"; else t tools_mount_readonly FAIL "writable:$tm"; fi
socks=$(find / \( -path /proc -o -path /sys -o -path /dev \) -prune -o -type s ! -path '/eq/tunnel/*' -print 2>/dev/null | head -n 5 | tr '\n' ' ')
case "$socks$(env | grep -E '^(DOCKER_HOST|DOCKER_CONFIG|DOCKER_CONTEXT)=' | tr '\n' ' ')" in
  "") t no_docker_socket PASS "no unix socket outside /eq/tunnel, no DOCKER_* variable";;
  *) t no_docker_socket FAIL "sockets or variables: $socks$(env | grep -E '^DOCKER_' | tr '\n' ' ')";;
esac
hm=$(awk '$2 ~ /^\/(home|root|Users|host_mnt)(\/|$)/ { print $2 }' /proc/mounts | tr '\n' ' ')
hf=$(awk -v h="${HOME:-/}" '$2 == h { print $3 }' /proc/mounts | head -n 1)
if [ -z "$hm" ] && { [ -z "$hf" ] || [ "$hf" = tmpfs ]; }; then t no_home_mount PASS "no mount at /home, /root, /Users or /host_mnt; HOME=${HOME:-unset} is ${hf:-the image}"; else t no_home_mount FAIL "mounts: $hm HOME fstype ${hf:-none}"; fi
dr=$(awk 'NR > 1 && $2 == "00000000" && $8 == "00000000" { print $1 }' /proc/net/route 2>/dev/null | tr '\n' ' ')
if [ -z "$dr" ]; then t no_default_route PASS "no default route"; else t no_default_route FAIL "default route via interface: $dr"; fi

# toolchain still works under the flags (so the isolation does not just break everything)
ran=""; badtool=""
for tl in lean uv python3; do
  if command -v "$tl" >/dev/null 2>&1; then
    if "$tl" --version >/dev/null 2>&1; then ran="$ran $tl"; else badtool="$badtool $tl"; fi
  fi
done
if [ -z "$badtool" ] && [ -n "$ran" ]; then t tools_run PASS "execute:$ran"; else t tools_run FAIL "ran:${ran:-none} failed:${badtool:-none}"; fi

# attack-surface inventory (INFO: compares the images; not a pass/fail criterion)
suid=$(find / \( -path /proc -o -path /sys -o -path /dev \) -prune -o -type f \( -perm -4000 -o -perm -2000 \) -print 2>/dev/null | head -n 20 | tr '\n' ' ')
t setuid_setgid_files INFO "${suid:-none}"
tools=""
for c in python3 perl awk sed find xargs git curl wget nc ssh gcc cc make apt apt-get dpkg pip busybox su sudo; do command -v "$c" >/dev/null 2>&1 && tools="$tools $c"; done
t tools_on_path INFO "${tools:-none}"
t image_kind INFO "$(cat /opt/eq/IMAGE_KIND 2>/dev/null || echo full-debian)"
