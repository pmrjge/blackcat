#!/usr/bin/env bash
# shellcheck disable=SC2016,SC2012,SC2086,SC2329,SC2015
# probe.sh (user-run, normal terminal): proves the isolation properties from inside the container, with the same flags as every
# check (lib.sh eq_run), and that the image works under them (the former spike). Backend: Apple `container`.
#   [EQ_PROBE_IMAGES="<TAG@sha256:..> ..."] bash probe.sh
# Default images: the recorded min-both (PF) and min-py (CP, CR); every DIFFERENT image is probed once and the exit code is the
# worst. Plants decoys on the host as SIBLINGS of the mounted check copy (an oracle-looking tree, a fake home with an ssh key, a
# grading key, an env var), runs probe_inner.sh in the container, then separate containers for: the work (spike) checks, the
# process-count limit, the memory limit, the /work size cap, a read-only /in mount, the watchdog kill and "no state survives".
# Prints a PASS/FAIL table (INFO rows do not count); exit 1 on any FAIL; result in $EQ_STATE_DIR/results/probe.*.env.
# Hooks (section G): every probe.d/*.sh runs after the built-in sections and its `T|name|RESULT|detail` rows are folded in
# (probe.d/50-tunnel.sh: the WALL tunnel). It tries only benign writes and connects.
set -u
here=$(cd "$(dirname "$0")" && pwd -P)
# shellcheck disable=SC1091
. "$here/lib.sh"

eq_need_container
if [ -z "${EQ_PROBE_SINGLE:-}" ]; then
  imgs=()
  for c in ${EQ_PROBE_IMAGES:-$(eq_pinned_ref min-both) $(eq_pinned_ref min-py)}; do
    dup=0
    for d in ${imgs[@]+"${imgs[@]}"}; do [ "$d" = "$c" ] && dup=1; done
    [ "$dup" = 1 ] || imgs[${#imgs[@]}]=$c
  done
  [ "${#imgs[@]}" -gt 0 ] || { echo "probe: no image (no build record of min-both/min-py; set EQ_PROBE_IMAGES)" >&2; exit 11; }
  worst=0; k=0
  for img in "${imgs[@]}"; do
    k=$((k + 1)); echo "== probe $k/${#imgs[@]}: image $img"
    EQ_PROBE_SINGLE="$img" bash "$here/probe.sh"; rc=$?
    [ "$rc" -gt "$worst" ] && worst=$rc
    echo
  done
  exit "$worst"
fi
IMG=$EQ_PROBE_SINGLE
eq_require_image "$IMG"
EQ_RUN_IMAGE_REPORT=${IMG%@*}; EQ_IMAGE_ID_REPORT=$EQ_IMAGE_DIGEST_NOW
EQ_RUN_IMAGE=$IMG
trap 'eq_sweep; [ -n "${root:-}" ] && rm -rf "$root"' EXIT INT TERM

rows=(); fails=0; seen=" "
row() { rows[${#rows[@]}]=$(printf '%-34s %-6s %s' "$1" "$2" "$3"); [ "$2" = FAIL ] && fails=$((fails + 1)); return 0; }
to_bytes() { # 8G / 512M / 1024K / plain bytes
  case "$1" in
    *[gG]) echo $(( ${1%[gG]} * 1024 * 1024 * 1024 ));;
    *[mM]) echo $(( ${1%[mM]} * 1024 * 1024 ));;
    *[kK]) echo $(( ${1%[kK]} * 1024 ));;
    *) echo "$1";;
  esac
}
sum_dir() { (cd "$1" && find . -type f | LC_ALL=C sort | while read -r f; do cksum "$f"; done | cksum | cut -d' ' -f1); }
rand() { od -An -N8 -tx1 /dev/urandom | tr -d ' \n'; }
short() { printf '%s' "$1" | tr '\n' ' ' | cut -c1-200; }

root=$(mktemp -d "$EQ_WORK_ROOT/probe.XXXXXX")
canary_out="EQCANARY-OUT-$(rand)"; canary_in="EQCANARY-IN-$(rand)"; canary_env="EQCANARY-ENV-$(rand)"
export EQ_PROBE_SECRET_ENV="$canary_env"   # must never reach the container (eq_run passes only fixed -e KEY=VALUE entries)
mkdir -p "$root/copy" "$root/fixture" "$root/in" "$root/items/PF/oracle/ref" "$root/home/.ssh" "$root/secrets" "$root/grading_keys"
printf 'eq_probe\ntheorem eq_probe : True\n' > "$root/fixture/statement.txt"
cp "$root/fixture/statement.txt" "$root/copy/"
echo "$canary_in" > "$root/copy/in_scope.txt"
echo "staged-oracle-input" > "$root/in/answer.json"
for f in items/PF/oracle/ref/PF-0001.lean home/.ssh/id_probe secrets/token.txt grading_keys/CR.key.json; do echo "$canary_out" > "$root/$f"; done
chmod -R a+rX "$root/copy" "$root/in" "$root/fixture"
before=$(sum_dir "$root/fixture")$(sum_dir "$root/items")$(sum_dir "$root/home")$(sum_dir "$root/secrets")$(sum_dir "$root/grading_keys")$(sum_dir "$root/in")

# A. the main in-container probe, with the real limits
EQ_RUN_MOUNTS=(--mount "type=bind,source=$root/copy,target=/work" --mount "type=bind,source=$root/fixture,target=/fixture,readonly")
EQ_RUN_STDIN=""
res=$(eq_run "eq-$EQ_RUN_ID-probe-main" 300 bash -c "$(cat "$here/probe_inner.sh")" probe \
        "$canary_out" "$canary_in" "$canary_env" "$EQ_NPROC" "$(to_bytes "$EQ_MEMORY")" "$EQ_CPUS" "$(to_bytes "$EQ_WORK_SIZE")" 2>&1)
rc=$?
printf '%s\n' "$res" | grep -q '^T|' || row container_main_probe FAIL "rc $rc: $(short "$res")"
while IFS='|' read -r tag name result detail; do
  if [ "$tag" = T ]; then row "$name" "$result" "$detail"; seen="$seen$name "; fi
done <<EOF
$(printf '%s\n' "$res" | grep '^T|')
EOF
# rows the in-container probe must report (a truncated or tampered probe_inner.sh is a failure, never a pass)
for need in user_nonroot caps_dropped rootfs_readonly write_outside_copy work_writable work_is_tmpfs work_tmpfs_size eqsrc_mounted_ro \
            bin_sh_present planted_secret_invisible host_env_not_passed network_connect_fails only_loopback_interface \
            only_expected_host_mounts nproc_limit_set memory_limit_set cpu_limit_set host_path_not_inherited path_dirs_readonly \
            path_executables_allowlisted tools_hash_verified tools_mount_readonly no_host_socket no_home_mount no_default_route \
            no_setuid_files tools_run no_debug_shell no_package_manager network_probe_control; do
  case "$seen" in *" $need "*) ;; *) row "$need" FAIL "the in-container probe did not report this row";; esac
done
if [ ! -e "$root/copy/eq_probe_write" ]; then row work_write_stays_off_host PASS "the /work write is not in the host copy (tmpfs copy)"
else row work_write_stays_off_host FAIL "a write reached $root/copy: /work is a host directory"; fi

# S. the image works under the flags (the former spike): Mathlib in a Lean image, uv + a PEP 723 script in a Python image
EQ_RUN_MOUNTS=()
kind=$(eq_run "eq-$EQ_RUN_ID-probe-kind" 60 /bin/sh -c 'command -v lean >/dev/null && echo HAS_LEAN; command -v uv >/dev/null && echo HAS_UV; true' 2>&1)
case "$kind" in *HAS_LEAN*|*HAS_UV*) ;; *) row works_tools_found FAIL "neither lean nor uv on PATH: $(short "$kind")";; esac
case "$kind" in
  *HAS_LEAN*)
    t0=$SECONDS
    out=$(eq_run "eq-$EQ_RUN_ID-probe-mathlib" 600 bash -c '
LP=$(cd "$EQ_LEAN_PROJECT" && lake env printenv LEAN_PATH) || exit 2
printf "import Mathlib\ntheorem eq_builtin : (2:Nat) + 2 = 4 := by norm_num\n#print axioms eq_builtin\n" > /tmp/t.lean
LEAN_PATH="$LP" lean /tmp/t.lean; echo "lean_rc=$?"' 2>&1)
    if printf '%s' "$out" | grep -q '^lean_rc=0$'; then row works_lean_mathlib PASS "import Mathlib + norm_num in $((SECONDS - t0))s"
    else row works_lean_mathlib FAIL "$(short "$out")"; fi;;
esac
case "$kind" in
  *HAS_UV*)
    out=$(eq_run "eq-$EQ_RUN_ID-probe-py" 120 bash -c '
printf "# /// script\n# requires-python = \">=3.10\"\n# dependencies = []\n# ///\nimport unittest, json, sys\nprint(\"script-ok\", sys.version.split()[0])\n" > /tmp/s.py
uv run --quiet /tmp/s.py && echo py_rc=0' 2>&1)
    if printf '%s' "$out" | grep -q '^py_rc=0$'; then row works_uv_python PASS "$(printf '%s' "$out" | grep -m1 script-ok)"
    else row works_uv_python FAIL "$(short "$out")"; fi;;
esac

# B. process-count limit enforced (lowered to 64 for this container; the real value is checked in A as nproc_limit_set)
res=$(EQ_RUN_NPROC=64 eq_run "eq-$EQ_RUN_ID-probe-nproc" 120 bash -c '
exec 2>/tmp/err
n=0
while [ "$n" -lt 300 ]; do sleep 40 & if grep -q "fork" /tmp/err 2>/dev/null; then break; fi; n=$((n + 1)); done
if grep -q "fork" /tmp/err 2>/dev/null; then echo "fork failed after $n children"; else echo "NO LIMIT: forked $n"; fi
kill $(jobs -p) 2>/dev/null' 2>&1)
case "$res" in
  *"fork failed after"*) row nproc_limit_enforced PASS "$(printf '%s' "$res" | grep -m1 'fork failed') at --ulimit nproc=64";;
  *) row nproc_limit_enforced FAIL "$(short "$res")";;
esac

# C. memory: a 1.5 GiB shell variable in a 1 GiB VM is killed by the guest's OOM killer (137, or 9 when the init reports the signal)
EQ_RUN_MEMORY=1G eq_run "eq-$EQ_RUN_ID-probe-mem" 180 bash -c 'x=$(head -c 1610612736 /dev/zero | tr "\0" a); echo "survived ${#x}"' >/dev/null 2>&1
rc=$?
case "$rc" in 137|9) row memory_limit_enforced PASS "killed (rc $rc) at -m 1G";; *) row memory_limit_enforced FAIL "rc $rc (want 137)";; esac

# C2. /work size cap: the tmpfs is lowered to 8M for this container; a 16 MiB write must stop with ENOSPC
EQ_RUN_MOUNTS=(--mount "type=bind,source=$root/copy,target=/work")
res=$(EQ_RUN_WORK_SIZE=8M eq_run "eq-$EQ_RUN_ID-probe-workcap" 60 bash -c '
head -c 16777216 /dev/zero > /work/eq_cap_probe 2>/tmp/cap.err; echo "cap_rc=$?"
echo "cap_size=$(wc -c < /work/eq_cap_probe)"
cat /tmp/cap.err' 2>&1)
sz=$(printf '%s' "$res" | sed -n 's/^cap_size=\([0-9]*\).*/\1/p' | head -n 1)
case "$res" in
  *"No space left"*) if [ "${sz:-99999999}" -le 8388608 ]; then row work_size_capped PASS "ENOSPC at ${sz} bytes (size=8M)"; else row work_size_capped FAIL "ENOSPC but ${sz} bytes written"; fi;;
  *) row work_size_capped FAIL "no ENOSPC for 16 MiB into /work at size=8M (are tmpfs size= options honoured?): $(short "$res")";;
esac

# C3. /in (the harness's staged oracle input), read-only bind: writes refused, the file readable
EQ_RUN_MOUNTS=(--mount "type=bind,source=$root/in,target=/in,readonly")
res=$(eq_run "eq-$EQ_RUN_ID-probe-in" 60 bash -c '
if ( : >> /in/answer.json ) 2>/dev/null; then echo IN_WRITABLE; else echo IN_RO; fi
if ( : > /in/eq_probe_new ) 2>/dev/null; then echo IN_NEW_FILE_ALLOWED; fi
cat /in/answer.json' 2>&1)
case "$res" in
  *IN_WRITABLE*|*IN_NEW_FILE_ALLOWED*) row in_mount_readonly FAIL "$(short "$res")";;
  *IN_RO*staged-oracle-input*) row in_mount_readonly PASS "/in readable, writes refused";;
  *) row in_mount_readonly FAIL "unexpected output: $(short "$res")";;
esac

# D. watchdog kill path (what the harness does on a timeout)
EQ_RUN_MOUNTS=()
t0=$SECONDS
eq_run "eq-$EQ_RUN_ID-probe-wd" 5 sleep 120 >/dev/null 2>&1
rc=$?; dt=$((SECONDS - t0))
if [ $rc = 124 ] && ! eq_container_exists "eq-$EQ_RUN_ID-probe-wd" && [ $dt -lt 60 ]; then row timeout_kills_container PASS "container kill after 5 s (took ${dt}s), none left"
else row timeout_kills_container FAIL "rc $rc, ${dt}s, left: $(eq_container_exists "eq-$EQ_RUN_ID-probe-wd" && echo yes || echo no)"; fi

# E. no state survives: a fresh container sees neither the /tmp marker nor the first run's /work marker
fresh=$(mktemp -d "$EQ_WORK_ROOT/probe-fresh.XXXXXX"); chmod a+rx "$fresh"
EQ_RUN_MOUNTS=(--mount "type=bind,source=$fresh,target=/work")
res=$(eq_run "eq-$EQ_RUN_ID-probe-fresh" 60 bash -c 'ls /tmp/eq_probe_marker /work/eq_probe_write 2>&1 | tr "\n" " "' 2>&1)
case "$res" in *"No such file"*"No such file"*) row no_state_survives PASS "markers absent in a fresh container";; *) row no_state_survives FAIL "$(short "$res")";; esac
rm -rf "$fresh"

# F. the host side is untouched, nothing left running
after=$(sum_dir "$root/fixture")$(sum_dir "$root/items")$(sum_dir "$root/home")$(sum_dir "$root/secrets")$(sum_dir "$root/grading_keys")$(sum_dir "$root/in")
if [ "$before" = "$after" ]; then row host_fixture_and_decoys_unchanged PASS "fixture, /in source and planted siblings identical"; else row host_fixture_and_decoys_unchanged FAIL "changed on the host"; fi
left=$(eq_list_ids "eq-run=$EQ_RUN_ID")
if [ -z "$left" ]; then row no_container_left PASS ""; else row no_container_left FAIL "$(short "$left")"; fi

# G. hooks: every probe.d/*.sh (sorted) runs on the host for THIS image; contract: `T|name|RESULT|detail` rows; no row, or a non-zero
#    exit without a FAIL row, is a FAIL (a crashed probe is never a pass). Environment: EQ_PROBE_IMAGE (TAG@sha256:..),
#    EQ_PROBE_ROOT, EQ_PROBE_LIB, EQ_PROBE_HOOK, EQ_STATE_DIR. EQ_PROBE_D overrides the hook directory (tests).
hook_dir=${EQ_PROBE_D:-$here/probe.d}
if [ -d "$hook_dir" ]; then
  for hk in "$hook_dir"/*.sh; do
    [ -f "$hk" ] || continue
    hname=$(basename "$hk")
    hres=$(EQ_PROBE_IMAGE="$IMG" EQ_PROBE_ROOT="$root" EQ_PROBE_LIB="$here/lib.sh" EQ_PROBE_HOOK="$hk" EQ_STATE_DIR="$EQ_STATE_DIR" bash "$hk" 2>&1)
    hrc=$?; hrows=0; hfail=0
    while IFS='|' read -r tag name result detail; do
      if [ "$tag" = T ]; then row "$name" "$result" "[$hname] $detail"; hrows=$((hrows + 1)); [ "$result" = FAIL ] && hfail=1; fi
    done <<EOF
$(printf '%s\n' "$hres" | grep '^T|')
EOF
    printf '%s\n' "$hres" | grep -v '^T|' | sed "s#^#  | $hname: #" | head -n 20
    if [ "$hrows" = 0 ]; then row "hook_$hname" FAIL "the hook reported no row (exit $hrc)"
    elif [ "$hrc" != 0 ] && [ "$hfail" = 0 ]; then row "hook_$hname" FAIL "the hook exited $hrc without a failing row"; fi
  done
fi

echo
echo "image: $IMG"
printf '%-34s %-6s %s\n' PROPERTY RESULT DETAIL
for r in "${rows[@]}"; do echo "$r"; done
echo
if [ $fails = 0 ]; then eq_write_result probe PASS 0; echo "PROBE: PASS (${#rows[@]} rows)"; exit 0; fi
eq_write_result probe FAIL "$fails"
echo "PROBE: FAIL ($fails failing rows). Do not use this backend until they are understood."
exit 1
