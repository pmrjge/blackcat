#!/bin/bash
# STUB lib/eq-container/eq-container.sh for the installer tests (tests/test_install_eq_container.py commits it over the
# driver in its scratch repos): it writes what a run of the real
# driver leaves behind (status.env, image.env, results/tunnel.*.env) and never calls a container CLI. Knobs:
#   EQ_STUB_LOG          append "$0<0x1f>$*" per call
#   EQ_STUB_RC           install's exit code (0 ok, 10 skipped, anything else failed); EQ_STUB_DRY_RC for --dry-run
#   EQ_STUB_DIGEST       the images' digest (default sha256:a{64})
#   EQ_STUB_TUNNEL       PASS (default), FAIL, or none (no tunnel result is written)
#   EQ_STUB_ISOLATION, EQ_STUB_PRINT_IMAGE   what print-env prints (default: container, the PF ref)
set -u
printf '%s\x1f%s\n' "$0" "$*" >> "${EQ_STUB_LOG:-/dev/null}"
cmd=${1:-}; [ $# -eq 0 ] || shift
d=${EQ_STUB_DIGEST:-sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa}
pf=eq.invalid/eq-min:4.34.1-arm64; py=eq.invalid/eq-py-min:4.34.1-arm64
case "$cmd" in
  install)
    case " $* " in *" --dry-run "*) echo "eq-container: dry run (stub)"; exit "${EQ_STUB_DRY_RC:-0}";; esac
    rc=${EQ_STUB_RC:-0}
    case "$rc" in 0) st=ok;; 10) st=skipped;; *) st=failed;; esac
    mkdir -p "$EQ_STATE_DIR/results"
    { echo "EQ_CONTAINER_STATUS=$st"; echo "EQ_CONTAINER_STATUS_AT=2026-10-05T00:00:00Z"; echo "EQ_CONTAINER_STATUS_WHY=stub $st"
      echo "EQ_CONTAINER_STATUS_SET=profiles"; echo "EQ_CONTAINER_STATUS_PROFILES=core"
      echo "EQ_CONTAINER_STATUS_PINS_SHA256=7777777777777777777777777777777777777777777777777777777777777777"
      if [ "$st" = ok ]; then echo "EQ_CONTAINER_STATUS_VERIFIED=$pf@$d,$py@$d"; echo "EQ_CONTAINER_STATUS_PROBE=PASS"; fi
    } > "$EQ_STATE_DIR/status.env"
    if [ "$st" != skipped ]; then
      { echo "EQ_BACKEND=container"; echo "EQ_ISOLATION=container"
        echo "EQ_MIN_BOTH_TAG=$pf"; echo "EQ_MIN_BOTH_DIGEST=$d"; echo "EQ_MIN_PY_TAG=$py"; echo "EQ_MIN_PY_DIGEST=$d"
        echo "EQ_IMAGE=$pf@$d"; echo "EQ_CONTAINER_IMAGE_PF=$pf@$d"; echo "EQ_CONTAINER_IMAGE_CP=$py@$d"
        echo "EQ_CONTAINER_IMAGE_CR=$py@$d"
      } > "$EQ_STATE_DIR/image.env"
      tr=${EQ_STUB_TUNNEL:-PASS}
      if [ "$tr" != none ]; then
        for t in $pf $py; do
          f="$EQ_STATE_DIR/results/tunnel.$(printf '%s' "$t" | tr ':/@' '___').env"
          { echo "TUNNEL_RESULT=$tr"; echo "TUNNEL_AT=2026-10-05T00:00:01Z"; echo "TUNNEL_IMAGE=$t"; echo "TUNNEL_IMAGE_DIGEST=$d"
            if [ "$tr" = PASS ]; then echo "TUNNEL_FAILS=0"; else echo "TUNNEL_FAILS=2"; fi; } > "$f"
        done
      fi
    fi
    echo "eq-container: stub install -> $st (rc $rc)"
    exit "$rc" ;;
  print-env)
    [ "$(sed -n 's/^EQ_CONTAINER_STATUS=//p' "$EQ_STATE_DIR/status.env" 2>/dev/null)" = ok ] || exit 1
    echo "EQ_ISOLATION=${EQ_STUB_ISOLATION:-container}"
    echo "EQ_IMAGE=${EQ_STUB_PRINT_IMAGE-$pf@$d}"
    exit 0 ;;
esac
exit 2
