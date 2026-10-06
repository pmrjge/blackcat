#!/usr/bin/env bash
# compare-images.sh (user-run): measures the candidates and prints the decision table of RUNBOOK_MINIMAL.md section 3.
#   ./compare-images.sh [--full TAG] [--lean-min TAG] [--lean-dl TAG] [--py-min TAG] [--both-min TAG] [--cand LABEL=TAG]...
#                       [--runs N] [--tol PCT] [--items "PF-0001 PF-DEV1"] [--time-item PF-0001] [--skip-inventory] [--skip-cp]
# Defaults: the tags recorded by build.sh (full = baseline, lean-min = FROM scratch, lean-dl = distroless; a candidate whose image
# is not present is left out). --cand adds any further lean image, e.g. a keep-profile build:
#   --cand scratch-noprivate=eq-lean-min:4.34.1-arm64-noprivate
# Every number printed is measured by this run, on this machine. Per candidate:
#   timing     the PF check (items/PF/check_lean.sh + EqVerify.lean, the oracle's own checker) on the reference proof of --time-item,
#              --runs times, candidates interleaved per round (run 1 = first touch of that image in this script = "cold"; for a
#              cold VM page cache restart Docker Desktop first). Timing runs come first, before anything else touches the images.
#   behaviour  reference proof (want 1) and gap-following wrong answer (want 0) of every --items item, same hardening flags in
#              every container; verdict and exit code must equal the baseline's
#   inventory  `docker create` + `docker export | tar -tv` (nothing is started): files, symlinks, bytes, setuid/setgid, executables,
#              shells/interpreters and package managers present; lists in $EQ_STATE_DIR/compare/LABEL.files.txt
#   olean tree sha256 (/opt/eq/PROVENANCE.txt) must equal the baseline's; spike/probe verdicts are read from results/*.env
#   CP-0001 checks of --py-min against the baseline (needs a host uv)
# DECISION RULE (fixed before measuring; X = --tol / EQ_COMPARE_TOL, default 10):
#   ELIGIBLE iff  PF gate SAME (all smoke items: ref=1, wrong=0, identical to the baseline)  AND  olean hash SAME
#   AND  median PF time <= baseline median * (1 + X%)  AND  ./spike.sh and ./probe.sh recorded PASS for the candidate's tag.
#   PICK = the eligible candidate with the fewest exported bytes; an eligible FROM-scratch candidate (label lean-min or scratch-*)
#   within 5% of that size wins instead (fewer unpinned inputs, no registry digest, no mixed libc). No eligible candidate:
#   keep the baseline. A missing measurement (no spike/probe result, no pools) makes a candidate INCOMPLETE, never eligible.
# Exit 0: a candidate was picked; 1: none or a PF verdict differs; 2 usage; 10/11 docker or image missing.
# shellcheck disable=SC2086,SC2016,SC2004,SC2321
set -u
here=$(cd "$(dirname "$0")" && pwd -P)
# shellcheck disable=SC1091
. "$here/lib.sh"

RUNS=3; TOL=${EQ_COMPARE_TOL:-10}; ITEMS_SMOKE="PF-0001 PF-DEV1"; TIME_ITEM=PF-0001; SKIP_INV=0; SKIP_CP=0
FULL=$(eq_img_tag full); LMIN=$(eq_img_tag min-lean); LDL=$(eq_img_tag dl-lean); PMIN=$(eq_img_tag min-py); BMIN=""
EXTRA_N=(); EXTRA_T=()
while [ $# -gt 0 ]; do
  case "$1" in
    --full) FULL=${2:?}; shift;; --lean-min) LMIN=${2:?}; shift;; --lean-dl) LDL=${2:?}; shift;;
    --py-min) PMIN=${2:?}; shift;; --both-min) BMIN=${2:?}; shift;;
    --cand) c=${2:?}; case "$c" in *=*) EXTRA_N[${#EXTRA_N[@]}]=${c%%=*}; EXTRA_T[${#EXTRA_T[@]}]=${c#*=};; *) echo "--cand wants LABEL=TAG" >&2; exit 2;; esac; shift;;
    --runs) RUNS=${2:?}; shift;; --tol) TOL=${2:?}; shift;;
    --items) ITEMS_SMOKE=${2:?}; shift;; --time-item) TIME_ITEM=${2:?}; shift;;
    --skip-inventory) SKIP_INV=1;; --skip-cp) SKIP_CP=1;;
    -h|--help) sed -n '2,29p' "$0"; exit 0;;
    *) echo "unknown argument: $1" >&2; exit 2;;
  esac
  shift
done
case "$RUNS$TOL" in ''|*[!0-9]*) echo "--runs and --tol are whole numbers" >&2; exit 2;; esac
[ "$RUNS" -ge 1 ] || { echo "--runs must be >= 1" >&2; exit 2; }
eq_need_docker
have() { docker image inspect "$1" >/dev/null 2>&1; }
CN=(); CT=()
add_cand() { CN[${#CN[@]}]=$1; CT[${#CT[@]}]=$2; }
have "$FULL" || { echo "baseline image $FULL not present: build it first (./build.sh)" >&2; exit 11; }
add_cand full "$FULL"
have "$LMIN" && add_cand lean-min "$LMIN"
have "$LDL" && add_cand lean-dl "$LDL"
i=0; while [ "$i" -lt "${#EXTRA_N[@]}" ]; do
  have "${EXTRA_T[$i]}" || { echo "--cand ${EXTRA_N[$i]}: image ${EXTRA_T[$i]} not present" >&2; exit 11; }
  add_cand "${EXTRA_N[$i]}" "${EXTRA_T[$i]}"; i=$((i + 1))
done
NC=${#CN[@]}
[ "$NC" -ge 2 ] || { echo "no candidate image present (build one: ./build-minimal.sh scratch)" >&2; exit 11; }
# every candidate must be an image a build record covers (F9), and is then run by the ID verified here, not by its tag
i=0; while [ "$i" -lt "$NC" ]; do eq_require_image "${CT[$i]}"; i=$((i + 1)); done
OUT="$EQ_STATE_DIR/compare"; mkdir -p "$OUT"
trap 'eq_sweep' EXIT INT TERM
EQ_RUN_IMAGE_REPORT=$FULL; EQ_IMAGE_ID_REPORT=none
have_items=0; [ -n "$EQ_ITEMS" ] && [ -d "$EQ_ITEMS/PF" ] && have_items=1
echo "candidates:"; i=0; while [ "$i" -lt "$NC" ]; do echo "  ${CN[$i]} = ${CT[$i]}"; i=$((i + 1)); done
echo "rule: tolerance ${TOL}% on the median PF time of $RUNS runs of $TIME_ITEM; smoke items: $ITEMS_SMOKE"
echo

median() { printf '%s\n' "$@" | grep -E '^[0-9]+$' | sort -n | awk '{a[NR] = $1} END { if (NR) print a[int((NR + 1) / 2)]; else print 0 }'; }
norm() { sed -e 's/in [0-9.]*s/in Xs/' -e 's#/tmp/[A-Za-z0-9._-]*#/tmp/X#g' -e 's/[0-9][0-9.]* seconds/N seconds/' -e 's/rc=[0-9]* //'; }

# ------------------------------------------------------------------ 1. timing (first, so run 1 is the first touch)
TIMES=(); i=0; while [ "$i" -lt "$NC" ]; do TIMES[$i]=""; i=$((i + 1)); done
if [ "$have_items" = 1 ]; then
  echo "== 1. timing: PF check of the $TIME_ITEM reference proof, $RUNS rounds, candidates interleaved"
  r=1; while [ "$r" -le "$RUNS" ]; do
    j=0; while [ "$j" -lt "$NC" ]; do
      EQ_RUN_IMAGE=${CT[$j]}; eq_pf_check "$TIME_ITEM" ref oracle
      TIMES[$j]="${TIMES[$j]} $PF_MS"
      echo "  round $r  ${CN[$j]}: score=$PF_SCORE  $PF_MS ms"
      j=$((j + 1))
    done
    r=$((r + 1))
  done
  echo
else
  echo "== 1. timing and PF behaviour skipped: EQ_ITEMS (the pools) not found"; echo
fi

# ------------------------------------------------------------------ 2. PF behaviour on the smoke items
NI=$(printf '%s\n' $ITEMS_SMOKE | grep -c .); NK=$((NI * 2))
PFRES=()   # index j*NK + 2*item + (0 ref | 1 wrong)  ->  "score|normalized detail"
if [ "$have_items" = 1 ]; then
  echo "== 2. PF behaviour (reference want 1, wrong want 0)"
  k=0
  for item in $ITEMS_SMOKE; do
    for kind in ref wrong; do
      kk=0; [ "$kind" = wrong ] && kk=1
      j=0; while [ "$j" -lt "$NC" ]; do
        EQ_RUN_IMAGE=${CT[$j]}; eq_pf_check "$item" "$kind" oracle
        PFRES[$((j * NK + 2 * k + kk))]="$PF_SCORE|$(printf '%s' "$PF_DETAIL" | norm)"
        echo "  $item $kind ${CN[$j]}: score=$PF_SCORE $(printf '%s' "$PF_DETAIL" | cut -c1-80)"
        j=$((j + 1))
      done
    done
    k=$((k + 1))
  done
  echo
fi

# ------------------------------------------------------------------ 3. inventory
INV_N=(); INV_LN=(); INV_B=(); INV_SUID=(); INV_EXE=(); INV_SH=(); INV_PKG=(); INV_MOD=(); INV_SZ=(); INV_BUILD=()
inventory() { # index label tag
  local k=$1 name=$2 tag=$3 cid f="$OUT/$2.files.txt" line
  cid=$(docker create --pull never "$tag" /nonexistent) || { echo "docker create failed for $tag" >&2; return 0; }
  docker export "$cid" | tar -tvf - 2>/dev/null | awk '
    { if ($2 ~ /\//) { sz = $3; path = $6 } else { sz = $5; path = $9 }
      printf "%s\t%s\t%s\n", sz, $1, path }' > "$f"
  docker rm "$cid" >/dev/null
  line=$(awk -F'\t' '
    BEGIN { n_sh = split("sh bash dash ash zsh ksh busybox perl python python3 git curl wget nc ssh su sudo gcc cc make", S, " ")
            n_pk = split("apt apt-get dpkg pip pip3 npm uv", P, " ")
            for (i = 1; i <= n_sh; i++) isS[S[i]] = 1
            for (i = 1; i <= n_pk; i++) isP[P[i]] = 1 }
    { path = $3; b = path; sub(/ -> .*/, "", b); q_n = split(b, q, "/"); b = q[q_n]
      if (isS[b] && !(b in seenS)) { seenS[b] = 1; sh = sh (sh == "" ? "" : ",") b }
      if (isP[b] && !(b in seenP)) { seenP[b] = 1; pk = pk (pk == "" ? "" : ",") b }
      if ($2 ~ /^l/) { ln++ }
      if ($2 ~ /^-/) { n++; bytes += $1
        if (substr($2, 4, 1) ~ /[sS]/ || substr($2, 7, 1) ~ /[sS]/) suid++
        if ($2 ~ /x/) ex++
        if (path ~ /\.(olean|olean\.private|olean\.server|ir|ir\.sig|ilean)$/) mod += $1 } }
    END { printf "%d %d %d %d %d %s %s %d\n", n, ln, bytes, suid, ex, (sh == "" ? "none" : sh), (pk == "" ? "none" : pk), mod }' "$f")
  # shellcheck disable=SC2162
  read INV_N[$k] INV_LN[$k] INV_B[$k] INV_SUID[$k] INV_EXE[$k] INV_SH[$k] INV_PKG[$k] INV_MOD[$k] <<EOF
$line
EOF
  echo "  $name ($tag): ${INV_N[$k]} files, ${INV_LN[$k]} symlinks, $(awk -v b="${INV_B[$k]}" 'BEGIN{printf "%.1f MB", b/1e6}'), module files $(awk -v b="${INV_MOD[$k]}" 'BEGIN{printf "%.1f MB", b/1e6}'), setuid/setgid ${INV_SUID[$k]}, executables ${INV_EXE[$k]}"
  echo "     shells/interpreters: ${INV_SH[$k]}   package managers: ${INV_PKG[$k]}   list: $f"
}
rec_name() { case "$1" in full) echo full;; lean-min) echo min-lean;; lean-dl) echo dl-lean;; *) echo none;; esac; }
i=0; while [ "$i" -lt "$NC" ]; do
  INV_SZ[$i]=$(docker image inspect --format '{{.Size}}' "${CT[$i]}" 2>/dev/null || echo 0)
  INV_N[$i]=-; INV_LN[$i]=-; INV_B[$i]=0; INV_SUID[$i]=-; INV_EXE[$i]=-; INV_SH[$i]=-; INV_PKG[$i]=-; INV_MOD[$i]=0
  r=$(eq_img_get "$(rec_name "${CN[$i]}")" EQ_BUILD_SECONDS); INV_BUILD[$i]=${r:--}
  i=$((i + 1))
done
if [ "$SKIP_INV" = 0 ]; then
  echo "== 3. inventory (docker create + export; nothing is started)"
  i=0; while [ "$i" -lt "$NC" ]; do inventory "$i" "${CN[$i]}" "${CT[$i]}"; i=$((i + 1)); done
  echo
fi
size_of() { if [ "$SKIP_INV" = 0 ]; then echo "${INV_B[$1]}"; else echo "${INV_SZ[$1]}"; fi; }

# ------------------------------------------------------------------ 4. CP rows (the python image vs the baseline)
CP_ROWS=(); cp_diffs=0; cp_ran=0
if [ "$SKIP_CP" = 0 ] && have "$PMIN"; then eq_require_image "$PMIN"; fi   # F9: record check, then run by the verified ID
cmp_row() { if [ "$2" = "$3" ]; then CP_ROWS[${#CP_ROWS[@]}]=$(printf '%-30s SAME   %s' "$1" "$(printf '%s' "$2" | tr '\n' ' ' | cut -c1-90)")
  else CP_ROWS[${#CP_ROWS[@]}]=$(printf '%-30s DIFF   full: %s || min: %s' "$1" "$(printf '%s' "$2" | tr '\n' ' ' | cut -c1-60)" "$(printf '%s' "$3" | tr '\n' ' ' | cut -c1-60)"); cp_diffs=$((cp_diffs + 1)); fi; }
if [ "$SKIP_CP" = 0 ] && have "$PMIN" && [ -n "$EQ_ITEMS" ] && [ -d "$EQ_ITEMS/CP" ] && eq_have uv; then
  id=CP-0001; w=$(mktemp -d "$EQ_WORK_ROOT/cmp.XXXXXX")
  ( cd "$EQ_ITEMS/CP" && uv run --no-project python -c '
import sys
sys.path.insert(0, "oracle")
import refs
i, ref, seed, ans = sys.argv[1:5]
refs.reference_workdir(i, ref); refs.seeded_workdir(i, seed); refs.answer_json(ans)' "$id" "$w/ref" "$w/seed" "$w/ans.json" ) >/dev/null 2>&1
  if [ -d "$w/seed" ]; then
    mkdir -p "$w/answer"; cp "$w/ans.json" "$w/answer/a.json"; chmod -R a+rX "$w"
    cp_run() { # image dir cmd...
      local img=$1 dir=$2; shift 2
      local copy; copy=$(mktemp -d "$w/c.XXXXXX"); cp -R "$w/$dir/." "$copy/"; chmod -R a+rX "$copy"
      EQ_RUN_IMAGE=$img
      EQ_RUN_MOUNTS=(--mount "type=bind,source=$copy,target=/work" --mount "type=bind,source=$EQ_ITEMS/CP,target=/items/CP,readonly" --mount "type=bind,source=$w/answer,target=/ans,readonly")
      EQ_RUN_EXTRA=(); EQ_RUN_STDIN=""
      local o rc; o=$(eq_run "eq-$EQ_RUN_ID-cmp-cp" 300 "$@" 2>&1); rc=$?
      printf 'rc=%s %s' "$rc" "$(printf '%s' "$o" | norm | tail -n 3)"
    }
    pub=(uv run --no-project python -m unittest discover -s tests -t . -q)
    orc=(uv run /items/CP/oracle.py --item "$id" --answer /ans/a.json --workdir /work)
    cmp_row "$id public check, seeded" "$(cp_run "$FULL" seed "${pub[@]}")" "$(cp_run "$PMIN" seed "${pub[@]}")"
    cmp_row "$id oracle, seeded workdir" "$(cp_run "$FULL" seed "${orc[@]}")" "$(cp_run "$PMIN" seed "${orc[@]}")"
    cmp_row "$id oracle, reference workdir" "$(cp_run "$FULL" ref "${orc[@]}")" "$(cp_run "$PMIN" ref "${orc[@]}")"
    cp_ran=1
  else echo "CP cases skipped (could not build the reference workdir with the host uv)"; fi
  rm -rf "$w"
else echo "CP cases skipped (need the py-min image, EQ_ITEMS with CP and a host uv; or --skip-cp)"; fi

prov() { docker run --rm --pull never --network none --user 10001:10001 "$(eq_resolve_image "$1")" cat /opt/eq/PROVENANCE.txt 2>/dev/null | sed -n 's/^olean_tree_sha256: //p' | head -n 1; }
result_of() { # kind tag -> PASS|FAIL|INCOMPLETE|n/a   (results/<kind>.<tag with : / @ as _>.env from spike.sh / probe.sh / reverify.sh)
  local san f up v
  san=$(printf '%s' "$2" | tr ':/@' '___'); f="$EQ_STATE_DIR/results/$1.$san.env"; up=$(printf '%s' "$1" | tr '[:lower:]' '[:upper:]')
  [ -f "$f" ] || { echo "n/a"; return 0; }
  v=$(sed -n "s/^${up}_RESULT=//p" "$f" | head -n 1); echo "${v:-n/a}"
}

# ------------------------------------------------------------------ 5. the table and the rule
base_ms=$(median ${TIMES[0]}); base_b=$(size_of 0); base_hash=$(prov "${CT[0]}")
echo "== 4. DECISION TABLE (measured by this run; exp_MB = sum of regular-file sizes of the exported rootfs, insp_MB = docker image inspect .Size)"
printf '%-13s %8s %8s %7s %6s %4s %-24s %-9s %7s %-6s %-6s %8s %8s %6s %6s %-6s %-6s\n' \
  CANDIDATE insp_MB exp_MB files links suid shells/interp pkgmgr build_s PFgate olean cold_ms med_ms time% size% spike probe
elig=""; incomplete=""; picked=""; pick_b=0; any_diff=0; notes=""
j=0; while [ "$j" -lt "$NC" ]; do
  name=${CN[$j]}; tag=${CT[$j]}
  med=$(median ${TIMES[$j]}); cold=$(printf '%s\n' ${TIMES[$j]} | grep -E '^[0-9]+$' | head -n 1); cold=${cold:-0}
  b=$(size_of "$j")
  gate=SAME
  if [ "$have_items" = 0 ]; then gate="n/a"
  else
    m=0; while [ "$m" -lt "$NK" ]; do
      want=1; [ $((m % 2)) = 1 ] && want=0
      a=${PFRES[$m]:-}; c=${PFRES[$((j * NK + m))]:-}
      case "$c" in "$want|"*) ;; *) gate=FAIL;; esac
      if [ "$a" != "$c" ] && [ "$gate" != FAIL ]; then gate=DIFF; fi
      m=$((m + 1))
    done
  fi
  h=$(prov "$tag"); oh=SAME; { [ -n "$h" ] && [ "$h" = "$base_hash" ]; } || oh=DIFF
  tp=0; [ "$base_ms" -gt 0 ] && tp=$((med * 100 / base_ms))
  sp=0; [ "$base_b" -gt 0 ] && sp=$((b * 100 / base_b))
  sres=$(result_of spike "$tag"); pres=$(result_of probe "$tag")
  printf '%-13s %8.0f %8.0f %7s %6s %4s %-24s %-9s %7s %-6s %-6s %8s %8s %5s%% %5s%% %-6s %-6s\n' \
    "$name" "$(awk -v b="${INV_SZ[$j]}" 'BEGIN{print b/1e6}')" "$(awk -v b="$b" 'BEGIN{print b/1e6}')" "${INV_N[$j]}" "${INV_LN[$j]}" "${INV_SUID[$j]}" \
    "${INV_SH[$j]}" "${INV_PKG[$j]}" "${INV_BUILD[$j]}" "$gate" "$oh" "$cold" "$med" "$tp" "$sp" "$sres" "$pres"
  if [ "$j" != 0 ]; then
    fail=""; miss=""
    case "$gate" in SAME) ;; n/a) miss="$miss pools";; *) fail="$fail PFgate=$gate";; esac
    [ "$oh" = SAME ] || fail="$fail olean=DIFF"
    if [ "$have_items" = 1 ]; then { [ "$tp" -gt 0 ] && [ "$tp" -le $((100 + TOL)) ]; } || fail="$fail time=${tp}%(>$((100 + TOL))%)"; fi
    case "$sres" in PASS) ;; n/a) miss="$miss spike";; *) fail="$fail spike=$sres";; esac
    case "$pres" in PASS) ;; n/a) miss="$miss probe";; *) fail="$fail probe=$pres";; esac
    if [ -n "$fail" ]; then
      notes="$notes
  not eligible: $name ->$fail"
      case "$fail" in *PFgate=*|*olean=*) any_diff=1;; esac
    elif [ -n "$miss" ]; then incomplete="$incomplete $name(missing:$miss)"
    else
      elig="$elig $name"
      if [ -z "$picked" ] || [ "$b" -lt "$pick_b" ]; then picked=$name; pick_b=$b; fi
    fi
  fi
  j=$((j + 1))
done
[ -z "$notes" ] || printf '%s\n' "$notes"
if [ -n "$picked" ]; then   # an eligible FROM-scratch candidate within 5% of the smallest wins
  for c in $elig; do
    case "$c" in lean-min|scratch-*)
      j=0; while [ "$j" -lt "$NC" ]; do
        if [ "${CN[$j]}" = "$c" ] && [ "$(size_of "$j")" -le $((pick_b * 105 / 100)) ]; then picked=$c; break 2; fi
        j=$((j + 1))
      done;;
    esac
  done
fi
echo
if [ "$cp_ran" = 1 ]; then
  echo "py-min vs baseline (CP-0001):"; for r in "${CP_ROWS[@]}"; do echo "  $r"; done
  if [ "$cp_diffs" = 0 ]; then echo "  py-min CP rows: all SAME"; else echo "  py-min CP rows: $cp_diffs DIFF -> do not use this py image"; fi
  echo
fi
if [ -n "$BMIN" ] && have "$BMIN" && have "$PMIN"; then
  sb=$(docker image inspect --format '{{.Size}}' "$BMIN"); spy=$(docker image inspect --format '{{.Size}}' "$PMIN"); sl=$(docker image inspect --format '{{.Size}}' "$LMIN" 2>/dev/null || echo 0)
  echo "ONE-vs-TWO (docker image inspect .Size): eq-min $(awk -v b="$sb" 'BEGIN{printf "%.0f", b/1e6}') MB vs eq-lean-min + eq-py-min $(awk -v a="$sl" -v b="$spy" 'BEGIN{printf "%.0f", (a+b)/1e6}') MB"
  echo "  rule: two images (a separate, smaller attack surface per class) unless eq-min is more than 25% smaller than the pair: $(awk -v a="$sb" -v b="$sl" -v c="$spy" 'BEGIN{ if (a < 0.75 * (b + c)) print "ONE image is >25% smaller"; else print "TWO images (eq-min saves <=25%)" }')"
  echo
fi
echo "BASELINE ${CN[0]}: median ${base_ms} ms, ${base_b} bytes. time% and size% are relative to it; cold_ms is round 1."
[ -z "$incomplete" ] || echo "INCOMPLETE (run the missing step, then this script again):$incomplete"
echo "ELIGIBLE:${elig:- none}"
if [ -n "$picked" ]; then echo "PICK: $picked  (smallest eligible; a FROM-scratch candidate within 5% wins)"; else echo "PICK: none -> keep the baseline ${CN[0]}"; fi
[ "$any_diff" = 0 ] || echo "NOTE: a candidate's PF verdicts or olean tree differ from the baseline (see the not eligible lines)"
if [ -n "$picked" ]; then echo "COMPARE: PICK $picked"; exit 0; fi
echo "COMPARE: no candidate eligible"
exit 1
