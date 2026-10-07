#!/usr/bin/env bash
# build.sh: build, check or remove the eq-docker images, built locally from the Dockerfiles in this directory. Never pushes.
#   ./build.sh [--set full|min|all] [--only NAME] [--keep-profile conservative|noprivate|slim] [--keep "EXT EXT .."]
#              [--yes] [--dry-run] [--force] [--no-cache] [--no-snapshot] [--json]
#   ./build.sh --profiles core,jvm,db [...]   build the images of TOOLS.toml profiles instead of a --set (`all` = every profile not
#                                             marked explicit; core is the minimum the item classes PF, CP, CR need)
#   ./build.sh --check     [--set ..]      verify docker, images and pins WITHOUT building (exit 0 ok, 11 not ok, 10 no docker)
#   ./build.sh --uninstall [--set ..] [--prune-cache] [--yes]   docker rmi the recorded tags, drop their records
#   ./build.sh --resolve-busybox [--write-pin]                  print (and optionally pin) the busybox sha256
#   ./build.sh --resolve-tools   [--write-pin]                  print (and optionally pin in TOOLS.toml) version + sha256 of busybox,
#                                                               bash, perl and jq from the pinned Debian snapshot (trust on first use)
# Sets: full = ./Dockerfile (Debian slim, eq-lean) | min = ./Dockerfile.minimal FROM scratch (min-lean min-py min-both) |
#       dl = min-lean + dl-lean (./Dockerfile.distroless, the distroless candidate) | all.
# NAME is one of: full min-lean min-py min-both dl-lean tc-node tc-rust tc-go tc-julia tc-haskell tc-jvm tc-pg tc-mongo.
# Default set: full (build-minimal.sh builds the minimal ones). Every image named in TOOLS.toml is built from the manifest: a
# PLACEHOLDER in a tool the image needs stops the build (exit 13), and the image carries the label eq.tools.sha256 (hash of its
# manifest entries) that verify-tools.sh --images compares.
# EQ_SELECT_LEAN / EQ_SELECT_PY (names, default min-lean / min-py when built, else full; with --profiles: min-both / min-py) choose
# which built images the summary image.env publishes as EQ_IMAGE / EQ_DOCKER_IMAGE_PF (lean) and EQ_DOCKER_IMAGE_CP, _CR (py):
# image IDs, digest-pinned form.
# Builds are idempotent: an image is skipped when its record in $EQ_STATE_DIR/images/NAME.env matches the image ID that is
# present and the hash of its inputs (Dockerfile, minimal/, project/, tc/, TOOLS.toml, target, keep profile). --force rebuilds.
# A keep-profile build (--keep-profile noprivate|slim|custom) of min-lean/min-both/dl-lean writes images/NAME-noprivate.env (etc.)
# next to the default record, so every tag built here is covered by a record (spike/probe/reverify refuse unrecorded images);
# EQ_SELECT_LEAN=min-lean-noprivate makes the summary image.env publish that record's image.
# Results: $EQ_STATE_DIR/images/NAME.env (KEY=VALUE), $EQ_STATE_DIR/image.env (summary), $EQ_STATE_DIR/image.json, build logs.
# Exit codes: see lib.sh (0 ok, 2 usage, 10 no docker, 11 image missing/stale, 12 build failed, 13 unresolved pin).
set -euo pipefail
here=$(cd "$(dirname "$0")" && pwd -P)
# --dry-run and --check change nothing: lib.sh then creates no state directory
for a in "$@"; do case "$a" in --dry-run|--check) export EQ_NO_STATE_WRITE=1;; esac; done
# shellcheck disable=SC1091
. "$here/lib.sh"
# shellcheck disable=SC1091
. "$here/tools.sh"
cd "$here"

SET=full; SET_GIVEN=0; PROFILES=""; ONLY=""; PROFILE=conservative; KEEP_CUSTOM=""; YES=0; DRY=0; FORCE=0; NOCACHE=0; NOSNAP=0; JSON=0
ACTION=build; PRUNE=0; WRITEPIN=0
while [ $# -gt 0 ]; do
  case "$1" in
    --set) SET=${2:?--set needs a value}; SET_GIVEN=1; shift;;
    --profiles) PROFILES=${2:?--profiles needs a list}; shift;;
    --only) ONLY=${2:?--only needs a name}; shift;;
    --keep-profile) PROFILE=${2:?}; shift;;
    --keep) KEEP_CUSTOM=${2:?}; PROFILE=custom; shift;;
    --yes|-y) YES=1;;
    --dry-run) DRY=1;;
    --force) FORCE=1;;
    --no-cache) NOCACHE=1;;
    --no-snapshot) NOSNAP=1;;
    --json) JSON=1;;
    --check) ACTION=check;;
    --uninstall) ACTION=uninstall;;
    --prune-cache) PRUNE=1;;
    --resolve-busybox) ACTION=busybox;;
    --resolve-tools) ACTION=tools;;
    --write-pin) WRITEPIN=1;;
    -h|--help) sed -n '2,29p' "$0"; exit 0;;
    *) echo "unknown argument: $1" >&2; exit 2;;
  esac
  shift
done

HAVE_TM=0
if [ -f "$here/TOOLS.toml" ]; then
  tm_load "$here/TOOLS.toml" || { echo "TOOLS.toml is unreadable (see above)" >&2; exit 2; }
  HAVE_TM=1
fi
if [ -n "$PROFILES" ]; then
  [ "$SET_GIVEN" = 0 ] || { echo "--set and --profiles exclude each other" >&2; exit 2; }
  [ "$HAVE_TM" = 1 ] || { echo "--profiles needs TOOLS.toml" >&2; exit 2; }
  pl=$(tm_expand_profiles "$PROFILES") || exit 2
  PROFILES=$(printf '%s' "$pl" | tr '\n' ' ' | sed 's/ *$//')
  NAMES=$(tm_profile_images "$PROFILES" | tr '\n' ' ' | sed 's/ *$//')
else
  case "$SET" in
    full) NAMES="full";; min) NAMES="min-lean min-py min-both";; dl) NAMES="min-lean dl-lean";;
    all) NAMES="full min-lean min-py min-both dl-lean";;
    *) echo "--set must be full, min, dl or all" >&2; exit 2;;
  esac
fi
if [ -n "$ONLY" ]; then
  case " $EQ_IMAGE_NAMES " in *" $ONLY "*) NAMES=$ONLY;; *) echo "--only: unknown image $ONLY" >&2; exit 2;; esac
fi
case "$PROFILE" in
  conservative) KEEP="olean olean.private olean.server ir ir.sig"; SUFFIX="";;
  noprivate)    KEEP="olean olean.server ir ir.sig"; SUFFIX="-noprivate";;
  slim)         KEEP="olean ir ir.sig"; SUFFIX="-slim";;
  custom)       KEEP=$KEEP_CUSTOM; SUFFIX="-custom";;
  *) echo "--keep-profile must be conservative, noprivate or slim" >&2; exit 2;;
esac

rn() { # record name: a keep-profile build of an image that carries Lean module files gets its own record (min-lean-noprivate), so it
  # never overwrites the default record, and every tag eq-docker built is covered by a record (lib.sh eq_require_image, F9)
  case "$1" in min-lean|min-both|dl-lean) echo "$1$SUFFIX";; *) echo "$1";; esac
}
sha256_of() { if command -v shasum >/dev/null 2>&1; then shasum -a 256 | cut -d' ' -f1; else sha256sum | cut -d' ' -f1; fi; }
img_file() { case "$1" in full) echo Dockerfile;; dl-lean) echo Dockerfile.distroless;; tc-*) echo Dockerfile.toolchains;; *) echo Dockerfile.minimal;; esac; }
img_target() {
  case "$1" in
    full) echo "";; min-lean) echo eq-lean-min;; min-py) echo eq-py-min;; min-both) echo eq-min;; dl-lean) echo eq-lean-dl;;
    tc-*) tm_get image "$1" target;;
  esac
}
img_tag() { # default tag (+ keep suffix for the lean images that carry Lean module files)
  local base; base=$(eq_img_default_tag "$1")
  case "$1" in min-lean|min-both|dl-lean) echo "${base}${SUFFIX}";; *) echo "$base";; esac
}
img_keep() { case "$1" in min-lean|min-both|dl-lean) echo "$KEEP";; *) echo "";; esac; }
in_manifest() { [ "$HAVE_TM" = 1 ] && tm_has image "$1"; }
inputs_hash() { # name
  local f df extra="" files
  df=$(img_file "$1")
  case "$1" in
    tc-*) files="$df TOOLS.toml tools.sh $(find tc -type f | LC_ALL=C sort)";;
    *) [ "$1" != dl-lean ] || extra="Dockerfile.minimal"
       files="$df $extra project/SHA256SUMS project/lakefile.toml project/lake-manifest.json project/lean-toolchain project/StackMathlib.lean project/StackMathlib/Basic.lean $(find minimal -type f | LC_ALL=C sort)"
       if in_manifest "$1"; then files="$files TOOLS.toml tools.sh"; fi;;
  esac
  {
    for f in $files; do
      printf 'FILE %s\n' "$f"; cat "$f"
    done
    printf 'TARGET %s\nKEEP %s\nNOSNAP %s\n' "$(img_target "$1")" "$(img_keep "$1")" "$NOSNAP"
    [ "$1" != dl-lean ] || printf 'DISTROLESS_BASE %s\n' "$(pin_value DISTROLESS_BASE)"
  } | sha256_of
}
pin_value() { sed -n "s/^$1=//p" PINS | head -n 1; }
needed_pins() { # name -> keys (dl-lean: only its own base; the Debian pins belong to the min-lean image it layers onto; tc-*: tool pins live in TOOLS.toml)
  local k="BASE_IMAGE APT_SNAPSHOT LEAN_VERSION LEAN_SHA256 UV_VERSION UV_SHA256 PYTHON_VERSION PBS_TAG PYTHON_SHA256 MATHLIB_REV"
  case "$1" in full) echo "$k";; dl-lean) echo "DISTROLESS_BASE";; tc-*) echo "BASE_IMAGE APT_SNAPSHOT";; *) echo "$k BUSYBOX_SHA256";; esac
}
# pins_check NAME: prints one line per problem, returns 0 when PINS and the Dockerfile agree and no pin is a placeholder
pins_check() {
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
# manifest_check NAME: the tools TOOLS.toml gives the image must all be pinned (verify-tools.sh --manifest); prints the PENDING/PROBLEM
# lines, returns verify-tools' code (0 ok, 2 invalid manifest, 13 a value is a placeholder); 0 for an image the manifest does not list
manifest_check() {
  local out rc=0
  in_manifest "$1" || return 0
  out=$(bash "$here/verify-tools.sh" --select "$1" --manifest 2>&1) || rc=$?
  [ "$rc" = 0 ] || printf '%s\n' "$out" | grep -E '^(PENDING|PROBLEM|TOOLS:)'
  return "$rc"
}
PIN_PLACEHOLDER=0

docker_state() { # sets DOCKER_OK=1/0 and DOCKER_WHY, never exits
  DOCKER_OK=0; DOCKER_WHY=""
  if ! eq_have docker; then DOCKER_WHY="docker CLI not found"; return 0; fi
  if ! docker info >/dev/null 2>&1; then DOCKER_WHY="docker daemon not reachable"; return 0; fi
  case "$(docker info --format '{{.Architecture}}' 2>/dev/null)" in aarch64|arm64) DOCKER_OK=1;; *) DOCKER_WHY="daemon architecture is not aarch64";; esac
}

# ------------------------------------------------------------------ --resolve-busybox
if [ "$ACTION" = busybox ]; then
  eq_need_docker
  log="$EQ_STATE_DIR/busybox-report.log"
  docker buildx build --platform linux/arm64 --progress=plain --provenance=false --sbom=false \
    --no-cache-filter busybox-report -f Dockerfile.minimal --target busybox-report . > "$log" 2>&1 || { tail -n 20 "$log" >&2; exit 12; }
  v=$(grep -o 'BUSYBOX_SHA256=[0-9a-f]\{64\}' "$log" | head -n 1 | cut -d= -f2)
  deb=$(grep -o 'BUSYBOX_DEB=[^ ]*' "$log" | head -n 1 | cut -d= -f2)
  [ -n "$v" ] || { echo "could not read the busybox sha256 from $log" >&2; exit 12; }
  echo "BUSYBOX_SHA256=$v"; echo "package: $deb (from the apt snapshot in PINS); log: $log"
  if [ "$WRITEPIN" = 1 ]; then
    for f in PINS Dockerfile.minimal; do
      if [ "$f" = PINS ]; then sed "s/^BUSYBOX_SHA256=.*/BUSYBOX_SHA256=$v/" "$f" > "$f.tmp"
      else sed "s/^ARG BUSYBOX_SHA256=.*/ARG BUSYBOX_SHA256=$v/" "$f" > "$f.tmp"; fi
      mv "$f.tmp" "$f"
    done
    [ "$HAVE_TM" = 0 ] || tm_set TOOLS.toml tool busybox sha256 "$v"
    echo "pinned in PINS, Dockerfile.minimal and TOOLS.toml (busybox sha256); review the diff and commit it. For the version and the other tools: --resolve-tools"
  else
    echo "to pin: re-run with --write-pin, or edit PINS, 'ARG BUSYBOX_SHA256=' in Dockerfile.minimal and the busybox entry of TOOLS.toml"
  fi
  exit 0
fi

# ------------------------------------------------------------------ --resolve-tools
if [ "$ACTION" = tools ]; then
  [ "$HAVE_TM" = 1 ] || { echo "--resolve-tools needs TOOLS.toml" >&2; exit 2; }
  eq_need_docker
  log="$EQ_STATE_DIR/tools-report.log"
  docker buildx build --platform linux/arm64 --progress=plain --provenance=false --sbom=false \
    --no-cache-filter tools-report -f Dockerfile.minimal --target tools-report . > "$log" 2>&1 || { tail -n 20 "$log" >&2; exit 12; }
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
  docker_state
  [ "$DOCKER_OK" = 1 ] || { echo "CHECK: SKIP ($DOCKER_WHY)"; exit 10; }
  rc=0
  for n in $NAMES; do
    tag=$(eq_img_tag "$n"); rec=$(eq_img_get "$n" EQ_IMAGE_ID)
    id=$(docker image inspect --format '{{.Id}}' "$tag" 2>/dev/null || true)
    st=ok; why=""
    if [ -z "$rec" ]; then st=MISSING; why="no record in $EQ_STATE_DIR/images/$n.env (never built here)"
    elif [ -z "$id" ]; then st=MISSING; why="image $tag not present"
    elif [ "$id" != "$rec" ]; then st=MISMATCH; why="image id $id != recorded $rec"
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
    printf 'CHECK %-9s %-8s %s %s\n' "$n" "$st" "${id:-none}" "$why"
    [ "$st" = ok ] || rc=11
  done
  [ $rc = 0 ] && echo "CHECK: OK" || echo "CHECK: NOT OK"
  exit $rc
fi

# ------------------------------------------------------------------ --uninstall
if [ "$ACTION" = uninstall ]; then
  # `--set all` on uninstall means every image eq-docker can have built, the extension images included (absent ones are just reported)
  [ "$SET" != all ] || [ -n "$PROFILES" ] || [ -n "$ONLY" ] || NAMES=$EQ_IMAGE_NAMES
  docker_state
  [ "$DOCKER_OK" = 1 ] || { echo "UNINSTALL: SKIP ($DOCKER_WHY); records kept"; exit 10; }
  if [ "$YES" != 1 ]; then
    if [ -t 0 ]; then printf 'Remove docker images %s and their records? [y/N] ' "$NAMES"; read -r ans; case "$ans" in y|Y|yes) ;; *) echo "aborted"; exit 2;; esac
    else echo "refusing to remove images without --yes" >&2; exit 2; fi
  fi
  for n in $NAMES; do
    tag=$(eq_img_tag "$n")
    if [ "$DRY" = 1 ]; then echo "would: docker rmi $tag; rm $EQ_STATE_DIR/images/$n.env"; continue; fi
    if docker image inspect "$tag" >/dev/null 2>&1; then docker rmi "$tag" >/dev/null && echo "removed $tag" || echo "could not remove $tag (in use?)" >&2; else echo "not present: $tag"; fi
    rm -f "$EQ_STATE_DIR/images/$n.env"
    # the keep-profile records of this image (min-lean-noprivate.env, ...): same removal
    for f in "$EQ_STATE_DIR/images/$n"-*.env; do
      [ -f "$f" ] || continue
      [ "$(sed -n 's/^EQ_IMAGE_NAME=//p' "$f" | head -n 1)" = "$n" ] || continue
      xt=$(sed -n 's/^EQ_IMAGE_TAG=//p' "$f" | head -n 1)
      if [ "$DRY" = 1 ]; then echo "would: docker rmi $xt; rm $f"; continue; fi
      if docker image inspect "$xt" >/dev/null 2>&1; then docker rmi "$xt" >/dev/null && echo "removed $xt" || echo "could not remove $xt (in use?)" >&2; else echo "not present: $xt"; fi
      rm -f "$f"
    done
  done
  [ "$DRY" = 1 ] || rm -f "$EQ_STATE_DIR/image.env" "$EQ_STATE_DIR/image.json"
  if [ "$PRUNE" = 1 ] && [ "$DRY" != 1 ]; then
    echo "pruning ALL unused build cache of the current builder (docker builder prune -f); it cannot be limited to these images"
    docker builder prune -f >/dev/null || echo "builder prune failed (non-fatal)" >&2
  fi
  echo "UNINSTALL: done"
  exit 0
fi

# ------------------------------------------------------------------ build
base=$(pin_value BASE_IMAGE)
docker_state
echo "== plan (state dir $EQ_STATE_DIR${PROFILES:+; profiles: $PROFILES})"
PLAN=""
for n in $NAMES; do
  tag=$(img_tag "$n"); rec=$(eq_img_get "$(rn "$n")" EQ_IMAGE_ID); recin=$(eq_img_get "$(rn "$n")" EQ_INPUTS_SHA256); cur=$(inputs_hash "$n")
  id=""; [ "$DOCKER_OK" = 1 ] && id=$(docker image inspect --format '{{.Id}}' "$tag" 2>/dev/null || true)
  if [ "$FORCE" != 1 ] && [ -n "$rec" ] && [ "$rec" = "$id" ] && [ "$recin" = "$cur" ] && [ "$(eq_img_get "$(rn "$n")" EQ_IMAGE_TAG)" = "$tag" ]; then act=skip; else act=build; fi
  printf '  %-9s %-34s %-5s inputs %s\n' "$n" "$tag" "$act" "$(printf '%s' "$cur" | cut -c1-12)"
  PLAN="$PLAN $n:$act"
done
if [ "$DOCKER_OK" != 1 ]; then echo "docker unavailable: $DOCKER_WHY"; [ "$DRY" = 1 ] && exit 0; exit 10; fi
for n in $NAMES; do
  PIN_PLACEHOLDER=0
  msg=$(pins_check "$n" || true)
  if [ -n "$msg" ]; then
    echo "$msg" >&2
    case "$msg" in *placeholder*) PIN_PLACEHOLDER=1;; esac
    if [ "$PIN_PLACEHOLDER" = 1 ]; then
      echo "unresolved pin: for BUSYBOX_SHA256 run ./build.sh --resolve-tools --write-pin; for DISTROLESS_BASE see the comment in PINS (docker buildx imagetools inspect ...); other keys: see PINS" >&2
      [ "$DRY" = 1 ] && continue
      exit 13
    fi
    [ "$DRY" = 1 ] || { echo "PINS and the Dockerfile disagree; fix before building" >&2; exit 2; }
  fi
  mrc=0; manifest_check "$n" >&2 || mrc=$?
  if [ "$mrc" = 13 ]; then
    echo "unresolved tool pin in TOOLS.toml for $n: distro packages (busybox, bash, perl, jq): ./build.sh --resolve-tools --write-pin; extension toolchains: the per-tool facts of TOOLCHAINS.md" >&2
    [ "$DRY" = 1 ] && continue
    exit 13
  elif [ "$mrc" != 0 ]; then
    echo "TOOLS.toml is invalid for $n (see above)" >&2
    [ "$DRY" = 1 ] && continue
    exit 2
  fi
done
[ "$DRY" = 1 ] && { echo "dry run: nothing built"; exit 0; }
# nothing to build still refreshes the summary files below (so EQ_SELECT_LEAN / EQ_SELECT_PY can re-select among built images)
NOBUILD=0
case "$PLAN" in *:build*) ;; *) echo "all images up to date (use --force to rebuild)"; NOBUILD=1;; esac

if [ "$NOBUILD" = 0 ] && [ "$YES" != 1 ]; then
  if [ -t 0 ]; then
    printf 'Build %s now? 10-40 min per cold build, several GB of disk (peak ~25-40 GB), network for the build only. [y/N] ' "$NAMES"
    read -r ans; case "$ans" in y|Y|yes) ;; *) echo "aborted"; exit 2;; esac
  else echo "refusing to start a long build non-interactively without --yes" >&2; exit 2; fi
fi

preflight_base() { # ref label hint
  echo "== preflight: $2 $1"
  if ! docker buildx imagetools inspect "$1" > "$EQ_STATE_DIR/base-inspect.txt" 2>&1; then
    cat "$EQ_STATE_DIR/base-inspect.txt" >&2
    echo "$2 not found by that reference. $3" >&2
    exit 12
  fi
  grep -q 'linux/arm64' "$EQ_STATE_DIR/base-inspect.txt" || { echo "$2 has no linux/arm64 variant" >&2; exit 12; }
}
need_debian=0; for n in $NAMES; do [ "$n" = dl-lean ] || need_debian=1; done
if [ "$NOBUILD" = 0 ] && [ "$need_debian" = 1 ]; then
  preflight_base "$base" "base image" "(the digest was copied from docker-library/repo-info, not the registry) Re-pin: docker buildx imagetools inspect debian:trixie-slim"
fi
for n in $NAMES; do
  if [ "$NOBUILD" = 0 ] && [ "$n" = dl-lean ]; then
    preflight_base "$(pin_value DISTROLESS_BASE)" "distroless base" "Re-pin: docker buildx imagetools inspect gcr.io/distroless/cc-debian13:nonroot"
  fi
done

snap=(); [ "$NOSNAP" = 1 ] && snap=(--build-arg APT_SNAPSHOT=)
extra=(); [ "$NOCACHE" = 1 ] && extra=(--no-cache)
for n in $NAMES; do
  case "$PLAN" in *" $n:build"*) ;; *) echo "== $n: up to date, skipped"; continue;; esac
  tag=$(img_tag "$n"); df=$(img_file "$n"); tg=$(img_target "$n"); keep=$(img_keep "$n")
  log="$EQ_STATE_DIR/build-$n.log"; md="$EQ_STATE_DIR/build-$n.metadata.json"
  targs=(); [ -n "$tg" ] && targs=(--target "$tg")
  kargs=(); [ -n "$keep" ] && [ "$n" != dl-lean ] && kargs=(--build-arg "KEEP_EXTS=$keep")
  largs=(); tsha=""
  if in_manifest "$n"; then tsha=$(tm_image_hash "$n"); largs=(--label "eq.tools.sha256=$tsha"); fi
  if [ "$n" = dl-lean ]; then
    rootfs_tag=$(img_tag min-lean)
    docker image inspect "$rootfs_tag" >/dev/null 2>&1 || { echo "dl-lean layers onto $rootfs_tag, which is not present: build min-lean first (./build-minimal.sh scratch)" >&2; exit 11; }
    kargs=(--build-arg "ROOTFS_IMAGE=$rootfs_tag" --build-arg "DISTROLESS_BASE=$(pin_value DISTROLESS_BASE)")
  fi
  echo "== build $n -> $tag (log $log)"
  rm -f "$md"; tb=$SECONDS
  set +e
  docker buildx build --platform linux/arm64 --load --provenance=false --sbom=false --progress=plain \
    --metadata-file "$md" ${snap[@]+"${snap[@]}"} ${extra[@]+"${extra[@]}"} ${targs[@]+"${targs[@]}"} ${kargs[@]+"${kargs[@]}"} ${largs[@]+"${largs[@]}"} \
    -t "$tag" -f "$df" . 2>&1 | tee "$log" | tail -n 5
  rc=${PIPESTATUS[0]}
  set -e
  [ "$rc" = 0 ] || { echo "BUILD FAILED for $n (rc $rc); see $log" >&2; exit 12; }
  bsec=$((SECONDS - tb))
  id=$(docker image inspect --format '{{.Id}}' "$tag")
  mdig=$(sed -n 's/.*"containerimage.digest": *"\([^"]*\)".*/\1/p' "$md" 2>/dev/null | head -n 1)
  prov=$(docker run --rm --pull never --network none --read-only --cap-drop ALL --security-opt no-new-privileges --user 10001:10001 "$tag" cat /opt/eq/PROVENANCE.txt 2>/dev/null || true)
  olean=$(printf '%s\n' "$prov" | sed -n 's/^olean_tree_sha256: //p' | head -n 1)
  mroot=$(docker run --rm --pull never --network none --read-only --cap-drop ALL --security-opt no-new-privileges --user 10001:10001 "$tag" cat /opt/eq/MANIFEST.root 2>/dev/null || true)
  size=$(docker image inspect --format '{{.Size}}' "$tag")
  {
    echo "EQ_IMAGE_NAME=$n"
    echo "EQ_RECORD_NAME=$(rn "$n")"
    echo "EQ_IMAGE_TAG=$tag"
    echo "EQ_IMAGE_ID=$id"
    echo "EQ_IMAGE_MANIFEST_DIGEST=$mdig"
    echo "EQ_INPUTS_SHA256=$(inputs_hash "$n")"
    echo "EQ_TOOLS_SHA256=$tsha"
    echo "EQ_OLEAN_TREE_SHA256=$olean"
    echo "EQ_MANIFEST_ROOT_SHA256=$mroot"
    echo "EQ_KEEP_EXTS=$keep"
    echo "EQ_KEEP_SUFFIX=$( [ -n "$keep" ] && echo "$SUFFIX" || true )"
    echo "EQ_NOSNAP=$NOSNAP"
    echo "EQ_IMAGE_BYTES=$size"
    echo "EQ_BUILD_SECONDS=$bsec"
    echo "EQ_BUILD_NOCACHE=$NOCACHE"
    echo "EQ_BACKEND=docker"
    echo "EQ_LIMITS=cpus=$EQ_CPUS memory=$EQ_MEMORY pids=$EQ_PIDS user=$EQ_USER"
    echo "EQ_BUILT_AT=$(date -u +%FT%TZ)"
    echo "EQ_DOCKER_SERVER=$(docker info --format '{{.ServerVersion}}' 2>/dev/null)"
  } > "$EQ_STATE_DIR/images/$(rn "$n").env.tmp"
  mv "$EQ_STATE_DIR/images/$(rn "$n").env.tmp" "$EQ_STATE_DIR/images/$(rn "$n").env"
  echo "   image id $id  size $(echo "$size" | awk '{printf "%.2f GB", $1/1e9}')  build ${bsec}s  olean_tree_sha256 ${olean:-n/a}"
done

# summary files for the installer / doctor / the harness flags. Selection: which built image serves PF (lean) and CP/CR (py).
# With --profiles the PF image is min-both when built: the harness runs the PF oracle (`uv run --script oracle.py`) inside the PF image
# (eq_harness.py oracle_isolated_classes PF, CP), so the PF image needs uv and python as well as Lean.
sel_lean=${EQ_SELECT_LEAN:-}; sel_py=${EQ_SELECT_PY:-}
lean_cands="min-lean full"; [ -z "$PROFILES" ] || lean_cands="min-both min-lean full"
if [ -z "$sel_lean" ]; then for c in $lean_cands; do [ -f "$EQ_STATE_DIR/images/$c.env" ] && { sel_lean=$c; break; }; done; fi
if [ -z "$sel_py" ]; then for c in min-py full; do [ -f "$EQ_STATE_DIR/images/$c.env" ] && { sel_py=$c; break; }; done; fi
{
  echo "EQ_BACKEND=docker"
  echo "EQ_ISOLATION=docker"
  [ -z "$PROFILES" ] || echo "EQ_DOCKER_PROFILES=$(printf '%s' "$PROFILES" | tr ' ' ',')"
  for n in $EQ_IMAGE_NAMES; do
    [ -f "$EQ_STATE_DIR/images/$n.env" ] || continue
    up=$(printf '%s' "$n" | tr '[:lower:]-' '[:upper:]_')
    echo "EQ_${up}_TAG=$(eq_img_get "$n" EQ_IMAGE_TAG)"
    echo "EQ_${up}_ID=$(eq_img_get "$n" EQ_IMAGE_ID)"
    echo "EQ_${up}_OLEAN_TREE_SHA256=$(eq_img_get "$n" EQ_OLEAN_TREE_SHA256)"
  done
  if [ -n "$sel_lean" ] && [ -f "$EQ_STATE_DIR/images/$sel_lean.env" ]; then
    echo "EQ_SELECT_LEAN=$sel_lean"
    echo "EQ_IMAGE=$(eq_img_get "$sel_lean" EQ_IMAGE_ID)"
    echo "EQ_DOCKER_IMAGE_PF=$(eq_img_get "$sel_lean" EQ_IMAGE_ID)"
  fi
  if [ -n "$sel_py" ] && [ -f "$EQ_STATE_DIR/images/$sel_py.env" ]; then
    echo "EQ_SELECT_PY=$sel_py"
    echo "EQ_DOCKER_IMAGE_CP=$(eq_img_get "$sel_py" EQ_IMAGE_ID)"
    echo "EQ_DOCKER_IMAGE_CR=$(eq_img_get "$sel_py" EQ_IMAGE_ID)"
  fi
} > "$EQ_STATE_DIR/image.env.tmp" && mv "$EQ_STATE_DIR/image.env.tmp" "$EQ_STATE_DIR/image.env"
{
  printf '{"backend":"docker","limits":{"cpus":"%s","memory":"%s","pids":"%s","user":"%s"},"images":{' "$EQ_CPUS" "$EQ_MEMORY" "$EQ_PIDS" "$EQ_USER"
  first=1
  for n in $EQ_IMAGE_NAMES; do
    [ -f "$EQ_STATE_DIR/images/$n.env" ] || continue
    [ $first = 1 ] || printf ','
    first=0
    printf '"%s":{"tag":"%s","id":"%s","manifest_digest":"%s","olean_tree_sha256":"%s","manifest_root_sha256":"%s","inputs_sha256":"%s","bytes":"%s","built_at":"%s"}' \
      "$n" "$(eq_img_get "$n" EQ_IMAGE_TAG)" "$(eq_img_get "$n" EQ_IMAGE_ID)" "$(eq_img_get "$n" EQ_IMAGE_MANIFEST_DIGEST)" \
      "$(eq_img_get "$n" EQ_OLEAN_TREE_SHA256)" "$(eq_img_get "$n" EQ_MANIFEST_ROOT_SHA256)" "$(eq_img_get "$n" EQ_INPUTS_SHA256)" \
      "$(eq_img_get "$n" EQ_IMAGE_BYTES)" "$(eq_img_get "$n" EQ_BUILT_AT)"
  done
  printf '}}\n'
} > "$EQ_STATE_DIR/image.json"
echo
echo "BUILD: OK  (records: $EQ_STATE_DIR/images/*.env, summary: $EQ_STATE_DIR/image.env, $EQ_STATE_DIR/image.json)"
[ "$JSON" = 1 ] && cat "$EQ_STATE_DIR/image.json"
exit 0
