#!/usr/bin/env bash
# shellcheck disable=SC2016,SC2012,SC2086,SC2329,SC2015
# trace-reads.sh (user-run, needs network ONCE for apt inside a diagnostic container): which files do the PF checks really
# open? It answers whether .olean.private / .olean.server / .ir / .ilean are read at check time, so the minimal image can be
# built with a smaller --keep-profile. Runs the trusted reference and wrong answers of a few items under `strace -f` in the
# FULL image (Debian), as root, with default capabilities and a network (apt installs strace). NOT an isolation test.
#   ./trace-reads.sh [ITEM ...]       default: first, 100th and last non-dev PF item     (needs EQ_ITEMS and the full image)
# Output: $EQ_STATE_DIR/trace/{opened.txt,execs.txt,summary.txt}. Coverage caveat: a trace shows what THESE answers read
# (.ir files are read lazily by the interpreter, so other tactics could read more). The decision is the reverify run on a
# --keep-profile build, never the trace alone.
set -u
here=$(cd "$(dirname "$0")" && pwd -P)
# shellcheck disable=SC1091
. "$here/lib.sh"
eq_need_items
eq_need_docker
FULLTAG=$(eq_img_tag full)
eq_require_image "$FULLTAG"
EQ_RUN_IMAGE_REPORT=$FULLTAG
T="$EQ_STATE_DIR/trace"; rm -rf "$T"; mkdir -p "$T"
if [ $# -gt 0 ]; then items=$*
else items=$(jq -r 'select((.dev // false) | not) | .id' "$EQ_ITEMS/PF/manifest.jsonl" | sed -n '1p;100p;$p'); fi
for it in $items; do
  for kind in ref wrong; do
    d="$T/case-$it-$kind"; mkdir -p "$d"
    cp -R "$EQ_ITEMS/PF/fixtures/$it/." "$d/"; cp "$EQ_ITEMS/PF/check_lean.sh" "$EQ_ITEMS/PF/EqVerify.lean" "$d/"
    cp "$EQ_ITEMS/PF/oracle/$kind/$it.lean" "$d/Answer.lean"
  done
done
chmod -R a+rwX "$T"
name="eq-$EQ_RUN_ID-trace"
trap 'docker rm -f "$name" >/dev/null 2>&1' EXIT INT TERM
docker run --rm --name "$name" --pull never --label eq-harness=1 --user root --security-opt no-new-privileges \
  --pids-limit 1024 --memory "$EQ_MEMORY" --cpus "$EQ_CPUS" \
  --mount "type=bind,source=$T,target=/out" "$FULLTAG" bash -c '
set -u
apt-get update -qq >/dev/null 2>&1 && apt-get install -y -qq --no-install-recommends strace >/dev/null 2>&1 || { echo "apt install strace failed (network? the snapshot host must be reachable)"; exit 2; }
export TMPDIR=/tmp
for d in /out/case-*; do
  b=$(basename "$d"); cd "$d" || continue
  strace -f -qq -e trace=openat,execve -o "/out/trace-$b.txt" bash check_lean.sh Answer.lean > "/out/result-$b.txt" 2>&1
  echo "$b: $(tail -n 1 /out/result-$b.txt)"
done
cat /out/trace-*.txt | grep -E "openat\(.*\) = [0-9]+$" | sed -E "s/.*\"([^\"]+)\".*/\1/" | grep "^/" | sort -u > /out/opened.txt
cat /out/trace-*.txt | grep -E "execve\(.*\) = 0$" | sed -E "s/.*execve\(\"([^\"]+)\".*/\1/" | sort | uniq -c | sort -rn > /out/execs.txt
grp() { awk "{ f=\$2; e=\"other\"; if (f ~ /\\.olean\\.private\$/) e=\"olean.private\"; else if (f ~ /\\.olean\\.server\$/) e=\"olean.server\"; else if (f ~ /\\.olean\$/) e=\"olean\"; else if (f ~ /\\.ir\\.sig\$/) e=\"ir.sig\"; else if (f ~ /\\.ir\$/) e=\"ir\"; else if (f ~ /\\.ilean\$/) e=\"ilean\"; else if (f ~ /\\.so/) e=\"so\"; n[e]++; b[e]+=\$1 } END { for (e in n) printf \"  %-14s %6d files %9.1f MB\\n\", e, n[e], b[e]/1e6 }" | sort; }
{
  echo "READ (opened successfully by the traced checks), under /opt:"
  grep "^/opt/" /out/opened.txt | xargs -d "\n" stat -c "%s %n" 2>/dev/null | grp
  echo "PRESENT under /opt in the full image:"
  find /opt -type f -printf "%s %p\n" 2>/dev/null | grp
  echo "READ outside /opt (system files), count: $(grep -vc "^/opt/" /out/opened.txt)"
  echo "executables started (count path):"; head -n 30 /out/execs.txt
} > /out/summary.txt
'
rc=$?
[ -f "$T/summary.txt" ] && cat "$T/summary.txt"
echo "trace dir: $T"
exit $rc
