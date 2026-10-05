#!/usr/bin/env bash
# shellcheck disable=SC2016,SC2015,SC2317,SC2329,SC3043,SC2034,SC2012
# (SC2317/SC2329: cleanup runs from the trap; SC2012: /proc/$$/fd holds numeric names only)
# (SC2034: EQ_RUN_* and EQ_*_REPORT are read by lib.sh's eq_run / eq_write_result)
# probe.d/50-tunnel.sh — the WALL tunnel probe (SCOPE X7 "only path, proven"; lib/eq-wall/WALL_DESIGN.md §3, §9).
# Backend: Apple `container` (each container is a Linux VM; the channel dir reaches it through a virtiofs bind).
# Proves that a container given the ONE tunnel (a WALL channel directory bind-mounted at /eq/tunnel) has no other
# path to the host: a second socket, an outbound connection, a host path and a signal to a host process are all
# blocked; exactly one host-backed mount exists, at /eq/tunnel; no inherited fds; its own PID namespace.
#
# Two modes in one file (one source of truth for the in-container checks):
#   bash probe.d/50-tunnel.sh            HOST mode (user-run, normal terminal; also run by probe.sh's probe.d hook):
#                                        builds a throwaway 0700 tunnel root with one channel and a sibling channel,
#                                        a host listener socket inside the channel and a host sleeper process, runs
#                                        ONE container with lib.sh's base flags plus exactly one extra mount (the
#                                        channel at /eq/tunnel), then checks the host side. Exit 0 = every row PASS.
#   sh 50-tunnel.sh --inner HOSTPID HOSTROOT CANARY [TUNNEL]
#                                        IN-CONTAINER mode (POSIX sh: busybox, dash or bash). The harness's
#                                        `eq_harness.py isolation-probe` runs this same text through isolate().
# Rows: T|name|PASS|FAIL|INFO|detail. Only benign actions: a connect attempt, kill -0 (no signal delivered), reads.

probe_tunnel_inner() {
  hp=$1; hroot=$2; canary=$3; tun=${4:-/eq/tunnel}
  t() { echo "T|$1|$2|$3"; }

  # 1. exactly one host-backed mount, at the tunnel (the runtime's resolv.conf/hostname/hosts binds excepted; "/" is the
  #    image's own block device in the VM, not a host directory)
  mt=$(awk '$2 != "/" && $3 ~ /^(virtiofs|fuse|fuse\..*|9p|grpcfuse|fakeowner|ext4|btrfs|xfs|nfs.*|vboxsf)$/ {print $2}' /proc/mounts 2>/dev/null \
       | sort -u | grep -v -e '^/etc/resolv.conf$' -e '^/etc/hostname$' -e '^/etc/hosts$' | tr '\n' ' ')
  if [ "$mt" = "$tun " ]; then t tunnel_single_host_mount PASS "host-backed mounts: $mt"
  else t tunnel_single_host_mount FAIL "host-backed mounts: '${mt:-none}' (want exactly $tun)"; fi
  eqm=$(awk '$2 ~ /^\/eq(\/|$)/ {print $2}' /proc/mounts 2>/dev/null | tr '\n' ' ')
  if [ "$eqm" = "$tun " ]; then t eq_namespace_single PASS "/eq holds only $tun"
  else t eq_namespace_single FAIL "mounts under /eq: '${eqm:-none}'"; fi

  # 2. the tunnel works (positive control) and is the only writable host path
  if ( printf 'probe\n' > "$tun/req-probe.json" ) 2>/dev/null; then t tunnel_writable PASS "wrote $tun/req-probe.json"
  else t tunnel_writable FAIL "cannot write $tun"; fi

  # 3. a second socket: no docker/containerd/host-services socket; a host socket inside the tunnel is unusable
  seen=""
  for p in /var/run/docker.sock /run/docker.sock /run/host-services /var/run/host-services /run/containerd \
           /var/run/secrets; do [ -e "$p" ] && seen="$seen $p"; done
  if [ -z "$seen" ]; then t no_host_service_socket PASS "docker.sock, containerd, /run/host-services absent"
  else t no_host_service_socket FAIL "present:$seen"; fi
  if [ -e "$tun/host.sock" ]; then
    if command -v python3 >/dev/null 2>&1; then
      if python3 -c 'import socket,sys; s=socket.socket(socket.AF_UNIX); s.settimeout(3); s.connect(sys.argv[1])' \
           "$tun/host.sock" 2>/dev/null; then t second_socket_blocked FAIL "connected to the host socket $tun/host.sock"
      else t second_socket_blocked PASS "connect to the host socket in the tunnel failed"; fi
    else t second_socket_blocked INFO "no AF_UNIX client in this image (host side checks the listener)"; fi
  else t second_socket_blocked INFO "host socket not visible in the tunnel"; fi

  # 4. outbound connections (pure bash /dev/tcp where bash exists; python3 otherwise)
  reach=""; tried=""
  for hp2 in 1.1.1.1:443 8.8.8.8:53 192.168.64.1:80 192.168.65.254:80 172.17.0.1:80 host.docker.internal:80; do
    h=${hp2%:*}; p=${hp2#*:}
    if command -v bash >/dev/null 2>&1; then
      tried=bash
      err=$(timeout 3 bash -c "exec 3<>/dev/tcp/$h/$p" 2>&1); rc=$?
      if [ $rc = 0 ] || printf '%s' "$err" | grep -qi refused; then reach="$reach $hp2"; fi
    elif command -v python3 >/dev/null 2>&1; then
      tried=python3
      if python3 -c 'import socket,sys; socket.create_connection((sys.argv[1], int(sys.argv[2])), 3)' "$h" "$p" \
           2>/dev/null; then reach="$reach $hp2"; fi
    fi
  done
  if [ -z "$tried" ]; then t outbound_blocked INFO "no bash or python3 to attempt a connection"
  elif [ -z "$reach" ]; then t outbound_blocked PASS "6 outbound connects failed ($tried)"
  else t outbound_blocked FAIL "reachable:$reach"; fi

  # 5. host paths: the host tunnel root, macOS and Docker Desktop host paths do not exist in here
  seen=""
  for p in "$hroot" /Users /Volumes /private /host_mnt /mnt/host /run/desktop /Applications; do
    [ -e "$p" ] && seen="$seen $p"
  done
  if [ -z "$seen" ]; then t host_paths_absent PASS "no host tunnel root, /Users, /Volumes, /host_mnt ..."
  else t host_paths_absent FAIL "exist:$seen"; fi
  other=""
  for e in /eq/* /eq/.[!.]*; do
    [ -e "$e" ] || [ -L "$e" ] || continue
    [ "$e" = /eq/tunnel ] || other="$other $e"
  done
  if [ -n "$other" ]; then t sibling_channels_invisible FAIL "/eq holds more than tunnel:$other"
  elif grep -rqs -- "$canary" /eq /tmp /work 2>/dev/null; then t sibling_channels_invisible FAIL "sibling canary found"
  else t sibling_channels_invisible PASS "only this channel is visible"; fi

  # 6. a signal to a host process: kill -0 (no signal delivered) must find no such process
  if kill -0 "$hp" 2>/dev/null; then
    t host_signal_blocked FAIL "pid $hp is signalable here: $(tr '\0' ' ' 2>/dev/null < "/proc/$hp/cmdline" | cut -c1-60)"
  else t host_signal_blocked PASS "kill -0 $hp refused (own PID namespace)"; fi
  p1=$( (tr '\0' ' ' < /proc/1/cmdline) 2>/dev/null)
  # the container is its own Linux VM: its pid 1 is the --init process (or the VM's init), never a host process
  case "$p1" in "") t own_pid_namespace FAIL "pid 1 unreadable";; *) t own_pid_namespace PASS "pid 1: $p1 (guest kernel $(uname -r 2>/dev/null))";; esac

  # 7. no inherited file descriptors beyond stdio (255: bash's own script fd)
  fds=$(ls /proc/$$/fd 2>/dev/null | tr '\n' ' ')
  extra=""
  for f in $fds; do case "$f" in 0|1|2|255) ;; *) extra="$extra $f";; esac; done
  if [ -z "$fds" ]; then t no_inherited_fds INFO "/proc/$$/fd unreadable"
  elif [ -z "$extra" ]; then t no_inherited_fds PASS "fds: $fds"
  else t no_inherited_fds FAIL "extra fds:$extra (all: $fds)"; fi

  # 8. a socket created in the tunnel by the container (reported; the broker never connects to sockets)
  if command -v python3 >/dev/null 2>&1; then
    python3 -c 'import socket,sys; s=socket.socket(socket.AF_UNIX); s.bind(sys.argv[1])' "$tun/ctr.sock" 2>/dev/null \
      && t container_socket_in_tunnel INFO "created $tun/ctr.sock (the broker removes it unread)" \
      || t container_socket_in_tunnel INFO "socket creation in the tunnel failed"
  fi
}

if [ "${1:-}" = --inner ]; then
  shift
  probe_tunnel_inner "$@"
  exit 0
fi

# ---- HOST mode (bash) ----------------------------------------------------------------------------------------------
if [ -n "${BASH_SOURCE:-}" ] && [ "${BASH_SOURCE[0]}" != "$0" ]; then
  # sourced by a probe.d hook: run in a child bash so nothing here touches the caller's state or exits it
  bash "${BASH_SOURCE[0]}"
  return $?
fi
set -u
self=$(cd "$(dirname "$0")" && pwd -P)/$(basename "$0")
iso=$(cd "$(dirname "$0")/.." && pwd -P)
# probe.sh section G runs every hook with EQ_PROBE_HOOK/EQ_PROBE_IMAGE/EQ_PROBE_LIB set: then the rows go out as
# `T|name|RESULT|detail` lines (the hook contract: no row, or a non-zero exit without a FAIL row, is a FAIL) and the
# image under probe is EQ_PROBE_IMAGE. Standalone: lib.sh's profile image and a human-readable table.
hook=${EQ_PROBE_HOOK:-}
# shellcheck disable=SC1090,SC1091
. "${EQ_PROBE_LIB:-$iso/lib.sh}"
img=${EQ_PROBE_IMAGE:-$(eq_img_tag min-both)}
[ -z "$hook" ] || img=${EQ_PROBE_IMAGE:?probe.sh sets EQ_PROBE_IMAGE for its hooks}
early_fail() {  # a precondition failed before any container ran: still one FAIL row, never a silent exit
  if [ -n "$hook" ]; then echo "T|$1|FAIL|$2"; else echo "TUNNEL PROBE: FAIL: $2" >&2; fi
  exit 1
}
( eq_need_container ) || early_fail tunnel_container "the container CLI or its services are not usable (eq_need_container)"
( eq_require_image "$img" ) || early_fail tunnel_image "image $img missing or not covered by a build record"
eq_require_image "$img"
EQ_RUN_IMAGE_REPORT=${img%@*}; EQ_IMAGE_ID_REPORT=$EQ_IMAGE_DIGEST_NOW; EQ_RUN_IMAGE=$img

rows=(); trows=(); fails=0
row() {
  rows[${#rows[@]}]=$(printf '%-34s %-6s %s' "$1" "$2" "$3")
  trows[${#trows[@]}]="T|$1|$2|$3"
  [ "$2" = FAIL ] && fails=$((fails + 1))
  return 0
}
rand() { od -An -N16 -tx1 /dev/urandom | tr -d ' \n'; }

root=$(mktemp -d "$EQ_WORK_ROOT/tunnel.XXXXXX") && chmod 700 "$root"
run="$root/$(rand)"; chan="$run/c$(rand)"; sib="$run/c$(rand)"
mkdir -m 700 "$run" "$chan" "$sib"
canary="EQCANARY-SIBLING-$(rand)"
echo "$canary" > "$sib/canary.txt"
listener_pid=""; sleeper_pid=""
cleanup() {
  [ -n "$listener_pid" ] && kill "$listener_pid" 2>/dev/null
  [ -n "$sleeper_pid" ] && kill "$sleeper_pid" 2>/dev/null
  eq_sweep
  rm -rf "$root"
}
trap cleanup EXIT INT TERM

# a host listener INSIDE the channel (relative bind: the AF_UNIX path-length limit); perl ships with macOS
( cd "$chan" && exec perl -MIO::Socket::UNIX -MSocket -e '
    my $s = IO::Socket::UNIX->new(Type => SOCK_STREAM(), Local => "host.sock", Listen => 1) or die "bind: $!";
    $s->blocking(0); my $t0 = time;
    while (time - $t0 < 170) { if (my $c = $s->accept) { print "CONNECTED\n"; exit 0 } select(undef, undef, undef, 0.2) }
    print "NOCONN\n";' > "$root/listener.out" 2>&1 ) &
listener_pid=$!
sleep 300 & sleeper_pid=$!
i=0; while [ ! -S "$chan/host.sock" ] && [ $i -lt 50 ]; do sleep 0.1; i=$((i + 1)); done
[ -S "$chan/host.sock" ] || row host_listener_socket INFO "could not create the host listener: $(cat "$root/listener.out")"

EQ_RUN_MOUNTS=(); EQ_RUN_STDIN=""; EQ_RUN_TUNNEL=$chan   # the ONE read-write host mount: the channel at /eq/tunnel
res=$(eq_run "eq-$EQ_RUN_ID-tunnel" 120 /bin/sh -c "$(cat "$self")" probe-tunnel --inner "$sleeper_pid" "$root" "$canary" /eq/tunnel 2>&1)
rc=$?
while IFS='|' read -r tag name result detail; do
  [ "$tag" = T ] && row "$name" "$result" "$detail"
done <<EOF
$(printf '%s\n' "$res" | grep '^T|')
EOF
printf '%s\n' "$res" | grep -q '^T|' || row container_tunnel_probe FAIL "rc $rc: $(printf '%s' "$res" | tr '\n' ' ' | cut -c1-200)"
for need in tunnel_single_host_mount eq_namespace_single tunnel_writable no_host_service_socket outbound_blocked \
            host_paths_absent sibling_channels_invisible host_signal_blocked own_pid_namespace no_inherited_fds; do
  printf '%s\n' "$res" | grep -q "^T|$need|" || row "$need" FAIL "the in-container probe did not report this row"
done

# host side
if [ -f "$chan/req-probe.json" ]; then row tunnel_roundtrip PASS "a file written at /eq/tunnel reached the host channel"
else row tunnel_roundtrip FAIL "nothing arrived in $chan"; fi
kill "$listener_pid" 2>/dev/null; wait "$listener_pid" 2>/dev/null; listener_pid=""
if grep -q CONNECTED "$root/listener.out" 2>/dev/null; then row host_socket_not_reached FAIL "the container connected to the host listener"
else row host_socket_not_reached PASS "no connection reached the host listener"; fi
if kill -0 "$sleeper_pid" 2>/dev/null; then row host_process_unsignalled PASS "host sleeper $sleeper_pid alive"
else row host_process_unsignalled FAIL "host sleeper gone"; fi
if [ "$(cat "$sib/canary.txt")" = "$canary" ] && [ "$(ls -A "$sib")" = canary.txt ]; then row sibling_channel_unchanged PASS ""
else row sibling_channel_unchanged FAIL "the sibling channel changed"; fi
if [ -S "$chan/ctr.sock" ]; then row container_socket_on_host INFO "a container-created socket appears on the host as a socket"
elif [ -e "$chan/ctr.sock" ]; then row container_socket_on_host INFO "a container-created socket appears on the host as a non-socket"; fi

if [ -n "$hook" ]; then
  for r in "${trows[@]}"; do echo "$r"; done
else
  echo
  echo "image: $img ($EQ_IMAGE_ID_REPORT)"
  printf '%-34s %-6s %s\n' PROPERTY RESULT DETAIL
  for r in "${rows[@]}"; do echo "$r"; done
  echo
fi
if [ "$fails" = 0 ]; then eq_write_result tunnel PASS 0; echo "TUNNEL PROBE: PASS (${#rows[@]} rows)"; exit 0; fi
eq_write_result tunnel FAIL "$fails"
echo "TUNNEL PROBE: FAIL ($fails failing rows). The WALL stays off until they are understood."
exit 1
