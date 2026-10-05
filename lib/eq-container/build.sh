#!/usr/bin/env bash
# build.sh: build, check or remove the eq-container images, built locally with Apple `container build` (BuildKit) from the
# Dockerfiles in this directory. Never pushes, never pulls an eq image (only the pinned base, inside the builder).
#   ./build.sh [--set full|min|all] [--only NAME] [--keep-profile conservative|noprivate|slim] [--yes] [--dry-run] [--force]
#              [--no-cache] [--no-snapshot]
#   ./build.sh --profiles core,jvm [...]     build the images of TOOLS.toml profiles instead of a --set (`all` = every profile not
#                                            marked explicit; core is the minimum the item classes PF, CP, CR need)
#   ./build.sh --check     [--set ..|--profiles ..]   verify images, records and pins WITHOUT building (0 ok, 11 not ok, 10 no container)
#   ./build.sh --uninstall [--set ..|--profiles ..] [--yes]   container image delete the recorded tags, drop their records
#   ./build.sh --resolve-tools [--write-pin]      print (and optionally pin in TOOLS.toml/PINS) version + sha256 of the distro-package
#                                                 tools (busybox, bash, perl, jq; cc and ghc-link-libs for the toolchain images) from the
#                                                 pinned Debian snapshot (trust on first use)
# Sets: full = ./Dockerfile (Debian slim, eq-lean) | min = ./Dockerfile.minimal FROM scratch (min-lean min-py min-both) | all.
# Identity: each image's record holds its tag (under eq.invalid/, which no registry resolves) and the digest `container image
# inspect` reports right after the build; every run re-checks that digest (lib.sh eq_require_image).
# Idempotent: an image is skipped when its record matches the present digest and the hash of its inputs (Dockerfile, minimal/,
# project/, tc/, TOOLS.toml, target, keep profile). --force rebuilds.
# Results: $EQ_STATE_DIR/images/NAME.env, $EQ_STATE_DIR/image.env (summary: EQ_IMAGE, EQ_CONTAINER_IMAGE_PF/CP/CR = TAG@sha256:..).
# Builder size: EQ_BUILD_MEMORY (default 8G), EQ_BUILD_CPUS (default 4): the Mathlib stage needs more than the CLI's 2 GB default.
# Exit codes: see lib.sh (0 ok, 2 usage, 10 no container, 11 image missing/stale, 12 build failed, 13 unresolved pin).
set -euo pipefail
here=$(cd "$(dirname "$0")" && pwd -P)
for a in "$@"; do case "$a" in --dry-run|--check) export EQ_NO_STATE_WRITE=1;; esac; done
# shellcheck disable=SC1091
. "$here/lib.sh"
# shellcheck disable=SC1091
. "$here/tools.sh"
cd "$here"

SET=full; SET_GIVEN=0; PROFILES=""; ONLY=""; PROFILE=conservative; YES=0; DRY=0; FORCE=0; NOCACHE=0; NOSNAP=0
ACTION=build; WRITEPIN=0
need() { [ $# -ge 2 ] && [ -n "$2" ] || { echo "build.sh: $1 needs a value" >&2; exit 2; }; }
while [ $# -gt 0 ]; do
  case "$1" in
    --set) need "$@"; SET=$2; SET_GIVEN=1; shift;;
    --profiles) need "$@"; PROFILES=$2; shift;;
    --only) need "$@"; ONLY=$2; shift;;
    --keep-profile) need "$@"; PROFILE=$2; shift;;
    --yes|-y) YES=1;;
    --dry-run) DRY=1;;
    --force) FORCE=1;;
    --no-cache) NOCACHE=1;;
    --no-snapshot) NOSNAP=1;;
    --check) ACTION=check;;
    --uninstall) ACTION=uninstall;;
    --resolve-tools) ACTION=tools;;
    --write-pin) WRITEPIN=1;;
    -h|--help) sed -n '2,24p' "$0"; exit 0;;
    *) echo "build.sh: unknown argument: $1" >&2; exit 2;;
  esac
  shift
done
EQ_BUILD_MEMORY=${EQ_BUILD_MEMORY:-8G}; EQ_BUILD_CPUS=${EQ_BUILD_CPUS:-4}

tm_load "$here/TOOLS.toml" || { echo "TOOLS.toml is unreadable (see above)" >&2; exit 2; }
if [ -n "$PROFILES" ]; then
  [ "$SET_GIVEN" = 0 ] || { echo "--set and --profiles exclude each other" >&2; exit 2; }
  pl=$(tm_expand_profiles "$PROFILES") || exit 2
  PROFILES=$(printf '%s' "$pl" | tr '\n' ' ' | sed 's/ *$//')
  NAMES=$(tm_profile_images "$PROFILES" | tr '\n' ' ' | sed 's/ *$//')
else
  case "$SET" in
    full) NAMES="full";; min) NAMES="min-lean min-py min-both";; all) NAMES="full min-lean min-py min-both";;
    *) echo "--set must be full, min or all" >&2; exit 2;;
  esac
fi
if [ -n "$ONLY" ]; then
  case " $EQ_IMAGE_NAMES " in *" $ONLY "*) NAMES=$ONLY;; *) echo "--only: unknown image $ONLY" >&2; exit 2;; esac
fi
case "$PROFILE" in
  conservative) KEEP="olean olean.private olean.server ir ir.sig"; SUFFIX="";;
  noprivate)    KEEP="olean olean.server ir ir.sig"; SUFFIX="-noprivate";;
  slim)         KEEP="olean ir ir.sig"; SUFFIX="-slim";;
  *) echo "--keep-profile must be conservative, noprivate or slim" >&2; exit 2;;
esac

rn() { case "$1" in min-lean|min-both) echo "$1$SUFFIX";; *) echo "$1";; esac; }   # a keep-profile build gets its own record
img_file() { case "$1" in full) echo Dockerfile;; tc-*) echo Dockerfile.toolchains;; *) echo Dockerfile.minimal;; esac; }
img_target() {
  case "$1" in
    full) echo "";; min-lean) echo eq-lean-min;; min-py) echo eq-py-min;; min-both) echo eq-min;;
    tc-*) tm_get image "$1" target;;
  esac
}
img_tag() { local base; base=$(eq_img_default_tag "$1"); case "$1" in min-lean|min-both) echo "${base}${SUFFIX}";; *) echo "$base";; esac; }
img_keep() { case "$1" in min-lean|min-both) echo "$KEEP";; *) echo "";; esac; }
in_manifest() { tm_has image "$1"; }
inputs_hash() { # name
  local f df files
  df=$(img_file "$1")
  case "$1" in
    tc-*) files="$df TOOLS.toml tools.sh $(find tc -type f | LC_ALL=C sort)";;
    *) files="$df project/SHA256SUMS project/lakefile.toml project/lake-manifest.json project/lean-toolchain project/StackMathlib.lean project/StackMathlib/Basic.lean $(find minimal -type f | LC_ALL=C sort)"
       if in_manifest "$1"; then files="$files TOOLS.toml tools.sh"; fi;;
  esac
  {
    for f in $files; do printf 'FILE %s\n' "$f"; cat "$f"; done
    printf 'TARGET %s\nKEEP %s\nNOSNAP %s\nBACKEND container\n' "$(img_target "$1")" "$(img_keep "$1")" "$NOSNAP"
  } | tm_sha256_stdin
}
pin_value() { sed -n "s/^$1=//p" PINS | head -n 1; }
needed_pins() {
  local k="BASE_IMAGE APT_SNAPSHOT LEAN_VERSION LEAN_SHA256 UV_VERSION UV_SHA256 PYTHON_VERSION PBS_TAG PYTHON_SHA256 MATHLIB_REV"
  case "$1" in full) echo "$k";; tc-*) echo "BASE_IMAGE APT_SNAPSHOT";; *) echo "$k BUSYBOX_SHA256";; esac
}
PIN_PLACEHOLDER=0
pins_check() { # NAME: one line per problem; 0 when PINS and the Dockerfile agree and no pin is a placeholder
  local name=$1 df k pv dv bad=0
  df=$(img_file "$name")
  for k in $(needed_pins "$name"); do
    pv=$(pin_value "$k")
    case "$pv" in ""|UNSET|*TODO*) echo "pin $k is a placeholder in PINS"; PIN_PLACEHOLDER=1; bad=1; continue;; esac
    dv=$(sed -n "s/^ARG $k=//p" "$df" | head -n 1)
    case "$dv" in UNSET|*TODO*) echo "pin $k is a placeholder in $df"; PIN_PLACEHOLDER=1; bad=1; continue;; esac
    [ "$pv" = "$dv" ] || { echo "pin $k differs: PINS=$pv $df=$dv"; bad=1; }
  done
  return $bad
}
manifest_check() { # NAME: verify-tools.sh --manifest for one image (0 ok, 2 invalid, 13 a selected value is a placeholder)
  local out rc=0
  in_manifest "$1" || return 0
  out=$(bash "$here/verify-tools.sh" --select "$1" --manifest 2>&1) || rc=$?
  [ "$rc" = 0 ] || printf '%s\n' "$out" | grep -E '^(PENDING|PROBLEM|TOOLS:)' || true
  return "$rc"
}

# ------------------------------------------------------------------ --resolve-tools
if [ "$ACTION" = tools ]; then
  eq_need_container
  log="$EQ_STATE_DIR/tools-report.log"; : > "$log"
  for spec in Dockerfile.minimal:tools-report Dockerfile.toolchains:tc-tools-report; do
    eqc build --progress plain --no-cache --platform linux/arm64 -m "$EQ_BUILD_MEMORY" -c "$EQ_BUILD_CPUS" \
      -f "${spec%%:*}" --target "${spec#*:}" -t "eq.invalid/eq-report:$$" . >> "$log" 2>&1 || { tail -n 20 "$log" >&2; exit 12; }
    eqc image delete "eq.invalid/eq-report:$$" >/dev/null 2>&1 || true
  done
  lines=$(grep -o 'TOOL [a-z0-9-]* [^ ]* [0-9a-f]\{64\}' "$log" | LC_ALL=C sort -u || true)
  [ -n "$lines" ] || { echo "could not read the tool hashes from $log" >&2; exit 12; }
  snap=$(pin_value APT_SNAPSHOT)
  printf '%s\n' "$lines"
  if [ "$WRITEPIN" = 1 ]; then
    while read -r _ tname tver tsha; do
      tm_has tool "$tname" || { echo "$tname is not in TOOLS.toml: skipped" >&2; continue; }
      tm_set TOOLS.toml tool "$tname" version "$tver"
      tm_set TOOLS.toml tool "$tname" sha256 "$tsha"
      tm_set TOOLS.toml tool "$tname" checksum_source "Debian snapshot $snap, installed file hashed in the pinned builder (trust on first use: build.sh --resolve-tools)"
      if [ "$tname" = busybox ]; then
        for f in PINS Dockerfile.minimal; do
          if [ "$f" = PINS ]; then sed "s/^BUSYBOX_SHA256=.*/BUSYBOX_SHA256=$tsha/" "$f" > "$f.tmp"
          else sed "s/^ARG BUSYBOX_SHA256=.*/ARG BUSYBOX_SHA256=$tsha/" "$f" > "$f.tmp"; fi
          mv "$f.tmp" "$f"
        done
      fi
    done <<EOF
$lines
EOF
    echo "pinned in TOOLS.toml (and BUSYBOX_SHA256 in PINS and Dockerfile.minimal); review the package versions and the diff, then commit it"
  else
    echo "to pin: re-run with --write-pin (TOOLS.toml version, sha256 and checksum_source of these tools, and BUSYBOX_SHA256)"
  fi
  exit 0
fi

# ------------------------------------------------------------------ --check
if [ "$ACTION" = check ]; then
  eqc_state
  [ "$EQC_OK" = 1 ] || { echo "CHECK: SKIP ($EQC_WHY)"; exit 10; }
  rc=0
  for n in $NAMES; do
    tag=$(eq_img_tag "$n"); rec=$(eq_img_get "$n" EQ_IMAGE_DIGEST)
    dig=$(eqc_image_digest "$tag" || true)
    st=ok; why=""
    if [ -z "$rec" ]; then st=MISSING; why="no record in $EQ_STATE_DIR/images/$n.env (never built here)"
    elif [ -z "$dig" ]; then st=MISSING; why="image $tag not present"
    elif [ "$dig" != "$rec" ]; then st=MISMATCH; why="digest $dig != recorded $rec"
    else
      recin=$(eq_img_get "$n" EQ_INPUTS_SHA256)
      SUFFIX_SAVE=$SUFFIX; SUFFIX=$(eq_img_get "$n" EQ_KEEP_SUFFIX); KEEP_SAVE=$KEEP; KEEP=$(eq_img_get "$n" EQ_KEEP_EXTS)
      NOSNAP_SAVE=$NOSNAP; NOSNAP=$(eq_img_get "$n" EQ_NOSNAP); NOSNAP=${NOSNAP:-0}
      cur=$(inputs_hash "$n"); SUFFIX=$SUFFIX_SAVE; KEEP=$KEEP_SAVE; NOSNAP=$NOSNAP_SAVE
      [ "$recin" = "$cur" ] || { st=STALE; why="Dockerfile/minimal/project/manifest changed since the build (inputs hash differs)"; }
    fi
    PIN_PLACEHOLDER=0
    pc=$(pins_check "$n" || true)
    [ -z "$pc" ] || { [ "$st" = ok ] && st=PINS; why="$why $(printf '%s' "$pc" | tr '\n' ';')"; }
    mrc=0; mc=$(manifest_check "$n" 2>&1) || mrc=$?
    [ "$mrc" = 0 ] || { [ "$st" = ok ] && st=PINS; why="$why tools manifest: $(printf '%s' "$mc" | tr '\n' ';')"; }
    printf 'CHECK %-9s %-8s %s %s\n' "$n" "$st" "${dig:-none}" "$why"
    [ "$st" = ok ] || rc=11
  done
  [ $rc = 0 ] && echo "CHECK: OK" || echo "CHECK: NOT OK"
  exit $rc
fi

# ------------------------------------------------------------------ --uninstall
if [ "$ACTION" = uninstall ]; then
  [ "$SET" != all ] || [ -n "$PROFILES" ] || [ -n "$ONLY" ] || NAMES=$EQ_IMAGE_NAMES
  eqc_state
  [ "$EQC_OK" = 1 ] || { echo "UNINSTALL: SKIP ($EQC_WHY); records kept"; exit 10; }
  if [ "$YES" != 1 ]; then
    if [ -t 0 ]; then printf 'Remove images %s and their records? [y/N] ' "$NAMES"; read -r ans; case "$ans" in y|Y|yes) ;; *) echo "aborted"; exit 2;; esac
    else echo "refusing to remove images without --yes" >&2; exit 2; fi
  fi
  for n in $NAMES; do
    for f in "$EQ_STATE_DIR/images/$n.env" "$EQ_STATE_DIR/images/$n"-*.env; do
      [ -f "$f" ] || continue
      [ "$(sed -n 's/^EQ_IMAGE_NAME=//p' "$f" | head -n 1)" = "$n" ] || continue
      xt=$(sed -n 's/^EQ_IMAGE_TAG=//p' "$f" | head -n 1)
      if [ "$DRY" = 1 ]; then echo "would: container image delete $xt; rm $f"; continue; fi
      if eqc_image_digest "$xt" >/dev/null; then eqc image delete "$xt" >/dev/null && echo "removed $xt" || echo "could not remove $xt (in use?)" >&2
      else echo "not present: $xt"; fi
      rm -f "$f"
    done
  done
  [ "$DRY" = 1 ] || rm -f "$EQ_STATE_DIR/image.env"
  echo "UNINSTALL: done"
  exit 0
fi

# ------------------------------------------------------------------ build
eqc_state
echo "== plan (state dir $EQ_STATE_DIR${PROFILES:+; profiles: $PROFILES})"
PLAN=""
for n in $NAMES; do
  tag=$(img_tag "$n"); rec=$(eq_img_get "$(rn "$n")" EQ_IMAGE_DIGEST); recin=$(eq_img_get "$(rn "$n")" EQ_INPUTS_SHA256); cur=$(inputs_hash "$n")
  dig=""; [ "$EQC_OK" = 1 ] && dig=$(eqc_image_digest "$tag" || true)
  if [ "$FORCE" != 1 ] && [ -n "$rec" ] && [ "$rec" = "$dig" ] && [ "$recin" = "$cur" ] && [ "$(eq_img_get "$(rn "$n")" EQ_IMAGE_TAG)" = "$tag" ]; then act=skip; else act=build; fi
  printf '  %-9s %-40s %-5s inputs %s\n' "$n" "$tag" "$act" "$(printf '%s' "$cur" | cut -c1-12)"
  PLAN="$PLAN $n:$act"
done
if [ "$EQC_OK" != 1 ]; then echo "container unavailable: $EQC_WHY"; [ "$DRY" = 1 ] && exit 0; exit 10; fi
for n in $NAMES; do
  PIN_PLACEHOLDER=0
  msg=$(pins_check "$n" || true)
  if [ -n "$msg" ]; then
    echo "$msg" >&2
    case "$msg" in *placeholder*) PIN_PLACEHOLDER=1;; esac
    if [ "$PIN_PLACEHOLDER" = 1 ]; then
      echo "unresolved pin: for BUSYBOX_SHA256 run bash lib/eq-container/build.sh --resolve-tools --write-pin (trust on first use; review the versions); other keys: see PINS" >&2
      [ "$DRY" = 1 ] && continue
      exit 13
    fi
    [ "$DRY" = 1 ] || { echo "PINS and the Dockerfile disagree; fix before building" >&2; exit 2; }
  fi
  mrc=0; manifest_check "$n" >&2 || mrc=$?
  if [ "$mrc" = 13 ]; then
    echo "unresolved tool pin in TOOLS.toml for $n: distro packages: bash lib/eq-container/build.sh --resolve-tools --write-pin; other tools: their upstream checksum file (TOOLS.toml header)" >&2
    [ "$DRY" = 1 ] && continue
    exit 13
  elif [ "$mrc" != 0 ]; then
    echo "TOOLS.toml is invalid for $n (see above)" >&2
    [ "$DRY" = 1 ] && continue
    exit 2
  fi
done
[ "$DRY" = 1 ] && { echo "dry run: nothing built"; exit 0; }
NOBUILD=0
case "$PLAN" in *:build*) ;; *) echo "all images up to date (use --force to rebuild)"; NOBUILD=1;; esac
if [ "$NOBUILD" = 0 ] && [ "$YES" != 1 ]; then
  if [ -t 0 ]; then
    printf 'Build %s now? 10-40 min per cold build, several GB of disk, network for the build only. [y/N] ' "$NAMES"
    read -r ans; case "$ans" in y|Y|yes) ;; *) echo "aborted"; exit 2;; esac
  else echo "refusing to start a long build non-interactively without --yes" >&2; exit 2; fi
fi

snap=(); [ "$NOSNAP" = 1 ] && snap=(--build-arg APT_SNAPSHOT=)
extra=(); [ "$NOCACHE" = 1 ] && extra=(--no-cache)
for n in $NAMES; do
  case "$PLAN" in *" $n:build"*) ;; *) echo "== $n: up to date, skipped"; continue;; esac
  tag=$(img_tag "$n"); df=$(img_file "$n"); tg=$(img_target "$n"); keep=$(img_keep "$n")
  log="$EQ_STATE_DIR/build-$n.log"
  targs=(); [ -n "$tg" ] && targs=(--target "$tg")
  kargs=(); [ -n "$keep" ] && kargs=(--build-arg "KEEP_EXTS=$keep")
  largs=(); tsha=""
  if in_manifest "$n"; then tsha=$(tm_image_hash "$n"); largs=(--label "eq.tools.sha256=$tsha"); fi
  echo "== build $n -> $tag (log $log)"
  tb=$SECONDS
  set +e
  # base image digests in the Dockerfiles (FROM ...@sha256:) are verified by the builder itself; nothing else is pulled
  eqc build --progress plain --platform linux/arm64 -m "$EQ_BUILD_MEMORY" -c "$EQ_BUILD_CPUS" \
    ${snap[@]+"${snap[@]}"} ${extra[@]+"${extra[@]}"} ${targs[@]+"${targs[@]}"} ${kargs[@]+"${kargs[@]}"} ${largs[@]+"${largs[@]}"} \
    -t "$tag" -f "$df" . > "$log" 2>&1
  rc=$?
  set -e
  tail -n 5 "$log"
  [ "$rc" = 0 ] || { echo "BUILD FAILED for $n (rc $rc); see $log" >&2; exit 12; }
  bsec=$((SECONDS - tb))
  dig=$(eqc_image_digest "$tag") || { echo "BUILD of $n produced no readable digest for $tag (container image inspect)" >&2; exit 12; }
  {
    echo "EQ_IMAGE_NAME=$n"
    echo "EQ_RECORD_NAME=$(rn "$n")"
    echo "EQ_IMAGE_TAG=$tag"
    echo "EQ_IMAGE_DIGEST=$dig"
    echo "EQ_INPUTS_SHA256=$(inputs_hash "$n")"
    echo "EQ_TOOLS_SHA256=$tsha"
    echo "EQ_KEEP_EXTS=$keep"
    echo "EQ_KEEP_SUFFIX=$( [ -n "$keep" ] && echo "$SUFFIX" || true )"
    echo "EQ_NOSNAP=$NOSNAP"
    echo "EQ_BUILD_SECONDS=$bsec"
    echo "EQ_BUILD_NOCACHE=$NOCACHE"
    echo "EQ_BACKEND=container"
    echo "EQ_LIMITS=cpus=$EQ_CPUS memory=$EQ_MEMORY nproc=$EQ_NPROC user=$EQ_USER"
    echo "EQ_BUILT_AT=$(date -u +%FT%TZ)"
    echo "EQ_CONTAINER_VERSION=$(eqc --version 2>/dev/null | head -n 1)"
  } > "$EQ_STATE_DIR/images/$(rn "$n").env.tmp"
  mv "$EQ_STATE_DIR/images/$(rn "$n").env.tmp" "$EQ_STATE_DIR/images/$(rn "$n").env"
  echo "   digest $dig  build ${bsec}s"
done

# summary for the installer, doctor and the harness flags: which built image serves PF (lean; with --profiles min-both, since
# the harness runs the PF oracle with uv and python in the PF image) and CP/CR (py). Values are TAG@sha256:DIGEST.
sel_lean=${EQ_SELECT_LEAN:-}; sel_py=${EQ_SELECT_PY:-}
lean_cands="min-lean full"; [ -z "$PROFILES" ] || lean_cands="min-both min-lean full"
if [ -z "$sel_lean" ]; then for c in $lean_cands; do [ -f "$EQ_STATE_DIR/images/$c.env" ] && { sel_lean=$c; break; }; done; fi
if [ -z "$sel_py" ]; then for c in min-py full; do [ -f "$EQ_STATE_DIR/images/$c.env" ] && { sel_py=$c; break; }; done; fi
{
  echo "EQ_BACKEND=container"
  echo "EQ_ISOLATION=container"
  [ -z "$PROFILES" ] || echo "EQ_CONTAINER_PROFILES=$(printf '%s' "$PROFILES" | tr ' ' ',')"
  for n in $EQ_IMAGE_NAMES; do
    [ -f "$EQ_STATE_DIR/images/$n.env" ] || continue
    up=$(printf '%s' "$n" | tr '[:lower:]-' '[:upper:]_')
    echo "EQ_${up}_TAG=$(eq_img_get "$n" EQ_IMAGE_TAG)"
    echo "EQ_${up}_DIGEST=$(eq_img_get "$n" EQ_IMAGE_DIGEST)"
  done
  if [ -n "$sel_lean" ] && [ -f "$EQ_STATE_DIR/images/$sel_lean.env" ]; then
    echo "EQ_SELECT_LEAN=$sel_lean"
    echo "EQ_IMAGE=$(eq_pinned_ref "$sel_lean")"
    echo "EQ_CONTAINER_IMAGE_PF=$(eq_pinned_ref "$sel_lean")"
  fi
  if [ -n "$sel_py" ] && [ -f "$EQ_STATE_DIR/images/$sel_py.env" ]; then
    echo "EQ_SELECT_PY=$sel_py"
    echo "EQ_CONTAINER_IMAGE_CP=$(eq_pinned_ref "$sel_py")"
    echo "EQ_CONTAINER_IMAGE_CR=$(eq_pinned_ref "$sel_py")"
  fi
} > "$EQ_STATE_DIR/image.env.tmp" && chmod 600 "$EQ_STATE_DIR/image.env.tmp" && mv "$EQ_STATE_DIR/image.env.tmp" "$EQ_STATE_DIR/image.env"
echo
echo "BUILD: OK  (records: $EQ_STATE_DIR/images/*.env, summary: $EQ_STATE_DIR/image.env)"
exit 0
