#!/usr/bin/env bash
# probe hook (probe.sh section G): what the `eqdb` network of compose.yaml promises, proven with the image under probe on a throw-away
# `docker network create --internal` network (the same option compose.yaml sets): a container attached to it has an interface but no
# default route, reaches no external address and resolves no external name. Skipped (INFO) for an image without bash.
# The network is removed on exit. It does not start a database; it proves the isolation the database services rely on.
# shellcheck disable=SC2034,SC2016  # EQ_RUN_* are read by eq_run in lib.sh; the container script is meant to be single-quoted
set -u
: "${EQ_PROBE_IMAGE:?run through probe.sh}" "${EQ_PROBE_LIB:?run through probe.sh}"
# shellcheck disable=SC1090
. "$EQ_PROBE_LIB"
net="eq-probe-$EQ_RUN_ID"
if ! docker network create --internal "$net" >/dev/null 2>&1; then
  echo "T|internal_net_created|FAIL|docker network create --internal $net failed"; exit 1
fi
trap 'docker network rm "$net" >/dev/null 2>&1' EXIT
eq_require_image "$EQ_PROBE_IMAGE"
EQ_RUN_IMAGE=$EQ_PROBE_IMAGE; EQ_RUN_MOUNTS=(); EQ_RUN_STDIN=""
EQ_RUN_EXTRA=(--network "$net")      # later flags override the base flags' --network none
res=$(eq_run "eq-$EQ_RUN_ID-probe-intnet" 120 bash -c '
echo "INT_IF=$(ls /sys/class/net | grep -v "^lo$" | tr "\n" ",")"
echo "INT_ROUTE=$(awk "NR > 1 && \$2 == \"00000000\" && \$8 == \"00000000\" { print \$1 }" /proc/net/route | tr "\n" " ")"
reach=""
for hp in 1.1.1.1:443 8.8.8.8:53 172.17.0.1:80; do
  h=${hp%:*}; p=${hp#*:}
  err=$(timeout 3 bash -c "exec 3<>/dev/tcp/$h/$p" 2>&1); rc=$?
  if [ $rc = 0 ] || printf "%s" "$err" | grep -qi refused; then reach="$reach $hp"; fi
done
echo "INT_REACH=$reach"
timeout 3 bash -c "exec 3<>/dev/tcp/example.com/443" >/dev/null 2>&1 && echo "INT_DNS=resolved" || echo "INT_DNS=none"' 2>&1)
rc=$?
if [ "$rc" != 0 ] && ! printf '%s' "$res" | grep -q '^INT_IF='; then
  echo "T|internal_net_attached|INFO|the container could not run bash on the internal network (rc $rc): $(printf '%s' "$res" | tr '\n' ' ' | cut -c1-120)"; exit 0
fi
ifs=$(printf '%s\n' "$res" | sed -n 's/^INT_IF=//p' | head -n 1)
route=$(printf '%s\n' "$res" | sed -n 's/^INT_ROUTE=//p' | head -n 1)
reach=$(printf '%s\n' "$res" | sed -n 's/^INT_REACH=//p' | head -n 1)
dns=$(printf '%s\n' "$res" | sed -n 's/^INT_DNS=//p' | head -n 1)
if [ -n "$ifs" ]; then echo "T|internal_net_attached|PASS|the container is on the internal network: interface(s) $ifs"; else echo "T|internal_net_attached|FAIL|no interface besides lo: the test did not run on the network"; fi
if [ -z "${route// /}" ]; then echo "T|internal_net_no_default_route|PASS|no default route on the internal network"; else echo "T|internal_net_no_default_route|FAIL|default route via $route"; fi
if [ -z "${reach// /}" ] && [ "$dns" = none ]; then echo "T|internal_net_no_egress|PASS|1.1.1.1:443, 8.8.8.8:53, 172.17.0.1:80 and example.com unreachable"; else echo "T|internal_net_no_egress|FAIL|reachable:$reach dns=$dns"; fi
exit 0
