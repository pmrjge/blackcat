#!/usr/bin/env bash
# shellcheck disable=SC2016,SC2012,SC2086,SC2329,SC2015
# probe.sh (user-run): proves the isolation properties from inside the container, with the same flags as every check.
#   [EQ_IMAGE=<tag|id|name@sha256:..>] [EQ_IMAGE_PY=<..>] [EQ_PROBE_EXTRA_IMAGES="<ref> <ref>"] ./probe.sh   (needs only bash +
#   busybox/coreutils in the image)
# EQ_IMAGE overrides the lean image (default: the recorded eq-lean, or the profile's). Every DIFFERENT image among EQ_IMAGE,
# EQ_IMAGE_PY and EQ_PROBE_EXTRA_IMAGES (for example the CR image when it is not the CP image) is probed once, because PF code
# runs in the lean image and CP/CR code in the python image; the exit code is the worst result. The harness's
# `eq_harness.py isolation-probe` passes the images of flags.json in these variables.
# Plants decoys on the host as SIBLINGS of the mounted check copy (an oracle-looking tree, a fake home with an ssh key, a
# grading key, an env var), runs probe_inner.sh in the container, then runs separate containers for the pids limit, the
# memory limit (OOM kill), the /work size cap (ENOSPC), a read-only /in mount (the oracle staging mount of the harness), the
# watchdog kill path and "no state survives". The check copy is mounted read-only at /eqsrc/work and copied into a capped
# tmpfs /work (see lib.sh): the probe proves that a write to /work never reaches the host. No equilibrium pools are needed
# (synthetic fixture). Prints a PASS/FAIL table (INFO rows do not count); exit 1 on any FAIL; result in
# $EQ_STATE_DIR/results/probe.*.env. It tries only benign writes and connects; it does not attack the Lean checker.
# Extension hook (section G below): every probe.d/*.sh runs after the built-in sections, sorted, and its `T|name|RESULT|detail` rows are
# folded into the report and the exit code (probe.d/20-tools-manifest.sh, 30-internal-net.sh, and 50-tunnel.sh from the WALL work).
set -u
here=$(cd "$(dirname "$0")" && pwd -P)
# shellcheck disable=SC1091
. "$here/lib.sh"

eq_need_docker
if [ -z "${EQ_PROBE_SINGLE:-}" ]; then
  imgs=("$EQ_IMAGE_TAG")
  for c in $EQ_IMAGE_PY ${EQ_PROBE_EXTRA_IMAGES:-}; do
    dup=0
    for d in "${imgs[@]}"; do [ "$d" = "$c" ] && dup=1; done
    [ "$dup" = 1 ] || imgs[${#imgs[@]}]=$c
  done
  if [ "${#imgs[@]}" -gt 1 ]; then
    worst=0; k=0
    for img in "${imgs[@]}"; do
      k=$((k + 1)); echo "== probe $k/${#imgs[@]}: image $img"
      EQ_PROBE_SINGLE=1 EQ_IMAGE="$img" EQ_IMAGE_PY="$img" bash "$here/probe.sh"; rc=$?
      [ "$rc" -gt "$worst" ] && worst=$rc
      echo
    done
    exit "$worst"
  fi
fi
eq_require_image "$EQ_IMAGE_TAG"
EQ_RUN_IMAGE_REPORT=$EQ_IMAGE_TAG; EQ_IMAGE_ID_REPORT=$EQ_IMAGE_ID_NOW
EQ_RUN_IMAGE=$EQ_IMAGE_TAG
trap 'eq_sweep; [ -n "${root:-}" ] && rm -rf "$root"' EXIT INT TERM

rows=(); fails=0; seen=" "
row() { rows[${#rows[@]}]=$(printf '%-34s %-6s %s' "$1" "$2" "$3"); [ "$2" = FAIL ] && fails=$((fails + 1)); return 0; }
to_bytes() { # 8g / 512m / 1024k / plain bytes
  case "$1" in
    *[gG]) echo $(( ${1%[gG]} * 1024 * 1024 * 1024 ));;
    *[mM]) echo $(( ${1%[mM]} * 1024 * 1024 ));;
    *[kK]) echo $(( ${1%[kK]} * 1024 ));;
    *) echo "$1";;
  esac
}
sha256_dir() { (cd "$1" && find . -type f | LC_ALL=C sort | while read -r f; do cksum "$f"; done | cksum | cut -d' ' -f1); }
rand() { od -An -N8 -tx1 /dev/urandom | tr -d ' \n'; }

root=$(mktemp -d "$EQ_WORK_ROOT/probe.XXXXXX")
canary_out="EQCANARY-OUT-$(rand)"
canary_in="EQCANARY-IN-$(rand)"
canary_env="EQCANARY-ENV-$(rand)"
export EQ_PROBE_SECRET_ENV="$canary_env"

# decoys: siblings of the copy, i.e. where member copies / the oracle tree sit in the real layout. Synthetic fixture.
mkdir -p "$root/copy" "$root/fixture" "$root/in" "$root/items/PF/oracle/ref" "$root/home/.ssh" "$root/secrets" "$root/grading_keys"
printf 'eq_probe\ntheorem eq_probe : True\n' > "$root/fixture/statement.txt"
printf 'import Mathlib\ntheorem eq_probe : True := by\n  sorry\n' > "$root/fixture/Problem.lean"
cp "$root/fixture/statement.txt" "$root/fixture/Problem.lean" "$root/copy/"
echo "$canary_in" > "$root/copy/in_scope.txt"
echo "staged-oracle-input" > "$root/in/answer.json"
echo "$canary_out" > "$root/items/PF/oracle/ref/PF-0001.lean"
echo "$canary_out" > "$root/home/.ssh/id_probe"
echo "$canary_out" > "$root/secrets/token.txt"
echo "$canary_out" > "$root/grading_keys/CR.key.json"
chmod -R a+rX "$root/copy" "$root/in"; chmod -R a+rX "$root/fixture"
before_fix=$(sha256_dir "$root/fixture")
before_dec=$(sha256_dir "$root/items")$(sha256_dir "$root/home")$(sha256_dir "$root/secrets")$(sha256_dir "$root/grading_keys")$(sha256_dir "$root/in")

# A. the main in-container probe, with the real limits
EQ_RUN_MOUNTS=(--mount "type=bind,source=$root/copy,target=/work" --mount "type=bind,source=$root/fixture,target=/fixture,readonly")
EQ_RUN_EXTRA=(); EQ_RUN_STDIN=""
cpu_quota=$(awk -v c="$EQ_CPUS" 'BEGIN{printf "%d", c*100000}')
work_cap=$(printf '%s' "$EQ_WORK_TMPFS" | tr ',' '\n' | sed -n 's/^size=//p' | head -n 1)
res=$(eq_run "eq-$EQ_RUN_ID-probe-main" 300 bash -c "$(cat "$here/probe_inner.sh")" probe \
        "$canary_out" "$canary_in" "$canary_env" "$EQ_PIDS" "$(to_bytes "$EQ_MEMORY")" "$cpu_quota" "$(to_bytes "${work_cap:-0}")" 2>&1)
rc=$?
if [ $rc != 0 ] && ! printf '%s' "$res" | grep -q '^T|'; then
  row "container main probe" FAIL "rc $rc: $(printf '%s' "$res" | tr '\n' ' ' | cut -c1-200)"
fi
while IFS='|' read -r tag name result detail; do
  if [ "$tag" = T ]; then row "$name" "$result" "$detail"; seen="$seen$name "; fi
done <<EOF
$(printf '%s\n' "$res" | grep '^T|')
EOF
printf '%s\n' "$res" | grep -v '^T|' | sed 's/^/  | /' | head -n 20
# rows the in-container probe must have reported (a truncated or tampered probe_inner.sh is a failure, not a pass). This also
# covers host_env_not_passed: the host environment canary is checked inside the container, not asserted here.
for need in user_nonroot caps_dropped no_new_privs rootfs_readonly write_outside_copy work_writable work_is_tmpfs work_tmpfs_size \
            eqsrc_mounted_ro bin_sh_present planted_secret_invisible host_env_not_passed network_connect_fails \
            pids_limit_set memory_limit_set cpu_limit_set \
            host_path_not_inherited path_dirs_readonly path_executables_allowlisted tools_hash_verified tools_mount_readonly \
            no_docker_socket no_home_mount no_default_route; do
  case "$seen" in *" $need "*) ;; *) row "$need" FAIL "the in-container probe did not report this row";; esac
done
if [ ! -e "$root/copy/eq_probe_write" ]; then row "work_write_stays_off_host" PASS "the /work write is not in the host copy (tmpfs copy)"; else row "work_write_stays_off_host" FAIL "write reached $root/copy: /work is a host bind mount"; fi

# B. pids limit behaviour (lowered limit so the test is quick; the real value is checked in A through pids.max).
#    Pure bash: children sleep, bash prints "fork: retry: Resource temporarily unavailable" when the cgroup refuses a fork.
EQ_RUN_EXTRA=(--pids-limit 64)
res=$(eq_run "eq-$EQ_RUN_ID-probe-pids" 120 bash -c '
exec 2>/tmp/err
n=0
while [ "$n" -lt 300 ]; do
  sleep 40 &
  if grep -q "fork" /tmp/err 2>/dev/null; then break; fi
  n=$((n + 1))
done
if grep -q "fork" /tmp/err 2>/dev/null; then echo "fork failed after $n children"; else echo "NO LIMIT: forked $n"; fi
kill $(jobs -p) 2>/dev/null' 2>&1)
case "$res" in
  *"fork failed after"*) n=$(printf '%s' "$res" | sed -n 's/.*after \([0-9]*\) children.*/\1/p'); row "pids_limit_enforced" PASS "fork refused after $n children at --pids-limit 64";;
  *) row "pids_limit_enforced" FAIL "$(printf '%s' "$res" | tr '\n' ' ' | cut -c1-160)";;
esac

# C. memory limit: building a 1.5 GiB shell variable under a 512 MiB cap gets the container OOM-killed (exit 137)
EQ_RUN_EXTRA=(--memory 512m --memory-swap 512m)
eq_run "eq-$EQ_RUN_ID-probe-mem" 120 bash -c 'x=$(head -c 1610612736 /dev/zero | tr "\0" a); echo "survived ${#x}"' >/dev/null 2>&1
rc=$?
if [ $rc = 137 ]; then row "memory_limit_enforced" PASS "OOM-killed (rc 137) at --memory 512m"; else row "memory_limit_enforced" FAIL "rc $rc (want 137)"; fi

# C2. /work size cap (F4): the tmpfs is lowered to 8 MiB for this container only; a 16 MiB write must stop with ENOSPC
EQ_RUN_EXTRA=(); EQ_RUN_WORK_TMPFS="rw,nosuid,nodev,exec,size=8m,mode=1777"
EQ_RUN_MOUNTS=(--mount "type=bind,source=$root/copy,target=/work")
res=$(eq_run "eq-$EQ_RUN_ID-probe-workcap" 60 bash -c '
head -c 16777216 /dev/zero > /work/eq_cap_probe 2>/tmp/cap.err; echo "cap_rc=$?"
echo "cap_size=$(wc -c < /work/eq_cap_probe)"
cat /tmp/cap.err' 2>&1)
EQ_RUN_WORK_TMPFS=""
sz=$(printf '%s' "$res" | sed -n 's/^cap_size=\([0-9]*\).*/\1/p' | head -n 1)
case "$res" in
  *"No space left"*) if [ "${sz:-99999999}" -le 8388608 ]; then row "work_size_capped" PASS "write past size=8m stopped with ENOSPC at ${sz} bytes"; else row "work_size_capped" FAIL "ENOSPC but ${sz} bytes written (cap 8 MiB)"; fi;;
  *) row "work_size_capped" FAIL "no ENOSPC for a 16 MiB write into /work at size=8m: $(printf '%s' "$res" | tr '\n' ' ' | cut -c1-160)";;
esac

# C3. /in (the harness mounts the staged oracle input there, read-only): a read-only bind mount must refuse writes and show the file
EQ_RUN_MOUNTS=(--mount "type=bind,source=$root/in,target=/in,readonly")
res=$(eq_run "eq-$EQ_RUN_ID-probe-in" 60 bash -c '
if ( : >> /in/answer.json ) 2>/dev/null; then echo "IN_WRITABLE"; else echo "IN_RO"; fi
if ( : > /in/eq_probe_new ) 2>/dev/null; then echo "IN_NEW_FILE_ALLOWED"; fi
cat /in/answer.json' 2>&1)
case "$res" in
  *IN_WRITABLE*|*IN_NEW_FILE_ALLOWED*) row "in_mount_readonly" FAIL "$(printf '%s' "$res" | tr '\n' ' ' | cut -c1-160)";;
  *IN_RO*staged-oracle-input*) row "in_mount_readonly" PASS "/in readable, writes refused";;
  *) row "in_mount_readonly" FAIL "unexpected output: $(printf '%s' "$res" | tr '\n' ' ' | cut -c1-160)";;
esac

# D. watchdog kill path (what the harness does on a timeout)
EQ_RUN_EXTRA=(); EQ_RUN_MOUNTS=()
t0=$SECONDS
eq_run "eq-$EQ_RUN_ID-probe-wd" 5 sleep 120 >/dev/null 2>&1
rc=$?; dt=$((SECONDS - t0))
left=$(docker ps -aq --filter "name=eq-$EQ_RUN_ID-probe-wd")
if [ $rc = 124 ] && [ -z "$left" ] && [ $dt -lt 30 ]; then row "timeout_kills_container" PASS "docker kill after 5 s (took ${dt}s), no container left"; else row "timeout_kills_container" FAIL "rc $rc, left '$left', ${dt}s"; fi

# E. no state survives: a second container with a fresh copy sees neither the /tmp marker nor the first run's /work marker
fresh=$(mktemp -d "$EQ_WORK_ROOT/probe-fresh.XXXXXX"); chmod a+rx "$fresh"
EQ_RUN_MOUNTS=(--mount "type=bind,source=$fresh,target=/work")
res=$(eq_run "eq-$EQ_RUN_ID-probe-fresh" 60 bash -c 'ls /tmp/eq_probe_marker /work/eq_probe_write 2>&1 | tr "\n" " "; ls /tmp | wc -l' 2>&1)
case "$res" in
  *"No such file"*"No such file"*) row "no_state_survives" PASS "fresh container: marker files absent, /tmp has $(printf '%s' "$res" | awk '{print $NF}') entries";;
  *) row "no_state_survives" FAIL "$res";;
esac
rm -rf "$fresh"

# F. the host side is untouched
after_fix=$(sha256_dir "$root/fixture")
after_dec=$(sha256_dir "$root/items")$(sha256_dir "$root/home")$(sha256_dir "$root/secrets")$(sha256_dir "$root/grading_keys")$(sha256_dir "$root/in")
if [ "$before_fix" = "$after_fix" ]; then row "host_fixture_unchanged" PASS "ro mount: fixture checksum identical"; else row "host_fixture_unchanged" FAIL "fixture changed on the host"; fi
if [ "$before_dec" = "$after_dec" ]; then row "host_decoys_unchanged" PASS "planted sibling files unchanged (incl. the /in source)"; else row "host_decoys_unchanged" FAIL "decoys changed"; fi
if [ -z "$(docker ps -q --filter "label=eq-run=$EQ_RUN_ID")" ]; then row "no_container_left" PASS ""; else row "no_container_left" FAIL "$(docker ps --filter "label=eq-run=$EQ_RUN_ID" --format '{{.Names}}')"; fi

# G. extension hook: every probe.d/*.sh (sorted by name) runs on the host with `bash`, after the sections above, for THIS image. The
#    host-side probes that need more than the main container (the WALL tunnel, an internal-only network, the tools manifest) live there,
#    so adding a proof is adding a file. Contract: the hook prints result lines `T|name|PASS/FAIL/INFO|detail` (same format as
#    probe_inner.sh; anything else it prints is shown indented); its rows are folded into this report and into the exit code. A hook that
#    prints no row, or exits non-zero without a FAIL row, is itself a FAIL row (a crashed probe is never a pass). Environment given to
#    it: EQ_PROBE_IMAGE (tag), EQ_PROBE_IMAGE_ID, EQ_PROBE_ROOT (the decoy tree of this run, 0700), EQ_PROBE_LIB (lib.sh, for eq_run),
#    EQ_PROBE_HOOK (its own path), plus every EQ_* of lib.sh. EQ_PROBE_D overrides the hook directory (tests).
hook_dir=${EQ_PROBE_D:-$here/probe.d}
if [ -d "$hook_dir" ]; then
  for hk in "$hook_dir"/*.sh; do
    [ -f "$hk" ] || continue
    hname=$(basename "$hk")
    hres=$(EQ_PROBE_IMAGE="$EQ_IMAGE_TAG" EQ_PROBE_IMAGE_ID="$EQ_IMAGE_ID_NOW" EQ_PROBE_ROOT="$root" EQ_PROBE_LIB="$here/lib.sh" \
           EQ_PROBE_HOOK="$hk" bash "$hk" 2>&1)
    hrc=$?
    hrows=0; hfail=0
    while IFS='|' read -r tag name result detail; do
      if [ "$tag" = T ]; then
        row "$name" "$result" "[$hname] $detail"; hrows=$((hrows + 1)); [ "$result" = FAIL ] && hfail=1
      fi
    done <<EOF
$(printf '%s\n' "$hres" | grep '^T|')
EOF
    printf '%s\n' "$hres" | grep -v '^T|' | sed "s#^#  | $hname: #" | head -n 20
    if [ "$hrows" = 0 ]; then row "hook_$hname" FAIL "the hook reported no row (exit $hrc)"
    elif [ "$hrc" != 0 ] && [ "$hfail" = 0 ]; then row "hook_$hname" FAIL "the hook exited $hrc without a failing row"; fi
  done
fi

echo
echo "image: $EQ_IMAGE_TAG ($EQ_IMAGE_ID_NOW)"
printf '%-34s %-6s %s\n' PROPERTY RESULT DETAIL
for r in "${rows[@]}"; do echo "$r"; done
echo
if [ $fails = 0 ]; then eq_write_result probe PASS 0; echo "PROBE: PASS (${#rows[@]} rows)"; exit 0; fi
eq_write_result probe FAIL "$fails"
echo "PROBE: FAIL ($fails failing rows). Do not freeze this backend until they are understood."
exit 1
