#!/usr/bin/env bash
# shellcheck disable=SC2016,SC2012,SC2086,SC2329,SC2015
# spike.sh (user-run): does the image work under the full hardening flags?
#   [EQ_IMAGE=<tag|id>] [EQ_IMAGE_PY=<tag|id>] ./spike.sh [--builtin] [ITEM]        ITEM default PF-0001
# EQ_IMAGE overrides the lean image under test (default: the recorded eq-lean; EQ_PROFILE=min: eq-lean-min); the python checks
# (section 1c) run only when EQ_IMAGE_PY names a different image. For a lean-only candidate set EQ_IMAGE alone.
# Default (needs EQ_ITEMS): the PF check of ITEM's reference proof and gap-following wrong answer, plus the tool checks.
# --builtin (also chosen when EQ_ITEMS is absent): no pools needed; Lean imports Mathlib and runs norm_num + #print axioms,
# and, when EQ_IMAGE_PY names another image, python/uv/unittest run there. This is what the installer runs.
# Optional: EQ_HOST_LEAN_PROJECT=<host Lean project dir> also tests whether the host's macOS-built oleans load in Linux Lean.
# Mounts: only the fresh check copy (read-only at /eqsrc/work, copied into a capped tmpfs /work) and the pristine fixture (ro);
# the olean test mounts the host .lake read-only in its own throw-away container. Prints a PASS/FAIL table; exit 1 on a gating FAIL; result in $EQ_STATE_DIR/results/spike.*.env
set -u
here=$(cd "$(dirname "$0")" && pwd -P)
# shellcheck disable=SC1091
. "$here/lib.sh"
BUILTIN=0
if [ "${1:-}" = --builtin ]; then BUILTIN=1; shift; fi
item=${1:-PF-0001}
[ -n "$EQ_ITEMS" ] && [ -d "$EQ_ITEMS/PF" ] || BUILTIN=1
host_proj=${EQ_HOST_LEAN_PROJECT:-}

eq_need_docker
eq_require_image "$EQ_IMAGE_TAG"
tags="$EQ_IMAGE_TAG"
if [ "$EQ_IMAGE_PY" != "$EQ_IMAGE_TAG" ]; then eq_require_image "$EQ_IMAGE_PY" "$EQ_IMAGE_TAG"; tags="$tags $EQ_IMAGE_PY"; fi
EQ_RUN_IMAGE_REPORT=$EQ_IMAGE_TAG; EQ_IMAGE_ID_REPORT=$EQ_IMAGE_ID_NOW
trap 'eq_sweep' EXIT INT TERM
orph=$(eq_orphans); if [ -n "$orph" ]; then echo "note: containers from earlier runs exist:"; echo "$orph"; fi

rows=(); gate_fail=0
row() { # name result detail [gating=1]
  rows[${#rows[@]}]=$(printf '%-44s %-8s %s' "$1" "$2" "$3")
  if [ "$2" = FAIL ] && [ "${4:-1}" = 1 ]; then gate_fail=$((gate_fail + 1)); fi
  return 0
}
echo "images: lean=$EQ_IMAGE_TAG py=$EQ_IMAGE_PY  (source: $EQ_IMAGE_SOURCE)"
echo "flags : --network none --read-only --cap-drop ALL --security-opt no-new-privileges --pids-limit $EQ_PIDS --memory $EQ_MEMORY --cpus $EQ_CPUS --user $EQ_USER --tmpfs /tmp:$EQ_TMPFS_OPTS${EQ_SECCOMP:+ --security-opt seccomp=$EQ_SECCOMP}"
echo

fresh_copy() { local d; d=$(mktemp -d "$EQ_WORK_ROOT/spike.XXXXXX"); chmod a+rx "$d"; echo "$d"; }   # read-only source of the /work copy

# 1. the lean image: tools, user, LEAN_PATH, Mathlib import + tactic
copy0=$(fresh_copy)
EQ_RUN_MOUNTS=(--mount "type=bind,source=$copy0,target=/work"); EQ_RUN_EXTRA=(); EQ_RUN_STDIN=""; EQ_RUN_IMAGE=$EQ_IMAGE_TAG
info=$(eq_run "eq-$EQ_RUN_ID-spike-info" 120 bash -c '
echo "uid=$(id -u) gid=$(id -g)"
if command -v lean >/dev/null 2>&1; then echo "HAS_LEAN=1"; lean --version; else echo "HAS_LEAN=0"; fi
echo "kind=$(cat /opt/eq/IMAGE_KIND 2>/dev/null || echo full-debian)"
echo "project=${EQ_LEAN_PROJECT:-none}"
if [ -n "${EQ_LEAN_PROJECT:-}" ]; then cd "$EQ_LEAN_PROJECT" && lake env printenv LEAN_PATH | tr ":" "\n" | head -n 2; fi
grep -E "olean_tree_sha256|olean_files|image_kind" /opt/eq/PROVENANCE.txt 2>/dev/null
' 2>&1)
rc=$?
printf '%s\n' "$info" | sed 's/^/  | /'
if [ $rc = 0 ]; then row "container starts under the flags" PASS "rc 0"; else row "container starts under the flags" FAIL "rc $rc (see output above)"; fi
case "$info" in *"uid=0"*) row "runs as non-root" FAIL "uid 0";; *"uid="*) row "runs as non-root" PASS "$(printf '%s\n' "$info" | grep -m1 '^uid=')";; esac
case "$info" in *HAS_LEAN=1*) ;; *) row "lean present in $EQ_IMAGE_TAG" FAIL "no lean binary (EQ_IMAGE must be a lean image)";; esac
case "$info" in *"version 4.34.1"*) row "Lean 4.34.1" PASS "";; *) row "Lean 4.34.1" FAIL "not found in output";; esac
case "$info" in *"/.lake/packages/mathlib/"*) row "lake env / LEAN_PATH" PASS "LEAN_PATH has mathlib";; *) row "lake env / LEAN_PATH" FAIL "no mathlib in LEAN_PATH (full image: lake needs a readable project; minimal: lake shim)";; esac
rm -rf "$copy0"

# 1b. Mathlib import and a tactic that runs Mathlib code (needs the module files the image kept)
copy1=$(fresh_copy)
EQ_RUN_MOUNTS=(--mount "type=bind,source=$copy1,target=/work")
t0=$SECONDS
out=$(eq_run "eq-$EQ_RUN_ID-spike-mathlib" 600 bash -c '
LP=$(cd "$EQ_LEAN_PROJECT" && lake env printenv LEAN_PATH) || exit 2
printf "import Mathlib\ntheorem eq_builtin : (2:Nat) + 2 = 4 := by norm_num\n#print axioms eq_builtin\n" > /tmp/t.lean
LEAN_PATH="$LP" lean /tmp/t.lean; echo "lean_rc=$?"' 2>&1)
if printf '%s' "$out" | grep -q '^lean_rc=0$'; then row "import Mathlib + norm_num + #print axioms" PASS "$((SECONDS - t0))s"
else row "import Mathlib + norm_num + #print axioms" FAIL "$(printf '%s' "$out" | tr '\n' ' ' | cut -c1-240)"; fi
rm -rf "$copy1"

# 1c. python image (only when it is a different image)
if [ "$EQ_IMAGE_PY" != "$EQ_IMAGE_TAG" ]; then
  copy2=$(fresh_copy)
  EQ_RUN_MOUNTS=(--mount "type=bind,source=$copy2,target=/work"); EQ_RUN_IMAGE=$EQ_IMAGE_PY
  out=$(eq_run "eq-$EQ_RUN_ID-spike-py" 120 bash -c '
uv run --no-project python -c "import unittest, json, sys; print(sys.version.split()[0])" || exit 3
printf "# /// script\n# requires-python = \">=3.10\"\n# dependencies = []\n# ///\nprint(\"script-ok\")\n" > /tmp/s.py
uv run --quiet /tmp/s.py || exit 4
echo "py_rc=0"' 2>&1)
  if printf '%s' "$out" | grep -q '^py_rc=0$'; then row "py image: uv run python + PEP 723 script" PASS "$(printf '%s' "$out" | head -n 1)"
  else row "py image: uv run python + PEP 723 script" FAIL "$(printf '%s' "$out" | tr '\n' ' ' | cut -c1-240)"; fi
  rm -rf "$copy2"; EQ_RUN_IMAGE=$EQ_IMAGE_TAG
fi

# 2. PF check of the reference proof and the gap-following wrong answer (needs the pools)
t_all=0; n_all=0
if [ "$BUILTIN" = 0 ]; then
  same=0
  if cmp -s "$EQ_ITEMS/PF/check_lean.sh" "$EQ_ITEMS/PF/fixtures/$item/check_lean.sh" && cmp -s "$EQ_ITEMS/PF/EqVerify.lean" "$EQ_ITEMS/PF/fixtures/$item/EqVerify.lean"; then same=1; fi
  modes="oracle public"; [ $same = 1 ] && modes=oracle
  for mode in $modes; do
    for kind in ref wrong; do
      want=1; [ $kind = wrong ] && want=0
      eq_pf_check "$item" "$kind" "$mode"
      t_all=$((t_all + PF_SECS)); n_all=$((n_all + 1))
      gating=1; [ "$mode" = public ] && gating=0
      if [ "$PF_SCORE" = "$want" ]; then row "$item $kind ($mode check)" PASS "score $PF_SCORE in ${PF_SECS}s" "$gating"
      else row "$item $kind ($mode check)" FAIL "score $PF_SCORE want $want, ${PF_SECS}s: $PF_DETAIL" "$gating"; fi
    done
  done
  if [ $same = 1 ]; then row "fixture checker == items/PF checker" PASS "public check identical, skipped"
  else row "fixture checker == items/PF checker" INFO "DIFFERENT: fixtures ship an older check_lean.sh/EqVerify.lean (public check != oracle)" 0; fi
  [ $n_all -gt 0 ] && echo "mean seconds per check (incl. container start): $((t_all / n_all))"
fi

# 3. host-built Mathlib oleans in Linux Lean (informational)
if [ -n "$host_proj" ] && [ -d "$host_proj/.lake/packages/mathlib/.lake/build/lib/lean" ]; then
  EQ_RUN_MOUNTS=(--mount "type=bind,source=$host_proj/.lake,target=/hostlake,readonly"); EQ_RUN_EXTRA=(); EQ_RUN_STDIN=""; EQ_RUN_IMAGE=$EQ_IMAGE_TAG
  out=$(eq_run "eq-$EQ_RUN_ID-spike-hostolean" 600 bash -c '
    LP=""; for d in /hostlake/packages/*/.lake/build/lib/lean /hostlake/build/lib/lean; do [ -d "$d" ] && LP="$LP:$d"; done
    printf "import Mathlib\nexample : (2:Nat) + 2 = 4 := by norm_num\n" > /tmp/t.lean
    LEAN_PATH="${LP#:}" lean /tmp/t.lean; echo "lean_rc=$?"' 2>&1)
  if printf '%s' "$out" | grep -q '^lean_rc=0$'; then
    row "host macOS oleans load in Linux Lean" INFO "YES loads (not used: the image's own Mathlib stays the pinned artefact)" 0
  else
    row "host macOS oleans load in Linux Lean" INFO "NO (expected) -> the image's Mathlib is used: $(printf '%s' "$out" | tr '\n' ' ' | cut -c1-160)" 0
  fi
fi

echo
echo "RESULT"
echo "------"
printf '%-44s %-8s %s\n' TEST RESULT DETAIL
for r in "${rows[@]}"; do echo "$r"; done
echo
if [ "$gate_fail" = 0 ]; then
  eq_write_result spike PASS 0
  echo "SPIKE: PASS (gating rows all PASS; INFO rows are not gating)"; exit 0
fi
eq_write_result spike FAIL "$gate_fail"
echo "SPIKE: FAIL (see FAIL rows). Common causes: the /work tmpfs cap too small for the check (EQ_WORK_TMPFS, now $EQ_WORK_TMPFS), memory too low (EQ_MEMORY), a read permission problem on the check copy for --user $EQ_USER, minimal image missing module files (build with another --keep-profile)."
exit 1
