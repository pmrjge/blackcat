#!/usr/bin/env bash
# shellcheck disable=SC2016,SC2012,SC2086,SC2329,SC2015
# reverify.sh (user-run): re-verify the pools inside the container, parallel and resumable.
#   ./reverify.sh [--jobs N] [--out DIR] [--mode oracle|public|both] [--stages LIST] [--only ID,ID] [--limit N] [--fresh]
#
# PF stage: for every PF manifest item (218) run the reference proof (expect score 1) and the gap-following wrong answer
#   (expect 0) through the container with the full hardening flags, then compare per item with
#   items/PF/oracle/build/final_check.tsv (the host baseline). mode oracle = items/PF/check_lean.sh over the fixture (what
#   oracle.py ran for the baseline; default), public = the fixture exactly as shipped, both = the two.
# Other stages (LIST, comma separated; default all): pf_selftest cp cr es cp_prove cr_prove  (the pools' own selftest.sh /
#   prove_pool.py, run read-only from /items/<CLS>; prove_pool works on a tmpfs copy and its report is compared with the
#   shipped proof_report.txt, first 3 lines).
# Resumable: finished items are kept in DIR/pf/ and skipped on re-run (errors and timeouts are re-run); --fresh wipes DIR.
# Images: PF checks use EQ_IMAGE (override: a tag, an image ID, or name@sha256:..); cp/cr/es/*_prove use EQ_IMAGE_PY; pf_selftest
#   needs lean+python+jq (EQ_IMAGE_BOTH). EQ_PROFILE=min targets the FROM-scratch images (see RUNBOOK_MINIMAL.md). With EQ_IMAGE
#   alone (no EQ_IMAGE_PY) the default stages are 'pf' only. Needs EQ_ITEMS (the pools).
# Output: DIR/reverify.tsv (per item), DIR/stages.tsv, DIR/logs/, DIR/summary.txt. Exit 0 only if everything matches.
set -u
here=$(cd "$(dirname "$0")" && pwd -P)
# shellcheck disable=SC1091
. "$here/lib.sh"

JOBS=${EQ_JOBS:-8}     # 8 jobs x 2 CPUs = the 16 CPUs of the Docker Desktop VM; 8 x 8 GiB memory cap = 64 of 253 GiB
OUT="$EQ_STATE_DIR/reverify-out"
MODE=oracle
STAGES=pf_selftest,cp,cr,es,cp_prove,cr_prove,pf
ONLY=""; LIMIT=0; FRESH=0; WORKER=""; STAGES_SET=0
while [ $# -gt 0 ]; do
  case "$1" in
    --jobs) JOBS=${2:?}; shift;;
    --out) OUT=${2:?}; shift;;
    --mode) MODE=${2:?}; shift;;
    --stages) STAGES=${2:?}; STAGES_SET=1; shift;;
    --only) ONLY=${2:?}; shift;;
    --limit) LIMIT=${2:?}; shift;;
    --fresh) FRESH=1;;
    --worker) WORKER=${2:?}; shift;;
    -h|--help) sed -n '2,17p' "$0"; exit 0;;
    *) echo "unknown argument: $1" >&2; exit 2;;
  esac
  shift
done
case "$MODE" in oracle|public|both) ;; *) eq_die "--mode must be oracle, public or both";; esac
# EQ_IMAGE alone names ONE image: the python stages (and the PF dev selftest, which needs python + jq) would run in it too and
# fail for a lean-only image. So the default becomes the PF stage only; name --stages to override.
if [ -z "$WORKER" ] && [ "$STAGES_SET" = 0 ] && [ -n "${EQ_IMAGE:-}" ] && [ "$EQ_PY_EXPLICIT" = 0 ] && [ "$EQ_PROFILE" = full ]; then
  STAGES=pf
  echo "note: EQ_IMAGE is set without EQ_IMAGE_PY: stages default to 'pf' only (set EQ_IMAGE_PY / EQ_IMAGE_BOTH or --stages to run the others)"
fi
mkdir -p "$OUT"; OUT=$(cd "$OUT" && pwd -P)
case "$JOBS" in ''|*[!0-9]*) eq_die "--jobs must be a number";; esac
[ "$JOBS" -ge 1 ] || eq_die "--jobs must be >= 1"
modes=$MODE; [ "$MODE" = both ] && modes="oracle public"

# ------------------------------------------------------------------ worker: one PF item, ref + wrong, per mode
if [ -n "$WORKER" ]; then
  item=$WORKER
  for mode in $modes; do
    f="$OUT/pf/$item.$mode.tsv"
    if [ -f "$f" ] && awk -F'\t' '{ok = (($3 == "1" || $3 == "0") && ($4 == "1" || $4 == "0")); exit !ok}' "$f"; then continue; fi
    eq_pf_check "$item" ref "$mode";   rs=$PF_SCORE; rt=$PF_SECS; rd=$PF_DETAIL
    eq_pf_check "$item" wrong "$mode"; ws=$PF_SCORE; wt=$PF_SECS; wd=$PF_DETAIL
    printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n' "$item" "$mode" "$rs" "$ws" "$rt" "$wt" "$rd" "$wd" > "$f.tmp.$$" && mv "$f.tmp.$$" "$f"
  done
  exit 0
fi

# ------------------------------------------------------------------ parent
eq_need_items
eq_need_docker
eq_require_image "$EQ_IMAGE_TAG" "$EQ_IMAGE_PY" "$EQ_IMAGE_BOTH"
EQ_RUN_IMAGE_REPORT=$EQ_IMAGE_TAG; EQ_IMAGE_ID_REPORT=$EQ_IMAGE_ID_NOW
[ "$FRESH" = 1 ] && rm -rf "$OUT/pf" "$OUT/stages" "$OUT/logs" "$OUT/reverify.tsv" "$OUT/stages.tsv" "$OUT/summary.txt"
mkdir -p "$OUT/pf" "$OUT/stages" "$OUT/logs"
export EQ_RUN_ID OUT MODE
progress_pid=""; bg_pid=""
cleanup() {
  [ -n "$progress_pid" ] && kill "$progress_pid" 2>/dev/null
  [ -n "$bg_pid" ] && kill "$bg_pid" 2>/dev/null
  pkill -P $$ 2>/dev/null
  eq_sweep
}
trap 'cleanup' EXIT
trap 'echo; echo "interrupted: containers removed; re-run the same command to resume"; exit 130' INT TERM

start=$SECONDS
echo "images  : pf=$EQ_IMAGE_TAG ($EQ_IMAGE_ID_NOW) py=$EQ_IMAGE_PY both=$EQ_IMAGE_BOTH  profile $EQ_PROFILE"
echo "limits  : --cpus $EQ_CPUS --memory $EQ_MEMORY --pids-limit $EQ_PIDS --user $EQ_USER, jobs $JOBS, mode $MODE"
echo "output  : $OUT   run id $EQ_RUN_ID"
orph=$(eq_orphans); [ -n "$orph" ] && { echo "note: containers from other runs exist (left alone):"; echo "$orph"; }

# preflight: host-side provenance, informational (never gating)
{
  echo "# preflight $(date '+%F %T')"
  for c in PF CP CR ES; do
    if (cd "$EQ_ITEMS/$c" && { if command -v shasum >/dev/null 2>&1; then shasum -a 256 -c pool.sha256 --quiet; else sha256sum -c --quiet pool.sha256; fi; } >/dev/null 2>&1); then echo "pool.sha256 $c: OK"; else echo "pool.sha256 $c: MISMATCH or unreadable"; fi
  done
  nstale=0; ntot=0
  for fx in "$EQ_ITEMS"/PF/fixtures/*/; do
    ntot=$((ntot + 1))
    if ! cmp -s "$EQ_ITEMS/PF/check_lean.sh" "${fx}check_lean.sh" || ! cmp -s "$EQ_ITEMS/PF/EqVerify.lean" "${fx}EqVerify.lean"; then nstale=$((nstale + 1)); fi
  done
  echo "PF fixtures whose check_lean.sh/EqVerify.lean differ from items/PF/: $nstale of $ntot"
  echo "image provenance:"; docker run --rm --pull never --network none --user 10001:10001 "$EQ_IMAGE_TAG" cat /opt/eq/PROVENANCE.txt | sed 's/^/  /'
} > "$OUT/preflight.txt" 2>&1
cat "$OUT/preflight.txt"
echo

want() { case ",$STAGES," in *",$1,"*) return 0;; esac; return 1; }

# ------------------------------------------------------------------ non-PF stages: one container each, items/<CLS> read-only
: > "$OUT/stages.tsv.new"
run_stage() { # name class command...
  local name=$1 cls=$2; shift 2
  case "$name" in pf_selftest) EQ_RUN_IMAGE=$EQ_IMAGE_BOTH;; *) EQ_RUN_IMAGE=$EQ_IMAGE_PY;; esac
  local t0=$SECONDS rc log="$OUT/logs/$name.log" p f
  if [ -f "$OUT/stages/$name.done" ]; then echo "stage $name: already done ($(cat "$OUT/stages/$name.done"))"; return 0; fi
  EQ_RUN_MOUNTS=(--mount "type=bind,source=$EQ_ITEMS/$cls,target=/items/$cls,readonly"); EQ_RUN_EXTRA=(); EQ_RUN_STDIN=""
  eq_run "eq-$EQ_RUN_ID-$name" "${EQ_STAGE_TIMEOUT:-3600}" "$@" > "$log" 2>&1
  rc=$?
  p=$(grep -c '^PASS' "$log"); f=$(grep -c '^FAIL' "$log")
  echo "$rc	$p	$f	$((SECONDS - t0))" > "$OUT/stages/$name.res"
  if [ "$rc" = 0 ]; then echo "$rc pass=$p fail=$f" > "$OUT/stages/$name.done"; fi
  echo "stage $name: rc=$rc PASS=$p FAIL=$f ($((SECONDS - t0))s)  log $log"
}
prove_cmd() { # class
  echo "cp -R /items/$1 /tmp/$1 && cd /tmp/$1 && uv run prove_pool.py; rc=\$?; head -n 3 /tmp/$1/proof_report.txt > /tmp/new.txt; head -n 3 /items/$1/proof_report.txt > /tmp/old.txt; if diff /tmp/old.txt /tmp/new.txt; then echo 'PASS report first 3 lines match shipped proof_report.txt'; else echo 'FAIL report differs from shipped proof_report.txt'; rc=1; fi; exit \$rc"
}
want cp       && run_stage cp_selftest CP bash /items/CP/selftest.sh
want cr       && run_stage cr_selftest CR bash /items/CR/selftest.sh
want es       && run_stage es_selftest ES bash /items/ES/selftest.sh
want cp_prove && run_stage cp_prove CP bash -c "$(prove_cmd CP)"
want cr_prove && run_stage cr_prove CR bash -c "$(prove_cmd CR)"

# the PF selftest (39 sequential Lean checks) runs in the background next to the PF stage
if want pf_selftest; then
  ( run_stage pf_selftest PF bash /items/PF/selftest.sh ) > "$OUT/logs/pf_selftest.stage.out" 2>&1 &
  bg_pid=$!
fi

# ------------------------------------------------------------------ PF stage
if want pf; then
  ids=$(jq -r '.id' "$EQ_ITEMS/PF/manifest.jsonl")
  if [ -n "$ONLY" ]; then ids=$(printf '%s\n' "$ids" | grep -Fxf <(printf '%s\n' "$ONLY" | tr ',' '\n')); fi
  if [ "$LIMIT" -gt 0 ]; then ids=$(printf '%s\n' "$ids" | head -n "$LIMIT"); fi
  total=$(printf '%s\n' "$ids" | grep -c .)
  pending=""
  for id in $ids; do
    need=0
    for m in $modes; do
      f="$OUT/pf/$id.$m.tsv"
      if [ ! -f "$f" ] || ! awk -F'\t' '{ok = (($3 == "1" || $3 == "0") && ($4 == "1" || $4 == "0")); exit !ok}' "$f"; then need=1; fi
    done
    [ $need = 1 ] && pending="$pending$id
"
  done
  npend=$(printf '%s' "$pending" | grep -c .)
  echo "PF: $total items x 2 answers x modes($modes); $((total - npend)) items already done, $npend to run with $JOBS jobs"
  if [ "$npend" -gt 0 ]; then
    t_pf=$SECONDS
    ( while sleep 60; do
        d=$(find "$OUT/pf" -name '*.tsv' | wc -l | tr -d ' ')
        n_modes=$(echo $modes | wc -w | tr -d ' ')
        el=$((SECONDS - t_pf));
        echo "  [$(date +%H:%M:%S)] PF result files: $d / $((total * n_modes)) (elapsed $((el / 60)) min)"
      done ) &
    progress_pid=$!
    # one worker process per item; xargs -P keeps JOBS of them running (each worker runs its two checks one after the other)
    printf '%s' "$pending" | xargs -P "$JOBS" -n 1 bash "$here/reverify.sh" --out "$OUT" --mode "$MODE" --worker
    kill "$progress_pid" 2>/dev/null; progress_pid=""
    echo "PF stage wall time: $(( (SECONDS - t_pf) / 60 )) min"
  fi
fi
if [ -n "$bg_pid" ]; then echo "waiting for pf_selftest ..."; wait "$bg_pid"; bg_pid=""; cat "$OUT/logs/pf_selftest.stage.out"; fi

# ------------------------------------------------------------------ aggregate and compare with the host baseline
base="$EQ_ITEMS/PF/oracle/build/final_check.tsv"
{
  printf 'id\tmode\tref_score\twrong_score\tref_s\twrong_s\texpected_1_0\tbaseline_ref\tbaseline_wrong\tmatches_baseline\tref_detail\twrong_detail\n'
  find "$OUT/pf" -name '*.tsv' -print | LC_ALL=C sort | xargs cat | \
    awk -F'\t' -v OFS='\t' -v base="$base" '
      BEGIN { while ((getline line < base) > 0) { split(line, a, "\t"); if (a[1] != "id") { br[a[1]] = a[2]; bw[a[1]] = a[3] } } }
      { okp = ($3 == "1" && $4 == "0") ? "yes" : "NO";
        b1 = (($1 in br) ? br[$1] : "-"); b2 = (($1 in bw) ? bw[$1] : "-");
        m = ($3 == b1 && $4 == b2) ? "yes" : "NO";
        print $1, $2, $3, $4, $5, $6, okp, b1, b2, m, $7, $8 }'
} > "$OUT/reverify.tsv"

{
  echo "stage	rc	pass_lines	fail_lines	seconds"
  for r in "$OUT"/stages/*.res; do [ -f "$r" ] && printf '%s\t%s\n' "$(basename "$r" .res)" "$(cat "$r")"; done
} > "$OUT/stages.tsv"
rm -f "$OUT/stages.tsv.new"

{
  echo "reverify summary $(date '+%F %T')  image $EQ_IMAGE_TAG $EQ_IMAGE_ID_NOW"
  awk -F'\t' 'NR > 1 {
      n++; if ($7 == "yes") ok++; else bad++; if ($10 == "yes") m++;
      if ($3 != "1" && $3 != "0") err++; if ($4 != "1" && $4 != "0") err++;
      rs += $5; ws += $6; if ($5 > mx) mx = $5; if ($6 > mx) mx = $6 }
    END { printf "PF rows: %d  ref=1 and wrong=0: %d  not: %d  errors/timeouts: %d  match final_check.tsv: %d/%d\n", n, ok, bad, err, m, n;
          if (n) printf "seconds per check (incl. container start): mean ref %.1f  mean wrong %.1f  max %d  serial total %.1f min\n", rs / n, ws / n, mx, (rs + ws) / 60 }' "$OUT/reverify.tsv"
  echo "wall time of this invocation: $(( (SECONDS - start) / 60 )) min at $JOBS jobs"
  echo "stages:"; if command -v column >/dev/null 2>&1; then column -t -s "$(printf '\t')" "$OUT/stages.tsv" | sed 's/^/  /'; else sed 's/^/  /' "$OUT/stages.tsv"; fi
  echo "mismatches (up to 20):"
  awk -F'\t' 'NR > 1 && ($7 != "yes" || $10 != "yes") { print "  " $1, $2, "ref=" $3, "wrong=" $4, "baseline=" $8 "/" $9, $11, $12 }' "$OUT/reverify.tsv" | head -n 20
} | tee "$OUT/summary.txt"

bad_pf=$(awk -F'\t' 'NR > 1 && ($7 != "yes" || $10 != "yes") { c++ } END { print c + 0 }' "$OUT/reverify.tsv")
bad_st=$(awk -F'\t' 'NR > 1 && $2 != 0 { c++ } END { print c + 0 }' "$OUT/stages.tsv")
n_pf=$(awk 'END { print NR - 1 }' "$OUT/reverify.tsv")
echo
if want pf && [ "$n_pf" -lt "${total:-0}" ]; then eq_write_result reverify INCOMPLETE "$n_pf"; echo "REVERIFY: INCOMPLETE ($n_pf of ${total:-?} PF rows); re-run to resume"; exit 3; fi
if [ "$bad_pf" = 0 ] && [ "$bad_st" = 0 ]; then eq_write_result reverify PASS 0; echo "REVERIFY: PASS"; exit 0; fi
eq_write_result reverify FAIL "$((bad_pf + bad_st))"
echo "REVERIFY: FAIL (PF mismatches $bad_pf, failing stages $bad_st) -- see $OUT/summary.txt"
exit 1
